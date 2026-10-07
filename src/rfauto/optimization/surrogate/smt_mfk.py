"""SMT MFK 多保真 co-kriging（阶段 6.2：三保真融合代理注册表接入）。

分层融合：海量低保真点（fake，几乎免费）+ 少量高保真点（openEMS/HFSS）
→ AR1 自回归 co-kriging——"HFSS 太贵、openEMS 有系统差、fake 太糙"
三难的方法学正解（roadmap §6.2）。

契约：
    model = SMTMultiFidelitySurrogate(config={
        "bounds": {...},
        "low_fi_samples": [...],   # 低保真样本集（fake）
        "low_fi_scale": 1.0,       # 可选：低保真方差折减
    })
    model.fit(high_samples)        # 高保真样本（openEMS/HFSS 真采样）
    pred = model.predict(params)   # 融合预测
依赖可选 extra（smt）；未安装显式报错。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import SurrogateModel, surrogate_registry


def _numeric_keys(samples: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for s in samples:
        keys |= {k for k, v in s.get("metrics", {}).items()
                 if isinstance(v, (int, float))}
    return keys


def _new_mfk(cfg: dict[str, Any], theta0: list[float]) -> Any:
    """按 config 构造 MFK（条件透传，df6③：只传非缺省 kwarg，不破旧调用方）。

    rho_regr（OP-7 暴露面）：SMT 选项，values=("constant","linear",
    "quadratic")，缺省 constant——诊断面只对 constant 出标量 ρ。
    """
    from smt.applications import MFK

    kwargs: dict[str, Any] = {"theta0": theta0, "print_global": False}
    if "rho_regr" in cfg:
        kwargs["rho_regr"] = str(cfg["rho_regr"])
    if "optim_var" in cfg:
        kwargs["optim_var"] = bool(cfg["optim_var"])
    return MFK(**kwargs)


@surrogate_registry.register("smt_mfk")
class SMTMultiFidelitySurrogate(SurrogateModel):
    """SMT MFK 双保真 co-kriging（low=fake / high=openEMS·HFSS）。"""

    KIND = "smt_mfk"

    def _ensure_smt(self):
        try:
            from smt.applications import MFK
            return MFK
        except ImportError as exc:
            raise RuntimeError(
                "smt_mfk 需要 SMT 2.x：pip install rfauto[smt] 或 pip install smt"
            ) from exc

    def _unit_row(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self._ensure_smt()  # 缺席早失败（构造在 _new_mfk，逐指标循环前）
        cfg = self.config
        self.bounds = {k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names = sorted(self.bounds)
        low_samples = list(cfg.get("low_fi_samples") or [])
        if not low_samples:
            raise ValueError("smt_mfk 需要 config.low_fi_samples（低保真样本集）")
        if len(samples) < 2:
            raise ValueError("高保真样本点不足（需 ≥2）")

        keys = cfg.get("metrics") or _numeric_keys(samples)
        self.metric_keys = sorted(keys)
        X_hi = np.array([self._unit_row(s["params"]) for s in samples])
        X_lo = np.array([self._unit_row(s["params"]) for s in low_samples])
        self._last_hi_samples = list(samples)

        theta0 = [float(cfg.get("theta0", 1e-2))] * len(self.names)
        self.models: dict[str, Any] = {}
        for key in self.metric_keys:
            y_hi = np.array([float(s["metrics"].get(key, np.nan))
                             for s in samples])
            y_lo = np.array([float(s["metrics"].get(key, np.nan))
                             for s in low_samples])
            mask_hi, mask_lo = np.isfinite(y_hi), np.isfinite(y_lo)
            if mask_hi.sum() < 2 or mask_lo.sum() < 3:
                continue
            mfk = _new_mfk(cfg, theta0)
            mfk.set_training_values(X_lo[mask_lo], y_lo[mask_lo], name=0)
            mfk.set_training_values(X_hi[mask_hi], y_hi[mask_hi])
            mfk.train()
            self.models[key] = mfk
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def fidelity_diagnostics(
        self, x: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """OP-7（round16 §六）：MFK 保真相关性诊断暴露（ρ / σ²_ρ + 弱相关告警）。

        AR(1) co-kriging 的层级融合假设"高保真 ≈ ρ·低保真 + δ-GP"——
        ρ≈0 意味低保真通道与高保真几乎不相关（错族样本/口径错位），
        融合退化为纯高保真 GP 甚至被低保真注入伪差。本方法逐指标暴露：

        - ``rho``：SMT ``rho_regr="constant"`` 档的 AR1 系数（实测源：
          ``optimal_par[i]["beta"][0, 0]``，smt 2.14.1 mfk.py——beta 首项
          即常数回归 g=[1] 的系数；rho_regr≠constant 时无标量 ρ，如实
          报 ``rho=None`` + ``reason``，不编数）；
        - ``sigma2_rho``：ρ 的 kriging 方差（smt ``predict_variances_
          all_levels`` 第二返回值在代表点 x 处取值；x 缺省=高保真训练
          均值点）；
        - ``warn``：|rho| < ``rho_warn_threshold``（config，缺省 0.1）
          时 True，附 ``warning`` 文案——调用方（日志/报告）消费，本模块
          只读数不告警副作用。

        Returns:
            {"x": 代表点, "rho_warn_threshold": float, "metrics":
            {metric: {"rho": float|None, "sigma2_rho": float|None,
            "warn": bool, "warning": str|None}}, "warn": bool}
        """
        self._check_fitted()
        cfg = self.config
        rho_regr = str(cfg.get("rho_regr", "constant"))
        thr = float(cfg.get("rho_warn_threshold", 0.1))
        x_row = (np.atleast_2d(self._unit_row(x)) if x is not None
                 else np.mean(
                     np.array([self._unit_row(s["params"])
                               for s in self._last_hi_samples]), axis=0,
                     keepdims=True))
        out: dict[str, Any] = {
            "x": {n: float(v) for n, v in zip(self.names, x_row[0], strict=True)},
            "rho_warn_threshold": thr,
            "metrics": {},
        }
        any_warn = False
        for key, mfk in self.models.items():
            entry: dict[str, Any] = {"rho": None, "sigma2_rho": None,
                                     "warn": False, "warning": None}
            if rho_regr != "constant":
                entry["warning"] = (
                    f"rho_regr={rho_regr!r} 非常数回归，无标量 ρ 可暴露"
                    "（诚实缺省：改回 rho_regr='constant' 以启用 ρ 诊断）")
            else:
                try:
                    beta = mfk.optimal_par[1]["beta"]
                    rho = float(np.asarray(beta).ravel()[0])
                    entry["rho"] = rho
                    _mse, s2r = mfk.predict_variances_all_levels(x_row)
                    if s2r:
                        entry["sigma2_rho"] = float(np.asarray(s2r[0]).ravel()[0])
                    if abs(rho) < thr:
                        entry["warn"] = True
                        entry["warning"] = (
                            f"|ρ|={abs(rho):.3g} < 阈值 {thr}：低保真与高保真"
                            "相关性弱——低保真样本可能错族/口径错位，融合"
                            "不可信，建议核查 low_fi_samples 或去掉该通道")
                except (IndexError, KeyError, ValueError, TypeError) as exc:
                    entry["warning"] = f"ρ 提取失败（结构不符，如实降级）: {exc!r}"
            any_warn = any_warn or bool(entry["warn"])
            out["metrics"][key] = entry
        out["warn"] = any_warn
        return out

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        self._check_fitted()
        x = np.atleast_2d(self._unit_row(params))
        return {key: float(mfk.predict_values(x)[0, 0])
                for key, mfk in self.models.items()}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        self._check_fitted()
        x = np.atleast_2d(self._unit_row(params))
        out: dict[str, float] = {}
        for key, mfk in self.models.items():
            var = float(mfk.predict_variances(x)[0, 0])
            out[key] = float(np.sqrt(max(var, 0.0)))
        return out
