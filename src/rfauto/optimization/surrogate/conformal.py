"""T-N1 split-conformal UQ 包装器（注册键 "conformal"，aurora_n W1-A）。

一句话：给任意已注册代理（config 内嵌 ``base_kind``）的 ``predict`` 输出
加"边际覆盖率有保证"的对称区间——补救 poly_ridge/gbdt 等 std=None 档
（base.py ``predict_with_std`` "不得伪造 0" 的正面出路：区间半宽来自
**校准残差分位数**，不伪造 σ）。

数值内核单源（AGENTS 7）：分位数数学全部复用 core/conformal 的
``calibrate``（有限样本高阶分位数 k=ceil((n+1)(1−α))，α 非法/残差非
有限显式报错，k>n 如实上溢 +inf）与 ``predict_interval``（区间组装），
本模块零新数值代码路径，只做 SurrogateModel 契约适配（samples/params
字典面、确定性 train/cal 划分、多指标、fit_info 报警）。

覆盖语义（如实标注）：split conformal 提供的是**边际覆盖**（marginal
coverage）——交换性成立时 P(Y∈C(X)) ≥ 1−α 对随机抽到的样本成立，
**不是逐点条件覆盖**；校准集与预测点分布漂移（协变量漂移/时序趋势/
分布外点混入）会破坏保证。fit 期对校准残差做重尾诊断（max/median
比值启发式），疑似分布外污染时在 ``fit_info["coverage_warning"]``
显式报警（#122 不静默）——报警是启发式提示，不是覆盖证明。

确定性（红线 2）：随机划分由 ``config["seed"]``（缺省 0）经
``numpy.default_rng`` 确定性置换产生（显式 ``cal_indices`` 时划分即
确定性，不消费 seed）——同 seed 同样本两次 fit 的分位数逐位相等
（tests/unit/test_conformal_surrogate.py 钉死）。

用法（注册面与手写面同构）::

    model = surrogate_registry.create("conformal", config={
        "base_kind": "poly_ridge",
        "base_config": {"bounds": {"x": [0.0, 1.0]}, "order": 2},
        "alpha": 0.1,       # 名义 90% 区间
        "cal_ratio": 0.5,   # 校准占比
        "seed": 7,
    })
    info = model.fit(samples)          # samples 同 SurrogateModel 契约
    yhat = model.predict(params)       # 透传 base
    halfw = model.uncertainty(params)  # {metric: q}——保形半宽（非 σ）
    iv = model.predict_interval(params)  # {metric: (lo, hi)}
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.conformal import calibrate as _calibrate_kernel
from rfauto.core.conformal import predict_interval as _predict_interval_kernel
from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)

__all__ = ["ConformalSurrogate"]


@surrogate_registry.register("conformal")
class ConformalSurrogate(SurrogateModel):
    """任意已注册代理的 split-conformal 区间包装（SurrogateModel 契约）。

    config:
        base_kind: 被包装代理的注册键（必填；"conformal" 自嵌套显式拒绝）
        base_config: 透传被包装代理工厂的 config dict（缺省 {}）
        alpha: 违覆盖率（缺省 0.1 → 名义 90% 区间；校验单源在内核 calibrate）
        cal_ratio: 校准集占比（缺省 0.5；随机划分保证 train/cal 各 ≥2）
        cal_indices: 显式校准集下标（可选；经典 split-conformal 的"用户自带
            校准集"形态——给定后 train=其余下标，seed 不参与划分；须唯一、
            2 ≤ len ≤ n−2，越界/重复 fit 期显式报错）
        seed: 随机划分种子（缺省 0；同 seed 确定性可复现，显式 cal_indices
            时不消费）
        metrics: 要建模校准的指标键列表（缺省 = fit 样本全部数值键并集）

    uncertainty 返回 {metric: q}——q 是保形区间**半宽**（残差分位数），
    不是高斯 σ；区间 = predict ± q。q=+inf（校准集撑不起 α，内核如实
    上溢）时区间无界，语义见 core/conformal。
    """

    KIND = "conformal"

    #: fit 样本下限（train/cal 各 ≥2 才有可校准的 split）
    _MIN_SAMPLES = 4
    #: 重尾诊断阈值：q90(|res|)/q25(|res|) > 12 视为疑似分布外污染。
    #: 统计取分位数比而非 max/median——污染占比高时 median 本身被抬走
    #: （50% 污染即失真），q25 仍锚在干净主体；实测分离度（本席探针，
    #: poly_ridge/1D 噪声面）：干净多 seed 3.8–6.1，50% OOD 校准 24.1，
    #: 12 取两向 ≥2× 余量。报警是启发式提示，不是覆盖证明。
    _OOD_RATIO = 12.0

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        cfg = self.config
        base_kind = cfg.get("base_kind")
        if not base_kind or not isinstance(base_kind, str):
            raise ValueError(
                "conformal 包装器需要 config['base_kind']"
                "（被包装代理的注册键，如 'poly_ridge'）")
        if base_kind == self.KIND:
            raise ValueError("conformal 不可嵌套自身（base_kind='conformal'）")
        self._base_kind: str = base_kind
        self._base_config: dict[str, Any] = dict(cfg.get("base_config") or {})
        self._alpha: Any = cfg.get("alpha", 0.1)  # 校验单源在内核 calibrate
        cal_ratio = cfg.get("cal_ratio", 0.5)
        if isinstance(cal_ratio, bool) or not isinstance(cal_ratio,
                                                         (int, float)) \
                or not (0.0 < float(cal_ratio) < 1.0):
            raise ValueError(f"cal_ratio 必须在 (0,1) 开区间，得 {cal_ratio!r}")
        self._cal_ratio = float(cal_ratio)
        self._seed = int(cfg.get("seed", 0))
        cal_idx = cfg.get("cal_indices")
        if cal_idx is not None:
            if not isinstance(cal_idx, (list, tuple)) or not all(
                    isinstance(i, int) and not isinstance(i, bool)
                    for i in cal_idx):
                raise ValueError(
                    f"cal_indices 必须为整数列表（样本下标），得 {cal_idx!r}")
            if len(set(cal_idx)) != len(cal_idx):
                raise ValueError("cal_indices 含重复下标（校准集须无重复）")
            if not (len(cal_idx) >= 2):
                raise ValueError(
                    f"cal_indices 至少 2 个（校准集下限），得 {len(cal_idx)}")
        self._cal_indices: list[int] | None = (
            sorted(int(i) for i in cal_idx) if cal_idx is not None else None)
        metrics = cfg.get("metrics")
        if metrics is not None and (not isinstance(metrics, (list, tuple))
                                    or not all(isinstance(m, str) for m in metrics)):
            raise ValueError(f"metrics 必须为字符串列表，得 {metrics!r}")
        self._metric_keys = sorted(metrics) if metrics else None
        self._base: SurrogateModel | None = None
        self._q: dict[str, float] = {}
        self.fit_info: dict[str, Any] = {}

    # ── fit：确定性划分 → base 拟合 → 校准残差分位数 ────────────────────

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(samples)
        if n < self._MIN_SAMPLES:
            raise ValueError(
                f"conformal 包装器至少需要 {self._MIN_SAMPLES} 个样本"
                f"（train/cal 各 ≥2），得 {n}")
        if self._cal_indices is not None:
            if len(self._cal_indices) > n - 2 or self._cal_indices[-1] >= n:
                raise ValueError(
                    f"cal_indices 越界/过长：样本数 n={n}，"
                    f"须 2 ≤ len ≤ n−2 且下标 ∈ [0, n)")
            cal_pos = list(self._cal_indices)
            cal_set = set(cal_pos)
            train_pos = [i for i in range(n) if i not in cal_set]
            split_desc = f"explicit_cal_indices(n_cal={len(cal_pos)})"
        else:
            perm = np.random.default_rng(self._seed).permutation(n)
            n_cal = min(max(round(self._cal_ratio * n), 2), n - 2)
            cal_pos = sorted(perm[:n_cal].tolist())
            train_pos = sorted(perm[n_cal:].tolist())
            split_desc = f"random(seed={self._seed}, cal_ratio={self._cal_ratio})"
        cal_samples = [samples[i] for i in cal_pos]
        train_samples = [samples[i] for i in train_pos]

        self._base = surrogate_registry.create(
            self._base_kind, config=dict(self._base_config))
        base_info = self._base.fit(train_samples)

        metric_keys = self._metric_keys or sorted(self._numeric_metrics(samples))
        residuals: dict[str, list[float]] = {k: [] for k in metric_keys}
        for s in cal_samples:
            pred = self._base.predict(s["params"])
            for k in metric_keys:
                y = s.get("metrics", {}).get(k)
                yh = pred.get(k) if isinstance(pred, dict) else None
                if (isinstance(y, (int, float)) and not isinstance(y, bool)
                        and isinstance(yh, (int, float))
                        and not isinstance(yh, bool)
                        and math.isfinite(float(y))
                        and math.isfinite(float(yh))):
                    residuals[k].append(float(yh) - float(y))

        q_map: dict[str, float] = {}
        dropped: list[str] = []
        for k in metric_keys:
            if not residuals[k]:
                dropped.append(k)  # 校准折内该键无有效数值（键名错配等）
                continue
            # 内核单源：α 校验/有限样本高阶分位数/+inf 上溢全在 calibrate
            q_map[k] = _calibrate_kernel(residuals[k], self._alpha)
        if not q_map:
            raise ValueError(
                f"无有效指标可校准（cal n={len(cal_samples)}，"
                f"metric_keys={metric_keys}）——检查样本 metrics 键名")

        warnings = self._ood_warnings(residuals, q_map)

        info = self._mark_fitted(n)
        info.update({
            "base_kind": self._base_kind,
            "base_fit": base_info,
            "split": split_desc,
            "n_train": len(train_samples),
            "n_cal": len(cal_samples),
            "alpha": float(self._alpha),
            "target_coverage": 1.0 - float(self._alpha),
            "quantiles": dict(q_map),
            "metric_keys_dropped": dropped,
            # 覆盖语义如实标注（任务书红线：docstring/fit_info 双面）
            "coverage": "marginal（边际覆盖，非逐点；交换性前提见模块 docstring）",
        })
        if warnings:
            info["coverage_warning"] = warnings
        self._q = q_map
        self.fit_info = info
        return info

    def _ood_warnings(self, residuals: dict[str, list[float]],
                      q_map: dict[str, float]) -> list[str]:
        """校准残差重尾诊断（启发式；疑似分布外污染时显式报警不静默）。"""
        warns: list[str] = []
        for k in sorted(q_map):
            q = q_map[k]
            if not math.isfinite(q):
                warns.append(
                    f"指标 {k}: 校准集太小撑不起 alpha={self._alpha}"
                    "（q=+inf，内核如实上溢）——区间无界，名义覆盖退化为恒真")
                continue
            arr = np.abs(np.asarray(residuals[k], dtype=float))
            q25 = float(np.quantile(arr, 0.25))
            if q25 <= 0.0:
                continue  # 低分位为 0（近插值/常数指标）：分位比无意义
            ratio = float(np.quantile(arr, 0.90)) / q25
            if ratio > self._OOD_RATIO:
                warns.append(
                    f"指标 {k}: 校准残差重尾（q90/q25={ratio:.1f}x > "
                    f"{self._OOD_RATIO}x）——疑似混入分布外点，边际覆盖可能"
                    "破位；建议清洗校准集或更换划分（seed/cal_indices）")
        return warns

    # ── SurrogateModel 契约面 ──────────────────────────────────────────

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        """透传被包装代理的点预测（区间不改均值面）。"""
        if not self.fitted or self._base is None:
            raise RuntimeError("代理未拟合，先调用 fit()")
        return self._base.predict(params)

    def uncertainty(self, params: dict[str, float]) -> dict[str, float] | None:
        """逐指标保形区间半宽 {metric: q}（残差分位数，非 σ——见类 docstring）。"""
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")
        return dict(self._q)

    def predict_interval(
            self, params: dict[str, float]) -> dict[str, tuple[float, float]]:
        """逐指标保形预测区间 {metric: (lo, hi)}（组装单源 core.predict_interval）。"""
        if not self.fitted or self._base is None:
            raise RuntimeError("代理未拟合，先调用 fit()")
        mean = self._base.predict(params)
        out: dict[str, tuple[float, float]] = {}
        for k, q in self._q.items():
            if k in mean:
                out[k] = _predict_interval_kernel(float(mean[k]), q)
        return out

    # ── 内部 ───────────────────────────────────────────────────────────

    @staticmethod
    def _numeric_metrics(samples: list[dict[str, Any]]) -> set[str]:
        """样本数值指标键并集（与 poly_ridge._numeric_metrics 同口径）。"""
        keys: set[str] = set()
        for s in samples:
            keys |= {k for k, v in s.get("metrics", {}).items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool)}
        return keys
