"""A3 PalaceSolver 完整实现测试（配置生成 → mock 可执行 → CSV 解析）。"""

from __future__ import annotations

import json
import stat
import sys


def _make_palace_stub(workdir, result_rows):
    """生成 mock palace 可执行文件：运行后产出 palace.csv。"""
    csv_body = "Frequency (GHz),re(S11),im(S11)\n"
    for f, re_, im in result_rows:
        csv_body += f"{f},{re_},{im}\n"
    ref = workdir / "palace_reference.csv"
    ref.write_text(csv_body, encoding="utf-8")
    if sys.platform == "win32":
        exe = workdir / "palace.cmd"
        exe.write_text(
            "@echo off\r\ncopy /y palace_reference.csv palace.csv >nul\r\n",
            encoding="ascii")
    else:
        exe = workdir / "palace.sh"
        exe.write_text("#!/bin/sh\ncp palace_reference.csv palace.csv\n",
                       encoding="ascii")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


class TestPalaceConfigGeneration:
    def test_build_geometry_writes_config(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        workdir = tmp_path / "run"
        dummy_exe = tmp_path / "palace-mock"
        dummy_exe.write_text("", encoding="ascii")
        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path=str(dummy_exe), working_dir=str(workdir),
                             freq_range_ghz=(2.0, 3.0))
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({"mesh_file": "board.msh"})
        text = (workdir / "palace_config.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert data["Mesh"]["MeshFile"] == "board.msh"
        assert data["Solver"]["Type"] == "DrivenSParam"
        assert data["Solver"]["MinimumFreq"] == 2.0e9
        assert data["Solver"]["MaximumFreq"] == 3.0e9

    def test_build_geometry_requires_mesh(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path="palace-mock", working_dir=str(tmp_path))
        solver = PalaceSolver(cfg)
        solver.connect()
        assert not solver.build_geometry({})

    def test_solve_without_config_fails_cleanly(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path="palace-mock", working_dir=str(tmp_path))
        solver = PalaceSolver(cfg)
        solver.connect()
        result = solver.solve()
        assert not result.success


class TestPalaceSolveMock:
    def test_solve_via_mock_exe(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        workdir = tmp_path / "run"
        workdir.mkdir()
        exe = _make_palace_stub(workdir, [
            (2.0, 0.1, -0.05), (2.5, 0.03, -0.01), (3.0, 0.2, 0.1),
        ])
        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path=str(exe), working_dir=str(workdir),
                             freq_range_ghz=(2.0, 3.0))
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({"mesh_file": "board.msh"})
        result = solver.solve()
        assert result.success, result.message
        assert len(result.freq_ghz) == 3
        assert abs(result.s_params[1, 0, 0]) < 0.05  # 2.5GHz 匹配点
        assert abs(result.s_params[0, 0, 0]) > 0.1

    def test_visualizations_declared(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path="palace-mock", working_dir=str(tmp_path),
                             extra_params={"mesh_file": "board.msh"})
        solver = PalaceSolver(cfg)
        kinds = [v["kind"] for v in solver.visualizations()]
        assert "model3d" in kinds and "sparams" in kinds

    def test_registered_and_listed(self):
        import rfauto.adapters  # noqa: F401
        from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry
        from rfauto.service.r3_services import list_registered_solvers
        assert get_global_registry().is_registered(EMSolverType.PALACE)
        names = [s["type"] for s in list_registered_solvers()["solvers"]]
        assert "palace" in names
