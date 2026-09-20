"""et/ht 源参考精修列（runs/mapes_etht_refine）单测：回归钉 + 纯函数回收。

对应 core.mapes.sref_etht_column_factors（纯增量）与既有装配链 opt-in 消费：
- 回归钉：assemble_s_from_ui 缺省路径逐位不变（sref_recal=None 显式=缺省）；
- 精修列回收：合成已知非平滑 wobble → 因子精确回收（估计量语义：
  Re 通道 median、Im 通道 lstsq——精确回收用相位 wobble + 对角直构）；
- 非循环钉：因子只依赖激励口对角（扰动非对角逐位不变）；
- 守卫：et 谱线含零 / 相位卷绕 / 形状错误显式报错；
- 真机钉（无档 skip）：runs/mapes_zall_refix 三锚值 + et 因子有限。

预声明门（EFFECTIVE/MARGINAL/SATURATED）在 runs/mapes_etht_refine/criteria.md
与驱动 scripts/mapes_etht_refine.py，本文件不钉 verdict（verdict 由数据出）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.mapes import (
    apply_sref_recal,
    assemble_s_from_ui,
    delay_model_delta,
    dft_time2freq,
    sref_column_factors,
    sref_etht_column_factors,
    termination_delta,
    z_all_gate,
)

Z0 = 50.0
REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# 合成数据（自包含；探针误差构造口径与
# tests/unit/test_mapes_probe.py::_synth_probe_case 同族：e^a/e^b，a=m+Δ/2）
# --------------------------------------------------------------------------- #

def _et_spectrum_grid(nf: int, n_samples: int = 2048, dt: float = 1.0e-12):
    """et 时序的分析频轴取其采样窗的 Fourier 网格 → 谱线回收逐位精确。"""
    freqs = np.arange(1, nf + 1) / (n_samples * dt)
    t = np.arange(n_samples) * dt
    return freqs, t


def _make_et(freqs: np.ndarray, t: np.ndarray, spectrum: np.ndarray) -> np.ndarray:
    """v(t) = Σ_k Re(E_k e^{j2πf_k t}) → dft_time2freq = N·dt·E_k（网格精确）。"""
    osc = np.exp(1j * 2.0 * np.pi * np.outer(t, freqs))
    return np.sum((osc * spectrum[None, :]).real, axis=1)


def _orthogonal_phase_wobble(nf: int, rng: np.random.Generator) -> np.ndarray:
    """离散意义严格正交于 {1, f} 的实相位 wobble（Im 通道 lstsq 精确分离）。"""
    s = np.arange(nf, dtype=float)
    basis = np.vstack([np.ones(nf), s]).T
    z = rng.uniform(-1.0, 1.0, nf)
    coef, *_ = np.linalg.lstsq(basis, z, rcond=None)
    wob = z - basis @ coef
    return wob / (np.max(np.abs(wob)) + 1.0e-30)


def _diag_case(q: int, rho: np.ndarray, seed: int = 7):
    """对角直构：inc_k(f) = E(f)·exp(rho_k(f))，uf[k,k]=2·inc、if[k,k]=0。

    函数只读激励口对角组合 0.5(uf+z0·if) → 该构造把 log(inc/E) 逐位钉在
    设计 rho 上（真机 uf/if 的非对角无关量在此不出现，专测估计量本身）。
    """
    nf = rho.shape[0]
    freqs, t = _et_spectrum_grid(nf)
    rng = np.random.default_rng(seed)
    spectrum = rng.uniform(0.4, 1.0, nf) + 1j * rng.uniform(-0.4, 0.4, nf)
    et_v = _make_et(freqs, t, spectrum)
    e_exc = dft_time2freq(t, et_v, freqs)
    inc = e_exc[:, None] * np.exp(rho)  # (nf, q)
    qq = rho.shape[1]
    uf = np.zeros((qq, qq, nf), dtype=complex)
    imf = np.zeros((qq, qq, nf), dtype=complex)
    idx = np.arange(qq)
    uf[idx, idx, :] = 2.0 * inc.T
    return {"freqs": freqs, "t": t, "et_v": et_v, "uf": uf, "if": imf}


def _smooth_rho(q: int, nf: int, seed: int) -> np.ndarray:
    """纯 3 参平滑设计 rho（Re 常数 + Im 常数/斜率）。"""
    rng = np.random.default_rng(seed)
    freqs, _ = _et_spectrum_grid(nf)
    w = 2.0 * np.pi * freqs
    re_c = rng.uniform(-0.05, 0.05, q)
    im_c = rng.uniform(-0.1, 0.1, q)
    tau = rng.uniform(-2.0e-11, 2.0e-11, q)  # 步长 ≪ π/2（nf·max|τw| ≪ 1）
    return (re_c[None, :] + 1j * (im_c[None, :] + w[:, None] * tau[None, :]))


def _synth_ui_with_wobble(q: int, nf: int, *, wobble: np.ndarray | None,
                          seed: int = 11, flat_diag_gamma: bool = False):
    """互易真网络 + 探针误差的完整 uf/if；wobble 注入激励口列（inc^meas）。

    ``flat_diag_gamma=True`` 把真网络对角延时置零 → Γ_kk 逐频常数 →
    log(inc^meas/E) 除注入 wobble 外严格 3 参平滑（端到端机制钉要求：
    精修列只剥 wobble，不剥真结构）。
    """
    rng = np.random.default_rng(seed)
    freqs, t = _et_spectrum_grid(nf)
    w = 2.0 * np.pi * freqs
    spectrum = rng.uniform(0.4, 1.0, nf) + 1j * rng.uniform(-0.4, 0.4, nf)
    et_v = _make_et(freqs, t, spectrum)
    e_exc = dft_time2freq(t, et_v, freqs)
    cu = np.triu(rng.uniform(0.05, 0.9, (q, q)), k=1)
    cmat = cu + cu.T
    np.fill_diagonal(cmat, rng.uniform(0.3, 0.8, q))
    du = np.triu(rng.uniform(-2.0e-10, 2.0e-10, (q, q)), k=1)
    dmat = du + du.T
    np.fill_diagonal(dmat, rng.uniform(-1.0e-10, 1.0e-10, q))
    if flat_diag_gamma:
        np.fill_diagonal(dmat, 0.0)
        np.fill_diagonal(cmat, np.diagonal(cmat))  # 对角幅度本就逐口常数
    tm = cmat[None, :, :] * np.exp(-1j * w[:, None, None] * dmat[None, :, :])
    for f in range(nf):
        smax = float(np.linalg.norm(tm[f], ord=2))
        if smax > 0.95:
            tm[f] *= 0.95 / smax
    tau_p = rng.uniform(-0.5e-12, 0.5e-12, q)
    c_p = rng.uniform(-0.02, 0.02, q) + 1j * rng.uniform(-0.05, 0.05, q)
    delta_p = c_p[None, :] + 1j * w[:, None] * tau_p[None, :]
    m_p = ((rng.uniform(-0.01, 0.01, q)
            + 1j * rng.uniform(-0.03, 0.03, q))[None, :]
           + np.zeros((nf, 1)))
    a_p = m_p + delta_p / 2.0
    b_p = m_p - delta_p / 2.0
    uf = np.empty((q, q, nf), dtype=complex)
    imf = np.empty((q, q, nf), dtype=complex)
    for k in range(q):
        for p in range(q):
            if p == k:
                ut = e_exc * (1.0 + tm[:, k, k])
                it = e_exc * (1.0 - tm[:, k, k]) / Z0
            else:
                ut = e_exc * tm[:, p, k]
                it = -ut / Z0
            uf[k, p] = np.exp(a_p[:, p]) * ut
            imf[k, p] = np.exp(b_p[:, p]) * it
    if wobble is not None:
        # wobble 注入激励口 inc^meas（uf/if 对角同乘 → inc 精确乘 exp(wob)）
        wob = np.exp(wobble.T)[None, :, :]  # (1, q, nf)
        idx = np.arange(q)
        uf[idx, idx, :] = uf[idx, idx, :] * wob[0]
        imf[idx, idx, :] = imf[idx, idx, :] * wob[0]
    return {"freqs": freqs, "t": t, "et_v": et_v, "uf": uf, "if": imf,
            "T": tm, "delta": delta_p, "m": m_p}


# --------------------------------------------------------------------------- #
# 回归钉：既有装配链缺省路径逐位不变（硬性要求，先于精修逻辑）
# --------------------------------------------------------------------------- #

def test_assemble_default_path_bitwise_unchanged():
    """缺省 vs 显式 sref_recal=None 逐位相等；opt-in 消费与 apply_sref_recal 同效。"""
    case = _synth_ui_with_wobble(5, 6, wobble=None, seed=5)
    uf, imf = case["uf"], case["if"]
    base = assemble_s_from_ui(uf, imf, reference_impedance=Z0)
    assert np.array_equal(base, assemble_s_from_ui(
        uf, imf, reference_impedance=Z0, sref_recal=None))
    col = np.exp(0.01 * np.arange(base.shape[0])[:, None]
                 + 1j * 0.02 * np.ones((1, base.shape[1])))
    np.testing.assert_array_equal(
        assemble_s_from_ui(uf, imf, reference_impedance=Z0, sref_recal=col),
        apply_sref_recal(base, col))
    # 复合列（colC × et 型乘法复合）同样同效
    np.testing.assert_array_equal(
        assemble_s_from_ui(uf, imf, reference_impedance=Z0, sref_recal=col * col),
        apply_sref_recal(base, col * col))


# --------------------------------------------------------------------------- #
# 精修列纯函数：回收 / 恒等 / 非循环 / 守卫（对角直构，专测估计量）
# --------------------------------------------------------------------------- #

def test_etht_factor_recovery_exact_with_orthogonal_wobble():
    """合成已知相位 wobble（严格正交于 3 参拟合基）→ 因子精确回收 exp(−wob)。"""
    q, nf = 4, 21
    rng = np.random.default_rng(11)
    wob_phase = _orthogonal_phase_wobble(nf, rng)
    amp = 0.02
    wob = 1j * amp * wob_phase[:, None] + np.zeros((1, q))  # (nf, q) 纯相位
    rho = _smooth_rho(q, nf, seed=3) + wob
    case = _diag_case(q, rho, seed=13)
    factors, info = sref_etht_column_factors(
        case["uf"], case["if"], case["freqs"], case["t"], case["et_v"],
        reference_impedance=Z0)
    assert factors.shape == (nf, q)
    # 符号口径：列污染进分母（S = S_true·e^{−wob}），修正回乘 exp(+wob)
    np.testing.assert_allclose(factors, np.exp(wob), rtol=0, atol=1e-12)
    # wobble_resid_max = max|log r − r̂| = 注入 wobble 幅度本身（被因子剥离）
    assert amp * 0.99 < info["wobble_resid_max"] < amp * 1.01
    assert np.all(np.isfinite(factors))


def test_etht_identity_case_factors_are_unity():
    """无 wobble（r_k 纯 3 参平滑）→ 因子 ≡ 1（修正中性）。"""
    q, nf = 4, 15
    case = _diag_case(q, _smooth_rho(q, nf, seed=17), seed=19)
    factors, info = sref_etht_column_factors(
        case["uf"], case["if"], case["freqs"], case["t"], case["et_v"],
        reference_impedance=Z0)
    np.testing.assert_allclose(factors, np.ones_like(factors), rtol=0, atol=1e-12)
    assert info["wobble_resid_max"] < 1e-12


def test_etht_factors_diagonal_only_noncircular():
    """非循环钉：因子只依赖激励口对角——扰动全部非对角档 → 因子逐位不变。"""
    case = _synth_ui_with_wobble(5, 9, wobble=None, seed=19)
    rng = np.random.default_rng(23)
    q = case["uf"].shape[0]
    off3 = np.broadcast_to((~np.eye(q, dtype=bool))[:, :, None], case["uf"].shape)
    uf2 = case["uf"].copy()
    imf2 = case["if"].copy()
    pert = np.exp(1j * rng.uniform(-0.4, 0.4, uf2.shape))
    uf2[off3] *= pert[off3]
    imf2[off3] *= pert[off3]
    f1, _ = sref_etht_column_factors(
        case["uf"], case["if"], case["freqs"], case["t"], case["et_v"],
        reference_impedance=Z0)
    f2, _ = sref_etht_column_factors(
        uf2, imf2, case["freqs"], case["t"], case["et_v"],
        reference_impedance=Z0)
    assert np.array_equal(f1, f2)


def test_etht_endtoend_reduces_reciprocity_residual():
    """端到端：激励口列注入逐口独立 wobble → wav+colC+et 残差严格低于 wav+colC。

    flat_diag_gamma（Γ_kk 逐频常数）下 log(inc/E) 除注入 wobble 外严格平滑 →
    精修列应精确剥 wobble；wobble 逐口独立（互易差分中不相消，区别于
    共模式 m 规范）。残差不要求归零：cosh(Δ/2) 行侧与 m 规范如实保留。
    """
    q, nf, amp = 6, 25, 0.05
    rng = np.random.default_rng(29)
    wob = 1j * amp * np.stack(
        [_orthogonal_phase_wobble(nf, rng) for _ in range(q)], axis=1)
    case = _synth_ui_with_wobble(q, nf, wobble=wob, seed=31, flat_diag_gamma=True)
    uf, imf, freqs = case["uf"], case["if"], case["freqs"]
    s_wav = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="wave")
    et, _ = sref_etht_column_factors(
        uf, imf, freqs, case["t"], case["et_v"], reference_impedance=Z0)
    # 机制钉：wobble-free 孪生档比值精确回收 exp(−wob)——两档共享全部结构性
    # 分量（logC 的 O(Δ²) 残留等），因子之差只剩 wobble（Re 通道 median 与
    # Im 通道 LS 对纯虚正交 wobble 均不受扰）。
    case0 = _synth_ui_with_wobble(q, nf, wobble=None, seed=31, flat_diag_gamma=True)
    et0, _ = sref_etht_column_factors(
        case0["uf"], case0["if"], freqs, case0["t"], case0["et_v"],
        reference_impedance=Z0)
    np.testing.assert_allclose(et / et0, np.exp(wob), rtol=0, atol=1e-9)
    # 列误差剥离钉（wav 口径，不含 colC——colC 的 Γ̂ 反演从受污对角部分吸收
    # 列误差，属真机门裁度而非单测断言）：逐口独立 wobble 在互易差分中
    # 不相消，剥离后残差严格回落。
    base = z_all_gate(s_wav)
    refined = z_all_gate(apply_sref_recal(s_wav, et))
    assert base["reciprocity_max"] > refined["reciprocity_max"]
    assert refined["reciprocity_max"] < 0.9 * base["reciprocity_max"]
    # 复合消费布线钉：colC × et 经 opt-in 参数与 apply_sref_recal 同效
    delta, _ = termination_delta(uf, imf, reference_impedance=Z0)
    colc = sref_column_factors(delta, np.diagonal(s_wav, axis1=1, axis2=2))
    np.testing.assert_array_equal(
        assemble_s_from_ui(uf, imf, reference_impedance=Z0,
                           numerator="wave", sref_recal=colc * et),
        apply_sref_recal(s_wav, colc * et))


def test_etht_guards_reject_degenerate_inputs():
    """守卫：et 谱零 / 相位卷绕 / 形状错 / 非有限 → ConfigError 不静默退化。"""
    case = _synth_ui_with_wobble(4, 9, wobble=None, seed=37)
    uf, imf, freqs, t, et_v = (
        case["uf"], case["if"], case["freqs"], case["t"], case["et_v"])
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf, imf, freqs, t, np.zeros_like(et_v),
                                 reference_impedance=Z0)
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf, imf, freqs[:-1], t, et_v,
                                 reference_impedance=Z0)
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf[:, :3, :], imf[:, :3, :], freqs, t, et_v,
                                 reference_impedance=Z0)
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf, imf, freqs, t, et_v[:-1],
                                 reference_impedance=Z0)
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf, imf, freqs, t, et_v, reference_impedance=-1.0)
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf, imf, freqs, np.full_like(t, np.nan), et_v,
                                 reference_impedance=Z0)
    # 相位卷绕（轨迹穿越 ±π）：τ=1.5ns 使总跨度 >π 而逐频步 <π/2
    #（存储 angle 出现 ~2π 级跳变）→ 表观步守卫捕获；
    # 真实步 >π 的混叠表观上不可分（core docstring 如实声明），不在测试面。
    q, nf = 3, 9
    rng = np.random.default_rng(41)
    freqs2, t2 = _et_spectrum_grid(nf)
    spec = rng.uniform(0.5, 1.0, nf) + 1j * 0.1
    et2 = _make_et(freqs2, t2, spec)
    e_exc = dft_time2freq(t2, et2, freqs2)
    rho = 1j * 2.0 * np.pi * freqs2[:, None] * 1.5e-10 + np.zeros((1, q))
    inc = e_exc[:, None] * np.exp(rho)
    uf3 = np.zeros((q, q, nf), dtype=complex)
    imf3 = np.zeros((q, q, nf), dtype=complex)
    idx = np.arange(q)
    uf3[idx, idx, :] = 2.0 * inc.T
    with pytest.raises(ConfigError):
        sref_etht_column_factors(uf3, imf3, freqs2, t2, et2, reference_impedance=Z0)


def test_etht_delay_model_reuse_consistency():
    """复用钉：info.tau_s 与对 log(inc/E) 直接 delay_model_delta 拟合逐位一致。"""
    case = _synth_ui_with_wobble(4, 17, wobble=None, seed=43)
    uf, imf, freqs = case["uf"], case["if"], case["freqs"]
    factors, info = sref_etht_column_factors(
        uf, imf, freqs, case["t"], case["et_v"], reference_impedance=Z0)
    e_dft = dft_time2freq(case["t"], case["et_v"], freqs)
    idx = np.arange(uf.shape[0])
    inc = 0.5 * (uf[idx, idx, :] + Z0 * imf[idx, idx, :])
    rho = np.log(inc / e_dft[None, :]).T
    rhohat, fit = delay_model_delta(rho, freqs)
    np.testing.assert_array_equal(np.asarray(info["tau_s"]), fit["tau_s"])
    np.testing.assert_allclose(factors, np.exp(rho - rhohat), rtol=0, atol=0)
    np.testing.assert_allclose(np.asarray(info["e_dft"]), e_dft, rtol=0, atol=0)


# --------------------------------------------------------------------------- #
# 真机钉（runs/mapes_zall_refix；无档机器 skip 不算绿）
# --------------------------------------------------------------------------- #

def test_refix150_etht_chain_realdata_pin():
    """150 轮真机档钉：三锚值逐位复现 + et 因子有限 + 精修档可计算。"""
    raw_npz = REPO / "runs" / "mapes_zall_refix" / "s5_diag" / "raw_ui.npz"
    et_path = REPO / "runs" / "mapes_zall_refix" / "rounds" / "p1" / "fdtd" / "et"
    if not (raw_npz.exists() and et_path.exists()):
        pytest.skip("真机档 runs/mapes_zall_refix 不在本机")
    with np.load(raw_npz) as data:
        uf = np.asarray(data["uf_all"], dtype=complex)
        imf = np.asarray(data["if_all"], dtype=complex)
        freqs = np.asarray(data["freq_hz"], dtype=float)
    dump = np.loadtxt(str(et_path))
    s_cur = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="current")
    s_wav = assemble_s_from_ui(uf, imf, reference_impedance=Z0, numerator="wave")
    assert z_all_gate(s_cur)["reciprocity_max"] == pytest.approx(
        0.014603526405276387, rel=1e-9)
    assert z_all_gate(s_wav)["reciprocity_max"] == pytest.approx(
        0.00896490993934581, rel=1e-9)
    delta, _ = termination_delta(uf, imf, reference_impedance=Z0)
    colc = sref_column_factors(delta, np.diagonal(s_wav, axis1=1, axis2=2))
    base = z_all_gate(apply_sref_recal(s_wav, colc))
    assert base["reciprocity_max"] == pytest.approx(0.0070773704118137, rel=1e-9)
    et_factors, info = sref_etht_column_factors(
        uf, imf, freqs, dump[:, 0], dump[:, 1], reference_impedance=Z0)
    assert np.all(np.isfinite(et_factors))
    refined = z_all_gate(apply_sref_recal(s_wav, colc * et_factors))
    assert np.isfinite(refined["reciprocity_max"])
    # wobble 量级如实钉（锚定后若档变动此处如实更新，不预设改善方向）
    assert info["wobble_resid_max"] < 0.5
