"""fd_oe_campaign --remote 路由（v1 调度面+执行通道接线）离线单测（全 mock
零网络零求解零真机）。

覆盖：argparse 形态（裸/带值/缺省 None）、remote_seat_gate 多态（预检
FAIL=fail-skip / 通道未提供=SKIP 如实 / 通道 skipped=候跑 SKIP / 通道
FAIL / 通道 ok=判读 pending+solve_success）、main 接线（chdir 隔离防污染
真实 runs/，#144：预检 fail-skip、通道 ok 产物回拉判读 PASS/PARTIAL、通道
skipped/FAIL 如实记账）、缺省 local 零变化钉（零预检零通道调用）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "fd_oe_campaign.py"

TEMPLATE = "fake_t"


def _load():
    spec = importlib.util.spec_from_file_location("fd_oe_campaign", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _ok_envelope(**kw):
    env = {"ok": True, "verdict": "PASS", "skipped": False, "launched": True,
           "reason": None, "machine": "sim_host", "batch": "oe_ab12cd34",
           "task_dir_remote": "E:\\rfauto_remote\\tasks\\oe_ab12cd34",
           "out_dir_local": "runs/ge_fd/fake_t", "exec_rc": 0,
           "wait_mode": "sync", "criteria": {}, "steps": {}}
    env.update(kw)
    return env


def _patch_render(monkeypatch, params_seen=None):
    import rfauto.adapters.openems_templates as ot

    def _render(template, params, band, mesh_resolution_mm=0.0):
        if params_seen is not None:
            params_seen.append(dict(params))
        lines = [f"# {template} auto"]
        for k in sorted(params):
            lines.append(f"{k} = {params[k]!r}")
        return "\n".join(lines)

    monkeypatch.setattr(ot, "TEMPLATE_META",
                        {TEMPLATE: {"f0_ghz": 5.8, "mesh_resolution_mm": 0.4}})
    monkeypatch.setattr(ot, "TEMPLATE_NOMINAL", {TEMPLATE: {"a_mm": 1.0}})
    monkeypatch.setattr(ot, "render_script", _render)


# ─── argparse 形态 ────────────────────────────────────────────────────────

def test_parse_args_remote_forms():
    """--remote 三形态：缺省 None（=local 零变化）、裸（=唯一登记机器）、
    带值（=显式机器名）。"""
    assert mod._parse_args([]).remote is None
    assert mod._parse_args(["--remote"]).remote == ""
    assert mod._parse_args(["--remote", "sim_host"]).remote == "sim_host"


def test_parse_args_local_flags_unchanged():
    """既有旗标缺省逐字节不变（零变化面）。"""
    a = mod._parse_args(["--only", "ms_patch", "--timeout", "99"])
    assert a.only == "ms_patch" and a.timeout == 99.0
    assert a.nrts == 0 and a.end_criteria == 0.0


# ─── remote_seat_gate 多态 ────────────────────────────────────────────────

def test_remote_seat_gate_preflight_fail_skips():
    """预检 FAIL → SKIP（fail-skip 不硬打），信封随增量 dict 落账；
    执行通道不发起（零 execute_fn 调用）。"""
    calls: list = []

    def _pf(machine):
        calls.append(machine)
        return {"verdict": "FAIL", "reason": "license 端口不可达"}

    def _boom(m, s):
        raise AssertionError("预检未过不得发起远程执行")

    out = mod.remote_seat_gate("sim_host", _pf, execute_fn=_boom,
                               seat_spec={"template": "x"})
    assert calls == ["sim_host"]
    assert out["status"] == "SKIP"
    assert "fail-skip" in out["reason"] and "不硬打" in out["reason"]
    assert out["license_preflight"]["verdict"] == "FAIL"
    assert out["remote"]["machine"] == "sim_host"
    assert out["remote"]["routed"] is True


def test_remote_seat_gate_pass_without_channel_skips_honestly():
    """预检 PASS 但 execute_fn/seat_spec 缺 → SKIP 如实（通道未提供，
    不假绿不冒充远程执行）。"""
    out = mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None})
    assert out["status"] == "SKIP"
    assert "通道未提供" in out["reason"]
    assert out["remote"]["exec_channel"].startswith("remote_oe_service")
    assert out["license_preflight"]["verdict"] == "PASS"


def test_remote_seat_gate_channel_skipped_is_seat_skip():
    """通道 skipped（互斥命中候跑/env 门）→ 座位 SKIP，未发射如实记账。"""
    def _run(m, s):
        return _ok_envelope(ok=False, skipped=True, launched=False,
                            reason="互斥命中 1 例=候跑（#261，禁止代杀）")

    out = mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None},
        execute_fn=_run, seat_spec={"template": "fake_t"})
    assert out["status"] == "SKIP"
    assert "候跑" in out["reason"] and "未发射" in out["reason"]
    assert out["remote_exec"]["skipped"] is True
    assert out["remote_exec"]["launched"] is False


def test_remote_seat_gate_channel_fail_is_seat_fail():
    """通道失败（SSH/回拉/清理）→ 座位 FAIL（已发射如实记败不假绿）。"""
    def _run(m, s):
        return _ok_envelope(ok=False, verdict="FAIL", exec_rc=None,
                            reason="服务器侧任务目录清理未通过")

    out = mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None},
        execute_fn=_run, seat_spec={"template": "fake_t"})
    assert out["status"] == "FAIL"
    assert "远程执行通道失败" in out["reason"]
    assert "清理" in out["reason"]


def test_remote_seat_gate_channel_ok_judgment_pending():
    """通道 ok → 不落 status（判读共用尾定 PASS/FAIL/PARTIAL）；
    solve_success=（exec_rc==0）随增量落档（rc≠0=判读降档口径）。"""
    def _run(m, s):
        return _ok_envelope()

    out = mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None},
        execute_fn=_run, seat_spec={"template": "fake_t"})
    assert "status" not in out
    assert out["solve_success"] is True
    assert out["remote_exec"]["exec_rc"] == 0
    assert out["remote_exec"]["task_dir_remote"].endswith("oe_ab12cd34")

    out2 = mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None},
        execute_fn=lambda m, s: _ok_envelope(exec_rc=3, verdict="PARTIAL"),
        seat_spec={"template": "fake_t"})
    assert "status" not in out2
    assert out2["solve_success"] is False


def test_remote_seat_gate_passes_seat_spec_through():
    seen: dict = {}

    def _run(m, s):
        seen["machine"], seen["spec"] = m, s
        return _ok_envelope()

    mod.remote_seat_gate(
        "sim_host", lambda m: {"verdict": "PASS", "reason": None},
        execute_fn=_run, seat_spec={"template": "fake_t", "timeout_s": 99.0})
    assert seen["machine"] == "sim_host"
    assert seen["spec"]["template"] == "fake_t"
    assert seen["spec"]["timeout_s"] == 99.0


# ─── _resolve_remote_machine ──────────────────────────────────────────────

def test_resolve_remote_machine_bare_and_named(monkeypatch):
    import rfauto.infra.remote_machines as rm

    cfg = rm.RemoteMachineConfig(name="sim_host", host="1.2.3.4")
    monkeypatch.setattr(rm, "load_remote_machines", lambda: {"sim_host": cfg})
    assert mod._resolve_remote_machine("") == "sim_host"      # 裸=唯一机器
    assert mod._resolve_remote_machine("sim_host") == "sim_host"


def test_resolve_remote_machine_errors(monkeypatch):
    import rfauto.infra.remote_machines as rm

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {})
    try:
        mod._resolve_remote_machine("")
        raised = False
    except ValueError:
        raised = True
    assert raised                                               # 空注册表
    monkeypatch.setattr(
        rm, "load_remote_machines", lambda: {
            "a": rm.RemoteMachineConfig(name="a", host="h"),
            "b": rm.RemoteMachineConfig(name="b", host="h")})
    try:
        mod._resolve_remote_machine("")                          # 歧义
        raised = False
    except ValueError:
        raised = True
    assert raised


# ─── main 接线（chdir 隔离，#144：绝不污染真实 runs） ─────────────────────

def test_main_remote_gate_end_to_end(tmp_path, monkeypatch):
    """--remote 接线：注册模板在 G1 渲染之后被预检门 SKIP（fail-closed），
    预检信封随 verdict 落档；零渲染上传零求解零网络。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm

    cfg = rm.RemoteMachineConfig(name="sim_host", host="1.2.3.4")
    monkeypatch.setattr(rm, "load_remote_machines", lambda: {"sim_host": cfg})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "FAIL",
                                   "reason": "license 端口不可达"})

    def _boom(m, s):
        raise AssertionError("预检未过不得发起远程执行")

    monkeypatch.setattr(mod, "_remote_oe_run", _boom)
    # H1-5：单座 SKIP → rc 3（修复前恒 0，全座 SKIP 曾被记成链成功）。
    rc = mod.main(["--only", TEMPLATE, "--remote", "sim_host"])
    assert rc == 3
    v = json.loads((tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json")
                   .read_text(encoding="utf-8"))
    assert v["status"] == "SKIP"
    assert "fail-skip" in v["reason"]
    assert v["license_preflight"]["verdict"] == "FAIL"
    assert v["remote"]["machine"] == "sim_host"
    assert v["g1_render"] is True                     # G1 渲染在本地先走
    s = json.loads((tmp_path / "runs" / "ge_fd" / "campaign_summary.json")
                   .read_text(encoding="utf-8"))
    assert s[TEMPLATE]["status"] == "SKIP"
    s = json.loads((tmp_path / "runs" / "ge_fd" / "campaign_summary.json")
                   .read_text(encoding="utf-8"))
    assert s[TEMPLATE]["status"] == "SKIP"


def test_main_remote_channel_ok_products_judged(tmp_path, monkeypatch):
    """--remote 全链：本地渲染→通道 ok（fake 写回 sparams.csv 到回拉目录）
    →判读共用尾按 disk 收割定 PASS（sparams_source=disk_harvest）；
    座位随行判据（criteria_md）随 seat_spec 落账（#122 判据先行）。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm
    import rfauto.service.health_service as hs

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {
        "sim_host": rm.RemoteMachineConfig(name="sim_host", host="h")})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "PASS", "reason": None})
    seen: dict = {}

    def _fake_channel(machine, seat_spec):
        seen["machine"] = machine
        seen["spec"] = dict(seat_spec)
        pull = tmp_path / "runs" / seat_spec["campaign"] / seat_spec["template"]
        pull.mkdir(parents=True, exist_ok=True)
        (pull / "sparams.csv").write_text(
            "freq,re_s11,im_s11\n2.3e9,0.10,0.01\n2.4e9,0.11,0.02\n"
            "2.5e9,0.12,0.03\n", encoding="utf-8")
        return _ok_envelope(out_dir_local=str(pull))

    monkeypatch.setattr(mod, "_remote_oe_run", _fake_channel)
    monkeypatch.setattr(hs, "health_check_run",
                        lambda name, runs_dir=None: {"verdict": "skip",
                                                     "ok": True})
    rc = mod.main(["--only", TEMPLATE, "--remote", "sim_host"])
    assert rc == 0
    assert seen["machine"] == "sim_host"
    assert seen["spec"]["template"] == TEMPLATE
    assert seen["spec"]["simulation_py"].startswith(f"# {TEMPLATE} auto")
    assert "criteria" in seen["spec"]["criteria_md"]     # 判据先行随座
    assert seen["spec"]["render_sha256"]
    v = json.loads((tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json")
                   .read_text(encoding="utf-8"))
    assert v["status"] == "PASS"
    assert v["sparams_source"] == "disk_harvest"
    assert v["solve_success"] is True
    assert v["remote_exec"]["ok"] is True
    assert v["remote"]["routed"] is True
    assert v["g1_render"] is True and v["g3_finite"] is True


def test_main_remote_channel_partial_rc_nonzero(tmp_path, monkeypatch):
    """通道 ok 但引擎 rc≠0（产物在）→ 判读按 solve_success=False 降档
    PARTIAL（「数值面健康，如超时截断」口径），不假绿。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm
    import rfauto.service.health_service as hs

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {
        "sim_host": rm.RemoteMachineConfig(name="sim_host", host="h")})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "PASS", "reason": None})

    def _fake_channel(machine, seat_spec):
        pull = tmp_path / "runs" / seat_spec["campaign"] / seat_spec["template"]
        pull.mkdir(parents=True, exist_ok=True)
        (pull / "sparams.csv").write_text(
            "freq,re_s11,im_s11\n2.3e9,0.10,0.01\n2.4e9,0.11,0.02\n"
            "2.5e9,0.12,0.03\n", encoding="utf-8")
        return _ok_envelope(exec_rc=124, verdict="PARTIAL")

    monkeypatch.setattr(mod, "_remote_oe_run", _fake_channel)
    monkeypatch.setattr(hs, "health_check_run",
                        lambda name, runs_dir=None: {"verdict": "skip",
                                                     "ok": True})
    # H1-5：PARTIAL 座位（引擎 rc≠0 产物在）→ rc 4（非 PASS 非 FAIL/SKIP）。
    assert mod.main(["--only", TEMPLATE, "--remote", "sim_host"]) == 4
    v = json.loads((tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json")
                   .read_text(encoding="utf-8"))
    assert v["status"] == "PARTIAL"
    assert "未正常结束" in v["reason"]
    assert v["solve_success"] is False
    assert v["remote_exec"]["exec_rc"] == 124


def test_main_remote_channel_busy_skips(tmp_path, monkeypatch):
    """通道 skipped（互斥候跑）→ 座位 SKIP 如实，不发射不假绿。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {
        "sim_host": rm.RemoteMachineConfig(name="sim_host", host="h")})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "PASS", "reason": None})
    monkeypatch.setattr(
        mod, "_remote_oe_run",
        lambda m, s: _ok_envelope(ok=False, skipped=True, launched=False,
                                  reason="互斥命中 1 例=候跑（#261）"))
    # H1-5：座位 SKIP（互斥候跑）→ rc 3（K-7 形态，修复前恒 0）。
    assert mod.main(["--only", TEMPLATE, "--remote", "sim_host"]) == 3
    v = json.loads((tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json")
                   .read_text(encoding="utf-8"))
    assert v["status"] == "SKIP"
    assert "候跑" in v["reason"] and "未发射" in v["reason"]
    assert v["remote_exec"]["launched"] is False


def test_main_remote_channel_fail_records(tmp_path, monkeypatch, capsys):
    """通道失败（回拉空/清理失败）→ 座位 FAIL 如实记账（已发射不假绿）；
    批尾日志行打规定格式（H1-5：seats=N pass=N skip=N fail=N rc=X）。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {
        "sim_host": rm.RemoteMachineConfig(name="sim_host", host="h")})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "PASS", "reason": None})
    monkeypatch.setattr(
        mod, "_remote_oe_run",
        lambda m, s: _ok_envelope(ok=False, verdict="FAIL",
                                  reason="服务器侧任务目录无可回拉产物"))
    # H1-5：座位 FAIL → rc 2（修复前恒 0）。
    rc = mod.main(["--only", TEMPLATE, "--remote", "sim_host"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "[fd] seats=1 pass=0 skip=0 fail=1 rc=2" in out, \
        "批尾日志行规定格式（H1-5）"
    v = json.loads((tmp_path / "runs" / "ge_fd" / TEMPLATE / "verdict.json")
                   .read_text(encoding="utf-8"))
    assert v["status"] == "FAIL"
    assert "远程执行通道失败" in v["reason"]
    assert "无可回拉产物" in v["reason"]


def test_main_remote_criteria_fallback_predeclared(tmp_path, monkeypatch):
    """runs/ge_fd/criteria.md 缺席时座位随行判据=确定性回退文本
    （G1..G5+nrts 门同口径，#122 判据先行不空转）。"""
    monkeypatch.chdir(tmp_path)
    _patch_render(monkeypatch)
    import rfauto.infra.remote_machines as rm

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {
        "sim_host": rm.RemoteMachineConfig(name="sim_host", host="h")})
    monkeypatch.setattr(mod, "_license_preflight",
                        lambda m: {"verdict": "PASS", "reason": None})
    seen: dict = {}

    def _fake_channel(machine, seat_spec):
        seen["criteria"] = seat_spec["criteria_md"]
        return _ok_envelope(ok=False, skipped=True, launched=False,
                            reason="互斥命中=候跑")

    monkeypatch.setattr(mod, "_remote_oe_run", _fake_channel)
    # H1-5：SKIP 座位 → rc 3（判据随座断言不变）。
    assert mod.main(["--only", TEMPLATE, "--remote", "sim_host"]) == 3
    assert "G5" in seen["criteria"] and "nrts_converged" in seen["criteria"]
    # 主判据在档时随座原文（优先级钉）
    (tmp_path / "runs" / "ge_fd").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "ge_fd" / "criteria.md").write_text(
        "# 主判据原文 MARKER\n", encoding="utf-8")
    seen.clear()
    assert mod.main(["--only", TEMPLATE, "--remote", "sim_host"]) == 3
    assert "MARKER" in seen["criteria"]


def test_main_default_local_zero_change(tmp_path, monkeypatch):
    """缺省（不带 --remote）零变化钉：零预检调用、未注册模板路径逐字节同
    旧 verdict 形态（template/started/status/reason 四键）。"""
    monkeypatch.chdir(tmp_path)

    def _boom(*a, **kw):
        raise AssertionError("缺省 local 不得发起 license 预检")

    monkeypatch.setattr(mod, "_license_preflight", _boom)
    monkeypatch.setattr(mod, "_remote_oe_run", _boom)
    # H1-5：未注册模板=SKIP 座 → rc 3（verdict 四键形态零变化钉保留）。
    assert mod.main(["--only", "no_such_template"]) == 3
    v = json.loads(
        (tmp_path / "runs" / "ge_fd" / "no_such_template" / "verdict.json")
        .read_text(encoding="utf-8"))
    assert set(v) == {"template", "started", "status", "reason"}
    assert v["status"] == "SKIP" and v["reason"] == "未注册模板"


def test_main_remote_bad_machine_is_launch_error(tmp_path, monkeypatch):
    """--remote 未登记机器 → 发射面异常 rc 1（H1-5 退出码表：战役未启动
    零座位，不进编排层；旧 parser.error→SystemExit 2 会与「座位 FAIL=2」
    双义，故改走 rc 1）。"""
    monkeypatch.chdir(tmp_path)
    import rfauto.infra.remote_machines as rm

    monkeypatch.setattr(rm, "load_remote_machines", lambda: {})
    rc = mod.main(["--only", "ms_patch", "--remote", "nope"])
    assert rc == 1
    assert rc == mod.EXIT_LAUNCH_ERROR
    assert not (tmp_path / "runs").exists()   # 编排层未启动
