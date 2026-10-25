"""INTEG-B 席跨模块集成测试：pyedb OpenSSL 预载链三态全链（aurora_d INTEG-B，2026-10-14）.

链条（真实 preload_ansys_openssl——与 test_pyedb_preload 的替身桩不同，
本文件只替 ctypes 边缝，resolver/登记表/信封全真）：

    env ``RFAUTO_PYEDB_PRELOAD`` / 构造参数 ``enable_preload``（三态开关）
      → EdbAdapter._load_pyedb_cls（edb_adapter 消费点）
        → pyedb_preload.preload_ansys_openssl（root 解析三档：显式>env>
          configs；AnsysEM/Win64 布局变体探测）
          → ctypes 边缝（monkeypatch 替身，零真 DLL 零真进程，#139）
            → 幂等登记表 _LOADED / last_result 信封
      → import pyedb（假包注入）→ Edb 类 → build() 全链

三态全覆盖：关（env 未设=零预载零行为）、开（env truthy/configs 档=预载
先行、信封 ok=True、幂等 already）、显式 False 压过 env。错误路径：root
落空/WinDLL OSError 均 fail-soft（信封 ok=False 不抛、build 主链照常
走通——#105 预载失败自会由后续 import pyedb 暴露）。顺序钉：DLL 预载
先于 import pyedb（#373 R5 配方语义，先到先得）。

既有单测分工：test_pyedb_preload 钉 helper 单元与替身桩级 flag 三态——
本文件补「真 resolver 经 adapter 消费点打穿到 import 面」的跨模块链。
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from rfauto.adapters import pyedb_preload as pp
from rfauto.adapters.edb_adapter import EdbAdapter

_DLLS = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")

_MIN_SPEC = {"stackup": {"layers": [
    {"name": "L", "type": "signal", "thickness_mm": 0.035}]}}


def _make_root(tmp_path: Path, layout: str = "flat") -> Path:
    """含两个假 DLL 文件的 AnsysEM 假根（零真 DLL；flat/AnsysEM/Win64 三布局）。"""
    root = {"flat": tmp_path / "root",
            "ansysem": tmp_path / "root" / "AnsysEM",
            "win64": tmp_path / "root" / "Win64"}[layout]
    root.mkdir(parents=True, exist_ok=True)
    for dll in _DLLS:
        (root / dll).write_bytes(b"fake dll bytes")
    return root


@pytest.fixture()
def dll_calls() -> list[str]:
    return []


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, dll_calls: list[str]):
    """env 整集合清空 + ctypes 边缝替身 + 登记表隔离（同前缀整集合纪律）。"""
    monkeypatch.delenv("ANSYSEM_ROOT251", raising=False)
    monkeypatch.delenv("RFAUTO_PYEDB_PRELOAD", raising=False)
    monkeypatch.setattr(pp, "_configs_aedt_path", lambda: "")
    monkeypatch.setattr(pp, "_win_dll",
                        lambda p: dll_calls.append(str(p)))
    monkeypatch.setattr(pp, "_file_version", lambda p: "3.0.14-teststub")
    pp.reset_loaded_registry()
    yield
    pp.reset_loaded_registry()


def _install_fake_pyedb(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    fake = types.ModuleType("pyedb")

    class _FakeCfg:
        def load(self, config_file, append=True, apply_file=False, **kw):
            return None

    class _FakeEdb:
        def __init__(self, **kw):
            self.configuration = _FakeCfg()

        def save_edb(self) -> bool:
            return True

        def close_edb(self) -> bool:
            return True

    fake.Edb = _FakeEdb
    monkeypatch.setitem(sys.modules, "pyedb", fake)
    return fake


# ────────────────────────── 三态开关全链 ──────────────────────────


class TestThreeStates:
    def test_state_closed_env_unset_zero_behavior(
            self, tmp_path, monkeypatch, dll_calls):
        _install_fake_pyedb(monkeypatch)
        cls = EdbAdapter(tmp_path)._load_pyedb_cls()
        assert cls is not None
        assert dll_calls == []  # 关闭态零 DLL 触碰
        assert pp.last_result is None  # 预载面整体未运行
        assert not pp._LOADED

    def test_state_open_env_chain_loads_both_dlls(
            self, tmp_path, monkeypatch, dll_calls):
        root = _make_root(tmp_path, "flat")
        monkeypatch.setenv("ANSYSEM_ROOT251", str(root))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        _install_fake_pyedb(monkeypatch)
        cls = EdbAdapter(tmp_path)._load_pyedb_cls()  # 构造参数 None=读 env
        assert cls is not None
        # 预载真跑：两 DLL 按配方序（crypto 先）绝对路径加载
        assert dll_calls == [str(root / dll) for dll in _DLLS]
        env = pp.last_result
        assert env["ok"] is True
        assert env["source"] == "env"
        assert env["root"] == str(root)
        assert [d["name"] for d in env["dlls"]] == list(_DLLS)
        assert all(d["loaded"] and not d["already"] for d in env["dlls"])
        assert env["dlls"][0]["version"] == "3.0.14-teststub"
        assert set(pp._LOADED) == set(_DLLS)  # 幂等登记表已入账

    def test_state_open_idempotent_across_adapter_instances(
            self, tmp_path, monkeypatch, dll_calls):
        root = _make_root(tmp_path, "flat")
        monkeypatch.setenv("ANSYSEM_ROOT251", str(root))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        _install_fake_pyedb(monkeypatch)
        EdbAdapter(tmp_path / "w1")._load_pyedb_cls()
        EdbAdapter(tmp_path / "w2")._load_pyedb_cls()  # 第二个 adapter 再走链
        assert dll_calls == [str(root / dll) for dll in _DLLS]  # 不重复加载
        env = pp.last_result
        assert env["ok"] is True
        assert all(d["already"] and not d["loaded"] for d in env["dlls"])

    def test_state_param_false_overrides_truthy_env(
            self, tmp_path, monkeypatch, dll_calls):
        """显式 False 压过 truthy env——走 build() 真消费链（构造 flag 经
        self._enable_preload 只在 build/solve 内部转发点生效；裸调
        _load_pyedb_cls() 无参形态读 env，非 adapter 消费路径）。"""
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        monkeypatch.setenv("ANSYSEM_ROOT251", str(_make_root(tmp_path)))
        _install_fake_pyedb(monkeypatch)
        result = EdbAdapter(tmp_path, enable_preload=False).build(
            dict(_MIN_SPEC))
        assert result.config_json_path.exists()  # 主链照常走通
        assert dll_calls == [] and pp.last_result is None

    def test_state_open_via_configs_tier(
            self, tmp_path, monkeypatch, dll_calls):
        """configs 档：env 缺席时经 settings aedt_path 派生（缝=_configs_aedt_path）。"""
        root = _make_root(tmp_path, "ansysem")
        monkeypatch.setattr(pp, "_configs_aedt_path", lambda: str(root.parent))
        _install_fake_pyedb(monkeypatch)
        # build() 真消费链：构造参数 True 经 _enable_preload 转发到预载
        EdbAdapter(tmp_path, enable_preload=True).build(dict(_MIN_SPEC))
        assert dll_calls == [str(root / dll) for dll in _DLLS]
        assert pp.last_result["source"] == "configs"
        assert pp.last_result["root"] == str(root)  # AnsysEM 子目录布局变体

    def test_env_parent_layout_variant_resolved(
            self, tmp_path, monkeypatch, dll_calls):
        """env 钉在父目录（安装器形态之一）：AnsysEM/Win64 子目录探测命中。"""
        root = _make_root(tmp_path, "win64")
        monkeypatch.setenv("ANSYSEM_ROOT251", str(root.parent))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        _install_fake_pyedb(monkeypatch)
        EdbAdapter(tmp_path)._load_pyedb_cls()
        assert dll_calls == [str(root / dll) for dll in _DLLS]
        assert pp.last_result["root"] == str(root)


# ────────────────────────── 错误路径：fail-soft 不阻塞主链 ──────────────────────────


class TestFailSoft:
    def test_env_root_without_dlls_still_imports(
            self, tmp_path, monkeypatch, dll_calls):
        empty = tmp_path / "empty_root"
        empty.mkdir()
        monkeypatch.setenv("ANSYSEM_ROOT251", str(empty))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        _install_fake_pyedb(monkeypatch)
        cls = EdbAdapter(tmp_path)._load_pyedb_cls()  # 不抛
        assert cls is not None
        env = pp.last_result
        assert env["ok"] is False
        assert dll_calls == []  # 未触加载
        for dll in _DLLS:
            assert dll in env["reason"]
        assert env["tried"]  # 诊断面：候选路径已列

    def test_build_chain_survives_preload_failure(
            self, tmp_path, monkeypatch, dll_calls):
        """#105 主链：预载失败不阻断 build（config 落盘+Edb 全调用面照常）。"""
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        monkeypatch.setenv("ANSYSEM_ROOT251", str(tmp_path / "nowhere"))
        _install_fake_pyedb(monkeypatch)
        adapter = EdbAdapter(tmp_path)
        result = adapter.build(dict(_MIN_SPEC))  # 不抛
        assert result.config_json_path.exists()
        assert pp.last_result["ok"] is False  # 失败如实落在信封
        assert dll_calls == []

    def test_win_dll_oserror_fail_soft(
            self, tmp_path, monkeypatch, dll_calls):
        def _boom(p):
            raise OSError("返回错误 193（位数不符形态）")

        monkeypatch.setattr(pp, "_win_dll", _boom)
        monkeypatch.setenv("ANSYSEM_ROOT251", str(_make_root(tmp_path)))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        _install_fake_pyedb(monkeypatch)
        cls = EdbAdapter(tmp_path)._load_pyedb_cls()  # OSError 被吞
        assert cls is not None
        env = pp.last_result
        assert env["ok"] is False
        assert "OSError" in env["reason"]
        assert not pp._LOADED  # 失败不入幂等登记表（下次可重试）


# ────────────────────────── 顺序钉：预载先于 import ──────────────────────────


class TestOrdering:
    def test_preload_precedes_pyedb_import_real_chain(
            self, tmp_path, monkeypatch, dll_calls):
        """真预载链（非替身桩）：DLL 加载事件先于 import pyedb 事件。"""
        events: list[str] = []

        class _Loader(importlib.abc.Loader):
            def create_module(self, spec):
                mod = types.ModuleType("pyedb")

                class _Edb:
                    def __init__(self, **kw):
                        pass

                mod.Edb = _Edb
                return mod

            def exec_module(self, module):
                pass

        class _Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pyedb":
                    events.append("import_pyedb")
                    return importlib.util.spec_from_loader("pyedb", _Loader())
                return None

        monkeypatch.setattr(sys, "meta_path", [_Finder(), *sys.meta_path])
        monkeypatch.setenv("ANSYSEM_ROOT251", str(_make_root(tmp_path)))
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        sys.modules.pop("pyedb", None)
        try:
            EdbAdapter(tmp_path)._load_pyedb_cls()
        finally:
            sys.modules.pop("pyedb", None)  # 防 loader 产物泄漏他测
        assert events == ["import_pyedb"]
        assert len(dll_calls) == 2  # 两 DLL 已先加载（先到先得配方语义）
        assert pp.last_result["ok"] is True
