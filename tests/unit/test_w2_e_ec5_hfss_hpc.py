"""W2-E EC-5——HFSS HPC/DSO 核数旋钮钉（全离线 mock，零真机）。

钉住契约（sa_specs2 §四 EC-5 预声明门值）：

1. **缺省路径零改动**：settings 无 ``hfss_cores`` 时 pyaedt settings.num_cores
   未触碰 + DSO 注册表活动配置名未动（判据 1）；
2. **升档显式生效**：带 ``hfss_cores`` 时 Desktop 构造前 num_cores 已写、
   attach 后 DSO 活动配置切到 ``hfss_dso_config``、``hpc_info`` 生效账在册
   （判据 2 的会话侧证据；引擎日志 distribution 行属真机窗）；
3. **退出恢复**：close 恢复进入前 num_cores 与 DSO 配置名；reconnect 重放
   同一旋钮仍以**最初**原值恢复；
4. **fail-loud 校验**：hfss_cores 非 ≥1 整数显式 ConnectFailedError 且
   Desktop 零构造；
5. **注册表透传**：remote_machines hfss.cores 解析 + hfss_remote_session_config
   仅显式配置时注入 hfss_cores 键（缺省键不存在=消费方零改动）。
"""

import sys
import types
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.hfss_session import HfssSession
from rfauto.core.errors import ConnectFailedError
from rfauto.infra.remote_machines import RemoteMachineConfig, _parse_machine
from rfauto.service import remote_service as rs
from rfauto.service.remote_service import hfss_remote_session_config

_DSO_KEY = "Desktop/ActiveDSOConfigurations/HFSS"


class _FakeOdesktop:
    """模拟 odesktop 注册表面（Get/SetRegistryString 记账）。"""

    def __init__(self, registry: dict[str, str]):
        self.registry = registry
        self.set_calls: list[tuple[str, str]] = []

    def GetRegistryString(self, key: str) -> str:
        return self.registry.get(key, "")

    def SetRegistryString(self, key: str, value: str) -> None:
        self.set_calls.append((key, str(value)))
        self.registry[key] = str(value)


class _FakeDesktop:
    """模拟 ansys.aedt.core.Desktop：记录构造参数与 DSO 操作。"""

    last_kwargs: dict | None = None
    #: Desktop 构造瞬间的 pyaedt settings 快照（num_cores 构造前生效证据）
    last_settings_at_ctor: dict | None = None
    last: "_FakeDesktop | None" = None

    def __init__(self, **kwargs):
        _FakeDesktop.last_kwargs = kwargs
        sm = sys.modules.get("ansys.aedt.core.generic.settings")
        if sm is not None and hasattr(sm, "settings"):
            s = sm.settings
            _FakeDesktop.last_settings_at_ctor = {
                "num_cores": getattr(s, "num_cores", None),
            }
        self.registry = {"Desktop/ActiveDSOConfigurations/HFSS": "Local"}
        self.odesktop = _FakeOdesktop(self.registry)
        self.dso_changes: list[tuple[str, str]] = []
        self.registry_changes: list[tuple[str, str]] = []
        _FakeDesktop.last = self
        self.current_version = "2025.1"

    def change_active_dso_config_name(self, product_name="HFSS",
                                      config_name="Local") -> bool:
        key = f"Desktop/ActiveDSOConfigurations/{product_name}"
        self.dso_changes.append((key, str(config_name)))
        self.registry[key] = str(config_name)
        return True

    def change_registry_key(self, key_full_name: str, key_value) -> bool:
        self.registry_changes.append((key_full_name, str(key_value)))
        self.registry[key_full_name] = str(key_value)
        return True

    def release_desktop(self, close_on_exit=True, close_projects=True):
        self.released = True


class _FakeAedtSettings:
    """模拟 pyaedt settings：num_cores 写入历史 + 远程开关记账。"""

    def __init__(self, initial_num_cores: int = 4):
        self._armed = False
        self.grpc_local = True
        self.grpc_secure_mode = True
        self.remote_rpc_session = False
        self.num_cores = initial_num_cores
        self.num_cores_history: list = []
        self._armed = True

    def __setattr__(self, name, value):
        if getattr(self, "_armed", False) and name == "num_cores":
            self.__dict__.setdefault("num_cores_history", []).append(value)
        super().__setattr__(name, value)


@pytest.fixture()
def fake_aedt(monkeypatch):
    mod = types.ModuleType("ansys.aedt.core")
    mod.Desktop = _FakeDesktop
    generic = types.ModuleType("ansys.aedt.core.generic")
    settings_mod = types.ModuleType("ansys.aedt.core.generic.settings")
    settings_obj = _FakeAedtSettings(initial_num_cores=4)
    settings_mod.settings = settings_obj
    monkeypatch.setitem(sys.modules, "ansys", types.ModuleType("ansys"))
    monkeypatch.setitem(sys.modules, "ansys.aedt",
                        types.ModuleType("ansys.aedt"))
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", mod)
    monkeypatch.setitem(sys.modules, "ansys.aedt.core.generic", generic)
    monkeypatch.setitem(
        sys.modules, "ansys.aedt.core.generic.settings", settings_mod)
    _FakeDesktop.last_kwargs = None
    _FakeDesktop.last_settings_at_ctor = None
    _FakeDesktop.last = None
    HfssSession.reset()
    yield mod, settings_obj
    HfssSession.reset()


# ─── 判据 1：缺省路径零改动 ───────────────────────────────────────────────


def test_default_path_num_cores_and_dso_untouched(fake_aedt):
    """无 hfss_cores：num_cores 零写入、DSO 零触碰、hpc_info=None。"""
    _, fake_settings = fake_aedt
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "non_graphical": True})
    assert fake_settings.num_cores_history == []
    assert fake_settings.num_cores == 4
    assert _FakeDesktop.last is not None
    assert _FakeDesktop.last.dso_changes == []
    assert _FakeDesktop.last.registry[_DSO_KEY] == "Local"
    assert session.hpc_info is None
    # 缺省路径 Desktop 构造 kwargs 与历史逐键相同
    assert set(_FakeDesktop.last_kwargs) == {
        "version", "non_graphical", "student_version", "new_desktop",
    }


# ─── 判据 2：升档显式生效 ─────────────────────────────────────────────────


def test_hfss_cores_applied_before_desktop_and_dso_switched(fake_aedt):
    """hfss_cores=8：构造前 num_cores=8 已写（证据=构造瞬间快照），
    attach 后 DSO 切换 + hpc_info 生效账在册。"""
    _, fake_settings = fake_aedt
    session = HfssSession.instance()
    session.connect({
        "desktop_version": "2025.1",
        "non_graphical": True,
        "hfss_cores": 8,
        "hfss_dso_config": "HPC8",
    })
    # Desktop 构造前 num_cores 已写（旋钮语义=构造前设置才被调度消费）
    assert _FakeDesktop.last_settings_at_ctor == {"num_cores": 8}
    assert fake_settings.num_cores == 8
    # DSO 活动配置显式切换
    assert _FakeDesktop.last.dso_changes == [(_DSO_KEY, "HPC8")]
    # 生效账（判据 2 会话侧证据）
    info = session.hpc_info
    assert info is not None
    assert info["num_cores"] == 8
    assert info["dso_config"] == "HPC8"
    assert info["saved_num_cores"] == 4
    assert info["saved_dso_config"] == "Local"


def test_hfss_cores_default_dso_config_is_local(fake_aedt):
    """hfss_cores 传而 hfss_dso_config 缺省：DSO 切到 "Local"（spec 缺省值）。"""
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "hfss_cores": 4})
    assert _FakeDesktop.last.dso_changes == [(_DSO_KEY, "Local")]
    assert session.hpc_info["dso_config"] == "Local"


# ─── 判据 3：退出恢复 ─────────────────────────────────────────────────────


def test_close_restores_num_cores_and_dso(fake_aedt):
    _, fake_settings = fake_aedt
    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1", "hfss_cores": 8,
                     "hfss_dso_config": "HPC8"})
    session.close(save=False)
    assert fake_settings.num_cores == 4
    assert _FakeDesktop.last.registry_changes == [(_DSO_KEY, "Local")]
    assert session.hpc_info is None


def test_reconnect_replay_restores_original_not_knob_value(fake_aedt):
    """reconnect 重放同一旋钮：close 仍以最初原值恢复（不拿旋钮值当原值）。"""
    _, fake_settings = fake_aedt
    session = HfssSession.instance()
    settings = {"desktop_version": "2025.1", "hfss_cores": 8}
    session.connect(settings)
    # 模拟 reconnect_with_backoff：裸 release（不走 close）→ 重连
    session.desktop.release_desktop(close_on_exit=False, close_projects=False)
    session._connected = False
    session.desktop = None
    session.connect(session._settings)
    assert fake_settings.num_cores == 8
    session.close(save=False)
    # 最初原值 4（若实现拿二次 connect 的 saved=8 当原值则本断言红）
    assert fake_settings.num_cores == 4


# ─── 判据 4：fail-loud 校验 ───────────────────────────────────────────────


@pytest.mark.parametrize("bad", [0, -3, "abc", 1.5])
def test_invalid_hfss_cores_raises_without_desktop(fake_aedt, bad):
    session = HfssSession.instance()
    with pytest.raises(ConnectFailedError, match="hfss_cores"):
        session.connect({"desktop_version": "2025.1", "hfss_cores": bad})
    assert _FakeDesktop.last is None


# ─── 判据 5：注册表透传（hfss.cores → session settings） ─────────────────


def _cfg(cores: int) -> RemoteMachineConfig:
    return RemoteMachineConfig(
        name="sim_host", host="10.20.30.40",
        hfss_project_root="E:\\rfauto_remote", hfss_cores=cores)


def test_parse_machine_hfss_cores_variants():
    base = {"host": "h"}
    assert _parse_machine("m", dict(base)).hfss_cores == 0
    assert _parse_machine(
        "m", {**base, "hfss": {"cores": 8}}).hfss_cores == 8
    # 非法/负值归 0=未配置（不炸注册表装载）
    assert _parse_machine(
        "m", {**base, "hfss": {"cores": "x"}}).hfss_cores == 0
    assert _parse_machine(
        "m", {**base, "hfss": {"cores": -2}}).hfss_cores == 0


def test_session_config_injects_cores_only_when_set(monkeypatch):
    cfg = _cfg(8)
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"m": cfg})
    monkeypatch.setattr(rs, "resolve_machine", lambda m, machines=None: cfg)
    remote = hfss_remote_session_config("m")["remote"]
    assert remote["hfss_cores"] == 8

    cfg0 = _cfg(0)
    monkeypatch.setattr(rs, "load_remote_machines", lambda: {"m": cfg0})
    monkeypatch.setattr(rs, "resolve_machine", lambda m, machines=None: cfg0)
    remote0 = hfss_remote_session_config("m")["remote"]
    assert "hfss_cores" not in remote0


# ─── 判据 2'（接地勘误面）：solve 级 HPC 旋钮（analyze_setup cores/tasks）──


class _FakeHfss:
    """记录 analyze_setup kwargs 的最小 hfss 替身。"""

    last_analyze: dict | None = None
    odesign = None

    def analyze_setup(self, **kwargs):
        _FakeHfss.last_analyze = kwargs
        return True

    def get_setup(self, name):
        # solve() 的 profile 复核/收敛面：get_setup 落空走 passes=0 分支
        return None


def test_solve_default_analyze_setup_kwargs_unchanged(fake_aedt, monkeypatch):
    """无 env/显参：analyze_setup 只收 name+blocking（缺省形态逐键不变）。"""
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_CORES", raising=False)
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_TASKS", raising=False)
    from rfauto.adapters.hfss_adapter import HfssAdapter

    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1"})
    adapter = HfssAdapter()
    adapter.session.hfss = _FakeHfss()
    _FakeHfss.last_analyze = None
    adapter.solve("Setup1")
    # 条件透传（df6③）：缺省不加新 kwargs——旧 stub 零冲击
    assert _FakeHfss.last_analyze == {"name": "Setup1", "blocking": True}


def test_solve_cores_env_and_explicit(fake_aedt, monkeypatch):
    from rfauto.adapters.hfss_adapter import HfssAdapter

    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1"})
    adapter = HfssAdapter()
    adapter.session.hfss = _FakeHfss()
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_CORES", "8")
    _FakeHfss.last_analyze = None
    adapter.solve("Setup1")
    assert _FakeHfss.last_analyze["cores"] == 8
    # 显式传参优先于 env
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_TASKS", "2")
    _FakeHfss.last_analyze = None
    adapter.solve("Setup1", cores=4)
    assert _FakeHfss.last_analyze["cores"] == 4
    assert _FakeHfss.last_analyze["tasks"] == 2


def test_solve_invalid_cores_env_fails_loud(fake_aedt, monkeypatch):
    from rfauto.adapters.hfss_adapter import HfssAdapter

    session = HfssSession.instance()
    session.connect({"desktop_version": "2025.1"})
    adapter = HfssAdapter()
    adapter.session.hfss = _FakeHfss()
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_CORES", "0")
    with pytest.raises(ValueError, match="RFAUTO_HFSS_SOLVE_CORES"):
        adapter.solve("Setup1")
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_CORES", "x")
    with pytest.raises(ValueError, match="RFAUTO_HFSS_SOLVE_CORES"):
        adapter.solve("Setup1")
    # tasks 容许 -1=auto（pyaedt 批量求解语义）
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_CORES")
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_TASKS", "-1")
    _FakeHfss.last_analyze = None
    adapter.solve("Setup1")
    assert _FakeHfss.last_analyze["tasks"] == -1
