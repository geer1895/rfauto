"""AI-2（round14 §三）：几何输入 GNN 代理插件（小图合成验证面）单元测试。

判据预声明（#207 合成裁判，机制级——冻结 seed，2026-10-03 本机实测）：

合成目标 = "孤立像素得分" score(P) = mean(occ·(1−邻域占用率))——
只依赖**局部邻域形态**，纯全局计数特征（1 阶多态回归基线）不可分
（本机实测基线 ρ≈−0.04）；GNN 消息传递（邻域聚合+交互池化）应
显著可分：6×6 图、130 样本、100 训练/30 测试，seed=7：
ρ_gnn ≥ 0.9（实测 0.9997）、且 ρ_gnn > ρ_baseline。

其余钉：注册表键 gnn_geom；fit/predict/uncertainty 契约（形状/键集/
忽略缺指标样本）；确定性（同参同输出）；config 校验（grid_shape/
n_rounds/hidden_dim/ridge_lam 非法值显式拒绝）；pyg 通道=接口位
（缺席显式报错指路 extras，不静默退化）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.gnn_geom import (
    GnnGeomSurrogate,
    pyg_available,
    require_pyg,
)
from rfauto.optimization.surrogate.poly_ridge import PolyRidgeSurrogate

GRID = 6
N_PARAMS = GRID * GRID


def _neighborhood_score(occ: np.ndarray) -> float:
    """孤立像素得分（合成裁判真值核；局部邻域形态函数）。"""
    occ2 = occ.reshape(GRID, GRID)
    nb = np.zeros((GRID, GRID))
    for r in range(GRID):
        for c in range(GRID):
            acc = []
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < GRID and 0 <= cc < GRID:
                    acc.append(occ2[rr, cc])
            nb[r, c] = float(np.mean(acc)) if acc else 0.0
    return float(np.mean(occ2 * (1.0 - nb)))


@pytest.fixture(scope="module")
def dataset():
    rng = np.random.default_rng(5)
    samples = []
    for _ in range(130):
        occ = (rng.random(N_PARAMS) < 0.45).astype(float)
        params = {f"p{j}": float(occ[j]) for j in range(N_PARAMS)}
        samples.append({"params": params,
                        "metrics": {"score": _neighborhood_score(occ)}})
    return samples


@pytest.fixture(scope="module")
def trained(dataset):
    model = GnnGeomSurrogate(config=dict(
        grid_shape=[GRID, GRID], n_rounds=2, hidden_dim=8, seed=7,
        ridge_lam=1e-4))
    model.fit(dataset[:100])
    return model


def _rho(a, b) -> float:
    return float(np.corrcoef(np.asarray(a), np.asarray(b))[0, 1])


class TestRegistrationAndContract:
    def test_registered(self):
        assert "gnn_geom" in surrogate_registry.available()
        # 工厂 kwargs 透传路径
        m = surrogate_registry.create("gnn_geom", config={"grid_shape": [2, 2]})
        assert isinstance(m, GnnGeomSurrogate)

    def test_fit_info_and_predict_shapes(self, dataset, trained):
        pred = trained.predict(dataset[101]["params"])
        assert set(pred) == {"score"}
        assert np.isfinite(pred["score"])
        unc = trained.uncertainty(dataset[101]["params"])
        assert unc["score"] >= 0.0

    def test_ignores_samples_with_missing_metrics(self, dataset):
        poisoned = [
            *dataset[:20],
            {"params": dataset[0]["params"], "metrics": {"score": None}},
            {"params": dataset[1]["params"], "metrics": {}},
        ]
        model = GnnGeomSurrogate(config=dict(grid_shape=[GRID, GRID]))
        info = model.fit(poisoned)
        assert info["n_samples"] == 20

    def test_deterministic(self, dataset):
        a = GnnGeomSurrogate(config=dict(grid_shape=[GRID, GRID], seed=7))
        b = GnnGeomSurrogate(config=dict(grid_shape=[GRID, GRID], seed=7))
        a.fit(dataset[:50])
        b.fit(dataset[:50])
        for s in dataset[50:60]:
            assert a.predict(s["params"]) == b.predict(s["params"])


class TestSyntheticJudge:
    def test_gnn_beats_count_baseline_on_neighborhood_target(
            self, dataset, trained):
        baseline = PolyRidgeSurrogate(config=dict(
            bounds={f"p{j}": (0.0, 1.0) for j in range(N_PARAMS)}, degree=1))
        baseline.fit(dataset[:100])
        test = dataset[100:]
        truth = [s["metrics"]["score"] for s in test]
        rho_gnn = _rho([trained.predict(s["params"])["score"] for s in test],
                       truth)
        rho_base = _rho(
            [baseline.predict(s["params"])["score"] for s in test], truth)
        assert rho_gnn >= 0.9
        assert rho_gnn > rho_base


class TestConfigValidation:
    def test_missing_grid_shape(self):
        with pytest.raises(ValueError, match="grid_shape"):
            GnnGeomSurrogate(config={}).fit(
                [{"params": {f"p{j}": 0.0 for j in range(4)},
                  "metrics": {"s": 0.0}} for _ in range(5)])

    def test_param_key_count_mismatch(self):
        model = GnnGeomSurrogate(config=dict(grid_shape=[2, 2]))
        with pytest.raises(ValueError, match="未知键"):
            model.fit([{"params": {f"q{j}": 0.0 for j in range(3)},
                        "metrics": {"s": 0.0}} for _ in range(5)])

    @pytest.mark.parametrize("cfg", [
        {"grid_shape": [6, 6], "n_rounds": 0},
        {"grid_shape": [6, 6], "hidden_dim": 0},
        {"grid_shape": [6, 6], "ridge_lam": 0.0},
    ])
    def test_bad_hyperparams_rejected(self, dataset, cfg):
        model = GnnGeomSurrogate(config=cfg)
        with pytest.raises(ValueError):
            model.fit(dataset[:10])


class TestPygChannel:
    def test_probe_function(self):
        # 本机无 torch_geometric：探测位如实 False；不真正 import
        assert isinstance(pyg_available(), bool)

    def test_require_pyg_absent_reports_extras(self):
        if pyg_available():
            pytest.skip("torch_geometric 已安装（跳过缺席报错钉）")
        with pytest.raises(RuntimeError, match="rfauto\\[gnn\\]"):
            require_pyg("pyg")
        # 非 pyg backend 不触发
        require_pyg("numpy")
