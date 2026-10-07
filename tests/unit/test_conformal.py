"""AI-1 保形预测包裹层锚测试（round14 :58，2026-10-02）。

锚口径（任务书预声明）：
- 分位数数学：手工小样本逐位（ceil((n+1)(1−α)) 高阶分位数规则）；
- 覆盖率锚：合成高斯残差，n=200 校准、100 次重复，经验覆盖率 ≈1−α
  ±3%（固定 seed 确定性）；
- 宽度对拍（round14 验收"区间宽度 vs GP σ 对比"）：高斯残差下 q ≈
  z_{1−α/2}·σ（α=0.1 → 1.6449σ，n=200 经验分位数波动带内）；
- GP 薄适配：鸭子类型假模型（predict_with_std / 纯 predict / 标量）
  三形态 + 未校准显式报错 + std 透出（None 如实）。
"""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.conformal import (
    ConformalInterval,
    SurrogateConformalWrapper,
    calibrate,
    predict_interval,
)

# 覆盖率锚参数（任务书预声明：n=200、100 次重复、±3%）
_SEED = 20261002
_N_CAL = 200
_N_REPEAT = 100
_TOL = 0.03


# ─── 分位数数学：手工小样本 ──────────────────────────────────────────────

def test_calibrate_higher_quantile_hand_cases():
    """k=ceil((n+1)(1−α)) 高阶分位数规则逐位（n=5 手算）。"""
    res = [0.1, 0.5, 0.3, 0.9, 0.7]
    # α=0.25: k=ceil(6·0.75)=5 → sorted(|r|)[4]=0.9
    assert calibrate(res, 0.25) == 0.9
    # α=0.5: k=ceil(6·0.5)=3 → sorted(|r|)[2]=0.5
    assert calibrate(res, 0.5) == 0.5
    # 残差取绝对值（−0.2 参与）：n=2, α=0.5 → k=2 → 0.4
    assert calibrate([-0.2, 0.4], 0.5) == 0.4
    # α 极小、k>n → +inf（如实上溢不夹持）
    assert calibrate([0.1, 0.2], 0.1) == math.inf


def test_calibrate_validation_explicit_errors():
    with pytest.raises(ValueError, match="alpha"):
        calibrate([0.1], 0.0)
    with pytest.raises(ValueError, match="alpha"):
        calibrate([0.1], 1.0)
    with pytest.raises(ValueError, match="alpha"):
        calibrate([0.1], True)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError, match="空"):
        calibrate([], 0.1)
    with pytest.raises(ValueError, match="非有限"):
        calibrate([0.1, float("nan")], 0.1)
    with pytest.raises(ValueError, match="非有限"):
        calibrate([float("inf")], 0.1)


def test_predict_interval_symmetric_and_validation():
    lo, hi = predict_interval(2.0, 0.3)
    assert (lo, hi) == (1.7, 2.3)
    assert lo == 2.0 - 0.3 and hi == 2.0 + 0.3  # 对称恒等式
    # q=+inf 合法（calibrate 上溢路径透传）
    lo, hi = predict_interval(0.0, math.inf)
    assert lo == -math.inf and hi == math.inf
    with pytest.raises(ValueError, match="point_pred"):
        predict_interval(float("nan"), 0.1)
    with pytest.raises(ValueError, match="q"):
        predict_interval(0.0, -0.1)
    with pytest.raises(ValueError, match="q"):
        predict_interval(0.0, True)


def test_conformal_interval_carrier_and_width():
    c = ConformalInterval(alpha=0.1, q=0.4, n=200)
    assert c.interval(1.0) == (0.6, 1.4)
    assert c.width == 0.8  # 全宽 = 2q


# ─── 覆盖率锚：合成高斯残差（固定 seed，确定性）─────────────────────────

@pytest.mark.parametrize("alpha", [0.05, 0.1, 0.2])
def test_synthetic_gaussian_coverage_anchor(alpha: float):
    """σ=1 高斯残差：n=200 校准 → 独立新样本覆盖率 ≈ 1−α ± 3%。"""
    rng = np.random.default_rng(_SEED)
    coverages = []
    for _ in range(_N_REPEAT):
        cal = rng.standard_normal(_N_CAL)
        fresh = rng.standard_normal(_N_CAL)
        q = calibrate(cal, alpha)
        if math.isinf(q):  # α≥1/(n+1) 才可达这里；本参数化不触发
            coverages.append(1.0)
            continue
        coverages.append(float(np.mean(np.abs(fresh) <= q)))
    mean_cov = float(np.mean(coverages))
    # 任务书口径：≈1−α±3%（100 次重复均值；均值标准误 ~0.002，带内充裕）
    assert abs(mean_cov - (1.0 - alpha)) <= _TOL, (
        f"alpha={alpha}: mean coverage {mean_cov:.4f} 偏离 "
        f"1−α={1.0 - alpha:.2f} 超出 ±{_TOL}")


def test_width_vs_gaussian_sigma_reference():
    """高斯残差下 q ≈ z_{1−α/2}·σ（α=0.1 → 1.6449σ；n=200 经验分位数）。"""
    rng = np.random.default_rng(_SEED + 1)
    sigma = 2.5
    q = calibrate((sigma * rng.standard_normal(_N_CAL)).tolist(), 0.1)
    z95 = 1.6448536269514722  # Φ⁻¹(0.95)（scipy 侧闭式另由 numpy erfc 反解互证）
    # n=200 高阶分位数的抽样波动 ~σ/√n 量级 × 数倍 → 8% 带宽充分且非恒真
    assert abs(q / sigma - z95) / z95 < 0.08, (
        f"q={q:.4f} vs z95·σ={z95 * sigma:.4f}")


# ─── GP 薄适配：鸭子类型三形态 ───────────────────────────────────────────

class _FakeGPWithStd:
    """SurrogateModel.predict_with_std 契约形态（mean, std）。"""

    def predict_with_std(self, params):
        x = params["x"]
        return {"f": (2.0 * x + 0.1, 0.05)}


class _FakeGPPlainDict:
    """纯 predict 形态（无不确定度；std 如实 None 不伪造 0）。"""

    def predict(self, params):
        return {"f": 2.0 * params["x"] + 0.1}


class _FakeGPScalar:
    """标量返回形态（metric 缺省 "y" 路径）。"""

    def predict(self, params):
        return 2.0 * params["x"] + 0.1


@pytest.mark.parametrize("model_cls,metric", [
    (_FakeGPWithStd, "f"),
    (_FakeGPPlainDict, "f"),
    (_FakeGPScalar, None),
])
def test_wrapper_adapter_three_model_shapes(model_cls, metric):
    model = model_cls()
    w = SurrogateConformalWrapper(model, metric=metric, alpha=0.2)
    # 校准集：无噪声 → 残差全 0 → q=0 → 区间退化为点
    pts = [{"x": float(i)} for i in range(20)]
    ys = [2.0 * p["x"] + 0.1 for p in pts]
    c = w.calibrate(pts, ys)
    assert c.q == 0.0 and c.n == 20
    out = w.predict_with_interval({"x": 3.0})
    assert out["mean"] == pytest.approx(6.1)
    assert out["lo"] == out["hi"] == out["mean"]
    assert out["q"] == 0.0
    if model_cls is _FakeGPWithStd:
        assert out["std"] == 0.05  # σ 透出（对比面）
    else:
        assert out["std"] is None  # 无原生 σ 如实 None（#122 诚实纪律）


def test_wrapper_with_noise_residuals_and_recalibrate():
    rng = np.random.default_rng(_SEED + 2)
    w = SurrogateConformalWrapper(_FakeGPPlainDict(), metric="f", alpha=0.1)
    pts = [{"x": float(i)} for i in range(50)]
    noise = rng.uniform(-0.5, 0.5, 50)
    ys = [2.0 * p["x"] + 0.1 + float(e) for p, e in zip(pts, noise, strict=True)]
    c1 = w.calibrate(pts, ys)
    # 期望值按同一高阶分位数规则手算：k=ceil((n+1)(1−α))=46 → 排序位 45
    k = math.ceil((len(noise) + 1) * (1.0 - 0.1))
    expected_q = float(np.sort(np.abs(noise))[k - 1])
    assert c1.q == pytest.approx(expected_q)
    # 重校准（alpha 收紧 → q 变大）
    c2 = w.set_alpha(0.05).calibrate(pts, ys)
    assert c2.alpha == 0.05 and c2.q >= c1.q
    out = w.predict_with_interval({"x": 100.0})
    assert out["lo"] <= out["mean"] <= out["hi"]


def test_wrapper_validation_paths():
    w = SurrogateConformalWrapper(_FakeGPWithStd(), metric="f", alpha=0.1)
    with pytest.raises(ValueError, match="尚未 calibrate"):
        w.predict_with_interval({"x": 0.0})
    with pytest.raises(ValueError, match="长度不一致"):
        w.calibrate([{"x": 0.0}], [1.0, 2.0])
    with pytest.raises(ValueError, match="alpha"):
        SurrogateConformalWrapper(_FakeGPWithStd(), metric="f", alpha=1.5)
    # 多指标模型不指名 metric → 显式 KeyError（不静默取第一键）
    class _Multi:
        def predict(self, params):
            return {"a": 1.0, "b": 2.0}
    with pytest.raises(KeyError, match="metric"):
        SurrogateConformalWrapper(_Multi()).calibrate([{}], [0.0])


def test_module_zero_network_imports():
    """AI-5/AI-1 内核零网络面：AST 双检查 Import 目标（#270 同源纪律）。"""
    src = (SRC / "rfauto" / "core" / "conformal.py").read_text("utf-8")
    tree = ast.parse(src)
    banned = {"urllib", "requests", "http", "httpx", "socket"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] not in banned for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned
