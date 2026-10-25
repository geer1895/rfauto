"""HFSS 工程导入器测试（PyAEDT mock，不依赖真实 HFSS 安装）。"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, ClassVar

import pytest

from rfauto.adapters import hfss_import


class _VarInfo:
    def __init__(self, expression, numeric, units, dependent=False):
        self.expression = expression
        self.numeric_value = numeric
        self.units = units
        self.is_dependent = dependent


class _VarManager:
    design_variables: ClassVar[dict] = {
        "L_arm": _VarInfo("18.1mm", 18.1, "mm"),
        "W_feed": _VarInfo("1.113mm", 1.113, "mm"),
        "L_total": _VarInfo("L_arm*2", 36.2, "mm", dependent=True),
        "chip_name": _VarInfo("abc", None, "", dependent=False),
    }

    def design_variable_names(self):
        return list(self.design_variables)


class _Sweep:
    name = "Sweep"
    props: ClassVar[dict[str, Any]] = {
        "Type": "Interpolating", "RangeStart": "1.5GHz",
        "RangeEnd": "3.5GHz", "RangeStep": "10MHz"}


class _Setup:
    name = "Setup1"
    props: ClassVar[dict[str, Any]] = {"Frequency": "2.5GHz"}
    sweeps: ClassVar[list] = [_Sweep()]


class _Boundary:
    def __init__(self, name, btype):
        self.name = name
        self.type = btype


class _Parametric:
    name = "OptimetricsSet1"
    props: ClassVar[dict[str, Any]] = {
        "Variable": "L_arm", "Start": "17mm", "Stop": "19mm", "Step": "0.5mm"}


class _FakeHfss:
    """按实装 pyaedt 1.4.0 真实形态建模的替身：**无 .release() 属性**
    （review_aurora_next A5 P0-2——替身多出 release() 会把生产码
    hfss.release() 的 AttributeError 在单测面永久假绿遮蔽）。
    释放面=release_desktop/close_desktop，调用记录在 self.released 供断言。"""

    design_name = "Design1"
    variable_manager = _VarManager()
    setups: ClassVar[list] = [_Setup()]
    boundaries: ClassVar[list] = [_Boundary("Port1", "Wave Port"),
                                  _Boundary("PerfE1", "Perfect E")]
    parametrics: ClassVar[list] = [_Parametric()]

    def __init__(self):
        self.released: list = []

    def release_desktop(self, close_projects=True, close_desktop=True):
        self.released.append(("release_desktop", close_projects, close_desktop))
        return True


@pytest.fixture()
def mock_open(monkeypatch):
    spy: dict = {}

    def _open(*a, **kw):
        spy["hfss"] = _FakeHfss()
        return spy["hfss"]

    monkeypatch.setattr(hfss_import, "_open_hfss", _open)
    return spy


def test_fake_hfss_models_real_pyaedt_no_release_attr():
    """A5 P0-2 防再犯钉：替身必须无 .release()（实装 pyaedt 1.4.0 Hfss
    MRO 全链无此属性，hasattr=False——替身多出即遮蔽生产码释放缺陷）。"""
    assert not hasattr(_FakeHfss(), "release")


def test_import_spec_reads_all_sections(mock_open, tmp_path):
    project = tmp_path / "fake.aedt"
    project.write_text("", encoding="utf-8")
    spec = hfss_import.import_project_spec(str(project))
    assert spec["ok"]
    assert spec["design"] == "Design1"
    assert spec["variables"]["L_arm"]["value"] == "18.1"
    assert spec["variables"]["L_total"]["dependent"] is True
    assert spec["parametrics"]["L_arm"] == {"start": "17mm", "stop": "19mm",
                                            "step": "0.5mm"}
    assert spec["setup"]["setup_name"] == "Setup1"
    assert spec["setup"]["sweeps"][0]["range_start"] == "1.5GHz"
    assert {p["name"] for p in spec["ports"]} == {"Port1", "PerfE1"}
    # A5 P0-1 释放钉：finally 走单源 _release_hfss（真 pyaedt 1.4.0 无
    # .release()，替身也必须无）→ release_desktop(False, True) 绝不保存
    assert mock_open["hfss"].released == [("release_desktop", False, True)]


def test_recipe_draft_uses_parametrics_ranges(mock_open, tmp_path):
    project = tmp_path / "fake.aedt"
    project.write_text("", encoding="utf-8")
    spec = hfss_import.import_project_spec(str(project))
    draft = hfss_import.spec_to_recipe_draft(spec)
    assert draft["ok"]
    recipe = draft["recipe"]
    # 依赖变量/非数值变量不进优化空间
    assert set(recipe["params"]) == {"L_arm", "W_feed"}
    # 扫参范围优先（HFSS 里用户设的 17-19mm）
    assert recipe["params"]["L_arm"] == {"value": 18.1, "low": 17.0, "high": 19.0}
    # 无扫参范围的给 ±20% 默认
    assert recipe["params"]["W_feed"]["low"] == pytest.approx(0.8904)
    assert recipe["hfss_var_map"]["L_arm"] == "L_arm"
    # 频率范围从 Sweep 提取（GHz）
    assert recipe["setup"]["freq_range_ghz"] == [1.5, 3.5]


def test_missing_project_file_fails_cleanly():
    spec = hfss_import.import_project_spec("Z:/no_such.aedt")
    assert not spec["ok"]
    assert "不存在" in spec["error"]


def test_draft_rejects_invalid_spec():
    draft = hfss_import.spec_to_recipe_draft({"ok": False, "error": "x"})
    assert not draft["ok"]


# ─── B-27：只读导入 + 端到端 + 渲染往返（全离线，mock PyAEDT）───────────────


class _ReadonlySpyHfss(_FakeHfss):
    """记录释放/自动保存调用的伪 Hfss（pyaedt 1.4.0 无 .release()）。"""

    def __init__(self):
        self.autosave_calls = 0
        self.released = []

    def autosave_disable(self):
        self.autosave_calls += 1

    def release_desktop(self, close_projects=True, close_desktop=True):
        self.released.append(("release_desktop", close_projects, close_desktop))
        return True


@pytest.fixture()
def mock_readonly(monkeypatch):
    """钉住只读打开通道，记录实际打开的路径/版本/会话参数。"""
    spy = {}

    def _open(path, design, version, non_graphical, **kwargs):
        spy["path"] = path
        spy["design"] = design
        spy["version"] = version
        spy["non_graphical"] = non_graphical
        spy["kwargs"] = kwargs
        spy["hfss"] = _ReadonlySpyHfss()
        return spy["hfss"]

    monkeypatch.setattr(hfss_import, "_open_hfss_readonly", _open)
    return spy


def test_readonly_import_opens_temp_copy_and_preserves_source(mock_readonly, tmp_path):
    from pathlib import Path

    project = tmp_path / "real.aedt"
    project.write_text("$begin 'AnsoftProject'", encoding="utf-8")
    # 源目录带锁文件：只读导入读副本，不受 .lock 阻塞（import_project_spec 才阻塞）
    (tmp_path / "real.aedt.lock").mkdir()
    before = project.read_text(encoding="utf-8")
    mtime_before = project.stat().st_mtime_ns

    spec = hfss_import.import_project_spec_readonly(str(project), version="2025.1")

    assert spec["ok"] is True
    assert spec["read_only_copy"] is True
    assert spec["source_locked"] is True
    # 打开的是副本且副本已随临时目录删除，原件内容/mtime 未被碰
    opened = Path(mock_readonly["path"])
    assert opened != project
    assert opened.name == project.name
    assert not opened.exists()
    assert project.read_text(encoding="utf-8") == before
    assert project.stat().st_mtime_ns == mtime_before
    # provenance 指回用户原件；版本按显式传入透传
    assert spec["project"] == str(project)
    assert mock_readonly["version"] == "2025.1"
    # 规格字段与 import_project_spec 一致
    assert spec["variables"]["L_arm"]["value"] == "18.1"
    assert spec["setup"]["sweeps"][0]["range_start"] == "1.5GHz"
    # 释放走 release_desktop(close_projects=False, close_desktop=True)，且关自动保存
    assert mock_readonly["hfss"].released == [("release_desktop", False, True)]
    assert mock_readonly["hfss"].autosave_calls == 1


def test_readonly_import_timeout_reports_explicitly(monkeypatch, tmp_path):
    import time

    project = tmp_path / "slow.aedt"
    project.write_text("", encoding="utf-8")

    def _slow_open(*args, **kwargs):
        time.sleep(0.4)
        return _ReadonlySpyHfss()

    monkeypatch.setattr(hfss_import, "_open_hfss_readonly", _slow_open)
    result = hfss_import.import_project_spec_readonly(str(project), timeout_s=0.05)

    assert result["ok"] is False
    assert "超时" in result["error"]


def test_release_hfss_prefers_release_desktop_and_never_saves():
    class _Spy:
        def __init__(self):
            self.calls = []

        def release_desktop(self, **kwargs):
            self.calls.append(("release_desktop", kwargs))

        def release(self):
            self.calls.append(("release", {}))

        def save_project(self):
            self.calls.append(("save_project", {}))

    spy = _Spy()
    hfss_import._release_hfss(spy)
    assert spy.calls == [("release_desktop",
                           {"close_projects": False, "close_desktop": True})]


def test_release_hfss_falls_back_to_legacy_release():
    class _Old:
        def __init__(self):
            self.called = False

        def release(self):
            self.called = True

    old = _Old()
    hfss_import._release_hfss(old)
    assert old.called is True


def test_resolve_aedt_version_explicit_wins():
    assert hfss_import._resolve_aedt_version("2025.1") == "2025.1"


def test_import_project_recipe_end_to_end(mock_readonly, tmp_path):
    project = tmp_path / "fake.aedt"
    project.write_text("", encoding="utf-8")

    result = hfss_import.import_project_recipe(str(project))

    assert result["ok"] is True
    recipe = result["recipe"]
    assert recipe["model"] == "custom_hfss"
    # 依赖变量/非数值变量不进优化空间
    assert set(recipe["params"]) == {"L_arm", "W_feed"}
    assert recipe["params"]["L_arm"] == {"value": 18.1, "low": 17.0, "high": 19.0}
    assert recipe["params"]["W_feed"]["low"] == pytest.approx(0.8904)
    # 函数签名（hfss_var_map）覆盖全部可调参数
    assert all(name in recipe["hfss_var_map"] for name in recipe["params"])
    assert recipe["hfss_var_map"]["L_arm"] == "L_arm"
    assert recipe["setup"]["freq_range_ghz"] == [1.5, 3.5]
    assert recipe["source_project"] == str(project)
    assert recipe["source_design"] == "Design1"
    assert result["validation"]["ok"] is True
    assert result["error"] is None


def test_validate_recipe_draft_render_roundtrip(mock_readonly, tmp_path):
    import yaml

    project = tmp_path / "fake.aedt"
    project.write_text("", encoding="utf-8")
    recipe = hfss_import.import_project_recipe(str(project))["recipe"]

    check = hfss_import.validate_recipe_draft(recipe)

    assert check["ok"], check["errors"]
    # 渲染成 HFSS 设计变量表达式（优化器写 HFSS 的同一通道）
    assert check["hfss_variables"]["L_arm"] == "18.1mm"
    assert check["hfss_variables"]["W_feed"] == "1.113mm"
    # YAML 格式往返等值（G16 格式面）
    assert yaml.safe_load(check["recipe_yaml"]) == recipe
    assert "recipe_version: 1" in check["recipe_yaml"]


def test_draft_to_hfss_variables_honors_var_map():
    recipe = {
        "model": "custom_hfss",
        "params": {"arm_len_mm": {"value": 18.1, "low": 17.0, "high": 19.0}},
        "hfss_var_map": {"arm_len_mm": "L_arm"},
        "setup": {"freq_range_ghz": [1.0, 2.0], "points": 101},
    }
    assert hfss_import.draft_to_hfss_variables(recipe) == {"L_arm": "18.1mm"}
    assert hfss_import.validate_recipe_draft(recipe)["ok"] is True


def test_validate_recipe_draft_reports_bad_draft_explicitly():
    bad = {
        "model": "custom_hfss",
        "params": {"L_arm": {"value": 20.0, "low": 19.0, "high": 17.0}},
        "hfss_var_map": {},
        "setup": {"freq_range_ghz": [3.5, 1.5]},
    }

    check = hfss_import.validate_recipe_draft(bad)

    assert check["ok"] is False
    joined = " ".join(check["errors"])
    assert "范围颠倒" in joined
    assert "freq_range_ghz" in joined
    assert any("未在 hfss_var_map" in w for w in check["warnings"])


def test_validate_recipe_draft_reports_degenerate_range():
    draft = {
        "model": "custom_hfss",
        "params": {"nn": {"value": 0.0, "low": 0.0, "high": 0.0}},
        "hfss_var_map": {"nn": "nn"},
        "setup": {"freq_range_ghz": [1.0, 10.0], "points": 101},
    }

    check = hfss_import.validate_recipe_draft(draft)

    assert check["ok"] is True
    assert any("范围退化" in w for w in check["warnings"])


def test_validate_recipe_draft_missing_fields():
    check = hfss_import.validate_recipe_draft({"params": {}})

    assert check["ok"] is False
    joined = " ".join(check["errors"])
    assert "缺少 'model' 字段" in joined
    assert "缺少 'setup' 字段" in joined


def test_validate_recipe_draft_rejects_non_mapping():
    check = hfss_import.validate_recipe_draft(["not", "a", "recipe"])
    assert check["ok"] is False
    assert "映射" in check["errors"][0]


def test_import_project_recipe_missing_file_fails_cleanly():
    result = hfss_import.import_project_recipe("Z:/no_such.aedt")
    assert result["ok"] is False
    assert "不存在" in result["error"]
    assert result["recipe"] is None


def test_detect_derived_variables_flags_expression_refs():
    spec = {
        "variables": {
            "h1": {"expression": "h0+hmetal*2+hsub1", "dependent": False},
            "hsub1": {"expression": "0.265mm", "dependent": False},
            "h0": {"expression": "0mm", "dependent": False},
            "hmetal": {"expression": "0.035mm", "dependent": False},
            "nn": {"expression": "0", "dependent": False},
        }
    }
    assert hfss_import.detect_derived_variables(spec) == ["h1"]


class _DerivedVarManager:
    design_variables: ClassVar[dict] = {
        "hsub1": _VarInfo("0.265mm", 0.265, "mm"),
        "hmetal": _VarInfo("0.035mm", 0.035, "mm"),
        # 表达式派生，但 pyaedt is_dependent 漏标为 False（真机实证口径）
        "h1": _VarInfo("hmetal*2+hsub1", 0.335, "mm", dependent=False),
    }

    def design_variable_names(self):
        return list(self.design_variables)


class _DerivedFakeHfss(_FakeHfss):
    variable_manager = _DerivedVarManager()


def test_import_project_recipe_excludes_derived_variables(monkeypatch, tmp_path):
    project = tmp_path / "derived.aedt"
    project.write_text("", encoding="utf-8")
    monkeypatch.setattr(hfss_import, "_open_hfss_readonly",
                        lambda *args, **kwargs: _DerivedFakeHfss())

    result = hfss_import.import_project_recipe(str(project))

    assert result["ok"] is True
    assert result["excluded_derived"] == ["h1"]
    assert set(result["recipe"]["params"]) == {"hsub1", "hmetal"}
    assert "h1" not in result["recipe"]["hfss_var_map"]
    assert any("派生变量" in w for w in result["validation"]["warnings"])


# ─── 多机协同 v0（B13）：hfss_import remote_machine 透传（mock，#139 钉通道）──


class _RemoteCfg:
    """infra.remote_machines.RemoteMachineConfig 的 duck（免真实注册表）。"""

    name = "sim_server"
    host = "10.20.30.40"
    hfss_grpc_port = 15555
    hfss_project_root = "E:/rfauto_remote"
    hfss_version = "2025.1"
    hfss_ca_cert = None
    hfss_client_cert = None
    hfss_client_key = None


@pytest.fixture()
def remote_registry(monkeypatch):
    """钉住注册表解析通道（#139：单测不读 configs，不真连）。"""
    from rfauto.infra import remote_machines as rm

    monkeypatch.setattr(rm, "resolve_machine",
                        lambda name=None, machines=None: _RemoteCfg())


@pytest.fixture()
def remote_open_spy(monkeypatch):
    """钉住远程打开通道：记录 machine/port 与远程四开关构造窗内的 settings 态。"""
    from ansys.aedt.core.generic.settings import settings as aedt_settings

    from rfauto.adapters import hfss_session

    seen: dict = {}
    grpc_before = aedt_settings.grpc_local
    rpc_before = aedt_settings.remote_rpc_session

    class _FakeHfssRemote:
        design_name = "Design1"
        variable_manager = _VarManager()
        setups: ClassVar[list] = []
        boundaries: ClassVar[list] = []
        parametrics: ClassVar[list] = []

        def __init__(self, **kwargs):
            seen["ctor"] = kwargs
            # 构造窗内：远程四开关生效（grpc_local=False）+ Hfss 前置
            # remote_rpc_session=None（开发注记 五百四十二坑 1）。
            seen["grpc_local_in_window"] = aedt_settings.grpc_local
            seen["rpc_in_window"] = aedt_settings.remote_rpc_session

        def autosave_disable(self):
            return None

        def release_desktop(self, **kwargs):
            return True

    monkeypatch.setattr(hfss_session, "remote_session_switches",
                        hfss_session.remote_session_switches)  # 走真 CM
    import ansys.aedt.core as aedt_core

    monkeypatch.setattr(aedt_core, "Hfss", _FakeHfssRemote)
    seen["grpc_before"] = grpc_before
    seen["rpc_before"] = rpc_before
    seen["aedt_settings"] = aedt_settings
    return seen


def test_import_spec_remote_machine_passthrough(tmp_path, remote_registry,
                                                remote_open_spy):
    """remote_machine=注册表名 → Hfss(machine=,port=) 透传 + 服务器侧路径语义。"""
    remote_path = "E:/rfauto_remote/proj/remote.aedt"  # 本地不存在=服务器侧路径
    spec = hfss_import.import_project_spec(remote_path, version="2025.1",
                                           remote_machine="sim_server")

    assert spec["ok"], spec.get("error")
    assert remote_open_spy["ctor"]["machine"] == "10.20.30.40"
    assert remote_open_spy["ctor"]["port"] == 15555
    # 服务器侧路径语义：本地不存在不被拒（本地存在性检查跳过）
    assert spec["project"] == remote_path
    assert spec["remote"]["name"] == "sim_server"
    assert spec["remote"]["port"] == 15555
    # 构造窗四开关（hfss_session 同款）与 Hfss 前置 None
    assert remote_open_spy["grpc_local_in_window"] is False
    assert remote_open_spy["rpc_in_window"] is None
    # CM 退出恢复原值
    s = remote_open_spy["aedt_settings"]
    assert s.grpc_local == remote_open_spy["grpc_before"]
    assert s.remote_rpc_session == remote_open_spy["rpc_before"]


def test_import_spec_remote_version_mismatch_fails_closed(monkeypatch, tmp_path,
                                                          remote_registry):
    """版本配对断言（内核立规注记 规则 0）：settings 与注册表失配显式拒绝，不打开。"""
    opened: list = []
    monkeypatch.setattr(hfss_import, "_open_hfss",
                        lambda *a, **kw: opened.append(1) or _FakeHfss())

    spec = hfss_import.import_project_spec("E:/x/whatever.aedt",
                                           version="2023.1",
                                           remote_machine="sim_server")

    assert spec["ok"] is False
    assert "版本配对失配" in spec["error"]
    assert "2025.1" in spec["error"] and "2023.1" in spec["error"]
    assert not opened  # fail-closed：拒绝发生在任何 AEDT 构造之前


def test_import_spec_unknown_machine_fails_cleanly(monkeypatch):
    """未登记机器名：RemoteConfigError → ok=False 信封（不裸抛）。"""
    from rfauto.infra.remote_machines import RemoteConfigError

    def _raise(name=None, machines=None):
        raise RemoteConfigError(f"远程机器 {name!r} 未登记", details={})

    from rfauto.infra import remote_machines as rm

    monkeypatch.setattr(rm, "resolve_machine", _raise)
    spec = hfss_import.import_project_spec("E:/x/nope.aedt", version="2025.1",
                                           remote_machine="ghost")
    assert spec["ok"] is False
    assert "远程会话解析失败" in spec["error"]


def test_import_spec_without_remote_key_local_unchanged(mock_open, tmp_path):
    """无 remote_machine 键=本地会话：本地存在性检查仍在、无 machine/port。"""
    project = tmp_path / "fake.aedt"
    project.write_text("", encoding="utf-8")
    spec = hfss_import.import_project_spec(str(project))
    assert spec["ok"] and "remote" not in spec
    missing = hfss_import.import_project_spec("Z:/no_such.aedt")
    assert missing["ok"] is False and "不存在" in missing["error"]


def test_readonly_remote_skips_local_copy(tmp_path, remote_registry,
                                          remote_open_spy):
    """只读链远程分支：不做本地临时副本（服务器侧路径直通）、带 remote 块。"""
    remote_path = "E:/rfauto_remote/proj/remote2.aedt"
    spec = hfss_import.import_project_spec_readonly(
        remote_path, version="2025.1", timeout_s=10.0,
        remote_machine="sim_server")

    assert spec["ok"], spec.get("error")
    assert spec["project"] == str(Path(remote_path))
    assert spec["read_only_copy"] is False  # 无本地副本（服务器侧路径语义）
    assert spec["source_locked"] is False   # 本地 .lock 检查跳过
    assert spec["remote"]["machine"] == "10.20.30.40"
    # 打开的是原路径直通（不是本地 temp 副本）
    assert remote_open_spy["ctor"]["machine"] == "10.20.30.40"
    assert str(remote_open_spy["ctor"].get("project")) == str(Path(remote_path))
    assert "rfauto_hfss_import_" not in str(remote_open_spy["ctor"]["project"])


def test_readonly_local_mode_keeps_copy_semantics(mock_readonly, tmp_path):
    """本地模式回归钉：仍走临时副本 + read_only_copy=True（零行为变化）。"""
    project = tmp_path / "local.aedt"
    project.write_text("", encoding="utf-8")
    spec = hfss_import.import_project_spec_readonly(str(project),
                                                    version="2025.1")
    assert spec["ok"] and spec["read_only_copy"] is True
    assert "remote" not in spec
    assert mock_readonly["path"] != str(project)  # 副本


def test_import_recipe_remote_passthrough(tmp_path, remote_registry,
                                          remote_open_spy):
    """端到端链：import_project_recipe 把 remote_machine 传进只读导入。"""
    result = hfss_import.import_project_recipe(
        "E:/rfauto_remote/proj/remote3.aedt", version="2025.1",
        remote_machine="sim_server")

    assert result["ok"], result.get("error")
    assert result["spec"]["remote"]["name"] == "sim_server"
    assert remote_open_spy["ctor"]["port"] == 15555


def test_open_hfss_local_window_has_no_remote_kwargs(monkeypatch):
    """本地构造窗：_open_hfss 不带 machine/port（Desktop 本地口径零变化）。"""
    import ansys.aedt.core as aedt_core

    seen: dict = {}

    class _FakeLocal:
        def __init__(self, **kwargs):
            seen["ctor"] = kwargs

    monkeypatch.setattr(aedt_core, "Hfss", _FakeLocal)
    hfss_import._open_hfss("p.aedt", None, "2023.1", True)
    assert "machine" not in seen["ctor"] and "port" not in seen["ctor"]


# ─── aurora72 A7-C：AEDT 缺省版本钉单源统一（edb_adapter._DEFAULT_AEDT_VERSION）─
# 真机口径 2025 R1/v251（内核立规注记 规则 0 勘误）；改前 hfss_import 缺省误钉
# "2023.1"、v3_services.hfss_import_recipe 误钉 "2026.1"——统一引用单源后
# 此处钉"缺省值==单源常量==2025.1"同值断言，防四处字面量再漂移。

class TestAedtVersionDefaultPins:
    def test_single_source_constant_is_real_machine_version(self):
        from rfauto.adapters.edb_adapter import _DEFAULT_AEDT_VERSION

        assert _DEFAULT_AEDT_VERSION == "2025.1"

    def test_import_spec_default_references_single_source(self):
        from rfauto.adapters.edb_adapter import _DEFAULT_AEDT_VERSION

        default = inspect.signature(
            hfss_import.import_project_spec).parameters["version"].default
        assert default == _DEFAULT_AEDT_VERSION

    def test_v3_recipe_default_references_single_source(self):
        from rfauto.adapters.edb_adapter import _DEFAULT_AEDT_VERSION
        from rfauto.service.v3_services import hfss_import_recipe

        default = inspect.signature(
            hfss_import_recipe).parameters["version"].default
        assert default == _DEFAULT_AEDT_VERSION

    def test_resolve_fallback_uses_single_source(self, monkeypatch):
        # 探测失败兜底=单源缺省（禁回退硬编码旧值 2023.1）
        from rfauto.infra import version_probe

        def _boom():
            raise RuntimeError("probe disabled (A7-C pin)")

        monkeypatch.setattr(version_probe, "resolve_aedt_install", _boom)
        assert hfss_import._resolve_aedt_version(None) == "2025.1"
