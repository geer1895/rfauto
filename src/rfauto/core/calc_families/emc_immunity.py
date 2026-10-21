"""EMC 抗扰度族（架构批 W6-A 席，R2 空白域 G4——抗扰半边补口）。

出处（IEC 抗扰度标准事实口径，正文物理口径节转录）：
- radiated_immunity_power：IEC 61000-4-3 严酷度等级与远场换算
  （E=√(30PG)/R；二级转引 Ott, Electromagnetic Compatibility
  Engineering ch.5）。
- conducted_immunity_cdn：IEC 61000-4-6 CDN 耦合 emf 口径换算
  （0dBm≡107 dBµV/113 dBµV emf，50Ω 恒等式）。
- esd_contact_waveform：IEC 61000-4-2 接触放电双指数波形表
  （150pF/330Ω 发生器校准口径；保守双指数参数化为任务书口径）。

三键：radiated_immunity_power（IEC 61000-4-3 射频辐射抗扰场强/功率
换算）/ conducted_immunity_cdn（IEC 61000-4-6 射频传导抗扰 CDN 耦合
口径 emf↔功率换算）/ esd_contact_waveform（IEC 61000-4-2 接触放电
双指数电流波形特征）。

与既有 EMC 面的分工（语义防撞，R2 §① J 族地图）
------------------------------------------------
- emc_radiated.py = 辐射**发射** RE/CISPR 检波面（发射半边，不同语义）；
  本族 61000-4-3 = 辐射**抗扰**（RS，受试设备注入面）。
- emc_tvs_gate.py = 61000-4-2/4-5 波形参数表 + TVS 选型门（core 纯函数，
  按既定约定不进注册表）；本族 esd_contact_waveform 消费其波形表单源
  （esd_waveform_currents/ESD_GENERATOR_C_PF/ESD_GENERATOR_R_OHM），
  补的是 TVS 门不做的**双指数波形参数反演与面积恒等回收**面。
- shielding_effectiveness/multipactor/corona/exposure_limits 各自域内
  独立，无键面重叠（triple-grep 证据见锚树测试注释）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
1. **IEC 61000-4-3 射频辐射抗扰**：严酷度等级 Table 1——Level 1/2/3/4
   = 1/3/10/30 V/m（未调制载波口径；试验时 80% AM 1kHz 调幅，包络峰
   功率 ×(1.8)²=+5.105dB，只进 note 不改换算）。远场换算（Ott，
   Electromagnetic Compatibility Engineering ch.5；与 exposure_limits
   的 EIRP 合规距离闭式同源）：

       E = √(30·P·G)/R  ⇔  P = (E·R)²/(30·G)，EIRP = P·G = (E·R)²/30

   P=天线口前向功率（W）、G=线增益、R=试验距离；试验距离 3m/10m
   （标准首选 3m）；cable_loss_db>0 时源输出功率按 +cable_loss_db
   补偿。 doubling E → 功率精确 +6.0206dB；3m→10m 功率 ×(10/3)²。
   天线系数换算面（可选 freq_mhz）：AF(dB/m)=20·log10(f_MHz)−G_dBi
   −29.79（AF↔增益经典恒等式，50Ω 接收口径）。
2. **IEC 61000-4-6 射频传导抗扰（CDN 耦合）**：严酷度 Table 1——
   Level 1/2/3 = 1/3/10 V **emf**（开路电动势口径，CDN 注入口径）。
   dB 换算恒等式（0dBm=1mW 基准、50Ω 系统，口径写死）：

       0 dBm → 匹配负载端电压 √(1mW·50Ω)=0.2236 V = 106.99 dBµV
       （惯称"107 dBµV"口径）；
       emf（开路）口径 = 2×匹配端电压 = +6.0206 dB（0 dBm ≡ 113.01
       dBµV emf）。

   即 P_W=(emf/2)²/Z；80% AM 1kHz 时包络峰电压 ×1.8、峰功率 ×3.24
   （+5.105dB）。Level 3（10 V emf）→ 端电压 5 V → P=0.5 W=26.99 dBm。
3. **IEC 61000-4-2 接触放电（ESD）双指数波形**：波形表仅对接触放电
   定义（空气放电无独立表，如实登记——emc_tvs_gate 同口径）；归一化
   每 kV：Ip=3.75 A/kV（±10%）、I(30ns)=2 A/kV、I(60ns)=1 A/kV
   （±30%）、t_r=0.6–1 ns（Table 2/3，150pF/330Ω 发生器校准口径，
   单源消费 core/emc_tvs_gate.esd_waveform_currents）。波形参数化取
   保守双指数（任务书口径，非规范定义——规范只给包络点）：

       I(t)=I0·(e^(−t/τ1)−e^(−t/τ2))，τ1=衰减、τ2=上升

   三条件定参（放电档 kV∈{2,4,6,8}）：①峰值 Ip=3.75·kV；②
   I(30)/I(60)=2:1（比值恒等，30/60 绝对值随双指数族有 ~1.6% 级
   系统差，如实回显、在 ±30% 容差带内）；③上升时间 t_r（10%→90%
   峰值，双分位数值解）=rise_time_ns（缺省 0.7，域 [0.6,1.0]）。
   τ1/τ2 经定点迭代（ratio 单调 → 对数域二分；rise 双分位二分），
   I0 由解析峰时 t_p=τ1τ2·ln(τ1/τ2)/(τ1−τ2) 的峰值因子反解。
   恒等锚：∫I dt = I0·(τ1−τ2)（解析面积 vs 梯形积分数值回收）。

数值锚（#118 独立来源：闭式/恒等回收，不用自身推导互证；锚树
tests/unit/test_w6a_trl_emc.py）
- 61000-4-3：10 V/m @3m、G=6dBi → P=7.536 W=38.771 dBm；E↔P 双向
  恒等残差 <1e-12；E×2 → +6.0206 dB；R 3→10 → ×(10/3)²；AF 恒等
  锚 100 MHz/0 dBi → 10.21 dB/m；
- 61000-4-6：0 dBm ≡ 106.9897 dBµV（匹配端电压，107 口径）≡
  113.0103 dBµV emf；Level 3 → 0.5 W/26.9897 dBm；emf×2 → 端电压
  与功率同步 +6.0206 dB；AM80% → +5.1055 dB；
- ESD：4 kV → Ip=15 A/t_r=0.7 ns（文献带 0.6–1 ns 锚）；面积恒等
  I0(τ1−τ2) vs 梯形积分 <1e-4 相对；8 kV 波形=2×4 kV 波形逐点
  （归一化表线性性，τ1/τ2 档位不变）；放电电荷 I0(τ1−τ2) 对发生器
  C·V=600 nC（4 kV）比值落物理窗 [0.8,1.5]（包络点容差量级自洽）。

守卫：test_level 与显式量恰给其一；level 白名单；距离/增益/损耗/
emf/Z/线长/点数/时窗域守卫；charge_kv 仅收 {2,4,6,8} 接触档；
rise_time_ns∈[0.6,1.0]；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator

# ─── IEC 61000-4-3 / 4-6 / 4-2 严酷度与波形常量（标准表机读化）───────────────
_RS_LEVELS_V_M = {1: 1.0, 2: 3.0, 3: 10.0, 4: 30.0}  # IEC 61000-4-3 Table 1
_CS_LEVELS_V_EMF = {1: 1.0, 2: 3.0, 3: 10.0}  # IEC 61000-4-6 Table 1（emf）
_ESD_CONTACT_LEVELS_KV = (2.0, 4.0, 6.0, 8.0)  # IEC 61000-4-2 Table 1（接触）
_ESD_RISE_WINDOW_NS = (0.6, 1.0)  # Table 2/3 上升时间规范窗
_AM80_FACTOR = 1.8  # 80% AM 1kHz：包络峰电压 ×(1+0.8)
_DBM_REF_W = 1.0e-3  # 0 dBm = 1 mW 基准
_TEST_DISTANCES_M = (3.0, 10.0)  # 61000-4-3 标准试验距离（首选 3m）

_SOURCE_RS = ("IEC 61000-4-3 Table 1 等级表（次级源双源核对口径同 "
              "emc_tvs_gate 先例）; Ott EMC Engineering ch.5 远场闭式")
_SOURCE_CS = ("IEC 61000-4-6 Table 1 等级表（emf 口径）; 0dBm=1mW/50Ω "
              "dB 换算恒等式（107 dBµV 惯称口径写死）")
_SOURCE_ESD = ("IEC 61000-4-2 Table 1/2/3 波形参数（单源消费 "
               "core/emc_tvs_gate.esd_waveform_currents）; 双指数为任务书"
               "保守参数化（规范只给包络点，非规范定义）")


# ─── 键 1：IEC 61000-4-3 辐射抗扰场强/功率换算 ───────────────────────────────

@register_calculator(
    "radiated_immunity_power",
    "辐射抗扰换算：IEC 61000-4-3 射频辐射抗扰场强/功率换算（远场口径）：严酷度 "
    "test_level（1/2/3/4→1/3/10/30 V/m，Table 1）或显式 field_v_per_m "
    "恰给其一 → 天线口所需前向功率 P=(E·R)²/(30G)（E=√(30·EIRP)/R "
    "恒等闭式，Ott ch.5；与 exposure_limits 合规距离同源）+ EIRP + 源"
    "输出补偿（cable_loss_db）。试验距离 3m/10m（标准首选 3m）。恒等"
    "锚：E↔P 双向残差 <1e-12；E×2=+6.0206dB；3m→10m 功率 ×(10/3)²。"
    "可选 freq_mhz 给天线系数换算面 AF(dB/m)=20log10(f_MHz)−G_dBi−29.79"
    "（50Ω 接收口径经典恒等）。80% AM 1kHz 包络峰 +5.105dB 只进 note",
    (("test_level", "int 严酷度等级 1|2|3|4（Table 1；与 field_v_per_m "
      "恰给其一）"),
     ("field_v_per_m", "float V/m 显式场强（>0；与 test_level 恰给其一）"),
     ("distance_m", "float m 试验距离（3|10，标准试验距离）"),
     ("antenna_gain_db", "float dBi 发射天线线增益（≥0，缺省 6）"),
     ("cable_loss_db", "float dB 天线口前馈缆损耗（≥0，缺省 0；源输出按此"
      "补偿）"),
     ("freq_mhz", "float MHz 天线系数换算频率（可选；给了才出 AF 面）")),
    required=("distance_m",),
)
def radiated_immunity_power(distance_m: float,
                            test_level: int | None = None,
                            field_v_per_m: float | None = None,
                            antenna_gain_db: float = 6.0,
                            cable_loss_db: float = 0.0,
                            freq_mhz: float | None = None) -> dict[str, Any]:
    key = "radiated_immunity_power"
    if (test_level is None) == (field_v_per_m is None):
        raise ValueError(
            f"{key}: test_level（等级查表）与 field_v_per_m（显式场强）"
            "恰给其一")
    if test_level is not None:
        lvl = int(test_level)
        if lvl not in _RS_LEVELS_V_M:
            raise ValueError(
                f"{key}: test_level 须为 1|2|3|4（IEC 61000-4-3 Table 1），"
                f"得到 {test_level!r}")
        e_field = _RS_LEVELS_V_M[lvl]
    else:
        e_field = float(field_v_per_m)
        if not (math.isfinite(e_field) and e_field > 0.0):
            raise ValueError(
                f"{key}: field_v_per_m 必须为正有限数，"
                f"得到 {field_v_per_m!r}")
    dist = float(distance_m)
    if dist not in _TEST_DISTANCES_M:
        raise ValueError(
            f"{key}: distance_m 须为标准试验距离 {list(_TEST_DISTANCES_M)}"
            f"（3m 首选），得到 {distance_m!r}")
    gain_db = float(antenna_gain_db)
    if not (math.isfinite(gain_db) and gain_db >= 0.0):
        raise ValueError(
            f"{key}: antenna_gain_db 必须 ≥0（各向同性 0 合法），"
            f"得到 {antenna_gain_db!r}")
    loss_db = float(cable_loss_db)
    if not (math.isfinite(loss_db) and loss_db >= 0.0):
        raise ValueError(
            f"{key}: cable_loss_db 必须为非负有限数，得到 {cable_loss_db!r}")

    g_lin = 10.0 ** (gain_db / 10.0)
    p_ant_w = (e_field * dist) ** 2 / (30.0 * g_lin)
    p_gen_w = p_ant_w * 10.0 ** (loss_db / 10.0)
    eirp_w = p_ant_w * g_lin
    # 恒等回核：E=√(30·EIRP)/R 反演残差（构造级恒等，残差逐位回显）
    e_back = math.sqrt(30.0 * eirp_w) / dist
    residual = abs(e_back - e_field) / e_field

    af_db_per_m: float | None = None
    if freq_mhz is not None:
        fm = float(freq_mhz)
        if not (math.isfinite(fm) and fm > 0.0):
            raise ValueError(
                f"{key}: freq_mhz 必须为正有限数，得到 {freq_mhz!r}")
        af_db_per_m = 20.0 * math.log10(fm) - gain_db - 29.79

    return {
        "standard": "IEC 61000-4-3 (radiated RF immunity)",
        "test_level": (int(test_level) if test_level is not None else None),
        "level_field_v_per_m": (e_field if test_level is not None else None),
        "field_v_per_m": e_field,
        "field_dbuv_per_m": round(20.0 * math.log10(e_field) + 120.0, 6),
        "distance_m": dist,
        "antenna_gain_db": gain_db,
        "cable_loss_db": loss_db,
        "p_fwd_antenna_w": round(p_ant_w, 12),
        "p_fwd_antenna_dbm": round(10.0 * math.log10(p_ant_w / _DBM_REF_W), 6),
        "p_fwd_source_w": round(p_gen_w, 12),
        "p_fwd_source_dbm": round(10.0 * math.log10(p_gen_w / _DBM_REF_W), 6),
        "eirp_w": round(eirp_w, 12),
        "eirp_dbm": round(10.0 * math.log10(eirp_w / _DBM_REF_W), 6),
        "identity_residual_rel": round(residual, 15),
        "af_db_per_m": (round(af_db_per_m, 6)
                        if af_db_per_m is not None else None),
        "modulation_note": ("试验时 80% AM 1kHz 调幅：包络峰电压 ×1.8，峰"
                            "功率 ×3.24（+5.105dB）——功率预算按包络峰评估"
                            "时自加此裕量，本键换算为未调制载波口径"),
        "uniform_field_note": "均匀域 1.5m×1.5m（3m 距离口径；10m 用于大 EUT）",
        "source": _SOURCE_RS,
    }


# ─── 键 2：IEC 61000-4-6 传导抗扰 CDN 耦合口径 ───────────────────────────────

@register_calculator(
    "conducted_immunity_cdn",
    "传导抗扰换算：IEC 61000-4-6 射频传导抗扰 CDN 耦合口径电压/功率换算：严酷度 "
    "test_level（1/2/3→1/3/10 V **emf**，Table 1 开路电动势口径）或显式 "
    "emf_v 恰给其一 → 匹配负载端电压（emf/2）、所需功率 P=(emf/2)²/Z、"
    "注入电流、80% AM 1kHz 包络峰（×1.8/+5.105dB）双列。dB 恒等式口径"
    "写死：0 dBm=1mW → 50Ω 匹配端电压 106.9897 dBµV（惯称 107 dBµV）；"
    "emf 开路口径 +6.0206 dB（0 dBm≡113.01 dBµV emf）。锚：Level 3→"
    "0.5 W/26.99 dBm；emf×2→+6.0206 dB 同步",
    (("test_level", "int 严酷度等级 1|2|3（Table 1 emf 口径；与 emf_v "
      "恰给其一）"),
     ("emf_v", "float V 显式电动势 emf（开路口径，>0；与 test_level 恰给"
      "其一）"),
     ("system_z_ohm", "float Ω 系统阻抗（>0，缺省 50）")),
    required=(),
)
def conducted_immunity_cdn(test_level: int | None = None,
                           emf_v: float | None = None,
                           system_z_ohm: float = 50.0) -> dict[str, Any]:
    key = "conducted_immunity_cdn"
    if (test_level is None) == (emf_v is None):
        raise ValueError(
            f"{key}: test_level（等级查表）与 emf_v（显式 emf）恰给其一")
    if test_level is not None:
        lvl = int(test_level)
        if lvl not in _CS_LEVELS_V_EMF:
            raise ValueError(
                f"{key}: test_level 须为 1|2|3（IEC 61000-4-6 Table 1），"
                f"得到 {test_level!r}")
        emf = _CS_LEVELS_V_EMF[lvl]
    else:
        emf = float(emf_v)
        if not (math.isfinite(emf) and emf > 0.0):
            raise ValueError(
                f"{key}: emf_v 必须为正有限数，得到 {emf_v!r}")
    z = float(system_z_ohm)
    if not (math.isfinite(z) and z > 0.0):
        raise ValueError(
            f"{key}: system_z_ohm 必须为正有限数，得到 {system_z_ohm!r}")

    v_load = emf / 2.0  # 匹配端电压（emf 开路 / 分压 2）
    p_w = v_load * v_load / z
    i_rms = v_load / z
    v0_dbm = math.sqrt(_DBM_REF_W * z)
    p_am_w = p_w * _AM80_FACTOR ** 2

    return {
        "standard": "IEC 61000-4-6 (conducted RF immunity, CDN coupling)",
        "test_level": (int(test_level) if test_level is not None else None),
        "level_emf_v": (emf if test_level is not None else None),
        "emf_v": emf,
        "emf_dbuv": round(20.0 * math.log10(emf) + 120.0, 6),
        "v_load_v": round(v_load, 12),
        "v_load_dbuv": round(20.0 * math.log10(v_load) + 120.0, 6),
        "p_fwd_w": round(p_w, 12),
        "p_fwd_dbm": round(10.0 * math.log10(p_w / _DBM_REF_W), 6),
        "i_load_rms_a": round(i_rms, 12),
        "am_80_percent": {
            "envelope_voltage_factor": _AM80_FACTOR,
            "peak_power_factor_db": round(
                20.0 * math.log10(_AM80_FACTOR), 6),
            "v_peak_env_v": round(v_load * _AM80_FACTOR, 12),
            "p_peak_w": round(p_am_w, 12),
            "p_peak_dbm": round(10.0 * math.log10(p_am_w / _DBM_REF_W), 6),
            "i_peak_env_a": round(i_rms * _AM80_FACTOR, 12),
            "note": "80% AM 1kHz（IEC 61000-4-6 §7 试验调制）",
        },
        "db_reference": {
            "basis": "0 dBm = 1 mW；0 dBm → Z 匹配端电压 √(1mW·Z)",
            "v_load_at_0dbm_v": round(v0_dbm, 12),
            "v_load_at_0dbm_dbuv": round(20.0 * math.log10(v0_dbm) + 120.0,
                                         6),
            "emf_at_0dbm_dbuv": round(20.0 * math.log10(2.0 * v0_dbm) + 120.0,
                                      6),
            "note": ("50Ω 下 0 dBm=106.9897 dBµV（匹配端电压，惯称 107 "
                     "dBµV）；emf 开路口径=2×端电压=+6.0206 dB（113.0103 "
                     "dBµV）——本族电平均按 emf↔功率此恒等式互算"),
        },
        "source": _SOURCE_CS,
    }


# ─── 键 3：IEC 61000-4-2 接触放电双指数波形 ──────────────────────────────────

def _de_current(t_ns: float, tau1: float, tau2: float, i0: float) -> float:
    """双指数 I(t)=I0(e^{−t/τ1}−e^{−t/τ2})（t/τ 同单位 ns）。"""
    return i0 * (math.exp(-t_ns / tau1) - math.exp(-t_ns / tau2))


def _de_peak_time_ns(tau1: float, tau2: float) -> float:
    """解析峰时 t_p=τ1τ2·ln(τ1/τ2)/(τ1−τ2)（dI/dt=0）。"""
    return tau1 * tau2 * math.log(tau1 / tau2) / (tau1 - tau2)


def _de_peak_factor(tau1: float, tau2: float) -> float:
    """峰值因子 I(t_p)/I0（<1，I0 反解载体）。"""
    return _de_current(_de_peak_time_ns(tau1, tau2), tau1, tau2, 1.0)


def _de_rise_time_ns(tau1: float, tau2: float) -> float:
    """上升时间 t_r=90% 分位时刻−10% 分位时刻（峰值归一双分位二分）。"""
    pf = _de_peak_factor(tau1, tau2)
    tp = _de_peak_time_ns(tau1, tau2)

    def t_at(frac: float) -> float:
        target = frac * pf
        lo_t, hi_t = 0.0, tp
        for _ in range(200):
            mid = 0.5 * (lo_t + hi_t)
            if _de_current(mid, tau1, tau2, 1.0) < target:
                lo_t = mid
            else:
                hi_t = mid
        return 0.5 * (lo_t + hi_t)

    return t_at(0.9) - t_at(0.1)


def _de_tail_ratio(tau1: float, tau2: float) -> float:
    """I(30)/I(60) 比值（τ1 单调降 → 对数域二分，唯一根）。"""
    return ((math.exp(-30.0 / tau1) - math.exp(-30.0 / tau2))
            / (math.exp(-60.0 / tau1) - math.exp(-60.0 / tau2)))


def _solve_tau2(rise_target_ns: float, tau1: float) -> float:
    """给 τ1 解 τ2 使 t_r=rise_target（t_r 随 τ2 单调升，二分）。"""
    lo2, hi2 = 1e-4, 5.0
    for _ in range(200):
        mid = 0.5 * (lo2 + hi2)
        if _de_rise_time_ns(tau1, mid) < rise_target_ns:
            lo2 = mid
        else:
            hi2 = mid
    return 0.5 * (lo2 + hi2)


def _solve_tau1(tau2: float) -> float:
    """给 τ2 解 τ1 使 I(30)/I(60)=2（ratio 随 τ1 单调降，对数域二分）。"""
    lo1 = math.log(tau2 * 1.0001)
    hi1 = math.log(1.0e5)
    for _ in range(200):
        mid = 0.5 * (lo1 + hi1)
        if _de_tail_ratio(math.exp(mid), tau2) > 2.0:
            lo1 = mid
        else:
            hi1 = mid
    return math.exp(0.5 * (lo1 + hi1))


@register_calculator(
    "esd_contact_waveform",
    "接触放电波形：IEC 61000-4-2 接触放电（ESD）双指数电流波形特征键：波形表仅对接触"
    "放电定义（空气放电无独立表），归一化每 kV——Ip=3.75 A/kV（±10%）、"
    "I(30ns)=2 A/kV、I(60ns)=1 A/kV（±30%）、t_r=0.6–1 ns（150pF/330Ω "
    "发生器校准口径，单源消费 core/emc_tvs_gate）。保守双指数参数化 "
    "I(t)=I0(e^(−t/τ1)−e^(−t/τ2))（规范只给包络点，非规范定义）：三条件"
    "定参=峰值 + I(30)/I(60)=2:1 比值恒等 + rise_time_ns（缺省 0.7，域 "
    "[0.6,1.0]）；τ1/τ2 定点迭代（单调二分），I0 由解析峰时反解。恒等"
    "锚：∫I dt=I0(τ1−τ2) 解析面积 vs 梯形积分回收；4 kV→15 A/0.7 ns；"
    "8 kV 波形=2×4 kV 波形（归一化表线性性）",
    (("charge_kv", "float kV 充电电压（接触放电档 {2,4,6,8}）"),
     ("rise_time_ns", "float ns 上升时间 t_r 10%→90%（[0.6,1.0] 规范窗，"
      "缺省 0.7）"),
     ("n_points", "int 波形采样点数（[50,5000]，缺省 401）"),
     ("t_max_ns", "float ns 波形时窗（[30,200]，缺省 100）")),
    required=("charge_kv",),
)
def esd_contact_waveform(charge_kv: float, rise_time_ns: float = 0.7,
                         n_points: int = 401,
                         t_max_ns: float = 100.0) -> dict[str, Any]:
    key = "esd_contact_waveform"
    kv = float(charge_kv)
    if kv not in _ESD_CONTACT_LEVELS_KV:
        raise ValueError(
            f"{key}: charge_kv 须为接触放电标准档 {list(_ESD_CONTACT_LEVELS_KV)}"
            f"（IEC 61000-4-2 Table 1），得到 {charge_kv!r}")
    rise = float(rise_time_ns)
    if not (math.isfinite(rise)
            and _ESD_RISE_WINDOW_NS[0] <= rise <= _ESD_RISE_WINDOW_NS[1]):
        raise ValueError(
            f"{key}: rise_time_ns 须在 {list(_ESD_RISE_WINDOW_NS)} ns 规范窗"
            f"内，得到 {rise_time_ns!r}")
    n = int(n_points)
    if n < 50 or n > 5000:
        raise ValueError(f"{key}: n_points 须在 [50,5000] 内，得到 {n_points!r}")
    t_max = float(t_max_ns)
    if not (math.isfinite(t_max) and 30.0 <= t_max <= 200.0):
        raise ValueError(
            f"{key}: t_max_ns 须在 [30,200] ns 内，得到 {t_max_ns!r}")

    from rfauto.core.emc_tvs_gate import (
        ESD_GENERATOR_C_PF,
        ESD_GENERATOR_R_OHM,
        esd_waveform_currents,
    )

    std = esd_waveform_currents(kv)
    i_peak_nom = float(std["i_peak_a"])
    i30_nom = float(std["i_30ns_a"])
    i60_nom = float(std["i_60ns_a"])

    # 定点迭代：τ2 ← rise(τ1)，τ1 ← ratio(τ2)（两条件各自单调二分，
    # 映射压缩快，60 轮机器精度级收敛且确定性）
    tau1, tau2 = 43.0, 0.32
    for _ in range(60):
        tau2_new = _solve_tau2(rise, tau1)
        tau1_new = _solve_tau1(tau2_new)
        if abs(tau1_new - tau1) < 1e-13 and abs(tau2_new - tau2) < 1e-13:
            tau1, tau2 = tau1_new, tau2_new
            break
        tau1, tau2 = tau1_new, tau2_new
    i0 = i_peak_nom / _de_peak_factor(tau1, tau2)
    t_p = _de_peak_time_ns(tau1, tau2)
    i30 = _de_current(30.0, tau1, tau2, i0)
    i60 = _de_current(60.0, tau1, tau2, i0)

    # 恒等锚：解析面积 I0(τ1−τ2) vs 梯形积分数值回收。两段网格——密栅
    # [0,5ns] 吃上升沿离散化（dt=0.25ps，误差 ~1e-10 相对），粗栅
    # [5ns,60τ1] 吃尾部（60τ1 处 e^−60→0）——与输出时窗 t_max 无关
    # （恒等是模型性质，不是窗口性质）
    charge_n_c = i0 * (tau1 - tau2)
    n_seg = 20001

    def _trapz(t_a: float, t_b: float, n: int) -> float:
        dt = (t_b - t_a) / (n - 1)
        prev = _de_current(t_a, tau1, tau2, i0)
        total = 0.0
        for k in range(1, n):
            cur = _de_current(t_a + dt * k, tau1, tau2, i0)
            total += 0.5 * (prev + cur) * dt
            prev = cur
        return total

    area_num = _trapz(0.0, 5.0, n_seg) + _trapz(5.0, 60.0 * tau1, n_seg)
    area_residual_rel = abs(area_num - charge_n_c) / charge_n_c
    cv_charge_n_c = ESD_GENERATOR_C_PF * 1e-12 * kv * 1e3 * 1e9  # C·V → nC
    charge_ratio = charge_n_c / cv_charge_n_c

    step = t_max / (n - 1)
    t_grid = [step * i for i in range(n)]
    i_grid = [_de_current(t, tau1, tau2, i0) for t in t_grid]

    return {
        "standard": "IEC 61000-4-2 (ESD, contact discharge)",
        "charge_kv": kv,
        "waveform_model": "I(t)=I0·(e^(−t/τ1)−e^(−t/τ2)) 双指数（保守"
                          "参数化，规范只给包络点）",
        "tau1_ns": round(tau1, 9),
        "tau2_ns": round(tau2, 9),
        "i0_a": round(i0, 9),
        "t_peak_ns": round(t_p, 9),
        "i_peak_a": round(_de_current(t_p, tau1, tau2, i0), 9),
        "rise_time_ns": round(_de_rise_time_ns(tau1, tau2), 9),
        "i_30ns_a": round(i30, 6),
        "i_60ns_a": round(i60, 6),
        "nominal_points": {
            "i_peak_a": i_peak_nom,
            "i_30ns_a": i30_nom,
            "i_60ns_a": i60_nom,
            "tolerance_note": "Ip ±10%、I(30/60ns) ±30%（Table 2/3）；"
                              "双指数族下 I(30)/I(60)=2:1 比值恒等定参，"
                              "30/60 绝对值有 ~1.6% 级系统差（容差带内，"
                              "如实回显）",
        },
        "charge_n_c": round(charge_n_c, 6),
        "charge_identity": {
            "analytic_n_c": round(charge_n_c, 6),
            "numeric_trapz_n_c": round(area_num, 6),
            "residual_rel": round(area_residual_rel, 12),
            "identity": "∫I dt = I0·(τ1−τ2)",
        },
        "generator_charge_reference": {
            "c_pf": ESD_GENERATOR_C_PF,
            "r_ohm": ESD_GENERATOR_R_OHM,
            "cv_charge_n_c": round(cv_charge_n_c, 6),
            "waveform_charge_ratio": round(charge_ratio, 6),
            "note": "双指数放电电荷对发生器储能 C·V 的比值（包络点容差"
                    "量级自洽窗 [0.8,1.5]；理想 DE 不严格守恒于物理发生"
                    "器，仅量级核对）",
        },
        "t_grid_ns": [round(t, 6) for t in t_grid],
        "i_grid_a": [round(v, 9) for v in i_grid],
        "waveform_scope": std["waveform_scope"],
        "source": _SOURCE_ESD,
    }
