"""A3 PalaceSolver 官方 schema 对齐测试（v0.18.1 五分节配置 → mock 可执行 → CSV 解析）。

官方口径出处（2026-09-22 实测取证，见 runs/palace_spike/schema_fix_plan.md）：
- 配置顶层五分节 + 各键名：官方 scripts/schema/config-schema.json（tag v0.18.1）；
- CLI 位置参数（无 -config 旗标）：官方 docs/src/run.md；
- 结果文件 <Problem.Output>/port-S.csv（dB/deg 列、频率列 GHz）：
  官方 palace/models/postoperatorcsv.cpp L1180 起。

全部离线 mock，不真调 Palace（#139）。
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import numpy as np
import pytest

# 官方 v0.18.1 config-schema.json 顶层 required（测试内字面量，独立于适配器常量）
OFFICIAL_TOP_LEVEL = {"Problem", "Model", "Domains", "Boundaries", "Solver"}
# 官方 Driven S 参数结果相对路径（Problem.Output 官方缺省 postpro）
OFFICIAL_SPARAM_REL = "postpro/port-S.csv"

# 官方 port-S.csv 表头（v0.18.1 postoperatorcsv.cpp InitializePortS 列构造：
# idx, f (GHz)，逐激励 e × 逐端口 o 交替 |S[o][e]| (dB) / arg(S[o][e]) (deg.)；
# 本 stub 模拟端口 1 激励、端口 2 端接的单激励 run）
OFFICIAL_PORT_S_HEADER = (
    "idx,f (GHz),"
    "|S[1][1]| (dB),arg(S[1][1]) (deg.),"
    "|S[2][1]| (dB),arg(S[2][1]) (deg.)"
)

# 双激励全矩阵表头（取证实跑表头回填：官方单文件逐激励列块，块序
# e=1 全列 → e=2 全列；实测 Case A rc=0、行数=频点数、掩码全 4 对）
OFFICIAL_PORT_S_HEADER_2EXC = (
    "idx,f (GHz),"
    "|S[1][1]| (dB),arg(S[1][1]) (deg.),"
    "|S[2][1]| (dB),arg(S[2][1]) (deg.),"
    "|S[1][2]| (dB),arg(S[1][2]) (deg.),"
    "|S[2][2]| (dB),arg(S[2][2]) (deg.)"
)


def _official_materials() -> list[dict]:
    """官方 Domains.Materials 最小段（Attributes 绑定域标签，材质值不进断言）。"""
    return [{"Attributes": [1], "Permeability": 1.0, "Permittivity": 2.08}]


def _make_palace_stub(workdir, sparam_rows, header=OFFICIAL_PORT_S_HEADER):
    """生成 mock palace 可执行文件：运行后产出 <cwd>/postpro/port-S.csv。

    CLI 契约钉死（官方 docs/src/run.md：配置文件是位置参数）：
    - 无位置参数 → 退出码 2；
    - 出现 -config 旗标 → 退出码 3。
    """
    lines = [header]
    for i, row in enumerate(sparam_rows):
        lines.append(",".join([str(i)] + [str(v) for v in row]))
    ref = workdir / "palace_reference_port_s.csv"
    ref.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if sys.platform == "win32":
        exe = workdir / "palace.cmd"
        exe.write_text(
            "@echo off\r\n"
            'if "%~1"=="" exit /b 2\r\n'
            'set "STUB_ARGS=%*"\r\n'
            'if not "%STUB_ARGS%"=="%STUB_ARGS:-config=%" exit /b 3\r\n'
            "if not exist postpro mkdir postpro\r\n"
            'copy /y palace_reference_port_s.csv "postpro\\port-S.csv" >nul\r\n',
            encoding="ascii")
    else:
        exe = workdir / "palace.sh"
        exe.write_text(
            "#!/bin/sh\n"
            "[ $# -ge 1 ] || exit 2\n"
            'for a in "$@"; do\n'
            '  [ "$a" = "-config" ] && exit 3\n'
            "done\n"
            "mkdir -p postpro\n"
            "cp palace_reference_port_s.csv postpro/port-S.csv\n",
            encoding="ascii")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def _make_solver(tmp_path, workdir=None, **cfg_kw):
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.palace_solver import PalaceSolver

    dummy_exe = tmp_path / "palace-mock"
    if not dummy_exe.exists():
        dummy_exe.write_text("", encoding="ascii")
    cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                         exe_path=str(dummy_exe),
                         working_dir=str(workdir or tmp_path / "run"),
                         freq_range_ghz=(2.0, 3.0), **cfg_kw)
    solver = PalaceSolver(cfg)
    assert solver.connect()
    return solver


class TestPalaceConfigGeneration:
    """配置写出面逐字面钉官方 v0.18.1 schema。"""

    def test_build_geometry_writes_official_five_sections(self, tmp_path):

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        geometry = {"mesh_file": "board.msh", "mesh_l0_m": 1.0e-3,
                    "materials": _official_materials()}
        assert solver.build_geometry(geometry)
        text = (workdir / "palace_config.json").read_text(encoding="utf-8")
        data = json.loads(text)
        # 顶层键 = 官方五分节（不多不少；守卫本任务核心差距 A1）
        assert set(data.keys()) == OFFICIAL_TOP_LEVEL
        # 问题类型名官方为 "Driven"（"DrivenSParam" 已不存在，schema 枚举实测）
        assert data["Problem"]["Type"] == "Driven"
        assert "DrivenSParam" not in text
        # Model.Mesh / Model.L0（L0=网格坐标单位，米；mm 网格 1.0e-3）
        assert data["Model"]["Mesh"] == "board.msh"
        assert data["Model"]["L0"] == 1.0e-3
        # 材料在 Domains.Materials（非顶层 Materials），Attributes 原样透传
        assert data["Domains"]["Materials"] == _official_materials()
        # 扫频在 Solver.Driven.Samples（线性采样，官方单位 GHz，不 ×1e9）
        samples = data["Solver"]["Driven"]["Samples"]
        assert samples[0]["Type"] == "Linear"
        assert samples[0]["MinFreq"] == 2.0
        assert samples[0]["MaxFreq"] == 3.0
        # 官方已废弃键不得再出现（RelativePosterioriError/FrequencySamples 无此键）
        assert "FrequencySamples" not in text
        assert "RelativePosterioriError" not in text
        assert "MinimumFreq" not in text and "MaximumFreq" not in text

    def test_build_geometry_default_min_freq_ghz(self, tmp_path):
        """EMSolverConfig 频窗原值直写（GHz），官方口径不再做 Hz 换算。"""

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials()})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        sample = data["Solver"]["Driven"]["Samples"][0]
        assert sample["MinFreq"] == 2.0 and sample["MaxFreq"] == 3.0
        assert 2.0e9 not in (sample["MinFreq"], sample["MaxFreq"])

    def test_config_top_level_keys_official_only(self, tmp_path):
        """守卫：配置 JSON 顶层键 ∈ 官方五分节，出现顶层 Ports/Mesh 即红。"""

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials()})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        assert set(data.keys()) <= OFFICIAL_TOP_LEVEL
        assert "Ports" not in data  # 端口在 Boundaries 分节，顶层 Ports 官方不存在
        assert "Mesh" not in data and "Materials" not in data

    def test_build_geometry_requires_mesh(self, tmp_path):

        solver = _make_solver(tmp_path)
        assert not solver.build_geometry({})

    def test_build_geometry_requires_materials(self, tmp_path):
        """材料必填（官方 Domains.Materials），缺省不再造 er=3.66 默认段。"""

        solver = _make_solver(tmp_path)
        assert not solver.build_geometry({"mesh_file": "b.msh"})
        # 材料缺 Attributes 域标签绑定 → 拒绝（官方 Material.required=["Attributes"]）
        bad = [{"Index": 1, "Permittivity": 3.66}]  # 官方无 Index 键、无 Attributes
        assert not solver.build_geometry({"mesh_file": "b.msh", "materials": bad})

    def test_mesh_l0_missing_warns_and_omits(self, tmp_path, caplog):
        """mesh_l0_m 缺省：不臆测单位（不写 L0，官方默认 1e-6=μm）+ warning。"""

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        with caplog.at_level("WARNING", logger="rfauto.adapters.palace_solver"):
            assert solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials()})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        assert "L0" not in data["Model"]
        assert any("mesh_l0_m" in rec.message for rec in caplog.records)

    def test_ports_passthrough_into_boundaries(self, tmp_path):
        """端口组以官方 Boundaries 形态透传（WavePort/LumpedPort 分组）。

        激励形态按官方多激励契约：每端口 Excitation: <自身 Index>
        （两端口同 Excitation: true 会落同一激励组，官方 IsMultipleSimple()
        ==false → port-S.csv 必不产出，build 期守卫拒绝——df5_multiexcite_
        criteria.md §1-§2）。
        """

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        ports = {
            "WavePort": [{"Index": 1, "Attributes": [2], "Mode": 1,
                          "Excitation": 1}],
            "LumpedPort": [{"Index": 2, "Attributes": [3], "R": 50.0,
                            "Excitation": 2}],
        }
        boundaries = {"PEC": {"Attributes": [4]}}
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials(),
                                      "ports": ports, "boundaries": boundaries})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        assert data["Boundaries"]["WavePort"] == ports["WavePort"]
        assert data["Boundaries"]["LumpedPort"] == ports["LumpedPort"]
        assert data["Boundaries"]["PEC"] == boundaries["PEC"]
        assert "Ports" not in data

    def test_ports_rejects_non_official_keys(self, tmp_path):
        """ports 非官方形态（list 或未 Boundaries 子键）→ 显式拒绝。"""

        solver = _make_solver(tmp_path)
        legacy_list = [{"Type": "WavePort", "Index": 1}]
        assert not solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "ports": legacy_list})
        bad_key = {"CoaxialPort": [{"Index": 1}]}
        assert not solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "ports": bad_key})

    def test_boundaries_rejects_non_official_keys(self, tmp_path):

        solver = _make_solver(tmp_path)
        assert not solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "boundaries": {"NotOfficial": {}}})

    def test_nsample_from_max_iterations(self, tmp_path):
        """扫频点数映射官方 Samples[0].NSample（GHz 频窗）。"""

        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir, max_iterations=101)
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials()})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        assert data["Solver"]["Driven"]["Samples"][0]["NSample"] == 101

    def test_solve_without_config_fails_cleanly(self, tmp_path):

        solver = _make_solver(tmp_path)
        result = solver.solve()
        assert not result.success


class TestPalaceSolveMock:
    def test_solve_via_mock_exe(self, tmp_path):
        """端到端 mock：位置参数 CLI + <Output>/port-S.csv 解析（dB/度→线性复数）。"""
        from rfauto.adapters.palace_solver import PalaceSolver

        workdir = tmp_path / "run"
        workdir.mkdir()
        exe = _make_palace_stub(workdir, [
            # f(GHz), |S11|dB, arg(S11)deg, |S21|dB, arg(S21)deg
            (2.0, -20.0, 0.0, -20.0, 90.0),
            (2.5, -40.0, 180.0, -6.0206, -90.0),
            (3.0, -10.0, 45.0, -20.0, 90.0),
        ])
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path=str(exe), working_dir=str(workdir),
                             freq_range_ghz=(2.0, 3.0))
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({"mesh_file": "board.msh", "mesh_l0_m": 1.0e-3,
                                      "materials": _official_materials(),
                                      "ports": {"WavePort": [{"Index": 1, "Attributes": [2]}],
                                                "LumpedPort": [{"Index": 2, "Attributes": [3]}]}})
        result = solver.solve()
        assert result.success, result.message
        # 频率列官方已是 GHz：直读不换算（旧 /1e9 口径会得 2e-9）
        np.testing.assert_allclose(result.freq_ghz, [2.0, 2.5, 3.0])
        # dB/度 → 线性复数：0.1∠0°、0.01∠180°=-0.01
        assert abs(result.s_params[0, 0, 0] - (0.1 + 0j)) < 1e-12
        assert abs(result.s_params[1, 0, 0] - (-0.01 + 0j)) < 1e-12
        assert abs(result.s_params[2, 0, 0]) > 0.03  # -10dB → ~0.316
        # |S21|：o=2, e=1 → s[:,1,0]；0.1∠90°、~0.5∠-90°（-6.0206dB 有输入精度限）
        assert abs(result.s_params[0, 1, 0] - 0.1j) < 1e-12
        assert abs(result.s_params[1, 1, 0] - (-0.5j)) < 1e-6
        # 单激励 run：非激励列 (o=2,e=2) 无测量列 → 零填占位（#314 掩码诚实口径）
        assert result.s_params[0, 1, 1] == 0j
        # message 报告已测条目清单（1-based）
        assert "(1, 1)" in result.message and "(2, 1)" in result.message

    def test_cli_positional_config_contract(self, tmp_path):
        """stub 契约自证：无位置参数退出 2、含 -config 退出 3（官方 run.md 口径）。"""
        import subprocess

        workdir = tmp_path / "stubcheck"
        workdir.mkdir()
        exe = _make_palace_stub(workdir, [(2.0, 0.0, 0.0, 0.0, 0.0)])
        if sys.platform == "win32":
            r_none = subprocess.run([str(exe)], cwd=workdir, capture_output=True)
            r_flag = subprocess.run([str(exe), "-config", "x.json"], cwd=workdir,
                                    capture_output=True)
        else:
            r_none = subprocess.run([str(exe)], cwd=workdir, capture_output=True)
            r_flag = subprocess.run([str(exe), "-config", "x.json"], cwd=workdir,
                                    capture_output=True)
        assert r_none.returncode == 2
        assert r_flag.returncode == 3

    def test_get_sparams_reads_output_dir(self, tmp_path):

        workdir = tmp_path / "run"
        workdir.mkdir()
        _make_palace_stub(workdir, [(2.0, -20.0, 0.0, -20.0, 90.0)])
        solver = _make_solver(tmp_path, workdir)
        # solve 未跑：结果文件不存在 → None（不落旧工作目录根路径）
        assert solver.get_sparams() is None
        (workdir / "postpro").mkdir()
        (workdir / "postpro" / "port-S.csv").write_text(
            f"{OFFICIAL_PORT_S_HEADER}\n0,2.0,-20.0,0.0,-20.0,90.0\n",
            encoding="utf-8")
        freq_ghz, s = solver.get_sparams()
        assert abs(freq_ghz[0] - 2.0) < 1e-12
        assert abs(s[0, 0, 0] - (0.1 + 0j)) < 1e-12

    def test_visualizations_declared(self, tmp_path):

        solver = _make_solver(tmp_path)
        kinds = [v["kind"] for v in solver.visualizations()]
        assert "model3d" in kinds and "sparams" in kinds

    def test_visualizations_sparams_points_to_official_path(self, tmp_path):

        solver = _make_solver(tmp_path)
        spec = next(v for v in solver.visualizations() if v["kind"] == "sparams")
        assert spec["spec"]["file"].replace("\\", "/").endswith(OFFICIAL_SPARAM_REL)

    def test_registered_and_listed(self):
        import rfauto.adapters  # noqa: F401
        from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry
        from rfauto.service.r3_services import list_registered_solvers
        assert get_global_registry().is_registered(EMSolverType.PALACE)
        names = [s["type"] for s in list_registered_solvers()["solvers"]]
        assert "palace" in names


class TestPalaceExeDiscovery:
    def test_find_exe_official_binary_names(self, tmp_path, monkeypatch):
        """官方二进制名 palace-<ARCH>.bin 在候选清单即可被发现（第 3 级 which 链）。

        用 monkeypatch 钉 shutil.which（Windows PATHEXT 不认 .bin 后缀，
        PATH 实测不可跨平台确定性）；返回路径须真实存在（is_available 门）。
        隔离：env 与仓库 tools 目录探测钉空（本仓真装有 wrapper，不隔离则
        探测链在第 2 级命中、测试变成环境依赖）。
        """
        import shutil as _shutil

        from rfauto.adapters import palace_solver as ps
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

        official = tmp_path / "palace-arm64.bin"
        official.write_text("", encoding="ascii")
        seen: list[str] = []

        def fake_which(name):
            seen.append(name)
            if name == "palace-arm64.bin":
                return str(official)
            return None

        monkeypatch.setattr(_shutil, "which", fake_which)
        monkeypatch.setattr(ps, "_probe_tools_bin", lambda: None)
        monkeypatch.delenv("RFAUTO_PALACE_EXE", raising=False)
        from rfauto.adapters.palace_solver import PalaceSolver

        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE)
        solver = PalaceSolver(cfg)
        assert solver.is_available()
        assert solver.connect()
        assert solver._exe_path == str(official)
        # 候选查询覆盖官方两种架构二进制名（docs/src/run.md：<ARCH> =
        # x86_64/arm64；x86_64 未命中后落到 arm64）
        assert "palace-x86_64.bin" in seen
        assert "palace-arm64.bin" in seen


class TestPalaceExeResolveChain:
    """resolve_palace_exe 三级解析链（bridge_criteria.md §1：env 显式 →
    仓库 tools 安装目录 → PATH which；env 坏即显式不可用不落回）。"""

    @staticmethod
    def _no_probe(monkeypatch):
        """隔离本仓真装环境（tools/ 有 wrapper）：env 清空 + 第 2 级探测钉空。"""
        from rfauto.adapters import palace_solver as ps

        monkeypatch.setattr(ps, "_probe_tools_bin", lambda: None)
        monkeypatch.delenv("RFAUTO_PALACE_EXE", raising=False)
        return ps

    def test_env_valid_file_wins_over_all(self, tmp_path, monkeypatch):
        """env 指向真实文件 → 直接采用（第 1 级，指向 wrapper 或原生均可）。"""
        import shutil as _shutil

        ps = self._no_probe(monkeypatch)
        target = tmp_path / "palace.cmd"
        target.write_text("@echo off\r\n", encoding="ascii")
        monkeypatch.setenv("RFAUTO_PALACE_EXE", str(target))

        def _no_which(name):
            raise AssertionError("env 命中后不得再走 which")

        monkeypatch.setattr(_shutil, "which", _no_which)
        assert ps.resolve_palace_exe() == str(target)

    def test_env_missing_file_is_unavailable_no_fallback(self, tmp_path, monkeypatch):
        """env 指向不存在路径 → None（不静默落回 which），且给 warning。"""
        import shutil as _shutil

        ps = self._no_probe(monkeypatch)
        monkeypatch.setenv("RFAUTO_PALACE_EXE", str(tmp_path / "nope" / "palace.cmd"))

        def _no_which(name):
            raise AssertionError("env 显式坏了不得落回 which")

        monkeypatch.setattr(_shutil, "which", _no_which)
        assert ps.resolve_palace_exe() is None

    def test_env_missing_file_unavailable_even_if_path_has_palace(self, tmp_path,
                                                                  monkeypatch):
        """同上，但 which 链本来能命中——显式坏配置仍判不可用（诚实口径）。"""
        import shutil as _shutil

        ps = self._no_probe(monkeypatch)
        monkeypatch.setenv("RFAUTO_PALACE_EXE", str(tmp_path / "gone.cmd"))
        monkeypatch.setattr(_shutil, "which", lambda name: r"C:\bin\palace.exe")
        assert ps.resolve_palace_exe() is None

    def test_tools_bin_probe_second(self, monkeypatch):
        """env 缺席 → 仓库 tools 安装目录 wrapper 命中（第 2 级）。"""

        ps = self._no_probe(monkeypatch)

        probed = r"E:\x\tools\palace-install\bin\palace.cmd"
        monkeypatch.setattr(ps, "_probe_tools_bin", lambda: probed)
        assert ps.resolve_palace_exe() == probed

    def test_which_chain_last(self, monkeypatch):
        """env 与 tools 目录都缺席 → PATH which（第 3 级，现行行为不变）。"""
        import shutil as _shutil

        ps = self._no_probe(monkeypatch)
        monkeypatch.setattr(_shutil, "which",
                            lambda name: r"C:\bin\palace.exe"
                            if name == "palace.exe" else None)
        assert ps.resolve_palace_exe() == r"C:\bin\palace.exe"

    def test_environ_injection_pure(self, tmp_path, monkeypatch):
        """environ 参数注入（不碰 os.environ，供调用方/测试纯函数使用）。"""
        ps = self._no_probe(monkeypatch)
        target = tmp_path / "palace-x86_64.bin"
        target.write_text("", encoding="ascii")
        assert ps.resolve_palace_exe({"RFAUTO_PALACE_EXE": str(target)}) == str(target)
        assert ps.resolve_palace_exe({}) is None

    def test_probe_tools_bin_platform_names(self, monkeypatch, tmp_path):
        """tools 目录探测按平台选名：win32 只认 .cmd/.bat，bash 脚本 `palace`
        在 Windows 不可执行禁止命中；命中结果须 is_file。"""
        import os as _os

        from rfauto.adapters import palace_solver as ps

        monkeypatch.delenv("RFAUTO_PALACE_EXE", raising=False)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "palace").write_text("#!/bin/bash\n", encoding="ascii")
        (bindir / "palace.cmd").write_text("@echo off\r\n", encoding="ascii")
        monkeypatch.setattr(ps, "_tools_bin_dir", lambda: bindir)
        if _os.name == "nt":
            assert ps._probe_tools_bin() == str(bindir / "palace.cmd")
        else:
            assert ps._probe_tools_bin() == str(bindir / "palace")

    def test_tools_bin_missing_names_returns_none(self, monkeypatch, tmp_path):
        """目录在但无平台 wrapper → None（落回 which 链）。"""
        from rfauto.adapters import palace_solver as ps

        monkeypatch.delenv("RFAUTO_PALACE_EXE", raising=False)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "schema").mkdir()
        monkeypatch.setattr(ps, "_tools_bin_dir", lambda: bindir)
        assert ps._probe_tools_bin() is None


@pytest.mark.parametrize("flag", ["-config", "--config"])
def test_no_legacy_config_flag_in_cmd(tmp_path, monkeypatch, flag):
    """solve() 组装的命令行不含官方不存在的 -config/--config 旗标。"""
    captured: dict = {}

    class FakeProc:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # 结果文件由测试预置到官方路径
        out = Path(kwargs["cwd"]) / "postpro"
        out.mkdir(parents=True, exist_ok=True)
        (out / "port-S.csv").write_text(
            f"{OFFICIAL_PORT_S_HEADER}\n0,2.0,-20.0,0.0,-20.0,90.0\n",
            encoding="utf-8")
        return FakeProc()

    monkeypatch.setattr("rfauto.adapters.palace_solver.subprocess.run", fake_run)

    workdir = tmp_path / "run"
    solver = _make_solver(tmp_path, workdir)
    assert solver.build_geometry({"mesh_file": "b.msh",
                                  "materials": _official_materials()})
    result = solver.solve()
    assert result.success, result.message
    cmd = captured["cmd"]
    assert flag not in cmd
    # 配置文件是位置参数（跟在二进制后，且为绝对路径）
    assert len(cmd) == 2
    assert cmd[1].endswith("palace_config.json")


# ── 多激励 S 矩阵（消账 PENDING #3；判据 runs/palace_spike/
#    df5_multiexcite_criteria.md，源码+真跑双取证）────────────────────────────
class TestPalaceMultiExcitation:
    """官方单 run 多激励语义（每端口 Excitation: <自身 Index>）。

    语义出处（tag v0.18.1 实测）：
    - drivensolver.cpp L154 主循环激励外层×频率内层 → 单 run 官方支持；
    - postoperatorcsv.cpp InitializePortS：单文件逐激励列块，仅
      IsMultipleSimple()（每组恰 1 端口）才产出 port-S.csv；
    - configfile.cpp ParsePortExcitation L416：bool/非负整数→组索引。
    """

    def test_multi_excitation_full_matrix_solve(self, tmp_path):
        """双激励 stub（8 个 S 列）→ 全 (n,2,2) 矩阵回填 + 掩码全 4 对。"""
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        workdir = tmp_path / "run"
        workdir.mkdir()
        # 列序按官方块结构：e=1 块（S11,S21）→ e=2 块（S12,S22）
        exe = _make_palace_stub(workdir, [
            (2.0, -20.0, 0.0, -6.0206, 90.0, -6.0206, -90.0, -20.0, 180.0),
            (3.0, -40.0, 45.0, -3.0103, -90.0, -3.0103, 90.0, -40.0, -135.0),
        ], header=OFFICIAL_PORT_S_HEADER_2EXC)
        cfg = EMSolverConfig(solver_type=EMSolverType.PALACE,
                             exe_path=str(exe), working_dir=str(workdir),
                             freq_range_ghz=(2.0, 3.0))
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({
            "mesh_file": "b.msh", "materials": _official_materials(),
            "ports": {"LumpedPort": [
                {"Index": 1, "Attributes": [3], "R": 50.0, "Excitation": 1},
                {"Index": 2, "Attributes": [4], "R": 50.0, "Excitation": 2},
            ]}})
        result = solver.solve()
        assert result.success, result.message
        assert result.s_params.shape == (2, 2, 2)
        # 已测掩码全 4 对（结构化 get_measured_mask + message 双口径）
        assert solver.get_measured_mask() == [(1, 1), (1, 2), (2, 1), (2, 2)]
        assert "(1, 2)" in result.message and "(2, 2)" in result.message
        # e 轴映射钉死：S[o][e] → s[:, o-1, e-1]
        # e=1 块：|S21|=0.5∠90° → s[0,1,0]；e=2 块：|S12|=0.5∠-90° → s[0,0,1]
        assert abs(result.s_params[0, 1, 0] - 0.5j) < 1e-6
        assert abs(result.s_params[0, 0, 1] + 0.5j) < 1e-6
        assert abs(result.s_params[0, 0, 0] - 0.1) < 1e-12
        assert abs(result.s_params[0, 1, 1] - (-0.1)) < 1e-12
        # 全矩阵无零填占位
        assert np.all(result.s_params != 0)

    def test_multi_excitation_config_passthrough(self, tmp_path):
        """每端口 Excitation:<Index> 形态 build 通过并原样写入 Boundaries。"""
        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        ports = {"LumpedPort": [
            {"Index": 1, "Attributes": [3], "R": 50.0, "Direction": "+R",
             "Excitation": 1},
            {"Index": 2, "Attributes": [4], "R": 50.0, "Direction": "+R",
             "Excitation": 2},
        ]}
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials(),
                                      "ports": ports})
        data = json.loads((workdir / "palace_config.json").read_text(encoding="utf-8"))
        assert data["Boundaries"]["LumpedPort"] == ports["LumpedPort"]

    def test_shared_excitation_group_rejected(self, tmp_path):
        """多端口共享激励组 → build 期拒绝（官方 IsMultipleSimple()==false →
        port-S.csv 必不产出，官方 run rc=0 静默——Case B 真跑实证：
        两端口 Excitation:true，wall 2.3s、postpro 无 port-S.csv）。"""
        solver = _make_solver(tmp_path)
        both_true = {"LumpedPort": [
            {"Index": 1, "Attributes": [3], "R": 50.0, "Excitation": True},
            {"Index": 2, "Attributes": [4], "R": 50.0, "Excitation": True},
        ]}
        assert not solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "ports": both_true})
        explicit_shared = {"WavePort": [
            {"Index": 1, "Attributes": [2], "Mode": 1, "Excitation": 5},
            {"Index": 2, "Attributes": [3], "Mode": 1, "Excitation": 5},
        ]}
        assert not solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "ports": explicit_shared})

    def test_illegal_excitation_value_rejected(self, tmp_path):
        """Excitation 类型/取值非法 → build 期拒绝（官方 ParsePortExcitation
        会 MFEM_ABORT，提前到 build 期诚实报错）。"""
        solver = _make_solver(tmp_path)
        for bad in ("yes", -1, 1.5):
            ports = {"LumpedPort": [
                {"Index": 1, "Attributes": [3], "R": 50.0, "Excitation": bad},
            ]}
            assert not solver.build_geometry(
                {"mesh_file": "b.msh", "materials": _official_materials(),
                 "ports": ports}), f"Excitation={bad!r} 应拒绝"

    def test_excitation_index_mismatch_warns_not_rejects(self, tmp_path, caplog):
        """激励组索引≠端口 Index（官方归一化不适用）→ warning 不拒绝
        （合法官方语义，S 列按激励组索引排列）。"""
        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)
        ports = {"LumpedPort": [
            {"Index": 1, "Attributes": [3], "R": 50.0, "Excitation": 2},
            {"Index": 2, "Attributes": [4], "R": 50.0, "Excitation": 3},
        ]}
        with caplog.at_level("WARNING", logger="rfauto.adapters.palace_solver"):
            assert solver.build_geometry({"mesh_file": "b.msh",
                                          "materials": _official_materials(),
                                          "ports": ports})
        assert any("激励组索引" in rec.message for rec in caplog.records)

    def test_single_excitation_bool_form_still_accepted(self, tmp_path):
        """单激励 legacy 形态（单端口 Excitation: true）保持现行行为。"""
        solver = _make_solver(tmp_path)
        ports = {"LumpedPort": [
            {"Index": 1, "Attributes": [3], "R": 50.0, "Excitation": True},
            {"Index": 2, "Attributes": [4], "R": 50.0},
        ]}
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials(),
                                      "ports": ports})

    def test_get_measured_mask_none_before_solve(self, tmp_path):
        solver = _make_solver(tmp_path)
        assert solver.get_measured_mask() is None


# ── C-LOW 三项回归钉───────────────────────────────────────────────────
class TestPalaceCLowPins:
    def test_convergence_threshold_not_mapped_to_adaptivetol(self, tmp_path):
        """C-LOW ①：convergence_threshold 不映射 Solver.Driven.AdaptiveTol。

        判据 bridge_criteria §5（源码：config-schema.json AdaptiveTol=
        ROM 自适应快频扫容差、0=关闭；utils/configfile.cpp DrivenSolverData；
        models/romoperator.cpp；Restart≠1 与 adaptive 互斥 MFEM_VERIFY）——
        映射会把缺省 run 从逐点全阶求解静默翻转为 ROM 扫频。
        """
        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir, convergence_threshold=1e-6)
        assert solver.build_geometry({"mesh_file": "b.msh",
                                      "materials": _official_materials()})
        text = (workdir / "palace_config.json").read_text(encoding="utf-8")
        assert "AdaptiveTol" not in text
        assert "Adaptive" not in text
        data = json.loads(text)
        assert set(data["Solver"].keys()) == {"Driven"}
        assert set(data["Solver"]["Driven"].keys()) == {"Samples"}

    def test_adaptive_tol_exclusion_docstring_pin(self):
        """C-LOW ①：模块 docstring 保留源码出处引用（不映射的判据锚）。"""
        import rfauto.adapters.palace_solver as ps

        doc = ps.__doc__ or ""
        assert "AdaptiveTol" in doc
        assert "configfile.cpp" in doc
        assert "romoperator.cpp" in doc

    def test_visualizations_mesh_single_source_model_mesh(self, tmp_path):
        """C-LOW ②：mesh_file 以 Model.Mesh 单源——visualizations 只读
        build_geometry 存下的 geometry["mesh_file"]，extra_params 第二源
        删除（含"两源不一致时 visualizations 报哪个"的歧义面）。"""
        workdir = tmp_path / "run"
        solver = _make_solver(tmp_path, workdir)

        def model3d(viz_list):
            return next(x for x in viz_list if x["kind"] == "model3d")["spec"]

        # build 前：无 Model.Mesh 源 → 空串
        assert model3d(solver.visualizations())["mesh_file"] == ""
        # 第二源已删：extra_params 值不得再透出
        solver._config.extra_params["mesh_file"] = "from_extra_params.msh"
        assert model3d(solver.visualizations())["mesh_file"] == ""
        assert solver.build_geometry({"mesh_file": "board.msh",
                                      "mesh_l0_m": 1.0e-3,
                                      "materials": _official_materials()})
        assert model3d(solver.visualizations())["mesh_file"] == "board.msh"


# ── opt-in 集成测试（真跑 WSL 内 Palace，秒级；环境缺席即 skip）───────────────
def _bridge_wrapper() -> str | None:
    """集成测试环境探测（单独可调）：生产同款解析链（tools 目录 + which，
    不读用户 env——env 是用户会话态，真跑通道以仓库安装面为准）。"""
    from rfauto.adapters.palace_solver import resolve_palace_exe

    return resolve_palace_exe({})


_BRIDGE_EXE = _bridge_wrapper()
_BRIDGE_MESH_WSL = "/root/palace_ws/src/palace/examples/coaxial/mesh/coaxial.msh"


@pytest.mark.skipif(
    sys.platform != "win32" or _BRIDGE_EXE is None,
    reason=(f"Palace WSL wrapper/binary not installed (resolved={_BRIDGE_EXE!r}); "
            "install via scripts/palace_wsl_wrapper.py"),
)
@pytest.mark.skipif(
    os.environ.get("RFAUTO_PALACE_ITEST", "") != "1",
    reason=("真跑集成测试 opt-in：设 RFAUTO_PALACE_ITEST=1 启用（依赖宿主 "
            "PATH/WSL VM 状态，套件内 PATH 泄漏可致 "
            "wsl.exe 9009 假红；unit 门保持封闭 #139）。绿记录 2026-09-23 "
            "单跑 19.95s。"),
)
class TestPalaceWslBridgeIntegration:
    """Windows 侧 adapter → palace.cmd wrapper → WSL 二进制端到端真跑。

    **opt-in 双门**：`RFAUTO_PALACE_ITEST=1` 意图门（见 skipif 理由）+
    机器状态探测（wrapper 在位/win32/发行版与 mesh 运行时探测缺席 skip）。
    判据预声明 runs/palace_spike/bridge_criteria.md §4：dr_matched 案例
    （adapter build_geometry 产官方五分节 config，εr=2.08 同轴 + 50Ω
    LumpedPort×2 + PEC 壳，2–6GHz 21 点）。预声明物理带（loose）：
    形状 (21,2,2)、已测掩码 [(1,1),(2,1)]、频率轴 2–6GHz、4GHz 中点
    |S21| ∈ (−3dB, 0dB]。上一棒 mpirun -np 2 真跑参考 |S21|=−0.9685dB
    （sanity 对照，不作门）。test_end_to_end_multi_excitation 同几何双激励
    （Excitation: 1/2，官方单 run 多激励，判据 df5_multiexcite_criteria.md
    §2-§3）。其余单测面全 mock（#139）。
    """

    def _require_wsl_mesh(self) -> None:
        import subprocess

        probe = subprocess.run(
            ["wsl.exe", "-d", "rfauto-ubuntu", "--exec", "bash", "-c",
             f"test -f {_BRIDGE_MESH_WSL}"],
            capture_output=True, text=True, timeout=60, check=False)
        if probe.returncode != 0:
            pytest.skip("WSL rfauto-ubuntu 不可达或官方例 mesh 不在位")

    def test_end_to_end_dr_matched(self, tmp_path):
        import numpy as np

        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        self._require_wsl_mesh()
        workdir = tmp_path / "run"
        workdir.mkdir()
        cfg = EMSolverConfig(
            solver_type=EMSolverType.PALACE,
            exe_path=_BRIDGE_EXE,
            working_dir=str(workdir),
            freq_range_ghz=(2.0, 6.0),
            max_iterations=21,
        )
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({
            "mesh_file": _BRIDGE_MESH_WSL,
            "mesh_l0_m": 1.0e-3,
            "materials": [
                {"Attributes": [1], "Permeability": 1.0, "Permittivity": 2.08},
            ],
            "ports": {
                "LumpedPort": [
                    {"Index": 1, "Attributes": [3], "R": 50.0,
                     "Direction": "+R", "Excitation": True},
                    {"Index": 2, "Attributes": [4], "R": 50.0,
                     "Direction": "+R"},
                ]
            },
            "boundaries": {"PEC": {"Attributes": [2]}},
        })
        result = solver.solve(timeout_s=300)
        assert result.success, result.message
        # 形状与频率轴（官方 Samples 线性 21 点，频率列直读 GHz）
        assert result.s_params.shape == (21, 2, 2)
        assert result.freq_ghz[0] == pytest.approx(2.0)
        assert result.freq_ghz[-1] == pytest.approx(6.0)
        # 已测掩码（message 报告清单）+ 未测条目零填占位（#314 口径）
        assert "(1, 1)" in result.message and "(2, 1)" in result.message
        assert result.s_params[0, 1, 1] == 0j
        # 预声明物理带（bridge_criteria §4）：4GHz 中点 |S21| ∈ (−3dB, 0dB]
        im = int(np.argmin(np.abs(result.freq_ghz - 4.0)))
        s21_db = float(20 * np.log10(abs(result.s_params[im, 1, 0])))
        assert -3.0 < s21_db <= 0.0, f"|S21|@4GHz={s21_db:.4f}dB 越预声明带"
        # 参考（不设门）：matched 线 |S11|（上一棒真跑 −19.9dB 量级）
        s11_db = float(20 * np.log10(abs(result.s_params[im, 0, 0])))
        print(f"[bridge] wall={result.wall_time_s}s |S21|@4GHz={s21_db:.4f}dB "
              f"|S11|@4GHz={s11_db:.4f}dB (reference only)")

    def test_end_to_end_multi_excitation(self, tmp_path):
        """官方单 run 多激励（PENDING #3 消账）：两端口 Excitation: 1/2。

        判据预声明 runs/palace_spike/df5_multiexcite_criteria.md §2-§3：
        同 dr_matched 几何（εr=2.08 同轴 + 50Ω LumpedPort×2 + PEC 壳），
        port1/port2 各自激励；断言面=全 (n,2,2) 已测掩码（get_measured_mask
        结构化口径）+ 未测条目零 + 互易对 |S12−S21|（线性幅值）≤ 0.05
        （对称网格 FEM 离散，Case A 实测 0.0）+ |S21|@4GHz 物理带
        （同 §4，Case A 实测 −0.9685dB 与单激励逐位一致）。
        """
        import numpy as np

        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.palace_solver import PalaceSolver

        self._require_wsl_mesh()
        workdir = tmp_path / "run"
        workdir.mkdir()
        cfg = EMSolverConfig(
            solver_type=EMSolverType.PALACE,
            exe_path=_BRIDGE_EXE,
            working_dir=str(workdir),
            freq_range_ghz=(2.0, 6.0),
            max_iterations=11,
        )
        solver = PalaceSolver(cfg)
        assert solver.connect()
        assert solver.build_geometry({
            "mesh_file": _BRIDGE_MESH_WSL,
            "mesh_l0_m": 1.0e-3,
            "materials": [
                {"Attributes": [1], "Permeability": 1.0, "Permittivity": 2.08},
            ],
            "ports": {
                "LumpedPort": [
                    {"Index": 1, "Attributes": [3], "R": 50.0,
                     "Direction": "+R", "Excitation": 1},
                    {"Index": 2, "Attributes": [4], "R": 50.0,
                     "Direction": "+R", "Excitation": 2},
                ]
            },
            "boundaries": {"PEC": {"Attributes": [2]}},
        })
        result = solver.solve(timeout_s=600)
        assert result.success, result.message
        n = len(result.freq_ghz)
        assert result.s_params.shape == (n, 2, 2)
        assert result.freq_ghz[0] == pytest.approx(2.0)
        assert result.freq_ghz[-1] == pytest.approx(6.0)
        # 全矩阵已测掩码（#314 结构化口径）+ 无零填占位
        assert sorted(solver.get_measured_mask()) == [
            (1, 1), (1, 2), (2, 1), (2, 2)]
        assert np.all(result.s_params != 0)
        # 互易对（预声明带 ≤0.05 线性幅值；Case A 实测 0.0）
        recip = float(np.max(np.abs(result.s_params[:, 0, 1]
                                    - result.s_params[:, 1, 0])))
        assert recip <= 0.05, f"|S12-S21|max={recip:.4f} 越互易带"
        # 物理带：4GHz 中点 |S21| ∈ (−3dB, 0dB]
        im = int(np.argmin(np.abs(result.freq_ghz - 4.0)))
        s21_db = float(20 * np.log10(abs(result.s_params[im, 1, 0])))
        assert -3.0 < s21_db <= 0.0, f"|S21|@4GHz={s21_db:.4f}dB 越预声明带"
        print(f"[bridge-multiexcite] wall={result.wall_time_s}s n={n} "
              f"|S21|@4GHz={s21_db:.4f}dB |S12-S21|max={recip:.6f}")
