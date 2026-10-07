"""多机协同 v0——service/remote_service 单测（全离线，#139 通道 monkeypatch 钉死）。

覆盖：probe/status 信封、无登记零行为变化、凭据缺失如实 missing、
hfss_remote_session_config 组装与拒绝路径、真机冒烟 env 门（unit 门
内必拒绝，绝不真连网）。
"""

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_service as rs
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteConfigError,
    RemoteMachineConfig,
)
from rfauto.service.remote_service import (
    hfss_remote_session_config,
    remote_hfss_smoke,
    remote_probe,
    remote_status,
)


def _one_machine(monkeypatch, **kw):
    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", ssh_port=22,
        hfss_grpc_port=50051,
        hfss_project_root=kw.get("project_root", "E:\\rfauto_remote"),
        probe_ports={"rdp": 3389},
        **{k: v for k, v in kw.items() if k != "project_root"},
    )
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"sim_host": cfg})
    return cfg


# ─── remote_probe ─────────────────────────────────────────────────────────


def test_probe_no_machines_empty_envelope(monkeypatch):
    """零配置零行为变化：无登记=空 machines 列表，不报错。"""
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {})
    out = remote_probe(None)
    assert out == {"ok": True, "machines": []}


def test_probe_envelope_structure(monkeypatch):
    _one_machine(monkeypatch)
    monkeypatch.setattr(rs, "probe_machine", lambda cfg: {
        "name": cfg.name, "host": cfg.host, "reachable": True,
        "ports": {}, "probe_s": 0.01,
    })
    out = remote_probe("sim_host")
    assert out["ok"] is True
    assert out["machines"][0]["name"] == "sim_host"
    assert out["machines"][0]["reachable"] is True


def test_probe_unknown_machine_raises(monkeypatch):
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {})
    with pytest.raises(RemoteConfigError):
        remote_probe("nope")


# ─── remote_status（#139：SSH 通道 mock，绝不真连网） ─────────────────────


def test_status_missing_credentials_no_ssh(monkeypatch):
    """凭据缺失：如实 missing_credentials，且不发起 SSH 连接。"""
    _one_machine(monkeypatch)
    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(ENV_REMOTE_SSH_PASSWORD, raising=False)
    import rfauto.service.remote_service as rsvc

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得发起 SSH 连接")

    monkeypatch.setattr(rsvc, "SshTransport", _boom)
    out = remote_status("sim_host")
    m = out["machines"][0]
    assert m["ssh"]["auth"] == "missing_credentials"
    assert "RFAUTO_REMOTE_SSH_USER" in m["ssh"]["hint"]


def test_status_ssh_ok_via_mock_channel(monkeypatch):
    """凭据齐：SSH 通道走 mock transport（#139），ok 判定按命令回执。"""
    _one_machine(monkeypatch)
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "member01")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "secret")

    class FakeTransport:
        def __init__(self, cfg):
            self.cfg = cfg

        def connect(self):
            self.connected = True

        def run_command(self, cmd, timeout_s=60.0):
            assert cmd == "echo rfauto_remote_ok"
            return 0, "rfauto_remote_ok\n", ""

        def close(self):
            self.closed = True

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    out = remote_status("sim_host")
    assert out["machines"][0]["ssh"] == {"auth": "ok", "rc": 0}


def test_status_ssh_failed_wrapped(monkeypatch):
    _one_machine(monkeypatch)
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "member01")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "secret")

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            raise ConnectionError("refused")

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    out = remote_status("sim_host")
    ssh = out["machines"][0]["ssh"]
    assert ssh["auth"] == "failed"
    # 凭据零泄漏：错误面只有异常类型名
    assert "secret" not in str(ssh)


# ─── hfss_remote_session_config ───────────────────────────────────────────


def test_session_config_none_when_unregistered(monkeypatch):
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {})
    assert hfss_remote_session_config(None) == {"ok": True, "remote": None}


def test_session_config_assembles_settings_delta(monkeypatch):
    cfg = _one_machine(monkeypatch)
    cfg.hfss_version = "2025.1"
    cfg.hfss_ansysedt_exe = "E:\\...\\ansysedt.exe"
    out = hfss_remote_session_config("sim_host")
    remote = out["remote"]
    assert remote["remote_machine"] == "sim_host"
    assert remote["machine"] == "10.20.30.40"
    assert remote["port"] == 50051
    assert remote["project_root"] == "E:\\rfauto_remote"
    assert remote["version"] == "2025.1"


def test_session_config_requires_project_root(monkeypatch):
    _one_machine(monkeypatch, project_root="")
    with pytest.raises(RemoteConfigError, match="project_root"):
        hfss_remote_session_config("sim_host")


# ─── remote_hfss_smoke（真机 env 门） ─────────────────────────────────────


def test_smoke_refuses_without_env_gate(monkeypatch):
    """真机冒烟必须显式 opt-in：unit 门内（env 未设）一律拒绝。"""
    monkeypatch.delenv(rs.REMOTE_SMOKE_ENV, raising=False)
    out = remote_hfss_smoke("sim_host")
    assert out["ok"] is False and out["skipped"] is True
    assert "RFAUTO_REMOTE_SMOKE" in out["reason"]


def test_smoke_missing_credentials_unknown(monkeypatch):
    """env 门开但凭据缺：steps.probe 有、ssh 如实 missing，不发起连接。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(ENV_REMOTE_SSH_PASSWORD, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得发起 SSH")

    # 守卫 patch 在实际消费点 rs.SshTransport（P3-7：冒烟链构造模块级
    # 导入名，patch irm.SshTransport 是空转守卫）。
    monkeypatch.setattr(rs, "SshTransport", _boom)
    monkeypatch.setattr(
        rs, "probe_machine",
        lambda cfg: {"name": cfg.name, "reachable": True, "ports": {}},
    )
    out = remote_hfss_smoke("sim_host")
    assert out["skipped"] is True
    assert out["steps"]["ssh"]["auth"] == "missing_credentials"


def test_smoke_missing_ansysedt_exe(monkeypatch):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    out = remote_hfss_smoke("sim_host")
    assert out["skipped"] is True
    assert "ansysedt_exe" in out["reason"]


# ─── L1 launch/cleanup 精确化（P2-1/P2-2，全 mock 通道） ──────────────────


def test_smoke_midway_failure_runs_cleanup(monkeypatch):
    """P2-1：launch 成功后链路裸抛 → 失败信封（fail-closed）+ finally 走
    服务器侧清理兜底（cleanup 自建 transport，L2 同构）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            return 0, "0\n", ""  # 进程查询/计数/任务清扫全零

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)

    def _boom(*a, **kw):
        raise RuntimeError("mock: sftp 上传裸抛")

    monkeypatch.setattr(rs, "_launch_grpcsrv", _boom)
    out = remote_hfss_smoke("sim_host")
    assert out["ok"] is False
    assert "L1 链路异常" in out["reason"] and "RuntimeError" in out["reason"]
    # cleanup 兜底被调且成功（无任务名→清扫路径；进程零匹配→0 杀）
    cleanup = out["steps"]["cleanup"]
    assert cleanup["ok"] is True
    assert cleanup["steps"]["ansysedt_grpcsrv_pids"] == []
    assert cleanup["steps"]["ansysedt_after"] == 0


def test_launch_grpcsrv_task_name_unique_and_recorded(monkeypatch):
    """P2-2：schtasks 任务名带唯一后缀（并发冒烟不互踩），launch 早期
    登记进 steps（部分失败路径也带名，cleanup 据此精确删）。"""
    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", hfss_grpc_port=50051,
        hfss_project_root="E:\\rfauto_remote",
        hfss_ansysedt_exe="E:\\x\\ansysedt.exe",
    )
    cmds_seen: list[str] = []

    class FakeTransport:
        def run_command(self, cmd, timeout_s=60.0):
            cmds_seen.append(cmd)
            return 0, "", ""

        def upload_file(self, local, remote):
            pass

    monkeypatch.setattr(
        "rfauto.infra.remote_machines.probe_port",
        lambda *a, **k: (True, 0.5),
    )
    steps1: dict = {}
    steps2: dict = {}
    assert rs._launch_grpcsrv(cfg, FakeTransport(), steps1, 5.0) is None
    assert rs._launch_grpcsrv(cfg, FakeTransport(), steps2, 5.0) is None
    n1 = steps1["schtasks"]["task_name"]
    n2 = steps2["schtasks"]["task_name"]
    assert n1 != n2  # 唯一后缀
    assert n1.startswith("RFAuto\\grpcsrv_smoke_")
    create_or_run = [c for c in cmds_seen if "schtasks" in c]
    assert sum(n1 in c for c in create_or_run) == 2  # create+run 同名
    assert steps1["grpc_port"] == {"port": 50051, "open": True}


def test_cleanup_kills_only_grpcsrv_port_matched_pids(monkeypatch):
    """P2-2：cleanup 按 PID 精确杀——只杀命令行含 -grpcsrv 且含本机端口
    指纹的实例；他人 GUI/其他端口 grpcsrv 不碰；全杀 /IM 禁绝。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    commands: list[str] = []

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            commands.append(cmd)
            if "Win32_Process" in cmd:
                return 0, (
                    '111|"E:\\x\\ansysedt.exe" -grpcsrv '
                    '10.20.30.40:50051:InsecureMode\n'
                    '222|"E:\\x\\ansysedt.exe" \n'          # 他人 GUI 实例
                    '333|"E:\\x\\ansysedt.exe" -grpcsrv '
                    '10.20.30.40:50052:InsecureMode\n'  # 其他端口
                ), ""
            return 0, "2\n", ""

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    out = rs.remote_hfss_cleanup("sim_host", grpc_match=":50051:")
    assert out["ok"] is True
    steps = out["steps"]
    assert steps["ansysedt_grpcsrv_pids"] == ["111"]
    kill_cmds = [c for c in commands if c.startswith("taskkill")]
    assert len(kill_cmds) == 1
    assert "/PID 111" in kill_cmds[0]
    assert "222" not in kill_cmds[0] and "333" not in kill_cmds[0]
    assert not any("/IM" in c for c in commands)  # 全杀禁绝
    assert steps["ansysedt_after"] == 2           # 杀后复数如实（含他人实例）
    assert steps["deleted_tasks"] == []           # 无 task_name → 清扫零残留


def test_cleanup_zero_grpcsrv_match_honest_zero_kill(monkeypatch):
    """P2-2：无匹配实例=0 杀如实上报，不发 taskkill。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    commands: list[str] = []

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            commands.append(cmd)
            if "Win32_Process" in cmd:
                return 0, '222|"E:\\x\\ansysedt.exe" \n', ""
            return 0, "1\n", ""

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    out = rs.remote_hfss_cleanup("sim_host", grpc_match=":50051:")
    assert out["ok"] is True
    assert out["steps"]["ansysedt_grpcsrv_pids"] == []
    assert not any(c.startswith("taskkill") for c in commands)
    assert out["steps"]["ansysedt_after"] == 1


def test_cleanup_deletes_recorded_task_name_only(monkeypatch):
    """P2-2：task_name 给定时只删该唯一名，不走清扫查询（并发冒烟不互踩）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    commands: list[str] = []

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            commands.append(cmd)
            return 0, "0\n", ""

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    name = "RFAuto\\grpcsrv_smoke_ab12cd34"
    out = rs.remote_hfss_cleanup("sim_host", task_name=name,
                                 grpc_match=":50051:")
    assert out["ok"] is True
    deletes = [c for c in commands if "schtasks /delete" in c]
    assert deletes == [f'schtasks /delete /f /tn "{name}"']
    assert not any("Select-String" in c for c in commands)  # 无清扫查询
    assert out["steps"]["deleted_tasks"] == [name]


# ─── #261 互斥预检共享单源 + HFSS 通道接线（X4 批推广，全 mock） ───────────


def test_remote_mutex_command_shape():
    """共享单源命令形态：进程域/指纹注入+零双引号（G5）。"""
    cmd = rs.remote_mutex_command("ansysedt.exe", r"grpcsrv.*:50051:")
    assert "Get-CimInstance Win32_Process" in cmd
    assert "$_.Name -eq 'ansysedt.exe'" in cmd
    assert "$_.CommandLine -match 'grpcsrv.*:50051:'" in cmd
    assert "'{0}|{1}' -f $_.ProcessId, $_.CommandLine" in cmd
    assert '"' not in cmd  # G5 零双引号
    # OE 通道委托同源（remote_oe_service.build_mutex_command 薄委托）
    from rfauto.service.remote_oe_service import (
        build_mutex_command as oe_build,
    )

    assert oe_build("x\\.py") == rs.remote_mutex_command("python.exe", "x\\.py")


class _MutexFakeTransport:
    """互斥预检单测通道：直查/旁证应答可注入。"""

    def __init__(self, hits=None, rc=0, probe="mutex CLEAR\n"):
        self.hits = hits or []
        self.rc = rc
        self.probe = probe
        self.commands: list[str] = []

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        if "-eq 'python.exe'" in cmd or "-eq 'ansysedt.exe'" in cmd:
            return self.rc, "".join(f"{h}\n" for h in self.hits), ""
        if "run_server_probe.ps1" in cmd:
            return 0, self.probe, ""
        raise AssertionError(f"未预期命令: {cmd[:80]}")


def test_mutex_precheck_clear_and_command_shape():
    """直查零命中+旁证 CLEAR → 不忙；命令含进程域与指纹。"""
    t = _MutexFakeTransport()
    out = rs.remote_mutex_precheck(
        t, "E:\\rfauto_remote",
        process_name="ansysedt.exe", fingerprint=r"grpcsrv.*:50051:")
    assert out["busy"] is False and out["fail_closed"] is False
    assert out["hits"] == [] and out["reason"] is None
    assert len(t.commands) == 2  # 直查+旁证各一次
    assert "-eq 'ansysedt.exe'" in t.commands[0]
    assert "run_server_probe.ps1" in t.commands[1]


def test_mutex_precheck_strict_pid_lines_no_false_hit():
    """命中行按 pid| 协议严格解析：非协议行（计数/census 残片）不误判忙。"""
    t = _MutexFakeTransport(hits=["0", "census tail"])
    out = rs.remote_mutex_precheck(
        t, "E:\\rfauto_remote",
        process_name="ansysedt.exe", fingerprint="x")
    assert out["busy"] is False and out["hits"] == []


def test_mutex_precheck_hit_is_busy_no_kill():
    t = _MutexFakeTransport(
        hits=['4242|"E:\\x\\ansysedt.exe" -grpcsrv 10.20.30.40:50051:InsecureMode'])
    out = rs.remote_mutex_precheck(
        t, "E:\\rfauto_remote",
        process_name="ansysedt.exe", fingerprint=r"grpcsrv.*:50051:")
    assert out["busy"] is True and out["fail_closed"] is False
    assert out["hits"] and "候跑" in out["reason"] and "禁止代杀" in out["reason"]


def test_mutex_precheck_query_fail_failclosed():
    """直查 rc≠0（验不了）→ busy=True fail-closed（不冒充 CLEAR）。"""
    t = _MutexFakeTransport(rc=2)
    out = rs.remote_mutex_precheck(
        t, "E:\\rfauto_remote",
        process_name="ansysedt.exe", fingerprint="x")
    assert out["busy"] is True and out["fail_closed"] is True
    assert "fail-closed" in out["reason"]


def test_mutex_precheck_probe_busy_and_census_header():
    """旁证 BUSY 值行判忙；census 表头行（含 mutex 字样）不假忙（OE 回归钉同源）。"""
    t = _MutexFakeTransport(
        probe='BUSY: PID=8584 CMD="python" -u scripts\\varactor_smoke.py\n')
    out = rs.remote_mutex_precheck(
        t, "E:\\rfauto_remote", process_name="python.exe", fingerprint="x")
    assert out["busy"] is True and "旁证非 CLEAR" in out["reason"]
    t2 = _MutexFakeTransport(
        probe=("=== [6] current solver-process census (#261 mutex precheck) ===\n"
               "mutex CLEAR\n"))
    out2 = rs.remote_mutex_precheck(
        t2, "E:\\rfauto_remote", process_name="python.exe", fingerprint="x")
    assert out2["busy"] is False


def test_mutex_precheck_unsafe_workroot_skips_probe():
    """work_root 含单引号/空白 → 旁证跳过如实登记，权威直查不受影响。"""
    t = _MutexFakeTransport()
    out = rs.remote_mutex_precheck(
        t, "E:\\some dir",
        process_name="ansysedt.exe", fingerprint="x")
    assert out["busy"] is False
    assert len(t.commands) == 1  # 只发直查
    assert out["probe"]["skipped"] is True


class _SmokeMutexFakeTransport:
    """L1/L2 冒烟互斥通道：按进程域应答命中行，其余命令全零。"""

    def __init__(self, busy=True):
        self.busy = busy
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []

    def connect(self):
        pass

    def run_command(self, cmd, timeout_s=60.0):
        self.commands.append(cmd)
        if "-eq 'ansysedt.exe'" in cmd:
            if self.busy:
                hit = ('111|"E:\\x\\ansysedt.exe" -grpcsrv '
                       "10.20.30.40:50051:InsecureMode")
                return 0, f"{hit}\n", ""
            return 0, "", ""
        if "run_server_probe.ps1" in cmd:
            return 0, "mutex CLEAR\n", ""
        return 0, "0\n", ""

    def upload_file(self, local, remote):
        self.uploads.append((str(local), remote))

    def close(self):
        pass


def test_smoke_mutex_busy_skips_launch_and_cleanup_yields(monkeypatch):
    """L1 互斥命中=候跑 SKIP：不 launch 不上传；finally 清理让位（不代杀
    在跑实例——按端口指纹杀恰会命中他者会话，#261）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    t = _SmokeMutexFakeTransport(busy=True)
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: t)

    def _boom(*a, **kw):
        raise AssertionError("互斥候跑时不得进入 launch 段")

    monkeypatch.setattr(rs, "_launch_grpcsrv", _boom)
    out = remote_hfss_smoke("sim_host")
    assert out["ok"] is False and out["skipped"] is True
    assert "候跑" in out["reason"]
    assert out["steps"]["mutex"]["busy"] is True
    assert not t.uploads                                   # bat 未上传
    assert not any("schtasks" in c for c in t.commands)    # 未注册任务
    assert not any("taskkill" in c for c in t.commands)    # 零代杀
    # 清理让位：skipped 信封如实落账，无进程查询/杀命令
    cleanup = out["steps"]["cleanup"]
    assert cleanup["skipped"] is True and "候跑" in cleanup["reason"]


def test_smoke_mutex_clear_proceeds_to_launch(monkeypatch):
    """L1 互斥 CLEAR → 正常进入 launch（接线不改变既有放行路径）。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    t = _SmokeMutexFakeTransport(busy=False)
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: t)
    monkeypatch.setattr(rs, "_launch_grpcsrv",
                        lambda *a, **kw: None)  # launch 打桩成功
    monkeypatch.setattr(rs, "_attach_and_verify",
                        lambda cfg, steps: {"ok": True, "reason": None,
                                            "steps": steps})
    out = remote_hfss_smoke("sim_host")
    assert out["ok"] is True
    assert out["steps"]["mutex"]["busy"] is False
    # launch 已打桩：无 bat 上传（stub 直通），清理兜底照常放行
    assert not t.uploads
    assert out["steps"]["cleanup"]["ok"] is True


def test_l2_mutex_busy_skips_launch(monkeypatch, tmp_path):
    """L2 互斥命中=候跑 SKIP（L1 同构）：不建模不求解，清理让位。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    t = _SmokeMutexFakeTransport(busy=True)
    monkeypatch.setattr(rs, "SshTransport", lambda cfg: t)

    def _boom(*a, **kw):
        raise AssertionError("互斥候跑时不得进入建模/求解段")

    monkeypatch.setattr(rs, "_launch_grpcsrv", _boom)
    monkeypatch.setattr(rs, "_l2_model_solve_export", _boom)
    out = rs.remote_hfss_l2_smoke("sim_host", out_dir=str(tmp_path / "pull"))
    assert out["ok"] is False and out["skipped"] is True
    assert "候跑" in out["reason"]
    assert out["steps"]["mutex"]["busy"] is True
    assert not any("schtasks" in c for c in t.commands)
    assert out["steps"]["cleanup"]["skipped"] is True


# ─── remote_hfss_l2_smoke（真机 env 门 + mock 编排 + 判据纯函数） ──────────


def _synth_l2_net(eps_eff=2.8526, s11_mag=None, s21_db=-0.2, n_points=41):
    """合成 L2 判读语料：均匀线 S21=-βL 精确线性相位 + 端口失配小纹波 S11。"""
    import numpy as np
    import skrf as rf

    f_hz = np.linspace(2.0e9, 2.8e9, n_points)
    beta_l = 2 * np.pi * f_hz * np.sqrt(eps_eff) * 0.04 / 299792458.0
    if s11_mag is None:
        s11 = 0.02 * np.exp(1j * 0.3) + 0.02 * np.exp(-2j * beta_l)
    else:
        s11 = np.full(n_points, s11_mag, dtype=complex)
    s21 = (10 ** (s21_db / 20)) * np.exp(-1j * beta_l)
    s = np.empty((n_points, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    s[:, 1, 1] = s11
    return rf.Network(frequency=f_hz, s=s, z0=50)


def test_l2_refuses_without_env_gate(monkeypatch):
    monkeypatch.delenv(rs.REMOTE_SMOKE_ENV, raising=False)
    out = rs.remote_hfss_l2_smoke("sim_host")
    assert out["ok"] is False and out["skipped"] is True
    assert "RFAUTO_REMOTE_SMOKE" in out["reason"]


def test_l2_missing_credentials_unknown(monkeypatch):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.delenv(ENV_REMOTE_SSH_PASSWORD, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("凭据缺失时不得发起 SSH")

    # 守卫 patch 在实际消费点 rs.SshTransport（P3-7，同 L1）。
    monkeypatch.setattr(rs, "SshTransport", _boom)
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    out = rs.remote_hfss_l2_smoke("sim_host")
    assert out["skipped"] is True
    assert out["steps"]["ssh"]["auth"] == "missing_credentials"


def test_l2_missing_ansysedt_exe(monkeypatch):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch)
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    out = rs.remote_hfss_l2_smoke("sim_host")
    assert out["skipped"] is True
    assert "ansysedt_exe" in out["reason"]


def test_l2_missing_project_root(monkeypatch):
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    _one_machine(monkeypatch, project_root="", hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})
    out = rs.remote_hfss_l2_smoke("sim_host")
    assert out["skipped"] is True
    assert "project_root" in out["reason"]


def test_l2_judge_synthetic_pass():
    """判据纯函数：合成均匀线（εeff=2.8526 精确线性相位）→ 四判据全过。"""
    out = rs._judge_l2(_synth_l2_net())
    assert out["c1_readback"] is True
    assert out["c2_s11_min_db"] is True
    assert out["c3_s21_min_db"] is True
    assert out["c4_eps_eff_window"] is True
    # εeff 回收精度（#118：合成已知量→回收钉）：斜率精确线性 → 逐位回收
    assert abs(out["eps_eff_app"] - 2.8526) < 1e-3
    assert out["s11_db_min"] <= -10.0
    assert out["s21_db_min"] >= -1.0


def test_l2_judge_s11_fail():
    out = rs._judge_l2(_synth_l2_net(s11_mag=0.5))
    assert out["c2_s11_min_db"] is False
    assert out["s11_db_min"] == pytest.approx(-6.0, abs=0.1)


def test_l2_judge_s21_fail():
    out = rs._judge_l2(_synth_l2_net(s21_db=-3.0))
    assert out["c3_s21_min_db"] is False
    assert out["c2_s11_min_db"] is True  # 其余判据不受牵连（逐项如实）


def test_l2_judge_eps_eff_fail():
    out = rs._judge_l2(_synth_l2_net(eps_eff=4.2))
    assert out["c4_eps_eff_window"] is False
    assert out["eps_eff_app"] == pytest.approx(4.2, abs=0.05)


def test_l2_judge_readback_fail():
    """点数不符：c1 如实 False，数值判据 NaN 不参与。"""
    out = rs._judge_l2(_synth_l2_net(n_points=11))
    assert out["c1_readback"] is False
    assert out["n_points"] == 11


def test_l2_orchestration_mock_channel(monkeypatch, tmp_path):
    """L2 编排全通道 mock（#139）：Fake transport + 打桩建模/前置段，
    download 落合成 PASS Touchstone → verdict PASS + cleanup 走同一 Fake。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})

    net_pass = _synth_l2_net()

    class FakeTransport:
        def __init__(self, cfg):
            self.cfg = cfg

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            if cmd.startswith("Test-Path"):
                return 0, "True\n", ""
            return 0, "0\n", ""  # Get-Process 计数（清理前后均 0）

        def upload_file(self, local, remote):
            pass

        def download_file(self, remote, local):
            from pathlib import Path as StdPath

            p = StdPath(local)
            p.parent.mkdir(parents=True, exist_ok=True)
            net_pass.write_touchstone(str(p))

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    monkeypatch.setattr(rs, "_launch_grpcsrv", lambda *a, **kw: None)
    monkeypatch.setattr(
        rs, "_l2_model_solve_export",
        lambda cfg, proj, s2p, steps: {"ok": True, "reason": None},
    )
    out = rs.remote_hfss_l2_smoke("sim_host", out_dir=str(tmp_path / "pull"))
    assert out["verdict"] == "PASS" and out["ok"] is True
    c = out["criteria"]
    assert c["c1_readback"] and c["c2_s11_min_db"]
    assert c["c3_s21_min_db"] and c["c4_eps_eff_window"]
    assert out["steps"]["cleanup"]["ok"] is True
    assert out["steps"]["cleanup"]["steps"]["ansysedt_after"] == 0
    from pathlib import Path as StdPath

    assert StdPath(out["touchstone_local"]).exists()
    assert out["project"] == "E:\\rfauto_remote\\l2_smoke\\proj.aedt"


def test_l2_build_failure_failclosed(monkeypatch, tmp_path):
    """建模/求解失败 → FAIL 信封如实落盘判据为空，清理仍执行。"""
    monkeypatch.setenv(rs.REMOTE_SMOKE_ENV, "1")
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    _one_machine(monkeypatch, hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setattr(rs, "probe_machine",
                        lambda cfg: {"name": cfg.name, "reachable": True})

    class FakeTransport:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            return 0, "0\n", ""

        def upload_file(self, local, remote):
            pass

        def download_file(self, remote, local):
            raise AssertionError("建模失败时不得走到回拉")

        def close(self):
            pass

    monkeypatch.setattr(rs, "SshTransport", FakeTransport)
    monkeypatch.setattr(rs, "_launch_grpcsrv", lambda *a, **kw: None)
    monkeypatch.setattr(
        rs, "_l2_model_solve_export",
        lambda cfg, proj, s2p, steps: {"ok": False, "reason": "mock: solve boom"},
    )
    out = rs.remote_hfss_l2_smoke("sim_host", out_dir=str(tmp_path / "pull"))
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert "mock: solve boom" in out["reason"]
    assert out["criteria"] == {}
    assert out["steps"]["cleanup"]["ok"] is True


# ─── license_preflight（v1 调度面一级门；全 mock 零网络 #139） ─────────────


def _preflight_machine(monkeypatch, probe_ports=None, **kw):
    kwargs = dict(
        name="sim_host", host="10.20.30.40", ssh_port=22,
        hfss_grpc_port=50051,
        hfss_project_root=kw.pop("project_root", "E:\\rfauto_remote"),
        probe_ports=probe_ports if probe_ports is not None else {
            "ansys_license": 1055, "ads_license": 27009, "rdp": 3389},
    )
    kwargs.update(kw)
    cfg = RemoteMachineConfig(**kwargs)
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"sim_host": cfg})
    return cfg


def test_preflight_pass_all_license_ports_open(monkeypatch):
    """一级门 PASS：全部 license 端口 OPEN；非 license 端口（rdp）不进探活面。"""
    _preflight_machine(monkeypatch)
    monkeypatch.setattr(rs, "probe_port",
                        lambda host, port, timeout_s=3.0: (True, 4.4))
    out = rs.license_preflight("sim_host")
    assert out["ok"] is True and out["verdict"] == "PASS"
    assert out["machine"] == "sim_host" and out["reason"] is None
    assert set(out["steps"]["probe"]) == {"ansys_license", "ads_license"}
    assert out["steps"]["probe"]["ansys_license"] == {
        "port": 1055, "open": True, "latency_ms": 4.4}
    assert out["gate"] == {"kind": "tcp_license_ports", "all_open": True,
                           "closed": []}
    # 诚实口径：席位级查询 UNVERIFIED 随信封落账（端口 OPEN≠席位可用）
    assert "UNVERIFIED" in out["seat_level_query"]


def test_preflight_fail_closed_when_port_down(monkeypatch):
    """任一 license 端口不通 → FAIL（fail-closed，closed 端口进 reason）。"""
    _preflight_machine(monkeypatch)

    def _probe(host, port, timeout_s=3.0):
        return (port != 1055, 1.0)   # ansys_license(1055) 不通

    monkeypatch.setattr(rs, "probe_port", _probe)
    out = rs.license_preflight("sim_host")
    assert out["ok"] is False and out["verdict"] == "FAIL"
    assert "1055" in out["reason"] and "ansys_license" in out["reason"]
    assert out["gate"]["closed"] == ["ansys_license"]


def test_preflight_fail_closed_without_license_ports(monkeypatch):
    """未登记 license 探活端口 → FAIL（fail-closed，不静默放行）。"""
    _preflight_machine(monkeypatch, probe_ports={"rdp": 3389})
    monkeypatch.setattr(rs, "probe_port",
                        lambda host, port, timeout_s=3.0: (True, 1.0))
    out = rs.license_preflight("sim_host")
    assert out["verdict"] == "FAIL"
    assert "未登记 license" in out["reason"]


def test_preflight_no_machines_skip(monkeypatch):
    """无登记机器 → SKIP 信封（本地路径零行为变化契约）。"""
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {})
    out = rs.license_preflight(None)
    assert out["skipped"] is True and out["verdict"] == "SKIP"
    assert out["machine"] is None and out["steps"] == {}


def test_preflight_deep_without_grpc_session_skips_attach(monkeypatch):
    """deep=True 且 gRPC 未开（无在跑会话=预期态）→ 深检跳过且不翻门。"""
    _preflight_machine(monkeypatch,
                       hfss_ansysedt_exe="E:\\x\\ansysedt.exe")

    def _probe(host, port, timeout_s=3.0):
        return (port != 50051, 1.0)   # license 开、grpc 未开

    monkeypatch.setattr(rs, "probe_port", _probe)
    out = rs.license_preflight("sim_host", deep=True)
    assert out["verdict"] == "PASS"   # 深检缺席不翻 license 门
    assert out["steps"]["attach_health"]["skipped"] is True
    assert "无在跑会话" in out["steps"]["attach_health"]["reason"]


def test_preflight_deep_attach_informational_only(monkeypatch):
    """deep=True 且 grpc 开 → attach 深检走 mock；attach 失败也不翻 license 门。"""
    _preflight_machine(monkeypatch,
                       hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setattr(rs, "probe_port",
                        lambda host, port, timeout_s=3.0: (True, 1.0))
    monkeypatch.setattr(rs, "_attach_and_verify",
                        lambda cfg, steps: {"ok": False, "reason": "attach 失败"})
    out = rs.license_preflight("sim_host", deep=True)
    assert out["verdict"] == "PASS"   # 信息面不进门
    assert out["steps"]["attach_health"]["ok"] is False
    assert "不翻 license 门" in out["steps"]["attach_health"]["note"]


def test_preflight_deep_not_attempted_when_gate_fails(monkeypatch):
    """license 门未过时不烧 attach 深检（fail-fast，不浪费真机 attach）。"""
    _preflight_machine(monkeypatch,
                       hfss_ansysedt_exe="E:\\x\\ansysedt.exe")
    monkeypatch.setattr(rs, "probe_port",
                        lambda host, port, timeout_s=3.0: (False, 1.0))

    def _boom(cfg, steps):
        raise AssertionError("门未过不得进入 attach 深检")

    monkeypatch.setattr(rs, "_attach_and_verify", _boom)
    out = rs.license_preflight("sim_host", deep=True)
    assert out["verdict"] == "FAIL"
    assert "attach_health" not in out["steps"]


def test_preflight_unknown_machine_raises(monkeypatch):
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {})
    with pytest.raises(RemoteConfigError):
        rs.license_preflight("nope")
