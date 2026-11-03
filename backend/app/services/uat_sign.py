# SPDX-License-Identifier: BUSL-1.1
"""ES9 UAT 签核状态机。所有 acceptance 字段改写必须经由本模块（唯一写入口）。

不变量：
1. FINALIZED / REJECTED 是终态 —— 一切改写 409（ES9-UAT-0002）；
2. DRAFT 只能 vendor 签；VENDOR_SIGNED 只能 customer 签或 reject；
3. verdict=CONDITIONAL ⇒ note 必填（ES9-UAT-0003）；
4. 双签齐时重算 report_hash 并写入尾注（固化）。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from ..models import Report
from ..errors import BizError
from .uat_report import compute_report_hash

STATE: dict[str, dict[str, str]] = {
    "DRAFT": {"vendor": "VENDOR_SIGNED", "reject": "REJECTED"},
    "VENDOR_SIGNED": {"customer": "FINALIZED", "reject": "REJECTED"},
    "FINALIZED": {},   # 终态
    "REJECTED": {},    # 终态（整改走 resample 出新版本）
}

VERDICTS = {"PASSED", "CONDITIONAL", "REJECTED"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign(db: Session, report: Report, party: Literal["vendor", "customer"],
         name: str, verdict: str | None = None, note: str | None = None,
         share_token: str | None = None) -> Report:
    """供应商/客户签署。report 必须是 subtype=UAT 且未删除；越界一律 BizError。"""
    acc = dict(report.acceptance or {})
    status = acc.get("status", "DRAFT")
    if not STATE.get(status) or party not in STATE[status]:
        raise BizError("ES9-UAT-0002", "报告当前状态不允许该签署动作（已锁定或顺序错误）",
                       http_status=409)
    if not name or not name.strip():
        raise BizError("ES9-UAT-0003", "签署人姓名必填", http_status=400)

    if party == "vendor":
        # 供应商签署时定结论（默认=§5 建议值，可覆写）
        v = (verdict or "PASSED").upper()
        if v not in {"PASSED", "CONDITIONAL"}:
            raise BizError("ES9-UAT-0003", "供应商签署结论仅允许 PASSED/CONDITIONAL",
                           http_status=400)
        if v == "CONDITIONAL" and not (note or "").strip():
            raise BizError("ES9-UAT-0003", "有条件通过必须填写豁免说明（note）",
                           http_status=400)
        acc.update({"verdict": v, "note": (note or "").strip() if v == "CONDITIONAL" else "",
                    "signer_vendor": {"name": name.strip(), "signed_at": _now()}})
    else:
        # 客户经 share_token 通道签署（设计方案 §3.3：非平台用户）
        acc.update({"signer_customer": {"name": name.strip(),
                                        "share_token": share_token or "",
                                        "signed_at": _now()}})

    acc["status"] = STATE[status][party]
    if acc["status"] == "FINALIZED":
        acc["finalized_at"] = _now()
        _finalize_hash(report, acc)
    report.acceptance = acc  # JSONB 整体赋值（避免原地 mutate 不脏化）
    db.flush()
    return report


def reject(db: Session, report: Report, party: Literal["vendor", "customer"],
           name: str, reason: str) -> Report:
    """拒收：REJECTED 终态 + 理由必填（进 §8 note 留痕）。"""
    acc = dict(report.acceptance or {})
    status = acc.get("status", "DRAFT")
    if "reject" not in STATE.get(status, {}):
        raise BizError("ES9-UAT-0002", "报告当前状态不允许拒收（已锁定）", http_status=409)
    if not reason or not reason.strip():
        raise BizError("ES9-UAT-0003", "拒收理由必填", http_status=400)
    acc.update({"status": "REJECTED", "verdict": "REJECTED",
                "note": reason.strip(),
                "rejected_by": {"party": party, "name": (name or "").strip(), "at": _now()}})
    report.acceptance = acc
    _finalize_hash(report, acc)
    db.flush()
    return report


def _finalize_hash(report: Report, acc: dict) -> None:
    """固化：把签核元数据并入 content 尾注后重算哈希（设计方案 §0.2 铁律2）。"""
    content = copy.deepcopy(report.content or {})
    content.setdefault("sections", {}).setdefault("s8_conclusion", {}).update({
        "verdict": acc.get("verdict"), "note": acc.get("note", ""),
        "signer_vendor": acc.get("signer_vendor"),
        "signer_customer": acc.get("signer_customer"),
        "finalized_at": acc.get("finalized_at"),
    })
    content["report_hash"] = compute_report_hash({k: v for k, v in content.items()
                                                  if k != "report_hash"})
    report.content = content  # JSONB 整体赋值（同 acceptance，确保脏化）


def validate_acceptance(value: dict) -> str:
    """acceptance 读侧防御校验（API 出参组装前调用）；返回错误消息，空串=合法。"""
    st = value.get("status", "DRAFT")
    if st not in STATE:
        return f"acceptance.status 非法：{st}"
    if st == "FINALIZED" and not value.get("finalized_at"):
        return "FINALIZED 缺失 finalized_at"
    if value.get("verdict") == "CONDITIONAL" and not (value.get("note") or "").strip():
        return "CONDITIONAL 缺失豁免说明 note"
    return ""
