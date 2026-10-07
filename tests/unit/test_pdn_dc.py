"""DR-6 core/pdn_dc.py 单测（规格 §C-5 验收锚，先写后跑 #122）。

锚面（规格原文逐条）：
① 对边注入矩形板 R = L/(σtW)：整边 Dirichlet + 面宽加权均匀汇点下线性场
   **逐节点精确满足离散方程**（模块 docstring 可证），解算 R 达机器精度
   （≪规格 1% 门），网格无关 + Richardson 外推互证同值；
② 制造解二次 φ：A·φ_quad 作注人向量、边界钳 φ_quad 值，解算逐节点回收
   <1e-10（规格门；实测 ~1e-14/1e-15），splu 与 Jacobi-CG 双路都过；
③ 串并联手算：R(L1+L2) = R(L1)+R(L2)（同电流串联）、2·R(2W) = R(W)
   （同压并联），全部对 L/(σtW) 闭式；
④ 真二维焊区对：网格自收敛 <1%（规格门）+ Richardson 外推改善互证
   （焊区角部场奇异 → 逐点一阶收敛，外推 2f−c 如实按一阶口径判读）；
⑤ 守卫：空钳压/汇点出板/汇点落钳压节点/求解器名非法/CG 残差门。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.pdn_dc import (
    CG_REL_RESIDUAL_TOL,
    DcSink,
    assemble_plate_matrix,
    dc_ir_drop,
    edge_sinks,
    plate_resistance_1d,
    solve_dc_network,
)

L, W, TH, SIG = 10e-3, 5e-3, 35e-6, 5.8e7
V_VRM = 1.0
I_DRAW = 2.0


def _r_opposite_edge(n: int, *, solver: str = "auto") -> tuple[float, object]:
    """整左边缘钳压 + 整右边缘面宽加权均匀汇点 → (R, result)。"""
    res = dc_ir_drop(
        L, W, TH, SIG, V_VRM,
        (0.0, 0.0, 0.0, W),
        edge_sinks("right", L, W, n, I_DRAW),
        n, n, solver=solver,
    )
    assert res.r_eff_ohm is not None
    return res.r_eff_ohm, res


# ─── 锚 ①：对边注入 R = L/(σtW)，机器精度 + Richardson 互证 ─────────────────


class TestOppositeEdgeAnchor:
    def test_resistance_machine_precision_multi_grid(self) -> None:
        """规格门 <1%；本构造离散精确，实测 ~1e-9（线性解算条件数地板）。"""
        r_hand = plate_resistance_1d(L, W, TH, SIG)
        assert r_hand == L / (SIG * TH * W)  # 闭式逐位
        for n in (21, 41, 81):
            r, res = _r_opposite_edge(n)
            assert abs(r / r_hand - 1.0) < 1e-8, (n, r, r_hand)
            assert res.rel_residual < 1e-12
            assert res.solver == "splu"  # n² ≤ 6561 ≪ 2e5 → auto=splu
            assert res.n_fixed == n  # 整左边缘 = n 个钳压节点

    def test_field_is_exactly_linear(self) -> None:
        """线性场 φ(x)=V0−I·x/(σtW) 逐节点回收（离散精确性的构造证明）。"""
        n = 41
        _, res = _r_opposite_edge(n)
        phi_lin = V_VRM - I_DRAW * res.x_m[:, None] / (SIG * TH * W)
        assert np.abs(res.phi - phi_lin).max() < 1e-10

    def test_richardson_cross_check(self) -> None:
        """Richardson 互证：离散精确 → 粗/细两档同值，外推逐位不动。"""
        from rfauto.core.quasistatic_fd import richardson_first_order

        r_coarse, _ = _r_opposite_edge(21)
        r_fine, _ = _r_opposite_edge(41)
        r_ext = richardson_first_order(r_coarse, r_fine)
        assert abs(r_ext / r_fine - 1.0) < 1e-8
        # 网格收敛 <1%（规格门）：粗细两档之差相对值
        assert abs(r_fine / r_coarse - 1.0) < 1e-8


# ─── 锚 ②：制造解二次 φ 逐节点 <1e-10 ────────────────────────────────────────


class TestManufacturedSolution:
    def _quadratic_case(self) -> tuple[object, np.ndarray, dict[int, float], np.ndarray]:
        nx = ny = 15
        a = assemble_plate_matrix(1.0, 1.0, TH, SIG, nx, ny)
        xs = np.linspace(0.0, 1.0, nx)
        ys = np.linspace(0.0, 1.0, ny)
        grid_x, grid_y = np.meshgrid(xs, ys, indexing="ij")
        phi_true = (0.3 + 0.7 * grid_x - 0.2 * grid_y + 1.1 * grid_x**2
                    - 0.4 * grid_x * grid_y + 0.9 * grid_y**2)
        fixed: dict[int, float] = {}
        for i in range(nx):
            fixed[i * ny] = float(phi_true[i, 0])
            fixed[i * ny + ny - 1] = float(phi_true[i, ny - 1])
        for j in range(ny):
            fixed[j] = float(phi_true[0, j])
            fixed[(nx - 1) * ny + j] = float(phi_true[nx - 1, j])
        b = a @ phi_true.ravel()
        return a, phi_true.ravel(), fixed, b

    def test_splu_per_node_below_1e_10(self) -> None:
        a, phi_true, fixed, b = self._quadratic_case()
        phi, rel_res, used = solve_dc_network(a, fixed, b, solver="splu")
        assert used == "splu"
        assert rel_res < 1e-12
        assert np.abs(phi - phi_true).max() < 1e-10  # 规格门

    def test_cg_per_node_below_1e_10_and_residual_gate(self) -> None:
        a, phi_true, fixed, b = self._quadratic_case()
        phi, rel_res, used = solve_dc_network(a, fixed, b, solver="cg")
        assert used == "cg"
        assert rel_res <= CG_REL_RESIDUAL_TOL  # 规格：残差 1e-12
        assert np.abs(phi - phi_true).max() < 1e-10


# ─── 锚 ③：串并联手算 ────────────────────────────────────────────────────────


class TestSeriesParallelHandCalc:
    def test_series_length_adds(self) -> None:
        """R(L1+L2) = R(L1) + R(L2)（同电流串联，各段全部对闭式）。"""
        l1, l2 = 6e-3, 4e-3
        r1, _ = self._r_plate(l1)
        r2, _ = self._r_plate(l2)
        r12, _ = self._r_plate(l1 + l2)
        r_hand1 = l1 / (SIG * TH * W)
        r_hand2 = l2 / (SIG * TH * W)
        assert abs(r1 / r_hand1 - 1.0) < 1e-9
        assert abs(r2 / r_hand2 - 1.0) < 1e-9
        assert abs(r12 / (r_hand1 + r_hand2) - 1.0) < 1e-9
        assert abs(r12 / (r1 + r2) - 1.0) < 1e-9

    def test_parallel_width_halves(self) -> None:
        """2·R(L,2W) = R(L,W)（同压并联=宽度加倍，各对闭式）。"""
        r_w, _ = self._r_plate(L, width=W)
        r_2w, _ = self._r_plate(L, width=2 * W, width_nodes=81)
        assert abs(r_w / (L / (SIG * TH * W)) - 1.0) < 1e-9
        assert abs(r_2w / (L / (SIG * TH * 2 * W)) - 1.0) < 1e-9
        assert abs(2.0 * r_2w / r_w - 1.0) < 1e-9

    def _r_plate(self, length: float, *, width: float = W,
                 width_nodes: int = 41) -> tuple[float, object]:
        res = dc_ir_drop(
            length, width, TH, SIG, V_VRM,
            (0.0, 0.0, 0.0, width),
            edge_sinks("right", length, width, width_nodes, I_DRAW),
            41, width_nodes,
        )
        assert res.r_eff_ohm is not None
        return res.r_eff_ohm, res


# ─── 锚 ④：真二维焊区对，网格自收敛 <1% + Richardson 互证 ────────────────────


class TestPadPair2D:
    def test_self_convergence_and_richardson(self) -> None:
        vrm_pad = (0.0, 4.5e-3, 1.0e-3, 5.5e-3)
        sink_pad = (9.0e-3, 4.5e-3, 10.0e-3, 5.5e-3)

        def solve(n: int) -> float:
            res = dc_ir_drop(L, L, TH, SIG, V_VRM, vrm_pad,
                             self._pad_sinks(n, sink_pad), n, n)
            assert res.r_eff_ohm is not None
            return res.r_eff_ohm

        r_coarse = solve(81)
        r_fine = solve(161)
        assert abs(r_fine / r_coarse - 1.0) < 0.01  # 规格门：网格收敛 <1%
        r_ext = 2.0 * r_fine - r_coarse
        # 焊区角部场奇异 → 逐点一阶收敛：外推改变量 ≤ 粗细差（不夸口二阶）
        assert abs(r_ext - r_fine) <= abs(r_fine - r_coarse)

    @staticmethod
    def _pad_sinks(n: int, pad: tuple[float, float, float, float]) -> tuple[DcSink, ...]:
        dx = dy = L / (n - 1)
        i0, i1 = round(pad[0] / dx), round(pad[2] / dx)
        j0, j1 = round(pad[1] / dy), round(pad[3] / dy)
        per = I_DRAW / ((i1 - i0 + 1) * (j1 - j0 + 1))
        return tuple(
            DcSink(i * dx, j * dy, per)
            for i in range(i0, i1 + 1)
            for j in range(j0, j1 + 1)
        )


# ─── 守卫与口径 ───────────────────────────────────────────────────────────────


class TestGuards:
    def test_no_sinks_zero_drop_and_r_none(self) -> None:
        res = dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 1e-3, W), (), 21, 21)
        assert res.v_drop_max_v == 0.0
        assert res.r_eff_ohm is None  # i_total=0 → 不虚构（is not None 判缺失，#364④）
        assert res.i_total_a == 0.0

    def test_vrm_rect_must_cover_nodes(self) -> None:
        with pytest.raises(ValueError, match="未覆盖任何网格节点"):
            dc_ir_drop(L, W, TH, SIG, V_VRM, (0.55e-3, 0.0, 0.9e-3, W), (), 21, 21)

    def test_sink_off_grid_rejected(self) -> None:
        with pytest.raises(ValueError, match="未吸附到网格节点"):
            dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 0.0, W),
                       (DcSink(1.234e-4, 0.0, 1.0),), 21, 21)

    def test_sink_outside_plate_rejected(self) -> None:
        with pytest.raises(ValueError, match="落在板外"):
            dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 0.0, W),
                       (DcSink(2.0 * L, 0.0, 1.0),), 21, 21)

    def test_sink_on_vrm_node_rejected(self) -> None:
        with pytest.raises(ValueError, match="钳压节点"):
            dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 1e-3, W),
                       (DcSink(0.0, 0.0, 1.0),), 21, 21)

    def test_sink_currents_merge_on_same_node(self) -> None:
        """同节点多汇点求和（并联负载语义）：2A 拆两笔与一笔 2A 同解。"""
        common = dict(length_m=L, width_m=W, thickness_m=TH, sigma_s_per_m=SIG,
                      v_vrm_v=V_VRM, vrm_rect=(0.0, 0.0, 0.0, W), n_x=21, n_y=21)
        node = 10e-3, 2.5e-3
        one = dc_ir_drop(sinks=(DcSink(*node, 2.0),), **common)
        two = dc_ir_drop(sinks=(DcSink(*node, 1.2), DcSink(*node, 0.8)), **common)
        assert one.phi.shape == two.phi.shape
        assert np.abs(one.phi - two.phi).max() < 1e-14

    def test_invalid_solver_name(self) -> None:
        a = assemble_plate_matrix(L, W, TH, SIG, 5, 5)
        with pytest.raises(ValueError, match="solver"):
            solve_dc_network(a, {0: 1.0}, np.zeros(25), solver="magic")

    def test_no_fixed_node_rejected(self) -> None:
        a = assemble_plate_matrix(L, W, TH, SIG, 5, 5)
        with pytest.raises(ValueError, match="钳压"):
            solve_dc_network(a, {}, np.zeros(25))

    def test_negative_total_injection_honest_sign(self) -> None:
        """净注人（负抽出）→ v_drop_max 为负，如实回报不夹持。"""
        res = dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 0.0, W),
                         edge_sinks("right", L, W, 21, -I_DRAW), 21, 21)
        assert abs(res.i_total_a + I_DRAW) < 1e-12  # 面宽加权和的浮点重构
        # 净注人抬电位：φ_max > V（v_drop_max 语义 = max(V−φ)，在钳压边界取 0）
        assert float(res.phi.max()) > V_VRM
        assert abs(float(res.phi.max()) - (V_VRM + I_DRAW * L / (SIG * TH * W))) < 1e-9
        assert res.r_eff_ohm is not None

    def test_as_dict_json_round_trip_keys(self) -> None:
        _, res = _r_opposite_edge(21)
        d = res.as_dict()
        for key in ("v_vrm_v", "v_drop_max_v", "i_total_a", "r_eff_ohm",
                    "n_nodes", "n_fixed", "solver", "rel_residual"):
            assert key in d

    def test_dc_sink_nonfinite_rejected(self) -> None:
        with pytest.raises(ValueError, match="有限"):
            dc_ir_drop(L, W, TH, SIG, V_VRM, (0.0, 0.0, 0.0, W),
                       (DcSink(float("nan"), 0.0, 1.0),), 21, 21)
