"""参数仿射 stamp 系数内核 + NGO 三档最小落地（T-O7，aurora_o 二期）。

定位：把 NGO（Neural Green's Operators，TU/e 2026 CMAME 455:118893，
arXiv 2406.01857，Melchers/Prins/Abdelmalik）的**参数进算子**结构先验落到
确定性合成族上——2D 稳态扩散 5 点 FDM 离散系统对材料参数 λ **构造性精确
仿射**：F(λ) = F0 + Σ_k λ_k·F_k（边电导按块通道线性叠加，F0/F_k 为固定
基矩阵）。网络只学参数依赖 λ→Â(λ)≈F(λ)^{-1}，"解 = 线性系统"的结构按
构造保留，最终数值永远来自精确通道（``AffineStampFamily.solve``）。

论文映射（与 optimization/surrogate/green_operator.py 的 RF 多端口第一席
互补——该席守"激励叠加"结构（读出头构造线性），本席守"参数仿射"结构
（参数进算子），两者正交且零代码耦合）::

    NGO（CMAME 455:118893）              green_stamp（合成族）
    ────────────────────────────────  ─────────────────────────────────────
    线性 PDE 算子 A(λ)（材料参数进     F(λ)=F0+Σλ_k F_k（构造性仿射，
      系统网络）                         SPD，边电导线性叠加）
    格林核 Â(θ)（网络预测）            Â(λ)≈F(λ)^{-1}（小型 MLP 预测）
    解 u = Φ·Â·d(f)                    x = Â·b（b=family 固定确定性源项）
    Model 档（方程+解标签）            标签=Â=F^{-1}（方程已知，family 自产）
    Data 档（仅数据）                  解标签 L2：‖Â(λ)b − x(λ)‖²（固定源）
    Data-free 档（无解标签）           ‖FÂF−F‖_F 代数一致性主项（F 可逆时唯一
                                       极小点 Â=F^{-1}）+ 等价辅项 ‖ÂF−I‖²
                                       （同一极小点、Hessian 条件数改善；预
                                       声明）+ 受保 Newton-Schulz 精修自蒸馏
                                       轮（零解标签，只用 F 乘积，逐样本
                                       单调不退化守卫——见 fit docstring）
    GMRES 预条件 1616→50（Table 4）    左预条件（scipy gmres 源码实证口径——W6-1 审查 P2 修正；谱半径量因 AB/BA 谱恒等预条件效果不变） M⁻¹=Â，多 λ 迭代数对照表
    OOD 6.68% vs FNO 373.59%（Table 2  训练 λ 凸包外 vs 黑箱对照（结构先验
      精神）                             分布外价值，``ood_error_table``）

三档共享同一 Â 表达（同一 ``_StampMLP`` 架构、同一 seed 协议、同一 λ 归一
化与输出尺度；mode 只改损失/标签面）——model 档与 data_free 档架构逐位
同构，model/data 两监督档在相同网络与旋钮下单源训练循环。

预声明简化（与论文差异，如实钉死不静默）：
1. Â 直接预测 n×n 稠密逆矩阵——论文预测格林核在基函数 Φ 下的展开系数；
   本族解实值（稳态扩散），最小形态无基展开，n 小（缺省 25）稠密可行，
   大规模稀疏基展开不在本席。
2. 黑箱 OOD 对照不直接消费注册代理 fno_lite（torch 曲线算子，接口为
   参数→S11 曲线，与 λ→解向量面不同构）：黑箱 ML 臂 = 同容量
   ``_StampMLP``（λ→x 直映——剥离结构先验后的唯一受控变量），黑箱闭式
   臂（poly_ridge 形态：poly2 特征岭回归）在测试内裸 numpy 独立实现
   （#118 裁判独立：基线与被测零共享代码）。
3. 稳态扩散实值族；RF 复数族（Y(λ,ω)=Y₀+Σλ_k Y_k）待三期；Â 的对称性
   不按构造强制（网络原始输出，诚实面）。
4. Data 档监督只经固定源方向 b（‖Âb−x‖²）——单源解标签只能约束 Â 的
   b 方向投影，这是"仅数据"形态的最小诚实语义（论文用多源数据恢复核；
   多源数据面待三期）。
5. Data-free 训练配方为**复合一致性预热 + 受保 Newton-Schulz 精修自蒸馏**
   （任务书 spec 的 ‖FÂF−F‖_F 为主项与报告口径；等价辅项 ‖ÂF−I‖²/n 与
   主项同极小点、条件数改善，纯主项优化平台高一个量级——预声明；NS
   精修只用 F 乘积、零解标签、逐样本单调不退化守卫——data-free 语义
   保持，``family.solve`` 在 data_free 路径零调用）。配方定标证据
   runs/aurora_o/to7_calib/（calib_out.txt + tune*.py 扫描账）。

Neumann 警戒（负例不静默）：左预条件（scipy gmres 源码实证口径——W6-1 审查 P2 修正；谱半径量因 AB/BA 谱恒等预条件效果不变） GMRES 求解 F M⁻¹y=b（M⁻¹v=Âv），
多项式迭代的收敛由残差传播矩阵 I−F(λ)Â(λ) 的谱半径支配——
``gmres_iteration_table`` 逐 λ 实测 ρ(I−FÂ)，超过阈值（缺省 1.0）显式
``warnings.warn``（不静默、不拦截——仍给出实测表供判读），并在
``summary["warnings"]`` 如实登记。

确定性（AGENTS 7 / C4）：全链路固定 seed 的 ``np.random.default_rng``
（不触全局 RNG 态），训练全批 Adam 无采样随机；gmres/splu 数值确定性；
同 seed 同数据两跑 ``predict_a_hat`` 逐位一致（测试钉住）。

分层与零改动（铁律 3/任务书）：core 叶子只 import stdlib+numpy+scipy；
``_StampMLP`` 是 optimization/surrogate/nn_model._MLP 形态先例的 core 自含
复制（core 不可上溯 import optimization——会反向破分层契约）。本模块不注册
代理键、不触既有消费面（纯增量独立件，green_op 契约先例零改动）。

诚实边界：
- 合成族真值=离散线性系统本身（解析构造即定义）；门的裁判走独立数值路径
  （稠密 np.linalg.solve vs 稀疏 splu 互证+残差 ‖Fx−b‖），不外推真机精度；
- data-free 档精度受网络容量/训练预算限制——门在测试预声明（定标证据
  runs/aurora_o/to7_calib/），超界如实降级不凑绿；
- 不提供逐点不确定度（无 σ 面，不伪造）。
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres, splu

__all__ = [
    "SPECTRAL_RADIUS_WARN_DEFAULT",
    "AffineStampFamily",
    "BlackBoxSolutionNet",
    "StampInversePredictor",
    "default_lambda_grid",
    "gmres_iteration_table",
    "ood_error_table",
]

#: 谱半径警戒缺省阈值（Neumann 型必要条件：不动点迭代收敛要求 ρ(I−FÂ)<1；
#: 超界=显式 warning 不静默，GMRES 仍照跑并如实报告收敛面）。
SPECTRAL_RADIUS_WARN_DEFAULT = 1.0

_TINY = 1e-300


# ─── core 自含小型 MLP（nn_model._MLP 形态先例；分层约束见模块 docstring） ──


class _StampMLP:
    """三层全连接（tanh×2 + 线性读出）+ Adam——nn_model._MLP 同构最小面。

    与 _MLP 的差异只有一处：``adam_grad_step`` 直接吃 dL/d(outputs)（已含
    链式系数），使 data-free 代数一致性损失（四阶型 ‖FÂF−F‖²，梯度经两次
    矩阵乘回传）、Data 档解标签损失（经 Âb 外积回传）与监督 L2 共用同一
    网络/优化器单源。
    """

    def __init__(self, n_in: int, n_out: int, hidden: int, seed: int):
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0.0, np.sqrt(2.0 / n_in), (n_in, hidden))
        self.b1 = np.zeros(hidden)
        self.w2 = rng.normal(0.0, np.sqrt(2.0 / hidden), (hidden, hidden))
        self.b2 = np.zeros(hidden)
        self.w3 = rng.normal(0.0, np.sqrt(2.0 / hidden), (hidden, n_out))
        self.b3 = np.zeros(n_out)
        self._params = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]
        self._m = [np.zeros_like(p) for p in self._params]
        self._v = [np.zeros_like(p) for p in self._params]
        self._t = 0

    def forward(self, x: np.ndarray) -> np.ndarray:
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        return h2 @ self.w3 + self.b3

    def grads(self, x: np.ndarray, d_out: np.ndarray, wd: float) -> list:
        """dL/dparams：d_out 已含链式系数（调用方按损失求好）。"""
        h1 = np.tanh(x @ self.w1 + self.b1)
        h2 = np.tanh(h1 @ self.w2 + self.b2)
        g = [None] * 6
        g[5] = d_out.sum(0)
        g[4] = h2.T @ d_out + wd * self.w3
        d_h2 = (d_out @ self.w3.T) * (1.0 - h2**2)
        g[3] = d_h2.sum(0)
        g[2] = h1.T @ d_h2 + wd * self.w2
        d_h1 = (d_h2 @ self.w2.T) * (1.0 - h1**2)
        g[1] = d_h1.sum(0)
        g[0] = x.T @ d_h1 + wd * self.w1
        return g

    def adam_grad_step(self, x: np.ndarray, d_out: np.ndarray, wd: float,
                       lr: float, betas: tuple[float, float] = (0.9, 0.999),
                       eps: float = 1e-8) -> None:
        g = self.grads(x, d_out, wd)
        self._t += 1
        for p, gi, mi, vi in zip(self._params, g, self._m, self._v, strict=True):
            mi *= betas[0]
            mi += (1.0 - betas[0]) * gi
            vi *= betas[1]
            vi += (1.0 - betas[1]) * gi * gi
            m_hat = mi / (1.0 - betas[0] ** self._t)
            v_hat = vi / (1.0 - betas[1] ** self._t)
            p -= lr * m_hat / (np.sqrt(v_hat) + eps)


# ─── 合成族：2D 稳态扩散 FDM 离散系统（构造性参数仿射） ──────────────────────


class AffineStampFamily:
    """F(λ)=F0+Σ_k λ_k·F_k 的 2D 稳态扩散离散系统族（SPD、精确仿射）。

    几何：单位方格 (N+2)×(N+2) 像素、内点 n=N²（N=``n_grid``），Dirichlet
    零边界，5 点差分。边电导 g=κ_e：内点-内点边按其中点 x 坐标归属条带块
    k（κ_e = κ_bg + λ_k），内点-边界边取 κ_bg（只进 F0——材料参数进域内、
    边界通道固定的 NGO 语义）。K=``n_blocks`` 个条带按 x 等宽确定性划分
    （零 RNG）。

    F0/F_k 由同一条带划分经 ``_walk``（独立逐边装配路径）构造，
    ``system_matrix`` 走基矩阵线性组合（消费单源），``stamp_affine_residual``
    实测两路径之差（构造性仿射=代数事实，残差实测只抓实现漂移，浮点求和
    序差留 ulp 底，门 ≤1e-12 相对）。
    """

    def __init__(self, n_grid: int = 5, n_blocks: int = 2,
                 kappa_bg: float = 1.0) -> None:
        if int(n_grid) < 2:
            raise ValueError("AffineStampFamily：n_grid 须 ≥2")
        if int(n_blocks) < 1:
            raise ValueError("AffineStampFamily：n_blocks 须 ≥1")
        if not (float(kappa_bg) > 0.0):
            raise ValueError("AffineStampFamily：kappa_bg 须 >0（SPD 底）")
        self.n_grid = int(n_grid)
        self.n_blocks = int(n_blocks)
        self.kappa_bg = float(kappa_bg)
        self.n = self.n_grid * self.n_grid
        self.n_params = self.n_blocks
        self._interior_edges: list[tuple[int, int, int]] = []
        self._build()

    # ── 装配（独立路径 _walk：逐边累加，消费面走基组合） ──
    def _node(self, i: int, j: int) -> int:
        """内点 (i,j)（0 基）→ 展平索引。"""
        return i * self.n_grid + j

    def _block_of(self, mx_norm: float) -> int:
        """边中点归一化 x 坐标 → 条带块 id（确定性等宽，右缘闭）。"""
        return min(int(mx_norm * self.n_blocks), self.n_blocks - 1)

    def _walk(self, lam: np.ndarray) -> np.ndarray:
        """独立装配路径：逐边累加电导贡献（对 lam 逐边仿射）。"""
        a = np.zeros((self.n, self.n), dtype=float)
        n_g = self.n_grid
        boundary_deg = np.zeros(self.n, dtype=float)
        for i in range(n_g):
            for j in range(n_g):
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ii, jj = i + di, j + dj
                    if not (0 <= ii < n_g and 0 <= jj < n_g):
                        boundary_deg[self._node(i, j)] += self.kappa_bg
        for i in range(n_g - 1):  # 水平内边：(i,j)-(i+1,j)，块按中点 x
            for j in range(n_g):
                blk = self._block_of((i + 0.5) / n_g)
                g = self.kappa_bg + float(lam[blk])
                ni, nj = self._node(i, j), self._node(i + 1, j)
                a[ni, ni] += g
                a[nj, nj] += g
                a[ni, nj] -= g
                a[nj, ni] -= g
                self._interior_edges.append((ni, nj, blk))
        for i in range(n_g):  # 垂直内边：(i,j)-(i,j+1)，块按中点 x（同 i）
            for j in range(n_g - 1):
                blk = self._block_of((i + 0.5) / n_g)
                g = self.kappa_bg + float(lam[blk])
                ni, nj = self._node(i, j), self._node(i, j + 1)
                a[ni, ni] += g
                a[nj, nj] += g
                a[ni, nj] -= g
                a[nj, ni] -= g
                self._interior_edges.append((ni, nj, blk))
        np.fill_diagonal(a, a.diagonal() + boundary_deg)
        return a

    def _build(self) -> None:
        self._f0 = self._walk(np.zeros(self.n_params))
        self._fk: list[np.ndarray] = []
        for c in range(self.n_params):
            unit = np.zeros(self.n_params)
            unit[c] = 1.0
            self._fk.append(self._walk(unit) - self._f0)  # 纯块通道基矩阵
        self._rhs = np.zeros(self.n, dtype=float)
        mid = self.n_grid // 2
        self._rhs[self._node(mid, mid)] = 1.0  # 中心单位点源（确定性）

    # ── 公开面 ──
    def basis_matrices(self) -> list[np.ndarray]:
        """基矩阵 [F0, F_1, …, F_K]（dense float64）。"""
        return [self._f0, *self._fk]

    def system_matrix(self, lam: Any, *, sparse_out: bool = False):
        """F(λ)=F0+Σλ_k F_k（基矩阵线性组合单源）；``sparse_out=True`` 给 CSR。"""
        v = self._check_lam(lam)
        m = self._f0.copy()
        for c in range(self.n_params):
            m += v[c] * self._fk[c]
        return sparse.csr_matrix(m) if sparse_out else m

    def stamp_affine_residual(self, lam: Any) -> float:
        """独立逐边装配 vs 基矩阵线性组合的相对残差（构造性仿射自检量）。"""
        v = self._check_lam(lam)
        walked = self._walk(v)
        combo = self.system_matrix(v)
        scale = float(np.linalg.norm(combo)) or _TINY
        return float(np.linalg.norm(walked - combo) / scale)

    def min_conductance(self, lam: Any) -> float:
        """最小边电导 min_e(κ_bg+λ_blk(e))（物理域：>0 ⇔ SPD 连通）。"""
        v = self._check_lam(lam)
        vals = [self.kappa_bg]
        for _, _, blk in self._interior_edges:
            vals.append(self.kappa_bg + v[blk])
        return float(min(vals))

    def physical_valid(self, lam: Any) -> bool:
        """λ 是否在物理域内（全部边电导 >0；域外 F 非 SPD，显式旗标）。"""
        return bool(self.min_conductance(lam) > 0.0)

    def rhs(self) -> np.ndarray:
        """固定确定性源项 b（中心单位点源；零 RNG）。"""
        return self._rhs.copy()

    def solve(self, lam: Any) -> np.ndarray:
        """精确解 x=F(λ)⁻¹b（稀疏 splu——真值通道，线性求解为确定性内核）。"""
        m = self.system_matrix(lam, sparse_out=True)
        return splu(sparse.csc_matrix(m)).solve(self._rhs)

    def solve_dense(self, lam: Any) -> np.ndarray:
        """稠密 np.linalg.solve 独立路径（裁判互证用，与 solve 零共享求解器）。"""
        return np.linalg.solve(self.system_matrix(lam), self._rhs)

    def _check_lam(self, lam: Any) -> np.ndarray:
        v = np.asarray(lam, dtype=float).ravel()
        if v.shape != (self.n_params,):
            raise ValueError(
                f"AffineStampFamily：λ 须为长度 {self.n_params} 的实向量，"
                f"实得 shape {np.asarray(lam).shape}")
        if not np.all(np.isfinite(v)):
            raise ValueError("AffineStampFamily：λ 含非有限值（nan/inf）")
        return v


# ─── λ 采样（确定性网格，零 RNG） ────────────────────────────────────────────


def default_lambda_grid(lam_bounds: Any, n_per_axis: int = 5,
                        max_points: int = 64) -> list[np.ndarray]:
    """bounds 内确定性均匀网格（逐轴 linspace 笛卡尔积；超 max_points 按
    等距下标确定性抽稀）。K 维泛化（K≥1）；点集与顺序只依赖输入。"""
    b = np.asarray(lam_bounds, dtype=float)
    if b.ndim != 2 or b.shape[1] != 2 or not np.all(b[:, 1] > b[:, 0]):
        raise ValueError("default_lambda_grid：lam_bounds 须为 (K,2) 且 lo<hi")
    if int(n_per_axis) < 2 or int(max_points) < 2:
        raise ValueError("default_lambda_grid：n_per_axis/max_points 须 ≥2")
    axes = [np.linspace(lo, hi, int(n_per_axis)) for lo, hi in b]
    mesh = np.stack(np.meshgrid(*axes, indexing="ij"),
                    axis=-1).reshape(-1, b.shape[0])
    if len(mesh) > int(max_points):
        idx = np.unique(np.round(
            np.linspace(0.0, len(mesh) - 1.0, int(max_points))).astype(int))
        mesh = mesh[idx]
    return [row.copy() for row in mesh]


# ─── NGO 三档预测器（共享 Â 表达） ───────────────────────────────────────────


class StampInversePredictor:
    """λ→Â(λ)≈F(λ)^{-1} 的小型网络（三档共享，NGO 最小落地）。

    构造关键字：
        lam_bounds: (K,2) 数组（必填；λ 逐轴归一化到 [-1,1]）
        mode: "model"（方程已知：标签=Â=F^{-1}，family 自产）| "data"
            （解标签 L2：‖Âb−x‖²，固定源方向）| "data_free"（缺省：
            代数一致性，无解标签——训练配方见下）
        hidden/seed/lr/epochs/weight_decay/record_every: 监督档训练旋钮
            （lr 缺省 2e-2、epochs 缺省 600）
        data_free 专用旋钮（预声明配方，定标证据 runs/aurora_o/to7_calib/）：
            warm_lr=5e-2 / warm_epochs=3000（复合一致性预热）；
            aux_weight=5.0（等价辅项 ‖ÂF−I‖²/n 的权重；0=纯 spec 主项——
            收敛慢一个量级，辅项与主项同极小点，预声明差异）；
            distill_rounds=1 / distill_epochs=800（受保 NS 精修自蒸馏轮，
            蒸馏轮学习率=lr）；grid_per_axis=5（samples=None 时缺省 λ 网格
            每轴点数）

    data-free 训练配方（全程零解标签、``family.solve`` 零调用）：
      1. 预热：复合代数一致性 L=mean_i[‖F_iÂ_iF_i−F_i‖²/‖F_i‖²_F +
         aux_weight·‖Â_iF_i−I‖²/n]——主项即任务书/论文 spec 的 ‖FÂF−F‖_F
         （逐样本相对化）；辅项与主项**同一唯一极小点**（F 可逆时
         FÂF=F ⇔ ÂF=I）而 Hessian 条件数从 σ_min⁴ 量级降到 σ_min² 量级
         （定标实测：纯主项 6000 epoch 残差平台 ~0.07，复合后 ~0.04 且
         ρ(I−FÂ) 0.9→0.15）。
      2. 受保 Newton-Schulz 精修自蒸馏轮：对每个训练 λ 取当前 Â 的单步
         NS 迭代目标 Â⁺=2Â−ÂFÂ（只用 F 乘积，零解标签；I−FÂ⁺=(I−FÂ)²
         谱半径平方收缩），**逐样本实测** ‖Â⁺F−I‖<‖ÂF−I‖ 才收进目标
         （单调不退化守卫；‖I−FÂ‖₂≥1 时 NS 目标被守卫自动拒绝），回归
         网络到守卫后目标（distill_epochs @ lr）。

    fit 返回 info：data_free 带 ``consistency_residual_curve``（全程逐
    record 的 max 相对一致性残差 ‖FÂF−F‖_F/‖F‖_F——验收①下降曲线证据
    面）、``consistency_residual_final``、``distill_taken``（守卫采纳的
    NS 目标样本数）；监督档带 ``label_rmse_curve``/``label_rmse_final``
    与 ``label_kind``（"a_hat"|"solution"，标签语义如实声明）。
    """

    _MODES = ("model", "data", "data_free")

    def __init__(self, family: AffineStampFamily, *, lam_bounds: Any,
                 mode: str = "data_free", hidden: int = 32,
                 seed: int = 20261101, lr: float = 2e-2, epochs: int = 600,
                 weight_decay: float = 0.0, record_every: int = 50,
                 warm_lr: float = 5e-2, warm_epochs: int = 3000,
                 aux_weight: float = 5.0, distill_rounds: int = 1,
                 distill_epochs: int = 800, grid_per_axis: int = 5) -> None:
        if not isinstance(family, AffineStampFamily):
            raise ValueError(
                "StampInversePredictor：family 须为 AffineStampFamily")
        self.family = family
        b = np.asarray(lam_bounds, dtype=float)
        if b.ndim != 2 or b.shape != (family.n_params, 2) \
                or not np.all(b[:, 1] > b[:, 0]):
            raise ValueError(
                f"StampInversePredictor：lam_bounds 须为 ({family.n_params},2) "
                "且逐轴 lo<hi")
        self.lam_bounds = b
        if mode not in self._MODES:
            raise ValueError(
                f"StampInversePredictor：mode 须为 {self._MODES}，实得 {mode!r}")
        self.mode = mode
        self.hidden = int(hidden)
        self.seed = int(seed)
        self.lr = float(lr)
        self.epochs = int(epochs)
        self.weight_decay = float(weight_decay)
        self.record_every = int(record_every)
        self.warm_lr = float(warm_lr)
        self.warm_epochs = int(warm_epochs)
        self.aux_weight = float(aux_weight)
        self.distill_rounds = int(distill_rounds)
        self.distill_epochs = int(distill_epochs)
        self.grid_per_axis = int(grid_per_axis)
        if self.hidden < 1 or self.epochs < 1 or self.lr <= 0.0 \
                or self.record_every < 1 or self.warm_lr <= 0.0 \
                or self.warm_epochs < 1 or self.aux_weight < 0.0 \
                or self.distill_rounds < 0 or self.distill_epochs < 1 \
                or self.grid_per_axis < 2:
            raise ValueError(
                "StampInversePredictor：hidden/epochs/record_every/"
                "warm_epochs/distill_epochs/grid_per_axis 须 ≥1（grid_per_axis"
                " ≥2），lr/warm_lr 须 >0，aux_weight ≥0，distill_rounds ≥0")
        # Â 输出尺度：逆矩阵条目 ~1/κ——固定取 1/κ_bg（无标签档不能依赖
        # 标签统计；三档共享同一表达式 ⇒ 统一固定尺度，预声明）。
        self._out_scale = 1.0 / self.family.kappa_bg
        self._net: _StampMLP | None = None
        self._curve: list[float] = []

    # ── 归一化/校验 ──
    def _norm(self, lam: np.ndarray) -> np.ndarray:
        mid = self.lam_bounds.mean(axis=1)
        half = 0.5 * (self.lam_bounds[:, 1] - self.lam_bounds[:, 0])
        return (lam - mid) / np.where(half > 0.0, half, 1.0)

    def _check_lam_row(self, lam: Any) -> np.ndarray:
        v = self.family._check_lam(lam)  # 长度/有限性单源校验
        if not self.family.physical_valid(v):
            raise ValueError(
                "StampInversePredictor：λ 越物理域（存在边电导 ≤0，F 非 SPD）"
                "——训练样本显式拒绝，不静默收坏样本")
        return v

    def _raw_lams(self, samples: list[dict[str, Any]] | None) -> list:
        if samples is None:
            return default_lambda_grid(self.lam_bounds,
                                       n_per_axis=self.grid_per_axis)
        if not isinstance(samples, list) or not samples:
            raise ValueError("StampInversePredictor.fit：samples 须非空列表")
        rows: list[np.ndarray] = []
        for k, s in enumerate(samples):
            if not isinstance(s, dict) or "lam" not in s:
                raise ValueError(
                    f"StampInversePredictor.fit：samples[{k}] 缺 'lam' 键")
            rows.append(self._check_lam_row(s["lam"]))
        return rows

    def _inv_labels(self, lams: list) -> np.ndarray:
        """model 档标签：Â=F^{-1} 展平（列解自产；方程已知语义）。"""
        n = self.family.n
        y = np.empty((len(lams), n * n), dtype=float)
        eye = np.eye(n)
        for r, lam in enumerate(lams):
            m = self.family.system_matrix(lam, sparse_out=True)
            y[r] = splu(sparse.csc_matrix(m)).solve(eye).ravel()
        return y / self._out_scale

    # ── data_free 内部：复合一致性预热 + 受保 NS 自蒸馏 ──
    def _fit_data_free(self, x_mat: np.ndarray, f_mat: np.ndarray,
                       f_norm: np.ndarray, n_batch: int, n: int) -> None:
        eye = np.eye(n)
        s = self._out_scale

        def primary_max() -> float:
            out = self._net.forward(x_mat)
            a = (s * out).reshape(n_batch, n, n)
            inner = np.einsum("lij,ljk->lik", f_mat, a)
            r = np.einsum("lij,ljk->lik", inner, f_mat) - f_mat
            rel = np.linalg.norm(r.reshape(n_batch, -1), axis=1) / f_norm
            return float(rel.max())

        # 1) 预热：主项（spec）+ 等价辅项（同极小点、条件数改善，预声明）
        for epoch in range(1, self.warm_epochs + 1):
            out = self._net.forward(x_mat)
            a = (s * out).reshape(n_batch, n, n)
            inner = np.einsum("lij,ljk->lik", f_mat, a)
            r_mat = np.einsum("lij,ljk->lik", inner, f_mat) - f_mat
            e_mat = np.einsum("lij,ljk->lik", a, f_mat) - eye
            rel = np.linalg.norm(r_mat.reshape(n_batch, -1), axis=1) / f_norm
            t1 = np.einsum("lji,ljk->lik", f_mat, r_mat)
            da1 = np.einsum("lij,lkj->lik", t1, f_mat) / f_norm[:, None, None]
            da2 = np.einsum("lij,lkj->lik", e_mat, f_mat) / np.sqrt(n)
            d_out = (s * 2.0 / n_batch) * (da1 + self.aux_weight * da2).reshape(
                n_batch, n * n)
            if epoch % self.record_every == 0 or epoch == self.warm_epochs:
                self._curve.append(float(rel.max()))
            self._net.adam_grad_step(x_mat, d_out, self.weight_decay,
                                     self.warm_lr)
        # 2) 受保 NS 精修自蒸馏轮（目标逐样本单调不退化守卫）
        self._distill_taken = 0
        for _rd in range(self.distill_rounds):
            out = self._net.forward(x_mat)
            a = (s * out).reshape(n_batch, n, n)
            e_cur = np.linalg.norm(
                (np.einsum("lij,ljk->lik", a, f_mat) - eye).reshape(
                    n_batch, -1), axis=1)
            # 真 Newton-Schulz：Â_new = 2Â − Â·F·Â（满足 docstring 声称的
            # I−FÂ_new = (I−FÂ)² 恒等式；W6-1 审查 P1-2 实证此前 F·Â² 形态
            # 不满足该恒等式且精修效率低——einsum 修正式）。
            af = np.einsum("lij,ljk->lik", a, f_mat)
            a_ns = 2.0 * a - np.einsum("lij,ljk->lik", af, a)
            e_ns = np.linalg.norm(
                (np.einsum("lij,ljk->lik", a_ns, f_mat) - eye).reshape(
                    n_batch, -1), axis=1)
            y_mat = out.copy()
            take = e_ns < e_cur
            y_mat[take] = a_ns[take].reshape(-1, n * n)
            self._distill_taken += int(take.sum())
            for epoch in range(1, self.distill_epochs + 1):
                o2 = self._net.forward(x_mat)
                if epoch % self.record_every == 0 \
                        or epoch == self.distill_epochs:
                    self._curve.append(primary_max())
                self._net.adam_grad_step(x_mat, 2.0 * (o2 - y_mat) / n_batch,
                                         self.weight_decay, self.lr)

    # ── 训练（三档单源循环） ──
    def fit(self, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """三档训练（全批 Adam，确定性；档语义/配方见类 docstring）。

        samples 行格式：{"lam": 序列(K)}；data 档另须 "solution"（长度 n
        的解标签，形状/有限性显式校验）。data_free 档忽略 "solution"
        （无解标签语义——传不传逐位一致，测试钉住）。samples=None 时用
        ``default_lambda_grid`` 确定性网格（model/data_free 档合法；data
        档必须外给解标签样本，缺样本显式报错）。
        """
        lams = self._raw_lams(samples)
        x_mat = np.vstack([self._norm(r) for r in lams])
        n = self.family.n
        n_batch = len(lams)
        self._net = _StampMLP(self.family.n_params, n * n, self.hidden,
                              self.seed)
        self._curve = []
        self._distill_taken = 0
        if self.mode == "data" and samples is None:
            raise ValueError(
                "StampInversePredictor.fit：data 档须外给解标签 samples"
                "（lam+solution），缺样本显式报错")
        y_mat: np.ndarray | None = None
        x_lab: np.ndarray | None = None
        label_kind: str | None = None
        if self.mode == "data_free":
            f_mat = np.stack([self.family.system_matrix(lam) for lam in lams])
            f_norm = np.linalg.norm(f_mat, axis=(1, 2))
            self._fit_data_free(x_mat, f_mat, f_norm, n_batch, n)
            info: dict[str, Any] = {
                "kind": "ngo_stamp_kernel",
                "mode": self.mode,
                "n_samples": n_batch,
                "n_outputs": n * n,
                "warm_epochs": self.warm_epochs,
                "distill_rounds": self.distill_rounds,
                "distill_taken": self._distill_taken,
                "aux_weight": self.aux_weight,
                "seed": self.seed,
                "label_kind": None,
                "consistency_residual_final": self._curve[-1],
                "consistency_residual_curve": list(self._curve),
            }
            return info
        if self.mode == "model":
            y_mat = self._inv_labels(lams)
            label_kind = "a_hat"
        else:
            x_lab = np.empty((n_batch, n), dtype=float)
            for k, s in enumerate(samples or []):
                v = np.asarray(s.get("solution"), dtype=float).ravel()
                if v.shape != (n,) or not np.all(np.isfinite(v)):
                    raise ValueError(
                        f"StampInversePredictor.fit：samples[{k}] 的 "
                        f"'solution' 须为长度 {n} 的有限实向量")
                x_lab[k] = v
            label_kind = "solution"
        b_vec = self.family.rhs()
        s = self._out_scale
        for epoch in range(1, self.epochs + 1):
            out = self._net.forward(x_mat)
            if self.mode == "model":
                diff = out - y_mat
                metric = float(np.sqrt(np.mean(diff**2)))
                d_out = 2.0 * diff / n_batch
            else:
                a_mat = (s * out).reshape(n_batch, n, n)
                resid = np.einsum("lij,j->li", a_mat, b_vec) - x_lab
                metric = float(np.sqrt(np.mean(resid**2)))
                # dL/dÂ_i = 2·(Â_i b − x_i)bᵀ/n_batch；链式乘 s。
                d_out = (s * 2.0 / n_batch) * np.einsum(
                    "li,j->lij", resid, b_vec).reshape(n_batch, n * n)
            if epoch % self.record_every == 0 or epoch == self.epochs:
                self._curve.append(metric)
            self._net.adam_grad_step(x_mat, d_out, self.weight_decay, self.lr)
        return {
            "kind": "ngo_stamp_kernel",
            "mode": self.mode,
            "n_samples": n_batch,
            "n_outputs": n * n,
            "epochs": self.epochs,
            "seed": self.seed,
            "label_kind": label_kind,
            "label_rmse_final": self._curve[-1],
            "label_rmse_curve": list(self._curve),
        }

    # ── 预测/诊断面 ──
    def predict_a_hat(self, lam: Any) -> np.ndarray:
        """Â(λ)：预测 (n,n) 近似逆矩阵（三档共享表达式）。"""
        if self._net is None:
            raise RuntimeError("StampInversePredictor.predict_a_hat：先 fit")
        v = self.family._check_lam(lam)
        out = self._net.forward(self._norm(v)[None, :])[0]
        return (self._out_scale * out).reshape(self.family.n, self.family.n)

    def solution_estimate(self, lam: Any) -> np.ndarray:
        """结构档解估计 x̂=Â(λ)·b（线性读出按构造——green_op 叠加先例同型）。"""
        return self.predict_a_hat(lam) @ self.family.rhs()

    def precond_operator(self, lam: Any) -> LinearOperator:
        """左预条件（scipy gmres 源码实证口径——W6-1 审查 P2 修正；谱半径量因 AB/BA 谱恒等预条件效果不变）算子 M⁻¹v=Â(λ)·v（``gmres_iteration_table`` 同源）。"""
        a_hat = self.predict_a_hat(lam)
        n = self.family.n
        return LinearOperator((n, n), matvec=lambda v: a_hat @ v, dtype=float)

    def neumann_spectral_radius(self, lam: Any) -> float:
        """ρ(I−F(λ)Â(λ))（左预条件（scipy gmres 源码实证口径——W6-1 审查 P2 修正；谱半径量因 AB/BA 谱恒等预条件效果不变）残差传播谱半径——Neumann 警戒实测面）。"""
        f = self.family.system_matrix(lam)
        return float(np.max(np.abs(np.linalg.eigvals(
            np.eye(self.family.n) - f @ self.predict_a_hat(lam)))))


# ─── 黑箱对照臂（OOD 基准；fno_lite 形态映射见模块 docstring 预声明简化） ──


class BlackBoxSolutionNet:
    """黑箱 ML 臂：同容量 ``_StampMLP`` 直接 λ→x（无 Â 结构先验）。

    与结构档的唯一受控差异=结构先验剥离（同网络容量、同 seed 协议、同 λ
    集、同训练预算）；标签=解向量（须逐点精确求解——data-free 结构档免
    解标签恰为对照点）。目标逐分量标准化（有标签可用——与结构档固定尺度
    不同，预声明差异）。
    """

    def __init__(self, family: AffineStampFamily, *, lam_bounds: Any,
                 hidden: int = 32, seed: int = 20261101, lr: float = 2e-2,
                 epochs: int = 600, weight_decay: float = 1e-8,
                 record_every: int = 50) -> None:
        if not isinstance(family, AffineStampFamily):
            raise ValueError("BlackBoxSolutionNet：family 须为 AffineStampFamily")
        self.family = family
        b = np.asarray(lam_bounds, dtype=float)
        if b.ndim != 2 or b.shape != (family.n_params, 2) \
                or not np.all(b[:, 1] > b[:, 0]):
            raise ValueError(
                f"BlackBoxSolutionNet：lam_bounds 须为 ({family.n_params},2) "
                "且逐轴 lo<hi")
        self.lam_bounds = b
        self.hidden = int(hidden)
        self.seed = int(seed)
        self.lr = float(lr)
        self.epochs = int(epochs)
        self.weight_decay = float(weight_decay)
        self.record_every = int(record_every)
        if self.hidden < 1 or self.epochs < 1 or self.lr <= 0.0 \
                or self.record_every < 1:
            raise ValueError(
                "BlackBoxSolutionNet：hidden/epochs/record_every 须 ≥1，lr>0")
        self._mid = b.mean(axis=1)
        self._half = np.where(0.5 * (b[:, 1] - b[:, 0]) > 0.0,
                              0.5 * (b[:, 1] - b[:, 0]), 1.0)
        self._net: _StampMLP | None = None
        self._x_mean = np.zeros(family.n)
        self._x_std = np.ones(family.n)

    def _norm(self, lam: np.ndarray) -> np.ndarray:
        return (lam - self._mid) / self._half

    def fit(self, lam_list: Any) -> dict[str, Any]:
        """监督训练（标签=family.solve 逐点自产；全批 Adam 确定性）。"""
        lams = [np.asarray(lam, dtype=float) for lam in lam_list]
        if not lams:
            raise ValueError("BlackBoxSolutionNet.fit：lam_list 须非空")
        for lam in lams:
            self.family._check_lam(lam)
        x_mat = np.vstack([self._norm(lam) for lam in lams])
        x_true = np.stack([self.family.solve(lam) for lam in lams])
        self._x_mean = x_true.mean(axis=0)
        self._x_std = x_true.std(axis=0) + 1e-12
        y_mat = (x_true - self._x_mean) / self._x_std
        n_batch = len(lams)
        self._net = _StampMLP(self.family.n_params, self.family.n,
                              self.hidden, self.seed)
        curve: list[float] = []
        for epoch in range(1, self.epochs + 1):
            out = self._net.forward(x_mat)
            diff = out - y_mat
            rmse = float(np.sqrt(np.mean(diff**2)))
            if epoch % self.record_every == 0 or epoch == self.epochs:
                curve.append(rmse)
            self._net.adam_grad_step(x_mat, 2.0 * diff / n_batch,
                                     self.weight_decay, self.lr)
        return {"kind": "green_stamp_blackbox", "n_samples": n_batch,
                "epochs": self.epochs, "seed": self.seed,
                "label_rmse_final": curve[-1], "label_rmse_curve": curve}

    def predict(self, lam: Any) -> np.ndarray:
        """黑箱解预测 x̂(λ)（n 维解向量直映；未 fit 显式报错）。"""
        if self._net is None:
            raise RuntimeError("BlackBoxSolutionNet.predict：先 fit")
        v = self.family._check_lam(lam)
        out = self._net.forward(self._norm(v)[None, :])[0]
        return out * self._x_std + self._x_mean


# ─── GMRES 预条件演示（论文 Table 4 形态映射） ──────────────────────────────


def gmres_iteration_table(family: AffineStampFamily,
                          predictor: StampInversePredictor, lam_list: Any,
                          *, rtol: float = 1e-8, restart: int | None = None,
                          max_cycles: int = 3,
                          warn_above: float = SPECTRAL_RADIUS_WARN_DEFAULT,
                          ) -> dict[str, Any]:
    """多 λ 采样下 无预条件 vs Â 左预条件（scipy gmres 源码实证口径——W6-1 审查 P2 修正；谱半径量因 AB/BA 谱恒等预条件效果不变） 的 GMRES 迭代数对照表。

    每行实测：无预条件迭代数 / 预条件迭代数（``callback_type='pr_norm'``
    逐内层迭代计数）、收敛旗标（info==0 且末端相对残差复核）、末端相对
    残差、谱半径 ρ(I−FÂ)、迭代比。ρ>warn_above 时显式 ``warnings.warn``
    （Neumann 收敛警戒，不静默不拦截）并登记 ``summary["warnings"]``。
    同一 (family, predictor, lam_list) 输入逐位可复现。

    判读语义（预声明）：``halved_fraction`` = 预条件后迭代数 ≤ 无预条件
    一半的（双方收敛）采样占比——论文 Table 4"迭代数大幅下降"的合成族
    最小形态映射（不承诺论文同量级 1616→50）。
    """
    lams = [np.asarray(lam, dtype=float) for lam in lam_list]
    if not lams:
        raise ValueError("gmres_iteration_table：lam_list 须非空")
    n = family.n
    restart_eff = int(restart) if restart is not None else n
    if restart_eff < 1 or int(max_cycles) < 1:
        raise ValueError("gmres_iteration_table：restart/max_cycles 须 ≥1")
    b = family.rhs()
    b_norm = float(np.linalg.norm(b)) or _TINY
    rows: list[dict[str, Any]] = []
    warn_list: list[str] = []

    def _run(a_sp, m_op) -> tuple[int, bool, float]:
        cnt = 0

        def _cb(_rel: float) -> None:
            nonlocal cnt
            cnt += 1

        # scipy≥1.12：maxiter=restart 循环数；callback_type='pr_norm' 逐
        # 内层迭代回调。
        x, info = gmres(a_sp, b, rtol=rtol, atol=0.0, restart=restart_eff,
                        maxiter=int(max_cycles), M=m_op, callback=_cb,
                        callback_type="pr_norm")
        rel_final = float(np.linalg.norm(b - a_sp @ x)) / b_norm
        return cnt, bool(info == 0 and rel_final <= rtol * (1.0 + 1e-6)), rel_final

    for lam in lams:
        family._check_lam(lam)
        a_sp = family.system_matrix(lam, sparse_out=True)
        a_hat = predictor.predict_a_hat(lam)
        it0, ok0, rel0 = _run(a_sp, None)
        mop = LinearOperator((n, n), matvec=lambda v, m=a_hat: m @ v,
                             dtype=float)
        it1, ok1, rel1 = _run(a_sp, mop)
        rho = float(np.max(np.abs(np.linalg.eigvals(
            np.eye(n) - family.system_matrix(lam) @ a_hat))))
        row: dict[str, Any] = {
            "lam": [float(t) for t in np.asarray(lam).ravel()],
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
                f"green_stamp.gmres_iteration_table：λ={row['lam']} 的预条件"
                f"残差传播谱半径 ρ(I−FÂ)={rho:.4g} > {warn_above}——Neumann "
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


# ─── OOD 基准（论文 Table 2 精神：结构先验分布外价值） ──────────────────────


def ood_error_table(family: AffineStampFamily,
                    predictor: StampInversePredictor, lam_in: Any,
                    lam_ood: Any, *,
                    blackbox: BlackBoxSolutionNet | None = None,
                    blackbox_seed: int = 20261101) -> dict[str, Any]:
    """结构档 vs 黑箱 ML 臂的域内/域外相对误差对照表。

    predictor 须已 fit（任意档——结构先验 = Â 表达 + 线性读出）；黑箱臂
    缺省内建 ``BlackBoxSolutionNet``（同 lam_in、同 seed/lr/epochs/容量，
    标签=逐点精确解）。真值=``family.solve`` 独立通道；
    rel_err=‖x̂−x‖₂/‖x‖₂。lam_ood 为训练 λ 凸包外的外推采样（越界由调用
    方保证——本函数逐点如实报告，不静默域检查）。summary 给出
    structure/blackbox × in/ood 的 max/mean 与退化比（ood/in，黑箱退化
    更猛=结构先验 OOD 价值的直接读数）。
    """
    if predictor._net is None:
        raise RuntimeError("ood_error_table：predictor 须先 fit")
    lams_in = [np.asarray(lam, dtype=float) for lam in lam_in]
    lams_ood = [np.asarray(lam, dtype=float) for lam in lam_ood]
    if not lams_in or not lams_ood:
        raise ValueError("ood_error_table：lam_in/lam_ood 须非空")
    if blackbox is None:
        bb = BlackBoxSolutionNet(family, lam_bounds=predictor.lam_bounds,
                                 hidden=predictor.hidden,
                                 seed=int(blackbox_seed), lr=predictor.lr,
                                 epochs=predictor.epochs,
                                 weight_decay=predictor.weight_decay)
        bb.fit(lams_in)
    else:
        bb = blackbox
    rows: list[dict[str, Any]] = []
    for region, lams in (("in", lams_in), ("ood", lams_ood)):
        for lam in lams:
            x_true = family.solve(lam)
            scale = float(np.linalg.norm(x_true)) or _TINY
            e_st = float(np.linalg.norm(
                predictor.solution_estimate(lam) - x_true)) / scale
            e_bb = float(np.linalg.norm(bb.predict(lam) - x_true)) / scale
            rows.append({"region": region,
                         "lam": [float(t) for t in np.asarray(lam).ravel()],
                         "rel_err_structure": e_st, "rel_err_blackbox": e_bb})

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
