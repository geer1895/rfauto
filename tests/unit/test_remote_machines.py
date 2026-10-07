"""多机协同 v0——infra/remote_machines 单测（全离线，#139 零真网零真机）。

覆盖：注册表加载（文件缺失=空表契约/local 覆盖合并/配置错误）、
resolve_machine 语义、probe（mock socket）、SSH 传输（mock paramiko）、
凭据解析优先级（密码不落配置/日志）。
"""

import dataclasses
import socket
import sys
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    ENV_SSH_STRICT,
    SSH_HOST_FINGERPRINTS_FILENAME,
    RemoteConfigError,
    RemoteMachineConfig,
    RemoteTransportError,
    SshTransport,
    decide_host_key_policy,
    fingerprint_of_key,
    load_fingerprint_ledger,
    load_remote_machines,
    probe_machine,
    probe_port,
    record_fingerprint,
    resolve_machine,
    ssh_strict_enabled,
)

# ─── 注册表加载 ───────────────────────────────────────────────────────────


def test_load_missing_file_returns_empty(tmp_path):
    """零配置零行为变化契约：登记文件不存在=空表，不报错。"""
    assert load_remote_machines(tmp_path / "nonexistent.yaml") == {}


def test_load_parses_full_entry(tmp_path):
    cfg_path = tmp_path / "remote_machines.yaml"
    cfg_path.write_text(
        yaml.safe_dump({
            "machines": {
                "sim_host": {
                    "host": "10.20.30.40",
                    "ssh_port": 22,
                    "probe_ports": {"rdp": 3389, "ansys_license": 1055},
                    "hfss": {
                        "version": "2025.1",
                        "grpc_port": 50051,
                        "project_root": "E:\\rfauto_remote",
                        "ansysedt_exe": "E:\\HFSS25\\HFSS2025\\...\\ansysedt.exe",
                    },
                    "ads": {"hpeesof_dir": "E:\\ADS27\\ADS2027"},
                },
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )
    machines = load_remote_machines(cfg_path)
    assert set(machines) == {"sim_host"}
    cfg = machines["sim_host"]
    assert cfg.host == "10.20.30.40"
    assert cfg.ssh_port == 22
    assert cfg.hfss_version == "2025.1"
    assert cfg.hfss_grpc_port == 50051
    assert cfg.hfss_project_root == "E:\\rfauto_remote"
    assert cfg.ads_hpeesof_dir == "E:\\ADS27\\ADS2027"
    assert cfg.probe_ports == {"rdp": 3389, "ansys_license": 1055}


def test_load_local_override_merges_credentials(tmp_path):
    """local 覆盖文件（gitignore 面）提供 ssh_user/key，登记文件零凭据。"""
    base = tmp_path / "remote_machines.yaml"
    base.write_text(
        yaml.safe_dump({
            "machines": {"m1": {"host": "10.0.0.1", "ssh_port": 2222}},
        }),
        encoding="utf-8",
    )
    local = tmp_path / "remote_machines.local.yaml"
    local.write_text(
        yaml.safe_dump({
            "machines": {"m1": {"ssh_user": "member01",
                                 "ssh_key_path": "C:\\keys\\id_ed25519"}},
        }),
        encoding="utf-8",
    )
    cfg = load_remote_machines(base)["m1"]
    assert cfg.host == "10.0.0.1"          # base 键保留
    assert cfg.ssh_port == 2222
    assert cfg.ssh_user == "member01"      # local 覆盖进凭据面
    assert cfg.ssh_key_path == "C:\\keys\\id_ed25519"


def test_load_missing_host_raises(tmp_path):
    cfg_path = tmp_path / "remote_machines.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"machines": {"bad": {"ssh_port": 22}}}), encoding="utf-8",
    )
    with pytest.raises(RemoteConfigError, match="host"):
        load_remote_machines(cfg_path)


def test_load_non_mapping_entry_raises(tmp_path):
    cfg_path = tmp_path / "remote_machines.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"machines": {"bad": "just-a-string"}}), encoding="utf-8",
    )
    with pytest.raises(RemoteConfigError):
        load_remote_machines(cfg_path)


# ─── resolve_machine ──────────────────────────────────────────────────────


def _two_machines() -> dict[str, RemoteMachineConfig]:
    return {
        "a": RemoteMachineConfig(name="a", host="10.0.0.1"),
        "b": RemoteMachineConfig(name="b", host="10.0.0.2"),
    }


def test_resolve_none_single_machine():
    table = {"only": RemoteMachineConfig(name="only", host="10.0.0.9")}
    assert resolve_machine(None, table).name == "only"


def test_resolve_none_ambiguous_raises():
    with pytest.raises(RemoteConfigError, match="显式指名"):
        resolve_machine(None, _two_machines())


def test_resolve_none_empty_returns_none():
    assert resolve_machine(None, {}) is None


def test_resolve_unknown_name_raises():
    with pytest.raises(RemoteConfigError, match="未登记"):
        resolve_machine("nope", _two_machines())


# ─── probe（mock socket，零真网） ─────────────────────────────────────────


def test_probe_port_open_and_closed(monkeypatch):
    calls = {"n": 0}

    def fake_create_connection(addr, timeout=None):
        calls["n"] += 1
        if addr[1] == 22:
            return socket.socket()
        raise OSError("refused")

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    opened, latency = probe_port("10.0.0.1", 22, timeout_s=1.0)
    assert opened is True and latency >= 0.0
    closed, _ = probe_port("10.0.0.1", 9999, timeout_s=1.0)
    assert closed is False
    assert calls["n"] == 2


def test_probe_machine_structure(monkeypatch):
    def fake_probe_port(host, port, timeout_s=3.0):
        return (port == 22, 1.5)

    monkeypatch.setattr(
        "rfauto.infra.remote_machines.probe_port", fake_probe_port,
    )
    cfg = RemoteMachineConfig(
        name="m", host="10.0.0.1", ssh_port=22,
        probe_ports={"rdp": 3389},
    )
    result = probe_machine(cfg)
    assert result["name"] == "m" and result["host"] == "10.0.0.1"
    assert result["reachable"] is True
    assert result["ports"]["ssh"] == {"port": 22, "open": True, "latency_ms": 1.5}
    assert result["ports"]["rdp"]["open"] is False


# ─── SshTransport（mock paramiko，零真网） ────────────────────────────────


def test_transport_run_command_requires_connect():
    t = SshTransport(RemoteMachineConfig(name="m", host="10.0.0.1"))
    with pytest.raises(RemoteTransportError, match="未连接"):
        t.run_command("echo hi")


def test_transport_paramiko_missing_raises(monkeypatch):
    """paramiko 缺装路径：显式 RemoteTransportError 指明 extras。"""
    monkeypatch.setitem(sys.modules, "paramiko", None)
    t = SshTransport(RemoteMachineConfig(name="m", host="10.0.0.1"))
    with pytest.raises(RemoteTransportError, match="rfauto\\[remote\\]"):
        t.connect()


class _FakeSftp:
    def __init__(self, transport):
        self.transport = transport
        self.puts = []
        self.gets = []

    def put(self, local, remote):
        self.puts.append((local, remote))

    def get(self, remote, local):
        self.gets.append((remote, local))

    def close(self):
        self.transport.sftp_closed = True


class _FakeClient:
    def __init__(self, transport):
        self.transport = transport
        self.connected = False
        self.commands = []

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, host, port=None, timeout=None, **creds):
        self.connected = True
        self.connect_args = {"host": host, "port": port, **creds}
        if creds.get("password") == "bad":
            raise RuntimeError("auth failed")

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        import io

        chan = type("Chan", (), {"recv_exit_status": lambda self: 0})()
        out = io.BytesIO(b"rfauto_remote_ok\n")
        err = io.BytesIO(b"")
        return io.BytesIO(b""), type("Out", (), {
            "channel": chan,
            "read": lambda self, _o=out: _o.read(),
        })(), type("Err", (), {"read": lambda self, _e=err: _e.read()})()

    def open_sftp(self):
        self.transport.sftp_closed = False
        return _FakeSftp(self.transport)

    def close(self):
        self.closed = True


def test_transport_connect_run_download_roundtrip(monkeypatch, tmp_path):
    """通道面全 mock：connect 参数（凭据不外泄）+命令回执+sftp 下载。"""
    t = SshTransport(
        RemoteMachineConfig(name="m", host="10.0.0.1", ssh_port=22),
        fingerprint_store_path=tmp_path / SSH_HOST_FINGERPRINTS_FILENAME,
    )
    fake_client = _FakeClient(t)
    monkeypatch.setitem(sys.modules, "paramiko",
                        type("P", (), {
                            "SSHClient": lambda: fake_client,
                            "AutoAddPolicy": lambda: object(),
                        }))
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "member01")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "secret")

    t.connect()
    assert fake_client.connected
    assert fake_client.connect_args["host"] == "10.0.0.1"
    assert fake_client.connect_args["username"] == "member01"
    # look_for_keys=False：凭据只走显式通道，不偷 agent/keyring
    assert fake_client.connect_args["look_for_keys"] is False

    rc, out, err = t.run_command("echo rfauto_remote_ok")
    assert rc == 0 and out.strip() == "rfauto_remote_ok" and err == ""

    remote = "E:\\rfauto_remote\\x.csv"
    local = tmp_path / "x.csv"
    t.download_file(remote, local)
    assert fake_client.transport.sftp_closed is True

    t.close()
    assert fake_client.closed


def test_transport_auth_failure_wrapped(monkeypatch, tmp_path):
    """认证失败包装为 RemoteTransportError，异常消息不含密码。"""
    t = SshTransport(
        RemoteMachineConfig(name="m", host="10.0.0.1"),
        fingerprint_store_path=tmp_path / SSH_HOST_FINGERPRINTS_FILENAME,
    )
    fake_client = _FakeClient(t)
    monkeypatch.setitem(sys.modules, "paramiko",
                        type("P", (), {
                            "SSHClient": lambda: fake_client,
                            "AutoAddPolicy": lambda: object(),
                        }))
    monkeypatch.setenv(ENV_REMOTE_SSH_USER, "u")
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "bad")
    with pytest.raises(RemoteTransportError, match="SSH 连接失败") as exc_info:
        t.connect()
    assert "bad" not in str(exc_info.value)


# ─── 凭据解析优先级 ───────────────────────────────────────────────────────


def test_credentials_local_key_precedence(monkeypatch):
    """local key 优先于 env 密码通道（key_filename 在位+密码仍透传兜底）。"""
    from rfauto.infra.remote_machines import _resolve_ssh_credentials

    cfg = RemoteMachineConfig(
        name="m", host="10.0.0.1", ssh_user="local_user",
        ssh_key_path="C:\\keys\\id",
    )
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "env_pass")
    creds = _resolve_ssh_credentials(cfg)
    assert creds["key_filename"] == "C:\\keys\\id"
    assert creds["username"] == "local_user"
    assert creds["password"] == "env_pass"


def test_credentials_env_user_fallback(monkeypatch):
    from rfauto.infra.remote_machines import _resolve_ssh_credentials

    monkeypatch.delenv(ENV_REMOTE_SSH_USER, raising=False)
    monkeypatch.setenv(ENV_REMOTE_SSH_PASSWORD, "p")
    creds = _resolve_ssh_credentials(RemoteMachineConfig(name="m", host="h"))
    assert creds["username"] is None
    assert creds["password"] == "p"


# ─── mTLS 证书面（多机 v1，fail-closed 不静默降级） ───────────────────────


def test_load_parses_hfss_mtls_keys(tmp_path):
    """hfss 节平键 ca_cert/client_cert/client_key 解析到 dataclass 字段。"""
    cfg_path = tmp_path / "remote_machines.yaml"
    cfg_path.write_text(
        yaml.safe_dump({
            "machines": {
                "sim_host": {
                    "host": "10.20.30.40",
                    "hfss": {
                        "version": "2025.1",
                        "grpc_port": 50051,
                        "ca_cert": "E:\\certs\\ca.crt",
                        "client_cert": "E:\\certs\\client.crt",
                        "client_key": "E:\\certs\\client.key",
                    },
                },
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )
    cfg = load_remote_machines(cfg_path)["sim_host"]
    assert cfg.hfss_ca_cert == "E:\\certs\\ca.crt"
    assert cfg.hfss_client_cert == "E:\\certs\\client.crt"
    assert cfg.hfss_client_key == "E:\\certs\\client.key"


def test_mtls_certs_none_when_all_missing():
    """三键全缺=None（insecure 现行为零变化）。"""
    from rfauto.infra.remote_machines import hfss_mtls_certs

    assert hfss_mtls_certs(RemoteMachineConfig(name="m", host="h")) is None


def test_mtls_certs_partial_config_raises():
    """缺一：fail-closed RemoteConfigError 显式点名缺件。"""
    from rfauto.infra.remote_machines import hfss_mtls_certs

    cfg = RemoteMachineConfig(
        name="sim_host", host="h", hfss_ca_cert="E:\\certs\\ca.crt",
    )
    with pytest.raises(RemoteConfigError, match="配置不完整"):
        hfss_mtls_certs(cfg)


def test_mtls_certs_missing_file_raises(tmp_path):
    """三键齐但文件不存在：fail-closed（前置到 connect 之前）。"""
    from rfauto.infra.remote_machines import hfss_mtls_certs

    d = tmp_path / "certs_missing"
    d.mkdir()
    (d / "ca.crt").write_bytes(b"CA")
    cfg = RemoteMachineConfig(
        name="sim_host", host="h",
        hfss_ca_cert=str(d / "ca.crt"),
        hfss_client_cert=str(d / "nope.crt"),
        hfss_client_key=str(d / "nope.key"),
    )
    with pytest.raises(RemoteConfigError, match="不存在"):
        hfss_mtls_certs(cfg)


def test_mtls_certs_complete_returns_frozen_spec(tmp_path):
    """三键齐且文件在位：返回冻结 HfssMtlsCerts（三路径逐键）。"""
    from rfauto.infra.remote_machines import HfssMtlsCerts, hfss_mtls_certs

    d = tmp_path / "certs_ok"
    d.mkdir()
    for name in ("ca.crt", "client.crt", "client.key"):
        (d / name).write_bytes(b"x")
    cfg = RemoteMachineConfig(
        name="sim_host", host="h",
        hfss_ca_cert=str(d / "ca.crt"),
        hfss_client_cert=str(d / "client.crt"),
        hfss_client_key=str(d / "client.key"),
    )
    spec = hfss_mtls_certs(cfg)
    assert isinstance(spec, HfssMtlsCerts)
    assert spec.ca_cert == str(d / "ca.crt")
    assert spec.client_cert == str(d / "client.crt")
    assert spec.client_key == str(d / "client.key")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.ca_cert = "immutable"  # frozen=True：值对象不可变


# ─── hfss.max_parallel（v1 调度面发射侧闸；缺省 2=实测可用档 §2.4） ───────


def test_max_parallel_default_two(tmp_path):
    """缺省 2：无显式配置时 dataclass 与解析层同值（实测可用档）。"""
    assert RemoteMachineConfig(name="m", host="h").hfss_max_parallel == 2
    p = tmp_path / "remote_machines.yaml"
    p.write_text("machines:\n  m1:\n    host: 10.0.0.1\n", encoding="utf-8")
    table = load_remote_machines(p)
    assert table["m1"].hfss_max_parallel == 2


def test_max_parallel_config_value_honored_and_clamped(tmp_path):
    """显式配置生效；<1 收敛到 1（fail-safe，不产生零/负并行度）。"""
    p = tmp_path / "remote_machines.yaml"
    p.write_text(
        "machines:\n"
        "  m1:\n"
        "    host: 10.0.0.1\n"
        "    hfss:\n"
        "      max_parallel: 4\n"
        "  m2:\n"
        "    host: 10.0.0.2\n"
        "    hfss:\n"
        "      max_parallel: 0\n",
        encoding="utf-8")
    table = load_remote_machines(p)
    assert table["m1"].hfss_max_parallel == 4
    assert table["m2"].hfss_max_parallel == 1


def test_max_parallel_invalid_raises(tmp_path):
    """非正整数配置 → RemoteConfigError（不静默回缺省，#122 如实）。"""
    p = tmp_path / "remote_machines.yaml"
    p.write_text(
        "machines:\n"
        "  m1:\n"
        "    host: 10.0.0.1\n"
        "    hfss:\n"
        "      max_parallel: 'many'\n",
        encoding="utf-8")
    with pytest.raises(RemoteConfigError):
        load_remote_machines(p)


# ─── E3-2（ge8e 审查批 F4）：repr/str 不泄密码 ────────────────────────────


def test_repr_and_str_do_not_leak_password():
    """ssh_password 字段 repr=False：调试/日志/pytest diff 面零密码原文
    （exp3 A 实测默认 dataclass repr 双泄漏面）；其余字段 repr 保持。"""
    cfg = RemoteMachineConfig(
        name="m", host="10.0.0.1", ssh_user="member01",
        ssh_password="FAKE-SECRET-VALUE")
    for text in (repr(cfg), str(cfg)):
        assert "FAKE-SECRET-VALUE" not in text
    # 其余字段 repr 保持：ssh_user 仍可见（调试面不残缺）
    assert "ssh_user='member01'" in repr(cfg)
    assert "name='m'" in repr(cfg)


def test_local_override_password_not_in_repr(tmp_path):
    """local 覆盖装载路径同样不泄（cfg 构造与来源无关，repr 面一致）。"""
    base = tmp_path / "remote_machines.yaml"
    base.write_text(
        yaml.safe_dump({"machines": {"m1": {"host": "10.0.0.1"}}}),
        encoding="utf-8")
    local = tmp_path / "remote_machines.local.yaml"
    local.write_text(
        yaml.safe_dump({"machines": {"m1": {"ssh_password": "LOCAL-SECRETS"}}}),
        encoding="utf-8")
    cfg = load_remote_machines(base)["m1"]
    assert cfg.ssh_password == "LOCAL-SECRETS"
    assert "LOCAL-SECRETS" not in repr(cfg)
    assert "LOCAL-SECRETS" not in str(cfg)


# ─── E3-6①（ge8e 审查批 F4）：local 覆盖不可读/非法 YAML 留痕 ────────────


def test_load_local_override_unreadable_records_load_errors(tmp_path):
    """存在但不可读（OSError）→ load_errors 留根因，主表照常返回。"""
    from rfauto.infra import remote_machines as rm

    base = tmp_path / "remote_machines.yaml"
    base.write_text(
        yaml.safe_dump({"machines": {"m1": {"host": "10.0.0.1"}}}),
        encoding="utf-8")
    # "存在但不可读"模拟：同名列是目录（exists()=True，read_text 抛 OSError）
    (tmp_path / "remote_machines.local.yaml").mkdir()
    machines = rm.load_remote_machines(base)
    assert machines["m1"].host == "10.0.0.1", "损坏 local 不挡主表返回"
    assert len(rm.load_errors) == 1
    assert rm.load_errors[0].startswith("remote_machines.local.yaml")
    assert ":" in rm.load_errors[0], "记录须含根因（异常类型与消息）"


def test_load_local_override_broken_yaml_records_load_errors(tmp_path):
    """非法 YAML → load_errors 留根因，base 主表照常返回（不再裸抛）。"""
    from rfauto.infra import remote_machines as rm

    base = tmp_path / "remote_machines.yaml"
    base.write_text(
        yaml.safe_dump({"machines": {"m1": {"host": "10.0.0.1"}}}),
        encoding="utf-8")
    local = tmp_path / "remote_machines.local.yaml"
    local.write_text("machines: [unclosed", encoding="utf-8")
    machines = rm.load_remote_machines(base)
    assert machines["m1"].host == "10.0.0.1"
    assert len(rm.load_errors) == 1
    assert rm.load_errors[0].startswith("remote_machines.local.yaml")
    assert "Error" in rm.load_errors[0]


def test_load_errors_reset_between_calls(tmp_path):
    """账本随调用清空：干净装载后不留上一次的陈旧告警。"""
    from rfauto.infra import remote_machines as rm

    clean = tmp_path / "remote_machines.yaml"
    clean.write_text(
        yaml.safe_dump({"machines": {"m1": {"host": "10.0.0.1"}}}),
        encoding="utf-8")
    rm.load_remote_machines(clean)
    assert rm.load_errors == []


# ─── E3-6②（ge8e 审查批 F4）：recv_exit_status 超时 watchdog ─────────────


def test_run_command_exit_status_timeout_raises_not_hang(monkeypatch, tmp_path):
    """sshd 停滞（exit-status 永不返回）→ RemoteTransportError 带超时标签，
    不无限挂起（channel timeout 只约束流读不约束 recv_exit_status）。"""
    import threading

    t = SshTransport(
        RemoteMachineConfig(name="m", host="10.0.0.1"),
        fingerprint_store_path=tmp_path / SSH_HOST_FINGERPRINTS_FILENAME,
    )
    release = threading.Event()
    chans: list = []

    class _StuckChan:
        closed = False

        def recv_exit_status(self):
            release.wait(2.0)  # 模拟 sshd 停滞（测试 bounded，不留挂死线程）
            return 0

        def close(self):
            self.closed = True

    def fake_exec(command, timeout=None):
        import io

        chan = _StuckChan()
        chans.append(chan)
        out = io.BytesIO(b"late")
        err = io.BytesIO(b"")
        return (io.BytesIO(b""),
                type("Out", (), {"channel": chan,
                                 "read": lambda self, _o=out: _o.read()})(),
                type("Err", (), {"read": lambda self, _e=err: _e.read()})())

    fake_client = _FakeClient(t)
    monkeypatch.setitem(sys.modules, "paramiko",
                        type("P", (), {
                            "SSHClient": lambda: fake_client,
                            "AutoAddPolicy": lambda: object(),
                        }))
    monkeypatch.setattr(fake_client, "exec_command", fake_exec)
    t.connect()
    with pytest.raises(RemoteTransportError, match="exit-status 等待超时") as exc_info:
        t.run_command("long-running", timeout_s=0.1)
    assert exc_info.value.details.get("phase") == "recv_exit_status"
    assert chans and chans[0].closed, "超时须关通道解阻塞流读"
    release.set()


def test_run_command_normal_path_unaffected(monkeypatch, tmp_path):
    """watchdog 包裹不改变正常路径（rc/输出/异常包装语义零变化）。"""
    t = SshTransport(
        RemoteMachineConfig(name="m", host="10.0.0.1"),
        fingerprint_store_path=tmp_path / SSH_HOST_FINGERPRINTS_FILENAME,
    )
    fake_client = _FakeClient(t)
    monkeypatch.setitem(sys.modules, "paramiko",
                        type("P", (), {
                            "SSHClient": lambda: fake_client,
                            "AutoAddPolicy": lambda: object(),
                        }))
    t.connect()
    rc, out, err = t.run_command("echo hi")
    assert rc == 0 and out.strip() == "rfauto_remote_ok" and err == ""


# ─── E3-3（ge8e 审查批 W3）：SSH TOFU 折中——指纹落档+严格模式 ─────────────
#
# 用户裁决折中案：缺省 AutoAdd+首连指纹落档告警（TOFU），指纹变更=error
# 醒目告警仍放行；RFAUTO_SSH_STRICT=1=无落档指纹/不匹配拒连（全量严格等
# mTLS 通道一起）。真实 SSH 行为不可单测连网——策略逻辑抽纯函数 +
# mock transport（任务书§5），paramiko 调用面保持薄。

_FP_A = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_FP_B = "SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
_RM_LOG = "rfauto.infra.remote_machines"


class _FakePKey:
    """假主机公钥：只实现 fingerprint_of_key 消费的 asbytes()。"""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def asbytes(self) -> bytes:
        return self._data


class _PolicyProbeClient:
    """模拟 paramiko known_hosts 未命中路径：connect 内回调 missing_host_key。

    本仓从不装载系统 known_hosts（SshTransport 不调 load_system_host_keys），
    paramiko 对每台新 client 首连必走 missing_host_key——探针客户端按同
    语义在 connect 内同步回调策略，单测即覆盖真实调用序。
    """

    def __init__(self, transport, key_bytes: bytes = b"probe-server-key"):
        self.transport = transport
        self.key_bytes = key_bytes
        self.policy = None
        self.connected = False
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, host, port=None, timeout=None, **creds):
        # paramiko 语义：known_hosts 未命中 → 先回调策略，接受才完成连接
        self.policy.missing_host_key(self, host, _FakePKey(self.key_bytes))
        self.connected = True

    def close(self):
        self.closed = True


def _strict_transport(tmp_path, host="10.0.0.1", port=22):
    t = SshTransport(
        RemoteMachineConfig(name="m", host=host, ssh_port=port),
        fingerprint_store_path=tmp_path / SSH_HOST_FINGERPRINTS_FILENAME,
    )
    return t


def _mock_paramiko(monkeypatch, client):
    monkeypatch.setitem(sys.modules, "paramiko",
                        type("P", (), {"SSHClient": lambda: client}))


@pytest.mark.parametrize(
    ("recorded", "current", "strict", "expected"),
    [
        # 首连：缺省=warning 放行+落档；严格=error 拒绝
        (None, _FP_A, False, ("autoadd", "warning", True)),
        (None, _FP_A, True, ("strict", "error", False)),
        # 一致：缺省=静默；严格=放行（已录匹配才连）
        (_FP_A, _FP_A, False, ("autoadd", "none", True)),
        (_FP_A, _FP_A, True, ("strict", "none", True)),
        # 变更：缺省=error 醒目告警仍放行（折中案语义）；严格=拒绝
        (_FP_A, _FP_B, False, ("autoadd", "error", True)),
        (_FP_A, _FP_B, True, ("strict", "error", False)),
    ],
)
def test_decide_host_key_policy_six_states(recorded, current, strict, expected):
    """三态×严格两档=6 例策略钉（纯函数，零 IO）。"""
    assert decide_host_key_policy(recorded, current, strict) == expected


def test_decide_host_key_policy_unverifiable_current_is_none():
    """指纹不可得：严格 fail-closed 拒绝；缺省降级 warning 放行（#105）。"""
    assert decide_host_key_policy(_FP_A, None, True) == ("strict", "error", False)
    assert decide_host_key_policy(None, None, False) == ("autoadd", "warning", True)


def test_fingerprint_of_key_open_ssh_format():
    """SHA256:base64 无 padding、确定性（同字节同指纹，异字节异指纹）。"""
    import base64 as b64
    import hashlib as hl

    want = "SHA256:" + b64.b64encode(
        hl.sha256(b"host-key-bytes-A").digest(),
    ).decode("ascii").rstrip("=")
    assert fingerprint_of_key(_FakePKey(b"host-key-bytes-A")) == want
    assert "=" not in want
    assert fingerprint_of_key(_FakePKey(b"host-key-bytes-A")) == want
    assert fingerprint_of_key(_FakePKey(b"host-key-bytes-B")) != want


def test_fingerprint_ledger_roundtrip(tmp_path):
    """读写往返：{host:port: {fingerprint, first_seen}} 结构逐键保真。"""
    from datetime import datetime

    p = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    assert load_fingerprint_ledger(p) == {}  # 不存在=首连语义
    stamp = 1_700_000_000.0
    assert record_fingerprint(p, "10.0.0.1", 22, _FP_A, now=stamp) == "created"
    want_seen = datetime.fromtimestamp(stamp).isoformat(timespec="seconds")
    assert load_fingerprint_ledger(p) == {
        "10.0.0.1:22": {"fingerprint": _FP_A, "first_seen": want_seen},
    }
    # 变更换基线：新指纹覆盖（变更事件在 error 日志，账本持当前基线）
    assert record_fingerprint(
        p, "10.0.0.1", 22, _FP_B, now=stamp + 60,
    ) == "updated"
    ledger = load_fingerprint_ledger(p)
    assert ledger["10.0.0.1:22"]["fingerprint"] == _FP_B
    # 一致=unchanged（不触发写盘——mtime 不变）
    before = p.stat().st_mtime_ns
    assert record_fingerprint(
        p, "10.0.0.1", 22, _FP_B, now=stamp + 120,
    ) == "unchanged"
    assert p.stat().st_mtime_ns == before


def test_fingerprint_record_atomic_no_tmp_leftover(tmp_path):
    """原子写：tmp+replace，成功后无 .tmp 残留（进程号后缀自清理）。"""
    p = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    record_fingerprint(p, "h", 22, _FP_A, now=0.0)
    assert p.exists()
    assert list(tmp_path.glob("*.tmp*")) == []


def test_fingerprint_ledger_corrupt_or_non_mapping_raises(tmp_path):
    """损坏 JSON / 顶层非映射 → RemoteTransportError（分流在调用方）。"""
    p = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    p.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RemoteTransportError, match="指纹账本不可读"):
        load_fingerprint_ledger(p)
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(RemoteTransportError, match="映射"):
        load_fingerprint_ledger(p)


def test_ssh_strict_env_parsing(monkeypatch):
    """truthy 集判定（大小写不敏感+空白容忍）+ environ 注入纯函数性。"""
    for truthy in ("1", "true", "TRUE", "Yes", "on", " 1 "):
        monkeypatch.setenv(ENV_SSH_STRICT, truthy)
        assert ssh_strict_enabled() is True, truthy
    for falsy in ("", "0", "false", "no", "off", "enabled-by-typo"):
        monkeypatch.setenv(ENV_SSH_STRICT, falsy)
        assert ssh_strict_enabled() is False, falsy
    monkeypatch.delenv(ENV_SSH_STRICT, raising=False)
    assert ssh_strict_enabled() is False
    assert ssh_strict_enabled({ENV_SSH_STRICT: "1"}) is True
    assert ssh_strict_enabled({}) is False


def test_connect_default_first_connect_warns_and_archives(monkeypatch, tmp_path, caplog):
    """缺省首连：WARNING 首连告警（含 TOFU 提示）+ 指纹落档 + 连接成功。"""
    import logging

    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.delenv(ENV_SSH_STRICT, raising=False)
    with caplog.at_level(logging.DEBUG, logger=_RM_LOG):
        t.connect()
    assert client.connected
    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    ledger = load_fingerprint_ledger(store)
    want_fp = fingerprint_of_key(_FakePKey(b"probe-server-key"))
    assert ledger["10.0.0.1:22"]["fingerprint"] == want_fp
    warns = [r for r in caplog.records
             if r.name == _RM_LOG and r.levelno == logging.WARNING]
    assert warns, "首连必须 WARNING 级告警"
    assert "首连" in warns[0].getMessage()
    assert "TOFU" in warns[0].getMessage()
    assert want_fp in warns[0].getMessage()


def test_connect_default_match_silent(monkeypatch, tmp_path, caplog):
    """缺省再连（指纹一致）：静默放行，无 warning/error，账本免写。"""
    import logging

    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    fp = fingerprint_of_key(_FakePKey(b"probe-server-key"))
    record_fingerprint(store, "10.0.0.1", 22, fp, now=0.0)
    before = store.stat().st_mtime_ns
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.delenv(ENV_SSH_STRICT, raising=False)
    with caplog.at_level(logging.DEBUG, logger=_RM_LOG):
        t.connect()
    assert client.connected
    loud = [r for r in caplog.records
            if r.name == _RM_LOG and r.levelno >= logging.WARNING]
    assert loud == [], "一致再连必须静默"
    assert store.stat().st_mtime_ns == before, "一致免写盘"


def test_connect_default_mismatch_error_but_connects(monkeypatch, tmp_path, caplog):
    """缺省指纹变更：error 醒目告警（折中案）仍放行；账本换新基线。"""
    import logging

    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    old_fp = fingerprint_of_key(_FakePKey(b"old-server-key"))
    new_fp = fingerprint_of_key(_FakePKey(b"new-server-key"))
    record_fingerprint(store, "10.0.0.1", 22, old_fp, now=0.0)
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t, key_bytes=b"new-server-key")
    _mock_paramiko(monkeypatch, client)
    monkeypatch.delenv(ENV_SSH_STRICT, raising=False)
    with caplog.at_level(logging.DEBUG, logger=_RM_LOG):
        t.connect()
    assert client.connected, "折中案：缺省模式指纹变更仍放行"
    errs = [r for r in caplog.records
            if r.name == _RM_LOG and r.levelno == logging.ERROR]
    assert errs, "指纹变更必须 ERROR 级醒目告警"
    msg = errs[0].getMessage()
    assert "主机钥变更" in msg
    assert old_fp in msg and new_fp in msg, "新旧指纹都必须在告警里"
    ledger = load_fingerprint_ledger(store)
    assert ledger["10.0.0.1:22"]["fingerprint"] == new_fp


def test_connect_strict_no_record_rejects_with_guidance(monkeypatch, tmp_path):
    """严格档首连：拒绝+处置指引；不落档。"""
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.setenv(ENV_SSH_STRICT, "1")
    with pytest.raises(RemoteTransportError, match="缺省模式连接一次落档指纹") as ei:
        t.connect()
    assert not client.connected
    assert not (tmp_path / SSH_HOST_FINGERPRINTS_FILENAME).exists(), "拒绝不落档"
    assert ei.value.details.get("strict") is True


def test_connect_strict_match_connects(monkeypatch, tmp_path):
    """严格档已录匹配：放行（"已录指纹匹配才连"语义）。"""
    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    fp = fingerprint_of_key(_FakePKey(b"probe-server-key"))
    record_fingerprint(store, "10.0.0.1", 22, fp, now=0.0)
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.setenv(ENV_SSH_STRICT, "1")
    t.connect()
    assert client.connected


def test_connect_strict_mismatch_rejects_keeps_old_record(monkeypatch, tmp_path):
    """严格档指纹变更：拒绝且不改账本（旧基线保留供人工核对）。"""
    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    old_fp = fingerprint_of_key(_FakePKey(b"old-server-key"))
    record_fingerprint(store, "10.0.0.1", 22, old_fp, now=0.0)
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t, key_bytes=b"new-server-key")
    _mock_paramiko(monkeypatch, client)
    monkeypatch.setenv(ENV_SSH_STRICT, "1")
    with pytest.raises(RemoteTransportError, match="严格模式"):
        t.connect()
    assert not client.connected
    ledger = load_fingerprint_ledger(store)
    assert ledger["10.0.0.1:22"]["fingerprint"] == old_fp


def test_connect_ledger_unreadable_strict_fails_closed(monkeypatch, tmp_path):
    """严格档账本损坏：fail-closed 拒连（不静默降级）。"""
    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    store.write_text("{broken", encoding="utf-8")
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.setenv(ENV_SSH_STRICT, "1")
    with pytest.raises(RemoteTransportError, match="fail-closed"):
        t.connect()
    assert not client.connected


def test_connect_ledger_unreadable_default_degrades(monkeypatch, tmp_path, caplog):
    """缺省档账本损坏：降级告警不挡连接（#105），连接后自愈重落档。"""
    import logging

    store = tmp_path / SSH_HOST_FINGERPRINTS_FILENAME
    store.write_text("{broken", encoding="utf-8")
    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.delenv(ENV_SSH_STRICT, raising=False)
    with caplog.at_level(logging.DEBUG, logger=_RM_LOG):
        t.connect()
    assert client.connected, "缺省模式账本坏=降级告警不挡连接"
    msgs = [r.getMessage() for r in caplog.records
            if r.name == _RM_LOG and r.levelno >= logging.WARNING]
    assert any("降级" in m for m in msgs)
    ledger = load_fingerprint_ledger(store)
    assert ledger["10.0.0.1:22"]["fingerprint"] == \
        fingerprint_of_key(_FakePKey(b"probe-server-key")), "损坏账本自愈重落档"


def test_strict_rejection_wrapped_as_remote_transport_error(monkeypatch, tmp_path):
    """严格拒连异常形态：RemoteTransportError（host/strict details 随行）。"""
    from rfauto.infra.remote_machines import RemoteTransportError

    t = _strict_transport(tmp_path)
    client = _PolicyProbeClient(t)
    _mock_paramiko(monkeypatch, client)
    monkeypatch.setenv(ENV_SSH_STRICT, "1")
    with pytest.raises(RemoteTransportError) as ei:
        t.connect()
    assert ei.value.details.get("host") == "10.0.0.1"
    assert ei.value.details.get("ssh_port") == 22
    assert ei.value.details.get("strict") is True
