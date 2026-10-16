"""G9 圆柱介质谐振器 TE01δ 正解/反解族（批 B Wave3 W3-G17G9，2026-10-13）。

两键：dr_te01d_cohn_f0（正解：直径/高/εr → TE01δ 谐振频率，Cohn 磁壁
超越方程 brentq 求根）/ dr_te01d_design_size（反解：εr/目标频率/L-D 比
→ 尺寸，一维单调求根 + roundtrip 自检）。**不做 Kajfez 数值拟合表数字化**
（规格包裁定：数字化专有表不可自证，#118）——解析 transcendental 求根，
裁判=测试面独立二分求根双路线 + 规格包独立复算锚 + 同仓常数/方向互证。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
TE01δ 圆柱介质谐振器（半径 a、高 L、εr，环境空气；侧面磁壁近似 + z 向
空气区指数衰减场）：

- 径向：k_r = x01/a，x01 = J₀ 首正零点 = **2.4048255576957724**
  （scipy ``jn_zeros(0, 1)`` 惰性求值；与 calc_families.waveguide_closed_form
  圆柱腔 TM010 同根常数——磁壁条件 H_z(r=a)=0 ⟹ J₀(k_r a)=0）。
- 纵向波数：介质区 β² = εr·k0² − k_r²、空气区 α² = k_r² − k0²
  （k0 = 2πf/c0）。
- **偶对称 TE01δ 特征方程**（z=±L/2 界面 H_z/E_φ 连续）::

      tan(β·L/2) = α/β        ……（式 D1，对 f 求根，brentq）

  存在唯一根：β>0 且 α>0（k0 ∈ (k_r/√εr, k_r) 频窗）内基模支
  （βL/2 ∈ (0, π/2)，tan>0 支）上 tan(βL/2) 随 f 严格增、α/β 严格减
  ⟹ 恰一根；下端 g→−∞（β→0 时 α/β→+∞）、上端 g>0（β=π/L 极点或
  tan(√(εr−1)·k_r·L/2)>0，二者必居其一）——对任意 εr>1、L>0、D>0
  恒有唯一基模根（代数证明+全域数值扫描双证，见测试）。
- **端板贴面极限**（理想导电板紧贴介质端面、侧面磁壁口径不变，TE01p
  全填充口径）::

      f = c0/(2π√εr)·√((x01/a)² + (π/L)²)   ……（式 D2）

  结构恒等式：式 D1 基模支的 β=π/L 极点频率**恰等于**式 D2（β²+α 关系
  代数推得），故恒有 f_TE01δ(式 D1) < f_贴面(式 D2)（α>0 严格）——
  自由 DR 低于贴面口径=物理方向锚。
- δ 记号：式 D1 解出的模式记 TE01δ（0<δ<1=场部分在介质内，轴向变化
  不足半波）；式 D2 为端板贴面 TE01p 全填充口径。**两模型是不同物理
  组态（自由 DR vs 导电板贴面），不存在极限衔接**（规格勘误 2026-10-13：
  L→0 时式 D1 → 频窗上缘 c0·x01/(2πa) 而式 D2 → ∞，实测
  tests/unit/test_b_wave3_dr_te01d.py）。
- 介质内储能份额（电能量口径，推导：E_φ ∝ J₁(k_r r)·Z(z)，介质区
  Z=cos(βz)、空气区 Z=cos(βL/2)·e^{−α(|z|−L/2)} 幅值匹配）::

      δ_e = εr·(L/2 + sin(βL)/(2β)) / [εr·(L/2 + sin(βL)/(2β))
                                       + cos²(βL/2)/α]

  （分子=介质区 εr·∫cos²dz、分母第二项=两侧空气区 ∫|Z|²dz；径向积分
  与公共因子约去。磁壁模型精度：与全波偏差典型 ~1% 内，Kajfez 口径；
  无端板的自由 DR 假定，如实 note。）

与 material_characterization.courtney_* 的口径边界（同仓双模型防撞）
--------------------------------------------------------------------
courtney_f0_of_er 的 TE01p 闭式径向条件为 **J₁ 零点 x11=3.8317**
（confined 全金属侧壁口径，TE0mn 径向条件 J₁(x0n)=0）；本族磁壁口径
径向条件为 **J₀ 零点 x01=2.4048**。两者是不同物理组态（平行板贴面+
开放侧壁 vs 全封闭金属腔），同几何下恒有 f_磁壁贴面(D2) < f_confined(J1)
——测试面钉方向锚与常数同根钉（waveguide_closed_form TM010），**不做
逐位互证**（规格包"与 courtney_f0_of_er 逐位同源/逐位一致 ≤1e-12"系
勘误项：2026-10-13 实测 courtney_f0_of_er(38, 7.5mm, 7.5mm)=5.1136 GHz
vs 本族式 D2=4.0830 GHz，径向条件不同源，见规格文件勘误注记）。

出处
----
- S. B. Cohn, "Microwave Bandpass Filters Containing High-Q Dielectric
  Resonators", IEEE T-MTT 16(4), 218-227 (1968), DOI
  10.1109/TMTT.1968.1126708（磁壁模型；IEEE 付费墙 access_status=
  unverified，式 D1 为 Pozar *Microwave Engineering* §6.5 / Kajfez &
  Guillon *Dielectric Resonators* ch.3 磁壁模型教科书普遍转引口径）。
- 端板贴面极限（式 D2）：出处见 rfauto.core.material_characterization
  .courtney_f0_of_er docstring（同形闭式；注意其径向条件为 J1 零点
  confined 口径，见上"口径边界"节——同仓互证=方向锚+常数同根，非逐位）。
- 锚值（#118 双路径）：内部规格档独立复算（D1-D6 全部复算确认）+
  测试面独立二分求根第二路线。

守卫：diameter_mm>0、height_mm>0、epsilon_r ≥2（<2 拒绝——εr→1 时模式
概念退化）、tan_delta ≥0；design 键 height_to_diameter ∈ (0,2) 开区间
（2.0 恰值拒绝）；L≥D（高径比 >1 高阶模竞争）输出 warnings 不拒绝；
NaN/inf/bool 一律显式拒绝。数值 0.0 合法面判缺失一律 is not None（#364④）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

#: 真空光速（m/s，SI 精确定义值；与 registry.C_MM_GHZ·1e6 同根）
_C0 = 299792458.0

#: 式 D2（端板贴面极限）口径 note 前缀
_PLATES_NOTE = (
    "f0_mw_plates_ghz=式 D2 端板贴面极限（理想导电板紧贴介质端面，侧面"
    "磁壁口径不变，TE01p 全填充）；与式 D1 之比即空气份额物理量（自由 DR "
    "恒低于贴面口径）")

_SOURCES = {
    "cohn": (
        "Cohn 1968 IEEE T-MTT 16(4) DOI 10.1109/TMTT.1968.1126708 磁壁超越"
        "方程（Pozar §6.5/Kajfez & Guillon ch.3 教科书转引口径；原著付费墙 "
        "access_status=unverified）；端板贴面极限同形闭式出处见 "
        "material_characterization.courtney_f0_of_er（注意其径向条件为 J1 "
        "零点 confined 口径，本族为 J0 零点磁壁口径）"),
    "design": (
        "式 D1 反解（一维单调求根+roundtrip 自检）；式 D2 对照；出处见 "
        "rfauto.core.calc_families.dr_te01d 模块 docstring"),
}


def _j0_first_zero() -> float:
    """J₀ 第一正零点 x01（scipy 惰性求值免硬编码；=圆柱腔 TM010 同根）。"""
    from scipy.special import jn_zeros

    return float(jn_zeros(0, 1)[-1])


def _char_eq_residual(f_hz: float, er: float, kr: float, l_m: float) -> float:
    """式 D1 左右差 g(f) = tan(βL/2) − α/β（根处应为 0）。

    端点奇异性处理：β→0（f=频窗下缘）时 g→−∞（哨兵 −1.0）；α→0
    （f=频窗上缘/极点）时 g=tan(βL/2)（有限或大正值——math.tan 对
    π/2 邻域返回有限大数，不溢出）。
    """
    k0 = 2.0 * math.pi * f_hz / _C0
    b2 = er * k0 * k0 - kr * kr
    a2 = kr * kr - k0 * k0
    beta = math.sqrt(b2) if b2 > 0.0 else 0.0
    alpha = math.sqrt(a2) if a2 > 0.0 else 0.0
    if beta == 0.0:
        return -1.0
    tan_term = math.tan(beta * l_m / 2.0)
    if alpha == 0.0:
        return tan_term
    return tan_term - alpha / beta


def _cohn_f0_hz(er: float, a_m: float, l_m: float) -> float:
    """式 D1 基模支求根（Hz）。er≥2、a_m>0、l_m>0；根恒存在（见模块头注）。"""
    from scipy.optimize import brentq

    x01 = _j0_first_zero()
    kr = x01 / a_m
    f_lo = _C0 * kr / (2.0 * math.pi * math.sqrt(er))
    f_hi = _C0 * kr / (2.0 * math.pi)
    # 基模支 β=π/L 极点频率（代数恒等于式 D2 贴面值）；极点在窗内时
    # 以其为上括（tan→+大正数），否则整窗即基模支。
    f_pole = _C0 * math.sqrt(
        kr * kr + (math.pi / l_m) ** 2) / (2.0 * math.pi * math.sqrt(er))
    f_up = min(f_hi, f_pole)
    a_br = f_lo
    b_br = f_up * (1.0 - 1e-12)  # 上端内缩：避开极点/上缘的 β² 灾难性消去
    g_a = _char_eq_residual(a_br, er, kr, l_m)
    g_b = _char_eq_residual(b_br, er, kr, l_m)
    if not (g_a < 0.0 < g_b):
        # 数学上对 εr>1、L>0、D>0 不可达（模块头注唯一根证明）——到达即
        # 退化几何（亚纳米级 L/D 比或浮点 bracket 塌缩），显式报错不静默。
        raise ValueError(
            "dr_te01d: 式 D1 基模根 bracket 失败（退化几何/浮点塌缩）——"
            f"g(f_lo)={g_a!r}, g(f_up)={g_b!r}, 频窗 "
            f"[{f_lo/1e9:.9g}, {f_up/1e9:.9g}] GHz")
    return float(brentq(
        _char_eq_residual, a_br, b_br,
        args=(er, kr, l_m), xtol=1e-15, rtol=8.881784197001252e-16,
        maxiter=200))


def _plates_f0_hz(er: float, a_m: float, l_m: float) -> float:
    """式 D2 端板贴面极限（Hz）——磁壁径向条件 x01/a + 轴向 π/L 驻波。"""
    x01 = _j0_first_zero()
    kr = x01 / a_m
    k0_sq = kr * kr + (math.pi / l_m) ** 2
    return _C0 / (2.0 * math.pi * math.sqrt(er)) * math.sqrt(k0_sq)


def _delta_energy_fraction(
    er: float, beta_rad_m: float, alpha_per_m: float, l_m: float) -> float:
    """介质内电能量份额 δ_e（推导见模块头注；单一实现点，测试独立重算）。"""
    w_dr = er * (l_m / 2.0 + math.sin(beta_rad_m * l_m)
                 / (2.0 * beta_rad_m))
    w_air = math.cos(beta_rad_m * l_m / 2.0) ** 2 / alpha_per_m
    return w_dr / (w_dr + w_air)


@register_calculator(
    "dr_te01d_cohn_f0",
    "圆柱介质谐振器 TE01δ 正解（磁壁模型）：Cohn 1968 超越方程 "
    "tan(βL/2)=α/β，brentq 求根——直径 D/高 L/εr → f0，随行式 D2 端板"
    "贴面对照频率（两"
    "模型之比=空气份额物理量）、k_r=x01/a（x01=J0 首正零点 2.4048，与圆"
    "柱腔 TM010 同根）、β/α、介质内储能份额 δ_e、q_dielectric=1/tanδ"
    "（tanδ=0 返 null）。L≥D 带高阶模竞争警告不拒绝。锚（规格包独立复算，"
    "测试面独立二分双路线互证）：εr=38/D=15mm/L=7.5mm → f0=3.114682 GHz、"
    "贴面=4.083040 GHz（比 0.7628）；εr=81/D=10.6/L=4.6 → 3.132377 GHz；"
    "εr=36.3/D=18/L=8 → 2.733303 GHz",
    (("diameter_mm", "float mm 谐振器直径 D=2a（>0，DR 商品口径单输入）"),
     ("height_mm", "float mm 谐振器高度 L（>0）"),
     ("epsilon_r", "float 相对介电常数（≥2，DR 实用域；<2 模式概念退化拒绝）"),
     ("tan_delta", "float 损耗角正切（≥0，缺省 0=无耗，q_dielectric=null）")),
    required=("diameter_mm", "height_mm", "epsilon_r"),
)
def dr_te01d_cohn_f0(
    diameter_mm: float,
    height_mm: float,
    epsilon_r: float,
    tan_delta: float = 0.0,
) -> dict[str, Any]:
    """正解：几何/材料 → TE01δ 谐振频率（式 D1 brentq 基模支唯一根）。"""
    d_mm = _finite(diameter_mm, "diameter_mm")
    l_mm = _finite(height_mm, "height_mm")
    er = _finite(epsilon_r, "epsilon_r")
    tand = _finite(tan_delta, "tan_delta")
    if d_mm <= 0.0:
        raise ValueError(
            f"dr_te01d_cohn_f0: diameter_mm 必须 >0，得到 {diameter_mm!r}")
    if l_mm <= 0.0:
        raise ValueError(
            f"dr_te01d_cohn_f0: height_mm 必须 >0，得到 {height_mm!r}")
    if er < 2.0:
        raise ValueError(
            f"dr_te01d_cohn_f0: epsilon_r 必须 ≥2（DR 实用域，<2 模式概念"
            f"退化），得到 {epsilon_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"dr_te01d_cohn_f0: tan_delta 必须 ≥0，得到 {tan_delta!r}")

    x01 = _j0_first_zero()
    a_mm = d_mm / 2.0
    a_m, l_m = a_mm * 1e-3, l_mm * 1e-3
    kr_per_mm = x01 / a_mm
    kr = kr_per_mm * 1e3  # rad/m
    f0_hz = _cohn_f0_hz(er, a_m, l_m)
    f_plates_hz = _plates_f0_hz(er, a_m, l_m)
    k0 = 2.0 * math.pi * f0_hz / _C0
    beta = math.sqrt(er * k0 * k0 - kr * kr)
    alpha = math.sqrt(kr * kr - k0 * k0)
    residual = abs(math.tan(beta * l_m / 2.0) - alpha / beta)
    delta_e = _delta_energy_fraction(er, beta, alpha, l_m)

    warnings: list[str] = []
    if l_mm >= d_mm:
        warnings.append(
            f"height_mm={l_mm!r} ≥ diameter_mm={d_mm!r}（高径比 ≥1）："
            "高阶轴向模竞争，TE01δ 基模语义弱化，数值照给如实标注")

    return {
        "f0_ghz": f0_hz / 1e9,
        "f0_mw_plates_ghz": f_plates_hz / 1e9,
        "f_plates_over_cohn": f_plates_hz / f0_hz,
        "f_window_low_ghz": _C0 * kr / (2.0 * math.pi * math.sqrt(er))
        / 1e9,
        "f_window_high_ghz": _C0 * kr / (2.0 * math.pi) / 1e9,
        "x01": x01,
        "kr_rad_per_mm": kr_per_mm,
        "beta_rad_per_mm": beta / 1e3,
        "alpha_per_mm": alpha / 1e3,
        "delta_energy_fraction": delta_e,
        "q_dielectric": None if tand == 0.0 else 1.0 / tand,
        "char_eq_residual": residual,
        "note": (
            "Cohn 1968 磁壁模型（侧面磁壁 + 空气区指数衰减场），与全波偏差"
            "典型 ~1% 内（Kajfez 口径）；无端板的自由 DR 假定；根在频窗 "
            "(k_r/√εr, k_r)·c0/2π 内基模支唯一；" + _PLATES_NOTE),
        "warnings": warnings,
        "source": _SOURCES["cohn"],
    }


@register_calculator(
    "dr_te01d_design_size",
    "圆柱介质谐振器 TE01δ 反解尺寸：式 D1 一维求根——εr/目标频率/L-D 比"
    "h → 直径 D、高 L=h·D。f0(D) 在有效域严格单调降（√εr 标度因空气份额"
    "破缺——εr×4 只降 0.501 非 0.5，规格包 D5 锚），可行域 D ∈ "
    "(K_lo, min(K_hi, K_pole))/f_target 由频窗上下缘+贴面极点三界给出，"
    "log 栅格扫描+cell 内 brentq；roundtrip 残差（尺寸回代式 D1）随行，"
    ">1e-8 内部断言失败显式报错。锚：εr=38/f0=3.1146824935345903 GHz/"
    "h=0.5 → D=15mm/L=7.5mm（D1 锚回代）",
    (("epsilon_r", "float 相对介电常数（≥2，DR 实用域）"),
     ("f0_ghz", "float GHz 目标 TE01δ 谐振频率（>0）"),
     ("height_to_diameter", "float L/D 设计比（0<h<2 开区间，2.0 恰值拒绝；"
      "缺省 0.4=商品 DR 典型域；h≥1 带高阶模竞争警告）")),
    required=("epsilon_r", "f0_ghz"),
)
def dr_te01d_design_size(
    epsilon_r: float,
    f0_ghz: float,
    height_to_diameter: float = 0.4,
) -> dict[str, Any]:
    """反解：材料/频率 → 尺寸（唯一单调根 + roundtrip 自检）。"""
    er = _finite(epsilon_r, "epsilon_r")
    f_target_ghz = _finite(f0_ghz, "f0_ghz")
    h = _finite(height_to_diameter, "height_to_diameter")
    if er < 2.0:
        raise ValueError(
            f"dr_te01d_design_size: epsilon_r 必须 ≥2（DR 实用域），得到 "
            f"{epsilon_r!r}")
    if f_target_ghz <= 0.0:
        raise ValueError(
            f"dr_te01d_design_size: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    if not 0.0 < h < 2.0:
        raise ValueError(
            f"dr_te01d_design_size: height_to_diameter 必须 ∈ (0,2) 开区间"
            f"（商品 DR 典型域 ≤1；≥2 高阶模主导无基模设计意义），得到 "
            f"{height_to_diameter!r}")

    from scipy.optimize import brentq

    x01 = _j0_first_zero()
    f_target = f_target_ghz * 1e9
    # 频窗三界（全部 ∝1/D）：f_lo=K_lo/D、f_hi=K_hi/D、f_pole=K_pole/D。
    # 根存在 ⟺ f_lo(D)<f_target<min(f_hi(D), f_pole(D)) ⟺ D ∈ (D_lo, D_min)。
    k_lo = _C0 * x01 / (math.pi * math.sqrt(er))
    k_hi = _C0 * x01 / math.pi
    k_pole = _C0 / (2.0 * math.pi * math.sqrt(er)) * math.sqrt(
        (2.0 * x01) ** 2 + (math.pi / h) ** 2)
    d_lo = k_lo / f_target
    d_min = min(k_hi, k_pole) / f_target
    if not d_min > d_lo * (1.0 + 1e-9):
        raise ValueError(
            "dr_te01d_design_size: 可行直径区间塌缩（目标频率落频窗外/"
            f"退化 h）——D ∈ ({d_lo*1e3:.9g}, {d_min*1e3:.9g}) mm")

    def _f_dev(d_m: float) -> float:
        return _cohn_f0_hz(er, d_m / 2.0, h * d_m) - f_target

    # log 栅格扫描找首个变号 cell（f0(D) 严格单调降 ⟹ 唯一变号）
    n_scan = 96
    lo_m, hi_m = d_lo * (1.0 + 1e-9), d_min * (1.0 - 1e-9)
    step = (math.log(hi_m) - math.log(lo_m)) / n_scan
    bracket: tuple[float, float] | None = None
    prev_d = lo_m
    prev_v = _f_dev(prev_d)
    for i in range(1, n_scan + 1):
        cur_d = lo_m * math.exp(step * i)
        if i == n_scan:
            cur_d = hi_m
        cur_v = _f_dev(cur_d)
        if prev_v > 0.0 >= cur_v:
            bracket = (prev_d, cur_d)
            break
        prev_d, prev_v = cur_d, cur_v
    if bracket is None:
        raise ValueError(
            "dr_te01d_design_size: 单调根 bracket 未命中（数值退化）——"
            f"D 可行窗 ({d_lo*1e3:.9g}, {d_min*1e3:.9g}) mm")
    d_m = float(brentq(
        _f_dev, bracket[0], bracket[1],
        xtol=1e-15, rtol=8.881784197001252e-16, maxiter=200))
    l_m = h * d_m

    f_roundtrip_hz = _cohn_f0_hz(er, d_m / 2.0, l_m)
    rel_residual = abs(f_roundtrip_hz - f_target) / f_target
    if rel_residual > 1e-8:
        raise ValueError(
            "dr_te01d_design_size: roundtrip 残差超内部阈值（求根失败）——"
            f"|f(D)-f_target|/f_target={rel_residual!r} > 1e-8")
    f_plates_hz = _plates_f0_hz(er, d_m / 2.0, l_m)

    warnings: list[str] = []
    if h >= 1.0:
        warnings.append(
            f"height_to_diameter={h!r} ≥1（L≥D）：高阶轴向模竞争，"
            "TE01δ 基模语义弱化，尺寸照给如实标注")

    return {
        "epsilon_r": er,
        "f0_target_ghz": f_target_ghz,
        "height_to_diameter": h,
        "diameter_mm": d_m * 1e3,
        "height_mm": l_m * 1e3,
        "radius_mm": d_m * 1e3 / 2.0,
        "roundtrip_rel_residual": rel_residual,
        "f0_mw_plates_ghz": f_plates_hz / 1e9,
        "x01": x01,
        "note": (
            "反解=f0(D) 一维单调降根（可行域由频窗上下缘+式 D2 极点三界"
            "给出）；roundtrip=尺寸回代式 D1 的相对残差（求根精度级）；"
            "√εr 标度因空气份额破缺（εr×4 → f0×0.501 非 0.5，D5 锚）；"
            + _PLATES_NOTE),
        "warnings": warnings,
        "source": _SOURCES["design"],
    }

