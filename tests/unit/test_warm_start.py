"""E11 warm-start 单元测试——相似度门 + Optuna 注入 + run_optimization 集成。

覆盖：
- warm_start_points：相似度门两态（同族键通过 / 异族键与越界值拒绝）、
  top_n cost 升序、界外裁剪、缺 cost/空历史拒绝
- enqueue_warm_start：真 optuna 内存 study，#123 口径（enqueue_trial 返回
  None，回查 WAITING trial 集合）、WAITING trial 先跑且 params 精确等于注入值
- run_optimization(warm_start=...)：fake 配方集成——result["warm_start_n"]
  ≥1、注入 trial 先跑、异族历史点被门拒绝降级冷启动
- warm_start=None 回归：结果键与 E10 基线一致（无 warm_start_n 键）

fake 响应标定同 test_constraint_optimization.py（FakeAdapter wilkinson
3 端口，band [2.3, 2.5]，arm_len/series_w 两参数搜索空间）。
"""

import sys
from pathlib import Path

import optuna
import pytest
import yaml
from optuna.trial import TrialState

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization import optimizer as opt_mod
from rfauto.optimization.optimizer import run_optimization
from rfauto.optimization.warm_start import enqueue_warm_start, warm_start_points

optuna.logging.set_verbosity(optuna.logging.WARNING)

# 与 optimizer.extract_param_ranges 口径一致的参数空间（wilkinson 两参数）
BOUNDS = {
    "arm_len_mm": {"low": 18.0, "high": 23.0},
    "series_w_mm": {"low": 0.25, "high": 0.45},
}


@pytest.fixture(autouse=True)
def _clean_optuna_db(tmp_path, monkeypatch):
    """每个测试用临时 SQLite storage + chdir（同 test_constraint_optimization.py）。

    chdir 隔离必须：run_optimization 往 cwd 的 runs/ 写产物，不得污染真实
    runs/（#144）。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    yield


def _write_recipe(tmp_path: Path, name: str = "ws.yaml") -> str:
    """wilkinson fake 配方（同 test_constraint_optimization.py 基线，无约束）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within", "value": [-3.6, -3.1]},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _load_study(result: dict) -> optuna.Study:
    return optuna.load_study(
        study_name=result["study_name"],
        storage=opt_mod.get_storage_path(),
    )


# ─── 相似度门（warm_start_points） ───────────────────────────────────────────

class TestSimilarityGate:
    """相似度门两态：同族键通过 / 异族键与越界值拒绝（负迁移防线）。"""

    def test_same_family_keys_pass(self):
        """参数键与 bounds 键全同（Jaccard=1.0）、值全落界 → 通过。"""
        pts = [{"params": {"arm_len_mm": 19.0, "series_w_mm": 0.30}, "cost": 1.0}]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is True
        assert res["n_candidates"] == 1
        assert res["n_rejected"] == 0
        assert res["points"] == [
            {"params": {"arm_len_mm": 19.0, "series_w_mm": 0.30}, "cost": 1.0},
        ]

    def test_partial_key_overlap_passes(self):
        """Jaccard=2/3 ≥ 0.5 且落界率 1.0 → 通过（重叠率门限语义）。"""
        pts = [{
            "params": {"arm_len_mm": 19.0, "series_w_mm": 0.30, "extra_key": 7.0},
            "cost": 0.8,
        }]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is True

    def test_alien_keys_rejected(self):
        """异族键（与 bounds 零交集）→ ok=False + insufficient_similarity。"""
        pts = [{"params": {"w_mm": 1.0, "l_mm": 2.0}, "cost": 0.001}]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is False
        assert res["reason"] == "insufficient_similarity"
        assert res["n_candidates"] == 1
        assert res["n_rejected"] == 1
        assert "points" not in res

    def test_low_jaccard_rejected_even_if_in_bounds(self):
        """Jaccard=1/3 < 0.5：即使交集值在界内也拒绝（键空间不同族）。"""
        pts = [{"params": {"arm_len_mm": 19.0, "e1": 1.0, "e2": 2.0}, "cost": 0.5}]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is False

    def test_out_of_bounds_values_rejected(self):
        """键全同但值全部越界（落界率 0 < 0.5）→ 拒绝（量级不同族）。"""
        pts = [{"params": {"arm_len_mm": 100.0, "series_w_mm": 9.0}, "cost": 0.001}]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is False
        assert res["reason"] == "insufficient_similarity"

    def test_boundary_rate_exactly_half_passes(self):
        """落界率恰为 0.5（两键一出一入）→ ≥0.5 通过（门限含边界）。"""
        pts = [{"params": {"arm_len_mm": 100.0, "series_w_mm": 0.30}, "cost": 2.0}]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is True
        assert res["points"][0]["params"]["arm_len_mm"] == 23.0  # 裁剪到上界


class TestTopNAndClip:
    """top_n 排序 + 界外裁剪。"""

    def test_sorted_by_cost_and_clipped(self):
        pts = [
            {"params": {"arm_len_mm": 30.0, "series_w_mm": 0.30}, "cost": 3.0},  # 越上界
            {"params": {"arm_len_mm": 19.0, "series_w_mm": 0.30}, "cost": 1.0},
            {"params": {"arm_len_mm": 10.0, "series_w_mm": 0.32}, "cost": 2.0},  # 越下界
            {"params": {"arm_len_mm": 21.0, "series_w_mm": 0.33}, "cost": 4.0},
        ]
        res = warm_start_points(pts, bounds=BOUNDS, top_n=3)
        assert res["ok"] is True
        assert res["n_candidates"] == 4
        assert res["n_rejected"] == 0
        top = res["points"]
        assert len(top) == 3
        # cost 升序：1.0 → 2.0 → 3.0
        assert [p["cost"] for p in top] == [1.0, 2.0, 3.0]
        # 界内原值保留
        assert top[0]["params"]["arm_len_mm"] == 19.0
        # 界外裁剪到界内（Optuna fixed_params 越界会使建议阶段报错）
        assert top[1]["params"]["arm_len_mm"] == 18.0
        assert top[2]["params"]["arm_len_mm"] == 23.0

    def test_top_n_limits_output(self):
        pts = [
            {"params": {"arm_len_mm": 19.0 + i, "series_w_mm": 0.30}, "cost": float(i)}
            for i in range(5)
        ]
        res = warm_start_points(pts, bounds=BOUNDS, top_n=2)
        assert res["ok"] is True
        assert len(res["points"]) == 2
        assert [p["cost"] for p in res["points"]] == [0.0, 1.0]

    def test_missing_cost_rejected(self):
        """无 cost 的点无法参与"最优先注入"排序 → 计拒绝。"""
        pts = [
            {"params": {"arm_len_mm": 19.0, "series_w_mm": 0.30}},  # 缺 cost
            {"params": {"arm_len_mm": 20.0, "series_w_mm": 0.31}, "cost": 1.0},
        ]
        res = warm_start_points(pts, bounds=BOUNDS)
        assert res["ok"] is True
        assert res["n_rejected"] == 1
        assert len(res["points"]) == 1

    def test_empty_history_rejected(self):
        res = warm_start_points([], bounds=BOUNDS)
        assert res["ok"] is False
        assert res["reason"] == "insufficient_similarity"
        assert res["n_candidates"] == 0


# ─── Optuna 注入（enqueue_warm_start，#123 回查口径） ────────────────────────

class TestEnqueueWarmStart:
    def test_enqueue_returns_new_waiting_numbers(self):
        """注入后回查 WAITING 差集得 trial 号（不依赖 enqueue_trial 返回值，
        #123：该返回值随版本可能是 None）。"""
        study = optuna.create_study(
            study_name="ws_enq", storage="sqlite:///:memory:", direction="minimize")
        numbers = enqueue_warm_start(study, [
            {"params": {"a": 1.0}, "cost": 1.0},
            {"params": {"a": 2.0}, "cost": 0.5},
        ])
        assert numbers == [0, 1]
        waiting = study.get_trials(deepcopy=False, states=(TrialState.WAITING,))
        assert [t.system_attrs["fixed_params"] for t in waiting] == [
            {"a": 1.0}, {"a": 2.0}]

    def test_waiting_trials_run_first_with_exact_params(self):
        """WAITING trial 在 optimize 中先被弹出执行，params 精确等于注入值。"""
        study = optuna.create_study(
            study_name="ws_first", storage="sqlite:///:memory:", direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=42))
        enqueue_warm_start(study, [{"params": {"x": 0.25}, "cost": 0.0}])
        study.optimize(
            lambda t: t.suggest_float("x", 0.0, 1.0), n_trials=3)
        trials = study.get_trials(deepcopy=False)
        assert all(t.state == TrialState.COMPLETE for t in trials)
        assert trials[0].params["x"] == 0.25  # 注入点先跑

    def test_injection_into_study_with_existing_trials(self):
        """已有 trial 的 study 注入：差集口径只报新注入号。"""
        study = optuna.create_study(
            study_name="ws_exist", storage="sqlite:///:memory:", direction="minimize")
        study.optimize(lambda t: t.suggest_float("x", 0.0, 1.0), n_trials=2)
        numbers = enqueue_warm_start(study, [{"params": {"x": 0.75}, "cost": 0.1}])
        assert numbers == [2]


# ─── run_optimization 集成（fake 配方） ──────────────────────────────────────

class TestRunOptimizationWarmStart:
    def test_injected_points_run_first(self, tmp_path):
        """门通过 → 注入 trial 先跑、warm_start_n 回显注入数、
        study 里出现注入 params 的 trial。"""
        recipe = _write_recipe(tmp_path)
        warm = [
            {"params": {"arm_len_mm": 19.5, "series_w_mm": 0.35}, "cost": 0.05},
            {"params": {"arm_len_mm": 22.5, "series_w_mm": 0.40}, "cost": 0.50},
            # 异族键点：门应拒绝（负迁移防线），不影响其余点注入
            {"params": {"l_mm": 1.0, "w_mm": 2.0}, "cost": 0.001},
        ]
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=6,
            study_name="e11_ws", adapter_kwargs={"n_ports": 3},
            warm_start=warm,
        )
        assert result["ok"]
        assert result["warm_start_n"] == 2  # 异族点被门拒，同族 2 点注入
        assert result["trials_completed"] == 6

        study = _load_study(result)
        trials = study.get_trials(deepcopy=False)
        completed = [t for t in trials if t.state == TrialState.COMPLETE]
        assert len(completed) == 6
        # 注入点先跑：trial 0/1 的 params 即 cost 升序的注入值
        assert completed[0].params == {"arm_len_mm": 19.5, "series_w_mm": 0.35}
        assert completed[1].params == {"arm_len_mm": 22.5, "series_w_mm": 0.40}

    def test_gate_rejected_falls_back_to_cold_start(self, tmp_path):
        """全异族历史点 → 门拒绝如实降级冷启动：warm_start_n=0、
        优化正常跑完、无注入 trial。"""
        recipe = _write_recipe(tmp_path)
        warm = [{"params": {"l_mm": 1.0, "w_mm": 2.0}, "cost": 0.001}]
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=3,
            study_name="e11_reject", adapter_kwargs={"n_ports": 3},
            warm_start=warm,
        )
        assert result["ok"]
        assert result["warm_start_n"] == 0
        assert result["trials_completed"] == 3
        study = _load_study(result)
        waiting = study.get_trials(deepcopy=False, states=(TrialState.WAITING,))
        assert waiting == []

    def test_out_of_bounds_history_clipped_into_search_space(self, tmp_path):
        """历史点界外值裁剪到新战役搜索空间内再注入（trial 可正常评估）。"""
        recipe = _write_recipe(tmp_path)
        warm = [{"params": {"arm_len_mm": 99.0, "series_w_mm": 0.30}, "cost": 0.1}]
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=2,
            study_name="e11_clip", adapter_kwargs={"n_ports": 3},
            warm_start=warm,
        )
        assert result["ok"]
        assert result["warm_start_n"] == 1
        study = _load_study(result)
        trials = study.get_trials(deepcopy=False)
        # 裁剪后注入值=上界 23.0，trial 正常完成无越界报错
        assert trials[0].state == TrialState.COMPLETE
        assert trials[0].params["arm_len_mm"] == 23.0
        assert trials[0].params["series_w_mm"] == 0.30

    def test_empty_warm_start_list_reports_zero(self, tmp_path):
        """显式传空列表：与 None 区分（is not None 语义），warm_start_n=0。"""
        recipe = _write_recipe(tmp_path)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=2,
            study_name="e11_empty", adapter_kwargs={"n_ports": 3},
            warm_start=[],
        )
        assert result["ok"]
        assert result["warm_start_n"] == 0


class TestWarmStartNoneRegression:
    """warm_start=None 回归：行为不变，结果无 warm_start_n 键。"""

    def test_result_keys_unchanged(self, tmp_path):
        recipe = _write_recipe(tmp_path)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=4,
            study_name="e11_none", adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["trials_completed"] == 4
        assert result["best_cost"] is not None
        assert "warm_start_n" not in result
        # 关键结果键与 E10 基线一致
        expected_keys = {
            "ok", "run_id", "run_dir", "study_name", "sampler", "storage",
            "elapsed_s", "max_trials", "trials_total", "trials_completed",
            "trials_pruned", "existing_trials", "max_trials_effective",
            "quota", "best_params", "best_cost", "best_metrics",
        }
        assert expected_keys <= set(result)

    def test_none_adds_no_waiting_trials(self, tmp_path):
        recipe = _write_recipe(tmp_path)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=2,
            study_name="e11_none2", adapter_kwargs={"n_ports": 3},
            warm_start=None,
        )
        assert result["ok"]
        study = _load_study(result)
        waiting = study.get_trials(deepcopy=False, states=(TrialState.WAITING,))
        assert waiting == []
