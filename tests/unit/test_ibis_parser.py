"""IBIS (.ibs) 解析内核单测（aurora_q Q-X46 席位，2026-11-07）。

覆盖面（任务书 ≥20 条之解析内核半边）：
- 夹具正例：头部 keyword、component/manufacturer、Package 三列
  （单位换算基准单位）、Pin 表（GND/VDD/NC 行+RLC 引脚+选择器引用）、
  Model Selector、Model 子参数（Model_type/Polarity/Enable/Vinl/
  Vmeas/C_comp/Voltage_range/*_reference）、四张 IV 查找表、Ramp
  （``key = value`` 与三列两形态）、Rising/Falling Waveform（元参数+
  数据列）；
- 单位词法：V/mA/uA/nH/pF/n 前缀换算基准单位、"/V" 比值形态直通、
  未知后缀报错；
- 插值：interp_iv 内点手算锚+越界夹取+corner 列、interp_waveform 内点
  手算锚、单点表、非递增轴报错、缺 corner 列报错；
- 结构化输出：include_tables=False 剪表体（元数据保留）、warnings
  回显（未识别 keyword 零静默丢弃）、多 component 扁平 pins 视图；
- 负例：缺 Model_type/缺 [End]/[End] 后内容/IV 行列数错/列数不一致/
  IV 表在 [Model] 外/[Package]/[Pin] 在 [Component] 前/重复模型名/
  重复 pin/波形缺 V_fixture/顶层裸数据行/未知单位后缀——全部
  IbisParseError 断言。

单测零网络零真机零写盘（夹具只读；负例用内联字符串）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.ibis_parser import (
    IbisParseError,
    extract_ibis,
    interp_iv,
    interp_waveform,
    parse_ibis,
    parse_quantity,
    try_quantity,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ibis" / "sample.ibs"


@pytest.fixture(scope="module")
def file_tree():
    return parse_ibis(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data(file_tree) -> dict:
    return extract_ibis(file_tree)


# ── 头部/器件/封装 ──────────────────────────────────────────────────────────


class TestHeaderComponent:
    def test_header_keywords(self, data: dict) -> None:
        assert data["header"]["ibis_ver"] == "3.2"
        assert data["header"]["file_name"] == "sample.ibs"
        assert data["header"]["file_rev"] == "1.1"
        assert data["header"]["date"] == "2026-11-07"
        assert data["header"]["source"] == "rfauto fixture"
        assert "manufacturer" not in data["header"]  # 器件级 Manufacturer 不落头

    def test_component_inventory(self, data: dict) -> None:
        assert len(data["components"]) == 1
        comp = data["components"][0]
        assert comp["name"] == "SAMPLE_SOC"
        assert comp["manufacturer"] == "rfauto"

    def test_package_triples_base_units(self, data: dict) -> None:
        pkg = data["components"][0]["package"]
        assert pkg["r_pkg"] == {"typ": 4.5, "min": 3.8, "max": 5.2}
        # 单位乘子换算走浮点乘法——pytest.approx 元素级（ulp 容差）
        assert pkg["l_pkg"] == pytest.approx(
            {"typ": 2.1e-9, "min": 1.8e-9, "max": 2.4e-9})
        assert pkg["c_pkg"] == pytest.approx(
            {"typ": 1.1e-12, "min": 0.9e-12, "max": 1.3e-12})
        assert pkg["attrs"] == {}

    def test_pins_flat_view(self, data: dict) -> None:
        assert set(data["pins"]) == {"1", "2", "3", "4", "5", "6"}

    def test_pin_power_ground_rows_no_model(self, data: dict) -> None:
        gnd = data["pins"]["1"]
        assert gnd["signal"] == "GND"
        assert gnd["model"] is None
        assert gnd["r_pin"] is None
        assert data["pins"]["6"]["signal"] == "NC"

    def test_pin_full_rlc_row(self, data: dict) -> None:
        p3 = data["pins"]["3"]
        assert p3["signal"] == "IO_A0"
        assert p3["model"] == "PD_MODEL"
        assert p3["r_pin"] == 0.30
        assert p3["l_pin"] == pytest.approx(1.1e-9)
        assert p3["c_pin"] == pytest.approx(0.6e-12)

    def test_pin_selector_reference(self, data: dict) -> None:
        # pin 4 的 model 列引用 Model Selector 名（IBIS 合法形态）
        assert data["pins"]["4"]["model"] == "IO_SEL"

    def test_model_selector_entries(self, data: dict) -> None:
        sel = data["model_selectors"]["IO_SEL"]
        assert [row["model"] for row in sel] == ["IO_FAST", "IO_SLOW"]
        assert sel[0]["comment"] == "Fast corner output model"

    def test_unknown_keyword_warning_not_fatal(self, data: dict) -> None:
        # [OEM] 超出解析面 → warning 如实回显，解析不炸、内容零静默丢弃
        assert len(data["warnings"]) == 1
        assert "OEM" in data["warnings"][0]


# ── Model 子参数 ────────────────────────────────────────────────────────────


class TestModelAttrs:
    def test_model_inventory(self, data: dict) -> None:
        assert set(data["models"]) == {"PD_MODEL", "IO_FAST", "IO_SLOW"}

    def test_model_type_and_polarity(self, data: dict) -> None:
        pd = data["models"]["PD_MODEL"]
        assert pd["model_type"] == "Input"
        assert pd["polarity"] is None  # 缺失如实 None
        fast = data["models"]["IO_FAST"]
        assert fast["model_type"] == "Output"
        assert fast["polarity"] == "Non-Inverting"
        assert fast["enable"] == "Active-High"

    def test_threshold_scalars_base_units(self, data: dict) -> None:
        fast = data["models"]["IO_FAST"]
        assert fast["vinl"] == 0.8
        assert fast["vinh"] == 2.0
        assert fast["vmeas"] == 1.65

    def test_c_comp_triple(self, data: dict) -> None:
        assert data["models"]["PD_MODEL"]["c_comp"] == {
            "typ": 1.8e-12, "min": 1.5e-12, "max": 2.1e-12}

    def test_voltage_range_triple(self, data: dict) -> None:
        assert data["models"]["IO_FAST"]["voltage_range"] == {
            "typ": 3.3, "min": 3.0, "max": 3.6}
        assert data["models"]["PD_MODEL"]["voltage_range"] is None

    def test_reference_promotion(self, data: dict) -> None:
        refs = data["models"]["IO_FAST"]["references"]
        assert refs == {"gnd_clamp_reference": 0.0,
                        "power_clamp_reference": 3.3}
        assert "gnd_clamp_reference" not in data["models"]["IO_FAST"]["attrs"]
        assert data["models"]["PD_MODEL"]["references"] == {
            "gnd_clamp_reference": 0.0}


# ── IV 查找表 ───────────────────────────────────────────────────────────────


class TestIvTables:
    def test_table_presence_map(self, data: dict) -> None:
        # PD_MODEL 只有 GND clamp；IO_FAST 三张；IO_SLOW 只有 pulldown
        assert [k for k, v in data["models"]["PD_MODEL"]["tables"].items()
                if v is not None] == ["gnd_clamp"]
        assert [k for k, v in data["models"]["IO_FAST"]["tables"].items()
                if v is not None] == ["pullup", "pulldown", "power_clamp"]
        assert [k for k, v in data["models"]["IO_SLOW"]["tables"].items()
                if v is not None] == ["pulldown"]

    def test_pulldown_columns_exact(self, data: dict) -> None:
        t = data["models"]["IO_FAST"]["tables"]["pulldown"]
        assert t["kind"] == "pulldown"
        assert t["n_rows"] == 7
        assert t["voltage"] == [-1.5, -0.5, 0.0, 0.5, 1.65, 3.3, 3.6]
        # mA/uA 乘子换算列走 approx 元素级（ulp 容差）
        assert t["typ"] == pytest.approx(
            [-0.105, -0.038, 0.0, 0.039, 0.0615, 0.0745, 0.078])
        assert t["min"] == pytest.approx(
            [-0.095, -0.033, 0.0, 0.034, 0.055, 0.066, 0.069])
        assert t["max"] == pytest.approx(
            [-0.115, -0.043, 0.0, 0.044, 0.068, 0.083, 0.087])

    def test_microamp_conversion(self, data: dict) -> None:
        # GND clamp 0.35V 行 0.9uA → 9e-7 A（基准单位）
        t = data["models"]["PD_MODEL"]["tables"]["gnd_clamp"]
        assert t["typ"][3] == 0.9e-6
        assert t["voltage"][3] == 0.35

    def test_pullup_negative_microamp_row(self, data: dict) -> None:
        t = data["models"]["IO_FAST"]["tables"]["pullup"]
        assert t["max"][-1] == -8.0e-6

    def test_ramp_two_forms(self, data: dict) -> None:
        ramp = data["models"]["IO_FAST"]["ramp"]
        assert ramp["ramp_load"] == 50.0  # "Ramp_load = 50 Ohm"（值含空格单位）
        assert ramp["ramp_dr"] == {"typ": 2.24, "min": 2.05, "max": 2.43}
        assert ramp["ramp_df"] == {"typ": 2.18, "min": 1.99, "max": 2.37}

    def test_ramp_absent_model_none(self, data: dict) -> None:
        assert data["models"]["IO_SLOW"]["ramp"] is None


# ── 暂态表 ──────────────────────────────────────────────────────────────────


class TestWaveforms:
    def test_waveform_inventory(self, data: dict) -> None:
        fast = data["models"]["IO_FAST"]["waveforms"]
        slow = data["models"]["IO_SLOW"]["waveforms"]
        assert [w["kind"] for w in fast] == ["rising", "falling"]
        assert [w["kind"] for w in slow] == ["rising"]

    def test_rising_meta_flattened(self, data: dict) -> None:
        w = data["models"]["IO_FAST"]["waveforms"][0]
        assert w["r_dut"] == 50.0
        assert w["c_dut"] == 1e-11
        assert w["l_dut"] == 1e-9
        assert w["v_fixture"] == 3.3
        assert w["v_fixture_min"] == 3.0
        assert w["v_fixture_max"] == 3.6

    def test_falling_meta_optional_corners_absent(self, data: dict) -> None:
        w = data["models"]["IO_FAST"]["waveforms"][1]
        assert w["v_fixture"] == 3.3
        assert "v_fixture_min" not in w
        assert "v_fixture_max" not in w

    def test_rising_columns_exact(self, data: dict) -> None:
        w = data["models"]["IO_FAST"]["waveforms"][0]
        assert w["time"] == [0.0, 0.5e-9, 1e-9, 2e-9, 4e-9, 8e-9]
        assert w["typ"][2] == 1.94
        assert w["min"][1] == 0.52
        assert w["max"][-1] == 3.387

    def test_n_rows_counts(self, data: dict) -> None:
        fast = data["models"]["IO_FAST"]["waveforms"]
        slow = data["models"]["IO_SLOW"]["waveforms"]
        assert all(w["n_rows"] == 6 for w in fast)
        assert slow[0]["n_rows"] == 4


# ── 数量词法 ────────────────────────────────────────────────────────────────


class TestQuantity:
    def test_unit_suffixes_base_units(self) -> None:
        assert parse_quantity("3.3V", "") == 3.3
        # 乘子换算列 approx（浮点 ulp 容差），乘子 1.0 列恒精确
        assert parse_quantity("-50.0mA", "") == pytest.approx(-0.05)
        assert parse_quantity("0.9uA", "") == pytest.approx(9e-7)
        assert parse_quantity("2.10nH", "") == pytest.approx(2.1e-9)
        assert parse_quantity("1.10pF", "") == pytest.approx(1.1e-12)
        assert parse_quantity("10.0n", "") == 1e-8  # 裸 n 前缀（IBIS 时间惯例）
        assert parse_quantity("50.0 Ohm", "") == 50.0  # 数字与单位间空格
        assert parse_quantity("3.30", "") == 3.3
        assert parse_quantity("1.0E-3A", "") == pytest.approx(1e-3)

    def test_ratio_suffix_passthrough(self) -> None:
        # Ramp_dR "-2.228/V" 比值形态：量值直通、不猜单位
        assert parse_quantity("-2.228/V", "") == -2.228
        assert try_quantity("-2.228/V") == -2.228

    def test_unknown_suffix_rejected(self) -> None:
        with pytest.raises(IbisParseError, match="未知单位后缀"):
            parse_quantity("5.0QQ", "")

    def test_non_quantity_none(self) -> None:
        assert try_quantity("Output") is None
        assert try_quantity("Non-Inverting") is None
        assert try_quantity("Active-High") is None

    def test_three_column_string_not_one_quantity(self) -> None:
        # 三列串不得被首列吞成单数量（正则 $ 锚守卫）
        assert try_quantity("2.0pF 1.5pF 2.1pF") is None


# ── 插值（确定性内核，手算锚）───────────────────────────────────────────────


class TestInterp:
    def test_interp_iv_interior_hand_anchor(self, data: dict) -> None:
        # pulldown typ：0.0V→0.0A 与 0.5V→0.039A 中点 0.25V → 0.0195A
        t = data["models"]["IO_FAST"]["tables"]["pulldown"]
        assert interp_iv(t, 0.25) == pytest.approx(0.0195)

    def test_interp_iv_min_corner(self, data: dict) -> None:
        # min 列：0.0V→0.0A 与 0.5V→0.034A 中点 → 0.017A
        t = data["models"]["IO_FAST"]["tables"]["pulldown"]
        assert interp_iv(t, 0.25, corner="min") == pytest.approx(0.017)

    def test_interp_iv_clamps_outside(self, data: dict) -> None:
        t = data["models"]["IO_FAST"]["tables"]["pulldown"]
        assert interp_iv(t, -5.0) == -0.105
        assert interp_iv(t, 5.0) == 0.078

    def test_interp_iv_exact_node(self, data: dict) -> None:
        t = data["models"]["PD_MODEL"]["tables"]["gnd_clamp"]
        assert interp_iv(t, 0.35) == 0.9e-6

    def test_interp_waveform_interior_hand_anchor(self, data: dict) -> None:
        # rising typ：0.5ns→0.58V 与 1.0ns→1.94V 中点 0.75ns → 1.26V
        w = data["models"]["IO_FAST"]["waveforms"][0]
        assert interp_waveform(w, 0.75e-9) == pytest.approx(1.26)

    def test_interp_waveform_clamps(self, data: dict) -> None:
        w = data["models"]["IO_FAST"]["waveforms"][1]
        assert interp_waveform(w, -1.0) == 3.3
        assert interp_waveform(w, 100e-9) == 0.004

    def test_interp_bad_corner_rejected(self, data: dict) -> None:
        t = data["models"]["IO_FAST"]["tables"]["pulldown"]
        with pytest.raises(ValueError, match="corner"):
            interp_iv(t, 0.25, corner="mid")

    def test_interp_missing_min_column_rejected(self) -> None:
        # 两列形态（无 min/max）→ corner=min 如实 ValueError
        table = {"voltage": [0.0, 1.0], "typ": [0.0, 1.0]}
        with pytest.raises(ValueError, match="min"):
            interp_iv(table, 0.5, corner="min")

    def test_interp_non_ascending_axis_rejected(self) -> None:
        table = {"voltage": [1.0, 0.0], "typ": [1.0, 0.0]}
        with pytest.raises(ValueError, match="严格递增"):
            interp_iv(table, 0.5)

    def test_interp_single_row_table(self) -> None:
        table = {"voltage": [2.5], "typ": [7.25]}
        assert interp_iv(table, 0.0) == 7.25

    def test_interp_length_mismatch_rejected(self) -> None:
        table = {"voltage": [0.0, 1.0], "typ": [0.0]}
        with pytest.raises(ValueError, match="长度"):
            interp_iv(table, 0.5)


# ── 结构化输出裁面/多器件 ───────────────────────────────────────────────────


class TestExtractFaces:
    def test_include_tables_false_strips_bodies(self, file_tree) -> None:
        view = extract_ibis(file_tree, include_tables=False)
        m = view["models"]["IO_FAST"]
        assert "tables" not in m
        assert "waveforms" not in m
        assert "ramp" not in m
        assert m["model_type"] == "Output"  # 元数据保留
        assert view["pins"]["3"]["l_pin"] == pytest.approx(1.1e-9)

    def test_multi_component_flat_pins(self) -> None:
        text = (
            "[IBIS Ver] 3.2\n"
            "[Component] CHIP_A\n"
            "[Pin]\n"
            "1 GND\n"
            "2 IO_A  MA  0.1  1nH  0.5pF\n"
            "[Component] CHIP_B\n"
            "[Pin]\n"
            "1 VDD\n"
            "3 IO_B  MB\n"
            "[Model] MA\n"
            "Model_type Output\n"
            "[Model] MB\n"
            "Model_type Input\n"
            "[End]\n"
        )
        view = extract_ibis(parse_ibis(text))
        assert [c["name"] for c in view["components"]] == ["CHIP_A", "CHIP_B"]
        assert view["components"][0]["manufacturer"] is None
        assert set(view["pins"]) == {"1", "2", "3"}  # 同号 1 后者覆盖（docstring 口径）
        assert view["pins"]["1"]["signal"] == "VDD"
        assert view["pins"]["3"]["model"] == "MB"

    def test_file_level_manufacturer_into_header(self) -> None:
        text = (
            "[IBIS Ver] 3.2\n"
            "[Manufacturer] acme\n"
            "[Component] C1\n"
            "[Model] M\n"
            "Model_type Input\n"
            "[End]\n"
        )
        view = extract_ibis(parse_ibis(text))
        assert view["header"]["manufacturer"] == "acme"
        assert view["components"][0]["manufacturer"] is None


# ── 负例（IbisParseError 全家福）───────────────────────────────────────────


class TestParseErrors:
    def test_model_without_model_type(self) -> None:
        with pytest.raises(IbisParseError, match="Model_type"):
            parse_ibis("[Component] C\n[Model] M\nVinl = 0.8V\n[End]\n")

    def test_missing_end(self) -> None:
        with pytest.raises(IbisParseError, match="End"):
            parse_ibis("[Component] C\n[Model] M\nModel_type Input\n")

    def test_content_after_end(self) -> None:
        with pytest.raises(IbisParseError, match="End"):
            parse_ibis("[Component] C\n[Model] M\nModel_type Input\n"
                       "[End]\nstray\n")

    def test_iv_row_three_columns(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[GND Clamp]\n0.0V 1.0mA 2.0mA\n[End]\n")
        with pytest.raises(IbisParseError, match="2 或 4 列"):
            parse_ibis(text)

    def test_iv_row_column_count_inconsistent(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[Pulldown]\n0.0V 1.0mA\n0.5V 2.0mA 3.0mA 4.0mA\n[End]\n")
        with pytest.raises(IbisParseError, match="列数不一致"):
            parse_ibis(text)

    def test_iv_row_non_numeric_voltage(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[Pulldown]\nzero 1.0mA\n[End]\n")
        with pytest.raises(IbisParseError, match="非数量词"):
            parse_ibis(text)

    def test_iv_table_outside_model(self) -> None:
        with pytest.raises(IbisParseError, match="Model"):
            parse_ibis("[Component] C\n[Pulldown]\n0.0V 1.0mA\n[End]\n")

    def test_package_before_component(self) -> None:
        with pytest.raises(IbisParseError, match="Component"):
            parse_ibis("[Package]\nR_pkg 1 2 3\n[End]\n")

    def test_pin_before_component(self) -> None:
        with pytest.raises(IbisParseError, match="Component"):
            parse_ibis("[Pin]\n1 GND\n[End]\n")

    def test_duplicate_model_name(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[Model] M\nModel_type Output\n[End]\n")
        with pytest.raises(IbisParseError, match="重名"):
            parse_ibis(text)

    def test_duplicate_pin_number(self) -> None:
        text = ("[Component] C\n[Pin]\n1 GND\n1 VDD\n"
                "[Model] M\nModel_type Input\n[End]\n")
        with pytest.raises(IbisParseError, match="重复"):
            parse_ibis(text)

    def test_waveform_missing_v_fixture(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Output\n"
                "[Rising Waveform]\nR_dut = 50 Ohm\nC_dut = 10pF\n"
                "L_dut = 0nH\n0.0n 0.0V\n[End]\n")
        with pytest.raises(IbisParseError, match="v_fixture"):
            parse_ibis(text)

    def test_top_level_bare_data_line(self) -> None:
        with pytest.raises(IbisParseError, match="裸数据行"):
            parse_ibis("1 GND\n[Component] C\n[Model] M\n"
                       "Model_type Input\n[End]\n")

    def test_unknown_unit_suffix_in_table(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[Pulldown]\n0.0VV 1.0mA\n[End]\n")
        with pytest.raises(IbisParseError, match="未知单位后缀"):
            parse_ibis(text)

    def test_component_without_name(self) -> None:
        with pytest.raises(IbisParseError, match="缺器件名"):
            parse_ibis("[Component]\n[Model] M\nModel_type Input\n[End]\n")

    def test_model_without_name(self) -> None:
        with pytest.raises(IbisParseError, match="缺模型名"):
            parse_ibis("[Component] C\n[Model]\nModel_type Input\n[End]\n")

    def test_duplicate_package(self) -> None:
        text = ("[Component] C\n[Package]\nR_pkg 1 2 3\n"
                "[Package]\nR_pkg 1 2 3\n[Model] M\nModel_type Input\n[End]\n")
        with pytest.raises(IbisParseError, match="重复"):
            parse_ibis(text)

    def test_ramp_bad_two_column_value(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Output\n"
                "[Ramp]\nRamp_dR 1.0 2.0\n[End]\n")
        with pytest.raises(IbisParseError, match="无法解释"):
            parse_ibis(text)


# ── 注释/空表杂项 ───────────────────────────────────────────────────────────


class TestMisc:
    def test_comment_lines_and_inline_comment(self) -> None:
        text = ("| full line comment\n"
                "[IBIS Ver] 3.2 | trailing comment\n"
                "[Component] C\n[Model] M\nModel_type Input\n"
                "[End]\n| tail comment ok\n")
        tree = parse_ibis(text)
        assert tree.ended is True
        assert tree.header["ibis_ver"] == "3.2"

    def test_empty_table_warning(self) -> None:
        text = ("[Component] C\n[Model] M\nModel_type Input\n"
                "[GND Clamp]\n[Pulldown]\n0.0V 1.0mA\n[End]\n")
        tree = parse_ibis(text)
        assert any("gnd_clamp" in w and "零数据行" in w
                   for w in tree.warnings)

    def test_no_component_rejected(self) -> None:
        with pytest.raises(IbisParseError, match="Component"):
            parse_ibis("[IBIS Ver] 3.2\n[End]\n")

    def test_selector_before_model_ok(self) -> None:
        # 选择器可先于模型出现（引用名不要求先行定义——IBIS 文档序惯例）
        text = ("[Component] C\n[Model Selector] S\nM1 fast\n"
                "[Model] M1\nModel_type Output\n[End]\n")
        view = extract_ibis(parse_ibis(text))
        assert view["model_selectors"]["S"][0]["model"] == "M1"

    def test_fixture_file_exists(self) -> None:
        assert FIXTURE.is_file()
