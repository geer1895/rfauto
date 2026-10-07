"""A2 quantity 类型 + 量纲守卫回收钉（月计划 I 流 B2；#118 合成裁判）。

裁判预声明（core/quantity.py 模块 docstring 同源）：
- 换算回收逐位：2.4 GHz→2.4e9、1 mm→1e-3（10 的幂在双精度内可与字面量
  逐位相等）；
- 量纲代数回收：dim(frequency)+dim(time)==全零向量（指数相加）；
  si 复合 2.4 GHz × 1 ns ≈ 2.4（float 乘法余量 approx）；
- 错配/裸数字/bool/NaN/对数域/摄氏域一律拒收（fail-closed 多报方向）；
- validate_quantity_args 只过问 type=="quantity" 的参数——未声明参数
  零行为变化（零接线守卫钉）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rfauto.core.quantity import (
    DIMENSIONS,
    UNIT_TABLE,
    Dimension,
    QuantityDimensionError,
    QuantityError,
    check_dimension,
    dimension_of,
    parse_quantity,
    quantity_of,
    validate_quantity_args,
)

# ── 换算回收（逐位/近似，预声明） ───────────────────────────────────────────

class TestConversionRecovery:
    def test_ghz_to_si_exact(self):
        assert quantity_of(2.4, "GHz").si_value == 2.4e9

    def test_mm_to_si_exact(self):
        assert quantity_of(1.0, "mm").si_value == 1e-3

    def test_ns_to_si_exact(self):
        assert quantity_of(1.0, "ns").si_value == 1e-9

    def test_value_and_unit_preserved_verbatim(self):
        q = quantity_of(2.4, "GHz")
        assert q.value == 2.4 and q.unit == "GHz"

    def test_degenerate_prefix_chain(self):
        assert quantity_of(1.0, "kHz").si_value == 1e3
        assert quantity_of(1.0, "MHz").si_value == 1e6
        assert quantity_of(1.0, "THz").si_value == 1e12

    def test_deg_to_rad_scale(self):
        assert quantity_of(180.0, "deg").si_value == pytest.approx(3.141592653589793)


# ── 量纲代数回收 ────────────────────────────────────────────────────────────

class TestDimensionAlgebra:
    def test_frequency_times_time_is_dimensionless(self):
        df = dimension_of("frequency")
        dt = dimension_of("time")
        assert (df + dt).is_dimensionless
        assert df + dt == Dimension()

    def test_resistance_derivation_ohm_law(self):
        # U=RI → resistance = voltage / current（指数相减回收）
        assert (dimension_of("voltage") - dimension_of("current")
                == dimension_of("resistance"))

    def test_si_composition_numeric_recovery(self):
        q1 = quantity_of(2.4, "GHz")
        q2 = quantity_of(1.0, "ns")
        assert q1.si_value * q2.si_value == pytest.approx(2.4)

    def test_angle_distinct_from_dimensionless(self):
        assert quantity_of(1.0, "rad").dimension_name == "angle"
        assert quantity_of(1.0, "ratio").dimension_name == "dimensionless"
        # 指数向量同为全零，但量纲标签不同——混用必须被守卫拦下
        with pytest.raises(QuantityDimensionError):
            check_dimension(quantity_of(1.0, "rad"), "dimensionless")

    def test_check_dimension_pass_and_fail(self):
        check_dimension(quantity_of(2.4, "GHz"), "frequency")  # 不抛
        with pytest.raises(QuantityDimensionError) as ei:
            check_dimension(quantity_of(3.0, "mm"), "frequency")
        msg = str(ei.value)
        assert "frequency" in msg and "mm" in msg


# ── fail-closed 拒收面 ──────────────────────────────────────────────────────

class TestFailClosed:
    @pytest.mark.parametrize("bad", [2.4, 0, "2.4", None, [1, "Hz"]])
    def test_non_pair_forms_rejected(self, bad):
        with pytest.raises(QuantityError):
            parse_quantity(bad)

    def test_bool_value_rejected(self):
        with pytest.raises(QuantityError):
            parse_quantity({"value": True, "unit": "Hz"})

    def test_string_value_rejected(self):
        with pytest.raises(QuantityError):
            parse_quantity({"value": "2.4", "unit": "GHz"})

    @pytest.mark.parametrize("v", [float("nan"), float("inf"), float("-inf")])
    def test_nonfinite_value_rejected(self, v):
        with pytest.raises(QuantityError):
            parse_quantity({"value": v, "unit": "GHz"})

    def test_missing_and_extra_keys_rejected(self):
        with pytest.raises(QuantityError):
            parse_quantity({"value": 1.0})
        with pytest.raises(QuantityError):
            parse_quantity({"value": 1.0, "unit": "GHz", "note": "x"})

    def test_unknown_unit_rejected_with_dimensions(self):
        with pytest.raises(QuantityError) as ei:
            parse_quantity({"value": 1.0, "unit": "furlongs"})
        assert "furlongs" in str(ei.value)

    def test_case_sensitivity_is_si_convention(self):
        with pytest.raises(QuantityError):
            parse_quantity({"value": 1.0, "unit": "mhz"})  # 小写 m=毫
        assert quantity_of(1.0, "MHz").si_value == 1e6

    def test_log_domain_units_explicitly_excluded(self):
        for u in ("dB", "dBm", "dBi"):
            with pytest.raises(QuantityError) as ei:
                parse_quantity({"value": -3.0, "unit": u})
            assert "对数域" in str(ei.value)

    def test_celsius_rejected_kelvin_accepted(self):
        with pytest.raises(QuantityError) as ei:
            parse_quantity({"value": 25.0, "unit": "degC"})
        assert "非原点" in str(ei.value)
        assert quantity_of(298.15, "K").dimension_name == "temperature"

    def test_ohm_aliases_resolve_same_dimension(self):
        base = quantity_of(50.0, "ohm")
        for alias in ("Ohm", "Ω"):
            assert quantity_of(50.0, alias).dimension == base.dimension


# ── typed tool call 守卫面 ──────────────────────────────────────────────────

_SPECS = {
    "f0": {"type": "quantity", "dimension": "frequency"},
    "width": {"type": "quantity", "dimension": "length"},
    "limit": {"type": "integer"},
}


class TestValidateQuantityArgs:
    def test_ok_pair_passes(self):
        errs = validate_quantity_args(
            _SPECS,
            {"f0": {"value": 2.4, "unit": "GHz"},
             "width": {"value": 0.5, "unit": "mm"},
             "limit": 5})
        assert errs == []

    def test_bare_number_rejected_for_quantity_param(self):
        errs = validate_quantity_args(_SPECS, {"f0": 2.4})
        assert len(errs) == 1 and "f0" in errs[0] and "二元组" in errs[0]

    def test_dimension_mismatch_rejected(self):
        errs = validate_quantity_args(
            _SPECS, {"f0": {"value": 0.5, "unit": "mm"}})
        assert len(errs) == 1 and "量纲不匹配" in errs[0]

    def test_unknown_unit_surfaced_not_silent(self):
        errs = validate_quantity_args(
            _SPECS, {"width": {"value": 1.0, "unit": "chains"}})
        assert errs and "chains" in errs[0]

    def test_missing_optional_ok_missing_required_flagged(self):
        assert validate_quantity_args(_SPECS, {}) == []
        errs = validate_quantity_args(
            _SPECS, {}, required={"quantity": ["f0"]})
        assert len(errs) == 1 and "缺席" in errs[0]

    def test_null_optional_flagged_only_if_required(self):
        assert validate_quantity_args(_SPECS, {"f0": None}) == []
        errs = validate_quantity_args(
            _SPECS, {"f0": None}, required={"quantity": ["f0"]})
        assert errs and "缺席" in errs[0]

    def test_undeclared_params_untouched(self):
        errs = validate_quantity_args(
            {"limit": {"type": "integer"}}, {"limit": "not-checked"})
        assert errs == []

    def test_quantity_spec_without_dimension_is_error(self):
        errs = validate_quantity_args(
            {"f0": {"type": "quantity"}}, {"f0": {"value": 1.0, "unit": "Hz"}})
        assert errs and "dimension" in errs[0]

    def test_errors_are_jsonable_strings(self):
        import json

        errs = validate_quantity_args(
            _SPECS, {"f0": {"value": 0.5, "unit": "mm"}})
        json.dumps(errs, ensure_ascii=False)  # 不抛即过：错误串可 JSON 化即契约


def test_unit_table_covers_rf_core_families() -> None:
    """守卫面登记单：RF 常用量纲族必须在表（缺族=守卫假红源头）。"""
    for name in ("length", "time", "frequency", "resistance", "voltage",
                 "current", "power", "capacitance", "inductance",
                 "temperature", "angle", "dimensionless"):
        assert name in DIMENSIONS
    for unit in ("m", "mm", "um", "nm", "s", "ms", "ns", "ps", "Hz", "kHz",
                 "MHz", "GHz", "ohm", "V", "A", "W", "F", "pF", "nH", "K",
                 "rad", "deg"):
        assert unit in UNIT_TABLE


def test_unit_table_spot_values_bitwise():
    """review-slice2 P3-4 补钉：RF 常用单位 SI 换算逐位抽查（全表 65 单位审查实测零错值的回归钉）。"""
    for unit, expect in [("pF", 1e-12), ("nH", 1e-9), ("kOhm", 1e3),
                         ("MOhm", 1e6), ("GHz", 1e9), ("ns", 1e-9)]:
        assert quantity_of(1.0, unit).si_value == expect


def test_logarithmic_units_rejected_with_guidance():
    """dB/dBm 对数域显式拒收（不与量纲代数混算）——报文含替代表达指引。"""
    with pytest.raises(QuantityError, match="对数域"):
        quantity_of(0.0, "dBm")


# ── pint 可选桥（B2-2 followUp：惰性 import，未装诚实降级） ──────────────────

from rfauto.core.quantity import PINT_SI_UNITS, from_pint, to_pint


def _pint_or_skip():
    return pytest.importorskip("pint")


class TestPintBridgeNotInstalled:
    """pint 未装环境（本仓 venv 现状）：ImportError 诚实降级三钉。

    sys.modules["pint"]=None 令 ``import pint`` 抛 ImportError——与真实
    未装同路径，且不依赖本机是否恰好装过 pint（df6⑦：装 extras 后
    skip 集合会转正，降级钉必须在两种状态下都成立）。
    """

    def test_to_pint_import_error_honest(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "pint", None)
        with pytest.raises(ImportError, match=r"rfauto\[units\]"):
            to_pint(quantity_of(2.4, "GHz"))

    def test_from_pint_import_error_honest(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "pint", None)
        with pytest.raises(ImportError, match=r"rfauto\[units\]"):
            from_pint(object())

    def test_bridge_names_exported_without_pint(self):
        """桥函数与 SI 出口表在零 pint 环境可 import（内核自洽不弱化）。"""
        assert set(PINT_SI_UNITS) == set(DIMENSIONS)
        assert PINT_SI_UNITS["frequency"] == "Hz"
        assert PINT_SI_UNITS["resistance"] == "ohm"


class TestPintBridgeRoundtrip:
    """pint 已装环境的往返回收（skipif 如实——未装环境整类跳过）。"""

    def test_to_pint_si_value_exact(self):
        pint = _pint_or_skip()
        pq = to_pint(quantity_of(2.4, "GHz"))
        assert pq.magnitude == pytest.approx(2.4e9)
        assert pq.check(pint.Unit("Hz")) is not None

    def test_to_pint_dimensionless_and_length(self):
        pint = _pint_or_skip()
        assert to_pint(quantity_of(0.5, "ratio")).magnitude == 0.5
        length = to_pint(quantity_of(1.0, "mm"))
        assert length.magnitude == pytest.approx(1e-3)
        assert length.check(pint.Unit("m")) is not None

    def test_roundtrip_original_unit_preserved(self):
        _pint_or_skip()
        q0 = quantity_of(47.0, "kOhm")
        q1 = from_pint(to_pint(q0))
        assert q1.si_value == pytest.approx(q0.si_value, rel=1e-15)
        assert q1.dimension_name == q0.dimension_name
        # pint 缩写形渲染随版本漂移（2026-10-03 实测 0.26.1 把 kiloohm
        # 缩写渲染成 "Ω" 而非 "kohm"）——两形都在 UNIT_TABLE
        # （同量纲 resistance，SI 值不变），钉 SI 语义不钉版本渲染。
        assert q1.unit in {"kohm", "Ω"}

    def test_from_pint_rejects_non_pint_type(self):
        _pint_or_skip()
        with pytest.raises(QuantityError, match=r"pint\.Quantity"):
            from_pint({"value": 1.0, "unit": "GHz"})
