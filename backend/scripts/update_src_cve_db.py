# -*- coding: utf-8 -*-
"""更新本地 CVE 库（backend/data/src_cve_db.json）。

离线模式（默认）：把补丁 JSON 中的条目合并进主库，按 (ecosystem, package, cve_id) 去重。
    python scripts/update_src_cve_db.py --patch path/to/patch.json

在线模式（可选，需外网与 requests）：从 NVD API 拉取指定 CVE 并合并。
    python scripts/update_src_cve_db.py --online CVE-2021-3177 CVE-2023-32681

补丁/在线条目字段与主库一致：
    {"entries": [{"ecosystem","package","affected","fixed_version",
                  "cve_id","severity","cvss","description"}]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "src_cve_db.json"

_REQUIRED = {"ecosystem", "package", "affected", "cve_id", "severity"}


def _load_db() -> dict:
    if not DB_PATH.exists():
        return {"entries": []}
    return json.loads(DB_PATH.read_text(encoding="utf-8-sig"))


def _validate(entry: dict) -> str | None:
    missing = _REQUIRED - set(entry)
    if missing:
        return f"缺少字段: {sorted(missing)}"
    if entry["ecosystem"] not in {"pypi", "npm"}:
        return f"不支持的 ecosystem: {entry['ecosystem']}"
    return None


def _merge(entries: list[dict]) -> tuple[int, int]:
    db = _load_db()
    index = {(e["ecosystem"], e["package"].lower(), e["cve_id"]) for e in db["entries"]}
    added = skipped = 0
    for e in entries:
        err = _validate(e)
        if err:
            print(f"[跳过] {e.get('cve_id', '?')}: {err}")
            skipped += 1
            continue
        key = (e["ecosystem"], e["package"].lower(), e["cve_id"])
        if key in index:
            skipped += 1
            continue
        db["entries"].append(e)
        index.add(key)
        added += 1
    DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return added, skipped


def apply_patch(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        sys.exit("补丁格式错误：应为 {'entries': [...]} 或顶层数组")
    added, skipped = _merge(entries)
    print(f"补丁合并完成：新增 {added} 条，跳过 {skipped} 条（重复/非法）")


def fetch_online(cve_ids: list[str]) -> None:
    """从 NVD API 2.0 拉取 CVE 并转为本地条目（尽力而为，需人工核对 ecosystem/package）。"""
    import urllib.request

    entries = []
    for cve in cve_ids:
        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {cve}: {exc}")
            continue
        vulns = payload.get("vulnerabilities") or []
        if not vulns:
            print(f"[未找到] {cve}")
            continue
        c = vulns[0]["cve"]
        desc = next((d["value"] for d in c.get("descriptions", [])
                     if d.get("lang") == "en"), "")
        metrics = c.get("metrics", {})
        cvss = None
        for m in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if metrics.get(m):
                cvss = metrics[m][0].get("cvssData", {}).get("baseScore")
                break
        # 从 CPE 猜包名（仅 pypi/npm 常见形态，失败则需人工补全）
        ecosystem, package, affected = "", "", "<9999"
        for conf in c.get("configurations", []):
            for node in conf.get("nodes", []):
                for mr in node.get("cpeMatch", []):
                    parts = (mr.get("criteria") or "").split(":")
                    if len(parts) > 6 and parts[3] == "python" and not ecosystem:
                        ecosystem, package = "pypi", parts[5]
                        affected = (f"<{mr['versionEndIncluding']}"
                                    if mr.get("versionEndIncluding")
                                    else f"<{mr.get('versionEndExcluding', '9999')}")
        if not ecosystem:
            print(f"[跳过] {cve}: 无法从 CPE 识别 pypi/npm 包，请手工补录")
            continue
        entries.append({
            "ecosystem": ecosystem, "package": package, "affected": affected,
            "fixed_version": None, "cve_id": cve,
            "severity": "HIGH" if (cvss or 0) >= 7 else "MEDIUM",
            "cvss": cvss, "description": desc[:300],
        })
    if entries:
        added, skipped = _merge(entries)
        print(f"在线拉取完成：新增 {added} 条，跳过 {skipped} 条")
    else:
        print("未获取到可合并条目")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, help="本地补丁 JSON 文件路径")
    parser.add_argument("--online", nargs="*", metavar="CVE_ID", help="从 NVD 在线拉取的 CVE 编号列表")
    args = parser.parse_args()
    if not args.patch and not args.online:
        parser.print_help()
        sys.exit(1)
    if args.patch:
        apply_patch(args.patch)
    if args.online:
        fetch_online(args.online)


if __name__ == "__main__":
    main()
