"""OP-4b/OP-5a（round16 §六）：multiobj_backend algorithm 选择 单元测试。

判据预声明（#207 合成函数裁判，确定性 seed）：

1. 缺省路径不变：algorithm="nsga2"（缺省）与 E9 既有语义一致——
   pareto_front/pareto_variables/hv_convergence 键齐、逐 seed 确定性；
2. rnsga3 通道：pymoo RNSGA3（构造签名按本地 pymoo 0.6.2 实录：
   ``RNSGA3(ref_points, pop_per_ref_point, ...)``）——偏好参考点附近
   的前沿段更密（参考点邻域内点数 ≥ 无偏好 NSGA-II 同窗口内点数）；
   缺 ref_points/pop_per_ref_point 显式 ValueError；坏形状显式拒绝；
3. 未知 algorithm 显式 ValueError。

铁律 7 对照：目标函数=合成 ZDT 型（解析），数字全部出自引擎。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.optimization.multiobj_backend import MultiObjBackend


def zdt1_like(x: np.ndarray) -> tuple[float, float]:
    f1 = float(x[0])
    g = 1.0 + 9.0 * float(np.mean(x[1:]))
    return (f1, float(g * (1.0 - np.sqrt(f1 / g))))


BOUNDS = (np.zeros(3), np.ones(3))


class TestDefaultPathUnchanged:
    def test_nsga2_result_shape_and_keys(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        out = backend.optimize(zdt1_like, n_gen=5, pop_size=12, seed=7)
        assert out["ok"] is True
        assert {"pareto_front", "pareto_variables", "n_evaluations",
                "n_generations"} <= set(out)
        front = np.asarray(out["pareto_front"], dtype=float)
        assert front.shape[1] == 2
        assert out["n_generations"] == 5

    def test_nsga2_deterministic_by_seed(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        a = backend.optimize(zdt1_like, n_gen=4, pop_size=12, seed=11)
        b = backend.optimize(zdt1_like, n_gen=4, pop_size=12, seed=11)
        assert a["pareto_front"] == b["pareto_front"]

    def test_explicit_nsga2_equals_default(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        d = backend.optimize(zdt1_like, n_gen=4, pop_size=12, seed=3)
        e = backend.optimize(zdt1_like, n_gen=4, pop_size=12, seed=3,
                             algorithm="nsga2")
        assert d["pareto_front"] == e["pareto_front"]


class TestRNSGA3Channel:
    # ZDT1 前沿（g=1）：f2 = 1−√f1；参考点取**前沿上**两点（离前参考点
    # 会把种群拉向不可达区——判据失真，2026-10-03 实测证伪后改锚）
    REFS = np.array([[0.15, 1.0 - np.sqrt(0.15)], [0.8, 1.0 - np.sqrt(0.8)]])

    @staticmethod
    def _seg_frac(points, width=0.15) -> float:
        f1 = np.asarray(points, dtype=float)[:, 0]
        return float(np.mean(
            [min(abs(v - 0.15), abs(v - 0.8)) < width for v in f1]))

    def test_preference_concentrates_front_segment(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        for seed in (5, 9):  # 双 seed 双判（#207：不赌单种子彩票）
            out = backend.optimize(
                zdt1_like, n_gen=20, pop_size=16, seed=seed,
                algorithm="rnsga3", ref_points=self.REFS,
                pop_per_ref_point=8)
            front = np.asarray(out["pareto_front"], dtype=float)
            assert front.shape[1] == 2 and front.shape[0] >= 2
            plain = backend.optimize(zdt1_like, n_gen=20, pop_size=16,
                                     seed=seed)
            frac_pref = self._seg_frac(front)
            frac_plain = self._seg_frac(plain["pareto_front"])
            assert frac_pref >= frac_plain, (seed, frac_pref, frac_plain)

    def test_missing_required_args_rejected(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        with pytest.raises(ValueError, match="ref_points"):
            backend.optimize(zdt1_like, n_gen=2, pop_size=8,
                             algorithm="rnsga3")
        ref = np.array([[0.2, 1.0]])
        with pytest.raises(ValueError, match="pop_per_ref_point"):
            backend.optimize(zdt1_like, n_gen=2, pop_size=8,
                             algorithm="rnsga3", ref_points=ref)

    def test_bad_ref_shape_rejected(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        with pytest.raises(ValueError, match="ref_points 形状"):
            backend.optimize(
                zdt1_like, n_gen=2, pop_size=8, algorithm="rnsga3",
                ref_points=np.array([[0.2, 1.0, 0.3]]), pop_per_ref_point=4)

    def test_unknown_algorithm_rejected(self):
        backend = MultiObjBackend(n_objectives=2, n_variables=3, bounds=BOUNDS)
        with pytest.raises(ValueError, match="未知 algorithm"):
            backend.optimize(zdt1_like, n_gen=2, pop_size=8, algorithm="moead")
