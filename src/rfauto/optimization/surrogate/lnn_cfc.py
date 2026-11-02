"""液态神经网络 CfC 时域响应代理（注册键 "lnn_cfc"，aurora_p LNN 席）。

定位：既有 27 键全是「静态 θ→曲线/标量」映射；本键补 **参数化时域响应族
代理**——θ（设计参数）→ 整条瞬态轨迹 y(t)（阶跃/包络/捕获动态面），
以 **CfC（Closed-form Continuous-time）单元** 作为动力学内核做自治 rollout：
时间 Δt 显式进入门控（免 ODE 数值求解器，单步闭式），支持训练窗外的
**时域外推**（同 Δt 多滚几步——BENCH 实测有效）；更细时间步（Δt<训练步）
按物理秒折算进门但**不在验证包络内**（见诚实边界第一条）。

法源（web 实读 2026-11-02；逐式出处，公式不受版权保护）：
- LTC：Hasani, Lechner, Amini, Rus, Grosu, "Liquid Time-constant Networks",
  AAAI-21，arXiv:2006.04439（CC BY 4.0）——Eq.(1)
  dx/dt = −[1/τ + f(x,I,t,θ)]·x + f(x,I,t,θ)·A；液态时间常数
  τ_sys = τ/(1+τ·f)；Theorem 2 有界态 min(0,A_min) ≤ x_i(t) ≤ max(0,A_max)。
- CfC：Hasani, Lechner, Amini, Liebenwein, Ray, Tschaikowski, Teschl, Rus,
  "Closed-form Continuous-time Neural Models", Nature Machine Intelligence
  4, 992–1003 (2022)，DOI 10.1038/s42256-022-00556-7，arXiv:2106.13898
  （CC BY-NC-SA 4.0）——Eq.(2)/Thm.1 闭式近似解
  x(t) = (x₀−A)·e^{−[w_τ+f(I)]t}·f(−I) + A；Lemma 1 误差界
  |x(t)−x̃(t)| ≤ |x(0)−A|·e^{−w_τ t}；**Eq.(10) CfC 单元（本件实现式）**
  x(t) = σ(−f(x,I;θ_f)·t) ⊙ g(x,I;θ_g) + [1−σ(−f(x,I;θ_f)·t)] ⊙ h(x,I;θ_h)
  ——f 充当「液态时间常数」（论文 Fig.4 说明），σ(−f·t) 为时间连续门。
- 实现参考对象（**只读思想、代码零复制**）：mlech26l/ncps（Apache-2.0，
  LICENSE 原文实读）、raminmh/CfC（Apache-2.0）、
  raminmh/liquid_time_constant_networks（Apache-2.0）。本件为论文公式自研
  numpy 实现：骨干/读出/训练器/参数化头全部本席设计，与上述仓库无共享
  代码路径（RECON 档案 runs/aurora_p/lnn/RECON.md）。

本件架构（本席设计，Eq.(10) 之外的工程选择逐条声明）：
- 参数化头：θ̃（bounds 单位归一，不截断——允许凸包外外推）→ 初始态
  x₀ = tanh(θ̃W₀+b₀)；θ̃ 同时作为常输入 I 进入 CfC 骨干，使门控率 f 与
  两路 g/h 全部 θ 依赖（任务书"θ→初始态/τ/门控偏置"映射）；
- CfC 单元：共享骨干 z = tanh([x;θ̃]W_b+b_b)（单隐层）；f = zW_f+b_f
  （无约束，b_f 即门控偏置）；g = tanh(zW_g+b_g)、h = tanh(zW_h+b_h)
  （tanh 有界取 LTC Thm.2 有界态精神）；时间门 s = σ(−f·Δt)；
  x⁺ = s⊙g + (1−s)⊙h（Eq.(10) 逐字）；
- 读出：线性 y = xW_o+b_o（CfC 惯例；nn_model._MLP 只作基准基线臂，
  不作读出——BPTT 需对输入求导，_MLP 无该面，裁量不复用）；
- 时间单位：训练网格一步 = 1.0 单位（Δt_unit = Δt_phys/dt_train_s），
  predict_curve 任意网格按物理秒折算 Δt 进门；
- 训练：全批 BPTT + 手写 Adam（同 svgp minibatch/_MLP 惯例），权重衰减
  只作用于矩阵；目标全局标准化；全局梯度范数裁剪（缺省 10，探针实测
  lr=1e-2 无裁剪 1500 轮发散、有裁剪不发散）；可选多速率训练（dt_strides，
  缺省单速率 (1,)——见常量注记）。

诚实边界（#122，逐条如实）：
- **细网格（Δt_unit<1）预测不在验证包络内**：探针实测训练 Δt=1 的模型在
  2× 细网格上 RMSE 劣化 ~20×（0.0069→0.13，probe_sweep2.log），且多速率
  (1,2)/(1,2,4) 训练不能修复——结构性根因：Eq.(10) 门 σ(−f·Δt) 在 Δt→0
  恒为 ½，x⁺→(g+h)/2 而非 x（Eq.(2)/Lemma 1 的误差界 |x₀−A|e^{−w_τ t}
  恰在 t=0 最松），CfC 闭式是"大步跳"近似而非一致积分器——细步 rollout
  把每步最坏误差累加。预测请用 ≥ 训练 Δt 的网格（时域外推同 Δt 多滚步
  实测 RMSE 0.003 量级）；BENCH OOD 表如实记此项为 FAIL；
- 参数凸包外外推不是先验保证（BENCH ζ 外推档 RMSE 0.03 量级，如实记）；
- 无原生逐点不确定度（uncertainty 走基类 None，predict_with_std 如实
  std=None）；
- 轨迹假设为与 time_grid 同跨度的均匀采样（与 fno_lite/deeponet 的
  freq_grid 口径同构），非均匀采样原曲线请先重采样；
- 本件是数据驱动代理（粗筛），不替代真机/闭式求解；OOD 胜负（vs MLP
  基线）见 runs/aurora_p/lnn/BENCH.md，凹凸都记。

确定性（红线）：唯一随机源=权重初始化 default_rng(seed)；全批训练无洗牌
——同 seed 同数据 fit/predict/predict_curve/fit_info 逐位复现。

负例契约：samples 空 / 缺 bounds / 缺 time_grid 或 t1≤t0 / curve_samples<2
/ hidden·backbone<1 / epochs<1 / lr≤0 或非有限 / 轨迹非一维·长度<2·
含非有限值（**显式报错不静默丢弃**）/ 有效轨迹 <2 / 未拟合 predict /
predict_curve n_points<2 或 t_end≤t0——全部显式 ValueError/RuntimeError。

用法::

    model = surrogate_registry.create("lnn_cfc", config={
        "bounds": {"wn": (1.0, 3.0), "zeta": (0.3, 1.2)},   # 必填
        "time_grid": [0.0, 8.0],   # 必填，轨迹物理时间跨度（秒）
        "curve_samples": 64,       # 训练网格点数 T
        "curve_key": "response_curve",  # metrics 内轨迹键（list[float]）
        "hidden": 16, "backbone": 32, "epochs": 1500, "lr": 5e-3,
        "seed": 20261102,
    })
    info = model.fit([{"params": {...}, "metrics": {"response_curve": [...]}}])
    c = model.predict_curve({"wn": 2.0, "zeta": 0.5})          # 训练网格
    c2 = model.predict_curve({...}, n_points=96, t_end=12.0)   # 同 Δt 时域外推
    v = model.predict({...})  # {curve_key_final, curve_key_max, curve_key_min}
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)

__all__ = [
    "DEFAULT_LNN_SEED",
    "CfcNet",
    "LnnCfcSurrogate",
    "cfc_time_gate",
    "rc_cascade_step_response",
    "second_order_step_response",
]

#: 缺省随机种子（确定性红线：显式缺省值；唯一随机源=权重初始化）
DEFAULT_LNN_SEED = 20261102

#: 缺省训练网格点数 / 隐态维 / 骨干宽 / 训练轮 / 学习率 / 权重衰减
#:（lr 缺省 5e-3：探针实测 1e-2 在 1500 轮 BPTT 发散，5e-3 稳定收敛）
DEFAULT_CURVE_SAMPLES = 64
DEFAULT_HIDDEN = 16
DEFAULT_BACKBONE = 32
DEFAULT_EPOCHS = 1500
DEFAULT_LR = 5e-3
DEFAULT_WEIGHT_DECAY = 1e-5

#: 多速率训练整数步长集缺省（单速率 (1,)=论文朴素档；(1,2)/(1,2,4) 为可选
#: 档：在 y[:, ::s] 上以 Δt=s 同步训练让时间门见到多个 Δt——探针实测
#: 多速率**不能**修复细网格（Δt<1）预测的劣化且同轮数原网格精度略降
#:（runs/aurora_p/lnn/probe_sweep2.log），故缺省单速率；细网格劣化的
#: 结构性根因见模块 docstring 诚实边界）
DEFAULT_DT_STRIDES: tuple[int, ...] = (1,)

#: 缺省全局梯度范数裁剪（RNN BPTT 稳定性惯例，Pascanu et al. 2013 思想；
#: None=不裁剪）
DEFAULT_GRAD_CLIP = 10.0

#: 缺省轨迹键（metrics 内 list[float]）
DEFAULT_CURVE_KEY = "response_curve"

#: 有效轨迹少于此数不拟合（显式报错）
_MIN_FIT_CURVES = 2

#: 目标标准差低于此阈值视为常数目标（y_std 取 1，fit_info 如实记）
_CONST_STD_FLOOR = 1e-12


# ─── 已知锚闭式解（教科书级，#300：裁判先过基准——单测对 scipy 独立互证） ──

def second_order_step_response(
    t: np.ndarray, wn: float, zeta: float,
) -> np.ndarray:
    """标准二阶系统 H(s)=ωn²/(s²+2ζωn s+ωn²) 的单位阶跃响应闭式解。

    三段式（欠阻尼/临界/过阻尼），y(0)=0、y(∞)=1：
    - ζ<1：y = 1 − e^{−ζωn t}[cos ωd t + (ζ/√(1−ζ²)) sin ωd t]，
      ωd = ωn√(1−ζ²)；
    - ζ=1：y = 1 − e^{−ωn t}(1 + ωn t)；
    - ζ>1：y = 1 + [ωn²/(s₁(s₁−s₂))]e^{s₁t} + [ωn²/(s₂(s₂−s₁))]e^{s₂t}，
      s₁,₂ = −ζωn ± ωn√(ζ²−1)（部分分式，s₁s₂=ωn²）。
    ζ≤0 或 ωn≤0 显式报错（无界/非物理）。
    """
    t = np.asarray(t, dtype=float)
    wn = float(wn)
    zeta = float(zeta)
    if not (np.isfinite(wn) and wn > 0.0):
        raise ValueError(f"wn 须为正有限，实得 {wn}")
    if not (np.isfinite(zeta) and zeta > 0.0):
        raise ValueError(f"zeta 须为正有限，实得 {zeta}")
    if abs(zeta - 1.0) < 1e-12:
        return 1.0 - np.exp(-wn * t) * (1.0 + wn * t)
    if zeta < 1.0:
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        coef = zeta / math.sqrt(1.0 - zeta * zeta)
        return 1.0 - np.exp(-zeta * wn * t) * (
            np.cos(wd * t) + coef * np.sin(wd * t))
    root = math.sqrt(zeta * zeta - 1.0)
    s1 = -zeta * wn + wn * root
    s2 = -zeta * wn - wn * root
    c1 = wn * wn / (s1 * (s1 - s2))
    c2 = wn * wn / (s2 * (s2 - s1))
    return 1.0 + c1 * np.exp(s1 * t) + c2 * np.exp(s2 * t)


def rc_cascade_step_response(
    t: np.ndarray, tau: float, n_stages: int,
) -> np.ndarray:
    """N 级缓冲级联一阶 RC（同 τ）单位阶跃响应闭式解。

    y(t) = 1 − e^{−t/τ} Σ_{k=0}^{N−1} (t/τ)^k / k!（Erlang/Gamma CDF，
    = 正则化下不完全伽马 P(N, t/τ)——单测以 scipy.special.gammainc 互证）。
    N=1 退化为 1 − e^{−t/τ}。τ≤0 或 N<1 显式报错。
    """
    t = np.asarray(t, dtype=float)
    tau = float(tau)
    n = int(n_stages)
    if not (np.isfinite(tau) and tau > 0.0):
        raise ValueError(f"tau 须为正有限，实得 {tau}")
    if n < 1:
        raise ValueError(f"n_stages 须 ≥1，实得 {n}")
    u = t / tau
    acc = np.zeros_like(u)
    term = np.ones_like(u)
    for k in range(n):
        if k > 0:
            term = term * u / k
        acc = acc + term
    return 1.0 - np.exp(-u) * acc


# ─── CfC 单元（Eq.(10)）与网络 ────────────────────────────────────────────

def cfc_time_gate(f: np.ndarray, dt: float | np.ndarray) -> np.ndarray:
    """CfC 时间连续门 σ(−f·Δt)（Hasani et al. 2022 Eq.(10) 的 σ 项）。

    数值稳定形 σ(u)=½(1+tanh(u/2))；Δt=0 时恒为 ½，f>0 时随 Δt→∞ 单调
    趋 0（旧态路径 g 权重衰减、新态路径 h 权重增至 1）。
    """
    u = -np.asarray(f, dtype=float) * dt
    return 0.5 * (1.0 + np.tanh(0.5 * u))


class CfcNet:
    """numpy CfC 网络：参数化初始态头 + CfC 单元自治 rollout + 线性读出。

    形状约定：θ̃ (N,d) 单位归一参数；隐态 (N,H)；骨干 (N,B)；输出 (N,T)。
    forward 返回 (N,T) 轨迹；loss_and_grads 返回标准化 MSE 与各参数梯度
    （与 ``params`` 同序，BPTT 解析梯度——单测以中心差分裁判，#118 族）。
    """

    _KEYS: tuple[str, ...] = (
        "w0", "b0", "wb", "bb", "wf", "bf", "wg", "bg", "wh", "bh", "wo", "bo")

    def __init__(self, n_in: int, hidden: int, backbone: int, seed: int) -> None:
        d = int(n_in)
        h = int(hidden)
        b = int(backbone)
        if d < 1 or h < 1 or b < 1:
            raise ValueError(
                f"n_in/hidden/backbone 须 ≥1，实得 {d}/{h}/{b}")
        rng = np.random.default_rng(int(seed))
        self.n_in, self.hidden, self.backbone = d, h, b
        self.w0 = rng.normal(0.0, math.sqrt(1.0 / d), (d, h))
        self.b0 = np.zeros(h)
        self.wb = rng.normal(0.0, math.sqrt(1.0 / (h + d)), (h + d, b))
        self.bb = np.zeros(b)
        self.wf = rng.normal(0.0, math.sqrt(1.0 / b), (b, h))
        self.bf = np.zeros(h)
        self.wg = rng.normal(0.0, math.sqrt(1.0 / b), (b, h))
        self.bg = np.zeros(h)
        self.wh = rng.normal(0.0, math.sqrt(1.0 / b), (b, h))
        self.bh = np.zeros(h)
        self.wo = rng.normal(0.0, math.sqrt(1.0 / h), (h, 1))
        self.bo = np.zeros(1)
        self.params: list[np.ndarray] = [getattr(self, k) for k in self._KEYS]
        self._m = [np.zeros_like(p) for p in self.params]
        self._v = [np.zeros_like(p) for p in self.params]
        self._t = 0

    @property
    def n_params(self) -> int:
        return int(sum(p.size for p in self.params))

    # ── 前向 ──

    def initial_state(self, theta_u: np.ndarray) -> np.ndarray:
        """参数化初始态头 x₀ = tanh(θ̃W₀+b₀)。"""
        return np.tanh(theta_u @ self.w0 + self.b0)

    def step(self, x: np.ndarray, theta_u: np.ndarray, dt: float,
             ) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
        """单步 CfC 单元（Eq.(10)）：返回 (x⁺, cache)。"""
        u = np.concatenate([x, theta_u], axis=1)
        z = np.tanh(u @ self.wb + self.bb)
        f = z @ self.wf + self.bf
        g = np.tanh(z @ self.wg + self.bg)
        h = np.tanh(z @ self.wh + self.bh)
        s = cfc_time_gate(f, dt)
        x_next = s * g + (1.0 - s) * h
        return x_next, (u, z, g, h, s)

    def rollout(self, theta_u: np.ndarray, n_steps: int,
                dt: float | np.ndarray,
                ) -> tuple[np.ndarray, list[tuple[np.ndarray, ...]]]:
        """自治 rollout：返回隐态序列 (N,T,H) 与逐步 cache。"""
        theta_u = np.atleast_2d(np.asarray(theta_u, dtype=float))
        n_steps = int(n_steps)
        dts = self._dt_vector(dt, n_steps)
        x = self.initial_state(theta_u)
        xs = [x]
        caches: list[tuple[np.ndarray, ...]] = []
        for k in range(n_steps - 1):
            x, cache = self.step(x, theta_u, float(dts[k]))
            xs.append(x)
            caches.append(cache)
        return np.stack(xs, axis=1), caches

    @staticmethod
    def _dt_vector(dt: float | np.ndarray, n_steps: int) -> np.ndarray:
        if np.isscalar(dt):
            return np.full(max(n_steps - 1, 0), float(dt))
        arr = np.asarray(dt, dtype=float).ravel()
        if arr.size != n_steps - 1:
            raise ValueError(
                f"dt 向量长度须为 n_steps−1={n_steps - 1}，实得 {arr.size}")
        return arr

    def forward(self, theta_u: np.ndarray, n_steps: int,
                dt: float | np.ndarray) -> np.ndarray:
        """θ̃ → 标准化空间轨迹 (N,T)。"""
        xs, _ = self.rollout(theta_u, n_steps, dt)
        return (xs @ self.wo)[..., 0] + self.bo[0]

    # ── 损失与 BPTT 解析梯度 ──

    def loss_and_grads(
        self, theta_u: np.ndarray, y_target: np.ndarray,
        dt: float | np.ndarray, weight_decay: float = 0.0,
    ) -> tuple[float, list[np.ndarray]]:
        """标准化 MSE（含 ½·wd·Σ‖W‖² 矩阵衰减项）与各参数梯度。"""
        theta_u = np.atleast_2d(np.asarray(theta_u, dtype=float))
        y_target = np.asarray(y_target, dtype=float)
        n, t_len = y_target.shape
        dts = self._dt_vector(dt, t_len)
        xs, caches = self.rollout(theta_u, t_len, dt)
        y = (xs @ self.wo)[..., 0] + self.bo[0]
        diff = y - y_target
        loss = float(np.mean(diff * diff))
        d_y = 2.0 * diff / (n * t_len)                      # (N,T)
        g = {k: np.zeros_like(getattr(self, k)) for k in self._KEYS}
        g["wo"] = np.einsum("nth,nt->h", xs, d_y)[:, None]
        g["bo"] = np.array([d_y.sum()])
        d_xs = d_y[:, :, None] * self.wo[None, None, :, 0]  # (N,T,H)
        hdim = self.hidden
        dx_next = np.zeros((n, hdim))
        for k in range(t_len - 2, -1, -1):
            dx_kp1 = d_xs[:, k + 1] + dx_next
            u, z, gk, hk, sk = caches[k]
            ds = dx_kp1 * (gk - hk)
            dg = dx_kp1 * sk
            dh = dx_kp1 * (1.0 - sk)
            d_pf = ds * sk * (1.0 - sk) * (-float(dts[k]))
            d_pg = dg * (1.0 - gk * gk)
            d_ph = dh * (1.0 - hk * hk)
            g["wf"] += z.T @ d_pf
            g["bf"] += d_pf.sum(0)
            g["wg"] += z.T @ d_pg
            g["bg"] += d_pg.sum(0)
            g["wh"] += z.T @ d_ph
            g["bh"] += d_ph.sum(0)
            dz = d_pf @ self.wf.T + d_pg @ self.wg.T + d_ph @ self.wh.T
            d_pz = dz * (1.0 - z * z)
            g["wb"] += u.T @ d_pz
            g["bb"] += d_pz.sum(0)
            dx_next = (d_pz @ self.wb.T)[:, :hdim]
        dx0 = d_xs[:, 0] + dx_next
        x0 = xs[:, 0]
        d_p0 = dx0 * (1.0 - x0 * x0)
        g["w0"] = theta_u.T @ d_p0
        g["b0"] = d_p0.sum(0)
        wd = float(weight_decay)
        if wd > 0.0:
            for k in ("w0", "wb", "wf", "wg", "wh", "wo"):
                w = getattr(self, k)
                g[k] = g[k] + wd * w
                loss += 0.5 * wd * float(np.sum(w * w))
        return loss, [g[k] for k in self._KEYS]

    def adam_step(self, grads: list[np.ndarray], lr: float,
                  betas: tuple[float, float] = (0.9, 0.999),
                  eps: float = 1e-8) -> None:
        """手写 Adam（原位更新，保持 params 别名——#116 名字绑定家法）。"""
        self._t += 1
        b1, b2 = betas
        for p, gi, mi, vi in zip(self.params, grads, self._m, self._v,
                                 strict=True):
            mi *= b1
            mi += (1.0 - b1) * gi
            vi *= b2
            vi += (1.0 - b2) * gi * gi
            m_hat = mi / (1.0 - b1 ** self._t)
            v_hat = vi / (1.0 - b2 ** self._t)
            p -= lr * m_hat / (np.sqrt(v_hat) + eps)


def _clip_global_norm(grads: list[np.ndarray], max_norm: float) -> float:
    """全局梯度范数裁剪（原位缩放；返回裁剪前范数）。"""
    total = math.sqrt(sum(float(np.sum(g * g)) for g in grads))
    if total > max_norm and total > 0.0:
        scale = max_norm / total
        for g in grads:
            g *= scale
    return total


# ─── 代理契约面 ────────────────────────────────────────────────────────────

@surrogate_registry.register("lnn_cfc")
class LnnCfcSurrogate(SurrogateModel):
    """CfC 液态神经网络参数化时域响应代理（注册键 "lnn_cfc"）。

    config:
        bounds: {param: (low, high)}（必填，单位归一基准；不截断）。
        time_grid: [t0, t1] 轨迹物理时间跨度（必填，t1>t0）。
        curve_samples: 训练网格点数 T（缺省 64，≥2）。
        curve_key: metrics 内轨迹键（缺省 "response_curve"）。
        hidden / backbone: 隐态维 H / 骨干宽 B（缺省 16/32，≥1）。
        epochs / lr / weight_decay: 全批 Adam 轮数/学习率/矩阵衰减
            （缺省 1500/5e-3/1e-5；epochs≥1、lr 正有限、wd≥0）。
        dt_strides: 多速率训练整数步长集（缺省 (1,) 单速率；(1,2) 等
            可选档：每轮在 y[:, ::s] 上以 Δt=s 同步算损失相加，让时间门
            见到多个 Δt——探针实测不能修复细网格劣化，见模块诚实边界；
            每个步长须为 ≥1 整数且 ≤ n_steps−1）。
        grad_clip: 全局梯度范数裁剪阈（缺省 10.0；None 不裁剪；>0 有限）。
        seed: 随机种子（缺省 DEFAULT_LNN_SEED；唯一随机源=初始化）。
    fit_info：kind/n_samples(有效轨迹数)/n_skipped(缺键样本)/n_steps/
        hidden/backbone/n_params/epochs/lr/weight_decay/dt_strides/
        grad_clip/seed/dt_train_s/time_grid/curve_key/loss_initial/
        loss_final（标准化空间 MSE，多速率为各步长和）/train_rmse（原单位，
        原网格）/constant_target。
    """

    KIND = "lnn_cfc"

    # ── 校验 ──

    def _resolve_config(self) -> None:
        cfg = self.config
        bounds_cfg = cfg.get("bounds")
        if not bounds_cfg:
            raise ValueError("config 缺 bounds（单位归一基准必填）")
        self.bounds = {str(k): (float(v[0]), float(v[1]))
                       for k, v in bounds_cfg.items()}
        for k, (lo, hi) in self.bounds.items():
            if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
                raise ValueError(
                    f"bounds[{k!r}] 须为有限且 high>low，实得 ({lo}, {hi})")
        self.names = sorted(self.bounds)
        tg = cfg.get("time_grid")
        if tg is None or len(tg) != 2:
            raise ValueError("config 缺 time_grid=[t0, t1]（轨迹物理时间跨度必填）")
        t0, t1 = float(tg[0]), float(tg[1])
        if not (np.isfinite(t0) and np.isfinite(t1)) or t1 <= t0:
            raise ValueError(f"time_grid 须 t1>t0 且有限，实得 [{t0}, {t1}]")
        self.time_grid = (t0, t1)
        self.n_steps = int(cfg.get("curve_samples", DEFAULT_CURVE_SAMPLES))
        if self.n_steps < 2:
            raise ValueError(f"curve_samples 须 ≥2，实得 {self.n_steps}")
        self.curve_key = str(cfg.get("curve_key", DEFAULT_CURVE_KEY))
        self.hidden = int(cfg.get("hidden", DEFAULT_HIDDEN))
        self.backbone = int(cfg.get("backbone", DEFAULT_BACKBONE))
        if self.hidden < 1 or self.backbone < 1:
            raise ValueError(
                f"hidden/backbone 须 ≥1，实得 {self.hidden}/{self.backbone}")
        self.epochs = int(cfg.get("epochs", DEFAULT_EPOCHS))
        if self.epochs < 1:
            raise ValueError(f"epochs 须 ≥1，实得 {self.epochs}")
        self.lr = float(cfg.get("lr", DEFAULT_LR))
        if not np.isfinite(self.lr) or self.lr <= 0.0:
            raise ValueError(f"lr 须为正有限，实得 {self.lr}")
        self.weight_decay = float(cfg.get("weight_decay", DEFAULT_WEIGHT_DECAY))
        if not np.isfinite(self.weight_decay) or self.weight_decay < 0.0:
            raise ValueError(f"weight_decay 须 ≥0 有限，实得 {self.weight_decay}")
        raw_strides = cfg.get("dt_strides", DEFAULT_DT_STRIDES)
        if np.isscalar(raw_strides):
            raw_strides = (raw_strides,)
        strides: list[int] = []
        for s in raw_strides:
            si = int(s)
            if si != s or si < 1 or si > self.n_steps - 1:
                raise ValueError(
                    f"dt_strides 元素须为 1..{self.n_steps - 1} 的整数，实得 {s!r}")
            strides.append(si)
        if not strides:
            raise ValueError("dt_strides 不得为空")
        self.dt_strides = tuple(dict.fromkeys(strides))  # 去重保序
        raw_clip = cfg.get("grad_clip", DEFAULT_GRAD_CLIP)
        if raw_clip is None:
            self.grad_clip: float | None = None
        else:
            clip = float(raw_clip)
            if not np.isfinite(clip) or clip <= 0.0:
                raise ValueError(f"grad_clip 须为正有限或 None，实得 {raw_clip!r}")
            self.grad_clip = clip
        self.seed = int(cfg.get("seed", DEFAULT_LNN_SEED))
        self._dt_train_s = (t1 - t0) / (self.n_steps - 1)

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        """单位归一（不截断：凸包外参数按线性外推进网络）；缺键取区间中点。"""
        row = []
        for n in self.names:
            lo, hi = self.bounds[n]
            v = params.get(n)
            v = 0.5 * (lo + hi) if v is None else float(v)
            if not np.isfinite(v):
                raise ValueError(f"params[{n!r}] 非有限：{v}")
            row.append((v - lo) / (hi - lo))
        return np.array(row, dtype=float)

    def _extract_curve(self, idx: int, sample: dict[str, Any]) -> np.ndarray:
        raw = sample["metrics"][self.curve_key]
        arr = np.asarray(raw, dtype=float)
        if arr.ndim != 1:
            raise ValueError(
                f"样本 {idx} 轨迹 {self.curve_key!r} 须为一维序列，"
                f"实得 shape={arr.shape}（形状不符显式报错）")
        if arr.size < 2:
            raise ValueError(
                f"样本 {idx} 轨迹 {self.curve_key!r} 长度 {arr.size} <2（空/退化轨迹）")
        if not np.all(np.isfinite(arr)):
            raise ValueError(
                f"样本 {idx} 轨迹 {self.curve_key!r} 含非有限值（显式报错不静默丢弃）")
        t0, t1 = self.time_grid
        src = np.linspace(t0, t1, arr.size)
        dst = np.linspace(t0, t1, self.n_steps)
        return np.interp(dst, src, arr)

    # ── 契约面 ──

    def _multi_rate_loss_and_grads(
        self, net: CfcNet, theta_u: np.ndarray, ys: np.ndarray,
    ) -> tuple[float, list[np.ndarray]]:
        """多速率损失：Σ_s MSE(y[:, ::s] | Δt=s)；权重衰减只计一次。"""
        first, *rest = self.dt_strides
        total_loss, total_grads = net.loss_and_grads(
            theta_u, ys[:, ::first], float(first), self.weight_decay)
        for s in rest:
            loss_s, grads_s = net.loss_and_grads(theta_u, ys[:, ::s], float(s), 0.0)
            total_loss += loss_s
            for acc, g in zip(total_grads, grads_s, strict=True):
                acc += g
        return total_loss, total_grads

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if not samples:
            raise ValueError("samples 为空（n=0，负例契约），无法拟合")
        self._resolve_config()
        rows: list[np.ndarray] = []
        curves: list[np.ndarray] = []
        n_skipped = 0
        for idx, s in enumerate(samples):
            metrics = s.get("metrics") or {}
            if self.curve_key not in metrics or metrics[self.curve_key] is None:
                n_skipped += 1
                continue
            curves.append(self._extract_curve(idx, s))
            rows.append(self._unit_row(s.get("params") or {}))
        if len(curves) < _MIN_FIT_CURVES:
            raise ValueError(
                f"有效轨迹 {len(curves)} 条 <{_MIN_FIT_CURVES}（键 "
                f"{self.curve_key!r}；缺键样本 {n_skipped}），无法拟合")
        theta_u = np.vstack(rows)
        y = np.vstack(curves)
        y_mean = float(y.mean())
        y_std = float(y.std())
        constant_target = y_std < _CONST_STD_FLOOR
        if constant_target:
            y_std = 1.0
        ys = (y - y_mean) / y_std
        net = CfcNet(len(self.names), self.hidden, self.backbone, self.seed)
        loss_initial = None
        loss = float("nan")
        for _ in range(self.epochs):
            loss, grads = self._multi_rate_loss_and_grads(net, theta_u, ys)
            if loss_initial is None:
                loss_initial = loss
            if self.grad_clip is not None:
                _clip_global_norm(grads, self.grad_clip)
            net.adam_step(grads, self.lr)
        self._net = net
        self._y_mean, self._y_std = y_mean, y_std
        pred = net.forward(theta_u, self.n_steps, 1.0) * y_std + y_mean
        train_rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
        info = self._mark_fitted(len(curves))
        info.update({
            "n_skipped": n_skipped,
            "n_steps": self.n_steps,
            "hidden": self.hidden,
            "backbone": self.backbone,
            "n_params": net.n_params,
            "epochs": self.epochs,
            "lr": self.lr,
            "weight_decay": self.weight_decay,
            "dt_strides": list(self.dt_strides),
            "grad_clip": self.grad_clip,
            "seed": self.seed,
            "dt_train_s": self._dt_train_s,
            "time_grid": list(self.time_grid),
            "curve_key": self.curve_key,
            "loss_initial": loss_initial,
            "loss_final": loss,
            "train_rmse": train_rmse,
            "constant_target": bool(constant_target),
        })
        return info

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict_curve(
        self, params: dict[str, float], n_points: int | None = None,
        t_end: float | None = None,
    ) -> dict[str, list[float]]:
        """θ → 轨迹 {"time": [...], "response": [...]}。

        n_points 缺省=训练网格点数；t_end 缺省=训练窗终点——给更大 t_end
        即时域外推（保持训练 Δt 多滚步，BENCH 验证有效）。**细于训练网格
        的 n_points（Δt_unit<1）不在验证包络内**——CfC 闭式门在 Δt→0 恒为
        ½（结构性非一致积分器，见模块诚实边界），细网格请先在调用方离线
        重采样而非依赖本面（接口支持但精度不背书）。
        """
        self._check_fitted()
        t0, t1 = self.time_grid
        t_end_v = t1 if t_end is None else float(t_end)
        if not np.isfinite(t_end_v) or t_end_v <= t0:
            raise ValueError(f"t_end 须 >t0={t0} 且有限，实得 {t_end_v}")
        n = self.n_steps if n_points is None else int(n_points)
        if n < 2:
            raise ValueError(f"n_points 须 ≥2，实得 {n}")
        grid = np.linspace(t0, t_end_v, n)
        dt_unit = ((t_end_v - t0) / (n - 1)) / self._dt_train_s
        theta_u = self._unit_row(params)[None, :]
        ys = self._net.forward(theta_u, n, dt_unit)[0]
        y = ys * self._y_std + self._y_mean
        return {"time": grid.tolist(), "response": y.tolist()}

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        """训练网格轨迹的标量摘要：{key}_final / {key}_max / {key}_min。"""
        y = np.asarray(self.predict_curve(params)["response"], dtype=float)
        k = self.curve_key
        return {f"{k}_final": float(y[-1]), f"{k}_max": float(y.max()),
                f"{k}_min": float(y.min())}
