"""HS-5 SSO 地弹上界内核：同步开关噪声一阶闭式 + PDN 阻抗频域求和 + 裕度门。

模块面（round4 中件包一 HS-5 规格，全部为**上界筛查口径**，非波形仿真器）：
- ground_bounce_voltage：V_地弹 = N·L_eff·di/dt（时间域一阶闭式，线性叠加
  口径）。
- rail_noise_contributions / rail_noise_peak：给定 |Z_PDNI(f_m)| 数组与谐波
  电流谱 |I(f_m)| → V_rail 峰值估计 Σ|Z(f_m)|·|I(f_m)|。**如实声明：这是
  频域逐谐波求和口径，非时域卷积**——隐含各谐波最坏情形同相叠加（相位
  信息不进判据），对随机相位实际波形是过估计；上界语义宁高勿低。
  Z_PDNI 面由 core/pdn.py pdn_impedance_profile / service 层只读复用产出，
  本模块只吃 |Z| 数组（解耦，不做第二份阻抗合成实现）。
- sso_margin_gate / sso_bounce_gate：噪声电平 vs 噪声裕度门（v ≤ margin →
  pass，恰等判 pass、utilization=1.0 留痕；二值不折中，#122 预声明）。

IBIS power-aware 波形级 = NO-GO 登记（不开实现）：带 PDN 的波形级 SSN
需要 IBIS 5.0+ [Power Aware] 模型（ISS 子电路/IBIS-ISS PDN）与 transient
联合仿真，属外部 EDA 波形域，超出确定性内核范畴（铁律 7：数值只在确定
性内核，波形级不含闭式）。登记见模块常量 IBIS_POWER_AWARE_STATUS =
"no_go"；v1 不提供任何波形级入口。

法源（#300 公式-出处一一对应）：
- 地弹/SSN 一阶式 V = L·dI/dt 与多驱动同步开关线性叠加：H. W. Johnson,
  M. Graham, "High-Speed Digital Design: A Handbook of Black Magic,"
  Prentice Hall 1993（ground bounce / simultaneous switching 工程口径）。
  线性叠加忽略驱动非线性与互感耦合（同向同瞬最坏情形假设），是工程
  上界非精算——如实标注。
- 电源轨噪声频域估计 Σ|Z(f_m)|·|I(f_m)|：L. D. Smith, R. E. Anderson,
  D. W. Forehand, T. J. Pelc, T. Roy, "Power distribution system design
  methodology and capacitor selection for modern CMOS technology," IEEE
  Trans. Adv. Packag., vol. 22, no. 3, 1999 目标阻抗法同族（频域阻抗×
  电流谱），与 core/pdn.py target_impedance 口径互恰。
- 噪声裕度判据：V_noise ≤ noise_margin（静态噪声裕度工程口径）。

数值口径：0.0 合法（N=0/L=0/di_dt=0 → V=0.0；判缺失一律 is not None，
#364④）；负参数/NaN/空谱/两谱长度不配一律 ValueError 硬错。逐位恒等式：
N=1、L=1、di/dt=1 → V=1.0 逐位；L=1、di/dt=1 时 V(N)=N 逐位（单测钉）。
纯函数零 IO；不进 calculators 注册表（免 #231 注册表消费者三表同步，
参照 core/rwg_mmt.py 先例）；不定义 __all__（公开 API 快照只钉带
__all__ 模块）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# IBIS power-aware 波形级 SSN：NO-GO 登记（docstring 法源节，不开实现）。
IBIS_POWER_AWARE_STATUS = "no_go"


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _nonneg(value: float, name: str) -> float:
    """入参收敛为有限非负 float（0.0 合法），负数即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，实际 {value!r}")
    return out


def _positive(value: float, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {value!r}")
    return out


def _switch_count(value: object, name: str) -> int:
    """同步开关数收敛为非负 int：bool/非整数/负数一律 ValueError。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}") from exc
    if out != value:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if out < 0:
        raise ValueError(f"{name} 必须 >=0，实际 {value!r}")
    return out


def _magnitude_spectrum(values: Sequence[float], name: str) -> list[float]:
    """幅度谱收敛：逐元素有限且 ≥0，空谱 ValueError（任务书边界口径）。"""
    out: list[float] = []
    for k, v in enumerate(values):
        out.append(_nonneg(v, f"{name}[{k}]"))
    if not out:
        raise ValueError(f"{name} 谱为空：空谱不构成 SSO 评估")
    return out


def ground_bounce_voltage(n_switch: int, l_eff_h: float, di_dt_a_per_s: float) -> float:
    """地弹一阶闭式 V = N·L_eff·di/dt（线性叠加口径，上界筛查）。

    Args:
        n_switch: 同步开关驱动数（非负 int；0 → V=0.0 合法）。
        l_eff_h: 等效地弹电感（H，≥0；返回路径+过孔+封装的合成等效值，
            标定责任在调用方）。
        di_dt_a_per_s: 单驱动电流斜率幅度（A/s，≥0；取幅度，极性由
            判据面按上界语义吸收）。

    Returns:
        地弹电压幅度（V）。恒等式：N=1、L=1、di/dt=1 → 1.0 逐位；
        L=1、di/dt=1 时 V(N)=N 逐位。
    """
    n = _switch_count(n_switch, "n_switch")
    l_eff = _nonneg(l_eff_h, "l_eff_h")
    di_dt = _nonneg(di_dt_a_per_s, "di_dt_a_per_s")
    return (n * l_eff) * di_dt


def rail_noise_contributions(
    z_pdni: Sequence[float], i_harmonics: Sequence[float]
) -> list[float]:
    """逐谐波噪声贡献 [|Z(f_m)|·|I(f_m)|]（与 rail_noise_peak 同口径）。

    Args:
        z_pdni: |Z_PDNI(f_m)| 幅度数组（Ω，≥0，来自 pdn.py 阻抗谱取模）。
        i_harmonics: 谐波电流幅度数组（A，≥0，与 z_pdni 逐点同频对齐）。

    Returns:
        逐谐波贡献列表（V，与输入同长）。
    """
    z = _magnitude_spectrum(z_pdni, "z_pdni")
    i = _magnitude_spectrum(i_harmonics, "i_harmonics")
    if len(z) != len(i):
        raise ValueError(f"两谱长度必须一致，实际 |Z|={len(z)}、|I|={len(i)}")
    return [zk * ik for zk, ik in zip(z, i, strict=True)]


def rail_noise_peak(z_pdni: Sequence[float], i_harmonics: Sequence[float]) -> float:
    """电源轨噪声峰值估计 Σ|Z(f_m)|·|I(f_m)|（频域求和口径）。

    **如实声明：频域逐谐波顺序求和，非时域卷积**——最坏情形同相叠加
    假设（相位不进判据），对随机相位波形是上界（见模块 docstring）。

    Args:
        z_pdni / i_harmonics: 同 rail_noise_contributions。

    Returns:
        峰值估计（V，顺序求和）。
    """
    return sum(rail_noise_contributions(z_pdni, i_harmonics))


@dataclass(frozen=True)
class SsoMarginVerdict:
    """SSO 噪声裕度门结果（verdict + 全部中间量，不替用户放宽判据）。"""

    verdict: str  # "pass" | "fail"
    noise_v: float  # 噪声电平（V）
    noise_margin_v: float  # 噪声裕度（V）
    margin_v: float  # noise_margin_v − noise_v（负=超限量）
    utilization: float  # noise_v / noise_margin_v（1.0=恰达门限）

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "verdict": self.verdict,
            "noise_v": self.noise_v,
            "noise_margin_v": self.noise_margin_v,
            "margin_v": self.margin_v,
            "utilization": self.utilization,
        }


def sso_margin_gate(noise_level_v: float, noise_margin_v: float) -> SsoMarginVerdict:
    """噪声电平 vs 噪声裕度门：v ≤ margin → "pass"（恰等 pass）。

    Args:
        noise_level_v: 噪声电平（V，≥0；V_bounce 或 rail_noise_peak 产出）。
        noise_margin_v: 噪声裕度（V，>0）。

    Returns:
        SsoMarginVerdict（margin_v = margin − noise，utilization = noise/margin）。
    """
    v = _nonneg(noise_level_v, "noise_level_v")
    m = _positive(noise_margin_v, "noise_margin_v")
    verdict = "pass" if v <= m else "fail"
    return SsoMarginVerdict(verdict=verdict, noise_v=v, noise_margin_v=m, margin_v=m - v, utilization=v / m)


def sso_bounce_gate(
    n_switch: int, l_eff_h: float, di_dt_a_per_s: float, noise_margin_v: float
) -> SsoMarginVerdict:
    """V_bounce vs 噪声裕度门（ground_bounce_voltage → sso_margin_gate 组合）。"""
    return sso_margin_gate(ground_bounce_voltage(n_switch, l_eff_h, di_dt_a_per_s), noise_margin_v)
