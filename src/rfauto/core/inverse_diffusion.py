"""像素逆设计 stage-2 离线段：提议器注册表 + 确定性"扩散式"噪声-去噪提议器。

任务口径：在既有像素逆设计闭环
（core/inverse_design.py：提议器 × MAPES 闭式评判 × top-k）上加一个可注入
随机源、固定 seed 可复现的"扩散式"提议器——噪声-去噪迭代把可行像素图案向
目标推进，评判仍走既有确定性内核（core/mapes 闭式代理）。

设计（基类 + 注册表，可替换组件模式）
- :class:`PixelProposer` 基类统一接口 ``propose(layout, rng, *, seed_pattern,
  score_fn) -> 0/1 numpy 矩阵``；:data:`PROPOSER_REGISTRY` 以名字注册，
  :func:`create_proposer` 工厂构造——换/加提议器实现注册即可。
- :class:`RandomBernoulliProposer` 包装既有 ``propose_random``（基线档）。
- :class:`DiffusionProposer`（``diffusion_annealed``）：
  前向（noising）——逐像素以噪声率 β_t 伯努利翻转（rng 注入，行主序）；
  反向（denoising）——用注入的确定性评判分数做 1-bit 贪心去噪（只接受严格
  改善，最多 ``polish_flips`` 次翻转）；β_t 自 ``beta_max`` 线性退火至
  ``beta_min``，共 ``n_steps`` 步；起点为种子图案（无种子则伯努利噪声）。

诚实边界（#122，不冒充）
- 这是**离散退火式噪声-去噪提议器**（deterministic annealed discrete
  denoising），**不是**训练出的神经扩散/流匹配生成模型；命名带引号的
  "扩散式"即此意。
- 数值只在确定性内核：提议器只产出**拓扑**（0/1 像素矩阵）；去噪步消费的分数全部来自
  注入的 ``score_fn``（inverse_design.evaluate_occupancy → core/mapes 闭式
  内核），本模块不产生任何物理数字；``score_fn=None`` 时退化为纯噪声游走。
- Z_ALL 真机段（adapters/openems_rotation 多端口轮转提取）不在本模块
  （followUp）。

确定性：random.Random 注入、行主序枚举、无集合迭代——同 seed 同日程同评判器
→ 逐像素一致；:meth:`DiffusionProposer.propose_with_trace` 返回每步审计轨迹
（翻转数 / 去噪前后分数）。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.errors import ConfigError
from rfauto.core.inverse_design import one_flip_neighbors, propose_random
from rfauto.core.mapes import PixelLayout

__all__ = [
    "PROPOSER_REGISTRY",
    "DiffusionProposer",
    "PixelProposer",
    "RandomBernoulliProposer",
    "create_proposer",
    "list_proposers",
    "register_proposer",
]

#: 去噪步"严格改善"判定容差（dB）；与 inverse_design 局部贪心同口径。
_IMPROVE_EPS = 1e-12

ScoreFn = Callable[[np.ndarray], float]


class PixelProposer:
    """像素提议器基类：只产出 0/1 拓扑，数字一律来自注入的评判器。"""

    #: 注册表键（子类必须覆盖为非空唯一字符串）。
    name: str = ""

    def propose(
        self,
        layout: PixelLayout,
        rng: random.Random,
        *,
        seed_pattern: Any = None,
        score_fn: ScoreFn | None = None,
    ) -> np.ndarray:  # pragma: no cover - 抽象接口
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """JSON 友好的自描述（名字 + 超参），供结果记录/审计。"""
        return {"name": self.name}


PROPOSER_REGISTRY: dict[str, type[PixelProposer]] = {}


def register_proposer(cls: type[PixelProposer]) -> type[PixelProposer]:
    """类装饰器：按 ``cls.name`` 注册；名字空/重复显式报错（不静默覆盖）。"""
    name = str(getattr(cls, "name", "") or "").strip()
    if not name:
        raise ConfigError(f"提议器 {cls.__name__} 未声明非空 name，拒绝注册")
    if name in PROPOSER_REGISTRY and PROPOSER_REGISTRY[name] is not cls:
        raise ConfigError(f"提议器名字重复注册: {name!r}")
    PROPOSER_REGISTRY[name] = cls
    return cls


def list_proposers() -> list[str]:
    """已注册提议器名字（注册序，确定性）。"""
    return list(PROPOSER_REGISTRY)


def create_proposer(name: str, **kwargs: Any) -> PixelProposer:
    """工厂：按名字构造提议器；未知名字报错并列出可用项。"""
    key = str(name).strip()
    cls = PROPOSER_REGISTRY.get(key)
    if cls is None:
        raise ConfigError(
            f"未知提议器 {name!r}；可用: {list_proposers()}")
    return cls(**kwargs)


def _as_pattern(layout: PixelLayout, pattern: Any) -> np.ndarray:
    occ = np.array(pattern, dtype=bool, copy=True)
    if occ.shape != (layout.n_rows, layout.n_cols):
        raise ConfigError(
            f"seed_pattern 形状 {occ.shape} 与版图 "
            f"({layout.n_rows}, {layout.n_cols}) 不符")
    return occ


@register_proposer
class RandomBernoulliProposer(PixelProposer):
    """基线档：随机伯努利提议器（包装 inverse_design.propose_random）。"""

    name = "random_bernoulli"

    def __init__(self, *, p_on: float = 0.5) -> None:
        if not 0.0 <= float(p_on) <= 1.0:
            raise ConfigError(f"p_on 必须落在 [0,1]，实得 {p_on}")
        self.p_on = float(p_on)

    def propose(
        self,
        layout: PixelLayout,
        rng: random.Random,
        *,
        seed_pattern: Any = None,
        score_fn: ScoreFn | None = None,
    ) -> np.ndarray:
        # 基线提议器忽略种子与评判器：纯随机拓扑。
        return propose_random(layout, rng, p_on=self.p_on)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "p_on": self.p_on}


@register_proposer
class DiffusionProposer(PixelProposer):
    """确定性"扩散式"提议器：退火噪声（forward）× 评判器引导去噪（backward）。

    Args:
        n_steps: 噪声-去噪迭代步数（≥1）。
        beta_max / beta_min: 首步 / 末步逐像素翻转率（线性退火，
            0 ≤ beta_min ≤ beta_max ≤ 1）。
        p_on: 无种子图案时的初始伯努利占用率。
        polish_flips: 每个去噪步最多接受的严格改善翻转数（≥0；0=纯噪声游走）。
    """

    name = "diffusion_annealed"

    def __init__(
        self,
        *,
        n_steps: int = 6,
        beta_max: float = 0.35,
        beta_min: float = 0.05,
        p_on: float = 0.5,
        polish_flips: int = 1,
    ) -> None:
        n_steps = int(n_steps)
        if n_steps < 1:
            raise ConfigError(f"n_steps 必须 ≥ 1，实得 {n_steps}")
        beta_max = float(beta_max)
        beta_min = float(beta_min)
        if not (0.0 <= beta_min <= beta_max <= 1.0):
            raise ConfigError(
                f"需 0 ≤ beta_min ≤ beta_max ≤ 1，实得 beta_min={beta_min} "
                f"beta_max={beta_max}")
        if not 0.0 <= float(p_on) <= 1.0:
            raise ConfigError(f"p_on 必须落在 [0,1]，实得 {p_on}")
        polish_flips = int(polish_flips)
        if polish_flips < 0:
            raise ConfigError(f"polish_flips 必须 ≥ 0，实得 {polish_flips}")
        self.n_steps = n_steps
        self.beta_max = beta_max
        self.beta_min = beta_min
        self.p_on = float(p_on)
        self.polish_flips = polish_flips

    # -- 日程 ---------------------------------------------------------------
    def betas(self) -> list[float]:
        """线性退火噪声日程 β_1..β_n（n=1 时只取 beta_max）。"""
        if self.n_steps == 1:
            return [self.beta_max]
        span = self.beta_max - self.beta_min
        return [
            self.beta_max - span * k / (self.n_steps - 1)
            for k in range(self.n_steps)
        ]

    # -- 单步 -----------------------------------------------------------------
    @staticmethod
    def _noise(occ: np.ndarray, beta: float, rng: random.Random) -> tuple[np.ndarray, int]:
        """前向：逐像素以概率 β 翻转（行主序消费 rng，确定性）。"""
        out = occ.copy()
        flipped = 0
        for r in range(out.shape[0]):
            for c in range(out.shape[1]):
                if rng.random() < beta:
                    out[r, c] = not out[r, c]
                    flipped += 1
        return out, flipped

    def _denoise(
        self, occ: np.ndarray, score_fn: ScoreFn,
    ) -> tuple[np.ndarray, float, float, int]:
        """反向：1-bit 贪心去噪，只接受严格改善（分数越小越好）。"""
        before = float(score_fn(occ))
        current, cur_score = occ, before
        accepted = 0
        for _ in range(self.polish_flips):
            best: np.ndarray | None = None
            best_score = cur_score
            for cand in one_flip_neighbors(current):
                s = float(score_fn(cand))
                if s < best_score - _IMPROVE_EPS:
                    best, best_score = cand, s
            if best is None:
                break
            current, cur_score = best, best_score
            accepted += 1
        return current, before, cur_score, accepted

    # -- 接口 -----------------------------------------------------------------
    def propose_with_trace(
        self,
        layout: PixelLayout,
        rng: random.Random,
        *,
        seed_pattern: Any = None,
        score_fn: ScoreFn | None = None,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """提议 + 每步审计轨迹 [{step, beta, n_noised, score_noised, score_denoised, n_denoise_flips}]。"""
        occ = (
            propose_random(layout, rng, p_on=self.p_on)
            if seed_pattern is None
            else _as_pattern(layout, seed_pattern)
        )
        trace: list[dict[str, Any]] = []
        for step, beta in enumerate(self.betas(), start=1):
            occ, n_noised = self._noise(occ, beta, rng)
            record: dict[str, Any] = {
                "step": step,
                "beta": beta,
                "n_noised": n_noised,
                "score_noised": None,
                "score_denoised": None,
                "n_denoise_flips": 0,
            }
            if score_fn is not None and self.polish_flips > 0:
                occ, before, after, accepted = self._denoise(occ, score_fn)
                record.update({
                    "score_noised": before,
                    "score_denoised": after,
                    "n_denoise_flips": accepted,
                })
            trace.append(record)
        return occ, trace

    def propose(
        self,
        layout: PixelLayout,
        rng: random.Random,
        *,
        seed_pattern: Any = None,
        score_fn: ScoreFn | None = None,
    ) -> np.ndarray:
        occ, _trace = self.propose_with_trace(
            layout, rng, seed_pattern=seed_pattern, score_fn=score_fn)
        return occ

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "annealed_discrete_denoising（确定性噪声-去噪，非训练生成模型）",
            "n_steps": self.n_steps,
            "beta_max": self.beta_max,
            "beta_min": self.beta_min,
            "p_on": self.p_on,
            "polish_flips": self.polish_flips,
        }
