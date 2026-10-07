"""Phase 4 W4-E 锚批回归钉（10 锚 8 族；ra_criteria §七 UX-B1 档①+X5 二批）。

锚册：knowledge/anchors.yaml W4-E 批（2026-10-05，49→59 席）——cps×2
（Wadell/Gupta-Ghione 共形链×C9 γ(εr) FD 定标）/suspended_stripline×2
（Cohn+softmin 串联饱和修正族）/cheb_g×5（MYJ Table 4.05-1 0.1dB 档表值×
Pozar §8.4 递推双源）/msl_cpw×1（同阻异模理想级联 S11(f0)=0）。

本文件每锚两类钉（#118 禁同源自证）：
1. **独立重算钉**：文献公式在测试内**第二实现转录**（不 import 内核公式/
   系数表），与锚值对拍；内核值另与第二实现对拍（抓转录/回归错）；
2. **注册表钉**：resolve_anchor 域内命中、值/单位/形态一致；analytic 档
   形态=engine_pair.calibrated="closedform"（与引擎档可区分，#122）。

候选裁决（宁少勿滥）：cpw 模型二义（CPWG 50.0Ω vs skrf-CPW 67.44Ω）不立
锚——两候选并列证据档 runs/w4_phase4/w4e/cpw_ambiguity_evidence.md，裁决
权在用户；mline HJ 系数无仓内已核原文（#df6-⑬）不立锚。
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.infra.anchors_store import load_anchors

#: W4-E 批 10 锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_W4E_ANCHOR_IDS = (
    "cps.z0_ohm.closedform-v1",
    "cps.eps_eff.closedform-v1",
    "suspended_stripline.z0_ohm.closedform-v1",
    "suspended_stripline.eps_eff.closedform-v1",
    "coupled_bpf.cheb_g.closedform-v1",
    "xcheb_bpf4.cheb_g.closedform-v1",
    "hairpin.cheb_g.closedform-v1",
    "hairpin_alt.cheb_g.closedform-v1",
    "varactor_bpf.cheb_g.closedform-v1",
    "msl_cpw.s11_f0.closedform-v1",
)

_C0 = 299792458.0
_ETA0 = 376.730313668  # η0=√(μ0/ε0)（自由空间波阻抗，文献常数）


def _live():
    return load_anchors()


# ── 通用独立数值件（AGM 椭圆积分比，第二实现；与内核无 import 关系）──────

def _kk_ratio_agm(k: float) -> float:
    """r=K(k)/K'(k)：k'=√(1−k²) 直取 + AGM 恒等式（K=π/(2·agm(1,k′))）。

    本测试自实现（#118 第二实现）；k 近 1 的饱和域本批名义点不触
    （cps k1=0.127/k3=0.504、ssl k_b=0.246/k_h=0.992 均安全）。
    """
    kp = math.sqrt(max(1.0 - k * k, 0.0))
    a, b = 1.0, kp
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    agm_kp = 0.5 * (a + b)
    a, b = 1.0, k
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return (0.5 * (a + b)) / agm_kp


# ── 1. cps：Wadell 空气线 × Gupta-Ghione 部分电容 × γ(εr) FD 定标 ─────────

_CPS_GAMMA_C = 0.9014     # γ(εr)=1+C·εr^(−P)（C9 定标，第二转录）
_CPS_GAMMA_P = 0.6361


def _cps_ri_ref(w_mm: float, gap_mm: float, h_mm: float,
                epsilon_r: float) -> tuple[float, float]:
    """CPS (εeff, Z0) 第二实现（内核 _cps_ri docstring 口径逐项转录）。"""
    a = gap_mm / 2.0
    b = gap_mm / 2.0 + w_mm
    k1 = a / b
    h_eff = h_mm * (1.0 + _CPS_GAMMA_C * epsilon_r ** (-_CPS_GAMMA_P))
    k3 = (math.tanh(math.pi * a / (2.0 * h_eff))
          / math.tanh(math.pi * b / (2.0 * h_eff)))
    r1 = _kk_ratio_agm(k1)
    r3 = _kk_ratio_agm(k3)
    c_air = 1.0 / r1                       # 以 ε0 为单位
    c_tot = c_air + (epsilon_r - 1.0) / (2.0 * r3)
    eps_eff = c_tot / c_air
    z0 = _ETA0 / math.sqrt(c_air * c_tot)  # =1/(ε0·c·√(C·C_air)) 准静态恒等
    return eps_eff, z0


@pytest.mark.parametrize("aid, key", [
    ("cps.z0_ohm.closedform-v1", "z0"),
    ("cps.eps_eff.closedform-v1", "eps"),
])
def test_cps_second_implementation_and_fd_band(aid: str, key: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    eps_ref, z0_ref = _cps_ri_ref(2.95, 0.5, 0.508, 3.66)
    assert eps_ref == pytest.approx(1.676469, abs=5e-6)   # 第二实现自检
    assert z0_ref == pytest.approx(116.170323, abs=5e-4)
    if key == "z0":
        assert rec.value == pytest.approx(round(z0_ref, 2), abs=1e-9)
    else:
        assert rec.value == pytest.approx(round(eps_ref, 4), abs=1e-9)
    # 内核对拍（抓转录/回归错）
    from rfauto.core.calc_families.rf_line import _cps_ri

    eps_k, z0_k = _cps_ri(2.95, 0.5, 0.508, 3.66)
    assert z0_k == pytest.approx(z0_ref, rel=1e-9)
    assert eps_k == pytest.approx(eps_ref, rel=1e-9)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value  # domain null 恒域内


def test_cps_limit_identities() -> None:
    """两支解析极限（文献恒等，γ 不影响）：h→∞ εeff→(1+εr)/2（Wen 半空间）；
    εr=1 时 Z_CPS·Z_CPW 互补对偶（Z_CPW=30π/r 同 k，Wen 口径）——本仓双式
    乘积=30π·η0（k 无关性即对偶本体；教科书 (60π)²=η₀²/4 系 η₀=120π 旧
    惯例，SI-2019 μ₀ 重定义后 η₀=376.7303，两惯例差 0.069% 如实注）。"""
    eps_deep, _ = _cps_ri_ref(2.95, 0.5, 1.0e6, 3.66)
    assert eps_deep == pytest.approx((1.0 + 3.66) / 2.0, rel=1e-6)
    _, z0_cps_air = _cps_ri_ref(2.95, 0.5, 1.0e6, 1.0)
    k1 = 0.25 / (0.25 + 2.95)
    z0_cpw_air = 30.0 * math.pi / _kk_ratio_agm(k1)   # CPW 互补对偶同 k
    assert z0_cps_air * z0_cpw_air == pytest.approx(
        30.0 * math.pi * _ETA0, rel=1e-9)
    # FD 数值裁判（独立第二源）：C9 定标档真值 1.667，闭式差 ≤ 定标域 INFO 门
    rec = _live().get("cps.eps_eff.closedform-v1")
    assert abs(rec.value - 1.667) / 1.667 <= 0.012


# ── 2. suspended_stripline：Cohn 端点 × softmin 串联饱和修正族 ─────────────

_SSL_Q_G1 = (0.85842, 0.003, 2.38305, -0.21519)    # (A1, a1, b1, mu1)
_SSL_Q_G2 = (4.19252, 0.003, 8.57574, 0.1113)      # (A2, a2, b2, mu2)
_SSL_D = (31.76642, -1.85399, -0.89951)            # (D0, d1, d2)
_SSL_P = (0.17662, 0.73466)                        # (p0, p1)


def _stripline_z0_ref(w_mm: float, b_mm: float, er: float) -> float:
    """Cohn 零厚对称带状线第二实现（X5 一批同款独立重算件，本文件自持）。

    Z0=30π/(√εr·r)、r=K(k)/K'(k)、k=tanh(πw/2b)（AGM 恒等式）。"""
    x = math.pi * w_mm / (2.0 * b_mm)
    r = _kk_ratio_agm(math.tanh(x))
    return 30.0 * math.pi / (r * math.sqrt(er))


def _ssl_ri_ref(w_mm: float, b_mm: float, h_mm: float,
                epsilon_r: float) -> tuple[float, float]:
    """悬置带线 (εeff, Z0) 第二实现（softmin 常数逐项转录）。"""
    if h_mm >= b_mm:                      # h→b 全填充精确极限（内核同款守卫）
        return epsilon_r, _stripline_z0_ref(w_mm, b_mm, epsilon_r)
    u = w_mm / b_mm
    s = h_mm / b_mm
    a1, b1, c1, mu1 = _SSL_Q_G1
    a2, b2, c2, mu2 = _SSL_Q_G2
    g = (1.0 + u ** mu1 * a1 * s ** b1 * (1.0 - s) ** c1
         + u ** mu2 * a2 * s ** b2 * (1.0 - s) ** c2)
    x_b = math.pi * u / 2.0
    x_h = math.pi * u / (2.0 * s)
    kb, kh = math.tanh(x_b), math.tanh(x_h)
    q = (_kk_ratio_agm(kb) / _kk_ratio_agm(kh)
         if kh < 1.0 else 0.0)  # k'→0 时 r_h→∞，q→0 精确极限
    dd = (epsilon_r - 1.0) * min(q * g, 1.0)
    if dd <= 0.0:                         # h→0 空气带状线精确极限
        return 1.0, _stripline_z0_ref(w_mm, b_mm, 1.0)
    d0_, d1_, d2_ = _SSL_D
    d_cap = d0_ * (1.0 + u) ** d1_ * (4.0 * s * (1.0 - s)) ** d2_
    p = _SSL_P[0] + _SSL_P[1] * s
    eps_eff = 1.0 + (dd ** (-p) + d_cap ** (-p)) ** (-1.0 / p)
    z0 = _stripline_z0_ref(w_mm, b_mm, 1.0) / math.sqrt(eps_eff)
    return eps_eff, z0


@pytest.mark.parametrize("aid, key", [
    ("suspended_stripline.z0_ohm.closedform-v1", "z0"),
    ("suspended_stripline.eps_eff.closedform-v1", "eps"),
])
def test_ssl_second_implementation_and_fd_band(aid: str, key: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    eps_ref, z0_ref = _ssl_ri_ref(0.9058, 1.016, 0.508, 3.66)
    assert eps_ref == pytest.approx(2.001062, abs=5e-6)   # 第二实现自检
    assert z0_ref == pytest.approx(49.999951, abs=5e-4)
    if key == "z0":
        assert rec.value == pytest.approx(round(z0_ref, 4), abs=1e-9)
    else:
        assert rec.value == pytest.approx(round(eps_ref, 4), abs=1e-9)
    from rfauto.core.calc_families.rf_line import _suspended_stripline_ri

    eps_k, z0_k = _suspended_stripline_ri(0.9058, 1.016, 0.508, 3.66)
    assert z0_k == pytest.approx(z0_ref, rel=1e-9)
    assert eps_k == pytest.approx(eps_ref, rel=1e-9)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value


def test_ssl_endpoint_limits_and_fd_band() -> None:
    """两支精确极限锚（Cohn 文献闭式，8c1f3229 定标不改变端点）+ FD 双源。"""
    eps0, z0_air = _ssl_ri_ref(0.9058, 1.016, 1e-12, 3.66)   # h→0 空气带状线
    assert eps0 == pytest.approx(1.0, abs=1e-9)
    assert z0_air == pytest.approx(
        _stripline_z0_ref(0.9058, 1.016, 1.0), rel=1e-9)
    eps1, z0_fill = _ssl_ri_ref(0.9058, 1.016, 1.016, 3.66)  # h→b 全填充
    assert eps1 == pytest.approx(3.66, abs=1e-9)
    assert z0_fill == pytest.approx(
        _stripline_z0_ref(0.9058, 1.016, 3.66), rel=1e-9)
    # FD 数值裁判双源（2026-09-18 定标批档）：εeff 真值 2.025/Z0 49.7
    eps_a = _live().get("suspended_stripline.eps_eff.closedform-v1")
    z0_a = _live().get("suspended_stripline.z0_ohm.closedform-v1")
    assert abs(eps_a.value - 2.025) / 2.025 <= 0.0194   # 独立验证族带
    assert abs(z0_a.value - 49.7) / 49.7 <= 0.0384      # 定标 fit 带
    # 单调性 h↑→εeff↑（内核 FD 域 2001 点零违例注记的抽样钉）
    from rfauto.core.calc_families.rf_line import _suspended_stripline_ri

    seq = [_suspended_stripline_ri(0.9058, 1.016, h, 3.66)[0]
           for h in (0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 0.9)]
    assert all(x < y for x, y in pairwise(seq))


# ── 3. cheb_g：MYJ Table 4.05-1 0.1dB 档表值 × Pozar §8.4 递推双源 ─────────

#: MYJ Table 4.05-1 0.1dB 档（测试内第二转录，不 import 内核表；N=4 g4=
#: 0.8181——W4-E 批 #118 双源钉修正内核表旧 g4:=g2 转录错）
_MYJ_01DB_ROWS: dict[int, tuple[float, ...]] = {
    3: (1.0316, 1.1474, 1.0316),
    4: (1.1088, 1.3062, 1.7704, 0.8181),
}


def _cheb_g_recursion(n: int, ripple_db: float) -> list[float]:
    """Chebyshev 等纹波原型 g0..g_{n+1} 递推（Pozar §8.4 文献式第二实现）。

    ε=√(10^(r/10)−1)、β=ln(1/tanh(r/17.37))、γ=sinh(β/(2N))；
    g1=2sin(π/2N)/γ、g_i=4sin((2i−1)π/2N)sin((2i−3)π/2N)/
    (g_{i−1}(γ²+sin²((i−1)π/N)))、端接=1（奇 N）| 1+ε²（偶 N）。
    """
    eps = math.sqrt(10.0 ** (ripple_db / 10.0) - 1.0)
    beta = math.log(1.0 / math.tanh(ripple_db / 17.37))
    gamma = math.sinh(beta / (2.0 * n))
    g = [1.0, 2.0 * math.sin(math.pi / (2.0 * n)) / gamma]
    for i in range(2, n + 1):
        num = (4.0 * math.sin((2.0 * i - 1.0) * math.pi / (2.0 * n))
               * math.sin((2.0 * i - 3.0) * math.pi / (2.0 * n)))
        den = g[i - 1] * (gamma ** 2
                          + math.sin((i - 1.0) * math.pi / n) ** 2)
        g.append(num / den)
    g.append(1.0 if n % 2 == 1 else 1.0 + eps * eps)
    return g


_CHEB_FAMILY_ROWS = {
    "coupled_bpf.cheb_g.closedform-v1": 3,
    "xcheb_bpf4.cheb_g.closedform-v1": 4,
    "hairpin.cheb_g.closedform-v1": 3,
    "hairpin_alt.cheb_g.closedform-v1": 3,
    "varactor_bpf.cheb_g.closedform-v1": 3,
}


@pytest.mark.parametrize("aid", _CHEB_FAMILY_ROWS)
def test_cheb_g_anchor_table_recursion_dual_source(aid: str) -> None:
    n = _CHEB_FAMILY_ROWS[aid]
    rec = _live().get(aid)
    assert rec is not None, aid
    row = _MYJ_01DB_ROWS[n]
    # ① 锚值=g1=表行首元（表 4 位舍入逐位）
    assert rec.value == pytest.approx(row[0], abs=1e-9)
    # ② 双源 A：内核 g 表（N=3/RL20 → 最近档 0.1dB）与第二转录逐位合
    from rfauto.core.synthesis import chebyshev_lpf_g_values

    out = chebyshev_lpf_g_values(n, -20.0)
    assert out["ripple_table_db"] == 0.1      # 档位 tripwire（§7.4 注记）
    assert out["passband_ripple_db"] == pytest.approx(0.043648, abs=5e-7)
    assert out["g_values"] == list(row)
    # ③ 双源 B：Pozar §8.4 递推第二实现在恰好 0.1dB 处 4 位逐位合表
    g_exact = _cheb_g_recursion(n, 0.1)
    for gi, ti in zip(g_exact[1:n + 1], row, strict=True):
        assert gi == pytest.approx(ti, abs=5e-5)
    # 偶 N 端接 g5=1+ε²=10^(r/10)（内核表未内嵌，递推精确值自洽钉）
    if n == 4:
        assert g_exact[n + 1] == pytest.approx(10.0 ** (0.1 / 10.0),
                                               abs=1e-12)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value


def test_cheb_g_design_chain_tier_links() -> None:
    """设计链档位联动钉：名义链的 rl_db=20 → 纹波 0.0436dB → 0.1dB 最近档；
    coupled_bpf 名义几何逐位复现（rl=20 链在档的直接证据）。"""
    from rfauto.adapters.oe_templates.render_coupled_bpf import (
        coupled_bpf_design_from_order,
    )
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    d = coupled_bpf_design_from_order(3, 2.5, 0.05, 20.0)
    nom = TEMPLATE_NOMINAL["coupled_bpf"]
    assert [round(s["w_mm"], 4) for s in d["sections"]] == nom["widths_mm"]
    assert [round(s["s_mm"], 4) for s in d["sections"]] == nom["gaps_mm"]
    assert round(d["res_len_mm"], 4) == nom["res_len_mm"]
    assert round(d["w_feed_mm"], 4) == nom["w_feed_mm"]
    # hairpin 链：耦合缝（C13 k→KJ 反解输出）逐位复现名义（arm_len 后续
    # 批改端修正式非本链输出，不在此钉）
    from rfauto.core.synthesis import hairpin_design_from_order

    h = hairpin_design_from_order(3, 2.5, 0.05, 20.0)
    assert round(h["gap_mm"], 4) == TEMPLATE_NOMINAL["hairpin"]["gap_mm"]
    # varactor 链：k=FBW·|M12|=0.051514（VARACTOR_BPF_NOMINAL 注记值）
    import numpy as np

    from rfauto.core.synthesis import synthesize_bpf_model

    synth = synthesize_bpf_model(order=3, f0_ghz=2.5, fbw=0.05, rl_db=20.0,
                                 topology="folded")
    arr = np.asarray(synth["coupling_matrix"], dtype=float)
    if arr.ndim == 3:                       # [re, im] 对（复元素）
        arr = np.hypot(arr[..., 0], arr[..., 1])
    assert 0.05 * abs(float(arr[1, 2])) == pytest.approx(0.051514, abs=5e-7)


def test_xcheb_all_pole_degenerate_g_crosscheck() -> None:
    """xcheb cheb_g 锚的上游互证（cross_coupled_map 验证锚①）：
    全极点退化时 cm 链 k_i 对递推 g 行 k_i=FBW/√(g_j·g_{j+1})——本测试用
    第二实现递推（非 core/matching）独立构成第三路径。"""
    from rfauto.core.cross_coupled_map import cross_coupled_bpf_design

    out = cross_coupled_bpf_design(order=4, f0_ghz=2.5, fbw=0.05,
                                   rl_db=20.0)  # tz=None 全极点退化
    assert out["anchors"]["g_value_max_rel_dev"] <= 1e-4   # 内核自报互证
    ripple = 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (20.0 / 10.0) - 1.0))
    g = _cheb_g_recursion(4, ripple)
    k_g = [0.05 / math.sqrt(g[j] * g[j + 1]) for j in range(1, 4)]
    k_map = [p["k"] for p in sorted(
        (p for p in out["k_pairs"] if p["kind"] == "mainline"),
        key=lambda p: (p["i"], p["j"]))]
    assert len(k_map) == 3
    for kv, kg in zip(k_map, k_g, strict=True):
        assert kv == pytest.approx(kg, rel=1e-4)


# ── 4. msl_cpw：同阻异模理想级联 S11(f0)=0（ABCD 第二实现）─────────────────

def _abcd_line(z0: float, eps_eff: float, length_mm: float,
               f_ghz: float) -> list[list[complex]]:
    lam_mm = _C0 / (f_ghz * 1e9) / math.sqrt(eps_eff) * 1e3
    theta = 2.0 * math.pi * length_mm / lam_mm
    return [[complex(math.cos(theta)), 1j * z0 * math.sin(theta)],
            [1j * math.sin(theta) / z0, complex(math.cos(theta))]]


def _abcd_cascade(a: list[list[complex]],
                  b: list[list[complex]]) -> list[list[complex]]:
    return [[a[0][0] * b[0][0] + a[0][1] * b[1][0],
             a[0][0] * b[0][1] + a[0][1] * b[1][1]],
            [a[1][0] * b[0][0] + a[1][1] * b[1][0],
             a[1][0] * b[0][1] + a[1][1] * b[1][1]]]


def _s11_from_abcd(m: list[list[complex]], z_sys: float = 50.0) -> complex:
    a, b, c, d = m[0][0], m[0][1], m[1][0], m[1][1]
    return ((a + b / z_sys - c * z_sys - d)
            / (a + b / z_sys + c * z_sys + d))


def test_msl_cpw_s11_f0_identity() -> None:
    rec = _live().get("msl_cpw.s11_f0.closedform-v1")
    assert rec is not None
    assert rec.value == 0.0
    # 恒等式钉：两段等特征阻抗级联（任意长度/εeff）→ S11≡0
    for e1, e2, l1, l2 in ((2.725, 2.567, 40.0, 40.0), (3.0, 2.2, 17.0, 23.0)):
        m = _abcd_cascade(_abcd_line(50.0, e1, l1, 2.5),
                          _abcd_line(50.0, e2, l2, 2.5))
        assert abs(_s11_from_abcd(m)) == pytest.approx(0.0, abs=1e-12)
    # 失配对照 sanity：Z0 不一致 → S11≠0（恒等式非平凡）
    m = _abcd_cascade(_abcd_line(50.0, 2.725, 40.0, 2.5),
                      _abcd_line(40.0, 2.567, 40.0, 2.5))
    assert abs(_s11_from_abcd(m)) > 1e-3
    # 内核名义复现（综合链逐位）：w_msl=1.1134 / w_cpw=0.849 @gap=0.2
    from rfauto.core.synthesis import synthesize_msl_cpw_model

    out = synthesize_msl_cpw_model()
    assert out.params["w_msl_mm"] == pytest.approx(1.1134, abs=5e-5)
    assert out.params["w_cpw_mm"] == pytest.approx(0.849, abs=5e-5)
    res = _live().resolve_anchor("msl_cpw.s11_f0.closedform-v1", {})
    assert res["hit"] and res["value"] == 0.0


# ── 5. 注册表形态钉（#122：analytic 档与引擎档可区分）───────────────────────

@pytest.mark.parametrize("aid", _W4E_ANCHOR_IDS)
def test_w4e_anchor_registry_shape(aid: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    assert rec.kind == "constant"
    assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                      "referee": None}
    assert rec.status == "experimental"  # 真机首判前如实
    assert rec.fallback == "closed_form"
    assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
    assert rec.template_family == [aid.split(".")[0]]
    fam, qty = aid.split(".")[0], aid.split(".")[1]
    assert rec.raw["quantity"]["name"] == f"{fam}_{qty}"
    # G-08 两语义二分：本批全为 declarative 参考档 → consumers=[] +
    # provenance.consumers_note 显式声明（G-04 纪律）
    assert rec.consumers == []
    assert "declarative_identity" in str(rec.raw["provenance"]
                                         .get("consumers_note", ""))


def test_w4e_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 W4-E 批 10 席全在册
    live = _live()
    for aid in _W4E_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_W4E_ANCHOR_IDS) == 10
    assert all(a in EXPECTED_ANCHORS for a in _W4E_ANCHOR_IDS)
