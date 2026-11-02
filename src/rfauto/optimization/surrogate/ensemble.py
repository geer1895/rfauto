"""LOOCV 加权集成代理（注册键 "ensemble"，aurora_n W1-C T-N6）。

一句话：把已注册的多个代理（poly_ridge/nn/gbdt/smt_kriging 等可创建面）
各自在留一交叉验证（LOOCV）下的 Spearman ρ 做 softmax 加权，对逐指标
预测做**确定性**凸组合；成员间预测离散度（std 或 max−min）作为免费的
epistemic σ 透出 ``uncertainty()``（base.py 契约——poly_ridge/gbdt 等
std=None 档借此获得"模型族间分歧"意义的不确定度，不伪造高斯 σ）。

权重单源（提案口径）：``loocv_rho``（poly_ridge.py 公开 API，包门面
re-export）——本模块不内联任何 LOOCV/秩相关数学。每个成员的 ρ 由其在
同一样本集上的 LOOCV 折外预测 cost 与实际 cost 的秩相关给出；权重
w_i = exp(ρ_i/T)/Σ_j exp(ρ_j/T)（T=softmax_temperature，缺省 1.0；
softmax 对 ρ 整体平移不变，ρ∈[−1,1] 直接进指数）。

诚实契约（提案负例）：
- 单成员 fit/LOOCV 失败 → **按权重剔除**并 fit_info 如实记录
  （members[i].status="dropped" + error 原文），不静默塌缩；
- 全部成员失败 → 显式 RuntimeError（不产出无成员的空壳集成）；
- 仅 1 席幸存 → 允许但 fit_info 记 n_members_effective=1 +
  single_member_warning（离散度 σ 恒 0 的语义如实标注）。

确定性（红线）：权重与预测只依赖样本数据 + 显式配置——LOOCV 闭式折、
softmax 闭式、成员自身确定性（poly_ridge 闭式解/nn 固定种子/gbdt
subsample=1.0）→ 同配置同样本两次 fit 权重与预测逐位相等。

用法::

    model = surrogate_registry.create("ensemble", config={
        "bounds": {"x": (0.0, 1.0)},
        "members": ["poly_ridge", "nn",
                    {"kind": "gbdt", "config": {"n_estimators": 50}}],
        # 可选：rho_metric（LOOCV 裁判指标键，缺省=样本唯一数值指标键）、
        # softmax_temperature、dispersion("std"|"range")、eval_indices
    })
    info = model.fit(samples)   # members 权重/剔除记录在 info["members"]
    y = model.predict(params)   # 逐指标加权平均
    sigma = model.uncertainty(params)  # 逐指标成员间离散度

规模边界：单次 fit 的权重测量=每成员一次 LOOCV（O(n) 次成员拟合，
n≲100 毫秒-秒级）；若调用方再对 ensemble **整体**做 LOOCV（如 loocv_rho
套 ensemble 工厂），每折都会重跑全部成员 LOOCV → O(n²·m) 次成员拟合
（n=40、m=4 ≈ 6400 次）——纯闭式成员（poly_ridge）可承受，GP/NN 成员
时建议 n≲30 或 eval_indices 收窄折面。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)
from rfauto.optimization.surrogate.poly_ridge import loocv_rho

__all__ = ["EnsembleSurrogate"]

#: 离散度档位（config["dispersion"]；std=成员间总体标准差，range=max−min）
_DISPERSION_KINDS = ("std", "range")

#: LOOCV ρ 无意义的最小样本数（loocv_rho 内部同口径，<4 返回 ok=False）
_MIN_LOOCV_SAMPLES = 4


def _softmax(rhos: list[float], temperature: float) -> list[float]:
    """数值稳定 softmax（平移不变；同输入同输出，确定性）。"""
    t = max(float(temperature), 1e-12)
    scaled = [r / t for r in rhos]
    m = max(scaled)
    exps = [math.exp(v - m) for v in scaled]
    s = sum(exps)
    return [e / s for e in exps]


@surrogate_registry.register("ensemble")
class EnsembleSurrogate(SurrogateModel):
    """LOOCV ρ softmax 加权的确定性代理集成（SurrogateModel 契约）。

    config:
        bounds: {param: (low, high)}（必填；注入每个成员工厂的 config）
        members: 成员清单（必填，非空）；元素 = 注册键字符串或
            {"kind": 键, "config": 成员私有 config}；成员 config 会与
            {"bounds": bounds} 合并（成员显式给出的键优先）。"ensemble"
            自嵌套显式拒绝。
        rho_metric: LOOCV Spearman ρ 的裁判指标键（缺省 None = 样本集中
            恰有一个数值指标键时自动取之，多于一个显式 ValueError——
            不替用户猜裁判面）
        softmax_temperature: 权重锐度（缺省 1.0，须 >0 有限；→0 收敛到
            argmax 独占，→∞ 收敛到均匀权重）
        dispersion: 离散度档位（缺省 "std"；"range"=max−min）
        eval_indices: 透传 loocv_rho 的折面下标（缺省 None=全样本留一；
            T-N2 语义——虚拟样本进训练集不进裁判折面）
        metrics: 透传各成员的指标键白名单（缺省 None=各成员自决）
    """

    KIND = "ensemble"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        cfg = self.config
        bounds = cfg.get("bounds")
        if not isinstance(bounds, dict) or not bounds:
            raise ValueError(
                "ensemble 需要 config['bounds']（非空 {param: (low, high)}，"
                "注入各成员工厂）")
        self._bounds: dict[str, tuple[float, float]] = {
            k: tuple(v) for k, v in bounds.items()}
        members = cfg.get("members")
        if not isinstance(members, (list, tuple)) or not members:
            raise ValueError(
                "ensemble 需要 config['members']（非空成员清单，元素为注册键"
                "字符串或 {kind, config} dict）")
        specs: list[tuple[str, dict[str, Any]]] = []
        for m in members:
            if isinstance(m, str):
                kind, mcfg = m, {}
            elif isinstance(m, dict):
                kind = m.get("kind")
                mcfg = dict(m.get("config") or {})
            else:
                raise ValueError(f"ensemble 成员元素非法: {m!r}")
            if not kind or not isinstance(kind, str):
                raise ValueError(f"ensemble 成员缺 'kind' 键: {m!r}")
            if kind == self.KIND:
                raise ValueError("ensemble 不可嵌套自身（members 含 'ensemble'）")
            specs.append((kind, mcfg))
        self._member_specs = specs
        rho_metric = cfg.get("rho_metric")
        if rho_metric is not None and not isinstance(rho_metric, str):
            raise ValueError(f"rho_metric 须为 str 或 None，得 {rho_metric!r}")
        self._rho_metric: str | None = rho_metric
        temp = cfg.get("softmax_temperature", 1.0)
        if isinstance(temp, bool) or not isinstance(temp, (int, float)) \
                or not math.isfinite(float(temp)) or float(temp) <= 0.0:
            raise ValueError(
                f"softmax_temperature 须为 >0 的有限数，得 {temp!r}")
        self._temperature = float(temp)
        dispersion = cfg.get("dispersion", "std")
        if dispersion not in _DISPERSION_KINDS:
            raise ValueError(
                f"dispersion 须为 {_DISPERSION_KINDS} 之一，得 {dispersion!r}")
        self._dispersion = dispersion
        eval_idx = cfg.get("eval_indices")
        if eval_idx is not None and (not isinstance(eval_idx, (list, tuple))
                                     or not all(
                                         isinstance(i, int)
                                         and not isinstance(i, bool)
                                         for i in eval_idx)):
            raise ValueError(
                f"eval_indices 须为整数列表或 None，得 {eval_idx!r}")
        self._eval_indices: list[int] | None = (
            [int(i) for i in eval_idx] if eval_idx is not None else None)
        metrics = cfg.get("metrics")
        if metrics is not None and (not isinstance(metrics, (list, tuple))
                                    or not all(isinstance(m, str)
                                               for m in metrics)):
            raise ValueError(f"metrics 须为字符串列表或 None，得 {metrics!r}")
        self._metric_keys = sorted(metrics) if metrics else None
        # 幸存成员：(kind, model, weight, fit_info 记录引用)——weight 与
        # 记录同源同序（fit 期 zip strict 对账），predict/uncertainty 只读
        self._active: list[tuple[str, SurrogateModel, float,
                                 dict[str, Any]]] = []
        self.fit_info: dict[str, Any] = {}

    # ── fit：逐成员 LOOCV ρ → softmax 权重 → 全样本终拟合 ────────────────

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if len(samples) < _MIN_LOOCV_SAMPLES:
            raise ValueError(
                f"ensemble fit 至少需要 {_MIN_LOOCV_SAMPLES} 个样本"
                f"（LOOCV ρ 在更小样本上无意义），得 {len(samples)}")
        rho_metric = self._rho_metric or self._auto_rho_metric(samples)
        self._rho_metric_resolved = rho_metric

        def cost_fn(sample: dict[str, Any]) -> float:
            return float(sample["metrics"][rho_metric])

        member_records: list[dict[str, Any]] = []
        fitted_members: list[tuple[str, SurrogateModel]] = []
        rhos: list[float] = []
        for kind, mcfg in self._member_specs:
            rec: dict[str, Any] = {"kind": kind, "status": "active"}
            cfg_i = {"bounds": dict(self._bounds), **mcfg}
            if self._metric_keys is not None and "metrics" not in mcfg:
                cfg_i["metrics"] = list(self._metric_keys)

            def factory(k=kind, c=cfg_i) -> SurrogateModel:
                return surrogate_registry.create(k, config=dict(c))

            loocv: dict[str, Any] = {"ok": False, "error": "未执行"}
            try:
                loocv = loocv_rho(samples, cost_fn, factory,
                                  eval_indices=self._eval_indices)
            except Exception as exc:
                loocv = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if not loocv.get("ok"):
                rec["status"] = "dropped"
                rec["error"] = loocv.get(
                    "error", f"LOOCV 失败（{type(loocv)} 形态缺 error）")
                rec["rho"] = None
                member_records.append(rec)
                continue
            rec["rho"] = float(loocv["rho"])
            rec["loocv_n_folds"] = loocv.get("n_folds")
            rec["loocv_skipped"] = loocv.get("skipped")
            # 终拟合（LOOCV 过关后才花这份预算；失败同样按权重剔除）
            try:
                model = factory()
                model.fit(samples)
            except Exception as exc:
                rec["status"] = "dropped"
                rec["error"] = f"final fit: {type(exc).__name__}: {exc}"
                member_records.append(rec)
                continue
            if not model.fitted:  # 防御：契约违例的成员按失败处置
                rec["status"] = "dropped"
                rec["error"] = "final fit 后 fitted=False（成员契约违例）"
                member_records.append(rec)
                continue
            rhos.append(rec["rho"])
            member_records.append(rec)
            fitted_members.append((kind, model))

        if not rhos:
            raise RuntimeError(
                "ensemble fit：全部成员失败，无法构成集成——"
                f"成员记录: {member_records}")

        weights = _softmax(rhos, self._temperature)
        # 单源同序：weights[i] ↔ fitted_members[i] ↔ member_records 里
        # 第 i 个 active 记录（同一条 append 路径，zip strict 对账）
        active_records = [r for r in member_records
                          if r["status"] == "active"]
        for rec, w in zip(active_records, weights, strict=True):
            rec["weight"] = w
        self._active = [
            (kind, model, w, rec)
            for (kind, model), w, rec in zip(fitted_members, weights,
                                             active_records, strict=True)]

        info = self._mark_fitted(len(samples))
        info.update({
            "rho_metric": rho_metric,
            "weights": {kind: w for kind, _m, w, _rec in self._active},
            "members": member_records,
            "n_members_effective": len(self._active),
            "softmax_temperature": self._temperature,
            "dispersion": self._dispersion,
        })
        if len(self._active) == 1:
            info["single_member_warning"] = (
                "仅 1 席成员幸存（其余已剔除，见 members 记录）——离散度 σ "
                "恒 0，无成员间分歧信息")
        self.fit_info = info
        return info

    def _auto_rho_metric(self, samples: list[dict[str, Any]]) -> str:
        """缺省裁判指标键：样本数值指标键并集恰为 1 个时取之，否则报错。"""
        keys: set[str] = set()
        for s in samples:
            keys |= {k for k, v in (s.get("metrics") or {}).items()
                     if isinstance(v, (int, float))
                     and not isinstance(v, bool)}
        if len(keys) != 1:
            raise ValueError(
                "ensemble 需要显式 config['rho_metric']（样本数值指标键 "
                f"{sorted(keys)} 不止一个，不替用户猜 LOOCV 裁判面）")
        return next(iter(keys))

    # ── SurrogateModel 契约面 ──────────────────────────────────────────

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        """逐指标加权平均（某键缺席的成员不参与该键，权重在该键内重归一）。"""
        self._check_fitted()
        preds = [m.predict(params) for _k, m, _w, _rec in self._active]
        ws = [w for _k, _m, w, _rec in self._active]
        keys: list[str] = []
        for p in preds:
            for k in p:
                if k not in keys:
                    keys.append(k)
        out: dict[str, float] = {}
        for k in keys:
            num = 0.0
            den = 0.0
            for p, w in zip(preds, ws, strict=True):
                if k in p:
                    num += w * float(p[k])
                    den += w
            out[k] = num / den if den > 0.0 else float("nan")
        return out

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """逐指标成员间离散度（免费 epistemic σ；单成员时恒 0.0）。

        dispersion="std"：成员预测的总体标准差（ddof=0，单成员=0）；
        dispersion="range"：max−min。这是模型族间分歧的度量，不是高斯
        观测噪声 σ——语义如实标注，不与 smt_kriging 的后验方差混同。
        """
        self._check_fitted()
        preds = [m.predict(params) for _k, m, _w, _rec in self._active]
        keys: list[str] = []
        for p in preds:
            for k in p:
                if k not in keys:
                    keys.append(k)
        out: dict[str, float] = {}
        for k in keys:
            vals = [float(p[k]) for p in preds if k in p]
            if len(vals) < 2:
                out[k] = 0.0
            elif self._dispersion == "range":
                out[k] = max(vals) - min(vals)
            else:
                arr = np.asarray(vals, dtype=float)
                out[k] = float(arr.std(ddof=0))
        return out

    def _check_fitted(self) -> None:
        if not self.fitted or not self._active:
            raise RuntimeError("代理未拟合，先调用 fit()")

    # ── 内部 ───────────────────────────────────────────────────────────

    @staticmethod
    def _numeric_metrics(samples: list[dict[str, Any]]) -> set[str]:
        """样本数值指标键并集（与 conformal 同口径，诊断面用）。"""
        keys: set[str] = set()
        for s in samples:
            keys |= {k for k, v in (s.get("metrics") or {}).items()
                     if isinstance(v, (int, float))
                     and not isinstance(v, bool)}
        return keys
