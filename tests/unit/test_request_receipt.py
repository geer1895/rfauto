"""VB-2 不确定结局协议（请求回执状态机）钉测（aurora_r R-11 席）。

五类验收钉（runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-2 验收要点）：
① 状态机纯函数钉：同键同载荷→原快照且执行器计数=1；同键异载荷→rejected；
   时间窗外→rejected；预算耗尽→not_started；重启丢缓存→resume 如实 unknown；
② 故障注入钉：发送后断连→unknown 且同键重试不重执行（计数仍=1）；
   发送前失败→not_started 且允许重试；
③ 毒化钉：unknown 后新提交被拒→探针重同步成功后放行；unknown 键自身
   仍须 reconcile 对账后才落定；
④ 缺省零变化钉：不传键的缺省路径信封键集逐字节零变化（既有远程/作业
   测试全绿为面证据，此处钉单点形状）；
⑤ 信封纪律钉：全走 ok_envelope/error_envelope 构造器；unknown 随信封带
   receipt_id 与诊断。

远程面全部 FakeTransport 离线（#139 零真机零连网；patch 消费点
roe.SshTransport，P3-7 家法）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.api.tuning as tuning_mod
import rfauto.service.remote_oe_service as roe
from rfauto.infra.request_receipt import (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_NOT_STARTED,
    OUTCOME_REJECTED,
    OUTCOME_UNKNOWN,
    NotSentError,
    ReceiptDecision,
    RequestReceiptLedger,
    UncertainOutcomeError,
    execute_with_receipt,
    payload_fingerprint,
)
from rfauto.service.remote_oe_service import REMOTE_OE_ENV, remote_oe_run

WORK_ROOT = "E:\\rfauto_remote"


class _FakeClock:
    """单调假钟（TTL/预算判定零真睡；advance 显式推进）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _fp(tag: str = "p0") -> str:
    return payload_fingerprint({"payload": tag})


# ═══ ① 状态机纯函数钉 ══════════════════════════════════════════════════════


class TestStateMachinePurePins:
    def test_same_key_same_payload_replays_snapshot_executor_count_one(self):
        """同键同载荷终态 → 原快照重放；执行器全程只被调用一次。"""
        ledger = RequestReceiptLedger(clock=_FakeClock())
        calls: list[int] = []

        def run() -> dict:
            calls.append(1)
            return {"rc": 0, "metrics": {"s11": -20.0}}

        d1 = execute_with_receipt(ledger, key="k", fingerprint=_fp(), executor=run)
        assert d1.outcome == OUTCOME_COMPLETED and d1.proceed is False
        d2 = execute_with_receipt(ledger, key="k", fingerprint=_fp(), executor=run)
        assert d2.outcome == OUTCOME_COMPLETED
        assert d2.snapshot == {"rc": 0, "metrics": {"s11": -20.0}}
        assert d2.receipt_id == d1.receipt_id, "同键重放携带同一回执号"
        assert len(calls) == 1, "执行器调用计数必须=1（快照重放不重执行）"

    def test_same_key_different_payload_rejected(self):
        ledger = RequestReceiptLedger()
        ledger.claim("k", _fp("a"))
        ledger.mark_completed("k", {"rc": 0})
        d = ledger.claim("k", _fp("b"))
        assert d.outcome == OUTCOME_REJECTED
        assert d.proceed is False and d.retry_allowed is False
        assert d.diagnostics.get("payload_mismatch") is True

    def test_window_outside_rejected(self):
        """TTL 时间窗外 → rejected（旧回执不可漂白成新提交）。"""
        clock = _FakeClock()
        ledger = RequestReceiptLedger(ttl_s=60.0, clock=clock)
        d1 = ledger.claim("k", _fp())
        assert d1.proceed is True
        ledger.mark_completed("k", {"rc": 0})
        clock.advance(61.0)
        d2 = ledger.claim("k", _fp())
        assert d2.outcome == OUTCOME_REJECTED
        assert d2.diagnostics.get("window_expired") is True

    def test_budget_deadline_exhausted_not_started_no_entry(self):
        """单调时钟预算耗尽（观察位 5）→ not_started，不落条目、可重试。"""
        clock = _FakeClock()
        ledger = RequestReceiptLedger(clock=clock)
        d = ledger.claim("k", _fp(), deadline_mono=clock.now - 1.0)
        assert d.outcome == OUTCOME_NOT_STARTED
        assert d.proceed is False and d.retry_allowed is True
        assert ledger.peek("k") is None, "预算拒绝不得残留条目"
        # wrapper 侧同口径
        ran: list[int] = []

        def exec_() -> dict:
            ran.append(1)
            return {}

        dw = execute_with_receipt(
            ledger, key="k2", fingerprint=_fp(), executor=exec_,
            deadline_mono=clock.now - 1.0,
        )
        assert dw.outcome == OUTCOME_NOT_STARTED and ran == []

    def test_resume_after_cache_loss_unknown_not_not_started(self):
        """进程重启=回执缓存丢失 → resume 如实 unknown（绝不 not_started）。"""
        ledger = RequestReceiptLedger()  # 新实例模拟重启后空账
        d = ledger.resume("k_from_previous_life", _fp())
        assert d.outcome == OUTCOME_UNKNOWN
        assert d.proceed is False and d.retry_allowed is False
        assert d.diagnostics.get("ledger_miss") is True

    def test_bounded_cache_capacity_evicts_terminal_keeps_shape(self):
        """容量有界：终态 LRU 淘汰；账本形状保持可查（TTL/容量有界口径）。"""
        ledger = RequestReceiptLedger(max_entries=3, clock=_FakeClock())
        for i in range(5):
            ledger.claim(f"k{i}", _fp(f"v{i}"))
            ledger.mark_completed(f"k{i}", {"i": i})
        st = ledger.stats()
        assert st["entries"] <= 3
        assert st["state_counts"].get("completed", 0) <= 3


# ═══ ② 故障注入钉 ══════════════════════════════════════════════════════════


class TestFaultInjectionPins:
    def test_send_then_disconnect_unknown_and_retry_not_reexecuted(self):
        """发送后断连 → unknown；同键重试不重执行（计数仍=1）；车道毒化。"""
        ledger = RequestReceiptLedger()
        calls: list[int] = []

        def exec_disconnect_after_send() -> dict:
            calls.append(1)  # 已完成"发送"动作
            raise ConnectionError("通道断连")

        d1 = execute_with_receipt(
            ledger, key="k", fingerprint=_fp(), executor=exec_disconnect_after_send,
            uncertain_exceptions=(ConnectionError,),
        )
        assert d1.outcome == OUTCOME_UNKNOWN
        assert d1.retry_allowed is False and d1.receipt_id
        # 同键重试：命中 sent 条目 → 仍 unknown，执行器不再被调用
        d2 = execute_with_receipt(
            ledger, key="k", fingerprint=_fp(), executor=exec_disconnect_after_send,
            uncertain_exceptions=(ConnectionError,),
        )
        assert d2.outcome == OUTCOME_UNKNOWN
        assert d2.receipt_id == d1.receipt_id
        assert len(calls) == 1, "unknown 永不自动重放（执行器计数仍=1）"
        assert ledger.lane_state("default")["poisoned"] is True

    def test_pre_send_failure_not_started_and_retry_allowed(self):
        """发送前失败 → not_started（确定未发送），同键重试放行。"""
        ledger = RequestReceiptLedger()
        calls: list[int] = []

        def exec_fail_before_send() -> dict:
            raise NotSentError("装配段失败，尚未发送")

        d1 = execute_with_receipt(
            ledger, key="k", fingerprint=_fp(), executor=exec_fail_before_send,
        )
        assert d1.outcome == OUTCOME_NOT_STARTED
        assert d1.retry_allowed is True
        assert ledger.peek("k") is None, "未发送条目必须回收"
        assert ledger.lane_state("default")["poisoned"] is False
        # 重试：执行器真正执行一次
        def real_run() -> dict:
            calls.append(1)
            return {"rc": 0}

        d2 = execute_with_receipt(ledger, key="k", fingerprint=_fp(), executor=real_run)
        assert d2.outcome == OUTCOME_COMPLETED and calls == [1]

    def test_uncertain_and_not_sent_exception_tuple_mapping(self):
        ledger = RequestReceiptLedger()

        def raise_conn() -> dict:
            raise ConnectionError("x")

        d = execute_with_receipt(
            ledger, key="a", fingerprint=_fp(), executor=raise_conn,
            uncertain_exceptions=(ConnectionError,),
        )
        assert d.outcome == OUTCOME_UNKNOWN
        ledger2 = RequestReceiptLedger()

        def raise_rt() -> dict:
            raise RuntimeError("pre-send boom")

        d2 = execute_with_receipt(
            ledger2, key="b", fingerprint=_fp(), executor=raise_rt,
            not_sent_exceptions=(RuntimeError,),
        )
        assert d2.outcome == OUTCOME_NOT_STARTED and d2.retry_allowed is True

    def test_definite_failure_failed_snapshot_replay(self):
        """确定失败 → failed（快照带错误摘要）；同键重放快照不重执行。"""
        ledger = RequestReceiptLedger()
        calls: list[int] = []

        def raise_val() -> dict:
            calls.append(1)
            raise ValueError("参数非法")

        d1 = execute_with_receipt(ledger, key="k", fingerprint=_fp(), executor=raise_val)
        assert d1.outcome == OUTCOME_FAILED
        assert "ValueError" in (d1.snapshot or {}).get("error", "")
        d2 = execute_with_receipt(ledger, key="k", fingerprint=_fp(), executor=raise_val)
        assert d2.outcome == OUTCOME_FAILED and d2.snapshot == d1.snapshot
        assert len(calls) == 1


# ═══ ③ 毒化钉 ══════════════════════════════════════════════════════════════


class TestLanePoisonPins:
    def _poison(self, ledger: RequestReceiptLedger, key: str = "k") -> None:
        def boom() -> dict:
            raise ConnectionError("cut")

        execute_with_receipt(
            ledger, key=key, fingerprint=_fp(), executor=boom,
            uncertain_exceptions=(ConnectionError,),
        )

    def test_unknown_poisons_lane_new_submission_rejected_then_resync_releases(self):
        ledger = RequestReceiptLedger()
        self._poison(ledger, "k_unknown")
        # 毒化中：新提交（新键）被拒
        d_new = ledger.claim("k_fresh", _fp())
        assert d_new.outcome == OUTCOME_REJECTED
        assert d_new.diagnostics.get("lane_poisoned") is True
        # 探针重同步成功 → 解除毒化 → 新提交放行
        assert ledger.resync_lane("default") is True
        d_after = ledger.claim("k_fresh", _fp())
        assert d_after.outcome == OUTCOME_NOT_STARTED and d_after.proceed is True

    def test_resync_releases_lane_but_unknown_key_still_needs_reconcile(self):
        """车道解除不等于 unknown 键放行——须凭回执对账（reconcile）落定。"""
        ledger = RequestReceiptLedger()
        self._poison(ledger, "k_unknown")
        ledger.resync_lane("default")
        d = ledger.claim("k_unknown", _fp())
        assert d.outcome == OUTCOME_UNKNOWN, "unknown 键自身永不自动重放"
        # 对账（人工/探针证据后显式落定）
        assert ledger.reconcile(
            "k_unknown", outcome=OUTCOME_COMPLETED, snapshot={"verified": 1},
        ) is True
        d2 = ledger.claim("k_unknown", _fp())
        assert d2.outcome == OUTCOME_COMPLETED and d2.snapshot == {"verified": 1}

    def test_reconcile_rejects_bogus_outcome_and_missing_key(self):
        ledger = RequestReceiptLedger()
        assert ledger.reconcile("nope", outcome=OUTCOME_COMPLETED) is False
        ledger.claim("k", _fp())
        assert ledger.reconcile(
            "k", outcome="made_up") is False, "非四分结局不得落定"

    def test_poison_not_cleared_without_resync(self):
        ledger = RequestReceiptLedger()
        self._poison(ledger)
        assert ledger.resync_lane("default") is True
        assert ledger.resync_lane("default") is False, "无毒化可解除时如实 False"


# ═══ 远程/作业接入面的共用离线装置 ══════════════════════════════════════════


class _FakeTransport:
    """同步档五步全通道 mock（命令形态应答；fail_on 前缀注入故障）。"""

    def __init__(self, exec_rc: int = 0, fail_on: str | None = None) -> None:
        self.commands: list[str] = []
        self.exec_rc = exec_rc
        self.fail_on = fail_on
        self.removed: set[str] = set()
        self.launch_calls = 0

    def connect(self) -> None:
        pass

    def run_command(self, cmd: str, timeout_s: float = 60.0):
        self.commands.append(cmd)
        if self.fail_on and cmd.startswith(self.fail_on):
            raise RuntimeError("mock: command boom")
        if "$_.Name -eq 'python.exe'" in cmd:            # 互斥直查（权威）
            return 0, "", ""
        if "run_server_probe.ps1" in cmd:                 # 互斥旁证
            return 0, "mutex CLEAR\n", ""
        if "cleanup_after_task.ps1" in cmd:               # census 旁证
            return 0, "census: no procs\n", ""
        if cmd.startswith("New-Item"):
            return 0, "", ""
        if cmd.startswith("Test-Path"):
            target = cmd.split("'")[1].lower()
            if any(target == r or target.startswith(r + "\\")
                   for r in self.removed):
                return 0, "False\n", ""
            return 0, "True\n", ""
        if "Get-Content -LiteralPath" in cmd and "launch_rc.txt" in cmd:
            return 0, "rc=0\n", ""
        if cmd.startswith("cmd /c"):                      # sync 档发射
            self.launch_calls += 1
            return self.exec_rc, "[launch] ok\n", ""
        if cmd.startswith("Get-ChildItem"):
            task = cmd.split("'")[1]
            return 0, f"{task}\\sparams.csv\n", ""
        if cmd.startswith("Remove-Item"):
            self.removed.add(cmd.split("'")[1].lower())
            return 0, "", ""
        return 0, "", ""

    def upload_file(self, local, remote) -> None:
        pass

    def download_file(self, remote, local) -> None:
        p = Path(local)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-oe-product-bytes")

    def close(self) -> None:
        pass


def _remote_harness(monkeypatch, transport: _FakeTransport,
                    probe_reachable: bool = True) -> None:
    from rfauto.infra.remote_machines import (
        ENV_REMOTE_SSH_PASSWORD,
        ENV_REMOTE_SSH_USER,
        RemoteMachineConfig,
    )
    monkeypatch.setenv(REMOTE_OE_ENV, "1")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    cfg = RemoteMachineConfig(
        name="lab_server", host="192.0.2.10", ssh_port=22,
        hfss_project_root=WORK_ROOT, probe_ports={"ansys_license": 1055},
    )
    monkeypatch.setattr(roe, "load_remote_machines", lambda: {"lab_server": cfg})
    monkeypatch.setattr(
        roe, "probe_machine",
        lambda c: {"name": c.name, "reachable": probe_reachable, "ports": {}},
    )
    monkeypatch.setattr(roe, "SshTransport", lambda c: transport)


def _seat_spec() -> dict:
    return {
        "template": "bend",
        "simulation_py": "# rendered simulation.py\n",
        "criteria_md": "# criteria\n- G1..G5\n",
        "timeout_s": 120.0,
        "campaign": "ge_fd",
        "render_sha256": "ab" * 32,
    }


# ═══ ④ 缺省零变化钉 ════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolated_and_registry(isolated):
    """cwd 隔离（runs/ 湖防污染，#144 家法）+ job 注册表逐用例重置。"""
    from rfauto.service.job_registry import reset_job_registry
    reset_job_registry()
    yield
    reset_job_registry()


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestDefaultPathZeroChangePins:
    def test_run_once_async_default_envelope_keys_unchanged(self, tmp_path):
        """不传键：信封键集与既有面逐键一致 {ok, job_id, state, message}。"""
        from rfauto.service.api import run_once_async
        from rfauto.service.job_registry import get_job_registry

        result = run_once_async(_recipe(tmp_path))
        assert result["ok"] is True
        assert set(result.keys()) == {"ok", "job_id", "state", "message"}
        final = get_job_registry().wait(result["job_id"], timeout_s=120)
        assert final is not None and final["state"] == "done"

    def test_remote_oe_run_default_envelope_no_receipt_keys(self, tmp_path,
                                                            monkeypatch):
        """不传 receipt_key：信封零 receipt 诊断键（既有形状逐键不变）。"""
        t = _FakeTransport(exec_rc=0)
        _remote_harness(monkeypatch, t)
        envelope = remote_oe_run(
            "lab_server", _seat_spec(), out_dir=tmp_path / "pull",
        )
        assert envelope["ok"] is True and envelope["verdict"] == "PASS"
        assert "receipt_outcome" not in envelope
        assert "receipt_id" not in envelope
        assert t.launch_calls == 1


# ═══ ⑤ 信封纪律钉 ══════════════════════════════════════════════════════════


class TestEnvelopeDisciplinePins:
    def test_run_once_async_replay_envelope_executor_count_one(self, tmp_path,
                                                               monkeypatch):
        """同键同载荷第二次提交 → 快照重放信封；run_once 只真跑一次。"""
        from rfauto.service.api import run_once_async
        from rfauto.service.job_registry import get_job_registry

        real_run_once = tuning_mod.run_once
        calls: list[int] = []

        def counting_run_once(*a, **kw):
            calls.append(1)
            return real_run_once(*a, **kw)

        monkeypatch.setattr(tuning_mod, "run_once", counting_run_once)
        ledger = RequestReceiptLedger()
        key = "job-key-1"
        r1 = run_once_async(_recipe(tmp_path), idempotency_key=key,
                            receipt_ledger=ledger)
        assert r1["ok"] is True and r1["state"] == "running"
        final = get_job_registry().wait(r1["job_id"], timeout_s=120)
        assert final["state"] == "done"
        r2 = run_once_async(_recipe(tmp_path), idempotency_key=key,
                            receipt_ledger=ledger)
        assert r2["ok"] is True
        assert r2["idempotent_replay"] is True
        assert r2["receipt_outcome"] == OUTCOME_COMPLETED
        assert r2["receipt_id"], "重放信封必须携带回执号"
        assert r2["job_id"] == r1["job_id"], "重放返回原 job_id"
        assert r2["replayed_result"]["run_id"] == final["run_id"]
        assert len(calls) == 1, "执行器（run_once）调用计数=1"

    def test_run_once_async_unknown_envelope_receipt_id_diagnostics(self):
        """在飞/归属未落定 → ok=False + errors list + receipt_id + 诊断。"""
        from rfauto.service.api import run_once_async

        ledger = RequestReceiptLedger()
        fp = payload_fingerprint({
            "kind": "run_once_async", "recipe_path": "whatever.yaml",
            "adapter_name": "fake", "payload": None,
        })
        ledger.claim("stuck-key", fp)
        ledger.mark_sent("stuck-key")  # 模拟发射后进程崩溃前的悬挂态
        result = run_once_async("whatever.yaml", idempotency_key="stuck-key",
                                receipt_ledger=ledger)
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert all(isinstance(e, str) for e in result["errors"])
        assert result["receipt_outcome"] == OUTCOME_UNKNOWN
        assert result["receipt_id"]
        assert result["diagnostics"]["entry_state"] == "sent"

    def test_run_once_async_payload_mismatch_rejected_envelope(self, tmp_path):
        from rfauto.service.api import run_once_async
        from rfauto.service.job_registry import get_job_registry

        ledger = RequestReceiptLedger()
        recipe = _recipe(tmp_path)
        r1 = run_once_async(recipe, idempotency_key="kk",
                            idempotency_payload={"v": 1},
                            receipt_ledger=ledger)
        get_job_registry().wait(r1["job_id"], timeout_s=120)
        r2 = run_once_async(recipe, idempotency_key="kk",
                            idempotency_payload={"v": 2},
                            receipt_ledger=ledger)
        assert r2["ok"] is False
        assert r2["receipt_outcome"] == OUTCOME_REJECTED
        assert isinstance(r2["errors"], list)

    def test_remote_oe_sync_receipt_completed_then_snapshot_replay(
            self, tmp_path, monkeypatch):
        t1 = _FakeTransport(exec_rc=0)
        _remote_harness(monkeypatch, t1)
        ledger = RequestReceiptLedger()
        env1 = remote_oe_run("lab_server", _seat_spec(),
                             out_dir=tmp_path / "pull1",
                             receipt_key="oe-job-1", receipt_ledger=ledger)
        assert env1["ok"] is True and env1["verdict"] == "PASS"
        assert env1["receipt_outcome"] == OUTCOME_COMPLETED
        assert "receipt_id" not in env1, "确定终态信封不冒充回执号诊断键"
        # 同键同载荷第二次 → 快照重放，零发射零 SSH 命令
        t2 = _FakeTransport(exec_rc=0)
        monkeypatch.setattr(roe, "SshTransport", lambda c: t2)
        env2 = remote_oe_run("lab_server", _seat_spec(),
                             out_dir=tmp_path / "pull2",
                             receipt_key="oe-job-1", receipt_ledger=ledger)
        assert env2["ok"] is True
        assert env2["idempotent_replay"] is True
        assert env2["receipt_outcome"] == OUTCOME_COMPLETED
        assert env2["replayed_envelope"]["verdict"] == "PASS"
        assert t2.launch_calls == 0 and t2.commands == [], \
            "快照重放不得再触碰通道"

    def test_remote_oe_send_then_fault_unknown_envelope_and_poison(
            self, tmp_path, monkeypatch):
        """发射命令抛错（发送后归属不可证）→ unknown 信封 + 车道毒化。"""
        t = _FakeTransport(fail_on="cmd /c")
        _remote_harness(monkeypatch, t)
        ledger = RequestReceiptLedger()
        env = remote_oe_run("lab_server", _seat_spec(),
                            out_dir=tmp_path / "pull",
                            receipt_key="oe-flaky", receipt_ledger=ledger)
        assert env["ok"] is False
        assert env["receipt_outcome"] == OUTCOME_UNKNOWN
        assert env["receipt_id"]
        assert isinstance(env["errors"], list) and env["errors"]
        assert ledger.lane_state("remote_oe:lab_server")["poisoned"] is True
        assert t.launch_calls == 0
        # 同键重试 → unknown 拒绝重放（不重执行；毒化中探针不可达=直接拒）
        t2 = _FakeTransport()
        monkeypatch.setattr(roe, "SshTransport", lambda c: t2)
        monkeypatch.setattr(
            roe, "probe_machine",
            lambda c: {"name": c.name, "reachable": False, "ports": {}},
        )
        env2 = remote_oe_run("lab_server", _seat_spec(),
                             out_dir=tmp_path / "pull2",
                             receipt_key="oe-flaky", receipt_ledger=ledger)
        assert env2["ok"] is False
        assert env2["receipt_outcome"] in (OUTCOME_UNKNOWN, OUTCOME_REJECTED)
        assert t2.launch_calls == 0

    def test_remote_oe_pre_send_fault_not_started_and_retry_allowed(
            self, tmp_path, monkeypatch):
        """发射前（建目录段）失败 → not_started；条目回收，健康通道重试放行。"""
        t_bad = _FakeTransport(fail_on="New-Item")
        _remote_harness(monkeypatch, t_bad)
        ledger = RequestReceiptLedger()
        env = remote_oe_run("lab_server", _seat_spec(),
                            out_dir=tmp_path / "pull",
                            receipt_key="oe-pre", receipt_ledger=ledger)
        assert env["ok"] is False
        assert env["receipt_outcome"] == OUTCOME_NOT_STARTED
        assert ledger.peek("oe-pre") is None, "未发射条目回收"
        assert ledger.lane_state("remote_oe:lab_server")["poisoned"] is False
        t_good = _FakeTransport(exec_rc=0)
        monkeypatch.setattr(roe, "SshTransport", lambda c: t_good)
        env2 = remote_oe_run("lab_server", _seat_spec(),
                             out_dir=tmp_path / "pull2",
                             receipt_key="oe-pre", receipt_ledger=ledger)
        assert env2["ok"] is True and env2["verdict"] == "PASS"
        assert env2["receipt_outcome"] == OUTCOME_COMPLETED
        assert t_good.launch_calls == 1

    def test_remote_oe_lane_poison_probe_resync_releases_new_key(
            self, tmp_path, monkeypatch):
        """毒化中探针可达 → 自动重同步放行新键；unknown 旧键仍须对账。"""
        t_bad = _FakeTransport(fail_on="cmd /c")
        _remote_harness(monkeypatch, t_bad)
        ledger = RequestReceiptLedger()
        remote_oe_run("lab_server", _seat_spec(), out_dir=tmp_path / "p1",
                      receipt_key="old", receipt_ledger=ledger)
        assert ledger.lane_state("remote_oe:lab_server")["poisoned"] is True
        # 探针可达 → 通道内自动 resync → 新键放行
        t_good = _FakeTransport(exec_rc=0)
        monkeypatch.setattr(roe, "SshTransport", lambda c: t_good)
        env_new = remote_oe_run("lab_server", _seat_spec(),
                                out_dir=tmp_path / "p2",
                                receipt_key="fresh", receipt_ledger=ledger)
        assert env_new["ok"] is True
        assert env_new["receipt_outcome"] == OUTCOME_COMPLETED
        assert ledger.lane_state("remote_oe:lab_server")["poisoned"] is False
        # 旧 unknown 键：不自动重放
        env_old = remote_oe_run("lab_server", _seat_spec(),
                                out_dir=tmp_path / "p3",
                                receipt_key="old", receipt_ledger=ledger)
        assert env_old["ok"] is False
        assert env_old["receipt_outcome"] == OUTCOME_UNKNOWN

    def test_remote_oe_receipt_key_poll_mode_rejected(self, tmp_path,
                                                      monkeypatch):
        """receipt_key × poll 档 = fail-closed 拒绝（不静默忽略）。"""
        t = _FakeTransport()
        _remote_harness(monkeypatch, t)
        env = remote_oe_run("lab_server", _seat_spec(),
                            out_dir=tmp_path / "pull", wait_mode="poll",
                            receipt_key="oe-x", receipt_ledger=RequestReceiptLedger())
        assert env["ok"] is False
        assert env["receipt_outcome"] == OUTCOME_REJECTED
        assert isinstance(env["errors"], list)
        assert t.launch_calls == 0

    def test_receipt_decision_is_frozen_value_object(self):
        import dataclasses
        d = ReceiptDecision(outcome=OUTCOME_NOT_STARTED, key="k", fingerprint="f")
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.outcome = OUTCOME_FAILED  # type: ignore[misc]

    def test_uncertain_marker_types_are_importable_and_distinct(self):
        assert not issubclass(NotSentError, UncertainOutcomeError)
        assert issubclass(NotSentError, Exception)
        assert issubclass(UncertainOutcomeError, Exception)
