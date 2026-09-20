"""A1 MeepSolver 适配器测试（§10.1 A1）。

离线、确定性、无真机（Meep 本机不可装——CI-only，方案冻结口径）：
- 脚本渲染 + **stub-meep exec 几何审计**（#212 精神：字符串存在性抓不住
  画法错误——注入记录型 stub meep 模块后 exec 生成脚本并调 build_sim，
  实测几何块尺寸/端口面/网格/激励参数）；
- 求解链路（mock 解释器 exe 产出 CSV → 装配全 S 矩阵 + β）；
- β 三方对照确定性内核（Meep/openEMS/HJ 互差 ≤5%，A1 验收口径）；
- HJ 腿 vs openEMS 真锚 golden（runs/benchmark/mline_mauto 实测值冻结，
  两腿互差 ≤2%——#162 金标准口径，比三方 5% 更紧）。
"""

from __future__ import annotations

import math
import stat
import sys
import types

import pytest

# ── stub meep 模块（记录型：构造调用全部进 RECORD，供几何审计）────────────────

RECORD: list = []


class _StubVector3:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)
        RECORD.append(("Vector3", self))


class _StubMedium:
    def __init__(self, epsilon=1.0, **_kw):
        self.epsilon = epsilon
        self.kwargs = dict(_kw)   # 扩展关键字（D_conductivity 等）存档供审计
        RECORD.append(("Medium", self))


class _StubBlock:
    def __init__(self, center=None, size=None, material=None):
        self.center, self.size, self.material = center, size, material
        RECORD.append(("Block", self))


class _StubPML:
    def __init__(self, thickness=0.0):
        self.thickness = thickness
        RECORD.append(("PML", self))


class _StubGaussianSource:
    def __init__(self, frequency=None, fwidth=None):
        self.frequency, self.fwidth = frequency, fwidth
        RECORD.append(("GaussianSource", self))


class _StubEigenModeSource:
    def __init__(self, src=None, center=None, size=None, eig_band=None,
                 eig_match_freq=None, **_kw):
        self.src, self.center, self.size = src, center, size
        self.eig_band, self.eig_match_freq = eig_band, eig_match_freq
        RECORD.append(("EigenModeSource", self))


class _StubFluxRegion:
    def __init__(self, center=None, size=None, **_kw):
        self.center, self.size = center, size
        RECORD.append(("FluxRegion", self))


class _StubVolume:
    def __init__(self, center=None, size=None, **_kw):
        self.center, self.size = center, size
        RECORD.append(("Volume", self))


class _StubEigenmodeData:
    def __init__(self, k):
        self.k = k


class _StubSimulation:
    def __init__(self, resolution=None, cell_size=None, boundary_layers=None,
                 geometry=None, sources=None, default_material=None, **_kw):
        self.resolution = resolution
        self.cell_size = cell_size
        self.boundary_layers = boundary_layers
        self.geometry = geometry
        self.sources = sources
        self.default_material = default_material
        RECORD.append(("Simulation", self))

    def add_flux(self, *_a, **_kw):
        RECORD.append(("add_flux", self))
        return object()

    def run(self, **kw):
        RECORD.append(("run", self, kw))

    def get_eigenmode_coefficients(self, flux, bands, **_kw):
        class _Res:
            pass
        res = _Res()
        res.alpha = __import__("numpy").ones((len(bands), 2, 2), dtype=complex)
        return res

    def get_eigenmode(self, _f, _direction, _where, _band, _kpoint, **_kw):
        return _StubEigenmodeData(k=_StubVector3(0.0, 0.0, 0.0))


def _install_stub_meep(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """注入记录型 stub meep 模块（monkeypatch 自动还原 sys.modules）。"""
    RECORD.clear()
    mod = types.ModuleType("meep")
    mod.inf = float("inf")
    mod.Vector3 = _StubVector3
    mod.Medium = _StubMedium
    mod.Block = _StubBlock
    mod.PML = _StubPML
    mod.GaussianSource = _StubGaussianSource
    mod.EigenModeSource = _StubEigenModeSource
    mod.FluxRegion = _StubFluxRegion
    mod.Volume = _StubVolume
    mod.Simulation = _StubSimulation
    mod.metal = object()          # 哨兵：地/带材质
    mod.Y = 2                     # 方向枚举（stub 只比身份）
    mod.NO_PARITY = 0
    mod.AUTOMATIC = -1
    mod.stop_when_dft_decayed = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "meep", mod)
    return mod


def _exec_script(script: str) -> dict:
    """exec 生成的脚本（__name__ 非主模块 → 只定义函数不执行 main）。"""
    ns: dict = {"__name__": "meep_mline_audit"}
    exec(compile(script, "meep_mline_sim.py", "exec"), ns)
    return ns


_FREQS_HZ = [2.25e9, 2.5e9, 2.75e9]


def _render(**kw) -> str:
    from rfauto.adapters.meep_adapter import MEEP_LENGTH_UNIT_M, default_stackup, render_mline_script
    defaults = dict(resolution=2.0, length_unit_m=MEEP_LENGTH_UNIT_M)
    defaults.update(kw)
    return render_mline_script(1.113, 40.0, default_stackup(), list(_FREQS_HZ), **defaults)


# ── 单位换算内核 ──────────────────────────────────────────────────────────────

class TestUnits:
    def test_freq_hz_to_meep_hand_value(self):
        from rfauto.adapters.meep_adapter import freq_hz_to_meep
        # 2.5GHz @LU=1mm: f̃ = 2.5e9*1e-3/c0
        assert freq_hz_to_meep(2.5e9) == pytest.approx(2.5e9 * 1e-3 / 299792458.0)

    def test_beta_meep_to_si_hand_value(self):
        from rfauto.adapters.meep_adapter import beta_meep_to_si
        assert beta_meep_to_si(1.0) == pytest.approx(2 * math.pi / 1e-3)
        # k 不含 2π（官方相位惯例）→ β=2π|k|/LU
        assert beta_meep_to_si(-0.0140799) == pytest.approx(2 * math.pi * 0.0140799 / 1e-3)

    def test_invalid_length_unit_rejected(self):
        from rfauto.adapters.meep_adapter import beta_meep_to_si, freq_hz_to_meep
        with pytest.raises(ValueError):
            freq_hz_to_meep(1e9, length_unit_m=0.0)
        with pytest.raises(ValueError):
            beta_meep_to_si(1.0, length_unit_m=-1.0)


# ── 介质损耗换算内核（官方 Materials 口径，A1 子项④）─────────────────────────

class TestTandToDConductivity:
    def test_official_worked_example_hand_value(self):
        """官方 worked 例：ε = 3.4+0.101i @ f̃=0.42 → σ_D = 2π·0.42·(0.101/3.4)。"""
        from rfauto.adapters.meep_adapter import (
            MEEP_LENGTH_UNIT_M,
            tand_to_d_conductivity,
        )
        f_tilde = 0.42
        f_hz = f_tilde * 299792458.0 / MEEP_LENGTH_UNIT_M
        sigd = tand_to_d_conductivity(f_hz, 0.101 / 3.4)
        assert sigd == pytest.approx(2 * math.pi * 0.42 * 0.101 / 3.4, rel=1e-12)

    def test_dual_path_si_form_same_value(self):
        """SI 式 σ_D=(LU/c0)·σ_SI/(εr·ε0)（σ_SI=2πf·ε0·εr·tanδ）与直算式同值。"""
        from rfauto.adapters.meep_adapter import (
            MEEP_LENGTH_UNIT_M,
            tand_to_d_conductivity,
        )
        f_hz, tand, er = 2.5e9, 0.0037, 3.66
        direct = tand_to_d_conductivity(f_hz, tand)
        eps0 = 8.8541878128e-12
        sigma_si = 2 * math.pi * f_hz * eps0 * er * tand
        via_si = MEEP_LENGTH_UNIT_M / 299792458.0 * sigma_si / (er * eps0)
        assert direct == pytest.approx(via_si, rel=1e-12)

    def test_tand_round_trip_recovery(self):
        """往返恢复闭式：tanδ = σ_D/(2π·f̃)（f̃=f·LU/c0，freq_hz_to_meep 同源）。"""
        from rfauto.adapters.meep_adapter import (
            freq_hz_to_meep,
            tand_to_d_conductivity,
        )
        for f_hz, tand in ((2.5e9, 0.0037), (2.6e9, 0.022), (10e9, 0.001)):
            sigd = tand_to_d_conductivity(f_hz, tand)
            assert sigd / (2 * math.pi * freq_hz_to_meep(f_hz)) == pytest.approx(
                tand, rel=1e-12)

    def test_invalid_inputs_rejected(self):
        from rfauto.adapters.meep_adapter import tand_to_d_conductivity
        with pytest.raises(ValueError):
            tand_to_d_conductivity(0.0, 0.01)          # 钉频非正
        with pytest.raises(ValueError):
            tand_to_d_conductivity(2.5e9, 0.0)         # tanδ=0（无损不走内核）
        with pytest.raises(ValueError):
            tand_to_d_conductivity(2.5e9, -0.01)       # tanδ 非物理
        with pytest.raises(ValueError):
            tand_to_d_conductivity(2.5e9, 0.01, length_unit_m=0.0)


# ── 脚本渲染 ──────────────────────────────────────────────────────────────────

class TestRenderMlineScript:
    def test_render_contains_constants_and_entry(self):
        script = _render()
        assert "W = 1.113" in script
        assert "H = 0.508" in script
        assert "L = 40.0" in script
        assert "ER = 3.66" in script
        assert "__main__" in script
        assert "--excite-port" in script
        # 频点网格 SI 值原样进脚本（与 openEMS 网格显式对齐的抓手；repr(2.25e9) 口径）
        assert "2250000000.0" in script
        # 产物 CSV 契约（与 openEMS #162 金标准同 schema）
        assert "meep_sparams_p" in script
        assert "meep_port_beta_p" in script

    def test_render_rejects_bad_inputs(self):
        from rfauto.adapters.meep_adapter import default_stackup, render_mline_script
        st = default_stackup()
        with pytest.raises(ValueError):
            render_mline_script(1.113, 40.0, st, [2.5e9], resolution=2.0)  # 单频点
        with pytest.raises(ValueError):
            render_mline_script(1.113, 40.0, st, _FREQS_HZ, resolution=0.0)
        with pytest.raises(ValueError):
            render_mline_script(1.113, 40.0, st, [2.5e9, -1e9], resolution=2.0)

    def test_no_unreplaced_tokens(self):
        script = _render()
        for tok in ("@LU_M@", "@W_MM@", "@H_MM@", "@L_MM@", "@ER@", "@TAND@",
                    "@SIGD@", "@SUB_EXPR@", "@RES@", "@DPML_MM@", "@SRC_GAP_MM@",
                    "@MARGIN_X_MM@", "@AIR_TOP_MM@", "@FREQS_HZ@"):
            assert tok not in script   # 占位符必须全部替换干净


# ── stub-meep 几何审计（#212 精神：exec 实测画法，不是字符串断言）──────────────

class TestStubMeepGeometryAudit:
    def test_geometry_blocks_mirror_openems_mline(self, monkeypatch):
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())
        sim, _mon = ns["build_sim"](1)
        blocks = [r[1] for r in RECORD if r[0] == "Block"]
        assert len(blocks) == 3
        assert sim.resolution == pytest.approx(2.0)
        metal = sys.modules["meep"].metal
        # 地：z∈[-DPML-T,0] PEC 板（延展进底 PML），x/y 全域
        ground = blocks[0]
        assert ground.material is metal
        assert ground.size.x == float("inf") and ground.size.y == float("inf")
        assert ground.center.z == pytest.approx(-(2.0 + 0.5) / 2)
        assert ground.size.z == pytest.approx(2.0 + 0.5)
        # 基板：z∈[0,H] er=3.66（guided 口径 x/y 延展到域边）
        substrate = blocks[1]
        assert substrate.material.epsilon == pytest.approx(3.66)
        assert substrate.center.z == pytest.approx(0.508 / 2)
        assert substrate.size.z == pytest.approx(0.508)
        # 信号带：x∈[-W/2,W/2] 顶面 z∈[H,H+T]，y 贯穿
        strip = blocks[2]
        assert strip.material is metal
        assert strip.size.x == pytest.approx(1.113)
        assert strip.center.z == pytest.approx(0.508 + 0.5 / 2)
        assert strip.size.z == pytest.approx(0.5)          # T_METAL = 1/RES
        assert strip.size.y == float("inf")

    def test_grid_pml_and_freq_identity(self, monkeypatch):
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())
        sim, _mon = ns["build_sim"](1)
        # PML 2.0 / cell y 含线长+两侧 SRC_GAP+两侧 PML
        pmls = [r[1] for r in RECORD if r[0] == "PML"]
        assert len(pmls) == 1 and pmls[0].thickness == pytest.approx(2.0)
        assert sim.cell_size.y == pytest.approx(40.0 + 2 * 2.0 + 2 * 2.0)
        # 空气边距默认 max(3W,3H)=3.339：cell x / z
        assert sim.cell_size.x == pytest.approx(1.113 + 2 * 3.339 + 2 * 2.0)
        assert sim.cell_size.z == pytest.approx(2 * 2.0 + 0.508 + 3.339)
        # DFT 频网格恒等式：FCEN/DF 由 FREQS_MEEP 首尾导出 → add_flux
        # (fcen, df, nfreq) 网格 == FREQS_MEEP（S 参数与 β 同网格的前提）
        assert ns["NFREQ"] == 3
        assert ns["FCEN"] == pytest.approx((ns["FREQS_MEEP"][0] + ns["FREQS_MEEP"][-1]) / 2)
        assert ns["DF"] == pytest.approx(ns["FREQS_MEEP"][-1] - ns["FREQS_MEEP"][0])
        assert ns["FREQS_MEEP"][1] == pytest.approx(2.5e9 * 1e-3 / 299792458.0)

    def test_port_planes_and_excitation_routing(self, monkeypatch):
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())
        _sim1, _mon1 = ns["build_sim"](1)
        srcs1 = [r[1] for r in RECORD if r[0] == "EigenModeSource"]
        assert len(srcs1) == 1
        assert srcs1[0].center.y == pytest.approx(-22.0)   # YP1 = -L/2 - SRC_GAP
        assert srcs1[0].eig_band == 1
        assert srcs1[0].eig_match_freq is True
        assert srcs1[0].size.y == 0                         # y 法向平面
        assert srcs1[0].size.x == pytest.approx(1.113 + 2 * 3.339)
        fluxes = [r for r in RECORD if r[0] == "FluxRegion"]
        assert len(fluxes) == 2                             # 双端口监视面齐备
        ys = sorted(f[1].center.y for f in fluxes)
        assert ys == pytest.approx([-22.0, 22.0])
        assert all(f[1].size.y == 0 for f in fluxes)
        RECORD.clear()
        _sim2, _mon2 = ns["build_sim"](2)
        srcs2 = [r[1] for r in RECORD if r[0] == "EigenModeSource"]
        assert srcs2[0].center.y == pytest.approx(22.0)    # 激励随端口路由


# ── 有耗介质路径（A1 子项④：常值 D_conductivity 钉频带中心）─────────────────

class TestLossyMediumPath:
    def test_lossy_default_stackup_wires_d_conductivity(self, monkeypatch):
        """默认锚 stackup（tanδ=0.0037>0）→ SUB 走 D_conductivity=内核值。"""
        from rfauto.adapters.meep_adapter import tand_to_d_conductivity
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())
        f_pin_hz = 0.5 * (_FREQS_HZ[0] + _FREQS_HZ[-1])   # 频带中心 = FCEN 同点
        expected = tand_to_d_conductivity(f_pin_hz, 0.0037)
        assert ns["SIGD"] == pytest.approx(expected)
        assert ns["TAND"] == pytest.approx(0.0037)
        _sim, _mon = ns["build_sim"](1)                    # 几何构造进 RECORD
        blocks = [r[1] for r in RECORD if r[0] == "Block"]
        sub_mat = blocks[1].material                       # 基板 Medium
        assert sub_mat.kwargs.get("D_conductivity") == pytest.approx(expected)
        # 空气 default_material 不带损耗关键字（无损背景）
        sims = [r[1] for r in RECORD if r[0] == "Simulation"]
        assert sims[0].default_material.kwargs.get("D_conductivity") is None

    def test_effective_tand_is_1_over_f_at_band_edges(self, monkeypatch):
        """常 σ_D 钉带中心 ⇒ 有效 tanδ(f)=tanδ_pin·f_pin/f：带边比=首末频比。"""
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())
        f_pin_hz = 0.5 * (_FREQS_HZ[0] + _FREQS_HZ[-1])
        for f_hz in _FREQS_HZ:
            eff = ns["SIGD"] / (2 * math.pi * ns["FREQS_MEEP"][_FREQS_HZ.index(f_hz)])
            assert eff == pytest.approx(0.0037 * f_pin_hz / f_hz, rel=1e-12)

    def test_lossless_stackup_omits_keyword(self, monkeypatch):
        """tanδ≤0 → SUB 构造不带 D_conductivity 关键字（lossless 路径保持）。"""
        from rfauto.adapters.meep_adapter import default_stackup, render_mline_script
        from rfauto.core.synthesis import Stackup
        for tand in (0.0, -0.01):
            st = Stackup(name="lossless", epsilon_r=3.66, thickness_mm=0.508,
                         loss_tangent=tand)
            script = render_mline_script(1.113, 40.0, st, list(_FREQS_HZ),
                                         resolution=2.0)
            assert "SUB = mp.Medium(epsilon=ER)\n" in script
            assert "mp.Medium(epsilon=ER, D_conductivity=SIGD)" not in script
            _install_stub_meep(monkeypatch)
            ns = _exec_script(script)
            _sim, _mon = ns["build_sim"](1)
            blocks = [r[1] for r in RECORD if r[0] == "Block"]
            assert blocks[1].material.kwargs == {}
            assert ns["SIGD"] == 0.0
        assert default_stackup().loss_tangent > 0   # 锚默认即 lossy（与 openEMS 金锚同基准）

    def test_beta_formula_consistent_with_hj(self, monkeypatch):
        """脚本 _beta_at 的 2π·|k|/LU 公式 vs HJ 闭式：喂 εeff·f̃ 的 k 应还原 β_HJ。"""
        _install_stub_meep(monkeypatch)
        ns = _exec_script(_render())

        class _Mode:
            pass
        mode = _Mode()
        # k = n_eff·f̃（meep k 不含 2π）；εeff=2.8526 为 HJ@2.5GHz 实测口径
        mode.k = _StubVector3(0.0, math.sqrt(2.8526) * ns["FREQS_MEEP"][1], 0.0)
        sim, mon = ns["build_sim"](1)

        def _fake_get_eigenmode(*_a, **_kw):
            return mode
        sim.get_eigenmode = _fake_get_eigenmode
        beta = ns["_beta_at"](sim, mon["plane1"], float(ns["FREQS_MEEP"][1]))
        # β_HJ(2.5GHz, w=1.113, rogers4350b) = 88.496 rad/m（forward_z0 实测）
        assert beta == pytest.approx(88.496, rel=1e-3)


# ── CSV 解析与求解链路（mock 解释器 exe）──────────────────────────────────────

def _csv_body(rows: list[tuple]) -> str:
    return "freq_hz,re_sxx,im_sxx,re_syx,im_syx\n" + "".join(
        f"{f},{a.real},{a.imag},{b.real},{b.imag}\n" for f, a, b in rows)


def _beta_body(rows: list[tuple[float, float]]) -> str:
    return "freq_hz,beta_rad_per_m\n" + "".join(f"{f},{b}\n" for f, b in rows)


def _port1_rows():
    return [(2.25e9, 0.1 + 0.02j, 0.95 - 0.05j),
            (2.5e9, 0.08 + 0.01j, 0.96 - 0.04j),
            (2.75e9, 0.12 - 0.03j, 0.93 + 0.02j)]


def _port2_rows():
    return [(2.25e9, 0.11 + 0.01j, 0.94 - 0.06j),
            (2.5e9, 0.09 + 0.02j, 0.95 - 0.03j),
            (2.75e9, 0.10 + 0.04j, 0.92 + 0.01j)]


def _make_mock_python(workdir, mode: str = "ok"):
    """mock meep 解释器：执行后产出双激励 CSV（ok）/退出码非零（fail）/零产出（empty）。"""
    for name, body in (
        ("tpl_sparams_p1.csv", _csv_body(_port1_rows())),
        ("tpl_sparams_p2.csv", _csv_body(_port2_rows())),
        ("tpl_beta_p1.csv", _beta_body([(2.25e9, 80.55), (2.5e9, 89.51), (2.75e9, 98.46)])),
        ("tpl_beta_p2.csv", _beta_body([(2.25e9, 80.61), (2.5e9, 89.44), (2.75e9, 98.52)])),
    ):
        (workdir / name).write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        exe = workdir / "meep-python.cmd"
        if mode == "ok":
            exe.write_text(
                "@echo off\r\n"
                "copy /y tpl_sparams_p1.csv meep_sparams_p1.csv >nul\r\n"
                "copy /y tpl_sparams_p2.csv meep_sparams_p2.csv >nul\r\n"
                "copy /y tpl_beta_p1.csv meep_port_beta_p1.csv >nul\r\n"
                "copy /y tpl_beta_p2.csv meep_port_beta_p2.csv >nul\r\n",
                encoding="ascii")
        elif mode == "fail":
            exe.write_text("@echo off\r\nexit /b 3\r\n", encoding="ascii")
        else:
            exe.write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
    else:
        exe = workdir / "meep-python.sh"
        body = ("#!/bin/sh\n"
                "cp tpl_sparams_p1.csv meep_sparams_p1.csv\n"
                "cp tpl_sparams_p2.csv meep_sparams_p2.csv\n"
                "cp tpl_beta_p1.csv meep_port_beta_p1.csv\n"
                "cp tpl_beta_p2.csv meep_port_beta_p2.csv\n")
        if mode == "fail":
            body = "#!/bin/sh\nexit 3\n"
        elif mode == "empty":
            body = "#!/bin/sh\nexit 0\n"
        exe.write_text(body, encoding="ascii")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def _make_solver(tmp_path, mode: str = "ok"):
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.meep_adapter import MeepSolver
    workdir = tmp_path / "run"
    workdir.mkdir()
    exe = _make_mock_python(workdir, mode)
    cfg = EMSolverConfig(solver_type=EMSolverType.MEEP, exe_path=str(exe),
                         working_dir=str(workdir), freq_range_ghz=(2.25, 2.75))
    solver = MeepSolver(cfg)
    return solver, workdir


class TestParsePortCsv:
    def test_parse_sparams_with_beta_sidecar(self, tmp_path):
        from rfauto.adapters.meep_adapter import MeepSolver
        p = tmp_path / "meep_sparams_p1.csv"
        p.write_text(_csv_body(_port1_rows()), encoding="utf-8")
        (tmp_path / "meep_port_beta_p1.csv").write_text(
            _beta_body([(2.25e9, 80.5), (2.5e9, 89.2), (2.75e9, 98.4)]), encoding="utf-8")
        freq, s, beta = MeepSolver._parse_port_csv(p)
        assert freq.tolist() == [2.25e9, 2.5e9, 2.75e9]
        assert s[0, 0] == pytest.approx(0.1 + 0.02j)
        assert s[2, 1] == pytest.approx(0.93 + 0.02j)
        assert beta.tolist() == pytest.approx([80.5, 89.2, 98.4])

    def test_missing_beta_sidecar_falls_back_to_nan(self, tmp_path):
        from rfauto.adapters.meep_adapter import MeepSolver
        p = tmp_path / "meep_sparams_p1.csv"
        p.write_text(_csv_body(_port1_rows()[:1]), encoding="utf-8")
        freq, _s, beta = MeepSolver._parse_port_csv(p)
        assert len(freq) == 1
        assert math.isnan(beta[0])

    def test_empty_and_bad_header_raise(self, tmp_path):
        from rfauto.adapters.meep_adapter import MeepSolver
        p = tmp_path / "x.csv"
        p.write_text("freq_hz,re_sxx\n", encoding="utf-8")
        with pytest.raises(ValueError):
            MeepSolver._parse_port_csv(p)
        p.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with pytest.raises(ValueError):
            MeepSolver._parse_port_csv(p)


class TestSolveMock:
    def test_solve_assembles_full_s_matrix_and_beta(self, tmp_path):
        solver, _wd = _make_solver(tmp_path)
        assert solver.connect()
        assert solver.build_geometry({})
        result = solver.solve()
        assert result.success, result.message
        assert result.freq_ghz.tolist() == pytest.approx([2.25, 2.5, 2.75])
        s = result.s_params
        assert s.shape == (3, 2, 2)
        assert s[0, 0, 0] == pytest.approx(0.1 + 0.02j)    # S11 ← p1
        assert s[0, 1, 0] == pytest.approx(0.95 - 0.05j)   # S21 ← p1
        assert s[0, 1, 1] == pytest.approx(0.11 + 0.01j)   # S22 ← p2
        assert s[0, 0, 1] == pytest.approx(0.94 - 0.06j)   # S12 ← p2
        fd = result.field_data
        assert fd["beta_rad_per_m"].tolist() == pytest.approx([80.55, 89.51, 98.46])
        assert fd["beta_p2_rad_per_m"].tolist() == pytest.approx([80.61, 89.44, 98.52])
        # get_sparams / get_beta 重读工作目录
        freq_g, s2 = solver.get_sparams()
        assert freq_g.tolist() == pytest.approx([2.25, 2.5, 2.75])
        assert s2[1, 0, 0] == pytest.approx(0.08 + 0.01j)
        bf, bb = solver.get_beta()
        assert bf.tolist() == pytest.approx([2.25, 2.5, 2.75])
        assert bb.tolist() == pytest.approx([80.55, 89.51, 98.46])

    def test_solve_without_connection_or_script_fails_cleanly(self, tmp_path):
        solver, _wd = _make_solver(tmp_path)
        assert not solver.solve().success            # 未连接
        assert solver.connect()
        assert not solver.solve().success            # 未 build_geometry
        assert solver.solve().success is False

    def test_nonzero_exit_fails_with_stderr(self, tmp_path):
        solver, _wd = _make_solver(tmp_path, mode="fail")
        assert solver.connect()
        assert solver.build_geometry({})
        result = solver.solve()
        assert not result.success
        assert "退出码" in result.message

    def test_zero_exit_without_csv_fails_cleanly(self, tmp_path):
        solver, _wd = _make_solver(tmp_path, mode="empty")
        assert solver.connect()
        assert solver.build_geometry({})
        result = solver.solve()
        assert not result.success
        assert "未产出" in result.message

    def test_all_nan_beta_still_succeeds_with_warning(self, tmp_path):
        solver, workdir = _make_solver(tmp_path)
        # β 伴生文件替换为全 NaN（版本兼容层降级路径）——S 主路不阻塞
        for n in (1, 2):
            (workdir / f"tpl_beta_p{n}.csv").write_text(
                _beta_body([(2.25e9, float("nan")), (2.5e9, float("nan")),
                            (2.75e9, float("nan"))]), encoding="utf-8")
        assert solver.connect()
        assert solver.build_geometry({})
        result = solver.solve()
        assert result.success, result.message
        assert "NaN" in result.message
        assert math.isnan(result.field_data["beta_rad_per_m"][0])


# ── β 三方对照确定性内核（A1 验收：互差 ≤5%）──────────────────────────────────

class TestBetaTriadKernel:
    def test_sym_rel_diff_hand_number(self):
        from rfauto.adapters.meep_adapter import _sym_rel_diff
        assert _sym_rel_diff(100.0, 102.0) == pytest.approx(2.0 / 101.0)
        assert _sym_rel_diff(5.0, 5.0) == 0.0
        assert _sym_rel_diff(0.0, 0.0) == 0.0

    def test_consistent_triad_passes(self):
        from rfauto.adapters.meep_adapter import compare_beta_three_way
        freq = [2.25, 2.5, 2.75]
        rep = compare_beta_three_way(freq, [79.7, 88.5, 97.3], [80.6, 89.5, 98.5],
                                     [80.1, 88.9, 97.9])
        assert rep.passed is True
        assert rep.max_pairwise_rel < 0.05
        assert set(rep.per_pair_max_rel) == {"hj-openems", "hj-meep", "openems-meep"}
        assert rep.n_freq == 3

    def test_outlier_leg_fails_with_culprit_pair(self):
        from rfauto.adapters.meep_adapter import compare_beta_three_way
        freq = [2.5]
        rep = compare_beta_three_way(freq, [88.5], [89.5], [96.5])   # meep +8%
        assert rep.passed is False
        assert rep.max_pairwise_rel > 0.05
        assert rep.culprit_pair == "hj-meep"
        assert rep.worst_freq_ghz == 2.5

    def test_grid_and_value_validation(self):
        from rfauto.adapters.meep_adapter import compare_beta_three_way
        with pytest.raises(ValueError):
            compare_beta_three_way([2.5], [88.5], [89.5], [88.0, 90.0])  # 长度不齐
        with pytest.raises(ValueError):
            compare_beta_three_way([], [], [], [])                        # 空网格
        with pytest.raises(ValueError, match="NaN"):
            compare_beta_three_way([2.5], [float("nan")], [89.5], [88.0])
        with pytest.raises(ValueError, match="正"):
            compare_beta_three_way([2.5], [-88.5], [89.5], [88.0])

    def test_to_dict_roundtrip(self):
        from rfauto.adapters.meep_adapter import compare_beta_three_way
        rep = compare_beta_three_way([2.5], [88.5], [89.5], [88.9])
        d = rep.to_dict()
        assert d["passed"] == rep.passed
        assert d["culprit_pair"] == rep.culprit_pair
        assert d["tol_rel"] == pytest.approx(0.05)


# ── HJ 腿 + 真锚 golden（openEMS mline_mauto 实测，两腿 ≤2%）─────────────────

# golden 源：runs/benchmark/mline_mauto/port_beta.csv（W=1.113mm 锚、auto 网格、
# 2.25-2.75GHz；#162 β 金标准）。冻结为常量：测试不依赖 runs/（工作区态）。
_OPENEMS_GOLDEN = {2.25: 80.55376868947421, 2.5: 89.50940246779182,
                   2.75: 98.45637105318495}


class TestHjLegAndGolden:
    def test_hj_series_matches_forward_z0(self):
        from rfauto.adapters.meep_adapter import default_stackup as _ds
        from rfauto.adapters.meep_adapter import hj_beta_series
        from rfauto.core.synthesis import forward_z0
        st = _ds()
        betas = hj_beta_series(1.113, [2.25, 2.5, 2.75])
        for f, b in zip((2.25, 2.5, 2.75), betas, strict=True):
            _z0, eeff = forward_z0(1.113, f, st)
            assert b == pytest.approx(2 * math.pi * f * 1e9 * math.sqrt(eeff) / 299792458.0)
            assert 1.0 < eeff < st.epsilon_r        # 物理界：微带 εeff∈(1, εr)

    def test_hj_vs_openems_golden_within_2pct(self):
        """两腿真锚互差 ≤2%（#162 金标准口径；比三方 5% 验收更紧）。

        2026-09-14 实测互差：1.12% / 1.14% / 1.14%。
        skrf 版本由 uv.lock 钉扎；漂移超限 = HJ/引擎口径变化信号。
        """
        from rfauto.adapters.meep_adapter import hj_beta_series
        betas = hj_beta_series(1.113, list(_OPENEMS_GOLDEN))
        for (f, gold), b in zip(_OPENEMS_GOLDEN.items(), betas, strict=True):
            assert abs(b - gold) / gold < 0.02, (f, b, gold)

    def test_triad_end_to_end_with_golden_legs(self):
        """端到端三方：HJ + openEMS 真腿，Meep 腿合成 ±1%/+8% 两种命运。"""
        from rfauto.adapters.meep_adapter import compare_beta_three_way, hj_beta_series
        freqs = list(_OPENEMS_GOLDEN)
        hj = hj_beta_series(1.113, freqs).tolist()
        ems = list(_OPENEMS_GOLDEN.values())
        ok = compare_beta_three_way(freqs, hj, ems, [b * 1.01 for b in hj])
        assert ok.passed is True
        bad = compare_beta_three_way(freqs, hj, ems, [b * 1.08 for b in hj])
        assert bad.passed is False
        assert bad.culprit_pair == "hj-meep"


# ── 能力声明与注册表 ──────────────────────────────────────────────────────────

class TestCapabilitiesAndRegistry:
    def test_registered_and_caps_truthful(self):
        import rfauto.adapters  # noqa: F401 —— 导入副作用完成注册
        from rfauto.adapters.em_solver_base import (
            MATERIAL_MODELS,
            EMSolverType,
            get_global_registry,
            solver_capabilities_for,
        )
        from rfauto.adapters.meep_adapter import MeepSolver
        assert get_global_registry().lookup(EMSolverType.MEEP) is MeepSolver
        caps = solver_capabilities_for(EMSolverType.MEEP)
        assert caps.solver_type == "meep"
        assert caps.supports_wave_port is True          # EigenModeSource 模式端口
        assert caps.supports_lumped_port is False
        assert caps.supports_touchstone_export is False  # 仅 CSV（不虚报）
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.parallel_backends == ()              # subprocess 未透传 MPI
        assert caps.requires_license is False
        assert caps.supported_templates == ("mline",)
        assert set(caps.material_models) <= MATERIAL_MODELS
        assert caps.availability_gate == "python_exe+meep_import"

    def test_capabilities_available_tracks_is_available(self, tmp_path):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.meep_adapter import MeepSolver
        dummy = tmp_path / "meep-python"
        dummy.write_text("", encoding="ascii")
        solver = MeepSolver(EMSolverConfig(solver_type=EMSolverType.MEEP,
                                           exe_path=str(dummy)))
        assert solver.is_available() is True
        assert solver.capabilities().available is True
        missing = MeepSolver(EMSolverConfig(solver_type=EMSolverType.MEEP,
                                            exe_path=str(tmp_path / "nope")))
        assert missing.is_available() is False
        assert missing.capabilities().available is False

    def test_find_exe_env_override(self, tmp_path, monkeypatch):
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
        from rfauto.adapters.meep_adapter import MeepSolver
        fake = tmp_path / "conda-python"
        fake.write_text("", encoding="ascii")
        monkeypatch.setenv("RFAUTO_MEEP_PYTHON", str(fake))
        solver = MeepSolver(EMSolverConfig(solver_type=EMSolverType.MEEP))
        assert solver._find_exe() == str(fake)

    def test_build_geometry_rejects_unknown_template_and_bad_freqs(self, tmp_path):
        solver, _wd = _make_solver(tmp_path)
        assert solver.connect()
        assert not solver.build_geometry({"template": "patch"})   # v1 仅 mline
        assert not solver.build_geometry({"n_freq": 1})           # DF=0 退化
        assert not solver.build_geometry({"freqs_ghz": [2.5, 2.0]})  # 非递增
        assert not solver.build_geometry({"params": {"w_mm": -1.0}})
        assert solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        script = (tmp_path / "run" / "meep_mline_sim.py").read_text(encoding="utf-8")
        assert "2250000000.0" in script

    def test_visualizations_and_formats(self, tmp_path):
        solver, _wd = _make_solver(tmp_path)
        vis = solver.visualizations()
        kinds = [v["kind"] for v in vis]
        assert "model3d" in kinds and "sparams" in kinds
        assert solver.supported_output_formats() == ["csv"]
