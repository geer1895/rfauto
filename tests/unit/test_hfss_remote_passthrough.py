"""多机协同 v0——HFSS 会话/adapter 远程透传钉（全离线 mock）。

钉住三条契约：

1. **零行为变化**：settings 无 ``remote_machine`` 键时 Desktop/Hfss 构造
   参数与历史逐键相同（无 machine/port），远程四开关零触碰；
2. **远程透传**：带键时 machine/port 进 Desktop 与 Hfss，adapter 远程
   分支不创建本地父目录（服务器侧路径语义）；远程四开关只在 Desktop
   构造期生效、connect 返回前恢复（P1-1）；
3. **版本配对交叉断言**：settings.desktop_version 与注册表 hfss_version
   失配显式 ConnectFailedError（P1-1 附带项）。
"""

import os
import sys
import types
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_adapter import HfssAdapter
from rfauto.adapters.hfss_session import (
    HfssSession,
    active_mtls_certs,
    remote_session_switches,
    set_active_mtls_certs,
)

# ─── fake Desktop（记录 kwargs） ──────────────────────────────────────────


class _FakeDesktop:
    """模拟 ansys.aedt.core.Desktop：记录构造参数供断言。"""

    last_kwargs: dict | None = None
    last_env: str | None = None
    last_switches: dict | None = None
    last_certs: str | None = None
    last_certs_files: dict[str, bytes] | None = None

    def __init__(self, **kwargs):
        _FakeDesktop.last_kwargs = kwargs
        _FakeDesktop.last_env = os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS")
        _FakeDesktop.last_certs = os.environ.get("ANSYS_GRPC_CERTIFICATES")
        certs_dir = _FakeDesktop.last_certs
        _FakeDesktop.last_certs_files = (
            {
                f.name: f.read_bytes()
                for f in sorted(Path(certs_dir).iterdir())
            }
            if certs_dir and Path(certs_dir).is_dir() else None
        )
        sm = sys.modules.get("ansys.aedt.core.generic.settings")
        if sm is not None and hasattr(sm, "settings"):
            s = sm.settings
            _FakeDesktop.last_switches = {
                "grpc_local": s.grpc_local,
                "grpc_secure_mode": s.grpc_secure_mode,
                "remote_rpc_session": s.remote_rpc_session,
            }
        self.current_version = "2025.1"

    def release_desktop(self, close_on_exit=True, close_projects=True):
        self.released = True


class _FakeAedtSettings:
    """模拟 pyaedt settings：记录远程开关写入历史（初始化自设不入账）。"""

    def __init__(self):
        self._armed = False
        self.grpc_local = True
        self.grpc_secure_mode = True
        self.remote_rpc_session = False
        self.switch_history: list[tuple[str, bool]] = []
        self._armed = True

    def __setattr__(self, name, value):
        if getattr(self, "_armed", False) and name in (
            "grpc_local", "grpc_secure_mode", "remote_rpc_session",
        ):
            self.__dict__.setdefault("switch_history", []).append((name, value))
        super().__setattr__(name, value)


@pytest.fixture()
def fake_aedt_module(monkeypatch):
    mod = types.ModuleType("ansys.aedt.core")
    mod.Desktop = _FakeDesktop
    generic = types.ModuleType("ansys.aedt.core.generic")
    settings_mod = types.ModuleType("ansys.aedt.core.generic.settings")
    settings_obj = _FakeAedtSettings()
    settings_mod.settings = settings_obj
    monkeypatch.setitem(sys.modules, "ansys", types.ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt", types.ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", mod)
    monkeypatch.setitem(sys.modules, "ansys.aedt.core.generic", generic)
    monkeypatch.setitem(
        sys.modules, "ansys.aedt.core.generic.settings", settings_mod,
    )
    _FakeDesktop.last_kwargs = None
    _FakeDesktop.last_env = None
    _FakeDesktop.last_switches = None
    _FakeDesktop.last_certs = None
    _FakeDesktop.last_certs_files = None
    set_active_mtls_certs(None)
    yield mod, settings_obj
    set_active_mtls_certs(None)
    HfssSession.reset()


# ─── 零行为变化钉 ─────────────────────────────────────────────────────────


def test_connect_local_desktop_kwargs_unchanged(fake_aedt_module, monkeypatch):
    """无 remote_machine 键：Desktop 不收 machine/port（历史行为逐键），
    远程四开关零触碰（P1-1 开关面的零行为变化钉）。"""
    _, fake_settings = fake_aedt_module
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "non_graphical": True})
    kwargs = _FakeDesktop.last_kwargs
    assert set(kwargs) == {
        "version", "non_graphical", "student_version", "new_desktop",
    }
    assert session.remote_info is None
    # 开关零触碰：本地分支不进 CM（历史为空 + env 未设）
    assert fake_settings.switch_history == []
    assert "PYAEDT_USE_PRE_GRPC_ARGS" not in os.environ


def test_connect_remote_desktop_receives_machine_port(fake_aedt_module, monkeypatch):
    """带 remote_machine 键：Desktop 收 machine/port，remote_info 填充。"""
    from rfauto.infra.remote_machines import RemoteMachineConfig

    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40",
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
    )
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", lambda name: cfg,
    )
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    kwargs = _FakeDesktop.last_kwargs
    assert kwargs["machine"] == "10.20.30.40"
    assert kwargs["port"] == 50051
    info = session.remote_info
    assert info == {
        "name": "sim_host", "machine": "10.20.30.40", "port": 50051,
        "project_root": "E:\\rfauto_remote", "version": "2025.1",
    }


def test_connect_remote_switches_during_desktop_and_restored(
    fake_aedt_module, monkeypatch
):
    """P1-1：远程分支 Desktop 构造期四开关+一 env 生效，connect 返回前
    恢复原值（开关只在构造期消费——保存旧值/恢复时序逐条钉）。"""
    _, fake_settings = fake_aedt_module
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    from rfauto.infra.remote_machines import RemoteMachineConfig

    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40",
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
    )  # hfss_version 缺省 "2025.1" 与 desktop_version 配对
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", lambda name: cfg,
    )
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    # 构造期快照（FakeDesktop.__init__ 捕获）：四开关+一 env 全部在位
    assert _FakeDesktop.last_switches == {
        "grpc_local": False,
        "grpc_secure_mode": False,
        "remote_rpc_session": True,
    }
    assert _FakeDesktop.last_env == "True"
    # connect 返回前恢复原值：写入历史=三设+三恢复（时序逐条钉）
    assert fake_settings.switch_history == [
        ("grpc_local", False),
        ("grpc_secure_mode", False),
        ("remote_rpc_session", True),
        ("grpc_local", True),
        ("grpc_secure_mode", True),
        ("remote_rpc_session", False),
    ]
    assert "PYAEDT_USE_PRE_GRPC_ARGS" not in os.environ


def test_connect_remote_version_mismatch_raises(fake_aedt_module, monkeypatch):
    """P1-1 附带：settings.desktop_version 与注册表 hfss_version 失配
    显式 ConnectFailedError（版本配对指引），Desktop 不构造。"""
    from rfauto.core.errors import ConnectFailedError
    from rfauto.infra.remote_machines import RemoteMachineConfig

    _, _fake_settings = fake_aedt_module
    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", hfss_version="2025.1",
        hfss_grpc_port=50051,
    )
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", lambda name: cfg,
    )
    session = HfssSession.instance()
    with pytest.raises(ConnectFailedError, match="版本配对失配"):
        session.connect({
            "desktop_version": "2024.1", "non_graphical": True,
            "remote_machine": "sim_host",
        })
    assert _FakeDesktop.last_kwargs is None  # 失配在 Desktop 构造前拒绝


def test_connect_remote_unknown_machine_raises(fake_aedt_module, monkeypatch):
    """注册表无名：显式 RemoteConfigError（不猜）。"""
    from rfauto.infra.remote_machines import RemoteConfigError

    def _raise(name):
        raise RemoteConfigError("未登记", details={"name": name})

    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", _raise,
    )
    session = HfssSession.instance()
    with pytest.raises(RemoteConfigError):
        session.connect({"remote_machine": "nope"})


# ─── adapter 远程分支 ─────────────────────────────────────────────────────


class _FakeHfss:
    last_kwargs: dict | None = None
    last_env: str | None = None
    last_switches: dict | None = None
    last_certs: str | None = None

    def __init__(self, **kwargs):
        _FakeHfss.last_kwargs = kwargs
        _FakeHfss.last_env = os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS")
        _FakeHfss.last_certs = os.environ.get("ANSYS_GRPC_CERTIFICATES")
        sm = sys.modules.get("ansys.aedt.core.generic.settings")
        if sm is not None and hasattr(sm, "settings"):
            s = sm.settings
            _FakeHfss.last_switches = {
                "grpc_local": s.grpc_local,
                "grpc_secure_mode": s.grpc_secure_mode,
                "remote_rpc_session": s.remote_rpc_session,
            }
        self.odesign = None


def _patch_adapter_hfss(monkeypatch):
    """垫掉 adapter 内的 Hfss 构造与就绪探测循环。"""
    _FakeHfss.last_kwargs = None
    _FakeHfss.last_env = None
    _FakeHfss.last_switches = None
    _FakeHfss.last_certs = None
    monkeypatch.setattr(
        "rfauto.adapters.hfss_adapter._ensure_hfss", lambda: _FakeHfss,
    )
    monkeypatch.setattr("time.sleep", lambda *_a: None)


def test_open_or_create_project_remote_no_local_mkdir(monkeypatch, tmp_path,
                                                      fake_aedt_module):
    """远程分支：服务器侧路径不在本地 mkdir，Hfss 收 machine/port。"""
    _patch_adapter_hfss(monkeypatch)
    created: list[Path] = []
    real_mkdir = Path.mkdir

    def spy_mkdir(self, *a, **kw):
        created.append(self)
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)

    adapter = HfssAdapter.__new__(HfssAdapter)
    session = HfssSession.instance()
    session._connected = True
    session._remote = {
        "name": "sim_host", "machine": "10.20.30.40", "port": 50051,
        "project_root": "E:\\rfauto_remote", "version": "2025.1",
    }
    session._settings = {"non_graphical": True}
    adapter.session = session

    # 服务器侧语义路径（本地不存在也不创建）
    server_path = tmp_path / "local_should_not_exist" / "proj.aedt"
    assert not server_path.parent.exists()
    adapter.open_or_create_project(server_path, "Design1")

    kwargs = _FakeHfss.last_kwargs
    assert kwargs["machine"] == "10.20.30.40"
    assert kwargs["port"] == 50051
    assert kwargs["project"] == str(server_path)
    # 远程分支零本地 mkdir（含 parents 链）
    assert created == []
    HfssSession.reset()


def test_open_or_create_project_local_keeps_mkdir(monkeypatch, tmp_path,
                                                  fake_aedt_module):
    """本地分支回归钉：父目录创建行为保持，且开关零触碰（adapter 期本地
    分支不进 CM——第二个构造窗口只属于远程分支）。"""
    _patch_adapter_hfss(monkeypatch)
    _, fake_settings = fake_aedt_module
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    adapter = HfssAdapter.__new__(HfssAdapter)
    session = HfssSession.instance()
    session._connected = True
    session._remote = None
    session._settings = {"non_graphical": True}
    adapter.session = session

    local_path = tmp_path / "fresh_dir" / "proj.aedt"
    adapter.open_or_create_project(local_path, "Design1")
    assert local_path.parent.exists()
    kwargs = _FakeHfss.last_kwargs
    assert "machine" not in kwargs and "port" not in kwargs
    # 本地分支开关零触碰：switch 历史为空 + env 未设（若误进 CM，
    # _FakeAedtSettings 的写入历史会非空当场抓出）
    assert fake_settings.switch_history == []
    assert "PYAEDT_USE_PRE_GRPC_ARGS" not in os.environ
    HfssSession.reset()


def test_open_or_create_project_remote_hfss_construct_switches(
    monkeypatch, tmp_path, fake_aedt_module,
):
    """review-fix1 v1 锚闭合：远程分支 Hfss 构造点包四开关 CM（第二个
    构造窗口），构造期 remote_rpc_session=None，构造完成后 CM 恢复原值。"""
    _patch_adapter_hfss(monkeypatch)
    _, fake_settings = fake_aedt_module
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    adapter = HfssAdapter.__new__(HfssAdapter)
    session = HfssSession.instance()
    session._connected = True
    session._remote = {
        "name": "sim_host", "machine": "10.20.30.40", "port": 50051,
        "project_root": "E:\\rfauto_remote", "version": "2025.1",
    }
    session._settings = {"non_graphical": True}
    adapter.session = session

    adapter.open_or_create_project(tmp_path / "server" / "proj.aedt", "Design1")

    # Hfss 构造期快照：四开关在位，其中 remote_rpc_session 已被置 None
    assert _FakeHfss.last_switches == {
        "grpc_local": False,
        "grpc_secure_mode": False,
        "remote_rpc_session": None,
    }
    assert _FakeHfss.last_env == "True"
    # 写入时序逐条钉：CM 进入三设 → remote_rpc_session=None 覆写
    # → CM 退出三恢复（缺省初值 True/True/False）
    assert fake_settings.switch_history == [
        ("grpc_local", False),
        ("grpc_secure_mode", False),
        ("remote_rpc_session", True),
        ("remote_rpc_session", None),
        ("grpc_local", True),
        ("grpc_secure_mode", True),
        ("remote_rpc_session", False),
    ]
    assert "PYAEDT_USE_PRE_GRPC_ARGS" not in os.environ
    HfssSession.reset()


def test_two_construct_windows_independent_sequence(
    monkeypatch, fake_aedt_module,
):
    """时序钉：connect 的 Desktop 构造窗口（CM 进入三设+退出三恢复）与
    adapter 的 Hfss 构造窗口（再进 CM+None 覆写+恢复）独立进出互不干扰
    ——13 条写入历史逐条钉全序。"""
    _patch_adapter_hfss(monkeypatch)
    _, fake_settings = fake_aedt_module
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    from rfauto.infra.remote_machines import RemoteMachineConfig

    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40",
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
    )
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", lambda name: cfg,
    )
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    adapter = HfssAdapter.__new__(HfssAdapter)
    adapter.session = session
    adapter.open_or_create_project("E:\\rfauto_remote\\proj.aedt", "Design1")

    assert fake_settings.switch_history == [
        # 窗口一（connect→Desktop 构造）
        ("grpc_local", False),
        ("grpc_secure_mode", False),
        ("remote_rpc_session", True),
        ("grpc_local", True),
        ("grpc_secure_mode", True),
        ("remote_rpc_session", False),
        # 窗口二（open_or_create_project→Hfss 构造，None 覆写居中）
        ("grpc_local", False),
        ("grpc_secure_mode", False),
        ("remote_rpc_session", True),
        ("remote_rpc_session", None),
        ("grpc_local", True),
        ("grpc_secure_mode", True),
        ("remote_rpc_session", False),
    ]
    # Desktop 构造期 remote_rpc_session=True（远程 attach 语义）、
    # Hfss 构造期=None（设计初始化不走 rpyc filemanager）——两窗口
    # 构造期快照语义相反即"独立进出"的直接证据。
    assert _FakeDesktop.last_switches["remote_rpc_session"] is True
    assert _FakeHfss.last_switches["remote_rpc_session"] is None
    HfssSession.reset()


# ─── mTLS secure 通道（多机 v1） ──────────────────────────────────────────
#
# pyaedt 1.4.0 官方口径 ground（desktop.py 源码实测）：
# - ANSYS_GRPC_CERTIFICATES env = 证书**文件夹**，内含固定名三件
#   ca.crt/client.crt/client.key（_get_grpcsrv_args.check_mtls 逐件点名）；
# - grpc_secure_mode=True + grpc_local=False + env 在位 → MTLS，连接串
#   __repr__ 为 host:port:SecureMode 三段式；env 缺位时同一函数静默回
#   InsecureMode 后缀（本层 fail-closed 封死该降级面）；
# - PYAEDT_USE_PRE_GRPC_ARGS=True 会把连接串砍成裸 IP（丢 SecureMode
#   后缀）——secure 形态必须强制 False。


def _write_canonical_certs(d: Path) -> Path:
    """造规范名证书三件（内容为假字节——单测零真证书，只验证链路）。"""
    d.mkdir(parents=True, exist_ok=True)
    (d / "ca.crt").write_bytes(b"CA")
    (d / "client.crt").write_bytes(b"CERT")
    (d / "client.key").write_bytes(b"KEY")
    return d


def _secure_cfg(cert_dir: Path, **overrides):
    from rfauto.infra.remote_machines import RemoteMachineConfig

    kwargs = dict(
        name="sim_host", host="10.20.30.40",
        hfss_grpc_port=50051, hfss_project_root="E:\\rfauto_remote",
        hfss_ca_cert=str(cert_dir / "ca.crt"),
        hfss_client_cert=str(cert_dir / "client.crt"),
        hfss_client_key=str(cert_dir / "client.key"),
    )
    kwargs.update(overrides)
    return RemoteMachineConfig(**kwargs)


def test_connect_remote_mtls_secure_switches_and_env(
    fake_aedt_module, monkeypatch, tmp_path,
):
    """证书三件齐（规范名同目录）：构造期 grpc_secure_mode=True + 证书
    env 直用规范目录 + pre-args 强制 False；connect 返回后 env 双恢复；
    remote_info 五键契约零变化。"""
    cert_dir = _write_canonical_certs(tmp_path / "certs")
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine",
        lambda name: _secure_cfg(cert_dir),
    )
    monkeypatch.delenv("PYAEDT_USE_PRE_GRPC_ARGS", raising=False)
    monkeypatch.delenv("ANSYS_GRPC_CERTIFICATES", raising=False)
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    # 构造期快照：secure 形态三开关 + env 注入内容逐键
    assert _FakeDesktop.last_switches == {
        "grpc_local": False,
        "grpc_secure_mode": True,
        "remote_rpc_session": True,
    }
    assert _FakeDesktop.last_env == "False"
    assert _FakeDesktop.last_certs == str(cert_dir)
    # 证书面落到 session（adapter 第二窗口经活跃状态同源消费）
    assert session.remote_mtls_certs is not None
    assert active_mtls_certs() is session.remote_mtls_certs
    # remote_info 五键契约零变化（mtls 不进该 dict）
    assert session.remote_info == {
        "name": "sim_host", "machine": "10.20.30.40", "port": 50051,
        "project_root": "E:\\rfauto_remote", "version": "2025.1",
    }
    # connect 返回前 env 全恢复（防污染本地会话）
    assert "PYAEDT_USE_PRE_GRPC_ARGS" not in os.environ
    assert "ANSYS_GRPC_CERTIFICATES" not in os.environ
    HfssSession.reset()


def test_connect_remote_mtls_staging_noncanonical_names(
    fake_aedt_module, monkeypatch, tmp_path,
):
    """非规范文件名：CM 暂存规范化为 pyaedt 固定名三件（内容逐字节），
    env 指向暂存目录，CM 退出清理暂存。"""
    d = tmp_path / "certs_odd"
    d.mkdir()
    (d / "my-ca.pem").write_bytes(b"CA2")
    (d / "client-cert.pem").write_bytes(b"CERT2")
    (d / "client-key.pem").write_bytes(b"KEY2")
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine",
        lambda name: _secure_cfg(
            d,
            hfss_ca_cert=str(d / "my-ca.pem"),
            hfss_client_cert=str(d / "client-cert.pem"),
            hfss_client_key=str(d / "client-key.pem"),
        ),
    )
    monkeypatch.delenv("ANSYS_GRPC_CERTIFICATES", raising=False)
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    staged = _FakeDesktop.last_certs
    assert staged is not None and Path(staged) != d
    # 构造期快照：暂存目录内是 pyaedt 固定名三件，内容逐字节等于源
    assert _FakeDesktop.last_certs_files == {
        "ca.crt": b"CA2", "client.crt": b"CERT2", "client.key": b"KEY2",
    }
    # CM 退出清理暂存目录（正常路径必清，不留私钥拷贝）
    assert not Path(staged).exists()
    assert "ANSYS_GRPC_CERTIFICATES" not in os.environ
    HfssSession.reset()


def test_connect_remote_mtls_partial_config_fail_closed(
    fake_aedt_module, monkeypatch, tmp_path,
):
    """只配一件：注册表解析期 fail-closed（RemoteConfigError 显式点名缺
    件），Desktop 不构造、活跃状态不置位——绝不静默降级 InsecureMode。"""
    from rfauto.infra.remote_machines import (
        RemoteConfigError,
        RemoteMachineConfig,
    )

    cert_dir = _write_canonical_certs(tmp_path / "certs_partial")
    cfg = RemoteMachineConfig(
        name="sim_host", host="10.20.30.40", hfss_grpc_port=50051,
        hfss_ca_cert=str(cert_dir / "ca.crt"),  # 只配一件
    )
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine", lambda name: cfg,
    )
    session = HfssSession.instance()
    with pytest.raises(RemoteConfigError, match="mTLS 证书配置不完整"):
        session.connect({
            "desktop_version": "2025.1", "non_graphical": True,
            "remote_machine": "sim_host",
        })
    assert _FakeDesktop.last_kwargs is None
    assert active_mtls_certs() is None
    HfssSession.reset()


def test_open_or_create_project_remote_mtls_window2_auto(
    fake_aedt_module, monkeypatch, tmp_path,
):
    """adapter 第二构造窗口（Hfss 构造，裸 CM 调用）经活跃状态自动选形
    secure——hfss_adapter.py 零改动即透传。"""
    _patch_adapter_hfss(monkeypatch)
    cert_dir = _write_canonical_certs(tmp_path / "certs_w2")
    monkeypatch.setattr(
        "rfauto.infra.remote_machines.resolve_machine",
        lambda name: _secure_cfg(cert_dir),
    )
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1", "non_graphical": True,
        "remote_machine": "sim_host",
    })
    adapter = HfssAdapter.__new__(HfssAdapter)
    adapter.session = session
    adapter.open_or_create_project("E:\\rfauto_remote\\proj.aedt", "Design1")
    # 第二窗口构造期快照：secure 三开关（remote_rpc_session 被适配层置
    # None 覆写）+ 证书 env 在位 + pre-args 强制 False
    assert _FakeHfss.last_switches == {
        "grpc_local": False,
        "grpc_secure_mode": True,
        "remote_rpc_session": None,
    }
    assert _FakeHfss.last_env == "False"
    assert _FakeHfss.last_certs == str(cert_dir)
    HfssSession.reset()


def test_local_connect_clears_active_mtls(fake_aedt_module):
    """本地 connect 清活跃 mTLS 状态（无跨会话泄漏面）。"""
    from rfauto.infra.remote_machines import HfssMtlsCerts

    set_active_mtls_certs(HfssMtlsCerts("a", "b", "c"))
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "non_graphical": True})
    assert active_mtls_certs() is None
    HfssSession.reset()


def test_remote_session_switches_explicit_mtls_saves_restores_env(
    fake_aedt_module, monkeypatch, tmp_path,
):
    """显式传 spec 的 CM 单元钉：secure 形态逐键 + 外部已有 env 值保存
    恢复（含 PYAEDT_USE_PRE_GRPC_ARGS 外部误设 True 被强制 False）。"""
    from rfauto.infra.remote_machines import HfssMtlsCerts

    cert_dir = _write_canonical_certs(tmp_path / "certs_explicit")
    spec = HfssMtlsCerts(
        str(cert_dir / "ca.crt"), str(cert_dir / "client.crt"),
        str(cert_dir / "client.key"),
    )
    monkeypatch.setenv("PYAEDT_USE_PRE_GRPC_ARGS", "True")
    monkeypatch.setenv("ANSYS_GRPC_CERTIFICATES", "E:\\legacy_certs")
    with remote_session_switches(spec):
        sm = sys.modules["ansys.aedt.core.generic.settings"].settings
        assert sm.grpc_local is False
        assert sm.grpc_secure_mode is True
        assert sm.remote_rpc_session is True
        assert os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] == "False"
        assert os.environ["ANSYS_GRPC_CERTIFICATES"] == str(cert_dir)
    # 退出恢复：pre-args 回外部 True、证书 env 回外部旧值
    assert os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] == "True"
    assert os.environ["ANSYS_GRPC_CERTIFICATES"] == "E:\\legacy_certs"


def test_remote_session_switches_default_stays_insecure(fake_aedt_module):
    """裸调用（无活跃 secure 会话）=缺省路径零变化的直接钉：secure_mode
    False + pre-args True + 证书 env 不触碰。"""
    sm = sys.modules["ansys.aedt.core.generic.settings"].settings
    os.environ.pop("ANSYS_GRPC_CERTIFICATES", None)
    with remote_session_switches():
        assert sm.grpc_secure_mode is False
        assert os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] == "True"
        assert "ANSYS_GRPC_CERTIFICATES" not in os.environ
    assert sm.grpc_secure_mode is True  # 恢复 fixture 初值


def test_remote_session_switches_missing_cert_file_fail_closed(
    fake_aedt_module, tmp_path,
):
    """CM 层二次校验（窗口间文件被删场景）：缺件 ConnectFailedError
    fail-closed，开关/env 不进 secure 形态。"""
    from rfauto.core.errors import ConnectFailedError
    from rfauto.infra.remote_machines import HfssMtlsCerts

    cert_dir = _write_canonical_certs(tmp_path / "certs_gone")
    (cert_dir / "client.key").unlink()
    spec = HfssMtlsCerts(
        str(cert_dir / "ca.crt"), str(cert_dir / "client.crt"),
        str(cert_dir / "client.key"),
    )
    os.environ.pop("ANSYS_GRPC_CERTIFICATES", None)
    with pytest.raises(ConnectFailedError, match="证书文件缺失"), remote_session_switches(spec):
        raise AssertionError("CM 体内不应到达")
    assert "ANSYS_GRPC_CERTIFICATES" not in os.environ
