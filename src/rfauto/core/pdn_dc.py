"""DR-6 PDN 直流压降确定性内核（平面 DC IR-drop，五点 stencil 电导稀疏阵）。

规格出处：规格深案 §C-5 DR-6（P1/M）。全套数值
机制复用 core/quasistatic_fd.py 先例（sp.coo_matrix 四块组装→tocsr、Dirichlet
自由/固定分块消元、spla.spsolve 族直解、一阶 Richardson 外推），铁律 7：
数值只在确定性内核，本模块 = 纯 numpy/scipy 叶子，零业务依赖。

物理口径：
- 矩形导体板 [0,L]×[0,W]、厚 t、电导率 σ（S/m），面电导 σt（S，每方）；
  静电势 φ 满足 ∇·(σt∇φ) = −i_inj（节点注人电流，A；正注人=电流流入平面）。
- 五点 stencil：相邻节点电导 = σt·(面宽/边长)，面宽为**有限体积半格口径**
  （quasistatic_fd 同款）：水平边 (i,j)-(i+1,j) 电导 g_h = σt·w_y(j)/Δx
  （w_y = Δy，端行 Δy/2）、竖直边 g_v = σt·w_x(i)/Δy（w_x = Δx，端列 Δx/2）
  ——边界行/列的边缘只能分到半格面宽，整格权重会使边界行电流密度加倍
  （实测线性锚 R 偏 R·(n−1)/n、一阶收敛，故不取）。
- 边界：VRM 钳压 = Dirichlet（矩形焊区覆盖的节点 φ=V_vrm）；其余外边界自然
  Neumann（零法向电流流出色散域）；汇点 = 节点电流源（正 current_a = 从平面
  抽出，即负载电流）。
- 求解器两档（规格钉）：总节点 N ≤ 2e5 直接 splu；更大 Jacobi 预条件 CG
  （相对残差门 1e-12，超门显式报错不静默）。

对边注入锚（解析可证，test_pdn_dc.py 钉）：整左边缘 Dirichlet + 整右边缘
均匀汇点时，线性场 φ(x)=V0−(I/(σtW))·x **逐节点精确满足离散方程**（内部二阶
差分为零；右缘节点通量 g_h·Δx·I/(σtW)=I·Δy/W 恰与该节点汇流平衡），故解算
R = L/(σt·W) 达机器精度（≪规格 1% 门），Richardson 外推互证同值。

诚实边界（预声明）：
1. 均匀网格五点 stencil，离散误差 O(d²)（二阶）；点汇在网格上是有限分辨率
   近似（连续域点汇有对数奇异），有限尺寸焊区随网格加密收敛——真值锚一律用
   均匀边缘注入（离散精确）或自收敛+Richardson，不用点汇绝对值裁判；
2. 仅矩形板/均匀 σt（无开槽/挖孔/变厚）；多相网络请按层叠板另行建模；
3. 返回的 r_eff 以 v_drop_max/i_total 定义（最大压降点未必是电流路径等效端口，
   供裁判参考）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

#: splu 直解节点上限（规格 §C-5：N≤2e5 直接 splu，更大走 Jacobi-CG）
SPLU_NODE_LIMIT = 200_000

#: Jacobi-CG 相对残差门（规格钉：残差 1e-12；rtol 收 1e-13 留判据余量）
CG_REL_RESIDUAL_TOL = 1e-12
_CG_RTOL = 1e-13

#: 汇点/焊区坐标吸附容差（相对板尺寸）
_POS_TOL = 1e-9


def _positive(value: Any, name: str) -> float:
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return out


# ─── 闭式锚 ──────────────────────────────────────────────────────────────────


def plate_resistance_1d(
    length_m: float, width_m: float, thickness_m: float, sigma_s_per_m: float
) -> float:
    """对边（整边）注入矩形板直流电阻闭式 R = L/(σ·t·W）。

    电流沿 L 向均匀流动（整边进入/整边抽出）时的板电阻；DR-6 网格解算锚。
    """
    length = _positive(length_m, "length_m")
    width = _positive(width_m, "width_m")
    thick = _positive(thickness_m, "thickness_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    return length / (sigma * thick * width)


@dataclass(frozen=True)
class DcSink:
    """汇点（负载电流抽头）。

    Attributes:
        x_m / y_m: 汇点位置（m，板内坐标系 [0,L]×[0,W]）。
        current_a: 抽出电流（A，正 = 从平面抽出流入负载；负 = 注人）。
            多个汇点吸附到同一节点时电流求和（并联负载语义）。
    """

    x_m: float
    y_m: float
    current_a: float


def edge_sinks(
    edge: str, length_m: float, width_m: float, n_points: int, total_current_a: float
) -> tuple[DcSink, ...]:
    """沿板边缘均匀布 n_points 个汇点（对边注入锚的布点助手）。

    Args:
        edge ∈ {"left","right","bottom","top"}；n_points 与网格该边节点数一致、
        均匀布点时吸附到全部边节点。

    电流分配按**有限体积面宽**加权（端节点半格、内点整格，Σw = 边长）——
    这是均匀边缘注入的离散精确构造条件（见模块 docstring 对边注入锚）：
    端节点若与内点同流，边界行电流密度被加倍，线性场不再精确满足离散方程
    （实测 R 偏 R·(n−1)/n、一阶收敛，锚失效）。
    """
    length = _positive(length_m, "length_m")
    width = _positive(width_m, "width_m")
    n = int(n_points)
    if n < 2:
        raise ValueError(f"n_points 必须 ≥2，实际 {n}")
    total = float(total_current_a)
    if not math.isfinite(total):
        raise ValueError(f"total_current_a 必须为有限数，实际 {total_current_a!r}")
    if edge not in ("left", "right", "bottom", "top"):
        raise ValueError(f"edge 必须是 left/right/bottom/top，实际 {edge!r}")
    span = length if edge in ("bottom", "top") else width
    step = span / (n - 1)
    weights = np.full(n, step)
    weights[0] = weights[-1] = step / 2.0
    per_node = total * weights / weights.sum()
    ys = (np.arange(n) * width / (n - 1)).tolist()
    xs = (np.arange(n) * length / (n - 1)).tolist()
    if edge == "left":
        return tuple(DcSink(0.0, y, float(cur)) for y, cur in zip(ys, per_node, strict=True))
    if edge == "right":
        return tuple(DcSink(length, y, float(cur)) for y, cur in zip(ys, per_node, strict=True))
    if edge == "bottom":
        return tuple(DcSink(x, 0.0, float(cur)) for x, cur in zip(xs, per_node, strict=True))
    if edge == "top":
        return tuple(DcSink(x, width, float(cur)) for x, cur in zip(xs, per_node, strict=True))
    raise ValueError(f"edge 必须是 left/right/bottom/top，实际 {edge!r}")


# ─── 装配 ────────────────────────────────────────────────────────────────────


def assemble_plate_matrix(
    length_m: float,
    width_m: float,
    thickness_m: float,
    sigma_s_per_m: float,
    n_x: int,
    n_y: int,
) -> sp.csr_matrix:
    """矩形板五点 stencil 电导稀疏阵 A（N=n_x·n_y 节点，n = i·n_y + j）。

    节点 (i,j) 位于 (i·Δx, j·Δy)；相邻节点电导 = σt·面宽/边长，面宽为有限
    体积半格口径（quasistatic_fd 同款）：g_h(i,j) = σt·w_y(j)/Δx（w_y = Δy，
    端行 Δy/2）、g_v(i,j) = σt·w_x(i)/Δy（w_x = Δx，端列 Δx/2）；
    A = Σ_edges g·(e_a−e_b)(e_a−e_b)^T（对称半正定，Dirichlet 缺席时奇异
    ——至少一个钳压节点后正定）。组装复用 quasistatic_fd.energy_quasistatic
    的 coo 四块先例。
    """
    length = _positive(length_m, "length_m")
    width = _positive(width_m, "width_m")
    thick = _positive(thickness_m, "thickness_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    nx = int(n_x)
    ny = int(n_y)
    if nx < 2 or ny < 2:
        raise ValueError(f"n_x/n_y 必须 ≥2，实际 ({n_x!r}, {n_y!r})")
    dx = length / (nx - 1)
    dy = width / (ny - 1)
    g_st = sigma * thick  # 面电导（S）
    # 有限体积半格面宽（quasistatic_fd 同款；见模块 docstring stencil 口径）
    w_y = np.full(ny, dy)
    w_y[0] = w_y[-1] = dy / 2.0
    w_x = np.full(nx, dx)
    w_x[0] = w_x[-1] = dx / 2.0

    ii, jj = np.meshgrid(np.arange(nx - 1), np.arange(ny), indexing="ij")
    h1 = (ii * ny + jj).ravel()
    h2 = ((ii + 1) * ny + jj).ravel()
    gh = g_st * w_y[jj.ravel()] / dx  # 水平边 (i,j)-(i+1,j)，面宽 w_y(j)
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny - 1), indexing="ij")
    v1 = (ii * ny + jj).ravel()
    v2 = (ii * ny + jj + 1).ravel()
    gv = g_st * w_x[ii.ravel()] / dy  # 竖直边 (i,j)-(i,j+1)，面宽 w_x(i)

    n1 = np.concatenate([h1, v1])
    n2 = np.concatenate([h2, v2])
    g = np.concatenate([gh, gv])
    n_nodes = nx * ny
    return sp.coo_matrix(
        (np.concatenate([g, g, -g, -g]),
         (np.concatenate([n1, n2, n1, n2]), np.concatenate([n1, n2, n2, n1]))),
        shape=(n_nodes, n_nodes),
    ).tocsr()


def solve_dc_network(
    a: sp.csr_matrix,
    fixed: dict[int, float],
    injected: np.ndarray,
    *,
    solver: str = "auto",
    n_nodes_limit: int = SPLU_NODE_LIMIT,
) -> tuple[np.ndarray, float, str]:
    """解 A·φ = b（钳压节点消元），返回 (φ, 相对残差, 求解器名)。

    - fixed: 钳压节点号 → 电位（VRM Dirichlet）；至少一个，否则 A 奇异。
    - injected: 全长节点注人电流向量（固定节点上的注人被钳压吸收，忽略）。
    - solver："auto"（N ≤ n_nodes_limit → splu，否则 Jacobi-CG）|"splu"|"cg"。
      CG 相对残差超 CG_REL_RESIDUAL_TOL 显式 RuntimeError（不静默）。
    """
    if solver not in ("auto", "splu", "cg"):
        raise ValueError(f"solver 必须是 auto/splu/cg，实际 {solver!r}")
    a = sp.csr_matrix(a)
    n_nodes = a.shape[0]
    if not fixed:
        raise ValueError("至少需要一个钳压（Dirichlet）节点，否则电导阵奇异")
    phi = np.zeros(n_nodes)
    is_fixed = np.zeros(n_nodes, dtype=bool)
    for node, val in fixed.items():
        k = int(node)
        if not (0 <= k < n_nodes):
            raise ValueError(f"钳压节点号 {node!r} 越界（N={n_nodes}）")
        phi[k] = float(val)
        is_fixed[k] = True
    injected = np.asarray(injected, dtype=float)
    if injected.shape != (n_nodes,):
        raise ValueError(f"injected 长度须 {n_nodes}，实际 {injected.shape}")

    free = ~is_fixed
    a_ff = a[free][:, free].tocsc()
    rhs = injected[free] - (a[free][:, is_fixed] @ phi[is_fixed])
    n_free = int(free.sum())
    use_cg = solver == "cg" or (solver == "auto" and n_nodes > n_nodes_limit)
    if use_cg:
        jacobi = sp.diags(1.0 / a_ff.diagonal())
        x, info = spla.cg(a_ff, rhs, rtol=_CG_RTOL, atol=0.0, M=jacobi,
                          maxiter=max(1000, 10 * n_free))
        if info != 0:
            raise RuntimeError(f"Jacobi-CG 未收敛（info={info}，n_free={n_free}）")
        used = "cg"
    else:
        x = spla.splu(a_ff).solve(rhs)
        used = "splu"
    phi[free] = x
    rel_res = float(np.linalg.norm(a_ff @ x - rhs) / max(np.linalg.norm(rhs), 1e-300))
    if use_cg and rel_res > CG_REL_RESIDUAL_TOL:
        raise RuntimeError(f"CG 相对残差 {rel_res:.3e} 超门 {CG_REL_RESIDUAL_TOL:.0e}")
    return phi, rel_res, used


# ─── 主入口 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DcIrDropResult:
    """一次直流压降解算结果（字段语义见 dc_ir_drop）。"""

    v_vrm_v: float
    v_drop_max_v: float  # max(V_vrm − φ)（自由节点；净注人时可为负，如实）
    v_drop_at_x_m: float  # 最大压降节点 x（m）
    v_drop_at_y_m: float  # 最大压降节点 y（m）
    i_total_a: float  # 汇点总抽出电流（Σ current_a，正=净抽出）
    r_eff_ohm: float | None  # v_drop_max/i_total；i_total=0 → None（不虚构）
    n_nodes: int
    n_fixed: int
    solver: str  # "splu" | "cg"
    rel_residual: float
    phi: np.ndarray  # (n_x, n_y) 电位场（V）
    x_m: np.ndarray  # (n_x,) 网格 x 坐标
    y_m: np.ndarray  # (n_y,) 网格 y 坐标

    def as_dict(self) -> dict[str, Any]:
        return {
            "v_vrm_v": self.v_vrm_v,
            "v_drop_max_v": self.v_drop_max_v,
            "v_drop_at_x_m": self.v_drop_at_x_m,
            "v_drop_at_y_m": self.v_drop_at_y_m,
            "i_total_a": self.i_total_a,
            "r_eff_ohm": self.r_eff_ohm,
            "n_nodes": self.n_nodes,
            "n_fixed": self.n_fixed,
            "solver": self.solver,
            "rel_residual": self.rel_residual,
        }


def dc_ir_drop(
    length_m: float,
    width_m: float,
    thickness_m: float,
    sigma_s_per_m: float,
    v_vrm_v: float,
    vrm_rect: tuple[float, float, float, float],
    sinks: Sequence[DcSink],
    n_x: int,
    n_y: int,
    *,
    solver: str = "auto",
) -> DcIrDropResult:
    """矩形板直流压降解算（VRM 钳压 + 汇点电流源，见模块 docstring 口径）。

    Args:
        length_m / width_m: 板尺寸（m，坐标系 [0,L]×[0,W]）。
        thickness_m: 铜厚（m，正数）。
        sigma_s_per_m: 电导率（S/m，正数；铜 5.8e7 量级由调用方给）。
        v_vrm_v: VRM 钳压电位（V）。
        vrm_rect: VRM 焊区 (x0, y0, x1, y1)（m；覆盖的网格节点全部钳压，
            至少含 1 节点）。
        sinks: 汇点序列（DcSink；正 current_a = 抽出）。空序列合法
            （纯钳压 → 零压降）。
        n_x / n_y: 两轴节点数（≥2）。
        solver: "auto"|"splu"|"cg"（见 solve_dc_network）。

    Returns:
        DcIrDropResult（φ 场 + 最大压降 + 等效电阻 + 求解器与残差观测）。
    """
    length = _positive(length_m, "length_m")
    width = _positive(width_m, "width_m")
    v_vrm = float(v_vrm_v)
    if not math.isfinite(v_vrm):
        raise ValueError(f"v_vrm_v 必须为有限数，实际 {v_vrm_v!r}")
    rect = tuple(float(v) for v in vrm_rect)
    if len(rect) != 4:
        raise ValueError(f"vrm_rect 必须是 (x0,y0,x1,y1) 四元组，实际 {vrm_rect!r}")
    x0, y0, x1, y1 = rect
    if not all(math.isfinite(v) for v in rect) or x1 < x0 or y1 < y0:
        raise ValueError(f"vrm_rect 必须为有限矩形（x1≥x0、y1≥y0），实际 {vrm_rect!r}")

    nx = int(n_x)
    ny = int(n_y)
    if nx < 2 or ny < 2:
        raise ValueError(f"n_x/n_y 必须 ≥2，实际 ({n_x!r}, {n_y!r})")
    xs = np.linspace(0.0, length, nx)
    ys = np.linspace(0.0, width, ny)
    a = assemble_plate_matrix(length, width, thickness_m, sigma_s_per_m, nx, ny)
    n_nodes = a.shape[0]

    # VRM 钳压节点（矩形覆盖；容差按网格间距相对量）
    tol_x = _POS_TOL * max(length, 1e-30)
    tol_y = _POS_TOL * max(width, 1e-30)
    mask = (
        (xs[:, None] >= x0 - tol_x) & (xs[:, None] <= x1 + tol_x)
        & (ys[None, :] >= y0 - tol_y) & (ys[None, :] <= y1 + tol_y)
    )
    fixed_idx = np.flatnonzero(mask.ravel())
    if fixed_idx.size == 0:
        raise ValueError(f"vrm_rect {vrm_rect!r} 未覆盖任何网格节点（检查坐标/网格密度）")
    fixed = {int(k): v_vrm for k in fixed_idx}

    # 汇点电流按节点归并（同节点并联求和；落点最近节点吸附）
    inj = np.zeros(n_nodes)
    for k, snk in enumerate(sinks):
        sx, sy, sc = float(snk.x_m), float(snk.y_m), float(snk.current_a)
        if not (math.isfinite(sx) and math.isfinite(sy) and math.isfinite(sc)):
            raise ValueError(f"sinks[{k}] 坐标/电流必须为有限数，实际 {snk!r}")
        if not (-tol_x <= sx <= length + tol_x and -tol_y <= sy <= width + tol_y):
            raise ValueError(f"sinks[{k}] 位置 ({sx!r},{sy!r}) 落在板外")
        i = int(np.argmin(np.abs(xs - sx)))
        j = int(np.argmin(np.abs(ys - sy)))
        if abs(xs[i] - sx) > max(tol_x, 1e-15) or abs(ys[j] - sy) > max(tol_y, 1e-15):
            raise ValueError(
                f"sinks[{k}] 位置 ({sx!r},{sy!r}) 未吸附到网格节点（最近 "
                f"({xs[i]!r},{ys[j]!r})）——汇点必须落在网格上"
            )
        node = i * ny + j
        if node in fixed:
            raise ValueError(
                f"sinks[{k}] 落在 VRM 钳压节点上（电流被钳压静默吸收，拒绝——"
                "fail loud #316 方向）"
            )
        inj[node] -= sc  # 抽出为负注人

    phi, rel_res, used = solve_dc_network(a, fixed, inj, solver=solver)
    phi_grid = phi.reshape(nx, ny)
    drop = v_vrm - phi_grid
    kmax = int(np.argmax(drop))
    i_max, j_max = divmod(kmax, ny)
    i_total = float(sum(float(s.current_a) for s in sinks))
    r_eff: float | None = None
    if i_total != 0.0:
        r_eff = float(drop[i_max, j_max] / i_total)
    return DcIrDropResult(
        v_vrm_v=v_vrm,
        v_drop_max_v=float(drop[i_max, j_max]),
        v_drop_at_x_m=float(xs[i_max]),
        v_drop_at_y_m=float(ys[j_max]),
        i_total_a=i_total,
        r_eff_ohm=r_eff,
        n_nodes=n_nodes,
        n_fixed=int(fixed_idx.size),
        solver=used,
        rel_residual=rel_res,
        phi=phi_grid,
        x_m=xs,
        y_m=ys,
    )
