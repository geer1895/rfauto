"""PyEDB 适配器（EDB 快车道底座）单元测试（2026-10-08）。

零 pyedb 真调（假包注入 sys.modules——test_q3d_adapter::_install_fake_pyaedt
三级假包注入先例同款纪律；pyedb 是顶层包故一级注入即命中惰性 import），
零网络零真机零 license。spec_to_config_json 翻译面另经真 pyedb CfgData
pydantic 校验互证（开发期实测 7 种 setup 形态全 OK，见适配器尾部注释）；
本文件对真 CfgData 零依赖（裸环境/无 pyedb 环境同样全绿）。
"""

from __future__ import annotations

import copy
import json
import re
import sys
import types
from pathlib import Path

import pytest

from rfauto.adapters import edb_adapter as ea
from rfauto.adapters.edb_adapter import (
    BatchSolveResult,
    EdbAdapter,
    EdbBuildResult,
    EdbSpecError,
    spec_to_config_json,
)
from rfauto.adapters.em_solver_base import (
    MATERIAL_MODELS,
    EMSolverType,
    solver_capabilities_for,
)


def _base_spec() -> dict:
    """合法最小 spec（每次新建防用例间变异串味）。"""
    return {
        "name": "demo",
        "stackup": {"layers": [
            {"name": "Bot", "type": "signal", "thickness_mm": 0.035},
            {"name": "Sub", "type": "dielectric", "thickness_mm": 0.254,
             "material_props": {"er": 3.66, "tan_d": 0.0037}},
            {"name": "Top", "type": "signal", "thickness_mm": 0.035},
        ]},
        "traces": [{"layer": "Top", "width_mm": 0.3,
                    "path_mm": [[0.0, 0.0], [5.0, 0.0]], "net": "sig"}],
        "vias": [{"diameter_mm": 0.2, "x_mm": 2.0, "y_mm": 1.0,
                  "start_layer": "Top", "stop_layer": "Bot", "net": "sig"}],
        "ports": [{"number": 1, "layer": "Top", "net": "sig",
                   "start": [0.0, 0.0],
                   "end": {"layer": "Top", "point_mm": [5.0, 0.0], "net": "sig"}}],
        "sim_setup": {"f_start_ghz": 0.1, "f_stop_ghz": 20.0, "points": 401},
    }


# ─── 假 pyedb / 假 hfss_batch 注入（惰性 import 命中面）──────────────────────


class _FakeConfiguration:
    def __init__(self, calls: list):
        self._calls = calls

    def load(self, config_file, append=True, apply_file=False, **kw):
        self._calls.append(("load", copy.deepcopy(config_file),
                            {"append": append, "apply_file": apply_file, **kw}))
        return None


class _FakeEdb:
    def __init__(self, calls: list, **kw):
        calls.append(("Edb", kw))
        self.configuration = _FakeConfiguration(calls)
        self._calls = calls

    def save_edb(self) -> bool:
        self._calls.append(("save",))
        return True

    def close_edb(self) -> bool:
        self._calls.append(("close",))
        return True


def _install_fake_pyedb(monkeypatch: pytest.MonkeyPatch, calls: list, *,
                        without_edb_attr: bool = False,
                        without_configuration: bool = False) -> None:
    """注入假 pyedb 顶层包（adapter 函数内惰性 import 命中，不触真包）。"""
    fake = types.ModuleType("pyedb")
    if without_edb_attr:
        pass  # 不挂 Edb 属性：入口类缺失路径
    else:
        def _edb_cls(**kw):
            edb = _FakeEdb(calls, **kw)
            if without_configuration:
                del edb.configuration  # configuration 接口缺失路径
            return edb

        fake.Edb = _edb_cls
    monkeypatch.setitem(sys.modules, "pyedb", fake)


def _install_fake_hfss_batch(monkeypatch: pytest.MonkeyPatch, calls: list, *,
                             as_none: bool = False,
                             without_fn: bool = False,
                             result: object | None = None) -> None:
    """注入假 rfauto.adapters.hfss_batch（他席通道替身）。"""
    if as_none:
        # sys.modules 挂 None → import_module 抛 ImportError（未落地确定性口径）
        monkeypatch.setitem(sys.modules, "rfauto.adapters.hfss_batch", None)
        return
    mod = types.ModuleType("rfauto.adapters.hfss_batch")
    if not without_fn:
        ret = result if result is not None else BatchSolveResult(success=True, message="ok")

        def _solve(aedb_path, timeout_s=3600.0):
            calls.append(("solve", aedb_path, timeout_s))
            return ret

        mod.solve_project_batch = _solve
    monkeypatch.setitem(sys.modules, "rfauto.adapters.hfss_batch", mod)


# ─── spec → config 翻译面 ────────────────────────────────────────────────────


class TestSpecTranslation:
    def test_full_spec_all_sections(self):
        cfg = spec_to_config_json(_base_spec())
        assert set(cfg) == {"stackup", "modeler", "padstacks", "ports", "setups"}
        # 材料：er/tan_d → permittivity/dielectric_loss_tangent
        assert cfg["stackup"]["materials"] == [{
            "name": "Sub_material", "permittivity": 3.66,
            "dielectric_loss_tangent": 0.0037}]
        # 层序：spec 自底向上 → config 翻转为自顶向下（pyedb 0.83
        # __create_stackup 逐层 AddLayerBottom 首项落物理顶层，源码实证——
        # 2026-10-08 审查批 P0 修复，物理顶层=spec 末层 Top 落 config 首位）
        assert [ly["name"] for ly in cfg["stackup"]["layers"]] == ["Top", "Sub", "Bot"]
        assert cfg["stackup"]["layers"][0]["material"] == "copper"
        assert cfg["stackup"]["layers"][1]["material"] == "Sub_material"
        assert cfg["stackup"]["layers"][2]["thickness"] == "0.035mm"
        # 路径 mm→米（官方文档口径）
        assert cfg["modeler"]["traces"][0]["path"] == [[0.0, 0.0], [0.005, 0.0]]
        assert cfg["modeler"]["traces"][0]["width"] == "0.3mm"
        # 过孔：同孔径共享定义 + 位置 mm→米
        inst = cfg["padstacks"]["instances"][0]
        assert inst["definition"] == "via_0.2mm"
        assert inst["position"] == [0.002, 0.001]
        assert cfg["padstacks"]["definitions"][0]["hole_parameters"] == {
            "shape": "circle", "diameter": "0.2mm"}
        # 端口：coordinates 正负终端 + 阻抗缺省 50
        port = cfg["ports"][0]
        assert port["name"] == "p1" and port["impedance"] == 50.0
        assert port["positive_terminal"] == {
            "coordinates": {"layer": "Top", "point": [0.0, 0.0], "net": "sig"}}
        assert port["negative_terminal"]["coordinates"]["point"] == [0.005, 0.0]

    def test_minimal_spec_only_stackup(self):
        cfg = spec_to_config_json({
            "stackup": {"layers": [{"name": "L", "type": "signal",
                                    "thickness_mm": 0.035}]}})
        assert set(cfg) == {"stackup"}
        assert "materials" in cfg["stackup"]  # 空材料表也显式在（结构稳定）

    def test_shorthand_sim_setup_defaults(self):
        spec = _base_spec()
        del spec["sim_setup"]["points"]  # 缺省 401
        cfg = spec_to_config_json(spec)
        setup = cfg["setups"][0]
        assert setup["name"] == "hfss_setup_1" and setup["type"] == "hfss"
        sweep = setup["freq_sweep"][0]
        assert sweep["type"] == "interpolation"
        freq = sweep["frequencies"][0]
        # 带单位字符串=%.10g 统一口径（2026-10-08 契约统一：与
        # edb_templates.schema.assemble_config _fmt_ghz 同式，尾零省略）
        assert freq == {"start": "0.1GHz", "stop": "20GHz",
                        "increment": 401, "distribution": "linear_count"}
        # 自适应缺省 = pyedb 官方缺省（5GHz/20/0.02；字符串=%.10g 统一口径）
        assert setup["single_frequency_adaptive_solution"] == {
            "adaptive_frequency": "5GHz", "max_passes": 20, "max_delta": 0.02}

    def test_explicit_sweeps_distribution_mapping(self):
        """spec 形态 → pyedb distribution literal 映射（linear_step→linear_scale
        等——CfgFrequencies docstring 与真 literal 失真按实现口径）。"""
        spec = {"stackup": {"layers": [{"name": "L", "type": "signal",
                                        "thickness_mm": 0.035}]},
                "sim_setup": {"sweeps": [
                    {"type": "linear_step", "start_ghz": 0.1, "stop_ghz": 10.0,
                     "step_ghz": 0.01},
                    {"type": "log_count", "start_ghz": 0.1, "stop_ghz": 10.0,
                     "count": 50},
                    {"type": "log_step", "start_ghz": 0.1, "stop_ghz": 10.0,
                     "step_ghz": 0.5},
                    {"type": "single", "freq_ghz": 2.4},
                    {"type": "linear_count", "start_ghz": 1.0, "stop_ghz": 2.0,
                     "count": 11},
                ]}}
        freqs = [s["frequencies"][0]
                 for s in spec_to_config_json(spec)["setups"][0]["freq_sweep"]]
        assert [f["distribution"] for f in freqs] == [
            "linear_scale", "log_count", "log_scale", "single", "linear_count"]
        assert freqs[0]["increment"] == "0.01GHz"  # 步进带单位（setup 频率缺省 Hz 歧义规避）
        assert freqs[2]["increment"] == 0.5        # log_step 步进=十倍程数（无量纲）
        assert freqs[3] == {"start": "2.4GHz", "stop": "2.4GHz",
                            "increment": 1, "distribution": "single"}

    def test_config_json_round_trip(self):
        cfg = spec_to_config_json(_base_spec())
        assert json.loads(json.dumps(cfg)) == cfg  # 全 JSON 安全类型

    def test_config_layer_order_lands_physical_top_down(self):
        """层序回归钉（2026-10-08 审查批 P0）：spec 自底向上 [GND,SUB,TOP]
        → config 自顶向下 [TOP,SUB,GND]。

        证据链：pyedb 0.83 __create_stackup 按列表序逐层 AddLayerBottom
        （每次插到全栈最底→列表首项落物理顶层；configuration.py:863-868 +
        dotnet/database/stackup.py:97-130 源码实证；__update_stackup 同口径
        layers.pop(0) 走 add_layer_top）；官方示例 TOP,DE,BOTTOM 首项=顶层；
        docs/pyedb_distilled.md §3.1/§6-2（「adapter 翻转一次」处方）；
        真机冒烟（runs/edblane85/w1_smoke/build_pyaedt.py）以 GND=elevation0
        验证的正确物理序=信号层在上。未翻转时发射族叠层整体上下颠倒
        （GND 落物理顶层=倒置微带，综合 λ/4 几何全错且无报错）。
        """
        spec = {"stackup": {"layers": [
            {"name": "GND", "type": "signal", "thickness_mm": 0.035},
            {"name": "SUB", "type": "dielectric", "thickness_mm": 0.5,
             "material_props": {"er": 4.4}},
            {"name": "TOP", "type": "signal", "thickness_mm": 0.035}]}}
        cfg = spec_to_config_json(spec)
        assert [ly["name"] for ly in cfg["stackup"]["layers"]] == [
            "TOP", "SUB", "GND"]
        # 地板载体平面（board 段）仍落物理底层信号层（spec 首层 GND）
        spec["board"] = {"lower_left_mm": [0.0, 0.0],
                         "upper_right_mm": [1.0, 1.0]}
        (plane,) = spec_to_config_json(spec)["modeler"]["planes"]
        assert plane["layer"] == "GND"


class TestSpecValidation:
    """fail-fast：缺键/类型错/越界给中文定位（EdbSpecError）。"""

    @staticmethod
    def _raises(spec, fragment):
        with pytest.raises(EdbSpecError, match=fragment):
            spec_to_config_json(spec)

    def test_spec_not_dict(self):
        self._raises(["nope"], "须为 dict")

    def test_missing_stackup(self):
        self._raises({"traces": []}, "缺必填键 'stackup'")

    def test_unknown_top_key(self):
        spec = _base_spec()
        spec["oops"] = 1
        self._raises(spec, "未知顶层键")

    def test_bad_name(self):
        spec = _base_spec()
        spec["name"] = "a/b"
        self._raises(spec, "纯文件名主干")
        spec["name"] = ".."
        self._raises(spec, "纯文件名主干")

    def test_bad_layer_type_and_thickness(self):
        self._raises({"stackup": {"layers": [
            {"name": "A", "type": "weird", "thickness_mm": 1.0}]}}, "type 须为")
        self._raises({"stackup": {"layers": [
            {"name": "A", "type": "signal", "thickness_mm": -1.0}]}}, "正数")
        self._raises({"stackup": {"layers": [
            {"name": "A", "type": "signal", "thickness_mm": True}]}}, "须为数值")

    def test_dielectric_requires_material_or_props(self):
        self._raises({"stackup": {"layers": [
            {"name": "A", "type": "dielectric", "thickness_mm": 1.0}]}},
            "material_props")

    def test_signal_material_props_rejected(self):
        spec = {"stackup": {"layers": [
            {"name": "A", "type": "signal", "thickness_mm": 1.0,
             "material_props": {"er": 1.0}}]}}
        self._raises(spec, "v1 边界")

    def test_material_and_props_exclusive(self):
        spec = {"stackup": {"layers": [
            {"name": "A", "type": "dielectric", "thickness_mm": 1.0,
             "material": "FR4_epoxy", "material_props": {"er": 4.4}}]}}
        self._raises(spec, "二选一")

    def test_duplicate_layer_and_material(self):
        spec = {"stackup": {"layers": [
            {"name": "A", "type": "signal", "thickness_mm": 1.0},
            {"name": "A", "type": "signal", "thickness_mm": 1.0}]}}
        self._raises(spec, "重复")
        spec2 = {"stackup": {"layers": [
            {"name": "A", "type": "dielectric", "thickness_mm": 1.0,
             "material_props": {"er": 2.0, "name": "M"}},
            {"name": "B", "type": "dielectric", "thickness_mm": 1.0,
             "material_props": {"er": 3.0, "name": "M"}}]}}
        self._raises(spec2, "材料名 .* 重复")

    def test_trace_validation(self):
        spec = _base_spec()
        spec["traces"][0]["layer"] = "Sub"  # 介质层不可布线
        self._raises(spec, "signal 层内")
        spec2 = _base_spec()
        spec2["traces"][0]["path_mm"] = [[0, 0]]
        self._raises(spec2, "≥2 点")

    def test_via_validation(self):
        spec = _base_spec()
        spec["vias"][0]["stop_layer"] = "Nope"
        self._raises(spec, "不在 stackup 内")

    def test_port_validation(self):
        spec = _base_spec()
        spec["ports"].append({"number": 1, "start": [0, 0], "end": [1, 1]})
        self._raises(spec, "端口号 1 重复")
        spec2 = _base_spec()
        spec2["ports"][0]["start"] = [0, 0]  # 简写但无端口级 layer
        del spec2["ports"][0]["layer"]
        self._raises(spec2, "缺 layer")
        spec3 = _base_spec()
        spec3["ports"][0]["type"] = "wave"  # 波端口不在 EDB 电路端口词表
        self._raises(spec3, "type 须为")

    def test_sweep_validation(self):
        spec = _base_spec()
        spec["sim_setup"] = {"sweeps": [{"type": "quantum", "x": 1}]}
        self._raises(spec, "type 须为")
        spec2 = _base_spec()
        spec2["sim_setup"] = {"sweeps": [{"type": "linear_count",
                                          "start_ghz": 1.0}]}
        self._raises(spec2, "缺必填键 'stop_ghz'")
        spec3 = _base_spec()
        spec3["sim_setup"] = {"sweeps": [{"type": "linear_count", "start_ghz": 1.0,
                                          "stop_ghz": 2.0, "count": 10, "v": 1}]}
        self._raises(spec3, "不接受键")

    def test_sim_setup_ranges_and_type(self):
        spec = _base_spec()
        spec["sim_setup"]["f_stop_ghz"] = 0.05
        self._raises(spec, "不得小于")
        spec2 = _base_spec()
        spec2["sim_setup"]["type"] = "siwave_ac"
        spec2["sim_setup"]["max_passes"] = 5
        self._raises(spec2, "仅 type=hfss")

    def test_number_type_rejects_bool(self):
        spec = _base_spec()
        spec["sim_setup"]["points"] = False
        self._raises(spec, "须为整数")

    def test_via_must_be_through_span(self):
        """v1 边界（2026-10-08 审查批 P1）：pyedb CfgPadstackDefinition.
        hole_range 未透传（缺省 through 语义，cfg_padstacks.py:196，
        docs/pyedb_distilled.md §3.2）——盲埋孔 spec 会静默错落整叠通孔，
        fail-fast 不虚报。"""
        spec = _base_spec()  # Bot/Sub/Top，信号层极端=Bot/Top
        spec["vias"][0]["start_layer"] = "Bot"
        spec["vias"][0]["stop_layer"] = "Bot"
        self._raises(spec, "整叠通孔")
        # 五层叠（含中间信号层）盲埋孔：start/stop 不跨全部信号极端
        spec2 = {"stackup": {"layers": [
            {"name": "B", "type": "signal", "thickness_mm": 0.035},
            {"name": "D1", "type": "dielectric", "thickness_mm": 0.2,
             "material_props": {"er": 4.0}},
            {"name": "M", "type": "signal", "thickness_mm": 0.035},
            {"name": "D2", "type": "dielectric", "thickness_mm": 0.2,
             "material_props": {"er": 4.0}},
            {"name": "T", "type": "signal", "thickness_mm": 0.035}]},
            "vias": [{"diameter_mm": 0.2, "x_mm": 0.0, "y_mm": 0.0,
                      "start_layer": "M", "stop_layer": "T"}]}
        self._raises(spec2, "整叠通孔")
        # 整叠通孔（两极端，任一方向）仍放行
        spec2["vias"][0].update(start_layer="T", stop_layer="B")
        spec_to_config_json(spec2)
        spec2["vias"][0].update(start_layer="B", stop_layer="T")
        spec_to_config_json(spec2)


# ─── build 面（假 pyedb，零真调）─────────────────────────────────────────────


class TestBuild:
    def test_build_full_sequence(self, tmp_path, monkeypatch):
        calls: list = []
        monkeypatch.delenv("RFAUTO_EDB_AEDT_VERSION", raising=False)  # 钉版断言前清环境
        _install_fake_pyedb(monkeypatch, calls)
        adapter = EdbAdapter(tmp_path / "nested" / "dir")  # 不存在目录自动建
        result = adapter.build(_base_spec())

        assert isinstance(result, EdbBuildResult)
        assert result.aedb_path == tmp_path / "nested" / "dir" / "demo.aedb"
        assert result.config_json_path.name == "demo_config.json"
        assert result.config_json_path.exists()
        assert result.warnings == []
        # 惰性 import 命中假包：Edb(edbpath=, isreadonly=, version=钉版)
        assert calls[0][0] == "Edb"
        kw = calls[0][1]
        assert kw["edbpath"] == str(result.aedb_path)
        assert kw["isreadonly"] is False
        assert kw["version"] == "2025.1"  # AGENTS 规则 0：本机 AEDT 2025 R1 对齐基准
        # configuration.load 收到与落盘 JSON 逐字节同构的 dict + apply_file=True
        loads = [c for c in calls if c[0] == "load"]
        assert len(loads) == 1
        _, loaded, lkwa = loads[0]
        on_disk = json.loads(result.config_json_path.read_text(encoding="utf-8"))
        assert loaded == on_disk
        assert lkwa["apply_file"] is True
        # save 在 close 之前（release 纪律）
        order = [c[0] for c in calls]
        assert order.index("save") < order.index("close")

    def test_build_version_env_override(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        monkeypatch.setenv("RFAUTO_EDB_AEDT_VERSION", "2024.2")
        EdbAdapter(tmp_path).build(_base_spec())
        assert calls[0][1]["version"] == "2024.2"

    def test_build_occupied_path_suffix_and_warning(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        (tmp_path / "demo.aedb").mkdir()  # 占位：不覆盖既有工程
        result = EdbAdapter(tmp_path).build(_base_spec())
        assert result.aedb_path.name == "demo_1.aedb"
        assert result.config_json_path.name == "demo_1_config.json"  # 存证与工程同名配对
        assert result.warnings and "不覆盖" in result.warnings[0]

    def test_build_missing_pyedb_explicit_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyedb", None)  # 强制 ImportError（真包已装也拦）
        with pytest.raises(RuntimeError, match=r"rfauto\[edb\]"):
            EdbAdapter(tmp_path).build(_base_spec())

    def test_build_pyedb_without_edb_attr(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls, without_edb_attr=True)
        with pytest.raises(RuntimeError, match="Edb 入口类"):
            EdbAdapter(tmp_path).build(_base_spec())

    def test_build_edb_without_configuration(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls, without_configuration=True)
        with pytest.raises(RuntimeError, match=r"configuration\.load"):
            EdbAdapter(tmp_path).build(_base_spec())

    def test_build_invalid_spec_fails_before_io(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb(monkeypatch, calls)
        bad = _base_spec()
        del bad["stackup"]
        with pytest.raises(EdbSpecError):
            EdbAdapter(tmp_path).build(bad)
        assert calls == []  # fail-fast：校验前移，零副作用（无假包调用/无落盘）


# ─── solve_batch 面（假 hfss_batch 通道）─────────────────────────────────────


class TestSolveBatch:
    def test_pass_through(self, tmp_path, monkeypatch):
        calls: list = []
        sentinel = BatchSolveResult(success=True, message="done", elapsed_s=1.5)
        _install_fake_pyedb(monkeypatch, [])
        _install_fake_hfss_batch(monkeypatch, calls, result=sentinel)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        out = EdbAdapter(tmp_path).solve_batch(aedb, timeout_s=60.0)
        assert out is sentinel
        ((_, path, timeout),) = calls  # type: ignore[index]
        assert path == aedb and isinstance(path, Path)
        assert timeout == 60.0

    def test_default_timeout(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_hfss_batch(monkeypatch, calls)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        EdbAdapter(tmp_path).solve_batch(aedb)
        assert calls[0][2] == 3600.0

    def test_channel_not_landed(self, tmp_path, monkeypatch):
        _install_fake_hfss_batch(monkeypatch, [], as_none=True)
        with pytest.raises(RuntimeError, match="未落地"):
            EdbAdapter(tmp_path).solve_batch(tmp_path / "x.aedb")

    def test_contract_incomplete(self, tmp_path, monkeypatch):
        _install_fake_hfss_batch(monkeypatch, [], without_fn=True)
        with pytest.raises(RuntimeError, match="契约不完整"):
            EdbAdapter(tmp_path).solve_batch(tmp_path / "x.aedb")

    def test_missing_aedb_fails_fast(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_hfss_batch(monkeypatch, calls)
        with pytest.raises(FileNotFoundError):
            EdbAdapter(tmp_path).solve_batch(tmp_path / "ghost.aedb")
        assert calls == []  # 不存在不发求解请求

    def test_dict_result_normalized(self, tmp_path, monkeypatch):
        """他席结构化 dict 契约 → BatchSolveResult 归一（成功形态）。"""
        raw = {"ok": True, "rc": 0, "timed_out": False, "elapsed_s": 12.5,
               "logfile": str(tmp_path / "log.txt"),
               "artifacts": [str(tmp_path / "a.s2p")], "errors": []}
        _install_fake_hfss_batch(monkeypatch, [], result=raw)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        out = EdbAdapter(tmp_path).solve_batch(aedb)
        assert out.success is True
        assert out.rc == 0 and out.timed_out is False
        assert out.log_path == tmp_path / "log.txt"
        assert out.artifacts == [tmp_path / "a.s2p"]
        assert out.elapsed_s == 12.5 and out.message == ""

    def test_dict_failure_normalized(self, tmp_path, monkeypatch):
        """rc=None 前置失败形态：errors 进 message、success=False 不臆造。"""
        raw = {"ok": False, "rc": None, "timed_out": False, "elapsed_s": 0.0,
               "logfile": None, "artifacts": [],
               "errors": ["未找到 ansysedt.exe"]}
        _install_fake_hfss_batch(monkeypatch, [], result=raw)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        out = EdbAdapter(tmp_path).solve_batch(aedb)
        assert out.success is False
        assert out.rc is None
        assert "ansysedt" in out.message

    def test_dict_timed_out_message(self, tmp_path, monkeypatch):
        raw = {"ok": False, "rc": 1, "timed_out": True, "elapsed_s": 60.0,
               "logfile": None, "artifacts": [], "errors": []}
        _install_fake_hfss_batch(monkeypatch, [], result=raw)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        out = EdbAdapter(tmp_path).solve_batch(aedb)
        assert out.success is False and out.timed_out is True
        assert out.message == "watchdog 超时"

    def test_unknown_result_shape_reported_not_silent(self, tmp_path, monkeypatch):
        _install_fake_hfss_batch(monkeypatch, [], result=42)
        aedb = tmp_path / "x.aedb"
        aedb.mkdir()
        out = EdbAdapter(tmp_path).solve_batch(aedb)
        assert out.success is False
        assert "int" in out.message


# ─── 能力声明（em_solver_base "edb" 字符串键条目）────────────────────────────


class TestCapabilityDeclaration:
    def test_edb_reachable_and_honest(self):
        caps = solver_capabilities_for("edb")
        assert caps.solver_type == "edb"
        assert caps.availability_gate == "pyedb"
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is True
        assert caps.supports_touchstone_export is True
        assert caps.supports_headless_solve is True
        assert caps.dimension == "2d"
        assert caps.requires_license is True
        # 诚实位：无实现的能力如实 False/空（#122）
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.supports_lumped_elements is False
        assert caps.supported_templates == ()
        assert caps.parallel_backends == ()
        assert set(caps.material_models) <= set(MATERIAL_MODELS)

    def test_enum_not_extended_and_legacy_keys_untouched(self):
        """独立协议通道不扩枚举（注册面决策门口径）；既有键语义零扰动。"""
        assert not hasattr(EMSolverType, "EDB")
        with pytest.raises(KeyError):
            solver_capabilities_for(EMSolverType.Q3D)  # 原未声明语义保持
        with pytest.raises(KeyError):
            solver_capabilities_for("never_a_solver")

    def test_dataclass_shapes(self):
        r = EdbBuildResult(aedb_path=Path("a"), config_json_path=Path("b"))
        assert r.warnings == []
        s = BatchSolveResult(success=False)
        assert s.message == "" and s.log_path is None and s.elapsed_s == 0.0


# ─── 分层/惰性导入卫生（import-linter 语义自查）──────────────────────────────


class TestLayeringHygiene:
    _SRC = Path(ea.__file__).read_text(encoding="utf-8")

    def test_no_service_cli_imports(self):
        for bad in ("rfauto.service", "rfauto.cli", "from rfauto import service"):
            assert bad not in self._SRC, bad

    def test_top_level_imports_are_stdlib_only(self):
        """顶层 import 仅 stdlib——pyedb/hfss_batch 必须函数内惰性（未装环境
        import 本模块零副作用）。"""
        top = [ln for ln in self._SRC.splitlines()
               if re.match(r"^(import |from )", ln)]
        assert top, "顶层 import 缺失？"
        for ln in top:
            assert not ln.startswith(("import pyedb", "from pyedb",
                                      "import rfauto", "from rfauto")), ln

    def test_lazy_import_sites_present(self):
        assert "import pyedb" in self._SRC  # 函数内（上一测试钉了非顶层）
        assert "rfauto.adapters.hfss_batch" in self._SRC


# ─── 发射器契约统一面（2026-10-08：edb_templates emit_* spec → adapter 直通）──
#
# 正本裁定：以发射器实际产出为契约基准（emit_branchline_spec /
# emit_power_divider_spec 实跑样例）。本节双向钉：
# ① 发射样例 → spec_to_config_json 零错，且与发射器自产 assemble_config
#    逐键一致（唯一豁免 setups[0]["name"]：发射器字面 "setup1" vs 适配器
#    缺省 "hfss_setup_1"，纯命名差异零 pyedb 语义）；
# ② 发射样例 → build() 全链（假 pyedb 零真调）零错 + 关键 EDB 调用序列断言
#    （功分器隔离电阻 RLC 落地复用他席 _translate_resistors 面）。


def _emit_samples() -> dict[str, tuple[dict, dict]]:
    """两族发射器实跑样例（正本；发射器纯函数，可重复调用）。"""
    from rfauto.adapters.edb_templates import (
        emit_branchline_spec,
        emit_power_divider_spec,
    )

    return {
        "edb_branchline": emit_branchline_spec({"f0_ghz": 2.4}),
        "edb_power_divider": emit_power_divider_spec({"f0_ghz": 2.4}),
    }


def _family_stackup() -> dict:
    """发射族同构最小层叠（GND/SUB/TOP，介质走 material_props 派生面）。"""
    return {"layers": [
        {"name": "G", "type": "signal", "thickness_mm": 0.035},
        {"name": "S", "type": "dielectric", "thickness_mm": 0.254,
         "material_props": {"er": 3.66}},
        {"name": "T", "type": "signal", "thickness_mm": 0.035},
    ]}


def _wave_spec(**port_extra) -> dict:
    """单走线 + 单 wave_port 最小 spec（port_extra 逐键并入端口）。"""
    port = {"name": "P1", "port_nr": 1, "type": "wave_port", "trace": "tl",
            "point_mm": [5.0, 0.0]}
    port.update(port_extra)
    return {
        "stackup": _family_stackup(),
        "traces": [{"name": "tl", "layer": "T", "width_mm": 0.3,
                    "path_mm": [[0.0, 0.0], [5.0, 0.0]], "net": "RF"}],
        "ports": [port],
    }


class TestEmitterSpecContract:
    """发射样例（正本）→ adapter 校验/翻译直通零错 + 双路径 config 一致。"""

    def test_emitter_spec_translates_zero_error(self):
        """任务书契约测试①：发射样例 → adapter 内部 spec 校验直通零错，
        元段（template/schema_version/units/params）跳过零产出。"""
        for template, (spec, _emitter_cfg) in _emit_samples().items():
            cfg = spec_to_config_json(spec)
            for meta in ("template", "schema_version", "units", "params"):
                assert meta not in cfg, (template, meta)
            assert set(cfg) == {"stackup", "modeler", "ports", "setups",
                                "boundaries"}, template
            assert cfg["modeler"]["traces"]  # 走线全量翻译

    def test_adapter_config_matches_emitter_assemble_config(self):
        """契约统一最强钉：同 spec 双路径 config 逐键相等（唯一豁免
        setups[0]["name"]，见本节头注）。"""
        for (spec, emitter_cfg) in _emit_samples().values():
            cfg = spec_to_config_json(spec)
            expected = copy.deepcopy(emitter_cfg)
            expected["setups"][0]["name"] = "hfss_setup_1"
            assert cfg == expected

    def test_emitter_meta_validated_then_skipped(self):
        spec, _ = _emit_samples()["edb_branchline"]
        spec_to_config_json(spec)  # 元段齐备不报错
        bad = copy.deepcopy(spec)
        bad["units"] = {"length": "mil", "frequency": "GHz"}
        with pytest.raises(EdbSpecError, match="units"):
            spec_to_config_json(bad)
        bad2 = copy.deepcopy(spec)
        bad2["schema_version"] = 2
        with pytest.raises(EdbSpecError, match="schema_version"):
            spec_to_config_json(bad2)
        bad3 = copy.deepcopy(spec)
        bad3["params"] = [1, 2]
        with pytest.raises(EdbSpecError, match="params"):
            spec_to_config_json(bad3)
        bad4 = copy.deepcopy(spec)
        bad4["template"] = ""
        with pytest.raises(EdbSpecError, match="template"):
            spec_to_config_json(bad4)

    def test_explicit_materials_passthrough(self):
        """stackup.materials 显式段直通 config（铜 conductivity+介质 er/tanD）。"""
        spec, _ = _emit_samples()["edb_branchline"]
        cfg = spec_to_config_json(spec)
        assert cfg["stackup"]["materials"] == spec["stackup"]["materials"]

    def test_materials_whitelist_and_duplicate_fail_fast(self):
        stackup = {"materials": [{"name": "m1", "permittivity": 3.66}],
                   "layers": _family_stackup()["layers"]}
        spec = {"stackup": stackup,
                "board": {"lower_left_mm": [0.0, 0.0], "upper_right_mm": [1.0, 1.0]}}
        cfg = spec_to_config_json(spec)
        # 显式段在前、material_props 派生（S_material）追加在后
        assert cfg["stackup"]["materials"][0] == {"name": "m1",
                                                  "permittivity": 3.66}
        assert cfg["stackup"]["materials"][1]["name"] == "S_material"
        # 未知属性键 fail-fast（CfgMaterial 白名单外）
        bad = copy.deepcopy(spec)
        bad["stackup"]["materials"][0]["er"] = 3.66  # er 是层 props 键非材料键
        with pytest.raises(EdbSpecError, match="不接受材料属性键 'er'"):
            spec_to_config_json(bad)
        # 显式段内同名
        dup = copy.deepcopy(spec)
        dup["stackup"]["materials"].append({"name": "m1", "conductivity": 1.0})
        with pytest.raises(EdbSpecError, match="'m1' 重复"):
            spec_to_config_json(dup)
        # 显式段 vs 层 material_props 派生名冲突
        clash = {"stackup": {"materials": [{"name": "S_material",
                                            "permittivity": 3.0}],
                             "layers": _family_stackup()["layers"]}}
        with pytest.raises(EdbSpecError, match="'S_material' 重复"):
            spec_to_config_json(clash)

    def test_board_to_ground_plane_and_boundaries(self):
        """board → GND_plane 整版矩形（落 layers[0]、mm→米）+ 开放域辐射边界，
        与发射器 assemble_config 逐键同款。"""
        for (spec, emitter_cfg) in _emit_samples().values():
            cfg = spec_to_config_json(spec)
            assert cfg["modeler"]["planes"] == emitter_cfg["modeler"]["planes"]
            (plane,) = cfg["modeler"]["planes"]
            x0, y0 = spec["board"]["lower_left_mm"]
            x1, y1 = spec["board"]["upper_right_mm"]
            assert plane == {"name": "GND_plane", "layer": "GND",
                             "net_name": "GND", "type": "rectangle",
                             "lower_left_point": [x0 * 1e-3, y0 * 1e-3],
                             "upper_right_point": [x1 * 1e-3, y1 * 1e-3]}
            assert cfg["boundaries"] == {"use_open_region": True,
                                         "open_region_type": "radiation"}

    def test_no_board_keeps_legacy_behavior(self):
        """无 board 段（通用 spec）：零 planes、零 boundaries（行为零变化）。"""
        cfg = spec_to_config_json(_base_spec())
        assert "planes" not in cfg.get("modeler", {})
        assert "boundaries" not in cfg

    def test_board_validation_fail_fast(self):
        ok = {"stackup": _family_stackup(),
              "board": {"lower_left_mm": [0.0, 0.0], "upper_right_mm": [10.0, 8.0]}}
        cfg = spec_to_config_json(ok)
        assert cfg["modeler"]["planes"][0]["layer"] == "G"
        rev = copy.deepcopy(ok)
        rev["board"] = {"lower_left_mm": [5.0, 0.0], "upper_right_mm": [1.0, 8.0]}
        with pytest.raises(EdbSpecError, match="角点"):
            spec_to_config_json(rev)
        unk = copy.deepcopy(ok)
        unk["board"]["height_mm"] = 1.0
        with pytest.raises(EdbSpecError, match="不接受键 'height_mm'"):
            spec_to_config_json(unk)
        # 地板载体层（stackup.layers[0]）须 signal 层
        dia_first = copy.deepcopy(ok)
        dia_first["stackup"]["layers"] = [
            {"name": "S", "type": "dielectric", "thickness_mm": 0.254,
             "material_props": {"er": 3.66}},
            {"name": "T", "type": "signal", "thickness_mm": 0.035}]
        with pytest.raises(EdbSpecError, match="signal 层"):
            spec_to_config_json(dia_first)

    def test_wave_port_extent_factors_passthrough(self):
        port = spec_to_config_json(_wave_spec(
            horizontal_extent_factor=7, vertical_extent_factor=4))["ports"][0]
        assert port == {"name": "P1", "type": "wave_port",
                        "primitive_name": "tl", "point_on_edge": [0.005, 0.0],
                        "horizontal_extent_factor": 7,
                        "vertical_extent_factor": 4,
                        "pec_launch_width": "0.01mm"}

    def test_wave_port_defaults_impedance_and_extents(self):
        """缺省：extent 5/3（CfgEdgePort 官方缺省）、阻抗缺省 50。"""
        port = spec_to_config_json(_wave_spec())["ports"][0]
        assert port["horizontal_extent_factor"] == 5
        assert port["vertical_extent_factor"] == 3
        spec = _wave_spec(impedance=50)  # int 50 亦收（数值=50 口径）
        spec_to_config_json(spec)

    def test_wave_port_rejects_unknown_trace(self):
        with pytest.raises(EdbSpecError, match="引用不存在走线 'nope'"):
            spec_to_config_json(_wave_spec(trace="nope"))

    def test_wave_port_rejects_non50_impedance(self):
        with pytest.raises(EdbSpecError, match="硬编码"):
            spec_to_config_json(_wave_spec(impedance=75.0))

    def test_wave_port_rejects_unknown_key_and_missing_name(self):
        with pytest.raises(EdbSpecError, match="不接受键 'number'"):
            spec_to_config_json(_wave_spec(number=1))  # circuit 形态键不混用
        spec = _wave_spec()
        del spec["ports"][0]["name"]
        with pytest.raises(EdbSpecError, match="'name'"):
            spec_to_config_json(spec)

    def test_port_nr_unique_across_forms(self):
        """port_nr 与 circuit number 同池查重（两形态混排不撞号）。"""
        spec = _wave_spec()
        spec["ports"].append({"number": 1, "layer": "T", "net": "RF",
                              "start": [0.0, 0.0],
                              "end": {"layer": "T", "point_mm": [0.0, 1.0]}})
        with pytest.raises(EdbSpecError, match="端口号 1 重复"):
            spec_to_config_json(spec)

    def test_mixed_circuit_and_wave_ports(self):
        """两形态同 spec 混用：wave_port 走 CfgEdgePort 面、circuit 走终端面。"""
        spec = _wave_spec()
        spec["ports"].append({"number": 2, "name": "p2", "layer": "T",
                              "net": "RF", "start": [0.0, 0.0],
                              "end": {"layer": "T", "point_mm": [0.0, 1.0],
                                      "net": "RF"}})
        ports = spec_to_config_json(spec)["ports"]
        assert [p["type"] for p in ports] == ["wave_port", "circuit"]
        assert ports[1]["positive_terminal"]["coordinates"] == {
            "layer": "T", "point": [0.0, 0.0], "net": "RF"}

    def test_emitter_sim_setup_maps_adaptive_and_sweep(self):
        """f0_ghz→自适应频点、sweep dict→单段 linear_count、adapt dict→
        单频自适应（与发射器 assemble_config 同式同键）。"""
        spec, emitter_cfg = _emit_samples()["edb_branchline"]
        setup = spec_to_config_json(spec)["setups"][0]
        assert setup == emitter_cfg["setups"][0] | {"name": "hfss_setup_1"}
        assert setup["adapt_type"] == "single"
        assert setup["single_frequency_adaptive_solution"] == {
            "adaptive_frequency": "2.4GHz", "max_passes": 20, "max_delta": 0.02}
        (sweep,) = setup["freq_sweep"]
        assert sweep == {"name": "sweep1", "type": "interpolation",
                         "frequencies": [{"start": "1.68GHz", "stop": "3.12GHz",
                                          "increment": 401,
                                          "distribution": "linear_count"}]}

    def test_emitter_sim_setup_conflicts_fail_fast(self):
        stackup = _family_stackup()
        sweep = {"start_ghz": 1.0, "stop_ghz": 2.0, "points": 11}

        def _mk(extra):
            return {"stackup": stackup, "sim_setup": extra}

        with pytest.raises(EdbSpecError, match=r"'sweep'.*'sweeps'"):
            spec_to_config_json(_mk({"sweep": sweep, "sweeps": [
                {"type": "linear_count", "start_ghz": 1.0, "stop_ghz": 2.0,
                 "count": 11}]}))
        with pytest.raises(EdbSpecError, match="'sweep' 与通用形态简写键"):
            spec_to_config_json(_mk({"sweep": sweep, "f_start_ghz": 1.0}))
        with pytest.raises(EdbSpecError, match="'adapt' 与通用形态键"):
            spec_to_config_json(_mk({"sweep": sweep,
                                     "adapt": {"max_passes": 10},
                                     "max_passes": 5}))
        with pytest.raises(EdbSpecError, match="'f0_ghz' 与 'adaptive_freq_ghz'"):
            spec_to_config_json(_mk({"f0_ghz": 2.4, "adaptive_freq_ghz": 5.0}))
        with pytest.raises(EdbSpecError, match="仅 type=hfss"):
            spec_to_config_json(_mk({"type": "siwave_ac", "f0_ghz": 2.4}))
        with pytest.raises(EdbSpecError, match="'points'"):
            spec_to_config_json(_mk({"sweep": dict(sweep, points=1)}))
        with pytest.raises(EdbSpecError, match="不接受键 'count'"):
            spec_to_config_json(_mk({"sweep": dict(sweep, count=11)}))
        with pytest.raises(EdbSpecError, match="不得小于"):
            spec_to_config_json(_mk({"sweep": {"start_ghz": 2.0,
                                               "stop_ghz": 1.0}}))
        with pytest.raises(EdbSpecError, match="不接受键 'max_delta_s'"):
            spec_to_config_json(_mk({"sweep": sweep,
                                     "adapt": {"max_delta_s": 0.02}}))
        with pytest.raises(EdbSpecError, match="需配合扫频形态之一"):
            spec_to_config_json(_mk({"f0_ghz": 2.4,
                                     "adapt": {"max_passes": 10}}))

    def test_emitter_sim_setup_partial_forms(self):
        """发射族键可部分给：只给 sweep（无 f0/adapt）也成 setup（自适应走
        pyedb 官方缺省）；adapt 可只给其一键；f0 与 sweep 组合各归其位。"""
        stackup = _family_stackup()
        cfg = spec_to_config_json({"stackup": stackup, "sim_setup": {
            "sweep": {"start_ghz": 1.0, "stop_ghz": 2.0}}})
        setup = cfg["setups"][0]
        assert setup["freq_sweep"][0]["frequencies"][0]["increment"] == 401
        assert setup["single_frequency_adaptive_solution"][
            "adaptive_frequency"] == "5GHz"  # 无 f0 → pyedb 官方缺省
        cfg2 = spec_to_config_json({"stackup": stackup, "sim_setup": {
            "f0_ghz": 10.0,
            "sweep": {"start_ghz": 5.0, "stop_ghz": 15.0},
            "adapt": {"max_delta": 0.05}}})
        setup2 = cfg2["setups"][0]
        assert setup2["single_frequency_adaptive_solution"] == {
            "adaptive_frequency": "10GHz", "max_passes": 20, "max_delta": 0.05}
        assert setup2["freq_sweep"][0]["frequencies"][0] == {
            "start": "5GHz", "stop": "15GHz", "increment": 401,
            "distribution": "linear_count"}

    def test_string_format_10g_unified(self):
        """带单位字符串=%.10g（与 edb_templates.schema._fmt_mm 同式）——
        发射器全精度综合值（如 0.7*2.4=1.6800000000000002）双路径逐位一致。"""
        spec = {"stackup": {"layers": [{"name": "L", "type": "signal",
                                        "thickness_mm": 0.035}]},
                "traces": [{"layer": "L", "width_mm": 2.0 / 3.0,
                            "path_mm": [[0.0, 0.0], [1.0, 0.0]]}],
                "sim_setup": {"f0_ghz": 2.4,
                              "sweep": {"start_ghz": 0.7 * 2.4,
                                        "stop_ghz": 1.3 * 2.4, "points": 11}}}
        cfg = spec_to_config_json(spec)
        assert cfg["modeler"]["traces"][0]["width"] == f"{2.0 / 3.0:.10g}mm"
        fr = cfg["setups"][0]["freq_sweep"][0]["frequencies"][0]
        assert fr["start"] == f"{0.7 * 2.4:.10g}GHz"
        assert fr["stop"] == f"{1.3 * 2.4:.10g}GHz"


# ─── 发射样例 build 全链（假 pyedb：configuration+RLC 落地面全替身）──────────


class _FamilyConfiguration:
    def __init__(self, calls: list):
        self._calls = calls

    def load(self, config_file, append=True, apply_file=False, **kw):
        self._calls.append(("load", copy.deepcopy(config_file),
                            {"append": append, "apply_file": apply_file, **kw}))


class _FamilyRawTerminal:
    def __init__(self, calls: list, name: str):
        self._calls = calls
        self._name = name

    def SetRlcBoundaryParameters(self, rlc):
        self._calls.append(("SetRlcBoundaryParameters", self._name, rlc))


class _FamilyTerminal:
    def __init__(self, calls: list, name: str):
        self.name = name
        self.boundary_type = None
        self.reference_terminal = None
        self._edb_object = _FamilyRawTerminal(calls, name)


class _FamilyExcitation:
    def __init__(self, calls: list):
        self._calls = calls

    def create_point_terminal(self, x, y, layer, net, name=""):
        t = _FamilyTerminal(self._calls, name)
        self._calls.append(("create_point_terminal", x, y, layer, net, name, t))
        return t


class _FamilyRlc:
    def __init__(self) -> None:
        self.REnabled = self.LEnabled = self.CEnabled = self.R = None


class _FamilyUtility:
    def __init__(self, calls: list):
        self._calls = calls

    def Rlc(self):
        self._calls.append(("Utility.Rlc",))
        return _FamilyRlc()


class _FamilyCore:
    def __init__(self, calls: list):
        self.Utility = _FamilyUtility(calls)


class _FamilyEdb:
    """带 RLC 落地面的全功能假 Edb（configuration/excitation_manager/core）。"""

    def __init__(self, calls: list, **kw):
        calls.append(("Edb", kw))
        self._calls = calls
        self.configuration = _FamilyConfiguration(calls)
        self.excitation_manager = _FamilyExcitation(calls)
        self.core = _FamilyCore(calls)

    def edb_value(self, value):
        self._calls.append(("edb_value", value))
        return ("Value", value)

    def save_edb(self) -> bool:
        self._calls.append(("save",))
        return True

    def close_edb(self) -> bool:
        self._calls.append(("close",))
        return True


def _install_fake_pyedb_family(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    fake = types.ModuleType("pyedb")
    fake.Edb = lambda **kw: _FamilyEdb(calls, **kw)
    monkeypatch.setitem(sys.modules, "pyedb", fake)


class TestEmitterBuildChain:
    """发射样例 → build() 全链（假 pyedb 零真调）：零错 + 调用序列断言。"""

    def test_branchline_build_full_chain(self, tmp_path, monkeypatch):
        calls: list = []
        _install_fake_pyedb_family(monkeypatch, calls)
        spec, _ = _emit_samples()["edb_branchline"]
        result = EdbAdapter(tmp_path).build(spec)
        # 发射 spec 无 name 键 → 缺省文件名主干
        assert result.aedb_path.name == "edb_layout.aedb"
        assert result.config_json_path.name == "edb_layout_config.json"
        assert result.warnings == []
        # 无电阻 → 裸建库四步：Edb → load → save → close
        assert [c[0] for c in calls] == ["Edb", "load", "save", "close"]
        _, loaded, lkwa = next(c for c in calls if c[0] == "load")
        on_disk = json.loads(result.config_json_path.read_text(encoding="utf-8"))
        assert loaded == on_disk  # 注入与落盘存证同构
        assert lkwa["apply_file"] is True
        # 发射族面在注入 config 内齐备：4 wave_port + GND_plane + 开放域
        assert [p["type"] for p in loaded["ports"]] == ["wave_port"] * 4
        assert loaded["ports"][0]["horizontal_extent_factor"] == 5
        assert loaded["ports"][0]["vertical_extent_factor"] == 3
        assert [pl["name"] for pl in loaded["modeler"]["planes"]] == ["GND_plane"]
        assert loaded["boundaries"] == {"use_open_region": True,
                                        "open_region_type": "radiation"}

    def test_power_divider_build_full_chain_lands_isolation_resistor(
            self, tmp_path, monkeypatch):
        """功分器样例 → 全链零错；隔离电阻 RISO 经他席 _translate_resistors
        落地（点端子对 + 纯电阻 RLC 处方），时序 load < 端子 < save < close。"""
        calls: list = []
        _install_fake_pyedb_family(monkeypatch, calls)
        spec, _ = _emit_samples()["edb_power_divider"]
        result = EdbAdapter(tmp_path).build(spec)
        assert result.aedb_path.name == "edb_layout.aedb"
        order = [c[0] for c in calls]
        assert order[0] == "Edb"
        assert order.index("load") < order.index("create_point_terminal")
        assert order.index("create_point_terminal") < order.index("save")
        assert order.index("save") < order.index("close")
        # RISO 端子坐标=spec 几何逐字 mm→米、命名 {name}_p/{name}_ref
        created = [c for c in calls if c[0] == "create_point_terminal"]
        res = spec["resistors"][0]
        (x0, y0), (x1, y1) = res["path_mm"]
        assert [(c[1], c[2], c[3], c[4], c[5]) for c in created] == [
            (x0 * 1e-3, y0 * 1e-3, res["layer"], res["net"], "RISO_p"),
            (x1 * 1e-3, y1 * 1e-3, res["layer"], res["net"], "RISO_ref"),
        ]
        pos, ref = created[0][6], created[1][6]
        assert pos.boundary_type == "RlcBoundary"
        assert ref.boundary_type == "RlcBoundary"
        # 纯电阻处方（L/C 关断仅 R 使能）+ R=2·Z0=100Ω 逐字透传
        assert calls.count(("Utility.Rlc",)) == 1
        rlc = next(c[2] for c in calls if c[0] == "SetRlcBoundaryParameters")
        assert rlc.REnabled is True and rlc.LEnabled is False
        assert rlc.CEnabled is False
        assert ("edb_value", 100.0) in calls
        assert rlc.R == ("Value", 100.0)
        assert pos.reference_terminal is ref

    def test_emitter_build_config_matches_emitter_config_on_disk(
            self, tmp_path, monkeypatch):
        """build 落盘存证（配置 JSON）与发射器 assemble_config 逐键一致
        （setup 名豁免同契约测试）——存证即正本镜像。"""
        calls: list = []
        _install_fake_pyedb_family(monkeypatch, calls)
        spec, emitter_cfg = _emit_samples()["edb_power_divider"]
        result = EdbAdapter(tmp_path).build(spec)
        on_disk = json.loads(result.config_json_path.read_text(encoding="utf-8"))
        expected = copy.deepcopy(emitter_cfg)
        expected["setups"][0]["name"] = "hfss_setup_1"
        assert on_disk == expected


# ─── 3D Layout setup 自适应档写入通道（W8 仲裁建议 2，2026-10-09）────────────
#
# W8 实证（runs/edblane85/w8_cl_arb/ARBITRATION.md §2 V3/§5-2）：对已解
# 3D Layout 工程重载改档不传播——pyaedt props 无 AdaptiveSettings 子树，
# 子树重建写入+update+save 后批解仍逐位回放缓存解（S31 十位小数同值
# -9.4569、wall 26s vs 原档 ~52s）。因此改档走建模期写入
# （spec.sim_setup.adapt → configuration.load 落 setup），改档须重建；
# 配套写入一致断言 verify_adapt_tightening（批解后重开工程读回 setup
# max_delta 与存证请求档核对，不一致/不可核对=告警，best-effort 不抛异常）。
#
# W9 勘误 + W10 定谳（runs/edblane85/w9_cl_recheck 与 w10_cl_recheck）：
# 本节单测验证的是**请求值达 configuration.load 的写入面**，非"求解按
# 新档收敛"的行为效力——W9 真机 props 建库期写入 0.005 读回确认后批解
# 仍按 0.02 准则停机（TIGHTENING_NOT_EFFECTIVE）；W10 定谳：EDB 3D
# Layout schema（SimSetupID=19）无 MaxDelta 键=写入不可达（四互证），
# EDB 侧唯一可达收紧通道=MinConvergedPasses 扁平键（求解器实消费）；
# coupled_line 缺省档已按 W10 定谳回退 0.02（史值 0.005 见发射器
# DEFAULT_ADAPT_MAX_DELTA 注释）。


class _AdaptEntry:
    """假 AdaptiveFrequencyData（pyedb 只读读回面三属性替身）。"""

    def __init__(self, adaptive_frequency: str, max_delta: float,
                 max_passes: int = 20):
        self.adaptive_frequency = adaptive_frequency
        self.max_delta = max_delta
        self.max_passes = max_passes


class _AdaptSettings:
    def __init__(self, entries: list):
        self.adaptive_frequency_data_list = entries


class _VerifySetup:
    def __init__(self, entries: list):
        self.adaptive_settings = _AdaptSettings(entries)


def _install_fake_pyedb_verify(monkeypatch: pytest.MonkeyPatch, calls: list,
                               setups: object | None, *,
                               setups_raises: Exception | None = None,
                               edb_init_raises: Exception | None = None,
                               without_setups_attr: bool = False) -> None:
    """假 pyedb：Edb 实例带 setups 只读集合（verify 读回面替身）。

    setups：dict（正常读回）；setups_raises 非空时属性读抛异常（读回链
    断裂路径）；without_setups_attr 时实例无该属性（版本兼容路径）；
    edb_init_raises 非空时 Edb 构造即抛（重开失败路径）。
    """
    fake = types.ModuleType("pyedb")

    def _edb_cls(**kw):
        calls.append(("Edb", kw))
        if edb_init_raises is not None:
            raise edb_init_raises

        class _E:
            if not without_setups_attr:
                @property
                def setups(self):
                    if setups_raises is not None:
                        raise setups_raises
                    return setups() if callable(setups) else setups

            def close_edb(self):
                calls.append(("close",))
                return True

        return _E()

    fake.Edb = _edb_cls
    monkeypatch.setitem(sys.modules, "pyedb", fake)


def _adapt_config(max_delta: float = 0.005, freq: str = "2.4GHz",
                  name: str = "setup1", passes: int = 20) -> dict:
    """最小请求存证 config（hfss 单频自适应，build() 落盘形态同构）。"""
    return {"setups": [{
        "name": name, "type": "hfss", "adapt_type": "single",
        "single_frequency_adaptive_solution": {
            "adaptive_frequency": freq, "max_passes": passes,
            "max_delta": max_delta},
    }]}


def _make_result(tmp_path: Path, config: dict) -> EdbBuildResult:
    """手写 build 产物（config 存证落盘 + aedb 路径配对）。"""
    cfg_path = tmp_path / "demo_config.json"
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return EdbBuildResult(aedb_path=tmp_path / "demo.aedb",
                          config_json_path=cfg_path)


class TestAdaptTighteningChannel:
    """建议 1/2 联动：发射器缺省档建模期写入（写入通道验证：值达
    configuration.load；求解行为效力不在单测面，W9 勘误+W10 定谳见文件
    头）+ verify_adapt_tightening 写入一致断言（match/mismatch/不可核对
    全谱）。"""

    # ── 建模期写入通道（缺省档 → 建议 2 写入路径）─────────────────────────

    def test_coupled_line_default_tightened_flows_through_build(
            self, tmp_path, monkeypatch):
        """coupled_line 缺省档 0.02（W10 定谳回退值）逐级落：emit →
        spec_to_config_json → build 注入 config（与落盘存证同构）——发射
        器改档即随建库写入请求档，无需求解后干预（W8 建议 2 的主修法路
        径写入面验证；W10 定谳 EDB 路径 MaxDelta 写入不可达见文件头）。"""
        calls: list = []
        _install_fake_pyedb_family(monkeypatch, calls)
        from rfauto.adapters.edb_templates import emit_coupled_line_spec

        spec, _ = emit_coupled_line_spec({"f0_ghz": 2.4})
        cfg = spec_to_config_json(spec)
        sol = cfg["setups"][0]["single_frequency_adaptive_solution"]
        assert sol["max_delta"] == 0.02
        result = EdbAdapter(tmp_path).build(spec)
        _, loaded, _lkwa = next(c for c in calls if c[0] == "load")
        assert loaded["setups"][0]["single_frequency_adaptive_solution"][
            "max_delta"] == 0.02
        on_disk = json.loads(result.config_json_path.read_text(encoding="utf-8"))
        assert on_disk == loaded  # 存证=注入同一 dict（请求正本可回放）

    def test_coupled_line_explicit_override_flows_through(
            self, tmp_path, monkeypatch):
        """显式覆盖档原样透传建模期通道（0.01 请求 → config 0.01；覆盖值
        取非缺省 0.02 的 0.01 保证透传断言有区分度）。"""
        calls: list = []
        _install_fake_pyedb_family(monkeypatch, calls)
        from rfauto.adapters.edb_templates import emit_coupled_line_spec

        spec, _ = emit_coupled_line_spec(
            {"f0_ghz": 2.4, "adapt": {"max_delta": 0.01}})
        assert spec_to_config_json(spec)["setups"][0][
            "single_frequency_adaptive_solution"]["max_delta"] == 0.01
        EdbAdapter(tmp_path).build(spec)
        _, loaded, _ = next(c for c in calls if c[0] == "load")
        assert loaded["setups"][0]["single_frequency_adaptive_solution"][
            "max_delta"] == 0.01

    def test_module_docstring_declares_rebuild_channel(self):
        """「改档须重建」声明在案（建议 2 的 docstring 落地面，W8 证据
        链可回溯：ARBITRATION/AdaptiveSettings/断言入口三要素）。"""
        doc = ea.__doc__ or ""
        assert "改档须重建" in doc
        assert "AdaptiveSettings" in doc
        assert "verify_adapt_tightening" in doc
        assert "W8 仲裁档" in doc

    # ── 生效断言：一致/不一致/不可核对全谱 ─────────────────────────────────

    def test_verify_match_returns_empty_and_reopens_readonly(
            self, tmp_path, monkeypatch):
        """读回=请求 → 空告警；重开是只读会话且释放（#265）。"""
        calls: list = []
        _install_fake_pyedb_verify(
            monkeypatch, calls,
            setups={"setup1": _VerifySetup([_AdaptEntry("2.4GHz", 0.005)])})
        result = _make_result(tmp_path, _adapt_config(max_delta=0.005))
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert warnings_out == []
        kw = calls[0][1]
        assert kw["isreadonly"] is True
        assert [c[0] for c in calls] == ["Edb", "close"]  # 读回后必须释放

    def test_verify_float_roundtrip_tolerance(self, tmp_path, monkeypatch):
        """max_delta double 往返量化噪声（1e-12 级）不误报（eps 家法）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [],
            setups={"setup1": _VerifySetup(
                [_AdaptEntry("2.4GHz", 0.005 + 1e-12)])})
        result = _make_result(tmp_path, _adapt_config(max_delta=0.005))
        assert EdbAdapter(tmp_path).verify_adapt_tightening(result) == []

    def test_verify_mismatch_warns_with_rebuild_hint(
            self, tmp_path, monkeypatch):
        """读回≠请求 → 告警带双值+改档须重建指引（W8 收紧不传播实证），
        并带 W10 定谳补注（EDB schema 无 MaxDelta 键、重建亦不落库）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [],
            setups={"setup1": _VerifySetup([_AdaptEntry("2.4GHz", 0.02)])})
        result = _make_result(tmp_path, _adapt_config(max_delta=0.005))
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1
        msg = warnings_out[0]
        assert "setup1" in msg and "不一致" in msg
        assert "0.005" in msg and "0.02" in msg
        assert "改档须重建" in msg
        assert "W10" in msg and "不可达" in msg

    def test_verify_multi_freq_matches_by_frequency(
            self, tmp_path, monkeypatch):
        """多频点条目按 adaptive_frequency 匹配请求频点（他频点不误报）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [],
            setups={"setup1": _VerifySetup([
                _AdaptEntry("1.2GHz", 0.02),
                _AdaptEntry("2.4GHz", 0.005),
            ])})
        result = _make_result(tmp_path, _adapt_config(
            max_delta=0.005, freq="2.4GHz"))
        assert EdbAdapter(tmp_path).verify_adapt_tightening(result) == []
        # 请求频点缺席 → 不猜对档，如实告警
        result2 = _make_result(tmp_path, _adapt_config(
            max_delta=0.005, freq="3.6GHz"))
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result2)
        assert len(warnings_out) == 1 and "未在读回频点表" in warnings_out[0]

    def test_verify_setup_missing_warns(self, tmp_path, monkeypatch):
        """请求 setup 在工程内无同名读回 → 告警点名（请求档未落库嫌疑）。"""
        _install_fake_pyedb_verify(monkeypatch, [], setups={})
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1
        assert "无同名 setup" in warnings_out[0]

    def test_verify_no_request_is_vacuous(self, tmp_path, monkeypatch):
        """存证无 hfss 单频自适应请求 → 空告警且不触 pyedb（vacuous 真）。"""
        calls: list = []
        _install_fake_pyedb_verify(monkeypatch, calls, setups={})
        result = _make_result(tmp_path, {"stackup": {"layers": []}})
        assert EdbAdapter(tmp_path).verify_adapt_tightening(result) == []
        assert calls == []  # 无请求无读回（零副作用）

    def test_verify_corrupt_config_warns_not_raises(self, tmp_path, monkeypatch):
        """存证缺失/损坏 → 告警不冒充核对通过（#122），不触 pyedb。"""
        calls: list = []
        _install_fake_pyedb_verify(monkeypatch, calls, setups={})
        result = EdbBuildResult(
            aedb_path=tmp_path / "demo.aedb",
            config_json_path=tmp_path / "ghost_config.json")  # 不存在
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1 and "不可核对" in warnings_out[0]
        assert calls == []

    def test_verify_pyedb_missing_warns_not_raises(
            self, tmp_path, monkeypatch):
        """pyedb 缺装 → 告警不抛（best-effort 断言，#105）。"""
        monkeypatch.setitem(sys.modules, "pyedb", None)
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1 and "pyedb 不可用" in warnings_out[0]

    def test_verify_edb_open_failure_warns(self, tmp_path, monkeypatch):
        """重开工程失败（锁/损坏）→ 告警不抛（#105）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [], setups={},
            edb_init_raises=RuntimeError("project locked"))
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1
        assert "重开工程失败" in warnings_out[0]

    def test_verify_setups_readback_failure_warns_and_closes(
            self, tmp_path, monkeypatch):
        """setups 读回抛异常 → 告警含异常摘要，且 close 仍执行（finally）。"""
        calls: list = []
        _install_fake_pyedb_verify(
            monkeypatch, calls, setups=None,
            setups_raises=RuntimeError("boom"))
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1
        assert "读回失败" in warnings_out[0] and "boom" in warnings_out[0]
        assert [c[0] for c in calls] == ["Edb", "close"]

    def test_verify_setups_attr_missing_warns(self, tmp_path, monkeypatch):
        """实例无 setups 属性（版本兼容）→ 不可核对告警（#122 不冒充）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [], setups=None, without_setups_attr=True)
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1 and "不可核对" in warnings_out[0]

    def test_verify_siwave_style_setup_without_adapt_warns(
            self, tmp_path, monkeypatch):
        """读回 setup 缺自适应频点数据 → 告警（请求档未落库嫌疑）。"""
        _install_fake_pyedb_verify(
            monkeypatch, [],
            setups={"setup1": _VerifySetup([])})
        result = _make_result(tmp_path, _adapt_config())
        warnings_out = EdbAdapter(tmp_path).verify_adapt_tightening(result)
        assert len(warnings_out) == 1 and "无自适应频点数据" in warnings_out[0]
