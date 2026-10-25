"""域词表巡检引擎（UX-B13/Z-8 survey domains，aurora_e W2-S10 U3）。

把"域扩张靠冲刺缺巡检"的机制根源（ux_vertical B4 探针实证）制度化：
对 UI/服务层暴露的三张 domains/分组词表做**词表项 ↔ 实际注册面双向对账**
（孤儿词/缺词报出；Z-11 pool-patrol 同范式，引擎在 service 层、scripts/
与调用方薄壳同包装，规则 3/4 分层不破）。

三张词表（单源各有其主，本引擎只读不改）：

- **V1 计算器组词表**：CALC_GROUP_ORDER（UI optgroup 词表）↔
  CALC_GROUP_TABLE 值域（注册面分组实值）——src/rfauto/core/calc_families/
  registry.py AST 直读（不 import core，#228 他轨在制不误伤）；
- **V2 CLI 域词表**：cli 主 app 顶层组名（rfauto --help 暴露面，由调用方
  注入 typer app 后运行时枚举；service 层禁 import cli，W4-S20 分层修复）
  ↔ cli/domains/ 源模块可达面（入口文件 import/自注册）；
- **V3 MCP 工具组词表**：knowledge/toolsets.yaml 组名+tools_hint ↔
  mcp_tools/ 注册面（@mcp.tool/@mcp.resource；工具名枚举复用
  toolsets_service.enumerate_registered_tool_names 单源）。

红面（门判据，零违例基线 2026-10-18 冻结）：
- V1 孤儿词（ORDER 有、TABLE 值域无）/ 缺词（TABLE 值域有、ORDER 无）；
- V2 空组（顶层组零命令零子组=help 里的死词）/ 孤儿域模块（domains/
  模块不被任何 cli 入口引用=死文件）；
- V3 toolset 组名空/重；tools_hint 任一模式对注册面零命中（drift，同
  toolsets_service 报 drift 口径）；mcp_tools 死组模块（除 _core/__init__
  外零注册装饰器）。

报告面（永不红——空白≠立项，B4 原文"只产报告"）：域×层覆盖矩阵、
组键计数、注册计算器键未入 CALC_GROUP_TABLE（落"其他"）、注册工具未
被任何 toolset hint 覆盖。

零网络零 LLM（#139 语义）；同输入两次调用逐位一致。返回 ok/error 信封
（规则 4）；input ports（文件文本/运行时枚举）可注入替身供测试隔离。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["SCHEMA", "domain_survey"]

SCHEMA = "rfauto-domain-survey-v1"

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: mcp_tools/ 豁免模块（无注册装饰器属正常：包 init 与 mcp 实例承载面）
_MCP_TOOLS_EXEMPT_MODULES = {"__init__", "_core"}

#: cli/domains/ 豁免模块（无域语义属正常：包 init 与共享核心面）——
#: 孤儿判定与模块计数共用单源（W6-P3-5③：曾两处口径，计数处硬编码 −2，
#: 豁免集扩张即计数漂移）
_CLI_DOMAINS_EXEMPT_MODULES = frozenset({"__init__", "_core"})


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ─── V1 计算器组词表（AST 直读，不 import core）────────────────────────────

def _const_str(node: ast.expr | None) -> str | None:
    """AST 节点 → 字符串字面量值；非 str 字面量（名字引用/拼接/**解包的
    None 键）返回 None（W5-P3-5/W6-P3-5①：调用方跳过而非裸 ``.value``
    AttributeError 出轨迹）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse_calc_registry(source: str) -> tuple[list[str], dict[str, str], int]:
    """registry.py 源 → (CALC_GROUP_ORDER, CALC_GROUP_TABLE, 跳过条目数)。

    非字面量条目跳过不入解析结果、计数如实返回（W5-P3-5：曾直接
    ``el.value``/``k.value`` 裸取，表达式条目使引擎 AttributeError 而非
    error 信封；跳过使对应词进 V1 对账红面——漏报方向安全）。
    """
    order: list[str] = []
    table: dict[str, str] = {}
    skipped = 0
    for node in ast.parse(source).body:
        target = getattr(node, "target", None)
        if target is None and isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
        if not isinstance(target, ast.Name) or node.value is None:
            continue
        if target.id == "CALC_GROUP_ORDER" and isinstance(
                node.value, (ast.Tuple, ast.List)):
            for el in node.value.elts:
                val = _const_str(el)
                if val is None:
                    skipped += 1
                else:
                    order.append(val)
        elif target.id == "CALC_GROUP_TABLE" and isinstance(node.value, ast.Dict):
            for k_node, v_node in zip(node.value.keys, node.value.values,
                                      strict=False):
                key = _const_str(k_node)
                val = _const_str(v_node)
                if key is None or val is None:
                    skipped += 1
                else:
                    table[key] = val
    return order, table, skipped


_DECORATOR_NAME = re.compile(r"@register_calculator\(")


def _first_str_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) \
            and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _registered_calc_keys(family_dir: Path) -> tuple[list[str], list[str]]:
    """calc_families/*.py 的 @register_calculator 首参键（AST 扫，保序去重）。

    返回 (keys, unparsable_files)：语法不可解析的族文件跳过并如实列名
    （W6-P3-5① 同面收口——曾裸 ``ast.parse`` 使单个半成品/损坏族文件
    让整个巡检出轨迹而非降级；在制席位半成品按 #228 不红活体基线，
    跳过面入报告计数可见，不静默）。
    """
    keys: list[str] = []
    unparsable: list[str] = []
    for path in sorted(family_dir.glob("*.py")):
        text = _read(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            unparsable.append(path.stem)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "register_calculator":
                key = _first_str_arg(node)
                if key is not None and key not in keys:
                    keys.append(key)
    return keys, unparsable


# ─── V2 CLI 域词表（运行时枚举 + 源可达面）─────────────────────────────────

def _cli_group_names(app: Any) -> list[dict[str, Any]]:
    """typer 主 app 顶层组 → [{name, command_count}]（鸭子判别，#354 家法）。"""
    out: list[dict[str, Any]] = []
    for info in app.registered_groups:
        typer_instance = info.typer_instance
        n_cmds = len(typer_instance.registered_commands or [])
        n_sub = len(typer_instance.registered_groups or [])
        out.append({"name": info.name or "",
                    "command_count": n_cmds + n_sub})
    return out


def _orphan_cli_domain_modules(domains_dir: Path,
                               cli_sources: dict[str, str]) -> list[str]:
    """domains/ 模块不被 cli 树任何其他文件引用 → 死文件名单（__init__/_core 豁免）。

    引用链可达口径：main.py 直引（scattered/lake 等）与域模块间转引
    （bands_uq → campaign 的 UX-B6 拆分链）都算活；唯一判据="domains.<mod>
    出现在 cli 树（顶层+domains）除自身外任一文件"——引用图上零入度的
    模块即死文件。
    """
    orphans: list[str] = []
    for path in sorted(domains_dir.glob("*.py")):
        name = path.stem
        if name in _CLI_DOMAINS_EXEMPT_MODULES:
            continue
        referenced = any(
            f"domains.{name}" in src
            for other, src in cli_sources.items() if other != name)
        if not referenced:
            orphans.append(name)
    return orphans


# ─── V3 MCP 工具组词表 ──────────────────────────────────────────────────────

def _mcp_tool_registration_counts(tools_dir: Path) -> dict[str, dict[str, int]]:
    r"""mcp_tools/*.py → {module: {tool: n, resource: n}}（装饰器行扫描）。

    判定口径（W5-P3-4/W6-P3-5②）：``\s*`` 容缩进形态（类方法/if 块内
    注册曾因行首锚漏扫误判"死组模块"）；resource 侧 ``\b`` 不强制括号
    （裸 ``@mcp.resource`` 风格曾必误判；``\b`` 对 ``@mcp.resource(`` 与
    ``@mcp.resource_x`` 分别兼容/排除——下划线延续标识符无词边界）。
    """
    tool_re = re.compile(r"^\s*@mcp\.tool\b", re.MULTILINE)
    resource_re = re.compile(r"^\s*@mcp\.resource\b", re.MULTILINE)
    counts: dict[str, dict[str, int]] = {}
    for path in sorted(tools_dir.glob("*.py")):
        text = _read(path)
        if text is None:
            continue
        counts[path.stem] = {
            "tool": len(tool_re.findall(text)),
            "resource": len(resource_re.findall(text)),
        }
    return counts


def _fnmatch_any(name: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatchcase(name, str(p)) for p in patterns)


def _load_toolsets(path: Path) -> list[dict[str, Any]]:
    """toolsets.yaml → toolset 条目列表（yaml 缺失/损坏向上抛 ValueError）。"""
    import yaml

    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = doc.get("toolsets") or []
    if not isinstance(entries, list):
        raise ValueError("toolsets.yaml toolsets 节非列表")
    return entries


# ─── 引擎入口 ───────────────────────────────────────────────────────────────

def domain_survey(
        *,
        repo_root: Path | None = None,
        cli_app: Any = None,
        registered_tool_names: list[str] | None = None,
) -> dict[str, Any]:
    """三张域词表双向对账（ok 信封；输入面不可读 → error 信封）。

    注入端口：``cli_app``（**必注入**——typer 主 app；service 层禁
    import rfauto.cli，W4-S20 分层修复后不再有缺省 lazy import）、
    ``registered_tool_names``（缺省 toolsets_service 注册面枚举单源）；
    测试以替身注入即可隔离运行时依赖（#144 家法）。
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT

    # V1 计算器组词表
    reg_path = root / "src" / "rfauto" / "core" / "calc_families" / "registry.py"
    reg_src = _read(reg_path)
    if reg_src is None:
        return error_envelope(f"计算器注册表不可读: {reg_path}")
    try:
        order, table, n_literal_skipped = _parse_calc_registry(reg_src)
    except SyntaxError as exc:
        # 输入面语法损坏同"不可读"契约=error 信封（W6-P3-5① 同面：
        # 曾直接出 SyntaxError 轨迹，脚本 rc2 口径拿不到）
        return error_envelope(f"计算器注册表语法不可解析: {reg_path}: {exc}")
    table_values = set(table.values())
    v1_orphan = [o for o in order if o not in table_values]
    v1_missing = sorted(table_values - set(order))
    calc_keys, unparsable_families = _registered_calc_keys(reg_path.parent)
    calc_keys_ungrouped = [k for k in calc_keys if k not in table]
    group_key_counts: dict[str, int] = {}
    for group in table.values():
        group_key_counts[group] = group_key_counts.get(group, 0) + 1
    violations: list[str] = []
    for o in v1_orphan:
        violations.append(f"V1 孤儿词: CALC_GROUP_ORDER 组名「{o}」"
                          "无任何 CALC_GROUP_TABLE 键使用")
    for m in v1_missing:
        violations.append(f"V1 缺词: CALC_GROUP_TABLE 组名「{m}」不在 "
                          "CALC_GROUP_ORDER（UI optgroup 不可见）")

    # V2 CLI 域词表（W4-S20 分层修复：service 禁 import cli——cli 主 app
    # 一律由调用方注入；缺注入=error 信封，不再 lazy import rfauto.cli.main）
    if cli_app is None:
        return error_envelope(
            "cli_app 未注入：service 层禁 import rfauto.cli（分层契约），"
            "由调用方传 typer 主 app（scripts/survey_domains.py 与活体基线"
            "测试均显式 from rfauto.cli.main import app 后注入）")
    groups = _cli_group_names(cli_app)
    dup_groups = sorted({g["name"] for g in groups
                         if g["name"] and [x["name"] for x in groups]
                         .count(g["name"]) > 1})
    empty_groups = [g["name"] for g in groups if not g["command_count"]]
    nameless_groups = sum(1 for g in groups if not g["name"])
    domains_dir = root / "src" / "rfauto" / "cli" / "domains"
    cli_sources: dict[str, str] = {}
    cli_top = root / "src" / "rfauto" / "cli"
    for path in [*sorted(cli_top.glob("*.py")), *sorted(domains_dir.glob("*.py"))]:
        text = _read(path)
        if text is not None:
            cli_sources[path.stem] = text
    orphan_modules = _orphan_cli_domain_modules(domains_dir, cli_sources)
    for g in empty_groups:
        violations.append(f"V2 空组: CLI 顶层组「{g}」零命令零子组"
                          "（help 死词，词表孤儿）")
    for m in orphan_modules:
        violations.append(f"V2 孤儿域模块: cli/domains/{m}.py 不被任何 cli "
                          "入口引用（死文件，域词表声明未注册）")

    # V3 MCP 工具组词表
    toolsets_path = root / "knowledge" / "toolsets.yaml"
    try:
        entries = _load_toolsets(toolsets_path)
    except Exception as exc:
        return error_envelope(f"toolsets.yaml 不可读: {exc}")
    if registered_tool_names is None:
        try:
            from rfauto.service.toolsets_service import (
                enumerate_registered_tool_names,
            )
            registered_tool_names = enumerate_registered_tool_names()
        except Exception as exc:
            return error_envelope(f"MCP 注册面枚举失败: {exc}")
    tool_names = list(registered_tool_names)
    ts_names = [str(e.get("name") or "") for e in entries]
    dup_ts = sorted({n for n in ts_names if n and ts_names.count(n) > 1})
    empty_ts = sum(1 for n in ts_names if not n.strip())
    hint_drift: list[str] = []
    covered: set[str] = set()
    for entry in entries:
        tname = str(entry.get("name") or "?")
        hints = [str(p) for p in (entry.get("tools_hint") or [])]
        if not hints:
            hint_drift.append(f"{tname}: tools_hint 空")
            continue
        hits = {t for t in tool_names if _fnmatch_any(t, hints)}
        covered |= hits
        if not hits:
            hint_drift.append(f"{tname}: 全部 tools_hint 模式对注册面零命中")
    uncovered_tools = sorted(set(tool_names) - covered)
    tools_dir = root / "src" / "rfauto" / "mcp_tools"
    reg_counts = _mcp_tool_registration_counts(tools_dir)
    dead_modules = [m for m, c in reg_counts.items()
                    if m not in _MCP_TOOLS_EXEMPT_MODULES
                    and c["tool"] == 0 and c["resource"] == 0]
    for n in dup_ts:
        violations.append(f"V3 重名: toolset「{n}」重复登记")
    if empty_ts:
        violations.append(f"V3 空名: {empty_ts} 个 toolset 名为空")
    for d in hint_drift:
        violations.append(f"V3 hint 漂移: {d}")
    for m in dead_modules:
        violations.append(f"V3 死组模块: mcp_tools/{m}.py 零注册装饰器"
                          "（工具组词表声明未落地）")

    data = {
        "schema": SCHEMA,
        "calc_groups": {
            "order_count": len(order),
            "table_value_count": len(table_values),
            "table_key_count": len(table),
            "orphan_words": v1_orphan,
            "missing_words": v1_missing,
            "group_key_counts": dict(sorted(group_key_counts.items())),
            "registered_keys": len(calc_keys),
            "registered_keys_ungrouped": calc_keys_ungrouped,
            "non_literal_entries_skipped": n_literal_skipped,
            "family_files_unparsable": unparsable_families,
        },
        "cli_domains": {
            "top_level_group_count": len(groups),
            "group_names": [g["name"] for g in groups],
            "duplicate_groups": dup_groups,
            "empty_groups": empty_groups,
            "nameless_groups": nameless_groups,
            "domain_module_count": sum(
                1 for p in domains_dir.glob("*.py")
                if p.stem not in _CLI_DOMAINS_EXEMPT_MODULES),
            "orphan_modules": orphan_modules,
        },
        "mcp_toolsets": {
            "toolset_count": len(entries),
            "toolset_names": ts_names,
            "duplicate_names": dup_ts,
            "registered_tool_count": len(tool_names),
            "hint_drift": hint_drift,
            "uncovered_tools": uncovered_tools,
            "module_registration_counts": reg_counts,
            "dead_modules": dead_modules,
        },
        "violation_count": len(violations),
        "violations": violations,
    }
    return ok_envelope(**data)
