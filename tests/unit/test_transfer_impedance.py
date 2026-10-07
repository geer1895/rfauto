"""EM-4 电缆转移阻抗单测（实体屏蔽 Vance 式，2026-10-02）。

锚树口径（#118 教训：锚值独立复算/独立公式，不赌推导）：
- DC 极限（规格验收锚一）：Zt(0)=1/(2πaσt) 解析恒等直算；f→低频端
  与小 u 级数 1−x²/6+7x⁴/360 的独立裁判路残差 ≤1e-12（内核 sinh 路
  vs 测试级数路，两路不同源）。
- 高频 √f 恒等（规格验收锚二）：渐近式 |Zt_hf|=√(ωμσ)e^{-t/δ}/(πaσ)
  的实数独立式与 cmath 式互证 ≤1e-12；折叠指数因子后
  S(f)=20lg|Zt_hf|+8.686·t/δ 对十倍频严格 +10.0 dB（残差 ≤1e-9，
  开发期实测 ≤3.4e-13）。
- 渐近误差下一阶恰为 e^{-2γt}（残差 |ratio−1−e^{-2x}|=e^{-4t/δ}）：
  t/δ=2.5/3/3.5 三点开发期实测 4.5e-5/6.2e-6/8.3e-7，按 2e^{-4u} 钉。
- 单调性物理结论：实体管 |Zt(f)| 自 R_dc 单调不增（小 u 展开实部
  1−0.0222u⁴ 已负）——"高频抬升"是编织体 jωM 行为，实体管无此项。
- 耦合电感项：jωM 手算值回收（M=1e-9 H/m @1MHz → j6.2831853e-3）；
  M=None 时 zt_total 与 zt_diffusion 逐键相等；Kley 暂缓如实标注。
- 溢出守卫：cmath.sinh 在 u≈3.4e4 必炸（开发期实测 OverflowError），
  u>350 分支返回渐近式且与渐近函数逐位相等。
"""
from __future__ import annotations

import cmath
import json
import math

import pytest

from rfauto.core import transfer_impedance as ti
from rfauto.core.transfer_impedance import (
    inductive_leakage_term,
    transfer_impedance,
    transfer_impedance_dc,
    zt_solid_tube,
    zt_solid_tube_hf_asymptote,
)

_MU0 = 4e-7 * math.pi
_SIGMA_CU = 5.8e7
_A_MM = 2.0e-3  # 屏蔽体平均半径 2 mm
_T_MM = 0.5e-3  # 壁厚 0.5 mm


def _f_of_u(u: float, t: float, sigma: float, mu_r: float = 1.0) -> float:
    """u=t/δ 的频率反演（测试独立推导：δ=t/u ⇒ f=u²/(πμσt²)）。"""
    return u * u / (math.pi * _MU0 * mu_r * sigma * t * t)


def _zt_ref(f_hz: float, a: float, t: float, sigma: float,
            mu_r: float = 1.0) -> complex:
    """独立复算精确薄壁式（与内核同式、测试内独立书写，EM-1 惯例）。"""
    u = t / math.sqrt(2.0 / (2.0 * math.pi * f_hz * _MU0 * mu_r * sigma))
    x = (1.0 + 1j) * u
    return (1.0 / (2.0 * math.pi * a * sigma * t)) * x / cmath.sinh(x)


# ─── DC 极限解析锚（规格验收锚一）──────────────────────────────────────────

@pytest.mark.parametrize("sigma", [5.8e7, 3.5e7, 1.5e7, 1.0e7])
def test_dc_limit_closed_form(sigma):
    """Zt(0)=1/(2πaσt) 直算恒等（铜/铝/黄铜/钢四材料；DC 式与 μr 无关，
    μr 只进交流扩散式，由 low-f 级数锚与全频域单式承担）。"""
    rdc = transfer_impedance_dc(_A_MM, _T_MM, sigma)
    assert rdc == pytest.approx(1.0 / (2.0 * math.pi * _A_MM * sigma * _T_MM),
                                rel=1e-15)
    assert rdc > 0.0


def test_dc_limit_mu_r_independence_low_frequency():
    """低频极限与 μr 无关（DC 式语义）：f=0.01 Hz 钢 μr=100 与 μr=1 的
    Zt 之比 →1（μr 只重排 u=t/δ 的频率刻度，低频端两者都趋 1）。"""
    f = 0.01
    z_mu1 = zt_solid_tube(f, _A_MM, _T_MM, conductivity_s_per_m=1.0e7,
                          mu_r=1.0)
    z_mu100 = zt_solid_tube(f, _A_MM, _T_MM, conductivity_s_per_m=1.0e7,
                            mu_r=100.0)
    rdc = 1.0 / (2.0 * math.pi * _A_MM * 1.0e7 * _T_MM)
    assert abs(z_mu1) / rdc == pytest.approx(1.0, rel=1e-9)
    assert abs(z_mu100) / rdc == pytest.approx(1.0, rel=1e-9)


def test_dc_continuity_series_independent_path():
    """低频端与级数 1−x²/6+7x⁴/360 独立裁判路互证（残差 ≤1e-12）。

    f=0.01 Hz 铜管 u=7.57e-4：内核走 cmath.sinh、裁判走截断级数，
    两路不同源；截断误差阶 O(x⁶)≈u⁶/1e5 量级，1e-12 门宽裕。
    """
    f = 0.01
    u = _T_MM / math.sqrt(2.0 / (2.0 * math.pi * f * _MU0 * _SIGMA_CU))
    x = (1.0 + 1j) * u
    series = 1.0 - x * x / 6.0 + 7.0 * x ** 4 / 360.0
    zt = zt_solid_tube(f, _A_MM, _T_MM, conductivity_s_per_m=_SIGMA_CU)
    rdc = 1.0 / (2.0 * math.pi * _A_MM * _SIGMA_CU * _T_MM)
    assert abs(zt / rdc - series) <= 1e-12
    # DC 门面值与低频极限衔接（|Zt|→R_dc，相对差 ≤ 级数首阶 2u²/6·1.01）
    assert abs(zt) / rdc == pytest.approx(1.0, abs=(2.0 * u * u / 6.0) * 1.01)


# ─── 高频 √f 恒等（规格验收锚二）──────────────────────────────────────────

def test_hf_asymptote_real_form_cross_check():
    """|Zt_hf| 的实数独立式 √(ωμσ)e^{-t/δ}/(πaσ) 与 cmath 式互证。"""
    for u in (1.5, 3.0, 6.0):
        f = _f_of_u(u, _T_MM, _SIGMA_CU)
        z = zt_solid_tube_hf_asymptote(f, _A_MM, _T_MM,
                                       conductivity_s_per_m=_SIGMA_CU)
        w = 2.0 * math.pi * f
        ref = math.sqrt(w * _MU0 * _SIGMA_CU) * math.exp(-u) / (
            math.pi * _A_MM * _SIGMA_CU)
        assert abs(z) / ref == pytest.approx(1.0, rel=1e-12)


@pytest.mark.parametrize("f0", [1.0e4, 1.0e6, 1.0e8])
def test_sqrt_f_identity_per_decade(f0):
    """√f 恒等：S(f)=20lg|Zt_hf|+8.686·t/δ 对十倍频严格 +10.0 dB。

    折叠掉已知的指数因子 e^{-t/δ}（∝√f 同源于 δ）后，|Zt_h|∝√f
    是精确恒等（规格验收锚二的解析形式），残差只余浮点（实测 ≤3.4e-13）。
    """
    t = _T_MM

    def s_of(f: float) -> float:
        u = t / math.sqrt(2.0 / (2.0 * math.pi * f * _MU0 * _SIGMA_CU))
        z = zt_solid_tube_hf_asymptote(f, _A_MM, t,
                                       conductivity_s_per_m=_SIGMA_CU)
        return 20.0 * math.log10(abs(z)) + (20.0 / math.log(10.0)) * u

    assert s_of(10.0 * f0) - s_of(f0) == pytest.approx(10.0, abs=1e-9)


@pytest.mark.parametrize("u", [2.5, 3.0, 3.5])
def test_hf_asymptote_next_term_error(u):
    """精确式/渐近式之比 −1 −e^{-2x} 的残差恰为下一阶 e^{-4u}（×2 门）。"""
    f = _f_of_u(u, _T_MM, _SIGMA_CU)
    x = (1.0 + 1j) * u
    z_exact = zt_solid_tube(f, _A_MM, _T_MM, conductivity_s_per_m=_SIGMA_CU)
    z_asm = zt_solid_tube_hf_asymptote(f, _A_MM, _T_MM,
                                       conductivity_s_per_m=_SIGMA_CU)
    resid = abs(z_exact / z_asm - 1.0 - cmath.exp(-2.0 * x))
    assert resid <= 2.0 * math.exp(-4.0 * u)


def test_exact_matches_reference_and_merges_to_dc():
    """全频域单式 vs 独立复算路逐点一致；|Zt| 绝对值单调不增（实体管）。"""
    rdc = 1.0 / (2.0 * math.pi * _A_MM * _SIGMA_CU * _T_MM)
    prev_abs = math.inf
    for k in range(120):
        u = 0.02 + (10.0 - 0.02) * k / 119.0
        f = _f_of_u(u, _T_MM, _SIGMA_CU)
        z = zt_solid_tube(f, _A_MM, _T_MM, conductivity_s_per_m=_SIGMA_CU)
        assert z == pytest.approx(
            _zt_ref(f, _A_MM, _T_MM, _SIGMA_CU), rel=1e-12, abs=0.0)
        assert abs(z) <= prev_abs  # 单调不增（u⁴ 展开实部已负，物理结论）
        prev_abs = abs(z)
    assert prev_abs < rdc  # u=10 深趋肤：已显著低于 DC 值


# ─── 耦合电感项与 Kley 暂缓口径 ────────────────────────────────────────────

def test_inductive_leakage_hand_value_recovery():
    """jωM 手算回收：M=1e-9 H/m @1 MHz → j·2π·1e6·1e-9 = j6.2831853e-3。"""
    z = inductive_leakage_term(1.0e6, 1.0e-9)
    assert z.real == pytest.approx(0.0, abs=1e-18)
    assert z.imag == pytest.approx(2.0 * math.pi * 1.0e6 * 1.0e-9, rel=1e-15)


def test_facade_without_m_total_equals_diffusion():
    """M=None（纯实体屏蔽）：zt_total 与 zt_diffusion 逐键逐位相等。"""
    r = transfer_impedance(
        f_axis_hz=[1.0e4, 1.0e6, 1.0e8], radius_m=_A_MM, thickness_m=_T_MM,
        conductivity_s_per_m=_SIGMA_CU)
    assert r["zt_inductive_re"] is None and r["zt_inductive_im"] is None
    assert r["zt_total_abs"] == r["zt_diffusion_abs"]
    assert r["zt_total_db"] == r["zt_diffusion_db"]
    assert r["zt_total_phase_deg"] == r["zt_diffusion_phase_deg"]
    assert "暂缓" in r["note"] and "Kley" in r["note"]


def test_facade_with_m_superposition_recovery():
    """Zt_total=Zt_diffusion+jωM 叠加回收（M 外部给定口径）。"""
    m_h = 2.0e-9
    f = 1.0e7
    r = transfer_impedance(
        frequency_hz=f, radius_m=_A_MM, thickness_m=_T_MM,
        conductivity_s_per_m=_SIGMA_CU, coupling_inductance_h_per_m=m_h)
    z_d = complex(r["zt_diffusion_re"][0], r["zt_diffusion_im"][0])
    z_i = complex(r["zt_inductive_re"][0], r["zt_inductive_im"][0])
    assert z_i == pytest.approx(1j * 2.0 * math.pi * f * m_h, rel=1e-12)
    assert abs(complex(r["zt_total_abs"][0], 0.0)) == pytest.approx(
        abs(z_d + z_i), rel=1e-12)


# ─── 溢出守卫（cmath.sinh 溢出分支）────────────────────────────────────────

def test_deep_skin_branch_no_overflow_and_equals_asymptote():
    """u=400（>350 分支）：不抛 OverflowError，与渐近函数逐位相等。"""
    f = _f_of_u(400.0, 1.0e-3, _SIGMA_CU)
    z_branch = zt_solid_tube(f, _A_MM, 1.0e-3, conductivity_s_per_m=_SIGMA_CU)
    z_asm = zt_solid_tube_hf_asymptote(f, _A_MM, 1.0e-3,
                                       conductivity_s_per_m=_SIGMA_CU)
    assert math.isfinite(abs(z_branch))
    assert z_branch == z_asm  # 分支走同一渐近表达式，逐位重合


def test_ultra_high_frequency_underflow_to_zero():
    """u≈3.4e4（5 THz 铜管 1 mm）：e^{-u} 下溢为 0，返回有限零值不炸。"""
    z = zt_solid_tube(5.0e12, _A_MM, 1.0e-3, conductivity_s_per_m=_SIGMA_CU)
    assert math.isfinite(abs(z))
    assert abs(z) < 1e-200


# ─── 门面 dict / 材料表 / JSON 可序列化 ────────────────────────────────────

def test_facade_keys_and_json_roundtrip():
    r = transfer_impedance(
        frequency_hz=1.0e6, radius_m=_A_MM, thickness_m=_T_MM,
        conductivity_s_per_m=_SIGMA_CU)
    for key in ("f_hz", "t_over_delta", "zt_dc_ohm_per_m",
                "zt_diffusion_re", "zt_diffusion_im", "zt_diffusion_abs",
                "zt_diffusion_db", "zt_diffusion_phase_deg",
                "zt_hf_asymptote_abs", "zt_inductive_re", "zt_total_abs",
                "zt_total_db", "zt_total_phase_deg", "conductivity_s_per_m",
                "mu_r", "material", "coupling_inductance_h_per_m", "note"):
        assert key in r
    assert json.dumps(r, ensure_ascii=False)  # JSON 可序列化


def test_material_table_equivalence_and_dc_consistency():
    """material=copper 与直给 σ 同值；门面 DC 值与 transfer_impedance_dc 一致。"""
    r_tab = transfer_impedance(
        frequency_hz=1.0e6, radius_m=_A_MM, thickness_m=_T_MM,
        material="copper")
    r_sig = transfer_impedance(
        frequency_hz=1.0e6, radius_m=_A_MM, thickness_m=_T_MM,
        conductivity_s_per_m=5.8e7)
    assert r_tab["zt_dc_ohm_per_m"] == r_sig["zt_dc_ohm_per_m"]
    # 数值面全同（材料表命中=同 σ 同 μr）；material 键是溯源字段，本别：
    # 'copper' vs None 合法差异，不进等价断言。
    diff = {k for k in r_tab if r_tab[k] != r_sig[k]}
    assert diff == {"material"}
    assert r_tab["zt_dc_ohm_per_m"] == pytest.approx(
        transfer_impedance_dc(_A_MM, _T_MM, 5.8e7), rel=1e-14)


# ─── 负例守卫（域违例显式拒绝）────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    {"frequency_hz": 0.0, "radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU},
    {"frequency_hz": -1.0, "radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU},
    {"frequency_hz": 1.0e6, "radius_m": 0.0, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU},
    {"frequency_hz": 1.0e6, "radius_m": _A_MM, "thickness_m": 0.0,
     "conductivity_s_per_m": _SIGMA_CU},
    {"frequency_hz": 1.0e6, "radius_m": _T_MM, "thickness_m": _A_MM + 1e-9,
     "conductivity_s_per_m": _SIGMA_CU},  # t≥a 非薄壁管
    {"frequency_hz": 1.0e6, "radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": 0.0},
    {"frequency_hz": 1.0e6, "radius_m": _A_MM, "thickness_m": _T_MM,
     "material": "unobtainium"},
    {"frequency_hz": 1.0e6, "radius_m": _A_MM, "thickness_m": _T_MM,
     "mu_r": 0.0},
    {"frequency_hz": 1.0e6, "radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU,
     "coupling_inductance_h_per_m": -1e-9},
    {"radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU},  # 频率都缺
    {"frequency_hz": 1.0e6, "f_axis_hz": [1.0e6], "radius_m": _A_MM,
     "thickness_m": _T_MM, "conductivity_s_per_m": _SIGMA_CU},  # 同给
    {"radius_m": _A_MM, "thickness_m": _T_MM,
     "conductivity_s_per_m": _SIGMA_CU, "f_axis_hz": []},  # 空轴
])
def test_facade_domain_guards(kwargs):
    with pytest.raises(ValueError):
        transfer_impedance(**kwargs)


@pytest.mark.parametrize("func,args", [
    (zt_solid_tube, (0.0, _A_MM, _T_MM, _SIGMA_CU)),
    (zt_solid_tube_hf_asymptote, (-1.0, _A_MM, _T_MM, _SIGMA_CU)),
    (inductive_leakage_term, (1.0e6, -1e-9)),
    (inductive_leakage_term, (0.0, 1e-9)),
])
def test_point_guards(func, args):
    with pytest.raises(ValueError):
        func(*args)


@pytest.mark.parametrize("kwargs", [
    {"radius_m": True, "thickness_m": _T_MM, "conductivity_s_per_m": _SIGMA_CU,
     "frequency_hz": 1.0e6},
    {"radius_m": _A_MM, "thickness_m": _T_MM, "conductivity_s_per_m": True,
     "frequency_hz": 1.0e6},
])
def test_bool_rejection(kwargs):
    """bool 显式拒收（float(True)=1.0 静默污染，df7+⑯ 惯例）。"""
    with pytest.raises(ValueError):
        transfer_impedance(**kwargs)


def test_module_pure_functions_no_registry():
    """round17 EM-4 未要求注册键：模块无 register_calculator 消费（与
    EM-1/EM-2 同口径）；__all__ 无编织常数出口。"""
    assert not hasattr(ti, "register_calculator")
    joined = " ".join(ti.__all__).lower()
    assert "kley" not in joined and "braid" not in joined
