"""C14 有源链路确定性内核单测（core/active_chain）。

钉死口径（全部离线、纯 numpy）:
- 稳定性: Rollett K/μ 与 core/cosim.check_stability_k 交叉一致;
- 增益: GT/GP/GA 在双共轭匹配点三重相等 + 独立 ABCD 电路暴力求解互证
  + Γ 网格搜索最大值 == GT,max（教科书恒等式裁判, 不赌推导）;
- 恒增益圈/恒噪声圈: 圈上点回代增益/噪声 == 目标值（1e-9 级恒等式）;
- Cripps load-pull: P(Γopt)==Vsw·Isw/2 闭式、数值等值点落在解析等功率线
  （电流限 Norton 圆弧 ∪ 电压限弦）上 1e-6 级、合理性裁判全绿。

数值审计记录（2026-09-14, 三重独立验证）: GT 内核 vs 独立 ABCD 电路求解
差 <1e-13 dB; 曾被引用的 |S21/S12|(K−√(K²−4)) 闭式被无源 6dB 衰减器
反例证伪（该式给 +1.58dB, 真值 −6dB）, 本内核不采用（见
simultaneous_conjugate_match docstring）。
"""

import numpy as np
import pytest

from rfauto.core import active_chain as ac
from rfauto.core.cosim import check_stability_k

F0 = 2.0e9
F_PA = 2.4e9

#: 稳定双极性 LNA 器件（栅阻尼 rg 后 K=2.70>1, 数值审计实测）。
LNA_STABLE = dict(gm_s=0.02, rds_ohm=300.0, cgs_f=0.5e-12, cds_f=0.12e-12,
                  cgd_f=2e-15, rg_ohm=5.0)
#: 单向器件（cgd=0 → S12=0, K=inf）。
LNA_UNILATERAL = dict(gm_s=0.03, rds_ohm=300.0, cgs_f=0.5e-12, cds_f=0.12e-12,
                      cgd_f=0.0, rg_ohm=5.0)
#: 裸 FET（无栅阻尼）→ K≈0.005, 条件稳定。
LNA_UNSTABLE = dict(gm_s=0.05, rds_ohm=300.0, cgs_f=0.5e-12, cds_f=0.12e-12,
                    cgd_f=0.02e-12, rg_ohm=0.0)
#: 稳定 PA 器件（K=1.77, GT,max≈15.79dB）。
PA_STABLE = dict(gm_s=0.08, rds_ohm=200.0, cgs_f=2e-12, cds_f=1.2e-12,
                 cgd_f=0.02e-12, rg_ohm=8.0)
#: PA 负载线物理参数: Pmax = (5−0.3)·0.2/2 = 0.47W = 26.72dBm。
PA_PHYS = dict(vdd_v=5.0, imax_a=0.2, cout_f=1.2e-12, vknee_v=0.3)


def _s(params: dict, f: float = F0) -> np.ndarray:
    return ac.HybridPiModel(**params).to_sparams(f)


def _through_line() -> np.ndarray:
    """理想过线: S21=1, 其余为 0（注意 eye 是全反射, 不是过线）。"""
    return np.array([[0.0, 1.0], [1.0, 0.0]], dtype=complex)


def _attenuator_db(db: float) -> np.ndarray:
    a = 10.0 ** (-db / 20.0)
    return np.array([[0, a], [a, 0]], dtype=complex)


def _brute_force_gt(
    s: np.ndarray, gamma_s: complex, gamma_l: complex, z0: float = 50.0,
) -> float:
    """独立 ABCD 电路暴力求解 GT = P_del/P_av（与波公式零共享代码路径）。

    [Vs, Zs(ΓS)] → 器件 ABCD → [ZL(ΓL)]; P_av = |Vs|²/(8 Re{Zs}),
    P_del = |I_L|²·Re{ZL}/2（峰值振幅口径）。
    """
    det = s[0, 0] * s[1, 1] - s[0, 1] * s[1, 0]
    d = 2.0 * s[1, 0]
    a = (1 + s[0, 0] - s[1, 1] - det) / d
    b = z0 * (1 + s[0, 0] + s[1, 1] + det) / d
    c = (1 - s[0, 0] - s[1, 1] + det) / (z0 * d)
    dd = (1 - s[0, 0] + s[1, 1] - det) / d
    zs = ac.gamma_to_z(gamma_s, z0)
    zl = ac.gamma_to_z(gamma_l, z0)
    vs = 2.0
    i2 = vs / ((a * zl + b) + zs * (c * zl + dd))
    p_del = abs(i2) ** 2 * zl.real / 2.0
    p_av = abs(vs) ** 2 / (8.0 * zs.real)
    return 10.0 * np.log10(p_del / p_av)


class TestGammaZ:
    def test_roundtrip(self):
        for z in (50.0, 12.3 + 45.6j, 200.0 - 30.0j, 1e-3):
            g = ac.z_to_gamma(z)
            assert abs(ac.gamma_to_z(g) - z) < 1e-9 * max(1.0, abs(z))

    def test_matched_load(self):
        assert abs(ac.z_to_gamma(50.0)) < 1e-15
        assert abs(ac.gamma_to_z(0.0) - 50.0) < 1e-15


class TestStability:
    def test_stable_device(self):
        m = ac.stability_margins(_s(LNA_STABLE))
        assert m.unconditionally_stable
        assert m.k_factor > 1 and m.delta_abs < 1 and m.mu_factor > 1

    def test_bare_fet_conditionally_stable(self):
        m = ac.stability_margins(_s(LNA_UNSTABLE))
        assert not m.unconditionally_stable
        assert m.k_factor < 1.0

    def test_cosim_cross_consistency(self):
        """与 core/cosim.check_stability_k 的 K/μ 公式交叉一致。"""
        for params in (LNA_STABLE, LNA_UNSTABLE):
            s = _s(params)
            mine = ac.stability_margins(s)
            theirs = check_stability_k(s)
            assert abs(mine.k_factor - theirs.k_factor) < 1e-12
            assert abs(mine.mu_factor - theirs.mu_factor) < 1e-12
            assert mine.unconditionally_stable == theirs.is_stable

    def test_attenuator_stable(self):
        m = ac.stability_margins(_attenuator_db(6.0))
        assert m.unconditionally_stable

    def test_rejects_non_2x2(self):
        with pytest.raises(ValueError):
            ac.stability_margins(np.zeros((3, 3), dtype=complex))


class TestTransducerGain:
    def test_gt_50ohm_equals_s21_power(self):
        s = _s(LNA_STABLE)
        assert abs(ac.transducer_gain_db(s, 0.0, 0.0) - 20.0 * np.log10(abs(s[1, 0]))) < 1e-12

    def test_brute_force_circuit_agreement(self):
        """GT 内核 vs 独立 ABCD 电路暴力求解（<1e-10 dB, 含失配点）。"""
        rng = np.random.default_rng(14)
        s = _s(LNA_STABLE)
        for _ in range(8):
            gs = 0.6 * np.exp(1j * rng.uniform(0, 2 * np.pi))
            gl = 0.5 * np.exp(1j * rng.uniform(0, 2 * np.pi))
            assert abs(ac.transducer_gain_db(s, gs, gl) - _brute_force_gt(s, gs, gl)) < 1e-10

    def test_through_line_mismatch_loss(self):
        """过线 GT(ΓS,0) == (1−|ΓS|²)（源失配损耗, 暴力求解同式）。"""
        gs = 0.6 + 0.2j
        expect = 10.0 * np.log10(1.0 - abs(gs) ** 2)
        assert abs(ac.transducer_gain_db(_through_line(), gs, 0.0) - expect) < 1e-12

    def test_triple_equality_at_conjugate_match(self):
        """双共轭匹配点 GT=GP=GA（教科书恒等式）。"""
        s = _s(LNA_STABLE)
        cm = ac.simultaneous_conjugate_match(s)
        gt = ac.transducer_gain_db(s, cm.gamma_s, cm.gamma_l)
        assert abs(gt - ac.operating_power_gain_db(s, cm.gamma_l)) < 1e-10
        assert abs(gt - ac.available_power_gain_db(s, cm.gamma_s)) < 1e-10

    def test_grid_max_equals_gt_max(self):
        """Γ 网格搜索最大增益 == 内核 GT,max（最优点真值裁判）。"""
        s = _s(LNA_STABLE)
        cm = ac.simultaneous_conjugate_match(s)
        best = -np.inf
        for r in np.linspace(0, 0.999, 200):
            for t in np.linspace(0, 2 * np.pi, 360, endpoint=False):
                g = r * np.exp(1j * t)
                v = ac.transducer_gain_db(s, g, g)
                best = max(best, v)
        assert ac.transducer_gain_db(s, cm.gamma_s, cm.gamma_l) >= best - 1e-6

    def test_gt_max_not_above_msg(self):
        """GT,max ≤ |S21/S12|（K=1 稳定边界增益上限）。"""
        s = _s(LNA_STABLE)
        cm = ac.simultaneous_conjugate_match(s)
        _s11, s12, s21, _s22 = ac._unpack(s)
        msg_db = 20.0 * np.log10(abs(s21) / abs(s12))
        assert cm.gt_max_db <= msg_db + 1e-9


class TestConjugateMatch:
    def test_defining_property(self):
        """Γin(ΓML) == conj(ΓMS)（双共轭匹配定义式）。"""
        s = _s(LNA_STABLE)
        cm = ac.simultaneous_conjugate_match(s)
        assert abs(ac.input_gamma(s, cm.gamma_l) - np.conj(cm.gamma_s)) < 1e-9
        assert abs(ac.output_gamma(s, cm.gamma_s) - np.conj(cm.gamma_l)) < 1e-9
        assert abs(cm.gamma_s) < 1 and abs(cm.gamma_l) < 1

    def test_attenuator_matches_at_center(self):
        """匹配衰减器: ΓMS=ΓML=0, GT,max=|S21|²（C1=0 退化路径）。"""
        s = _attenuator_db(6.0)
        cm = ac.simultaneous_conjugate_match(s)
        assert abs(cm.gamma_s) < 1e-12 and abs(cm.gamma_l) < 1e-12
        assert abs(cm.gt_max_db - (-6.0)) < 1e-9

    def test_unilateral_exact_closed_form(self):
        """单向器件: ΓMS=S11*, ΓML=S22*, GT,max 教科书闭式。"""
        s = _s(LNA_UNILATERAL)
        cm = ac.simultaneous_conjugate_match(s)
        s11, _s12, s21, s22 = ac._unpack(s)
        assert abs(cm.gamma_s - np.conj(s11)) < 1e-12
        assert abs(cm.gamma_l - np.conj(s22)) < 1e-12
        expect = 10.0 * np.log10(abs(s21) ** 2 / ((1 - abs(s11) ** 2) * (1 - abs(s22) ** 2)))
        assert abs(cm.gt_max_db - expect) < 1e-9

    def test_unstable_raises(self):
        with pytest.raises(ValueError, match="无条件稳定"):
            ac.simultaneous_conjugate_match(_s(LNA_UNSTABLE))


class TestGainCircle:
    def test_on_circle_points_hit_target(self):
        """圈上任意点的单向增益 == 目标增益（1e-9 恒等式）。"""
        s = _s(LNA_UNILATERAL)
        g1 = ac.unilateral_transducer_gain_db(s, 0.0, 0.0)
        for delta in (0.5, 1.0, 2.0):
            circ = ac.constant_gain_circle(s, g1 - delta, side="output")
            assert circ.radius >= 0
            errs = []
            for ang in np.linspace(0, 2 * np.pi, 16, endpoint=False):
                gl = circ.center + circ.radius * np.exp(1j * ang)
                if abs(gl) < 1.0:
                    errs.append(abs(ac.unilateral_transducer_gain_db(s, 0.0, gl) - (g1 - delta)))
            assert max(errs) < 1e-9

    def test_input_side_symmetric(self):
        s = _s(LNA_UNILATERAL)
        g1 = ac.unilateral_transducer_gain_db(s, 0.0, 0.0)
        circ = ac.constant_gain_circle(s, g1 - 1.0, side="input")
        errs = [
            abs(ac.unilateral_transducer_gain_db(s, circ.center + circ.radius * np.exp(1j * a), 0.0)
                - (g1 - 1.0))
            for a in np.linspace(0, 2 * np.pi, 12, endpoint=False)
            if abs(circ.center + circ.radius * np.exp(1j * a)) < 1.0
        ]
        assert max(errs) < 1e-9

    def test_max_gain_degenerates_to_point(self):
        """输出侧最大增益圈退化为点（圆心 S22*, 半径 0）。

        侧增益上限 = |S21|²/(1−|S22|²)（总 GTU_max 是源/负载两侧增益之积,
        不能整值喂给单侧圈）。
        """
        s = _s(LNA_UNILATERAL)
        _s11, _s12, s21, s22 = ac._unpack(s)
        side_max_db = 10.0 * np.log10(abs(s21) ** 2 / (1.0 - abs(s22) ** 2))
        circ = ac.constant_gain_circle(s, side_max_db, side="output")
        assert circ.radius < 1e-6  # dB↔倍数往返的浮点尾差
        assert abs(circ.center - np.conj(s22)) < 1e-9
        # 该点回代 GTU(0, S22*) == 侧上限
        assert abs(ac.unilateral_transducer_gain_db(s, 0.0, np.conj(s22)) - side_max_db) < 1e-9

    def test_over_range_raises(self):
        s = _s(LNA_UNILATERAL)
        with pytest.raises(ValueError, match="可达范围"):
            ac.constant_gain_circle(s, 60.0, side="output")

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            ac.constant_gain_circle(_s(LNA_UNILATERAL), 10.0, side="both")


class TestNoise:
    GAMMA_OPT = 0.3 + 0.2j
    RN = 0.4
    FMIN_DB = 0.5

    def test_f_at_gamma_opt_equals_fmin(self):
        f = ac.noise_figure_db(self.FMIN_DB, self.GAMMA_OPT, self.RN, self.GAMMA_OPT)
        assert abs(f - self.FMIN_DB) < 1e-12

    def test_f_increases_away_from_opt(self):
        base = ac.noise_figure_db(self.FMIN_DB, self.GAMMA_OPT, self.RN, self.GAMMA_OPT)
        near = ac.noise_figure_db(self.FMIN_DB, self.GAMMA_OPT, self.RN, self.GAMMA_OPT * 0.8)
        far = ac.noise_figure_db(self.FMIN_DB, self.GAMMA_OPT, self.RN, 0.0)
        assert base < near < far

    def test_noise_circle_on_circle_identity(self):
        """圈上点回代 F == 目标噪声（1e-12 恒等式）。"""
        target = 0.8
        circ = ac.noise_figure_circle(self.FMIN_DB, self.GAMMA_OPT, self.RN, target)
        errs = []
        for ang in np.linspace(0, 2 * np.pi, 24, endpoint=False):
            g = circ.center + circ.radius * np.exp(1j * ang)
            if abs(g) < 1.0:
                errs.append(abs(ac.noise_figure_db(self.FMIN_DB, self.GAMMA_OPT, self.RN, g) - target))
        assert max(errs) < 1e-12

    def test_fmin_circle_degenerates_to_opt_point(self):
        circ = ac.noise_figure_circle(self.FMIN_DB, self.GAMMA_OPT, self.RN, self.FMIN_DB)
        assert circ.radius < 1e-12
        assert abs(circ.center - self.GAMMA_OPT) < 1e-12

    def test_below_fmin_raises(self):
        with pytest.raises(ValueError, match="低于 Fmin"):
            ac.noise_figure_circle(self.FMIN_DB, self.GAMMA_OPT, self.RN, 0.3)


class TestHybridPi:
    def test_unilateral_when_cgd_zero(self):
        s = _s(LNA_UNILATERAL)
        assert abs(s[0, 1]) < 1e-15

    def test_reciprocal_when_gm_zero(self):
        s = ac.HybridPiModel(gm_s=0.0, rds_ohm=300.0, cgs_f=0.5e-12,
                             cds_f=0.12e-12, cgd_f=0.05e-12).to_sparams(F0)
        assert abs(s[0, 1] - s[1, 0]) < 1e-12

    def test_rg_damps_input_reflection(self):
        """|S11|<1 仅在 rg>0 时成立（纯电容输入 |S11|=1）。"""
        s_rg0 = ac.HybridPiModel(gm_s=0.02, rds_ohm=300.0, cgs_f=0.5e-12,
                                 cds_f=0.12e-12, cgd_f=0.0, rg_ohm=0.0).to_sparams(F0)
        s_rg5 = ac.HybridPiModel(gm_s=0.02, rds_ohm=300.0, cgs_f=0.5e-12,
                                 cds_f=0.12e-12, cgd_f=0.0, rg_ohm=5.0).to_sparams(F0)
        assert abs(abs(s_rg0[0, 0]) - 1.0) < 1e-9
        assert abs(s_rg5[0, 0]) < 1.0 - 1e-4

    def test_y21_zero_raises(self):
        model = ac.HybridPiModel(gm_s=0.0, rds_ohm=1e12, cgs_f=0.0, cds_f=0.0,
                                 cgd_f=0.0, rg_ohm=0.0)
        with pytest.raises(ValueError, match="Y21"):
            model.to_sparams(F0)


class TestCrippsLoadPull:
    def _device(self) -> ac.LoadPullDevice:
        return ac.LoadPullDevice(**PA_PHYS)

    def test_class_a_max_power_closed_form(self):
        dev = self._device()
        assert abs(dev.max_power_dbm() - 10.0 * np.log10(0.5 * 4.7 * 0.2 / 1e-3)) < 1e-9
        assert abs(dev.gopt_s - 0.2 / 4.7) < 1e-12

    def test_power_at_optimum_is_pmax(self):
        dev = self._device()
        p = ac.load_pull_power_dbm(dev.optimal_gamma(F_PA), dev, F_PA)
        assert abs(float(p) - dev.max_power_dbm()) < 1e-9

    def test_invalid_loads_give_no_power(self):
        """极端负载: 开路/短路只剩微功率（Cout 电流通路）, |ΓL|≥1 判 −inf。"""
        dev = self._device()
        pmax = dev.max_power_dbm()
        p_open = float(ac.load_pull_power_dbm(0.999 + 0.0j, dev, F_PA))
        p_short = float(ac.load_pull_power_dbm(-0.999 + 0.0j, dev, F_PA))
        assert p_open < pmax - 20.0
        assert p_short < pmax - 20.0
        # |ΓL|>1（负阻区, 数值外推）: 无功率交付
        p_neg = ac.load_pull_power_dbm(1.5 + 0.0j, dev, F_PA)
        assert float(p_neg) == -np.inf

    def test_locus_points_satisfy_physics(self):
        """解析等功率线采样点回代功率面 == 电平（数值↔闭式互证, <0.01dB）。"""
        dev = self._device()
        for bo in (1.0, 2.0, 3.0):
            locus = ac.cripps_contour_locus(dev, F_PA, bo)
            level = locus["level_dbm"]
            pts = [complex(pt["re"], pt["im"]) for pt in locus["gamma_polyline"]]
            assert len(pts) >= 20
            p = ac.load_pull_power_dbm(np.asarray(pts), dev, F_PA)
            finite = np.isfinite(p)
            assert finite.all(), "等功率线采样点必须落在有效负载区"
            assert float(np.max(np.abs(p - level))) < 0.01

    def test_scan_grid_optimum_matches_model(self):
        dev = self._device()
        scan = ac.load_pull_scan(dev, F_PA, n_grid=61)
        opt = scan.optimum_dict()
        assert opt["gamma_dist"] < 0.05
        assert abs(opt["power_dbm"] - opt["power_model_dbm"]) < 0.5

    def test_scan_contours_on_analytic_locus(self):
        dev = self._device()
        scan = ac.load_pull_scan(dev, F_PA, n_grid=61, backoff_db=(1.0, 2.0, 3.0))
        for c in scan.contours:
            assert c["locus_max_dev"] < 1e-5
            assert c.get("arc_circle_fit_rel_rms", 1.0) < 0.01

    def test_plausibility_all_green_with_stable_pa(self):
        dev = self._device()
        spa = _s(PA_STABLE, F_PA)
        scan = ac.load_pull_scan(dev, F_PA, n_grid=81, backoff_db=(1.0, 2.0, 3.0),
                                 sparams=spa)
        pl = ac.load_pull_plausibility(scan, sparams=spa)
        assert pl["plausible"] is True, pl
        # GT,max 恒等式段: 网格增益峰 == 双共轭匹配 GT,max（<0.5dB）
        gchk = pl["checks"]["gain_peak_matches_conj_match"]
        assert gchk["ok"] is True
        assert abs(gchk["peak_gain_db"] - gchk["gt_max_db"]) < 0.5

    def test_plausibility_skips_gain_for_unstable_device(self):
        dev = self._device()
        spa_unstable = ac.HybridPiModel(gm_s=0.08, rds_ohm=200.0, cgs_f=2e-12,
                                        cds_f=1.2e-12, cgd_f=0.05e-12,
                                        rg_ohm=3.0).to_sparams(F_PA)
        assert not ac.stability_margins(spa_unstable).unconditionally_stable
        scan = ac.load_pull_scan(dev, F_PA, n_grid=61, backoff_db=(1.0, 2.0),
                                 sparams=spa_unstable)
        pl = ac.load_pull_plausibility(scan, sparams=spa_unstable)
        chk = pl["checks"]["gain_peak_matches_conj_match"]
        assert chk["status"] == "skipped"

    def test_scan_to_dict_jsonable(self):
        import json

        scan = ac.load_pull_scan(self._device(), F_PA, n_grid=41, backoff_db=(2.0,))
        text = json.dumps(scan.to_dict(max_grid=20))
        assert "contours" in text and "optimum" in text
