#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TEN-02 租户号矩阵导出与对账（方案 §0.4 号段分配 / §14 脚本清单 / BUG-ES9-005）.

扫描 backend/tests/test_*.py 中 99xxxx 租户号字面量，输出 号段 × 用例组 映射
（stdout markdown + verification/es9/tenant_matrix.json），并与 §0.4 分配表对账。

分层判据（先全量 grep 定事实，宁可保守登记现状）：
  [1] ES9 文件（test_es9_*.py）严格判：所用租户号必须落在 §0.4 该组规划段，
      否则必须命中 REUSE_BASELINE 登记豁免，否则 fail：
        test_es9_qb_fixtures   990102 ∈ 规划段 990100-103（SMP）      —— 在段
        test_es9_tenant_matrix 990120/121 ∉ 规划段 990110-111        —— 复用 ES8 M8 段
        test_es9_uat_report    990110 ∉ 规划段 990106-107（DELIV）    —— 复用 ES8 M6 段
        test_es9_rvw05_promote 990130/131 ∉ 规划段 990104-105（RVW）  —— 复用 ES8 M7/M9 段
        test_es9_ssrf_guard    990112 ——【号表外登记】§0.4 未给 HAL/PWD 组段号，
                               落码占用 TEN 段邻号；建议回填 §0.4 或改用 990106-107 空闲号
        test_es9_pwd_half      990113 —— 同上（PWD 组号表外）
        test_es9_eval_run_compat 990114 —— RUN 组规划段 990100-103 与 QB/SMP 占用重叠
                               （990102 已用），沿 990112-113 续排号表外
  [2] ES9 规划独占段（990100-107）反向排他：ES8/存量文件不得新落入该段。
      命中存量例外入 ES8_EXCLUSIVE_BASELINE 登记（先于 §0.4 定案，维持现状）：
        test_es8_gate.py   990100 —— ES8 门禁 GATE_TENANT；ES9 QB 组落码用段内空闲号
        test_es8_review.py 990110/990111 —— ES8 M6 段与 ES9 TEN 计划段同号，
            两文件清场前缀不同（es8rw*/es9tm*）串行不互踩；ES9 TEN 组实际改用
            990120/121（见 REUSE_BASELINE），本条仅登记历史冲突
  [3] 非租户哨兵号：999999 / 990999 / 991070 等出现在"不存在 ID/对照配额行"
      语境，不属号段分配管辖 → SENTINEL 名单排除。
  [4] ES8 段间相互复用（990097×3 文件、990098/990099×2、990130/131×2 等）
      为 ES8 存量既成事实：只登记进矩阵输出，不做 fail 判定。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "backend" / "tests"
OUT = ROOT / "verification" / "es9" / "tenant_matrix.json"

# §0.4 号段分配表（组 → [lo, hi] 闭区间；其余 ES9 组复用 ES8 原段 990097 起）
PLAN = {
    "QB/IMP/SMP/RUN": (990100, 990103),
    "JD/RVW": (990104, 990105),
    "STD/HAL/DELIV": (990106, 990107),
    "TEN(越权矩阵)": (990110, 990111),
}
# [3] 非租户哨兵号（不存在 ID / 对照配额行语境），不参与号段对账
SENTINEL = {999999, 990999, 991070}

# [1] ES9 复用/号表外豁免登记（文件 → 允许租户号集合 + 理由）
REUSE_BASELINE = {
    "test_es9_tenant_matrix.py": ({990120, 990121},
        "复用 ES8 M8(traces) 段；es9tm/ES9TM 前缀物理清场与 ES8 数据不交叠"),
    "test_es9_uat_report.py": ({990110},
        "复用 ES8 M6(review) 段（UAT 报告 fixture 与 review 用例同表族不同前缀）"),
    "test_es9_rvw05_promote.py": ({990130, 990131},
        "复用 ES8 M7/M9(dataset/redteam) 段；promote 用例独立前缀清场"),
    "test_es9_ssrf_guard.py": ({990112},
        "号表外登记：§0.4 未给 HAL 组段号，落码占用 TEN 段邻号；建议回填 §0.4 或改用空闲号"),
    "test_es9_pwd_half.py": ({990113},
        "号表外登记：§0.4 未给 PWD 组段号，落码续排 990112 之后；建议回填 §0.4"),
    "test_es9_eval_run_compat.py": ({990114},
        "号表外登记：RUN 组规划段 990100-103 与 QB/SMP 占用重叠，沿 990112-113 续排"),
    "test_es9_coverage_batch_a.py": ({990120},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 A 种子行 TESTA 前缀 + 夹具内回滚，不交叠"),
    "test_es9_coverage_batch_b.py": ({990120},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 B 种子行 TESTB 标记 + 夹具自清理，不交叠"),
    "test_es9_coverage_batch_c.py": ({990120},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 C 种子行 TESTC 标记 + 夹具自清理，不交叠"),
    "test_es9_coverage_batch_d.py": ({990120},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 D 纯 mock 不落库，990120 仅为常量字面量"),
    "test_es9_coverage_batch_e.py": ({990120},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 E 纯 mock 不落库，990120 仅为常量字面量"),
    "test_es9_coverage_batch_f.py": ({990120, 990121},
        "复用 ES8 M8(traces) 段（与 tenant_matrix 同段）；批次 F admin/cases_core 路由覆盖，TESTF/testf_ 前缀 autouse 夹具物理清场，不交叠"),
    # —— ES10 批次 G（§11.1，号段顺延登记；990122/123 亦不落 §0.4 规划独占段）——
    "test_es10_batch_g.py": ({990122, 990123},
        "ES10 批次 G（P-04 scopes / P-05 share / P-07 orgs / P-01 fact-source / P-02 version）；"
        "沿 ES9 矩阵段 990120-121 顺延排 990122/123，TESTG/testg_ 前缀 autouse 夹具物理清场，不交叠"),
}
# [2] ES8/存量落入 §0.4 规划段（含 TEN 990110-111）的存量例外
ES8_EXCLUSIVE_BASELINE = {
    ("test_es8_gate.py", 990100):
        "ES8 门禁 GATE_TENANT 先于 §0.4 定案；ES9 QB 组落码用 990101-103 空闲号",
    ("test_es8_review.py", 990110):
        "ES8 M6 段与 ES9 TEN 计划段同号；清场前缀不同（es8rw*/es9tm*）串行不互踩，仅登记",
    ("test_es8_review.py", 990111):
        "同上，ES9 TEN 组实际改用 990120/121（见 REUSE_BASELINE），本条仅登记历史冲突",
}

NUM = re.compile(r"\b(99\d{4})\b")
CONST = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*(99\d{4})\b")


def scan() -> dict[str, list[int]]:
    """file → 该文件代码行出现的租户号（去重排序；剔除注释行降噪）."""
    out: dict[str, list[int]] = {}
    for f in sorted(TESTS.glob("test_*.py")):
        nums: set[int] = set()
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s.startswith("#"):
                continue
            m = CONST.match(s)
            if m:
                nums.add(int(m.group(1)))
            else:
                nums |= {int(x) for x in NUM.findall(re.sub(r"#.*$", "", ln))}
        if nums:
            out[f.name] = sorted(n for n in nums if n not in SENTINEL)
    return {k: v for k, v in out.items() if v}


def main() -> int:
    if not TESTS.exists():
        print("FAIL: backend/tests 缺失")
        return 1
    matrix = scan()
    errs = []

    def in_plan(n: int) -> bool:
        return any(lo <= n <= hi for lo, hi in PLAN.values())

    for fname, tenants in matrix.items():
        is_es9 = fname.startswith("test_es9_")
        for t in tenants:
            if not (990000 <= t <= 999999):
                continue
            if is_es9:
                base, _reason = REUSE_BASELINE.get(fname, (set(), ""))
                if not (in_plan(t) or t in base):
                    errs.append(f"ES9 文件 {fname} 租户号 {t} 既不在 §0.4 规划段也无复用登记")
            else:
                if in_plan(t) and (fname, t) not in ES8_EXCLUSIVE_BASELINE:
                    errs.append(f"ES8/存量文件 {fname} 落入 ES9 规划独占段: {t}（§0.4 对账冲突）")

    payload = {
        "plan_0_4": {k: list(v) for k, v in PLAN.items()},
        "matrix": matrix,
        "es9_reuse_baseline": {k: {"tenants": sorted(v[0]), "reason": v[1]} for k, v in REUSE_BASELINE.items()},
        "es8_exclusive_baseline": {f"{f}:{t}": r for (f, t), r in ES8_EXCLUSIVE_BASELINE.items()},
        "sentinel_excluded": sorted(SENTINEL),
        "es8_legacy_note": "ES8 段间相互复用（990097/990098/990099/990130-131 多文件）为存量既成事实，仅登记不判罚",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout：markdown 矩阵
    print("# 租户号矩阵（§0.4 对账，TEN-02）\n")
    print("| 文件 | 租户号 | 归属 |")
    print("|---|---|---|")
    for fname, tenants in matrix.items():
        grp = "ES9" if fname.startswith("test_es9_") else ("ES8" if "es8" in fname else "存量")
        note = ""
        if fname in REUSE_BASELINE:
            note = "（复用登记段）"
        print(f"| {fname} | {','.join(map(str, tenants))} | {grp}{note} |")

    if errs:
        print("\nFAIL: 号段对账冲突：")
        [print("  -", e) for e in errs]
        return 1
    print(f"\nPASS: 租户矩阵对账（{len(matrix)} 文件；ES9 规划段+复用登记全覆盖；"
          f"JSON → {OUT.relative_to(ROOT).as_posix()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
