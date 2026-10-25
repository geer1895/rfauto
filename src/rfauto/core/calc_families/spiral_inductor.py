"""八角螺旋电感 CALC 注册面（aurora_k K11，2026-10-23，用户反馈 F1）。

一键：``octagonal_spiral_inductance``——GaAs 薄膜 IPD 工艺八角螺旋电感
（W/S/N/Din 全 μm 标量参数）的闭式评估面：Mohan 电流片/修正 Wheeler/
单项式三表达式 L + 带状截面 GMD + 闭式几何回显（d_out/d_avg/填充率/
导带总长）+ 直流电阻与 Q 一阶估计 + SRF 估计，以及**质量门**（反馈 F1
原文口径）：L 对闭式基准 ±25%、SRF>2×f0——门为确定性函数随结果透传
（ok=True + gates.pass 布尔，FAIL 如实呈现不抛异常，#122）。

**薄注册纪律**（conductor_reg/polarization_reg/deembed_metrics 同款）：
物理数学单源在 ``rfauto.core.nfc_coil``（Mohan JSSC 34(10) 1999 三式
系数表原文逐位核对在案；Neumann/GMD 数值参考链同文件）——本模块只做
μm 参数（IPD 工艺口径）→ SI 装配与门组装，零公式复制（#116 死副本教训）。

出处：八角螺旋电感修正 Wheeler/电流片/单项式三闭式与八角形状系数
  =Mohan–Schneider–Chibante, IEEE JSSC 34(10) 1999, pp.1419–1424
  （Table II 电流片八角系数 c1–c4；Table IV 八角实测例 #55/#56 回放
  锚）——物理单源 rfauto.core.nfc_coil（2026-09-24 原文逐位核对在档，
  PDF 存档 内部证据档），本模块薄注册零公式
  复制（#116）。

与既有面分工（#222 triple-grep，2026-10-23 本席开工实测）：
- core/nfc_coil.spiral_inductance=**物理单源**（四形状×三表达式通用内核，
  NFC 13.56MHz 线圈族 df7 C10b 落地；系数表+Table IV 原文锚在案）——
  本键=其八角形状的**注册出口**（CALC 键面此前零螺旋电感键，src/tests/
  scripts 三面 grep ``spiral`` 只命中 nfc_coil 与 NFC 服务面）；
- 本键新增的组装面：μm→SI 换算（IPD 工艺口径）、d_out 由 W/S/N/Din
  闭式导出（d_out=d_in+2nw+2(n−1)s，渲染匝梯同式）、SRF/Q 一阶报告与
  F1 质量门——NFC 侧无对应面（f0 由外配电容给定，Q 面在 coil_esr）。
  形状固定 "octagon"（键名即口径；四形状通用面归 core/nfc_coil 内核与
  其 NFC 服务面，不在 CALC 键复制形状开关）。

数值锚（#118 家法）：
- Mohan 原文 Table IV 八角实测例 #55/#56（n=4, d_out=346μm, w=18μm,
  s=2μm, L_meas=5.90nH 与 n=5 同几何 L_meas=7.50nH，原文 pp.1419-1424
  数表）——本仓 test_nfc_coil.py 已回放（误差列 ≤0.3 个百分点），本键
  经同一单源继承该锚；本席测试另经键面回放（μm 参数口径端到端）；
- 用户实测参考（反馈 F1 原文）：HFSS 默认网格 L=4.226nH/Q=10.86/
  SRF=6.32GHz、金属局部 5μm 网格后 4.312nH/13.44/7.18GHz——对名义
  几何（n=5, din=80, w=10, s=5μm → L_闭式=4.1147nH，电流片式实测）
  偏差 +2.7%/+4.8%（±25% 门内），SRF/f0=3.16/3.59（f0=2GHz 口径，
  >2 门内）——测试钉住（未标定注记：用户几何未给全 W/S/N/Din，此为
  同量级参考对拍非逐位锚；4.1147 为键面实算值，此前 docstring 的
  ≈4.17nH 系手估漂移已勘误，#118 数值裁判家法）。

守卫：n_turns≥1、W/S/Din>0、几何可行（d_in>0，圈数/线宽/间距过大显式
拒绝）；dout_um 给出时与闭式导出值一致性校验（>1% 漂移显式报错——
跨通道同语义，#154）；f0_ghz/c_par_ff 给出时 SRF>2×f0 门才评估。

真机验证留登记：openEMS/HFSS 对拍与 Q 预算区间门（F1 第三门"Q 落预算
区间"）待真机批（内部证据档 §e）——本键 Q 为直流
一阶档（coil_track_dc_resistance 单源，趋肤/邻近在 coil_esr、真机标定
前如实声明未标定）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.nfc_coil import (
    CoilGeometry,
    coil_track_dc_resistance,
    evaluate_coil,
    strip_gmd,
)

from .registry import register_calculator

__all__ = ["octagonal_spiral_inductance"]

_SOURCE = (
    "物理单源 core/nfc_coil（Mohan-Schneider-Chibante IEEE JSSC 34(10) "
    "1999 pp.1419-1424 三式系数表原文逐位核对；GMD=Rosa 零厚带 "
    "g=w·e^(−3/2)；R_dc=coil_track_dc_resistance）；本模块为薄注册包装"
    "（μm 参数装配+K11 质量门组装），公式零复制")

#: 金（IPD 电镀厚金工艺典型值，20°C；Ω·m——调用方可覆盖为 Cu/Al）
RHO_AU_IPD = 2.44e-8

#: IPD 八角螺旋金属厚度缺省（μm，厚金工艺典型档）
T_UM_DEFAULT = 3.0

#: L 对闭式基准门限（反馈 F1 原文口径：±25%）
L_GATE_LIMIT_PCT = 25.0

#: SRF 工作频率倍率门限（反馈 F1 原文口径：>2×f0）
SRF_OVER_F0_LIMIT = 2.0


def _spiral_track_length_m(geom: CoilGeometry) -> float:
    """八角螺旋中心线总长（m）：Σ匝八角环周长（across-flats 顶点单源）。

    与渲染匝梯同口径（A_k=d_out/2−w/2−k(w+s)，nfc_coil.turn_perimeter_m
    顶点闭包求和）；换匝尾/跳桥附加长度属二阶不进闭式报告（如实）。
    """
    from rfauto.core.nfc_coil import turn_perimeter_m

    return sum(turn_perimeter_m(geom, k)
               for k in range(int(geom.n_turns)))


@register_calculator(
    "octagonal_spiral_inductance",
    "八角螺旋电感闭式（μm 参数）：GaAs IPD 工艺 W/S/N/Din→Mohan 电流片/"
    "Wheeler/单项式三表达式 L+nH 级报告+GMD+d_out/d_avg/填充率/导带总长+"
    "R_dc 与 Q 一阶+SRF=1/(2π√(L·C_par))；质量判据随结果透传：L 对"
    "reference_l_nh ±25%、SRF>2×f0。锚：Mohan Table IV 八角例 #55/#56"
    "（5.90/7.50nH）+用户实测参考 4.226/4.312nH（名义几何闭式 4.1147nH，"
    "+2.7%/+4.8%）",
    (("n_turns", "float 匝数 N（≥1；渲染取整，Mohan 拟合库允许分数）"),
     ("din_um", "float 内径 D_in（μm，>0——内圈最内缘跨面宽）"),
     ("w_um", "float 线宽 W（μm，>0）"),
     ("s_um", "float 匝间距 S（μm，>0）"),
     ("dout_um", "float 外径 D_out（μm，可选——缺省闭式导出 d_in+2nW+"
      "2(n−1)S；给出时与导出值一致性校验 >1% 即报错）"),
     ("t_um", "float 金属厚度（μm，>0，缺省 3.0 IPD 厚金档）"),
     ("rho_ohm_m", "float 金属电阻率（Ω·m，>0，缺省 2.44e-8 金）"),
     ("f0_ghz", "float 工作频率 GHz（>0，可选——给 c_par_ff 时评 SRF 门）"),
     ("c_par_ff", "float 寄生电容 C_par（fF，>0，可选——SRF=1/(2π√(LC))）"),
     ("reference_l_nh", "float L 参考基准（nH，>0，可选——±25% 判据，"
      "Mohan 闭式为基准侧/实测提取值喂本参数）"),
     ("include_esr", "bool True=附加 ESR(f0) 数值估计（趋肤+邻近，"
      "coil_esr 单源；缺省 False 只报 R_dc 一阶档）")),
    required=("n_turns", "din_um", "w_um", "s_um"),
)
def octagonal_spiral_inductance(
    n_turns: float,
    din_um: float,
    w_um: float,
    s_um: float,
    dout_um: float | None = None,
    t_um: float = T_UM_DEFAULT,
    rho_ohm_m: float = RHO_AU_IPD,
    f0_ghz: float | None = None,
    c_par_ff: float | None = None,
    reference_l_nh: float | None = None,
    include_esr: bool = False,
) -> dict[str, Any]:
    n = float(n_turns)
    din_m = float(din_um) * 1e-6
    w_m = float(w_um) * 1e-6
    s_m = float(s_um) * 1e-6
    t_m = float(t_um) * 1e-6
    rho = float(rho_ohm_m)
    if not (n >= 1.0):
        raise ValueError(f"octagonal_spiral_inductance: n_turns 须 ≥1，收到 {n_turns!r}")
    for name, v in (("din_um", din_um), ("w_um", w_um), ("s_um", s_um),
                    ("t_um", t_um), ("rho_ohm_m", rho)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(
                f"octagonal_spiral_inductance: {name} 须为正有限，收到 {v!r}")
    d_out_closed_m = din_m + 2.0 * n * w_m + 2.0 * (n - 1.0) * s_m
    if dout_um is not None:
        d_out_given_m = float(dout_um) * 1e-6
        if not (math.isfinite(d_out_given_m) and d_out_given_m > 0.0):
            raise ValueError(
                f"octagonal_spiral_inductance: dout_um 须为正有限，收到 {dout_um!r}")
        dev = abs(d_out_given_m - d_out_closed_m) / d_out_closed_m
        if dev > 0.01:
            raise ValueError(
                f"octagonal_spiral_inductance: dout_um={dout_um!r} 与闭式导出 "
                f"{d_out_closed_m * 1e6:.6g}μm 漂移 {dev * 100:.3f}%>1%"
                "（d_out=d_in+2nW+2(n−1)S，跨通道同语义 #154——检查参数）")
    geom = CoilGeometry("octagon", n, d_out_closed_m, w_m, s_m)
    geom.validate()   # d_in>0 可行性（圈数/线宽/间距过大显式拒绝）
    result = evaluate_coil(geom)
    l_main = result.l_h["current_sheet"]
    l_nh = {expr: val * 1e9 for expr, val in result.l_h.items()}
    r_dc = coil_track_dc_resistance(geom, t_m, resistivity_ohm_m=rho)
    track_len = _spiral_track_length_m(geom)
    out: dict[str, Any] = {
        "ok": True,
        "l_nh": {k: round(v, 6) for k, v in l_nh.items()},
        "l_main_nh": round(l_main * 1e9, 6),
        "l_main_expression": "current_sheet",
        "l_expressions_spread_pct": round(
            (max(l_nh.values()) - min(l_nh.values())) / min(l_nh.values())
            * 100.0, 4),
        "gmd_um": round(strip_gmd(w_m) * 1e6, 6),
        "geometry": {
            "shape": "octagon",
            "n_turns": n,
            "d_in_um": round(geom.d_in_m * 1e6, 6),
            "d_out_um": round(geom.d_out_m * 1e6, 6),
            "d_avg_um": round(result.d_avg_m * 1e6, 6),
            "fill_ratio": round(result.fill_ratio, 6),
            "w_um": float(w_um),
            "s_um": float(s_um),
            "track_length_mm": round(track_len * 1e3, 6),
        },
        "loss": {
            "r_dc_ohm": round(r_dc, 6),
            "t_um": float(t_um),
            "rho_ohm_m": rho,
            "model": "dc_first_order(uncalibrated)",
        },
        "gates": {},
        "source": _SOURCE,
    }
    if f0_ghz is not None:
        f0 = float(f0_ghz)
        if not (math.isfinite(f0) and f0 > 0.0):
            raise ValueError(
                f"octagonal_spiral_inductance: f0_ghz 须为正有限，收到 {f0_ghz!r}")
        out["q_dc_at_f0"] = round(
            2.0 * math.pi * f0 * 1e9 * l_main / r_dc, 4)
        if include_esr:
            esr = coil_esr_checked(geom, f0 * 1e9, t_m, rho)
            out["loss"]["esr_ohm"] = round(esr["esr_ohm"], 6)
            out["loss"]["esr_model"] = esr["model"]
            out["q_esr_at_f0"] = round(
                2.0 * math.pi * f0 * 1e9 * l_main / esr["esr_ohm"], 4)
    if c_par_ff is not None:
        c_par = float(c_par_ff)
        if not (math.isfinite(c_par) and c_par > 0.0):
            raise ValueError(
                f"octagonal_spiral_inductance: c_par_ff 须为正有限，收到 {c_par_ff!r}")
        srf_hz = 1.0 / (2.0 * math.pi * math.sqrt(l_main * c_par * 1e-15))
        out["srf_ghz"] = round(srf_hz * 1e-9, 6)
        out["c_par_ff"] = c_par
        if f0_ghz is not None:
            ratio = srf_hz / (float(f0_ghz) * 1e9)
            out["gates"]["srf_over_f0"] = {
                "ratio": round(ratio, 4),
                "limit": SRF_OVER_F0_LIMIT,
                "pass": ratio > SRF_OVER_F0_LIMIT,
            }
    if reference_l_nh is not None:
        ref = float(reference_l_nh)
        if not (math.isfinite(ref) and ref > 0.0):
            raise ValueError(
                f"octagonal_spiral_inductance: reference_l_nh 须为正有限，"
                f"收到 {reference_l_nh!r}")
        dev_pct = (ref - l_main * 1e9) / (l_main * 1e9) * 100.0
        out["gates"]["l_vs_reference"] = {
            "reference_l_nh": ref,
            "deviation_pct": round(dev_pct, 4),
            "limit_pct": L_GATE_LIMIT_PCT,
            "pass": abs(dev_pct) <= L_GATE_LIMIT_PCT,
        }
    return out


def coil_esr_checked(geom: CoilGeometry, f_hz: float, t_m: float,
                     rho: float) -> dict[str, Any]:
    """coil_esr 薄包（集总域守卫越界如实降级为 R_dc 档，不抛）。"""
    from rfauto.core.nfc_coil import coil_esr

    try:
        return coil_esr(geom, f_hz, t_m, resistivity_ohm_m=rho)
    except ValueError:
        # 集总域上限守卫（f>c/(10·n·(w+s))）：IPD µm 尺度 n·(w+s)≪λ 实际
        # 不触；触界属调用域异常——降级 R_dc 档如实标注
        r_dc = coil_track_dc_resistance(geom, t_m, resistivity_ohm_m=rho)
        return {"esr_ohm": r_dc, "model": "dc_fallback_lumped_domain_guard"}
