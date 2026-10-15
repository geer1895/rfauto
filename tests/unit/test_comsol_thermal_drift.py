"""d14-stage2 COMSOL 三场热漂移单测（离线确定性，零 COMSOL/license/JVM 依赖）。

覆盖三层（制度同 test_comsol_microwave_oven.py：真机路径 run_real 不执行）：
A. core 判据：thermo_mech.three_field_vs_oneway（漂移量口径/阈值/零漂守卫）；
B. adapter D14 stage-2 原子方法 Java 序列（add_structural_properties /
   add_thermal_expansion / add_point_displacement_constraint /
   build_thermal_drift_study / extract_eigenfrequency——全部官方
   cavity_filter_thermal_expansion.mph / biased_resonator_3d_basic.mph
   dmodel actions 实录口径，runs/d14_stage2/_doc_probe/）；
C. 脚本离线面（scripts/comsol_thermal_drift_3field.py：参数表/选择盒/
   build_drift_model Java 序列/evaluate_drift/compare_three_field 判定/
   offline_report/render_summary/CLI --offline/run_real 桩链）。

桩约定：调用路径按"带参调用"追加参数标记，如 propertyGroup("def") 之后的
set 记为 .propertyGroup[('def',)].set——同名方法不同参数（无参
propertyGroup() vs propertyGroup("def")）由此可区分。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca
from rfauto.core.thermo_mech import three_field_vs_oneway

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import comsol_thermal_drift_3field as td

# ─── 记录桩（同 test_comsol_microwave_oven.py 手法 + 带参路径标记）────────────


class _Recorder:
    """任意属性 → 可调用 → 返回子桩；调用以 (路径, 参数) 记入共享列表。

    带参调用产生的子桩路径追加 args 标记 [repr(args)]，使后续同名方法可
    按父参数区分（如 propertyGroup("def") vs propertyGroup()）。getReal
    按调用顺序从预置队列弹出；tags() 返回预置数据集标签。
    """

    def __init__(self, calls: list, real: list, tags: tuple = ("dset1",),
                 path: str = "", raise_on: tuple = ()) -> None:
        self._calls = calls
        self._real = real
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
            if name == "tags":
                return list(self._tags)
            marker = f"[{args!r}]" if args else ""
            return _Recorder(self._calls, self._real, self._tags,
                             f"{full}{marker}", self._raise_on)

        return _call


class _StubModel:
    def __init__(self, calls, real, tags=("dset1",), raise_on=()) -> None:
        self.java = _Recorder(calls, real, tags, raise_on=raise_on)
        self.saved: list[str] = []
        self.params: list[tuple[str, str]] = []

    def save(self, path):
        self.saved.append(str(path))

    def param(self):
        outer = self

        class _P:
            def set(self, name, expr):
                outer.params.append((str(name), str(expr)))

        return _P()


class _StubClient:
    def __init__(self, model) -> None:
        self._model = model

    def create(self, name):
        return self._model


def _args(calls, suffix):
    """路径以 suffix 结尾的调用的实参元组列表。"""
    return [a for n, a in calls if n.endswith(suffix)]


def _creates(calls):
    """所有 create(...) 调用的实参元组（特征/几何/study 步/网格）。"""
    return [a for n, a in calls if n == "create" or n.endswith(".create")]


def _creates_under(calls, marker):
    """父路径含 marker 的 create 实参（如某物理接口下的子特征）。

    marker 不含路径首段前导点（root 级调用路径无前缀，如 "study.create"）。
    """
    return [a for n, a in calls
            if (n == "create" or n.endswith(".create")) and marker in n]


def _sets_under(calls, marker):
    """父路径含 marker 的 set 实参（如 Enu 组/def 组/te1 特征的属性）。"""
    return [a for n, a in calls if n.endswith(".set") and marker in n]


def _calls_under(calls, marker, method):
    """父路径含 marker 的 method(...) 调用（如 stat/eig 步的 setSolveFor）。"""
    return [a for n, a in calls
            if n.endswith(f".{method}") and marker in n]


@pytest.fixture
def spec():
    return dict(td.DRIFT_SPEC_DEFAULTS)


@pytest.fixture
def temps():
    return [-40.0, 85.0]


# 单向链实际漂移（hairpin 口径，CTE=14/TCDk=50：ΔT=−65/+60 K）构造的
# 三场本征频率队列——run_real 桩链用它验「一致 → PASS」判定
_F0_REF = 3.9176007
_F_SIM_REAL = [_F0_REF,
               _F0_REF * (1.0 + 2541.284e-6),
               _F0_REF * (1.0 - 2334.672e-6)]

# ─── A. core 判据：three_field_vs_oneway ─────────────────────────────────────


class TestThreeFieldVsOneway:
    def test_identical_drift_zero_deviation(self):
        # 单向链 -2340ppm：f0=10GHz → f=9.9766；三场同漂移 → 偏差 0
        f_oneway = 10.0 * (1.0 - 2340e-6)
        row = three_field_vs_oneway(
            10.0, f0_oneway_ghz=f_oneway, f0_three_field_ghz=f_oneway)
        assert row["drift_oneway"] == pytest.approx(-2340e-6)
        assert row["drift_three_field"] == pytest.approx(-2340e-6)
        assert row["relative_deviation"] == pytest.approx(0.0)
        assert row["within_10pct"] is True

    def test_acceptance_boundary_is_ten_pct(self):
        f0 = 10.0
        drift = -2000e-6
        # 恰好 10% 漂移偏差：三场漂移 = oneway*0.9（≤10% 边界含等于）
        f_three = f0 * (1.0 + drift * 0.9)
        row = three_field_vs_oneway(
            f0, f0_oneway_ghz=f0 * (1.0 + drift), f0_three_field_ghz=f_three)
        assert row["relative_deviation"] == pytest.approx(0.10)
        assert row["within_10pct"] is True
        # 略超 10% 即 FAIL
        f_three_bad = f0 * (1.0 + drift * 0.85)
        row_bad = three_field_vs_oneway(
            f0, f0_oneway_ghz=f0 * (1.0 + drift), f0_three_field_ghz=f_three_bad)
        assert row_bad["relative_deviation"] == pytest.approx(0.15)
        assert row_bad["within_10pct"] is False

    def test_drift_deviation_not_frequency_deviation(self):
        # 判据分母是**漂移量**而非频率：漂移偏差 30% 时频率差仅 ~0.0076%，
        # 若误用 |Δf|/f 作分母会假绿——钉死口径
        f0 = 4.0
        drift = -2540e-6
        row = three_field_vs_oneway(
            f0, f0_oneway_ghz=f0 * (1.0 + drift),
            f0_three_field_ghz=f0 * (1.0 + drift * 0.7))
        assert row["relative_deviation"] == pytest.approx(0.30)
        assert row["within_10pct"] is False
        assert abs(row["df_abs_ghz"]) < f0 * 1e-3

    def test_zero_oneway_drift_undefined_not_green(self):
        row = three_field_vs_oneway(
            10.0, f0_oneway_ghz=10.0, f0_three_field_ghz=10.001)
        assert row["drift_oneway"] == 0.0
        assert row["relative_deviation"] is None
        assert row["within_10pct"] is None  # 退化点如实 None，不凑绿

    def test_positive_drift_and_nonpositive_inputs_rejected(self):
        row = three_field_vs_oneway(
            10.0, f0_oneway_ghz=10.0 * 1.002, f0_three_field_ghz=10.0 * 1.0021)
        assert row["drift_oneway"] > 0.0 and row["within_10pct"] is True
        with pytest.raises(ValueError, match="必须"):
            three_field_vs_oneway(-1.0, f0_oneway_ghz=1.0,
                                  f0_three_field_ghz=1.0)
        with pytest.raises(ValueError, match="必须"):
            three_field_vs_oneway(10.0, f0_oneway_ghz=0.0,
                                  f0_three_field_ghz=1.0)


# ─── B. adapter D14 stage-2 原子方法（Java 序列钉官方实录）───────────────────


class TestStructuralProperties:
    def test_enu_group_and_cte_matrix(self):
        calls: list = []
        mat = _Recorder(calls, [])
        ca.ComsolAdapter.add_structural_properties(
            mat, youngs_expr="3[GPa]", poisson_expr="0.3", cte_expr="cte")
        # 官方 MEMS 例：materialmodel 三参 (tag,type,label) 建 Enu 组——
        # label 是材料属性模型组元数据，两参建组真机实证 solid 消费不到
        # E/nu（刚度退化、位移恒零，runs/d14_stage2/）
        assert ("Enu", "Enu",
                "Young's modulus and Poisson's ratio") in \
            _creates_under(calls, "propertyGroup.create")
        enu_sets = _sets_under(calls, "('Enu', 'Enu'")
        assert ("E", "3[GPa]") in enu_sets
        assert ("nu", "0.3") in enu_sets
        # def 组热膨胀系数：9 元数组（对角 cte），官方 dmodel actions 实录
        def_sets = [a for a in _sets_under(calls, "('def',)")
                    if a and a[0] == "thermalexpansioncoefficient"]
        assert len(def_sets) == 1
        diag = def_sets[0][1]
        assert len(diag) == 9
        assert diag[0] == diag[4] == diag[8] == "cte"
        assert diag[1] == diag[3] == diag[7] == "0"
        # def 组 youngsmodulus/poissonsratio 标准名兜底
        assert ("youngsmodulus", ["3[GPa]"]) in _sets_under(calls, "('def',)")
        assert ("poissonsratio", ["0.3"]) in _sets_under(calls, "('def',)")


class TestThermalExpansion:
    def test_lemm1_feature_sequence(self):
        calls: list = []
        solid = _Recorder(calls, [])
        ca.ComsolAdapter.add_thermal_expansion(
            solid, t_ref_expr="Tref", t_expr="T1")
        assert ("geometricNonlinearity", "linear") in _sets_under(
            calls, "('lemm1'")
        assert ("te1", "ThermalExpansion", 3) in _creates_under(
            calls, "('lemm1'")
        te_sets = _sets_under(calls, "te1")
        assert ("minput_strainreferencetemperature_src", "userdef") in te_sets
        assert ("minput_strainreferencetemperature", "Tref") in te_sets
        assert ("minput_temperature_src", "userdef") in te_sets
        assert ("minput_temperature", "T1") in te_sets

    def test_missing_lemm1_raises_honest(self):
        calls: list = []
        solid = _Recorder(calls, [], raise_on=("feature",))
        with pytest.raises(RuntimeError, match="lemm1"):
            ca.ComsolAdapter.add_thermal_expansion(solid)


class TestPointDisplacementConstraint:
    def test_displacement0_point_sequence(self):
        calls: list = []
        solid = _Recorder(calls, [])
        ca.ComsolAdapter.add_point_displacement_constraint(
            solid, selection="sel_fix")
        # 单测上下文 solid 为桩根节点：create 即该特征（root 无父路径）
        assert ("disp_fix", "Displacement0", 0) in _creates(calls)
        named = _args(calls, ".selection.named")
        assert named == [("sel_fix",)]
        directions = [a for a in _calls_under(calls, "disp_fix", "setIndex")
                      if a[0] == "Direction"]
        assert directions == [("Direction", "prescribed", 0),
                              ("Direction", "prescribed", 1),
                              ("Direction", "prescribed", 2)]

    def test_partial_components_allowed(self):
        calls: list = []
        solid = _Recorder(calls, [])
        ca.ComsolAdapter.add_point_displacement_constraint(
            solid, selection="sel_fix", tag="d2", components=(1,))
        assert ("d2", "Displacement0", 0) in _creates(calls)
        directions = [a for a in _calls_under(calls, "d2", "setIndex")
                      if a[0] == "Direction"]
        assert directions == [("Direction", "prescribed", 1)]


class TestMeshDisplacement:
    def test_prescribed_mesh_displacement_bound_to_solid(self):
        calls: list = []
        comp = _Recorder(calls, [])
        ca.ComsolAdapter.add_mesh_displacement(comp)
        # 官方 tunable_cavity 例实录：PrescribedMeshDisplacement 绑定
        # solid 位移分量 u/v/w（同域场景必需且充分）
        assert ("disp1", "PrescribedMeshDisplacement") in _creates_under(
            calls, "common")
        prescribed = [a for n, a in calls
                      if n.endswith(".set")
                      and a and a[0] == "prescribedMeshDisplacement"]
        assert ("prescribedMeshDisplacement", ["u", "v", "w"]) in prescribed
        assert _args(calls, ".selection.named") == []
        assert len(_args(calls, ".selection.all")) == 1

    def test_named_selection_and_components(self):
        calls: list = []
        comp = _Recorder(calls, [])
        ca.ComsolAdapter.add_mesh_displacement(comp, selection="sel_pot",
                                               tag="disp2",
                                               components=("u",))
        assert ("disp2", "PrescribedMeshDisplacement") in _creates_under(
            calls, "common")
        assert _args(calls, ".selection.named") == [("sel_pot",)]
        prescribed = [a for n, a in calls
                      if n.endswith(".set")
                      and a and a[0] == "prescribedMeshDisplacement"]
        assert ("prescribedMeshDisplacement", ["u"]) in prescribed


class TestDeformingDomain:
    def test_free_smoothing_feature_cross_domain(self):
        calls: list = []
        comp = _Recorder(calls, [])
        ca.ComsolAdapter.add_deforming_domain(comp)
        # 跨域（结构域+空气域）场景的自由平滑域；同域不建（真机实证冲突）
        assert ("free1", "DeformingDomain") in _creates_under(
            calls, "common")
        assert _args(calls, ".selection.named") == []
        assert len(_args(calls, ".selection.all")) == 1


class TestThermalDriftStudy:
    def test_stat_then_eig_sequence_matches_official(self):
        calls: list = []
        j = _Recorder(calls, [])
        ca.ComsolAdapter.build_thermal_drift_study(j, neigs=1)
        # 步类型串/顺序（官方 cavity_filter_thermal_expansion：stat → eig）
        assert ("std1",) in _creates_under(calls, "study.create")
        assert ("stat", "Stationary") in _creates(calls)
        assert ("eig", "Eigenfrequency") in _creates(calls)
        # stat 步 solve-for 矩阵（官方：solid=True / emw=False）
        stat_flags = {a[0]: a[1]
                      for a in _calls_under(calls, "('stat', 'Stationary')",
                                            "setSolveFor")}
        assert stat_flags == {"/physics/solid": True, "/physics/emw": False}
        # eig 步 solve-for 矩阵（官方：solid=False / 空间框架=False——
        # 变形构型上重解 EM 的官方机制）
        eig_flags = {a[0]: a[1]
                     for a in _calls_under(calls, "('eig', 'Eigenfrequency')",
                                           "setSolveFor")}
        assert eig_flags == {"/physics/solid": False,
                             "/frame/spatial1": False}
        # 本征模个数
        eig_sets = _sets_under(calls, "('eig', 'Eigenfrequency')")
        assert ("neigsactive", True) in eig_sets
        assert ("neigs", "1") in eig_sets

    def test_custom_neigs_and_tag(self):
        calls: list = []
        j = _Recorder(calls, [])
        ca.ComsolAdapter.build_thermal_drift_study(j, neigs=3,
                                                   study_tag="stddrift")
        assert ("stddrift",) in _creates_under(calls, "study.create")
        eig_sets = _sets_under(calls, "('eig', 'Eigenfrequency')")
        assert ("neigs", "3") in eig_sets


class TestExtractEigenfrequency:
    def test_evalglobal_single_expression_row(self):
        calls: list = []
        model = _StubModel(calls, [[[3.9176, 6.5423]]])
        out = ca.ComsolAdapter.extract_eigenfrequency(model)
        assert isinstance(out, np.ndarray)
        assert out == pytest.approx([3.9176, 6.5423])
        assert ("eig_freq", "EvalGlobal") in _creates_under(
            calls, "numerical.create")
        sets = _sets_under(calls, "('eig_freq'")
        assert ("expr", ["emw.freq"]) in sets
        assert ("unit", ["GHz"]) in sets

    def test_empty_result_raises_honest(self):
        calls: list = []
        model = _StubModel(calls, [[]])
        with pytest.raises(RuntimeError, match="EvalGlobal"):
            ca.ComsolAdapter.extract_eigenfrequency(model)

    def test_dataset_and_expr_passthrough(self):
        calls: list = []
        model = _StubModel(calls, [[[2.5]]])
        out = ca.ComsolAdapter.extract_eigenfrequency(
            model, expr="emw.freq", dataset="dset2", tag="gf")
        assert out == pytest.approx([2.5])
        assert ("data", "dset2") in _sets_under(calls, "('gf'")


class TestConfigureEigenShift:
    def test_sets_shift_on_every_sol_feature(self):
        calls: list = []
        model = _StubModel(calls, [])
        touched = ca.ComsolAdapter.configure_eigen_shift(model, "3.9176007[GHz]")
        # 桩只有一个 sol×feature（tags=("dset1",)）：每个特征都收到 set shift
        sets = [a for n, a in calls
                if n.endswith(".set") and a and a[0] == "shift"]
        assert sets == [("shift", "3.9176007[GHz]")]
        assert touched and all("/" in t for t in touched)

    def test_no_accepting_feature_raises_honest(self):
        calls: list = []
        model = _StubModel(calls, [], raise_on=("set",))
        with pytest.raises(RuntimeError, match="shift"):
            ca.ComsolAdapter.configure_eigen_shift(model, "3.9[GHz]")


class TestPrepareEigenSolver:
    def test_sequence_run_then_shift_from_closed_form(self, spec):
        calls: list = []
        model = _StubModel(calls, [])
        td.prepare_eigen_solver(model, spec)
        # 序列生成走一次 run()（首解为零模、弃用；createAutoSequences
        # 实测稳态步不收敛，真机实录见脚本 docstring）
        runs = [a for n, a in calls
                if n.endswith(".run") and "'std1'" in n]
        assert len(runs) == 1
        # shift = 模型自身闭式基模（数值搜索起点）
        shift_sets = [a for n, a in calls
                      if n.endswith(".set") and a and a[0] == "shift"]
        assert shift_sets == [("shift", "3.9176007[GHz]")]


# ─── C. 脚本离线面 ────────────────────────────────────────────────────────────


class TestParams:
    def test_defaults_and_expression_parameters(self, spec):
        params = td.drift_comsol_parameters(spec)
        assert params["A"] == "20[mm]" and params["B"] == "12[mm]"
        assert params["EPSR"] == "3.66"
        # TCDk 表达式与单向链 eps_scale 同式（物理对齐的关键）
        assert params["alphatcdk"] == "5e-05[1/K]"
        assert params["EPS_T"] == "EPSR*(1+alphatcdk*(T1-Tref))"
        assert params["Tref"] == "25[degC]" and params["T1"] == "25[degC]"
        assert params["cte"] == "1.4e-05[1/K]"

    def test_normalize_rejects_bad_geometry(self):
        with pytest.raises(ValueError, match="必须 >0"):
            td.normalize_drift_params({"a_mm": -1.0})
        with pytest.raises(ValueError, match="开区间"):
            td.normalize_drift_params({"nu": 0.6})

    def test_closed_form_matches_hairpin_semantics(self, spec):
        # f0 = c/(2a√εr)：与 core hairpin 半波式同构（数值独立复核）
        assert td.resonator_closed_form_ghz(spec) == pytest.approx(
            299.792458 / (2.0 * 20.0 * np.sqrt(3.66)), rel=1e-12)

    def test_selection_boxes_dims_and_fix_corner(self, spec):
        boxes = td.drift_selection_boxes(spec)
        for tag in ("sel_fix1", "sel_fix2", "sel_fix3"):
            assert boxes[tag][0] == 0  # 点级（Displacement0 官方 i(0)）
        for tag in ("sel_pec_z0", "sel_pec_zh", "sel_pmc_x0", "sel_pmc_xl",
                    "sel_pmc_y0", "sel_pmc_yw"):
            assert boxes[tag][0] == 2
        hi1 = boxes["sel_fix1"][2]
        assert hi1[0] > 0 and hi1[1] > 0 and hi1[2] > 0  # 角点 (0,0,0) 落盒内
        # 三点各锚一角：(0,0,0)/(a,0,0)/(0,b,0)
        lo2 = boxes["sel_fix2"][1]
        assert lo2[0] == pytest.approx(spec["a_mm"] - 1e-3)
        lo3 = boxes["sel_fix3"][1]
        assert lo3[1] == pytest.approx(spec["b_mm"] - 1e-3)


class TestBuildDriftModel:
    def test_java_sequence_pins_official_apis(self, spec):
        calls: list = []
        model = _StubModel(calls, [])
        client = _StubClient(model)
        opts = {"mesh_hmax_mm": 1.0, "neigs": 1}
        td.build_drift_model(client, spec, opts)
        # 全局参数（含 EPS_T 温漂表达式）：走 java.param().set（记录桩 path）
        param_sets = dict(a for n, a in calls if n == "param.set")
        assert param_sets["A"] == "20[mm]"
        assert param_sets["EPS_T"] == "EPSR*(1+alphatcdk*(T1-Tref))"
        # 几何：单 Block
        assert ("blk1", "Block") in _creates_under(calls, "geom.create")
        # 选择盒 9 个（6 边界面 + 3 约束点，官方 cavity 例三点 3-2-1 同构）
        box_creates = [a for a in _creates_under(calls, "selection.create")
                       if a[1] == "Box"]
        assert len(box_creates) == 9
        # emw 边界：2 PEC + 4 PMC（封闭腔本征问题，无端口）
        emw_kinds = [a[1] for a in _creates_under(calls, "'emw'")]
        assert emw_kinds.count("PerfectElectricConductor") == 2
        assert emw_kinds.count("PerfectMagneticConductor") == 4
        # solid + 热膨胀 + 三点约束（复用 adapter 原子方法）
        solid_creates = _creates_under(calls, "'solid'")
        assert ("te1", "ThermalExpansion", 3) in solid_creates
        assert ("disp1", "Displacement0", 0) in solid_creates
        assert ("disp2", "Displacement0", 0) in solid_creates
        assert ("disp3", "Displacement0", 0) in solid_creates
        # 网格位移=solid 位移（官方 tunable_cavity 例 PrescribedMeshDisplacement
        # 同构）：同域场景必需且充分；同域不建 free1（真机实证冲突）
        assert ("disp1", "PrescribedMeshDisplacement") in _creates_under(
            calls, "common")
        assert ("free1", "DeformingDomain") not in _creates_under(
            calls, "common")
        # study 两步（官方 cavity 例）+ 网格
        assert ("stat", "Stationary") in _creates(calls)
        assert ("eig", "Eigenfrequency") in _creates(calls)
        assert ("ftet1", "FreeTet") in _creates_under(calls, "('mesh1'")
        # 材料 def 组 relpermittivity=EPS_T（ε(T) 表达式进材料）
        mat_sets = [a for a in _sets_under(calls, "('def',)")
                    if a and a[0] == "relpermittivity"]
        assert ("relpermittivity", ["EPS_T"]) in mat_sets


class TestEvaluateDrift:
    def test_per_temperature_param_and_study_run(self, spec, temps):
        calls: list = []
        model = _StubModel(calls, [[[v]] for v in _F_SIM_REAL])
        opts = {"neigs": 1, "temps_c": temps}
        f_sim = td.evaluate_drift(model, spec, opts)
        # 首点 Tref=25 归一锚，其后两个包络点
        assert sorted(f_sim) == [-40.0, 25.0, 85.0]
        assert f_sim[25.0] == pytest.approx(_F0_REF)
        # 每温度点 java.param().set T1 → run std1（T1 走 java 面记录桩）
        t1_sets = [a for n, a in calls
                   if n == "param.set" and a[0] == "T1"]
        assert t1_sets == [("T1", "25[degC]"), ("T1", "-40[degC]"),
                           ("T1", "85[degC]")]
        runs = [a for n, a in calls
                if n.endswith(".run") and "'std1'" in n]
        assert len(runs) == 4  # prepare 1 次（生成序列+设 shift）+ 3 温度点


class TestCompareThreeField:
    def test_agreement_when_three_field_matches_oneway(
            self, spec, temps):
        # 构造：三场漂移 = 单向链一阶漂移 −(CTE+½TCDk)·ΔT（理论一致场景）
        drift_lin = {t: -39e-6 * (t - 25.0) for t in (25.0, -40.0, 85.0)}
        f_sim = {t: 3.9176 * (1.0 + drift_lin[t])
                 for t in (25.0, -40.0, 85.0)}
        report = td.compare_three_field(spec, f_sim, temps)
        assert report["f0_sim_ref_ghz"] == pytest.approx(3.9176)
        assert report["verdict"]["stage2_within_10pct_all"] is True
        # 判据键齐全（两个包络点；Tref 点漂移恒零不进判定面）
        assert set(report["comparison"]) == {"-40", "85"}
        assert report["verdict"]["stage1_within_20pct_all"] is True

    def test_divergence_detected_when_three_field_off(self, spec, temps):
        # 构造：三场漂移只有单向链的一半 → 漂移偏差 50% → FAIL
        drift_oneway = {25.0: 0.0, -40.0: +2541.28e-6, 85.0: -2334.67e-6}
        f_sim = {t: 3.9176 * (1.0 + drift_oneway[t] * 0.5)
                 for t in (25.0, -40.0, 85.0)}
        report = td.compare_three_field(spec, f_sim, temps)
        assert report["verdict"]["stage2_within_10pct_all"] is False
        assert report["comparison"]["85"]["relative_deviation"] == pytest.approx(
            0.5, rel=1e-3)

    def test_sim_nominal_used_as_common_reference(self, spec, temps):
        # 归一锚 = 三场在 Tref 的仿真值（消网格系统偏置）：f_sim 整体偏置
        # 1%，漂移量与判定不变
        drift = {25.0: 0.0, -40.0: +2541.28e-6, 85.0: -2334.67e-6}
        bias = 1.01
        f_sim = {t: 3.9176 * bias * (1.0 + drift[t])
                 for t in (25.0, -40.0, 85.0)}
        report = td.compare_three_field(spec, f_sim, temps)
        assert report["f0_sim_ref_ghz"] == pytest.approx(3.9176 * bias)
        assert report["verdict"]["stage2_within_10pct_all"] is True


class TestOfflineReportAndCli:
    def test_offline_report_matches_stage1_numbers(self, spec, temps):
        report = td.offline_report(spec, temps)
        assert report["mode"] == "offline"
        assert report["stage1_within_20pct_all"] is True
        # stage-1 hairpin 口径同值（CTE=14/TCDk=50/ΔT=−65/+60）
        assert report["by_temp"]["-40"]["oneway_drift_ppm"] == pytest.approx(
            2541.284, rel=1e-4)
        assert report["by_temp"]["85"]["oneway_drift_ppm"] == pytest.approx(
            -2334.672, rel=1e-4)

    def test_offline_cli_exit_zero(self, capsys):
        # --temps 用 = 形式传负数（argparse 把 "-40,85" 当选项吞掉）
        assert td.main(["--offline", "--temps=-40,85"]) == 0
        import json as _json
        payload = _json.loads(capsys.readouterr().out)
        assert payload["mode"] == "offline"
        assert payload["stage1_within_20pct_all"] is True

    def test_render_summary_contains_verdict_and_numbers(self):
        report = {
            "f0_sim_ref_ghz": 3.9176,
            "f0_closed_form_ghz": 3.9176,
            "verdict": {"stage2_within_10pct_all": True,
                        "stage1_within_20pct_all": True,
                        "assumption": "等温口径"},
            "comparison": {
                "85": {"f0_three_field_ghz": 3.8915,
                       "drift_three_field_ppm": -6673.1,
                       "drift_oneway_ppm": -6700.0,
                       "relative_deviation": 0.004,
                       "within_10pct": True},
            },
        }
        text = td.render_summary(report)
        assert "PASS" in text and "3.9176" in text and "等温口径" in text


class TestRunRealStub:
    def test_run_real_glue_with_stub_client(self, spec, temps, tmp_path,
                                            monkeypatch):
        calls: list = []
        model = _StubModel(calls, [[[v]] for v in _F_SIM_REAL])
        monkeypatch.setattr(td.ca, "get_shared_client",
                            lambda: _StubClient(model))

        class _NS:
            out_dir = str(tmp_path)
            save_mph = False

        opts = {"mesh_hmax_mm": 1.0, "neigs": 1, "save_mph": False,
                "temps_c": temps}
        report = td.run_real(_NS(), spec, opts)
        assert report["mode"] == "real"
        assert report["verdict"]["stage2_within_10pct_all"] is True
        assert (tmp_path / "thermal_drift_3field_result.json").exists()
        assert (tmp_path / "thermal_drift_3field_summary.md").exists()
        # save_mph=False 不落 mph
        assert model.saved == []
