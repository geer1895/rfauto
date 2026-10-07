"""T-match 匹配闭式（Balanis 折合偶极子等效：分析 + 短截线补偿设计）。

权威口径（铁律 1c：常数与公式逐条回原文核对，2026-09-30 实取原文 PDF
逐位抄录；禁凭记忆写系数——#df6⑬ NFC 三式教训）
---------------------------------------------------------------------------
主出处：C. A. Balanis, "Antenna Theory: Analysis and Design", 3rd ed.,
Wiley 2005, §9.7.3 "T-Match", pp.531-533, 式 (9-48)–(9-55)（本地实测
原文 PDF 第 531-533 页逐位核对；4th ed 对应 §9.8.4 同式系）：

- (9-48)  电流分配因子 α：
            α = acosh((v²−u²+1)/(2v)) / acosh((v²+u²−1)/(2uv))
            近似式（细线极限）α ≈ ln(v)/(ln(v)−ln(u))
          (9-48a) u = a/a'（主偶极子半径 a / T 棒半径 a'）
          (9-48b) v = s/a'（中心距 s / T 棒半径 a'）
          馈电在 T 棒中心（Balanis Fig.9.21(a)："The transmission line
          is connected to the smaller dipole at its center"）——α 即
          主棒电流/T 棒电流比，步升比 (1+α)²=(总辐射电流/馈入电流)²；
          细棒 T 棒（a'<a）→ α>1 → 步升 >4（ARRL gamma 实践同向）。
          注意：Milligan《Modern Antenna Design》2ed eq.(5-17)（引
          Hansen）同一 acosh 式但 u=a₂/a₁ 取倒（a₁=driven）——两书
          "driven"所指的馈电位置约定不同，本模块严格按 Balanis T-match
          馈棒口径实现，两口径等值面在测试中互相验证（薄线极限互为
          倒数）。
- (9-49)  两导线等效半径：ln(a_e) = (a'²·ln a' + a²·ln a +
          2a'a·ln s)/(a'+a)²（Table 9.3 同项式；量纲自消——系数和
          (a'+a)² 归一，单位制无关，单测钉住）
- (9-50)  传输线模（长 l'/2 短路二线段）：Zt = j·Z0·tan(k·l'/2)
- (9-50a) Z0 = 60·acosh((s²−a²−a'²)/(2aa')) ≈ 276·log10(s/√(a·a'))
- (9-51)  Zin = 2Zt·[(1+α)²Za] / (2Zt + (1+α)²Za)
- (9-52)  Yin = Ya/(1+α)² + 1/(2Zt)
- (9-53)  l'≈λ/2 时 Zt→∞ → Zin ≈ (1+α)²Za；等半径 α=1 → Zin=4Za
          （(9-54)，经典折合偶极子 4× 锚：半波 Za=73+j42.5 →
          292+j170 Ω——教科书普适值，本模块半波谐振锚）
- (9-55)  谐振化串联电容（两只对称串联，C_in=C/2）：C = 1/(πf·Xin)

设计闭式（本模块推导，双路径回收钉于单测）：给定步升后天线模
Rp+jXp=(1+α)²·Za 与短截线总电抗 jY（Y=2·Im(Zt)），并联式 (9-51)
展开：Re(Zin)=Y²Rp/(Rp²+(Xp+Y)²)、Im(Zin)=Y(Rp²+Xp²+Xp·Y)/(Rp²+
(Xp+Y)²)。命 Re(Zin)=R0 得 (Rp−R0)Y²−2R0Xp·Y−R0(Rp²+Xp²)=0，
正根 Y=R0[Xp+√(Xp²+(Rp−R0)(Rp²+Xp²)/R0)]/(Rp−R0)
（ Rp>R0 显式必需——并联电抗只能把实部从步升值往下拉，拉不到
步升值以上）；残量电抗由两只串联电容谐振化（(9-55)）。

域守卫：v ≥ u+1（⟺ s ≥ a+a'，两棒不相交；恰等 = acosh 定义域边缘，
显式拒绝）、0 < l' ≤ l、l' < λ（tan 主支单调查询）、Q 类量正值。
"""

from __future__ import annotations

import math
from typing import Any

_C0 = 299792458.0  # m/s（真空光速）

# 半波细偶极子输入阻抗经典值（Ω）——Balanis 全书通篇锚值（折合偶极子
# 4× 步升锚 (9-54) 的 Za 基准）；仅作缺省参考输入，非本模块推导产物。
HALF_WAVE_ZA_RE_OHM = 73.0
HALF_WAVE_ZA_IM_OHM = 42.5


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def current_division_factor(main_radius_m: float, bar_radius_m: float,
                            spacing_m: float) -> dict[str, Any]:
    """Balanis (9-48)：α 与步升比 (1+α)²（u=a/a', v=s/a'）。

    域守卫 v ≥ u+1（⟺ s ≥ a+a'，两导线不相交；越域显式拒绝不外推）。
    同时回代细线近似式 ln(v)/(ln(v)−ln(u)) 供交叉核对（偏差随 s/a 增大
    收敛，单测钉 1% 量级一致而非逐位相等——两式本身即近似关系）。"""
    a = _pos(main_radius_m, "main_radius_m")
    ap = _pos(bar_radius_m, "bar_radius_m")
    s = _pos(spacing_m, "spacing_m")
    u = a / ap
    v = s / ap
    if v < u + 1.0:
        raise ValueError(
            f"v={v:.6g} < u+1={u + 1.0:.6g}（⟺ s < a+a'，两导线相交，"
            "acosh 定义域外——显式拒绝）")
    arg1 = (v * v - u * u + 1.0) / (2.0 * v)
    arg2 = (v * v + u * u - 1.0) / (2.0 * v * u)
    alpha = math.acosh(arg1) / math.acosh(arg2)
    alpha_approx = math.log(v) / (math.log(v) - math.log(u))
    return {"alpha": round(alpha, 12),
            "alpha_thin_wire_approx": round(alpha_approx, 12),
            "stepup_ratio": round((1.0 + alpha) ** 2, 12),
            "u": round(u, 12), "v": round(v, 12)}


def equivalent_radius(main_radius_m: float, bar_radius_m: float,
                      spacing_m: float) -> float:
    """Balanis (9-49)：两导线等效半径 a_e（ln 平均式）。

    ln(a_e) = (a'²·ln a' + a²·ln a + 2a'a·ln s)/(a'+a)²
    系数和=(a'+a)² 归一 → 量纲自消（m→mm 不变，单测钉）。"""
    a = _pos(main_radius_m, "main_radius_m")
    ap = _pos(bar_radius_m, "bar_radius_m")
    s = _pos(spacing_m, "spacing_m")
    if s < a + ap:
        raise ValueError("s < a+a'（两导线相交）——显式拒绝")
    ln_ae = (ap * ap * math.log(ap) + a * a * math.log(a)
             + 2.0 * a * ap * math.log(s)) / ((ap + a) ** 2)
    return math.exp(ln_ae)


def _tmatch_core(freq_hz: float, main_radius_m: float, bar_radius_m: float,
                 spacing_m: float, tbar_length_m: float, za_re_ohm: float,
                 za_im_ohm: float) -> dict[str, Any]:
    """(9-48)–(9-51) 公共链（不含 l'≤l 主棒长度约束——设计反解时主棒
    长度属调用方，分析入口 tmatch_impedance 在外层补该守卫）。"""
    f = _pos(freq_hz, "freq_hz")
    a = _pos(main_radius_m, "main_radius_m")
    ap = _pos(bar_radius_m, "bar_radius_m")
    s = _pos(spacing_m, "spacing_m")
    lp = _pos(tbar_length_m, "tbar_length_m")
    wavelength = _C0 / f
    if lp >= wavelength:
        raise ValueError("tbar_length_m 必须 < λ（tan 主支单值域）")
    fac = current_division_factor(a, ap, s)
    alpha = fac["alpha"]
    z0 = 60.0 * math.acosh((s * s - a * a - ap * ap) / (2.0 * a * ap))
    if z0 <= 0.0:
        raise ValueError("二线特性阻抗非正（几何域异常）——显式拒绝")
    k = 2.0 * math.pi / wavelength
    zt_re, zt_im = 0.0, z0 * math.tan(k * lp / 2.0)
    # Zin = 2Zt·Zp/(2Zt+Zp)，Zp=(1+α)²(Za_re+j·Za_im)——复数乘除直算
    zp_re = (1.0 + alpha) ** 2 * za_re_ohm
    zp_im = (1.0 + alpha) ** 2 * za_im_ohm
    num_re = (2.0 * zt_re * zp_re - 2.0 * zt_im * zp_im)
    num_im = (2.0 * zt_re * zp_im + 2.0 * zt_im * zp_re)
    den_re = 2.0 * zt_re + zp_re
    den_im = 2.0 * zt_im + zp_im
    den_abs = den_re * den_re + den_im * den_im
    zin_re = (num_re * den_re + num_im * den_im) / den_abs
    zin_im = (num_im * den_re - num_re * den_im) / den_abs
    return {"fac": fac, "z0_two_wire_ohm": z0, "zt_re_ohm": zt_re,
            "zt_im_ohm": zt_im, "zin_re_ohm": zin_re, "zin_im_ohm": zin_im,
            "lambda_m": wavelength, "tbar_length_m": lp}


def tmatch_impedance(freq_hz: float, main_radius_m: float,
                     bar_radius_m: float, spacing_m: float,
                     tbar_length_m: float, dipole_length_m: float,
                     za_re_ohm: float = HALF_WAVE_ZA_RE_OHM,
                     za_im_ohm: float = HALF_WAVE_ZA_IM_OHM) -> dict[str, Any]:
    """Balanis (9-48)–(9-51) 分析链：几何+天线阻抗 → Zin。

    Za=(za_re, za_im) 为无 T-match 连接时天线中心点自由空间输入阻抗
    （(9-51) 原文口径）；缺省给半波经典值 73+j42.5 Ω。l'≈λ/2 时
    Zin→(1+α)²Za（(9-53)，折合极限由调用方或测试核对）。"""
    _pos(freq_hz, "freq_hz")
    a = _pos(main_radius_m, "main_radius_m")
    ap = _pos(bar_radius_m, "bar_radius_m")
    s = _pos(spacing_m, "spacing_m")
    lp = _pos(tbar_length_m, "tbar_length_m")
    ld = _pos(dipole_length_m, "dipole_length_m")
    zre = _num(za_re_ohm, "za_re_ohm")
    zim = _num(za_im_ohm, "za_im_ohm")
    if lp > ld:
        raise ValueError("tbar_length_m 必须 ≤ dipole_length_m"
                         "（T 棒短于主偶极子：l'<l，T-match 定义）")
    core = _tmatch_core(freq_hz, a, ap, s, lp, zre, zim)
    fac = core["fac"]
    return {"alpha": fac["alpha"], "stepup_ratio": fac["stepup_ratio"],
            "u": fac["u"], "v": fac["v"],
            "equivalent_radius_m": round(equivalent_radius(a, ap, s), 12),
            "z0_two_wire_ohm": round(core["z0_two_wire_ohm"], 9),
            "zt_re_ohm": round(core["zt_re_ohm"], 9),
            "zt_im_ohm": round(core["zt_im_ohm"], 9),
            "zin_re_ohm": round(core["zin_re_ohm"], 9),
            "zin_im_ohm": round(core["zin_im_ohm"], 9),
            "lambda_m": round(core["lambda_m"], 12),
            "tbar_over_lambda": round(lp / core["lambda_m"], 12),
            "note": "Balanis 3ed §9.7.3 (9-48)-(9-51)；馈电在 T 棒中心，"
                    "Za=无 T-match 天线中心点阻抗"}


def tmatch_design(freq_hz: float, main_radius_m: float, bar_radius_m: float,
                  spacing_m: float, za_re_ohm: float = HALF_WAVE_ZA_RE_OHM,
                  za_im_ohm: float = 0.0,
                  target_rin_ohm: float = 50.0) -> dict[str, Any]:
    """设计闭式：几何+天线阻抗+目标 Rin → T 棒长度与谐振化电容。

    步升 Rp=(1+α)²za_re 必须 > target_rin_ohm（并联短截线把实部从
    步升值往下拉——拉不到步升值以上，越界显式 ValueError）。
    Y 正根 = R0[Xp+√(Xp²+(Rp−R0)(Rp²+Xp²)/R0)]/(Rp−R0)（模块
    docstring 设计闭式）；l'=2·atan((Y/2)/Z0)/k（tan 主支，0<l'<λ/2）；
    残量电抗按 (9-55) 两只对称串联电容谐振化 C=1/(πf·Xin)。
    返回含正向复核 rin_re_check（应=target，恰等回收 1e-9 级）。"""
    f = _pos(freq_hz, "freq_hz")
    a = _pos(main_radius_m, "main_radius_m")
    ap = _pos(bar_radius_m, "bar_radius_m")
    s = _pos(spacing_m, "spacing_m")
    zre = _num(za_re_ohm, "za_re_ohm")
    zim = _num(za_im_ohm, "za_im_ohm")
    r0 = _pos(target_rin_ohm, "target_rin_ohm")
    fac = current_division_factor(a, ap, s)
    alpha = fac["alpha"]
    stepup = (1.0 + alpha) ** 2
    rp = stepup * zre
    xp = stepup * zim
    if rp <= r0:
        raise ValueError(
            f"步升后实部 Rp={rp:.6g} Ω ≤ 目标 {r0:.6g} Ω——并联短截线"
            "只能降低实部（(9-51) 并联结构），请加粗 T 棒增大步升或降目标")
    disc = xp * xp + (rp - r0) * (rp * rp + xp * xp) / r0
    y_ohm = r0 * (xp + math.sqrt(disc)) / (rp - r0)
    if y_ohm <= 0.0:
        raise ValueError("正根 Y 非正（数值域异常）——显式拒绝")
    z0 = 60.0 * math.acosh((s * s - a * a - ap * ap) / (2.0 * a * ap))
    if z0 <= 0.0:
        raise ValueError("二线特性阻抗非正（几何域异常）——显式拒绝")
    wavelength = _C0 / f
    k = 2.0 * math.pi / wavelength
    tbar_len = 2.0 * math.atan((y_ohm / 2.0) / z0) / k
    # 正向复核：把解回代 (9-51)（公共链，主棒长度约束属调用方）
    core = _tmatch_core(f, a, ap, s, tbar_len, zre, zim)
    fac = core["fac"]
    zin_re = core["zin_re_ohm"]
    zin_im = core["zin_im_ohm"]
    if zin_im <= 0.0:
        raise ValueError("残量电抗非感性（几何组合异常）——显式拒绝")
    c_each = 1.0 / (math.pi * f * zin_im)
    return {"alpha": fac["alpha"], "stepup_ratio": round(stepup, 12),
            "z0_two_wire_ohm": round(z0, 9),
            "stub_total_reactance_ohm": round(y_ohm, 9),
            "tbar_length_m": round(tbar_len, 12),
            "tbar_over_lambda": round(tbar_len / wavelength, 12),
            "zin_re_ohm": round(zin_re, 9), "zin_im_ohm": round(zin_im, 9),
            "target_rin_ohm": round(r0, 9),
            "rin_re_check_ohm": round(zin_re, 9),
            "resonating_cap_each_f": round(c_each, 15),
            "lambda_m": round(wavelength, 12),
            "note": "设计闭式=docstring 二次式正根；正向复核回代 (9-51)；"
                    "两只串联电容 C（各 Xc=1/(2πfC)），Balanis (9-55)"}
