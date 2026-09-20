"""HFSS 工程导入器测试（PyAEDT mock，不依赖真实 HFSS 安装）。"""

from __future__ import annotations

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
    design_name = "Design1"
    variable_manager = _VarManager()
    setups: ClassVar[list] = [_Setup()]
    boundaries: ClassVar[list] = [_Boundary("Port1", "Wave Port"),
                                  _Boundary("PerfE1", "Perfect E")]
    parametrics: ClassVar[list] = [_Parametric()]

    def release(self):
        pass


@pytest.fixture()
def mock_open(monkeypatch):
    monkeypatch.setattr(hfss_import, "_open_hfss", lambda *a, **kw: _FakeHfss())


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

    def _open(path, design, version, non_graphical):
        spy["path"] = path
        spy["design"] = design
        spy["version"] = version
        spy["non_graphical"] = non_graphical
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
