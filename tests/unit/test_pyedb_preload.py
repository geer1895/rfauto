"""pyedb 预载 helper + edb_adapter 预载 feature-flag 单元测试（#373 回归席）。

零真机零 pyedb 真调：helper 的 WinDLL/版本探测/configs 读全走测试缝
（monkeypatch 模块级函数）；feature-flag 态用假 pyedb 假包注入
（test_edb_adapter::_install_fake_pyedb 同款纪律）。本文件对真
AnsysEM/真 pyedb 零依赖（裸环境同样全绿），不触任何真 DLL 加载。
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

from rfauto.adapters import pyedb_preload as pp
from rfauto.adapters.edb_adapter import EdbAdapter
from rfauto.adapters.pyedb_preload import preload_ansys_openssl

_DLLS = ("libcrypto-3-x64.dll", "libssl-3-x64.dll")

#: 真函数存根（autouse fixture 替换模块属性前抓原装——best-effort 用例
#: 要测真实现而非替身）
_REAL_FILE_VERSION = pp._file_version


def _make_root(tmp_path: Path, layout: str = "flat") -> Path:
    """造含两个假 DLL 文件的 AnsysEM 假根目录（零真 DLL）。"""
    root = tmp_path / ("AnsysEM" if layout != "flat" else "root")
    if layout == "win64":
        root = tmp_path / "root" / "Win64"
    root.mkdir(parents=True, exist_ok=True)
    for dll in _DLLS:
        (root / dll).write_bytes(b"fake")
    return root


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    """环境与进程内登记隔离（机器可能设了真 env——同前缀整集合清空纪律）。

    configs 档默认钉空 + WinDLL/版本探测默认替身（个别用例自行覆盖为
    记录/炸桩），保证解析与加载全程确定、零真 DLL 触碰。
    """
    monkeypatch.delenv("ANSYSEM_ROOT251", raising=False)
    monkeypatch.delenv("RFAUTO_PYEDB_PRELOAD", raising=False)
    monkeypatch.setattr(pp, "_configs_aedt_path", lambda: "")
    monkeypatch.setattr(pp, "_win_dll", lambda p: object())
    monkeypatch.setattr(pp, "_file_version", lambda p: "0.0.0-teststub")
    pp.reset_loaded_registry()
    yield
    pp.reset_loaded_registry()


# ─── helper：解析链 / 信封 / 幂等 / fail-soft ───────────────────────────────


class TestPreloadHelper:
    def test_ok_explicit_root_envelope(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        calls: list[str] = []
        monkeypatch.setattr(pp, "_win_dll",
                            lambda p: calls.append(p) or object())
        monkeypatch.setattr(pp, "_file_version", lambda p: "3.0.14")
        env = preload_ansys_openssl(root)
        assert env["ok"] is True and env["reason"] == ""
        assert env["source"] == "explicit"
        assert env["root"] == str(root)
        assert [d["name"] for d in env["dlls"]] == list(_DLLS)  # 配方序
        assert all(d["loaded"] and not d["already"] for d in env["dlls"])
        assert all(d["version"] == "3.0.14" for d in env["dlls"])
        # 绝对路径形态（配方核心：按绝对路径加载）
        assert calls == [str(root / d) for d in _DLLS]
        assert all(os.path.isabs(p) for p in calls)

    def test_idempotent_second_call_no_reload(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        calls: list[str] = []
        monkeypatch.setattr(pp, "_win_dll",
                            lambda p: calls.append(p) or object())
        first = preload_ansys_openssl(root)
        assert first["ok"] is True
        second = preload_ansys_openssl(str(root))
        assert second["ok"] is True
        assert [d["already"] for d in second["dlls"]] == [True, True]
        assert all(not d["loaded"] for d in second["dlls"])
        assert len(calls) == 2  # 幂等：二次调用零新加载

    def test_env_resolution(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)
        monkeypatch.setenv("ANSYSEM_ROOT251", str(root))
        env = preload_ansys_openssl()
        assert env["ok"] is True and env["source"] == "env"
        assert env["root"] == str(root)

    def test_configs_fallback(self, tmp_path, monkeypatch):
        parent = tmp_path / "v251"
        root = _make_root(parent, layout="ansys")  # parent/AnsysEM/DLLs
        monkeypatch.setattr(pp, "_configs_aedt_path", lambda: str(parent))
        env = preload_ansys_openssl()
        assert env["ok"] is True and env["source"] == "configs"
        assert env["root"] == str(root)

    def test_win64_layout_variant(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path, layout="win64")
        env = preload_ansys_openssl(tmp_path / "root")
        assert env["ok"] is True and env["root"] == str(root)

    def test_env_missing_fail_soft(self, monkeypatch):
        # env 已被 autouse 清空 + configs 钉空：解析链全空 → ok=False 不抛
        env = preload_ansys_openssl()
        assert env["ok"] is False
        assert env["reason"]
        assert env["root"] is None and env["source"] == ""

    def test_dll_missing_fail_soft(self, tmp_path):
        lonely = tmp_path / "root"
        lonely.mkdir()
        (lonely / _DLLS[0]).write_bytes(b"fake")  # 只有一个 DLL → 不算命中
        env = preload_ansys_openssl(lonely)
        assert env["ok"] is False and env["reason"]
        assert env["root"] is None
        assert env["tried"]  # 诊断面：尝试过的候选在档

    def test_windll_oserror_fail_soft(self, tmp_path, monkeypatch):
        root = _make_root(tmp_path)

        def _boom(p):
            raise OSError("boom")

        monkeypatch.setattr(pp, "_win_dll", _boom)
        env = preload_ansys_openssl(root)
        assert env["ok"] is False
        assert "OSError" in env["reason"] and "boom" in env["reason"]

    def test_non_windows_fail_soft(self, monkeypatch):
        monkeypatch.delattr(pp.ctypes, "WinDLL")
        env = preload_ansys_openssl("E:/nowhere")
        assert env["ok"] is False
        assert "Windows" in env["reason"]

    def test_relative_explicit_resolves_absolute(self, tmp_path,
                                                 monkeypatch):
        _make_root(tmp_path)
        monkeypatch.chdir(tmp_path)
        env = preload_ansys_openssl("root")
        assert env["ok"] is True
        assert os.path.isabs(env["root"])
        assert all(os.path.isabs(d["path"]) for d in env["dlls"])

    @pytest.mark.skipif(os.name != "nt", reason="Win32 Version API")
    def test_file_version_best_effort_empty(self, tmp_path):
        # 无版本信息文件 → ""（best-effort 不抛，#105；测真实现）
        f = tmp_path / "noversion.bin"
        f.write_bytes(b"x")
        assert _REAL_FILE_VERSION(str(f)) == ""

    def test_last_result_stub(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pp, "_win_dll", lambda p: object())
        preload_ansys_openssl(_make_root(tmp_path))
        assert pp.last_result is not None and pp.last_result["ok"] is True


# ─── feature-flag：关闭态零行为 / 开启态预载先行 ─────────────────────────────


class _FakeCfg:
    def __init__(self, calls: list):
        self._calls = calls

    def load(self, config_file, append=True, apply_file=False, **kw):
        self._calls.append(("load",))
        return None


class _FakeEdb:
    def __init__(self, calls: list, **kw):
        calls.append(("Edb", kw))
        self.configuration = _FakeCfg(calls)
        self._calls = calls

    def save_edb(self) -> bool:
        self._calls.append(("save",))
        return True

    def close_edb(self) -> bool:
        self._calls.append(("close",))
        return True


def _install_fake_pyedb(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    fake = types.ModuleType("pyedb")
    fake.Edb = lambda **kw: _FakeEdb(calls, **kw)
    monkeypatch.setitem(sys.modules, "pyedb", fake)


def _install_preload_stub(monkeypatch: pytest.MonkeyPatch,
                          events: list) -> None:
    """假 pyedb_preload 模块（记录调用；替身命中 adapter 惰性 import）。"""
    mod = types.ModuleType("rfauto.adapters.pyedb_preload")
    mod.preload_ansys_openssl = lambda *a, **kw: events.append("preload")
    monkeypatch.setitem(sys.modules, "rfauto.adapters.pyedb_preload", mod)


_MIN_SPEC = {"stackup": {"layers": [
    {"name": "L", "type": "signal", "thickness_mm": 0.035}]}}


class TestFeatureFlag:
    def test_closed_zero_behavior_no_preload(self, tmp_path, monkeypatch):
        # 毒桩：关闭态若误触预载路径即炸（含 import 面）
        poison = types.ModuleType("rfauto.adapters.pyedb_preload")

        def _must_not_run(*a, **kw):
            raise AssertionError("flag 关闭态不得触预载路径")

        poison.preload_ansys_openssl = _must_not_run
        monkeypatch.setitem(sys.modules,
                            "rfauto.adapters.pyedb_preload", poison)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        cls = EdbAdapter(tmp_path)._load_pyedb_cls()
        assert cls is not None and calls == []  # 关闭态：零预载零真调

    def test_closed_build_zero_behavior(self, tmp_path, monkeypatch):
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        result = EdbAdapter(tmp_path).build(dict(_MIN_SPEC))
        assert events == []  # env 未开 → build 链零预载
        assert calls[0][0] == "Edb" and calls[-1] == ("close",)
        assert result.config_json_path.exists()  # 存证面照常落盘

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on"])
    def test_open_env_truthy_variants(self, tmp_path, monkeypatch, raw):
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", raw)
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        EdbAdapter(tmp_path)._load_pyedb_cls()
        assert events == ["preload"]

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "bogus"])
    def test_env_falsy_or_unknown_stays_closed(self, tmp_path,
                                               monkeypatch, raw):
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", raw)
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        EdbAdapter(tmp_path)._load_pyedb_cls()
        assert events == []

    def test_param_true_without_env(self, tmp_path, monkeypatch):
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        result = EdbAdapter(tmp_path, enable_preload=True).build(
            dict(_MIN_SPEC))
        assert events == ["preload"]  # 参数显式开启（env 未设）
        assert calls[0][0] == "Edb"
        assert result.config_json_path.exists()

    def test_param_false_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        EdbAdapter(tmp_path, enable_preload=False).build(dict(_MIN_SPEC))
        assert events == []  # 显式 False 优先于 env

    def test_open_env_build_propagates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        events: list = []
        _install_preload_stub(monkeypatch, events)
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        EdbAdapter(tmp_path).build(dict(_MIN_SPEC))
        assert events == ["preload"]  # 构造 None → env → build 调用点传播
        assert calls[0][0] == "Edb"

    def test_preload_precedes_pyedb_import(self, tmp_path, monkeypatch):
        """顺序钉：预载先于 import pyedb（#373 配方语义——先到先得）。"""
        events: list = []
        _install_preload_stub(monkeypatch, events)

        class _Loader(importlib.abc.Loader):
            def create_module(self, spec):
                mod = types.ModuleType("pyedb")
                mod.Edb = lambda **kw: None
                return mod

            def exec_module(self, module):
                pass

        class _Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pyedb":
                    events.append("import_pyedb")
                    return importlib.util.spec_from_loader(
                        "pyedb", _Loader())
                return None

        # 挂到 meta_path 最前：本机主 venv 可能装有真 pyedb——替身必须
        # 抢在 PathFinder 之前命中，测试进程零真包触碰
        monkeypatch.setattr(sys, "meta_path",
                            [_Finder(), *sys.meta_path])
        monkeypatch.setenv("RFAUTO_PYEDB_PRELOAD", "1")
        sys.modules.pop("pyedb", None)
        try:
            EdbAdapter(tmp_path)._load_pyedb_cls()
            assert events == ["preload", "import_pyedb"]
        finally:
            sys.modules.pop("pyedb", None)  # 防 loader 产物泄漏他测
