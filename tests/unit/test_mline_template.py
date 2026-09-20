"""WP2.1 Tier 0 微带均匀线（mline 锚）单测：渲染/解析/综合/spec 接线。

锚模板验收口径（refs §1/§6 + #162 β 金标准）：S21 相位斜率→εeff 对照
skrf HJ；|S11| 显著非零=端口/网格判废信号。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))


def test_template_tables_have_mline():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "mline" in TEMPLATE_META and "mline" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["mline"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["mline"]["w_mm"] == pytest.approx(1.113, abs=0.01)
    assert _TEMPLATE_PORT_AXES["mline"] == ("y",)
    assert _TEMPLATE_RADIATOR["mline"] is False


def test_near_points_and_geometry_spec():
    from rfauto.adapters.openems_templates import _near_points, geometry_spec

    params = {"w_mm": 1.113, "line_len_mm": 40.0}
    nx, ny = _near_points("mline", params)
    # 线两缘 + 线两端（各含默认 0.0 共 3 点）
    assert len(nx) == 3 and len(ny) == 3
    spec = geometry_spec("mline", params)
    names = [b["name"] for b in spec["boxes"]]
    assert "uniform_line" in names
    assert len(spec["ports"]) == 2


def test_render_script_mline_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                         (2.25, 2.75))
    assert "port_nr=1" in text and "port_nr=2" in text
    assert 'CSX.AddMetal("microstrip")' in text
    assert "MSLPort(CSX, port_nr=1" in text
    assert "MSLPort(CSX, port_nr=2" in text
    # footer 的通用 S23 二次激励块（全模板共享，无 port3 时优雅跳过）
    assert text.count("MSLPort(CSX, port_nr=3") == 1
    assert "FeedShift=10 * NEAR" in text  # 官方口径
    # mline 锚专属：β 金标准数据落盘（#162/#161）
    assert "port_beta.csv" in text
    # 线体坐标进入脚本
    assert "1.113" in text and "40.0" in text


def test_fake_mline_closed_form():
    from rfauto.adapters.fake_adapter import _mline_sparams

    freq = np.linspace(2.0, 3.0, 201)
    eps_eff, length_mm, tan_d = 2.73, 40.0, 0.0037
    s = _mline_sparams(freq, eps_eff=eps_eff, line_len_mm=length_mm,
                       tan_d=tan_d)
    # 匹配线：|S11| 数值底
    assert np.max(np.abs(s[:, 0, 0])) <= 1e-3
    # 相位斜率 → εeff（确定性复原，#175 线性语料口径）
    phase = np.unwrap(np.angle(s[:, 0, 1]))
    slope = np.polyfit(freq * 1e9, phase, 1)[0]  # rad/Hz
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * length_mm * 1e-3)) ** 2
    assert eps_recovered == pytest.approx(eps_eff, rel=1e-9)
    # 损耗：|S21| = exp(-α_d L) @ f0
    i0 = 100
    f0_hz = freq[i0] * 1e9
    alpha = np.pi * f0_hz * np.sqrt(eps_eff) * tan_d / 299792458.0
    assert np.abs(s[i0, 0, 1]) == pytest.approx(
        np.exp(-alpha * length_mm * 1e-3), rel=1e-9)


def test_fake_adapter_mline_dispatch():
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.synthesis import Stackup, forward_z0

    ad = FakeAdapter(model_type="mline", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "1.113mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s = net.s
    assert np.max(np.abs(s[:, 0, 0])) < 0.05  # 匹配线 |S11| 小
    # 相位斜率复原 εeff，与 skrf HJ 同源对照（同函数 → 应精确一致）
    phase = np.unwrap(np.angle(s[:, 0, 1]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * 40e-3)) ** 2
    stackup = Stackup.from_materials_yaml(
        "rogers4350b_h0.508", str(REPO / "configs" / "materials.yaml"))
    _, eps_hj = forward_z0(1.113, 2.5, stackup)
    assert eps_recovered == pytest.approx(eps_hj, rel=0.02)


def test_synthesize_mline_model():
    from rfauto.core.synthesis import synthesize_mline_model

    result = synthesize_mline_model(z0_ohm=50.0, freq_ghz=2.5,
                                    line_len_mm=40.0)
    assert result.model == "mline"
    # 权威口径表 §1：50Ω @rogers4350b h0.508 er3.66 = 1.113mm（skrf HJ）
    assert result.params["w_mm"] == pytest.approx(1.113, abs=0.02)
    assert result.recipe_draft["model"] == "mline"
    assert result.recipe_draft["params"]["w_mm"]["value"] == \
        result.params["w_mm"]


def test_spec_wiring_and_hint():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    assert "mline" in TEMPLATE_SPECS.names()
    spec = TEMPLATE_SPECS.get("mline")
    assert spec.render_script is not None and spec.fake_model is not None
    assert spec.hfss_plugin is None  # 纯 openEMS 锚模板
    from rfauto.service.ui_service import _template_hint

    assert _template_hint({"model": "mline"}) == "mline"
    assert _template_for_mline() == "mline"


def _template_for_mline() -> str:
    from rfauto.service.calibration_service import _template_for

    return _template_for("mline")
