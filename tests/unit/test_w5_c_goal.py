"""W5-C DS-3：goal 域测试（持久目标+自动续轮 driver+CLI 四叶；全确定性零模型）。

规格判据（criteria.md W5-C 节预声明）：
①持久化存续单测：写入→subprocess 新进程读回同状态（跨进程存续铁面）；
②续轮 driver dry 轮转：确定性判据函数三态各一例（done/advancing/blocked）
  + 轮次预算用尽 blocked + done 幂等；
③CLI goal 子应用 --help/--json 双路径（成功信封+失败信封同构）；
④campaign 适配层：goal.done_when 引用 campaign verdict（只读消费既有
  plan 字段，零回写零双账本——campaign 本体 apply_event 语义原样）；
⑤零数值面：判据评估器只比较调用方供给的 evidence，不产物理数字。

#139 全 mock：零 LLM 零真机零网络；chdir 隔离不依赖（root 全显式传参）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.domains.goal import goal_app
from rfauto.service.campaign_manager import apply_event, save_plan
from rfauto.service.goal_domain import (
    CRITERIA_KINDS,
    advance_goal,
    campaign_evidence,
    get_goal,
    list_goals,
    set_goal,
)

runner = CliRunner()


def _goals_root(tmp_path: Path) -> Path:
    return tmp_path / "goals"


def _flag_spec() -> dict:
    return {"kind": "flag_equal", "key": "completed", "value": True}


# ─── ① 持久化存续（写入→subprocess 新进程读回同状态）─────────────────────────

def test_goal_persistence_survives_new_process(tmp_path):
    """写入 goal → 全新 Python 进程读回同 objective/status/rounds（跨进程）。"""
    root = _goals_root(tmp_path)
    made = set_goal(
        "把 2.4 GHz 滤波器调到 S11 达标",
        _flag_spec(),
        campaign_plan=None,
        max_rounds=4,
        goal_id="goal_w5c_persist",
        root=root)
    assert made["ok"], made.get("errors")
    # 同进程内推进一轮（未达标→advancing，rounds=1）后再交给新进程读
    adv = advance_goal("goal_w5c_persist", root=root,
                       evidence_fn=lambda _g: {"completed": False})
    assert adv["ok"] and adv["status"] == "advancing" and adv["rounds"] == 1

    script = tmp_path / "_read_goal.py"
    script.write_text(
        "import json, sys\n"
        "from rfauto.service.goal_domain import get_goal\n"
        "got = get_goal(sys.argv[1], root=sys.argv[2])\n"
        "g = got.get('goal') or {}\n"
        "print(json.dumps({'ok': got.get('ok'), 'objective': g.get('objective'),"
        " 'status': g.get('status'), 'rounds': g.get('rounds'),"
        " 'done_when': g.get('done_when'), 'max_rounds': g.get('max_rounds'),"
        " 'schema': g.get('schema')}))\n",
        encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(script), "goal_w5c_persist", str(root)],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    state = json.loads(r.stdout.strip().splitlines()[-1])
    assert state["ok"] is True
    assert state["objective"] == "把 2.4 GHz 滤波器调到 S11 达标"
    assert state["status"] == "advancing"   # 新进程读回同状态（未再推进）
    assert state["rounds"] == 1
    assert state["done_when"] == _flag_spec()
    assert state["max_rounds"] == 4
    assert state["schema"] == "rfauto-goal-v1"


# ─── ② 续轮 driver dry 轮转（确定性判据函数三态各一例）────────────────────────

def test_driver_done_state_via_injected_criteria(tmp_path):
    """判据满足→done（rounds 不增；历史落 done 条目）。"""
    root = _goals_root(tmp_path)
    set_goal("达标即收", None, goal_id="goal_w5c_done", root=root)
    adv = advance_goal(
        "goal_w5c_done", root=root,
        criteria_fn=lambda g, e: True)
    assert adv["ok"] and adv["status"] == "done"
    assert adv["criteria_met"] is True and adv["advanced"] is True
    goal = get_goal("goal_w5c_done", root=root)["goal"]
    assert goal["rounds"] == 0                      # 达标不烧轮次
    assert goal["history"][-1]["result"] == "done"
    # done 幂等：再 advance 原样返回（advanced=False）
    again = advance_goal("goal_w5c_done", root=root,
                         criteria_fn=lambda g, e: False)
    assert again["ok"] and again["status"] == "done" and again["advanced"] is False


def test_driver_advancing_state_via_injected_criteria(tmp_path):
    """判据未满足且 planner 给出动作→advancing（rounds+1，建议随信封出）。"""
    root = _goals_root(tmp_path)
    set_goal("续推", None, goal_id="goal_w5c_adv", root=root)

    def _planner(goal, reason):
        return {"action": "retune", "round": int(goal["rounds"]) + 1,
                "reason": reason}

    adv = advance_goal("goal_w5c_adv", root=root,
                       criteria_fn=lambda g, e: False,
                       action_planner=_planner)
    assert adv["ok"] and adv["status"] == "advancing"
    assert adv["rounds"] == 1 and adv["criteria_met"] is False
    assert adv["suggestion"]["action"] == "retune"
    goal = get_goal("goal_w5c_adv", root=root)["goal"]
    assert goal["status"] == "advancing" and goal["rounds"] == 1


def test_driver_blocked_state_via_injected_criteria(tmp_path):
    """判据未满足且无可执行下一步→blocked（如实堵住，不空转）。"""
    root = _goals_root(tmp_path)
    set_goal("无路可走则堵", None, goal_id="goal_w5c_blk", root=root)
    adv = advance_goal("goal_w5c_blk", root=root,
                       criteria_fn=lambda g, e: False,
                       action_planner=lambda g, r: None)
    assert adv["ok"] and adv["status"] == "blocked"
    assert adv["criteria_met"] is False and adv["rounds"] == 1
    goal = get_goal("goal_w5c_blk", root=root)["goal"]
    assert goal["status"] == "blocked"


def test_driver_blocked_on_round_budget(tmp_path):
    """轮次预算用尽→blocked（done_when=rounds_at_least 走声明式 spec 评估）。"""
    root = _goals_root(tmp_path)
    set_goal("五轮内收工", {"kind": "rounds_at_least", "value": 5},
             max_rounds=2, goal_id="goal_w5c_budget", root=root)
    first = advance_goal("goal_w5c_budget", root=root,
                         evidence_fn=lambda _g: {})
    assert first["status"] == "advancing" and first["rounds"] == 1
    second = advance_goal("goal_w5c_budget", root=root,
                          evidence_fn=lambda _g: {})
    assert second["status"] == "blocked" and second["rounds"] == 2
    assert "轮次预算用尽" in second["reason"]
    assert second["suggestion"]["action"] == "blocked"


def test_driver_criteria_fn_exception_degrades_blocked(tmp_path):
    """判据函数异常=未达标（如实降级不猜）；无建议→blocked。"""
    root = _goals_root(tmp_path)
    set_goal("判据炸了要如实", None, goal_id="goal_w5c_boom", root=root)

    def _boom(_g, _e):
        raise RuntimeError("判据内核失联")

    adv = advance_goal("goal_w5c_boom", root=root, criteria_fn=_boom)
    assert adv["ok"] and adv["status"] == "blocked"
    assert "判据函数异常" in adv["reason"]


# ─── 声明式 spec 词表（flag_equal/rounds_at_least/未知 kind 拒收）──────────────

def test_spec_flag_equal_bool_type_guard(tmp_path):
    """flag_equal 布尔语义类型守卫：1 == True 的跨型相等不算达标。"""
    root = _goals_root(tmp_path)
    set_goal("布尔判据", _flag_spec(), goal_id="goal_w5c_flag", root=root)
    not_yet = advance_goal("goal_w5c_flag", root=root,
                           evidence_fn=lambda _g: {"completed": 1})
    assert not_yet["status"] == "advancing" and not_yet["criteria_met"] is False
    done = advance_goal("goal_w5c_flag", root=root,
                        evidence_fn=lambda _g: {"completed": True})
    assert done["status"] == "done" and done["criteria_met"] is True


def test_spec_rounds_at_least_via_evidence(tmp_path):
    """rounds_at_least 只认 evidence.rounds（证据缺如实未达）。"""
    root = _goals_root(tmp_path)
    set_goal("三轮起判", {"kind": "rounds_at_least", "value": 3},
             goal_id="goal_w5c_rounds", root=root)
    no_ev = advance_goal("goal_w5c_rounds", root=root, evidence_fn=lambda _g: {})
    assert no_ev["status"] == "advancing"
    met = advance_goal("goal_w5c_rounds", root=root,
                       evidence_fn=lambda _g: {"rounds": 3})
    assert met["status"] == "done"


def test_set_goal_rejects_unknown_criteria_kind(tmp_path):
    """未知判据 kind 立目标即拒（词表外零入口）。"""
    made = set_goal("坏判据", {"kind": "vibes", "value": 1},
                    goal_id="goal_w5c_bad", root=_goals_root(tmp_path))
    assert made["ok"] is False
    assert "vibes" in made["errors"][0] and "未知" in made["errors"][0]
    assert sorted(CRITERIA_KINDS) == ["campaign_verdict", "flag_equal",
                                      "rounds_at_least"]


def test_goal_id_whitelist(tmp_path):
    """goal_id 白名单：路径穿越/非法字符拒收（防落盘逃逸）。"""
    root = _goals_root(tmp_path)
    for bad in ("../escape", "a/b", "", ".", ".."):
        made = set_goal("x", None, goal_id=bad, root=root)
        assert made["ok"] is False, bad
    made = set_goal("合法 id", None, goal_id="goal_ok-1_2", root=root)
    assert made["ok"] is True


def test_get_goal_missing_and_corrupt(tmp_path):
    """不存在/损坏 goal 文件如实 ok=False（不猜不静默）。"""
    root = _goals_root(tmp_path)
    missing = get_goal("goal_nope", root=root)
    assert missing["ok"] is False and "不存在" in missing["errors"][0]
    root.mkdir(parents=True, exist_ok=True)
    (root / "goal_corrupt.json").write_text("{oops", encoding="utf-8")
    corrupt = get_goal("goal_corrupt", root=root)
    assert corrupt["ok"] is False
    listed = list_goals(root=root)
    assert listed["ok"] and listed["unreadable"] == ["goal_corrupt.json"]


# ─── ④ campaign 适配层（done_when 引用 campaign verdict；零回写）───────────────

def _make_campaign_plan(camp_dir: Path) -> Path:
    """最小三阶段战役计划落盘（campaign 本体原样，零重构）。"""
    plan = {
        "model": "w5c_campaign",
        "recipe": "recipes/w5c_placeholder.yaml",
        "stages": [
            {"stage": "calibrate", "kind": "calibrate", "status": "pending"},
            {"stage": "tune", "kind": "tune", "status": "pending"},
            {"stage": "report", "kind": "report", "status": "pending"},
        ],
    }
    return save_plan(plan, camp_dir)


def test_campaign_adapter_verdict_criteria(tmp_path):
    """goal.done_when 引用 campaign verdict：RUNNING→advancing，
    apply_event 全阶段 done（verdict=COMPLETE）→ 再 advance → done。"""
    camp_dir = tmp_path / "camp"
    plan_path = _make_campaign_plan(camp_dir)
    root = _goals_root(tmp_path)
    made = set_goal(
        "战役收官（verdict=COMPLETE）",
        {"kind": "campaign_verdict", "value": "COMPLETE"},
        campaign_plan=str(camp_dir),
        goal_id="goal_w5c_camp",
        root=root)
    assert made["ok"], made.get("errors")

    evidence = campaign_evidence(plan_path)
    assert evidence["campaign_plan_readable"] is True
    assert evidence["campaign_verdict"] in ("RUNNING", None)

    adv1 = advance_goal("goal_w5c_camp", root=root)   # 缺省证据=适配层
    assert adv1["ok"] and adv1["status"] == "advancing"
    assert adv1["criteria_met"] is False

    # campaign 本体状态机原样推进（goal 域零回写 campaign 计划）
    loaded = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    for stage in ("calibrate", "tune", "report"):
        got = apply_event(loaded, stage, "stage_done")
        assert got["ok"], got.get("errors")
    assert got["verdict"] == "COMPLETE"
    save_plan(loaded, camp_dir)

    adv2 = advance_goal("goal_w5c_camp", root=root)
    assert adv2["ok"] and adv2["status"] == "done"
    assert adv2["criteria_met"] is True
    assert get_goal("goal_w5c_camp", root=root)["goal"]["status"] == "done"


def test_campaign_adapter_unreadable_plan_degrades(tmp_path):
    """计划不可读→证据如实落空（campaign_verdict=None，判据未达不猜）。"""
    ev = campaign_evidence(tmp_path / "__no_plan__")
    assert ev["campaign_plan_readable"] is False
    assert ev["campaign_verdict"] is None


# ─── ③ CLI goal 子应用（--help/--json 双路径）────────────────────────────────

def test_goal_cli_help_all_leaves():
    """goal 子应用与四叶 --help 全 rc=0（help 源文本卫生由常驻门扫描）。"""
    top = runner.invoke(goal_app, ["--help"])
    assert top.exit_code == 0
    for leaf in ("set", "status", "advance", "list"):
        got = runner.invoke(goal_app, [leaf, "--help"])
        assert got.exit_code == 0, (leaf, got.output)


def test_goal_cli_json_dual_path(tmp_path):
    """四叶 --json 双路径：set→advance(done)→status→list 成功信封 +
    status 缺席失败信封同构（errors 恒 list[str]）。"""
    root = _goals_root(tmp_path)
    spec = json.dumps({"kind": "flag_equal", "key": "done", "value": True})
    ev_file = tmp_path / "evidence.json"
    ev_file.write_text(json.dumps({"done": True}), encoding="utf-8")

    got_set = runner.invoke(
        goal_app,
        ["set", "CLI 立标", "--done-when", spec, "--goal-id",
         "goal_w5c_cli", "--max-rounds", "3", "--root", str(root), "--json"])
    assert got_set.exit_code == 0, got_set.output
    out = json.loads(got_set.output)
    assert out["ok"] is True and out["goal_id"] == "goal_w5c_cli"

    got_adv = runner.invoke(
        goal_app,
        ["advance", "goal_w5c_cli", "--evidence-file", str(ev_file),
         "--root", str(root), "--json"])
    assert got_adv.exit_code == 0, got_adv.output
    out = json.loads(got_adv.output)
    assert out["ok"] is True and out["status"] == "done"

    got_status = runner.invoke(
        goal_app, ["status", "goal_w5c_cli", "--root", str(root), "--json"])
    assert got_status.exit_code == 0
    out = json.loads(got_status.output)
    assert out["goal"]["status"] == "done"

    got_list = runner.invoke(goal_app, ["list", "--root", str(root), "--json"])
    assert got_list.exit_code == 0
    out = json.loads(got_list.output)
    ids = [g["goal_id"] for g in out["goals"]]
    assert "goal_w5c_cli" in ids and out["n_goals"] >= 1

    # 失败路径：缺席目标 status → rc≠0 + 失败信封同构（errors 列表）
    got_miss = runner.invoke(
        goal_app, ["status", "goal_absent", "--root", str(root), "--json"])
    assert got_miss.exit_code != 0
    out = json.loads(got_miss.output)
    assert out["ok"] is False and isinstance(out["errors"], list)
    assert out["errors"]


def test_goal_cli_advance_without_evidence_blocks(tmp_path):
    """CLI advance 无证据文件且 goal 未声明 campaign_plan → 空证据如实
    blocked（不猜不伪造达标）。"""
    root = _goals_root(tmp_path)
    runner.invoke(goal_app, ["set", "无证据目标", "--goal-id", "goal_w5c_noev",
                             "--root", str(root), "--json"])
    got = runner.invoke(goal_app, ["advance", "goal_w5c_noev",
                                   "--root", str(root), "--json"])
    assert got.exit_code == 0
    out = json.loads(got.output)
    assert out["status"] == "blocked" and out["criteria_met"] is False


def test_goal_cli_human_path(tmp_path):
    """非 --json 人读路径 rc=0（四叶各一冒烟；富文本面不炸即过）。"""
    root = _goals_root(tmp_path)
    assert runner.invoke(goal_app, ["set", "人读立标", "--goal-id",
                                    "goal_w5c_human", "--root", str(root)]
                         ).exit_code == 0
    assert runner.invoke(goal_app, ["status", "goal_w5c_human",
                                    "--root", str(root)]).exit_code == 0
    assert runner.invoke(goal_app, ["advance", "goal_w5c_human",
                                    "--root", str(root)]).exit_code == 0
    assert runner.invoke(goal_app, ["list", "--root", str(root)]).exit_code == 0
