"""PR-5 画廊交互化单测（service/gallery_service.py + /api/gallery）。

预览通道=显式白名单；每条规则真跑 /api/calculators/run 同一内核钉住
（形参集/数值合法性由确定性内核显式报错，测试全量扫规则）。
X1 席增量：模板族分类（TEMPLATE_FAMILIES 全量覆盖 + 抽样归类 + "other"
如实兜底）——静态画廊页 data-* 数据源的单一事实源钉。
"""

from __future__ import annotations

import pytest

from rfauto.service.calculator_service import run_calculator
from rfauto.service.gallery_service import (
    FAMILY_LABELS,
    PREVIEW_RULES,
    TEMPLATE_FAMILIES,
    gallery_cards,
    resolve_preview_params,
    template_family,
)


class TestGalleryCards:
    def test_covers_full_registry_sorted(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        d = gallery_cards()
        assert d["ok"]
        assert d["n_templates"] == len(TEMPLATE_META)
        names = [c["name"] for c in d["cards"]]
        assert names == sorted(TEMPLATE_META)
        assert d["preview_rules"] == sorted(PREVIEW_RULES)

    def test_card_fields_and_nominal_passthrough(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

        d = gallery_cards()
        by_name = {c["name"]: c for c in d["cards"]}
        card = by_name["siw"]
        assert card["f0_ghz"] == TEMPLATE_META["siw"]["f0_ghz"]
        assert card["nominal_params"] == TEMPLATE_NOMINAL["siw"]
        assert card["param_semantics"] == TEMPLATE_META["siw"]["param_semantics"]

    def test_unmapped_template_preview_none(self):
        d = gallery_cards()
        by_name = {c["name"]: c for c in d["cards"]}
        assert by_name["wilkinson"]["preview"] is None  # 未配通道如实 None
        assert d["n_previews"] == sum(1 for c in d["cards"] if c["preview"])


class TestPreviewRules:
    @pytest.mark.parametrize("template", sorted(PREVIEW_RULES))
    def test_rule_runs_on_deterministic_kernel(self, template):
        """每条规则真跑闭式内核（形参缺/值非法会显式报错——全量钉住）。"""
        d = gallery_cards()
        card = next(c for c in d["cards"] if c["name"] == template)
        preview = card["preview"]
        assert preview is not None, f"{template} 映射规则必须可解析出参数"
        calc = preview["calculator"]
        from rfauto.service.calculator_service import list_calculators

        known = {c["name"] for c in list_calculators()["calculators"]}
        assert calc in known
        r = run_calculator(calc, dict(preview["params"]))
        assert r.get("ok"), r

    def test_slider_meta_ranges_contain_initial(self):
        d = gallery_cards()
        for card in d["cards"]:
            if not card["preview"]:
                continue
            for key, m in card["preview"]["slider_meta"].items():
                assert m["min"] <= m["initial"] <= m["max"]
                assert m["step"] > 0
                assert key in card["preview"]["params"]

    def test_resolve_unresolvable_source_returns_none(self):
        assert resolve_preview_params({"w_mm": "missing_key"}, {}, 10.0) is None
        assert resolve_preview_params({"w_mm": "@f0_ghz"}, {}, None) is None
        got = resolve_preview_params({"freq_ghz": "@f0_ghz", "w_mm": "w_mm"},
                                     {"w_mm": 2.0}, 10.0)
        assert got == {"freq_ghz": 10.0, "w_mm": 2.0}


class TestTemplateFamilies:
    """PR-5 X1 模板族分类钉（静态画廊页 data-* 数据源；服务层单一事实源）。

    全量覆盖钉=注册表消费者纪律（#231/#304 家法）：新模板注册必须同批
    登记族键，漏登记当场红（静态页如实回退 "other"，但注册面不允许漂）。
    """

    def test_full_coverage_over_registry(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        missing = sorted(set(TEMPLATE_META) - set(TEMPLATE_FAMILIES))
        assert not missing, (
            f"新模板缺族登记（service/gallery_service.TEMPLATE_FAMILIES）: "
            f"{missing}——注册须同批登记族键（#231 注册表消费者纪律）")
        assert not (set(TEMPLATE_FAMILIES) - set(TEMPLATE_META)), \
            "TEMPLATE_FAMILIES 含注册表外的死键（陈旧即删）"

    def test_family_keys_all_have_labels(self):
        for name, fam in TEMPLATE_FAMILIES.items():
            assert fam in FAMILY_LABELS, f"{name} 族键 {fam} 缺标签"
        assert FAMILY_LABELS["other"]  # 如实兜底标签在场

    @pytest.mark.parametrize("name,fam", [
        ("patch", "antenna"),
        ("patch_array_2x2", "antenna"),
        ("vivaldi_tsa", "antenna"),
        ("coil_nfc", "antenna"),
        ("hairpin", "filter"),
        ("coupled_bpf", "filter"),
        ("diplexer", "filter"),
        ("wilkinson", "coupler"),
        ("nway_wilkinson", "coupler"),
        ("marchand_balun", "coupler"),
        ("siw", "line"),
        ("cpw", "line"),
        ("via", "line"),
        ("msl_cpw", "transition"),
        ("sma_launcher", "transition"),
        ("ms_cross", "fss"),
        ("ms_ring_patch", "fss"),
        ("ring_resonator", "material"),
        ("atten_pi", "material"),
    ])
    def test_sampled_classification(self, name, fam):
        assert template_family(name) == fam

    def test_unknown_name_honest_other(self):
        assert template_family("not_a_template") == "other"
        assert template_family("") == "other"

    def test_every_registry_template_bucketed_by_exporters(self):
        """导出器消费面：全注册表逐模板族标签非空（chips 渲染单源可用）。"""
        from rfauto.adapters.openems_templates import TEMPLATE_META

        for name in TEMPLATE_META:
            fam = template_family(name)
            assert FAMILY_LABELS.get(fam), name


class TestHttpEndpoint:
    @pytest.fixture()
    def client(self):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_gallery_endpoint_shape(self, client):
        r = client.get("/api/gallery").json()
        assert r["ok"] and r["n_templates"] > 0
        assert isinstance(r["cards"], list)

    def test_slider_value_roundtrip_via_calculators_run(self, client):
        """前端契约：滑块值 POST /api/calculators/run 即得预览（零专用端点）。"""
        cards = client.get("/api/gallery").json()["cards"]
        siw = next(c for c in cards if c["name"] == "siw")["preview"]
        params = dict(siw["params"])
        params["w_mm"] = params["w_mm"] * 1.1  # 模拟滑块 +10%
        r = client.post("/api/calculators/run",
                        json={"name": siw["calculator"], "params": params}).json()
        assert r["ok"] and r["params"]["w_mm"] == pytest.approx(params["w_mm"])

    def test_index_serves_gallery_view(self, client):
        html = client.get("/").text
        assert 'id="view-gallery"' in html and 'data-v="gallery"' in html
