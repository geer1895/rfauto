"""WP2.1 CPW 均匀共面波导锚单测：渲染（CPWPort 口径）/解析/综合/spec。

口径依据：绑定源码 L1117+（CPWPort：start/stop=中心带、gap_width、
地自画、exc_dir='z'）+ CPWG 共形映射闭式综合（50Ω@gap0.2 → w=0.849mm）。
参照系=CPWG：openEMS 官方口径 z-min=PEC 强制地，实际结构即底接地
共面波导（#193 参照系错位教训，#198 闭式收口——skrf CPW 无地口径作废）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))


def test_template_tables_have_cpw():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "cpw" in TEMPLATE_META and "cpw" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["cpw"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["cpw"]["w_mm"] == pytest.approx(0.849, abs=0.02)
    assert _TEMPLATE_PORT_AXES["cpw"] == ("y",)
    assert _TEMPLATE_RADIATOR["cpw"] is False


def test_near_points_and_geometry_spec():
    from rfauto.adapters.openems_templates import _near_points, geometry_spec

    params = {"w_mm": 0.849, "gap_mm": 0.2, "line_len_mm": 40.0}
    nx, ny = _near_points("cpw", params)
    # 四条几何边 + 两条缝中线 + 默认 0.0 共 7 点；线两端共 3 点
    assert len(nx) == 7 and len(ny) == 3
    w_half = 0.4245e-3
    assert w_half in nx and -(w_half) in nx
    assert (w_half + 0.2e-3) in nx  # 激励盒边必须有网格线（#198 零体积教训）
    assert (w_half + 0.1e-3) in nx  # 缝中线（pt4 收敛加密）
    spec = geometry_spec("cpw", params)
    names = [b["name"] for b in spec["boxes"]]
    assert "cpw_center" in names and "gnd_left" in names
    assert len(spec["ports"]) == 2


def test_render_script_cpw_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("cpw", {"w_mm": 0.849, "gap_mm": 0.2,
                                 "line_len_mm": 40.0}, (2.25, 2.75))
    assert "CPWPort(CSX, port_nr=1" in text
    assert "CPWPort(CSX, port_nr=2" in text
    assert "gap_width=GAP" in text
    assert 'CSX.AddMetal("cpw")' in text
    # 地自画且贯穿全域（端口段地须自画——CPWPort 只补中心带）
    assert text.count("cpw.AddBox") == 3


def test_fake_cpw_dispatch_matches_cpwg_closed_form():
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.calculators import _cpwg_ri

    ad = FakeAdapter(model_type="cpw", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "0.849mm", "gap_mm": "0.2mm",
                      "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s = net.s
    assert np.max(np.abs(s[:, 0, 0])) < 0.05  # 匹配线
    phase = np.unwrap(np.angle(s[:, 0, 1]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * 40e-3)) ** 2
    eps_ref = _cpwg_ri(0.849, 0.2, 0.508, 3.66)[0]
    assert eps_recovered == pytest.approx(eps_ref, rel=0.02)


def test_synthesize_cpw_model_roundtrip():
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import synthesize_cpw_model

    result = synthesize_cpw_model(z0_ohm=50.0, gap_mm=0.2, freq_ghz=2.5,
                                  line_len_mm=40.0)
    assert result.model == "cpw"
    assert result.params["w_mm"] == pytest.approx(0.849, abs=0.05)
    # 回代自洽：综合出的 w 在 CPWG 闭式下 Z0=50（口径一致性）
    z0_back = _cpwg_ri(result.params["w_mm"], 0.2, 0.508, 3.66)[1]
    assert z0_back == pytest.approx(50.0, abs=0.5)
    assert result.recipe_draft["model"] == "cpw"


def test_cpwg_closed_form_matches_measured_anchor():
    """#193 冒烟实测双锚（runs/cpw_smoke 证据链）对闭式的校验。

    实测 1：β→εeff=3.084（旧 4.035mm 几何）；实测 2：|S11|max=−6.5dB
    ——闭式预言 Z0=18.2Ω → |Γ|=−6.6dB，两独立测量同轴印证参照系。
    """
    from rfauto.core.calculators import _cpwg_ri

    eps, z0 = _cpwg_ri(4.035, 0.2, 0.508, 3.66)
    assert eps == pytest.approx(3.084, rel=0.025)   # −1.86%
    assert 15.0 < z0 < 22.0                          # 18.2Ω 失配线
    gamma = abs((z0 - 50.0) / (z0 + 50.0))
    assert 20 * np.log10(gamma) == pytest.approx(-6.5, abs=0.5)


def test_spec_wiring_and_hint():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs
    from rfauto.service.ui_service import _template_hint

    bootstrap_template_specs()
    assert "cpw" in TEMPLATE_SPECS.names()
    spec = TEMPLATE_SPECS.get("cpw")
    assert spec.render_script is not None and spec.fake_model is not None
    assert _template_hint({"model": "cpw"}) == "cpw"
    assert "cpw" in _template_hint({"model": "cpw_line"})  # 子串匹配


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "cpw" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "cpw"
    assert data["n_ports"] == TEMPLATE_META["cpw"]["n_ports"]
