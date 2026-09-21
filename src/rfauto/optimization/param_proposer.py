"""E12 参数域提议器（最小实现）：连续参数退火高斯扰动 + 贪心接受。

任务口径（B4/E12 参数域提议器最小实现与合成裁判评估）：
- :class:`ParamProposer` 基类统一接口 ``propose(bounds, rng, *, x_start,
  score_fn) -> 参数点 dict``；
- :data:`PROPOSER_PARAM_REGISTRY` + :func:`register_proposer_param`：
  基类+注册表模式（分层架构约束：新增可替换组件走基类+注册表）。形态仿
  ``core/inverse_diffusion.py`` 的 ``register_proposer``（重名/空名显式
  报错、同类幂等），但**不继承** :class:`PixelProposer`——接口不同：
  像素提议器产出 0/1 拓扑矩阵，本注册表产出连续参数向量。
- :class:`ParamAnnealedProposer`：σ_t 线性退火高斯扰动（步长日程递减）
  + 注入 ``score_fn`` 的贪心接受（只接受严格改善；``score_fn=None``
  时退化为纯噪声游走，仍受 bounds 裁剪）。

诚实边界（#122，不冒充；确定性内核纪律：数值只在确定性内核）
- 本模块只产出**参数点**；它消费的每一个分数都来自注入的 ``score_fn``
  （确定性评判器/代理/求解器响应包装），模块自身不产生任何物理数字
  ——频率/损耗/几何数值永不由提议器凭空给出。
- 这是**确定性退火随机游走**（annealed Gaussian random walk + greedy
  acceptance），不是扩散模型、不是贝叶斯优化；与随机搜索/gp-LCB 的
  配对对照见 ``scripts/param_proposer_bench.py``（结果如实，设计预期
  可能不敌 LCB——FAIL 也是交付，不调门凑绿）。

确定性：``random.Random`` 注入、``sorted(bounds)`` 固定参数枚举序、
无集合迭代——同 seed 同日程同评判器 → 逐位一致；
:meth:`ParamAnnealedProposer.propose_with_trace` 返回每步审计轨迹
（步长 σ / 候选分数 / 当前最优分数 / 是否接受）。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from rfauto.core.errors import ConfigError

__all__ = [
    "PROPOSER_PARAM_REGISTRY",
    "ParamAnnealedProposer",
    "ParamProposer",
    "create_param_proposer",
    "list_param_proposers",
    "register_proposer_param",
]

#: 贪心接受"严格改善"判定容差（与 inverse_diffusion 局部贪心同口径）。
_IMPROVE_EPS = 1e-12

#: 分数函数契约：参数点 → 标量 cost（越小越好），全部由调用方注入。
ScoreFn = Callable[[dict[str, float]], float]
Bounds = dict[str, tuple[float, float]]


class ParamProposer:
    """参数域提议器基类：只产出参数点，分数一律来自注入的评判器。"""

    #: 注册表键（子类必须覆盖为非空唯一字符串）。
    name: str = ""

    def propose(
        self,
        bounds: Bounds,
        rng: random.Random,
        *,
        x_start: dict[str, float] | None = None,
        score_fn: ScoreFn | None = None,
    ) -> dict[str, float]:  # pragma: no cover - 抽象接口
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """JSON 友好的自描述（名字 + 超参），供结果记录/审计。"""
        return {"name": self.name}


PROPOSER_PARAM_REGISTRY: dict[str, type[ParamProposer]] = {}


def register_proposer_param(cls: type[ParamProposer]) -> type[ParamProposer]:
    """类装饰器：按 ``cls.name`` 注册；名字空/重复显式报错（不静默覆盖）。"""
    name = str(getattr(cls, "name", "") or "").strip()
    if not name:
        raise ConfigError(f"参数域提议器 {cls.__name__} 未声明非空 name，拒绝注册")
    if name in PROPOSER_PARAM_REGISTRY and PROPOSER_PARAM_REGISTRY[name] is not cls:
        raise ConfigError(f"参数域提议器名字重复注册: {name!r}")
    PROPOSER_PARAM_REGISTRY[name] = cls
    return cls


def list_param_proposers() -> list[str]:
    """已注册参数域提议器名字（注册序，确定性）。"""
    return list(PROPOSER_PARAM_REGISTRY)


def create_param_proposer(name: str, **kwargs: Any) -> ParamProposer:
    """工厂：按名字构造提议器；未知名字报错并列出可用项。"""
    key = str(name).strip()
    cls = PROPOSER_PARAM_REGISTRY.get(key)
    if cls is None:
        raise ConfigError(
            f"未知参数域提议器 {name!r}；可用: {list_param_proposers()}")
    return cls(**kwargs)


# ---------------------------------------------------------------- helpers


def _check_bounds(bounds: Bounds) -> list[str]:
    """bounds 合法性守卫；返回排序后的参数名（固定枚举序，确定性）。"""
    if not bounds:
        raise ConfigError("bounds 为空（至少一个连续参数）")
    names = sorted(str(k) for k in bounds)
    for n in names:
        lo, hi = (float(v) for v in bounds[n])
        if not hi > lo:
            raise ConfigError(f"参数 {n!r} 的 bounds 非法：需 hi > lo，"
                              f"实得 ({lo}, {hi})")
    return names


def _as_start(names: list[str], bounds: Bounds,
              x_start: dict[str, float] | None,
              rng: random.Random) -> dict[str, float]:
    """起点归一：缺省时由 rng 均匀采样（确定性）；多余/缺失键报错。"""
    if x_start is None:
        return {n: float(rng.uniform(bounds[n][0], bounds[n][1]))
                for n in names}
    missing = [n for n in names if n not in x_start]
    extra = [k for k in x_start if k not in names]
    if missing or extra:
        raise ConfigError(
            f"x_start 键与 bounds 不符：缺失 {missing}，多余 {extra}")
    out: dict[str, float] = {}
    for n in names:
        lo, hi = (float(v) for v in bounds[n])
        out[n] = min(hi, max(lo, float(x_start[n])))
    return out


def _clip(name: str, val: float, bounds: Bounds) -> float:
    lo, hi = (float(v) for v in bounds[name])
    return min(hi, max(lo, val))


# ---------------------------------------------------------------- proposer


@register_proposer_param
class ParamAnnealedProposer(ParamProposer):
    """连续参数退火高斯扰动提议器：(1+1) 贪心游走 × σ_t 线性退火。

    每步：候选 = 当前点 + σ_t·(hi−lo)·N(0,1)（逐参数独立、bounds 裁剪）；
    评测候选（一次 score_fn 调用 = 一次评估预算），仅当分数严格优于当前
    最优才接受（贪心）。σ_t 自 ``sigma_max`` 线性退火至 ``sigma_min``。

    Args:
        n_steps: 迭代步数（≥1）；每步恰一次 score_fn 评估。
        sigma_max / sigma_min: 首步 / 末步相对步长（参数跨度的比例，
            0 ≤ sigma_min ≤ sigma_max）。
        x_improve_eps: "严格改善"判定容差。
    """

    name = "param_annealed"

    def __init__(
        self,
        *,
        n_steps: int = 30,
        sigma_max: float = 0.30,
        sigma_min: float = 0.02,
        x_improve_eps: float = _IMPROVE_EPS,
    ) -> None:
        n_steps = int(n_steps)
        if n_steps < 1:
            raise ConfigError(f"n_steps 必须 ≥ 1，实得 {n_steps}")
        sigma_max = float(sigma_max)
        sigma_min = float(sigma_min)
        if not (0.0 <= sigma_min <= sigma_max) or sigma_max <= 0.0:
            raise ConfigError(
                f"需 0 < sigma_max 且 0 ≤ sigma_min ≤ sigma_max，实得 "
                f"sigma_min={sigma_min} sigma_max={sigma_max}")
        self.n_steps = n_steps
        self.sigma_max = sigma_max
        self.sigma_min = sigma_min
        self.x_improve_eps = float(x_improve_eps)

    # -- 日程 ---------------------------------------------------------------
    def sigma_schedule(self) -> list[float]:
        """线性退火步长日程 σ_1..σ_n（单调不增；n=1 时只取 sigma_max）。"""
        if self.n_steps == 1:
            return [self.sigma_max]
        span = self.sigma_max - self.sigma_min
        return [
            self.sigma_max - span * k / (self.n_steps - 1)
            for k in range(self.n_steps)
        ]

    # -- 接口 -----------------------------------------------------------------
    def propose_with_trace(
        self,
        bounds: Bounds,
        rng: random.Random,
        *,
        x_start: dict[str, float] | None = None,
        score_fn: ScoreFn | None = None,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        """提议 + 每步审计轨迹。

        轨迹元素: ``{step, sigma, score_cand, score_best, accepted}``；
        ``score_fn=None`` 时分数键为 None、accepted 恒 False（纯噪声游走，
        仍返回走到的末点）。
        """
        names = _check_bounds(bounds)
        x = _as_start(names, bounds, x_start, rng)
        best: dict[str, float] = dict(x)
        best_score: float | None = (
            float(score_fn(dict(best))) if score_fn is not None else None)
        trace: list[dict[str, Any]] = []
        for step, sigma in enumerate(self.sigma_schedule(), start=1):
            cand = {
                n: _clip(n, x[n] + sigma * (bounds[n][1] - bounds[n][0])
                         * rng.gauss(0.0, 1.0), bounds)
                for n in names
            }
            accepted = False
            score_cand: float | None = None
            if score_fn is not None:
                score_cand = float(score_fn(dict(cand)))
                if score_cand < best_score - self.x_improve_eps:
                    x = cand
                    best = dict(cand)
                    best_score = score_cand
                    accepted = True
            else:
                x = cand
            trace.append({
                "step": step,
                "sigma": sigma,
                "score_cand": score_cand,
                "score_best": best_score,
                "accepted": accepted,
            })
        return best, trace

    def propose(
        self,
        bounds: Bounds,
        rng: random.Random,
        *,
        x_start: dict[str, float] | None = None,
        score_fn: ScoreFn | None = None,
    ) -> dict[str, float]:
        best, _trace = self.propose_with_trace(
            bounds, rng, x_start=x_start, score_fn=score_fn)
        return best

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "annealed_gaussian_greedy_walk（确定性退火随机游走，"
                    "非扩散模型/非贝叶斯优化；分数全来自注入评判器）",
            "n_steps": self.n_steps,
            "sigma_max": self.sigma_max,
            "sigma_min": self.sigma_min,
        }
