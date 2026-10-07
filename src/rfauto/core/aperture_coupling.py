"""EM-2 孔缝泄漏 SE 族（Bethe 小孔极化率/传输截面 + Robinson 电路类比全链
+ 矩形缝波导截止穿透）（2026-10-02，round17 EM-2）。

规格：研究扩充 round17 §四 EM-2——Bethe 小孔
极化系数（αe=2a³/3、αm=4a³/3）+孔阵列+矩形缝波导截止穿透项+Robinson
电路类比全链。验收=Robinson 1998 图锚+孔径-波长幂律 −60dB/dec 恒等。

出处等级（如实标注）：
- **Robinson 1998 全链式(1)-(12)**：M.P. Robinson, T.M. Benson,
  C. Christopoulos, J.F. Dawson, M.D. Ganley, A.C. Marvin, S.J. Porter,
  D.W.P. Thomas, "Analytical formulation for the shielding effectiveness
  of enclosures with apertures", IEEE Trans. EMC 40(3):240-248, Aug. 1998。
  本机留档 runs/em2/robinson1998_postprint.pdf（White Rose 免费后印本，
  eprints.whiterose.ac.uk/id/eprint/90051），式(1)-(12) 于 2026-10-02
  PDF 渲染放大逐式抄录（原文式回收，非转引）。图锚=Fig.6/7（300×120×300
  mm 黄铜腔 t=1.5mm + 100×5mm 缝，p=150mm：谐振 ~700MHz 负屏蔽、
  SE_E(200MHz)≈45dB、SE 随观察距离 p 增大、TE10 截止 500MHz——均由
  单测钉住，限值带按图读数放宽）。
- **Bethe 极化率**：圆孔 αe=2r³/3、αmx=αmy=4r³/3（规格原文式；Bethe
  1944 Phys. Rev. 66:163）。方孔/矩形闭式经 York 博士论文 Table 4.1
  （etheses.whiterose.ac.uk/id/eprint/24535，其引用 Bethe[39]/Junqua
  [42]）回收：矩形 αe=A^{3/2}/(3√π·E(e))·(w/l)、
  αmx=A^{3/2}e²(l/w)^{3/2}/(3√π[K(e)−E(e)])、
  αmy=A^{3/2}e²(w/l)^{1/2}/(3√π[K−E])（A=lw，e=√(1−(w/l)²)）。
  原表 αmy 分母印作 [E(e)−K(e)]：按 K≥E（0≤e≤1）判为排版负号，量级取
  [K−E]（σ_t 为平方和不受符号影响；方孔极限与窄缝渐近均复核自洽）。
- **传输截面** σ_t=(2k⁴/9π)(αe²+αmx²+αmy²)：同论文式(4.28)（Junqua
  口径：随机极化等概率+半空间积分两 ½ 因子已折入）。
- **孔径-波长幂律 −60dB/dec 恒等**：圆孔 α∝a³ ⇒ σ_t∝k⁴a⁶ ⇒
  σ_t/λ²=(2(2π)⁴/9π)·(a/λ)⁶——对 (a/λ) 严格 6 次幂（SE 视角
  −60dB/dec，任意十年期逐位恒等，无小量近似；规格验收恒等式由本律
  承担，test 钉 1e-9）。同域 Robinson 腔链的孔径斜率实测 ≈−47dB/dec
  （孔阻抗 Z_ap∝(l/a)·Z0s(w_e/b)·k0·l，Z0s 随 w_e/b 对数缓增），与
  Bethe 截面律非同一定义（腔内场比 vs 随机入射截面），两口径并陈。
- **矩形缝截止穿透**：f_c=c/(2L)（半波缝谐振/截止，规格原文语义）；
  低于截止衰减 SE=20lg(e)·t·√((π/L)²−k0²)（矩形波导消失模衰减常数，
  f→0 极限=27.289·t/L dB，即"波导低于截止"经验律的闭式来源）。
  t→0 精确退化为薄屏（Bethe 口径，SE→0）。

模型域限制（如实声明）：Robinson 链假设单 TE10 模+电小孔近似
（tan(k0·l/2) 线性域最佳）；缝长接近 λ/2 时 Z_ap 的 tan 发散（缝半波
谐振），该邻域模型失效（非有限值显式拒绝）；孔阵列按式(12)串联组合
（×n），原文自注忽略孔间互导纳、孔距过近时不适用；壁损耗 ζ 为均匀
分布损耗近似（式(9)(10) 的 (1+ζ−jζ) 乘子，印刷口径 UNVERIFIED，仅
定性验证使谐振 dip 变浅）。

纯函数模块（无注册表）：round17 EM-2 未要求 calculator 注册键（与
EM-1 同口径），消费面需要时再走基类+注册表模式补注册。
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from typing import Any

from scipy.special import ellipe, ellipk

from rfauto.core.metasurface_lut import C0_M_S, ETA0_OHM

__all__ = [
    "APERTURE_CIRCULAR",
    "APERTURE_SLOT",
    "SUPPORTED_APERTURE_TYPES",
    "SUPPORTED_Z0S_MODES",
    "aperture_effective_width_m",
    "aperture_impedance_ohm",
    "bethe_polarizability_circle",
    "bethe_polarizability_rectangle",
    "bethe_polarizability_square",
    "bethe_transmission_cross_section_m2",
    "coplanar_strip_impedance_approx_ohm",
    "coplanar_strip_impedance_exact_ohm",
    "robinson_enclosure_se",
    "slot_cutoff_frequency_hz",
    "slot_thickness_se_db",
]

#: 孔类型键（Robinson 式(11)：圆孔映射为等面积正方形 l=w=√π/2·d_h）
APERTURE_SLOT = "slot"
APERTURE_CIRCULAR = "circular"
SUPPORTED_APERTURE_TYPES = (APERTURE_SLOT, APERTURE_CIRCULAR)

#: Z0s 计算口径：auto=按论文（w_e<b/√2 用 Gupta 近似式(2)，否则椭圆积分
#: 精确式）；exact=全椭圆积分；approx=强制近似式（出域显式拒绝）
SUPPORTED_Z0S_MODES = ("auto", "exact", "approx")

_D20_LN10 = 20.0 / math.log(10.0)  # 8.685889638…（Np→dB）
_CPS_K_LIMIT = 1.0 / math.sqrt(2.0)  # 论文式(2)适用域 w_e/b < 1/√2

_POLARIZABILITY_KEYS = ("alpha_e_m3", "alpha_mx_m3", "alpha_my_m3")


def _positive_finite(value: float, name: str) -> float:
    """标量收敛：>0 且有限（NaN/Inf 显式拒绝）。"""
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须 >0 且有限，got {value!r}")
    return v


def _nonnegative_finite(value: float, name: str) -> float:
    """标量收敛：≥0 且有限（NaN/Inf 显式拒绝）。"""
    v = float(value)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须 ≥0 且有限，got {value!r}")
    return v


# ─── Bethe 极化率（静态、零厚度无限大屏，体积量纲 m³）──────────────────────


def bethe_polarizability_circle(radius_m: float) -> dict[str, float]:
    """圆孔 Bethe 极化率（规格原文式：αe=2a³/3、αm=4a³/3，Bethe 1944）。

    Returns:
        dict：{alpha_e_m3, alpha_mx_m3, alpha_my_m3}（mx 沿任意面内轴，
        圆对称 mx≡my）。
    """
    a = _positive_finite(radius_m, "radius_m")
    a3 = a * a * a
    return {
        "alpha_e_m3": 2.0 * a3 / 3.0,
        "alpha_mx_m3": 4.0 * a3 / 3.0,
        "alpha_my_m3": 4.0 * a3 / 3.0,
    }


def bethe_polarizability_square(side_m: float) -> dict[str, float]:
    """方孔极化率（Table 4.1：αe=2l³/(3π^{3/2})、αm=4l³/(3π^{3/2})）。

    与圆孔同面积精确相等（π r²=l² ⇒ 两式逐项恒等，跨形互证锚）。
    """
    side = _positive_finite(side_m, "side_m")
    side3 = side * side * side
    denom = 3.0 * math.pi ** 1.5
    return {
        "alpha_e_m3": 2.0 * side3 / denom,
        "alpha_mx_m3": 4.0 * side3 / denom,
        "alpha_my_m3": 4.0 * side3 / denom,
    }


def bethe_polarizability_rectangle(
    length_m: float, width_m: float
) -> dict[str, float]:
    """矩形孔极化率（Table 4.1 椭圆积分闭式；0<w≤l，w=l 走方孔闭式）。

    αe=A^{3/2}/(3√π·E(e))·(w/l)；
    αmx=A^{3/2}·e²·(l/w)^{3/2}/(3√π·[K(e)−E(e)])；
    αmy=A^{3/2}·e²·(w/l)^{1/2}/(3√π·[K(e)−E(e)])，
    A=lw，e=√(1−(w/l)²)。原表 αmy 分母印 [E−K]，按 K≥E 判为排版
    负号取量级 [K−E]（见模块 docstring 出处节）。窄缝极限
    αmx≈l³/(3√π·K(e))（沿缝长磁耦合，裂缝不闭合）、αmy∝lw²、
    αe∝l^{1/2}w^{5/2} 均快速趋零。
    """
    length = _positive_finite(length_m, "length_m")
    width = _positive_finite(width_m, "width_m")
    if width > length:
        raise ValueError(
            f"width_m 必须 ≤ length_m（长轴沿缝长约定），got l={length}, "
            f"w={width}")
    if width == length:
        return bethe_polarizability_square(length)
    area = length * width
    ecc = math.sqrt(1.0 - (width / length) ** 2)
    k_e = ellipk(ecc * ecc)  # K(e)，scipy 参数为模平方 m=e²
    e_e = ellipe(ecc * ecc)
    a15 = area ** 1.5
    common = 3.0 * math.sqrt(math.pi)
    ke_minus = k_e - e_e  # >0 恒成立（0<e<1）
    return {
        "alpha_e_m3": a15 / (common * e_e) * (width / length),
        "alpha_mx_m3": a15 * ecc * ecc * (length / width) ** 1.5
        / (common * ke_minus),
        "alpha_my_m3": a15 * ecc * ecc * (width / length) ** 0.5
        / (common * ke_minus),
    }


def bethe_transmission_cross_section_m2(
    frequency_hz: float, polarizability: dict[str, float]
) -> float:
    """Bethe/Junqua 平均传输截面 σ_t=(2k⁴/9π)(αe²+αmx²+αmy²)（式 4.28）。

    Args:
        frequency_hz: 频率 Hz（>0）。
        polarizability: 极化率 dict（bethe_polarizability_* 的返回值，
            三键 alpha_e_m3/alpha_mx_m3/alpha_my_m3 必读；体积量纲 m³）。

    Returns:
        σ_t（m²）。幂律恒等：圆孔 σ_t/λ² ∝ (a/λ)⁶（SE 视角 −60dB/dec，
        严格恒等，规格验收锚）。
    """
    f = _positive_finite(frequency_hz, "frequency_hz")
    if not isinstance(polarizability, dict):
        raise ValueError("polarizability 须为 bethe_polarizability_* 的 dict")
    missing = [k for k in _POLARIZABILITY_KEYS if k not in polarizability]
    if missing:
        raise ValueError(
            f"polarizability 缺键 {missing}（须含 {list(_POLARIZABILITY_KEYS)}）")
    a_e = float(polarizability["alpha_e_m3"])
    a_mx = float(polarizability["alpha_mx_m3"])
    a_my = float(polarizability["alpha_my_m3"])
    for key, val in zip(_POLARIZABILITY_KEYS, (a_e, a_mx, a_my),
                        strict=True):
        if not math.isfinite(val):
            raise ValueError(f"polarizability[{key!r}] 必须有限，got {val!r}")
    k0 = 2.0 * math.pi * f / C0_M_S
    return (2.0 * k0 ** 4 / (9.0 * math.pi)) * (a_e * a_e + a_mx * a_mx
                                                + a_my * a_my)


# ─── Robinson 1998 孔缝阻抗链（式(1)-(3)+(12)）────────────────────────────


def aperture_effective_width_m(width_m: float, thickness_m: float) -> float:
    """厚壁修正有效缝宽 w_e=w−(5t/4π)(1+ln(4πw/t))（Robinson 式(1)）。

    t=0 精确返回 w（薄屏极限，物理恒等）；w_e≤0（壁厚远超缝宽，缝
    等效闭合）显式拒绝——Gupta 修正在该域无定义。
    """
    w = _positive_finite(width_m, "width_m")
    t = _nonnegative_finite(thickness_m, "thickness_m")
    if t == 0.0:
        return w
    w_e = w - (5.0 * t / (4.0 * math.pi)) * (
        1.0 + math.log(4.0 * math.pi * w / t))
    if w_e <= 0.0:
        raise ValueError(
            f"厚壁修正出域：w_e={w_e:.6g} ≤0（w={w} m, t={t} m，"
            "壁厚远超缝宽时缝等效闭合，式(1)无定义）")
    return w_e


def coplanar_strip_impedance_exact_ohm(width_over_height: float) -> float:
    """CPS 特性阻抗精确式 Z0s=120π·K(k)/K'(k)（Gupta；k=w_e/b∈(0,1)）。

    scipy 参数约定：K(k)=ellipk(k²)、K'(k)=K(k')=ellipk(1−k²)。
    Fig.2 读数锚：k=0.01→≈98.8Ω、k=0.7→≈373Ω（单调增，k→0⁺→0
    短路、k→1⁻→∞ 开路）。
    """
    k = _positive_finite(width_over_height, "width_over_height")
    if k >= 1.0:
        raise ValueError(
            f"k=w_e/b 必须 ∈(0,1)，got {width_over_height!r}")
    return 120.0 * math.pi * float(ellipk(k * k)) / float(ellipk(1.0 - k * k))


def coplanar_strip_impedance_approx_ohm(width_over_height: float) -> float:
    """CPS 阻抗 Gupta 近似式（Robinson 式(2)，适用域 k=w_e/b<1/√2）。

    Z0s=120π²·[ln(2(1+√(1−k²))/(1−√(1−k²)))]⁻¹；论文口径：多数实用
    孔缝满足 k<1/√2，此时可替代精确式（k≤0.01 与精确式差 ≤7%）。
    """
    k = _positive_finite(width_over_height, "width_over_height")
    if k >= _CPS_K_LIMIT:
        raise ValueError(
            f"近似式(2)适用域 k=w_e/b < 1/√2≈{1.0 / math.sqrt(2.0):.4f}，"
            f"got {width_over_height!r}（此域用 exact 口径）")
    s = math.sqrt(1.0 - k * k)
    return 120.0 * math.pi ** 2 / math.log(2.0 * (1.0 + s) / (1.0 - s))


def _z0s_ohm(w_e: float, b: float, z0s_mode: str) -> float:
    """按论文口径选 Z0s：auto=（k<1/√2 用近似式(2)否则精确式）。"""
    k = w_e / b
    if z0s_mode == "auto":
        if k < _CPS_K_LIMIT:
            return coplanar_strip_impedance_approx_ohm(k)
        return coplanar_strip_impedance_exact_ohm(k)
    if z0s_mode == "exact":
        return coplanar_strip_impedance_exact_ohm(k)
    return coplanar_strip_impedance_approx_ohm(k)


def aperture_impedance_ohm(
    frequency_hz: float,
    aperture_length_m: float,
    effective_width_m: float,
    enclosure_width_m: float,
    enclosure_height_m: float,
    n_apertures: int = 1,
    z0s_mode: str = "auto",
) -> complex:
    """孔缝等效阻抗（Robinson 式(3)+(12)，复数）。

    Z_ap = n·(1/2)·(l/a)·j·Z0s·tan(k0·l/2)：两侧短路 CPS 经 l/2 变换
    到缝中心，因子 l/a 计孔-腔耦合（式(3)），n 孔按式(12)串联组合
    （×n；原文自注忽略孔间互导纳，孔距过近不适用）。
    l_a=λ/2 邻域 tan 发散（缝半波谐振），非有限值显式拒绝。
    """
    f = _positive_finite(frequency_hz, "frequency_hz")
    la = _positive_finite(aperture_length_m, "aperture_length_m")
    w_e = _positive_finite(effective_width_m, "effective_width_m")
    a = _positive_finite(enclosure_width_m, "enclosure_width_m")
    b = _positive_finite(enclosure_height_m, "enclosure_height_m")
    n = int(n_apertures)
    if n < 1 or n_apertures != n:
        raise ValueError(f"n_apertures 必须 ≥1 整数，got {n_apertures!r}")
    if str(z0s_mode) not in SUPPORTED_Z0S_MODES:
        raise ValueError(
            f"未知 z0s_mode {z0s_mode!r}（可用: {list(SUPPORTED_Z0S_MODES)}）")
    if la > a:
        raise ValueError(
            f"aperture_length_m 必须 ≤ enclosure_width_m（缝长沿 a 面放置），"
            f"got l={la} > a={a}")
    if w_e >= b:
        raise ValueError(
            f"effective_width_m 必须 < enclosure_height_m（CPS 模数 k=w_e/b<1），"
            f"got w_e={w_e} ≥ b={b}")
    z0s = _z0s_ohm(w_e, b, str(z0s_mode))
    k0 = 2.0 * math.pi * f / C0_M_S
    z_ap = n * 0.5 * (la / a) * 1j * z0s * cmath.tan(k0 * la / 2.0)
    if not cmath.isfinite(z_ap):
        raise ValueError(
            "孔缝阻抗非有限（l_a≈λ/2 缝半波谐振邻域，Robinson CPS 模型"
            f"失效）：f={f}, l_a={la}")
    return z_ap


# ─── Robinson 1998 全链（式(4)-(10)，Fig.1 等效电路）──────────────────────


def _robinson_point(
    f_hz: float,
    a: float,
    b: float,
    d: float,
    p: float,
    z_ap: complex,
    loss_zeta: float,
) -> dict[str, float]:
    """单频点全链（式(4)-(8)），返回 S_E/S_M 与中间量（复数拆实虚）。"""
    lam = C0_M_S / f_hz
    k0 = 2.0 * math.pi * f_hz / C0_M_S
    # Thevenin（原文 II-B：v1=v0·Z_ap/(Z0+Z_ap)，Z1=Z0·Z_ap/(Z0+Z_ap)）
    v1 = z_ap / (ETA0_OHM + z_ap)
    z1 = ETA0_OHM * z_ap / (ETA0_OHM + z_ap)
    # TE10 波导阻抗/传播常数（截止 c/2a 以下取虚，原文 II-B）
    guide = cmath.sqrt(1.0 - (lam / (2.0 * a)) ** 2)
    z_g = ETA0_OHM / guide
    k_g = k0 * guide
    if loss_zeta > 0.0:
        factor = 1.0 + loss_zeta - 1j * loss_zeta  # 式(9)(10) 印刷口径
        z_g = z_g * factor
        k_g = k_g * factor
    # 变换到观察点 P（式(4)(5)(6)）
    v2 = v1 / (cmath.cos(k_g * p) + 1j * (z1 / z_g) * cmath.sin(k_g * p))
    z2 = (z1 + 1j * z_g * cmath.tan(k_g * p)) / (
        1.0 + 1j * (z1 / z_g) * cmath.tan(k_g * p))
    z3 = 1j * z_g * cmath.tan(k_g * (d - p))
    v_p = v2 * z3 / (z2 + z3)
    i_p = v2 / (z2 + z3)
    # 式(7)(8)：自由空间参考 v_p'=v0/2、i_p'=v0/(2Z0)（v0 已约去）
    se_e = -20.0 * math.log10(abs(2.0 * v_p))
    se_m = -20.0 * math.log10(abs(2.0 * i_p * ETA0_OHM))
    if not (math.isfinite(se_e) and math.isfinite(se_m)):
        raise ValueError(
            "SE 非有限（缝半波谐振 k0·l/2≈π/2 或波导半波驻点邻域，"
            f"Robinson 模型失效）：f={f_hz}")
    return {
        "se_electric_db": se_e,
        "se_magnetic_db": se_m,
        "z_ap_real_ohm": z_ap.real,
        "z_ap_imag_ohm": z_ap.imag,
        "z_g_real_ohm": z_g.real,
        "z_g_imag_ohm": z_g.imag,
        "k_g_real_rad_per_m": k_g.real,
        "k_g_imag_rad_per_m": k_g.imag,
        "wavelength_m": lam,
        "k0_rad_per_m": k0,
    }


def _resolve_aperture_dims(
    aperture_type: str,
    enclosure_height_m: float,
    aperture_length_m: float | None,
    aperture_width_m: float | None,
    hole_diameter_m: float | None,
) -> tuple[float, float]:
    """孔尺寸收敛：slot 用 l/w 直给，circular 按式(11) l=w=√π/2·d_h。"""
    if aperture_type == APERTURE_CIRCULAR:
        if hole_diameter_m is None:
            raise ValueError(
                "aperture_type='circular' 必读 hole_diameter_m（式(11) 映射）")
        d_h = _positive_finite(hole_diameter_m, "hole_diameter_m")
        side = math.sqrt(math.pi) / 2.0 * d_h
        return side, side
    if aperture_length_m is None or aperture_width_m is None:
        raise ValueError(
            "aperture_type='slot' 必读 aperture_length_m 与 aperture_width_m")
    if aperture_width_m > aperture_length_m:
        raise ValueError(
            f"aperture_width_m 必须 ≤ aperture_length_m（缝长沿 a 面、"
            f"缝宽沿 b 面，长边垂直 E 场为最恶劣口径），"
            f"got l={aperture_length_m}, w={aperture_width_m}")
    return (
        _positive_finite(aperture_length_m, "aperture_length_m"),
        _positive_finite(aperture_width_m, "aperture_width_m"),
    )


def robinson_enclosure_se(
    frequency_hz: float | None = None,
    f_axis_hz: Sequence[float] | None = None,
    *,
    enclosure_width_m: float,
    enclosure_height_m: float,
    enclosure_depth_m: float,
    wall_thickness_m: float,
    aperture_type: str = APERTURE_SLOT,
    aperture_length_m: float | None = None,
    aperture_width_m: float | None = None,
    hole_diameter_m: float | None = None,
    observation_distance_m: float,
    n_apertures: int = 1,
    loss_zeta: float = 0.0,
    z0s_mode: str = "auto",
) -> dict[str, Any]:
    """Robinson 1998 腔体孔缝 SE 全链（式(1)-(12)，JSON 可序列化 dict）。

    等效电路（原文 Fig.1）：平面波源 v0+Z0（Z0=η0）→ 孔缝 CPS 阻抗
    Z_ap（式(3)，n 孔按式(12)×n）→ 短路波导腔（TE10，Z_g/k_g，式
    (4)-(6) 变换到观察点 P）→ 式(7)(8) 给出电/磁屏蔽。

    Args:
        frequency_hz: 单点频率 Hz（与 f_axis_hz 二选一，同给显式拒绝）。
        f_axis_hz: 频率轴 Hz 列表（逐点 >0）。
        enclosure_width_m: 腔宽 a（>0，波导 a 边，TE10 截止 c/2a）。
        enclosure_height_m: 腔高 b（>0；CPS 总宽=b 的模数分母）。
        enclosure_depth_m: 腔深 d（>0，孔面到背板）。
        wall_thickness_m: 壁厚 t（≥0；t=0 薄屏极限 w_e=w）。
        aperture_type: "slot"（矩形缝，直给 l/w）或 "circular"
            （圆孔，式(11) 等面积方映射 l=w=√π/2·d_h）。
        aperture_length_m: 缝长 l（slot 必读，>0，≤a；沿 a 面）。
        aperture_width_m: 缝宽 w（slot 必读，>0，≤l；沿 b 面）。
        hole_diameter_m: 圆孔直径 d_h（circular 必读，>0）。
        observation_distance_m: 观察点距孔面距离 p（∈(0,d) 开区间）。
        n_apertures: 同面同形孔数 n（≥1 整数，式(12) 串联 ×n）。
        loss_zeta: 腔内均匀损耗因子 ζ（≥0，式(9)(10)；0=无损）。
        z0s_mode: Z0s 口径（auto/exact/approx，见 SUPPORTED_Z0S_MODES）。

    Returns:
        dict：{f_hz, aperture_type, aperture_length_m, aperture_width_m,
        aperture_effective_width_m, z0s_ohm, aperture_impedance_ohm
        （{real_ohm, imag_ohm, abs_ohm} 逐频）, se_electric_db,
        se_magnetic_db（逐频）, te10_cutoff_hz, enclosure_*_m,
        n_apertures, loss_zeta, z0s_mode, note}。

    Raises:
        ValueError: 全部域守卫显式拒绝（f≤0/尺寸≤0/p 出开区间/
            l>a/w≥b/w_e≤0 厚壁出域/n<1/ζ<0/孔类型或口径键未知/
            缝半波谐振邻域非有限值）。

    图锚（Robinson 1998 Fig.6/7，单测钉住）：a×b×d=300×120×300mm、
    t=1.5mm、缝 100×5mm、p=150mm → 谐振 dip ≈700MHz（负屏蔽）、
    SE_E(200MHz)≈45dB、SE 随 p 单调增、TE10 截止≈500MHz。
    """
    if aperture_type not in SUPPORTED_APERTURE_TYPES:
        raise ValueError(
            f"未知 aperture_type {aperture_type!r}"
            f"（可用: {list(SUPPORTED_APERTURE_TYPES)}）")
    if str(z0s_mode) not in SUPPORTED_Z0S_MODES:
        raise ValueError(
            f"未知 z0s_mode {z0s_mode!r}（可用: {list(SUPPORTED_Z0S_MODES)}）")
    if (frequency_hz is None) == (f_axis_hz is None):
        raise ValueError("frequency_hz 与 f_axis_hz 须二选一（同给/都缺显式拒绝）")
    a = _positive_finite(enclosure_width_m, "enclosure_width_m")
    b = _positive_finite(enclosure_height_m, "enclosure_height_m")
    d = _positive_finite(enclosure_depth_m, "enclosure_depth_m")
    t = _nonnegative_finite(wall_thickness_m, "wall_thickness_m")
    p = _positive_finite(observation_distance_m, "observation_distance_m")
    if p >= d:
        raise ValueError(
            f"observation_distance_m 必须 < enclosure_depth_m（观察点在腔内），"
            f"got p={p} ≥ d={d}")
    n = int(n_apertures)
    if n < 1 or n_apertures != n:
        raise ValueError(f"n_apertures 必须 ≥1 整数，got {n_apertures!r}")
    zeta = _nonnegative_finite(loss_zeta, "loss_zeta")
    if frequency_hz is not None:
        f_list = [_positive_finite(frequency_hz, "frequency_hz")]
    else:
        f_axis = list(f_axis_hz)  # type: ignore[arg-type]
        if not f_axis:
            raise ValueError("f_axis_hz 不能为空")
        f_list = [
            _positive_finite(v, f"f_axis_hz[{i}]")
            for i, v in enumerate(f_axis)
        ]
    la, w = _resolve_aperture_dims(
        str(aperture_type), b, aperture_length_m, aperture_width_m,
        hole_diameter_m)
    if la > a:
        raise ValueError(
            f"aperture_length_m 必须 ≤ enclosure_width_m（缝长沿 a 面放置），"
            f"got l={la} > a={a}")
    if w >= b:
        raise ValueError(
            f"孔宽必须 < enclosure_height_m（CPS 模数 k=w_e/b<1），"
            f"got w={w} ≥ b={b}")
    w_e = aperture_effective_width_m(w, t)

    points = []
    for f_hz in f_list:
        z_ap = aperture_impedance_ohm(
            f_hz, la, w_e, a, b, n_apertures=n, z0s_mode=str(z0s_mode))
        point = _robinson_point(f_hz, a, b, d, p, z_ap, zeta)
        point["f_hz"] = f_hz
        points.append(point)

    return {
        "f_hz": [round(float(v), 6) for v in f_list],
        "aperture_type": str(aperture_type),
        "aperture_length_m": round(float(la), 12),
        "aperture_width_m": round(float(w), 12),
        "aperture_effective_width_m": round(float(w_e), 15),
        "z0s_ohm": round(
            float(_z0s_ohm(w_e, b, str(z0s_mode))), 9),
        "aperture_impedance_ohm": [
            {
                "real_ohm": round(float(pt["z_ap_real_ohm"]), 9),
                "imag_ohm": round(float(pt["z_ap_imag_ohm"]), 9),
                "abs_ohm": round(float(abs(complex(
                    pt["z_ap_real_ohm"], pt["z_ap_imag_ohm"]))), 9),
            }
            for pt in points
        ],
        "se_electric_db": [round(float(pt["se_electric_db"]), 9)
                           for pt in points],
        "se_magnetic_db": [round(float(pt["se_magnetic_db"]), 9)
                           for pt in points],
        "te10_cutoff_hz": round(C0_M_S / (2.0 * a), 6),
        "wavelength_m": [round(float(pt["wavelength_m"]), 12)
                         for pt in points],
        "enclosure_width_m": round(float(a), 12),
        "enclosure_height_m": round(float(b), 12),
        "enclosure_depth_m": round(float(d), 12),
        "wall_thickness_m": round(float(t), 12),
        "observation_distance_m": round(float(p), 12),
        "n_apertures": n,
        "loss_zeta": round(float(zeta), 12),
        "z0s_mode": str(z0s_mode),
        "note": "EM-2 Robinson 1998 全链（式(1)-(12)，White Rose 后印本"
                "逐式回收，留档 runs/em2/robinson1998_postprint.pdf）；"
                "单 TE10 模+电小孔近似，缝半波谐振邻域失效；n 孔按式(12)"
                "串联（忽略互导纳）；ζ 损耗为式(9)(10) 印刷口径"
                "（UNVERIFIED）；图锚 Fig.6/7 由单测钉住",
    }


# ─── 矩形缝波导截止穿透（规格："矩形缝波导截止穿透项"）────────────────────


def slot_cutoff_frequency_hz(slot_length_m: float) -> float:
    """半波缝截止/谐振上限 f_c=c/(2L)（规格原文语义：缝谐振上限）。"""
    slot_len = _positive_finite(slot_length_m, "slot_length_m")
    return C0_M_S / (2.0 * slot_len)


def slot_thickness_se_db(
    frequency_hz: float, slot_length_m: float, wall_thickness_m: float
) -> float:
    """矩形缝低于截止穿透衰减 SE=20lg(e)·t·√((π/L)²−k0²)（dB，≥0）。

    矩形波导消失模衰减常数 α=√((π/L)²−k0²)（f<f_c=c/(2L) 严格域）；
    f→0 极限=27.289·t/L dB（"波导低于截止"经验律的闭式来源）；
    t→0 精确返回 0（薄屏退化 Bethe 口径）。f≥f_c 显式拒绝（高于截止
    缝透明，消失模衰减项不适用，孔缝泄漏由 Robinson 全链承担）。
    """
    f = _positive_finite(frequency_hz, "frequency_hz")
    slot_len = _positive_finite(slot_length_m, "slot_length_m")
    t = _nonnegative_finite(wall_thickness_m, "wall_thickness_m")
    fc = slot_cutoff_frequency_hz(slot_len)
    if f >= fc:
        raise ValueError(
            f"频率必须低于缝截止 f_c=c/(2L)={fc:.6g} Hz（高于截止缝透明，"
            f"消失模衰减项不适用），got f={f}")
    if t == 0.0:
        return 0.0
    alpha = math.sqrt(
        (math.pi / slot_len) ** 2 - (2.0 * math.pi * f / C0_M_S) ** 2)
    return _D20_LN10 * t * alpha
