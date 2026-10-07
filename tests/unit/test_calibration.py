"""E9b 校准框架单元测试。

验收标准（扩展方案 §E9b）：
① SOLT 校准套件加载
② TRL 校准套件加载
③ 无校准时返回原样数据
④ 校准结果序列化
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pytest
import skrf
import yaml

from rfauto.measurement.calibration import (
    CalibrationKit,
    CalibrationMethod,
    CalibrationStandard,
    apply_calibration,
)
from rfauto.measurement.import_data import MeasurementData, MeasurementMetadata


def _make_network(n_freq: int = 5, n_ports: int = 2) -> skrf.Network:
    """创建测试用网络。"""
    freq = skrf.Frequency(1, 3, n_freq, unit="GHz")
    s = np.random.rand(n_freq, n_ports, n_ports) + 1j * np.random.rand(n_freq, n_ports, n_ports)
    return skrf.Network(frequency=freq, s=s)


def _make_measurement() -> MeasurementData:
    """创建测试用测量数据。"""
    return MeasurementData(
        network=_make_network(),
        metadata=MeasurementMetadata(),
        source_file="test.s2p",
        n_ports=2,
        freq_range_ghz=(1.0, 3.0),
    )


def _make_calkit(method: CalibrationMethod) -> CalibrationKit:
    """创建测试用校准套件。"""
    standards = []
    if method == CalibrationMethod.SOLT:
        for std_type in ["short", "open", "load", "through"]:
            standards.append(CalibrationStandard(
                name=f"{std_type}_standard",
                network=_make_network(),
                standard_type=std_type,
            ))
    elif method == CalibrationMethod.TRL:
        for std_type in ["through", "reflect", "line"]:
            standards.append(CalibrationStandard(
                name=f"{std_type}_standard",
                network=_make_network(),
                standard_type=std_type,
            ))

    return CalibrationKit(
        name=f"test_{method.value}_kit",
        method=method,
        standards=standards,
    )


class TestCalibrationKit:
    """校准套件测试。"""

    def test_solt_kit(self):
        """① SOLT 校准套件。"""
        kit = _make_calkit(CalibrationMethod.SOLT)
        assert kit.method == CalibrationMethod.SOLT
        assert len(kit.standards) == 4

    def test_trl_kit(self):
        """② TRL 校准套件。"""
        kit = _make_calkit(CalibrationMethod.TRL)
        assert kit.method == CalibrationMethod.TRL
        assert len(kit.standards) == 3

    def test_to_dict(self):
        kit = _make_calkit(CalibrationMethod.SOLT)
        d = kit.to_dict()
        assert d["method"] == "solt"
        assert d["n_standards"] == 4


class TestApplyCalibration:
    """校准应用测试。"""

    def test_no_calibration(self):
        """③ 无校准时返回原样数据。"""
        measured = _make_measurement()
        result = apply_calibration(measured, None)
        assert result.method == CalibrationMethod.NONE
        assert result.is_calibrated is False
        assert result.calibrated_network is not None

    def test_solt_calibration(self):
        """SOLT 校准。"""
        measured = _make_measurement()
        kit = _make_calkit(CalibrationMethod.SOLT)
        result = apply_calibration(measured, kit)
        assert result.method == CalibrationMethod.SOLT
        # 注意：简化实现可能不会真正校准，但不应崩溃

    def test_trl_calibration(self):
        """TRL 校准。"""
        measured = _make_measurement()
        kit = _make_calkit(CalibrationMethod.TRL)
        result = apply_calibration(measured, kit)
        assert result.method == CalibrationMethod.TRL

    def test_result_to_dict(self):
        """④ 校准结果序列化。"""
        measured = _make_measurement()
        result = apply_calibration(measured, None)
        d = result.to_dict()
        assert "method" in d
        assert "is_calibrated" in d


class TestCalibrationStandard:
    """校准标准件测试。"""

    def test_standard_creation(self):
        std = CalibrationStandard(
            name="test_short",
            network=_make_network(),
            standard_type="short",
        )
        assert std.name == "test_short"
        assert std.standard_type == "short"

    def test_to_dict(self):
        std = CalibrationStandard(
            name="test_short",
            network=_make_network(),
            standard_type="short",
        )
        d = std.to_dict()
        assert d["name"] == "test_short"
        assert d["type"] == "short"

# ─── D12 FSV 曲线级等级（方案 §10.20 ⑥ 补强）────────────────────────────────
# 加性验收：calibration_service 的 FSV 字段与 core/fsv 内核逐字一致；恒等曲线
# Ex；已知差异曲线等级下降（非恒真）；非法输入/缺曲线 best-effort 不崩；
# 既有单点容差口径（validation_max_delta / rho）行为不变。

def _fsv_base_curve(n: int = 201) -> tuple[np.ndarray, np.ndarray]:
    """平滑 S11 型谐振曲线（2.0-3.0GHz，2.5GHz 深谷）——与 test_fsv 同型。"""
    f = np.linspace(2.0, 3.0, n)
    y = -0.5 - 25.0 / (1.0 + ((f - 2.5) / 0.05) ** 2)
    return f, y


def _fsv_ripple(n: int = 201, k: int = 61) -> np.ndarray:
    """归一化高频纹波（落在 Hi 段），幅值 1。"""
    return np.sin(2.0 * np.pi * k * np.arange(n) / n)


class TestFsvCurveLevels:
    """fsv_curve_levels：曲线对 → ADM/FDM/GDM 六级等级。"""

    def test_grade_fields_match_core_kernel(self):
        from rfauto.core.fsv import GRADE_CODES, GRADE_LABELS
        from rfauto.core.fsv import fsv as core_fsv
        from rfauto.service.calibration_service import fsv_curve_levels

        f, y = _fsv_base_curve()
        yb = y + 0.9 * _fsv_ripple()
        out = fsv_curve_levels(f, y, f, yb)
        raw = core_fsv(f, y, f, yb)
        assert out["ok"] is True
        assert out["adm_grade"] == raw["adm_grade"]
        assert out["fdm_grade"] == raw["fdm_grade"]
        assert out["gdm_grade"] == raw["gdm_grade"]
        assert out["gdm_mean"] == pytest.approx(raw["gdm_mean"])
        assert out["n_points"] == raw["n_points"]
        assert out["gdm_grade_level"] == raw["gdm_grade_level"]
        assert out["gdm_spread"] == raw["gdm_spread"]
        for code_key, label_key in (("adm_grade", "adm_grade_label"),
                                    ("fdm_grade", "fdm_grade_label"),
                                    ("gdm_grade", "gdm_grade_label")):
            assert out[label_key] == GRADE_LABELS[GRADE_CODES.index(out[code_key])]

    def test_identity_is_excellent(self):
        from rfauto.service.calibration_service import fsv_curve_levels

        f, y = _fsv_base_curve()
        out = fsv_curve_levels(f, y, f, y)
        assert out["ok"] is True
        assert out["gdm_mean"] == 0.0
        assert out["adm_grade"] == "Ex"
        assert out["fdm_grade"] == "Ex"
        assert out["gdm_grade"] == "Ex"

    def test_known_difference_degrades_grade(self):
        from rfauto.core.fsv import grade_index_of
        from rfauto.service.calibration_service import fsv_curve_levels

        f, y = _fsv_base_curve()
        ripple = _fsv_ripple()
        levels = [
            grade_index_of(float(
                fsv_curve_levels(f, y, f, y + amp * ripple)["gdm_mean"]))
            for amp in (0.0, 0.1, 0.4, 1.6, 3.2)
        ]
        assert levels[0] == 0, levels
        assert levels[-1] > levels[0], levels  # 非恒真：差异确实降级
        assert all(b >= a for a, b in itertools.pairwise(levels)), levels

    def test_invalid_inputs_best_effort(self):
        from rfauto.service.calibration_service import fsv_curve_levels

        f, y = _fsv_base_curve()
        cases = [
            fsv_curve_levels([1.0, 2.0, 3.0], [1.0, 2.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
            fsv_curve_levels([], [], [], []),
            fsv_curve_levels(f, np.full(f.size, np.nan), f, y),
            fsv_curve_levels(f, y, f + 100.0, y),
            fsv_curve_levels(np.linspace(0.0, 1.0, 8), np.zeros(8),
                             np.linspace(0.0, 1.0, 8), np.ones(8)),
        ]
        for out in cases:
            assert out["ok"] is False, out
            assert isinstance(out["errors"][0], str) and out["errors"][0]
            assert "errors" in out and "adm_grade" not in out


class TestFsvLevelsFromCurves:
    """fsv_levels_from_curves：多曲线 → 参考 vs 其余（曲线级判读）。"""

    def test_reference_selection_and_json_safe(self):
        from rfauto.service.calibration_service import fsv_levels_from_curves

        f, y = _fsv_base_curve()
        curves = {"b": (f, y + 0.9 * _fsv_ripple()), "a": (f, y), "c": (f, y)}
        out = fsv_levels_from_curves(curves)
        assert out["ok"] is True
        assert out["reference"] == "a"
        assert set(out["entries"]) == {"b", "c"}
        assert out["entries"]["c"]["gdm_grade"] == "Ex"
        assert out["entries"]["b"]["gdm_grade"] != "Ex"
        json.dumps(out)  # to_jsonable 口径：可序列化

    def test_empty_and_explicit_reference(self):
        from rfauto.service.calibration_service import fsv_levels_from_curves

        assert fsv_levels_from_curves({})["ok"] is False
        f, y = _fsv_base_curve()
        out = fsv_levels_from_curves(
            {"a": (f, y), "b": (f, y + 0.9 * _fsv_ripple())}, reference="b")
        assert out["reference"] == "b"
        assert set(out["entries"]) == {"a"}

    def test_bad_curve_isolated(self):
        from rfauto.service.calibration_service import fsv_levels_from_curves

        f, y = _fsv_base_curve()
        out = fsv_levels_from_curves({
            "a": (f, y),
            "bad": ([1.0, 2.0, 3.0], [1.0, 2.0]),
            "c": (f, y + 0.9 * _fsv_ripple()),
        })
        assert out["ok"] is True
        assert out["entries"]["bad"]["ok"] is False
        assert out["entries"]["c"]["ok"] is True


class TestFsvValidationLevels:
    """fsv_validation_levels：验证点序列上的预测 vs 实际曲线级等级。"""

    def test_sequence_levels_match_core(self):
        from rfauto.core.fsv import fsv as core_fsv
        from rfauto.service.calibration_service import fsv_validation_levels

        n = 24
        actual = [float(1.0 + 0.1 * np.sin(i / 3.0)) for i in range(n)]
        predicted = [float(v + (0.05 if i % 4 == 0 else 0.0))
                     for i, v in enumerate(actual)]
        validation = [{"actual": {"s11_db_max_in_band": a},
                       "predicted": {"s11_db_max_in_band": p}}
                      for a, p in zip(actual, predicted, strict=True)]
        out = fsv_validation_levels(validation)
        assert out["ok"] is True
        assert out["n_validation"] == n
        entry = out["entries"]["s11_db_max_in_band"]
        x = [float(i) for i in range(n)]
        raw = core_fsv(x, actual, x, predicted)
        assert entry["gdm_grade"] == raw["gdm_grade"]
        assert entry["adm_grade"] == raw["adm_grade"]
        assert entry["fdm_grade"] == raw["fdm_grade"]
        assert entry["gdm_mean"] == pytest.approx(raw["gdm_mean"])
        assert out["worst_gdm_grade"] == raw["gdm_grade"]
        json.dumps(out)

    def test_below_min_points_is_unavailable(self):
        from rfauto.service.calibration_service import fsv_validation_levels

        out = fsv_validation_levels([
            {"actual": {"m": 1.0}, "predicted": {"m": 1.1}},
            {"error": "boom"},
        ])
        assert out["ok"] is False
        assert "MIN_POINTS" in out["errors"][0]
        assert out["entries"] == {}
        assert fsv_validation_levels([])["ok"] is False


def _calib_recipe(tmp_path) -> object:
    """wilkinson 校准配方（fake 采样器可跑，零真机）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "cal_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestFsvWiringRegression:
    """加性接线回归：FSV 段新增，既有单点容差契约与数值不变。"""

    def test_calibration_adds_fsv_without_changing_tolerance(
            self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(_calib_recipe(tmp_path), sampler="fake",
                                     n_levels=3, n_validation=2)
        assert result["ok"], result.get("errors")
        assert result["verdict"] in ("PASS", "FAIL")
        # 既有单点容差口径逐字保留：validation_max_delta == max(abs_delta)
        assert result["n_validation"] == 2
        calib = tmp_path / "runs" / result["run_id"] / "calibration"
        samples = json.loads((calib / "samples.json").read_text(encoding="utf-8"))
        deltas = [d for v in samples["validation"]
                  for d in (v.get("abs_delta") or {}).values()
                  if isinstance(d, (int, float))]
        expected = max(deltas) if deltas else None
        assert result["validation_max_delta"] == expected
        # 新增 FSV 段：2 点 < MIN_POINTS=16 → 如实不可用（不伪造等级）
        assert result["fsv_validation"]["ok"] is False
        assert "MIN_POINTS" in result["fsv_validation"]["errors"][0]
        # gate.json 与 result 同步携带 FSV 段，verdict 口径不变
        gate = json.loads((calib / "gate.json").read_text(encoding="utf-8"))
        assert gate["verdict"] == result["verdict"]
        assert gate["validation_max_delta"] == result["validation_max_delta"]
        assert gate["fsv_validation"]["ok"] is False
        assert "D12 曲线级 FSV" in (calib / "report.md").read_text(encoding="utf-8")


class TestFsvGradeGate:
    """§10.20 ⑥ 收口：fsv_grade_gate 等级门语义（verdict 并入共享内核）。

    门语义：可用段按 GDM 等级序 vs 门限序（≤ 门限 pass / > 门限否决）；
    不可用段降级（pass=None），调用方必须回既有单点口径，禁止因 FSV
    缺席而 FAIL。
    """

    def test_gate_semantics_boundary_and_grades(self):
        """等级序 vs 门限序的边界与各档（单曲线形状）。"""
        from rfauto.service.calibration_service import FSV_GRADE_THRESHOLD, fsv_grade_gate

        assert FSV_GRADE_THRESHOLD == "F"
        base = {"ok": True, "adm_grade": "Ex", "fdm_grade": "Ex",
                "gdm_mean": 0.5, "n_points": 24}
        # 门限边界：F==F → pass（等级序 ≤ 门限序语义）
        assert fsv_grade_gate(base | {"gdm_grade": "F"})["pass"] is True
        assert fsv_grade_gate(base | {"gdm_grade": "G"})["pass"] is True
        assert fsv_grade_gate(base | {"gdm_grade": "P"})["pass"] is False
        assert fsv_grade_gate(base | {"gdm_grade": "VP"})["pass"] is False
        g = fsv_grade_gate(base | {"gdm_grade": "VP"})
        assert g["degraded"] is False and g["grade"] == "VP"
        assert g["threshold"] == "F"
        assert "曲线级一致性不足" in g["reason"]

    def test_gate_multi_curve_shape_and_degraded_paths(self):
        """多曲线形状（worst_gdm_grade）与全部降级路径。"""
        from rfauto.service.calibration_service import fsv_grade_gate

        multi = {"ok": True, "entries": {}, "worst_gdm_grade": "VP"}
        assert fsv_grade_gate(multi)["pass"] is False
        multi_ok = {"ok": True, "entries": {}, "worst_gdm_grade": "Ex"}
        g = fsv_grade_gate(multi_ok, threshold="VG")
        assert g["pass"] is True and g["threshold"] == "VG"
        # 降级：段不可用 / 缺失 / 空等级 / 未知门限——一律 pass=None
        for section in ({"ok": False, "error": "点数不足"}, None, {},
                        {"ok": True, "entries": {}, "worst_gdm_grade": None}):
            g = fsv_grade_gate(section)
            assert g["pass"] is None and g["degraded"] is True
            assert g["grade"] is None and g["reason"]
        g = fsv_grade_gate({"ok": True, "gdm_grade": "Ex"}, threshold="Z")
        assert g["pass"] is None and g["degraded"] is True
        json.dumps(g)

    def test_gate_line_renders_pass_fail_degraded(self):
        from rfauto.service.calibration_service import _fsv_gate_summary_line

        assert "降级" in _fsv_gate_summary_line(
            {"degraded": True, "reason": "点数不足"})
        assert "PASS" in _fsv_gate_summary_line(
            {"degraded": False, "pass": True, "grade": "F", "threshold": "F"})
        assert "FAIL" in _fsv_gate_summary_line(
            {"degraded": False, "pass": False, "grade": "VP",
             "threshold": "F"})

    def test_calibration_gate_wiring_with_16_validation_points(
            self, tmp_path, monkeypatch):
        """集成：n_validation=16（≥MIN_POINTS）→ FSV 门真实参与 verdict。

        fake 校准接线实测（seed=42 确定性）。2026-09-23 fake 位置锚 3.54
        （乘法缩放 K=3.54/2.725，用户拍板）落配置后带内响应平滑化：实测
        worst GDM=VG（门内）、LOOCV ρ≈0.883 ≥ 0.8 → verdict=PASS——门参与
        判定与 gate.json/report 同步仍端到端覆盖。旧锚口径（GDM=F 边界、
        ρ≈0.633、verdict=FAIL）的"门通过不掩盖 base FAIL"路径改由下方
        两条注入式单测覆盖（不依赖 fake 响应数值，锚再变也不漂）。
        runs/fake_anchor_354/criteria.md §4。
        """
        monkeypatch.chdir(tmp_path)
        from rfauto.service.calibration_service import calibrate_surrogate

        result = calibrate_surrogate(_calib_recipe(tmp_path), sampler="fake",
                                     n_levels=3, n_validation=16)
        assert result["ok"], result.get("errors")
        gate = result["fsv_gate"]
        assert gate["degraded"] is False
        assert gate["grade"] == "VG"         # 实测内核等级（seed 确定性；旧锚 F）
        assert gate["pass"] is True          # VG 在门限 F 内
        assert result["fsv_validation"]["ok"] is True
        assert result["fsv_validation"]["worst_gdm_grade"] == "VG"
        # 绿 base（ρ≥0.8）+ 门通过 → PASS
        assert result["loocv"]["rho"] >= 0.8
        assert result["verdict"] == "PASS"
        calib = tmp_path / "runs" / result["run_id"] / "calibration"
        gate_json = json.loads(
            (calib / "gate.json").read_text(encoding="utf-8"))
        assert gate_json["fsv_gate"] == gate
        report = (calib / "report.md").read_text(encoding="utf-8")
        assert "FSV 等级门" in report
        json.dumps(result)

    def test_gate_pass_does_not_mask_base_fail(
            self, tmp_path, monkeypatch):
        """门通过不掩盖 base FAIL：注入 ρ=0.5（<0.8）→ verdict=FAIL（归因 ρ）。

        注入点=源模块属性（calibrate_surrogate 内 `from
        rfauto.optimization.surrogate import loocv_rho` 是调用点局部导入，
        patch 源才能生效）。FAIL 路径与 fake 响应数值解耦（2026-09-23
        位置锚落配置后由 16 点接线测试迁出，见上方 docstring）。
        """
        monkeypatch.chdir(tmp_path)
        from rfauto.service.calibration_service import calibrate_surrogate

        def _fake_loocv(samples, cost_fn, surrogate_factory):
            return {"ok": True, "rho": 0.5, "n_folds": len(samples),
                    "skipped": 0}

        monkeypatch.setattr("rfauto.optimization.surrogate.loocv_rho",
                            _fake_loocv)
        result = calibrate_surrogate(_calib_recipe(tmp_path), sampler="fake",
                                     n_levels=3, n_validation=16)
        assert result["ok"], result.get("errors")
        assert result["loocv"]["rho"] == 0.5
        assert result["fsv_gate"]["pass"] is True   # 门通过（真值 VG 门内）
        assert result["verdict"] == "FAIL"          # 不被门掩盖，归因 ρ

    def test_gate_veto_drags_green_base_to_fail(
            self, tmp_path, monkeypatch):
        """门否决（pass=False）拖垮绿 base：ρ≥0.8 仍 verdict=FAIL（§10.20 ⑥）。"""
        monkeypatch.chdir(tmp_path)
        import rfauto.service.calibration_service as calib_mod
        from rfauto.service.calibration_service import calibrate_surrogate

        real_gate = calib_mod.fsv_grade_gate

        def _veto(section, *args, **kwargs):
            g = dict(real_gate(section, *args, **kwargs))
            g["pass"] = False
            g["grade"] = "VP"
            g["reason"] = "注入否决（测试）"
            return g

        monkeypatch.setattr(calib_mod, "fsv_grade_gate", _veto)
        result = calibrate_surrogate(_calib_recipe(tmp_path), sampler="fake",
                                     n_levels=3, n_validation=16)
        assert result["ok"], result.get("errors")
        assert result["loocv"]["rho"] >= 0.8        # base 绿
        assert result["fsv_gate"]["pass"] is False  # 门否决
        assert result["verdict"] == "FAIL"


# ─── patch v2 判读复算（真实归档曲线，§10.20 ⑥ 验收）──────────────────────
# 归档：runs/20260908_122552_01847f02（openEMS 真机 16 点 sparams.csv，
# 401 频点/点；同批 18 个 work 目录中 2 个只留 simulation.py 无 Curve →
# 如实用可得的 16 条曲线）。既有判读口径 s11_db_max_in_band 是 #195 常数
# 陷阱（24 点 cost 恒定）；本组测试对照曲线级 FSV 等级。

_PATCH_RUN = (Path(__file__).resolve().parents[2]
              / "runs" / "20260908_122552_01847f02")


class TestPatchV2Recompute:
    """patch v2 归档曲线判读复算：ADM/FDM/GDM 等级输出。"""

    def test_archived_curves_give_adm_fdm_gdm_grades(self):
        from rfauto.core.fsv import GRADE_CODES, MIN_POINTS
        from rfauto.service.calibration_service import fsv_run_curve_levels

        if not _PATCH_RUN.is_dir():
            pytest.skip(f"归档 run 不存在: {_PATCH_RUN}")
        out = fsv_run_curve_levels(_PATCH_RUN, s_param="S11", db=True)
        assert out["ok"] is True, out.get("error")
        assert out["n_curves"] >= MIN_POINTS
        assert out["worst_gdm_grade"] in GRADE_CODES
        for name, entry in out["entries"].items():
            assert entry["ok"] is True, (name, entry)
            assert entry["adm_grade"] in GRADE_CODES
            assert entry["fdm_grade"] in GRADE_CODES
            assert entry["gdm_grade"] in GRADE_CODES
            assert entry["n_points"] >= MIN_POINTS
        json.dumps(out)

    def test_curve_level_signal_differs_from_degenerate_metric(self):
        """对照既有判读口径：单点指标是常数（#195），曲线级等级非退化。"""
        from rfauto.service.calibration_service import fsv_run_curve_levels
        from rfauto.service.health_service import _parse_sparams_csv

        if not _PATCH_RUN.is_dir():
            pytest.skip(f"归档 run 不存在: {_PATCH_RUN}")
        maxima = []
        for path in sorted(_PATCH_RUN.rglob("sparams.csv")):
            parsed = _parse_sparams_csv(path)
            assert parsed is not None
            freq_hz, s = parsed
            f_ghz = freq_hz * 1e-9
            mask = (f_ghz >= 1.8) & (f_ghz <= 2.1)  # 配方 objectives 带内
            maxima.append(float(np.max(20.0 * np.log10(
                np.abs(s[mask, 0, 0]) + 1e-30))))
        # 既有单点口径：带内 max 退化在 0dB 附近（常数陷阱 #195）
        assert max(maxima) - min(maxima) < 5.0, (min(maxima), max(maxima))
        out = fsv_run_curve_levels(_PATCH_RUN, s_param="S11", db=True)
        grades = {e["gdm_grade"] for e in out["entries"].values()}
        assert grades - {"Ex"}, grades  # 曲线级等级非恒真


# ─── MS-3 calibration 传参修复（规格 D-1，2026-10-02）───────────────────────
# 病灶三连修复锚（PV-005 已证：ndarray 逐频切片 → IndexError/AttributeError
# 被 except 吞成 is_calibrated=False，证据 runs/ms3_pv005）：
# ① measured=各标准件实测 Network 列表：合成 12 项误差盒 embed→校准→DUT
#    回收 max|ΔS|≤1e-9 + residual 全带 ≤−300dB；
# ② 长度不等/频率不齐显式 ValueError（不再被 except 吞）；
# ③ TRL（EightTerm 子类）switch_terms 透传；
# ④ catalog wl_2g5_solt_smoke 全链 is_calibrated=True；
# ⑤ legacy 单 MeasurementData 形态如实 is_calibrated=False + 显式原因。

_MS3_N_PTS = 201


def _ms3_media(n_pts: int = _MS3_N_PTS) -> skrf.media.DefinedGammaZ0:
    freq = skrf.Frequency(2.0, 3.0, n_pts, unit="GHz")
    return skrf.media.DefinedGammaZ0(frequency=freq, z0=50.0)


def _ms3_errbox(wg, s11m, s11p, s22m, s22p, tm,
                weak: bool = False) -> skrf.Network:
    """确定性温和误差盒（典型 VNA 量级：失配 ≤0.04、跟踪 ~0.98）。

    弱失配（weak）档把端口反射再压 10×，供 TRL 线长估计收敛（skrf
    TRLTest 同款口径）。全部系数显式给定——skrf media.random 走系统熵源
    非确定性，不能进测试锚。
    """
    s = np.zeros((len(wg.frequency.f), 2, 2), dtype=complex)
    s[:, 0, 0] = s11m * np.exp(1j * s11p)
    s[:, 1, 1] = s22m * np.exp(1j * s22p)
    s[:, 1, 0] = tm
    s[:, 0, 1] = tm
    net = skrf.Network(frequency=wg.frequency, s=s)
    if weak:
        net.s[:, 0, 0] *= 0.1
        net.s[:, 1, 1] *= 0.1
    return net


def _ms3_quadrant_measure(xf, xr, yf, yr, ntwk: skrf.Network) -> skrf.Network:
    """前向/反向误差盒拼象限（skrf SOLTTest 同款测量模型）。"""
    mf, mr = xf ** ntwk ** yf, xr ** ntwk ** yr
    m = ntwk.copy()
    m.s[:, 0, 0] = mf.s[:, 0, 0]
    m.s[:, 1, 0] = mf.s[:, 1, 0]
    m.s[:, 0, 1] = mr.s[:, 0, 1]
    m.s[:, 1, 1] = mr.s[:, 1, 1]
    return m


def _ms3_solt_fixture():
    """SOLT 锚夹具：确定性误差盒 + 4 标准件实测与 ideals（2-port 反射件）。"""
    wg = _ms3_media()
    xf = _ms3_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98)
    xr = _ms3_errbox(wg, 0.024, 1.1, 0.016, 0.7, 0.98)
    yf = _ms3_errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98)
    yr = _ms3_errbox(wg, 0.012, 0.8, 0.036, -1.2, 0.98)
    ideals = [
        wg.short(nports=2, name="short"),
        wg.open(nports=2, name="open"),
        wg.match(nports=2, name="load"),
        wg.thru(name="through"),
    ]
    measured = [_ms3_quadrant_measure(xf, xr, yf, yr, k) for k in ideals]
    kit = CalibrationKit(
        name="ms3_solt", method=CalibrationMethod.SOLT,
        standards=[CalibrationStandard(std.name, std, std.name)
                   for std in ideals])
    return wg, kit, measured, xf, xr, yf, yr


class TestMs3SoltMeasuredSemantics:
    """规格 D-1 锚：measured=各标准件实测列表的端到端语义。"""

    def test_embed_calibrate_recover_exact(self):
        """合成 12 项误差盒 embed→校准→DUT 回收：max|ΔS|≤1e-9+residual≤−300dB。"""
        from rfauto.measurement.calibration import apply_solt_calibration

        wg, kit, measured, xf, xr, yf, yr = _ms3_solt_fixture()
        dut = wg.line(35, "deg", name="dut")
        result = apply_solt_calibration(
            measured, kit, dut=_ms3_quadrant_measure(xf, xr, yf, yr, dut))
        assert result.is_calibrated is True
        assert result.method == CalibrationMethod.SOLT
        max_ds = float(np.max(np.abs(result.calibrated_network.s - dut.s)))
        assert max_ds <= 1e-9, max_ds
        residual_db = max(20.0 * np.log10(float(np.max(np.abs(n.s))))
                          for n in result.skrf_cal.residual_ntwks)
        assert residual_db <= -300.0, residual_db

    def test_dut_list_uses_apply_cal_to_list(self):
        """dut 为列表 → apply_cal_to_list 路径，逐个回收，calibrated_network=None。"""
        from rfauto.measurement.calibration import apply_solt_calibration

        wg, kit, measured, xf, xr, yf, yr = _ms3_solt_fixture()
        duts = [wg.line(20, "deg"), wg.line(40, "deg")]
        meas = [_ms3_quadrant_measure(xf, xr, yf, yr, k) for k in duts]
        result = apply_solt_calibration(measured, kit, dut=meas)
        assert result.is_calibrated is True
        assert result.calibrated_network is None
        assert result.calibrated_networks is not None
        assert len(result.calibrated_networks) == 2
        for got, want in zip(result.calibrated_networks, duts, strict=True):
            assert float(np.max(np.abs(got.s - want.s))) <= 1e-9

    def test_single_network_normalized_then_length_error(self):
        """传单 Network 包成列表（向后兼容归一，docstring 注明）→ 数量校验显式报错。"""
        from rfauto.measurement.calibration import apply_solt_calibration

        _, kit, measured, *_ = _ms3_solt_fixture()
        with pytest.raises(ValueError, match="长度与标准件数不等"):
            apply_solt_calibration(measured[0], kit)

    def test_length_mismatch_raises(self):
        """长度失配显式 ValueError（规格 D-1 锚），不再被 except 吞。"""
        from rfauto.measurement.calibration import apply_solt_calibration

        _, kit, measured, *_ = _ms3_solt_fixture()
        with pytest.raises(ValueError, match="长度与标准件数不等"):
            apply_solt_calibration(measured[:3], kit)

    def test_frequency_mismatch_raises(self):
        """频率不齐显式 ValueError（规格 D-1 锚）。"""
        from rfauto.measurement.calibration import apply_solt_calibration

        _, kit, measured, *_ = _ms3_solt_fixture()
        bad = [k.copy() for k in measured]
        bad[0] = skrf.Network(
            frequency=skrf.Frequency(1.0, 2.0, _MS3_N_PTS, unit="GHz"),
            s=bad[0].s, z0=50.0)
        with pytest.raises(ValueError, match="频率不齐"):
            apply_solt_calibration(bad, kit)

    def test_legacy_dut_only_shape_reports_explicit_reason(self):
        """legacy 单 MeasurementData 形态：如实 is_calibrated=False+显式原因。"""
        result = apply_calibration(_make_measurement(),
                                   _make_calkit(CalibrationMethod.SOLT))
        assert result.is_calibrated is False
        assert "各标准件实测" in result.error_terms["error"]
        # 原样返回（调用方拿原网络继续比对，与 vna_capture 链兼容）
        assert result.calibrated_network is not None


class TestMs3TrlSwitchTerms:
    """规格 D-1 锚：TRL（EightTerm 子类）switch_terms 透传。"""

    @staticmethod
    def _trl_fixture():
        from skrf.calibration import terminate as skrf_terminate
        from skrf.network import two_port_reflect

        wg = _ms3_media(101)
        x = _ms3_errbox(wg, 0.02, 0.3, 0.032, -0.5, 0.98, weak=True)
        y = _ms3_errbox(wg, 0.028, -0.9, 0.02, 0.2, 0.98, weak=True)
        gf = _ms3_errbox(wg, 0.10, 0.5, 0.0, 0.0, 0.0).s11
        gr = _ms3_errbox(wg, 0.12, -0.7, 0.0, 0.0, 0.0).s11
        actuals = [
            wg.thru(name="through"),
            two_port_reflect(wg.load(-0.9 - 0.1j), wg.load(-0.9 - 0.1j),
                             name="reflect"),
            wg.line(45, "deg", name="line"),
        ]
        ideals = [
            wg.thru(name="through"),
            wg.short(nports=2, name="reflect"),
            wg.line(90, "deg", name="line"),
        ]
        measured = [skrf_terminate(x ** k ** y, gf, gr) for k in actuals]
        kit = CalibrationKit(
            name="ms3_trl", method=CalibrationMethod.TRL,
            standards=[CalibrationStandard(std.name, std, std.name)
                       for std in ideals])
        return wg, kit, measured, x, y, gf, gr, skrf_terminate

    def test_switch_terms_passthrough_recovers_exact(self):
        """带 switch terms：开关项透传 skrf TRL → DUT 精确回收（max|ΔS|≤1e-9）。"""
        from rfauto.measurement.calibration import apply_trl_calibration

        wg, kit, measured, x, y, gf, gr, term = self._trl_fixture()
        dut = wg.line(25, "deg", name="dut")
        result = apply_trl_calibration(
            measured, kit, dut=term(x ** dut ** y, gf, gr),
            switch_terms=(gf, gr))
        assert result.is_calibrated is True
        assert result.error_terms["switch_terms"] is True
        max_ds = float(np.max(np.abs(result.calibrated_network.s - dut.s)))
        assert max_ds <= 1e-9, max_ds

    def test_without_switch_terms_skrf_warns_and_recovery_degrades(self):
        """不带 switch terms：skrf UserWarning+回收显著失真——透传不可省的实证。"""
        from rfauto.measurement.calibration import apply_trl_calibration

        wg, kit, measured, x, y, gf, gr, term = self._trl_fixture()
        dut = wg.line(25, "deg", name="dut")
        dut_meas = term(x ** dut ** y, gf, gr)
        with pytest.warns(UserWarning, match="switch"):
            result = apply_trl_calibration(measured, kit, dut=dut_meas)
        assert result.error_terms["switch_terms"] is None
        max_ds = float(np.max(np.abs(result.calibrated_network.s - dut.s)))
        assert max_ds > 1e-3, max_ds


class TestMs3CatalogSoltSmoke:
    """规格 D-1 锚：catalog wl_2g5_solt_smoke 全链 is_calibrated=True。"""

    @staticmethod
    def _two_port_diag(net: skrf.Network) -> skrf.Network:
        """1-port 标准件 → 双端口同反射 2-port（VNA 双口实测口径）。

        catalog 反射件目前是合成理想 .s1p；skrf SOLT 契约要求双端口
        （TwelveTerm.run 读 s11/s22 两个口径），此包裹是测试脚手架，
        与 skrf media.short(nports=2) 的双端口同反射语义一致。
        """
        s = np.zeros((len(net.f), 2, 2), dtype=complex)
        s[:, 0, 0] = net.s[:, 0, 0]
        s[:, 1, 1] = net.s[:, 0, 0]
        return skrf.Network(frequency=net.frequency, s=s, z0=50.0,
                            name=net.name)

    def test_catalog_full_chain_is_calibrated(self):
        from rfauto.measurement.calibration import (
            apply_solt_calibration,
            load_calkit,
        )

        kit = load_calkit("wl_2g5_solt_smoke")
        assert kit.method == CalibrationMethod.SOLT
        by_type = {s.standard_type: s.network for s in kit.standards}
        order = ["short", "open", "load", "through"]
        ideals = [self._two_port_diag(by_type[t]) if by_type[t].nports == 1
                  else by_type[t] for t in order]
        # 冒烟链：合成理想标准件 measured=ideals（零误差盒）→ 恒等校准
        result = apply_solt_calibration(
            [k.copy() for k in ideals], kit, dut=by_type["through"].copy())
        assert result.is_calibrated is True
        assert result.skrf_cal is not None
        dut = by_type["through"]
        assert float(np.max(np.abs(result.calibrated_network.s - dut.s))) == 0.0



def test_compare_surrogates_rho_zero_kept_not_replaced(tmp_path, monkeypatch):
    """R3-5 回归钉：合法 rho=0.0 不被 `or -1` 惯语顶替（#117/#364 家族）。

    排序键改 `is not None` 判缺后：rho=0.0（键 0.0）> rho=-0.5（键 -0.5），
    ranking 为 [poly_ridge, nn]；旧代码 0.0→-1.0 会被 -0.5 反超（本钉必红）。
    门判定（0.0 < 0.8 → FAIL）结果中性面保持不变。
    """
    from rfauto.optimization import surrogate as surrogate_mod
    from rfauto.service.calibration_service import compare_surrogates

    path = tmp_path / "samples.json"
    path.write_text(json.dumps({
        "bounds": {"x": [0.0, 1.0]},
        "objectives": [],
        "samples": [{"params": {"x": 0.5}, "metrics": {}},
                    {"params": {"x": 0.6}, "metrics": {}},
                    {"params": {"x": 0.7}, "metrics": {}}],
    }), encoding="utf-8")
    rhos = iter([0.0, -0.5])

    def fake_loocv(samples, cost_fn, surrogate_factory):
        return {"ok": True, "rho": next(rhos)}

    monkeypatch.setattr(surrogate_mod, "loocv_rho", fake_loocv)
    r = compare_surrogates(path, kinds=("poly_ridge", "nn"))
    assert r["ok"], r
    assert [row["rho"] for row in r["results"]] == [0.0, -0.5]
    assert r["ranking"] == ["poly_ridge", "nn"]  # 0.0 > -0.5（旧码反转）
    assert r["results"][0]["gate"] == "FAIL"  # 0.0 < 0.8：门语义不变


class TestTwoPortSameReflectZ0Guard:
    """S-1 C-04 2026-10-04：_two_port_same_reflect 的复 z0 显式校验。

    旧实现 ``float(net.z0[0][0])`` 对复参考阻抗静默丢虚部（复 dtype 下以
    TypeError/截断形态炸或失真）；现 |imag|>1e-9 显式 ValueError（带实测值
    回显），容差内按实数舍入残差处理。"""

    def _one_port(self, z0) -> skrf.Network:
        freq = skrf.Frequency(1, 3, 5, unit="GHz")
        s = np.zeros((5, 1, 1), dtype=complex)
        s[:, 0, 0] = 0.5
        return skrf.Network(frequency=freq, s=s, z0=z0)

    def test_complex_z0_raises_with_measured_value(self):
        from rfauto.measurement.calibration import _two_port_same_reflect
        net = self._one_port(50.0 + 3.0j)
        with pytest.raises(ValueError, match=r"50(\.0)?\+3j"):
            _two_port_same_reflect(net)

    def test_tiny_imag_treated_as_rounding_residue(self):
        from rfauto.measurement.calibration import _two_port_same_reflect
        net = self._one_port(50.0 + 1e-12j)
        out = _two_port_same_reflect(net)
        assert np.allclose(out.z0, 50.0)
        assert out.s.shape == (5, 2, 2)

    def test_real_z0_unchanged(self):
        from rfauto.measurement.calibration import _two_port_same_reflect
        net = self._one_port(50.0)
        out = _two_port_same_reflect(net)
        assert np.allclose(out.z0, 50.0)
        # 双端口同反射：对角取 1-port s11
        assert np.allclose(out.s[:, 0, 0], 0.5)
        assert np.allclose(out.s[:, 1, 1], 0.5)
