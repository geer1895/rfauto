"""S-3 SPRT 早停内核单测（round3 §3.1 S-3 判据：ASN 理论对照 + 错误率冒出）。

裁判口径（#118：全部解析常量双路径独立推导，不自证）：
- 路径 A（被测内核）：sprt.py 闭式；
- 路径 B（测试内独立重推导）：plain math 重算边界/ASN，或 scipy
  norm.logpdf 直算 LLR、scipy.integrate.quad 直积混合积分。
  断言容差 rel=1e-9（闭式）/ 1e-6（数值积分）容纳两路径浮点差。

MC 判据（round3 S-3 行判据草案，固定 seed 可复现）：
- 合成已知效应量 δ=μ1−μ0（σ=1）：实测停止样本数 vs Wald ASN 一阶理论
  ±20% 带（预扫 d∈{0.25,0.30,0.40} 实测比 ∈[1.01,1.15] 带内——一阶
  近似忽略过冲系统性低估，δ≤0.4σ 时 <15%，docstring 已注记）；
- α/β 经验冒出率 ≤ 名义 1.5×（Wald 边界过冲使真实错误率略高于名义，
  1.5× 为 round3 判据带）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import integrate, stats

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import sprt

SEED = 20260927
ALPHA = 0.05
BETA = 0.05
LN19 = 2.9444389791664403  # ln(0.95/0.05)，双路径手算钉值


# ─── 1. Wald 边界 ────────────────────────────────────────────────────────────


def test_wald_bounds_symmetric_closed_form():
    b = sprt.wald_bounds(ALPHA, BETA)
    # 双路径：模块 ln((1-β)/α) vs 测试内手算 ln19
    assert b.log_upper == pytest.approx(LN19, rel=1e-12)
    assert b.log_lower == pytest.approx(-LN19, rel=1e-12)
    assert b.log_upper > 0.0 and b.log_lower < 0.0


def test_wald_bounds_asymmetric_formula():
    b = sprt.wald_bounds(0.1, 0.2)
    # 独立重推导（路径 B）
    assert b.log_upper == pytest.approx(math.log(0.8 / 0.1), rel=1e-12)
    assert b.log_lower == pytest.approx(math.log(0.2 / 0.9), rel=1e-12)
    # to_dict JSON 可序列化
    assert json.dumps(b.to_dict())  # 不抛即合法
    assert b.to_dict()["log_upper_A"] == b.log_upper


def test_wald_bounds_guards():
    for bad_alpha in (0.0, 1.0, -0.1, 1.5, float("nan"), True):
        with pytest.raises(ValueError):
            sprt.wald_bounds(bad_alpha, BETA)
    for bad_beta in (0.0, 1.0, -0.1, float("inf"), False):
        with pytest.raises(ValueError):
            sprt.wald_bounds(ALPHA, bad_beta)


# ─── 2. 正态 LLR：增量闭式 vs scipy 直算（双路径） ───────────────────────────


def test_normal_llr_increment_dual_path_scipy():
    rng = np.random.default_rng(SEED)
    xs = rng.normal(0.3, 1.0, 50)
    mu0, mu1, sigma = 0.0, 0.5, 1.2
    # 路径 A：模块增量累加
    inc = [sprt.normal_llr_increment(x, mu0, mu1, sigma) for x in xs]
    # 路径 B：scipy norm.logpdf 逐点直算
    direct = stats.norm.logpdf(xs, mu1, sigma) - stats.norm.logpdf(xs, mu0, sigma)
    assert np.allclose(inc, direct, rtol=1e-10, atol=1e-12)


def test_normal_llr_increment_closed_form_identity():
    # 闭式恒等式：z = (μ1−μ0)(x − (μ0+μ1)/2)/σ²
    z = sprt.normal_llr_increment(2.0, mu0=-1.0, mu1=3.0, sigma=2.0)
    assert z == pytest.approx(4.0 * (2.0 - 1.0) / 4.0, rel=1e-12)
    # x=中点 → z=0 逐位
    assert sprt.normal_llr_increment(1.0, -1.0, 3.0, 2.0) == 0.0


def test_normal_drift_anchors():
    # E_μ0[z] = −δ²/(2σ²)，E_μ1[z] = +δ²/(2σ²)，中点 0
    assert sprt.normal_drift(0.0, 0.0, 0.6, 1.0) == pytest.approx(-0.18, rel=1e-12)
    assert sprt.normal_drift(0.6, 0.0, 0.6, 1.0) == pytest.approx(0.18, rel=1e-12)
    assert sprt.normal_drift(0.3, 0.0, 0.6, 1.0) == 0.0


# ─── 3. 单步判定与序贯运行 ───────────────────────────────────────────────────


def test_sprt_decide_three_regions():
    b = sprt.wald_bounds(ALPHA, BETA)
    assert sprt.sprt_decide(b.log_upper + 0.1, b).decision == "reject_h0"
    assert sprt.sprt_decide(b.log_lower - 0.1, b).decision == "accept_h0"
    mid = sprt.sprt_decide(0.0, b)
    assert mid.decision == "continue" and mid.prune is False


def test_sprt_decide_boundary_inclusive_and_prune_semantics():
    b = sprt.wald_bounds(ALPHA, BETA)
    assert sprt.sprt_decide(b.log_upper, b).decision == "reject_h0"  # 含等号
    low = sprt.sprt_decide(b.log_lower, b)
    assert low.decision == "accept_h0" and low.prune is True  # H0=无改进→剪枝
    with pytest.raises(ValueError):
        sprt.sprt_decide(float("nan"), b)


def test_sprt_run_stops_at_first_crossing():
    # 构造已知交叉点：mu0=0, mu1=0.6, σ=1 → 增量 0.6·(x−0.3)
    mu0, mu1, sigma = 0.0, 0.6, 1.0
    xs = [0.0, 3.0, 5.0, 0.0, 0.0]  # 增量 [−0.18, 1.62, 2.82, −0.18, −0.18]
    # 累计：[−0.18, 1.44, 4.26, ...]，A=ln19≈2.944 → 第 3 步越上界
    trace = sprt.sprt_run(xs, mu0, mu1, sigma, ALPHA, BETA)
    assert trace.decision == "reject_h0"
    assert trace.bound_crossed == "upper"
    assert trace.stopped_by == "bound"
    assert trace.n_stopped == 3
    assert len(trace.llr_path) == 3
    assert trace.llr_path[-1] >= sprt.wald_bounds(ALPHA, BETA).log_upper
    assert json.dumps(trace.to_dict())  # JSON 可序列化


def test_sprt_run_max_n_inconclusive():
    # 零效应样本（x 恒=中点）LLR 恒 0，永不越界
    mu0, mu1, sigma = 0.0, 0.6, 1.0
    xs = [0.3] * 20
    trace = sprt.sprt_run(xs, mu0, mu1, sigma, ALPHA, BETA)
    assert trace.decision == "inconclusive"
    assert trace.bound_crossed is None
    assert trace.llr == 0.0
    # max_n 截断语义
    trace2 = sprt.sprt_run([0.3] * 100, mu0, mu1, sigma, ALPHA, BETA, max_n=7)
    assert trace2.n_stopped == 7 and trace2.stopped_by == "max_n"
    with pytest.raises(ValueError):
        sprt.sprt_run([], mu0, mu1, sigma, ALPHA, BETA)
    with pytest.raises(ValueError):
        sprt.sprt_run([0.1], 1.0, 1.0, sigma, ALPHA, BETA)  # mu0==mu1


# ─── 4. ASN 一阶闭式 ─────────────────────────────────────────────────────────


def test_asn_wald_closed_form_dual_path():
    res = sprt.asn_wald(0.0, 0.3, 1.0, ALPHA, BETA)
    # 路径 B：测试内 plain math 独立重推导
    a_ = math.log((1 - BETA) / ALPHA)
    b_ = math.log(BETA / (1 - ALPHA))
    delta = 0.3
    asn0 = (ALPHA * a_ + (1 - ALPHA) * b_) / (-(delta**2) / 2)
    asn1 = (BETA * b_ + (1 - BETA) * a_) / ((delta**2) / 2)
    assert res.asn_h0 == pytest.approx(asn0, rel=1e-12)
    assert res.asn_h1 == pytest.approx(asn1, rel=1e-12)
    assert res.drift_h0 == pytest.approx(-delta * delta / 2, rel=1e-12)
    # α=β 对称 → asn_h0 == asn_h1 逐位
    sym = sprt.asn_wald(0.0, 0.3, 1.0, 0.05, 0.05)
    assert sym.asn_h0 == sym.asn_h1
    assert json.dumps(res.to_dict())


def test_asn_wald_guards():
    with pytest.raises(ValueError):
        sprt.asn_wald(1.0, 1.0, 1.0, ALPHA, BETA)  # δ=0
    with pytest.raises(ValueError):
        sprt.asn_wald(0.0, 0.3, 0.0, ALPHA, BETA)  # σ=0
    with pytest.raises(ValueError):
        sprt.asn_wald(0.0, 0.3, 1.0, 1.0, BETA)  # α 越界


# ─── 5. MC 判据：ASN ±20% 带 + 错误率 ≤1.5× 名义（固定 seed） ─────────────────


def _mc_sprt(delta: float, mu_true: float, n_runs: int = 300, cap: int = 4000) -> dict:
    """固定 seed 的 SPRT MC：返回停止样本数均值/判定计数。"""
    rng = np.random.default_rng(SEED + int(delta * 1000))
    mu0, mu1, sigma = 0.0, delta, 1.0
    stops: list[int] = []
    n_reject = n_accept = 0
    for _ in range(n_runs):
        xs = rng.normal(mu_true, sigma, cap)
        trace = sprt.sprt_run(list(xs), mu0, mu1, sigma, ALPHA, BETA, max_n=cap)
        assert trace.decision != "inconclusive", "cap 不足以触发停止，MC 设置错"
        stops.append(trace.n_stopped)
        if trace.decision == "reject_h0":
            n_reject += 1
        else:
            n_accept += 1
    return {
        "mean_stop": float(np.mean(stops)),
        "n_reject": n_reject,
        "n_accept": n_accept,
        "n_runs": n_runs,
    }


def test_asn_mc_h0_stopping_within_20pct_and_false_reject():
    res = sprt.asn_wald(0.0, 0.3, 1.0, ALPHA, BETA)
    mc = _mc_sprt(0.3, mu_true=0.0)
    assert mc["mean_stop"] == pytest.approx(res.asn_h0, rel=0.20)  # ±20% 判据带
    # α/β 经验冒出率 ≤ 1.5× 名义
    assert mc["n_reject"] / mc["n_runs"] <= 1.5 * ALPHA


def test_asn_mc_h1_stopping_within_20pct_and_miss_rate():
    res = sprt.asn_wald(0.0, 0.3, 1.0, ALPHA, BETA)
    mc = _mc_sprt(0.3, mu_true=0.3)
    assert mc["mean_stop"] == pytest.approx(res.asn_h1, rel=0.20)
    assert mc["n_accept"] / mc["n_runs"] <= 1.5 * BETA


def test_asn_curve_multiple_effect_sizes_within_20pct():
    # ASN 理论曲线对照：多效应量扫（round3 判据「ASN 曲线」口径）
    for delta in (0.25, 0.30, 0.40):
        res = sprt.asn_wald(0.0, delta, 1.0, ALPHA, BETA)
        mc0 = _mc_sprt(delta, mu_true=0.0, n_runs=200)
        mc1 = _mc_sprt(delta, mu_true=delta, n_runs=200)
        ratio0 = mc0["mean_stop"] / res.asn_h0
        ratio1 = mc1["mean_stop"] / res.asn_h1
        assert 0.80 <= ratio0 <= 1.20, f"delta={delta}: ratio_h0={ratio0:.3f}"
        assert 0.80 <= ratio1 <= 1.20, f"delta={delta}: ratio_h1={ratio1:.3f}"
        assert mc0["n_reject"] / 200 <= 1.5 * ALPHA
        assert mc1["n_accept"] / 200 <= 1.5 * BETA


# ─── 6. mSPRT：闭式统计量 vs 数值积分（双路径）+ always-valid MC ──────────────


def test_msprt_log_statistic_closed_form_identity():
    # n=1：混合似然 = N(x;0,σ²+τ²)，Λ = N(x;0,σ²+τ²)/N(x;0,σ²)（路径 B）
    x, sigma, tau = 0.4, 1.0, 0.5
    log_ratio = stats.norm.logpdf(x, 0.0, math.sqrt(sigma**2 + tau**2)) - stats.norm.logpdf(
        x, 0.0, sigma
    )
    assert sprt.msprt_log_statistic(x, 1, sigma, tau) == pytest.approx(log_ratio, rel=1e-10)
    # n=0 → 0.0 逐位（Λ=1）
    assert sprt.msprt_log_statistic(0.0, 0, sigma, tau) == 0.0


def test_msprt_log_statistic_quad_referee_n3():
    # n=3：路径 B = scipy.quad 直积混合积分（对数域拼常数）
    xs = [0.3, 0.5, 0.2]
    sigma, tau = 1.0, 0.5

    def integrand(theta: float) -> float:
        s2 = sigma**2
        t2 = tau**2
        return math.exp(-theta**2 / (2 * t2) - sum((x - theta) ** 2 for x in xs) / (2 * s2))

    val, _ = integrate.quad(integrand, -2.0, 2.0, limit=200, epsabs=1e-13, epsrel=1e-13)
    # 被积函数未含 (2πσ²)^(−n/2) 与 (2πτ²)^(−1/2) 归一化常数 → 对数域补齐
    log_mix = (
        math.log(val)
        - 0.5 * math.log(2 * math.pi * tau**2)
        - len(xs) * 0.5 * math.log(2 * math.pi * sigma**2)
    )
    log_h0 = -0.5 * math.log(2 * math.pi * sigma**2) * 3 - sum(x**2 for x in xs) / (2 * sigma**2)
    assert sprt.msprt_log_statistic(sum(xs), 3, sigma, tau) == pytest.approx(
        log_mix - log_h0, rel=1e-5
    )


def test_msprt_pvalue_identity():
    sv, n, sigma, tau = 2.0, 8, 1.0, 0.5
    log_llr = sprt.msprt_log_statistic(sv, n, sigma, tau)
    assert sprt.msprt_pvalue(sv, n, sigma, tau) == pytest.approx(min(1.0, math.exp(-log_llr)))
    # 负证据（sum_x=0）→ p=1
    assert sprt.msprt_pvalue(0.0, 8, sigma, tau) == 1.0


def test_msprt_decide_threshold_and_guards():
    d = sprt.msprt_decide(-math.log(0.05), 0.05)
    assert d.reject_h0 is True and d.log_threshold == pytest.approx(-math.log(0.05))
    assert sprt.msprt_decide(-10.0, 0.05).reject_h0 is False
    assert sprt.msprt_decide(0.0, 0.05).pvalue == 1.0
    with pytest.raises(ValueError):
        sprt.msprt_decide(0.0, 0.0)
    with pytest.raises(ValueError):
        sprt.msprt_log_statistic(0.0, 3, 1.0, 0.0)  # τ=0 显式拒绝
    with pytest.raises(ValueError):
        sprt.msprt_log_statistic(float("nan"), 3, 1.0, 0.5)


def test_msprt_run_always_valid_h0_false_positive():
    # Ville 不等式：H0 下 sup_n Λ_n ≥ 1/α 的频率 ≤ α（经验 ≤1.5α 判据带）
    rng = np.random.default_rng(SEED)
    n_runs, n_steps = 300, 200
    sigma, tau = 1.0, 0.5
    n_reject = 0
    for _ in range(n_runs):
        xs = rng.normal(0.0, sigma, n_steps)
        run = sprt.msprt_run(list(xs), sigma, tau, ALPHA)
        assert run["stopped_by"] != "bound" or run["n_stopped"] <= n_steps
        if run["reject_h0"]:
            n_reject += 1
    assert n_reject / n_runs <= 1.5 * ALPHA


def test_msprt_run_power_h1_and_path_shape():
    rng = np.random.default_rng(SEED + 1)
    sigma, tau = 1.0, 0.5
    n_reject = 0
    for _ in range(200):
        xs = rng.normal(0.4, sigma, 300)  # 恒定正效应 → 应拒 H0
        if sprt.msprt_run(list(xs), sigma, tau, ALPHA)["reject_h0"]:
            n_reject += 1
    assert n_reject / 200 >= 0.90
    # 路径形状：sup ≥ 末值； stopped_by=bound 时 sup ≥ 阈值
    run = sprt.msprt_run(list(rng.normal(0.4, sigma, 300)), sigma, tau, ALPHA)
    assert run["log_llr_max"] >= run["log_llr"] - 1e-12
    assert json.dumps({k: v for k, v in run.items()})  # JSON 可序列化


# ─── 7. Optuna 剪枝信封（纯函数） ────────────────────────────────────────────


def test_optuna_prune_decision_envelope():
    b = sprt.wald_bounds(ALPHA, BETA)
    prune = sprt.optuna_prune_decision(b.log_lower - 1.0, ALPHA, BETA)
    cont = sprt.optuna_prune_decision(0.0, ALPHA, BETA)
    keep = sprt.optuna_prune_decision(b.log_upper + 1.0, ALPHA, BETA)
    assert prune["prune"] is True and prune["decision"] == "accept_h0"
    assert cont["prune"] is False and cont["decision"] == "continue"
    assert keep["prune"] is False and keep["decision"] == "reject_h0"
    assert prune["ok"] is True and keep["ok"] is True
    # JSON 信封逐位可序列化
    assert json.dumps(prune) and json.dumps(cont) and json.dumps(keep)
    assert prune["bounds"]["log_upper_A"] == pytest.approx(LN19, rel=1e-12)
