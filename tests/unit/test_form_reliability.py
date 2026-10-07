"""XD-11 FORM/SORM 可靠度内核单测（core/form_reliability.py）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * 解析回收锚 1（Hasofer-Lind 教科书线性面）：g=3−x1−2·x2（独立
    标准正态）→ β=3/√5、设计点=(3/5)·(1,2)、α=(1,2)/√5——线性面
    HL-RF 一步到解、闭式逐位一致（1e-9），Pf 对拍 scipy.stats.norm.sf；
  * 解析回收锚 2（R−S 应力-强度模型）：R~N(200,20)、S~N(150,30) →
    β=(200−150)/√(20²+30²)=50/√1300，Pf=Φ(−β) 与 norm.sf 对照；
  * MC 对拍锚（非线性面，30% 预声明带）：g=2.5−x1−0.05·x2²（弱
    二次非线性）——FORM 一阶对非线性面有方法学偏差，docstring/规格
    预声明 30% 相对带；1e6 点固定种子 MC（seed=20261004，PCG64 跨
    平台流稳定）+ Gauss 求积精确值双裁判（实测偏差 ~15%）。
    **选面注记（2026-10-04 预验实测）**：规格例示的中心化乘积面
    g=x1·x2−c 不作 MC 锚——实测 FORM 偏差 45%（μ=(2,2) 偏置）到
    17×+（中心化：梯度在均值处为零且双叶失效域一阶切平面根本不
    覆盖），超出 30% 方法学带是 FORM 的诚实边界（模块 docstring
    预声明），不是实现缺陷；中心化乘积面经显式 u0 逃生阀单钉
    （β=√(2c) 解析回收）。
  * 数值件：Acklam 逆 CDF 常数逐位对拍 scipy.stats.norm.ppf（≤1e-8
    abs，防常数抄写笔误）；erfc 尾式 Pf 对拍 norm.sf（1e-15 量级）。
  * 病态面如实不收敛不抛（#122）：常数面 g≡±1 → converged=False、
    β=±inf、Pf=0/1；非有限 callable 值显式 ValueError（不吞）。
  * SORM：凸面（κ>0）β_sorm≥β 单调性弱钉 + κ 与解析 Hessian 回收
    （g=c+x2²−x1 → κ=2 精确，二次面二阶差分无截断误差）；Breitung
    适用域外（1+β·κ≤0 强凹面）显式 ValueError；n=1 无切维恒等；
    FORM 未收敛显式拒绝外插。
  * 注册键 form_beta_linear：canonical 线性面经 service JSON 出口
    与闭式 β 双路径互证（beta/beta_closed_form 逐位一致）+ 零 σ
    域守卫 ok=False。

确定性：无网络、无真机、无文件 IO；MC 固定种子 numpy Generator
（runs/research_seats_20261004/s6_wave2/ 预验脚本实测后锚值写死）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import integrate, stats

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.form_reliability import (
    _norm_ppf,
    form_beta,
    sorm_beta_correction,
)

# ─── 解析回收锚 1：Hasofer-Lind 线性面 ────────────────────────────────────

def test_linear_anchor_bitwise():
    """g=3−x1−2·x2（独立标准正态）：β=3/√5、u*=(3/5)(1,2)、α=(1,2)/√5。

    闭式推导（独立于实现）：安全 g>0、失效 x1+2x2>3；u-space 最近点
    u*=β·α，α=a·σ/||a·σ||=(1,2)/√5，β=(c−aᵀμ)/||aσ||=3/√5。
    """
    res = form_beta(lambda x: 3.0 - x[0] - 2.0 * x[1], [0.0, 0.0], [1.0, 1.0])
    assert res.converged
    beta_exact = 3.0 / math.sqrt(5.0)
    assert res.beta == pytest.approx(beta_exact, abs=1e-9)
    # 设计点 x*=u*（μ=0, σ=1）：逐位 (3/5)·(1,2)
    assert res.design_point_x == pytest.approx([0.6, 1.2], abs=1e-9)
    assert res.design_point_u == pytest.approx([0.6, 1.2], abs=1e-9)
    # α=失效方向单位灵敏度 =(1,2)/√5
    assert res.alpha == pytest.approx(
        [1.0 / math.sqrt(5.0), 2.0 / math.sqrt(5.0)], abs=1e-9)
    # Pf=Φ(−β) 对拍 scipy（独立路径）
    assert res.pf_form == pytest.approx(stats.norm.sf(beta_exact), rel=1e-9)


def test_linear_anchor_alpha_sensitivity_scaling():
    """α 指数语义弱钉：x2 系数大 → |α_2|>|α_1|（x2 把 Pf 拖得更狠）。"""
    res = form_beta(lambda x: 3.0 - x[0] - 2.0 * x[1], [0.0, 0.0], [1.0, 1.0])
    assert abs(res.alpha[1]) > abs(res.alpha[0])
    # α 单位范数 + 与 u* 平行同向（线性面 u*=β·α 恒等式）
    assert np.linalg.norm(res.alpha) == pytest.approx(1.0, abs=1e-9)
    assert float(res.alpha @ res.design_point_u) == pytest.approx(
        res.beta, abs=1e-9)


# ─── 解析回收锚 2：R−S 应力-强度模型 ──────────────────────────────────────

def test_rs_stress_strength_anchor():
    """g=R−S，R~N(200,20)、S~N(150,30)：β=50/√1300，Pf 对拍 norm.sf。"""
    res = form_beta(lambda x: x[0] - x[1], [200.0, 150.0], [20.0, 30.0])
    assert res.converged
    beta_exact = 50.0 / math.sqrt(1300.0)
    assert res.beta == pytest.approx(beta_exact, abs=1e-9)
    assert res.pf_form == pytest.approx(stats.norm.sf(beta_exact), rel=1e-9)
    # α=−∇g·σ/||∇g·σ||=(−20,30)/√1300：降 R 抬 S 方向=失效方向
    assert res.alpha == pytest.approx(
        [-20.0 / math.sqrt(1300.0), 30.0 / math.sqrt(1300.0)], abs=1e-9)
    # 设计点回代落在极限状态面上（g(x*)=0）
    assert 200.0 + 20.0 * res.design_point_u[0] - (
        150.0 + 30.0 * res.design_point_u[1]) == pytest.approx(0.0, abs=1e-8)


# ─── MC 对拍锚：非线性面（30% 预声明带） ─────────────────────────────────

def test_mc_nonlinear_anchor_band_30pct():
    """g=2.5−x1−0.05·x2²：FORM Pf vs 1e6 固定种子 MC 相对差 <30%。

    预声明带（模块 docstring 同款）：FORM 一阶对非线性面有方法学
    偏差（本面实测 ~15%，切平面低估了 x2² 把失效域往安全侧推的
    质量）；Pf≈0.0073 落规格档 [1e-3, 1e-1]。双裁判：MC（seed=
    20261004，1e6 点）+ Gauss 求积精确值 ∫φ(t)Φ(0.05t²−2.5)dt。
    """
    c, k = 2.5, 0.05
    res = form_beta(lambda x: c - x[0] - k * x[1] ** 2, [0.0, 0.0], [1.0, 1.0])
    assert res.converged
    # FORM 设计点=(c,0)（对称轴，u2*=0），β=c（闭式：面在该点梯度=1）
    assert res.beta == pytest.approx(c, abs=1e-9)

    rng = np.random.default_rng(20261004)
    x = rng.normal(0.0, 1.0, size=(1_000_000, 2))
    pf_mc = float(np.mean(c - x[:, 0] - k * x[:, 1] ** 2 < 0.0))
    assert 1e-3 <= pf_mc <= 1e-1, f"MC Pf 落出规格档: {pf_mc}"
    assert abs(res.pf_form / pf_mc - 1.0) < 0.30, (
        f"FORM vs MC 相对差超 30% 预声明带: {res.pf_form} vs {pf_mc}")

    # Gauss 求积精确值（独立解析裁判，非 MC 抽样误差）
    pf_exact, _ = integrate.quad(
        lambda t: stats.norm.pdf(t) * stats.norm.cdf(k * t * t - c), -8, 8)
    assert abs(res.pf_form / pf_exact - 1.0) < 0.30


def test_centered_product_surface_u0_escape():
    """中心化乘积面 g=x1·x2+3.2：显式 u0 逃生阀 → β=√(2·3.2) 解析回收。

    均值处 ∇g=(x2,x1)=(0,0)——黑盒差分起点无方向（converged=False
    如实）；u0=(2,−2) 起跑后 HL-RF 收敛到最近点 (√3.2,−√3.2)。
    设计点范数=min u1²+u2² s.t. u1·u2=−3.2（AM-GM：|u1|=|u2|=√3.2）。
    """
    res0 = form_beta(lambda x: x[0] * x[1] + 3.2, [0.0, 0.0], [1.0, 1.0])
    assert res0.converged is False  # 起点零梯度：如实不收敛
    res = form_beta(lambda x: x[0] * x[1] + 3.2, [0.0, 0.0], [1.0, 1.0],
                    u0=[2.0, -2.0])
    assert res.converged
    assert res.beta == pytest.approx(math.sqrt(6.4), abs=1e-6)
    assert res.design_point_x == pytest.approx(
        [math.sqrt(3.2), -math.sqrt(3.2)], abs=1e-6)
    # 注：此面 FORM Pf 与真值差 ~17×（双叶失效域，模块 docstring 诚实
    # 边界）——本钉只回收设计点几何，不钉 Pf。


# ─── 数值件：正态 CDF/逆 CDF ──────────────────────────────────────────────

def test_norm_ppf_matches_scipy():
    """Acklam 常数逐位防笔误：对拍 scipy.stats.norm.ppf ≤1e-8 abs。

    覆盖三区段（下尾/中央/上尾）+ 端点语义（0→−inf，1→+inf）。
    """
    grid = np.concatenate([
        np.linspace(1e-9, 0.02, 60),
        np.linspace(0.025, 0.975, 60),
        np.linspace(0.98, 1.0 - 1e-9, 60),
    ])
    worst = max(abs(_norm_ppf(float(p)) - float(stats.norm.ppf(p)))
                for p in grid)
    assert worst <= 1e-8, f"逆 CDF 偏差超带: {worst}"
    assert _norm_ppf(0.0) == -math.inf
    assert _norm_ppf(1.0) == math.inf
    with pytest.raises(ValueError):
        _norm_ppf(1.5)


def test_pf_tail_precision():
    """erfc 尾式在大 β 保精度：β=8 → Pf≈6.22e-16（scipy sf 对照 rel 1e-9）。"""
    res = form_beta(lambda x: 8.0 - x[0], [0.0], [1.0])
    assert res.beta == pytest.approx(8.0, abs=1e-9)
    assert res.pf_form == pytest.approx(stats.norm.sf(8.0), rel=1e-9)


# ─── 病态面如实不收敛（#122）+ 入参守卫 ───────────────────────────────────

def test_flat_surfaces_report_not_converged():
    """常数面 g≡±1：零梯度无设计点——converged=False 不抛，β=±inf 如实。"""
    for g_const, beta_exp, pf_exp in ((1.0, math.inf, 0.0),
                                      (-1.0, -math.inf, 1.0)):
        res = form_beta(lambda x, g=g_const: g, [0.0, 0.0], [1.0, 1.0])
        assert res.converged is False
        assert res.beta == beta_exp
        assert res.pf_form == pf_exp


def test_mean_in_failure_domain_negative_beta():
    """均值点已失效（g(μ)<0）：β<0、Pf>0.5 如实（不翻符号凑正）。"""
    res = form_beta(lambda x: -0.5 - x[0], [0.0], [1.0])
    assert res.converged
    assert res.beta == pytest.approx(-0.5, abs=1e-9)
    assert res.pf_form == pytest.approx(stats.norm.cdf(0.5), rel=1e-9)
    assert res.pf_form > 0.5


def test_nonfinite_limit_state_raises():
    """callable 返回 NaN/Inf：显式 ValueError（如实报错不吞）。"""

    def bad(x):
        return math.nan

    with pytest.raises(ValueError, match="非有限"):
        form_beta(bad, [0.0, 0.0], [1.0, 1.0])


@pytest.mark.parametrize("mean,stddev,msg", [
    ([math.nan, 0.0], [1.0, 1.0], "mean 含非有限值"),
    ([0.0, 0.0], [1.0, -0.1], "stddev 必须"),
    ([0.0, 0.0], [1.0, 0.0], "stddev 必须"),
    ([0.0, 0.0], [1.0, math.inf], "stddev 含非有限值"),
    ([0.0, 0.0], [1.0], "形状不一致"),
    ([], [], "mean 必须为一维非空"),
])
def test_input_guards(mean, stddev, msg):
    with pytest.raises(ValueError, match=msg):
        form_beta(lambda x: 1.0 - float(x[0]), mean, stddev)


def test_iteration_budget_guard():
    with pytest.raises(ValueError, match="max_iter"):
        form_beta(lambda x: 1.0 - x[0], [0.0], [1.0], max_iter=0)
    with pytest.raises(ValueError, match="tol"):
        form_beta(lambda x: 1.0 - x[0], [0.0], [1.0], tol=0.0)


# ─── SORM ─────────────────────────────────────────────────────────────────

def test_sorm_convex_beta_sorm_ge_beta():
    """凸面弱钉：g=1.5+x2²−x1（面朝失效侧凸，κ=+2>0）→ β_sorm≥β。

    κ 解析回收：Hessian=diag(0,2)，设计点 (c,0) 处 ||∇G||=1、切向=e2
    → κ=2（二次面二阶差分无截断误差）；Breitung Pf_sorm=Φ(−β)(1+βκ)^{−1/2}。
    """
    sr = sorm_beta_correction(lambda x: 1.5 + x[1] ** 2 - x[0],
                              [0.0, 0.0], [1.0, 1.0])
    assert sr.beta == pytest.approx(1.5, abs=1e-9)
    assert len(sr.curvatures) == 1
    assert sr.curvatures[0] == pytest.approx(2.0, abs=1e-6)
    # 单调性弱钉：凸面（κ>0）SORM 把 Pf 往下修 → β_sorm ≥ β
    assert sr.beta_sorm >= sr.beta
    assert sr.pf_sorm < sr.pf_form
    # Breitung 公式独立复算（闭式：(1+1.5·2)^{−1/2}=0.5 精确）
    assert sr.pf_sorm == pytest.approx(
        stats.norm.sf(1.5) * 0.5, rel=1e-6)
    assert sr.kappa_mean == pytest.approx(2.0, abs=1e-6)


def test_sorm_breitung_domain_guard():
    """强凹面 g=1−x1−2·x2²：κ=−4、β=1 → 1+βκ=−3<0，显式 ValueError。

    Breitung 渐近式适用域外不静默外推（球面 βκ=−1 同族边界）。
    """
    with pytest.raises(ValueError, match="Breitung 适用域外"):
        sorm_beta_correction(lambda x: 1.0 - x[0] - 2.0 * x[1] ** 2,
                             [0.0, 0.0], [1.0, 1.0])


def test_sorm_n1_identity():
    """单变量无切维：空积=1 → Pf_sorm≡Pf_form、β_sorm=β（ppf 回路容差）。"""
    sr = sorm_beta_correction(lambda x: 3.0 - x[0], [0.0], [1.0])
    assert sr.curvatures == ()
    assert sr.pf_sorm == sr.pf_form
    assert sr.beta_sorm == pytest.approx(sr.beta, abs=1e-8)


def test_sorm_rejects_unconverged_form():
    """FORM 未收敛（平坦面）→ SORM 拒绝在设计点外插（显式 ValueError）。"""
    with pytest.raises(ValueError, match="FORM 未收敛"):
        sorm_beta_correction(lambda x: 1.0, [0.0, 0.0], [1.0, 1.0])


def test_sorm_explicit_design_point_path():
    """显式 design_point_u 路径：凸面传 FORM 设计点与内跑路径逐位一致。"""
    ls = lambda x: 1.5 + x[1] ** 2 - x[0]  # noqa: E731
    fr = form_beta(ls, [0.0, 0.0], [1.0, 1.0])
    sr = sorm_beta_correction(ls, [0.0, 0.0], [1.0, 1.0],
                              design_point_u=fr.design_point_u)
    sr2 = sorm_beta_correction(ls, [0.0, 0.0], [1.0, 1.0])
    assert sr.beta == pytest.approx(sr2.beta, abs=1e-12)
    assert sr.pf_sorm == pytest.approx(sr2.pf_sorm, rel=1e-12)
    assert sr.curvatures == pytest.approx(sr2.curvatures, abs=1e-12)


# ─── 注册键 form_beta_linear（service JSON 出口） ─────────────────────────

def test_form_beta_linear_calculator_service_path():
    """canonical 线性面经 service 出口：闭式/HL-RF 双路径互证逐位一致。"""
    from rfauto.service.calculator_service import run_calculator

    out = run_calculator("form_beta_linear", {
        "coeffs": [1.0, 2.0], "offset": 3.0,
        "mean": [0.0, 0.0], "stddev": [1.0, 1.0]})
    assert out["ok"], out
    r = out["result"]
    beta_exact = 3.0 / math.sqrt(5.0)
    assert r["beta"] == pytest.approx(beta_exact, abs=1e-9)
    assert r["beta_closed_form"] == pytest.approx(beta_exact, abs=1e-12)
    assert r["alpha"] == pytest.approx(
        [1.0 / math.sqrt(5.0), 2.0 / math.sqrt(5.0)], abs=1e-9)
    assert r["pf_form"] == pytest.approx(stats.norm.sf(beta_exact), rel=1e-9)
    assert r["converged"] is True
    assert r["n_iter"] >= 1
    assert r["design_point_x"] == pytest.approx([0.6, 1.2], abs=1e-9)


def test_form_beta_linear_domain_guards():
    """零 σ / 全零系数 / 长度不齐 → ok=False 显式报错（service 契约）。"""
    from rfauto.service.calculator_service import run_calculator

    for params, _match in (
        ({"coeffs": [1.0], "offset": 3.0, "mean": [0.0],
          "stddev": [0.0]}, "stddev"),
        ({"coeffs": [0.0, 0.0], "offset": 3.0, "mean": [0.0, 0.0],
          "stddev": [1.0, 1.0]}, "全零"),
        ({"coeffs": [1.0], "offset": 3.0, "mean": [0.0, 0.0],
          "stddev": [1.0, 1.0]}, "形状"),
    ):
        out = run_calculator("form_beta_linear", params)
        assert out["ok"] is False, params
        assert out.get("error")
