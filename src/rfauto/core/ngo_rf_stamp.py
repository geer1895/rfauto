"""RF 复数参数仿射 stamp 族内核（NGO 三期，aurora_p D1 席）。

定位：green_stamp v1（T-O7，``core/green_stamp.py``——实数稳态扩散族，本模块
只读消费其 ``_StampMLP``/``default_lambda_grid``，零复制零改动）的 **RF 复数
扩展**——参数仿射算子

    Y(λ,ω) = Y₀(ω) + Σ_k λ_k·Y_k(ω)          （复数节点导纳 stamp）

物理形态：n_grid×n_grid 节点 RC 导纳网络——每条邻边带背景并联导纳
g_bg + jω·c_bg、每节点带对地并联 g_g0 + jω·c_g0（全部进 Y₀，保证严格无源
与可逆性）；条带块 k 的边额外叠加 λ_k·(g_ch_k + jω·c_ch_k)（进 Y_k）——
对 λ **构造性精确仿射**（导纳按边线性叠加，Y_k(ω) 为固定复基矩阵），
对 ω 经 jω 线性（RC 网络的物理频率响应面）。λ 为无量纲通道乘子（物理域
λ_k ≥ 0：额外导纳非负保持无源；负值=有源面，``physical_valid`` 显式旗标）。
端口=两个对角角点（P=2，参考阻抗 port_z0），S 参数经**端接口径**求解出。

结构先验与分工（NGO，TU/e CMAME 455:118893 精神，green_stamp 同款映射）：
- 网络只学两件事：① **θ→stamp 系数**（``RfStampPredictor.predict_coefficients``
  ——red line 铁律 7 口径：最终 S 由 Y(λ̂,ω) 的**精确线性求解**出，网络误差
  只活在系数空间）；② **(λ,ω)→Â≈Y⁻¹**（``predict_a_hat``，GMRES 预条件/
  Newton-Schulz 精修的加速面——永不进最终 S 的数值通道）。
- S 求解=端口约束精确线性系统（``solve_s_matrix``）：端口行按
  V_k + Z_k·I_k = 2√Z_k·a_k 端接（坑账 #290 端接口径——内部谐振处开路
  激励消元奇异；本模块独立实现导纳域端接系统，参考路径复用仓内单源
  ``core/slotline_transitions.reduce_to_s_matrix``（Z 域同约束方程）互证）。
- 无源性 verdict 消费 ``pole_residue.passivity_verdict`` 单源（surrogate 层
  接线，本内核不复制公式）。

复数 einsum 路径（GMRES/NS）：
- GMRES：scipy 复数路径，**左预条件**（坑账 ⑫：scipy gmres=左预条件，
  源码口径；预条件残差传播谱半径量 ρ(I−ÂY) 因 AB/BA 特征多项式恒等
  χ_AB=χ_BA（方阵）而不歧义——green_stamp 同款记法）。
- Newton-Schulz：复数 einsum 精修 Â⁺=2Â−Â·Y·Â（恒等式
  I−Â⁺Y=(I−ÂY)² 逐位成立——``ns_step`` 纯函数+测试钉），逐样本单调
  不退化守卫（``newton_schulz_refine``）。

预声明简化（如实钉死不静默）：
1. 系数头目标=恒等参数化（Model 档：系数标签=归一化 λ 本身，family 自产）
   ——学习任务刻意最小，结构先验（精确装配+精确求解）承载频率面与物理
   一致性，网络只补系数面误差；这是"参数进算子"结构的最小落地形态。
2. 频率不学基：训练栅格=预测栅格（``RfStampPredictor`` 持有 freq_grid_hz；
   栅格外输入可机械运行但未受训，不保证精度——不伪造）。
3. P=2 端口、稠密 n×n（n_grid 缺省 4 → n=16）、Â 直接预测稠密逆——
   稀疏/多端口/基展开扩展不在本席。
4. 黑箱 OOD 对照臂=同容量 ``BlackBoxResponseNet``（λ→整条 S 响应直映，
   剥离结构先验的唯一受控变量；green_stamp BlackBoxSolutionNet 先例同构）。
5. 互易性：装配对称（Y=Yᵀ 逐位，同值双边累加）⇒ 精确算术下 S=Sᵀ；数值
   求解路径不按构造强制对称（双列独立求解，残差在浮点底）——测试实测
   报数（装配级逐位 + 求解级 ≤1e-12 相对，不冒充逐位）。

确定性（AGENTS 7 / C4）：全链路固定 seed 的 ``np.random.default_rng``（不触
全局 RNG），训练全批 Adam 无采样随机；gmres/inv/solve 数值确定性——同
seed 同数据两跑逐位一致（测试钉住）。

分层与零改动（铁律 3/任务书）：core 叶子只 import stdlib+numpy+scipy+同层
（``green_stamp``/``slotline_transitions``）；本模块不注册代理键、不触既有
消费面（纯增量独立件，green_op/ngo_stamp 先例零改动——注册面在
optimization/surrogate/ngo_stamp_rf.py 新键 ``ngo_stamp_rf``）。

诚实边界：
- 合成族真值=离散线性系统本身（解析构造即定义）；门的裁判走独立数值路径
  （导纳域端接系统 vs Z 域 reduce_to_s_matrix 互证），不外推真机精度；
- 系数头/逆头精度受网络容量与训练预算限制——门在测试预声明（定标证据
  runs/aurora_p/d1/），超界如实降级不凑绿；
- 不提供逐点不确定度（无 σ 面，不伪造）。
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres

from rfauto.core.green_stamp import _StampMLP, default_lambda_grid
from rfauto.core.slotline_transitions import reduce_to_s_matrix

__all__ = [
    "SPECTRAL_RADIUS_WARN_DEFAULT",
    "BlackBoxResponseNet",
    "ComplexAffineStampFamily",
    "RfStampPredictor",
    "default_lambda_grid",
    "gmres_iteration_table",
    "ns_step",
    "ood_error_table",
]

#: 谱半径警戒缺省阈值（Neumann 型必要条件 ρ(I−ÂY)<1；超界显式 warning
#: 不静默，GMRES 仍照跑并如实报告——green_stamp 同款语义）。
SPECTRAL_RADIUS_WARN_DEFAULT = 1.0

_TINY = 1e-300


# ─── 合成族：RF RC 导纳网络（构造性参数仿射，复数） ─────────────────────────


class ComplexAffineStampFamily:
    """Y(λ,ω)=Y₀(ω)+Σ_k λ_k·Y_k(ω) 的 RC 导纳网络族（复数、精确仿射、无源域）。

    几何：n_grid×n_grid 内点（n=n_grid²），节点索引 (i,j)→i·n_grid+j；邻边
    （水平+垂直）各带背景导纳 g_bg+jω·c_bg，节点各带对地导纳
    g_g0+jω·c_g0（全部只进 Y₀——背景通道固定、材料参数进额外通道的
    green_stamp 语义）。K=``n_blocks`` 个条带按边中点 x 坐标等宽确定性划分
    （零 RNG），块 k 的边额外叠加 λ_k·(g_ch_k+jω·c_ch_k)——Y_k(ω)=
    (g_ch_k+jω·c_ch_k)·L_k（L_k=块 k 边集的实 Laplacian 图样）。

    ``lossless=True`` 时全部电导置零（纯电纳网络）——Y=jω·B（B 正定：
    Laplacian·c + c_g0·I，ω>0 时非奇异）⇒ S 严格酉（|S|≤1 且 σmax≈1），
    供验收 B（无源无耗回收）使用。

    装配双路径：``_walk`` 独立逐边累加；``system_matrix`` 走基矩阵线性组合
    （消费单源）；``stamp_affine_residual`` 实测两路径之差（≤1e-12 相对，
    green_stamp 同款门）；``affine_segment_residual`` 实测
    Y(λ+a·e_k)−Y(λ)≡a·Y_k(ω)（∂Y/∂λ_k≡Y_k 常数性的代数自检量）。
    """

    def __init__(self, *, n_grid: int = 4, n_blocks: int = 2,
                 g_bg: float = 1e-3, c_bg: float = 1e-12,
                 g_g0: float = 1e-4, c_g0: float = 5e-13,
                 g_ch: float = 2e-3, c_ch: float = 3e-12,
                 port_z0: float = 50.0, lossless: bool = False) -> None:
        if int(n_grid) < 2:
            raise ValueError("ComplexAffineStampFamily：n_grid 须 ≥2")
        if int(n_blocks) < 1:
            raise ValueError("ComplexAffineStampFamily：n_blocks 须 ≥1")
        if not (float(port_z0) > 0.0):
            raise ValueError("ComplexAffineStampFamily：port_z0 须 >0")
        for name, val in (("c_bg", c_bg), ("c_g0", c_g0), ("c_ch", c_ch)):
            if not (float(val) > 0.0):
                raise ValueError(
                    f"ComplexAffineStampFamily：{name} 须 >0（电纳底）")
        self.n_grid = int(n_grid)
        self.n_blocks = int(n_blocks)
        self.n = self.n_grid * self.n_grid
        self.n_params = self.n_blocks
        self.n_ports = 2
        self.port_z0 = float(port_z0)
        self.lossless = bool(lossless)
        zero_g = 0.0 if self.lossless else 1.0
        self.g_bg = float(g_bg) * zero_g
        self.c_bg = float(c_bg)
        self.g_g0 = float(g_g0) * zero_g
        self.c_g0 = float(c_g0)
        # 通道常数按 k 确定性错开（零 RNG：1+0.5k 因子），给 Y_k 互异的频响形状
        self.g_ch = [float(g_ch) * (1.0 + 0.5 * k) * zero_g
                     for k in range(self.n_blocks)]
        self.c_ch = [float(c_ch) * (1.0 + 0.5 * k)
                     for k in range(self.n_blocks)]
        # 端口=两个对角角点（确定性）
        self._ports = (0, self.n - 1)
        self._opens = tuple(k for k in range(self.n) if k not in self._ports)
        self._edges: list[tuple[int, int, int]] = []
        self._build_edges()

    # ── 边表（构建期一次，确定性） ──
    def _node(self, i: int, j: int) -> int:
        return i * self.n_grid + j

    def _block_of(self, i: int) -> int:
        """边所在列 i → 条带块 id（中点 (i+0.5)/n_grid 等宽划分，右缘闭）。"""
        return min(int((i + 0.5) / self.n_grid * self.n_blocks),
                   self.n_blocks - 1)

    def _build_edges(self) -> None:
        n_g = self.n_grid
        for i in range(n_g - 1):      # 水平边 (i,j)-(i+1,j)
            for j in range(n_g):
                self._edges.append((self._node(i, j), self._node(i + 1, j),
                                    self._block_of(i)))
        for i in range(n_g):          # 垂直边 (i,j)-(i,j+1)
            for j in range(n_g - 1):
                self._edges.append((self._node(i, j), self._node(i, j + 1),
                                    self._block_of(i)))

    # ── 装配（独立路径 _walk：逐边累加，对 λ 仿射、对 ω 经 jω） ──
    def _walk(self, lam: np.ndarray, omega: float) -> np.ndarray:
        v = self._check_lam(lam)
        if not (float(omega) > 0.0) or not math.isfinite(float(omega)):
            raise ValueError("ComplexAffineStampFamily：omega 须为正有限")
        a = np.zeros((self.n, self.n), dtype=complex)
        y_g = self.g_g0 + 1j * float(omega) * self.c_g0
        np.fill_diagonal(a, y_g)
        y_bg = self.g_bg + 1j * float(omega) * self.c_bg
        for ni, nj, blk in self._edges:
            y = y_bg + v[blk] * (self.g_ch[blk]
                                 + 1j * float(omega) * self.c_ch[blk])
            a[ni, ni] += y
            a[nj, nj] += y
            a[ni, nj] -= y
            a[nj, ni] -= y
        return a

    def _check_lam(self, lam: Any) -> np.ndarray:
        v = np.asarray(lam, dtype=float).ravel()
        if v.shape != (self.n_params,):
            raise ValueError(
                f"ComplexAffineStampFamily：λ 须为长度 {self.n_params} 的实向量，"
                f"实得 shape {np.asarray(lam).shape}")
        if not np.all(np.isfinite(v)):
            raise ValueError("ComplexAffineStampFamily：λ 含非有限值（nan/inf）")
        return v

    def _check_freqs(self, freq_hz: Any) -> np.ndarray:
        f = np.asarray(freq_hz, dtype=float).ravel()
        if f.size == 0 or not np.all(np.isfinite(f)) or np.any(f <= 0.0):
            raise ValueError(
                "ComplexAffineStampFamily：freq_hz 须为非空正有限 1-D 序列")
        if np.any(np.diff(f) < 0.0):
            raise ValueError("ComplexAffineStampFamily：freq_hz 须升序")
        return f

    # ── 公开面 ──
    def port_nodes(self) -> tuple[int, int]:
        """端口节点索引（对角角点，确定性）。"""
        return self._ports

    def physical_valid(self, lam: Any) -> bool:
        """λ 是否在无源物理域内（全部 λ_k ≥ 0；负值=有源面，显式旗标）。"""
        v = self._check_lam(lam)
        return bool(np.all(v >= 0.0))

    def basis_matrices(self, omega: float) -> list[np.ndarray]:
        """基矩阵 [Y₀(ω), Y₁(ω), …, Y_K(ω)]（dense complex128）。"""
        y0 = self._walk(np.zeros(self.n_params), omega)
        out = [y0]
        for c in range(self.n_params):
            unit = np.zeros(self.n_params)
            unit[c] = 1.0
            out.append(self._walk(unit, omega) - y0)
        return out

    def system_matrix(self, lam: Any, omega: float) -> np.ndarray:
        """Y(λ,ω)=Y₀(ω)+Σλ_k·Y_k(ω)（基矩阵线性组合单源；dense complex128）。"""
        v = self._check_lam(lam)
        mats = self.basis_matrices(omega)
        m = mats[0].copy()
        for c in range(self.n_params):
            m += v[c] * mats[c + 1]
        return m

    def stamp_affine_residual(self, lam: Any, omega: float) -> float:
        """独立逐边装配 vs 基矩阵线性组合的相对残差（构造性仿射自检量）。"""
        v = self._check_lam(lam)
        walked = self._walk(v, omega)
        combo = self.system_matrix(v, omega)
        scale = float(np.linalg.norm(combo)) or _TINY
        return float(np.linalg.norm(walked - combo) / scale)

    def affine_segment_residual(self, lam: Any, omega: float) -> float:
        """∂Y/∂λ_k≡Y_k 常数性的代数自检：‖Y(λ+e_k)−Y(λ)−Y_k(ω)‖/‖Y_k(ω)‖ 逐 k 最大。"""
        v = self._check_lam(lam)
        mats = self.basis_matrices(omega)
        worst = 0.0
        for c in range(self.n_params):
            shift = v.copy()
            shift[c] += 1.0
            seg = self.system_matrix(shift, omega) - self.system_matrix(v, omega)
            scale = float(np.linalg.norm(mats[c + 1])) or _TINY
            worst = max(worst, float(np.linalg.norm(seg - mats[c + 1]) / scale))
        return worst

    def rhs_probe(self) -> np.ndarray:
        """确定性复数探针源 b = e_{p0} + 0.5j·e_{p1}（GMRES 表/解读出用，零 RNG）。"""
        b = np.zeros(self.n, dtype=complex)
        b[self._ports[0]] = 1.0
        b[self._ports[1]] = 0.5j
        return b

    def solve_s_matrix(self, lam: Any, freq_hz: Any) -> np.ndarray:
        """端接口径精确解 S(λ,ω)：端口行按 V_k+Z_k·I_k=2√Z_k·a_k 端接的
        导纳域线性系统（dense np.linalg.solve——真值通道，逐频独立）。

        推导：功率波口径 V_k=√Z_k(a_k+b_k)、注入电流 I_k=(a_k−b_k)/√Z_k ⇒
        V_k+Z_k·I_k=2√Z_k·a_k；I=Y·V（KCL）⇒ 端口行 e_k+Z_k·Y[k,:]、内部行
        Y[i,:]（无注入）；解出 V 后 S_kp=δ_kp−√Z_k·(Y·V)_k。
        """
        v = self._check_lam(lam)
        f = self._check_freqs(freq_hz)
        sq = math.sqrt(self.port_z0)
        out = np.empty((f.size, self.n_ports, self.n_ports), dtype=complex)
        for fi, fr in enumerate(f):
            y = self.system_matrix(v, 2.0 * math.pi * float(fr))
            a_sys = y.copy()
            for k in self._ports:
                a_sys[k, :] *= self.port_z0
                a_sys[k, k] += 1.0
            b = np.zeros((self.n, self.n_ports), dtype=complex)
            for col, k in enumerate(self._ports):
                b[k, col] = 2.0 * sq
            volts = np.linalg.solve(a_sys, b)
            inj = y @ volts
            out[fi] = np.eye(self.n_ports, dtype=complex) \
                - sq * inj[self._ports, :]
        return out

    def solve_s_matrix_reference(self, lam: Any, freq_hz: Any) -> np.ndarray:
        """独立参考路径：Z=inv(Y)（全网络）→ 仓内单源 ``reduce_to_s_matrix``
        （Z 域同一端接约束方程，内部节点 opens=零注入）——互证裁判用，
        与 ``solve_s_matrix`` 零共享求解路径。"""
        v = self._check_lam(lam)
        f = self._check_freqs(freq_hz)
        omegas = np.array([2.0 * math.pi * float(fr) for fr in f])
        y_stack = np.stack([self.system_matrix(v, float(om)) for om in omegas])
        z_stack = np.linalg.inv(y_stack)
        return reduce_to_s_matrix(z_stack, external=self._ports,
                                  z_ref=(self.port_z0,) * self.n_ports,
                                  opens=self._opens)

    def solution_vector(self, lam: Any, omega: float) -> np.ndarray:
        """节点电压解 x=Y(λ,ω)⁻¹·b_probe（复数精确解——OOD/诊断读出通道）。"""
        v = self._check_lam(lam)
        return np.linalg.solve(self.system_matrix(v, omega), self.rhs_probe())

    def solve_solution_exact(self, lam: Any, omega: float) -> np.ndarray:
        """同 ``solution_vector``（命名对称面——真值通道显式名）。"""
        return self.solution_vector(lam, omega)


# ─── Newton-Schulz 复数 einsum 精修（纯函数 + 受保包装） ────────────────────


def ns_step(a_hat: np.ndarray, m: np.ndarray) -> np.ndarray:
    """单步真 Newton-Schulz：Â⁺=2Â−Â·M·Â（复数 einsum）。

    恒等式 I−Â⁺M=(I−ÂM)²（M 可任意复方阵——逐项展开验证见测试钉）。
    支持批量前导维（(…,n,n)）。"""
    a = np.asarray(a_hat, dtype=complex)
    mat = np.asarray(m, dtype=complex)
    af = np.einsum("...ij,...jk->...ik", a, mat)
    return 2.0 * a - np.einsum("...ij,...jk->...ik", af, a)


# ─── NGO 预测器（系数头 + 逆头，共享确定性协议） ─────────────────────────────


class RfStampPredictor:
    """(λ,ω)→{stamp 系数 λ̂, 近似逆 Â≈Y⁻¹} 的双头小型网络（NGO 最小落地）。

    构造关键字：
        family: ComplexAffineStampFamily（必填）
        lam_bounds: (K,2) 数组（必填；λ 逐轴归一化到 [-1,1]）
        freq_grid_hz: 训练/预测频率栅格（必填，升序正 1-D——栅格锁定，
            预声明简化 2）
        hidden/coef_hidden: 逆头/系数头隐层宽（缺省 32/16）
        seed/lr/epochs_inv/epochs_coef/weight_decay/record_every: 训练旋钮
            （缺省 lr=2e-2、epochs_inv=1500、epochs_coef=800、wd=1e-4）

    双头（同一确定性协议，全批 Adam，固定 seed）：
    - **系数头** ``predict_coefficients``：归一化 λ→归一化 λ̂（恒等目标，
      Model 档 family 自产，预声明简化 1）——denormalize 后即 stamp 系数；
      最终 S 由 Y(λ̂,ω) 精确装配+精确求解出（铁律 7：网络永不直接产生
      S 数值）。
    - **逆头** ``predict_a_hat``：(λ,ω)→Â≈Y(λ,ω)⁻¹（标签=逐 (λ,ω) 精确
      逆，family 自产；逐维标准化）——只作 GMRES 预条件与 NS 精修的
      加速面，永不进最终 S 的数值通道。

    fit 返回 info：coef_rmse_curve/final（归一化空间）、inv_rmse_curve/final
    （标准化空间）、n_samples（(λ,ω) 对数）。
    """

    def __init__(self, family: ComplexAffineStampFamily, *, lam_bounds: Any,
                 freq_grid_hz: Any, hidden: int = 32, coef_hidden: int = 16,
                 seed: int = 20261101, lr: float = 2e-2,
                 epochs_inv: int = 1500, epochs_coef: int = 800,
                 weight_decay: float = 1e-4, record_every: int = 50) -> None:
        if not isinstance(family, ComplexAffineStampFamily):
            raise ValueError(
                "RfStampPredictor：family 须为 ComplexAffineStampFamily")
        self.family = family
        b = np.asarray(lam_bounds, dtype=float)
        if b.ndim != 2 or b.shape != (family.n_params, 2) \
                or not np.all(b[:, 1] > b[:, 0]):
            raise ValueError(
                f"RfStampPredictor：lam_bounds 须为 ({family.n_params},2) "
                "且逐轴 lo<hi")
        self.lam_bounds = b
        fg = np.asarray(freq_grid_hz, dtype=float).ravel()
        family._check_freqs(fg)
        if fg.size < 2:
            raise ValueError("RfStampPredictor：freq_grid_hz 至少 2 点")
        self.freq_grid_hz = fg
        self.f_max = float(fg.max())
        self.hidden = int(hidden)
        self.coef_hidden = int(coef_hidden)
        self.seed = int(seed)
        self.lr = float(lr)
        self.epochs_inv = int(epochs_inv)
        self.epochs_coef = int(epochs_coef)
        self.weight_decay = float(weight_decay)
        self.record_every = int(record_every)
        if self.hidden < 1 or self.coef_hidden < 1 or self.lr <= 0.0 \
                or self.epochs_inv < 1 or self.epochs_coef < 1 \
                or self.record_every < 1:
            raise ValueError(
                "RfStampPredictor：hidden/coef_hidden/epochs_inv/epochs_coef"
                "/record_every 须 ≥1，lr 须 >0")
        self._net_inv: _StampMLP | None = None
        self._net_coef: _StampMLP | None = None
        self._lab_mean: np.ndarray | None = None
        self._lab_std: np.ndarray | None = None
        self._curve_inv: list[float] = []
        self._curve_coef: list[float] = []

    # ── 归一化/校验 ──
    def _norm_lam(self, lam: np.ndarray) -> np.ndarray:
        mid = self.lam_bounds.mean(axis=1)
        half = 0.5 * (self.lam_bounds[:, 1] - self.lam_bounds[:, 0])
        return (lam - mid) / np.where(half > 0.0, half, 1.0)

    def _denorm_lam(self, x: np.ndarray) -> np.ndarray:
        mid = self.lam_bounds.mean(axis=1)
        half = 0.5 * (self.lam_bounds[:, 1] - self.lam_bounds[:, 0])
        return x * np.where(half > 0.0, half, 1.0) + mid

    def _check_lam_row(self, lam: Any) -> np.ndarray:
        v = self.family._check_lam(lam)
        if not self.family.physical_valid(v):
            raise ValueError(
                "RfStampPredictor：λ 越无源物理域（存在 λ_k<0）——训练样本"
                "显式拒绝，不静默收坏样本")
        return v

    # ── 训练 ──
    def fit(self, lam_list: Any) -> dict[str, Any]:
        """双头训练（标签全部 family 自产——Model 档；全批 Adam 确定性）。

        lam_list：无源域内的 λ 行列表。逆头样本=(λ,ω) 对（λ×栅格笛卡尔
        积），标签=Y(λ,ω)⁻¹ 展平复→实（Re|Im 拼接，逐维标准化）；系数头
        样本=λ，标签=归一化 λ（恒等目标，预声明简化 1）。
        """
        if not isinstance(lam_list, (list, tuple)) or not lam_list:
            raise ValueError("RfStampPredictor.fit：lam_list 须非空列表")
        lams = [self._check_lam_row(lam) for lam in lam_list]
        p2 = self.family.n * self.family.n
        # 系数头：恒等目标（归一化空间）
        x_c = np.vstack([self._norm_lam(lam) for lam in lams])
        self._net_coef = _StampMLP(self.family.n_params,
                                   self.family.n_params,
                                   self.coef_hidden, self.seed)
        self._curve_coef = []
        n_c = len(lams)
        for epoch in range(1, self.epochs_coef + 1):
            out = self._net_coef.forward(x_c)
            diff = out - x_c
            rmse = float(np.sqrt(np.mean(diff**2)))
            if epoch % self.record_every == 0 or epoch == self.epochs_coef:
                self._curve_coef.append(rmse)
            self._net_coef.adam_grad_step(x_c, 2.0 * diff / n_c,
                                          self.weight_decay, self.lr)
        # 逆头：(λ,ω) 对 → Y⁻¹
        rows_x: list[np.ndarray] = []
        rows_y: list[np.ndarray] = []
        for lam in lams:
            for fr in self.freq_grid_hz:
                om = 2.0 * math.pi * float(fr)
                inv = np.linalg.inv(self.family.system_matrix(lam, om))
                rows_y.append(np.concatenate([inv.real.ravel(),
                                              inv.imag.ravel()]))
                row = self._norm_lam(lam)
                rows_x.append(np.concatenate([row, [float(fr) / self.f_max]]))
        x_mat = np.vstack(rows_x)
        y_mat = np.vstack(rows_y)
        self._lab_mean = y_mat.mean(axis=0)
        self._lab_std = y_mat.std(axis=0) + 1e-12
        y_std = (y_mat - self._lab_mean) / self._lab_std
        n_out = 2 * p2
        self._net_inv = _StampMLP(x_mat.shape[1], n_out, self.hidden,
                                  self.seed)
        self._curve_inv = []
        n_b = x_mat.shape[0]
        for epoch in range(1, self.epochs_inv + 1):
            out = self._net_inv.forward(x_mat)
            diff = out - y_std
            rmse = float(np.sqrt(np.mean(diff**2)))
            if epoch % self.record_every == 0 or epoch == self.epochs_inv:
                self._curve_inv.append(rmse)
            self._net_inv.adam_grad_step(x_mat, 2.0 * diff / n_b,
                                         self.weight_decay, self.lr)
        return {
            "kind": "ngo_rf_stamp_predictor",
            "n_samples": n_b,
            "n_coef_samples": n_c,
            "n_outputs": n_out,
            "epochs_inv": self.epochs_inv,
            "epochs_coef": self.epochs_coef,
            "seed": self.seed,
            "coef_rmse_final": self._curve_coef[-1],
            "coef_rmse_curve": list(self._curve_coef),
            "inv_rmse_final": self._curve_inv[-1],
            "inv_rmse_curve": list(self._curve_inv),
        }

    # ── 预测/诊断面 ──
    def _freq_row(self, freq_hz: float) -> np.ndarray:
        f = float(freq_hz)
        if not (math.isfinite(f) and f > 0.0):
            raise ValueError("RfStampPredictor：freq_hz 须为正有限标量")
        return np.array([f / self.f_max], dtype=float)

    def predict_coefficients(self, lam: Any) -> np.ndarray:
        """系数头：λ̂（stamp 系数，原始单位，K 维）——最终 S 由 Y(λ̂,ω) 精确
        装配+精确求解出（铁律 7；未 fit 显式报错）。"""
        if self._net_coef is None:
            raise RuntimeError("RfStampPredictor.predict_coefficients：先 fit")
        v = self.family._check_lam(lam)
        x = self._norm_lam(v)[None, :]
        return self._denorm_lam(self._net_coef.forward(x)[0])

    def predict_a_hat(self, lam: Any, freq_hz: float) -> np.ndarray:
        """逆头：Â≈Y(λ,ω)⁻¹（(n,n) 复数；只作 GMRES 预条件/NS 精修加速面）。"""
        if self._net_inv is None or self._lab_mean is None:
            raise RuntimeError("RfStampPredictor.predict_a_hat：先 fit")
        v = self.family._check_lam(lam)
        row = np.concatenate([self._norm_lam(v), self._freq_row(freq_hz)])
        out = self._net_inv.forward(row[None, :])[0]
        n = self.family.n
        denorm = out * self._lab_std + self._lab_mean
        half = n * n
        return (denorm[:half] + 1.0j * denorm[half:]).reshape(n, n)

    def precond_operator(self, lam: Any, freq_hz: float) -> LinearOperator:
        """左预条件算子 M⁻¹v=Â(λ,ω)·v（``gmres_iteration_table`` 同源；
        scipy gmres=左预条件——坑账 ⑫ 源码口径）。"""
        a_hat = self.predict_a_hat(lam, freq_hz)
        n = self.family.n
        return LinearOperator((n, n), matvec=lambda v: a_hat @ v,
                              dtype=complex)

    def neumann_spectral_radius(self, lam: Any, freq_hz: float) -> float:
        """ρ(I−Â(λ,ω)·Y(λ,ω))（左预条件残差传播谱半径；AB/BA 特征多项式
        恒等——量与记法次序无关）。"""
        om = 2.0 * math.pi * float(freq_hz)
        y = self.family.system_matrix(lam, om)
        return float(np.max(np.abs(np.linalg.eigvals(
            np.eye(self.family.n) - self.predict_a_hat(lam, float(freq_hz))
            @ y))))

    def newton_schulz_refine(self, lam: Any, freq_hz: float,
                             rounds: int = 1) -> dict[str, Any]:
        """受保 NS 精修：逐轮 Â⁺=2Â−Â·Y·Â（``ns_step``），仅当
        ‖Â⁺Y−I‖_F<‖ÂY−I‖_F 才采纳（单调不退化守卫；零解标签，data-free
        语义——只用 family 乘积）。

        返回 {"a_hat": 采纳后的 Â（未采纳轮保持原值）, "rounds_taken",
        "residual_trace": [初始, 逐轮后]}。
        """
        if int(rounds) < 1:
            raise ValueError("RfStampPredictor.newton_schulz_refine：rounds ≥1")
        om = 2.0 * math.pi * float(freq_hz)
        y = self.family.system_matrix(lam, om)
        a = self.predict_a_hat(lam, float(freq_hz))
        eye = np.eye(self.family.n, dtype=complex)
        r0 = float(np.linalg.norm(a @ y - eye))
        trace = [r0]
        taken = 0
        for _ in range(int(rounds)):
            a_ns = ns_step(a, y)
            r_ns = float(np.linalg.norm(a_ns @ y - eye))
            if r_ns < trace[-1]:
                a = a_ns
                taken += 1
                trace.append(r_ns)
            else:
                trace.append(trace[-1])
                break
        return {"a_hat": a, "rounds_taken": taken, "residual_trace": trace}


# ─── 黑箱对照臂（OOD 基准：剥离结构先验的唯一受控变量） ──────────────────────


class BlackBoxResponseNet:
    """黑箱 ML 臂：同容量 ``_StampMLP`` 直接 λ→整条 S 响应（无结构先验）。

    与结构臂的唯一受控差异=结构先验剥离（同网络容量、同 seed 协议、同 λ
    集、同训练预算）；输入=归一化 λ（与系数头同输入面），输出=栅格全部
    频点的 S 展平实/虚（逐维标准化）。目标=``family.solve_s_matrix`` 逐点
    精确自产（与逆头标签同通道）。"""
    def __init__(self, family: ComplexAffineStampFamily, *, lam_bounds: Any,
                 freq_grid_hz: Any, hidden: int = 32, seed: int = 20261101,
                 lr: float = 2e-2, epochs: int = 1500,
                 weight_decay: float = 1e-4, record_every: int = 50) -> None:
        if not isinstance(family, ComplexAffineStampFamily):
            raise ValueError(
                "BlackBoxResponseNet：family 须为 ComplexAffineStampFamily")
        self.family = family
        b = np.asarray(lam_bounds, dtype=float)
        if b.ndim != 2 or b.shape != (family.n_params, 2) \
                or not np.all(b[:, 1] > b[:, 0]):
            raise ValueError(
                f"BlackBoxResponseNet：lam_bounds 须为 ({family.n_params},2) "
                "且逐轴 lo<hi")
        self.lam_bounds = b
        fg = np.asarray(freq_grid_hz, dtype=float).ravel()
        family._check_freqs(fg)
        self.freq_grid_hz = fg
        self.hidden = int(hidden)
        self.seed = int(seed)
        self.lr = float(lr)
        self.epochs = int(epochs)
        self.weight_decay = float(weight_decay)
        self.record_every = int(record_every)
        if self.hidden < 1 or self.lr <= 0.0 or self.epochs < 1 \
                or self.record_every < 1:
            raise ValueError(
                "BlackBoxResponseNet：hidden/epochs/record_every 须 ≥1，lr>0")
        self._mid = b.mean(axis=1)
        self._half = np.where(0.5 * (b[:, 1] - b[:, 0]) > 0.0,
                              0.5 * (b[:, 1] - b[:, 0]), 1.0)
        self._net: _StampMLP | None = None
        self._y_mean: np.ndarray | None = None
        self._y_std: np.ndarray | None = None
        self._curve: list[float] = []

    def _norm(self, lam: np.ndarray) -> np.ndarray:
        return (lam - self._mid) / self._half

    def fit(self, lam_list: Any) -> dict[str, Any]:
        """监督训练（标签=family.solve_s_matrix 逐点自产；全批 Adam 确定性）。"""
        if not isinstance(lam_list, (list, tuple)) or not lam_list:
            raise ValueError("BlackBoxResponseNet.fit：lam_list 须非空")
        lams = []
        for lam in lam_list:
            v = self.family._check_lam(lam)
            if not self.family.physical_valid(v):
                raise ValueError(
                    "BlackBoxResponseNet.fit：λ 越无源物理域（存在 λ_k<0）")
            lams.append(v)
        x_mat = np.vstack([self._norm(lam) for lam in lams])
        ys = []
        p_sq = self.family.n_ports * self.family.n_ports
        for lam in lams:
            s = self.family.solve_s_matrix(lam, self.freq_grid_hz)
            ys.append(np.concatenate([s.real.ravel(), s.imag.ravel()]))
        y_mat = np.vstack(ys)
        self._y_mean = y_mat.mean(axis=0)
        self._y_std = y_mat.std(axis=0) + 1e-12
        y_std = (y_mat - self._y_mean) / self._y_std
        n_out = 2 * self.freq_grid_hz.size * p_sq
        self._net = _StampMLP(len(self._mid), n_out, self.hidden, self.seed)
        n_b = len(lams)
        self._curve = []
        for epoch in range(1, self.epochs + 1):
            out = self._net.forward(x_mat)
            diff = out - y_std
            rmse = float(np.sqrt(np.mean(diff**2)))
            if epoch % self.record_every == 0 or epoch == self.epochs:
                self._curve.append(rmse)
            self._net.adam_grad_step(x_mat, 2.0 * diff / n_b,
                                     self.weight_decay, self.lr)
        return {"kind": "ngo_rf_stamp_blackbox", "n_samples": n_b,
                "epochs": self.epochs, "seed": self.seed,
                "label_rmse_final": self._curve[-1],
                "label_rmse_curve": list(self._curve)}

    def predict(self, lam: Any) -> np.ndarray:
        """黑箱 S 预测 (n_freq, P, P)（未 fit 显式报错）。"""
        if self._net is None or self._y_mean is None:
            raise RuntimeError("BlackBoxResponseNet.predict：先 fit")
        v = self.family._check_lam(lam)
        out = self._net.forward(self._norm(v)[None, :])[0]
        denorm = out * self._y_std + self._y_mean
        nf = self.freq_grid_hz.size
        half = nf * self.family.n_ports * self.family.n_ports
        re = denorm[:half].reshape(nf, self.family.n_ports, self.family.n_ports)
        im = denorm[half:].reshape(nf, self.family.n_ports, self.family.n_ports)
        return re + 1.0j * im


# ─── GMRES 预条件迭代数表（复数路径，左预条件——坑账 ⑫ 口径） ────────────────


def gmres_iteration_table(family: ComplexAffineStampFamily,
                          predictor: RfStampPredictor, lam_list: Any,
                          freq_hz: float, *, rtol: float = 1e-8,
                          restart: int | None = None, max_cycles: int = 3,
                          warn_above: float = SPECTRAL_RADIUS_WARN_DEFAULT,
                          ) -> dict[str, Any]:
    """多 λ 采样下 无预条件 vs Â 左预条件 的复数 GMRES 迭代数对照表。

    求解系统：Y(λ,ω)·x=b（b=``family.rhs_probe`` 确定性复数探针源）——
    stamp 线性系统本体（S 提取的底层线性代数）；``freq_hz`` 须在预测器
    栅格附近（栅格锁定语义见预测器 docstring）。每行实测：无预条件/预
    条件迭代数（``callback_type='pr_norm'`` 逐内层迭代计数）、收敛旗标
    （info==0 且末端相对残差复核）、末端相对残差、谱半径 ρ(I−ÂY)、迭代比。
    ρ>warn_above 时显式 ``warnings.warn``（Neumann 收敛警戒，不静默不拦截）
    并登记 ``summary["warnings"]``。同一输入逐位可复现。

    判读语义（预声明）：``halved_fraction``=预条件后迭代数 ≤ 无预条件一半的
    （双方收敛）采样占比；预条件收益**正负都记**（ratio>1 如实行内保留）。
    """
    if not isinstance(lam_list, (list, tuple)) or not lam_list:
        raise ValueError("gmres_iteration_table：lam_list 须非空")
    n = family.n
    restart_eff = int(restart) if restart is not None else n
    if restart_eff < 1 or int(max_cycles) < 1:
        raise ValueError("gmres_iteration_table：restart/max_cycles 须 ≥1")
    b = family.rhs_probe()
    b_norm = float(np.linalg.norm(b)) or _TINY
    rows: list[dict[str, Any]] = []
    warn_list: list[str] = []

    def _run(a_sp, m_op) -> tuple[int, bool, float]:
        cnt = 0

        def _cb(_rel: float) -> None:
            nonlocal cnt
            cnt += 1

        # scipy≥1.12：maxiter=restart 循环数；callback_type='pr_norm' 逐
        # 内层迭代回调；M=左预条件（scipy 源码口径，坑账 ⑫）。
        x, info = gmres(a_sp, b, rtol=rtol, atol=0.0, restart=restart_eff,
                        maxiter=int(max_cycles), M=m_op, callback=_cb,
                        callback_type="pr_norm")
        rel_final = float(np.linalg.norm(b - a_sp @ x)) / b_norm
        return cnt, bool(info == 0 and rel_final <= rtol * (1.0 + 1e-6)), rel_final

    for lam in lam_list:
        v = family._check_lam(lam)
        om = 2.0 * math.pi * float(freq_hz)
        a_sp = sparse.csr_matrix(family.system_matrix(v, om))
        it0, ok0, rel0 = _run(a_sp, None)
        a_hat = predictor.predict_a_hat(v, float(freq_hz))
        mop = LinearOperator((n, n), matvec=lambda x, m=a_hat: m @ x,
                             dtype=complex)
        it1, ok1, rel1 = _run(a_sp, mop)
        rho = float(np.max(np.abs(np.linalg.eigvals(
            np.eye(n) - a_hat @ family.system_matrix(v, om)))))
        row: dict[str, Any] = {
            "lam": [float(t) for t in v],
            "freq_hz": float(freq_hz),
            "iterations_unprecond": it0, "converged_unprecond": ok0,
            "residual_rel_unprecond": rel0,
            "iterations_precond": it1, "converged_precond": ok1,
            "residual_rel_precond": rel1,
            "spectral_radius": rho,
            "ratio": (it1 / it0) if it0 else float("inf"),
        }
        rows.append(row)
        if rho > float(warn_above):
            msg = (
                f"ngo_rf_stamp.gmres_iteration_table：λ={row['lam']} 的预条件"
                f"残差传播谱半径 ρ(I−ÂY)={rho:.4g} > {warn_above}——Neumann "
                "收敛必要条件超界，GMRES 可能发散或不降（实测行如实保留）")
            warnings.warn(msg, UserWarning, stacklevel=2)
            warn_list.append(msg)
    both = [r for r in rows
            if r["converged_unprecond"] and r["converged_precond"]]
    n_halved = sum(1 for r in both
                   if r["iterations_precond"] <= 0.5 * r["iterations_unprecond"])
    summary = {
        "n_cases": len(rows),
        "n_converged_both": len(both),
        "n_halved": n_halved,
        "halved_fraction": (n_halved / len(both)) if both else 0.0,
        "max_ratio": max((r["ratio"] for r in both), default=float("inf")),
        "max_spectral_radius": max(r["spectral_radius"] for r in rows),
        "warnings": warn_list,
    }
    return {"rows": rows, "summary": summary}


# ─── OOD 基准（结构先验分布外价值：系数头+精确求解 vs 黑箱直映） ─────────────


def ood_error_table(family: ComplexAffineStampFamily,
                    predictor: RfStampPredictor, lam_in: Any, lam_ood: Any,
                    *, blackbox: BlackBoxResponseNet | None = None,
                    blackbox_seed: int = 20261101) -> dict[str, Any]:
    """结构臂 vs 黑箱臂的域内/域外 S 响应相对误差对照表。

    结构臂：λ̂=``predict_coefficients``（stamp 系数回归）→ Y(λ̂,ω) 精确
    装配+``solve_s_matrix`` 精确求解——网络误差只活在 K 维系数空间，频率
    响应形状由结构按构造保持（NGO 论点）。黑箱臂缺省内建
    ``BlackBoxResponseNet``（同 lam_in、同 seed/容量/预算，λ→S 直映）。
    真值=``family.solve_s_matrix`` 独立精确通道；
    rel_err=‖Ŝ−S‖_F/‖S‖_F（全栅格栈级）。lam_ood 须为训练 λ 凸包外的
    外推采样（越界由调用方保证——本函数逐点如实报告，不静默域检查；
    λ̂ 须仍在无源域内由调用方自查，非物理预测如实入表）。
    """
    if predictor._net_inv is None or predictor._net_coef is None:
        raise RuntimeError("ood_error_table：predictor 须先 fit")
    lams_in = [family._check_lam(lam) for lam in lam_in]
    lams_ood = [family._check_lam(lam) for lam in lam_ood]
    if not lams_in or not lams_ood:
        raise ValueError("ood_error_table：lam_in/lam_ood 须非空")
    if blackbox is None:
        bb = BlackBoxResponseNet(family, lam_bounds=predictor.lam_bounds,
                                 freq_grid_hz=predictor.freq_grid_hz,
                                 hidden=predictor.hidden,
                                 seed=int(blackbox_seed), lr=predictor.lr,
                                 epochs=predictor.epochs_inv,
                                 weight_decay=predictor.weight_decay)
        bb.fit(lams_in)
    else:
        bb = blackbox
    freqs = predictor.freq_grid_hz
    rows: list[dict[str, Any]] = []
    for region, lams in (("in", lams_in), ("ood", lams_ood)):
        for lam in lams:
            s_true = family.solve_s_matrix(lam, freqs)
            scale = float(np.linalg.norm(s_true)) or _TINY
            lam_hat = predictor.predict_coefficients(lam)
            s_st = family.solve_s_matrix(lam_hat, freqs)
            e_st = float(np.linalg.norm(s_st - s_true)) / scale
            s_bb = bb.predict(lam)
            e_bb = float(np.linalg.norm(s_bb - s_true)) / scale
            rows.append({
                "region": region,
                "lam": [float(t) for t in lam],
                "lam_hat_structure": [float(t) for t in lam_hat],
                "rel_err_structure": e_st, "rel_err_blackbox": e_bb,
            })

    def _agg(region: str, key: str) -> dict[str, float]:
        vals = [r[key] for r in rows if r["region"] == region]
        return {"max": max(vals), "mean": float(np.mean(vals))}

    summary: dict[str, Any] = {}
    for arm, key in (("structure", "rel_err_structure"),
                     ("blackbox", "rel_err_blackbox")):
        summary[arm] = {"in": _agg("in", key), "ood": _agg("ood", key)}
        summary[arm]["degradation_ood_over_in"] = (
            summary[arm]["ood"]["max"]
            / max(summary[arm]["in"]["max"], _TINY))
    return {"rows": rows, "summary": summary}
