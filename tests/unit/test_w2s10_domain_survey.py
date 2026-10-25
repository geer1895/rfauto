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
        order, table, skipped = _parse_calc_registry(_REGISTRY_SRC)
        assert order == ["传输线", "天线", "雷达"]
        assert table["dangling"] == "幽灵组"
        assert skipped == 0

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


class TestMisreportSurfacesFixed:
    """三误报面修复钉（aurora_f W2-S8：W5-P3-4/W5-P3-5/W6-P3-5）。

    修复前形态：① 非字面量条目 ``el.value``/``k.value`` 裸 AttributeError
    出轨迹（引擎死而非 error 信封）；② ``^@mcp\\.resource\\(`` 行首+强制
    括号——缩进装饰器/裸 resource 风格误判"死组模块"；③
    ``glob(...)-2`` 硬编码豁免计数，树里无 _core.py 时 domain_module_count
    漂移。每条=行为变更+新用例。
    """

    def test_v1_parser_non_literal_entries_skipped_not_crash(self):
        """非字面量条目跳过+计数，不再 AttributeError（W5-P3-5①）。"""
        src = '''from rfauto.core.calc_families.registry import GROUPS
CALC_GROUP_ORDER: tuple[str, ...] = (
    "传输线",
    GROUPS[0],  # 非字面量：名字引用
    "天线" + "雷达",  # 非字面量：拼接
)

CALC_GROUP_TABLE: dict[str, str] = {
    "mline_analysis": "传输线",
    **EXTRA,  # 非字面量：dict 解包（键节点为 None）
    "patch_f0": SUFFIX,  # 非字面量：值引用
}
'''
        order, table, skipped = _parse_calc_registry(src)
        assert order == ["传输线"]
        assert table == {"mline_analysis": "传输线"}
        assert skipped == 4

    def test_v1_survey_envelope_on_non_literal_registry(self, tmp_path):
        """合成注册表含非字面量条目 → 巡检器 ok 信封 + 跳过计数如实暴露
        （修复前 AttributeError 轨迹，rc2 error 信封契约拿不到）。"""
        src = '''CALC_GROUP_ORDER: tuple[str, ...] = ("传输线", PREFIX)
CALC_GROUP_TABLE: dict[str, str] = {"mline_analysis": "传输线"}
'''
        result = _survey(tmp_path, registry_src=src,
                         domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
                         toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a", "tool_b1"])
        assert result["ok"] is True
        assert result["calc_groups"]["non_literal_entries_skipped"] == 1
        assert result["calc_groups"]["order_count"] == 1

    def test_v1_error_envelope_on_syntax_broken_registry(self, tmp_path):
        """注册表语法损坏 → error 信封（同"输入面不可读"rc2 契约）。"""
        result = _survey(tmp_path, registry_src="CALC_GROUP_ORDER = (\n",
                         domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
                         toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a"])
        assert result["ok"] is False
        assert any("语法不可解析" in e for e in result["errors"])

    def test_v1_unparsable_family_file_skipped_and_counted(self, tmp_path):
        """语法损坏的族文件跳过+列名，巡检整体不炸（W6-P3-5① 同面收口）。

        单个半成品/损坏族文件曾使裸 ast.parse 出轨迹而非降级；#228 在制
        席位半成品不红活体基线——跳过面入报告计数可见，不静默。"""
        root, app, tools = _make_repo(
            tmp_path, registry_src=_CLEAN_REGISTRY_SRC,
            domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
            toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
            tool_names=["tool_a", "tool_b1"])
        (root / "src" / "rfauto" / "core" / "calc_families"
         / "half_done.py").write_text("def broken(:\n", encoding="utf-8")
        result = domain_survey(repo_root=root, cli_app=app,
                               registered_tool_names=tools)
        assert result["ok"] is True
        cg = result["calc_groups"]
        assert cg["family_files_unparsable"] == ["half_done"]
        # 好文件照常解析（mline_analysis+orphan_key 两键在册）
        assert cg["registered_keys"] == 2

    def test_v3_indented_and_bare_resource_decorators_counted(self, tmp_path):
        """缩进装饰器与裸 ``@mcp.resource``（无括号）均计数——修复前
        行首锚+强制括号把该模块误判"死组模块"（W5-P3-4/W6-P3-5②）。"""
        mcp = {"alpha": "@mcp.tool\ndef tool_a():\n    pass\n",
               # 类方法缩进 + 裸 resource（无括号）：双误报面同模块
               "cls_style": (
                   "class Holder:\n"
                   "    @mcp.tool\n"
                   "    def tool_b1(self):\n"
                   "        pass\n"
                   "\n"
                   "    @mcp.resource\n"
                   "    def res_x(self):\n"
                   "        pass\n"
               ),
               "indented_res": (
                   "def setup(mcp):\n"
                   "    @mcp.resource('res://x')\n"
                   "    def x():\n"
                   "        pass\n"
               )}
        result = _survey(tmp_path, registry_src=_CLEAN_REGISTRY_SRC,
                         domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
                         toolsets=_CLEAN_TS, mcp_modules=mcp,
                         tool_names=["tool_a", "tool_b1"])
        counts = result["mcp_toolsets"]["module_registration_counts"]
        assert counts["cls_style"] == {"tool": 1, "resource": 1}
        assert counts["indented_res"] == {"tool": 0, "resource": 1}
        assert not any("死组模块" in v and "cls_style" in v
                       for v in result["violations"])
        assert not any("死组模块" in v and "indented_res" in v
                       for v in result["violations"])

    def test_v3_decorator_lookalike_not_counted(self, tmp_path):
        """``@mcp.resources``/``@mcp.toolkit``（标识符延续）不误计数
        （\\b 词边界口径：下划线/字母延续无词边界）。"""
        from rfauto.service.domain_survey_service import (
            _mcp_tool_registration_counts,
        )
        tools_dir = tmp_path / "mcp_tools"
        tools_dir.mkdir()
        (tools_dir / "m.py").write_text(
            "@mcp.resources('x')\n@mcp.toolkit\ndef f():\n    pass\n",
            encoding="utf-8")
        counts = _mcp_tool_registration_counts(tools_dir)
        assert counts["m"] == {"tool": 0, "resource": 0}

    def test_v2_domain_module_count_without_core_module(self, tmp_path):
        """合成树无 _core.py → 计数=非豁免模块实数（修复前 −2 硬编码
        把 maindom+alpha 数成 0，W6-P3-5③）。"""
        result = _survey(tmp_path, registry_src=_CLEAN_REGISTRY_SRC,
                         domains=dict(_CLEAN_DOMAINS), groups=_CLEAN_GROUPS,
                         toolsets=_CLEAN_TS, mcp_modules=_CLEAN_MCP,
                         tool_names=["tool_a", "tool_b1"])
        # 合成树 domains/：__init__ 无、maindom+alpha 两个非豁免模块
        assert result["cli_domains"]["domain_module_count"] == 2

    def test_v2_live_tree_count_matches_exempt_set(self):
        """活体树计数与豁免集单源口径一致（非豁免模块数）。"""
        domains_dir = Path(__file__).resolve().parents[2] / "src" \
            / "rfauto" / "cli" / "domains"
        stems = {p.stem for p in domains_dir.glob("*.py")}
        expected = len(stems - {"__init__", "_core"})
        result = domain_survey(cli_app=_live_cli_app)
        assert result["cli_domains"]["domain_module_count"] == expected
        assert result["ok"] is True


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
