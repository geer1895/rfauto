"""inverse_prefilter：生成式逆设计前滤波（阶段 7.2 保守版【近】首片）。

光子学逆设计的保守翻译：在参数化模板家族内造"(参数, 指标) 语料"，
把"目标指标 → 候选参数分布"做成可复现的确定性反演——生成 k 个高分
起点交给确定性优化器收尾（定位是优化器的**前滤波器**，不是替代；
可信度归仿真管）。

首片语料引擎 = fake 通道批量合成（零 license、全内存零落盘——
v1 定案后 fake 的正确定位：数据引擎/冒烟/CI）。100k 级条件扩散
升级（CVAE/diffusion）留待 GPU 档；本片的反演核 = 指标空间加权
距离的近邻反演 + 有界抖动多样性，种子确定可复现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _fake_metrics(recipe: dict[str, Any], params: dict[str, float]) -> dict[str, float]:
    """用 fake 解析通道在内存内评估单点指标（零落盘、零 license）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.models.registry import get as get_plugin_cls

    model_name = recipe.get("model", "")
    plugin_cls = get_plugin_cls(model_name)
    plugin = plugin_cls()
    adapter = FakeAdapter(n_ports=plugin_cls.n_ports,
                          model_type=plugin_cls.fake_model_type)
    try:
        adapter.connect({})
        plugin.build(adapter, plugin.params_model(**params))
        report = adapter.solve("main_setup")
        if not report.success:
            raise RuntimeError(report.message)
        network = adapter.get_sparams()
        objectives = [Objective(**o) for o in recipe.get("objectives") or []]
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        metrics["cost"] = float(
            SpecEvaluator.evaluate_objectives(metrics, objectives))
        return metrics
    finally:
        adapter.close()


def prefilter_candidates(
    recipe_path: str,
    target_metrics: dict[str, float],
    *,
    n_corpus: int = 400,
    k: int = 20,
    jitter: float = 0.03,
    seed: int = 42,
) -> dict[str, Any]:
    """目标指标 → k 个候选参数起点（fake 语料 + 加权近邻反演）。

    1. 读配方 optimization.params 搜索空间，LHS 撒 n_corpus 语料点；
    2. fake 通道全内存批量评估语料指标（数据引擎定位）；
    3. 指标空间加权距离反演（目标里未指定的指标不计距离）；
    4. 前 k 名各做有界抖动扰动（多样性起点，不越界）。
    确定性：同 seed 同语料同结果；候选需中/高保真复核（可信度归仿真）。
    """
    import yaml

    from rfauto.optimization.sample_design import lhs_points

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    space = (recipe.get("optimization") or {}).get("params") or {}
    bounds = {n: (float(v["low"]), float(v["high"]))
              for n, v in space.items() if "low" in v and "high" in v}
    if not bounds:
        return {"ok": False, "errors": ["配方 optimization.params 无 low/high 搜索空间"]}
    if not target_metrics:
        return {"ok": False, "errors": ["target_metrics 为空"]}

    corpus = lhs_points(bounds, n_corpus, seed=seed)["points"]
    names = sorted(target_metrics)
    scored: list[tuple[float, dict[str, float], dict[str, float]]] = []
    errors: list[str] = []
    for pt in corpus:
        try:
            metrics = _fake_metrics(recipe, pt)
        except Exception as exc:  # 单点失败不阻塞语料（解析模型边界）
            errors.append(str(exc))
            continue
        dist = 0.0
        for n in names:
            t, got = float(target_metrics[n]), metrics.get(n)
            if got is None:
                dist += abs(t)  # 缺指标当最大失配惩罚
                continue
            dist += abs(float(got) - t)
        scored.append((dist, pt, metrics))
    if not scored:
        return {"ok": False,
                "errors": ["语料评估全部失败", *errors[:3]]}
    scored.sort(key=lambda t: t[0])

    import numpy as np

    rng = np.random.default_rng(seed)
    candidates = []
    for dist, pt, metrics in scored[:k]:
        cand = dict(pt)
        for n, (lo, hi) in bounds.items():
            span = hi - lo
            val = float(np.clip(pt[n] + rng.uniform(-jitter, jitter) * span,
                                lo, hi))
            cand[n] = round(val, 6)
        candidates.append({
            "params": cand,
            "seed_params": {n: round(pt[n], 6) for n in pt},
            "corpus_distance": round(dist, 6),
            "corpus_metrics": {n: round(float(metrics[n]), 4)
                               for n in metrics
                               if isinstance(metrics.get(n), (int, float))},
        })
    return {
        "ok": True,
        "recipe": str(path).replace("\\", "/"),
        "target_metrics": target_metrics,
        "n_corpus": n_corpus,
        "n_corpus_failed": len(errors),
        "candidates": candidates,
        "generator": "fake_corpus_nn_invert_v1",
        "note": "生成式候选=优化器前滤波器；可信度归中/高保真仿真复核",
    }
