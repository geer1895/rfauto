"""LM-2 Van Atta 回射阵内核单测（研究扩充 round4 中件包二）。

裁判口径（#118 双路径，不自证）：
- 回射恒等式：路径 A = 内核闭式推证（镜像配对相位共轭 → AF 峰在 u'=u，
  内核 docstring）；路径 B = array_synthesis.array_factor 数值扫角 argmax，
  预声明 ±0.5° 带（实测网格分辨率限 ~3e-3°）；
- 相位表：路径 A = 闭式几何级数（含多次反射，测试内独立展开 400 项求和
  互证）；路径 B = skrf connect 级联（DefinedGammaZ0 等长线）；预声明
  rel ≤ 1e-12；
- 等长失配不倾斜不变量：路径 A = 对称剖面奇分量恒 0（内核 docstring
  推导）；路径 B = 数值 AF argmax 仍指来波方向 + |AF(u)|=|Σe^{j2πL}| 精确
  恒等式（测试内独立求和）；
- 波前倾斜通用估计器：合成线性误差剖面 α·x → 解析 Δu = −α/2π vs 数值
  AF argmax（回收钉，#118 合成已知量回收范式）。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import van_atta as va

BAND = va.RETRO_ANGLE_BAND_DEG


def _af_direct(u_grid, weights, spacing_lambda):
    """复权重阵因子独立直算核（Σ w_n·e^{j2πd·u·n}，与 array_factor 完全独立）。"""
    idx = np.arange(weights.size, dtype=float)
    return weights @ np.exp(1j * 2.0 * np.pi * spacing_lambda * np.outer(idx, u_grid))


# ─── 1. 配对拓扑 ─────────────────────────────────────────────────────────────


def test_mirror_pairing_structure():
    p4 = va.mirror_pairing(4)
    assert p4 == ((0, 3), (1, 2))
    p8 = va.mirror_pairing(8)
    assert len(p8) == 4 and all(i + j == 7 for i, j in p8)
    seen = sorted(x for pr in p8 for x in pr)
    assert seen == list(range(8))
    p5 = va.mirror_pairing(5)
    assert p5 == ((0, 4), (1, 3), (2, 2))  # 奇数 N 中心元自配对（直通）


def test_build_vanatta_array_guards():
    with pytest.raises(ValueError):
        va.build_vanatta_array(1)
    with pytest.raises(ValueError):
        va.build_vanatta_array(0)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4.0)  # float 拒收（严格整数）
    with pytest.raises(ValueError):
        va.build_vanatta_array(True)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, spacing_lambda=0.0)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, spacing_lambda=-0.5)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, spacing_lambda=float("nan"))
    arr = va.build_vanatta_array(4)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, line_lengths_lambda=[0.1, 0.2, 0.3])  # 长度数 ≠ 配对数(2)
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, line_lengths_lambda=[0.1, -0.2])  # 负线长
    assert arr.center_index is None  # 偶数 N 无中心元（判缺失 is not None）
    assert va.build_vanatta_array(5).center_index == 2


def test_custom_pairing_validation():
    # 非整数配对 → ValueError（float/bool/str 一律，钉严格整数口径）
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, pairing=((0, 1.5), (2, 3)))
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, pairing=((0, True), (2, 3)))
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, pairing=((0, "3"), (2, 1)))
    # 非对合：端口重复 / 未全覆盖
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, pairing=((0, 1), (0, 2)))
    with pytest.raises(ValueError):
        va.build_vanatta_array(4, pairing=((0, 1), (2, 2)))
    # 合法自定义对合（交换书写次序）可接受
    arr = va.build_vanatta_array(4, pairing=((1, 0), (3, 2)))
    assert arr.pair_of(1) == 0 and arr.pair_of(0) == 1 and arr.pair_of(3) == 2


def test_array_to_dict_and_wiring_table():
    arr = va.build_vanatta_array(4, spacing_lambda=0.45, line_lengths_lambda=[0.1, 0.2])
    d = json.loads(json.dumps(arr.to_dict()))
    assert d["n_elements"] == 4 and d["spacing_lambda"] == 0.45
    assert d["pairing"] == [[0, 3], [1, 2]] and d["line_lengths_lambda"] == [0.1, 0.2]
    wt = va.vanatta_wiring_table(arr)
    assert wt["n_elements"] == 4 and len(wt["lines"]) == 2
    assert wt["lines"][0] == {
        "pair_index": 0, "element_a": 0, "element_b": 3, "through": False, "length_lambda": 0.1
    }
    odd = va.build_vanatta_array(5)
    assert va.vanatta_wiring_table(odd)["lines"][2]["through"] is True


# ─── 2. 回射恒等式 ───────────────────────────────────────────────────────────


def test_incident_phases_closed_form():
    arr = va.build_vanatta_array(4, spacing_lambda=0.5)
    # 独立路径 B：x=(−0.75,−0.25,0.25,0.75)，θ=30° → u=0.5 → v_n = e^{jπ·x_n}
    v = va.incident_phases(arr, 30.0)
    x = np.array([-0.75, -0.25, 0.25, 0.75])
    expect = np.exp(1j * np.pi * x)
    assert np.allclose(v, expect, rtol=1e-12, atol=1e-12)
    # 侧射来波：所有元同相（逐位 1+0j）
    v0 = va.incident_phases(arr, 0.0)
    assert np.all(v0 == 1.0)
    with pytest.raises(ValueError):
        va.incident_phases(arr, 95.0)


def test_excitations_conjugate_identity():
    arr8 = va.build_vanatta_array(8, spacing_lambda=0.5)
    for theta in (30.0, -45.0):
        v = va.incident_phases(arr8, theta)
        w = va.vanatta_excitations(arr8, theta)
        assert np.allclose(np.abs(w), 1.0, rtol=1e-12)
        # 镜像配对等长：出射相位 = −入射相位 + 常数（相位共轭斜坡，逐元）
        s = np.angle(w) + np.angle(v)
        assert np.allclose(s, s[0], atol=1e-12)
    # 奇数 N 中心元：w_c = v_c·e^{jφ_c}（直通自配对）
    arr9 = va.build_vanatta_array(9, spacing_lambda=0.5, line_lengths_lambda=[0.0] * 4 + [0.25])
    w9 = va.vanatta_excitations(arr9, 20.0)
    v9 = va.incident_phases(arr9, 20.0)
    assert w9[4] == pytest.approx(v9[4] * np.exp(2j * np.pi * 0.25), rel=1e-12)


def test_retro_scan_seven_points_main_criterion():
    """主判据：任意 θ∈[−60°,60°] 抽 7 点 → 重辐射 AF argmax = θ ±0.5°。"""
    arr = va.build_vanatta_array(8, spacing_lambda=0.5)
    scan = va.verify_retroreflection(arr)  # 缺省 7 点
    assert [s["theta_deg"] for s in scan] == [-60.0, -40.0, -20.0, 0.0, 20.0, 40.0, 60.0]
    errors = [abs(s["angle_error_deg"]) for s in scan]
    assert max(errors) <= BAND
    assert max(errors) < 0.05  # 实测网格分辨率限量级（如实上界，不凑 0.5 的满带）


def test_retro_scan_dirichlet_null_direction():
    """Σw=0 的 Dirichlet 零点来波方向（θ=30°，u=0.5=k/(N·d)）：守卫旁路面。

    该方向 Σw 精确为 0（array_factor 零和守卫的伪拒面——回射峰本身
    |AF(u)|=N 完全良好），内核 _af_complex 走同核直算旁路。
    """
    arr = va.build_vanatta_array(8, spacing_lambda=0.5)
    w = va.vanatta_excitations(arr, 30.0)
    assert abs(complex(w.sum())) == pytest.approx(0.0, abs=1e-12)  # 零和确在此触发
    peak = va.reradiated_af_peak(arr, 30.0)
    assert abs(peak["angle_error_deg"]) <= BAND
    assert peak["af_at_incident_abs"] == pytest.approx(8.0, rel=5e-3)  # 回射峰=N（网格限）


def test_retro_scan_odd_n_center_through():
    arr = va.build_vanatta_array(9, spacing_lambda=0.5, line_lengths_lambda=[0.12, 0.0, 0.3, 0.05, 0.2])
    scan = va.verify_retroreflection(arr, theta_deg_list=[-60.0, -30.0, 0.0, 30.0, 60.0])
    assert max(abs(s["angle_error_deg"]) for s in scan) <= BAND
    # 中心元直通激励与来波方向无关（x_c=0 → w_c=e^{jφ_c}，各向同性自项）
    w_a = va.vanatta_excitations(arr, 20.0)
    w_b = va.vanatta_excitations(arr, 50.0)
    assert w_a[4] == w_b[4]


def test_common_line_phase_invariance():
    """全线共模相移不改变回射峰（全局相位不可观测）。"""
    base = va.build_vanatta_array(8, spacing_lambda=0.5)
    common = va.build_vanatta_array(8, spacing_lambda=0.5, line_lengths_lambda=[0.37] * 4)
    s0 = va.verify_retroreflection(base, theta_deg_list=[-40.0, 10.0, 55.0], n_points=4001)
    s1 = va.verify_retroreflection(common, theta_deg_list=[-40.0, 10.0, 55.0], n_points=4001)
    for a, b in zip(s0, s1, strict=True):
        assert a["u_peak"] == b["u_peak"]  # 逐位同峰
        assert a["af_peak_abs"] == pytest.approx(b["af_peak_abs"], rel=1e-12)


def test_symmetric_length_errors_no_tilt_and_gain_loss():
    """等长失配不变量（镜像配对）：倾斜恰 0 + |AF(u)|=|Σe^{j2πL}| 精确恒等。"""
    lengths = [0.05, 0.02, 0.07, 0.03]  # 极差 0.05 < λ/16 → 门内
    arr = va.build_vanatta_array(8, spacing_lambda=0.5, line_lengths_lambda=lengths)
    profile = va.phase_error_profile(arr)
    tilt = va.wavefront_tilt_estimate(arr.positions_lambda(), profile)
    assert abs(tilt["slope_rad_per_lambda"]) < 1e-12  # 对称剖面奇分量精确为 0
    # 恒等式路径（独立求和）：|AF(u)| = |Σ_m e^{j2π·L_pair(m)}| = |2·Σ_k e^{j2πL_k}|
    expect = abs(sum(2.0 * np.exp(2j * np.pi * lv) for lv in lengths))
    for theta in (-50.0, -20.0, 25.0, 60.0):
        w = va.vanatta_excitations(arr, theta)
        u = math.sin(math.radians(theta))
        x = arr.positions_lambda()
        af_exact = float(np.abs(np.sum(w * np.exp(2j * np.pi * u * x))))
        assert af_exact == pytest.approx(expect, rel=1e-12)  # 精确恒等（无网格近似）
        peak = va.reradiated_af_peak(arr, theta)
        assert af_exact == pytest.approx(peak["af_at_incident_abs"], rel=5e-3)  # 网格极限
        assert abs(peak["angle_error_deg"]) <= BAND  # 门内失配不倾斜（数值 AF 路径）
    # 相干增益恒等：coherence_gain(δφ) = |AF(u)|/N
    assert va.coherence_gain(profile) == pytest.approx(expect / 8.0, rel=1e-12)
    # 门内判定
    assert va.equal_length_gate(lengths)["passed"] is True


def test_out_of_gate_errors_gain_loss_honest():
    """门外失配：等长门如实 FAIL，恒等式仍精确成立（倾斜仍 0）。"""
    lengths = [0.0, 0.2]  # N=4：极差 0.2λ > λ/16 → 任两线相位差 72°
    arr = va.build_vanatta_array(4, spacing_lambda=0.5, line_lengths_lambda=lengths)
    gate = va.equal_length_gate(lengths)
    assert gate["passed"] is False
    assert gate["spread_lambda"] == pytest.approx(0.2, rel=1e-12)
    assert gate["max_phase_error_deg"] == pytest.approx(72.0, rel=1e-12)
    profile = va.phase_error_profile(arr)
    expect = abs(2.0 * (1.0 + np.exp(2j * np.pi * 0.2)))
    assert va.coherence_gain(profile) == pytest.approx(expect / 4.0, rel=1e-12)
    tilt = va.wavefront_tilt_estimate(arr.positions_lambda(), profile)
    assert abs(tilt["slope_rad_per_lambda"]) < 1e-12  # 失配不倾斜与门内外无关


# ─── 3. 等长容差面：通用波前倾斜估计器 ────────────────────────────────────────


def test_wavefront_tilt_estimator_recycle():
    """合成线性误差剖面回收钉：δφ=α·x → Δu=−α/2π，数值 AF argmax 复核。"""
    arr = va.build_vanatta_array(8, spacing_lambda=0.5)
    x = arr.positions_lambda()
    alpha = 0.3  # rad/λ
    dphi = alpha * x + 0.7  # 非对称剖面（截距为共模，不影响倾斜）
    est = va.wavefront_tilt_estimate(x, dphi, theta_deg=20.0)
    assert est["slope_rad_per_lambda"] == pytest.approx(alpha, rel=1e-12)
    assert est["du"] == pytest.approx(-alpha / (2.0 * math.pi), rel=1e-12)
    # 数值复核：理想回射激励 × e^{jδφ} → AF 峰移到 u+Δu
    theta = 20.0
    w = va.vanatta_excitations(arr, theta) * np.exp(1j * dphi)
    u_grid = np.linspace(-1.0, 1.0, 20001)
    af = _af_direct(u_grid, w, 0.5)
    u_peak = float(u_grid[int(np.argmax(np.abs(af)))])
    u_pred = math.sin(math.radians(theta)) + est["du"]
    assert abs(u_peak - u_pred) * math.degrees(1.0) <= BAND  # Δθ ≤ 0.5°（网格限）
    assert est["tilt_deg"] == pytest.approx(math.degrees(math.asin(u_pred)) - theta, rel=1e-9)
    with pytest.raises(ValueError):
        va.wavefront_tilt_estimate(x[:4], dphi)  # 形状不符
    out = va.wavefront_tilt_estimate(x, dphi, theta_deg=-90.0)
    assert out["tilt_deg"] is None  # u+Δu 出可见区 → None（判缺失 is not None）


def test_equal_length_gate():
    assert va.equal_length_gate([0.1, 0.1, 0.1])["passed"] is True
    assert va.equal_length_gate([0.1, 0.1, 0.1])["spread_lambda"] == 0.0  # 0.0 合法（#364④）
    # 严格小于：ΔL 恰等于 λ/16 判 FAIL（钉死不模糊）
    edge = 1.0 / 16.0
    assert va.equal_length_gate([0.0, 0.0, edge])["passed"] is False
    assert va.equal_length_gate([0.0, 0.0, edge - 0.001])["passed"] is True
    # 容差参数显式可覆盖（spread 0.04：>1/32 FAIL，<1/16 PASS）
    assert va.equal_length_gate([0.0, 0.04], tol_lambda=1.0 / 32.0)["passed"] is False
    assert va.equal_length_gate([0.0, 0.04], tol_lambda=1.0 / 16.0)["passed"] is True
    assert va.equal_length_gate([0.3, 0.1])["max_phase_error_deg"] == pytest.approx(72.0)
    with pytest.raises(ValueError):
        va.equal_length_gate([])
    with pytest.raises(ValueError):
        va.equal_length_gate([0.1], tol_lambda=0.0)
    with pytest.raises(ValueError):
        va.equal_length_gate([0.1, float("nan")])


# ─── 4. skrf 级联面：单元 S + 等长线 → 相位表双路径 ───────────────────────────


def test_element_s_matrix_guards_and_values():
    s = va.element_s_matrix()
    assert np.array_equal(s, np.array([[0, 1], [1, 0]], dtype=complex))  # 理想直通逐位
    s2 = va.element_s_matrix(gamma_ant=0.2j, gamma_line=0.3, tau=0.9)
    assert s2[0, 0] == 0.2j and s2[1, 1] == 0.3 and s2[0, 1] == 0.9 and s2[1, 0] == 0.9
    assert va.element_s_matrix(tau=0.0)[0, 1] == 0.0  # τ=0 合法（#364④）
    with pytest.raises(ValueError):
        va.element_s_matrix(gamma_ant=1.2)
    with pytest.raises(ValueError):
        va.element_s_matrix(gamma_line=complex(1, 1))
    with pytest.raises(ValueError):
        va.element_s_matrix(tau=1.2)
    with pytest.raises(ValueError):
        va.element_s_matrix(tau=-0.1)


def test_transmission_table_closed_independent_series():
    """闭式路径 A vs 独立几何级数展开（路径 B'，400 项截断 |r|^400≈0）。"""
    arr = va.build_vanatta_array(4, spacing_lambda=0.5, line_lengths_lambda=[0.0, 0.37])
    table = va.transmission_table_closed(arr)
    assert table[0]["t_forward"] == 1.0  # L=0 理想直通逐位 1+0j
    assert table[0]["s_reflect_i"] == 0.0
    assert table[1]["t_forward"] == pytest.approx(np.exp(-2j * np.pi * 0.37), rel=1e-12)
    # 含多次反射：γ_l=0.2, τ=0.9, L=0.23 → 与显式级数逐位对照
    arr2 = va.build_vanatta_array(4, line_lengths_lambda=[0.23, 0.0])
    t_closed = va.transmission_table_closed(arr2, gamma_ant=0.1j, gamma_line=0.2, tau=0.9)
    phi = 2.0 * math.pi * 0.23
    r = 0.2**2 * np.exp(-2j * phi)
    series = sum((0.9**2) * np.exp(-1j * phi) * r**m for m in range(400))
    assert abs(complex(t_closed[0]["t_forward"])) > 0  # 幅值非零
    assert complex(t_closed[0]["t_forward"]) == pytest.approx(series, rel=1e-12)
    refl_expect = 0.1j + (0.9**2) * 0.2 * np.exp(-2j * phi) / (1.0 - r)
    assert complex(t_closed[0]["s_reflect_i"]) == pytest.approx(refl_expect, rel=1e-12)


def test_transmission_table_skrf_dual_path():
    """主判据：skrf connect 级联 vs 闭式逐位对照 rel ≤1e-12（#118）。"""
    arr = va.build_vanatta_array(
        8, spacing_lambda=0.5, line_lengths_lambda=[0.0, 0.11, 0.37, 0.23]
    )
    closed = va.transmission_table_closed(arr)
    skrf_tab = va.transmission_table_skrf(arr)
    assert va._complex_rel_max(closed, skrf_tab) <= va.TOL_DUAL_PATH
    # 含反射与损耗：多次反射路径同时钉（γ_l≠0、τ≠1、Γ_a≠0）
    closed2 = va.transmission_table_closed(arr, gamma_ant=0.1j, gamma_line=0.15, tau=0.95)
    skrf2 = va.transmission_table_skrf(arr, gamma_ant=0.1j, gamma_line=0.15, tau=0.95)
    rel2 = va._complex_rel_max(closed2, skrf2)
    assert rel2 <= va.TOL_DUAL_PATH
    # 奇数 N（自配对直通对）双路径同样成立
    odd = va.build_vanatta_array(7, spacing_lambda=0.5, line_lengths_lambda=[0.1, 0.25, 0.0, 0.05])
    rel_odd = va._complex_rel_max(
        va.transmission_table_closed(odd, gamma_line=0.1),
        va.transmission_table_skrf(odd, gamma_line=0.1),
    )
    assert rel_odd <= va.TOL_DUAL_PATH


def test_full_network_block_structure():
    """全阵网络：端口自然序、对间隔离精确 0、对内传输=闭式表。"""
    arr = va.build_vanatta_array(8, spacing_lambda=0.5, line_lengths_lambda=[0.05, 0.2, 0.0, 0.13])
    net = va.build_vanatta_network(arr)
    assert net.nports == 8
    s = np.asarray(net.s[0])
    pair_set = {frozenset(p) for p in arr.pairing}
    for m in range(8):
        for n in range(8):
            if frozenset((m, n)) in pair_set:
                continue
            assert s[m, n] == 0.0  # 块对角精确零（纯拼接，无求解）
    closed = va.transmission_table_closed(arr)
    for row in closed:
        i, j = row["element_i"], row["element_j"]
        assert s[j, i] == pytest.approx(complex(row["t_forward"]), rel=1e-12, abs=1e-15)
        assert s[i, j] == pytest.approx(complex(row["t_reverse"]), rel=1e-12, abs=1e-15)


# ─── 5. 端到端报告与信封 ─────────────────────────────────────────────────────


def test_verify_vanatta_report_all_pass():
    arr = va.build_vanatta_array(8, spacing_lambda=0.5)
    rep = va.verify_vanatta(arr)
    assert rep.all_pass is True
    assert max(abs(e) for e in rep.angle_error_deg) <= rep.angle_band_deg
    assert rep.dual_path_max_rel is not None and rep.dual_path_max_rel <= va.TOL_DUAL_PATH
    assert rep.length_gate_pass is True and rep.phase_profile_symmetric is True
    assert rep.coherence_gain == pytest.approx(1.0, rel=1e-12)  # 全等长无相干损失
    d = json.loads(json.dumps(rep.to_dict()))
    assert d["all_pass"] is True and d["n_elements"] == 8
    assert len(d["thetas_deg"]) == 7


def test_verify_vanatta_report_honest_fail():
    arr = va.build_vanatta_array(8, spacing_lambda=0.5, line_lengths_lambda=[0.0, 0.0, 0.0, 0.3])
    rep = va.verify_vanatta(arr)
    assert rep.length_gate_pass is False  # 极差 0.3λ > λ/16 → 门红
    assert rep.equal_length_spread_lambda == pytest.approx(0.3, rel=1e-12)
    assert rep.all_pass is False  # 如实 FAIL（不凑绿）
    assert rep.dual_path_max_rel is not None  # 双路径仍跑（失配不影响级联恒等）
    skip = va.verify_vanatta(arr, dual_path=False)
    assert skip.dual_path_max_rel is None
    assert skip.all_pass is False  # 未跑不判 PASS（#122 精神，如实）


def test_service_envelope():
    from rfauto.service import van_atta_service as vas

    rep = vas.van_atta_report(8, n_points=2001)
    assert rep["ok"] is True and rep["data"]["all_pass"] is True
    payload = vas.van_atta_payload(4, line_lengths_lambda=[0.05, 0.1])
    assert payload["ok"] is True
    data = payload["data"]
    json.loads(json.dumps(data))  # 全载荷 JSON 可序列化（复数已折 [re, im]）
    assert data["wiring_table"]["n_elements"] == 4
    assert len(data["transmission_table_closed"]) == 2
    assert len(data["transmission_table_closed"][0]["t_forward"]) == 2  # [re, im]
    # 异常 → 信封 ok=False 不抛
    bad = vas.van_atta_report(1)
    assert bad["ok"] is False and "error" in bad
    bad2 = vas.van_atta_payload(4, spacing_lambda=-1.0)
    assert bad2["ok"] is False and "error" in bad2
