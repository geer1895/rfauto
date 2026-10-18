"""MCP 描述单源门（Z-10，aurora_e W2-S10 E2）——独立入口。

单源不变量：**工具 docstring 的 Args 段 = 参数描述唯一真源**；fastmcp
把它渲染进 inputSchema ``properties[].description``（多行 Args 条目以
换行并入）。MCP-B 普查（test_mcp_tool_consistency）只硬判幽灵参数、
未记录参数 report-only——普查≠单源化门（patrol §二明证），本脚本把
五维升级为硬门：

  1. 工具描述非空（``tool.description``）；
  2. 必填参数全覆盖：schema ``required`` ⊆ docstring Args 记录名；
  3. schema 参数描述全覆盖：每个 ``properties`` 项有非空 description；
  4. 单源一致：schema description == docstring Args 描述（空白归一后
     逐字相等——多行条目归一换行比较，杜绝双源漂移）；
  5. 幽灵参数：docstring 记录但 schema 不存在的参数名（同
     test_mcp_tool_consistency phantom_args 硬判口径，脚本侧独立复检）。

零违例基线冻结（2026-10-18 实测 152 工具/514 参数五维全绿）；新增违例
即红，误报合法形态走 ``EXEMPTIONS``（带理由注记，只收不放，挂面时为空）。
``--json`` 输出机器报告；退出码 0=零违例 / 1=有违例 / 2=注册面不可用
（fastmcp 缺席/import 失败——SKIP 诚实降级，merge_preflight 面 17 挂面
口径）。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

#: 豁免表（工具名 → 参数名清单；dim 3/4 参数级豁免，只收不放）。
#: 挂面时为空（零违例基线）；新增条目必须带理由与背书注记。
EXEMPTIONS: dict[str, list[str]] = {}

_ARGS_ENTRY_RE = re.compile(r"^([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s?(.*)$")
_SECTION_END_RE = re.compile(
    r"^(Args|Returns|Raises|Examples?|Yields|Note|Notes)\s*:\s*$")

#: W8-S36（审查波 2 P2-1）：Google 风格 docstring 的保留节名/惯用续行
#: 前缀——Args 段内形如 ``Default: 0.1`` / ``Note: must be positive.``
#: （乃至行内 ``Returns: ...``）是上一参数的续行，不是新参数条目；
#: 误判会各自生成幽灵条目（dim5 假红拦 merge_preflight 合流）。
#: 真幽灵参数（schema 没有的非保留标识符）不受影响，照抓。
_RESERVED_CONTINUATION_NAMES = frozenset({
    "Args", "Argument", "Arguments", "Returns", "Raises", "Yields",
    "Example", "Examples", "Note", "Notes", "Default", "Defaults",
    "Type", "Warning", "Warnings",
})


@dataclass
class ToolReport:
    """单工具五维检查结果（violation 非空=红）。"""
    name: str
    param_count: int = 0
    required_count: int = 0
    violations: list[str] = field(default_factory=list)


def documented_args(fn: Any,
                    known_names: set[str] | None = None) -> dict[str, str]:
    """docstring Args 段 → {参数名: 描述}（含多行续行，行序保序）。

    续行归属：Args 段内非新条目且非节尾的非空行并入上一参数描述；
    与 tests/unit/test_mcp_tool_consistency._documented_args 同族正则，
    本版多收续行（单源比对需要全量描述文本）。

    W8-S36（审查波 2 P2-1）：新条目判定收紧——``known_names``（调用方
    传入 schema props ∪ required）给出的名字才算参数行；保留节名
    （``Default:``/``Note:`` 等惯用续行前缀）并入上一参数描述；两者
    都不沾的名字（schema 没有且非保留）仍按新条目收——dim5 真幽灵
    参数照抓。schema 成员优先于保留名（防 param 字面撞名误并）。
    """
    doc = inspect.getdoc(fn) or ""
    out: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            current = None
            continue
        if not in_args:
            continue
        if _SECTION_END_RE.match(stripped):
            break
        entry = _ARGS_ENTRY_RE.match(stripped)
        if entry:
            name = entry.group(1)
            is_param_line = (
                (known_names is not None and name in known_names)
                or (name not in _RESERVED_CONTINUATION_NAMES))
            if is_param_line:
                current = name
                out[current] = entry.group(2).strip()
                continue
        if current is not None and stripped:
            out[current] = f"{out[current]}\n{stripped}".strip()
    return out


def _norm(text: str) -> str:
    return " ".join(text.split())


def check_tool(tool: Any, report: ToolReport) -> ToolReport:
    """单工具五维检查（violations 追加到 report.violations）。"""
    name = tool.name
    schema = tool.parameters or {}
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    doc = documented_args(tool.fn,
                          known_names=set(props) | required)
    report.param_count = len(props)
    report.required_count = len(required)

    if not (tool.description or "").strip():
        report.violations.append("dim1: 工具描述为空")
    missing_required = sorted(required - set(doc))
    if missing_required:
        report.violations.append(
            f"dim2: 必填参数未入 docstring Args: {missing_required}")
    exempt = set(EXEMPTIONS.get(name, []))
    for param, spec in sorted(props.items()):
        desc = (spec or {}).get("description") or ""
        if not desc.strip():
            if param in exempt:
                continue
            report.violations.append(f"dim3: 参数 {param} schema description 为空")
            continue
        if param in exempt:
            continue
        doc_desc = doc.get(param)
        if doc_desc is None:
            report.violations.append(
                f"dim4: 参数 {param} schema 有描述但 docstring Args 无条目")
        elif _norm(doc_desc) != _norm(desc):
            report.violations.append(
                f"dim4: 参数 {param} 描述双源漂移"
                f"（docstring={doc_desc[:40]!r} vs schema={desc[:40]!r}）")
    ghosts = sorted(set(doc) - set(props))
    if ghosts:
        report.violations.append(f"dim5: 幽灵参数（docstring 有 schema 无）: {ghosts}")
    return report


def collect_registered_tools() -> list[Any]:
    """fastmcp 注册面 → 工具对象列表（import 失败向上抛，rc2 SKIP 口径）。"""
    from rfauto.mcp_server import mcp

    return list(asyncio.run(mcp.list_tools()))


def run_check(tools: list[Any]) -> dict[str, Any]:
    """全量五维检查 → 机器报告 dict（ok=零违例）。"""
    reports = [check_tool(t, ToolReport(name=t.name)) for t in tools]
    violations = {r.name: r.violations for r in reports if r.violations}
    return {
        "schema": "rfauto-mcp-desc-gate-v1",
        "tool_count": len(reports),
        "param_count": sum(r.param_count for r in reports),
        "required_param_count": sum(r.required_count for r in reports),
        "violation_tools": len(violations),
        "violations": violations,
        "ok": not violations,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MCP 描述单源门（Z-10 五维检查）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = ap.parse_args(argv)

    try:
        tools = collect_registered_tools()
    except Exception as exc:
        print(f"[SKIP] MCP 注册面不可用（fastmcp 缺席/import 失败）：{exc}")
        return 2

    report = run_check(tools)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["ok"]:
        print(f"[PASS] MCP 描述单源门：{report['tool_count']} 工具/"
              f"{report['param_count']} 参数（必填 "
              f"{report['required_param_count']}）五维零违例")
        return 0
    print(f"[FAIL] MCP 描述单源门：{report['violation_tools']} 工具违例"
          f"（docstring Args=参数描述唯一真源，新增违例即红；"
          f"豁免走 EXEMPTIONS 带理由，只收不放）")
    for name, vs in report["violations"].items():
        for v in vs:
            print(f"  {name}: {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
