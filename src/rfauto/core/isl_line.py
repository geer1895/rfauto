r"""TA-10 ISL/SISL 集成悬置线确定性内核（ge8b Wave B 席 B9，2026-10-03）。

规格：研究扩充 round15 §二·2 TA-10「ISL/SISL 集成
悬置线（用户点名）：suspended_stripline+siw 过孔墙；Shu-Qi 屏蔽悬置式（IET
明示无可频变闭式→**准静态口径如实**）」+ ge8b 席 B9 任务书「闭式内核（悬置/
倒置微带 εeff 准静态近似）」。

规格边界（#122 如实）
--------------------
- **准静态一阶口径**：εeff/Z0 由分层串联等效 + 经典双半腔电容分解给出，
  不含色散（频变表面阻抗/高阶模），适用 ka≪1 级横截面（本仓名义档
  D=2.032mm@2.5GHz ≈ λ0/59）；
- **文献频变闭式不可达如实账**：round15 明示 IET 屏蔽悬置式"无可频变闭
  式"——本模块不自造频变系数（#118：未回原文逐位核对的系数不入码），
  恒等式与精确极限是唯一裁判（tests/unit/test_ta_wave_b_templates）；
- 损耗面：tan_d 走基板材料消费（渲染/引擎面），内核只交付无损 εeff/Z0。

模型（每式出处）
----------------
几何记号（悬置微带 SUSPENDED 口径）：地面 z=0（域 PEC 底界）→ 空气隙
g（z∈[0,g]）→ 基板 h_s/εr（z∈[g,g+h_s]）→ 零厚条带 z=g+h_s（基板上表面）
→ 空气 h_t → 屏蔽顶板（z=D=g+h_s+h_t）。倒置微带 INVERTED 口径：条带在
基板**下**表面（z=g），基板上覆至 g+h_s，再上空气 h_t 到顶板。

- **分层串联等效**（下/上半腔各自）：εeq = Σd_i / Σ(d_i/ε_i)——
  平行板串联层精确（w→∞ 极限下全场竖直，构造恒等式）。
- **经典双半腔电容分解**（offset stripline 准静态标准构造，Howe
  "Stripline Circuit Design" / Wadell《Transmission Line Design Handbook》
  §3.3 口径；**二手转写如实登记**：原文页码未回 PDF 逐位核对，citation-rot
  纪律下以恒等式/极限为裁判）：
  零厚条带把腔分为下/上两半腔（高 h1、ε1eq；h2、ε2eq），每半腔按
  "对称带状线之半"计电容——对称线（2h 腔）沿条带面是磁壁对称面，拆成
  两个 h 腔半问题精确；非对称（h1≠h2）时取两半和 = 一阶准静态近似：

      ca_i(w) = 1/(c · Z0_cohn(w, 2h_i, 1))       （半腔空气电容基准）
      C_i^med = ½·ε_i·ca_i，  C_i^air = ½·ca_i    （ε·ca 标定，见下）
      C(w)    = Σ C_i^med                         （分层 ε_i=ε_ieq）
      C_air(w) = Σ C_i^air                        （全空气）
      εeff    = C(w) / C_air(w)
      Z0      = √εeff / (c · C(w))                （Z0=1/(C·v_p)，v_p=c/√εeff）

  ε·ca 标定的必要性：C=1/(Z0·v_p) 中 Z0=Z0_air/√ε 与 v_p=c/√ε 的两个 √ε
  相乘消去 → C ∝ ε·ca——对称退化 εeff=ε 逐位的必要条件。
  已知一阶误差面（如实）：w→∞ 极限本模型给 (ε1eq·h1+ε2·h2)/(h1+h2)
  （算术混合），真平行板分层线按磁力线路径给 (ε1eq/h1+ε2/h2)/(1/h1+1/h2)
  （逐径混合）——h1=h2 时二者恒等（测试钉此点），h1≠h2 差 O(|h1−h2|/D)
  归入一阶口径。

  其中 Z0_cohn = core/calculators._stripline_z0（**仓内单源**：零厚对称
  带状线共形映射精确解 Cohn/Wadell 30π·K'(k)/K(k)/√εr，k=tanh(πw/2b)；
  本模块零新几何闭式，#118 单源纪律）。

精确极限（判据全在测试）
------------------------
1. 对称退化：h1=h2=h 且 ε1eq=ε2=εr → Z0 ≡ _stripline_z0(w, 2h, εr)、
   εeff=εr **逐位**（代数恒等式，复用单源）；
2. εr=1 全空气 → εeff=1 精确；
3. w→∞ 且 h1=h2 → εeff → 逐径/算术混合共有的串联层精确值（两理想化
   恒等点，见"已知一阶误差面"）；
4. 单调性：εr↑ → εeff↑；g↑（空气份额↑）→ εeff↓。

设计链：isl_design_params(50Ω, ...) brentq 反解 w（回代自洽 |ΔZ0|≤0.01Ω，
名义值全链内核精算 #1c，无手抄毫米数）。

单位口径 mm/Ω/GHz 入参；e^{−jωt}；core 纯函数零 IO、不注册 calculators 键
（amc_mushroom 同款本席纪律）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.dielectric_extract import C0

__all__ = [
    "inverted_ms_qs",
    "isl_design_params",
    "isl_layer_stack_eps_eq",
    "isl_two_half_c",
    "suspended_ms_qs",
]


def _positive(value: float, label: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{label} 必须为正有限，得到 {value!r}")
    return v


def isl_layer_stack_eps_eq(layers_mm_er: tuple[tuple[float, float], ...]) -> float:
    """分层串联等效介电常数 εeq = Σd / Σ(d/ε)（平行板串联层精确）。"""
    if not layers_mm_er:
        raise ValueError("层表不得为空")
    total = 0.0
    electric = 0.0
    for d, er in layers_mm_er:
        d = _positive(d, "层厚")
        er = _positive(er, "层 εr")
        total += d
        electric += d / er
    return total / electric


def isl_two_half_c(w_m: float, h1_m: float, eps1: float,
                   h2_m: float, eps2: float) -> tuple[float, float]:
    """双半腔电容分解（F/m）：返回 (C_介质, C_全空气)。

    每半腔（对称 2h_i 腔沿条带面磁壁拆半精确）：
        C_half,i^med = ½·ε_i·ca_i，  C_half,i^air = ½·ca_i，
        ca_i = 1/(c·Z0_cohn(w, 2h_i, 1))
    （电容标定 ε·ca 而非 √ε·ca：C=1/(Z0·v_p)，Z0=Z0_air/√ε 且 v_p=c/√ε
    两个 √ε 相消——对称退化 εeff=ε、Z0=Z0_cohn(w,2h,εr) 逐位的必要条件）。
    Z0_cohn 走 core/calculators._stripline_z0 单源。
    """
    from rfauto.core.calculators import _stripline_z0

    w = _positive(w_m, "w")
    h1 = _positive(h1_m, "h1")
    h2 = _positive(h2_m, "h2")
    eps1 = _positive(eps1, "eps1")
    eps2 = _positive(eps2, "eps2")
    z0a = _stripline_z0(w * 1e3, 2.0 * h1 * 1e3, 1.0)
    z0b = _stripline_z0(w * 1e3, 2.0 * h2 * 1e3, 1.0)
    if not (z0a > 0.0 and z0b > 0.0 and math.isfinite(z0a) and math.isfinite(z0b)):
        raise ValueError(
            f"双半腔 Z0 下溢（w={w * 1e3:.4g}mm 过宽，Cohn 闭式 K(k) 溢出）——"
            "收窄 w 或按平行板极限手核")
    ca1 = 1.0 / (C0 * z0a)
    ca2 = 1.0 / (C0 * z0b)
    c_med = 0.5 * (eps1 * ca1 + eps2 * ca2)
    c_air = 0.5 * (ca1 + ca2)
    return c_med, c_air


def _qs_from_halves(w_mm: float, h1_mm: float, eps1: float,
                    h2_mm: float, eps2: float) -> dict[str, float]:
    w_m = _positive(w_mm, "w_mm") * 1e-3
    c_med, c_air = isl_two_half_c(w_m, h1_mm * 1e-3, eps1,
                                  h2_mm * 1e-3, eps2)
    eps_eff = c_med / c_air
    z0 = math.sqrt(eps_eff) / (C0 * c_med)
    return {"eps_eff": eps_eff, "z0_ohm": z0,
            "h1_mm": float(h1_mm), "h2_mm": float(h2_mm),
            "eps1_eq": eps1, "eps2_eq": eps2,
            "d_total_mm": float(h1_mm + h2_mm)}


def suspended_ms_qs(w_mm: float, g_air_mm: float, h_sub_mm: float,
                    er: float, h_top_mm: float) -> dict[str, float]:
    """悬置微带准静态 (εeff, Z0)：地面→空气隙 g→基板 h_s/εr→条带（基板
    上表面）→空气 h_t→屏蔽顶板。

    下半腔 ε1eq = (g+h_s)/(g+h_s/εr)（串联层精确）；上半腔全空气。
    """
    g = _positive(g_air_mm, "g_air_mm")
    hs = _positive(h_sub_mm, "h_sub_mm")
    ht = _positive(h_top_mm, "h_top_mm")
    er = _positive(er, "er")
    if er < 1.0:
        raise ValueError(f"εr≥1 定义域，得到 {er!r}")
    eps1 = isl_layer_stack_eps_eq(((g, 1.0), (hs, er)))
    return _qs_from_halves(w_mm, g + hs, eps1, ht, 1.0)


def inverted_ms_qs(w_mm: float, g_air_mm: float, h_sub_mm: float,
                   er: float, h_top_mm: float) -> dict[str, float]:
    """倒置微带准静态 (εeff, Z0)：地面→空气隙 g→条带（z=g）→基板
    h_s/εr 上覆→空气 h_t→屏蔽顶板（金属/介质 z 序与悬置口径对调）。

    下半腔全空气；上半腔 ε2eq = (h_s+h_t)/(h_s/εr+h_t)（串联层精确）。
    与 core/inverted_ms（FD 裁判反演设计链）互为交叉参考——本闭式为
    准静态近似，FD 裁判面数值以此对账（偏差如实，不互替）。
    """
    g = _positive(g_air_mm, "g_air_mm")
    hs = _positive(h_sub_mm, "h_sub_mm")
    ht = _positive(h_top_mm, "h_top_mm")
    er = _positive(er, "er")
    if er < 1.0:
        raise ValueError(f"εr≥1 定义域，得到 {er!r}")
    eps2 = isl_layer_stack_eps_eq(((hs, er), (ht, 1.0)))
    return _qs_from_halves(w_mm, g, 1.0, hs + ht, eps2)


def isl_design_params(z0_ohm: float = 50.0,
                      g_air_mm: float = 0.508,
                      h_sub_mm: float = 0.508,
                      h_top_mm: float = 1.016,
                      er: float = 3.66,
                      flavor: str = "suspended") -> dict[str, Any]:
    """设计链：目标 Z0 → 条带宽度 w（brentq 反解 + 回代自洽守卫）。

    flavor="suspended"（悬置微带，ISL 模板名义档）|"inverted"（倒置微带）。
    """
    z0_target = _positive(z0_ohm, "z0_ohm")
    qs = suspended_ms_qs if flavor == "suspended" else inverted_ms_qs
    if flavor not in ("suspended", "inverted"):
        raise ValueError(f"flavor 须 suspended|inverted，得到 {flavor!r}")

    def z_of(w_mm: float) -> float:
        return float(qs(w_mm, g_air_mm, h_sub_mm, er, h_top_mm)["z0_ohm"])

    from scipy.optimize import brentq

    d_total = float(g_air_mm + h_sub_mm + h_top_mm)
    w_lo, w_hi = 0.01 * d_total, 10.0 * d_total
    z_lo, z_hi = z_of(w_lo), z_of(w_hi)
    if z_lo <= 0.0 or z_hi <= 0.0:
        raise ValueError("双半腔 Z0 扫描端点退化（Cohn 闭式下溢），收窄 w 域")
    if not (z_lo > z0_target > z_hi):
        raise ValueError(
            f"目标 {z0_target:.4g}Ω 超出可达范围 [{z_hi:.2f}, {z_lo:.2f}]Ω"
            f"（g={g_air_mm} h_s={h_sub_mm} h_t={h_top_mm} εr={er} {flavor}）")
    w_mm = float(brentq(lambda w: z_of(w) - z0_target, w_lo, w_hi, xtol=1e-10))
    out = qs(w_mm, g_air_mm, h_sub_mm, er, h_top_mm)
    z_back = float(out["z0_ohm"])
    if abs(z_back - z0_target) > 0.01:
        raise ValueError(
            f"回代自洽失败：w={w_mm:.6f}mm → {z_back:.4f}Ω ≠ {z0_target:.4f}Ω")
    return {"w_mm": round(w_mm, 4), "z0_ohm": round(z_back, 4),
            "eps_eff": round(float(out["eps_eff"]), 4),
            "g_air_mm": float(g_air_mm), "h_sub_mm": float(h_sub_mm),
            "h_top_mm": float(h_top_mm), "er": float(er),
            "flavor": flavor}
