"""WP2.3 π 型衰减器首族单测：渲染（LumpedElement 口径）/解析/综合/spec。

口径：串臂 LumpedElement 桥接中点断口（ny=y）+ 两端对地 shunt
LumpedElement（ny=z，短柱接 z-min PEC 地）。确定性裁判=理想电阻
网络 ABCD 闭式（E4 attenuator_pi 同源），|S21|=-atten_db 平坦、
S11=0（按设计匹配）。几何边精确入网（#198）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W, D = 1.1134, 6.0


def test_template_tables_have_atten_pi():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "atten_pi" in TEMPLATE_META and "atten_pi" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["atten_pi"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["atten_pi"]["w_mm"] == pytest.approx(1.1134,
                                                                 abs=0.02)
    assert _TEMPLATE_PORT_AXES["atten_pi"] == ("y",)
    assert _TEMPLATE_RADIATOR["atten_pi"] is False


def test_render_atten_pi_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_pi", {"atten_db": 10.0, "w_mm": W,
                                      "shunt_off_mm": D,
                                      "r_series_mid_ohm": 71.151,
                                      "r_shunt_end_ohm": 96.248},
                         (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    assert text.count('CSX.AddLumpedElement("') == 3  # 串臂 + 两 shunt
    assert "ny=1" in text and "ny=2" in text
    # 串臂断口：带在 y=±G 处断开
    assert "-BOARD, H_SUB), (W / 2, -G, H_SUB)" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("atten_pi", {"w_mm": W, "shunt_off_mm": D})
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12   # 带缘
    assert min(abs(v - 0.25e-3) for v in nx) < 1e-12     # shunt 盒 x 边
    assert min(abs(v - 6.25e-3) for v in ny) < 1e-12     # shunt 盒 y 边
    assert min(abs(v - 0.5e-3) for v in ny) < 1e-12      # 串臂断口


def test_fake_atten_pi_flat_attenuation():
    """fake：理想电阻网络 |S21|=-10dB 平坦、按设计匹配 S11≈0。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="atten_pi", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"atten_db": "10dB"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s21_db = 20 * np.log10(np.abs(net.s[:, 0, 1]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-10.0, abs=0.05)
    assert float(np.max(20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12))) < -100


def test_synthesize_atten_pi_model_roundtrip():
    from rfauto.core.synthesis import synthesize_atten_pi_model

    result = synthesize_atten_pi_model(attenuation_db=10.0, z0_ohm=50.0)
    assert result.model == "atten_pi"
    assert result.params["r_series_mid_ohm"] == pytest.approx(71.151,
                                                              abs=0.1)
    assert result.params["r_shunt_end_ohm"] == pytest.approx(96.248,
                                                             abs=0.1)
    objs = result.recipe_draft["objectives"]
    assert objs[0]["metric"] == "s21_db" and objs[0]["op"] == "mean_within"
    assert objs[0]["value"] == pytest.approx([-10.5, -9.5])
    assert objs[1]["metric"] == "s11_db"


def test_atten_pi_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("atten_pi")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("atten_pi", attenuation_db=10.0)
    assert draft["model"] == "atten_pi"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "atten_pi" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "atten_pi"
    assert data["n_ports"] == TEMPLATE_META["atten_pi"]["n_ports"]
