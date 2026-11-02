"""T-N18 torch 曲线深度集成/完整版 FNO 单测（aurora_n W3，注册键 "deep_ensemble"）。

判据（任务书预声明，门值冻结于 runs/aurora_n/w3_tn18/criteria.md，标定=
同目录 probe_output_unit_tier.txt 单测档实测）：
- A1 RMSE 对照：多频正弦+趋势解析族（独立闭式真值面，#118 裁判与被测
  实现零共享代码路径）N=100 训练，held-out 插值/域外外推——fno(完整版)
  RMSE ≤ 0.10 / ≤ 0.50（绝对门，实测 0.0178/0.1021，余量 ≥4.9×）且
  fno ≤ fno_lite + 0.05（"完整版不劣于 lite"，实测优 0.31/0.38）；
- A2 σ 单调：密集区（85 点∈[0,0.5]）σ < 稀疏区（15 点∈[0.85,1.0]）σ
  且 < 空洞区（x=0.675 无样本）σ（实测 0.0112 < 0.0283/0.0242，比值
  ≥2.2×）+ σ_dense ≤ 0.05 绝对锚；
- A3 确定性：deep_ensemble 同 seed 两 fit，predict/uncertainty/
  predict_curve_with_std 逐位 np.array_equal（CPU 同平台语义；跨平台
  BLAS 轨迹漂移如实注记，只互比不钉绝对值，#247 家法）；
- A4 负例：fno 训练 loss NaN → 检测停+RuntimeError+fit_info["diverged"]
  如实+fitted=False；deep_ensemble n_members<2 → ValueError；成员全失败
  → RuntimeError"全部成员失败"+逐成员 error 原文；
- A5 零改动：既有键注册面全在（fno_lite/fno/deeponet/ensemble/poly_ridge/
  smt_kriging/conformal）+ 门面 re-export 同一对象 + model_card 出卡；
  行为零改动由邻接回归定向批（test_fno/test_fno_lite/test_ensemble_
  surrogate/test_deeponet）证明，本文件不重复。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

torch = pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")

from rfauto.optimization.surrogate import (
    DeepEnsembleSurrogate,
    FNOLiteSurrogate,
    FNOSurrogate,
    surrogate_registry,
)

# ── 合成语料（独立真值面，criteria.md A1/A2 同口径） ────────────────────

T_N = 32
T_AXIS = np.linspace(0.0, 1.0, T_N)


def truth_curve(x: float, t: np.ndarray = T_AXIS) -> np.ndarray:
    """多频正弦+趋势曲线族（criteria.md A1 原文公式）。"""
    a = 0.6 + 0.4 * np.sin(2.0 * x)
    b = 0.5 * np.cos(3.0 * x)
    c = 0.8 + 0.5 * x
    return (a * np.sin(2 * np.pi * 1.3 * t)
            + b * np.sin(2 * np.pi * 2.7 * t + 0.5 * x)
            + c * (0.3 + t))


def make_samples(xs: np.ndarray) -> list[dict]:
    return [{"params": {"x": float(x)},
             "metrics": {"s11_curve_db": truth_curve(x).tolist()}}
            for x in xs]


def rms_against_truth(model, xs_q) -> float:
    errs = []
    for x in xs_q:
        pred = np.asarray(model.predict_curve({"x": float(x)})["s11_db"])
        errs.append((pred - truth_curve(float(x))) ** 2)
    return float(np.sqrt(np.mean(np.concatenate(errs))))


#: 单测档配置（criteria.md 冻结口径：fno width12/modes5/layers2/epochs250）
FNO_CFG = {"bounds": {"x": (0.0, 1.0)}, "freq_grid": [0.0, 1.0],
           "curve_samples": T_N, "width": 12, "n_modes": 5,
           "n_layers": 2, "epochs": 250, "lr": 5e-3, "seed": 42}
LITE_CFG = {"bounds": {"x": (0.0, 1.0)}, "freq_grid": [0.0, 1.0],
            "curve_samples": T_N, "hidden": 24, "epochs": 250, "seed": 42}

XS_INTERP = np.array([0.13, 0.37, 0.52, 0.68, 0.81, 0.95])  # 域内 held-out
XS_EXTRAP = np.array([1.08, 1.2])  # 域外（双模型按设计 clip=边界持延语义）


# ── A1：RMSE 对照门（完整版 fno vs fno_lite，同数据 N=100） ─────────────

@pytest.fixture(scope="module")
def rmse_pair():
    rng = np.random.default_rng(20261029)
    samples = make_samples(rng.uniform(0.0, 1.0, 100))
    fno = FNOSurrogate(config=dict(FNO_CFG))
    fno.fit(samples)
    lite = FNOLiteSurrogate(config=dict(LITE_CFG))
    lite.fit(samples)
    return fno, lite


class TestRMSEGate:
    def test_interp_absolute_gate(self, rmse_pair):
        fno, _ = rmse_pair
        r = rms_against_truth(fno, XS_INTERP)
        assert r <= 0.10, f"完整版 fno 插值 RMSE {r:.4f} > 0.10 门"

    def test_interp_not_worse_than_lite(self, rmse_pair):
        fno, lite = rmse_pair
        r_f, r_l = rms_against_truth(fno, XS_INTERP), \
            rms_against_truth(lite, XS_INTERP)
        assert r_f <= r_l + 0.05, \
            f"完整版劣于 lite：fno {r_f:.4f} > lite {r_l:.4f} + 0.05"

    def test_extrap_absolute_gate(self, rmse_pair):
        # 域外语义如实注记：双模型按设计把参数 clip 到 bounds（边界持延）
        fno, _ = rmse_pair
        r = rms_against_truth(fno, XS_EXTRAP)
        assert np.isfinite(r) and r <= 0.50, \
            f"完整版 fno 外推 RMSE {r:.4f} > 0.50 门"

    def test_extrap_not_worse_than_lite(self, rmse_pair):
        fno, lite = rmse_pair
        r_f, r_l = rms_against_truth(fno, XS_EXTRAP), \
            rms_against_truth(lite, XS_EXTRAP)
        assert r_f <= r_l + 0.05, \
            f"完整版劣于 lite：fno {r_f:.4f} > lite {r_l:.4f} + 0.05"


# ── A2：深度集成 σ 单调性（密集区小/稀疏区大） ──────────────────────────

@pytest.fixture(scope="module")
def sigma_ensemble():
    rng = np.random.default_rng(7)
    pool = make_samples(np.concatenate([rng.uniform(0.0, 0.5, 85),
                                        rng.uniform(0.85, 1.0, 15)]))
    m = DeepEnsembleSurrogate(config={
        **FNO_CFG, "base_kind": "fno", "n_members": 3, "seed": 42,
        "bootstrap": True, "dispersion": "std"})
    info = m.fit(pool)
    return m, info


class TestSigmaMonotonic:
    def test_dense_smaller_than_sparse_and_gap(self, sigma_ensemble):
        m, _info = sigma_ensemble
        sig = {q: float(np.mean(np.asarray(
                   m.predict_curve_with_std({"x": q})["s11_db_std"])))
               for q in (0.25, 0.92, 0.675)}  # 密集/稀疏/空洞
        assert sig[0.25] < sig[0.92], \
            f"σ 密集 {sig[0.25]:.4f} 未小于 σ 稀疏 {sig[0.92]:.4f}"
        assert sig[0.25] < sig[0.675], \
            f"σ 密集 {sig[0.25]:.4f} 未小于 σ 空洞 {sig[0.675]:.4f}"
        assert sig[0.25] <= 0.05, f"σ 密集 {sig[0.25]:.4f} > 0.05 绝对锚"

    def test_curve_with_std_contract(self, sigma_ensemble):
        m, _info = sigma_ensemble
        out = m.predict_curve_with_std({"x": 0.4}, n_points=24)
        assert set(out) == {"freq_ghz", "s11_db", "s11_db_std"}
        assert len(out["freq_ghz"]) == len(out["s11_db"]) \
            == len(out["s11_db_std"]) == 24
        assert all(s >= 0.0 for s in out["s11_db_std"])

    def test_uncertainty_contract_matches_predict_keys(self, sigma_ensemble):
        m, _info = sigma_ensemble
        pt = {"x": 0.4}
        pred, unc = m.predict(pt), m.uncertainty(pt)
        assert set(unc) == set(pred)
        assert all(isinstance(v, float) and v >= 0.0 for v in unc.values())

    def test_fit_info_honesty(self, sigma_ensemble):
        _m, info = sigma_ensemble
        assert info["kind"] == "deep_ensemble"
        assert info["n_members"] == 3 and info["n_members_effective"] == 3
        assert info["base_kind"] == "fno" and info["bootstrap"] is True
        assert [r["status"] for r in info["members"]] == ["active"] * 3
        assert [r["seed"] for r in info["members"]] == [42, 43, 44]
        assert len({r["n_train"] for r in info["members"]}) == 1  # bootstrap 同规模


# ── A3：确定性钉（同 seed 两 fit 逐位） ─────────────────────────────────

class TestDeterminism:
    def test_same_seed_bitwise_reproducible(self):
        rng = np.random.default_rng(11)
        pool = make_samples(rng.uniform(0.0, 1.0, 8))
        cfg = {**FNO_CFG, "curve_samples": 16, "width": 8, "n_modes": 3,
               "epochs": 60, "base_kind": "fno", "n_members": 2,
               "seed": 7, "bootstrap": False}  # False 档=仅异 seed 多样性
        outs = []
        for _ in range(2):
            m = DeepEnsembleSurrogate(config=dict(cfg))
            m.fit(pool)
            pt = {"x": 0.42}
            outs.append((m.predict(pt), m.uncertainty(pt),
                         m.predict_curve_with_std(pt)))
        assert outs[0][0] == outs[1][0]
        assert outs[0][1] == outs[1][1]
        for k in ("freq_ghz", "s11_db", "s11_db_std"):
            assert np.array_equal(np.asarray(outs[0][2][k]),
                                  np.asarray(outs[1][2][k])), k


# ── A4：负例（NaN 发散检测停 / 构造校验 / 成员全失败） ───────────────────

class TestNegatives:
    def test_fno_nan_loss_detect_stop_honest(self):
        rng = np.random.default_rng(5)
        samples = make_samples(rng.uniform(0.0, 1.0, 6))
        samples[2]["metrics"]["s11_curve_db"] = [
            float("nan")] * len(samples[2]["metrics"]["s11_curve_db"])
        m = FNOSurrogate(config={**FNO_CFG, "epochs": 30, "width": 8,
                                 "n_modes": 3, "curve_samples": 16})
        with pytest.raises(RuntimeError, match="训练发散"):
            m.fit(samples)
        assert not m.fitted
        assert m.fit_info["diverged"] is True
        assert m.fit_info["diverged_at_epoch"] == 1
        assert not np.isfinite(m.fit_info["final_loss"])

    def test_n_members_below_two_rejected(self):
        with pytest.raises(ValueError, match="n_members"):
            DeepEnsembleSurrogate(config={**FNO_CFG, "n_members": 1})

    def test_all_members_fail_unregistered_kind(self):
        rng = np.random.default_rng(5)
        pool = make_samples(rng.uniform(0.0, 1.0, 6))
        m = DeepEnsembleSurrogate(config={
            **FNO_CFG, "epochs": 5, "n_members": 2, "bootstrap": False,
            "base_kind": "no_such_kind"})
        with pytest.raises(RuntimeError, match="全部成员失败"):
            m.fit(pool)
        assert not m.fitted

    def test_all_members_fail_nan_propagates_honestly(self):
        rng = np.random.default_rng(5)
        pool = make_samples(rng.uniform(0.0, 1.0, 6))
        pool[0]["metrics"]["s11_curve_db"] = [
            float("nan")] * len(pool[0]["metrics"]["s11_curve_db"])
        m = DeepEnsembleSurrogate(config={
            **FNO_CFG, "epochs": 5, "n_members": 2, "bootstrap": False,
            "base_kind": "fno", "width": 8, "n_modes": 3,
            "curve_samples": 16})
        # bootstrap=False：保证 NaN 样本进每个成员的训练集（bootstrap 有
        # 放回抽样可能恰好抽掉坏样本=正确的鲁棒行为，不适合做本负例载体）
        with pytest.raises(RuntimeError, match="全部成员失败") as ei:
            m.fit(pool)
        assert "训练发散" in str(ei.value)  # 逐成员 error 原文不静默
        assert not m.fitted


# ── A5：注册面/门面/model_card（零改动的存在性面） ───────────────────────

class TestRegistryAndFacade:
    def test_registered_and_legacy_kinds_intact(self):
        kinds = surrogate_registry.available()
        assert "deep_ensemble" in kinds
        for k in ("fno", "fno_lite", "deeponet", "ensemble", "poly_ridge",
                  "smt_kriging", "conformal"):
            assert k in kinds, f"既有键 {k} 消失（零改动红线）"

    def test_facade_reexport_same_object(self):
        from rfauto.optimization.surrogate import (
            DeepEnsembleSurrogate as FacadeCls,
        )
        assert FacadeCls is DeepEnsembleSurrogate
        m = surrogate_registry.create("deep_ensemble", config=dict(FNO_CFG))
        assert isinstance(m, DeepEnsembleSurrogate)
        assert m.KIND == "deep_ensemble" and not m.fitted

    def test_model_card_registry_surface(self):
        from rfauto.service.model_card_service import (
            build_model_card,
            registry_model_ids,
        )
        assert "deep_ensemble" in registry_model_ids()["surrogate"]
        card = build_model_card("deep_ensemble", "registry")
        assert card.get("ok") is not False
        assert card.get("model_id") == "deep_ensemble"
        assert card.get("kind") == "surrogate"

    def test_predict_before_fit_raises(self):
        m = DeepEnsembleSurrogate(config=dict(FNO_CFG))
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict({"x": 0.5})
        with pytest.raises(RuntimeError, match="未拟合"):
            m.predict_curve_with_std({"x": 0.5})
