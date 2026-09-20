"""WP2.1 对称带状线锚单测：渲染（StripLinePort 口径）/解析/综合/spec。

口径依据：绑定源码 L914+（StripLinePort：height=带-地半高、上下对称
电压探针）；上下地 = 域 z 边界 PEC（对称双面敷铜板 b=1.016 口径）。
TEM 模：εeff=εr 精确——β 锚判据最干净的闭式。几何边精确入网（#198
激励体积教训：盒边不进网格 → 吸附归零）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))


def test_template_tables_have_stripline():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "stripline" in TEMPLATE_META
    assert TEMPLATE_META["stripline"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["stripline"]["w_mm"] == pytest.approx(0.5554,
                                                                  abs=0.02)
    assert _TEMPLATE_PORT_AXES["stripline"] == ("y",)
    assert _TEMPLATE_RADIATOR["stripline"] is False


def test_render_stripline_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("stripline", {"w_mm": 0.5554, "line_len_mm": 40.0},
                         (2.25, 2.75))
    assert "StripLinePort(CSX, port_nr=1" in text
    assert "StripLinePort(CSX, port_nr=2" in text
    assert "height=H_SUB" in text
    # 上下地 = z 域边界双 PEC（对称板口径）
    assert '"PEC", "PEC"' in text
    # 基板填满 0..2·H_SUB，z 网格含中面（带平面）
    assert "2 * H_SUB" in text
    assert 'np.linspace(0, 2 * H_SUB, 9)' in text
    assert 'CSX.AddMetal("stripline")' in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("stripline", {"w_mm": 0.5554,
                                        "line_len_mm": 40.0})
    # 带缘精确入网（#198 激励体积教训）——float 噪声用近似比较
    assert min(abs(v - 0.2777e-3) for v in nx) < 1e-12
    assert len(ny) == 3  # 0 + 线两端


def test_fake_stripline_dispatch_tem():
    """fake 派发：TEM εeff=εr=3.66——相位斜率恢复 εeff 必须等于 εr。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="stripline", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "0.5554mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert np.max(np.abs(net.s[:, 0, 0])) < 0.05  # 匹配线
    phase = np.unwrap(np.angle(net.s[:, 0, 1]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * 40e-3)) ** 2
    assert eps_recovered == pytest.approx(3.66, rel=0.01)


def test_synthesize_stripline_model_roundtrip():
    from rfauto.core.calculators import _stripline_z0
    from rfauto.core.synthesis import synthesize_stripline_model

    result = synthesize_stripline_model(z0_ohm=50.0, freq_ghz=2.5,
                                        line_len_mm=40.0)
    assert result.model == "stripline"
    assert result.params["w_mm"] == pytest.approx(0.5554, abs=0.02)
    z0_back = _stripline_z0(result.params["w_mm"], 1.016, 3.66)
    assert z0_back == pytest.approx(50.0, abs=0.3)
    assert result.recipe_draft["model"] == "stripline"


def test_stripline_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("stripline")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("stripline", z0_ohm=50.0)
    assert draft["model"] == "stripline"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "stripline" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "stripline"
    assert data["n_ports"] == TEMPLATE_META["stripline"]["n_ports"]
