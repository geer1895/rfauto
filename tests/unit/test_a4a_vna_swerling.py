"""aurora72 A4-A 席锚树：vna_uncertainty 三键 + radar_detection_ext 两键。

数值断言口径（#118 不自证——裁判全部为测试侧独立实现）：
- VNA 族：①方向性地板恒等（Γ=0 → |δΓ|=|Ed|、回损地板=−directivity_db，
  "残差方向性限定可测最佳回损"经典结论）；②单误差项退化逐位；③20dB
  负载@40dB 残差经典例纹波 ~±0.9dB 文献带 + 全项独立重算逐位；④Type-B
  u=界/√3 方和根独立重算（EURAMET cg-12 口径）；⑤隔离地板恒等；⑥直通
  @El=−20dB 增益纹波 20lg(1.1) 独立重算；⑦三天线法 Friis 正演→反演逐
  位回收 + 独立 92.45+20lgf_GHz+20lgd_km 常数式双源 + 对称 IL 恒等 +
  比较法平移恒等。
- Swerling 族：①SW1≡SW2（N=1）闭式逐位 + 独立公式重算（S̄=T/ln(1/Pd)
  −1）；②SW3≡SW4（N=1）双路线互证 + quad 积分核复现闭式（机器精度）；
  ③SW2 全 N 与 scipy gammaincc/gammainccinv 独立重算逐位 + 三向互算闭
  环；④SW4 有限和 vs 原始基元蒙特卡洛（3σ 二项带）；⑤SW1 quad vs 原
  始基元蒙特卡洛（3σ 二项带）；⑥SW0 交叉锚：SW1 损失=21.14−13.18=
  7.96dB（SW0 经 ncx2+brentq 独立实现，经典 Swerling 损耗数 dB 窗）；
  ⑦单调律（Pd↑SNR↑/SNR↓N↑/积累 improvement>0）与符号语义（SW1 loss>0
  /SW2 loss<0=起伏分集，docstring 声明）。
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


def _sw0_exact_snr_db(pfa: float, pd: float) -> float:
    """SW0 非起伏单脉冲精确反解（独立实现）：T=√(−2lnPfa)，Pd=Q1(√(2S),T)。

    Marcum Q1 经非中心 χ² 映射 Q1(a,b)=ncx2.sf(b²; df=2, nc=a²)
    （与 test_w4a_mod_radar 同款独立路线，本树自含）。"""
    from scipy.optimize import brentq
    from scipy.stats import ncx2

    t = math.sqrt(-2.0 * math.log(pfa))
    a_req = brentq(lambda a: ncx2.sf(t * t, 2, a * a) - pd,
                   1e-6, 60.0, xtol=1e-13)
    return 10.0 * math.log10(a_req * a_req / 2.0)


# ─── vna_reflection_uncertainty：地板/退化/经典例/Type-B ────────────────────


def test_reflection_directivity_floor_identity():
    """Γ=0 → 纹波=|Ed| 恒等；回损地板=−directivity_db（方向性限定最佳
    可测回损，经典结论）。"""
    r = _run("vna_reflection_uncertainty",
             {"gamma_mag": 0.0, "directivity_db": -40.0,
              "source_match_db": -35.0})
    ed_lin = 10.0 ** (-40.0 / 20.0)
    assert r["e_gamma_worst"] == pytest.approx(ed_lin, rel=1e-12)
    assert r["rl_floor_db"] == pytest.approx(40.0, abs=1e-9)
    assert r["return_loss_db"] is None
    assert r["dominant_term"] == "directivity"
    # 源匹配项 γ²=0 消失：单误差项退化恒等
    assert r["terms"]["source_match"] == pytest.approx(0.0, abs=1e-30)


def test_reflection_single_term_degeneracy_exact():
    """单误差项退化逐位：只留 Es（Ed=−120dB 近零、无跟踪）→ e=|Es||Γ|²。"""
    r = _run("vna_reflection_uncertainty",
             {"gamma_mag": 1.0, "directivity_db": -120.0,
              "source_match_db": -20.0})
    es_lin = 10.0 ** (-20.0 / 20.0)
    assert r["e_gamma_worst"] == pytest.approx(es_lin + 1e-6, rel=1e-9)
    assert r["terms"]["source_match"] == pytest.approx(es_lin, rel=1e-12)
    assert r["dominant_term"] == "source_match"


def test_reflection_classic_20db_load_anchor():
    """经典例：20dB 负载@40dB 残差方向性/源匹配+±0.05dB 跟踪 → 纹波
    ~±0.9dB（文献口径带）+ 全项独立重算逐位。"""
    r = _run("vna_reflection_uncertainty",
             {"gamma_mag": 0.1, "directivity_db": -40.0,
              "source_match_db": -40.0, "tracking_db": 0.05})
    ed = 10.0 ** (-40.0 / 20.0)
    tr = 10.0 ** (0.05 / 20.0) - 1.0
    e_ref = ed + tr * 0.1 + ed * 0.1 ** 2  # 独立重算三误差项线性相加
    assert r["e_gamma_worst"] == pytest.approx(e_ref, rel=1e-12)
    assert r["terms"]["tracking"] == pytest.approx(tr * 0.1, rel=1e-12)
    assert r["rl_meas_min_db"] == pytest.approx(
        -20.0 * math.log10(0.1 + e_ref), abs=6e-7)
    assert r["rl_meas_max_db"] == pytest.approx(
        -20.0 * math.log10(0.1 - e_ref), abs=6e-7)
    # 经典带：纹波 ~±0.9dB（方向性主导项；文献 VNA 不确定度口径）
    ripple_min = r["rl_meas_min_db"] - 20.0
    assert -1.1 < ripple_min < -0.7
    assert r["dominant_term"] == "directivity"


def test_reflection_rss_uniform_type_b():
    """rss 档：u=√Σ(项/√3)²（均匀分布 Type-B，EURAMET cg-12）独立重算；
    U=k·u；u_RL=8.686·u/|Γ| 线性化换算独立重算。"""
    params = {"gamma_mag": 0.3, "directivity_db": -45.0,
              "source_match_db": -40.0, "tracking_db": 0.1,
              "combine": "rss", "k": 2.0}
    r = _run("vna_reflection_uncertainty", params)
    ed = 10.0 ** (-45.0 / 20.0)
    tr = 10.0 ** (0.1 / 20.0) - 1.0
    es = 10.0 ** (-40.0 / 20.0)
    terms = [ed, tr * 0.3, es * 0.3 ** 2]
    u_ref = math.sqrt(sum((t / math.sqrt(3.0)) ** 2 for t in terms))
    assert r["u_gamma_rss"] == pytest.approx(u_ref, rel=1e-12)
    assert r["u_gamma_expanded"] == pytest.approx(2.0 * u_ref, rel=1e-12)
    assert r["rl_u_db"] == pytest.approx(8.685890 / 0.3 * u_ref, abs=6e-7)
    # worst 界仍并列输出（两种口径同键并存）
    assert r["e_gamma_worst"] == pytest.approx(sum(terms), rel=1e-12)


# ─── vna_transmission_uncertainty：隔离地板/直通纹波 ────────────────────────


def test_transmission_isolation_floor_identity():
    """S21=0 → 纹波=|Xt| 恒等；隔离地板=−crosstalk_db（串扰限定隔离度）。"""
    r = _run("vna_transmission_uncertainty",
             {"s21_mag": 0.0, "crosstalk_db": -90.0,
              "load_match_db": -25.0})
    xt_lin = 10.0 ** (-90.0 / 20.0)
    assert r["e_s21_worst"] == pytest.approx(xt_lin, rel=1e-12)
    assert r["isolation_floor_db"] == pytest.approx(90.0, abs=1e-9)
    assert r["dominant_term"] == "crosstalk"


def test_transmission_loadmatch_passthrough_anchor():
    """直通 |S21|=1@El=−20dB → 纹波=|El|（+串扰微量）；增益上窗
    20lg(1.1)≈0.828dB 独立重算。"""
    r = _run("vna_transmission_uncertainty",
             {"s21_mag": 1.0, "crosstalk_db": -120.0,
              "load_match_db": -20.0})
    el = 10.0 ** (-20.0 / 20.0)
    xt = 10.0 ** (-120.0 / 20.0)
    assert r["e_s21_worst"] == pytest.approx(el + xt, rel=1e-9)
    assert r["g21_meas_max_db"] == pytest.approx(
        20.0 * math.log10(1.0 + el + xt), abs=6e-7)
    # 文献口径：~0.83dB 失配纹波带
    assert 0.7 < r["g21_meas_max_db"] < 0.9
    assert r["dominant_term"] == "load_match"


# ─── three_antenna_gain：Friis 闭环/对称恒等/比较法 ─────────────────────────


C_M_S = 299792458.0  # 光速 SI 精确值（m/s，与 C_MM_GHZ 同源不同路线）


def _fspl_ref_db(f_ghz: float, range_m: float) -> float:
    """独立 FSPL（4πdf/c 直算路线，与键内 4πR/λ 路线互证；92.45 常数式
    为工程圆整值，与本键逐位对照差 ~0.002dB 故不用于逐位锚）。"""
    return 20.0 * math.log10(4.0 * math.pi * range_m * f_ghz * 1e9 / C_M_S)


def test_three_antenna_friis_roundtrip_and_dual_source_fspl():
    """给定真增益 (20,15,10)dBi 经独立 Friis 正演 IL → 反演回收逐位；
    FSPL 双路线（4πR/λ vs 92.45 常数式）一致。"""
    f_ghz, rng_m = 10.0, 10.0
    gains = (20.0, 15.0, 10.0)
    fs_ref = _fspl_ref_db(f_ghz, rng_m)
    il12 = fs_ref - (gains[0] + gains[1])
    il13 = fs_ref - (gains[0] + gains[2])
    il23 = fs_ref - (gains[1] + gains[2])
    r = _run("three_antenna_gain", {
        "method": "three_antenna", "il12_db": il12, "il13_db": il13,
        "il23_db": il23, "f_ghz": f_ghz, "range_m": rng_m})
    assert r["gain1_db"] == pytest.approx(gains[0], abs=5e-9)
    assert r["gain2_db"] == pytest.approx(gains[1], abs=5e-9)
    assert r["gain3_db"] == pytest.approx(gains[2], abs=5e-9)
    assert r["fspl_db"] == pytest.approx(fs_ref, abs=5e-9)
    assert abs(r["pair_sum_max_err"]) < 1e-9  # 构造恒等式机器精度自检


def test_three_antenna_symmetric_identity():
    """对称插入损耗 → 三增益相等=(FS−IL)/2 恒等。"""
    r = _run("three_antenna_gain", {
        "il12_db": 60.0, "il13_db": 60.0, "il23_db": 60.0,
        "f_ghz": 5.0, "range_m": 20.0})
    fs = _fspl_ref_db(5.0, 20.0)
    assert r["gain1_db"] == r["gain2_db"] == r["gain3_db"]
    assert r["gain1_db"] == pytest.approx((fs - 60.0) / 2.0, abs=5e-9)


def test_three_antenna_comparison_shift_identity():
    """比较法平移恒等：G_dut=G_ref+(IL_ref−IL_dut)。"""
    r = _run("three_antenna_gain", {
        "method": "comparison", "ref_gain_db": 25.0,
        "il_ref_db": 58.0, "il_dut_db": 55.5})
    assert r["gain_dut_db"] == pytest.approx(25.0 + 2.5, abs=1e-12)


# ─── swerling_detection_factor：闭式恒等/双路线/独立重算 ────────────────────


def test_sw1_sw2_n1_closed_identity_and_anchor():
    """SW1≡SW2（N=1 单脉冲退化）逐位；独立公式重算 S̄=T/ln(1/Pd)−1；
    经典锚 Pfa=1e-6/Pd=0.9 → 21.14dB。"""
    pfa, pd = 1e-6, 0.9
    r1 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 1})
    r2 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 2})
    assert r1["snr_db"] == r2["snr_db"]  # 同一闭式路径，逐位
    t = -math.log(pfa)
    s_ref = 10.0 * math.log10(t / math.log(1.0 / pd) - 1.0)  # 独立重算
    assert r1["snr_db"] == pytest.approx(s_ref, abs=6e-7)
    assert r1["snr_db"] == pytest.approx(21.14, abs=5e-3)  # 经典锚位
    assert r1["threshold_t"] == pytest.approx(t, abs=5e-10)
    assert r1["method"] == "closed_form_single_pulse"


def test_sw3_sw4_n1_two_routes_and_quad_kernel_machine_precision():
    """SW3≡SW4（N=1）双路线互证；quad 积分核在该点复现闭式（机器精度）；
    门限为 Gamma(1,1) 噪声地板 T=−lnPfa（与 k 无关口径）。"""
    from scipy.special import gammainccinv

    pfa, pd = 1e-6, 0.9
    r3 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 3})
    r4 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 4})
    assert r3["snr_db"] == pytest.approx(r4["snr_db"], abs=1e-6)
    t1 = float(gammainccinv(1, pfa))
    assert r4["threshold_t"] == pytest.approx(t1, abs=5e-10)
    s_lin = 10.0 ** (r4["snr_db"] / 10.0)
    from rfauto.core.calc_families import radar_detection_ext as rde
    pd_quad = rde._pd_swerling1or3(3, 1, s_lin, t1)
    assert pd_quad == pytest.approx(pd, rel=1e-6)  # 积分核 vs 有限和
    pd_quad1 = rde._pd_swerling1or3(1, 1, s_lin, t1)
    assert pd_quad1 == pytest.approx(math.exp(-t1 / (1.0 + s_lin)), rel=1e-9)


def test_sw2_all_n_closed_vs_scipy_recompute_and_roundtrip():
    """SW2 全 N 精确闭式：与 scipy gammaincc/gammainccinv 独立重算逐位；
    三向互算闭环（前向→两反方向回填复现）。"""
    from scipy.special import gammaincc, gammainccinv

    pfa, pd = 1e-5, 0.85
    for n in (1, 2, 5, 16):
        r = _run("swerling_detection_factor",
                 {"pfa": pfa, "pd": pd, "swerling": 2, "n_pulses": n})
        t = float(gammainccinv(n, pfa))  # 独立重算门限
        s_ref = 10.0 * math.log10(t / float(gammainccinv(n, pd)) - 1.0)
        assert r["snr_db"] == pytest.approx(s_ref, abs=6e-7), n
        assert r["method"] == "closed_form_gamma"
        # 前向回代：Q(N, T/(1+S̄)) 独立重算 = pd
        s_lin = 10.0 ** (r["snr_db"] / 10.0)
        assert float(gammaincc(n, t / (1.0 + s_lin))) == pytest.approx(
            pd, rel=1e-6)
        # (pfa, snr)→pd 反解闭环
        r_pd = _run("swerling_detection_factor",
                    {"pfa": pfa, "snr_db": r["snr_db"], "swerling": 2,
                     "n_pulses": n})
        assert r_pd["pd"] == pytest.approx(pd, rel=1e-6)
        # (pd, snr)→pfa 反解闭环
        r_pfa = _run("swerling_detection_factor",
                     {"pd": pd, "snr_db": r["snr_db"], "swerling": 2,
                      "n_pulses": n})
        assert r_pfa["pfa"] == pytest.approx(pfa, rel=1e-4)


def _mc_pd_fast4(n_pulses: int, s_lin: float, t: float, n_trials: int,
                 seed: int) -> float:
    """SW4 原始基元蒙特卡洛（独立裁判）：**每脉冲独立重抽** x~Gamma(2,
    S̄/2)（两独立指数和）、z=|n+√x·e^{jθ}|²（n=单位复高斯）、W=Σz>T 判决
    （快起伏=脉冲间独立，与慢起伏共享 x 的 SW3 口径严格区分）。"""
    rng = np.random.default_rng(seed)
    count = 0
    done = 0
    while done < n_trials:
        m = min(200_000, n_trials - done)
        # x 形状 (m, n_pulses)：快起伏逐脉冲独立重抽
        x = (-(s_lin / 2.0) * np.log(
            rng.random((m, n_pulses, 2)))).sum(axis=2)
        amp = np.sqrt(x)
        th = rng.random((m, n_pulses)) * 2.0 * math.pi
        nre = rng.standard_normal((m, n_pulses)) / math.sqrt(2.0)
        nim = rng.standard_normal((m, n_pulses)) / math.sqrt(2.0)
        z = ((nre + amp * np.cos(th)) ** 2
             + (nim + amp * np.sin(th)) ** 2)
        count += int((z.sum(axis=1) > t).sum())
        done += m
    return count / n_trials


def test_sw4_finite_sum_monte_carlo_referee():
    """SW4 有限和 vs 原始基元蒙特卡洛（N=4/Pfa=1e-4/S=5dB，4σ 二项带）。"""
    from scipy.special import gammainccinv

    n, pfa, snr_db = 4, 1e-4, 5.0
    r = _run("swerling_detection_factor",
             {"pfa": pfa, "snr_db": snr_db, "swerling": 4, "n_pulses": n})
    pd_model = r["pd"]
    assert 0.3 < pd_model < 0.95  # MC 灵敏度窗（事件数充分）
    t = float(gammainccinv(n, pfa))
    n_trials = 600_000
    pd_mc = _mc_pd_fast4(n, 10.0 ** (snr_db / 10.0), t, n_trials, 20261011)
    sigma = math.sqrt(pd_model * (1.0 - pd_model) / n_trials)
    assert abs(pd_mc - pd_model) <= 4.0 * sigma  # 3σ 带+余量


def test_sw1_slow_quad_monte_carlo_referee():
    """SW1 quad vs 原始基元蒙特卡洛（N=8/Pfa=1e-4，慢起伏=全脉冲同一
    x；3σ 二项带）。"""
    from scipy.special import gammainccinv

    n, pfa, snr_db = 8, 1e-4, 13.0
    r = _run("swerling_detection_factor",
             {"pfa": pfa, "snr_db": snr_db, "swerling": 1, "n_pulses": n})
    pd_model = r["pd"]
    assert 0.3 < pd_model < 0.95
    assert r["method"] == "numerical_quadrature_1d"
    t = float(gammainccinv(n, pfa))
    s_lin = 10.0 ** (snr_db / 10.0)
    rng = np.random.default_rng(20261012)
    n_trials = 400_000
    x = -s_lin * np.log(rng.random(n_trials))  # Exp(S̄) 全脉冲共用
    amp2 = np.sqrt(x)[:, None]
    th = rng.random(n_trials) * 2.0 * math.pi
    nre = rng.standard_normal((n_trials, n)) / math.sqrt(2.0)
    nim = rng.standard_normal((n_trials, n)) / math.sqrt(2.0)
    z = ((nre + amp2 * np.cos(th)[:, None]) ** 2
         + (nim + amp2 * np.sin(th)[:, None]) ** 2)
    pd_mc = float((z.sum(axis=1) > t).mean())
    sigma = math.sqrt(pd_model * (1.0 - pd_model) / n_trials)
    assert abs(pd_mc - pd_model) <= 4.0 * sigma


def test_sw0_loss_window_classic_anchor():
    """SW0 交叉锚：SW1 相对 SW0 检测损失 @Pd=0.9/Pfa=1e-6/N=1 = 7.96dB
    （SW0 经 ncx2+brentq 独立实现）——经典 Swerling 损耗数 dB 窗。"""
    r_sw1 = _run("swerling_detection_factor",
                 {"pfa": 1e-6, "pd": 0.9, "swerling": 1})
    snr_sw0 = _sw0_exact_snr_db(1e-6, 0.9)
    assert snr_sw0 == pytest.approx(13.1835, abs=1e-3)  # 与 W4 锚同源
    loss = r_sw1["snr_db"] - snr_sw0
    assert loss == pytest.approx(7.96, abs=0.05)
    assert 7.0 < loss < 9.0  # "数 dB"量级窗（任务书锚）


def test_ordering_laws_and_integration_gain_semantics():
    """序律与积累语义：SW4<SW1（N=1 高 Pd 序）；SNR 随 N 降；improvement
    >0；SW1 loss>0 vs SW2 loss<0（起伏分集，docstring 声明符号语义）；
    N=1 退化恒等三量全 0。"""
    pfa, pd = 1e-6, 0.9
    s1 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 1})
    s4 = _run("swerling_detection_factor",
              {"pfa": pfa, "pd": pd, "swerling": 4})
    assert s4["snr_db"] < s1["snr_db"]  # χ²₄ 高 Pd 检测因子低于 χ²₂
    s2_n1 = _run("swerling_detection_factor",
                 {"pfa": pfa, "pd": pd, "swerling": 2, "n_pulses": 1})
    s2_n10 = _run("swerling_detection_factor",
                  {"pfa": pfa, "pd": pd, "swerling": 2, "n_pulses": 10})
    assert s2_n10["snr_db"] < s2_n1["snr_db"]  # 积累降检测因子
    # N=1 退化恒等
    g0 = _run("swerling_integration_gain",
              {"pfa": pfa, "pd": pd, "swerling": 3, "n_pulses": 1})
    assert g0["improvement_db"] == 0.0
    assert g0["integration_loss_db"] == 0.0
    assert g0["coherent_reference_db"] == pytest.approx(0.0, abs=1e-12)
    # SW1 慢起伏：loss>0（低于相干界，经典结论）
    g1 = _run("swerling_integration_gain",
              {"pfa": pfa, "pd": pd, "swerling": 1, "n_pulses": 10})
    assert g1["improvement_db"] > 0.0
    assert g1["integration_loss_db"] > 0.0
    assert g1["coherent_reference_db"] == pytest.approx(10.0, abs=1e-9)
    # SW2 快起伏：分集增益可超相干界（loss<0 如实输出不夹持）
    g2 = _run("swerling_integration_gain",
              {"pfa": pfa, "pd": pd, "swerling": 2, "n_pulses": 10})
    assert g2["improvement_db"] == pytest.approx(
        s2_n1["snr_db"] - s2_n10["snr_db"], abs=1e-5)
    assert g2["integration_loss_db"] < 0.0  # 起伏分集超出 10lgN
    assert g2["snr_db_n"] == pytest.approx(s2_n10["snr_db"], abs=1e-6)


# ─── 守卫族与 JSON 契约 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("key,params,match", [
    ("vna_reflection_uncertainty",
     {"gamma_mag": 1.5, "directivity_db": -40.0, "source_match_db": -35.0},
     "gamma_mag"),
    ("vna_reflection_uncertainty",
     {"gamma_mag": 0.1, "directivity_db": 0.0, "source_match_db": -35.0},
     "directivity_db"),
    ("vna_reflection_uncertainty",
     {"gamma_mag": 0.1, "directivity_db": -40.0,
      "source_match_db": -35.0, "tracking_db": 11.0},
     "tracking_db"),
    ("vna_transmission_uncertainty",
     {"s21_mag": -1.0, "crosstalk_db": -90.0, "load_match_db": -20.0},
     "s21_mag"),
    ("three_antenna_gain",
     {"method": "three_antenna", "il12_db": 65.0, "il13_db": 70.0},
     "缺参数"),
    ("three_antenna_gain",
     {"method": "side_by_side"}, "method"),
    ("swerling_detection_factor",
     {"pfa": 1e-6, "pd": 0.9, "swerling": 0}, "albersheim"),
    ("swerling_detection_factor",
     {"pfa": 1e-6, "pd": 0.9, "swerling": 5}, "swerling"),
    ("swerling_detection_factor",
     {"pfa": 1e-6, "pd": 1e-6, "swerling": 1}, "pd>pfa"),
    ("swerling_detection_factor",
     {"pfa": 1e-6, "pd": 0.9, "swerling": 1, "n_pulses": 4097},
     "n_pulses"),
    ("swerling_detection_factor",
     {"pfa": 1e-6, "pd": 0.9, "snr_db": 10.0, "swerling": 2}, "超定"),
    ("swerling_detection_factor",
     {"pd": 0.9, "swerling": 2}, "给其二"),
    ("swerling_integration_gain",
     {"pfa": 1e-6, "pd": 0.9, "swerling": 2, "n_pulses": 0.5}, "n_pulses"),
    ("swerling_integration_gain",
     {"pfa": 1e-6, "pd": 0.9, "swerling": 2}, "n_pulses"),
])
def test_domain_guards_explicit(key, params, match):
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r} -> {out!r}"
    assert match in out["error"]


@pytest.mark.parametrize("key", [
    "vna_reflection_uncertainty", "vna_transmission_uncertainty",
    "three_antenna_gain", "swerling_detection_factor",
    "swerling_integration_gain",
])
def test_service_json_contract_and_registration(key):
    """五键在册 + 输出 JSON 可序列化（allow_nan=False 契约）。"""
    assert key in CALCULATOR_REGISTRY.names()
    nominal = {
        "vna_reflection_uncertainty": {
            "gamma_mag": 0.1, "directivity_db": -40.0,
            "source_match_db": -35.0},
        "vna_transmission_uncertainty": {
            "s21_mag": 0.9, "crosstalk_db": -100.0,
            "load_match_db": -25.0},
        "three_antenna_gain": {
            "il12_db": 65.0, "il13_db": 70.0, "il23_db": 75.0,
            "f_ghz": 10.0, "range_m": 10.0},
        "swerling_detection_factor": {"pfa": 1e-6, "pd": 0.9,
                                      "swerling": 1},
        "swerling_integration_gain": {"pfa": 1e-6, "pd": 0.9,
                                      "swerling": 2, "n_pulses": 4},
    }[key]
    out = run_calculator(key, nominal)
    assert out["ok"] is True
    json.dumps(out, allow_nan=False)  # JSON 进出契约（NaN/Inf 即炸）
