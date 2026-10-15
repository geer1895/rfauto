"""aurora72 A3-B 席锚树：stub_tuner 两键（双/三支节并联调配）+
linear_antenna_zin 三键（偶极/折合/小环输入阻抗）。

数值断言口径（#118 不自证——恒等式/独立常数/独立路线/跨键互证，不用
自身推导互证）：
- 支节调配：禁区边界 g_max=csc²(βd) 解析钉（45°→2.0、135°→2.0、
  60°→4/3 独立常数式）；禁区边界邻域（g=1.999 可解 / g=2.001 禁区）
  双侧判定；可调区固定负载清单→测试侧独立 ABCD 级联 |Γ|<1e-10 逐点
  回收；支节长度定义恒等式回代（开路 tan(2πl/λ)=b_s、短路
  −cot(2πl/λ)=b_s、b_s=0 短路→0.25λ）；stub1_deg=45° 旋转负载出禁区；
  三支节 bypass_first/rotate_first 双路线（构造负载 y=0.5+1.2j 归一
  点触发旋转）+ 任意 r_L>0 负载清单全匹配。
- 偶极：半波 73.1+j42.5 教科书常数窗（73.079/42.515 实测，独立窗
  断言）；半波 X 线径无关（sin(π)≈0 半径项归零，a=0.1/2.0 逐位）；
  短偶极渐近 R→20π²(l/λ)²（三角电流极限，rel<5e-3）；方向性半波
  2.15dBi/短偶极 1.5（1.76dBi）双锚；谐振长度 0.465~0.485 文献带
  （Numerical 逼近）+ 残差 |X|≈0；容性/感性符号翻转；|X| 随线径
  增大而减小；l=λ 电流节点奇点显式拒绝。
- 折合：谐振 4× 恒等（Z_in=4Z_d 逐位；step_up→4；线径/间距约去=
  间距 5/20mm 同值）；并联恒等式 1/Z_in=1/(4Z_d)+1/Z_tl 测试侧独立
  重算（离谐振 l=λ/4）；l→λ⁻ 短路边（|Z_in|≪|Z_d|）。
- 小环：三式恒等（320π⁴ ≡ 20π²(C/λ)⁴·(1/A 换算) 机器精度；31171
  圆整常数偏差 ~3e-6 如实非零断言窗）；N×2→Rr×4、b×2→Rr×16 标度
  逐位；Grover 电感 L=μ0b[ln(8b/a)−2] 测试侧独立重算；效率∈(0,1)、
  R_L=Rs·N·b/a 独立式；C/λ>0.3 守卫。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

C_MM_GHZ = 299.792458          # mm·GHz（测试侧独立常量，同注册表锚值）
_MU0 = 1.25663706212e-6
_ETA0 = math.sqrt(_MU0 / 8.8541878128e-12)


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


def _abcd_gamma(rl: float, xl: float, z0: float,
                sections: list[tuple[str, float]]) -> float:
    """测试侧独立 ABCD 级联 |Γ_in|（归一化；sections 输入端→负载序）。"""
    a_m, b_m, c_m, d_m = 1.0 + 0j, 0j, 0j, 1.0 + 0j
    for kind, value in sections:
        if kind == "line":
            m00 = m11 = complex(math.cos(value), 0.0)
            m01 = m10 = 1j * math.sin(value)
        else:
            m00, m01, m10, m11 = 1.0 + 0j, 0j, 1j * value, 1.0 + 0j
        a_n = a_m * m00 + b_m * m10
        b_n = a_m * m01 + b_m * m11
        c_n = c_m * m00 + d_m * m10
        d_n = c_m * m01 + d_m * m11
        a_m, b_m, c_m, d_m = a_n, b_n, c_n, d_n
    z_l = complex(rl, xl) / z0
    z_in = (a_m * z_l + b_m) / (c_m * z_l + d_m)
    return abs((z_in - 1.0) / (z_in + 1.0))


# 可调区固定负载清单（rl, xl；含感/容、低/高阻抗，全部 g ≤ 2 可解）
_SOLVABLE_LOADS = [
    (100.0, 60.0),    # Pozar 型感性负载 g=0.368
    (35.0, -70.0),    # 容性负载
    (200.0, -100.0),  # 高阻抗
    (12.5, 25.0),     # 低阻抗（z̄=0.25+0.5j → g=1.6 贴禁区内侧）
    (80.0, -60.0),
    (50.0, 100.0),
]


# ─── stub_tuner_double：禁区边界 / ABCD 回收 / 长度恒等 ─────────────────────


@pytest.mark.parametrize("spacing_deg,expect_gmax", [
    (45.0, 2.0), (135.0, 2.0), (60.0, 4.0 / 3.0),
])
def test_double_forbidden_boundary_analytic(spacing_deg, expect_gmax):
    """禁区边界 g_max=csc²(βd)（测试侧独立常数式 1+1/tan²）。"""
    r = _run("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                   "spacing_deg": spacing_deg})
    t = math.tan(math.radians(spacing_deg))
    assert r["g_max"] == pytest.approx(1.0 + 1.0 / (t * t), abs=1e-9)
    assert r["g_max"] == pytest.approx(expect_gmax, rel=1e-9)


def test_double_boundary_neighborhood_discrimination():
    """边界邻域双侧判定：g=1.999 可解 / g=2.001 禁区（λ/8 间距）。"""
    # y 归一电导直接构造：z = 1/y（z0=50 换算）
    for g, solvable in ((1.999, True), (2.001, False)):
        z_l = 50.0 / complex(g, 0.0)
        r = _run("stub_tuner_double", {"rl_ohm": z_l.real, "xl_ohm": 0.0})
        assert r["solvable"] is solvable
        assert r["forbidden"] is (not solvable)
        assert r["g_load_at_stub1"] == pytest.approx(g, rel=1e-9)


@pytest.mark.parametrize("rl,xl", _SOLVABLE_LOADS)
def test_double_random_solvable_loads_abcd_recovery(rl, xl):
    """可调区负载→解→测试侧独立 ABCD 级联 |Γ|<1e-10 逐点回收。"""
    r = _run("stub_tuner_double", {"rl_ohm": rl, "xl_ohm": xl})
    assert r["matched"] is True
    assert r["solvable"] is True and r["forbidden"] is False
    assert r["gamma_in_abs"] < 1e-12  # in-output（未舍入链）
    gam = _abcd_gamma(rl, xl, 50.0, [
        ("shunt", r["b_s2"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s1"]),
        ("line", math.radians(r["stub1_deg"]))])
    assert gam < 1e-10, f"独立 ABCD 回收失败: {rl},{xl} gam={gam}"


def test_double_forbidden_load_reported_not_raised():
    """z_L=10+j10（g=2.5>2）→ solvable=False + 禁区数据如实报告。"""
    r = _run("stub_tuner_double", {"rl_ohm": 10.0, "xl_ohm": 10.0})
    assert r["solvable"] is False and r["forbidden"] is True
    assert r["g_load_at_stub1"] == pytest.approx(2.5, rel=1e-9)
    assert r["forbidden_margin"] == pytest.approx(-0.5, rel=1e-9)
    assert r["b_s1"] is None and r["b_s2"] is None
    assert r["matched"] is False


def test_double_stub_length_defining_identities():
    """支节长度定义恒等式回代：开路 tan(2πl/λ)=b_s、短路 −cot=b_s。"""
    r = _run("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0})
    l1, l2 = r["l1_over_lambda"], r["l2_over_lambda"]
    bs1, bs2 = r["b_s1"], r["b_s2"]
    assert math.tan(2.0 * math.pi * l1) == pytest.approx(bs1, rel=1e-9)
    assert math.tan(2.0 * math.pi * l2) == pytest.approx(bs2, rel=1e-9)
    assert 0.0 <= l1 < 0.5 and 0.0 <= l2 < 0.5
    # 短路支节：−cot(2πl/λ)=b_s
    r_s = _run("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                     "stub_type": "short"})
    for ll, bs in ((r_s["l1_over_lambda"], r_s["b_s1"]),
                   (r_s["l2_over_lambda"], r_s["b_s2"])):
        assert -1.0 / math.tan(2.0 * math.pi * ll) == pytest.approx(
            bs, rel=1e-9, abs=1e-15)


def test_double_rotation_escapes_forbidden_zone():
    """stub1_deg=45° 旋转：g=2.5 禁区负载转到 g≈0.270 可调区并匹配。"""
    r = _run("stub_tuner_double", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                                   "stub1_deg": 45.0})
    assert r["solvable"] is True and r["matched"] is True
    assert r["forbidden"] is False
    assert r["g_load_at_stub1"] == pytest.approx(0.270270270270, rel=1e-9)
    gam = _abcd_gamma(10.0, 10.0, 50.0, [
        ("shunt", r["b_s2"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s1"]),
        ("line", math.radians(r["stub1_deg"]))])
    assert gam < 1e-10


def test_double_domain_rejections():
    """rl≤0 / z0≤0 / 间距 90° 奇点与越界 / stub1_deg≥180 / 非法类型。"""
    _reject("stub_tuner_double", {"rl_ohm": 0.0, "xl_ohm": 60.0}, "rl_ohm")
    _reject("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                  "z0_ohm": 0.0}, "z0_ohm")
    _reject("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                  "spacing_deg": 90.0}, "spacing_deg")
    _reject("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                  "spacing_deg": 179.9}, "spacing_deg")
    _reject("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                  "stub1_deg": 180.0}, "stub1_deg")
    _reject("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                                  "stub_type": "quasi"}, "stub_type")


# ─── stub_tuner_triple：禁区消除 / 双路线 / 全可解 ───────────────────────────


def test_triple_clears_double_forbidden_zone():
    """双支节禁区负载（z=10+j10）三支节 matched（bypass_first 路线）。
    旁路 b_s1=0 的短路支节 = λ/4 开路器（b_s=0 → 0.25λ 惯例）。"""
    r = _run("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0})
    assert r["solvable"] is True and r["matched"] is True
    assert r["route"] == "bypass_first"
    assert r["b_s1"] == 0.0
    assert r["gamma_in_abs"] < 1e-12
    gam = _abcd_gamma(10.0, 10.0, 50.0, [
        ("shunt", r["b_s3"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s2"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s1"]),
        ("line", math.radians(r["stub1_deg"]))])
    assert gam < 1e-10
    r_short = _run("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                                         "stub_type": "short"})
    assert r_short["b_s1"] == 0.0
    assert r_short["l1_over_lambda"] == pytest.approx(0.25, abs=1e-12)


def test_triple_rotate_route_for_bypass_forbidden():
    """构造负载（y=0.5+1.2j 归一点）触发 rotate_first 路线并匹配。"""
    # z_L = 50/(0.5+1.2j) → rl=14.7929, xl=-35.5030
    rl, xl = 50.0 * 0.5 / 1.69, -50.0 * 1.2 / 1.69
    r = _run("stub_tuner_triple", {"rl_ohm": rl, "xl_ohm": xl})
    assert r["route"] == "rotate_first"
    assert r["matched"] is True and r["gamma_in_abs"] < 1e-12
    gam = _abcd_gamma(rl, xl, 50.0, [
        ("shunt", r["b_s3"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s2"]),
        ("line", math.radians(r["spacing_deg"])),
        ("shunt", r["b_s1"]),
        ("line", math.radians(r["stub1_deg"]))])
    assert gam < 1e-10


def test_triple_never_unsolvable_load_list():
    """任意 r_L>0 负载清单全匹配（含双支节禁区内外、强失配远点）。"""
    loads = [(2.0, 2.0), (300.0, 250.0), (5.0, -200.0), (150.0, 300.0),
             (10.0, 10.0), (75.0, -125.0), (25.0, 0.5), (400.0, -400.0)]
    for rl, xl in loads:
        r = _run("stub_tuner_triple", {"rl_ohm": rl, "xl_ohm": xl})
        assert r["solvable"] is True and r["matched"] is True, (rl, xl)
        assert r["gamma_in_abs"] < 1e-12


def test_triple_double_pair_consistency():
    """旁路路线下 stub2/stub3 解=对 (g2,b2) 的双支节闭式解（跨键互证）。"""
    r3 = _run("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0})
    r2 = _run("stub_tuner_double", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                                    "stub1_deg": 45.0})
    # 旁路：y@stub2 = T(y@45°, 45°)；双支节键在 stub1_deg=45 解出的
    # (b_s1', b_s2') 应=三支节的 (b_s2, b_s3)
    assert r3["b_s2"] == pytest.approx(r2["b_s1"], rel=1e-9)
    assert r3["b_s3"] == pytest.approx(r2["b_s2"], rel=1e-9)


# ─── dipole_emf_zin：教科书常数 / 渐近 / 方向性 / 谐振 ───────────────────────

_FREQ = 2.0
_LAM = C_MM_GHZ / _FREQ  # 149.896229 mm


def test_dipole_halfwave_textbook_constants():
    """半波 73.1+j42.5 教科书常数窗；方向性 2.15dBi。"""
    r = _run("dipole_emf_zin", {"length_mm": 0.5 * _LAM, "f_ghz": _FREQ,
                                "wire_radius_mm": 0.5})
    assert r["r_in_ohm"] == pytest.approx(73.1, abs=0.1)
    assert r["x_in_ohm"] == pytest.approx(42.5, abs=0.1)
    assert r["directivity_dbi"] == pytest.approx(2.15, abs=0.01)
    assert r["directivity_linear"] == pytest.approx(1.641, abs=0.005)


def test_dipole_halfwave_x_radius_independent():
    """kl=π 处 sin 项归零→X 线径无关（a=0.1 vs 2.0mm 逐位）。"""
    r1 = _run("dipole_emf_zin", {"length_mm": 0.5 * _LAM, "f_ghz": _FREQ,
                                 "wire_radius_mm": 0.1})
    r2 = _run("dipole_emf_zin", {"length_mm": 0.5 * _LAM, "f_ghz": _FREQ,
                                 "wire_radius_mm": 2.0})
    assert r1["x_in_ohm"] == pytest.approx(r2["x_in_ohm"], rel=1e-9)


@pytest.mark.parametrize("l_over_lam,tol_rel", [(0.02, 2e-3), (0.05, 5e-3)])
def test_dipole_short_asymptote_triangular(l_over_lam, tol_rel):
    """短偶极渐近 R→20π²(l/λ)²（三角电流分布极限，测试侧独立常数）。"""
    r = _run("dipole_emf_zin", {"length_mm": l_over_lam * _LAM,
                                "f_ghz": _FREQ, "wire_radius_mm": 0.3})
    expect = 20.0 * math.pi ** 2 * l_over_lam ** 2
    assert r["r_in_ohm"] == pytest.approx(expect, rel=tol_rel)


def test_dipole_directivity_short_limit():
    """短偶极方向性→1.5（1.76dBi，与赫兹元同形）。"""
    r = _run("dipole_emf_zin", {"length_mm": 0.02 * _LAM, "f_ghz": _FREQ,
                                "wire_radius_mm": 0.3})
    assert r["directivity_linear"] == pytest.approx(1.5, abs=5e-3)


def test_dipole_resonant_length_numerical_band():
    """谐振长度细线锚带 0.465~0.485λ（Numerical 逼近文献带）+ 残差≈0。"""
    r = _run("dipole_emf_zin", {"length_mm": 70.5, "f_ghz": _FREQ,
                                "wire_radius_mm": 0.5})
    assert 0.465 <= r["resonant_l_over_lambda"] <= 0.485
    assert abs(r["residual_x_at_resonance_ohm"]) < 1e-6


def test_dipole_x_sign_flip_and_radius_trend():
    """谐振下容性/上感性符号翻转；同长下 |X| 随线径增大而减小。"""
    below = _run("dipole_emf_zin", {"length_mm": 0.40 * _LAM,
                                    "f_ghz": _FREQ, "wire_radius_mm": 0.5})
    above = _run("dipole_emf_zin", {"length_mm": 0.50 * _LAM,
                                    "f_ghz": _FREQ, "wire_radius_mm": 0.5})
    assert below["x_in_ohm"] < 0.0
    assert above["x_in_ohm"] > 0.0
    thin = _run("dipole_emf_zin", {"length_mm": 0.45 * _LAM,
                                   "f_ghz": _FREQ, "wire_radius_mm": 0.25})
    thick = _run("dipole_emf_zin", {"length_mm": 0.45 * _LAM,
                                    "f_ghz": _FREQ, "wire_radius_mm": 1.0})
    assert abs(thick["x_in_ohm"]) < abs(thin["x_in_ohm"])


def test_dipole_fullwave_current_node_rejected():
    """l=λ 全波馈点电流节点（sin(kh)=0）模型奇点显式拒绝。"""
    _reject("dipole_emf_zin", {"length_mm": _LAM, "f_ghz": _FREQ,
                               "wire_radius_mm": 0.5}, "电流节点")


# ─── folded_dipole_zin：4× 恒等 / 并联恒等式 / 短路边 ────────────────────────


def test_folded_resonance_stepup_four_exact():
    """谐振 l=λ/2：Z_in=4Z_d（逐位）；step_up→4；间距/线径约去。"""
    r1 = _run("folded_dipole_zin", {"length_mm": 0.5 * _LAM, "f_ghz": _FREQ,
                                    "wire_radius_mm": 0.5,
                                    "spacing_mm": 10.0})
    z_d = complex(r1["z_d_r_ohm"], r1["z_d_x_ohm"])
    z_in = complex(r1["z_in_r_ohm"], r1["z_in_x_ohm"])
    assert z_in == pytest.approx(4.0 * z_d, rel=1e-9)
    assert r1["step_up_abs"] == pytest.approx(4.0, rel=1e-6)
    assert z_in.real == pytest.approx(4.0 * 73.079, abs=0.1)  # ≈300Ω 口径
    # 间距 5/20mm：Z_tl→∞ 极限下 Z_in 与间距无关（谐振点恒等锚）
    for spacing in (5.0, 20.0):
        r2 = _run("folded_dipole_zin", {"length_mm": 0.5 * _LAM,
                                        "f_ghz": _FREQ,
                                        "wire_radius_mm": 0.5,
                                        "spacing_mm": spacing})
        assert r2["z_in_r_ohm"] == pytest.approx(r1["z_in_r_ohm"], rel=1e-9)
        assert r2["z_in_x_ohm"] == pytest.approx(r1["z_in_x_ohm"], rel=1e-9)


def test_folded_parallel_identity_off_resonance():
    """并联恒等式 1/Z_in=1/(4Z_d)+1/Z_tl 测试侧独立重算（l=λ/4）。"""
    r = _run("folded_dipole_zin", {"length_mm": 0.25 * _LAM, "f_ghz": _FREQ,
                                   "wire_radius_mm": 0.5,
                                   "spacing_mm": 10.0})
    z_d = complex(r["z_d_r_ohm"], r["z_d_x_ohm"])
    z_tl = 2j * r["z_t_ohm"] * math.tan(math.pi * 0.25)  # tan(kl/2)=tan(π/4)
    z_expect = 1.0 / (1.0 / (4.0 * z_d) + 1.0 / z_tl)
    z_in = complex(r["z_in_r_ohm"], r["z_in_x_ohm"])
    assert z_in == pytest.approx(z_expect, rel=1e-9)


def test_folded_short_trend_near_full_wave():
    """l→λ⁻ 传输线模 tan(kl/2)→0 旁路馈点：|Z_in|≪|Z_d|（短路边定性）。"""
    r = _run("folded_dipole_zin", {"length_mm": 0.999 * _LAM,
                                   "f_ghz": _FREQ, "wire_radius_mm": 0.5,
                                   "spacing_mm": 10.0})
    assert abs(complex(r["z_in_r_ohm"], r["z_in_x_ohm"])) < 0.01 * abs(
        complex(r["z_d_r_ohm"], r["z_d_x_ohm"]))


def test_folded_domain_rejections():
    """线重叠/超域/l=λ 奇点/线径≤0 显式拒绝。"""
    _reject("folded_dipole_zin", {"length_mm": 70.0, "f_ghz": _FREQ,
                                  "wire_radius_mm": 1.0,
                                  "spacing_mm": 1.5}, "不重叠")
    _reject("folded_dipole_zin", {"length_mm": 200.0, "f_ghz": _FREQ,
                                  "wire_radius_mm": 0.5,
                                  "spacing_mm": 10.0}, "λ")
    _reject("folded_dipole_zin", {"length_mm": _LAM, "f_ghz": _FREQ,
                                  "wire_radius_mm": 0.5,
                                  "spacing_mm": 10.0}, "电流节点")


# ─── small_loop_zin：三式恒等 / 标度 / 独立重算 ─────────────────────────────


def test_loop_three_form_identity():
    """Rr=320π⁴N²(A/λ²)² ≡ 20π²N²(C/λ)⁴（机器精度）；31171 圆整窗。"""
    r = _run("small_loop_zin", {"radius_mm": 10.0, "f_ghz": 1.0,
                                "wire_radius_mm": 1.0, "turns_n": 2.0,
                                "conductivity_s_per_m": 5.8e7})
    assert r["identity_rel_dev"] <= 1e-12
    assert r["r_radiation_ohm"] == pytest.approx(
        r["r_radiation_form2_ohm"], rel=1e-12)
    # 320π⁴ = 31170.9…（测试侧独立常数）；31171 圆整偏差 ~3e-6 如实
    const = 320.0 * math.pi ** 4
    assert 31170.0 < const < 31172.0
    assert r["r_radiation_31171_ohm"] == pytest.approx(
        r["r_radiation_ohm"], rel=5e-6)  # 圆整常数档
    assert r["r_radiation_31171_ohm"] != pytest.approx(
        r["r_radiation_ohm"], rel=1e-9)  # 非逐位（圆整如实非恒等）


def test_loop_scaling_laws_exact():
    """N×2→Rr×4、b×2→Rr×16（A∝b²）标度逐位；两几何均在电小域内。"""
    base = {"f_ghz": 0.5, "wire_radius_mm": 1.0,
            "conductivity_s_per_m": 5.8e7}
    r1 = _run("small_loop_zin", {**base, "radius_mm": 10.0, "turns_n": 1.0})
    r2 = _run("small_loop_zin", {**base, "radius_mm": 10.0, "turns_n": 2.0})
    assert r2["r_radiation_ohm"] == pytest.approx(
        4.0 * r1["r_radiation_ohm"], rel=1e-9)
    r3 = _run("small_loop_zin", {**base, "radius_mm": 20.0, "turns_n": 1.0})
    assert r3["r_radiation_ohm"] == pytest.approx(
        16.0 * r1["r_radiation_ohm"], rel=1e-9)


def test_loop_loss_induction_q_independent_recompute():
    """R_L=Rs·N·b/a 与 Grover L=μ0b[ln(8b/a)−2] 测试侧独立重算；
    效率∈(0,1)、Q=X/(Rr+R_L) 恒等。"""
    params = {"radius_mm": 10.0, "f_ghz": 1.0, "wire_radius_mm": 1.0,
              "turns_n": 2.0, "conductivity_s_per_m": 5.8e7}
    r = _run("small_loop_zin", params)
    rs = math.sqrt(math.pi * 1.0e9 * _MU0 / 5.8e7)
    assert r["r_loss_ohm"] == pytest.approx(rs * 2.0 * 10.0 / 1.0, rel=1e-9)
    l_h = _MU0 * 2.0 ** 2 * 0.01 * (math.log(80.0) - 2.0)
    assert r["l_loop_nh"] == pytest.approx(l_h * 1e9, rel=1e-9)
    x_expect = 2.0 * math.pi * 1.0e9 * l_h
    assert r["x_in_ohm"] == pytest.approx(x_expect, rel=1e-9)
    assert 0.0 < r["efficiency"] < 1.0
    assert r["efficiency"] == pytest.approx(
        r["r_radiation_ohm"] / (r["r_radiation_ohm"] + r["r_loss_ohm"]),
        rel=1e-9)
    assert r["q"] == pytest.approx(
        r["x_in_ohm"] / (r["r_radiation_ohm"] + r["r_loss_ohm"]), rel=1e-9)


def test_loop_electrically_small_guard():
    """C/λ>0.3 超电小域显式拒绝；域内临界值放行。"""
    _reject("small_loop_zin", {"radius_mm": 30.0, "f_ghz": 5.0,
                               "wire_radius_mm": 1.0, "turns_n": 1.0,
                               "conductivity_s_per_m": 5.8e7}, "电小")


# ─── 键面卫生：description 首行中文名形态 + EXPECTED 成员 ───────────────────


def test_new_keys_description_first_line_format():
    """aurora72 新规：description 首行 = 中文名（≤24 字符）+全角冒号。"""
    new_keys = ("stub_tuner_double", "stub_tuner_triple", "dipole_emf_zin",
                "folded_dipole_zin", "small_loop_zin")
    for key in new_keys:
        desc = CALCULATOR_REGISTRY.get(key).description
        first_line = desc.split("\n", 1)[0]
        idx = first_line.find("：")
        assert idx >= 1, f"{key}: 首行无全角冒号: {first_line!r}"
        assert idx <= 24, (
            f"{key}: 中文名超 24 字符（{idx}）: {first_line!r}")
        assert first_line[:idx].strip(), f"{key}: 中文名为空"


def test_registry_count_grew_by_five():
    """注册键面增量自洽：EXPECTED 含五新键（与 test_calculators 对账）。"""
    from tests.unit.test_calculators import EXPECTED
    for key in ("stub_tuner_double", "stub_tuner_triple", "dipole_emf_zin",
                "folded_dipole_zin", "small_loop_zin"):
        assert key in EXPECTED
        assert key in CALCULATOR_REGISTRY.names()
