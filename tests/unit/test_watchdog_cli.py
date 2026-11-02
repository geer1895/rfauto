"""watchdog CLI 叶钉子测试（aurora_p F2 席，2026-11-02）。

对应验收（任务书冻结判据）：
A. 新叶注册 + --json 信封契约（失败路径也是信封：usage 错误/白名单越界）；
B. 缺省一次性动作零后台零写（信封逐字节同 service 直调语义；无线程；
   零文件写）；
C. --watch 常驻循环：短 interval+注入停止（KeyboardInterrupt 注入）优雅停
   零悬挂线程，jsonl 落白名单 runs/watchdog/；interval 下限单源
   speculative_watch_service.MIN_INTERVAL_S；越界 sink 显式报错；
D. 计数面（test_check_numbers/test_cli/注册序金快照各自守，本文件不重复钉）；
E. 既有 tests/unit/test_watchdog_service.py 零改动全绿（本文件不触 service）。

零真机、零真 PS：census/CPU 采样/进程存活全 monkeypatch 注入（T-O12 同款
注入面）；产物面走真实 tmp_path（#144：测试不落真实 runs/——repo_root 注入
tmp，白名单根随之重定向，真实 runs/watchdog 零写入）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from typer.testing import CliRunner

import rfauto.service.watchdog_service as wd
from rfauto.service.speculative_watch_service import MIN_INTERVAL_S

_runner = CliRunner()


def _invoke(*args: str):
    from rfauto.cli.main import app

    return _runner.invoke(app, ["watchdog", "watch", *args])


def _parse_json_stream(text: str) -> list[dict]:
    """解析 --json 输出流（print_json 缩进多对象：watch 形态逐轮+汇总多段）。"""
    dec = json.JSONDecoder()
    objs: list[dict] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        obj, j = dec.raw_decode(text, i)
        objs.append(obj)
        i = j
    return objs


def _first_json(text: str) -> dict:
    return _parse_json_stream(text[text.index("{"):])[0]


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, tmp: Path) -> None:
    """白名单根重定向到 tmp（watch sink 默认路径与越界判定随之入 tmp——
    真实 runs/watchdog 零写入，#144 家法）。"""
    monkeypatch.setattr(wd, "repo_root", lambda: tmp)


# ── A：一次性视图三形态信封 ──────────────────────────────────────────────────


def test_one_shot_pid_dead_envelope():
    """pid 形态（零注入确定性面）：不存在 pid → dead 信封 ok=True。"""
    r = _invoke("--pid", "999999", "--json")
    assert r.exit_code == 0, r.output[:400]
    env = _first_json(r.output)
    assert env["ok"] is True
    assert env["state"] == "dead"
    assert env["evidence"]["process_alive"] is False
    assert env["target"] == {"kind": "pid", "pid": 999999}


def test_one_shot_pid_alive_via_injection(monkeypatch: pytest.MonkeyPatch):
    """pid 形态 alive：注入存活+CPU 增长两证（census 缺省不被调用）。"""
    monkeypatch.setattr(wd, "_pid_alive_default", lambda pid: True)
    samples = iter([1.0, 5.0])
    monkeypatch.setattr(wd, "sample_cpu_seconds", lambda pid: next(samples))
    r = _invoke("--pid", "100", "--json")
    assert r.exit_code == 0, r.output[:400]
    env = _first_json(r.output)
    assert env["state"] == "alive"
    assert env["evidence"] == {
        "process_alive": True, "cpu_growing": True, "artifact_fresh": None}
    assert env["cpu"]["delta_s"] == pytest.approx(4.0)


def test_one_shot_census_dict_form(monkeypatch: pytest.MonkeyPatch):
    """--fingerprint + --process-name → Mapping 形态透传（census 证命中）。"""
    seen: dict = {}

    def fake_census(name, fp):
        seen["name"], seen["fp"] = name, fp
        return ["4242|python _rfauto_runner --campaign aurora_p"]

    samples = iter([1.0, 2.0])
    monkeypatch.setattr(wd, "default_census", fake_census)
    monkeypatch.setattr(wd, "sample_cpu_seconds", lambda pid: next(samples))
    r = _invoke("--fingerprint", "_rfauto_runner",
                "--process-name", "python", "--json")
    assert r.exit_code == 0, r.output[:400]
    env = _first_json(r.output)
    assert env["state"] == "alive"
    assert env["target"]["kind"] == "census"
    assert env["target"]["process_name"] == "python"
    assert seen == {"name": "python", "fp": "_rfauto_runner"}
    # census 命中行首 pid 作 CPU 采样对象
    assert env["cpu"]["first_s"] == 1.0


def test_one_shot_census_unverifiable_is_unknown(monkeypatch: pytest.MonkeyPatch):
    """census 不可验证（查询失败）→ unknown 且 ok=True（#122 不凑判）。"""
    monkeypatch.setattr(wd, "default_census", lambda name, fp: None)
    r = _invoke("--fingerprint", "nohit", "--json")
    assert r.exit_code == 0, r.output[:400]
    env = _first_json(r.output)
    assert env["ok"] is True and env["state"] == "unknown"


def test_one_shot_artifact_only_fresh_and_zero_match(tmp_path: Path):
    """None 产物证形态：新鲜产物→alive（仅产物证）；glob 零命中→unknown。"""
    art = tmp_path / "art.log"
    art.write_text("progress", encoding="utf-8")
    r = _invoke("--artifact-glob", str(tmp_path / "*.log"), "--json")
    assert r.exit_code == 0, r.output[:400]
    env = _first_json(r.output)
    assert env["state"] == "alive"
    assert env["evidence"]["process_alive"] is None
    assert env["evidence"]["artifact_fresh"] is True
    assert "仅产物证" in (env.get("reason") or "")

    empty = tmp_path / "none"
    empty.mkdir()
    r2 = _invoke("--artifact-glob", str(empty / "*.log"), "--json")
    assert r2.exit_code == 0, r2.output[:400]
    env2 = _first_json(r2.output)
    assert env2["state"] == "unknown"


def test_one_shot_human_branch(tmp_path: Path):
    """人读分支（无 --json）：state 行+证据行，退出码 0。"""
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    r = _invoke("--artifact-glob", str(tmp_path / "*.log"))
    assert r.exit_code == 0, r.output[:400]
    assert "watchdog 判活" in r.output
    assert "alive" in r.output


# ── A：usage 错误失败路径（--json 下也是信封，exit 2） ────────────────────────


def test_usage_error_envelope_both_target_forms():
    r = _invoke("--pid", "1", "--fingerprint", "x", "--json")
    assert r.exit_code == 2
    env = _first_json(r.output)
    assert env["ok"] is False and env["errors"]


def test_usage_error_process_name_requires_fingerprint():
    r = _invoke("--process-name", "python", "--json")
    assert r.exit_code == 2
    env = _first_json(r.output)
    assert env["ok"] is False


# ── B：缺省一次性动作零后台零写 + 逐字节同 service 直调 ──────────────────────


def test_one_shot_default_no_write_no_thread_and_service_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """缺省动作钉：信封与 service 直调逐位一致、零文件写、无线程增殖。"""
    _patch_repo_root(monkeypatch, tmp_path)
    monkeypatch.setattr(wd.time, "time", lambda: 1000.0)  # 冻结 now
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    os.utime(art, (900.0, 900.0))  # age=100s ≤ 缺省 900s 窗 → fresh
    globs = str(tmp_path / "*.log")

    threads_before = threading.active_count()
    r = _invoke("--artifact-glob", globs, "--json")
    assert r.exit_code == 0, r.output[:400]
    cli_env = _first_json(r.output)
    assert threading.active_count() == threads_before
    # 零文件写：白名单根（tmp/runs/watchdog）未被创建
    assert not (tmp_path / "runs" / "watchdog").exists()

    direct = wd.seat_liveness_view(
        None, artifact_globs=(globs,), stall_window_s=900.0, now=1000.0)
    assert cli_env == direct, "缺省一次性动作必须逐字节同 service 直调语义"


# ── C：--watch 常驻循环 ──────────────────────────────────────────────────────


def test_watch_loop_short_duration_jsonl_whitelist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """短 interval+duration：轮数折算+interval 下限单源+jsonl 落白名单。"""
    _patch_repo_root(monkeypatch, tmp_path)
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    sink = tmp_path / "runs" / "watchdog" / "cli" / "watch.jsonl"

    threads_before = threading.active_count()
    r = _invoke("--watch", "--interval", "0", "--duration", "2",
                "--sink", str(sink),
                "--artifact-glob", str(tmp_path / "*.log"), "--json")
    assert r.exit_code == 0, r.output[:400]
    assert threading.active_count() == threads_before, "零悬挂线程"

    objs = _parse_json_stream(r.output)
    assert len(objs) == 3, "逐轮 2 行+汇总 1 行"
    assert [o["watch_round"] for o in objs[:2]] == [1, 2]
    assert all(o["sink_write_ok"] is True for o in objs[:2])
    summary = objs[2]
    assert summary["ok"] is True
    assert summary["mode"] == "watch"
    # interval 下限=service 家族 MIN_INTERVAL_S 单源（--interval 0 被抬到 1.0）
    assert summary["interval_s"] == float(MIN_INTERVAL_S)
    assert summary["rounds_done"] == 2  # ceil(2 / 1.0)
    assert summary["interrupted"] is False
    assert summary["sink_write_ok"] is True
    assert summary["state_counts"]["alive"] == 2
    assert summary["sink"] == str(sink)
    # jsonl 逐轮落白名单单根内
    lines = sink.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for ln in lines:
        rec = json.loads(ln)
        assert "ts" in rec and rec["view"]["watch_round"] in (1, 2)


def test_watch_loop_keyboard_interrupt_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """注入停止（glob 第二次调用抛 KeyboardInterrupt）：优雅停零悬挂。"""
    _patch_repo_root(monkeypatch, tmp_path)
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    sink = tmp_path / "runs" / "watchdog" / "cli" / "watch.jsonl"

    calls = {"n": 0}
    real_glob = wd._globmod.glob

    def fake_glob(pattern, recursive=False):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt
        return real_glob(pattern, recursive=recursive)

    monkeypatch.setattr(wd._globmod, "glob", fake_glob)
    threads_before = threading.active_count()
    r = _invoke("--watch", "--interval", "1", "--sink", str(sink),
                "--artifact-glob", str(tmp_path / "*.log"), "--json")
    assert r.exit_code == 0, r.output[:400]
    assert threading.active_count() == threads_before, "零悬挂线程"

    objs = _parse_json_stream(r.output)
    assert len(objs) == 2, "首轮完成+汇总"
    summary = objs[1]
    assert summary["interrupted"] is True
    assert summary["rounds_done"] == 1
    assert summary["rounds_planned"] > 10 ** 8, "无 --duration=长驻轮数上限"
    assert sink.read_text(encoding="utf-8").count("\n") == 1


def test_watch_loop_sink_outside_whitelist_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """白名单越界（调用期急切校验）→ 失败信封（--json 契约）+exit 1。"""
    _patch_repo_root(monkeypatch, tmp_path)
    outside = tmp_path / "outside.jsonl"
    r = _invoke("--watch", "--sink", str(outside), "--json")
    assert r.exit_code == 1
    env = _first_json(r.output)
    assert env["ok"] is False
    assert any("白名单" in e for e in env["errors"])
    assert not outside.exists(), "越界 sink 零写入"


def test_watch_human_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """人读分支 watch 汇总：轮数+sink 回显（escape 纪律下零 MarkupError）。"""
    _patch_repo_root(monkeypatch, tmp_path)
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    sink = tmp_path / "runs" / "watchdog" / "cli" / "watch.jsonl"
    r = _invoke("--watch", "--duration", "1", "--sink", str(sink),
                "--artifact-glob", str(tmp_path / "*.log"))
    assert r.exit_code == 0, r.output[:400]
    assert "watch 结束" in r.output
    # rich 人读面按终端宽折行——去换行后再对 sink 路径（折行只插 \n 不改字面）
    assert str(sink) in r.output.replace("\n", "")


# ── help 卫生（#305 家族：真构建 parser 跑 --help 可抓） ─────────────────────


def test_leaf_help_renders_in_process():
    """--help 进程内渲染零崩（裸 [/MarkupError 即红）。"""
    r = _invoke("--help")
    assert r.exit_code == 0, r.output[:400]
    assert "三证" in r.output


def test_leaf_help_subprocess_hygiene():
    """子进程 --help 卫生（真 spawn 冒烟）。"""
    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "rfauto.cli.main", "watchdog", "watch",
         "--help"],
        capture_output=True, text=True, timeout=120, cwd=str(repo))
    assert proc.returncode == 0, proc.stderr[:400]
    assert "三证" in proc.stdout


def test_watchdog_domain_in_top_level_tree():
    """顶层域注册+面板映射入表（HELP_PANEL_OF 键集==顶层名集的邻接自证）。"""
    from typer.main import get_command

    from rfauto.cli import main as cli_main
    from rfauto.cli.help_groups import HELP_PANEL_OF

    cmd = get_command(cli_main.app)
    assert "watchdog" in cmd.commands
    assert HELP_PANEL_OF["watchdog"] == "自动化与协作"
