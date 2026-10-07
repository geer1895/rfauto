"""KD-3 数据质量门测试（round16 P1，J 流）。

锚树：
- 单调频轴门：严格递增缺省/宽松档/回折与重复点 FAIL/空轴 FAIL；
- NaN 门：非有限点计数与首现索引/空序列 FAIL/非数值元素 FAIL；
- 单位门：受控词表 PASS/未声明 UNKNOWN（不猜）/词表外 FAIL/大小写与
  词根形态；kind 无词表如实 UNKNOWN；
- 掩码门（#314/#316 家族）：None=UNKNOWN 不翻转总门/长度不匹配 FAIL/
  全 False FAIL/非 bool FAIL；
- 曲线聚合门：单曲线 FAIL 翻总门；UNKNOWN 不翻总门但如实透出；
  确定性：同输入两次 JSON 逐位一致；
- 行级门：必填列缺失/数值列非有限/JSON 载荷损坏留痕；
- 消费面旁挂：不改动 dataset_service.query_dataset 读取链（导入即可，
  缺 duckdb 不影响本门纯函数面）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.dataset_quality_service import (
    DATASET_QUALITY_SCHEMA,
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    check_finite,
    check_frequency_axis,
    check_mask,
    check_units,
    curve_quality_gate,
    gates_for_dataset_rows,
)


class TestFrequencyAxis:
    def test_strict_increasing_passes(self):
        r = check_frequency_axis([1e9, 1.5e9, 2e9, 3e9])
        assert r["gate"] == GATE_PASS and r["n_points"] == 4

    def test_duplicate_point_fails_strict(self):
        r = check_frequency_axis([1e9, 2e9, 2e9])
        assert r["gate"] == GATE_FAIL
        assert any("严格递增" in m for m in r["issues"])

    def test_duplicate_allowed_in_lenient_mode(self):
        assert check_frequency_axis([1e9, 2e9, 2e9], strict=False)["gate"] == GATE_PASS

    def test_reversal_fails_both_modes(self):
        assert check_frequency_axis([1e9, 3e9, 2e9])["gate"] == GATE_FAIL
        assert check_frequency_axis([1e9, 3e9, 2e9], strict=False)["gate"] == GATE_FAIL

    def test_empty_axis_fails(self):
        assert check_frequency_axis([])["gate"] == GATE_FAIL
        assert check_frequency_axis("not-a-list")["gate"] == GATE_FAIL

    def test_nonfinite_point_fails(self):
        r = check_frequency_axis([1e9, float("nan"), 2e9])
        assert r["gate"] == GATE_FAIL
        assert any("NaN/Inf" in m for m in r["issues"])

    def test_non_numeric_element_fails(self):
        r = check_frequency_axis([1e9, "2e9"])
        assert r["gate"] == GATE_FAIL
        assert any("非数值" in m for m in r["issues"])


class TestFinite:
    def test_all_finite_passes(self):
        assert check_finite([1.0, 2.0, -3.5])["gate"] == GATE_PASS

    def test_nan_counted_with_first_index(self):
        r = check_finite([1.0, float("nan"), float("inf"), 2.0])
        assert r["gate"] == GATE_FAIL and r["n_nonfinite"] == 2
        assert "idx=1" in r["issues"][0]

    def test_empty_fails(self):
        assert check_finite([], name="s21_db")["gate"] == GATE_FAIL

    def test_non_numeric_fails(self):
        assert check_finite([1.0, None])["gate"] == GATE_FAIL


class TestUnits:
    def test_whitelisted_units_pass_case_insensitive(self):
        for u in ("Hz", "hz", "GHz", "MHz", "THz", "KHz"):
            assert check_units(u)["gate"] == GATE_PASS, u

    def test_plural_root_form_passes(self):
        assert check_units("Hzs")["gate"] == GATE_PASS

    def test_undeclared_is_unknown_not_pass(self):
        r = check_units(None)
        assert r["gate"] == GATE_UNKNOWN
        assert check_units("  ")["gate"] == GATE_UNKNOWN

    def test_out_of_vocabulary_fails(self):
        r = check_units("rpm")
        assert r["gate"] == GATE_FAIL
        assert "受控词表" in r["issues"][0]

    def test_impedance_vocabulary(self):
        assert check_units("ohm", kind="impedance")["gate"] == GATE_PASS
        assert check_units("Hz", kind="impedance")["gate"] == GATE_FAIL

    def test_unknown_kind_is_honest_unknown(self):
        r = check_units("Hz", kind="kelvin")
        assert r["gate"] == GATE_UNKNOWN and "无受控词表" in r["issues"][0]


class TestMask:
    def test_no_mask_is_unknown(self):
        assert check_mask(None, 3)["gate"] == GATE_UNKNOWN

    def test_valid_mask_passes(self):
        r = check_mask([True, False, True], 3)
        assert r["gate"] == GATE_PASS and r["n_true"] == 2

    def test_length_mismatch_fails(self):
        assert check_mask([True, False], 3)["gate"] == GATE_FAIL

    def test_all_false_fails_direction_of_hiding(self):
        r = check_mask([False, False], 2)
        assert r["gate"] == GATE_FAIL
        assert "全 False" in r["issues"][0]

    def test_non_bool_fails(self):
        assert check_mask([1, 0], 2)["gate"] == GATE_FAIL


class TestCurveQualityGate:
    def _good_curve(self) -> dict:
        return {"curve_id": "pt1", "freq_hz": [1e9, 2e9, 3e9],
                "s11_db": [-0.5, -1.0, -2.0], "unit_freq": "Hz"}

    def test_good_curve_passes(self):
        r = curve_quality_gate([self._good_curve()])
        assert r["ok"] and r["verdict"] == GATE_PASS and r["n_curves"] == 1

    def test_non_monotonic_axis_flips_verdict(self):
        c = self._good_curve()
        c["freq_hz"] = [2e9, 1e9, 3e9]
        r = curve_quality_gate([c])
        assert r["verdict"] == GATE_FAIL and r["n_fail"] == 1
        assert any("freq" in m for m in r["issues"])

    def test_nan_value_flips_verdict(self):
        c = self._good_curve()
        c["s11_db"] = [-0.5, float("nan"), -2.0]
        r = curve_quality_gate([c])
        assert r["verdict"] == GATE_FAIL

    def test_missing_unit_is_unknown_not_fail(self):
        c = self._good_curve()
        del c["unit_freq"]
        r = curve_quality_gate([c])
        assert r["verdict"] == GATE_UNKNOWN and r["n_unknown"] == 1
        assert r["n_fail"] == 0

    def test_mask_unknown_does_not_flip_verdict(self):
        c = self._good_curve()
        r = curve_quality_gate([c])
        assert r["verdict"] == GATE_PASS  # mask=None=UNKNOWN，单门不翻总门

    def test_mask_mismatch_flips_verdict(self):
        c = self._good_curve()
        c["mask"] = [True, False]
        r = curve_quality_gate([c])
        assert r["verdict"] == GATE_FAIL

    def test_malformed_payload_recorded_not_raised(self):
        r = curve_quality_gate([{"freq_hz": 1}])
        assert r["verdict"] == GATE_FAIL
        r2 = curve_quality_gate(["not-a-mapping"])
        assert r2["verdict"] == GATE_FAIL and "mapping" in r2["issues"][0]

    def test_deterministic_roundtrip(self):
        curves = [self._good_curve(),
                  {"freq_hz": [1e9, 2e9], "s21_db": [0.0, -3.0]}]
        a = json.dumps(curve_quality_gate(curves), sort_keys=True)
        b = json.dumps(curve_quality_gate(curves), sort_keys=True)
        assert a == b

    def test_schema_pinned(self):
        assert curve_quality_gate([])["schema"] == DATASET_QUALITY_SCHEMA


class TestRowsGate:
    def _row(self, **over):
        base = {"run_id": "abc", "model": "mline", "adapter": "fake",
                "seed": 1, "point_index": 0, "cost": 0.5,
                "params_json": json.dumps({"w": 1.0}),
                "metrics_json": json.dumps({"cost": 0.5})}
        base.update(over)
        return base

    def test_clean_rows_pass(self):
        r = gates_for_dataset_rows([self._row(), self._row()])
        assert r["ok"] and r["verdict"] == GATE_PASS and r["n_rows"] == 2

    def test_missing_required_column_fails(self):
        r = gates_for_dataset_rows([self._row(model="  ")])
        assert r["verdict"] == GATE_FAIL and r["bad_required"]

    def test_nonfinite_cost_fails(self):
        r = gates_for_dataset_rows([self._row(cost=float("nan"))])
        assert r["verdict"] == GATE_FAIL and r["bad_numeric"]

    def test_corrupt_json_recorded(self):
        r = gates_for_dataset_rows([self._row(metrics_json="{oops")])
        assert r["verdict"] == GATE_FAIL and r["bad_json"]
        assert "metrics_json" in r["bad_json"][0]

    def test_json_non_object_recorded(self):
        r = gates_for_dataset_rows([self._row(params_json="[1,2]")])
        assert r["verdict"] == GATE_FAIL and r["bad_json"]

    def test_nullable_seed_skipped(self):
        r = gates_for_dataset_rows([self._row(seed=None)])
        assert r["verdict"] == GATE_PASS
