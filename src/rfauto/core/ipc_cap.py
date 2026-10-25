"""IPD 电容物理单源（aurora_k K12，反馈 F1：MIM+叉指 IDC）。

GaAs 薄膜 IPD 工艺两类集总电容的闭式评估内核（CALC 键
``mim_capacitance``/``interdigital_capacitance`` 与 oe/fake 通道共用的
物理单源；本模块只放公式与一阶估计，μm 参数装配与质量门在
core/calc_families/ipc_cap 薄注册面——deembed_metrics 同款分层）。

**闭式来源与精度声明（#118 家法：不凭记忆写文献系数）**：

出处：MIM=平行板精确式 C=ε0·εr·A/d（教科书式，单源复用
  core/package_interconnect.mim_capacitance 零公式复制）；IDC=相邻
  齿对**侧壁平行板主项**的几何恒等式推导（非文献转写）+εeff=(1+εr)/2
  衬底半空间均匀化（nfc_coil 匝间寄生同款推导类）；Gevorgian 1996
  级 even/odd 模精确式**未入库**——分项声明见下。

- **MIM**：平行板 C=ε0·εr·A/d（A=上极板重叠面积，d=介质厚）——教科书
  精确式，**单源复用 core/package_interconnect.mim_capacitance（零公式
  复制，#116）**；边缘场 O(d/√A) 偏差如实声明（该单源已声明"不引入未
  核修正系数"，本模块沿袭——可选修正一律不做凭记忆式）。串联寄生：
  - R_s：双极板 DC 电阻一阶（电流自端口边摊开，平均路径 l/2/板，
    R=ρ·l/(t·w) 双板串联合计；趋肤/邻近不在内，coil_esr 同类声明）；
  - L_s：平行板线电感 L'=μ0·d/w（Ampère 定律宽板精确、边缘场忽略，
    可推导不转写）×回路路径长 l（上/下板各 l/2 平均）→ L=μ0·d·l/w
    ——一阶估计，端口引线/馈线电感不在内（如实）。
- **叉指 IDC**：sum-of-capacitances 一阶模型——(n−1) 个相邻齿对的
  **侧壁平行板主项** C=(n−1)·ε0·εeff·t·l_c/s（面对面积 t·l_c、间距 s
  的几何恒等式推导，非文献转写；εeff=(1+εr)/2 衬底半空间均匀化——
  nfc_coil.winding_parasitic_capacitance_f 同款推导类）。
  **如实声明**：①槽平面（共面缝）场与齿端边缘场为同阶省略项，薄金属
  （t/s 小）时模型**系统性低估**（趋近零厚极限时侧壁项→0 而槽平面场
  有限）；②Gevorgian 1996 级 even/odd 模精确式未入库（原文数表未逐位
  核对，K11 教训不凭记忆写系数）——精度类 **±50%**（反馈 F1 原文质量
  门口径），用户实测 173.5fF 作同量级参考锚（非逐位）。
- **IDC 串联寄生 L**：齿排并联电感一阶（Greenhouse 自感+同排最近邻
  互感/equal-current 并联合成，core/package_interconnect 单源复用）；
  汇流排与齿根电流不均匀为一阶省略项（如实）。

守卫纪律：全部输入正有限显式拒绝；l_c=lf−e_tip>0、n≥2（至少一对齿）
等几何可行性 fail-fast。
"""

from __future__ import annotations

import math

__all__ = [
    "EPS0",
    "MU0",
    "interdigital_bank_inductance_h",
    "interdigital_capacitance_f",
    "interdigital_series_resistance_ohm",
    "mim_capacitance_report",
    "mim_series_inductance_h",
    "mim_series_resistance_ohm",
]

#: 真空介电常数（CODATA 精确值，F/m）——与 package_interconnect 同值口径
EPS0 = 8.854187817e-12
#: 真空磁导率（精确值，H/m）
MU0 = 4.0e-7 * math.pi


# ─── MIM：平行板 + 一阶串联寄生 ──────────────────────────────────────────────

def mim_capacitance_report(w_m: float, l_m: float, d_m: float,
                           er_diel: float) -> dict[str, float | str]:
    """MIM 平行板电容报告（单源复用 core/package_interconnect）。

    C=ε0·εr·A/d（A=w·l 上极板重叠面积，d=介质厚）；边缘场 O(d/√A)
    如实声明。返回 c_f/c_ff/c_density 与 scope_note（包内单源透传）。
    """
    from rfauto.core.package_interconnect import mim_capacitance

    for name, v in (("w_m", w_m), ("l_m", l_m), ("d_m", d_m),
                    ("er_diel", er_diel)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(f"mim_capacitance_report: {name} 须为正有限，"
                             f"收到 {v!r}")
    return mim_capacitance(w_m * l_m, d_m, er_diel)


def mim_series_resistance_ohm(w_m: float, l_m: float, t_m: float,
                              rho_ohm_m: float) -> float:
    """MIM 双极板串联 DC 电阻一阶（Ω）。

    电流自端口边摊开（1 端口边馈口径）：每板平均路径 l/2、截面 t·w →
    每板 R=ρ·(l/2)/(t·w)，双板串联合计 R=ρ·l/(t·w)。**一阶声明**：
    均匀电流摊开假设（实际集边效应增 R）；趋肤不在内（DC 档，
    coil_track_dc_resistance 同类）。
    """
    for name, v in (("w_m", w_m), ("l_m", l_m), ("t_m", t_m),
                    ("rho_ohm_m", rho_ohm_m)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(f"mim_series_resistance_ohm: {name} 须为正有限，"
                             f"收到 {v!r}")
    return rho_ohm_m * l_m / (t_m * w_m)


def mim_series_inductance_h(w_m: float, l_m: float, d_m: float) -> float:
    """MIM 串联寄生电感一阶（H）。

    平行板线单位长电感 L'=μ0·d/w（Ampère 定律：板间 B=μ0·I/w，链通量
    /I = μ0·d/w——宽板精确、边缘场忽略，可推导非转写）；电流回路路径：
    上板自端口边平均 l/2 + 下板返回平均 l/2 = l → L=μ0·d·l/w。
    **一阶声明**：均匀摊开假设；端口引线/馈线电感不在内（SRF 评估时
    属保守低估侧——真 L 更大则 SRF 更低，门判读留真机批）。
    """
    for name, v in (("w_m", w_m), ("l_m", l_m), ("d_m", d_m)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(f"mim_series_inductance_h: {name} 须为正有限，"
                             f"收到 {v!r}")
    return MU0 * d_m * l_m / w_m


# ─── 叉指 IDC：sum-of-capacitances 一阶 + 串联寄生 ──────────────────────────

def interdigital_eps_eff(er_sub: float) -> float:
    """叉指缝有效介电常数（衬底半空间均匀化）：εeff=(1+εr)/2。

    共面缝场一半入空气一半入衬底的一阶口径（nfc_coil 匝间寄生
    winding_parasitic_capacitance_f 同款推导类）；薄衬底/厚金属叠层
    修正不在内（如实）。
    """
    if not (math.isfinite(float(er_sub)) and float(er_sub) > 0.0):
        raise ValueError(f"interdigital_eps_eff: er_sub 须为正有限，"
                         f"收到 {er_sub!r}")
    return 0.5 * (1.0 + float(er_sub))


def interdigital_capacitance_f(n_fingers: int, lf_m: float, wf_m: float,
                               sf_m: float, t_m: float, er_sub: float,
                               e_tip_m: float = 0.0) -> dict[str, float | str]:
    """叉指 IDC 电容 sum-of-capacitances 一阶（F）与分解报告。

    模型（推导式，非文献转写——来源声明见模块头）::

        C ≈ (n−1) · ε0 · εeff · t · l_c / s

    - n=n_fingers 总齿数，相邻异排齿对数=n−1（每缝计一次）；
    - l_c=lf−e_tip 耦合长度（e_tip=B 齿越过 A 齿端的尖部外伸——跨过
      对排齿端的延伸段不产生相邻缝，不进主项）；
    - εeff=(1+εr)/2（:func:`interdigital_eps_eff` 半空间均匀化）。

    **精度类 ±50% 如实声明**（反馈 F1 原文门口径）：侧壁平行板主项为
    缝电容的下界口径——槽平面（共面缝）场与齿端边缘场同阶省略，薄金属
    （t/s→0）时低估加重；Gevorgian 1996 even/odd 精确式未入库（K11
    教训：原文数表未逐位核对不凭记忆写系数）。用户实测 173.5fF 作
    同量级参考（名义档几何量级对拍，非逐位锚）。
    """
    n = int(n_fingers)
    if n != n_fingers or n < 2:
        raise ValueError(
            f"interdigital_capacitance_f: n_fingers 须为 ≥2 整数，收到 "
            f"{n_fingers!r}")
    for name, v in (("lf_m", lf_m), ("wf_m", wf_m), ("sf_m", sf_m),
                    ("t_m", t_m), ("er_sub", er_sub)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(f"interdigital_capacitance_f: {name} 须为正有限，"
                             f"收到 {v!r}")
    if not (math.isfinite(float(e_tip_m)) and float(e_tip_m) >= 0.0):
        raise ValueError(f"interdigital_capacitance_f: e_tip_m 须为非负有限，"
                         f"收到 {e_tip_m!r}")
    l_c = float(lf_m) - float(e_tip_m)
    if l_c <= 0.0:
        raise ValueError(
            f"interdigital_capacitance_f: 耦合长度 l_c=lf−e_tip={l_c!r} ≤0"
            "（e_tip ≥ lf 几何不可行）")
    if float(e_tip_m) >= float(lf_m):
        raise ValueError(
            f"interdigital_capacitance_f: e_tip={e_tip_m!r} ≥ lf={lf_m!r}"
            "（尖部外伸不得超过齿长）")
    eps_eff = interdigital_eps_eff(er_sub)
    c_pair = EPS0 * eps_eff * t_m * l_c / float(sf_m)
    c_f = (n - 1) * c_pair
    return {
        "c_f": c_f,
        "c_ff": c_f * 1e15,
        "c_pair_f": c_pair,
        "n_gap_pairs": n - 1,
        "l_c_m": l_c,
        "eps_eff": eps_eff,
        "model": "sidewall_parallel_plate_sum_first_order",
        "scope_note": "±50% 精度类（槽平面/齿端边缘场省略→薄金属低估偏置；"
                      "推导式非文献转写，来源声明见 core/ipc_cap 模块头）",
    }


def interdigital_bank_inductance_h(lf_m: float, wf_m: float, sf_m: float,
                                   t_m: float, n_bank: int) -> float:
    """单排齿组并联电感一阶（H，IDC 串联寄生 L 估计用）。

    n_bank 根平行同向齿（equal-current 并联合成）：L_eff=(L_self+ΣM)/n
    ——L_self=Greenhouse/Grover 矩形截面直段自感、M=等长平行段互感
    （**同排最近邻对**，齿距 2(wf+sf)——跨过一个对排齿；core/
    package_interconnect 两单源复用零公式复制）。**一阶声明**：最近邻
    互感截断（次邻互感 O(ln2) 级省略）、电流均匀分配假设、汇流排电感
    不在内（如实）。
    """
    from rfauto.core.package_interconnect import (
        gmd_equal_strips,
        greenhouse_mutual_equal_length_h,
        greenhouse_segment_self_h,
    )

    n = int(n_bank)
    if n != n_bank or n < 1:
        raise ValueError(
            f"interdigital_bank_inductance_h: n_bank 须为 ≥1 整数，收到 "
            f"{n_bank!r}")
    for name, v in (("lf_m", lf_m), ("wf_m", wf_m), ("sf_m", sf_m),
                    ("t_m", t_m)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(
                f"interdigital_bank_inductance_h: {name} 须为正有限，收到 {v!r}")
    l_self = greenhouse_segment_self_h(float(lf_m), float(wf_m), float(t_m))
    if n == 1:
        return l_self
    # 同排最近邻间距=2(wf+sf)（跨过一个对排齿）；GMD 用等宽带单源
    spacing = 2.0 * (float(wf_m) + float(sf_m))
    gmd = gmd_equal_strips(float(wf_m), spacing)
    m_nn = greenhouse_mutual_equal_length_h(float(lf_m), gmd)
    return (l_self + (n - 1) * m_nn) / n


def interdigital_series_resistance_ohm(lf_m: float, wf_m: float, t_m: float,
                                       rho_ohm_m: float, n_fingers: int,
                                       w_bus_m: float, l_bus_m: float) -> float:
    """IDC 双排串联 DC 电阻一阶（Ω）。

    齿排：n_bank 根齿并联（每根 l_f 长、截面 t·w_f，等流分配）→
    R_bank=ρ·l_f/(t·w_f·n_bank)；双排串联 + 两根汇流排（各长 l_bus、
    宽 w_bus）串联。**一阶声明**：等流分配假设（齿根渐缩实际略偏）；
    DC 档趋肤不在内（如实）。
    """
    n = int(n_fingers)
    if n != n_fingers or n < 2:
        raise ValueError(
            f"interdigital_series_resistance_ohm: n_fingers 须为 ≥2 整数，"
            f"收到 {n_fingers!r}")
    for name, v in (("lf_m", lf_m), ("wf_m", wf_m), ("t_m", t_m),
                    ("rho_ohm_m", rho_ohm_m), ("w_bus_m", w_bus_m),
                    ("l_bus_m", l_bus_m)):
        if not (math.isfinite(float(v)) and float(v) > 0.0):
            raise ValueError(
                f"interdigital_series_resistance_ohm: {name} 须为正有限，"
                f"收到 {v!r}")
    n_a = (n + 1) // 2          # A 排齿数（含首根）
    n_b = n // 2                # B 排齿数
    r_finger = rho_ohm_m * lf_m / (t_m * wf_m)
    r_bank = r_finger / n_a + r_finger / n_b
    r_bus = 2.0 * rho_ohm_m * l_bus_m / (t_m * w_bus_m)
    return r_bank + r_bus
