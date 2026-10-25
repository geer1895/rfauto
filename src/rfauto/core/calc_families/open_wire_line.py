"""平衡开线族（aurora_g W10-S4 席，R3_domain_expansion 视角1 A2——rf_line
第七种线型：唯一无基板的开架平行线，rf_line 六型（microstrip/cpw/cpwg/
stripline/cps/suspended_stripline）全部是基板线，开架双线/单线对地零命中）。

两键：open_two_wire_line（开架双线，精确双极坐标式）/open_wire_over_ground
（单线对地，镜像定理精确式）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``twin|open.?wire|明线|ladder`` src/rfauto/core 三面零实命中（rwg_mmt
"twin"=HStepJunction 变量名误中）；corona.two_wire 是**电晕场强**语境
（几何因子 arcosh(D/2r) 同核、量纲与语义不同）；rf_line 13 键无开架线；
coax_line=同轴、wirebond=键合线电感。本族只做开架平行传输线参数面。

物理口径（docstring 写死，#1c/#300 出处纪律；双源核对 2026-10-19）
--------------------------------------------------------
1. 开架双线（半径 a、中心距 D>2a、均匀介质 εr）——双极坐标**精确式**
   （Ramo-Whinnery-Van Duzer《Fields and Waves in Communication
   Electronics》§2.6 / Pozar《Microwave Engineering》4th ed eq.(2.74)；
   与 core/corona.py two_wire 几何因子 arcosh(D/2r) 同核双源）：

       Z0 = (η0/(π·√εr))·acosh(D/(2a))
       C' = π·ε0·εr/acosh(D/(2a))        （双极坐标精确电容）
       L' = (μ0/π)·acosh(D/(2a))
       延迟 √(L'C') = √εr/c0（均匀填充准 TEM 精确）

   acosh(x)=ln(x+√(x²−1)) 恒等式给出 D≫a 渐近 Z0→(120/√εr)·ln(D/a)
   （对数式与 acosh 式逐位同值——同式双形态锚）。模型域 D>2a 全域精确
   （双极解无细线近似），非 h≫a 工程近似档。

2. 单线对地（半径 a、离地高度 h>a）——镜像定理精确式（wire+镜像电荷
   −q 恰为 D=2h 双线的奇激励半问题，midplane 为精确等位面）：

       Z0 = (η0/(2π·√εr))·acosh(h/a)     ≈ (60/√εr)·ln(2h/a)（h≫a）
       C' = 2π·ε0·εr/acosh(h/a)
       L' = (μ0/(2π))·acosh(h/a)

   镜像退化恒等式（#118 跨键）：Z0_wg(h) = Z0_two_wire(D=2h)/2——激励
   口径差（对地电压=差分电压之半）逐位可验；h→a⁺ 时 acosh→0 → Z0→0
   （导线触地=短路，物理极限行为正确；arccosh(2h/a) 形态在 h→a 给非零
   Z0=非物理，故本键拒绝该误形态——h/a 为半径口径，直径口径 2h/d 与
   之等价）。

3. 趋肤衰减（freq_ghz+conductivity 同时给时输出）——表面电阻
   Rs=√(πfμ0/σ)（与 core/coax_line/conductor_loss 同核三源）；单位长
   串联电阻按趋肤均匀电流：每导体 R'=Rs/(2πa)，双线回路两导体串联
   R'_loop=Rs/(πa)、单线对地 R'_loop=Rs/(2πa)；αc=R'/(2Z0) Np/m
   （低损线通用式，Pozar eq.(2.87) 口径）→ dB=8.686·Np。近距双线的
  邻近效应修正不建模（如实边界；σ=None 或 freq=None 不出衰减面）。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- rf_line=基板线六型（skrf HJ 单源，有基板口径，本族=无基板开架线）；
- coax_line=同轴（内外导体嵌套非平行开架）；
- corona=电晕起始场强判据（arcosh(D/2r) 仅几何因子同核，量纲 Ω·m）；
- wirebond=键合线部分电感 L 口径（无回流导体、无 Z0/C' 传输线参数面）；
- feed_antenna/linear_antenna_zin=天线阻抗面。
本族只做开架平行线单位长参数（Z0/C'/L'/延迟/趋肤衰减）。

出处：Ramo-Whinnery-Van Duzer（双线精确式）、Pozar 4th ed（双线/单线
对地/低损衰减口径）、镜像定理（Jackson §2.2 级教科书恒等式）。
"""

from __future__ import annotations

import math

from .registry import register_calculator

#: 真空波阻抗 η0（Ω；与 microstrip_disc._ETA0_OHM 同值）
_ETA0_OHM = 376.73031346958504364963
#: 真空介电常数 ε0（F/m；与 η0、c0 配套）
_EPS0_F_M = 8.8541878128e-12
#: 真空磁导率 μ0（H/m）
_MU0_H_M = 1.25663706212e-6
#: 光速 m/s
_C0_M_S = 299792458.0


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


def _finite_pos(key: str, name: str, value: object) -> float:
    v = _finite(key, name, value)
    if v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0，得 {value!r}")
    return v


def _skin_face(key: str, freq_ghz: float | None,
               conductivity: float | None, radius_mm: float,
               z0_ohm: float, r_loop_per_wire_ratio: float) -> dict:
    """趋肤衰减面（freq+σ 同时给才出；r_loop_per_wire_ratio=回路 R' 相对
    每导体 Rs/(2πa) 的倍数：双线两导体串联=2、单线对地=1）。"""
    out: dict = {}
    if freq_ghz is None or conductivity is None:
        return out
    tag = key
    f_hz = _finite_pos(tag, "freq_ghz", freq_ghz) * 1e9
    sigma = _finite_pos(tag, "conductivity_s_per_m", conductivity)
    rs = math.sqrt(math.pi * f_hz * _MU0_H_M / sigma)
    r_loop = r_loop_per_wire_ratio * rs / (2.0 * math.pi * radius_mm * 1e-3)
    alpha_np = r_loop / (2.0 * z0_ohm)
    out["rs_ohm"] = rs
    out["r_prime_loop_ohm_per_m"] = r_loop
    out["alpha_c_db_per_m"] = 8.685889638065035 * alpha_np
    return out


@register_calculator(
    "open_two_wire_line",
    "开架双线：双极坐标精确式 Z0=(η0/π√εr)acosh(D/2a)+C'/L'/延迟与趋肤"
    "衰减面。D>2a 全域精确（无细线近似）；acosh 对数恒等式给 D≫a 渐近 "
    "120·ln(D/a) 档；Z0·C'=√εr/c0 恒等（均匀填充准 TEM 精确）。邻近效应"
    "修正不建模（如实边界）",
    (("radius_mm", "float mm 导线半径 a（>0）"),
     ("spacing_mm", "float mm 中心距 D（>2a，触线即短路显式拒绝）"),
     ("epsilon_r", "float 均匀介质相对介电常数（≥1；1=空气/真空开架）"),
     ("freq_ghz", "float GHz 趋肤衰减求值频率（与 conductivity 恰同时给"
      "才出衰减面）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（与 freq_ghz 配套）")),
    required=("radius_mm", "spacing_mm", "epsilon_r"),
)
def open_two_wire_line(radius_mm: float, spacing_mm: float, epsilon_r: float,
                       freq_ghz: float | None = None,
                       conductivity_s_per_m: float | None = None) -> dict:
    key = "open_two_wire_line"
    a_mm = _finite_pos(key, "radius_mm", radius_mm)
    d_mm = _finite_pos(key, "spacing_mm", spacing_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(f"{key}: εr 必须 ≥1，得 {epsilon_r!r}")
    if d_mm <= 2.0 * a_mm:
        raise ValueError(
            f"{key}: 中心距 D 必须 >2a（D≤2a 导线接触=短路、acosh 失域），"
            f"得 D={d_mm!r} vs 2a={2.0 * a_mm!r}")
    if (freq_ghz is None) != (conductivity_s_per_m is None):
        raise ValueError(
            f"{key}: freq_ghz 与 conductivity_s_per_m 必须恰同时给（衰减"
            f"面两参配套），得 {freq_ghz!r}/{conductivity_s_per_m!r}")

    u = d_mm / (2.0 * a_mm)  # acosh 自变量
    a_cosh = math.acosh(u)
    z0 = _ETA0_OHM / (math.pi * math.sqrt(er)) * a_cosh
    c_prime = math.pi * _EPS0_F_M * er / a_cosh
    l_prime = _MU0_H_M / math.pi * a_cosh

    out: dict = {
        "radius_mm": a_mm,
        "spacing_mm": d_mm,
        "epsilon_r": er,
        "d_over_2a": u,
        "z0_ohm": z0,
        "c_prime_f_per_m": c_prime,
        "l_prime_h_per_m": l_prime,
        # 传输线恒等面（均匀填充准 TEM 精确：√(L'C')=√εr/c0）
        "delay_s_per_m": math.sqrt(l_prime * c_prime),
        "telegrapher_residual": abs(
            z0 * c_prime / (math.sqrt(er) * 3.335640951981520e-9) - 1.0),
    }
    out.update(_skin_face(key, freq_ghz, conductivity_s_per_m, a_mm, z0,
                          r_loop_per_wire_ratio=2.0))
    return out


@register_calculator(
    "open_wire_over_ground",
    "单线对地：镜像定理精确式 Z0=(η0/2π√εr)acosh(h/a)+C'/L'/延迟与趋肤"
    "衰减面。镜像退化恒等 Z0(h)=Z0_two_wire(D=2h)/2（激励口径差逐位可验）；"
    "h→a⁺ Z0→0 触地短路物理极限；h≫a 渐近 60·ln(2h/a)。邻近效应修正不"
    "建模（如实边界）",
    (("radius_mm", "float mm 导线半径 a（>0）"),
     ("height_mm", "float mm 离地高度 h（>a；h≤a 触地短路显式拒绝）"),
     ("epsilon_r", "float 均匀介质相对介电常数（≥1）"),
     ("freq_ghz", "float GHz 趋肤衰减求值频率（与 conductivity 配套）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（与 freq_ghz 配套）")),
    required=("radius_mm", "height_mm", "epsilon_r"),
)
def open_wire_over_ground(radius_mm: float, height_mm: float,
                          epsilon_r: float, freq_ghz: float | None = None,
                          conductivity_s_per_m: float | None = None) -> dict:
    key = "open_wire_over_ground"
    a_mm = _finite_pos(key, "radius_mm", radius_mm)
    h_mm = _finite_pos(key, "height_mm", height_mm)
    er = _finite(key, "epsilon_r", epsilon_r)
    if er < 1.0:
        raise ValueError(f"{key}: εr 必须 ≥1，得 {epsilon_r!r}")
    if h_mm <= a_mm:
        raise ValueError(
            f"{key}: 高度 h 必须 >a（h≤a 导线触地=短路、acosh 失域），"
            f"得 h={h_mm!r} vs a={a_mm!r}")
    if (freq_ghz is None) != (conductivity_s_per_m is None):
        raise ValueError(
            f"{key}: freq_ghz 与 conductivity_s_per_m 必须恰同时给（衰减"
            f"面两参配套），得 {freq_ghz!r}/{conductivity_s_per_m!r}")

    a_cosh = math.acosh(h_mm / a_mm)
    z0 = _ETA0_OHM / (2.0 * math.pi * math.sqrt(er)) * a_cosh
    c_prime = 2.0 * math.pi * _EPS0_F_M * er / a_cosh
    l_prime = _MU0_H_M / (2.0 * math.pi) * a_cosh

    out: dict = {
        "radius_mm": a_mm,
        "height_mm": h_mm,
        "epsilon_r": er,
        "h_over_a": h_mm / a_mm,
        "z0_ohm": z0,
        "c_prime_f_per_m": c_prime,
        "l_prime_h_per_m": l_prime,
        "delay_s_per_m": math.sqrt(l_prime * c_prime),
        "telegrapher_residual": abs(
            z0 * c_prime / (math.sqrt(er) * 3.335640951981520e-9) - 1.0),
    }
    out.update(_skin_face(key, freq_ghz, conductivity_s_per_m, a_mm, z0,
                          r_loop_per_wire_ratio=1.0))
    return out
