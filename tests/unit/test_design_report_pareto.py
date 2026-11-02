"""§⑤b Pareto 前沿节钉子测试（aurora_p C1，2026-11-01）。

范围（席位任务书验收 A-F 映射）：

- A 手算锚（#300 家法：先过教科书/手算锚再采信）：5 trial 3 非支配合成
  fixture——前沿 [0,1,2]、ref=(9,7)、HV=2+12+7=21、knee=p1 距弦垂直距离
  3/√61；3D fixture HV=13（三维盒容斥 15−3+1）；全部与 pareto_tools
  输出逐位一致（单源逐位，零公式复制）；
- B provenance：``bare_number_fields(model)==[]``（含/不含 PNG 两形态）
  + 负例（剥 source 必非空）；
- C 三降级如实：单目标 run → ``na_single_objective``（md 显式
  ``single-objective run`` + ``N/A``，不空不炸）；目标键缺失 →
  ``unknown``（缺键≠违约量 0，#364-④ 家法）；trials<2 → 如实注记
  （单点前沿合法）；无 objectives 规格 / 全空 metrics → missing；
- D 单目标既有行为零变化：既有 design report 测试文件零改动独立全绿
  （本文件只做节形态复核：§①-⑥ 头部原样+⑤b 追加，⑥ 不重编号）；
- E PNG 确定性：两跑逐字节 + PNG 签名头 + with_diagrams=False 不落盘；
- 双源：源 A=nsga2 ``results/pareto_front.json`` 直读（hv_convergence
  摘要回显+弱单调自证）；源 B=trials 现算（约束 list/dict 双格式、
  可行优先支配、不可用回退无约束注记）。

全部离线确定性（#139 零网络；#144 tmp fixture 隔离，零 runs/ 污染）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization.pareto_tools import (
    default_reference_point,
    exact_hypervolume,
    knee_point_bending_angle,
    knee_point_hv_contribution,
    nondominated_indices,
)
from rfauto.service.design_replay_report import (
    build_design_report_model,
    generate_design_report,
    render_design_report_md,
)
from rfauto.service.report_render import bare_number_fields

# ── 手算锚 fixture（最小化口径，目标向量=逐目标违约量） ─────────────────────
# objectives 两条 max_below value=0.0 → 违约量=指标值本身（手算直读）。
# p0=(8,1) p1=(5,3) p2=(2,6) 非支配；p3=(6,5) 被 p1 支配；p4=(3,8) 被 p2 支配
# ref=(8+1, 6+1)=(9,7)；HV=2·1 + 3·4 + 1·7 = 21；knee=p1（|6·(−3)−(−5)·3|/√61）
_ANCHOR_POINTS = [(8.0, 1.0), (5.0, 3.0), (2.0, 6.0), (6.0, 5.0), (3.0, 8.0)]
_ANCHOR_PARAMS = [
    {"arm_len_mm": 20.0, "gap_mm": 0.30},
    {"arm_len_mm": 21.0, "gap_mm": 0.25},
    {"arm_len_mm": 22.0, "gap_mm": 0.20},
    {"arm_len_mm": 19.5, "gap_mm": 0.35},
    {"arm_len_mm": 23.0, "gap_mm": 0.15},
]


def _make_mo_run(tmp_path: Path,
                 points: list[tuple[float, ...]] | None = None,
                 *,
                 n_objectives: int = 2,
                 params: list[dict] | None = None,
                 metrics_override: dict[int, dict] | None = None,
                 costs: list[float | None] | None = None,
                 constraint_values: dict[int, list | dict] | None = None,
                 with_recipe: bool = True,
                 drop_objectives: bool = False) -> Path:
    """trials 现算源（源 B）最小 fixture：metrics 键=m1_db/m2_db/m3_db
    （裸指标名，max_below value=0 → 违约量=指标值）。"""
    pts = list(points if points is not None else _ANCHOR_POINTS)
    params = params if params is not None else _ANCHOR_PARAMS
    metrics_override = metrics_override or {}
    costs = costs if costs is not None else [sum(p) for p in pts]
    run = tmp_path / "run_mo"
    (run / "trials").mkdir(parents=True)
    for i, pt in enumerate(pts):
        if n_objectives == 2 and len(pt) == 2:
            metrics = {"m1_db": pt[0], "m2_db": pt[1]}
        else:
            metrics = {f"m{j + 1}_db": v for j, v in enumerate(pt)}
        if i in metrics_override:
            metrics = metrics_override[i]
        payload: dict = {"trial_number": i, "params": dict(params[i]),
                         "metrics": metrics, "cost": costs[i]}
        if constraint_values and i in constraint_values:
            payload["constraint_values"] = constraint_values[i]
        (run / "trials" / f"trial_{i}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
    if with_recipe:
        names = [f"m{j + 1}_db" for j in range(n_objectives)]
        recipe: dict = {
            "model": "synthetic_mo",
            "params": {"arm_len_mm": {"value": 20.0, "unit": "mm"}},
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 24.0}}},
            "objectives": [
                {"metric": n, "band": [2.3, 2.5], "op": "max_below",
                 "value": 0.0} for n in names],
        }
        if drop_objectives:
            recipe["objectives"] = []
        (run / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump(recipe, allow_unicode=True, sort_keys=True),
            encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": run.name, "model": "synthetic_mo", "adapter": "fake",
        "status": "done",
    }), encoding="utf-8")
    return run


def _make_nsga2_run(tmp_path: Path, *,
                    n_pareto: int | None = 3,
                    hv_convergence: list[float] | None = None) -> Path:
    """源 A fixture：results/pareto_front.json（optimizer E9 落盘同构形态）。"""
    run = tmp_path / "run_nsga2"
    (run / "results").mkdir(parents=True)
    names = ["s11_db", "s21_db"]
    doc: dict = {
        "run_id": "run_nsga2",
        "algorithm": "nsga2",
        "objective_names": names,
        "param_names": ["arm_len_mm"],
        "n_pareto": len(_ANCHOR_POINTS[:3]) if n_pareto is None else n_pareto,
        "n_evaluations": 36,
        "pareto_points": [
            {"params": {"arm_len_mm": 20.0 + i},
             "objectives": {"s11_db": pt[0], "s21_db": pt[1]}}
            for i, pt in enumerate(_ANCHOR_POINTS[:3])
        ],
    }
    if hv_convergence is not None:
        doc["hv_convergence"] = hv_convergence
    (run / "results" / "pareto_front.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": "run_nsga2", "algorithm": "nsga2", "status": "done",
        "n_pareto": doc["n_pareto"],
    }), encoding="utf-8")
    return run


def _pareto_of(model: dict) -> dict:
    return model["pareto"]


# ── A 手算锚（#300 家法：合成已知量回收；单源逐位） ─────────────────────────


class TestHandAnchor:
    def test_front_hv_ref_knee_hand_and_single_source(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok" and p["kind"] == "trials_recomputed"
        assert p["objective_names"] == ["m1_db", "m2_db"]
        # 前沿成员=手算 {0,1,2}，输出原序（trial 数值序）
        assert [n["trial"] for n in p["front"]] == [0, 1, 2]
        # 逐点目标值原样（违约量=指标值）
        got = [tuple(n["objectives"][k] for k in p["objective_names"])
               for n in p["front"]]
        assert got == [(8.0, 1.0), (5.0, 3.0), (2.0, 6.0)]
        # HV 与 ref：手算 21 / (9,7)，且与 pareto_tools 直调逐位一致
        hv_node = p["hypervolume"]
        assert hv_node["reference_point"] == [9.0, 7.0]
        assert hv_node["reference_point"] == \
            default_reference_point(got)
        assert hv_node["value"] == 21.0
        assert hv_node["value"] == exact_hypervolume(got, [9.0, 7.0])
        # knee：p1（弯曲角法），距离手算 |6·(−3)−(−5)·3|/√61 = 3/√61
        knee = p["knee"]
        assert knee["point"] == 1
        assert knee["method"] == "knee_point_bending_angle（2D 弯曲角法）"
        assert knee["value"] == pytest.approx(3.0 / math.sqrt(61.0))
        assert (knee["point"], knee["value"]) == \
            knee_point_bending_angle(got)

    def test_front_order_equals_nondominated_indices_input_order(
            self, tmp_path: Path):
        # 点序=pareto_tools.nondominated_indices 输出原序（trials 打乱写入序
        # 仍按 trial_number 数值序进矩阵——al_service.py:154 家法）
        run = tmp_path / "run_shuffled"
        (run / "trials").mkdir(parents=True)
        pts = _ANCHOR_POINTS
        for number, pt in [(10, pts[0]), (2, pts[1]), (1, pts[2]),
                           (4, pts[3]), (3, pts[4])]:
            (run / "trials" / f"trial_{number}.json").write_text(json.dumps({
                "trial_number": number, "params": {"p": float(pt[0])},
                "metrics": {"m1_db": pt[0], "m2_db": pt[1]},
                "cost": pt[0] + pt[1]}), encoding="utf-8")
        (run / "recipe.snapshot.yaml").write_text(yaml.safe_dump({
            "objectives": [
                {"metric": "m1_db", "band": [2.3, 2.5], "op": "max_below",
                 "value": 0.0},
                {"metric": "m2_db", "band": [2.3, 2.5], "op": "max_below",
                 "value": 0.0}]}), encoding="utf-8")
        (run / "meta.json").write_text(json.dumps({"run_id": run.name}))
        model = build_design_report_model(run, with_diagrams=False)
        front = _pareto_of(model)["front"]
        trials = [n["trial"] for n in front]
        assert trials == [1, 2, 10]  # 输入原序（trial 数值序）中的非支配成员
        # 手工重建同矩阵（盘上文件按 trial 数值序）→ 单源逐位
        files = sorted((run / "trials").glob("trial_*.json"),
                       key=lambda p: int(p.stem.split("_")[-1]))
        numbers = [int(p.stem.split("_")[-1]) for p in files]
        obj_mat = []
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            obj_mat.append([data["metrics"]["m1_db"],
                            data["metrics"]["m2_db"]])
        assert trials == [numbers[i] for i in nondominated_indices(obj_mat)]

    def test_zero_violation_is_legal_not_falsy(self, tmp_path: Path):
        # #364-④ 家法：违约量恰 0.0 是合法前沿点；cost=0.0 不是缺失
        run = _make_mo_run(
            tmp_path,
            points=[(2.0, 0.0), (3.0, 1.0)],
            params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
            costs=[0.0, 4.0])
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert [n["trial"] for n in p["front"]] == [0]  # (2,0) 支配 (3,1)
        node = p["front"][0]
        assert {k: v for k, v in node["objectives"].items()
                if k != "source"} == {"m1_db": 2.0, "m2_db": 0.0}
        assert node["cost"] == 0.0  # 0.0 不得被顶替成 None/缺失
        assert p["hypervolume"]["value"] == 1.0  # ref=(3,1)：1×1 盒
        assert p["hypervolume"]["value"] == exact_hypervolume(
            [(2.0, 0.0)], [3.0, 1.0])

    def test_three_objectives_hv_inclusion_exclusion_and_hv_knee(
            self, tmp_path: Path):
        # 3D：A=(1,5,5) B=(5,1,5) C=(5,5,1) 互不支配；ref=(6,6,6)；
        # HV=5+5+5 −1−1−1 +1 = 13（容斥）；knee=HV 贡献法（k>2 无唯一弯曲角）
        run = _make_mo_run(
            tmp_path, points=[(1.0, 5.0, 5.0), (5.0, 1.0, 5.0), (5.0, 5.0, 1.0)],
            n_objectives=3,
            params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0},
                    {"arm_len_mm": 22.0}])
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert p["objective_names"] == ["m1_db", "m2_db", "m3_db"]
        pts = [(1.0, 5.0, 5.0), (5.0, 1.0, 5.0), (5.0, 5.0, 1.0)]
        ref = [6.0, 6.0, 6.0]
        assert p["hypervolume"]["value"] == 13.0
        assert p["hypervolume"]["value"] == exact_hypervolume(pts, ref)
        assert p["hypervolume"]["reference_point"] == ref
        assert p["knee"]["method"].startswith("knee_point_hv_contribution")
        assert (p["knee"]["point"], p["knee"]["value"]) == \
            knee_point_hv_contribution(pts, ref)


# ── B provenance 门 ─────────────────────────────────────────────────────────


class TestParetoProvenance:
    def test_bare_number_fields_empty_with_and_without_png(
            self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        assert bare_number_fields(
            build_design_report_model(run, with_diagrams=False)) == []
        model_png = build_design_report_model(run, with_diagrams=True)
        assert model_png["pareto"]["scatter"]["status"] == "ok"
        assert bare_number_fields(model_png) == []

    def test_nsga2_model_bare_number_fields_empty(self, tmp_path: Path):
        run = _make_nsga2_run(tmp_path, hv_convergence=[1.0, 2.5, 2.5])
        assert bare_number_fields(
            build_design_report_model(run, with_diagrams=False)) == []

    def test_negative_example_detected(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        stripped = json.loads(json.dumps(model))
        del stripped["pareto"]["front"][0]["objectives"]["source"]
        assert bare_number_fields(stripped) != []


# ── C 三降级如实（不凑节不炸） ───────────────────────────────────────────────


class TestDegradation:
    def test_single_objective_na(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, n_objectives=1,
                           points=[(3.0,), (1.0,)],
                           params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
                           costs=[3.0, 1.0])
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "na_single_objective"
        assert p["objective_names"] == ["m1_db"]
        assert "front" not in p and "hypervolume" not in p
        md = render_design_report_md(model)
        assert "single-objective run" in md and "N/A" in md
        # 既有节零变化：⑥ 复现附录不重编号（头部原样在 ⑤b 之后）
        assert md.index("## ⑤b") < md.index("## ⑥ 复现命令附录")

    def test_missing_objective_key_unknown_not_zero(self, tmp_path: Path):
        # trial 1 缺 m2_db 键（SpecEvaluator 对缺键静默贡献 0——绝不能当
        # 违约量 0 进前沿，#364-④）
        run = _make_mo_run(tmp_path, metrics_override={
            1: {"m1_db": 0.5},  # 缺 m2_db
        })
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "unknown"
        assert "trial 1" in p["note"] and "键缺失" in p["note"]
        assert "front" not in p and "hypervolume" not in p
        assert p["counts"]["n_pareto"] is None
        md = render_design_report_md(model)
        assert "unknown" in md and "trial 1" in md

    def test_non_numeric_metric_value_unknown(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, metrics_override={
            0: {"m1_db": "bad", "m2_db": 1.0},  # 非数值
        })
        model = build_design_report_model(run, with_diagrams=False)
        assert _pareto_of(model)["status"] == "unknown"

    def test_insufficient_trials_single_point_honest(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, points=[(2.0, 4.0)],
                           params=[{"arm_len_mm": 20.0}], costs=[6.0])
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert "<2" in p["note"] and "单点前沿" in p["note"]
        assert p["counts"]["n_pareto"] == 1
        assert p["hypervolume"]["value"] == 1.0  # ref=(3,5)：1×1 盒

    def test_no_objective_spec_na(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, with_recipe=False)
        model = build_design_report_model(run, with_diagrams=False)
        assert _pareto_of(model)["status"] == "na_no_objective_spec"

    def test_empty_objectives_list_na(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, drop_objectives=True)
        model = build_design_report_model(run, with_diagrams=False)
        assert _pareto_of(model)["status"] == "na_no_objective_spec"

    def test_all_metrics_empty_missing(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, metrics_override={
            i: {} for i in range(len(_ANCHOR_POINTS))})
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "missing"
        assert "无 metrics" in p["note"]
        assert "front" not in p

    def test_malformed_metric_objective_spec_unknown(self, tmp_path: Path):
        # objective 规格不可解析（op 非法枚举触发 pydantic 校验负例）→ unknown
        run = tmp_path / "run_badspec"
        (run / "trials").mkdir(parents=True)
        (run / "trials" / "trial_0.json").write_text(json.dumps({
            "trial_number": 0, "params": {"p": 1.0},
            "metrics": {"m1_db": 1.0, "m2_db": 1.0}, "cost": 2.0}))
        (run / "recipe.snapshot.yaml").write_text(yaml.safe_dump({
            "objectives": [
                {"metric": "m1_db", "band": [2.3, 2.5], "op": "max_below",
                 "value": 0.0},
                {"metric": "m2_db", "band": [2.3, 2.5], "op": "bogus_op",
                 "value": 0.0}]}), encoding="utf-8")
        (run / "meta.json").write_text(json.dumps({"run_id": "run_badspec"}))
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "unknown"
        assert "不可解析" in p["note"]


# ── 双源：源 A（pareto_front.json 直读） ────────────────────────────────────


class TestFrontFileSource:
    def test_direct_read_hv_convergence_and_weak_monotone(
            self, tmp_path: Path):
        run = _make_nsga2_run(tmp_path,
                              hv_convergence=[1.0, 2.5, 2.5, 2.5])
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok" and p["kind"] == "front_file"
        assert p["objective_names"] == ["s11_db", "s21_db"]
        assert [n["point"] for n in p["front"]] == [0, 1, 2]
        got = [tuple(n["objectives"][k] for k in p["objective_names"])
               for n in p["front"]]
        assert p["hypervolume"]["value"] == exact_hypervolume(
            got, default_reference_point(got))
        assert p["hypervolume"]["value"] == 21.0
        conv = p["hv_convergence"]
        assert conv is not None
        assert conv["n_generations"] == 4
        assert conv["first"] == 1.0 and conv["last"] == 2.5
        assert conv["weakly_monotone"] is True
        assert p["counts"]["n_trials_evaluable"] is None

    def test_n_pareto_mismatch_noted(self, tmp_path: Path):
        run = _make_nsga2_run(tmp_path, n_pareto=99)
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert "n_pareto=99" in p["note"] and "不符" in p["note"]

    def test_malformed_doc_falls_back_to_trials(self, tmp_path: Path):
        # 形态不合（objective_names 只有 1 个）→ 回退 trials 现算+注记
        run = _make_mo_run(tmp_path)
        names = ["s11_db"]
        doc = {"objective_names": names, "pareto_points": [
            {"params": {}, "objectives": {"s11_db": 1.0}}],
            "n_pareto": 1}
        (run / "results").mkdir(exist_ok=True)
        (run / "results" / "pareto_front.json").write_text(
            json.dumps(doc), encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert p["kind"] == "trials_recomputed"
        assert "pareto_front.json" in p["note"] and "回退" in p["note"]

    def test_point_missing_objective_value_not_usable(self, tmp_path: Path):
        # 点缺目标键（objectives 只有 s11_db）→ 形态不合 → 回退 trials
        run = _make_mo_run(tmp_path)
        doc = {"objective_names": ["s11_db", "s21_db"], "pareto_points": [
            {"params": {}, "objectives": {"s11_db": 1.0}}]}
        (run / "results").mkdir(exist_ok=True)
        (run / "results" / "pareto_front.json").write_text(
            json.dumps(doc), encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        assert _pareto_of(model)["kind"] == "trials_recomputed"

    def test_non_monotone_convergence_flagged_honestly(
            self, tmp_path: Path):
        run = _make_nsga2_run(tmp_path, hv_convergence=[3.0, 2.0])
        model = build_design_report_model(run, with_diagrams=False)
        conv = _pareto_of(model)["hv_convergence"]
        assert conv["weakly_monotone"] is False  # 如实回显，不凑单调
        md = render_design_report_md(model)
        assert "否（如实注记）" in md


# ── 约束面（list/dict 双格式 + 可行优先支配 + 回退） ─────────────────────────


class TestConstraints:
    def test_feasible_dominates_infeasible_list_format(self, tmp_path: Path):
        # (1,1) 可行支配 (0.5,0.5) 不可行（Deb 2000 可行优先）
        run = _make_mo_run(
            tmp_path, points=[(1.0, 1.0), (0.5, 0.5)],
            params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
            costs=[2.0, 1.0],
            constraint_values={0: [0.0], 1: [5.0]})
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert [n["trial"] for n in p["front"]] == [0]
        assert p["front"][0]["feasible"] is True
        assert p["front"][0]["constraint_values"] == [0.0]
        # md 可行列：可行=是
        md = render_design_report_md(model)
        assert "是" in md

    def test_constraint_dict_format(self, tmp_path: Path):
        run = _make_mo_run(
            tmp_path, points=[(1.0, 1.0), (0.5, 0.5)],
            params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
            costs=[2.0, 1.0],
            constraint_values={0: {"c1_db": -1.0}, 1: {"c1_db": 5.0}})
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert [n["trial"] for n in p["front"]] == [0]
        assert p["front"][0]["constraint_values"] == [-1.0]

    def test_unusable_constraint_falls_back_with_note(self, tmp_path: Path):
        # 一 trial 有约束键、一 trial 缺 → 整体回退无约束支配+如实注记
        run = _make_mo_run(
            tmp_path, points=[(1.0, 1.0), (3.0, 3.0)],
            params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
            costs=[2.0, 6.0],
            constraint_values={0: [0.5]})
        model = build_design_report_model(run, with_diagrams=False)
        p = _pareto_of(model)
        assert p["status"] == "ok"
        assert "回退无约束支配" in p["note"]
        assert all(n["constraint_values"] is None for n in p["front"])
        # 回退后标准支配：trial0 支配 trial1
        assert [n["trial"] for n in p["front"]] == [0]


# ── E 散点 PNG（确定性逐字节 + 降级不落盘） ──────────────────────────────────


class TestScatterPng:
    def test_two_runs_byte_identical_and_md_link(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        r1 = generate_design_report(run)
        png = run / "diagrams" / "pareto_scatter.png"
        bytes1 = png.read_bytes()
        r2 = generate_design_report(run)
        bytes2 = png.read_bytes()
        assert r1["ok"] and r2["ok"]
        assert bytes1 == bytes2  # E：确定性两跑逐字节
        assert bytes1[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(bytes1) > 1000
        md = (run / "design_report.md").read_text(encoding="utf-8")
        assert "[diagrams/pareto_scatter.png](diagrams/pareto_scatter.png)" \
            in md  # T-O9 round-trip 相对链接
        # 图例标签（front/dominated）只在 PNG 内；正文 "nondominated_indices"
        # 为函数名合法出现，剥后不得再有独立 dominated 字样
        assert md.replace("nondominated", "").count("dominated") == 0

    def test_with_diagrams_false_skips_png(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        model = build_design_report_model(run, with_diagrams=False)
        scatter = _pareto_of(model)["scatter"]
        assert scatter["status"] == "skipped"
        assert scatter["path"] is None
        assert not (run / "diagrams").exists()

    def test_single_point_png_rendered(self, tmp_path: Path):
        run = _make_mo_run(tmp_path, points=[(2.0, 4.0)],
                           params=[{"arm_len_mm": 20.0}], costs=[6.0])
        generate_design_report(run)
        assert (run / "diagrams" / "pareto_scatter.png").is_file()


# ── D 既有报告路径零变化 + md 确定性 ────────────────────────────────────────


class TestExistingPathZeroChange:
    def test_section_headers_order_and_repro_unrenumbered(
            self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        md = render_design_report_md(build_design_report_model(run))
        headers = [line for line in md.splitlines()
                   if line.startswith("## ")]
        assert headers == [
            "## ① 设计目标与配方摘要",
            "## ② 优化轨迹回放",
            "## ③ 最终设计与 verdict 门表",
            "## ④ 电路图总结（.drawio 附件）",
            "## ⑤ 敏感性 / trade-off 摘要",
            "## ⑤b Pareto 前沿（多目标 run 扩展节）",
            "## ⑥ 复现命令附录",
        ]

    def test_single_objective_original_sections_intact(self, tmp_path: Path):
        # 单目标 run：①-⑥ 内容不受影响（front/hypervolume 节键不出现），
        # ⑤b 如实 N/A；既有消费面（信封/其余节）键集零增减
        run = _make_mo_run(tmp_path, n_objectives=1,
                           points=[(3.0,), (1.0,)],
                           params=[{"arm_len_mm": 20.0}, {"arm_len_mm": 21.0}],
                           costs=[3.0, 1.0])
        model = build_design_report_model(run, with_diagrams=False)
        assert set(model) >= {
            "schema", "run_ref", "goals", "trajectory", "final_design",
            "diagrams", "tradeoff", "pareto", "repro", "anomalies",
            "base_report"}
        result = generate_design_report(run, output=tmp_path / "dr.md")
        assert result["ok"]
        assert set(result) == {"ok", "run_id", "schema", "report",
                               "diagrams", "design_verdict", "n_gates_pass",
                               "n_gates_fail", "freshness"}  # 信封零增键

    def test_md_two_pass_identical_except_timestamp(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        t1 = render_design_report_md(
            build_design_report_model(run, with_diagrams=False)).splitlines()
        t2 = render_design_report_md(
            build_design_report_model(run, with_diagrams=False)).splitlines()
        assert len(t1) == len(t2)
        diffs = [(a, b) for a, b in zip(t1, t2, strict=True) if a != b]
        assert len(diffs) <= 1
        assert all("生成时间" in a and "生成时间" in b for a, b in diffs)

    def test_front_table_cells_render_trial_and_values(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        md = render_design_report_md(
            build_design_report_model(run, with_diagrams=False))
        assert "| 0 | 0 | 8 | 1 | 9 |" in md
        assert "| 2 | 2 | 2 | 6 | 8 |" in md
        assert "hypervolume" in md and "reference_point" in md
        assert "knee" in md

    def test_generate_envelope_ok_and_report_written(self, tmp_path: Path):
        run = _make_mo_run(tmp_path)
        result = generate_design_report(run)
        assert result["ok"]
        assert Path(result["report"]).is_file()
        md = Path(result["report"]).read_text(encoding="utf-8")
        assert "## ⑤b Pareto 前沿（多目标 run 扩展节）" in md
        # HV 说明列字面 |·|（绝对值）已转义——管道表不被撕裂
        assert "0.1·\\|最差值\\|" in md
