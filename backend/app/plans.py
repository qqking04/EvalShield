# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business License stated in the
# LICENSE file at the root of this distribution.
# SPDX-License-Identifier: BUSL-1.1
"""产品档位常量与能力矩阵（优化9 §1.4 —— 单一事实源）。

两个正交维度（禁止混用）：
- 部署形态：settings.EDITION ∈ {community, saas, enterprise}，
  决定 app/commercial/ 代码是否存在；
- 商业档位：社区 / 专业 / 企业（+集团版口径），由本文件常量 ×
  License 能力位 / 订阅态共同决定商业模块开哪些。

消费方：
- ``build_edition_matrix()`` → GET /api/meta/edition-matrix（ES9-P-02）
- ``resolve_flags()``        → GET /api/meta/feature-flags（ES9-P-01）
- ``limits.py`` 的 suggest_plan 引导（kind→档位）引用本文件口径

禁止前端重复维护等价常量（EditionCompare / flags.js 只消费接口）。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 档位 → 模块能力映射（§1.4 逐字）
# ---------------------------------------------------------------------------

PLAN_MODULES: dict[str, list[str]] = {
    "professional": ["ai_eval_full", "question_bank", "src_audit", "uat",
                     "cost_dashboard", "model_compare", "report_delivery"],
    "enterprise":   ["*"],  # professional 全集 + 下列专属
}

ENTERPRISE_ONLY = ["multi_tenant", "org_sync_sso", "platform_monitor",
                   "white_label", "fact_sources", "delivery_packages"]

# 专业档位在 PLAN_MODULES 之外可达的实验区能力
#（前端 FALLBACK 口径："定时监控 / 在线评测 / 红队" = 专业限量、企业全量）
PROFESSIONAL_EXTRA = ["ci", "recordings", "perf_lab",
                      "online_eval", "generative_redteam"]

# 题库分级限额（§1.4 逐字；banks/questions=None 表示不限）
COMMUNITY_PLAN_BANK_LIMITS = {"banks": 1, "questions": 200, "sensitivity_max": "public"}
PRO_PLAN_BANK_LIMITS       = {"banks": 10, "questions": 5000, "sensitivity_max": "internal"}
ENT_PLAN_BANK_LIMITS       = {"banks": None, "questions": None, "sensitivity_max": "confidential"}


def _professional_module_set() -> set[str]:
    return set(PLAN_MODULES["professional"]) | set(PROFESSIONAL_EXTRA)


def _enterprise_module_set() -> set[str]:
    return _professional_module_set() | set(ENTERPRISE_ONLY)


# ---------------------------------------------------------------------------
# feature flags 求值（ES9-P-01，§2.1.1-A）
# ---------------------------------------------------------------------------

# 导航 flag → 所需模块位（无映射的 flag 属核心导航，恒可见）
FLAG_TO_MODULE: dict[str, str] = {
    "nav.lab.cost": "cost_dashboard",
    "nav.lab.uat": "uat",
    "nav.lab.ci": "ci",
    "nav.lab.model_compare": "model_compare",
    "nav.lab.recordings": "recordings",
    "nav.lab.perf": "perf_lab",
    "nav.lab.src": "src_audit",
    "nav.lab.redteam": "generative_redteam",
    "nav.lab.monitor": "platform_monitor",
}

# 已知 flag 全集（与 frontend/src/edition/flags.js KNOWN_NAV_FLAGS 对齐，
# 新增入口先登记本表再登记前端，两端顺序一致便于对账）
KNOWN_NAV_FLAGS: list[str] = [
    "nav.question_bank",
    "nav.targets",
    "nav.reports",
    "nav.lab.cost",
    "nav.lab.uat",
    "nav.lab.ci",
    "nav.lab.model_compare",
    "nav.lab.recordings",
    "nav.lab.perf",
    "nav.lab.src",
    "nav.lab.redteam",
    "nav.lab.monitor",
]


def _enabled_modules(edition: str, plan_features: list[str] | None) -> set[str]:
    """形态 + 能力位 → 实际开启的商业模块集合。

    - community：商业代码物理缺席 → 空集；
    - saas / enterprise 且 plan_features=None（License 有效但未细分档位，
      或订阅态全功能）：按企业全集（= 现状：License 有效则全挂载）；
    - plan_features 含 "*"：企业全集；
    - 否则：plan_features ∪ 档位基线中专业/企业可达项（签发模块名可能是
      能力位而非模块名，逐项 AND 由调用方保证，这里只做集合化）。
    """
    if edition == "community":
        return set()
    if plan_features is None:
        return _enterprise_module_set()
    feats = set(plan_features)
    if "*" in feats:
        return _enterprise_module_set()
    # 模块名与能力位混排时宽容合并：专业集内按位点亮，企业专属仅按位点亮
    allowed = _professional_module_set() | feats
    return {m for m in allowed if m in feats or m in set(PLAN_MODULES["professional"])}


def resolve_flags(
    edition: str,
    nav_profile: str,
    plan_features: list[str] | None = None,
) -> dict[str, bool]:
    """纯函数求值导航 flag（三形态 × 三档位可单测，对齐 ES8-BUG-007）。

    求值链（§1.4）：EDITION（形态）→ 商业挂载有无（community 空集）→
    plans.py 档位基线（plan_features=None 即全集）→ 逐 flag AND。

    - ``nav_profile == "full"``：全部可达（开发环境口径，能力不删）；
    - ``nav_profile == "focused"``：按档位矩阵收敛。
    """
    if nav_profile == "full":
        return {k: True for k in KNOWN_NAV_FLAGS}
    modules = _enabled_modules(edition, plan_features)
    flags: dict[str, bool] = {}
    for key in KNOWN_NAV_FLAGS:
        module = FLAG_TO_MODULE.get(key)
        # 核心导航 flag（无模块映射）恒可见；lab flag 按模块位 AND
        flags[key] = True if module is None else module in modules
    return flags


# ---------------------------------------------------------------------------
# 版本能力对比矩阵（ES9-P-02，§2.2.3 —— 三列全部代码反射生成）
# ---------------------------------------------------------------------------

def _bank_cell(limits: dict[str, Any]) -> str:
    banks, questions = limits.get("banks"), limits.get("questions")
    if banks is None and questions is None:
        return "不限库 / 不限题"
    return f"{banks} 库 / {questions} 题"


def build_edition_matrix() -> dict[str, list[dict[str, Any]]]:
    """返回 ``{"rows": [{capability, group, community, professional,
    enterprise, group_edition}]}``。

    反射源：COMMUNITY_LIMITS（社区列数值）+ PLAN_MODULES / ENTERPRISE_ONLY
    （专业 / 企业两列布尔）+ PLAN_BANK_LIMITS（题库分级字符串单元格）。
    矩阵内每个数字都直接引用常量，杜绝手填漂移（单元测试断言相等）。
    """
    from .limits import COMMUNITY_LIMITS  # 延迟导入：limits 不依赖本文件

    def modules_row(capability: str, group: str, modules: list[str],
                    pro_value: Any = True, ent_value: Any = True) -> dict[str, Any]:
        pro_set = _professional_module_set()
        return {
            "group": group,
            "capability": capability,
            "community": False,
            "professional": pro_value if all(m in pro_set for m in modules) else False,
            "enterprise": ent_value,
            "group_edition": True,
        }

    rows: list[dict[str, Any]] = [
        {
            "group": "核心评测",
            "capability": "评测任务与报告",
            "community": True, "professional": True,
            "enterprise": True, "group_edition": True,
        },
        {
            "group": "核心评测",
            "capability": "项目与用例额度",
            "community": (
                f"{COMMUNITY_LIMITS['projects_total']} 个项目 / "
                f"{COMMUNITY_LIMITS['cases_total']} 条用例"
            ),
            "professional": True, "enterprise": True, "group_edition": True,
        },
        {
            "group": "核心评测",
            "capability": "AI 用例生成",
            "community": (
                f"单次 {COMMUNITY_LIMITS['case_gen_per_call']} 条 / "
                f"每日 {COMMUNITY_LIMITS['case_gen_per_day']} 次"
            ),
            "professional": True, "enterprise": True, "group_edition": True,
        },
        {
            "group": "核心评测",
            "capability": "题库与覆盖度",
            "community": _bank_cell(COMMUNITY_PLAN_BANK_LIMITS),
            "professional": _bank_cell(PRO_PLAN_BANK_LIMITS),
            "enterprise": _bank_cell(ENT_PLAN_BANK_LIMITS),
            "group_edition": _bank_cell(ENT_PLAN_BANK_LIMITS),
        },
        {
            "group": "核心评测",
            "capability": "人工复核工作台",
            "community": True, "professional": True,
            "enterprise": True, "group_edition": True,
        },
        modules_row("成本看板 / 模型对比", "商业能力", ["cost_dashboard", "model_compare"]),
        modules_row("UAT 验收报告", "商业能力", ["uat"]),
        modules_row("SRC 轻量代码检查", "商业能力", ["src_audit"]),
        modules_row("CI 集成 / UI 录制", "商业能力", ["ci", "recordings"]),
        modules_row(
            "定时监控 / 在线评测 / 红队", "商业能力",
            ["online_eval", "generative_redteam", "perf_lab"],
            pro_value="限量", ent_value=True,
        ),
        {
            "group": "部署形态",
            "capability": "私有化离线部署",
            "community": True, "professional": True,
            "enterprise": True, "group_edition": True,
        },
        {
            "group": "部署形态",
            "capability": "本地私有模型接入",
            # local_llm 开关型：False → 社区列展示关闭
            "community": bool(COMMUNITY_LIMITS["local_llm"]),
            "professional": True, "enterprise": True, "group_edition": True,
        },
        {
            "group": "部署形态",
            "capability": "多租户与平台运营",
            "community": False, "professional": False,
            "enterprise": True, "group_edition": True,
        },
        {
            "group": "部署形态",
            "capability": "集团版组织级隔离",
            "community": False, "professional": False,
            "enterprise": False, "group_edition": True,
        },
    ]
    return {"rows": rows}
