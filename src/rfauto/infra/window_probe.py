"""交互式 AEDT 会话三态只读巡检（VB-8，aurora_r R-17 席）。

对照目标仓 shared-ciw-dialogs 协议（runs/aurora_q/qx40_vbridge PROPOSALS
VB-8 + DIGEST §3.6）：按 ansysedt PID 枚举顶层窗口，识别模态对话框，
三态判定 ``clear / blocked / indeterminate``——**indeterminate 不等于
空闲**（枚举失败/PID 不可验/拒绝访问/零窗口都落此态，绝不冒充
"干净"）。三态语义与目标仓退出码对齐：``clear``=0 放行、
``indeterminate``=1 不可证、``blocked``=2 有模态框拦发。

只读铁律（本模块存在的前提）：

- 全 API 面只含 Get/Query 类原语（EnumWindows、GetWindowThreadProcessId、
  IsWindowVisible、GetClassNameW、GetWindowLongPtrW、OpenProcess、
  CloseHandle）——**不发消息、不改窗、不点按钮、不关窗**；未知来源弹窗
  一律留给人工（"Never automatically press Enter/Cancel/close"，DIGEST
  §6 第 1 条不吸收清单）。
- 归属判定**只以 PID/owner 判，不以标题判**：窗口归属经
  GetWindowThreadProcessId 取创建进程 PID；owner 经 GetWindowLongPtrW
  （GWL_HWNDPARENT，等价 GetWindow GW_OWNER 语义）取拥有窗句柄——
  全程不读窗口标题文本（标题是脆弱面，且读文本无判定增量）。
- 模态对话框识别走**机读常量表**（:data:`DIALOG_CLASS_TABLE`）：主条目
  ``#32770``（Win32 标准对话框窗口类，AEDT 弹窗/进度/告警窗宿主类）。
- 纯 stdlib + Windows ctypes，**零 pywin32 依赖**（AGENTS 硬限制：新
  依赖默认不进）；非 Windows 平台恒 indeterminate（不抛不猜）。
- 观测面 best-effort（#105 家法）：任何 Win32 调用失败/异常一律折
  indeterminate 返回，绝不上抛阻塞求解主路径——但**守卫消费方按
  fail-closed 处置 indeterminate**（见 adapters.hfss_session
  ``hfss_dialog_guard_preflight``）。

层级：infra（无 rfauto 内部 import）。静态守卫钉（变更类调用全表零
命中 + stdlib-only import 面）见 tests/unit/test_window_probe.py。
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

# ── 三态常量（机读；语义对齐目标仓退出码 0/1/2）─────────────────────────
VERDICT_CLEAR = "clear"
VERDICT_INDETERMINATE = "indeterminate"
VERDICT_BLOCKED = "blocked"
VERDICTS: tuple[str, ...] = (
    VERDICT_CLEAR,
    VERDICT_INDETERMINATE,
    VERDICT_BLOCKED,
)


@dataclass(frozen=True)
class DialogClassInfo:
    """模态对话框窗口类常量表条目（机读，新增识别类只扩本表）。"""

    class_name: str
    role: str
    note: str


#: Win32 系统窗口类机读表。``#32770`` = 标准对话框类（Dialog Manager 注册
#: 的系统原子类）——AEDT 的模态弹窗/求解进度框/许可告警框均宿生于该类。
#: 其余候选（菜单/桌面类等）与本守卫无关，不收录（表=可执行知识，不堆砌）。
DIALOG_CLASS_TABLE: tuple[DialogClassInfo, ...] = (
    DialogClassInfo(
        class_name="#32770",
        role="modal_dialog",
        note="Win32 标准对话框窗口类（系统原子）；AEDT 模态弹窗/进度/告警宿主类",
    ),
)

#: 模态对话框类名集合（判定用快照，单一来源=上表）。
MODAL_DIALOG_CLASSES: frozenset[str] = frozenset(
    entry.class_name for entry in DIALOG_CLASS_TABLE
)


@dataclass(frozen=True)
class WindowInfo:
    """单个顶层窗口的只读快照（判定纯函数的输入行）。

    Attributes:
        hwnd: 窗口句柄（整型快照）。
        pid: 创建进程 PID（GetWindowThreadProcessId 实测）。
        class_name: 窗口类名（GetClassNameW 实测；取不到 None）。
        visible: 可见性（IsWindowVisible 实测）——判定只看可见窗，
            隐藏辅助对话框不构成阻塞证据（降低假 blocked）。
        owner: 拥有窗句柄（GWL_HWNDPARENT 实测；0=无 owner）。
    """

    hwnd: int
    pid: int
    class_name: str | None
    visible: bool
    owner: int = 0

    @property
    def is_modal_dialog(self) -> bool:
        """类名命中机读模态对话框表（可见性与归属由判定函数合成）。"""
        return self.class_name in MODAL_DIALOG_CLASSES

    def as_dict(self) -> dict[str, Any]:
        """信封友好快照（机读，判定证据链随信封走）。"""
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "class_name": self.class_name,
            "visible": self.visible,
            "owner": self.owner,
            "modal_dialog": self.is_modal_dialog,
        }


@dataclass(frozen=True)
class ProbeResult:
    """三态判定结果（不可变；信封消费方只读）。

    Attributes:
        verdict: 三态之一（:data:`VERDICTS`）。**indeterminate 不等于
            空闲**——它是"不可证"，不是"干净"。
        pid: 目标 ansysedt PID（入参原样；None=入参不可验）。
        reason: 人读判定依据（一句话，随日志/信封走）。
        pid_verified: PID 可验性（进程句柄可开=可验；拒绝访问/进程
            不存在/平台不支持=False）。
        windows: 归属目标 PID 的顶层窗口快照（只含本 PID 的窗；
            他窗不采信也不记录）。
        error: 枚举/检查面失败摘要（无失败 None）。
    """

    verdict: str
    pid: int | None
    reason: str
    pid_verified: bool = False
    windows: tuple[WindowInfo, ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """信封友好快照（窗口行逐条机读，证据链完整）。"""
        return {
            "verdict": self.verdict,
            "pid": self.pid,
            "reason": self.reason,
            "pid_verified": self.pid_verified,
            "error": self.error,
            "windows": [w.as_dict() for w in self.windows],
            "modal_count": sum(
                1 for w in self.windows
                if w.visible and w.is_modal_dialog
            ),
        }


# ── 判定纯函数（三态钉靶心；合成窗口表全量测试，不真开 AEDT）──────────


def classify_windows(
    pid: int | None,
    windows: tuple[WindowInfo, ...] | list[WindowInfo],
    *,
    pid_verified: bool = True,
) -> ProbeResult:
    """三态判定纯函数（无 I/O，合成窗口表可测）。

    判定序（先不可证后阻塞后干净——fail-unknown 优先）：

    1. PID 不可验（None/非正整/pid_verified=False）→ indeterminate；
    2. 枚举成功但零窗口归属 → indeterminate（**零窗口不是空闲证据**：
       可能是无头进程、会话窗口站隔离或进程将死——不可冒充 clear）；
    3. 任一**可见**窗口属于本 PID 且类名命中 :data:`MODAL_DIALOG_CLASSES`
       → blocked（保守偏置：宁假阻塞不假放行——假阻塞用户关守卫即可，
       假放行把字节发进被模态框卡死的会话）；
    4. 其余 → clear。

    Args:
        pid: 目标 ansysedt PID（None/非法 → indeterminate）。
        windows: 顶层窗口快照表（已按 PID 过滤或混表均可——判定只认
            ``w.pid == pid`` 的行）。
        pid_verified: PID 可验性（枚举面传入；False → indeterminate）。

    Returns:
        :class:`ProbeResult`（verdict + 证据链快照）。
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return ProbeResult(
            verdict=VERDICT_INDETERMINATE,
            pid=pid if isinstance(pid, int) else None,
            reason="PID 不可验（None/非法）——三态按 fail-unknown 落"
                   " indeterminate；indeterminate 不等于空闲",
            pid_verified=False,
            windows=tuple(windows),
        )
    if not pid_verified:
        return ProbeResult(
            verdict=VERDICT_INDETERMINATE,
            pid=pid,
            reason="PID 存在性/可访问性不可证（拒绝访问或平台不支持）——"
                   "indeterminate 不等于空闲",
            pid_verified=False,
            windows=tuple(windows),
        )
    owned = tuple(w for w in windows if w.pid == pid)
    if not owned:
        return ProbeResult(
            verdict=VERDICT_INDETERMINATE,
            pid=pid,
            reason="PID 可验但零顶层窗口归属——可能是无头形态/会话窗口站"
                   "隔离/进程将死；零窗口不是空闲证据，indeterminate "
                   "不等于空闲",
            pid_verified=True,
            windows=(),
        )
    modal = tuple(
        w for w in owned if w.visible and w.is_modal_dialog
    )
    if modal:
        hwnds = ", ".join(str(w.hwnd) for w in modal)
        owners = ", ".join(str(w.owner) for w in modal)
        return ProbeResult(
            verdict=VERDICT_BLOCKED,
            pid=pid,
            reason=f"检测到 {len(modal)} 个本 PID 可见模态对话框"
                   f"（类 {'/'.join(sorted(MODAL_DIALOG_CLASSES))}，"
                   f"hwnd {hwnds}，owner {owners}）——交互面被占用，"
                   "未裁决前不得发送",
            pid_verified=True,
            windows=owned,
        )
    return ProbeResult(
        verdict=VERDICT_CLEAR,
        pid=pid,
        reason=f"本 PID {len(owned)} 个顶层窗口均非可见模态对话框"
               "（归属以 PID/owner 判，不以标题判）",
        pid_verified=True,
        windows=owned,
    )


# ── 枚举面（Windows ctypes；tests 经 _load_api 注入合成 user32/kernel32）


def _is_windows() -> bool:
    """平台判定（tests monkeypatch 注入点，不动全局 sys.platform）。"""
    return sys.platform == "win32"


#: PROCESS_QUERY_LIMITED_INFORMATION（Vista+；只查基本信息不需高权）。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_GWL_HWNDPARENT = -8  # 拥有窗句柄（等价 GetWindow GW_OWNER 语义）
_CLASS_BUF_CHARS = 256


def _load_api() -> Any | None:
    """装载 Win32 API 面（tests monkeypatch 注入点；非 Windows 返回 None）。

    返回 ``SimpleNamespace(user32=..., kernel32=...)``，函数签名一次
    配齐；64 位下取 ``GetWindowLongPtrW``（指针安全），32 位回退
    ``GetWindowLongW``（窗口句柄在 Win64 上仅低 32 位有效，句柄截断
    不丢信息——owner 是证据字段不是操作句柄，本模块从不对它调用）。
    """
    if not _is_windows():
        return None
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    wndenumproc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = (wndenumproc, wt.LPARAM)
    user32.EnumWindows.restype = wt.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.IsWindowVisible.argtypes = (wt.HWND,)
    user32.IsWindowVisible.restype = wt.BOOL
    user32.GetClassNameW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    get_long_ptr = getattr(user32, "GetWindowLongPtrW", None)
    if get_long_ptr is not None:
        get_long_ptr.argtypes = (wt.HWND, ctypes.c_int)
        get_long_ptr.restype = ctypes.c_ssize_t
    else:  # 32 位 Python 无 PtrW 变体
        get_long_ptr = user32.GetWindowLongW
        get_long_ptr.argtypes = (wt.HWND, ctypes.c_int)
        get_long_ptr.restype = ctypes.c_long
    # 注意：OpenProcess 无 W/A 变体拆分（kernel32 单一导出名）——
    # 本机真机冒烟实证（2026-11-10 R-17）：取 OpenProcessW 即
    # AttributeError 折不可证。
    kernel32.OpenProcess.argtypes = (
        wt.DWORD, wt.BOOL, wt.DWORD)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)
    kernel32.CloseHandle.restype = wt.BOOL
    return SimpleNamespace(
        user32=user32, kernel32=kernel32, wndenumproc=wndenumproc,
        get_long_ptr=get_long_ptr,
    )


def _process_queryable(api: Any, pid: int) -> tuple[bool, str | None]:
    """PID 可验性检查（OpenProcessW 只查句柄，随取随关，无副作用面）。

    Returns:
        (可验, 失败原因)：拒绝访问/进程不存在 → (False, 原因)——调用方
        折 indeterminate；成功句柄立即关闭并 (True, None)。
    """
    handle = api.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        api.kernel32.CloseHandle(handle)
        return True, None
    err = ctypes.get_last_error()
    if err == _ERROR_ACCESS_DENIED:
        return False, "拒绝访问（OpenProcess ERROR_ACCESS_DENIED）"
    if err == _ERROR_INVALID_PARAMETER:
        return False, "进程不存在（OpenProcess ERROR_INVALID_PARAMETER）"
    return False, f"OpenProcess 失败（winerror={err}）"


def _enumerate_windows(pid: int, api: Any) -> tuple[tuple[WindowInfo, ...], str | None]:
    """枚举归属 pid 的顶层窗口快照（只读面本体）。

    EnumWindows 回调只收集句柄；归属（PID）、类名、可见性、owner 逐窗
    Get 实测，他窗直接跳过不记录。任一本 PID 窗口检查失败 → 整表作废
    返回错误（部分证据不参与判定，fail-unknown 优先于部分放行）。

    Returns:
        (窗口快照表, 错误摘要)：EnumWindows 失败或逐窗检查失败时
        error 非 None（调用方折 indeterminate）。
    """
    hwnds: list[int] = []

    def _collect(hwnd: Any, _lparam: Any) -> int:
        hwnds.append(int(hwnd) if hwnd is not None else 0)
        return 1  # 继续枚举（TRUE）

    proc = api.wndenumproc(_collect)
    if not api.user32.EnumWindows(proc, 0):
        err = ctypes.get_last_error()
        return (), f"EnumWindows 失败（winerror={err}）"

    windows: list[WindowInfo] = []
    for hwnd in hwnds:
        pid_ref = ctypes.c_ulong(0)
        api.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
        if pid_ref.value != pid:
            continue  # 他窗不采信不记录（归属以 PID 判）
        visible = bool(api.user32.IsWindowVisible(hwnd))
        buf = ctypes.create_unicode_buffer(_CLASS_BUF_CHARS)
        copied = api.user32.GetClassNameW(hwnd, buf, _CLASS_BUF_CHARS)
        if copied <= 0:
            err = ctypes.get_last_error()
            return (), f"GetClassNameW 失败（hwnd={hwnd}，winerror={err}）"
        owner = int(api.get_long_ptr(hwnd, _GWL_HWNDPARENT))
        windows.append(WindowInfo(
            hwnd=hwnd, pid=pid, class_name=buf.value or None,
            visible=visible, owner=owner,
        ))
    return tuple(windows), None


def probe_pid_windows(pid: int | None) -> ProbeResult:
    """按 ansysedt PID 做三态只读巡检（本模块对外主入口）。

    链路：平台检查 → PID 可验性（OpenProcessW）→ 顶层窗口枚举 →
    :func:`classify_windows` 三态。任何一步失败/异常折 indeterminate
    （#105 best-effort：探针绝不上抛阻塞求解主路径；守卫消费方对
    indeterminate 自行 fail-closed）。

    Args:
        pid: ansysedt PID（None/非法 → indeterminate，不碰枚举面）。

    Returns:
        :class:`ProbeResult`（三态 + 窗口证据链）。
    """
    try:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return classify_windows(pid, (), pid_verified=False)
        api = _load_api()
        if api is None:
            return ProbeResult(
                verdict=VERDICT_INDETERMINATE, pid=pid,
                reason="非 Windows 平台——窗口枚举面不可达（探针不猜）",
                pid_verified=False, windows=(),
            )
        ok, reason = _process_queryable(api, pid)
        if not ok:
            return ProbeResult(
                verdict=VERDICT_INDETERMINATE, pid=pid,
                reason=f"PID 不可验：{reason}——indeterminate 不等于空闲",
                pid_verified=False, windows=(),
            )
        windows, error = _enumerate_windows(pid, api)
        if error is not None:
            return ProbeResult(
                verdict=VERDICT_INDETERMINATE, pid=pid,
                reason=f"窗口枚举面失败——indeterminate 不等于空闲：{error}",
                pid_verified=True, windows=(),
                error=error,
            )
        return classify_windows(pid, windows, pid_verified=True)
    except Exception as exc:  # 观测面绝不二次抛（#105）；守卫折 fail-closed
        return ProbeResult(
            verdict=VERDICT_INDETERMINATE, pid=pid if isinstance(pid, int) else None,
            reason=f"探针内部异常折不可证（indeterminate 不等于空闲）：{exc!r}",
            pid_verified=False, windows=(), error=repr(exc)[:200],
        )
