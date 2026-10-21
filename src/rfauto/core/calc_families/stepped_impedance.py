"""阶梯阻抗低通滤波器（stepped-impedance LPF）综合内核（架构批 W1-S3 席域，
R2_core_tier3 §⑤ F2 设计案）。

出处（阶梯阻抗 LPF 综合经典口径，文末「出处」节转录）：
- stepped_impedance_lpf_synthesize：原型 g_k→高低阻段电长设计式
  （D. Pozar, Microwave Engineering 4th ed. §8.3；切比雪夫 g 值表
  Matthaei-Young-Jones Table 4.05-1 经 core/synthesis 单源转引）。
- stepped_impedance_response：均匀线 ABCD 级联频响（Pozar Table 4.2
  换算；无耗互易构造性成立）。

两键：stepped_impedance_lpf_synthesize（原型 g_k 阶梯 → 感性高阻段/容性低阻
段电长 → HJ 线宽精算 → 逐段物理长）/ stepped_impedance_response（高低阻
均匀线 ABCD 级联 → |S11|/|S21| dB + fc−3dB 回收 + 无耗守恒残差）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- 原型 g 值（低通梯形原型，等端接）：
  binomial（最平坦）：g_k = 2·sin((2k−1)π/(2N))（精确闭式，Pozar 4th ed.
  Table 8.3 最平坦原型同式；g_{N+1}=1 等端接对任意 N 成立）；
  chebyshev（等纹波）：**单源复用** core/synthesis.chebyshev_lpf_g_values
  （MYJ Table 4.05-1 同源内嵌表，N≤4；ripple_db 口径=带内 |S11| 上限负 dB，
  与该函数一致透传）——本面零公式复制（#116）。
- 阶梯实现（Pozar 4th ed. §8.3 stepped-impedance LPF 设计式）：串联电感
  （g_k 奇位）以高阻短线上实现——在 fc 处等电抗条件
  Z_high·tanθ_L = g_k·Z0 → θ_L = arctan(g_k·Z0/Z_high)；并联电容（偶位）
  以低阻短线实现——tanθ_C = g_k·Z_low/Z0 → θ_C = arctan(g_k·Z_low/Z0)。
  阶梯近似精度随 Z_high/Z_low 比值增大而改善（段长趋短），βL > π/4 时
  近似劣化如实记 note 不拦截。
- 物理长：l_i = θ_i·λ_g,i/(2π) = θ_i·c/(2π·fc·√εeff_i)，εeff_i 取该段
  自身线宽的 skrf HJ 正向 @fc（铁律 1c 唯一线宽/介质口径；XA-3 迭代序同
  款——各段按自身 εeff 独立精算）。
- 等端接约束：chebyshev 偶数节原型 g_{N+1}≠1（不等端接），与两端口等
  Z0 端接的实现语义冲突——显式拒绝（binomial 任意 N 放行）。
- 响应键：高低阻均匀线 ABCD（Pozar Table 4.2 阻抗形）级联 → 2 端口 S；
  无耗互易由构造保证（|S11|²+|S21|²=1 残差随值报告）。fc−3dB=自低频段
  首次穿越 −3dB 的插值回收；离散段化固有偏差（arctan 等电抗近似+色散）
  如实并列，不冒充精确。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- lc_filter/mask_filter=集总/规格级、synthesize_commensurate_line（core/
  matching）=Richards 全 λ/4 变换（同名阶梯异域）、stub_filter_design=
  stub BPF、stepped_impedance **模板**（oe_templates，高低阻谐振器链渲染
  +fake 裁判）=实现级通道——本族只做 (fc,ripple,N)→几何的 LPF 综合两键。

出处
----
- D. Pozar, Microwave Engineering 4th ed. §8.3（stepped-impedance LPF 电长
  设计式；Example 8.2 口径参照：N=5 最平坦、fc=2GHz、50Ω、Z_high=150Ω、
  Z_low=10Ω——印刷数值未回原文逐位核对不硬钉，闭式直算锚在测试侧）。
- Matthaei-Young-Jones (MYJ), Microwave Filters, Impedance-Matching
  Networks, and Coupling Structures（原型 g 值表出处，经
  core/synthesis.chebyshev_lpf_g_values 内嵌表单源转引）。

守卫：n_sections 整数 ≥1（chebyshev 限奇数且 N≤4=表域）；fc/z0/Z_high/
Z_low>0 且 Z_high>Z0>Z_low；chebyshev 必须显式 ripple_db（负 dB ∈
[-60,−0.05]，同源口径）；response 键 Z_high>Z_low>0、εeff≥1、长度>0、
频率>0；全部越界显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

__all__ = [
    "stepped_impedance_lpf_synthesize",
    "stepped_impedance_response",
]

_N_MAX = 13          # 节数上限（最平坦闭式任意 N 可算，工程域显式收口）
_THETA_WARN_RAD = math.pi / 4.0   # 阶梯近似劣化提示阈（βL>π/4 如实记 note）


def _binomial_g_values(n: int) -> list[float]:
    """最平坦低通原型 g_k=2·sin((2k−1)π/(2N))（精确闭式；N=3 → [1,2,1]、
    N=5 → 0.618/1.618/2.000/1.618/0.618 = Pozar Table 8.3 同值）。"""
    return [2.0 * math.sin((2 * k - 1) * math.pi / (2.0 * n))
            for k in range(1, n + 1)]


def _abcd_cascade(z_list: list[float], th_list: list[float],
                  z_ref: float) -> tuple[complex, complex]:
    """2 端口均匀线链 ABCD 级联 → (S11, S21)（Pozar Table 4.2 阻抗形转换；
    与 calc_families.multisection_coupler._abcd_cascade 同式独立实现，
    测试双路线互证）。"""
    aa = 1.0 + 0.0j
    bb = 0.0 + 0.0j
    cc = 0.0 + 0.0j
    dd = 1.0 + 0.0j
    for zc, th in zip(z_list, th_list, strict=True):
        co = complex(math.cos(th), 0.0)
        si = complex(math.sin(th), 0.0)
        aa, bb, cc, dd = (
            aa * co + bb * (1j * si / zc),
            aa * (1j * zc * si) + bb * co,
            cc * co + dd * (1j * si / zc),
            cc * (1j * zc * si) + dd * co,
        )
    den = aa + bb / z_ref + cc * z_ref + dd
    return (aa + bb / z_ref - cc * z_ref - dd) / den, 2.0 / den


# ─── 键 1：阶梯阻抗 LPF 综合 ─────────────────────────────────────────────────

@register_calculator(
    "stepped_impedance_lpf_synthesize",
    "阶梯阻抗低通滤波器综合（Pozar §8.3）：原型 g_k 阶梯 → 串联电感=高阻"
    "短线（θ_L=arctan(g_k·Z0/Z_high)）、并联电容=低阻短线（θ_C=arctan"
    "(g_k·Z_low/Z0)）→ HJ 逐段线宽/εeff 精算（铁律 1c）→ 物理长。原型"
    "两档：binomial 精确闭式 2sin((2k−1)π/2N)（任意 N）/ chebyshev 单源"
    "复用 chebyshev_lpf_g_values（N≤4 奇数，等端接约束）。锚：Pozar "
    "Example 8.2 设计式口径 + g 表同仓逐位对照",
    (("n_sections", "int 低通节数（≥1；chebyshev 限奇数 ≤4=g 表域）"),
     ("fc_ghz", "float GHz 截止频率（>0）"),
     ("prototype", "str binomial|chebyshev（缺省 binomial）"),
     ("ripple_db", "float chebyshev 必填：带内 |S11| 上限负 dB ∈[-60,-0.05]"
                   "（与 chebyshev_lpf_g_values 同口径透传）"),
     ("z0_ohm", "float Ω 端接阻抗（缺省 50；须 Z_low<Z0<Z_high）"),
     ("z_high_ohm", "float Ω 高阻段（感性）特性阻抗（缺省 120）"),
     ("z_low_ohm", "float Ω 低阻段（容性）特性阻抗（缺省 20）"),
     ("er", "float 基板相对介电常数（>1，缺省 3.66 rogers4350b）"),
     ("h_mm", "float mm 基板厚度（>0，缺省 0.508）")),
    required=("n_sections", "fc_ghz"),
)
def stepped_impedance_lpf_synthesize(
    n_sections: int, fc_ghz: float, prototype: str = "binomial",
    ripple_db: float | None = None, z0_ohm: float = 50.0,
    z_high_ohm: float = 120.0, z_low_ohm: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
) -> dict[str, Any]:
    """(N, fc, 原型) → g_k 阶梯 + 逐段 (类型, 电长, 线宽, εeff, 物理长)。"""
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    if isinstance(n_sections, bool) or not isinstance(n_sections, int):
        raise ValueError(
            f"stepped_impedance_lpf_synthesize: n_sections 须为整数，"
            f"得到 {n_sections!r}")
    n = int(n_sections)
    if not 1 <= n <= _N_MAX:
        raise ValueError(
            f"stepped_impedance_lpf_synthesize: n_sections 须 ∈[1,"
            f"{_N_MAX}]，得到 {n}")
    proto = str(prototype).strip().lower()
    if proto not in ("binomial", "chebyshev"):
        raise ValueError(
            f"stepped_impedance_lpf_synthesize: prototype 须 binomial|"
            f"chebyshev，得到 {prototype!r}")
    fc = _finite(fc_ghz, "fc_ghz")
    if fc <= 0.0:
        raise ValueError(
            f"stepped_impedance_lpf_synthesize: fc_ghz 必须 >0，得到 {fc!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    zh = _finite(z_high_ohm, "z_high_ohm")
    zl = _finite(z_low_ohm, "z_low_ohm")
    if not zh > z0 > zl > 0.0:
        raise ValueError(
            "stepped_impedance_lpf_synthesize: 须 z_high_ohm > z0_ohm > "
            f"z_low_ohm > 0，得到 ({zh}, {z0}, {zl})")
    if float(er) <= 1.0 or float(h_mm) <= 0.0:
        raise ValueError(
            "stepped_impedance_lpf_synthesize: 须 er>1 且 h_mm>0，得到 "
            f"({er!r}, {h_mm!r})")

    g_values: list[float]
    ripple_out: float | None = None
    passband_ripple_db: float | None = None
    if proto == "binomial":
        g_values = _binomial_g_values(n)
    else:
        if n % 2 == 0:
            raise ValueError(
                "stepped_impedance_lpf_synthesize: chebyshev 偶数节原型 "
                "g_{N+1}≠1（不等端接），与两端口等 Z0 端接实现语义冲突——"
                "显式拒绝（等端接综合用 binomial 或奇数 N）")
        if ripple_db is None:
            raise ValueError(
                "stepped_impedance_lpf_synthesize: chebyshev 必须显式给 "
                "ripple_db（带内 |S11| 上限负 dB，同 chebyshev_lpf_g_values "
                "口径）")
        from rfauto.core.synthesis import chebyshev_lpf_g_values

        gspec = chebyshev_lpf_g_values(n, ripple_db)
        g_values = [float(v) for v in gspec["g_values"]]
        ripple_out = float(gspec["ripple_db_requested"])
        passband_ripple_db = float(gspec["passband_ripple_db"])

    stackup = Stackup(name="stepped_impedance_lpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    w_high, _zh_act, _st_h = inverse_width(zh, fc, stackup)
    w_low, _zl_act, _st_l = inverse_width(zl, fc, stackup)
    w_feed = float(inverse_width(z0, fc, stackup)[0])
    ere_h = float(forward_z0(float(w_high), fc, stackup)[1])
    ere_l = float(forward_z0(float(w_low), fc, stackup)[1])

    section_types: list[str] = []
    theta_rad: list[float] = []
    theta_deg: list[float] = []
    lengths_mm: list[float] = []
    for k, g_k in enumerate(g_values):
        if k % 2 == 0:      # 奇位（0 基偶数）= 串联电感 = 高阻段
            th = math.atan(g_k * z0 / zh)
            ere = ere_h
            section_types.append("L")
        else:               # 偶位 = 并联电容 = 低阻段
            th = math.atan(g_k * zl / z0)
            ere = ere_l
            section_types.append("C")
        theta_rad.append(th)
        theta_deg.append(math.degrees(th))
        lengths_mm.append(th * C_MM_GHZ / (2.0 * math.pi * fc * math.sqrt(ere)))

    notes = [
        f"原型 {proto}：g=" + "[" + ", ".join(f"{v:.6f}" for v in g_values)
        + "]" + ("（最平坦精确闭式 2sin((2k−1)π/2N)，g_{N+1}=1 等端接）"
                 if proto == "binomial" else
                 f"（MYJ 表单源 chebyshev_lpf_g_values；纹波档 "
                 f"{passband_ripple_db}dB 通带纹波口径）"),
        "阶梯实现（Pozar §8.3）：θ_L=arctan(g_k·Z0/Z_high)、θ_C=arctan"
        "(g_k·Z_low/Z0)，逐段 l=θ·c/(2π·fc·√εeff)（εeff 按自身线宽 HJ @fc）",
        f"最大电长 {max(theta_deg):.2f}°"
        + ("（≤45° 阶梯近似域内）" if max(theta_rad) <= _THETA_WARN_RAD
           else "（>45°——阶梯近似劣化，结果如实降级不冒充精确）"),
        "响应回收（stepped_impedance_response 键）与综合的 fc−3dB 偏差为"
        "离散段化固有量（等电抗近似+色散），如实并列不冒充精确",
    ]
    return {
        "n_sections": n,
        "prototype": proto,
        "fc_ghz": fc,
        "ripple_db": ripple_out,
        "passband_ripple_db": passband_ripple_db,
        "z0_ohm": z0,
        "z_high_ohm": zh,
        "z_low_ohm": zl,
        "g_values": g_values,
        "section_types": section_types,
        "theta_rad": theta_rad,
        "theta_deg": theta_deg,
        "w_high_mm": float(w_high),
        "w_low_mm": float(w_low),
        "ereff_high": ere_h,
        "ereff_low": ere_l,
        "lengths_mm": lengths_mm,
        "total_len_mm": sum(lengths_mm),
        "w_feed_mm": w_feed,
        "notes": notes,
    }


# ─── 键 2：阶梯阻抗链频响 ────────────────────────────────────────────────────

@register_calculator(
    "stepped_impedance_response",
    "阶梯阻抗链频响：高低阻均匀线 ABCD 级联（段型 L 高阻起交替）→ 2 端口 "
    "|S11|/|S21| dB（Pozar Table 4.2；无耗互易由构造保证，守恒残差随值"
    "报告）+ fc−3dB 首穿越插值回收 + 带内最差回损。fc 回收 vs 综合目标"
    "的偏差=离散段化固有量（如实并列）",
    (("z_high_ohm", "float Ω 高阻段特性阻抗（>z_low_ohm；键 1 出口）"),
     ("z_low_ohm", "float Ω 低阻段特性阻抗（>0）"),
     ("ereff_high", "float 高阻段有效介电常数（≥1；键 1 出口 ereff_high）"),
     ("ereff_low", "float 低阻段有效介电常数（≥1；键 1 出口 ereff_low）"),
     ("lengths_mm", "array 逐段物理长 mm（>0；长短阻交替起）"),
     ("freq_ghz", "array GHz 频率轴（>0，须覆盖 −3dB 穿越才有 fc 回收）"),
     ("z_ref_ohm", "float Ω 参考阻抗（>0，缺省 50）")),
    required=("z_high_ohm", "z_low_ohm", "ereff_high", "ereff_low",
              "lengths_mm", "freq_ghz"),
)
def stepped_impedance_response(
    z_high_ohm: float, z_low_ohm: float, ereff_high: float,
    ereff_low: float, lengths_mm: list, freq_ghz: list,
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """高低阻 ABCD 级联频响（|S|dB 列表面——非复 S 矩阵产出）。"""
    zh = _finite(z_high_ohm, "z_high_ohm")
    zl = _finite(z_low_ohm, "z_low_ohm")
    if not zh > zl > 0.0:
        raise ValueError(
            f"stepped_impedance_response: 须 z_high_ohm > z_low_ohm > 0，"
            f"得到 ({zh}, {zl})")
    eh = _finite(ereff_high, "ereff_high")
    el = _finite(ereff_low, "ereff_low")
    if min(eh, el) < 1.0:
        raise ValueError(
            f"stepped_impedance_response: ereff_high/ereff_low 须 ≥1，"
            f"得到 ({eh}, {el})")
    lens = [float(v) for v in lengths_mm]
    if not lens or any(v <= 0.0 for v in lens):
        raise ValueError(
            "stepped_impedance_response: lengths_mm 须非空且全 >0")
    zr = _finite(z_ref_ohm, "z_ref_ohm")
    if zr <= 0.0:
        raise ValueError(
            f"stepped_impedance_response: z_ref_ohm 必须 >0，得到 {zr!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("stepped_impedance_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("stepped_impedance_response: 频率须 >0")

    z_by_type = {"L": zh, "C": zl}       # 段型标签沿用键 1（L=高阻感性起）
    ere_by_type = {"L": eh, "C": el}
    s11_db: list[float] = []
    s21_db: list[float] = []
    energy_dev = 0.0
    for f in freqs:
        z_list: list[float] = []
        th_list: list[float] = []
        for i, ln in enumerate(lens):
            typ = "L" if i % 2 == 0 else "C"
            ere = ere_by_type[typ]
            th = (2.0 * math.pi * f * 1e9 * math.sqrt(ere) * (ln * 1e-3)
                  / 299792458.0)
            z_list.append(z_by_type[typ])
            th_list.append(th)
        s11, s21 = _abcd_cascade(z_list, th_list, zr)
        s11_db.append(20.0 * math.log10(max(abs(s11), 1e-300)))
        s21_db.append(20.0 * math.log10(max(abs(s21), 1e-300)))
        energy_dev = max(energy_dev,
                         abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0))

    # fc−3dB：自频率轴起点（通带侧）首次向下穿越 −3dB 的线性插值回收
    fc_3db: float | None = None
    for i in range(1, len(freqs)):
        if s21_db[i] <= -3.0 < s21_db[i - 1]:
            lo, hi = s21_db[i - 1], s21_db[i]
            t = (lo - (-3.0)) / (lo - hi)
            fc_3db = freqs[i - 1] + t * (freqs[i] - freqs[i - 1])
            break
    # 带内最差回损（f ≤ fc−3dB；无回收点则全轴如实报告）
    inband = ([db for f, db in zip(freqs, s11_db, strict=True)
               if fc_3db is None or f <= fc_3db])
    rl_worst = -max(inband) if inband else None
    return {
        "n_points": len(freqs),
        "freq_ghz": freqs,
        "s11_db": s11_db,
        "s21_db": s21_db,
        "fc_3db_ghz": fc_3db,
        "rl_worst_inband_db": rl_worst,
        "energy_residual_max": energy_dev,
        "notes": [
            "段型交替：index 0 起高阻（L 感性）、奇数位低阻（C 容性）——"
            "与 stepped_impedance_lpf_synthesize 输出同口径",
            "fc_3db_ghz=−3dB 首次向下穿越的线性插值（频率轴须覆盖穿越点，"
            "未覆盖为 None 如实报告）；rl_worst_inband_db=带内最差回损",
            "无耗守恒 |S11|²+|S21|²=1 由构造保证；阶梯跳宽不连续性不进"
            "模型（EM 冒烟实测其总量，stepped_impedance 模板 fake 同口径"
            "假设清单）",
        ],
    }
