"""SVGP 变分稀疏 GP 大规模代理（注册键 "svgp"，aurora_p D3）。

定位：rff_gp（随机傅里叶特征+岭读出，aurora_n T-N21）已覆盖 >10k 档的
RFF 路线；本键落 **诱导点变分稀疏 GP（Sparse Variational GP）作为同档
备选路线**，与 rff_gp 同数据集对照精度/训练速度/预测速度（benchmark
证据 runs/aurora_p/d3/BENCH.md）。O(n·M²) 训练 / O(M²) 逐点评估，
M=诱导点数旋钮（缺省 128）——训练内存/墙钟不随 n 平方（n>M 稀疏性）。

法源（两源 2026-11-01 实读核对）：
- Hensman, J. & Matthews, A. & Ghahramani, Z., "Gaussian Processes for
  Big Data", UAI 2013：自由形式变分后验 q(u)=N(m,S) 于 M 个诱导点
  u=f(Z)，ELBO = Σ_i E_q[log p(y_i|f_i)] − KL(q(u)||p(u))；小批随机
  变分推断（minibatch 缩放 ELBO）；whitened 参数化（u=L_MM v）数值
  稳定档为工程惯例；
- Titsias, M., "Variational Learning of Inducing Variables in Sparse
  Gaussian Processes", AISTATS 2009：高斯似然下全批最优 q(u) 闭式解
  （共轭解，本件 "closed" 缺省档——免迭代、O(nM²) 单遍，数学上即
  Hensman 自由形式族的全批最优解）；
- 高斯似然 q(f) 边际：E[log p(y_i|f_i)] = −½log(2πσ²)
  −((y_i−μ_i)²+v_i)/(2σ²)，v_i = w_iᵀS w_i（q(u) 注入的潜函数方差）。

诚实边界（#122，逐条如实）：
- **只支持 SE（RBF）核**（与 rff_gp 同族口径；核矩阵单源复用
  gp_det.se_ard_kernel，不复制实现）；
- **超参降档**：信号幅 amp=1.0（标准化目标空间固定）与噪声方差
  noise_var（缺省 1e-2，标准化单位）**不入优化**——超参仅 ℓ 单源
  MLE（gp_det.fit_mle 固定 seed+1 子样本，与 rff_gp 同约定逐位同源；
  fixed 档 config 显式给）。amp/σ 联优（需对 collapsed 界做 L-BFGS）
  不在本件，如实不做；
- **诱导点训练期固定**（不随梯度学 Z；学 Z 档在本件边界外）；
  缺省 "spread"=最远点采样（FPS，零依赖确定性），可选 "random" 子采样；
- **closed 缺省档**=全批闭式最优 q(u)（高斯似然共轭解，无需迭代、
  无随机性——变分后验取到自由形式族内全局最优）；**minibatch 可选档**
  =对角 S（mean-field）+ 手写 Adam 小批训练（全协方差 SGD 不在本件，
  如实不做）——小批模式是"真 SVGP 训练回路"，closed 档是它的全批
  共轭快捷形态，两者预测公式同构；
- Z=X（M=n 且诱导点取全训练点）时本件闭式后验**退化为精确 GP 回归
  后验**（均值/方差，R&W (2.22)-(2.24)）——单测已知锚（#118：先在
  已知 GP 后验上验 SVGP 正确性，再上大样本对照）。

确定性（红线）：诱导点选择/MLE 子样本/小批排列三路独立固定
（Z 用 seed+2、ℓ-MLE 子样本用 seed+1——与 rff_gp 同约定、小批排列用
seed+3）——同 seed 同数据 fit/predict/uncertainty 逐位复现；closed
档全链无随机消费（同 seed 必逐位，含 Z=FPS 确定性迭代）。Cholesky/
np.linalg.solve 同机确定；BLAS 线程钉 1（#258 家法）由调用面承担。

负例契约（任务书验收④）：n_inducing<1 / 样本数=0 / 缺 bounds /
fixed 档 ℓ≤0（标量或逐维任一）或长度错 / ell_mode·mode·inducing_init
非法值 / noise_var≤0 非有限 / minibatch iters<1·batch_size<1·lr≤0 /
未拟合 predict——全部显式 ValueError/RuntimeError，不静默。

用法::

    model = surrogate_registry.create("svgp", config={
        "bounds": {"a": (0, 1), "b": (0, 2)},  # 必填，单元归一基准
        "n_inducing": 128,       # M（>10k 档缺省 128；M≥n 时自动取全点）
        "seed": 20261101,        # 缺省 DEFAULT_SVGP_SEED
        "ell_mode": "mle",       # "mle"（缺省）| "fixed"
        # "ell": 0.3,            # 仅 fixed 档：标量或逐维列表，>0
        "noise_var": 1e-2,       # 标准化单位固定噪声方差
        "mode": "closed",        # "closed"（缺省全批闭式）| "minibatch"
        # "iters": 200, "batch_size": 256, "lr": 0.05,   # minibatch 档
        "inducing_init": "spread",  # "spread"（FPS 缺省）| "random"
    })
    info = model.fit([{"params": {...}, "metrics": {"s21_db": ...}}])
    v = model.predict({"a": 0.5, "b": 1.0})      # {"s21_db": float}
    s = model.uncertainty({"a": 0.5, "b": 1.0})  # 后验 σ（非伪造）
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import fit_mle, se_ard_kernel

__all__ = [
    "DEFAULT_SVGP_SEED",
    "SvgpSurrogate",
    "farthest_point_sample",
    "svgp_elbo_terms",
    "svgp_inducing",
]

#: 缺省随机种子（确定性红线：显式缺省值；Z=seed+2/子样本=seed+1/排列=seed+3）
DEFAULT_SVGP_SEED = 20261101

#: 缺省诱导点数（>10k 档建议档；M≥n 时自动取全部训练点=精确 GP 退化锚）
DEFAULT_N_INDUCING = 128

#: ℓ-MLE 子样本缺省上限（n>cap 时 fit_mle 在固定 seed+1 子样本上估，
#: 与 rff_gp 同约定；n≤cap 与 gp_det 消费面逐位同源）
DEFAULT_MLE_SUBSAMPLE = 256

#: 缺省噪声方差（标准化单位；固定不入优化——诚实边界见 docstring）
DEFAULT_NOISE_VAR = 1e-2

#: minibatch 档缺省超参（Adam 手写档）
DEFAULT_ITERS = 200
DEFAULT_BATCH_SIZE = 256
DEFAULT_LR = 0.05

#: K_MM 相对抖动下限（数值 PD 守卫，非建模噪声；whitened 双 Cholesky
#: 链的稳定性前提；chol 失败时 ×100 阶梯重试至多 4 次）
_JITTER_REL = 1e-6

#: 有效点少于此数的指标键跳过不硬拟（家族口径，同 rff_gp 的 <3 约定）
_MIN_FIT_POINTS = 3

#: 目标标准差低于此阈值视为常数键（退化分支：predict 常数、σ=0——
#: 常数目标残差方差解析为 0，非伪造，fit_info["constant_keys"] 记录）
_CONST_STD_FLOOR = 1e-12


def farthest_point_sample(x: np.ndarray, m: int, seed: int) -> np.ndarray:
    """最远点采样（FPS）诱导点索引（确定性：起点 seed 决定，升序返回）。

    零依赖 k-means 替代：每步取距已选点集最远的点——M 个点覆盖 [0,1]^d
    单元域更均匀，K_MM 条件数稳健（近邻对=whitened 链病态源）。
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    n = int(x.shape[0])
    m = min(int(m), n)
    rng = np.random.default_rng(seed)
    start = int(rng.integers(0, n))
    selected = [start]
    d_min = np.linalg.norm(x - x[start], axis=1)
    while len(selected) < m:
        i = int(np.argmax(d_min))
        selected.append(i)
        d_min = np.minimum(d_min, np.linalg.norm(x - x[i], axis=1))
    return np.array(sorted(selected), dtype=int)


def svgp_inducing(
    xu: np.ndarray, m: int, seed: int, init: str = "spread",
) -> np.ndarray:
    """诱导点集合 Z（m×d，单元归一空间；m≥n 时退化为全部训练点）。

    "spread"=FPS（缺省，确定性），"random"=固定 seed 无放回子采样。
    """
    if init not in ("spread", "random"):
        raise ValueError(
            f'inducing_init 须为 "spread" 或 "random"，实得 {init!r}')
    n = int(xu.shape[0])
    m_eff = min(int(m), n)
    if m_eff >= n:
        return xu
    if init == "spread":
        return xu[farthest_point_sample(xu, m_eff, seed + 2)]
    rng = np.random.default_rng(seed + 2)
    idx = np.sort(rng.choice(n, size=m_eff, replace=False))
    return xu[idx]


def _chol_pd(k_mat: np.ndarray) -> np.ndarray:
    """K_MM + 相对抖动的 PD Cholesky（失败 ×100 阶梯至多 4 次）。"""
    m = k_mat.shape[0]
    jit = max(1e-12, _JITTER_REL * float(np.mean(np.diag(k_mat))))
    for _ in range(4):
        try:
            return np.linalg.cholesky(k_mat + jit * np.eye(m))
        except np.linalg.LinAlgError:
            jit *= 100.0
    raise np.linalg.LinAlgError(
        "svgp: K_MM 加抖动阶梯后仍非正定（诱导点近重合？）")


def _kernel_nm(
    z: np.ndarray, xu: np.ndarray, ell: np.ndarray, amp: float,
) -> np.ndarray:
    """M×n 核矩阵（分块行计算封顶内存；单源复用 se_ard_kernel）。

    分块尺寸按 M·d·chunk≈2e6 元素折算——50k×128×2d 档中间数组
    峰值 ~32MB（训练内存不随 n 平方的内存面佐证）。
    """
    m = int(z.shape[0])
    n = int(xu.shape[0])
    d = int(xu.shape[1])
    chunk = max(1024, int(2_000_000 // max(m * d, 1)))
    out = np.empty((m, n), dtype=float)
    for s in range(0, n, chunk):
        e = min(s + chunk, n)
        out[:, s:e] = se_ard_kernel(z, xu[s:e], ell, amp)
    return out


def svgp_closed_posterior(
    z: np.ndarray, xu: np.ndarray, ys: np.ndarray, noise_var: float,
    ell: np.ndarray, amp: float,
) -> dict[str, Any]:
    """全批闭式最优自由形式 q(v)（whitened，高斯似然共轭解）。

    返回 whitened 变分参数：m_w = B⁻¹Ay/σ²、S_w = B⁻¹，其中
    A = L_MM⁻¹K_MN、B = AAᵀ/σ²+I（L_MM = chol(K_MM+jitter)）——
    Titsias 2009 共轭解的 whitened 形，同时是 Hensman 2013 自由形式
    ELBO 在全批高斯似然下的全局最优（免迭代）。预测面 var 走
    LB 双项式（K_** − ‖L⁻¹k‖² + ‖L_B⁻¹L⁻¹k‖²，数值稳定）。
    """
    m = int(z.shape[0])
    k_mm = se_ard_kernel(z, z, ell, amp)
    l_mm = _chol_pd(k_mm)
    k_mn = _kernel_nm(z, xu, ell, amp)
    a_mat = np.linalg.solve(l_mm, k_mn)                     # M×n
    b_mat = a_mat @ a_mat.T / float(noise_var) + np.eye(m)
    l_b = np.linalg.cholesky(b_mat)
    a_y = a_mat @ ys
    c_vec = np.linalg.solve(l_b, a_y)                       # L_B⁻¹Ay
    m_w = np.linalg.solve(l_b.T, c_vec) / float(noise_var)  # B⁻¹Ay/σ²
    return {"l_mm": l_mm, "l_b": l_b, "m_w": m_w, "a_mat": a_mat,
            "b_mat": b_mat}


def svgp_elbo_terms(
    a_rows: np.ndarray, y_batch: np.ndarray, m_w: np.ndarray,
    log_s2: np.ndarray, n_total: int, noise_var: float,
) -> tuple[float, np.ndarray, np.ndarray]:
    """mean-field 小批 ELBO 及解析梯度（Hensman 2013，whitened）。

    返回 (elbo, dELBO/dm_w, dELBO/dlog_s2)。minibatch 缩放：似然项乘
    n/B；KL(q(v)||N(0,I)) = ½[Σs²+‖m‖²−M−Σlog s²] 不缩放。梯度形态
    由单测有限差分钉（#118 族：梯度裁判=数值中心差分）。
    """
    batch = int(a_rows.shape[0])
    m = int(m_w.shape[0])
    s2 = np.exp(2.0 * log_s2)
    mu = a_rows @ m_w
    v_f = (a_rows ** 2) @ s2
    log_term = (-0.5 * np.log(2.0 * np.pi * noise_var)
                - ((y_batch - mu) ** 2 + v_f) / (2.0 * noise_var)).sum()
    elbo = (float(n_total) / batch) * float(log_term) - 0.5 * (
        float(s2.sum() + m_w @ m_w - m) - 2.0 * float(log_s2.sum()))
    grad_m = (float(n_total) / batch) * (
        a_rows.T @ (y_batch - mu)) / float(noise_var) - m_w
    c_j = (a_rows ** 2).sum(axis=0)
    grad_log_s2 = (-(float(n_total) / batch) * c_j * s2 / float(noise_var)
                   - (s2 - 1.0))
    return elbo, grad_m, grad_log_s2


@surrogate_registry.register("svgp")
class SvgpSurrogate(SurrogateModel):
    """变分稀疏 GP（诱导点路线）大规模代理（rff_gp 同档备选，D3）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）。
        n_inducing: 诱导点数 M（缺省 DEFAULT_N_INDUCING=128；≥1；
            M≥n 时取全部训练点=精确 GP 退化档）。
        seed: 随机种子（缺省 DEFAULT_SVGP_SEED；Z=seed+2/MLE 子样本
            =seed+1/小批排列=seed+3，同 seed 逐位复现）。
        ell_mode: "mle"（缺省，ℓ 由 gp_det.fit_mle 单源估）| "fixed"
            （config["ell"] 显式给）。
        ell: fixed 档的长度尺度（标量=各维同值，或逐维列表；任一 ≤0
            或非有限显式报错）。
        mle_subsample: ℓ-MLE 子样本上限（缺省 DEFAULT_MLE_SUBSAMPLE）。
        noise_var: 固定噪声方差（标准化单位，>0 有限；缺省 1e-2）。
        mode: "closed"（缺省，全批闭式最优 q(u)）| "minibatch"
            （mean-field 对角 S + Adam；fit_info["elbo"]=末批 ELBO，
            closed 档无训练轨迹记 None）。
        iters/batch_size/lr: minibatch 档超参（缺省 200/256/0.05）。
        inducing_init: "spread"（FPS 缺省）| "random"。
        metrics: 要建模的指标键列表（缺省 = fit 样本全部数值键并集，
            同 rff_gp 约定；有效点 <3 的键跳过不硬拟）。
    """

    KIND = "svgp"

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    # ── config 校验（负例契约，fit 期单点拦截） ──────────────────────

    def _resolve_fixed_ell(self, d: int) -> np.ndarray:
        raw = self.config.get("ell")
        if raw is None:
            raise ValueError('ell_mode="fixed" 需要 config["ell"]')
        if np.isscalar(raw):
            ell = np.full(d, float(raw))
        else:
            arr = np.asarray(raw, dtype=float)
            if arr.ndim != 1 or arr.size != d:
                raise ValueError(
                    f"fixed 档 ell 须为标量或长度 {d} 的列表，"
                    f"实得 shape={arr.shape}")
            ell = arr
        if not np.all(np.isfinite(ell)) or np.any(ell <= 0.0):
            raise ValueError(
                f"fixed 档 ℓ 须逐维为正有限（负例契约），实得 "
                f"{ell.tolist()}")
        return ell

    def _resolve_ell_mle(
        self, xu: np.ndarray, y: np.ndarray, mask: np.ndarray, seed: int,
    ) -> tuple[np.ndarray, int]:
        """ℓ-MLE 单源复用 gp_det.fit_mle（与 rff_gp 同约定）。

        n>cap 时在固定 seed+1 子样本上估（诚实近似，行数入 fit_info）；
        子样本内有效点 <3 时回退全量有效行（不静默空拟合）。
        """
        cap = int(self.config.get("mle_subsample", DEFAULT_MLE_SUBSAMPLE))
        idx_all = np.flatnonzero(mask)
        if int(mask.sum()) > cap:
            rng_sub = np.random.default_rng(seed + 1)
            idx = rng_sub.choice(xu.shape[0], size=int(cap), replace=False)
            rows = idx[mask[idx]]
            if rows.size < _MIN_FIT_POINTS:
                rows = idx_all
        else:
            rows = idx_all
        params = fit_mle(xu[rows], y[rows], kind="se",
                         optimize_nugget=False)
        return np.asarray(params["ell"], dtype=float), int(rows.size)

    def _fit_key_closed(
        self, z: np.ndarray, xu: np.ndarray, ys: np.ndarray,
        ell: np.ndarray, noise_var: float,
    ) -> dict[str, Any]:
        st = svgp_closed_posterior(z, xu, ys, noise_var, ell, 1.0)
        return {"constant": False, "mode": "closed", "z": z, "ell": ell,
                "l_mm": st["l_mm"], "l_b": st["l_b"], "m_w": st["m_w"],
                "noise_var": noise_var}

    def _fit_key_minibatch(
        self, z: np.ndarray, xu: np.ndarray, ys: np.ndarray,
        ell: np.ndarray, noise_var: float, seed: int,
    ) -> tuple[dict[str, Any], float]:
        iters = int(self.config.get("iters", DEFAULT_ITERS))
        batch_size = int(self.config.get("batch_size", DEFAULT_BATCH_SIZE))
        lr = float(self.config.get("lr", DEFAULT_LR))
        if iters < 1:
            raise ValueError(f"iters 须 ≥1（负例契约），实得 {iters}")
        if batch_size < 1:
            raise ValueError(
                f"batch_size 须 ≥1（负例契约），实得 {batch_size}")
        if not np.isfinite(lr) or lr <= 0.0:
            raise ValueError(f"lr 须为正有限（负例契约），实得 {lr}")
        m = int(z.shape[0])
        k_mm = se_ard_kernel(z, z, ell, 1.0)
        l_mm = _chol_pd(k_mm)
        k_mn = _kernel_nm(z, xu, ell, 1.0)
        a_mat = np.linalg.solve(l_mm, k_mn)                     # M×n
        n = int(xu.shape[0])
        batch = min(batch_size, n)
        m_w = np.zeros(m)
        log_s2 = np.full(m, -1.0)
        mm = np.zeros(m)
        vm = np.zeros(m)
        ml = np.zeros(m)
        vl = np.zeros(m)
        b1, b2, eps_a = 0.9, 0.999, 1e-8
        rng_mb = np.random.default_rng(seed + 3)
        elbo_final = float("nan")
        for t in range(1, iters + 1):
            idx = rng_mb.choice(n, size=batch, replace=False)
            elbo, g_m, g_ls = svgp_elbo_terms(
                a_mat[:, idx].T, ys[idx], m_w, log_s2, n, noise_var)
            mm = b1 * mm + (1 - b1) * g_m
            vm = b2 * vm + (1 - b2) * g_m ** 2
            ml = b1 * ml + (1 - b1) * g_ls
            vl = b2 * vl + (1 - b2) * g_ls ** 2
            m_w += lr * (mm / (1 - b1 ** t)) / (
                np.sqrt(vm / (1 - b2 ** t)) + eps_a)
            log_s2 += lr * (ml / (1 - b1 ** t)) / (
                np.sqrt(vl / (1 - b2 ** t)) + eps_a)
            elbo_final = float(elbo)
        return {"constant": False, "mode": "minibatch", "z": z, "ell": ell,
                "l_mm": l_mm, "m_w": m_w, "log_s2": log_s2,
                "noise_var": noise_var}, elbo_final

    # ── 契约面 ───────────────────────────────────────────────────────

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        n_inducing = int(self.config.get("n_inducing", DEFAULT_N_INDUCING))
        if n_inducing < 1:
            raise ValueError(
                f"n_inducing 须 ≥1（负例契约），实得 {n_inducing}")
        mode = str(self.config.get("mode", "closed"))
        if mode not in ("closed", "minibatch"):
            raise ValueError(
                f'mode 须为 "closed" 或 "minibatch"，实得 {mode!r}')
        ell_mode = str(self.config.get("ell_mode", "mle"))
        if ell_mode not in ("mle", "fixed"):
            raise ValueError(
                f'ell_mode 须为 "mle" 或 "fixed"，实得 {ell_mode!r}')
        inducing_init = str(self.config.get("inducing_init", "spread"))
        if inducing_init not in ("spread", "random"):
            raise ValueError(
                f'inducing_init 须为 "spread" 或 "random"，实得 '
                f"{inducing_init!r}")
        noise_var = float(self.config.get("noise_var", DEFAULT_NOISE_VAR))
        if not np.isfinite(noise_var) or noise_var <= 0.0:
            raise ValueError(
                f"noise_var 须为正有限（负例契约），实得 {noise_var}")
        if not samples:
            raise ValueError("samples 为空（n=0，负例契约），无法拟合")
        bounds_cfg = self.config.get("bounds")
        if not bounds_cfg:
            raise ValueError("config 缺 bounds（单元归一基准必填）")
        self.bounds = {k: tuple(v) for k, v in bounds_cfg.items()}
        self.names = sorted(self.bounds)
        self.n_inducing = n_inducing
        self.mode = mode
        self.ell_mode = ell_mode
        seed = int(self.config.get("seed", DEFAULT_SVGP_SEED))
        xu = np.array([self._unit_row(s["params"]) for s in samples])
        keys = self.config.get("metrics") or sorted({
            k for s in samples
            for k, v in s.get("metrics", {}).items()
            if isinstance(v, (int, float))})
        d = xu.shape[1]
        ell_fixed = (self._resolve_fixed_ell(d) if ell_mode == "fixed"
                     else None)
        z = svgp_inducing(xu, n_inducing, seed, inducing_init)
        self._models: dict[str, dict[str, Any]] = {}
        constant_keys: list[str] = []
        skipped_keys: list[str] = []
        ell_used: dict[str, list[float]] = {}
        mle_rows: dict[str, int] = {}
        elbo_used: dict[str, float] = {}
        m_eff_used: dict[str, int] = {}
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if int(mask.sum()) < _MIN_FIT_POINTS:
                skipped_keys.append(key)
                continue  # 键不存在/全 NaN——跳过不硬拟（家族约定）
            if ell_fixed is not None:
                ell = ell_fixed
                rows_used = int(mask.sum())
            else:
                ell, rows_used = self._resolve_ell_mle(xu, y, mask, seed)
            mle_rows[key] = rows_used
            ell_used[key] = ell.tolist()
            m_eff_used[key] = int(z.shape[0])
            ym = y[mask]
            y_mean = float(ym.mean())
            y_std = float(ym.std(ddof=1)) if ym.size > 1 else 0.0
            if y_std < _CONST_STD_FLOOR:
                # 常数目标：predict 常数、σ=0（残差方差解析为 0，非伪造）
                constant_keys.append(key)
                self._models[key] = {
                    "constant": True, "y_mean": y_mean, "y_std": 0.0}
                continue
            ys_std = (ym - y_mean) / y_std
            if mode == "closed":
                m_key = self._fit_key_closed(
                    z, xu[mask], ys_std, ell, noise_var)
                elbo_used[key] = None  # closed 档无 ELBO 训练轨迹
            else:
                m_key, elbo_v = self._fit_key_minibatch(
                    z, xu[mask], ys_std, ell, noise_var, seed)
                elbo_used[key] = elbo_v
            m_key["y_mean"] = y_mean
            m_key["y_std"] = y_std
            self._models[key] = m_key
        self.ell_used = ell_used
        self.mle_rows = mle_rows
        self.elbo_used = elbo_used
        info = self._mark_fitted(len(samples))
        info.update({
            "keys": [k for k in self._models],
            "skipped_keys": skipped_keys,
            "constant_keys": constant_keys,
            "n_inducing": int(z.shape[0]),
            "mode": mode,
            "ell_mode": ell_mode,
            "ell": ell_used,
            "mle_rows": mle_rows,
            "noise_var": noise_var,
            "inducing_init": inducing_init,
            "seed": seed,
            "elbo": elbo_used,
        })
        return info

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def _key_terms(self, params: dict[str, float], m: dict[str, Any],
                   ) -> np.ndarray:
        """单元空间预测面：t1 = L_MM⁻¹k（M，逐点 O(nM) 核行评估）。"""
        x = self._unit_row(params)[None, :]
        k_row = se_ard_kernel(m["z"], x, m["ell"], 1.0)[:, 0]
        return np.linalg.solve(m["l_mm"], k_row)

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        out: dict[str, Any] = {}
        for key, m in self._models.items():
            if m["constant"]:
                out[key] = float(m["y_mean"])
                continue
            t1 = self._key_terms(params, m)
            mu_u = float(t1 @ m["m_w"])
            out[key] = float(m["y_std"] * mu_u + m["y_mean"])
        return out

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """后验 σ（q(u) 变分后验潜函数标准差，非伪造）。

        σ(x) = y_std·√(1 − ‖L⁻¹k‖² + wᵀS_w w)；常数键 σ=0（残差方差
        解析为 0）。远点 k→0 ⇒ σ→y_std（先验），数据邻点 σ→0（内插）。
        """
        self._check_fitted()
        out: dict[str, float] = {}
        for key, m in self._models.items():
            if m["constant"]:
                out[key] = 0.0
                continue
            t1 = self._key_terms(params, m)
            if m["mode"] == "closed":
                t2 = np.linalg.solve(m["l_b"], t1)
                var_u = 1.0 - float(t1 @ t1) + float(t2 @ t2)
            else:
                s2 = np.exp(2.0 * np.asarray(m["log_s2"], dtype=float))
                var_u = 1.0 - float(t1 @ t1) + float(s2 @ (t1 * t1))
            out[key] = float(m["y_std"] * np.sqrt(max(var_u, 0.0)))
        return out
