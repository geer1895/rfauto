"""hfss_session 会话健康加固钉（#413，全 fake 零真机）。

钉住契约（#413：失败 AssignWavePort 后 AEDT 会话元数据查询面整体返
None，oboundary.GetBoundaries()/odesign.GetVariables()/GetSolutionType
由 [] 转 None，后续调用连环失败、finally 清理路径必死）：

1. **健康探针**：check_session_health() 依次调可得元数据原始查询，
   None=毒化 / []·非 None=健康，逐探针可归因；探针自身 try 全包
   绝不抛（#105）；
2. **fail-fast**：require_healthy() 毒化即抛 HfssSessionDeadError，
   消息附 AEDT 最后 Desktop 消息（best-effort，取不到注明 unknown）；
3. **自动重建钩子**：reconnect() 复用 connect 路径单次直连重建
   （旧桌面优雅释放 close_on_exit=False 不杀 AEDT 进程），业务
   操作不自动重试；
4. **观测面**：last_desktop_message 与 pyaedt "Last Electronics
   Desktop Message" 同源提取链（GetMessages("", "", 2) + [error]
   标记截取），任何输入形态下不抛。
"""

import sys
import types
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_session import HfssSession, last_desktop_message
from rfauto.core.errors import AdapterError, HfssSessionDeadError, RFAutoError


def _probe_value(value):
    """配置值=Exception 实例时原样抛出（传输级故障形态），否则返回。"""
    if isinstance(value, Exception):
        raise value
    return value


class _FakeOdesktop:
    """模拟裸 odesktop：GetMessages/GetProjectList 可编程返回。"""

    def __init__(self):
        #: severity=2 错误级消息（GetMessages 返回面；None/异常可注入）
        self.messages = []
        self.get_messages_raises = None
        #: 项目列表（[] 健康 / None=桌面面毒化形态 / 异常可注入）
        self.projects = []
        self.get_project_list_raises = None

    def GetMessages(self, project, design, severity):
        if self.get_messages_raises is not None:
            raise self.get_messages_raises
        return self.messages

    def GetProjectList(self):
        if self.get_project_list_raises is not None:
            raise self.get_project_list_raises
        return self.projects


class _FakeDesktop:
    """模拟 ansys.aedt.core.Desktop：记录构造参数与 release 调用。"""

    last: "_FakeDesktop | None" = None

    def __init__(self, **kwargs):
        self.ctor_kwargs = kwargs
        self.odesktop = _FakeOdesktop()
        self.current_version = "2025.1"
        self.release_calls = []
        _FakeDesktop.last = self

    def release_desktop(self, close_on_exit=True, close_projects=True):
        self.release_calls.append(
            {"close_on_exit": close_on_exit, "close_projects": close_projects})


class _FakeOboundary:
    """模拟 oboundary：GetBoundaries 返回 []（健康）/None（#413 毒化）。"""

    def __init__(self, boundaries=()):
        self._boundaries = boundaries
        self.calls = []

    def GetBoundaries(self):
        self.calls.append("GetBoundaries")
        return _probe_value(self._boundaries)


class _FakeOdesign:
    """模拟 odesign：GetVariables/GetSolutionType 同上两态。"""

    def __init__(self, variables=(), solution="Modal"):
        self._variables = variables
        self._solution = solution
        self.calls = []

    def GetVariables(self):
        self.calls.append("GetVariables")
        return _probe_value(self._variables)

    def GetSolutionType(self):
        self.calls.append("GetSolutionType")
        return _probe_value(self._solution)


class _FakeHfss:
    """模拟 ansys.aedt.core.Hfss 的原始对象挂载面（oboundary/odesign）。"""

    def __init__(self, oboundary=None, odesign=None):
        self.oboundary = oboundary if oboundary is not None else _FakeOboundary()
        self.odesign = odesign if odesign is not None else _FakeOdesign()


@pytest.fixture()
def fake_aedt(monkeypatch):
    """注入假 ansys.aedt.core（EC-5 先例同款），隔离真机/真包。"""
    mod = types.ModuleType("ansys.aedt.core")
    mod.Desktop = _FakeDesktop
    monkeypatch.setitem(sys.modules, "ansys", types.ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt",
                        types.ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", mod)
    _FakeDesktop.last = None
    HfssSession.reset()
    yield _FakeDesktop
    HfssSession.reset()


def _connect() -> HfssSession:
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "non_graphical": True})
    return session


# ─── 判据 1：健康路径（[]/非 None=健康） ──────────────────────────────


def test_healthy_session_all_probes_ok(fake_aedt):
    """健康会话：三设计探针+桌面探针全 healthy，poisoned=False。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=[]),
        odesign=_FakeOdesign(variables=["a=1mm"], solution="Modal"),
    )
    health = session.check_session_health()
    assert health["connected"] is True
    assert health["poisoned"] is False
    assert health["errors"] == {}
    assert health["probes"] == {
        "oboundary.GetBoundaries": "healthy",
        "odesign.GetVariables": "healthy",
        "odesign.GetSolutionType": "healthy",
        "odesktop.GetProjectList": "healthy",
    }
    # 原始查询真的被打到（不是空转）
    assert session.hfss.oboundary.calls == ["GetBoundaries"]
    assert session.hfss.odesign.calls == ["GetVariables", "GetSolutionType"]
    # require_healthy 健康面=原样返回探针结果不抛
    assert session.require_healthy() == health


def test_non_empty_probe_values_are_healthy(fake_aedt):
    """非空返回值（已有边界/变量）同样=健康，不误判。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=["BoundarySetup:port1"]),
        odesign=_FakeOdesign(variables=["w=0.5mm"], solution="Modal"),
    )
    session.desktop.odesktop.projects = ["repro_prj"]
    assert session.check_session_health()["poisoned"] is False


# ─── 判据 2：毒化路径（None=#413 签名） ──────────────────────────────


def test_poisoned_all_design_queries_return_none(fake_aedt):
    """#413 全签名：三设计查询由 [] 转 None → poisoned=True。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=None),
        odesign=_FakeOdesign(variables=None, solution=None),
    )
    health = session.check_session_health()
    assert health["poisoned"] is True
    assert health["probes"]["oboundary.GetBoundaries"] == "poisoned"
    assert health["probes"]["odesign.GetVariables"] == "poisoned"
    assert health["probes"]["odesign.GetSolutionType"] == "poisoned"
    # #413 实证桌面进程存活——桌面探针不受毒化影响
    assert health["probes"]["odesktop.GetProjectList"] == "healthy"


def test_poisoned_single_probe_suffices(fake_aedt):
    """任一可得探针返 None 即毒化（部分毒化形态）。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=[]),
        odesign=_FakeOdesign(variables=None, solution="Modal"),
    )
    health = session.check_session_health()
    assert health["poisoned"] is True
    assert health["probes"]["odesign.GetVariables"] == "poisoned"
    assert health["probes"]["odesign.GetSolutionType"] == "healthy"


def test_poisoned_desktop_plane_also_counts(fake_aedt):
    """桌面面 GetProjectList 返 None 属更深层毒化，一并拦下。"""
    session = _connect()
    session.desktop.odesktop.projects = None
    health = session.check_session_health()
    assert health["poisoned"] is True
    assert health["probes"]["odesktop.GetProjectList"] == "poisoned"


# ─── 判据 3：require_healthy fail-fast + 消息增强 ────────────────────


def test_require_healthy_raises_dead_error_with_aedt_message(fake_aedt):
    """毒化即抛 HfssSessionDeadError，附 AEDT [error] 消息（同源提取链）。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=None),
        odesign=_FakeOdesign(variables=None),
    )
    session.desktop.odesktop.messages = [
        "[error] script macro error: port 'portwrongfmt': "
        "length of port lines must be greater than zero.",
    ]
    with pytest.raises(HfssSessionDeadError) as exc_info:
        session.require_healthy()
    exc = exc_info.value
    # 谱系：AdapterError/RFAutoError 家族 + 结构化输出面
    assert isinstance(exc, AdapterError)
    assert isinstance(exc, RFAutoError)
    assert exc.error_type == "HfssSessionDeadError"
    assert exc.to_dict()["error_type"] == "HfssSessionDeadError"
    # AEDT 消息同源附加（[error] 标记截取，非 "unknown"）
    assert "length of port lines must be greater than zero" in str(exc)
    assert exc.details["last_desktop_message"].startswith("[error]")
    assert exc.details["probes"]["odesign.GetVariables"] == "poisoned"


def test_require_healthy_unknown_message_when_unobtainable(fake_aedt):
    """取不到 Desktop 消息时注明 unknown，绝不因取消息二次抛错（#105）。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=None),
        odesign=_FakeOdesign(variables=None),
    )
    session.desktop.odesktop.messages = []
    with pytest.raises(HfssSessionDeadError) as exc_info:
        session.require_healthy()
    assert "unknown" in str(exc_info.value)
    assert exc_info.value.details["last_desktop_message"] is None


# ─── 判据 4：探针自身绝不抛（#105） ──────────────────────────────────


def test_probe_never_raises_on_transport_error(fake_aedt):
    """原始查询抛异常=传输级故障：status=error、探针不抛、不计毒化。"""
    session = _connect()
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=RuntimeError("grpc channel dead")),
        odesign=_FakeOdesign(variables=TimeoutError("rpc timeout"),
                             solution=None),
    )
    session.desktop.odesktop.get_project_list_raises = RuntimeError("boom")
    health = session.check_session_health()  # 不抛即过
    assert health["poisoned"] is True  # GetSolutionType 返 None 仍按值判毒化
    assert health["probes"]["oboundary.GetBoundaries"] == "error"
    assert health["probes"]["odesign.GetVariables"] == "error"
    assert health["probes"]["odesign.GetSolutionType"] == "poisoned"
    assert "RuntimeError" in health["errors"]["oboundary.GetBoundaries"]
    # 纯 error 面（毒化探针清走，只剩抛异常的桌面探针）：error ≠ #413
    # 毒化签名，require_healthy 放行（传输级故障归 health_check/reconnect）
    session.hfss = None
    health2 = session.check_session_health()  # 不抛即过
    assert health2["poisoned"] is False
    assert health2["probes"]["odesktop.GetProjectList"] == "error"
    assert health2["errors"]["odesktop.GetProjectList"] == \
        "RuntimeError: boom"
    assert session.require_healthy()["poisoned"] is False


def test_unavailable_probes_without_design(fake_aedt):
    """已连接未开设计（hfss=None）：设计探针 unavailable，不计毒化。"""
    session = _connect()
    assert session.hfss is None
    health = session.check_session_health()
    assert health["poisoned"] is False
    assert health["probes"]["oboundary.GetBoundaries"] == "unavailable"
    assert health["probes"]["odesign.GetVariables"] == "unavailable"
    assert health["probes"]["odesign.GetSolutionType"] == "unavailable"
    assert health["probes"]["odesktop.GetProjectList"] == "healthy"
    assert session.require_healthy()["connected"] is True


def test_unavailable_when_mounted_object_is_none(fake_aedt):
    """挂载对象属性为 None（如 hfss.odesign=None）同样 unavailable 不抛。"""
    session = _connect()
    hfss = _FakeHfss()
    hfss.odesign = None
    session.hfss = hfss
    health = session.check_session_health()
    assert health["probes"]["odesign.GetVariables"] == "unavailable"
    assert health["probes"]["oboundary.GetBoundaries"] == "healthy"
    assert health["poisoned"] is False


def test_disconnected_session_probe_passes_through(fake_aedt):
    """未连接会话：connected=False、无探针毒化；require_healthy 放行
    （连接面归 health_check/connect，#413 门只管毒化签名）。"""
    session = HfssSession.instance()
    health = session.check_session_health()
    assert health["connected"] is False
    assert health["poisoned"] is False
    assert health["probes"] == {
        "oboundary.GetBoundaries": "unavailable",
        "odesign.GetVariables": "unavailable",
        "odesign.GetSolutionType": "unavailable",
        "odesktop.GetProjectList": "unavailable",
    }
    assert session.require_healthy() == health


# ─── 判据 5：reconnect 自动重建钩子 ──────────────────────────────────


def test_reconnect_rebuilds_poisoned_session(fake_aedt):
    """毒化后 reconnect()：旧桌面优雅释放（不杀进程）→ 新会话健康。"""
    session = _connect()
    old_desktop = session.desktop
    session.hfss = _FakeHfss(
        oboundary=_FakeOboundary(boundaries=None),
        odesign=_FakeOdesign(variables=None),
    )
    assert session.check_session_health()["poisoned"] is True

    session.reconnect()

    # 旧桌面只解绑不杀（close_on_exit=False，#413 场景 AEDT 进程仍存活）
    assert old_desktop.release_calls == [
        {"close_on_exit": False, "close_projects": False}]
    # 复用 connect 路径重建：新 Desktop 实例、同配置
    assert session.desktop is not old_desktop
    assert session.desktop is _FakeDesktop.last
    assert session.desktop.ctor_kwargs == {
        "version": "2025.1",
        "non_graphical": True,
        "student_version": False,
        "new_desktop": True,
    }
    assert session.is_connected is True
    # 新会话挂健康设计面后探针恢复健康（重建≠自动重试业务操作）
    session.hfss = _FakeHfss()
    assert session.check_session_health()["poisoned"] is False
    assert session.require_healthy()["connected"] is True


def test_reconnect_accepts_settings_override(fake_aedt):
    """reconnect(settings) 覆盖连接配置（缺省复用上次 connect 配置）。"""
    session = _connect()
    session.hfss = _FakeHfss(oboundary=_FakeOboundary(boundaries=None))
    session.reconnect({"desktop_version": "2024.2", "non_graphical": False})
    assert session.desktop.ctor_kwargs["version"] == "2024.2"
    assert session.desktop.ctor_kwargs["non_graphical"] is False


def test_reconnect_succeeds_even_when_old_release_raises(fake_aedt):
    """旧桌面释放抛错（传输已死形态）：best-effort 忽略，重建照常。"""
    session = _connect()

    def _boom(close_on_exit=True, close_projects=True):
        raise RuntimeError("already dead")

    session.desktop.release_desktop = _boom
    session.reconnect()
    assert session.is_connected is True
    assert session.desktop is _FakeDesktop.last


# ─── 判据 6：last_desktop_message 提取链（pyaedt 同源配方） ──────────


def test_last_message_extracts_from_error_marker():
    """末条消息含 [error] 标记：从标记处截取（pyaedt 同一字段）。"""
    odesktop = _FakeOdesktop()
    odesktop.messages = [
        "[info] project opened",
        "[error] script macro error: port 'portwrongfmt': "
        "length of port lines must be greater than zero.",
    ]
    text = last_desktop_message(types.SimpleNamespace(odesktop=odesktop))
    assert text == ("[error] script macro error: port 'portwrongfmt': "
                    "length of port lines must be greater than zero.")


def test_last_message_scans_reversed_for_marker():
    """末条无标记时反向扫描取最近一条 [error] 消息。"""
    odesktop = _FakeOdesktop()
    odesktop.messages = [
        "[error] first failure",
        "[warning] later noise",
    ]
    text = last_desktop_message(types.SimpleNamespace(odesktop=odesktop))
    assert text == "[error] first failure"


def test_last_message_falls_back_to_last_raw_message():
    """全列表无 [error] 标记：回落末条原文（不丢弃证据）。"""
    odesktop = _FakeOdesktop()
    odesktop.messages = ["[warning] something odd"]
    text = last_desktop_message(types.SimpleNamespace(odesktop=odesktop))
    assert text == "[warning] something odd"


def test_last_message_returns_none_on_all_unusable_inputs():
    """None desktop / 无消息 / 返 None / 抛异常 / 非 GetMessages 对象：
    一律 None，任何输入形态不抛（#105）。"""
    assert last_desktop_message(None) is None
    assert last_desktop_message(object()) is None
    empty = types.SimpleNamespace(odesktop=_FakeOdesktop())
    assert last_desktop_message(empty) is None
    none_ret = _FakeOdesktop()
    none_ret.messages = None
    assert last_desktop_message(types.SimpleNamespace(odesktop=none_ret)) is None
    raising = _FakeOdesktop()
    raising.get_messages_raises = RuntimeError("grpc dead")
    assert last_desktop_message(types.SimpleNamespace(odesktop=raising)) is None
    # 裸 odesktop 直传（无 .odesktop 包装层）同源可用
    bare = _FakeOdesktop()
    bare.messages = ["[error] boom"]
    assert last_desktop_message(bare) == "[error] boom"
