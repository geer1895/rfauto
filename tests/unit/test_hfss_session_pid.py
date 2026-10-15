"""hfss_session PID 捕获兜底钉（#265 武装，w8_pid_probe 批，全 fake 零真机）。

钉住契约（根因：pyaedt 1.4.0 ``aedt_process_id`` 只在 Desktop 类，
desktop.py:934——app 级 ``getattr(hfss, "aedt_process_id", None)`` 恒
None，W5/W6 的"#265 兜底未武装"系误读属性宿主；w8_pid_probe 静态
dir()+真机双证）：

1. **主源**：extract_desktop_pid 读 Desktop 级属性（int 收敛，mock/
   漂移形态→None 不抛）；
2. **兜底**：resolve_desktop_pid 主源缺失时经 desktop_guard 单源枚举
   按 ``-grpcsrv`` 端口=desktop.port 唯一匹配（歧义/失败/禁扫→None）；
3. **连接捕获**：connect() 后 session.desktop_pid 有值、close() 清空；
4. **残留探针**：release 后 PID 仍存活记 warning（warn-only，#105），
   远程会话跳过（本地存活判定对服务器侧 PID 无意义）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_session import (
    HfssSession,
    _grpcsrv_port_from_cmdline,
    extract_desktop_pid,
    resolve_desktop_pid,
)
from rfauto.infra import desktop_guard


class _FakeDesktopWithPid:
    """Desktop 级属性在场的 fake（主源路径）。"""

    def __init__(self, pid=28844, port=61359):
        self.aedt_process_id = pid
        self.port = port

    def release_desktop(self, close_on_exit=True, close_projects=True):
        pass


class _FakeDesktopNoPid:
    """无 aedt_process_id 属性的 fake（兜底路径；app 级对象形态）。"""

    def __init__(self, port=61359):
        self.port = port


def test_extract_desktop_pid_primary_and_coercion():
    assert extract_desktop_pid(_FakeDesktopWithPid(pid=28844)) == 28844
    # 整数字符串收敛（gRPC 面偶发 str 形态）
    assert extract_desktop_pid(_FakeDesktopWithPid(pid="4321")) == 4321


def test_extract_desktop_pid_missing_or_junk_is_none():
    assert extract_desktop_pid(_FakeDesktopNoPid()) is None
    assert extract_desktop_pid(_FakeDesktopWithPid(pid="not-a-pid")) is None
    # mock 属性 int() 失败形态（未配置 stub 的漂移面）——收敛 None 不抛
    weird = MagicMock()
    weird.aedt_process_id.__int__.side_effect = TypeError("boom")
    assert extract_desktop_pid(weird) is None
    assert extract_desktop_pid(None) is None


def test_grpcsrv_port_parses_bare_and_triple_forms():
    # 实测形态（w8_pid_probe 真机）：裸端口
    assert _grpcsrv_port_from_cmdline(
        '"E:\\ANSYSINC\\...\\ansysedt.exe" -grpcsrv 61359 -ng') == 61359
    # pyaedt _get_grpcsrv_args 三段式（TCP/mTLS）
    assert _grpcsrv_port_from_cmdline(
        "ansysedt.exe -grpcsrv 127.0.0.1:50051:SecureMode") == 50051
    # 无旗标/不可解析不猜
    assert _grpcsrv_port_from_cmdline("ansysedt.exe -ng") is None
    assert _grpcsrv_port_from_cmdline("ansysedt.exe -grpcsrv junk") is None


def test_resolve_primary_wins_without_scan(monkeypatch):
    def _boom():
        raise AssertionError("主源在场时不得触发枚举扫描")

    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes", _boom)
    assert resolve_desktop_pid(_FakeDesktopWithPid(pid=1234)) == 1234


def test_resolve_fallback_scan_unique_match(monkeypatch):
    procs = [
        {"pid": 111, "ppid": 1, "cmdline": "ansysedt.exe -ng"},
        {"pid": 222, "ppid": 1, "cmdline": "ansysedt.exe -grpcsrv 61359 -ng"},
    ]
    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes",
                        lambda: procs)
    assert resolve_desktop_pid(_FakeDesktopNoPid(port=61359)) == 222


def test_resolve_fallback_ambiguous_enum_failure_or_disabled(monkeypatch):
    # 多候选=端口歧义，不猜
    dup = [
        {"pid": 1, "ppid": 1, "cmdline": "ansysedt.exe -grpcsrv 61359"},
        {"pid": 2, "ppid": 1, "cmdline": "ansysedt.exe -grpcsrv 61359"},
    ]
    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes", lambda: dup)
    assert resolve_desktop_pid(_FakeDesktopNoPid(port=61359)) is None

    # 枚举失败 best-effort（#105）
    def _boom():
        raise RuntimeError("enum down")

    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes", _boom)
    assert resolve_desktop_pid(_FakeDesktopNoPid(port=61359)) is None

    # 禁扫（远程会话语义）与端口缺失
    monkeypatch.setattr(desktop_guard, "list_ansysedt_processes",
                        lambda: dup)
    assert resolve_desktop_pid(_FakeDesktopNoPid(port=61359),
                               fallback_cmdline_scan=False) is None
    assert resolve_desktop_pid(_FakeDesktopNoPid(port=None)) is None


def test_session_connect_captures_pid_and_close_clears(monkeypatch):
    HfssSession.reset()
    try:
        monkeypatch.setattr(
            "ansys.aedt.core.Desktop",
            lambda **kwargs: _FakeDesktopWithPid(pid=4321))
        session = HfssSession.instance()
        session.connect({"desktop_version": "2025.1",
                         "non_graphical": True})
        assert session.desktop_pid == 4321
        session.close()
        assert session.desktop_pid is None
    finally:
        HfssSession.reset()


def test_close_warns_on_pid_residue_local_only(monkeypatch, caplog):
    HfssSession.reset()
    try:
        monkeypatch.setattr(desktop_guard, "process_alive", lambda pid: True)
        session = HfssSession.instance()
        session.desktop = _FakeDesktopWithPid(pid=9999)
        session._desktop_pid = 9999
        with caplog.at_level("WARNING",
                             logger="rfauto.adapters.hfss_session"):
            session.close()
        assert any("9999" in rec.message and "#265" in rec.message
                   for rec in caplog.records)
        # close 后清空，二次探针不触发
        assert session.desktop_pid is None

        # 远程会话：PID 属服务器侧，本地存活判定跳过
        monkeypatch.setattr(
            desktop_guard, "process_alive",
            lambda pid: pytest.fail("远程会话不得做本地存活判定"))
        session = HfssSession.instance()
        session.desktop = _FakeDesktopWithPid(pid=8888)
        session._desktop_pid = 8888
        session._remote = {"name": "sim_host"}
        with caplog.at_level("WARNING",
                             logger="rfauto.adapters.hfss_session"):
            session.close()
        assert not any("8888" in rec.message for rec in caplog.records)
    finally:
        HfssSession.reset()
