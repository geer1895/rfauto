"""remote_scheduler_service 单测（E-06/PR-15 调度面 v1 切片，2026-10-08）。

全离线（#139：进程探测/SSH 通道一律 monkeypatch 桩钉死，绝不真连网真枚举）。
覆盖：resources_view 本机两通道互斥态与 #105 降级 unknown、登记机器可达性/
在跑进程数/磁盘余量、凭据缺失不猜不试、信封契约（恒 ok=True + 凭据/主机名
不落信封）、queue_view 注册表×单写锁×席位×服务器在途态合并、CLI 两叶接线。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_scheduler_service as rss
from rfauto.infra.remote_machines import RemoteMachineConfig
from rfauto.service.job_registry import (
    ENV_JOB_REGISTRY_DB,
    get_job_registry,
    get_write_lock,
    reset_job_registry,
)
from rfauto.service.remote_scheduler_service import (
    HFSS_MUTEX_FINGERPRINT,
    OE_MUTEX_FINGERPRINT,
    _count_hits,
    _drive_letter_of,
    local_hfss_view,
    local_openems_view,
    queue_view,
    remote_resources,
    resources_view,
)


def _one_machine(monkeypatch, **kw) -> RemoteMachineConfig:
    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", ssh_port=22,
        hfss_grpc_port=50051,
        hfss_project_root=kw.pop("project_root", "E:\\rfauto_remote"),
        probe_ports=kw.pop("probe_ports", {"rdp": 3389}),
        **kw,
    )
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {"sim_host": cfg})
    return cfg


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """纯内存注册表 + 单写锁还原（#144 隔离；持久化 env 清空整集合）。"""
    monkeypatch.delenv(ENV_JOB_REGISTRY_DB, raising=False)
    reset_job_registry()
    yield
    reset_job_registry()


# ─── 纯函数（指纹/协议行/盘符） ───────────────────────────────────────────────

def test_count_hits_only_protocol_lines():
    out = "42|python.exe -u _rfauto_runner.py\n" \
          "探针 census header line\n" \
          "mutex CLEAR\n" \
          "7|python.exe simulation.py\n"
    assert _count_hits(out) == 2
    assert _count_hits("") == 0


def test_oe_fingerprint_no_cli_self_hit():
    """#261 自锁红线：本 CLI 调用链命令行不落 OE 指纹（自排除语义钉）。"""
    import re

    for cmdline in ("python.exe rfauto remote resources",
                    "python.exe -m pytest tests/unit",):
        assert re.search(OE_MUTEX_FINGERPRINT, cmdline) is None, cmdline
    assert re.search(OE_MUTEX_FINGERPRINT,
                     "python.exe -u _rfauto_runner.py") is not None


def test_drive_letter_of():
    assert _drive_letter_of("E:\\rfauto_remote") == "E:"
    assert _drive_letter_of("e:/rfauto_remote") == "E:"
    assert _drive_letter_of("") is None
    assert _drive_letter_of("relative/path") is None


# ─── 本机进程互斥态（探测桩，零真枚举） ──────────────────────────────────────

def test_local_openems_counts(monkeypatch):
    monkeypatch.setattr(rss, "_ps_capture",
                        lambda cmd, timeout_s=30.0: (True, "42|python x\njunk\n"))
    view = local_openems_view()
    assert view == {"state": "ok", "busy": True, "n_procs": 1, "reason": None}


def test_local_openems_idle(monkeypatch):
    monkeypatch.setattr(rss, "_ps_capture", lambda cmd, timeout_s=30.0: (True, ""))
    view = local_openems_view()
    assert view["state"] == "ok" and view["busy"] is False and view["n_procs"] == 0


def test_local_openems_degrades_unknown(monkeypatch):
    """枚举失败 → unknown（#105：宁 unknown 不阻塞，信封不炸）。"""
    monkeypatch.setattr(rss, "_ps_capture",
                        lambda cmd, timeout_s=30.0: (False, "TimeoutExpired: x"))
    view = local_openems_view()
    assert view["state"] == "unknown" and view["busy"] is None
    assert view["reason"]


def test_local_hfss_view_idle_busy(monkeypatch):
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
    assert local_hfss_view()["busy"] is False
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [
        {"pid": 1, "ppid": 2, "cmdline": "ansysedt.exe -grpcsrv h:50051:InsecureMode"}])
    view = local_hfss_view()
    assert view["state"] == "ok" and view["busy"] is True
    assert view["n_procs"] == 1 and view["n_grpcsrv"] == 1


def test_local_hfss_view_degrades_unknown(monkeypatch):
    def _boom():
        raise RuntimeError("枚举超时")

    monkeypatch.setattr(rss, "list_ansysedt_processes", _boom)
    view = local_hfss_view()
    assert view["state"] == "unknown" and view["reason"]


# ─── 登记机器资源面（SSH 桩，#139 零真连网） ─────────────────────────────────

class _FakeTransport:
    """SSH 桩：按命令内容分发 canned 输出（互斥 python/ansysedt/磁盘）。"""

    instances: ClassVar[list[_FakeTransport]] = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.commands: list[str] = []
        self.closed = False
        _FakeTransport.instances.append(self)

    def connect(self) -> None:
        pass

    def run_command(self, cmd: str, timeout_s: float = 30.0):
        self.commands.append(cmd)
        if "Win32_LogicalDisk" in cmd:
            return 0, "E:|107374182400\n", ""
        if "'python.exe'" in cmd:
            return 0, "101|python.exe -u _rfauto_runner.py\nno-protocol\n", ""
        if "'ansysedt.exe'" in cmd:
            return 0, "55|ansysedt.exe -grpcsrv 10.20.30.40:50051:InsecureMode\n", ""
        return 0, "", ""

    def close(self) -> None:
        self.closed = True


def _probe_ok(cfg):
    return {"name": cfg.name, "host": cfg.host, "reachable": True,
            "ports": {"rdp": {"port": 3389, "open": True, "latency_ms": 1.2}},
            "probe_s": 0.01}


def test_remote_full_paths(monkeypatch):
    _one_machine(monkeypatch, ssh_user="u", ssh_password="sekret-pw")
    monkeypatch.setattr(rss, "probe_machine", _probe_ok)
    monkeypatch.setattr(rss, "SshTransport", _FakeTransport)
    _FakeTransport.instances = []
    view = remote_resources("sim_host")
    assert view["machine"] == "sim_host"
    assert view["reachable"] is True
    assert view["ssh"] == {"auth": "ok"}
    assert view["openems"]["n_procs"] == 1 and view["openems"]["busy"] is True
    assert view["hfss"]["n_procs"] == 1 and view["hfss"]["busy"] is True
    assert view["disk"] == {"state": "ok", "free_gb": 100.0, "drive": "E:",
                            "reason": None}
    assert view["n_tasks"] == 2
    assert view["state"] == "ok"
    # 凭据/主机名不落信封（任务书铁律；transport 桩已收尾）
    blob = json.dumps(view, ensure_ascii=False, default=str)
    assert "10.20.30.40" not in blob
    assert "sekret-pw" not in blob
    assert _FakeTransport.instances and _FakeTransport.instances[0].closed


def test_remote_missing_credentials_no_ssh(monkeypatch):
    """凭据缺失：如实 missing_credentials，且绝不发起 SSH（构造即炸桩）。"""
    _one_machine(monkeypatch)
    monkeypatch.delenv("RFAUTO_REMOTE_SSH_USER", raising=False)
    monkeypatch.delenv("RFAUTO_REMOTE_SSH_PASSWORD", raising=False)

    class _NoSsh:
        def __init__(self, _cfg):
            raise AssertionError("凭据缺失不得构造 SSH 通道（不猜不试）")

    monkeypatch.setattr(rss, "probe_machine", _probe_ok)
    monkeypatch.setattr(rss, "SshTransport", _NoSsh)
    view = remote_resources(None)
    assert view["ssh"] == {"auth": "missing_credentials"}
    for face in (view["openems"], view["hfss"], view["disk"]):
        assert face["state"] == "unknown" and face["reason"]
    assert view["n_tasks"] is None and view["state"] == "unknown"


def test_remote_unreachable_skips_ssh(monkeypatch):
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rss, "probe_machine", lambda c: {
        "name": c.name, "host": c.host, "reachable": False, "ports": {},
        "probe_s": 0.01})

    class _NoSsh:
        def __init__(self, _cfg):
            raise AssertionError("不可达不得发起 SSH")

    monkeypatch.setattr(rss, "SshTransport", _NoSsh)
    view = remote_resources("sim_host")
    assert view["reachable"] is False and view["state"] == "unknown"
    assert view["openems"]["state"] == "unknown"


def test_remote_ssh_connect_failure_degrades(monkeypatch):
    """SSH 链路裸抛 → 整面 unknown、信封不炸（#105 fail-soft）。"""
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rss, "probe_machine", _probe_ok)

    class _DeadTransport(_FakeTransport):
        def connect(self):
            raise RuntimeError("channel closed")

    monkeypatch.setattr(rss, "SshTransport", _DeadTransport)
    view = remote_resources("sim_host")
    assert view["state"] == "unknown"
    assert view["ssh"] == {"auth": "failed", "error": "RuntimeError"}
    assert view["n_tasks"] is None


def test_remote_query_rc_nonzero_degrades(monkeypatch):
    """互斥/磁盘查询 rc≠0 → 对应子面 unknown（验不了=不凑数）。"""
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rss, "probe_machine", _probe_ok)

    class _Rc1(_FakeTransport):
        def run_command(self, cmd, timeout_s=30.0):
            return 1, "", "boom"

    monkeypatch.setattr(rss, "SshTransport", _Rc1)
    view = remote_resources("sim_host")
    for face in (view["openems"], view["hfss"], view["disk"]):
        assert face["state"] == "unknown"
    assert view["n_tasks"] is None and view["state"] == "unknown"


def test_remote_probe_raises_degrades_reachable(monkeypatch):
    """探活异常 → reachable=None、不发起 SSH 面查询（降级 unknown）。"""
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p")

    def _boom(_cfg):
        raise OSError("net down")

    monkeypatch.setattr(rss, "probe_machine", _boom)
    view = remote_resources("sim_host")
    assert view["reachable"] is None
    assert view["openems"]["state"] == "unknown"


def test_remote_no_machines_view(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    view = remote_resources(None)
    assert view["machine"] is None and view["state"] == "no_machine"


def test_remote_n_tasks_not_faked_when_partial(monkeypatch):
    """磁盘面降级：n_tasks 仍按两通道 census 计（磁盘与进程数无关），
    state=partial、reason 留痕。"""
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p",
                 project_root="relative/no/drive")
    monkeypatch.setattr(rss, "probe_machine", _probe_ok)
    monkeypatch.setattr(rss, "SshTransport", _FakeTransport)
    view = remote_resources("sim_host")
    assert view["openems"]["n_procs"] == 1
    assert view["disk"]["state"] == "unknown"  # 无盘符
    assert view["n_tasks"] == 2 and view["state"] == "partial"
    assert view["reason"] and "disk" in view["reason"]


# ─── resources_view 聚合信封 ────────────────────────────────────────────────

def test_resources_view_envelope_contract(monkeypatch):
    """信封契约：ok 恒 True 且首键；子面降级不翻 ok（#105）。"""
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    monkeypatch.setattr(rss, "_ps_capture",
                        lambda cmd, timeout_s=30.0: (False, ""))
    monkeypatch.setattr(
        rss, "list_ansysedt_processes",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    env = resources_view(None)
    assert next(iter(env)) == "ok" and env["ok"] is True
    assert set(env["local"]) == {"openems", "hfss"}
    assert env["local"]["openems"]["state"] == "unknown"
    assert env["local"]["hfss"]["state"] == "unknown"
    assert env["remote"]["state"] == "no_machine"


def test_resources_view_happy_local(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    monkeypatch.setattr(rss, "_ps_capture", lambda cmd, timeout_s=30.0: (True, ""))
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
    env = resources_view(None)
    assert env["ok"] is True
    assert env["local"]["openems"]["n_procs"] == 0
    assert env["local"]["hfss"]["busy"] is False


# ─── queue_view（注册表 × 单写锁 × 席位 × 服务器在途态） ─────────────────────

def test_registry_snapshots_read_view():
    reg = get_job_registry()
    reg.create("job_a")
    reg.create("job_b")
    reg.create("job_c")
    reg.finish("job_b", run_id="run_b")
    reg.cancel("job_c")  # 未开始 → 直接 cancelled
    snaps = reg.snapshots()
    assert [s["job_id"] for s in snaps] == ["job_a", "job_b", "job_c"]
    active = reg.snapshots(active_only=True)
    assert [s["job_id"] for s in active] == ["job_a"]
    # 与 get 同形（_snapshot 单源）
    assert reg.snapshots()[1] == reg.get("job_b")


def test_queue_view_merges_registry_seats_remote(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    reg = get_job_registry()
    reg.create("job_a")
    reg.assign_seats("job_a", ("solver:hfss",))
    reg.set_progress("job_a", 40.0, "solve")
    reg.create("job_b")
    reg.finish("job_b", run_id="run_b")
    env = queue_view(None)
    assert env["ok"] is True
    assert env["counts"] == {"n_jobs": 2, "n_active": 1, "n_waiting": 0}
    assert env["write_lock"] == {"owner": None, "queue_length": 0}
    assert env["seat_occupancy"] == {"solver:hfss": ["job_a"]}
    rows = {r["job_id"]: r for r in env["jobs"]}
    assert rows["job_a"]["state"] == "running"
    assert rows["job_a"]["stage"] == "solve"
    assert rows["job_b"]["run_id"] == "run_b"
    for row in env["jobs"]:  # 瘦形：结果载荷不入队列视图
        assert "result" not in row
    assert env["remote"]["state"] == "no_machine"


def test_queue_view_reflects_write_lock(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    reg = get_job_registry()
    reg.create("job_lock")
    lock = get_write_lock()
    assert lock.acquire("job_lock", timeout_s=1.0) is True
    try:
        env = queue_view(None)
        assert env["write_lock"]["owner"] == "job_lock"
        assert env["counts"]["n_waiting"] == 0
    finally:
        lock.release("job_lock")
    assert queue_view(None)["write_lock"]["owner"] is None


def test_queue_view_remote_busy_passthrough(monkeypatch):
    """服务器在途态原样透传（busy census 合并进队列视图）。"""
    _one_machine(monkeypatch, ssh_user="u", ssh_password="p")
    monkeypatch.setattr(rss, "probe_machine", _probe_ok)
    monkeypatch.setattr(rss, "SshTransport", _FakeTransport)
    env = queue_view("sim_host")
    assert env["remote"]["n_tasks"] == 2
    assert "10.20.30.40" not in json.dumps(env, default=str)


# ─── CLI 两叶接线（--json 信封 + human 表格；服务注入 #139） ─────────────────

from rfauto.cli.main import app as root_app

_runner = CliRunner()


def _remote_leaves() -> dict[str, bool]:
    import inspect

    for g in root_app.registered_groups:
        if g.name == "remote":
            inst = getattr(g, "typer_instance", None) or g
            out = {}
            for info in inst.registered_commands:
                sig = inspect.signature(info.callback)
                out[info.name] = any("json" in p for p in sig.parameters)
            return out
    raise AssertionError("remote 子应用未注册")


def test_cli_remote_leaves_registered_with_json():
    leaves = _remote_leaves()
    assert leaves.get("probe") is True and leaves.get("status") is True
    assert leaves.get("resources") is True and leaves.get("queue") is True


def test_cli_resources_json_offline_real(monkeypatch):
    """remote resources --json：零登记+探测桩的真实离线路径（非注入）。"""
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    monkeypatch.setattr(rss, "_ps_capture", lambda cmd, timeout_s=30.0: (True, ""))
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
    r = _runner.invoke(root_app, ["remote", "resources", "--json"])
    assert r.exit_code == 0, r.output[:400]
    payload = json.loads(r.output[r.output.index("{"):])
    assert payload["ok"] is True
    assert payload["remote"]["machine"] is None


def test_cli_resources_json_failure_envelope(monkeypatch):
    """服务失败信封 → _emit 同构失败出口（exit 1）。"""
    monkeypatch.setattr(rss, "resources_view",
                        lambda machine: {"ok": False, "errors": ["注入失败"]})
    r = _runner.invoke(root_app, ["remote", "resources", "--json"])
    assert r.exit_code == 1
    payload = json.loads(r.output[r.output.index("{"):])
    assert payload["ok"] is False and payload["errors"]


def test_cli_resources_human_table(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    monkeypatch.setattr(rss, "_ps_capture", lambda cmd, timeout_s=30.0: (True, ""))
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
    r = _runner.invoke(root_app, ["remote", "resources"])
    assert r.exit_code == 0, r.output[:400]
    assert "资源视图" in r.output and "no_machine" in r.output


def test_cli_queue_json_offline_real(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    r = _runner.invoke(root_app, ["remote", "queue", "--json"])
    assert r.exit_code == 0, r.output[:400]
    payload = json.loads(r.output[r.output.index("{"):])
    assert payload["ok"] is True
    assert set(payload) >= {"jobs", "counts", "write_lock",
                            "seat_occupancy", "remote"}


def test_cli_queue_human(monkeypatch):
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    r = _runner.invoke(root_app, ["remote", "queue"])
    assert r.exit_code == 0, r.output[:400]
    assert "任务队列" in r.output


# 防误用哨兵：指纹常量被发射面误改时本文件先红（视图与发射互斥同语义家族）
def test_fingerprint_family_semantics():
    assert "grpcsrv" in HFSS_MUTEX_FINGERPRINT
    assert "_rfauto_runner" in OE_MUTEX_FINGERPRINT
