"""A4 ElmerAdapter 离线确定性测试（不真跑 Elmer）。

覆盖：参数规范化 / 闭式解析解 / Gmsh+SIF 文本生成 / SaveLine 解析 /
闭式对照 / runner 注入下的 build+solve 全链路 / best-effort 失败路径 /
能力声明与注册表。

纪律：全部用 monkeypatch/注入 runner，禁止真实 Elmer 子进程；对
resolve_elmer_bin 的「不可用」用例同时清除环境变量与默认安装根，
保证换机（无 Elmer）也稳定。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

import rfauto.adapters  # noqa: F401  —— 导入副作用：elmer 导入即注册（全局注册表）
from rfauto.adapters import elmer_adapter as ea
from rfauto.adapters.elmer_adapter import (
    ElmerAdapter,
    build_gmsh_quad_strip,
    build_slab_sif,
    compare_temperature_profiles,
    normalize_slab_params,
    parse_save_line,
    register_elmer_adapter,
    resolve_elmer_bin,
    run_command,
    slab_temperature_closed_form,
)
from rfauto.adapters.em_solver_base import (
    CAPABILITY_METHOD_REQUIREMENTS,
    EMSolverConfig,
    EMSolverRegistry,
    EMSolverType,
    create_solver_from_config,
    get_global_registry,
    load_solvers_config,
    solver_capabilities_for,
)

# 仓库内 solvers.yaml 绝对路径（接线验收不依赖 pytest 的 cwd）
_REPO_SOLVERS_YAML = Path(__file__).resolve().parents[2] / "configs" / "solvers.yaml"

# ── 公共夹具 ──────────────────────────────────────────────────────────────────


def _no_elmer(monkeypatch) -> None:
    """抹掉一切 Elmer 发现路径（环境变量 + 默认安装根 + PATH）。"""
    monkeypatch.delenv(ea.ELMER_HOME_ENV, raising=False)
    monkeypatch.delenv(ea.RFAUTO_ELMER_BIN_ENV, raising=False)
    monkeypatch.setattr(ea, "DEFAULT_ELMER_HOME", r"Z:\definitely-no-elmer")
    monkeypatch.setattr(shutil, "which", lambda name: None)


def _fake_install(tmp_path: Path, *, with_grid: bool = True) -> Path:
    """伪造 Elmer 安装：bin/ElmerSolver.exe（可选 ElmerGrid.exe）。"""
    bin_dir = tmp_path / "Elmer" / "bin"
    bin_dir.mkdir(parents=True)
    solver = bin_dir / "ElmerSolver.exe"
    solver.write_text("stub", encoding="ascii")
    if with_grid:
        (bin_dir / "ElmerGrid.exe").write_text("stub", encoding="ascii")
    return solver


def _make_runner(
    *,
    grid_rc: int = 0,
    solver_rc: int = 0,
    solver_timeout: bool = False,
    write_line: bool = True,
    line_text: str | None = None,
):
    """伪造 run_command：ElmerGrid 造 mesh.header，ElmerSolver 造 line.dat。

    返回 (runner, calls)；runner 记录全部命令行供断言。
    """
    calls: list[list[str]] = []

    def runner(cmd, timeout_s, cwd=None):
        calls.append([str(c) for c in cmd])
        exe = Path(str(cmd[0])).name
        if "--version" in cmd:
            return {"rc": 0, "stdout": "ELMER SOLVER (v 26.1) STARTED AT: x",
                    "stderr": "", "timed_out": False, "elapsed_s": 0.01}
        wd = Path(cwd) if cwd is not None else Path(".")
        if exe.startswith("ElmerGrid"):
            if grid_rc == 0:
                mesh = wd / ea.MESH_DIR
                mesh.mkdir(parents=True, exist_ok=True)
                (mesh / "mesh.header").write_text("1 0 0\n", encoding="utf-8")
            return {"rc": grid_rc, "stdout": "ElmerGrid done",
                    "stderr": "" if grid_rc == 0 else "grid exploded",
                    "timed_out": False, "elapsed_s": 0.01}
        if write_line and not solver_timeout and solver_rc == 0:
            text = line_text
            if text is None:
                spec = normalize_slab_params(None)
                x = np.linspace(0.0, spec["thickness_mm"] / 1000.0,
                                int(spec["n_x"]) + 1)
                t = slab_temperature_closed_form(
                    x, spec["thickness_mm"] / 1000.0,
                    spec["heat_source_w_m3"], spec["heat_conductivity_w_mk"],
                    spec["t0_k"])
                rows = [
                    f"1 1 {10 + i} {xi:.5e} 2.5e-02 0.0 {ti:.6e}"
                    for i, (xi, ti) in enumerate(zip(x, t, strict=True))
                ]
                # 故意打乱顺序：解析器必须按 x 排序
                text = "\n".join(rows[::-1]) + "\n"
            (wd / ea.RESULT_LINE_FILE).write_text(text, encoding="utf-8")
        return {"rc": solver_rc,
                "stdout": "ELMER SOLVER FINISHED" if solver_rc == 0 else "",
                "stderr": "" if solver_rc == 0 else "solver exploded",
                "timed_out": solver_timeout, "elapsed_s": 0.02}

    return runner, calls


def _connected_adapter(tmp_path: Path, runner, *, with_grid: bool = True,
                       extra: dict | None = None) -> ElmerAdapter:
    solver = _fake_install(tmp_path, with_grid=with_grid)
    cfg = EMSolverConfig(solver_type=EMSolverType.ELMER, exe_path=str(solver),
                         working_dir=str(tmp_path / "run"),
                         extra_params=dict(extra or {}))
    adapter = ElmerAdapter(cfg, runner=runner)
    assert adapter.connect()
    return adapter


# ── 参数规范化 ────────────────────────────────────────────────────────────────


class TestNormalizeSlabParams:
    def test_defaults(self):
        spec = normalize_slab_params(None)
        assert spec["thickness_mm"] == 100.0
        assert spec["heat_source_w_m3"] == 1000.0
        assert spec["heat_conductivity_w_mk"] == 1.0
        assert spec["t0_k"] == 300.0
        assert spec["n_x"] == 40 and isinstance(spec["n_x"], int)
        assert spec["n_y"] == 2

    def test_override(self):
        spec = normalize_slab_params({"thickness_mm": 20.0, "n_x": 8, "t0_k": 293.15})
        assert spec["thickness_mm"] == 20.0
        assert spec["n_x"] == 8
        assert spec["t0_k"] == 293.15
        assert spec["width_mm"] == 50.0  # 未提供的键保默认

    @pytest.mark.parametrize("bad", [{"thickness_mm": 0}, {"thickness_mm": -1},
                                     {"heat_source_w_m3": 0}, {"t0_k": -5}])
    def test_rejects_nonpositive(self, bad):
        with pytest.raises(ValueError, match="必须为正数"):
            normalize_slab_params(bad)

    @pytest.mark.parametrize("bad", [{"n_x": 2.5}, {"n_x": 0}, {"n_y": -1}])
    def test_rejects_noninteger_grid(self, bad):
        with pytest.raises(ValueError, match="必须为正整数"):
            normalize_slab_params(bad)


# ── 闭式解析解（裁判） ────────────────────────────────────────────────────────


class TestClosedForm:
    def test_known_values(self):
        L, q, k, t0 = 0.1, 1000.0, 1.0, 300.0
        assert slab_temperature_closed_form(0.0, L, q, k, t0) == pytest.approx(300.0)
        assert slab_temperature_closed_form(L, L, q, k, t0) == pytest.approx(305.0)
        assert slab_temperature_closed_form(L / 2, L, q, k, t0) == pytest.approx(303.75)

    def test_monotonic_and_insulated_far_end(self):
        L, q, k, t0 = 0.1, 1000.0, 1.0, 300.0
        x = np.linspace(0.0, L, 101)
        t = slab_temperature_closed_form(x, L, q, k, t0)
        assert np.all(np.diff(t) > 0)
        # 右端绝热 <=> dT/dx(L)=0：解析上 T(L)-T(L-d) = q/(2k)·d²（一阶项为零）
        delta = x[-1] - x[-2]
        assert (t[-1] - t[-2]) == pytest.approx(q / (2.0 * k) * delta ** 2, rel=1e-9)
        # 末段温升远小于首段（首段 ~ q/k·L·delta，末段 ~ q/(2k)·delta²）
        assert (t[-1] - t[-2]) < 0.01 * (t[1] - t[0])

    def test_scaling_with_source_and_conductivity(self):
        x = np.array([0.1])
        base = slab_temperature_closed_form(x, 0.1, 1000.0, 1.0, 300.0)
        doubled = slab_temperature_closed_form(x, 0.1, 2000.0, 1.0, 300.0)
        halved_k = slab_temperature_closed_form(x, 0.1, 1000.0, 2.0, 300.0)
        assert (doubled - 300.0) == pytest.approx(2 * (base - 300.0))
        assert (halved_k - 300.0) == pytest.approx(0.5 * (base - 300.0))


# ── Gmsh 文本 ─────────────────────────────────────────────────────────────────


class TestGmshMesh:
    def test_counts(self):
        text = build_gmsh_quad_strip(0.1, 0.05, 4, 2)
        assert "$MeshFormat" in text and "2.2 0 8" in text
        # 节点 (4+1)*(2+1)=15；单元 4*2 四边形 + (2+2+4+4) 边界线 = 20
        assert text.split("$Nodes\n")[1].splitlines()[0] == "15"
        assert text.split("$Elements\n")[1].splitlines()[0] == "20"
        assert text.count("$EndElements") == 1

    def test_element_tags(self):
        text = build_gmsh_quad_strip(0.1, 0.05, 3, 1)
        body = [ln for ln in text.splitlines()
                if len(ln.split()) == 9 and ln.split()[1] == "3"]
        assert len(body) == 3  # 3 个四边形（4 节点 + 2 标签 + 类型 + 编号）
        for tag in (2, 3, 4, 5):  # 左/右/上/下 边界 physical tag
            assert f" 1 2 {tag} {tag} " in text

    def test_coordinates_span_domain(self):
        text = build_gmsh_quad_strip(0.1, 0.05, 2, 2)
        coords = [ln.split() for ln in text.split("$Nodes\n")[1].splitlines()[1:]]
        xs = sorted({float(c[1]) for c in coords if len(c) == 4})
        ys = sorted({float(c[2]) for c in coords if len(c) == 4})
        assert xs == pytest.approx([0.0, 0.05, 0.1])
        assert ys == pytest.approx([0.0, 0.025, 0.05])

    def test_rejects_bad_grid(self):
        with pytest.raises(ValueError):
            build_gmsh_quad_strip(0.1, 0.05, 0, 1)


# ── SIF 文本 ──────────────────────────────────────────────────────────────────


class TestSif:
    def _sif(self, **kw):
        args = {"length_m": 0.1, "width_m": 0.05, "heat_source_w_m3": 1000.0,
                "heat_conductivity_w_mk": 1.0, "t0_k": 300.0}
        args.update(kw)
        return build_slab_sif(**args)

    def test_uses_volumetric_heat_source(self):
        # 真机实证回归：Heat Source 关键字在 26.1 不被 HeatSolver 消费，
        # 必须用 Volumetric Heat Source（否则 T≡T0）
        sif = self._sif()
        assert "Volumetric Heat Source = 1000" in sif
        assert "\n  Heat Source = " not in sif

    def test_required_blocks(self):
        sif = self._sif()
        for token in ('Equation = Heat Equation', 'Procedure = "HeatSolve" "HeatSolver"',
                      'Procedure = "SaveData" "SaveLine"', "Body Force = 1",
                      "Material = 1", "Steady State Max Iterations = 1"):
            assert token in sif, token

    def test_boundary_conditions(self):
        sif = self._sif()
        assert "Target Boundaries(1) = 2" in sif
        assert "Temperature = 300" in sif
        assert "Target Boundaries(3) = 3 4 5" in sif
        assert "Heat Flux = 0.0" in sif

    def test_polyline_along_midline(self):
        sif = self._sif()
        assert "Polyline Coordinates(2,3) = Real 0.0 0.025 0.0  0.1 0.025 0.0" in sif

    def test_solver_indices_contiguous(self):
        # 真机实证：Solver 缺号 -> ERROR:: LoadInputFile: Entry missing
        sif = self._sif()
        assert "Solver 1" in sif and "Solver 2" in sif and "Solver 3" not in sif


# ── SaveLine 解析 ─────────────────────────────────────────────────────────────


class TestParseSaveLine:
    def test_sorts_by_x(self):
        text = ("1 1 3 0.2 0.0 0.0 302.0\n"
                "1 1 1 0.0 0.0 0.0 300.0\n"
                "1 1 2 0.1 0.0 0.0 301.0\n")
        x, t = parse_save_line(text)
        assert x.tolist() == [0.0, 0.1, 0.2]
        assert t.tolist() == [300.0, 301.0, 302.0]

    def test_takes_last_block(self):
        text = ("1 1 1 0.0 0.0 0.0 300.0\n"
                "2 1 1 0.0 0.0 0.0 311.0\n"
                "2 1 2 0.1 0.0 0.0 322.0\n")
        x, t = parse_save_line(text)
        assert x.tolist() == [0.0, 0.1]
        assert t.tolist() == [311.0, 322.0]

    def test_ignores_blank_lines(self):
        x, t = parse_save_line("\n\n1 1 1 0.0 0.0 0.0 300.0\n\n")
        assert x.tolist() == [0.0] and t.tolist() == [300.0]

    def test_rejects_short_row(self):
        with pytest.raises(ValueError, match="列数"):
            parse_save_line("1 1 1 0.0 300.0\n")

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError, match="非数值"):
            parse_save_line("1 1 1 0.0 0.0 0.0 abc\n")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="无可解析"):
            parse_save_line("\n# comment only\n")


# ── 闭式对照 ──────────────────────────────────────────────────────────────────


class TestCompareProfiles:
    def test_exact_match(self):
        x = np.linspace(0.0, 0.1, 5)
        t = slab_temperature_closed_form(x, 0.1, 1000.0, 1.0, 300.0)
        rep = compare_temperature_profiles(x, t, x, t)
        assert rep["max_abs_deviation_k"] == 0.0
        assert rep["max_relative_deviation"] == 0.0
        assert rep["reference_rise_k"] == pytest.approx(5.0)
        assert rep["n_points"] == 5

    def test_known_one_percent(self):
        x = np.linspace(0.0, 0.1, 5)
        ref = slab_temperature_closed_form(x, 0.1, 1000.0, 1.0, 300.0)
        num = ref + 0.05  # 升幅 5 K 的 1%
        rep = compare_temperature_profiles(x, num, x, ref)
        assert rep["max_abs_deviation_k"] == pytest.approx(0.05)
        assert rep["max_relative_deviation"] == pytest.approx(0.01)

    def test_interpolates_reference_grid(self):
        x_num = np.linspace(0.0, 0.1, 41)
        x_ref = np.array([0.0, 0.1])
        t_ref = np.array([300.0, 305.0])
        num = 300.0 + 50.0 * x_num  # 线性，恰为粗网格参考的插值
        rep = compare_temperature_profiles(x_num, num, x_ref, t_ref)
        assert rep["max_abs_deviation_k"] == pytest.approx(0.0, abs=1e-12)

    def test_flat_reference_falls_back_to_absolute(self):
        x = np.array([0.0, 0.1])
        rep = compare_temperature_profiles(x, np.array([300.0, 300.2]),
                                           x, np.array([300.0, 300.0]))
        assert rep["reference_rise_k"] == 0.0
        assert rep["max_relative_deviation"] == pytest.approx(0.2)

    def test_rejects_too_few_points(self):
        with pytest.raises(ValueError):
            compare_temperature_profiles(np.array([]), np.array([]),
                                         np.array([0.0]), np.array([1.0]))


# ── runner 注入下的适配器全链路 ────────────────────────────────────────────────


class TestBuildGeometry:
    def test_writes_mesh_sif_and_converts(self, tmp_path):
        runner, calls = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        assert adapter.build_geometry({})
        workdir = tmp_path / "run"
        assert (workdir / ea.GMSH_FILE).exists()
        assert (workdir / ea.SIF_FILE).exists()
        assert (workdir / ea.MESH_DIR / "mesh.header").exists()
        grid_calls = [c for c in calls if "ElmerGrid" in c[0]]
        assert len(grid_calls) == 1
        assert grid_calls[0][1:3] == ["14", "2"]  # Gmsh -> ElmerSolver mesh

    def test_sif_written_matches_builder(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({"thickness_mm": 20.0, "width_mm": 10.0})
        sif = (tmp_path / "run" / ea.SIF_FILE).read_text(encoding="utf-8")
        assert "Volumetric Heat Source" in sif
        assert "0.005" in sif  # 20mm/2 中线

    def test_fails_without_grid_binary(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner, with_grid=False)
        assert not adapter.build_geometry({})
        assert "ElmerGrid" in adapter._last_message

    def test_fails_when_not_connected(self, tmp_path):
        cfg = EMSolverConfig(solver_type=EMSolverType.ELMER,
                             working_dir=str(tmp_path / "run"))
        adapter = ElmerAdapter(cfg, runner=_make_runner()[0])
        assert not adapter.build_geometry({})
        assert "未连接" in adapter._last_message

    def test_fails_on_bad_params(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        assert not adapter.build_geometry({"thickness_mm": -1})
        assert "参数非法" in adapter._last_message

    def test_fails_on_grid_nonzero_rc(self, tmp_path):
        runner, _ = _make_runner(grid_rc=3)
        adapter = _connected_adapter(tmp_path, runner)
        assert not adapter.build_geometry({})
        assert "ElmerGrid rc=3" in adapter._last_message


class TestSolveOffline:
    def test_success_and_closed_form_comparison(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        assert adapter.build_geometry({})
        result = adapter.solve()
        assert result.success, result.message
        x = result.field_data["x_m"]
        t = result.field_data["temperature_k"]
        assert x.size == 41
        assert x[0] == 0.0 and x[-1] == pytest.approx(0.1)
        assert t[0] == pytest.approx(300.0)
        assert t[-1] == pytest.approx(305.0)
        rep = adapter.deviation_report()
        assert rep["max_relative_deviation"] <= 0.01
        assert result.field_data["deviation_vs_closed_form"]["pass_1pct"] is True
        assert adapter.temperature_field()["x_m"].size == 41
        assert adapter.closed_form_profile()["temperature_k"][-1] == pytest.approx(305.0)

    def test_solve_accepts_explicit_timeout(self, tmp_path):
        runner, calls = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({})
        adapter.solve(timeout_s=12.5)
        solver_calls = [c for c in calls
                        if c[0].endswith("ElmerSolver.exe") and "--version" not in c]
        assert len(solver_calls) == 1  # --version 之外的求解调用

    def test_nonzero_rc_reports_failure(self, tmp_path):
        runner, _ = _make_runner(solver_rc=1)
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({})
        result = adapter.solve()
        assert not result.success
        assert "rc=1" in result.message

    def test_timeout_reports_failure(self, tmp_path):
        runner, _ = _make_runner(solver_timeout=True)
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({})
        result = adapter.solve(timeout_s=1.0)
        assert not result.success
        assert "超时" in result.message

    def test_missing_result_file(self, tmp_path):
        runner, _ = _make_runner(write_line=False)
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({})
        result = adapter.solve()
        assert not result.success
        assert ea.RESULT_LINE_FILE in result.message

    def test_corrupt_result_file(self, tmp_path):
        runner, _ = _make_runner(line_text="1 1 1 0.0\n")
        adapter = _connected_adapter(tmp_path, runner)
        adapter.build_geometry({})
        result = adapter.solve()
        assert not result.success
        assert "结果解析失败" in result.message

    def test_solve_before_build(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        result = adapter.solve()
        assert not result.success
        assert "未建模" in result.message

    def test_get_sparams_is_explicit_error(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        with pytest.raises(NotImplementedError):
            adapter.get_sparams()


class TestBestEffortUnavailable:
    def test_resolve_none_and_connect_false(self, tmp_path, monkeypatch):
        _no_elmer(monkeypatch)
        assert resolve_elmer_bin(None) is None
        cfg = EMSolverConfig(solver_type=EMSolverType.ELMER,
                             exe_path=str(tmp_path / "missing.exe"),
                             working_dir=str(tmp_path / "run"))
        adapter = ElmerAdapter(cfg, runner=_make_runner()[0])
        assert adapter.is_available() is False
        assert adapter.connect() is False
        # 不崩：build/solve 返回结构化失败
        assert adapter.build_geometry({}) is False
        result = adapter.solve()
        assert result.success is False
        assert "未连接" in result.message
        assert adapter.temperature_field() is None
        assert adapter.deviation_report() is None

    def test_run_command_never_raises_on_missing_exe(self):
        info = run_command(["definitely-not-a-real-executable-xyz"], 5.0)
        assert info["rc"] == -1
        assert info["timed_out"] is False
        assert info["stderr"]


class TestCapabilitiesAndRegistry:
    def test_declared_capabilities(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        caps = adapter.capabilities()
        assert caps.solver_type == "elmer"
        assert caps.available is True
        assert caps.dimension == "2d"
        assert caps.requires_license is False
        assert caps.supports_field_export is True
        assert caps.supports_touchstone_export is False
        assert caps.material_models == ()
        assert caps.supported_templates == (ea.TEMPLATE_HEAT_SLAB_1D,)
        # 声明为真的能力位必须有对应实现方法（em_solver_base 一致性口径）
        assert any(hasattr(adapter, method)
                   for method in CAPABILITY_METHOD_REQUIREMENTS["supports_field_export"])
        assert hasattr(adapter, "temperature_field")

    def test_register_into_registry(self, tmp_path):
        reg = EMSolverRegistry()
        register_elmer_adapter(reg)
        assert reg.is_registered(EMSolverType.ELMER)
        cfg = EMSolverConfig(solver_type=EMSolverType.ELMER,
                             exe_path=str(tmp_path / "x.exe"))
        made = reg.create(EMSolverType.ELMER, cfg)
        assert isinstance(made, ElmerAdapter)

    def test_visualizations_empty_before_build(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        assert adapter.visualizations() == []
        adapter.build_geometry({})
        adapter.solve()
        kinds = {v["kind"] for v in adapter.visualizations()}
        assert kinds == {"model3d", "field"}

    def test_close(self, tmp_path):
        runner, _ = _make_runner()
        adapter = _connected_adapter(tmp_path, runner)
        adapter.close()
        assert adapter.solve().success is False


class TestGlobalWiring:
    """注册接线验收（A4/WP4.4d 接线项，2026-09-15）：全离线可断言。

    四判据：全局注册表 / configs/solvers.yaml / list_registered_solvers
    （CLI `rfauto solvers list` 与 UI /api/solvers 的数据源）/
    solver_capabilities_for 四条链路都能看到 elmer。
    """

    def test_global_registry_has_elmer(self):
        assert get_global_registry().is_registered(EMSolverType.ELMER)

    def test_solvers_yaml_elmer_loadable_and_creatable(self):
        configs = load_solvers_config(_REPO_SOLVERS_YAML)
        assert "elmer" in configs
        assert configs["elmer"].solver_type is EMSolverType.ELMER
        solver = create_solver_from_config("elmer", path=_REPO_SOLVERS_YAML)
        assert isinstance(solver, ElmerAdapter)
        assert solver._connected is False  # 只创建实例，不 connect

    def test_list_registered_solvers_reports_elmer(self):
        from rfauto.service.r3_services import list_registered_solvers

        assert get_global_registry().is_registered(EMSolverType.ELMER)
        names = [s["type"] for s in list_registered_solvers()["solvers"]]
        assert "elmer" in names

    def test_solver_capabilities_for_elmer_positive(self):
        # 原消费面把 ELMER 当「未声明能力」KeyError 探针——接线后反转为正向断言
        caps = solver_capabilities_for(EMSolverType.ELMER)
        assert caps.solver_type == "elmer"
        assert caps.dimension == "2d"
