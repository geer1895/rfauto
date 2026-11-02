"""T-N16 迁移学习 champion 微调链——nn warm-start+负迁移门单测（aurora_n W2）。

验收面（席位任务书预声明）：
- ①合成两任务（同结构不同参数域）：迁移预热小样本 LOOCV ρ 显著优于从零
  （预声明门 ρ_transfer ≥ ρ_scratch+0.10）+ 负迁移域自动回退被触发
  （第二合成对刻意构造分布差，门拒→fallback=scratch 逐位等价）；
- ②确定性钉：同 seed 同权重载入两次 fit 预测逐位相等；门双臂数字复现；
- ③负例：资产缺权重/架构不匹配/成员数不匹配/格式版本不兼容/未知旋钮键/
  增广语义不一致/blob 损坏/stale——全部显式报错或显式 ok=False，不静默；
- ④既有路径零改动：无 warm_start 配置 fit_info 键面不变（{"kind",
  "n_samples"}），回归由 test_nn_surrogate 既有件守护；
- 语境组合：T-N2 sample_weight_key / T-N1 conformal / T-N6 ensemble 各一例。

判据纪律：LOOCV ρ 裁判单源 loocv_rho（#118 独立裁判）；全部数值出自
确定性内核（固定种子），同配置逐位复现。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

SEED = 42
BOUNDS_SRC = {"x1": (0.0, 1.0), "x2": (0.0, 1.0)}
BOUNDS_TGT = {"x1": (0.9, 1.7), "x2": (0.4, 1.1)}
#: 预声明门：正迁移对 warm 相对 scratch 的 ρ 增益下限
POSITIVE_GATE_MARGIN = 0.10


def _resp_source(x1: float, x2: float) -> float:
    return 1.0 * math.tanh(2.0 * (x1 - 0.5)) + 0.6 * x2 + 0.4 * x1 * x2


def _resp_pos(x1: float, x2: float) -> float:
    """正迁移目标任务：同结构、参数域平移+缩放、系数近亲。"""
    u1 = (x1 - 1.3) / 0.8
    u2 = (x2 - 0.75) / 0.35
    return 0.8 * math.tanh(2.0 * u1) + 0.75 * u2 + 0.3 * u1 * u2


def _resp_neg(x1: float, x2: float) -> float:
    """负迁移目标任务：刻意分布差——x1 方向振荡（与源单调 tanh 结构冲突）。"""
    u1 = (x1 - 1.3) / 0.8
    u2 = (x2 - 0.75) / 0.35
    return 1.6 * math.sin(4.5 * math.pi * u1) + 0.25 * u2


def _grid_samples(bounds: dict, resp, na: int, nb: int) -> list[dict]:
    (a1, b1), (a2, b2) = bounds["x1"], bounds["x2"]
    pts = []
    for i in range(na):
        for j in range(nb):
            x1 = a1 + (b1 - a1) * i / (na - 1)
            x2 = a2 + (b2 - a2) * j / (nb - 1)
            y = float(resp(x1, x2))
            pts.append({"params": {"x1": x1, "x2": x2},
                        "metrics": {"y": y}, "cost": y + 10.0})
    return pts


def _target_samples(resp, n: int = 8) -> list[dict]:
    """小样本目标集：确定性对角铺点（可复跑逐位同）。"""
    (a1, b1), (a2, b2) = BOUNDS_TGT["x1"], BOUNDS_TGT["x2"]
    pts = []
    for i in range(n):
        t = i / (n - 1)
        x1 = a1 + (b1 - a1) * (0.08 + 0.84 * t)
        x2 = a2 + (b2 - a2) * (0.92 - 0.84 * t)
        y = float(resp(x1, x2))
        pts.append({"params": {"x1": x1, "x2": x2},
                    "metrics": {"y": y}, "cost": y + 10.0})
    return pts


def _base_cfg(epochs: int = 1200) -> dict:
    return {"bounds": dict(BOUNDS_TGT), "augmenter": "polynomial_cross",
            "hidden": 16, "n_ensemble": 2, "epochs": epochs, "seed": SEED}


def _probe_points() -> list[dict]:
    (a1, b1), (a2, b2) = BOUNDS_TGT["x1"], BOUNDS_TGT["x2"]
    return [{"x1": a1 + (b1 - a1) * (0.15 + 0.7 * i / 4),
             "x2": a2 + (b2 - a2) * (0.85 - 0.7 * i / 4)} for i in range(5)]


@pytest.fixture(scope="module")
def champion(tmp_path_factory):
    """源任务 champion 资产（canonical 链：upsert_from_surrogate_loop）。"""
    from rfauto.core.objectives import MetricOp, Objective
    from rfauto.optimization.model_registry import (
        ModelRegistry,
        canonical_key,
        feature_set_fingerprint,
        upsert_from_surrogate_loop,
    )
    from rfauto.optimization.surrogate import NNSurrogate

    root = tmp_path_factory.mktemp("tn16_champion")
    reg = ModelRegistry(registry_path=root / "registry.yaml",
                        store_dir=root / "store")
    src_cfg = {"bounds": dict(BOUNDS_SRC), "augmenter": "polynomial_cross",
               "hidden": 16, "epochs": 1500, "n_ensemble": 2, "seed": SEED}
    samples = _grid_samples(BOUNDS_SRC, _resp_source, 6, 6)
    model = NNSurrogate(config=dict(src_cfg))
    model.fit(samples)
    obj = Objective(metric="y", op=MetricOp.MAX_BELOW, value=-10.0)
    up = upsert_from_surrogate_loop(
        model=model, samples=samples, bounds=BOUNDS_SRC, objectives=[obj],
        surrogate_kind="nn", surrogate_config=src_cfg,
        meta={"template_family": "tn16_test_src", "channel": "synthetic",
              "registry_path": reg.registry_path,
              "store_dir": reg.store_dir,
              "trained_run_ids": ["tn16_test_source"]})
    assert up.get("ok"), up
    key = canonical_key("tn16_test_src", "synthetic",
                        feature_set_fingerprint(["x1", "x2"]))
    return {"registry": reg, "key": key, "heldout": up["heldout"]}


def _extract(champion):
    from rfauto.optimization.model_registry import extract_nn_warm_start

    ext = extract_nn_warm_start(champion["registry"], champion["key"])
    assert ext.get("ok"), ext
    return ext


class TestTransferGain:
    """验收①：正迁移对——预热小样本 ρ 显著优于从零，门自动采纳。"""

    def test_positive_pair_gate_adopts_with_margin(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate, loocv_rho

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        # 独立裁判臂（loocv_rho 直跑，同 seed 同样本）
        rho_warm = loocv_rho(
            samples, lambda s: float(s["metrics"]["y"]),
            lambda: NNSurrogate(config={
                **_base_cfg(600),
                "warm_start": {"weights": ext["weights"], "gate": False}}))
        rho_scratch = loocv_rho(
            samples, lambda s: float(s["metrics"]["y"]),
            lambda: NNSurrogate(config=_base_cfg(600)))
        assert rho_warm["ok"] and rho_scratch["ok"]
        assert rho_warm["rho"] >= rho_scratch["rho"] + POSITIVE_GATE_MARGIN, (
            f"预热收益不足: warm={rho_warm['rho']:.4f} "
            f"scratch={rho_scratch['rho']:.4f}")

        model = NNSurrogate(config={
            **_base_cfg(),
            "warm_start": {"weights": ext["weights"], "meta": ext["meta"],
                           "fine_tune_epochs": 1200, "gate_epochs": 600}})
        info = model.fit(samples)
        assert info["n_samples"] == len(samples)
        assert info["negative_transfer"] is False
        ws = info["warm_start"]
        assert ws["adopted"] is True
        assert ws["gate_metric"] == "y"
        # 门内数字与独立裁判臂一致（同 seed 同折同轮数→逐位复现）
        assert ws["rho_transfer"] == pytest.approx(rho_warm["rho"])
        assert ws["rho_scratch"] == pytest.approx(rho_scratch["rho"])
        assert ws["margin"] >= POSITIVE_GATE_MARGIN

    def test_transfer_model_differs_from_scratch(self, champion):
        """采纳迁移后模型确实被权重改变（不是静默回退的假阳性）。"""
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        warm = NNSurrogate(config={
            **_base_cfg(400),
            "warm_start": {"weights": ext["weights"], "gate": False,
                           "fine_tune_epochs": 400}})
        warm.fit(samples)
        scratch = NNSurrogate(config=_base_cfg(400))
        scratch.fit(samples)
        preds_differ = any(
            warm.predict(p) != scratch.predict(p) for p in _probe_points())
        assert preds_differ


class TestNegativeTransferGate:
    """验收①负支+③：刻意分布差——门拒绝、自动回退、回退=从零逐位。"""

    def test_negative_pair_gate_rejects_and_falls_back(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_neg)
        model = NNSurrogate(config={
            **_base_cfg(),
            "warm_start": {"weights": ext["weights"], "meta": ext["meta"],
                           "fine_tune_epochs": 1200, "gate_epochs": 600}})
        info = model.fit(samples)
        ws = info["warm_start"]
        assert ws["adopted"] is False
        assert ws["fallback"] == "scratch"
        assert info["negative_transfer"] is True
        assert ws["rho_transfer"] < ws["rho_scratch"]
        assert ws["gate_metric"] == "y"

        # 回退等价钉：门拒后的最终模型与纯从零拟合（同 seed 同轮数）逐位同
        scratch = NNSurrogate(config=_base_cfg())
        scratch.fit(samples)
        for p in _probe_points():
            assert model.predict(p) == scratch.predict(p)

    def test_gate_loocv_unavailable_falls_back(self, champion):
        """LOOCV 不可跑（有效样本 <4）= 不可证实收益 → 拒绝采信回退从零。"""
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos, n=3)
        model2 = NNSurrogate(config={
            **_base_cfg(200),
            "warm_start": {"weights": ext["weights"],
                           "fine_tune_epochs": 200}})
        info = model2.fit(samples)
        assert info["negative_transfer"] is True
        assert info["warm_start"]["adopted"] is False
        assert info["warm_start"]["reason"] == "gate_loocv_unavailable"

    def test_gate_off_blind_transfer(self, champion):
        """gate=False 盲迁移：跳过门直接采纳（调用方自担），info 带键面。"""
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_neg)
        model = NNSurrogate(config={
            **_base_cfg(200),
            "warm_start": {"weights": ext["weights"], "gate": False,
                           "fine_tune_epochs": 200}})
        info = model.fit(samples)
        assert info["warm_start"] == {"adopted": True, "gate": False}
        assert "negative_transfer" not in info


class TestDeterminism:
    """验收②：同 seed 权重载入+训练逐位。"""

    def test_warm_fit_bitwise_reproducible(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        cfg = {**_base_cfg(300),
               "warm_start": {"weights": ext["weights"],
                              "meta": ext["meta"], "gate": False,
                              "fine_tune_epochs": 300}}
        p1 = NNSurrogate(config=dict(cfg))
        p1.fit(samples)
        p2 = NNSurrogate(config=dict(cfg))
        p2.fit(samples)
        for p in _probe_points():
            assert p1.predict(p) == p2.predict(p)
            assert p1.uncertainty(p) == p2.uncertainty(p)

    def test_gate_numbers_reproducible(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        cfg = {**_base_cfg(),
               "warm_start": {"weights": ext["weights"],
                              "fine_tune_epochs": 1200,
                              "gate_epochs": 600}}
        i1 = NNSurrogate(config=dict(cfg)).fit(samples)
        i2 = NNSurrogate(config=dict(cfg)).fit(samples)
        assert i1["warm_start"] == i2["warm_start"]
        assert i1["negative_transfer"] == i2["negative_transfer"]


class TestNegativeCases:
    """验收③：缺权重/架构不匹配/版本/成员数/未知键/增广语义/blob/stale。"""

    def test_asset_without_weights(self, tmp_path):
        from rfauto.optimization.model_registry import (
            ModelRegistry,
            canonical_key,
            extract_nn_warm_start,
            feature_set_fingerprint,
        )
        from rfauto.optimization.surrogate import PolyRidgeSurrogate

        reg = ModelRegistry(registry_path=tmp_path / "r.yaml",
                            store_dir=tmp_path / "s")
        pr = PolyRidgeSurrogate(config={"bounds": dict(BOUNDS_SRC)})
        pr.fit([{"params": {"x1": 0.1, "x2": 0.2}, "metrics": {"y": 1.0}},
                {"params": {"x1": 0.5, "x2": 0.4}, "metrics": {"y": 0.6}},
                {"params": {"x1": 0.9, "x2": 0.8}, "metrics": {"y": 0.2}},
                {"params": {"x1": 0.3, "x2": 0.9}, "metrics": {"y": 0.8}}])
        key = canonical_key("fam", "ch",
                            feature_set_fingerprint(["x1", "x2"]))
        reg.upsert(key=key, model=pr,
                   heldout={"metric": "linf", "value": 0.5, "n_points": 1})
        out = extract_nn_warm_start(reg, key)
        assert out["ok"] is False
        assert out["reason"] == "asset_has_no_weights"

    def test_no_champion_and_stale(self, tmp_path):
        from rfauto.optimization.model_registry import (
            ModelRegistry,
            canonical_key,
            extract_nn_warm_start,
            feature_set_fingerprint,
        )
        from rfauto.optimization.surrogate import NNSurrogate

        reg = ModelRegistry(registry_path=tmp_path / "r.yaml",
                            store_dir=tmp_path / "s")
        key = canonical_key("fam", "ch",
                            feature_set_fingerprint(["x1", "x2"]))
        out = extract_nn_warm_start(reg, key)
        assert out["ok"] is False and out["reason"] == "no_champion"

        model = NNSurrogate(config={"bounds": dict(BOUNDS_SRC), "epochs": 10,
                                    "n_ensemble": 1, "seed": SEED})
        model.fit([{"params": {"x1": 0.1, "x2": 0.2}, "metrics": {"y": 1.0}},
                   {"params": {"x1": 0.5, "x2": 0.4}, "metrics": {"y": 0.6}},
                   {"params": {"x1": 0.9, "x2": 0.8}, "metrics": {"y": 0.2}},
                   {"params": {"x1": 0.3, "x2": 0.9}, "metrics": {"y": 0.8}}])
        reg.upsert(key=key, model=model,
                   heldout={"metric": "linf", "value": 0.1, "n_points": 1})
        reg.mark_family_stale("fam", "anchor_drifted")
        out = extract_nn_warm_start(reg, key)
        assert out["ok"] is False and out["reason"] == "stale"

    def test_corrupt_blob(self, tmp_path):
        from rfauto.optimization.model_registry import (
            ModelRegistry,
            canonical_key,
            extract_nn_warm_start,
            feature_set_fingerprint,
        )
        from rfauto.optimization.surrogate import NNSurrogate

        reg = ModelRegistry(registry_path=tmp_path / "r.yaml",
                            store_dir=tmp_path / "s")
        model = NNSurrogate(config={"bounds": dict(BOUNDS_SRC), "epochs": 10,
                                    "n_ensemble": 1, "seed": SEED})
        model.fit([{"params": {"x1": 0.1, "x2": 0.2}, "metrics": {"y": 1.0}},
                   {"params": {"x1": 0.5, "x2": 0.4}, "metrics": {"y": 0.6}},
                   {"params": {"x1": 0.9, "x2": 0.8}, "metrics": {"y": 0.2}},
                   {"params": {"x1": 0.3, "x2": 0.9}, "metrics": {"y": 0.8}}])
        key = canonical_key("fam", "ch",
                            feature_set_fingerprint(["x1", "x2"]))
        reg.upsert(key=key, model=model,
                   heldout={"metric": "linf", "value": 0.1, "n_points": 1})
        champ = reg.champion(key)
        blob = Path(str(champ["entry"]["blob_path"]))
        if not blob.exists():
            blob = reg.store_dir / \
                f"{champ['entry']['model_blob_sha256']}.pkl"
        blob.write_bytes(blob.read_bytes() + b"x")
        out = extract_nn_warm_start(reg, key)
        assert out["ok"] is False
        assert out["reason"] == "blob_sha256_mismatch"

    def test_architecture_mismatch_raises(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        with pytest.raises(ValueError, match="架构不匹配"):
            NNSurrogate(config={
                **_base_cfg(5), "hidden": 8,
                "warm_start": {"weights": ext["weights"], "gate": False}}).fit(
                    samples)

    def test_member_count_mismatch_raises(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        with pytest.raises(ValueError, match="成员数"):
            NNSurrogate(config={
                **_base_cfg(5), "n_ensemble": 3,
                "warm_start": {"weights": ext["weights"]}})

    def test_format_version_raises(self):
        from rfauto.optimization.surrogate import NNSurrogate

        with pytest.raises(ValueError, match="格式版本"):
            NNSurrogate(config={
                "bounds": dict(BOUNDS_TGT), "n_ensemble": 2,
                "warm_start": {"weights": [{"format_version": 999}]}})

    def test_unknown_knob_raises(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        with pytest.raises(ValueError, match="未知键"):
            NNSurrogate(config={
                **_base_cfg(5),
                "warm_start": {"weights": ext["weights"],
                               "fine_tune_epocs": 100}})  # 拼错旋钮

    def test_augmenter_mismatch_extract_face(self, champion):
        from rfauto.optimization.model_registry import extract_nn_warm_start

        out = extract_nn_warm_start(champion["registry"], champion["key"],
                                    expected_augmenter="wilkinson_rf")
        assert out["ok"] is False
        assert out["reason"] == "augmenter_mismatch"

    def test_augmenter_mismatch_fit_face(self, champion):
        """fit 期 meta 通道终校验：特征面不同构（3 参数目标）显式报错。"""
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = [{"params": {"x1": 1.0, "x2": 0.5, "x3": 0.3},
                    "metrics": {"y": 1.0}},
                   {"params": {"x1": 1.2, "x2": 0.7, "x3": 0.5},
                    "metrics": {"y": 0.6}},
                   {"params": {"x1": 1.4, "x2": 0.9, "x3": 0.7},
                    "metrics": {"y": 0.2}},
                   {"params": {"x1": 1.6, "x2": 1.0, "x3": 0.9},
                    "metrics": {"y": 0.8}}]
        with pytest.raises(ValueError, match="feature_names_mismatch"):
            NNSurrogate(config={
                "bounds": {"x1": (0.9, 1.7), "x2": (0.4, 1.1),
                           "x3": (0.0, 1.0)},
                "augmenter": "polynomial_cross", "hidden": 16,
                "n_ensemble": 2, "epochs": 5, "seed": SEED,
                "warm_start": {"weights": ext["weights"], "gate": False,
                               "meta": ext["meta"]}}).fit(samples)


class TestDefaultEquivalence:
    """验收④：既有路径零改动——无 warm_start 配置 fit_info 键面不变。"""

    def test_no_warm_start_info_keys_unchanged(self):
        from rfauto.optimization.surrogate import NNSurrogate

        model = NNSurrogate(config=_base_cfg(50))
        info = model.fit(_target_samples(_resp_pos))
        assert set(info.keys()) == {"kind", "n_samples"}
        assert info["kind"] == "nn"


class TestComposition:
    """语境组合：T-N2 sample_weight_key / T-N1 conformal / T-N6 ensemble。"""

    def test_tn2_sample_weight_key_with_warm(self, champion):
        from rfauto.optimization.surrogate import NNSurrogate

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        for i, s in enumerate(samples):
            s["w"] = 0.5 + 0.1 * (i % 5)
        model = NNSurrogate(config={
            **_base_cfg(200), "sample_weight_key": "w",
            "warm_start": {"weights": ext["weights"], "gate": False,
                           "fine_tune_epochs": 200}})
        info = model.fit(samples)
        assert info["warm_start"]["adopted"] is True
        pred = model.predict({"x1": 1.2, "x2": 0.7})
        assert math.isfinite(pred["y"])

    def test_tn1_conformal_wraps_warm_nn(self, champion):
        from rfauto.optimization.surrogate import surrogate_registry

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        model = surrogate_registry.create("conformal", config={
            "base_kind": "nn",
            "base_config": {**_base_cfg(200),
                            "warm_start": {"weights": ext["weights"],
                                           "gate": False,
                                           "fine_tune_epochs": 200}},
            "alpha": 0.2, "cal_ratio": 0.5, "seed": 3})
        info = model.fit(samples)
        assert info["n_samples"] == len(samples)
        iv = model.predict_interval({"x1": 1.2, "x2": 0.7})
        lo, hi = iv["y"]
        assert lo <= hi

    def test_tn6_ensemble_with_warm_nn_member(self, champion):
        from rfauto.optimization.surrogate import surrogate_registry

        ext = _extract(champion)
        samples = _target_samples(_resp_pos)
        model = surrogate_registry.create("ensemble", config={
            "bounds": dict(BOUNDS_TGT),
            "members": ["poly_ridge",
                        {"kind": "nn", "config": {
                            **_base_cfg(150),
                            "warm_start": {"weights": ext["weights"],
                                           "gate": False,
                                           "fine_tune_epochs": 150}}}],
            "rho_metric": "y"})
        info = model.fit(samples)
        statuses = [m["status"] for m in info["members"]]
        assert "active" in statuses
        pred = model.predict({"x1": 1.2, "x2": 0.7})
        assert math.isfinite(pred["y"])


class TestWeightKernels:
    """mlp_state/mlp_load_state 与增广判据的单元面。"""

    def test_state_roundtrip_bitwise_and_adam_reset(self):
        from rfauto.optimization.surrogate.nn_model import (
            _MLP,
            WARM_STATE_FORMAT_VERSION,
            mlp_load_state,
            mlp_state,
        )

        net = _MLP(3, 1, 16, SEED)
        for _ in range(3):
            net.adam_step(np.zeros((2, 3)), np.zeros((2, 1)), 1e-3, 5e-3)
        assert net._t == 3
        state = mlp_state(net)
        assert state["format_version"] == WARM_STATE_FORMAT_VERSION
        fresh = _MLP(3, 1, 16, SEED + 1)  # 不同初始化
        mlp_load_state(fresh, state)
        for key in ("w1", "b1", "w2", "b2", "w3", "b3"):
            assert (getattr(fresh, key) == getattr(net, key)).all()
            assert getattr(fresh, key) is not getattr(net, key)
        # Adam 动量清零（微调=新优化器轨迹）
        assert fresh._t == 0
        assert all((m == 0).all() for m in fresh._m)
        assert all((v == 0).all() for v in fresh._v)
        # _params 别名有效（原位覆盖）：载入后训练步数推进且权重变化
        x = np.ones((2, 3))
        y = np.ones((2, 1))
        w_before = fresh.w3.copy()
        fresh.adam_step(x, y, 1e-3, 5e-3)
        assert fresh._t == 1
        assert not (fresh.w3 == w_before).all()

    def test_load_state_shape_mismatch(self):
        import numpy as np

        from rfauto.optimization.surrogate.nn_model import (
            _MLP,
            mlp_load_state,
            mlp_state,
        )

        state = mlp_state(_MLP(3, 1, 16, SEED))
        with pytest.raises(ValueError, match="架构不匹配"):
            mlp_load_state(_MLP(3, 1, 8, SEED), state)
        bad = dict(state)
        bad["w1"] = np.zeros((4, 16))
        with pytest.raises(ValueError, match="架构不匹配"):
            mlp_load_state(_MLP(3, 1, 16, SEED), bad)
        with pytest.raises(ValueError, match="缺键"):
            mlp_load_state(_MLP(3, 1, 16, SEED),
                           {"format_version": 1, "w1": state["w1"]})

    def test_augmenter_transfer_verdict(self):
        from rfauto.optimization.surrogate.nn_model import (
            augmenter_transfer_verdict,
        )

        names = ["x1", "x2", "cross__x1__x2"]
        assert augmenter_transfer_verdict(
            "polynomial_cross", names, "polynomial_cross", names)["ok"]
        out = augmenter_transfer_verdict(
            "wilkinson_rf", names, "polynomial_cross", names)
        assert not out["ok"] and out["reason"] == "augmenter_mismatch"
        out = augmenter_transfer_verdict(
            "polynomial_cross", ["x1", "x2"], "polynomial_cross", names)
        assert not out["ok"] and out["reason"] == "feature_names_mismatch"
        # 两端信息皆缺（手工权重直灌）不判——形状门兜底
        assert augmenter_transfer_verdict(None, None, "polynomial_cross",
                                          names)["ok"]
