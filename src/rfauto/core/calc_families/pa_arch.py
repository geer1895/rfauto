"""PA/控制件族（R2 空白域 G11；架构批 W7-A 席首批三键+批 B Wave3
W3-CORE3 席原位扩展四键，2026-10-13）。

七键：balanced_pair_sparams（90° 混合器平衡放大器对 S 参数合成）/
doherty_combining_network（经典 2-Way 等功率 Doherty 合路 λ/4 网络）/
doherty_efficiency_curve（理想 B 类双拐点效率-回退曲线，单源消费
core/pa_architectures 两区域闭式）/ envelope_tracking_efficiency（ET
包络跟踪平均漏极效率，Rayleigh 包络+供电下限/削顶闭式）/
pin_diode_limiter（PIN 二极管并联限幅器两态 S/功率三分/门限一阶估计）/
step_attenuator_design（步进衰减器二进制位组合+逐位 π/T 衰减节综合）/
multiplier_chain_budget（倍频链频率/功率预算+理想 20log10(N) 相噪劣化律）。

与既有 PA 面的分工（语义防撞，R2 §① E 族地图 + G11 三重搜索证据）
------------------------------------------------
- core/pa_architectures.py = Doherty 负载调制/Chireix **效率闭式**内核
  （docstring 自述"不进注册表"）；本族补的是 G11 点名的**合成网络面**
  （λ/4 inverter 阻抗+peak 偏置线+功分比）与**平衡对**（push-pull/
  balanced amplifier 三重搜索全仓零命中）——效率曲线键直接单源消费
  该内核闭式（双实现不重复，R2 G11 测试策略"交叉对拍"以锚树测试侧
  独立重算承担），不复制第二份推导。
- active_chain.py = 单管器件面（S 增益圆/双共轭匹配/load-pull/Cripps）；
  本族 balanced_pair_sparams 消费单管 S 参数（器件面输出）合成架构级
  S 参数，不重复器件面 API。
- switch_pa_efficiency.py = 开关类（D/E/F）导通角效率——口径不同域。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
1. **平衡放大器对（Kurokawa 90° 杂交口径）**：输入/输出各一只 3dB
   90° 混合器，两管各得等幅正交激励。理想混合器下合成恒等式：

       S11,bal = (S11a − S11b)/2   （同管 → 严格 0，反射对消）
       S21,bal = (S21a + S21b)/2   （同管 → = 单管，增益不变）
       S22,bal = (S22a − S22b)/2   （输出侧同恒等式）

   推导（功率波口径）：输入混合器直通/耦合臂各 −3dB 且相差 90°，
   a_A = a_in/√2、a_B = −j·a_in/√2；反射波在输出混合器的隔离臂合成，
   输入口剩 (Γ_A − Γ_B)/2。失配容忍度（本键输出字段）：
   - 单管失效（开路/短路 |Γ|=1、另一管匹配）→ |S11,bal| = 1/2 →
     回损 6.0206 dB（劣化有界，不灾难性失配）；增益 −6.0206 dB
     （S21,bal = S21/2）——平衡架构的经典失效容忍性质；
   - 同幅反射管对相位失配 Δφ：|S11,bal| = Γ·|sin(Δφ/2)|——给目标
     回损 RL 的相位容差 Δφ_max = 2·arcsin(10^(−RL/20)/Γ)。
   来源：K. Kurokawa 平衡放大器原理（90° 杂交对消口径）；
   S.C. Cripps《RF Power Amplifiers for Wireless Communications》2nd ed.
   平衡架构节（反射对消恒等式与失效容忍口径）。
2. **经典 2-Way 等功率 Doherty 合路网络**（写死口径）：R_opt = 单管
   最优基波负载（V_dd/I_1）。设计关系（Cripps ARMMS "Revisiting the
   Doherty PA" 2008 原文：Z0 = 2R、R = Ropt/2；2nd ed. Doherty 节）：

       合路节点负载 R_L = R_opt/2
       载波臂 λ/4 逆变器特征阻抗 Z_T = R_opt = 2·R_L
       回退点载波视入负载 Z_BO = Z_T²/R_L = 2·R_opt（λ/4 反演恒等式）
       合并点回退 = 10·log10(4) = 6.0206 dB（等功率 2-Way 固定值）
       功分比 = 50/50（等功率口径；输入功分器同比）

   满驱峰值时两管各入 R_opt（电压同摆幅 V_dd 各给 V_dd·I_1/2）；
   回退点辅管截止呈开路、载波经反演看 2R_opt——电压摆幅保持满幅、
   电流减半 → 效率第二拐点（负载调制的全部要义）。peak 臂偏置线
   （offset line）：电长度 90°@f0、特征阻抗取 Z_T（惯例口径，实现
   相关非唯一，Cripps Doherty 节；作用=辅管截止态输出电抗补偿），
   本键按惯例给出并如实标注。λ/4 反演恒等式 Z_in = Z_T²/Z_L 走
   core/pa_architectures.quarter_wave_invert 单源（ABCD 矩阵 βl=π/2
   精确退化），锚树测试用测试侧独立 ABCD 级联回代互证（ADS 域回代
   同一恒等式形态）。
3. **理想 B 类 Doherty 效率-回退曲线**（单源消费 core/pa_architectures
   .doherty_efficiency 两区域闭式，Cripps ARMMS 2008 原文口径）：

       区域 I（σ ≤ 1/2，辅管截止）：η = (π/2)·σ
       区域 II（1/2 ≤ σ ≤ 1，负载调制）：η = πσ²/[2(3σ−1)]
       σ = √(P/P_pk)

   双拐点锚：η(σ=1) = η(σ=1/2) = π/4 ≈ 78.54% 逐位（峰值与 6dB 合并
   点）；中段凹陷严格极小 min η = 2π/9 ≈ 69.81% 在 σ = 2/3（PBO ≈
   3.5218 dB，独立求导 d/dσ[σ²/(3σ−1)]=0 给 σ=2/3）。凹陷深度依辅管
   实现而定（Cripps ARMMS 原文 Notes 7 自证）；文献理想化"全平平台"
   是辅管电流波形优化的上界、非严格 B 类结果——本键采用严格 B 类
   口径并如实报告凹陷。对照列：单管 B 类 η = (π/4)·√p 三角衰减律。
4. **ET 包络跟踪平均漏极效率**（批 B Wave3 W3-CORE3，理想 B 类 +
   Rayleigh 包络 + 供电下限/硬削顶口径）：点态 B 类效率
   η(t) = (π/4)·(V_o/V_s)（Cripps 2nd ed. ch.5 B 类口径）；ET 供电
   V_s(t) = max(v, f)·V_max，v = 包络对满摆幅归一（Rayleigh，E[v²]
   = 1/ξ，ξ=PAPR 线性）、f = 供电下限份额、v>1 段削顶到轨（v :=
   min(v,1)）。平均效率按能量口径 η = E[P_out]/E[P_dc]
   （P_out ∝ v²、P_dc ∝ (2/π)·max(v,f)·v，B 类 I_dc=2V_o/(πR_L)），
   Rayleigh 积分闭式：

       η_ET(f, ξ) = (π/4)·(1−e^{−ξ}) / [e^{−ξf²} − e^{−ξ}
                    + (√(πξ)/2)·f·erf(f√ξ)]      ……（式 ET1）

   双结构锚：f=0（理想全程跟踪）→ η = π/4 与 PAPR 无关（ET 的全部
   要义）；f=1（无跟踪退化）→ 逐位等于定供 B 类对照
   η_fixed = (π/4)·E[v²]/E[v] = (√π/(2√ξ))·(1−e^{−ξ})/erf(√ξ)。
   供电恒不高于定供（max(v,f) ≤ 1）⟹ η_ET(f) ≥ η_fixed 全域（能量
   口径单调性，测试面栅格钉）。#118 第二路线 = scipy 数值积分
   (π/4)·E[v²]/E[max(v,f)·v]（不同算法独立裁判，实测 ≤1.3e-9）。
   来源：点态 B 类效率 Cripps《RF Power Amplifiers for Wireless
   Communications》2nd ed. ch.5（B 类 π/4 口径）；ET 架构口径 =
   包络跟踪高效率发射机标准文献（概念级，不引具体百分比）；
   Rayleigh 包络 = 通信信号标准统计模型；含供电下限/削顶的平均效率
   闭式（式 ET1）= 本仓独立推导（数值积分独立裁判）。
5. **PIN 二极管并联限幅器两态线性口径**（同席）：并联导纳 y 的二口
   S（ABCD [1,0;y,1] 退化，Pozar ch.10 PIN 二极管开关同式）::

       S11 = −y/(2+y)、S21 = 2/(2+y)（互易 S12=S21、S11=S22）

   关断态 y = jωC_off·Z0（插损/回损面）；导通态 y = Z0/R_on（隔离
   面）+ 功率三分：反射 |S11|²、泄漏 |S21|²、二极管吸收
   1−|S11|²−|S21|²（和=1 精确，热设计面；y=2 即 R_on=Z0/2 时吸收
   恒 50% 最大）。限幅门限一阶估计 P_th = V_f²/(2Z0)（RF 电压摆幅
   触及二极管导通电压；实际门限依载流子寿命/视频电阻上浮，记
   first-order estimate 不冒充实测）。模型边界：集总并联近似（二极管
   尺寸 ≪ λ）、封装 L/C 不在键面，docstring 如实标注。
   来源：并联导纳二口 S 闭式 Pozar《Microwave Engineering》ch.10
   （PIN 二极管开关/衰减器口径，ABCD [1,0;y,1] 退化）；门限
   V_f²/(2Z0) 为限幅器标准一阶估计（记 empirical-estimate 档）。
6. **步进衰减器（二进制位组合 + 逐位 π/T 衰减节）**（同席）：N 位、
   LSB=step_db → 量程 step_db·(2^N−1)、分辨率=step_db；目标衰减
   realized = floor(target/step) 的二进制位组合（不可表示余量
   residual 如实输出不静默吞）；逐 engaged 位 π/T 电阻闭式**单源
   消费** rf_match.attenuator_pi/attenuator_t（ABCD 校验在库，零
   公式复制，#116 教训）；堆叠误差：逐位精度规格给定时
   worst-case = Σe_i、RSS = √(Σe_i²)（计量学两口径并列输出）。
   来源：位组合/堆叠误差 = 确定性算术（仪器步进衰减器二进制加权
   结构惯例）；π/T 衰减节电阻闭式 = rf_match attenuator_pi/
   attenuator_t 单源（其出处与锚在库）。
7. **倍频链预算（级联 ×M_i）**（同席）：f_out = f_in·∏M_i；理想倍频
   相噪劣化律 L_out(f) = L_in(f) + 20·log10(N)（N=∏M_i；逐级累计
   同律：20log10 逐级相加恰 = 总倍次单式，测试面恒等钉）；级联转换
   损耗/dBm 预算 = 逐级 dB 算术（Friis 同口径）；可选逐级剩余相噪
   地板（同偏移）功率和 10·log10(Σ10^(r_i/10))——单列输出不与理想
   律强行合并（合并需链输入相噪，键面不冒充）。谐波杂散枚举归
   spur_search（混频 RF/LO/IF 乘积域，边界防撞），本键不做。
   来源：20log10(N) 倍频相噪劣化律 = W. P. Robins《Phase Noise in
   Signal Sources》ch.2（教科书律，Rubiola 同式转引口径）；级联 dB
   预算 = Friis 口径（cascade_budget 同式不同域：本键=倍频频率变换
   面，边界见 docstring）。

数值锚（#118 独立来源；锚树 tests/unit/test_w7a_pa_qubit.py）
- 平衡对：同管 S11,bal 逐位 0；异管 (S11a−S11b)/2 测试侧复数重算
  逐位回收；单管失效 → RL=6.0206 dB/增益 −6.0206 dB；相位容差
  Γ=0.2/RL=20dB → Δφ_max=60° 边界逐位（0.2·sin30°=0.1）。
- Doherty 网络：R_opt=100Ω → R_L=50Ω/Z_T=100Ω/Z_BO=200Ω；Z_BO 对
  Z0=50 归一恰 4:1；10·log10(4)=6.0206 dB 回退恒等；ABCD 级联
  （A=D=0、B=jZ_T、C=j/Z_T）回代 Z_T²/Z_L 与 quarter_wave_invert
  逐位互证。
- 效率曲线：η(PBO=6.0206dB) = π/4（1e-12）；η(0dB) = π/4；网格
  argmin ≈ 2π/9 @ PBO ≈ 3.5218 dB；η ≥ 单管 B 类逐点。
- ET（W3-CORE3 独立复算锚，2026-10-13）：f=0 → π/4 逐位（ξ=2）；
  f=0.1/ξ=4（6.0206dB）→ 0.785188；f=0.2/ξ=8（9.0309dB）→ 0.773744；
  f=1/ξ=4 → 0.437042 = 定供对照逐位（结构恒等）；scipy 数值积分第二
  路线 ≤1.3e-9；η_ET(f) ≥ η_fixed 全域栅格单调；f=1/ξ=2 →
  0.567678 = 定供对照逐位。
- PIN（同席）：C_off=0.1pF@10GHz/50Ω → |S21|=0.987887、
  IL=0.105857 dB、|S11|=0.155177；R_on=1Ω → 隔离 28.299467 dB、
  反射 92.4556%/泄漏 0.14793%/吸收 7.3964%（和=1 逐位）；R_on=Z0/2
  → 吸收恰 50%（功率三分最大点，S21=Γ=−0.5）；V_f=0.7V/50Ω → 门限
  6.901961 dBm（10log10(0.49/0.1/2·1000)=10log10(4.9)）。
- 步进（同席）：5 位 LSB=1 目标 31 → 全位 engaged、realized=31、
  residual=0（量程 31dB）；10.5 → realized=10、residual=0.5（量化
  余量如实）；π 10dB/50Ω → 串 71.151Ω/并 96.248Ω（镜像阻抗
  A=(N+1/N)/2 回代在库）；精度 [0.2,0.2,0.3,0.5,0.8] 全位 →
  worst-case 2.0 / RSS 1.029563。
- 倍频链（同席）：×2×3×2 → N=12、20log10(12)=21.583625 dB；逐级
  累计 6.020600/15.563025/21.583625（恒等式 Σ20log10(M_i)
  =20log10(∏M_i) 逐位）；0dBm+逐级 [7,7,3] dB → −17 dBm；
  残差地板 [−130,−128] → 功率和 10log10(10^−13+10^−12.8)
  = −125.875574 dBc；×2×2 与 ×4 单级同 12.041200 dB（分解不变性）。

守卫：反射幅值 ∈ [0,1]（|S11|>1 非物理显式拒绝）；相位有限；
hybrid_il_db ≥ 0；r_opt_ohm/z0_ohm > 0；backoff_db 偏离经典
10·log10(4)=6.0206 dB 超 0.05 显式拒绝（非等功率口径不外推）；
n_points/pbo_max_db 域守卫；越界一律显式报错不静默。
W3-CORE3 四键守卫：papr_db ∈ [0,15]（<0 非物理拒绝，>15 超
Rayleigh 模型有效域拒绝）；supply_floor_frac ∈ [0,1]（f>1 拒绝）；
f_ghz/C_off/R_on/Z0/V_f 有限正值；attenuation_db ≥ 0 且 ≤ 量程
（超量程显式拒绝不回卷）；step_db > 0、n_bits ∈ [1,8]（int，bool
拒绝）、pad_topology ∈ {pi,t}、per_step_accuracy_db 逐项 ≥0 且
长度=n_bits；factors 逐项 int ∈ [2,64]、1..8 级、N=∏M ≤ 65536、
loss/residual 有限（loss ≥0）、可选列表长度=级数；数值 0.0 合法面
判缺失一律 is not None（#364④）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator

#: 经典 2-Way 等功率 Doherty 合并点回退（10·log10(4)，dB）
_CLASSIC_BACKOFF_DB = 10.0 * math.log10(4.0)
#: 经典口径容差（合并点回退一致性守卫）
_BACKOFF_TOL_DB = 0.05
#: 单管失效最坏输入回损（|S11,bal|=1/2 → −20log10(1/2)，正 dB 口径）
_FAILED_DEVICE_RL_DB = -20.0 * math.log10(0.5)
#: 单管失效增益跌落（S21,bal=S21/2 → 负 dB）
_FAILED_DEVICE_GAIN_DROP_DB = 20.0 * math.log10(0.5)
#: 默认目标回损（相位容差字段口径）
_DEFAULT_TARGET_RL_DB = 20.0

_SOURCE_BALANCED = (
    "Kurokawa 90° 杂交平衡对消口径; Cripps《RF Power Amplifiers for "
    "Wireless Communications》2nd ed. 平衡架构节（失效容忍 6.02dB 口径）")
_SOURCE_DOHERTY_NET = (
    "Cripps ARMMS 'Revisiting the Doherty PA' 2008（Z0=2R、R=Ropt/2）"
    "+ 2nd ed. Doherty 节; 单源消费 core/pa_architectures."
    "doherty_design_impedances + quarter_wave_invert（λ/4 ABCD 退化）")
_SOURCE_DOHERTY_ETA = (
    "Cripps ARMMS 2008 两区域闭式（Notes 7：凹陷深度依辅管实现）；"
    "单源消费 core/pa_architectures.doherty_efficiency（严格 B 类口径）")


def _finite(value: Any, name: str, key: str) -> float:
    """入参收敛为有限 float（bool 显式拒收，df7+⑯ float(True) 污染口径）。"""
    if isinstance(value, bool):
        raise ValueError(f"{key}: {name} 不接受 bool（float(True)=1.0 静默污染）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{key}: {name} 必须为有限数，得到 {value!r}")
    return out


def _reflection(value: Any, name: str, key: str) -> float:
    """反射幅值守卫：∈ [0,1]（线性幅度，非 dB）。"""
    out = _finite(value, name, key)
    if out < 0.0 or out > 1.0:
        raise ValueError(
            f"{key}: {name} 必须为 [0,1] 内线性幅度（|S11|>1 非物理），"
            f"得到 {value!r}")
    return out


def _phase_deg(value: Any, name: str, key: str) -> float:
    """相位输入域守卫：|deg| ≤ 360（相位周期等价，但越窗输入一律拒绝
    防口径歧义——400° 静默折叠成 40° 是输入契约失败，不外推）。"""
    out = _finite(value, name, key)
    if abs(out) > 360.0:
        raise ValueError(
            f"{key}: {name} 输入契约 |deg|≤360（周期等价角不折叠，越窗"
            f"拒绝防口径歧义），得到 {value!r}")
    return out


def _sparam_complex(mag: float, deg: float) -> complex:
    """(线性幅值, 相位 deg) → 复数 S 参数值。"""
    return mag * complex(math.cos(math.radians(deg)), math.sin(math.radians(deg)))


def _cx_dict(z: complex) -> dict[str, Any]:
    """复数 → JSON 可序列化字典（re/im 线性 + mag/deg 展示面）。

    re/im 保留 12 位（恒等式回收锚用，rel 1e-9 判据下无损）；mag=0 时
    deg 记 0.0、rl_db 记 None（完美对消显式语义，不冒充 −inf）。
    """
    mag = abs(z)
    deg = math.degrees(math.atan2(z.imag, z.real)) if mag > 0.0 else 0.0
    rl_db = (-20.0 * math.log10(mag)) if mag > 0.0 else None
    return {
        "re": round(z.real, 12),
        "im": round(z.imag, 12),
        "mag": round(mag, 12),
        "deg": round(deg, 9),
        "rl_db": round(rl_db, 6) if rl_db is not None else None,
    }


# ─── 键 1：平衡放大器对 S 参数合成 ───────────────────────────────────────────


@register_calculator(
    "balanced_pair_sparams",
    "平衡对S参数合成：平衡放大器对 S 参数合成（90° 杂交 Kurokawa 口径，G11）：两管单管"
    "S 参数 → 平衡对合成 S 参数。恒等式：S11,bal=(S11a−S11b)/2（同管"
    "→ 严格 0 反射对消）、S21,bal=(S21a+S21b)/2（同管 → 增益=单管）、"
    "S22,bal 输出侧同恒等式。B 管参数缺省=A 管值（同管口径）。失配"
    "容忍度字段：单管失效 → 输入回损 6.0206 dB 上界+增益 −6.0206 dB"
    "（失效不灾难性失配）；同幅反射管对相位容差 Δφ_max="
    "2·arcsin(10^(−RL/20)/Γ)。hybrid_il_db 为每只混合器插损（缺省 0="
    "理想混合器；增益按 −2×IL 修正）。守卫：反射幅值∈[0,1]",
    (("s11a_mag", "float A 管输入反射线性幅值（[0,1]）"),
     ("s21a_db", "float dB A 管增益 |S21|（dB，正=放大）"),
     ("s11a_deg", "float deg A 管 S11 相位（缺省 0）"),
     ("s21a_deg", "float deg A 管 S21 相位（缺省 0）"),
     ("s11b_mag", "float B 管输入反射幅值（缺省=A 管：同管口径）"),
     ("s11b_deg", "float deg B 管 S11 相位（缺省=A 管）"),
     ("s21b_db", "float dB B 管增益（缺省=A 管）"),
     ("s21b_deg", "float deg B 管 S21 相位（缺省=A 管）"),
     ("s22a_mag", "float A 管输出反射幅值（缺省=s11a_mag：只回损一手"
      "数据时的镜像口径，note 如实标注）"),
     ("s22a_deg", "float deg A 管 S22 相位（缺省=s11a_deg）"),
     ("s22b_mag", "float B 管输出反射幅值（缺省=B 管 S11 同口径）"),
     ("s22b_deg", "float deg B 管 S22 相位（缺省=B 管 S11 同口径）"),
     ("hybrid_il_db", "float dB 每只 90° 混合器插损（≥0，缺省 0=理想；"
      "增益按 −2×IL 修正）"),
     ("target_rl_db", "float dB 相位容差字段的目标回损（>0，缺省 20）")),
    required=("s11a_mag", "s21a_db"),
)
def balanced_pair_sparams(
    s11a_mag: float,
    s21a_db: float,
    s11a_deg: float = 0.0,
    s21a_deg: float = 0.0,
    s11b_mag: float | None = None,
    s11b_deg: float | None = None,
    s21b_db: float | None = None,
    s21b_deg: float | None = None,
    s22a_mag: float | None = None,
    s22a_deg: float | None = None,
    s22b_mag: float | None = None,
    s22b_deg: float | None = None,
    hybrid_il_db: float = 0.0,
    target_rl_db: float = _DEFAULT_TARGET_RL_DB,
) -> dict[str, Any]:
    key = "balanced_pair_sparams"
    g_a = _reflection(s11a_mag, "s11a_mag", key)
    g_a_deg = _phase_deg(s11a_deg, "s11a_deg", key)
    s21_a_db = _finite(s21a_db, "s21a_db", key)
    s21_a_deg = _phase_deg(s21a_deg, "s21a_deg", key)

    # B 管缺省=A 管（同管口径——反射对消恒等式的严格 0 路径）
    g_b = g_a if s11b_mag is None else _reflection(s11b_mag, "s11b_mag", key)
    g_b_deg = (g_a_deg if s11b_deg is None
                 else _phase_deg(s11b_deg, "s11b_deg", key))
    s21_b_db = s21_a_db if s21b_db is None else _finite(s21b_db, "s21b_db", key)
    s21_b_deg = (s21_a_deg if s21b_deg is None
                 else _phase_deg(s21b_deg, "s21b_deg", key))
    # 输出侧缺省镜像输入侧（只回损一手数据口径，如实标注）
    s22_source = "explicit" if s22a_mag is not None else "mirrored_from_s11"
    a22_mag = (g_a if s22a_mag is None
               else _reflection(s22a_mag, "s22a_mag", key))
    a22_deg = (g_a_deg if s22a_deg is None
               else _phase_deg(s22a_deg, "s22a_deg", key))
    b22_mag = (g_b if s22b_mag is None
               else _reflection(s22b_mag, "s22b_mag", key))
    b22_deg = (g_b_deg if s22b_deg is None
               else _phase_deg(s22b_deg, "s22b_deg", key))

    il_db = _finite(hybrid_il_db, "hybrid_il_db", key)
    if il_db < 0.0:
        raise ValueError(f"{key}: hybrid_il_db 必须 ≥0，得到 {hybrid_il_db!r}")
    rl_target = _finite(target_rl_db, "target_rl_db", key)
    if rl_target <= 0.0:
        raise ValueError(f"{key}: target_rl_db 必须 >0，得到 {target_rl_db!r}")

    s11a = _sparam_complex(g_a, g_a_deg)
    s11b = _sparam_complex(g_b, g_b_deg)
    s21a = _sparam_complex(10.0 ** (s21_a_db / 20.0), s21_a_deg)
    s21b = _sparam_complex(10.0 ** (s21_b_db / 20.0), s21_b_deg)
    s22a = _sparam_complex(a22_mag, a22_deg)
    s22b = _sparam_complex(b22_mag, b22_deg)

    # 理想 90° 杂交平衡对恒等式（模块 docstring 推导口径）
    s11_bal = (s11a - s11b) / 2.0
    s21_bal = (s21a + s21b) / 2.0
    s22_bal = (s22a - s22b) / 2.0

    gain_bal_db = 20.0 * math.log10(abs(s21_bal)) - 2.0 * il_db
    identical = (abs(s11a - s11b) <= 1e-15 and abs(s21a - s21b) <= 1e-15)

    # 失配容忍度：单管失效（|Γ|=1、另一管匹配）+ 相位容差面
    gamma_ref = max(abs(s11a), abs(s11b))
    gamma_lin = 10.0 ** (-rl_target / 20.0)
    if gamma_ref <= 0.0:
        phase_tol_deg: float | None = None
        phase_note = "两管均完美匹配（Γ=0）：任意相位差下回损无究大"
    elif gamma_lin >= gamma_ref:
        phase_tol_deg = None
        phase_note = (
            f"同幅反射 Γ={gamma_ref:.4g} 的最坏相位对消残差 {gamma_ref:.4g} "
            f"已满足目标回损 {rl_target:.4g} dB——相位容差无上界")
    else:
        phase_tol_deg = math.degrees(
            2.0 * math.asin(gamma_lin / gamma_ref))
        phase_note = (
            f"同幅反射 Γ={gamma_ref:.4g} 管对 |S11,bal|=Γ·|sin(Δφ/2)|："
            f"回损 ≥{rl_target:.4g} dB 的相位容差 Δφ ≤ "
            f"{phase_tol_deg:.4f}°")

    return {
        "s11_bal": _cx_dict(s11_bal),
        "s21_bal": _cx_dict(s21_bal),
        "s22_bal": _cx_dict(s22_bal),
        "gain_bal_db": round(gain_bal_db, 6),
        "s22_source": s22_source,
        "hybrid_il_db": round(il_db, 6),
        "identical_devices": bool(identical),
        "gamma_ref": round(gamma_ref, 12),
        "mismatch_tolerance": {
            "failed_device_rl_db": round(_FAILED_DEVICE_RL_DB, 6),
            "failed_device_gain_drop_db": round(
                _FAILED_DEVICE_GAIN_DROP_DB, 6),
            "failed_device_note": (
                "单管开路/短路（|Γ|=1）、另一管匹配：|S11,bal|=1/2 → "
                "输入回损 6.0206 dB 上界；增益 S21,bal=S21/2 → −6.0206 dB"
                "（失效容忍口径，非灾难性失配）"),
            "target_rl_db": round(rl_target, 6),
            "max_phase_mismatch_deg": (
                round(phase_tol_deg, 6) if phase_tol_deg is not None
                else None),
            "phase_note": phase_note,
        },
        "source": _SOURCE_BALANCED,
    }


# ─── 键 2：经典 2-Way 等功率 Doherty 合路网络 ────────────────────────────────


@register_calculator(
    "doherty_combining_network",
    "Doherty合路网络：经典 2-Way 等功率 Doherty 合路 λ/4 网络综合（G11，口径写死）："
    "给单管最优负载 R_opt → 合路节点负载 R_L=R_opt/2、载波臂 λ/4 "
    "逆变器特征阻抗 Z_T=R_opt=2R_L、回退点载波视入 Z_BO=Z_T²/R_L="
    "2R_opt（Cripps ARMMS 2008：Z0=2R、R=Ropt/2）；合并点回退固定 "
    "10·log10(4)=6.0206 dB、功分比 50/50。λ/4 反演 Z_in=Z_T²/Z_L 走 "
    "core 单源（ABCD βl=π/2 精确退化）并回代自洽；peak 臂偏置线"
    "（90°@f0、Z=Z_T 惯例口径，实现相关非唯一）如实标注。"
    "backoff_db 偏离经典值超 0.05dB 显式拒绝（非等功率口径不外推）",
    (("r_opt_ohm", "float Ω 单管最优基波负载 R_opt=V_dd/I_1（>0）"),
     ("z0_ohm", "float Ω 系统阻抗（归一化展示面，缺省 50）"),
     ("backoff_db", "float dB 合并点回退（缺省=经典 6.0206；偏离超 "
      "0.05dB 显式拒绝）")),
    required=("r_opt_ohm",),
)
def doherty_combining_network(
    r_opt_ohm: float,
    z0_ohm: float = 50.0,
    backoff_db: float | None = None,
) -> dict[str, Any]:
    key = "doherty_combining_network"
    r_opt = _finite(r_opt_ohm, "r_opt_ohm", key)
    if r_opt <= 0.0:
        raise ValueError(f"{key}: r_opt_ohm 必须 >0，得到 {r_opt_ohm!r}")
    z0 = _finite(z0_ohm, "z0_ohm", key)
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    if backoff_db is not None:
        bo = _finite(backoff_db, "backoff_db", key)
        if abs(bo - _CLASSIC_BACKOFF_DB) > _BACKOFF_TOL_DB:
            raise ValueError(
                f"{key}: backoff_db={bo:.4f} 偏离经典 2-Way 等功率合并点 "
                f"10·log10(4)={_CLASSIC_BACKOFF_DB:.4f} dB 超 "
                f"{_BACKOFF_TOL_DB} dB 容差——非等功率口径需非对称管径/"
                "峰值臂偏置线修正，本键不实现，显式拒绝不外推")

    # 设计关系单源消费（Cripps：Z0=2R、R=Ropt/2）
    from rfauto.core.pa_architectures import (
        doherty_design_impedances,
        quarter_wave_invert,
    )

    design = doherty_design_impedances(r_opt)
    r_load = design["r_load"]
    z_t = design["z_t"]

    # 回退点载波视入负载：λ/4 反演恒等式回代自洽（ABCD 级联回收锚）
    z_bo = quarter_wave_invert(complex(r_load, 0.0), z_t)
    z_bo_expected = 2.0 * r_opt
    roundtrip_ok = abs(abs(z_bo) - z_bo_expected) <= 1e-9 * z_bo_expected

    return {
        "r_opt_ohm": round(r_opt, 9),
        "z0_ohm": round(z0, 9),
        "r_load_ohm": round(r_load, 9),
        "z_t_ohm": round(z_t, 9),
        "r_load_over_z0": round(r_load / z0, 9),
        "z_t_over_z0": round(z_t / z0, 9),
        "power_split_carrier_pct": 50.0,
        "power_split_peak_pct": 50.0,
        "power_split_note": "等功率 2-Way 口径（输入功分器同比 50/50）",
        "combine_backoff_db": round(_CLASSIC_BACKOFF_DB, 6),
        "z_backoff_carrier_ohm": {
            "re": round(z_bo.real, 9),
            "im": round(z_bo.imag, 12),
            "mag": round(abs(z_bo), 9),
        },
        "abcd_roundtrip": {
            "z_in_expected_ohm": round(z_bo_expected, 9),
            "matches": bool(roundtrip_ok),
            "note": "Z_in=Z_T²/Z_L（λ/4 ABCD βl=π/2 精确退化；测试侧"
                    "独立 ABCD 级联回代互证，锚树 test_w7a_pa_qubit.py）",
        },
        "identities": {
            "z_t_eq_2r_load": bool(z_t == 2.0 * r_load),
            "r_load_eq_r_opt_half": bool(r_load == r_opt / 2.0),
        },
        "inverter": {
            "electrical_deg_at_f0": 90.0,
            "z_t_ohm": round(z_t, 9),
            "note": "载波臂 λ/4 逆变器（Z_in=Z_T²/Z_L）：回退点把合路"
                    "负载 R_L 反演为 2R_opt，负载调制的全部要义",
        },
        "peak_offset_line": {
            "electrical_deg_at_f0": 90.0,
            "z_t_ohm": round(z_t, 9),
            "note": "peak 臂偏置线（offset line）：补偿辅管截止态输出"
                    "电抗；特征阻抗取 Z_T 为惯例口径，实现相关非唯一"
                    "（Cripps Doherty 节），如实标注",
        },
        "operating_points": {
            "peak": "两管满驱各入 R_opt（同摆幅 V_dd，各给 V_dd·I_1/2）",
            "backoff": "辅管截止呈开路，载波视入 2R_opt：满电压摆幅、"
                       "电流减半 → 效率第二拐点",
        },
        "source": _SOURCE_DOHERTY_NET,
    }


# ─── 键 3：理想 B 类 Doherty 效率-回退曲线（单源消费 core） ──────────────────


@register_calculator(
    "doherty_efficiency_curve",
    "Doherty效率曲线：理想 B 类 Doherty 效率-回退曲线（G11，单源消费 core/pa_architectures"
    " 两区域闭式，Cripps ARMMS 2008 口径）：区域 I（σ≤1/2 辅管截止）"
    "η=(π/2)σ、区域 II η=πσ²/[2(3σ−1)]，σ=√(P/P_pk)。双拐点锚：η(σ=1)"
    "=η(σ=1/2)=π/4≈78.54% 逐位（峰值与 6.0206dB 合并点）；中段凹陷"
    "严格极小 2π/9≈69.81% 在 σ=2/3（PBO≈3.5218dB，独立求导锚）——"
    "凹陷深度依辅管实现（Cripps Notes 7 原文），本键采用严格 B 类口径"
    "如实报告凹陷、不冒充全平平台。对照列：单管 B 类 (π/4)√p 三角"
    "衰减律+逐点 doherty_ge_class_b 判读",
    (("n_points", "int 回退轴点数（[2,1001]，缺省 41；PBO 0→pbo_max_db"
      " 均匀栅格）"),
     ("pbo_max_db", "float dB 回退轴上限（(0,30]，缺省 10）")),
)
def doherty_efficiency_curve_key(
    n_points: int = 41,
    pbo_max_db: float = 10.0,
) -> dict[str, Any]:
    key = "doherty_efficiency_curve"
    if isinstance(n_points, bool) or not isinstance(n_points, int):
        raise ValueError(f"{key}: n_points 必须为 int，得到 {n_points!r}")
    if n_points < 2 or n_points > 1001:
        raise ValueError(f"{key}: n_points 须在 [2,1001]，得到 {n_points!r}")
    pbo_max = _finite(pbo_max_db, "pbo_max_db", key)
    if pbo_max <= 0.0 or pbo_max > 30.0:
        raise ValueError(
            f"{key}: pbo_max_db 须在 (0,30]，得到 {pbo_max_db!r}")

    # 单源消费（core/pa_architectures 两区域闭式 + B 类对照 + 锚常量）
    from rfauto.core.pa_architectures import (
        DOHERTY_ETA_DIP_MIN,
        DOHERTY_SIGMA_COMBINE,
        DOHERTY_SIGMA_DIP,
        ETA_CLASS_B_PEAK,
        class_b_efficiency_from_power_ratio,
        doherty_efficiency,
    )

    step = pbo_max / (n_points - 1)
    pbo_axis = [i * step for i in range(n_points)]
    sigmas = [10.0 ** (-p / 20.0) for p in pbo_axis]
    etas = [doherty_efficiency(s) for s in sigmas]
    class_b = [class_b_efficiency_from_power_ratio(s * s) for s in sigmas]

    knee_eta = doherty_efficiency(DOHERTY_SIGMA_COMBINE)
    knee_pbo_db = -20.0 * math.log10(DOHERTY_SIGMA_COMBINE)
    dip_pbo_db = -20.0 * math.log10(DOHERTY_SIGMA_DIP)
    # 区域 II 栅格凹陷（σ≥1/2 段极小——全局极小在低功率端是 B 类线性
    # 衰减尾巴，非"中段凹陷"；凹陷锚只对区域 II 段取，语义如实）
    dip_in_span = bool(pbo_max >= knee_pbo_db)
    if dip_in_span:
        region2 = [(p, e) for p, s, e in zip(pbo_axis, sigmas, etas,
                                             strict=True) if s >= 0.5]
        dip_pbo_grid, dip_eta_grid = min(region2, key=lambda t: t[1])
    else:
        dip_pbo_grid, dip_eta_grid = None, None

    return {
        "pbo_db": [round(p, 9) for p in pbo_axis],
        "sigma": [round(s, 12) for s in sigmas],
        "eta": [round(e, 12) for e in etas],
        "class_b_eta": [round(e, 12) for e in class_b],
        "eta_peak": round(ETA_CLASS_B_PEAK, 12),
        "eta_knee": round(knee_eta, 12),
        "knee_pbo_db": round(knee_pbo_db, 6),
        "eta_dip_min": round(DOHERTY_ETA_DIP_MIN, 12),
        "dip_pbo_db": round(dip_pbo_db, 6),
        "dip_grid_eta": (round(dip_eta_grid, 12)
                         if dip_eta_grid is not None else None),
        "dip_grid_pbo_db": (round(dip_pbo_grid, 9)
                            if dip_pbo_grid is not None else None),
        "dip_in_span": dip_in_span,
        "flags": {
            "eta_bounds_ok": bool(
                all(0.0 <= e <= ETA_CLASS_B_PEAK + 1e-12 for e in etas)),
            "doherty_ge_class_b": bool(all(
                d >= c - 1e-12 for d, c in zip(etas, class_b, strict=True))),
            "knee_identity_ok": bool(
                abs(knee_eta - ETA_CLASS_B_PEAK) <= 1e-12),
        },
        "convention_note": (
            "严格 B 类口径：η(σ=1)=η(σ=1/2)=π/4 双拐点逐位、中段凹陷 "
            "2π/9 为'理想线性辅管电流+严格 B 类直流'的严格解内禀属性；"
            "文献'全平平台'是辅管电流波形优化的理想化上界，不采用"
            "（无权威闭式不臆造，core/pa_architectures 诚实边界同口径）"),
        "source": _SOURCE_DOHERTY_ETA,
    }


# ─── 键 4：ET 包络跟踪效率（批 B Wave3 W3-CORE3）─────────────────────────────

_SOURCE_ET = (
    "点态 B 类效率 Cripps《RF Power Amplifiers for Wireless "
    "Communications》2nd ed. ch.5（π/4 口径）；ET 架构=包络跟踪高效率"
    "发射机标准文献（概念级）；Rayleigh 包络=通信信号标准统计模型；"
    "含供电下限/硬削顶的平均效率闭式（式 ET1）=本仓独立推导"
    "（#118 第二路线=测试面 scipy 数值积分独立裁判，实测 ≤1.3e-9）")


@register_calculator(
    "envelope_tracking_efficiency",
    "ET包络跟踪效率：理想 B 类包络跟踪平均漏极效率闭式（Rayleigh 包络"
    "+供电下限 f+轨上硬削顶）：η=(π/4)(1−e^−ξ)/[e^−ξf²−e^−ξ+"
    "(√(πξ)/2)f·erf(f√ξ)]，ξ=PAPR 线性。双结构锚：f=0 → η=π/4 与 "
    "PAPR 无关（ET 全部要义）；f=1 → 逐位退化为定供 B 类对照 "
    "η_fixed（随行输出）。能量口径 E[Pout]/E[Pdc]；η_ET ≥ η_fixed "
    "全域（供电恒不高于定供）。门限/削顶概率随行",
    (("papr_db", "float dB 信号峰均比（[0,15]；<0 非物理、>15 超 "
      "Rayleigh 包络模型有效域）"),
     ("supply_floor_frac", "float - 供电下限占满摆幅份额 f（[0,1]；"
      "0=理想全程跟踪，1=无跟踪退化档；缺省 0.1=典型 ET 面口径）")),
    required=("papr_db",),
)
def envelope_tracking_efficiency(
    papr_db: float,
    supply_floor_frac: float = 0.1,
) -> dict[str, Any]:
    key = "envelope_tracking_efficiency"
    p = _finite(papr_db, "papr_db", key)
    if p < 0.0:
        raise ValueError(
            f"{key}: papr_db 必须 ≥0（峰均比低于 0dB 非物理），得到 "
            f"{papr_db!r}")
    if p > 15.0:
        raise ValueError(
            f"{key}: papr_db 必须 ≤15（Rayleigh 包络模型有效域；更高 "
            f"PAPR 的高阶统计不在本闭式键面），得到 {papr_db!r}")
    f_frac = _finite(supply_floor_frac, "supply_floor_frac", key)
    if not 0.0 <= f_frac <= 1.0:
        raise ValueError(
            f"{key}: supply_floor_frac 必须 ∈ [0,1]（0=理想全程跟踪、"
            f"1=无跟踪退化档），得到 {supply_floor_frac!r}")

    xi = 10.0 ** (p / 10.0)
    e_neg_xi = math.exp(-xi)
    e_neg_xi_f2 = math.exp(-xi * f_frac * f_frac)
    denom = (e_neg_xi_f2 - e_neg_xi
             + math.sqrt(math.pi * xi) / 2.0 * f_frac
             * math.erf(f_frac * math.sqrt(xi)))
    eta_et = (math.pi / 4.0) * (1.0 - e_neg_xi) / denom
    # 定供 B 类对照（能量口径）：η_fixed=(π/4)E[v²]/E[v]
    eta_fixed = (math.sqrt(math.pi) / (2.0 * math.sqrt(xi))
                 * (1.0 - e_neg_xi) / math.erf(math.sqrt(xi)))

    return {
        "papr_db": round(p, 9),
        "papr_linear": round(xi, 12),
        "supply_floor_frac": round(f_frac, 9),
        "eta_et": round(eta_et, 12),
        "eta_et_pct": round(eta_et * 100.0, 9),
        "eta_fixed_supply": round(eta_fixed, 12),
        "et_gain_db": round(10.0 * math.log10(eta_et / eta_fixed), 9),
        "clipping_prob": round(e_neg_xi, 12),
        "supply_floor_prob": round(1.0 - e_neg_xi_f2, 12),
        "degenerate_note": (
            "f=1（无跟踪）档 η 恒等于 eta_fixed_supply（结构恒等式，"
            "锚树测试逐位钉）；f=0（理想跟踪）档 η 恒=π/4 与 PAPR 无关"
            "——ET 的全部要义（B 类点态 η=(π/4)(Vo/Vs)，供电跟踪后恒"
            "工作在峰效点）"),
        "model_note": (
            "理想 B 类+Rayleigh 包络+轨上硬削顶能量口径；不含 knee "
            "电压/供电调制损耗/增益平坦度等实现非理想（实测 ET 漏效"
            "低于本上界，方向如实标注）；clipping_prob=包络质量落在轨"
            "上的概率 e^−ξ；supply_floor_prob=供电贴下限概率 1−e^−ξf²"),
        "source": _SOURCE_ET,
    }


# ─── 键 5：PIN 二极管并联限幅器（批 B Wave3 W3-CORE3）────────────────────────

_SOURCE_PIN = (
    "并联导纳二口 S 闭式 Pozar《Microwave Engineering》ch.10（PIN "
    "二极管开关/衰减器口径，ABCD [1,0;y,1] 退化）；限幅门限 V_f²/(2Z0) "
    "为限幅器标准一阶估计（first-order estimate 档，非实测口径）")


@register_calculator(
    "pin_diode_limiter",
    "PIN二极管限幅器：并联 PIN 二极管限幅器两态线性口径——关断态"
    "（y=jωC_off·Z0）插损/回损、导通态（y=Z0/R_on）隔离与功率三分"
    "（反射/泄漏/二极管吸收，和=1 精确；R_on=Z0/2 吸收恒 50% 最大）"
    "+限幅门限一阶估计 P_th=V_f²/(2Z0)。互易 S11=S22、S12=S21；"
    "集总并联近似（二极管 ≪λ）、封装 L/C 不在键面",
    (("f_ghz", "float GHz 工作频率（>0；集总并联近似有效域）"),
     ("r_on_ohm", "float Ω 导通态串联电阻 R_on（>0，缺省 1=典型 PIN "
      "导通档）"),
     ("c_off_pf", "float pF 关断态结电容 C_off（>0，缺省 0.1=典型零偏"
      "结电容档）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）"),
     ("v_forward_v", "float V 二极管导通电压 V_f（>0，缺省 0.7=硅 "
      "PIN 典型；门限为一阶估计）")),
    required=("f_ghz",),
)
def pin_diode_limiter(
    f_ghz: float,
    r_on_ohm: float = 1.0,
    c_off_pf: float = 0.1,
    z0_ohm: float = 50.0,
    v_forward_v: float = 0.7,
) -> dict[str, Any]:
    key = "pin_diode_limiter"
    freq = _finite(f_ghz, "f_ghz", key)
    if freq <= 0.0:
        raise ValueError(f"{key}: f_ghz 必须 >0，得到 {f_ghz!r}")
    r_on = _finite(r_on_ohm, "r_on_ohm", key)
    if r_on <= 0.0:
        raise ValueError(f"{key}: r_on_ohm 必须 >0，得到 {r_on_ohm!r}")
    c_off = _finite(c_off_pf, "c_off_pf", key)
    if c_off <= 0.0:
        raise ValueError(f"{key}: c_off_pf 必须 >0，得到 {c_off_pf!r}")
    z0 = _finite(z0_ohm, "z0_ohm", key)
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    v_f = _finite(v_forward_v, "v_forward_v", key)
    if v_f <= 0.0:
        raise ValueError(f"{key}: v_forward_v 必须 >0，得到 {v_forward_v!r}")

    def _shunt_s(y_norm: complex) -> tuple[complex, complex]:
        """并联导纳二口 S：S11=−y/(2+y)、S21=2/(2+y)（ABCD [1,0;y,1]）。"""
        s11 = -y_norm / (2.0 + y_norm)
        s21 = 2.0 / (2.0 + y_norm)
        return s11, s21

    # 关断态：结电容并联（集总近似）
    y_off = 1j * 2.0 * math.pi * (freq * 1e9) * (c_off * 1e-12) * z0
    s11_off, s21_off = _shunt_s(y_off)
    il_db = -20.0 * math.log10(abs(s21_off))
    rl_db = -20.0 * math.log10(abs(s11_off))

    # 导通态：R_on 并联（隔离+功率三分，无源网络能量守恒精确）
    y_on = z0 / r_on
    s11_on, s21_on = _shunt_s(y_on)
    refl = abs(s11_on) ** 2
    trans = abs(s21_on) ** 2
    absorbed = 1.0 - refl - trans
    iso_db = -20.0 * math.log10(abs(s21_on))

    # 限幅门限一阶估计：RF 电压摆幅触及 V_f（P=V²/(2Z0)）
    p_th_w = v_f * v_f / (2.0 * z0)
    p_th_dbm = 10.0 * math.log10(p_th_w / 1e-3)

    return {
        "f_ghz": round(freq, 9),
        "z0_ohm": round(z0, 9),
        "off_state": {
            "y_norm_re": round(y_off.real, 12),
            "y_norm_im": round(y_off.imag, 12),
            "s11": _cx_dict(s11_off),
            "s21": _cx_dict(s21_off),
            "il_db": round(il_db, 9),
            "rl_db": round(rl_db, 9),
        },
        "on_state": {
            "y_norm": round(y_on, 12),
            "s11": _cx_dict(s11_on),
            "s21": _cx_dict(s21_on),
            "iso_db": round(iso_db, 9),
            "power_split": {
                "reflected_frac": round(refl, 12),
                "leaked_frac": round(trans, 12),
                "absorbed_frac": round(absorbed, 12),
                "sum": round(refl + trans + absorbed, 12),
                "note": "反射/泄漏/二极管吸收三分（无源网络和=1 精确；"
                        "吸收份额是限幅态热设计输入；R_on=Z0/2 时吸收"
                        "恒 50% 最大——iso 升高以反射为主）",
            },
        },
        "threshold": {
            "p_th_w": round(p_th_w, 12),
            "p_th_dbm": round(p_th_dbm, 9),
            "note": "一阶估计（first-order estimate）：RF 摆幅触及 V_f "
                    "即开始自导通；实际门限依载流子寿命/视频电阻上浮，"
                    "不冒充实测口径",
        },
        "identities": {
            "reciprocal": True,
            "energy_conserved": bool(
                abs(refl + trans + absorbed - 1.0) <= 1e-12),
        },
        "model_note": (
            "集总并联近似（二极管尺寸 ≪ λ）；封装引线电感/管壳电容不在"
            "键面（高频段实测插损高于本模型，方向如实标注）；两态线性"
            "口径不含限幅动态（R_on 随功率演化属器件物理，不外推）"),
        "source": _SOURCE_PIN,
    }


# ─── 键 6：步进衰减器（批 B Wave3 W3-CORE3）──────────────────────────────────

_SOURCE_STEP = (
    "位组合/堆叠误差=确定性算术（仪器步进衰减器二进制加权结构惯例；"
    "worst-case 与 RSS 两口径计量学并列）；π/T 衰减节电阻闭式=单源消费 "
    "rf_match.attenuator_pi/attenuator_t（ABCD 校验在库，零公式复制）")

#: n_bits 上限（防组合面；工程步进衰减器 ≤6 位惯例的宽松封顶）
_N_BITS_MAX = 8
_STEP_TOPOLOGIES = ("pi", "t")


@register_calculator(
    "step_attenuator_design",
    "步进衰减器综合：二进制加权位组合（N 位、LSB=step_db → 量程 "
    "step_db·(2^N−1)、分辨率=step_db）——目标衰减 realized=floor("
    "target/step) 的位组合（量化余量 residual 如实输出），逐 engaged 位"
    "π/T 衰减节电阻闭式（单源消费 rf_match attenuator 键）+堆叠误差 "
    "worst-case/RSS 两口径（给逐位精度规格时）",
    (("attenuation_db", "float dB 目标衰减（≥0 且 ≤量程；超量程显式"
      "拒绝不回卷）"),
     ("step_db", "float dB 最低位步进 LSB（>0，缺省 1）"),
     ("n_bits", "int 位数（[1,8]，缺省 5 → 31dB 量程）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）"),
     ("pad_topology", "str 衰减节拓扑 pi|t（缺省 pi）"),
     ("per_step_accuracy_db", "list[float] 逐位精度规格（≥0 有限，长度"
      "=n_bits；可选——给定时输出 worst-case/RSS 堆叠误差）")),
    required=("attenuation_db",),
)
def step_attenuator_design(
    attenuation_db: float,
    step_db: float = 1.0,
    n_bits: int = 5,
    z0_ohm: float = 50.0,
    pad_topology: str = "pi",
    per_step_accuracy_db: list[float] | None = None,
) -> dict[str, Any]:
    key = "step_attenuator_design"
    target = _finite(attenuation_db, "attenuation_db", key)
    if target < 0.0:
        raise ValueError(
            f"{key}: attenuation_db 必须 ≥0，得到 {attenuation_db!r}")
    step = _finite(step_db, "step_db", key)
    if step <= 0.0:
        raise ValueError(f"{key}: step_db 必须 >0，得到 {step_db!r}")
    if isinstance(n_bits, bool) or not isinstance(n_bits, int):
        raise ValueError(
            f"{key}: n_bits 必须为 int，得到 {n_bits!r}")
    if not 1 <= n_bits <= _N_BITS_MAX:
        raise ValueError(
            f"{key}: n_bits 必须 ∈ [1,{_N_BITS_MAX}]，得到 {n_bits!r}")
    z0 = _finite(z0_ohm, "z0_ohm", key)
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    topo = str(pad_topology)
    if topo not in _STEP_TOPOLOGIES:
        raise ValueError(
            f"{key}: pad_topology 必须 ∈ {_STEP_TOPOLOGIES}，得到 "
            f"{pad_topology!r}")

    range_db = step * float(2 ** n_bits - 1)
    if target > range_db:
        raise ValueError(
            f"{key}: attenuation_db={target:.6g} 超出量程 {range_db:.6g} "
            f"dB（{n_bits} 位 × LSB {step:.6g} dB；超量程显式拒绝不回卷"
            "——增位或加大 LSB）")

    # 位组合：floor(target/step) 的二进制表示（量化余量如实输出）
    k_steps = math.floor(target / step + 1e-12)
    step_values = [step * float(2 ** i) for i in range(n_bits)]
    engaged = [(2 ** i) & k_steps != 0 for i in range(n_bits)]
    realized = step * float(k_steps)
    residual = abs(target - realized)

    # 逐 engaged 位衰减节电阻（单源消费 rf_match 闭式；A≤0 不可能——
    # engaged 位衰减恒 >0）
    if topo == "pi":
        from .rf_match import attenuator_pi as _pad_fn
    else:
        from .rf_match import attenuator_t as _pad_fn
    sections = []
    for i, (sv, on) in enumerate(zip(step_values, engaged, strict=True)):
        if not on:
            continue
        pad = _pad_fn(sv, z0)
        sections.append({
            "bit_index": i,
            "step_db": round(sv, 9),
            "r_series_ohm": pad.get("r_series_mid_ohm",
                                    pad.get("r_series_arm_ohm")),
            "r_shunt_ohm": pad.get("r_shunt_end_ohm",
                                   pad.get("r_shunt_mid_ohm")),
        })

    worst_db: float | None = None
    rss_db: float | None = None
    if per_step_accuracy_db is not None:
        if not isinstance(per_step_accuracy_db, (list, tuple)):
            raise ValueError(
                f"{key}: per_step_accuracy_db 须为 list[float]，得到 "
                f"{type(per_step_accuracy_db).__name__}")
        if len(per_step_accuracy_db) != n_bits:
            raise ValueError(
                f"{key}: per_step_accuracy_db 长度 "
                f"{len(per_step_accuracy_db)} ≠ n_bits={n_bits}")
        acc = [_finite(v, f"per_step_accuracy_db[{i}]", key)
               for i, v in enumerate(per_step_accuracy_db)]
        if any(v < 0.0 for v in acc):
            raise ValueError(
                f"{key}: per_step_accuracy_db 逐项须 ≥0，得到 "
                f"{per_step_accuracy_db!r}")
        engaged_acc = [a for a, on in zip(acc, engaged, strict=True) if on]
        worst_db = math.fsum(engaged_acc)
        rss_db = math.sqrt(math.fsum(a * a for a in engaged_acc))

    return {
        "attenuation_target_db": round(target, 9),
        "step_db": round(step, 9),
        "n_bits": n_bits,
        "range_db": round(range_db, 9),
        "resolution_db": round(step, 9),
        "realized_db": round(realized, 9),
        "residual_db": round(residual, 9),
        "step_values_db": [round(sv, 9) for sv in step_values],
        "engaged_bits": engaged,
        "n_engaged": int(sum(engaged)),
        "pad_topology": topo,
        "sections": sections,
        "worst_case_error_db": (round(worst_db, 9)
                                if worst_db is not None else None),
        "rss_error_db": (round(rss_db, 9) if rss_db is not None else None),
        "note": (
            "二进制加权位组合：realized=floor(target/step) 对应位之和，"
            "residual=量化余量如实输出（步进衰减器分辨率=LSB，不静默吞"
            "余量）；π 节=中点串+两端各并、T 节=上下臂各串+中点并（字段"
            "名随拓扑）；worst-case=Σe（保守上界）与 RSS=√Σe²（独立"
            "误差统计口径）并列；逐节 π/T 电阻闭式单源消费 rf_match"
            "（ABCD 校验在库），本面零公式复制"),
        "source": _SOURCE_STEP,
    }


# ─── 键 7：倍频链预算（批 B Wave3 W3-CORE3）──────────────────────────────────

_SOURCE_MULT = (
    "20log10(N) 倍频相噪劣化律 W. P. Robins《Phase Noise in Signal "
    "Sources》ch.2（教科书律，Rubiola 同式转引口径）；级联 dB 预算="
    "Friis 口径（cascade_budget 同式不同域：本键=倍频频率变换面）；"
    "谐波杂散枚举归 spur_search（边界防撞，本键不做）")

#: 倍频链级数/单级倍次/总倍次域封顶
_STAGES_MAX = 8
_FACTOR_MAX = 64
_N_TOTAL_MAX = 65536


@register_calculator(
    "multiplier_chain_budget",
    "倍频链预算：级联 ×M_i 倍频器——f_out=f_in·∏M_i、逐级频率/累计"
    "倍次/累计损耗表、理想倍频相噪劣化 20log10(N)（逐级累计恒等式 "
    "Σ20log10(M_i)=20log10(∏M_i)）+dBm 功率预算；可选逐级剩余相噪"
    "地板功率和（同偏移同频功率相加，单列不与理想律合并）。谐波杂散"
    "枚举归 spur_search，本键不做",
    (("f_in_ghz", "float GHz 输入频率（>0）"),
     ("factors", "list[int] 逐级倍次 M_i（整数 [2,64]，1..8 级，"
      "N=∏M_i ≤ 65536）"),
     ("stage_loss_db", "list[float] 逐级转换损耗 dB（≥0 有限，长度="
      "级数；缺省全 0=理想倍频档）"),
     ("pin_dbm", "float dBm 输入功率（可选；给定时输出 pout_dbm）"),
     ("stage_residual_pn_dbc_hz", "list[float] 逐级剩余相噪地板 dBc/Hz"
      "（有限，长度=级数，同偏移口径；可选——给定时输出功率和）")),
    required=("f_in_ghz", "factors"),
)
def multiplier_chain_budget(
    f_in_ghz: float,
    factors: list[int],
    stage_loss_db: list[float] | None = None,
    pin_dbm: float | None = None,
    stage_residual_pn_dbc_hz: list[float] | None = None,
) -> dict[str, Any]:
    key = "multiplier_chain_budget"
    f_in = _finite(f_in_ghz, "f_in_ghz", key)
    if f_in <= 0.0:
        raise ValueError(f"{key}: f_in_ghz 必须 >0，得到 {f_in_ghz!r}")
    if not isinstance(factors, (list, tuple)):
        raise ValueError(
            f"{key}: factors 须为 list[int]，得到 {type(factors).__name__}")
    if not 1 <= len(factors) <= _STAGES_MAX:
        raise ValueError(
            f"{key}: 级数必须 ∈ [1,{_STAGES_MAX}]，得到 {len(factors)!r}")
    m_list: list[int] = []
    for i, m in enumerate(factors):
        if isinstance(m, bool) or not isinstance(m, int):
            raise ValueError(
                f"{key}: factors[{i}] 必须为 int，得到 {m!r}")
        if not 2 <= m <= _FACTOR_MAX:
            raise ValueError(
                f"{key}: factors[{i}] 必须 ∈ [2,{_FACTOR_MAX}]（×1 非倍"
                f"频级拒绝），得到 {m!r}")
        m_list.append(m)
    n_total = int(math.prod(m_list))
    if n_total > _N_TOTAL_MAX:
        raise ValueError(
            f"{key}: 总倍次 N={n_total} 超 {_N_TOTAL_MAX} 封顶（毫米波/"
            f"THz 链实用域；更高倍次链逐级核算），得到 {factors!r}")

    if stage_loss_db is not None:
        if not isinstance(stage_loss_db, (list, tuple)):
            raise ValueError(
                f"{key}: stage_loss_db 须为 list[float]，得到 "
                f"{type(stage_loss_db).__name__}")
        if len(stage_loss_db) != len(m_list):
            raise ValueError(
                f"{key}: stage_loss_db 长度 {len(stage_loss_db)} ≠ 级数 "
                f"{len(m_list)}")
        losses = [_finite(v, f"stage_loss_db[{i}]", key)
                  for i, v in enumerate(stage_loss_db)]
        if any(v < 0.0 for v in losses):
            raise ValueError(
                f"{key}: stage_loss_db 逐项须 ≥0，得到 {stage_loss_db!r}")
    else:
        losses = [0.0] * len(m_list)

    p_in_dbm: float | None = None
    if pin_dbm is not None:
        p_in_dbm = _finite(pin_dbm, "pin_dbm", key)

    if stage_residual_pn_dbc_hz is not None:
        if not isinstance(stage_residual_pn_dbc_hz, (list, tuple)):
            raise ValueError(
                f"{key}: stage_residual_pn_dbc_hz 须为 list[float]，得到 "
                f"{type(stage_residual_pn_dbc_hz).__name__}")
        if len(stage_residual_pn_dbc_hz) != len(m_list):
            raise ValueError(
                f"{key}: stage_residual_pn_dbc_hz 长度 "
                f"{len(stage_residual_pn_dbc_hz)} ≠ 级数 {len(m_list)}")
        residuals = [_finite(v, f"stage_residual_pn_dbc_hz[{i}]", key)
                     for i, v in enumerate(stage_residual_pn_dbc_hz)]
        res_sum_dbc = 10.0 * math.log10(
            math.fsum(10.0 ** (r / 10.0) for r in residuals))
    else:
        residuals = None
        res_sum_dbc = None

    stages = []
    f_acc = f_in
    n_acc = 1
    loss_acc = 0.0
    for i, (m, loss) in enumerate(zip(m_list, losses, strict=True)):
        n_acc *= m
        f_acc *= m
        loss_acc += loss
        stages.append({
            "index": i,
            "factor": m,
            "f_out_ghz": round(f_acc, 12),
            "cum_n": n_acc,
            "stage_loss_db": round(loss, 9),
            "cum_loss_db": round(loss_acc, 9),
            "ideal_pn_deg_db_cum": round(20.0 * math.log10(n_acc), 9),
        })

    total_loss_db = math.fsum(losses)
    # 素因子分解（确定性；n_total ≤ 65536 平凡量级）
    rem = n_total
    primes: list[int] = []
    d = 2
    while d * d <= rem:
        while rem % d == 0:
            primes.append(d)
            rem //= d
        d += 1
    if rem > 1:
        primes.append(rem)

    out: dict[str, Any] = {
        "f_in_ghz": round(f_in, 12),
        "n_stages": len(m_list),
        "factors": m_list,
        "n_total": n_total,
        "f_out_ghz": round(f_acc, 12),
        "pn_degradation_ideal_db": round(20.0 * math.log10(n_total), 9),
        "pn_identity_check": bool(
            abs(math.fsum(20.0 * math.log10(m) for m in m_list)
                - 20.0 * math.log10(n_total)) <= 1e-9),
        "total_conversion_loss_db": round(total_loss_db, 9),
        "prime_factorization": primes,
        "stages": stages,
        "residual_pn_sum_dbc": (round(res_sum_dbc, 9)
                                if res_sum_dbc is not None else None),
        "note": (
            "理想倍频相噪劣化律 20log10(N)（同偏移单边带口径；逐级累计"
            "恒等式 Σ20log10(M_i)=20log10(∏M_i)，pn_identity_check 随"
            "行）；总转换损耗=逐级 dB 算术（Friis 同口径）；剩余相噪"
            "地板按同偏移同频功率和 10log10(Σ10^(r_i/10)) 单列输出——"
            "与理想律的合并需链输入相噪，键面不冒充（如实拆列）；谐波"
            "杂散枚举归 spur_search（混频乘积域边界）"),
        "source": _SOURCE_MULT,
    }
    if p_in_dbm is not None:
        out["pin_dbm"] = round(p_in_dbm, 9)
        out["pout_dbm"] = round(p_in_dbm - total_loss_db, 9)
    return out


# ─── 键 8/9：N-way Doherty（架构批 W4-S4，R2 边际池顺延件）─────────────────

_SOURCE_DOHERTY_NWAY = (
    "理想 N-way Doherty 区域效率=第一性推导（理想 B 类电流簿记+顺序开通"
    "剖面，core/pa_architectures.doherty_nway_efficiency docstring 推导"
    "链）；独立裁判=N=2 逐位回归 Cripps ARMMS 2008 两区域闭式（既有 "
    "doherty_efficiency）+断点回峰 η(σ=m/N)=π/4 恒等式族+凹陷闭式 "
    "πr(r−1)/(2r−1)²（r=2 → 2π/9 与既有 DOHERTY_ETA_DIP_MIN 逐位）；"
    "20·log10(N) 满回退=N-way Doherty 文献标准语义")


@register_calculator(
    "doherty_nway_efficiency",
    "N-way Doherty效率：理想 N-way（N 支路顺序开通）区域效率闭式：η=(π/4)"
    "·σ²·N/S_N(σ)（区域 r：N·σ²/[σ(2r−1)−r(r−1)/N]，σ=√(P/P_max)）。恒"
    "等式：η(σ=m/N)=π/4 断点回峰族/η(1)=π/4/全域 η∈[0,π/4]/区域 1=(π/4)"
    "·N·σ。N=2 逐位回归既有 2-way Cripps 闭式（同仓双源裁判）。输出效率+"
    "区域+归一化器件电流剖面+断点判读",
    (("n_way", "int - Doherty 支路数 N（整数 ∈[2,8]，2=经典 2-way）"),
     ("sigma", "float - 归一化电压摆幅 σ=√(P/P_max)（[0,1]）")),
    required=("n_way", "sigma"),
)
def doherty_nway_efficiency(n_way: int, sigma: float) -> dict[str, Any]:
    from rfauto.core.pa_architectures import (
        ETA_CLASS_B_PEAK,
        doherty_nway_point,
    )

    n = int(n_way)
    if n != n_way or isinstance(n_way, bool) or n < 2 or n > 8:
        raise ValueError(f"n_way 必须为整数 ∈[2,8]，得 {n_way!r}")
    point = doherty_nway_point(n, sigma)
    point["eta_peak"] = ETA_CLASS_B_PEAK
    point["source"] = _SOURCE_DOHERTY_NWAY
    return point


@register_calculator(
    "doherty_nway_breakpoints",
    "N-way Doherty断点表：断点/回峰/凹陷全表（σ=m/N，PBO=20log10(N/m)dB，"
    "m=1..N——m=1 档=经典 N-way 满回退 20log10(N)dB）；区域 r 凹陷闭式 "
    "σ*_r=2r(r−1)/(N(2r−1))、η_min=π·r(r−1)/(2r−1)²（只依赖区域号与 N "
    "无关；r=2 → 2π/9 与既有 2-way DOHERTY_ETA_DIP_MIN 逐位）。效率点值"
    "面归 doherty_nway_efficiency 不重复",
    (("n_way", "int - Doherty 支路数 N（整数 ∈[2,8]，2=经典 2-way）"),),
    required=("n_way",),
)
def doherty_nway_breakpoints(n_way: int) -> dict[str, Any]:
    from rfauto.core.pa_architectures import doherty_nway_breakpoints as _bp

    n = int(n_way)
    if n != n_way or isinstance(n_way, bool) or n < 2 or n > 8:
        raise ValueError(f"n_way 必须为整数 ∈[2,8]，得 {n_way!r}")
    out = _bp(n)
    out["source"] = _SOURCE_DOHERTY_NWAY
    return out
