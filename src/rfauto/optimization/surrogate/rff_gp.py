"""RFF 随机傅里叶特征大规模 GP（注册键 "rff_gp"，aurora_n W3 T-N21）。

XD-4 条件件升格的最小形态（M）：数据集 >10k 时精确 GP（gp_det，O(n³)）
不可承载，走**随机傅里叶特征（Random Fourier Features, RFF）+ 线性岭
读出**路线——O(n·D²) 训练 / O(D+d) 逐点评估，D=特征数旋钮（缺省 512）。
消费预留（XD-4 条件面）：>10k 建议档——样本量越过精确 GP 门槛时由
本键或全量变分路线（SVGP/VFF 族）承载。

法源（两源 2026-10-30 实读核对）：
- Rahimi, A. & Recht, B., "Random Features for Large-Scale Kernel
  Machines", NIPS 2007（proceedings.neurips.cc 全文实读）：
  · Bochner 定理（论文 Thm 1）：连续平移不变核 k(x,y)=k(x−y) 正定 ⟺
    k(δ) 是某非负测度的 Fourier 变换——SE 核的谱密度是高斯
    p(ω)=N(0, diag(1/ℓ²))（ARD 时逐维 ℓ_j）；
  · 随机特征（论文 §3 原文）："zω(x) = √2·cos(ω′x+b), where ω is
    drawn from p(ω) and b is drawn uniformly from [0,2π]" 满足
    E[zω(x)ᵀzω(y)] = k(x,y)；D 个特征拼接按 1/√D 归一降方差
    （本件紧凑形 z(x)=√(2/D)·[cos(ωⱼᵀx+bⱼ)]_{j=1..D}，逐分量等价）；
  · 读出（论文 §5）：岭回归 min_w ‖Zᵀw−y‖²+λ‖w‖²，评估 O(D+d)；
  · 维数律 D=O(d·ε⁻²·log ε⁻²)（§1，一致逼近界 Claim 1）。
- Hensman, J., Durrande, N. & Solin, A., "Variational Fourier Features
  for Gaussian Processes", JMLR 18(151):1−52, 2018（jmlr.org v18/
  16-579 摘要页实读）：变分+谱表示路线（VFF/SVGP 族）——谱特征近似
  只需单遍数据（O(NM)，M=特征数），4M 训练点分钟级；本件取同族
  "随机特征"谱系的最小形态（蒙特卡洛谱采样，非变分后验），XD-4
  全量变分升级位的语境锚。

诚实边界（#122）：
- **σ 是近似**：uncertainty() 返回线性特征空间贝叶斯岭回归的解析
  预测方差 σ̂²·z(x)ᵀ(ZᵀZ+λI)⁻¹z(x)（σ̂²=标准化目标残差方差，
  自由度取 n−1 保守口径）——两层近似（随机特征蒙特卡洛 + 线性读出）
  后的近似 σ，**非** gp_det 精确 GP 后验， docstring 如实注明；
- **ℓ 单源复用**（任务书）：lengthscale 口径不复制实现——MLE 档
  （缺省）直接调 gp_det.fit_mle（同初值/同 L-BFGS-B/同口径，n≤
  mle_subsample 时与 gp_det 消费面逐位同源）；n>cap 时在固定 seed
  子样本上估（>10k 档的必要妥协，诚实近似，fit_info 记
  mle_rows=n_sub）；固定档 ell_mode="fixed" 由 config 显式给 ℓ>0；
- 只支持 SE（RBF）核（Bochner 谱=高斯，闭式可采样）；matern52 的
  谱非高斯不在本件（无 kernel 键，如实不做）；输入单元归一 [0,1]^d
  由 bounds 承担（家族口径，同 warped_kriging）。

确定性（红线）：特征采样走 np.random.default_rng(seed)（特征
ω/b 用 seed、MLE 子样本用 seed+1，两路独立固定）——同 seed 同数据
fit/predict/uncertainty 逐位复现；岭解 np.linalg.solve 同机确定。

负例契约（任务书验收④）：n_features<1 / 样本数=0 / 固定档 ℓ≤0
（标量或逐维任一）显式 ValueError，不静默退化。

用法::

    model = surrogate_registry.create("rff_gp", config={
        "bounds": {"a": (0, 1), "b": (0, 2)},  # 必填，单元归一基准
        "n_features": 512,       # D（XD-4 >10k 档建议 ≥512）
        "seed": 20261030,        # 缺省 DEFAULT_RFF_SEED
        "ell_mode": "mle",       # "mle"（缺省）| "fixed"
        # "ell": 0.3,            # 仅 fixed 档：标量或逐维列表，>0
        "mle_subsample": 256,    # ℓ-MLE 子样本上限（n 超过才截断）
    })
    info = model.fit([{"params": {...}, "metrics": {"s21_db": ...}}])
    v = model.predict({"a": 0.5, "b": 1.0})      # {"s21_db": float}
    s = model.uncertainty({"a": 0.5, "b": 1.0})  # 近似 σ（见诚实边界）
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.gp_det import fit_mle

__all__ = [
    "DEFAULT_RFF_SEED",
    "RffGPSurrogate",
    "fourier_features",
    "sample_rff",
]

#: 缺省随机种子（确定性红线：显式缺省值，非调用方隐藏态）
DEFAULT_RFF_SEED = 20261030

#: ℓ-MLE 子样本缺省上限（n>cap 时 fit_mle 在固定 seed 子样本上估，
#: O(n³) 门槛的诚实近似档；n≤cap 与 gp_det 消费面逐位同源）
DEFAULT_MLE_SUBSAMPLE = 256

#: 有效点少于此数的指标键跳过不硬拟（家族口径，同 smt_kriging/
#: warped_kriging 的 <3 约定）
_MIN_FIT_POINTS = 3

#: 目标标准差低于此阈值视为常数键（退化分支：predict 常数、σ=0——
#: 常数目标下残差方差解析为 0，非伪造，fit_info["constant_keys"] 记录）
_CONST_STD_FLOOR = 1e-12


def sample_rff(
    ell: np.ndarray, n_features: int, seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """谱采样（Rahimi & Recht 2007 §3）：返回 (omega, b)。

    omega: D×d，第 j 列 ~ N(0, 1/ℓ_j²)（SE 核谱密度，ARD 逐维）；
    b: D，~ U[0, 2π)。固定 (ell, n_features, seed) 逐位复现。
    """
    ell = np.asarray(ell, dtype=float)
    if ell.ndim != 1 or ell.size < 1:
        raise ValueError(f"ell 须为一维非空向量，实得 shape={ell.shape}")
    if not np.all(np.isfinite(ell)) or np.any(ell <= 0.0):
        raise ValueError(f"ell 须逐维为正有限，实得 {ell.tolist()}")
    d = int(ell.size)
    rng = np.random.default_rng(seed)
    omega = rng.standard_normal((int(n_features), d)) / ell[None, :]
    bias = rng.uniform(0.0, 2.0 * np.pi, int(n_features))
    return omega, bias


def fourier_features(
    x: np.ndarray, omega: np.ndarray, b: np.ndarray,
) -> np.ndarray:
    """随机傅里叶特征 z(x)=√(2/D)·[cos(ωⱼᵀx+bⱼ)]（x: n×d → n×D）。

    E[z(x)ᵀz(y)] = k_se(x, y)（Bochner/无偏性，Rahimi & Recht 2007
    式 (2) 的紧凑 cos 形）。
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    d_feat = int(omega.shape[0])
    return np.sqrt(2.0 / d_feat) * np.cos(x @ omega.T + b[None, :])


@surrogate_registry.register("rff_gp")
class RffGPSurrogate(SurrogateModel):
    """RFF 特征 + 岭读出的大规模 GP 近似代理（XD-4 >10k 条件件，M 档）。

    config:
        bounds: {param: (low, high)}（必填，单元归一化基准）。
        n_features: 特征数 D（缺省 512；<1 显式报错）。
        seed: 随机种子（缺省 DEFAULT_RFF_SEED；同 seed 逐位复现）。
        ell_mode: "mle"（缺省，ℓ 由 gp_det.fit_mle 单源估）| "fixed"
            （config["ell"] 显式给）。
        ell: fixed 档的长度尺度（标量=各维同值，或逐维列表；任一 ≤0
            或非有限显式报错）。
        mle_subsample: ℓ-MLE 子样本上限（缺省 DEFAULT_MLE_SUBSAMPLE；
            n≤cap 逐位同源 gp_det 消费面，n>cap 固定 seed 子样本）。
        ridge_rel: 相对岭正则（缺省 1e-6，λ=ridge_rel·n——镜像 gp_det
            固定 nugget/var 比 1e-6 量级口径）。
        metrics: 要建模的指标键列表（缺省 = fit 样本全部数值键并集，
            同 smt_kriging 约定；有效点 <3 的键跳过不硬拟）。
    """

    KIND = "rff_gp"

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
        """ℓ-MLE 单源复用 gp_det.fit_mle（原始 y 标度，逐位同源口径）。

        n>cap 时在固定 seed+1 子样本上估（诚实近似，行数入 fit_info）；
        子样本内有效点 <3 时回退全量有效行（不静默空拟合）。
        """
        cap = int(self.config.get("mle_subsample", DEFAULT_MLE_SUBSAMPLE))
        idx_all = np.flatnonzero(mask)
        if mask.sum() > cap:
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

    # ── 契约面 ───────────────────────────────────────────────────────

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        n_features = int(self.config.get("n_features", 512))
        if n_features < 1:
            raise ValueError(f"n_features 须 ≥1（负例契约），实得 "
                             f"{n_features}")
        ridge_rel = float(self.config.get("ridge_rel", 1e-6))
        if not np.isfinite(ridge_rel) or ridge_rel <= 0.0:
            raise ValueError(f"ridge_rel 须为正有限，实得 {ridge_rel}")
        ell_mode = str(self.config.get("ell_mode", "mle"))
        if ell_mode not in ("mle", "fixed"):
            raise ValueError(
                f'ell_mode 须为 "mle" 或 "fixed"，实得 {ell_mode!r}')
        if not samples:
            raise ValueError("samples 为空（n=0，负例契约），无法拟合")
        bounds_cfg = self.config.get("bounds")
        if not bounds_cfg:
            raise ValueError("config 缺 bounds（单元归一基准必填）")
        self.bounds = {k: tuple(v) for k, v in bounds_cfg.items()}
        self.names = sorted(self.bounds)
        self.n_features = n_features
        self.ell_mode = ell_mode
        seed = int(self.config.get("seed", DEFAULT_RFF_SEED))
        xu = np.array([self._unit_row(s["params"]) for s in samples])
        keys = self.config.get("metrics") or sorted({
            k for s in samples
            for k, v in s.get("metrics", {}).items()
            if isinstance(v, (int, float))})
        d = xu.shape[1]
        ell_fixed = (self._resolve_fixed_ell(d) if ell_mode == "fixed"
                     else None)
        self._models: dict[str, dict[str, Any]] = {}
        constant_keys: list[str] = []
        skipped_keys: list[str] = []
        ell_used: dict[str, list[float]] = {}
        mle_rows: dict[str, int] = {}
        for key in keys:
            y = np.array([float(s["metrics"].get(key, np.nan))
                          for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < _MIN_FIT_POINTS:
                skipped_keys.append(key)
                continue  # 键不存在/全 NaN——跳过不硬拟（家族约定）
            if ell_fixed is not None:
                ell = ell_fixed
                rows_used = int(mask.sum())
            else:
                ell, rows_used = self._resolve_ell_mle(xu, y, mask, seed)
            mle_rows[key] = rows_used
            ell_used[key] = ell.tolist()
            omega, bias = sample_rff(ell, n_features, seed)
            z_all = fourier_features(xu, omega, bias)
            zm = z_all[mask]
            ym = y[mask]
            y_mean = float(ym.mean())
            y_std = float(ym.std(ddof=1)) if ym.size > 1 else 0.0
            if y_std < _CONST_STD_FLOOR:
                # 常数目标：predict 常数、σ=0（残差方差解析为 0，非伪造）
                constant_keys.append(key)
                self._models[key] = {
                    "constant": True, "y_mean": y_mean, "y_std": 0.0}
                continue
            ys = (ym - y_mean) / y_std
            n_m = int(ym.size)
            lam = ridge_rel * n_m
            a_mat = zm.T @ zm + lam * np.eye(n_features)
            w_vec = np.linalg.solve(a_mat, zm.T @ ys)
            resid = zm @ w_vec - ys
            s2 = float(resid @ resid / max(n_m - 1, 1))
            self._models[key] = {
                "constant": False, "omega": omega, "b": bias, "w": w_vec,
                "A": a_mat, "sigma2": s2, "y_mean": y_mean,
                "y_std": y_std}
        self.ell_used = ell_used
        self.mle_rows = mle_rows
        info = self._mark_fitted(len(samples))
        info.update({
            "keys": [k for k in self._models],
            "skipped_keys": skipped_keys,
            "constant_keys": constant_keys,
            "n_features": n_features,
            "ell_mode": ell_mode,
            "ell": ell_used,
            "mle_rows": mle_rows,
            "ridge_rel": ridge_rel,
        })
        return info

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def _feature_row(self, params: dict[str, float], m: dict[str, Any],
                    ) -> np.ndarray:
        x = self._unit_row(params)[None, :]
        return fourier_features(x, m["omega"], m["b"])[0]

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        out: dict[str, Any] = {}
        for key, m in self._models.items():
            if m["constant"]:
                out[key] = float(m["y_mean"])
                continue
            z = self._feature_row(params, m)
            out[key] = float(m["y_mean"] + m["y_std"] * float(z @ m["w"]))
        return out

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """近似 σ（诚实边界）：岭回归预测方差解析形开方，非精确 GP 后验。

        σ(x) = y_std·√(σ̂²·z(x)ᵀ(ZᵀZ+λI)⁻¹z(x))；常数键 σ=0（残差方差
        解析为 0）。
        """
        self._check_fitted()
        out: dict[str, float] = {}
        for key, m in self._models.items():
            if m["constant"]:
                out[key] = 0.0
                continue
            z = self._feature_row(params, m)
            var_std = m["sigma2"] * float(z @ np.linalg.solve(m["A"], z))
            out[key] = float(m["y_std"] * np.sqrt(max(var_std, 0.0)))
        return out
