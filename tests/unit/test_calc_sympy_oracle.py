"""Z-13 sympy oracle 对拍族（aurora_j W4-S14 席）。

10 个 CALC 注册键的 sympy 符号第三方裁判：每键先由 sympy 符号引擎独立
推导期望形态（simplify 恒等式证明 / diff 符号求导 / solve 代数反解 /
nsolve 超越方程求根），再数值代入（evalf 25+ 位）与注册计算器输出对拍。

#118 诚实性：oracle=符号推导独立路线，非实现公式重抄——期望值不是把
实现的 float 表达式逐字誊写再算，而是由符号引擎从物理定义式出发化简/
求解产出（抓"实现数值面与符号推导不一致"的面；比 formula_reimpl 抓
实现笔误档更进一步的采信层级，文档闭式本身错仍归 1b/1c 审计面）。
被测键只经 CALCULATOR_REGISTRY 公开入口调用，内部 helper 零引用。

对拍点=实现 docstring 教科书锚点或典型工作点 2-3 个；rel 门按内核输出
round 末位定（round(…,12)→1e-10、round(…,9)→1e-9、round(…,6)→1e-6；
数值微分/系数圆整面单独声明地板，如实注记）。

skip 行为：sympy 未装环境全模块诚实 skip（importorskip，venv 已装
1.14.0 但依赖面 dev extra 声明随本席落 pyproject，#178 教训）；rfauto
本体缺失时报错而非 skip（被测产品不可缺）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

sympy = pytest.importorskip("sympy")

from rfauto.core.calculators import CALCULATOR_REGISTRY

sp = sympy

# 物理/SI 常数（与内核同值的定义常数——常数不是被测公式，物理常数取
# SI 精确值/行业约定值本身即独立来源）
_C0_M_S = 299792458.0
_C_MM_GHZ = 299.792458
_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12


def _calc(key: str, **kwargs):
    """注册计算器公开入口调用（被测面唯一触点）。"""
    return CALCULATOR_REGISTRY.get(key).func(**kwargs)


def _assert_relim(actual: float, expected: float, tol: float, label: str) -> None:
    rel = abs(actual - expected) / max(abs(expected), 1e-300)
    assert rel <= tol, (
        f"{label}: rel={rel:.3e} > {tol:.0e} "
        f"(actual={actual!r}, expected={expected!r})")


def _assert_abs(actual: float, expected: float, tol: float, label: str) -> None:
    assert abs(actual - expected) <= tol, (
        f"{label}: |d|={abs(actual - expected):.3e} > {tol:.0e} "
        f"(actual={actual!r}, expected={expected!r})")


def _f(expr) -> float:
    """sympy 数值化 → float（evalf 高精度后落 double）。"""
    return float(sp.N(expr, 25))


def _poly_from_coeffs(coeffs: list[list[float]], s: sp.Symbol) -> sp.Expr:
    """[[re, im], ...]（np.poly 降幂系数序）→ sympy 多项式。"""
    deg = len(coeffs) - 1
    return sum(
        (complex(re_, im_) * s ** (deg - k) for k, (re_, im_) in enumerate(coeffs)),
        sp.S(0))


def _rlc_samples(kind: str, r_ohm: float, q_target: float, f0_hz: float,
                 n_half: int, delta_f: float) -> tuple[list[float], list[complex]]:
    """RLC 符号模型 lambdify 采样（f0 恰居样点正中，Yaghjian-Best 采样契约
    Δf/f₀≪1/(2Q)）；Z(ω) 由符号表达式生成，不经任何实现代码。"""
    w0 = 2.0 * math.pi * f0_hz
    if kind == "series":
        l_h = q_target * r_ohm / w0
        c_f = 1.0 / (w0 * w0 * l_h)
    else:
        c_f = q_target / (w0 * r_ohm)
        l_h = 1.0 / (w0 * w0 * c_f)
    w_sym = sp.symbols("w_sample", positive=True)
    if kind == "series":
        z_expr = r_ohm + sp.I * (w_sym * l_h - 1 / (w_sym * c_f))
    else:
        z_expr = 1.0 / (1 / r_ohm + sp.I * (w_sym * c_f - 1 / (w_sym * l_h)))
    z_fun = sp.lambdify(w_sym, z_expr, modules="math")
    freqs = [f0_hz + (i - n_half) * delta_f for i in range(2 * n_half + 1)]
    zs = [complex(z_fun(2.0 * math.pi * f)) for f in freqs]
    return freqs, zs


# ══════════ 1. waveguide_lambda_g：1/λg² 恒等式符号化 ══════════


def test_waveguide_lambda_g_identity_and_numeric() -> None:
    """TE10 恒等式 1/λg²=1/λ0²−1/λc² sympy simplify 证明 + 传播参数对拍。

    oracle=符号推导独立路线：λ0=c/f、λc=2a、λg=λ0/√(1−(fc/f)²) 由符号
    引擎化简证明恒等式后数值代入（Pozar §3.x 口径），非实现公式重抄。
    """
    a_m, f_hz, c = sp.symbols("a_m f_hz c", positive=True)
    lam0 = c / f_hz
    lam_c = 2 * a_m
    lam_g = lam0 / sp.sqrt(1 - (lam0 / lam_c) ** 2)
    assert sp.simplify(1 / lam_g ** 2 - (1 / lam0 ** 2 - 1 / lam_c ** 2)) == 0
    # vg/c=√(1−(λ0/λc)²)=√(1−(fc/f)²) 符号面（色散口径一致性）
    assert sp.simplify((lam0 / lam_g) ** 2 - (1 - (lam0 / lam_c) ** 2)) == 0
    for a_mm, f_ghz in ((22.86, 10.0), (12.7, 30.0), (15.0, 12.0)):
        subs = {a_m: a_mm * 1e-3, f_hz: f_ghz * 1e9, c: _C0_M_S}
        out = _calc("waveguide_lambda_g", a_mm=a_mm, f_ghz=f_ghz)
        _assert_relim(out["lambda_0_mm"], _f(sp.N(lam0.subs(subs), 25)) * 1e3,
                      1e-11, "lambda_0")
        _assert_relim(out["lambda_c_mm"], _f(sp.N(lam_c.subs(subs), 25)) * 1e3,
                      1e-11, "lambda_c")
        _assert_relim(out["lambda_g_mm"], _f(sp.N(lam_g.subs(subs), 25)) * 1e3,
                      1e-11, "lambda_g")
        beta_sym = 2 * sp.pi / lam_g
        _assert_relim(out["beta_rad_per_m"], _f(sp.N(beta_sym.subs(subs), 25)),
                      1e-11, "beta")
        _assert_relim(out["fc10_ghz"],
                      _f(sp.N((c / (2 * a_m)).subs(subs), 25)) / 1e9,
                      1e-11, "fc10")
        _assert_relim(out["vg_over_c"],
                      _f(sp.N(sp.sqrt(1 - (lam0 / lam_c) ** 2).subs(subs), 25)),
                      1e-11, "vg/c")
        _assert_relim(out["vp_over_c"],
                      _f(sp.N((lam_g / lam0).subs(subs), 25)),
                      1e-11, "vp/c")


# ══════════ 2. coax_line_z0：solve 正反解 ══════════


def test_coax_line_z0_solve_and_lc_identity() -> None:
    """Z0=(60/√εr)·ln(b/a) 符号 solve 正反解 + L'C'=με 恒等式证明。

    oracle=符号推导独立路线：综合方向由 sympy.solve 从 TEM 阻抗定义式
    反解半径（非沿用 exp 形态），分布参数恒等式由符号化简证明。
    """
    a_s, b_s, z_s, e_s = sp.symbols("a b z0 eps_r", positive=True)
    z_eq = sp.Eq(z_s, 60 / sp.sqrt(e_s) * sp.log(b_s / a_s))
    b_sol = sp.solve(z_eq, b_s)
    a_sol = sp.solve(z_eq, a_s)
    assert len(b_sol) == 1 and len(a_sol) == 1
    ln_r = sp.log(b_s / a_s)
    c_prime = 2 * sp.pi * _EPS0 * e_s / ln_r          # F/m
    l_prime = _MU0 * ln_r / (2 * sp.pi)               # H/m
    assert sp.simplify(l_prime * c_prime - _MU0 * _EPS0 * e_s) == 0
    for a_mm, b_mm, er in ((1.0, 3.0, 2.1), (0.5, 1.5, 1.0)):
        out = _calc("coax_line_z0", a_mm=a_mm, b_mm=b_mm, epsilon_r=er)
        subs = {a_s: a_mm, b_s: b_mm, e_s: er}
        _assert_relim(out["z0_ohm"],
                      _f(sp.N((60 / sp.sqrt(e_s) * sp.log(b_s / a_s)).subs(subs), 25)),
                      1e-11, "z0 analyze")
        _assert_relim(out["capacitance_pf_per_m"],
                      _f(sp.N(c_prime.subs(subs), 25)) * 1e12, 1e-11, "C'")
        _assert_relim(out["inductance_nh_per_m"],
                      _f(sp.N(l_prime.subs(subs), 25)) * 1e9, 1e-11, "L'")
        te11 = _C_MM_GHZ / (sp.pi * (a_s + b_s) * sp.sqrt(e_s))
        _assert_relim(out["te11_cutoff_ghz"], _f(sp.N(te11.subs(subs), 25)),
                      1e-9, "te11 cutoff")
        _assert_relim(out["lc_over_muepsilon"], 1.0, 1e-11, "L'C'/με")
    # 综合方向（solve 反解，给 z0+内径 → 反解外径）
    out = _calc("coax_line_z0", a_mm=0.8, z0_ohm=45.0, epsilon_r=2.1)
    b_want = _f(sp.N(b_sol[0].subs({a_s: 0.8, z_s: 45.0, e_s: 2.1}), 25))
    _assert_relim(out["b_mm"], b_want, 1e-10, "synthesize b")
    _assert_relim(out["z0_ohm"], 45.0, 1e-9, "synthesize z0 roundtrip")
    # 综合方向（给 z0+外径 → 反解内径）
    out = _calc("coax_line_z0", b_mm=3.0, z0_ohm=60.0, epsilon_r=1.0)
    a_want = _f(sp.N(a_sol[0].subs({b_s: 3.0, z_s: 60.0, e_s: 1.0}), 25))
    _assert_relim(out["a_mm"], a_want, 1e-10, "synthesize a")
    # ratio_only 路线：b/a 符号解数值对拍
    out = _calc("coax_line_z0", z0_ohm=75.0)
    _assert_relim(out["b_over_a"],
                  _f(sp.N(b_sol[0].subs({a_s: 1, z_s: 75.0, e_s: 1.0}), 25)),
                  1e-12, "ratio_only b/a")


# ══════════ 3. small_loop_zin：三式恒等 simplify 证明（最强对拍面）══════════


def test_small_loop_zin_triple_identity() -> None:
    """Rr 三式恒等 320π⁴N²(A/λ²)²≡20π²N²(C/λ)⁴ simplify 符号证明 + 数值对拍。

    oracle=符号推导独立路线：A=πb²、C=2πb 的几何代换由符号引擎完成，
    三式恒等/圆整常数偏差/趋肤损耗/Grover 电感链全部符号求值对拍
    （Balanis ch5 小环口径）；31171 系教科书圆整常数（非恒等，偏差
    ~2.9e-6 如实钉区间不凑恒等）。
    """
    n_s, b_s, a_s, lam_s, f_s = sp.symbols(
        "N b a lambda f", positive=True)
    area = sp.pi * b_s ** 2
    circ = 2 * sp.pi * b_s
    form1 = 320 * sp.pi ** 4 * n_s ** 2 * (area / lam_s ** 2) ** 2
    form2 = 20 * sp.pi ** 2 * n_s ** 2 * (circ / lam_s) ** 4
    # 最强对拍面：三式恒等的符号证明（λ=λ 语义下逐项化简到 0）
    assert sp.simplify(form1 - form2) == 0
    # 31171 = 320π⁴ 圆整（相对偏差 ~2.9e-6，非恒等——如实钉区间）
    rel_const = abs(_f(sp.N(320 * sp.pi ** 4, 30)) - 31171.0) / 31171.0
    assert 1e-6 < rel_const < 1e-5, rel_const
    sigma = 5.8e7
    rs_expr = sp.sqrt(sp.pi * f_s * 1e9 * _MU0 / sigma) * n_s * b_s / a_s
    l_expr = _MU0 * n_s ** 2 * b_s * (sp.log(8 * b_s / a_s) - 2.0)
    x_expr = 2 * sp.pi * f_s * 1e9 * l_expr
    q_expr = x_expr / (form1 + rs_expr)
    eff_expr = form1 / (form1 + rs_expr)
    for b_mm, f_ghz, a_mm, turns in ((10.0, 0.3, 0.5, 2.0),
                                     (20.0, 0.15, 1.0, 3.0)):
        out = _calc("small_loop_zin", radius_mm=b_mm, f_ghz=f_ghz,
                    wire_radius_mm=a_mm, turns_n=turns,
                    conductivity_s_per_m=sigma)
        lam_mm = _C_MM_GHZ / f_ghz
        subs = {b_s: b_mm * 1e-3, a_s: a_mm * 1e-3,
                lam_s: lam_mm * 1e-3, n_s: turns, f_s: f_ghz}
        _assert_relim(out["lambda_mm"], lam_mm, 1e-9, "lambda")
        _assert_relim(out["circumference_over_lambda"],
                      _f(sp.N(2 * sp.pi * b_mm / lam_mm, 25)), 1e-11,
                      "C/lambda")
        _assert_relim(out["r_radiation_ohm"], _f(sp.N(form1.subs(subs), 25)),
                      1e-10, "Rr form1")
        _assert_relim(out["r_radiation_form2_ohm"],
                      _f(sp.N(form2.subs(subs), 25)), 1e-10, "Rr form2")
        form3 = 31171.0 * turns ** 2 * (sp.pi * (b_mm * 1e-3) ** 2
                                        / (lam_mm * 1e-3) ** 2) ** 2
        _assert_relim(out["r_radiation_31171_ohm"], _f(sp.N(form3, 25)),
                      1e-10, "Rr 31171")
        _assert_relim(out["r_loss_ohm"], _f(sp.N(rs_expr.subs(subs), 25)),
                      1e-10, "R_loss")
        _assert_relim(out["efficiency"], _f(sp.N(eff_expr.subs(subs), 25)),
                      1e-10, "efficiency")
        _assert_relim(out["l_loop_nh"], _f(sp.N(l_expr.subs(subs), 25)) * 1e9,
                      1e-9, "L loop")
        _assert_relim(out["x_in_ohm"], _f(sp.N(x_expr.subs(subs), 25)),
                      1e-9, "X in")
        _assert_relim(out["q"], _f(sp.N(q_expr.subs(subs), 25)), 1e-9, "Q")


# ══════════ 4/5/6. antenna_q_yaghjian_best：diff 符号求导回收 ══════════


def test_antenna_q_yaghjian_series_rlc_diff_recovery() -> None:
    """串联 RLC：Q=ω|dZ/dω|/(2R)|_ω0 符号求导回收 Q=ω0L/R + 数值对拍。

    oracle=符号推导独立路线：Yaghjian-Best 2005 导数式对符号 RLC 阻抗
    做 sympy.diff，在 ω0=1/√(LC) 化简回收闭式 Q；数值面由符号模型
    lambdify 采样喂注册键（采样契约 Δf/f₀=1e-6≪1/(2Q)=1/80，中心
    差分截断 O(h²/2)~5e-13 声明地板）。
    """
    r_s, l_s, c_s, w_s = sp.symbols("R L C omega", positive=True)
    w0 = 1 / sp.sqrt(l_s * c_s)
    z_ser = r_s + sp.I * (w_s * l_s - 1 / (w_s * c_s))
    q_derived = w0 * sp.Abs(sp.diff(z_ser, w_s).subs(w_s, w0)) / (2 * r_s)
    assert sp.simplify(q_derived - w0 * l_s / r_s) == 0
    freqs, zs = _rlc_samples("series", 50.0, 40.0, 1.0e9, 3, 1000.0)
    out = _calc("antenna_q_yaghjian_best", f_hz=freqs,
                z_re_ohm=[z.real for z in zs],
                z_im_ohm=[z.imag for z in zs], vswr=2.0)
    _assert_relim(out["q"], 40.0, 1e-9, "Q series")
    _assert_relim(out["f0_hz"], 1.0e9, 1e-12, "f0")
    _assert_relim(out["r0_ohm"], 50.0, 1e-12, "r0")
    _assert_abs(out["x0_ohm"], 0.0, 1e-8, "x0")
    # FBW=2/Q 与 FBW_S=(S−1)/(√S·Q) 闭式链（符号面已回收 Q=ω0L/R=40）
    _assert_relim(out["fbw_half_power"], 2.0 / 40.0, 1e-9, "FBW half power")
    s_val = 2.0
    _assert_relim(out["fbw_vswr"], (s_val - 1) / (math.sqrt(s_val) * 40.0),
                  1e-9, "FBW vswr")


def test_antenna_q_yaghjian_parallel_rlc_diff_recovery() -> None:
    """并联 RLC：同一导数式符号求导回收 Q=ω0RC + 数值对拍。

    oracle=符号推导独立路线；并联型中心差分截断 4Q²h̃²=5.8e-10
    （Q=40、h̃=3e-7）声明地板，rel 门 1e-9 内如实可达。
    """
    r_s, l_s, c_s, w_s = sp.symbols("R L C omega", positive=True)
    w0 = 1 / sp.sqrt(l_s * c_s)
    z_par = 1 / (1 / r_s + sp.I * (w_s * c_s - 1 / (w_s * l_s)))
    q_derived = w0 * sp.Abs(sp.diff(z_par, w_s).subs(w_s, w0)) / (2 * r_s)
    assert sp.simplify(q_derived - w0 * r_s * c_s) == 0
    freqs, zs = _rlc_samples("parallel", 50.0, 40.0, 1.0e9, 3, 300.0)
    out = _calc("antenna_q_yaghjian_best", f_hz=freqs,
                z_re_ohm=[z.real for z in zs],
                z_im_ohm=[z.imag for z in zs], vswr=3.0)
    _assert_relim(out["q"], 40.0, 1e-9, "Q parallel")
    _assert_relim(out["f0_hz"], 1.0e9, 1e-12, "f0")
    _assert_relim(out["r0_ohm"], 50.0, 1e-12, "r0")
    _assert_relim(out["fbw_half_power"], 2.0 / 40.0, 1e-9, "FBW")
    _assert_relim(out["fbw_vswr"], (3.0 - 1) / (math.sqrt(3.0) * 40.0),
                  1e-9, "FBW vswr")


def test_antenna_q_yaghjian_chu_bound_symbolic() -> None:
    """Chu/McLean 界 q_min=1/(ka)³+1/ka 符号求值对拍（圆极化减半口径）。

    oracle=符号推导独立路线：界式对 ka 符号代入 evalf，与注册键
    verdict 面（core/bounds 单源）对拍；ka=0.2 电小区 Q=40<130 判
    unreachable 属实现语义，本测只对拍界值本体。
    """
    ka_s = sp.symbols("ka", positive=True)
    q_min_sym = 1 / ka_s ** 3 + 1 / ka_s
    freqs, zs = _rlc_samples("series", 50.0, 40.0, 1.0e9, 3, 1000.0)
    kw = dict(f_hz=freqs, z_re_ohm=[z.real for z in zs],
              z_im_ohm=[z.imag for z in zs], vswr=2.0, ka=0.2)
    out = _calc("antenna_q_yaghjian_best", polarization="linear", **kw)
    _assert_relim(out["q_min_chu"], _f(sp.N(q_min_sym.subs(ka_s, 0.2), 25)),
                  1e-9, "q_min linear")
    assert out["verdict_chu"] == "unreachable"
    out_c = _calc("antenna_q_yaghjian_best", polarization="circular", **kw)
    _assert_relim(out_c["q_min_chu"],
                  0.5 * _f(sp.N(q_min_sym.subs(ka_s, 0.2), 25)),
                  1e-9, "q_min circular")


# ══════════ 7. l_section_match：solve 反解 ══════════


def test_l_section_match_solve_inversion() -> None:
    """L 节 sympy.solve 反解两元件电抗（Z_in=R_small@f0 两方程）分支对拍。

    oracle=符号推导独立路线：jXs+(R_big∥jXp)=R_small 联立方程由符号
    引擎求解出两支解（low_pass=Xs>0/Xp<0、high_pass=Xs<0/Xp>0），
    电抗值与实现元件 L/C 值换算的电抗对拍（Pozar §5.1 口径）。
    """
    r_sm, r_bg, x_s, x_p = sp.symbols("R_small R_big X_s X_p", positive=True)
    z_in = sp.I * x_s + 1 / (1 / r_bg + 1 / (sp.I * x_p))
    sols = sp.solve([sp.re(z_in) - r_sm, sp.im(z_in)], [x_s, x_p], dict=True)
    assert len(sols) == 2
    q_expr = sp.sqrt(r_bg / r_sm - 1)
    cases = (
        (50.0, 100.0, 2.0, "low_pass"),
        (200.0, 75.0, 1.0, "high_pass"),
        (75.0, 200.0, 2.5, "low_pass"),
    )
    for rs, rl, f0_ghz, resp in cases:
        big, small = max(rs, rl), min(rs, rl)
        subs = {r_sm: small, r_bg: big}
        want_pos = resp == "low_pass"
        matched = [sv for sv in sols
                   if (_f(sp.N(sv[x_s].subs(subs), 25)) > 0) == want_pos]
        assert len(matched) == 1, (rs, rl, resp)
        xs_want = _f(sp.N(matched[0][x_s].subs(subs), 25))
        xp_want = _f(sp.N(matched[0][x_p].subs(subs), 25))
        out = _calc("l_section_match", z_source_ohm=rs, z_load_ohm=rl,
                    f0_ghz=f0_ghz, response=resp)
        _assert_relim(out["q"], _f(sp.N(q_expr.subs(subs), 25)), 1e-11, "q")
        # f0 处匹配条件：源侧所见 Z_in=z_source（L 节把负载变换到源阻值）
        _assert_relim(out["zin_f0_re_ohm"], rs, 1e-9, "Zin re")
        _assert_abs(out["zin_f0_im_ohm"], 0.0, 1e-9, "Zin im")
        _assert_abs(out["match_residual_gamma_mag_f0"], 0.0, 1e-9, "residual")
        om = 2.0 * math.pi * f0_ghz * 1e9
        ser = next(e for e in out["elements"] if e["role"] == "series")
        shn = next(e for e in out["elements"] if e["role"] == "shunt")
        x_ser = (om * ser["value_nh"] * 1e-9 if ser["kind"] == "L"
                 else -1.0 / (om * ser["value_pf"] * 1e-12))
        x_shn = (-1.0 / (om * shn["value_pf"] * 1e-12) if shn["kind"] == "C"
                 else om * shn["value_nh"] * 1e-9)
        _assert_relim(x_ser, xs_want, 1e-9, "series reactance")
        _assert_relim(x_shn, xp_want, 1e-9, "shunt reactance")


# ══════════ 8. chebyshev_prototype：chebyshevt 符号对拍 ══════════


def test_chebyshev_prototype_chebyshevt_and_feldtkeller() -> None:
    """反射零点=chebyshevt(n,x) 根符号对拍 + ε 闭式 + Feldtkeller 恒等式。

    oracle=符号推导独立路线：T_n 的根由 sympy.solve(chebyshevt) 符号
    求出；ε=(10^(RL/10)−1)^(−1/2) 符号求值；F/P/E 多项式满足
    Feldtkeller 方程 |S11|²+|S21|²=1（带内逐点）与带缘回损=RL、TZ 处
    |S21|=0（Cameron 口径的定义性质，非实现公式重抄）。
    """
    x_s, s_s = sp.symbols("x s")
    for n, rl in ((3, 20.0), (5, 26.0)):
        out = _calc("chebyshev_prototype", order=n, rl_db=rl)
        roots_sym = sorted(_f(sp.N(r_, 25))
                           for r_ in sp.solve(sp.chebyshevt(n, x_s), x_s))
        rz = sorted(float(v) for v in out["reflection_zeros"])
        assert len(rz) == n
        for got, want in zip(rz, roots_sym, strict=True):
            _assert_abs(got, want, 1e-8, f"T_{n} root")
        eps_sym = 1 / sp.sqrt(10 ** (sp.Float(rl) / 10) - 1)
        _assert_relim(out["epsilon"], _f(sp.N(eps_sym, 25)), 1e-8, "epsilon")
        f_poly = _poly_from_coeffs(out["f_s"], s_s)
        p_poly = _poly_from_coeffs(out["p_s"], s_s)
        e_poly = _poly_from_coeffs(out["e_s"], s_s)
        eps_v = out["epsilon"]
        for om in (0.0, 0.3, 0.55, 0.8, 1.0):
            sv = sp.I * om
            fv = complex(sp.N(f_poly.subs(s_s, sv), 30))
            pv = complex(sp.N(p_poly.subs(s_s, sv), 30))
            ev = complex(sp.N(e_poly.subs(s_s, sv), 30))
            tot = (abs(fv) ** 2 + abs(pv) ** 2 / eps_v ** 2) / abs(ev) ** 2
            _assert_abs(tot, 1.0, 1e-7, f"Feldtkeller n={n} OM={om}")
        fv = complex(sp.N(f_poly.subs(s_s, sp.I), 30))
        ev = complex(sp.N(e_poly.subs(s_s, sp.I), 30))
        _assert_relim(20.0 * math.log10(abs(fv / ev)), -rl, 1e-6,
                      f"band-edge RL n={n}")
    # 含传输零点：Feldtkeller 保持 + TZ 处 |S21|=0（P(jΩ_z)=0）
    out = _calc("chebyshev_prototype", order=4, rl_db=20.0,
                transmission_zeros=[2.5])
    p_poly = _poly_from_coeffs(out["p_s"], s_s)
    f_poly = _poly_from_coeffs(out["f_s"], s_s)
    e_poly = _poly_from_coeffs(out["e_s"], s_s)
    eps_v = out["epsilon"]
    for om in (0.0, 0.5, 0.9):
        sv = sp.I * om
        fv = complex(sp.N(f_poly.subs(s_s, sv), 30))
        pv = complex(sp.N(p_poly.subs(s_s, sv), 30))
        ev = complex(sp.N(e_poly.subs(s_s, sv), 30))
        tot = (abs(fv) ** 2 + abs(pv) ** 2 / eps_v ** 2) / abs(ev) ** 2
        _assert_abs(tot, 1.0, 1e-7, f"Feldtkeller TZ OM={om}")
    _assert_abs(abs(complex(sp.N(p_poly.subs(s_s, sp.I * 2.5), 30))), 0.0,
                1e-9, "|P| at TZ")


# ══════════ 9. slot_stevenson_conductance：cos² 电导式化简 ══════════


def test_slot_stevenson_cos2_identity_and_inverse() -> None:
    """g_max 的 cos²(πλ0/2λg) 半角化简恒等式 + sin² 电导式数值 + solve 反解。

    oracle=符号推导独立路线：λg 由 TE10 色散关系符号定义，cos² 半角
    恒等由 simplify 证明；反解 x=(a/π)asin(√(g/g_max)) 由 sympy.solve
    从 sin² 方程独立解出（Stevenson 一阶口径，2.09 经验常数照声明）。
    """
    a_s, b_s, f_s, x_s = sp.symbols("a b f x", positive=True)
    lam0 = _C_MM_GHZ / f_s
    lam_g = lam0 / sp.sqrt(1 - (_C_MM_GHZ / (2 * a_s) / f_s) ** 2)
    k_const = sp.Rational(209, 100)
    g_max = k_const * (a_s / b_s) * (lam_g / lam0) * sp.cos(
        sp.pi * lam0 / (2 * lam_g)) ** 2
    g_of_x = g_max * sp.sin(sp.pi * x_s / a_s) ** 2
    # 半角恒等式 cos²(θ/2)=(1+cosθ)/2 符号证明（θ 取波导色散内嵌的
    # 符号本体 π·√(1−(κ/f)²)，纯符号无浮点常数，引擎可完整化简）
    k_s, f2_s = sp.symbols("kappa f2", positive=True)
    theta = sp.pi * sp.sqrt(1 - (k_s / f2_s) ** 2)
    assert sp.simplify(sp.cos(theta / 2) ** 2 - (1 + sp.cos(theta)) / 2) == 0
    for f_ghz, a_mm, b_mm, offs in ((10.0, 22.86, 10.16, (2.0, 5.0)),
                                    (9.375, 22.86, 10.16, (3.0,))):
        subs = {a_s: a_mm, b_s: b_mm, f_s: f_ghz}
        for x_mm in offs:
            out = _calc("slot_stevenson_conductance", f_ghz=f_ghz, a_mm=a_mm,
                        b_mm=b_mm, offset_x_mm=x_mm)
            _assert_relim(out["g_max"], _f(sp.N(g_max.subs(subs), 25)),
                          1e-12, "g_max")
            g_val_sym = _f(sp.N(g_of_x.subs({**subs, x_s: x_mm}), 25))
            _assert_relim(out["conductance"], g_val_sym, 1e-12, "g(x)")
            # 两形态数值互证：cos² 形 vs 半角 (1−cos)/2 形（符号恒等式
            # 已证，数值面在嵌套根号实参下再对一次）
            g_half_val = k_const * (a_mm / b_mm) * float(sp.N(
                (lam_g / lam0).subs(subs), 25)) * (1.0 + float(sp.N(
                    sp.cos(sp.pi * lam0 / lam_g).subs(subs), 25))) / 2.0 * (
                math.sin(math.pi * x_mm / a_mm) ** 2)
            _assert_relim(g_half_val, g_val_sym, 1e-12, "g half-arg form")
            _assert_relim(out["lambda_g_mm"], _f(sp.N(lam_g.subs(subs), 25)),
                          1e-12, "lambda_g")
            _assert_relim(out["resonant_length_mm"],
                          _f(sp.N((lam0 / 2).subs(subs), 25)), 1e-12,
                          "resonant length")
    # 反解：g=0.5 → sympy.solve(sin²(πx/a)=g/g_max) 取 [0,a/2] 支
    f_ghz, a_mm, b_mm = 10.0, 22.86, 10.16
    subs = {a_s: a_mm, b_s: b_mm, f_s: f_ghz}
    g_target = 0.5
    g_max_v = sp.N(g_max.subs(subs), 30)
    sols = sp.solve(sp.Eq(sp.sin(sp.pi * x_s / a_s) ** 2, g_target / g_max_v),
                    x_s)
    xs_in = sorted(
        _f(sp.N(sv.subs(a_s, a_mm), 25)) for sv in sols
        if 0.0 <= _f(sp.N(sv.subs(a_s, a_mm), 25)) <= a_mm / 2.0)
    assert len(xs_in) == 1, xs_in
    out = _calc("slot_stevenson_conductance", f_ghz=f_ghz, a_mm=a_mm,
                b_mm=b_mm, g=g_target)
    _assert_relim(out["offset_x_mm"], xs_in[0], 1e-9, "inverse offset")
    _assert_relim(out["conductance"], g_target, 1e-15, "route g")


# ══════════ 10. bethe_hole_coupler：耦合度幂律/系数代数形 ══════════


def test_bethe_hole_coupler_power_law_and_algebra() -> None:
    """c(d)=K·d³ 幂律符号证明 + Bethe 极化率代数形数值对拍 + solve 综合反解。

    oracle=符号推导独立路线：αe=2r³/3、αm=4r³/3（Bethe 1944）与 E/M
    支路 Z10 结构由符号式组装，幂律 c(d)/c(d′)=(d/d′)³ 由 simplify
    证明；综合方向由 K=c(d)/d³ 符号化反解孔径（非沿用实现的对数/幂
    float 路线）。
    """
    d_s, d2_s, f_s, a_s, b_s = sp.symbols("d d2 f a b", positive=True)
    lam0 = _C0_M_S / f_s
    fc = _C0_M_S / (2 * a_s)
    lam_g = lam0 / sp.sqrt(1 - (fc / f_s) ** 2)
    z10 = sp.sqrt(_MU0 / _EPS0) * lam_g / lam0
    r_h = d_s / 2
    alpha_e = sp.Rational(2, 3) * r_h ** 3
    alpha_m = sp.Rational(4, 3) * r_h ** 3
    prefac = 2 * (2 * sp.pi * f_s) / (a_s * b_s)
    term_e = _EPS0 * alpha_e * z10
    term_m = _MU0 * alpha_m / z10
    c_expr = prefac * (term_e + term_m)
    # 幂律符号证明：c(d)/c(d′)=(d/d′)³
    assert sp.simplify(c_expr / c_expr.subs(d_s, d2_s) - (d_s / d2_s) ** 3) == 0
    for f_ghz, a_mm, b_mm, d_mm in ((10.0, 22.86, 10.16, 3.0),
                                    (14.0, 15.8, 7.9, 2.0)):
        out = _calc("bethe_hole_coupler", freq_ghz=f_ghz, a_mm=a_mm, b_mm=b_mm,
                    hole_diameter_mm=d_mm)
        subs = {a_s: a_mm * 1e-3, b_s: b_mm * 1e-3, f_s: f_ghz * 1e9,
                d_s: d_mm * 1e-3}
        c_sym = _f(sp.N(c_expr.subs(subs), 25))
        _assert_relim(out["c_strong"], c_sym, 1e-9, "c_strong")
        _assert_relim(out["coupling_db"], -20.0 * math.log10(c_sym), 1e-6,
                      "coupling_db")
        c_iso_sym = _f(sp.N(prefac.subs(subs)
                            * sp.Abs(term_e.subs(subs) - term_m.subs(subs)), 25))
        _assert_relim(out["c_iso"], c_iso_sym, 1e-9, "c_iso")
        _assert_relim(out["directivity_db"],
                      20.0 * math.log10(c_sym / c_iso_sym), 1e-6,
                      "directivity_db")
        _assert_relim(out["f_design_ghz"],
                      _f(sp.N((_C0_M_S / (sp.sqrt(2) * a_s)).subs(
                          {a_s: a_mm * 1e-3}), 25)) / 1e9, 1e-7, "f_design")
    # 综合：solve c(d)=10^(-C/20) → d（符号幂律反解）
    f_ghz, a_mm, b_mm = 10.0, 22.86, 10.16
    subs = {a_s: a_mm * 1e-3, b_s: b_mm * 1e-3, f_s: f_ghz * 1e9}
    k_sym = sp.simplify(c_expr / d_s ** 3)
    k_val = sp.N(k_sym.subs(subs), 30)
    d_want = _f(sp.N((sp.Float(10.0 ** (-40.0 / 20.0), 25) / k_val)
                     ** (sp.Rational(1, 3)), 30)) * 1e3
    out = _calc("bethe_hole_coupler", freq_ghz=f_ghz, a_mm=a_mm, b_mm=b_mm,
                coupling_db=40.0)
    _assert_relim(out["hole_diameter_mm"], d_want, 1e-6, "synthesis d")


# ══════════ 11. circular_waveguide_mode_prop：besselj 零点 ══════════


def test_circular_waveguide_mode_prop_bessel_zeros() -> None:
    """TE/TM 根=J_m'/J_m 零点 sympy nsolve（McMahon 种子）对拍 + 模式参量。

    oracle=符号推导独立路线：J_m'(x)=(J_{m−1}−J_{m+1})/2 导数恒等式
    符号证明；零点由 sympy.nsolve 从 McMahon 渐近种子独立求根（对照
    实现的 scipy.special.jn_zeros/jnp_zeros 路线）；fc/λg/Z_mode 符号
    求值；TE02/TM11 同根简并 Z_TE·Z_TM=η² 符号+数值双面。
    """
    x_s = sp.symbols("x", positive=True)
    for m in (0, 1, 2):
        dj = sp.diff(sp.besselj(m, x_s), x_s)
        assert sp.simplify(
            dj - (sp.besselj(m - 1, x_s) - sp.besselj(m + 1, x_s)) / 2) == 0

    def _seed(m: int, n: int, is_te: bool) -> float:
        """McMahon 交错不等式的括号中点种子（零点所在 π 区间的中点）。

        J_m 零点 x_{mn} ∈ ((n+(m−1)/2)π, (n+m/2)π)；J_m' 零点交错于
        ((n+m/2−5/4)π, (n+m/2−3/4)π)；m=0 的 J_0'≡−J_1（导数恒等式
        已证）根取 J_1 零点区间 (nπ, (n+1/2)π)。纯 π 有理式种子，与
        实现的 scipy.special.jn_zeros/jnp_zeros 路线完全独立。
        """
        if is_te:
            mid = ((n + sp.Rational(1, 4)) * sp.pi if m == 0
                   else (n + sp.Rational(m, 2) - 1) * sp.pi)
        else:
            mid = (n + sp.Rational(m, 2) - sp.Rational(1, 4)) * sp.pi
        return _f(sp.N(mid, 25))

    a_mm = 10.0
    cases = (("TE", 1, 1, 12.0), ("TM", 0, 1, 14.0),
             ("TE", 0, 1, 24.0), ("TE", 2, 1, 20.0))
    for mtype, m, n, f_ghz in cases:
        is_te = mtype == "TE"
        out = _calc("circular_waveguide_mode_prop", mode_type=mtype, m=m, n=n,
                    radius_mm=a_mm, f_ghz=f_ghz, conductivity_s_per_m=5.8e7)
        expr = sp.diff(sp.besselj(m, x_s), x_s) if is_te else sp.besselj(m, x_s)
        root = _f(sp.N(sp.nsolve(expr, _seed(m, n, is_te), prec=30), 25))
        _assert_relim(out["x_root"], root, 1e-11, f"{mtype}{m}{n} root")
        fc_sym = root * _C_MM_GHZ / (2 * sp.pi * a_mm)
        _assert_relim(out["fc_ghz"], _f(sp.N(fc_sym, 25)), 1e-9, "fc")
        lam0_mm = sp.N(_C_MM_GHZ / f_ghz, 40)
        ratio = sp.N(fc_sym / f_ghz, 40)
        lamg_sym = sp.N(lam0_mm / sp.sqrt(1 - ratio ** 2), 30)
        _assert_relim(out["lambda_g_mm"], _f(sp.N(lamg_sym, 25)), 1e-9,
                      "lambda_g")
        k0 = 2 * sp.pi * f_ghz * 1e9 / _C0_M_S
        beta_sym = 2 * sp.pi / (lamg_sym * 1e-3)
        eta_sym = sp.sqrt(_MU0 / _EPS0)
        z_sym = k0 * eta_sym / beta_sym if is_te else beta_sym * eta_sym / k0
        _assert_relim(out["z_mode_ohm"], _f(sp.N(z_sym, 25)), 1e-10, "z_mode")
    # 简并恒等：Z_TE·Z_TM=η²（TE01 与 TM11 同根 3.8317，符号+数值双面）
    k_s, b_s, e_s = sp.symbols("k beta eta", positive=True)
    assert sp.simplify(
        (k_s * e_s / b_s) * (b_s * e_s / k_s) - e_s ** 2) == 0
    out_te = _calc("circular_waveguide_mode_prop", mode_type="TE", m=0, n=1,
                   radius_mm=a_mm, f_ghz=24.0, conductivity_s_per_m=5.8e7)
    out_tm = _calc("circular_waveguide_mode_prop", mode_type="TM", m=1, n=1,
                   radius_mm=a_mm, f_ghz=24.0, conductivity_s_per_m=5.8e7)
    _assert_relim(out_te["x_root"], out_tm["x_root"], 1e-12, "简并根一致")
    _assert_relim(out_te["z_mode_ohm"] * out_tm["z_mode_ohm"],
                  _MU0 / _EPS0, 1e-9, "Z_TE·Z_TM=η²")


# ══════════ 12. free_space_path_loss：FSPL 常数恒等式 ══════════


def test_free_space_path_loss_constant_identity() -> None:
    """FSPL=(4πd/λ)²≡(4πdf/c)² 形恒等符号证明 + 常数形/倍距律数值对拍。

    oracle=符号推导独立路线：λ=c/f 代换的 dB/线性两形态恒等由 simplify
    证明；教科书常数形 32.44+20lg(d_km)+20lg(f_MHz)（c≈3e8 圆化口径，
    与精确 SI 差 mdB 级如实钉 0.01dB 宽门）；倍距 +20lg2 律符号+数值。
    """
    d_s, f_s, c_s = sp.symbols("d f c", positive=True)
    fspl_db = 20 * sp.log(4 * sp.pi * d_s * f_s / c_s, 10)
    lam_s = c_s / f_s
    assert sp.simplify(fspl_db - 20 * sp.log(4 * sp.pi * d_s / lam_s, 10)) == 0
    lin = (4 * sp.pi * d_s * f_s / c_s) ** 2
    assert sp.simplify(lin - (4 * sp.pi * d_s / lam_s) ** 2) == 0
    assert sp.simplify(
        fspl_db.subs(d_s, 2 * d_s) - fspl_db - 20 * sp.log(2, 10)) == 0
    for d_m, f_hz, excess in ((1000.0, 1e9, 0.0), (1.0, 2.4e9, 3.0),
                              (5000.0, 900e6, -2.0)):
        out = _calc("free_space_path_loss", distance_m=d_m, freq_hz=f_hz,
                    excess_loss_db=excess)
        subs = {d_s: d_m, f_s: f_hz, c_s: _C0_M_S}
        _assert_relim(out["wavelength_m"],
                      _f(sp.N(lam_s.subs(subs), 25)), 1e-11, "lambda")
        _assert_relim(out["fspl_db"], _f(sp.N(fspl_db.subs(subs), 25)),
                      1e-11, "fspl_db")
        _assert_relim(out["fspl_linear"], _f(sp.N(lin.subs(subs), 25)),
                      1e-11, "fspl_linear")
        _assert_relim(out["total_loss_db"],
                      _f(sp.N(fspl_db.subs(subs), 25)) + excess, 1e-11,
                      "total")
        _assert_abs(out["identity_residual_db"], 0.0, 1e-12, "identity resid")
    # 精确 SI 锚（实现 docstring 教科书锚点）：1km@1GHz=92.4477832dB
    out = _calc("free_space_path_loss", distance_m=1000.0, freq_hz=1e9)
    _assert_relim(out["fspl_db"], 92.4477832, 1e-9, "SI anchor")
    # 教科书常数形（宽门 0.01dB——常数圆化口径如实）
    textbook = 32.44 + 20.0 * math.log10(1.0) + 20.0 * math.log10(1000.0)
    _assert_abs(out["fspl_db"], textbook, 0.01, "textbook const form")
    # 倍距 +6.0205999dB 数值律
    out2 = _calc("free_space_path_loss", distance_m=2000.0, freq_hz=1e9)
    _assert_abs(out2["fspl_db"] - out["fspl_db"], 20.0 * math.log10(2.0),
                1e-9, "doubling law")
