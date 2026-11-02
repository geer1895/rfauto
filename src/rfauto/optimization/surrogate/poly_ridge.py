"""多项式岭回归代理（v1 默认校准代理，docs/surrogate_calibration_design.md §3）。

设计取舍：
- 小样本友好：Taguchi 9 点 + 3 维参数下，2 阶特征 10 个系数用岭回归闭式解
  稳定；λ 可配（默认 0.1，标准化特征尺度）。
- 纯 numpy 闭式解，零新增依赖（GP→sklearn、NN→torch 都是 v2 的可选项）。
- 参数按 bounds 归一化到 [0,1]（外推有界）；特征 = [1, xi, xi², xi·xj]。
- gate 验收配套 loocv_rho：留一交叉验证的预测 cost 与实际 cost 的
  Spearman ρ（P0 gate 口径）。
- 样本置信度加权通道（T-N2，aurora_n W1-B）：config["sample_weight_key"]
  给定键名时（opt-in，缺省 None=旧路径逐字节等价），逐样本读取该键作
  置信度权重进加权岭闭式解——质量守恒归一（c=|折内有效行|/Σw）：
  min Σ(c·w_i)r_i² + λ‖β‖²，置信度只重分配真实锚点/虚拟样本相对话语权，
  不改 data:penalty 平衡（uniform 置信重缩放不变量；全 1 权重 c=1.0
  精确=旧路径逐位一致）。语义与 virtual_samples.VIRTUAL_WEIGHT_KEY 对
  齐（值域 [0,1] 越大越可信）：缺键样本=1.0（真实锚点全可信——§7.2
  "合成样本不与真样本平权"的消费端落地），非有限/负权重显式 ValueError
  （#316 多报不放过），有效权重全 0 显式报错不静默退化。配套 loocv_rho
  的 eval_indices 折面（缺省 None=全样本留一旧路径；给定下标列表时只在
  其上留一——虚拟样本进训练集但不做折，裁判面只对真实锚点）。
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from typing import Any

import numpy as np

from rfauto.optimization.surrogate.base import (
    SurrogateModel,
    surrogate_registry,
)


def _features(unit: dict[str, float], names: list[str],
              order: int) -> list[float]:
    """标准化参数 → 特征向量（含偏置；order=2 加平方项与交叉项）。"""
    x = [unit[n] for n in names]
    feats = [1.0, *x]
    if order >= 2:
        feats += [xi * xi for xi in x]
        feats += [x[i] * x[j] for i, j in combinations(range(len(x)), 2)]
    return feats


# F8：与其余代理模块（deeponet/fno/nn 等）一致的装饰器注册风格
# （第三方代理按 base 模块 docstring 的方式自行注册）
def _extract_sample_weights(samples: list[dict[str, Any]],
                            key: str | None) -> np.ndarray | None:
    """按样本字典顶层键抽置信度权重（T-N2；key=None → None=旧路径）。"""
    if key is None:
        return None
    ws: list[float] = []
    for idx, s in enumerate(samples):
        if key not in s:
            ws.append(1.0)  # 真实锚点缺权重建=全可信（docstring 语义）
            continue
        try:
            v = float(s[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"样本 {idx} 的权重键 {key!r} 值 {s[key]!r} 不可转 float"
                ) from exc
        if not np.isfinite(v) or v < 0.0:
            raise ValueError(
                f"样本 {idx} 的权重键 {key!r} 值 {v!r} 非法"
                f"（须非负有限，#316 多报不放过）")
        ws.append(v)
    return np.array(ws, dtype=float)


@surrogate_registry.register("poly_ridge")
class PolyRidgeSurrogate(SurrogateModel):
    """逐指标多项式岭回归代理（params→metrics 字典契约，见 base）。

    config:
        bounds: {param: (low, high)}（必填，归一化基准）
        order: 1|2（默认 2）
        ridge_lambda: 默认 0.1
        metrics: 要建模的指标键列表（缺省 = fit 样本里全部数值键的并集）
        sample_weight_key: 样本字典顶层置信度权重键名（缺省 None=不消费
            权重，旧路径逐字节等价；给定键名时缺键样本权重=1.0，
            与 virtual_samples.VIRTUAL_WEIGHT_KEY 消费对齐，T-N2）
"""

    KIND = "poly_ridge"

    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self.config
        self.bounds: dict[str, tuple[float, float]] = {
            k: tuple(v) for k, v in cfg["bounds"].items()}
        self.names: list[str] = sorted(self.bounds)
        self.order: int = int(cfg.get("order", 2))
        lam = float(cfg.get("ridge_lambda", 0.1))
        metric_keys = cfg.get("metrics") or self._numeric_metrics(samples)
        self.metric_keys: list[str] = sorted(metric_keys)

        # 折内样本数可能少于高阶特征数（LOOCV 每折留 1）：
        # 特征数 > n_samples-1 时自动降为一阶（主效应优先，防奇异）
        n_feat_2 = 1 + 2 * len(self.names) + len(
            list(combinations(range(len(self.names)), 2)))
        order = self.order
        if order >= 2 and len(samples) < n_feat_2 + 1:
            order = 1
        self.effective_order = order

        X = np.array([
            _features(self._unit(s["params"]), self.names, order)
            for s in samples
        ])
        n_feat = X.shape[1]
        # 置信度权重通道（T-N2）：cfg["sample_weight_key"] 缺省 None=旧路径
        # 逐字节等价；给定键名时抽权重（缺键=1.0，非法值显式报错）。
        sample_w = _extract_sample_weights(samples, cfg.get("sample_weight_key"))
        if sample_w is not None and not sample_w.sum() > 0.0:
            raise ValueError(
                f"poly_ridge fit：权重键 {cfg.get('sample_weight_key')!r} 下"
                f"全部样本有效权重为 0（显式报错不静默退化——虚拟样本权重"
                f"配置有误请查生成端）")
        # 岭回归闭式解：(XᵀX + λ·diag(1))⁻¹Xᵀy（偏置不惩罚）；
        # λ=0 且仍奇异（极端共线）时退 pinv 最小范数解
        penalty = np.eye(n_feat) * lam
        penalty[0, 0] = 0.0
        self.models: dict[str, np.ndarray] = {}
        for key in self.metric_keys:
            y = np.array([float(s["metrics"].get(key, np.nan)) for s in samples])
            mask = np.isfinite(y)
            if mask.sum() < 3:
                continue  # 键在样本里不存在/全 NaN（如键名错配）——跳过不硬拟
            if sample_w is None:
                xtx = X[mask].T @ X[mask] + penalty
                xty = X[mask].T @ y[mask]
            else:
                # 加权闭式解（质量守恒归一，T-N2）：
                #   min Σ (c·w_i)·r_i² + λ‖β‖²，c = |mask|/Σw（折内质量守恒）
                # 总数据质量与平权路径一致——置信度只重分配真实锚点/虚拟
                # 样本的相对话语权，不改 data:penalty 平衡（uniform 置信
                # 重缩放不变量；全 1 权重时 c=1.0 精确，与旧路径逐位一致）。
                # 归一化因子为零时显式报错（权重全 0 不静默退化）。
                sw = sample_w[mask]
                sw_sum = float(sw.sum())
                if not sw_sum > 0.0:
                    raise ValueError(
                        f"poly_ridge fit：指标键 {key!r} 的有效行子集上权重"
                        f"全 0（显式报错不静默退化）")
                swn = sw * (mask.sum() / sw_sum)
                xw = X[mask] * swn[:, None]
                xtx = xw.T @ X[mask] + penalty
                xty = X[mask].T @ (swn * y[mask])
            try:
                self.models[key] = np.linalg.solve(xtx, xty)
            except np.linalg.LinAlgError:
                self.models[key] = np.linalg.pinv(xtx) @ xty
        return self._mark_fitted(len(samples))

    def _unit(self, params: dict[str, float]) -> dict[str, float]:
        unit = {}
        for n in self.names:
            lo, hi = self.bounds[n]
            span = max(hi - lo, 1e-12)
            unit[n] = float(np.clip((float(params.get(n, lo)) - lo) / span, 0.0, 1.0))
        return unit

    def predict(self, params: dict[str, float]) -> dict[str, float]:
        if not self.fitted:
            raise RuntimeError("代理未拟合，先调用 fit()")
        feats = np.array(
            _features(self._unit(params), self.names,
                      getattr(self, "effective_order", self.order)))
        return {key: float(feats @ coef) for key, coef in self.models.items()}

    def _numeric_metrics(self, samples: list[dict[str, Any]]) -> set[str]:
        keys: set[str] = set()
        for s in samples:
            keys |= {k for k, v in s.get("metrics", {}).items()
                     if isinstance(v, (int, float))}
        return keys


def loocv_rho(
    samples: list[dict[str, Any]],
    cost_fn: Callable[[dict[str, Any]], float],
    surrogate_factory: Callable[[], SurrogateModel],
    *,
    eval_indices: list[int] | None = None,
) -> dict[str, Any]:
    """留一交叉验证：每折留出 1 个样本做预测，其余拟合。

    返回预测 cost 与实际 cost 的 Spearman ρ（P0 gate 口径 ≥0.8）。
    样本数 <4 时结果不稳定，直接返回 ok=False。

    eval_indices（T-N2，opt-in；缺省 None=全样本留一旧路径逐字节等价）：
    只在其下标上留一做折（折内模型仍用除该折外的全部样本训练）——
    虚拟样本进训练集但不进裁判折面（裁判只对真实锚点，合成点留一会
    把插值偏差算进 ρ）。须为有效下标且 ≥4 个。
    """
    if eval_indices is None:
        folds = range(len(samples))
        n_folds_total = len(samples)
        fold_label = f"样本数 {len(samples)}"
    else:
        folds = [int(i) for i in eval_indices]
        bad = [i for i in folds if not 0 <= i < len(samples)]
        if bad:
            raise ValueError(
                f"loocv_rho：eval_indices 越界 {bad}"
                f"（样本数 {len(samples)}）")
        n_folds_total = len(folds)
        fold_label = f"折数 {len(folds)}"
    if n_folds_total < 4:
        return {"ok": False,
                "error": f"{fold_label} < 4，LOOCV 无意义"}
    predicted: list[float] = []
    actual: list[float] = []
    skipped = 0
    for i in folds:
        hold = samples[i]
        rest = [s for j, s in enumerate(samples) if j != i]
        model = surrogate_factory()
        model.fit(rest)
        try:
            pred = model.predict(hold["params"])
        except Exception:
            skipped += 1
            continue
        # 预测 cost：用折内模型预测的指标交给 cost_fn（同 objectives 口径）
        try:
            predicted.append(float(cost_fn({"metrics": pred})))
            actual.append(float(cost_fn(hold)))
        except Exception:
            skipped += 1
    if len(predicted) < 3:
        return {"ok": False, "error": f"有效折数 {len(predicted)} < 3",
                "skipped": skipped}
    rho = _spearman(predicted, actual)
    return {"ok": True, "rho": rho, "n_folds": len(predicted),
            "skipped": skipped}


def _spearman(a: list[float], b: list[float]) -> float:
    """Spearman ρ（秩相关；并列秩取平均）。"""
    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math_sqrt(sum((ra[i] - ma) ** 2 for i in range(n)))
    db = math_sqrt(sum((rb[i] - mb) ** 2 for i in range(n)))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def math_sqrt(x: float) -> float:
    return x ** 0.5
