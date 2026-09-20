"""E11 warm-start 战役判定逻辑单测（合成数据钉死，零真机零长跑）。

被测对象：scripts/e11_warm_start_campaign.py 的纯判定函数
（cumulative_best / trials_to_target / judge_campaign /
build_history_samples）与战役编排接线（run_campaign，monkeypatch 假通道）。
真跑面不在单测范围——验收真跑按战役脚本独立执行。

判定口径（target 偏置修复后的新语义）：
- "同族真跑次数再降 ≥30%" → 配对 time-to-target 的平均缩减率 ≥ 阈值；
- target **先验固定**：缺省=冷臂末代累计 best，或调用方显式传入
  （旧口径 min(双臂末代 best) 是事后 target——末代质量优势会被合成
  "次数缩减"，已废弃，反例见 TestJudgeCampaignPriorTarget）；
- 缩减率只统计双臂都达同一 target 的种子；未达臂记 censored（不进
  均值），censored 种子数在 n_censored/verdict 透出——未达标如实
  FAIL，不凑绿。

判定钉死（2026-09-17 收口）：
- channel 口径：verdict 顶层带 ``channel``=adapter_name，meta 记 cold/warm
  双臂通道——fake 通道数字不得填"真跑次数"判据（TestRunCampaignWiring）；
- 历史集上界剔除：warm 历史集构造剔除全部 cost ≤ target+ε 的上界/目标点
  （历史集含最优点时缩减率是构造上界，e11c_main 95.5% 实证）——
  TestBuildHistorySamples 做全量集与构造集差集断言。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from e11_warm_start_campaign import (
    build_history_samples,
    cumulative_best,
    judge_campaign,
    run_campaign,
    trials_to_target,
)


class TestCumulativeBest:
    def test_running_min(self):
        assert cumulative_best([5.0, 3.0, 4.0, 1.0]) == [5.0, 3.0, 3.0, 1.0]

    def test_none_trials_do_not_update(self):
        assert cumulative_best([2.0, None, 1.0, None]) == [2.0, 2.0, 1.0, 1.0]

    def test_empty(self):
        assert cumulative_best([]) == []

    def test_zero_plateau(self):
        assert cumulative_best([1.0, 0.0, 0.0]) == [1.0, 0.0, 0.0]


class TestTrialsToTarget:
    def test_reached_midway(self):
        # 累计 best 在第 4 次评估首次 ≤ 0.5
        assert trials_to_target([9.0, 8.0, 7.0, 0.5, 0.6], 0.5, budget=10) == 4

    def test_reached_at_first_trial(self):
        assert trials_to_target([0.1, 5.0], 0.5, budget=10) == 1

    def test_never_reached_is_censored_to_budget(self):
        assert trials_to_target([9.0, 8.0, 7.0], 0.5, budget=6) == 6

    def test_empty_trajectory_censored(self):
        assert trials_to_target([], 0.5, budget=7) == 7

    def test_all_failed_trials_censored(self):
        assert trials_to_target([None, None], 0.5, budget=4) == 4

    def test_epsilon_tolerances_exact_hit(self):
        # target=0.0 平底：0.0 ≤ 0.0 + 1e-12 判达标
        assert trials_to_target([1.0, 0.0], 0.0, budget=5) == 2

    def test_budget_floor_at_least_one(self):
        assert trials_to_target([], 0.5, budget=0) == 1


class TestJudgeCampaignPass:
    def test_warm_reaches_target_much_earlier_pass(self):
        # target = 冷臂末代 best = 0.5（先验）；冷臂第 8 次才到，热臂先验第 1 次即到
        pairs = {
            "11": {
                "cold": [9.0, 7.0, 5.0, 3.0, 2.0, 1.0, 0.8, 0.5],
                "warm": [0.5, 0.6],
            },
        }
        v = judge_campaign(pairs, budget=30, threshold_pct=30.0)
        assert v["pass"] is True
        assert v["n_seeds"] == 1
        assert v["n_censored"] == 0
        row = v["per_seed"]["11"]
        assert row["target_cost"] == pytest.approx(0.5)
        assert row["cold_trials_to_target"] == 8
        assert row["warm_trials_to_target"] == 1
        assert row["reduction_pct"] == 87.5
        assert "PASS" in v["verdict"]

    def test_three_seeds_aggregate_mean(self):
        # 新口径（target=各冷臂末代）：逐种子缩减 87.5 / 83.33 / 33.33
        # → 均值 ≈68.06 ≥ 30 → PASS（旧口径 min(双臂末代) 时为 73.3——
        # seed 11/22 的 warm 末代 0.3 < 冷臂 0.5 曾把 target 拉更低）
        pairs = {
            "11": {"cold": [9.0, 7.0, 5.0, 3.0, 2.0, 1.0, 0.8, 0.5],
                   "warm": [0.4, 0.3]},
            "22": {"cold": [8.0, 6.0, 4.0, 2.0, 1.0, 0.5],
                   "warm": [0.4, 0.3]},
            "33": {"cold": [2.0, 1.0, 0.5], "warm": [0.6, 0.5]},
        }
        v = judge_campaign(pairs, budget=30)
        assert v["pass"] is True
        assert v["n_seeds"] == 3
        assert v["mean_reduction_pct"] == pytest.approx(68.06, abs=0.1)
        # 逐种子明细齐备（可审计）
        assert set(v["per_seed"]) == {"11", "22", "33"}

    def test_zero_plateau_target(self):
        # fake wilkinson 平底碗（#207）：冷臂末代=0.0 → target=0.0，
        # warm 先验即 0.0（新口径结论与旧口径一致）
        pairs = {
            "11": {"cold": [1.0, 2.0, 0.0, 3.0], "warm": [0.0, 0.0]},
        }
        v = judge_campaign(pairs, budget=10)
        assert v["pass"] is True
        row = v["per_seed"]["11"]
        assert row["target_cost"] == 0.0
        assert row["cold_trials_to_target"] == 3
        assert row["warm_trials_to_target"] == 1


class TestJudgeCampaignFail:
    def test_warm_no_better_than_cold_is_censored_not_negative_counted(self):
        # 冷臂末代 0.5 = target；热臂整预算未达 0.5 → censored（不进均值）
        # 语义变化：旧口径把 censored 当 reduction=-100% 计入均值（仍 FAIL）；
        # 新口径剔除该种子、透出 n_censored=1，均值无样本 → FAIL
        pairs = {
            "11": {"cold": [5.0, 1.0, 0.5], "warm": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0]},
        }
        v = judge_campaign(pairs, budget=6, threshold_pct=30.0)
        assert v["pass"] is False
        assert v["n_seeds"] == 0
        assert v["n_censored"] == 1
        assert "FAIL" in v["verdict"]
        row = v["per_seed"]["11"]
        assert row["warm_reached"] is False
        assert row["cold_reached"] is True
        assert row["censored"] is True
        assert row["censored_arm"] == "warm"
        assert row["reduction_pct"] is None
        assert row["warm_trials_to_target"] == 6  # censored 按整预算保守计

    def test_small_reduction_below_threshold_fails(self):
        # cold 第 5 次达标、warm 第 4 次达标（target=冷臂末代 0.5）
        # → 缩减 20% < 30% → FAIL
        pairs = {
            "11": {"cold": [9.0, 7.0, 5.0, 1.0, 0.5],
                   "warm": [9.0, 7.0, 5.0, 0.5]},
        }
        v = judge_campaign(pairs, budget=10, threshold_pct=30.0)
        assert v["pass"] is False
        row = v["per_seed"]["11"]
        assert row["reduction_pct"] == 20.0
        assert "FAIL" in v["verdict"]
        assert "10.0" in v["verdict"]  # 差距：30 - 20 = 10 个百分点

    def test_threshold_param_respected(self):
        pairs = {
            "11": {"cold": [8.0, 6.0, 4.0, 2.0, 1.0, 0.5],  # 第 6 次达标
                   "warm": [1.0, 1.0, 1.0, 0.5]},            # 第 4 次达标
        }
        # 缩减 (6-4)/6 ≈ 33.3%：阈值 30 → PASS；阈值 50 → FAIL
        v30 = judge_campaign(pairs, budget=10, threshold_pct=30.0)
        v50 = judge_campaign(pairs, budget=10, threshold_pct=50.0)
        assert v30["pass"] is True
        assert v50["pass"] is False
        assert v50["mean_reduction_pct"] == pytest.approx(33.3, abs=0.1)

    def test_warm_censored_when_cold_is_better_fails(self):
        # target = 冷臂末代 = 8.0：冷臂第 2 次即到，热臂整预算未到
        # → censored 剔除、n_censored=1 透出（语义变化：旧口径按
        # reduction=-150% 计入均值后 FAIL，新口径无均值样本直接 FAIL）
        pairs = {
            "11": {"cold": [9.0, 8.0], "warm": [8.5, 8.4]},
        }
        v = judge_campaign(pairs, budget=5, threshold_pct=30.0)
        assert v["pass"] is False
        assert v["n_seeds"] == 0
        assert v["n_censored"] == 1
        row = v["per_seed"]["11"]
        assert row["cold_trials_to_target"] == 2
        assert row["warm_trials_to_target"] == 5
        assert row["cold_reached"] is True
        assert row["warm_reached"] is False
        assert row["reduction_pct"] is None


class TestJudgeCampaignEdge:
    def test_empty_trajectory_seed_skipped_not_crash(self):
        pairs = {
            "11": {"cold": [], "warm": [1.0]},
            "22": {"cold": [2.0, 1.0, 0.5], "warm": [0.5]},
        }
        v = judge_campaign(pairs, budget=5)
        assert v["n_seeds"] == 1
        assert any("seed=11" in e for e in v["errors"])
        assert v["per_seed"].get("11") is None

    def test_all_seeds_invalid(self):
        v = judge_campaign({"11": {"cold": [], "warm": []}}, budget=5)
        assert v["pass"] is False
        assert "无有效配对种子" in v["verdict"]

    def test_none_cost_entries_count_as_failed_trials(self):
        # 失败 trial（None 占位）不更新累计 best，但占真评估序数
        pairs = {
            "11": {"cold": [None, 1.0, 0.5], "warm": [0.5]},
        }
        v = judge_campaign(pairs, budget=10)
        row = v["per_seed"]["11"]
        assert row["cold_trials_to_target"] == 3  # None 占位后第 3 次才累计到达
        assert row["warm_trials_to_target"] == 1


class TestJudgeCampaignPriorTarget:
    """target 偏置修复回归（e11-campaign 复盘：旧口径 min(双臂末代 best)）。"""

    def test_final_quality_edge_no_longer_synthesizes_reduction(self):
        # 实证反例：warm 末代 0.59 略优于 cold 末代 0.60，但 warm 每个前缀
        # 都不优于 cold。旧口径 target=min(末代)=0.59 → 冷臂整预算 censored、
        # 合成"次数缩减"可 PASS；新口径 target=冷臂末代 0.60，warm 第 10 次
        # 才达标 → 缩减率为负，如实 FAIL
        pairs = {
            "11": {"cold": [2.0, 1.0, 0.60, 0.60, 0.60],
                   "warm": [2.0, 1.5, 1.2, 1.0, 0.9,
                            0.8, 0.7, 0.65, 0.62, 0.59]},
        }
        v = judge_campaign(pairs, budget=10, threshold_pct=30.0)
        assert v["pass"] is False
        row = v["per_seed"]["11"]
        assert row["target_cost"] == pytest.approx(0.60)
        assert row["cold_trials_to_target"] == 3
        assert row["warm_trials_to_target"] == 10
        assert row["reduction_pct"] == pytest.approx(-233.33, abs=0.01)
        assert v["mean_reduction_pct"] == pytest.approx(-233.33, abs=0.01)

    def test_explicit_target_fixed_across_seeds(self):
        # 调用方显式传 target：全战役统一先验值，不再从轨迹反推
        pairs = {
            "11": {"cold": [9.0, 1.0], "warm": [1.0]},
            "22": {"cold": [5.0, 2.0, 1.0], "warm": [2.0, 1.0]},
        }
        v = judge_campaign(pairs, budget=5, threshold_pct=30.0, target=1.0)
        assert v["per_seed"]["11"]["target_cost"] == 1.0
        assert v["per_seed"]["22"]["target_cost"] == 1.0
        # seed 11: 冷第 2 次达 1.0，热第 1 次 → 缩减 50%
        assert v["per_seed"]["11"]["reduction_pct"] == 50.0
        # seed 22: 冷第 3 次达 1.0，热第 2 次（2.0 > 1.0，第 2 次 1.0 达标）
        # → 缩减 (3-2)/3 ≈ 33.33%
        assert v["per_seed"]["22"]["reduction_pct"] == pytest.approx(33.33, abs=0.01)
        assert v["pass"] is True
        assert v["n_censored"] == 0

    def test_explicit_target_censors_cold_arm(self):
        # 显式 target 高于冷臂末代：冷臂也可能 censored（对称语义）
        pairs = {"11": {"cold": [9.0, 2.0], "warm": [1.0, 1.0]}}
        v = judge_campaign(pairs, budget=5, target=1.0)
        assert v["n_seeds"] == 0
        assert v["n_censored"] == 1
        row = v["per_seed"]["11"]
        assert row["censored_arm"] == "cold"
        assert row["cold_reached"] is False
        assert row["warm_reached"] is True

    def test_all_failed_cold_arm_skipped_with_error(self):
        # 冷臂全失败（末代=inf）：无先验 target 可定，跳过并报 error
        pairs = {"11": {"cold": [None, None], "warm": [1.0]}}
        v = judge_campaign(pairs, budget=5)
        assert v["n_seeds"] == 0
        assert v["n_censored"] == 0
        assert any("seed=11" in e for e in v["errors"])
        assert v["per_seed"] == {}

    def test_real_campaign_verdict_shape_regression(self):
        # 真实战役 verdict 文件（归档不入库）实录形状：
        # target=0（fake wilkinson 平底碗）双臂均达——新口径下 target 仍为
        # 冷臂末代 0.0，结论不变（3 种子 PASS，均值 95.49%）
        pairs = {
            "11": {"cold": [None] * 15 + [0.0] * 15, "warm": [0.0] * 30},
            "22": {"cold": [None] * 28 + [0.0] * 2, "warm": [0.0] * 30},
            "33": {"cold": [None] * 25 + [0.0] * 5, "warm": [0.0] * 30},
        }
        v = judge_campaign(pairs, budget=30, threshold_pct=30.0)
        assert v["pass"] is True
        assert v["n_seeds"] == 3
        assert v["n_censored"] == 0
        assert v["mean_reduction_pct"] == pytest.approx(95.49, abs=0.01)
        # 逐种子实录数字：16/29/26 次达标 vs warm 先验 1 次
        assert v["per_seed"]["11"]["cold_trials_to_target"] == 16
        assert v["per_seed"]["22"]["cold_trials_to_target"] == 29
        assert v["per_seed"]["33"]["cold_trials_to_target"] == 26
        for row in v["per_seed"].values():
            assert row["warm_trials_to_target"] == 1
            assert row["target_cost"] == 0.0
            assert row["reduction_pct"] is not None


class TestBuildHistorySamples:
    """历史集上界剔除（历史集含最优点 → 缩减率是构造上界）。

    断言口径：全量集 − 构造集 = 恰为上界点（cost ≤ target+ε），差集互斥、
    溯源字段原样保留、统计可追溯。
    """

    @staticmethod
    def _sample(cost, idx: int) -> dict:
        return {"params": {"w": idx}, "cost": cost, "run_id": "h1", "point_index": idx}

    def test_difference_assertion_only_upper_bound_points_removed(self):
        # 全量集 → 构造集做差：被剔除的恰为上界点（含最优点 0.0）
        full = [self._sample(c, i) for i, c in enumerate([5.0, 3.0, 1.0, 0.0])]
        kept, stats = build_history_samples(full, target=0.5)
        assert [s["cost"] for s in kept] == [5.0, 3.0, 1.0]
        removed = [full[i] for i in stats["removed_indices"]]
        assert [s["cost"] for s in removed] == [0.0]
        # 差集互斥：被剔除点不在构造集内（对象同一性），且剔除+保留=全量
        assert not ({id(s) for s in removed} & {id(s) for s in kept})
        assert len(removed) + len(kept) == len(full)

    def test_tied_optima_all_removed(self):
        # 多个并列最优点（fake 平底碗 #207 形态）全部剔除
        full = [self._sample(c, i) for i, c in enumerate([0.0, 2.0, 0.0])]
        kept, stats = build_history_samples(full, target=0.0)
        assert [s["cost"] for s in kept] == [2.0]
        assert stats["n_removed"] == 2
        assert stats["removed_indices"] == [0, 2]

    def test_cost_equal_to_target_is_removed(self):
        # cost == target 也是目标点：注入即命中 target+ε（首 trial 平推达标）
        full = [self._sample(c, i) for i, c in enumerate([2.0, 1.0, 0.5])]
        kept, stats = build_history_samples(full, target=1.0)
        assert [s["cost"] for s in kept] == [2.0]
        assert stats["n_removed"] == 2

    def test_epsilon_boundary(self):
        # ε 内视同达标（与 trials_to_target 同口径）；ε 外保留
        full = [self._sample(1.0 + 1e-13, 0), self._sample(1.0 + 1e-3, 1)]
        kept, stats = build_history_samples(full, target=1.0)
        assert [s["cost"] for s in kept] == [pytest.approx(1.0 + 1e-3)]
        assert stats["n_removed"] == 1

    def test_empty_full_set(self):
        kept, stats = build_history_samples([], target=0.0)
        assert kept == []
        assert stats["n_total"] == 0
        assert stats["n_removed"] == 0
        assert stats["n_kept"] == 0

    def test_all_at_or_below_target_kept_empty(self):
        # 全量集整体不高于 target → 构造集为空（战役层须如实跳过，不静默降级）
        full = [self._sample(0.0, i) for i in range(3)]
        kept, stats = build_history_samples(full, target=0.0)
        assert kept == []
        assert stats["n_removed"] == 3

    def test_stats_traceability_fields(self):
        full = [self._sample(c, i) for i, c in enumerate([3.0, 0.0, 1.0])]
        kept, stats = build_history_samples(full, target=0.0)
        assert stats["n_total"] == 3
        assert stats["n_removed"] == 1
        assert stats["n_kept"] == 2 == len(kept)
        assert stats["removal_threshold"] == 0.0
        assert stats["epsilon"] == 1e-12
        assert stats["removed_indices"] == [1]

    def test_sample_payload_preserved_by_identity(self):
        s = {"params": {"a": 1}, "cost": 5.0, "run_id": "r9", "point_index": 7}
        kept, _ = build_history_samples([s], target=1.0)
        assert kept[0] is s  # 原样保留：不复制、不改写（溯源字段不动）

    def test_nonfinite_or_missing_cost_kept_not_classified(self):
        # 非数值/非有限 cost 不参与剔除判定、原样保留（喂料面在源头拦截，
        # 纯函数不静默丢数据）；bool 视为非数值
        full = [
            {"params": {}, "cost": None, "run_id": "r", "point_index": 0},
            {"params": {}, "cost": float("nan"), "run_id": "r", "point_index": 1},
            {"params": {}, "cost": True, "run_id": "r", "point_index": 2},
            {"params": {}, "cost": 0.0, "run_id": "r", "point_index": 3},
        ]
        kept, stats = build_history_samples(full, target=5.0)
        assert stats["n_removed"] == 1
        assert stats["removed_indices"] == [3]
        assert [s["point_index"] for s in kept] == [0, 1, 2]


class TestRunCampaignWiring:
    """战役编排接线（monkeypatch 假通道，零真机零 optuna 真跑）。

    钉死两件事：verdict.channel 通道口径（配对来源可追溯）+ warm 臂
    注入先验不含上界点（构造逻辑真接线，非仅纯函数）。#144：workdir 落
    tmp_path 沙箱（run_campaign 自带 chdir+还原），RFAUTO_CACHE 经
    monkeypatch.setenv 保还原；#139：run_optimization/materialize/collect/
    study_trajectory 四通道全部钉住。
    """

    @staticmethod
    def _write_recipe(tmp_path: Path) -> Path:
        p = tmp_path / "recipe_src.yaml"
        p.write_text("setup:\n  points: 3\n", encoding="utf-8")
        return p

    @staticmethod
    def _patch_fake_channels(monkeypatch, calls, cold_costs, warm_costs, dataset_samples):
        import e11_warm_start_campaign as camp
        import rfauto.optimization.optimizer as opt_mod
        import rfauto.service.dataset_service as ds_mod
        import rfauto.service.warm_start_data as wsd_mod

        traj: dict[str, list] = {}

        def fake_run_optimization(recipe_path, adapter_name="fake", max_trials=60,
                                  study_name=None, sampler="tpe", adapter_kwargs=None,
                                  warm_start=None, **kw):
            calls.append({
                "study_name": study_name,
                "adapter_name": adapter_name,
                "max_trials": max_trials,
                "warm_start": warm_start,
            })
            if study_name and "_cold_" in study_name:
                traj[study_name] = list(cold_costs)
            elif study_name and "_warm_" in study_name:
                traj[study_name] = list(warm_costs)
            return {"ok": True, "run_id": f"run-{study_name}", "study_name": study_name,
                    "warm_start_n": len(warm_start or [])}

        def fake_study_trajectory(study_name, storage_url=None):
            return list(traj.get(study_name, []))

        monkeypatch.setattr(opt_mod, "run_optimization", fake_run_optimization)
        monkeypatch.setattr(
            ds_mod, "materialize_dataset",
            lambda run_ids=None, *, name, **kw: {"ok": True, "name": name,
                                                 "n_rows": len(dataset_samples)})
        monkeypatch.setattr(
            wsd_mod, "collect_warm_start_samples",
            lambda dataset, **kw: {"ok": True, "dataset": str(dataset),
                                   "samples": [dict(s) for s in dataset_samples],
                                   "n_rows_scanned": len(dataset_samples)})
        monkeypatch.setattr(camp, "study_trajectory", fake_study_trajectory)

    def test_channel_field_and_upper_bound_excluded_from_warm_injection(
            self, tmp_path, monkeypatch):
        calls: list[dict] = []
        # 历史集含最优点 0.0 与 target 之下点 0.4（实证的构造上界形态）
        dataset_samples = [
            {"params": {"w": 1}, "cost": 0.0, "run_id": "h1", "point_index": 0},
            {"params": {"w": 2}, "cost": 0.4, "run_id": "h1", "point_index": 1},
            {"params": {"w": 3}, "cost": 0.6, "run_id": "h1", "point_index": 2},
        ]
        self._patch_fake_channels(
            monkeypatch, calls,
            cold_costs=[1.0, 0.5],  # 冷臂末代 best=0.5 → 判据 target=剔除阈值=0.5
            warm_costs=[0.45, 0.5],
            dataset_samples=dataset_samples)
        monkeypatch.setenv("RFAUTO_CACHE", "off")  # run_campaign 内部再设；monkeypatch 保还原
        v = run_campaign(tmp_path / "camp", self._write_recipe(tmp_path),
                         seeds=[11], budget=5, history_seeds=[101], tag="t1")
        # ① channel 字段：顶层 + meta 双臂通道（配对来源可追溯）
        assert v["channel"] == "fake"
        assert v["meta"]["channel"] == "fake"
        assert v["meta"]["channels"] == {"cold": "fake", "warm": "fake"}
        # ② 注入先验差集断言：cost ≤ target(0.5) 的 0.0/0.4 被剔除，只余 0.6
        warm_calls = [c for c in calls if c["study_name"] and "_warm_" in c["study_name"]]
        cold_calls = [c for c in calls if c["study_name"] and "_cold_" in c["study_name"]]
        assert len(warm_calls) == 1
        assert len(cold_calls) == 1
        assert cold_calls[0]["warm_start"] is None  # 冷臂无注入
        assert [s["cost"] for s in warm_calls[0]["warm_start"]] == [0.6]
        # ③ 剔除统计透出（可追溯）+ 判据 target 与剔除阈值同款
        hf = v["meta"]["history_filter"]
        assert hf["n_full_samples"] == 3
        assert hf["per_seed"]["11"]["n_removed"] == 2
        assert hf["per_seed"]["11"]["removal_threshold"] == 0.5
        assert v["per_seed"]["11"]["target_cost"] == 0.5
        # verdict 落盘且含 channel
        on_disk = json.loads((tmp_path / "camp" / "campaign_verdict.json").read_text(encoding="utf-8"))
        assert on_disk["channel"] == "fake"

    def test_empty_constructed_history_skips_warm_honestly(self, tmp_path, monkeypatch):
        # 全部历史样本 ≤ 冷臂末代 target → 构造集为空 → 该种子如实跳过，
        # warm 臂不被调用（不静默降级冷启动）
        calls: list[dict] = []
        dataset_samples = [
            {"params": {"w": 1}, "cost": 0.0, "run_id": "h1", "point_index": 0},
            {"params": {"w": 2}, "cost": 0.05, "run_id": "h1", "point_index": 1},
        ]
        self._patch_fake_channels(
            monkeypatch, calls,
            cold_costs=[0.1, 0.05],  # 冷臂末代 best=0.05 → target=0.05
            warm_costs=[0.05],
            dataset_samples=dataset_samples)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        v = run_campaign(tmp_path / "camp", self._write_recipe(tmp_path),
                         seeds=[11], budget=5, history_seeds=[101], tag="t2")
        assert v["pass"] is False
        assert v["channel"] == "fake"
        assert any("历史集为空" in e for e in v["errors"])
        assert v["meta"]["history_filter"]["per_seed"]["11"]["n_removed"] == 2
        assert not [c for c in calls if c["study_name"] and "_warm_" in c["study_name"]]

    def test_channel_follows_adapter_name(self, tmp_path, monkeypatch):
        calls: list[dict] = []
        dataset_samples = [
            {"params": {"w": 1}, "cost": 0.7, "run_id": "h1", "point_index": 0},
        ]
        self._patch_fake_channels(
            monkeypatch, calls, cold_costs=[1.0, 0.5], warm_costs=[0.4],
            dataset_samples=dataset_samples)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        v = run_campaign(tmp_path / "camp", self._write_recipe(tmp_path),
                         seeds=[11], budget=5, history_seeds=[101],
                         tag="t3", adapter_name="openems")
        assert v["channel"] == "openems"
        assert v["meta"]["channels"] == {"cold": "openems", "warm": "openems"}
        # 造史/冷/热三类 run 全部走同一通道
        assert calls and all(c["adapter_name"] == "openems" for c in calls)

    def test_explicit_target_used_for_both_judge_and_filter(self, tmp_path, monkeypatch):
        # 显式 target：判据与剔除阈值同为 target（不再从冷臂末代反推）
        calls: list[dict] = []
        dataset_samples = [
            {"params": {"w": 1}, "cost": 0.2, "run_id": "h1", "point_index": 0},
            {"params": {"w": 2}, "cost": 0.9, "run_id": "h1", "point_index": 1},
        ]
        self._patch_fake_channels(
            monkeypatch, calls, cold_costs=[1.0, 0.1], warm_costs=[0.3],
            dataset_samples=dataset_samples)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        v = run_campaign(tmp_path / "camp", self._write_recipe(tmp_path),
                         seeds=[11], budget=5, history_seeds=[101],
                         tag="t4", target=0.3)
        warm_calls = [c for c in calls if c["study_name"] and "_warm_" in c["study_name"]]
        assert [s["cost"] for s in warm_calls[0]["warm_start"]] == [0.9]
        assert v["meta"]["target"] == 0.3
        assert v["meta"]["history_filter"]["per_seed"]["11"]["removal_threshold"] == 0.3
        assert v["per_seed"]["11"]["target_cost"] == 0.3
