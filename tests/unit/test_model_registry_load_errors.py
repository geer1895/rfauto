"""F4/F5：models.registry 结构化 load_errors 可观测性测试。

不依赖真实坏插件：通过 monkeypatch 注入抛 ImportError 的伪 importer 与
伪 entry-point，断言三个失败点（内置插件 ImportError / entry-point 单插件
失败 / entry-point 组枚举失败）都追加结构化 load_errors 条目，且注册表
主功能（get/list_models）不受影响。

#362 铁律：禁止 importlib.reload(registry)——状态隔离用快照/还原
（_registry 内容、load_errors 内容、_plugins_loaded 标志），finally 还原。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from rfauto.models import registry as reg

_BUILTIN_MODULES = (
    "rfauto.models.wilkinson_power_divider.plugin",
    "rfauto.models.branchline_coupler.plugin",
    "rfauto.models.patch_antenna.plugin",
    "rfauto.models.mline.plugin",
)


@pytest.fixture()
def fresh_registry_state():
    """快照注册表三件可变状态并重置，teardown 还原（不 reload，#362）。

    注意不清空 _registry：sys.modules 已缓存的插件模块重新 import 是
    no-op（模块体不重执行、@register 不重跑），清空后靠真实环境无法
    复位——快照/还原能保证既有注册内容零丢失。
    """
    saved_registry = dict(reg._registry)
    saved_errors = list(reg.load_errors)
    saved_flag = reg._plugins_loaded
    reg.load_errors.clear()
    reg._plugins_loaded = False
    yield reg
    reg._registry.clear()
    reg._registry.update(saved_registry)
    reg.load_errors.clear()
    reg.load_errors.extend(saved_errors)
    reg._plugins_loaded = saved_flag


class TestBuiltinImportFailure:
    """失败点 1：内置插件 ImportError（原 contextlib.suppress 静默跳过）。"""

    def test_import_error_recorded_and_other_models_intact(
            self, fresh_registry_state, monkeypatch):
        real_import_module = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "rfauto.models.mline.plugin":
                raise ImportError(f"simulated missing: {name}")
            return real_import_module(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        fresh_registry_state._ensure_plugins_loaded()

        builtin_entries = [
            e for e in fresh_registry_state.load_errors
            if e.startswith("builtin=rfauto.models.mline.plugin: ImportError:")
        ]
        assert len(builtin_entries) == 1
        assert "simulated missing" in builtin_entries[0]

        # 主功能不受影响：其余内置模型照常可取
        models = fresh_registry_state.list_models()
        for expected in ("wilkinson_power_divider", "branchline_coupler",
                         "patch_antenna"):
            assert expected in models
        assert fresh_registry_state.get(
            "wilkinson_power_divider").name == "wilkinson_power_divider"


class TestEntryPointPluginFailure:
    """失败点 2：entry-point 单插件 load 失败（原仅 logger.warning）。"""

    def test_load_failure_recorded_and_good_plugin_registered(
            self, fresh_registry_state, monkeypatch):
        def _boom():
            raise RuntimeError("boom")

        class GoodPlugin:
            name = "good_plugin"

        fake_eps = [
            SimpleNamespace(name="bad_plugin", load=_boom),
            SimpleNamespace(name="good_plugin", load=lambda: GoodPlugin),
        ]
        monkeypatch.setattr(
            "importlib.metadata.entry_points", lambda group=None, **kw: fake_eps)

        fresh_registry_state._discover_entry_points()

        assert ("entry_point=bad_plugin: RuntimeError: boom"
                in fresh_registry_state.load_errors)
        # 好插件照常注册（单点失败不传染）
        assert fresh_registry_state._registry.get("good_plugin") is GoodPlugin
        # 好插件不产生失败条目
        assert not [e for e in fresh_registry_state.load_errors
                    if "good_plugin" in e]


class TestEntryPointGroupEnumerationFailure:
    """失败点 3：entry-point 组枚举失败（原裸吞置空）。"""

    def test_enumeration_failure_recorded_no_crash(
            self, fresh_registry_state, monkeypatch):
        def _raise(**kwargs):
            raise RuntimeError("enum boom")

        monkeypatch.setattr("importlib.metadata.entry_points", _raise)
        # 不抛错（照旧置空继续，零控制流变化）
        fresh_registry_state._discover_entry_points()
        assert ("entry_point_group=rfauto.models: RuntimeError: enum boom"
                in fresh_registry_state.load_errors)


class TestImportBuiltinHelper:
    """_import_builtin 独立 helper：坏模块名跳过并记账，不抛错。"""

    def test_bogus_module_recorded_and_skipped(self, fresh_registry_state):
        bogus = "rfauto.models.__no_such_plugin_for_test__"
        fresh_registry_state._import_builtin(bogus)
        entries = [e for e in fresh_registry_state.load_errors
                   if e.startswith(f"builtin={bogus}: ImportError:")]
        assert len(entries) == 1


class TestCleanLoad:
    """正常环境：干净加载零失败条目，主功能完好。"""

    def test_clean_load_no_errors_all_builtins_registered(
            self, fresh_registry_state):
        fresh_registry_state._ensure_plugins_loaded()
        assert fresh_registry_state.load_errors == []
        models = fresh_registry_state.list_models()
        for name in ("wilkinson_power_divider", "branchline_coupler",
                     "patch_antenna", "mline"):
            assert name in models


class TestDuplicateRegistration:
    """S-1 C-03 2026-10-04：重名注册防护（对照 TemplateSpecRegistry ValueError
    惯例）——同名**不同类**显式拒绝；同名**同一类**幂等直通（builtin import
    与 pyproject entry-point 对同一插件的双路径注册合法形态）。"""

    def test_same_class_reregistration_idempotent(self, fresh_registry_state):
        class Plugin:
            name = "dup_idempotent"

        reg.register(Plugin)
        reg.register(Plugin)          # entry-point 二次注册同对象 → no-op
        assert fresh_registry_state.get("dup_idempotent") is Plugin
        assert fresh_registry_state.load_errors == []

    def test_different_class_same_name_rejected(self, fresh_registry_state):
        class First:
            name = "dup_conflict"

        class Second:                # 同名不同类：静默覆盖=劫持既有调用方
            name = "dup_conflict"

        reg.register(First)
        with pytest.raises(ValueError, match="重名注册"):
            reg.register(Second)
        assert fresh_registry_state.get("dup_conflict") is First, \
            "拒绝后旧注册保持原绑定"
