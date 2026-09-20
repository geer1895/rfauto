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
        MFK = self._ensure_smt()
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
            mfk = MFK(theta0=theta0, print_global=False)
            mfk.set_training_values(X_lo[mask_lo], y_lo[mask_lo], name=0)
            mfk.set_training_values(X_hi[mask_hi], y_hi[mask_hi])
            mfk.train()
            self.models[key] = mfk
        return self._mark_fitted(len(samples))

    def _check_fitted(self) -> None:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")

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
