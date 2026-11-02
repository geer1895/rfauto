"""代理键 ``ngo_stamp_rf``：RF 复数参数仿射 stamp 代理（NGO 三期，aurora_p D1）。

定位：green_op（T-N23，多端口叠加结构）与 green_stamp v1（T-O7，实数稳态
扩散参数仿射族）之后的第三种结构先验——**参数进算子**的 RF 复数形态：
Y(λ,ω)=Y₀(ω)+Σ_k λ_k·Y_k(ω)（复数节点导纳 stamp，``core/ngo_rf_stamp.
ComplexAffineStampFamily`` 单源）。本代理只学 **θ→stamp 系数**（系数头，
恒等参数化 Model 档——family 自产标签，预声明简化见内核 docstring）；
最终 S 由 Y(λ̂,ω) 的**精确线性求解**出（``solve_s_matrix`` 端接口径）——
铁律 7：网络永不直接产生 S 数值，网络误差只活在 K 维系数空间。

样本格式（SurrogateModel 契约同构）：
    samples = [{"params": {param: value}, ...}]   （标签 family 自产，
                                                   metrics 面不消费）
params 键=通道乘子名（bounds 键），值=无量纲乘子 λ_k（物理域 ≥0）；缺键
取界中点（green_op/pole_residue 同约定）；不可转 float 的行按"真机失败
trial"契约面跳过并如实计数（``n_skipped``）。

predict（SurrogateModel 契约标量面）：
- 逐 (i,j) 的带内 ``s{i}{j}_db_max_in_band`` / ``s{i}{j}_db_min_in_band``
  （P=2，紧凑命名，green_op 同款）；
- ``passivity``：``pole_residue.passivity_verdict`` 单源 verdict dict
  （**原样内嵌不复制公式**——σmax(S)≤1+tol 带内直判；对预测 S 栈实测，
  非无源如实报 passive=False 不修饰）；
- ``stamp_coefficients``：装配实际使用的 λ̂（dict；``clip_coefficients``
  缺省 True 时=系数头原始输出向 bounds 物理域 [lo,hi] 的投影——投影是
  装配前的物理域约束，如实记录；原始头输出经 ``predictor`` 属性可观测）。

多端口主面：``predict_matrix``（复数 S 栈 (n_freq,2,2)）。

确定性（AGENTS 7 / C4）：全链路固定 seed（``_StampMLP`` 内部 Generator，
不触全局 RNG），全批 Adam 无采样随机；同 config 同 samples 两跑 predict
逐位一致（测试钉住）。

诚实边界：
- 系数头=恒等参数化最小学习任务（结构先验承载频率面——见内核 docstring
  预声明简化 1）；域内 S 相对误差门在测试预声明（定标证据
  runs/aurora_p/d1/），不外推真机精度；
- 频率栅格锁定（训练栅格=预测栅格，栅格外不保证——不伪造）；
- 无原生逐点不确定度（uncertainty 返回 None，不伪造 σ）。

注册即生效（基类+注册表模式，规则 3）：``surrogate_registry.create(
"ngo_stamp_rf", config={...})``；纯增量键，既有 kind 消费面零改动。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.ngo_rf_stamp import ComplexAffineStampFamily, RfStampPredictor
from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry
from rfauto.optimization.surrogate.pole_residue import passivity_verdict

__all__ = ["NgoStampRfSurrogate"]

#: dB 下限（|S|=0 保护，与 green_op._DB_FLOOR 同值同语义）。
_DB_FLOOR = 1e-30


@surrogate_registry.register("ngo_stamp_rf")
class NgoStampRfSurrogate(SurrogateModel):
    """参数仿射 RF stamp 代理：θ→λ̂（系数头，被学）× 精确装配/求解（结构）。"""

    KIND = "ngo_stamp_rf"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        bounds = self.config.get("bounds")
        if not bounds:
            raise ValueError("NgoStampRfSurrogate：config['bounds'] 必填")
        parsed = {}
        for name, pair in bounds.items():
            lo, hi = float(pair[0]), float(pair[1])
            if not (hi > lo):
                raise ValueError(
                    f"NgoStampRfSurrogate：bounds[{name!r}] 须 lo<hi")
            if lo < 0.0:
                raise ValueError(
                    f"NgoStampRfSurrogate：bounds[{name!r}] 下界须 ≥0"
                    "（λ 为无源通道乘子，负值=有源面不进训练/预测域）")
            parsed[name] = (lo, hi)
        self.bounds = parsed
        self.param_names = sorted(self.bounds)
        self.n_params = len(self.param_names)
        grid = self.config.get("freq_grid_ghz")
        if grid is None or len(grid) != 2 or float(grid[1]) <= float(grid[0]):
            raise ValueError(
                "NgoStampRfSurrogate：config['freq_grid_ghz'] 须为 (f_lo, f_hi)"
                " 且 f_lo < f_hi")
        self.n_freq = int(self.config.get("n_freq", 8))
        if self.n_freq < 2:
            raise ValueError("NgoStampRfSurrogate：n_freq 须 ≥2")
        self.freq_grid_hz = np.linspace(float(grid[0]) * 1e9,
                                        float(grid[1]) * 1e9, self.n_freq)
        self.family = ComplexAffineStampFamily(
            n_grid=int(self.config.get("n_grid", 4)),
            n_blocks=self.n_params,
            port_z0=float(self.config.get("port_z0", 50.0)),
            lossless=bool(self.config.get("lossless", False)),
        )
        self.predictor = RfStampPredictor(
            self.family,
            lam_bounds=np.array([self.bounds[k] for k in self.param_names]),
            freq_grid_hz=self.freq_grid_hz,
            hidden=int(self.config.get("hidden", 32)),
            coef_hidden=int(self.config.get("coef_hidden", 16)),
            seed=int(self.config.get("seed", 20261101)),
            lr=float(self.config.get("lr", 2e-2)),
            epochs_inv=int(self.config.get("epochs_inv", 1500)),
            epochs_coef=int(self.config.get("epochs_coef", 800)),
            weight_decay=float(self.config.get("weight_decay", 1e-4)),
        )
        self.clip_coefficients = bool(self.config.get("clip_coefficients", True))

    # ── 内部 ──
    def _lam_row_of_params(self, params: dict[str, float]) -> np.ndarray:
        row = []
        for name in self.param_names:
            lo, hi = self.bounds[name]
            row.append(float(params.get(name, 0.5 * (lo + hi))))
        return np.array(row, dtype=float)

    def _project(self, lam_hat: np.ndarray) -> np.ndarray:
        """系数头原始输出向 bounds 物理域的投影（clip_coefficients=True）。"""
        if not self.clip_coefficients:
            return lam_hat
        lo = np.array([self.bounds[k][0] for k in self.param_names])
        hi = np.array([self.bounds[k][1] for k in self.param_names])
        return np.clip(lam_hat, lo, hi)

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """系数头+逆头训练（标签全部 family 自产——Model 档零外部数据面）。

        samples 行仅消费 ``params``（通道乘子 λ）；无样本/全部无效显式报错。
        返回 info：n_samples/n_skipped（契约面）+ 系数/逆头 RMSE 曲线尾与
        训练面 S 域回代 RMSE（结构臂在训练 λ 上的响应精度实测）。
        """
        if not samples:
            raise ValueError("NgoStampRfSurrogate.fit：无样本")
        rows: list[np.ndarray] = []
        n_skipped = 0
        for sample in samples:
            params = sample.get("params") if isinstance(sample, dict) else None
            if not isinstance(params, dict):
                n_skipped += 1
                continue
            try:
                row = self._lam_row_of_params(params)
            except (TypeError, ValueError):
                n_skipped += 1
                continue
            if not np.all(np.isfinite(row)):
                n_skipped += 1
                continue
            rows.append(row)
        if not rows:
            raise ValueError(
                "NgoStampRfSurrogate.fit：无有效 params 样本（键须覆盖 "
                f"{self.param_names}）")
        info = self._mark_fitted(len(rows))
        fit_info = self.predictor.fit(rows)
        lam_bounds = self.predictor.lam_bounds
        sq_sum = 0.0
        s_sum = 0.0
        s_max = 0.0
        for row in rows:
            lam_hat = self._project(self.predictor.predict_coefficients(row))
            s_hat = self.family.solve_s_matrix(lam_hat, self.freq_grid_hz)
            s_true = self.family.solve_s_matrix(row, self.freq_grid_hz)
            scale = float(np.linalg.norm(s_true)) or 1e-300
            rel = float(np.linalg.norm(s_hat - s_true)) / scale
            sq_sum += rel * rel
            s_max = max(s_max, rel)
            s_sum += rel
        mid = 0.5 * (lam_bounds[:, 0] + lam_bounds[:, 1])
        lam_mid = mid
        s_mid = self.family.solve_s_matrix(lam_mid, self.freq_grid_hz)
        info.update({
            "n_skipped": n_skipped,
            "n_params": self.n_params,
            "n_grid": self.family.n_grid,
            "n_freq": self.n_freq,
            "n_ports": self.family.n_ports,
            "clip_coefficients": self.clip_coefficients,
            "coef_rmse_final": fit_info["coef_rmse_final"],
            "coef_rmse_curve": fit_info["coef_rmse_curve"],
            "inv_rmse_final": fit_info["inv_rmse_final"],
            "inv_rmse_curve": fit_info["inv_rmse_curve"],
            "train_rel_err_s_mean": s_sum / len(rows),
            "train_rel_err_s_max": s_max,
            "train_rel_err_s_rms": float(np.sqrt(sq_sum / len(rows))),
            "midpoint_rel_err_s": float(np.linalg.norm(
                self.family.solve_s_matrix(
                    self._project(self.predictor.predict_coefficients(lam_mid)),
                    self.freq_grid_hz)
                - s_mid)) / max(float(np.linalg.norm(s_mid)), 1e-300),
        })
        return info

    # ── 预测面 ──
    def predict_matrix(self, params: dict[str, float]) -> np.ndarray:
        """预测复数 S 栈 (n_freq, 2, 2)：系数头出 λ̂（物理域投影）→ Y(λ̂,ω)
        精确装配 → ``solve_s_matrix`` 端接口径精确求解（铁律 7）。"""
        if not self._fitted:
            raise RuntimeError("NgoStampRfSurrogate.predict_matrix：先 fit")
        row = self._lam_row_of_params(dict(params))
        if not np.all(np.isfinite(row)):
            raise ValueError(
                "NgoStampRfSurrogate.predict_matrix：params 含非有限值")
        lam_hat = self._project(self.predictor.predict_coefficients(row))
        return self.family.solve_s_matrix(lam_hat, self.freq_grid_hz)

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        """契约标量面：逐 (i,j) 带内 dB 摘要 + ``passivity`` 单源 verdict
        + ``stamp_coefficients``（装配实际使用的 λ̂）。"""
        row = self._lam_row_of_params(dict(params))
        lam_hat = self._project(self.predictor.predict_coefficients(row))
        s = self.family.solve_s_matrix(lam_hat, self.freq_grid_hz)
        db = 20.0 * np.log10(np.maximum(np.abs(s), _DB_FLOOR))
        out: dict[str, Any] = {}
        for i in range(self.family.n_ports):
            for j in range(self.family.n_ports):
                name = f"s{i + 1}{j + 1}"
                out[f"{name}_db_max_in_band"] = float(db[:, i, j].max())
                out[f"{name}_db_min_in_band"] = float(db[:, i, j].min())
        out["passivity"] = passivity_verdict(s)
        out["stamp_coefficients"] = {
            name: float(lam_hat[k])
            for k, name in enumerate(self.param_names)
        }
        return out

    def uncertainty(self, params: dict[str, float]) -> None:
        """无原生逐点不确定度（单头确定性模型，不伪造 σ——#122 诚实纪律）。"""
        return None
