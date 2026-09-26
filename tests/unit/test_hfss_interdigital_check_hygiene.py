"""hfss_interdigital_check.py 异常路径卫生钉（round6 A3-⑥；全离线零 HFSS）。

覆盖两条 #265/#308 族教训的修复：
  1) Hfss() 构造入 try——构造半途失败（gRPC 通道级故障）也走统一 finally：
     solve_record.json 照常落盘（丢 ok 键=崩溃取证），不抛裸异常绕过释放；
  2) _build_and_solve 重试循环的 raise last_exc 有 None 兜底——循环体未
     执行时抛显式 RuntimeError 而非 `raise None` 的 TypeError（吞真因）。

被测脚本的 HFSS/ansys.aedt 依赖以假模块注入（monkeypatch sys.modules），
零真机、零 PowerShell 进程查（_assert_existing_desktops_none 一并 stub）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hfss_interdigital_check.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "_hfss_interdigital_check_hygiene", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load_mod()


def _install_fake_aedt(monkeypatch, hfss_init):
    """假 ansys.aedt.core 三级包注入（屏蔽真实 pyaedt 父包，零真机）。"""

    class _FakeHfss:
        def __init__(self, **kwargs):
            hfss_init(**kwargs)

    for name in ("ansys", "ansys.aedt", "ansys.aedt.core"):
        fake = types.ModuleType(name)
        fake.__path__ = []  # 标记为包
        monkeypatch.setitem(sys.modules, name, fake)
    sys.modules["ansys.aedt.core"].Hfss = _FakeHfss  # type: ignore[attr-defined]
    return _FakeHfss


def test_retry_loop_raises_last_exception_not_none(mod, monkeypatch, tmp_path):
    """重试循环穷尽后重抛末次真异常（兜底：last_exc=None 不发生 raise None）。"""
    monkeypatch.setattr(mod, "OUT", tmp_path)
    attempts: list[int] = []

    def _boom() -> dict:
        attempts.append(1)
        raise ValueError("boom-真因")

    monkeypatch.setattr(mod, "_build_and_solve_once", _boom)
    monkeypatch.setattr(mod, "BUILD_ATTEMPTS", 3)
    with pytest.raises(ValueError, match="boom-真因"):
        mod._build_and_solve()
    assert len(attempts) == 3


def test_hfss_construction_inside_try_records_crash(
        mod, monkeypatch, tmp_path):
    """Hfss() 构造失败也走 finally：solve_record.json 落盘（无 ok 键）。"""
    monkeypatch.setattr(mod, "OUT", tmp_path)
    monkeypatch.setattr(mod, "_assert_existing_desktops_none", lambda: None)

    def _broken_init(**_kw):
        raise RuntimeError("gRPC 通道损坏（#308 族）")

    _install_fake_aedt(monkeypatch, _broken_init)
    with pytest.raises(RuntimeError, match="gRPC 通道损坏"):
        mod._build_and_solve_once()
    record = tmp_path / "solve_record.json"
    assert record.exists(), "构造失败未落 solve_record.json（finally 未覆盖）"
    data = json.loads(record.read_text(encoding="utf-8"))
    assert "setups" in data and "ok" not in data
    assert data["started_utc"]


def test_hfss_success_path_still_releases(mod, monkeypatch, tmp_path):
    """构造成功但后续 HFSS 调用失败：finally 仍释放（h 非 None 路径不变）。"""
    monkeypatch.setattr(mod, "OUT", tmp_path)
    monkeypatch.setattr(mod, "_assert_existing_desktops_none", lambda: None)
    released: list[bool] = []

    class _BrokenAfterConstruction:
        def __init__(self, **_kw):
            self.modeler = types.SimpleNamespace(model_units=None)

        @property
        def materials(self):  # 构造后的首次 HFSS 调用即断链
            raise RuntimeError("构造后首调用失败")

        def release_desktop(self, **_kw):
            released.append(True)

    for name in ("ansys", "ansys.aedt", "ansys.aedt.core"):
        fake = types.ModuleType(name)
        fake.__path__ = []
        monkeypatch.setitem(sys.modules, name, fake)
    sys.modules["ansys.aedt.core"].Hfss = _BrokenAfterConstruction  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="构造后首调用失败"):
        mod._build_and_solve_once()
    assert released == [True]
    record = tmp_path / "solve_record.json"
    assert record.exists() and "ok" not in json.loads(
        record.read_text(encoding="utf-8"))
