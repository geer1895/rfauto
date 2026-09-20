"""W3⑧b 路线 B 离线单测：HFSS 仲裁脚本（建模参数/端口尺寸/结果解析，pyaedt 不 import）、
LumpedPort 渲染几何审计（#212）、路线 B 后处理、三路线对拍汇总（合成 JSON）。

纪律：数值断言对计算函数（不匹配渲染文本长尾）；合成数据独立来源（skrf
DefinedGammaZ0 造线，与被测提取器不同源）；pyaedt/openEMS 求解一律不触发。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SRC))

from rfauto.adapters.slotline_lumped_template import (
    N_PROBE_STATIONS,
    PORT_INSET_BASE,
    RUN_MARKER,
    assemble_route_b_sparams,
    beta_from_probe_phases,
    fit_z0_from_tap_s11,
    render_slotline_lumped_script,
    slotline_lumped_layout,
    tap_network_sparams,
    two_wave_beta_fit,
)
from rfauto.core.slotline import slotline_closed_form

W_MM, H_MM, ER, L_MM, F0 = 1.0, 1.524, 3.66, 93.4624, 2.5
PARAMS = {"w_mm": W_MM, "h_mm": H_MM, "er": ER, "line_len_mm": L_MM}
BAND = (2.25, 2.75)
CF = slotline_closed_form(W_MM, H_MM, ER, F0)


def _load_script(name: str):
    """按文件路径加载 scripts/ 模块（不污染 sys.modules 命名；pyaedt 懒导入不触发）。"""
    spec = importlib.util.spec_from_file_location(f"_slot_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _synth_line(f_hz, beta, z0, alpha=0.05):
    """独立来源：skrf DefinedGammaZ0 造均匀线（线基=广义 S），返回 (N,2,2)。"""
    import skrf

    freq = skrf.Frequency.from_f(f_hz, unit="Hz")
    med = skrf.media.DefinedGammaZ0(freq, z0=z0, gamma=alpha + 1j * beta)
    return med.line(L_MM * 1e-3, "m").s


@pytest.fixture(scope="module")
def hfss_mod():
    return _load_script("hfss_slotline_arbitration")


@pytest.fixture(scope="module")
def band():
    f = np.linspace(2e9, 3e9, 401)
    cf = [slotline_closed_form(W_MM, H_MM, ER, x / 1e9) for x in f]
    return f, np.array([c.beta_rad_m for c in cf]), np.array([c.z0_ohm for c in cf])


# ───────────────────────── HFSS 仲裁脚本 ─────────────────────────
class TestHfssScriptDesign:
    def test_design_point_inside_closed_form_domain_and_matches_route_a(self, hfss_mod):
        m = hfss_mod
        r = slotline_closed_form(m.W, m.H, m.ER, m.F0)
        assert r.segment == "low"
        assert pytest.approx(r.lambda_ratio * 299792458.0 / (m.F0 * 1e9) * 1e3, abs=1e-3) == m.L
        # 示例 h=0.508 在 2.5GHz 落域外（d/λ0<0.006）——脚本必须拒绝该口径
        with pytest.raises(ValueError):
            slotline_closed_form(0.5, 0.508, 3.66, 2.5)

    def test_port_variants_are_large_sections_and_primary_matches_route_a_section(self, hfss_mod):
        m = hfss_mod
        tags = [v["tag"] for v in m.PORT_VARIANTS]
        assert tags == ["mid", "wide", "xl"] and m.PRIMARY_TAG == "wide"
        wide = next(v for v in m.PORT_VARIANTS if v["tag"] == "wide")
        assert (wide["y_half_mm"], wide["z_bot_mm"], wide["z_top_mm"]) == (60.0, 30.0, 30.0)
        # 单调放大（收敛序列）；每档端口半宽 ≥ 1/e 横向衰减长度（κ=k0√(εeff−1)≈42/m → 24mm）
        k0 = 2 * np.pi * m.F0 * 1e9 / 299792458.0
        decay_mm = 1e3 / (k0 * np.sqrt(CF.eps_eff - 1))
        prev = 0.0
        for v in m.PORT_VARIANTS:
            assert v["y_half_mm"] > prev and v["y_half_mm"] >= decay_mm
            prev = v["y_half_mm"]
        # 窄档（微带惯例 5×w）不在求解列表，只作留证键
        assert m.NARROW_TAG == "narrow5w" and m.NARROW_TAG not in tags

    def test_mm_literal_formatting_no_arithmetic(self, hfss_mod):
        assert hfss_mod._mm(93.4624) == "93.4624mm"
        assert hfss_mod._mm(-60.0) == "-60.0mm"


class TestHfssBetaExtraction:
    def test_beta_from_s21_absolute_phase_exact_on_dispersive_line(self, hfss_mod, band):
        f, beta, z0 = band
        s_line = _synth_line(f, beta, z0)
        # HFSS 50Ω 导出口径：线基 → 50Ω，再由被测函数重归一回线基提 β
        import skrf

        net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"), s=s_line, z0=z0)
        net.renormalize(50.0)
        r = hfss_mod.beta_from_s21(f, net.s, 50.0, CF.z0_ohm, CF.beta_rad_m, F0 * 1e9, L_MM * 1e-3)
        i0 = int(np.argmin(np.abs(f - F0 * 1e9)))
        assert r["branch_n"] == 1
        assert r["beta_f0_rad_m"] == pytest.approx(beta[i0], rel=1e-3)
        assert np.max(np.abs(r["beta_rad_m"] / beta - 1)) < 1e-3
        # 先验 ±30% 仍锁同分支（分支步长=β 本身）
        for k in (0.7, 1.3):
            rk = hfss_mod.beta_from_s21(f, net.s, 50.0, CF.z0_ohm, CF.beta_rad_m * k,
                                        F0 * 1e9, L_MM * 1e-3)
            assert rk["branch_n"] == 1

    def test_group_delay_would_be_biased_by_dispersion(self, band):
        """反例钉住：dφ/dω 给 dβ/dω，槽线色散下偏离 β 数 %（绝对相位法才对）。"""
        f, beta, _z0 = band
        phi = -beta * L_MM * 1e-3
        slope = np.polyfit(2 * np.pi * f, phi, 1)[0]
        beta_gd = -slope / (L_MM * 1e-3) * (2 * np.pi * F0 * 1e9)
        i0 = int(np.argmin(np.abs(f - F0 * 1e9)))
        assert abs(beta_gd / beta[i0] - 1) > 0.03


class TestHfssAnalysis:
    def test_analyze_propagating_mode(self, hfss_mod, band):
        f, beta, z0 = band
        beta_h = beta * 1.012                     # HFSS 比闭式 +1.2%
        zpv = z0 * 0.97
        zpi = zpv * 0.92
        s_gen = _synth_line(f, beta_h, zpv)
        gamma = np.stack([0.05 + 1j * beta_h, (0.05 + 1j * beta_h) * (1 + 2e-4)], axis=1)
        # touchstone 阻抗注释两列皆 Zpi（真机实证）；真 Zpv 走 LastAdaptive 入参
        z0_arr = np.stack([zpi + 0.05j, zpi * (1 + 1e-3) + 0.05j], axis=1)
        i0 = int(np.argmin(np.abs(f - F0 * 1e9)))
        r = hfss_mod.analyze_hfss_slotline(f, s_gen, gamma, z0_arr,
                                           zpv_last_adaptive=complex(zpv[i0], 0.1))
        assert r["mode_evanescent_at_f0"] is False
        assert r["zpv_source"].startswith("last_adaptive")
        # LastAdaptive 缺失 → 降级用 Zpi 列冒充并打标
        r_fb = hfss_mod.analyze_hfss_slotline(f, s_gen, gamma, z0_arr)
        assert r_fb["zpv_source"].startswith("FALLBACK")
        assert r_fb["zpv_ohm"] == pytest.approx(zpi[i0], rel=1e-3)
        assert r["beta_gamma_rad_m_f0"] == pytest.approx(beta_h[i0], rel=3e-4)
        assert r["beta_gamma_vs_cf_f0_pct"] == pytest.approx(1.2, abs=0.05)
        assert r["beta_s21_rad_m_f0"] == pytest.approx(beta_h[i0], rel=1e-3)
        assert abs(r["beta_s21_vs_gamma_pct"]) < 0.1
        assert r["zpv_ohm"] == pytest.approx(zpv[i0], rel=1e-4)
        assert r["zpi_ohm"] == pytest.approx(zpi[i0] * (1 + 5e-4), rel=1e-4)   # 两列均值
        assert r["zvi_ohm"] == pytest.approx(np.sqrt(zpi[i0] * zpv[i0]), rel=1e-3)
        assert r["zpv_vs_cf_pct"] == pytest.approx(-3.0, abs=0.05)
        assert r["zpv_over_zpi"] == pytest.approx(1 / 0.92, rel=1e-3)
        assert r["port_gamma_asymmetry_max_rel"] < 1e-3
        assert r["s11_db_f0_generalized"] < -40
        # 1λ' 线在 f0 对 50Ω 透明 → 50Ω 基 S11 深谷；带内最大值回到失配级
        assert r["s11_db_f0_50ohm"] < -20
        assert r["band_max_s11_db_50ohm"] > -12
        assert len(r["beta_band_rows"]) >= 8

    def test_analyze_evanescent_mode_flags_cutoff(self, hfss_mod, band):
        """窄端口实证形态：γ≈201+j0.03、Zo≈j40Ω → 标 evanescent + 截止反推 ≈10GHz。"""
        f, _beta, _z0 = band
        gam = np.full(len(f), 201.4 + 0.035j)
        gamma = np.stack([gam, gam], axis=1)
        z0_arr = np.stack([np.full(len(f), 0.006 + 39.7j), np.full(len(f), 0.006 + 39.7j)], axis=1)
        s_gen = np.zeros((len(f), 2, 2), dtype=complex)
        s_gen[:, 0, 0] = 0.52
        s_gen[:, 1, 1] = 0.52
        s_gen[:, 1, 0] = 0.06
        s_gen[:, 0, 1] = 0.06
        r = hfss_mod.analyze_hfss_slotline(f, s_gen, gamma, z0_arr)
        assert r["mode_evanescent_at_f0"] is True
        assert r["cutoff_ghz_from_alpha"] == pytest.approx(9.95, abs=0.1)
        assert r["beta_s21_rad_m_f0"] is None and r["s11_db_f0_50ohm"] is None

    def test_analyze_variant_parses_hfss_touchstone_comments(self, hfss_mod, band, tmp_path):
        """合成 HFSS 风格 .s2p（! Gamma / ! Port Impedance 注释）→ skrf 解析 → 分析核。"""
        f, beta, z0 = band
        s_gen = _synth_line(f, beta, z0)
        lines = ["! synthetic HFSS export", "!Data is not renormalized", "# GHz S RI",
                 "! Modal data exported", "! Port[1] = P1sheetP", "! Port[2] = P2sheetP"]
        for k, fk in enumerate(f):
            s = s_gen[k]
            row = [f"{fk / 1e9:.6f}"]
            for i, j in ((0, 0), (1, 0), (0, 1), (1, 1)):
                row += [f"{s[i, j].real:.12e}", f"{s[i, j].imag:.12e}"]
            lines.append(" ".join(row))
            lines.append(f"! Gamma ! 0.05 {beta[k]:.9f} 0.05 {beta[k]:.9f}")
            lines.append(f"! Port Impedance {z0[k]:.6f} 0.0 {z0[k] * 0.92:.6f} 0.0")
        s2p_g = tmp_path / "x_gamma.s2p"
        s2p_g.write_text("\n".join(lines) + "\n", encoding="utf-8")
        s2p = tmp_path / "x.s2p"
        s2p.write_text("\n".join(ln for ln in lines if not ln.startswith("! Gamma")
                                 and not ln.startswith("! Port Impedance")) + "\n",
                       encoding="utf-8")
        i0 = int(np.argmin(np.abs(f - F0 * 1e9)))
        pm = {"port_geometry": {"total_width_mm": 120.0}, "solve_s": 1.0,
              "ports": {"P1sheetP": {"Zo(P1sheetP)": [float(z0[i0] * 0.97), 0.05]},
                        "P2sheetP": {"Zo(P2sheetP)": [float(z0[i0] * 0.92), 0.01]}}}
        r = hfss_mod._analyze_variant("wide", s2p, s2p_g, pm)
        assert r["variant"] == "wide" and r["port_geometry"]["total_width_mm"] == 120.0
        assert r["beta_gamma_rad_m_f0"] == pytest.approx(beta[i0], rel=1e-6)
        assert r["zpv_ohm"] == pytest.approx(z0[i0] * 0.97, rel=1e-5)        # LastAdaptive Zpv
        assert r["zpi_ohm"] == pytest.approx(z0[i0] * 0.96, rel=1e-5)        # 两列 (1, 0.92) 均值
        assert r["zpv_source"].startswith("last_adaptive")
        assert abs(r["beta_s21_vs_gamma_pct"]) < 0.05

    def test_finalize_verdict_gates_and_convergence(self, hfss_mod):
        def _ana(beta_pct, zpv, evan=False):
            b = CF.beta_rad_m * (1 + beta_pct / 100)
            return {"mode_evanescent_at_f0": evan, "beta_gamma_rad_m_f0": b,
                    "beta_gamma_vs_cf_f0_pct": beta_pct, "beta_s21_rad_m_f0": b * 1.001,
                    "beta_s21_vs_cf_f0_pct": beta_pct + 0.1, "beta_s21_vs_gamma_pct": 0.1,
                    "zpv_ohm": zpv, "zpi_ohm": zpv * 0.9, "zvi_ohm": zpv * 0.95,
                    "zpv_vs_cf_pct": (zpv / CF.z0_ohm - 1) * 100, "zpi_vs_cf_pct": 0.0,
                    "zvi_vs_cf_pct": 0.0, "port_geometry": {"total_width_mm": 120.0}}
        analyses = {"mid": _ana(2.0, 108.0), "wide": _ana(1.0, 107.0), "xl": _ana(0.8, 106.8),
                    "narrow5w": {"mode_evanescent_at_f0": True, "alpha_np_m_f0": 201.4,
                                 "beta_gamma_rad_m_f0": 0.03, "cutoff_ghz_from_alpha": 9.95,
                                 "zpv_complex": [0.006, 39.7]}}
        v = hfss_mod._finalize(analyses)
        assert v["ok"] is True and v["gate_beta_le_5pct"] is True
        assert set(v["port_size_convergence"]) == {"mid", "wide", "xl"}
        assert v["beta_wide_vs_xl_pct"] == pytest.approx((1.01 / 1.008 - 1) * 100, rel=1e-6)
        assert v["beta_mid_vs_wide_pct"] == pytest.approx((1.02 / 1.01 - 1) * 100, rel=1e-6)
        assert v["narrow5w_evidence"]["mode_evanescent_at_f0"] is True
        assert v["z0_three_defs_vs_cf"]["zpv_ohm"] == 107.0
        # 基准档超门 → 不凑绿
        analyses["wide"] = _ana(6.0, 107.0)
        assert hfss_mod._finalize(analyses)["ok"] is False
        # 基准档缺失 → UNDECIDABLE
        del analyses["wide"]
        v2 = hfss_mod._finalize(analyses)
        assert v2["ok"] is False and "UNDECIDABLE" in v2["note"]


# ───────────────────────── 路线 B 模板 ─────────────────────────
class TestLumpedLayout:
    def test_layout_numbers(self):
        lay = slotline_lumped_layout(PARAMS, BAND)
        f_max = 2.75e9
        base = 299792458.0 / (f_max * np.sqrt(ER)) / 50.0
        assert lay.base_m == pytest.approx(base) and lay.near_m == pytest.approx(base / 4)
        assert lay.port_inset_m == pytest.approx(PORT_INSET_BASE * base)
        assert lay.x_port2_m - lay.x_port1_m == pytest.approx(L_MM * 1e-3)
        assert lay.dom_x_m == pytest.approx(L_MM * 1e-3 / 2 + PORT_INSET_BASE * base)
        assert lay.port_inset_m > 8 * base          # 端口出 PML_8
        assert len(lay.probe_x_m) == N_PROBE_STATIONS
        assert lay.probe_x_m[0] == pytest.approx(-L_MM * 1e-3 / 4)
        assert lay.probe_x_m[-1] == pytest.approx(L_MM * 1e-3 / 4)   # 跨度 λ'/2 整周期
        assert lay.port_dx_m == lay.near_m and lay.port_dz_m == lay.near_m

    @pytest.mark.parametrize("bad", [{"w_mm": -1}, {"h_mm": 0}, {"w_mm": 200.0},
                                     {"er": 0.5}, {"line_len_mm": float("nan")}])
    def test_layout_rejects_bad_inputs(self, bad):
        with pytest.raises(ValueError):
            slotline_lumped_layout({**PARAMS, **bad}, BAND)

    def test_render_rejects_bad_port_args(self):
        with pytest.raises(ValueError):
            render_slotline_lumped_script(PARAMS, BAND, r_port_ohm=-5.0)
        with pytest.raises(ValueError):
            render_slotline_lumped_script(PARAMS, BAND, r_port_ohm=110.0, excite_port=3)


class TestLumpedRenderStructure:
    def test_compiles_and_carries_contract(self):
        text = render_slotline_lumped_script(PARAMS, BAND, r_port_ohm=110.92,
                                             beta_ref_rad_m=CF.beta_rad_m)
        compile(text, "gen", "exec")
        assert RUN_MARKER in text and text.index(RUN_MARKER) < text.index("FDTD.Run(")
        assert text.count("LumpedPort(CSX,") == 2
        assert '"PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"' in text
        assert "R_PORT = 110.92" in text
        assert "excite=1.0 if EXCITE_PORT == 1 else 0" in text
        assert 'CSX.AddProbe("vslot_%02d" % _k, p_type=0)' in text
        assert "np.unwrap(np.angle(_vals), axis=0)" in text      # 沿探针轴解缠
        assert "-np.polyfit(PROBE_X, _phases, 1)[0]" in text     # (n_probe,n_f) 形状（路线 A 崩点）
        assert "s21_convention" in text and "slotline_summary.json" in text


class TestLumpedGeometryAudit:
    """#212 离线审计：exec 脚本头 → CSXCAD 实测。"""

    @pytest.fixture(scope="class")
    def sim(self, tmp_path_factory):
        pytest.importorskip("CSXCAD")
        tmp = tmp_path_factory.mktemp("slotline_b_audit")
        text = render_slotline_lumped_script(PARAMS, BAND, r_port_ohm=110.92,
                                             beta_ref_rad_m=CF.beta_rad_m)
        head = text.split(RUN_MARKER)[0]
        g = {"__name__": "__main__", "__file__": str(tmp / "simulation.py")}
        exec(compile(head, "sim", "exec"), g)
        return g

    @staticmethod
    def _prims(csx, type_str: str):
        out = []
        for pi in range(csx.GetQtyProperties()):
            prop = csx.GetProperty(pi)
            if str(prop.GetTypeString()) != type_str:
                continue
            for prim in prop.GetAllPrimitives():
                s = np.array(prim.GetStart(), dtype=float)
                e = np.array(prim.GetStop(), dtype=float)
                out.append((prop.GetName(), np.minimum(s, e), np.maximum(s, e)))
        return out

    def test_slot_metal_two_isolated_groups_full_domain(self, sim):
        metals = self._prims(sim["CSX"], "Metal")
        assert len(metals) == 2
        w2 = W_MM / 2 * 1e-3
        lo_edges = sorted(b[2][1] for b in metals)   # 各盒 y 上缘
        hi_edges = sorted(b[1][1] for b in metals)   # 各盒 y 下缘
        assert lo_edges[0] == pytest.approx(-w2, abs=1e-12)    # 左盒止于 −w/2
        assert hi_edges[1] == pytest.approx(+w2, abs=1e-12)    # 右盒起于 +w/2
        for _n, lo, hi in metals:
            assert lo[0] == pytest.approx(sim["DOM_LO"]) and hi[0] == pytest.approx(sim["DOM_HI"])
            assert lo[2] == pytest.approx(H_MM * 1e-3) and hi[2] == pytest.approx(H_MM * 1e-3)

    def test_lumped_ports_three_dimensional_and_only_port1_excited(self, sim):
        names = [sim["CSX"].GetProperty(i).GetName() for i in range(sim["CSX"].GetQtyProperties())]
        assert "port_excite_1" in names and "port_excite_2" not in names
        for pn in (1, 2):
            port = sim[f"_port{pn}"]
            d = port.stop - port.start
            assert d[0] > 0 and d[1] == pytest.approx(W_MM * 1e-3) and d[2] > 0
            assert port.exc_ny == 1
            # 盒对称跨金属面 z=h（u 探针恰在 z=h）
            assert 0.5 * (port.start[2] + port.stop[2]) == pytest.approx(H_MM * 1e-3)
        assert pytest.approx(110.92) == sim["_port1"].R

    def test_probes_and_mesh_lines(self, sim):
        mesh = sim["mesh"]
        lx, ly, lz = (np.asarray(mesh.GetLines(a), dtype=float) for a in ("x", "y", "z"))

        def has(lines, v):
            return bool(np.min(np.abs(lines - v)) < 1e-12)

        w2 = W_MM / 2 * 1e-3
        assert has(ly, -w2) and has(ly, w2) and has(ly, 0.0)
        assert has(lz, 0.0) and has(lz, H_MM * 1e-3)
        for pn in (1, 2):
            port = sim[f"_port{pn}"]
            for v in (port.start[0], port.stop[0]):
                assert has(lx, v)
            for v in (port.start[2], port.stop[2]):
                assert has(lz, v)
        assert len(sim["PROBE_X"]) == N_PROBE_STATIONS
        assert all(has(lx, px) for px in sim["PROBE_X"])
        for lines in (lx, ly, lz):
            assert np.diff(lines).min() > 1e-6        # #152 近重合守卫


class TestRouteBPostprocessing:
    def test_two_wave_fit_robust_to_load_mismatch_and_slope_method_biased(self):
        """|Γ_load|=0.2 驻波：双行波拟合 β 误差 <0.3%、|B/A| 复原 0.2；线性斜率法偏 ≈−10%（反例钉住）。"""
        lay = slotline_lumped_layout(PARAMS, BAND)
        x = np.asarray(lay.probe_x_m)
        f = np.linspace(2.25e9, 2.75e9, 21)
        beta = np.array([slotline_closed_form(W_MM, H_MM, ER, v / 1e9).beta_rad_m for v in f])
        # V(x)=e^{−jβx}(1+Γe^{+2jβ(x−L/2)})：端口 2 残余失配 |Γ|=0.2
        v = np.exp(-1j * np.outer(x, beta)) * (1 + 0.2 * np.exp(2j * np.outer(x - L_MM * 1e-3 / 2, beta)))
        est, gam, resid = two_wave_beta_fit(x, v, beta * 1.05)      # 先验偏 +5%
        assert np.max(np.abs(est / beta - 1)) < 3e-3
        assert np.allclose(gam, 0.2, atol=2e-3)
        assert np.max(resid) < 1e-6
        # 先验 ±30% 仍收敛（窗 ±50%）
        est2, _g, _r = two_wave_beta_fit(x, v, beta * 0.75)
        assert np.max(np.abs(est2 / beta - 1)) < 3e-3
        slope = beta_from_probe_phases(x, v)
        assert np.min(np.abs(slope / beta - 1)) > 0.03           # 斜率法系统偏差（路线 A 同法同坑）
        # 无失配时两法一致
        v0 = np.exp(-1j * np.outer(x, beta))
        est0, gam0, _ = two_wave_beta_fit(x, v0, beta)
        assert np.max(np.abs(est0 / beta - 1)) < 1e-4 and np.max(gam0) < 1e-3   # |B/A| 取网格点未精化
        assert np.max(np.abs(beta_from_probe_phases(x, v0) / beta - 1)) < 1e-9
        with pytest.raises(ValueError):
            beta_from_probe_phases(x, v[:3])
        with pytest.raises(ValueError):
            two_wave_beta_fit(x[:2], v[:2], beta)

    def test_tap_network_model_matched_1lambda_and_z0_inversion(self):
        """PML 匹配线+双并联抽头解析模型：R=Z0、βL=2π → S11=−1/2、S21=+1/2（真机 r_closed
        −6.6/−7.4dB 的拓扑解释）；合成 S11 反演 Z0 精确复原；Γ_end=−1/3 与两行波 |B/A| 同源。"""
        L = L_MM * 1e-3
        s11, s21 = tap_network_sparams(110.92, 110.92, 1j * 2 * np.pi / L, L)
        assert s11 == pytest.approx(-0.5, abs=1e-12) and s21 == pytest.approx(0.5, abs=1e-12)
        # R≠Z0：βL=2π 时 Z_L1 = Z0 ∥ (Z0 ∥ R) 的闭式对照
        z0, r = 100.0, 80.0
        z_end = r * z0 / (r + z0)
        z_l1 = z0 * z_end / (z0 + z_end)
        s11b, _ = tap_network_sparams(z0, r, 1j * 2 * np.pi / L, L)
        assert s11b == pytest.approx((z_l1 - r) / (z_l1 + r), abs=1e-12)
        # 带内合成（含 α）→ 反演 Z0 逐频精确
        f = np.linspace(2.25e9, 2.75e9, 11)
        gam = 0.3 + 1j * CF.beta_rad_m * f / 2.5e9
        s11s, _ = tap_network_sparams(95.0, 110.92, gam, L)
        zf, res = fit_z0_from_tap_s11(s11s, 110.92, gam, L)
        assert np.allclose(zf, 95.0, atol=0.15) and np.max(res) < 1e-3
        # 端接反射 Γ_end=(R∥Z0−Z0)/(R∥Z0+Z0)=−1/3 @R=Z0：两行波 |B/A| 的理论预期
        assert pytest.approx(-1 / 3, abs=1e-3) == (55.46 - 110.92) / (55.46 + 110.92)

    def test_rendered_script_embeds_two_wave_source(self):
        import inspect

        text = render_slotline_lumped_script(PARAMS, BAND, r_port_ohm=110.92)
        assert inspect.getsource(two_wave_beta_fit) in text
        assert "two_wave_beta_fit(PROBE_X, _vals, _prior, span=0.5)" in text
        assert 'os.environ.get("RFAUTO_SKIP_RUN") != "1"' in text

    def test_assemble_identity_at_50_and_matches_skrf_at_110(self):
        f = np.linspace(2.25e9, 2.75e9, 51)
        beta = np.array([slotline_closed_form(W_MM, H_MM, ER, v / 1e9).beta_rad_m for v in f])
        s_line = _synth_line(f, beta, 110.92, alpha=0.0)
        s11, s21 = s_line[:, 0, 0], s_line[:, 1, 0]
        # R=50 → 恒等
        out50 = assemble_route_b_sparams(s11, s21, 50.0, 50.0)
        assert np.allclose(out50[:, 1, 0], s21) and np.allclose(out50[:, 0, 0], s11)
        # R=110.92（线基）→ 50Ω 基应与 skrf 直接重归一一致（代数路径不同，1e-8 级）
        import skrf

        net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"), s=s_line, z0=110.92)
        net.renormalize(50.0)
        out = assemble_route_b_sparams(s11, s21, 110.92, 50.0)
        assert np.allclose(out, net.s, atol=1e-7)
        with pytest.raises(ValueError):
            assemble_route_b_sparams(s11, s21[:-1], 110.92)

    def test_smoke_analyze_variant_and_hfss_loader(self, tmp_path):
        m = _load_script("smoke_slotline_port_b")
        f = np.linspace(2.25e9, 2.75e9, 201)
        beta = np.array([slotline_closed_form(W_MM, H_MM, ER, v / 1e9).beta_rad_m for v in f]) * 1.01
        s_line = _synth_line(f, beta, CF.z0_ohm, alpha=0.02)
        sp = np.column_stack([f, s_line[:, 0, 0].real, s_line[:, 0, 0].imag,
                              s_line[:, 1, 0].real, s_line[:, 1, 0].imag,
                              np.zeros(len(f)), np.zeros(len(f))])
        bt = {"freq_hz": f, "beta_probe_rad_m": beta, "beta_slope_rad_m": beta * 0.9,
              "gamma_load_mag": np.full(len(f), 0.2), "fit_resid_rel": np.full(len(f), 1e-6),
              "swr_amp": np.full(len(f), 1.05)}
        summary = {"s21_resid_at_f0": [1e-3, 0.0], "s21_convention": "uf_ref", "mesh_lines": [1, 2, 3]}
        raw = {"summary": summary, "sparams": sp, "beta": bt, "solve_s": 600.0, "work": "x"}
        hfss = {"beta_gamma_rad_m_f0": CF.beta_rad_m * 1.02, "zpv_ohm": 107.0}
        ana = m.analyze_variant("r_closed", CF.z0_ohm, raw, CF.beta_rad_m, hfss)
        assert ana["beta_vs_cf_pct"] == pytest.approx(1.0, abs=1e-6)
        assert ana["beta_vs_hfss_pct"] == pytest.approx((1.01 / 1.02 - 1) * 100, abs=1e-6)
        assert ana["s11_db_f0_line_basis"] < -100          # 合成线基匹配
        assert ana["s11_db_f0_50ohm"] < -20                # 1λ' 透明
        assert ana["passivity_max_line_basis"] <= 1.0 + 1e-9
        assert ana["beta_slope_vs_two_wave_pct"] == pytest.approx(-10.0, abs=1e-6)
        assert ana["gamma_load_mag_f0"] == pytest.approx(0.2)
        assert len(ana["beta_band_rows"]) >= 8
        # CSV 列名读取器（beta_ref 列可空）
        csv_p = tmp_path / "slotline_beta.csv"
        csv_p.write_text(
            "freq_hz,beta_probe_rad_m,beta_slope_rad_m,gamma_load_mag,fit_resid_rel,"
            "beta_ref_rad_m,swr_amp\n"
            "2.5e9,67.9,61.0,0.2,1e-6,,1.05\n2.6e9,70.1,63.0,0.2,1e-6,,1.04\n",
            encoding="utf-8")
        cols = m.read_beta_csv(csv_p)
        assert cols["beta_probe_rad_m"].tolist() == [67.9, 70.1]
        assert np.isnan(cols["beta_ref_rad_m"]).all()
        # HFSS 读取器：仅 stage=done 采信
        p = tmp_path / "h.json"
        p.write_text(json.dumps({"stage": "solved_wide"}), encoding="utf-8")
        assert m.load_hfss_zpv(p) is None
        wide = {"zpv_ohm": 107.0, "zpi_ohm": 98.0, "zvi_ohm": 102.0,
                "beta_gamma_rad_m_f0": 68.0, "beta_s21_rad_m_f0": 68.1}
        p.write_text(json.dumps({"stage": "done", "verdict": {"primary_variant": "wide"},
                                 "variants": {"wide": wide}}), encoding="utf-8")
        got = m.load_hfss_zpv(p)
        assert got["zpv_ohm"] == 107.0 and got["beta_gamma_rad_m_f0"] == 68.0 and got["variant"] == "wide"
        # 基准档倏逝 → 不采信
        p.write_text(json.dumps({"stage": "done", "verdict": {"primary_variant": "wide"},
                                 "variants": {"wide": {**wide, "mode_evanescent_at_f0": True}}}),
                     encoding="utf-8")
        assert m.load_hfss_zpv(p) is None
        assert m.load_hfss_zpv(tmp_path / "missing.json") is None


# ───────────────────────── 对拍汇总 ─────────────────────────
class TestCompareRoutes:
    def _cf(self):
        return {"beta_rad_m": CF.beta_rad_m, "z0_ohm": CF.z0_ohm, "eps_eff": CF.eps_eff}

    def _hfss(self, beta_pct=1.0):
        b = CF.beta_rad_m * (1 + beta_pct / 100)
        return {"stage": "done",
                "verdict": {"ok": True, "primary_variant": "wide",
                            "port_size_convergence": {"wide": {}}, "beta_wide_vs_xl_pct": 0.3,
                            "narrow5w_evidence": {"cutoff_ghz_from_alpha": 9.95}},
                "variants": {"wide": {"mode_evanescent_at_f0": False, "beta_gamma_rad_m_f0": b,
                                      "beta_gamma_vs_cf_f0_pct": beta_pct,
                                      "zpv_ohm": 107.0, "zpi_ohm": 98.0, "zvi_ohm": 102.4,
                                      "zpv_vs_cf_pct": -3.5, "zpi_vs_cf_pct": -11.6,
                                      "zvi_vs_cf_pct": -7.7, "eps_eff_gamma_f0": 1.68,
                                      "s11_db_f0_50ohm": -30.0, "s21_db_f0_50ohm": -0.1,
                                      "solve_s": 100.0}}}

    def _route_b(self, beta_pct_vs_cf=2.0, s11_line=-18.0):
        b = CF.beta_rad_m * (1 + beta_pct_vs_cf / 100)
        return {"primary_variant": "r_hfss_zpv",
                "variants": {"r_hfss_zpv": {"r_port_ohm": 107.0, "beta_probe_rad_m_f0": b,
                                            "beta_vs_cf_pct": beta_pct_vs_cf,
                                            "eps_eff_probe_f0": 1.7, "s11_db_f0_50ohm": -25.0,
                                            "s21_db_f0_50ohm": -0.3, "s11_db_f0_line_basis": s11_line,
                                            "s21_db_f0_line_basis": -0.4, "swr_amp_f0": 1.2,
                                            "solve_s": 700.0, "s21_convention": "uf_ref"}},
                "lumped_port_grading": {"beta_usable": True, "sparams_usable": s11_line <= -15,
                                        "sparams_grade": "B"}}

    def test_pending_everything_but_closed_form(self):
        m = _load_script("compare_slotline_routes")
        out = m.build_compare(self._cf(), None, None, None)
        statuses = [r["status"] for r in out["rows"]]
        assert statuses[0] == "ok" and all(s == "pending" for s in statuses[1:])
        assert out["gates"]["route_b_beta_vs_hfss_le_3pct"] is None
        assert any("pending" in c for c in out["conclusions"])

    def test_full_compare_gate_pass_and_fail(self):
        m = _load_script("compare_slotline_routes")
        route_a = {"beta_three_way_f0": {"openems_probe": CF.beta_rad_m * 1.015, "ngsolve": CF.beta_rad_m,
                                         "pct_oem_vs_cf": 1.5},
                   "openems": {"s11_at_f0": [0.05, 0.0], "s21_at_f0": [0.9, 0.1]},
                   "port": {"z_mode_ohm": 107.4}, "gates": {}}
        out = m.build_compare(self._cf(), self._hfss(1.0), route_a, self._route_b(2.0))
        g = out["gates"]
        assert g["hfss_beta_vs_cf_le_5pct"] is True
        assert g["route_b_beta_vs_hfss_le_3pct"] is True          # (1.02/1.01−1)=+0.99%
        assert g["route_a_beta_vs_hfss_le_3pct_info"] is True
        b_row = next(r for r in out["rows"] if r["source"].startswith("route B"))
        assert b_row["beta_vs_hfss_pct"] == pytest.approx((1.02 / 1.01 - 1) * 100, rel=1e-9)
        assert any("PASS" in c for c in out["conclusions"])
        # 路线 B 偏 5% → 门红，如实
        out2 = m.build_compare(self._cf(), self._hfss(1.0), None, self._route_b(6.0))
        assert out2["gates"]["route_b_beta_vs_hfss_le_3pct"] is False
        assert any("FAIL" in c for c in out2["conclusions"])
        # HFSS 倏逝/未决 → HFSS 行 undecidable，路线 B 门 None
        h = self._hfss(1.0)
        h["variants"]["wide"]["mode_evanescent_at_f0"] = True
        out3 = m.build_compare(self._cf(), h, None, self._route_b(2.0))
        assert out3["rows"][1]["status"] == "undecidable"
        assert out3["gates"]["route_b_beta_vs_hfss_le_3pct"] is None
