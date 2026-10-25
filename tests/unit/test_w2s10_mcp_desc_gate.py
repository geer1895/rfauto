"""MCP 描述单源门（Z-10）单测（aurora_e W2-S10 E2）。

两层口径：
- 探测器灵敏度：合成工具对象注入五维违例各一，逐一被抓（负样本）；
  干净合成工具放行（正样本）；EXEMPTIONS 豁免生效；
- 活体基线冻结：真实 fastmcp 注册面（152 工具）五维零违例——新增
  工具/参数描述漂移在脚本门与本测试双落红。

活体用例依赖 fastmcp：与 test_mcp_tool_consistency 同前提（缺环境按
ImportError skip，不判红——CI 无重依赖环境诚实降级）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from scripts.check_mcp_desc import (
    EXEMPTIONS,
    ToolReport,
    check_tool,
    documented_args,
    run_check,
)


def _tool(name: str, doc: str, parameters: dict[str, Any],
          description: str = "工具描述") -> SimpleNamespace:
    def fn(**_kwargs: Any) -> dict[str, Any]:
        return {}

    fn.__doc__ = doc
    return SimpleNamespace(name=name, description=description,
                           parameters=parameters, fn=fn)


_CLEAN_DOC = """工具摘要。

Args:
    recipe: 配方路径
    limit: 返回条数上限

Returns:
    信封
"""


class TestDetectorSensitivity:
    def test_clean_tool_passes(self):
        tool = _tool("t_ok", _CLEAN_DOC, {
            "properties": {
                "recipe": {"type": "string", "description": "配方路径"},
                "limit": {"type": "integer", "description": "返回条数上限"},
            },
            "required": ["recipe"],
        })
        assert check_tool(tool, ToolReport(name="t_ok")).violations == []

    def test_dim1_empty_tool_description(self):
        tool = _tool("t1", _CLEAN_DOC, {"properties": {}, "required": []},
                     description="   ")
        vs = check_tool(tool, ToolReport(name="t1")).violations
        assert any(v.startswith("dim1") for v in vs)

    def test_dim2_required_missing_in_docstring(self):
        tool = _tool("t2", "摘要。\n\nArgs:\n    limit: 上限\n",
                     {"properties": {
                         "recipe": {"description": "配方"},
                         "limit": {"description": "上限"}},
                      "required": ["recipe"]})
        vs = check_tool(tool, ToolReport(name="t2")).violations
        assert any(v.startswith("dim2") and "recipe" in v for v in vs)

    def test_dim3_schema_desc_empty(self):
        tool = _tool("t3", _CLEAN_DOC, {
            "properties": {
                "recipe": {"description": "配方路径"},
                "limit": {"description": ""},
            },
            "required": ["recipe"]})
        vs = check_tool(tool, ToolReport(name="t3")).violations
        assert any(v.startswith("dim3") and "limit" in v for v in vs)

    def test_dim4_single_source_mismatch(self):
        tool = _tool("t4", _CLEAN_DOC, {
            "properties": {
                "recipe": {"description": "被手改过的另一份描述"},
                "limit": {"description": "返回条数上限"},
            },
            "required": ["recipe"]})
        vs = check_tool(tool, ToolReport(name="t4")).violations
        assert any(v.startswith("dim4") and "recipe" in v for v in vs)

    def test_dim5_ghost_param(self):
        doc = ("摘要。\n\nArgs:\n    recipe: 配方路径\n"
               "    limit: 返回条数上限\n    phantom: schema 里没有的参数\n"
               "\nReturns:\n    信封\n")
        tool = _tool("t5", doc, {
            "properties": {
                "recipe": {"description": "配方路径"},
                "limit": {"description": "返回条数上限"},
            },
            "required": ["recipe"]})
        vs = check_tool(tool, ToolReport(name="t5")).violations
        assert any(v.startswith("dim5") and "phantom" in v for v in vs)

    def test_multiline_doc_entry_matches_schema_newline_form(self):
        # fastmcp 把多行 Args 描述以换行并入 schema description——
        # 空白归一后必须逐字相等（单源一致的真形态）
        tool = _tool("t6", "摘要。\n\nArgs:\n    stages: 级链描述，\n        第二行续写\n",
                     {"properties": {"stages": {
                         "description": "级链描述，\n第二行续写"}},
                      "required": []})
        assert check_tool(tool, ToolReport(name="t6")).violations == []

    def test_documented_args_continuation_lines(self):
        fn = _make_fn("摘要。\n\nArgs:\n    stages: 级链描述，\n        第二行续写\n\n"
                      "Returns:\n    信封\n")
        assert documented_args(fn) == {"stages": "级链描述，\n第二行续写"}

    def test_documented_args_section_end_stops(self):
        fn = _make_fn("摘要。\n\nArgs:\n    a: 参数a\nNote:\n    b: 不是参数\n")
        assert documented_args(fn) == {"a": "参数a"}

    def test_documented_args_colon_continuations_not_ghosts(self):
        # W8-S36（审查波 2 P2-1 三形态回归钉）：Args 段内 Google 风格
        # 惯用续行（`Default: 0.1`/`Note: ...`/行内 `Returns: ...`）此前
        # 各自生成幽灵条目（dim5 假红拦合流）——须并入上一参数描述。
        fn = _make_fn(
            "摘要。\n\nArgs:\n    tol: 容差\n"
            "        Default: 0.1\n        Note: must be positive.\n"
            "        Returns: nothing useful\n\nReturns:\n    信封\n")
        assert documented_args(
            fn, known_names={"tol"}) == {
                "tol": "容差\nDefault: 0.1\nNote: must be positive.\n"
                       "Returns: nothing useful"}

    def test_colon_continuation_tool_check_zero_violations(self):
        # 端到端：含 Default:/Note: 续行的工具五维零违例（假红形态不再发生；
        # fastmcp 把多行描述按换行并入 schema description 的口径）
        doc = ("摘要。\n\nArgs:\n    tol: 容差\n        Default: 0.1\n"
               "        Note: must be positive.\n\nReturns:\n    信封\n")
        tool = _tool("t_cont", doc, {
            "properties": {"tol": {
                "type": "number",
                "description": "容差\nDefault: 0.1\nNote: must be positive."}},
            "required": []})
        assert check_tool(tool, ToolReport(name="t_cont")).violations == []

    def test_real_ghost_param_still_caught(self):
        # 真幽灵参数（schema 没有的非保留标识符）在新判定下仍被 dim5 抓
        fn = _make_fn("摘要。\n\nArgs:\n    a: 参数a\n"
                      "    ghost_param: schema 里没有的参数\n\nReturns:\n    x\n")
        assert documented_args(fn, known_names={"a"}) == {
            "a": "参数a", "ghost_param": "schema 里没有的参数"}


def _make_fn(doc: str) -> Any:
    def fn() -> None:
        pass
    fn.__doc__ = doc
    return fn


class TestExemptions:
    def test_exemption_suppresses_dim34_only(self, monkeypatch):
        monkeypatch.setitem(EXEMPTIONS, "t_ex", ["limit"])
        tool = _tool("t_ex", _CLEAN_DOC, {
            "properties": {
                "recipe": {"description": "配方路径"},
                "limit": {"description": ""},
            },
            "required": ["recipe"]})
        vs = check_tool(tool, ToolReport(name="t_ex")).violations
        assert vs == []  # limit dim3 被豁免

    def test_exemption_does_not_cover_dim125(self, monkeypatch):
        monkeypatch.setitem(EXEMPTIONS, "t_ex2", ["recipe"])
        tool = _tool("t_ex2", "摘要。\n\nArgs:\n    recipe: 配方\n",
                     {"properties": {"recipe": {"description": "配方"}},
                      "required": ["ghost_req"]})
        vs = check_tool(tool, ToolReport(name="t_ex2")).violations
        assert any(v.startswith("dim2") for v in vs)  # 豁免不覆盖必填缺失

    def test_run_check_freeze_baseline_exempt_table_empty(self):
        # 基线冻结纪律：挂面时豁免表必须为空（只收不放的起点）
        assert EXEMPTIONS == {}


class TestLiveRegistryBaseline:
    """活体基线冻结：真实注册面五维零违例（fastmcp 缺席=skip）。"""

    def test_live_registry_zero_violations(self):
        from scripts.check_mcp_desc import collect_registered_tools
        try:
            tools = collect_registered_tools()
        except Exception as exc:  # pragma: no cover - 无 fastmcp 环境
            pytest.skip(f"fastmcp 注册面不可用：{exc}")
        report = run_check(tools)
        assert report["tool_count"] >= 100  # 计数锚（152@2026-10-18）
        assert report["ok"] is True, report["violations"]
