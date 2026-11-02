"""深度集成 σ 曲线代理（注册键 "deep_ensemble"，aurora_n W3 T-N18）。

M 个**同构** torch 成员（同一 base_kind，缺省 "fno"）——成员 i 用独立种子
初始化（seed_i = seed + i）+ bootstrap 有放回重采样训练集（bagging，
Lakshminanathan et al. 2017 "Simple and Scalable Predictive Uncertainty
Estimation using Deep Ensembles", arXiv:1612.01474 的同构成员+随机初始化
口径；NeurIPS 版 NeurIPS.ps/2017）——预测取成员**等权均值**，成员间预测
离散度（总体 std 或 max−min）作 epistemic σ 经 ``uncertainty()`` 透出
（base.py 契约：T-N6 numpy 面 ensemble 的 torch 深度集成对应物；σ 语义=
成员间分歧，非高斯观测噪声，不与 smt_kriging 后验方差混同）。

与 ensemble.py（LOOCV ρ softmax 加权、模型族间异构集成）的分工：本件是
同构深度集成的 torch 形态——成员便宜可复制、bootstrap+异 seed 提供多样性、
等权平均是深度集成标准口径（不做 LOOCV 加权：M 次 LOOCV 会把 torch 成员
训练预算放大 O(n) 倍）。曲线级 σ 走 ``predict_curve_with_std``（逐频点
std），带内标量 σ 走 ``uncertainty()``（对齐 predict 键）。

诚实契约（对齐 ensemble.py 先例）：
- 成员 fit 失败 → 按成员剔除并在 fit_info["members"] 记录 error 原文，
  不静默塌缩；全部成员失败 → 显式 RuntimeError；
- 成员训练发散（loss NaN/Inf，fno 内建检测停）同样按失败成员剔除——
  剔除后幸存成员数如实记 ``n_members_effective``；
- n_members < 2 → 构造期 ValueError（单成员无离散度信息，不静默放行）。

确定性（红线）：成员种子与 bootstrap 重采样全部由 master seed 确定性派生
（成员 torch seed=seed+i；bootstrap rng=np.random.default_rng([seed, i])，
PCG64 序列种子跨平台确定）→ 同配置同样本两次 fit，predict/uncertainty/
predict_curve_with_std 逐位相等（CPU 同平台；跨平台 BLAS 轨迹漂移如实
声明，#247 家法——只互比不钉绝对值）。

用法::

    model = surrogate_registry.create("deep_ensemble", config={
        "bounds": {"x": (0.0, 1.0)},
        "freq_grid": [1.5, 3.5],          # 透传成员（fno）的必填 config
        "base_kind": "fno",               # 缺省 fno
        "n_members": 5,                   # 缺省 5，须 ≥2
        "seed": 42,                       # 缺省 42；成员 seed=42+i
        "bootstrap": True,                # 缺省 True；False=仅异 seed 多样性
        "dispersion": "std",              # 缺省 "std"；"range"=max−min
        # base_config: 成员私有 config（与 bounds 合并，成员显式键优先）
    })
    info = model.fit(samples)   # 成员记录在 info["members"]
    y = model.predict(params)   # 带内标量均值
    sigma = model.uncertainty(params)          # 带内标量成员间 σ
    curve = model.predict_curve_with_std(params)  # 曲线级均值+逐点 σ

规模边界（训练时长纪律，T-N18）：单次 fit = M 次成员全批训练——单测档
（T=32/width12/epochs200/M=3）实测 ~2s；真实档（T=48/width16/epochs400/
M=5）实测 ~5s（runs/aurora_n/w3_tn18/probe_output_r1.txt）；GPU 升级位同
fno（成员 net/数据 .to(device)）。成员须为曲线代理（支持
predict_curve(params, n_points)，curve_key 语义同 fno）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)

__all__ = ["DeepEnsembleSurrogate"]

#: 离散度档位（config["dispersion"]；std=成员间总体标准差，range=max−min）
_DISPERSION_KINDS = ("std", "range")

#: deep_ensemble 自身保留键（其余顶层键一律透传成员——freq_grid/width/
#: epochs 等成员 config 平铺写法；base_config 可再覆盖，成员显式键优先）
_RESERVED_KEYS = frozenset({
    "bounds", "base_kind", "n_members", "seed", "bootstrap",
    "dispersion", "base_config",
})


@surrogate_registry.register("deep_ensemble")
class DeepEnsembleSurrogate(SurrogateModel):
    """同构 torch 深度集成（bootstrap+异 seed）曲线代理，成员离散度=σ。

    config:
        bounds: {param: (low, high)}（必填；注入每个成员的 config）
        base_kind: 成员注册键（缺省 "fno"；"deep_ensemble" 自嵌套拒绝；
            成员须支持 predict_curve）
        n_members: 成员数（缺省 5，须 ≥2 整数）
        seed: master 种子（缺省 42；成员 i torch seed=seed+i，
            bootstrap rng=default_rng([seed, i])）
        bootstrap: 是否有放回重采样训练集（缺省 True；False=仅异 seed）
        dispersion: 离散度档位（缺省 "std"；"range"=max−min）
        base_config: 成员私有 config dict（优先级最高，覆盖顶层透传键）
        其余顶层键（freq_grid/curve_samples/width/epochs/curve_key/...）
            一律透传每个成员——成员 config 平铺写法
        curve_key: bootstrap 池过滤键（缺省 "s11_curve_db"，与 fno 缺省
            同源；缺该键的样本不进任何成员的训练池）

    fit_info: kind/n_samples/n_pool/n_members/n_members_effective/
        base_kind/bootstrap/dispersion/seed/members（逐成员 status/seed/
        n_train/error 原文）。
    """

    KIND = "deep_ensemble"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        cfg = self.config
        bounds = cfg.get("bounds")
        if not isinstance(bounds, dict) or not bounds:
            raise ValueError(
                "deep_ensemble 需要 config['bounds']（非空 "
                "{param: (low, high)}，注入各成员工厂）")
        self._bounds: dict[str, tuple[float, float]] = {
            k: tuple(v) for k, v in bounds.items()}
        base_kind = cfg.get("base_kind", "fno")
        if not isinstance(base_kind, str) or not base_kind:
            raise ValueError(f"base_kind 须为非空 str，得 {base_kind!r}")
        if base_kind == self.KIND:
            raise ValueError("deep_ensemble 不可嵌套自身（base_kind='deep_ensemble'）")
        self._base_kind = base_kind
        n_members = cfg.get("n_members", 5)
        if isinstance(n_members, bool) or not isinstance(n_members, int) \
                or n_members < 2:
            raise ValueError(
                f"n_members 须为 ≥2 的整数（单成员无离散度信息），得 "
                f"{n_members!r}")
        self._n_members = int(n_members)
        seed = cfg.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"seed 须为 int，得 {seed!r}")
        self._seed = int(seed)
        bootstrap = cfg.get("bootstrap", True)
        if not isinstance(bootstrap, bool):
            raise ValueError(f"bootstrap 须为 bool，得 {bootstrap!r}")
        self._bootstrap = bootstrap
        dispersion = cfg.get("dispersion", "std")
        if dispersion not in _DISPERSION_KINDS:
            raise ValueError(
                f"dispersion 须为 {_DISPERSION_KINDS} 之一，得 {dispersion!r}")
        self._dispersion = dispersion
        base_config = cfg.get("base_config")
        if base_config is not None and not isinstance(base_config, dict):
            raise ValueError(f"base_config 须为 dict 或 None，得 {base_config!r}")
        self._base_config: dict[str, Any] = dict(base_config or {})
        # 顶层透传键（freq_grid/width/epochs/curve_key 等）→ 每个成员
        self._member_extras: dict[str, Any] = {
            k: v for k, v in cfg.items() if k not in _RESERVED_KEYS}
        curve_key = cfg.get("curve_key", "s11_curve_db")
        if not isinstance(curve_key, str) or not curve_key:
            raise ValueError(f"curve_key 须为非空 str，得 {curve_key!r}")
        self._curve_key = curve_key
        # 幸存成员（model, record 同序）——predict/uncertainty 只读
        self._members: list[tuple[SurrogateModel, dict[str, Any]]] = []
        self.fit_info: dict[str, Any] = {}

    # ── fit：M×（bootstrap 重采样 + 成员全批训练），失败成员剔除如实记 ──

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        pool = [s for s in samples
                if self._curve_key in (s.get("metrics") or {})]
        member_records: list[dict[str, Any]] = []
        members: list[SurrogateModel] = []
        active_records: list[dict[str, Any]] = []
        for i in range(self._n_members):
            rec: dict[str, Any] = {"index": i, "seed": self._seed + i,
                                   "status": "active"}
            if self._bootstrap:
                idx = np.random.default_rng([self._seed, i]).integers(
                    0, len(pool), len(pool))
                subset = [pool[int(j)] for j in idx]
            else:
                subset = list(pool)
            rec["n_train"] = len(subset)
            try:
                model = surrogate_registry.create(
                    self._base_kind,
                    config={"bounds": dict(self._bounds),
                            **self._member_extras,
                            **self._base_config,
                            "seed": rec["seed"]})
                model.fit(subset)
            except Exception as exc:  # 成员失败剔除（诚实记录原文）
                rec["status"] = "dropped"
                rec["error"] = f"{type(exc).__name__}: {exc}"
                member_records.append(rec)
                continue
            if not model.fitted:  # 防御：契约违例成员按失败处置
                rec["status"] = "dropped"
                rec["error"] = "final fit 后 fitted=False（成员契约违例）"
                member_records.append(rec)
                continue
            members.append(model)
            member_records.append(rec)
            active_records.append(rec)

        if not members:
            raise RuntimeError(
                "deep_ensemble fit：全部成员失败，无法构成集成——"
                f"成员记录: {member_records}")

        # 单源同序：members[i] ↔ active_records[i]（同一条 append 路径，
        # zip strict 对账；dropped 记录只进 member_records 供 fit_info）
        self._members = list(zip(members, active_records, strict=True))
        info = self._mark_fitted(len(samples))
        info.update({
            "n_pool": len(pool),
            "n_members": self._n_members,
            "n_members_effective": len(self._members),
            "base_kind": self._base_kind,
            "bootstrap": self._bootstrap,
            "dispersion": self._dispersion,
            "seed": self._seed,
            "curve_key": self._curve_key,
            "members": member_records,
        })
        if len(pool) < len(samples):
            info["pool_filtered"] = (
                f"{len(samples) - len(pool)} 个样本缺 "
                f"metrics['{self._curve_key}']，未进成员训练池")
        self.fit_info = info
        return info

    # ── SurrogateModel 契约面（等权均值 + 成员间离散度） ─────────────────

    def _check_fitted(self) -> None:
        if not self.fitted or not self._members:
            raise RuntimeError("代理未拟合，先调用 fit()")

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        """带内标量：成员等权均值（某键缺席的成员不参与该键）。"""
        self._check_fitted()
        preds = [m.predict(params) for m, _rec in self._members]
        keys: list[str] = []
        for p in preds:
            for k in p:
                if k not in keys:
                    keys.append(k)
        return {k: float(np.mean([float(p[k]) for p in preds if k in p]))
                for k in keys}

    def uncertainty(self, params: dict[str, float]) -> dict[str, float]:
        """带内标量成员间离散度（epistemic σ；语义=成员分歧非观测噪声）。

        dispersion="std"：成员预测总体标准差（ddof=0）；
        dispersion="range"：max−min。幸存成员仅 1 席时恒 0.0（fit_info
        n_members_effective=1 如实在案）。
        """
        self._check_fitted()
        preds = [m.predict(params) for m, _rec in self._members]
        keys: list[str] = []
        for p in preds:
            for k in p:
                if k not in keys:
                    keys.append(k)
        out: dict[str, float] = {}
        for k in keys:
            vals = np.asarray([float(p[k]) for p in preds if k in p],
                              dtype=float)
            if len(vals) < 2:
                out[k] = 0.0
            elif self._dispersion == "range":
                out[k] = float(vals.max() - vals.min())
            else:
                out[k] = float(vals.std(ddof=0))
        return out

    def predict_curve_with_std(
        self, params: dict[str, float],
        n_points: int | None = None,
    ) -> dict[str, Any]:
        """曲线级均值±逐点 σ：{freq_ghz, s11_db(均值), s11_db_std}。"""
        self._check_fitted()
        curves: list[np.ndarray] = []
        grid: list[float] | None = None
        for m, rec in self._members:
            if not hasattr(m, "predict_curve"):
                raise RuntimeError(
                    f"predict_curve_with_std 需要成员支持 predict_curve"
                    f"（base_kind={self._base_kind!r} 不支持，成员 "
                    f"index={rec['index']}）")
            out = m.predict_curve(params, n_points=n_points)
            if grid is None:
                grid = out["freq_ghz"]
            curves.append(np.asarray(out["s11_db"], dtype=float))
        if len({c.shape for c in curves}) != 1:
            raise RuntimeError(
                "deep_ensemble 成员曲线长度不一致（预测网格漂移）——"
                f"shapes={[c.shape for c in curves]}")
        arr = np.stack(curves)  # (M, T)
        return {"freq_ghz": list(grid),
                "s11_db": arr.mean(axis=0).tolist(),
                "s11_db_std": arr.std(axis=0, ddof=0).tolist()}
