"""F-E.5 PAPR 内核单测（研究扩充 round3 F-E 表件 5 判据）。

裁判口径（#118，先测后钉）：解析公式本身的裁判=合成 OFDM 蒙特卡洛
（随机 QPSK/16QAM + IFFT + 固定 seed，本文件实测后钉阈值）；求逆的裁判=
闭式/数值二分/scipy brentq 三路互证；EVM 闭式的裁判=scipy.integrate.quad
独立积分。固定 seed（20260927）在同一 numpy 版本下逐位可复现，容差仅
为跨版本漂移留余量。

seed=20260927、临界采样、n=4×10⁵ 符号的实测相对误差表（MC−解析）/解析
（%，σ_rel 为二项统计地板）::

    p        N=256 rel   N=64 rel      σ_rel%(N=256)
    2e-1      -1.10       -3.49          0.32
    1e-1      -2.42       -8.84          0.47
    5e-2      -3.96      -12.22          0.69
    2e-2      -5.46      -15.54          1.11
    1e-2      -6.20      -21.05          1.57
    5e-3      -7.85      -24.85          2.23
    2e-3     -11.00      -30.87          3.53
    1e-3     -14.75      -30.00          5.00

任务书判据的三处如实登记（#122，不凑绿）：
1. "γ=0→P=0" 与任务书自己的公式 1−(1−e^(−γ))^N 不自洽：CCDF(γ_lin→0+)=1
   （PAPR 恒>0），γ=0→P=0 是 **CDF 侧**极限 F(0)=0。本文件按公式自洽的
   可达恒等式钉（N=1 逐位 Rayleigh、γ→∞→0、F(0)=0）。
2. "N=1024 时 P≈e^(−γ) rel≤1e-3@γ≥10dB" 按公式自检不可能成立（γ_lin=10
   处 P≈N·e^(−γ)，比 e^(−γ) 大约 N 倍）。真渐近（Rayleigh 尾/Poisson 小量
   1−(1−x)^N≈Nx，相对误差≈(N−1)e^(−γ)/2）按 γ_lin≥20 钉 rel≤1e-3，并把
   γ_lin=10 的边界值（~2.3%>1e-3）一并钉住。
3. "MC rel≤5%@CCDF∈[1e-3,1e-1]，N≥64" 只能部分成立：满带 OFDM 样点功率
   受 Parseval 恒等 Σ|x_k|²=const 约束（负相关），公式系统性**高于** MC；
   N=256 在 p∈[0.05,0.2] 子带内 |rel|≤4%（≤5% 判据成立，含统计余量），
   p≤2e-3 偏差 −11%~−15%（系统性远超 σ_rel，加大样本不消失）。2000 符号
   锚定场景按 4σ+5% 统计包络钉（尾部 σ_rel@1e-3=71%，5% 点判在统计上
   不可实现）。以上如实 PARTIAL，不调参凑绿。
"""
from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import papr
from rfauto.service import papr_service

SEED = papr.PAPR_MC_DEFAULT_SEED


# ─── 1. dB/线性换算 ──────────────────────────────────────────────────────────


def test_papr_lin_db_roundtrip():
    assert papr.papr_lin_of_db(0.0) == 1.0
    assert papr.papr_lin_of_db(10.0) == pytest.approx(10.0, rel=1e-14)
    assert papr.papr_db_of_lin(2.0) == pytest.approx(10.0 * math.log10(2.0), rel=1e-15)
    for g in (0.5, 6.02, 11.3):
        assert papr.papr_db_of_lin(papr.papr_lin_of_db(g)) == pytest.approx(g, rel=1e-12)
    with pytest.raises(ValueError):
        papr.papr_lin_of_db(-0.5)
    with pytest.raises(ValueError):
        papr.papr_lin_of_db(True)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        papr.papr_db_of_lin(0.0)


# ─── 2. 解析 CCDF：恒等式 + 渐近 + 独立实现对照 ──────────────────────────────


def test_ccdf_n1_rayleigh_bitwise():
    # N=1：1−(1−e^(−γ))^1 = e^(−γ) 恒等，内核短路保逐位（单样点 Rayleigh 尾）
    for g in (0.0, 0.7, 3.0103, 10.0, 20.0, 40.0):
        assert papr.ccdf_analytic(g, 1, 1.0) == math.exp(-(10.0 ** (g / 10.0)))
    # α=1 的浮点路径下 N=1 恒等也逐位（N_eff==1.0 判定）
    assert papr.ccdf_analytic(6.0, 1.0, 1.0) == math.exp(-10.0**0.6)


def test_ccdf_gamma0_and_cdf_limit():
    # 登记口径（文件头 #122-1）：CCDF(γ_lin→0+)=1、CDF(γ_db=0 处)=(1−e^(−1))^N
    c0 = papr.ccdf_analytic(0.0, 64)
    expected = 1.0 - (1.0 - math.exp(-1.0)) ** 64.0  # 测试侧独立表达式
    assert c0 == pytest.approx(expected, rel=1e-12)
    assert 0.0 < c0 < 1.0  # N=64 时为内点（N=1024 起 1−(1−e^(−1))^N 浮点饱和为 1.0）
    assert papr.ccdf_analytic(0.0, 1024) == 1.0  # 饱和钉：1−1e-204 逐位为 1.0
    # N=1 退化：CCDF(0 dB)=e^(−1) 逐位
    assert papr.ccdf_analytic(0.0, 1) == math.exp(-1.0)


def test_ccdf_monotone_and_unit_range():
    for n, a in ((64, 1.0), (256, 2.5), (1024, 1.0)):
        grid = [0.0, 2.0, 5.0, 8.0, 12.0]
        vals = [papr.ccdf_analytic(g, n, a) for g in grid]
        assert all(0.0 <= v <= 1.0 for v in vals)
        # 全程非增；N_eff 大时近 0 dB 端 CCDF 浮点饱和为 1.0（1−N_eff·e^(−1) 下溢），
        # 严格递减只对 <1.0 的内点断言
        assert all(v1 >= v2 for v1, v2 in pairwise(vals))
        interior = [v for v in vals if v < 1.0]
        assert all(v1 > v2 for v1, v2 in pairwise(interior))
        # 深尾（γ_lin≥100 起 N=1024 亦饱和）非增即可（−0.0 == 0.0）
        tail = [papr.ccdf_analytic(g, n, a) for g in (12.0, 20.0, 35.0)]
        assert all(t1 >= t2 for t1, t2 in pairwise(tail))
        assert all(0.0 <= t <= vals[-1] + 1e-300 for t in tail)
    # γ→∞ → P→0（γ_lin=1e4 处 e^(−γ) 下溢，公式稳定给 0 不出 NaN）
    assert papr.ccdf_analytic(40.0, 64) == 0.0


def test_ccdf_alpha_identity_and_direction():
    # 恒等式：CCDF(γ, N=64, α=2) == CCDF(γ, N=128, α=1)（N_eff 同为 128，逐位）
    for g in (0.0, 5.0, 10.0):
        assert papr.ccdf_analytic(g, 64, 2.0) == papr.ccdf_analytic(g, 128, 1.0)
    # 方向：α↑（等效样点更多）→ 同门限超越概率↑
    assert papr.ccdf_analytic(8.0, 64, 2.0) > papr.ccdf_analytic(8.0, 64, 1.0)


def test_ccdf_large_n_poisson_tail_asymptote():
    # 登记口径（文件头 #122-2）：真渐近是 P≈N·e^(−γ)（Poisson 小量）
    for g_lin in (20.0, 40.0):
        got = papr.ccdf_analytic(10.0 * math.log10(g_lin), 1024)
        ref = 1024.0 * math.exp(-g_lin)
        assert abs(got - ref) / ref <= 1e-3
    # 边界演示：γ_lin=10（10 dB）处渐近尚未进入 1e-3 域（相对偏差 ~2.3%）
    got10 = papr.ccdf_analytic(10.0, 1024)
    ref10 = 1024.0 * math.exp(-10.0)
    assert 1e-3 < abs(got10 - ref10) / ref10 < 0.05


def test_ccdf_vs_independent_implementation():
    # 数值路径双查：expm1/log 稳定路径 vs 测试侧直算 (1−e^(−γ))**M（γ≤30 dB 无病态）
    for n, a in ((64, 1.0), (256, 2.5), (7, 3.0)):
        for g in np.linspace(0.0, 30.0, 31):
            got = papr.ccdf_analytic(float(g), n, a)
            direct = 1.0 - (1.0 - math.exp(-(10.0 ** (float(g) / 10.0)))) ** (n * a)
            assert got == pytest.approx(direct, rel=1e-9)


def test_ccdf_input_guards():
    for n_bad in (0, -1, 2.5, True, float("nan")):
        with pytest.raises(ValueError):
            papr.ccdf_analytic(6.0, n_bad)
    for g_bad in (-0.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            papr.ccdf_analytic(g_bad, 64)
    for a_bad in (0.9, 0.0, -1.0, float("nan"), True):
        with pytest.raises(ValueError):
            papr.ccdf_analytic(6.0, 64, a_bad)


# ─── 3. 门限求逆（PRNT）：闭式/数值/brentq 三路 + 往返 ────────────────────────


_COMBOS = ((1, 1.0), (2, 1.0), (64, 1.0), (64, 2.5), (256, 4.0))
# p≤0.1 ⇒ N=1 时 γ_lin=−ln(p)≥2.3（γ_db>0），可安全走 γ_db≥0 的 CCDF 接口往返
_PROBS = (0.1, 1e-2, 1e-3, 1e-4, 1e-6)


@pytest.mark.parametrize("n,a", _COMBOS)
@pytest.mark.parametrize("p", _PROBS)
def test_threshold_roundtrip_tol_1e10(n: int, a: float, p: float):
    # 任务书判据：γ_p 求逆后回代 CCDF(γ_p)=p（tol 1e-10；实测 ~1e-16）
    g_db = papr.papr_threshold_db(p, n, a)
    assert abs(papr.ccdf_analytic(g_db, n, a) - p) <= 1e-10


def test_threshold_below_zero_db_linear_identity():
    # N=1、p>e^(−1) 的门限合法地落在 0 dB 以下（CCDF(0 dB)=e^(−1)≈0.368）：
    # dB 接口守卫（γ_db≥0，规格边界）不拦求逆输出——用线性域恒等式 e^(−γ)=p 钉
    for p in (0.5, 0.7, 0.9):
        g_db = papr.papr_threshold_db(p, 1, 1.0)
        assert g_db < 0.0
        g_lin = 10.0 ** (g_db / 10.0)
        assert math.exp(-g_lin) == pytest.approx(p, rel=1e-12)


def test_threshold_analytic_anchor_n1():
    # 手算锚：N=1、p=e^(−2) → e^(−γ)=p → γ_lin=2 → 3.0103 dB（独立推导）
    g_db = papr.papr_threshold_db(math.exp(-2.0), 1, 1.0)
    assert g_db == pytest.approx(10.0 * math.log10(2.0), rel=1e-12)


def test_threshold_numeric_matches_closed_form():
    for n, a in _COMBOS:
        for p in (0.01, 1e-3, 1e-4):
            closed = papr.papr_threshold_db(p, n, a)
            numeric = papr.papr_threshold_db_numeric(p, n, a)
            assert numeric == pytest.approx(closed, rel=1e-9)
            assert abs(papr.ccdf_analytic(numeric, n, a) - p) <= 1e-10
    # p=0.5（N≥2 时 γ_db>0 可回代）
    for n, a in ((2, 1.0), (64, 1.0), (256, 4.0)):
        closed = papr.papr_threshold_db(0.5, n, a)
        assert papr.papr_threshold_db_numeric(0.5, n, a) == pytest.approx(closed, rel=1e-9)
        assert abs(papr.ccdf_analytic(closed, n, a) - 0.5) <= 1e-10


def test_threshold_prnt_brentq_crosscheck():
    pytest.importorskip("scipy")
    from scipy.optimize import brentq

    assert papr.PRNT_PROBABILITY == 1e-4
    # 独立求根器对照闭式（N=64，α=1）
    g_closed = papr.prnt_db(64)
    g_brent = brentq(lambda g: papr.ccdf_analytic(g, 64, 1.0) - 1e-4, 0.0, 40.0)
    assert g_closed == pytest.approx(g_brent, rel=1e-9)
    assert g_closed == pytest.approx(11.2610458330, rel=1e-9)  # 实测钉（seed 无关，纯闭式）
    # α 修正方向：过采样 → PRNT 更高
    assert papr.prnt_db(64, 4.0) > g_closed


def test_threshold_guards():
    for p_bad in (0.0, 1.0, -0.1, 1.1, float("nan"), True):
        with pytest.raises(ValueError):
            papr.papr_threshold_db(p_bad, 64)
    with pytest.raises(ValueError):
        papr.papr_threshold_db(0.01, 0)
    with pytest.raises(ValueError):
        papr.papr_threshold_db(0.01, 64, 0.5)
    with pytest.raises(ValueError):
        papr.papr_threshold_db_numeric(0.0, 64)


# ─── 4. 蒙特卡洛 CCDF（裁判路径；阈值预声明见文件头实测表）────────────────────


def test_mc_seed_determinism():
    # 同 seed 逐位复现；不同 seed 经验计数不同（门限网格是纯闭式、逐位同）
    r1 = papr.ccdf_monte_carlo(64, 500, 1, "qpsk", 11, p_grid=(0.2, 0.1))
    r2 = papr.ccdf_monte_carlo(64, 500, 1, "qpsk", 11, p_grid=(0.2, 0.1))
    r3 = papr.ccdf_monte_carlo(64, 500, 1, "qpsk", 12, p_grid=(0.2, 0.1))
    assert r1.to_dict() == r2.to_dict()
    assert np.array_equal(r1.gamma_grid_db, r3.gamma_grid_db)
    assert not np.array_equal(r1.n_exceed, r3.n_exceed)
    # 波形出口逐位确定性
    w1 = papr.ofdm_symbols(16, 3, 2, "16qam", 11)
    w2 = papr.ofdm_symbols(16, 3, 2, "16qam", 11)
    assert np.array_equal(w1, w2)


def test_mc_gate_analytic_band_5pct():
    # 5% 门（预声明成立子带 p∈[0.05,0.2]@N=256，n=4×10⁵：实测 −1.1~−4.0%）
    r256 = papr.ccdf_monte_carlo(
        256, 400_000, 1, "qpsk", SEED,
        p_grid=(0.2, 0.1, 0.05, 0.02, 0.01, 5e-3, 2e-3, 1e-3),
    )
    rel = r256.rel_errors()
    for i in range(3):  # p = 0.2, 0.1, 0.05
        assert abs(rel[i]) <= 0.05
    # 全带方向+包络：公式系统性高于 MC（Parseval 满带约束），幅度 ≤25%
    assert np.all(rel <= 1e-12)  # 全部 ≤0（MC 不高于解析）
    assert np.all(rel >= -0.25)
    # 大 N 收敛方向：同点 N=256 的偏差小于 N=64（实测 −2.4% vs −8.8%@p=0.1）
    r64 = papr.ccdf_monte_carlo(64, 400_000, 1, "qpsk", SEED, p_grid=(0.2, 0.1))
    assert abs(r64.rel_errors()[1]) > abs(rel[1])


def test_mc_spec_anchor_2000x256_statistical_envelope():
    # 任务书锚定场景：seed 固定 2000 符号×N=256——按 4σ+5% 统计包络钉
    # （文件头 #122-3：尾部 5% 点判在 n=2000 下统计不可实现，如实 PARTIAL）
    r = papr.ccdf_monte_carlo(256, 2000, 1, "qpsk", SEED, p_grid=(0.2, 0.1, 0.05, 0.02, 0.01))
    for i, p in enumerate(r.p_grid):
        sigma = math.sqrt(p * (1.0 - p) / r.n_symbols)
        assert abs(r.ccdf_empirical[i] - r.ccdf_analytic[i]) <= 4.0 * sigma + 0.05 * p
        # 方向：经验 CCDF 不高于解析（满带约束方向，5 点全负实测）
        assert r.ccdf_empirical[i] <= r.ccdf_analytic[i]


def test_mc_qpsk_16qam_consistency():
    # 星座无关性（CLT 域）：同门限下两调制的经验 CCDF 差 ≤4(σ_q+σ_16)
    rq = papr.ccdf_monte_carlo(64, 50_000, 1, "qpsk", SEED, p_grid=(0.2, 0.1, 0.05, 0.02))
    r16 = papr.ccdf_monte_carlo(64, 50_000, 1, "16qam", SEED, p_grid=(0.2, 0.1, 0.05, 0.02))
    assert np.array_equal(rq.gamma_grid_db, r16.gamma_grid_db)
    for i, p in enumerate(rq.p_grid):
        bound = 4.0 * (
            math.sqrt(p * (1.0 - p) / rq.n_symbols) + math.sqrt(p * (1.0 - p) / r16.n_symbols)
        )
        assert abs(rq.ccdf_empirical[i] - r16.ccdf_empirical[i]) <= bound


def test_mc_oversampled_bracket():
    # 过采样口径（van Nee α·N 启发式）：真实 CCDF ∈ [公式(α=1), 公式(α=L)]
    # 实测（N=64、L=4、n=1e5）：MC 严格介于两闭式之间且余量大
    ro = papr.ccdf_monte_carlo(64, 100_000, 4, "qpsk", SEED, p_grid=(0.1, 0.05, 0.02, 0.01))
    f_lo = np.array([papr.ccdf_analytic(g, 64, 1.0) for g in ro.gamma_grid_db])
    f_hi = ro.ccdf_analytic  # 构造上 == p_grid
    assert np.all(f_lo < ro.ccdf_empirical)
    assert np.all(ro.ccdf_empirical < f_hi)


# ─── 5. EVM 闭式与 CFR 软削峰 ────────────────────────────────────────────────


def test_evm_closed_form_edges_and_monotone():
    assert papr.evm_clip_gauss_closed_form(0.0) == 1.0  # a=0：削到零 → EVM²=1
    assert papr.evm_clip_gauss_closed_form(1e6) == pytest.approx(0.0, abs=1e-12)
    vals = [papr.evm_clip_gauss_closed_form(a) for a in (0.0, 0.25, 1.0, 4.0, 16.0)]
    assert all(v >= 0.0 for v in vals)
    assert all(v1 > v2 for v1, v2 in pairwise(vals))  # 单调递减
    with pytest.raises(ValueError):
        papr.evm_clip_gauss_closed_form(-1.0)
    with pytest.raises(ValueError):
        papr.evm_clip_gauss_closed_form(True)


def test_evm_closed_form_quad_crosscheck():
    # 独立路径 B：scipy.quad 直接数值积分 E[(|x|−A)⁺²]/E|x|² 的 Rayleigh 积分式
    pytest.importorskip("scipy")
    from scipy.integrate import quad

    for a in (0.25, 1.0, 4.0):

        def integrand(u: float, a: float = a) -> float:
            return (math.sqrt(u) - math.sqrt(a)) ** 2 * math.exp(-u)

        val, _ = quad(integrand, a, np.inf)
        closed = papr.evm_clip_gauss_closed_form(a)
        assert val == pytest.approx(closed, rel=1e-8)


def test_evm_numerical_vs_closed_form():
    # 复高斯参考信号：数值 E[(|x|−A)⁺²]/E|x|² 对照闭式（n=2²¹，统计地板内）
    rng = np.random.default_rng(7)
    n = 1 << 21
    z = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / math.sqrt(2.0)
    p_mean = float(np.mean(np.abs(z) ** 2))
    for a, tol in ((1.0, 5e-3), (4.0, 2.5e-2)):
        amp = math.sqrt(a * p_mean)
        excess = np.maximum(np.abs(z) - amp, 0.0)
        evm2_num = float(np.mean(excess**2)) / p_mean
        assert evm2_num == pytest.approx(papr.evm_clip_gauss_closed_form(a), rel=tol)


def test_cfr_clip_target_identity_and_evm_nonneg():
    # 端到端：16QAM OFDM 波形削 1 dB——达标恒等式（削后无样点超目标包络）
    x = papr.ofdm_symbols(64, 4, 2, "16qam", SEED).ravel()
    above = papr.cfr_soft_clip(x, 100.0)  # 远超峰值 → 不削（见 noclip 测试）
    target_db = above.papr_before_db - 1.0
    res = papr.cfr_soft_clip(x, target_db)
    target_lin = 10.0 ** (target_db / 10.0)
    p_mean = float(np.mean(np.abs(x) ** 2))
    assert res.target_met is True
    assert float(np.max(np.abs(res.clipped) ** 2)) <= target_lin * p_mean * (1.0 + 1e-12)
    assert res.evm_rms >= 0.0
    assert res.evm_db is not None and res.evm_db < 0.0
    assert 0.0 < res.clip_frac < 1.0
    assert 0.0 < res.power_reduction_frac < 1.0
    # 削后自归一 PAPR 因功率回退可略超目标（如实报告语义，非失败）
    assert res.papr_after_db >= res.papr_target_db - 1e-9
    assert res.papr_before_db == pytest.approx(above.papr_before_db)


def test_cfr_no_clip_bitwise_identity():
    # 目标高于当前峰值：不削——波形逐位不变、EVM=0（evm_db=None）、零功率回退
    x = papr.ofdm_symbols(64, 4, 2, "qpsk", SEED).ravel()
    res = papr.cfr_soft_clip(x, 200.0)
    assert np.array_equal(res.clipped, x)
    assert res.evm_rms == 0.0
    assert res.evm_db is None  # 20log10(0) 无定义，判缺失 is not None
    assert res.clip_frac == 0.0
    assert res.power_reduction_frac == 0.0
    assert res.target_met is True
    assert res.papr_after_db == res.papr_before_db  # 逐位


def test_cfr_guards():
    x = papr.ofdm_symbols(32, 2, 1, "qpsk", SEED).ravel()
    with pytest.raises(ValueError):
        papr.cfr_soft_clip(np.array([], dtype=complex), 6.0)
    with pytest.raises(ValueError):
        papr.cfr_soft_clip(x.reshape(2, -1), 6.0)  # 二维拒绝
    with pytest.raises(ValueError):
        papr.cfr_soft_clip(x * float("nan"), 6.0)
    x_inf = x.copy()
    x_inf[0] = complex(math.inf, 0.0)  # 显式注入非有限样点（x*inf 会有 0×inf 告警）
    with pytest.raises(ValueError):
        papr.cfr_soft_clip(x_inf, 6.0)
    with pytest.raises(ValueError):
        papr.cfr_soft_clip(np.zeros_like(x), 6.0)  # 全零波形无法标定包络
    for t_bad in (0.0, -1.0, float("nan"), True):
        with pytest.raises(ValueError):
            papr.cfr_soft_clip(x, t_bad)


# ─── 6. dataclass JSON 面 + service 薄壳信封 ─────────────────────────────────


def test_dataclasses_to_dict_json_roundtrip():
    mc = papr.ccdf_monte_carlo(64, 100, 2, "qpsk", SEED, p_grid=(0.2, 0.01))
    d1 = mc.to_dict()
    assert json.loads(json.dumps(d1))["n_symbols"] == 100
    assert len(d1["gamma_grid_db"]) == 2
    x = papr.ofdm_symbols(32, 2, 1, "qpsk", SEED).ravel()
    cf = papr.cfr_soft_clip(x, 6.0)
    d2 = cf.to_dict()
    assert "clipped" not in d2  # 波形数组不进 to_dict
    assert json.loads(json.dumps(d2))["n_samples"] == x.size


def test_service_ok_envelopes():
    # ccdf 标量/列表
    out = papr_service.papr_ccdf_eval({"gamma_db": 6.0, "n_subcarriers": 64})
    assert out["ok"] is True
    assert out["ccdf"] == pytest.approx(papr.ccdf_analytic(6.0, 64), rel=1e-15)
    out_l = papr_service.papr_ccdf_eval({"gamma_db": [0.0, 6.0], "n_subcarriers": 64, "alpha": 2.0})
    assert len(out_l["ccdf"]) == 2
    # threshold（PRNT 语义）
    out_t = papr_service.papr_threshold_eval({"prob": 1e-4, "n_subcarriers": 64})
    assert out_t["papr_db"] == pytest.approx(papr.prnt_db(64), rel=1e-15)
    # mc（小规模）
    out_m = papr_service.papr_monte_carlo_eval({"n_subcarriers": 64, "n_symbols": 500})
    assert out_m["ok"] is True and out_m["result"]["n_symbols"] == 500
    # cfr（高目标 → 不削 → evm_db=null）
    x = papr.ofdm_symbols(32, 2, 1, "qpsk", SEED).ravel()
    pairs = [[float(s.real), float(s.imag)] for s in x]
    out_c = papr_service.papr_cfr_eval({"samples": pairs, "papr_target_db": 100.0})
    assert out_c["ok"] is True
    assert out_c["result"]["evm_db"] is None
    assert out_c["result"]["target_met"] is True
    for env in (out, out_l, out_t, out_m, out_c):
        assert env["schema_version"] == papr_service.PAPR_SERVICE_SCHEMA_VERSION


def test_service_error_envelopes_never_raise():
    bad_payloads = [
        ("ccdf", "not-a-dict"),
        ("ccdf", {"n_subcarriers": 64}),  # 缺 gamma_db
        ("ccdf", {"gamma_db": True, "n_subcarriers": 64}),
        ("ccdf", {"gamma_db": -1.0, "n_subcarriers": 64}),  # 内核边界 γ_db<0
        ("ccdf", {"gamma_db": 6.0, "n_subcarriers": 0}),  # N<1
        ("ccdf", {"gamma_db": 6.0, "n_subcarriers": 64, "alpha": 0.5}),  # α<1
        ("threshold", {"prob": 1.0, "n_subcarriers": 64}),  # p 开区间
        ("threshold", "junk"),
        ("mc", {"n_subcarriers": 64, "n_symbols": 300_000}),  # 服务封顶
        ("mc", {"n_subcarriers": 64, "modulation": "256qam"}),
        ("cfr", {"papr_target_db": 6.0}),  # 缺 samples
        ("cfr", {"samples": [[1.0, 2.0, 3.0]], "papr_target_db": 6.0}),
        ("cfr", {"samples": [], "papr_target_db": 6.0}),
        ("cfr", {"samples": [[True, 0.0]], "papr_target_db": 6.0}),
    ]
    dispatch = {
        "ccdf": papr_service.papr_ccdf_eval,
        "threshold": papr_service.papr_threshold_eval,
        "mc": papr_service.papr_monte_carlo_eval,
        "cfr": papr_service.papr_cfr_eval,
    }
    for name, payload in bad_payloads:
        out = dispatch[name](payload)  # 不抛即为过
        assert out["ok"] is False, f"{name}: {payload!r}"
        assert out["errors"], f"{name}: errors 空"
