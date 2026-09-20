"""openEMS 模板 + 求解器适配器测试（E1a 缺口补齐批次）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    create_solver_from_config,
    get_global_registry,
    load_solvers_config,
)
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.openems_templates import render_script


def _config(tmp_path: Path, **kw) -> EMSolverConfig:
    return EMSolverConfig(
        solver_type=EMSolverType.OPENEMS,
        working_dir=str(tmp_path / "openems_run"),
        **kw,
    )


def _connected_solver(tmp_path: Path) -> OpenEMSSolver:
    s = OpenEMSSolver(_config(tmp_path))
    # 无真实 openEMS 安装的环境也要能 build——直接置 exe 为占位路径
    s._exe_path = str(tmp_path / "openEMS.exe")
    (tmp_path / "openEMS.exe").write_text("", encoding="utf-8")
    assert s.connect()
    return s


class TestTemplates:
    def test_wilkinson_script_contains_geometry_and_csv_contract(self):
        script = render_script(
            "wilkinson",
            {"f0_ghz": 2.4, "series_w_mm": 0.33, "shunt_w_mm": 1.10, "arm_len_mm": 20.5},
            (1.5, 3.5),
        )
        assert "MSLPort" in script
        assert "sparams.csv" in script
        # CSV 契约列序：freq, re(S11), im(S11), re(S21), im(S21)
        assert '["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"]' in script
        # 参数被代入
        assert "0.33" in script
        assert "20.5" in script

    def test_patch_script_contains_patch_geometry(self):
        script = render_script(
            "patch",
            {"f0_ghz": 2.4, "patch_len_mm": 40.0, "patch_w_mm": 50.0,
             "feed_offset_mm": 10.0},
            (1.5, 3.5),
        )
        assert "40.0" in script
        assert "patch.AddBox" in script

    def test_freq_values_in_hz(self):
        script = render_script("wilkinson", {}, (1.0, 5.0))
        assert "3000000000.0" in script  # 中心 3 GHz
        assert "2000000000.0" in script  # 半带宽 2 GHz


class TestOpenEMSSolverBuild:
    def test_build_requires_connect(self, tmp_path):
        s = OpenEMSSolver(_config(tmp_path))
        assert s.build_geometry({"template": "wilkinson", "params": {}}) is False

    def test_build_template_writes_script(self, tmp_path):
        s = _connected_solver(tmp_path)
        assert s.build_geometry({"template": "wilkinson", "params": {"f0_ghz": 2.4}})
        script = (tmp_path / "openems_run" / "simulation.py").read_text(encoding="utf-8")
        assert "MSLPort" in script

    def test_solve_without_build_fails_cleanly(self, tmp_path):
        s = _connected_solver(tmp_path)
        result = s.solve()
        assert result.success is False

    def test_parse_output_reads_csv(self, tmp_path):
        s = _connected_solver(tmp_path)
        s.build_geometry({"template": "wilkinson", "params": {}})
        run_dir = tmp_path / "openems_run"
        freq = np.array([2e9, 3e9])
        data = np.column_stack([
            freq,
            np.zeros(2), np.full(2, 0.1),   # S11 = 0.1j
            np.full(2, 0.7), np.zeros(2),   # S21 = 0.7
        ])
        header = "freq_hz,re_S11,im_S11,re_S21,im_S21"
        lines = [header] + [
            f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}" for row in data
        ]
        (run_dir / "sparams.csv").write_text("\n".join(lines), encoding="utf-8")

        result = s._parse_output()
        assert result.success
        assert result.s_params.shape == (2, 2, 2)
        np.testing.assert_allclose(np.abs(result.s_params[:, 1, 0]), 0.7)

    def test_parse_output_prefers_touchstone(self, tmp_path):
        """#208 主路：.s4p Touchstone（skrf 读取，N 端口全矩阵）优先于 CSV。"""
        import skrf

        s = _connected_solver(tmp_path)
        s.build_geometry({"template": "ratrace", "params": {}})
        run_dir = tmp_path / "openems_run"
        freq = skrf.Frequency(2.0, 3.0, 5, unit="Hz")
        freq.f[:] = np.array([2e9, 2.25e9, 2.5e9, 2.75e9, 3e9])
        rng = np.random.default_rng(42)
        smat = (rng.normal(size=(5, 4, 4)) + 1j * rng.normal(size=(5, 4, 4)))
        net = skrf.Network(frequency=freq, s=smat * 0.1, z0=50.0)
        net.write_touchstone(str(run_dir / "ratrace.s4p"))
        # 同目录故意放一个 CSV——验证 Touchstone 优先
        (run_dir / "sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21\n1e9,0,0,0,0\n",
            encoding="utf-8")

        result = s._parse_output()
        assert result.success
        assert "Touchstone" in result.message
        assert result.s_params.shape == (5, 4, 4)
        np.testing.assert_allclose(result.freq_ghz * 1e9,
                                   np.array([2e9, 2.25e9, 2.5e9, 2.75e9, 3e9]))

    def test_parse_output_reads_3port_csv(self, tmp_path):
        """双激励 9 列 CSV（S11/S21/S31/S23）→ 3x3 部分矩阵（V1-2）。"""
        s = _connected_solver(tmp_path)
        s.build_geometry({"template": "wilkinson", "params": {}})
        run_dir = tmp_path / "openems_run"
        freq = np.array([2e9, 3e9])
        header = ("freq_hz,re_S11,im_S11,re_S21,im_S21,"
                  "re_S31,im_S31,re_S23,im_S23")
        lines = [header]
        for f in freq:
            # S11=0.2, S21=0.7, S31=0.7, S23=0.05（隔离）
            lines.append(f"{f},0.2,0.0,0.7,0.0,0.7,0.0,0.05,0.0")
        (run_dir / "sparams.csv").write_text("\n".join(lines), encoding="utf-8")

        result = s._parse_output()
        assert result.success
        assert result.s_params.shape == (2, 3, 3)
        np.testing.assert_allclose(np.abs(result.s_params[:, 0, 0]), 0.2)
        np.testing.assert_allclose(np.abs(result.s_params[:, 1, 0]), 0.7)
        np.testing.assert_allclose(np.abs(result.s_params[:, 2, 0]), 0.7)
        np.testing.assert_allclose(np.abs(result.s_params[:, 1, 2]), 0.05)
        np.testing.assert_allclose(np.abs(result.s_params[:, 2, 1]), 0.05)


class TestSolverConfigLoading:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_solvers_config(tmp_path / "no_such.yaml") == {}

    def test_load_and_create(self, tmp_path):
        import yaml

        cfg = tmp_path / "solvers.yaml"
        cfg.write_text(yaml.safe_dump({
            "solvers": {
                "openems": {
                    "solver_type": "openems",
                    "exe_path": str(tmp_path / "o.exe"),
                    "working_dir": str(tmp_path / "w"),
                    "freq_range_ghz": [1.0, 3.0],
                    "mesh_resolution_mm": 0.4,
                },
            },
        }), encoding="utf-8")

        configs = load_solvers_config(cfg)
        assert "openems" in configs
        assert configs["openems"].freq_range_ghz == (1.0, 3.0)
        assert configs["openems"].mesh_resolution_mm == 0.4

        # 注册表里有 openEMS（模块导入即自动注册），能按配置名创建
        solver = create_solver_from_config("openems", path=cfg)
        assert isinstance(solver, OpenEMSSolver)
        assert solver.is_available() or not solver.is_available()  # 不抛错即可

    def test_create_unknown_entry_raises_keyerror(self, tmp_path):
        import yaml

        cfg = tmp_path / "solvers.yaml"
        cfg.write_text(yaml.safe_dump({"solvers": {}}), encoding="utf-8")
        with pytest.raises(KeyError):
            create_solver_from_config("nope", path=cfg)

    def test_global_registry_has_openems(self):
        assert get_global_registry().is_registered(EMSolverType.OPENEMS)


class TestSparamsCache:
    """solve() 结果磁盘缓存：同脚本重跑不重复仿真（零精度损失提速）。"""

    @staticmethod
    def _fake_csv(run_dir: Path) -> None:
        lines = [
            "freq_hz,re_S11,im_S11,re_S21,im_S21",
            "2e9,0.05,0.0,0.7,0.0",
            "3e9,0.1,0.0,0.6,0.0",
        ]
        (run_dir / "sparams.csv").write_text("\n".join(lines), encoding="utf-8")

    def test_second_solve_reuses_cache_without_subprocess(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            self._fake_csv(Path(kw["cwd"]))
            import subprocess as sp

            r = sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            return r

        monkeypatch.setattr("subprocess.run", fake_run)
        s = _connected_solver(tmp_path)
        # 缓存目录放进 tmp_path，避免污染工作区 runs/
        s._config.extra_params["cache_dir"] = str(tmp_path / "cache")

        s.build_geometry({"template": "wilkinson", "params": {"f0_ghz": 2.4}})
        r1 = s.solve()
        assert r1.success
        assert len(calls) == 1

        # 清掉运行目录产物，模拟"换目录重跑同一配置"
        for f in (tmp_path / "openems_run").rglob("*.csv"):
            f.unlink()
        r2 = s.solve()
        assert r2.success
        assert len(calls) == 1  # 未再启动子进程
        assert "缓存" in r2.message
        np.testing.assert_allclose(r2.freq_ghz, r1.freq_ghz)
        np.testing.assert_allclose(r2.s_params, r1.s_params)

    def test_cache_disabled_runs_every_time(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            self._fake_csv(Path(kw["cwd"]))
            import subprocess as sp

            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        s = _connected_solver(tmp_path)
        s._config.extra_params["cache"] = False
        s._config.extra_params["cache_dir"] = str(tmp_path / "cache")

        s.build_geometry({"template": "wilkinson", "params": {}})
        assert s.solve().success
        assert s.solve().success
        assert len(calls) == 2

    def test_different_params_get_different_cache_entries(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            self._fake_csv(Path(kw["cwd"]))
            import subprocess as sp

            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        s = _connected_solver(tmp_path)
        s._config.extra_params["cache_dir"] = str(tmp_path / "cache")

        s.build_geometry({"template": "wilkinson", "params": {"arm_len_mm": 18.1}})
        s.solve()
        s.build_geometry({"template": "wilkinson", "params": {"arm_len_mm": 20.0}})
        s.solve()
        assert len(calls) == 2  # 键不同，互不命中
