"""C1L1 最终设计选择约束格式语义钉（aurora_p，2026-11-01）。

缺口（C1 席如实登记）：:func:`rfauto.service.design_replay_report.
_pick_best_trial` 只认 dict 形 ``constraint_values``，而优化器写侧落盘
为 **list 形**——真实约束 TPE run 的 §③ 最终设计选择把不可行 trial 当
无约束处理（可能选中违约点当"最终设计"）。既有钉用 dict 夹具故绿
（夹具盲区型 bug），本文件用**真实写侧形态**构造夹具清偿。

写侧语义出处（optimization/optimizer.py，本文件断言的形态地面真相）：
- ``_record_constraints``（:358-383）：逐约束违约量 list[float] 写入
  trial 审计 ``constraint_values``（:378 set_user_attr；湖审计落盘
  :594-595，仅约束 run 写）——元素=该 trial 第 i 条约束（配方
  constraints 表序）的违约量，**>0=违约、0=可行边界**（docstring
  :363-374）；``feasible`` 旗标=``all(v <= 0.0)``（:379）同口径。
- NaN 违约量走 user_attrs 通道（新通道 set_constraint 拒 NaN，:370-372），
  ``nan <= 0`` 恒 False → ``feasible=False``（:379）——非数值/NaN 按违约
  处理。
- 缺失视为可行（``_trial_is_feasible`` :341-355 ``vals is None → True``，
  兼容旧 study 断点续跑）。

读侧单源=design_replay_report._constraint_violations_of（list/dict 双
格式归一，与 §⑤b pareto 节共用——禁两份解析逻辑）。dict 路径既有行为
零变化（test_design_replay_report.py 既有钉全绿为本席门）。

全部离线确定性（#139 零网络；#144 tmp_path 隔离零湖写）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.design_replay_report import build_design_report_model


def _make_run(tmp_path: Path, name: str,
              trials: list[dict]) -> Path:
    """优化族最小湖同构 fixture（meta + trials/trial_N.json）。

    ``constraint_values`` 一律用优化器真实落盘形态构造（list[float] 违约
    量，optimizer.py:594-595）——禁造第三种"方便"形态（任务书红线）。
    """
    run = tmp_path / name
    (run / "trials").mkdir(parents=True)
    for i, rec in enumerate(trials):
        base: dict = {"trial_number": i, "params": {"p": float(i)},
                      "metrics": {}}
        base.update(rec)
        (run / "trials" / f"trial_{i}.json").write_text(
            json.dumps(base, indent=1), encoding="utf-8")
    (run / "meta.json").write_text(
        json.dumps({"run_id": name}), encoding="utf-8")
    return run


class TestListFormFinalDesignSelection:
    """list 形（真实写侧形态）最终设计选择——修复前红（复现钉）。"""

    def test_list_infeasible_low_cost_not_selected(self, tmp_path: Path):
        # 复现钉（B）：违约 trial cost 更低，修复前被判无约束而当选——
        # 修复后 Deb 可行优先：可行 trial 胜出（即便 cost 更高，与既有
        # dict 钉 test_constraint_values_feasible_filter 同款场景）。
        run = _make_run(tmp_path, "run_list_mix", [
            {"cost": 0.1, "constraint_values": [0.5]},   # 违约（低成本）
            {"cost": 5.0, "constraint_values": [-1.0]},  # 可行
        ])
        model = build_design_report_model(run, with_diagrams=False)
        best = model["final_design"]["best"]
        assert best["status"] == "ok"
        assert best["trial"] == 1  # cost 5 但可行
        assert best["cost"] == 5.0
        assert best["constrained"] is True

    def test_list_all_infeasible_honest_degradation(self, tmp_path: Path):
        # 全不可行 → all_infeasible 如实降级（既有 dict 语义同款，
        # E10 best_feasible 对齐：最终设计表留空不凑绿）。
        run = _make_run(tmp_path, "run_list_infeasible", [
            {"cost": 0.1, "constraint_values": [0.5]},
            {"cost": 0.2, "constraint_values": [0.3]},
        ])
        model = build_design_report_model(run, with_diagrams=False)
        fd = model["final_design"]
        assert fd["best"]["status"] == "all_infeasible"
        assert fd["best"]["constrained"] is True
        assert fd["rows"] == []
        assert "不可行" in fd["note"]

    def test_list_nan_violation_treated_infeasible(self, tmp_path: Path):
        # NaN 违约量（optimizer :370-372 user_attrs 通道承载）按违约
        # 处理（:379 feasible=False 同口径；读侧 _num NaN→None）。
        run = _make_run(tmp_path, "run_list_nan", [
            {"cost": 0.1, "constraint_values": [float("nan")]},
            {"cost": 5.0, "constraint_values": [-0.5]},
        ])
        model = build_design_report_model(run, with_diagrams=False)
        best = model["final_design"]["best"]
        assert best["status"] == "ok"
        assert best["trial"] == 1

    def test_list_missing_key_trial_feasible_like_dict(self, tmp_path: Path):
        # 约束 run 中缺 constraint_values 键的 trial 视为可行（既有 dict
        # 路径口径 + optimizer _trial_is_feasible ``vals is None → True``
        # 旧 study 兼容一致；缺失≠违约）。
        run = _make_run(tmp_path, "run_list_missing", [
            {"cost": 1.0},                              # 无约束键
            {"cost": 3.0, "constraint_values": [0.5]},  # 违约
        ])
        model = build_design_report_model(run, with_diagrams=False)
        best = model["final_design"]["best"]
        assert best["status"] == "ok"
        assert best["trial"] == 0
        assert best["constrained"] is True

    def test_unconstrained_run_behavior_unchanged(self, tmp_path: Path):
        # 无约束 run 零变化（C 的另一面）：无 constraint_values 键 →
        # 全体候选、cost 最小者胜出、constrained=False。
        run = _make_run(tmp_path, "run_no_cons", [
            {"cost": 2.0},
            {"cost": 1.0},
        ])
        model = build_design_report_model(run, with_diagrams=False)
        best = model["final_design"]["best"]
        assert best["status"] == "ok"
        assert best["trial"] == 1
        assert best["cost"] == 1.0
        assert best["constrained"] is False


# 等价钉共享 trial 集：(cost, violations)。trial_0 违约（分量1>0）；
# trial_1 可行（边界 0 计可行）；trial_2 可行。可行域内 cost 最小=trial_1。
_EQUIV_VALUES = [(2.0, (0.1, -0.5)), (7.0, (-0.2, 0.0)), (9.0, (-1.0, -1.0))]


class TestDualFormSemanticEquivalence:
    """双格式语义等价钉（D）：同一 trial 集合 list/dict 选择结果一致。"""

    def test_same_trial_set_same_selection(self, tmp_path: Path):
        # 可行域内 cost 最小=trial_1（cost 7.0）——两格式同判。
        run_list = _make_run(tmp_path, "run_equiv_list", [
            {"cost": cost, "constraint_values": list(vals)}
            for cost, vals in _EQUIV_VALUES
        ])
        run_dict = _make_run(tmp_path, "run_equiv_dict", [
            {"cost": cost,
             "constraint_values": {f"c{j}": v for j, v in enumerate(vals)}}
            for cost, vals in _EQUIV_VALUES
        ])
        best_list = build_design_report_model(
            run_list, with_diagrams=False)["final_design"]["best"]
        best_dict = build_design_report_model(
            run_dict, with_diagrams=False)["final_design"]["best"]
        assert best_list["trial"] == 1
        assert best_list == best_dict
        assert best_dict["constrained"] is True

    def test_all_infeasible_same_degradation(self, tmp_path: Path):
        # 全不可行降级形态两格式一致。
        run_list = _make_run(tmp_path, "run_inf_list", [
            {"cost": 0.1, "constraint_values": [0.5]},
            {"cost": 0.2, "constraint_values": [0.3]},
        ])
        run_dict = _make_run(tmp_path, "run_inf_dict", [
            {"cost": 0.1, "constraint_values": {"c": 0.5}},
            {"cost": 0.2, "constraint_values": {"c": 0.3}},
        ])
        best_list = build_design_report_model(
            run_list, with_diagrams=False)["final_design"]["best"]
        best_dict = build_design_report_model(
            run_dict, with_diagrams=False)["final_design"]["best"]
        assert best_list["status"] == "all_infeasible"
        assert best_list == best_dict
