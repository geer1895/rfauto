"""超导量子比特读出链族（aurora36 W7-A 席，R2 空白域 G18——quantum_cryo 升格）。

三键：qubit_dispersive_shift（色散位移 χ 一阶闭式+强色散域判据）/
qubit_readout_s21（读出谐振器 S21 双态频响，单源实现）/
qubit_readout_snr（读出 IQ 分离 SNR/积分时间面）。

与既有量子面的分工（语义防撞，R2 G18 三重搜索证据）
------------------------------------------------
- quantum_cryo.py = BCS 两流体 Rs/RCSJ 结（材料/器件面）+
  quantum_register_note（Tq/χ/Purcell **只出口径名声明字典、不做数值
  判据**，docstring 自证登记级）——本族是其点名升格的**数值面**：
  χ 一阶闭式、S21 双态曲线、SNR/积分时间，口径与登记级声明一致
  （χ=g²/Δ 一阶口径名 → 本族给有限 κ 的 Lorentzian 完整形）。
- quasistatic_fd.py = 准静态电容/参与比（participation）面——χ 的
  几何输入端邻居，本族以 g 为入口不重复电容提取。
- cryo_materials.py = 低温材料损耗面，无键面重叠。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
1. **色散位移 χ（Blais 2004 色散哈密顿量 + 有限线宽修正）**：腔-
   比特耦合 g、失谐 Δ=ω_q−ω_r、腔线宽 κ。复色散系数一阶近似：

       χ̃ = g²/(Δ + jκ/2)
       Re(χ̃) = g²Δ/((κ/2)² + Δ²)      （本键输出的 χ，读出频移口径）
       Im(χ̃) = −g²(κ/2)/((κ/2)² + Δ²)  （对应读出致退相干支路）

   远失谐 |Δ|≫κ 退化为教科书色散支 χ = g²/Δ（quantum_cryo 登记级
   声明同口径）。强色散域判据（输出 regime 字段，不做硬门）：
   - 可分辨（resolved/strong dispersive）：|2χ| ≥ κ（两态腔频移过
     半线宽，Blais RMP 2021 口径）；
   - 色散近似有效：|g/Δ| ≪ 1（本键按 ≤0.1 旗标）、临界光子数
     n_crit = Δ²/(4g²)（|g/Δ|²/4；读出光子数须 n ≪ n_crit）；
   - Purcell 衰减：Γ_P = (g/Δ)²·κ（登记级声明同式升格数值）。
   来源：A. Blais et al., Phys. Rev. A 69, 062320 (2004)（色散近似）；
   Blais et al., Rev. Mod. Phys. 93, 025005 (2021)（强色散判据与
   n_crit 口径）。
2. **读出谐振器 S21（传输/notch 型，双态单源）**：输入-输出理论
   稳态传输（普通频率口径，线宽单位 Hz）：

       S21(δ) = 1 − κe/(κ/2 + j·(δ − shift))

   δ = ω−ω_r（普通频率差）；κe 外部（耦合口）线宽、κ 总线宽；
   shift = ±χ 为比特态依赖的腔频移——**单源实现**：两态曲线经同一
   内部函数产出，state0（|g⟩）取 +χ、state1（|e⟩）取 −χ（符号约定
   写死）。耦合状态判读：临界耦合 κe=κ/2 → 谐振点 |S21|=0（深谷
   全消，"−1 归一口径"：S21 = 1 − κe/(κ/2) = 1−1 = 0）；欠耦合
   κe<κ/2 → |S21(f_r)| = 1−2κe/κ > 0；过耦合 κe>κ/2 → 谐振点
   幅值回升且相位翻转（经典 notch 形态）。两态分离度 |2χ|/κ。
3. **读出 SNR/积分时间（IQ 平面分离口径，工程近似写死）**：两态
   稳态输出的 IQ 平面质心距离 d_IQ = |S21(f_probe,+χ) − S21(f_probe,
   −χ)|（探针频率 f_probe = f_r + detune，缺省 on-resonance）。光子
   计数口径：探测到光子流 ≈ κe·n̄（n̄=腔内平均光子数，过耦合口径），
   积分 τ 后信号 = d_IQ·√(κe·n̄·τ)，噪声 = √(n_sys)（折算到输入的
   噪声光子数；相敏放大量子极限 n_sys=1 对应 T_n = h·f_r/k_B）：

       SNR = d_IQ · √(κe·n̄·τ / n_sys)，  n_sys = k_B·T_n/(h·f_r)

   恒等锚：SNR ∝ √τ（τ×4 → SNR×2 逐位）、SNR ∝ √n̄；χ→0 →
   d_IQ→0 → SNR→0（与键 2 连续）。参考字段：测量率 Γ_m = 8χ²n̄/κ
   （坏腔可分辨极限参考，Blais RMP 2021/Gambetta 2006 口径，仅参考
   不参与 SNR 主路径）；SNR=1 所需积分时间 τ₁ = n_sys/(κe·n̄·d_IQ²)。
   来源：S. Goppl et al., Eur. Phys. J. B 63, 39 (2008)（共面波导
   谐振器异差读出 IQ 平面 SNR 定义口径）；Blais RMP 2021（Γ_m 参考）。
   诚实边界：工程近似（理想线性放大、真空+热噪声仅计 T_n 折算、
   过耦合 κe·n̄ 光子流口径），非端到端链路预算；量子极限参考与
   有限 T_n 口径并存，选用时如实标注。

单位约定（写死）：本模块全部频率量（g/Δ/κ/Γ1/χ/δ）为**普通频率**
口径（Hz，参数以 MHz 入参、内部 1e6 s⁻¹）——色散闭式与 S21 式在
普通频率与角频率下同形（全部量同除 2π），混用即错，入参一律 MHz。

数值锚（#118 独立来源；锚树 tests/unit/test_w7a_pa_qubit.py）
- χ：远失谐 |Δ|≫κ 退化 g²/Δ（rel<1e-6）；奇对称 χ(−Δ)=−χ(Δ)；
  Δ→0⁺ 序列 χ→0 单调；ncrit/Γ_P 测试侧独立重算。
- S21：临界耦合 κe=κ/2 → 态谐振点 S21 逐位 0；κe=κ/4 → 0.5；
  κe=κ → |S21|=1（过耦合相位翻转）；χ=0 → 双态曲线逐点相同；
  带缘 |S21|→1。
- SNR：τ×4 → SNR×2（rel 1e-12）；T_n→量子极限（T_n=h·f/k_B）→
  n_sys=1；T_n×4 → SNR ÷2；d_IQ 测试侧独立复数重算回收。

守卫：g_mhz/κ/κe/f_r/n̄/τ 正性；κe ≤ κ；Δ≠0（简并点色散近似失效
显式拒绝，连续性锚用 1e-3 MHz 量级小失谐钉）；Γ1 ≥ 0；T_n > 0
（T_n=0 无噪声放大器非物理，量子极限走缺省 None 路径）；|χ|=0 的
SNR 键显式拒绝（零信号测量无信息）；span/n_points 域守卫；越界一律
显式报错不静默。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator

#: 约化普朗克常数 × 波尔兹曼（K/Hz）：T_q = h·f/k_B 的系数
_H_OVER_KB = 6.62607015e-34 / 1.380649e-23  # K·s（SI 2019 定义值）

_SOURCE_CHI = (
    "Blais PR A 69, 062320 (2004) 色散近似 + Blais RMP 93, 025005 "
    "(2021) 强色散判据/n_crit/Purcell 口径；远失谐极限与 quantum_cryo."
    "quantum_register_note 登记级声明同式（χ=g²/Δ）升格数值")
_SOURCE_S21 = (
    "输入-输出理论稳态传输（notch/through 型，普通频率线宽口径）；"
    "Goppl EPJ B 63, 39 (2008) 读出谐振器响应口径；单源实现两态曲线")
_SOURCE_SNR = (
    "Goppl EPJ B 63, 39 (2008) IQ 平面分离 SNR 定义（工程近似写死："
    "d_IQ·√(光子数/噪声光子)；相敏放大量子极限 n_sys=1 ↔ "
    "T_n=h·f/k_B）；Γ_m=8χ²n̄/κ 参考面：Blais RMP 2021/Gambetta 2006")


def _finite(value: Any, name: str, key: str) -> float:
    """入参收敛为有限 float（bool 显式拒收，df7+⑯ float(True) 污染口径）。"""
    if isinstance(value, bool):
        raise ValueError(f"{key}: {name} 不接受 bool（float(True)=1.0 静默污染）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{key}: {name} 必须为有限数，得到 {value!r}")
    return out


def _positive(value: Any, name: str, key: str) -> float:
    out = _finite(value, name, key)
    if out <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0，得到 {value!r}")
    return out


def _s21_notch(delta_hz: float, kappa_hz: float, kappa_e_hz: float,
               shift_hz: float) -> complex:
    """读出谐振器 S21 单源核：S21 = 1 − κe/(κ/2 + j(δ − shift))。

    全部量普通频率口径（Hz）。两态曲线与 SNR 的 IQ 分离都消费本函数
    （单源纪律：双态差异只经 shift 参数进入，公式路径唯一）。
    """
    denom = complex(kappa_hz / 2.0, delta_hz - shift_hz)
    return 1.0 - kappa_e_hz / denom


# ─── 键 1：色散位移 χ ────────────────────────────────────────────────────────


@register_calculator(
    "qubit_dispersive_shift",
    "色散位移：量子比特读出色散位移 χ 一阶闭式（G18，Blais 2004 色散近似+有限"
    "线宽修正）：χ = g²Δ/((κ/2)²+Δ²)（复色散系数 Re(g²/(Δ+jκ/2))；"
    "远失谐 |Δ|≫κ 退化教科书 g²/Δ）。附强色散域判据字段：可分辨 "
    "|2χ|≥κ、色散近似有效 |g/Δ|≤0.1、临界光子数 n_crit=Δ²/(4g²)、"
    "Purcell 衰减 Γ_P=(g/Δ)²κ、有效比特线宽 Γ1+Γ_P。全部频率量普通"
    "频率口径（MHz 入参；g 为单比特真空耦合——实测谐振分裂 2g 请先"
    "除 2）。Δ=0 简并点色散近似失效，显式拒绝",
    (("g_mhz", "float MHz 腔-比特真空耦合强度 g（>0；非 2g 分裂）"),
     ("delta_mhz", "float MHz 比特-腔失谐 Δ=ω_q−ω_r（≠0，符号进 χ）"),
     ("kappa_mhz", "float MHz 腔总线宽 κ（>0）"),
     ("gamma1_mhz", "float MHz 比特弛豫率 Γ1（≥0，缺省 0；给定时出"
      "有效线宽 Γ1+Γ_P 面）")),
    required=("g_mhz", "delta_mhz", "kappa_mhz"),
)
def qubit_dispersive_shift(
    g_mhz: float,
    delta_mhz: float,
    kappa_mhz: float,
    gamma1_mhz: float = 0.0,
) -> dict[str, Any]:
    key = "qubit_dispersive_shift"
    g = _positive(g_mhz, "g_mhz", key)
    delta = _finite(delta_mhz, "delta_mhz", key)
    if delta == 0.0:
        raise ValueError(
            f"{key}: delta_mhz=0 为腔-比特简并点（色散近似失效，"
            "|g/Δ| 发散），显式拒绝；弱色散连续性用 |Δ|≪κ 小失谐钉")
    kappa = _positive(kappa_mhz, "kappa_mhz", key)
    gamma1 = _finite(gamma1_mhz, "gamma1_mhz", key)
    if gamma1 < 0.0:
        raise ValueError(f"{key}: gamma1_mhz 必须 ≥0，得到 {gamma1_mhz!r}")

    # χ̃ = g²/(Δ+jκ/2)：实部=色散频移、虚部=读出致退相干支路
    chi_tilde = g * g / complex(delta, kappa / 2.0)
    chi = chi_tilde.real
    purcell = (g / delta) ** 2 * kappa
    ncrit = delta * delta / (4.0 * g * g)
    two_chi_over_kappa = 2.0 * abs(chi) / kappa
    g_over_delta = abs(g / delta)

    return {
        "chi_mhz": round(chi, 12),
        "chi_imag_mhz": round(chi_tilde.imag, 12),
        "chi_over_kappa": round(chi / kappa, 12),
        "two_chi_over_kappa": round(two_chi_over_kappa, 12),
        "purcell_mhz": round(purcell, 12),
        "gamma1_mhz": round(gamma1, 12),
        "gamma_eff_mhz": round(gamma1 + purcell, 12),
        "ncrit": round(ncrit, 12),
        "g_over_delta": round(g_over_delta, 12),
        "kappa_mhz": round(kappa, 12),
        "delta_mhz": round(delta, 12),
        "regime": {
            "resolved_strong_dispersive": bool(two_chi_over_kappa >= 1.0),
            "resolved_note": "|2χ|≥κ：两态腔频移过半线宽（可分辨读出）",
            "dispersive_approx_valid": bool(g_over_delta <= 0.1),
            "dispersive_note": "|g/Δ|≤0.1 旗标（二阶微扰有效域）+读出"
                               "光子数 n≪n_crit（超出即腔内临界跃迁）",
            "kappa_dominant_bad_cavity": bool(abs(delta) <= kappa),
            "far_detuned_limit": bool(abs(delta) >= 10.0 * kappa),
        },
        "source": _SOURCE_CHI,
    }


# ─── 键 2：读出谐振器 S21 双态频响（单源） ───────────────────────────────────


@register_calculator(
    "qubit_readout_s21",
    "读出S21曲线：读出谐振器 S21 双态频响曲线（G18，notch/through 型单源实现）："
    "S21(δ)=1−κe/(κ/2+j(δ∓χ))，两态经同一内部函数产出（单源：双态"
    "差异只经 ±χ 位移进入；state0=|g⟩ 取 +χ、state1=|e⟩ 取 −χ，"
    "符号约定写死）。锚：临界耦合 κe=κ/2 → 态谐振点 S21 逐位 0（深"
    "谷归一 −1 口径）；欠/过耦合谐振点幅值 1−2κe/κ 与相位翻转。"
    "χ=0 → 双态曲线逐点相同（与色散键连续）。分离度 |2χ|/κ 字段",
    (("f_r_ghz", "float GHz 裸腔频率 ω_r/2π（>0）"),
     ("kappa_mhz", "float MHz 腔总线宽 κ（>0）"),
     ("kappa_e_mhz", "float MHz 外部（耦合口）线宽 κe（0<κe≤κ）"),
     ("chi_mhz", "float MHz 色散频移（缺省 0；qubit_dispersive_shift."
      "chi_mhz 直连；state0 取 +χ、state1 取 −χ）"),
     ("span_mhz", "float MHz 扫频跨度（>0，缺省 10×κ，以 f_r 为中心）"),
     ("n_points", "int 频点数（[2,2001]，缺省 201）")),
    required=("f_r_ghz", "kappa_mhz", "kappa_e_mhz"),
)
def qubit_readout_s21(
    f_r_ghz: float,
    kappa_mhz: float,
    kappa_e_mhz: float,
    chi_mhz: float = 0.0,
    span_mhz: float | None = None,
    n_points: int = 201,
) -> dict[str, Any]:
    key = "qubit_readout_s21"
    fr_hz = _positive(f_r_ghz, "f_r_ghz", key) * 1.0e9
    kappa_hz = _positive(kappa_mhz, "kappa_mhz", key) * 1.0e6
    ke_hz = _positive(kappa_e_mhz, "kappa_e_mhz", key) * 1.0e6
    if ke_hz > kappa_hz:
        raise ValueError(
            f"{key}: kappa_e_mhz 须 ∈ (0, κ]，得到 {kappa_e_mhz!r} "
            f"> κ={kappa_mhz!r}")
    chi_hz = _finite(chi_mhz, "chi_mhz", key) * 1.0e6
    span = (10.0 * kappa_hz if span_mhz is None
            else _positive(span_mhz, "span_mhz", key) * 1.0e6)
    if isinstance(n_points, bool) or not isinstance(n_points, int):
        raise ValueError(f"{key}: n_points 必须为 int，得到 {n_points!r}")
    if n_points < 2 or n_points > 2001:
        raise ValueError(f"{key}: n_points 须在 [2,2001]，得到 {n_points!r}")

    def _curve(shift_hz: float) -> tuple[list[float], list[dict[str, float]],
                                         list[float], list[float]]:
        """单源 _s21_notch 的栅格化出口（freq/复数对/dB/相位）。"""
        step = span / (n_points - 1)
        freqs = [fr_hz - span / 2.0 + i * step for i in range(n_points)]
        pairs: list[dict[str, float]] = []
        mags_db: list[float] = []
        phases: list[float] = []
        for f in freqs:
            s = _s21_notch(f - fr_hz, kappa_hz, ke_hz, shift_hz)
            mag = abs(s)
            pairs.append({"re": round(s.real, 12), "im": round(s.imag, 12)})
            # 临界耦合态谐振点 |S21| 逐位 0 → dB 发散，记 None（JSON
            # 安全、诚实语义——不冒充 −inf/有限深谷）
            mags_db.append(round(20.0 * math.log10(mag), 9)
                           if mag > 0.0 else None)
            phases.append(round(math.degrees(math.atan2(s.imag, s.real)), 9))
        return [round(f / 1.0e6, 9) for f in freqs], pairs, mags_db, phases

    freq_mhz, s21_s0, mag_db_s0, phase_deg_s0 = _curve(+chi_hz)
    _, s21_s1, mag_db_s1, phase_deg_s1 = _curve(-chi_hz)

    # 态谐振点精确值（δ=+shift，不依赖栅格采样——深谷锚走此面；两态
    # 对称同值 1−κe/(κ/2)，state1 曲线由同一单源函数镜像产出）
    dip_mag = abs(_s21_notch(+chi_hz, kappa_hz, ke_hz, +chi_hz))
    if ke_hz < kappa_hz / 2.0:
        coupling = "undercoupled"
    elif ke_hz > kappa_hz / 2.0:
        coupling = "overcoupled"
    else:
        coupling = "critical"
    return {
        "f_r_ghz": round(f_r_ghz, 12),
        "kappa_mhz": round(kappa_hz / 1.0e6, 12),
        "kappa_e_mhz": round(ke_hz / 1.0e6, 12),
        "chi_mhz": round(chi_hz / 1.0e6, 12),
        "two_chi_over_kappa": round(2.0 * abs(chi_hz) / kappa_hz, 12),
        "coupling_regime": coupling,
        "dip_mag_state_resonance": round(dip_mag, 12),
        "dip_note": "态谐振点 |S21| = 1−κe/(κ/2)：临界耦合逐位 0（深谷"
                    "归一）；欠耦合 >0；过耦合幅值回升且相位翻转。"
                    "mag_db 数组在精确零幅值点记 None（dB 发散，JSON "
                    "安全诚实口径）",
        "freq_mhz": freq_mhz,
        "s21_state0": s21_s0,
        "s21_state1": s21_s1,
        "mag_db_state0": mag_db_s0,
        "mag_db_state1": mag_db_s1,
        "phase_deg_state0": phase_deg_s0,
        "phase_deg_state1": phase_deg_s1,
        "convention_note": "state0（|g⟩）谐振在 f_r+χ、state1（|e⟩）在 "
                           "f_r−χ（shift 符号约定写死）；两态曲线单源"
                           "产出，双态差异只经 ±χ 进入",
        "source": _SOURCE_S21,
    }


# ─── 键 3：读出 SNR/积分时间 ─────────────────────────────────────────────────


@register_calculator(
    "qubit_readout_snr",
    "读出SNR：量子比特读出 SNR/积分时间（G18，IQ 平面分离口径，工程近似写"
    "死）：SNR = d_IQ·√(κe·n̄·τ/n_sys)。d_IQ=|S21(f_probe,+χ)−"
    "S21(f_probe,−χ)|（单源消费键 2 同一内部函数）；n̄=腔内平均光子"
    "数（光子流 κe·n̄ 过耦合口径）；n_sys=k_B·T_n/(h·f_r) 折算输入噪"
    "声光子数（T_n 缺省=量子极限 h·f_r/k_B → n_sys=1；相敏放大口径）。"
    "恒等锚：SNR∝√τ（τ×4→×2）、SNR∝√n̄；参考字段 Γ_m=8χ²n̄/κ（坏腔"
    "可分辨极限，仅参考）与 SNR=1 积分时间 τ₁=n_sys/(κe·n̄·d_IQ²)。"
    "|χ|=0 零信号显式拒绝",
    (("chi_mhz", "float MHz 色散频移（|χ|>0；qubit_dispersive_shift."
      "chi_mhz 直连）"),
     ("kappa_mhz", "float MHz 腔总线宽 κ（>0）"),
     ("kappa_e_mhz", "float MHz 外部线宽 κe（0<κe≤κ）"),
     ("n_bar", "float 腔内平均读出光子数（>0；须≪ncrit，调用方自查）"),
     ("f_r_ghz", "float GHz 裸腔频率（>0；n_sys 的 T_q=h·f/k_B 口径）"),
     ("tau_us", "float μs 积分时间（>0）"),
     ("t_n_k", "float K 放大器噪声温度（>0，缺省=量子极限 h·f_r/k_B）"),
     ("detune_mhz", "float MHz 探针频率偏移 δ（缺省 0=on-resonance）")),
    required=("chi_mhz", "kappa_mhz", "kappa_e_mhz", "n_bar",
              "f_r_ghz", "tau_us"),
)
def qubit_readout_snr(
    chi_mhz: float,
    kappa_mhz: float,
    kappa_e_mhz: float,
    n_bar: float,
    f_r_ghz: float,
    tau_us: float,
    t_n_k: float | None = None,
    detune_mhz: float = 0.0,
) -> dict[str, Any]:
    key = "qubit_readout_snr"
    chi_hz = _finite(chi_mhz, "chi_mhz", key) * 1.0e6
    if chi_hz == 0.0:
        raise ValueError(
            f"{key}: chi_mhz=0 为零信号测量（d_IQ=0，SNR 无定义），"
            "显式拒绝——弱信号面请直接给小 χ")
    kappa_hz = _positive(kappa_mhz, "kappa_mhz", key) * 1.0e6
    ke_hz = _positive(kappa_e_mhz, "kappa_e_mhz", key) * 1.0e6
    if ke_hz > kappa_hz:
        raise ValueError(
            f"{key}: kappa_e_mhz 须 ∈ (0, κ]，得到 {kappa_e_mhz!r} "
            f"> κ={kappa_mhz!r}")
    n_ph = _positive(n_bar, "n_bar", key)
    fr_hz = _positive(f_r_ghz, "f_r_ghz", key) * 1.0e9
    tau_s = _positive(tau_us, "tau_us", key) * 1.0e-6
    detune_hz = _finite(detune_mhz, "detune_mhz", key) * 1.0e6
    t_q = _H_OVER_KB * fr_hz
    if t_n_k is None:
        n_sys = 1.0
        quantum_limited = True
        t_n_used: float | None = None
    else:
        # t_n_k=0 → n_sys=0 → SNR 发散，显式拒绝（量子极限走缺省
        # None 路径；0 K"无噪声放大器"非物理）
        t_n_used = _positive(t_n_k, "t_n_k", key)
        n_sys = t_n_used / t_q
        quantum_limited = t_n_used == t_q

    # IQ 分离：单源消费键 2 同一内部函数（双态差异只经 ±χ 进入）
    d_iq = abs(_s21_notch(detune_hz, kappa_hz, ke_hz, +chi_hz)
               - _s21_notch(detune_hz, kappa_hz, ke_hz, -chi_hz))
    photons_total = ke_hz * n_ph * tau_s
    snr = d_iq * math.sqrt(photons_total / n_sys)
    gamma_m = 8.0 * (abs(chi_hz) ** 2) * n_ph / kappa_hz
    tau_snr1 = n_sys / (ke_hz * n_ph * d_iq * d_iq)

    return {
        "snr": round(snr, 12),
        "d_iq": round(d_iq, 12),
        "n_sys": round(n_sys, 12),
        "quantum_limited": bool(quantum_limited),
        "t_q_k": round(t_q, 12),
        "t_n_k": (round(t_n_used, 12) if t_n_used is not None else None),
        "photons_total": round(photons_total, 12),
        "gamma_m_per_s": round(gamma_m, 9),
        "tau_for_snr1_us": round(tau_snr1 * 1.0e6, 12),
        "f_probe_ghz": round((fr_hz + detune_hz) / 1.0e9, 12),
        "chi_mhz": round(chi_hz / 1.0e6, 12),
        "kappa_mhz": round(kappa_hz / 1.0e6, 12),
        "n_bar": round(n_ph, 12),
        "tau_us": round(tau_s * 1.0e6, 12),
        "convention_note": (
            "SNR = d_IQ·√(κe·n̄·τ/n_sys)：n_sys=k_B·T_n/(h·f_r)（T_n="
            "h·f_r/k_B 量子极限 → n_sys=1）；τ×4→SNR×2、n̄×4→SNR×2 "
            "恒等（√律）；Γ_m=8χ²n̄/κ 为坏腔可分辨极限参考值，仅参考"
            "不参与 SNR 主路径"),
        "honesty_note": (
            "工程近似边界：理想线性放大、真空+热噪声仅计 T_n 折算、"
            "过耦合 κe·n̄ 光子流口径——非端到端链路预算（量子效率/"
            "损耗链/ 读出脉冲整形不计）"),
        "source": _SOURCE_SNR,
    }
