"""edb_adapter spec["resistors"] 消费面单元测试（2026-10-08，EDB 快车道收尾件）。

零 pyedb 真调（假包注入 sys.modules——test_edb_adapter::_install_fake_pyedb
同款纪律，pyedb 顶层包一级注入命中惰性 import），零网络零真机零 license。

断言面：
- R 值/几何/层/net 逐字透传（点端子坐标 mm→米，纯电阻处方 L/C 关断仅 R 使能，
  处方出处=pyedb 0.83.0 dotnet/database/source_excitations.py:898-908
  SourceType.Rlc 分支，见 edb_adapter._land_resistors docstring 逐行标注）；
- 无 resistors 键/空列表 = 零 RLC 调用零行为变化；电阻绝不进 config JSON
  （edb_templates/schema.py 假设 5 安全钉同款）；
- pyedb 缺失 / excitation_manager 缺失 / core.Utility 缺失 / 端子创建失败
  → 明确报错（fail-fast 不静默），close 仍执行（release 纪律）；
- 键名契约与 edb_templates 功分器发射器（power_divider.py:135-148）逐字
  对齐：用例直接以发射器原样七键集（name/layer/net/r_ohm/width_mm/
  path_mm/role）驱动全流程。
"""

from __future__ import annotations

import copy
import json
import sys
import types

import pytest

from rfauto.adapters.edb_adapter import (
    EdbAdapter,
    EdbSpecError,
    spec_to_config_json,
)


def _base_spec() -> dict:
    """合法最小 spec（无电阻键；每次新建防用例间变异串味）。"""
    return {
        "name": "demo",
        "stackup": {"layers": [
            {"name": "Bot", "type": "signal", "thickness_mm": 0.035},
            {"name": "Sub", "type": "dielectric", "thickness_mm": 0.254,
             "material_props": {"er": 3.66, "tan_d": 0.0037}},
            {"name": "Top", "type": "signal", "thickness_mm": 0.035},
        ]},
        "traces": [{"layer": "Top", "width_mm": 0.3,
                    "path_mm": [[0.0, 0.0], [5.0, 0.0]], "net": "RF"}],
    }


def _emitter_shape_resistor() -> dict:
    """edb_templates 功分器发射器原样键集（power_divider.py:135-148 同构
    自含样本）——契约互证：七键逐字对齐，role/width_mm 为发射侧声明键。"""
    return {
        "name": "RISO",
        "layer": "Top",
        "net": "RF",
        "r_ohm": 100.0,
        "width_mm": 0.3,
        "path_mm": [[1.85, -5.0], [2.15, -5.0]],
        "role": "isolation_resistor",
    }


def _spec_with_resistor(**overrides) -> dict:
    spec = _base_spec()
    res = _emitter_shape_resistor()
    res.update(overrides)
    spec["resistors"] = [res]
    return spec


# ─── 假 pyedb（记录调用序列；零真调）─────────────────────────────────────────


class _FakeConfiguration:
    def __init__(self, calls: list):
        self._calls = calls

    def load(self, config_file, append=True, apply_file=False, **kw):
        self._calls.append(("load", copy.deepcopy(config_file),
                            {"append": append, "apply_file": apply_file, **kw}))


class _FakeRawTerminal:
    """裸 dotnet 端子替身（wrapper._edb_object 面）。"""

    def __init__(self, calls: list, name: str):
        self._calls = calls
        self._name = name

    def SetRlcBoundaryParameters(self, rlc):
        self._calls.append(("SetRlcBoundaryParameters", self._name, rlc))


class _FakeTerminal:
    """PointTerminal wrapper 替身（boundary_type/reference_terminal 属性面）。"""

    def __init__(self, calls: list, name: str):
        self.name = name
        self.boundary_type = None
        self.reference_terminal = None
        self._edb_object = _FakeRawTerminal(calls, name)


class _FakeExcitation:
    def __init__(self, calls: list, fail_prefix: str | None = None):
        self._calls = calls
        self._fail_prefix = fail_prefix

    def create_point_terminal(self, x, y, layer, net, name=""):
        if self._fail_prefix is not None and name.startswith(self._fail_prefix):
            raise RuntimeError(f"Failed to create terminal. Input arguments: name={name}.")
        terminal = _FakeTerminal(self._calls, name)
        self._calls.append(("create_point_terminal", x, y, layer, net, name, terminal))
        return terminal


class _FakeRlc:
    def __init__(self) -> None:
        self.REnabled = None
        self.LEnabled = None
        self.CEnabled = None
        self.R = None


class _FakeUtility:
    def __init__(self, calls: list):
        self._calls = calls

    def Rlc(self):
        self._calls.append(("Utility.Rlc",))
        return _FakeRlc()


class _FakeCore:
    def __init__(self, calls: list):
        self.Utility = _FakeUtility(calls)


class _FakeEdb:
    """带 RLC 落地面的假 Edb（configuration/excitation_manager/core/edb_value）。"""

    def __init__(self, calls: list, *, without_excitation: bool = False,
                 without_core: bool = False, fail_prefix: str | None = None):
        self._calls = calls
        self.configuration = _FakeConfiguration(calls)
        if not without_excitation:
            self.excitation_manager = _FakeExcitation(calls, fail_prefix=fail_prefix)
        if not without_core:
            self.core = _FakeCore(calls)

    def edb_value(self, value):
        self._calls.append(("edb_value", value))
        return ("Value", value)  # 可辨识 marker：R 透传断言用

    def save_edb(self) -> bool:
        self._calls.append(("save",))
        return True

    def close_edb(self) -> bool:
        self._calls.append(("close",))
        return True


def _install_fake_pyedb(monkeypatch: pytest.MonkeyPatch, calls: list, **fake_kw) -> None:
    """注入假 pyedb 顶层包（adapter 函数内惰性 import 命中，不触真包）。"""
    fake = types.ModuleType("pyedb")

    def _edb_cls(**kw):
        calls.append(("Edb", kw))
        return _FakeEdb(calls, **fake_kw)

    fake.Edb = _edb_cls
    monkeypatch.setitem(sys.modules, "pyedb", fake)


# ─── spec 校验/翻译面（config 不收电阻，结构非法 fail-fast）──────────────────


class TestResistorSpecValidation:
    def test_resistors_never_in_config(self):
        """安全钉（schema.py 假设 5）：电阻绝不以金属进 config。"""
        cfg_with = spec_to_config_json(_spec_with_resistor())
        cfg_without = spec_to_config_json(_base_spec())
        assert cfg_with == cfg_without  # 电阻零 config 足迹
        assert "resistors" not in cfg_with
        assert "RISO" not in [t["name"] for t in cfg_with["modeler"]["traces"]]

    def test_empty_resistor_list_config_identical(self):
        spec = _base_spec()
        spec["resistors"] = []
        assert spec_to_config_json(spec) == spec_to_config_json(_base_spec())

    def test_resistors_must_be_list(self):
        spec = _base_spec()
        spec["resistors"] = {"name": "R1"}
        with pytest.raises(EdbSpecError, match="须为 list"):
            spec_to_config_json(spec)

    def test_duplicate_resistor_name(self):
        spec = _spec_with_resistor()
        spec["resistors"].append(dict(spec["resistors"][0]))
        with pytest.raises(EdbSpecError, match="'RISO' 重复"):
            spec_to_config_json(spec)

    def test_layer_must_be_signal(self):
        with pytest.raises(EdbSpecError, match="signal 层内"):
            spec_to_config_json(_spec_with_resistor(layer="Sub"))

    def test_net_required_non_empty(self):
        """net 必填非空：点端子经 pyedb find_net_by_name 挂网，空 net 无处可挂。"""
        with pytest.raises(EdbSpecError, match="'net'"):
            spec_to_config_json(_spec_with_resistor(net=""))
        with pytest.raises(EdbSpecError, match="'net'"):
            spec_to_config_json(_spec_with_resistor(net=None))

    def test_r_ohm_must_be_positive(self):
        with pytest.raises(EdbSpecError, match="'r_ohm'"):
            spec_to_config_json(_spec_with_resistor(r_ohm=0.0))
        with pytest.raises(EdbSpecError, match="'r_ohm'"):
            spec_to_config_json(_spec_with_resistor(r_ohm=-5.0))

    def test_width_mm_must_be_positive(self):
        with pytest.raises(EdbSpecError, match="'width_mm'"):
            spec_to_config_json(_spec_with_resistor(width_mm=0.0))

    def test_path_mm_at_least_two_points(self):
        with pytest.raises(EdbSpecError, match="≥2 点"):
            spec_to_config_json(_spec_with_resistor(path_mm=[[1.0, 2.0]]))

    def test_path_point_must_be_xy_pair(self):
        with pytest.raises(EdbSpecError, match=r"\[x, y\]"):
            spec_to_config_json(_spec_with_resistor(path_mm=[[1.0, 2.0], [3.0]]))

    def test_role_must_be_string_when_present(self):
        with pytest.raises(EdbSpecError, match="'role'"):
            spec_to_config_json(_spec_with_resistor(role=123))

    def test_default_name_and_extra_keys_tolerated(self):
        """缺 name 缺省 resistor_{i}；发射器 role 等额外键容忍（traces 先例）。"""
        spec = _base_spec()
        res = _emitter_shape_resistor()
        del res["name"]
        spec["resistors"] = [res]
        cfg = spec_to_config_json(spec)  # 不抛即通过（校验面无产出可断言）
        assert "resistors" not in cfg

    def test_resistor_top_key_now_legal_and_others_still_rejected(self):
        spec = _spec_with_resistor()
        spec["resistor"] = [dict(spec["resistors"][0])]  # 单数拼写=未知键
        with pytest.raises(EdbSpecError, match="未知顶层键"):
            spec_to_config_json(spec)


# ─── 落地面（build + 假 pyedb，调用序列断言）─────────────────────────────────


class TestResistorLanding:
    def test_full_landing_sequence(self, tmp_path, monkeypatch):
        """点端子对 + RlcBoundary + 纯电阻 RLC 处方，全程调用序列逐项断言。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        result = EdbAdapter(tmp_path).build(_spec_with_resistor())
        assert result.aedb_path.name == "demo.aedb"
        # 两个点端子：首点=正端子 {name}_p、末点=参考端子 {name}_ref（pyedb
        # create_rlc_boundary_on_pins:1765 命名同款）；坐标 mm→米逐字透传
        created = [c for c in calls if c[0] == "create_point_terminal"]
        assert [(c[1], c[2], c[3], c[4], c[5]) for c in created] == [
            (0.00185, -0.005, "Top", "RF", "RISO_p"),
            (0.00215, -0.005, "Top", "RF", "RISO_ref"),
        ]
        pos, ref = created[0][6], created[1][6]
        # 双端子 boundary_type="RlcBoundary"（terminal.py 字符串映射面）
        assert pos.boundary_type == "RlcBoundary"
        assert ref.boundary_type == "RlcBoundary"
        # 纯电阻处方（source_excitations.py:898-908 逐字）：L/C 关断仅 R 使能
        assert calls.count(("Utility.Rlc",)) == 1
        rlc = next(c[2] for c in calls if c[0] == "SetRlcBoundaryParameters")
        assert isinstance(rlc, _FakeRlc)
        assert rlc.REnabled is True and rlc.LEnabled is False and rlc.CEnabled is False
        # R 经 edb_value 裸数值透传（r_ohm 逐字，含 marker 身份）
        assert ("edb_value", 100.0) in calls
        assert rlc.R == ("Value", 100.0)
        # 参数挂正端子裸对象；参考端子接线 pos→ref
        assert ("SetRlcBoundaryParameters", "RISO_p", rlc) in calls
        assert not any(c[0] == "SetRlcBoundaryParameters" and c[1] == "RISO_ref"
                       for c in calls)
        assert pos.reference_terminal is ref
        # 时序：load（config 注入）< 端子创建 < save < close（release 纪律）
        order = [c[0] for c in calls]
        assert order.index("load") < order.index("create_point_terminal")
        assert order.index("create_point_terminal") < order.index("save")
        assert order.index("save") < order.index("close")

    def test_values_pass_through_exactly(self, tmp_path, monkeypatch):
        """R 值/几何/层/net 逐字透传：非整数值与小数坐标零变换。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        spec = _spec_with_resistor(name="R2", r_ohm=137.5, width_mm=0.254,
                                   path_mm=[[1.0 / 3.0, -2.5], [4.25, -2.5]])
        EdbAdapter(tmp_path).build(spec)
        created = [c for c in calls if c[0] == "create_point_terminal"]
        assert [(c[1], c[2]) for c in created] == [
            (1.0 / 3.0 * 1e-3, -2.5e-3), (4.25e-3, -2.5e-3)]
        assert ("edb_value", 137.5) in calls

    def test_two_resistors_default_names(self, tmp_path, monkeypatch):
        """多条电阻逐条落地；缺 name 缺省 resistor_{i}（表内序号）。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        spec = _spec_with_resistor()
        r2 = dict(_emitter_shape_resistor())
        del r2["name"]
        r2["path_mm"] = [[0.0, 0.0], [0.1, 0.0]]
        spec["resistors"].append(r2)
        EdbAdapter(tmp_path).build(spec)
        names = [c[5] for c in calls if c[0] == "create_point_terminal"]
        assert names == ["RISO_p", "RISO_ref", "resistor_2_p", "resistor_2_ref"]
        assert calls.count(("Utility.Rlc",)) == 2

    def test_no_resistors_key_zero_rlc_calls(self, tmp_path, monkeypatch):
        """无 resistors 键=行为零变化：零 RLC 调用，序列即裸建库四步。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        EdbAdapter(tmp_path).build(_base_spec())
        assert [c[0] for c in calls] == ["Edb", "load", "save", "close"]

    def test_empty_resistor_list_zero_rlc_calls(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        spec = _base_spec()
        spec["resistors"] = []
        EdbAdapter(tmp_path).build(spec)
        assert [c[0] for c in calls] == ["Edb", "load", "save", "close"]

    def test_missing_pyedb_explicit_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyedb", None)  # 强制 ImportError
        with pytest.raises(RuntimeError, match=r"rfauto\[edb\]"):
            EdbAdapter(tmp_path).build(_spec_with_resistor())

    def test_without_excitation_manager_explicit_error(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls, without_excitation=True)
        with pytest.raises(RuntimeError, match="excitation_manager"):
            EdbAdapter(tmp_path).build(_spec_with_resistor())
        assert "close" in [c[0] for c in calls]  # release 纪律不因失败豁免

    def test_without_core_utility_explicit_error(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls, without_core=True)
        with pytest.raises(RuntimeError, match=r"core\.Utility"):
            EdbAdapter(tmp_path).build(_spec_with_resistor())

    def test_terminal_creation_failure_wrapped_with_context(self, tmp_path, monkeypatch):
        """端子创建失败（net 不存在等）→ 包装电阻名上下文重抛，不静默。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls, fail_prefix="RISO")
        with pytest.raises(RuntimeError, match=r"RISO.*端子创建失败"):
            EdbAdapter(tmp_path).build(_spec_with_resistor())
        assert "close" in [c[0] for c in calls]

    def test_config_json_on_disk_has_no_resistor_metal(self, tmp_path, monkeypatch):
        """落盘存证同钉：config JSON 无电阻金属痕迹（防下游逐字套用短路）。"""
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        result = EdbAdapter(tmp_path).build(_spec_with_resistor())
        on_disk = json.loads(result.config_json_path.read_text(encoding="utf-8"))
        assert on_disk == spec_to_config_json(_base_spec())
