"""EC-6 工具集目录服务（W5-D）：toolsets.yaml 单一真源 + 注册面自动枚举。

规格（runs/research_seats_20261004/se_specs3/SPECS.md §2.2）：
- yaml 只持 name/description/skill/tools_hint——**tools 成员名单不在 yaml 手写**，
  输出时按 mcp_tools 注册面自动枚举（check_numbers 同法的装饰器行正则），
  单一真源防 yaml 与注册面漂移；
- 任一 tools_hint 模式对注册面零命中 → ok=False 报 drift（不凑）；
- skill 必须非空且含 ≥1 个出处标记（坑号 #NNN 或 rfauto 命令名）——空/缺标记
  → errors 显式；
- 零网络零 LLM（#139 语义），同输入两次调用逐位一致。
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "TOOLSETS_RESOURCE_URI",
    "TOOLSETS_SCHEMA",
    "build_toolsets_definition",
    "default_toolsets_yaml_path",
    "enumerate_registered_tool_names",
    "mcp_source_files",
    "repo_root",
]

#: 资源 URI（保持本仓 rfauto:// scheme——池原文 toolsets://definition 是
#: pyaedt-mcp 自家 scheme，沿用会破本仓 URI 命名一致性，spec §2.2.2 裁决）
TOOLSETS_RESOURCE_URI = "rfauto://toolsets/definition"

#: 工具集目录 schema 版本（recipe_version 与 schema_version 语义区分，#106）
TOOLSETS_SCHEMA = "rfauto-toolsets-v1"

_DECORATOR_PREFIX = "@mcp.tool"
_DEF_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)")
_SKILL_PIT_RE = re.compile(r"#\d{1,4}")
_SKILL_CLI_RE = re.compile(r"`rfauto[ A-Za-z0-9_:-]*`")


def repo_root() -> Path:
    """仓根（本文件三层深 src/rfauto/service/，CWD 无关锚）。"""
    return Path(__file__).resolve().parents[3]


def default_toolsets_yaml_path() -> Path:
    """tracked 的工具集目录 yaml（人工编辑面，增删走 commit）。"""
    return repo_root() / "knowledge" / "toolsets.yaml"


def mcp_source_files(root: str | Path | None = None) -> list[Path]:
    """MCP 源码文件集：facade + mcp_tools/ 全集（scripts/check_numbers.py
    count_mcp 同法同界——工具注册面枚举必须与计数口径同源）。"""
    base = Path(root) if root is not None else repo_root() / "src" / "rfauto"
    return [base / "mcp_server.py", *sorted((base / "mcp_tools").rglob("*.py"))]


def enumerate_registered_tool_names(root: str | Path | None = None) -> list[str]:
    """按装饰器行枚举注册面工具名（确定性、不依赖运行时事件循环）。

    `@mcp.tool` 行定位其后第一个 def/async def 的名字（与
    tests/unit/test_mcp_tool_consistency.py::_decorated_function_names 同法）；
    跨文件保序去重（同名单一真源）。资源函数内可用——不进 asyncio，
    规避资源回调里嵌套事件循环的不可重入问题。
    """
    names: list[str] = []
    for f in mcp_source_files(root):
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not line.startswith(_DECORATOR_PREFIX):
                continue
            for follow in lines[index + 1:]:
                match = _DEF_RE.match(follow)
                if match:
                    name = match.group(1)
                    if name not in names:
                        names.append(name)
                    break
                # 装饰器实参续行（@mcp.tool(...) 多参形态：缩进行/闭括号行/
                # 叠加装饰器行/空行）——继续找真 def 行
                stripped = follow.strip()
                if (not stripped or follow.startswith(("@", " ", "\t"))
                        or stripped.startswith(")")):
                    continue
                break  # 顶层非 def 行：装饰器悬空（异常形态，跳过）
    return names


def _as_hint_list(raw: Any) -> list[str]:
    """tools_hint 容错归一：None → 空表；str → 单元素；其余可迭代 → 列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Iterable):
        return [str(item) for item in raw]
    return [str(raw)]


def build_toolsets_definition(
    yaml_path: str | Path | None = None,
    tool_names: list[str] | None = None,
) -> dict[str, Any]:
    """构建工具集目录资源负载（信封进出，规则 4）。

    Args:
        yaml_path: 工具集 yaml 路径（缺省 tracked 的 knowledge/toolsets.yaml；
            测试传 tmp 样本造 drift/坏 skill 分歧）。
        tool_names: 注册面名单（缺省按源码面自动枚举；测试可注入合成名单）。

    Returns:
        dict: ok 信封 {ok, uri, schema, toolsets: [{name, description, skill,
        tools_hint, tools}], registry_count, covered_count, uncovered}；
        结构错/hint 零命中（drift）/skill 缺出处标记 → error 信封
        {ok: False, errors: [...]}（toolsets 已构建部分随行留痕）。
    """
    path = Path(yaml_path) if yaml_path is not None else default_toolsets_yaml_path()
    if not path.is_file():
        return error_envelope([f"toolsets yaml 不存在: {path}"])
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return error_envelope([f"toolsets yaml 解析失败: {exc}"])
    if not isinstance(data, dict):
        return error_envelope(["toolsets yaml 顶层必须是映射"])
    if data.get("schema") != TOOLSETS_SCHEMA:
        return error_envelope(
            [f"schema 版本不符: 期望 {TOOLSETS_SCHEMA}，实得 {data.get('schema')!r}"]
        )
    entries = data.get("toolsets")
    if not isinstance(entries, list) or not entries:
        return error_envelope(["toolsets 不能为空（至少一个工具集）"])

    names = list(tool_names) if tool_names is not None else enumerate_registered_tool_names()
    errors: list[str] = []
    seen: set[str] = set()
    toolsets_out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("toolset 条目必须是映射")
            continue
        name = str(entry.get("name") or "").strip()
        description = str(entry.get("description") or "").strip()
        skill = str(entry.get("skill") or "").strip()
        hints = _as_hint_list(entry.get("tools_hint"))
        if not name:
            errors.append("toolset 缺 name")
            continue
        if name in seen:
            errors.append(f"toolset 名重复: {name}")
            continue
        seen.add(name)
        if not description:
            errors.append(f"{name}: description 为空")
        if not skill:
            errors.append(f"{name}: skill 为空（调用时序文本必填）")
        elif not (_SKILL_PIT_RE.search(skill) or _SKILL_CLI_RE.search(skill)):
            errors.append(f"{name}: skill 缺出处标记（坑号 #NNN 或 rfauto 命令名）")
        matched = sorted({n for pat in hints for n in names if fnmatch.fnmatchcase(n, pat)})
        for pat in hints:
            if not any(fnmatch.fnmatchcase(n, pat) for n in names):
                errors.append(f"{name}: tools_hint 模式对注册面零命中（drift）: {pat}")
        toolsets_out.append(
            {
                "name": name,
                "description": description,
                "skill": skill,
                "tools_hint": hints,
                "tools": matched,
            }
        )
    covered = sorted({t for ts in toolsets_out for t in ts["tools"]})
    uncovered = sorted(set(names) - set(covered))
    if errors:
        return error_envelope(
            errors,
            uri=TOOLSETS_RESOURCE_URI,
            toolsets=toolsets_out,
            registry_count=len(names),
        )
    return ok_envelope(
        uri=TOOLSETS_RESOURCE_URI,
        schema=TOOLSETS_SCHEMA,
        toolsets=toolsets_out,
        registry_count=len(names),
        covered_count=len(covered),
        uncovered=uncovered,
    )
