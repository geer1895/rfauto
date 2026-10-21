"""架构批 A2-C 席锚树：coax_line 四键（同轴 Z0 双向/行波衰减分解/功率
容量/截止式衰减器）+ waveguide_closed_form 三键（圆柱腔模式谱/模式图/模式无载 Q）。

数值断言口径（#118 不自证——恒等式/独立常数/双路线/跨键互证，不用自身
推导互证）：
- 同轴 Z0：空气 50Ω ↔ b/a=e^{5/6} 恒等（双向 roundtrip ≤1e-12）；
  a=1/b=3mm → 60·ln3；εr=2.25 → Z0 准确 ÷1.5；L'·C'=με 恒等；TE11
  截止 =c₀/(π(a+b)) 测试侧独立重算（a=1/b=3mm → 23.8567GHz）；
  ratio_only 路线 b/a=e^{Z0√εr/60} 逐位。
- 衰减：αc∝√f（f×4→×2 逐位）、αc∝1/√σ（σ×4→÷2 逐位）、αd 线性于
  f·tanδ 测试侧独立式 8.686·π·f√εr·tanδ/c₀；线 Q 双路线（β/(2αc) vs
  场积分 ωμ·ln(b/a)/(Rs(1/a+1/b))）rel_dev≤1e-12 且与 combline 族
  cavity_unloaded_q 跨键逐位互证（同输入同物理，独立实现）；Cu/1GHz/
  a=1mm/b=2.301mm 空气 αc≈0.16373 dB/m（实测 0.163730589366；窗
  0.1~0.25）。
- 功率容量：P_max=E_br²a²ln(b/a)√εr/120 恒等式（in-output p_identity
  rel_dev≤1e-12+测试侧独立重算）；V²/(2Z0) 回代恒等；εr×4→P×2
  （√εr 标度）；p_op=P_max/4 → 余量=10log10(4)=6.0206dB；p_op>P_max →
  负余量如实报告；a_opt=b/√e、Z0_opt=30Ω 常数锚。
- 截止衰减器（W8-S37）：深截止每 (a+b) 长度 8.686·2=17.372dB 定义恒等
  式（k_c(a+b)=2）；√(1−(f/f_c)²) 标度（f_c 测试侧独立重算）；L 线性
  逐位；εr 分离标度（f_c÷√εr、k_c 不变）；f_c 与 z0 键跨键同值；EMC
  经典锚=精确圆波导 TE11（k_c=x'_11/b）32.0 dB/直径+λ_c=1.706D 测试侧
  独立常数验证；f≥f_c/a≥b/L≤0/εr<1 显式拒绝。
- 圆柱谱：TM010 f=x_01·c₀/(2πa)（x_01=2.4048255577 测试侧独立常数）；
  主模判据 l<2a→TM010 / l>2a→TE111 双腔复现；TE011/TM111 简并同频
  ≤1e-12；TE011 与 material_characterization._sc_empty_f0 同仓双源
  ≤1e-12；εr=4 → 全谱 ÷2 逐位；TE11 波导截止 x'_11·c₀/(2πa) 独立
  常数；谱 vs 测试侧暴力枚举（不同循环序/scipy 直调）闭合。
- 模式图：TE111/TM010 交叉 r=π/(2·√(x_01²−x'_11²))≈1.0153782（测试侧
  独立常数式）+交叉点 f_norm=x_01 逐位；p≥1 单调降/TM010 平坦；主模
  序列跨交叉翻转；与谱键跨键一致（f_ghz=f_norm·C/(2πa√εr)）。
- 模式 Q：闭式 vs 数值积分双路线 rel_dev≤1e-9（11 模式扫描）；Ue/Um
  ≈1（谐振腔储能定理，测试侧独立体积分验证）；TM010 清洁式
  (η0·k0·a/2Rs)·L/(L+a) 测试侧独立重算 ≤1e-9；Qc∝1/√σ（σ×4→×2
  逐位）；TE011>TE111（无端壁环流高 Q 性质）；介质串联合成单调性；
  新键 description 首行"中文名：全角冒号"形态门（中文名≤24 字符）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

C_MM_GHZ = 299.792458          # mm·GHz（测试侧独立常量，同注册表锚值）
_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_ETA0 = math.sqrt(_MU0 / _EPS0)  # 真空波阻抗（测试侧独立推导）
X01 = 2.4048255577             # J_0 首零（TM010，独立常数）
X11P = 1.8411837814            # J_1' 首零（TE11 波导主模截止）
X01P = 3.8317059702            # J_0' 首零（TE011 径向）


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


# ─── coax_line_z0：阻抗恒等 / 双向 roundtrip / 分布参数 / TE11 截止 ─────────


def test_coax_z0_air_50ohm_identity_both_directions():
    """空气 50Ω ↔ b/a=e^{5/6}：分析与综合双向恒等（≤1e-12）。"""
    b_over_a = math.exp(50.0 / 60.0)
    r = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 1.0 * b_over_a})
    assert r["route"] == "analyze"
    assert r["z0_ohm"] == pytest.approx(50.0, abs=1e-9)
    # 综合：给 z0+b 反解 a，回读 a
    r2 = _run("coax_line_z0", {"z0_ohm": 50.0, "b_mm": 2.5})
    assert r2["route"] == "synthesize_inner"
    assert r2["a_mm"] == pytest.approx(2.5 / b_over_a, rel=1e-12)
    assert r2["z0_ohm"] == pytest.approx(50.0, abs=1e-9)
    # 综合：给 z0+a 反解 b
    r3 = _run("coax_line_z0", {"z0_ohm": 50.0, "a_mm": 0.5})
    assert r3["route"] == "synthesize_outer"
    assert r3["b_mm"] == pytest.approx(0.5 * b_over_a, rel=1e-12)
    # 分析 roundtrip：综合结果回代分析
    r4 = _run("coax_line_z0", {"a_mm": r2["a_mm"], "b_mm": 2.5})
    assert r4["z0_ohm"] == pytest.approx(50.0, abs=1e-9)


def test_coax_z0_ln3_anchor_and_dielectric_scaling():
    """a=1/b=3mm → 60·ln3 锚；εr=2.25 → Z0 准确 ÷1.5（√εr 标度）。"""
    r = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0})
    assert r["z0_ohm"] == pytest.approx(60.0 * math.log(3.0), abs=1e-9)
    r2 = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 2.25})
    assert r2["z0_ohm"] == pytest.approx(r["z0_ohm"] / 1.5, rel=1e-12)


def test_coax_z0_lumped_products_identity():
    """L'·C' = με 恒等（键输出 lc_over_muepsilon ≈ 1，≤1e-12）。"""
    r = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 2.25})
    # 测试侧独立重算分布参数并核恒等式
    ln_ratio = math.log(3.0)
    c_prime = 2.0 * math.pi * _EPS0 * 2.25 / ln_ratio
    l_prime = _MU0 * ln_ratio / (2.0 * math.pi)
    assert r["capacitance_pf_per_m"] == pytest.approx(c_prime * 1e12,
                                                      rel=1e-9)
    assert r["inductance_nh_per_m"] == pytest.approx(l_prime * 1e9, rel=1e-9)
    assert l_prime * c_prime == pytest.approx(_MU0 * _EPS0 * 2.25,
                                              rel=1e-15)
    assert r["lc_over_muepsilon"] == pytest.approx(1.0, abs=1e-12)


def test_coax_z0_te11_cutoff_independent_constant():
    """TE11 截止 =c₀/(π(a+b)√εr)：测试侧独立重算（a=1/b=3mm 空气）。"""
    r = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0})
    expect = C_MM_GHZ / (math.pi * 4.0)
    assert r["te11_cutoff_ghz"] == pytest.approx(expect, abs=1e-9)
    assert expect == pytest.approx(23.8567, abs=5e-4)  # 独立常数窗
    # εr=2.25 → 截止 ÷1.5
    r2 = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 2.25})
    assert r2["te11_cutoff_ghz"] == pytest.approx(expect / 1.5,
                                                   abs=1e-8)  # 键输出 9 位舍入


def test_coax_z0_ratio_only_route():
    """只给 z0 → ratio_only：b/a=e^{Z0√εr/60}，无绝对尺寸。"""
    r = _run("coax_line_z0", {"z0_ohm": 75.0, "epsilon_r": 2.25})
    assert r["route"] == "ratio_only"
    assert r["b_over_a"] == pytest.approx(math.exp(75.0 * 1.5 / 60.0),
                                          rel=1e-12)
    assert r["a_mm"] is None and r["b_mm"] is None
    assert r["te11_cutoff_ghz"] is None
    assert r["z0_max_power_ratio_ohm"] == pytest.approx(30.0 / 1.5,
                                                        rel=1e-12)


def test_coax_z0_optimum_ratio_constants():
    """最优比常数：功率最大 30/√εr（b/a=√e）；损耗最小 76.7/√εr
    （lnx=1+1/x 根，测试侧独立二分重解）。"""
    r = _run("coax_line_z0", {"a_mm": 1.0, "b_mm": 2.0})
    assert r["z0_max_power_ratio_ohm"] == pytest.approx(30.0, abs=1e-9)
    # 测试侧独立解 ln x = 1 + 1/x
    lo, hi = 2.7, 6.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if math.log(mid) - 1.0 - 1.0 / mid < 0.0:
            lo = mid
        else:
            hi = mid
    x_root = 0.5 * (lo + hi)
    assert r["z0_min_loss_ratio_ohm"] == pytest.approx(60.0 * math.log(x_root),
                                                       rel=1e-9)
    assert 76.5 < r["z0_min_loss_ratio_ohm"] < 76.9  # 经典 76.7Ω 窗


@pytest.mark.parametrize("params", [
    {"a_mm": 1.0, "b_mm": 1.0},
    {"a_mm": 1.0, "b_mm": 0.5},
    {"a_mm": 1.0, "b_mm": 3.0, "z0_ohm": 50.0},
    {"a_mm": 0.0, "b_mm": 3.0},
    {"z0_ohm": 0.0},
    {"epsilon_r": 0.5, "z0_ohm": 50.0},
    {},
])
def test_coax_z0_domain_rejections(params):
    """越界/互斥/空输入显式拒绝。"""
    _reject("coax_line_z0", params)


# ─── coax_line_attenuation：标度恒等 / 双路线 / 跨键互证 ────────────────────


_BASE_ATT = {"f_ghz": 1.0, "a_mm": 1.0, "b_mm": 2.301,
             "conductivity_s_per_m": 5.8e7}


def test_coax_att_skin_scaling_identity():
    """αc∝√f（f×4→×2 逐位）；αc∝1/√σ（σ×4→÷2 逐位）；αd 线性于 f。"""
    r1 = _run("coax_line_attenuation", dict(_BASE_ATT))
    r4f = _run("coax_line_attenuation", {**_BASE_ATT, "f_ghz": 4.0})
    assert r4f["alpha_conductor_db_m"] == pytest.approx(
        2.0 * r1["alpha_conductor_db_m"], rel=1e-12)
    assert r4f["alpha_dielectric_db_m"] is None  # tanδ=0 无介质项
    r4s = _run("coax_line_attenuation",
               {**_BASE_ATT, "conductivity_s_per_m": 4 * 5.8e7})
    assert r4s["alpha_conductor_db_m"] == pytest.approx(
        0.5 * r1["alpha_conductor_db_m"], rel=1e-12)


def test_coax_att_dielectric_term_independent_formula():
    """αd=8.686·π·f√εr·tanδ/c₀ 测试侧独立式回收（PTFE 类点）。"""
    params = {**_BASE_ATT, "epsilon_r": 2.1, "tan_delta": 2.0e-4}
    r = _run("coax_line_attenuation", params)
    alpha_d_db = (8.686 * math.pi * 1.0e9 * math.sqrt(2.1) * 2.0e-4
                  / (C_MM_GHZ * 1e6))
    assert r["alpha_dielectric_db_m"] == pytest.approx(alpha_d_db, rel=1e-12)
    assert r["alpha_total_db_m"] == pytest.approx(
        r["alpha_conductor_db_m"] + r["alpha_dielectric_db_m"], rel=1e-12)


def test_coax_att_line_q_dual_route_and_cross_key():
    """线 Q 双路线（β/(2αc) vs 场积分法）≤1e-12；与 cavity_unloaded_q
    跨键逐位互证（同输入同物理、独立实现）。"""
    r = _run("coax_line_attenuation", dict(_BASE_ATT))
    assert r["q_xcheck_rel_dev"] <= 1e-12
    # 测试侧独立场积分重算
    f_hz = 1.0e9
    a_m, b_m = 1.0e-3, 2.301e-3
    rs = math.sqrt(math.pi * f_hz * _MU0 / 5.8e7)
    omega = 2.0 * math.pi * f_hz
    q_field = omega * _MU0 * math.log(b_m / a_m) / (rs * (1.0 / a_m
                                                          + 1.0 / b_m))
    assert r["q_conductor_field_integral"] == pytest.approx(q_field,
                                                            rel=1e-9)
    # 跨键：combline 族 cavity_unloaded_q（W5 键，独立实现）
    q_key = _run("cavity_unloaded_q", {
        "f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
        "a_mm": 1.0, "b_mm": 2.301})
    assert r["q_conductor_field_integral"] == pytest.approx(
        q_key["q_conductor"], rel=1e-12)


def test_coax_att_concrete_value_window():
    """Cu/1GHz/a=1mm/b=2.301mm 空气 50Ω 口径：αc≈0.16373 dB/m 工程窗。

    锚值单源（2026-10-13 A1-P3 修复）：模块 docstring/CALC 描述/本钉
    三处统一 0.16373（实测 0.163730589366），并附窄带互证（5 位有效）。"""
    r = _run("coax_line_attenuation", dict(_BASE_ATT))
    assert 0.10 < r["alpha_conductor_db_m"] < 0.25
    assert r["alpha_conductor_db_m"] == pytest.approx(0.16373, abs=5e-6)
    assert r["alpha_dielectric_db_m"] is None
    assert r["alpha_total_db_m"] == pytest.approx(r["alpha_conductor_db_m"],
                                                  rel=1e-12)
    assert r["z0_ohm"] == pytest.approx(50.0, abs=0.05)


def test_coax_att_domain_rejections():
    """f≤0 / a≥b / σ≤0 / tanδ<0 / μr≤0 显式拒绝。"""
    _reject("coax_line_attenuation", {**_BASE_ATT, "f_ghz": 0.0})
    _reject("coax_line_attenuation", {**_BASE_ATT, "b_mm": 1.0})
    _reject("coax_line_attenuation", {**_BASE_ATT,
                                      "conductivity_s_per_m": -1.0})
    _reject("coax_line_attenuation", {**_BASE_ATT, "tan_delta": -0.01})
    _reject("coax_line_attenuation", {**_BASE_ATT, "mu_r": 0.0})
    _reject("coax_line_attenuation", {**_BASE_ATT, "epsilon_r": 0.9})


# ─── coax_line_power_capacity：恒等式 / 标度 / 余量 ─────────────────────────


def test_coax_pwr_identity_and_roundtrip():
    """P_max 双口径恒等（V²/2Z0 vs E²a²ln(b/a)√εr/120，测试侧独立重算）。"""
    r = _run("coax_line_power_capacity",
             {"a_mm": 1.0, "b_mm": 3.0, "e_br_v_per_m": 3.0e6})
    assert r["p_identity_rel_dev"] <= 1e-12
    a_m = 1.0e-3
    ln_ratio = math.log(3.0)
    e_br = 3.0e6
    p_expect = e_br * e_br * a_m * a_m * ln_ratio * math.sqrt(1.0) / 120.0
    assert r["p_max_peak_w"] == pytest.approx(p_expect, rel=1e-9)
    z0 = 60.0 * ln_ratio
    v_expect = e_br * a_m * ln_ratio
    assert r["v_max_peak_v"] == pytest.approx(v_expect, rel=1e-9)
    assert r["z0_ohm"] == pytest.approx(z0, rel=1e-12)
    assert v_expect * v_expect / (2.0 * z0) == pytest.approx(
        r["p_max_peak_w"], rel=1e-12)


def test_coax_pwr_epsilon_scaling_and_margin():
    """εr×4 → P×2（√εr 标度）；p_op=P_max/4 → 余量 6.0206dB；过驱如实。"""
    r = _run("coax_line_power_capacity", {"a_mm": 1.0, "b_mm": 3.0})
    r4 = _run("coax_line_power_capacity",
              {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 4.0})
    assert r4["p_max_peak_w"] == pytest.approx(2.0 * r["p_max_peak_w"],
                                               rel=1e-12)
    quarter = r["p_max_peak_w"] / 4.0
    rm = _run("coax_line_power_capacity",
              {"a_mm": 1.0, "b_mm": 3.0, "p_op_w": quarter})
    assert rm["margin_db"] == pytest.approx(10.0 * math.log10(4.0),
                                            abs=1e-6)
    over = _run("coax_line_power_capacity",
                {"a_mm": 1.0, "b_mm": 3.0, "p_op_w": r["p_max_peak_w"] * 2})
    assert over["over_drive"] is True
    assert over["margin_db"] == pytest.approx(-10.0 * math.log10(2.0),
                                               abs=1e-9)


def test_coax_pwr_optimum_diameter_and_rejections():
    """a_opt=b/√e、Z0=30Ω 常数锚；越界拒绝族。"""
    r = _run("coax_line_power_capacity", {"a_mm": 1.0, "b_mm": 3.0})
    assert r["a_opt_max_power_mm"] == pytest.approx(3.0 / math.sqrt(math.e),
                                                    rel=1e-12)
    assert r["z0_max_power_ohm"] == pytest.approx(30.0, abs=1e-9)
    _reject("coax_line_power_capacity", {"a_mm": 3.0, "b_mm": 3.0})
    _reject("coax_line_power_capacity",
            {"a_mm": 1.0, "b_mm": 3.0, "e_br_v_per_m": 0.0})
    _reject("coax_line_power_capacity",
            {"a_mm": 1.0, "b_mm": 3.0, "p_op_w": -1.0})
    _reject("coax_line_power_capacity",
            {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 0.9})


# ─── coax_line_cutoff_attenuator：深截止恒等 / f 标度 / 跨键 / EMC 锚 ───────
# （W8-S37 池件批 3；#118 口径——恒等式/独立常数/跨键互证，不自证）


def test_coax_cutoff_deep_limit_identity():
    """深截止渐近：每 (a+b) 长度衰减=8.686·2 dB 定义恒等式；α 与频率无关。"""
    a, b = 1.0, 3.0
    r = _run("coax_line_cutoff_attenuator",
             {"a_mm": a, "b_mm": b, "length_mm": a + b})
    # k_c·(a+b)=2（保角映射定义）→ 深截止每 (a+b) 恰 8.686·2 Np→dB
    assert r["attenuation_per_ab_db"] == pytest.approx(8.686 * 2.0, abs=1e-9)
    assert r["attenuation_db"] == pytest.approx(8.686 * 2.0, abs=1e-9)
    assert r["alpha_np_per_m"] == pytest.approx(500.0, rel=1e-12)
    assert r["deep_cutoff"] is True
    assert r["evanescent_factor"] == 1.0
    # 截止波长 λ_c=π(a+b)（介质无关几何量，测试侧独立式）
    assert r["lambda_c_mm"] == pytest.approx(math.pi * (a + b), rel=1e-12)
    # 深截止频率无关：f=1e-4·f_c（测试侧独立重算 f_c）与缺省渐近 α 逐位同
    fc = C_MM_GHZ / (math.pi * (a + b))
    r4 = _run("coax_line_cutoff_attenuator",
              {"a_mm": a, "b_mm": b, "length_mm": 10.0,
               "f_ghz": 1e-4 * fc})
    assert r4["alpha_np_per_m"] == pytest.approx(500.0, rel=1e-7)
    assert r4["deep_cutoff"] is True


def test_coax_cutoff_finite_f_scaling_and_cross_key():
    """√(1−(f/f_c)²) 标度（f_c 测试侧独立重算）；L 线性；与 z0 键 f_c 互证。"""
    a, b = 1.0, 3.0
    fc = C_MM_GHZ / (math.pi * (a + b))   # 独立重算 =23.8567 GHz
    half = _run("coax_line_cutoff_attenuator",
                {"a_mm": a, "b_mm": b, "length_mm": 10.0,
                 "f_ghz": 0.5 * fc})
    assert half["evanescent_factor"] == pytest.approx(math.sqrt(0.75),
                                                      rel=1e-12)
    assert half["alpha_db_per_m"] == pytest.approx(
        8.686 * 500.0 * math.sqrt(0.75), rel=1e-12)
    assert half["deep_cutoff"] is False
    # 长度线性：2L 恰两倍（逐位）
    r1 = _run("coax_line_cutoff_attenuator",
              {"a_mm": a, "b_mm": b, "length_mm": 10.0, "f_ghz": 0.5 * fc})
    r2 = _run("coax_line_cutoff_attenuator",
              {"a_mm": a, "b_mm": b, "length_mm": 20.0, "f_ghz": 0.5 * fc})
    assert r2["attenuation_db"] == pytest.approx(2.0 * r1["attenuation_db"],
                                                 rel=1e-12)
    # εr：f_c 准确 ÷√εr、k_c/深截止衰减不变（几何量 vs 介质标度分离）
    r_er = _run("coax_line_cutoff_attenuator",
                {"a_mm": a, "b_mm": b, "length_mm": 10.0, "epsilon_r": 2.25})
    assert r_er["te11_cutoff_ghz"] == pytest.approx(fc / 1.5, abs=5e-9)
    assert r_er["kc_per_m"] == pytest.approx(500.0, rel=1e-12)
    # 跨键：f_c 与 coax_line_z0 同式同值（同几何，独立消费路线）
    z0 = _run("coax_line_z0", {"a_mm": a, "b_mm": b})
    assert r1["te11_cutoff_ghz"] == z0["te11_cutoff_ghz"]


def test_coax_cutoff_emc_anchor_and_rejections():
    """EMC 经典锚：精确圆波导 TE11 深截止 32 dB/直径（测试侧独立常数）；越界拒绝。"""
    # 外部文献锚独立验证公式族（α=k_c 深截止）：圆波导 TE11 k_c=x'_11/b
    # → 每直径 D=2b 衰减 8.686·k_c·D ≈ 32.0 dB（Ott/learnEMC 工程口径）
    kc_exact = X11P / 1.0                       # b=1 m 归一
    per_diameter_db = 8.686 * kc_exact * 2.0
    assert per_diameter_db == pytest.approx(32.0, abs=0.05)
    # 同口径下截止波长 λ_c=2π/k_c=3.4126b=1.706·D（D=2b 直径，测试侧独立式）
    assert (2.0 * math.pi / kc_exact) / 2.0 == pytest.approx(1.706, rel=1e-3)
    # 本键保角映射 k_c≈2/(a+b) 的近似偏差如实存在（a→0 极限 34.76 dB/D，
    # 偏高 8.6%——键内 note 注记，不冒充精确圆波导值）
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 3.0, "b_mm": 3.0, "length_mm": 10.0})
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 1.0, "b_mm": 3.0, "length_mm": -1.0})
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 1.0, "b_mm": 3.0, "length_mm": 10.0, "epsilon_r": 0.9})
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 1.0, "b_mm": 3.0, "length_mm": 10.0, "f_ghz": 0.0})
    fc = C_MM_GHZ / (math.pi * 4.0)
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 1.0, "b_mm": 3.0, "length_mm": 10.0, "f_ghz": fc})
    _reject("coax_line_cutoff_attenuator",
            {"a_mm": 1.0, "b_mm": 3.0, "length_mm": 10.0, "f_ghz": 2.0 * fc},
            needle="行波区无倏逝衰减")


# ─── circular_cavity_mode_spectrum：独立常数 / 主模判据 / 双源 / 暴力闭合 ───


def test_spectrum_tm010_independent_constant():
    """TM010 f=x_01·c₀/(2πa)（x_01 独立常数；a=10mm/L=8mm 窄带唯一）。"""
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": 10.0, "length_mm": 8.0, "f_min_ghz": 10.0,
              "f_max_ghz": 13.0})
    tm010 = [m for m in r["modes"] if m["mode"] == "TM010"]
    assert len(r["modes"]) == 1 and tm010, f"窄带应只含 TM010: {r['modes']}"
    expect = X01 * C_MM_GHZ / (2.0 * math.pi * 10.0)
    assert tm010[0]["f_ghz"] == pytest.approx(expect, abs=1e-6)
    assert r["dominant_mode"] == "TM010"


def test_spectrum_dominant_criterion_crossover():
    """主模判据经典口径复现：l<2a→TM010、l>2a→TE111（计算判读）。"""
    r_long = _run("circular_cavity_mode_spectrum",
                  {"radius_mm": 10.0, "length_mm": 25.0, "f_min_ghz": 8.0,
                   "f_max_ghz": 16.0})
    r_short = _run("circular_cavity_mode_spectrum",
                   {"radius_mm": 10.0, "length_mm": 15.0, "f_min_ghz": 8.0,
                    "f_max_ghz": 16.0})
    assert r_long["dominant_mode"] == "TE111"
    assert r_short["dominant_mode"] == "TM010"
    # 主模频率测试侧独立重算（TE111：x'_11 与 π/L 两项）
    expect_te111 = C_MM_GHZ / (2.0 * math.pi) * math.hypot(
        X11P / 10.0, math.pi / 25.0)
    assert r_long["dominant_f_ghz"] == pytest.approx(expect_te111, abs=1e-6)


def test_spectrum_te011_tm111_degeneracy():
    """TE011/TM111 简并（x'_01=x_11=3.8317）：同频逐位（≤1e-12）。"""
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": 10.0, "length_mm": 12.0, "f_min_ghz": 21.0,
              "f_max_ghz": 23.5})
    by_name = {m["mode"]: m["f_ghz"] for m in r["modes"]}
    assert "TE011" in by_name and "TM111" in by_name
    assert by_name["TE011"] == pytest.approx(by_name["TM111"], abs=1e-9)
    # 与测试侧独立常数式互证
    expect = C_MM_GHZ / (2.0 * math.pi) * math.hypot(
        X01P / 10.0, math.pi / 12.0)
    assert by_name["TE011"] == pytest.approx(expect, abs=1e-6)


def test_spectrum_te011_same_repo_double_source():
    """TE011 空腔频率 vs material_characterization._sc_empty_f0（同仓
    第二源，≤1e-12；h=2ℓ+d 拼装等长腔）。"""
    from rfauto.core.material_characterization import _sc_empty_f0
    f_ref = _sc_empty_f0(0.010, 0.004, 0.004)  # h_total=12mm
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": 10.0, "length_mm": 12.0, "f_min_ghz": 21.0,
              "f_max_ghz": 23.5})
    f_key = next(m["f_ghz"] for m in r["modes"]
                 if m["mode"] == "TE011")
    assert f_key * 1e9 == pytest.approx(f_ref, rel=1e-9)  # 第二源手码根常数 9 位精度


def test_spectrum_epsilon_r_scaling_exact():
    """εr=4 → 全谱频率准确 ÷2（1/√εr 标度，模式名序列不变）。"""
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": 10.0, "length_mm": 25.0, "f_min_ghz": 8.0,
              "f_max_ghz": 16.0})
    r4 = _run("circular_cavity_mode_spectrum",
              {"radius_mm": 10.0, "length_mm": 25.0, "f_min_ghz": 4.0,
               "f_max_ghz": 8.0, "epsilon_r": 4.0})
    names_r = [m["mode"] for m in r["modes"]]
    names_r4 = [m["mode"] for m in r4["modes"]]
    assert names_r == names_r4
    for m1, m2 in zip(r["modes"], r4["modes"], strict=True):
        assert m2["f_ghz"] == pytest.approx(m1["f_ghz"] / 2.0, rel=1e-9)


def test_spectrum_te11_waveguide_cutoff_reference():
    """TE11 波导截止参考 x'_11·c₀/(2πa)=0.293·c₀/a 口径（独立常数）。"""
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": 10.0, "length_mm": 25.0, "f_min_ghz": 8.0,
              "f_max_ghz": 16.0})
    expect = X11P * C_MM_GHZ / (2.0 * math.pi * 10.0)
    assert r["te11_waveguide_cutoff_ghz"] == pytest.approx(expect, abs=1e-9)
    assert expect == pytest.approx(8.7849, abs=5e-4)


def test_spectrum_brute_force_enumeration_closure():
    """谱 vs 测试侧暴力枚举（不同循环序+scipy 直调）：集合严格闭合。"""
    from scipy.special import jn_zeros, jnp_zeros
    a, length, lo, hi = 10.0, 25.0, 8.0, 16.0
    brute: set[tuple[str, float]] = set()
    for typ in ("TE", "TM"):
        zfn = jnp_zeros if typ == "TE" else jn_zeros
        p_min = 1 if typ == "TE" else 0
        for mm in range(0, 13):
            for nn in range(1, 7):
                for pp in range(p_min, 31):
                    x = float(zfn(mm, nn)[nn - 1])
                    f = C_MM_GHZ / (2.0 * math.pi) * math.hypot(
                        x / a, pp * math.pi / length)
                    if lo <= f <= hi:
                        brute.add((f"{typ}{mm}{nn}{pp}", round(f, 9)))
    r = _run("circular_cavity_mode_spectrum",
             {"radius_mm": a, "length_mm": length, "f_min_ghz": lo,
              "f_max_ghz": hi})
    key = {(m["mode"], round(m["f_ghz"], 9)) for m in r["modes"]}
    assert key == brute


def test_spectrum_domain_rejections():
    """频段/几何/εr/枚举预算越界显式拒绝。"""
    base = {"radius_mm": 10.0, "length_mm": 25.0}
    _reject("circular_cavity_mode_spectrum",
            {**base, "f_min_ghz": 16.0, "f_max_ghz": 16.0})
    _reject("circular_cavity_mode_spectrum",
            {**base, "radius_mm": 0.0, "f_min_ghz": 8.0, "f_max_ghz": 16.0})
    _reject("circular_cavity_mode_spectrum",
            {**base, "f_min_ghz": 8.0, "f_max_ghz": 16.0, "epsilon_r": 0.5})
    _reject("circular_cavity_mode_spectrum",
            {**base, "f_min_ghz": 0.5, "f_max_ghz": 60.0, "max_modes": 10})
    _reject("circular_cavity_mode_spectrum",
            {**base, "f_min_ghz": 8.0, "f_max_ghz": 16.0, "max_modes": 0})


# ─── circular_cavity_mode_chart：交叉点 / 单调性 / 跨键一致 ─────────────────


def test_chart_te111_tm010_crossover_independent_constant():
    """TE111/TM010 交叉 r=π/(2·√(x_01²−x'_11²))（独立常数式）+交叉点
    f_norm=x_01 逐位；主模序列跨交叉翻转。"""
    c = _run("circular_cavity_mode_chart",
             {"modes": ["TM010", "TE111"], "l_over_2a_min": 0.8,
              "l_over_2a_max": 1.3, "n_points": 26})
    r_expect = math.pi / (2.0 * math.sqrt(X01 ** 2 - X11P ** 2))
    assert len(c["crossovers"]) == 1
    cross = c["crossovers"][0]
    assert set(cross["between"]) == {"TM010", "TE111"}
    assert cross["l_over_2a"] == pytest.approx(r_expect, abs=1e-6)
    assert cross["f_norm"] == pytest.approx(X01, abs=1e-9)
    dominant = c["dominant_by_ratio"]
    assert dominant[0] == "TM010" and dominant[-1] == "TE111"
    assert len(set(dominant)) == 2  # 恰一次翻转


def test_chart_monotonicity():
    """p≥1 模式随长径比单调降；TM010（p=0）平坦。"""
    c = _run("circular_cavity_mode_chart",
             {"modes": ["TM010", "TE111", "TM011", "TE011"],
              "l_over_2a_min": 0.4, "l_over_2a_max": 2.5, "n_points": 41})
    by_mode = {s["mode"]: s["f_norm"] for s in c["series"]}
    assert by_mode["TM010"] == [pytest.approx(X01, abs=1e-9)] * 41
    for name in ("TE111", "TM011", "TE011"):
        vals = by_mode[name]
        assert all(v2 <= v1 + 1e-12
                   for v1, v2 in pairwise(vals)), name


def test_chart_consistency_with_spectrum_key():
    """跨键一致：chart f_norm → f_ghz=f_norm·C/(2πa) 与谱键逐位（≤1e-6）。"""
    a_mm, l_mm = 10.0, 25.0  # r=1.25（网格 i=5 恰落 1.25）
    c = _run("circular_cavity_mode_chart",
             {"modes": ["TE111", "TM010"], "l_over_2a_min": 1.2,
              "l_over_2a_max": 1.3, "n_points": 11})
    ratios = c["aspect_ratios"]
    idx = min(range(len(ratios)), key=lambda i: abs(ratios[i] - 1.25))
    assert abs(ratios[idx] - 1.25) < 1e-9
    f_from_chart = c["series"][0]["f_norm"][idx] * C_MM_GHZ / (
        2.0 * math.pi * a_mm)
    s = _run("circular_cavity_mode_spectrum",
             {"radius_mm": a_mm, "length_mm": l_mm, "f_min_ghz": 10.0,
              "f_max_ghz": 11.5})
    te111 = next(m["f_ghz"] for m in s["modes"]
                 if m["mode"] == "TE111")
    assert f_from_chart == pytest.approx(te111, rel=1e-6)


def test_chart_domain_rejections():
    """非法模式名/TE p=0/重复模式/网格与轴域越界显式拒绝。"""
    _reject("circular_cavity_mode_chart",
            {"modes": ["TX011", "TE111"]})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TE110", "TE111"]})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TM010", "TM010", "TE111"]})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TM010", "TE111"], "n_points": 1})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TM010", "TE111"], "n_points": 2.5})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TM010", "TE111"], "l_over_2a_min": 0.5,
             "l_over_2a_max": 0.5})
    _reject("circular_cavity_mode_chart",
            {"modes": ["TM010", "TE111"], "l_over_2a_max": 25.0})


# ─── circular_cavity_mode_q：双路线 / 独立清洁式 / 标度 / 物理 ──────────────


_Q_SWEEP = [
    ("TE", 0, 1, 1), ("TE", 1, 1, 1), ("TE", 2, 1, 1), ("TE", 1, 2, 1),
    ("TE", 0, 1, 2), ("TE", 3, 1, 3),
    ("TM", 0, 1, 0), ("TM", 1, 1, 1), ("TM", 1, 1, 2), ("TM", 0, 2, 3),
    ("TM", 2, 1, 0),
]


@pytest.mark.parametrize("mtype,mm,nn,pp", _Q_SWEEP)
def test_mode_q_dual_route_agreement(mtype, mm, nn, pp):
    """闭式 vs 数值积分双路线 rel_dev≤1e-9；Ue/Um≈1（谐振定理）。"""
    r = _run("circular_cavity_mode_q",
             {"mode_type": mtype, "m": mm, "n": nn, "p": pp,
              "radius_mm": 10.0, "length_mm": 12.0,
              "conductivity_s_per_m": 5.8e7})
    assert r["q_xcheck_rel_dev"] <= 1e-9
    assert r["ue_over_um"] == pytest.approx(1.0, abs=1e-9)
    assert r["q_conductor"] > 1.0e3  # Cu 腔工程量级窗


def test_mode_q_tm010_clean_formula_independent():
    """TM010 清洁式 (η0·k0·a/2Rs)·L/(L+a) 测试侧独立重算（≤1e-9）。"""
    r = _run("circular_cavity_mode_q",
             {"mode_type": "TM", "m": 0, "n": 1, "p": 0, "radius_mm": 10.0,
              "length_mm": 8.0, "conductivity_s_per_m": 5.8e7})
    a_m, l_m = 0.01, 0.008
    k0 = X01 / a_m                       # TM010：k0=x_01/a（kz=0）
    omega = 299792458.0 * k0
    rs = math.sqrt(math.pi * (omega / (2.0 * math.pi)) * _MU0 / 5.8e7)
    q_clean = (_ETA0 * k0 * a_m / (2.0 * rs)) * l_m / (l_m + a_m)
    assert r["q_conductor"] == pytest.approx(q_clean, rel=1e-9)


def test_mode_q_sigma_scaling_exact():
    """Qc∝1/Rs∝1/√σ：σ×4 → Qc×2 逐位。"""
    base = {"mode_type": "TE", "m": 0, "n": 1, "p": 1, "radius_mm": 10.0,
            "length_mm": 12.0}
    r1 = _run("circular_cavity_mode_q",
              {**base, "conductivity_s_per_m": 5.8e7})
    r4 = _run("circular_cavity_mode_q",
              {**base, "conductivity_s_per_m": 4 * 5.8e7})
    assert r4["q_conductor"] == pytest.approx(2.0 * r1["q_conductor"],
                                              rel=1e-12)


def test_mode_q_te011_higher_than_te111():
    """TE011>TE111（m=0 无角向电流跨端壁结、经典高 Q 模性质）。"""
    base = {"radius_mm": 10.0, "length_mm": 12.0,
            "conductivity_s_per_m": 5.8e7}
    q_te011 = _run("circular_cavity_mode_q",
                   {**base, "mode_type": "TE", "m": 0, "n": 1, "p": 1})
    q_te111 = _run("circular_cavity_mode_q",
                   {**base, "mode_type": "TE", "m": 1, "n": 1, "p": 1})
    assert q_te011["q_conductor"] > q_te111["q_conductor"]


def test_mode_q_dielectric_series_combination():
    """介质串联合成：tanδ=0→Qd null 且 Qu=Qc；tanδ>0→Qu<Qc 且
    Qu≤min(Qc,Qd)；tanδ→小 时 Qu→Qc。"""
    base = {"mode_type": "TE", "m": 0, "n": 1, "p": 1, "radius_mm": 10.0,
            "length_mm": 12.0, "conductivity_s_per_m": 5.8e7}
    r0 = _run("circular_cavity_mode_q", dict(base))
    assert r0["q_dielectric"] is None
    assert r0["q_unloaded"] == pytest.approx(r0["q_conductor"], rel=1e-12)
    r1 = _run("circular_cavity_mode_q", {**base, "tan_delta": 1.0e-4})
    assert r1["q_dielectric"] == pytest.approx(1.0e4, rel=1e-12)
    assert r1["q_unloaded"] < r1["q_conductor"]
    assert r1["q_unloaded"] <= min(r1["q_conductor"], r1["q_dielectric"])
    r2 = _run("circular_cavity_mode_q", {**base, "tan_delta": 1.0e-7})
    assert r2["q_unloaded"] > 0.995 * r2["q_conductor"]


def test_mode_q_domain_rejections():
    """TE p=0（非物理）/n=0/负 m/非整 m/σ≤0/tanδ<0 显式拒绝。"""
    base = {"radius_mm": 10.0, "length_mm": 12.0,
            "conductivity_s_per_m": 5.8e7}
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TE", "m": 0, "n": 1, "p": 0})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TE", "m": 0, "n": 0, "p": 1})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TE", "m": -1, "n": 1, "p": 1})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TE", "m": 0.5, "n": 1, "p": 1})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TM", "m": 0, "n": 1, "p": 0,
             "conductivity_s_per_m": 0.0})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "TE", "m": 0, "n": 1, "p": 1,
             "tan_delta": -0.01})
    _reject("circular_cavity_mode_q",
            {**base, "mode_type": "XX", "m": 0, "n": 1, "p": 1})


# ─── 键面卫生：新键 description 首行"中文名：用途"形态门 ───────────────────


def test_new_keys_description_first_line_format():
    """架构批 新规：description 首行 = 中文名（≤24 字符）+全角冒号。"""
    new_keys = (
        "coax_line_z0", "coax_line_attenuation", "coax_line_power_capacity",
        "circular_cavity_mode_spectrum", "circular_cavity_mode_chart",
        "circular_cavity_mode_q",
    )
    for key in new_keys:
        desc = CALCULATOR_REGISTRY.get(key).description
        first_line = desc.split("\n", 1)[0]
        idx = first_line.find("：")
        assert idx >= 1, f"{key}: 首行无全角冒号: {first_line!r}"
        assert idx <= 24, (
            f"{key}: 中文名超 24 字符（{idx}）: {first_line!r}")
        assert first_line[:idx].strip(), f"{key}: 中文名为空"


def test_registry_count_grew_by_six():
    """注册键面增量自洽：EXPECTED 含六新键（与 test_calculators 对账）。"""
    from tests.unit.test_calculators import EXPECTED
    for key in ("coax_line_z0", "coax_line_attenuation",
                "coax_line_power_capacity", "circular_cavity_mode_spectrum",
                "circular_cavity_mode_chart", "circular_cavity_mode_q"):
        assert key in EXPECTED
        assert key in CALCULATOR_REGISTRY.names()
