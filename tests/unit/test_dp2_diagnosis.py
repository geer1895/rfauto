"""DP-2 耦合矩阵诊断三件套判据测试（df6_dp2diag，2026-09-24）。

判据预声明 runs/df6_dp2diag/criteria.md（先写后跑，#122）；全部合成回收，
裁判=综合内核真值/解析已知量，独立于被测实现（#118/#300）：
- ① CM 回收：synthesize（N=2..6、folded/arrow、TZ 0-2）→response→提取→
  逐元素 ≤5%；噪声 σ=1e-3/1e-2 → ≤10% 或 ok=False；
- ② Q 回收：单极点解析 fixture（Qu∈{100,500,2000}×β∈{0.5,1,2}）→
  两通道各 ≤2%（无噪）/≤8%（σ=1e-3），互证差 ≤10%；
- ③ C 系数钉：S21 透射泄漏 C=2、S11 反射全通 C=4（两候选 /2、/4 均被
  合成回收唯一确定，分属两测量端口；写死 calculators 模块头）；
- ④ skrf.qfactor 第三方仲裁（三方极差 ≤15%）+ UNDECIDABLE 路径。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    _CAT_C_REFLECTION,
    _CAT_C_TRANSMISSION,
    _cm_from_list,
    _cm_reduce_arrow,
    _cm_reduce_folded,
    _cm_response_raw,
    _cm_sign_normalize,
    _dp2_group_delay_phys,
    _dp2_prominent_peaks,
    _dp2_response_batch,
    _taubin_circle_fit,
)
from rfauto.service.calculator_service import run_calculator
from rfauto.service.diagnosis_service import (
    diagnose_q,
    run_diagnosis,
)

F0_GHZ = 2.5
FBW = 0.1
CASES_DIR = Path(__file__).resolve().parents[2] / "runs" / "df6_dp2diag"


# ─── fixtures / helpers（裁判面：解析式+综合内核真值，独立于被测键）──────────


def _single_pole_s11(freq_ghz, q_u: float, beta: float):
    """解析单极点反射 Γ=(β−1−jQu·x)/(β+1+jQu·x)（Q 双通道回收裁判真值）。"""
    f = np.asarray(freq_ghz, dtype=float)
    x = f / F0_GHZ - F0_GHZ / f
    return (beta - 1.0 - 1j * q_u * x) / (beta + 1.0 + 1j * q_u * x)


def _pair(v):
    return [float(np.real(v)), float(np.imag(v))]


def _cm_true(order: int, tz_pairs: list):
    out = run_calculator("coupling_matrix_synthesize_n2", {
        "order": order, "rl_db": 20.0, "transmission_zeros": tz_pairs})
    assert out["ok"], out
    return _cm_from_list(out["result"]["coupling_matrix"])


def _cm_sweep(matrix, freq_ghz):
    """既有 coupling_matrix_response 键产复 S11/S21（响应裁判=独立既有键）。"""
    out = run_calculator("coupling_matrix_response", {
        "freq_ghz": [float(v) for v in freq_ghz], "f0_ghz": F0_GHZ,
        "fbw": FBW,
        "matrix": [[_pair(v) for v in row] for row in matrix]})
    assert out["ok"], out
    s = out["result"]["s_matrix"]
    s11 = np.array([complex(v[0][0][0], v[0][0][1]) for v in s])
    s21 = np.array([complex(v[1][0][0], v[1][0][1]) for v in s])
    return s11, s21


def _rel_dev(m_hat, m_true) -> float:
    """逐元素相对偏差（先按仓内 _cm_sign_normalize 规范节点符号——DMD 相似
    变换 |S| 不变，符号非可辨识量）。"""
    a, _ = _cm_sign_normalize(np.array(m_hat, dtype=complex))
    b, _ = _cm_sign_normalize(np.array(m_true, dtype=complex))
    worst = 0.0
    n = b.shape[0]
    for i in range(n):
        for j in range(i + 1, n):
            if abs(b[i, j]) > 1e-9:
                worst = max(worst, float(abs(a[i, j] - b[i, j])
                                         / abs(b[i, j])))
    return worst


def _extract_refine(freq_ghz, s11, s21, order, topology,
                    n_starts=1, loss=True, tz=None):
    ext = run_calculator("cm_extract_vf", {
        "freq_ghz": [float(v) for v in freq_ghz],
        "s11": [_pair(v) for v in s11],
        "s21": [_pair(v) for v in s21],
        "order": order, "f0_ghz": F0_GHZ, "fbw": FBW,
        "topology": topology, "k_max": 2})
    assert ext["ok"], ext.get("error") or ext["result"]
    rext = ext["result"]
    ref = run_calculator("cm_refine_lm", {
        "freq_ghz": [float(v) for v in freq_ghz],
        "s11": [_pair(v) for v in s11],
        "s21": [_pair(v) for v in s21],
        "matrix": rext["coupling_matrix"],
        "f0_ghz": rext["f0_ghz"], "fbw": rext["fbw"],
        "topology": topology, "loss": loss,
        "transmission_zeros_norm": tz,
        "homotopy_steps": 4, "n_starts": n_starts})
    assert ref["ok"], ref.get("error") or ref["result"]
    return rext, ref["result"]


# ─── 0. 内核底座：向量化逐位一致（#329）+ Taubin 精确回收（#118）──────────────


def test_response_batch_bitwise_equals_scalar():
    """_dp2_response_batch 与 _cm_response_raw 逐位一致（缺省语义不变）。"""
    m = np.array([[0, 1, 0.5j, 0], [1, 0.2 + 0.05j, 0.9, 0.3],
                  [0.5j, 0.9, -0.1 + 0.02j, 1], [0, 0.3, 1, 0]], complex)
    om = np.linspace(-1.2, 1.2, 37)
    a11, a21 = _dp2_response_batch(m, 1.2, 0.9, om)
    for i, w in enumerate(om):
        b11, b21 = _cm_response_raw(m, 1.2, 0.9, w)
        assert a11[i] == b11
        assert a21[i] == b21


def test_taubin_fit_exact_full_circle_and_short_arc():
    """整圆与 30° 短弧精确回收（Kasa 小弧有偏故弃用；裁判=已知圆）。"""
    cx0, cy0, r0 = 1.3, -0.7, 2.1
    for th in (np.linspace(0.0, 2 * np.pi, 200),
               np.linspace(0.0, np.pi / 6, 60)):
        xs = cx0 + r0 * np.cos(th)
        ys = cy0 + r0 * np.sin(th)
        cx, cy, r = _taubin_circle_fit(xs, ys)
        assert abs(cx - cx0) < 1e-9
        assert abs(cy - cy0) < 1e-9
        assert abs(r - r0) / r0 < 1e-9


def test_taubin_fit_noise_arc_within_half_percent():
    rng = np.random.default_rng(7)
    th = np.linspace(0.0, np.pi / 3, 80)
    xs = 1.3 + 2.1 * np.cos(th) + rng.normal(0, 0.002, 80)
    ys = -0.7 + 2.1 * np.sin(th) + rng.normal(0, 0.002, 80)
    cx, cy, r = _taubin_circle_fit(xs, ys)
    assert abs(cx - 1.3) < 0.01
    assert abs(cy + 0.7) < 0.01
    assert abs(r - 2.1) / 2.1 < 0.005


# ─── §4.2 Q 回收（两通道 + 互证）──────────────────────────────────────────────


@pytest.mark.parametrize("q_u,beta", [(100.0, 0.5), (100.0, 2.0),
                                      (500.0, 0.5), (500.0, 1.0),
                                      (500.0, 2.0), (2000.0, 0.5),
                                      (2000.0, 1.0), (2000.0, 2.0)])
def test_q_recovery_noiseless_two_channels(q_u: float, beta: float):
    n_pts = {100.0: 201, 500.0: 401, 2000.0: 1201}[q_u]
    freq = np.linspace(F0_GHZ * 0.96, F0_GHZ * 1.04, n_pts)
    g = _single_pole_s11(freq, q_u, beta)
    rv = run_calculator("q_factor_vf", {
        "freq_ghz": [float(v) for v in freq], "s11": [_pair(v) for v in g],
        "f0_hint_ghz": F0_GHZ, "q_e": [q_u / beta]})
    rc = run_calculator("q_factor_circle", {
        "freq_ghz": [float(v) for v in freq], "s11": [_pair(v) for v in g]})
    assert rv["ok"] and rc["ok"], (rv, rc)
    qv = rv["result"]["q_unloaded"]
    qc = rc["result"]["q_unloaded"]
    assert abs(qv - q_u) / q_u <= 0.02, f"vf: {qv} vs {q_u}"
    assert abs(qc - q_u) / q_u <= 0.02, f"circle: {qc} vs {q_u}"
    assert abs(qv - qc) / q_u <= 0.10
    assert rc["result"]["coupling_side"] == (
        "over" if beta > 1 else ("critical" if beta == 1 else "under"))


@pytest.mark.parametrize("q_u,beta", [(100.0, 0.5), (500.0, 1.0),
                                      (2000.0, 2.0)])
def test_q_recovery_noise_sigma_1e3(q_u: float, beta: float):
    rng = np.random.default_rng(42)
    n_pts = {100.0: 201, 500.0: 401, 2000.0: 1201}[q_u]
    freq = np.linspace(F0_GHZ * 0.96, F0_GHZ * 1.04, n_pts)
    g = _single_pole_s11(freq, q_u, beta)
    g = g + 1e-3 * (rng.standard_normal(g.size)
                    + 1j * rng.standard_normal(g.size))
    rv = run_calculator("q_factor_vf", {
        "freq_ghz": [float(v) for v in freq], "s11": [_pair(v) for v in g],
        "f0_hint_ghz": F0_GHZ, "q_e": [q_u / beta]})
    rc = run_calculator("q_factor_circle", {
        "freq_ghz": [float(v) for v in freq], "s11": [_pair(v) for v in g]})
    qv = rv["result"]["q_unloaded"]
    qc = rc["result"]["q_unloaded"]
    assert abs(qv - q_u) / q_u <= 0.08
    assert abs(qc - q_u) / q_u <= 0.08
    assert abs(qv - qc) / q_u <= 0.10


def test_q_loss_degraded_flag():
    """|Re p|/|Im p| > 0.05 → loss_degraded 如实标记（criteria §2）。"""
    freq = np.linspace(F0_GHZ * 0.96, F0_GHZ * 1.04, 201)
    g = _single_pole_s11(freq, 20.0, 1.0)  # Qu=20 → 阻尼比 1/40≈0.025…不够；
    # 直接压低 Qu 到 8 → |Re p|/|Im p| ≈ 1/(2·8) = 0.0625 > 0.05
    g = _single_pole_s11(freq, 8.0, 1.0)
    rv = run_calculator("q_factor_vf", {
        "freq_ghz": [float(v) for v in freq], "s11": [_pair(v) for v in g],
        "f0_hint_ghz": F0_GHZ})
    assert rv["result"]["loss_degraded"] is True


# ─── §4.3 C 系数钉（合成回收唯一确定，写死 docstring）────────────────────────


def test_c_coefficient_pins():
    """反射全通 C=4 / Dishal 透射泄漏 C=2（两候选 /2、/4 均被回收确定，
    分属两端口；错配 C 值偏差 ≈2× 判死）。"""
    w0 = 2.0 * math.pi * F0_GHZ * 1e9

    # 实验 A：反射全通（N=1 一端口口径：m01=0.9 → Qe=1/(fbw·m01²)）
    m01 = 0.9
    qe_true = 1.0 / (FBW * m01 ** 2)
    om = np.linspace(-1.4, 1.4, 4001)
    m1 = np.zeros((3, 3), dtype=complex)
    m1[0, 1] = m1[1, 0] = m01
    s11 = np.array([_cm_response_raw(m1, 1.0, 1.0, w)[0] for w in om])
    freq = F0_GHZ + om * FBW * F0_GHZ / 2.0  # 窄带 Ω→f 映射（τ 判据足够）
    tau = _dp2_group_delay_phys(freq, s11)
    i_pk = _dp2_prominent_peaks(np.abs(tau))[0]
    qe_c4 = w0 * float(abs(tau[i_pk])) / _CAT_C_REFLECTION
    qe_c2 = w0 * float(abs(tau[i_pk])) / 2.0
    assert abs(qe_c4 - qe_true) / qe_true < 0.02, "反射口径 C=4 回收失败"
    assert abs(qe_c2 - qe_true) / qe_true > 0.9, "C=2 错配未被否决"

    # 实验 B：Dishal 透射泄漏（N=2、腔 2 失谐 ±10，m01=0.9）
    for detune in (10.0, -10.0):
        m2 = np.zeros((4, 4), dtype=complex)
        m2[0, 1] = m2[1, 0] = m01
        m2[1, 2] = m2[2, 1] = 0.9
        m2[2, 3] = m2[3, 2] = m01
        m2[2, 2] = detune
        s21 = np.array([_cm_response_raw(m2, 1.0, 1.0, w)[1] for w in om])
        tau = _dp2_group_delay_phys(freq, s21)
        i_pk = _dp2_prominent_peaks(np.abs(tau))[0]
        qe_c2t = w0 * float(abs(tau[i_pk])) / _CAT_C_TRANSMISSION
        qe_c4t = w0 * float(abs(tau[i_pk])) / 4.0
        assert abs(qe_c2t - qe_true) / qe_true < 0.02, \
            "透射口径 C=2 回收失败"
        assert abs(qe_c4t - qe_true) / qe_true > 0.4, "C=4 错配未被否决"
        # 失谐方向指纹：τ 峰偏向失谐反侧
        offset = freq[i_pk] - F0_GHZ
        assert offset * detune < 0


# ─── §4.4 skrf 第三方仲裁 + UNDECIDABLE 路径 ─────────────────────────────────


def test_skrf_third_party_arbitration_agree():
    freq = list(np.linspace(F0_GHZ * 0.96, F0_GHZ * 1.04, 201))
    g = _single_pole_s11(np.array(freq), 500.0, 2.0)
    r = diagnose_q({"freq_ghz": freq, "s11": [_pair(v) for v in g],
                    "f0_hint_ghz": F0_GHZ, "q_e": [250.0]})
    assert r["ok"]
    assert r["result"]["verdict"] == "AGREE"
    third = r["result"]["third_opinion"]
    assert not third.get("unavailable"), third
    chk = r["result"]["third_check"]
    assert chk is not None and chk["within_15pct"] is True
    assert chk["range_pct"] <= 0.15


def test_undecidable_path_when_channels_disagree():
    """双谐振混叠（2.5GHz Q=500 主谐振 + 2.615GHz Q=150 副谐振）：单极点
    通道各自锁定不同特征 → 数值互证差 80% → UNDECIDABLE（不冒充，#122）。"""
    freq = list(np.linspace(2.35, 2.65, 801))
    om1 = np.array([v / F0_GHZ - F0_GHZ / v for v in freq])
    om2 = np.array([v / 2.615 - 2.615 / v for v in freq])
    g1 = (1.0 - 1j * 500.0 * om1) / (1.0 + 1j * 500.0 * om1)
    g2 = (1.0 - 1j * 150.0 * om2) / (1.0 + 1j * 150.0 * om2)
    g = (g1 + g2) / np.max(np.abs(g1 + g2)) * 0.999
    r = diagnose_q({"freq_ghz": freq, "s11": [_pair(v) for v in g],
                    "f0_hint_ghz": F0_GHZ, "q_e": [500.0]})
    assert r["ok"], r
    res = r["result"]
    assert res["verdict"] == "UNDECIDABLE"
    assert res["cross_diff_pct"] > 0.10


# ─── §4.1 CM 回收（N=2..6、folded/arrow、TZ 0-2）─────────────────────────────


_FOLDED_CASES = [(2, []), (2, [1.5]), (3, []), (3, [1.5]), (4, []),
                 (4, [1.5]), (4, [1.5, 2.0]), (5, []), (5, [1.5, 2.0]),
                 (6, [1.5, 2.0])]
_ARROW_CASES = [(2, []), (4, [1.5])]


@pytest.mark.parametrize("order,tz", _FOLDED_CASES)
def test_cm_recovery_folded(order: int, tz: list):
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09),
                       121 if order <= 4 else 141)
    m_true = _cm_true(order, tz)
    s11, s21 = _cm_sweep(m_true, freq)
    rext, rref = _extract_refine(freq, s11, s21, order, "folded")
    assert rref["fit_rms"] <= 1e-2
    assert rref["response_max_dev"] <= 0.05
    # 真值须经同一拓扑约简（synthesize 产出=横向矩阵；对比同拓扑同符号规范）
    m_true_topo, _ = _cm_reduce_folded(m_true)
    dev = _rel_dev(_cm_from_list(rref["coupling_matrix"]), m_true_topo)
    assert dev <= 0.05, f"N={order} tz={tz}: 逐元素偏差 {dev:.2e}"
    assert rext["order"] == order


@pytest.mark.parametrize("order,tz", _ARROW_CASES)
def test_cm_recovery_arrow(order: int, tz: list):
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 121)
    m_true = _cm_true(order, tz)
    s11, s21 = _cm_sweep(m_true, freq)
    _rext, rref = _extract_refine(freq, s11, s21, order, "arrow")
    m_true_topo = _cm_reduce_arrow(m_true)
    dev = _rel_dev(_cm_from_list(rref["coupling_matrix"]), m_true_topo)
    assert dev <= 0.05, f"arrow N={order}: 逐元素偏差 {dev:.2e}"


def test_cm_recovery_auto_order_detect():
    """不给 order：VF 定阶扫描自动判 N=3（criteria §0 定阶 rms 平台）。"""
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 161)
    m_true = _cm_true(3, [1.5])
    s11, s21 = _cm_sweep(m_true, freq)
    ext = run_calculator("cm_extract_vf", {
        "freq_ghz": [float(v) for v in freq],
        "s11": [_pair(v) for v in s11], "s21": [_pair(v) for v in s21],
        "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded", "k_max": 5})
    assert ext["ok"], ext
    assert ext["result"]["order"] == 3
    assert ext["result"]["n_fz"] == 2  # ±1.5 对=P 次数 2（与既有键口径一致）


def test_cm_recovery_with_noise_sigma_1e3():
    rng = np.random.default_rng(42)
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 161)
    m_true = _cm_true(3, [1.5])
    s11, s21 = _cm_sweep(m_true, freq)
    s11n = s11 + 1e-3 * (rng.standard_normal(s11.size)
                         + 1j * rng.standard_normal(s11.size))
    s21n = s21 + 1e-3 * (rng.standard_normal(s21.size)
                         + 1j * rng.standard_normal(s21.size))
    ext = run_calculator("cm_extract_vf", {
        "freq_ghz": [float(v) for v in freq],
        "s11": [_pair(v) for v in s11n], "s21": [_pair(v) for v in s21n],
        "order": 3, "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded",
        "k_max": 2})
    ref = run_calculator("cm_refine_lm", {
        "freq_ghz": [float(v) for v in freq],
        "s11": [_pair(v) for v in s11n], "s21": [_pair(v) for v in s21n],
        "matrix": ext["result"]["coupling_matrix"],
        "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded",
        "homotopy_steps": 4, "n_starts": 2})
    m_true_topo, _ = _cm_reduce_folded(m_true)
    dev = _rel_dev(_cm_from_list(ref["result"]["coupling_matrix"]),
                   m_true_topo)
    # 判据族 ①：噪声 σ=1e-3 → ≤10% 或 ok=False（如降级必须如实带门原因）
    if ref["result"]["ok"]:
        assert dev <= 0.10, f"噪声 σ=1e-3 偏差 {dev:.2e} 超 10%"
    else:
        assert ref["result"]["ok_reason"]


def test_cm_recovery_heavy_noise_sigma_1e2_honest():
    """σ=1e-2：≤10% 或 ok=False 皆可，绝不假绿（criteria §1）。"""
    rng = np.random.default_rng(7)
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 161)
    m_true = _cm_true(2, [])
    s11, s21 = _cm_sweep(m_true, freq)
    s11n = s11 + 1e-2 * (rng.standard_normal(s11.size)
                         + 1j * rng.standard_normal(s11.size))
    s21n = s21 + 1e-2 * (rng.standard_normal(s21.size)
                         + 1j * rng.standard_normal(s21.size))
    ext = run_calculator("cm_extract_vf", {
        "freq_ghz": [float(v) for v in freq],
        "s11": [_pair(v) for v in s11n], "s21": [_pair(v) for v in s21n],
        "order": 2, "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded",
        "k_max": 2})
    if not ext["ok"]:
        return  # 段一如实失败即符合判据（不冒充）
    ref = run_calculator("cm_refine_lm", {
        "freq_ghz": [float(v) for v in freq],
        "s11": [_pair(v) for v in s11n], "s21": [_pair(v) for v in s21n],
        "matrix": ext["result"]["coupling_matrix"],
        "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded",
        "homotopy_steps": 4, "n_starts": 2})
    m_true_topo, _ = _cm_reduce_folded(m_true)
    dev = _rel_dev(_cm_from_list(ref["result"]["coupling_matrix"]),
                   m_true_topo)
    if ref["result"]["ok"]:
        assert dev <= 0.10, f"σ=1e-2 偏差 {dev:.2e} 超 10%"
    else:
        assert ref["result"]["ok_reason"]


def test_cm_recovery_with_diagonal_loss():
    """可选损耗（d=0.02）：损耗可辨识，耦合/对角一并 ≤5%（criteria §1）。"""
    freq = np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 161)
    m_true = _cm_true(3, [1.5])
    m_lossy = m_true.copy()
    for k in range(1, m_true.shape[0] - 1):
        m_lossy[k, k] = m_lossy[k, k] + 0.02j
    s11, s21 = _cm_sweep(m_lossy, freq)
    _rext, rref = _extract_refine(freq, s11, s21, 3, "folded", loss=True)
    m_true_topo, _ = _cm_reduce_folded(m_lossy)
    dev = _rel_dev(_cm_from_list(rref["coupling_matrix"]), m_true_topo)
    assert dev <= 0.05, f"损耗链路逐元素偏差 {dev:.2e}"


# ─── cat_critique 阶段判据（Qe 步 / k12 步 / 指纹）────────────────────────────


def _cat_on_matrix(matrix, **extra):
    freq = [round(2.0 + 0.0005 * i, 6) for i in range(2001)]
    _s11, s21 = _cm_sweep(matrix, np.array(freq))
    target = _cm_true(2, [1.5])
    r = run_calculator("cat_critique", {
        "freq_ghz": freq, "s21": [_pair(v) for v in s21],
        "f0_ghz": F0_GHZ, "fbw": FBW,
        "target_matrix": [[_pair(v) for v in row] for row in target],
        **extra})
    assert r["ok"], r
    return r["result"]


def test_cat_qe_step_recovers_qe_and_offset_fingerprint():
    """步①（腔 2 远失谐 +10）：Qe1=ω0·τmax/C，C=2 回收 ≤2%；峰位偏=失谐方向。"""
    m = np.zeros((4, 4), dtype=complex)
    m[0, 1] = m[1, 0] = 0.15
    m[1, 2] = m[2, 1] = 0.9
    m[2, 3] = m[3, 2] = 0.15
    m[2, 2] = 10.0  # 腔 2 远失谐（正失谐）
    r = _cat_on_matrix(m, current_params={"gap_in_mm": 0.4})
    qe_true = 1.0 / (FBW * 0.15 ** 2)
    assert r["c_coef"] == _CAT_C_TRANSMISSION == 2.0
    assert abs(r["qe_measured"] - qe_true) / qe_true <= 0.02
    assert r["fingerprint"]["peak_offset_pct"] < 0  # 正失谐 → 峰偏低频
    assert r["issues"], "与任取目标偏差应发 issue"
    assert any(f["kind"] == "qe_adjust" for f in r["fixes"])


def test_cat_k_step_split_formula_on_weak_tap():
    """步②（弱抽头双峰）：k=(f₂²−f₁²)/(f₂²+f₁²) 回收 m12·fbw ≤5%。"""
    m = np.zeros((4, 4), dtype=complex)
    m[0, 1] = m[1, 0] = 0.15
    m[1, 2] = m[2, 1] = 0.2
    m[2, 3] = m[3, 2] = 0.15
    r = _cat_on_matrix(m)
    assert r["n_peaks"] >= 2
    k_true = 0.2 * FBW
    assert abs(r["k_measured"] - k_true) / k_true <= 0.05


def test_cat_service_level_with_matching_target_pass():
    """目标=被测自身设计值 → PASS 无 issue（service 编排面）。"""
    m_pair = np.zeros((4, 4), dtype=complex)
    m_pair[0, 1] = m_pair[1, 0] = 0.15
    m_pair[1, 2] = m_pair[2, 1] = 0.2
    m_pair[2, 3] = m_pair[3, 2] = 0.15
    freq = [round(2.0 + 0.0005 * i, 6) for i in range(2001)]
    _, s21 = _cm_sweep(m_pair, np.array(freq))
    target = run_calculator("coupling_matrix_synthesize_n2", {
        "order": 2, "rl_db": 25.0})
    tm = target["result"]["coupling_matrix"]
    r = run_diagnosis({
        "mode": "cat", "freq_ghz": freq,
        "s21": [[float(np.real(v)), float(np.imag(v))] for v in s21],
        "f0_ghz": F0_GHZ, "fbw": FBW,
        "target_matrix": [[float(np.real(v)) if np.imag(v) == 0 else
                           [float(np.real(v)), float(np.imag(v))]
                           for v in row] for row in
                          _cm_from_list(tm)],
        "current_params": {"gap12_mm": 0.3}})
    assert r["ok"], r
    res = r["result"]
    # k12 步判决相对自洽目标：m12 同量级（综合目标 ~0.1-0.15）→ 不发 k issue
    assert res.get("k_measured") is not None


# ─── service 编排面（CM 目标偏差表 + ok 门）──────────────────────────────────


def test_service_cm_target_check_pass():
    freq = list(np.linspace(F0_GHZ * (1 - 0.09), F0_GHZ * (1 + 0.09), 121))
    m_true = _cm_true(3, [1.5])
    s11, s21 = _cm_sweep(m_true, np.array(freq))
    r = run_diagnosis({
        "mode": "cm", "freq_ghz": freq,
        "s11": [_pair(v) for v in s11], "s21": [_pair(v) for v in s21],
        "f0_ghz": F0_GHZ, "fbw": FBW, "topology": "folded",
        "target_matrix": [[_pair(v) for v in row] for row in m_true]})
    assert r["ok"], r
    chk = r["result"]["target_check"]
    assert chk["pass"] is True
    assert chk["max_rel_dev"] <= 0.05
    assert r["result"]["refine"]["ok"] is True


def test_service_unknown_mode_explicit_error():
    r = run_diagnosis({"mode": "nope"})
    assert r["ok"] is False
    assert "未知 mode" in r["error"]
