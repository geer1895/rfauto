"""W2-B 席（VI-3 模板推荐器 + TEMPLATE_SPECS 49→71 + UX-A7 深链）单测。

规格=runs/research_seats_20261004/sp_specs6/SPECS.md §VI-3 + 批判据
runs/w2_phase2/criteria.md W2-B 节。判据（预声明门值）：
① TEMPLATE_SPECS names()=71（bootstrap 后真跑计数）；
② recommend 三组预声明查询 top-1 golden 稳定；
③ 推荐函数零外部调用（monkeypatch 钉网络面，#139）；
④ 22 模板 draft_recipe 冒烟全过（名义逐键回代）；
⑤ 深链 71 卡路径逐一 os.path 断言存在；
⑥ rerank 缺省路径零变化（None 负控）+ 生效/降级两档。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import ClassVar

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
from rfauto.models.template_spec import TEMPLATE_SPECS
from rfauto.models.template_specs import bootstrap_template_specs
from rfauto.service.gallery_service import (
    RECOMMEND_F0_TOL,
    gallery_cards,
    recommend_templates,
)

#: §VI-3 实测缺 22 名单（2026-10-04 接地；W2-B 开工差集复核逐位一致）。
W2B_NEW_TEMPLATES: tuple[str, ...] = (
    "coax_waveguide_transition", "diplexer", "embedded_ms", "fgcpw",
    "hmsiw", "inverted_ms", "isl_shielded", "ms_array_NxN", "ms_cross",
    "ms_jcross", "ms_patch", "ms_ring_patch", "nway_wilkinson",
    "pyramid_horn", "qwt_multisection", "ridged_wg", "ring_resonator",
    "schiffman", "sicl", "varactor_bpf", "vivaldi_tsa", "xcheb_bpf4",
)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    old = os.getcwd()
    os.chdir(REPO)  # 综合链需 configs/materials.yaml（#144 同款隔离口径）
    bootstrap_template_specs()
    yield
    os.chdir(old)


# ═══ 判据①：TEMPLATE_SPECS names()=71 真跑计数 ═══════════════════════════════


class TestSpecCoverage71:
    def test_names_equal_template_meta_71(self):
        assert len(TEMPLATE_META) == 71
        assert TEMPLATE_SPECS.names() == sorted(TEMPLATE_META)
        assert len(TEMPLATE_SPECS.names()) == 71

    def test_w2b_22_newly_registered(self):
        missing = sorted(set(W2B_NEW_TEMPLATES) - set(TEMPLATE_SPECS.names()))
        assert not missing, f"VI-3 缺口未闭合: {missing}"

    def test_new_specs_have_synthesizer_and_render(self):
        rows = {t["name"]: t for t in TEMPLATE_SPECS.describe()}
        for name in W2B_NEW_TEMPLATES:
            comp = rows[name]["components"]
            assert comp["synthesizer"], name
            assert comp["render_script"], name
            # 22 模板无已标定 fake 前向模型——显式缺失语义（可见但不可用，
            # 绝不静默）；调用面抛 TemplateComponentMissing（不静默）。
            assert comp["fake_model"] is False, name
            assert comp["hfss_plugin"] is None, name  # 纯 openEMS 锚模板

    def test_new_spec_fake_component_missing_raises(self):
        from rfauto.models.template_spec import TemplateComponentMissing

        with pytest.raises(TemplateComponentMissing, match="fake_model"):
            TEMPLATE_SPECS.component("sicl", "fake_model")


# ═══ 判据④：22 模板 draft_recipe 冒烟全过（名义逐键回代）═════════════════════


class TestDraftRecipeSmoke22:
    @pytest.mark.parametrize("name", W2B_NEW_TEMPLATES)
    def test_draft_smoke_and_nominal_roundtrip(self, name):
        draft = TEMPLATE_SPECS.draft_recipe(name)
        assert draft["model"] == name
        assert draft["recipe_version"] == 1 and draft["schema_version"] == 1
        assert draft["params"], name
        assert draft["objectives"], name
        # #252：缺省实参必须逐键复现 TEMPLATE_NOMINAL 名义值（毫秒链真复算
        # 或 FD 慢链名义引用——两口径都不许手抄毫米数漂移）。
        nominal = TEMPLATE_NOMINAL[name]
        for key, want in nominal.items():
            got = draft["params"].get(key, {}).get("value")
            assert got == want, f"{name}.{key}: draft={got!r} nominal={want!r}"

    def test_synthesizer_takes_f0_argument(self):
        """综合入口可按 f0 移点（快链真重算；hmsiw fc=f0/1.5 规则）。"""
        r = TEMPLATE_SPECS.draft_recipe("hmsiw", f0_ghz=6.0)
        # fc 目标=6.0/1.5=4.0GHz → 物理宽变大（w 随 fc 目标降单调增）
        w6 = r["params"]["w_mm"]["value"]
        w10 = TEMPLATE_SPECS.draft_recipe("hmsiw")["params"]["w_mm"]["value"]
        assert w6 > w10 > 0


# ═══ 判据②：recommend 三组预声明查询 top-1 golden ════════════════════════════


class TestRecommendGolden:
    def test_golden_1_bpf_at_2p4(self):
        """规格示例查询：f0=2.4/topology=bpf → coupled_bpf 族首。"""
        r = recommend_templates(f0_ghz=2.4, topology="bpf", top_k=3)
        assert r["ok"] and r["n_candidates"] >= 1
        assert r["recommendations"][0]["name"] == "coupled_bpf"
        assert r["provider"] == "deterministic"
        assert not r["reranked"] and not r["degraded"]

    def test_golden_2_horn_at_10(self):
        """f0=10/topology=喇叭 → pyramid_horn（拓扑文本子串命中）。"""
        r = recommend_templates(f0_ghz=10.0, topology="喇叭", top_k=3)
        assert r["n_candidates"] >= 1
        assert r["recommendations"][0]["name"] == "pyramid_horn"

    def test_golden_3_antenna_array_at_5p8(self):
        """f0=5.8/topology=antenna → patch_array_2x2（rank 全链：f0_dev=0
        并列组内次键 semantics 覆盖数逐位定序）。"""
        r = recommend_templates(f0_ghz=5.8, topology="antenna", top_k=5)
        names = [c["name"] for c in r["recommendations"]]
        assert names[0] == "patch_array_2x2"
        assert names == sorted(names, key=names.index)  # 信封序=排序序

    def test_rank_total_order_deterministic_repeat(self):
        """全序确定性：同查询重复调用名单逐位一致。"""
        kw = dict(f0_ghz=10.0, n_ports=2, top_k=8)
        r1 = recommend_templates(**kw)
        r2 = recommend_templates(**kw)
        a = [c["name"] for c in r1["recommendations"]]
        b = [c["name"] for c in r2["recommendations"]]
        assert a == b
        assert len(a) == min(8, r1["n_candidates"])
        assert r1["query"] == r2["query"]


# ═══ 判据③：推荐零外部调用（monkeypatch 钉网络面，#139）═════════════════════


class TestRecommendNoExternalCalls:
    def test_no_network_on_deterministic_path(self, monkeypatch):
        import socket
        import urllib.request

        def _boom(*a, **k):  # pragma: no cover - 触发即失败
            raise AssertionError("推荐函数走了外部调用（#139 违约）")

        monkeypatch.setattr(socket, "socket", _boom)
        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        r = recommend_templates(f0_ghz=2.4, topology="bpf", top_k=3)
        assert r["ok"] and r["recommendations"][0]["name"] == "coupled_bpf"

    def test_zero_llm_zero_physics_output_shape(self):
        """输出=模板名+排序分解（铁律 7）：无任何求解/响应字段。"""
        r = recommend_templates(f0_ghz=2.5, top_k=2)
        for card in r["recommendations"]:
            assert set(card) <= {
                "name", "family", "family_label", "topology", "f0_ghz",
                "n_ports", "docs_link", "preview", "rank"}
            assert set(card["rank"]) == {
                "f0_dev", "semantics_covered", "preview"}


# ═══ 判据⑥：rerank 缺省零变化负控 + 生效/降级两档 ═══════════════════════════


class TestRerankProviderContract:
    BASE_KW: ClassVar[dict] = {"f0_ghz": 10.0, "n_ports": 2,
                               "top_k": 4}

    def test_none_negative_control_byte_identical(self):
        """缺省 None=纯确定性路径：零 provider 调用（负控 spy 钉）。"""
        calls: list = []

        def _spy(candidates, query):
            calls.append((list(candidates), dict(query)))
            return list(candidates)

        r_none = recommend_templates(**self.BASE_KW, rerank_provider=None)
        r_plain = recommend_templates(**self.BASE_KW)
        assert r_none == r_plain  # 显式 None 与省略逐字节不变
        assert r_none["provider"] == "deterministic"
        assert not r_none["reranked"] and not r_none["degraded"]
        assert not calls  # None/省略路径零 provider 调用（负控）
        recommend_templates(**self.BASE_KW, rerank_provider=_spy)
        assert len(calls) == 1  # 通道只在显式传入时启用

    def test_provider_reorder_effective(self):
        full = [c["name"] for c in recommend_templates(
            f0_ghz=10.0, n_ports=2, top_k=100)["recommendations"]]
        flipped = list(reversed(full))

        def provider(candidates, query):
            assert candidates == full
            assert query["f0_ghz"] == 10.0
            return flipped

        r = recommend_templates(**self.BASE_KW, rerank_provider=provider)
        assert r["reranked"] and not r["degraded"]
        assert [c["name"] for c in r["recommendations"]] == flipped[:4]

    def test_provider_envelope_shape_accepted(self):
        """ask_systemone 同形信封（answer.order）亦可接入（仅契约）。"""
        full = [c["name"] for c in recommend_templates(
            f0_ghz=10.0, n_ports=2, top_k=100)["recommendations"]]

        def provider(candidates, query):
            return {"ok": True, "answer": {"order": list(reversed(candidates))}}

        r = recommend_templates(**self.BASE_KW, rerank_provider=provider)
        assert r["reranked"]
        assert [c["name"] for c in r["recommendations"]] == list(
            reversed(full))[:4]

    def test_provider_bad_permutation_degrades_honestly(self):
        base = recommend_templates(**self.BASE_KW)

        def provider(candidates, query):
            return ["not_a_template"]  # 非法置换

        r = recommend_templates(**self.BASE_KW, rerank_provider=provider)
        assert r["degraded"] and r["degrade_reason"]
        # 降级=保持确定性序原样（#105 家法）；信封仅 degraded/reason 两键如实
        assert r["recommendations"] == base["recommendations"]
        assert not r["reranked"] and r["provider"] == "deterministic"

    def test_provider_raise_degrades_honestly(self):
        base = recommend_templates(**self.BASE_KW)

        def provider(candidates, query):
            raise RuntimeError("provider 故障")

        r = recommend_templates(**self.BASE_KW, rerank_provider=provider)
        assert r["degraded"] and "provider 故障" in r["degrade_reason"]
        assert r["recommendations"] == base["recommendations"]
        assert r["n_candidates"] == base["n_candidates"]


# ═══ filter/rank 语义与输入校验 ═══════════════════════════════════════════════


class TestRecommendFilterRank:
    def test_family_key_and_label_and_substring(self):
        from rfauto.service.gallery_service import TEMPLATE_FAMILIES

        r_key = recommend_templates(f0_ghz=2.5, topology="filter", top_k=50)
        assert r_key["n_candidates"] == sum(
            1 for v in TEMPLATE_FAMILIES.values() if v == "filter")
        r_label = recommend_templates(f0_ghz=2.5, topology="滤波器与双工器",
                                      top_k=50)
        assert r_label["n_candidates"] == r_key["n_candidates"]
        assert all(c["family"] == "filter"
                   for c in r_label["recommendations"])

    def test_n_ports_equality(self):
        r = recommend_templates(f0_ghz=2.5, n_ports=5, top_k=10)
        names = [c["name"] for c in r["recommendations"]]
        assert names == ["nway_wilkinson"]  # TA-4 五端口树形功分器

    def test_f0_band_tolerance_boundary(self):
        """带内 ±tol 缺省 0.30；MHz 级查询按 GHz 单位换算命中（0.01356）。"""
        assert recommend_templates(f0_ghz=2.5, top_k=100)["n_candidates"] > 0
        # coil_nfc f0=0.01356GHz：13.56MHz 查询 dev=0 唯一命中
        r = recommend_templates(f0_ghz=0.01356, top_k=5)
        assert [c["name"] for c in r["recommendations"]] == ["coil_nfc"]
        narrow = recommend_templates(f0_ghz=2.5, f0_tol=0.001, top_k=5)
        assert all(c["rank"]["f0_dev"] <= 0.001
                   for c in narrow["recommendations"])

    def test_keywords_and_semantics(self):
        r = recommend_templates(f0_ghz=2.5, keywords="发夹 带通", top_k=10)
        names = [c["name"] for c in r["recommendations"]]
        assert "hairpin" in names and "varactor_bpf" in names
        for card in r["recommendations"]:
            assert set(card["rank"]) == {
                "f0_dev", "semantics_covered", "preview"}
        # 次键生效：同 f0_dev 并列组内 semantics 覆盖多者在前
        devs = [c["rank"]["f0_dev"] for c in r["recommendations"]]
        assert devs == sorted(devs)

    def test_invalid_inputs_degraded_envelope(self):
        for bad in (dict(f0_ghz=0.0), dict(f0_ghz=-1.0),
                    dict(f0_ghz=2.5, f0_tol=1.5), dict(f0_ghz=2.5, top_k=0),
                    dict(f0_ghz=2.5, n_ports="two")):
            r = recommend_templates(**bad)
            assert r["ok"] and r["degraded"] and r["degrade_reason"]
            assert r["n_candidates"] == 0 and r["recommendations"] == []

    def test_default_tol_constant(self):
        assert RECOMMEND_F0_TOL == 0.30


# ═══ 判据⑤：UX-A7 深链 71 卡路径逐一存在 ═════════════════════════════════════


class TestDocsDeepLinks:
    def test_gallery_cards_docs_link_all_71_exist(self):
        d = gallery_cards()
        assert d["n_templates"] == 71
        for card in d["cards"]:
            link = card.get("docs_link")
            assert link == f"docs/templates/{card['name']}/meta.yaml", card
            assert (REPO / link).is_file(), link  # os.path 断言逐一存在

    def test_gallery_export_cards_docs_link_sync(self):
        """gallery_export.py 同步（UX-A7 并档）：同式同源逐卡一致。"""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "w2b_gallery_export", REPO / "scripts" / "gallery_export.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cards = mod.collect_cards()
        svc = {c["name"]: c["docs_link"] for c in gallery_cards()["cards"]}
        assert len(cards) == 71
        for card in cards:
            assert card["docs_link"] == svc[card["name"]], card["name"]
            assert (REPO / card["docs_link"]).is_file()

    def test_recommend_cards_carry_docs_link(self):
        r = recommend_templates(f0_ghz=10.0, top_k=5)
        for card in r["recommendations"]:
            assert (REPO / card["docs_link"]).is_file()


# ═══ CLI 叶 + MCP 工具接线 ═══════════════════════════════════════════════════


class TestCliAndMcpWiring:
    def test_cli_recommend_registered_and_help_hygiene(self):
        """typer→click 树实构建：recommend 叶在册 + help 无 [ / %（#305/#269）。"""
        import click
        from typer.main import get_command

        from rfauto.cli.main import app as main_app

        root = get_command(main_app)
        sub = root.get_command(click.Context(root), "template-spec")
        assert sub is not None and hasattr(sub, "commands")
        rec = sub.get_command(click.Context(sub), "recommend")
        assert rec is not None
        # 字符卫生=命令 help/short_help 原文（共享门 test_cli_help_text_hygiene
        # 同判定面；get_help 渲染面含 Usage 的 [OPTIONS] 不在此列）
        for text in (getattr(rec, "help", None) or "",
                     getattr(rec, "short_help", None) or ""):
            assert "[" not in text and "%" not in text, text
        opts = {o for p in getattr(rec, "params", [])
                for o in getattr(p, "opts", [])}
        for opt in ("--f0-ghz", "--topology", "--n-ports", "--keywords",
                    "--top-k", "--f0-tol", "--json"):
            assert opt in opts, opt

    def test_cli_recommend_json_envelope(self, capsys, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app as main_app

        monkeypatch.chdir(REPO)
        result = CliRunner().invoke(
            main_app, ["template-spec", "recommend", "--f0-ghz", "10",
                       "--topology", "喇叭", "--json"])
        assert result.exit_code == 0, result.output
        import json

        data = json.loads(result.output)
        assert data["ok"] and data["recommendations"][0]["name"] == \
            "pyramid_horn"

    def test_mcp_tool_registered_and_callable(self):
        import asyncio
        import json

        from rfauto.mcp_server import mcp

        async def _run():
            tools = await mcp.list_tools()
            return {t.name for t in tools}

        names = asyncio.run(_run())
        assert "recommend_templates" in names
        result = asyncio.run(mcp.call_tool(
            "recommend_templates",
            {"f0_ghz": 10.0, "topology": "喇叭", "top_k": 3}))
        payload = (result.structured_content
                   if hasattr(result, "structured_content")
                   and result.structured_content is not None
                   else json.loads(result.content[0].text))
        assert payload["ok"]
        assert payload["recommendations"][0]["name"] == "pyramid_horn"
