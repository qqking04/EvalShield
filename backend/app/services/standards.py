# -*- coding: utf-8 -*-
"""ES9-P-11：TC260 标准对照配置加载（监管数字唯一入口，代码 0 硬编码）。

规格锚点（《优化9详细设计方案》§4.3.1）：
- 配置文件 ``deploy/standards/tc260.yaml``：
  ``standard:{code,name,version,source}`` + ``mapping:[{category_code,
  bank_category,min_questions,pass_threshold,tested_engines}]`` +
  ``statement:{delivery_qualifier,self_consistency_only}``。
- **代码中不得出现任何题量/百分比字面量**；阈值字段默认 ``null``，由交付人
  依据 GB/T 45654 / TC260-003 原文填入。CI lint 与交付链经
  ``assert_thresholds_configured()`` 阻断未配置阈值的交付件生成。
- ``GET /api/meta/standards`` 透出（meta_router，前端对照页消费）。
- 路径解析：环境变量 ``STANDARDS_CONFIG`` > <repo>/deploy/standards/tc260.yaml
  （自本文件向上回溯定位仓库根，不新增 config.py 键）。

D-15（ES9）：默认 **fail-fast** —— 配置缺失/损坏时 ``load_standards()`` 直接
raise ``ES-STD-001``（422）拒绝交付；仅当显式配置
``STD_ALLOW_DEGRADED=true`` 才回退降级结构（mapping 为空 → 覆盖矩阵不判缺口
灰显、``GET /api/meta/standards`` 回 ``available:false``）。交付链
``assert_thresholds_configured`` 始终 raise（防"无阈值默认通过"）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, authenticate_request, require_any_permission
from ..errors import BizError, ok
from .audit import write_audit

# ---------------------------------------------------------------- 路径解析

_ENV_KEY = "STANDARDS_CONFIG"


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = (os.environ.get(_ENV_KEY) or getattr(settings, "STANDARDS_CONFIG", "") or "").strip()
    if env:
        out.append(Path(env))
    # 自本文件向上回溯找 deploy/standards/tc260.yaml（backend/app/services → repo 根）
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "deploy" / "standards" / "tc260.yaml"
        if cand.exists():
            out.append(cand)
            break
    return out


# ---------------------------------------------------------------- 加载与缓存

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"mtime": None, "path": None, "data": None}


def _empty() -> dict[str, Any]:
    return {
        "loaded": False,
        "available": False,
        "path": None,
        "standard": {},
        "mapping": [],
        "dimensions": [],
        "refusal_thresholds": {},
        "statement": {},
        "error": None,
    }


def _service_type(bank_category: str) -> str | None:
    """A.5 服务类型编码：bank_category 的 ``@{服务类型}`` 后缀解析（§5.1/§5.2）。"""
    _, sep, tail = bank_category.rpartition("@")
    return tail if sep and tail else None


def _norm_row(row: dict[str, Any], dimension: dict[str, Any] | None) -> dict[str, Any]:
    """展平单个 sub（两级）或旧单层类别行（§5.2 双读统一行形状）。"""
    bank = str(row.get("bank_category") or "")
    if dimension is None:  # 旧单层：无维度归属，监管口径按 True 保守处理
        dim_code: str | None = None
        dim_name: str | None = None
        regulatory = True
    else:
        dim_code = str(dimension.get("dimension_code") or "") or None
        dim_name = str(dimension.get("dimension_name") or "") or None
        regulatory = bool(dimension.get("regulatory", True))
    return {
        "category_code": str(row.get("sub_code") or row.get("category_code") or ""),
        "dimension_code": dim_code,
        "dimension_name": dim_name,
        "regulatory": regulatory,
        "bank_category": bank,
        "service_type": _service_type(bank),
        "min_questions": row.get("min_questions"),
        "pass_threshold": row.get("pass_threshold"),
        "tested_engines": [
            str(e) for e in (row.get("tested_engines") or []) if str(e).strip()
        ],
    }


def _parse(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("tc260.yaml 顶层必须是映射")
    standard = raw.get("standard") or {}
    mapping = raw.get("mapping") or []
    statement = raw.get("statement") or {}
    refusal = raw.get("refusal_thresholds") or {}
    if not isinstance(mapping, list):
        raise ValueError("mapping 必须是列表")
    norm_map: list[dict[str, Any]] = []
    dimensions: list[dict[str, Any]] = []
    for row in mapping:
        if not isinstance(row, dict):
            continue
        if row.get("dimension_code"):  # 两级：维度行 → 展平 subs[]
            dim = {
                "dimension_code": str(row["dimension_code"]),
                "dimension_name": str(row.get("dimension_name") or ""),
                "regulatory": bool(row.get("regulatory", True)),
            }
            dimensions.append(dim)
            for sub in row.get("subs") or []:
                if isinstance(sub, dict) and sub.get("sub_code"):
                    norm_map.append(_norm_row(sub, dim))
        elif row.get("category_code"):  # 旧单层兼容（双读，§5.2）
            norm_map.append(_norm_row(row, None))
    return {
        "loaded": True,
        "available": True,
        "path": str(path),
        "standard": {
            "code": str(standard.get("code") or ""),
            "name": str(standard.get("name") or ""),
            "version": str(standard.get("version") or ""),
            "source": str(standard.get("source") or ""),
        },
        "mapping": norm_map,
        "dimensions": dimensions,
        "refusal_thresholds": {
            "refuse_pass_rate_min": (refusal or {}).get("refuse_pass_rate_min"),
            "false_refuse_rate_max": (refusal or {}).get("false_refuse_rate_max"),
            "reviewed_by": (refusal or {}).get("reviewed_by"),
            "basis": (refusal or {}).get("basis"),
        },
        "statement": {
            "delivery_qualifier": str(statement.get("delivery_qualifier") or ""),
            "self_consistency_only": str(statement.get("self_consistency_only") or ""),
        },
        "error": None,
    }


def load_standards(force: bool = False) -> dict[str, Any]:
    """加载并缓存配置（按 mtime 失效）。

    D-15：默认 fail-fast —— 配置缺失/损坏时直接 raise ``ES-STD-001``（422）
    拒绝交付；仅显式 ``STD_ALLOW_DEGRADED=true`` 才返回降级结构
    （``loaded=False``、``available=False``、``error`` 说明原因）。
    """
    with _LOCK:
        cands = _candidates()
        path = cands[0] if cands else None
        mtime = path.stat().st_mtime if path and path.exists() else None
        if not force and _CACHE["data"] is not None and _CACHE["mtime"] == mtime and (
            _CACHE["path"] == str(path) if path else _CACHE["path"] is None
        ):
            data = _CACHE["data"]
        elif path is None or mtime is None:
            data = _empty()
            data["error"] = f"标准对照配置缺失（查找顺序：环境变量 {_ENV_KEY} → deploy/standards/tc260.yaml）"
        else:
            try:
                data = _parse(path)
            except Exception as exc:  # noqa: BLE001 —— 损坏口径按开关决定降级/拒绝
                data = _empty()
                data["path"] = str(path)
                data["error"] = f"标准对照配置解析失败：{exc}"
        _CACHE.update({"mtime": mtime, "path": str(path) if path else None, "data": data})
        if not data["loaded"] and not settings.STD_ALLOW_DEGRADED:
            raise BizError(
                "ES-STD-001",
                f"标准对照配置未就绪（D-15 fail-fast）：{data['error'] or '未知原因'}",
                http_status=422,
            )
        return data


# ---------------------------------------------------------------- 查询接口


def standard_meta() -> dict[str, Any]:
    """标准元信息（版本快照用：delivery_packages.standards_ver）。"""
    data = load_standards()
    std = dict(data["standard"])
    std["loaded"] = data["loaded"]
    return std


def standards_version() -> str | None:
    """版本快照字符串（code/version），未加载返回 None。"""
    data = load_standards()
    if not data["loaded"] or not data["standard"].get("code"):
        return None
    return f"{data['standard']['code']}@{data['standard'].get('version') or '-'}"


def statement_of(key: str) -> str:
    """限定语文案（delivery_qualifier / self_consistency_only），缺失返回空串。"""
    return load_standards()["statement"].get(key) or ""


def mapping_rows() -> list[dict[str, Any]]:
    return load_standards()["mapping"]


def category_map() -> dict[str, dict[str, Any]]:
    """bank_category → mapping 行（覆盖矩阵缺口判定入口）。"""
    return {row["bank_category"]: row for row in mapping_rows() if row["bank_category"]}


def engine_codes_for_category(bank_category: str) -> list[str]:
    """类别的可执行覆盖引擎清单；未配置的类别返回 []（灰显不判缺口）。"""
    row = category_map().get(bank_category)
    return list(row["tested_engines"]) if row else []


def dimension_rows() -> list[dict[str, Any]]:
    """两级结构：按维度分组（含 subs 展平行）。旧单层配置返回 []。"""
    data = load_standards()
    out: list[dict[str, Any]] = []
    for dim in data.get("dimensions") or []:
        subs = [r for r in data["mapping"] if r["dimension_code"] == dim["dimension_code"]]
        out.append({**dim, "subs": subs})
    return out


def missing_threshold_items() -> list[str]:
    """阈值未配置的**监管**子类（regulatory=True）；扩展视角不参与 ES-STD-003（§5.2）。"""
    return [
        row["category_code"]
        for row in mapping_rows()
        if row.get("regulatory", True)
        and (row["min_questions"] is None or row["pass_threshold"] is None)
    ]


def missing_threshold_categories() -> list[str]:
    """阈值未配置（min_questions 或 pass_threshold 为 null）的类别编码列表。

    §5.2 别名转调：只统计 regulatory=True 子类（旧单层行 regulatory 保守为 True，
    行为与升级前一致）。
    """
    return missing_threshold_items()


def refusal_thresholds() -> dict[str, Any]:
    """§5.2d 拒答双阈值块（展示态；未核定返回四键 null 形态，不阻断）。"""
    data = load_standards()
    ref = data.get("refusal_thresholds") or {}
    return {
        "refuse_pass_rate_min": ref.get("refuse_pass_rate_min"),
        "false_refuse_rate_max": ref.get("false_refuse_rate_max"),
        "reviewed_by": ref.get("reviewed_by"),
        "basis": ref.get("basis"),
    }


def default_quotas(category_codes: list[str] | None = None) -> dict[str, int]:
    """按子类抽题的默认配额（优化12 §4.5）：返回 {bank_category: min_questions}。

    - 数字只读已核定的 tc260.yaml（ES9-P-11 铁律，禁代码内联）；
    - min_questions 为 null（未核定）的类别不进入返回值，
      由发起端显式提示"该类别阈值未核定，不可用于正式交付"。
    - category_codes 为 None 时返回全部已核定类别；否则按 category_code 过滤。
    """
    wanted = set(category_codes) if category_codes else None
    out: dict[str, int] = {}
    for row in mapping_rows():
        if wanted is not None and row["category_code"] not in wanted:
            continue
        if row.get("min_questions") is None or not row.get("bank_category"):
            continue
        out[row["bank_category"]] = int(row["min_questions"])
    return out


def min_questions_for_category(bank_category: str) -> int | None:
    """子类核定最小题量（QUOTA_ABOVE_MIN 复校验用）；未配置返回 None。"""
    row = category_map().get(bank_category)
    v = (row or {}).get("min_questions")
    return int(v) if v is not None else None


# ---------------------------------------------------------------- presets（优化12 §8.1/§8.1a）

_PRESET_FILE = "presets.yaml"
_PRESETS_LOCK = threading.Lock()
_PRESETS_CACHE: dict[str, Any] = {"mtime": None, "path": None, "data": None}


def _preset_candidates() -> list[Path]:
    """presets.yaml 路径：STANDARDS_CONFIG 同目录优先，否则回溯 deploy/standards/。"""
    out: list[Path] = []
    env = (os.environ.get(_ENV_KEY) or getattr(settings, "STANDARDS_CONFIG", "") or "").strip()
    if env:
        out.append(Path(env).parent / _PRESET_FILE)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "deploy" / "standards" / _PRESET_FILE
        if cand.exists():
            out.append(cand)
            break
    return out


def _presets_empty(error: str | None) -> dict[str, Any]:
    return {"presets": [], "presets_error": error}


def _derive_presets(raw: list[Any]) -> list[dict[str, Any]]:
    """按预设条目派生 calibrated / min_bank_questions / engine_union 引擎并集。"""
    rows = mapping_rows()
    by_dim: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_dim.setdefault(str(r.get("dimension_code") or ""), []).append(r)
    quotas = default_quotas()  # {bank_category: min_questions}（仅已核定）
    out: list[dict[str, Any]] = []
    for p in raw:
        if not isinstance(p, dict) or not p.get("preset_code"):
            continue
        dim_order = [str(d) for d in (p.get("dimension_order") or []) if str(d).strip()]
        include_reg_only = bool(p.get("include_regulatory_only", False))
        subs: list[dict[str, Any]] = []
        for dc in dim_order:
            for r in by_dim.get(dc, []):
                if include_reg_only and not r.get("regulatory", True):
                    continue
                subs.append(r)
        uncalibrated = [
            r["category_code"] for r in subs
            if r.get("regulatory", True)
            and (r["min_questions"] is None or r["pass_threshold"] is None)
        ]
        min_bank = sum(
            quotas.get(r["bank_category"], 0)
            for r in subs if r.get("regulatory", True) and r.get("bank_category")
        )
        engines: list[str] = []
        if str(p.get("engine_union") or "") == "from_tested_engines":
            seen: set[str] = set()
            for r in subs:
                for e in r["tested_engines"]:
                    if e not in seen:
                        seen.add(e)
                        engines.append(e)
        out.append({
            "preset_code": str(p["preset_code"]),
            "name": str(p.get("name") or ""),
            "dimension_order": dim_order,
            "include_regulatory_only": include_reg_only,
            "exclude_categories": [str(c) for c in (p.get("exclude_categories") or [])],
            "engine_union": str(p.get("engine_union") or ""),
            "run_purpose": str(p.get("run_purpose") or "STANDARD"),
            "calibrated": not uncalibrated,
            "uncalibrated_items": uncalibrated,
            # 派生注入（yaml 源不写，§8.1a）：官方子类核定 min_questions 之和
            "min_bank_questions": int(min_bank),
            "engines": engines,
        })
    return out


def load_presets(force: bool = False) -> dict[str, Any]:
    """加载评估预设（§8.1a 三情形降级：缺失/解析失败→presets:[]+presets_error，
    不拖挂 /meta/standards 整体；子类阈值未核定→该预设 calibrated:false）。"""
    import logging

    with _PRESETS_LOCK:
        cands = _preset_candidates()
        path = cands[0] if cands else None
        mtime = path.stat().st_mtime if path and path.exists() else None
        if not force and _PRESETS_CACHE["data"] is not None and (
            _PRESETS_CACHE["mtime"] == mtime
            and (_PRESETS_CACHE["path"] == str(path) if path else _PRESETS_CACHE["path"] is None)
        ):
            return _PRESETS_CACHE["data"]
        if path is None or mtime is None:
            data = _presets_empty(
                f"评估预设配置缺失（查找顺序：环境变量 {_ENV_KEY} 同目录 → deploy/standards/{_PRESET_FILE}）")
        else:
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict) or not isinstance(raw.get("presets"), list):
                    raise ValueError("presets.yaml 顶层需为含 presets 列表的映射")
                data = {"presets": _derive_presets(raw["presets"])}
            except Exception as exc:  # noqa: BLE001 —— 降级不拖挂 meta，仅 WARN
                logging.getLogger(__name__).warning("presets.yaml 解析失败：%s（%s）", exc, path)
                data = _presets_empty(f"评估预设解析失败：{exc}（{path}）")
        _PRESETS_CACHE.update({"mtime": mtime, "path": str(path) if path else None, "data": data})
        return data


def assert_thresholds_configured() -> None:
    """交付链门禁：任何阈值为 null 或 mapping 为空 → 422 阻断出交付件。

    防 AI/文档口径冒充监管口径（§4.3.1 CI lint 同断言语义）。
    """
    data = load_standards()
    if not data["loaded"]:
        raise BizError("ES-STD-001", f"标准对照配置未就绪：{data['error'] or '未知原因'}", http_status=422)
    if not data["mapping"]:
        raise BizError("ES-STD-002", "标准对照 mapping 为空，禁止生成交付件", http_status=422)
    missing = missing_threshold_categories()
    if missing:
        raise BizError(
            "ES-STD-003",
            "监管阈值未配置（min_questions/pass_threshold 为 null），"
            "请依据 GB/T 45654 / TC260-003 原文填入 tc260.yaml 后重试："
            + ", ".join(missing),
            http_status=422,
        )


# ---------------------------------------------------------------- 透出路由


class ThresholdCalibrateBody(BaseModel):
    """PUT /api/standards/thresholds 请求体（§6.3）。"""

    target: str = Field("threshold", pattern="^(threshold|refusal)$")
    sub_code: str | None = Field(None, max_length=64)
    min_questions: int | None = None
    pass_threshold: float | None = None
    refuse_pass_rate_min: float | None = None
    false_refuse_rate_max: float | None = None
    reviewer: str = Field(..., min_length=1, max_length=128)
    basis: str = Field(..., min_length=1, max_length=512)
    dry_run: bool = False


def build_meta_router():
    """meta 薄路由：GET /api/meta/standards（只读）+ PUT /api/standards/thresholds（核定写入）。

    PUT 权限（§6.3 v2.2）：监管数字写入仅限 SUPER_ADMIN（交付负责人）角色硬校验，
    不新建权限码。**部署假设**：直接写磁盘 yaml，仅适用单实例部署（与离线 License
    交付形态一致）；多实例/容器化必须改"配置提交"通道，禁止并发调用。
    """
    from fastapi import APIRouter, Depends

    from . import standards_thresholds as svc

    router = APIRouter()

    @router.get("/meta/standards", summary="TC260/GBT45654 标准对照集（ES9-P-11）")
    async def get_standards(
        auth: AuthContext = Depends(
            require_any_permission(("case", "read"), ("eval", "read"))
        ),
    ):
        data = load_standards()
        presets = load_presets()
        return ok(
            {
                "loaded": data["loaded"],
                "available": data["available"],
                "error": data["error"],
                "standard": data["standard"],
                "mapping": data["mapping"],
                "dimensions": dimension_rows(),
                "refusal_thresholds": refusal_thresholds(),
                "statement": data["statement"],
                "thresholds_missing": missing_threshold_categories(),
                "presets": presets["presets"],
                **({"presets_error": presets["presets_error"]}
                   if presets.get("presets_error") else {}),
            }
        )

    @router.put("/standards/thresholds", summary="监管阈值人工核定写入（仅超管，ES9-P-11）")
    async def calibrate_thresholds(
        body: ThresholdCalibrateBody,
        request: Request,
        auth: AuthContext = Depends(authenticate_request),
        db: Session = Depends(get_db),
    ):
        if not auth.is_super_admin:
            raise BizError("ES-BIZ-PERM-0001", "阈值核定仅限超级管理员（交付负责人）账号",
                           http_status=403)
        from . import standards_thresholds as svc

        payload = body.model_dump(exclude={"dry_run"})
        before = {
            r["category_code"]: (r["min_questions"], r["pass_threshold"])
            for r in mapping_rows()
        }
        try:
            if body.dry_run:
                target = svc.resolve_target()
                text = target.read_text(encoding="utf-8")
                if body.target == "refusal":
                    svc.validate_and_patch_refusal(
                        text,
                        refuse_pass_rate_min=body.refuse_pass_rate_min,
                        false_refuse_rate_max=body.false_refuse_rate_max,
                        reviewer=body.reviewer, basis=body.basis)
                else:
                    svc.validate_and_patch(
                        text, code=body.sub_code or "",
                        min_questions=body.min_questions,
                        pass_threshold=body.pass_threshold,
                        reviewer=body.reviewer, basis=body.basis)
                return ok({"dry_run": True, "changed": False,
                           "code": body.sub_code or "REFUSAL"})
            res = svc.calibrate(payload)
        except ValueError as exc:
            raise BizError("ES-BIZ-STD-0001", str(exc), http_status=422) from exc
        except svc.ThresholdLockBusy as exc:
            raise BizError("ES-BIZ-STD-0002", str(exc), http_status=409) from exc

        after = {
            r["category_code"]: (r["min_questions"], r["pass_threshold"])
            for r in mapping_rows()
        }
        changed_key = res.get("code")
        detail = (
            f"target={body.target} code={changed_key} "
            f"改前={before.get(changed_key) if changed_key in before else '新增'} "
            f"改后={after.get(changed_key) if changed_key in after else '见yaml'} "
            f"refusal={body.refuse_pass_rate_min}/{body.false_refuse_rate_max} "
            f"basis={body.basis}"
        )
        write_audit(
            db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
            action=("standards.refusal.calibrate" if body.target == "refusal"
                    else "standards.threshold.calibrate"),
            module="standards", request=request, detail=detail,
            status_code=200,
        )
        return ok({
            "dry_run": False,
            "changed": res["changed"],
            "code": res["code"],
            "thresholds_missing": missing_threshold_categories(),
        })

    return router
