"""DP-17 O1 单测——em_solver_base 第三方适配器 entry-point 发现口。

判据（runs/df6_dp17/criteria.md §O1）：
- monkeypatch importlib.metadata.entry_points 伪造 rfauto.adapters 组 →
  ensure_adapter_plugins_loaded() 后注册表含伪插件（不依赖真实安装；
  pyproject 段本批不加，由主代理合入）；
- 单个 entry-point 加载失败不传染既有注册表内容（warning 不抛）；
- 内置注册路径逐字节不变：发现前后内置键恒在；双检锁幂等（二次调用
  不重复发现）。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.adapters import em_solver_base
from rfauto.adapters.em_solver_base import (
    ensure_adapter_plugins_loaded,
    get_global_registry,
)

_BUILTIN_KEYS = {"comsol", "elmer", "meep", "ngsolve", "openems", "palace"}


def _make_stub_plugin_module(tmp_path: Path, key: str) -> types.ModuleType:
    """生成一个 import 即注册的伪适配器插件模块（真实第三方包形态）。"""
    name = f"_fake_ep_plugin_{key}"
    code = f'''
from rfauto.adapters.em_solver_base import (
    EMSolverAdapter, EMSolverConfig, EMSolverResult, get_global_registry)

SOLVER_TYPE = {key!r}


class {key}Adapter(EMSolverAdapter):
    param_semantics = {{}}

    def connect(self):
        self._connected = True
        return True

    def is_available(self):
        return True

    def build_geometry(self, geometry):
        return bool(self._connected)

    def solve(self):
        return EMSolverResult(success=False)

    def get_sparams(self):
        raise RuntimeError("stub")

    def close(self):
        self._connected = False


def register(registry=None):
    (registry if registry is not None
     else get_global_registry()).register(SOLVER_TYPE, {key}Adapter)


register()
'''
    path = tmp_path / f"{name}.py"
    path.write_text(code, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeEP:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


@pytest.fixture
def registry_guard():
    """注册表+发现标志快照/还原（#362 口径）。"""
    snap_solvers = dict(get_global_registry()._solvers)
    snap_flag = em_solver_base._adapter_plugins_loaded
    yield
    get_global_registry()._solvers = snap_solvers
    em_solver_base._adapter_plugins_loaded = snap_flag


def _patch_entry_points(monkeypatch, eps):
    import importlib.metadata as md

    def fake_entry_points(group=None):
        assert group == "rfauto.adapters"
        return list(eps)

    monkeypatch.setattr(md, "entry_points", fake_entry_points)


class TestAdapterEntryPointDiscovery:
    def test_discovery_registers_fake_plugin(self, tmp_path, monkeypatch,
                                             registry_guard):
        em_solver_base._adapter_plugins_loaded = False
        module = _make_stub_plugin_module(tmp_path, "stub_solver")
        _patch_entry_points(monkeypatch, [
            _FakeEP("stub_solver", lambda: module)])

        ensure_adapter_plugins_loaded()
        reg = get_global_registry()
        assert reg.is_registered("stub_solver")
        assert {
            getattr(k, "value", k) for k in reg.list_available()} >= _BUILTIN_KEYS, \
            "内置注册路径不得受发现影响"

        # 双检锁幂等：标志已置位，二次调用不再枚举
        em_solver_base._adapter_plugins_loaded = True
        ensure_adapter_plugins_loaded()  # 不触发 entry_points（标志短路）
        assert reg.is_registered("stub_solver")

    def test_single_plugin_failure_does_not_poison(self, tmp_path,
                                                   monkeypatch,
                                                   registry_guard):
        em_solver_base._adapter_plugins_loaded = False
        module = _make_stub_plugin_module(tmp_path, "stub_ok")

        def boom():
            raise ImportError("插件缺失（模拟坏包）")

        _patch_entry_points(monkeypatch, [
            _FakeEP("broken", boom),
            _FakeEP("stub_ok", lambda: module),
        ])
        ensure_adapter_plugins_loaded()
        reg = get_global_registry()
        assert reg.is_registered("stub_ok")
        assert not reg.is_registered("broken")
        assert {
            getattr(k, "value", k) for k in reg.list_available()} >= _BUILTIN_KEYS

    def test_discovery_no_entry_points_is_noop(self, monkeypatch,
                                               registry_guard):
        em_solver_base._adapter_plugins_loaded = False
        _patch_entry_points(monkeypatch, [])
        ensure_adapter_plugins_loaded()
        assert em_solver_base._adapter_plugins_loaded is True
        assert {
            getattr(k, "value", k) for k in get_global_registry().list_available()} >= _BUILTIN_KEYS

    def test_group_enum_failure_honest_no_raise(self, monkeypatch,
                                                registry_guard):
        import importlib.metadata as md

        em_solver_base._adapter_plugins_loaded = False

        def boom(**kwargs):
            raise RuntimeError("metadata 损坏")

        monkeypatch.setattr(md, "entry_points", boom)
        ensure_adapter_plugins_loaded()  # 不抛（warning 落日志）
        assert em_solver_base._adapter_plugins_loaded is True
