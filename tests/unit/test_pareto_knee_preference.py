"""OP-4（round16 §六）：knee 点双法 + R-NSGA-III 偏好排序 单元测试。

判据预声明（解析锚，#118 独立来源）：

1. 弯曲角 knee（2D 凸前沿 {(0,4),(1,2),(2,1),(4,0)}，极值点弦
   x+y=4）：到弦垂直距离 |x+y−4|/√2——(1,2)/(2,1) 同为 0.7071 最大，
   平局取最小索引 → (1, 0.7071)；3D 显式拒绝；
2. HV 贡献 knee：ref=(5,5) 下各点贡献 HV(front)−HV(front\\{i})——
   (1,2) 移除跌落 2.0 最大（独占 [1,5]×[2,5] 条带 + 独占矩形），平局
   取最小索引；单点前沿贡献=全 HV；
3. 偏好排序：参考点 (1.2,1.2) 加权切比雪夫距离——(1,2) 最近
   （超出量 max(0,1−1.2)/1, max(0,2−1.2)/1 → 0.8）... 手算序
   [(1,2),(2,1),(0,4),(4,0)]；权重非正/维数不配显式 ValueError；
4. 回归钉：既有三件套（exact_hypervolume/constrained_pareto_front/
   hv_convergence）行为不变——同文件跑一遍已知值。
"""

from __future__ import annotations

import itertools
import math

import pytest

from rfauto.optimization.pareto_tools import (
    constrained_pareto_front,
    exact_hypervolume,
    hv_convergence,
    knee_point_bending_angle,
    knee_point_hv_contribution,
    preferred_indices,
)

FRONT = [(0.0, 4.0), (1.0, 2.0), (2.0, 1.0), (4.0, 0.0)]
REF = (5.0, 5.0)


class TestKneeBendingAngle:
    def test_convex_front_known_value(self):
        idx, dist = knee_point_bending_angle(FRONT)
        assert idx == 1  # 平局 (1,2)/(2,1) 取最小索引
        assert dist == pytest.approx(math.sqrt(2) / 2, rel=1e-12)

    def test_extremes_have_zero_distance(self):
        # 端点在弦上 → 距离恒 0；反转序后 knee 仍取平局最小索引的内点
        idx, dist = knee_point_bending_angle(list(reversed(FRONT)))
        assert idx == 1  # (2,1) 在反转序中先于 (1,2)（平局取最小索引）
        assert dist == pytest.approx(math.sqrt(2) / 2, rel=1e-12)

    def test_single_point_and_collinear(self):
        assert knee_point_bending_angle([(1.0, 2.0)]) == (0, 0.0)
        # 共线前沿（无弯曲）→ 距离全 0（浮点噪声 <1e-12），取最小 f1 点
        idx, dist = knee_point_bending_angle(
            [(0.0, 4.0), (1.0, 3.0), (2.0, 2.0)])
        assert dist < 1e-12
        assert idx == 0

    def test_3d_rejected_honest(self):
        with pytest.raises(ValueError, match="2D"):
            knee_point_bending_angle([(1.0, 2.0, 3.0), (2.0, 1.0, 3.0)])

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            knee_point_bending_angle([])


class TestKneeHvContribution:
    def test_known_contribution(self):
        idx, contrib = knee_point_hv_contribution(FRONT, REF)
        assert idx == 1
        assert contrib == pytest.approx(2.0, rel=1e-12)

    def test_single_point_contribution_is_full_hv(self):
        idx, contrib = knee_point_hv_contribution([(1.0, 2.0)], REF)
        assert idx == 0
        assert contrib == pytest.approx(exact_hypervolume([(1, 2)], REF))

    def test_dominated_point_zero_contribution(self):
        pts = [(1.0, 1.0), (2.0, 2.0)]  # (2,2) 被 (1,1) 支配
        idx, contrib = knee_point_hv_contribution(pts, REF)
        assert idx == 0
        # 支配点 (2,2) 贡献=0（HV 不因移除它变化——集合运算性质直接钉）
        assert exact_hypervolume(pts, REF) == \
            exact_hypervolume([pts[0]], REF)
        # 贡献最大者=支配点 (1,1)：移除跌落 (5−1)²−(5−2)² = 7
        assert contrib == pytest.approx(7.0)

    def test_tie_takes_lowest_index(self):
        pts = [(1.0, 2.0), (2.0, 1.0)]
        idx, _ = knee_point_hv_contribution(pts, REF)
        assert idx == 0


class TestPreferredIndices:
    def test_order_near_aspiration(self):
        order = preferred_indices(FRONT, [(1.2, 1.2)])
        # (1,2) 与 (2,1) 的切比雪夫超出量同为 0.8 → 平局按输入序；
        # (0,4)/(4,0) 超出 2.8
        assert order == [1, 2, 0, 3]

    def test_two_reference_points_union(self):
        order = preferred_indices(FRONT, [(0.2, 3.8), (3.8, 0.2)])
        assert order[0] in (0, 3)

    def test_weights_change_ranking(self):
        # 权重拉大第二维 → 第二维超出量折价 → (0,4) 相对提前
        order = preferred_indices(FRONT, [(1.2, 1.2)], weights=[1.0, 10.0])
        assert order.index(0) < order.index(3)

    def test_dominating_reference_clamped_to_zero(self):
        """B-1/S3：全面优于参考点（期望内）→ 距离钳位为 0，不再负距离偏好。

        docstring 契约「只量超出期望侧，期望内全 0」——无钳位时 (1,2)/(2,1)
        得负距离被排在 (0,4)/(4,0)（同为负但更大）之前，aspiration 语义被
        背叛（过冲≠比落在期望上更近）。钳位后四点全 0，平局按输入序。
        """
        order = preferred_indices(FRONT, [(10.0, 10.0)])
        assert order == [0, 1, 2, 3]

    def test_partial_overshoot_dimension_clamped(self):
        """单维过冲钳位：ref=(3.5,3.5) 时 (0,4) 的 f1 侧超出量被钳、
        f2 侧 0.5 保留——(1,2)/(2,1) 双维全在期望内 → 0，仍最优。"""
        order = preferred_indices(FRONT, [(3.5, 3.5)])
        assert order[:2] == [1, 2]

    def test_validation(self):
        with pytest.raises(ValueError, match="非空二维"):
            preferred_indices([], [(1.0, 1.0)])
        with pytest.raises(ValueError, match="维数不一致"):
            preferred_indices(FRONT, [(1.0, 1.0, 1.0)])
        with pytest.raises(ValueError, match="weights"):
            preferred_indices(FRONT, [(1.2, 1.2)], weights=[1.0, 0.0])


class TestExistingKernelsRegress:
    """同文件回归钉：既有三件套行为不变（OP-4 追加不扰动）。"""

    def test_hv_known_value(self):
        # 矩形 [0,5]×[0,5] 内点 (1,2)：HV = (5−1)·(5−2) = 12
        assert exact_hypervolume([(1.0, 2.0)], REF) == pytest.approx(12.0)

    def test_constraint_front(self):
        objs = [(1.0, 1.0), (0.5, 3.0), (2.0, 0.5)]
        violations = [(0.0, 0.0), (0.1, 0.0), (0.0, 0.0)]
        front = constrained_pareto_front(objs, violations)
        assert front == [0, 2]  # 可行支配不可行（Deb）

    def test_hv_convergence_monotone_archive(self):
        fronts = [[(2.0, 2.0)], [(1.5, 1.5), (2.0, 2.0)],
                  [(1.0, 1.0), (1.5, 1.5), (2.0, 2.0)]]
        seq = hv_convergence(fronts, REF)
        assert all(b >= a for a, b in itertools.pairwise(seq))
