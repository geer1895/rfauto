"""COMSOL 收尾特性单测：mock/闭式级。

零 COMSOL/license/JVM 依赖；真机断言不进单测（真机证据归档不入库）。
A1: r3_services 显式 import comsol_adapter（注册副作用不依赖调用方）；
A2: configs/solvers.yaml comsol 条目可读；
A3: scripts/comsol_probe.py 正式探针 #217 口径（6.3 钉扎 + ElectromagneticWaves）；
B: mline 锚模板（参数规范化/skrf HJ 闭式锚值/build Java 序列/全 S 装配）；
C: 端口扫描全 S 矩阵 + Touchstone（COMSOL 原生导出优先/skrf 兜底）+
   skrf 读回互易/无源校验。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca
from rfauto.adapters.comsol_adapter import (
    ComsolAdapter,
    extract_eps_eff,
    mline_closed_form,
    normalize_mline_params,
    tl_section_sparams,
    to_comsol_parameters_mline,
)
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    load_solvers_config,
)

REPO = Path(__file__).resolve().parents[2]

# ─── Java 链式调用录制桩（test_comsol_adapter 同模式 + 6 行 EvalGlobal 数据）──


class _JavaRecorder:
    """任意属性 → 可调用 → 返回子桩；getReal/getImag 回放预置数据。"""

    def __init__(self, calls: list, data: dict, path: str = ""):
        self._calls = calls
        self._data = data
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args):
            full = f"{self._path}.{name}" if self._path else name
            self._calls.append((full, args))
            if name == "getReal":
                return self._data["real"]
            if name == "getImag":
                return self._data["imag"]
            if name == "tags":  # dataset().tags()：提取循环遍历的解数据集
                return list(self._data.get("tags", ["dset1"]))
            return _JavaRecorder(self._calls, self._data, full)

        return _call


class _FakeModel:
    def __init__(self, calls, data):
        self.java = _JavaRecorder(calls, data)
        self.saved: list[str] = []

    def save(self, path):
        self.saved.append(str(path))


class _FakeClient:
    def __init__(self, data):
        self.calls: list = []
        self.data = data
        self.removed: list = []

    def create(self, name):
        return _FakeModel(self.calls, self.data)

    def remove(self, model):
        self.removed.append(model)


def _full_eval_data(freqs_ghz, eps_eff=2.85264, z_line=50.0, length_mm=40.0,
                    shuffle=True):
    """6 行 EvalGlobal 数据（freq/PortName/S11/S21/S12/S22），列=解。

    端口 2 的 S11/S21 行给不同值——装配必须按 (freq, PortName) 识别列而非
    按行序盲取。shuffle=True 时列交错，证明装配不假设解序。
    """
    f = np.asarray(freqs_ghz, float)
    s = tl_section_sparams(f, eps_eff, z_line, length_mm)  # (n,2,2) 无耗线
    n = len(f)
    cols = list(range(n * 2))
    if shuffle:
        cols = [c for pair in zip(range(n), range(n, 2 * n), strict=True)
                for c in pair]
    freq_row, port_row, s11r, s21r, s12r, s22r = [], [], [], [], [], []
    s11i, s21i, s12i, s22i = [], [], [], []
    for col in cols:
        k, exc = (col, 1) if col < n else (col - n, 2)
        freq_row.append(f[k] * 1e9)
        port_row.append(float(exc))
        if exc == 1:
            s11r.append(s[k, 0, 0].real)
            s11i.append(s[k, 0, 0].imag)
            s21r.append(s[k, 1, 0].real)
            s21i.append(s[k, 1, 0].imag)
            s12r.append(9.0)  # 非本激励列的值不应用
            s12i.append(9.0)
            s22r.append(9.0)
            s22i.append(9.0)
        else:
            s11r.append(8.0)
            s11i.append(8.0)
            s21r.append(8.0)
            s21i.append(8.0)
            s12r.append(s[k, 0, 1].real)
            s12i.append(s[k, 0, 1].imag)
            s22r.append(s[k, 1, 1].real)
            s22i.append(s[k, 1, 1].imag)
    return {"real": [freq_row, port_row, s11r, s21r, s12r, s22r],
            "imag": [[0.0] * (n * 2)] * 2 + [s11i, s21i, s12i, s22i]}


def _calls_named(calls, suffix):
    return [(n, a) for n, a in calls if n.endswith(suffix)]


def _make_adapter(tmp_path, monkeypatch, client=None, **extra):
    monkeypatch.setattr(ca, "mph_installed", lambda: True)
    cfg = EMSolverConfig(
        solver_type=EMSolverType.COMSOL,
        working_dir=str(tmp_path / "work"),
        freq_range_ghz=(2.3, 2.7),
        mesh_resolution_mm=0.5,
        extra_params={"comsol_root": str(tmp_path), **extra},
    )
    return ComsolAdapter(cfg, client_factory=(lambda: client) if client else None)


# ─── A1: r3_services 显式 import comsol_adapter ──────────────────────────────


class TestA1ExplicitImport:
    def test_r3_services_source_pins_comsol_adapter_import(self):
        from rfauto.service import r3_services

        src = inspect.getsource(r3_services)
        # 注册副作用 import 不得只靠调用方先 import 包
        assert "comsol_adapter" in src

    def test_list_registered_solvers_reports_comsol(self):
        from rfauto.service.r3_services import list_registered_solvers

        names = [s["type"] for s in list_registered_solvers()["solvers"]]
        assert "comsol" in names


# ─── A2: configs/solvers.yaml comsol 条目 ────────────────────────────────────


class TestA2SolversYaml:
    def test_comsol_entry_loadable(self):
        cfg = load_solvers_config().get("comsol")
        assert cfg is not None
        assert cfg.solver_type == EMSolverType.COMSOL
        assert cfg.working_dir == "runs/comsol"
        # #215：6.4 过期，配置必须钉 6.3
        assert cfg.extra_params["comsol_version"] == "6.3"
        assert cfg.extra_params["cores"] == 2


# ─── A3: scripts/comsol_probe.py 正式探针（#217 口径）────────────────────────


class TestA3ProbeScript:
    def test_probe_script_exists_with_217_semantics(self):
        src = (REPO / "scripts" / "comsol_probe.py").read_text(encoding="utf-8")
        assert 'default="6.3"' in src  # 版本钉扎（#215）
        assert "ElectromagneticWaves" in src  # #217①：RF 接口正确类型串
        # 早期探针误用的 ewfd 口径不得用于建模（docstring 记录史实不算回归）
        assert '"ElectromagneticWavesFrequencyDomain"' not in src
        assert "LumpedPort" in src  # license 判据 = LumpedPort 可创建
        assert "--dump-api" in src  # API 核对模式（属性名取自 COMSOL 自报）


# ─── B: mline 锚模板纯函数 ────────────────────────────────────────────────────


class TestMlinePure:
    def test_defaults_are_wp21_anchor(self):
        spec = normalize_mline_params(None)
        # WP2.1 权威口径表 §1：50Ω@rogers4350b = 1.113mm（skrf HJ 精算）
        assert spec == {"w_mm": 1.113, "line_len_mm": 40.0, "eps_r": 3.66,
                        "sub_h_mm": 0.508, "z_ref_ohm": 50.0}
        with pytest.raises(ValueError):
            normalize_mline_params({"w_mm": 0})
        with pytest.raises(ValueError):
            normalize_mline_params({"line_len_mm": float("nan")})

    def test_closed_form_matches_benchmark_anchor(self):
        # 同一条 skrf HJ 链路（core/synthesis.forward_z0）必须复现 WP1.2 引擎
        # 基准的闭式锚值（runs/benchmark/mline_mesh_convergence.json：
        # eps_hj_closed_form=2.85264）
        z0, eps = mline_closed_form(1.113, 2.5, 3.66, 0.508)
        assert z0 == pytest.approx(50.011, abs=0.05)
        assert eps == pytest.approx(2.85264, abs=2e-3)

    def test_to_comsol_parameters_units(self):
        params = to_comsol_parameters_mline(normalize_mline_params(None))
        assert params == {"W": "1.113[mm]", "L": "40[mm]", "HS": "0.508[mm]",
                          "epsr": "3.66", "Zref": "50[ohm]"}


class TestMlineBuildGeometry:
    def test_build_writes_spec_with_hj_closed_form(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": [2.3, 2.7]},
                                       "port_sweep": True})
        spec = json.loads((tmp_path / "work" / "comsol_spec.json")
                          .read_text(encoding="utf-8"))
        assert spec["template"] == "mline"
        assert spec["port_sweep"] is True
        assert spec["comsol_version_pin"] == "6.3"
        assert spec["comsol_parameters"]["W"] == "1.113[mm]"
        assert spec["closed_form_hj"]["eps_eff"] == pytest.approx(2.85264, abs=2e-3)
        assert "tanδ" in spec["note"]  # 无耗建模偏差如实声明

    def test_build_rejects_unknown_template(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch)
        adapter.connect()
        assert not adapter.build_geometry({"template": "cpw"})


# ─── B: mline mock 求解序列（Java 调用对照官方口径）──────────────────────────


class TestMlineSolveMock:
    FREQS: ClassVar[list[float]] = [2.3, 2.5, 2.7]

    def _solved(self, tmp_path, monkeypatch, **extra):
        data = _full_eval_data(self.FREQS)
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client,
                                **extra)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": self.FREQS},
                                       "port_sweep": True})
        result = adapter.solve()
        return adapter, client, result

    def test_solve_full_matrix_and_java_sequence(self, tmp_path, monkeypatch):
        _adapter, client, result = self._solved(tmp_path, monkeypatch)
        assert result.success, result.message
        # 全 S 矩阵（端口扫描实测口径，无互易/对称补齐）
        assert result.s_params.shape == (3, 2, 2)
        assert "PortName parametric port sweep" in result.field_data["sparam_fill"]
        assert "filled" not in result.field_data["sparam_fill"]
        # 无耗线闭式：|S21|=1、互易
        assert np.allclose(np.abs(result.s_params[:, 1, 0]), 1.0, atol=1e-9)
        assert np.allclose(result.s_params[:, 0, 1], result.s_params[:, 1, 0])
        # skrf 兜底 Touchstone 落盘（COMSOL 原生导出在 mock 下无文件）
        ts = result.field_data["touchstone"]
        assert ts["writer"] == "skrf_fallback"
        assert (tmp_path / "work" / "sparams.s2p").exists()

        calls = client.calls
        # 走线=WorkPlane 印痕（官方 vivaldi_antenna 手法），非厚 Block
        all_args = [a for _, a in calls]
        assert ("wp_trace", "WorkPlane") in all_args
        assert ("r_trace", "Rectangle") in all_args
        assert not any(a and a[0] == "trace" for a in all_args
                       if len(a) == 2 and isinstance(a[1], str))  # 无厚块走线
        sets = [a for _, a in _calls_named(calls, ".set")]
        assert ("quickplane", "xy") in sets and ("quickz", "HS") in sets
        assert ("base", "corner") in sets  # 合法值小写（真机报错实录）
        # RF 接口 + 散射边界（官方例类型串 "Scattering"，非 ScatteringBoundaryCondition）
        assert _calls_named(calls, "physics.create")[0][1] == (
            "emw", "ElectromagneticWaves", "geom1")
        feature_types = [a[1] for n, a in calls
                         if n.endswith("physics.create.create")]
        assert feature_types.count("Scattering") == 5
        assert "ScatteringBoundaryCondition" not in feature_types
        assert feature_types.count("PerfectElectricConductor") == 2
        assert feature_types.count("LumpedPort") == 2
        # 集总端口：数字名（扫描/Touchstone 必需）+ Uniform/Cable + 两口激励候选
        assert ("PortName", "1") in sets and ("PortName", "2") in sets
        assert sets.count(("PortExcitation", "on")) == 2
        assert sets.count(("TerminalType", "Cable")) == 2
        # 端口扫描设置（官方 h_bend_waveguide_3d 实录属性名）
        assert ("PortSweepSettings",) in all_args  # phys.prop(...) 定位
        prop_sets = [a for n, a in calls if n.endswith("prop.set")]
        assert ("useSweep", "1") in prop_sets
        assert ("PortParamName", "PortName") in prop_sets
        assert ("ExportTouchstone", "1") in prop_sets
        assert ("format", "RI") in prop_sets
        # study：Parametric 外层扫 PortName + Frequency 内层（#217②③）
        study_creates = [a for _, a in _calls_named(calls, "study.create")]
        assert study_creates[0] == ("std1",)
        assert ("param", "Parametric") in study_creates
        assert ("freq", "Frequency") in study_creates
        assert ("pname", ["PortName"]) in sets  # Parametric 步扫 PortName
        assert ("plistarr", [["1", "2"]]) in sets
        assert _calls_named(calls, "study.run")
        # 全 S 提取表达式（freq/PortName/S11..S22）
        assert ("expr", ["freq", "PortName", "comp1.emw.S11", "comp1.emw.S21",
                         "comp1.emw.S12", "comp1.emw.S22"]) in sets

    def test_solve_single_excitation_path_keeps_fill_note(
            self, tmp_path, monkeypatch):
        # port_sweep=False：走既有单激励路径（互易/对称补齐显式标注）
        freqs = self.FREQS
        f = np.asarray(freqs, float)
        s = tl_section_sparams(f, 2.85, 50.0, 40.0)
        data = {"real": [list(f * 1e9), list(s[:, 0, 0].real),
                         list(s[:, 1, 0].real)],
                "imag": [[0.0] * 3, list(s[:, 0, 0].imag),
                         list(s[:, 1, 0].imag)]}
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": freqs}})
        result = adapter.solve()
        assert result.success
        assert "Port Sweep" in result.field_data["sparam_fill"]
        assert result.field_data["touchstone"] == {}


# ─── C: TEM 边界模端口完整链 + tanδ 材料口径（6i③；mock 序列钉官方实录）──────


class TestTemPortChain:
    """数值 TEM 边界模端口完整链（官方例 cpw_numeric_tem_port/tem_via 同构）。

    官方实录（runs/comsol_tail/_doc_probe/ 本机解包）：Port 特征
    PortType="TEM"+numericTEM="1"（cpw 链）、StudyStep="std1/tbma" 解引用
    （tem_via dmodel）；study 首步=边界模分析（bma），端口模变量
    Cmode/Lmode 只在该步产生——run9/10 报 Cmode_1 未定义即缺此链。
    """

    FREQS: ClassVar[list[float]] = [2.3, 2.5, 2.7]

    def _solved(self, tmp_path, monkeypatch, **extra):
        # 单激励数据（freq/S11/S21 三行）——tem 链默认单激励口径（对拍只需 S21）
        f = np.asarray(self.FREQS, float)
        s = tl_section_sparams(f, 2.85264, 50.011, 40.0)
        data = {"real": [list(f * 1e9), list(s[:, 0, 0].real),
                         list(s[:, 1, 0].real)],
                "imag": [[0.0] * 3, list(s[:, 0, 0].imag),
                         list(s[:, 1, 0].imag)]}
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client,
                                mline_port_chain="tem", **extra)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": self.FREQS}})
        result = adapter.solve()
        return adapter, client, result

    def test_solve_java_sequence_matches_official_chain(
            self, tmp_path, monkeypatch):
        adapter, client, result = self._solved(tmp_path, monkeypatch)
        assert result.success, result.message
        calls = client.calls
        sets = [a for _, a in _calls_named(calls, ".set")]
        feature_types = [a[1] for n, a in calls
                         if n.endswith("physics.create.create")]
        # Port 特征（类型串 "Port"）替代 LumpedPort + 电压积分线子特征 ×2
        assert feature_types.count("Port") == 2
        assert feature_types.count("LumpedPort") == 0
        ilv_types = [a[1] for n, a in calls
                     if n.endswith("physics.create.create.create")]
        assert ilv_types.count("IntegrationLineforVoltage") == 2
        # 官方属性：Numeric 型 + 数值 TEM + StudyStep 解引用各自 bma 步
        assert sets.count(("PortType", "Numeric")) == 2
        assert sets.count(("numericTEM", "1")) == 2
        assert sets.count(("StudyStep", "std1/bma1")) == 1
        assert sets.count(("StudyStep", "std1/bma2")) == 1
        assert sets.count(("TerminalType", "Cable")) == 0  # Cable 是集总端口属性
        # 积分线边选择（端面 x=0 竖直线：地→走线）
        named_sels = [a for n, a in calls if n.endswith("selection.named")]
        assert ("sel_ilv1",) in named_sels and ("sel_ilv2",) in named_sels
        # 解引用时序：StudyStep 回填必须晚于 bma 步创建（真机实证：步不存在
        # 时 set 报「参数值无效」——run9/10 Cmode 未定义的解引用侧根因）
        idx_bma = next(i for i, (n, a) in enumerate(calls)
                       if n.endswith("study.create") and a[:1] == ("bma1",))
        idx_ref = next(i for i, (n, a) in enumerate(calls)
                       if n.endswith("feature.set") and a[:1] == ("StudyStep",))
        assert idx_bma < idx_ref
        # 单激励：port1 激励、port2 不激励（port_sweep=False）
        assert sets.count(("PortExcitation", "on")) == 1
        assert sets.count(("PortExcitation", "off")) == 1
        # 几何=官方 cpw 例同构：域端即端口面（Port 只能放外部边界，真机实录）
        # ——无余量段块、散射边界仅 3 面（y 端=端口面）
        block_creates = [a for n, a in calls
                         if n.endswith("geom.create.create")
                         and len(a) == 2 and a[1] == "Block"]
        assert ("subT0", "Block") not in block_creates
        assert ("airT1", "Block") not in block_creates
        assert ("subM", "Block") in block_creates  # 反证过滤器有效
        assert feature_types.count("Scattering") == 3
        # 电压积分线边：WorkPlane(yz) LineSegment（coord1/coord2 官方实录）
        wp_creates = [a for n, a in calls
                      if n.endswith("geom.create.create")]
        assert ("wp_trace", "WorkPlane") in wp_creates
        assert ("wp_voltage", "WorkPlane") in wp_creates
        seg_creates = [a for n, a in calls
                       if n.endswith("geom.create.create.geom.create")]
        assert ("lv_port1", "LineSegment") in seg_creates
        assert ("lv_port2", "LineSegment") in seg_creates
        assert sets.count(("specify1", "coord")) == 2  # butler 例实录（默认
        assert sets.count(("specify2", "coord")) == 2  # 顶点选择模式会报错）
        assert sets.count(("coord1", [-20.0, 0.0])) == 1  # y0=-L/2, z=0（地面）
        assert sets.count(("coord2", [-20.0, 0.508])) == 1  # 终点=走线 z=HS
        assert sets.count(("coord1", [20.0, 0.0])) == 1
        assert sets.count(("coord2", [20.0, 0.508])) == 1
        # study：每端口一个边界模分析步（官方 cpw 例 std=[bma1, bma2, freq]）
        study_creates = [a for _, a in _calls_named(calls, "study.create")]
        assert ("bma1", "BoundaryModeAnalysis") in study_creates
        assert ("bma2", "BoundaryModeAnalysis") in study_creates
        assert ("freq", "Frequency") in study_creates
        assert study_creates.index(("bma1", "BoundaryModeAnalysis")) < \
            study_creates.index(("freq", "Frequency"))
        # bma 步绑定端口 + 模式分析频率 + 本征值搜索偏移（真机 dump 实录）
        assert sets.count(("PortName", "1")) >= 1  # bma1 绑定（端口也有 PortName）
        assert sets.count(("PortName", "2")) >= 1
        assert sets.count(("modeFreq", "2.5[GHz]")) == 2
        assert sets.count(("shift", "sqrt(epsr)")) == 2
        # 数值 TEM 边界模分析步无 plist（真机实证：BoundaryModeAnalysis 与
        # 频点无关；单频端口模是解析变体 tbma 的口径）；plist 只在 freq 步
        step_plists = [a for n, a in _calls_named(calls, "study.create.set")
                       if a and a[0] == "plist"]
        assert step_plists == [("plist", "2.3[GHz] 2.5[GHz] 2.7[GHz]")]
        # 证据回填
        assert adapter._result.field_data["port_chain"] == "tem"

    def test_solve_tem_chain_supports_port_sweep(self, tmp_path, monkeypatch):
        # tem 链 + 端口扫描组合：两口激励候选 + Parametric 步仍在
        data = _full_eval_data(self.FREQS)
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client,
                                mline_port_chain="tem")
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": self.FREQS},
                                       "port_sweep": True})
        result = adapter.solve()
        assert result.success, result.message
        sets = [a for _, a in _calls_named(client.calls, ".set")]
        assert sets.count(("PortExcitation", "on")) == 2
        study_creates = [a for _, a in _calls_named(client.calls, "study.create")]
        assert ("param", "Parametric") in study_creates

    def test_spec_note_declares_tem_chain(self, tmp_path, monkeypatch):
        self._solved(tmp_path, monkeypatch)
        spec = json.loads((tmp_path / "work" / "comsol_spec.json")
                          .read_text(encoding="utf-8"))
        assert spec["port_chain"] == "tem"
        assert "数值 TEM 边界模端口完整链" in spec["note"]


class TestLossTangentMaterial:
    """tanδ 介质损耗口径（官方 RF 材料库 LossTangentDF 组实录）。"""

    def test_lossy_dielectric_uses_losstangentdf_group(self, tmp_path,
                                                       monkeypatch):
        f = np.asarray([2.3, 2.5, 2.7], float)
        s = tl_section_sparams(f, 2.85264, 50.011, 40.0)
        data = {"real": [list(f * 1e9), list(s[:, 0, 0].real),
                         list(s[:, 1, 0].real)],
                "imag": [[0.0] * 3, list(s[:, 0, 0].imag),
                         list(s[:, 1, 0].imag)]}
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client,
                                mline_port_chain="tem", loss_tangent=0.0037)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": [2.3, 2.5, 2.7]}})
        result = adapter.solve()
        assert result.success, result.message
        calls = client.calls
        sets = [a for _, a in _calls_named(calls, ".set")]
        # propertyGroup().create(tag, type) 两参建组（6.3 客户端真机实证：
        # 无单参 create；官方材料库 dmodel op=tag=type 同名）
        group_creates = [a for n, a in calls
                         if n.endswith("propertyGroup.create")]
        assert group_creates.count(("LossTangentDF", "LossTangentDF")) == 1  # 仅基板
        assert sets.count(("epsilonPrim", ["epsr"])) == 1
        assert sets.count(("tanDelta", ["0.0037"])) == 1
        # def 组不再设 relpermittivity（Rogers 材料实录口径）
        assert ("relpermittivity", ["epsr"]) not in sets
        # 空气仍走无耗 def 组
        assert ("relpermittivity", ["1"]) in sets
        assert adapter._result.field_data["loss_tangent"] == 0.0037

    def test_default_stays_lossless_zero_regression(self, tmp_path,
                                                    monkeypatch):
        # 默认（无 loss_tangent）不建损耗组、def 组 relpermittivity 保留
        f = np.asarray([2.3, 2.5, 2.7], float)
        s = tl_section_sparams(f, 2.85264, 50.011, 40.0)
        data = {"real": [list(f * 1e9), list(s[:, 0, 0].real),
                         list(s[:, 1, 0].real)],
                "imag": [[0.0] * 3, list(s[:, 0, 0].imag),
                         list(s[:, 1, 0].imag)]}
        client = _FakeClient(data)
        adapter = _make_adapter(tmp_path, monkeypatch, client=client)
        adapter.connect()
        assert adapter.build_geometry({"template": "mline",
                                       "params": {"freq_ghz": [2.3, 2.5, 2.7]}})
        assert adapter.solve().success
        calls = client.calls
        sets = [a for _, a in _calls_named(calls, ".set")]
        group_creates = [a for n, a in calls
                         if n.endswith("propertyGroup.create")]
        assert group_creates.count(("LossTangentDF",)) == 0
        assert ("relpermittivity", ["epsr"]) in sets

    def test_normalize_loss_tangent_gates(self):
        assert ca.normalize_loss_tangent(None) is None
        assert ca.normalize_loss_tangent({}) is None
        assert ca.normalize_loss_tangent({"loss_tangent": 0.0037}) == 0.0037
        with pytest.raises(ValueError):
            ca.normalize_loss_tangent({"loss_tangent": 0})  # 0 应用 None 表达
        with pytest.raises(ValueError):
            ca.normalize_loss_tangent({"loss_tangent": -1.0})
        with pytest.raises(ValueError):
            ca.normalize_loss_tangent({"loss_tangent": float("nan")})


class TestChainRouting:
    """端口链路由与 spec 证据（默认 lumped 零回归由 TestMlineSolveMock 钉）。"""

    def test_normalize_port_chain(self):
        assert ca.normalize_port_chain(None) == "lumped"
        assert ca.normalize_port_chain({}) == "lumped"
        assert ca.normalize_port_chain({"mline_port_chain": "tem"}) == "tem"
        with pytest.raises(ValueError):
            ca.normalize_port_chain({"mline_port_chain": "wave"})

    def test_invalid_chain_build_returns_false(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path, monkeypatch,
                                mline_port_chain="wave")
        adapter.connect()
        assert not adapter.build_geometry({"template": "mline",
                                           "params": {"freq_ghz": [2.5]}})


# ─── D: 全 S 装配与 Touchstone 校验 ──────────────────────────────────────────
class TestExtractFullAssembly:
    def test_assembly_identifies_columns_by_freq_and_port(self, tmp_path,
                                                          monkeypatch):
        # 列交错 + 端口 2 列含干扰值：装配必须按 (freq, PortName) 识别
        freqs = [2.3, 2.5, 2.7]
        data = _full_eval_data(freqs, shuffle=True)
        model = _FakeModel([], data)
        f_ghz, s = ComsolAdapter._extract_sparams_full(model, freqs)
        assert np.allclose(f_ghz, freqs)
        expected = tl_section_sparams(np.asarray(freqs), 2.85264, 50.0, 40.0)
        assert np.allclose(s, expected, atol=1e-12)

    def test_assembly_raises_on_missing_solutions(self):
        data = _full_eval_data([2.3, 2.5])
        for row in (data["real"], data["imag"]):  # 掐掉端口 2 的全部解列
            for r in row:
                del r[2:4]
        model = _FakeModel([], data)
        with pytest.raises(RuntimeError, match="装配不完整"):
            ComsolAdapter._extract_sparams_full(model, [2.3, 2.5])


class TestTouchstoneRoundTrip:
    def test_skrf_written_s2p_passes_reciprocity_passivity_gates(self,
                                                                 tmp_path):
        # 兜底写出的 .s2p 必须过互易/无源/无耗单位性三判据（真机证据
        # runs/comsol_tail/ 用同一判据读 COMSOL 原生导出）
        import skrf

        freqs = np.linspace(2.3, 2.7, 5)
        s = tl_section_sparams(freqs, 2.85264, 50.011, 40.0)
        path = tmp_path / "sparams.s2p"
        ntw = skrf.Network(
            frequency=skrf.Frequency(float(freqs[0]), float(freqs[-1]),
                                     len(freqs), unit="GHz"),
            s=s, z0=50.0)
        ntw.write_touchstone(str(path))

        rd = skrf.Network(str(path))
        assert rd.s.shape == (5, 2, 2)
        reciprocity = float(np.max(np.abs(rd.s[:, 0, 1] - rd.s[:, 1, 0])))
        assert reciprocity < 1e-12
        max_abs = float(np.max(np.abs(rd.s)))
        assert max_abs <= 1.0 + 1e-9  # 无源
        unitary = float(np.max(np.abs(
            np.abs(rd.s[:, 0, 0]) ** 2 + np.abs(rd.s[:, 1, 0]) ** 2 - 1.0)))
        assert unitary < 1e-9  # 无耗（真机判据门 0.01）

    def test_extract_eps_eff_on_synthetic_line_hits_closed_form(self):
        # β 金标准判据（#162）：S21 相位斜率反推 εeff
        freqs = np.linspace(2.3, 2.7, 5)
        s = tl_section_sparams(freqs, 2.85264, 50.011, 40.0)
        assert extract_eps_eff(freqs, s[:, 1, 0], 40.0) == pytest.approx(
            2.85264, rel=1e-6)
