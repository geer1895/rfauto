"""aurora_g W4-S4 席锚树：内核余量出键批十键+en_report W-S 薄增量。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算；
#122 三态/UNVERIFIED 如实不凑绿）：

- WI LoS/NLoS（walfisch_ikegami_los/nlos）：①LoS 教科书点 2000MHz/
  1km=42.6+20lg(2000)=108.6206dB（独立算术）+d 加倍 +26lg2 精确恒等；
  ②NLoS 925MHz 锚点 k_f=−4 逐位+三分量独立算术逐位对拍+与
  link_limits.free_space_path_loss 精确 SI 形带对拍（32.4 圆化常数
  口径差 ~48mdB，同 link_limits docstring 常数注记，|差|≤0.06dB）；
  ③L_ori 分段端点（0→−10/35°→2.39+2.5 原文级接缝/55°→4.0/90°→
  0.01）+medium vs metropolitan k_f 双档；④h_bs>h_roof/Δh_m≤0/b<w
  显式拒绝（#1c 上 roof 分支不做如实）。
- 模拟调制（carson_bandwidth/fm_processing_gain/am_power_split）：
  ①FM 广播 75k/15k → β=5/B=180kHz 逐位+PM 同构+β→0 → 2f_m 逐位退化；
  ②G=3β²(β+1)：β=5 → 450=26.53212514dB+多步独立算术路径（C=1/N₀=1/
  W=15k 数值代回比值 450 逐位——非同一公式二次抄写）+门限三态+
  snr_out=cnr+G_dB 恒等；③AM m=1 → η=1/3/P_sb=P_c/2/PEP=4P_c 逐位、
  m=0.5 → η=1/9 逐位、m>1 拒绝。
- N-way Doherty（doherty_nway_efficiency/doherty_nway_breakpoints）：
  ①N=2 全网格逐位回归既有 core/pa_architectures.doherty_efficiency
  （Cripps 两区域闭式=独立裁判，同仓双源）；②断点回峰 η(σ=m/N)=π/4
  N=2..8 全恒等（<1e-12）+全域 η∈[0,π/4] 稠密网格；③凹陷闭式
  πr(r−1)/(2r−1)²：r=2 → 2π/9 与既有 DOHERTY_ETA_DIP_MIN 逐位+N=3
  数值 argmin 对拍 σ*_r 闭式；④区域 1 斜率恒等 η=(π/4)Nσ+20log10(3)
  满回退；⑤跨键一致性：键面 N=2 与 doherty_efficiency_curve 同值；
  守卫族（n_way 非整数/越域、σ 越域）。
- CTLE（ctle_nyquist_gain/ctle_pole_from_boost/ctle_gain_at）：
  ①DC 增益=g 逐位（f→0⁺ 极限）；②单极对退化 p1=p2=p → f_peak=
  √(p²−z²) 独立算术逐位；③roundtrip：pole_from_boost(5dB) → f_p1
  回灌 nyquist_gain 复现 boost（<1e-9）；④gain_at 与 nyquist_gain
  同参同值（<1e-12）+相位独立 cmath 复算；⑤上限/下限/域序守卫。
- en_report Welch–Satterthwaite：无 dof 输出语义不变（nu_eff=None）/
  单分量 ν 逐位回收/等 u 等 ν → n·ν 恒等/混合预算独立 W-S 手算/ν→∞
  → k=1.959964 正态极限/dof<1 拒绝/灵敏度系数进分子路径。
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.calculator_service import run_calculator


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _err(key: str, params: dict) -> str:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 对非法输入未报错: {out!r}"
    return out["error"]


# ─── WI：walfisch_ikegami_los ───────────────────────────────────────────────


def test_wi_los_textbook_anchor_and_scaling():
    """LoS 教科书点 2000MHz/1km=108.6206dB（独立算术）+d 加倍恒等。"""
    r = _run("walfisch_ikegami_los", {"f_mhz": 2000.0, "d_km": 1.0})
    expect = 42.6 + 26.0 * math.log10(1.0) + 20.0 * math.log10(2000.0)
    assert abs(r["loss_db"] - expect) < 1e-12
    assert abs(expect - 108.62059991327962) < 1e-9
    r2 = _run("walfisch_ikegami_los", {"f_mhz": 2000.0, "d_km": 2.0})
    assert abs(r2["loss_db"] - r["loss_db"]
               - 26.0 * math.log10(2.0)) < 1e-12


def test_wi_los_domain_guards():
    """域盒 [800,2000]MHz/[0.02,5]km 域外显式拒绝。"""
    assert "f_mhz" in _err("walfisch_ikegami_los",
                           {"f_mhz": 799.0, "d_km": 1.0})
    assert "f_mhz" in _err("walfisch_ikegami_los",
                           {"f_mhz": 2100.0, "d_km": 1.0})
    assert "d_km" in _err("walfisch_ikegami_los",
                          {"f_mhz": 1000.0, "d_km": 0.01})
    assert "d_km" in _err("walfisch_ikegami_los",
                          {"f_mhz": 1000.0, "d_km": 6.0})


# ─── WI：walfisch_ikegami_nlos ──────────────────────────────────────────────

_WI_NLOS = {"f_mhz": 925.0, "d_km": 1.0, "h_bs_m": 30.0, "h_m_m": 1.5,
            "h_roof_m": 40.0, "w_m": 15.0, "b_m": 40.0, "phi_deg": 45.0}


def test_wi_nlos_components_independent_arithmetic():
    """925MHz 锚点：k_f=−4 逐位+三分量独立算术逐位对拍。"""
    r = _run("walfisch_ikegami_nlos", dict(_WI_NLOS))
    assert r["k_f"] == -4.0  # 原文锚点频率 925MHz：−4+0.7·(1−1)=−4 逐位
    assert r["k_a"] == 54.0
    # 独立算术路径（逐分量手算）
    l_f = 32.4 + 20.0 * math.log10(1.0) + 20.0 * math.log10(925.0)
    l_ori = 2.5 + 0.075 * (45.0 - 35.0)
    l_rts = (-16.9 - 10.0 * math.log10(15.0) + 10.0 * math.log10(925.0)
             + 20.0 * math.log10(40.0 - 1.5) + l_ori)
    k_d = 18.0 - 15.0 * (40.0 - 30.0) / 40.0
    l_msd = 54.0 + k_d * math.log10(1.0) + (-4.0) * math.log10(925.0) \
        - 9.0 * math.log10(40.0)
    assert abs(r["l_free_db"] - l_f) < 1e-12
    assert abs(r["l_rts_db"] - l_rts) < 1e-12
    assert abs(r["l_msd_db"] - l_msd) < 1e-12
    assert abs(r["l_ori_db"] - l_ori) < 1e-12
    assert abs(r["loss_db"] - (l_f + l_rts + l_msd)) < 1e-12
    assert abs(r["k_d"] - k_d) < 1e-12


def test_wi_nlos_fspl_dual_source_band():
    """L_f 与 free_space_path_loss 精确 SI FSPL 带对拍（32.4 圆化常数
    口径 ~48mdB，同 link_limits docstring 常数注记；|差|≤0.06dB 不凑
    逐位——#118 同仓双源）。"""
    r = _run("walfisch_ikegami_nlos", dict(_WI_NLOS))
    fspl = _run("free_space_path_loss",
                {"distance_m": 1000.0, "freq_hz": 925.0e6})
    assert abs(r["l_free_db"] - fspl["fspl_db"]) <= 0.06


def test_wi_nlos_orientation_and_city_variants():
    """L_ori 分段端点+medium/metropolitan k_f 双档+h_bs=h_roof 接缝 k_d=18。"""
    p = dict(_WI_NLOS)
    r45 = _run("walfisch_ikegami_nlos", p)
    assert abs(r45["l_ori_db"] - (2.5 + 0.075 * 10.0)) < 1e-12
    p0 = dict(p, phi_deg=0.0)
    assert abs(_run("walfisch_ikegami_nlos", p0)["l_ori_db"] - (-10.0)) < 1e-12
    p35 = dict(p, phi_deg=35.0)
    assert abs(_run("walfisch_ikegami_nlos", p35)["l_ori_db"] - 2.5) < 1e-12
    p55 = dict(p, phi_deg=55.0)
    assert abs(_run("walfisch_ikegami_nlos", p55)["l_ori_db"] - 4.0) < 1e-12
    p90 = dict(p, phi_deg=90.0)
    assert abs(_run("walfisch_ikegami_nlos", p90)["l_ori_db"] - 0.01) < 1e-12
    # medium 档 k_f：−4+1.5·(925/925−1) = −4（925 同值）；1800MHz 分岔
    p18 = dict(p, f_mhz=1800.0)
    r18m = _run("walfisch_ikegami_nlos", p18)
    r18d = _run("walfisch_ikegami_nlos", dict(p18, city="medium"))
    assert abs(r18m["k_f"] - (-4.0 + 0.7 * (1800.0 / 925.0 - 1.0))) < 1e-12
    assert abs(r18d["k_f"] - (-4.0 + 1.5 * (1800.0 / 925.0 - 1.0))) < 1e-12
    assert r18m["k_f"] != r18d["k_f"]
    # h_bs=h_roof 接缝：k_d → 18（Δh_b=0）
    p0d = dict(p, h_bs_m=40.0)
    assert abs(_run("walfisch_ikegami_nlos", p0d)["k_d"] - 18.0) < 1e-12


def test_wi_nlos_domain_guards():
    """h_bs>h_roof 分支不做（#1c 原文未复读）/Δh_m≤0/b<w/φ 越域拒绝。"""
    assert "h_roof" in _err("walfisch_ikegami_nlos",
                            dict(_WI_NLOS, h_bs_m=50.0))
    assert "h_m" in _err("walfisch_ikegami_nlos",
                         dict(_WI_NLOS, h_m_m=45.0))
    assert "b_m" in _err("walfisch_ikegami_nlos",
                         dict(_WI_NLOS, b_m=10.0))
    assert "phi_deg" in _err("walfisch_ikegami_nlos",
                             dict(_WI_NLOS, phi_deg=91.0))
    assert "city" in _err("walfisch_ikegami_nlos",
                          dict(_WI_NLOS, city="rural"))


# ─── 模拟调制：carson_bandwidth ─────────────────────────────────────────────


def test_carson_fm_broadcast_anchor_and_pm_isomorphism():
    """FM 广播 75k/15k → β=5/B=180kHz 逐位；PM 相偏口径同构；β→0 退化。"""
    r = _run("carson_bandwidth",
             {"deviation": 75000.0, "mod_freq_hz": 15000.0})
    assert r["beta"] == 5.0
    assert r["bandwidth_hz"] == 180000.0
    # PM：Δφ=5 rad、f_m=15k → 数值同构 180kHz
    rp = _run("carson_bandwidth",
              {"deviation": 5.0, "mod_freq_hz": 15000.0, "mode": "pm"})
    assert rp["bandwidth_hz"] == 180000.0
    assert abs(rp["delta_f_hz"] - 75000.0) < 1e-9
    # β→0：B → 2f_m 逐位（窄带 FM 与 AM DSB 同宽结构恒等式）
    rn = _run("carson_bandwidth",
              {"deviation": 15.0, "mod_freq_hz": 15000.0})
    assert rn["bandwidth_hz"] == 2.0 * (15.0 / 15000.0 + 1.0) * 15000.0
    assert abs(rn["bandwidth_hz"] - 30030.0) < 1e-9
    assert "mode" in _err("carson_bandwidth",
                          {"deviation": 1000.0, "mod_freq_hz": 100.0,
                           "mode": "am"})
    assert "deviation" in _err("carson_bandwidth",
                               {"deviation": 0.0, "mod_freq_hz": 100.0})


# ─── 模拟调制：fm_processing_gain ───────────────────────────────────────────


def test_fm_gain_broadcast_anchor_and_independent_path():
    """G=3β²(β+1)：β=5 → 450 逐位+多步独立算术路径（非同一公式二次抄写）。
    """
    r = _run("fm_processing_gain", {"beta": 5.0, "cnr_db": 20.0})
    assert r["gain_linear"] == 450.0
    assert abs(r["gain_db"] - 26.532125137753436) < 1e-9
    # 独立算术路径：C=1、N₀=1、W=15kHz 数值代回
    c, n0, w, beta = 1.0, 1.0, 15000.0, 5.0
    snr_out = 1.5 * beta ** 2 * c / (n0 * w)          # 鉴频器口径
    cnr_rf = c / (n0 * 2.0 * (beta + 1.0) * w)        # Carson 带宽口径
    assert abs(snr_out / cnr_rf - 450.0) < 1e-9
    assert abs(snr_out / cnr_rf - r["gain_linear"]) < 1e-12
    # snr_out = cnr + G_dB 恒等；门限三态
    assert abs(r["snr_out_db"] - (20.0 + r["gain_db"])) < 1e-12
    assert r["above_threshold"] is True
    r9 = _run("fm_processing_gain", {"beta": 5.0, "cnr_db": 9.0})
    assert r9["above_threshold"] is False
    # β 单调增
    gains = [_run("fm_processing_gain",
                  {"beta": b, "cnr_db": 20.0})["gain_linear"]
             for b in (0.5, 1.0, 2.0, 5.0, 10.0)]
    assert gains == sorted(gains)
    assert "beta" in _err("fm_processing_gain", {"beta": 0.0, "cnr_db": 20.0})
    assert "cnr_db" in _err("fm_processing_gain",
                            {"beta": 5.0, "cnr_db": float("inf")})


# ─── 模拟调制：am_power_split ───────────────────────────────────────────────


def test_am_power_split_textbook_identities():
    """m=1 → η=1/3 逐位/P_sb=P_c/2/PEP=4P_c；m=0.5 → η=1/9 逐位；m>1 拒绝。"""
    r = _run("am_power_split", {"mod_index": 1.0})
    assert r["p_carrier_w"] == 1.0
    assert r["p_sideband_w"] == 0.5
    assert abs(r["efficiency"] - 1.0 / 3.0) < 1e-15
    assert r["pep_w"] == 4.0
    r5 = _run("am_power_split", {"mod_index": 0.5})
    assert r5["p_sideband_w"] == 0.125
    assert abs(r5["efficiency"] - 0.25 / 2.25) < 1e-15
    assert abs(r5["efficiency"] - 1.0 / 9.0) < 1e-12
    assert abs(r5["pep_w"] - 2.25) < 1e-12
    # 功率定标线性：P_c=10 → 全字段 ×10（η 不变）
    r10 = _run("am_power_split", {"mod_index": 1.0, "p_carrier_w": 10.0})
    assert abs(r10["efficiency"] - r["efficiency"]) < 1e-15
    assert r10["p_total_w"] == 15.0
    assert "mod_index" in _err("am_power_split", {"mod_index": 1.1})
    assert "mod_index" in _err("am_power_split", {"mod_index": 0.0})


# ─── N-way Doherty ──────────────────────────────────────────────────────────


def test_doherty_nway_bitwise_regression_on_2way():
    """N=2 全网格逐位回归既有 Cripps 两区域闭式（同仓双源独立裁判）。"""
    from rfauto.core.pa_architectures import doherty_efficiency

    for i in range(1, 2001):
        s = i / 2000.0
        r = _run("doherty_nway_efficiency", {"n_way": 2, "sigma": s})
        assert r["eta"] == doherty_efficiency(s), (s, r["eta"])


def test_doherty_nway_breakpoint_peak_identities():
    """断点回峰 η(σ=m/N)=π/4 N=2..8 全恒等（<1e-12）+全域 η∈[0,π/4]。"""
    for n in range(2, 9):
        for m in range(1, n + 1):
            r = _run("doherty_nway_efficiency",
                     {"n_way": n, "sigma": m / n})
            assert abs(r["eta"] - math.pi / 4.0) < 1e-12, (n, m)
        for i in range(1, 2001):
            s = i / 2000.0
            r = _run("doherty_nway_efficiency", {"n_way": n, "sigma": s})
            assert -1e-15 <= r["eta"] <= math.pi / 4.0 + 1e-12


def test_doherty_nway_dip_closed_forms():
    """凹陷闭式 πr(r−1)/(2r−1)²：r=2 → 2π/9 与既有常数逐位+N=3 数值
    argmin 对拍 σ*_r 闭式。"""
    from rfauto.core.pa_architectures import DOHERTY_ETA_DIP_MIN

    b2 = _run("doherty_nway_breakpoints", {"n_way": 2})
    assert len(b2["dips"]) == 1
    assert b2["dips"][0]["eta_min"] == DOHERTY_ETA_DIP_MIN
    assert abs(b2["dips"][0]["eta_min"] - 2.0 * math.pi / 9.0) < 1e-15
    assert abs(b2["dips"][0]["sigma_star"] - 2.0 / 3.0) < 1e-15
    b3 = _run("doherty_nway_breakpoints", {"n_way": 3})
    assert b3["backoff_full_db"] == 20.0 * math.log10(3.0)
    for d in b3["dips"]:
        r = d["region"]
        expect_sigma = 2.0 * r * (r - 1) / (3.0 * (2.0 * r - 1.0))
        expect_eta = math.pi * r * (r - 1) / (2.0 * r - 1.0) ** 2
        assert abs(d["sigma_star"] - expect_sigma) < 1e-15
        assert abs(d["eta_min"] - expect_eta) < 1e-15
        # 区域内数值 argmin 对拍（区域 r 跨 [(r−1)/3, r/3]，1e-5 步长）
        lo, hi = (r - 1) / 3.0, r / 3.0
        grid = [lo + (hi - lo) * i / 4000.0 for i in range(1, 4000)]
        etas = [_run("doherty_nway_efficiency",
                     {"n_way": 3, "sigma": s})["eta"] for s in grid]
        s_min = grid[etas.index(min(etas))]
        assert abs(s_min - expect_sigma) < 5e-4
        assert abs(min(etas) - expect_eta) < 1e-7


def test_doherty_nway_region1_slope_and_point_profile():
    """区域 1 斜率恒等 η=(π/4)Nσ+工作点电流剖面（主管 σ/峰值管斜率 2）。"""
    for n in (2, 3, 4):
        for s in (0.05, 0.1, 0.2 / n):
            if s > 1.0 / n:
                continue
            r = _run("doherty_nway_efficiency", {"n_way": n, "sigma": s})
            assert abs(r["eta"] - math.pi / 4.0 * n * s) < 1e-12
    r = _run("doherty_nway_efficiency", {"n_way": 3, "sigma": 0.5})
    assert r["region"] == 2
    assert r["active_devices"] == 2
    cur = r["device_currents_over_i1"]
    assert len(cur) == 3
    assert abs(cur[0] - 0.5) < 1e-15
    assert abs(cur[1] - 1.0 / 3.0) < 1e-15
    assert cur[2] == 0.0
    assert abs(r["current_sum"] - (0.5 + 1.0 / 3.0)) < 1e-15
    assert abs(r["eta_over_peak"] - r["eta"] / (math.pi / 4.0)) < 1e-15
    # σ=m/N 断点判读：σ=1/3、2/3、1 处 η 全 π/4（breakpoints 键逐位对拍）
    b3 = _run("doherty_nway_breakpoints", {"n_way": 3})
    for bp in b3["breakpoints"]:
        rp = _run("doherty_nway_efficiency",
                  {"n_way": 3, "sigma": bp["sigma"]})
        assert abs(rp["eta"] - bp["eta"]) < 1e-15


def test_doherty_nway_cross_key_2way_curve():
    """跨键一致性：doherty_nway_efficiency(N=2) 与既有
    doherty_efficiency_curve 同 σ 采样同值（服务面双路径）。"""
    from rfauto.core.pa_architectures import doherty_efficiency_curve

    sigmas = [0.1, 0.3, 0.5, 2.0 / 3.0, 0.8, 1.0]
    curve = doherty_efficiency_curve(sigmas)
    for s, e in zip(sigmas, curve, strict=True):
        r = _run("doherty_nway_efficiency", {"n_way": 2, "sigma": s})
        assert r["eta"] == e


def test_doherty_nway_guards():
    """守卫族：n_way 非整数/越域、σ 越域显式拒绝。"""
    assert "n_way" in _err("doherty_nway_efficiency",
                           {"n_way": 1, "sigma": 0.5})
    assert "n_way" in _err("doherty_nway_efficiency",
                           {"n_way": 9, "sigma": 0.5})
    assert "n_way" in _err("doherty_nway_efficiency",
                           {"n_way": 2.5, "sigma": 0.5})
    assert "sigma" in _err("doherty_nway_efficiency",
                           {"n_way": 3, "sigma": 1.5})
    assert "n_way" in _err("doherty_nway_breakpoints", {"n_way": 1})
    assert "n_way" in _err("doherty_nway_breakpoints", {"n_way": 0})


# ─── CTLE ───────────────────────────────────────────────────────────────────


def test_ctle_dc_identity_and_single_pole_pair_peak():
    """DC 增益=g（f→0⁺ 极限）+重极对退化 p1=p2=p → u*=p²−2z²（impl 闭式
    sqrt((p1²−z²)(p2²−z²))−z² 的 p1=p2 档）独立算术逐位。"""
    z, p = 1.0e6, 1.0e9
    r = _run("ctle_nyquist_gain",
             {"f_z_hz": z, "f_p1_hz": p, "f_nyq_hz": 8.0e9,
              "f_p2_hz": p, "g_dc": 1.0})
    u = p * p - 2.0 * z * z
    expect_peak = math.sqrt(u)
    assert abs(r["f_peak_hz"] - expect_peak) < 1e-6
    gain_at_peak = _run("ctle_gain_at",
                        {"f_z_hz": z, "f_p1_hz": p, "f_hz": expect_peak,
                         "f_p2_hz": p})
    # 峰值增益独立算术：f=√u → |H|² = (1+u/z²)/((1+u/p²)²)
    h2 = (1.0 + u / (z * z)) / (1.0 + u / (p * p)) ** 2
    assert abs(gain_at_peak["gain_db"] - 10.0 * math.log10(h2)) < 1e-9
    assert abs(gain_at_peak["gain_db"] - r["peak_gain_db"]) < 1e-9
    # DC 恒等（f→0⁺ 极限逼近 g；guard f>0，用 1e-6Hz 量级）
    rd = _run("ctle_gain_at",
              {"f_z_hz": z, "f_p1_hz": p, "f_hz": 1.0e-6, "f_p2_hz": p})
    assert abs(rd["gain_db"]) < 1e-9
    assert abs(rd["phase_deg"]) < 1e-3


def test_ctle_pole_from_boost_roundtrip():
    """roundtrip：pole_from_boost(5dB) → f_p1 回灌 nyquist_gain 复现
    boost（<1e-9）+gain_at 与 nyquist_gain 同参同值（<1e-12）。"""
    z, fnyq = 1.0e6, 8.0e9
    r = _run("ctle_pole_from_boost",
             {"boost_db": 5.0, "f_z_hz": z, "f_nyq_hz": fnyq})
    fp1 = r["f_p1_hz"]
    back = _run("ctle_nyquist_gain",
                {"f_z_hz": z, "f_p1_hz": fp1, "f_nyq_hz": fnyq})
    assert abs(back["boost_db"] - 5.0) < 1e-9
    g1 = _run("ctle_gain_at", {"f_z_hz": z, "f_p1_hz": fp1, "f_hz": fnyq})
    assert abs(g1["gain_db"] - back["gain_nyquist_db"]) < 1e-12
    # 带次极点档 roundtrip：f_p2=20GHz
    r2 = _run("ctle_pole_from_boost",
              {"boost_db": 6.0, "f_z_hz": z, "f_nyq_hz": fnyq,
               "f_p2_hz": 20.0e9})
    back2 = _run("ctle_nyquist_gain",
                 {"f_z_hz": z, "f_p1_hz": r2["f_p1_hz"],
                  "f_p2_hz": 20.0e9, "f_nyq_hz": fnyq})
    assert abs(back2["boost_db"] - 6.0) < 1e-9


def test_ctle_gain_at_phase_and_consistency():
    """相位独立 cmath 复算+nyquist_gain/gain_at 同参一致性（任意参数）。"""
    z, p1, p2, f = 2.0e6, 3.0e8, 15.0e9, 8.0e9
    r = _run("ctle_nyquist_gain",
             {"f_z_hz": z, "f_p1_hz": p1, "f_p2_hz": p2,
              "f_nyq_hz": f, "g_dc": 0.8})
    g = _run("ctle_gain_at",
             {"f_z_hz": z, "f_p1_hz": p1, "f_p2_hz": p2,
              "f_hz": f, "g_dc": 0.8})
    assert abs(g["gain_db"] - r["gain_nyquist_db"]) < 1e-12
    h = 0.8 * (1.0 + 1j * f / z) / ((1.0 + 1j * f / p1)
                                    * (1.0 + 1j * f / p2))
    assert abs(g["gain_linear"] - abs(h)) < 1e-15
    assert abs(g["phase_deg"] - math.degrees(cmath.phase(h))) < 1e-9


def test_ctle_guards():
    """上限（超纯零点增益）/下限（低于 boost 域）/域序守卫。"""
    assert "boost" in _err("ctle_pole_from_boost",
                           {"boost_db": 200.0, "f_z_hz": 1e6,
                            "f_nyq_hz": 8e9})
    assert "boost" in _err("ctle_pole_from_boost",
                           {"boost_db": -30.0, "f_z_hz": 1e6,
                            "f_nyq_hz": 8e9})
    assert "f_p1" in _err("ctle_nyquist_gain",
                          {"f_z_hz": 2e9, "f_p1_hz": 1e9,
                           "f_nyq_hz": 8e9})
    assert "f_p2" in _err("ctle_nyquist_gain",
                          {"f_z_hz": 1e6, "f_p1_hz": 1e9,
                           "f_p2_hz": 5e8, "f_nyq_hz": 8e9})
    assert "f_hz" in _err("ctle_gain_at",
                          {"f_z_hz": 1e6, "f_p1_hz": 1e9, "f_hz": 0.0})


# ─── en_report：Welch–Satterthwaite 薄增量 ──────────────────────────────────


def test_gum_backward_compat_no_dof():
    """无 dof 输入：既有输出语义不变（u_c/U/k/contributions 逐位）+
    nu_eff/k_effective 恒 None。"""
    from rfauto.measurement.en_report import gum_combined_uncertainty

    comps = [{"name": "a", "u": 0.1}, {"name": "b", "u": 0.2}]
    out = gum_combined_uncertainty(comps)
    u_c = math.sqrt(0.1 ** 2 + 0.2 ** 2)
    assert abs(out["u_c"] - u_c) < 1e-15
    assert out["U"] == 2.0 * u_c
    assert out["nu_eff"] is None
    assert out["k_effective"] is None
    assert out["U_effective"] is None


def test_gum_ws_single_component_recovers_nu():
    """单分量 ν 逐位回收（ν_eff = ν）+k_eff = t.ppf(0.975, ν)。"""
    from scipy import stats

    from rfauto.measurement.en_report import gum_combined_uncertainty

    out = gum_combined_uncertainty([{"name": "a", "u": 0.1, "dof": 5}])
    assert abs(out["nu_eff"] - 5.0) < 1e-9
    assert abs(out["k_effective"] - float(stats.t.ppf(0.975, 5.0))) < 1e-12
    assert abs(out["U_effective"] - out["k_effective"] * out["u_c"]) < 1e-15


def test_gum_ws_equal_components_nu_multiplication():
    """等 u 等 ν → ν_eff = n·ν 恒等（W-S 经典结构恒等式）。"""
    from rfauto.measurement.en_report import gum_combined_uncertainty

    comps = [{"name": f"c{i}", "u": 0.1, "dof": 4.0} for i in range(3)]
    out = gum_combined_uncertainty(comps)
    assert abs(out["nu_eff"] - 12.0) < 1e-9


def test_gum_ws_mixed_budget_independent_arithmetic():
    """混合预算独立 W-S 手算：u=[2,1]/ν=[3,1000]（灵敏度系数进分子）。"""
    from rfauto.measurement.en_report import gum_combined_uncertainty

    out = gum_combined_uncertainty(
        [{"name": "a", "u": 2.0, "dof": 3.0},
         {"name": "b", "u": 1.0, "dof": 1000.0}])
    u_c = math.sqrt(5.0)
    expect = u_c ** 4 / (16.0 / 3.0 + 1.0 / 1000.0)
    assert abs(out["nu_eff"] - expect) < 1e-9
    out_c = gum_combined_uncertainty(
        [{"name": "a", "u": 0.1, "c": 2.0, "dof": 3.0}])
    expect_c = 0.2 ** 4 / (0.2 ** 4 / 3.0)
    assert abs(out_c["nu_eff"] - expect_c) < 1e-9


def test_gum_ws_normal_limit_and_guard():
    """ν→∞ → k=1.959964 正态极限+dof<1 显式拒绝（GUM Type A ν≥1）。"""
    from rfauto.measurement.en_report import gum_combined_uncertainty

    comps = [{"name": "a", "u": 0.1, "dof": 1e12},
             {"name": "b", "u": 0.1, "dof": 1e12}]
    out = gum_combined_uncertainty(comps)
    assert abs(out["k_effective"] - 1.959963984540054) < 1e-6
    try:
        gum_combined_uncertainty([{"name": "a", "u": 0.1, "dof": 0.5}])
    except ValueError as e:
        assert "dof" in str(e)
    else:
        raise AssertionError("dof<1 未拒绝")
