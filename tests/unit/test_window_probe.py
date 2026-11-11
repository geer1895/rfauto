"""VB-8 交互式 AEDT 会话三态只读巡检钉（aurora_r R-17 席，全合成零真机）。

钉住契约（PROPOSALS VB-8 + DIGEST §3.6 shared-ciw-dialogs 协议）：

1. **判定纯函数三态**（合成窗口表）：仅主窗→clear；属本 PID 的
   ``#32770`` 模态框→blocked；PID 不可验/拒绝访问→indeterminate；
   零窗口归属→indeterminate（**indeterminate 不等于空闲**——钉死）。
2. **静态守卫**（#270 静态双检先例）：window_probe 模块内变更类
   调用全表零命中 + import 面 stdlib-only + 零 pywin32。
3. **枚举面合成注入**：EnumWindows 回调经 fake user32/kernel32 驱动
   （monkeypatch ``_load_api``）——不真开 AEDT。
4. **开关缺省关调用形状钉**：``RFAUTO_HFSS_DIALOG_GUARD`` 未设时
   预检零接触会话对象（``__getattr__`` 即炸的双）且零探针调用。
5. **opt-in 真机钉**：双 env 门（开关旗标 + PID 旗标）skipif——
   图形 AEDT 手动弹框验收留主代窗口挂账，门/CI 恒 skip。
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_session import (
    ENV_DIALOG_GUARD,
    hfss_dialog_guard_preflight,
)
from rfauto.infra import window_probe
from rfauto.infra.window_probe import (
    DIALOG_CLASS_TABLE,
    MODAL_DIALOG_CLASSES,
    VERDICT_BLOCKED,
    VERDICT_CLEAR,
    VERDICT_INDETERMINATE,
    VERDICTS,
    ProbeResult,
    WindowInfo,
    classify_windows,
    probe_pid_windows,
)

_PID = 4242


def _w(hwnd, cls, *, pid=_PID, visible=True, owner=0) -> WindowInfo:
    """合成窗口行（判定纯函数输入）。"""
    return WindowInfo(
        hwnd=hwnd, pid=pid, class_name=cls, visible=visible, owner=owner)


# ── 1. 判定纯函数三态钉（合成窗口表）────────────────────────────────────


def test_clear_only_main_window():
    """仅主窗（非对话框类）→ clear。"""
    result = classify_windows(_PID, [
        _w(0x101, "Afx:00400000:8:00010003:00000000"),
        _w(0x102, "tooltips_class32", visible=False),
    ])
    assert result.verdict == VERDICT_CLEAR
    assert result.pid_verified is True
    assert result.as_dict()["modal_count"] == 0


def test_blocked_modal_dialog_of_same_pid():
    """属本 PID 的 #32770 模态框（owner 指向主窗）→ blocked。"""
    result = classify_windows(_PID, [
        _w(0x101, "AfxMain"),
        _w(0x102, "#32770", owner=0x101),
    ])
    assert result.verdict == VERDICT_BLOCKED
    assert result.pid_verified is True
    detail = result.as_dict()
    assert detail["modal_count"] == 1
    assert detail["windows"][1]["modal_dialog"] is True
    # 证据链带 owner（归属以 PID/owner 判）
    assert detail["windows"][1]["owner"] == 0x101


def test_blocked_unowned_visible_dialog_still_blocked():
    """无 owner 的可见 #32770 也 blocked（保守偏置：宁假阻塞不假放行）。"""
    result = classify_windows(_PID, [
        _w(0x101, "AfxMain"), _w(0x102, "#32770", owner=0)])
    assert result.verdict == VERDICT_BLOCKED


def test_dialog_of_other_pid_ignored():
    """他进程的对话框不采信（归属以 PID 判）→ clear。"""
    result = classify_windows(_PID, [
        _w(0x101, "AfxMain"), _w(0x102, "#32770", pid=999999)])
    assert result.verdict == VERDICT_CLEAR


def test_hidden_dialog_not_evidence():
    """隐藏 #32770 不构成阻塞证据（判定只看可见窗）→ clear。"""
    result = classify_windows(_PID, [
        _w(0x101, "AfxMain"), _w(0x102, "#32770", visible=False)])
    assert result.verdict == VERDICT_CLEAR


def test_pid_unverifiable_is_indeterminate():
    """PID 不可验（pid_verified=False）→ indeterminate（有窗也不判）。"""
    result = classify_windows(_PID, [_w(0x101, "#32770")], pid_verified=False)
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.pid_verified is False


def test_pid_none_or_junk_is_indeterminate():
    """PID None/非法 → indeterminate。"""
    for junk in (None, 0, -1, "4242", True):
        result = classify_windows(junk, [])
        assert result.verdict == VERDICT_INDETERMINATE, junk


def test_empty_window_table_is_indeterminate_not_clear():
    """零窗口归属→indeterminate：零枚举不是空闲证据（核心语义钉）。"""
    result = classify_windows(_PID, [])
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.pid_verified is True  # PID 本身可验，只是零窗口


def test_indeterminate_semantics_hard_written_in_docstring():
    """\"indeterminate 不等于空闲\"语义写死模块 docstring（结构性钉）。"""
    src = Path(window_probe.__file__).read_text(encoding="utf-8")
    assert "indeterminate 不等于空闲" in src
    assert src.count("indeterminate 不等于空闲") >= 3  # 模块头+判定+探针链


def test_dialog_class_table_machine_readable():
    """机读常量表：#32770 在表、条目三字段齐、三态常量可辨。"""
    assert {"#32770"} == MODAL_DIALOG_CLASSES
    assert DIALOG_CLASS_TABLE[0].role == "modal_dialog"
    assert DIALOG_CLASS_TABLE[0].note
    assert len(set(VERDICTS)) == 3
    assert VERDICT_CLEAR == "clear"
    assert VERDICT_INDETERMINATE == "indeterminate"
    assert VERDICT_BLOCKED == "blocked"


# ── 2. 静态守卫（#270 静态双检先例：文本扫描 + AST import 面）──────────

#: 变更类 Win32 调用全表（本模块内零命中是存在前提——只读探针）。
_MUTATING_TOKENS = (
    "SendMessage", "PostMessage", "EndDialog", "DestroyWindow",
    "SetWindowText", "SetWindowLong", "EnableWindow", "ShowWindow",
    "SetWindowPos", "SendInput", "keybd_event", "mouse_event",
    "SetForegroundWindow", "SetFocus", "PostThreadMessage",
    "CallWindowProc", "SetProp", "RemoveProp",
    "BM_CLICK", "WM_CLOSE", "WM_QUIT", "WM_DESTROY", "WM_COMMAND",
)
_ALLOWED_IMPORTS = {
    "__future__", "ctypes", "ctypes.wintypes", "dataclasses",
    "types", "sys", "typing",
}
_BANNED_MODULES = (
    "win32gui", "win32api", "win32con", "win32process",
    "win32ui", "pywintypes", "pythoncom",
)


def _probe_source() -> str:
    return Path(window_probe.__file__).read_text(encoding="utf-8")


def test_static_no_mutating_window_calls():
    """变更类调用全表零命中（词边界整词扫描，含注释与 docstring 面）。"""
    src = _probe_source()
    for token in _MUTATING_TOKENS:
        assert re.search(rf"\b{re.escape(token)}\b", src) is None, (
            f"只读探针模块出现变更类调用/字面量：{token}")


def test_static_stdlib_only_imports_no_pywin32():
    """import 面 stdlib-only（AST 扫描，字符串伪造无效）且零 pywin32。"""
    tree = ast.parse(_probe_source())
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                seen.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            seen.add(node.module)
    assert seen <= _ALLOWED_IMPORTS, sorted(seen - _ALLOWED_IMPORTS)
    for banned in _BANNED_MODULES:
        assert banned not in seen


# ── 3. 枚举面合成注入钉（EnumWindows 回调 monkeypatch，不真开 AEDT）────


class _FakeApi:
    """合成 user32/kernel32（真枚举链路逻辑 + 自持合成窗口表）。

    ``windows`` 表：hwnd -> (pid, class, visible, owner)。EnumWindows
    逐 hwnd 回调真透传；GetWindowThreadProcessId 经真 ctypes byref
    对象写回（测真写回路径）。
    """

    def __init__(self, windows, *, open_ok=True, enum_fail=False):
        self._windows = windows
        self._open_ok = open_ok
        self._enum_fail = enum_fail
        self.enum_calls = 0
        self.opened: list[int] = []
        self.closed: list[int] = []
        self.user32 = SimpleNamespace(
            EnumWindows=self._enum_windows,
            GetWindowThreadProcessId=self._get_pid,
            IsWindowVisible=lambda hwnd: (
                1 if self._windows[hwnd][2] else 0),
            GetClassNameW=self._get_class,
        )
        self.kernel32 = SimpleNamespace(
            OpenProcess=self._open_process,
            CloseHandle=lambda h: (self.closed.append(h), 1)[1],
        )
        self.wndenumproc = lambda fn: fn  # 回调透传（同步直调）
        self.get_long_ptr = lambda hwnd, index: self._windows[hwnd][3]

    def _enum_windows(self, proc, lparam):
        self.enum_calls += 1
        if self._enum_fail:
            return 0
        for hwnd in self._windows:
            if not proc(hwnd, 0):
                return 0
        return 1

    def _get_pid(self, hwnd, ref):
        ref._obj.value = self._windows[hwnd][0]
        return 1

    def _get_class(self, hwnd, buf, size):
        buf.value = self._windows[hwnd][1]
        return len(buf.value)

    def _open_process(self, access, inherit, pid):
        self.opened.append(pid)
        return 0x1234 if self._open_ok else None


def _seed_table(main_pid=_PID) -> dict[int, tuple]:
    """合成窗口表：主窗 + 本 PID 模态框 + 他 PID 模态框。"""
    return {
        0x201: (main_pid, "AfxFrame", True, 0),
        0x202: (main_pid, "#32770", True, 0x201),
        0x203: (999999, "#32770", True, 0),
    }


def test_enum_face_blocked_via_fake_api(monkeypatch):
    """枚举面注入：本 PID 模态框→blocked；他 PID 窗口不采信不记录。"""
    fake = _FakeApi(_seed_table())
    monkeypatch.setattr(window_probe, "_load_api", lambda: fake)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_BLOCKED
    assert fake.enum_calls == 1
    assert fake.opened == [_PID]
    assert len(fake.closed) == 1  # 查询句柄随取随关
    # 归属过滤：只记录本 PID 两窗，他 PID 的 #32770 不采信
    assert [w.hwnd for w in result.windows] == [0x201, 0x202]
    assert result.as_dict()["modal_count"] == 1


def test_enum_face_clear_via_fake_api(monkeypatch):
    """枚举面注入：仅主窗（无模态框）→ clear。"""
    fake = _FakeApi({0x201: (_PID, "AfxFrame", True, 0)})
    monkeypatch.setattr(window_probe, "_load_api", lambda: fake)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_CLEAR


@pytest.mark.skipif(os.name != "nt",
            reason="EnumWindows 失败路径消费 ctypes.get_last_error=Win32 专属（Linux 上 error 形态不同）——诚实 skip")
def test_enum_failure_is_indeterminate(monkeypatch):
    """EnumWindows 失败→indeterminate（error 摘要在案，不冒充空闲）。"""
    fake = _FakeApi(_seed_table(), enum_fail=True)
    monkeypatch.setattr(window_probe, "_load_api", lambda: fake)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.error is not None and "EnumWindows" in result.error
    assert result.windows == ()


def test_access_denied_is_indeterminate_and_skips_enum(monkeypatch):
    """拒绝访问→indeterminate 且零枚举接触（PID 不可验优先）。"""
    fake = _FakeApi(_seed_table(), open_ok=False)
    monkeypatch.setattr(window_probe, "_load_api", lambda: fake)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.pid_verified is False
    assert fake.enum_calls == 0


def test_non_windows_platform_is_indeterminate(monkeypatch):
    """非 Windows 平台→indeterminate（探针不猜不抛）。"""
    monkeypatch.setattr(window_probe, "_is_windows", lambda: False)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.pid_verified is False


def test_invalid_pid_never_touches_enum_face(monkeypatch):
    """PID None/非法→indeterminate 且零枚举接触。"""
    fake = _FakeApi(_seed_table())
    monkeypatch.setattr(window_probe, "_load_api", lambda: fake)
    for junk in (None, 0, -5, True, "4242"):
        result = probe_pid_windows(junk)
        assert result.verdict == VERDICT_INDETERMINATE, junk
    assert fake.enum_calls == 0
    assert fake.opened == []


def test_probe_internal_exception_is_indeterminate(monkeypatch):
    """探针内部异常→折 indeterminate 绝不上抛（#105 best-effort）。"""
    boom = MagicMock(side_effect=RuntimeError("api bundle gone"))
    monkeypatch.setattr(window_probe, "_load_api", boom)
    result = probe_pid_windows(_PID)
    assert result.verdict == VERDICT_INDETERMINATE
    assert result.error is not None


# ── 4. hfss_dialog_guard_preflight 开关钉（缺省关零接触 + 信封契约）────


class _BombSession:
    """任何属性访问即炸（缺省关=零接触会话对象的形状证据）。"""

    def __getattr__(self, name):
        raise AssertionError(f"开关缺省关不得触碰会话属性：{name}")


def _make_session(pid=_PID, *, non_graphical=False, remote=None):
    return SimpleNamespace(
        desktop_pid=(lambda: pid) if pid is not None else None,
        desktop=SimpleNamespace(aedt_process_id=pid, port=61000),
        non_graphical=non_graphical,
        remote_info=remote,
    )


def _boom_probe(pid):
    raise AssertionError(f"探针被触达（不该发生）：pid={pid}")


def test_guard_default_off_zero_contact(monkeypatch):
    """缺省关：零接触会话对象 + 零探针调用（调用形状钉）。"""
    monkeypatch.delenv(ENV_DIALOG_GUARD, raising=False)
    monkeypatch.setattr(window_probe, "probe_pid_windows", _boom_probe)
    envelope = hfss_dialog_guard_preflight(_BombSession())
    assert envelope["enabled"] is False
    assert envelope["send_allowed"] is True
    assert envelope["verdict"] is None
    assert envelope["probe"] is None
    assert envelope["request_sent"] is None


@pytest.mark.parametrize("token", ["0", "", "false", "off", "yes-no"])
def test_guard_falsy_tokens_stay_off(monkeypatch, token):
    """非真值令牌=关（同款家法：只认显式真值，不猜意图）。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, token)
    monkeypatch.setattr(window_probe, "probe_pid_windows", _boom_probe)
    envelope = hfss_dialog_guard_preflight(_BombSession())
    assert envelope["enabled"] is False
    assert envelope["send_allowed"] is True


@pytest.mark.parametrize("token", ["1", "true", "YES", "on"])
def test_guard_truthy_tokens_enable(monkeypatch, token):
    """真值令牌=开（license_gate 家法；大小写不敏感）。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, token)
    seen: list[int | None] = []

    def fake_probe(pid):
        seen.append(pid)
        return ProbeResult(verdict=VERDICT_CLEAR, pid=pid, reason="合成",
                           pid_verified=True)

    monkeypatch.setattr(window_probe, "probe_pid_windows", fake_probe)
    envelope = hfss_dialog_guard_preflight(_make_session(pid=5150))
    assert envelope["enabled"] is True
    assert envelope["verdict"] == VERDICT_CLEAR
    assert envelope["send_allowed"] is True
    assert seen == [5150]


def test_guard_blocked_yields_not_started_envelope(monkeypatch):
    """blocked→not_started 型信封：拦发 + request_sent=False。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    monkeypatch.setattr(
        window_probe, "probe_pid_windows",
        lambda pid: ProbeResult(
            verdict=VERDICT_BLOCKED, pid=pid, reason="合成模态框",
            pid_verified=True,
            windows=(_w(0x102, "#32770", owner=0x101),)),
    )
    envelope = hfss_dialog_guard_preflight(_make_session())
    assert envelope["verdict"] == VERDICT_BLOCKED
    assert envelope["send_allowed"] is False
    assert envelope["request_sent"] is False
    assert envelope["outcome"] == "not_started"
    assert envelope["probe"]["modal_count"] == 1


def test_guard_indeterminate_fails_closed(monkeypatch):
    """indeterminate→拦发（fail-closed；不等于空闲，不许冒充放行）。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    monkeypatch.setattr(
        window_probe, "probe_pid_windows",
        lambda pid: ProbeResult(
            verdict=VERDICT_INDETERMINATE, pid=pid, reason="合成不可证",
            pid_verified=False),
    )
    envelope = hfss_dialog_guard_preflight(_make_session())
    assert envelope["verdict"] == VERDICT_INDETERMINATE
    assert envelope["send_allowed"] is False
    assert envelope["request_sent"] is False
    assert envelope["outcome"] == "not_started"


def test_guard_headless_session_not_applicable(monkeypatch):
    """无头会话：预检不适用（放行 + 注明），探针零调用。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    monkeypatch.setattr(window_probe, "probe_pid_windows", _boom_probe)
    envelope = hfss_dialog_guard_preflight(
        _make_session(non_graphical=True))
    assert envelope["verdict"] == "not_applicable"
    assert envelope["applicable"] is False
    assert envelope["send_allowed"] is True


def test_guard_remote_session_not_applicable(monkeypatch):
    """远程会话：服务器侧窗口本机不可达，不装样子（放行 + 注明）。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    monkeypatch.setattr(window_probe, "probe_pid_windows", _boom_probe)
    envelope = hfss_dialog_guard_preflight(
        _make_session(remote={"name": "lab_server"}))
    assert envelope["verdict"] == "not_applicable"
    assert envelope["send_allowed"] is True


def test_guard_pid_fallback_via_desktop_attr(monkeypatch):
    """desktop_pid 缺失时经 desktop.aedt_process_id 兜底解析。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    seen: list[int | None] = []

    def fake_probe(pid):
        seen.append(pid)
        return ProbeResult(verdict=VERDICT_CLEAR, pid=pid, reason="合成",
                           pid_verified=True)

    monkeypatch.setattr(window_probe, "probe_pid_windows", fake_probe)
    session = SimpleNamespace(
        desktop_pid=None,
        desktop=SimpleNamespace(aedt_process_id=6060, port=61001),
        non_graphical=False,
        remote_info=None,
    )
    envelope = hfss_dialog_guard_preflight(session)
    assert envelope["pid"] == 6060
    assert seen == [6060]


def test_guard_probe_crash_fails_closed(monkeypatch):
    """探针面自身故障→indeterminate 拦发（守卫面 fail-closed，不上抛）。"""
    monkeypatch.setenv(ENV_DIALOG_GUARD, "1")
    monkeypatch.setattr(
        window_probe, "probe_pid_windows",
        MagicMock(side_effect=ImportError("probe gone")))
    envelope = hfss_dialog_guard_preflight(_make_session())
    assert envelope["verdict"] == VERDICT_INDETERMINATE
    assert envelope["send_allowed"] is False
    assert envelope["request_sent"] is False
    assert envelope["outcome"] == "not_started"


# ── 5. opt-in 真机钉（双 env 门；门/CI 恒 skip，留主代窗口挂账）────────

_REAL_GATE_ENV = "RFAUTO_HFSS_WINDOW_PROBE_REAL"
_REAL_PID_ENV = "RFAUTO_HFSS_WINDOW_PROBE_PID"
_REAL_REASON = (
    "opt-in 真机钉：需 RFAUTO_HFSS_WINDOW_PROBE_REAL=1 且 "
    "RFAUTO_HFSS_WINDOW_PROBE_PID=<图形 ansysedt PID>；验收流程=手动"
    "弹模态框跑 blocked 钉→手动关闭跑 clear 钉（主代窗口挂账）"
)
_real_pid_raw = os.environ.get(_REAL_PID_ENV, "").strip()
_REAL_READY = (
    os.environ.get(_REAL_GATE_ENV) == "1" and _real_pid_raw.isdigit()
)


@pytest.mark.skipif(not _REAL_READY, reason=_REAL_REASON)
def test_real_graphical_aedt_manual_modal_blocked():
    """真机 blocked 钉：手动弹模态框后跑——本 PID 可见 #32770→blocked。"""
    result = probe_pid_windows(int(_real_pid_raw))
    assert result.verdict == VERDICT_BLOCKED, result.as_dict()
    assert result.pid_verified is True
    assert result.as_dict()["modal_count"] >= 1


@pytest.mark.skipif(not _REAL_READY, reason=_REAL_REASON)
def test_real_graphical_aedt_no_dialog_clear():
    """真机 clear 钉：关闭弹窗后跑——无可见模态框→clear。"""
    result = probe_pid_windows(int(_real_pid_raw))
    assert result.verdict == VERDICT_CLEAR, result.as_dict()
