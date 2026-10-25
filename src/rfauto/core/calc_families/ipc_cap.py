"""IPD 电容 CALC 注册面（aurora_k K12，2026-10-23，用户反馈 F1）。

两键：``mim_capacitance``（MIM 平行板闭式，精确几何档）+
``interdigital_capacitance``（叉指 IDC sum-of-capacitances 一阶）——
GaAs 薄膜 IPD 工艺 W/L/D（全 μm 标量参数）→ C 报告 + 串联寄生
（R_s/L_s 一阶）+ SRF=1/(2π√(L_s·C)) 与 Q(f0) 一阶 + **质量门**
（反馈 F1 原文口径）：C 对闭式参考 ±25%（MIM 精确几何档）/
±50%（IDC 一阶模型档）、SRF>2×f0——门为确定性函数随结果透传
（ok=True + gates.pass 布尔，FAIL 如实呈现不抛异常，#122）。

**薄注册纪律**（spiral_inductor/deembed_metrics 同款）：物理数学单源在
``rfauto.core.ipc_cap``（MIM 平行板复用 core/package_interconnect.
mim_capacitance 教科书精确式零复制；IDC 侧壁 sum-of-capacitances 推导
式+精度声明+Greenhouse 齿排电感——来源与"不凭记忆写文献系数"纪律见
core/ipc_cap 模块头）——本模块只做 μm 参数（IPD 工艺口径）→ SI 装配
与门组装，零公式复制（#116 死副本教训）。

数值锚（#118 家法）：
- MIM：平行板缩放恒等式（C∝A、C∝1/d，test_package_interconnect 已
  钉）+ 手算值逐位回收（本席测试 nominal 档 132.8128fF）；
- IDC：侧壁主项分解逐项回收（合成参数→几何重算→与闭式一致，回收钉
  口径）+ 用户实测参考（反馈 F1 原文：K8 Z12 去嵌后 173.5fF）——名义
  档（n=24, lf=220, wf=sf=5, e_tip=15μm → l_c=205μm → 174.1fF）偏差
  +0.35%（±50% 门内；用户几何未给全，同量级参考对拍非逐位锚）。

真机验证留登记：openEMS/HFSS 对拍（含渲染零厚金属 vs CALC 侧壁 t_um
跨口径注记）待真机批（内部证据档）——本键 R/Q 为 DC 一阶档
（趋肤/邻近与衬底损耗未标定，如实声明）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.ipc_cap import (
    interdigital_bank_inductance_h,
    interdigital_capacitance_f,
    interdigital_series_resistance_ohm,
    mim_capacitance_report,
    mim_series_inductance_h,
    mim_series_resistance_ohm,
)

from .registry import register_calculator

__all__ = ["interdigital_capacitance", "mim_capacitance"]

_SOURCE = (
    "物理单源 core/ipc_cap（MIM 平行板=core/package_interconnect."
    "mim_capacitance 教科书精确式复用零复制；IDC 侧壁 sum-of-capacitances"
    " 推导式非文献转写+εeff=(1+εr)/2 半空间均匀化+Greenhouse 齿排电感"
    " 单源复用；精度声明见 core/ipc_cap 模块头）；本模块为薄注册包装"
    "（μm 参数装配+K12 质量门组装），公式零复制")

#: 金（IPD 电镀厚金工艺典型值，20°C；Ω·m——调用方可覆盖为 Cu/Al）
RHO_AU_IPD = 2.44e-8

#: IPD 金属厚度缺省（μm，厚金工艺典型档）
T_UM_DEFAULT = 3.0

#: MIM C 对闭式参考门限（反馈 F1 原文口径：精确几何档 ±25%）
MIM_GATE_LIMIT_PCT = 25.0

#: IDC C 对闭式参考门限（反馈 F1 原文口径：一阶模型档 ±50%）
IDC_GATE_LIMIT_PCT = 50.0

#: SRF 工作频率倍率门限（反馈 F1 原文口径：>2×f0）
SRF_OVER_F0_LIMIT = 2.0


@register_calculator(
    "mim_capacitance",
    "MIM 平行板电容闭式（μm 参数）：GaAs IPD 工艺 W/L/D/εr→C=ε0·εr·A/d"
    "（A=W·L 叠合面积，精确几何档）+面密度+双极板 R_s 与串联 L_s 一阶"
    "+SRF=1/(2π√(L_s·C))+Q(f0)；质量判据随结果透传：C 对 "
    "reference_c_ff ±25%、SRF>2×f0。锚：平行板缩放恒等式（C∝A、C∝1/d）"
    "+nominal 档手算回收 132.8128fF（20×20μm/0.2μm SiNx）",
    (("w_um", "float 上极板叠合区宽（μm，>0）"),
     ("l_um", "float 上极板叠合区长（μm，>0）"),
     ("d_um", "float 介质厚（μm，>0，SiNx 0.2μm 典型档）"),
     ("er_diel", "float 介质相对介电常数（>0，SiNx 7.5 典型档）"),
     ("t_um", "float 金属厚度（μm，>0，缺省 3.0 IPD 厚金档）"),
     ("rho_ohm_m", "float 金属电阻率（Ω·m，>0，缺省 2.44e-8 金）"),
     ("f0_ghz", "float 工作频率 GHz（>0，可选——评 Q 与 SRF 判据）"),
     ("reference_c_ff", "float C 参考基准（fF，>0，可选——±25% 判据，"
      "闭式为基准侧/实测提取值喂本参数）")),
    required=("w_um", "l_um", "d_um", "er_diel"),
)
def mim_capacitance(
    w_um: float,
    l_um: float,
    d_um: float,
    er_diel: float,
    t_um: float = T_UM_DEFAULT,
    rho_ohm_m: float = RHO_AU_IPD,
    f0_ghz: float | None = None,
    reference_c_ff: float | None = None,
) -> dict[str, Any]:
    w_m = float(w_um) * 1e-6
    l_m = float(l_um) * 1e-6
    d_m = float(d_um) * 1e-6
    t_m = float(t_um) * 1e-6
    rho = float(rho_ohm_m)
    for name, v in (("w_um", w_um), ("l_um", l_um), ("d_um", d_um),
                    ("er_diel", er_diel), ("t_um", t_um),
                    ("rho_ohm_m", rho)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(
                f"mim_capacitance: {name} 须为正有限，收到 {v!r}")
    rep = mim_capacitance_report(w_m, l_m, d_m, float(er_diel))
    c_f = float(rep["c_f"])
    r_s = mim_series_resistance_ohm(w_m, l_m, t_m, rho)
    l_ser = mim_series_inductance_h(w_m, l_m, d_m)
    srf_hz = 1.0 / (2.0 * math.pi * math.sqrt(max(l_ser * c_f, 1e-30)))
    out: dict[str, Any] = {
        "ok": True,
        "c_f": c_f,
        "c_ff": round(c_f * 1e15, 6),
        "c_density_ff_per_um2": round(float(rep["c_density_ff_per_mm2"])
                                      * 1e-6, 8),
        "geometry": {
            "w_um": float(w_um), "l_um": float(l_um), "d_um": float(d_um),
            "er_diel": float(er_diel),
            "overlap_area_um2": round(w_m * l_m * 1e12, 6),
        },
        "parasitics": {
            "r_s_ohm": round(r_s, 8),
            "l_ser_ph": round(l_ser * 1e12, 6),
            "model": "dc_first_order(uncalibrated)",
        },
        "srf_ghz": round(srf_hz * 1e-9, 4),
        "gates": {},
        "source": _SOURCE,
    }
    if f0_ghz is not None:
        f0 = float(f0_ghz)
        if not (math.isfinite(f0) and f0 > 0.0):
            raise ValueError(
                f"mim_capacitance: f0_ghz 须为正有限，收到 {f0_ghz!r}")
        out["q_at_f0"] = round(
            1.0 / (2.0 * math.pi * f0 * 1e9 * c_f * r_s), 4)
        ratio = srf_hz / (f0 * 1e9)
        out["gates"]["srf_over_f0"] = {
            "ratio": round(ratio, 4),
            "limit": SRF_OVER_F0_LIMIT,
            "pass": ratio > SRF_OVER_F0_LIMIT,
        }
    if reference_c_ff is not None:
        ref = float(reference_c_ff)
        if not (math.isfinite(ref) and ref > 0.0):
            raise ValueError(
                f"mim_capacitance: reference_c_ff 须为正有限，收到 {reference_c_ff!r}")
        dev_pct = (ref - c_f * 1e15) / (c_f * 1e15) * 100.0
        out["gates"]["c_vs_reference"] = {
            "reference_c_ff": ref,
            "deviation_pct": round(dev_pct, 4),
            "limit_pct": MIM_GATE_LIMIT_PCT,
            "pass": abs(dev_pct) <= MIM_GATE_LIMIT_PCT,
        }
    return out


@register_calculator(
    "interdigital_capacitance",
    "叉指 IDC 电容闭式（μm 参数）：GaAs IPD 工艺 N/L/W/S/e_tip→侧壁 "
    "sum-of-capacitances 一阶 C=(N−1)·ε0·εeff·t·l_c/s（l_c=L−e_tip 耦合"
    "长度，εeff=(1+εr)/2 半空间均匀化）+齿排 Greenhouse 并联电感与串联 "
    "R_s 一阶+SRF/Q；质量判据随结果透传：C 对 reference_c_ff ±50%、"
    "SRF>2×f0。精度类 ±50% 如实声明（槽平面/齿端边缘场省略→薄金属低估"
    "偏置；推导式非文献转写，不凭记忆写 Gevorgian 系数）。锚："
    "分解逐项回收钉+用户实测参考 173.5fF（名义档 174.1fF，+0.35%）",
    (("n_fingers", "int 总齿数 N（≥2 偶数——A/B 排各半）"),
     ("lf_um", "float 齿长 L（μm，>0）"),
     ("wf_um", "float 齿宽 W（μm，>0）"),
     ("sf_um", "float 齿间距 S（μm，>0）"),
     ("e_tip_um", "float B 排尖部外伸（μm，≥0——Clears 汇流排不产生相邻"
      "缝；耦合长度 l_c=lf−e_tip>0）"),
     ("t_um", "float 金属厚度（μm，>0，缺省 3.0 IPD 厚金档）"),
     ("er_sub", "float 衬底相对介电常数（>0，GaAs 12.9 典型档）"),
     ("rho_ohm_m", "float 金属电阻率（Ω·m，>0，缺省 2.44e-8 金）"),
     ("f0_ghz", "float 工作频率 GHz（>0，可选——评 Q 与 SRF 判据）"),
     ("reference_c_ff", "float C 参考基准（fF，>0，可选——±50% 判据，"
      "闭式为基准侧/实测提取值喂本参数）")),
    required=("n_fingers", "lf_um", "wf_um", "sf_um"),
)
def interdigital_capacitance(
    n_fingers: float,
    lf_um: float,
    wf_um: float,
    sf_um: float,
    e_tip_um: float = 0.0,
    t_um: float = T_UM_DEFAULT,
    er_sub: float = 12.9,
    rho_ohm_m: float = RHO_AU_IPD,
    f0_ghz: float | None = None,
    reference_c_ff: float | None = None,
) -> dict[str, Any]:
    lf_m = float(lf_um) * 1e-6
    wf_m = float(wf_um) * 1e-6
    sf_m = float(sf_um) * 1e-6
    e_tip_m = float(e_tip_um) * 1e-6
    t_m = float(t_um) * 1e-6
    rho = float(rho_ohm_m)
    n = float(n_fingers)
    if not (math.isfinite(n) and n >= 2.0 and n == int(n_fingers)
            and int(n_fingers) % 2 == 0):
        raise ValueError(
            f"interdigital_capacitance: n_fingers 须为 ≥2 偶数（A/B 排各"
            f"半），收到 {n_fingers!r}")
    for name, v in (("lf_um", lf_um), ("wf_um", wf_um), ("sf_um", sf_um),
                    ("t_um", t_um), ("er_sub", er_sub), ("rho_ohm_m", rho)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(
                f"interdigital_capacitance: {name} 须为正有限，收到 {v!r}")
    if not (math.isfinite(e_tip_m) and e_tip_m >= 0.0):
        raise ValueError(
            f"interdigital_capacitance: e_tip_um 须为非负有限，收到 {e_tip_um!r}")
    rep = interdigital_capacitance_f(int(n_fingers), lf_m, wf_m, sf_m,
                                     t_m, float(er_sub), e_tip_m=e_tip_m)
    c_f = float(rep["c_f"])
    n_a = (int(n_fingers) + 1) // 2
    n_b = int(n_fingers) // 2
    l_ser = (interdigital_bank_inductance_h(lf_m, wf_m, sf_m, t_m, n_a)
             + interdigital_bank_inductance_h(lf_m, wf_m, sf_m, t_m, n_b))
    w_bus_m = wf_m                       # 汇流排宽=齿宽（渲染派生值同语义）
    l_bus_m = int(n_fingers) * (wf_m + sf_m) - sf_m   # 汇流排跨全齿组
    r_s = interdigital_series_resistance_ohm(
        lf_m, wf_m, t_m, rho, int(n_fingers), w_bus_m, l_bus_m)
    srf_hz = 1.0 / (2.0 * math.pi * math.sqrt(max(l_ser * c_f, 1e-30)))
    out: dict[str, Any] = {
        "ok": True,
        "c_f": c_f,
        "c_ff": round(c_f * 1e15, 6),
        "decomposition": {
            "n_gap_pairs": int(rep["n_gap_pairs"]),
            "l_c_um": round(float(rep["l_c_m"]) * 1e6, 6),
            "eps_eff": round(float(rep["eps_eff"]), 6),
            "c_pair_ff": round(float(rep["c_pair_f"]) * 1e15, 6),
            "model": str(rep["model"]),
            "scope_note": str(rep["scope_note"]),
        },
        "geometry": {
            "n_fingers": int(n_fingers), "lf_um": float(lf_um),
            "wf_um": float(wf_um), "sf_um": float(sf_um),
            "e_tip_um": float(e_tip_um), "er_sub": float(er_sub),
        },
        "parasitics": {
            "r_s_ohm": round(r_s, 8),
            "l_ser_ph": round(l_ser * 1e12, 6),
            "model": "dc_first_order(uncalibrated)",
        },
        "srf_ghz": round(srf_hz * 1e-9, 4),
        "gates": {},
        "source": _SOURCE,
    }
    if f0_ghz is not None:
        f0 = float(f0_ghz)
        if not (math.isfinite(f0) and f0 > 0.0):
            raise ValueError(
                f"interdigital_capacitance: f0_ghz 须为正有限，收到 {f0_ghz!r}")
        out["q_at_f0"] = round(
            1.0 / (2.0 * math.pi * f0 * 1e9 * c_f * r_s), 4)
        ratio = srf_hz / (f0 * 1e9)
        out["gates"]["srf_over_f0"] = {
            "ratio": round(ratio, 4),
            "limit": SRF_OVER_F0_LIMIT,
            "pass": ratio > SRF_OVER_F0_LIMIT,
        }
    if reference_c_ff is not None:
        ref = float(reference_c_ff)
        if not (math.isfinite(ref) and ref > 0.0):
            raise ValueError(
                f"interdigital_capacitance: reference_c_ff 须为正有限，"
                f"收到 {reference_c_ff!r}")
        dev_pct = (ref - c_f * 1e15) / (c_f * 1e15) * 100.0
        out["gates"]["c_vs_reference"] = {
            "reference_c_ff": ref,
            "deviation_pct": round(dev_pct, 4),
            "limit_pct": IDC_GATE_LIMIT_PCT,
            "pass": abs(dev_pct) <= IDC_GATE_LIMIT_PCT,
        }
    return out
