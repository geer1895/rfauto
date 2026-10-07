"""TF-4 双通带 SIR 内核单测（round5 §4.2 判据）。

裁判口径（#118 双路径/独立来源，详见模块 docstring 偏差登记）：
- 谐振条件：tan²(atan(√Rz))=Rz 逐位；闭式极点处 residual ≤1e-12·Z1。
- Z_in 双路径：闭式 vs ABCD 级联（模块内两条独立代数路径）rel ≤1e-12
  （实测 1.1e-15）。
- 杂散比 f_s1/f0 = π/atan(√Rz)−1：测试内 brentq 独立求根互证 rel ≤1e-9
  （实测 ≤5e-16）；UIR 锚 Rz=1 → 3.0（λ/4 UIR 杂散谱 3f0 口径）。
  任务书引述的 "π/(2·atan(√Rz))−1" 在 Rz=1 给 1 而非 3，判为转述笔误，
  模块按自推导+求根钉死（docstring 已登记）。
- 双带映射往返：rz_from_band_ratio ∘ band_ratio_from_rz rel ≤1e-9
  （实测逐位 0）；锚 r=3 ⇔ Rz=1、r=5 ⇔ Rz=1/3。
- 双峰频响：J-inverter ABCD 级联，峰位 vs f1/f2 预声明 ±5% 门
  （实测 ≤0.01%，500× 余量）；b̄ 数值差分为声明近似源，以 UIR 闭式
  π/(4·Z_S) 锚定。
"""
from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import brentq

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import sir_filter as sir

F1 = 2.4e9
Z0 = 50.0


# ─── 1. 谐振条件与恒等式 ─────────────────────────────────────────────────────


def test_resonance_identity_equal_length_exact():
    # tan²(atan(√Rz)) = Rz 逐位（任务书判据）
    for rz in (0.05, 0.25, 0.5, 1.0, 2.0, 4.0, 100.0):
        theta = sir.sir_theta_equal(rz)
        assert math.tan(theta) ** 2 == pytest.approx(rz, rel=1e-12)
    assert sir.sir_theta_equal(1.0) == math.pi / 4  # UIR 逐位锚


def test_resonance_residual_at_closed_form_pole():
    # 等长与不等长（θ2=atan(Rz/tanθ1)）闭式极点处 residual ≤1e-12·Z1
    for rz in (0.25, 0.5, 1.0, 2.0):
        t1 = 0.4
        t2 = math.atan(rz / math.tan(t1))
        res = sir.sir_resonance_residual(50.0, 50.0 / rz, t1, t2)
        assert abs(res) <= 1e-12 * 50.0
    theta = sir.sir_theta_equal(0.5)
    assert abs(sir.sir_resonance_residual(50.0, 100.0, theta, theta)) <= 1e-12 * 50.0


def test_zin_closed_vs_abcd_dual_path():
    # #118 双路径：闭式 vs ABCD 级联，相对差 ≤1e-12（实测 1.1e-15）
    for zr in (0.25, 0.5, 1.0, 2.0):
        z1, z2 = 50.0, 50.0 / zr
        for t1 in (0.2, 0.5, 0.8):
            for t2 in (0.3, 0.7):
                a = sir.sir_zin(z1, z2, t1, t2)
                b = sir.sir_zin_abcd(z1, z2, t1, t2)
                assert a.real == 0.0 and b.real == pytest.approx(0.0, abs=1e-8 * abs(b))
                assert a == pytest.approx(b, rel=1e-12)


def test_zin_divergence_near_pole():
    # 极点邻域 Z_in 发散（并联谐振语义 sanity）
    theta = sir.sir_theta_equal(0.5)
    off = 1e-3
    zin = sir.sir_zin(50.0, 100.0, theta + off, theta + off)
    assert abs(zin) > 10.0 * 50.0
    # 闭式极点处 |Z_in| 巨大且 residual 逐位级（den==0 精确零对浮点乘法
    # 顺序敏感，不作断言——guard 为 defensive 分支，docstring 已声明）
    resid = sir.sir_resonance_residual(50.0, 100.0, theta, theta)
    assert abs(resid) <= 1e-12 * 50.0


# ─── 2. 杂散比与双带映射 ─────────────────────────────────────────────────────


def test_spurious_ratio_uir_limit_exact():
    # Rz=1（UIR）→ f_s1/f0 = 3（λ/4 UIR 杂散谱 3f0,5f0,... 口径，逐位锚）
    assert sir.band_ratio_from_rz(1.0) == pytest.approx(3.0, rel=1e-12)


def test_spurious_ratio_vs_numeric_root():
    # 独立路径：brentq 求杂散支单根（tan(θr) = −√Rz）vs 闭式，rel ≤1e-9（任务书门）
    # 括号必须从根下方的最后一个 tan 极点之上起（跨极点的假符号变化
    # 会让 brentq 收敛到不连续点本身，rz=0.25 实测收敛到 r=π/(2θ)）
    for rz in (0.25, 0.5, 1.0, 2.0, 4.0):
        theta = sir.sir_theta_equal(rz)
        ratio = sir.band_ratio_from_rz(rz)

        def eq(r: float, theta: float = theta, rz: float = rz) -> float:
            return math.tan(theta * r) / math.sqrt(rz) + 1.0

        excess = (ratio * theta - math.pi / 2.0) % math.pi
        r_lo = (ratio * theta - excess) / theta + 1e-9  # 根下方最后一个极点之上
        assert r_lo < ratio
        root = brentq(eq, r_lo, ratio + 1e-9, xtol=1e-15, rtol=8.9e-16)
        assert root == pytest.approx(ratio, rel=1e-9)


def test_band_ratio_roundtrip_exact():
    # 双带映射往返（任务书门 rel 1e-9；实测逐位 0）
    for ratio in (1.5, 2.4, 3.0, 3.5, 5.0, 8.0):
        rz = sir.rz_from_band_ratio(ratio)
        back = sir.band_ratio_from_rz(rz)
        assert back == pytest.approx(ratio, rel=1e-9)
    # 锚点：r=3 ⇔ UIR（Rz=1，float 下 rel 1e-15——tan(π/4) 非精确 1）；
    # r=5 ⇔ Rz=1/3（tan²(π/6)）
    assert sir.rz_from_band_ratio(3.0) == pytest.approx(1.0, rel=1e-15)
    assert sir.rz_from_band_ratio(5.0) == pytest.approx(1.0 / 3.0, rel=1e-12)


def test_dual_band_is_monotone():
    # 频率比越大 → Rz 越小（θ 越短），单调自洽
    ratios = np.linspace(1.2, 10.0, 89)
    rzs = [sir.rz_from_band_ratio(float(r)) for r in ratios]
    assert all(b < a for a, b in pairwise(rzs))


# ─── 3. 不等长半闭式 ─────────────────────────────────────────────────────────


def test_theta2_unequal_recovers_equal_length():
    # θ1 取等长闭式值 → 解回 θ2 = θ1（κ=−1 情形，根 = π/(1+r) 闭式）
    ratio = 3.5
    rz = sir.rz_from_band_ratio(ratio)
    theta = sir.sir_theta_equal(rz)
    theta2, rz2 = sir.sir_theta2_unequal(theta, ratio)
    assert theta2 == pytest.approx(theta, rel=1e-9)
    assert rz2 == pytest.approx(rz, rel=1e-9)


def test_theta2_unequal_dual_resonance():
    # θ1=π/10、r=4：解出的 (θ2, Rz) 使两频率同时并联谐振（≤1e-9）
    ratio, t1 = 4.0, math.pi / 10
    theta2, rz = sir.sir_theta2_unequal(t1, ratio)
    assert rz > 0.0
    eq_fund = math.tan(t1) * math.tan(theta2) - rz
    eq_spur = math.tan(ratio * t1) * math.tan(ratio * theta2) - rz
    assert abs(eq_fund) <= 1e-9
    assert abs(eq_spur) <= 1e-9
    # 几何守卫：θ2 落 (0, π/2)，几何可构造
    geom = sir.sir_geometry(50.0, 50.0 / rz, t1, theta2, f0_hz=F1)
    assert 0.0 < geom.theta2_rad < math.pi / 2


# ─── 4. 几何与耦合面 ─────────────────────────────────────────────────────────


def test_geometry_dataclass_and_miniaturization():
    # rz<1（θ<45°）→ 短于 UIR（miniaturization_frac>0）；rz>1 → 长于 UIR
    short = sir.sir_geometry(50.0, 100.0, sir.sir_theta_equal(0.5), sir.sir_theta_equal(0.5), F1)
    long_ = sir.sir_geometry(50.0, 25.0, sir.sir_theta_equal(2.0), sir.sir_theta_equal(2.0))
    assert short.rz == pytest.approx(0.5, rel=1e-15)
    assert short.miniaturization_frac == pytest.approx(1 - 2 * math.degrees(math.atan(math.sqrt(0.5))) / 90.0, rel=1e-12)
    assert short.miniaturization_frac > 0.0 > long_.miniaturization_frac
    d = short.to_dict()
    assert d["f0_hz"] == F1 and d["rz"] == pytest.approx(0.5, rel=1e-15)
    assert sir.sir_geometry(50.0, 50.0, math.pi / 4, math.pi / 4).f0_hz is None  # 判缺失 is not None


def test_coupling_formulas_recycle():
    # Qe=g0g1/FBW、k12=FBW/√(g1g2)（测试内独立重写）+ UIR 斜率锚 π/(4·Z_S)
    g = [1.0, math.sqrt(2.0), math.sqrt(2.0), 1.0]
    fbw = 0.05
    slope = sir.sir_slope(Z0, Z0, math.pi / 4, math.pi / 4, F1)
    assert slope == pytest.approx(math.pi / (4 * Z0), rel=1e-8)  # UIR=λ/4 stub 闭式锚
    c = sir.sir_coupling(g, fbw, slope, Z0)
    qe_expect = g[0] * g[1] / fbw
    k12_expect = fbw / math.sqrt(g[1] * g[2])
    assert c.qe == pytest.approx(qe_expect, rel=1e-12)
    assert c.k12 == pytest.approx(k12_expect, rel=1e-12)
    assert c.j01 == pytest.approx(math.sqrt(slope / (qe_expect * Z0)), rel=1e-12)
    assert c.j12 == pytest.approx(k12_expect * slope, rel=1e-12)
    assert c.to_dict()["k12"] == pytest.approx(k12_expect, rel=1e-12)


# ─── 5. 双峰频响验证面（预声明门 ±5%，见文件头）──────────────────────────────


def _peaks(freqs: np.ndarray, s21: np.ndarray, floor: float = 0.2) -> list[float]:
    p = np.abs(s21) ** 2
    return [float(freqs[i]) for i in range(1, p.size - 1) if p[i] > p[i - 1] and p[i] >= p[i + 1] and p[i] > floor]


def test_two_pole_dual_band_peaks_gate():
    # 预声明门：双峰位置 vs f1/f2 rel ≤5%（实测 ≤0.01%）
    ratio = 3.5
    f2 = F1 * ratio
    rz = sir.rz_from_band_ratio(ratio)
    theta = sir.sir_theta_equal(rz)
    geom = sir.sir_geometry(Z0, Z0 / rz, theta, theta, f0_hz=F1)
    slope = sir.sir_slope(Z0, Z0 / rz, theta, theta, F1)
    g = [1.0, math.sqrt(2.0), math.sqrt(2.0), 1.0]
    coupling = sir.sir_coupling(g, 0.05, slope, Z0)
    grid = np.concatenate(
        [np.linspace(0.93 * F1, 1.07 * F1, 40001), np.linspace(0.93 * f2, 1.07 * f2, 40001)]
    )
    _, s21 = sir.sir_two_pole_sparams(grid, geom, coupling, Z0)
    peaks = _peaks(grid, s21)
    assert peaks, "双带网无峰（响应异常）"
    f1_errs = [abs(p / F1 - 1.0) for p in peaks if p < 0.5 * (F1 + f2)]
    f2_errs = [abs(p / f2 - 1.0) for p in peaks if p >= 0.5 * (F1 + f2)]
    assert f1_errs and min(f1_errs) <= 0.05
    assert f2_errs and min(f2_errs) <= 0.05
    # 峰位远优于门（登记实测余量：≤0.01%）
    assert min(f1_errs) <= 1e-3 and min(f2_errs) <= 1e-3


def test_two_pole_requires_f0():
    geom = sir.sir_geometry(Z0, Z0, math.pi / 4, math.pi / 4)  # f0 缺省 None
    coupling = sir.sir_coupling([1.0, math.sqrt(2.0), math.sqrt(2.0), 1.0], 0.05, math.pi / 200.0, Z0)
    with pytest.raises(ValueError):
        sir.sir_two_pole_sparams(np.array([F1]), geom, coupling, Z0)


# ─── 6. 守卫面 ───────────────────────────────────────────────────────────────


def test_boundary_guards():
    # rz<=0（任务书）；θ ∉ (0,π/2)（任务书）；fbw ∉ (0,1)（任务书）；ratio<=1
    with pytest.raises(ValueError):
        sir.sir_theta_equal(0.0)
    with pytest.raises(ValueError):
        sir.sir_theta_equal(-0.5)
    # sir_zin 对外推域（θ 出 (0,π/2)）按 docstring 放行，不做守卫断言
    with pytest.raises(ValueError):
        sir.sir_geometry(50.0, 50.0, 0.0, math.pi / 4)  # θ=0 拒
    with pytest.raises(ValueError):
        sir.sir_geometry(50.0, 50.0, math.pi / 2, math.pi / 4)  # θ=π/2 拒
    with pytest.raises(ValueError):
        sir.sir_geometry(0.0, 50.0, 0.3, 0.4)
    with pytest.raises(ValueError):
        sir.sir_coupling([1.0, 1.0, 1.0, 1.0], 1.2, 0.1, Z0)
    with pytest.raises(ValueError):
        sir.rz_from_band_ratio(1.0)
    with pytest.raises(ValueError):
        sir.sir_theta2_unequal(math.pi / 2, 3.0)  # θ1 越界（r·θ1<π/2 要求）
    with pytest.raises(ValueError):
        sir.sir_coupling([1.0, 1.0, 1.0], 0.1, 0.1, Z0)  # len(g)≠4
    with pytest.raises(ValueError):
        sir.sir_theta_equal(True)  # bool 拒收（df7+⑯）
    with pytest.raises(ValueError):
        sir.sir_geometry(50.0, 50.0, float("nan"), 0.4)
