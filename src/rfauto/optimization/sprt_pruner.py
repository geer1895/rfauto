"""OP-8（round16 §六）：SPRT 早停 pruner——core/sprt 内核接线 Optuna 剪枝面。

round16 现状记录："SPRT optuna_prune_decision 未接线"。本模块把
core/sprt.py 的 Wald 序贯概率比检验接成 ``optuna.pruners.BasePruner``，
并经 optimizer._build_pruner 以 pruner="sprt" 名字进入 ME-13 pruner
通道（与 asha/hyperband 同旋钮位）。

统计语义（全部判据来自 core/sprt.py，Wald 1945 / Johari KDD'17，来源
钉在彼处 docstring——本模块只做接线不重新发明统计）：

- 观测流 = **逐 report 步的"对当前最优改进量"**（最小化口径）：
  x_1 = (study.best_value − v_1)（基线=开跑时已完成 trial 的最优；无
  已完成 trial 时如实不判），x_t = v_{t−1} − v_t（t≥2，正=在改进）。
  本仓 build_objective 的 simple-report 语义只有 step=1 一个中间值，
  故常态下单观测判定；多保真适配器未来提供多步 report 时同一 pruner
  自然升级为序贯（spec 原文"未来适配器提供多保真中间 cost 时同一
  pruner 消费多步 report"）。
- H0 =「试验相对当前最优无期望改进」（均值 0），H1 =「有 δ>0 的期望
  改进」；LLR = Σ normal_llr_increment(x_t, mu0=0, mu1=δ, σ)。Λ≤B
  （accept H0）→ prune=True；Λ≥A（显著在改进）→ 继续；期间 → 继续。
- LLR 从 trial.intermediate_values 全量重算（无跨步状态）——纯函数
  语义，同输入同判定（C4 确定性红线），且天然兼容 optuna 的
  pruner 重放/中断恢复语义。
- δ（H1 期望改进量）与 σ（单步 cost 观测标准差）必须由调用方显式
  给出（pruner_kwargs）——本模块不臆造 cost 尺度（铁律 7：数值只在
  确定性内核；调用方从既有 cost 历史估计，或用保守界）。

对照裁判（tests/unit/test_sprt_pruner.py）：#207 口径合成函数上
sprt vs none 双臂配对 seed，scipy.stats.wilcoxon 对照 best-f 分布 +
剪枝节省评估数如实记账（合成数据预声明判据，不赌真机）。
"""

from __future__ import annotations

from typing import Any

import optuna

from rfauto.core.sprt import (
    normal_llr_increment,
    sprt_decide,
    wald_bounds,
)


def improvement_stream(
    trial: optuna.trial.FrozenTrial | optuna.Trial,
    study: optuna.Study,
) -> list[float] | None:
    """trial 的中间值序列 → 对当前最优的改进量流（无基线时 None）。

    最小化口径；步号升序。基线 = 调用时刻已完成（COMPLETE）trial 的
    最优 cost；study 里没有已完成 trial 时返回 None（首个 trial 无从
    判"是否有改进"，不剪——保守面与 asha 缺省一致）。运行中的
    optuna.Trial 不暴露 intermediate_values——经 storage 读冻结快照。
    """
    iv = getattr(trial, "intermediate_values", None) or None
    if not iv:
        try:
            frozen = next(t for t in study.get_trials(deepcopy=False)
                          if t.number == trial.number)
            iv = frozen.intermediate_values
        except StopIteration:
            return None
    if not iv:
        return None
    values = [v for _, v in sorted(iv.items(), key=lambda kv: int(kv[0]))]
    best = None
    for t in study.get_trials(deepcopy=False,
                              states=(optuna.trial.TrialState.COMPLETE,)):
        if t.value is not None:
            best = t.value if best is None else min(best, t.value)
    if best is None:
        return None
    stream = [best - values[0]]
    stream.extend(values[i - 1] - values[i] for i in range(1, len(values)))
    return stream


class SPRTPruner(optuna.pruners.BasePruner):
    """Wald SPRT 早停 pruner（H0=无改进 → 剪）。

    Args:
        delta: H1 下的期望单步改进量（cost 单位，>0；调用方从 cost
            历史显式给出）。
        sigma: 单步改进观测标准差（cost 单位，>0）。
        alpha: 第一类错误上界（把"在改进"的试验误剪为 H0 的概率侧）。
        beta: 第二类错误上界。
    """

    def __init__(
        self,
        delta: float,
        sigma: float,
        alpha: float = 0.05,
        beta: float = 0.10,
    ) -> None:
        for name, val in (("delta", delta), ("sigma", sigma)):
            if isinstance(val, bool) or not float(val) > 0.0:
                raise ValueError(
                    f"{name} 必须为 >0 的有限数（调用方显式给出，不臆造 "
                    f"cost 尺度），实得 {val!r}")
        self.delta = float(delta)
        self.sigma = float(sigma)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.bounds = wald_bounds(self.alpha, self.beta)

    def prune(self, study: optuna.Study, trial: optuna.trial.FrozenTrial) -> bool:
        stream = improvement_stream(trial, study)
        if not stream:
            return False
        llr = 0.0
        for x in stream:
            llr += normal_llr_increment(float(x), 0.0, self.delta, self.sigma)
        decision = sprt_decide(llr, self.bounds)
        return bool(decision.prune)

    def describe(self) -> dict[str, Any]:
        """JSON 友好自描述（审计/报告面）。"""
        return {
            "pruner": "sprt",
            "delta": self.delta,
            "sigma": self.sigma,
            "alpha": self.alpha,
            "beta": self.beta,
            "bounds": self.bounds.to_dict(),
            "rule": "H0=无改进(剪)；Λ≤B 剪，Λ≥A 继续（Wald 1945）",
        }
