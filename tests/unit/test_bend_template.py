"""WP2.2 微带直角弯折基元单测：渲染/解析（理想级联裁判）/综合/spec。

口径：L 形两臂各 arm_len、全臂 50Ω、未切角标准口径。裁判=理想级联
（同宽两段直接级联在闭式里完全匹配——引擎的唯一反射源即弯角寄生），
|S11| 绝对门 -15dB（未切角直角弯折文献口径）。几何边精确入网（#198）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W, A = 1.1134, 20.0


def test_template_tables_have_bend():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "bend" in TEMPLATE_META and "bend" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["bend"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["bend"]["w_mm"] == pytest.approx(1.1134, abs=0.02)
    assert _TEMPLATE_PORT_AXES["bend"] == ("x", "y")
    assert _TEMPLATE_RADIATOR["bend"] is False


def test_render_bend_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("bend", {"w_mm": W, "arm_len_mm": A}, (2.25, 2.75))
    assert "MSLPort(CSX, port_nr=1" in text
    assert "MSLPort(CSX, port_nr=2" in text
    assert 'prop_dir="x"' in text  # 臂2 沿 x
    assert 'CSX.AddMetal("bend")' in text
    assert text.count("bend.AddBox") == 2


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("bend", {"w_mm": W, "arm_len_mm": A})
    # 臂1带缘 ±W/2（nx）+ 臂2端点 A（nx）；臂1端点 -A 与臂2带缘
    # ±W/2（ny）；弯角=默认 0.0
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12
    assert min(abs(v - 20.0e-3) for v in nx) < 1e-12
    assert min(abs(v + 20.0e-3) for v in ny) < 1e-12
    assert 0.0 in nx and 0.0 in ny


def test_fake_bend_is_ideal_matched_cascade():
    """fake = 同宽两段理想级联：完全匹配（弯角寄生为零的闭式极限）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="bend", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": f"{W}mm", "arm_len_mm": f"{A}mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s11_db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    assert np.max(s11_db) < -100  # 理想级联数值零反射
    # S21 相位斜率 → εeff 恢复 = HJ 闭式（每臂 A 长共 2A）
    phase = np.unwrap(np.angle(net.s[:, 0, 1]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * (2 * A) * 1e-3)) ** 2
    from rfauto.core.synthesis import Stackup, forward_z0
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_hj = forward_z0(W, 2.5, stackup)
    assert eps_recovered == pytest.approx(eps_hj, rel=0.01)


def test_synthesize_bend_model_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_bend_model

    result = synthesize_bend_model(z0_ohm=50.0, freq_ghz=2.5, arm_len_mm=20.0)
    assert result.model == "bend"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_ref, _, _ = inverse_width(50.0, 2.5, st)
    assert result.params["w_mm"] == pytest.approx(w_ref, abs=0.01)
    obj = result.recipe_draft["objectives"][0]
    assert obj["metric"] == "s11_db" and obj["value"] == pytest.approx(-15.0)


def test_bend_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("bend")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("bend", z0_ohm=50.0)
    assert draft["model"] == "bend"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "bend" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "bend"
    assert data["n_ports"] == TEMPLATE_META["bend"]["n_ports"]
