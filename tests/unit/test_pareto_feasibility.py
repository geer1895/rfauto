"""E9 hypervolume/约束 Pareto/热目标 + E10 可行性热图 单元测试（#18 optstack 收口）。

覆盖：
- pareto_tools 纯 numpy 内核：exact_hypervolume 手算值、与 mf_backend 私有
  别名同值；constrained_pareto_front 的 Deb 可行优先支配三律；hv_convergence
  统一 ref 逐代序列 + 弱单调判定；
- MultiObjBackend：hv_convergence 精英存档序列弱单调（§10.23「hypervolume
  单调」）；constraint_fn 通道（G≤0 同义）把前沿压进可行域；
- 热目标进 Pareto（E9⑤）：3 目标合成裁判（S11 违约 / T_max / 功率容量裕度）
  直接喂 objective_fn 出前沿，T_max 锚与 core/calculators.thermal_resistance_stack
  既有键一点对拍且前沿上非退化；
- run_multi_optimization（E9④）：optimization.constraints 消费——前沿逐点
  constraint_values/feasible、pareto_front.json 落盘；无约束配方不添约束键；
- ui_service.pareto_view 双源 / feasibility_heatmap 确定性分箱 + 无约束 run
  如实报错；ui/server 两只读路由薄壳。

全部离线零真机；数值只来自确定性内核（合成裁判系数为算法常数，不是物理数字）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization.pareto_tools import (
    constrained_pareto_front,
    constraint_dominates,
    default_reference_point,
    exact_hypervolume,
    hv_convergence,
    is_weakly_monotone,
    nondominated_indices,
)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """优化入口/服务会写 runs/，统一 chdir 隔离（#144）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


# ─── pareto_tools 内核 ────────────────────────────────────────────────────────

class TestExactHypervolume:
    def test_single_point_box(self):
        assert exact_hypervolume([(0.5, 0.5)], (1.0, 1.0)) == pytest.approx(0.25)

    def test_two_points_hand_computed(self):
        # y∈[0.25,0.5): 活跃 x≤0.75 → 0.25×0.25；y∈[0.5,1): x≤0.5 → 0.5×0.5
        hv = exact_hypervolume([(0.5, 0.5), (0.75, 0.25)], (1.0, 1.0))
        assert hv == pytest.approx(0.0625 + 0.25)

    def test_dominated_point_adds_nothing(self):
        base = exact_hypervolume([(0.5, 0.5)], (1.0, 1.0))
        assert exact_hypervolume([(0.5, 0.5), (0.8, 0.9)], (1.0, 1.0)) == pytest.approx(base)

    def test_point_outside_ref_is_zero(self):
        assert exact_hypervolume([(1.5, 0.2)], (1.0, 1.0)) == 0.0
        assert exact_hypervolume([], (1.0, 1.0)) == 0.0

    def test_one_dimensional_closed_form(self):
        assert exact_hypervolume([(0.3,), (0.7,)], (1.0,)) == pytest.approx(0.7)

    def test_three_dimensional_box(self):
        assert exact_hypervolume([(0.0, 0.0, 0.0)], (1.0, 2.0, 3.0)) == pytest.approx(6.0)

    def test_mf_backend_alias_is_same_kernel(self):
        """mf_backend._hv_exact_min 改为 pareto_tools 别名——31 测语义同源。"""
        from rfauto.optimization.mf_backend import _hv_exact_min

        pts = [(0.2, 0.9), (0.5, 0.5), (0.9, 0.1)]
        assert _hv_exact_min(pts, (1.0, 1.0)) == pytest.approx(
            exact_hypervolume(pts, (1.0, 1.0)))

    def test_default_reference_point_convention(self):
        ref = default_reference_point([[-30.0, 2.0], [-20.0, 5.0]])
        # 最差值 + max(1, 0.1·|最差|)：-20+2=-18；5+1=6
        assert ref == pytest.approx([-18.0, 6.0])


class TestConstrainedParetoFront:
    def test_unconstrained_equals_standard_nondominated(self):
        f = [[1.0, 5.0], [2.0, 2.0], [5.0, 1.0], [3.0, 3.0]]
        assert constrained_pareto_front(f) == nondominated_indices(f) == [0, 1, 2]
        assert constrained_pareto_front(f, [[], [], [], []]) == [0, 1, 2]

    def test_feasible_dominates_infeasible_even_if_worse_objectives(self):
        # 点 0 目标更好但违约；点 1 可行——Deb 律①：可行支配不可行
        f = [[0.0, 0.0], [5.0, 5.0]]
        v = [[0.3], [0.0]]
        assert constrained_pareto_front(f, v) == [1]

    def test_infeasible_ranked_by_total_violation(self):
        f = [[0.0, 0.0], [9.0, 9.0], [1.0, 1.0]]
        v = [[0.5, 0.5], [0.2, 0.0], [0.1, 0.05]]  # 总违约 1.0 / 0.2 / 0.15
        assert constrained_pareto_front(f, v) == [2]

    def test_equal_violation_falls_back_to_objective_dominance(self):
        f = [[1.0, 1.0], [2.0, 2.0], [0.5, 3.0]]
        v = [[0.4], [0.4], [0.4]]
        # 点 1 被点 0 支配；点 0/2 互不支配
        assert constrained_pareto_front(f, v) == [0, 2]

    def test_duplicates_both_kept(self):
        f = [[1.0, 1.0], [1.0, 1.0]]
        assert constrained_pareto_front(f, [[0.0], [0.0]]) == [0, 1]

    def test_row_mismatch_rejected(self):
        with pytest.raises(ValueError, match="行数"):
            constrained_pareto_front([[1.0, 2.0]], [[0.0], [0.0]])

    def test_constraint_dominates_truth_table(self):
        a, b = np.array([1.0, 1.0]), np.array([2.0, 2.0])
        assert constraint_dominates(a, 0.0, b, 0.5)       # 可行 vs 不可行
        assert not constraint_dominates(b, 0.5, a, 0.0)
        assert constraint_dominates(a, 0.0, b, 0.0)       # 两可行：标准支配
        assert constraint_dominates(b, 0.1, a, 0.3)       # 两不可行：违约小者
        assert not constraint_dominates(a, 0.3, b, 0.1)


class TestHvConvergence:
    def test_sequence_with_fixed_ref_and_monotone_check(self):
        fronts = [
            [[0.8, 0.8]],
            [[0.8, 0.8], [0.5, 0.9]],
            [[0.5, 0.5]],
        ]
        hv = hv_convergence(fronts, (1.0, 1.0))
        # 第 2 代：盒 [0.8,1]²（0.04）∪ 盒 [0.5,1]×[0.9,1]（0.05）− 重叠
        # [0.8,1]×[0.9,1]（0.02）= 0.07（独立手算，#118）
        assert hv == pytest.approx([0.04, 0.07, 0.25])
        assert is_weakly_monotone(hv)
        assert not is_weakly_monotone([0.3, 0.2])
        assert is_weakly_monotone([0.3, 0.3 - 1e-13])  # 浮点回退容忍

    def test_empty_front_is_zero(self):
        assert hv_convergence([[], [[0.5, 0.5]]], (1.0, 1.0)) == [0.0, 0.25]


# ─── MultiObjBackend：hv_convergence + 约束通道 ───────────────────────────────

class TestBackendHvAndConstraints:
    @staticmethod
    def _two_obj(x: np.ndarray) -> np.ndarray:
        # 一维凸前沿：f1=x², f2=(1−x)²（Schaffer 型，x∈[0,1] 全为 Pareto 最优）
        return np.array([x[0] ** 2, (1.0 - x[0]) ** 2])

    def test_hv_convergence_weakly_monotone(self):
        from rfauto.optimization.multiobj_backend import MultiObjBackend

        backend = MultiObjBackend(n_objectives=2, n_variables=1,
                                  bounds=(np.zeros(1), np.ones(1)))
        res = backend.optimize(self._two_obj, n_gen=8, pop_size=12, seed=3)
        assert res["ok"] and res["n_pareto"] >= 1
        hv = res["hv_convergence"]
        assert isinstance(hv, list) and len(hv) == 8
        assert all(math.isfinite(v) and v >= 0.0 for v in hv)
        assert is_weakly_monotone(hv), hv
        assert hv[-1] > 0.0

    def test_constraint_channel_confines_front(self):
        from rfauto.optimization.multiobj_backend import MultiObjBackend

        # 约束 x ≤ 0.6：违约量 = max(0, x−0.6)（≥0，0=可行边界，直接作 G）
        def con(x: np.ndarray) -> np.ndarray:
            return np.array([max(0.0, x[0] - 0.6)])

        backend = MultiObjBackend(n_objectives=2, n_variables=1,
                                  bounds=(np.zeros(1), np.ones(1)))
        res = backend.optimize(self._two_obj, n_gen=15, pop_size=16, seed=5,
                               constraint_fn=con, n_constraints=1)
        assert res["ok"] and res["n_pareto"] >= 1
        xs = [v[0] for v in res["pareto_variables"]]
        assert max(xs) <= 0.6 + 1e-9, xs
        assert "pareto_constraints" in res
        assert all(g[0] <= 1e-9 for g in res["pareto_constraints"])
        # 无约束对照：前沿延伸到 x>0.6（约束确有作用，不是搜索空间偶然）
        free = backend.optimize(self._two_obj, n_gen=15, pop_size=16, seed=5)
        assert max(v[0] for v in free["pareto_variables"]) > 0.6
        assert "pareto_constraints" not in free


# ─── 热目标进 Pareto（E9⑤）─────────────────────────────────────────────────────

class TestThermalObjectivesPareto:
    """3 目标合成裁判：x=(p_diss_W, theta_C_per_W) → [S11 违约, T_max, 功率容量裕度]。

    T_max = T_amb + θ·P 与 core/calculators.thermal_resistance_stack 的
    junction_temp_c 同式（既有注册键，一点对拍）；S11 违约/功率容量为合成
    单调面（算法常数）。三目标互相拉扯（P 大→S11 好、T 高、裕度差），
    前沿非退化。
    """

    T_AMB_C = 25.0
    P_CAP_W = 6.0

    @classmethod
    def judge(cls, x: np.ndarray) -> np.ndarray:
        p_w = 0.5 + 5.0 * float(x[0])          # 0.5…5.5 W
        theta = 5.0 + 35.0 * float(x[1])       # 5…40 °C/W
        s11_violation = max(0.0, 3.0 - p_w)    # 合成：功率越大匹配越好
        t_max = cls.T_AMB_C + theta * p_w      # 热阻链闭式（与计算器同式）
        capacity_use = p_w / cls.P_CAP_W       # 功率容量占用（越小越好）
        return np.array([s11_violation, t_max, capacity_use])

    def test_tmax_anchor_matches_thermal_resistance_stack(self):
        from rfauto.core.calculators import thermal_resistance_stack

        x = np.array([0.3, 0.5])  # p=2.0 W, θ=22.5 °C/W
        t_judge = float(self.judge(x)[1])
        ref = thermal_resistance_stack(power_w=2.0, ambient_c=self.T_AMB_C,
                                       theta_jc_c_per_w=22.5)
        assert t_judge == pytest.approx(ref["junction_temp_c"], abs=1e-9)
        assert ref["junction_temp_c"] == pytest.approx(70.0)

    def test_three_objective_front_nondegenerate(self):
        from rfauto.optimization.multiobj_backend import MultiObjBackend

        backend = MultiObjBackend(n_objectives=3, n_variables=2,
                                  bounds=(np.zeros(2), np.ones(2)))
        res = backend.optimize(self.judge, n_gen=10, pop_size=20, seed=11)
        assert res["ok"] and res["n_pareto"] >= 3
        front = np.asarray(res["pareto_front"])
        assert front.shape[1] == 3 and np.all(np.isfinite(front))
        # T_max 沿前沿非退化（不是常数陷阱，#195 同源判据）
        assert float(np.std(front[:, 1])) > 1.0
        # 前沿互不支配（内核自检）
        assert nondominated_indices(front.tolist()) == list(range(len(front)))
        hv = res["hv_convergence"]
        assert len(hv) == 10 and is_weakly_monotone(hv)


# ─── run_multi_optimization：约束消费 + pareto_front.json ─────────────────────

def _dual_recipe(tmp_path: Path, constraints: list[dict] | None) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm", "bounds": [15.0, 30.0]}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -20},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -3.0},
        ],
    }
    if constraints is not None:
        recipe["optimization"] = {"constraints": constraints}
    path = tmp_path / "recipe_dual.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestRunMultiOptimizationConstraints:
    # fake wilkinson：iso_s23_db_min_in_band 在 arm_len≈18-20.5mm 为 27.8-29.4dB，
    # ≳21.4mm 时 <27dB（test_constraint_optimization 标定）——min_above 28.0
    # 构成真实的部分可行域
    CONS: ClassVar[list[dict]] = [
        {"metric": "iso_s23_db", "band": [2.3, 2.5], "op": "min_above", "value": 28.0}]

    def test_constrained_front_records_violations_and_json(self, tmp_path):
        from rfauto.optimization.optimizer import run_multi_optimization

        res = run_multi_optimization(_dual_recipe(tmp_path, self.CONS),
                                     adapter_name="fake", n_gen=4, pop_size=8)
        assert res["ok"], res.get("errors")
        assert res["n_constraints"] == 1
        assert res["n_pareto"] == len(res["pareto_points"]) >= 1
        for pt in res["pareto_points"]:
            assert isinstance(pt["constraint_values"], list)
            assert len(pt["constraint_values"]) == 1
            assert pt["feasible"] == all(v <= 0.0 for v in pt["constraint_values"])
        # Deb 可行优先：只要存在可行个体，前沿不应留不可行点
        assert any(pt["feasible"] for pt in res["pareto_points"])
        assert all(pt["feasible"] for pt in res["pareto_points"])
        # 逐代超体积序列（best-effort 通道在 pymoo 0.6.2 可取）
        assert "hv_convergence" in res and len(res["hv_convergence"]) == 4
        assert is_weakly_monotone(res["hv_convergence"])
        doc = json.loads((Path(res["run_dir"]) / "results" / "pareto_front.json")
                         .read_text(encoding="utf-8"))
        assert doc["constraint_names"] == ["iso_s23_db"]
        assert doc["n_pareto"] == res["n_pareto"]
        assert doc["pareto_points"][0]["constraint_values"] is not None
        assert doc["hv_convergence"] == res["hv_convergence"]

    def test_unconstrained_recipe_shape_unchanged(self, tmp_path):
        from rfauto.optimization.optimizer import run_multi_optimization

        res = run_multi_optimization(_dual_recipe(tmp_path, None),
                                     adapter_name="fake", n_gen=2, pop_size=6)
        assert res["ok"], res.get("errors")
        assert "n_constraints" not in res
        for pt in res["pareto_points"]:
            assert set(pt) == {"params", "objectives"}
        front = Path(res["run_dir"]) / "results" / "pareto_front.json"
        assert front.is_file()
        doc = json.loads(front.read_text(encoding="utf-8"))
        assert "constraint_names" not in doc
        assert doc["objective_names"] == ["s11_db", "s21_db"]


# ─── E10 ui_service：pareto_view 双源 / feasibility_heatmap ─────────────────

def _write_trial_run(run_dir: Path, trials: list[dict], recipe: dict | None) -> None:
    (run_dir / "trials").mkdir(parents=True, exist_ok=True)
    for t in trials:
        (run_dir / "trials" / f"trial_{t['trial_number']}.json").write_text(
            json.dumps(t), encoding="utf-8")
    if recipe is not None:
        (run_dir / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump(recipe), encoding="utf-8")


_RECIPE_2OBJ = {
    "model": "wilkinson_power_divider",
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -20},
        {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -3.0},
    ],
    "optimization": {"constraints": [
        {"metric": "iso_s23_db", "band": [2.3, 2.5], "op": "min_above", "value": 28.0}]},
}


def _synthetic_trials() -> list[dict]:
    """4 条 trial：0 不可行但目标最好；1/2 可行互不支配；3 可行被 1 支配。"""
    def mk(n, a, b, s11, s21, cv):
        return {"trial_number": n, "params": {"a_mm": a, "b_mm": b},
                "metrics": {"s11_db_max_in_band": s11, "s21_db_mean_in_band": s21},
                "cost": max(0.0, s11 + 20.0) + max(0.0, -3.0 - s21),
                "constraint_values": cv}
    return [
        mk(0, 0.1, 0.1, -30.0, -1.0, [0.7]),   # 违约 0.7，目标向量 (0,0)
        mk(1, 0.4, 0.6, -18.0, -2.0, [0.0]),   # (2,0) 可行
        mk(2, 0.9, 0.2, -25.0, -4.0, [0.0]),   # (0,1) 可行
        mk(3, 0.6, 0.9, -15.0, -3.5, [0.0]),   # (5,0.5) 可行、被 1 支配
    ]


class TestParetoViewService:
    def test_recomputed_from_trials_with_constraints(self, tmp_path):
        from rfauto.service import ui_service

        run_dir = tmp_path / "runs" / "run_tpe"
        _write_trial_run(run_dir, _synthetic_trials(), _RECIPE_2OBJ)
        d = ui_service.pareto_view("run_tpe")
        assert d["ok"], d.get("errors")
        assert d["source"] == "trials_recomputed"
        assert d["objective_names"] == ["s11_db", "s21_db"]
        assert d["constraint_names"] == ["iso_s23_db"]
        assert d["param_names"] == ["a_mm", "b_mm"]
        got = sorted((p["params"]["a_mm"], p["params"]["b_mm"]) for p in d["points"])
        assert got == [(0.4, 0.6), (0.9, 0.2)]  # 不可行 0 与被支配 3 均剔除
        assert all(p["feasible"] for p in d["points"])
        assert d["points"][0]["objectives"].keys() == {"s11_db", "s21_db"}

    def test_reads_pareto_front_json_when_present(self, tmp_path):
        from rfauto.service import ui_service

        run_dir = tmp_path / "runs" / "run_nsga"
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "pareto_front.json").write_text(json.dumps({
            "objective_names": ["s11_db", "s21_db"], "param_names": ["arm_len_mm"],
            "n_pareto": 1, "hv_convergence": [0.1, 0.2],
            "pareto_points": [{"params": {"arm_len_mm": 20.0},
                               "objectives": {"s11_db": 0.0, "s21_db": 0.5}}],
        }), encoding="utf-8")
        d = ui_service.pareto_view("run_nsga")
        assert d["ok"] and d["source"] == "pareto_front.json"
        assert d["n_pareto"] == 1 and d["hv_convergence"] == [0.1, 0.2]
        assert d["points"][0]["params"] == {"arm_len_mm": 20.0}

    def test_missing_run_and_empty_run_are_explicit_errors(self, tmp_path):
        from rfauto.service import ui_service

        assert not ui_service.pareto_view("nope")["ok"]
        (tmp_path / "runs" / "empty").mkdir(parents=True)
        d = ui_service.pareto_view("empty")
        assert not d["ok"] and "不可算" in d["errors"][0]


class TestFeasibilityHeatmapService:
    def test_deterministic_binning(self, tmp_path):
        from rfauto.service import ui_service

        run_dir = tmp_path / "runs" / "run_c"
        _write_trial_run(run_dir, _synthetic_trials(), _RECIPE_2OBJ)
        d = ui_service.feasibility_heatmap("run_c", "a_mm", "b_mm", grid_n=2)
        assert d["ok"], d.get("errors")
        assert d["grid_n"] == 2
        assert d["x_edges"] == pytest.approx([0.1, 0.5, 0.9])
        assert d["y_edges"] == pytest.approx([0.1, 0.5, 0.9])
        assert d["n_trials_used"] == d["n_trials_total"] == 4
        assert d["n_feasible_total"] == 3
        cells = {(c["i"], c["j"]): c for c in d["cells"]}
        # a=0.1,b=0.1 → (0,0) 不可行；a=0.4,b=0.6 → (0,1) 可行；
        # a=0.9,b=0.2 → (1,0) 可行（右端点归末格）；a=0.6,b=0.9 → (1,1) 可行
        assert set(cells) == {(0, 0), (0, 1), (1, 0), (1, 1)}
        assert cells[(0, 0)]["feasible_rate"] == 0.0
        assert cells[(0, 0)]["mean_total_violation"] == pytest.approx(0.7)
        for key in ((0, 1), (1, 0), (1, 1)):
            assert cells[key]["n"] == 1 and cells[key]["feasible_rate"] == 1.0
        assert sum(c["n"] for c in d["cells"]) == 4

    def test_unconstrained_run_reported_honestly(self, tmp_path):
        from rfauto.service import ui_service

        trials = [{k: v for k, v in t.items() if k != "constraint_values"}
                  for t in _synthetic_trials()]
        run_dir = tmp_path / "runs" / "run_free"
        _write_trial_run(run_dir, trials, None)
        d = ui_service.feasibility_heatmap("run_free", "a_mm", "b_mm")
        assert not d["ok"]
        assert "constraint_values" in d["errors"][0]

    def test_bad_params_rejected(self, tmp_path):
        from rfauto.service import ui_service

        run_dir = tmp_path / "runs" / "run_c2"
        _write_trial_run(run_dir, _synthetic_trials(), None)
        assert not ui_service.feasibility_heatmap("run_c2", "a_mm", "a_mm")["ok"]
        assert not ui_service.feasibility_heatmap("run_c2", "a_mm", "zz")["ok"]
        assert not ui_service.feasibility_heatmap("missing", "a_mm", "b_mm")["ok"]


class TestOptStackRoutes:
    """ui/server 两只读路由薄壳（数据解释全在 ui_service）。"""

    @pytest.fixture()
    def client(self, tmp_path):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        _write_trial_run(tmp_path / "runs" / "run_c", _synthetic_trials(), _RECIPE_2OBJ)
        return TestClient(create_ui_app())

    def test_pareto_route(self, client):
        r = client.get("/api/runs/run_c/pareto").json()
        assert r["ok"] and r["source"] == "trials_recomputed" and r["n_pareto"] == 2

    def test_feasibility_route(self, client):
        r = client.get("/api/runs/run_c/feasibility",
                       params={"x_param": "a_mm", "y_param": "b_mm", "grid_n": 2}).json()
        assert r["ok"] and r["grid_n"] == 2 and sum(c["n"] for c in r["cells"]) == 4
        bad = client.get("/api/runs/run_c/feasibility",
                         params={"x_param": "a_mm", "y_param": "a_mm"}).json()
        assert not bad["ok"]

    def test_static_index_has_optstack_view(self):
        import rfauto.ui.server as server_mod

        static = Path(server_mod.__file__).parent / "static"
        html = (static / "index.html").read_text(encoding="utf-8")
        assert 'data-v="optstack"' in html and 'id="view-optstack"' in html
        js = (static / "pages.js").read_text(encoding="utf-8")
        assert "optstack: pageOptStack" in js
        assert "/feasibility" in js and "/pareto" in js
