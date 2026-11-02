"""param_vf 参数化 VF 宏模型邻域插值（T-N15，aurora_n W2）单测。

五验收映射：
    ① 合成参数族（RL 负载反射族，N=8）邻域预测对真值 RMSE 门（预声明
      REL_RMSE_GATE=5e-2）+ 不劣对照（内点插值 < nearest-neighbor 基线；
      训练点回代与逐点直接拟合逐位一致）；
    ② 外推判据=新参数点在样本凸包外 → extrapolation_warn（warn 档不阻断
      预测，T-N3 band_edge_verdict 同款语义）；
    ③ 确定性钉=同配置两跑 fit/predict/verdict 逐位一致（全链闭式零随机，
      seed 为占位契约位）；
    ④ 负例=有效样本 N<3 / params 与 bounds 维度不匹配 → 显式 ValueError；
    ⑤ 既有路径零改动=本文件只触新模块（邻接回归由 pole_residue/macromodel/
      surrogate 定向批独立承担）。
裁判纪律（#118）：合成真值一律用与被测实现无共享代码路径的独立闭式公式
（RL 负载反射 Möbius 族 / 基内极点仿射族），不经 fit_residues/evaluate。

门值预声明依据（runs/aurora_n/w2_tn15/probe_calib.py 开发期探针）：内点
邻域插值误差=样本曲线仿射组合的曲率误差（等效核），实测相对 RMSE
3.4e-3..7.5e-3；逐点直接拟合地板 ~1e-5 量级。门取 5e-2 留 ≥5× 余量；
"与逐点直接拟合对照不劣"由 interp<nearest 与训练点逐位回代双钉承担
（地板本身 ~1e-5，任何"逐位不劣于地板"式断言在稀疏 8 样本上不成立，
以对照基线+回代等价作可执行口径）。
"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 三批单源化）。"""
    yield


from rfauto.optimization.surrogate import (
    ParamVFSurrogate,
    convex_hull_verdict,
    local_linear_weights,
    surrogate_registry,
)
from rfauto.optimization.surrogate.pole_residue import (
    default_pole_basis,
    evaluate_pole_residue,
    fit_residues,
    theta_to_model,
)

# ─── 合成参数族（#118 独立闭式，与被测实现零共享代码路径） ────────────────────

F_LO_HZ = 0.1e9
F_HI_HZ = 6.0e9
N_FREQ = 81
Z0_OHM = 50.0
#: 内点邻域预测相对 RMSE 门（预声明，依据见模块 docstring）。
REL_RMSE_GATE = 5e-2

RL_SAMPLES = [(32.0, 9.0), (45.0, 14.5), (58.0, 8.5), (66.0, 13.0),
              (38.0, 15.5), (52.0, 10.5), (30.0, 12.5), (62.0, 15.0)]
RL_BOUNDS = {"r_ohm": (28.0, 70.0), "l_nh": (8.0, 16.0)}
RL_INTERIOR = [(44.0, 12.0), (55.0, 11.5), (40.0, 14.0)]
RL_EXTRAP = (85.0, 12.0)  # r_ohm 超出 bbox ⊂ 凸包外（判据无歧义点）


def _s11_rl(freq_hz: np.ndarray, r_ohm: float, l_nh: float) -> np.ndarray:
    """独立闭式：RL 串联负载反射系数 S11=(ZL−Z0)/(ZL+Z0)，ZL=R+jωL。"""
    s = 2.0j * np.pi * np.asarray(freq_hz, dtype=float)
    zl = r_ohm + s * (l_nh * 1e-9)
    return (zl - Z0_OHM) / (zl + Z0_OHM)


def _freq_grid() -> np.ndarray:
    return np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ)


def _rl_samples() -> list[dict]:
    freq = _freq_grid()
    return [{"params": {"r_ohm": r, "l_nh": l_nh},
             "metrics": {"s11_curve": _s11_rl(freq, r, l_nh)}}
            for r, l_nh in RL_SAMPLES]


def _rl_config(**overrides) -> dict:
    cfg = {"bounds": RL_BOUNDS, "freq_grid_ghz": (0.1, 6.0), "n_freq": N_FREQ,
           "n_real_poles": 2, "n_cmplx_pairs": 3}
    cfg.update(overrides)
    return cfg


def _rel_rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b))
                 / np.linalg.norm(b))


# ─── 邻域等效核：local_linear_weights ────────────────────────────────────────


class TestLocalLinearWeights:
    def test_weights_sum_to_one_and_affine_exact(self):
        """Σw̃=1；对仿射数据逐位精确回收（等效核的定义性质）。"""
        pts = np.array([[0.0], [0.25], [0.6], [0.9]])
        data = np.column_stack([3.0 * pts[:, 0] + 2.0, np.ones(4) * -1.5])
        for q in (0.1, 0.5, 0.87):
            w, idx, exact = local_linear_weights(pts, np.array([q]), 3)
            assert not exact
            assert w.sum() == pytest.approx(1.0, abs=1e-12)
            assert (w >= 0).sum() >= 1  # 权可含负（局部线性），和恒为 1
            assert np.allclose(data[idx].T @ w[idx], [3.0 * q + 2.0, -1.5],
                               atol=1e-12)

    def test_exact_hit_branch(self):
        """查询点=样本点 → 独占权 1（训练点回代逐位一致的基础）。"""
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        w, idx, exact = local_linear_weights(pts, np.array([1.0, 0.0]), 4)
        assert exact and idx[0] == 1
        assert w[1] == 1.0 and w.sum() == 1.0

    def test_k_capped_at_n(self):
        pts = np.array([[0.0], [1.0], [2.0]])
        w, idx, _ = local_linear_weights(pts, np.array([0.5]), 99)
        assert len(idx) == 3 and w.sum() == pytest.approx(1.0, abs=1e-12)

    def test_negatives(self):
        pts = np.array([[0.0], [1.0]])
        with pytest.raises(ValueError, match="维度"):
            local_linear_weights(pts, np.array([0.0, 0.0]), 2)
        with pytest.raises(ValueError, match="power"):
            local_linear_weights(pts, np.array([0.5]), 2, power=0.0)
        with pytest.raises(ValueError, match="k_neighbors"):
            local_linear_weights(pts, np.array([0.5]), 0)


# ─── 凸包外推判据：convex_hull_verdict ───────────────────────────────────────


class TestConvexHullVerdict:
    def test_2d_inside_outside_boundary(self):
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        inside = convex_hull_verdict(pts, np.array([0.2, 0.2]))
        assert inside["param_extrapolation"] == "ok"
        assert inside["hull_kind"] == "convex_hull" and inside["margin"] <= 0
        outside = convex_hull_verdict(pts, np.array([0.9, 0.9]))
        assert outside["param_extrapolation"] == "extrapolation_warn"
        assert outside["margin"] > 0
        boundary = convex_hull_verdict(pts, np.array([0.5, 0.5]))
        assert boundary["param_extrapolation"] == "ok"  # 边界=凸组合，合法内插

    def test_1d_interval(self):
        pts = np.array([[0.5], [2.5]])
        ok = convex_hull_verdict(pts, np.array([1.0]))
        assert ok["hull_kind"] == "interval" and ok["param_extrapolation"] == "ok"
        warn = convex_hull_verdict(pts, np.array([3.0]))
        assert warn["param_extrapolation"] == "extrapolation_warn"
        assert warn["margin"] == pytest.approx(0.5)

    def test_degenerate_collinear_bbox_fallback(self):
        pts = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])  # 共线，QhullError
        v = convex_hull_verdict(pts, np.array([0.5, 0.5]))
        assert v["hull_kind"] == "bbox_fallback" and v["param_extrapolation"] == "ok"
        w = convex_hull_verdict(pts, np.array([0.5, 3.0]))
        assert w["hull_kind"] == "bbox_fallback"
        assert w["param_extrapolation"] == "extrapolation_warn"

    def test_negatives(self):
        with pytest.raises(ValueError, match="tol"):
            convex_hull_verdict(np.array([[0.0], [1.0]]), np.array([0.5]),
                                tol=0.0)
        with pytest.raises(ValueError, match="维度"):
            convex_hull_verdict(np.array([[0.0], [1.0]]), np.array([0.5, 0.5]))


# ─── ParamVFSurrogate：五验收主面 ────────────────────────────────────────────


class TestParamVFSurrogateRLFamily:
    def test_fit_info_and_readout_passivity(self):
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(_rl_samples())
        assert info["kind"] == "vf_parametric"
        assert info["n_curves"] == 8 and info["n_skipped"] == 0
        assert info["n_param_dims"] == 2 and info["n_poles"] == 8
        assert info["k_eff"] == 4
        assert info["max_fit_rms"] <= 1e-3  # 固定基读出逐样本 RMS 远低于门
        assert info["passivity"]["passive"] is True  # RL 族读出曲线物理无源
        assert info["hull_kind"] == "convex_hull"

    def test_interior_rmse_gate_and_not_worse_control(self):
        """验收①：内点 RMSE ≤ 预声明门，且逐点优于 nearest-neighbor 基线。"""
        m = ParamVFSurrogate(_rl_config())
        m.fit(_rl_samples())
        freq = _freq_grid()
        for r, l_nh in RL_INTERIOR:
            params = {"r_ohm": r, "l_nh": l_nh}
            pred = m.predict_curve(params)
            truth = _s11_rl(freq, r, l_nh)
            rel = _rel_rmse(pred, truth)
            assert rel <= REL_RMSE_GATE, f"{params} rel_rmse={rel:.3e}"
            # 不劣对照：邻域插值 < 最近样本基线（同裁判、同真值）
            _, idx, exact = local_linear_weights(
                m._sample_x, m._norm_params(params), m._k_eff, m.idw_power)
            assert not exact
            nn_model = theta_to_model(m._theta_table[idx[0]], m._poles)
            nn = evaluate_pole_residue(freq, m._poles, nn_model["residues"],
                                       nn_model["d"], nn_model["e"])
            assert rel < _rel_rmse(nn, truth), (
                f"{params} interp={rel:.3e} 不得劣于 nearest="
                f"{_rel_rmse(nn, truth):.3e}")

    def test_extrapolation_warn(self):
        """验收②：凸包外 → warn 档；预测不阻断（曲线有限可复核）。"""
        m = ParamVFSurrogate(_rl_config())
        m.fit(_rl_samples())
        params = {"r_ohm": RL_EXTRAP[0], "l_nh": RL_EXTRAP[1]}
        v = m.param_extrapolation_verdict(params)
        assert v["param_extrapolation"] == "extrapolation_warn"
        assert v["hull_kind"] == "convex_hull" and v["margin"] > 0
        combo = m.predict_curve_with_verdict(params)
        assert np.isfinite(combo["curve"]).all()
        assert combo["param_extrapolation"]["param_extrapolation"] == (
            "extrapolation_warn")
        # 内点对照：ok 档
        assert m.param_extrapolation_verdict(
            {"r_ohm": 44.0, "l_nh": 12.0})["param_extrapolation"] == "ok"
        assert m.predict({"r_ohm": 44.0, "l_nh": 12.0})[
            "param_extrapolation"] == "ok"
        assert m.predict(params)["param_extrapolation"] == "extrapolation_warn"

    def test_sample_reproduction_bitwise(self):
        """不劣对照的逐位形态：训练点回代 == 逐点直接拟合（kernel 单源）。"""
        m = ParamVFSurrogate(_rl_config())
        m.fit(_rl_samples())
        freq = _freq_grid()
        for r, l_nh in RL_SAMPLES[:3]:
            got = m.predict_curve({"r_ohm": r, "l_nh": l_nh})
            direct = fit_residues(freq, _s11_rl(freq, r, l_nh), m._poles)
            want = evaluate_pole_residue(freq, m._poles, direct["residues"],
                                         direct["d"], direct["e"])
            assert np.array_equal(got, want), f"({r},{l_nh}) 回代非逐位一致"

    def test_determinism_bitwise(self):
        """验收③：同配置同数据两跑，fit 表/预测/判据逐位一致（零随机）。"""
        samples = _rl_samples()
        ma, mb = ParamVFSurrogate(_rl_config()), ParamVFSurrogate(_rl_config())
        ia, ib = ma.fit(samples), mb.fit(samples)
        assert np.array_equal(ma._theta_table, mb._theta_table)
        assert ia["max_fit_rms"] == ib["max_fit_rms"]
        for params in ({"r_ohm": 44.0, "l_nh": 12.0}, {"r_ohm": 61.0, "l_nh": 9.5}):
            assert np.array_equal(ma.predict_curve(params),
                                  mb.predict_curve(params))
            assert (ma.param_extrapolation_verdict(params)
                    == mb.param_extrapolation_verdict(params))

    def test_seed_is_noop_placeholder(self):
        """seed 为契约占位位：不同 seed 输出逐位一致（docstring 口径钉）。"""
        samples = _rl_samples()
        ma = ParamVFSurrogate(_rl_config(seed=1))
        mb = ParamVFSurrogate(_rl_config(seed=999))
        ma.fit(samples)
        mb.fit(samples)
        assert np.array_equal(ma._theta_table, mb._theta_table)
        assert np.array_equal(ma.predict_curve({"r_ohm": 44.0, "l_nh": 12.0}),
                              mb.predict_curve({"r_ohm": 44.0, "l_nh": 12.0}))


class TestParamVFSurrogateNegatives:
    """验收④：N<3 / 参数维度不匹配显式报错。"""

    def test_n_lt_3(self):
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(ValueError, match=r"有效曲线样本 2 < 3"):
            m.fit(_rl_samples()[:2])

    def test_skipped_curves_collapse_below_3(self):
        samples = _rl_samples()
        for i in range(6):  # 8 行里 6 行曲线缺失 → 只剩 2 有效
            samples[i] = {"params": dict(samples[i]["params"]),
                          "metrics": {}}
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(ValueError, match="跳过 6 行"):
            m.fit(samples)

    def test_curve_length_mismatch_skipped(self):
        freq = _freq_grid()[:40]
        samples = _rl_samples()
        samples[0]["metrics"]["s11_curve"] = _s11_rl(freq, *RL_SAMPLES[0])
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(samples)
        assert info["n_curves"] == 7 and info["n_skipped"] == 1

    def test_fit_param_dim_mismatch(self):
        samples = _rl_samples()
        del samples[2]["params"]["l_nh"]  # 缺键
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(ValueError, match="键集与 bounds 不匹配"):
            m.fit(samples)
        samples = _rl_samples()
        samples[2]["params"]["extra"] = 1.0  # 多键
        with pytest.raises(ValueError, match="多="):
            m.fit(samples)
        samples = _rl_samples()
        samples[2]["params"]["l_nh"] = "bad"  # 不可转 float
        with pytest.raises(ValueError, match="不可转 float"):
            m.fit(samples)

    def test_predict_param_dim_mismatch(self):
        m = ParamVFSurrogate(_rl_config())
        m.fit(_rl_samples())
        with pytest.raises(ValueError, match="键集与 bounds 不匹配"):
            m.predict_curve({"r_ohm": 44.0})
        with pytest.raises(ValueError, match="多="):
            m.predict_curve({"r_ohm": 44.0, "l_nh": 12.0, "x": 0.0})
        with pytest.raises(ValueError, match="键集与 bounds 不匹配"):
            m.param_extrapolation_verdict({"r_ohm": 44.0})

    def test_predict_before_fit(self):
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(RuntimeError, match="先 fit"):
            m.predict_curve({"r_ohm": 44.0, "l_nh": 12.0})

    def test_config_validation(self):
        with pytest.raises(ValueError, match="bounds"):
            ParamVFSurrogate({"freq_grid_ghz": (0.1, 6.0)})
        with pytest.raises(ValueError, match="low < high"):
            ParamVFSurrogate(_rl_config(bounds={"r_ohm": (70.0, 28.0),
                                                "l_nh": (8.0, 16.0)}))
        with pytest.raises(ValueError, match="freq_grid_ghz"):
            ParamVFSurrogate(_rl_config(freq_grid_ghz=(6.0, 0.1)))
        with pytest.raises(ValueError, match="不足以支撑"):
            ParamVFSurrogate(_rl_config(n_freq=10))  # 8 极点需 ≥12


# ─── 仿射族精确性钉（等效核的解析性质） + 注册键/契约面 ───────────────────────


class TestAffineFamilyAndContract:
    def test_affine_family_exact(self):
        """基内极点+留数线性于参数：内点预测回收真值（affine 精确性钉）。

        真值族 S11(f;g) = (r0+g·r1)/(s−p*) + d0（p*=固定基内实极点，独立
        公式直算）——theta(g) 仿射 → 局部线性插值逐位精确（机器精度带）。
        """
        basis = default_pole_basis(1e9, 5e9, 1, 1)
        p_star = basis[0]
        freq = np.linspace(1e9, 5e9, 33)
        s = 2.0j * np.pi * freq
        r0, r1, d0 = 3.0e8, 2.0e9, 0.25

        def truth(g: float) -> np.ndarray:
            return (r0 + g * r1) / (s - p_star) + d0  # 独立公式（#118）

        gs = [0.05, 0.3, 0.55, 0.8]
        samples = [{"params": {"g": g}, "metrics": {"s11_curve": truth(g)}}
                   for g in gs]
        m = ParamVFSurrogate({"bounds": {"g": (0.0, 1.0)},
                              "freq_grid_ghz": (1.0, 5.0), "n_freq": 33,
                              "n_real_poles": 1, "n_cmplx_pairs": 1})
        m.fit(samples)
        g_q = 0.425  # 0.3 与 0.55 之间（凸包内非样本点）
        rel = _rel_rmse(m.predict_curve({"g": g_q}), truth(g_q))
        assert rel <= 1e-8, f"仿射族内点预测 rel={rel:.2e}（应机器精度带）"

    def test_registry_key(self):
        """新注册键入表（同 pole_residue 先例的成员断言，无计数棘轮）。"""
        assert "vf_parametric" in surrogate_registry.available()

    def test_predict_scalar_keys_and_uncertainty(self):
        m = ParamVFSurrogate(_rl_config())
        m.fit(_rl_samples())
        out = m.predict({"r_ohm": 44.0, "l_nh": 12.0})
        assert set(out) == {"s11_db_max_in_band", "s11_db_min_in_band",
                            "param_extrapolation"}
        assert np.isfinite(out["s11_db_max_in_band"])
        assert np.isfinite(out["s11_db_min_in_band"])
        assert out["param_extrapolation"] in ("ok", "extrapolation_warn")
        assert m.uncertainty({"r_ohm": 44.0, "l_nh": 12.0}) is None
