"""谐波平衡确定性内核（场-路协同的数值根）。

方案行口径
----------
"A3 Xyce 电路协同 | 场-路协同（EM S 参数→电路仿真，谐波平衡/非线性） |
对照 ngspice 参考解"。本模块是"谐波平衡/非线性"的确定性数值内核：
EM S 参数（任意频点，含真机 Touchstone 插值产物）经 s_to_y 转为导纳后，
作为线性多端口元件与非线性电路（二极管等）一起进入单音谐波平衡
（harmonic balance / harmonic-Newton）求解，产出各节点直流分量与谐波相量。

数值只在确定性内核：本模块纯 numpy 确定性实现，LLM/agent 不接触
任何数值；linkage 层只编排（组装电路、调 ngspice 参考、写报告）。

方法
----
谐波-Newton（实系数槽位向量 + 时域采样正交投影）：

- 未知量：每节点电压与 MNA 支路电流在 k=0..K 每谐波的实部/虚部系数槽位
  （物理波形 v(t) = c_0 + Σ_{k≥1} 2·Re{c_k e^{jkωt}}，c_{−k}=conj(c_k)）。
- 线性元件（R/C/EM N 端口）逐谐波精确 stamps；L 与电压源走 MNA 支路电流
  未知量（nodal 分析无法直接表达串联支路）；实 Jacobian 由逐谐波复 MNA
  矩阵的实虚部嵌入精确装配。
- 非线性（二极管）在时域采样点上逐点求值后经正交投影回谐波系数
  （K < N/2 时投影精确）；Jacobian 用链式法则 Q·diag(g)·P 精确装配。
- Newton 迭代 + 回溯阻尼；失败时源幅度同伦阶梯（0.05→1.0 暖启动）兜底。

与 ngspice 的对照由 linkage/field_circuit_nonlinear +
adapters/spice_netlist 承载：同一物理电路（RLC+二极管）两侧独立求解，
HB（频域）vs ngspice 瞬态+傅里叶（时域）互差进报告。

诚实边界
--------
- 二极管模型：Shockley 指数（Is/N），无结电容/串联电阻/温度效应——
  与 ngspice `.model D(Is=.. N=..)` 最小口径一致（Rs/CJO/IKF 等缺省关闭，
  两侧同为"纯指数结"）；指数宗量钳位 ≤80（标准 SPICE 防溢出做法，
  正常工况不触发）。
- 非线性电流带外分量被投影截断（K 谐波）；K 的收敛性由调用方
  （linkage 锚）以 K 阶梯加密自检。
- DC 方程取 MNA 矩阵实部（直流量本为实数；EM 端口 y_dc 若含虚部，
  虚部对 DC 方程无贡献——无源 DC 导纳本就实数）。
- 本模块不做 Touchstone 读取/插值（linkage 负责），只接受给定频点的
  Y 矩阵。

分层：core 叶子，不 import 仓库内其他层。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# --------------------------------------------------------------------------- #
# 物理常数（与 ngspice 缺省温度对齐：TEMP=TNOM=27°C=300.15K）
# --------------------------------------------------------------------------- #

#: 电路温度（K）。ngspice 缺省 TEMP=TNOM=27°C——热电压两侧一致是 HB vs
#: ngspice 二极管工况可比的物理前提。
TEMP_K = 300.15
BOLTZMANN_J_PER_K = 1.380649e-23
ELEMENTARY_CHARGE_C = 1.602176634e-19
#: 热电压 Vt = kT/q ≈ 25.852 mV（@300.15K）。
VT_THERMAL = BOLTZMANN_J_PER_K * TEMP_K / ELEMENTARY_CHARGE_C

#: 二极管指数宗量钳位（exp 宗量 ≤80，防 Newton 发散步浮点溢出）。
EXPONENT_LIMIT = 80.0


# --------------------------------------------------------------------------- #
# S → Y 转换（EM 数据进电路的桥）
# --------------------------------------------------------------------------- #

def s_to_y(s: np.ndarray, z0: float | complex | np.ndarray = 50.0) -> np.ndarray:
    """S 参数 → 导纳参数：Y = (1/z0)(I − S)(I + S)^{-1}（逐频点）。

    Args:
        s: shape (..., n, n)（单频点传 (n, n) 亦可）。
        z0: 参考阻抗（标量，或长度=频点数的一维数组）。

    Returns:
        Y，shape 与 s 相同。
    """
    s = np.asarray(s, dtype=complex)
    scalar = s.ndim == 2
    if scalar:
        s = s[None, ...]
    z0_arr = np.atleast_1d(np.asarray(z0, dtype=complex))
    n = s.shape[-1]
    eye = np.eye(n, dtype=complex)
    y = np.empty_like(s)
    for k in range(s.shape[0]):
        z0k = z0_arr[k] if z0_arr.size == s.shape[0] else z0_arr[0]
        a = eye - s[k]
        b = eye + s[k]
        if np.linalg.matrix_rank(b) < n:
            raise ValueError(f"频点 {k}: I+S 奇异（全反射），无法转 Y")
        y[k] = (a @ np.linalg.inv(b)) / z0k
    return y[0] if scalar else y


# --------------------------------------------------------------------------- #
# 电路元件（A3 最小完备集：EM N 端口 + R/L/C + 单音源 + 结型二极管）
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class HBResistor:
    """电阻（Ω），节点 a→b。"""
    node_a: int
    node_b: int
    resistance: float


@dataclass(frozen=True)
class HBCapacitor:
    """电容（F），节点 a→b。"""
    node_a: int
    node_b: int
    capacitance: float


@dataclass(frozen=True)
class HBInductor:
    """电感（H），节点 a→b（MNA 支路电流未知量）。"""
    node_a: int
    node_b: int
    inductance: float


@dataclass(frozen=True)
class HBDiode:
    """Shockley 结型二极管：i = Is·(exp(v/(N·Vt)) − 1)，v = v_anode − v_cathode。

    与 ngspice `.model <name> D(Is=<is> N=<n>)` 最小口径一致（Rs/CJO 等缺省
    关闭，两侧同为"纯指数结"），Vt 取 :data:`VT_THERMAL`（27°C，与 ngspice
    缺省 TEMP 一致）。
    """
    node_anode: int
    node_cathode: int
    is_sat: float
    emission_n: float = 1.0


@dataclass(frozen=True)
class HBVSource:
    """单音独立电压源：v(t) = dc + amp·cos(2π f0 t + phase)（余弦参考）。

    amp=峰值幅度（V）。MNA 支路电流（自 node_plus 经源流向 node_minus）为
    未知量。``phase_deg=-90`` 时 v(t)=amp·sin(ωt)，与 ngspice
    SIN(0 amp f0)（TD=0）波形逐点一致（网表侧换算见 adapters/spice_netlist）。
    """
    node_plus: int
    node_minus: int
    dc: float
    amp: float
    phase_deg: float = -90.0


@dataclass(frozen=True)
class HBEmNPort:
    """EM 提取的线性 N 端口（频域 Y 矩阵，逐谐波，公共地参考实现）。

    y_at_harmonics: shape (K, n, n)，第 k−1 行 = k·f0（k=1..K）处的导纳
    （S→Y 后）——**不含 DC 行**：真机 Touchstone 无 DC 点，DC 行为显式
    独立参数 ``y_dc`` (n, n)（如替代网络的闭式 DC 导纳）；None 时按
    "DC 开路"处理并在解里标注 ``em_dc_open=True``（诚实降级，不臆造
    DC 行为）。

    端口 i 的流出电流 I_i(h_k) = Σ_j Y_ij(h_k)·V_j（V_j 为节点对地电压，
    端口顺序 = ``nodes`` 元素顺序）。
    """
    nodes: tuple[int, ...]
    y_at_harmonics: np.ndarray
    y_dc: np.ndarray | None = None

    @property
    def n_ports(self) -> int:
        return len(self.nodes)


@dataclass
class HBCircuit:
    """单音谐波平衡电路：节点数 + 元件清单 + 分析设置（节点 0 恒为地）。"""
    n_nodes: int
    f0_hz: float
    elements: list[Any] = field(default_factory=list)
    n_harmonics: int = 7
    n_samples: int = 256

    def add(self, element: Any) -> HBCircuit:
        self.elements.append(element)
        return self


# --------------------------------------------------------------------------- #
# 系数 ↔ 时域采样（正交投影矩阵，构建一次复用）
# --------------------------------------------------------------------------- #

def pack_unpack_matrices(n_harmonics: int, n_samples: int) -> tuple[np.ndarray, np.ndarray]:
    """P: 系数槽位→采样 (N×m)；Q: 采样→系数槽位投影 (m×N)；m=2K+1。

    v(θ_j) = c_0 + Σ_{k≥1} 2[Re c_k·cos kθ_j − Im c_k·sin kθ_j]；
    反投影：c_0=(1/N)Σv，Re c_k=(1/N)Σv·cos kθ，Im c_k=−(1/N)Σv·sin kθ
    （由三角正交性 Σcos²=Σsin²=N/2、Σcos·sin=0）。谐波完备（K<N/2）时
    Q·P=I（单测钉死）；K ≥ N/2 会混叠，显式拒绝。
    """
    if n_harmonics >= n_samples / 2:
        raise ValueError(
            f"谐波数 K={n_harmonics} ≥ 采样点数 N={n_samples} 的一半（投影混叠）"
        )
    k = np.arange(n_harmonics + 1)
    theta = 2.0 * np.pi * np.arange(n_samples) / n_samples
    cos_kj = np.cos(np.outer(theta, k))  # (N, K+1)
    sin_kj = np.sin(np.outer(theta, k))
    p = np.zeros((n_samples, 2 * n_harmonics + 1))
    q = np.zeros((2 * n_harmonics + 1, n_samples))
    p[:, 0] = 1.0
    q[0, :] = 1.0 / n_samples
    for i in range(1, n_harmonics + 1):
        p[:, 2 * i - 1] = 2.0 * cos_kj[:, i]
        p[:, 2 * i] = -2.0 * sin_kj[:, i]
        q[2 * i - 1, :] = cos_kj[:, i] / n_samples
        q[2 * i, :] = -sin_kj[:, i] / n_samples
    return p, q


def hb_waveform_dense(
    coeffs: np.ndarray, node: int, n_points: int, n_harmonics: int,
) -> np.ndarray:
    """任意密度重建节点时域波形（n_points 点覆盖一个周期，直接三角求和）。"""
    c = np.asarray(coeffs, dtype=float)[node]
    theta = 2.0 * np.pi * np.arange(n_points) / n_points
    v = np.full(n_points, c[0])
    for i in range(1, n_harmonics + 1):
        v += 2.0 * c[2 * i - 1] * np.cos(i * theta)
        v -= 2.0 * c[2 * i] * np.sin(i * theta)
    return v


def phasor_of(coeffs: np.ndarray, node: int, harmonic: int) -> complex:
    """节点的谐波峰值相量（k=0 返回直流实数；k≥1 返回 2·c_k，余弦参考）。

    峰值相量即 |v(t)| 该次谐波分量的峰值幅度，对应 ngspice .four 的
    Magnitude 列口径（纯弦标定实测：1V 正弦源半分压 → 0.5）。
    """
    c = np.asarray(coeffs, dtype=float)[node]
    if harmonic == 0:
        return complex(c[0], 0.0)
    return 2.0 * complex(c[2 * harmonic - 1], c[2 * harmonic])


# --------------------------------------------------------------------------- #
# 逐谐波 MNA 装配
# --------------------------------------------------------------------------- #

def _split_elements(circuit: HBCircuit) -> dict[str, list[Any]]:
    by: dict[str, list[Any]] = {"r": [], "c": [], "l": [], "d": [], "v": [], "em": []}
    for el in circuit.elements:
        if isinstance(el, HBResistor):
            by["r"].append(el)
        elif isinstance(el, HBCapacitor):
            by["c"].append(el)
        elif isinstance(el, HBInductor):
            by["l"].append(el)
        elif isinstance(el, HBDiode):
            by["d"].append(el)
        elif isinstance(el, HBVSource):
            by["v"].append(el)
        elif isinstance(el, HBEmNPort):
            by["em"].append(el)
        else:
            raise TypeError(f"未知 HB 元件类型: {type(el).__name__}")
    return by


@dataclass
class _HarmonicContext:
    """预装配的逐谐波 MNA 上下文（Newton 全程复用）。"""
    n_nodes: int
    n_branch: int
    n_total: int
    n_harmonics: int
    dim_slot: int
    #: A[k]：复 MNA 矩阵 (n_total, n_total)——上半节点 KCL 行（含支路列），
    #: 下半支路约束行（V_a−V_b−z·I）。DC 行用其实部（直流量为实数）。
    a_blocks: list[np.ndarray]
    branches: list[tuple[str, Any]]
    p_mat: np.ndarray
    q_mat: np.ndarray
    #: 各槽位的全局下标（按元件连续布局 x[i*dim_slot + slot]）。
    slot_re: list[int]
    slot_im: list[int]

    def source_coeffs(self, amp_scale: float, circuit: HBCircuit) -> np.ndarray:
        """电压源约束右端 (n_branch, dim_slot)：k=0 行=dc；k≥1 = amp·e^{jφ}/2。"""
        e = np.zeros((self.n_branch, self.dim_slot))
        for idx, (kind, el) in enumerate(self.branches):
            if kind != "v":
                continue
            e[idx, 0] = amp_scale * el.dc
            ph = math.radians(el.phase_deg)
            c1 = 0.5 * amp_scale * el.amp * complex(math.cos(ph), math.sin(ph))
            e[idx, 1] = c1.real
            e[idx, 2] = c1.imag
        return e


def _build_context(circuit: HBCircuit) -> _HarmonicContext:
    """装配逐谐波复 MNA 块 A[k] 与投影矩阵（只建一次）。"""
    if circuit.n_harmonics < 1:
        raise ValueError("谐波数 K ≥ 1")
    if circuit.n_harmonics >= circuit.n_samples / 2:
        raise ValueError("谐波数 K 必须小于采样点数 N 的一半（投影正交性前提）")
    by = _split_elements(circuit)
    n_nodes = circuit.n_nodes
    branches = [("l", el) for el in by["l"]] + [("v", el) for el in by["v"]]
    n_branch = len(branches)
    n_total = n_nodes + n_branch
    m = circuit.n_harmonics
    dim_slot = 2 * m + 1

    a_blocks: list[np.ndarray] = []
    for k in range(m + 1):
        w = 2.0 * np.pi * k * circuit.f0_hz
        a = np.zeros((n_total, n_total), dtype=complex)
        # --- 节点 KCL 行：线性导纳（流出节点口径） ---
        for el in by["r"]:
            g = 1.0 / el.resistance
            a[el.node_a, el.node_a] += g
            a[el.node_b, el.node_b] += g
            a[el.node_a, el.node_b] -= g
            a[el.node_b, el.node_a] -= g
        for el in by["c"]:
            y = 1j * w * el.capacitance
            a[el.node_a, el.node_a] += y
            a[el.node_b, el.node_b] += y
            a[el.node_a, el.node_b] -= y
            a[el.node_b, el.node_a] -= y
        for el in by["em"]:
            if k == 0:
                continue  # DC 行不来自 Touchstone：仅由 y_dc 显式给出（见类 docstring）
            ymat = np.asarray(el.y_at_harmonics[k - 1], dtype=complex)
            if ymat.shape != (el.n_ports, el.n_ports):
                raise ValueError("EM N 端口 Y 矩阵尺寸与节点数不一致")
            for i in range(el.n_ports):
                for j in range(el.n_ports):
                    a[el.nodes[i], el.nodes[j]] += ymat[i, j]
        # --- 支路列（支路电流对流出口径）+ 支路约束行 ---
        for idx, (kind, el) in enumerate(branches):
            col = n_nodes + idx
            if kind == "l":
                a[el.node_a, col] += 1.0   # 电流 i 自 a 流向 b：离开 a
                a[el.node_b, col] -= 1.0   # 流入 b：离开 b 的为 −i
                a[n_nodes + idx, el.node_a] += 1.0
                a[n_nodes + idx, el.node_b] -= 1.0
                a[n_nodes + idx, col] -= 1j * w * el.inductance
            else:
                a[el.node_plus, col] += 1.0
                a[el.node_minus, col] -= 1.0
                a[n_nodes + idx, el.node_plus] += 1.0
                a[n_nodes + idx, el.node_minus] -= 1.0
        # 地方程：v_0 ≡ 0（MNA 地约束；地行其他条目清零）
        a[0, :] = 0.0
        a[0, 0] = 1.0
        a_blocks.append(a)

    slot_re = [0] + [2 * k - 1 for k in range(1, m + 1)]
    slot_im = [0] + [2 * k for k in range(1, m + 1)]
    p_mat, q_mat = pack_unpack_matrices(m, circuit.n_samples)
    return _HarmonicContext(
        n_nodes=n_nodes,
        n_branch=n_branch,
        n_total=n_total,
        n_harmonics=m,
        dim_slot=dim_slot,
        a_blocks=a_blocks,
        branches=branches,
        p_mat=p_mat,
        q_mat=q_mat,
        slot_re=slot_re,
        slot_im=slot_im,
    )


def _slot_indices(ctx: _HarmonicContext, harmonic: int) -> tuple[np.ndarray, np.ndarray]:
    """某谐波的全局槽位下标（按元件连续布局）。"""
    base = np.arange(ctx.n_total) * ctx.dim_slot
    return base + ctx.slot_re[harmonic], base + ctx.slot_im[harmonic]


def _coeffs_from_slots(ctx: _HarmonicContext, x: np.ndarray, harmonic: int) -> np.ndarray:
    """槽位向量 → 复谐波系数向量 (n_total,)。"""
    idx_re, idx_im = _slot_indices(ctx, harmonic)
    c = x[idx_re].astype(complex)
    if harmonic > 0:
        c = c + 1j * x[idx_im]
    return c


def _write_coeffs_to_slots(
    ctx: _HarmonicContext, x: np.ndarray, harmonic: int, values: np.ndarray,
) -> None:
    """复谐波系数向量 → 槽位向量（就地写入）。"""
    idx_re, idx_im = _slot_indices(ctx, harmonic)
    x[idx_re] = values.real
    if harmonic > 0:
        x[idx_im] = values.imag


def _nonlinear_term(
    circuit: HBCircuit, ctx: _HarmonicContext, v_slots: np.ndarray, with_jacobian: bool,
) -> tuple[np.ndarray, np.ndarray | None]:
    """二极管时域求值 → 谐波投影电流槽位（KCL 行加项）与其 Jacobian 块。

    口径与线性导纳一致：i_nl[anode] += i_d（流出阳极进二极管），
    i_nl[cathode] −= i_d；Jacobian 同导纳 stamp（+blk/−blk）。
    """
    n_nodes = ctx.n_nodes
    i_nl = np.zeros((n_nodes, ctx.dim_slot))
    g_nl = np.zeros((n_nodes * ctx.dim_slot, n_nodes * ctx.dim_slot)) if with_jacobian else None
    for el in _split_elements(circuit)["d"]:
        vd_t = ctx.p_mat @ (v_slots[el.node_anode] - v_slots[el.node_cathode])
        expo = np.clip(vd_t / (el.emission_n * VT_THERMAL), -EXPONENT_LIMIT, EXPONENT_LIMIT)
        exp_v = np.exp(expo)
        i_t = el.is_sat * (exp_v - 1.0)
        i_c = ctx.q_mat @ i_t
        i_nl[el.node_anode] += i_c
        i_nl[el.node_cathode] -= i_c
        if g_nl is not None:
            g_t = (el.is_sat / (el.emission_n * VT_THERMAL)) * exp_v
            blk = ctx.q_mat @ (g_t[:, None] * ctx.p_mat)
            na, nc = el.node_anode * ctx.dim_slot, el.node_cathode * ctx.dim_slot
            d = ctx.dim_slot
            g_nl[na:na + d, na:na + d] += blk
            g_nl[na:na + d, nc:nc + d] -= blk
            g_nl[nc:nc + d, na:na + d] -= blk
            g_nl[nc:nc + d, nc:nc + d] += blk
    # 地槽位：电流流入大地被吸收，不产生 KCL 残差/Jacobian 项
    i_nl[0] = 0.0
    if g_nl is not None:
        d = ctx.dim_slot
        g_nl[:d, :] = 0.0
        g_nl[:, :d] = 0.0
    return i_nl, g_nl


def _residual_and_jacobian(
    circuit: HBCircuit,
    ctx: _HarmonicContext,
    x: np.ndarray,
    e_coeffs: np.ndarray,
    with_jacobian: bool,
) -> tuple[np.ndarray, np.ndarray | None]:
    """组装 MNA-HB 残差 r(x)=A·x+i_nl−e 与（可选）实 Jacobian J(x)。"""
    n_nodes = ctx.n_nodes
    dim = ctx.dim_slot
    v_slots = x[: n_nodes * dim].reshape(n_nodes, dim)
    r = np.zeros_like(x)
    # 线性部分：逐谐波复矩阵乘 → 实虚槽位（口径：A·x + i_nl − e = 0）
    for k in range(ctx.n_harmonics + 1):
        x_k = _coeffs_from_slots(ctx, x, k)
        r_k = ctx.a_blocks[k] @ x_k
        idx_re, idx_im = _slot_indices(ctx, k)
        r[idx_re] += r_k.real
        if k > 0:
            r[idx_im] += r_k.imag
        # DC 行取实部即可（直流量为实数；见模块 docstring 诚实边界）
    # 电压源约束右端 −e（支路行）
    if ctx.n_branch:
        i0 = n_nodes * dim
        for idx in range(ctx.n_branch):
            r[i0 + idx * dim: i0 + (idx + 1) * dim] -= e_coeffs[idx]
    # 非线性投影电流（节点 KCL 行加项）
    i_nl, g_nl = _nonlinear_term(circuit, ctx, v_slots, with_jacobian)
    r[: n_nodes * dim] += i_nl.reshape(-1)
    if not with_jacobian:
        return r, None
    # Jacobian：逐谐波复块实虚嵌入（∂Re r/∂u=Re A，∂Re r/∂v=−Im A，…）
    n_slot = n_nodes * dim
    j = np.zeros((x.size, x.size))
    for k in range(ctx.n_harmonics + 1):
        a = ctx.a_blocks[k]
        idx_re, idx_im = _slot_indices(ctx, k)
        j[np.ix_(idx_re, idx_re)] += a.real
        j[np.ix_(idx_re, idx_im)] -= a.imag
        j[np.ix_(idx_im, idx_re)] += a.imag
        j[np.ix_(idx_im, idx_im)] += a.real
    if g_nl is not None:
        j[:n_slot, :n_slot] += g_nl
    return r, j


def _linear_only_solution(ctx: _HarmonicContext, e_coeffs: np.ndarray) -> np.ndarray:
    """非线性置零的线性 MNA 解（逐谐波独立；HB 初值/同伦底座）。"""
    x = np.zeros(ctx.n_total * ctx.dim_slot)
    for k in range(ctx.n_harmonics + 1):
        e_k = np.zeros(ctx.n_total, dtype=complex)
        if ctx.n_branch:
            e_k[ctx.n_nodes:] = e_coeffs[:, 0] + (
                1j * e_coeffs[:, ctx.slot_im[k]] if k > 0 else 0.0
            )
        x_k = np.linalg.solve(ctx.a_blocks[k], e_k)
        _write_coeffs_to_slots(ctx, x, k, x_k)
    return x


# --------------------------------------------------------------------------- #
# Newton 求解器
# --------------------------------------------------------------------------- #

@dataclass
class HBSolution:
    """HB 求解产物（物理口径访问器 + 求解诊断）。"""
    circuit: HBCircuit
    #: 实槽位向量：前 n_nodes·m 为节点电压系数，后 n_branch·m 为支路电流。
    x: np.ndarray
    converged: bool
    n_iterations: int
    residual_inf: float
    #: EM 端口是否按"DC 开路"处理（y_dc=None 的诚实降级标注）。
    em_dc_open: bool
    #: 求解是否走了源幅度同伦阶梯兜底。
    used_homotopy: bool = False

    @property
    def voltage_coeffs(self) -> np.ndarray:
        return self.x[: self.circuit.n_nodes * (2 * self.circuit.n_harmonics + 1)].reshape(
            self.circuit.n_nodes, 2 * self.circuit.n_harmonics + 1,
        )

    def node_dc(self, node: int) -> float:
        return float(self.voltage_coeffs[node, 0])

    def node_phasor(self, node: int, harmonic: int) -> complex:
        return phasor_of(self.voltage_coeffs, node, harmonic)

    def node_amplitude(self, node: int, harmonic: int) -> float:
        return abs(self.node_phasor(node, harmonic))

    def waveform(self, node: int, n_points: int | None = None) -> np.ndarray:
        n = n_points if n_points is not None else self.circuit.n_samples
        return hb_waveform_dense(
            self.voltage_coeffs, node, n, self.circuit.n_harmonics,
        )


def _newton(
    circuit: HBCircuit,
    ctx: _HarmonicContext,
    x0: np.ndarray,
    e_coeffs: np.ndarray,
    *,
    tol_current: float,
    tol_step: float,
    max_iter: int,
) -> tuple[np.ndarray, bool, int, float]:
    """带回溯阻尼的 Newton 迭代（确定性：固定 halving 阶梯）。"""
    x = x0.copy()
    r, _ = _residual_and_jacobian(circuit, ctx, x, e_coeffs, False)
    norm = float(np.max(np.abs(r)))
    it = 0
    for it in range(1, max_iter + 1):
        if norm <= tol_current:
            return x, True, it - 1, norm
        _, jac = _residual_and_jacobian(circuit, ctx, x, e_coeffs, True)
        try:
            dx = np.linalg.solve(jac, -r)
        except np.linalg.LinAlgError:
            return x, False, it, norm
        alpha = 1.0
        for _ in range(40):
            x_try = x + alpha * dx
            r_try, _ = _residual_and_jacobian(circuit, ctx, x_try, e_coeffs, False)
            if float(np.max(np.abs(r_try))) < norm:
                break
            alpha *= 0.5
        x = x + alpha * dx
        r, _ = _residual_and_jacobian(circuit, ctx, x, e_coeffs, False)
        norm = float(np.max(np.abs(r)))
        step_rel = float(np.max(np.abs(alpha * dx))) / max(1.0, float(np.max(np.abs(x))))
        if step_rel <= tol_step:
            return x, norm <= tol_current, it, norm
    return x, norm <= tol_current, it, norm


def solve_harmonic_balance(
    circuit: HBCircuit,
    *,
    tol_current: float = 1e-9,
    tol_step: float = 1e-12,
    max_newton_iter: int = 100,
    homotopy_steps: int = 20,
) -> HBSolution:
    """单音谐波平衡求解（Newton + 回溯阻尼；失败时源幅度同伦兜底）。

    收敛判据：残差无穷范数 ≤ ``tol_current``（SI 混合单位，A/V）。
    未收敛（含同伦兜底失败）抛 RuntimeError——锚是裁判，不静默降级。
    """
    ctx = _build_context(circuit)
    em_dc_open = False
    for el in circuit.elements:
        if isinstance(el, HBEmNPort):
            if el.y_dc is None:
                em_dc_open = True  # DC 开路：不加 DC 导纳（A[0] 无 EM 项）
            else:
                ydc = np.asarray(el.y_dc, dtype=complex)
                if ydc.shape != (el.n_ports, el.n_ports):
                    raise ValueError("EM N 端口 y_dc 尺寸与节点数不一致")
                for i in range(el.n_ports):
                    for j in range(el.n_ports):
                        ctx.a_blocks[0][el.nodes[i], el.nodes[j]] += ydc[i, j]

    def attempt(ladder: np.ndarray) -> tuple[np.ndarray, bool, int, float, bool]:
        x = _linear_only_solution(ctx, ctx.source_coeffs(float(ladder[0]), circuit))
        total_it = 0
        used_h = len(ladder) > 1
        for lam in ladder:
            e_l = ctx.source_coeffs(float(lam), circuit)
            x, ok, it, res = _newton(
                circuit, ctx, x, e_l,
                tol_current=tol_current, tol_step=tol_step, max_iter=max_newton_iter,
            )
            total_it += it
            if not ok:
                return x, False, total_it, res, used_h
        return x, True, total_it, res, used_h

    x, ok, n_it, res, used_h = attempt(np.array([1.0]))
    if not ok:
        ladder = np.linspace(0.05, 1.0, max(2, homotopy_steps))
        x, ok, n_it, res, used_h = attempt(ladder)
    if not ok:
        raise RuntimeError(
            f"谐波平衡未收敛（Newton 与同伦兜底均失败，最后残差 {res:.3e}）"
        )
    return HBSolution(
        circuit=circuit,
        x=x,
        converged=True,
        n_iterations=int(n_it),
        residual_inf=float(res),
        em_dc_open=bool(em_dc_open),
        used_homotopy=bool(used_h),
    )
