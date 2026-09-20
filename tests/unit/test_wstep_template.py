"""WP2.2 微带宽度阶跃基元单测：渲染/解析（skrf 级联裁判）/综合/spec。

口径：单阶跃两段线（窄 50Ω/宽 35Ω 各半长），锚判据=skrf 级联 HJ 闭式
（两段理想 TL 级联为确定性裁判，引擎-理想偏差即阶梯寄生贡献）。
几何边精确入网（#198）；阶跃角落在默认网格线 0（junction）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W1, W2, L = 1.1134, 1.897, 40.0


def test_template_tables_have_wstep():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "wstep" in TEMPLATE_META and "wstep" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["wstep"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["wstep"]["w1_mm"] == pytest.approx(1.1134, abs=0.02)
    assert TEMPLATE_NOMINAL["wstep"]["w2_mm"] == pytest.approx(1.897, abs=0.02)
    assert _TEMPLATE_PORT_AXES["wstep"] == ("y",)
    assert _TEMPLATE_RADIATOR["wstep"] is False


def test_render_wstep_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("wstep", {"w1_mm": W1, "w2_mm": W2,
                                   "line_len_mm": L}, (2.25, 2.75))
    assert "MSLPort(CSX, port_nr=1" in text
    assert "MSLPort(CSX, port_nr=2" in text
    # 两段带 + 阶跃在中点
    assert 'CSX.AddMetal("wstep")' in text
    assert "W1 = 1.1134 * 1e-3" in text and "W2 = 1.897 * 1e-3" in text
    assert "YM = 0.0" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("wstep", {"w1_mm": W1, "w2_mm": W2,
                                    "line_len_mm": L})
    # 四条几何边精确入网（#198）；阶跃中点=默认网格线 0
    for edge_mm in (W1 / 2, -W1 / 2, W2 / 2, -W2 / 2):
        assert min(abs(v - edge_mm * 1e-3) for v in nx) < 1e-12
    assert len(ny) == 3  # 0（阶跃）+ 线两端


def test_fake_wstep_matches_skrf_cascade_referee():
    """fake 派发 vs skrf 级联 HJ 闭式裁判：同源口径必须重合。"""
    import skrf

    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="wstep", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w1_mm": f"{W1}mm", "w2_mm": f"{W2}mm",
                      "line_len_mm": f"{L}mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()

    # 确定性裁判：两段 HJ 线级联，端口归一 50Ω
    freq = skrf.Frequency(2.0, 3.0, 101, unit="GHz")
    st_h = 0.508e-3
    m1 = skrf.media.MLine(frequency=freq, w=W1 * 1e-3, h=st_h, ep_r=3.66)
    m2 = skrf.media.MLine(frequency=freq, w=W2 * 1e-3, h=st_h, ep_r=3.66)
    ideal = m1.line(L / 2, unit="mm") ** m2.line(L / 2, unit="mm")
    ideal.renormalize([50.0, 50.0])

    # 级联线存在阻抗跳变：理想 |S11| 地板非零（约 -15dB），fake 应复现
    s11_fake = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    s11_ideal = 20 * np.log10(np.abs(ideal.s[:, 0, 0]) + 1e-12)
    assert np.max(np.abs(s11_fake - s11_ideal)) < 1.0  # dB 逐点贴合
    # S21 相位斜率（级联电长度）
    ph_fake = np.unwrap(np.angle(net.s[:, 0, 1]))
    ph_ideal = np.unwrap(np.angle(ideal.s[:, 0, 1]))
    assert np.max(np.abs(ph_fake - ph_ideal)) < np.deg2rad(2.0)


def test_wstep_asymmetric_s22_differs_from_s11():
    """非对称阶跃（z1≠z2）全矩阵：S22≠S11（Pozar T4.2 + 级联序修正）。

    回归钉：旧实现 s[:,1,1]=s11 且级联序倒置（第二段矩阵
    在输入侧），z1=50→z2=30 时 S22 与真值线性差 0.43-0.74。修复后闭式
    必须与两路独立裁判逐位一致：
    ① 第一性原理波动方程直解（边界条件直接解电压波幅，不经 ABCD 公式）；
    ② skrf 显式级联（匹配线 + impedance_mismatch 阶跃网络，方向全显式）。
    """
    import skrf

    from rfauto.adapters.fake_adapter import _tl_gamma, _wstep_sparams

    freq = np.linspace(2.0, 3.0, 101)
    eps = 2.9
    td = 0.0037
    z1, z2, z_ref, seg_mm = 50.0, 30.0, 50.0, 20.0
    s = _wstep_sparams(freq, eps_eff1=eps, eps_eff2=eps, z1=z1, z2=z2,
                       seg_len_mm=seg_mm, tan_d=td)

    # ① 第一性原理（f=2.5GHz 单点，电压波边界条件直解）
    f0 = 2.5e9
    c0 = 299792458.0
    beta = 2 * np.pi * f0 * np.sqrt(eps) / c0
    alpha = np.pi * f0 * np.sqrt(eps) * td / c0
    g = (alpha + 1j * beta) * (seg_mm * 1e-3)
    ep, em = np.exp(-g), np.exp(g)
    rho0 = z_ref / z1
    ca, cb = (1 + rho0) / 2, (1 - rho0) / 2
    da, db = (1 - rho0) / 2, (1 + rho0) / 2
    m = np.array([
        [ep * cb + em * db, -1.0, -1.0],
        [(ep * cb - em * db) / z1, -1.0 / z2, 1.0 / z2],
        [0.0, ep * (1 - z_ref / z2), em * (1 + z_ref / z2)],
    ], dtype=complex)
    v = np.array([-(ep * ca + em * da),
                  -(ep * ca - em * da) / z1, 0.0], dtype=complex)
    i_mid = 50
    s11_fp = np.linalg.solve(m, v)[0]
    assert np.abs(s11_fp - s[i_mid, 0, 0]) < 1e-9
    # S22 = 反转网络的 S11（30Ω 线在前）
    rho0r = z2 / z_ref
    car, cbr = (1 + rho0r) / 2, (1 - rho0r) / 2
    dar, dbr = (1 - rho0r) / 2, (1 + rho0r) / 2
    mr = np.array([
        [ep * cbr + em * dbr, -1.0, -1.0],
        [(ep * cbr - em * dbr) / z2, -1.0 / z1, 1.0 / z1],
        [0.0, ep * (1 - z_ref / z1), em * (1 + z_ref / z1)],
    ], dtype=complex)
    vr = np.array([-(ep * car + em * dar),
                   -(ep * car - em * dar) / z2, 0.0], dtype=complex)
    s22_fp = np.linalg.solve(mr, vr)[0]
    assert np.abs(s22_fp - s[i_mid, 1, 1]) < 1e-9

    # ② skrf 显式级联（方向全显式，逐频点全矩阵对照）
    fs = skrf.Frequency(float(freq[0]), float(freq[-1]), len(freq), unit="GHz")
    gamma = _tl_gamma(fs.f, eps, td)
    media50 = skrf.media.DefinedGammaZ0(frequency=fs, z0=z_ref, gamma=gamma)
    media30 = skrf.media.DefinedGammaZ0(frequency=fs, z0=z2, gamma=gamma)

    def mismatch_net(za, zb):
        smat = skrf.network.impedance_mismatch(
            np.full(len(fs), float(za)), np.full(len(fs), float(zb)))
        net = skrf.Network(frequency=fs, s=smat)
        net.z0 = [za, zb]
        return net

    net = media50.line(seg_mm, unit="mm")
    net = skrf.network.connect(net, 1, mismatch_net(z_ref, z2), 0)
    net = skrf.network.connect(net, 1, media30.line(seg_mm, unit="mm"), 0)
    net = skrf.network.connect(net, 1, mismatch_net(z2, z_ref), 0)
    assert np.max(np.abs(net.s[:, 0, 0] - s[:, 0, 0])) < 1e-9
    assert np.max(np.abs(net.s[:, 1, 1] - s[:, 1, 1])) < 1e-9
    assert np.max(np.abs(net.s[:, 1, 0] - s[:, 1, 0])) < 1e-9

    # 非对称是常态：z1≠z2 时 |S11−S22| 显著非零（防回退到 S22:=S11）
    diff = np.abs(s[:, 0, 0] - s[:, 1, 1])
    assert np.max(diff) > 0.1
    # 对称口径（z1=z2）必须退化为 S11=S22（同一性守卫）
    s_sym = _wstep_sparams(freq, eps_eff1=eps, eps_eff2=eps, z1=z_ref,
                           z2=z_ref, seg_len_mm=seg_mm, tan_d=td)
    assert np.max(np.abs(s_sym[:, 0, 0] - s_sym[:, 1, 1])) < 1e-9
    # 互易性守卫（级联 TL det(ABCD)=1）
    assert np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])) < 1e-9


def test_synthesize_wstep_model_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_wstep_model

    result = synthesize_wstep_model(z1_ohm=50.0, z2_ohm=35.0, freq_ghz=2.5,
                                    line_len_mm=40.0)
    assert result.model == "wstep"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w1_ref, _, _ = inverse_width(50.0, 2.5, st)
    w2_ref, _, _ = inverse_width(35.0, 2.5, st)
    assert result.params["w1_mm"] == pytest.approx(w1_ref, abs=0.01)
    assert result.params["w2_mm"] == pytest.approx(w2_ref, abs=0.01)
    # objectives 地板 = 理想失配 Γ + 3dB 裕量
    obj = result.recipe_draft["objectives"][0]
    assert obj["metric"] == "s11_db" and obj["op"] == "max_below"
    assert obj["value"] == pytest.approx(-12.1, abs=1.0)


def test_wstep_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("wstep")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("wstep", z1_ohm=50.0, z2_ohm=35.0)
    assert draft["model"] == "wstep"
    assert draft["params"]["w2_mm"]["value"] == pytest.approx(1.897, abs=0.02)


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "wstep" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "wstep"
    assert data["n_ports"] == TEMPLATE_META["wstep"]["n_ports"]
