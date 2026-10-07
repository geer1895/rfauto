"""M-2.1 array_calib 定向测试：合成注入回收主门 + 噪声带 + 简并 + 守卫。

判据（方案书 M-2 判据①）：合成注入增益误差 → logcal/lincal 回收 ≤1e-6
（无噪）/噪声下覆盖带（SNR 30dB，松界 + 种子固定防 flaky）。
数值裁判 = 合成注入回收 + 独立推导（#118：真值由合成构造给出，与被测
实现不同源；幅/相分别断言）。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.array_calib import (
    apply_delay_correction,
    firstcal_delay_solve,
    lincal_gain_solve,
    logcal_gain_solve,
    redundant_group_degeneracy,
)

SEED = 20260926
N_ANT = 8
N_FREQ = 64
F_AXIS = np.linspace(1.0e9, 2.0e9, N_FREQ)
RECOVERY_TOL = 1e-6


def _full_pairs(n_ant: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(n_ant) for j in range(i + 1, n_ant)]


def _random_gains(
    rng: np.random.Generator,
    n_ant: int,
    *,
    with_delay: bool = False,
    pin_ref: bool = True,
    f_axis: np.ndarray = F_AXIS,
) -> tuple[np.ndarray, np.ndarray]:
    """真增益：|g|∈[0.5,2]、相位∈[-pi,pi]（逐元），可选延迟因子（hera_cal 正号）。"""
    amp = rng.uniform(0.5, 2.0, size=n_ant)
    phase = rng.uniform(-np.pi, np.pi, size=n_ant)
    tau = rng.uniform(2.0e-9, 8.0e-9, size=n_ant) if with_delay else np.zeros(n_ant)
    if pin_ref:
        amp[0] = 1.0
        phase[0] = 0.0
        tau[0] = 0.0
    g = (
        amp[:, None]
        * np.exp(1j * phase[:, None])
        * np.exp(2j * np.pi * f_axis[None, :] * tau[:, None])
    )
    return g, tau


def _random_truth(rng: np.random.Generator, pairs: list[tuple[int, int]]) -> np.ndarray:
    """每基线真值（复随机、频率平坦、非零；与被测实现不同源的独立真值）。

    频率平坦是刻意的：firstcal 拟合的是观测相位-频率斜率，真值若逐频 iid
    随机相位会淹没斜率（物理真值传递函数在带内也是平滑的）。
    """
    base = rng.standard_normal(len(pairs)) + 1j * rng.standard_normal(len(pairs))
    assert np.all(np.abs(base) > 1e-3)
    return np.repeat(base[:, None], N_FREQ, axis=1)


def _measure(g: np.ndarray, pairs: list[tuple[int, int]], v_true: np.ndarray) -> np.ndarray:
    idx = np.asarray(pairs)
    return g[idx[:, 0]] * np.conj(g[idx[:, 1]]) * v_true


def _gain_errors(g_hat: np.ndarray, g_true: np.ndarray) -> tuple[float, float]:
    """幅/相回收误差（相位按 wrapped 差）。"""
    amp_err = float(np.max(np.abs(np.abs(g_hat) - np.abs(g_true)) / np.abs(g_true)))
    ph_err = float(np.max(np.abs(np.angle(g_hat * np.conj(g_true)))))
    return amp_err, ph_err


def _model_predictions(g: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    idx = np.asarray(pairs)
    return g[idx[:, 0]] * np.conj(g[idx[:, 1]])


# ---------------------------------------------------------------------------
# 主门 1：无噪合成回收链（firstcal → logcal → lincal），全连接 N=8
# ---------------------------------------------------------------------------


def test_noiseless_full_chain_recovery() -> None:
    rng = np.random.default_rng(SEED)
    pairs = _full_pairs(N_ANT)
    g_true, tau_true = _random_gains(rng, N_ANT, with_delay=True, pin_ref=True)
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(g_true, pairs, v_true)

    # firstcal：锚定参考元（真值 tau[0]=0）→ 延迟直接可比
    fc = firstcal_delay_solve(v_meas, pairs, F_AXIS, ref_ant=0)
    tau_hat = np.asarray(fc["per_ant_delay_s"])
    assert float(np.max(np.abs(tau_hat - tau_true))) <= 1e-12
    assert float(np.max(np.asarray(fc["residual_phase_after_delay"]))) <= 1e-8

    v_corr = apply_delay_correction(v_meas, pairs, F_AXIS, tau_hat)
    # 链上解出的增益不含延迟因子，与真值比较须回乘 firstcal 延迟（锚定口径一致）
    g_delay = np.exp(2j * np.pi * F_AXIS[None, :] * tau_hat[:, None])
    lc = logcal_gain_solve(v_corr, pairs, v_true)
    assert lc["converged"] is True
    amp_err, ph_err = _gain_errors(np.asarray(lc["gains"]) * g_delay, g_true)
    assert amp_err <= RECOVERY_TOL, f"logcal 幅值回收 {amp_err:.3e} > 1e-6"
    assert ph_err <= RECOVERY_TOL, f"logcal 相位回收 {ph_err:.3e} rad > 1e-6"

    ln = lincal_gain_solve(v_corr, pairs, v_true)
    assert ln["converged"] is True
    assert float(ln["residual_rms"]) <= 1e-9
    amp_err, ph_err = _gain_errors(np.asarray(ln["gains"]) * g_delay, g_true)
    assert amp_err <= RECOVERY_TOL, f"lincal 幅值回收 {amp_err:.3e} > 1e-6"
    assert ph_err <= RECOVERY_TOL, f"lincal 相位回收 {ph_err:.3e} rad > 1e-6"


def test_noiseless_redundant_group_recovery() -> None:
    """线性阵真冗余组（间隔 u=1..3 共享组真值）——同一 1e-6 回收门。"""
    rng = np.random.default_rng(SEED + 1)
    n_ant = 8
    groups = {u: [(i, i + u) for i in range(n_ant - u)] for u in (1, 2, 3)}
    pairs = [p for ps in groups.values() for p in ps]
    v_true = np.empty((len(pairs), N_FREQ), dtype=complex)
    for ps in groups.values():
        v_grp = complex(rng.standard_normal() + 1j * rng.standard_normal())
        for k, p in enumerate(pairs):
            if p in ps:
                v_true[k] = v_grp
    g_true, _ = _random_gains(rng, n_ant, pin_ref=True)
    v_meas = _measure(g_true, pairs, v_true)

    lc = logcal_gain_solve(v_meas, pairs, v_true)
    assert lc["converged"] is True
    amp_err, ph_err = _gain_errors(np.asarray(lc["gains"]), g_true)
    assert amp_err <= RECOVERY_TOL and ph_err <= RECOVERY_TOL

    ln = lincal_gain_solve(v_meas, pairs, v_true)
    amp_err, ph_err = _gain_errors(np.asarray(ln["gains"]), g_true)
    assert amp_err <= RECOVERY_TOL and ph_err <= RECOVERY_TOL


# ---------------------------------------------------------------------------
# 主门 2：SNR 30dB 加噪带（松界 + 种子固定，防 flaky）
# ---------------------------------------------------------------------------


def test_noise_30db_recovery_band() -> None:
    rng = np.random.default_rng(SEED + 2)
    pairs = _full_pairs(N_ANT)
    g_true, _ = _random_gains(rng, N_ANT)
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(g_true, pairs, v_true)
    # 逐基线 SNR 恒 30dB（全局 σ 会让低幅基线 SNR 崩到负 dB、对数域爆炸）
    sigma = np.sqrt(np.mean(np.abs(v_meas) ** 2, axis=1, keepdims=True)) * 10.0 ** (
        -30.0 / 20.0
    )
    noise = (
        rng.standard_normal(v_meas.shape) + 1j * rng.standard_normal(v_meas.shape)
    ) * (sigma / np.sqrt(2.0))
    v_noisy = v_meas + noise

    for solver in (logcal_gain_solve, lincal_gain_solve):
        out = solver(v_noisy, pairs, v_true)
        amp_err, ph_err = _gain_errors(np.asarray(out["gains"]), g_true)
        assert amp_err <= 0.05, f"{solver.__name__} 30dB 幅值误差 {amp_err:.3e} > 0.05"
        assert ph_err <= 0.05, f"{solver.__name__} 30dB 相位误差 {ph_err:.3e} rad > 0.05"


# ---------------------------------------------------------------------------
# 简并：全局相位等价类（预测逐位不变）+ 锚定唯一 + 二部图幅值棋盘族
# ---------------------------------------------------------------------------


def test_global_phase_degeneracy_family_and_anchor() -> None:
    rng = np.random.default_rng(SEED + 3)
    pairs = _full_pairs(N_ANT)
    g_true, _ = _random_gains(rng, N_ANT, pin_ref=False)  # 真值参考元不钉 1
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(g_true, pairs, v_true)

    # 等价类性质：g -> g*exp(j*alpha) 的模型预测逐位不变（e^{ja}·e^{-ja}=1）
    g_hat = np.asarray(logcal_gain_solve(v_meas, pairs, v_true)["gains"])
    pred = _model_predictions(g_hat, pairs)
    pred_rot = _model_predictions(g_hat * np.exp(1j * 0.7), pairs)
    assert np.allclose(pred, pred_rot, rtol=0, atol=1e-12)

    # 锚定解的唯一代表：g_hat/g_true = 全局相位因子（幅值域非二部图唯一）
    ratio = g_hat / g_true
    assert float(np.max(np.abs(np.abs(ratio) - 1.0))) <= RECOVERY_TOL
    assert float(np.max(np.abs(ratio - ratio[0][None, :]))) <= 1e-9

    # 重跑确定性（同输入同解）
    g_hat2 = np.asarray(logcal_gain_solve(v_meas, pairs, v_true)["gains"])
    assert np.array_equal(g_hat, g_hat2)


def test_bipartite_star_amplitude_checkerboard_family() -> None:
    """星形（二部图）幅值棋盘简并：锚定代表元 + 棋盘变换还原真值。

    真值相位钉参考元、幅值不钉（棋盘自由度下 a_ref=0 代表元 ≠ 真值，
    但真值必在解族内——棋盘变换 t 还原）。
    """
    rng = np.random.default_rng(SEED + 4)
    n_ant = 6
    pairs = [(0, k) for k in range(1, n_ant)]
    amp = rng.uniform(0.5, 2.0, size=n_ant)
    phase = rng.uniform(-np.pi, np.pi, size=n_ant)
    phase[0] = 0.0  # 相位参考钉零（锚定可达）；幅值不钉
    g_true = amp[:, None] * np.exp(1j * phase[:, None])
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(g_true, pairs, v_true)

    d = redundant_group_degeneracy(pairs, n_ant)
    assert d["amp_rank_deficiency"] == 1
    assert d["phase_rank_deficiency"] == 1
    assert d["rank_deficiency"] == 2

    g_hat = np.asarray(logcal_gain_solve(v_meas, pairs, v_true)["gains"])
    # 幅值域锚定代表元（a_ref=0）：棋盘变换 t = ln|g0_true| 还原真值
    side = np.array([1.0] + [-1.0] * (n_ant - 1))
    t = float(np.log(np.abs(g_true[0, 0]) / np.abs(g_hat[0, 0])))
    g_fam = g_hat * np.exp(t * side)[:, None]
    amp_err, ph_err = _gain_errors(g_fam, g_true)
    assert amp_err <= RECOVERY_TOL and ph_err <= RECOVERY_TOL
    # 棋盘族内预测逐位不变（等价类）：裸增益积 vs 归一观测 W
    w_obs = v_meas / v_true
    assert np.allclose(_model_predictions(g_fam, pairs), w_obs, rtol=0, atol=1e-9)


def test_degeneracy_analysis_examples() -> None:
    """全连接（非二部）vs 星形（二部）vs 非连通：简并维数如实报告。"""
    d_full = redundant_group_degeneracy(_full_pairs(8), 8)
    assert d_full["n_components"] == 1
    assert d_full["amp_rank_deficiency"] == 0
    assert d_full["phase_rank_deficiency"] == 1
    assert d_full["rank_deficiency"] == 1
    assert d_full["anchor_suggestion"] == [0]

    d_star = redundant_group_degeneracy([(0, k) for k in range(1, 6)], 6)
    assert d_star["n_components"] == 1
    assert d_star["amp_rank_deficiency"] == 1
    assert d_star["phase_rank_deficiency"] == 1
    assert d_star["rank_deficiency"] == 2
    assert d_star["anchor_suggestion"] == [0, 1]

    # 两个三角（奇圈，非二部）+ 孤立元：幅值缺 1（孤立），相位缺 3
    d_disc = redundant_group_degeneracy(
        [(0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5)], 7
    )
    assert d_disc["n_components"] == 3
    assert d_disc["amp_rank_deficiency"] == 1
    assert d_disc["phase_rank_deficiency"] == 3
    assert d_disc["rank_deficiency"] == 4
    assert d_disc["anchor_suggestion"] == [0, 3, 6]


# ---------------------------------------------------------------------------
# firstcal 2π 歧义：真延迟跨多周期 → 解出不缠绕延迟；直接相位法失败对照
# ---------------------------------------------------------------------------


def test_firstcal_resolves_2pi_ambiguity() -> None:
    rng = np.random.default_rng(SEED + 5)
    n_ant = 6
    n_freq = 401
    f_axis = np.linspace(1.0e9, 3.0e9, n_freq)  # Δf=5MHz：相邻步进 <π
    tau_true = rng.uniform(2.0e-9, 8.0e-9, size=n_ant)  # 跨 ~4-24 个周期
    pairs = _full_pairs(n_ant)
    v_meas = np.exp(
        2j
        * np.pi
        * f_axis[None, :]
        * (tau_true[np.asarray(pairs)[:, 0]] - tau_true[np.asarray(pairs)[:, 1]])[:, None]
    )

    fc = firstcal_delay_solve(v_meas, pairs, f_axis, ref_ant=0)
    tau_hat = np.asarray(fc["per_ant_delay_s"])
    # 锚定口径下的延迟差恢复（真值参考元延迟非零，只可比差）
    diff_err = (tau_hat - tau_hat[0]) - (tau_true - tau_true[0])
    assert float(np.max(np.abs(diff_err))) <= 1e-12
    assert float(np.max(np.asarray(fc["residual_phase_after_delay"]))) <= 1e-8

    # 对照：直接相位法（中心频点相位 / (2πf0)）被 2π 缠绕，失败形态如实断言
    f0 = f_axis[n_freq // 2]
    naive = np.angle(v_meas[:, n_freq // 2]) / (2.0 * np.pi * f0)
    true_diff = tau_true[np.asarray(pairs)[:, 0]] - tau_true[np.asarray(pairs)[:, 1]]
    assert float(np.max(np.abs(naive - true_diff))) > 0.5e-9


# ---------------------------------------------------------------------------
# lincal 初值依赖：logcal 启动（默认）vs 随机初值——收敛性对比登记
# ---------------------------------------------------------------------------


def test_lincal_init_dependency_registration() -> None:
    rng = np.random.default_rng(SEED + 6)
    pairs = _full_pairs(N_ANT)
    g_true, _ = _random_gains(rng, N_ANT)
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(g_true, pairs, v_true)

    ln_log = lincal_gain_solve(v_meas, pairs, v_true, g_init=None)
    rng_b = np.random.default_rng(SEED + 60)
    g0 = 1.0 + 0.3 * (
        rng_b.standard_normal((N_ANT, N_FREQ)) + 1j * rng_b.standard_normal((N_ANT, N_FREQ))
    )
    ln_rand = lincal_gain_solve(v_meas, pairs, v_true, g_init=g0)

    # 登记口径：两者收敛；随机初值迭代数不少于 logcal 启动；
    # 随机初值解 = 同一最优点的全局相位规范族（规范 = g_init 参考元相位），
    # 按参考元相位归零后与真值一致（幅值域非二部图唯一，不受规范影响）。
    assert ln_log["converged"] is True
    assert ln_rand["converged"] is True
    assert int(ln_log["n_iter"]) <= int(ln_rand["n_iter"])
    for out in (ln_log, ln_rand):
        g_hat = np.asarray(out["gains"])
        gauge = g_hat[0] / np.abs(g_hat[0])  # 每频点参考元单位相位
        amp_err, ph_err = _gain_errors(g_hat / gauge[None, :], g_true)
        assert amp_err <= RECOVERY_TOL and ph_err <= RECOVERY_TOL
    assert float(ln_rand["residual_rms"]) <= float(ln_log["residual_rms"]) + 1e-12


# ---------------------------------------------------------------------------
# 守卫：bool/NaN/零真值/重复/自配/越界/不连通/形状不配 → ValueError
# ---------------------------------------------------------------------------


def _valid_inputs(n_ant: int = 4) -> tuple[np.ndarray, list[tuple[int, int]], np.ndarray]:
    pairs = _full_pairs(n_ant)
    rng = np.random.default_rng(SEED + 7)
    v_true = _random_truth(rng, pairs)
    v_meas = _measure(np.ones((n_ant, N_FREQ), dtype=complex), pairs, v_true)
    return v_meas, pairs, v_true


def test_guards_reject_invalid_inputs() -> None:
    v_meas, pairs, v_true = _valid_inputs()
    f_axis = np.linspace(1e9, 2e9, N_FREQ)

    with pytest.raises(ValueError, match="二维"):
        logcal_gain_solve(v_meas[0], pairs, v_true)
    v_nan = v_meas.copy()
    v_nan[0, 0] = np.nan
    with pytest.raises(ValueError, match=r"NaN|Inf"):
        logcal_gain_solve(v_nan, pairs, v_true)
    with pytest.raises(ValueError, match="bool"):
        logcal_gain_solve(v_meas > 0, pairs, v_true)
    with pytest.raises(ValueError, match=r"NaN|Inf"):
        firstcal_delay_solve(v_nan, pairs, f_axis)
    v_true_zero = v_true.copy()
    v_true_zero[0, 0] = 0.0
    with pytest.raises(ValueError, match="零元"):
        logcal_gain_solve(v_meas, pairs, v_true_zero)
    with pytest.raises(ValueError, match="零元"):
        lincal_gain_solve(v_meas, pairs, v_true_zero)
    with pytest.raises(ValueError, match="重复"):
        logcal_gain_solve(v_meas[:3], [(0, 1), (0, 1), (1, 2)], v_true[:3])
    with pytest.raises(ValueError, match="自配对"):
        logcal_gain_solve(v_meas, [(1, 1), *pairs[1:]], v_true)
    with pytest.raises(ValueError, match="越界"):
        logcal_gain_solve(v_meas, [(-1, 2), *pairs[1:]], v_true)
    with pytest.raises(ValueError, match="bool"):
        logcal_gain_solve(v_meas[:1], [(True, False)], v_true[:1])
    with pytest.raises(ValueError, match="越界"):
        logcal_gain_solve(v_meas[:3], pairs[:3], v_true[:3], ref_ant=9)
    with pytest.raises(ValueError, match="长度"):
        firstcal_delay_solve(v_meas, pairs, f_axis[:-1])
    with pytest.raises(ValueError, match="严格递增"):
        firstcal_delay_solve(v_meas, pairs, f_axis[::-1].copy())
    # 不连通（元 0 被孤立，仅 1-2-3 内部有基线）：求解类如实拒绝
    with pytest.raises(ValueError, match="不连通"):
        logcal_gain_solve(v_meas[:3], [(1, 2), (2, 3), (1, 3)], v_true[:3])
    # g_init 守卫：零增益 / 形状不配
    g0 = np.ones((4, N_FREQ), dtype=complex)
    g0[0, 0] = 0.0
    with pytest.raises(ValueError, match="零增益"):
        lincal_gain_solve(v_meas, pairs, v_true, g_init=g0)
    with pytest.raises(ValueError, match="g_init 形状"):
        lincal_gain_solve(v_meas, pairs, v_true, g_init=np.ones((3, N_FREQ), dtype=complex))
    with pytest.raises(ValueError, match="n_ant"):
        redundant_group_degeneracy(pairs, 0)
