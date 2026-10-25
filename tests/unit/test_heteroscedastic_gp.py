"""ME-14 补强：GPR 逐点噪声（异方差）合成回收裁判 + σ=0 退化逐位钉。

背景（#222 对账）：ME-14 生产面（analyze_run_surrogate 的 y_sigma→
GPR(alpha=σ²) 透传）已随 wf:gecode12 代码批轨 1（46395d1）落地；本文件
补任务书钉的两块缺口：

1. **合成回收裁判（判据预声明）**：带噪合成数据（真 f + 已知逐点 σ，
   σ 强异构 0.02/0.6 两档）上，逐点噪声 GP（alpha=σ²）应优于常数噪声
   GP（alpha=mean(σ²)），判据=两条，缺一即 FAIL：
   - 拟合面 log marginal likelihood：逐点 − 常数 ≥ +10 nats；
   - σ 已知 LOO 预测 logpdf（折内预测方差 = s折² + σ_i²，即"折知道
     被留出点的观测噪声"）：逐点 − 常数 ≥ +10 nats。
   #118 族纪律：裁判的统计口径本身先验算——**朴素 LOO（不把被留出点
   的 σ 告诉折）是错误裁判**：留出的大噪声点在折内模型看来是"意外值"，
   逐点模型反而灾难性落败（实测 dLL≈−1.5 万 nats/10 seeds 全输）。
   正确口径必须把 σ_i² 加进留出点的预测方差（未来观测的预测分布语义）。
   10 seeds × {LML, σ-aware LOO} 两口径 20/20 全胜后才冻结本门。

2. **σ=0 退化等价旧路径（逐位钉）**：y_sigma=全零向量 → GPR 不带
   alpha kwarg，与 y_sigma=None 旧路径 to_dict() 输出逐位相等
   （sklearn 缺省 alpha=1e-10 语义原样；部分零仍走数组）。

3. **CharImp 2.5% 分散消费形态钉**：锚 arbitration 场景的 σ 来源
   （HFSS 宽端口 CharImp 三定义 Z0 分散 ~2.5%，df6⑲）——σ_i=2.5%·|y_i|
   形态的 y_sigma 透传 analyze_run_surrogate 全链路可用（观测块如实
   回报）。接地结论：仓内尚无锚 arbitration GP 拟合消费点
   （analyze_run_surrogate 的消费面=surrogate_loop/service.api 两处，
   均无 σ 来源列），故按任务书"无则 core+测试交付"口径只钉形态。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from rfauto.optimization.surrogate_analysis import analyze_run_surrogate

#: 合成裁判固定 seed（预声明后冻结；换 seed=换门，须重跑 10 seeds 全胜）
JUDGE_SEED = 7
N_POINTS = 21
#: σ 两档（强异构：15 倍比），每 3 点一个 0.6 档
SIGMA_LO, SIGMA_HI = 0.02, 0.6
#: 判据边距（nats）：两口径各自 ≥ 此边距才算"优于"
LML_MARGIN_NATS = 10.0
LOO_MARGIN_NATS = 10.0


def _make_noisy_data(seed: int = JUDGE_SEED, n: int = N_POINTS,
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """真 f(x)=sin(3x)+0.5x + 已知逐点 σ 高斯噪声（确定性）。"""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    f = np.sin(3.0 * x) + 0.5 * x
    sigma = np.where(np.arange(n) % 3 == 0, SIGMA_HI, SIGMA_LO)
    y = f + rng.normal(0.0, 1.0, size=n) * sigma
    return x.reshape(-1, 1), y, sigma


def _make_gp(alpha: np.ndarray, restarts: int):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    return GaussianProcessRegressor(
        kernel=ConstantKernel(1.0) * RBF(length_scale=1.0), alpha=alpha,
        n_restarts_optimizer=int(restarts), random_state=0)


def _fit_lml(x: np.ndarray, y: np.ndarray, alpha: np.ndarray) -> float:
    """拟合面 log marginal likelihood（同核同参仅 alpha 异——噪声模型
    的模型选择判据就是 LML）。"""
    gp = _make_gp(alpha, restarts=3)
    gp.fit(x, y)
    return float(gp.log_marginal_likelihood_value_)


def _loo_sigma_aware(x: np.ndarray, y: np.ndarray, sigma: np.ndarray,
                     alpha: np.ndarray) -> float:
    """σ 已知 LOO 预测 logpdf 总和：折 i 用其余 n−1 点拟合（alpha 同源
    子集），留出点的预测方差 = s_折² + σ_i²（未来观测分布语义）。"""
    n = int(y.size)
    total = 0.0
    for i in range(n):
        tr = np.array([j for j in range(n) if j != i])
        gp = _make_gp(alpha[tr], restarts=1)
        gp.fit(x[tr], y[tr])
        mu, s = gp.predict(x[i:i + 1], return_std=True)
        var = (float(np.asarray(s).ravel()[0]) ** 2 + float(sigma[i]) ** 2)
        sd = max(float(np.sqrt(var)), 1e-9)
        r = float(y[i]) - float(np.asarray(mu).ravel()[0])
        total += -0.5 * (r / sd) ** 2 - np.log(sd) - 0.5 * np.log(2.0 * np.pi)
    return total


# ── 合成回收裁判（判据预声明见模块 docstring）────────────────────────────

def test_pointwise_noise_lml_beats_constant() -> None:
    """拟合面 LML：逐点噪声 GP 优于常数噪声 GP（边距 ≥ +10 nats）。"""
    x, y, sigma = _make_noisy_data()
    lml_point = _fit_lml(x, y, sigma ** 2)
    lml_const = _fit_lml(x, y, np.full_like(sigma, float(np.mean(sigma ** 2))))
    assert lml_point - lml_const >= LML_MARGIN_NATS, (
        f"逐点噪声 LML 未胜出: {lml_point:.3f} vs {lml_const:.3f} "
        f"(d={lml_point - lml_const:.3f})")


def test_pointwise_noise_sigma_aware_loo_beats_constant() -> None:
    """σ 已知 LOO 预测 logpdf：逐点噪声 GP 优于常数噪声 GP（≥ +10 nats）。

    口径注释（本裁判的先验证）：折内预测方差必须加被留出点的 σ_i²——
    朴素 LOO（不加）会系统性误判逐点模型（见模块 docstring 实测）。
    """
    x, y, sigma = _make_noisy_data()
    a_pt = sigma ** 2
    a_ct = np.full_like(sigma, float(np.mean(sigma ** 2)))
    ll_point = _loo_sigma_aware(x, y, sigma, a_pt)
    ll_const = _loo_sigma_aware(x, y, sigma, a_ct)
    assert ll_point - ll_const >= LOO_MARGIN_NATS, (
        f"逐点噪声 LOO logpdf 未胜出: {ll_point:.3f} vs {ll_const:.3f} "
        f"(d={ll_point - ll_const:.3f})")


# ── σ=0 退化等价旧路径（逐位钉）──────────────────────────────────────────

def _make_trials(n: int = 8) -> list[dict]:
    rng = np.random.default_rng(11)
    return [{"params": {"a": float(rng.uniform(0, 1)), "b": float(rng.uniform(0, 1))},
             "cost": float(rng.uniform(-1, 1))} for _ in range(n)]


def test_sigma_all_zero_bit_exact_old_path() -> None:
    """y_sigma=全零 → 与 y_sigma=None 旧路径逐位相等（GP 拟合/预测面）。

    quality.pointwise_noise 是 y_sigma 分支的观测记账（used=False 如实
    登记退化），不在逐位比对范围——比对键=GP 派生的全部输出。
    """
    trials = _make_trials()
    zeros = np.zeros(len(trials))
    d_old = analyze_run_surrogate("deg_old", trials).to_dict()
    d_zero = analyze_run_surrogate("deg_zero", trials, y_sigma=zeros).to_dict()
    d_old.pop("run_id")
    d_zero.pop("run_id")
    # 观测块先单独钉（used=False + 退化说明），再从两侧剔除做逐位比对
    pn = d_zero["quality"].pop("pointwise_noise")
    assert "pointwise_noise" not in d_old["quality"]
    assert pn["used"] is False
    assert "退化" in pn["detail"]
    assert pn["sigma_max"] == 0.0
    assert d_zero == d_old


def test_partial_zero_sigma_keeps_array_semantics(monkeypatch) -> None:
    """部分零 σ 仍走数组路径（零方差点=精确观测，异方差语义自洽）。"""
    import sklearn.gaussian_process as sgp

    real_cls = sgp.GaussianProcessRegressor
    alphas: list = []

    class SpyGPR(real_cls):
        def __init__(self, **kwargs):
            alphas.append(kwargs.get("alpha", "ABSENT"))
            super().__init__(**kwargs)

    monkeypatch.setattr(sgp, "GaussianProcessRegressor", SpyGPR)
    trials = _make_trials()
    sigma = np.full(len(trials), 0.1)
    sigma[0] = 0.0  # 单点零方差
    result = analyze_run_surrogate("partial_zero", trials, y_sigma=sigma)
    assert result.quality["available"] is True
    assert len(alphas) >= 2
    zero_seen = False
    for a in alphas:
        assert not isinstance(a, str), "部分零 σ 不得退化为无 alpha 构造"
        arr = np.asarray(a, dtype=float)
        if 0.0 in arr:
            zero_seen = True  # 零方差点以 alpha=0 进所在折的数组
    assert zero_seen, "零方差点的 alpha=0 未出现在任一折/主拟合中"
    assert result.quality["pointwise_noise"]["used"] is True


# ── CharImp 2.5% 分散消费形态钉（锚 arbitration σ 来源）──────────────────

def test_charimp_dispersion_sigma_passthrough() -> None:
    """CharImp 三定义 2.5% 分散场景：σ_i=2.5%·|y_i| 透传全链路可用。

    场景（df6⑲）：HFSS 宽端口 CharImp 三定义重建 Z0 天然分散 ~2.5%——
    多次仲裁取样的 Z0 样本带已知相对分散，σ=0.025·|Z0_i| 直接入代理，
    σ 不再被丢弃。锚 arbitration_interval 来源同理（区间半宽/2）。
    """
    rng = np.random.default_rng(21)
    z0 = 49.0 + rng.uniform(-1.5, 1.5, size=9)  # 宽端口 Z0 样本（Ω）
    sigma = 0.025 * np.abs(z0)
    trials = [{"params": {"w_mm": float(w)}, "cost": float(v)}
              for w, v in zip(rng.uniform(0.2, 1.2, size=9), z0, strict=True)]
    result = analyze_run_surrogate("charimp", trials, y_sigma=sigma)
    q = result.quality
    assert q["available"] is True
    assert q["pointwise_noise"]["used"] is True
    assert q["pointwise_noise"]["n"] == len(trials)
    assert q["pointwise_noise"]["sigma_min"] == pytest.approx(
        float(sigma.min()), rel=1e-12)
    assert q["pointwise_noise"]["sigma_max"] == pytest.approx(
        float(sigma.max()), rel=1e-12)
    d = result.to_dict()
    assert d["quality"]["pointwise_noise"]["detail"].startswith("GPR alpha")
