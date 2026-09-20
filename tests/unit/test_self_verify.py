"""WP3.5 自验证环收口测试：propose→verify→fix 闭环 + milestone 由易到难。

方案 §4 WP3.5 口径（§10.23 归宿：service/autotune_service 🟨→本轮收口）：
- propose（typed call，LLM/优化器只出假设起点）→ verify（确定性内核：
  引擎基准 sampler + SpecEvaluator + 谷位/带中心闭式对照）→
  fix（critique_point typed fixes）闭环；
- propose 输出由易到难 milestone 分解（粗网格→细网格、单点→战役，
  逐里程碑验收，passed/failed/skipped 如实标注）；
- 执行看板（暂停/接管）走 service/loop_board.py，环在步骤边界协作式响应。
全部 fake sampler 离线秒级，零真机。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _fake_sampler(valley_fn, rl_fn, on_call=None):
    """fake sampler：metrics 由谷位+回损函数决定（同 test_autotune 口径）。"""
    calls = {"n": 0}

    def sampler(params: dict[str, float]) -> dict[str, Any]:
        calls["n"] += 1
        if on_call is not None:
            on_call(calls["n"], params)
        return {
            "metrics": {
                "s11_db_max_in_band": rl_fn(params),
                "s21_db_mean_in_band": -3.3,
                "iso_s23_db_min_in_band": -30.0,
            },
            "valley_ghz": valley_fn(params),
        }

    sampler.calls = calls  # type: ignore[attr-defined]
    return sampler


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 12.0, "high": 30.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "selfverify_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestDecomposeMilestones:
    def test_ladder_easy_to_hard_deterministic(self):
        from rfauto.service.autotune_service import decompose_milestones

        ms = decompose_milestones({})
        again = decompose_milestones({})
        assert ms == again  # 确定性
        assert [m["id"] for m in ms] == ["M1", "M2", "M3", "M4", "M5"]
        order = {"easy": 0, "medium": 1, "hard": 2}
        ranks = [order[m["difficulty"]] for m in ms]
        assert ranks == sorted(ranks), "难度必须由易到难单调递增"
        for m in ms:
            assert m["status"] == "pending"
            assert m["acceptance"], "逐里程碑验收必须有显式判据"
        names = " ".join(m["name"] for m in ms)
        assert "粗网格" in names and "细网格" in names  # 粗→细口径

    def test_acceptance_embeds_tolerances(self):
        from rfauto.service.autotune_service import decompose_milestones

        ms = decompose_milestones({}, f0_tolerance=0.1, fine_epsilon=0.3)
        assert "10%" in ms[1]["acceptance"]
        assert "0.3" in ms[3]["acceptance"]


class TestSelfVerifyHappyPath:
    def test_full_loop_pass_all_milestones(self, recipe_path):
        """谷位修正→达标→细网格复验→沙箱草稿：verdict PASS、看板 done。"""
        from rfauto.service.autotune_service import self_verify_loop
        from rfauto.service.loop_board import LoopBoard

        def valley(p):
            return 2.4 if p["arm_len_mm"] < 20.0 else 1.8

        board_root = Path("boards")
        board = _new_board(board_root)
        sampler = _fake_sampler(valley, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=3,
                             board=board)
        assert r["ok"], r.get("errors")
        assert r["verdict"] == "PASS"
        assert sampler.calls["n"] >= 2, "至少一次修正轮"
        by_id = {m["id"]: m for m in r["milestones"]}
        assert by_id["M1"]["status"] == "passed"
        assert by_id["M2"]["status"] == "passed"
        assert by_id["M3"]["status"] == "passed"
        assert by_id["M4"]["status"] == "passed"
        assert by_id["M5"]["status"] == "passed"
        assert r["sandbox"]["ok"]
        draft = Path(r["sandbox"]["draft"])
        assert draft.exists() and "sandbox" in str(draft)  # 写面隔离

        # 产物兼容既有消费者（dataset_service/rationale_memory 读 autotune.json）
        run_dir = Path(r["run_dir"])
        data = json.loads((run_dir / "autotune.json").read_text(encoding="utf-8"))
        assert data["verdict"] == "PASS" and data["final_params"]

        # 看板落盘：全部里程碑 passed、终态 done
        disk = LoopBoard.load(r["board_id"], root=board_root).read()
        assert disk["status"] == "done"
        assert all(m["status"] == "passed" for m in disk["milestones"])
        assert disk["best"] is not None
        assert any(s["name"] == "propose" for s in disk["steps"])

    def test_board_disabled(self, recipe_path):
        from rfauto.service.autotune_service import self_verify_loop

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             board=None)
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["board_id"] is None


class TestProposeStage:
    def test_typed_proposer_used_and_clipped(self, recipe_path):
        """proposer typed call：假设起点被采纳但限界收敛（确定性守卫）。"""
        from rfauto.service.autotune_service import self_verify_loop

        def proposer(state):
            assert state["bounds"]["arm_len_mm"] == (12.0, 30.0)
            return {"params": {"arm_len_mm": 99.0},  # 越界假设 → 限到 30
                    "note": "LLM 假设（typed）"}

        seen: list[dict] = []

        def on_call(n, params):
            seen.append(dict(params))

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0, on_call)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             proposer=proposer, board=None)
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["proposer_note"] == "LLM 假设（typed）"
        assert seen[0]["arm_len_mm"] == 30.0, "proposer 参数必须限界后进环"

    def test_proposer_milestone_override_validated(self, recipe_path):
        from rfauto.service.autotune_service import self_verify_loop

        def proposer(state):
            return {"params": {"arm_len_mm": 18.0},
                    "milestones": [
                        {"id": "A1", "name": "单点", "difficulty": "easy",
                         "acceptance": "有 metrics"},
                        {"id": "A2", "name": "达标", "difficulty": "hard",
                         "acceptance": "cost=0"},
                    ]}

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             proposer=proposer, board=None)
        assert [m["id"] for m in r["milestones"]] == ["A1", "A2"]
        assert all(m["status"] == "passed" for m in r["milestones"])

    def test_proposer_bad_milestones_falls_back(self, recipe_path):
        """形状不合规的 milestone 覆写 → 退回确定性分解（typed 纪律）。"""
        from rfauto.service.autotune_service import self_verify_loop

        def proposer(state):
            return {"params": {"arm_len_mm": 18.0},
                    "milestones": [{"id": "X"}]}  # 缺 name/acceptance

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             proposer=proposer, board=None)
        assert [m["id"] for m in r["milestones"]] == ["M1", "M2", "M3", "M4", "M5"]


class TestControlSemantics:
    def test_pause_then_resume_completes(self, recipe_path, tmp_path):
        """暂停在步骤边界生效，resume 后环继续完成（协作式，不打断仿真）。"""
        from rfauto.service.autotune_service import self_verify_loop
        from rfauto.service.loop_board import LoopBoard

        board_root = tmp_path / "boards"
        board = _new_board(board_root)
        board.control("pause")

        def _resume_like_human():
            time.sleep(0.1)
            board.control("resume")

        t = threading.Thread(target=_resume_like_human)
        t.start()
        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=2,
                             board=board, pause_poll_s=0.01)
        t.join()
        assert r["ok"] and r["verdict"] == "PASS"
        disk = LoopBoard.load(r["board_id"], root=board_root).read()
        assert disk["status"] == "done"

    def test_pause_timeout_auto_resume_noted(self, recipe_path, tmp_path):
        """无人 resume：超时自动续跑并如实记录（批处理不被挂死）。"""
        from rfauto.service.autotune_service import self_verify_loop

        board = _new_board(tmp_path / "boards")
        board.control("pause")
        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             board=board, pause_timeout_s=0.05, pause_poll_s=0.01)
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["pause_notes"] and "超时" in r["pause_notes"][0]

    def test_takeover_stops_and_stages_draft(self, recipe_path, tmp_path):
        """接管：环如实停（TAKEN_OVER），best 已落沙箱草稿供人续跑。"""
        from rfauto.service.autotune_service import self_verify_loop
        from rfauto.service.loop_board import LoopBoard

        board_root = tmp_path / "boards"
        board = _new_board(board_root)
        board.control("takeover")  # 环开始前就接管
        sampler = _fake_sampler(lambda p: 1.8, lambda p: -5.0)  # 病态面
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=5,
                             board=board)
        assert r["ok"]
        assert r["verdict"] == "TAKEN_OVER"
        assert sampler.calls["n"] == 0, "接管后不得再消耗一次仿真"
        disk = LoopBoard.load(r["board_id"], root=board_root).read()
        assert disk["status"] == "taken_over"

    def test_takeover_after_first_round_keeps_best(self, recipe_path, tmp_path):
        """第一轮后接管：best-so-far 保留，verdict TAKEN_OVER。"""
        from rfauto.service.autotune_service import self_verify_loop
        from rfauto.service.loop_board import LoopBoard

        board_root = tmp_path / "boards"
        board = _new_board(board_root)

        def on_call(n, params):
            if n == 1:
                board.control("takeover")  # 第一轮仿真完成后由人接管

        def valley(p):
            return 2.4 if p["arm_len_mm"] < 20.0 else 1.8

        sampler = _fake_sampler(valley, lambda p: -20.0, on_call)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=3,
                             board=board)
        assert r["verdict"] == "TAKEN_OVER"
        assert r["best"] is not None  # best-so-far 保留
        disk = LoopBoard.load(r["board_id"], root=board_root).read()
        assert disk["status"] == "taken_over"
        assert disk["best"] is not None


class TestHonestFailure:
    def test_budget_exhausted_fail(self, recipe_path):
        """RL 永远浅且无改进方向：M3 如实 failed，verdict FAIL。"""
        from rfauto.service.autotune_service import self_verify_loop

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -5.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=2,
                             rl_floor_db=-8.0, board=None)
        assert r["ok"] and r["verdict"] == "FAIL"
        by_id = {m["id"]: m for m in r["milestones"]}
        assert by_id["M1"]["status"] == "passed"  # 基线在案
        assert by_id["M3"]["status"] == "failed"

    def test_fine_grid_mismatch_fails_m4(self, recipe_path):
        """细网格复验劣化超 ε：M4 如实 failed（跨网格一致性不过）。"""
        from rfauto.service.autotune_service import self_verify_loop

        coarse = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        fine = _fake_sampler(lambda p: 2.4, lambda p: -6.0)  # 细网格更差
        r = self_verify_loop(recipe_path, sampler_fn=coarse,
                             fine_sampler_fn=fine, budget_coarse=1, board=None)
        by_id = {m["id"]: m for m in r["milestones"]}
        assert by_id["M4"]["status"] == "failed"
        assert "fine cost" in (by_id["M4"]["detail"] or "")
        assert r["verdict"] == "FAIL"

    def test_no_length_params_m2_skipped(self, tmp_path):
        """无长度类参数：M2 如实 skipped，其余可达 PASS。"""
        from rfauto.service.autotune_service import self_verify_loop

        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"gap_um": {"value": 100}},
            "setup": {"freq_range_ghz": [2.3, 2.5]},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "optimization": {"params": {"gap_um": {"low": 50, "high": 200}}},
        }
        path = tmp_path / "nolen.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")

        def fake_metrics(params):
            return {"metrics": {"s11_db_max_in_band": -20.0}, "valley_ghz": 2.4}

        r = self_verify_loop(path, sampler_fn=fake_metrics, budget_coarse=1,
                             board=None)
        by_id = {m["id"]: m for m in r["milestones"]}
        assert by_id["M2"]["status"] == "skipped"
        assert r["verdict"] == "PASS"

    def test_fine_disabled_m4_skipped(self, recipe_path):
        from rfauto.service.autotune_service import self_verify_loop

        sampler = _fake_sampler(lambda p: 2.4, lambda p: -20.0)
        r = self_verify_loop(recipe_path, sampler_fn=sampler, budget_coarse=1,
                             mesh_fine_mm=0.0, board=None)  # 关细网格通道
        by_id = {m["id"]: m for m in r["milestones"]}
        assert by_id["M4"]["status"] == "skipped"
        assert r["verdict"] == "PASS"

    def test_sampler_exception_stops_with_fail(self, recipe_path):
        from rfauto.service.autotune_service import self_verify_loop

        def boom(params):
            raise RuntimeError("openEMS 不可用")

        r = self_verify_loop(recipe_path, sampler_fn=boom, budget_coarse=2,
                             board=None)
        assert r["ok"] and r["verdict"] == "FAIL"
        assert "openEMS 不可用" in r["history"][0]["error"]

    def test_missing_recipe_rejected(self, tmp_path):
        from rfauto.service.autotune_service import self_verify_loop

        assert not self_verify_loop(tmp_path / "nope.yaml", board=None)["ok"]


def _new_board(root: Path):
    from rfauto.service.loop_board import LoopBoard

    return LoopBoard(root=root)
