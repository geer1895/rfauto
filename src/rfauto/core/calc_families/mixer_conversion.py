"""混频器变换面（架构批 W2-S6 席域，R2_core_tier3 §③ D2 立项）。

三键：mixer_ssb_nf（镜像噪声折入 SSB-NF 链路口径）/ mixer_conversion_loss
（变频损耗 SSB/DSB 口径换算+无源混频噪声地板）/ mixer_image_plan（镜像
频率规划+IQ 失衡 IRR 同式复算）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **镜像噪声折入（image noise fold）**：混频器 DSB 噪声系数按"两信号边带
  都载信号功率"定义，源噪声两带同温 T0 注入；SSB 口径只有单边带载信号，
  镜像带源噪声经变频折入中频。设镜像支路相对信号支路的电压增益比
  g=10^(−IR/10)（IR=镜像抑制度 dB）、镜像带源温度比 t=T_im/T0，混频器
  内部噪声两支路同贡献（教科书等噪声口径），则输出噪声

      N_out = kT0B·G_s·F_m + k·t·T0·B·G_i·F_m + N_int
      F_DSB = N_out/((G_s+G_i)kT0B)，F_SSB = N_out/(G_s·kT0B)

  两式消 N_int 与 F_m 得精确恒等式（t=1 时对 F_m 无假设依赖）：

      **F_SSB = (1 + g·t)·F_DSB**

  t=1（镜像带同温注入，无前选滤除经典口径）：IR=0 → F_SSB=2·F_DSB，
  即 **NF_SSB = NF_DSB + 3.0103 dB** 教科书 3dB 折入极限；IR→∞ 或
  t→0（镜像滤除/冷镜像）→ 折入归零。t≠1 时本键按镜像支路与信号支路
  同噪声贡献 F_m=F_DSB 假设闭合为 F_SSB=(1+g·t)·F_DSB（假设如实注记，
  t=1 档不受该假设影响）。
- **变频损耗 SSB/DSB 口径**：CL_SSB=单边带射频功率/中频功率（器件
  手册惯例）；DSB 口径两带都载信号 → 总信号功率×2 → 增益 +3.0103 dB
  （CL_DSB = CL_SSB − 3.0103 dB，等分恒等式）。
- **无源混频噪声地板**（理想无源变频+镜像带同温注入）：器件本身处于
  温度 T0 热平衡，输出可用噪声=kT0B，与衰减器同构——F_DSB=CL_lin/2、
  F_SSB=CL_lin，即 **NF_SSB(理想无源) = CL_SSB**（与 mixer_ssb_nf 键
  以 nf_dsb=CL_SSB−3.0103、IR=0 互证：F_SSB=2·(CL_lin/2)=CL_lin，
  同族跨键双源）。真实有源/二极管混频器的 NF 高于该地板，超出量=器件
  质量指标（手册如实）。
- **镜像规划**：低本振（f_LO<f_RF）镜像 f_im=f_LO−f_IF、高本振
  f_im=f_LO+f_IF，镜像距信号 **2·f_IF**（预选滤波器设计依据）；本振
  偏移 Δf_LO → 中频 1:1 平移（d f_IF/d f_LO=±1 恒等）。
- **IQ 失衡→IRR**：Razavi 式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)
  （ε=10^(a/20)、φ=正交相位误差）——与 calc_families.rx_impairments
  iq_imbalance_irr 同式，本模块独立复算（#118 同仓双源，测试互证）。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- cascade_budget/spur_search/if_plan_sweep=级联聚总与**杂散面**
  （m·f_RF±n·f_LO 乘积域）、block_cfg 的 BlockSpec.conversion_loss_db=
  模型层参数槽——本族只做**变换损耗+镜像噪声记账+镜像几何规划**。
- iq_imbalance_irr=IRR/EVM/blocking 损伤面——IRR 同式独立复算互证，
  不重写其 EVM/blocking 消费面。
- pa_arch multiplier_chain_budget=倍频链（谐波倍乘域）不撞。

出处
----
- D. M. Pozar, Microwave Engineering 4th ed. Ch.12（混频器噪声系数
  DSB/SSB 口径与镜像噪声折入；章节号以版次为准）。
- B. Razavi, RF Microelectronics 2nd ed. Ch.8（IQ 失衡 IRR 式，与
  rx_impairments 同源二级转引）。
- 教科书口径：NF_SSB=NF_DSB+3dB 理想镜像无抑制极限、无源混频
  NF=变频损耗（同温双带注入），等噪声贡献假设随 t≠1 档如实注记。

守卫：nf_dsb_db/转换损耗有限且 ≥0；image_rejection_db ≥0（None=完美
镜像抑制）；t_image_ratio ∈[0,1]；频率 >0 且 f_RF≠f_LO（零中频镜像=
信号本身，超外差口径显式拒绝）；失衡 ε>0；越界一律显式 ValueError。

出处（Pozar《Microwave Engineering》4th ed. Ch.12；Razavi）：
- mixer_ssb_nf/mixer_conversion_loss/mixer_image_plan：混频器 DSB/SSB
  噪声口径与镜像噪声折入=Pozar 4th ed. Ch.12（F_SSB=(1+g·t)·F_DSB
  恒等式全推导在模块 docstring；3.0103dB 极限逐位测试钉）；IRR 式=
  Razavi《RF Microelectronics》2nd ed. Ch.8（rx_impairments 同仓双源
  独立复算互证）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "mixer_conversion_loss",
    "mixer_image_plan",
    "mixer_ssb_nf",
]

_T0_K = 290.0
_SSB_DSB_SPLIT_DB = 10.0 * math.log10(2.0)   # 3.0102999566398120


def _ir_to_gain(image_rejection_db: float | None) -> float | None:
    """镜像抑制度 dB → 电压/功率共用的线性增益比 g=10^(−IR/10)。"""
    if image_rejection_db is None:
        return None
    ir = _finite(image_rejection_db, "image_rejection_db")
    if ir < 0.0:
        raise ValueError(
            f"image_rejection_db 必须 ≥0（负值=镜像增益，非抑制度），"
            f"得到 {image_rejection_db!r}")
    return 10.0 ** (-ir / 10.0)


# ─── 键 1：mixer_ssb_nf（镜像噪声折入 SSB-NF 链路口径）───────────────────────

@register_calculator(
    "mixer_ssb_nf",
    "混频器镜像噪声折入：NF_DSB → NF_SSB 链路口径换算。镜像支路增益比 "
    "g=10^(−IR/10)、镜像带源温度比 t=T_im/T0，等噪声贡献口径下精确恒等式 "
    "F_SSB=(1+g·t)·F_DSB（Pozar Ch.12 口径）：IR=0 且 t=1（镜像带同温注入"
    "无前选滤除）→ NF_SSB=NF_DSB+3.0103dB 教科书 3dB 折入极限；IR→∞ "
    "（None=完美镜像抑制）或 t=0（镜像滤除/冷镜像）→ 折入归零。t≠1 档按 "
    "镜像支路与信号支路同噪声贡献假设闭合（如实注记，t=1 档不受影响）。"
    "输出含折入 dB/噪声温度面。锚：3dB 极限逐位、恒等式测试侧独立重算、"
    "双极限回收",
    (("nf_dsb_db", "float dB 混频器 DSB 噪声系数（≥0；器件手册 DSB 口径）"),
     ("image_rejection_db", "float dB 镜像抑制度（≥0，缺省 0=无抑制双带同温"
      "经典口径；None=完美镜像抑制）"),
     ("t_image_ratio", "float 镜像带源温度比 T_im/T0（∈[0,1]，缺省 1=同温"
      "注入；0=镜像滤除/冷镜像）")),
    required=("nf_dsb_db",),
)
def mixer_ssb_nf(nf_dsb_db: float,
                 image_rejection_db: float | None = 0.0,
                 t_image_ratio: float = 1.0) -> dict[str, Any]:
    nf_dsb = _finite(nf_dsb_db, "nf_dsb_db")
    if nf_dsb < 0.0:
        raise ValueError(
            f"mixer_ssb_nf: nf_dsb_db 必须 ≥0（噪声系数非负），得到 {nf_dsb!r}")
    g = _ir_to_gain(image_rejection_db)
    t_im = _finite(t_image_ratio, "t_image_ratio")
    if not 0.0 <= t_im <= 1.0:
        raise ValueError(
            f"mixer_ssb_nf: t_image_ratio 须 ∈[0,1]（镜像带源温度比），"
            f"得到 {t_image_ratio!r}")
    g_eff = 0.0 if g is None else g
    fold_factor = 1.0 + g_eff * t_im
    f_dsb = 10.0 ** (nf_dsb / 10.0)
    f_ssb = fold_factor * f_dsb
    nf_ssb_db = 10.0 * math.log10(f_ssb)
    fold_db = 10.0 * math.log10(fold_factor)
    # 恒等式自检（构造恒满足，残差随值并列报告；#364④ is-not-None 显式判缺）
    recompute = 10.0 * math.log10((1.0 + g_eff * t_im)
                                  * 10.0 ** (nf_dsb / 10.0))
    residual = abs(recompute - nf_ssb_db)
    return {
        "nf_dsb_db": nf_dsb,
        "image_rejection_db": image_rejection_db,
        "t_image_ratio": t_im,
        "image_gain_ratio": None if g is None else round(g, 18),
        "fold_factor": round(fold_factor, 18),
        "fold_db": round(fold_db, 15),
        "nf_ssb_db": round(nf_ssb_db, 15),
        "f_dsb_linear": round(f_dsb, 18),
        "f_ssb_linear": round(f_ssb, 18),
        "t_dsb_k": round(_T0_K * (f_dsb - 1.0), 15),
        "t_ssb_k": round(_T0_K * (f_ssb - 1.0), 15),
        "fold_residual_db": round(residual, 18),
        "note": (
            "t=1 档恒等式 F_SSB=(1+g)·F_DSB 对镜像/信号支路噪声分配无假设"
            "依赖（消元精确）；t≠1 档按镜像支路同噪声贡献 F_m=F_DSB 假设"
            "闭合，实际器件以手册 SSB 实测为准（如实注记）；fold 只计镜像"
            "带源噪声折入——LO 相噪侧边带混频（倒易混频）走 blocking_budget "
            "面不在此层"),
        "source": (
            "Pozar Microwave Engineering Ch.12 混频器 DSB/SSB 噪声口径与"
            "镜像噪声折入；恒等式 F_SSB=(1+g·t)·F_DSB 为本席按输出噪声"
            "记账推导（t=1 精确、t≠1 含等噪声贡献假设如实登记）"),
    }


# ─── 键 2：mixer_conversion_loss（变频损耗 SSB/DSB 口径）────────────────────

@register_calculator(
    "mixer_conversion_loss",
    "混频器变频损耗 SSB/DSB 口径换算：CL_SSB=单边带射频/中频（手册惯例）"
    "→ 增益 gain_ssb_db=−CL_SSB；DSB 口径两带载信号总功率×2 → "
    "gain_dsb_db=gain_ssb_db+3.0103（CL_DSB=CL_SSB−3.0103 等分恒等式）。"
    "无源混频噪声地板（镜像带同温注入、器件 T0 热平衡与衰减器同构）："
    "NF_DSB_floor=CL_SSB−3.0103、NF_SSB_floor=CL_SSB（与 mixer_ssb_nf "
    "键跨键互证口径）；真实混频器 NF 高于地板、超出量=器件质量。可选 "
    "IIP3 → OIP3=IIP3−CL 线性级联口径。锚：+3.0103 等分恒等式逐位、"
    "地板跨键互证、OIP3 恒等式",
    (("conversion_loss_ssb_db", "float dB 变频损耗 SSB 口径（≥0；0=理想"
      "无耗变频）"),
     ("iip3_dbm", "float dBm 输入三阶交调点（可选；给了才输出 OIP3 面）")),
    required=("conversion_loss_ssb_db",),
)
def mixer_conversion_loss(conversion_loss_ssb_db: float,
                          iip3_dbm: float | None = None) -> dict[str, Any]:
    cl_ssb = _finite(conversion_loss_ssb_db, "conversion_loss_ssb_db")
    if cl_ssb < 0.0:
        raise ValueError(
            "mixer_conversion_loss: conversion_loss_ssb_db 必须 ≥0（变频"
            f"损耗非负；负值=变频增益请先换算口径），得到 {cl_ssb!r}")
    gain_ssb_db = -cl_ssb
    gain_dsb_db = gain_ssb_db + _SSB_DSB_SPLIT_DB
    cl_dsb_db = cl_ssb - _SSB_DSB_SPLIT_DB
    gain_ssb_lin = 10.0 ** (gain_ssb_db / 10.0)
    # 无源混频噪声地板（镜像带同温注入）：F_SSB=CL_lin、F_DSB=CL_lin/2
    nf_floor_ssb_db = cl_ssb
    nf_floor_dsb_db = cl_ssb - _SSB_DSB_SPLIT_DB
    oip3_dbm = None
    if iip3_dbm is not None:
        iip3 = _finite(iip3_dbm, "iip3_dbm")
        oip3_dbm = round(iip3 - cl_ssb, 15)
    return {
        "conversion_loss_ssb_db": cl_ssb,
        "conversion_loss_dsb_db": round(cl_dsb_db, 15),
        "gain_ssb_db": round(gain_ssb_db, 15),
        "gain_dsb_db": round(gain_dsb_db, 15),
        "gain_ssb_linear": round(gain_ssb_lin, 18),
        "split_db": round(_SSB_DSB_SPLIT_DB, 15),
        "nf_floor_ssb_db": round(nf_floor_ssb_db, 15),
        "nf_floor_dsb_db": round(nf_floor_dsb_db, 15),
        "iip3_dbm": iip3_dbm,
        "oip3_dbm": oip3_dbm,
        "note": (
            "无源混频噪声地板口径=器件 T0 热平衡+镜像带同温注入（与衰减器"
            "同构）：NF_SSB_floor=CL_SSB、NF_DSB_floor=CL_SSB−3.0103；"
            "有源/二极管混频器 NF 高于地板，超出量=器件品质以手册为准；"
            "DSB 增益口径=两带总信号功率口径（等分 +3.0103dB），非单带"
            "功率口径——级联记账按单带口径走 gain_ssb_db"),
        "source": (
            "变频损耗 SSB/DSB 等分恒等式与无源混频 NF=CL 地板为教科书口径"
            "（Pozar Ch.12；无源器件同温热平衡输出噪声=kT0B），地板跨键"
            "与 mixer_ssb_nf 互证（F_SSB=2·F_DSB=CL_lin 逐位闭合）"),
    }


# ─── 键 3：mixer_image_plan（镜像频率规划 + IQ 失衡 IRR）────────────────────

@register_calculator(
    "mixer_image_plan",
    "混频器镜像规划：f_IF=|f_RF−f_LO|，低本振（f_LO<f_RF）镜像 "
    "f_im=f_LO−f_IF、高本振 f_im=f_LO+f_IF，镜像距信号 2·f_IF（预选滤波"
    "器设计依据）；本振偏移 Δf_LO → 中频 1:1 平移（df_IF/df_LO=±1 恒等）。"
    "可选 IQ 失衡 → 镜像抑制比 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ) "
    "（Razavi 式，ε=10^(a/20)；ε=1 退化 cot²(φ/2)）——与 iq_imbalance_irr "
    "同式独立复算（同仓双源）。f_RF=f_LO（零中频，镜像=信号本身）显式"
    "拒绝。锚：2·f_IF 间距恒等、IRR 与既有键逐位互证",
    (("f_rf_hz", "float Hz 射频频率（>0）"),
     ("f_lo_hz", "float Hz 本振频率（>0；=f_RF 显式拒绝）"),
     ("amp_imbalance_db", "float dB I/Q 增益失衡（可选；同值异号 IRR 相同）"),
     ("phase_imbalance_deg", "float deg 正交相位误差（可选；须与增益失衡"
      "同给）")),
    required=("f_rf_hz", "f_lo_hz"),
)
def mixer_image_plan(f_rf_hz: float, f_lo_hz: float,
                     amp_imbalance_db: float | None = None,
                     phase_imbalance_deg: float | None = None) -> dict[str, Any]:
    f_rf = _finite(f_rf_hz, "f_rf_hz")
    f_lo = _finite(f_lo_hz, "f_lo_hz")
    if f_rf <= 0.0 or f_lo <= 0.0:
        raise ValueError(
            "mixer_image_plan: f_rf_hz/f_lo_hz 必须 >0，得到 "
            f"({f_rf!r}, {f_lo!r})")
    if f_rf == f_lo:
        raise ValueError(
            "mixer_image_plan: f_rf_hz=f_lo_hz 为零中频（镜像=信号本身，"
            "镜像规划退化），本键超外差口径显式拒绝")
    f_if = abs(f_rf - f_lo)
    low_side = f_lo < f_rf
    f_image = f_lo - f_if if low_side else f_lo + f_if
    if f_image <= 0.0:
        raise ValueError(
            f"mixer_image_plan: 镜像频率 {f_image!r} Hz ≤0（低本振且 "
            "f_LO<f_IF 半中频域），无物理镜像面，显式拒绝")
    irr_db = None
    if amp_imbalance_db is not None or phase_imbalance_deg is not None:
        if amp_imbalance_db is None or phase_imbalance_deg is None:
            raise ValueError(
                "mixer_image_plan: amp_imbalance_db 与 phase_imbalance_deg "
                "必须同给（IRR 两参数齐备），显式拒绝")
        a_db = _finite(amp_imbalance_db, "amp_imbalance_db")
        phi_deg = _finite(phase_imbalance_deg, "phase_imbalance_deg")
        if abs(phi_deg) > 180.0:
            raise ValueError(
                "mixer_image_plan: phase_imbalance_deg |φ|≤180（与 "
                "iq_imbalance_irr 同口径），得到 " f"{phi_deg!r}")
        eps = 10.0 ** (a_db / 20.0)
        phi = math.radians(phi_deg)
        denom = 1.0 + eps * eps - 2.0 * eps * math.cos(phi)
        # 完全反相（0dB+±180°）信号支路零输出 → IRR 无界走 None
        irr_db = None if denom <= 0.0 else 10.0 * math.log10(
            (1.0 + eps * eps + 2.0 * eps * math.cos(phi)) / denom)
    return {
        "f_rf_hz": f_rf,
        "f_lo_hz": f_lo,
        "f_if_hz": round(f_if, 15),
        "injection_side": "low" if low_side else "high",
        "f_image_hz": round(f_image, 15),
        "image_offset_hz": round(2.0 * f_if, 15),
        "lo_offset_sensitivity": 1.0,
        "amp_imbalance_db": amp_imbalance_db,
        "phase_imbalance_deg": phase_imbalance_deg,
        "irr_db": None if irr_db is None else round(irr_db, 15),
        "note": (
            "镜像距信号 2·f_IF 为预选滤波器滚降设计依据；本振偏移 1:1 平移"
            "中频（锁相环相噪→中频抖动同权）；IRR 与 iq_imbalance_irr 同式"
            "独立复算（同仓双源互证）；低本振 f_LO<f_IF 时镜像落负频轴"
            "（无物理镜像面）显式拒绝"),
        "source": (
            "镜像几何 f_im=f_LO∓f_IF、间距 2f_IF 为超外差教科书口径"
            "（Pozar Ch.12）；IRR=Razavi RF Microelectronics Ch.8 同式"
            "（二级转引，与 calc_families.rx_impairments 同源）"),
    }
