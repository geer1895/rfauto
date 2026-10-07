"""DP-10 P1 离线内核测试：metasurface_lut 纯函数面（判据预声明 runs/df6_dp10ms/criteria.md）。

判据（本文件全部离线合成，零仿真）：
- J1a 合成回收钉（逐位）：合成 S11→LUT→布局综合反查→已知相位图逐位；
- J1b LUT 留一交叉验证合成版：pchip 留一相位 ≤10°@|S|≥−3dB、幅度 ≤0.5dB；
- J1c 覆盖 ≥300° 覆盖门（合成 LUT 预演，真机门同口径）；
- T26 圆周度量（T13 分支切割伪象修复）：覆盖=圆周间隙口径、pchip 相位
  插值圆周化（跨 ±180° 界走短弧）——合成回收钉（已知真值回收+旧行为
  报错值对照）；
- J5 量化：σ²=(π/2^b)²/3 + 文献带 3/0.6/0.2±1dB；
- EC 自洽钉：JC 缝带通口径 |S21| 峰=设计 f0（并联拓扑；串联=带阻陷即红）；
- 名义尺寸闭式互证（#252）：εeff 不动点与渲染同源（openems_templates 侧
  消费同一函数，此处钉数值域合理性与确定性）；
- JSON+CSV 双载体逐位往返。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.metasurface_lut import (
    ETA0_OHM,
    LUT_SCHEMA,
    MetasurfaceLUT,
    _circ_diff_deg,
    arc_coverage_deg,
    fss_jcross_parallel_lc,
    fss_mesh_grid_inductance_h,
    fss_patch_grid_capacitance_f,
    fss_screen_sparams,
    lut_interp_pchip,
    lut_lookup_phase,
    lut_summary,
    ms_cross_arm_len_mm,
    ms_jcross_slot_dims_mm,
    ms_patch_eps_eff,
    ms_patch_resonant_len_mm,
    ms_screen_eps_eff,
    phase_quantization_mse_rad2,
    quantization_loss_db,
    quantize_phase_deg,
    required_phase_plane_wave,
    required_phase_reflectarray,
    synthesize_layout,
    unwrap_phase_deg,
    unwrap_sweep_axis_deg,
)

ER = 3.66
H_MM = 1.524
F0 = 10.0


# ─── 合成 LUT 工厂（合成谐振模型：单值已知函数，非真机数据）──────────────────


def _synthetic_phase_deg(px_mm: float) -> float:
    """合成反射相位模型：px∈[2,13]mm 线性映射 −180°..+150°（覆盖 330°）。

    已知单值函数=回收钉的"真值"；单调覆盖与真贴片 LUT 同形（谐振陡降区
    由 pchip 消费——合成版不做谐振陡降，LOO 判的是插值器本身）。
    """
    return -180.0 + (px_mm - 2.0) / (13.0 - 2.0) * 330.0


def _synthetic_lut(n_px: int = 23, n_freq: int = 41) -> MetasurfaceLUT:
    px = np.linspace(2.0, 13.0, n_px)
    freq = np.linspace(9.0, 11.0, n_freq)
    s11_db = np.full((n_px, n_freq), -0.2)
    phase = np.empty((n_px, n_freq))
    for i, v in enumerate(px):
        phase[i, :] = _synthetic_phase_deg(v)
    return MetasurfaceLUT(
        cell_id="ms_patch", f0_ghz=F0, substrate_key="rogers4350b_60mil",
        sweep_key="px_mm", sweep_values=px, freq_ghz=freq,
        s11_db=s11_db, s11_phase_deg=phase,
        params={"period_mm": 15.0, "py_mm": px[0], "h_mm": H_MM, "er": ER},
        origin="synthetic",
        validity={"theta_deg": 0.0, "pol": "x", "technique": "wg_sim"},
    )


# ─── J1a 合成回收钉（逐位）────────────────────────────────────────────────────


class TestSynthesisRecoveryNail:
    def test_reflectarray_plane_wave_roundtrip_bitwise(self) -> None:
        """闭式目标相位 → 布局综合反查 → 每胞 px == LUT 最近邻真值（逐位）。"""
        lut = _synthetic_lut()
        cells = synthesize_layout(
            n_x=8, n_y=8, period_m=15e-3, f0_ghz=F0, lut=lut,
            u_beam=np.array([math.sin(math.radians(20)), 0.0,
                             math.cos(math.radians(20))]),
        )
        # 独立重算目标相位（不经过 synthesize_layout 的路径）
        xs = (np.arange(8) - 3.5) * 15e-3
        xx, yy = np.meshgrid(xs, xs, indexing="ij")
        pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(64)], axis=1)
        u_in = np.array([0.0, 0.0, -1.0])
        u_out = np.array([math.sin(math.radians(20)), 0.0,
                          math.cos(math.radians(20))])
        k0 = 2 * math.pi * F0 * 1e9 / 299792458.0
        phi_true = np.degrees(k0 * ((u_in - u_out) * pos).sum(axis=1)) % 360.0
        # 最近邻真值（独立实现：圆周距离 argmin）
        col = lut.s11_phase_deg[:, int(np.argmin(np.abs(lut.freq_ghz - F0)))]
        for k, cell in enumerate(cells):
            assert cell["phase_target_deg"] == pytest.approx(
                float(phi_true[k]), abs=1e-9)
            d = np.array([min((float(phi_true[k]) - v) % 360.0,
                              360.0 - ((float(phi_true[k]) - v) % 360.0))
                          for v in col])
            nearest_px = float(lut.sweep_values[int(np.argmin(d))])
            assert cell["sweep_value"] == nearest_px, f"cell {k} 反查漂移"

    def test_point_feed_reflectarray_phase_law(self) -> None:
        """点馈反射阵：φ=k0(R−r·û) mod 2π——对 x 偶对称、中心最小、常数项独立。"""
        pos = np.array([[x, 0.0, 0.0] for x in np.linspace(-0.03, 0.03, 7)])
        feed = np.array([0.0, 0.0, 0.15])  # 正上方 150mm 相心
        u_beam = np.array([0.0, 0.0, 1.0])  # 法向主瓣
        phi = required_phase_reflectarray(pos, feed, u_beam, F0)
        k0 = 2 * math.pi * F0 * 1e9 / 299792458.0
        # 中心单元：R=0.15 → φ = k0·0.15 mod 2π（常数项不被形式吸收）
        assert float(phi[3]) == pytest.approx(
            math.degrees(k0 * 0.15) % 360.0, abs=1e-6)
        assert phi[0] == pytest.approx(phi[6], rel=1e-9)
        assert phi[0] > phi[3]
        assert bool(np.all((phi >= 0.0) & (phi < 360.0)))

    def test_quantized_layout_cells_match_two_step_path(self) -> None:
        """b-bit 量化不变量：布局综合逐胞 == 「先量化目标相位再反查」两步路径。

        量化发生在相位域（不进 px 域）：cell.phase_quantized_deg 必须逐位等于
        quantize_phase_deg(cell.phase_target_deg, bits)，反查值与两步路径逐位
        一致（J1a 量化段）。
        """
        lut = _synthetic_lut()
        cells = synthesize_layout(
            n_x=6, n_y=6, period_m=15e-3, f0_ghz=F0, lut=lut,
            u_beam=np.array([math.sin(math.radians(15)), 0.0,
                             math.cos(math.radians(15))]),
            bits=2,
        )
        assert len(cells) == 36
        for cell in cells:
            q = quantize_phase_deg(cell["phase_target_deg"], 2)
            assert cell["phase_quantized_deg"] == q
            hit = lut_lookup_phase(lut, q)
            assert cell["sweep_value"] == hit["sweep_value"]
            assert cell["phase_achieved_deg"] == hit["phase_deg"]

    def test_bits_gt0_requires_full_coverage(self) -> None:
        """覆盖不足的 LUT 上 bits>0 显式拒绝（量化误差失控前置拦截）。"""
        lut = _synthetic_lut()
        lut.s11_phase_deg = lut.s11_phase_deg[:5, :]  # 人为砍覆盖
        lut.sweep_values = lut.sweep_values[:5]
        lut.s11_db = lut.s11_db[:5, :]
        with pytest.raises(ValueError, match="覆盖"):
            synthesize_layout(2, 2, 15e-3, F0, lut,
                              u_beam=np.array([0.0, 0.0, 1.0]), bits=2)

    def test_phase_and_law_identity_transmission(self) -> None:
        """透射编码面法向入射特例：φ=−k0·r·û_out mod 2π（规格书 §3 口径）。"""
        pos = np.array([[0.015, 0.0, 0.0], [0.0, 0.0, 0.0]])
        u_out = np.array([math.sin(math.radians(30)), 0.0,
                          math.cos(math.radians(30))])
        phi = required_phase_plane_wave(pos, np.array([0.0, 0.0, -1.0]),
                                        u_out, F0)
        k0 = 2 * math.pi * F0 * 1e9 / 299792458.0
        ref = math.degrees(-k0 * float(np.dot(u_out, pos[0]))) % 360.0
        assert phi[0] == pytest.approx(ref, abs=1e-6)
        assert phi[1] == pytest.approx(0.0, abs=1e-9)


# ─── J1b 留一交叉验证（合成版）＋ J1c 覆盖门 ─────────────────────────────────


class TestLeaveOneOutAndCoverage:
    def test_loo_pchip_recovers_synthetic(self) -> None:
        """逐点留一：pchip 相位误差 ≤10°@|S|≥−3dB、幅度 ≤0.5dB（J1b 冻结门）。"""
        lut = _synthetic_lut(n_px=23)
        j = int(np.argmin(np.abs(lut.freq_ghz - F0)))
        worst_ph = 0.0
        worst_db = 0.0
        for i in range(lut.sweep_values.size):
            keep = [k for k in range(lut.sweep_values.size) if k != i]
            sub = MetasurfaceLUT(
                cell_id=lut.cell_id, f0_ghz=F0,
                substrate_key=lut.substrate_key, sweep_key=lut.sweep_key,
                sweep_values=lut.sweep_values[keep],
                freq_ghz=lut.freq_ghz,
                s11_db=lut.s11_db[keep, :],
                s11_phase_deg=lut.s11_phase_deg[keep, :],
            )
            db, ph = lut_interp_pchip(sub, float(lut.sweep_values[i]), F0)
            # |S|≥−3dB 频点判据：合成全带 |S|=−0.2dB → 全点参与
            assert db >= -3.0
            worst_ph = max(worst_ph, abs(ph - float(lut.s11_phase_deg[i, j])))
            worst_db = max(worst_db, abs(db - float(lut.s11_db[i, j])))
        assert worst_ph <= 10.0, f"J1b 相位留一 {worst_ph:.3f}° > 10°"
        assert worst_db <= 0.5, f"J1b 幅度留一 {worst_db:.3f}dB > 0.5dB"

    def test_coverage_gate_pass_fail(self) -> None:
        """覆盖门：330° 合成 PASS；砍到 <300° FAIL（门同口径预演）。"""
        lut = _synthetic_lut()
        assert lut.coverage_gate()["verdict"] == "PASS"
        assert lut.coverage_gate()["phase_coverage_deg"] == pytest.approx(
            330.0, rel=1e-9)
        cut = MetasurfaceLUT(
            cell_id="ms_patch", f0_ghz=F0, substrate_key="x",
            sweep_key="px_mm", sweep_values=np.linspace(2.0, 8.0, 7),
            freq_ghz=lut.freq_ghz,
            s11_db=lut.s11_db[:7, :],
            s11_phase_deg=lut.s11_phase_deg[:7, :],
        )
        assert cut.coverage_gate()["verdict"] == "FAIL"


# ─── T26 圆周覆盖/圆周插值（T13 分支切割伪象内核修复；合成回收钉 #118 家法）──


def _branch_cut_column(truth_deg: np.ndarray, jump_idx: int,
                       shift_deg: float = 360.0) -> np.ndarray:
    """把连续真值列在 jump_idx 起整体平移 shift（复刻逐行频轴解缠伪象）。"""
    stored = np.array(truth_deg, dtype=float)
    stored[jump_idx:] += shift_deg
    return stored


class TestCircularCoverageMetric:
    """周期量覆盖=圆周间隙口径（T13 定案，T26 内核单源 arc_coverage_deg）。

    已知真值回收：构造已知圆周覆盖的合成相位表→新度量报真值、
    旧 max−min 口径报分支切割抬升的错值；门语义上伪 PASS 不可再现。
    """

    def test_arc_coverage_known_270(self) -> None:
        truth = np.linspace(10.0, 280.0, 55)          # 圆周覆盖 270（wrap 隙 90）
        assert arc_coverage_deg(truth) == pytest.approx(270.0, abs=1e-9)
        stored = _branch_cut_column(truth, 28)        # 后半段 +360 伪跳变
        assert arc_coverage_deg(stored) == pytest.approx(270.0, abs=1e-9)
        old_span = float(stored.max() - stored.min())  # 旧行为报错值 630
        assert old_span == pytest.approx(630.0, abs=1e-9)
        assert arc_coverage_deg(stored) != pytest.approx(old_span, rel=1e-6)

    def test_arc_coverage_degenerate_cases(self) -> None:
        assert arc_coverage_deg(np.array([])) == 0.0
        assert arc_coverage_deg(np.array([35.0])) == 0.0
        assert arc_coverage_deg(np.array([350.0, 10.0])) == pytest.approx(
            20.0, abs=1e-9)
        assert arc_coverage_deg(
            np.array([0.0, 90.0, 180.0, 270.0])) == pytest.approx(270.0, abs=1e-9)

    def test_phase_coverage_branch_cut_immune_t13_replica(self) -> None:
        """T13 fine 结构合成复刻：真圆周 100.90°，存储 max−min 被抬过门（伪
        PASS），新度量如实 FAIL——伪 PASS 不可再现的回归钉。"""
        lut = _synthetic_lut(n_px=41, n_freq=9)
        truth = np.linspace(80.0, -20.90, 41)          # 真实圆周覆盖 100.90
        stored = _branch_cut_column(truth, 21)
        lut.s11_phase_deg = stored[:, None].repeat(lut.freq_ghz.size, axis=1)
        assert lut.phase_coverage_deg() == pytest.approx(100.90, abs=1e-9)
        assert lut.phase_span_deg() == pytest.approx(
            float(stored.max() - stored.min()), rel=1e-12)
        assert lut.phase_span_deg() > 300.0            # 旧口径伪 PASS 域
        gate = lut.coverage_gate()
        assert gate["verdict"] == "FAIL"               # 新门语义
        assert gate["phase_coverage_deg"] == pytest.approx(100.90, abs=1e-9)

    def test_phase_coverage_matches_independent_unwrap(self) -> None:
        """双路径互证（#118 家法）：圆周间隙口径 == np.unwrap(px 轴) 独立实现。"""
        lut = _synthetic_lut(n_px=41, n_freq=9)
        truth = np.linspace(80.0, -20.90, 41)
        lut.s11_phase_deg = _branch_cut_column(truth, 21)[:, None].repeat(
            lut.freq_ghz.size, axis=1)
        j = int(np.argmin(np.abs(lut.freq_ghz - F0)))
        cont = np.degrees(np.unwrap(np.radians(lut.s11_phase_deg[:, j])))
        assert float(np.ptp(cont)) == pytest.approx(
            lut.phase_coverage_deg(), abs=1e-9)

    def test_branch_cut_free_lut_span_equals_coverage(self) -> None:
        """无分支切割的连续列：圆周覆盖 == max−min 跨度（旧口径对好数据无损）。"""
        lut = _synthetic_lut()
        assert lut.phase_coverage_deg() == pytest.approx(
            lut.phase_span_deg(), rel=1e-9)
        assert lut.coverage_gate()["verdict"] == "PASS"


class TestCircularInterpolation:
    """pchip 相位插值圆周化：跨 ±180° 界走短弧，不走差值捷径（合成回收钉）。"""

    def test_interp_across_branch_cut_short_arc(self) -> None:
        # 真值 [170,175,185,190]（连续穿 +180 界），存储列 idx2 起带 −360 伪跳变
        lut = _synthetic_lut(n_px=4, n_freq=9)
        truth = np.array([170.0, 175.0, 185.0, 190.0])
        lut.s11_phase_deg = _branch_cut_column(
            truth, 2, shift_deg=-360.0)[:, None].repeat(lut.freq_ghz.size, axis=1)
        px_mid = float(lut.sweep_values[1]) + 0.5
        _, ph = lut_interp_pchip(lut, px_mid)
        # 圆周短弧域内插（pchip 单调：值必落区间 [175,185]）
        assert 175.0 - 1e-6 <= ph <= 185.0 + 1e-6
        assert _circ_diff_deg(ph, 0.0) >= 170.0     # 差值捷径（伪值 0 附近）被排除
        for k, sv in enumerate(lut.sweep_values):   # 网格点回代 mod 360 一致
            _, phk = lut_interp_pchip(lut, float(sv))
            assert _circ_diff_deg(phk, truth[k]) <= 1e-9

    def test_unwrap_sweep_axis_identity_and_recovery(self) -> None:
        cont = np.linspace(-80.0, 150.0, 30)        # 连续列：恒等
        assert np.allclose(unwrap_sweep_axis_deg(cont), cont, atol=1e-12)
        stored = _branch_cut_column(cont, 15)       # 伪跳变列：回收连续真值
        got = unwrap_sweep_axis_deg(stored)
        assert np.allclose(got, cont, atol=1e-9)
        assert np.allclose(np.mod(got, 360.0), np.mod(stored, 360.0), atol=1e-9)
        assert float(np.abs(np.diff(got)).max()) < 180.0  # 圆周连续性

    def test_unwrap_sweep_axis_true_large_step_keeps_short_arc(self) -> None:
        """真差 >180°（物理欠采样）不在本原语修域：如实取最短角差（+160），
        不做采样充分性裁决（语义=圆周连续化，非真值重构）。"""
        raw = np.array([0.0, 100.0, -100.0])
        got = unwrap_sweep_axis_deg(raw)
        assert float(got[2] - got[1]) == pytest.approx(160.0, abs=1e-9)


# ─── LUT schema/双载体/provenance ─────────────────────────────────────────────


class TestLutSchema:
    def test_json_csv_roundtrip_bitwise(self) -> None:
        lut = _synthetic_lut()
        lut2 = MetasurfaceLUT.from_json(lut.to_json())
        assert np.array_equal(lut2.s11_db, lut.s11_db)
        assert np.array_equal(lut2.s11_phase_deg, lut.s11_phase_deg)
        assert lut2.to_dict()["schema"] == LUT_SCHEMA
        lut3 = MetasurfaceLUT.from_csv(lut.to_csv())
        assert np.array_equal(lut3.s11_db, lut.s11_db)
        assert np.array_equal(lut3.s11_phase_deg, lut.s11_phase_deg)
        assert lut3.params == lut.params
        # CSV↔JSON 双载体一致性
        assert MetasurfaceLUT.from_json(
            lut3.to_json()).to_dict() == lut.to_dict()

    def test_validate_flags_missing_provenance(self) -> None:
        """#320：真机 origin 缺 run_dir provenance 必须报不合格。"""
        lut = _synthetic_lut()
        assert lut.validate() == []
        lut.origin = "openems_wg_sim"
        problems = lut.validate()
        assert any("run_dir" in p for p in problems)
        lut.run_dir = "runs/df6_dp10ms/wg_sim/run001"
        assert lut.validate() == []
        lut.s11_db = lut.s11_db[:, :5]
        assert any("形状" in p for p in lut.validate())

    def test_summary_and_unwrap(self) -> None:
        s = lut_summary(_synthetic_lut())
        assert s["n_sweep"] == 23 and s["interp"] == "pchip"
        raw = np.array([-170.0, 170.0, -170.0])  # 跨 ±180 跳变
        unwrapped = unwrap_phase_deg(raw)
        # unwrap 取连续分支：+340° 跳变折回 −360° → [−170, −190, −170]
        assert float(unwrapped[1]) == pytest.approx(-190.0, abs=1e-9)
        assert float(unwrapped[2]) == pytest.approx(-170.0, abs=1e-9)
        assert float(np.ptp(unwrapped)) < 360.0


# ─── J5 量化口径（预声明 criteria §2）────────────────────────────────────────


class TestQuantization:
    @pytest.mark.parametrize(("bits", "mse"), [(1, 0.822467), (2, 0.205617),
                                               (3, 0.051404)])
    def test_mse_closed_form(self, bits: int, mse: float) -> None:
        assert phase_quantization_mse_rad2(bits) == pytest.approx(
            mse, abs=1e-5)
        assert phase_quantization_mse_rad2(bits) == pytest.approx(
            (math.pi / (2 ** bits)) ** 2 / 3.0, rel=1e-12)

    @pytest.mark.parametrize(("bits", "loss_db", "literature_db"),
                             [(1, 3.92, 3.0), (2, 0.91, 0.6), (3, 0.22, 0.2)])
    def test_loss_within_literature_band(self, bits: int, loss_db: float,
                                         literature_db: float) -> None:
        """J5：量化损失 vs 文献带 ±1dB（criteria §2 冻结）。"""
        got = quantization_loss_db(bits)
        assert got == pytest.approx(loss_db, abs=0.01)
        assert abs(got - literature_db) <= 1.0

    def test_quantize_grid(self) -> None:
        assert quantize_phase_deg(0.0, 1) == 0.0
        assert quantize_phase_deg(360.0, 1) == 360.0  # round-half-even 边界
        assert quantize_phase_deg(46.0, 2) == 90.0  # 2-bit 栅格 90°
        assert quantize_phase_deg(46.0, 3) == 45.0  # 3-bit 栅格 45°
        with pytest.raises(ValueError):
            quantize_phase_deg(0.0, 0)


# ─── EC 自洽钉（criteria §1d：并联=带通峰、串联口径=带阻谷）──────────────────


class TestEcClosedForms:
    def test_jcross_parallel_lc_bandpass_peak_at_f0(self) -> None:
        freq = np.linspace(6e9, 14e9, 801)
        l_h, c_f = fss_jcross_parallel_lc(12e-3, 0.5e-3, 10e9)
        r = fss_screen_sparams(freq, "parallel_lc", 12e-3,
                               ms_screen_eps_eff(ER), parallel_lc=(l_h, c_f))
        peak_i = int(np.argmax(r["s21_db"]))
        assert freq[peak_i] == pytest.approx(10e9, rel=1e-6)
        assert r["s21_db"][peak_i] == pytest.approx(0.0, abs=1e-6)
        # 离谐单调滚降（线网闭式 L 的 EC 带宽宽且高低侧不对称——幅度如实，
        # 不虚构窄带陡峭度；带缘抑制量属 J3 真机口径）
        assert r["s21_db"][0] < r["s21_db"][peak_i] - 0.5
        assert r["s21_db"][-1] < r["s21_db"][peak_i]
        assert bool(np.all(np.diff(r["s21_db"][:peak_i]) > -1e-12))  # 上升单调
        assert bool(np.all(np.diff(r["s21_db"][peak_i:]) < 1e-12))   # 下降单调

    def test_series_lc_would_be_notch(self) -> None:
        """topology 判据（离线冒烟实证入账）：串联 LC shunt 在 f0=短路=谷。"""
        freq = np.linspace(9.9e9, 10.1e9, 41)
        l_h, c_f = fss_jcross_parallel_lc(12e-3, 0.5e-3, 10e9)
        om = 2 * np.pi * freq
        z = 1j * om * l_h + 1.0 / (1j * om * c_f)  # 串联（错误拓扑）
        from rfauto.core.metasurface_lut import _abcd_shunt, _abcd_tl

        s21 = np.empty(freq.size)
        for i in range(freq.size):
            abcd = _abcd_tl(ETA0_OHM, 2 * np.pi * freq[i] / 299792458.0, 0.0)
            abcd = abcd @ _abcd_shunt(z[i]) @ abcd
            s21[i] = abs(2.0 / (abcd[0, 0] + abcd[0, 1] / ETA0_OHM
                                + abcd[1, 0] * ETA0_OHM + abcd[1, 1]))
        assert float(s21.min()) < 1e-6  # f0 处全反射（带阻陷）
        assert int(np.argmin(s21)) == 20  # 谷恰在 f0

    def test_patch_and_mesh_grid_trends(self) -> None:
        freq = np.array([6e9, 14e9])
        r_p = fss_screen_sparams(freq, "patch", 12e-3,
                                 ms_screen_eps_eff(ER), gap_m=0.5e-3,
                                 slab_eps=ER, slab_h_m=0.508e-3)
        assert r_p["s21_db"][0] > r_p["s21_db"][1]  # 贴片阵低通带阻趋势
        r_m = fss_screen_sparams(freq, "mesh", 12e-3, 1.0, wire_m=0.5e-3)
        assert r_m["s21_db"][0] < r_m["s21_db"][1]  # 线网高通趋势
        c = fss_patch_grid_capacitance_f(12e-3, 0.5e-3,
                                         ms_screen_eps_eff(ER))
        assert 1e-14 < c < 1e-11  # 量级护栏（文献贴片阵 0.01-1pF/胞）
        with pytest.raises(ValueError):
            fss_mesh_grid_inductance_h(12e-3, 13e-3)

    def test_luukkonen_prefactors_against_hand_calc(self) -> None:
        """D=12mm/g=0.5mm/εeff=2.33：α 手算互证（公式换算独立复核）。"""
        eps_eff = ms_screen_eps_eff(ER)
        c = fss_patch_grid_capacitance_f(12e-3, 0.5e-3, eps_eff)
        x = math.pi * 0.5e-3 / (2 * 12e-3)
        expect = (2 * 12e-3 / math.pi) * 8.854187817e-12 * eps_eff * math.log(
            1 / math.sin(x))
        assert c == pytest.approx(expect, rel=1e-12)
        l_h = fss_mesh_grid_inductance_h(12e-3, 1.0e-3)
        assert l_h == pytest.approx(
            4e-7 * math.pi * 12e-3 / (2 * math.pi)
            * math.log(1 / math.sin(math.pi * 1e-3 / (2 * 12e-3))), rel=1e-12)


# ─── 名义尺寸闭式（#252：禁抄毫米数，闭式单源数值域钉）────────────────────────


class TestNominalSizingClosedForms:
    def test_ms_patch_fixed_point(self) -> None:
        px = ms_patch_resonant_len_mm(10.0, ER, H_MM)
        # 自洽：px 代回 εeff 后 λ0/(2√εeff) 不动
        lam0 = 299792458.0 / 10e9 * 1e3
        assert px == pytest.approx(
            lam0 / (2 * math.sqrt(ms_patch_eps_eff(px, ER, H_MM))), rel=1e-12)
        assert 7.0 < px < 10.0  # λ0/2·(0.4..0.6) 合理域
        assert ms_patch_eps_eff(px, ER, H_MM) == pytest.approx(3.07, abs=0.1)

    def test_ms_cross_and_jcross_lambda_g(self) -> None:
        lam0 = 299792458.0 / 10e9 * 1e3
        eps_eff = ms_screen_eps_eff(ER)
        assert ms_cross_arm_len_mm(10.0, ER) == pytest.approx(
            lam0 / (4 * math.sqrt(eps_eff)), rel=1e-12)
        d = ms_jcross_slot_dims_mm(10.0, ER)
        lamg = lam0 / math.sqrt(eps_eff)
        assert d["slot_len_mm"] == pytest.approx(lamg / 4, rel=1e-12)
        assert d["stub_len_mm"] == pytest.approx(lamg / 8, rel=1e-12)

    def test_sizing_deterministic(self) -> None:
        """确定性内核：同入参两次调用逐位一致。"""
        a = ms_patch_resonant_len_mm(10.0, ER, H_MM)
        b = ms_patch_resonant_len_mm(10.0, ER, H_MM)
        assert a == b


# ─── LM-1 PRS 供体（纯增量接口：lut_prs_reflectance → fpa_antenna 桥）─────────


class TestPrsDonorBridge:
    def test_prs_reflectance_recovers_amp_and_power(self) -> None:
        """已知 s11_db → |Γ|=10^(dB/20)、R=10^(dB/10) 双径回收（rel 1e-12/1e-9）。"""
        from rfauto.core.metasurface_lut import lut_prs_reflectance

        lut = _synthetic_lut()
        px = 7.5
        out = lut_prs_reflectance(lut, px)
        db, ph = lut_interp_pchip(lut, px)
        r_amp_expected = 10.0 ** (db / 20.0)
        assert out["r_amp"] == pytest.approx(r_amp_expected, rel=1e-12)
        # 独立路径：R=10^(dB/10)（幂路径）vs amp²（乘法路径）
        assert out["r_power"] == pytest.approx(10.0 ** (db / 10.0), rel=1e-9)
        assert out["phase_deg"] == pytest.approx(ph, rel=1e-12)
        # 合成 LUT 全列 −0.2 dB → R<1 且接近 1
        assert 0.0 < out["r_power"] < 1.0
        assert out["r_power"] == pytest.approx(10.0 ** (-0.2 / 10.0), rel=1e-9)

    def test_prs_reflectance_feeds_fpa_antenna(self) -> None:
        """桥接集成：LUT 单点 (R, φ_PRS) → fpa_antenna 谐振解 h>0 + D≥1。"""
        from rfauto.core import fpa_antenna
        from rfauto.core.metasurface_lut import lut_prs_reflectance

        lut = _synthetic_lut()
        out = lut_prs_reflectance(lut, 7.5)
        sols = fpa_antenna.resonance_heights(
            lut.f0_ghz, out["phase_deg"], 180.0, n_solutions=2
        )
        assert len(sols) == 2 and all(s.h_m > 0.0 for s in sols)
        assert fpa_antenna.directivity(out["r_power"]) >= 1.0
        # 回代恒等式（跨模块契约钉）
        import math

        for sol in sols:
            residual = (
                4.0 * math.pi * sol.h_m / sol.lam0_m
                - math.radians(sol.phi_prs_deg)
                - math.radians(sol.phi_gnd_deg)
                - 2.0 * math.pi * sol.n
            )
            assert abs(residual) <= 1e-12 * max(1.0, abs(2.0 * math.pi * sol.n))
