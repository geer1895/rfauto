"""PCB 无源/互连 RLC 闭式锚。

定位（对照电-热链的 1-D 传导锚）：Q3D/SIwave 寄生提取通道的**裁判内核**。
Q3D 数值提取出的每单位长度 L/C 与总 R，须对独立来源闭式解校验：

- **L/C 锚（传输线恒等式，给定 Z0/εeff 后精确成立）**：
  微带准 TEM 满足 Z0 = sqrt(L/C)、相速 v_p = c0/sqrt(εeff) = 1/sqrt(LC)，
  联立解得 L = Z0·sqrt(εeff)/c0、C = sqrt(εeff)/(Z0·c0)。Z0/εeff 取
  core/synthesis.forward_z0（skrf MLine Hammerstad-Jensen，与全项目
  线宽综合同一实现，#118 独立来源口径）。建模误差只落在 HJ 公式本身
  （常规 w/h 范围 ~1%），不在恒等式。
- **DC R 锚（欧姆定律几何精确）**：R = ρ·len/(w·t)，无模型假设。
- **AC R 参考（一阶趋肤模型，不做门判）**：t ≤ δ 时电流均匀
  （R = ρ/(w·t)）；t > δ 时顶/底/两侧四电流面并联（R = Rs/(2(w+t))，
  Pozar §1.7.1 Rs 口径）。不含邻近效应/粗糙度——产出**参考值**，
  只报告不做验收门（诚实声明，不虚报精度）。

单位口径（全项目惯例）：几何 mm、频率 GHz、结果 L 用 nH/mm、C 用 pF/mm、
R 用 Ω（总量）或 Ω/mm（每长度）。数值只在确定性内核（LLM 不产生物理数字）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.conductor_loss import (
    skin_depth,
    smooth_surface_resistance,
)
from rfauto.core.synthesis import Stackup, forward_z0

#: 真空光速 [m/s]
C0_M_S = 299_792_458.0

#: 退火铜电阻率 [Ω·m]（IACS；与 configs/materials.yaml rogers4350b rho 口径一致）
COPPER_RHO_OHM_M = 1.724e-8

#: H/(m) → nH/mm 换算因子（1 H/m = 1e9 nH / 1e3 mm）
_NH_PER_MM_PER_H_PER_M = 1e6

#: F/m → pF/mm 换算因子（1 F/m = 1e12 pF / 1e3 mm）
_PF_PER_MM_PER_F_PER_M = 1e9


def _positive(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，收到 {value!r}")
    return out


def microstrip_lc_per_length(
    w_mm: float,
    h_mm: float,
    eps_r: float,
    freq_ghz: float,
    *,
    loss_tangent: float = 0.0,
    rho_ohm_m: float = COPPER_RHO_OHM_M,
    rough_mm: float = 0.0,
) -> dict[str, float]:
    """微带线每单位长度 L/C 闭式锚（nH/mm、pF/mm）。

    经传输线恒等式（见模块 docstring）由 Z0/εeff 精确导出；Z0/εeff 用
    core/synthesis.forward_z0（skrf MLine Hammerstad-Jensen）。

    Args:
        w_mm: 线宽 [mm]（>0）
        h_mm: 介质厚度 [mm]（>0）
        eps_r: 相对介电常数（>=1）
        freq_ghz: 综合频率 [GHz]（>0；HJ 模型频变项输入）
        loss_tangent: 介质损耗角正切（>=0，只影响 skrf 内部模型，不进 L/C 锚）
        rho_ohm_m: 导体电阻率 [Ω·m]（skrf MLine 内部用）
        rough_mm: 表面粗糙度 RMS [mm]（skrf MLine 内部用）

    Returns:
        {"z0_ohm", "eps_eff", "l_nh_per_mm", "c_pf_per_mm", ...入参回显}

    Raises:
        ValueError: 参数非法（正数/有限/eps_r>=1）。
    """
    w = _positive("w_mm", w_mm)
    h = _positive("h_mm", h_mm)
    er = _positive("eps_r", eps_r)
    if er < 1.0:
        raise ValueError(f"eps_r 必须 >=1（相对介电常数），收到 {eps_r!r}")
    freq = _positive("freq_ghz", freq_ghz)

    stackup = Stackup(
        name="parasitic_anchor",
        epsilon_r=er,
        thickness_mm=h,
        loss_tangent=float(loss_tangent),
        rho=float(rho_ohm_m),
        rough_mm=float(rough_mm),
    )
    z0, eps_eff = forward_z0(w, freq, stackup)
    sqrt_er = math.sqrt(eps_eff)
    l_h_per_m = z0 * sqrt_er / C0_M_S
    c_f_per_m = sqrt_er / (z0 * C0_M_S)
    return {
        "w_mm": w,
        "h_mm": h,
        "eps_r": er,
        "freq_ghz": freq,
        "z0_ohm": z0,
        "eps_eff": eps_eff,
        "l_nh_per_mm": l_h_per_m * _NH_PER_MM_PER_H_PER_M,
        "c_pf_per_mm": c_f_per_m * _PF_PER_MM_PER_F_PER_M,
    }


def trace_dc_resistance_ohm(
    length_mm: float,
    w_mm: float,
    t_mm: float,
    *,
    rho_ohm_m: float = COPPER_RHO_OHM_M,
) -> float:
    """直条走线 DC 电阻 R = ρ·len/(w·t) [Ω]（欧姆定律，几何精确无模型假设）。

    Raises:
        ValueError: 任一几何参数非正/非有限。
    """
    length = _positive("length_mm", length_mm)
    w = _positive("w_mm", w_mm)
    t = _positive("t_mm", t_mm)
    rho = _positive("rho_ohm_m", rho_ohm_m)
    return rho * (length * 1e-3) / ((w * 1e-3) * (t * 1e-3))


def trace_ac_resistance_per_length(
    w_mm: float,
    t_mm: float,
    freq_ghz: float,
    *,
    rho_ohm_m: float = COPPER_RHO_OHM_M,
    mu_r: float = 1.0,
) -> dict[str, Any]:
    """走线 AC 电阻每长度参考值 [Ω/mm]（一阶趋肤模型；参考值，不做门判）。

    双区间模型（Pozar, Microwave Engineering 4e, §1.7 趋肤口径）：
    - t ≤ δ：电流近似均匀 → R = ρ/(w·t)（几何精确）；
    - t > δ：顶/底/两侧四个电流面并联 → R = Rs/(2·(w+t))，
      Rs = sqrt(π·f·μ/σ)（core/conductor_loss.smooth_surface_resistance）。

    已知近似（如实声明）：不含邻近效应、表面粗糙度与端部效应——Q3D 数值
    AC R 高于此参考属正常（粗糙度/邻近效应单向增大 R），故**只报告不判门**。

    Returns:
        {"r_ohm_per_mm", "regime", "skin_depth_um", "rs_ohm_per_sq" |
         None, "w_mm", "t_mm", "freq_ghz"}
    """
    w = _positive("w_mm", w_mm)
    t = _positive("t_mm", t_mm)
    freq = _positive("freq_ghz", freq_ghz)
    rho = _positive("rho_ohm_m", rho_ohm_m)
    mur = _positive("mu_r", mu_r)
    sigma = 1.0 / rho
    freq_hz = freq * 1e9
    delta_m = skin_depth(freq_hz, sigma, mu_r=mur)
    if t * 1e-3 <= delta_m:
        r_ohm_per_m = rho / ((w * 1e-3) * (t * 1e-3))
        return {
            "r_ohm_per_mm": r_ohm_per_m / 1e3,
            "regime": "uniform_dc_like",
            "skin_depth_um": delta_m * 1e6,
            "rs_ohm_per_sq": None,
            "w_mm": w,
            "t_mm": t,
            "freq_ghz": freq,
        }
    rs = smooth_surface_resistance(freq_hz, sigma, mu_r=mur)
    r_ohm_per_m = rs / (2.0 * ((w + t) * 1e-3))
    return {
        "r_ohm_per_mm": r_ohm_per_m / 1e3,
        "regime": "skin_perimeter",
        "skin_depth_um": delta_m * 1e6,
        "rs_ohm_per_sq": rs,
        "w_mm": w,
        "t_mm": t,
        "freq_ghz": freq,
    }


def interconnect_rlc_anchor(
    length_mm: float,
    w_mm: float,
    t_mm: float,
    h_mm: float,
    eps_r: float,
    freq_ghz: float,
    *,
    loss_tangent: float = 0.0,
    rho_ohm_m: float = COPPER_RHO_OHM_M,
    rough_mm: float = 0.0,
) -> dict[str, Any]:
    """互连段总 RLC 闭式锚（主入口，服务/Q3D 对比共用单一实现）。

    L/C 总量 = 每长度 × 段长（准 TEM 均匀段）；R 给 DC 精确值 + AC 每长度
    参考（不做门判）。返回 dict 供 adapters/q3d_adapter 与
    service/parasitic_service 消费（同一实现，避免两处漂移）。

    Raises:
        ValueError: 参数非法。
    """
    lc = microstrip_lc_per_length(
        w_mm, h_mm, eps_r, freq_ghz,
        loss_tangent=loss_tangent, rho_ohm_m=rho_ohm_m, rough_mm=rough_mm,
    )
    length = _positive("length_mm", length_mm)
    dc_r = trace_dc_resistance_ohm(length, w_mm, t_mm, rho_ohm_m=rho_ohm_m)
    ac = trace_ac_resistance_per_length(
        w_mm, t_mm, freq_ghz, rho_ohm_m=rho_ohm_m)
    return {
        **lc,
        "length_mm": length,
        "l_total_nh": lc["l_nh_per_mm"] * length,
        "c_total_pf": lc["c_pf_per_mm"] * length,
        "dc_r_ohm": dc_r,
        "ac_r_ohm_per_mm": ac["r_ohm_per_mm"],
        "ac_regime": ac["regime"],
        "skin_depth_um": ac["skin_depth_um"],
    }
