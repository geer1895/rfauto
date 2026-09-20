r"""电-热链确定性内核。

链路：Wilkinson 隔离电阻损耗 → 热路温升（闭式/Icepak 场解）→
材料温漂 → S 参数失谐。本模块只做确定性算术：无随机、无网络、无真机。

口径与公式来源（裁判 = 独立来源，不是本模块自己的推导，#118）
----------------------------------------------------------------
1) Wilkinson 隔离电阻损耗（理想三端口，Pozar, Microwave Engineering,
   4th ed. §7.3 eq. (7.35)/(7.37) 同款口径）::

       S = -j/sqrt(2) * [[0, 1, 1],
                         [1, 0, 0],
                         [1, 0, 0]]

   S11=S22=S33=0（全匹配）、S23=S32=0（输出端口隔离）、S21=S31=-j/√2
   （3 dB 等分）。功率归一入射波 a_i（|a_i|^2 = 入射功率 [W]），网络内
   部唯一损耗元件 = 隔离电阻，能量守恒给出

       P_res = sum|a_i|^2 - sum|b_i|^2
             = |a2|^2 + |a3|^2 - 0.5|a2+a3|^2
             = 0.5 |a2 - a3|^2

   三个极限自检（单测以显式 S 矩阵乘法独立复算，test_electrothermal_core）：
   - 等分直通（a1=√P, a2=a3=0）→ P_res = 0；
   - 奇模注入（a2=-a3=a）→ P_res = 2|a|^2 = 全部入射功率；
   - 单边隔离注入（a2=√P, a3=0）→ P_res = P/2（另一半经 -j/√2 支路
     出 port1，构成隔离机理本身）。

2) 一阶温漂闭式（Pozar 谐振器温漂对数一阶展开；实现单一事实源 =
   core/thermal_iteration.closed_form_drift_ratio，本模块直接复用）::

       df0/f0 = -CTE*dT - 0.5*TCDk*dT

3) 1-D 传导锚（Incropera, Fundamentals of Heat and Mass Transfer，
   稳态傅里叶传导 + 均匀体热源层的中面平均温升）::

       T = T_base + (P/A) * (h_sub/k_sub + h_blk/(2*k_blk))

   发热块满覆基板顶面、基板底面 Dirichlet、侧壁绝热时精确成立；用作
   Icepak 首案例温度场的独立解析裁判（真机门 ≤2%）。

设计约束
--------
- core 叶子层：只 import 标准库 math/typing + 同层叶子
  thermal_iteration（零新依赖、零 numpy）。
- 全部纯函数；非法输入显式 ValueError，不静默兜底。
- 单位约定：功率 W、温度 °C、频率 Hz、几何 SI（m）；适配/脚本层负责
  mm↔m 换算。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.thermal_iteration import closed_form_drift_ratio

__all__ = [
    "band_guard",
    "combiner_imbalance_case",
    "conduction_stack_rise_k",
    "conduction_uniform_flux_rise_k",
    "divider_through_case",
    "isolation_injection_case",
    "resistor_power_from_waves",
    "thermal_detune",
]


def _finite(value: Any, name: str) -> float:
    """把入参收敛为有限 float；非法即显式 ValueError。"""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，收到 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须是有限数，收到 {value!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {value!r}")
    return out


# ---------------------------------------------------------------------------
# 1) Wilkinson 隔离电阻损耗
# ---------------------------------------------------------------------------

def resistor_power_from_waves(
    p2_w: float,
    p3_w: float,
    phase_diff_deg: float = 0.0,
) -> float:
    """理想 Wilkinson 隔离电阻耗散功率 [W]（Pozar §7.3，见模块头推导）。

    P_res = 0.5|a2 - a3|^2 = 0.5 (p2 + p3 - 2 sqrt(p2 p3) cos(dphi))，
    其中 p2/p3 为输出端口 2/3 的入射功率，dphi 为 a3 相对 a2 的相位差。

    Raises:
        ValueError: 功率为负或非有限。
    """
    p2 = _nonneg(p2_w, "p2_w")
    p3 = _nonneg(p3_w, "p3_w")
    dphi_rad = math.radians(_finite(phase_diff_deg, "phase_diff_deg"))
    return 0.5 * (p2 + p3 - 2.0 * math.sqrt(p2 * p3) * math.cos(dphi_rad))


def divider_through_case(input_power_w: float) -> dict[str, float]:
    """等分直通工况（port1 入 P，输出匹配）：P_res=0，两输出各 P/2。"""
    p_in = _nonneg(input_power_w, "input_power_w")
    return {
        "resistor_w": 0.0,
        "port1_out_w": 0.0,
        "port2_out_w": p_in / 2.0,
        "port3_out_w": p_in / 2.0,
        "input_w": p_in,
    }


def isolation_injection_case(injected_power_w: float) -> dict[str, float]:
    """隔离注入工况（port2 入 P，port1/port3 匹配）：P_res=P/2，port1 出 P/2。

    这正是隔离机理：注入输出端口的功率一半耗散在隔离电阻上。
    """
    p_inj = _nonneg(injected_power_w, "injected_power_w")
    return {
        "resistor_w": p_inj / 2.0,
        "port1_out_w": p_inj / 2.0,
        "port2_out_w": 0.0,
        "port3_out_w": 0.0,
        "input_w": p_inj,
    }


def combiner_imbalance_case(
    p2_w: float,
    p3_w: float,
    phase_diff_deg: float,
) -> dict[str, float]:
    """合路器失配工况：两路输入 P2/P3、相位差 dphi → 隔离电阻/port1 分配。

    功率守恒残差 residual_w = (p2+p3) - (P_res + port1_out)（理想模板下
    应为 ~0，保留作数值自检输出）。
    """
    p2 = _nonneg(p2_w, "p2_w")
    p3 = _nonneg(p3_w, "p3_w")
    dphi_rad = math.radians(_finite(phase_diff_deg, "phase_diff_deg"))
    res_w = 0.5 * (p2 + p3 - 2.0 * math.sqrt(p2 * p3) * math.cos(dphi_rad))
    port1_w = 0.5 * (p2 + p3 + 2.0 * math.sqrt(p2 * p3) * math.cos(dphi_rad))
    return {
        "resistor_w": res_w,
        "port1_out_w": port1_w,
        "port2_out_w": 0.0,
        "port3_out_w": 0.0,
        "input_w": p2 + p3,
        "residual_w": (p2 + p3) - (res_w + port1_w),
    }


# ---------------------------------------------------------------------------
# 2) 材料温漂 → S 参数失谐
# ---------------------------------------------------------------------------

def thermal_detune(
    f0_hz: float,
    delta_t_c: float,
    cte_ppm_per_k: float,
    tcdk_ppm_per_k: float,
) -> dict[str, float]:
    """一阶温漂 → 谐振/中心频率失谐（闭式，复用 thermal_iteration 单一事实源）。

    Returns:
        {"drift_ratio": df0/f0, "df_hz": ..., "df_ppm": ...,
         "f0_shifted_hz": ...}
    """
    f0 = _positive(f0_hz, "f0_hz")
    dt = _finite(delta_t_c, "delta_t_c")
    ratio = closed_form_drift_ratio(cte_ppm_per_k, tcdk_ppm_per_k, dt)
    return {
        "drift_ratio": ratio,
        "df_hz": f0 * ratio,
        "df_ppm": ratio * 1e6,
        "f0_shifted_hz": f0 * (1.0 + ratio),
    }


def band_guard(
    f0_shifted_hz: float,
    band_low_hz: float,
    band_high_hz: float,
) -> dict[str, Any]:
    """失谐后的特征频率是否仍在工作带内的确定性判据。

    Returns:
        {"in_band": bool, "nearest_edge_hz": lo|hi, "margin_hz": ...,
         "margin_ppm_of_center": ...}；margin = 失谐 f0 到最近带缘的距离
        （负值=已出带），ppm 以带几何中心为参考。

    Raises:
        ValueError: f0 非正或带缘非有限/low>=high。
    """
    f0 = _positive(f0_shifted_hz, "f0_shifted_hz")
    lo = _finite(band_low_hz, "band_low_hz")
    hi = _finite(band_high_hz, "band_high_hz")
    if lo >= hi:
        raise ValueError(f"band_low_hz 必须 < band_high_hz，收到 ({lo!r}, {hi!r})")
    margin_lo = f0 - lo
    margin_hi = hi - f0
    in_band = margin_lo >= 0.0 and margin_hi >= 0.0
    if margin_lo <= margin_hi:
        edge, margin = lo, margin_lo
    else:
        edge, margin = hi, margin_hi
    center = 0.5 * (lo + hi)
    return {
        "in_band": in_band,
        "nearest_edge_hz": edge,
        "margin_hz": margin,
        "margin_ppm_of_center": margin / center * 1e6,
    }


# ---------------------------------------------------------------------------
# 3) 1-D 传导锚（Icepak 温度场的独立解析裁判）
# ---------------------------------------------------------------------------

def conduction_stack_rise_k(
    power_w: float,
    area_m2: float,
    h_sub_m: float,
    k_sub_w_mk: float,
    h_blk_m: float,
    k_blk_w_mk: float,
    t_base_c: float,
) -> dict[str, float]:
    """1-D 传导锚：发热块满覆基板、底面 Dirichlet 时的块中面温度（°C）。

    T = T_base + (P/A) * (h_sub/k_sub + h_blk/(2 k_blk))；前一项是基板
    传导热阻，后一项是均匀体热源层到自身中面的一半温升（Incropera，
    见模块头）。面积 A = 发热块/基板共同足印。

    Returns:
        {"t_monitor_c": ..., "rise_k": ..., "r_total_k_per_w": ...}

    Raises:
        ValueError: 功率为负；面积/厚度/热导率非正。
    """
    p = _nonneg(power_w, "power_w")
    a = _positive(area_m2, "area_m2")
    hs = _positive(h_sub_m, "h_sub_m")
    ks = _positive(k_sub_w_mk, "k_sub_w_mk")
    hb = _positive(h_blk_m, "h_blk_m")
    kb = _positive(k_blk_w_mk, "k_blk_w_mk")
    t_base = _finite(t_base_c, "t_base_c")
    r_total = hs / (ks * a) + hb / (2.0 * kb * a)
    rise = p * r_total
    return {
        "t_monitor_c": t_base + rise,
        "rise_k": rise,
        "r_total_k_per_w": r_total,
    }


def conduction_uniform_flux_rise_k(
    power_w: float,
    area_m2: float,
    depth_m: float,
    k_w_mk: float,
    t_base_c: float,
) -> dict[str, float]:
    """均匀面通量层内一点的线性传导温升（Fourier 定律，Incropera）。

    T = T_base + (P/A) * depth / k。当满覆发热块的全部功率经均匀通量
    流过均匀介质时，层内温度剖面为线性——任何网格下逐点精确（与体热源
    层内的抛物面剖面不同，后者对网格离散敏感）。用作 Icepak 锚工况
    （监控点取基板中面）的独立解析裁判。

    Returns:
        {"t_monitor_c": ..., "rise_k": ..., "r_total_k_per_w": ...}

    Raises:
        ValueError: 功率为负；面积/深度/热导率非正。
    """
    p = _nonneg(power_w, "power_w")
    a = _positive(area_m2, "area_m2")
    d = _positive(depth_m, "depth_m")
    k = _positive(k_w_mk, "k_w_mk")
    t_base = _finite(t_base_c, "t_base_c")
    r_total = d / (k * a)
    rise = p * r_total
    return {
        "t_monitor_c": t_base + rise,
        "rise_k": rise,
        "r_total_k_per_w": r_total,
    }
