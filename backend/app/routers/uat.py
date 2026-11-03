# SPDX-License-Identifier: BUSL-1.1
"""ES9 UAT 验收报告路由（共享域，前缀 /api/projects/{project_id}/uat-reports）。

- 域归属：OSS 共享域（app/routers/），不进 _COMMERCIAL_ROUTERS；
  导出端点内按 settings.EDITION == "community" 判边界。
- operationId：逐个显式命名（BUG-001 教训），前缀 uat。
- 响应：统一 ok() 包壳 {code:0,data,message}（对齐 projects_quality 现例）。
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, ok
from ..models import Project, Report, ReportShare
from ..services import uat_report as ur
from ..services import uat_render as uw
from ..services import uat_sign as us
from ..services.audit import write_audit
from ..services.export_helpers import FMT_EXT
from ..services.notifications import emit
from ..services.quality_gate import validate_gate_rules
from .projects_ext import _load_project   # 项目加载+租户校验现例（L133）

router = APIRouter(prefix="/api", tags=["uat"])


class CreateUatBody(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=50)
    criteria_override: list[dict] | None = None      # Step2 覆写整表（validate_gate_rules 口径）
    contract_no: str | None = Field(default=None, max_length=64)
    defect_disposals: dict[int, dict] | None = None  # {defect_id: {deadline, waiver}}


class SignBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    verdict: Literal["PASSED", "CONDITIONAL", "REJECTED"] | None = None   # REJECTED=公开通道拒收
    note: str | None = Field(default=None, max_length=2000)
    share_token: str | None = None                   # customer 免登录通道用


class RejectBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class ResampleBody(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=50)
    criteria_override: list[dict] | None = None
    contract_no: str | None = None
    defect_disposals: dict[int, dict] | None = None


# ---------------------------------------------------------------------------
# 文件内私有 helper
# ---------------------------------------------------------------------------
def _now_cn() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _load_uat_report(db: Session, report_id: int, auth: AuthContext) -> Report:
    """按 id 取 UAT 报告；subtype 非 UAT / 已删除 / 跨租户 → 404（不泄露存在性）。"""
    rep = db.get(Report, report_id)
    if rep is None or rep.report_subtype != "UAT" or rep.deleted_at is not None \
            or rep.tenant_id != auth.tenant_id:
        raise BizError("ES9-UAT-0006", "验收报告不存在或无权访问", http_status=404)
    return rep


def _chain(db: Session, rep: Report) -> list[dict]:
    """版本链：沿 parent_report_id 逐级取 {id, report_no, version, status}（防环上限 50）。"""
    out: list[dict] = []
    seen = {rep.id}
    pid = rep.parent_report_id
    while pid is not None and pid not in seen and len(out) < 50:
        seen.add(pid)
        p = db.get(Report, pid)
        if p is None or p.deleted_at is not None:
            break
        out.append({
            "id": p.id, "report_no": p.report_no,
            "version": (p.content or {}).get("uat_version"),
            "status": (p.acceptance or {}).get("status", "DRAFT"),
        })
        pid = p.parent_report_id
    return out


def _detail_out(db: Session, rep: Report) -> dict:
    """详情出参：content（8 节）+ acceptance（读侧防御校验）+ 版本链。"""
    acc = dict(rep.acceptance or {})
    err_msg = us.validate_acceptance(acc)
    if err_msg:
        # 数据被外部破坏（理论不可达）——报警不静默
        raise BizError("ES9-UAT-0007", f"验收状态数据异常：{err_msg}", http_status=500)
    return {
        "id": rep.id,
        "report_no": rep.report_no,
        "title": rep.title,
        "project_id": rep.project_id,
        "uat_version": (rep.content or {}).get("uat_version"),
        "acceptance": acc,
        "content": rep.content or {},
        "parent_report_id": rep.parent_report_id,
        "chain": _chain(db, rep),
        "created_by": rep.created_by,
        "generated_by": rep.generated_by,
        "generated_at": rep.generated_at.isoformat() if rep.generated_at else None,
    }


def _list_out(rep: Report, project_name: str | None = None) -> dict:
    """列表精简行：version/status/verdict 均从 content/acceptance 读（表无独立版本列）。"""
    acc = rep.acceptance or {}
    row = {
        "id": rep.id,
        "report_no": rep.report_no,
        "title": rep.title,
        "project_id": rep.project_id,
        "version": (rep.content or {}).get("uat_version"),
        "status": acc.get("status", "DRAFT"),
        "verdict": acc.get("verdict"),
        "finalized_at": acc.get("finalized_at"),
        "created_at": rep.created_at.isoformat() if rep.created_at else None,
    }
    if project_name is not None:
        row["project_name"] = project_name
    return row


@router.get("/uat-reports", operation_id="listAllUatReports", response_model=dict)
async def list_all_uat_reports(
    project_id: int | None = Query(None, description="不传=本租户全部项目汇总"),
    status: str | None = Query(None, pattern="^(DRAFT|VENDOR_SIGNED|FINALIZED|REJECTED)$"),
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    auth=Depends(require_permission("report", "read")),
):
    """跨项目验收报告汇总（全局列表页用）：可按项目/签核状态过滤，带项目名。"""
    if project_id is not None:
        _load_project(db, project_id, auth)
    q = (
        db.query(Report, Project.name)
        .outerjoin(Project, Project.id == Report.project_id)
        .filter(Report.report_subtype == "UAT",
                Report.tenant_id == auth.tenant_id,
                Report.deleted_at.is_(None))
    )
    if project_id is not None:
        q = q.filter(Report.project_id == project_id)
    if status:
        # JSON 文本比较（PG →> ；sqlite json_extract），方言安全
        q = q.filter(Report.acceptance["status"].as_string() == status)
    q = q.order_by(Report.id.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total,
               "items": [_list_out(r, project_name=pname) for r, pname in rows]})


def _validate_override(override: list[dict] | None) -> None:
    """criteria_override 严格校验（与 gate_rules 同口径）；ES-GATE-* 统一映射 ES9-UAT-0001。"""
    if not override:
        return
    try:
        validate_gate_rules(override)  # 返回规范化 JSON 串，非法抛 BizError
    except BizError as e:
        raise BizError("ES9-UAT-0001", f"验收标准覆写非法：{e.message}", http_status=400) from e


def _parse_json_param(raw: str | None, name: str):
    """GET query 里的 JSON 串参数（candidates 覆写用）；非法 JSON → ES9-UAT-0001。"""
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise BizError("ES9-UAT-0001", f"参数 {name} 必须是合法 JSON", http_status=400) from None


def _persist_new(db: Session, auth: AuthContext, project_id: int, payload: dict,
                 parent_report_id: int | None) -> Report:
    """create/resample 共用落库段：编号、版本回填、DRAFT 状态机初始化。"""
    project = _load_project(db, project_id, auth)
    payload["sections"]["s1_overview"]["report_no"] = ur.next_uat_no(db, project.code)
    payload["sections"]["s1_overview"]["project_name"] = project.name
    rep = Report(
        project_id=project_id, tenant_id=auth.tenant_id,
        report_no=payload["sections"]["s1_overview"]["report_no"],
        # reports.task_id NOT NULL（存量契约不动）：以纳入任务首个作为来源任务留痕
        task_id=payload["task_ids"][0],
        task_no=payload["sections"]["s1_overview"]["task_nos"][0],
        title=f"UAT 验收报告 {payload['sections']['s1_overview']['report_no']}",
        report_type="FULL", report_subtype="UAT", format="json",
        status="DONE", content=payload,
        acceptance={"status": "DRAFT", "verdict": None, "note": "",
                    "signer_vendor": None, "signer_customer": None, "finalized_at": None},
        parent_report_id=parent_report_id,
        summary={"total_cases": payload["sections"]["s4_results"]["total_cases"],
                 "agg_pass_rate": payload["sections"]["s4_results"]["agg_pass_rate"]},
        generated_by=auth.username, created_by=auth.user_id,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(rep)
    db.flush()
    db.commit()
    return rep


def _audit(db: Session, auth: AuthContext, action: str, rep: Report,
           detail: dict | None = None) -> None:
    """标准审计埋点（module=reports，对齐 quality_export 现例）。"""
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action=action.upper(),
        module="reports",
        result="SUCCESS",
        detail=json.dumps({"report_id": rep.id, "report_no": rep.report_no, **(detail or {})},
                          ensure_ascii=False),
    )
    db.commit()


# ---------------------------------------------------------------------------
# M3 事件（notifications.emit：异常内部吞掉，不影响主流程）
# ---------------------------------------------------------------------------
def _emit_finalized(db: Session, rep: Report) -> None:
    emit(rep.tenant_id, "uat.finalized",
         {"dedup_key": f"uat:{rep.id}:finalized",
          "title": f"验收报告 {rep.report_no} 双方签核完成",
          "report_id": rep.id, "url": f"/projects/{rep.project_id}/uat"},
         severity="MEDIUM")


def _emit_reject(db: Session, rep: Report) -> None:
    emit(rep.tenant_id, "uat.rejected",
         {"dedup_key": f"uat:{rep.id}:rejected",
          "title": f"验收报告 {rep.report_no} 被拒收",
          "report_id": rep.id, "url": f"/projects/{rep.project_id}/uat"},
         severity="HIGH")


# ---------------------------------------------------------------------------
# 端点（登录态）
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/uat-reports/candidates",
            operation_id="uatCandidates", response_model=dict)
async def uat_candidates(
    project_id: int,
    task_ids: str = Query(..., description="逗号分隔任务 id，如 1,2,3"),
    criteria_override: str | None = Query(None, description="JSON 数组（向导 Step2 覆写整表，可选）"),
    contract_no: str | None = Query(None, max_length=64),
    defect_disposals: str | None = Query(None, description='JSON 对象 {"<defect_id>": {"deadline","waiver"}}（可选）'),
    db: Session = Depends(get_db),
    auth=Depends(require_permission("report", "read")),
):
    """§1-§7 只读预览（不落库）。向导 Step3 用；校验与生成同口径（ES9-UAT-0001 前置暴露）。

    覆写参数与 create 同口径：传入后预览即后端权威重算（推荐2），Step3 所见即所签。
    """
    _load_project(db, project_id, auth)
    try:
        ids = [int(x) for x in task_ids.split(",") if x.strip()]
    except ValueError:
        raise BizError("ES9-UAT-0006", "task_ids 必须是逗号分隔的数字", http_status=400) from None
    override = _parse_json_param(criteria_override, "criteria_override")
    disposals = _parse_json_param(defect_disposals, "defect_disposals")
    _validate_override(override)
    payload = ur.build_uat_payload(
        db, project_id, auth.tenant_id, ids,
        criteria_override=override,
        contract_no=contract_no,
        defect_disposals=disposals,
    )
    return ok({"preview": True, "payload": payload})


@router.post("/projects/{project_id}/uat-reports",
             operation_id="createUatReport", status_code=201, response_model=dict)
async def create_uat_report(
    project_id: int, body: CreateUatBody,
    db: Session = Depends(get_db),
    auth=Depends(require_permission("report", "read")),
):
    """生成 UAT 报告（DRAFT）。落库：subtype=UAT、acceptance.status=DRAFT、content=固化快照。"""
    _load_project(db, project_id, auth)
    _validate_override(body.criteria_override)   # 先校验覆写，再进聚合
    payload = ur.build_uat_payload(
        db, project_id, auth.tenant_id, body.task_ids,
        criteria_override=body.criteria_override,
        contract_no=body.contract_no,
        defect_disposals=body.defect_disposals,
    )
    payload["uat_version"] = 1
    rep = _persist_new(db, auth, project_id, payload, parent_report_id=None)
    _audit(db, auth, "uat.create", rep)
    return ok(_detail_out(db, rep))


@router.get("/projects/{project_id}/uat-reports",
            operation_id="listUatReports", response_model=dict)
async def list_uat_reports(
    project_id: int,
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    auth=Depends(require_permission("report", "read")),
):
    """列表（subtype=UAT，按项目倒序），每行带版本号/状态机/结论。"""
    _load_project(db, project_id, auth)
    q = (db.query(Report)
         .filter(Report.project_id == project_id,
                 Report.report_subtype == "UAT",
                 Report.tenant_id == auth.tenant_id,
                 Report.deleted_at.is_(None))
         .order_by(Report.id.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_list_out(r) for r in rows]})


@router.get("/projects/{project_id}/uat-reports/{report_id}",
            operation_id="getUatReport", response_model=dict)
async def get_uat_report(project_id: int, report_id: int,
                         db: Session = Depends(get_db),
                         auth=Depends(require_permission("report", "read"))):
    rep = _load_uat_report(db, report_id, auth)
    return ok(_detail_out(db, rep))


@router.post("/projects/{project_id}/uat-reports/{report_id}/sign",
             operation_id="signUatReport", response_model=dict)
async def sign_uat_report(project_id: int, report_id: int, body: SignBody,
                          db: Session = Depends(get_db),
                          auth=Depends(require_permission("report", "read"))):
    """供应商签署（登录态）。客户签署走免登录通道 /api/public/uat-sign（见下）。"""
    rep = _load_uat_report(db, report_id, auth)
    us.sign(db, rep, "vendor", name=body.name, verdict=body.verdict, note=body.note)
    _audit(db, auth, "uat.sign_vendor", rep)
    return ok(_detail_out(db, rep))


@router.post("/projects/{project_id}/uat-reports/{report_id}/reject",
             operation_id="rejectUatReport", response_model=dict)
async def reject_uat_report(project_id: int, report_id: int, body: RejectBody,
                            db: Session = Depends(get_db),
                            auth=Depends(require_permission("report", "read"))):
    rep = _load_uat_report(db, report_id, auth)
    us.reject(db, rep, "vendor", name=body.name, reason=body.reason)
    _audit(db, auth, "uat.reject", rep)
    _emit_reject(db, rep)                      # M3 事件
    return ok(_detail_out(db, rep))


@router.post("/projects/{project_id}/uat-reports/{report_id}/resample",
             operation_id="resampleUatReport", status_code=201, response_model=dict)
async def resample_uat_report(project_id: int, report_id: int, body: ResampleBody,
                              db: Session = Depends(get_db),
                              auth=Depends(require_permission("report", "read"))):
    """基于旧版重生成 v{n+1}：旧报告必须终态（REJECTED/FINALIZED），新报告 parent 链留痕。"""
    old = _load_uat_report(db, report_id, auth)
    st = (old.acceptance or {}).get("status", "DRAFT")
    if st not in ("REJECTED", "FINALIZED"):
        raise BizError("ES9-UAT-0002", "仅终态报告可重生成新版本", http_status=409)
    _validate_override(body.criteria_override)
    payload = ur.build_uat_payload(
        db, project_id, auth.tenant_id, body.task_ids,
        criteria_override=body.criteria_override,
        contract_no=body.contract_no,
        defect_disposals=body.defect_disposals,
    )
    payload["uat_version"] = ur.next_version(db, old.id)
    rep = _persist_new(db, auth, project_id, payload, parent_report_id=old.id)
    _audit(db, auth, "uat.resample", rep, {"parent_report_id": old.id})
    return ok(_detail_out(db, rep))


@router.get("/projects/{project_id}/uat-reports/{report_id}/export",
            operation_id="exportUatReport")
async def export_uat_report(
    project_id: int, report_id: int,
    format: str = Query("pdf", pattern="^(pdf|word|md|html)$"),
    db: Session = Depends(get_db),
    auth=Depends(require_permission("report", "export")),
):
    """导出。community 形态仅 md/html（403 ES9-UAT-0004）；DRAFT 自动水印（§3.4 渲染层保证）。"""
    rep = _load_uat_report(db, report_id, auth)
    if settings.EDITION == "community" and format in ("pdf", "word"):
        raise BizError("ES9-UAT-0004", "当前版本仅支持 Markdown / HTML 导出", http_status=403)
    acc = rep.acceptance or {}
    watermark = acc.get("status") == "DRAFT"
    payload = rep.content or {}
    try:
        if format == "md":
            data = uw.render_uat_md(payload, acc, watermark).encode("utf-8")
            media = "text/markdown; charset=utf-8"
        elif format == "html":
            data = uw.render_uat_html(payload, acc, watermark).encode("utf-8")
            media = "text/html; charset=utf-8"
        elif format == "word":
            data = uw.render_uat_word(payload, acc, watermark)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            data = uw.render_uat_pdf(payload, acc, watermark)
            media = "application/pdf"
    except ImportError as e:
        raise BizError("ES9-UAT-0007", f"导出依赖缺失（{format}）：{e}", http_status=500) from e
    except Exception as e:  # noqa: BLE001 —— 对齐 quality_export：失败 500 不静默降级
        raise BizError("ES9-UAT-0008", f"验收报告导出失败：{str(e)[:200]}", http_status=500) from e
    _audit(db, auth, "uat.export", rep, {"format": format, "watermark": watermark})
    fname = f"UAT_{rep.report_no}_{_now_cn().strftime('%Y%m%d')}.{FMT_EXT[format]}"
    return Response(
        content=data, media_type=media,
        headers={
            "Content-Disposition": (
                f"attachment; filename=UAT_{rep.report_no}.{FMT_EXT[format]}; "
                f"filename*=UTF-8''{quote(fname)}"
            )
        },
    )


@router.post("/projects/{project_id}/uat-reports/{report_id}/share",
             operation_id="shareUatReport", response_model=dict)
async def share_uat_report(project_id: int, report_id: int,
                           db: Session = Depends(get_db),
                           auth=Depends(require_permission("report", "read"))):
    """生成/复用客户签署通道（report_shares 既有治理；token=secrets.token_urlsafe(32) 现例）。

    同一报告未过期且启用的 token 直接复用（幂等）；单次使用：签署后置 is_enabled=False。
    """
    rep = _load_uat_report(db, report_id, auth)
    if (rep.acceptance or {}).get("status") != "VENDOR_SIGNED":
        raise BizError("ES9-UAT-0002", "供应商签署后方可发出客户链接", http_status=409)
    share = _find_or_create_share(db, rep, auth)
    db.commit()
    return ok({
        "share_token": share.share_token,
        "url": f"/s/uat/{share.share_token}",
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,  # 推荐4：到期提醒依据
    })


# ---------------------------------------------------------------------------
# ReportShare 通道 helper（写法照 commercial/routers/report_shares.py 现例；
# ReportShare 无 purpose/used_at 列 → 语义映射：purpose=uat_sign ⇒ 该 UAT 报告关联的唯一 share；
# 单次使用 ⇒ 签署后 is_enabled=False）
# ---------------------------------------------------------------------------
def _find_or_create_share(db: Session, rep: Report, auth: AuthContext) -> ReportShare:
    now = datetime.now(timezone.utc)
    share = (
        db.query(ReportShare)
        .filter(ReportShare.report_id == rep.id,
                ReportShare.tenant_id == rep.tenant_id,
                ReportShare.is_enabled.is_(True))
        .order_by(ReportShare.id.desc())
        .first()
    )
    if share is not None and _share_usable(share, now):
        return share
    share = ReportShare(
        report_id=rep.id,
        share_token=secrets.token_urlsafe(32),
        password_hash=None,
        expires_at=now + timedelta(days=30),
        view_count=0,
        max_views=None,
        is_enabled=True,
        tenant_id=rep.tenant_id,
        created_by=auth.user_id,
    )
    db.add(share)
    db.flush()
    return share


def _share_usable(share: ReportShare, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not share.is_enabled:
        return False
    if share.expires_at is not None:
        exp = share.expires_at if share.expires_at.tzinfo else share.expires_at.replace(tzinfo=timezone.utc)
        if exp < now:
            return False
    if share.max_views is not None and share.view_count >= share.max_views:
        return False
    return True


def _load_share_for_public(db: Session, share_token: str) -> tuple[ReportShare, Report]:
    """免登录通道 token 校验：无效/过期/已使用 → ES9-UAT-0005；报告必须是未删除的 UAT。"""
    share = db.query(ReportShare).filter(ReportShare.share_token == share_token).first()
    if share is None:
        raise BizError("ES9-UAT-0005", "签署链接无效", http_status=400)
    if not _share_usable(share):
        raise BizError("ES9-UAT-0005", "签署链接已过期或已使用", http_status=400)
    rep = db.get(Report, share.report_id)
    if rep is None or rep.report_subtype != "UAT" or rep.deleted_at is not None:
        raise BizError("ES9-UAT-0005", "签署链接已失效", http_status=400)
    return share, rep


def _public_out(rep: Report) -> dict:
    """客户预览：8 节只读裁剪版（不含版本链/创建人等内部字段）。"""
    return {
        "report_no": rep.report_no,
        "title": rep.title,
        "uat_version": (rep.content or {}).get("uat_version"),
        "acceptance": rep.acceptance or {},
        "content": rep.content or {},
    }


# ---------- 免登录客户签署通道（对齐 ShareReport.jsx 的公开端点范式） ----------
@router.post("/public/uat-sign/{share_token}", operation_id="publicSignUat", response_model=dict)
async def public_sign_uat(share_token: str, body: SignBody,
                          db: Session = Depends(get_db)):
    """客户免登录签署/拒收：token 校验（有效性 + 单次使用）。不走 require_permission。"""
    share, rep = _load_share_for_public(db, share_token)
    if body.verdict == "REJECTED":               # 前端「拒收」按钮走本端点
        us.reject(db, rep, "customer", name=body.name, reason=body.note or "")
        _emit_reject(db, rep)
    else:
        us.sign(db, rep, "customer", name=body.name, share_token=share_token)
        if (rep.acceptance or {}).get("status") == "FINALIZED":
            _emit_finalized(db, rep)             # M3 事件
    share.is_enabled = False                     # 单次使用失效（设计方案 §6 语义映射）
    write_audit(db, user_id=None, username=f"客户:{body.name}",
                tenant_id=rep.tenant_id, action="UAT.SIGN_CUSTOMER", module="reports",
                result="SUCCESS",
                detail=json.dumps({"report_id": rep.id, "report_no": rep.report_no},
                                  ensure_ascii=False))
    db.commit()
    return ok({"status": (rep.acceptance or {}).get("status")})


@router.get("/public/uat-sign/{share_token}/report", operation_id="publicGetUat", response_model=dict)
async def public_get_uat(share_token: str, db: Session = Depends(get_db)):
    """客户预览：只读 payload + acceptance（token 治理同上，浏览计数 +1）。"""
    share, rep = _load_share_for_public(db, share_token)
    share.view_count = (share.view_count or 0) + 1
    db.commit()
    return ok(_public_out(rep))
