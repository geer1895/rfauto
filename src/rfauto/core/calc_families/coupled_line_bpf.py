"""平行耦合线带通滤波器（coupled-line BPF）综合族（aurora72 A3-C 席域 1，
R7 第二梯队 T5）。

两键：coupled_line_bpf_synthesize（规格→J 倒置器→逐节 (Z0e,Z0o)→微带实现
尺寸 (w,s) mm + 段长/谐振器长） / coupled_line_bpf_response（逐节 (Z0e,Z0o)
同步 TEM 电路频响——偶/奇模叠加 4 端口 S + 交叉口开路端接 2 端口级联）。

与既有面的边界（#222 三重搜索证据，2026-10-11 实测）
--------------------------------------------------------
- core/synthesis.py synthesize_bpf_model（C13）= **耦合矩阵级**（广义切比
  雪夫→(N+2)×(N+2) 归一化矩阵 m_ij，无物理尺寸输出）；本族是**实现尺寸级**
  （全极点切比雪夫 g 值→逐节奇偶模阻抗→mm 缝宽），不重复矩阵综合（无 TZ、
  无折叠/箭头拓扑）。
- adapters/oe_templates/render_coupled_bpf.py = **模板渲染级**（J→(Z0e,Z0o)
  →KJ 反解链绑定 TEMPLATE_META 渲染管线，非注册计算器）；本族把同语义链
  收进 core 注册键面（calc_families grep `coupled|interdigital` 注册键 0 命
  中，2026-10-11 实测）。
- calc_families 内 chebyshev_prototype/coupling_matrix_* = 原型/矩阵级；
  sir_filter、mask_* = SIR 族/规格级——本族只做**半波长耦合线谐振 BPF 的
  器件实现**（Mathaei-Pollard-Feit ch.8 / Pozar §8.6.2 口径）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- J 倒置器（Pozar *Microwave Engineering* §8.6，MYJ ch.8 同源）：

      x_01 = J_01/Z0 = sqrt(π·δ/(2·g_0·g_1))          （端节）
      x_j  = J_j,j+1/Z0 = (π·δ/2)/sqrt(g_j·g_{j+1})   （内节，j=1..n−1）
      x_n  = J_n,n+1/Z0 = sqrt(π·δ/(2·g_n·g_{n+1}))   （端节）

  δ=相对带宽（FBW）；g 值走 core/matching.chebyshev_g_values（Pozar 表 8.4
  递推；N=3/0.5dB → g=[1, 1.5963, 1.0967, 1.5963, 1.0] 教科书值）。
- 逐节奇偶模阻抗（Pozar 式 (8.13x) 精确形）：

      Z0e = Z0·(1 + x + x²)，  Z0o = Z0·(1 − x + x²)

  反解恒等式 x = (Z0e − Z0o)/(2·Z0)（测试钉）。该综合在同步 TEM 极限下中
  心频率精确（各节等效倒置器 J_cohn = x/(Z0·(1+x²+x⁴)) 与 Pozar 小 x 近似
  的差异即倒置器 λ/4 实现的二阶修正，带内偏差实测见测试锚）。
- (Z0e,Z0o)→(w,s)：本族稳健二维数值反解（正向=core/coupled_microstrip.
  coupled_microstrip_even_odd_ohm，Kirschning-Jansen 1984 准静态闭式；内层
  固定 w 对 Z0e 解 s——Z0e 随 s 单调**降**、s→∞ 退化单线 Z0(w)，实测钉住；
  外层对 Z0o 解 w——h(w)=Z0o(w,s*(w))−目标沿 w 网格括号后 brentq。core/
  slotline_transitions 的同义反解其外括号启发式（inverse_width 端点）在本
  综合域边缘实测脆弱（nan 端点假越域），故本族自带括号逻辑；物理正向同
  源）。正向回代出 εeff_e/εeff_o → 段长 = λ0/4·sqrt(2/(εe+εo))；谐振器 =
  λg/2（两邻段平均 εeff）− 2×Δl（Hammerstad 开路端修正，core
  microstrip_open_end_delta_l_mm，端宽取该端所在段的线宽）。
- 馈线宽 = core/synthesis.inverse_width（skrf HJ 综合，铁律 1c 唯一线宽
  口径）。
- 外部 Q：Q_e,1 = g_0·g_1/δ、Q_e,n = g_n·g_{n+1}/δ（g 链恒等输出；与耦合
  节映射 Q_e=(π/2)(Z0/Z_r)/x_01²（Z_r=sqrt(Z0e·Z0o)）仅当 Z_r≈Z0 一致，
  窄带近似差如实 note）。

频响键口径
----------
每节 = 偶/奇模各自 2 端口线 S 叠加构造 4 端口 S（构造恒满足无耗/互易），
交叉口（A 远端 + B 近端）以 Γ=+1 开路端接压缩为 2 端口，(N+1) 节 ABCD 级
联（S→ABCD 按 Pozar Table 4.2），端接 z_ref 出 S 参数。同步 TEM 口径
（各节 εeff 逐节给定、段长=λ/4@f0）下综合链↔频响自洽：N=3/δ=0.10/0.5dB
纹波（Pozar Example 8.7 阻抗表）带内 |ΔS21| vs 切比雪夫原型闭式 ≤0.5 dB
（带缘倒置器频率依赖的二阶偏差，实测 ~0.28 dB）；带心 |S21|=0 dB、带内
S11 谷数=N。频域奇异守卫：任一节 θ=kπ（sinθ<1e-9）显式拒绝。

数值锚（#118 独立来源；锚树 tests/unit/test_a3c_coupled_interdigital.py）
- Pozar Example 8.7（§8.6，p.435 4th ed，文献例引文）：N=3、0.5dB 等纹波、
  f0=2 GHz、δ=10%、Z0=50 → (Z0e,Z0o) = (70.61,39.24)/(56.64,44.77)/
  (56.64,44.77)/(70.61,39.24) Ω（本键闭式链逐位复现，εr/h 无关）。
- 回代恒等：x ← (Z0e−Z0o)/(2Z0) 逐位；KJ 正向 |Z0e_fwd/Z0e_tgt−1| ≤1e-6。
- g 值 vs 教科书表（1.5963/1.0967）。
- 频响 vs 切比雪夫原型闭式（独立推导路线）与 vs adapters 裁判
  （coupled_bpf_circuit_sparams，同物理异层实现）。

守卫：order 为 ≥2 整数；0<fbw≤1；ripple_db>0；z0_ohm>0；epsilon_r≥1；
h_mm>0；KJ 反解越域（极宽/极窄带不可实现）显式拒绝（透传 core 守卫并附
节序号）；response 键列表长度一致（=n_sections≥2）、eps 标量或等长列表、
freq_ghz>0 且避开 θ=kπ。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

Z0_REF_DEFAULT = 50.0

_SOURCES = {
    "synth": ("Pozar Microwave Engineering §8.6.2 / MYJ ch.8 耦合线 BPF 综合；"
              "g 值 core/matching（Pozar 表 8.4 递推）；(w,s) KJ 1984 反解 "
              "(core/coupled_microstrip)；Δl=Hammerstad 开路端修正"),
    "resp": ("偶/奇模叠加 4 端口 S（Pozar §7.6 同源构造）+ 交叉口 Γ=+1 开路"
             "端接 2 端口级联（S→ABCD 按 Pozar Table 4.2）"),
}


def _g_values(order: int, ripple_db: float) -> list[float]:
    """全极点切比雪夫 g 值（core/matching 单源复用，不在本族重写递推）。"""
    from rfauto.core.matching import chebyshev_g_values

    return [float(v) for v in chebyshev_g_values(order, ripple_db)]


def _x_targets(order: int, fbw: float, g: list[float]) -> list[float]:
    """J/Z0 目标列表 [x_01, x_12.., x_n,n+1]（Pozar §8.6 闭式）。"""
    x = [math.sqrt(math.pi * fbw / (2.0 * g[0] * g[1]))]
    for j in range(1, order):
        x.append((math.pi * fbw / 2.0) / math.sqrt(g[j] * g[j + 1]))
    x.append(math.sqrt(math.pi * fbw / (2.0 * g[order] * g[order + 1])))
    return x


def _ze_zo_from_x(x: float, z0: float) -> tuple[float, float]:
    return z0 * (1.0 + x + x * x), z0 * (1.0 - x + x * x)


def _kj_invert(ze_t: float, zo_t: float, f0: float, er: float,
               h: float) -> tuple[float, float]:
    """(Z0e,Z0o)→(w,s) 稳健二维反解（KJ 正向；内层 s 单调降、外层网格括号）。

    内层：固定 w，Z0e(w,s) 随 s 单调降（s→∞ → 单线 Z0(w)；s_lo=0.02mm 为
    KJ 准静态拟合域下缘 s/h≥~0.08）；外层：h(w)=Z0o(w,s*(w))−Z0o 目标沿
    w∈[0.05h, 40h] 48 点几何网格找变号区间后 brentq（不依赖端点启发式）。
    """
    from scipy.optimize import brentq

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    def zpair(w: float, s: float) -> tuple[float, float]:
        return coupled_microstrip_even_odd_ohm(w, s, f0, er, h)[:2]

    s_lo, s_hi = 0.02, 80.0

    def s_star(w: float) -> float | None:
        lo = zpair(w, s_lo)[0]
        hi = zpair(w, s_hi)[0]
        if not lo > ze_t > hi:
            return None
        return float(brentq(lambda s_: zpair(w, s_)[0] - ze_t,
                            s_lo, s_hi, xtol=1e-10))

    def h_res(w: float) -> float | None:
        ss = s_star(w)
        return None if ss is None else zpair(w, ss)[1] - zo_t

    grid = [h * 0.05 * (800.0 ** (i / 47.0)) for i in range(48)]
    prev: tuple[float, float] | None = None
    bracket: tuple[float, float] | None = None
    for w_g in grid:
        hv = h_res(w_g)
        if hv is None:
            prev = None
            continue
        if prev is not None and prev[1] * hv < 0.0:
            bracket = (prev[0], w_g)
            break
        prev = (w_g, hv)
    if bracket is None:
        raise ValueError(
            f"(Z0e,Z0o)=({ze_t:.3f},{zo_t:.3f})Ω @er={er},h={h}mm 在 KJ 可"
            f"达域外（w 网格 48 点无变号；换薄基板/低 εr 或收窄带宽）")
    w_mm = float(brentq(h_res, bracket[0], bracket[1], xtol=1e-10))
    s_mm = s_star(w_mm)
    assert s_mm is not None
    return w_mm, s_mm


# ─── 键 1：规格 → 实现尺寸 ───────────────────────────────────────────────────

@register_calculator(
    "coupled_line_bpf_synthesize",
    "耦合线带通综合：全极点切比雪夫平行耦合线带通（Pozar §8.6.2/MYJ ch.8）："
    "阶数+中心频率+相对带宽+纹波 → J 倒置器 x 列表 → 逐节 (Z0e,Z0o) → KJ 二"
    "维反解微带实现 (w,s) mm → 段长 λ/4@εeff 均值、谐振器 λg/2−2Δl（Hammer"
    "stad 开路端修正）、50Ω 馈线宽（skrf HJ）。锚：Pozar Example 8.7 阻抗表 "
    "(70.61,39.24)/(56.64,44.77) 逐位复现（εr/h 无关）；x=(Z0e−Z0o)/(2Z0) 回"
    "代恒等；g 值 vs 教科书表 1.5963/1.0967",
    (("order", "int 阶数 N（≥2；谐振器数，耦合段=N+1）"),
     ("f0_ghz", "float GHz 中心频率（>0）"),
     ("fbw", "float 相对带宽 δ=（f2−f1)/f0（0<δ≤1）"),
     ("ripple_db", "float dB 通带等纹波（>0；0.5dB 教科书例口径）"),
     ("z0_ohm", "float Ω 端口/馈线阻抗（>0，缺省 50）"),
     ("epsilon_r", "float 基板相对介电常数（≥1）"),
     ("h_mm", "float mm 基板厚（>0）")),
    required=("order", "f0_ghz", "fbw", "ripple_db", "epsilon_r", "h_mm"),
)
def coupled_line_bpf_synthesize(order: int, f0_ghz: float, fbw: float,
                                ripple_db: float, epsilon_r: float,
                                h_mm: float,
                                z0_ohm: float = 50.0) -> dict[str, Any]:
    n = int(order)
    if n < 2 or order != int(order):
        raise ValueError(
            f"coupled_line_bpf_synthesize: order 须为 ≥2 整数，得到 {order!r}")
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    delta = _finite(fbw, "fbw")
    if not 0.0 < delta <= 1.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: fbw 须在 (0,1]，得到 {fbw!r}")
    rip = _finite(ripple_db, "ripple_db")
    if rip <= 0.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: ripple_db 必须 >0，得到 "
            f"{ripple_db!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    er = _finite(epsilon_r, "epsilon_r")
    if er < 1.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: epsilon_r 必须 ≥1，得到 "
            f"{epsilon_r!r}")
    h = _finite(h_mm, "h_mm")
    if h <= 0.0:
        raise ValueError(
            f"coupled_line_bpf_synthesize: h_mm 必须 >0，得到 {h_mm!r}")

    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.slotline_transitions import microstrip_open_end_delta_l_mm
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    g = _g_values(n, rip)
    x_list = _x_targets(n, delta, g)
    stackup = Stackup(name="clbpf", epsilon_r=er, thickness_mm=h)

    sections: list[dict[str, Any]] = []
    eps_mean_list: list[float] = []
    rt_dev_max = 0.0
    for j, xv in enumerate(x_list):
        ze_t, zo_t = _ze_zo_from_x(xv, z0)
        try:
            w_mm, s_mm = _kj_invert(ze_t, zo_t, f0, er, h)
        except ValueError as exc:
            raise ValueError(
                f"coupled_line_bpf_synthesize: 第 {j + 1}/{n + 1} 节 "
                f"(Z0e,Z0o)=({ze_t:.3f},{zo_t:.3f})Ω 反解失败——{exc}") from exc
        ze_f, zo_f, eps_e, eps_o = coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, f0, er, h)
        rt = max(abs(ze_f / ze_t - 1.0), abs(zo_f / zo_t - 1.0))
        rt_dev_max = max(rt_dev_max, rt)
        eps_mean = 0.5 * (eps_e + eps_o)
        eps_mean_list.append(eps_mean)
        sec_len = C_MM_GHZ / (4.0 * f0 * math.sqrt(eps_mean))
        sections.append({
            "j_over_z0": round(xv, 12),
            "z0e_ohm": round(ze_t, 9),
            "z0o_ohm": round(zo_t, 9),
            "w_mm": round(w_mm, 6),
            "s_mm": round(s_mm, 6),
            "eps_eff_e": round(eps_e, 9),
            "eps_eff_o": round(eps_o, 9),
            "eps_eff_mean": round(eps_mean, 9),
            "section_len_mm": round(sec_len, 6),
            "j_cohn_s": round(xv / (z0 * (1.0 + xv * xv + xv ** 4)), 12),
        })

    # 谐振器 k（1..n）= 节 k−1 的 B 线 + 节 k 的 A 线，λg/2 − 2Δl
    dl_cache: dict[float, float] = {}
    resonators: list[dict[str, Any]] = []
    for k in range(1, n + 1):
        w_a = sections[k - 1]["w_mm"]
        w_b = sections[k]["w_mm"]
        eps_res = 0.5 * (eps_mean_list[k - 1] + eps_mean_list[k])
        lg2 = C_MM_GHZ / (2.0 * f0 * math.sqrt(eps_res))
        dl_total = 0.0
        for w_end in (w_a, w_b):
            if w_end not in dl_cache:
                _, ere_single = forward_z0(w_end, f0, stackup)
                dl_cache[w_end] = microstrip_open_end_delta_l_mm(
                    w_end, h, float(ere_single))
            dl_total += dl_cache[w_end]
        resonators.append({
            "k": k,
            "eps_eff_mean": round(eps_res, 9),
            "lambda_half_mm": round(lg2, 6),
            "open_end_delta_mm": round(dl_total, 6),
            "res_len_mm": round(lg2 - dl_total, 6),
        })

    w_feed = float(inverse_width(z0, f0, stackup)[0])
    qe_in = g[0] * g[1] / delta
    qe_out = g[n] * g[n + 1] / delta
    zr_end = math.sqrt(sections[0]["z0e_ohm"] * sections[0]["z0o_ohm"])
    qe_map_in = (math.pi / 2.0) * (z0 / zr_end) / sections[0]["j_over_z0"] ** 2
    return {
        "order": n,
        "f0_ghz": f0,
        "fbw": delta,
        "ripple_db": rip,
        "z0_ohm": z0,
        "epsilon_r": er,
        "h_mm": h,
        "g_list": [round(v, 9) for v in g],
        "j_over_z0": [s["j_over_z0"] for s in sections],
        "z0e_ohm": [s["z0e_ohm"] for s in sections],
        "z0o_ohm": [s["z0o_ohm"] for s in sections],
        "w_mm": [s["w_mm"] for s in sections],
        "s_mm": [s["s_mm"] for s in sections],
        "section_len_mm": [s["section_len_mm"] for s in sections],
        "sections": sections,
        "resonators": resonators,
        "w_feed_mm": round(w_feed, 6),
        "qe_in": round(qe_in, 9),
        "qe_out": round(qe_out, 9),
        "qe_coupled_section_map_in": round(qe_map_in, 9),
        "kj_roundtrip_rel_dev_max": round(rt_dev_max, 15),
        "note": (
            "实现尺寸级综合（全极点切比雪夫，无传输零点——广义切比雪夫/"
            "耦合矩阵综合走 core/synthesis.synthesize_bpf_model，互不重复）；"
            "Q_e 耦合节映射值 qe_coupled_section_map_in 与 g 链值 qe_in 的"
            "差=Z_r≠Z0 的窄带近似量（如实并列）；段长/谐振器长已含 KJ 准静"
            "态色散口径（εeff 逐节），宽度台阶不连续与开路端边缘导纳残差不"
            "进模型（由 EM 冒烟实测总量）"),
        "source": _SOURCES["synth"],
    }


# ─── 键 2：同步 TEM 电路频响 ─────────────────────────────────────────────────

def _tl_s2(zc: float, th: float, z_ref: float) -> tuple[complex, complex]:
    """2 端口均匀线 S（参考 z_ref）：S21=e^{-jθ}(1−Γ²)/(1−Γ²e^{-2jθ}) 形。"""
    gam = (zc - z_ref) / (zc + z_ref)
    e = complex(math.cos(th), -math.sin(th))
    e2 = e * e
    den = 1.0 - gam * gam * e2
    return gam * (1.0 - e2) / den, e * (1.0 - gam * gam) / den


def _section_s4(ze: float, zo: float, th: float,
                z_ref: float) -> np.ndarray:
    """对称耦合线节 4 端口 S（偶/奇模叠加；0/1=A 近/远、2/3=B 近/远）。

    构造恒满足无耗（S†S=I）与互易（S=Sᵀ）（测试钉）。
    """
    se = _tl_s2(ze, th, z_ref)
    so = _tl_s2(zo, th, z_ref)
    s4 = np.zeros((4, 4), dtype=complex)
    s4[0, 0] = s4[1, 1] = s4[2, 2] = s4[3, 3] = (se[0] + so[0]) / 2.0
    s4[0, 1] = s4[1, 0] = s4[2, 3] = s4[3, 2] = (se[1] + so[1]) / 2.0
    s4[0, 2] = s4[2, 0] = s4[1, 3] = s4[3, 1] = (se[0] - so[0]) / 2.0
    s4[0, 3] = s4[3, 0] = s4[1, 2] = s4[2, 1] = (se[1] - so[1]) / 2.0
    return s4


@register_calculator(
    "coupled_line_bpf_response",
    "耦合线带通频响校验：逐节 (Z0e,Z0o) 同步 TEM 电路频响——偶/奇模各自 2 端"
    "口线 S 叠加成 4 端口（构造无耗/互易），交叉口 Γ=+1 开路端接压缩 2 端口"
    "级联（S→ABCD 按 Pozar Table 4.2）。锚：Pozar Example 8.7 阻抗表带心 "
    "|S21|=0 dB、S11 谷数=N、无耗 |S11|²+|S21|²=1；vs 切比雪夫原型闭式带内 "
    "≤0.5 dB（带缘倒置器频率依赖二阶偏差）",
    (("z0e_ohm", "array 逐节偶模阻抗 Ω（≥2 节）"),
     ("z0o_ohm", "array 逐节奇模阻抗 Ω（同长；须 Z0e>Z0o>0）"),
     ("f0_ghz", "float GHz 中心频率（段长=λ/4@f0）"),
     ("freq_ghz", "array GHz 频率轴（>0；避开各节 θ=kπ）"),
     ("eps_eff", "float|array 逐节平均有效介电常数（≥1；标量=同步均匀）")),
    required=("z0e_ohm", "z0o_ohm", "f0_ghz", "freq_ghz"),
)
def coupled_line_bpf_response(z0e_ohm: list, z0o_ohm: list, f0_ghz: float,
                              freq_ghz: list,
                              eps_eff: float | list = 1.0) -> dict[str, Any]:
    ze_l = [float(v) for v in z0e_ohm]
    zo_l = [float(v) for v in z0o_ohm]
    n_sec = len(ze_l)
    if n_sec < 2 or len(zo_l) != n_sec:
        raise ValueError(
            f"coupled_line_bpf_response: z0e/z0o 须为同长列表且 ≥2 节，得到 "
            f"{n_sec}/{len(zo_l)}")
    if any(not (a > b > 0.0) for a, b in zip(ze_l, zo_l, strict=True)):
        raise ValueError(
            "coupled_line_bpf_response: 每节须 Z0e > Z0o > 0")
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"coupled_line_bpf_response: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("coupled_line_bpf_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("coupled_line_bpf_response: 频率须 >0")
    if isinstance(eps_eff, (int, float)):
        eps_l = [float(eps_eff)] * n_sec
    else:
        eps_l = [float(v) for v in eps_eff]
        if len(eps_l) != n_sec:
            raise ValueError(
                f"coupled_line_bpf_response: eps_eff 标量或 {n_sec} 元列表，"
                f"得到 {len(eps_l)} 元")
    if any(e < 1.0 for e in eps_l):
        raise ValueError("coupled_line_bpf_response: eps_eff 须 ≥1")
    # 奇异域守卫：任一节 θ=kπ 显式拒绝
    for e in eps_l:
        sec_len = C_MM_GHZ / (4.0 * f0 * math.sqrt(e))
        for f in freqs:
            th = 2.0 * math.pi * f * math.sqrt(e) * sec_len / C_MM_GHZ
            if abs(math.sin(th)) < 1e-9:
                raise ValueError(
                    f"coupled_line_bpf_response: f={f} GHz 触及节电长 θ=kπ "
                    f"奇异点（显式拒绝）")

    s11_l: list[float] = []
    s21_l: list[float] = []
    passivity_dev = 0.0
    for f in freqs:
        t = np.eye(2, dtype=complex)
        for j in range(n_sec):
            th = (2.0 * math.pi * f * math.sqrt(eps_l[j])
                  * (C_MM_GHZ / (4.0 * f0)) / C_MM_GHZ)
            s4 = _section_s4(ze_l[j], zo_l[j], th, Z0_REF_DEFAULT)
            # 交叉口（A 远端=1、B 近端=2，0 基）Γ=+1 开路端接压缩 2 端口
            p = [1, 2]
            o = [0, 3]
            spp = s4[np.ix_(p, p)]
            s2 = (s4[np.ix_(o, o)]
                  + s4[np.ix_(o, p)]
                  @ np.linalg.solve(np.eye(2, dtype=complex) - spp,
                                    s4[np.ix_(p, o)]))
            # 2 端口 S → ABCD（Pozar Table 4.2 反演）并级联
            a_, b_, c_, d_ = s2[0, 0], s2[0, 1], s2[1, 0], s2[1, 1]
            den = 2.0 * c_
            abcd = np.array([
                [(1.0 + a_) * (1.0 - d_) + b_ * c_,
                 Z0_REF_DEFAULT * ((1.0 + a_) * (1.0 + d_) - b_ * c_)],
                [((1.0 - a_) * (1.0 - d_) - b_ * c_) / Z0_REF_DEFAULT,
                 (1.0 - a_) * (1.0 + d_) + b_ * c_],
            ]) / den
            t = t @ abcd
        aa, bb, cc, dd = t[0, 0], t[0, 1], t[1, 0], t[1, 1]
        delta = aa + bb / Z0_REF_DEFAULT + cc * Z0_REF_DEFAULT + dd
        s21 = 2.0 / delta
        s11 = (aa + bb / Z0_REF_DEFAULT - cc * Z0_REF_DEFAULT - dd) / delta
        s11_l.append(abs(s11))
        s21_l.append(abs(s21))
        passivity_dev = max(passivity_dev,
                            abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0))

    f_closest_idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - f0))
    return {
        "n_sections": n_sec,
        "f0_ghz": f0,
        "freq_ghz": [round(f, 9) for f in freqs],
        "s11_mag": [round(v, 12) for v in s11_l],
        "s21_mag": [round(v, 12) for v in s21_l],
        "s11_db": [round(20.0 * math.log10(max(v, 1e-300)), 6)
                   for v in s11_l],
        "s21_db": [round(20.0 * math.log10(max(v, 1e-300)), 6)
                   for v in s21_l],
        "s21_at_f0_db": round(
            20.0 * math.log10(max(s21_l[f_closest_idx], 1e-300)), 6),
        "s11_at_f0_db": round(
            20.0 * math.log10(max(s11_l[f_closest_idx], 1e-300)), 6),
        "passivity_max_dev": round(passivity_dev, 15),
        "note": (
            "同步 TEM 极限电路口径（各节 εeff 逐节、段长=λ/4@f0，无开路端修"
            "正）——综合方程在该极限下中心频率精确；真非均匀介质口径（εe/εo "
            "分离相位）与宽度台阶不连续由 EM 冒烟实测。θ=kπ 奇异频点显式拒"
            "绝"),
        "source": _SOURCES["resp"],
    }
