"""aurora_f W3-S10 内核池件批 4 锚树：D3 AGC 环路 + D5 校准件完整性验证 + D7 六端口反射计。

三域六键（R2_core_tier3 §③ D3/D5/D7 立项）。#118 双源口径：每个闭式
锚都由测试侧独立重算（不同代数路线/常数链/numpy 线代），不赌实现自身
推导；同仓双源（跨键/跨族三方地板互证）逐位。empirical/建模选择如实
（AGC 一阶线性化边界、C_f 一阶模型、ℓ_eff 类不在本席——见各模块
docstring 预声明）。
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

_C = 299792458.0                                # m/s（与实现同物理常数，
# 但测试侧按独立代数路线重算，非 import 实现私有量）
_Q_ENGEN = [(0.0, 0.0), (1.5, 0.0),
            (-0.75, 1.299038105676658), (-0.75, -1.299038105676658)]


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"], f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _err(key: str, params: dict) -> str:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 未显式报错: {out!r}"
    return out.get("error", "")


# ─── D3 键 1：agc_loop_dynamics（闭环常数）───────────────────────────────────

def test_agc_pole_bandwidth_identity():
    """闭环极点/带宽恒等独立重算：f_loop=(1+T)/(2πτ_L)、τ_a=τ_L/(1+T)。"""
    kd, kv, a, tau_l, rho = 0.02, 40.0, 8.0, 2.5e-3, 4.0
    t_open = a * kd * kv  # 测试侧独立乘积（T=6.4）
    d = _run("agc_loop_dynamics", {
        "detector_slope_v_per_db": kd, "vga_slope_db_per_v": kv,
        "loop_gain_a": a, "loop_tau_s": tau_l, "release_ratio": rho})
    assert d["open_loop_gain"] == pytest.approx(t_open, rel=1e-12)
    # 恒等式 1：环路带宽 × 2π × τ_L = 1+T（闭环极点定义回写）
    assert d["loop_bandwidth_hz"] * 2.0 * math.pi * tau_l == pytest.approx(
        1.0 + t_open, rel=1e-12)
    assert d["closed_loop_pole_rad_s"] == pytest.approx(
        (1.0 + t_open) / tau_l, rel=1e-12)
    # 恒等式 2：attack/release 时间常数与带宽互逆（release 带 ρ）
    assert d["attack_tau_s"] == pytest.approx(tau_l / (1.0 + t_open),
                                              rel=1e-12)
    assert d["release_tau_s"] == pytest.approx(rho * tau_l / (1.0 + t_open),
                                               rel=1e-12)
    assert d["release_bandwidth_hz"] * 2.0 * math.pi * rho * tau_l == \
        pytest.approx(1.0 + t_open, rel=1e-12)


def test_agc_steady_state_error_and_settling():
    """稳态误差 1/(1+T)、建立时间 −τ·ln(α)、release=ρ×attack 恒等。"""
    kd, kv, a, tau_l, rho, alpha = 0.01, 50.0, 20.0, 1e-3, 10.0, 0.05
    d = _run("agc_loop_dynamics", {
        "detector_slope_v_per_db": kd, "vga_slope_db_per_v": kv,
        "loop_gain_a": a, "loop_tau_s": tau_l, "release_ratio": rho,
        "settling_fraction": alpha})
    t_open = a * kd * kv
    assert d["steady_state_error_fraction"] == pytest.approx(
        1.0 / (1.0 + t_open), rel=1e-12)
    tau_a = tau_l / (1.0 + t_open)
    assert d["settling_time_attack_s"] == pytest.approx(
        -tau_a * math.log(alpha), rel=1e-12)
    assert d["settling_time_release_s"] == pytest.approx(
        rho * d["settling_time_attack_s"], rel=1e-12)
    # 误差抑制百分比恒等（1−ε 换算独立路线）
    assert d["error_suppression_percent"] == pytest.approx(
        100.0 * t_open / (1.0 + t_open), rel=1e-12)


def test_agc_no_agc_degeneration_limit():
    """无 AGC 退化=T→0（A→0⁺ 极限档）：τ→τ_L、ε→1（开环直通）。"""
    tau_l = 5e-4
    d = _run("agc_loop_dynamics", {
        "detector_slope_v_per_db": 0.01, "vga_slope_db_per_v": 50.0,
        "loop_gain_a": 1e-9, "loop_tau_s": tau_l})
    assert d["open_loop_gain"] == pytest.approx(0.0, abs=1e-6)
    assert d["attack_tau_s"] == pytest.approx(tau_l, rel=1e-7)
    assert d["steady_state_error_fraction"] == pytest.approx(1.0, rel=1e-7)
    # 退化档带宽=开环极点 1/τ_L
    assert d["loop_bandwidth_hz"] == pytest.approx(1.0 / (2.0 * math.pi
                                                          * tau_l),
                                                   rel=1e-7)


def test_agc_threshold_plane_and_guards():
    """起控门限面三参恒等（P_thresh=P_tgt−G0、输出摆幅 ΔG/(1+T)）+守卫族。"""
    d = _run("agc_loop_dynamics", {
        "detector_slope_v_per_db": 0.01, "vga_slope_db_per_v": 50.0,
        "loop_gain_a": 20.0, "loop_tau_s": 1e-3,
        "p_out_target_dbm": -10.0, "g0_db": 30.0,
        "vga_gain_range_db": 40.0})
    tp = d["threshold_plane"]
    assert tp["p_in_threshold_dbm"] == pytest.approx(-40.0, abs=1e-9)
    assert tp["p_in_range_dbm"] == pytest.approx([-40.0, 0.0], abs=1e-9)
    assert tp["p_out_variation_db"] == pytest.approx(
        40.0 / 11.0, rel=1e-12)  # ΔG/(1+T)，T=10
    base = {"detector_slope_v_per_db": 0.01, "vga_slope_db_per_v": 50.0,
            "loop_gain_a": 20.0, "loop_tau_s": 1e-3}
    # 部分门限面显式拒绝
    partial = dict(base, p_out_target_dbm=-10.0)
    assert "p_out_target_dbm" in _err("agc_loop_dynamics", partial)
    # K_d=0 / ρ<1 / α=1 / τ≤0 显式拒绝
    assert _err("agc_loop_dynamics", dict(base,
                                          detector_slope_v_per_db=0.0))
    assert _err("agc_loop_dynamics", dict(base, release_ratio=0.5))
    assert _err("agc_loop_dynamics", dict(base, settling_fraction=1.0))
    assert _err("agc_loop_dynamics", dict(base, loop_tau_s=0.0))


# ─── D3 键 2：agc_loop_response（阶跃轨迹）──────────────────────────────────

def test_agc_step_three_point_analytic():
    """阶跃三点解析：t=0⁺ 全额扰动、t=τ 处 e^{−1}、大 t 渐近终值。"""
    kd, kv, a, tau_l = 0.01, 50.0, 20.0, 1e-3
    t_open = a * kd * kv                      # 10
    tau_a = tau_l / (1.0 + t_open)
    step = 10.0
    r = _run("agc_loop_response", {
        "step_db": step, "t_grid_s": [0.0, tau_a, 1.0],
        "detector_slope_v_per_db": kd, "vga_slope_db_per_v": kv,
        "loop_gain_a": a, "loop_tau_s": tau_l})
    assert r["direction"] == "attack"
    assert r["tau_eff_s"] == pytest.approx(tau_a, rel=1e-12)
    ss = step / (1.0 + t_open)
    # t=0⁺：环路滤波状态连续 → 输出全额扰动（恒等式字段逐位）
    assert r["identity_at_t0_dev_db"] == pytest.approx(step, rel=1e-12)
    assert r["output_dev_db"][0] == pytest.approx(step, rel=1e-12)
    # t=τ：δ=ss·(1+T·e^{−1})（测试侧独立闭式重算）
    assert r["output_dev_db"][1] == pytest.approx(
        ss * (1.0 + t_open * math.exp(-1.0)), rel=1e-12)
    # 大 t 渐近=稳态残差（e^{−20} 机器带）
    assert r["asymptote_dev_db"] == pytest.approx(ss, rel=1e-8)
    assert r["output_dev_db"][2] == pytest.approx(ss, rel=1e-8)
    # 绝对电平面恒等：level=target+dev
    r2 = _run("agc_loop_response", {
        "step_db": step, "t_grid_s": [0.0, 1e-4],
        "detector_slope_v_per_db": kd, "vga_slope_db_per_v": kv,
        "loop_gain_a": a, "loop_tau_s": tau_l, "p_out_target_dbm": -20.0})
    for d_lvl, d_dev in zip(r2["output_level_dbm"],
                                r2["output_dev_db"], strict=True):
        assert d_lvl == pytest.approx(-20.0 + d_dev, abs=1e-9)


def test_agc_release_tau_ratio():
    """负阶跃=release 慢档：τ_eff=ρ·τ_a、两档时间常数比=ρ 恒等。"""
    kd, kv, a, tau_l, rho = 0.01, 50.0, 20.0, 1e-3, 8.0
    common = {"detector_slope_v_per_db": kd, "vga_slope_db_per_v": kv,
              "loop_gain_a": a, "loop_tau_s": tau_l, "release_ratio": rho}
    r_up = _run("agc_loop_response", dict(common, step_db=6.0,
                                          t_grid_s=[1e-4]))
    r_dn = _run("agc_loop_response", dict(common, step_db=-6.0,
                                          t_grid_s=[1e-4]))
    assert r_up["direction"] == "attack"
    assert r_dn["direction"] == "release"
    assert r_dn["tau_eff_s"] == pytest.approx(
        rho * r_up["tau_eff_s"], rel=1e-12)
    # 两档同 t 逐点公式复核（各自 τ 代入同一闭式；负阶跃→偏差为负）
    t_open = a * kd * kv
    ss = 6.0 / (1.0 + t_open)
    assert r_dn["output_dev_db"][0] == pytest.approx(
        -ss * (1.0 + t_open * math.exp(-1e-4 / (rho * tau_l / (1 + t_open)))),
        rel=1e-12)


def test_agc_response_guards():
    """阶跃=0/栅格乱序/非列表/负时间 显式拒绝。"""
    base = {"step_db": 10.0, "t_grid_s": [0.0, 1e-4],
            "detector_slope_v_per_db": 0.01, "vga_slope_db_per_v": 50.0,
            "loop_gain_a": 20.0, "loop_tau_s": 1e-3}
    assert _err("agc_loop_response", dict(base, step_db=0.0))
    assert _err("agc_loop_response", dict(base, t_grid_s=[1e-4, 5e-5]))
    assert _err("agc_loop_response", dict(base, t_grid_s="fast"))
    assert _err("agc_loop_response", dict(base, t_grid_s=[0.0, -1e-4]))


# ─── D5 键 1：cal_kit_standard_response（标准件响应+判据）───────────────────

def test_calkit_ideal_standards_exact():
    """理想件（零 offset/零耗/C_f=0/ratio=1）→ 理想响应逐位+判据 pass。"""
    s = _run("cal_kit_standard_response", {"standard_type": "short",
                                           "freq_ghz": [1.0, 10.0]})
    assert s["response_mag"] == pytest.approx([1.0, 1.0], abs=1e-15)
    assert s["response_phase_deg"] == pytest.approx([180.0, 180.0],
                                                    abs=1e-9)
    assert s["acceptance"]["pass"] is True
    o = _run("cal_kit_standard_response", {"standard_type": "open",
                                           "freq_ghz": [1.0]})
    assert o["response_mag"][0] == pytest.approx(1.0, abs=1e-15)
    assert o["response_phase_deg"][0] == pytest.approx(0.0, abs=1e-9)
    ld = _run("cal_kit_standard_response", {"standard_type": "load",
                                            "freq_ghz": [1.0]})
    assert ld["response_mag"][0] == 0.0
    assert ld["acceptance"]["checks"]["load_rl_min_db"][
        "measured_rl_min_db"] is None  # RL=∞ 走 None JSON 契约
    assert ld["acceptance"]["pass"] is True
    t = _run("cal_kit_standard_response", {"standard_type": "through",
                                           "freq_ghz": [1.0]})
    assert t["response_mag"][0] == pytest.approx(1.0, abs=1e-15)
    assert t["insertion_loss_db"][0] == pytest.approx(0.0, abs=1e-12)
    assert t["group_delay_ns"] == 0.0
    assert t["acceptance"]["pass"] is True


def test_calkit_offset_short_independent_recompute():
    """offset 短路独立重算：相位=180−2βl·deg（独立三角路线）、|Γ|=10^(−A_RT/20)。"""
    f, loff, l1, eps = 10.0, 5.0, 8.6859, 1.0
    s = _run("cal_kit_standard_response", {
        "standard_type": "short", "freq_ghz": [f],
        "offset_length_mm": loff, "offset_loss_db_m_1ghz": l1,
        "epsilon_r_offset": eps})
    # 相位：Γ=−e^{−j2βl} → 相位=180−2βl·deg；2βl=2×360·l·√εr/λ0，
    # λ0=c/f（测试侧独立常数链）
    lam0_mm = _C / (f * 1e9) * 1e3
    two_beta_l_deg = 2.0 * 360.0 * loff * math.sqrt(eps) / lam0_mm
    expect_ph = (180.0 - two_beta_l_deg) % 360.0
    if expect_ph > 180.0:
        expect_ph -= 360.0
    assert s["response_phase_deg"][0] == pytest.approx(expect_ph, abs=1e-9)
    # 幅度：单程损耗 A=L₁·√f·l（dB），往返 2A → |Γ|=10^(−2A/20)
    a_one_way = l1 * math.sqrt(f) * (loff * 1e-3)
    assert s["response_mag"][0] == pytest.approx(
        10.0 ** (-2.0 * a_one_way / 20.0), rel=1e-12)
    # offset 短路电抗语义=|Γ| 仍≈1（小损耗）而相位大转（偏离 180° 达
    # 2βl 回卷量级）
    wrap_dev = two_beta_l_deg % 360.0
    if wrap_dev > 180.0:
        wrap_dev = 360.0 - wrap_dev
    assert s["worst_phase_deviation_deg"] == pytest.approx(wrap_dev,
                                                           abs=1e-9)


def test_calkit_open_cap_phase_negative_rotation():
    """open 边缘电容：相位随 f 单调负旋、|Γ| 保持≈1；独立复数路线重算。"""
    c_ff, z0 = 80.0, 50.0
    o = _run("cal_kit_standard_response", {
        "standard_type": "open", "freq_ghz": [1.0, 5.0],
        "open_cap_ff": c_ff, "z0_ohm": z0})
    ph1, ph5 = o["response_phase_deg"]
    assert ph1 < 0.0 and ph5 < ph1  # 单调负旋
    # 独立重算 @1GHz：Γ_cap=(1−jωCZ0)/(1+jωCZ0) 相位=−2·atan(ωCZ0)
    omega = 2.0 * math.pi * 1e9
    x = omega * (c_ff * 1e-15) * z0
    assert ph1 == pytest.approx(-2.0 * math.degrees(math.atan(x)), rel=1e-9)
    assert o["response_mag"][0] == pytest.approx(1.0, rel=1e-12)  # |Γ_cap|=1


def test_calkit_load_floor_and_through_il():
    """load 失配地板 RL=−20lg|(r−1)/(r+1)|、through IL/时延独立重算。"""
    ld = _run("cal_kit_standard_response", {
        "standard_type": "load", "freq_ghz": [1.0, 10.0],
        "load_z_ratio": 1.1})
    g0 = 0.1 / 2.1  # 测试侧独立 (r−1)/(r+1)
    rl = -20.0 * math.log10(g0)
    assert ld["acceptance"]["checks"]["load_rl_min_db"][
        "measured_rl_min_db"] == pytest.approx(rl, rel=1e-12)
    assert ld["acceptance"]["pass"] is False  # 26.44dB < 35dB 缺省判据
    assert ld["response_mag"] == pytest.approx([g0, g0], rel=1e-12)
    # through：IL=L₁·√f·l、时延=l√εr/c（独立常数链）
    t = _run("cal_kit_standard_response", {
        "standard_type": "through", "freq_ghz": [1.0, 4.0],
        "offset_length_mm": 20.0, "offset_loss_db_m_1ghz": 2.0,
        "epsilon_r_offset": 2.1})
    for f_ghz, il in zip([1.0, 4.0], t["insertion_loss_db"],
                         strict=True):
        assert il == pytest.approx(-2.0 * math.sqrt(f_ghz) * 0.020,
                                   rel=1e-12)
    assert t["group_delay_ns"] == pytest.approx(
        0.020 * math.sqrt(2.1) / _C * 1e9, rel=1e-12)
    assert t["acceptance"]["pass"] is True  # IL≤0.2dB 缺省档


def test_calkit_guards():
    """白名单外/C_f 键错挂/负频/ratio 键错挂/判据窗越界 显式拒绝。"""
    assert _err("cal_kit_standard_response", {"standard_type": "z0_cal",
                                              "freq_ghz": [1.0]})
    assert _err("cal_kit_standard_response", {"standard_type": "short",
                                              "freq_ghz": [1.0],
                                              "open_cap_ff": 30.0})
    assert _err("cal_kit_standard_response", {"standard_type": "open",
                                              "freq_ghz": [-1.0]})
    assert _err("cal_kit_standard_response", {"standard_type": "through",
                                              "freq_ghz": [1.0],
                                              "load_z_ratio": 1.1})
    assert _err("cal_kit_standard_response", {"standard_type": "short",
                                              "freq_ghz": [1.0],
                                              "gamma_mag_min": 0.5})
    assert _err("cal_kit_standard_response", {"standard_type": "load",
                                              "freq_ghz": [1.0],
                                              "load_rl_min_db": 80.0})


# ─── D5 键 2：cal_kit_verify_ripple（纹波法）────────────────────────────────

def test_ripple_perfect_load_floor_triple_source():
    """完美负载地板=−directivity_db：directional_bridge 同值逐位三方互证。"""
    rv = _run("cal_kit_verify_ripple", {"load_gamma_mag": 0.0,
                                        "residual_directivity_db": -40.0})
    assert rv["perfect_load_floor_db"] == pytest.approx(40.0, abs=1e-12)
    assert rv["ripple_pp_db"] == pytest.approx(0.0, abs=1e-12)
    # 同仓双源 1：directional_bridge_response（其 directivity 口径 >0）
    br = _run("directional_bridge_response", {"gamma_mag": 0.0,
                                              "directivity_db": 40.0})
    assert br["rl_floor_db"] == pytest.approx(
        rv["perfect_load_floor_db"], abs=1e-12)
    # 同仓双源 2：vna_reflection_uncertainty（其 directivity 口径 <0）
    vu = _run("vna_reflection_uncertainty", {"gamma_mag": 0.0,
                                             "directivity_db": -40.0,
                                             "source_match_db": -40.0})
    assert -20.0 * math.log10(vu["ed_lin"]) == pytest.approx(
        rv["perfect_load_floor_db"], abs=1e-12)
    # 窗塌缩单点：min=max=|Ed|
    assert rv["gamma_meas_mag_min"] == rv["gamma_meas_mag_max"]


def test_ripple_forward_inverse_roundtrip():
    """注入已知残差→正向纹波解析回收；反向解逐位往返（#118）。"""
    g, d_db = 0.1, -40.0
    rv = _run("cal_kit_verify_ripple", {"load_gamma_mag": g,
                                        "residual_directivity_db": d_db})
    d_lin = 10.0 ** (d_db / 20.0)  # 测试侧独立 10^ 路线
    pp_expect = 20.0 * math.log10((g + d_lin) / (g - d_lin))
    assert rv["ripple_pp_db"] == pytest.approx(pp_expect, rel=1e-12)
    # 窗双界对称恒等：rl_max−rl_min=pp
    assert rv["rl_meas_min_db"] - rv["rl_meas_max_db"] == pytest.approx(
        rv["ripple_pp_db"], rel=1e-9)
    # 反向解：pp→d 逐位往返
    rv2 = _run("cal_kit_verify_ripple", {"load_gamma_mag": g,
                                         "measured_ripple_pp_db":
                                             rv["ripple_pp_db"]})
    assert rv2["mode"] == "inverse"
    assert rv2["residual_directivity_db"] == pytest.approx(d_db, rel=1e-10)
    # 验收面：直接性 −40dB ≤ 35dB 上界 → 直接性判 pass；回损窗下界
    # 20.92dB < 30dB 缺省档 → 负载回损判如实 False（20dB 负载经典例窗）
    assert rv["acceptance"]["checks"]["residual_directivity_max"]["pass"]
    assert rv["acceptance"]["checks"]["load_rl_min"]["pass"] is False
    assert rv["acceptance"]["checks"]["load_rl_min"][
        "measured_rl_min_db"] == pytest.approx(
        -20.0 * math.log10(g - d_lin), rel=1e-12)


def test_ripple_enclosing_regime_and_verdict():
    """d≥g（g>0）包围域：旗标=True、纹波窗仍给（lo=d−g）、回损判据按
    不通过如实记（相位回绕域负载质量判读失义，不外推假窗）。"""
    rv = _run("cal_kit_verify_ripple", {"load_gamma_mag": 0.05,
                                        "residual_directivity_db": -20.0})
    assert rv["directivity_ge_load_gamma"] is True
    lo = 0.1 - 0.05  # d_lin=0.1, lo=|g−d|=0.05（未恰触零，窗仍给）
    assert rv["gamma_meas_mag_min"] == pytest.approx(lo, rel=1e-12)
    assert rv["ripple_pp_db"] == pytest.approx(
        20.0 * math.log10(0.15 / lo), rel=1e-12)
    assert rv["acceptance"]["checks"]["load_rl_min"]["pass"] is False
    assert rv["acceptance"]["pass"] is False
    # d≈g 深谷近触零：pp 巨幅有限值如实（浮点 dB 入参下 d 与 g 差
    # ~1 ulp 落在 d<g 侧属正常——包围旗标不冒认；d==g 恰等的 pp=None
    # 分支为 JSON ∞ 契约防御性守卫）
    rv_near = _run("cal_kit_verify_ripple", {
        "load_gamma_mag": 0.05,
        "residual_directivity_db": 20.0 * math.log10(0.05)})
    assert rv_near["ripple_pp_db"] > 300.0  # 近触零 → dB 域巨幅失真带
    # 验收不通过档：残差方向性 −30dB vs 35dB 上界
    rv2 = _run("cal_kit_verify_ripple", {"load_gamma_mag": 0.2,
                                         "residual_directivity_db": -30.0})
    assert rv2["directivity_ge_load_gamma"] is False
    assert rv2["acceptance"]["checks"]["residual_directivity_max"][
        "pass"] is False
    assert rv2["acceptance"]["pass"] is False


def test_ripple_guards():
    """|Γ| 越域/正反恰给其一违/正 dB/非正 pp 显式拒绝。"""
    assert _err("cal_kit_verify_ripple", {"load_gamma_mag": 1.5})
    assert _err("cal_kit_verify_ripple", {"load_gamma_mag": 0.1})
    assert _err("cal_kit_verify_ripple", {
        "load_gamma_mag": 0.1, "residual_directivity_db": -40.0,
        "measured_ripple_pp_db": 1.7})
    assert _err("cal_kit_verify_ripple", {
        "load_gamma_mag": 0.1, "residual_directivity_db": 40.0})
    assert _err("cal_kit_verify_ripple", {
        "load_gamma_mag": 0.1, "measured_ripple_pp_db": 0.0})
    assert _err("cal_kit_verify_ripple", {
        "load_gamma_mag": 0.1, "measured_ripple_pp_db": 1.7,
        "residual_directivity_max_db": -5.0})


# ─── D7 键 1：six_port_gamma_solve（OLS 反演）───────────────────────────────

def _p_vector(gamma: complex, qs) -> list[float]:
    """测试侧独立合成读数（|Γ−q|² 直算，非 import 实现）。"""
    return [abs(gamma - complex(*q)) ** 2 for q in qs]


def test_sixport_synthetic_recovery():
    """合成回收（#118）：读数测试侧合成→反演 Γ 逐位级回收+残差机器带。"""
    gamma = complex(0.2, -0.3)
    ps = _p_vector(gamma, _Q_ENGEN)
    gs = _run("six_port_gamma_solve", {"power_ratio": ps,
                                       "q_points": [list(q) for q
                                                    in _Q_ENGEN]})
    assert gs["gamma_re"] == pytest.approx(gamma.real, rel=1e-10)
    assert gs["gamma_im"] == pytest.approx(gamma.imag, rel=1e-10)
    assert gs["gamma_mag"] == pytest.approx(abs(gamma), rel=1e-10)
    assert gs["residual_rms"] < 1e-12
    assert gs["gamma_mag_gt1"] is False
    # 深反射点（|Γ| 近 1）与纯虚点同口径回收
    for gamma2 in (complex(-0.5, 0.5), complex(0.0, 0.95)):
        gs2 = _run("six_port_gamma_solve", {
            "power_ratio": _p_vector(gamma2, _Q_ENGEN),
            "q_points": [list(q) for q in _Q_ENGEN]})
        assert gs2["gamma_re"] == pytest.approx(gamma2.real, rel=1e-10)
        assert gs2["gamma_im"] == pytest.approx(gamma2.imag, rel=1e-10)


def test_sixport_ols_matches_exact_3x3_numpy():
    """过定 OLS=恰定直解一致性：测试侧 numpy 独立解 3×3 逐位对拍。"""
    gamma = complex(0.15, 0.4)
    ps = _p_vector(gamma, _Q_ENGEN)
    gs = _run("six_port_gamma_solve", {"power_ratio": ps,
                                       "q_points": [list(q) for q
                                                    in _Q_ENGEN]})
    # 测试侧独立：丢第 4 方程 → 3×3 恰定线性系统 numpy 求解
    a_mat = np.array([[1.0, -2.0 * q[0], -2.0 * q[1]]
                      for q in _Q_ENGEN[:3]])
    b_vec = np.array([ps[i] - (q[0] ** 2 + q[1] ** 2)
                      for i, q in enumerate(_Q_ENGEN[:3])])
    x2, x_re, x_im = np.linalg.solve(a_mat, b_vec)
    assert gs["gamma_re"] == pytest.approx(x_re, rel=1e-9)
    assert gs["gamma_im"] == pytest.approx(x_im, rel=1e-9)
    assert gs["gamma_mag_sq"] == pytest.approx(x2, rel=1e-9)


def test_sixport_powers_dbm_plane():
    """绝对功率面恒等：P_i=incident+10lg(p_i)；p=0 深零点→None（JSON 禁 −∞）。"""
    gamma = complex(0.2, -0.3)
    ps = _p_vector(gamma, _Q_ENGEN)
    gs = _run("six_port_gamma_solve", {
        "power_ratio": ps, "q_points": [list(q) for q in _Q_ENGEN],
        "incident_power_dbm": -10.0})
    for p_read, p_norm in zip(gs["powers_dbm"], ps, strict=True):
        assert p_read == pytest.approx(-10.0 + 10.0 * math.log10(p_norm),
                                       rel=1e-12)
    gs_zero = _run("six_port_gamma_solve", {
        "power_ratio": [0.0, *ps[1:]],
        "q_points": [list(q) for q in _Q_ENGEN],
        "incident_power_dbm": 0.0})
    assert gs_zero["powers_dbm"][0] is None  # Γ 恰落 q0 深零点合法
    assert gs_zero["gamma_mag_gt1"] is False


def test_sixport_guards():
    """元数错/负功率/q 退化/q 元数错 显式拒绝。"""
    q_lists = [list(q) for q in _Q_ENGEN]
    assert _err("six_port_gamma_solve", {"power_ratio": [0.1, 0.2, 0.3],
                                         "q_points": q_lists})
    assert _err("six_port_gamma_solve", {"power_ratio": [-0.1, 1.0, 1.0,
                                                         1.0],
                                         "q_points": q_lists})
    assert _err("six_port_gamma_solve", {
        "power_ratio": [0.13, 1.78, 3.46, 1.9],
        "q_points": [[0.0, 0.0]] * 4})
    assert _err("six_port_gamma_solve", {
        "power_ratio": [0.13, 1.78, 3.46, 1.9],
        "q_points": [[0.0, 0.0], [1.5, 0.0], [-0.75, 1.3]]})
    assert _err("six_port_gamma_solve", {
        "power_ratio": [0.13, 1.78, 3.46, 1.9], "q_points": q_lists,
        "incident_power_dbm": float("nan")})


# ─── D7 键 2：six_port_cal_extract（q 点提取）───────────────────────────────

def test_sixport_cal_extract_recover_and_roundtrip():
    """q 回收+extract→solve 合成回收闭环（#118 主判）。"""
    loads = [complex(0.0, 0.0), complex(0.5, 0.0), complex(0.0, 0.5)]
    pm = [[abs(g - complex(*q)) ** 2 for g in loads] for q in _Q_ENGEN]
    ce = _run("six_port_cal_extract", {
        "known_loads": [[g.real, g.imag] for g in loads],
        "power_matrix": pm})
    for (q_re, q_im), row in zip(_Q_ENGEN, ce["q_points"],
                                 strict=True):
        assert row[0] == pytest.approx(q_re, abs=1e-9)
        assert row[1] == pytest.approx(q_im, abs=1e-9)
    assert ce["residual_rms_max"] < 1e-12  # 恰定直解=机器精度
    # 闭环：提取的 q 喂回 gamma_solve 反演新未知点
    unknown = complex(0.2, -0.3)
    gs = _run("six_port_gamma_solve", {
        "power_ratio": _p_vector(unknown, [tuple(r) for r
                                            in ce["q_points"]]),
        "q_points": ce["q_points"]})
    assert gs["gamma_re"] == pytest.approx(unknown.real, rel=1e-9)
    assert gs["gamma_im"] == pytest.approx(unknown.imag, rel=1e-9)


def test_sixport_cal_overdetermined_and_null():
    """N=4 过定=最小二乘冗余一致；p_ij=0 深零点合法读数。"""
    loads = [complex(0.0, 0.0), complex(0.5, 0.0), complex(0.0, 0.5),
             complex(0.2, -0.3)]
    pm = [[abs(g - complex(*q)) ** 2 for g in loads] for q in _Q_ENGEN]
    ce = _run("six_port_cal_extract", {
        "known_loads": [[g.real, g.imag] for g in loads],
        "power_matrix": pm})
    for (q_re, q_im), row in zip(_Q_ENGEN, ce["q_points"],
                                 strict=True):
        assert row[0] == pytest.approx(q_re, abs=1e-9)
        assert row[1] == pytest.approx(q_im, abs=1e-9)
    assert ce["n_loads"] == 4
    # 深零点：load0=q0 → 首行首列 0 仍合法
    pm2 = [row[:] for row in pm]
    pm2[0][0] = 0.0
    ce2 = _run("six_port_cal_extract", {
        "known_loads": [[g.real, g.imag] for g in loads[:3]],
        "power_matrix": [row[:3] for row in pm2]})
    assert ce2["residual_rms_max"] < 1e-12


def test_sixport_cal_guards():
    """负载不足/共线/q_init_hint 误用/矩阵错列 显式拒绝。"""
    loads3 = [[0.0, 0.0], [0.5, 0.0], [0.0, 0.5]]
    pm3 = [[0.0, 0.25, 0.25], [2.25, 1.0, 2.5],
           [2.25, 3.25, 1.2009618943], [2.25, 3.25, 3.7990381057]]
    assert _err("six_port_cal_extract", {
        "known_loads": loads3[:2], "power_matrix": [r[:2] for r in pm3]})
    assert _err("six_port_cal_extract", {
        "known_loads": [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]],
        "power_matrix": [[0.0, 0.25, 1.0], [2.25, 1.0, 0.25],
                         [2.25, 3.25, 6.25], [2.25, 3.25, 6.25]]})
    assert _err("six_port_cal_extract", {
        "known_loads": loads3, "power_matrix": pm3,
        "q_init_hint": [[0.0, 0.0]]})
    assert _err("six_port_cal_extract", {
        "known_loads": loads3, "power_matrix": pm3[:3]})  # 3 行≠4 路
    assert _err("six_port_cal_extract", {
        "known_loads": loads3, "power_matrix": [r[:2] for r in pm3] * 2})


# ─── 描述形态门（六键 spec 完整性）───────────────────────────────────────────

def test_w3s10_keys_describe_shape():
    """六键描述/参数元数据完整（JSON 进出契约+必填一致+分组挂表）。"""
    by_name = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    keys = ("agc_loop_dynamics", "agc_loop_response",
            "cal_kit_standard_response", "cal_kit_verify_ripple",
            "six_port_gamma_solve", "six_port_cal_extract")
    for key in keys:
        entry = by_name[key]
        assert entry["description"]
        json.dumps(entry, ensure_ascii=False)
        required = {p["name"] for p in entry["params"] if p["required"]}
        assert required == set(CALCULATOR_REGISTRY.get(key).required)
    assert by_name["agc_loop_dynamics"]["group"] == "收发链路·频综"
    assert by_name["agc_loop_response"]["group"] == "收发链路·频综"
    assert by_name["cal_kit_standard_response"]["group"] == "测量与校准"
    assert by_name["cal_kit_verify_ripple"]["group"] == "测量与校准"
    assert by_name["six_port_gamma_solve"]["group"] == "测量与校准"
    assert by_name["six_port_cal_extract"]["group"] == "测量与校准"
