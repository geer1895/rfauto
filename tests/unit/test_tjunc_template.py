"""WP2.2 微带 T 接头基元单测：渲染/解析（理想结点裁判）/综合/spec。

口径：主线沿 y（端口 1/2）、支臂沿 x（端口 3），全臂 50Ω 对称均分。
锚判据=skrf 理想三端口结点（S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]，幺正
互易）+ 三条 HJ 线。物理要点：无损互易三端口匹配地板 Sii=-1/3
（-9.55dB）——wilkinson 隔离电阻存在的物理原因。几何边精确入网（#198）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

WF, TL, BL = 1.1134, 25.0, 20.0


def test_template_tables_have_tjunc():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "tjunc" in TEMPLATE_META and "tjunc" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["tjunc"]["n_ports"] == 3
    assert TEMPLATE_NOMINAL["tjunc"]["w_feed_mm"] == pytest.approx(1.1134,
                                                                   abs=0.02)
    assert _TEMPLATE_PORT_AXES["tjunc"] == ("x", "y")
    assert _TEMPLATE_RADIATOR["tjunc"] is False


def test_render_tjunc_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("tjunc", {"w_feed_mm": WF, "through_len_mm": TL,
                                   "branch_len_mm": BL}, (2.25, 2.75))
    for n in (1, 2, 3):
        assert f"MSLPort(CSX, port_nr={n}" in text
    assert 'prop_dir="x"' in text  # 支臂端口沿 x
    # 四侧 PML_8（三侧带端口）+ 双金属盒（主线+支臂）
    assert 'CSX.AddMetal("tjunc")' in text
    assert text.count("tjunc.AddBox") == 2


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("tjunc", {"w_feed_mm": WF, "through_len_mm": TL,
                                    "branch_len_mm": BL})
    # 主线带缘 ±WF/2（nx）；支臂端 BL（nx）；主线端 ±TL 与支臂带缘
    # ±WF/2（ny）；结点角=默认 0.0
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12
    assert min(abs(v - 20.0e-3) for v in nx) < 1e-12
    assert min(abs(v - 25.0e-3) for v in ny) < 1e-12
    assert min(abs(v - 0.5567e-3) for v in ny) < 1e-12
    assert 0.0 in nx and 0.0 in ny


def test_fake_tjunc_ideal_node_physics():
    """fake 三端口：均分 + 理想结点匹配地板 -9.55dB（无损互易极限）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="tjunc", n_ports=3,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_feed_mm": f"{WF}mm", "through_len_mm": f"{TL}mm",
                      "branch_len_mm": f"{BL}mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert net.s.shape[1] == 3
    i = int(np.argmin(np.abs(net.f - 2.5e9)))
    s11 = 20 * np.log10(np.abs(net.s[i, 0, 0]))
    s21 = 20 * np.log10(np.abs(net.s[i, 1, 0]))
    s31 = 20 * np.log10(np.abs(net.s[i, 2, 0]))
    # 理想结点地板（-9.55dB 量级，随臂相位微漂）
    assert s11 == pytest.approx(-9.55, abs=0.5)
    # 均分（对称口径）
    assert abs(s21 - s31) < 0.2
    assert s21 == pytest.approx(-3.6, abs=0.3)


def test_synthesize_tjunc_model_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_tjunc_model

    result = synthesize_tjunc_model(z_arm_ohm=50.0, freq_ghz=2.5,
                                    through_len_mm=25.0, branch_len_mm=20.0)
    assert result.model == "tjunc"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_ref, _, _ = inverse_width(50.0, 2.5, st)
    assert result.params["w_feed_mm"] == pytest.approx(w_ref, abs=0.01)
    assert result.params["w_branch_mm"] == pytest.approx(w_ref, abs=0.01)
    # objectives 地板 = 理想结点 -9.55dB + 裕量 → -5
    obj = result.recipe_draft["objectives"][0]
    assert obj["metric"] == "s11_db" and obj["op"] == "max_below"
    assert obj["value"] == pytest.approx(-5.0, abs=0.5)


def test_tjunc_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("tjunc")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("tjunc", z_arm_ohm=50.0)
    assert draft["model"] == "tjunc"


def test_three_port_beta_single_source_block():
    """β 锚单源锁定（「tjunc beta2 混源」历史问题收口）。

    port_beta.csv 必须由唯一插桩槽写出：三端口 β（beta1/beta2/beta3）
    全部取自同一 run 的 CalcPort 探针（_port1/_port2/_port3），且写在
    _port3.CalcPort 之后（三探针齐备）；固定槽位 beta_block 模板清单
    不得包含 tjunc（否则出现第二写者=混源回归）。
    """
    from rfauto.adapters.openems_templates import render_script

    text = render_script("tjunc", {"w_feed_mm": WF, "through_len_mm": TL,
                                   "branch_len_mm": BL}, (2.25, 2.75))
    assert text.count("port_beta.csv") == 1  # 单一写者
    i_calc3 = text.index("_port3.CalcPort")
    i_beta = text.index("beta1_rad_per_m")
    assert i_calc3 < i_beta  # 三探针齐备后才写 CSV
    for token in ("_port1.beta", "_port2.beta", "_port3.beta",
                  "beta2_rad_per_m", "beta3_rad_per_m"):
        assert token in text, token


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "tjunc" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "tjunc"
    assert data["n_ports"] == TEMPLATE_META["tjunc"]["n_ports"]
