"""PIN 二极管移相器族（aurora_d W3-CORE6 席，R7_core_tier2 附加候选
"loaded-line/switched-line 移相器"补口，2026-10-14；W3-CORE8 席反射式
续作与本席 W3-CORE9 Schiffman/开关网络式续作收口原位扩展同日）。

五键：loaded_line_phaser（加载线移相器：双并联可切换电纳格胞——设计
正解 Δφ→b/间距 与格胞 ABCD 分析反解）/ switched_line_phaser（开关线
移相器：路径差电长度真时延口径——Δφ→Δl 正解与 Δl→Δφ 反解）/
reflective_phaser（反射式移相器：可变电抗终端反射经环行器/正交混合
环回输——Γ 相位二态差分口径）/ schiffman_phaser（Schiffman 耦合线移
相器：Δφ-频率响应闭式 arccos 口径+平坦点双条件综合，W3-CORE9）/
switched_network_phaser（开关网络式移相器：PIN 开关选通 LC 低通 T 节
移相网络——镜像参数设计+开关插损+N 位级联预算，W3-CORE9）。

边界防撞（R7 附加候选表；CORE9 收口后口径）
------------------------------------------------
- schiffman=耦合线 C-section 宽带定差移相器（模板级
  adapters/oe_templates/render_phase_qwt.py，TA-1；物理长度/微带几何
  反演面=core/synthesis.py schiffman_delta_phase——QW-10 席）；本族
  schiffman_phaser 只做**无量纲电长度设计面**（ρ/电长度比 B/Δφ 三者
  闭式+平坦点综合），与模板渲染、几何综合三层不重复。
- switched_line（路径差 TTD）已在本族；switched_network=开关选通
  **集总低通网络**（相位滞后态+开关插损+N 位级联），两者拓扑不同
  （分布线路径差 vs 集总 LC 网络）不并入。
- butler_matrix.butler_phase_shifter_s_matrix=阵列馈电网络内部理想移相
  器 S 矩阵积木（未注册、无综合面）；varactor.loaded_line_f0_limits_
  ghz=变容管加载线谐振频率限（加载线谐振语境非移相位态）——均不并入。
- attenuator_pi/t、pin_diode_limiter=衰减/限幅面（pa_arch）；本族是
  **相移**面：同一 PIN 控制电路家族的不同物理量口径（Pozar ch.10 同章
  ——开关网络式与限幅器共用 R_on 串联开关损耗口径）。

物理口径（docstring 写死，#1c/#300/#118 出处纪律）
----------------------------------------------
1. **加载线移相器（loaded-line phaser）格胞**：格胞=并联电纳 jb | 电长度
   θ 的传输线 | 并联电纳 jb（Z0 归一化 b），ABCD 级联（Pozar §4.4 约定）::

       M = [1,0; jb,1]·[cosθ, jZ0' sinθ; j sinθ/Z0', cosθ]·[1,0; jb,1]
         （Z0 归一化 Z0'=1）
       A = D = cosθ − b·sinθ
       B = j·sinθ
       C = j·(2b·cosθ + sinθ − b²·sinθ)

   **匹配条件** B=C（等参考阻抗下 S11=0 的充要式）：b = 2·cotθ。匹配时
   格胞等价于 Z0' = sqrt(B/C) = Z0 的均匀线、等效电长度 θ' 满足
   cosθ' = A = −cosθ → **θ' = 180° − θ**。相位二态：电纳接入态相位 θ'
   vs 电纳撤除态（b=0）相位 θ，**差分相移**::

       Δφ = θ' − θ = 180° − 2θ = 2·arctan(b/2)

   （后一等式用匹配关系 b=2cotθ 代入：2arctan(b/2)=180°−2arctan(2/b)、
   θ=arctan(2/b)。Δφ=2·arctan(b/2) 即加载线移相器教科书标准式；小电纳
   近似 Δφ≈b（弧度）。）设计正解：目标位 Δφ 给定 → b = 2·tan(Δφ/2)、
   间距 θ = 90° − Δφ/2；等价并联集总实现 @f0：b>0 容性
   C = b/(2π·f·Z0)、b<0 感性 L = |b|·Z0/(2π·f)。Δφ→180° 时 b→∞/θ→0
   （物理不可实现），本键显式拒绝并指回开关线口径——与经典位态分工
   （22.5/45/90° 用加载线、180° 用开关线）自洽。
   分析反解：给定 b/θ 按 ABCD 级联精确算 S11/S21 与差分相移（对无载
   θ 线参考面），失配 b≠2cotθ 时 S11≠0 如实输出（不静默装匹配）。
   理想化边界：电纳无损集总、PIN 开关理想（on=短路到电纳面/off=开路）、
   TEM/准 TEM 线（εeff 已含色散均值）；封装寄生/开关电阻损耗不在键面。
2. **开关线移相器（switched-line phaser）**：SPDT-SPDT 间参考臂 L_ref 与
   延迟臂 L_ref+Δl 二选一，差分相移=路径差电长度::

       Δφ = 2π·Δl/λg = 360°·Δl·√εeff·f / c0，  λg = c0/(f·√εeff)

   （c0 = 299.792458 mm·GHz，注册表单源 C_MM_GHZ。）真时延（TTD）口径：
   Δφ(f) 随频率线性外推无相差（Δφ(2f₀)=2Δφ(f₀) 恒等），群时延
   Δt = Δl·√εeff/c0 = Δφ/(360°·f)。反解：Δl = (Δφ/360°)·λg。
   L_ref 缺省 λg/4（布局惯例非唯一，不影响 Δφ，如实注记）；插损=开关
   插损+线损（理想开关/无耗线键面输出 0 dB 理想口径，如实标注）。
   180° 位 Δl=λg/2 精确可达（开关线的经典分工位）。
3. **反射式移相器（reflective phaser，W3-CORE8 续作）**：环行器或 3dB
   正交混合环把入射波导向可变电抗终端、反射波回输输出——通过相位=
   反射系数相位。纯电抗终端（归一化电抗 x=X/Z0，串联损耗电阻 r_norm=
   R_s/Z0）::

       Γ = (r_norm + jx − 1)/(r_norm + jx + 1)
       r_norm=0：|Γ|=1 精确、φ(Γ) = 180° − 2·arctan(x)（全角域 (0,360)）

   差分相移恒等式 Δφ = φ(x2)−φ(x1) = 2·(arctan x1 − arctan x2)。
   **设计正解**：±x 对称态对（容性/感性变容管对，x=tan(Δφ/4)）——
   φ(±x) = 180° ∓ Δφ/2 精确、Δφ∈(0,360) 开区间全可达（180° 位
   x=±1 双有限态精确可达——与加载线 b→∞ 不可达分工）；分析反解：
   x1/x2（或变容管 C1/C2 pF @f0：x = −10³/(2π·f_GHz·C_pF·Z0_Ω)）→
   逐态 |Γ|/相位/反射损耗与 Δφ。损耗口径：r_norm>0 时 |Γ|<1，逐态
   反射损耗 −20log10|Γ|（单次反射口径；环行器/混合环理想=零附加损耗，
   混合环双臂等分相干回输不损功率，如实注记）；终端 Q=|x|/r_norm 随
   行输出。理想化边界：变容管纯电容（封装寄生/调制噪声不在键面）、
   环行器/混合环理想 3dB、终端线无耗。

出处（#118 双路径：闭式推导 + 阻抗式数值第二路线互证）
----------------------------------------------
来源：Pozar, *Microwave Engineering*, 4th ed., Wiley 2012, ch.10（PIN
二极管控制电路：开关线/加载线/反射式移相器口径——反射式=混合环+变容
管终端、Γ 幅相口径，章节级转引，式号不落键面）；Bahl & Bhartia,
*Microwave Solid State Circuit Design*, 2nd ed., Wiley 2003（移相器章，
chapter 级转引）；Γ=(Z_L−Z0)/(Z_L+Z0) 阻抗 step 反射系数为传输线教科
书标准式（Pozar §2.x 口径）；φ=180°−2arctan(x)、Δφ=2(arctan x1−arctan
x2)、±x 对称设计态对=本仓第一性推导（实现前独立复算：|Γ|=1 机器精度、
闭式角 vs 阻抗式数值角 ≤1.1e-16、设计 roundtrip 逐位，锚树
tests/unit/test_aurora_d_core8.py 第二路线 numpy 阻抗式独立重算）。

守卫：f_ghz>0 有限；ereff≥1 有限；z0_ohm>0；加载线 Δφ∈(0°,180°) 开区间
（恰值 0/180 显式拒绝——0 无位态、180 需 b→∞ 指回开关线）；分析路线
spacing_deg∈(0°,90°) 开区间（θ→0 对应 b→∞、θ=90 匹配电纳 b=0 退化）、
susceptance_norm 非零有限；开关线设计路线 Δφ∈(0°,360°) 开区间（360°
恰值=整波长约简拒绝，>360 多圈位不收）、反解路线 Δl>0 有限；反射式
设计路线 Δφ∈(0°,360°) 开区间（0 无位态/360 整周期约简拒绝）、分析
路线 x1/x2 有限且 x1≠x2（同态 Δφ=0 无意义）、变容管路线 C>0、
r_norm≥0 有限；route 参数二选一（同给/全缺显式拒绝，#364④ is not
None 口径）；数值 0.0 合法面判缺失一律 is not None。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

#: 加载线差分相移上界（开区间；180° 位指回开关线口径）
_LOADED_PHI_MAX_DEG = 180.0
#: 开关线差分相移上界（开区间；主值口径）
_SWITCHED_PHI_MAX_DEG = 360.0

_SOURCES = {
    "loaded": (
        "加载线移相器：Pozar, Microwave Engineering, 4th ed., Wiley 2012, "
        "ch.10（PIN 二极管控制电路——加载线二态口径，章节级转引，式号不落"
        "键面）；Bahl & Bhartia, Microwave Solid State Circuit Design, "
        "2nd ed., Wiley 2003 移相器章（chapter 级转引）；格胞 ABCD 级联 "
        "Pozar §4.4；匹配条件 b=2cotθ / Δφ=2arctan(b/2) / 等效线 θ'=180°−θ "
        "为本仓 ABCD 第一性推导（数值级联第二路线互证）"),
    "switched": (
        "开关线移相器：Pozar, Microwave Engineering, 4th ed., Wiley 2012, "
        "ch.10（PIN 二极管控制电路——开关线路径差口径，章节级转引，式号不"
        "落键面）；Bahl & Bhartia, Microwave Solid State Circuit Design, "
        "2nd ed., Wiley 2003 移相器章（chapter 级转引）；Δφ=2πΔl/λg 传输线"
        "电长度教科书式（Pozar §2.x 口径）"),
}


def _lambda_g_mm(f_ghz: float, ereff: float) -> float:
    """准 TEM 导波波长 λg = c0/(f·√εeff)（mm·GHz 单源 C_MM_GHZ）。"""
    return C_MM_GHZ / (f_ghz * math.sqrt(ereff))


def _loaded_cell_abcd(b: float, theta_rad: float) -> tuple[float, ...]:
    """加载线格胞 ABCD（Z0 归一化）：[1,0;jb,1]·[cosθ,jsinθ;jsinθ,cosθ]·同左。"""
    c = math.cos(theta_rad)
    s = math.sin(theta_rad)
    a = c - b * s
    bb = 1j * s
    cc = 1j * (2.0 * b * c + s - b * b * s)
    return a, bb, cc, a


def _abcd_to_s(a: complex, bb: complex, cc: complex, d: complex) -> tuple[complex, complex]:
    """等实参考阻抗（归一化 Z0=1）ABCD→S（Pozar §4.4 口径）。"""
    den = a + bb + cc + d
    s11 = (a + bb - cc - d) / den
    s21 = 2.0 / den
    return s11, s21


def _phase_state_deg(s21: complex) -> float:
    """e^{−jφ} 口径的状态相位 φ(deg) = −angle(S21)，规范到 [0,360)。"""
    phi = -math.degrees(math.atan2(s21.imag, s21.real))
    return phi % 360.0


@register_calculator(
    "loaded_line_phaser",
    "加载线移相器：双并联可切换电纳格胞（jb|θ线|jb）二态相移——设计正解 "
    "Δφ→b=2tan(Δφ/2)/间距 θ=90°−Δφ/2（匹配 b=2cotθ，S11=0 精确）或 ABCD "
    "格胞分析反解 b/θ→S11/S21/差分相移（route 二选一）；差分相移闭式 "
    "Δφ=2arctan(b/2)、等效匹配线 θ'=180°−θ；随行集总 C/L 实现值；"
    "Δφ≥180° 显式拒绝（b→∞ 指回开关线口径）",
    (("f_ghz", "float GHz 工作频率（>0）"),
     ("ereff", "float 线有效相对介电常数（≥1，准 TEM 色散均值）"),
     ("z0_ohm", "float Ω 线特性阻抗（>0，缺省 50）"),
     ("delta_phi_deg", "float° 目标差分相移（0<Δφ<180 开区间；设计路线，"
      "与 susceptance_norm/spacing_deg 二选一）"),
     ("susceptance_norm", "float Z0 归一化并联电纳 b（≠0 有限；分析路线）"),
     ("spacing_deg", "float° 两电纳间线电长度 θ（0<θ<90 开区间；分析路线）")),
    required=("f_ghz", "ereff"),
)
def loaded_line_phaser(
    f_ghz: float,
    ereff: float,
    z0_ohm: float = 50.0,
    delta_phi_deg: float | None = None,
    susceptance_norm: float | None = None,
    spacing_deg: float | None = None,
) -> dict[str, Any]:
    """加载线移相器：Δφ→b/间距 正解或 b/θ→S/Δφ ABCD 反解（route 分派）。"""
    f = _finite(f_ghz, "f_ghz")
    er = _finite(ereff, "ereff")
    z0 = _finite(z0_ohm, "z0_ohm")
    if f <= 0.0:
        raise ValueError(
            f"loaded_line_phaser: f_ghz 必须 >0，得到 {f_ghz!r}")
    if er < 1.0:
        raise ValueError(
            f"loaded_line_phaser: ereff 必须 ≥1（相对介电常数物理下界），"
            f"得到 {ereff!r}")
    if z0 <= 0.0:
        raise ValueError(
            f"loaded_line_phaser: z0_ohm 必须 >0，得到 {z0_ohm!r}")

    has_phi = delta_phi_deg is not None
    has_b = susceptance_norm is not None or spacing_deg is not None
    if has_phi and has_b:
        raise ValueError(
            "loaded_line_phaser: delta_phi_deg（设计路线）与 susceptance_"
            "norm/spacing_deg（分析路线）二选一（同给显式拒绝，route 不可"
            "分派）")
    if not has_phi and not has_b:
        raise ValueError(
            "loaded_line_phaser: 须给 delta_phi_deg（设计）或 susceptance_"
            "norm 与 spacing_deg（分析）之一（全缺显式拒绝）")

    lg = _lambda_g_mm(f, er)
    if has_phi:
        phi = _finite(delta_phi_deg, "delta_phi_deg")
        if not 0.0 < phi < _LOADED_PHI_MAX_DEG:
            raise ValueError(
                "loaded_line_phaser: delta_phi_deg 必须 ∈ (0, 180) 开区间"
                f"，得到 {delta_phi_deg!r}（0° 无位态；180° 需 b=2tan90°→∞"
                "物理不可实现——180° 位走 switched_line_phaser 经典分工）")
        b = 2.0 * math.tan(math.radians(phi) / 2.0)
        theta_deg = 90.0 - phi / 2.0
        route = "design_from_delta_phi"
    else:
        if susceptance_norm is None or spacing_deg is None:
            raise ValueError(
                "loaded_line_phaser: 分析路线须同时给 susceptance_norm 与 "
                "spacing_deg（单给显式拒绝）")
        b = _finite(susceptance_norm, "susceptance_norm")
        if b == 0.0:
            raise ValueError(
                "loaded_line_phaser: susceptance_norm 须非零（b=0 电纳撤除"
                f"态无相移），得到 {susceptance_norm!r}")
        theta_deg = _finite(spacing_deg, "spacing_deg")
        if not 0.0 < theta_deg < 90.0:
            raise ValueError(
                "loaded_line_phaser: spacing_deg 必须 ∈ (0, 90) 开区间"
                f"，得到 {spacing_deg!r}（θ→0 对应 b→∞；θ=90 匹配电纳 "
                "b=2cot90°=0 电纳退化）")
        phi = None
        route = "analysis_from_b_theta"

    theta_rad = math.radians(theta_deg)
    a, bb, cc, d = _loaded_cell_abcd(b, theta_rad)
    s11, s21 = _abcd_to_s(a, bb, cc, d)
    phi_loaded = _phase_state_deg(s21)
    phi_ref = theta_deg % 360.0
    dphi_num = (phi_loaded - phi_ref) % 360.0
    if dphi_num > 180.0:  # 差分相移取 (−180,180] 主值口径
        dphi_num -= 360.0
    b_match = 2.0 / math.tan(theta_rad)
    phi_equiv = math.degrees(math.acos(max(-1.0, min(1.0, a.real))))

    out: dict[str, Any] = {
        "route": route,
        "f_ghz": f,
        "ereff": er,
        "z0_ohm": z0,
        "lambda_g_mm": lg,
        "susceptance_norm": b,
        "spacing_deg": theta_deg,
        "spacing_mm": (theta_deg / 360.0) * lg,
        "matched_susceptance_norm": b_match,
        "match_deviation": b - b_match,
        "matched": abs(b - b_match) <= 1e-9 * max(1.0, abs(b_match)),
        "equivalent_line_deg": phi_equiv,
        "state_loaded_deg": phi_loaded,
        "state_reference_deg": phi_ref,
        "delta_phi_deg": dphi_num,
        "s11_mag": abs(s11),
        "s11_db": 20.0 * math.log10(max(abs(s11), 1e-12)),
        "s21_mag": abs(s21),
        "s21_phase_deg": math.degrees(math.atan2(s21.imag, s21.real)),
        "insertion_loss_db": 20.0 * math.log10(1.0 / max(abs(s21), 1e-12)),
    }
    if phi is not None:
        b_pos = b > 0.0
        out["design_delta_phi_deg"] = phi
        out["shunt_C_pf"] = (
            b / (2.0 * math.pi * f * z0) * 1e3 if b_pos else None)
        out["shunt_L_nH"] = (
            abs(b) * z0 / (2.0 * math.pi * f) * 1e3 if not b_pos else None)
    out["note"] = (
        "格胞=并联电纳 jb | θ 线 | jb（Z0 归一化）；匹配条件 B=C → "
        "b=2cotθ（matched=True 时 S11=0 机器精度、|S21|=1）；等效匹配线 "
        "θ'=arccos(−cosθ)=180°−θ；差分相移=接入态 θ' − 撤除态 θ（主值 "
        "(−180,180] 口径）；设计路线 Δφ=2arctan(b/2)（小电纳近似 Δφ≈b "
        "弧度）；集总实现 @f0：b>0 容性 C=b/(2πfZ0)、b<0 感性 "
        "L=|b|Z0/(2πf)；理想化=无损集总电纳+理想 PIN 开关（封装寄生/"
        "开关电阻不在键面）；180° 位态经典分工=switched_line_phaser")
    out["source"] = _SOURCES["loaded"]
    return out


@register_calculator(
    "switched_line_phaser",
    "开关线移相器：SPDT 间参考臂/延迟臂路径差电长度二态——Δφ=360°·Δl·"
    "√εeff·f/c0 正解（Δφ→Δl=Δφ/360°·λg）或 Δl→Δφ 反解（route 二选一）；"
    "真时延（TTD）口径：Δφ 随 f 线性外推零相差误差、群时延 Δt=Δl√εeff/"
    "c0=Δφ/(360°f)；参考臂缺省 λg/4 布局惯例（不影响 Δφ）；180° 位 "
    "Δl=λg/2 精确可达",
    (("f_ghz", "float GHz 工作频率（>0）"),
     ("ereff", "float 线有效相对介电常数（≥1）"),
     ("z0_ohm", "float Ω 线特性阻抗（>0，缺省 50）"),
     ("delta_phi_deg", "float° 目标差分相移（0<Δφ<360 开区间主值；设计"
      "路线，与 delay_line_mm 二选一）"),
     ("delay_line_mm", "float mm 路径差物理长度 Δl（>0；反解路线）"),
     ("ref_len_mm", "float mm 参考臂长度（>0，缺省 λg/4 布局惯例）")),
    required=("f_ghz", "ereff"),
)
def switched_line_phaser(
    f_ghz: float,
    ereff: float,
    z0_ohm: float = 50.0,
    delta_phi_deg: float | None = None,
    delay_line_mm: float | None = None,
    ref_len_mm: float | None = None,
) -> dict[str, Any]:
    """开关线移相器：Δφ↔Δl 双向（TTD 口径，route 二选一）。"""
    f = _finite(f_ghz, "f_ghz")
    er = _finite(ereff, "ereff")
    z0 = _finite(z0_ohm, "z0_ohm")
    if f <= 0.0:
        raise ValueError(
            f"switched_line_phaser: f_ghz 必须 >0，得到 {f_ghz!r}")
    if er < 1.0:
        raise ValueError(
            f"switched_line_phaser: ereff 必须 ≥1（相对介电常数物理下界），"
            f"得到 {ereff!r}")
    if z0 <= 0.0:
        raise ValueError(
            f"switched_line_phaser: z0_ohm 必须 >0，得到 {z0_ohm!r}")

    has_phi = delta_phi_deg is not None
    has_dl = delay_line_mm is not None
    if has_phi and has_dl:
        raise ValueError(
            "switched_line_phaser: delta_phi_deg（设计路线）与 "
            "delay_line_mm（反解路线）二选一（同给显式拒绝，route 不可"
            "分派）")
    if not has_phi and not has_dl:
        raise ValueError(
            "switched_line_phaser: 须给 delta_phi_deg（设计）或 "
            "delay_line_mm（反解）之一（全缺显式拒绝）")

    lg = _lambda_g_mm(f, er)
    if has_phi:
        phi = _finite(delta_phi_deg, "delta_phi_deg")
        if not 0.0 < phi < _SWITCHED_PHI_MAX_DEG:
            raise ValueError(
                "switched_line_phaser: delta_phi_deg 必须 ∈ (0, 360) 开"
                f"区间（主值口径；360° 恰值=整波长约简拒绝，多圈位态不"
                f"收），得到 {delta_phi_deg!r}")
        dl = (phi / 360.0) * lg
        route = "design_from_delta_phi"
    else:
        dl = _finite(delay_line_mm, "delay_line_mm")
        if dl <= 0.0:
            raise ValueError(
                f"switched_line_phaser: delay_line_mm 必须 >0，得到 "
                f"{delay_line_mm!r}")
        phi = 360.0 * dl * math.sqrt(er) * f / C_MM_GHZ
        route = "analysis_from_delay_line"

    phi_unwrapped = phi
    phi_principal = phi % 360.0
    if ref_len_mm is None:
        l_ref = lg / 4.0
        ref_convention = "lambda_g_over_4"
    else:
        l_ref = _finite(ref_len_mm, "ref_len_mm")
        if l_ref <= 0.0:
            raise ValueError(
                f"switched_line_phaser: ref_len_mm 必须 >0，得到 "
                f"{ref_len_mm!r}")
        ref_convention = "explicit"
    group_delay_ns = dl * math.sqrt(er) / C_MM_GHZ

    return {
        "route": route,
        "f_ghz": f,
        "ereff": er,
        "z0_ohm": z0,
        "lambda_g_mm": lg,
        "delta_phi_deg": phi_principal,
        "delta_phi_unwrapped_deg": phi_unwrapped,
        "delay_line_mm": dl,
        "delay_line_electrical_deg": (dl / lg) * 360.0,
        "ref_len_mm": l_ref,
        "ref_len_convention": ref_convention,
        "delay_arm_len_mm": l_ref + dl,
        "group_delay_ns": group_delay_ns,
        "group_delay_ps": group_delay_ns * 1e3,
        "ttd_phase_at_2f0_deg": (phi_unwrapped * 2.0) % 360.0,
        "insertion_loss_db": 0.0,
        "note": (
            "真时延（TTD）口径：Δφ(f)=360°·Δl·√εeff·f/c0 随频率线性外推"
            "（Δφ(2f₀)=2Δφ(f₀) 恒等，无加载线色散位差）；群时延恒等式 "
            "Δt=Δl√εeff/c0=Δφ/(360°·f)；delta_phi_deg=主值 [0,360)、"
            "unwrapped=电长度真值；ref_len 缺省 λg/4 为布局惯例非唯一"
            "（不影响 Δφ）；插损=开关插损+线损，键面为理想开关/无耗线 "
            "0 dB 理想口径如实标注（实测按开关插损上浮）；180° 位 "
            "Δl=λg/2 精确可达（与加载线 b→∞ 不可达的经典分工）"),
        "source": _SOURCES["switched"],
    }

_SOURCES["reflective"] = (
    "反射式移相器：Pozar, Microwave Engineering, 4th ed., Wiley 2012, "
    "ch.10（PIN 二极管控制电路——反射式=混合环/环行器+可变电抗终端、Γ "
    "幅相口径，章节级转引，式号不落键面）；Bahl & Bhartia, Microwave "
    "Solid State Circuit Design, 2nd ed., Wiley 2003 移相器章（chapter "
    "级转引）；Γ=(Z_L−Z0)/(Z_L+Z0) 阻抗 step 反射系数传输线教科书式"
    "（Pozar §2.x 口径）；φ(Γ)=180°−2arctan(x)、Δφ=2(arctan x1−arctan "
    "x2)、±x=tan(Δφ/4) 对称设计态对=本仓第一性推导（阻抗式数值第二"
    "路线互证 ≤1.1e-16）")


@register_calculator(
    "reflective_phaser",
    "反射式移相器：可变电抗终端反射经环行器/正交混合环回输——Γ=(r+jx−1)/"
    "(r+jx+1) 二态，无耗 |Γ|=1、φ=180°−2arctan(x)；设计正解 Δφ→±x="
    "tan(Δφ/4) 容感对称态对（180° 位双有限态精确可达，Δφ∈(0,360)）或 "
    "x1/x2（变容管 C1/C2 pF@f0 同价）分析反解 Δφ=2(arctan x1−arctan x2)"
    "+逐态反射损耗；r_norm 串联损耗口径 Q=|x|/r 随行",
    (("f_ghz", "float GHz 工作频率（>0；变容管路线必需，电抗路线路由"
      " x 无量纲化不消费）"),
     ("z0_ohm", "float Ω 参考阻抗（>0，缺省 50）"),
     ("delta_phi_deg", "float° 目标差分相移（0<Δφ<360 开区间；设计路线，"
      "与 reactance_norm/varactor 路线二选一）"),
     ("x1_norm", "float 态 1 归一化电抗 X/Z0（有限；与 x2_norm 成对，"
      "分析路线）"),
     ("x2_norm", "float 态 2 归一化电抗 X/Z0（有限且 ≠x1；分析路线）"),
     ("c1_pf", "float pF 态 1 变容管电容（>0；变容管路线，与 c2_pf 成对，"
      "需 f_ghz/z0_ohm）"),
     ("c2_pf", "float pF 态 2 变容管电容（>0 且 ≠c1_pf；变容管路线）"),
     ("r_norm", "float 归一化串联损耗电阻 R_s/Z0（≥0 有限，缺省 0=无耗）")),
    required=("f_ghz",),
)
def reflective_phaser(
    f_ghz: float,
    z0_ohm: float = 50.0,
    delta_phi_deg: float | None = None,
    x1_norm: float | None = None,
    x2_norm: float | None = None,
    c1_pf: float | None = None,
    c2_pf: float | None = None,
    r_norm: float = 0.0,
) -> dict[str, Any]:
    """反射式移相器：Δφ→±x 正解或 x1/x2（或 C1/C2）→Δφ/|Γ| 反解。"""
    f = _finite(f_ghz, "f_ghz")
    if f <= 0.0:
        raise ValueError(
            f"reflective_phaser: f_ghz 必须 >0，得到 {f_ghz!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"reflective_phaser: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    r = _finite(r_norm, "r_norm")
    if r < 0.0:
        raise ValueError(
            f"reflective_phaser: r_norm 必须 ≥0（串联损耗电阻非负），"
            f"得到 {r_norm!r}")

    has_phi = delta_phi_deg is not None
    has_x = x1_norm is not None or x2_norm is not None
    has_c = c1_pf is not None or c2_pf is not None
    if sum(bool(v) for v in (has_phi, has_x, has_c)) > 1:
        raise ValueError(
            "reflective_phaser: delta_phi_deg（设计路线）与 x1_norm/"
            "x2_norm（电抗分析）与 c1_pf/c2_pf（变容管分析）三路线二选"
            "一（同给显式拒绝，route 不可分派）")
    if not has_phi and not has_x and not has_c:
        raise ValueError(
            "reflective_phaser: 须给 delta_phi_deg（设计）或 x1_norm/"
            "x2_norm（电抗分析）或 c1_pf/c2_pf（变容管分析）之一（全缺"
            "显式拒绝）")

    def _x_to_cap(x_val: float) -> float | None:
        """x<0（容性）→ 等效电容 pF；感性返 None（与 loaded_line 同风格）。"""
        if x_val >= 0.0:
            return None
        return 1e3 / (2.0 * math.pi * f * (-x_val) * z0)

    def _cap_to_x(c_pf: float) -> float:
        """C_pF@f_GHz → 归一化容抗 x=−10³/(2π·f·C·Z0)。"""
        return -1e3 / (2.0 * math.pi * f * c_pf * z0)

    def _load_l_h(x_val: float) -> float | None:
        if x_val <= 0.0:
            return None
        return x_val * z0 / (2.0 * math.pi * f)  # Ω/GHz ≡ nH

    if has_phi:
        phi = _finite(delta_phi_deg, "delta_phi_deg")
        if not 0.0 < phi < 360.0:
            raise ValueError(
                "reflective_phaser: delta_phi_deg 必须 ∈ (0, 360) 开区间"
                f"（0° 无位态；360° 整周期约简拒绝），得到 {delta_phi_deg!r}")
        x_mag = math.tan(math.radians(phi) / 4.0)
        x1, x2 = x_mag, -x_mag  # 感性/容性对称态对（φ(x1)<φ(x2) → Δφ>0）
        route = "design_from_delta_phi"
        design_phi = phi
    else:
        if has_x:
            if x1_norm is None or x2_norm is None:
                raise ValueError(
                    "reflective_phaser: 电抗分析路线须同时给 x1_norm 与 "
                    "x2_norm（单给显式拒绝）")
            x1 = _finite(x1_norm, "x1_norm")
            x2 = _finite(x2_norm, "x2_norm")
            route = "analysis_from_reactance"
        else:
            if c1_pf is None or c2_pf is None:
                raise ValueError(
                    "reflective_phaser: 变容管分析路线须同时给 c1_pf 与 "
                    "c2_pf（单给显式拒绝）")
            c1 = _finite(c1_pf, "c1_pf")
            c2 = _finite(c2_pf, "c2_pf")
            if c1 <= 0.0 or c2 <= 0.0:
                raise ValueError(
                    f"reflective_phaser: c1_pf/c2_pf 必须 >0，得到 "
                    f"{c1_pf!r}/{c2_pf!r}")
            if c1 == c2:
                raise ValueError(
                    f"reflective_phaser: c1_pf == c2_pf（同态 Δφ=0 无意"
                    f"义），得到 {c1_pf!r}")
            x1 = _cap_to_x(c1)
            x2 = _cap_to_x(c2)
            route = "analysis_from_varactor"
        if x1 == x2:
            raise ValueError(
                f"reflective_phaser: x1_norm == x2_norm（同态 Δφ=0 无意"
                f"义），得到 {x1_norm!r}/{x2_norm!r}")
        design_phi = None

    states: list[dict[str, Any]] = []
    phases: list[float] = []
    for idx, x_val in enumerate((x1, x2), start=1):
        z_load = complex(r, x_val)  # Z_L/Z0 = r + jx
        gamma = (z_load - 1.0) / (z_load + 1.0)  # (r+jx−1)/(r+jx+1)
        g_mag = abs(gamma)
        g_phi = math.degrees(math.atan2(gamma.imag, gamma.real)) % 360.0
        states.append({
            "index": idx,
            "x_norm": x_val,
            "reactance_ohm": x_val * z0,
            "gamma_mag": g_mag,
            "gamma_phase_deg": g_phi,
            "reflection_loss_db": -20.0 * math.log10(max(g_mag, 1e-12)),
            "load_q": None if r == 0.0 or x_val == 0.0
            else abs(x_val) / r,
            "shunt_C_pf": _x_to_cap(x_val) if x_val < 0.0 else None,
            "series_L_nH": _load_l_h(x_val) if x_val > 0.0 else None,
        })
        phases.append(g_phi)
    dphi_raw = phases[1] - phases[0]
    dphi_principal = dphi_raw % 360.0
    if dphi_principal > 180.0:
        dphi_principal -= 360.0

    out: dict[str, Any] = {
        "route": route,
        "f_ghz": f,
        "z0_ohm": z0,
        "r_norm": r,
        "architecture": "circulator_or_quadrature_hybrid",
        "states": states,
        "x1_norm": x1,
        "x2_norm": x2,
        "gamma1_mag": states[0]["gamma_mag"],
        "gamma1_phase_deg": states[0]["gamma_phase_deg"],
        "gamma2_mag": states[1]["gamma_mag"],
        "gamma2_phase_deg": states[1]["gamma_phase_deg"],
        "delta_phi_deg": dphi_principal,
        "delta_phi_unwrapped_deg": dphi_raw,
        "insertion_loss_db": max(states[0]["reflection_loss_db"],
                                 states[1]["reflection_loss_db"]),
    }
    if design_phi is not None:
        out["design_delta_phi_deg"] = design_phi
        out["x_mag_tan_quarter"] = x_mag
    if r > 0.0:
        out["note"] = (
            "损耗口径：r_norm=R_s/Z0 串联电阻随态电抗进 Γ（|Γ|<1），逐态"
            "反射损耗=−20log10|Γ|（单次反射口径；终端 Q=|x|/r 随行）；"
            "环行器/3dB 正交混合环理想=零附加损耗（混合环双臂等分相干回"
            "输不损功率）；r_norm=0 时 |Γ|=1 精确、φ=180°−2arctan(x)、"
            "Δφ=2(arctan x1−arctan x2)；设计路线 ±x=tan(Δφ/4) 容感对称"
            "态对（φ(±x)=180°∓Δφ/2 精确，180° 位 x=±1 双有限态——与加"
            "载线 b→∞ 的分工）；变容管路线 x=−10³/(2πfC_pF·Z0_Ω)；封"
            "装寄生/调制噪声/终端线损耗不在键面")
    else:
        out["note"] = (
            "无耗口径：|Γ|=1 精确、φ=180°−2arctan(x)、Δφ=2(arctan x1−"
            "arctan x2)；设计路线 ±x=tan(Δφ/4) 容感对称态对（φ(±x)=180°"
            "∓Δφ/2 精确，180° 位 x=±1 双有限态——与加载线 b→∞ 的分工）；"
            "变容管路线 x=−10³/(2πfC_pF·Z0_Ω)；环行器/混合环理想零附加"
            "损耗（损耗面=r_norm 串联电阻口径）；封装寄生/调制噪声不在"
            "键面")
    out["source"] = _SOURCES["reflective"]
    return out


_SOURCES["schiffman"] = (
    "Schiffman 移相器：B. M. Schiffman, \"A New Class of Broad-Band "
    "Microwave 90-Degree Phase Shifters\", IRE Trans. MTT 6(2):232-237, "
    "April 1958（耦合段 arccos 相位式 φ_c=arccos[(ρ−tan²θ)/(ρ+tan²θ)] 与 "
    "λ/4 耦合段 vs 3λ/4 参考段经典 90° 口径，原文可达已核——IEEE Xplore/"
    "ADS 双源，式号不落键面）；均匀介质极限与模态 S21=−j(a+b)/(1+ab+"
    "j(a−b)) 换算=core/synthesis.py QW-10 同链（实测 4e-6°）；平坦点双条"
    "件（dΔφ/dθ=0 解析式 2√ρ·sec²θ/(ρ+tan²θ)=B + Δφ=target）与连续支延"
    "拓（φ_c(θ+180°)=φ_c(θ)+360°）=本仓第一性推导（模态第二路线逐象限 "
    "≤7e-14°，独立验证轨迹（内部档））")


def _schiffman_phi_c_deg(theta_deg: float, rho: float) -> float:
    """Schiffman 耦合段（短路耦合 C-section）连续插入相位（度）。

    闭式 arccos 主支+连续支延拓：φ_c(θ mod 180°) 基础支（≤90° 取
    arccos、>90° 取 360°−arccos）+360°·⌊θ/180°⌋——θ→0 时 φ_c→0 单调
    全通相位（模态第二路线逐象限互证 ≤7e-14°）。"""
    theta_mod = theta_deg % 180.0
    turns = math.floor(theta_deg / 180.0)
    t2 = math.tan(math.radians(theta_mod)) ** 2
    u = (rho - t2) / (rho + t2)
    u_c = max(-1.0, min(1.0, u))
    base = math.degrees(math.acos(u_c))
    if theta_mod > 90.0:
        base = 360.0 - base
    return base + 360.0 * turns


def _schiffman_delta_phi_deg(theta_deg: float, rho: float,
                             b_ratio: float) -> float:
    """Schiffman 差分相移 Δφ = B·θ − φ_c(θ)（度；B=L_ref/L 电长度比）。"""
    return b_ratio * theta_deg - _schiffman_phi_c_deg(theta_deg, rho)


_SCHIFFMAN_BAND_RATIOS = (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)


@register_calculator(
    "schiffman_phaser",
    "Schiffman 耦合线移相器（电长度设计面）：短路耦合 C-section "
    "φ_c=arccos[(ρ−tan²θ)/(ρ+tan²θ)] vs 参考段 B·θ——三路线：分析（ρ/"
    "B/θ₀→Δφ(f₀)+频带响应+平坦度）、设计（Δφ 目标+ρ+B→θ₀ brentq 上升"
    "支反解）、平坦综合（Δφ 目标+B→ρ* 与 θ* 双条件——dΔφ/dθ=0 平坦峰）"
    "；λ/4 耦合段 vs 3λ/4 参考段经典 90° 锚精确；Z0e·Z0o=Z0² 全通匹配"
    "随行几何；(0,360) 连续支延拓全域",
    (("f_ghz", "float GHz 工作频率（>0；电长度→物理长度换算）"),
     ("ereff", "float 线有效相对介电常数（≥1，准 TEM 色散均值）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50；全通匹配 Z0e·Z0o=Z0²）"),
     ("rho", "float 阻抗比 ρ=Z0e/Z0o（>1 物理序；设计路线与 delta_phi_"
      "deg 同给）"),
     ("b_ratio", "float 参考段/耦合段电长度比 B=L_ref/L（>0，缺省 3="
      "Schiffman 3λ/4 惯例）"),
     ("theta0_deg", "float° 耦合段电长度 θ₀（0<θ₀≤180；分析路线，与 "
      "delta_phi_deg 二选一）"),
     ("delta_phi_deg", "float° 目标差分相移（>0；设计路线——与 rho 同给"
      "走定 ρ 反解 θ₀，缺省 rho 走平坦综合双条件）")),
    required=("f_ghz", "ereff"),
)
def schiffman_phaser(
    f_ghz: float,
    ereff: float,
    z0_ohm: float = 50.0,
    rho: float | None = None,
    b_ratio: float = 3.0,
    theta0_deg: float | None = None,
    delta_phi_deg: float | None = None,
) -> dict[str, Any]:
    """Schiffman 移相器：分析 / 定 ρ 设计 / 平坦点综合三路线。"""
    key = "schiffman_phaser"
    f = _finite(f_ghz, "f_ghz")
    er = _finite(ereff, "ereff")
    z0 = _finite(z0_ohm, "z0_ohm")
    if f <= 0.0:
        raise ValueError(f"{key}: f_ghz 必须 >0，得到 {f_ghz!r}")
    if er < 1.0:
        raise ValueError(
            f"{key}: ereff 必须 ≥1（相对介电常数物理下界），得到 {ereff!r}")
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    if b_ratio is None:
        raise ValueError(f"{key}: b_ratio 不可为 None（显式传值口径）")
    b_val = _finite(b_ratio, "b_ratio")
    if b_val <= 0.0:
        raise ValueError(
            f"{key}: b_ratio=L_ref/L 必须 >0，得到 {b_ratio!r}")

    has_theta = theta0_deg is not None
    has_phi = delta_phi_deg is not None
    if has_theta and has_phi:
        raise ValueError(
            f"{key}: theta0_deg（分析路线）与 delta_phi_deg（设计路线）二"
            "选一（同给显式拒绝，route 不可分派）")
    if not has_theta and not has_phi:
        raise ValueError(
            f"{key}: 须给 theta0_deg（分析）或 delta_phi_deg（设计）之一"
            "（全缺显式拒绝）")

    from scipy.optimize import brentq

    lg = _lambda_g_mm(f, er)
    if has_theta:
        if rho is None:
            raise ValueError(
                f"{key}: 分析路线须显式给 rho（θ₀ 单给无法定耦合强度）")
        rho_v = _finite(rho, "rho")
        if rho_v <= 1.0:
            raise ValueError(
                f"{key}: rho=Z0e/Z0o 必须 >1（耦合线偶/奇模阻抗物理序，"
                f"ρ→1 无耦合退化），得到 {rho!r}")
        th0 = _finite(theta0_deg, "theta0_deg")
        if not 0.0 < th0 <= 180.0:
            raise ValueError(
                f"{key}: theta0_deg 必须 ∈ (0, 180]（连续支主域；θ→0 无"
                f"耦合段），得到 {theta0_deg!r}")
        route = "analysis"
        rho_star = rho_v
        theta_star = th0
        design_phi = None
    else:
        phi_t = _finite(delta_phi_deg, "delta_phi_deg")
        if phi_t <= 0.0:
            raise ValueError(
                f"{key}: delta_phi_deg 必须 >0（0° 无位态），得到 "
                f"{delta_phi_deg!r}")

        def dphi(th_deg: float, rv: float) -> float:
            return _schiffman_delta_phi_deg(th_deg, rv, b_val)

        if rho is not None:
            # 设计路线：定 ρ 反解 θ₀（(0,90] 细扫首个 −→+ 变号+refine）
            rho_v = _finite(rho, "rho")
            if rho_v <= 1.0:
                raise ValueError(
                    f"{key}: rho=Z0e/Z0o 必须 >1，得到 {rho!r}")
            grid = [1e-6 + 90.0 * k / 900 for k in range(901)]
            vals = [dphi(g_v, rho_v) - phi_t for g_v in grid]
            dphi_max = max(dphi(g_v, rho_v) for g_v in grid)
            if phi_t > dphi_max + 1e-9:
                raise ValueError(
                    f"{key}: 目标 Δφ={phi_t}° 超 ρ={rho_v} 可达峰 "
                    f"{dphi_max:.6f}°（(0,90] 域；显式拒绝不外推——平坦综"
                    "合路线可解更大 Δφ）")
            bracket = None
            for k_i in range(len(grid) - 1):
                if vals[k_i] <= 0.0 <= vals[k_i + 1]:
                    bracket = (grid[k_i], grid[k_i + 1])
                    break
            if bracket is None:
                raise ValueError(
                    f"{key}: 目标 Δφ={phi_t}° 在 (0,90] 无上升支解（显式"
                    "拒绝）")
            theta_star = brentq(lambda tv: dphi(tv, rho_v) - phi_t,
                                bracket[0], bracket[1], xtol=1e-12)
            th0 = theta_star
            route = "design_from_delta_phi"
            design_phi = phi_t
        else:
            # 平坦综合：外层 ρ*（Δφ_flat 单调）+内层 θ*（平坦条件）
            b_sq = b_val * b_val / 4.0

            def flat_theta(rv: float) -> float:
                rr = math.sqrt(rv)

                def ddd(tv: float) -> float:
                    return (2.0 * rr / math.cos(tv) ** 2
                            / (rr * rr + math.tan(tv) ** 2) - b_val)

                return brentq(ddd, 1e-9, math.pi / 2 - 1e-12, xtol=1e-14)

            def dphi_flat(rv: float) -> float:
                return dphi(math.degrees(flat_theta(rv)), rv)

            phi_lo = 90.0 * b_val - 180.0  # ρ→(B²/4)⁺ 渐近下界（解析）
            phi_hi = dphi_flat(1e7)
            if not phi_lo < phi_t <= phi_hi:
                raise ValueError(
                    f"{key}: 平坦综合目标 Δφ={phi_t}° 须 ∈ "
                    f"({phi_lo:.4f}, {phi_hi:.3f}]（B={b_val} 平坦域；下"
                    "界=90B−180° 渐近（恰值=退化点 ρ→B²/4、θ*→90°）、上界="
                    "ρ≤1e7 域；显式拒绝）")
            rho_star = brentq(lambda rv: dphi_flat(rv) - phi_t,
                              b_sq * (1.0 + 1e-9), 1e7, xtol=1e-10,
                              rtol=1e-14)
            theta_star = math.degrees(flat_theta(rho_star))
            rho_v = rho_star
            th0 = theta_star
            route = "design_flat"
            design_phi = phi_t

    phi_c = _schiffman_phi_c_deg(th0, rho_v)
    dphi_f0 = _schiffman_delta_phi_deg(th0, rho_v, b_val)
    coupled_len = (th0 / 360.0) * lg
    ref_len = b_val * coupled_len
    z0e = z0 * math.sqrt(rho_v)
    z0o = z0 / math.sqrt(rho_v)
    band = {f"{ratio:g}": _schiffman_delta_phi_deg(th0 * ratio, rho_v, b_val)
            for ratio in _SCHIFFMAN_BAND_RATIOS}
    flat_dev = max(abs(v - dphi_f0) for v in band.values())

    out: dict[str, Any] = {
        "route": route,
        "f_ghz": f,
        "ereff": er,
        "z0_ohm": z0,
        "lambda_g_mm": lg,
        "rho": rho_v,
        "z0e_ohm": z0e,
        "z0o_ohm": z0o,
        "allpass_match_dev": abs(z0e * z0o - z0 * z0),
        "b_ratio": b_val,
        "theta0_deg": th0,
        "coupled_len_mm": coupled_len,
        "ref_len_mm": ref_len,
        "phi_c_f0_deg": phi_c,
        "delta_phi_f0_deg": dphi_f0,
        "band_response_deg": band,
        "flatness_dev_deg": flat_dev,
    }
    if design_phi is not None:
        out["design_delta_phi_deg"] = design_phi
        if route == "design_flat":
            out["flatness_peak_check_deg"] = min(
                dphi_f0 - _schiffman_delta_phi_deg(th0 - 0.5, rho_v, b_val),
                dphi_f0 - _schiffman_delta_phi_deg(th0 + 0.5, rho_v, b_val))
    out["note"] = (
        "耦合段=远端桥接短路平行耦合线（C-section 全通段），参考直通段 "
        "L_ref=B·L；闭式 φ_c=arccos[(ρ−tan²θ)/(ρ+tan²θ)] 主支+连续支延拓"
        "（θ mod 180° 基础支、+360°/圈）；Δφ=B·θ−φ_c；经典锚：θ₀=90°/B=3 "
        "→ Δφ(f₀)=90° 精确（λ/4 耦合 vs 3λ/4 参考）；全通匹配 Z0e·Z0o="
        "Z0² → Z0e=Z0√ρ、Z0o=Z0/√ρ；band_response=f/f₀∈{0.5..1.5} 频带"
        "抽样（含 >90° 连续支）、flatness_dev=带内最大偏差；设计路线取 "
        "(0,90] 上升支首解（θ₀≤λ/4@f₀ 惯例），平坦综合双条件 dΔφ/dθ="
        "2√ρ·sec²θ/(ρ+tan²θ)−B=0+Δφ=target（Δφ_flat(ρ) 自 90B−180° 单调"
        "上行、ρ>B²/4）；准静态 εeff 常数化口径、色散与损耗不在键面；物"
        "理长度/微带几何反演=synthesis.py schiffman_delta_phase（QW-10）、"
        "模板渲染=render_phase_qwt.py（三层不重复）")
    out["source"] = _SOURCES["schiffman"]
    return out


_SOURCES["switched_network"] = (
    "开关网络式移相器：Pozar, Microwave Engineering, 4th ed., Wiley 2012, "
    "ch.10（PIN 二极管控制电路——开关选通移相网络口径，章节级转引，式号"
    "不落键面）；Bahl & Bhartia, Microwave Solid State Circuit Design, "
    "2nd ed., Wiley 2003 移相器章（chapter 级转引）；镜像参数法（image "
    "parameters）LC 低通 T 节综合=传输线教科书标准法（Pozar §2.x 镜像参"
    "数口径）：τ=2sin(φ/2)/ω₀、L=2Z0·tan(φ/2)/ω₀、C=sinφ/(ω₀Z0)、截止 "
    "ω_c=ω₀/sin(φ/2)=本仓镜像参数第一性推导（ABCD 数值级联第二路线 "
    "|S11|≤1.2e-15 roundtrip，独立验证档）；开关插损 "
    "|S21|=2Z0/(2Z0+R_on) 与 pa_arch pin_diode_limiter "
    "同章同口径")


@register_calculator(
    "switched_network_phaser",
    "开关网络式移相器：PIN 开关选通 LC 低通 T 节移相网络（滞后相位态 vs "
    "直通参考）——镜像参数设计闭式 L=2Z0·tan(φ/2)/ω₀、C=sinφ/(ω₀Z0)、"
    "截止 f_c=f₀/sin(φ/2)、f₀ 处 Z_T=Z0 精确匹配；单网络路线（φ→L/C/截止"
    "/开关插损）或 N 位级联路线（权重 180/2^i 逐位设计+全开 Δφ=360−LSB+"
    "量化 RMS=LSB/√12+总开关插损）；与 pin_diode_limiter 同章开关口径衔接",
    (("f_ghz", "float GHz 工作频率（>0）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）"),
     ("phi_deg", "float° 单网络目标相位滞后（0<φ<180 开区间；单网络路线，"
      "与 n_bits 二选一）"),
     ("n_bits", "int 位数（1..8；N 位级联路线，与 phi_deg 二选一）"),
     ("r_on_ohm", "float Ω PIN 串联开关导通电阻（≥0，缺省 0=理想开关；"
      "每位 2 只串联开关）")),
    required=("f_ghz",),
)
def switched_network_phaser(
    f_ghz: float,
    z0_ohm: float = 50.0,
    phi_deg: float | None = None,
    n_bits: int | None = None,
    r_on_ohm: float = 0.0,
) -> dict[str, Any]:
    """开关网络式移相器：单网络设计或 N 位级联预算（route 二选一）。"""
    key = "switched_network_phaser"
    f = _finite(f_ghz, "f_ghz")
    if f <= 0.0:
        raise ValueError(f"{key}: f_ghz 必须 >0，得到 {f_ghz!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    r_on = _finite(r_on_ohm, "r_on_ohm")
    if r_on < 0.0:
        raise ValueError(
            f"{key}: r_on_ohm 必须 ≥0（导通电阻非负），得到 {r_on_ohm!r}")
    has_phi = phi_deg is not None
    has_bits = n_bits is not None
    if has_phi and has_bits:
        raise ValueError(
            f"{key}: phi_deg（单网络路线）与 n_bits（N 位级联路线）二选一"
            "（同给显式拒绝，route 不可分派）")
    if not has_phi and not has_bits:
        raise ValueError(
            f"{key}: 须给 phi_deg（单网络）或 n_bits（N 位级联）之一（全缺"
            "显式拒绝）")
    w0 = 2.0 * math.pi * f

    def design_cell(phi_t: float) -> dict[str, Any]:
        """镜像参数设计闭式（Ω·ns=nH 口径；C 的 ns/Ω→pF ×1e3）。

        φ=180° 恰值单节 L→∞ 不可实现——L/C 如实 None+realizable=False
        （f_c/群时延极限值仍精确）。"""
        if phi_t >= 180.0:
            fc = f / math.sin(math.radians(phi_t) / 2.0)
            return {
                "phi_deg": phi_t,
                "series_L_total_nH": None,
                "shunt_C_pf": None,
                "cutoff_ghz": fc,
                "cutoff_ratio_f_over_f0": 1.0 / math.sin(
                    math.radians(phi_t) / 2.0),
                "group_delay_ns": 2.0 / w0,
                "image_z0_f0_ohm": None,
                "image_z0_dev": None,
                "realizable_single_cell": False,
            }
        l_nh = 2.0 * z0 * math.tan(math.radians(phi_t) / 2.0) / w0
        c_pf = math.sin(math.radians(phi_t)) / (w0 * z0) * 1e3
        fc = f / math.sin(math.radians(phi_t) / 2.0)
        tau_ns = 2.0 * math.sin(math.radians(phi_t) / 2.0) / w0
        # f₀ 处镜像阻抗恒等式 Z_T(f₀)=(Z0/cos(φ/2))·√(1−(f₀/f_c)²)=Z0
        z_t_f0 = (z0 / math.cos(math.radians(phi_t) / 2.0)) * math.sqrt(
            max(0.0, 1.0 - (f / fc) ** 2))
        return {
            "phi_deg": phi_t,
            "series_L_total_nH": l_nh,
            "shunt_C_pf": c_pf,
            "cutoff_ghz": fc,
            "cutoff_ratio_f_over_f0": 1.0 / math.sin(
                math.radians(phi_t) / 2.0),
            "group_delay_ns": tau_ns,
            "image_z0_f0_ohm": z_t_f0,
            "image_z0_dev": abs(z_t_f0 - z0),
            "realizable_single_cell": True,
        }

    il_switch = 0.0 if r_on == 0.0 else -20.0 * math.log10(
        2.0 * z0 / (2.0 * z0 + r_on))

    if has_phi:
        phi_v = _finite(phi_deg, "phi_deg")
        if not 0.0 < phi_v < 180.0:
            raise ValueError(
                f"{key}: phi_deg 必须 ∈ (0, 180) 开区间（0° 无位态；180° "
                f"需 L→∞ 指回开关线口径），得到 {phi_deg!r}")
        cell = design_cell(phi_v)
        n_sw = 2
        out: dict[str, Any] = {
            "route": "single_network",
            "f_ghz": f,
            "z0_ohm": z0,
            "r_on_ohm": r_on,
            **cell,
            "switches_in_path": n_sw,
            "switch_loss_db": n_sw * il_switch,
            "insertion_loss_db": n_sw * il_switch,
            "delta_phi_deg": phi_v,
        }
        out["note"] = (
            "单网络口径：LC 低通 T 节（串 L/2|并 C|串 L/2）PIN 开关选通 vs "
            "直通参考臂——滞后相位态 Δφ=−φ（键面取滞后幅值 φ 口径）；镜像"
            "参数设计：f₀ 处 Z_T=Z0 精确、ω_c=2/√(LC)=ω₀/sin(φ/2)（镜像"
            "阻抗实数域上限，工作须 f<f_c 且远离 f_c——Z_T(f)=(Z0/cos(φ/2))"
            "√(1−(f/f_c)²) 随 f 塌缩）；无耗网络口径（LC Q 损耗不在键面）；"
            "每位 2 只串联开关插损 |S21|=2Z0/(2Z0+R_on)（与 pa_arch "
            "pin_diode_limiter 同口径）；N 位级联预算=n_bits 路线")
        out["source"] = _SOURCES["switched_network"]
        return out

    if isinstance(n_bits, bool):
        raise ValueError(
            f"{key}: n_bits 须为整数，得到 bool {n_bits!r}")
    n_f = _finite(n_bits, "n_bits")
    if n_f != int(n_f):
        raise ValueError(
            f"{key}: n_bits 须为整数，得到 {n_bits!r}")
    n_bit = int(n_f)
    if not 1 <= n_bit <= 8:
        raise ValueError(
            f"{key}: n_bits 必须 ∈ [1,8]（JSON 面/位态体积守卫），得到 "
            f"{n_bits!r}")
    weights = [180.0 / 2 ** i for i in range(n_bit)]
    cells = [design_cell(w_v) for w_v in weights]
    lsb = weights[-1]
    total_il = 2 * n_bit * il_switch
    out = {
        "route": "bitfield_cascade",
        "f_ghz": f,
        "z0_ohm": z0,
        "r_on_ohm": r_on,
        "n_bits": n_bit,
        "weights_deg": weights,
        "lsb_deg": lsb,
        "bits": [{**c, "switch_loss_db": 2 * il_switch} for c in cells],
        "delta_phi_all_on_deg": sum(weights),
        "delta_phi_max_deg": 360.0 - lsb,
        "quantization_rms_deg": lsb / math.sqrt(12.0),
        "switches_total": 2 * n_bit,
        "insertion_loss_db": total_il,
        "note": (
            "N 位级联口径：位权重 w_i=180°/2^i（MSB=180°、LSB=360°/2^N）——"
            "全开 Δφ=Σw=360°−LSB<360、量化 RMS=LSB/√12（均匀量化标准差）；"
            "逐位独立 LC 低通 T 节（镜像参数设计同单网络路线）、级联总插损"
            "=2N 只串联开关累加（网络无耗口径）；MSB=180° 恰值单节 L→∞ 不"
            "可实现（realizable_single_cell=False、L/C=None——180° 位拓扑"
            "需开关线/多节级联实现，如实注记不虚构有限值）；开关导通电阻口"
            "径与 pa_arch pin_diode_limiter 同章衔接"),
        "source": _SOURCES["switched_network"],
    }
    return out
