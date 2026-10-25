"""campaign stage 级 --remote 发射路由（E62 席 2026-10-08）离线单测。

全离线（#139：预检/执行通道/日历一律 monkeypatch 桩钉死，零网络零真机
零求解；tmp 隔离 #144——plan/run_dir/cache/solve 锁全在 tmp_path）。

覆盖：stage_remote_decl 声明形态归一（缺省/true/机器名/dict/plan 级
campaign_remote_default 缺省、stage 声明优先）、remote_stage_gate 门序
（日历维护窗 blocked 不预检 / 预检 fail-skip / 通道缺如实 SKIP / 通道
skipped / 通道 FAIL / 通道 ok）、座位载荷解析（内联文本/文件路径/缺省
timeout+campaign）、run_campaign 接线（路由 SKIP=inconclusive→视图
pending、通道 ok=done、本机零变化钉、信封/日志落座位目录）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.campaign_executor as ce
from rfauto.service.campaign_executor import (
    CAMPAIGN_EXECUTORS,
    CAMPAIGN_KINDS,
    REMOTE_STAGE_FILE,
    STAGE_RESULT_FILE,
    remote_stage_gate,
    run_campaign,
    stage_remote_decl,
)
from rfauto.service.campaign_manager import PLAN_FILE_NAME, save_plan

NODE = {"node_id": "tune", "stage_extra": {}}


def _pf_pass(machine):
    return {"ok": True, "verdict": "PASS", "machine": machine, "reason": None}


def _pf_fail(machine):
    return {"ok": False, "verdict": "FAIL", "machine": machine,
            "reason": "license 端口不可达"}


def _ok_channel(machine, seat_spec):
    return {"ok": True, "verdict": "PASS", "skipped": False, "launched": True,
            "machine": machine, "batch": "oe_ab12cd34",
            "task_dir_remote": "E:\\rfauto_remote\\tasks\\oe_ab12cd34",
            "out_dir_local": str(seat_spec.get("out_dir_hint") or ""),
            "exec_rc": 0, "wait_mode": "sync", "reason": None}


# ─── stage_remote_decl 声明形态 ──────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    (None, None), (False, None), ("", None),
    (True, {"machine": None}),
    ("sim_server", {"machine": "sim_server"}),
    ("  sim_server  ", {"machine": "sim_server"}),
    ({"machine": "sim_server", "wait_mode": "poll", "keep_remote": True},
     {"machine": "sim_server", "wait_mode": "poll", "keep_remote": True}),
    ({"machine": True}, {"machine": None}),
])
def test_stage_remote_decl_forms(raw, expect):
    node = {"node_id": "tune", "stage_extra": {"remote": raw}}
    assert stage_remote_decl(node) == expect


def test_stage_remote_decl_absent_is_none():
    assert stage_remote_decl({"node_id": "tune", "stage_extra": {}}) is None


def test_stage_remote_decl_plan_default_fallback_and_priority():
    # plan 级缺省（campaign_remote_default）在场 → 缺省路由
    node = {"node_id": "tune",
            "stage_extra": {"campaign_remote_default": "sim_server"}}
    assert stage_remote_decl(node) == {"machine": "sim_server"}
    # stage 级声明优先：stage remote=False 压掉 plan 级缺省
    node["stage_extra"]["remote"] = False
    assert stage_remote_decl(node) is None


# ─── remote_stage_gate 门序 ─────────────────────────────────────────────────

def _gate_boom(*_a, **_k):
    raise AssertionError("门序前置 blocked 时预检/通道不得被触达")


def test_gate_calendar_blocked_skips_without_preflight():
    gate = remote_stage_gate(
        {"machine": "sim_server"},
        preflight_fn=_gate_boom,
        calendar={"state": "blocked", "launchable": False, "loaded": True,
                  "windows_hit": ["maintenance_windows[0] 01:00-03:00"]},
        execute_fn=_gate_boom, seat_spec={"template": "t"})
    assert gate["status"] == "SKIP"
    assert "维护窗" in gate["reason"]
    assert "license_preflight" not in gate


def test_gate_preflight_fail_is_skip():
    gate = remote_stage_gate(
        {"machine": "sim_server"}, preflight_fn=_pf_fail,
        calendar={"state": "open", "launchable": True, "loaded": True})
    assert gate["status"] == "SKIP"
    assert gate["license_preflight"]["verdict"] == "FAIL"
    assert "不硬打" in gate["reason"]


def test_gate_backup_risk_passes_to_preflight():
    gate = remote_stage_gate(
        {"machine": "sim_server"}, preflight_fn=_pf_fail,
        calendar={"state": "risk", "launchable": True, "loaded": True,
                  "backup_risk": True,
                  "windows_hit": ["backup_windows[0] 02:50-05:35"]})
    # 备份窗=risk 落账放行（进预检），不 SKIP 不阻断
    assert gate["license_preflight"]["verdict"] == "FAIL"
    assert gate["calendar"]["backup_risk"] is True


def test_gate_missing_channel_skips_honestly():
    gate = remote_stage_gate({"machine": None}, preflight_fn=_pf_pass,
                             calendar={"state": "open"})
    assert gate["status"] == "SKIP"
    assert "不假绿" in gate["reason"] and "拆批余件" in gate["reason"]


def test_gate_channel_skipped_is_skip():
    calls = {}

    def _chan(machine, seat):
        calls["machine"] = machine
        return {"ok": False, "skipped": True, "launched": False,
                "reason": "互斥命中候跑"}

    gate = remote_stage_gate({"machine": "sim_server"},
                             preflight_fn=_pf_pass,
                             calendar={"state": "open"},
                             execute_fn=_chan, seat_spec={"template": "t"})
    assert gate["status"] == "SKIP"
    assert calls["machine"] == "sim_server"
    assert "候跑" in gate["reason"]


def test_gate_channel_fail_is_fail():
    gate = remote_stage_gate(
        {"machine": "sim_server"}, preflight_fn=_pf_pass,
        calendar={"state": "open"},
        execute_fn=lambda m, s: {"ok": False, "skipped": False,
                                 "launched": True, "reason": "SSH 链路失败"},
        seat_spec={"template": "t"})
    assert gate["status"] == "FAIL"
    assert "SSH" in gate["reason"]


def test_gate_channel_ok_records_solve_success():
    gate = remote_stage_gate(
        {"machine": "sim_server"}, preflight_fn=_pf_pass,
        calendar={"state": "open"},
        execute_fn=lambda m, s: _ok_channel(m, s), seat_spec={"template": "t"})
    assert "status" not in gate
    assert gate["solve_success"] is True
    assert gate["verdict"] == "PASS"
    assert gate["remote_exec"]["exec_rc"] == 0


# ─── 座位载荷解析 ────────────────────────────────────────────────────────────

def test_seat_payload_inline_and_defaults(tmp_path):
    node = {"node_id": "tune", "stage_extra": {"remote_seat": {
        "template": "patch",
        "simulation_py": "# inline script\nx = 1\n",
        "criteria_md": "# criteria\n"}}}
    ctx = {"run_dir": str(tmp_path / "runs" / "camp")}
    seat, err = ce._resolve_seat_payload({}, node, ctx)
    assert err is None
    assert seat["simulation_py"].startswith("# inline")
    assert seat["timeout_s"] == 2400.0
    assert seat["campaign"] == "camp"


def test_seat_payload_from_file_paths(tmp_path):
    sim = tmp_path / "simulation.py"
    sim.write_text("# from file\n", encoding="utf-8")
    crit = tmp_path / "criteria.md"
    crit.write_text("# from file crit\n", encoding="utf-8")
    node = {"node_id": "tune", "stage_extra": {"remote_seat": {
        "template": "patch", "simulation_py": "simulation.py",
        "criteria_md": str(crit), "timeout_s": 600}}}
    seat, err = ce._resolve_seat_payload(
        {}, node, {"run_dir": str(tmp_path)})
    assert err is None
    assert seat["simulation_py"] == "# from file\n"
    assert seat["criteria_md"] == "# from file crit\n"
    assert seat["timeout_s"] == 600.0


def test_seat_payload_decl_seat_overrides_and_absent_is_none():
    node = {"node_id": "tune", "stage_extra": {"remote_seat": {
        "template": "a", "simulation_py": "x", "criteria_md": "y"}}}
    seat, err = ce._resolve_seat_payload(
        {"seat": {"template": "b", "simulation_py": "x2", "criteria_md": "y2"}},
        node, {"run_dir": "."})
    assert err is None and seat["template"] == "b"
    # 未声明座位载荷 → (None, None)（gate 走「通道未提供」SKIP 分支）
    assert ce._resolve_seat_payload({}, NODE, {"run_dir": "."}) == (None, None)


# ─── run_campaign 接线（tmp 隔离，#144） ────────────────────────────────────

def _fake_executors():
    def _mk(kind):
        def _exec(node, ctx):
            return dict(ok=True, outputs=[], wall_s=0.0,
                        message=f"{kind} fake")
        return _exec
    return {k: _mk(k) for k in CAMPAIGN_KINDS}


def _plan_dir(tmp_path, tune_extra=None, plan_level_remote=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "model: mline\nobjectives:\n  - metric: s11_db\n"
        "    op: max_below\n    value: -10.0\nlimits:\n  max_trials: 30\n",
        encoding="utf-8")
    stages = [
        {"stage": "calibrate", "kind": "calibrate", "adapter": "fake",
         "depends_on": [], "status": "pending", "budget": 3,
         "license_gated": False, "entry": "rfauto calibrate recipe.yaml",
         "note": ""},
        {"stage": "tune", "kind": "tune", "adapter": "fake",
         "depends_on": ["calibrate"], "status": "pending", "budget": 3,
         "license_gated": False, "entry": "rfauto tune recipe.yaml",
         "note": ""},
    ]
    if tune_extra:
        stages[1].update(tune_extra)
    plan = {"ok": True, "recipe": str(recipe), "model": "mline",
            "stages": stages,
            "campaign_schema": "rfauto-campaign-plan-v1.1"}
    if plan_level_remote is not None:
        plan["remote"] = plan_level_remote
    camp = tmp_path / "runs" / "camp"
    camp.mkdir(parents=True, exist_ok=True)
    save_plan(plan, camp)
    return camp


def _run(tmp_path, camp, **kw):
    kw.setdefault("executors", _fake_executors())
    kw.setdefault("solve_lock_path", tmp_path / "solve.lock")
    kw.setdefault("cache_dir", tmp_path / "cache")
    return run_campaign(str(camp), **kw)


def _node_status(camp, node_id):
    state = json.loads(
        (camp / "dag.state.json").read_text(encoding="utf-8"))
    return (state["nodes"].get(node_id) or {}).get("status")


@pytest.fixture(autouse=True)
def _boom_unstubbed_channels(monkeypatch):
    """缺省把未桩的网络面钉爆：任何意外触达=测试失败（零网络零真机）。"""
    def _boom(*_a, **_k):
        raise AssertionError("网络面未桩即被触达（#139 红线）")
    monkeypatch.setattr(ce, "_license_preflight", _boom)
    monkeypatch.setattr(ce, "_remote_oe_run", _boom)
    monkeypatch.setattr(ce, "_calendar_launch_view",
                        lambda: {"loaded": False, "state": "open",
                                 "launchable": True})


def test_local_zero_change_no_remote_touch(tmp_path):
    """本机路径零变化钉：无 remote 声明 → 预检/日历/通道零触达，全绿。"""
    camp = _plan_dir(tmp_path)
    res = _run(tmp_path, camp)
    assert res["ok"] is True and res["verdict"] == "COMPLETE"
    assert _node_status(camp, "tune") == "done"
    assert not (camp / "tune" / REMOTE_STAGE_FILE).exists()


def test_route_preflight_fail_skip_is_inconclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_license_preflight", _pf_fail)
    camp = _plan_dir(tmp_path, tune_extra={"remote": "sim_server"})
    res = _run(tmp_path, camp)
    # PARTIAL（inconclusive 不冒充完成；战役未死=ok True 信封 + verdict PARTIAL）
    assert res["ok"] is True
    assert res["verdict"] == "PARTIAL"
    assert _node_status(camp, "tune") == "inconclusive"
    view = {r["stage"]: r for r in res["stage_view"]}
    assert view["tune"]["status"] == "pending"  # 续跑重探语义
    work = camp / "tune"
    gate = json.loads((work / REMOTE_STAGE_FILE).read_text(encoding="utf-8"))
    assert gate["status"] == "SKIP"
    assert gate["license_preflight"]["verdict"] == "FAIL"
    assert gate["remote"]["machine"] == "sim_server"
    slim = json.loads((work / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
    assert slim["ok"] is True
    assert slim["license_preflight"]["verdict"] == "FAIL"
    log = (camp / "campaign.log").read_text(encoding="utf-8")
    assert "[remote] tune" in log and "SKIP" in log


def test_route_calendar_blocked_no_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ce, "_calendar_launch_view",
        lambda: {"loaded": True, "state": "blocked", "launchable": False,
                 "windows_hit": ["maintenance_windows[0] 01:00-03:00"]})
    camp = _plan_dir(tmp_path, tune_extra={"remote": True})
    _run(tmp_path, camp)
    # 预检桩缺省是 boom——未触发即证明门序（日历 blocked 不预检）
    assert _node_status(camp, "tune") == "inconclusive"
    gate = json.loads((camp / "tune" / REMOTE_STAGE_FILE)
                      .read_text(encoding="utf-8"))
    assert gate["status"] == "SKIP" and "维护窗" in gate["reason"]
    assert "license_preflight" not in gate


def test_route_channel_ok_done_and_seat_dir(tmp_path, monkeypatch):
    seen = {}

    def _chan(machine, seat_spec):
        seen["machine"] = machine
        seen["seat"] = seat_spec
        return _ok_channel(machine, seat_spec)

    monkeypatch.setattr(ce, "_license_preflight", _pf_pass)
    monkeypatch.setattr(ce, "_remote_oe_run", _chan)
    camp = _plan_dir(tmp_path, tune_extra={
        "remote": "sim_server",
        "remote_seat": {"template": "patch",
                        "simulation_py": "# inline\n",
                        "criteria_md": "# crit\n"}})
    res = _run(tmp_path, camp)
    assert res["ok"] is True
    assert _node_status(camp, "tune") == "done"
    assert seen["machine"] == "sim_server"
    assert seen["seat"]["template"] == "patch"
    # 产物回拉落座位目录（out_dir=节点工作目录语义由通道承担；信封在此）
    work = camp / "tune"
    gate = json.loads((work / REMOTE_STAGE_FILE).read_text(encoding="utf-8"))
    assert gate["solve_success"] is True
    slim = json.loads((work / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
    assert slim["remote_exec"]["exec_rc"] == 0
    assert slim["solve_success"] is True


def test_route_no_seat_payload_skips_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_license_preflight", _pf_pass)
    camp = _plan_dir(tmp_path, tune_extra={"remote": "sim_server"})
    _run(tmp_path, camp)
    assert _node_status(camp, "tune") == "inconclusive"
    gate = json.loads((camp / "tune" / REMOTE_STAGE_FILE)
                      .read_text(encoding="utf-8"))
    assert gate["status"] == "SKIP"
    assert "拆批余件" in gate["reason"]


def test_plan_level_remote_flag_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_license_preflight", _pf_fail)
    camp = _plan_dir(tmp_path)
    res = _run(tmp_path, camp, remote="sim_server")
    assert _node_status(camp, "tune") == "inconclusive"
    # "true" 串归一缺省机器形态（CLI 传值形态）
    camp2 = _plan_dir(tmp_path / "b", plan_level_remote=None)
    res2 = _run(tmp_path / "b", camp2, remote="TRUE")
    assert _node_status(camp2, "tune") == "inconclusive"
    assert res["verdict"] == "PARTIAL" and res2["verdict"] == "PARTIAL"


def test_stage_decl_overrides_plan_level(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_license_preflight", _pf_fail)
    # plan 级缺省给出，但 stage 显式 remote=False → 本机（零触达预检）
    camp = _plan_dir(tmp_path, tune_extra={"remote": False},
                     plan_level_remote="sim_server")
    res = _run(tmp_path, camp)
    assert res["ok"] is True and _node_status(camp, "tune") == "done"


def test_route_registration_defaults_intact():
    """六件注册表缺省不被路由改造（注入缝契约零漂移）。"""
    assert set(CAMPAIGN_EXECUTORS) == set(CAMPAIGN_KINDS)
    assert all(fn is CAMPAIGN_EXECUTORS[k] for k, fn in CAMPAIGN_EXECUTORS.items())


def test_plan_file_name_untouched():
    assert PLAN_FILE_NAME == "campaign.plan.json"
