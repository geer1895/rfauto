"""线性结构保留代理：NGO 神经格林算子 → RF 多端口叠加映射（T-N23，aurora_o 第一席）。

定位（最小可用形态）：微波线性网络的**叠加定理**天然就是格林结构——固定无源
互易拓扑下，端口 j 单位入射波的响应列 S_{·j}(θ,f) 对任意端口激励向量 a 线性
叠加：b(θ,f) = S(θ,f)·a。几何/材料参数 θ 变化时 S 整体非线性变化，但 **a→b 的
线性结构不变**。本代理照 NGO 的分工：**已知线性结构按构造保留，网络只学参数
依赖** θ→Â(θ)；读出头 b=Â(θ)·a 对 a 线性——叠加精确性是代数恒等式而非学到的
近似。

法源与映射（TU/e 2026 CMAME，Melchers/Prins/Abdelmalik "Neural Green's
Operators"；代码 github.com/JoostHMPrins/ngo）——NGO 把线性 PDE 解写成
u = Φ(θ)·Â(θ)·d(f)：Â(θ) 格林核矩阵由网络从材料参数 θ 预测，d 是源项/边界载荷
的积分向量（对 f 线性），Φ 是基函数；三种训练形态 Model（方程+解标签）/
Data-free（方程已知，代数一致性 FÂF≈F 无解标签）/Data（仅数据）。逐项映射：

    NGO                              green_op（RF 多端口）
    ───────────────────────────────  ──────────────────────────────────────────
    源项 f / 积分载荷向量 d          端口入射波向量 a ∈ ℂ^P（常量或逐频 (n_freq,P)）
    格林核矩阵 Â(θ)                  采样栅格上的 S(θ,f_k) ∈ ℂ^{P×P}
    解 u                             反射波 b(f_k) = S(θ,f_k)·a（叠加 S 波形）
    基函数 Φ(θ)                      采样栅格恒等（最小形态不学基）
    u 对 f 线性（结构先验）          b 对 a 线性（叠加定理，读出头按构造）
    Data-free 一致性 FÂF≈F           ① 叠加残差 ‖Â(a1+a2)−Âa1−Âa2‖≡0（线性读出头
                                        构造性成立，fit 信息逐次报告实测值）；
                                     ② 互易 S=Sᵀ 按构造（上三角参数化，
                                        reciprocal=True 缺省）
    训练形态                         Data 形态：样本 {θ, S(θ,·)}——"单端口激励
                                     响应矩阵族"= S 的各列

与邻接代理的关系（三者正交，各守一种结构）：
- pole_residue：**单端口** 参数→极点-留数系数→S11(f) 曲线（因果稳定极点基先验，
  读出对留数线性）；
- mt_gp：**多指标联合 GP**（ICM 共区域化矩阵 B 承载指标间相关结构）；
- green_op：**多端口叠加结构保留**——任意端口激励线性组合的响应精确等于响应
  的同系数线性组合；θ→Â(θ) 的参数依赖才是被学对象。

形态（预声明，与 tests/unit/test_green_operator.py 判据同口径）：
- 读出头：b_f = Â_f(θ)·a_f（逐频矩阵-向量积，``superpose``）——对 a 线性为
  **代数恒等式**：predict(αa1+βa2) = α·predict(a1) + β·predict(a2) 在精确算术下
  逐项成立；有限精度下残差只在浮点舍入底（实测 ~1e-16 相对，测试钉 ≤1e-12）。
  "Data-free 一致性项"由此落地为**结构零项**：不进损失（无需优化），fit 信息
  以 ``superposition_residual_rel`` 逐次实测报告（证据面，#122 不假设而实测）。
- 参数头 θ→Â(θ)（唯一被学部分）：``head="ridge"``（缺省；归一化 θ 的多项式
  特征 + 闭式 ridge，列截距不正则，零随机）| ``head="mlp"``（复用
  nn_model._MLP，固定 seed）。目标 = 展平的 S 实/虚部（按训练集逐维标准化）。
- 互易按构造：``reciprocal=True``（缺省，任务书"固定无源互易拓扑"）只参数化
  上三角（含对角）P(P+1)/2 项，predict_matrix 对称填充 ⇒ S=Sᵀ **逐位**成立；
  训练样本按 (S+Sᵀ)/2 对称化并报告 ``max_reciprocity_residual_train``（样本
  不互易时如实报告，不静默）。``reciprocal=False`` 走全 P² 项。
- predict(params)（SurrogateModel 契约标量面）：逐 (i,j) 的带内
  ``s{i}{j}_db_max_in_band`` / ``s{i}{j}_db_min_in_band``（P≤9 紧凑命名，P≥10
  走 ``s{i}_{j}``）；多端口主面是 ``predict_matrix`` / ``predict_response``。

确定性（AGENTS 7 / C4）：ridge 路径零随机源；mlp 路径随机源仅 ``_MLP(seed)``
内部 Generator（不触全局 RNG）——同 config 同数据两跑逐位一致（测试钉住）。

诚实边界：
- 代理只保证**结构**（叠加/互易）精确；θ→Â 的参数依赖精度取决于头容量与样本
  覆盖——合成族门（Wilkinson 闭式 θ 扫参）在测试里预声明，不外推到真机；
- 不学频率基（Φ=恒等）：训练栅格即预测栅格，栅格外插值不在本席；
- 无源性不按构造强制（线性读出头无法同时保证 σmax≤1）——消费方用
  pole_residue.passivity_verdict 后验判据（单源，本模块不重造）；
- 无原生逐点不确定度（uncertainty 返回 None，不伪造 σ）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create("green_op",
config={...})``；纯增量键，既有 kind 消费面零改动。
"""

from __future__ import annotations

from itertools import combinations_with_replacement
from typing import Any

import numpy as np

from .base import SurrogateModel, surrogate_registry
from .nn_model import _MLP

__all__ = [
    "RESPONSE_KEY",
    "GreenOperatorSurrogate",
    "superpose",
    "superposition_residual",
]

#: 样本 metrics 里的多端口响应键：复数 S 矩阵栈 (n_freq, P, P)，列 j = 端口 j
#: 单位入射波的响应（"单端口激励响应矩阵族"）。
RESPONSE_KEY = "s_matrix"
#: dB 下限（|S|=0 保护，与 pole_residue._DB_FLOOR 同值同语义）。
_DB_FLOOR = 1e-30
#: 叠加残差相对量的分母保护（lhs 全零时不除零）。
_TINY = 1e-300


# ─── 线性读出（叠加定理，结构面；纯函数） ─────────────────────────────────────


def _as_s_stack(s_stack: Any, *, where: str) -> np.ndarray:
    s = np.asarray(s_stack, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2]:
        raise ValueError(
            f"{where}：S 栈须为 (n_freq, P, P) 方阵栈，实得 shape {s.shape}")
    return s


def _as_excitation(a: Any, n_freq: int, n_ports: int, *, where: str) -> np.ndarray:
    """激励向量规整：(P,) 广播到逐频，或 (n_freq, P) 原样；端口数/有限性显式校验。"""
    arr = np.asarray(a, dtype=complex)
    if arr.ndim == 1:
        if arr.shape[0] != n_ports:
            raise ValueError(
                f"{where}：激励向量端口数 {arr.shape[0]} ≠ 模型端口数 {n_ports}")
        arr = np.broadcast_to(arr, (n_freq, n_ports))
    elif arr.ndim == 2:
        if arr.shape != (n_freq, n_ports):
            raise ValueError(
                f"{where}：逐频激励须为 (n_freq, P)=({n_freq}, {n_ports})，"
                f"实得 {arr.shape}")
    else:
        raise ValueError(
            f"{where}：激励须为 (P,) 或 (n_freq, P)，实得 ndim={arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{where}：激励向量含非有限值（nan/inf）")
    return arr


def superpose(s_stack: Any, a: Any) -> np.ndarray:
    """叠加读出 b_f = S_f · a_f（逐频矩阵-向量积）。

    输入：s_stack (n_freq, P, P) 复数；a (P,)（常量激励，逐频广播）或 (n_freq, P)。
    输出：(n_freq, P) 复数反射波。对 a 线性是本函数的代数性质（无可学参数）。
    负例显式：端口数不匹配 / 非有限激励 → ValueError（不静默广播、不吞 nan）。
    """
    s = _as_s_stack(s_stack, where="superpose")
    n_freq, p = s.shape[0], s.shape[1]
    arr = _as_excitation(a, n_freq, p, where="superpose")
    return np.einsum("fij,fj->fi", s, arr)


def superposition_residual(s_stack: Any, a1: Any, a2: Any, *,
                           alpha: complex = 1.0,
                           beta: complex = 1.0) -> dict[str, float]:
    """叠加一致性残差 ‖S(αa1+βa2) − αSa1 − βSa2‖（Data-free 一致性项的 RF 形态）。

    对线性读出头该量在精确算术下恒为 0；本函数**实测**有限精度残差（最大绝对
    值与相对 lhs 尺度的相对值）供 fit 信息与测试钉用，不假设为零（#122）。
    """
    for name, v in (("alpha", alpha), ("beta", beta)):
        if not np.isfinite(complex(v)):
            raise ValueError(f"superposition_residual：{name} 须为有限标量")
    s = _as_s_stack(s_stack, where="superposition_residual")
    n_freq, p = s.shape[0], s.shape[1]
    v1 = _as_excitation(a1, n_freq, p, where="superposition_residual")
    v2 = _as_excitation(a2, n_freq, p, where="superposition_residual")
    lhs = superpose(s, alpha * v1 + beta * v2)
    rhs = alpha * superpose(s, v1) + beta * superpose(s, v2)
    diff = np.abs(lhs - rhs)
    lhs_scale = float(np.max(np.abs(lhs))) if lhs.size else 0.0
    max_abs = float(diff.max()) if diff.size else 0.0
    return {
        "residual_max_abs": max_abs,
        "residual_rel": max_abs / max(lhs_scale, _TINY),
        "lhs_max_abs": lhs_scale,
    }


# ─── 展平/还原（互易上三角参数化） ────────────────────────────────────────────


def _index_pairs(n_ports: int, reciprocal: bool) -> list[tuple[int, int]]:
    if reciprocal:
        return [(i, j) for i in range(n_ports) for j in range(i, n_ports)]
    return [(i, j) for i in range(n_ports) for j in range(n_ports)]


def _flatten_s(s: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    """(n_freq, P, P) → 实向量 [Re(entries...), Im(entries...)]（entries 按 pairs）。"""
    rows = np.array([i for i, _ in pairs], dtype=int)
    cols = np.array([j for _, j in pairs], dtype=int)
    ent = s[:, rows, cols]  # (n_freq, n_pairs)
    return np.concatenate([ent.real.ravel(), ent.imag.ravel()])


def _unflatten_s(y: np.ndarray, n_freq: int, n_ports: int,
                 pairs: list[tuple[int, int]], reciprocal: bool) -> np.ndarray:
    n_pairs = len(pairs)
    half = n_freq * n_pairs
    ent = (y[:half] + 1.0j * y[half:]).reshape(n_freq, n_pairs)
    out = np.zeros((n_freq, n_ports, n_ports), dtype=complex)
    for k, (i, j) in enumerate(pairs):
        out[:, i, j] = ent[:, k]
        if reciprocal and i != j:
            out[:, j, i] = ent[:, k]  # 同一数值双写 ⇒ S=Sᵀ 逐位成立
    return out


def _poly_features(x: np.ndarray, degree: int) -> np.ndarray:
    """归一化参数 → 全部 ≤degree 次单项式特征（含常数 1；字典序确定）。"""
    x = np.asarray(x, dtype=float)
    feats = [1.0]
    for d in range(1, int(degree) + 1):
        for combo in combinations_with_replacement(range(len(x)), d):
            feats.append(float(np.prod(x[list(combo)])))
    return np.array(feats, dtype=float)


def _entry_name(i: int, j: int, n_ports: int) -> str:
    return f"s{i + 1}{j + 1}" if n_ports <= 9 else f"s{i + 1}_{j + 1}"


# ─── 代理（kind="green_op"，SurrogateModel 契约） ─────────────────────────────


@surrogate_registry.register("green_op")
class GreenOperatorSurrogate(SurrogateModel):
    """参数化叠加代理：θ→Â(θ)（被学）× 线性读出 b=Â(θ)·a（按构造）。

    样本格式（SurrogateModel 契约同构）：
        samples = [{"params": {param: value},
                    "metrics": {"s_matrix": 复数数组 (n_freq, P, P)}}]
    响应缺失 / 不可转复数 / 形状不符 / 含非有限值的行，以及 params 含不可转
    float 值的行，按基类契约忽略（对应真机失败 trial），fit 信息 ``n_skipped``
    如实计数；params 缺键取界中点（与 pole_residue 同约定）。

    config:
        bounds: {param: (low, high)}（必填；参数线性映射到 [-1,1]，缺参取中点）
        n_ports: 端口数 P（必填，≥1）
        n_freq: 栅格点数（必填，≥1；训练栅格=预测栅格）
        freq_grid_ghz: (f_lo, f_hi) 可选元数据（``freq_hz`` 属性供消费方对齐）
        reciprocal: 互易按构造（缺省 True）
        head: "ridge"（缺省，闭式零随机）| "mlp"（nn_model._MLP，固定种子）
        poly_degree: ridge 多项式特征阶（缺省 2，≥1）
        ridge_lambda / seed / hidden / epochs / lr: 头超参
        response_key: 样本响应键（缺省 "s_matrix"）
    """

    KIND = "green_op"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        bounds = self.config.get("bounds")
        if not bounds:
            raise ValueError("GreenOperatorSurrogate：config['bounds'] 必填")
        self.bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
        self.param_names = sorted(self.bounds)
        n_ports = self.config.get("n_ports")
        if n_ports is None or int(n_ports) < 1:
            raise ValueError("GreenOperatorSurrogate：config['n_ports'] 必填且 ≥1")
        self.n_ports = int(n_ports)
        n_freq = self.config.get("n_freq")
        if n_freq is None or int(n_freq) < 1:
            raise ValueError("GreenOperatorSurrogate：config['n_freq'] 必填且 ≥1")
        self.n_freq = int(n_freq)
        grid = self.config.get("freq_grid_ghz")
        self.freq_hz: np.ndarray | None = None
        if grid is not None:
            if len(grid) != 2 or float(grid[1]) <= float(grid[0]):
                raise ValueError(
                    "GreenOperatorSurrogate：config['freq_grid_ghz'] 须为 "
                    "(f_lo, f_hi) 且 f_lo < f_hi")
            self.freq_hz = np.linspace(float(grid[0]) * 1e9,
                                       float(grid[1]) * 1e9, self.n_freq)
        self.reciprocal = bool(self.config.get("reciprocal", True))
        self.response_key = str(self.config.get("response_key", RESPONSE_KEY))
        self.head_kind = str(self.config.get("head", "ridge"))
        if self.head_kind not in ("ridge", "mlp"):
            raise ValueError("GreenOperatorSurrogate：head 须为 'ridge'|'mlp'")
        self.poly_degree = int(self.config.get("poly_degree", 2))
        if self.poly_degree < 1:
            raise ValueError("GreenOperatorSurrogate：poly_degree 须 ≥1")
        self.ridge_lambda = float(self.config.get("ridge_lambda", 1e-6))
        if self.ridge_lambda < 0.0:
            raise ValueError("GreenOperatorSurrogate：ridge_lambda 须 ≥0")
        self.seed = int(self.config.get("seed", 42))
        self.hidden = int(self.config.get("hidden", 32))
        self.epochs = int(self.config.get("epochs", 2000))
        self.lr = float(self.config.get("lr", 5e-3))
        if self.hidden < 1 or self.epochs < 1 or self.lr <= 0.0:
            raise ValueError("GreenOperatorSurrogate：hidden/epochs 须 ≥1，lr 须 >0")
        self._pairs = _index_pairs(self.n_ports, self.reciprocal)
        self._n_out = 2 * self.n_freq * len(self._pairs)
        self._w_ridge: np.ndarray | None = None
        self._net: _MLP | None = None
        self._y_mean: np.ndarray | None = None
        self._y_std: np.ndarray | None = None

    # ── 内部 ──
    def _norm_params(self, params: dict[str, float]) -> np.ndarray:
        x = []
        for k in self.param_names:
            lo, hi = self.bounds[k]
            half = 0.5 * (hi - lo)
            val = float(params.get(k, 0.5 * (lo + hi)))
            x.append((val - 0.5 * (lo + hi)) / (half if half else 1.0))
        return np.array(x, dtype=float)

    def _coerce_sample(self, sample: dict[str, Any]) -> np.ndarray | None:
        metrics = sample.get("metrics") or {}
        raw = metrics.get(self.response_key)
        if raw is None:
            return None
        try:
            s = np.asarray(raw, dtype=complex)
        except (TypeError, ValueError):
            return None
        if s.shape != (self.n_freq, self.n_ports, self.n_ports):
            return None
        if not np.all(np.isfinite(s)):
            return None
        return s

    def _y_of(self, x: np.ndarray) -> np.ndarray:
        if self.head_kind == "ridge":
            y_std = _poly_features(x, self.poly_degree) @ self._w_ridge
        else:
            y_std = self._net.forward(x[None, :])[0]
        return y_std * self._y_std + self._y_mean

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if not samples:
            raise ValueError("GreenOperatorSurrogate.fit：无样本")
        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        s_train: list[np.ndarray] = []
        n_skipped = 0
        recip_resid = 0.0
        for sample in samples:
            s = self._coerce_sample(sample)
            if s is None:
                n_skipped += 1
                continue
            try:
                x = self._norm_params(sample.get("params") or {})
            except (TypeError, ValueError):
                # params 含不可转 float 的值：同"真机失败 trial"契约面，跳过
                # 并如实计数（metrics 无效行同口径）。
                n_skipped += 1
                continue
            if self.reciprocal:
                asym = float(np.max(np.abs(s - np.swapaxes(s, 1, 2))))
                recip_resid = max(recip_resid, asym)
                s = 0.5 * (s + np.swapaxes(s, 1, 2))
            xs.append(x)
            ys.append(_flatten_s(s, self._pairs))
            s_train.append(s)
        if not ys:
            raise ValueError(
                f"GreenOperatorSurrogate.fit：无有效 {self.response_key} 样本"
                f"（期望形状 ({self.n_freq}, {self.n_ports}, {self.n_ports})）")
        x_mat = np.vstack(xs)
        y_mat = np.vstack(ys)
        self._y_mean = y_mat.mean(0)
        self._y_std = y_mat.std(0) + 1e-12
        y_std_mat = (y_mat - self._y_mean) / self._y_std
        if self.head_kind == "ridge":
            feats = np.vstack([_poly_features(x, self.poly_degree) for x in x_mat])
            penalty = np.eye(feats.shape[1]) * self.ridge_lambda
            penalty[0, 0] = 0.0  # 常数项不正则
            self._w_ridge = np.linalg.solve(
                feats.T @ feats + penalty, feats.T @ y_std_mat)
            self._net = None
        else:
            self._net = _MLP(len(self.param_names), self._n_out, self.hidden, self.seed)
            for _ in range(self.epochs):
                self._net.adam_step(x_mat, y_std_mat, 1e-4, self.lr)
            self._w_ridge = None
        self._fitted = True
        # 训练面回代 RMSE（线性 |S| 单位）+ 叠加一致性实测（结构零项证据）
        sq = 0.0
        cnt = 0
        for x, s in zip(x_mat, s_train, strict=True):
            pred = _unflatten_s(self._y_of(x), self.n_freq, self.n_ports,
                                self._pairs, self.reciprocal)
            sq += float(np.sum(np.abs(pred - s) ** 2))
            cnt += pred.size
        s0 = _unflatten_s(self._y_of(x_mat[0]), self.n_freq, self.n_ports,
                          self._pairs, self.reciprocal)
        e1 = np.zeros(self.n_ports, dtype=complex)
        e1[0] = 1.0
        e2 = np.zeros(self.n_ports, dtype=complex)
        e2[-1] = 1.0
        sup = superposition_residual(s0, e1, e2, alpha=0.7 - 0.2j, beta=-1.3 + 0.4j)
        info = self._mark_fitted(len(ys))
        info.update({
            "n_skipped": n_skipped,
            "n_ports": self.n_ports,
            "n_freq": self.n_freq,
            "n_outputs": self._n_out,
            "head": self.head_kind,
            "poly_degree": self.poly_degree if self.head_kind == "ridge" else None,
            "reciprocal": self.reciprocal,
            "max_reciprocity_residual_train": (recip_resid if self.reciprocal
                                               else None),
            "train_rmse": float(np.sqrt(sq / max(cnt, 1))),
            "superposition_residual_rel": sup["residual_rel"],
        })
        return info

    def predict_matrix(self, params: dict[str, float]) -> np.ndarray:
        """Â(θ)：预测参数对应的复数 S 矩阵栈 (n_freq, P, P)（reciprocal 时逐位对称）。"""
        if not self._fitted:
            raise RuntimeError("GreenOperatorSurrogate.predict_matrix：先 fit")
        return _unflatten_s(self._y_of(self._norm_params(params)), self.n_freq,
                            self.n_ports, self._pairs, self.reciprocal)

    def predict_response(self, params: dict[str, float], a: Any) -> np.ndarray:
        """叠加 S 波形 b(f) = Â(θ,f)·a（a 为 (P,) 常量激励或 (n_freq, P) 逐频激励）。

        对 a 线性按构造成立（见模块 docstring）；端口数不匹配/非有限激励显式
        ValueError。
        """
        if not self._fitted:
            raise RuntimeError("GreenOperatorSurrogate.predict_response：先 fit")
        return superpose(self.predict_matrix(params), a)

    def superposition_residual(self, params: dict[str, float], a1: Any, a2: Any,
                               *, alpha: complex = 1.0,
                               beta: complex = 1.0) -> dict[str, float]:
        """预测模型在 (a1, a2, α, β) 上的叠加一致性残差实测（结构零项诊断面）。"""
        if not self._fitted:
            raise RuntimeError(
                "GreenOperatorSurrogate.superposition_residual：先 fit")
        return superposition_residual(self.predict_matrix(params), a1, a2,
                                      alpha=alpha, beta=beta)

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        s = self.predict_matrix(params)
        db = 20.0 * np.log10(np.maximum(np.abs(s), _DB_FLOOR))
        out: dict[str, Any] = {}
        for i in range(self.n_ports):
            for j in range(self.n_ports):
                name = _entry_name(i, j, self.n_ports)
                out[f"{name}_db_max_in_band"] = float(db[:, i, j].max())
                out[f"{name}_db_min_in_band"] = float(db[:, i, j].min())
        return out

    def uncertainty(self, params: dict[str, float]) -> None:
        """无原生逐点不确定度（单头确定性模型，不伪造 σ——#122 诚实纪律）。"""
        return None
