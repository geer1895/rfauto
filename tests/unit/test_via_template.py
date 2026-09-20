"""WP2.2 过孔过渡基元单测：渲染（双层板+反焊盘+过孔柱）/解析/综合/spec。

口径：双层板 z∈[0,2H]，内层地方 sheet z=H 带方反焊盘（四盒拼孔，
边长 2*antipad），过孔金属柱 r_via 穿孔连接顶带（z=2H, port1）与
底带（z=0, port2）。无 PEC 边界（z 双 MUR，地=内层 sheet）——全站
首例。反焊盘同轴口径 Z≈(60/√εr)ln(r_pad/r_via)≈52.5Ω 近 50Ω。
几何边精确入网（#198）；过孔柱阶梯化口径（r≪cell 不加网格线）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W, AP, RV = 1.1134, 0.8, 0.15


def test_template_tables_have_via():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "via" in TEMPLATE_META and "via" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["via"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["via"]["w_mm"] == pytest.approx(1.1134, abs=0.02)
    assert TEMPLATE_NOMINAL["via"]["antipad_mm"] == pytest.approx(0.8)
    assert _TEMPLATE_PORT_AXES["via"] == ("y",)
    assert _TEMPLATE_RADIATOR["via"] is False


def test_render_via_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("via", {"w_mm": W, "antipad_mm": AP,
                                 "r_via_mm": RV}, (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 教训制度化）
    assert text.count("via_gnd.AddBox") == 4  # 方反焊盘四盒拼孔
    assert "AddCylinder([0.0, 0.0, 0.0], [0.0, 0.0, H_TOP], radius=RV" in text
    # 无 PEC 边界（地=内层 sheet，z 双 MUR）
    assert '"MUR", "MUR", "PML_8", "PML_8", "MUR", "MUR"' in text
    # 双层板 0..2H + β 双列
    assert "2 * H_SUB" in text and "beta2_rad_per_m" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("via", {"w_mm": W, "antipad_mm": AP,
                                  "r_via_mm": RV})
    # 顶带缘 ±W/2 与反焊盘方边 ±AP 精确入网（过孔柱阶梯化不加线）
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12
    assert min(abs(v - 0.8e-3) for v in nx) < 1e-12
    assert min(abs(v + 0.8e-3) for v in nx) < 1e-12
    assert min(abs(v - 0.8e-3) for v in ny) < 1e-12


def test_fake_via_is_ideal_matched_cascade():
    """fake = 两馈线理想级联：完全匹配（过孔寄生为零的闭式极限）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="via", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": f"{W}mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s11_db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    assert np.max(s11_db) < -100  # 理想级联数值零反射


def test_synthesize_via_model_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_via_model

    result = synthesize_via_model(z0_ohm=50.0, freq_ghz=2.5)
    assert result.model == "via"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_ref, _, _ = inverse_width(50.0, 2.5, st)
    assert result.params["w_mm"] == pytest.approx(w_ref, abs=0.01)
    assert result.params["antipad_mm"] == 0.8
    assert result.params["r_via_mm"] == 0.15


def test_via_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("via")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("via", z0_ohm=50.0)
    assert draft["model"] == "via"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "via" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "via"
    assert data["n_ports"] == TEMPLATE_META["via"]["n_ports"]
