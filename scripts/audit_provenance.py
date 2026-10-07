"""XA-6 出处断链巡检门（KD-1 注册表健康巡检）。

规格：研究扩充 round18 XA-6「出处断链巡检门
（自动对照 docstring 公式↔出处）」。巡检对象=KD-1 公式 provenance 注册表
（knowledge/formula_provenance.yaml，schema/扫描单源在
src/rfauto/core/formula_provenance.py）。

巡检五面（判据口径）：
1. **unverified 占比**（fail 面）：access_status=unverified 条目占 docstring
   条目总数比例 > 阈值（缺省 0.30）→ 门红。null（判不了如实不判）不入
   分子分母污染——judged 口径（unverified/(verified+unverified)）随报告
   附带，不作门；
2. **孤儿条目**（fail 面）：kernel_file 磁盘缺失（文件删除/移动后注册表
   未再生）——硬断链，逐条列名；
3. **陈旧条目**（fail 面）：origin=docstring 条目的 formula_id 在仓级
   docstring 重扫描中消失（docstring 出处标记被删/改名未再生）——
   docstring↔出处断链本体，逐条列名。manual_entries 人工补录区不参与
   （按定义不在 docstring 扫描面，非断链）；
4. **verified 条目 evidence 抽检**（报告面，不阻断）：access_status=
   verified 且 refs/source_doi 双缺的条目如实列出（可达性是 docstring
   词面自声明，证据可能在 claim_block prose——静态抽检只对账机读证据
   在档性，网络可达性归人工核验流程，本门保确定性）；
5. **未收集新条目**（报告面，不阻断）：docstring 扫描有而注册表无的
   formula_id——再生归属 collect_formula_provenance.py --check（字节
   漂移门，已存在）；并行批次窗口树面常态漂移，本门不重复裁决。

门语义：**报告不阻断，1/2/3 超限才 fail**（exit 1；巡检不可执行=
exit 2——注册表缺失/schema 坏/扫描失败）。确定性：巡检 payload 零时间戳
字段，同树二跑 JSON 逐字节一致（列表全部排序）。

用法（仓根执行）：
    .venv/Scripts/python.exe scripts/audit_provenance.py               # 人读报告
    .venv/Scripts/python.exe scripts/audit_provenance.py --json        # 机读面
    .venv/Scripts/python.exe scripts/audit_provenance.py --unverified-ratio-max 0.3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.formula_provenance import (  # noqa: E402
    load_formula_provenance,
    scan_repo_formula_provenance,
)

#: unverified 占比门缺省阈值（unverified/docstring_entries，严格大于才红）。
DEFAULT_UNVERIFIED_RATIO_MAX = 0.30

#: 缺省注册表路径（仓相对）。
DEFAULT_REGISTRY_RELPATH = Path("knowledge") / "formula_provenance.yaml"


def audit_provenance(
    repo_root: str | Path,
    *,
    registry_data: dict[str, Any] | None = None,
    fresh_entries: list[dict[str, Any]] | None = None,
    unverified_ratio_max: float = DEFAULT_UNVERIFIED_RATIO_MAX,
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """KD-1 注册表健康巡检（纯函数面；IO 只读——读注册表/扫 docstring/查存在性）。

    Args:
        repo_root: 仓根（kernel_file 存在性基准 + docstring 扫描根）。
        registry_data: 注入已加载注册表（``load_formula_provenance`` 返回
            形态；缺省读 canonical 路径）——单测免重复落盘。
        fresh_entries: 注入 docstring 重扫描条目（缺省实扫）——单测免扫
            真树（~5s）。
        unverified_ratio_max: 占比阈值（严格大于才红；边界=绿）。
        registry_path: 注册表路径覆盖（registry_data 未注入时生效）。

    Returns:
        巡检报告 dict（确定性；结构见模块 docstring 巡检五面）。
    """
    root = Path(repo_root)
    rel_max = float(unverified_ratio_max)
    if not (rel_max > 0.0):
        raise ValueError(f"unverified_ratio_max 须 >0，实际 {rel_max!r}")

    if registry_data is None:
        registry_data = load_formula_provenance(registry_path)
    entries = list(registry_data["entries"])
    manual = list(registry_data.get("manual_entries") or [])
    if fresh_entries is None:
        fresh_entries = scan_repo_formula_provenance(root)

    # ── 总量面 ────────────────────────────────────────────────────────────
    doc_entries = [e for e in entries if e.get("origin") == "docstring"]
    by_access: dict[str, int] = {"verified": 0, "unverified": 0, "null": 0}
    by_kind: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    for e in entries:
        acc = e.get("access_status")
        by_access[acc if acc in ("verified", "unverified") else "null"] += 1
        by_kind[e.get("kind")] = by_kind.get(e.get("kind"), 0) + 1
        by_origin[e.get("origin")] = by_origin.get(e.get("origin"), 0) + 1
    n_doc = len(doc_entries)
    n_unver = by_access["unverified"]
    n_ver = by_access["verified"]
    ratio = (n_unver / n_doc) if n_doc else 0.0
    judged = (n_unver / (n_ver + n_unver)) if (n_ver + n_unver) else None

    # ── fail 面 1：孤儿条目（kernel_file 磁盘缺失）────────────────────────
    orphans: list[dict[str, str]] = []
    for e in entries:
        kf = str(e.get("kernel_file") or "")
        if kf and not (root / kf).exists():
            orphans.append({"formula_id": e["formula_id"], "kernel_file": kf})
    orphans.sort(key=lambda d: (d["formula_id"], d["kernel_file"]))

    # ── fail 面 2 + 报告面 5：docstring 重扫描 id 对照 ────────────────────
    reg_ids = {e["formula_id"] for e in doc_entries}
    fresh_ids = {e["formula_id"] for e in fresh_entries}
    stale_ids = sorted(reg_ids - fresh_ids)
    uncollected_ids = sorted(fresh_ids - reg_ids)

    # ── 报告面 4：verified 条目 evidence 抽检（refs/DOI 双缺）─────────────
    verified_without_evidence = sorted(
        ({"formula_id": e["formula_id"], "kernel_file": e["kernel_file"]}
         for e in entries
         if e.get("access_status") == "verified"
         and not e.get("refs") and not e.get("source_doi")),
        key=lambda d: d["formula_id"])

    # ── 门裁决（1 占比 + 2 孤儿 + 3 陈旧；4/5 永不阻断）───────────────────
    fail_items: list[str] = []
    if ratio > rel_max:
        fail_items.append(
            f"unverified_ratio {ratio:.4f} > max {rel_max:.4f}"
            f"（{n_unver}/{n_doc} docstring 条目）")
    for o in orphans:
        fail_items.append(
            f"orphan kernel_file missing: {o['formula_id']} -> {o['kernel_file']}")
    if stale_ids:
        fail_items.append(
            f"stale entries（注册表有/docstring 扫描无，断链）: {stale_ids}")

    return {
        "registry_path": str(registry_path) if registry_path is not None
        else str(DEFAULT_REGISTRY_RELPATH),
        "totals": {
            "entries": len(entries),
            "manual_entries": len(manual),
            "docstring_entries": n_doc,
            "files": len({e["kernel_file"] for e in doc_entries}),
            "modules": len({e["module"] for e in doc_entries}),
            "by_access": by_access,
            "by_kind": dict(sorted(by_kind.items(), key=lambda kv: str(kv[0]))),
            "by_origin": dict(sorted(by_origin.items(), key=lambda kv: str(kv[0]))),
            "fresh_scan_entries": len(fresh_entries),
        },
        "unverified_ratio": ratio,
        "unverified_ratio_judged": judged,
        "unverified_ratio_max": rel_max,
        "unverified_ids": sorted(
            e["formula_id"] for e in doc_entries
            if e.get("access_status") == "unverified"),
        "orphans": orphans,
        "stale_ids": stale_ids,
        "uncollected_ids": uncollected_ids,
        "verified_without_evidence": verified_without_evidence,
        "gate": {
            "ok": not fail_items,
            "fail_items": fail_items,
            "warn_counts": {
                "uncollected": len(uncollected_ids),
                "verified_without_evidence": len(verified_without_evidence),
            },
        },
    }


def render_report(report: dict[str, Any]) -> str:
    """人读报告面（确定性行序；不含时间戳）。"""
    t = report["totals"]
    lines = [
        f"[xa6] registry: {report['registry_path']}",
        f"[xa6] entries={t['entries']}（docstring {t['docstring_entries']}"
        f" + manual {t['manual_entries']}），files={t['files']}，"
        f"modules={t['modules']}；fresh_scan={t['fresh_scan_entries']}",
        f"[xa6] by_access={t['by_access']} by_kind={t['by_kind']}",
        f"[xa6] unverified_ratio={report['unverified_ratio']:.4f}"
        f"（judged {_fmt_opt_ratio(report['unverified_ratio_judged'])}）"
        f" max={report['unverified_ratio_max']:.4f}",
        f"[xa6] orphans={len(report['orphans'])}"
        f" stale={len(report['stale_ids'])}"
        f" uncollected={len(report['uncollected_ids'])}"
        f"（报告面，归属 collector --check）"
        f" verified_without_evidence={len(report['verified_without_evidence'])}",
    ]
    for o in report["orphans"]:
        lines.append(f"[xa6]   orphan: {o['formula_id']} -> {o['kernel_file']}")
    for fid in report["stale_ids"]:
        lines.append(f"[xa6]   stale: {fid}")
    for fid in report["uncollected_ids"]:
        lines.append(f"[xa6]   uncollected: {fid}")
    for row in report["verified_without_evidence"]:
        lines.append(
            f"[xa6]   verified_no_evidence: {row['formula_id']}"
            f"（refs/DOI 双缺，人工抽检）")
    if report["gate"]["ok"]:
        lines.append("[xa6] OK: 出处巡检门绿（占比/孤儿/断链均在限内）")
    else:
        lines.append("[xa6] FAIL:")
        for item in report["gate"]["fail_items"]:
            lines.append(f"  {item}")
        lines.append("[xa6] 处置：docstring 改动→再生 python "
                     "scripts/collect_formula_provenance.py；文件删除/移动→"
                     "再生并核对孤儿条目归属")
    return "\n".join(lines)


def _fmt_opt_ratio(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="XA-6 出处断链巡检门（KD-1 注册表健康巡检，报告不阻断、超限才 fail）",
    )
    parser.add_argument(
        "--registry", default=None,
        help=f"注册表路径覆盖（缺省 <repo>/{DEFAULT_REGISTRY_RELPATH}）")
    parser.add_argument(
        "--repo-root", default=str(ROOT), help="仓根（缺省=脚本上级目录）")
    parser.add_argument(
        "--unverified-ratio-max", type=float,
        default=DEFAULT_UNVERIFIED_RATIO_MAX,
        help=f"unverified 占比阈值（缺省 {DEFAULT_UNVERIFIED_RATIO_MAX}）")
    parser.add_argument(
        "--json", action="store_true", help="输出机读 JSON 报告（确定性）")
    args = parser.parse_args(argv)

    registry_path = Path(args.registry) if args.registry else None
    try:
        report = audit_provenance(
            args.repo_root,
            registry_path=registry_path,
            unverified_ratio_max=args.unverified_ratio_max,
        )
    except (FileNotFoundError, ValueError) as exc:
        # 巡检不可执行（注册表缺失/schema 坏/参数坏）≠ 巡检门红——如实 exit 2
        print(f"[xa6] ERROR: 巡检不可执行: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1))
    else:
        print(render_report(report))
    return 0 if report["gate"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
