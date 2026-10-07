"""ME-22 array_error_injection 定向测试：确定性 + 统计闭式锚 + 失效元 + 校准闭环 + 守卫。

统计裁判（#118 独立推导，与被测 Monte Carlo 实现不同源）
========
误差方向图二阶矩逐项展开：
    E[|AF(θ)|²] = Σ_i E|g_i|² + Σ_{i≠j} E[g_i g_j*]·exp(jψ_ij)
幅度 dB 域高斯（|g|=10^(X/20)，X~N(0,σ_dB²)）⇒ E|g|² = exp(2σ'²)、
E|g| = exp(σ'²/2)，σ' = ln10·σ_dB/20；独立高斯相位 ⇒ E[e^{jφ}] = exp(−σ_φ²/2)、
E[g] = exp(σ'²/2 − σ_φ²/2)、E[g_i g_j*] = |E[g]|² (i≠j)。故

    E[|AF(θ)|²] = N·E|g|² + |E[g]|²·(|AF_0(θ)|² − N)

对理想峰值 N² 归一：E[P_err(θ)] = Var(g)/N + |E[g]|²·P_0(θ)，其中
Var(g) = exp(2σ'²) − exp(σ'² − σ_φ²)。由此：
- 副瓣掩码上的期望地板 = Var(g)/N − (1 − |E[g]|²)·P_sll_mean
  （第二项是"误差相干项对理想副瓣的缩摆"，σ'、σ_φ 小时二阶可略，
  本测试用精确式断言）；小误差极限 ≈ (σ'² + σ_φ²)/N（Mailloux σ²/N 口径）；
- 平均峰值增益 = (E|g|² + (N−1)|E[g]|²)/N；纯相位 ≈ 1 − σ_φ²(1−1/N)。
失效元几何闭式：无幅相误差失效 k 元时 |AF| ≤ N−k（三角不等式）且
广侧射处 = N−k（同相），峰损 = 20·log10((N−k)/N) ≈ −8.686·k/N dB（精确）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.array_error_injection import (
    array_factor_with_errors,
    calibration_roundtrip,
    degradation_metrics,
    ideal_array_factor,
    inject_errors,
)

SEED = 20260926
N_ANT = 32
F_GHZ = 10.0
N_SEEDS = 10


def _ula_pos(n: int, d: float = 0.5) -> np.ndarray:
    return d * np.arange(n, dtype=float)


def _theta_grid(n_pts: int = 3601) -> np.ndarray:
    return np.linspace(-90.0, 90.0, n_pts)


def _seeds(n: int = N_SEEDS) -> list[int]:
    return list(range(SEED, SEED + n))


def _metrics_for_seed(
    n: int, seed: int, amp_sigma_db: float, phase_sigma_deg: float, dead: list[int] | None = None
) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
    theta = _theta_grid()
    pos = _ula_pos(n)
    af0 = ideal_array_factor(theta, pos, F_GHZ)
    g = inject_errors(n, seed, amp_sigma_db, phase_sigma_deg, dead_elements=dead)["gains"]
    af_e = array_factor_with_errors(theta, pos, g, F_GHZ)
    return degradation_metrics(af_e, af0, theta), af0, theta


def _ideal_sll_mean(af0: np.ndarray, theta: np.ndarray, first_null_deg: list[float]) -> float:
    """理想方向图主瓣外平均功率（与 degradation_metrics 同一掩码口径）。"""
    p = np.abs(af0) ** 2 / np.max(np.abs(af0)) ** 2
    mask = (theta <= first_null_deg[0]) | (theta >= first_null_deg[-1])
    return float(p[mask].mean())


def _theory_floor(amp_sigma_db: float, phase_sigma_deg: float, n: int, p_sll_mean: float) -> float:
    """副瓣掩码上误差地板的解析期望（见模块文档推导）。"""
    s = np.log(10.0) / 20.0 * amp_sigma_db
    sig_p = np.deg2rad(phase_sigma_deg)
    var_g = np.exp(2.0 * s**2) - np.exp(s**2 - sig_p**2)
    eg2 = np.exp(s**2 - sig_p**2)
    return float(var_g / n - (1.0 - eg2) * p_sll_mean)


class TestDeterminism:
    def test_same_seed_bitwise_identical(self) -> None:
        kw: dict[str, object] = {"amp_sigma_db": 0.7, "phase_sigma_deg": 6.0, "dead_elements": [3]}
        a = inject_errors(16, SEED, **kw)  # type: ignore[arg-type]
        b = inject_errors(16, SEED, **kw)  # type: ignore[arg-type]
        for key in ("gains", "amp_realizations_db", "phase_realizations_deg"):
            assert np.array_equal(a[key], b[key])  # type: ignore[index]
        assert a["dead"] == b["dead"] == [3]  # type: ignore[index]

    def test_different_seed_differs(self) -> None:
        a = inject_errors(16, SEED, 0.5, 5.0)
        b = inject_errors(16, SEED + 1, 0.5, 5.0)
        assert not np.array_equal(a["gains"], b["gains"])

    def test_zero_error_injection_is_exact_ones(self) -> None:
        out = inject_errors(8, SEED, 0.0, 0.0)
        assert np.array_equal(out["gains"], np.ones(8, dtype=complex))
        assert np.all(np.asarray(out["amp_realizations_db"]) == 0.0)
        assert np.all(np.asarray(out["phase_realizations_deg"]) == 0.0)
        assert out["dead"] == []

    def test_zero_error_af_equals_ideal_bitwise(self) -> None:
        theta = _theta_grid(721)
        pos = _ula_pos(8)
        g = inject_errors(8, SEED, 0.0, 0.0)["gains"]
        af_zero = array_factor_with_errors(theta, pos, g, F_GHZ)
        af_ideal = ideal_array_factor(theta, pos, F_GHZ)
        assert np.array_equal(af_zero, af_ideal)

    def test_ideal_af_matches_uniform_closed_form(self) -> None:
        """d=λ/2 均匀阵对照闭式 Σe^{jnψ} = sin(Nψ/2)/sin(ψ/2)（未归一化，ψ→0 极限 N）。"""
        n = 8
        theta = np.array([-30.0, -10.0, 0.0, 15.0, 40.0])
        af = ideal_array_factor(theta, _ula_pos(n), F_GHZ)
        psi = 2.0 * np.pi * 0.5 * np.sin(np.deg2rad(theta))
        with np.errstate(invalid="ignore", divide="ignore"):
            ref = np.where(
                np.abs(np.sin(psi / 2)) < 1e-12, float(n), np.sin(n * psi / 2) / np.sin(psi / 2)
            )
        assert np.allclose(np.abs(af), np.abs(ref), atol=1e-9)

    def test_element_pattern_multiplicative_bitwise(self) -> None:
        theta = _theta_grid(181)
        pos = _ula_pos(6)

        def _pat(t: object, f: float) -> object:
            return np.cos(np.deg2rad(np.asarray(t)))

        af_omni = ideal_array_factor(theta, pos, F_GHZ)
        af_pat = ideal_array_factor(theta, pos, F_GHZ, element_pattern=_pat)
        assert np.array_equal(af_pat, af_omni * np.cos(np.deg2rad(theta)))

    def test_1d_pos_matches_3d_pos_bitwise(self) -> None:
        theta = _theta_grid(361)
        p1 = _ula_pos(6)
        p3 = np.column_stack([p1, np.zeros(6), np.zeros(6)])
        assert np.array_equal(
            ideal_array_factor(theta, p1, F_GHZ), ideal_array_factor(theta, p3, F_GHZ)
        )


class TestStatistics:
    def test_phase_only_peak_loss_matches_closed_form(self) -> None:
        """N=32、σ_φ=5°、10 seed 平均：主峰损失 ≈ (1+(N−1)e^{−σ_φ²})/N 的 dB。"""
        n = N_ANT
        losses = [_metrics_for_seed(n, s, 0.0, 5.0)[0]["p_gain_loss_db"] for s in _seeds()]
        mean_loss = float(np.mean(losses))
        sig = np.deg2rad(5.0)
        theory_db = float(10.0 * np.log10((1.0 + (n - 1) * np.exp(-(sig**2))) / n))
        assert -0.2 < theory_db < -0.005  # 推导数值自检（32 元 5° ≈ −0.032 dB）
        assert mean_loss < 0.0
        assert abs(mean_loss - theory_db) < 0.1  # 松界：每 seed 峰值起伏 σ_φ/√N ≈ 0.066 dB

    def test_sidelobe_floor_matches_closed_form(self) -> None:
        """N=32、σ_φ=10°：主瓣外平均功率地板 ≈ Var(g)/N 修正式（10 seed 平均）。"""
        n = N_ANT
        floors = []
        ref = None
        for s in _seeds():
            m, af0, theta = _metrics_for_seed(n, s, 0.0, 10.0)
            p_sll = _ideal_sll_mean(af0, theta, m["first_null_deg"])  # type: ignore[arg-type]
            floors.append(m["sidelobe_mean_power_err"] - m["sidelobe_mean_power_ideal"])
            ref = (af0, theta, p_sll)
        assert ref is not None
        af0, theta, p_sll = ref
        theory = _theory_floor(0.0, 10.0, n, p_sll)
        # 推导数值自检：精确式 ≈ σ_φ²/N·(1−N·P_sll)，量级 ~1e-3
        assert 0.5e-3 < theory < 2.0e-3
        mean_floor = float(np.mean(floors))
        assert 0.7 * theory < mean_floor < 1.5 * theory
        assert _ideal_sll_mean(af0, theta, [0.0, 0.0]) >= 0.0  # 掩码口径自洽（非负功率）

    def test_floor_monotonic_in_phase_sigma(self) -> None:
        seeds = _seeds(8)
        theory: list[float] = []
        floors: list[float] = []
        for sigma in (5.0, 10.0, 20.0):
            vals = []
            ref = None
            for s in seeds:
                m, af0, theta = _metrics_for_seed(N_ANT, s, 0.0, sigma)
                p_sll = _ideal_sll_mean(af0, theta, m["first_null_deg"])  # type: ignore[arg-type]
                vals.append(m["sidelobe_mean_power_err"] - m["sidelobe_mean_power_ideal"])
                ref = p_sll
            assert ref is not None
            floors.append(float(np.mean(vals)))
            theory.append(_theory_floor(0.0, sigma, N_ANT, ref))
        assert floors[0] < floors[1] < floors[2]
        for f, t in zip(floors, theory, strict=True):
            assert 0.7 * t < f < 1.5 * t

    def test_floor_monotonic_in_amp_sigma(self) -> None:
        seeds = _seeds(8)
        theory: list[float] = []
        floors: list[float] = []
        for sigma_db in (0.5, 1.0, 2.0):
            vals = []
            ref = None
            for s in seeds:
                m, af0, theta = _metrics_for_seed(N_ANT, s, sigma_db, 0.0)
                p_sll = _ideal_sll_mean(af0, theta, m["first_null_deg"])  # type: ignore[arg-type]
                vals.append(m["sidelobe_mean_power_err"] - m["sidelobe_mean_power_ideal"])
                ref = p_sll
            assert ref is not None
            floors.append(float(np.mean(vals)))
            theory.append(_theory_floor(sigma_db, 0.0, N_ANT, ref))
        assert floors[0] < floors[1] < floors[2]
        for f, t in zip(floors, theory, strict=True):
            assert 0.7 * t < f < 1.5 * t


class TestDeadElement:
    def test_dead_peak_loss_exact_and_one_over_n_scaling(self) -> None:
        losses: dict[int, float] = {}
        for n, dead in ((8, [2]), (N_ANT, [5])):
            m, _af0, _theta = _metrics_for_seed(n, SEED, 0.0, 0.0, dead=dead)
            expect = float(20.0 * np.log10((n - 1) / n))
            # 无幅相误差、网格含广侧射：主峰 = N−1 精确成立（|AF| ≤ N−1 三角不等式）
            assert abs(float(m["p_gain_loss_db"]) - expect) < 1e-9
            losses[n] = float(m["p_gain_loss_db"])
        # ≈1/N 量级：|loss(8)|/|loss(32)| = log10(8/7)/log10(32/31) ≈ 4.21（对数律非严格 4）
        ratio = abs(losses[8] / losses[N_ANT])
        assert 3.5 < ratio < 5.0

    def test_dead_element_fills_first_null(self) -> None:
        m, _af0, _theta = _metrics_for_seed(N_ANT, SEED, 0.0, 0.0, dead=[5])
        assert np.isfinite(m["null_fill_db"])  # 理想零点被填充（> −inf）
        assert m["null_fill_db"] > -100.0  # 线性功率 > 0（填充非零）
        assert m["null_fill_db"] < 0.0  # 仍低于理想峰


class TestCalibrationRoundtrip:
    def test_roundtrip_noiseless_recovery_1e_minus6(self) -> None:
        out = calibration_roundtrip(
            8, {"rng_seed": SEED, "amp_sigma_db": 0.5, "phase_sigma_deg": 5.0}, F_GHZ
        )
        assert out["converged"] is True
        assert out["dead_detected"] == []
        assert out["recovery_err"] <= 1e-6  # M-2.1 无噪判据继承
        assert out["amp_err_max"] <= 1e-6
        assert out["phase_err_max_rad"] <= 1e-6

    def test_roundtrip_strong_errors_still_exact(self) -> None:
        out = calibration_roundtrip(
            8, {"rng_seed": SEED + 1, "amp_sigma_db": 3.0, "phase_sigma_deg": 30.0}, F_GHZ
        )
        assert out["recovery_err"] <= 1e-6

    def test_roundtrip_with_dead_element(self) -> None:
        out = calibration_roundtrip(
            8,
            {"rng_seed": SEED + 2, "amp_sigma_db": 0.5, "phase_sigma_deg": 5.0, "dead_elements": [3]},
            F_GHZ,
        )
        assert out["dead_injected"] == [3]
        assert out["dead_detected"] == [3]  # 零可见度行检出 = 注入
        assert out["recovered"][3] == 0.0  # dead 元回收 g ≈ 0（精确 0）
        assert out["recovery_err"] <= 1e-6  # 存活子阵仍机器精度

    def test_roundtrip_custom_pairs_with_triangle(self) -> None:
        pairs = [(0, 1), (0, 2), (1, 2), (2, 3), (3, 4), (2, 4)]
        out = calibration_roundtrip(
            5, {"rng_seed": SEED + 3, "amp_sigma_db": 1.0, "phase_sigma_deg": 10.0},
            F_GHZ, baseline_pairs=pairs,
        )
        assert out["recovery_err"] <= 1e-6

    def test_roundtrip_bipartite_pairs_rejected(self) -> None:
        with pytest.raises(ValueError, match="幅值简并"):
            calibration_roundtrip(
                4, {"rng_seed": SEED, "amp_sigma_db": 0.5, "phase_sigma_deg": 5.0},
                F_GHZ, baseline_pairs=[(0, 1), (1, 2), (2, 3)],
            )

    def test_roundtrip_missing_seed_rejected(self) -> None:
        with pytest.raises(ValueError, match="rng_seed"):
            calibration_roundtrip(8, {"amp_sigma_db": 0.5}, F_GHZ)

    def test_roundtrip_n_ant_below_3_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_ant ≥ 3"):
            calibration_roundtrip(2, {"rng_seed": SEED}, F_GHZ)

    def test_roundtrip_too_few_live_rejected(self) -> None:
        with pytest.raises(ValueError, match="存活元"):
            calibration_roundtrip(
                4, {"rng_seed": SEED, "amp_sigma_db": 0.5, "phase_sigma_deg": 5.0, "dead_elements": [0, 1]},
                F_GHZ,
            )


class TestGuards:
    @pytest.mark.parametrize(
        ("n_ant", "seed", "kwargs"),
        [
            (8, SEED, {"amp_sigma_db": -0.1}),
            (8, SEED, {"phase_sigma_deg": -5.0}),
            (8, SEED, {"amp_sigma_db": float("nan")}),
            (8, SEED, {"phase_sigma_deg": float("inf")}),
        ],
    )
    def test_inject_invalid_sigma(self, n_ant: int, seed: int, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            inject_errors(n_ant, seed, **kwargs)

    @pytest.mark.parametrize(
        "args",
        [(True, SEED), (0, SEED), (-3, SEED), (8.5, SEED)],
    )
    def test_inject_invalid_n_ant(self, args: tuple) -> None:
        with pytest.raises(ValueError):
            inject_errors(*args)

    def test_inject_invalid_seed(self) -> None:
        with pytest.raises(ValueError):
            inject_errors(8, True)
        with pytest.raises(ValueError):
            inject_errors(8, -1)
        with pytest.raises(ValueError):
            inject_errors(8, 1.5)  # type: ignore[arg-type]

    def test_inject_invalid_dead_elements(self) -> None:
        with pytest.raises(ValueError, match="越界"):
            inject_errors(8, SEED, dead_elements=[8])
        with pytest.raises(ValueError, match="越界"):
            inject_errors(8, SEED, dead_elements=[-1])
        with pytest.raises(ValueError, match="重复"):
            inject_errors(8, SEED, dead_elements=[2, 2])
        with pytest.raises(ValueError, match="bool"):
            inject_errors(8, SEED, dead_elements=[True])
        with pytest.raises(ValueError, match="dead_elements"):
            inject_errors(8, SEED, dead_elements="01")  # type: ignore[arg-type]

    def test_af_guards(self) -> None:
        theta = _theta_grid(181)
        pos = _ula_pos(8)
        with pytest.raises(ValueError, match="不一致"):
            array_factor_with_errors(theta, pos, np.ones(6, dtype=complex), F_GHZ)
        with pytest.raises(ValueError, match="形状"):
            array_factor_with_errors(theta, np.zeros((8, 2)), np.ones(8, dtype=complex), F_GHZ)
        with pytest.raises(ValueError, match="为正"):
            array_factor_with_errors(theta, pos, np.ones(8, dtype=complex), 0.0)
        with pytest.raises(ValueError):
            array_factor_with_errors(theta, pos, np.full(8, np.nan), F_GHZ)
        with pytest.raises(ValueError, match="可调用"):
            ideal_array_factor(theta, pos, F_GHZ, element_pattern="x")  # type: ignore[arg-type]

    def test_metrics_guards(self) -> None:
        theta = _theta_grid(181)
        pos = _ula_pos(8)
        af0 = ideal_array_factor(theta, pos, F_GHZ)
        with pytest.raises(ValueError, match="递增"):
            degradation_metrics(af0, af0, theta[::-1])
        with pytest.raises(ValueError, match="不一致"):
            degradation_metrics(af0, af0, _theta_grid(101))
        with pytest.raises(ValueError, match="形状"):
            degradation_metrics(af0[:-1], af0, theta)
        # 主瓣占满网格 → 无第一零点 → 拒绝
        tiny = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
        af_tiny = ideal_array_factor(tiny, pos, F_GHZ)
        with pytest.raises(ValueError, match="第一零点"):
            degradation_metrics(af_tiny, af_tiny, tiny)
