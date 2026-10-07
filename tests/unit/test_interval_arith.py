"""S-4 区间算术试点单测（round3 §3.1 S-4 判据：包含恒等式 + 宽度单调 + certify 对拍）。

裁判口径（#118：双路径/独立实现，不自证）：
- 四则裁判 = 测试内 numpy 端点枚举 + nextafter 外扩 1 ulp（单次乘/除的
  精确积在舍入积 0.5 ulp 内，外扩后必然包含真极值）——与 mpmath.iv
  定向舍入完全独立的两条路径；
- certify_design 对拍 = service/certify_design.py 的 Lipschitz 保守带
  口径（中心 ± L·Δx，L 有限差分估计）在解析函数上复算——非调 service
  （certify_design 只读，#222 语境钉），公式按其源码逐行复刻。

对拍结论（试点留档，round3 S-4 行「对拍收敛差→后批 affine 裁决」）：
① 仿射 f=ax+b 两法等宽（区间算术无过保守，affine 收益为零）；② 单调
非线性 f=x² 区间算术严格更窄；③ 包含关系一致（真值范围都在两者内）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("mpmath")  # 非核心依赖（lit-mining 附带）→ 缺装如实 skip

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import interval_arith as ia


def _encloses_tol(outer: ia.IVal, inner: ia.IVal, tol: float = 1e-12) -> bool:
    """容差版包含（导出端点外扩 1 ulp 后，精确 ⊆ 在 ulp 级可能反向）。"""
    return outer.lo <= inner.lo + tol * max(1.0, abs(inner.lo)) and outer.hi >= (
        inner.hi - tol * max(1.0, abs(inner.hi))
    )

# ─── 0. IVal 构造与守卫 ──────────────────────────────────────────────────────


def test_ival_guards_and_json():
    with pytest.raises(ValueError):
        ia.ival(2.0, 1.0)  # lo>hi
    with pytest.raises(ValueError):
        ia.ival(float("nan"), 1.0)
    with pytest.raises(ValueError):
        ia.ival(float("inf"), 1.0)
    with pytest.raises(ValueError):
        ia.ival(True, 1.0)  # bool 显式拒收（df7+⑯）
    # 点区间与退化合法
    assert ia.point(1.5) == ia.IVal(1.5, 1.5)
    d = ia.ival(1.0, 2.0).to_dict()
    assert json.dumps(d) and d["width"] == pytest.approx(1.0)


# ─── 1. 四则：精确例 + 端点枚举独立裁判 ──────────────────────────────────────


def test_four_arithmetic_exact_degenerate_points():
    # 退化点运算：真结果为可精确表示的点 → 导出端点外扩 ≤1ulp 后仍含点、宽 ~0
    r = ia.iadd(ia.point(2.0), ia.point(3.0))
    assert r.contains_point(5.0) and r.width() < 1e-12
    s = ia.isub(ia.point(2.0), ia.point(3.0))
    assert s.contains_point(-1.0) and s.width() < 1e-12
    m = ia.imul(ia.point(2.0), ia.point(3.0))
    assert m.contains_point(6.0) and m.width() < 1e-12
    q = ia.idiv(ia.point(1.0), ia.point(4.0))
    assert q.contains_point(0.25) and q.width() < 1e-12


def test_iadd_isub_exact_endpoints():
    # 整数端点二进制精确 → 定向舍入无损，宽度不超真宽度（无膨胀）
    r = ia.iadd(ia.ival(1, 2), ia.ival(10, 20))
    assert r.contains_point(11.0) and r.contains_point(22.0)
    assert r.encloses(ia.ival(11.0, 22.0)) and r.width() < 11.0 + 1e-12
    s = ia.isub(ia.ival(1, 2), ia.ival(10, 20))
    assert s.contains_point(-19.0) and s.contains_point(-8.0)
    assert s.width() < 11.0 + 1e-12


def _ref_mul(lo_a: float, hi_a: float, lo_b: float, hi_b: float) -> ia.IVal:
    """四则独立裁判：float 端点四积枚举 + 单次舍入 0.5ulp → 外扩 1ulp。"""
    prods = [lo_a * lo_b, lo_a * hi_b, hi_a * lo_b, hi_a * hi_b]
    return ia.IVal(
        math.nextafter(min(prods), -math.inf),
        math.nextafter(max(prods), math.inf),
    )


def test_imul_mixed_sign_vs_enumeration_referee():
    # 双路径：解析真范围（手算端点积）vs mpmath.iv 定向舍入
    cases = [
        ((1.0, 2.0), (3.0, 4.0), 3.0, 8.0),
        ((-1.0, 2.0), (-3.0, 4.0), -6.0, 8.0),
        ((-2.0, -0.5), (2.0, 5.0), -10.0, -1.0),
    ]
    for (la, ha), (lb, hb), true_lo, true_hi in cases:
        got = ia.imul(ia.ival(la, ha), ia.ival(lb, hb))
        ref = _ref_mul(la, ha, lb, hb)
        # 两路径都包含解析真范围
        assert got.contains_point(true_lo) and got.contains_point(true_hi)
        assert ref.lo <= true_lo and ref.hi >= true_hi
        # 宽度一致到浮点容差（互为独立实现的收敛证据）
        assert got.width() == pytest.approx(ref.width(), rel=1e-9, abs=1e-12)


def test_idiv_and_zero_divisor_guard():
    q = ia.idiv(ia.ival(1, 2), ia.ival(2, 4))
    assert q.contains_point(0.25) and q.contains_point(0.5)
    assert q.encloses(ia.ival(0.25, 0.5))
    for bad in (ia.ival(-1.0, 1.0), ia.ival(0.0, 2.0), ia.point(0.0)):
        with pytest.raises(ValueError):
            ia.idiv(ia.ival(1, 2), bad)
    with pytest.raises(ValueError):
        ia.iadd(ia.ival(1, 2), (0.0, 1.0))  # 非 IVal 入参显式拒绝


# ─── 2. 单调函数区间化（exp/sqrt/sin 正单调域） ──────────────────────────────


def test_iexp_enclosure_monotone_exact_range():
    r = ia.iexp(ia.ival(0.0, 1.0))
    assert r.contains_point(1.0) and r.contains_point(math.e)
    # 单调递增 → 端点即精确范围（宽度不超 (e−1) + 数 ulp）
    assert r.width() <= (math.e - 1.0) + 1e-12
    with pytest.raises(ValueError):
        ia.iexp("x")  # 非 IVal


def test_isqrt_domain_and_endpoints():
    r = ia.isqrt(ia.ival(4.0, 9.0))
    assert r.contains_point(2.0) and r.contains_point(3.0)
    assert r.width() <= 1.0 + 1e-12
    z = ia.isqrt(ia.ival(0.0, 4.0))  # 0 端点合法
    assert z.contains_point(0.0) and z.contains_point(2.0)
    with pytest.raises(ValueError):
        ia.isqrt(ia.ival(-0.1, 4.0))


def test_isin_monotone_increasing_and_decreasing_branches():
    inc = ia.isin_monotone(ia.ival(-0.5, 0.5))  # 递增分支 [−π/2, π/2]
    assert inc.contains_point(-math.sin(0.5)) and inc.contains_point(math.sin(0.5))
    assert inc.width() <= 2 * math.sin(0.5) + 1e-12
    dec = ia.isin_monotone(ia.ival(3.0, 4.0))  # 递减分支 (π/2, 3π/2)
    assert dec.contains_point(math.sin(3.0)) and dec.contains_point(math.sin(4.0))
    assert dec.lo < dec.hi


def test_isin_monotone_spanning_branch_rejected():
    # [1,2] 含 π/2（递增→递减拐点）→ 显式拒绝，不产过保守外包围
    with pytest.raises(ValueError):
        ia.isin_monotone(ia.ival(1.0, 2.0))
    # 跨多整支同样拒绝
    with pytest.raises(ValueError):
        ia.isin_monotone(ia.ival(0.0, 10.0))


# ─── 3. 包含恒等式 + 宽度单调性（Moore 基本定理实证） ────────────────────────


def test_pipeline_contains_true_value_identity():
    rng = np.random.default_rng(20260927)
    inputs = {"x": ia.ival(1.0, 2.0), "y": ia.ival(0.5, 1.0)}
    ops = [
        {"op": "add", "out": "t", "a": "x", "b": "y"},
        {"op": "mul", "out": "m", "a": "t", "b": "x"},
    ]
    env = ia.propagate(inputs, ops)
    final = env["values"][env["final"]]
    for _ in range(20):
        x = rng.uniform(1.01, 1.99)
        y = rng.uniform(0.51, 0.99)
        assert final.contains_point((x + y) * x)  # 真值 ∈ 区间（包含恒等式）
    with pytest.raises(ValueError):
        ia.propagate(inputs, [{"op": "mul", "out": "m", "a": "t", "b": "nope"}])
    with pytest.raises(ValueError):
        ia.propagate(inputs, [{"op": "pow", "out": "m", "a": "x", "b": "y"}])


def test_width_monotonicity_widen_inputs():
    base_x, wide_x = ia.ival(1.0, 2.0), ia.ival(0.5, 3.0)
    b = ia.ival(0.5, 1.5)
    for fn in (ia.iadd, ia.isub, ia.imul, ia.idiv):
        if fn is ia.idiv:
            base, wide = fn(base_x, ia.ival(2.0, 4.0)), fn(wide_x, ia.ival(2.0, 4.0))
        else:
            base, wide = fn(base_x, b), fn(wide_x, b)
        assert wide.width() >= base.width() - 1e-15, f"{fn.__name__} 宽度单调性破"


def test_inclusion_monotonicity_subinterval():
    inner, outer = ia.ival(1.2, 1.8), ia.ival(1.0, 2.0)
    b = ia.ival(0.5, 1.5)
    assert outer.encloses(inner)  # 前置：子区间关系成立
    unary = {ia.iexp, ia.isqrt}
    for fn in (ia.iadd, ia.isub, ia.imul, ia.idiv, ia.iexp, ia.isqrt):
        if fn is ia.idiv:
            r_in, r_out = fn(inner, b), fn(outer, b)
        elif fn in unary:
            r_in, r_out = fn(inner), fn(outer)
        else:
            r_in, r_out = fn(inner, b), fn(outer, b)
        assert r_out.encloses(r_in), f"{fn.__name__} 包含单调性破"


# ─── 4. LC 谐振小管线（RF 语义试点） ─────────────────────────────────────────


def test_lc_resonance_pipeline_contains_true_value():
    rng = np.random.default_rng(20260927)
    l0, c0 = 10e-9, 100e-12  # 10 nH / 100 pF
    inputs = {"L": ia.ival(0.9 * l0, 1.1 * l0), "C": ia.ival(0.9 * c0, 1.1 * c0)}
    ops = [
        {"op": "mul", "out": "lc", "a": "L", "b": "C"},
        {"op": "call", "fn": "sqrt", "out": "s", "a": "lc"},
        {"op": "mul", "out": "d", "a": "s", "b": "x2pi"},
        {"op": "div", "out": "f", "a": "one", "b": "d"},
    ]
    env = ia.propagate({**inputs, "one": ia.point(1.0), "x2pi": ia.point(2 * math.pi)}, ops)
    f_iv = env["values"]["f"]
    assert env["final"] == "f"
    for _ in range(10):
        L = rng.uniform(0.91 * l0, 1.09 * l0)
        C = rng.uniform(0.91 * c0, 1.09 * c0)
        assert f_iv.contains_point(1.0 / (2 * math.pi * math.sqrt(L * C)))
    # 谐振频率量级合理（10nH·100pF → ~159 MHz；区间宽度 < ±6%）
    assert 140e6 < f_iv.lo < 145e6 and 172e6 < f_iv.hi < 180e6


# ─── 5. certify_design 同例对拍（口径只读复刻；结论留档 docstring） ──────────


def _certify_lipschitz_band(f, c: float, delta: float, n_grid: int = 9) -> ia.IVal:
    """复刻 service/certify_design.py 口径：L=单轴有限差分 max，带=中心±L·Δ。"""
    center = f(c)
    slopes = []
    for gi in range(n_grid):
        frac = gi / (n_grid - 1) * 2 - 1
        x = c + frac * delta
        slopes.append(abs(f(x) - center) / max(abs(frac) * delta, 1e-12))
    radius = max(slopes) * delta
    return ia.lipschitz_band(center, radius)


def test_certify_compare_affine_equal_width_both_contain():
    a_, b_, c, delta = 2.0, 1.0, 1.5, 0.1

    def f(x: float) -> float:
        return a_ * x + b_

    affine = ia.iadd(ia.imul(ia.point(a_), ia.ival(c - delta, c + delta)), ia.point(b_))
    cert = _certify_lipschitz_band(f, c, delta)
    true_lo, true_hi = f(c - delta), f(c + delta)  # 单调增 → 精确范围
    # ③ 包含关系一致：真范围都在两者内
    assert affine.contains_point(true_lo) and affine.contains_point(true_hi)
    assert cert.contains_point(true_lo) and cert.contains_point(true_hi)
    # ① 仿射两法等宽（±1e-9）
    assert affine.width() == pytest.approx(cert.width(), rel=1e-9, abs=1e-12)
    # 且区间算术 ⊆ Lipschitz 带（等宽情形，容差化 ulp 后仍成立）
    assert _encloses_tol(cert, affine)


def test_certify_compare_quadratic_ia_strictly_narrower():
    c, delta = 1.5, 0.5

    def f(x: float) -> float:
        return x * x  # x∈[1,2] 单调增

    box = ia.ival(c - delta, c + delta)
    ia_band = ia.imul(box, box)
    cert = _certify_lipschitz_band(f, c, delta)
    # ③ 两者都包含真范围 [1,4]
    for band in (ia_band, cert):
        assert band.contains_point(1.0) and band.contains_point(4.0)
    # ② 区间算术严格更窄（单调非线性：Lipschitz 带系统性偏宽）
    assert ia_band.width() < cert.width() - 1e-9
    assert _encloses_tol(cert, ia_band)


def test_certify_compare_width_monotonicity_parity():
    # 输入区间变宽 → 两法输出区间都不窄（宽度单调性跨法一致）
    c = 1.5

    def f(x: float) -> float:
        return x * x

    base_ia = base_cert = None
    for delta in (0.3, 0.6):
        box = ia.ival(c - delta, c + delta)
        ia_w = ia.imul(box, box).width()
        cert_w = _certify_lipschitz_band(f, c, delta).width()
        if base_ia is not None:
            assert ia_w >= base_ia - 1e-15
            assert cert_w >= base_cert - 1e-15
        base_ia, base_cert = ia_w, cert_w


def test_lipschitz_band_wrapper():
    band = ia.lipschitz_band(2.25, 1.75)
    assert band == ia.IVal(0.5, 4.0)
    with pytest.raises(ValueError):
        ia.lipschitz_band(1.0, -0.1)


# ─── 6. mpmath 惰性通道钉（#139：monkeypatch，不依赖真实卸载） ────────────────


def test_mpmath_channel_pinning(monkeypatch):
    def _missing():
        raise ImportError("mpmath not installed (simulated)")

    monkeypatch.setattr(ia, "_import_mpmath", _missing)
    with pytest.raises(ImportError):
        ia.iadd(ia.point(1.0), ia.point(2.0))
    with pytest.raises(ImportError):
        ia.isin_monotone(ia.ival(-0.5, 0.5))
