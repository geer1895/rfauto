"""WP2.3 T 型衰减器横向变体单测：渲染/解析（ABCD 闭式裁判）/综合/spec。

口径：±d 断口各串 LumpedElement（ny=y）+ 中点对地全带宽 shunt
LumpedElement（ny=z）。确定性裁判=理想电阻网络 ABCD（E4 attenuator_t
同源）：|S21|=-atten_db 平坦、S11=0。几何边精确入网（#198）。
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


def test_template_tables_have_atten_t():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "atten_t" in TEMPLATE_META and "atten_t" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["atten_t"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["atten_t"]["atten_db"] == pytest.approx(10.0)
    assert _TEMPLATE_PORT_AXES["atten_t"] == ("y",)
    assert _TEMPLATE_RADIATOR["atten_t"] is False


def test_render_atten_t_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_t", {"atten_db": 10.0, "w_mm": W,
                                     "shunt_off_mm": D,
                                     "r_series_arm_ohm": 25.975,
                                     "r_shunt_mid_ohm": 35.136},
                         (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    assert text.count('CSX.AddLumpedElement("') == 3  # 两串臂 + 中点 shunt
    assert text.count("ny=1") == 2 and "ny=2" in text
    # 三段带：两断口在 ±(D±G/2)
    assert "-BOARD, H_SUB), (W / 2, -D - G / 2, H_SUB)" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("atten_t", {"w_mm": W, "shunt_off_mm": D})
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12   # 带缘
    assert min(abs(v - 0.25e-3) for v in nx) < 1e-12     # shunt 盒 x 边
    for edge_mm in (-6.25, -5.75, 5.75, 6.25):           # 两断口 y 边
        assert min(abs(v - edge_mm * 1e-3) for v in ny) < 1e-12


def test_fake_atten_t_flat_attenuation():
    """fake：理想电阻网络 |S21|=-10dB 平坦、按设计匹配 S11≈0。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="atten_t", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"atten_db": "10dB"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s21_db = 20 * np.log10(np.abs(net.s[:, 0, 1]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-10.0, abs=0.05)
    assert float(np.max(20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12))) < -100


def test_synthesize_atten_t_model_roundtrip():
    from rfauto.core.synthesis import synthesize_atten_t_model

    result = synthesize_atten_t_model(attenuation_db=10.0, z0_ohm=50.0)
    assert result.model == "atten_t"
    assert result.params["r_series_arm_ohm"] == pytest.approx(25.975,
                                                              abs=0.1)
    assert result.params["r_shunt_mid_ohm"] == pytest.approx(35.136,
                                                             abs=0.1)
    objs = result.recipe_draft["objectives"]
    assert objs[0]["metric"] == "s21_db" and objs[0]["op"] == "mean_within"
    assert objs[0]["value"] == pytest.approx([-10.5, -9.5])


def test_atten_t_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("atten_t")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("atten_t", attenuation_db=10.0)
    assert draft["model"] == "atten_t"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "atten_t" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "atten_t"
    assert data["n_ports"] == TEMPLATE_META["atten_t"]["n_ports"]
