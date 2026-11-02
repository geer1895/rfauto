"""devtest 投机执行档服务层钉子测试（T-O11，aurora_o）。

六项验收对应（任务书口径）：
①缓存命中：launch→finish→status 秒回 hit 且 failed_ids 与 summary 逐位一致
 （纯文件读零子进程——spawn 记录器断言零额外发射）；
②stale 如实：变更面加一文件后指纹过期，返回 stale 且不携带旧 summary 冒充；
③#261 互斥：census 命中/不可验证都 declined，spawn 记录器零调用（零 pytest 子进程）；
④缓存白名单钉：根越出 runs/devtest_speculative 拒绝、写面含 .. 拒绝（#144 反向钉）；
⑤确定性：同输入指纹逐位一致 + 同指纹二次触发幂等返回 cached 不重跑；
⑥负例：空变更 nothing_to_do。

全部进程/census/spawn/时钟面 monkeypatch 注入（零真机、零真 PS、零 sleep）；
缓存根一律 tmp_path/"runs/devtest_speculative"（白名单尾段校验通过），零
真实 runs/ 湖写（#144 家族：测试不 chdir 也不落假数据——写根显式注入）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

import rfauto.service.devtest_speculative_service as dss
from rfauto.service.devtest_speculative_service import (
    SpeculativeGuardError,
    classify_census_hits,
    compute_fingerprint,
    finish_run,
    guard_cache_path,
    local_census_command,
    parse_pytest_summary,
    run_speculative_child,
    speculative_run,
    speculative_status,
    strip_real_machine_tests,
    validate_cache_root,
)

_HEAD = "a" * 40
_DIGEST = "d" * 64
_CHANGED = ["src/rfauto/service/devtest_speculative_service.py"]
_TESTS = ["tests/unit/test_devtest_speculative.py"]


@pytest.fixture()
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "devtest_speculative"
    root.mkdir(parents=True)
    return root


def _launch(cache_root: Path, *, changed=None, tests=None,
            census=None, spawn_record=None, owner_pid=777, now=1000.0, **kwargs):
    """触发一轮（全注入）：spawn 记录 cmd 不真发；census 缺省=空闲。"""
    spawn_record = [] if spawn_record is None else spawn_record

    def fake_spawn(cmd, log_path):
        spawn_record.append((cmd, str(log_path)))
        return 424242

    env = speculative_run(
        changed if changed is not None else _CHANGED,
        tests=tests if tests is not None else _TESTS,
        head=_HEAD,
        map_digest=_DIGEST,
        cache_root=cache_root,
        census_fn=census if census is not None else (lambda: []),
        pid_alive_fn=lambda pid: False,
        spawn_fn=fake_spawn,
        owner_pid=owner_pid,
        now=now,
        **kwargs,
    )
    return env, spawn_record


def _summary_fp(cache_root: Path) -> str:
    return json.loads((cache_root / "fingerprint.json").read_text(encoding="utf-8"))["fingerprint"]


# ── ⑤ 确定性：指纹纯函数 ─────────────────────────────────────────────────────


def test_fingerprint_deterministic_and_order_insensitive():
    fp1, fields1 = compute_fingerprint(
        ["src/b.py", "src/a.py"], head=_HEAD, map_digest=_DIGEST, tests=["tests/t2.py", "tests/t1.py"]
    )
    fp2, fields2 = compute_fingerprint(
        ["src/a.py", "src/b.py"], head=_HEAD, map_digest=_DIGEST, tests=["tests/t1.py", "tests/t2.py"]
    )
    assert fp1 == fp2 and fields1 == fields2
    assert fields1["changed_src"] == ["src/a.py", "src/b.py"]  # 排序去重
    fp3, _ = compute_fingerprint(
        ["src/a.py"], head=_HEAD, map_digest=_DIGEST, tests=["tests/t1.py"]
    )
    assert fp3 != fp1, "测试面变化必须换指纹（派生负载 pin）"
    fp4, _ = compute_fingerprint(
        ["src/a.py", "src/b.py"], head="b" * 40, map_digest=_DIGEST, tests=["tests/t1.py", "tests/t2.py"]
    )
    assert fp4 != fp1, "HEAD 变化必须换指纹"


# ── ⑥ 负例：空变更 ───────────────────────────────────────────────────────────


def test_nothing_to_do_on_empty_changes(cache_root: Path, monkeypatch: pytest.MonkeyPatch):
    spawn_record: list = []
    monkeypatch.setattr(dss, "_spawn_detached", lambda cmd, log: spawn_record.append(cmd))
    env = speculative_run(
        [], tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: [], spawn_fn=lambda cmd, log: spawn_record.append(cmd),
    )
    assert env["ok"] is True and env["state"] == "nothing_to_do"
    assert spawn_record == [], "空变更零子进程"
    st = speculative_status([], tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root)
    assert st["state"] == "nothing_to_do"


# ── ① 缓存命中 + 幂等 ────────────────────────────────────────────────────────


def test_cache_hit_and_idempotent_retrigger(cache_root: Path, monkeypatch: pytest.MonkeyPatch):
    env, spawn_record = _launch(cache_root)
    assert env["ok"] is True and env["state"] == "launched"
    assert len(spawn_record) == 1
    cmd, log_path = spawn_record[0]
    # 发射命令形态钉：child 内部模式 + 显式测试清单（真机面已在触发面剔除）
    assert "--child" in cmd and "--" in cmd
    assert not any("real_edt" in t for t in cmd[cmd.index("--") + 1:])
    assert cmd[cmd.index("--") + 1:] == _TESTS

    fp = env["fingerprint"]
    finish_run(
        cache_root, fp,
        {"schema": dss.SPECULATIVE_SUMMARY_SCHEMA, "fingerprint": fp, "state": "done",
         "passed": 9, "failed": 1, "failed_ids": ["tests/unit/test_x.py::test_red"],
         "log_path": log_path, "ts": 1060.0, "reason": None},
        "done",
    )
    t0 = time.perf_counter()
    st = speculative_status(_CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
                            cache_root=cache_root)
    elapsed = time.perf_counter() - t0
    assert st["ok"] is True and st["state"] == "hit"
    assert st["summary"]["failed_ids"] == ["tests/unit/test_x.py::test_red"]
    assert st["summary"]["passed"] == 9 and st["summary"]["failed"] == 1
    assert elapsed < 1.0, "status 必须纯文件读秒回（验收①）"

    env2, spawn_record2 = _launch(cache_root)
    assert env2["state"] == "cached", "同指纹二次触发幂等（验收⑤）"
    assert env2["summary"]["failed_ids"] == ["tests/unit/test_x.py::test_red"]
    assert spawn_record2 == [], "缓存命中零新发射"


# ── ② stale 如实 ─────────────────────────────────────────────────────────────


def test_stale_on_changed_src_growth(cache_root: Path):
    env, _ = _launch(cache_root)
    old_fp = env["fingerprint"]
    finish_run(cache_root, old_fp, {"fingerprint": old_fp, "state": "done"}, "done")
    st = speculative_status(
        [*_CHANGED, "src/rfauto/service/watchdog_service.py"],
        tests=[*_TESTS, "tests/unit/test_watchdog_service.py"],
        head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
    )
    assert st["ok"] is True and st["state"] == "stale"
    assert st["cached_fingerprint"] == old_fp
    assert "summary" not in st, "stale 不得携带旧 summary 冒充有效"


def test_status_missing_on_fresh_root(cache_root: Path):
    st = speculative_status(_CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
                            cache_root=cache_root)
    assert st["state"] == "missing"


def test_status_running_and_interrupted(cache_root: Path):
    _launch(cache_root)
    st = speculative_status(_CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
                            cache_root=cache_root, pid_alive_fn=lambda pid: pid == 424242,
                            now=1005.0)
    assert st["state"] == "running" and st["child_pid"] == 424242
    st2 = speculative_status(_CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
                             cache_root=cache_root, pid_alive_fn=lambda pid: False, now=1006.0)
    assert st2["state"] == "interrupted", "running 记录但子进程已死 → 如实 interrupted 不凑判"


# ── ③ #261 互斥 ──────────────────────────────────────────────────────────────


def test_mutex_declined_when_census_busy(cache_root: Path):
    spawn_record: list = []
    hits = [{"pid": 9, "name": "python.exe", "kind": "pytest_or_runner", "cmdline": "...pytest -q"}]
    env = speculative_run(
        _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: hits, spawn_fn=lambda cmd, log: spawn_record.append(cmd),
    )
    assert env["ok"] is True and env["state"] == "declined"
    assert env["guard"] == "mutex" and env["census_hits"] == hits
    assert spawn_record == [], "互斥命中零 pytest 子进程（验收③）"


def test_mutex_unverified_fail_closed(cache_root: Path):
    env = speculative_run(
        _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: None, spawn_fn=lambda cmd, log: (_ for _ in ()).throw(AssertionError("no spawn")),
    )
    assert env["state"] == "declined" and env["guard"] == "mutex_unverified"


def test_single_instance_blocks_second_trigger(cache_root: Path):
    _launch(cache_root)  # 心跳落 child_pid=424242
    env2 = speculative_run(
        [*_CHANGED, "src/rfauto/service/other.py"], tests=_TESTS,
        head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: [], pid_alive_fn=lambda pid: pid == 424242,
        spawn_fn=lambda cmd, log: 1, owner_pid=777, now=2000.0,
    )
    assert env2["state"] == "declined" and env2["guard"] == "single_instance"
    env3 = speculative_run(
        [*_CHANGED, "src/rfauto/service/other.py"], tests=_TESTS,
        head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: [], pid_alive_fn=lambda pid: False,
        spawn_fn=lambda cmd, log: 1, owner_pid=777, now=2000.0,
        min_trigger_interval_s=0.0,
    )
    assert env3["state"] == "launched", "死 pid 心跳=无主遗痕，不阻塞新触发"


def test_debounce_declines_rapid_refire(cache_root: Path):
    env, _ = _launch(cache_root, now=1000.0)
    fp1 = env["fingerprint"]
    finish_run(cache_root, fp1, {"fingerprint": fp1, "state": "done", "ts": 1010.0}, "done")
    env2 = speculative_run(
        [*_CHANGED, "src/rfauto/service/other.py"], tests=_TESTS,
        head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
        census_fn=lambda: [], pid_alive_fn=lambda pid: False,
        spawn_fn=lambda cmd, log: 1, owner_pid=777, now=1030.0,  # 距上轮 20s < 60s
    )
    assert env2["state"] == "declined" and env2["guard"] == "debounce"


# ── ④ 缓存白名单钉（#144 反向钉） ────────────────────────────────────────────


def test_whitelist_root_rejects_outside_roots(tmp_path: Path):
    with pytest.raises(SpeculativeGuardError):
        validate_cache_root(tmp_path / "runs" / "other_root")
    with pytest.raises(SpeculativeGuardError):
        validate_cache_root(tmp_path / "runs")  # 湖根本体也不是本服务缓存根
    resolved = validate_cache_root(tmp_path / "runs" / "devtest_speculative")
    assert resolved.name == "devtest_speculative" and resolved.parent.name == "runs"


def test_whitelist_guard_rejects_escape_names(tmp_path: Path):
    root = tmp_path / "runs" / "devtest_speculative"
    root.mkdir(parents=True)
    with pytest.raises(SpeculativeGuardError):
        guard_cache_path(root, "../evil.json")
    with pytest.raises(SpeculativeGuardError):
        guard_cache_path(root, "logs/../../evil.json")
    with pytest.raises(SpeculativeGuardError):
        guard_cache_path(root, str(tmp_path / "evil.json"))  # 绝对路径
    ok = guard_cache_path(root, "logs/abcd1234.log")
    assert ok.parent == root / "logs" and ok.name == "abcd1234.log"


def test_speculative_run_rejects_non_whitelist_root(tmp_path: Path):
    env = speculative_run(
        _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
        cache_root=tmp_path / "elsewhere", census_fn=lambda: [],
        spawn_fn=lambda cmd, log: 1,
    )
    assert env["ok"] is False, "白名单外缓存根必须 error 信封拒绝（验收④）"
    assert "白名单" in env["errors"][0]


# ── 真机面剔除（红线 1：投机预跑永不真机） ───────────────────────────────────


def test_real_machine_tests_dropped_and_all_real_declined(cache_root: Path):
    kept, dropped = strip_real_machine_tests(
        ["tests/unit/test_a.py", "tests/real_edt/test_hfss_real.py"]
    )
    assert kept == ["tests/unit/test_a.py"]
    assert dropped == ["tests/real_edt/test_hfss_real.py"]
    env, spawn_record = _launch(
        cache_root,
        tests=["tests/real_edt/test_hfss_real.py", r"tests\real_edt\test_ads_real.py"],
    )
    assert env["state"] == "declined" and env["guard"] == "real_machine_only"
    assert len(env["real_machine_dropped"]) == 2
    assert spawn_record == []


# ── census 命令与分类（纯函数） ──────────────────────────────────────────────


def test_local_census_command_contains_process_domains():
    cmd = local_census_command()
    assert "Win32_Process" in cmd
    for name in ("python.exe", "ansysedt.exe", "hpeesofsim.exe", "openems.exe"):
        assert name in cmd


def test_classify_census_hits_protocol_lines_only():
    lines = [
        "123|python.exe|C:\\venv\\python.exe -m pytest tests/unit -q",
        "124|python.exe|C:\\venv\\python.exe scripts/devtest_speculative.py --status",
        "125|ansysedt.exe|ansysedt -grpcsrv -ng",
        "126|python.exe|C:\\venv\\python.exe _rfauto_runner.py --template patch",
        "garbage line without protocol",
        "127|python.exe|C:\\venv\\python.exe -c print(1)",
    ]
    hits = classify_census_hits(lines)
    pids = {h["pid"] for h in hits}
    assert pids == {123, 125, 126}, "pytest/求解器/_rfauto_runner 命中；普通 python 与本驱动查询不命中"


# ── pytest 日志解析（纯函数，failed_ids 与日志逐位一致） ─────────────────────


def test_parse_pytest_summary_xdist_log():
    log = (
        "============================= test session starts =============================\n"
        "collected 10 items\n"
        "\n"
        "tests/unit/test_a.py F..\n"
        "tests/unit/test_b.py .F\n"
        "\n"
        "=================================== FAILURES ===================================\n"
        "==================================== short summary ============================\n"
        "FAILED tests/unit/test_a.py::test_one\n"
        "FAILED tests/unit/test_b.py::test_two\n"
        "========================= 2 failed, 8 passed in 4.21s =========================\n"
    )
    parsed = parse_pytest_summary(log)
    assert parsed["failed_ids"] == [
        "tests/unit/test_a.py::test_one",
        "tests/unit/test_b.py::test_two",
    ]
    assert parsed["passed"] == 8 and parsed["failed"] == 2
    assert "2 failed, 8 passed in 4.21s" in parsed["summary_line"]


def test_parse_pytest_summary_unparsable_is_none_not_zero():
    parsed = parse_pytest_summary("no summary band here\n")
    assert parsed["passed"] is None and parsed["failed"] is None
    assert parsed["failed_ids"] == []


def test_parse_pytest_summary_q_mode_bare_line():
    """-q 口径末行是无 ==== 带的裸 ``N passed in Xs``（E2E 实测形态）——
    非汇总数字行（进度点/FAILED 行）不得误当计数源。"""
    log = (
        "bringing up nodes...\n"
        "......................                                                   [100%]\n"
        "22 passed in 7.48s\n"
    )
    parsed = parse_pytest_summary(log)
    assert parsed["passed"] == 22 and parsed["failed"] == 0
    assert parsed["summary_line"] == "22 passed in 7.48s"
    assert parsed["failed_ids"] == []
    parsed_red = parse_pytest_summary(
        "FAILED tests/unit/test_x.py::test_red\n"
        "......................                                                   [100%]\n"
        "1 failed, 21 passed in 8.01s\n"
    )
    assert parsed_red["passed"] == 21 and parsed_red["failed"] == 1
    assert parsed_red["failed_ids"] == ["tests/unit/test_x.py::test_red"]


# ── child 执行体 ─────────────────────────────────────────────────────────────


class _FakeProc:
    """child pytest 子进程 stub：PIPE+communicate 口径（与实现同契约）。"""

    pid = 987654

    def __init__(self, rc: int | None, timeout: bool, out: bytes = b""):
        self._rc = rc
        self._timeout = timeout
        self._out = out
        self.returncode: int | None = None
        self._calls = 0

    def communicate(self, timeout: float | None = None):
        self._calls += 1
        if self._timeout and self._calls == 1:
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=timeout or 0)
        self.returncode = int(self._rc) if self._rc is not None else None
        return self._out, None


def test_child_done_red_run_writes_summary(cache_root: Path):
    fp = "f" * 64
    log = cache_root / "logs" / "abc.log"
    pytest_out = (
        b"FAILED tests/unit/test_devtest_speculative.py::test_red\n"
        b"========================= 1 failed, 5 passed in 3.00s =========================\n"
    )
    (cache_root / "fingerprint.json").write_text(
        json.dumps({"schema": dss.SPECULATIVE_CACHE_SCHEMA, "fingerprint": fp, "state": "running",
                    "child_pid": 1, "started_ts": 1.0}),
        encoding="utf-8",
    )
    popen_args: list = []

    def fake_popen(args, cwd=None, stdout=None, stderr=None, env=None):
        popen_args.append(args)
        return _FakeProc(rc=1, timeout=False, out=pytest_out)

    summary = run_speculative_child(
        fingerprint=fp, tests=["tests/unit/test_devtest_speculative.py"], log_path=log,
        cache_root=cache_root, workers=8, timeout_s=600, repo=cache_root,
        popen_fn=fake_popen, start_ts=10.0, clock=lambda: 13.5,
    )
    assert summary["state"] == "done" and summary["pytest_rc"] == 1
    assert summary["failed_ids"] == ["tests/unit/test_devtest_speculative.py::test_red"]
    assert summary["passed"] == 5 and summary["failed"] == 1
    # worker 硬顶钉：8 → 4（资源上限红线）+ 真机 marker 双保险钉
    args0 = popen_args[0]
    pytest_pos = args0.index("pytest")
    assert args0[args0.index("-n", pytest_pos) + 1] == "4"
    assert args0[args0.index("-m", pytest_pos) + 1] == "not real_edt"
    record = json.loads((cache_root / "fingerprint.json").read_text(encoding="utf-8"))
    assert record["state"] == "done" and record["fingerprint"] == fp
    on_disk = json.loads((cache_root / "summary.json").read_text(encoding="utf-8"))
    assert on_disk["fingerprint"] == fp and on_disk["failed"] == 1
    assert log.read_text(encoding="utf-8") == pytest_out.decode("utf-8"), (
        "日志=单写者追加全量 pytest 输出（Windows 句柄继承无追加语义的修复钉）"
    )


def test_child_timeout_kills_tree_and_marks_failed(cache_root: Path):
    fp = "e" * 64
    log = cache_root / "logs" / "t.log"
    log.parent.mkdir(parents=True)
    (cache_root / "fingerprint.json").write_text(
        json.dumps({"schema": dss.SPECULATIVE_CACHE_SCHEMA, "fingerprint": fp,
                    "state": "running", "child_pid": 1, "started_ts": 1.0}),
        encoding="utf-8",
    )
    killed: list = []

    summary = run_speculative_child(
        fingerprint=fp, tests=["tests/unit/test_slow.py"], log_path=log,
        cache_root=cache_root, timeout_s=5, repo=cache_root,
        popen_fn=lambda args, cwd=None, stdout=None, stderr=None, env=None:
            _FakeProc(rc=None, timeout=True, out=b"partial out\n"),
        kill_tree_fn=lambda pid: killed.append(pid) or True,
        start_ts=0.0, clock=lambda: 12.0,
    )
    assert summary["state"] == "failed" and summary["timed_out"] is True
    assert "超时" in (summary["reason"] or "")
    assert len(killed) == 1, "墙钟超时必须 kill 进程树（资源上限红线）"
    record = json.loads((cache_root / "fingerprint.json").read_text(encoding="utf-8"))
    assert record["state"] == "failed"


def test_child_rejects_log_outside_root(cache_root: Path, tmp_path: Path):
    with pytest.raises(SpeculativeGuardError):
        run_speculative_child(
            fingerprint="a" * 64, tests=["tests/unit/test_x.py"],
            log_path=tmp_path / "evil.log", cache_root=cache_root, repo=cache_root,
            popen_fn=lambda args, cwd=None, stdout=None, stderr=None, env=None: _FakeProc(0, False),
        )


def test_child_rejects_non_whitelist_root(tmp_path: Path):
    with pytest.raises(SpeculativeGuardError):
        run_speculative_child(
            fingerprint="a" * 64, tests=["tests/unit/test_x.py"],
            log_path=tmp_path / "x.log", cache_root=tmp_path / "other", repo=tmp_path,
            popen_fn=lambda args, cwd=None, stdout=None, stderr=None, env=None: _FakeProc(0, False),
        )
