"""多节对称定向耦合器族（aurora72 A6-B 席域 1，R7_core_tier2 §② G5 余量）。

两键：multisection_coupler_binomial（对称 N 节二项式=中心最大平坦综合：
结点权→节耦合→逐节 (Z0e,Z0o)） / multisection_coupler_response（逐节
(Z0e,Z0o) 偶/奇模精确级联 4 端口频响——耦合/直通/隔离/回损+方向性）。

与既有耦合面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- 全仓 grep（multisection|multi_section|levy|n_section.*coupl）注册键面
  零命中；synthesis.py synthesize_multisection_quarter_wave=λ/4 阻抗
  变换器**匹配**域（同名 multisection 非耦合器）；bethe_hole_coupler=
  波导孔耦合**单节综合**；coupled_line_bpf_*=带通谐振器实现（交叉口
  开路端接，非直通 4 口）——均不并入。
- adapters 层 Pozar §7.83/§7.84 单节闭式=单节裁判积木；本族补**多节
  级联**（单节=N=1 退化档，测试侧互证）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 偶/奇模精确级联（Pozar §7.6 同源构造）：对称耦合器 4 口 P1=入、P2=直
  通（同侧远端）、P3=耦合（对侧近端）、P4=隔离（对侧远端）；偶/奇模各
  为 2 端口级联链（逐节特性阻抗 Z0e_i / Z0o_i、电长 θ_i），端接 Z0：

      S11=(Se11+So11)/2   S21=(Se21+So21)/2（直通）
      S31=(Se11−So11)/2（耦合）   S41=(Se21−So21)/2（隔离）

  该构造恒满足无耗（|S11|²+|S21|²+|S31|²+|S41|²=1）与互易（测试钉）。
- 单节精确闭式（测试侧独立重解）：Z0e·Z0o=Z0² 配对下 Γ0o=−Γ0e，故
  S31=Γe，|S31|=c·sinθ/√(1−c²cos²θ)，c=2g/(1+g²)、g=(Z0e−Z0)/(Z0e+Z0)
  ——θ=90° 处恰 =c（精确，非近似）。
- 二项式（中心最大平坦）一阶小反射设计（Levy 级联理论同源）：结点反
  射权 Γ_i（i=0..N，N+1 个结点，镜像对称结构 Γ_{N−i}=−Γ_i）的耦合口
  一阶响应 S31(θ)=Σ_i Γ_i e^{−j2iθ}=e^{−jNθ}·2j·Σ_{i≤M}Γ_i sin((N−2i)θ)
  （N=2M+1 奇数节）。中心最大平坦（|S31| 对 x=sinθ 的全部可达阶导数
  在 x=1 处为零）唯一确定半权：

      g(x) ∝ ∫₀ˣ(1−t²)^M dt = Σ_k (−1)^k·C(M,k)/(2k+1)·x^(2k+1)

  与 sin 多项式（sin(nθ) 按 x 的奇次展开，整数二项式系数精确递推）
  三角分解解线性方程组即 Γ_i（N=3 → 结点比 1:9:9:1、节耦合比 1:10:1；
  N=5 → 结点比 3:25:150）。节耦合由结点权累计 c_i=2Σ_{k<i}Γ_k（一阶
  Γ≈Δc/2 恒等变形）；电平归一对精确偶/奇级联在 θ=90° 处求根（结点权
  整体缩放不改二项式比；精确级联 |S31| 随 scale 单调，二分确定性收
  敛）——f0 处精确命中目标耦合，一阶口径值并列报告（有限耦合二阶差
  0.1–0.5dB 量级 @10dB，如实不隐藏）。
- (Z0e,Z0o)=core/slotline_transitions.even_odd_from_coupling 同式闭式
  （Z0e=Z0√((1+c)/(1−c))、Z0o=Z0√((1−c)/(1+c))，恒 Z0e·Z0o=Z0²——该
  配对性质给出 f0 处隔离口精确零：S21e=S21o（同幅同相）→ S41=0）。

数值锚（#118 独立来源；锚树 tests/unit/test_a6b_multisection_gysel.py）
- N=1 频响 vs 单节精确闭式 c·sinθ/√(1−c²cos²θ)（独立推导路线）逐位
  ≤1e-12；θ=90° 恰 =c。
- 二项式结点/节耦合比：测试侧对最大平坦条件 g'(x=1)=0 独立重解
  （N=3 → Γ₁=9Γ₀、c₂/c₁=10）。
- 精确级联 vs 一阶：θ=90° |S31|−目标 ≤0.1dB（10dB/3 节档）；能量守恒
  残差 ≤1e-12（全频轴）；f0 隔离 |S41|≤1e-10（浮点配对地板）；
  |S31(90°−δ)|=|S31(90°+δ)| 对称残差 ≤1e-12。

守卫：n_sections 为正奇整数（≤15）；coupling_db∈(0,60]；逐节 c_i<0.99
（过耦不可实现显式拒绝）；response 键列表同长 ≥1、Z0e>Z0o>0、freq>0
且避开任一节 θ=kπ 奇异点（显式拒绝，coupled_line_bpf_response 同口径）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "synth": ("对称多节耦合器二项式（中心最大平坦）一阶小反射设计——Levy "
              "级联理论同源口径；结点权由 g(x)∝∫₀ˣ(1−t²)^M dt 与 sin 多项"
              "式三角分解唯一确定（测试侧独立重解互证）；(Z0e,Z0o) 闭式同 "
              "core/slotline_transitions.even_odd_from_coupling"),
    "resp": ("偶/奇模各自 2 端口线级联 + 叠加构造 4 端口 S（Pozar §7.6 同源；"
             "ABCD 级联按 Pozar Table 4.2 转换）；构造恒无耗/互易"),
}

_C_MAX = 0.99          # 逐节耦合上限（Z0e/Z0 ≤ ~14.1，过耦显式拒绝）
_N_MAX = 15            # 节数上限（奇数）
_SIN_ARG_GUARD = 1e-9  # θ=kπ 奇异守卫阈值


def _sin_poly(n: int) -> list[float]:
    """sin(nθ) 按 x=sinθ 的幂级数系数（奇 n；整数二项式精确递推）。

    sin(nθ)=Im[(cosθ+j·sinθ)^n]=Σ_{m 奇} C(n,m)·(−1)^((m−1)/2)·(1−x²)^((n−m)/2)·x^m，
    再展开 (1−x²)^k=Σ_j C(k,j)(−1)^j x^{2j}。返回 [c0,c1,...]（c_k·x^k，
    偶次恒 0）。
    """
    coeffs = [0.0] * (n + 1)
    for m in range(1, n + 1, 2):
        sgn = 1.0 if ((m - 1) // 2) % 2 == 0 else -1.0
        k = (n - m) // 2
        for j in range(k + 1):
            coeffs[m + 2 * j] += (
                sgn * math.comb(n, m) * math.comb(k, j)
                * ((-1.0) ** j))
    return coeffs


def _g_poly(m_half: int) -> list[float]:
    """g(x)=∫₀ˣ(1−t²)^M dt 的系数（奇次幂；中心最大平坦半权母多项式）。"""
    coeffs = [0.0] * (2 * m_half + 2)
    for k in range(m_half + 1):
        coeffs[2 * k + 1] = ((-1.0) ** k * math.comb(m_half, k)
                             / (2.0 * k + 1.0))
    return coeffs


def _solve_linear(mat: list[list[float]], rhs: list[float]) -> list[float]:
    """小规模稠密线性方程组（部分主元 Gauss 消去；纯 Python 确定性）。"""
    n = len(rhs)
    a = [[*row[:], rhs[i]] for i, row in enumerate(mat)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-300:
            raise ValueError("multisection_coupler_binomial: 结点权线性系统"
                             "奇异（内部口径错误，请报告）")
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col] / a[col][col]
            for c2 in range(col, n + 1):
                a[r][c2] -= f * a[col][c2]
    return [a[i][n] / a[i][i] for i in range(n)]


def _junction_weights(n_sections: int) -> list[float]:
    """半权 Γ_0..Γ_M（未归一；最大平坦条件唯一解，符号前半正后半负）。"""
    big = n_sections // 2          # M：g(x) 的 (1−t²)^M 阶
    g = _g_poly(big)
    # 奇次幂系数 [x, x^3, ...]（g 的幂次 1..2M+1 = N）
    rhs = [g[2 * k + 1] for k in range(big + 1)]
    mat: list[list[float]] = []
    for k in range(big + 1):       # 行=x^(2k+1) 系数匹配
        # P_{N−2i} 次数=N−2i，2k+1 超次取 0（缺项补零）
        row = [(_sin_poly(n_sections - 2 * i)[2 * k + 1]
                if 2 * k + 1 <= n_sections - 2 * i else 0.0)
               for i in range(big + 1)]
        mat.append(row)
    half = _solve_linear(mat, rhs)
    # 全结点权：前半 +，后半 −（镜像反对称 Γ_{N−i}=−Γ_i）
    return half + [-v for v in reversed(half)]


def _couplings_from_junctions(gam: list[float]) -> list[float]:
    """节耦合 c_i=2Σ_{k<i}Γ_k（一阶 Γ≈Δc/2 恒等变形，c_0=c_{N+1}=0）。"""
    out: list[float] = []
    acc = 0.0
    for g in gam[:-1]:
        acc += g
        out.append(2.0 * acc)
    return out


def _ze_zo(c: float, z0: float) -> tuple[float, float]:
    from rfauto.core.slotline_transitions import even_odd_from_coupling

    return even_odd_from_coupling(c, z0)


def _abcd_cascade(z_list: list[float], th_list: list[float],
                  z_ref: float) -> tuple[complex, complex]:
    """2 端口线级联 ABCD → (S11, S21)（Pozar Table 4.2 转换）。"""
    aa = bb = cc = dd = 0.0
    a_mat = [1.0 + 0.0j, 0.0 + 0.0j, 0.0 + 0.0j, 1.0 + 0.0j]
    for zc, th in zip(z_list, th_list, strict=True):
        co = complex(math.cos(th), 0.0)
        si = complex(math.sin(th), 0.0)
        a_mat = [
            a_mat[0] * co + a_mat[1] * (1j * si / zc),
            a_mat[0] * (1j * zc * si) + a_mat[1] * co,
            a_mat[2] * co + a_mat[3] * (1j * si / zc),
            a_mat[2] * (1j * zc * si) + a_mat[3] * co,
        ]
    aa, bb, cc, dd = a_mat
    den = aa + bb / z_ref + cc * z_ref + dd
    s11 = (aa + bb / z_ref - cc * z_ref - dd) / den
    s21 = 2.0 / den
    return s11, s21


def _exact_s4(z0e: list[float], z0o: list[float], th_e: list[float],
              th_o: list[float], z0: float) -> dict[str, complex]:
    """偶/奇模级联叠加 → 端口 1 激励的 S11/S21/S31/S41（精确闭式）。"""
    se11, se21 = _abcd_cascade(z0e, th_e, z0)
    so11, so21 = _abcd_cascade(z0o, th_o, z0)
    return {
        "s11": (se11 + so11) / 2.0,
        "s21": (se21 + so21) / 2.0,
        "s31": (se11 - so11) / 2.0,
        "s41": (se21 - so21) / 2.0,
    }


def _db(x: complex) -> float:
    return 20.0 * math.log10(max(abs(x), 1e-300))


# ─── 键 1：二项式（中心最大平坦）多节综合 ─────────────────────────────────────

@register_calculator(
    "multisection_coupler_binomial",
    "多节定向耦合器二项式综合：对称 N 节（奇）中心最大平坦口径——结点反"
    "射权按 g(x)∝∫₀ˣ(1−t²)^M dt 三角分解唯一确定（N=3 → 结点比 1:9:9:1、"
    "节耦合比 1:10:1；N=5 → 3:25:150），节耦合累计→逐节 (Z0e,Z0o)（恒 "
    "Z0e·Z0o=Z0²，f0 隔离口精确零）。电平归一对精确偶/奇级联 θ=90° 求根，"
    "f0 精确命中目标耦合；一阶 vs 精确二阶差如实并列。锚：N=1 退化 vs 单"
    "节精确闭式逐位；最大平坦条件测试侧独立重解；能量守恒 ≤1e-12",
    (("n_sections", "int 耦合节数（正奇整数，1..15；3 节最常用）"),
     ("coupling_db", "float dB 目标耦合度（正数口径：10=10dB 耦合器）"),
     ("z0_ohm", "float Ω 端口/馈线阻抗（>0，缺省 50）")),
    required=("n_sections", "coupling_db"),
)
def multisection_coupler_binomial(n_sections: int, coupling_db: float,
                                  z0_ohm: float = 50.0) -> dict[str, Any]:
    n = float(n_sections)
    if n != int(n) or int(n) < 1 or int(n) > _N_MAX or int(n) % 2 == 0:
        raise ValueError(
            f"multisection_coupler_binomial: n_sections 须为正奇整数（1.."
            f"{_N_MAX}，对称结构），得到 {n_sections!r}")
    n = int(n)
    c_db = _finite(coupling_db, "coupling_db")
    if not 0.0 < c_db <= 60.0:
        raise ValueError(
            f"multisection_coupler_binomial: coupling_db 须 ∈(0,60]"
            f"（正数=耦合度口径），得到 {c_db!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"multisection_coupler_binomial: z0_ohm 必须 >0，得到 {z0!r}")
    c_target = 10.0 ** (-c_db / 20.0)

    gam_un = _junction_weights(n)
    g1 = sum(gam_un[i] * (1.0 if ((n - 2 * i) // 2) % 2 == 0 else -1.0)
             for i in range((n + 1) // 2))          # Σ Γ̃_i·sin((N−2i)π/2)
    scale_fo = c_target / (2.0 * abs(g1))

    def _exact_coupling(scale: float) -> float:
        cs = _couplings_from_junctions([scale * v for v in gam_un])
        ze = [_ze_zo(c, z0)[0] for c in cs]
        zo = [_ze_zo(c, z0)[1] for c in cs]
        s = _exact_s4(ze, zo, [math.pi / 2.0] * n, [math.pi / 2.0] * n, z0)
        return abs(s["s31"])

    # 电平归一：精确级联 |S31(90°)|=目标（scale 单调，二分确定性求根）
    lo_s, hi_s = scale_fo * 0.5, scale_fo * 2.0
    for _ in range(200):
        mid = 0.5 * (lo_s + hi_s)
        if _exact_coupling(mid) < c_target:
            lo_s = mid
        else:
            hi_s = mid
    scale = 0.5 * (lo_s + hi_s)
    gam = [scale * v for v in gam_un]
    couplings = _couplings_from_junctions(gam)
    bad = [(i + 1, c) for i, c in enumerate(couplings) if not 0.0 < c < _C_MAX]
    if bad:
        i1, c1 = bad[0]
        raise ValueError(
            f"multisection_coupler_binomial: 第 {i1} 节耦合 c={c1:.4f} 越域 "
            f"(0,{_C_MAX})——{n} 节在该目标耦合下过耦不可实现；增大节数或提"
            f"高耦合 dB（目标 {c_db:g}dB）")
    if any(c <= 0.0 for c in couplings):
        raise ValueError(
            "multisection_coupler_binomial: 节耦合出现非正值（内部口径错误，"
            "请报告）")
    ze_list: list[float] = []
    zo_list: list[float] = []
    zr_dev = 0.0
    for c in couplings:
        ze, zo = _ze_zo(c, z0)
        ze_list.append(ze)
        zo_list.append(zo)
        zr_dev = max(zr_dev, abs(ze * zo / (z0 * z0) - 1.0))

    # 精确级联 @f0（θ=90°）与带形采样（一阶口径的二阶差如实并列）
    th90 = [math.pi / 2.0] * n
    at_f0 = _exact_s4(ze_list, zo_list, th90, th90, z0)
    dev_db = _db(at_f0["s31"]) + c_db
    th_lo = math.radians(60.0)
    th_hi = math.radians(120.0)
    s_lo = _exact_s4(ze_list, zo_list, [th_lo] * n, [th_lo] * n, z0)
    s_hi = _exact_s4(ze_list, zo_list, [th_hi] * n, [th_hi] * n, z0)
    sym_dev = abs(abs(s_lo["s31"]) - abs(s_hi["s31"]))
    iso_lin = abs(at_f0["s41"])
    return {
        "n_sections": n,
        "coupling_db_target": c_db,
        "coupling_linear_target": round(c_target, 15),
        "z0_ohm": z0,
        "junction_gamma": [round(v, 15) for v in gam],
        "coupling_linear": [round(v, 15) for v in couplings],
        "coupling_db": [round(-20.0 * math.log10(max(v, 1e-300)), 9)
                        for v in couplings],
        "z0e_ohm": [round(v, 9) for v in ze_list],
        "z0o_ohm": [round(v, 9) for v in zo_list],
        "coupling_palindrome_dev": round(
            max(abs(couplings[i] - couplings[n - 1 - i])
                for i in range(n)), 18),
        "zr_identity_dev": round(zr_dev, 18),
        "first_order_s31_at_f0_linear": round(2.0 * abs(g1) * scale, 15),
        "first_order_s31_at_f0_db": round(
            20.0 * math.log10(max(2.0 * abs(g1) * scale, 1e-300)), 9),
        "exact_s31_at_f0_db": round(_db(at_f0["s31"]), 9),
        "exact_vs_target_db": round(dev_db, 12),
        "first_order_vs_exact_db": round(
            _db(at_f0["s31"])
            - 20.0 * math.log10(max(2.0 * abs(g1) * scale, 1e-300)), 9),
        "exact_s21_at_f0_db": round(_db(at_f0["s21"]), 9),
        "exact_s11_at_f0_db": round(_db(at_f0["s11"]), 9),
        "isolation_s41_at_f0_linear": round(iso_lin, 18),
        "isolation_s41_at_f0_db": (
            None if iso_lin < 1e-12 else round(_db(at_f0["s41"]), 9)),
        "s31_60deg_db": round(_db(s_lo["s31"]), 9),
        "s31_120deg_db": round(_db(s_hi["s31"]), 9),
        "symmetry_dev_60_120": round(sym_dev, 18),
        "note": (
            "一阶小反射口径（中心最大平坦），电平归一=对精确偶/奇级联在 "
            "θ=90° 求根（f0 精确命中目标，exact_vs_target_db=求根残差）；"
            "first_order_vs_exact_db=有限耦合二阶差（一阶口径的真实局限，"
            "如实并列不隐藏）；f0 隔离口 |S41|<1e-12 记 None（浮点配对地"
            "板，Z0e·Z0o=Z0² 性质）；60°/120° 对称残差=带形以 θ=90° 镜像"
            "的构造定理"),
        "source": _SOURCES["synth"],
    }


# ─── 键 2：逐节 (Z0e,Z0o) 精确频响 ───────────────────────────────────────────

@register_calculator(
    "multisection_coupler_response",
    "多节定向耦合器精确频响：逐节 (Z0e,Z0o)（≥1 节，段长=λ/4@f0）偶/奇模"
    "各自 2 端口线级联、叠加构造 4 端口（P1=入/P2=直通/P3=耦合/P4=隔离）"
    "——S11/S21/S31/S41 幅度+dB、方向性、能量守恒残差（构造恒无耗）；"
    "Z0e·Z0o=Z0² 配对下 f0 隔离口精确零（|S41|<1e-12 如实记 None）。锚："
    "N=1 vs 单节精确闭式 c·sinθ/√(1−c²cos²θ) 逐位 ≤1e-12",
    (("z0e_ohm", "array 逐节偶模阻抗 Ω（≥1 节）"),
     ("z0o_ohm", "array 逐节奇模阻抗 Ω（同长；须 Z0e>Z0o>0）"),
     ("f0_ghz", "float GHz 中心频率（段长=λ/4@f0；>0）"),
     ("freq_ghz", "array GHz 频率轴（>0；避开 θ=kπ 奇异点）"),
     ("z0_ohm", "float Ω 端口参考阻抗（>0，缺省 50）"),
     ("eps_eff", "float|array 逐节有效介电常数（≥1；标量=同步均匀，缺省 1）")),
    required=("z0e_ohm", "z0o_ohm", "f0_ghz", "freq_ghz"),
)
def multisection_coupler_response(z0e_ohm: list, z0o_ohm: list,
                                  f0_ghz: float, freq_ghz: list,
                                  z0_ohm: float = 50.0,
                                  eps_eff: float | list = 1.0
                                  ) -> dict[str, Any]:
    ze_l = [float(v) for v in z0e_ohm]
    zo_l = [float(v) for v in z0o_ohm]
    n_sec = len(ze_l)
    if n_sec < 1 or len(zo_l) != n_sec:
        raise ValueError(
            f"multisection_coupler_response: z0e/z0o 须为同长列表且 ≥1 节，"
            f"得到 {n_sec}/{len(zo_l)}")
    if any(not (a > b > 0.0) for a, b in zip(ze_l, zo_l, strict=True)):
        raise ValueError(
            "multisection_coupler_response: 每节须 Z0e > Z0o > 0")
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"multisection_coupler_response: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"multisection_coupler_response: z0_ohm 必须 >0，得到 {z0!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("multisection_coupler_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("multisection_coupler_response: 频率须 >0")
    if isinstance(eps_eff, (int, float)):
        eps_l = [float(eps_eff)] * n_sec
    else:
        eps_l = [float(v) for v in eps_eff]
        if len(eps_l) != n_sec:
            raise ValueError(
                f"multisection_coupler_response: eps_eff 标量或 {n_sec} 元"
                f"列表，得到 {len(eps_l)} 元")
    if any(e < 1.0 for e in eps_l):
        raise ValueError("multisection_coupler_response: eps_eff 须 ≥1")
    # θ=kπ 奇异守卫（任一节）
    for f in freqs:
        for e in eps_l:
            th = (math.pi / 2.0) * (f / f0) * math.sqrt(e)
            if abs(math.sin(th)) < _SIN_ARG_GUARD:
                raise ValueError(
                    f"multisection_coupler_response: f={f} GHz 触及节电长 "
                    f"θ=kπ 奇异点（显式拒绝）")

    def _th(f: float, e: float) -> float:
        return (math.pi / 2.0) * (f / f0) * math.sqrt(e)

    rows: list[dict[str, float]] = []
    energy_dev = 0.0
    for f in freqs:
        s = _exact_s4(ze_l, zo_l, [_th(f, e) for e in eps_l],
                      [_th(f, e) for e in eps_l], z0)
        p_tot = (abs(s["s11"]) ** 2 + abs(s["s21"]) ** 2
                 + abs(s["s31"]) ** 2 + abs(s["s41"]) ** 2)
        energy_dev = max(energy_dev, abs(p_tot - 1.0))
        iso = abs(s["s41"])
        rows.append({
            "s11": abs(s["s11"]), "s21": abs(s["s21"]),
            "s31": abs(s["s31"]), "s41": iso,
            "dir": (None if iso < 1e-300
                    else abs(s["s31"]) / iso),
        })
    at_f0 = _exact_s4(ze_l, zo_l, [math.pi / 2.0] * n_sec,
                      [math.pi / 2.0] * n_sec, z0)
    iso_f0 = abs(at_f0["s41"])
    return {
        "n_sections": n_sec,
        "f0_ghz": f0,
        "z0_ohm": z0,
        "freq_ghz": [round(f, 9) for f in freqs],
        "s11_db": [round(_db(complex(r["s11"])), 6) for r in rows],
        "s21_db": [round(_db(complex(r["s21"])), 6) for r in rows],
        "s31_db": [round(_db(complex(r["s31"])), 6) for r in rows],
        "s41_db": [round(_db(complex(r["s41"])), 6) for r in rows],
        "s11_mag": [round(r["s11"], 15) for r in rows],
        "s21_mag": [round(r["s21"], 15) for r in rows],
        "s31_mag": [round(r["s31"], 15) for r in rows],
        "s41_mag": [round(r["s41"], 18) for r in rows],
        "directivity_db": [
            (None if r["dir"] is None or r["dir"] < 1e-15
             else round(20.0 * math.log10(r["dir"]), 6)) for r in rows],
        "s31_at_f0_db": round(_db(at_f0["s31"]), 9),
        "s21_at_f0_db": round(_db(at_f0["s21"]), 9),
        "s11_at_f0_db": round(_db(at_f0["s11"]), 9),
        "isolation_s41_at_f0_linear": round(iso_f0, 18),
        "isolation_s41_at_f0_db": (
            None if iso_f0 < 1e-12 else round(_db(at_f0["s41"]), 9)),
        "energy_conservation_max_dev": round(energy_dev, 18),
        "note": (
            "偶/奇模精确级联（无耗理想线，段长=λ/4@f0、逐节 εeff；无宽度台"
            "阶不连续与色散修正——EM 冒烟实测总量）。方向性=20lg|S31/S41|，"
            "f0 处配对阻抗（Z0e·Z0o=Z0²）下 |S41|<1e-12 记 None（构造精"
            "确零的浮点地板）；θ=kπ 奇异频点显式拒绝"),
        "source": _SOURCES["resp"],
    }
