"""检波/功率测量器件族（架构批 A4-B 席域 2，R7 第二梯队 T10=G13；
架构批 W1-S2 补齐任务书"热偶/测辐射热计功率计换算"子项）。

出处（第一性传递恒等式+工程判据惯例，正文物理口径节转录）：
- diode_square_law_detect：小信号平方律检波 I_dc=k·R_j·P_in（零偏
  Schottky 二极管伏安特性小信号泰勒展开，第一性；平方律域上沿工程
  惯例量级 docstring 写死）。
- detector_tss_nep：视频约翰逊-奈奎斯特噪声链 NEP=v_n/γ（第一性）
  + 8dB 切向灵敏度判据（EW 接收机工程量化惯例，二级转引口径）。
- thermal_power_sensor_detect：热链 ΔT=η·R_th·P 与 Seebeck EMF
  （热电效应第一性；热偶/测辐射热计功率计工程惯例）。

三键：diode_square_law_detect（二极管平方律检波：小信号 i∝v² →
I_dc=k·R_j·P_in 恒等 + 视频电压输出） / detector_tss_nep（切向灵敏度
TSS/噪声等效功率 NEP：视频热噪声链 + 8dB 切向判据口径写死） /
thermal_power_sensor_detect（热偶/测辐射热计功率换算：热链 ΔT=η·R_th·P
→ Seebeck EMF/平衡电桥小信号输出，W1-S2）。

与既有测量面的边界（语义防撞，R7 §② G13 三重搜索证据）
--------------------------------------------------------
- power_cal_chain（SB22-MS-1）= 功率**校准链**（传感器溯源地/失配
  修正面）；cispr_detector = EMC 接收机**检波算法**（QP/AV 加权）；
  nf_measurement = 噪声系数 Y 因子——本族只做**检波器件级**传递关
  系（检波二极管/检波器组件的功率→直流换算与灵敏度极限）。
- `tss` 全仓 grep 仅 alt_planning 应力温度误命中（R7 证据）——本族
  是仓内首个器件级检波键。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 平方律检波（小信号，零偏 Schottky 检波器工程模型）：检波传递
  i = k·v²（k=转移曲率，单位 A/V²；平方项主导的直流分量）。
  射频匹配下 P_in=V_rms²/R_j（R_j=检波管射频阻抗）→

      I_dc = k·V_rms² = (k·R_j)·P_in ≡ β·P_in

  恒等式（测试钉）：**电流灵敏度 β=k·R_j 与功率无关**（平方律区
  常数），I_dc 逐位线性于 P_in（P×2 → I×2）。视频负载 R_v 上
  V_video = I_dc·R_v。平方律有效域上沿 p_sq_max_dbm 缺省 −20 dBm
  （零偏 Schottky 工程惯例量级，docstring 写死；实际器件以厂家
  曲线为准）——越沿=线性/压缩区，本键显式拒绝不外推。
- TSS/NEP（视频噪声链，square-law detector 接收灵敏度经典口径）：
  视频负载约翰逊-奈奎斯特噪声 v_n=√(4k_BT·R_v·B_v)（B_v=视频带宽）。

      NEP = v_n/γ                  （输出 SNR=1 的输入功率，γ=电压
                                    灵敏度 V/W，平方律区 γ=R_v·β）
      TSS: 输出（检波后）SNR = snr_tss_db ≡ 8.0 dB 的输入功率
           （切向显示判据"噪声顶部=信号噪声底部"的工程量化惯例，
           8dB 口径 docstring 写死；TSS 按脉冲定义，B_v 与脉冲宽
           度配套选择，如实注记）

  平方律下 SNR∝P² → TSS/NEP 功率比 = 10^(snr/20)（dB 差=snr/2，
  8dB 判据恰 +4.0dB，恒等式测试钉）。NEP∝√(R_v·B_v/T) 标度逐点钉
  （B×4→NEP×2、R_v×4→NEP×2）。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- 检波键：I_dc=k·R_j·P_in 测试侧独立重算逐位；线性标度 P×2→I×2；
  β 常数性（两功率点 β 同值）；V_video=I_dc·R_v 回代；dBm↔mW↔W
  换算独立常数链（10^(dbm/10) 口径）。
- TSS 键：v_n=√(4k_BT·R_v·B_v) 测试侧独立常数重算（k_B=1.380649e-23
  精确定义值）；NEP=v_n/γ 回代；TSS−NEP=snr/2 dB 恒等；√B/√R_v
  标度逐位。

守卫：p_in_dbm∈[−120, p_sq_max_dbm]（域外显式拒绝——低功率端噪声
主导非器件传递、高功率端出平方律）；k_uav2>0；r_j_ohm>0；
r_v_ohm>0；gamma_v_per_w>0；b_video_hz>0；t_kelvin>0；
snr_tss_db∈(0,40)；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

# 玻尔兹曼常数（SI 2019 精确定义值）
_K_B = 1.380649e-23
# 平方律有效域（dBm）：低功率端以下噪声主导、高功率端以上出平方律
_P_DBM_MIN = -120.0
_P_SQ_MAX_DBM_DEFAULT = -20.0
# 切向灵敏度判据（检波后 SNR 口径，工程惯例 8 dB，docstring 写死）
_TSS_SNR_DB_DEFAULT = 8.0

_SOURCES = {
    "detect": "平方律检波工程模型 i=kv²（零偏 Schottky 小信号）→ I_dc=(k·R_j)·P_in；"
              "平方律有效域上沿 −20dBm 工程惯例（实际器件以厂家曲线为准，如实注记）",
    "tss": "视频约翰逊噪声 v_n=√(4k_BT·R_v·B_v)；NEP=v_n/γ；TSS=检波后 SNR=8dB "
           "切向判据（平方律下 TSS−NEP=snr/2=4.0dB 恒等）",
}


# ─── 键 1：二极管平方律检波 ──────────────────────────────────────────────────

@register_calculator(
    "diode_square_law_detect",
    "二极管平方律检波：小信号 i=kv²（k=转移曲率）+射频匹配 P=V_rms²/R_j →"
    " I_dc=(k·R_j)·P_in≡β·P_in（电流灵敏度 β 与功率无关=平方律恒等锚），"
    "视频电压 V_video=I_dc·R_v；dBm→mW→V_rms 换算链直出。平方律有效域"
    "[−120,−20]dBm（上沿=零偏 Schottky 工程惯例，域外显式拒绝不外推到"
    "压缩区）。锚：I_dc=k·R_j·P_in 测试侧独立重算；P×2→I×2 线性标度；"
    "β 两功率点同值；V_video=I·R_v 回代",
    (("p_in_dbm", "float dBm 射频输入功率（∈[−120,p_sq_max_dbm]，缺省上沿"
      "−20）"),
     ("k_uav2", "float µA/V² 平方律转移曲率 k（>0；i=kv²，I_dc=k·V_rms²）"),
     ("r_j_ohm", "float Ω 检波管射频阻抗（>0；匹配口径 P=V_rms²/R_j）"),
     ("r_v_ohm", "float Ω 视频负载（>0，缺省 1e6 高阻视频）"),
     ("p_sq_max_dbm", "float dBm 平方律有效域上沿（>p_in_dbm 下限，缺省 "
      "−20；实际器件以厂家曲线为准）")),
    required=("p_in_dbm", "k_uav2", "r_j_ohm"),
)
def diode_square_law_detect(p_in_dbm: float, k_uav2: float, r_j_ohm: float,
                            r_v_ohm: float = 1.0e6,
                            p_sq_max_dbm: float = _P_SQ_MAX_DBM_DEFAULT
                            ) -> dict[str, Any]:
    p_dbm = _finite(p_in_dbm, "p_in_dbm")
    k_ua = _finite(k_uav2, "k_uav2")
    r_j = _finite(r_j_ohm, "r_j_ohm")
    r_v = _finite(r_v_ohm, "r_v_ohm")
    p_max_dbm = _finite(p_sq_max_dbm, "p_sq_max_dbm")
    if not _P_DBM_MIN <= p_dbm <= p_max_dbm:
        raise ValueError(
            f"diode_square_law_detect: p_in_dbm={p_dbm!r} 超出平方律有效域 "
            f"[{_P_DBM_MIN},{p_max_dbm!r}]（低功率端噪声主导、高功率端出平方"
            "律进入压缩区，本键不外推），显式拒绝")
    if k_ua <= 0.0:
        raise ValueError(
            f"diode_square_law_detect: k_uav2 必须 >0，得到 {k_uav2!r}")
    if r_j <= 0.0:
        raise ValueError(
            f"diode_square_law_detect: r_j_ohm 必须 >0，得到 {r_j_ohm!r}")
    if r_v <= 0.0:
        raise ValueError(
            f"diode_square_law_detect: r_v_ohm 必须 >0，得到 {r_v_ohm!r}")
    if p_max_dbm <= _P_DBM_MIN:
        raise ValueError(
            "diode_square_law_detect: p_sq_max_dbm 必须 >−120（有效域非空），"
            f"得到 {p_sq_max_dbm!r}")

    p_w = 10.0 ** (p_dbm / 10.0) * 1e-3          # dBm → W
    k_a_per_v2 = k_ua * 1e-6                     # µA/V² → A/V²
    v_rms = math.sqrt(p_w * r_j)                 # V（匹配口径）
    i_dc_a = k_a_per_v2 * v_rms * v_rms          # 平方律直流分量
    beta_a_per_w = k_a_per_v2 * r_j              # 电流灵敏度（常数恒等）
    v_video_v = i_dc_a * r_v
    # p_w>0 恒成立（p_dbm≥−120）；防御分支仅护栏（#364④ 数值可达 0 面）
    beta_xcheck = i_dc_a / p_w if i_dc_a > 0.0 else beta_a_per_w
    beta_rel_dev = abs(beta_xcheck - beta_a_per_w) / beta_a_per_w
    return {
        "p_in_dbm": p_dbm,
        "p_in_w": round(p_w, 18),
        "p_in_mw": round(p_w * 1e3, 15),
        "v_rms_v": round(v_rms, 15),
        "k_a_per_v2": round(k_a_per_v2, 18),
        "r_j_ohm": r_j,
        "r_v_ohm": r_v,
        "i_dc_a": round(i_dc_a, 18),
        "beta_a_per_w": round(beta_a_per_w, 15),
        "beta_xcheck_rel_dev": round(beta_rel_dev, 15),
        "v_video_v": round(v_video_v, 15),
        "region": "square_law",
        "note": (
            "平方律区器件级传递（i=kv² 小信号主项）：I_dc 线性于 P_in、"
            "灵敏度 β=k·R_j 为常数；V_video=I_dc·R_v 高阻视频口径；实际"
            "器件的 k/R_j 随偏置与驱动电平漂移，平方律上沿以厂家曲线为准"
            "（−20dBm 为工程惯例缺省，如实注记非通用常数）"),
        "source": _SOURCES["detect"],
    }


# ─── 键 2：切向灵敏度 TSS / 噪声等效功率 NEP ────────────────────────────────

@register_calculator(
    "detector_tss_nep",
    "检波器切向灵敏度 TSS/噪声等效功率 NEP：视频约翰逊噪声 "
    "v_n=√(4k_BT·R_v·B_v) → NEP=v_n/γ（输出 SNR=1 输入功率，γ=电压灵敏"
    "度 V/W）；TSS=检波后 SNR=8dB 的输入功率（切向显示判据口径写死，"
    "平方律下 TSS−NEP=snr/2 dB——8dB 判据恰 +4.0dB 恒等锚）；NEP∝"
    "√(R_v·B_v/T) 标度可钉。TSS 按脉冲定义（B_v 与脉宽配套，如实注记）。"
    "锚：v_n 测试侧独立常数重算；√B/√R_v 标度逐位；TSS−NEP=snr/2 恒等",
    (("gamma_v_per_w", "float V/W 电压灵敏度 γ（>0；典型零偏 Schottky "
      "10³–10⁴ 量级）"),
     ("r_v_ohm", "float Ω 视频负载（>0，缺省 1e6）"),
     ("b_video_hz", "float Hz 视频带宽（>0，缺省 1e6；与检波脉冲宽度配套）"),
     ("t_kelvin", "float K 噪声温度（>0，缺省 290）"),
     ("snr_tss_db", "float dB 切向判据检波后 SNR（∈(0,40)，缺省 8.0 工程"
      "惯例口径）")),
    required=("gamma_v_per_w",),
)
def detector_tss_nep(gamma_v_per_w: float, r_v_ohm: float = 1.0e6,
                     b_video_hz: float = 1.0e6, t_kelvin: float = 290.0,
                     snr_tss_db: float = _TSS_SNR_DB_DEFAULT
                     ) -> dict[str, Any]:
    gamma = _finite(gamma_v_per_w, "gamma_v_per_w")
    r_v = _finite(r_v_ohm, "r_v_ohm")
    b_v = _finite(b_video_hz, "b_video_hz")
    t_k = _finite(t_kelvin, "t_kelvin")
    snr_db = _finite(snr_tss_db, "snr_tss_db")
    if gamma <= 0.0:
        raise ValueError(
            f"detector_tss_nep: gamma_v_per_w 必须 >0，得到 {gamma_v_per_w!r}")
    if r_v <= 0.0:
        raise ValueError(
            f"detector_tss_nep: r_v_ohm 必须 >0，得到 {r_v_ohm!r}")
    if b_v <= 0.0:
        raise ValueError(
            f"detector_tss_nep: b_video_hz 必须 >0，得到 {b_video_hz!r}")
    if t_k <= 0.0:
        raise ValueError(
            f"detector_tss_nep: t_kelvin 必须 >0，得到 {t_kelvin!r}")
    if not 0.0 < snr_db < 40.0:
        raise ValueError(
            "detector_tss_nep: snr_tss_db 须 ∈(0,40)（8.0=切向判据工程惯例），"
            f"得到 {snr_tss_db!r}")

    v_n = math.sqrt(4.0 * _K_B * t_k * r_v * b_v)   # 视频噪声（rms V）
    nep_w = v_n / gamma                              # SNR=1 输入功率
    # 平方律：SNR_out ∝ P_in² → P_tss = NEP·10^(snr/20)
    tss_w = nep_w * 10.0 ** (snr_db / 20.0)
    tss_minus_nep_db = snr_db / 2.0                  # 恒等式（功率域 dB）
    return {
        "gamma_v_per_w": gamma,
        "r_v_ohm": r_v,
        "b_video_hz": b_v,
        "t_kelvin": t_k,
        "snr_tss_db": snr_db,
        "v_noise_rms_v": round(v_n, 18),
        "nep_w": round(nep_w, 18),
        "nep_dbm": round(10.0 * math.log10(nep_w) + 30.0, 12),
        "tss_w": round(tss_w, 18),
        "tss_dbm": round(10.0 * math.log10(tss_w) + 30.0, 12),
        "tss_minus_nep_db": round(tss_minus_nep_db, 12),
        "convention": (
            "TSS=检波后 SNR=8.0dB 输入功率（切向显示判据的工程量化；"
            "平方律下 TSS/NEP=10^(snr/20)，dB 差=snr/2）"),
        "note": (
            "TSS 按脉冲定义（视频带宽与脉宽配套选择，连续波灵敏度另按 "
            "B_v→窄带口径自算）；只含视频负载热噪声——检波管内噪声/1f、"
            "视频放大器 NF 与匹配损耗未计入（如实注记，实测 TSS 恶化量="
            "各项 dB 叠加）；γ 折算含视频负载口径（γ=V_video/P_in）"),
        "source": _SOURCES["tss"],
    }


# ─── 键 3：热偶/测辐射热计功率计换算（架构批 W1-S2 补齐 T10 子项）─────────
# 口径（热式功率传感器器件级传递，教科书热链模型；docstring 写死）：
#   热链（准静态）：吸收功率 η·P_in → 热阻温升 ΔT = η·R_th·P_in；
#   热时间常数 τ = R_th·C_th、3dB 视频带宽 f_3dB = 1/(2πτ)。
#   热偶（thermocouple）：塞贝克效应 V_out = S·ΔT = S·η·R_th·P_in，
#     γ ≡ S·η·R_th（V/W，与功率无关——线性恒等锚）。
#   测辐射热计（bolometer）：ΔR = R0·TCR·ΔT，平衡惠斯通电桥小信号
#     V_out = (V_b/4)·(ΔR/R0) = (V_b/4)·TCR·η·R_th·P_in——电桥小信号
#     输出与 R0 绝对值无关（恒等锚，R0 只进报告面）；TCR 符号如实
#     保留（热敏负/金属膜正），γ 带符号输出。
#   最小可检功率（可选噪声底）：P_min = v_noise/|γ|（输出 SNR=1 口径，
#     与 detector_tss_nep 的 NEP 同构——此处器件级、彼处含判据）。
#   锚（#118）：功率→电压→功率往返回收逐位；P×2→V×2 线性；γ 测试侧
#   独立重算；同 γ 跨类型等价（热偶 S 与电桥参数凑同 γ → 输出逐位
#   一致=热链单源结构恒等）；τ=R_th·C_th 恒等。

_THERMAL_P_DBM_MIN = -120.0
_THERMAL_P_DBM_MAX = 30.0

_SENSOR_TYPES = ("thermocouple", "bolometer")


@register_calculator(
    "thermal_power_sensor_detect",
    "热偶/测辐射热计功率换算：吸收 η·P_in → 热阻温升 ΔT=η·R_th·P_in →"
    "热偶 Seebeck V_out=S·ΔT / 测辐射热计平衡电桥小信号 V_out=(V_b/4)·"
    "TCR·ΔT（γ=V_out/P 与功率无关=线性恒等锚；电桥输出与 R0 绝对值无关"
    "恒等锚；TCR 符号如实保留）；τ=R_th·C_th、f_3dB=1/(2πτ)、最小可检"
    "功率=v_noise/|γ|。锚：功率→电压→功率往返回收逐位；P×2→V×2；同 γ "
    "跨类型输出逐位一致（热链单源结构恒等）",
    (("sensor_type", "str 'thermocouple'|'bolometer'（封闭集合）"),
     ("p_in_dbm", "float dBm 入射射频功率（∈[−120,30]，域外显式拒绝）"),
     ("r_th_k_per_w", "float K/W 热阻（>0；吸收体→环境热链）"),
     ("c_th_j_per_k", "float J/K 热容（>0；τ=R_th·C_th 输入）"),
     ("eta_abs", "float 吸收效率（∈(0,1]，缺省 1.0；实际器件 0.8~0.95 "
      "量级以厂家为准）"),
     ("seebeck_v_per_k", "float V/K 热偶塞贝克系数（thermocouple 必给>0；"
      "热偶堆 1e-5~1e-2 量级）"),
     ("tcr_per_k", "float 1/K 测辐射热计电阻温度系数（bolometer 必给≠0；"
      "符号如实保留：热敏负/金属膜正）"),
     ("r0_ohm", "float Ω 测辐射热计冷态电阻（bolometer 可给>0；只进报告"
      "面——电桥小信号输出与 R0 绝对值无关）"),
     ("v_bridge_v", "float V 电桥偏置（bolometer 必给>0）"),
     ("v_noise_rms_v", "float rms V 输出噪声底（≥0，缺省 0=不报最小可检"
      "功率）")),
    required=("sensor_type", "p_in_dbm", "r_th_k_per_w", "c_th_j_per_k"),
)
def thermal_power_sensor_detect(sensor_type: str, p_in_dbm: float,
                                r_th_k_per_w: float, c_th_j_per_k: float,
                                eta_abs: float = 1.0,
                                seebeck_v_per_k: float | None = None,
                                tcr_per_k: float | None = None,
                                r0_ohm: float | None = None,
                                v_bridge_v: float | None = None,
                                v_noise_rms_v: float = 0.0
                                ) -> dict[str, Any]:
    stype = str(sensor_type).strip().lower()
    if stype not in _SENSOR_TYPES:
        raise ValueError(
            f"thermal_power_sensor_detect: sensor_type 须 "
            f"{'|'.join(_SENSOR_TYPES)}，得到 {sensor_type!r}")
    p_dbm = _finite(p_in_dbm, "p_in_dbm")
    r_th = _finite(r_th_k_per_w, "r_th_k_per_w")
    c_th = _finite(c_th_j_per_k, "c_th_j_per_k")
    eta = _finite(eta_abs, "eta_abs")
    v_noise = _finite(v_noise_rms_v, "v_noise_rms_v")
    if not _THERMAL_P_DBM_MIN <= p_dbm <= _THERMAL_P_DBM_MAX:
        raise ValueError(
            f"thermal_power_sensor_detect: p_in_dbm={p_dbm!r} 超出器件域 "
            f"[{_THERMAL_P_DBM_MIN},{_THERMAL_P_DBM_MAX}]dBm（下缘以下噪声"
            "主导非器件传递、上缘以上超典型功率计 destruct 上限量级，本键"
            "不外推），显式拒绝")
    if r_th <= 0.0:
        raise ValueError(
            f"thermal_power_sensor_detect: r_th_k_per_w 必须 >0，得到 "
            f"{r_th_k_per_w!r}")
    if c_th <= 0.0:
        raise ValueError(
            f"thermal_power_sensor_detect: c_th_j_per_k 必须 >0，得到 "
            f"{c_th_j_per_k!r}")
    if not 0.0 < eta <= 1.0:
        raise ValueError(
            f"thermal_power_sensor_detect: eta_abs 须 ∈(0,1]，得到 "
            f"{eta_abs!r}")
    if v_noise < 0.0:
        raise ValueError(
            f"thermal_power_sensor_detect: v_noise_rms_v 必须 ≥0，得到 "
            f"{v_noise_rms_v!r}")

    seebeck: float | None = None
    tcr: float | None = None
    r0: float | None = None
    v_bridge: float | None = None
    if stype == "thermocouple":
        if seebeck_v_per_k is None:
            raise ValueError(
                "thermal_power_sensor_detect: sensor_type=thermocouple "
                "需要 seebeck_v_per_k（塞贝克系数 >0）")
        seebeck = _finite(seebeck_v_per_k, "seebeck_v_per_k")
        if seebeck <= 0.0:
            raise ValueError(
                "thermal_power_sensor_detect: seebeck_v_per_k 必须 >0，"
                f"得到 {seebeck_v_per_k!r}")
        for name, val in (("tcr_per_k", tcr_per_k), ("v_bridge_v",
                                                     v_bridge_v)):
            if val is not None:
                raise ValueError(
                    "thermal_power_sensor_detect: "
                    f"{name} 仅 sensor_type=bolometer 接受（同给显式拒绝），"
                    f"得到 {val!r}")
        gamma = seebeck * eta * r_th
        transducer = "seebeck_emf"
    else:
        if tcr_per_k is None:
            raise ValueError(
                "thermal_power_sensor_detect: sensor_type=bolometer 需要 "
                "tcr_per_k（电阻温度系数 ≠0）")
        if v_bridge_v is None:
            raise ValueError(
                "thermal_power_sensor_detect: sensor_type=bolometer 需要 "
                "v_bridge_v（电桥偏置 >0）")
        tcr = _finite(tcr_per_k, "tcr_per_k")
        v_bridge = _finite(v_bridge_v, "v_bridge_v")
        if tcr == 0.0:
            raise ValueError(
                "thermal_power_sensor_detect: tcr_per_k 必须 ≠0（零温度"
                "系数无换算），显式拒绝")
        if v_bridge <= 0.0:
            raise ValueError(
                "thermal_power_sensor_detect: v_bridge_v 必须 >0，得到 "
                f"{v_bridge_v!r}")
        if r0_ohm is not None:
            r0 = _finite(r0_ohm, "r0_ohm")
            if r0 <= 0.0:
                raise ValueError(
                    "thermal_power_sensor_detect: r0_ohm 必须 >0，得到 "
                    f"{r0_ohm!r}")
        gamma = v_bridge / 4.0 * tcr * eta * r_th
        transducer = "wheatstone_bridge_small_signal"

    p_w = 10.0 ** (p_dbm / 10.0) * 1e-3
    d_t_k = eta * r_th * p_w
    v_out = gamma * p_w
    tau_s = r_th * c_th
    f3db_hz = 1.0 / (2.0 * math.pi * tau_s)
    p_min_w = None if v_noise <= 0.0 else v_noise / abs(gamma)
    return {
        "sensor_type": stype,
        "transducer": transducer,
        "p_in_dbm": p_dbm,
        "p_in_w": round(p_w, 18),
        "eta_abs": eta,
        "r_th_k_per_w": r_th,
        "c_th_j_per_k": c_th,
        "seebeck_v_per_k": seebeck,
        "tcr_per_k": tcr,
        "r0_ohm": r0,
        "v_bridge_v": v_bridge,
        "delta_t_k": round(d_t_k, 18),
        "gamma_v_per_w": round(gamma, 18),
        "v_out_v": round(v_out, 18),
        "tau_s": round(tau_s, 15),
        "f3db_hz": round(f3db_hz, 12),
        "p_min_w": None if p_min_w is None else round(p_min_w, 18),
        "p_min_dbm": (None if p_min_w is None
                      else round(10.0 * math.log10(p_min_w) + 30.0, 12)),
        "note": (
            "热链准静态口径（P_min=f_3dB 频内；调制/脉冲测量按 τ 与脉宽"
            "配套判读）；γ 与功率无关=热式传感器线性区恒等（超出线性区/"
            "烧毁上限以厂家曲线为准，如实注记）；bolometer 电桥小信号"
            "输出与 R0 绝对值无关（R0 只进报告面）；只含输出噪声底——"
            "热链温度涨落噪声/放大器 NF 未计入（如实注记）"),
        "source": (
            "热式功率计器件级传递（热偶 Seebeck / 测辐射热计平衡电桥"
            "小信号；教科书热链模型 ΔT=η·R_th·P，γ 口径为本席独立"
            "推导落地；器件参数典型量级以厂家手册为准）"),
    }
