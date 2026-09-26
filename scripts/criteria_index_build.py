"""criteria_index_build：历史 runs/**/criteria.md 批量抽取 → knowledge/criteria/index.yaml。

DP-13 Z1（specs §13.4）。只读登记：runs/ 零改写（#325/#326 历史零改写），
产物只落 knowledge/criteria/index.yaml（本脚本唯一写点）。schema 落点=
DP-12 criteria/v2，本工具不另立 schema——index 只是"历史判据清单"的
只读登记，status 双态标迁移资格：

- ``migrate_to_v2``：≥1 行被门阈值 regex 抽中（含结构化判据，迁移候选）；
- ``legacy_only``：0 行（纯散文人工判读，不迁移）。

无静默漏抽：单测断言 index 行数==rglob 扫描文件数
（tests/unit/test_criteria_index_build.py）。输出确定性：同树重跑逐字节
一致（无时间戳键）。

门阈值行 regex（预声明 runs/df6_dp13/criteria.md §Z1）：行含比较符
(≤|≥|<|>) 且含单位词（dB/GHz/%/mm/ns/µm/um/数字+s 秒）之一，或含
``±数值`` 门；逐行抽原文 raw + 比较符后首个数值 threshold（best-effort，
行数如实，不凑全）。

用法：
    python scripts/criteria_index_build.py --runs-root runs --out knowledge/criteria/index.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

INDEX_SCHEMA = "rfauto-criteria-index-v1"

# 比较符（含 Unicode ≤ ≥）与单位词；\ds\b 按预声明 "s\b" 的秒语义实现为
# "数字+s"（裸 s\b 会把英文复数词尾全吞进来，属实现保真而非改口径）。
_OPERATOR_RE = re.compile(r"[≤≥<>]")
_UNIT_RE = re.compile(r"dB|GHz|%|mm|ns|µm|um|\ds\b")
_PLUS_MINUS_RE = re.compile(r"±\s*\d")
_NUMBER_AFTER_OP_RE = re.compile(r"[≤≥<>]\s*-?(\d+(?:\.\d+)?)")
_NUMBER_AFTER_PM_RE = re.compile(r"±\s*(\d+(?:\.\d+)?)")


def extract_gate_lines(text: str) -> list[dict[str, Any]]:
    """从 criteria.md 文本抽取门阈值行（best-effort，逐行原文+阈值）。"""
    gates: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        is_gate = (
            bool(_OPERATOR_RE.search(line)) and bool(_UNIT_RE.search(line))
        ) or bool(_PLUS_MINUS_RE.search(line))
        if not is_gate:
            continue
        m = _NUMBER_AFTER_OP_RE.search(line) or _NUMBER_AFTER_PM_RE.search(line)
        gates.append({
            "raw": line,
            "threshold": float(m.group(1)) if m else None,
        })
    return gates


def _title_of(text: str, fallback: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line:  # 无标题时取首个非空行
            return line
    return fallback


def build_index(runs_root: str | Path) -> dict[str, Any]:
    """扫 runs_root 下全部 criteria.md（rglob），构建只读 index 文档。"""
    root = Path(runs_root)
    if not root.is_dir():
        return {"ok": False, "errors": [f"runs 根不存在: {root}"]}
    files = sorted(
        (p for p in root.rglob("criteria.md") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    entries: list[dict[str, Any]] = []
    n_gate_rows = 0
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(root).as_posix()
        gates = extract_gate_lines(text)
        n_gate_rows += len(gates)
        entries.append({
            "path": rel,
            "title": _title_of(text, rel),
            "status": "migrate_to_v2" if gates else "legacy_only",
            "n_gates": len(gates),
            "gates": gates,
        })
    return {
        "ok": True,
        "schema": INDEX_SCHEMA,
        "runs_root": root.as_posix(),
        "n_files": len(files),
        "n_gate_rows": n_gate_rows,
        "entries": entries,
    }


def write_index(index: dict[str, Any], out_path: str | Path) -> Path:
    """index 文档落盘（确定性：sort_keys + 固定缩进，无时间戳键）。"""
    payload = {k: v for k, v in index.items() if k != "ok"}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                       default_flow_style=None, width=100),
        encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="扫 runs/**/criteria.md 构建只读判据清单（DP-13 Z1）")
    parser.add_argument("--runs-root", default="runs",
                        help="runs 根目录（缺省 runs/）")
    parser.add_argument("--out", default="knowledge/criteria/index.yaml",
                        help="输出 index.yaml 路径")
    parser.add_argument("--quiet", action="store_true",
                        help="只打一行摘要")
    args = parser.parse_args(argv)

    index = build_index(args.runs_root)
    if not index.get("ok"):
        for err in index.get("errors", ["未知错误"]):
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    out = write_index(index, args.out)
    n_migrate = sum(1 for e in index["entries"] if e["status"] == "migrate_to_v2")
    if args.quiet:
        print(f"criteria index: {index['n_files']} files, "
              f"{index['n_gate_rows']} gate rows -> {out}")
    else:
        print(f"扫描 {index['n_files']} 份 criteria.md "
              f"（migrate_to_v2={n_migrate}, legacy_only="
              f"{index['n_files'] - n_migrate}），"
              f"门阈值行 {index['n_gate_rows']} 行 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
