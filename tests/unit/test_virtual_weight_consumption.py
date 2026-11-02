"""T-N2 虚拟样本置信度加权消费单测（aurora_n W1-B 席 B）。

预声明门（探针 runs/aurora_n/wave1_b/probe_tn2_regime.py /
probe_tn2_familyB.py / probe_tn2_rmse.py 定标后钉死，#207 拒绝种子彩票
——门设在多样本扫描分布上不是单 seed）：
- G1 LOOCV ρ A/B 门（提案字面）：27 组合扫描（噪声 0/0.03/0.08 ×
  锚点 seed 3/17/29 × 虚拟 seed 42/101/7）下 ρ_加权 ≥ ρ_平权 − 1/12。
  容差=1 个秩换步长 1/12≈0.083（n=9 折 Spearman 的粒度；实测 min
  −0.067、mean −0.0025 全过——粒度以下的方向抖动如实不钉单值方向）。
- G2 机制 RMSE 门（#118 独立裁判）：族 B 混合 regime（24 blend +
  6 port_scale 同参数冲突样本）同扫描下，独立稠密网格验证
  RMSE_加权 ≤ RMSE_平权 27/27（实测均值 −0.0086——族 B 冲突样本
  被平权拉向 (1+α)/2·y、加权恢复，机制方向钉）。
- 负例：权重全 0 / 负 / NaN 显式 ValueError 不静默退化。
- 确定性钉（AGENTS 7）：同锚同种子虚拟样本+加权拟合逐位复现。
- 缺省等价钉：旋钮关=旧路径逐位（样本携带权重键也忽略）；旋钮开+
  全 1 权重=旧路径逐位（质量守恒归一 c=1.0 精确）。

裁判独立构造（#118）：真值=独立闭式纯二次函数，与被测实现零共享
代码路径；验证网格独立于训练/虚拟样本构造。
"""

from __future__ import annotations

import json

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 三批单源化）。"""
    yield


BOUNDS = {"x1": (0.0, 1.0), "x2": (0.0, 1.0)}
#: 预声明 A/B 门容差 = 1 个秩换步长（n=9 折 Spearman 粒度 1/12≈0.083）
RHO_TOL = 1.0 / 12.0


def truth(x1: float, x2: float) -> float:
    """独立闭式真值（纯二次，在 poly_ridge order-2 假设空间内）：
    虚拟样本的凸组合 Jensen 偏置与族 B 同参数冲突是 A/B 间唯一系统差。"""
    return (1.0 + 0.8 * x1 - 0.6 * x2 + 1.2 * x1 * x2 - 1.5 * x1 * x1
            + 0.35 * x2 * x2)


def make_anchors(seed: int, noise: float) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = np.linspace(0.05, 0.95, 3)
    return [{"params": {"x1": float(a), "x2": float(b)},
             "metrics": {"cost": truth(float(a), float(b))
                         + float(rng.normal(0.0, noise))}}
            for a in xs for b in xs]


def factory(weighted: bool):
    from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
    from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

    cfg: dict = {"bounds": BOUNDS, "order": 2, "ridge_lambda": 0.1}
    if weighted:
        cfg["sample_weight_key"] = VIRTUAL_WEIGHT_KEY
    return lambda: PolyRidgeSurrogate(config=cfg)


def cost_fn(sample: dict) -> float:
    return float(sample["metrics"]["cost"])


def val_rmse(model) -> float:
    g = np.linspace(0.02, 0.98, 11)
    errs = [model.predict({"x1": float(a), "x2": float(b)})["cost"]
            - truth(float(a), float(b)) for a in g for b in g]
    return float(np.sqrt(np.mean(np.square(errs))))


# ─── 预声明 A/B 门（G1 LOOCV ρ / G2 独立验证 RMSE） ──────────────────────────


class TestABGates:
    def test_g1_loocv_rho_not_worse_within_rank_granularity(self):
        """G1：27 组合扫描 ρ_加权 ≥ ρ_平权 − 1/12（预声明，全过）。"""
        from rfauto.optimization.surrogate import generate_virtual_samples

        worst = 0.0
        for noise in (0.0, 0.03, 0.08):
            for sa in (3, 17, 29):
                for sv in (42, 101, 7):
                    anchors = make_anchors(sa, noise)
                    virts = generate_virtual_samples(
                        anchors, bounds=BOUNDS, n_blend=30, seed=sv)
                    full = anchors + virts
                    folds = list(range(len(anchors)))
                    from rfauto.optimization.surrogate import loocv_rho
                    ra = loocv_rho(full, cost_fn, factory(False),
                                   eval_indices=folds)["rho"]
                    rb = loocv_rho(full, cost_fn, factory(True),
                                   eval_indices=folds)["rho"]
                    worst = min(worst, rb - ra)
        assert worst >= -RHO_TOL, f"最差 ρ 差 {worst} 破 1 秩换容差"

    def test_g2_conflict_regime_rmse_weighted_not_worse(self):
        """G2：族 B 混合 regime 加权验证 RMSE ≤ 平权（27/27，机制方向）。"""
        from rfauto.optimization.surrogate import generate_virtual_samples

        n_win = 0
        for noise in (0.0, 0.03, 0.08):
            for sa in (3, 17, 29):
                for sv in (42, 101, 7):
                    anchors = make_anchors(sa, noise)
                    virts = generate_virtual_samples(
                        anchors, bounds=BOUNDS, n_blend=24, n_scale=6,
                        seed=sv)
                    full = anchors + virts
                    flat = factory(False)()
                    weighted = factory(True)()
                    flat.fit(full)
                    weighted.fit(full)
                    if val_rmse(weighted) <= val_rmse(flat):
                        n_win += 1
        assert n_win == 27, f"RMSE 加权不劣于平权仅 {n_win}/27"

    def test_conflict_flat_pulls_anchor_weighted_recovers(self):
        """机制具象钉（确定性单例）：族 B 同参数冲突平权把锚点预测拉向
        (1+α)/2·y，加权（w=α）恢复——方向断言带余量。"""
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY

        anchors = make_anchors(3, 0.0)
        # 族 B：每锚点一条 α·cost 缩放样本（同参数冲突，语义同
        # generate_virtual_samples 族 B 的标量形态，独立构造裁判）
        conflict = [{"params": dict(a["params"]),
                     "metrics": {"cost": 0.5 * a["metrics"]["cost"]},
                     VIRTUAL_WEIGHT_KEY: 0.5} for a in anchors[:6]]
        full = anchors + conflict
        flat = factory(False)()
        weighted = factory(True)()
        flat.fit(full)
        weighted.fit(full)
        err_flat = np.mean([abs(flat.predict(a["params"])["cost"]
                                - a["metrics"]["cost"]) for a in anchors])
        err_w = np.mean([abs(weighted.predict(a["params"])["cost"]
                             - a["metrics"]["cost"]) for a in anchors])
        assert err_w < err_flat, (f"加权锚点误差 {err_w} 未优于平权 "
                                  f"{err_flat}（冲突拉偏恢复方向破）")


# ─── 负例（显式报错不静默退化） ───────────────────────────────────────────────


class TestNegativeCases:
    def test_all_zero_weights_raise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

        samples = [{"params": {"x1": 0.1 * i, "x2": 0.2},
                    "metrics": {"cost": 1.0 + i},
                    VIRTUAL_WEIGHT_KEY: 0.0} for i in range(6)]
        model = PolyRidgeSurrogate(config={
            "bounds": BOUNDS, "order": 1,
            "sample_weight_key": VIRTUAL_WEIGHT_KEY})
        with pytest.raises(ValueError, match="权重"):
            model.fit(samples)

    def test_negative_and_nan_weights_raise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

        base = [{"params": {"x1": 0.1 * i, "x2": 0.2},
                 "metrics": {"cost": 1.0 + i}} for i in range(6)]
        for bad in (-0.5, float("nan")):
            samples = [dict(s) for s in base]
            samples[2][VIRTUAL_WEIGHT_KEY] = bad
            model = PolyRidgeSurrogate(config={
                "bounds": BOUNDS, "order": 1,
                "sample_weight_key": VIRTUAL_WEIGHT_KEY})
            with pytest.raises(ValueError, match=r"非法|不可转"):
                model.fit(samples)

    def test_nn_all_zero_weights_raise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.nn_model import NNSurrogate

        samples = [{"params": {"x1": 0.1 * i, "x2": 0.2},
                    "metrics": {"cost": 1.0 + i},
                    VIRTUAL_WEIGHT_KEY: 0.0} for i in range(6)]
        model = NNSurrogate(config={
            "bounds": BOUNDS, "augmenter": "polynomial_cross",
            "epochs": 5, "n_ensemble": 1,
            "sample_weight_key": VIRTUAL_WEIGHT_KEY})
        with pytest.raises(ValueError, match="权重"):
            model.fit(samples)

    def test_nn_negative_weight_raises(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.nn_model import NNSurrogate

        samples = [{"params": {"x1": 0.1 * i, "x2": 0.2},
                    "metrics": {"cost": 1.0 + i}} for i in range(6)]
        samples[1][VIRTUAL_WEIGHT_KEY] = -0.2
        model = NNSurrogate(config={
            "bounds": BOUNDS, "augmenter": "polynomial_cross",
            "epochs": 5, "n_ensemble": 1,
            "sample_weight_key": VIRTUAL_WEIGHT_KEY})
        with pytest.raises(ValueError, match="非法"):
            model.fit(samples)


# ─── 缺省等价钉（旋钮关=旧路径逐位） ─────────────────────────────────────────


class TestDefaultEquivalence:
    def test_knob_off_ignores_weight_keys_bitwise(self):
        """旋钮关：样本带权重键与否，模型系数逐位一致（旧路径不读键）。"""
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

        rng = np.random.default_rng(13)
        plain = [{"params": {"x1": float(rng.uniform()), "x2": 0.3},
                  "metrics": {"cost": 1.0 + i * 0.1}}
                 for i in range(10)]
        tagged = [dict(s, **{VIRTUAL_WEIGHT_KEY: 0.4}) for s in plain]
        m1 = PolyRidgeSurrogate(config={"bounds": BOUNDS, "order": 2})
        m2 = PolyRidgeSurrogate(config={"bounds": BOUNDS, "order": 2})
        m1.fit(plain)
        m2.fit(tagged)
        assert np.array_equal(m1.models["cost"], m2.models["cost"])

    def test_all_one_weights_bitwise_old_path(self):
        """旋钮开+全 1 权重：质量守恒 c=1.0 精确 → 与旧路径逐位一致。"""
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

        rng = np.random.default_rng(17)
        plain = [{"params": {"x1": float(rng.uniform()), "x2": 0.6},
                  "metrics": {"cost": 0.5 + i}}
                 for i in range(10)]
        tagged = [dict(s, **{VIRTUAL_WEIGHT_KEY: 1.0}) for s in plain]
        m1 = PolyRidgeSurrogate(config={"bounds": BOUNDS, "order": 2})
        m2 = PolyRidgeSurrogate(config={
            "bounds": BOUNDS, "order": 2,
            "sample_weight_key": VIRTUAL_WEIGHT_KEY})
        m1.fit(plain)
        m2.fit(tagged)
        assert np.array_equal(m1.models["cost"], m2.models["cost"])

    def test_nn_knob_off_ignores_weight_keys_bitwise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.nn_model import NNSurrogate

        samples = [{"params": {"x1": (i % 3) / 2, "x2": (i // 3) / 2},
                    "metrics": {"cost": 1.0 + 0.3 * i}} for i in range(9)]
        tagged = [dict(s, **{VIRTUAL_WEIGHT_KEY: 0.6}) for s in samples]
        cfg = {"bounds": BOUNDS, "augmenter": "polynomial_cross",
               "epochs": 50, "n_ensemble": 2, "seed": 5}
        m1 = NNSurrogate(config=dict(cfg))
        m2 = NNSurrogate(config=dict(cfg))
        m1.fit(samples)
        m2.fit(tagged)
        assert np.array_equal(m1._models[0].w1, m2._models[0].w1)
        p1 = [m1.predict({"x1": v / 10, "x2": 0.4})["cost"]
              for v in range(5)]
        p2 = [m2.predict({"x1": v / 10, "x2": 0.4})["cost"]
              for v in range(5)]
        assert p1 == p2  # repr 级逐位


# ─── 确定性钉（AGENTS 7：同锚同种子逐位复现） ────────────────────────────────


class TestDeterminism:
    def test_virtual_generation_plus_weighted_fit_bitwise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY, generate_virtual_samples

        anchors = make_anchors(3, 0.03)
        v1 = generate_virtual_samples(anchors, bounds=BOUNDS, n_blend=30,
                                      n_scale=6, seed=42)
        v2 = generate_virtual_samples(anchors, bounds=BOUNDS, n_blend=30,
                                      n_scale=6, seed=42)
        assert len(v1) == len(v2)
        for a, b in zip(v1, v2, strict=False):
            assert a["params"] == b["params"]
            assert np.array_equal(a["metrics"]["cost"], b["metrics"]["cost"])
            assert a[VIRTUAL_WEIGHT_KEY] == b[VIRTUAL_WEIGHT_KEY]
        full = anchors + v1
        w1 = factory(True)()
        w2 = factory(True)()
        w1.fit(full)
        w2.fit(full)
        assert np.array_equal(w1.models["cost"], w2.models["cost"])

    def test_nn_weighted_fit_bitwise(self):
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.nn_model import NNSurrogate

        samples = [{"params": {"x1": (i % 3) / 2, "x2": (i // 3) / 2},
                    "metrics": {"cost": 1.0 + 0.3 * i},
                    VIRTUAL_WEIGHT_KEY: 0.5 + 0.05 * i} for i in range(9)]
        cfg = {"bounds": BOUNDS, "augmenter": "polynomial_cross",
               "epochs": 60, "n_ensemble": 2, "seed": 5,
               "sample_weight_key": VIRTUAL_WEIGHT_KEY}
        m1 = NNSurrogate(config=dict(cfg))
        m2 = NNSurrogate(config=dict(cfg))
        m1.fit(samples)
        m2.fit(samples)
        assert np.array_equal(m1._models[0].w3, m2._models[0].w3)
        p1 = [m1.predict({"x1": v / 10, "x2": 0.4})["cost"]
              for v in range(5)]
        p2 = [m2.predict({"x1": v / 10, "x2": 0.4})["cost"]
              for v in range(5)]
        assert p1 == p2


# ─── loocv_rho eval_indices 折面 ─────────────────────────────────────────────


class TestLoocvEvalIndices:
    def test_eval_indices_all_equals_default(self):
        from rfauto.optimization.surrogate import loocv_rho

        rng = np.random.default_rng(23)
        samples = [{"params": {"x1": float(rng.uniform()), "x2": 0.5},
                    "metrics": {"cost": float(rng.normal())}}
                   for _ in range(8)]
        r_default = loocv_rho(samples, cost_fn, factory(False))
        r_all = loocv_rho(samples, cost_fn, factory(False),
                          eval_indices=list(range(len(samples))))
        assert r_default == r_all

    def test_eval_indices_subset_folds(self):
        from rfauto.optimization.surrogate import generate_virtual_samples

        anchors = make_anchors(3, 0.03)
        virts = generate_virtual_samples(anchors, bounds=BOUNDS,
                                         n_blend=30, seed=42)
        full = anchors + virts
        from rfauto.optimization.surrogate import loocv_rho
        r = loocv_rho(full, cost_fn, factory(True),
                      eval_indices=list(range(len(anchors))))
        assert r["ok"] and r["n_folds"] == len(anchors)

    def test_eval_indices_out_of_range_raises(self):
        from rfauto.optimization.surrogate import loocv_rho

        samples = make_anchors(3, 0.0)
        with pytest.raises(ValueError, match="越界"):
            loocv_rho(samples, cost_fn, factory(False),
                      eval_indices=[0, 1, 2, 99])

    def test_eval_indices_too_few_folds(self):
        from rfauto.optimization.surrogate import loocv_rho

        samples = make_anchors(3, 0.0)
        r = loocv_rho(samples, cost_fn, factory(False),
                      eval_indices=[0, 1, 2])
        assert r["ok"] is False and "< 4" in r["error"]


# ─── calibration_service 消费面（可选透传） ──────────────────────────────────


def _calib_recipe(tmp_path) -> object:
    recipe = {
        "model": "wilkinson_power_divider",
        "setup": {"freq_range_ghz": [2.3, 2.5]},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    import yaml
    path = tmp_path / "cal_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestCalibrationServiceConsumption:
    def test_default_path_has_no_virtual_block(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(_calib_recipe(tmp_path),
                                     sampler="fake", n_validation=0)
        assert result["ok"], result.get("errors")
        assert "virtual_augment" not in result

    def test_virtual_augment_consumption(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(_calib_recipe(tmp_path),
                                     sampler="fake", n_validation=0,
                                     virtual_augment_n=12)
        assert result["ok"], result.get("errors")
        assert result["virtual_augment"]["n_blend"] == 12
        assert result["virtual_augment"]["weight_key"] == "virtual_weight"
        # 折面只在真实锚点（L9=9 折）
        assert result["loocv"]["ok"]
        assert result["loocv"]["n_folds"] == 9
        # #144 家法：虚拟样本本体不落 samples.json（只有生成配置元数据）
        calib = tmp_path / "runs" / result["run_id"] / "calibration"
        doc = json.loads(
            (calib / "samples.json").read_text(encoding="utf-8"))
        assert len(doc["samples"]) == 9
        assert doc["virtual_augment"]["n_generated"] >= 1
        assert not any("virtual_weight" in s for s in doc["samples"])
        # surrogate.json 配置透出加权通道
        sj = json.loads(
            (calib / "surrogate.json").read_text(encoding="utf-8"))
        assert sj["config"].get("sample_weight_key") == "virtual_weight"

    def test_virtual_augment_insufficient_anchors_raises(
            self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import yaml

        from rfauto.service.calibration_service import calibrate_surrogate

        recipe = {
            "model": "wilkinson_power_divider",
            "setup": {"freq_range_ghz": [2.3, 2.5]},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
                 "value": -15},
            ],
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
            }},
        }
        path = tmp_path / "r1p.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        # 单参数 L3 设计=3 个有效锚点 ≥2 不触发；用 monkeypatch 采样器
        # 全失败形态构造 <2 锚点负例（显式 ValueError 不静默退化）
        import rfauto.service.calibration_service as cs

        def _boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(cs, "_make_sampler", lambda *a, **k: _boom)
        with pytest.raises(ValueError, match="≥2"):
            calibrate_surrogate(path, sampler="fake", n_validation=0,
                                virtual_augment_n=4)
