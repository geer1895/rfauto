"""域词表巡检引擎单测（UX-B13/Z-8 survey domains，aurora_e W2-S10 U3）。

两层口径：
- 探测器灵敏度：合成 repo_root（最小 registry.py/cli 树/toolsets.yaml/
  mcp_tools 树）+ 注入 cli_app/registered_tool_names 替身（#144 家法，
  不触真实注册面），五类红面各注入一、逐一被抓，干净合成树放行；
- 活体基线冻结：真实仓树零违例（V1 ORDER↔TABLE 双向、V2 空组/孤儿
  模块、V3 hint 漂移/死组模块）。活体红=词表与注册面真实漂移，先自查
  并行席位在制状态再动手（#228：S9 席 core/calc_families 在制时报告面
  数字会漂，红面双向对账不受键数增减影响）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from rfauto.cli.main import app as _live_cli_app
from rfauto.service.domain_survey_service import (
    _parse_calc_registry,
    domain_survey,
)


def _fake_app(groups: list[tuple[str, int]]) -> Any:
    return SimpleNamespace(registered_groups=[
        SimpleNamespace(name=name, typer_instance=SimpleNamespace(
            registered_commands=[1] * n, registered_groups=[]))
        for name, n in groups
    ])


_REGISTRY_SRC = '''"""合成注册表。"""
CALC_GROUP_ORDER: tuple[str, ...] = (
    "传输线",
    "天线",
    "雷达",
)

CALC_GROUP_TABLE: dict[str, str] = {
    "mline_analysis": "传输线",
    "patch_f0": "天线",
    "dangling": "幽灵组",
}
'''

_FAMILY_SRC = '''from rfauto.core.calc_families.registry import register_calculator

@register_calculator("mline_analysis")
def mline_analysis():
    pass

@register_calculator("orphan_key")
def orphan_key():
    pass
'''

#: 干净注册表源（无孤儿词/缺词）——clean 树用
_CLEAN_REGISTRY_SRC = '''"""合成注册表（干净）。"""
CALC_GROUP_ORDER: tuple[str, ...] = (
    "传输线",
    "天线",
)

CALC_GROUP_TABLE: dict[str, str] = {
    "mline_analysis": "传输线",
    "patch_f0": "天线",
}
'''


def _make_repo(
        tmp_path: Path, *, registry_src: str = _REGISTRY_SRC,
        domains: dict[str, str], groups: list[tuple[str, int]],
        toolsets: list[dict[str, Any]], mcp_modules: dict[str, str],
        tool_names: list[str],
) -> tuple[Path, Any, list[str]]:
    """最小合成仓 → (repo_root, cli_app 替身, 注册工具名替身)。"""
    root = tmp_path / "repo"
    fam = root / "src" / "rfauto" / "core" / "calc_families"
    fam.mkdir(parents=True)
    (fam / "registry.py").write_text(registry_src, encoding="utf-8")
    (fam / "mline.py").write_text(_FAMILY_SRC, encoding="utf-8")
    cli = root / "src" / "rfauto" / "cli"
    dom = cli / "domains"
    dom.mkdir(parents=True)
    refs = domains.pop("_extra_refs", [])
    (cli / "main.py").write_text(
        "from rfauto.cli.domains.maindom import x\n"
        + "".join(f"from rfauto.cli.domains.{n} import y\n" for n in refs),
        encoding="utf-8")
    (dom / "maindom.py").write_text("x = 0\n", encoding="utf-8")
    for name, text in domains.items():
        (dom / f"{name}.py").write_text(text, encoding="utf-8")
    kg = root / "knowledge"
    kg.mkdir(parents=True)
    (kg / "toolsets.yaml").write_text(
        yaml.safe_dump({"schema": "rfauto-toolsets-v1", "toolsets": toolsets},
                       allow_unicode=True), encoding="utf-8")
    tdir = root / "src" / "rfauto" / "mcp_tools"
    tdir.mkdir(parents=True)
    for name, text in mcp_modules.items():
        (tdir / f"{name}.py").write_text(text, encoding="utf-8")
    return root, _fake_app(groups), tool_names


def _survey(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    root, app, tools = _make_repo(tmp_path, **kwargs)
    return domain_survey(repo_root=root, cli_app=app,
                         registered_tool_names=tools)


_CLEAN_DOMAINS = {"alpha": "x = 1\n", "_extra_refs": ["alpha"]}
_CLEAN_GROUPS = [("g_one", 2), ("g_two", 1)]
_CLEAN_TS = [{"name": "ts_a", "tools_hint": ["tool_a"]},
             {"name": "ts_b", "tools_hint": ["tool_b*"]}]
_CLEAN_MCP = {"alpha": "@mcp.tool\ndef tool_a():\n    pass\n",
              "beta": "@mcp.tool\ndef tool_b1():\n    pass\n"}


class TestDetectorSensitivity:
    def test_clean_synthetic_tree_zero_violations(self, tmp_path):
        result = _survey(tmp_path, registry_src=_CLEAN_REGISTRY_SRC,
                         domains=dict(_CLEAN_DOMAINS),
                         groups=_CLEAN_GROUPS, toolsets=_CLEAN_TS,
                         mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a", "tool_b1"])
        assert result["ok"] is True
        assert result["violation_count"] == 0, result["violations"]
        # 报告面在场：未覆盖工具/未分组键如实列出，不判红（B4"空白≠立项"）
        assert result["mcp_toolsets"]["uncovered_tools"] == []
        assert result["calc_groups"]["registered_keys_ungrouped"] == ["orphan_key"]

    def test_v1_orphan_and_missing_words(self, tmp_path):
        # ORDER 的「雷达」零键使用=孤儿词；TABLE 值「幽灵组」不在 ORDER=缺词
        result = _survey(tmp_path, domains=dict(_CLEAN_DOMAINS),
                         groups=_CLEAN_GROUPS, toolsets=_CLEAN_TS,
                         mcp_modules=_CLEAN_MCP, tool_names=["tool_a"])
        vs = result["violations"]
        assert any("V1 孤儿词" in v and "雷达" in v for v in vs)
        assert any("V1 缺词" in v and "幽灵组" in v for v in vs)

    def test_v1_parser_ann_assign(self):
        order, table = _parse_calc_registry(_REGISTRY_SRC)
        assert order == ["传输线", "天线", "雷达"]
        assert table["dangling"] == "幽灵组"

    def test_v2_empty_group_and_orphan_module(self, tmp_path):
        domains = {"alpha": "x = 1\n", "lonely": "z = 3\n",
                   "_extra_refs": ["alpha"]}
        result = _survey(tmp_path, domains=domains,
                         groups=[("g_one", 2), ("dead", 0)],
                         toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a", "tool_b1"])
        vs = result["violations"]
        assert any("V2 空组" in v and "dead" in v for v in vs)
        assert any("V2 孤儿域模块" in v and "lonely" in v for v in vs)

    def test_v3_hint_drift_and_dead_module_and_dup(self, tmp_path):
        toolsets = [{"name": "ts_a", "tools_hint": ["nomatch*"]},
                    {"name": "ts_a", "tools_hint": ["tool_a"]},
                    {"name": "", "tools_hint": ["tool_a"]}]
        mcp = {"alpha": "@mcp.tool\ndef tool_a():\n    pass\n",
               "zombie": "x = 1\n"}
        result = _survey(tmp_path, domains=dict(_CLEAN_DOMAINS),
                         groups=_CLEAN_GROUPS, toolsets=toolsets,
                         mcp_modules=mcp, tool_names=["tool_a"])
        vs = result["violations"]
        assert any("V3 hint 漂移" in v and "ts_a" in v for v in vs)
        assert any("V3 重名" in v and "ts_a" in v for v in vs)
        assert any("V3 空名" in v for v in vs)
        assert any("V3 死组模块" in v and "zombie" in v for v in vs)

    def test_v3_uncovered_tools_report_only(self, tmp_path):
        result = _survey(tmp_path, registry_src=_CLEAN_REGISTRY_SRC,
                         domains=dict(_CLEAN_DOMAINS),
                         groups=_CLEAN_GROUPS, toolsets=_CLEAN_TS,
                         mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a", "tool_b1", "tool_x"])
        assert result["violation_count"] == 0
        assert result["mcp_toolsets"]["uncovered_tools"] == ["tool_x"]

    def test_error_envelope_on_missing_registry(self, tmp_path):
        result = domain_survey(repo_root=tmp_path, cli_app=_fake_app([]),
                               registered_tool_names=[])
        assert result["ok"] is False
        assert result["errors"]

    def test_error_envelope_when_cli_app_not_injected(self, tmp_path):
        """W4-S20 分层修复钉：service 禁 import cli——cli_app 缺注入=
        error 信封（不再有缺省 lazy import rfauto.cli.main 的后门）。"""
        root, _app, tools = _make_repo(
            tmp_path, domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
            toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
            tool_names=["tool_a"])
        result = domain_survey(repo_root=root, registered_tool_names=tools)
        assert result["ok"] is False
        assert any("cli_app 未注入" in e for e in result["errors"])


class TestLiveTreeBaseline:
    """活体零违例基线冻结（真实仓树；红=词表↔注册面真实漂移）。

    W4-S20 分层修复后 cli 主 app 由本测试（调用方）显式注入。
    """

    def test_live_tree_zero_violations(self):
        result = domain_survey(cli_app=_live_cli_app)
        assert result["ok"] is True
        assert result["violation_count"] == 0, result["violations"]

    def test_live_tree_shapes_sane(self):
        result = domain_survey(cli_app=_live_cli_app)
        assert result["calc_groups"]["order_count"] >= 10
        assert result["cli_domains"]["top_level_group_count"] >= 50
        assert result["mcp_toolsets"]["toolset_count"] >= 10
        assert result["mcp_toolsets"]["registered_tool_count"] >= 100
