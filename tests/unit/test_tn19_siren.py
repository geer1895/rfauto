"""T-N19 SIREN 坐标场代理单测（aurora_n W3，注册键 "siren"）。

判据（任务书预声明，门值冻结于 runs/aurora_n/w3_tn19/criteria.md，标定=
同目录 probe_output/probe_w0sweep/probe_realtier/probe_complex 实测）：
- A1 合成对照：2D 驻波场 cos(2π4x)cos(2π6y)+0.3cos(2π3x)+0.5（独立闭式
  真值面，#118 裁判与被测实现零共享代码路径）N=1024 训练 → 64×64 网格
  重建 RMSE ≤ 0.20（实测 0.1154）+ 频谱保真：空间 FFT 非 DC 主峰位置
  回收（真值四峰 (±4,±6) 曼哈顿距离 ≤ 1.5 bin，实测 0.0）+ 主峰幅值比
  ∈ [0.8,1.2]（实测 0.957）——RF 场代理的物理语义门；
- A2 复数场：cos(2π3x)·e^{i2π5y}（论文 §4.3 双通道 re/im 口径）→
  RMSE(|Δ|²) ≤ 0.20（实测 0.1075）+ predict 返回 complex；
- A3 确定性：同 seed 两 fit，32×32 预测网格逐位 np.array_equal +
  fit_info 逐键相等（CPU 同平台语义；跨平台 BLAS 轨迹漂移如实注记，
  只互比不钉绝对值，#247 家法）；
- A4 负例：坐标维度错（fit/predict 键集不对账）ValueError；场值
  NaN/Inf → 训练发散检测停 RuntimeError+fit_info["diverged"]+
  fitted=False（fno 家法）；实/复混杂/非数值场值/样本不足/坐标 NaN/
  config 校验/未拟合 predict 逐项显式报错；
- A5 零改动存在面：既有键注册面全在+门面 re-export 同一对象+
  model_card 出卡+uncertainty()=None（无原生 σ 不伪造，#122）；
  行为零改动由邻接回归定向批（fno/fno_lite/deeponet/deep_ensemble/
  ensemble/nn/surrogate_analysis/factory_m2）证明，本文件不重复。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")

from rfauto.optimization.surrogate import (
    SirenFieldSurrogate,
    surrogate_registry,
)

# ── 独立真值面（criteria.md 同口径；与被测实现零共享代码路径） ──────────

G = 64
GX, GY = np.meshgrid(np.linspace(0.0, 1.0, G), np.linspace(0.0, 1.0, G))
KX, KY = 4.0, 6.0  # 主峰空间频率（周期/单位长；64 点网格 FFT bin=4/6）
TRUE_PEAKS = ((KX, KY), (KX, -KY), (-KX, KY), (-KX, -KY))


def truth_field(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """2D 驻波场+背景（criteria.md A1 原文公式）。"""
    return (np.cos(2 * np.pi * KX * x) * np.cos(2 * np.pi * KY * y)
            + 0.3 * np.cos(2 * np.pi * 3.0 * x) + 0.5)


def truth_complex(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.cos(2 * np.pi * 3.0 * x) * np.exp(1j * 2 * np.pi * 5.0 * y)


TRUTH_GRID = truth_field(GX, GY)
TRUTH_CGRID = truth_complex(GX, GY)


def make_samples(pts: np.ndarray, mode: str = "real") -> list[dict]:
    x, y = pts[:, 0], pts[:, 1]
    v = truth_field(x, y) if mode == "real" else truth_complex(x, y)
    return [{"params": {"x": float(px), "y": float(py)},
             "metrics": {"field": complex(pv) if mode == "complex"
                         else float(pv)}}
            for px, py, pv in zip(x, y, v, strict=True)]


def eval_grid(model, truth: np.ndarray) -> np.ndarray:
    """模型重建场（64×64；pred[i,j]=f(x_j, y_i) 与 truth 网格同构）。"""
    return np.array([[model.predict({"x": float(gx), "y": float(gy)})["field"]
                      for gx in GX[0]] for gy in GY[:, 0]])


def dominant_peak(field: np.ndarray) -> tuple[int, int, float]:
    """非 DC 主峰：(kx, ky, |F|)——fft2 输入按 [y, x] 索引，故 kx=col−G/2。"""
    f = np.abs(np.fft.fftshift(np.fft.fft2(field)))
    f[G // 2, G // 2] = 0.0  # 掐 DC（背景项不参与峰判定）
    r, c = np.unravel_index(np.argmax(f), f.shape)
    return c - G // 2, r - G // 2, float(f[r, c])


def truth_peak_ref() -> tuple[tuple[int, int], float]:
    """真值主峰参考（幅值比门基准）：四峰严格简并（幅各 0.25），argmax
    破缺方向不钉死——位置门用"重建峰距四峰族最近距离"判（见 A1b）。"""
    kx, ky, amp = dominant_peak(TRUTH_GRID)
    return (kx, ky), amp


#: 单测档配置（criteria.md 冻结口径）
UNIT_CFG = {"coord_keys": ["x", "y"], "field_key": "field", "width": 32,
            "n_hidden": 2, "epochs": 600, "lr": 1e-3, "w0": 15.0, "seed": 42}
DATA_SEED = 20261029


def unit_points(n: int = 1024, seed: int = DATA_SEED) -> np.ndarray:
    return np.random.default_rng(seed).uniform(0.0, 1.0, (n, 2))


# ── A1：实数场 RMSE+频谱保真门 ───────────────────────────────────────────

@pytest.fixture(scope="module")
def fitted_real():
    m = SirenFieldSurrogate(config=dict(UNIT_CFG))
    m.fit(make_samples(unit_points()))
    return m


@pytest.fixture(scope="module")
def fitted_complex():
    m = SirenFieldSurrogate(config=dict(UNIT_CFG))
    m.fit(make_samples(unit_points(), mode="complex"))
    return m


class TestFieldReconstructionGate:
    def test_rmse_gate(self, fitted_real):
        recon = eval_grid(fitted_real, TRUTH_GRID)
        rmse = float(np.sqrt(np.mean((recon - TRUTH_GRID) ** 2)))
        assert rmse <= 0.20, f"重建 RMSE {rmse:.4f} > 0.20 门"

    def test_fft_peak_position_recovery(self, fitted_real):
        recon = eval_grid(fitted_real, TRUTH_GRID)
        kx_r, ky_r, _amp = dominant_peak(recon)
        dmin = min(abs(kx_r - kx) + abs(ky_r - ky) for kx, ky in TRUE_PEAKS)
        assert dmin <= 1.5, \
            f"主峰位置 (kx={kx_r}, ky={ky_r}) 距真值峰族 {TRUE_PEAKS} " \
            f"曼哈顿距离 {dmin} bin > 1.5 门"

    def test_fft_peak_amplitude_fidelity(self, fitted_real):
        recon = eval_grid(fitted_real, TRUTH_GRID)
        _kt, _pt, at = dominant_peak(TRUTH_GRID)
        _kr, _pr, ar = dominant_peak(recon)
        ratio = ar / at
        assert 0.8 <= ratio <= 1.2, f"主峰幅值比 {ratio:.3f} ∉ [0.8, 1.2]"

    def test_predict_contract_pointwise(self, fitted_real):
        v = fitted_real.predict({"x": 0.37, "y": 0.61})
        assert set(v) == {"field"}
        assert isinstance(v["field"], float)
        err = abs(v["field"] - float(truth_field(np.array(0.37),
                                                 np.array(0.61))))
        assert err <= 0.30, f"单点误差 {err:.4f} > 0.30"

    def test_fit_info_honesty(self, fitted_real):
        info = fitted_real.fit_info
        assert info["kind"] == "siren"
        assert info["coord_keys"] == ["x", "y"]
        assert info["field_mode"] == "real" and info["n_points"] == 1024
        assert info["bounds_inferred"] is True  # bounds 缺省=训练样本推断
        assert set(info["bounds"]) == {"x", "y"}


# ── A2：复数场（论文 §4.3 双通道口径） ──────────────────────────────────

class TestComplexField:
    def test_complex_rmse_gate_and_type(self, fitted_complex):
        assert fitted_complex.fit_info["field_mode"] == "complex"
        recon = eval_grid(fitted_complex, TRUTH_CGRID)
        rmse = float(np.sqrt(np.mean(np.abs(recon - TRUTH_CGRID) ** 2)))
        assert rmse <= 0.20, f"复数场重建 RMSE {rmse:.4f} > 0.20 门"
        v = fitted_complex.predict({"x": 0.37, "y": 0.61})["field"]
        assert isinstance(v, complex), \
            f"复数模式 predict 应返回 complex，得 {type(v).__name__}"

    def test_real_complex_mix_rejected(self):
        pts = unit_points(16)
        samples = make_samples(pts)
        samples[3]["metrics"]["field"] = complex(0.5, 0.1)
        m = SirenFieldSurrogate(config={**UNIT_CFG, "epochs": 5})
        with pytest.raises(ValueError, match="实/复混杂"):
            m.fit(samples)


# ── A3：确定性钉（同 seed 两 fit 逐位） ─────────────────────────────────

class TestDeterminism:
    def test_same_seed_bitwise_reproducible(self):
        pool = make_samples(unit_points(256, seed=7))
        cfg = {**UNIT_CFG, "width": 24, "epochs": 200}
        outs = []
        for _ in range(2):
            m = SirenFieldSurrogate(config=dict(cfg))
            m.fit(pool)
            grid = np.array([[m.predict({"x": float(gx), "y": float(gy)})["field"]
                              for gx in np.linspace(0, 1, 32)]
                             for gy in np.linspace(0, 1, 32)])
            outs.append((grid, dict(m.fit_info)))
        assert np.array_equal(outs[0][0], outs[1][0])
        assert outs[0][1] == outs[1][1]


# ── A4：负例（坐标维度错 / 训练发散 NaN 检测停 / config 校验） ───────────

class TestNegatives:
    def test_fit_coord_dim_mismatch_rejected(self):
        m = SirenFieldSurrogate(config=dict(UNIT_CFG))
        samples = [{"params": {"x": 0.1, "z": 0.2}, "metrics": {"field": 1.0}}
                   for _ in range(16)]
        with pytest.raises(ValueError, match="坐标维度错"):
            m.fit(samples)
        assert not m.fitted

    def test_predict_coord_dim_mismatch_rejected(self, fitted_real):
        with pytest.raises(ValueError, match="坐标维度错"):
            fitted_real.predict({"x": 0.5})  # 缺 y
        with pytest.raises(ValueError, match="坐标维度错"):
            fitted_real.predict({"x": 0.5, "y": 0.5, "z": 0.5})  # 多余键

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_nan_inf_field_train_divergence_detect_stop(self, bad):
        m = SirenFieldSurrogate(config={**UNIT_CFG, "epochs": 30})
        samples = make_samples(unit_points(16, seed=5))
        samples[2]["metrics"]["field"] = bad
        with pytest.raises(RuntimeError, match="训练发散"):
            m.fit(samples)
        assert not m.fitted
        assert m.fit_info["diverged"] is True
        assert m.fit_info["diverged_at_epoch"] == 1
        assert not np.isfinite(m.fit_info["final_loss"])

    def test_non_numeric_field_rejected(self):
        samples = make_samples(unit_points(16, seed=5))
        samples[1]["metrics"]["field"] = "0.5"
        m = SirenFieldSurrogate(config=dict(UNIT_CFG))
        with pytest.raises(ValueError, match="int/float/complex"):
            m.fit(samples)

    def test_too_few_points_rejected(self):
        m = SirenFieldSurrogate(config=dict(UNIT_CFG))
        with pytest.raises(ValueError, match="场样本不足"):
            m.fit(make_samples(unit_points(7, seed=5)))

    def test_nan_coord_rejected_at_prep(self):
        samples = make_samples(unit_points(16, seed=5))
        samples[4]["params"]["x"] = float("nan")
        m = SirenFieldSurrogate(config=dict(UNIT_CFG))
        with pytest.raises(ValueError, match="NaN/Inf"):
            m.fit(samples)

    def test_config_validation(self):
        base = dict(UNIT_CFG)
        with pytest.raises(ValueError, match="coord_keys"):
            SirenFieldSurrogate(config={**base, "coord_keys": []})
        with pytest.raises(ValueError, match="coord_keys"):
            SirenFieldSurrogate(config={**base, "coord_keys": "xy"})
        with pytest.raises(ValueError, match="重复"):
            SirenFieldSurrogate(config={**base, "coord_keys": ["x", "x"]})
        with pytest.raises(ValueError, match="w0"):
            SirenFieldSurrogate(config={**base, "w0": 0.0})
        with pytest.raises(ValueError, match="n_hidden"):
            SirenFieldSurrogate(config={**base, "n_hidden": 0})
        with pytest.raises(ValueError, match="bounds"):
            SirenFieldSurrogate(config={**base, "bounds": {"x": (0, 1)}})
        with pytest.raises(ValueError, match="lo<hi"):
            SirenFieldSurrogate(config={
                **base, "bounds": {"x": (1, 0), "y": (0, 1)}})

    def test_predict_before_fit_raises(self):
        m = SirenFieldSurrogate(config=dict(UNIT_CFG))
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict({"x": 0.5, "y": 0.5})


# ── A5：注册面/门面/model_card（零改动的存在性面） ───────────────────────

class TestRegistryAndFacade:
    def test_registered_and_legacy_kinds_intact(self):
        kinds = surrogate_registry.available()
        assert "siren" in kinds
        for k in ("fno", "fno_lite", "deeponet", "ensemble", "poly_ridge",
                  "smt_kriging", "conformal", "deep_ensemble"):
            assert k in kinds, f"既有键 {k} 消失（零改动红线）"

    def test_facade_reexport_same_object(self):
        from rfauto.optimization.surrogate import SirenFieldSurrogate as F
        assert F is SirenFieldSurrogate
        m = surrogate_registry.create("siren", config=dict(UNIT_CFG))
        assert isinstance(m, SirenFieldSurrogate)
        assert m.KIND == "siren" and not m.fitted

    def test_model_card_registry_surface(self):
        from rfauto.service.model_card_service import (
            build_model_card,
            registry_model_ids,
        )
        assert "siren" in registry_model_ids()["surrogate"]
        card = build_model_card("siren", "registry")
        assert card.get("ok") is not False
        assert card.get("model_id") == "siren"
        assert card.get("kind") == "surrogate"

    def test_uncertainty_honest_none(self, fitted_real):
        # 无原生不确定度：走 base 缺省 None（不伪造 σ，#122）
        assert fitted_real.uncertainty({"x": 0.5, "y": 0.5}) is None
