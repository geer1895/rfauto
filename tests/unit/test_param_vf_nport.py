"""param_vf 多端口增量（aurora_p D2；vf_parametric 键零新键扩展）单测。

验收映射（任务书冻结判据 A-E，门值先探针实测后冻结——冻结后不改）：
    A 已知真值回收（3 极点 2 端口互易仿射族）：真值极点独立公式重算与
      default_pole_basis 逐位相等（"极点回收"语义=基内已知值）；读出
      留数/d/e 对构造常数的回收相对误差 ≤ RECOVERY_GATE=1e-8（探针实测
      0.0，机器精度带取 1e-8 稳）；内点预测全矩阵相对 RMSE ≤1e-8（实测
      6.1e-16，仿射精确性钉）。
    B 参数族泛化（串联 RL 两端口闭式族，#118 独立闭式真值
      S11=Z/(2Z0+Z)、S21=2Z0/(2Z0+Z)）：新 θ 内插全矩阵相对 RMSE ≤
      RL_GATE=5e-2（探针实测 worst 6.3e-3，≥8× 余量；与 v1
      test_param_vf.REL_RMSE_GATE 同值同依据）+ 不劣对照（< nearest）。
    C 单端口既有行为零变化：n_ports=1 显式 config 与缺省 config 输出
      逐位一致；既有 test_param_vf.py 全绿为独立证据（本席零改动）。
    D 互易按构造：多 θ 点 max|S−Sᵀ| ≤ RECIP_GATE=1e-12（按构造应为
      逐位 0，双钉）；非互易输入对称化+如实报告（不静默不拒绝）。
    E 确定性：同配置同数据两跑 fit 表/predict_matrix 判据逐位一致；
      无源性 verdict 单源逐成员消费聚合（含 active 负例 passive=False）。
裁判纪律（#118）：合成真值一律独立闭式公式（基内极点仿射族 / 串联 RL
两端口 ABCD 推导），不经 fit_residues/evaluate_pole_residue 构造真值
（theta_to_model 仅作布局解包，不参与真值生成）。
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
    local_linear_weights,
    surrogate_registry,
)
from rfauto.optimization.surrogate.pole_residue import (
    default_pole_basis,
    theta_to_model,
)

# ─── 常量与冻结门（探针 runs/aurora_p/d2/probe_gates.py 实测依据） ───────────

F_LO_HZ = 1.0e9
F_HI_HZ = 6.0e9
N_FREQ = 61
ZETA = 0.7
Z0_OHM = 50.0
#: 验收 A：回收相对误差门（实测 0.0/6.1e-16——机器精度带）。
RECOVERY_GATE = 1e-8
#: 验收 B：串联 RL 两端口新 θ 内插全矩阵相对 RMSE 门（实测 worst 6.3e-3）。
RL_GATE = 5e-2
#: 验收 D：互易对称门（按构造逐位 0，门为浮点冗余位）。
RECIP_GATE = 1e-12

#: 仿射族真值常量（独立于被测实现构造：留数对 g 仿射、d/e 常数）。
_AFF_A = {(0, 0): [0.8e9 + 0.2e9j, 0.35e9 - 0.1e9j, 0.5e9 + 0.3e9j],
          (0, 1): [0.3e9 + 0.15e9j, 0.9e9 - 0.25e9j, 0.42e9 + 0.05e9j],
          (1, 1): [0.25e9 - 0.05e9j, 0.33e9 + 0.12e9j, 0.7e9 + 0.2e9j]}
_AFF_B = {(0, 0): [0.4e9 - 0.1e9j, 0.2e9 + 0.3e9j, 0.15e9 - 0.2e9j],
          (0, 1): [0.22e9 + 0.05e9j, 0.5e9 + 0.35e9j, 0.18e9 + 0.1e9j],
          (1, 1): [0.19e9 + 0.08e9j, 0.12e9 - 0.15e9j, 0.45e9 - 0.3e9j]}
_AFF_D = {(0, 0): 0.12 + 0.05j, (0, 1): -0.08 + 0.03j,
          (1, 1): 0.2 - 0.04j}
_AFF_E = {(0, 0): 2.0e-12 + 1e-12j, (0, 1): -1.5e-12 + 0.0j,
          (1, 1): 3.0e-12 + 0.0j}
_AFF_PAIRS = [(0, 0), (0, 1), (1, 1)]
_AFF_GS = [0.08, 0.34, 0.61, 0.9]
_AFF_G_QUERY = 0.475

#: 串联 RL 两端口族样本网格（v1 test_param_vf RL 族同款网格，连续性）。
RL_SAMPLES = [(32.0, 9.0), (45.0, 14.5), (58.0, 8.5), (66.0, 13.0),
              (38.0, 15.5), (52.0, 10.5), (30.0, 12.5), (62.0, 15.0)]
RL_BOUNDS = {"r_ohm": (28.0, 70.0), "l_nh": (8.0, 16.0)}
RL_INTERIOR = [(44.0, 12.0), (55.0, 11.5), (40.0, 14.0)]
F_LO2_HZ = 0.1e9
F_HI2_HZ = 6.0e9
N_FREQ2 = 81


def _truth_poles() -> np.ndarray:
    """独立公式重算固定基极点（n=1+1 对：对数栅格中点=几何平均，ζ=0.7）。"""
    w_lo = 2.0 * np.pi * F_LO_HZ
    w_hi = 2.0 * np.pi * F_HI_HZ
    w_star = float(np.sqrt(w_lo * w_hi))
    p_c = complex(-ZETA * w_star, w_star * np.sqrt(1.0 - ZETA * ZETA))
    return np.array([complex(-w_star), p_c, np.conj(p_c)])


def _affine_truth(g: float, freq_hz: np.ndarray | None = None) -> np.ndarray:
    """独立闭式真值：S_ij=Σ_k(a_ij_k+b_ij_k·g)/(s−p_k)+d_ij+e_ij·s（互易）。"""
    freq = np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ) if freq_hz is None else freq_hz
    s = 2.0j * np.pi * freq
    poles = _truth_poles()
    m = np.zeros((len(s), 2, 2), dtype=complex)
    for i, j in _AFF_PAIRS:
        col = sum((_AFF_A[(i, j)][k] + _AFF_B[(i, j)][k] * g)
                  / (s - poles[k]) for k in range(3))
        col = col + _AFF_D[(i, j)] + _AFF_E[(i, j)] * s
        m[:, i, j] = col
        m[:, j, i] = col
    return m


def _series_rl_truth(r_ohm: float, l_nh: float) -> np.ndarray:
    """串联 Z 两端口闭式（ABCD=[1,Z;0,1] 推导，#118 独立来源）：
    S11=S22=Z/(2Z0+Z)、S12=S21=2Z0/(2Z0+Z)，Z=R+jωL。"""
    freq = np.linspace(F_LO2_HZ, F_HI2_HZ, N_FREQ2)
    s = 2.0j * np.pi * freq
    z = r_ohm + s * (l_nh * 1e-9)
    s11 = z / (2.0 * Z0_OHM + z)
    s21 = 2.0 * Z0_OHM / (2.0 * Z0_OHM + z)
    m = np.zeros((len(s), 2, 2), dtype=complex)
    m[:, 0, 0] = m[:, 1, 1] = s11
    m[:, 0, 1] = m[:, 1, 0] = s21
    return m


def _affine_config(**overrides) -> dict:
    cfg = {"bounds": {"g": (0.0, 1.0)}, "freq_grid_ghz": (1.0, 6.0),
           "n_freq": N_FREQ, "n_real_poles": 1, "n_cmplx_pairs": 1,
           "zeta": ZETA, "n_ports": 2}
    cfg.update(overrides)
    return cfg


def _rl_config(**overrides) -> dict:
    cfg = {"bounds": dict(RL_BOUNDS), "freq_grid_ghz": (0.1, 6.0),
           "n_freq": N_FREQ2, "n_real_poles": 2, "n_cmplx_pairs": 3,
           "n_ports": 2}
    cfg.update(overrides)
    return cfg


def _affine_samples() -> list[dict]:
    return [{"params": {"g": g}, "metrics": {"s_matrix": _affine_truth(g)}}
            for g in _AFF_GS]


def _rl_samples() -> list[dict]:
    return [{"params": {"r_ohm": r, "l_nh": l_nh},
             "metrics": {"s_matrix": _series_rl_truth(r, l_nh)}}
            for r, l_nh in RL_SAMPLES]


def _rel_rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b))
                 / np.linalg.norm(b))


def _fitted_affine(**overrides) -> ParamVFSurrogate:
    m = ParamVFSurrogate(_affine_config(**overrides))
    m.fit(_affine_samples())
    return m


def _fitted_rl(**overrides) -> ParamVFSurrogate:
    m = ParamVFSurrogate(_rl_config(**overrides))
    m.fit(_rl_samples())
    return m


# ─── 验收 A：已知真值回收（裁判先行——裁判没过已知锚不得裁判泛化） ─────────────


class TestKnownTruthRecovery:
    def test_poles_match_independent_formula_bitwise(self):
        """"极点回收"语义：固定基=独立公式重算的已知极点逐位相等。

        若实现改基构造，此断言红=显式对齐点（测试真值与基失配而非静默
        错回收）。
        """
        basis = default_pole_basis(F_LO_HZ, F_HI_HZ, 1, 1, ZETA)
        assert np.array_equal(basis, _truth_poles())

    def test_residue_recovery_gate(self):
        """验收 A：逐训练样本逐条目读出 (r, d, e) 对构造常数 ≤1e-8。"""
        m = _fitted_affine()
        assert m._fitted and m.n_ports == 2
        assert m._theta_table.shape == (len(_AFF_GS), 3 * (2 * 3 + 4))
        block = 2 * 3 + 4
        worst = 0.0
        for si, g in enumerate(_AFF_GS):
            theta = m._theta_table[si]
            for p_idx, (i, j) in enumerate(_AFF_PAIRS):
                mdl = theta_to_model(theta[p_idx * block:(p_idx + 1) * block],
                                     m._poles)
                got = np.concatenate([mdl["residues"],
                                      np.array([mdl["d"], mdl["e"]])])
                want = np.concatenate([
                    np.array(_AFF_A[(i, j)]) + np.array(_AFF_B[(i, j)]) * g,
                    np.array([_AFF_D[(i, j)], _AFF_E[(i, j)]])])
                rel = _rel_rmse(got, want)
                worst = max(worst, rel)
        assert worst <= RECOVERY_GATE, f"留数回收 rel={worst:.3e}"

    def test_interior_prediction_affine_exact(self):
        """验收 A：仿射族内点预测全矩阵 rel RMSE ≤1e-8（等效核精确性）。"""
        m = _fitted_affine()
        pred = m.predict_matrix({"g": _AFF_G_QUERY})
        truth = _affine_truth(_AFF_G_QUERY)
        rel = _rel_rmse(pred, truth)
        assert rel <= RECOVERY_GATE, f"内点预测 rel={rel:.3e}"

    def test_fit_info_keys_and_readout_scale(self):
        m = _fitted_affine()
        info = m.fit(_affine_samples())  # 重拟合幂等（同数据同表）
        assert info["kind"] == "vf_parametric"
        assert info["n_ports"] == 2 and info["n_entries"] == 3
        assert info["n_theta"] == 3 * (2 * 3 + 4)
        assert info["max_fit_rms"] <= 1e-12  # 基内真值读出=机器精度
        assert info["max_reciprocity_residual_train"] == 0.0
        pv = info["passivity"]
        assert set(pv) >= {"passive", "sigma_max_in_band",
                           "lambda_min_i_minus_ssh", "tol", "n_members"}
        assert pv["n_members"] == len(_AFF_GS)  # 逐成员单源消费如实透出
        assert isinstance(pv["passive"], bool)


# ─── 验收 B：参数族泛化（串联 RL 两端口闭式族） ──────────────────────────────


class TestSeriesRLGeneralization:
    def test_interior_rmse_gate_and_not_worse_control(self):
        """验收 B：内点全矩阵 RMSE ≤5e-2，且逐点优于 nearest-neighbor 基线。"""
        m = _fitted_rl()
        for r, l_nh in RL_INTERIOR:
            params = {"r_ohm": r, "l_nh": l_nh}
            pred = m.predict_matrix(params)
            truth = _series_rl_truth(r, l_nh)
            rel = _rel_rmse(pred, truth)
            assert rel <= RL_GATE, f"{params} rel_rmse={rel:.3e}"
            # 不劣对照：邻域插值 < 最近样本基线（同裁判、同真值）
            _, idx, exact = local_linear_weights(
                m._sample_x, m._norm_params(params), m._k_eff, m.idw_power)
            assert not exact
            nn_theta = m._theta_table[idx[0]]
            nn = m._matrix_from_theta(nn_theta)
            assert rel < _rel_rmse(nn, truth), (
                f"{params} interp={rel:.3e} 不得劣于 nearest="
                f"{_rel_rmse(nn, truth):.3e}")

    def test_lossy_family_readout_passive(self):
        """有耗 RL 两端口读出族无源性 verdict=passive（σmax≤1+tol）。"""
        m = _fitted_rl()
        assert m.fit(_rl_samples())["passivity"]["passive"] is True

    def test_active_family_readout_not_passive(self):
        """无源性负例：真值 ×3（有源放大）→ 读出族 verdict passive=False。"""
        samples = _rl_samples()
        for smp in samples:
            smp["metrics"]["s_matrix"] = 3.0 * smp["metrics"]["s_matrix"]
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(samples)
        pv = info["passivity"]
        assert pv["passive"] is False
        assert pv["sigma_max_in_band"] > 1.0 + pv["tol"]

    def test_extrapolation_warn_and_scalar_predict_keys(self):
        """凸包外 → warn（不阻断预测）；predict 出逐条目 db 键+判据。"""
        m = _fitted_rl()
        out_params = {"r_ohm": 85.0, "l_nh": 12.0}  # r 超 bbox ⊂ 凸包外
        v = m.param_extrapolation_verdict(out_params)
        assert v["param_extrapolation"] == "extrapolation_warn"
        combo = m.predict_matrix_with_verdict(out_params)
        assert np.isfinite(combo["matrix"]).all()
        assert combo["param_extrapolation"]["param_extrapolation"] == (
            "extrapolation_warn")
        assert m.param_extrapolation_verdict(
            {"r_ohm": 44.0, "l_nh": 12.0})["param_extrapolation"] == "ok"
        out = m.predict({"r_ohm": 44.0, "l_nh": 12.0})
        assert set(out) == {"s11_db_max_in_band", "s11_db_min_in_band",
                            "s12_db_max_in_band", "s12_db_min_in_band",
                            "s22_db_max_in_band", "s22_db_min_in_band",
                            "param_extrapolation"}
        assert all(np.isfinite(v) for k, v in out.items()
                   if k != "param_extrapolation")
        assert m.uncertainty({"r_ohm": 44.0, "l_nh": 12.0}) is None

    def test_predict_curve_returns_s11_entry(self):
        """多端口模式 predict_curve=S11 条目（1-D 便捷面，全矩阵走主面）。"""
        m = _fitted_rl()
        params = {"r_ohm": 44.0, "l_nh": 12.0}
        curve = m.predict_curve(params)
        assert curve.shape == (N_FREQ2,)
        assert np.array_equal(curve, m.predict_matrix(params)[:, 0, 0])
        combo = m.predict_curve_with_verdict(params)
        assert np.array_equal(combo["curve"], curve)
        assert combo["param_extrapolation"]["param_extrapolation"] == "ok"


# ─── 验收 D：互易按构造（上三角参数化，green_op 先例） ────────────────────────


class TestReciprocityByConstruction:
    def test_bitwise_symmetry_multiple_theta(self):
        """多 θ 点（含定 seed 伪随机内点）max|S−Sᵀ| 逐位 0 且 ≤1e-12。"""
        m = _fitted_rl()
        rng = np.random.default_rng(2026)
        points = [{"r_ohm": float(rng.uniform(30.0, 66.0)),
                   "l_nh": float(rng.uniform(8.5, 15.5))} for _ in range(5)]
        points += [{"r_ohm": r, "l_nh": l_nh} for r, l_nh in RL_INTERIOR]
        for params in points:
            s = m.predict_matrix(params)
            assert np.array_equal(s, np.swapaxes(s, 1, 2)), f"{params} 非逐位对称"
            asym = float(np.max(np.abs(s - np.swapaxes(s, 1, 2))))
            assert asym <= RECIP_GATE

    def test_asymmetric_input_symmetrized_and_reported(self):
        """非互易输入：对称化进 fit+如实报告残差（不静默不拒绝），预测仍互易。"""
        samples = _rl_samples()
        for k in range(3):  # 给 S[:,0,1] 加 0.05 构造非互易（S12≠S21）
            sm = np.array(_series_rl_truth(*RL_SAMPLES[k]))
            sm[:, 0, 1] += 0.05
            samples[k]["metrics"]["s_matrix"] = sm
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(samples)
        assert info["max_reciprocity_residual_train"] > 0.0
        pred = m.predict_matrix({"r_ohm": 44.0, "l_nh": 12.0})
        assert float(np.max(np.abs(pred - np.swapaxes(pred, 1, 2)))) == 0.0


# ─── 验收 C：单端口既有行为零变化 ─────────────────────────────────────────────


class TestSinglePortCompat:
    def test_nports1_explicit_equals_default_bitwise(self):
        """n_ports=1 显式 config 与缺省 config 输出逐位一致（原路径）。"""
        base = {"bounds": dict(RL_BOUNDS), "freq_grid_ghz": (0.1, 6.0),
                "n_freq": N_FREQ2}
        samples = [{"params": {"r_ohm": r, "l_nh": l_nh},
                    "metrics": {"s11_curve":
                                _single_port_curve(r, l_nh)}}
                   for r, l_nh in RL_SAMPLES]
        ma = ParamVFSurrogate(dict(base))
        mb = ParamVFSurrogate({**base, "n_ports": 1})
        ia, ib = ma.fit(samples), mb.fit(samples)
        assert ma.n_ports == 1 and mb.n_ports == 1
        assert set(ia) == set(ib)
        for k in ia:
            assert ia[k] == ib[k], f"info[{k!r}] 漂移"
        for params in ({"r_ohm": 44.0, "l_nh": 12.0}, {"r_ohm": 55.0, "l_nh": 11.5}):
            assert np.array_equal(ma.predict_curve(params),
                                  mb.predict_curve(params))
        assert ia.get("n_ports") is None  # v1 info 键面无 n_ports（零变化）

    def test_v1_mode_ignores_s_matrix_samples(self):
        """v1 模式下 s_matrix-only 样本按缺曲线跳过（原路径语义）。"""
        cfg = {"bounds": dict(RL_BOUNDS), "freq_grid_ghz": (0.1, 6.0),
               "n_freq": N_FREQ2}
        samples = [{"params": {"r_ohm": r, "l_nh": l_nh},
                    "metrics": {"s_matrix": _series_rl_truth(r, l_nh)}}
                   for r, l_nh in RL_SAMPLES]
        m = ParamVFSurrogate(cfg)
        with pytest.raises(ValueError, match="有效曲线样本 0 < 3"):
            m.fit(samples)

    def test_registry_key_unchanged(self):
        """零新键：vf_parametric 工厂仍为 ParamVFSurrogate（注册面零改动）。"""
        assert surrogate_registry.snapshot()["vf_parametric"].__name__ == (
            "ParamVFSurrogate")


def _single_port_curve(r_ohm: float, l_nh: float) -> np.ndarray:
    """独立闭式 RL 负载反射 S11=(ZL−Z0)/(ZL+Z0)（v1 单端口族真值）。"""
    freq = np.linspace(F_LO2_HZ, F_HI2_HZ, N_FREQ2)
    s = 2.0j * np.pi * freq
    zl = r_ohm + s * (l_nh * 1e-9)
    return (zl - Z0_OHM) / (zl + Z0_OHM)


# ─── 验收 E：确定性 + 负例契约 ────────────────────────────────────────────────


class TestDeterminismAndNegatives:
    def test_determinism_bitwise(self):
        """同配置同数据两跑：theta 表/predict_matrix/verdict 逐位一致。"""
        samples = _rl_samples()
        ma, mb = _fitted_rl(), ParamVFSurrogate(_rl_config())
        mb.fit(samples)
        assert np.array_equal(ma._theta_table, mb._theta_table)
        for params in ({"r_ohm": 44.0, "l_nh": 12.0},
                       {"r_ohm": 61.0, "l_nh": 9.5}):
            assert np.array_equal(ma.predict_matrix(params),
                                  mb.predict_matrix(params))
            assert (ma.param_extrapolation_verdict(params)
                    == mb.param_extrapolation_verdict(params))

    def test_shape_mismatch_skipped(self):
        samples = _rl_samples()
        samples[0]["metrics"]["s_matrix"] = _series_rl_truth(
            *RL_SAMPLES[0])[:, :, :1]  # (n_freq,2,1) 形状不符
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(samples)
        assert info["n_curves"] == 7 and info["n_skipped"] == 1

    def test_nonfinite_matrix_skipped(self):
        samples = _rl_samples()
        bad = np.array(_series_rl_truth(*RL_SAMPLES[0]))
        bad[0, 0, 0] = np.nan
        samples[0]["metrics"]["s_matrix"] = bad
        m = ParamVFSurrogate(_rl_config())
        info = m.fit(samples)
        assert info["n_curves"] == 7 and info["n_skipped"] == 1

    def test_n_lt_3(self):
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(ValueError, match=r"样本 2 < 3"):
            m.fit(_rl_samples()[:2])

    def test_fit_param_dim_mismatch(self):
        samples = _rl_samples()
        del samples[2]["params"]["l_nh"]
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(ValueError, match="键集与 bounds 不匹配"):
            m.fit(samples)
        samples = _rl_samples()
        samples[2]["params"]["extra"] = 1.0
        with pytest.raises(ValueError, match="多="):
            m.fit(samples)

    def test_predict_param_dim_mismatch_and_before_fit(self):
        m = ParamVFSurrogate(_rl_config())
        with pytest.raises(RuntimeError, match="先 fit"):
            m.predict_matrix({"r_ohm": 44.0, "l_nh": 12.0})
        m.fit(_rl_samples())
        with pytest.raises(ValueError, match="键集与 bounds 不匹配"):
            m.predict_matrix({"r_ohm": 44.0})
        with pytest.raises(ValueError, match="多="):
            m.predict_matrix({"r_ohm": 44.0, "l_nh": 12.0, "x": 0.0})

    def test_config_nports_validation(self):
        with pytest.raises(ValueError, match="n_ports"):
            ParamVFSurrogate(_rl_config(n_ports=0))
