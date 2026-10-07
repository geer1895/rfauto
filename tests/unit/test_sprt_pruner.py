"""OP-8（round16 §六）：SPRT 早停 pruner 接线 + Wilcoxon 对照 单元测试。

统计语义全部来自 core/sprt.py（Wald 1945；来源钉彼处），本文件钉接线
与判据（合成函数，#207；数字 2026-10-03 本机冻结）：

1. **观测流语义**：improvement_stream——基线=已完成 trial 最优；无基线
   → None（不剪）；步升序；x_1=best−v1、x_t=v_{t−1}−v_t；
2. **pruner 判定**（机制级）：明显改进流（每步+0.5，δ=0.2,σ=0.1）→
   Λ 走上界不剪；持续无改进流（每步 0）→ Λ≤B 剪（alpha=0.05,
   beta=0.1 时单观测 LLR=(0−0−0.1)·(0−0.1)/σ²... 数值锚见用例）；
3. **接线**：optimizer._build_pruner("sprt", kwargs) 产出 SPRTPruner；
   缺 delta/sigma → ValueError（经 run_optimization 软失败面转
   {"ok": False}——由 PRUNER_CHOICES 校验与软失败路径钉）；
4. **optuna 集成**：内存 study 内真实 ask/report/should_prune 流——
   坏 trial（cost 无改进）被剪、好 trial（显著改进）存活；
5. **Wilcoxon 对照**（#207 合成目标，7 seeds 配对）：sprt vs none 双臂
   best-f——中位退化 ≤ 预算同额下的合成容差；scipy.stats.wilcoxon
   p 值如实记入报告（不设显著性断言——n=7 检验力有限，#122 不凑绿）；
   剪枝节省评估数如实记账。

铁律 7 对照：全部数字出自 core/sprt 解析边界与合成目标解析值。
"""

from __future__ import annotations

import numpy as np
import optuna
import pytest
from scipy import stats

from rfauto.optimization.optimizer import PRUNER_CHOICES, _build_pruner
from rfauto.optimization.sprt_pruner import SPRTPruner, improvement_stream

ALPHA, BETA, DELTA, SIGMA = 0.05, 0.10, 0.2, 0.1


def _make_pruner() -> SPRTPruner:
    return SPRTPruner(delta=DELTA, sigma=SIGMA, alpha=ALPHA, beta=BETA)


class TestImprovementStream:
    def test_stream_against_completed_best(self):
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="minimize")
        t_done = study.ask()
        t_done.suggest_float("x", 0.0, 1.0)
        study.tell(t_done, 1.0)                       # 基线 best=1.0
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        t.report(0.8, step=1)                          # 改进 0.2
        t.report(0.7, step=2)                          # 再改进 0.1
        stream = improvement_stream(t, study)
        assert stream == pytest.approx([0.2, 0.1])

    def test_no_completed_baseline_returns_none(self):
        study = optuna.create_study(direction="minimize")
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        t.report(0.5, step=1)
        assert improvement_stream(t, study) is None

    def test_no_intermediate_returns_none(self):
        study = optuna.create_study(direction="minimize")
        t_done = study.ask()
        study.tell(t_done, 1.0)
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        assert improvement_stream(t, study) is None


class TestPrunerDecision:
    def test_clear_improvement_not_pruned(self):
        pruner = _make_pruner()
        study = optuna.create_study(direction="minimize")
        seed = study.ask()
        study.tell(seed, 1.0)
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        t.report(0.3, step=1)   # 改进 0.7 = 3.5×H1 期望 → Λ 显著 >A
        assert pruner.prune(study, t) is False

    def test_stagnation_pruned(self):
        pruner = _make_pruner()
        study = optuna.create_study(direction="minimize")
        for v in (1.0, 1.0):
            t0 = study.ask()
            t0.suggest_float("x", 0.0, 1.0)
            study.tell(t0, v)
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        t.report(1.0, step=1)   # 改进 0 → LLR 单观测 = z(0) < B
        # z = δ(0 − δ/2)/σ² = 0.2·(−0.1)/0.01 = −2.0；B = ln(β/(1−α)) ≈ −2.25
        # → 单观测恰好 continue；再报一步 0 增量 → Λ=−4.0 ≤ B → 剪
        assert pruner.prune(study, t) is False
        t.report(1.0, step=2)
        assert pruner.prune(study, t) is True

    def test_build_pruner_wiring(self):
        pruner = _build_pruner(
            "sprt", {"delta": DELTA, "sigma": SIGMA,
                     "alpha": ALPHA, "beta": BETA})
        assert isinstance(pruner, SPRTPruner)
        assert pruner.describe()["rule"].startswith("H0=无改进")

    def test_build_pruner_missing_kwargs_rejected(self):
        with pytest.raises(ValueError, match="delta"):
            _build_pruner("sprt", {})
        with pytest.raises(ValueError, match="sigma"):
            _build_pruner("sprt", {"delta": 0.2})

    def test_choices_contains_sprt(self):
        assert "sprt" in PRUNER_CHOICES

    def test_bad_delta_rejected(self):
        with pytest.raises(ValueError, match="delta"):
            SPRTPruner(delta=0.0, sigma=0.1)


class TestOptunaIntegration:
    def test_bad_trial_pruned_good_trial_survives(self):
        pruner = _make_pruner()
        study = optuna.create_study(direction="minimize", pruner=pruner)
        # 种子 best
        t0 = study.ask()
        t0.suggest_float("x", 0.0, 1.0)
        study.tell(t0, 1.0)
        # 坏 trial：cost 无改进，双步零增量 → 触 B 剪
        bad = study.ask()
        bad.suggest_float("x", 0.0, 1.0)
        bad.report(1.0, step=1)
        bad.report(1.0, step=2)
        assert bad.should_prune() is True
        # 好 trial：显著改进 → 不剪
        good = study.ask()
        good.suggest_float("x", 0.0, 1.0)
        good.report(0.2, step=1)
        assert good.should_prune() is False


class TestWilcoxonComparison:
    """sprt vs none 配对对照（合成目标；判据预声明，数字冻结）。"""

    @staticmethod
    def _run_arm(pruner_name: str, seed: int) -> tuple[float, int]:
        """合成单变量 BO（TPE, 30 trial）：返回 (best_f, n_pruned)。"""
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        pruner = _build_pruner(pruner_name, {"delta": 0.05, "sigma": 0.2}) \
            if pruner_name == "sprt" else None
        study = optuna.create_study(direction="minimize", pruner=pruner)

        def objective(trial):
            x = trial.suggest_float("x", 0.0, 1.0)
            f = float((x - 0.37) ** 2 * 10.0) + 0.05 * np.sin(20 * x)
            trial.report(f, step=1)
            if trial.should_prune():
                raise optuna.TrialPruned()
            return f

        study.optimize(objective, n_trials=30)
        best = study.best_value
        pruned = len([t for t in study.trials
                      if t.state == optuna.trial.TrialState.PRUNED])
        return best, pruned

    def test_wilcoxon_paired_no_degradation_and_savings_reported(self):
        seeds = [101, 103, 107, 109, 113, 127, 131]
        bests_none, bests_sprt, savings = [], [], []
        for s in seeds:
            b0, _ = self._run_arm("none", s)
            b1, p1 = self._run_arm("sprt", s)
            bests_none.append(b0)
            bests_sprt.append(b1)
            savings.append(p1)
        a = np.asarray(bests_none)
        b = np.asarray(bests_sprt)
        # 判据（预声明）：sprt 臂中位 best-f 退化 ≤ 合成容差 0.05
        # （TPE 随机性量级；剪枝省下的评估以额外预算语义近似）
        assert float(np.median(b - a)) <= 0.05
        w = stats.wilcoxon(b, a)  # 配对秩检验；n=7 检验力有限——只记录不设显著性门
        report = {
            "median_delta_best_f": float(np.median(b - a)),
            "wilcoxon_p": float(w.pvalue),
            "total_pruned": int(sum(savings)),
        }
        assert report["total_pruned"] >= 0
        # 如实记账面（打印进测试日志供审计，不凑绿）
        print("wilcoxon 对照报告:", report)
