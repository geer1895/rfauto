"""scripts/oe_chain_launch.py（H1-5 消费面收编）rc 判链离线回归钉。

出处链：runs/ge8_followup/oe_chain_waiter.py（ge8b 档案）对战役 rc 只记
不判 + fd_oe_campaign 修复前恒 rc=0 → 全座 SKIP 被记成"OE 链完毕"
（oe_chain.log 2026-10-03 K-7 实证）→ F6 修复席：本脚本按 rc 判链
（rc 0 才串发下一项），runs/ 档案零改写。

钉面：
① chain_should_continue 三态（0 通行 / 非 0 拦截带原因）；
② run_chain 串行编排（首步非 0 即中止、后步零发射、全 0 链完毕）；
③ census_clear 保守判忙（异常不转盲发）；
④ wait_clear 三出口（CLEAR=0 / 等待超时=2 / 父心跳超时自尽=4）；
⑤ _resolve_arg 仓根锚定（#295 族）；
⑥ main 端到端（真实 venv python -u 子进程，log 显式落 tmp_path，
   零真实 runs/ 写入 #144）：步骤 rc!=0 → 链中止透传。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "oe_chain_launch.py"

_SPEC = importlib.util.spec_from_file_location("oe_chain_launch_test_target",
                                               _SCRIPT)
chain = importlib.util.module_from_spec(_SPEC)
sys.modules["oe_chain_launch_test_target"] = chain
_SPEC.loader.exec_module(chain)


# ─── ① 链闸三态（waiter 侧 rc 判定函数）──────────────────────────────────

def test_chain_gate_zero_continues():
    assert chain.chain_should_continue(0) == (True, "")


def test_chain_gate_nonzero_stops_with_reason():
    for rc in (1, 2, 3, 4, 64):
        ok, reason = chain.chain_should_continue(rc)
        assert ok is False
        assert str(rc) in reason and "链中止" in reason


def test_chain_gate_k7_signature():
    """K-7 回归签名：战役全座 SKIP → fd_oe_campaign rc=3 → 链不得续发。"""
    ok, _ = chain.chain_should_continue(3)
    assert ok is False


# ─── ② run_chain 串行编排 ─────────────────────────────────────────────────

def test_run_chain_all_zero_spawns_every_step_in_order():
    tags: list[str] = []

    def spawn(step):
        tags.append(step["tag"])
        return 0

    logs: list[str] = []
    rc = chain.run_chain(
        [{"tag": "K-5"}, {"tag": "K-7"}], spawn,
        log_fn=lambda m: logs.append(m))
    assert rc == 0
    assert tags == ["K-5", "K-7"], "rc=0 必须串发下一项"
    assert any("链完毕" in m for m in logs)


def test_run_chain_first_nonzero_stops_and_passthrough():
    """首步 rc=3（如全座 SKIP）→ 后一步零发射、透传 3（H1-5 修复面）。"""
    tags: list[str] = []

    def spawn(step):
        tags.append(step["tag"])
        return 3 if step["tag"] == "K-7" else 0

    logs: list[str] = []
    steps = [{"tag": "K-5"}, {"tag": "K-7"}, {"tag": "K-8"}]
    rc = chain.run_chain(steps, spawn, log_fn=lambda m: logs.append(m))
    assert rc == 3
    assert tags == ["K-5", "K-7"], "rc!=0 不得串发后续步骤"
    assert any("链中止" in m for m in logs)


# ─── ③ census 守望门（保守判忙）───────────────────────────────────────────

def test_census_clear_semantics():
    assert chain.census_clear(lambda: "CLEAR") is True
    assert chain.census_clear(lambda: "BUSY: python CMD=x PID=1") is False
    assert chain.census_clear(lambda: "") is False          # 空=不发射
    assert chain.census_clear(
        lambda: (_ for _ in ()).throw(RuntimeError("ssh down"))) is False, \
        "探针异常保守判忙（宁枉勿纵，不得转盲发）"


# ─── ④ wait_clear 三出口 ──────────────────────────────────────────────────

def test_wait_clear_returns_zero_on_clear():
    polls = {"n": 0}

    def runner():
        polls["n"] += 1
        return "CLEAR"

    rc = chain.wait_clear(runner, max_wait_s=60, poll_s=1,
                          sleep_fn=lambda s: None, now_fn=lambda: 1000.0)
    assert rc == 0 and polls["n"] == 1


def test_wait_clear_timeout_returns_2():
    clock = {"t": 0.0}

    def advance(s):
        clock["t"] += s

    rc = chain.wait_clear(lambda: "BUSY: x", max_wait_s=10, poll_s=5,
                          sleep_fn=advance, now_fn=lambda: clock["t"])
    assert rc == chain.EXIT_WAIT_TIMEOUT == 2


def test_wait_clear_parent_heartbeat_stale_self_terminates_4(tmp_path):
    hb = tmp_path / "parent.touch"
    hb.write_text("", encoding="utf-8")
    import os

    old = 1000.0 - 9999.0
    os.utime(hb, (old, old))
    rc = chain.wait_clear(
        lambda: "BUSY: x", max_wait_s=9999, poll_s=1,
        heartbeat_path=hb, heartbeat_timeout_s=90.0,
        sleep_fn=lambda s: None, now_fn=lambda: 1000.0)
    assert rc == chain.EXIT_PARENT_TIMEOUT == 4


def test_wait_clear_missing_parent_heartbeat_self_touches(tmp_path):
    """父心跳文件缺=自 touch 兜底（与历史 oe_chain_waiter 同口径），
    不误判自尽。"""
    hb = tmp_path / "never.touch"
    clock = {"t": 1000.0}

    def runner():
        clock["t"] += 1
        return "CLEAR" if clock["t"] >= 1002.0 else "BUSY: x"

    rc = chain.wait_clear(
        runner, max_wait_s=60, poll_s=1, heartbeat_path=hb,
        heartbeat_timeout_s=90.0, sleep_fn=lambda s: None,
        now_fn=lambda: clock["t"])
    assert rc == 0
    assert hb.exists(), "缺心跳须自 touch（自持）"


# ─── ⑤ argv 仓根锚定 ──────────────────────────────────────────────────────

def test_resolve_arg_repo_anchor():
    assert chain._resolve_arg("scripts/fd_oe_campaign.py") == str(
        REPO / "scripts" / "fd_oe_campaign.py")
    assert chain._resolve_arg(".venv/Scripts/python.exe") == str(
        REPO / ".venv" / "Scripts" / "python.exe")
    assert chain._resolve_arg("--only") == "--only"
    assert chain._resolve_arg("ms_ring_patch") == "ms_ring_patch"
    assert chain._resolve_arg(str(REPO / "scripts" / "x.py")) == str(
        REPO / "scripts" / "x.py")


# ─── ⑥ main 端到端（离线真子进程；log 全部显式落 tmp_path）────────────────

def _write_chain(tmp_path: Path, steps: list[dict]) -> Path:
    for s in steps:
        s.setdefault("log", str(tmp_path / f"{s['tag']}.log"))
    p = tmp_path / "chain.json"
    p.write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")
    return p


def test_main_chain_stops_on_nonzero_step(tmp_path):
    """真实子进程端到端：步 1 rc=3 → 链中止透传 3，步 2 未发射
    （log 文件不存在即铁证）。"""
    p = _write_chain(tmp_path, [
        {"tag": "k1", "argv": ["-c", "import sys; sys.exit(3)"]},
        {"tag": "k2", "argv": ["-c", "import sys; sys.exit(0)"]},
    ])
    rc = chain.main(["--chain", str(p)])
    assert rc == 3
    assert (tmp_path / "k1.log").exists()
    assert not (tmp_path / "k2.log").exists(), "rc!=0 不得串发下一步"


def test_main_chain_all_zero_completes(tmp_path):
    p = _write_chain(tmp_path, [
        {"tag": "k1", "argv": ["-c", "import sys; sys.exit(0)"]},
        {"tag": "k2", "argv": ["-c", "import sys; sys.exit(0)"]},
    ])
    assert chain.main(["--chain", str(p)]) == 0
    assert (tmp_path / "k1.log").exists() and (tmp_path / "k2.log").exists()


def test_main_bad_chain_file_is_usage_error(tmp_path):
    assert chain.main(["--chain", str(tmp_path / "nope.json")]) == 64
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert chain.main(["--chain", str(bad)]) == 64
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"a": 1}', encoding="utf-8")
    assert chain.main(["--chain", str(wrong)]) == 64


def test_main_usage_error_exits_64_not_2():
    """缺 --chain → 自定义 error rc=64（H1-6 同族：rc2 留给步骤透传语义）。"""
    with pytest.raises(SystemExit) as ei:
        chain.main([])
    assert ei.value.code == 64
