"""F-E 件 7：PA 架构回退效率闭式内核（Doherty 负载调制 + Chireix 异相）。

口径与公式来源（#118：来源写 docstring；裁判=独立手算路径，不自证）：

- λ/4 阻抗反演恒等式 Z_in = Z_T²/Z_L：无耗传输线 ABCD 矩阵在
  βl = π/2 的精确退化（V_in = jZ_T·I_out，I_in = jV_out/Z_T），对任意
  复 Z_L 逐位成立。与 core/active_chain.py 的 Cripps 单管 load-pull 面
  （恒功率圈，器件级）互补——本模块是架构级（组合器/负载调制）效率
  闭式，不重复器件面 API。
- 理想 B 类单管峰值效率 η = π/4：半波整流正弦电流 i(θ) = I_pk·max(0,
  cosθ) 的直流 I_dc = I_pk/π 与基波 I_1 = I_pk/2 之比在满摆幅
  （|V| = V_dd）下的效率 (1/2)·V_dd·I_1/(V_dd·I_dc) = π/4 ≈ 78.5%。
  回退律 η(σ) = (π/4)·σ（σ = √(P/P_max) = 归一化电压/电流摆幅）。
  来源：S.C. Cripps《RF Power Amplifiers for Wireless Communications》
  2nd ed., ch.3（reduced conduction angle 分析）。
- Doherty 两区域闭式（理想 B 类主管+线性辅管电流、无耗 λ/4 反演）：
  设计关系 R_L = R_opt/2、Z_T = R_opt = 2R_L（Cripps ARMMS "Revisiting
  the Doherty PA" 2008 原文口径：Z0 = 2R、R = Ropt/2）。σ = V_L/V_dd
  = √(P/P_pk)：
    区域 I（0 ≤ σ ≤ 1/2，辅管截止）：主臂唯一供电，
      η(σ) = (π/2)·σ —— 主管等效单管 B 类在 2σ 驱动；
    区域 II（1/2 ≤ σ ≤ 1，负载调制）：主管电压钉在 V_dd，臂电流
      I_Lm = I_1 恒定、辅管电流 I_a = (2σ−1)I_1（线性，恰在 σ=1/2
      开通、σ=1 满幅）；主/辅管基波（器件侧）i_m = σI_1、i_a =
      (2σ−1)I_1，直流按 B 类 I_dc = 2i/π：
      η(σ) = πσ² / [2(3σ−1)]。
  恒等式：η(1/2) = η(1) = π/4 逐位（回退 6 dB 点效率回到峰值——
  Doherty 平台口径的两端锚点）。**中段凹陷是严格解的内禀属性**：
  min η = 2π/9 ≈ 69.8% 在 σ = 2/3（≈−3.5 dB PBO）——Cripps ARMMS
  原文（Notes 7）自证："Composite efficiency shows close to maximum
  value maintained over upper 6dB power range; Depth of dip (at 3dB
  PBO point) dependent on implementation of peaking amp"（凹陷深度
  取决于辅管实现；"平坦平台"是理想化呈现，非严格 B 类结果）。
  主管负载调制轨迹（本内核计算输出）：Z_main/Z_T = 2（区域 I 恒定，
  Cripps："main sees 2Ropt at 6dB point"）→ Z_T/σ（区域 II，σ=1 时
  回到 Z_T = Ropt，Cripps："Z1 decreases from 2R down to R" 经反演
  映射）。辅管导通角口径：理想模型两管均为 B 类电流源，辅管在
  σ = 1/2 处由组合网络等效"开通"（实际实现偏置 C 类，本内核不做
  导通角波形修正——纯电流源假设的边界，见下方诚实边界）。
- Chireix 异相效率（恒包络电流源模型，直接合路器）：两支路基波电流
  I·e^{±jφ}，1:1:1 变压器合路到 R_L（与 Doherty 节同一合路数学，
  Cripps ARMMS Notes 3：Z1 = R(1+I2/I1)）。支路 1 视入阻抗
  z_1 = 2cos²φ − j·sin2φ（归一化 R_L；支路 2 取共轭）；归一化导纳
  y_1 = (1/2)(1 + j·tanφ)。Chireix 并联补偿电纳 ∓j·b（归一化
  1/R_L，支路 1 感性 −b 抵消其容性 tanφ/2、支路 2 反号）：
      y_1' = (1/2) + j(tanφ/2 − b)，
      η(φ, b) = (π/16) / [(1/4) + (tanφ/2 − b)²]，
      P/P_max = (1/4) / [(1/4) + (tanφ/2 − b)²]。
  恒等式：b=0 时 η = (π/4)cos²φ（经典无补偿线性回退律，η ∝ P，
  劣于单管 B 类的 √P 律）；补偿设计角 φ₀ 的最优电纳
  b_opt = tan(φ₀)/2（电纳归零条件）使 η(φ₀, b_opt) = π/4 逐位
  （φ 域凹陷抬升至峰值）。模型不变量：对任意固定 b，η = (π/4)·
  (P/P_max)（η-p 线性律不变，补偿改善的是 φ 域效率曲线与调制指
  数——同功率下所需异相角范围从 [0,π/2) 收窄到 [0,φ₀]）。
  来源：Cripps 2nd ed. outphasing/Chireix 合路章节；MDPI Electronics
  开放获取 Chireix 分析文（归一化补偿电纳 tan φ₀/2 与本推导一致，
  开放获取复核）。η 全域 ∈ [0, π/4]。

已知豁免（F-E 表预声明，本件不做）：IP5/AM-PM 级联式效率缺权威源
=单级外推+待证标注——本模块不实现级联 AM-PM 效率面；调用方需要时
应走 circuit_hb 非线性真跑通道。

诚实边界（预声明）：
1. 全部效率为**漏极效率**（DC → RF，含器件理想 B 类波形假设），
   不含增益/驱动损耗/膝电压/knee 回退（V_knee=0 口径）与合路器
   损耗——理想无耗假设的上界估计，非实测 PAE 预测器；
2. Doherty 中段凹陷 2π/9 是"理想线性辅管电流+严格 B 类直流"的
   严格解；文献常见的"完全平坦"曲线对应辅管电流波形优化的理想化
   上界，本内核不实现（无权威闭式，不臆造）；
3. Chireix 采用恒包络（电流源/LINC 类）口径；电压钳位（饱和电压
   源）口径的效率式不同（η = (π/4)·功率因数，凹陷位置在 p 域），
   本内核不混装两种口径；
4. 不进 calculators 注册表（F-E 域内约定，消费者是 service 层）；
   纯函数零 IO；接口全部返回 JSON 可序列化 float/dict，ndarray 仅
   在 curve 类辅助函数内部使用、出口转 list[float]。

接口约定：数值 0.0 合法（判缺失一律 `is not None`，#364④）；bool
显式拒收（float(True)=1.0 静默污染，df7+⑯）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 理想 B 类峰值漏极效率（η = π/4 ≈ 0.785398…，模块级锚常量）
ETA_CLASS_B_PEAK = math.pi / 4.0

#: Doherty 等功率设计的合并点（σ_comb = 1/2 ↔ 6 dB 回退，1:2 电压比）
DOHERTY_SIGMA_COMBINE = 0.5

#: Doherty 理想 B 类中段凹陷的严格极小值（σ = 2/3 处，≈0.6981）
DOHERTY_ETA_DIP_MIN = 2.0 * math.pi / 9.0

#: Doherty 中段凹陷位置（σ = 2/3 ≈ −3.52 dB PBO，Cripps ARMMS"3dB PBO dip"）
DOHERTY_SIGMA_DIP = 2.0 / 3.0


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _in_unit_interval(value: float, name: str) -> float:
    """入参收敛为 [0,1] 内有限 float。"""
    out = _finite(value, name)
    if out < 0.0 or out > 1.0:
        raise ValueError(f"{name} 必须 ∈ [0,1]，实际 {out}")
    return out


# ─── λ/4 阻抗反演 ────────────────────────────────────────────────────────────


def quarter_wave_invert(z_load: complex, z_t: float) -> complex:
    """λ/4 反演恒等式：Z_in = Z_T²/Z_L（任意复 Z_L 精确成立）。

    z_load：负载阻抗（复数，Ω，≠0）；z_t：λ/4 线特征阻抗（Ω，>0）。
    恒等式 Z_in·Z_L = Z_T² 逐位成立（浮点乘法往返 ~1e-16 相对误差，
    单测按 rel 1e-12 钉）。z_load=0 → 理想短路反演为开路，显式报错
    （调用方应自行决定开路口径，不静默回传 inf）。
    """
    z_l = complex(z_load)
    z_l = complex(_finite(z_l.real, "z_load.real"), _finite(z_l.imag, "z_load.imag"))
    z_t_ = _finite(z_t, "z_t")
    if z_t_ <= 0.0:
        raise ValueError(f"z_t 必须 >0，实际 {z_t_}")
    if z_l == 0:
        raise ValueError("z_load=0（理想短路）反演发散，不回传 inf")
    return (z_t_ * z_t_) / z_l


# ─── 理想 B 类单管 ───────────────────────────────────────────────────────────


def class_b_efficiency(drive: float) -> float:
    """理想 B 类单管回退效率 η(σ) = (π/4)·σ。

    drive：归一化驱动/摆幅 σ ∈ [0,1]（σ = 基波电流比 = 电压摆幅比 =
    √(P/P_max)，理想阻性负载线三者一致）。σ=1 → π/4（逐位）；
    σ=0 → 0.0（合法，#364④）。
    """
    sigma = _in_unit_interval(drive, "drive")
    return ETA_CLASS_B_PEAK * sigma


def class_b_efficiency_from_power_ratio(power_ratio: float) -> float:
    """理想 B 类单管效率（功率比口径）η = (π/4)·√(P/P_max)。

    power_ratio：输出功率与峰值功率之比 ∈ [0,1]（"三角衰减"律：
    回退 6 dB（ratio=1/4）时 η=π/8≈39.3%）。
    """
    p = _in_unit_interval(power_ratio, "power_ratio")
    return ETA_CLASS_B_PEAK * math.sqrt(p)


# ─── Doherty 负载调制 ────────────────────────────────────────────────────────


@dataclass
class DohertyPoint:
    """Doherty 工作点（理想 B 类两管等功率设计，σ = √(P/P_pk) 口径）。

    电流/电压/阻抗均为归一化量：i_main_over_i1（主管器件侧基波 /
    单管满驱基波 I_1）、i_aux_over_i1（辅管同口径，区域 I 为 0.0——
    截止是显式 0 而非 None，数值 0 合法 #364④）、v_main_over_vdd、
    z_main_over_zt（主管视入负载 / Z_T）、eta_main/eta_aux/eta
    （漏极效率；eta_aux 在区域 I 为 0.0：无直流无射频）。
    """

    sigma: float
    region: int  # 1 = 仅主管；2 = 负载调制（两管）
    eta: float
    eta_main: float
    eta_aux: float
    i_main_over_i1: float
    i_aux_over_i1: float
    v_main_over_vdd: float
    z_main_over_zt: float
    p_over_ppk: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sigma": self.sigma,
            "region": self.region,
            "eta": self.eta,
            "eta_main": self.eta_main,
            "eta_aux": self.eta_aux,
            "i_main_over_i1": self.i_main_over_i1,
            "i_aux_over_i1": self.i_aux_over_i1,
            "v_main_over_vdd": self.v_main_over_vdd,
            "z_main_over_zt": self.z_main_over_zt,
            "p_over_ppk": self.p_over_ppk,
        }


def doherty_efficiency(sigma: float) -> float:
    """Doherty 两区域理想 B 类效率闭式（模块 docstring 推导口径）。

    区域 I（σ ≤ 1/2）：η = (π/2)·σ（主臂唯一供电，等效单管 B 类 2σ 驱动）；
    区域 II（σ ≥ 1/2）：η = πσ² / [2(3σ−1)]。

    恒等式：η(1/2) = η(1) = π/4（逐位）；全域 η ∈ [0, π/4]，中段
    凹陷 min = 2π/9 @ σ = 2/3（严格解内禀属性，见模块 docstring）。
    """
    s = _in_unit_interval(sigma, "sigma")
    if s <= DOHERTY_SIGMA_COMBINE:
        return ETA_CLASS_B_PEAK * (2.0 * s)
    return math.pi * s * s / (2.0 * (3.0 * s - 1.0))


def doherty_point(sigma: float) -> DohertyPoint:
    """Doherty 工作点全量（效率 + 主/辅管电流电压 + 负载调制轨迹）。

    轨迹口径（Cripps ARMMS 2008 原文）：
    - 主管视入负载 z_main_over_zt：区域 I 恒 2（辅管截止，R_L=Z_T/2
      经 λ/4 反演为 Z_T²/R_L = 2Z_T）；区域 II = 1/σ（σ=1 时回到
      Z_T = R_opt——"Z1 decreases from 2R down to R" 的反演面）；
    - 辅管电流 i_aux = max(0, 2σ−1)（恰在合并点开通，满驱满幅）；
    - 主管电压 v_main = min(2σ, 1)（区域 I 线性爬升，区域 II 钉在
      V_dd——电压钳位是负载调制的前提）。
    """
    s = _in_unit_interval(sigma, "sigma")
    if s <= DOHERTY_SIGMA_COMBINE:
        eta = doherty_efficiency(s)
        return DohertyPoint(
            sigma=s,
            region=1,
            eta=eta,
            eta_main=eta,
            eta_aux=0.0,
            i_main_over_i1=s,
            i_aux_over_i1=0.0,
            v_main_over_vdd=2.0 * s,
            z_main_over_zt=2.0,
            p_over_ppk=s * s,
        )
    i_aux = 2.0 * s - 1.0
    return DohertyPoint(
        sigma=s,
        region=2,
        eta=doherty_efficiency(s),
        eta_main=ETA_CLASS_B_PEAK,
        eta_aux=ETA_CLASS_B_PEAK * s,
        i_main_over_i1=s,
        i_aux_over_i1=i_aux,
        v_main_over_vdd=1.0,
        z_main_over_zt=1.0 / s,
        p_over_ppk=s * s,
    )


def doherty_design_impedances(r_opt: float) -> dict[str, float]:
    """Doherty 等功率设计阻抗关系（Cripps：Z0 = 2R、R = Ropt/2）。

    r_opt：单管最优基波负载 R_opt = V_dd/I_1（Ω，>0）。返回
    {"r_load": R_L = R_opt/2（合路节点负载）, "z_t": Z_T = R_opt
    （λ/4 反演线特征阻抗 = 2R_L）}。恒等式 z_t == 2·r_load 逐位。
    """
    r = _finite(r_opt, "r_opt")
    if r <= 0.0:
        raise ValueError(f"r_opt 必须 >0，实际 {r}")
    r_load = r / 2.0
    return {"r_load": r_load, "z_t": 2.0 * r_load}


def doherty_efficiency_curve(sigmas: Any) -> list[float]:
    """σ 数组 → 效率数组（list[float] 出口，JSON 可序列化）。"""
    arr = np.asarray(sigmas, dtype=float)
    if arr.ndim != 1:
        raise ValueError("sigmas 必须为一维数组")
    return [doherty_efficiency(float(s)) for s in arr]


# ─── Chireix 异相 ────────────────────────────────────────────────────────────


@dataclass
class ChireixPoint:
    """Chireix 异相工作点（恒包络电流源模型，b 为归一化补偿电纳）。

    z_branch：含补偿后支路视入阻抗（归一化 R_L，复数）；eta 为每支路
    漏极效率（两支路对称相等）；power_ratio = P/P_max（P_max = φ=0、
    b=0、满驱口径）。eta_aux 不适用——两支路对称，无 aux 语义。
    """

    phi_rad: float
    b_comp: float
    eta: float
    power_ratio: float
    z_branch: complex
    conductance: float = field(default=0.5)  # y_1' 实部（归一化，恒 1/2）
    susceptance: float = field(default=0.0)  # y_1' 虚部 = tanφ/2 − b

    def to_dict(self) -> dict[str, Any]:
        return {
            "phi_rad": self.phi_rad,
            "b_comp": self.b_comp,
            "eta": self.eta,
            "power_ratio": self.power_ratio,
            "z_branch": {"re": self.z_branch.real, "im": self.z_branch.imag},
            "conductance": self.conductance,
            "susceptance": self.susceptance,
        }


def chireix_susceptance(phi_rad: float, b_comp: float) -> float:
    """支路 1 含补偿归一化电纳 B = tanφ/2 − b（无补偿 b=0 时 B = tanφ/2）。

    phi_rad：异相角 ∈ [0, π/2)（φ=π/2 恰在端点处 tan 发散，显式拒绝）；
    b_comp：归一化补偿电纳（任意有限 float，负值=反侧过补偿，物理对称）。
    """
    phi = _finite(phi_rad, "phi_rad")
    if phi < 0.0 or phi >= math.pi / 2.0:
        raise ValueError(f"phi_rad 必须 ∈ [0, π/2)，实际 {phi}")
    return math.tan(phi) / 2.0 - _finite(b_comp, "b_comp")


def chireix_efficiency(phi_rad: float, b_comp: float = 0.0) -> float:
    """Chireix 异相效率闭式 η = (π/16)/[(1/4) + (tanφ/2 − b)²]。

    b_comp：归一化补偿电纳（缺省 0 = 无补偿；此时退化为经典线性
    回退律 η = (π/4)cos²φ，rel 1e-12 恒等——单测钉）。恒等式：
    φ=0 且 b=0 → π/4（同相等幅峰值口径，逐位）；b_opt(φ₀)=tanφ₀/2
    → η(φ₀, b_opt) = π/4 逐位（凹陷抬升至峰值）。全域 η ∈ [0, π/4]。
    """
    b_eff = chireix_susceptance(phi_rad, b_comp)
    return (math.pi / 16.0) / (0.25 + b_eff * b_eff)


def chireix_power_ratio(phi_rad: float, b_comp: float = 0.0) -> float:
    """Chireix 输出功率比 P/P_max = (1/4)/[(1/4) + (tanφ/2 − b)²]。

    模型不变量：η = (π/4)·(P/P_max) 对任意固定 b 逐位成立（η-p 线性
    律不变量，单测钉）——补偿电纳改变 φ→P 映射（调制指数）与 φ 域
    效率凹陷，不改 η-p 关系。
    """
    b_eff = chireix_susceptance(phi_rad, b_comp)
    return 0.25 / (0.25 + b_eff * b_eff)


def chireix_point(phi_rad: float, b_comp: float = 0.0) -> ChireixPoint:
    """Chireix 工作点全量（效率 + 功率比 + 含补偿支路阻抗/导纳）。

    支路导纳（归一化 R_L）：y_1' = 1/2 + j·(tanφ/2 − b)；支路阻抗
    z_1' = 1/y_1'。b_opt 设计时 y_1' 实部 1/2、虚部 0（电纳归零）。
    """
    b_eff = chireix_susceptance(phi_rad, b_comp)
    y = complex(0.5, b_eff)
    return ChireixPoint(
        phi_rad=_finite(phi_rad, "phi_rad"),
        b_comp=_finite(b_comp, "b_comp"),
        eta=(math.pi / 16.0) / (0.25 + b_eff * b_eff),
        power_ratio=0.25 / (0.25 + b_eff * b_eff),
        z_branch=1.0 / y,
        conductance=0.5,
        susceptance=b_eff,
    )


def chireix_optimal_b(phi_design_rad: float) -> float:
    """设计角 φ₀ 的最优补偿电纳 b_opt = tan(φ₀)/2（电纳归零条件）。

    恒等式：η(φ₀, b_opt) = π/4 逐位、y_1' 虚部归零（逐位）。解析值
    与数值 argmax（η(φ₀, b) 对 b 网格扫描）对照为单测裁判（#118）。
    """
    phi = _finite(phi_design_rad, "phi_design_rad")
    if phi < 0.0 or phi >= math.pi / 2.0:
        raise ValueError(f"phi_design_rad 必须 ∈ [0, π/2)，实际 {phi}")
    return math.tan(phi) / 2.0


def chireix_efficiency_curve(
    phi_rads: Any, b_comp: float = 0.0
) -> dict[str, list[float]]:
    """φ 扫描数组 → {phi_rad, power_ratio, eta} 三数组（JSON 可序列化）。

    报告/绘图消费面（F-E 件 7 规格 3 的 Chireix 曲线数据）。b_comp
    可为 chireix_optimal_b(φ₀) 的返回值（补偿改善曲线对照 b=0）。
    """
    arr = np.asarray(phi_rads, dtype=float)
    if arr.ndim != 1:
        raise ValueError("phi_rads 必须为一维数组")
    b = _finite(b_comp, "b_comp")
    eta: list[float] = []
    p_ratio: list[float] = []
    phi_out: list[float] = []
    for v in arr:
        phi = float(v)
        pt = chireix_point(phi, b)
        phi_out.append(pt.phi_rad)
        p_ratio.append(pt.power_ratio)
        eta.append(pt.eta)
    return {"phi_rad": phi_out, "power_ratio": p_ratio, "eta": eta}


# ─── 回退效率对比（三架构同轴数据，报告/绘图消费） ────────────────────────────


def backoff_efficiency_comparison(power_ratios: Any) -> dict[str, Any]:
    """单管 B 类 vs Doherty vs Chireix 回退效率同轴对比数据。

    power_ratios：P/P_max 数组（每个元素 ∈ [0,1]）。返回三列同 x 轴
    （p_ratio）数据 + 物理判读标志：
    - class_b_eta = (π/4)√p（单管三角衰减）；
    - doherty_eta = 两区域闭式（6 dB 点平台恒等 η(1/4) = η(1) = π/4）；
    - chireix_eta = (π/4)·p（恒包络口径线性律——η-p 不变量的 p 轴
      直写形式，与 chireix_efficiency/power_ratio 逐点一致，单测钉；
      补偿电纳不改 η-p 关系，故对比列不含 b——φ 域改善曲线走
      chireix_efficiency_curve）。
    - flags：doherty_ge_class_b（架构有效性逐点判读）、chireix_le_
      class_b（线性律劣于三角律）、bounds_ok（三列均 ∈ [0, π/4]）。
    纯函数零 IO；全 dict JSON 可序列化。
    """
    arr = np.asarray(power_ratios, dtype=float)
    if arr.ndim != 1:
        raise ValueError("power_ratios 必须为一维数组")
    p_list: list[float] = []
    class_b: list[float] = []
    doherty: list[float] = []
    chireix: list[float] = []
    for v in arr:
        p = _in_unit_interval(float(v), "power_ratios[]")
        p_list.append(p)
        class_b.append(class_b_efficiency_from_power_ratio(p))
        doherty.append(doherty_efficiency(math.sqrt(p)))
        chireix.append(ETA_CLASS_B_PEAK * p)
    flags = {
        "doherty_ge_class_b": bool(
            all(d >= c - 1e-12 for d, c in zip(doherty, class_b, strict=True))
        ),
        "chireix_le_class_b": bool(
            all(x <= c + 1e-12 for x, c in zip(chireix, class_b, strict=True))
        ),
        "bounds_ok": bool(
            all(
                0.0 <= e <= ETA_CLASS_B_PEAK + 1e-12
                for col in (class_b, doherty, chireix)
                for e in col
            )
        ),
    }
    return {
        "p_ratio": p_list,
        "class_b_eta": class_b,
        "doherty_eta": doherty,
        "chireix_eta": chireix,
        "eta_peak": ETA_CLASS_B_PEAK,
        "flags": flags,
    }


def chireix_design_from_power_ratio(power_ratio: float) -> dict[str, float]:
    """按目标回退功率比选 Chireix 补偿设计角：φ₀ = arccos(√p₀)、b_opt。

    power_ratio ∈ (0,1]：设计点 P/P_max（b=0 口径的 P 映射 cos²φ₀ = p₀）。
    返回 {"phi0_rad", "phi0_deg", "b_opt"}。p₀=1 → φ₀=0、b_opt=0。
    """
    p = _in_unit_interval(power_ratio, "power_ratio")
    if p <= 0.0:
        raise ValueError("power_ratio 必须 >0（φ₀=90° 端点不可达）")
    phi0 = math.acos(math.sqrt(p))
    return {
        "phi0_rad": phi0,
        "phi0_deg": math.degrees(phi0),
        "b_opt": chireix_optimal_b(phi0),
    }


def z_branch_normalized(phi_rad: float, b_comp: float = 0.0) -> complex:
    """Chireix 支路视入阻抗（归一化 R_L，含补偿；cmath 复数出口）。

    无补偿 z_1 = 2cos²φ − j·sin2φ（支路 1；支路 2 取共轭）；含补偿
    z_1' = 1/(1/2 + j(tanφ/2 − b))。φ=0、b=0 → 2+0j（= Z_T 口径的
    满驱最优点，逐位）。诊断/审计用途，效率主路径不消费。
    """
    _ = chireix_susceptance(phi_rad, b_comp)  # 复用域守卫
    t = math.tan(_finite(phi_rad, "phi_rad")) / 2.0 - _finite(b_comp, "b_comp")
    return 1.0 / complex(0.5, t)


def chireix_b_null_check(phi_rad: float, b_comp: float) -> bool:
    """电纳归零判读：|tanφ/2 − b| ≤ 1e-12（b_opt 设计点逐位判据）。"""
    return abs(chireix_susceptance(phi_rad, b_comp)) <= 1e-12
