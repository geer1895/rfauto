"""B7 量纲安全构建器单测（#218 三类表达式语义回归，方案 §10.19 B7）。

全部为字符串级/数值级单测，零真机零网络。
验收口径（方案 B7 行）：#218 原案（"-2.5*1.113"）构建期拒绝 + 四工具
单位序列化往返（HFSS 表达式串 / openEMS 缩放浮点 / COMSOL "[mm]" 串 /
KiCad nm 整数）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from rfauto.adapters.hfss_builder_utils import Quantity
from rfauto.core.errors import ModelBuildError


class TestConstruction:
    """显式单位构造（mm/nm/m 唯一入口）。"""

    def test_mm_nm_m_canonical_storage(self):
        assert Quantity.mm(1.113).value_mm == pytest.approx(1.113)
        assert Quantity.nm(1e6).value_mm == pytest.approx(1.0)
        assert Quantity.m(1e-3).value_mm == pytest.approx(1.0)

    def test_of_with_explicit_unit(self):
        assert Quantity.of(2.5, "mm") == Quantity.mm(2.5)
        assert Quantity.of(1.0, "m") == Quantity.mm(1000.0)

    def test_invalid_unit_rejected(self):
        with pytest.raises(ModelBuildError, match="不支持的长度单位"):
            Quantity.of(1.0, "cm")

    def test_nonfinite_rejected(self):
        with pytest.raises(ModelBuildError, match="有限"):
            Quantity.mm(float("nan"))
        with pytest.raises(ModelBuildError, match="有限"):
            Quantity.mm(float("inf"))


class TestHfssStringSemantics218:
    """#218 三类字符串语义回归：一律在构建期拒绝（字符串级，零真机）。"""

    def test_pure_number_string_rejected(self):
        # 语义一：纯数字串按模型单位补全，量纲随模型 units 漂移
        with pytest.raises(ModelBuildError, match="纯数字"):
            Quantity.mm("1.113")
        with pytest.raises(ModelBuildError, match="纯数字"):
            Quantity.of("-25", "mm")

    def test_literal_arithmetic_string_rejected_218_original(self):
        # 语义二（#218 原案）：'-2.5*1.113' 曾被 HFSS 按 SI 米求值
        with pytest.raises(ModelBuildError, match="字面算术"):
            Quantity.of("-2.5*1.113", "mm")
        with pytest.raises(ModelBuildError, match="SI 米"):
            Quantity.mm("2.5*1.113e0")

    def test_design_variable_string_rejected(self):
        # 语义三：变量表达式量纲随变量定义，变量化建模走 set_variables 通道
        for s in ("W", "sub_h", "2*W", "(-2.5*w_in)", "h+t+0.1mm"):
            with pytest.raises(ModelBuildError, match="设计变量"):
                Quantity.mm(s)

    def test_classify_string_three_categories(self):
        assert Quantity.classify_string("1.113") == "pure_number"
        assert Quantity.classify_string("-2.5*1.113") == "literal_arithmetic"
        assert Quantity.classify_string("2*W") == "design_variable"

    def test_precomputed_float_accepted(self):
        # 修复式：预计算浮点 + 显式单位 = 合法路径
        assert Quantity.mm(-2.5 * 1.113).to_hfss() == "-2.7825mm"


class TestFourToolSerialization:
    """四套单位约定序列化（HFSS/openEMS/COMSOL/KiCad）+ 跨单位往返。"""

    def test_hfss_explicit_mm_suffix(self):
        assert Quantity.mm(2.7825).to_hfss() == "2.7825mm"
        assert Quantity.mm(0.0).to_hfss() == "0mm"

    def test_comsol_bracket_string(self):
        assert Quantity.mm(2.7825).to_comsol() == "2.7825[mm]"

    def test_openems_scaled_float(self):
        q = Quantity.mm(2.7825)
        assert q.to_openems("mm") == pytest.approx(2.7825)
        assert q.to_openems("m") == pytest.approx(0.0027825)
        assert q.to_openems("nm") == pytest.approx(2.7825e6)

    def test_openems_invalid_unit_rejected(self):
        with pytest.raises(ModelBuildError, match="不支持的长度单位"):
            Quantity.mm(1.0).to_openems("mil")

    def test_kicad_nm_integer(self):
        assert Quantity.mm(1.0).to_kicad() == 1_000_000
        assert Quantity.nm(500).to_kicad() == 500
        assert isinstance(Quantity.mm(0.508).to_kicad(), int)

    def test_cross_unit_roundtrip_same_physical_length(self):
        # nm/m 输入与 mm 输入是同一物理长度 → 四工具出口一致
        a, b = Quantity.mm(2.7825), Quantity.nm(2_782_500)
        assert a.to_hfss() == b.to_hfss()
        assert a.to_comsol() == b.to_comsol()
        assert a.to_kicad() == b.to_kicad()
        assert a.to_openems("m") == pytest.approx(b.to_openems("m"))


class TestDimensionSafeArithmetic:
    """量纲安全算术：结果仍为 Quantity（单位不丢）。"""

    def test_scale_and_serialize_218_site(self):
        # #218 修复位点的等价表达：-2.5 × w
        assert (-2.5 * Quantity.mm(1.113)).to_hfss() == "-2.7825mm"
        assert (Quantity.mm(1.113) * 5).to_hfss() == "5.565mm"

    def test_add_sub_neg(self):
        assert Quantity.mm(1) + Quantity.mm(2) == Quantity.mm(3)
        assert Quantity.mm(3) - Quantity.mm(1) == Quantity.mm(2)
        assert (-Quantity.mm(2)).value_mm == -2
        assert (-Quantity.mm(2)).to_hfss() == "-2mm"

    def test_div_quantity_yields_dimensionless_ratio(self):
        r = Quantity.mm(3) / Quantity.mm(1)
        assert isinstance(r, float) and r == pytest.approx(3.0)

    def test_div_by_scalar_yields_quantity(self):
        assert Quantity.mm(6) / 2 == Quantity.mm(3)

    def test_quantity_times_quantity_rejected(self):
        with pytest.raises(TypeError):
            Quantity.mm(1) * Quantity.mm(2)  # 长度×长度无物理定义

    def test_add_non_quantity_rejected(self):
        with pytest.raises(TypeError):
            Quantity.mm(1) + 2.0

    def test_div_by_zero_quantity_raises(self):
        with pytest.raises(ZeroDivisionError):
            Quantity.mm(1) / Quantity.mm(0)


# ─── B7 完整版追加：角度 / 无量纲 / 反解往返 / 迁移回归 ──────────────────────


class TestAngleDimension:
    """角度纲（deg/rad）：规范存储 rad，四工具序列化。"""

    def test_deg_rad_canonical_storage(self):
        assert Quantity.deg(180).radians == pytest.approx(math.pi)
        assert Quantity.rad(math.pi).degrees == pytest.approx(180.0)
        assert Quantity.of(90, "deg") == Quantity.deg(90)
        assert Quantity.deg(90).is_angle

    def test_angle_roundtrip_deg_rad(self):
        q = Quantity.deg(37.5)
        assert Quantity.rad(q.radians).degrees == pytest.approx(37.5)
        r = Quantity.rad(1.234)
        assert Quantity.deg(r.degrees).radians == pytest.approx(1.234)

    def test_angle_four_tool_serialization(self):
        q = Quantity.deg(45)
        assert q.to_hfss() == "45deg"
        assert q.to_comsol() == "45[deg]"
        assert q.to_openems("rad") == pytest.approx(math.pi / 4)
        assert q.to_openems("deg") == pytest.approx(45.0)
        assert q.to_kicad() == 450  # EDA_ANGLE::AsTenthsOfADegree

    def test_angle_add_sub_keeps_dimension(self):
        assert (Quantity.deg(30) + Quantity.deg(15)).to_hfss() == "45deg"
        assert (Quantity.deg(30) - Quantity.deg(45)).to_hfss() == "-15deg"
        assert (-Quantity.rad(1.0)).to_hfss() == "-57.29577951deg"

    def test_dimension_mismatch_add_rejected(self):
        with pytest.raises(ModelBuildError, match="量纲不匹配"):
            Quantity.deg(1) + Quantity.mm(1)
        with pytest.raises(ModelBuildError, match="量纲不匹配"):
            Quantity.deg(1) - Quantity.mm(1)

    def test_value_mm_on_angle_rejected(self):
        with pytest.raises(ModelBuildError, match="只对长度纲"):
            _ = Quantity.deg(1).value_mm

    def test_angle_cross_unit_rejected(self):
        with pytest.raises(ModelBuildError, match="不支持的角度单位"):
            Quantity.deg(1).to_openems("mm")
        with pytest.raises(ModelBuildError, match="不支持的长度单位"):
            Quantity.mm(1).to_openems("deg")


class TestDimensionlessDimension:
    """无量纲纲（比值/系数）：规范存储纯比值。"""

    def test_ratio_and_coefficient_construction(self):
        assert Quantity.ratio(2.5).ratio_value == pytest.approx(2.5)
        assert Quantity.coefficient(0.25).ratio_value == pytest.approx(0.25)
        assert Quantity.ratio(1).is_dimensionless
        assert Quantity.ratio(1) == Quantity.coefficient(1)

    def test_ratio_from_same_dimension_division(self):
        r = Quantity.mm(3) / Quantity.mm(2)
        assert isinstance(r, float) and r == pytest.approx(1.5)
        assert Quantity.ratio(r).to_hfss() == "1.5"  # 显式无量纲形态

    def test_coefficient_scales_length(self):
        assert (Quantity.ratio(2) * Quantity.mm(3)) == Quantity.mm(6)
        assert (Quantity.mm(3) * Quantity.coefficient(2)) == Quantity.mm(6)
        assert (Quantity.mm(6) / Quantity.ratio(2)) == Quantity.mm(3)
        assert (Quantity.ratio(2) * Quantity.ratio(3)).ratio_value == pytest.approx(6.0)

    def test_dimensionless_four_tool_serialization(self):
        q = Quantity.ratio(0.5)
        assert q.to_hfss() == "0.5"
        assert q.to_comsol() == "0.5"
        assert q.to_openems() == pytest.approx(0.5)
        assert q.to_kicad() == 500_000  # rfauto 1e-6 定点整数传输约定

    def test_length_times_length_still_rejected(self):
        with pytest.raises(TypeError):
            Quantity.mm(1) * Quantity.mm(2)

    def test_unknown_dimension_rejected(self):
        with pytest.raises(ModelBuildError, match="未知量纲"):
            Quantity(1.0, "mass")

    def test_ratio_value_on_length_rejected(self):
        with pytest.raises(ModelBuildError, match="只对无量纲纲"):
            _ = Quantity.mm(1).ratio_value


class TestCrossToolRoundtrip:
    """四工具序列化 → 反解往返（确定性、无网络、无真机）。"""

    @pytest.mark.parametrize(("q", "dim"), [
        (Quantity.mm(2.7825), "length"),
        (Quantity.deg(45), "angle"),
        (Quantity.ratio(0.5), "dimensionless"),
    ])
    def test_hfss_parse_roundtrip(self, q, dim):
        back = Quantity.parse(q.to_hfss())
        assert back.dimension == dim
        assert back.value == pytest.approx(q.value)

    @pytest.mark.parametrize(("q", "dim"), [
        (Quantity.mm(2.7825), "length"),
        (Quantity.deg(45), "angle"),
        (Quantity.ratio(0.5), "dimensionless"),
    ])
    def test_comsol_parse_roundtrip(self, q, dim):
        back = Quantity.parse(q.to_comsol())
        assert back.dimension == dim
        assert back.value == pytest.approx(q.value)

    @pytest.mark.parametrize(("q", "unit", "dim"), [
        (Quantity.mm(2.7825), "m", "length"),
        (Quantity.deg(45), "rad", "angle"),
        (Quantity.ratio(0.5), "1", "dimensionless"),
    ])
    def test_openems_roundtrip(self, q, unit, dim):
        back = Quantity.of(q.to_openems(unit), unit)
        assert back.dimension == dim
        assert back.value == pytest.approx(q.value)

    @pytest.mark.parametrize("q", [
        Quantity.mm(0.508),
        Quantity.deg(45),
        Quantity.ratio(0.5),
    ])
    def test_kicad_roundtrip(self, q):
        back = Quantity.from_kicad(q.to_kicad(), q.dimension)
        assert back.dimension == q.dimension
        assert back.value == pytest.approx(q.value)

    def test_cross_unit_same_physical_length(self):
        a, b = Quantity.parse("2.7825mm"), Quantity.parse("2782500nm")
        assert a.dimension == b.dimension == "length"
        assert a.value == pytest.approx(b.value)

    def test_bracket_and_suffix_equivalent(self):
        assert Quantity.parse("2.5[mm]") == Quantity.parse("2.5mm")
        assert Quantity.parse("45[deg]") == Quantity.parse("45deg")

    def test_from_kicad_invalid_dimension_rejected(self):
        with pytest.raises(ModelBuildError, match="未知量纲"):
            Quantity.from_kicad(1, "mass")


class TestRejectionAndIllegalInput:
    """扩展后的拒绝面：字面算术/无单位/非法量纲/非法单位。"""

    def test_parse_rejects_literal_arithmetic(self):
        for bad in ("-2.5*1.113", "2*W", "2.5*1.113e0", "1+1"):
            with pytest.raises(ModelBuildError, match="无法解析"):
                Quantity.parse(bad)

    def test_parse_rejects_empty_or_none(self):
        with pytest.raises(ModelBuildError, match="无法解析"):
            Quantity.parse("")
        with pytest.raises(ModelBuildError, match="无法解析"):
            Quantity.parse(None)  # type: ignore[arg-type]

    def test_parse_bare_number_is_dimensionless_not_length(self):
        # 裸数按无量纲解析——长度必须带单位（防 #218 语义一）
        q = Quantity.parse("25")
        assert q.dimension == "dimensionless" and q.ratio_value == 25

    def test_angle_constructors_reject_strings(self):
        with pytest.raises(ModelBuildError, match="纯数字"):
            Quantity.deg("45")
        with pytest.raises(ModelBuildError, match="字面算术"):
            Quantity.rad("2.5*1.113")

    def test_unknown_units_rejected(self):
        with pytest.raises(ModelBuildError, match="不支持的长度单位"):
            Quantity.of(1.0, "cm")
        with pytest.raises(ModelBuildError, match="不支持的长度单位"):
            Quantity.of(1.0, "grad")

    def test_nonfinite_angle_rejected(self):
        with pytest.raises(ModelBuildError, match="有限"):
            Quantity.deg(float("nan"))
        with pytest.raises(ModelBuildError, match="有限"):
            Quantity.ratio(float("inf"))


class TestDeterminism:
    """确定性：同输入重复序列化逐位一致（无随机/无环境依赖）。"""

    def test_repeated_serialization_identical(self):
        q = Quantity.deg(12.345)
        first = (q.to_hfss(), q.to_comsol(), q.to_openems(), q.to_kicad())
        for _ in range(100):
            assert (q.to_hfss(), q.to_comsol(), q.to_openems(), q.to_kicad()) == first

    def test_parse_deterministic(self):
        for _ in range(50):
            assert Quantity.parse("0.508mm").value == 0.508
            assert Quantity.parse("45[deg]").value == Quantity.deg(45).value


PLUGIN_FILES = (
    "src/rfauto/models/wilkinson_power_divider/plugin.py",
    "src/rfauto/models/branchline_coupler/plugin.py",
    "src/rfauto/models/patch_antenna/plugin.py",
)


def _read_plugin(rel: str) -> str:
    repo = Path(__file__).resolve().parents[2]
    return (repo / rel).read_text(encoding="utf-8")


class TestModelPluginMigration:
    """models/*/plugin.py 几何构造实参迁移回归（行为等价）。

    迁移口径：几何实参中的字面零值 "0mm" 改经 Quantity 显式单位构造
    （Quantity.mm(0.0).to_hfss() 输出仍为 "0mm"）；设计变量表达式实参保持
    不变（军规 2a 变量通道 / #218 语义三·四，迁成数值即行为改变）。
    """

    def test_zero_geometry_literals_migrated_to_quantity(self):
        for rel in PLUGIN_FILES:
            src = _read_plugin(rel)
            assert "Quantity.mm(0.0).to_hfss()" in src, rel
            assert '"0mm"' not in src, f"{rel} 仍残留字面 0mm 几何实参"

    def test_quantity_zero_renders_identical_string(self):
        assert Quantity.mm(0.0).to_hfss() == "0mm"
        assert Quantity.parse("0mm") == Quantity.mm(0.0)

    def test_plugin_geometry_has_no_pure_literal_arithmetic(self):
        scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import audit_literal_arithmetic_geometry as audit
        for rel in PLUGIN_FILES:
            cats = {f["category"] for f in audit.scan_source(_read_plugin(rel), rel)}
            assert "LITERAL_ARITH" not in cats, (rel, cats)

