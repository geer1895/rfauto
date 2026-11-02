"""T-N3 pole_residue 判据面扩展单测：带边过冲守卫 + 参数-曲线一致性。

判据面不改拟合——fit_residues / PoleResidueSurrogate.fit 路径零改动
（改动前后全量 fit 输出逐位等价钉在 runs/aurora_n/wave1_b/
baseline_before.json vs baseline_after.json，repr 级比对脚本同目录）。

裁判纪律（#118）：合成对照全部用与被测实现无共享代码路径的独立闭式
公式构造地面真相——带边趋势门用"dB 域严格线性"曲线（excursion 闭式
零）与"带外整体 ×3"（excursion 闭式=20·log10(3)）两态；α·S 一致性用
LS 标量回收（α 闭式真值）。负例=超宽带外推过冲必警、非缩放冲突必
port_scale_like=False；确定性=同输入 verdict 逐位（AGENTS 7）。
"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 三批单源化）。"""
    yield


F_LO, F_HI = 1.0e9, 5.0e9
Z0 = 50.0


def _extended_grid() -> np.ndarray:
    return np.linspace(0.8e9, 5.3e9, 97)


def _linear_db_curve(freq_hz: np.ndarray) -> np.ndarray:
    """独立闭式：|S| dB 域严格线性（带外延续带内趋势的理想光滑延拓）。"""
    amp_db = -10.0 + 4.0 * (freq_hz - 0.8e9) / 4.5e9
    return (10.0 ** (amp_db / 20.0)) * np.exp(
        1.0j * np.linspace(0.0, 3.0, len(freq_hz)))


# ─── 带边过冲守卫（阈值门 + 负例 + 确定性） ──────────────────────────────────


class TestBandEdgeVerdict:
    def test_linear_db_trend_excursion_zero_ok(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        curve = _linear_db_curve(freq)
        v = band_edge_verdict(freq, curve, F_LO, F_HI)
        assert v["band_edge"] == "ok"
        assert v["excursion_db"] <= 1e-8  # 闭式：严格线性 → 偏离=机器零
        assert v["threshold_db"] == 3.0
        assert v["n_out_of_band"] > 0
        assert v["passive_out_of_band"] is True
        assert v["deep_extrapolation"] is True  # 0.8-0.9GHz 落近带窗外

    def test_overshoot_warn_closed_form_20log10_3(self):
        """负例：带外整体 ×3 → verdict=extrapolation_warn，excursion
        闭式=20·log10(3)≈9.5424dB（近带窗内逐点恰差该值）。"""
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        curve = _linear_db_curve(freq)
        hostile = curve.copy()
        hostile[freq > F_HI] *= 3.0
        v = band_edge_verdict(freq, hostile, F_LO, F_HI)
        assert v["band_edge"] == "extrapolation_warn"
        assert v["excursion_db"] == pytest.approx(20.0 * np.log10(3.0),
                                                  abs=1e-6)

    def test_passivity_out_of_band_blowout(self):
        """带外无源性旁证（复用 passivity_verdict 单源）：×4 过冲 →
        passive_out_of_band=False 且 σmax 闭式可复核。"""
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        curve = _linear_db_curve(freq)
        blow = curve.copy()
        blow[freq > F_HI] *= 4.0
        v = band_edge_verdict(freq, blow, F_LO, F_HI)
        assert v["passive_out_of_band"] is False
        oob_max = float(np.max(np.abs(curve[freq > F_HI]))) * 4.0
        assert v["sigma_max_out_of_band"] == pytest.approx(oob_max, rel=1e-9)
        assert v["sigma_max_out_of_band"] > 1.0

    def test_no_out_of_band_points_honest_ok(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = np.linspace(F_LO, F_HI, 81)
        curve = _linear_db_curve(freq)
        v = band_edge_verdict(freq, curve, F_LO, F_HI)
        assert v["band_edge"] == "ok"
        assert v["n_out_of_band"] == 0
        assert v["passive_out_of_band"] is None
        assert v["deep_extrapolation"] is False

    def test_batch_input_worst_member_aggregates(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        smooth = _linear_db_curve(freq)
        hostile = smooth.copy()
        hostile[freq > F_HI] *= 3.0
        v = band_edge_verdict(freq, np.vstack([smooth, hostile]),
                              F_LO, F_HI)
        assert v["band_edge"] == "extrapolation_warn"
        assert len(v["per_member_excursion_db"]) == 2
        assert v["excursion_db"] == max(v["per_member_excursion_db"])
        # 成员 0 自身仍是 ok 档（per-member 明细透出不吞没）
        assert v["per_member_excursion_db"][0] <= 1e-8

    def test_matrix_stack_rejected_explicitly(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        curve = _linear_db_curve(freq)
        with pytest.raises(ValueError, match="多端口矩阵栈不支持"):
            band_edge_verdict(freq, curve[:, None, None] * np.ones(
                (1, 2, 2), dtype=complex), F_LO, F_HI)

    def test_determinism_bitwise(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = _extended_grid()
        curve = _linear_db_curve(freq)
        v1 = band_edge_verdict(freq, curve, F_LO, F_HI)
        v2 = band_edge_verdict(freq, curve, F_LO, F_HI)
        assert v1 == v2  # 全键含浮点逐位相等

    def test_insufficient_in_band_raises(self):
        from rfauto.optimization.surrogate.pole_residue import band_edge_verdict

        freq = np.linspace(F_LO, F_HI, 8)
        with pytest.raises(ValueError, match="n_trend"):
            band_edge_verdict(freq, _linear_db_curve(freq), F_LO, F_HI,
                              n_trend=16)


class TestSurrogateBandEdgeMethod:
    def _fit_rl_surrogate(self):
        from rfauto.optimization.surrogate.pole_residue import PoleResidueSurrogate

        freq = np.linspace(F_LO, F_HI, 81)

        def rl(r: float, l_nh: float) -> np.ndarray:
            z = r + 2.0j * np.pi * freq * l_nh * 1e-9
            return (z - Z0) / (z + Z0)

        anchors = [{"params": {"r_ohm": r, "l_nh": l_nh},
                    "metrics": {"s11_curve": rl(r, l_nh)}}
                   for r, l_nh in [(5, 1), (5, 3), (10, 2), (15, 1), (15, 3),
                                (8, 2.6)]]
        model = PoleResidueSurrogate(config={
            "bounds": {"r_ohm": [5.0, 15.0], "l_nh": [1.0, 3.0]},
            "freq_grid_ghz": (1.0, 5.0), "n_freq": 81, "head": "ridge"})
        model.fit(anchors)
        return model

    def test_smooth_family_ok_and_verdict_deterministic(self):
        """光滑 RL 族：带边延拓 ok（excursion 小）；verdict 两跑逐位
        （判据面只读 predict_curve，不触拟合状态）。"""
        model = self._fit_rl_surrogate()
        params = {"r_ohm": 10.0, "l_nh": 2.0}
        v = model.band_edge_verdict(params)
        assert v["band_edge"] == "ok"
        assert v["excursion_db"] < 0.5
        assert v["passive_out_of_band"] is True
        v2 = model.band_edge_verdict(params)
        assert v == v2

    def test_unfitted_raises(self):
        from rfauto.optimization.surrogate.pole_residue import PoleResidueSurrogate

        model = PoleResidueSurrogate(config={
            "bounds": {"x": [0.0, 1.0]}, "freq_grid_ghz": (1.0, 5.0)})
        with pytest.raises(RuntimeError, match="先 fit"):
            model.band_edge_verdict({"x": 0.5})

    def test_overshoot_curve_propagates_warn(self):
        """方法面负例（预测面注入闭式过冲曲线——判据链路 warn 透传）。"""
        model = self._fit_rl_surrogate()
        n_ext = 111

        def hostile(_params, freq_ghz=None):
            f = (np.linspace(F_LO, F_HI, model.n_freq) if freq_ghz is None
                 else np.asarray(freq_ghz, dtype=float) * 1e9)
            smooth = (0.3 * np.exp(1.0j * np.linspace(0, 2, len(f)))
                      * (f / F_LO))
            return np.where(f > F_HI, 3.0 * smooth, smooth)

        model.predict_curve = hostile  # 仅测试实例（判据链路注入）
        v = model.band_edge_verdict({"r_ohm": 10.0, "l_nh": 2.0},
                                    ext_frac=0.10, n_ext=n_ext)
        assert v["band_edge"] == "extrapolation_warn"


# ─── 参数-曲线一致性判据（port_scale α·S 语义可判定面） ──────────────────────


def _ramp(n: int = 40) -> np.ndarray:
    return np.exp(1.0j * np.linspace(0.0, 2.0, n))


class TestParamConflictVerdict:
    def test_scale_conflict_detected_alpha_recovered(self):
        """闭式回收钉：α·S 冲突检出且 LS 回收 α=0.6（真值精确）。"""
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c = _ramp()
        p = {"r": 10.0, "l": 2.0}
        samples = [
            {"params": p, "metrics": {"s11_curve": c}},
            {"params": dict(p), "metrics": {"s11_curve": 0.6 * c}},
            {"params": {"r": 12.0, "l": 2.0},
             "metrics": {"s11_curve": 0.9 * c}},
        ]
        v = param_conflict_verdict(samples)
        assert v["verdict"] == "conflict"
        assert v["n_conflict_pairs"] == 1
        assert v["port_scale_like_all"] is True
        conflict = v["conflicts"][0]
        assert conflict["alpha"] == pytest.approx(0.6, rel=1e-12)
        assert conflict["port_scale_like"] is True
        assert conflict["indices"] == [0, 1]
        assert v["n_param_groups"] == 2
        assert v["n_curve_samples"] == 3

    def test_nonscale_conflict_flagged_honestly(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c1, c2 = _ramp(), np.exp(1.0j * np.linspace(0.0, 4.0, 40))
        p = {"r": 10.0}
        v = param_conflict_verdict([
            {"params": p, "metrics": {"s11_curve": c1}},
            {"params": dict(p), "metrics": {"s11_curve": c2}}])
        assert v["verdict"] == "conflict"
        assert v["conflicts"][0]["port_scale_like"] is False
        assert v["port_scale_like_all"] is False
        assert v["conflicts"][0]["alpha"] is not None  # LS 照常回收供诊断

    def test_alpha_above_one_not_scale_like(self):
        """α>1 越出 (0,1] 语义（放大不属 port_scale 匹配衰减器族）。"""
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c = _ramp()
        v = param_conflict_verdict([
            {"params": {"r": 1.0}, "metrics": {"s11_curve": c}},
            {"params": {"r": 1.0}, "metrics": {"s11_curve": 1.5 * c}}])
        assert v["verdict"] == "conflict"
        assert v["conflicts"][0]["alpha"] == pytest.approx(1.5)
        assert v["conflicts"][0]["port_scale_like"] is False

    def test_clean_distinct_params_consistent(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c = _ramp()
        v = param_conflict_verdict([
            {"params": {"r": 1.0}, "metrics": {"s11_curve": c}},
            {"params": {"r": 2.0}, "metrics": {"s11_curve": 0.5 * c}}])
        assert v["verdict"] == "consistent"
        assert v["n_conflict_pairs"] == 0
        assert v["port_scale_like_all"] is None

    def test_noise_within_rtol_consistent(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        rng = np.random.default_rng(7)
        c = _ramp()
        noisy = c + 1e-9 * (rng.normal(size=len(c))
                            + 1.0j * rng.normal(size=len(c)))
        v = param_conflict_verdict([
            {"params": {"r": 1.0}, "metrics": {"s11_curve": c}},
            {"params": {"r": 1.0}, "metrics": {"s11_curve": noisy}}])
        assert v["verdict"] == "consistent"

    def test_shape_mismatch_recorded_not_crash(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        v = param_conflict_verdict([
            {"params": {"r": 1.0}, "metrics": {"s11_curve": _ramp(40)}},
            {"params": {"r": 1.0}, "metrics": {"s11_curve": _ramp(41)}}])
        assert v["verdict"] == "conflict"
        assert v["conflicts"][0]["reason"] == "shape_mismatch"

    def test_missing_curve_and_nonfloat_params(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c = _ramp()
        # 缺曲线键样本只计数不参与
        v = param_conflict_verdict([
            {"params": {"r": 1.0}, "metrics": {"s11_curve": c}},
            {"params": {"r": 1.0}, "metrics": {"other": 1.0}}])
        assert v["n_curve_samples"] == 1
        assert v["verdict"] == "consistent"
        with pytest.raises(ValueError, match="float"):
            param_conflict_verdict([
                {"params": {"r": "bad"}, "metrics": {"s11_curve": c}}])

    def test_determinism_bitwise(self):
        from rfauto.optimization.surrogate.pole_residue import param_conflict_verdict

        c = _ramp()
        samples = [
            {"params": {"r": 10.0}, "metrics": {"s11_curve": c}},
            {"params": {"r": 10.0}, "metrics": {"s11_curve": 0.6 * c}}]
        assert param_conflict_verdict(samples) == param_conflict_verdict(
            samples)


# ─── 拟合路径零改动钉 ─────────────────────────────────────────────────────────


class TestFitUntouched:
    def test_fit_twice_bitwise_and_weight_key_still_ignored(self):
        """fit 两跑逐位（确定性）+ 样本带 VIRTUAL_WEIGHT_KEY 仍被 fit 忽略
        （W4-4 接口注记在 T-N2 后依然为真：加权消费面=poly_ridge/nn，
        pole_residue 侧不扩）。改动前后全量等价钉见 runs/aurora_n/
        wave1_b/baseline_before.json vs baseline_after.json。"""
        from rfauto.optimization.surrogate import VIRTUAL_WEIGHT_KEY
        from rfauto.optimization.surrogate.pole_residue import PoleResidueSurrogate

        freq = np.linspace(F_LO, F_HI, 81)

        def rl(r: float, l_nh: float) -> np.ndarray:
            z = r + 2.0j * np.pi * freq * l_nh * 1e-9
            return (z - Z0) / (z + Z0)

        anchors = [{"params": {"r_ohm": r, "l_nh": l_nh},
                    "metrics": {"s11_curve": rl(r, l_nh)}}
                   for r, l_nh in [(5, 1), (5, 3), (10, 2), (15, 1), (15, 3),
                                (8, 2.6)]]
        cfg = {"bounds": {"r_ohm": [5.0, 15.0], "l_nh": [1.0, 3.0]},
               "freq_grid_ghz": (1.0, 5.0), "n_freq": 81, "head": "ridge"}
        m1 = PoleResidueSurrogate(config=dict(cfg))
        m2 = PoleResidueSurrogate(config=dict(cfg))
        info1 = m1.fit(anchors)
        info2 = m2.fit(anchors)
        assert info1 == info2
        assert np.array_equal(
            m1._theta_of({"r_ohm": 9.0, "l_nh": 2.2}),
            m2._theta_of({"r_ohm": 9.0, "l_nh": 2.2}))
        tagged = [dict(s, **{VIRTUAL_WEIGHT_KEY: 0.3}) for s in anchors]
        m3 = PoleResidueSurrogate(config=dict(cfg))
        info3 = m3.fit(tagged)
        assert info3 == info1
        assert np.array_equal(
            m1._theta_of({"r_ohm": 9.0, "l_nh": 2.2}),
            m3._theta_of({"r_ohm": 9.0, "l_nh": 2.2}))

    def test_closed_form_pole_recovery_end_to_end(self):
        """#340 同款注入→回收：已知极点-留数闭式曲线 → fit_residues 回收
        → 回收模型再过带边判据（判据消费拟合产物全链确定性）。"""
        from rfauto.optimization.surrogate.pole_residue import (
            band_edge_verdict,
            default_pole_basis,
            evaluate_pole_residue,
            fit_residues,
        )

        basis = default_pole_basis(F_LO, F_HI, 2, 2)
        truth = {0: 3.0e8 + 0.0j, 2: 1.0e8 + 5.0e7j, 3: 1.0e8 - 5.0e7j}
        freq_in = np.linspace(F_LO, F_HI, 81)

        def raw(freq_hz: np.ndarray) -> np.ndarray:
            s = 2.0j * np.pi * freq_hz
            out = sum(r / (s - basis[k]) for k, r in truth.items())
            return out + 0.25 + 2.0e-11 * s

        model = fit_residues(freq_in, raw(freq_in), basis)
        assert model["rms"] <= 1e-12
        # 回收模型外推到扩展栅格 → 判据（独立公式为裁判，非共享路径）
        freq_ext = _extended_grid()
        curve_rec = evaluate_pole_residue(freq_ext, model["poles"],
                                          model["residues"], model["d"],
                                          model["e"])
        curve_true = raw(freq_ext)
        v_rec = band_edge_verdict(freq_ext, curve_rec, F_LO, F_HI)
        v_true = band_edge_verdict(freq_ext, curve_true, F_LO, F_HI)
        assert v_true["band_edge"] == "ok"
        assert v_rec["band_edge"] == v_true["band_edge"]
        assert v_rec["excursion_db"] == pytest.approx(
            v_true["excursion_db"], abs=1e-6)
