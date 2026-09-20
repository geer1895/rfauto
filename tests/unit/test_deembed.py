"""§10.20 ② 端口去嵌入标准化（core/deembed.py）单测。

覆盖：
- 合成误差网络恢复（thru/line 差分、端口平移、OpenShort）——误差界=实测达到值；
- 恒等（无误差）不变、确定性（两次逐字节一致）；
- 非法输入/维度不符显式报错；
- via β2 真实归档（runs/via_smoke/pt3/port_beta.csv）去嵌验收：εeff2 与
  εeff1 自洽 ≤1%，且 1.0491 常数被复现（归档自算 1.049083，落 #205 定版
  1.0491±0.0011 窗内）；
- 2026-09-13 收口：三点波动方程估计器（驻波免疫）合成解析验证 + via 镜像
  前提裁决（归档原始探针场否证镜像前提，1.0491 = 真实模态比 × 链路残差；
  runs/ 缺失时 skip）。

裁判独立性（不得自证）：
- ≤1% 一致性断言用**定版常数 1.0491**（外部独立来源）做去嵌，
  不用归档自算的尺度；
- 归档自算尺度只用于"复现 #205 常数"与"带内恒定"两个断言。
- 归档缺失时相关用例 pytest.skip（不假装通过）。

数值容差 = 本机实测达到值（skrf 2.1.0 / Python 3.12.14）：
- 级联类恢复 ≤1.4e-16 → 门 1e-12；
- OpenShort 恢复 ≤4.2e-16 → 门 1e-12；
- γ 提取误差 ≤2.8e-14 → 门 1e-9。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import skrf

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

from rfauto.core.deembed import (
    C0,
    DOCUMENTED_VIA_SCALE,
    DOCUMENTED_VIA_SCALE_HALF_WIDTH,
    analyze_via_port_scale,
    beta_from_eps_eff,
    beta_from_voltage_trio,
    deembed_open_short,
    deembed_port_scale,
    deembed_reference_delay,
    deembed_reference_plane,
    deembed_thru,
    deembed_thru_line,
    derive_via_mirror_verdict,
    eps_eff_from_beta,
    estimate_port_scale,
    extract_line_gamma,
    ideal_line_network,
    network_from_json,
    network_to_json,
    reference_delay_phase,
    s_max_abs_diff,
)

# ── 合成实验常量 ───────────────────────────────────────────────────────────
_F = np.linspace(2.0e9, 3.0e9, 21)
_ER_EFF = 2.88          # 微带闭式量级（2.5GHz 附近），非"恰好通过"调参
_ALPHA = 2.0            # Np/m
_DL = 0.01              # 短标准件：β·Δl < π，无分支歧义
_DL_BRANCH = 0.08       # 长标准件：β·Δl > π，需 beta_guess 选分支

_CASCADE_TOL = 1e-12    # 实测 ≤1.4e-16
_OPEN_SHORT_TOL = 1e-12  # 实测 ≤4.2e-16
_GAMMA_TOL = 1e-9       # 实测 ≤2.8e-14

_VIA_BETA = REPO / "runs" / "via_smoke" / "pt3" / "port_beta.csv"
_VIA_FDTD = REPO / "runs" / "via_smoke" / "pt3" / "fdtd"
_TRIO_DELTA = 4.0e-4     # via pt3 探针三重奏实测间距 0.3985mm 量级
_TRIO_TOL = 1e-9         # 波动方程估计器对合成行波/驻波的解析恢复门


# ── 助手 ───────────────────────────────────────────────────────────────────
def _freq() -> skrf.Frequency:
    return skrf.Frequency.from_f(_F, unit="hz")


def _gamma() -> np.ndarray:
    return _ALPHA + 1j * 2.0 * np.pi * _F * np.sqrt(_ER_EFF) / C0


def _line(length: float, gamma=None, z0: float = 50.0) -> skrf.Network:
    return ideal_line_network(_freq(), length, _gamma() if gamma is None else gamma, z0=z0)


def _dut(seed: int = 7, z0: float = 50.0) -> skrf.Network:
    """确定性随机无源网络（固定种子，无网络依赖）。"""
    rng = np.random.default_rng(seed)
    n = _F.size
    s = (rng.standard_normal((n, 2, 2)) + 1j * rng.standard_normal((n, 2, 2))) * 0.15
    s[:, 1, 0] = s[:, 0, 1]
    s[:, 0, 0] = 0.2 + 0.1j
    s[:, 1, 1] = 0.1 - 0.05j
    return skrf.Network(frequency=_freq(), s=s, z0=z0)


def _via_beta() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not _VIA_BETA.exists():
        pytest.skip(f"via β 真实归档缺失：{_VIA_BETA}")
    with _VIA_BETA.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    b1 = np.array([float(r["beta1_rad_per_m"]) for r in rows])
    b2 = np.array([float(r["beta2_rad_per_m"]) for r in rows])
    return freq, b1, b2


# ── 合成：理想线标准件 ─────────────────────────────────────────────────────
def test_ideal_line_is_matched_and_reciprocal():
    line = _line(_DL)
    assert np.allclose(line.s[:, 0, 0], 0.0)
    assert np.allclose(line.s[:, 1, 1], 0.0)
    assert np.allclose(line.s[:, 0, 1], line.s[:, 1, 0])
    assert np.allclose(line.s[:, 1, 0], np.exp(-_gamma() * _DL))


# ── 合成：误差网络恢复 ─────────────────────────────────────────────────────
def test_deembed_reference_plane_output_side_recovers_dut():
    dut = _dut()
    line = _line(0.02)
    recovered = deembed_reference_plane(dut ** line, line, side="output")
    assert s_max_abs_diff(recovered, dut) < _CASCADE_TOL


def test_deembed_reference_plane_input_side_recovers_dut():
    dut = _dut()
    line = _line(0.02)
    recovered = deembed_reference_plane(line ** dut, line, side="input")
    assert s_max_abs_diff(recovered, dut) < _CASCADE_TOL


def test_deembed_thru_recovers_dut():
    dut = _dut()
    thru = _line(_DL)
    recovered = deembed_thru(dut ** thru, thru)
    assert s_max_abs_diff(recovered, dut) < _CASCADE_TOL


def test_identity_no_error_is_unchanged():
    dut = _dut()
    unchanged = deembed_reference_plane(dut, _line(0.0), side="output")
    assert s_max_abs_diff(unchanged, dut) == 0.0


def test_open_short_recovers_known_dut():
    dut = _dut()
    n = _F.size
    z_series = np.zeros((n, 2, 2), dtype=complex)
    z_series[:, 0, 0] = 3.0 + 2.0j
    z_series[:, 1, 1] = 4.0 - 1.0j
    y_shunt = np.zeros((n, 2, 2), dtype=complex)
    y_shunt[:, 0, 0] = 0.002 + 0.001j
    y_shunt[:, 1, 1] = 0.0015 - 0.0005j
    z_dut = dut.z
    y_meas = y_shunt + np.linalg.inv(z_series + z_dut)
    measured = skrf.Network(frequency=_freq(), y=y_meas, z0=50.0)
    open_std = skrf.Network(frequency=_freq(), y=y_shunt, z0=50.0)
    short_std = skrf.Network(frequency=_freq(), z=z_series, z0=50.0)
    expected = skrf.Network(frequency=_freq(), z=z_dut, z0=50.0)
    recovered = deembed_open_short(measured, open_std, short_std)
    assert s_max_abs_diff(recovered, expected) < _OPEN_SHORT_TOL


# ── 合成：thru/line 差分 ───────────────────────────────────────────────────
def test_thru_line_gamma_matches_closed_form():
    gamma = extract_line_gamma(_line(0.0), _line(_DL), _DL)
    assert np.max(np.abs(gamma - _gamma())) < _GAMMA_TOL


def test_thru_line_gamma_branch_resolution_with_guess():
    line = _line(_DL_BRANCH)
    # β·Δl > π：无 guess 时落错分支（偏差 ~分支宽 2π/Δl ≈ 78.5）
    no_guess = extract_line_gamma(_line(0.0), line, _DL_BRANCH)
    assert np.max(np.abs(no_guess - _gamma())) > 1.0
    with_guess = extract_line_gamma(
        _line(0.0), line, _DL_BRANCH, beta_guess=float(_gamma()[0].imag),
    )
    assert np.max(np.abs(with_guess - _gamma())) < _GAMMA_TOL


def test_deembed_thru_line_recovers_dut():
    dut = _dut()
    thru = _line(0.0)
    line = _line(_DL)
    recovered = deembed_thru_line(dut ** line, thru, line, length_m=_DL)
    assert s_max_abs_diff(recovered, dut) < _CASCADE_TOL


# ── 探针尺度（#205）────────────────────────────────────────────────────────
def test_estimate_port_scale_recovers_constant():
    beta1 = np.linspace(70.0, 90.0, _F.size)
    beta2 = 1.0491 * beta1
    est = estimate_port_scale(beta1, beta2)
    assert est.scale == pytest.approx(1.0491, rel=0, abs=1e-12)
    assert est.n_points == _F.size
    assert est.is_band_flat()
    assert est.to_dict()["reference"] == "beta_ref"


def test_estimate_port_scale_flags_dispersive_ratio():
    beta1 = np.linspace(70.0, 90.0, _F.size)
    beta2 = beta1 * (1.02 + 0.06 * np.linspace(0.0, 1.0, _F.size))
    est = estimate_port_scale(beta1, beta2)
    assert not est.is_band_flat(tol=0.005)


# ── 确定性 / JSON 进出 ─────────────────────────────────────────────────────
def test_deembed_is_deterministic_byte_identical():
    dut = _dut()
    line = _line(0.02)
    first = deembed_reference_plane(dut ** line, line, side="output")
    second = deembed_reference_plane(dut ** line, line, side="output")
    j1 = json.dumps(network_to_json(first), sort_keys=True)
    j2 = json.dumps(network_to_json(second), sort_keys=True)
    assert j1 == j2
    assert s_max_abs_diff(first, second) == 0.0


def test_network_json_roundtrip():
    dut = _dut()
    back = network_from_json(network_to_json(dut))
    assert s_max_abs_diff(back, dut) == 0.0


def test_eps_eff_beta_roundtrip():
    beta = np.linspace(70.0, 90.0, _F.size)
    eps = eps_eff_from_beta(beta, _F)
    assert np.max(np.abs(beta_from_eps_eff(eps, _F) - beta)) == 0.0


# ── 非法输入 / 维度不符 ────────────────────────────────────────────────────
def test_errors_on_non_2port():
    one_port = skrf.Network(
        frequency=_freq(),
        s=np.zeros((_F.size, 1, 1), dtype=complex),
        z0=50.0,
    )
    with pytest.raises(ValueError, match="2 端口"):
        deembed_open_short(one_port, one_port, one_port)
    with pytest.raises(ValueError, match="2 端口"):
        extract_line_gamma(one_port, _line(_DL), _DL)


def test_errors_on_non_network_input():
    with pytest.raises(TypeError, match=r"skrf.Network"):
        deembed_reference_plane([[1.0]], _line(_DL), side="output")


def test_errors_on_frequency_grid_mismatch():
    other = skrf.Frequency.from_f(np.linspace(2.1e9, 3.1e9, _F.size), unit="hz")
    mismatched = ideal_line_network(other, _DL, _gamma())
    with pytest.raises(ValueError, match="频率网格"):
        deembed_reference_plane(_dut(), mismatched, side="output")
    with pytest.raises(ValueError, match="频率网格"):
        extract_line_gamma(_line(0.0), mismatched, _DL)


def test_errors_on_nonpositive_or_nonfinite_length():
    for bad in (0.0, -0.01, float("nan")):
        with pytest.raises(ValueError, match="length_m"):
            extract_line_gamma(_line(0.0), _line(_DL), bad)
    with pytest.raises(ValueError, match="side"):
        deembed_reference_plane(_dut(), _line(_DL), side="middle")


def test_errors_on_bad_beta_inputs():
    beta = np.linspace(70.0, 90.0, _F.size)
    with pytest.raises(ValueError, match="形状不一致"):
        estimate_port_scale(beta, beta[:-1])
    with pytest.raises(ValueError, match="正值"):
        estimate_port_scale(beta, -beta)
    with pytest.raises(ValueError, match="NaN/Inf"):
        estimate_port_scale(beta, np.full_like(beta, np.nan))
    with pytest.raises(ValueError, match="scale"):
        deembed_port_scale(beta, 0.0)
    with pytest.raises(ValueError, match=r"shape|形状"):
        eps_eff_from_beta(beta, _F[:-1])


def test_errors_on_bad_json():
    with pytest.raises(ValueError, match="缺字段"):
        network_from_json({"n_ports": 2})
    good = network_to_json(_dut())
    good["s_real"] = good["s_real"][:-1]
    with pytest.raises(ValueError, match="S 形状"):
        network_from_json(good)


# ── via β2 真实归档验收（§10.20 ②）────────────────────────────────────────
def test_via_archive_scale_reproduces_documented_constant():
    """归档自算的乘性尺度复现 #205 定版常数 1.0491±0.0011（独立来源对拍）。"""
    _, b1, b2 = _via_beta()
    est = estimate_port_scale(b1, b2)
    assert abs(est.scale - DOCUMENTED_VIA_SCALE) <= DOCUMENTED_VIA_SCALE_HALF_WIDTH
    assert est.n_points == b1.size
    # 带内恒定（#205 口径：1.0491±0.0011）
    assert est.std <= 0.0012
    assert (est.maximum - est.minimum) / est.scale < 0.005


def test_via_archive_eps2_consistent_le_1pct_with_external_constant():
    """用 **外部定版常数 1.0491** 去嵌 → εeff2 与 εeff1 自洽 ≤1%（非自证）。"""
    freq, b1, b2 = _via_beta()
    raw_dev = abs(eps_eff_from_beta(b2, freq).mean() - eps_eff_from_beta(b1, freq).mean()) \
        / eps_eff_from_beta(b1, freq).mean()
    assert raw_dev > 0.09  # 原始偏差 ~10.06%，去嵌必须真的改变数值
    corrected = deembed_port_scale(b2, DOCUMENTED_VIA_SCALE)
    eps1 = eps_eff_from_beta(b1, freq)
    eps2 = eps_eff_from_beta(corrected, freq)
    assert abs(eps2.mean() - eps1.mean()) / eps1.mean() <= 0.01


def test_via_archive_analyze_report_fields():
    freq, b1, b2 = _via_beta()
    report = analyze_via_port_scale(b1, b2, freq)
    assert report["consistent"] is True
    assert report["band_flat"] is True
    assert report["reproduces_documented"] is True
    assert report["deembedded_rel_deviation"] <= 0.01
    assert report["raw_rel_deviation"] > 0.09
    assert report["n_points"] == freq.size
    json.dumps(report)  # 必须可 JSON 序列化


# ── 三点波动方程估计器（2026-09-13 收口：驻波免疫独立 β 通道）──────────────
def _make_trio(
    beta: np.ndarray, delta: float, refl: float = 0.0, phase: float = 0.0,
    scale: complex = 1.0 + 0.0j,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ua, ub, uc)：U(z)=a·e^(−jβz)+b·e^(+jβz) 在 z=0,δ,2δ 的采样。"""
    z = np.array([0.0, delta, 2.0 * delta])
    fwd = np.exp(-1j * np.outer(z, beta))
    back = refl * np.exp(1j * phase) * np.exp(1j * np.outer(z, beta))
    u = scale * (fwd + back)
    return (u[0], u[1], u[2])


def test_voltage_trio_recovers_traveling_wave_beta_analytic():
    beta = np.linspace(70.0, 95.0, _F.size)
    trio = _make_trio(beta, _TRIO_DELTA)
    est = beta_from_voltage_trio(*trio, _TRIO_DELTA)
    expected = 2.0 * np.sin(beta * _TRIO_DELTA / 2.0) / _TRIO_DELTA  # β·sinc(βδ/2)
    assert np.max(np.abs(est - expected)) < _TRIO_TOL


def test_voltage_trio_is_standing_wave_immune():
    """β²=−U″/U 是二点驻波比下的精确恒等式——任意 |b/a|、任意相位都不动。"""
    beta = np.linspace(70.0, 95.0, _F.size)
    baseline = beta_from_voltage_trio(*_make_trio(beta, _TRIO_DELTA), _TRIO_DELTA)
    for refl, phase in ((0.3, 0.0), (0.6, np.pi / 3), (0.45, np.pi)):
        est = beta_from_voltage_trio(
            *_make_trio(beta, _TRIO_DELTA, refl=refl, phase=phase), _TRIO_DELTA,
        )
        assert np.max(np.abs(est - baseline)) < _TRIO_TOL


def test_voltage_trio_probe_normalization_invariant():
    """探针积分的任意复归一化在 −U″/U 中相消（探针尺度无关）。"""
    beta = np.linspace(70.0, 95.0, _F.size)
    baseline = beta_from_voltage_trio(*_make_trio(beta, _TRIO_DELTA), _TRIO_DELTA)
    for scale in ((2.0 + 1.0j), 1e-6, -3.0 - 0.5j):
        est = beta_from_voltage_trio(
            *_make_trio(beta, _TRIO_DELTA, scale=scale), _TRIO_DELTA,
        )
        assert np.max(np.abs(est - baseline)) < _TRIO_TOL


def test_voltage_trio_point_order_is_irrelevant():
    """二阶差分对称：A/C 互换（传播方向翻转）不改变估计。"""
    beta = np.linspace(70.0, 95.0, _F.size)
    ua, ub, uc = _make_trio(beta, _TRIO_DELTA, refl=0.2, phase=0.7)
    fwd = beta_from_voltage_trio(ua, ub, uc, _TRIO_DELTA)
    rev = beta_from_voltage_trio(uc, ub, ua, _TRIO_DELTA)
    assert np.max(np.abs(fwd - rev)) < _TRIO_TOL


def test_voltage_trio_errors_on_bad_input():
    beta = np.linspace(70.0, 95.0, _F.size)
    ua, ub, uc = _make_trio(beta, _TRIO_DELTA)
    with pytest.raises(ValueError, match="同形"):
        beta_from_voltage_trio(ua[:-1], ub, uc, _TRIO_DELTA)
    with pytest.raises(ValueError, match="非空"):
        beta_from_voltage_trio(np.array([], dtype=complex), ub[:0], uc[:0], _TRIO_DELTA)
    for bad in (0.0, -1e-3, float("nan")):
        with pytest.raises(ValueError, match="spacing_m"):
            beta_from_voltage_trio(ua, ub, uc, bad)
    ub_zero = ub.copy()
    ub_zero[3] = 0.0
    with pytest.raises(ValueError, match="ub 含 0"):
        beta_from_voltage_trio(ua, ub_zero, uc, _TRIO_DELTA)
    with pytest.raises(ValueError, match="NaN/Inf"):
        beta_from_voltage_trio(ua * np.nan, ub, uc, _TRIO_DELTA)
    # 污染数据：给 uc 注入纯虚偏置 → 曲率比虚部/实比超容限，宁可报错不给数
    # （Δcurv = −ε/(δ²·ub)，ε=1e-3、δ²=1.6e-7、|ub|~O(1) → 虚部超实部量级）
    with pytest.raises(ValueError, match="超容限"):
        beta_from_voltage_trio(ua, ub, uc + 1e-3j, _TRIO_DELTA)


# ── via β2 镜像前提裁决（收口口径：真实模态差异 vs 探针伪象）────────────────
def test_mirror_verdict_synthetic_chain_artifact_case():
    """镜像成立（β2_true=β1_true）而链路比值偏离 → verdict=chain_artifact。"""
    beta1 = np.linspace(70.0, 95.0, _F.size)
    trio1 = _make_trio(beta1, _TRIO_DELTA, refl=0.2, phase=0.5)
    trio2 = _make_trio(beta1, _TRIO_DELTA, refl=0.2, phase=-0.9)
    chain1 = beta1 * 1.0005          # 链路各自的小残差
    chain2 = chain1 * 1.06           # 链路读出 6% 比值——前提成立时=伪象
    rep = derive_via_mirror_verdict(
        _F, chain1, chain2, trio1, trio2, _TRIO_DELTA, _TRIO_DELTA,
    )
    assert rep["mirror_premise_holds"] is True
    assert rep["deembedding_valid"] is True
    assert rep["verdict"] == "chain_artifact"
    assert rep["trio_ratio_mean"] == pytest.approx(1.0, abs=1e-9)
    assert rep["chain_ratio_mean"] == pytest.approx(1.06, rel=1e-12)
    assert rep["artifact_factor"] == pytest.approx(1.06, rel=1e-9)


def test_mirror_verdict_synthetic_real_modal_difference_case():
    """镜像不成立（β2_true=1.0467·β1_true）而链路读 1.0491 → 真实模态差异。"""
    beta1 = np.linspace(70.0, 95.0, _F.size)
    trio1 = _make_trio(beta1, _TRIO_DELTA, refl=0.15, phase=0.3)
    trio2 = _make_trio(1.0467 * beta1, _TRIO_DELTA, refl=0.15, phase=-1.1)
    chain1 = beta1 * 1.0005
    chain2 = chain1 * 1.0491
    rep = derive_via_mirror_verdict(
        _F, chain1, chain2, trio1, trio2, _TRIO_DELTA, _TRIO_DELTA,
    )
    assert rep["verdict"] == "real_modal_difference"
    assert rep["mirror_premise_holds"] is False
    assert rep["deembedding_valid"] is False
    # 二阶 sinc 偏差不随同间距相消（sin(β2δ/2)/sin(β1δ/2)≠1，量级 ~4e-6）：
    # 门放到 1e-5，解析恒等式由 test_voltage_trio_recovers_traveling_wave_beta_analytic 把守
    assert rep["trio_ratio_mean"] == pytest.approx(1.0467, abs=1e-5)
    assert rep["chain_reproduces_documented"] is True
    assert rep["artifact_factor"] == pytest.approx(1.0491 / 1.0467, rel=1e-4)
    assert rep["eps_eff_trio_ratio"] == pytest.approx(1.0467**2, rel=1e-4)


def test_mirror_verdict_consistent_mirror_case_and_json():
    """前提成立且链路比值≈1 → consistent_mirror；报告可 JSON 序列化。"""
    beta1 = np.linspace(70.0, 95.0, _F.size)
    trio1 = _make_trio(beta1, _TRIO_DELTA)
    trio2 = _make_trio(beta1, _TRIO_DELTA)
    rep = derive_via_mirror_verdict(
        _F, beta1, beta1, trio1, trio2, _TRIO_DELTA, _TRIO_DELTA,
    )
    assert rep["verdict"] == "consistent_mirror"
    json.dumps(rep)
    for key in (
        "beta1_trio_mean", "beta2_trio_mean", "trio_ratio_mean", "trio_ratio_std",
        "trio_ratio_flatness", "chain_ratio_mean", "artifact_factor",
        "eps_eff1_trio_mean", "eps_eff2_trio_mean", "eps_eff_trio_ratio",
        "mirror_premise_holds", "deembedding_valid", "chain_reproduces_documented",
        "verdict", "n_points",
    ):
        assert key in rep


def test_mirror_verdict_errors_on_shape_mismatch():
    beta1 = np.linspace(70.0, 95.0, _F.size)
    trio1 = _make_trio(beta1, _TRIO_DELTA)
    trio2 = _make_trio(beta1, _TRIO_DELTA)
    with pytest.raises(ValueError, match="同长非空"):
        derive_via_mirror_verdict(
            _F, beta1[:-1], beta1[:-1], trio1, trio2, _TRIO_DELTA, _TRIO_DELTA,
        )
    with pytest.raises(ValueError, match="三元组"):
        derive_via_mirror_verdict(
            _F, beta1, beta1, trio1, trio2[:2], _TRIO_DELTA, _TRIO_DELTA,
        )
    with pytest.raises(ValueError, match="形状必须与 freq 一致"):
        derive_via_mirror_verdict(
            _F, beta1, beta1, trio1, (trio2[0], trio2[1], trio2[2][:-1]),
            _TRIO_DELTA, _TRIO_DELTA,
        )


# ── via β2 真实归档收口（原始探针场 → 镜像前提否证）────────────────────────
def _read_td(path: Path) -> tuple[np.ndarray, np.ndarray]:
    t: list[float] = []
    v: list[float] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("%") or line.startswith("t/"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            t.append(float(parts[0]))
            v.append(float(parts[1]))
    return np.array(t), np.array(v)


def _probe_y(path: Path) -> float:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "start-coordinates" in line:
                seg = line.split("(")[1].split(")")[0]
                return float(seg.split(",")[1])
    raise ValueError(f"{path.name} 无 start-coordinates")


def _dft_band(t: np.ndarray, v: np.ndarray, freq: np.ndarray) -> np.ndarray:
    dt = t[1] - t[0]
    return np.array([np.sum(v * np.exp(-2j * np.pi * f * t)) * dt for f in freq])


def _via_trios() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
                          tuple, tuple, float, float]:
    """归档原始电压探针三重奏（缺失则 skip——runs/ 不入 git）。"""
    for p in (1, 2):
        for n in "ABC":
            if not (_VIA_FDTD / f"port_ut_{p}{n}").exists():
                pytest.skip(f"via 原始探针归档缺失：port_ut_{p}{n}")
    freq, b1, b2 = _via_beta()
    trios = {}
    spacings = {}
    for p in (1, 2):
        ys = [_probe_y(_VIA_FDTD / f"port_ut_{p}{n}") for n in "ABC"]
        delta = abs(ys[1] - ys[0])
        assert abs(abs(ys[2] - ys[1]) - delta) < 1e-12  # 等距前提（实测 0.3985mm）
        data = [_read_td(_VIA_FDTD / f"port_ut_{p}{n}") for n in "ABC"]
        trios[p] = tuple(_dft_band(t, v, freq) for t, v in data)
        spacings[p] = delta
    return freq, b1, b2, freq, trios[1], trios[2], spacings[1], spacings[2]


def test_via_archive_trio_derivation_refutes_mirror_premise():
    """收口主测：原始场数据的独立 β 通道否证镜像前提，1.0491=真实模态比×链路残差。

    关键误差数字（runs/via_smoke/pt3 实测，2026-09-13）：
    - trio β2/β1 = 1.04662±0.00033（带内平坦 0.031%）→ 镜像前提（≤1%）不成立；
    - 链路（CalcPort）比值 1.04905 复现 #205 定版 1.0491±0.0011；
    - 分解：1.04905 = 1.04662(真实模态) × 1.00232(链路残差因子)。
    """
    freq, b1, b2, _, trio1, trio2, d1, d2 = _via_trios()
    sel = np.abs(freq - 2.5e9) <= 200e6  # GaussExcite 1σ 带内（DFT 边缘信噪比）
    rep = derive_via_mirror_verdict(
        freq[sel], b1[sel], b2[sel],
        tuple(x[sel] for x in trio1), tuple(x[sel] for x in trio2), d1, d2,
    )
    assert rep["verdict"] == "real_modal_difference"
    assert rep["mirror_premise_holds"] is False
    assert 1.0455 <= rep["trio_ratio_mean"] <= 1.0480
    assert rep["trio_ratio_flatness"] <= 0.001
    assert rep["chain_reproduces_documented"] is True
    assert 1.001 <= rep["artifact_factor"] <= 1.004
    assert 1.09 <= rep["eps_eff_trio_ratio"] <= 1.10
    json.dumps(rep)


# ── 参考面时延相位去嵌原语（C13 followUp ③，2026-09-15）──────────────────────
# 口径：deembed_reference_delay 是 deembed_reference_plane（net ** line.inv）
# 的数组版——匹配线级联代数 S11_meas = S11·e^{−j2πf·2τin}、
# S21_meas = S21·e^{−j2πf·(τin+τout)}，逆变换逐点相位推进。诚实边界：只能去
# 纯时延型相位；λ/4 commensurate 段的相位在 Ω 域非有理（Richards），任何 τ
# 都无法完全吸收（收敛口径见 test_c13_refplane_deembed.py）。


def test_reference_delay_phase_matches_definition():
    """e^{+j2πfτ} 定义式逐点（标量 τ 与 γ(f) 色散 τ 数组两口径）。"""
    ph = reference_delay_phase(_F, 1e-9)
    assert np.allclose(ph, np.exp(1j * 2.0 * np.pi * _F * 1e-9))
    tau_arr = np.linspace(0.5e-9, 1.5e-9, _F.size)
    assert np.allclose(reference_delay_phase(_F, tau_arr),
                       np.exp(1j * 2.0 * np.pi * _F * tau_arr))
    with pytest.raises(ValueError):
        reference_delay_phase(_F, np.linspace(0.0, 1.0, _F.size + 1))
    with pytest.raises(ValueError):
        reference_delay_phase(np.array([1e9, np.nan]), 1e-9)


def test_deembed_reference_delay_matches_skrf_cascade():
    """与 skrf 级联互证（非自证）：DUT 两端各级联 τ_in/τ_out 真空匹配线
    （γ=j2πf/c，理想线 S11=0），数组原语逆变换恢复 DUT 复 S 逐点
    ≤1e−12（级联类实测地板 ≤1.4e−16）。"""
    tau_in, tau_out = 0.3e-9, 0.7e-9
    gamma_vac = 1j * 2.0 * np.pi * _F / C0
    line_in = ideal_line_network(_freq(), tau_in * C0, gamma_vac)   # l=τ·c
    line_out = ideal_line_network(_freq(), tau_out * C0, gamma_vac)
    dut = _dut()
    net = line_in ** dut ** line_out
    s11_rec, s21_rec = deembed_reference_delay(
        np.asarray(net.f, dtype=float),
        net.s[:, 0, 0], net.s[:, 1, 0], tau_in, tau_out)
    assert np.max(np.abs(s11_rec - dut.s[:, 0, 0])) < _CASCADE_TOL
    assert np.max(np.abs(s21_rec - dut.s[:, 1, 0])) < _CASCADE_TOL


def test_deembed_reference_delay_dispersive_tau_roundtrip():
    """τ 逐点数组（γ(f) 色散口径：τ(f)=β(f)l/(2πf) 由调用方换算）：已知
    S 施加色散参考面相位 → 原语精确逆 ≤1e−12；形状/NaN 显式报错。"""
    tau_in = np.linspace(0.2e-9, 0.4e-9, _F.size)
    tau_out = np.linspace(0.6e-9, 1.1e-9, _F.size)
    s11_0 = 0.3 * np.exp(1j * np.linspace(0.0, 2.0, _F.size))
    s21_0 = 0.8 * np.exp(1j * np.linspace(1.0, 3.0, _F.size))
    s11_m = s11_0 * np.exp(-1j * 2.0 * np.pi * _F * 2.0 * tau_in)
    s21_m = s21_0 * np.exp(-1j * 2.0 * np.pi * _F * (tau_in + tau_out))
    s11_rec, s21_rec = deembed_reference_delay(_F, s11_m, s21_m,
                                               tau_in, tau_out)
    assert np.max(np.abs(s11_rec - s11_0)) < 1e-12
    assert np.max(np.abs(s21_rec - s21_0)) < 1e-12
    with pytest.raises(ValueError):
        deembed_reference_delay(_F, s11_m[:-1], s21_m, tau_in, tau_out)
    with pytest.raises(ValueError):
        deembed_reference_delay(_F, s11_m, s21_m,
                                np.full(_F.size, np.nan), tau_out)
