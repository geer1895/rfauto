"""架构批 W4-A 席锚树：modulation_ber 三键 + radar_eq 三键。

数值断言口径（#118 不自证）：
- 调制族：①Q 函数 vs scipy.stats.norm.sf（独立实现逐位互证）+ 任务书
  量级锚 Q(3.026)≈1.24e-3；②BPSK@10dB=3.872e-6 文献通用锚（≈3.87e-6）；
  ③QPSK≡BPSK 同比特能量物理恒等（全扫描逐位相等）；④反解文献表锚
  BPSK 1e-5→9.588dB / 1e-3→6.79dB、16QAM 1e-6→14.40dB、64QAM
  1e-6→18.78dB；⑤16QAM Gray 蒙特卡洛独立裁判（numpy 仿真 vs 闭式
  和式，±4% 带，4e6 符号）；⑥编码键恒等结构钉（rate=1/2, gain=5 ⇔
  未编码 +1.9897dB）。
- 雷达族：①Albersheim（原式 √(N+0.44)）vs 线性检波 Marcum-Q1 精确反解
  （scipy ncx2 独立实现 + brentq 求根）在 Pfa=1e-6/Pd=0.9 点 Δ=0.069dB
  ≤0.1dB（任务书锚点）；相干 Q 反解参考 12.6032dB 并列；②雷达方程量纲
  自洽物理恒等：R 加倍 → Pr 精确 ÷16（−12.0412dB）、Pt ×16 → Pr 不变、
  SI/dB 双口径同参一致（<1e-9 相对）；③噪声锚 kT0B@290K/1MHz=
  −113.98dBm（教科书 −114dBm）；④CA-CFAR：Pfa 闭式回代逐位自洽 +
  蒙特卡洛独立裁判（经验 Pfa 与 SW1-Pd 落 3σ 带）。
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

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _q_ref(x: float) -> float:
    """Q 函数独立参考实现（scipy 正态生存函数，与本族 erfc 形态互证）。"""
    from scipy.stats import norm

    return float(norm.sf(x))


# ─── modulation_ber_curve：Q 单源 / 文献锚 / QPSK 恒等 / 曲线契约 ───────────


def test_qfunc_single_source_matches_scipy_and_task_anchor():
    """Q(3.026)≈1.24e-3（任务书量级锚）+ 与 scipy norm.sf 逐位互证。"""
    from rfauto.core.calc_families.modulation_ber import _qfunc

    assert _qfunc(3.026) == pytest.approx(1.2391e-3, abs=5e-6)
    assert _qfunc(3.026) == pytest.approx(_q_ref(3.026), rel=1e-12)
    assert _qfunc(0.0) == pytest.approx(0.5, abs=1e-15)


def test_bpsk_10db_literature_anchor():
    """BPSK @10dB → 3.872e-6（文献通用值 ≈3.87e-6，任务书锚）。"""
    r = _run("modulation_ber_curve", {"ebn0_db": 10.0, "scheme": "bpsk"})
    assert r["ber"][0] == pytest.approx(3.872e-6, rel=1e-3)
    assert r["ber"][0] == pytest.approx(_q_ref(math.sqrt(20.0)), rel=1e-12)


def test_qpsk_equals_bpsk_physical_identity():
    """QPSK≡BPSK 同比特能量物理恒等：全 γ 扫描逐位相等。"""
    grid = [-5.0, 0.0, 3.0, 7.0, 10.0, 15.0, 20.0]
    rb = _run("modulation_ber_curve", {"ebn0_db": grid, "scheme": "bpsk"})
    rq = _run("modulation_ber_curve", {"ebn0_db": grid, "scheme": "qpsk"})
    assert rb["ber"] == rq["ber"]  # 逐位（同代码路径，恒等不设容差）
    assert rq["es_n0_db"] == pytest.approx(
        [g + 10.0 * math.log10(2.0) for g in grid], abs=1e-6)


def test_qam_curve_literature_windows_and_monotone():
    """16/64QAM 曲线：文献窗锚（16QAM@10dB≈1.75e-3、64QAM@10dB≈2.65e-2）
    + BER 随 γ 单调降 + Es/N0=k·Eb/N0 换算。"""
    r16 = _run("modulation_ber_curve",
               {"ebn0_db": [6.0, 10.0, 14.0, 20.0], "scheme": "16qam"})
    r64 = _run("modulation_ber_curve",
               {"ebn0_db": [10.0, 15.0, 20.0, 24.0], "scheme": "64qam"})
    assert 1.6e-3 <= r16["ber"][1] <= 1.9e-3   # 文献 16QAM@10dB 窗
    assert 2.4e-2 <= r64["ber"][0] <= 2.9e-2   # 文献 64QAM@10dB 窗
    for r in (r16, r64):
        bers = r["ber"]
        assert all(bers[i] > bers[i + 1] for i in range(len(bers) - 1))
    assert r16["k_bits_per_symbol"] == 4 and r64["k_bits_per_symbol"] == 6


def test_curve_scalar_list_contract_and_guards():
    """标量/列表双形态 + 越界显式拒绝（空表/非有限/未知制式）。"""
    scalar = _run("modulation_ber_curve",
                  {"ebn0_db": 10.0, "scheme": "64qam"})
    assert scalar["n_points"] == 1 and len(scalar["ber"]) == 1
    big = _run("modulation_ber_curve",
               {"ebn0_db": 400.0, "scheme": "bpsk"})
    assert big["ber"] == [0.0] and big["ber_log10"] == [None]  # 深尾下溢如实
    for bad in ({"ebn0_db": [], "scheme": "bpsk"},
                {"ebn0_db": [1.0, float("nan")], "scheme": "bpsk"},
                {"ebn0_db": 10.0, "scheme": "8vsc"}):
        out = run_calculator("modulation_ber_curve", bad)
        assert out["ok"] is False, f"越界输入未拒绝: {bad!r}"


# ─── required_ebn0：文献表锚 / 前向回代 / 单调 / 域守卫 ─────────────────────


@pytest.mark.parametrize("scheme,target,expect_db,tol", [
    ("bpsk", 1e-5, 9.5879, 0.01),   # 文献表 9.588 dB
    ("bpsk", 1e-3, 6.7895, 0.01),   # 文献表 6.79 dB
    ("16qam", 1e-6, 14.4017, 0.05),  # 文献表 ~14.4 dB
    ("64qam", 1e-6, 18.7772, 0.05),  # 文献表 ~18.8 dB
])
def test_required_ebn0_literature_table_anchors(scheme, target, expect_db,
                                                tol):
    r = _run("required_ebn0", {"target_ber": target, "scheme": scheme})
    assert r["required_ebn0_db"] == pytest.approx(expect_db, abs=tol)


def test_required_ebn0_roundtrip_and_monotonicity():
    """前向回代自检（曲线键在解点复算=target）+ 目标越严所需 Eb/N0 越大。"""
    for scheme, targets in (("bpsk", [1e-9, 1e-6, 1e-3]),
                            ("64qam", [1e-6, 1e-4])):
        dbs = []
        for t in targets:
            r = _run("required_ebn0", {"target_ber": t, "scheme": scheme})
            curve = _run("modulation_ber_curve",
                         {"ebn0_db": r["required_ebn0_db"],
                          "scheme": scheme})
            # 解值输出按 1e-6 dB 圆整 → BER 相对误差 ~1e-6 量级（斜率换算）
            assert curve["ber"][0] == pytest.approx(t, rel=1e-5)
            dbs.append(r["required_ebn0_db"])
        assert dbs == sorted(dbs, reverse=True)  # 目标 BER 越小 → 所需 dB 越大


@pytest.mark.parametrize("bad", [0.0, -1e-6, 0.5, 1.0, 1e-20, float("nan")])
def test_required_ebn0_rejects_out_of_domain(bad):
    out = run_calculator("required_ebn0",
                         {"target_ber": bad, "scheme": "bpsk"})
    assert out["ok"] is False, f"target_ber={bad!r} 未拒绝"


def test_required_ebn0_high_ber_flagged_low_confidence():
    """目标 0.4 可解但如实标 low_confidence（闭式高 BER 端失精确带）。"""
    r = _run("required_ebn0", {"target_ber": 0.4, "scheme": "bpsk"})
    assert r["low_confidence"] is True
    assert _run("required_ebn0",
                {"target_ber": 1e-6, "scheme": "bpsk"})[
                    "low_confidence"] is False


# ─── coded_ber_estimate：恒等结构钉 / 域守卫 ────────────────────────────────


def test_coded_rate_expansion_identity():
    """rate=1/2 且 gain=0 ⇔ 未编码 −3.0103dB；加 gain=5 ⇔ +1.9897dB。

    有效 Eb/N0 按实现同式同序构造（(g + 10·lg(r)) + gain），保证 BER
    逐位相等（恒等钉不设容差）。
    """
    eff1 = 10.0 + 10.0 * math.log10(0.5)          # rate=1/2、无增益
    eff2 = eff1 + 5.0                             # 再加 5dB 净编码增益
    unc = _run("modulation_ber_curve",
               {"ebn0_db": [eff1, eff2], "scheme": "16qam"})
    r_half = _run("coded_ber_estimate",
                  {"scheme": "16qam", "ebn0_db": 10.0, "code_rate": 0.5})
    r_coded = _run("coded_ber_estimate",
                   {"scheme": "16qam", "ebn0_db": 10.0, "code_rate": 0.5,
                    "coding_gain_db": 5.0})
    assert r_half["ebn0_effective_db"] == pytest.approx(eff1, abs=5e-7)
    assert r_half["ber"] == unc["ber"][0]
    assert r_coded["ebn0_effective_db"] == pytest.approx(eff2, abs=5e-7)
    assert r_coded["ber"] == unc["ber"][1]


def test_coded_identity_and_guards():
    """rate=1 无增益 → 与未编码逐位相等；域守卫显式拒绝。"""
    unc = _run("modulation_ber_curve", {"ebn0_db": 12.0, "scheme": "qpsk"})
    same = _run("coded_ber_estimate",
                {"scheme": "qpsk", "ebn0_db": 12.0})
    assert same["ber"] == unc["ber"][0]
    for bad in ({"scheme": "qpsk", "ebn0_db": 12.0, "code_rate": 0.0},
                {"scheme": "qpsk", "ebn0_db": 12.0, "code_rate": 1.5},
                {"scheme": "qpsk", "ebn0_db": 12.0,
                 "coding_gain_db": float("nan")},
                {"scheme": "nope", "ebn0_db": 12.0},
                {"scheme": "qpsk", "ebn0_db": float("inf")}):
        out = run_calculator("coded_ber_estimate", bad)
        assert out["ok"] is False, f"越界输入未拒绝: {bad!r}"


def test_16qam_monte_carlo_independent_referee():
    """16QAM Gray 蒙特卡洛独立裁判：numpy 仿真 BER vs 闭式和式 ±4%。

    仿真口径：I/Q 两维独立 4-PAM（电平 ±1/±3，Gray 标签 00/01/11/10），
    Es=10 → Eb=Es/4；ML 最近邻判决；seed 固定（确定性）。
    """
    from rfauto.core.calc_families.modulation_ber import _ber_qam

    rng = np.random.default_rng(20261011)
    n_sym = 4_000_000
    gamma_b = 10.0  # dB
    es = 10.0       # 两维 4-PAM 平均能量 (9+1+1+9)/4 ×2
    n0 = es / (4.0 * 10.0 ** (gamma_b / 10.0))
    sigma = math.sqrt(n0 / 2.0)  # 每维噪声标准差

    levels = np.array([-3.0, -1.0, 1.0, 3.0])
    gray = np.array([[0, 0], [0, 1], [1, 1], [1, 0]])  # Gray 标签
    err_bits = 0
    for _ in range(2):  # I/Q 两维独立
        idx = rng.integers(0, 4, n_sym)
        tx = levels[idx]
        rx = tx + rng.normal(0.0, sigma, n_sym)
        det = levels[np.argmin(np.abs(rx[:, None] - levels[None, :]),
                               axis=1)]
        hit = det != tx
        if hit.any():
            lb, ld = gray[idx[hit]], gray[np.searchsorted(levels, det[hit])]
            err_bits += int((lb != ld).sum())
    ber_mc = err_bits / (4.0 * n_sym)  # 总比特=4 bit/符号 × n_sym
    ber_cf = _ber_qam(16, 10.0 ** (gamma_b / 10.0))
    assert ber_mc == pytest.approx(ber_cf, rel=0.04)
    api = _run("modulation_ber_curve", {"ebn0_db": gamma_b,
                                        "scheme": "16qam"})
    assert api["ber"][0] == ber_cf


# ─── radar_range_equation：物理恒等 / 双口径一致 / 噪声锚 / 守卫 ────────────


_DB_NOMINAL = {"pt_dbm": 60.0, "antenna_gain_db": 30.0, "freq_ghz": 10.0,
               "rcs_dbsm": 5.0, "range_km": 50.0, "loss_db": 3.0,
               "bandwidth_hz": 1e6, "noise_fig_db": 3.0}


def test_radar_eq_range_doubling_identity():
    """R 加倍 → Pr 精确 ÷16（−12.0412dB，任务书物理恒等钉）+ Pt×16 不变。"""
    r1 = _run("radar_range_equation", _DB_NOMINAL)
    r2 = _run("radar_range_equation",
              {**_DB_NOMINAL, "range_km": 100.0})
    delta = r2["pr_dbm"] - r1["pr_dbm"]
    assert delta == pytest.approx(-40.0 * math.log10(2.0), abs=1e-9)
    r3 = _run("radar_range_equation",
              {**_DB_NOMINAL, "pt_dbm": 60.0 + 10.0 * math.log10(16.0)})
    assert r3["pr_w"] == pytest.approx(r1["pr_w"], rel=1e-12)
    # SI 路径同恒等
    si = {"pt_w": 1000.0, "antenna_gain": 1000.0, "wavelength_m": 0.03,
          "rcs_m2": 3.1622776601683795, "range_m": 50000.0}
    s1 = _run("radar_range_equation", si)
    s2 = _run("radar_range_equation", {**si, "range_m": 100000.0})
    assert s2["pr_w"] == pytest.approx(s1["pr_w"] / 16.0, rel=1e-12)
    assert 0.0 < s1["pr_w"] < 1000.0  # 物理量级自洽


def test_radar_eq_si_db_path_consistency():
    """同参 SI/dB 双口径 → pr_w 一致（<1e-9 相对；结构一致性钉）。"""
    lam = 0.03
    f_ghz = 299.792458 / (lam * 1e3)  # 由 λ 反推频率（C_MM_GHZ 口径）
    si = {"pt_w": 1000.0, "antenna_gain": 1000.0, "wavelength_m": lam,
          "rcs_m2": 10.0 ** 0.5, "range_m": 50000.0, "loss_factor": 2.0,
          "noise_fig": 2.0, "bandwidth_hz": 1e6}
    db = {"pt_dbm": 60.0, "antenna_gain_db": 30.0, "freq_ghz": f_ghz,
          "rcs_dbsm": 5.0, "range_km": 50.0,
          "loss_db": 10.0 * math.log10(2.0),
          "noise_fig_db": 10.0 * math.log10(2.0), "bandwidth_hz": 1e6}
    r_si = _run("radar_range_equation", si)
    r_db = _run("radar_range_equation", db)
    assert r_si["mode"] == "si_linear" and r_db["mode"] == "db_mixed"
    assert r_db["wavelength_m"] == pytest.approx(lam, rel=1e-12)
    assert r_db["pr_w"] == pytest.approx(r_si["pr_w"], rel=1e-9)
    assert r_db["snr_db"] == pytest.approx(r_si["snr_db"], abs=1e-6)


def test_radar_eq_noise_anchor_and_snr_identity():
    """kT0B@290K/1MHz/F=1 → −113.975dBm（教科书 −174dBm/Hz+60dB）+SNR 恒等。"""
    r = _run("radar_range_equation",
             {**_DB_NOMINAL, "noise_fig_db": 0.0})
    assert r["noise_power_dbm"] == pytest.approx(-113.9752, abs=1e-3)
    assert r["snr_db"] == pytest.approx(
        r["pr_dbm"] - r["noise_power_dbm"], abs=1e-6)
    # 无带宽 → 不出噪声/SNR（如实 None）
    r0 = _run("radar_range_equation",
              {k: v for k, v in _DB_NOMINAL.items() if k != "bandwidth_hz"})
    assert r0["snr_db"] is None and r0["noise_power_w"] is None


@pytest.mark.parametrize("params,match", [
    ({**_DB_NOMINAL, "pt_w": 1000.0}, "只能给其一"),
    ({k: v for k, v in _DB_NOMINAL.items() if k != "pt_dbm"}, "必须给其一"),
    ({**_DB_NOMINAL, "range_km": 0.0}, "range_km"),
    ({**_DB_NOMINAL, "range_km": -5.0}, "range_km"),
    ({**_DB_NOMINAL, "freq_ghz": 0.0}, "freq_ghz"),
    ({**_DB_NOMINAL, "loss_db": -3.0}, "loss_db"),
    ({**_DB_NOMINAL, "noise_fig_db": -1.0}, "noise_fig_db"),
    ({**{k: v for k, v in _DB_NOMINAL.items()
         if k not in ("loss_db", "noise_fig_db")}, "loss_factor": 2.0},
     "混入"),
    ({"pt_w": 1000.0, "antenna_gain": 1000.0, "wavelength_m": 0.03,
      "rcs_m2": 1.0, "range_m": 50000.0, "freq_ghz": 10.0}, "混入"),
    ({"pt_w": -1.0, "antenna_gain": 1000.0, "wavelength_m": 0.03,
      "rcs_m2": 1.0, "range_m": 50000.0}, "pt_w"),
])
def test_radar_eq_domain_guards_explicit(params, match):
    out = run_calculator("radar_range_equation", params)
    assert out["ok"] is False, f"越界输入未拒绝: {params!r} -> {out!r}"
    assert match in out["error"]


# ─── albersheim_detection_snr：Marcum 精确互证（任务书锚）/ 三向互算 ───────


def _marcum_exact_snr_db(pfa: float, pd: float) -> float:
    """线性检波精确反解（独立实现）：T=√(−2lnPfa)，Pd=Q1(√(2·SNR),T)。

    Marcum Q1 经非中心 χ² 映射 Q1(a,b)=ncx2.sf(b²; df=2, nc=a²)
    （mpath 数值积分另证，见模块 docstring），brentq 求根。
    """
    from scipy.optimize import brentq
    from scipy.stats import ncx2

    t = math.sqrt(-2.0 * math.log(pfa))
    a_req = brentq(lambda a: ncx2.sf(t * t, 2, a * a) - pd,
                   1e-6, 60.0, xtol=1e-13)
    return 10.0 * math.log10(a_req * a_req / 2.0)


def test_albersheim_vs_exact_q_inversion_task_anchor():
    """任务书锚点：Pfa=1e-6/Pd=0.9 → Albersheim vs 解析反解 ≤0.1dB。"""
    r = _run("albersheim_detection_snr", {"pfa": 1e-6, "pd": 0.9})
    exact = _marcum_exact_snr_db(1e-6, 0.9)
    assert r["snr_db"] == pytest.approx(13.1145, abs=1e-3)
    assert exact == pytest.approx(13.1835, abs=1e-3)
    assert abs(r["snr_db"] - exact) <= 0.1
    # 相干检测参考（Q 反解界）与包络损失并列如实
    assert r["snr_db_coherent_reference"] == pytest.approx(12.6032, abs=1e-3)
    assert r["envelope_loss_db"] == pytest.approx(
        r["snr_db_coherent_reference"] - r["snr_db"], abs=1e-6)
    assert r["in_fit_window"] is True and r["extrapolated"] is False
    assert r["direction"] == "pfa_pd_to_snr"


@pytest.mark.parametrize("pfa,pd", [(1e-6, 0.5), (1e-3, 0.9), (1e-4, 0.8),
                                    (1e-7, 0.6)])
def test_albersheim_accuracy_across_fit_window(pfa, pd):
    """全拟合窗内 |Albersheim−精确|≤0.1dB（原式 N+0.44 口径的实证带）。"""
    r = _run("albersheim_detection_snr", {"pfa": pfa, "pd": pd})
    assert abs(r["snr_db"] - _marcum_exact_snr_db(pfa, pd)) <= 0.1


def test_albersheim_three_directions_roundtrip():
    """三给二解一互算闭环：任一方向解出的第三量回填后前向复现。"""
    pfa0, pd0 = 1e-6, 0.9
    fwd = _run("albersheim_detection_snr", {"pfa": pfa0, "pd": pd0})
    inv_pd = _run("albersheim_detection_snr",
                  {"pfa": pfa0, "snr_db": fwd["snr_db"]})
    assert inv_pd["direction"] == "pfa_snr_to_pd"
    # 解值 SNR 输出按 1e-6 dB 圆整 → Pd 反解相对误差 ~1e-7 量级
    assert inv_pd["pd"] == pytest.approx(pd0, rel=1e-6)
    inv_pfa = _run("albersheim_detection_snr",
                   {"pd": pd0, "snr_db": fwd["snr_db"]})
    assert inv_pfa["direction"] == "pd_snr_to_pfa"
    assert inv_pfa["pfa"] == pytest.approx(pfa0, rel=1e-5)
    # N 脉冲积累降门限（N=10 显著低于 N=1；N=10 点 ≈4.99dB 经典曲线位）
    n10 = _run("albersheim_detection_snr",
               {"pfa": pfa0, "pd": pd0, "n_pulses": 10})
    assert n10["snr_db"] < fwd["snr_db"]
    assert n10["snr_db"] == pytest.approx(4.9904, abs=1e-3)


def test_albersheim_fit_window_flag_and_guards():
    """窗外如实标注 extrapolated + 越界/超定/欠定显式拒绝。"""
    out9 = _run("albersheim_detection_snr", {"pfa": 1e-9, "pd": 0.9})
    assert out9["extrapolated"] is True and out9["in_fit_window"] is False
    for bad, match in (
            ({"pfa": 1e-6, "pd": 0.9, "snr_db": 13.0}, "超定"),
            ({"pfa": 1e-6}, "给其二"),
            ({"pfa": 0.0, "pd": 0.9}, "pfa"),
            ({"pfa": 1.5, "pd": 0.9}, "pfa"),
            ({"pfa": 1e-6, "pd": 1.0}, "pd"),
            ({"pfa": 1e-6, "pd": -0.1}, "pd"),
            ({"pfa": 1e-6, "snr_db": float("nan")}, "snr_db"),
            ({"pfa": 1e-6, "pd": 0.9, "n_pulses": 0.5}, "n_pulses"),
            ({"pfa": 1e-6, "pd": 0.9, "n_pulses": -2}, "n_pulses")):
        out = run_calculator("albersheim_detection_snr", bad)
        assert out["ok"] is False, f"越界输入未拒绝: {bad!r} -> {out!r}"
        assert match in out["error"]


# ─── ca_cfar_threshold：闭式回代 / 蒙特卡洛独立裁判 / 守卫 ──────────────────


def test_cfar_alpha_anchor_and_closed_roundtrip():
    """N=16/Pfa=1e-4 → α=12.4525；Pfa 闭式回代逐位自洽。"""
    r = _run("ca_cfar_threshold", {"pfa": 1e-4, "n_ref": 16})
    beta = 10.0 ** (4.0 / 16.0) - 1.0  # 独立重算 β=Pfa^(−1/N)−1
    assert r["beta"] == pytest.approx(beta, rel=1e-12)
    assert r["alpha"] == pytest.approx(16.0 * beta, rel=1e-12)
    assert r["alpha"] == pytest.approx(12.4525, abs=1e-3)
    assert r["pfa_roundtrip"] == pytest.approx(1e-4, rel=1e-12)
    assert r["alpha_db"] == pytest.approx(10.0 * math.log10(r["alpha"]),
                                          abs=1e-9)


def test_cfar_monte_carlo_pfa_and_swerling1_pd_referee():
    """蒙特卡洛独立裁判：经验 Pfa 与 SW1-Pd 落 3σ 带（指数噪声单元）。

    仿真口径：参考窗 16 单元 iid Exp(1)，单元平均×α 为门限；H1 时被检
    单元 Exp(1+S)（Swerling 1）。1e7 试验分块（防 10M×16 大矩阵驻内存）
    → Pfa 事件 ~1000 个（3σ≈9.5%，带宽 12%）、Pd 事件 ~3.3e6 个
    （3σ≈0.05%，带宽 2%）。门限只依赖参考窗、与被检单元独立（统计合法）。
    """
    rng = np.random.default_rng(20261011)
    n_trial, n_ref, pfa = 10_000_000, 16, 1e-4
    r = _run("ca_cfar_threshold",
             {"pfa": pfa, "n_ref": n_ref, "snr_db": 10.0})
    alpha = r["alpha"]
    s_lin = 10.0 ** (10.0 / 10.0)
    n_chunks, chunk = 20, 500_000
    pfa_hits = pd_hits = 0
    for _ in range(n_chunks):
        thr = alpha * rng.exponential(1.0, (chunk, n_ref)).mean(axis=1)
        pfa_hits += int((rng.exponential(1.0, chunk) > thr).sum())
        pd_hits += int((rng.exponential(1.0 + s_lin, chunk) > thr).sum())
    assert pfa_hits / n_trial == pytest.approx(pfa, rel=0.12)
    pd_mc = pd_hits / n_trial
    assert pd_mc == pytest.approx(r["pd_swerling1"], rel=0.02)
    assert r["pd_swerling1"] == pytest.approx(0.335, abs=2e-3)  # 文献量级


def test_cfar_guards_explicit():
    """pfa/n_ref 越界显式拒绝（任务书纪律）。"""
    for bad, match in (
            ({"pfa": 0.0, "n_ref": 16}, "pfa"),
            ({"pfa": 1.0, "n_ref": 16}, "pfa"),
            ({"pfa": -1e-4, "n_ref": 16}, "pfa"),
            ({"pfa": 1e-4, "n_ref": 0}, "n_ref"),
            ({"pfa": 1e-4, "n_ref": 16.5}, "n_ref"),
            ({"pfa": 1e-4, "n_ref": 8192}, "n_ref"),
            ({"pfa": 1e-4, "n_ref": 16, "snr_db": float("nan")}, "snr_db")):
        out = run_calculator("ca_cfar_threshold", bad)
        assert out["ok"] is False, f"越界输入未拒绝: {bad!r} -> {out!r}"
        assert match in out["error"]


# ─── service 出口契约：六键 ok=True、结果 dict、可 JSON 化 ──────────────────


@pytest.mark.parametrize("key,params", [
    ("modulation_ber_curve", {"ebn0_db": [0.0, 10.0], "scheme": "qpsk"}),
    ("required_ebn0", {"target_ber": 1e-5, "scheme": "bpsk"}),
    ("coded_ber_estimate", {"scheme": "16qam", "ebn0_db": 12.0,
                            "code_rate": 0.5, "coding_gain_db": 3.0}),
    ("radar_range_equation", _DB_NOMINAL),
    ("albersheim_detection_snr", {"pfa": 1e-6, "pd": 0.9}),
    ("ca_cfar_threshold", {"pfa": 1e-4, "n_ref": 16}),
])
def test_service_envelope_json_contract(key, params):
    """service 出口契约：ok=True、结果 dict、可 JSON 化（JSON 进出）。"""
    assert key in CALCULATOR_REGISTRY.names()
    out = run_calculator(key, params)
    assert out["ok"] is True and isinstance(out["result"], dict)
    json.dumps(out, ensure_ascii=False, allow_nan=False)
