"""校准件完整性验证（架构批 W3-S10 席域，R2_core_tier3 §③ D5 立项）。

两键：cal_kit_standard_response（机械校准件 open/short/load/through 一阶
模型响应闭式——offset 短路电抗/损耗、open 边缘电容、load 失配地板、
through 损耗时延，+工程验收判据面）/ cal_kit_verify_ripple（校准后
verification 纹波法——纹波幅度↔残余方向性解析关系，正反双解+验收
判据，与 vna_reflection_uncertainty/directional_bridge 回损地板恒等式
同仓双源）。

与既有校准面分工（语义防撞，#222 triple-grep 2026-10-18 实测）
--------------------------------------------------------
- core/trl_solt.py + measurement/calibration.py = 校准件**使用**链
  （测量数据→误差箱提取→校准应用；test_calkit.py 的 load_calkit/
  apply_response_calibration 面）——本族做校准件**模型核验与质量
  验收**（给定标准件参数→理想响应偏离闭式→判据），测量链零改动。
- trl_standards.py = TRL 标准件**设计端**（长度/电长度综合）——本族
  做 SOLT 机械件**验证端**（响应偏离+纹波诊断），TRL/SOLT 互指不互代。
- vna_uncertainty.py = 误差箱**传播**（残差→测量不确定度预算）——
  本族给纹波法正反解与判据（其上游"验"半边）；回损地板恒等式互证。
- power_cal.py = 功率校准链——不同对象零撞。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **offset 传输线因子**（机械校准件统一模型，参考面在连接器）：
  β=2πf√εr/c（TEM 色散-free 档）、衰减系数按趋肤 √f 标度
  α_dB/m(f)=L₁·√f_GHz（L₁=1 GHz 每米损耗），单程损耗
  A_dB=L₁·√f_GHz·l_m；反射路径往返因子 e^{−2(α_np+jβ)l}
  （α_np=A_dB/8.6859）。
- **各标准件一阶闭式**（Z0=系统阻抗）：
  short：Γ=−e^{−2(α+jβ)l}（理想 l=0/无耗 → |Γ|=1、相位 180°；
    offset 短路电抗语义=相位随 2βl 旋转、|Γ| 随 2αl 压低）；
  open：边缘电容 C_f（fF 档）：Z_c=1/(jωC_f) →
    Γ_cap=(1−jωC_fZ0)/(1+jωC_fZ0)，Γ=Γ_cap·e^{−2(α+jβ)l}
    （理想 l=0/C=0 → |Γ|=1、相位 0°；C_f>0 → 相位随 f 单调负旋）；
  load：Z_L=ratio·Z0 → Γ₀=(ratio−1)/(ratio+1)（实数），偏置时
    Γ=Γ₀·e^{−2(α+jβ)l}；失配地板 RL=−20lg|Γ₀|（理想 ratio=1 →
    Γ₀=0、RL=∞ 走 None JSON 契约）；
  through：S21=e^{−(α+jβ)l}（匹配透射档）、IL=L₁·√f·l dB、
    时延 τ=l√εr/c。
- **验收判据面**（工程档缺省=计量级惯例带，调用方可覆写；非特定
  厂商 spec——厂商规格如实不冒充，#300 归属纪律）：short/open
  |Γ|≥gamma_mag_min（缺省 0.97≈0.26 dB 往返损耗预算）；load
  RL≥load_rl_min_db（缺省 35 dB）；through IL≤through_il_max_db
  （缺省 0.2 dB）。pass=适用判据合取；不适用判据如实 not_applicable。
- **纹波法**（校准后 verification，残余方向性 d=10^(D_db/20)、精确
  负载 |Γ_L|=g）：单端口误差模型一阶 Γ_meas=e00+…（方向性项主导）
  → |Γ_meas|∈[|g−d|, g+d]，回损窗 [rl_min, rl_max]，

      纹波峰峰 pp_dB = 20lg((g+d)/(g−d))，反向 d = g·(10^(pp/20)−1)
      /(10^(pp/20)+1)。

  完美负载 g=0 → 窗塌缩到 |Ed| 单点、pp=0、回损地板=−directivity_db
  （与 directional_bridge_response.rl_floor_db /
  vna_reflection_uncertainty 回损地板恒等式同值三方互证）；d≥g
  （g>0）=|Γ_meas| 圆环包围原点、相位回绕域——纹波窗仍给但回损
  "负载质量"判读失义（包围旗标+回损判据按不通过如实记，不外推假窗；
  d=g 恰过零时 dB 域峰峰无定义走 None）。
- **诚实边界（预声明）**：一阶模型——offset 线 Z0 失配/连接器重复性/
  辐射开路的频率相关电容高阶项（多参数 C0,C1,C2 拟合面）不在本域；
  纹波法只含方向性单误差项（源匹配/负载匹配残差的高阶纹波面归
  vna_uncertainty 误差箱合成）；√f 损耗标度对介质损耗主导件
  （tan_d 项 ∝f）须调用方换算后给等效 L₁。

出处
----
- EURAMET cg-12 / NIST TN 1341（vna_uncertainty 同源文献族，校准件
  模型与 verification 惯例；二级转引）。
- 机械校准件 offset 模型=经典 SOLT 标准件定义口径（Keysight 85052D
  族定义惯例的通用化：offset Z0/时延/损耗+termination 残差；本族
  参数化口径，非厂商 spec 复刻）。
- 纹波法=残余方向性↔回损纹波教科书关系（二级转引）。

守卫：standard_type 白名单；freq_ghz 有限>0；offset_length_mm≥0；
offset_loss_db_m_1ghz≥0；epsilon_r_offset≥1；z0_ohm>0；open_cap_ff
仅 open 键合法（非 open 给非零显式拒绝）；load_z_ratio 仅 load 合法
（>0）；gamma_mag_min∈[0.9,1]；load_rl_min_db∈[20,60]；
through_il_max_db>0；纹波键 load_gamma_mag∈[0,1]；
residual_directivity_db/measured_ripple_pp_db 恰给其一（<0 / >0）；
越界一律显式 ValueError。

出处（EURAMET cg-12；NIST TN 1341；SOLT 标准件定义口径）：
- cal_kit_standard_response/cal_kit_verify_ripple：校准件响应与
  verification 惯例=EURAMET cg-12/NIST TN 1341 文献族
  （vna_uncertainty 同源文献族，二级转引）；机械校准件 offset 一阶
  模型=SOLT 标准件定义口径（Keysight 85052D 语境二级转引——定义惯例
  出处而非厂商数值）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "cal_kit_standard_response",
    "cal_kit_verify_ripple",
]

_C_LIGHT_M_S = 299792458.0
# dB→Np（功率衰减口径）：A_dB = 20·log10(e)·α_np = 8.6859·α_np
_NP_PER_DB = 1.0 / (20.0 * math.log10(math.e))

_STANDARDS = ("open", "short", "load", "through")

_SOURCE = (
    "EURAMET cg-12/NIST TN 1341 校准件与 verification 惯例（二级转引，"
    "vna_uncertainty 同源文献族）；机械件 offset 一阶模型=SOLT 标准件"
    "定义口径通用化（非厂商 spec 复刻，#300 归属纪律）；纹波法=残余"
    "方向性↔回损纹波教科书关系（二级转引）")


def _line_factor(freq_ghz: float, offset_length_mm: float,
                 offset_loss_db_m_1ghz: float, epsilon_r_offset: float,
                 trips: float) -> complex:
    """传输因子 e^{−trips·(α+jβ)l}（l 单位 mm；α 按 √f 标度）。

    trips=2：反射路径往返（short/open/load 参考面因子）；
    trips=1：through 单程透射。传播数学生源唯一（防复制漂移）。
    """
    l_m = offset_length_mm * 1e-3
    f_hz = freq_ghz * 1e9
    beta = 2.0 * math.pi * f_hz * math.sqrt(epsilon_r_offset) / _C_LIGHT_M_S
    a_db = offset_loss_db_m_1ghz * math.sqrt(max(freq_ghz, 0.0)) * l_m
    alpha_np = a_db * _NP_PER_DB
    mag = math.exp(-trips * alpha_np)
    ph = -trips * beta * l_m
    return complex(mag * math.cos(ph), mag * math.sin(ph))


def _wrap180(x_deg: float) -> float:
    """角度差回卷到 (−180,180]（理想/实测相位差语义）。"""
    w = math.fmod(x_deg, 360.0)
    if w <= -180.0:
        w += 360.0
    elif w > 180.0:
        w -= 360.0
    return w


# ─── 键 1：cal_kit_standard_response（标准件响应偏离+判据）──────────────────

@register_calculator(
    "cal_kit_standard_response",
    "校准件响应偏离：机械 SOLT 校准件一阶模型 vs 理想响应闭式+工程"
    "验收判据（R2 D5 立项——trl_solt/measurement=使用链、trl_standards="
    "TRL 设计端、vna_uncertainty=误差箱传播，本族=验证端，零撞）。"
    "offset 线往返因子 e^{−2(α+jβ)l}（α 按 √f 趋肤标度、TEM β）："
    "short Γ=−e^{−2(α+jβ)l}（理想 180°/|Γ|=1）；open 加边缘电容 "
    "Γ_cap=(1−jωC_fZ0)/(1+jωC_fZ0)（理想 0°；C_f>0 相位随 f 负旋）；"
    "load Γ₀=(ratio−1)/(ratio+1) 失配地板 RL=−20lg|Γ₀|（理想 RL=∞ 走 "
    "None）；through S21=e^{−(α+jβ)l}+IL/时延。判据面（工程档缺省，"
    "非厂商 spec）：short/open |Γ|≥0.97、load RL≥35dB、through IL≤"
    "0.2dB，pass=适用判据合取。锚：理想件→理想响应逐位、offset 相位"
    "旋转/损耗压低独立重算、C_f 相位负旋、判据边界",
    (("standard_type", "str 'open'|'short'|'load'|'through' 白名单"),
     ("freq_ghz", "list[float] 频率栅格 GHz（≥1 点，全>0）"),
     ("offset_length_mm", "float mm offset 段长度（≥0，缺省 0=理想"
      "参考面）"),
     ("offset_loss_db_m_1ghz", "float dB/m@1GHz offset 段损耗 L₁（≥0，"
      "按 √f_GHz 标度；介质损耗主导件须调用方换算等效值——预声明）"),
     ("epsilon_r_offset", "float offset 段有效介电常数（≥1，缺省 1="
      "空气线档）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）"),
     ("open_cap_ff", "float fF open 边缘电容（≥0，缺省 0=理想开路；"
      "仅 open 键合法，非 open 给非零显式拒绝）"),
     ("load_z_ratio", "float load 阻抗比 Z_L/Z0（>0，缺省 1=理想匹配；"
      "仅 load 键合法，非 load 给非 1 显式拒绝）"),
     ("gamma_mag_min", "float short/open 验收 |Γ| 下界（∈[0.9,1]，"
      "缺省 0.97）"),
     ("load_rl_min_db", "float load 验收回损下界 dB（∈[20,60]，缺省 35）"),
     ("through_il_max_db", "float through 验收插损上界 dB（>0，"
      "缺省 0.2）")),
    required=("standard_type", "freq_ghz"),
)
def cal_kit_standard_response(standard_type: str, freq_ghz: list,
                              offset_length_mm: float = 0.0,
                              offset_loss_db_m_1ghz: float = 0.0,
                              epsilon_r_offset: float = 1.0,
                              z0_ohm: float = 50.0,
                              open_cap_ff: float = 0.0,
                              load_z_ratio: float = 1.0,
                              gamma_mag_min: float = 0.97,
                              load_rl_min_db: float = 35.0,
                              through_il_max_db: float = 0.2
                              ) -> dict[str, Any]:
    key = "cal_kit_standard_response"
    if standard_type not in _STANDARDS:
        raise ValueError(
            f"{key}: standard_type 须 {list(_STANDARDS)}，得到 "
            f"{standard_type!r}")
    if not freq_ghz or not isinstance(freq_ghz, list):
        raise ValueError(
            f"{key}: freq_ghz 须为非空 list，得到 {type(freq_ghz)!r}")
    freqs = [_finite(v, f"{key}.freq_ghz[{i}]")
             for i, v in enumerate(freq_ghz)]
    for i, f in enumerate(freqs):
        if f <= 0.0:
            raise ValueError(
                f"{key}: freq_ghz[{i}] 必须 >0，得到 {f!r}")
    loff = _finite(offset_length_mm, f"{key}.offset_length_mm")
    if loff < 0.0:
        raise ValueError(
            f"{key}: offset_length_mm 必须 ≥0，得到 {loff!r}")
    l1 = _finite(offset_loss_db_m_1ghz, f"{key}.offset_loss_db_m_1ghz")
    if l1 < 0.0:
        raise ValueError(
            f"{key}: offset_loss_db_m_1ghz 必须 ≥0，得到 {l1!r}")
    eps = _finite(epsilon_r_offset, f"{key}.epsilon_r_offset")
    if eps < 1.0:
        raise ValueError(
            f"{key}: epsilon_r_offset 必须 ≥1，得到 {eps!r}")
    z0 = _finite(z0_ohm, f"{key}.z0_ohm")
    if z0 <= 0.0:
        raise ValueError(f"{key}: z0_ohm 必须 >0，得到 {z0!r}")
    c_ff = _finite(open_cap_ff, f"{key}.open_cap_ff")
    if c_ff < 0.0:
        raise ValueError(
            f"{key}: open_cap_ff 必须 ≥0，得到 {c_ff!r}")
    if c_ff != 0.0 and standard_type != "open":
        raise ValueError(
            f"{key}: open_cap_ff 仅 open 键合法（非 open 给非零=静默"
            f"忽略风险，显式拒绝），standard_type={standard_type!r}")
    ratio = _finite(load_z_ratio, f"{key}.load_z_ratio")
    if ratio <= 0.0:
        raise ValueError(
            f"{key}: load_z_ratio 必须 >0，得到 {ratio!r}")
    if ratio != 1.0 and standard_type != "load":
        raise ValueError(
            f"{key}: load_z_ratio 仅 load 键合法（非 load 给非 1 显式"
            f"拒绝），standard_type={standard_type!r}")
    g_min = _finite(gamma_mag_min, f"{key}.gamma_mag_min")
    if not 0.9 <= g_min <= 1.0:
        raise ValueError(
            f"{key}: gamma_mag_min 须 ∈[0.9,1]，得到 {g_min!r}")
    rl_min = _finite(load_rl_min_db, f"{key}.load_rl_min_db")
    if not 20.0 <= rl_min <= 60.0:
        raise ValueError(
            f"{key}: load_rl_min_db 须 ∈[20,60]，得到 {rl_min!r}")
    il_max = _finite(through_il_max_db, f"{key}.through_il_max_db")
    if il_max <= 0.0:
        raise ValueError(
            f"{key}: through_il_max_db 必须 >0，得到 {il_max!r}")

    mags: list[float] = []
    phases: list[float] = []
    re_list: list[float] = []
    im_list: list[float] = []
    il_list: list[float] | None = None
    if standard_type == "through":
        il_list = []
    for f in freqs:
        if standard_type == "through":
            z_resp = _line_factor(f, loff, l1, eps, trips=1.0)
            il_list.append(round(20.0 * math.log10(max(abs(z_resp), 1e-300)),
                                 15))
        else:
            circ = _line_factor(f, loff, l1, eps, trips=2.0)
            if standard_type == "short":
                z_resp = -circ
            elif standard_type == "open":
                omega = 2.0 * math.pi * f * 1e9
                c_f = c_ff * 1e-15
                if c_f > 0.0:
                    z_cap = 1.0 / (1j * omega * c_f)
                    g_cap = (z_cap - z0) / (z_cap + z0)
                else:
                    g_cap = 1.0 + 0.0j
                z_resp = g_cap * circ
            else:  # load
                g0 = (ratio - 1.0) / (ratio + 1.0)
                z_resp = g0 * circ
        mags.append(round(abs(z_resp), 18))
        phases.append(round(math.degrees(math.atan2(z_resp.imag, z_resp.real)),
                            15))
        re_list.append(round(z_resp.real, 18))
        im_list.append(round(z_resp.imag, 18))

    # 理想响应与偏离（mag/phase 口径；相位差回卷 (−180,180]）
    if standard_type == "short":
        ideal_mag, ideal_phase = 1.0, 180.0
        phase_dev = [round(_wrap180(180.0 - p), 15) for p in phases]
    elif standard_type == "open":
        ideal_mag, ideal_phase = 1.0, 0.0
        phase_dev = [round(p, 15) for p in phases]  # atan2 相位已在窗内
    elif standard_type == "load":
        ideal_mag, ideal_phase = 0.0, 0.0
        phase_dev = None  # Γ₀≈0 相位无意义（理想 load 相位失定，如实）
    else:
        ideal_mag, ideal_phase = 1.0, 0.0
        phase_dev = [round(p, 15) for p in phases]
    mag_dev = [round(abs(m - ideal_mag), 18) for m in mags]
    worst_mag_dev = max(mag_dev)
    worst_phase_dev = (None if phase_dev is None
                       else max(abs(d) for d in phase_dev))

    # 判据面（pass=适用判据合取）
    checks: dict[str, Any] = {}
    if standard_type in ("short", "open"):
        checks["gamma_mag_min"] = {
            "limit": g_min, "worst": round(min(mags), 18),
            "pass": min(mags) >= g_min}
    elif standard_type == "load":
        g_worst = max(mags)  # 有 offset 损耗时 |Γ| 随频压低→最劣=最大
        rl_worst_db = (None if g_worst <= 0.0
                       else round(-20.0 * math.log10(g_worst), 15))
        checks["load_rl_min_db"] = {
            "limit_db": rl_min,
            "measured_rl_min_db": rl_worst_db,
            # 理想 load（|Γ|=0 → RL=∞ 走 None JSON 契约）判据平凡通过
            "pass": rl_worst_db is None or rl_worst_db >= rl_min}
    else:
        checks["through_il_max_db"] = {
            "limit": il_max, "worst": round(max(il_list), 15),
            "pass": max(il_list) <= il_max}
    overall_pass = all(v["pass"] for v in checks.values())

    delay_ns = (None if standard_type == "load" else
                round(loff * 1e-3 * math.sqrt(eps) / _C_LIGHT_M_S * 1e9,
                      18))
    return {
        "standard_type": standard_type,
        "freq_ghz": freqs,
        "offset_length_mm": loff,
        "offset_loss_db_m_1ghz": l1,
        "epsilon_r_offset": eps,
        "z0_ohm": z0,
        "open_cap_ff": (c_ff if standard_type == "open" else None),
        "load_z_ratio": (ratio if standard_type == "load" else None),
        "response_re": re_list,
        "response_im": im_list,
        "response_mag": mags,
        "response_phase_deg": phases,
        "insertion_loss_db": il_list,
        "group_delay_ns": delay_ns,
        "ideal_mag": ideal_mag,
        "ideal_phase_deg": ideal_phase,
        "mag_deviation": mag_dev,
        "phase_deviation_deg": phase_dev,
        "worst_mag_deviation": round(worst_mag_dev, 18),
        "worst_phase_deviation_deg": (None if worst_phase_dev is None
                                      else round(worst_phase_dev, 15)),
        "acceptance": {"checks": checks, "pass": overall_pass,
                       "defaults_note": (
                           "缺省判据=计量级工程带（short/open |Γ|≥0.97、"
                           "load RL≥35dB、through IL≤0.2dB），非特定厂商"
                           "spec——厂商规格须调用方显式覆写（#300 归属"
                           "纪律）")},
        "note": (
            "一阶模型边界：offset 线 Z0 失配/连接器重复性/开路频率相关"
            "电容高阶项（C0,C1,C2 多参数拟合面）不在本域；through 反射"
            "档（S11）不在此键（失配纹波走 vna_uncertainty 误差箱）；"
            "load 判据取最劣频点（有 offset 损耗时 |Γ| 随频压低）"),
        "source": _SOURCE,
    }


# ─── 键 2：cal_kit_verify_ripple（纹波法 verification）──────────────────────

@register_calculator(
    "cal_kit_verify_ripple",
    "校准件纹波验证：校准后 verification 纹波法（残余方向性 d↔精确负载"
    "回损纹波解析关系，正反双解+验收判据；R2 D5'验'半边）。正向：给"
    "残余方向性 D_db（20lg 口径 <0）→|Γ_meas|∈[|g−d|,g+d]、回损窗与"
    "峰峰纹波 pp=20lg((g+d)/(g−d))；反向：给实测纹波 pp→d=g(10^(pp/20)"
    "−1)/(10^(pp/20)+1)。完美负载 g=0→窗塌缩单点、pp=0、回损地板="
    "−D_db（与 directional_bridge_response/vna_reflection_uncertainty "
    "地板恒等式同值三方互证）；d≥g（g>0）=包围原点相位回绕域如实"
    "旗标+回损判据按不通过记（深谷失真不外推假窗；d=g 恰过零 pp 走 "
    "None）。锚：地板恒等三方同值、注入残差→纹波解析回收（#118）、"
    "正反往返逐位、窗对称恒等",
    (("load_gamma_mag", "float 精确负载 |Γ_L|（∈[0,1]；0=完美负载地板"
      "档）"),
     ("residual_directivity_db", "float dB 校准后残余方向性（20lg 口径 "
      "<0；与 measured_ripple_pp_db 恰给其一——正向解档）"),
     ("measured_ripple_pp_db", "float dB 实测回损纹波峰峰（>0；与 "
      "residual_directivity_db 恰给其一——反向解档）"),
     ("residual_directivity_max_db", "float dB 验收上界口径（>0，缺省 "
      "35：要求 |Ed|≤10^(−35/20)）"),
     ("load_rl_min_db", "float dB 负载回损验收下界（∈[20,60]，缺省 30）")),
    required=("load_gamma_mag",),
)
def cal_kit_verify_ripple(load_gamma_mag: float,
                          residual_directivity_db: float | None = None,
                          measured_ripple_pp_db: float | None = None,
                          residual_directivity_max_db: float = 35.0,
                          load_rl_min_db: float = 30.0) -> dict[str, Any]:
    key = "cal_kit_verify_ripple"
    g = _finite(load_gamma_mag, f"{key}.load_gamma_mag")
    if not 0.0 <= g <= 1.0:
        raise ValueError(
            f"{key}: load_gamma_mag 须 ∈[0,1]，得到 {g!r}")
    if (residual_directivity_db is None) == (measured_ripple_pp_db is None):
        raise ValueError(
            f"{key}: residual_directivity_db 与 measured_ripple_pp_db "
            "恰给其一（正向/反向档），得到 "
            f"directivity={residual_directivity_db!r}, pp="
            f"{measured_ripple_pp_db!r}")
    d_max = _finite(residual_directivity_max_db,
                    f"{key}.residual_directivity_max_db")
    if d_max <= 0.0:
        raise ValueError(
            f"{key}: residual_directivity_max_db 必须 >0，得到 {d_max!r}")
    rl_floor_min = _finite(load_rl_min_db, f"{key}.load_rl_min_db")
    if not 20.0 <= rl_floor_min <= 60.0:
        raise ValueError(
            f"{key}: load_rl_min_db 须 ∈[20,60]，得到 {rl_floor_min!r}")

    if residual_directivity_db is not None:
        d_db = _finite(residual_directivity_db,
                       f"{key}.residual_directivity_db")
        if d_db >= 0.0:
            raise ValueError(
                f"{key}: residual_directivity_db 必须 <0（20lg 残差口径），"
                f"得到 {d_db!r}")
        mode = "forward"
    else:
        pp_in = _finite(measured_ripple_pp_db, f"{key}.measured_ripple_pp_db")
        if pp_in <= 0.0:
            raise ValueError(
                f"{key}: measured_ripple_pp_db 必须 >0（完美负载 pp=0 "
                f"地板档请走 directivity 输入档），得到 {pp_in!r}")
        if g <= 0.0:
            raise ValueError(
                f"{key}: 反向档（实测纹波）要求 load_gamma_mag>0（完美"
                f"负载 pp 恒 0 不可反解），得到 {g!r}")
        ratio = 10.0 ** (pp_in / 20.0)
        d_lin = g * (ratio - 1.0) / (ratio + 1.0)
        d_db = 20.0 * math.log10(d_lin) if d_lin > 0.0 else float("-inf")
        mode = "inverse"
    d = 10.0 ** (d_db / 20.0)

    # 回损窗（矢量相位未知 → 线性域双界）
    lo_lin = abs(g - d)
    hi_lin = g + d
    rl_max_db = (None if hi_lin <= 0.0
                 else round(-20.0 * math.log10(hi_lin), 15))
    rl_min_db = (None if lo_lin <= 0.0
                 else round(-20.0 * math.log10(lo_lin), 15))
    # 包围域旗标：d≥g（g>0）时 |Γ_meas| 圆环包围原点、相位回绕——
    # 纹波窗仍可计算（lo=d−g>0），但"回损=负载质量"判读失义；
    # d=g 恰过零（lo=0）时 dB 域峰峰无定义走 None（JSON 禁 ∞）
    enclosing = g > 0.0 and d >= g
    pp_db = (None if (lo_lin <= 0.0 or hi_lin <= 0.0)
             else round(20.0 * math.log10(hi_lin / lo_lin), 15))
    # 完美负载地板：|Γ_meas| 塌缩到 |Ed| 单点
    floor_db = (None if d <= 0.0 else round(-20.0 * math.log10(d), 15))
    checks = {
        "residual_directivity_max": {
            "limit_db": d_max, "measured_db": (None if d_db == float("-inf")
                                               else round(d_db, 15)),
            "pass": d <= 10.0 ** (-d_max / 20.0)},
        "load_rl_min": {
            "limit_db": rl_floor_min,
            "measured_rl_min_db": rl_min_db,
            # 包围域=深谷失真：回损"负载质量"判据不适用按不通过如实记
            #（不外推假窗；g=0 地板档不属包围域，地板恒等式正常判）
            "pass": (not enclosing) and rl_min_db is not None
            and rl_min_db >= rl_floor_min},
    }
    return {
        "load_gamma_mag": g,
        "mode": mode,
        "residual_directivity_db": (None if d_db == float("-inf")
                                    else round(d_db, 15)),
        "directivity_linear": round(d, 18),
        "gamma_meas_mag_min": round(lo_lin, 18),
        "gamma_meas_mag_max": round(hi_lin, 18),
        "rl_meas_min_db": rl_min_db,
        "rl_meas_max_db": rl_max_db,
        "ripple_pp_db": pp_db,
        "perfect_load_floor_db": floor_db,
        "directivity_ge_load_gamma": enclosing,
        "acceptance": {"checks": checks,
                       "pass": all(v["pass"] for v in checks.values())},
        "note": (
            "单端口一阶纹波模型（方向性项主导）：Γ_meas 矢量相位未知→"
            "线性域双界 [ |g−d|, g+d ]；g=0 地板档窗塌缩到 |Ed| 单点、"
            "pp=0、回损地板=−D_db（与 directional_bridge_response.rl_"
            "floor_db / vna_reflection_uncertainty 回损地板同值三方"
            "互证）；d≥g（g>0）=|Γ_meas| 圆环包围原点、相位回绕域——"
            "纹波窗仍给但回损'负载质量'判读失义，directivity_ge_load_"
            "gamma 旗标+回损判据按不通过如实记（不外推假窗，与 "
            "vna_uncertainty 下界触 0 同口径）；d=g 恰过零时 dB 域峰峰"
            "无定义走 None；源匹配/负载匹配残差高阶纹波面归 "
            "vna_uncertainty 误差箱合成（边界互指）"),
        "source": _SOURCE,
    }
