"""hierarchical_scheduler：拓扑/参数分层调度器（AD-9，round15 §五）。

规格：「拓扑/参数分层调度器：inverse_prefilter/MCTS×inverse_design/
diffusion 统一调度」（P3/L）。现状（调研 §五）：逆设计四件互不衔接、
无分层调度器——本模块立**战役级编排面**：

- L1 拓扑层：候选（配方路径）逐个走 inverse_prefilter 伪语料前滤波
  （fake 闭式语料 + 加权近邻反演，零 license），拓扑得分 = −最优语料
  距离（越小越好取负成"越大越好"口径）；按分排序，预算份额按
  TOP_WEIGHTS 名额权重确定性分配（无墙钟进决策，replan 同口径）。
- L2 参数层：参数搜索引擎注册表（基类+注册表，铁律 3）：
  ``surrogate`` → optimization.surrogate_loop（连续域，GP 代理）；
  ``mcts`` → service.mcts_search.mcts_plan（离散网格域，UCB1）。
  预算份额=评估次数（n_evaluations 语义），不是秒数。

铁律落地：
- 铁律 7：全部数字出自确定性内核（伪语料距离/代理环/MCTS 奖励），
  编排层只做分派与份额分配，零数值产出；生成式候选（扩散等）未来以
  新 engine 注册接入，可信度仍归仿真复核；
- JSON 进出：plan 输入/输出均为可 JSON 化结构（evaluate_fn 由本模块
  从配方确定性构造，不经调用方传入可执行体）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from rfauto.service.envelope import ok_envelope

SCHEDULE_SCHEMA = "rfauto-hierarchical-schedule-v1"

#: L1 名额权重（rank1..3；promote_top 截断后归一分配，确定性）。
TOP_WEIGHTS: tuple[float, ...] = (0.6, 0.3, 0.1)

#: L1 伪语料规模（前滤波评分用；独立于 L2 预算）。
PREFILTER_N_CORPUS_DEFAULT = 48

#: MCTS 每轴网格水平数（离散域 granularity）。
MCTS_LEVELS_DEFAULT = 5


def _recipe_view(recipe_path: str | Any) -> dict[str, Any]:
    """读配方 → {bounds, objectives, raw}（与 inverse_prefilter 同解析口径）。"""
    import yaml

    path = recipe_path if isinstance(recipe_path, str) else str(recipe_path)
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    space = (recipe.get("optimization") or {}).get("params") or {}
    bounds = {n: (float(v["low"]), float(v["high"]))
              for n, v in space.items() if "low" in v and "high" in v}
    return {"path": path, "bounds": bounds,
            "objectives": list(recipe.get("objectives") or []),
            "raw": recipe}


def _recipe_evaluator(recipe: Mapping[str, Any]):
    """配方 → 确定性评估器（fake 闭式语料同源；单源复用 inverse_prefilter）。"""
    from rfauto.service.inverse_prefilter import _fake_metrics

    raw = dict(recipe["raw"])

    def evaluate(params: dict[str, float]) -> dict[str, float]:
        return _fake_metrics(raw, params)

    return evaluate


class ParamSearchEngine(ABC):
    """L2 参数搜索引擎接口（基类+注册表模式，铁律 3）。"""

    name: str = "base"

    @abstractmethod
    def search(self, *, bounds: dict[str, tuple[float, float]],
               objectives: list[Any],
               evaluate_fn: Any,
               budget: int, seed: int) -> dict[str, Any]:
        """在 bounds 内以 ≤budget 次评估搜索 objectives 最优（确定性）。"""


class SurrogateSearchEngine(ParamSearchEngine):
    """连续域代理环引擎（wraps optimization.surrogate_loop）。"""

    name = "surrogate"

    def search(self, *, bounds, objectives, evaluate_fn,
               budget: int, seed: int) -> dict[str, Any]:
        import warnings

        from rfauto.optimization.surrogate_loop import run_surrogate_loop

        budget = max(int(budget), 1)
        # 小预算下 GP 核超参贴边界触 sklearn ConvergenceWarning——与搜索
        # 语义无关且污染调用方 stderr；仅本调用块内压制（run_optimize_kickoff
        # 同款先例，不改 optimization 层、不吞异常）。
        try:
            from sklearn.exceptions import ConvergenceWarning as _ConvWarn
        except Exception:  # pragma: no cover - sklearn 是环的既有依赖
            _ConvWarn = UserWarning  # type: ignore[assignment,misc]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", _ConvWarn)
            result = run_surrogate_loop(
                bounds, objectives, evaluate_fn,
                n_init=max(2, min(3, budget - 1)),
                top_k=1, max_real=budget, seed=int(seed))
        best = result.get("best") or None
        return {"ok": bool(result.get("ok", True)),
                "engine": self.name,
                "best_params": dict(best["params"]) if best else None,
                "best_cost": float(best["cost"]) if best else None,
                "n_evaluations": int(result.get("n_real_used") or 0),
                "stop_reason": result.get("stop_reason"),
                # 墙钟剔除（replan 同口径：无墙钟进决策面）——同 seed 同输入
                # 的整个计划包络逐字节可复现
                "raw": {k: v for k, v in result.items()
                        if k != "elapsed_s"}}


class MCTSGridSearchEngine(ParamSearchEngine):
    """离散网格 MCTS 引擎（wraps service.mcts_search.mcts_plan，UCB1）。"""

    name = "mcts"

    def __init__(self, levels: int = MCTS_LEVELS_DEFAULT):
        self.levels = max(2, int(levels))

    def search(self, *, bounds, objectives, evaluate_fn,
               budget: int, seed: int) -> dict[str, Any]:
        from rfauto.core.objectives import SpecEvaluator
        from rfauto.service.mcts_search import mcts_plan

        names = sorted(bounds)
        levels = self.levels

        def state_params(state: tuple[int, ...]) -> dict[str, float]:
            return {n: float(bounds[n][0] + (bounds[n][1] - bounds[n][0])
                             * state[i] / (levels - 1))
                    for i, n in enumerate(names)}

        def evaluate_state(state: tuple[int, ...]) -> float:
            metrics = evaluate_fn(state_params(state))
            cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
            return -float(cost)  # 奖励口径越大越好

        def actions(state: tuple[int, ...]) -> list[tuple[int, ...]]:
            moves: list[tuple[int, ...]] = []
            for i in range(len(names)):
                for step in (-1, 1):
                    j = state[i] + step
                    if 0 <= j < levels:
                        moves.append((*state[:i], j, *state[i + 1:]))
            return moves or [state]

        start = tuple((levels - 1) // 2 for _ in names)
        result = mcts_plan(start, actions, lambda s, a: a, evaluate_state,
                           n_simulations=max(int(budget), 1), max_depth=levels,
                           seed=int(seed))
        best_state = result.get("best_state")
        best_params = (state_params(tuple(best_state))
                       if isinstance(best_state, tuple) else None)
        return {"ok": bool(result.get("ok")),
                "engine": self.name, "levels": levels,
                "best_params": best_params,
                "best_cost": -float(result.get("best_reward") or 0.0),
                "n_evaluations": int(result.get("n_evaluations") or 0),
                "best_policy": list(result.get("best_policy") or []),
                "raw": {k: v for k, v in result.items()
                        if k not in ("best_state",)}}


class EngineRegistry:
    """L2 引擎注册表（同 RuntimeRegistry/EMSolverRegistry 模式）。"""

    _engines: ClassVar[dict[str, type[ParamSearchEngine]]] = {}

    @classmethod
    def register(cls, engine_cls: type[ParamSearchEngine],
                 ) -> type[ParamSearchEngine]:
        cls._engines[engine_cls.name] = engine_cls
        return engine_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> ParamSearchEngine:
        if name not in cls._engines:
            raise KeyError(f"未注册的参数搜索引擎: {name}（可用: {cls.available()}）")
        return cls._engines[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._engines)


EngineRegistry.register(SurrogateSearchEngine)
EngineRegistry.register(MCTSGridSearchEngine)


def _allocate(total_budget: int, n_promoted: int) -> list[int]:
    """TOP_WEIGHTS 名额权重 → 份额（floor+余数给高位，确定性）。"""
    n = max(1, min(int(n_promoted), len(TOP_WEIGHTS)))
    weights = [TOP_WEIGHTS[i] / sum(TOP_WEIGHTS[:n]) for i in range(n)]
    shares = [int(float(total_budget) * w) for w in weights]
    remainder = int(total_budget) - sum(shares)
    for i in range(remainder):  # 余数按 rank 顺序逐个补 1
        shares[i % n] += 1
    return shares


def plan_campaign(candidates: Sequence[Mapping[str, Any]], *,
                  target_metrics: Mapping[str, float] | None = None,
                  engine: str = "surrogate",
                  total_budget: int = 40,
                  promote_top: int = 1,
                  seed: int = 42,
                  n_corpus: int = PREFILTER_N_CORPUS_DEFAULT,
                  ) -> dict[str, Any]:
    """AD-9 战役编排入口：L1 拓扑排序 → L2 参数搜索分派（永不抛）。

    candidates = [{"name", "recipe_path"}]；target_metrics 缺省用各配方
    自带 objectives 的 value 阈值（max_below/min_above 取 value，mean_within
    取区间中点——全部确定性派生，不引入新数字）。promote_top 截断 L1
    名次（缺省 1=单拓扑吃满预算）。
    """
    from rfauto.service.inverse_prefilter import prefilter_candidates

    try:
        cands = [dict(c) for c in (candidates or [])
                 if isinstance(c, Mapping) and c.get("recipe_path")]
        if not cands:
            return {"ok": False, "schema_version": SCHEDULE_SCHEMA,
                    "errors": ["candidates 为空或缺 recipe_path：拒绝空跑"]}
        if int(total_budget) < 1:
            return {"ok": False, "schema_version": SCHEDULE_SCHEMA,
                    "errors": [f"total_budget 必须 ≥1：{total_budget}"]}

        # ── L1 拓扑层：伪语料前滤波评分 + 确定性排序 ─────────────────────
        ranked: list[dict[str, Any]] = []
        for cand in cands:
            name = str(cand.get("name") or _recipe_stem(cand["recipe_path"]))
            view = _recipe_view(cand["recipe_path"])
            if not view["bounds"]:
                ranked.append({"name": name, "recipe": view["path"],
                               "score": None, "promoted": False,
                               "reason": "配方无 low/high 搜索空间，不参选"})
                continue
            targets = dict(target_metrics or {})
            if not targets:
                targets = _targets_from_objectives(view["objectives"])
            pre = prefilter_candidates(view["path"], targets, n_corpus=n_corpus,
                                       k=5, seed=int(seed))
            if not pre.get("ok"):
                ranked.append({"name": name, "recipe": view["path"],
                               "score": None, "promoted": False,
                               "reason": f"前滤波失败: "
                                         f"{list(pre.get('errors') or [])[:1]}"})
                continue
            best_distance = min(float(c["corpus_distance"])
                                for c in pre.get("candidates") or [])
            ranked.append({"name": name, "recipe": view["path"],
                           "score": -best_distance,
                           "best_corpus_distance": best_distance,
                           "promoted": False, "reason": ""})
        scored = sorted(
            (r for r in ranked if r["score"] is not None),
            key=lambda r: (-r["score"], r["name"]))
        n_promote = max(1, min(int(promote_top), len(scored)))
        shares = _allocate(int(total_budget), n_promote)
        for i, row in enumerate(scored):
            row["promoted"] = i < n_promote
            row["rank"] = i + 1
            row["budget_share"] = shares[i] if i < n_promote else 0
        for row in ranked:
            if row["score"] is None and "rank" not in row:
                row["rank"] = None

        # ── L2 参数层：promoted 候选逐个分派引擎 ─────────────────────────
        from rfauto.core.objectives import Objective

        search_engine = EngineRegistry.create(engine)
        runs: list[dict[str, Any]] = []
        for row in scored:
            if not row["promoted"] or row["budget_share"] < 1:
                continue
            view = _recipe_view(row["recipe"])
            objectives = [Objective(**o) for o in view["objectives"]]
            if not objectives:
                runs.append({"name": row["name"], "ok": False,
                             "errors": ["配方无 objectives，L2 无从评估"]})
                continue
            run = search_engine.search(
                bounds=view["bounds"], objectives=objectives,
                evaluate_fn=_recipe_evaluator(view),
                budget=row["budget_share"], seed=int(seed))
            runs.append({"name": row["name"], "budget_share": row["budget_share"],
                         **run})
        return ok_envelope(
            schema_version=SCHEDULE_SCHEMA,
            layers={"topology": {"ranked": ranked,
                                        "n_promoted": n_promote,
                                        "weights": list(TOP_WEIGHTS[:n_promote])},
                           "params": {"engine": engine, "runs": runs}},
            total_budget=int(total_budget),
            seed=int(seed),
            errors=[],
        )
    except Exception as exc:  # 编排面永不抛（#105）
        return {"ok": False, "schema_version": SCHEDULE_SCHEMA,
                "errors": [f"{type(exc).__name__}: {exc}"]}


def _recipe_stem(recipe_path: Any) -> str:
    """配方路径 → 缺省候选名（stem；确定性）。"""
    from pathlib import Path as _P

    return _P(str(recipe_path)).stem


def _targets_from_objectives(objectives: Sequence[Mapping[str, Any]],
                             ) -> dict[str, float]:
    """配方 objectives → 前滤波目标指标（单阈值取 value，区间取中点）。"""
    targets: dict[str, float] = {}
    for obj in objectives or []:
        metric = str(obj.get("metric") or "")
        value = obj.get("value")
        if not metric or value is None:
            continue
        if isinstance(value, (list, tuple)) and value:
            try:
                targets[metric] = float(sum(float(v) for v in value)
                                        / len(value))
            except (TypeError, ValueError):
                continue
        elif isinstance(value, (int, float)):
            targets[metric] = float(value)
    return targets
