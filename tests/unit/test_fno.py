"""阶段 6.3 E3：FNO（谱卷积版）曲线算子插件测试（torch 缺失时跳过）。

合成解析曲线族（RLC 谐振反射）：并联 RLC 经 Z0=50Ω 线的输入阻抗
Zin = R / (1 + jQ(f/f0 − f0/f))，Γ = (Zin−Z0)/(Zin+Z0)，|S11|dB = 20log10|Γ|；
参数 x∈[0,1] 同时控制谷位 f0 = 2.0 + x GHz 与谷深（R = Z0·(0.2+0.8x)），
即谷的位置与深度都随参数变。门值来自离线实测（width 24 / modes 10 / 600-1200
epochs：held-out x=0.7 rms 0.09–0.27 dB、谷位零误差），门取 ≥3× 余量。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")

from rfauto.optimization.surrogate import FNOSurrogate, surrogate_registry

F_LO, F_HI = 1.5, 3.5
Z0 = 50.0


def rlc_s11_db(x: float, f_ghz: np.ndarray, q: float = 30.0) -> np.ndarray:
    """并联 RLC 谐振反射曲线（解析，见模块 docstring）。"""
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
            "width": 24, "n_modes": 10, "n_layers": 3, "seed": 42}
    base.update(over)
    return base


class TestFNORegistry:
    def test_registered_and_creatable(self):
        assert "fno" in surrogate_registry.available()
        m = surrogate_registry.create("fno", config=_cfg())
        assert isinstance(m, FNOSurrogate) and m.KIND == "fno"
        assert not m.fitted

    def test_legacy_kinds_still_present(self):
        kinds = surrogate_registry.available()
        for k in ("fno_lite", "deeponet", "poly_ridge", "smt_kriging"):
            assert k in kinds


@pytest.fixture(scope="module")
def fitted():
    """一次拟合供拟合类测试共用（800 epochs，CPU 十余秒）。"""
    _, samples = make_samples()
    model = FNOSurrogate(config=_cfg(epochs=800))
    info = model.fit(samples)
    return model, info


class TestFNOFit:
    def test_fit_info_contract(self, fitted):
        model, info = fitted
        assert model.fitted
        assert info["kind"] == "fno" and info["n_curves"] == 15
        assert info["n_curve_points"] == 128
        assert np.isfinite(info["final_loss"]) and info["final_loss"] < 1.0

    def test_heldout_curve_rms_and_valley(self, fitted):
        model, _ = fitted
        # x=0.7 不在 linspace(0,1,15) 训练网格上（真 held-out）
        out = model.predict_curve({"x": 0.7}, n_points=101)
        f = np.asarray(out["freq_ghz"])
        pred = np.asarray(out["s11_db"])
        true = rlc_s11_db(0.7, f)
        assert len(f) == 101 and len(pred) == 101
        rms = float(np.sqrt(np.mean((pred - true) ** 2)))
        assert rms <= 1.0, f"held-out 曲线 rms {rms:.3f} dB > 1.0 门"
        step = f[1] - f[0]  # 101 点 2GHz 跨度 = 20MHz
        valley_err = abs(f[int(np.argmin(pred))] - f[int(np.argmin(true))])
        assert valley_err <= step + 1e-9, f"谷位误差 {valley_err*1e3:.0f} MHz > 网格分辨率"
        # 谷深恢复：真值约 -17dB，预测应显著深于 -10dB
        assert pred.min() < -10.0

    def test_predict_scalar_contract(self, fitted):
        model, _ = fitted
        r = model.predict({"x": 0.5})
        assert set(r) == {"s11_db_min_in_band", "s11_curve_max_in_band"}
        curve = np.asarray(model.predict_curve({"x": 0.5})["s11_db"])
        assert r["s11_db_min_in_band"] == pytest.approx(float(curve.min()))
        assert r["s11_curve_max_in_band"] == pytest.approx(float(curve.max()))
        assert r["s11_db_min_in_band"] < r["s11_curve_max_in_band"]

    def test_predict_is_pure(self, fitted):
        model, _ = fitted
        a = model.predict_curve({"x": 0.3})["s11_db"]
        b = model.predict_curve({"x": 0.3})["s11_db"]
        assert a == b


class TestFNODeterminismAndErrors:
    def test_same_seed_bitwise_reproducible(self):
        _, samples = make_samples(n=8, n_pts=64)
        outs = []
        for _ in range(2):
            m = FNOSurrogate(config=_cfg(epochs=150, width=16, seed=7,
                                         curve_samples=64))
            m.fit(samples)
            outs.append(np.asarray(m.predict_curve({"x": 0.42})["s11_db"]))
        assert np.array_equal(outs[0], outs[1])

    def test_different_seed_differs(self):
        _, samples = make_samples(n=8, n_pts=64)
        outs = []
        for seed in (1, 2):
            m = FNOSurrogate(config=_cfg(epochs=50, width=16, seed=seed,
                                         curve_samples=64))
            m.fit(samples)
            outs.append(np.asarray(m.predict_curve({"x": 0.42})["s11_db"]))
        assert not np.array_equal(outs[0], outs[1])

    def test_n_modes_capped_to_grid(self):
        _, samples = make_samples(n=6, n_pts=32)
        m = FNOSurrogate(config=_cfg(epochs=20, width=8, n_modes=999,
                                     curve_samples=16))
        info = m.fit(samples)
        assert info["n_curve_points"] == 16
        assert len(m.predict_curve({"x": 0.1})["s11_db"]) == 16

    def test_requires_curve_samples(self):
        m = FNOSurrogate(config=_cfg())
        with pytest.raises(ValueError, match="曲线样本不足"):
            m.fit([{"params": {"x": 0.5}, "metrics": {"f": 1.0}}])

    def test_predict_before_fit_raises(self):
        m = FNOSurrogate(config=_cfg())
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict({"x": 0.5})

    def test_torch_missing_explicit_error(self, monkeypatch):
        _, samples = make_samples(n=6, n_pts=32)
        monkeypatch.setitem(sys.modules, "torch", None)  # import torch → ImportError
        m = FNOSurrogate(config=_cfg(epochs=1))
        with pytest.raises(RuntimeError, match="fno 需要 torch"):
            m.fit(samples)
