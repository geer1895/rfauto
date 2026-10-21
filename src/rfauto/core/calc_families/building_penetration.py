"""building_penetration 族（架构批 W14-S3 席，R3_domain_expansion 视角4
E4 穿媒质/穿墙空白——建筑媒质电性质+单层板穿透链）。

两键：building_material_properties（ITU-R P.2040-4 Table 3 材料电性质
闭式 ε′=a·f^b / σ=c·f^d + ε″/tanδ/介电极限衰减率换算面）/
wall_slab_transmission（单层墙板平面波穿透：Fresnel 界面系数 式(37a/b)
+ Airy 多次反射干涉 式(43a/b)/(44)，材料名或显式 ε′/σ 双模式）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``seawater|海水|穿墙|through.?wall|penetr|P.?2040`` src/tests/scripts 三面
零实命中（conductor_loss skin_depth=金属趋肤语境不撞、gpr=高斯过程回归
误中形态剔除；am_loss_budget/conductor_sigma_t 均为金属镀层语境）。
conductor_loss（金属）/sla_print（塑料 3D 打印）/itu_atmosphere（大气）/
itu_link（雨/气体/云雾）——本族只做**建筑媒质与墙板穿透**。

物理口径（#1c/#300 出处纪律；官方 PDF 逐式转写，证据
内部证据目录 原文在档）
--------------------------------------------------------
1. 材料电性质（P.2040-4 §3.1 式(57)/(58)+Table 3 逐行转写）：

       ε′ = a·f^b ，  σ = c·f^d    （f[GHz]，ε′ 无量纲，σ[S/m]）

   Table 3 摘 wall 系材料 1-100GHz 主档（b 全 0=ε′ 频率无关，原文
   "in almost all cases there is no evidence of a trend"）：

       concrete 5.24/0.0462/0.7822（1-100） brick 3.91/0.0238/0.16（1-40）
       plasterboard 2.73/0.0085/0.9395     wood 1.99/0.0047/1.0718（0.001-100）
       glass 6.31/0.0036/1.3394（0.1-100） chipboard 2.58/0.0217/0.78
       ceiling_board 1.48/0.0011/1.0750    plywood 2.71/0.33/0（1-40）

   换算面：ε″ = σ/(ωε₀)（式(11) 精确路径；官方实用式(59) ε″=17.98σ/f
   为同一式圆化常数——17.98 vs 精确 17.9752，rel +2.7e-4）；tanδ = ε″/ε′
   （式(13)）；介电极限衰减率 A_diel = 1636·σ/√ε′ [dB/m]（式(27a)，
   原文声明 tanδ<0.5 精度 ~3%——Table 3 全部介质材料声明满足）。

2. 单层板穿透（P.2040-4 §2.2.2.2，空气入射）：
   - 界面 Fresnel 场系数（式(37a)/(37b)，ε_rc=ε′−jσ/(ωε₀) 式(9b)/(10)）：

         R′_TE = (cosθ−√(ε_rc−sin²θ))/(cosθ+√(ε_rc−sin²θ))
         R′_TM = (ε_rc·cosθ−√(ε_rc−sin²θ))/(ε_rc·cosθ+√(ε_rc−sin²θ))

   - 相位厚 q = (2πd/λ)·√(ε_rc−sin²θ)（式(44)）
   - Airy 多次反射干涉（式(43a)/(43b)）：

         R = R′(1−e^{−j2q})/(1−R′²e^{−j2q}) ， T = (1−R′²)e^{−jq}/(1−R′²e^{−j2q})

   穿透损耗 = −20·log₁₀|T|（场系数口径）；功率面 |R|²+|T|²+吸收=1。

出处：ITU-R P.2040-4 (09/2025)《Effects of building materials and
structures on radio-wave propagation in the range of 1 MHz to 450 GHz》
官方 PDF 逐式转写（本模块式号按原文）； Fresnel/Airy 干涉式与任意电磁
教科书同构（Balanis ch.5 平面波斜入射同式）——零新引源。复反射干涉
窗（半波窗/Brewster）为式内恒等结构锚，见 tests/unit/
test_w14s3_core_domains.py 锚树。
"""

from __future__ import annotations

import cmath
import math

from .registry import register_calculator

#: 真空介电常数 [F/m]（itu_atmosphere/P.2040 §2.1.2.4 式(9b)-(11) 路径；
#: CODATA 2018 exact）
_EPS0_F_M = 8.8541878128e-12
#: 光速 [m/s]（SI 精确；hf_skywave/fmcw_radar/sar_geometry 同值口径）
_C0_M_S = 299792458.0

# ─── P.2040-4 Table 3 材料行（逐值转写； (a, b, c, d, f_lo_GHz, f_hi_GHz)）───
#: wall 系材料 1-100GHz 主档摘录（全表含 110-330/100-400 高带档，本键
#: 只收 wall 常用主档——高带档行值见官方 Table 3，按需再扩）
_MATERIAL_TABLE: dict[str, tuple[float, float, float, float, float, float]] = {
    "concrete": (5.24, 0.0, 0.0462, 0.7822, 1.0, 100.0),
    "brick": (3.91, 0.0, 0.0238, 0.16, 1.0, 40.0),
    "plasterboard": (2.73, 0.0, 0.0085, 0.9395, 1.0, 100.0),
    "wood": (1.99, 0.0, 0.0047, 1.0718, 0.001, 100.0),
    "glass": (6.31, 0.0, 0.0036, 1.3394, 0.1, 100.0),
    "chipboard": (2.58, 0.0, 0.0217, 0.78, 1.0, 100.0),
    "ceiling_board": (1.48, 0.0, 0.0011, 1.075, 1.0, 100.0),
    "plywood": (2.71, 0.0, 0.33, 0.0, 1.0, 40.0),
}

_POL_CHOICES = ("te", "tm")


def _material_row(material: str, f_ghz: float) -> tuple[float, float, float,
                                                         float, float, float]:
    """查 Table 3 行并做频域守卫（原文 "not hard limits"—— 主档边界外
    显式拒绝不静默外推，行值注明域）。"""
    if material not in _MATERIAL_TABLE:
        raise ValueError(
            f"material 未知名 {material!r}（Table 3 主档可选："
            f"{sorted(_MATERIAL_TABLE)}）")
    row = _MATERIAL_TABLE[material]
    if not row[4] <= f_ghz <= row[5]:
        raise ValueError(
            f"f_ghz={f_ghz} 越出 {material} 主档 [{row[4]},{row[5]}]GHz"
            "（Table 3 频域行界——官方注明 'not hard limits' 但本键不静默"
            "外推）")
    return row


def _material_eps_sigma(a: float, b: float, c: float, d: float,
                        f_ghz: float) -> tuple[float, float]:
    """式(57)/(58)： ε′=a·f^b、σ=c·f^d。"""
    return a * f_ghz ** b, c * f_ghz ** d


@register_calculator(
    "building_material_properties",
    "建筑媒质电性质：ITU-R P.2040-4 Table 3+式(57)/(58)；ε′=a·f^b、"
    "σ=c·f^d（f[GHz]）→ ε″=σ/(ωε₀)（式(11) 精确路径）、tanδ=ε″/ε′、介电"
    "极限衰减率 A_diel=1636·σ/√ε′ [dB/m]（式(27a)，原文声明 tanδ<0.5 内 "
    "~3% 精度）。8 种 wall 系材料主档（concrete/brick/plasterboard/wood/"
    "glass/chipboard/ceiling_board/plywood），频域行界外显式拒绝。与 "
    "conductor_loss（金属趋肤）/itu_link（大气）边界互指",
    (("material", "str 材料名（Table 3 主档 8 种，见描述）"),
     ("f_ghz", "float GHz 频率（材料行频域内）")),
    required=("material", "f_ghz"),
)
def building_material_properties(material: str, f_ghz: float) -> dict:
    key = "building_material_properties"
    if not isinstance(material, str):
        raise ValueError(f"{key}: material 须为字符串材料名，得 {material!r}")
    f = float(f_ghz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"{key}: f_ghz 必须 >0 且有限，得 {f_ghz!r}")
    row = _material_row(material, f)
    a, b, c, d, f_lo, f_hi = row
    eps_p, sigma = _material_eps_sigma(a, b, c, d, f)
    eps_pp = sigma / (2.0 * math.pi * f * 1e9 * _EPS0_F_M)  # 式(11) 精确
    tan_d = eps_pp / eps_p if eps_p != 0.0 else math.inf
    out: dict = {
        "material": material,
        "f_ghz": f,
        "freq_range_ghz": [f_lo, f_hi],
        "eps_prime": eps_p,
        "sigma_s_per_m": sigma,
        "eps_dprime": eps_pp,
        "tan_delta": tan_d,
        "eps_dprime_eq59_rounded": 17.98 * sigma / f,  # 式(59) 圆化常数档
        "atten_rate_db_per_m": 1636.0 * sigma / math.sqrt(eps_p),  # 式(27a)
        "note": ("式(27a) 为介电极限（tanδ<0.5 原文声明，Table 3 全介质行"
                 "满足）；ε″ 圆化式(59) 17.98 vs 精确 17.9752（rel+2.7e-4）"
                 "仅留痕对拍"),
    }
    return out


@register_calculator(
    "wall_slab_transmission",
    "单层墙板穿透：ITU-R P.2040-4 §2.2.2.2 式(37a/b)/(43a/b)/(44)；"
    "Fresnel 界面系数 R′（空气入射，TE/TM）+ Airy 多次反射干涉 "
    "R=R′(1−e^{−j2q})/(1−R′²e^{−j2q})、T=(1−R′²)e^{−jq}/(1−R′²e^{−j2q})、"
    "q=(2πd/λ)√(ε_rc−sin²θ)。材料名档（material，与 building_material_"
    "properties 同表同域守卫）或显式档（epsilon_r+sigma，sigma=0=无耗）"
    "二选一（双给/部分给显式拒绝）。输出功率面 |R|²/|T|²/吸收与穿透损耗 "
    "−20lg|T|；斜入射域 [0,90)°",
    (("f_ghz", "float GHz 频率（>0；材料档时须在行频域内）"),
     ("thickness_m", "float m 板厚 d（>0）"),
     ("material", "str 材料名（显式档不给）"),
     ("epsilon_r", "float 相对介电常数实部 ε′（显式档 >0）"),
     ("sigma", "float S/m 电导率 σ（显式档 >=0，0=无耗）"),
     ("polarization", "str 'te'/'tm'（缺省 'te'）"),
     ("incidence_deg", "float deg 入射角 θ（[0,90)，缺省 0=垂直入射）")),
    required=("f_ghz", "thickness_m"),
)
def wall_slab_transmission(
    f_ghz: float,
    thickness_m: float,
    material: str | None = None,
    epsilon_r: float | None = None,
    sigma: float | None = None,
    polarization: str = "te",
    incidence_deg: float = 0.0,
) -> dict:
    key = "wall_slab_transmission"
    f = float(f_ghz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"{key}: f_ghz 必须 >0 且有限，得 {f_ghz!r}")
    d_m = float(thickness_m)
    if not math.isfinite(d_m) or d_m <= 0.0:
        raise ValueError(f"{key}: thickness_m 必须 >0 且有限，得 "
                         f"{thickness_m!r}")
    pol = str(polarization).lower()
    if pol not in _POL_CHOICES:
        raise ValueError(f"{key}: polarization 只收 'te'/'tm'，得 "
                         f"{polarization!r}")
    theta_deg = float(incidence_deg)
    if not math.isfinite(theta_deg) or not 0.0 <= theta_deg < 90.0:
        raise ValueError(
            f"{key}: incidence_deg 有效域 [0,90)°，得 {incidence_deg!r}")

    # 双模式：材料名 XOR 显式 ε′+σ（部分给/双给显式拒绝）
    mat_given = material is not None
    eps_given = epsilon_r is not None
    sig_given = sigma is not None
    if mat_given and (eps_given or sig_given):
        raise ValueError(
            f"{key}: 材料名档与显式档（epsilon_r/sigma）互斥——双给=口径"
            "歧义显式拒绝")
    if not mat_given and not (eps_given and sig_given):
        raise ValueError(
            f"{key}: 须给 material 或 epsilon_r+sigma 成对显式档"
            "（部分给=口径歧义显式拒绝）")
    if mat_given:
        if not isinstance(material, str):
            raise ValueError(
                f"{key}: material 须为字符串材料名，得 {material!r}")
        a, b, c, dd, _, _ = _material_row(material, f)
        eps_p, sig = _material_eps_sigma(a, b, c, dd, f)
    else:
        eps_p = float(epsilon_r)  # type: ignore[arg-type]
        sig = float(sigma)  # type: ignore[arg-type]
        if not math.isfinite(eps_p) or eps_p <= 0.0:
            raise ValueError(f"{key}: epsilon_r 必须 >0 且有限，得 "
                             f"{epsilon_r!r}")
        if not math.isfinite(sig) or sig < 0.0:
            raise ValueError(f"{key}: sigma 必须 >=0 且有限，得 {sigma!r}")

    eps_rc = complex(eps_p, -sig / (2.0 * math.pi * f * 1e9 * _EPS0_F_M))
    th = math.radians(theta_deg)
    cos_th = math.cos(th)
    sin2 = math.sin(th) ** 2
    root = cmath.sqrt(eps_rc - sin2)  # 式(33)/(44) 公共根式 √(ε_rc−sin²θ)
    r_prime = ((cos_th - root) / (cos_th + root) if pol == "te"
               else (eps_rc * cos_th - root)
               / (eps_rc * cos_th + root))  # 式(37a)/(37b)
    lam_m = _C0_M_S / (f * 1e9)
    q = 2.0 * math.pi * d_m / lam_m * root  # 式(44)
    phase = cmath.exp(-2j * q)
    r_c = r_prime * (1.0 - phase) / (1.0 - r_prime * r_prime * phase)  # 式(43a)
    t_c = ((1.0 - r_prime * r_prime) * cmath.exp(-1j * q)
           / (1.0 - r_prime * r_prime * phase))  # 式(43b)
    pr = abs(r_c) ** 2
    pt = abs(t_c) ** 2
    loss_db = -20.0 * math.log10(abs(t_c))
    return {
        "f_ghz": f,
        "thickness_m": d_m,
        "polarization": pol,
        "incidence_deg": theta_deg,
        "mode": "material" if mat_given else "explicit",
        "material": material if mat_given else None,
        "eps_prime": eps_p,
        "sigma_s_per_m": sig,
        "eps_rc_real": eps_rc.real,
        "eps_rc_imag": eps_rc.imag,
        "tan_delta": -eps_rc.imag / eps_rc.real,
        "reflection_coeff_abs": abs(r_c),
        "transmission_coeff_abs": abs(t_c),
        "power_reflection": pr,
        "power_transmission": pt,
        "absorbed_fraction": 1.0 - pr - pt,
        "penetration_loss_db": loss_db,
        "phase_thickness_q_re": q.real,
        "phase_thickness_q_im": q.imag,
        "note": ("P.2040-4 式(43) 单层板 Airy 干涉；功率面 |R|²+|T|²+吸收=1"
                 "（有耗板吸收>0，无耗板吸收≈机器精度）"),
    }
