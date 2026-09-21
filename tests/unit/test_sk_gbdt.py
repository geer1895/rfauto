"""B3：sklearn GBDT 代理单测（可选依赖，pytest.importorskip 先例=test_smt_mfk）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

sklearn = pytest.importorskip("sklearn", reason="sklearn 为可选依赖（extra: gbdt）")

from rfauto.optimization.surrogate import (
    GBDTSurrogate,
    surrogate_registry,
)

BOUNDS = {"a": (0.0, 1.0), "b": (0.0, 1.0)}


def line_fn(a: float, b: float) -> float:
    """自写 2D 解析线语料（主效应+交互；禁引用 factory_m2_* 脚本口径）。"""
    return 3.0 * a + 1.5 * b + 0.8 * a * b + 0.2


def _corpus(n_train: int = 120, seed: int = 5):
    from rfauto.optimization.sample_design import lhs_points

    train = [{"params": p, "metrics": {"f": line_fn(p["a"], p["b"])}}
             for p in lhs_points(BOUNDS, n_train, seed=seed)["points"]]
    held = [{"params": {"a": a, "b": b}, "f": line_fn(a, b)}
            for a in np.linspace(0.05, 0.95, 5)
            for b in np.linspace(0.05, 0.95, 5)]
    return train, held


def _make_model(**cfg) -> GBDTSurrogate:
    return GBDTSurrogate(config={"bounds": BOUNDS, **cfg})


class TestGBDTRegistration:
    def test_registered(self):
        assert "gbdt" in surrogate_registry.available()

    def test_registry_create(self):
        model = surrogate_registry.create("gbdt", config={"bounds": BOUNDS})
        assert isinstance(model, GBDTSurrogate)
        assert model.KIND == "gbdt"

    def test_uncertainty_not_overridden_returns_none(self):
        """uncertainty() 不覆盖（基类默认 None）——σ 走 bootstrap/gp 通道。"""
        train, _ = _corpus()
        model = _make_model()
        model.fit(train)
        assert model.fitted
        assert model.uncertainty({"a": 0.5, "b": 0.5}) is None


class TestGBDTFit:
    def test_heldout_accuracy_on_synthetic_line(self):
        """120 点拟合 2D 解析线：held-out 峰值误差 ≤10%（量程归一）。

        门依据：GBDT 缺省超参（200/0.05/2）对角部交互项的阶梯近似使
        峰值误差集中在角点，实测 seeds{5,6,7} worst max_rel=5.75%
        （40 点时 ~14.5%——树模型样本需求的真实体现，不掩盖）；
        10% = 实测 1.7 倍裕量，仍远严于随机猜测（~30% 量级）。
        """
        train, held = _corpus()
        model = _make_model()
        model.fit(train)
        f_range = max(h["f"] for h in held) - min(h["f"] for h in held)
        errs = [abs(model.predict(h["params"])["f"] - h["f"]) / f_range
                for h in held]
        assert max(errs) <= 0.10, max(errs)

    def test_same_seed_two_fits_bitwise_identical(self):
        """同 config 两次 fit 预测逐位一致（subsample=1.0 + fixed seed）。"""
        train, held = _corpus()
        ma, mb = _make_model(), _make_model()
        ma.fit(train)
        mb.fit(train)
        pa = [ma.predict(h["params"])["f"] for h in held]
        pb = [mb.predict(h["params"])["f"] for h in held]
        assert pa == pb

    def test_hyperparams_config_overridable(self):
        train, held = _corpus()
        model = _make_model(n_estimators=10, learning_rate=0.2, max_depth=1)
        model.fit(train)
        assert model.fitted
        assert all(np.isfinite(model.predict(h["params"])["f"])
                   for h in held)


class TestGBDTNanMask:
    def test_nan_metrics_skipped_per_key(self):
        """逐指标 NaN 掩码：坏条目不进该键拟合；全 NaN 键不产出预测。"""
        from rfauto.optimization.sample_design import lhs_points

        pts = lhs_points(BOUNDS, 20, seed=9)["points"]
        samples = [{"params": p, "metrics": {"f": line_fn(p["a"], p["b"]),
                                             "bad": float("nan")}}
                   for p in pts]
        # 混入部分坏 f 条目（真机失败 trial 同构）
        samples[3]["metrics"]["f"] = float("nan")
        samples[7]["metrics"]["f"] = float("nan")
        model = _make_model()
        info = model.fit(samples)
        assert info["n_samples"] == 20 and model.fitted
        pred = model.predict({"a": 0.5, "b": 0.5})
        assert "f" in pred
        assert "bad" not in pred  # 全 NaN 键跳过不硬拟
        assert np.isfinite(pred["f"])

    def test_all_keys_nan_marks_unfitted_models_empty(self):
        pts = [{"params": {"a": 0.1 * i, "b": 0.2},
                "metrics": {"f": float("nan")}} for i in range(6)]
        model = _make_model()
        model.fit(pts)
        assert model.fitted
        assert model.predict({"a": 0.5, "b": 0.5}) == {}


class TestGBDTMissingSklearn:
    def test_import_error_raises_runtime_error_with_extra_hint(
        self, monkeypatch,
    ):
        """未装 sklearn：fit 显式 RuntimeError 提示 pip install rfauto[gbdt]
        （monkeypatch 钉住 import 通道，不依赖真实缺装环境）。"""
        monkeypatch.setitem(sys.modules, "sklearn.ensemble", None)
        model = _make_model()
        with pytest.raises(RuntimeError, match=r"rfauto\[gbdt\]"):
            model.fit([{"params": {"a": 0.1, "b": 0.2},
                        "metrics": {"f": 1.0}}])
