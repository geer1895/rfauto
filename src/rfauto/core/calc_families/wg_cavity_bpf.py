"""波导膜片耦合腔带通滤波器综合链（架构批 W10-S4 席，R3_domain_expansion
视角2 B1——滤波器实现族最后一块：微带耦合线侧 coupled_line_bpf 已有、波导
腔体侧组装链零命中）。

两键：wg_cavity_bpf_synthesize（g_k→J 倒置器→感性膜片电纳/开口/腔长全链）
/ wg_cavity_bpf_response（膜片电纳 λg 标度+腔电角逐频 ABCD 级联频响）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``wg_cavity|cavity_bpf|iris_coupled|coupled_cavity|waveguide_filter|腔体
滤波`` src/tests/scripts 三面零（varactor_bpf=变容管模板名误中）；既有
wg_iris 4 键=膜片器件级电纳/匹配/谐振窗/λg（无组装链）、cm_core=耦合矩
阵面、coupled_line_bpf=微带耦合线族、mask_filter=规格级——波导 BPF 组装
链（F1 lange 提升式同构先例）零。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
直接耦合腔滤波器 Cohn 1957 原文链（S.B. Cohn, "Direct-Coupled-Resonator
Filters", Proc. IRE 45(2), Feb 1957 pp.187-196，Fig.5 感性膜片波导滤波器
设计公式族；2026-10-19 本席全文逐字核验）。设计变量=**导内波长带限**
（Cohn Fig.5 原文口径 "the desired guide-wavelength passband limits
λg1 and λg2"）：

    λg0 = (λg1 + λg2)/2                    （Cohn eq.(19) 算术均值）
    w = (λg1 − λg2)/λg0                    （导内波长域相对带宽）

1. J 倒置器（πw/2 公式族与 coupled_line_bpf/Pozar §8.6.2 同形，g_k 走
   core/matching.chebyshev_g_values 单源）：

       J01/Z0 = √(πw/(2·g0·g1))
       Jj,j+1/Z0 = (πw/2)/√(gj·gj+1)（内部 j=1..N−1）
       JN,N+1/Z0 = √(πw/(2·gN·gN+1))

2. 膜片归一化电抗（Cohn Fig.13(e) 设计反演式 x=(K/Z0)/(1−(K/Z0)²)；
   代数恒等核验：t=tan(½arctan 2x) ⟺ x=t/(1−t²) 精确）：

       x_j = (J_j/Z0)/(1−(J_j/Z0)²)      （感性膜片，x>0）
       b_j = −1/x_j                       （归一化电纳口径，与
                                           wg_iris_susceptance 同号约定）

3. 膜片开口（消费 wg_iris_susceptance 同一薄膜片闭式反解——
   b=−(λg/a)cot²(πd/2a) ⟹ d=(2a/π)·arctan(√(λg0·x/a))，正反解
   roundtrip 逐位）。

4. 腔长（Cohn Fig.5 φi 式：θi = 180° − [arctan(2X'_{i−1,i}) +
   arctan(2X'_{i,i+1})]——负线长簿记 θi+½(φ_{i−1}+φ_i)=180°）：

       θ_i = π − ½[arctan(2x_{i−1,i}) + arctan(2x_{i,i+1})]
       l_i = θ_i·λg0/(2π)

5. 频响面（response 键）：膜片电抗随导内波长反比标度（Cohn 原文逐字
   "The iris reactance is assumed to vary in inverse proportion to guide
   wavelength"——与薄膜片闭式自身 λg 依赖同标度：b ∝ λg ⟹ x ∝ λg0/λg(f)，
   两路径逐位同值=#118 同文件双路径）；腔电角 ψi(f)=2π·l_i/λg(f)；级联
   [并联 b0]·[线 ψ1]·[并联 b1]…[线 ψN]·[并联 bN] → ABCD→S。响应在 λg 轴
   对称（Cohn 原文性质），带限 f1/f2 经 λg 映射后响应带缘落纹波位（本席
   实测：w=3.5% N=3 档带缘 S21=−0.46/−0.52dB≈0.5dB 纹波位，带外 −10dB）。

边界（如实）
--------------------------------------------------------
- 精度域：w≤0.2 显式守卫（Cohn 原文 "good results with bandwidths of at
  least 20 percent in guide wavelength"——域内高档通带纹波畸变渐显（原文
  Fig.8/9 同行为），消费者须以响应键全带复核）。
- 薄膜片近似（零厚度感性窗，wg_iris_susceptance 同口径）；厚膜片/销钉/
  谐振窗结构不在此口径。无耗假设（Q→∞），有限 Q 插损面不入键面。
- f≤TE10 截止显式拒绝（_frequency 守卫同源）。

出处：Cohn 1957 Proc. IRE 45(2) pp.187-196（Fig.5/Fig.13(e)/λg 标度全链
逐字；J 公式族与 Pozar §8.6.2/MYJ ch.8 同形——coupled_line_bpf 已双源在
案）；g_k：Pozar 表 8.4（core/matching 单源）；膜片闭式：Marcuvitz
Waveguide Handbook 薄感性窗工程式（wg_iris_susceptance 同源）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite
from .waveguide_iris import _frequency, _guide_dims


def _design_chain(order: int, f1_ghz: float, f2_ghz: float, ripple_db: float,
                  a_mm: float, b_mm: float) -> dict[str, Any]:
    """Cohn 链共享计算段（synthesize/response 两键单源；返回原始量）。

    g_k 走 core/matching 单源（coupled_line_bpf._g_values 同路径）；J 目
    标与 coupled_line_bpf._x_targets 同一 π/2 公式族（带宽自变量按 Cohn
    Fig.5 口径取导内波长域 w——跨族公式同源、域定义按主源）。"""
    from rfauto.core.calc_families.coupled_line_bpf import (
        _g_values,
    )

    tag = "wg_cavity_bpf"
    n = int(order)
    if n < 1 or order != int(order):
        raise ValueError(
            f"{tag}: order 须为 ≥1 整数（N=1 单腔合法），得到 {order!r}")
    f1 = _finite(f1_ghz, f"{tag}.f1_ghz")
    f2 = _finite(f2_ghz, f"{tag}.f2_ghz")
    if f1 <= 0.0 or f2 <= 0.0:
        raise ValueError(
            f"{tag}: 通带频率必须 >0，得 {f1_ghz!r}/{f2_ghz!r}")
    if f2 <= f1:
        raise ValueError(
            f"{tag}: 须 f2>f1（f1=下带缘/f2=上带缘；λg1>λg2），得 "
            f"{f1!r}/{f2!r}")
    rip = _finite(ripple_db, f"{tag}.ripple_db")
    if rip <= 0.0:
        raise ValueError(f"{tag}: ripple_db 必须 >0，得 {ripple_db!r}")
    a, b = _guide_dims(a_mm, b_mm, tag)

    # Cohn Fig.5 原生变量：导内波长带限与带宽
    _, lam_g1_mm, fc10_ghz = _frequency(a, f1, tag)
    _, lam_g2_mm, _ = _frequency(a, f2, tag)
    lam_g0_mm = 0.5 * (lam_g1_mm + lam_g2_mm)          # eq.(19) 算术均值
    w_lg = (lam_g1_mm - lam_g2_mm) / lam_g0_mm
    if not 0.0 < w_lg <= 0.2:
        raise ValueError(
            f"{tag}: 导内波长域相对带宽 w={w_lg:.6f} 在 (0,0.2] 外（Cohn "
            "精度域口径 ~20%；带限经 λg(f) 色散映射，同频域 δ 可能显著不同"
            "——如实拒绝）")

    g = _g_values(n, rip)
    j_list = [math.sqrt(math.pi * w_lg / (2.0 * g[0] * g[1]))]
    for j in range(1, n):
        j_list.append((math.pi * w_lg / 2.0) / math.sqrt(g[j] * g[j + 1]))
    j_list.append(math.sqrt(math.pi * w_lg / (2.0 * g[n] * g[n + 1])))

    x_list: list[float] = []
    for idx, jv in zip([f"J_{k}{k + 1}" for k in range(n + 1)], j_list,
                       strict=True):
        if not 0.0 < jv < 1.0:
            raise ValueError(
                f"{tag}: 倒置器 {idx}/Z0={jv!r} 出 (0,1)（w 守卫下结构性"
                "不可能；膜片电抗反演式失域）")
        x_list.append(jv / (1.0 - jv * jv))  # Cohn 精确反演式

    # 膜片开口：b=−(λg/a)cot²(πd/2a) 反解（=wg_iris_susceptance 反方向
    # 同式；|b|=1/x ⟹ tan(πd/2a)=√(λg0·x/a)）
    d_list = [
        (2.0 * a / math.pi) * math.atan(math.sqrt(lam_g0_mm * xv / a))
        for xv in x_list
    ]

    # 腔长（Cohn Fig.5 φi 式；负线长簿记 θi+½(φ_{i−1}+φ_i)=180°）
    theta_list = [
        math.pi - 0.5 * (math.atan(2.0 * x_list[i - 1])
                         + math.atan(2.0 * x_list[i]))
        for i in range(1, n + 1)
    ]
    l_list = [th * lam_g0_mm / (2.0 * math.pi) for th in theta_list]

    return {
        "order": n, "f1_ghz": f1, "f2_ghz": f2,
        "f0_ghz": math.sqrt(f1 * f2),
        "w_lg": w_lg, "ripple_db": rip, "a_mm": a, "b_mm": b,
        "fc10_ghz": fc10_ghz,
        "lambda_g0_mm": lam_g0_mm,
        "lambda_g1_mm": lam_g1_mm, "lambda_g2_mm": lam_g2_mm,
        "g": g, "j_over_z0": j_list, "x_norm": x_list,
        "b_norm": [-1.0 / xv for xv in x_list],
        "iris_open_mm": d_list,
        "theta_rad": theta_list, "cavity_len_mm": l_list,
    }


@register_calculator(
    "wg_cavity_bpf_synthesize",
    "波导耦合腔 BPF 综合：Cohn 1957 Proc.IRE 全链（原生导内波长域）——"
    "通带边缘+纹波+波导尺寸 → λg 带限（λg0 算术均值、w=(λg1−λg2)/"
    "λg0）→ g_k（core/matching 单源）→ J 倒置器 → 膜片电抗 x=J/(1−J²) 精"
    "确反演 → 膜片开口 d（wg_iris 薄膜片闭式反解 roundtrip）→ 腔长 "
    "l_i=θ_i·λg0/2π（负线长簿记）。精度域 w≤0.2（Cohn ~20% 口径）如实守"
    "卫；无耗薄膜片假设（有限 Q 插损不入键面）",
    (("order", "int 谐振腔数 N（≥1；膜片数=N+1）"),
     ("f1_ghz", "float GHz 通带下带缘（>TE10 截止；映射 λg1）"),
     ("f2_ghz", "float GHz 通带上带缘（>f1；映射 λg2）"),
     ("ripple_db", "float dB 通带等纹波（>0；Chebyshev 原型）"),
     ("a_mm", "float mm 波导宽边（>0）"),
     ("b_mm", "float mm 波导窄边（0<b≤a）")),
    required=("order", "f1_ghz", "f2_ghz", "ripple_db", "a_mm", "b_mm"),
)
def wg_cavity_bpf_synthesize(order: int, f1_ghz: float, f2_ghz: float,
                             ripple_db: float, a_mm: float,
                             b_mm: float) -> dict[str, Any]:
    d = _design_chain(order, f1_ghz, f2_ghz, ripple_db, a_mm, b_mm)
    r = 9
    return {
        "order": d["order"],
        "f1_ghz": round(d["f1_ghz"], r), "f2_ghz": round(d["f2_ghz"], r),
        "f0_ghz": round(d["f0_ghz"], r), "w_lg": round(d["w_lg"], r),
        "ripple_db": round(d["ripple_db"], r),
        "a_mm": round(d["a_mm"], r), "b_mm": round(d["b_mm"], r),
        "fc10_ghz": round(d["fc10_ghz"], r),
        "lambda_g0_mm": round(d["lambda_g0_mm"], r),
        "lambda_g1_mm": round(d["lambda_g1_mm"], r),
        "lambda_g2_mm": round(d["lambda_g2_mm"], r),
        "g": [round(v, 9) for v in d["g"]],
        "j_over_z0": [round(v, 9) for v in d["j_over_z0"]],
        "x_norm": [round(v, 9) for v in d["x_norm"]],
        "b_norm": [round(v, 9) for v in d["b_norm"]],
        "iris_open_mm": [round(v, 6) for v in d["iris_open_mm"]],
        "theta_rad": [round(v, 9) for v in d["theta_rad"]],
        "cavity_len_mm": [round(v, 6) for v in d["cavity_len_mm"]],
        "iris_open_over_a": [round(v / d["a_mm"], 9)
                             for v in d["iris_open_mm"]],
        "note": ("Cohn 1957 原生 λg 域设计（响应 λg 轴对称，带缘经 λg(f) "
                 "映射落纹波位）；膜片=零厚度感性窗（wg_iris_susceptance "
                 "同式）；response 键为频响面"),
    }


def _cascade_s(freq_ghz: float, d: dict[str, Any]) -> tuple[complex, complex]:
    """膜片-腔级联 2 端口 S（单频；ABCD 路径与 fake_adapter 同构）。

    膜片电抗标度 x(f)=x0·λg0/λg(f)（Cohn 原文 stated model——与薄膜片闭
    式自身 λg 依赖同标度，两路径逐位同值）；腔电角 ψ=2π·l/λg(f)。"""
    _, lam_g_mm, _ = _frequency(d["a_mm"], freq_ghz,
                                "wg_cavity_bpf_response")
    scale = d["lambda_g0_mm"] / lam_g_mm
    abcd = [[1.0 + 0j, 0j], [0j, 1.0 + 0j]]

    def _mul(m2: list[list[complex]]) -> None:
        a00, a01 = abcd[0]
        a10, a11 = abcd[1]
        abcd[0][0] = a00 * m2[0][0] + a01 * m2[1][0]
        abcd[0][1] = a00 * m2[0][1] + a01 * m2[1][1]
        abcd[1][0] = a10 * m2[0][0] + a11 * m2[1][0]
        abcd[1][1] = a10 * m2[0][1] + a11 * m2[1][1]

    def _shunt(y_norm: complex) -> None:
        _mul([[1.0 + 0j, 0j], [y_norm, 1.0 + 0j]])

    def _line(theta: float) -> None:
        cs = complex(math.cos(theta))
        sn = 1j * complex(math.sin(theta))
        _mul([[cs, sn], [sn, cs]])

    for k in range(d["order"] + 1):
        if k > 0:
            _line(2.0 * math.pi * d["cavity_len_mm"][k - 1] / lam_g_mm)
        y = -1j / (d["x_norm"][k] * scale)  # 感性膜片：b=−1/x（λg 标度）
        _shunt(y)

    a, bmat = abcd[0][0], abcd[0][1]
    cmat, dmat = abcd[1][0], abcd[1][1]
    den = a + bmat + cmat + dmat  # Z0=1 归一化
    s11 = (a + bmat - cmat - dmat) / den
    s21 = 2.0 / den
    return s11, s21


@register_calculator(
    "wg_cavity_bpf_response",
    "波导膜片耦合腔 BPF 频响：synthesize 同参设计的逐频 ABCD 级联（膜片"
    "电抗 λg 反比标度=Cohn 原文 stated model+薄膜片闭式自身 λg 依赖双路"
    "径同值；腔电角 ψ=2π·l/λg；响应 λg 轴对称）。输出 S11/S21 dB 与无耗"
    "守恒残差（无耗薄膜片假设面；有限 Q 插损不入键面）",
    (("freq_ghz", "array GHz 频率轴（全部 >TE10 截止）"),
     ("order", "int 谐振腔数 N（≥1）"),
     ("f1_ghz", "float GHz 通带下带缘（>TE10 截止）"),
     ("f2_ghz", "float GHz 通带上带缘（>f1）"),
     ("ripple_db", "float dB 通带等纹波（>0）"),
     ("a_mm", "float mm 波导宽边（>0）"),
     ("b_mm", "float mm 波导窄边（0<b≤a）")),
    required=("freq_ghz", "order", "f1_ghz", "f2_ghz", "ripple_db",
              "a_mm", "b_mm"),
)
def wg_cavity_bpf_response(freq_ghz: list, order: int, f1_ghz: float,
                           f2_ghz: float, ripple_db: float, a_mm: float,
                           b_mm: float) -> dict[str, Any]:
    tag = "wg_cavity_bpf_response"
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError(f"{tag}: freq_ghz 不能为空")
    d = _design_chain(order, f1_ghz, f2_ghz, ripple_db, a_mm, b_mm)

    s11_list: list[float] = []
    s21_list: list[float] = []
    unitary_res: list[float] = []
    for f in freqs:
        s11, s21 = _cascade_s(_finite(f, f"{tag}.freq_ghz"), d)
        s11_list.append(20.0 * math.log10(max(abs(s11), 1e-300)))
        s21_list.append(20.0 * math.log10(max(abs(s21), 1e-300)))
        unitary_res.append(abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0))

    return {
        "freq_ghz": [round(v, 9) for v in freqs],
        "order": d["order"],
        "s11_db": [round(v, 6) for v in s11_list],
        "s21_db": [round(v, 6) for v in s21_list],
        "unitary_residual_max": max(unitary_res),
        "f0_ghz": round(d["f0_ghz"], 9),
        "w_lg": round(d["w_lg"], 9),
        "note": ("无耗薄膜片口径；设计原生 λg 域（w 守卫与精度域见模块 "
                 "docstring）"),
    }
