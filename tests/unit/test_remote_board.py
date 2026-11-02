"""remote board CLI 叶钉子测试（aurora_p G2 席，2026-11-02）。

对应验收（任务书冻结判据）：
A. 四源聚合单源零新探测（service 纯组合：机器行透传/队列行透传/降级归集
   逐键钉；四源 fake 注入全离线——#139 零真连网零真枚举）；
B. 缺省一次性动作零循环零写（信封逐字节同 service 直调；零线程增殖；
   零文件写）+ --refresh 循环优雅停（KI 注入+sleep 桩零悬挂）；
C. best-effort 降级钉（单源失败/子面 unknown → 降级行留痕整板不炸）；
D. 计数面（test_check_numbers/test_cli/注册序金快照各自守，本文件不重复钉）；
E. 既有 remote 叶钉零改动（test_remote_scheduler_service.py/
   test_remote_service.py 全绿；本文件不触 remote_service/
   remote_scheduler_service 任何实现文件）。

确定性红线钉：快照内时间字段（probed_at）=fake 源原值透传，board 不新造
时间戳——同 fake 注入两跑快照逐字节相等。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.infra.remote_machines import RemoteConfigError
from rfauto.service import remote_board_service as rbs
from rfauto.service.speculative_watch_service import MIN_INTERVAL_S

_runner = CliRunner()

# ── fake 四源（全离线注入面；值域固定=确定性钉的数据面） ─────────────────────

_HOST = "10.99.99.9"  # 只许出现在源信封（板面剥离——主机名不落信封钉）
_PROBED_AT = 1700000000.0  # fake 时间戳：透传原值钉（board 零新造时间戳）


def _fake_probe_env() -> dict:
    return {"ok": True, "machines": [{
        "name": "sim_server", "host": _HOST, "reachable": True,
        "probe_s": 0.01,
        "ports": {"rdp": {"port": 3389, "open": True, "latency_ms": 1.5}},
    }]}


def _fake_status_env() -> dict:
    return {"ok": True, "machines": [{
        "name": "sim_server", "host": _HOST, "reachable": True,
        "probe_s": 0.01,
        "ports": {"rdp": {"port": 3389, "open": True, "latency_ms": 1.5}},
        "ssh": {"auth": "ok", "rc": 0},
    }]}


def _face_ok(busy: bool, n: int) -> dict:
    return {"state": "ok", "busy": busy, "n_procs": n, "reason": None}


def _fake_queue_env() -> dict:
    return {
        "ok": True,
        "jobs": [
            {"job_id": "job_a", "state": "running", "run_id": "",
             "seats": ["solver:hfss"], "progress_pct": 40.0,
             "stage": "solve", "created_at": 123.0, "finished_at": None,
             "error": ""},
            {"job_id": "job_b", "state": "done", "run_id": "run_b",
             "seats": [], "progress_pct": 100.0, "stage": "",
             "created_at": 100.0, "finished_at": 150.0, "error": ""},
        ],
        "counts": {"n_jobs": 2, "n_active": 1, "n_waiting": 0},
        "write_lock": {"owner": None, "queue_length": 0},
        "seat_occupancy": {"solver:hfss": ["job_a"]},
        "remote": {
            "machine": "sim_server", "state": "ok", "reason": None,
            "reachable": True,
            "ports": {"rdp": {"open": True, "latency_ms": 1.5}},
            "ssh": {"auth": "registered"},
            "openems": _face_ok(busy=True, n=3),
            "hfss": _face_ok(busy=True, n=2),
            "disk": {"state": "ok", "free_gb": 100.0, "drive": "E:",
                     "reason": None},
            "n_tasks": 5, "probed_at": _PROBED_AT,
        },
    }


def _fake_mutex_env() -> dict:
    return {"openems": _face_ok(busy=False, n=0),
            "hfss": _face_ok(busy=False, n=0)}


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe=None,
    status=None,
    queue=None,
    mutex=None,
) -> None:
    """四源 fake 注入（不传的源用缺省 fake；传异常类/工厂按需抛）。"""
    monkeypatch.setattr(rbs, "_src_probe",
                        probe if probe is not None
                        else lambda m: _fake_probe_env())
    monkeypatch.setattr(rbs, "_src_status",
                        status if status is not None
                        else lambda m: _fake_status_env())
    monkeypatch.setattr(rbs, "_src_queue",
                        queue if queue is not None
                        else lambda m: _fake_queue_env())
    monkeypatch.setattr(rbs, "_src_local_mutex",
                        mutex if mutex is not None
                        else lambda m: _fake_mutex_env())


def _invoke(*args: str):
    from rfauto.cli.main import app

    return _runner.invoke(app, ["remote", "board", *args])


def _first_json(text: str) -> dict:
    return json.loads(text[text.index("{"):])


# ── A：四源聚合逐键（service 纯组合单源） ────────────────────────────────────


def test_board_snapshot_aggregates_four_sources(
    monkeypatch: pytest.MonkeyPatch,
):
    """四源 fake 注入：机器行透传/队列行透传/本机互斥/零降级逐键钉。"""
    _install_fakes(monkeypatch)
    snap = rbs.board_snapshot("sim_server")
    assert next(iter(snap)) == "ok" and snap["ok"] is True
    # 机器行=queue 源 remote 子面透传（含 probed_at 原值——零新造时间戳）
    assert snap["machines"] == [_fake_queue_env()["remote"]]
    assert snap["machines"][0]["probed_at"] == _PROBED_AT
    # 队列面瘦形透传
    assert snap["jobs"] == _fake_queue_env()["jobs"]
    assert snap["counts"] == {"n_jobs": 2, "n_active": 1, "n_waiting": 0}
    assert snap["write_lock"] == {"owner": None, "queue_length": 0}
    assert snap["seat_occupancy"] == {"solver:hfss": ["job_a"]}
    # 本机互斥面=mutex 源透传；happy path 零降级行
    assert snap["local_mutex"] == _fake_mutex_env()
    assert snap["degradations"] == []
    # 主机名/IP 不落信封（源信封里有 host，板面剥离）
    assert _HOST not in json.dumps(snap, ensure_ascii=False, default=str)


def test_board_snapshot_no_machine_local_mode(monkeypatch: pytest.MonkeyPatch):
    """无登记机器：machines=[]（空表如实）；no_machine 是合法态非降级。"""
    monkeypatch.setattr(rbs, "_src_probe", lambda m: {"ok": True, "machines": []})
    monkeypatch.setattr(rbs, "_src_status",
                        lambda m: {"ok": True, "machines": []})
    monkeypatch.setattr(rbs, "_src_queue", lambda m: {
        "ok": True, "jobs": [], "counts": {"n_jobs": 0, "n_active": 0,
                                           "n_waiting": 0},
        "write_lock": {"owner": None, "queue_length": 0},
        "seat_occupancy": {},
        "remote": {"machine": None, "state": "no_machine",
                   "reason": "无登记机器（本地模式）", "reachable": None,
                   "ports": {}, "ssh": None,
                   "openems": {"state": "unknown", "busy": None,
                               "n_procs": None, "reason": "无登记机器"},
                   "hfss": {"state": "unknown", "busy": None,
                            "n_procs": None, "reason": "无登记机器"},
                   "disk": {"state": "unknown", "free_gb": None,
                            "drive": None, "reason": "无登记机器"},
                   "n_tasks": None, "probed_at": _PROBED_AT}})
    monkeypatch.setattr(rbs, "_src_local_mutex", lambda m: _fake_mutex_env())
    snap = rbs.board_snapshot(None)
    assert snap["ok"] is True
    assert snap["machines"] == []
    assert snap["degradations"] == [], "无登记机器≠降级（合法本地模式）"


def test_unknown_machine_error_envelope(monkeypatch: pytest.MonkeyPatch):
    """未登记机器名（RemoteConfigError）→ error 信封（既有叶同语义）。"""

    def _raise(_m):
        raise RemoteConfigError("远程机器 'ghost' 未登记（可用：sim_server）")

    _install_fakes(monkeypatch, probe=_raise, status=_raise, queue=_raise,
                   mutex=_raise)
    snap = rbs.board_snapshot("ghost")
    assert snap["ok"] is False and snap["errors"]
    assert "ghost" in snap["errors"][0]


# ── C：best-effort 降级钉（单源失败不炸板） ──────────────────────────────────


def test_single_source_failure_degrades_not_blocks(
    monkeypatch: pytest.MonkeyPatch,
):
    """probe 源炸 → 降级行留痕，机器行/队列面照常出（#105 不炸板）。"""

    def _boom(_m):
        raise ConnectionError("net down")

    _install_fakes(monkeypatch, probe=_boom)
    snap = rbs.board_snapshot("sim_server")
    assert snap["ok"] is True, "单源失败不翻 ok（#105 观测面）"
    assert [d["source"] for d in snap["degradations"]] == ["probe"]
    assert "ConnectionError" in snap["degradations"][0]["reason"]
    assert snap["machines"] and snap["machines"][0]["machine"] == "sim_server"
    assert snap["counts"]["n_jobs"] == 2


def test_all_sources_failure_board_still_ok(monkeypatch: pytest.MonkeyPatch):
    """四源全炸（非注册表类）：整板 ok=True+四降级行+空机器表。"""

    def _boom(_m):
        raise RuntimeError("x")

    _install_fakes(monkeypatch, probe=_boom, status=_boom, queue=_boom,
                   mutex=_boom)
    snap = rbs.board_snapshot(None)
    assert snap["ok"] is True
    assert sorted(d["source"] for d in snap["degradations"]) == \
        ["mutex", "probe", "queue", "status"]
    assert snap["machines"] == []
    assert snap["jobs"] == []
    assert snap["local_mutex"]["openems"]["state"] == "unknown"


def test_queue_fallback_row_from_probe_status(monkeypatch: pytest.MonkeyPatch):
    """queue 源炸：机器行回落 probe/status 瘦组装（host 剥离+通道 unknown）。"""

    def _boom(_m):
        raise RuntimeError("registry gone")

    _install_fakes(monkeypatch, queue=_boom)
    snap = rbs.board_snapshot("sim_server")
    assert snap["ok"] is True
    assert snap["machines"], "回落组装仍出机器行"
    row = snap["machines"][0]
    assert row["machine"] == "sim_server"
    assert row["reachable"] is True
    assert "host" not in row, "回落路径同样零主机名"
    assert row["ssh"] == {"auth": "ok", "rc": 0}
    assert row["openems"]["state"] == "unknown" and row["n_tasks"] is None
    assert any(d["source"] == "queue" and d["face"] == "queue"
               for d in snap["degradations"])
    assert any(d["source"] == "queue" and d["face"] == "remote.openems"
               for d in snap["degradations"])


def test_remote_subface_unknown_degradation_rows(
    monkeypatch: pytest.MonkeyPatch,
):
    """queue remote 子面 unknown → 逐面降级行（机器在册才逐行）。"""
    qenv = _fake_queue_env()
    qenv["remote"]["openems"] = {"state": "unknown", "busy": None,
                                 "n_procs": None, "reason": "查询失败 rc=1"}
    qenv["remote"]["disk"] = {"state": "unknown", "free_gb": None,
                              "drive": "E:", "reason": "磁盘查询失败 rc=1"}
    qenv["remote"]["reachable"] = False
    qenv["remote"]["n_tasks"] = None
    qenv["remote"]["state"] = "unknown"
    qenv["remote"]["reason"] = "机器不可达（TCP 探活不通）"
    _install_fakes(monkeypatch, queue=lambda m: qenv)
    snap = rbs.board_snapshot("sim_server")
    faces = {(d["source"], d["face"]) for d in snap["degradations"]}
    assert ("queue", "remote.openems") in faces
    assert ("queue", "remote.disk") in faces
    for d in snap["degradations"]:
        if d["face"] == "remote.openems":
            assert "rc=1" in d["reason"]


def test_status_ssh_failed_degradation_row(monkeypatch: pytest.MonkeyPatch):
    """status SSH 认证失败 → 降级行（真实失败信号，不凑 ok 不静默）。"""
    senv = _fake_status_env()
    senv["machines"][0]["ssh"] = {"auth": "failed", "error": "TimeoutError"}
    _install_fakes(monkeypatch, status=lambda m: senv)
    snap = rbs.board_snapshot("sim_server")
    assert any(d["source"] == "status" and d["face"] == "ssh"
               and "TimeoutError" in d["reason"]
               for d in snap["degradations"])


def test_local_mutex_unknown_degradation_row(monkeypatch: pytest.MonkeyPatch):
    """本机通道枚举失败 → mutex 源降级行（#105 unknown 不阻塞）。"""
    menv = {"openems": {"state": "unknown", "busy": None, "n_procs": None,
                        "reason": "本机 python 进程枚举失败/超时"},
            "hfss": _face_ok(busy=False, n=0)}
    _install_fakes(monkeypatch, mutex=lambda m: menv)
    snap = rbs.board_snapshot("sim_server")
    assert any(d["source"] == "mutex" and d["face"] == "local.openems"
               for d in snap["degradations"])
    assert snap["local_mutex"]["openems"]["state"] == "unknown"


# ── 确定性红线（同 fake 注入两跑快照逐字节） ─────────────────────────────────


def test_snapshot_deterministic_two_runs(monkeypatch: pytest.MonkeyPatch):
    """同 fake 注入两跑：快照逐字节相等；时间戳=源原值（board 零新造）。"""
    _install_fakes(monkeypatch)
    a = json.dumps(rbs.board_snapshot("sim_server"), ensure_ascii=False,
                   sort_keys=False)
    b = json.dumps(rbs.board_snapshot("sim_server"), ensure_ascii=False,
                   sort_keys=False)
    assert a == b, "同 fake 数据快照必须逐字节相等（确定性红线）"
    assert str(_PROBED_AT) in a


# ── B：CLI 缺省一次性（零循环零写+service 直调逐字节同构） ───────────────────


def test_cli_one_shot_json_service_parity_zero_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """缺省动作钉：--json 信封与 service 直调逐位一致、零文件写、无线程。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    threads_before = threading.active_count()
    r = _invoke("--json")
    assert r.exit_code == 0, r.output[:400]
    assert threading.active_count() == threads_before
    assert list(tmp_path.rglob("*")) == [], "缺省一次性零文件写（看板零落盘）"
    cli_env = _first_json(r.output)
    direct = rbs.board_snapshot("sim_server")
    assert cli_env == direct, "缺省一次性动作必须逐字节同 service 直调语义"


def test_cli_one_shot_human_board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """人读分支：三面板渲染+机器名+零 MarkupError（escape 纪律）。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = _invoke()
    assert r.exit_code == 0, r.output[:400]
    assert "队列看板" in r.output
    assert "sim_server" in r.output
    assert "任务队列" in r.output
    assert "互斥态" in r.output


def test_cli_one_shot_error_envelope_exit_1(monkeypatch: pytest.MonkeyPatch):
    """error 信封（未登记机器）→ _emit 同构失败出口（--json exit 1）。"""

    def _raise(_m):
        raise RemoteConfigError("远程机器 'ghost' 未登记")

    _install_fakes(monkeypatch, probe=_raise, status=_raise, queue=_raise,
                   mutex=_raise)
    r = _invoke("--json")
    assert r.exit_code == 1
    payload = _first_json(r.output)
    assert payload["ok"] is False and payload["errors"]


def test_cli_usage_error_negative_refresh():
    """--refresh 负数 → usage 错误信封（exit 2，--json 下禁裸文本）。"""
    r = _invoke("--refresh", "-1", "--json")
    assert r.exit_code == 2
    payload = _first_json(r.output)
    assert payload["ok"] is False


def test_cli_json_out_without_json_flag(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch):
    """--json-out 独立于 --json（信封契约独立于 out 钉）：人读渲染+落盘并行。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "board_only.json"
    r = _invoke("--json-out", str(out))
    assert r.exit_code == 0, r.output[:400]
    assert "队列看板" in r.output, "无 --json 仍走人读渲染"
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap == rbs.board_snapshot("sim_server"), "落盘与 service 直调同构"


def test_cli_refresh_error_envelope_stops_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """循环态遇注册表类错误信封（未登记机器）即停 exit 1 不空转。"""

    def _raise(_m):
        raise RemoteConfigError("远程机器 'ghost' 未登记")

    _install_fakes(monkeypatch, probe=_raise, status=_raise, queue=_raise,
                   mutex=_raise)
    monkeypatch.chdir(tmp_path)
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s),
                        raising=True)
    r = _invoke("--refresh", "0", "--json")
    assert r.exit_code == 1
    payload = _first_json(r.output)
    assert payload["ok"] is False and payload["errors"]
    assert sleep_calls == [], "错误轮后不得再 sleep 空转"


# ── B：--refresh 循环（显式开启+优雅停+interval 下限单源） ───────────────────


def test_cli_refresh_loop_graceful_stop_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """短 interval+KI 注入：优雅停零悬挂、逐轮 JSONL+汇总信封、下限单源。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda s: None, raising=True)

    calls = {"n": 0}
    real_queue = _fake_queue_env

    def fake_queue(_m):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt
        return real_queue()

    monkeypatch.setattr(rbs, "_src_queue", fake_queue)

    threads_before = threading.active_count()
    r = _invoke("--refresh", "0", "--json")
    assert r.exit_code == 0, r.output[:400]
    assert threading.active_count() == threads_before, "零悬挂线程"
    assert list(tmp_path.rglob("*")) == [], "刷新形态缺省仍零落盘"

    objs = []
    dec = json.JSONDecoder()
    text = r.output[r.output.index("{"):]
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        obj, i = dec.raw_decode(text, i)
        objs.append(obj)
    assert len(objs) == 2, "逐轮 1 快照+汇总 1 信封"
    assert objs[0]["ok"] is True and "machines" in objs[0]
    summary = objs[1]
    assert summary["ok"] is True and summary["mode"] == "board-refresh"
    assert summary["interrupted"] is True
    assert summary["rounds_done"] == 1
    # interval 下限=service 家族 MIN_INTERVAL_S 单源（--refresh 0 被抬到下限）
    assert summary["interval_s"] == float(MIN_INTERVAL_S)


def test_cli_refresh_json_out_each_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """--json-out + --refresh：每轮覆写最新快照（外部消费者读最新态）。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("time.sleep", lambda s: None, raising=True)
    calls = {"n": 0}

    def fake_queue(_m):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt
        return _fake_queue_env()

    monkeypatch.setattr(rbs, "_src_queue", fake_queue)
    out = tmp_path / "nested" / "board.json"
    r = _invoke("--refresh", "0", "--json-out", str(out), "--json")
    assert r.exit_code == 0, r.output[:400]
    assert calls["n"] >= 2, "两轮采集（第二轮 KI 优雅停）"
    assert out.is_file()
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["ok"] is True and snap["machines"], "落盘=最新一轮快照"


# ── --json-out 往返 + 导出确定性 ─────────────────────────────────────────────


def test_cli_json_out_roundtrip_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """--json-out 往返：文件内容==stdout 信封；两跑导出逐字节相等。"""
    _install_fakes(monkeypatch)
    monkeypatch.chdir(tmp_path)
    out1 = tmp_path / "b1.json"
    r1 = _invoke("--json-out", str(out1), "--json")
    assert r1.exit_code == 0, r1.output[:400]
    file_env = json.loads(out1.read_text(encoding="utf-8"))
    assert file_env == _first_json(r1.output), "文件与 stdout 信封同构"

    out2 = tmp_path / "b2.json"
    r2 = _invoke("--json-out", str(out2), "--json")
    assert r2.exit_code == 0, r2.output[:400]
    assert out1.read_bytes() == out2.read_bytes(), "同 fake 两跑导出逐字节相等"

    # --json-out 命中 error 快照（未登记机器）也如实落盘后走失败出口
    def _raise(_m):
        raise RemoteConfigError("远程机器 'ghost' 未登记")

    _install_fakes(monkeypatch, probe=_raise, status=_raise, queue=_raise,
                   mutex=_raise)
    out3 = tmp_path / "b3.json"
    r3 = _invoke("--json-out", str(out3), "--json")
    assert r3.exit_code == 1
    assert json.loads(out3.read_text(encoding="utf-8"))["ok"] is False


# ── help 卫生（#305 家族）+ 注册面 ───────────────────────────────────────────


def test_leaf_help_renders_in_process():
    """--help 进程内渲染零崩（裸 [/MarkupError 即红）。"""
    r = _invoke("--help")
    assert r.exit_code == 0, r.output[:400]
    assert "队列看板" in r.output


def test_leaf_help_subprocess_hygiene():
    """子进程 --help 卫生（真 spawn 冒烟；stdout 面含看板语义）。"""
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "rfauto.cli.main", "remote", "board",
         "--help"],
        capture_output=True, text=True, timeout=120, cwd=str(repo))
    assert proc.returncode == 0, proc.stderr[:400]
    assert "队列看板" in proc.stdout


def test_board_leaf_registered_with_json_flag():
    """board 叶注册+带 --json（新叶必带旗标——棘轮门同口径邻接自证）。"""
    import inspect

    from rfauto.cli.main import app as root_app

    for g in root_app.registered_groups:
        if g.name == "remote":
            inst = getattr(g, "typer_instance", None) or g
            for info in inst.registered_commands:
                if info.name == "board":
                    sig = inspect.signature(info.callback)
                    assert "json_output" in sig.parameters
                    return
    raise AssertionError("remote board 叶未注册")


def test_board_sources_constant():
    """四源名常量钉（degradations.source 取值域；审计对照面）。"""
    assert rbs.BOARD_SOURCES == ("probe", "status", "queue", "mutex")
