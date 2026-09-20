"""阶段 6.3 E3：DeepONet（branch×trunk）曲线算子插件测试（torch 缺失时跳过）。

合成解析曲线族与 test_fno 同源（并联 RLC 谐振反射，谷位/谷深都随 x 变）。
门值来自离线实测（p 32 / hidden 64 / depth 3 / trunk Fourier K=8 / 1500-2000
epochs，15 条曲线：held-out x=0.7 rms 0.67–0.74 dB、谷位 1 步）；对照无 Fourier
特征 rms 1.62 dB/谷深 −6 vs 真 −16.5——默认架构据此定。门取 ≥2× 余量。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")

from rfauto.optimization.surrogate import DeepONetSurrogate, surrogate_registry
from rfauto.optimization.surrogate.deeponet import _trunk_features

F_LO, F_HI = 1.5, 3.5
Z0 = 50.0


def rlc_s11_db(x: float, f_ghz: np.ndarray, q: float = 30.0) -> np.ndarray:
    f0 = 2.0 + 1.0 * x
    r = Z0 * (0.2 + 0.8 * x)
    zin = r / (1.0 + 1j * q * (f_ghz / f0 - f0 / f_ghz))
    gamma = (zin - Z0) / (zin + Z0)
    return (20.0 * np.log10(np.abs(gamma) + 1e-12)).astype(float)


def make_samples(n: int = 15, n_pts: int = 201) -> tuple[dict, list[dict]]:
    bounds = {"x": (0.0, 1.0)}
    f = np.linspace(F_LO, F_HI, n_pts)
    samples = [{"params": {"x": float(x)},
                "metrics": {"s11_curve_db": rlc_s11_db(x, f).tolist()}}
               for x in np.linspace(0.0, 1.0, n)]
    return bounds, samples


def _cfg(**over):
    base = {"bounds": {"x": (0.0, 1.0)}, "freq_grid": [F_LO, F_HI],
            "p": 32, "hidden": 64, "depth": 3, "trunk_fourier_feats": 8,
            "seed": 42}
    base.update(over)
    return base


class TestDeepONetRegistry:
    def test_registered_and_creatable(self):
        assert "deeponet" in surrogate_registry.available()
        m = surrogate_registry.create("deeponet", config=_cfg())
        assert isinstance(m, DeepONetSurrogate) and m.KIND == "deeponet"
        assert not m.fitted

    def test_trunk_features_shape(self):
        fn = np.linspace(0.4, 1.0, 10)
        assert _trunk_features(fn, 0).shape == (10, 1)
        feats = _trunk_features(fn, 3)
        assert feats.shape == (10, 7)
        np.testing.assert_allclose(feats[:, 0], fn)
        np.testing.assert_allclose(feats[:, 1], np.sin(2 * np.pi * fn))
        np.testing.assert_allclose(feats[:, 2], np.cos(2 * np.pi * fn))


@pytest.fixture(scope="module")
def fitted():
    """一次拟合供拟合类测试共用（1500 epochs，CPU 十余秒）。"""
    _, samples = make_samples()
    model = DeepONetSurrogate(config=_cfg(epochs=1500))
    info = model.fit(samples)
    return model, info


class TestDeepONetFit:
    def test_fit_info_contract(self, fitted):
        model, info = fitted
        assert model.fitted
        assert info["kind"] == "deeponet" and info["n_curves"] == 15
        assert info["n_curve_points"] == 128
        assert np.isfinite(info["final_loss"]) and info["final_loss"] < 2.0

    def test_heldout_curve_rms_and_valley(self, fitted):
        model, _ = fitted
        out = model.predict_curve({"x": 0.7}, n_points=101)  # x=0.7 真 held-out
        f = np.asarray(out["freq_ghz"])
        pred = np.asarray(out["s11_db"])
        true = rlc_s11_db(0.7, f)
        rms = float(np.sqrt(np.mean((pred - true) ** 2)))
        assert rms <= 1.5, f"held-out 曲线 rms {rms:.3f} dB > 1.5 门"
        step = f[1] - f[0]
        valley_err = abs(f[int(np.argmin(pred))] - f[int(np.argmin(true))])
        assert valley_err <= step + 1e-9, f"谷位误差 {valley_err*1e3:.0f} MHz > 网格分辨率"
        assert pred.min() < -10.0  # 真值约 -17dB

    def test_predict_scalar_contract(self, fitted):
        model, _ = fitted
        r = model.predict({"x": 0.5})
        assert set(r) == {"s11_db_min_in_band", "s11_curve_max_in_band"}
        curve = np.asarray(model.predict_curve({"x": 0.5})["s11_db"])
        assert r["s11_db_min_in_band"] == pytest.approx(float(curve.min()))
        assert r["s11_curve_max_in_band"] == pytest.approx(float(curve.max()))

    def test_predict_is_pure(self, fitted):
        model, _ = fitted
        assert (model.predict_curve({"x": 0.3})["s11_db"]
                == model.predict_curve({"x": 0.3})["s11_db"])


class TestDeepONetDeterminismAndErrors:
    def test_same_seed_bitwise_reproducible(self):
        _, samples = make_samples(n=8, n_pts=64)
        outs = []
        for _ in range(2):
            m = DeepONetSurrogate(config=_cfg(epochs=150, hidden=16, p=8,
                                              depth=2, seed=7, curve_samples=64))
            m.fit(samples)
            outs.append(np.asarray(m.predict_curve({"x": 0.42})["s11_db"]))
        assert np.array_equal(outs[0], outs[1])

    def test_bare_frequency_trunk_still_works(self):
        _, samples = make_samples(n=6, n_pts=32)
        m = DeepONetSurrogate(config=_cfg(epochs=20, hidden=8, p=4, depth=1,
                                          trunk_fourier_feats=0, curve_samples=16))
        info = m.fit(samples)
        assert info["n_curve_points"] == 16
        assert len(m.predict_curve({"x": 0.1}, n_points=9)["s11_db"]) == 9

    def test_requires_curve_samples(self):
        m = DeepONetSurrogate(config=_cfg())
        with pytest.raises(ValueError, match="曲线样本不足"):
            m.fit([{"params": {"x": 0.5}, "metrics": {"f": 1.0}}])

    def test_predict_before_fit_raises(self):
        m = DeepONetSurrogate(config=_cfg())
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict_curve({"x": 0.5})

    def test_torch_missing_explicit_error(self, monkeypatch):
        _, samples = make_samples(n=6, n_pts=32)
        monkeypatch.setitem(sys.modules, "torch", None)
        m = DeepONetSurrogate(config=_cfg(epochs=1))
        with pytest.raises(RuntimeError, match="deeponet 需要 torch"):
            m.fit(samples)
