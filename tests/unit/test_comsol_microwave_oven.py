"""a6-mwoven COMSOL 官方 Microwave Oven 例复现单测（离线确定性）。

零 COMSOL / license / JVM 依赖：MPh 与适配器的 Java 调用全部用记录桩，
脚本真机路径 run_real 不执行（真机证据另落 runs/comsol_microwave_oven/）。

覆盖三层：
A. 多物理纯函数（study 步序列/清单校验/温度统计/能量守恒/官方对照/球体
   教科书闭式裁判）；
B. 适配器多物理 Java 序列（ht 接口 + 默认初始值复用 + 兜底新建、emw->ht
   单向耦合、对流热边界、Frequency-Stationary / Frequency-Transient study、
   IntVolume/MaxVolume/MinVolume/AvVolume 结果特征解析）；
C. 脚本离线面（官方参数集与官方 parameters.txt 对账、参数表达式、几何包围盒、
   选择盒、计划报告、build_oven_model Java 序列、evaluate_oven 判定、CLI）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import comsol_microwave_oven as mo

REPO = Path(__file__).resolve().parents[2]
OFFICIAL_PARAMS_TXT = Path(
    r"E:\COMSOL\COMSOL_63\COMSOL63\Multiphysics\applications"
    r"\RF_Module\Microwave_Heating\microwave_oven_parameters.txt")

# ─── Java 链式调用记录桩 ─────────────────────────────────────────────────────


class _Recorder:
    """任意属性 → 可调用 → 返回子桩；调用以 (路径, 参数) 记入共享列表。

    getReal/getImag 按调用顺序从预置队列弹出：队列元素即该次调用的返回值
    （行=表达式、列=解号，官方口径）；raise_on 里的属性名会抛异常
    （覆盖 best-effort / 兜底分支）。
    """

    def __init__(self, calls: list, real: list, imag: list | None = None,
                 tags: tuple = ("dset1",), path: str = "",
                 raise_on: tuple = ()) -> None:
        self._calls = calls
        self._real = real
        self._imag = imag if imag is not None else []
        self._tags = tags
        self._path = path
        self._raise_on = raise_on

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args):
            full = f"{self._path}.{name}" if self._path else name
            self._calls.append((full, args))
            if name in self._raise_on:
                raise RuntimeError(f"stub raise: {name}")
            if name == "getReal":
                return self._real.pop(0)
            if name == "getImag":
                return self._imag.pop(0)
            if name == "tags":
                return list(self._tags)
            return _Recorder(self._calls, self._real, self._imag, self._tags,
                             full, self._raise_on)

        return _call


class _StubModel:
    def __init__(self, calls, real, imag=None, tags=("dset1",),
                 raise_on=(), field=None, datasets=(),
                 field_by_dataset=None) -> None:
        self.java = _Recorder(calls, real, imag, tags, raise_on=raise_on)
        self.saved: list[str] = []
        self._field = field
        self._datasets = list(datasets)
        self._field_by_dataset = dict(field_by_dataset or {})

    def save(self, path):
        self.saved.append(str(path))

    def datasets(self):
        return list(self._datasets)

    def evaluate(self, expression, unit=None, dataset=None):
        if dataset is not None and dataset in self._field_by_dataset:
            return self._field_by_dataset[dataset]
        if isinstance(self._field, Exception):
            raise self._field
        return self._field


class _StubClient:
    def __init__(self, model) -> None:
        self._model = model
        self.created: list[str] = []
        self.removed: list = []

    def create(self, name):
        self.created.append(name)
        return self._model

    def remove(self, model):
        self.removed.append(model)


def _args(calls, suffix):
    """路径以 suffix 结尾的调用的实参元组列表。"""
    return [a for n, a in calls if n.endswith(suffix)]


def _creates(calls):
    """所有 *create(...) 调用的实参元组（特征/几何/网格/study 步）。"""
    return [a for n, a in calls if n.endswith("create")]


def _sets(calls):
    return _args(calls, ".set")


def _multiples(calls, kinds):
    """按 create 实参的类型串计数（如 physics.create.create 的 "Impedance"）。"""
    return [a[1] for a in _creates(calls) if len(a) >= 2 and a[0] not in kinds]


@pytest.fixture
def oven_spec():
    return mo.normalize_oven_params(None)


@pytest.fixture
def oven_opts():
    return {"thermal": "stationary", "h_conv_w_m2k": 10.0, "t_ext_degc": 8.0,
            "mesh_hmax_mm": 15.0, "potato_hmax_mm": 3.0, "t_list": "range(0,1,5)"}


# ─── A. 适配器多物理纯函数 ───────────────────────────────────────────────────


class TestStudyPlan:
    def test_step_sequences_match_official_type_strings(self):
        assert ca.study_step_plan("frequency") == (("freq", "Frequency"),)
        assert ca.study_step_plan("frequency_stationary") == (
            ("freq", "Frequency"), ("stat", "Stationary"))
        assert ca.study_step_plan("frequency_transient") == (
            ("freq", "Frequency"), ("time", "Transient"))
        # 时间步类型串是 Transient（官方 oven StudyFeature op），不是 TimeDependent
        assert ca.STUDY_STEP_TRANSIENT == "Transient"
        assert ca.STUDY_STEP_TRANSIENT != "TimeDependent"

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="study_kind"):
            ca.study_step_plan("time_dependent")


class TestMultiphysicsList:
    def test_default_is_emw_plus_ht(self):
        assert ca.normalize_multiphysics(None) == ("emw", "ht")

    def test_dedup_and_solid_support(self):
        assert ca.normalize_multiphysics(["emw", "ht", "ht", "solid"]) == (
            "emw", "ht", "solid")

    def test_unknown_and_missing_emw_rejected(self):
        with pytest.raises(ValueError, match="不支持的多物理接口"):
            ca.normalize_multiphysics(["emw", "acdc"])
        with pytest.raises(ValueError, match="必须含 emw"):
            ca.normalize_multiphysics(["ht"])


class TestThermalJudges:
    def test_temperature_summary_and_guards(self):
        stats = ca.temperature_summary([10.0, 20.0, 30.0])
        assert stats == {"n_points": 3, "t_max_c": 30.0, "t_min_c": 10.0,
                         "t_mean_c": 20.0}
        with pytest.raises(ValueError, match="非有限值"):
            ca.temperature_summary([1.0, float("nan")])
        with pytest.raises(ValueError, match="为空"):
            ca.temperature_summary([])

    def test_temperature_record_order_guard(self):
        assert ca.temperature_record(250.0, 9.0, 120.0)["t_max_c"] == 250.0
        with pytest.raises(ValueError, match="序关系"):
            ca.temperature_record(100.0, 9.0, 200.0)

    def test_energy_balance_official_fraction(self):
        balance = ca.energy_balance(1000.0, 631.0)
        assert balance["p_reflected_w"] == pytest.approx(369.0)
        assert balance["absorbed_fraction"] == pytest.approx(0.631)
        assert balance["conserved"] is True and balance["passive"] is True
        # 吸收超过输入 = 非物理（无源器件不可能）
        assert ca.energy_balance(1000.0, 1010.0)["conserved"] is False
        with pytest.raises(ValueError, match="输入功率"):
            ca.energy_balance(0.0, 1.0)

    def test_reference_agreement_gate(self):
        assert ca.reference_agreement(631.0, 631.0)["ok"] is True
        in_gate = ca.reference_agreement(660.5, 631.0)  # +4.7% 在 ±5% 门内
        assert in_gate["ok"] is True and in_gate["rel_deviation"] < 0.05
        out_of_gate = ca.reference_agreement(680.0, 631.0)  # +7.8% 超门
        assert out_of_gate["ok"] is False and out_of_gate["rel_deviation"] > 0.05
        with pytest.raises(ValueError, match="参考值不能为 0"):
            ca.reference_agreement(1.0, 0.0)

    def test_sphere_textbook_closed_form(self):
        # Incropera & DeWitt / Carslaw & Jaeger：同心球均匀源稳态
        # T_center-T_inf = q a^2/(6k) [+ q a/(3h)]
        # 手算：q=1e6 W/m^3, a=0.05 m, k=1.0 W/(m*K)
        #   纯导热项 = 1e6*0.0025/6 = 416.6667 K
        pure = ca.sphere_uniform_source_center_excess(1.0e6, 0.05, 1.0)
        assert pure == pytest.approx(416.6666666667, rel=1e-9)
        #   叠加 h=10 W/(m^2*K) 薄膜项 q a/(3h) = 1e6*0.05/30 = 1666.6667 K
        total = ca.sphere_uniform_source_center_excess(1.0e6, 0.05, 1.0, 10.0)
        assert total == pytest.approx(2083.3333333333, rel=1e-9)
        with pytest.raises(ValueError, match="对流系数"):
            ca.sphere_uniform_source_center_excess(1.0e6, 0.05, 1.0, 0.0)
        with pytest.raises(ValueError, match="参数非法"):
            ca.sphere_uniform_source_center_excess(1.0e6, -1.0, 1.0)


class TestEnergyAnchors:
    """§10.24 d3-2：能量守恒自洽锚（替代官方缺失的温度场标量，如实非官方）。"""

    def test_transient_anchor_exact_closure_official_numbers(self, oven_spec):
        # 官方口径：P=631 W，Δt=5 s（range(0,1,5)），m=rho*V，Cp=3.64e3
        m = mo.potato_mass_kg(oven_spec)
        assert m == pytest.approx(1050.0 * 4.0 / 3.0 * np.pi * 0.0315 ** 3,
                                  rel=1e-12)
        predicted = 631.0 * 5.0 / (m * mo.POTATO_CP_J_KG_K)
        anchor = ca.transient_energy_anchor(
            631.0, 5.0, m, mo.POTATO_CP_J_KG_K, mo.MICROWAVE_OVEN_DEFAULTS[
                "t0_degc"] + predicted, mo.MICROWAVE_OVEN_DEFAULTS["t0_degc"])
        assert anchor["predicted_delta_t_k"] == pytest.approx(predicted)
        assert anchor["measured_delta_t_k"] == pytest.approx(predicted)
        assert anchor["rel_deviation"] == pytest.approx(0.0)
        assert anchor["ok"] is True
        # 如实标注：自洽锚、非官方
        assert anchor["official"] is False
        assert anchor["anchor"] == "self_consistency_energy_adiabatic"
        assert "非官方" in anchor["note"]

    def test_transient_anchor_official_expected_mean_rise_scale(self, oven_spec):
        # 官方 631 W × 5 s 的绝热平均温升量级（数量级手算 ~6.3 K）
        m = mo.potato_mass_kg(oven_spec)
        predicted = 631.0 * 5.0 / (m * mo.POTATO_CP_J_KG_K)
        assert 5.0 < predicted < 8.0

    def test_transient_anchor_breach_and_tolerance_boundary(self):
        m, cp = 0.5, 3640.0
        predicted = 631.0 * 5.0 / (m * cp)
        t0 = 8.0
        # 门语义在 ±5% 处翻转（+4% ok / +6% 超门；避开 0.05 浮点边界进位）
        ok_inside = ca.transient_energy_anchor(631.0, 5.0, m, cp,
                                               t0 + predicted * 1.04, t0)
        assert ok_inside["ok"] is True
        assert ok_inside["rel_deviation"] == pytest.approx(0.04)
        bad_edge = ca.transient_energy_anchor(631.0, 5.0, m, cp,
                                              t0 + predicted * 1.06, t0)
        assert bad_edge["ok"] is False
        assert bad_edge["rel_deviation"] == pytest.approx(0.06)
        # +20% 超门
        bad = ca.transient_energy_anchor(631.0, 5.0, m, cp,
                                         t0 + predicted * 1.2, t0)
        assert bad["ok"] is False and bad["rel_deviation"] == pytest.approx(0.2)

    def test_transient_anchor_validation(self):
        with pytest.raises(ValueError, match="正有限值"):
            ca.transient_energy_anchor(631.0, 5.0, 0.0, 3640.0, 14.0, 8.0)
        with pytest.raises(ValueError, match="正有限值"):
            ca.transient_energy_anchor(-1.0, 5.0, 0.5, 3640.0, 14.0, 8.0)
        with pytest.raises(ValueError, match="有限值"):
            ca.transient_energy_anchor(631.0, 5.0, 0.5, 3640.0, float("nan"),
                                       8.0)

    def test_energy_closure_exact_and_boundary(self):
        closure = ca.energy_closure(631.0, 631.0)
        assert closure["rel_deviation"] == pytest.approx(0.0)
        assert closure["ok"] is True
        assert closure["official"] is False
        assert closure["anchor"] == "self_consistency_energy_stationary_closure"
        # 门语义在 ±5% 处翻转（4% ok / 6% 超门；避开 0.05 浮点边界进位）
        assert ca.energy_closure(631.0, 631.0 * 1.04)["ok"] is True
        assert ca.energy_closure(631.0, 631.0 * 1.06)["ok"] is False
        assert ca.energy_closure(631.0, 631.0 * 0.90)["ok"] is False
        with pytest.raises(ValueError, match="吸收功率必须为正"):
            ca.energy_closure(0.0, 1.0)
        with pytest.raises(ValueError, match="有限值"):
            ca.energy_closure(float("nan"), 1.0)


# ─── B. 适配器多物理 Java 序列 ───────────────────────────────────────────────


class TestAdapterMultiphysicsBuilders:
    def test_add_heat_transfer_uses_existing_default_init(self):
        calls: list = []
        comp = _Recorder(calls, [])
        ca.ComsolAdapter.add_heat_transfer(comp, selection="sel_potato",
                                           t_init="T0")
        assert _args(calls, "physics.create")[0] == (
            "ht", "HeatTransfer", "geom1")
        assert ("sel_potato",) in _args(calls, "selection.named")
        # 默认初始值特征已被接口自动创建 -> 复用而非新建（避免 feature exists）
        assert ("init1",) in _args(calls, "feature")
        assert ("Tinit", "T0") in _sets(calls)
        assert ("init1", "init", 3) not in _creates(calls)

    def test_add_heat_transfer_creates_init_when_missing(self):
        calls: list = []
        comp = _Recorder(calls, [], raise_on=("feature",))
        ca.ComsolAdapter.add_heat_transfer(comp, t_init="T0", selection=None)
        assert ("init1", "init", 3) in _creates(calls)
        assert ("Tinit", "T0") in _sets(calls)

    def test_add_solid_and_coupling(self):
        calls: list = []
        comp = _Recorder(calls, [])
        ca.ComsolAdapter.add_solid_mechanics(comp)
        ca.ComsolAdapter.add_electromagnetic_heating(comp)
        assert ("solid", "SolidMechanics", "geom1") in _args(
            calls, "physics.create")
        assert ("emh1", "ElectromagneticHeating", 3) in _args(
            calls, "multiphysics.create")
        sets = _sets(calls)
        assert ("EMHeat_physics", "emw") in sets
        assert ("Heat_physics", "ht") in sets

    def test_add_convective_heat_flux_properties(self):
        calls: list = []
        ht = _Recorder(calls, [])
        ca.ComsolAdapter.add_convective_heat_flux(
            ht, selection="sel_potato_surface", h_expr="hconv",
            t_ext_expr="Text")
        assert ("hf_conv", "HeatFluxBoundary", 2) in _creates(calls)
        assert ("sel_potato_surface",) in _args(calls, "selection.named")
        sets = _sets(calls)
        assert ("HeatFluxType", "ConvectiveHeatFlux") in sets
        assert ("HeatTransferCoefficientType", "UserDef") in sets
        assert ("h", "hconv") in sets and ("Text", "Text") in sets


class TestBuildMultiphysicsStudy:
    def test_frequency_stationary_sequence(self):
        calls: list = []
        j = _Recorder(calls, [])
        ca.ComsolAdapter.build_multiphysics_study(
            j, study_kind="frequency_stationary", freqs_ghz=[2.45],
            thermal_physics=("ht",))
        creates = _args(calls, "study.create")
        assert creates[0] == ("std1",)
        assert ("freq", "Frequency") in creates
        assert ("stat", "Stationary") in creates
        sets = _sets(calls)
        assert ("plist", "2.45[GHz]") in sets
        # 只列真实存在的接口（真机 run1 实证：多写不存在的 tag / 追加 frame
        # 项都会被 COMSOL 判「属性值无效」）
        assert ("activate", ["emw", "off", "ht", "on"]) in sets
        assert ("activateCoupling", ["emh1", "on"]) in sets

    def test_frequency_transient_sequence_sets_tlist(self):
        calls: list = []
        j = _Recorder(calls, [])
        ca.ComsolAdapter.build_multiphysics_study(
            j, study_kind="frequency_transient", freqs_ghz=[2.45],
            t_list="range(0,1,5)", thermal_physics=("ht",))
        creates = _args(calls, "study.create")
        assert ("time", "Transient") in creates
        assert ("tlist", "range(0,1,5)") in _sets(calls)

    def test_frequency_only_has_no_activate(self):
        calls: list = []
        j = _Recorder(calls, [])
        ca.ComsolAdapter.build_multiphysics_study(
            j, study_kind="frequency", freqs_ghz=[2.45])
        creates = _args(calls, "study.create")
        assert creates == [("std1",), ("freq", "Frequency")]
        assert all(k != "activate" for k, _ in _sets(calls))


class TestResultExtraction:
    def test_evaluate_volume_series_java_contract(self):
        calls: list = []
        model = _StubModel(calls, [[[631.0]]])
        series = ca.ComsolAdapter.evaluate_volume_series(
            model, tag="int_pabs", kind=ca.RESULT_INT_VOLUME,
            expr="ht.Qtot", selection="sel_potato", unit="W", solution="all")
        assert np.allclose(series, [631.0])
        assert ("int_pabs", "IntVolume") in _args(calls, "numerical.create")
        assert ("sel_potato",) in _args(calls, "selection.named")
        sets = _sets(calls)
        assert ("expr", ["ht.Qtot"]) in sets
        assert ("unit", ["W"]) in sets
        assert ("innerinput", "all") in sets

    def test_evaluate_volume_series_rejects_bad_kind_and_empty(self):
        model = _StubModel([], [[[1.0]]])
        with pytest.raises(ValueError, match="结果特征类型"):
            ca.ComsolAdapter.evaluate_volume_series(
                model, tag="t", kind="EvalGlobal", expr="T")
        empty = _StubModel([], [[]])
        with pytest.raises(RuntimeError, match="未返回任何数值"):
            ca.ComsolAdapter.evaluate_volume_series(
                empty, tag="t", kind=ca.RESULT_MAX_VOLUME, expr="T")

    def test_extract_absorbed_power_and_temperature(self):
        model = _StubModel([], [[[631.0]], [[250.0]], [[9.0]], [[120.0]]])
        p_abs = ca.ComsolAdapter.extract_absorbed_power(
            model, selection="sel_potato")
        assert p_abs == pytest.approx(631.0)
        temp = ca.ComsolAdapter.extract_temperature(model, selection="sel_potato")
        assert temp == {"t_max_c": 250.0, "t_min_c": 9.0, "t_avg_c": 120.0}

    def test_extract_temperature_order_violation_raises(self):
        model = _StubModel([], [[[100.0]], [[9.0]], [[200.0]]])
        with pytest.raises(ValueError, match="序关系"):
            ca.ComsolAdapter.extract_temperature(model, selection="sel_potato")

    def test_temperature_field_best_effort(self):
        ok = _StubModel([], [], field=np.array([10.0, 20.0]))
        assert np.allclose(ca.ComsolAdapter.temperature_field(ok), [10.0, 20.0])
        boom = _StubModel([], [], field=RuntimeError("no dataset"))
        assert ca.ComsolAdapter.temperature_field(boom) is None
        junk = _StubModel([], [], field=object())
        assert ca.ComsolAdapter.temperature_field(junk) is None

    def test_temperature_field_skips_nan_and_retries_datasets(self):
        # 真机 run3 实证：默认数据集可能是 emw 频域解 -> T 全 NaN
        nan_default = _StubModel(
            [], [], field=np.full(4, np.nan),
            datasets=["研究 1/解 1", "研究 1/解 2"],
            field_by_dataset={"研究 1/解 2": np.array([30.0, 40.0])})
        field = ca.ComsolAdapter.temperature_field(nan_default)
        assert field is not None and np.allclose(field, [30.0, 40.0])
        # 所有数据集都非有限 -> None（不把 NaN 当温度场）
        all_nan = _StubModel([], [], field=np.full(4, np.nan),
                             datasets=["a", "b"])
        assert ca.ComsolAdapter.temperature_field(all_nan) is None

    def test_evaluate_point_series_java_contract(self):
        # §10.24：CutPoint3D(pointx/pointy/pointz 官方 dmodel 实录) + EvalPoint
        # getReal 队列元素：行=表达式、列=解号（单表达式 → 1×n_times）
        calls: list = []
        model = _StubModel(calls, [[[14.0, 20.0]]])
        series = ca.ComsolAdapter.evaluate_point_series(
            model, expr="T", point_exprs=("wo/2", "0", "rpot+bp+hp"),
            unit="degC", tag="pt_probe")
        assert np.allclose(series, [14.0, 20.0])
        assert ("pt_probe_cpt", ca.DATASET_CUT_POINT_3D) in _args(
            calls, "dataset.create")
        assert ("pt_probe_ev", ca.RESULT_EVAL_POINT) in _args(
            calls, "numerical.create")
        sets = _sets(calls)
        assert ("pointx", "wo/2") in sets
        assert ("pointy", "0") in sets
        assert ("pointz", "rpot+bp+hp") in sets
        assert ("data", "pt_probe_cpt") in sets
        assert ("expr", ["T"]) in sets
        assert ("unit", ["degC"]) in sets
        assert ("innerinput", "all") in sets

    def test_evaluate_point_series_with_explicit_dataset_and_empty(self):
        calls: list = []
        model = _StubModel(calls, [[[50.0]]])
        series = ca.ComsolAdapter.evaluate_point_series(
            model, expr="T", point_exprs=("x", "y", "z"), dataset="dset2",
            tag="p")
        assert np.allclose(series, [50.0])
        assert ("data", "dset2") in _sets(calls)
        empty = _StubModel([], [[]])
        with pytest.raises(RuntimeError, match="EvalPoint 未返回任何数值"):
            ca.ComsolAdapter.evaluate_point_series(
                empty, expr="T", point_exprs=("x", "y", "z"))

    def test_extract_surface_integral_java_contract(self):
        # §10.24：IntSurface（边界积分）走 evaluate_volume_series 白名单
        calls: list = []
        model = _StubModel(calls, [[[630.1]]])
        value = ca.ComsolAdapter.extract_surface_integral(
            model, selection="sel_potato_surface", expr="ht.ntflux", unit="W",
            tag="int_qout")
        assert value == pytest.approx(630.1)
        assert ("int_qout", ca.RESULT_INT_SURFACE) in _args(
            calls, "numerical.create")
        assert ("sel_potato_surface",) in _args(calls, "selection.named")
        sets = _sets(calls)
        assert ("expr", ["ht.ntflux"]) in sets and ("unit", ["W"]) in sets

    def test_evaluate_volume_series_accepts_int_surface(self):
        model = _StubModel([], [[[42.0]]])
        series = ca.ComsolAdapter.evaluate_volume_series(
            model, tag="t", kind=ca.RESULT_INT_SURFACE, expr="ht.ntflux")
        assert np.allclose(series, [42.0])


# ─── C. 脚本离线面 ───────────────────────────────────────────────────────────


class TestOfficialParameters:
    def test_defaults_pin_official_parameter_file(self):
        assert mo.MICROWAVE_OVEN_DEFAULTS == {
            "wo_mm": 267.0, "do_mm": 270.0, "ho_mm": 188.0,
            "wg_mm": 50.0, "dg_mm": 78.0, "hg_mm": 18.0,
            "rp_mm": 113.5, "hp_mm": 6.0, "bp_mm": 15.0,
            "rpot_mm": 31.5, "t0_degc": 8.0,
            "freq_ghz": 2.45, "pin_w": 1000.0,
        }
        assert mo.OFFICIAL_ABSORBED_POWER_W == 631.0
        assert mo.OFFICIAL_HALF_MODEL_POWER_W == 314.0
        assert mo.ACCEPTANCE_TOL == 0.05

    @pytest.mark.skipif(not OFFICIAL_PARAMS_TXT.exists(),
                        reason="本机无 COMSOL 官方例参数文件（离线环境）")
    def test_defaults_match_official_parameters_txt(self):
        names = {"wo_mm": "wo", "do_mm": "do", "ho_mm": "ho", "wg_mm": "wg",
                 "dg_mm": "dg", "hg_mm": "hg", "rp_mm": "rp", "hp_mm": "hp",
                 "bp_mm": "bp", "rpot_mm": "rpot", "t0_degc": "T0"}
        text = OFFICIAL_PARAMS_TXT.read_text(encoding="utf-8-sig")
        parsed: dict[str, float] = {}
        for line in text.splitlines():
            tokens = line.split()
            if len(tokens) >= 2 and tokens[0] in names.values():
                digits = "".join(ch for ch in tokens[1]
                                 if ch.isdigit() or ch in ".-")
                if digits:
                    parsed[tokens[0]] = float(digits)
        for key, name in names.items():
            assert name in parsed, f"官方 parameters.txt 缺项 {name}"
            assert parsed[name] == mo.MICROWAVE_OVEN_DEFAULTS[key], name

    def test_parameter_expressions_have_units(self):
        params = mo.oven_comsol_parameters(mo.normalize_oven_params(None))
        assert params["wo"] == "267[mm]" and params["rpot"] == "31.5[mm]"
        assert params["T0"] == "8[degC]" and params["freq"] == "2.45[GHz]"
        assert params["Pin"] == "1000[W]"

    def test_normalize_rejects_nonpositive(self):
        with pytest.raises(ValueError, match="必须为正有限值"):
            mo.normalize_oven_params({"rpot_mm": -1.0})
        spec = mo.normalize_oven_params(None, freq_ghz=5.8, pin_w=500.0)
        assert spec["freq_ghz"] == 5.8 and spec["pin_w"] == 500.0


class TestGeometryAndSelections:
    def test_geometry_bounds_match_official_spec(self, oven_spec):
        b = mo.geometry_bounds(oven_spec)
        assert b["oven"] == {"x": (0.0, 267.0), "y": (-135.0, 135.0),
                             "z": (0.0, 188.0)}
        assert b["waveguide"] == {"x": (-50.0, 0.0), "y": (-39.0, 39.0),
                                  "z": (170.0, 188.0)}
        assert b["plate"]["x"] == pytest.approx((20.0, 247.0))
        assert b["plate"]["z"] == pytest.approx((15.0, 21.0))
        # 土豆球心 z=rpot+bp+hp=52.5，球底与玻璃盘顶同高 21mm
        assert b["potato"]["z"] == pytest.approx((21.0, 84.0))
        assert b["potato"]["x"] == pytest.approx((102.0, 165.0))

    def test_material_selection_boxes_are_domains(self, oven_spec):
        boxes = mo.material_selection_boxes(oven_spec)
        assert set(boxes) == {"sel_potato", "sel_plate"}
        assert all(v[0] == 3 for v in boxes.values())

    def test_boundary_boxes_port_and_metals(self, oven_spec):
        boxes = mo.boundary_selection_boxes(oven_spec)
        assert all(v[0] == 2 for v in boxes.values())
        assert len([k for k in boxes if k.startswith("sel_metal_")]) == 11
        port_lo, port_hi = boxes["sel_port"][1], boxes["sel_port"][2]
        assert port_lo[0] == pytest.approx(-50.0 - 1e-3)
        assert port_hi[0] == pytest.approx(-50.0 + 1e-3)
        assert port_lo[2] == pytest.approx(170.0 - 1e-3)
        assert port_hi[2] == pytest.approx(188.0 + 1e-3)
        # 波导侧壁盒不得包含端口面 x=-50（否则端口被阻抗边界污染）
        for tag in ("sel_metal_wg_front", "sel_metal_wg_back"):
            assert boxes[tag][2][0] == 0.0

    def test_potato_volume_and_density(self, oven_spec):
        r_m = 31.5e-3
        assert mo.potato_volume_m3(oven_spec) == pytest.approx(
            4.0 / 3.0 * np.pi * r_m ** 3, rel=1e-12)
        q = mo.potato_power_density_w_m3(oven_spec, 631.0)
        assert q == pytest.approx(631.0 / mo.potato_volume_m3(oven_spec),
                                  rel=1e-12)

    def test_potato_mass_and_transient_times(self, oven_spec):
        # §10.24：质量（能量锚 m·Cp）与 tlist 末时刻（能量锚 Δt）确定性解析
        assert mo.potato_mass_kg(oven_spec) == pytest.approx(
            mo.POTATO_RHO_KG_M3 * mo.potato_volume_m3(oven_spec), rel=1e-12)
        assert mo.transient_times_s("range(0,1,5)") == [0.0, 1.0, 2.0, 3.0,
                                                        4.0, 5.0]
        assert mo.transient_times_s("range(0,0.4,1)") == [0.0, 0.4, 0.8]
        assert mo.transient_times_s("0 1 5") == [0.0, 1.0, 5.0]
        assert mo.transient_times_s(None) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        with pytest.raises(ValueError, match="步长必须为正"):
            mo.transient_times_s("range(0,0,5)")
        with pytest.raises(ValueError, match="区间为空"):
            mo.transient_times_s("range(5,1,0)")
        with pytest.raises(ValueError, match="3 个参数"):
            mo.transient_times_s("range(0,1)")

    def test_plan_report_is_json_serializable(self, oven_spec, oven_opts):
        plan = mo.plan_report(oven_spec, oven_opts)
        blob = json.dumps(plan, ensure_ascii=False)
        assert "631.0" in blob and "1424" in blob
        assert plan["official_model"]["model_number"] == 1424
        assert plan["official_model"]["acceptance_tol"] == 0.05
        # §10.24：温度参考结论与官方截点位/质量入计划
        assert "无官方标量" in plan["official_model"]["temperature_reference"]
        assert plan["official_center_point"] == ["wo/2", "0", "rpot+bp+hp"]
        assert plan["potato_mass_kg"] == pytest.approx(mo.potato_mass_kg(oven_spec))


class TestBuildOvenModelJavaSequence:
    def _built(self, oven_spec, oven_opts):
        calls: list = []
        client = _StubClient(_StubModel(calls, []))
        model = mo.build_oven_model(client, oven_spec, oven_opts)
        return model, calls

    def test_geometry_features_and_parameters(self, oven_spec, oven_opts):
        _model, calls = self._built(oven_spec, oven_opts)
        geom_creates = _args(calls, "geom.create.create")
        assert ("blk1", "Block") in geom_creates
        assert ("blk2", "Block") in geom_creates
        assert ("cyl1", "Cylinder") in geom_creates
        assert ("sph1", "Sphere") in geom_creates
        sets = _sets(calls)
        assert ("size", ["wo", "do", "ho"]) in sets
        assert ("pos", ["-wg", "-dg/2", "ho-hg"]) in sets
        assert ("size", ["wg", "dg", "hg"]) in sets
        assert ("r", "rp") in sets and ("h", "hp") in sets
        assert ("pos", ["wo/2", "0", "rpot+bp+hp"]) in sets
        param_sets = _args(calls, "param.set")
        assert ("wo", "267[mm]") in param_sets
        assert ("Pin", "1000[W]") in param_sets
        assert ("T0", "8[degC]") in param_sets
        assert ("hconv", "10[W/(m^2*K)]") in param_sets
        assert ("Text", "8[degC]") in param_sets

    def test_materials_and_port(self, oven_spec, oven_opts):
        _model, calls = self._built(oven_spec, oven_opts)
        mat_creates = _args(calls, "material.create")
        assert ("mat_air", "Common") in mat_creates
        assert ("mat_potato", "Common") in mat_creates
        assert ("mat_glass", "Common") in mat_creates
        sets = _sets(calls)
        assert ("relpermittivity", ["65-20*j"]) in sets
        assert ("relpermittivity", ["2.55"]) in sets
        assert ("thermalconductivity", ["0.55"]) in sets
        assert ("density", ["1050"]) in sets
        assert ("heatcapacity", ["3640"]) in sets
        feature_types = [a[1] for a in _creates(calls) if len(a) == 3]
        assert feature_types.count("Impedance") == 11
        assert feature_types.count("Port") == 1
        assert ("PortType", "Rectangular") in sets
        assert ("PortModeNumber", "10") in sets
        assert ("Pin", "Pin") in sets
        assert ("definedBy", "conductivity") in sets
        assert ("sigmabnd_mat", "userdef") in sets
        assert ("sigmabnd", f"{mo.COPPER_SIGMA_S_M:g}[S/m]") in sets
        # 外部金属壁外侧=真空：epsilonr 显式 userdef（真机 run2「未定义 epsilonr」）
        assert ("epsilonr_mat", "userdef") in sets
        assert ("epsilonr", "1") in sets
        assert ("murbnd_mat", "userdef") in sets
        assert ("HeatFluxType", "ConvectiveHeatFlux") in sets

    def test_multiphysics_study_and_mesh(self, oven_spec, oven_opts):
        _model, calls = self._built(oven_spec, oven_opts)
        assert ("ht", "HeatTransfer", "geom1") in _args(calls, "physics.create")
        assert ("emh1", "ElectromagneticHeating", 3) in _args(
            calls, "multiphysics.create")
        creates = _args(calls, "study.create")
        assert creates[0] == ("std1",)
        assert ("freq", "Frequency") in creates
        assert ("stat", "Stationary") in creates
        sets = _sets(calls)
        assert ("plist", "2.45[GHz]") in sets
        assert ("hmax", 15.0) in sets and ("hmax", 3.0) in sets
        assert ("ftet1", "FreeTet") in _args(calls, "mesh.create.create")

    def test_transient_mode_switches_step_and_drops_convection(self, oven_spec):
        opts = {"thermal": "transient", "h_conv_w_m2k": 10.0, "t_ext_degc": 8.0,
                "mesh_hmax_mm": 15.0, "potato_hmax_mm": 3.0,
                "t_list": "range(0,1,5)"}
        _model, calls = self._built(oven_spec, opts)
        creates = _args(calls, "study.create")
        assert ("time", "Transient") in creates
        assert ("stat", "Stationary") not in creates
        assert ("tlist", "range(0,1,5)") in _sets(calls)
        feature_types = [a[1] for a in _creates(calls) if len(a) == 3]
        assert feature_types.count("HeatFluxBoundary") == 0


class TestEvaluateOven:
    def test_checks_and_official_agreement(self, oven_spec, oven_opts):
        field = np.linspace(10.0, 250.0, 50)
        # 读数序：P_abs, T_max, T_min, T_avg, 中心截点 T, 稳态边界流出热流
        model = _StubModel(
            [], [[[631.0]], [[250.0]], [[9.0]], [[120.0]], [[150.0]], [[631.0]]],
            field=field)
        report, returned = mo.evaluate_oven(model, oven_spec, oven_opts,
                                            wall_time_s=12.5)
        assert returned is not None and returned.size == 50
        assert report["power"]["p_absorbed_w"] == pytest.approx(631.0)
        assert report["power"]["agreement"]["ok"] is True
        assert report["temperature_c"]["t_max_c"] == 250.0
        assert report["temperature_field"]["available"] is True
        assert report["temperature_field"]["t_max_c"] == pytest.approx(250.0)
        assert report["checks"]["energy_conserved"] is True
        assert report["checks"]["official_power_agreement"] is True
        assert report["wall_time_s"] == 12.5
        # §10.24：中心探针（官方截点位）+ 稳态能量闭合自洽锚
        assert report["center_probe"]["t_center_c"] == pytest.approx(150.0)
        assert report["center_probe"]["point_exprs"] == ["wo/2", "0",
                                                         "rpot+bp+hp"]
        # ΔT_center=142 > ΔT_mean=112 → 中心峰化
        assert report["center_probe"]["center_peaked"] is True
        assert report["center_probe"]["center_over_mean_delta"] == pytest.approx(
            142.0 / 112.0)
        # stationary 专用：稳态均匀源闭式裁判与能量闭合自洽锚
        assert report["analytic_judge"]["applies"] is True
        assert "analytic_order_of_magnitude" in report["checks"]
        anchor = report["temperature_anchor"]
        assert anchor["applies"] is True
        assert anchor["anchor"] == "self_consistency_energy_stationary_closure"
        assert anchor["official"] is False
        assert anchor["p_absorbed_w"] == pytest.approx(631.0)
        assert anchor["p_boundary_out_w"] == pytest.approx(631.0)
        assert anchor["rel_deviation"] == pytest.approx(0.0)
        assert report["checks"]["temperature_anchor_ok"] is True

    def test_out_of_tolerance_reported_honestly(self, oven_spec, oven_opts):
        # 读数序：P_abs, T_max, T_min, T_avg, 中心截点 T, 边界流出热流
        model = _StubModel(
            [], [[[800.0]], [[400.0]], [[9.0]], [[200.0]], [[300.0]], [[700.0]]])
        report, field = mo.evaluate_oven(model, oven_spec, oven_opts,
                                         wall_time_s=1.0)
        assert field is None
        assert report["power"]["agreement"]["ok"] is False
        assert report["checks"]["official_power_agreement"] is False
        assert report["checks"]["energy_conserved"] is True
        # 稳态闭合不守恒（700 vs 800 → 12.5%）→ 如实 False
        assert report["temperature_anchor"]["rel_deviation"] == pytest.approx(
            100.0 / 800.0)
        assert report["checks"]["temperature_anchor_ok"] is False

    def test_transient_path_energy_anchor(self, oven_spec):
        # 官方 study 型（Frequency-Transient）：绝热能量锚 ∫Pdt = m·Cp·ΔT_mean
        opts = {"thermal": "transient", "h_conv_w_m2k": 10.0, "t_ext_degc": 8.0,
                "mesh_hmax_mm": 15.0, "potato_hmax_mm": 3.0,
                "t_list": "range(0,1,5)"}
        m = mo.potato_mass_kg(oven_spec)
        predicted = 631.0 * 5.0 / (m * mo.POTATO_CP_J_KG_K)
        t_avg = 8.0 + predicted  # 构造精确闭合
        # 读数序：P_abs, T_max, T_min, T_avg, 中心截点 T（transient 无 IntSurface）
        model = _StubModel(
            [], [[[631.0]], [[t_avg + 40.0]], [[t_avg - 5.0]], [[t_avg]],
                 [[8.0 + predicted * 2.5]]])
        report, _ = mo.evaluate_oven(model, oven_spec, opts, wall_time_s=1.0)
        anchor = report["temperature_anchor"]
        assert anchor["applies"] is True
        assert anchor["anchor"] == "self_consistency_energy_adiabatic"
        assert anchor["official"] is False
        assert anchor["times_s"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        assert anchor["predicted_delta_t_k"] == pytest.approx(predicted)
        assert anchor["measured_delta_t_k"] == pytest.approx(predicted)
        assert anchor["ok"] is True
        assert report["checks"]["temperature_anchor_ok"] is True
        # 稳态均匀源闭式对绝热瞬态不适用（场景错配）→ 如实 applies=False
        # 且不产出该 check 键；瞬态闭式裁判=能量锚+中心峰化
        assert report["analytic_judge"]["applies"] is False
        assert "reason" in report["analytic_judge"]
        assert "analytic_order_of_magnitude" not in report["checks"]
        # 中心峰化定性对照（官方 Figure 2）：ΔT_center ≥ ΔT_mean
        assert report["center_probe"]["center_over_mean_delta"] == pytest.approx(
            2.5)
        assert report["center_probe"]["center_peaked"] is True
        assert report["checks"]["center_peaked"] is True

    def test_transient_path_anchor_breach_reported(self, oven_spec):
        opts = {"thermal": "transient", "h_conv_w_m2k": 10.0, "t_ext_degc": 8.0,
                "mesh_hmax_mm": 15.0, "potato_hmax_mm": 3.0,
                "t_list": "range(0,1,5)"}
        # 平均温升只有预测的一半 → 锚超差，如实 False
        model = _StubModel(
            [], [[[631.0]], [[30.0]], [[9.0]], [[12.0]], [[50.0]]])
        report, _ = mo.evaluate_oven(model, oven_spec, opts, wall_time_s=1.0)
        assert report["checks"]["temperature_anchor_ok"] is False
        assert report["temperature_anchor"]["ok"] is False

    def test_all_dataset_candidates_exhausted_raises_honestly(self, oven_spec,
                                                              oven_opts):
        # 读数队列空 → 逐候选 getReal 全空 → 如实 RuntimeError（不静默给假数）
        model = _StubModel([], [])
        with pytest.raises(RuntimeError, match="所有数据集候选提取失败"):
            mo.evaluate_oven(model, oven_spec, oven_opts, wall_time_s=1.0)


class TestCliOffline:
    def test_dry_run_writes_plan_and_returns_zero(self, tmp_path, capsys):
        out = tmp_path / "plan"
        rc = mo.main(["--dry-run", "--out", str(out)])
        assert rc == 0
        plan = json.loads((out / "dry_run_plan.json").read_text(encoding="utf-8"))
        assert plan["mode"] == "dry-run"
        assert plan["official_model"]["model_number"] == 1424
        assert plan["options"]["thermal"] == "stationary"
        assert "DRY-RUN" in capsys.readouterr().out

    def test_dry_run_transient_option(self, tmp_path):
        out = tmp_path / "plan2"
        assert mo.main(["--dry-run", "--out", str(out),
                        "--thermal", "transient"]) == 0
        plan = json.loads((out / "dry_run_plan.json").read_text(encoding="utf-8"))
        assert plan["official_model"]["study_here"] == "transient"

    def test_build_opts_carries_cli_values(self):
        args = mo._parse_args(["--h-conv", "25", "--t-ext-degc", "20",
                               "--mesh-hmax-mm", "12", "--potato-hmax-mm", "2"])
        opts = mo.build_opts(args)
        assert opts["h_conv_w_m2k"] == 25.0
        assert opts["t_ext_degc"] == 20.0
        assert opts["mesh_hmax_mm"] == 12.0
        assert opts["potato_hmax_mm"] == 2.0

    def test_script_compiles_and_pins_comsol_version(self):
        # #119：f-string 条件格式符语法合法但运行即炸；脚本必须能被 compile
        source = (REPO / "scripts" / "comsol_microwave_oven.py").read_text(
            encoding="utf-8")
        compile(source, "comsol_microwave_oven.py", "exec")
        assert "mph.start(version=" in source  # 版本必须显式钉扎（#215）
        assert "ElectromagneticWaves" in source or "PHYSICS_TYPE" in source
