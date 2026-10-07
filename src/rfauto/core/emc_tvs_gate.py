"""ME-3 EMC v3：ESD/浪涌免疫门（IEC 61000-4-2/4-5 波形参数表 + TVS 选型闭式）。

规格：月度增强方案 §三 A 流 ME-3。IEC 61000-4-2:2008 与
61000-4-5:2014 标准正文收费——按项目既定 provenance 纪律走**次级源双源交叉核对固化**
（检索 2026-09-27，出处与检索面见 IEC61000_4_2_PROVENANCE / IEC61000_4_5_PROVENANCE），
值面钉在本模块常量表；`rfauto emc gate` 挂 fab DFM 门旁（service/CLI 接线属后续批，
本件只出 core 纯函数层）。

**警示常量（任务书 ME-3 明文，防再犯）**：PyPI 包 ``emc2`` 是大气科学（NASA 大气
辐射/许可大气物理工具链）同名假朋友——EMC 领域**勿引用、勿进 pyproject**，见
``PYPI_EMC2_FAKE_FRIEND``。

波形参数口径（逐值双源核对，检索 2026-09-27）：

1. **IEC 61000-4-2 静电放电**：
   - 严酷度等级（Table 1）：接触放电 2/4/6/8 kV（Level 1–4）；空气放电 2/4/8/15 kV。
   - 电流波形参数（Table 2/3，接触放电，150 pF/330 Ω 发生器校准口径）——**归一化
     每 kV 充电电压**：首峰 I_peak = 3.75 A/kV（±10%，t_r=0.6–1 ns）、
     I(30 ns) = 2 A/kV（±30%）、I(60 ns) = 1 A/kV（±30%）。Level 4（8 kV contact）
     锚点：30 A 首峰 / 16 A@30 ns / 8 A@60 ns——任务书速记 "8/30 ns" 即 8 kV↔30 A
     峰值面、"1/60 ns" 即 1 ns 级上升沿 + 60 ns 电流点尾面（双波口径登记）。
   - 任务书双波速记的表常量化：esd_waveform_currents 按每 kV 线性归一产出三电流点
     （4 kV → 15/8/4 A 逐位），空气放电无独立波形表（4-2 波形规范仅对接触放电定义，
     如实登记）。
2. **IEC 61000-4-5 浪涌（组合波）**：开路电压 1.2/50 µs + 短路电流 8/20 µs，
   等效源阻抗 ≈2 Ω（虚拟阻抗=V_oc 峰/I_sc 峰）；首选试验等级 0.5/1/2/4 kV
   （对应短路电流 0.25/0.5/1/2 kA）。耦合网络附加阻抗口径（功率线线-线 2 Ω/
   线-地 12 Ω、信号线 42 Ω）随常量表登记，gate 入参显式传 Z。
3. **TVS 选型闭式**：钳位电压 VC = VBR + IPP·Rdyn（线性动态电阻近似——数据手册
   VC@IPP 点的直线化口径，Rdyn 可由 (VC−VBR)/IPP 反演）；峰值脉冲功率
   PPPM = VC·IPP；选型判定链 = 工作电压 ≤ VWM < VBR_min < 钳位（VC+余量 ≤ 被保护
   端口耐压）逐链 verdict，链序恒等式测试钉。
4. **浪涌通过判定**：浪涌开路电压 V_surge 经源阻抗 Z 打到 TVS——线性化电路精确解
   I_TVS = (V_surge − VBR)/(Z + Rdyn)（V_surge ≤ VBR 时不导通、端口吃满 V_surge），
   VC = VBR + I·Rdyn 判 vs 耐压；保守上界口径 I = V/Z 并出登记（忽略 VBR/钳位反馈）。

零 IO、纯函数；数值 0.0 合法（判缺失一律 ``is not None``，#364④）；bool 显式拒收
（df7+⑯）；IPP ≤ 0、负电压/负阻抗 → ValueError（任务书边界）。不进
@register_calculator（#231 同 ME-1/ME-2 约定）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "ESD_GENERATOR_C_PF",
    "ESD_GENERATOR_R_OHM",
    "IEC61000_4_2_LEVELS",
    "IEC61000_4_2_PROVENANCE",
    "IEC61000_4_2_WAVEFORM_PER_KV",
    "IEC61000_4_5_CWG",
    "IEC61000_4_5_PROVENANCE",
    "PYPI_EMC2_FAKE_FRIEND",
    "TvsGateResult",
    "esd_generator_energy",
    "esd_levels",
    "esd_waveform_currents",
    "surge_gate",
    "surge_levels",
    "surge_short_circuit_current",
    "tvs_clamp_voltage",
    "tvs_peak_pulse_power",
    "tvs_rdyn_ohm",
    "tvs_select",
]

# ── 警示常量（任务书 ME-3 明文登记）──────────────────────────────────────────

PYPI_EMC2_FAKE_FRIEND = (
    "PyPI 包 `emc2` 是大气科学（NASA 大气辐射传输/许可大气物理工具链）同名假朋友——"
    "EMC 领域勿引用、勿进 pyproject 依赖（monthly_plan ME-3 警示原文登记，防再犯）。"
)

# ── IEC 61000-4-2（ESD）常量表 ────────────────────────────────────────────────

#: ESD 发生器储能电容（pF）与放电电阻（Ω）——IEC 61000-4-2 标准发生器 150 pF/330 Ω。
ESD_GENERATOR_C_PF = 150.0
ESD_GENERATOR_R_OHM = 330.0

#: 严酷度等级（kV）：接触放电 Level 1–4 与空气放电 Level 1–4（Table 1）。
IEC61000_4_2_LEVELS: dict[str, tuple[float, ...]] = {
    "contact_kv": (2.0, 4.0, 6.0, 8.0),
    "air_kv": (2.0, 4.0, 8.0, 15.0),
}

#: 电流波形归一化参数（每 kV 充电电压；Table 2/3，接触放电，含容差）。
IEC61000_4_2_WAVEFORM_PER_KV: dict[str, object] = {
    "i_peak_a_per_kv": 3.75,
    "i_peak_tolerance": 0.10,
    "i_30ns_a_per_kv": 2.0,
    "i_60ns_a_per_kv": 1.0,
    "i_tail_tolerance": 0.30,
    "rise_time_ns": (0.6, 1.0),
    "waveform_scope": "仅对接触放电定义（空气放电无独立电流波形表，如实登记）",
}

IEC61000_4_2_PROVENANCE: dict[str, object] = {
    "primary": "IEC 61000-4-2:2008（标准正文收费，不抄收费表——项目 provenance 纪律）",
    "secondary": [
        "ESD 测试指南（scribd.com IEC 61000-4-2 ESD Testing Guide）：等级表接触 "
        "2/4/6/8 kV、空气 2/4/8/15 kV（检索 2026-09-27，web_search 摘录）",
        "3C-Test EDS 30T ESD 发生器校准规格（3c-test.com）：150 pF/330 Ω 网络、"
        "上升沿 0.8 ns±25%、2 kV 首峰 7.5 A±15%（=3.75 A/kV 归一）（检索 2026-09-27）",
        "TVS/ESD 保护厂商应用笔记族（Littelfuse/TI 口径）：I_peak=3.75 A/kV、"
        "I(30ns)=2 A/kV、I(60ns)=1 A/kV 线性归一（业界通用复现面，检索 2026-09-27）",
    ],
    "retrieved": "2026-09-27",
    "level4_anchor": "8 kV contact → 30 A 首峰 / 16 A@30ns / 8 A@60ns（3.75/2/1 A/kV）",
}


def esd_levels() -> dict[str, object]:
    """IEC 61000-4-2 严酷度等级表 + provenance（拷贝面，防外部改表）。"""
    return {
        "standard": "IEC 61000-4-2:2008",
        "levels": {k: tuple(v) for k, v in IEC61000_4_2_LEVELS.items()},
        "generator": {"c_pf": ESD_GENERATOR_C_PF, "r_ohm": ESD_GENERATOR_R_OHM},
        "waveform_per_kv": dict(IEC61000_4_2_WAVEFORM_PER_KV),
        "provenance": dict(IEC61000_4_2_PROVENANCE),
    }


# ── IEC 61000-4-5（浪涌组合波）常量表 ────────────────────────────────────────

#: 组合波发生器（CWG）参数：开路 1.2/50 µs、短路 8/20 µs、等效源阻抗 2 Ω、
#: 首选试验等级（kV）与耦合网络附加阻抗口径（Ω）。
IEC61000_4_5_CWG: dict[str, object] = {
    "voc_front_us": 1.2,
    "voc_tail_us": 50.0,
    "isc_front_us": 8.0,
    "isc_tail_us": 20.0,
    "z_eff_ohm": 2.0,
    "levels_kv": (0.5, 1.0, 2.0, 4.0),
    "coupling_z_ohm": {
        "power_line_line": 2.0,
        "power_line_earth": 12.0,
        "signal_line": 42.0,
    },
}

IEC61000_4_5_PROVENANCE: dict[str, object] = {
    "primary": "IEC 61000-4-5:2014（标准正文收费，次级源双源交叉核对口径）",
    "secondary": [
        "Schlöder CWG 2500 组合波发生器规格（reliantemc.com）：1.2/50 µs 开路 + "
        "8/20 µs 短路（检索 2026-09-27，web_search 摘录）",
        "Electronic Design《Lightning Surge Immunity Testing》：CWG 开路口径 1.2 µs "
        "波前时间（检索 2026-09-27）；多厂商发生器规格（3C-Test CWS 20G、Ramayes "
        "PG 12-804、Richtec SGIEC-645）同 1.2/50 + 8/20 口径互证",
        "组合波虚拟阻抗 2 Ω（=V_oc 峰/I_sc 峰）与等级 0.5/1/2/4 kV → 0.25/0.5/1/2 kA "
        "短路电流（检索 2026-09-27 web_search 摘要确认）",
    ],
    "retrieved": "2026-09-27",
}


def surge_levels() -> dict[str, object]:
    """IEC 61000-4-5 组合波参数表 + provenance（拷贝面）。"""
    return {
        "standard": "IEC 61000-4-5:2014",
        "cwg": {k: (dict(v) if isinstance(v, dict) else v) for k, v in IEC61000_4_5_CWG.items()},
        "provenance": dict(IEC61000_4_5_PROVENANCE),
    }


# ── 入参守卫（ME-2 同款，bool 显式拒收）──────────────────────────────────────


def _finite(value: object, name: str) -> float:
    """有限实数守卫（拒 bool）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _nonneg(value: object, name: str) -> float:
    """非负有限实数守卫（0 合法——0 V 工作电压是合法语义）。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须为非负数（负值无物理意义），实际 {value!r}")
    return out


def _positive(value: object, name: str) -> float:
    """正有限实数守卫（阻抗/击穿电压/耐压等 >0 量）。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，实际 {value!r}")
    return out


# ── ESD/浪涌波形面 ────────────────────────────────────────────────────────────


def esd_waveform_currents(charge_kv: float) -> dict[str, object]:
    """ESD 接触放电电流波形三点（每 kV 线性归一，IEC 61000-4-2 Table 2/3 口径）。

    I_peak = 3.75·V A、I(30 ns) = 2·V A、I(60 ns) = 1·V A（V=充电电压 kV；
    ±10%/±30% 容差面见 IEC61000_4_2_WAVEFORM_PER_KV）。任务书双波速记的锚：
    8 kV → 30/16/8 A（Level 4，"8↔30 A" 峰值面）、上升沿 0.6–1 ns（"1/60 ns" 尾面）。

    Args:
        charge_kv: 充电电压 kV（>=0）。

    Returns:
        dict: {"charge_kv", "i_peak_a", "i_30ns_a", "i_60ns_a", "rise_time_ns",
        "tolerances", "waveform_scope"}。
    """
    v = _nonneg(charge_kv, "charge_kv")
    wf = IEC61000_4_2_WAVEFORM_PER_KV
    return {
        "charge_kv": v,
        "i_peak_a": v * float(wf["i_peak_a_per_kv"]),  # type: ignore[arg-type]
        "i_30ns_a": v * float(wf["i_30ns_a_per_kv"]),  # type: ignore[arg-type]
        "i_60ns_a": v * float(wf["i_60ns_a_per_kv"]),  # type: ignore[arg-type]
        "rise_time_ns": tuple(wf["rise_time_ns"]),  # type: ignore[arg-type]
        "tolerances": {
            "i_peak": wf["i_peak_tolerance"],
            "i_tail": wf["i_tail_tolerance"],
        },
        "waveform_scope": wf["waveform_scope"],
    }


def esd_generator_energy(charge_kv: float, c_pf: float = ESD_GENERATOR_C_PF) -> dict[str, object]:
    """ESD 发生器储能 E = ½·C·V²（标称发生器 150 pF，充电电压二次律）。

    Args:
        charge_kv: 充电电压 kV（>=0）。
        c_pf: 储能电容 pF（>0；缺省 150 pF 标准发生器）。

    Returns:
        dict: {"charge_kv", "c_pf", "energy_j"}。
    """
    v = _nonneg(charge_kv, "charge_kv")
    cap = _positive(c_pf, "c_pf")
    energy = 0.5 * (cap * 1e-12) * (v * 1e3) ** 2
    return {"charge_kv": v, "c_pf": cap, "energy_j": energy}


def surge_short_circuit_current(
    voc_kv: float, source_impedance_ohm: float = 2.0
) -> dict[str, object]:
    """组合波短路电流（峰值）I_sc = V_oc/Z（CWG 虚拟阻抗口径，缺省 2 Ω）。

    Args:
        voc_kv: 开路电压峰值 kV（>=0；首选等级 0.5/1/2/4 kV）。
        source_impedance_ohm: 等效源阻抗 Ω（>0；CWG 2 Ω；信号线耦合网络 42 Ω
            等见 IEC61000_4_5_CWG["coupling_z_ohm"]）。

    Returns:
        dict: {"voc_kv", "z_ohm", "i_sc_peak_a", "i_sc_peak_ka"}。
    """
    v = _nonneg(voc_kv, "voc_kv")
    z = _positive(source_impedance_ohm, "source_impedance_ohm")
    i_a = v * 1e3 / z
    return {
        "voc_kv": v,
        "z_ohm": z,
        "i_sc_peak_a": i_a,
        "i_sc_peak_ka": i_a / 1e3,
    }


# ── TVS 选型闭式 ──────────────────────────────────────────────────────────────


def tvs_clamp_voltage(vbr_v: float, ipp_a: float, rdyn_ohm: float) -> float:
    """TVS 钳位电压（线性动态电阻近似）VC = VBR + IPP·Rdyn（逐位闭式）。

    Args:
        vbr_v: 击穿电压 V（>0；数据手册 VBR 口径）。
        ipp_a: 峰值脉冲电流 A（>0；IPP ≤ 0 显式 ValueError——任务书边界）。
        rdyn_ohm: 动态电阻 Ω（>=0）。

    Returns:
        钳位电压 V（float；线性式逐位）。
    """
    vbr = _positive(vbr_v, "vbr_v")
    ipp = _positive(ipp_a, "ipp_a")
    rdyn = _nonneg(rdyn_ohm, "rdyn_ohm")
    return vbr + ipp * rdyn


def tvs_peak_pulse_power(ipp_a: float, vbr_v: float, rdyn_ohm: float) -> float:
    """峰值脉冲功率 PPPM = VC·IPP（VC 由 tvs_clamp_voltage 同式，恒等式测试钉）。"""
    ipp = _positive(ipp_a, "ipp_a")
    vc = tvs_clamp_voltage(vbr_v, ipp, rdyn_ohm)
    return vc * ipp


def tvs_rdyn_ohm(vbr_v: float, vc_v: float, ipp_a: float) -> float:
    """数据手册点反演动态电阻 Rdyn = (VC − VBR)/IPP。

    vc_v < vbr_v 时线性近似退化（负 Rdyn）→ 显式 ValueError（不静默出负阻）。
    """
    vbr = _positive(vbr_v, "vbr_v")
    vc = _positive(vc_v, "vc_v")
    ipp = _positive(ipp_a, "ipp_a")
    if vc < vbr:
        raise ValueError(f"vc_v 必须 >= vbr_v（线性 Rdyn 近似要求非负动态电阻），实际 {vc} < {vbr}")
    return (vc - vbr) / ipp


@dataclass(frozen=True)
class TvsGateResult:
    """TVS 选型/浪涌门判定结果（JSON 可序列化；first_failure 判缺失 is not None）。"""

    verdict: str  # "PASS" | "FAIL"
    links: tuple[dict[str, object], ...]  # 逐链 {"link", "pass", "margin_v"/"margin_a", ...}
    first_failure: str | None  # 首个未过的链名（全过为 None）
    vc_v: float | None  # 工作点钳位电压（VBR 以下不导通时 = 源电压）
    ipp_a: float | None  # 工作点 TVS 电流
    pppm_w: float | None  # VC·IPP（ipp 已知时）
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "verdict": self.verdict,
            "links": [dict(link) for link in self.links],
            "first_failure": self.first_failure,
            "vc_v": self.vc_v,
            "ipp_a": self.ipp_a,
            "pppm_w": self.pppm_w,
            "notes": list(self.notes),
        }


def _clamp_point(
    vbr_min_v: float,
    ipp_a: float,
    rdyn_ohm: float | None,
    vc_max_v: float | None,
) -> float:
    """工作点钳位电压：显式 vc_max_v 优先，否则线性式 VBR+IPP·Rdyn（判缺失 is not None）。"""
    if vc_max_v is not None:
        return _positive(vc_max_v, "vc_max_v")
    if rdyn_ohm is not None:
        return tvs_clamp_voltage(vbr_min_v, ipp_a, rdyn_ohm)
    raise ValueError("钳位面缺参：rdyn_ohm 与 vc_max_v 至少给其一（is not None 判缺失）")


def tvs_select(
    v_op_max_v: float,
    vwm_v: float,
    vbr_min_v: float,
    ipp_a: float,
    *,
    rdyn_ohm: float | None = None,
    vc_max_v: float | None = None,
    port_withstand_v: float = 0.0,
    clamp_margin_v: float = 0.0,
) -> TvsGateResult:
    """TVS 选型判定链：工作电压 ≤ VWM < VBR_min < 钳位（VC+余量 ≤ 端口耐压）。

    链序（逐链 verdict，全过→PASS；first_failure=首个未过链名）：
    1. ``vop_vs_vwm``：v_op_max ≤ vwm（正常工作不进击穿区）；
    2. ``vwm_vs_vbr``：vwm < vbr_min（严格 <，数据手册链序）；
    3. ``clamp_vs_withstand``：VC + clamp_margin ≤ port_withstand。钳位面 vc_max_v
       （数据手册 VC@IPP 上限，**is not None 判缺失**）优先，否则线性式 VBR+IPP·Rdyn。

    Args:
        v_op_max_v: 被保护端口最高工作电压 V（>=0）。
        vwm_v: TVS 工作峰值电压 VWM V（>0）。
        vbr_min_v: 击穿电压下限 VBR(min) V（>0）。
        ipp_a: 需求峰值脉冲电流 A（>0；浪涌需求电流或数据手册 IPP 点）。
        rdyn_ohm: 动态电阻 Ω（>=0，与 vc_max_v 至少给其一）。
        vc_max_v: 数据手册 VC@IPP 上限 V（>0，优先于线性式）。
        port_withstand_v: 被保护端口耐压 V（>0）。
        clamp_margin_v: 钳位余量 V（>=0，加在 VC 侧）。

    Returns:
        TvsGateResult（pppm_w 按 VC·IPP 随附；链序恒等式测试钉）。
    """
    v_op = _nonneg(v_op_max_v, "v_op_max_v")
    vwm = _positive(vwm_v, "vwm_v")
    vbr = _positive(vbr_min_v, "vbr_min_v")
    ipp = _positive(ipp_a, "ipp_a")
    withstand = _positive(port_withstand_v, "port_withstand_v")
    margin = _nonneg(clamp_margin_v, "clamp_margin_v")
    vc = _clamp_point(vbr, ipp, rdyn_ohm, vc_max_v)

    m1 = vwm - v_op
    m2 = vbr - vwm
    m3 = withstand - vc - margin
    links = (
        {"link": "vop_vs_vwm", "pass": m1 >= 0.0, "margin_v": m1},
        {"link": "vwm_vs_vbr", "pass": m2 > 0.0, "margin_v": m2},
        {"link": "clamp_vs_withstand", "pass": m3 >= 0.0, "margin_v": m3},
    )
    first_fail: str | None = None
    for link in links:
        if not link["pass"]:
            first_fail = str(link["link"])
            break
    notes = (
        "链序：工作电压 ≤ VWM < VBR_min < 钳位（VC+余量 ≤ 耐压）；"
        "钳位口径=" + ("数据手册 vc_max_v" if vc_max_v is not None else "线性式 VBR+IPP·Rdyn"),
        PYPI_EMC2_FAKE_FRIEND,
    )
    return TvsGateResult(
        verdict="FAIL" if first_fail is not None else "PASS",
        links=links,
        first_failure=first_fail,
        vc_v=vc,
        ipp_a=ipp,
        pppm_w=vc * ipp,
        notes=notes,
    )


def surge_gate(
    surge_kv: float,
    *,
    source_impedance_ohm: float,
    vwm_v: float,
    vbr_min_v: float,
    port_withstand_v: float,
    rdyn_ohm: float | None = None,
    vc_max_v: float | None = None,
    v_op_max_v: float = 0.0,
    clamp_margin_v: float = 0.0,
    ipp_rating_a: float | None = None,
) -> TvsGateResult:
    """浪涌通过判定：浪涌等级（kV）经源阻抗 Z → TVS 电流分流 → VC vs 端口耐压。

    线性化电路精确解（VBR+Rdyn 直线模型）：
    - V_surge ≤ VBR_min：TVS 不导通，I_TVS=0，端口吃满 V_surge（VC=V_surge）；
    - 否则 I_TVS = (V_surge − VBR)/(Z + Rdyn)、VC = VBR + I·Rdyn（并联分流闭式）。
    保守上界口径 I = V_surge/Z（忽略 VBR/钳位反馈）随结果并出登记。钳位面显式给
    vc_max_v（数据手册口径，is not None 判缺失）时，VC 判定用 vc_max_v、线性解只
    出电流。选型链复用 tvs_select 三链 + 可选 ``ipp_vs_rating`` 链（ipp_rating_a
    is not None 时启用：I_TVS ≤ 额定 IPP）。

    Args:
        surge_kv: 浪涌开路电压峰值 kV（>=0；IEC 61000-4-5 首选 0.5/1/2/4 kV）。
        source_impedance_ohm: 等效源阻抗 Ω（>0；CWG 2 Ω/信号线 42 Ω 等显式传）。
        其余同 tvs_select；ipp_rating_a：TVS 额定峰值脉冲电流 A（可选）。

    Returns:
        TvsGateResult（vc_v/ipp_a=线性解工作点；notes 登记保守上界与钳位口径）。
    """
    v_surge = _nonneg(surge_kv, "surge_kv") * 1e3
    z_src = _positive(source_impedance_ohm, "source_impedance_ohm")
    vbr = _positive(vbr_min_v, "vbr_min_v")
    rdyn = 0.0 if rdyn_ohm is None else _nonneg(rdyn_ohm, "rdyn_ohm")

    if v_surge <= vbr:
        i_tvs = 0.0
        vc_linear = v_surge
        mode = "below_breakdown"
    else:
        i_tvs = (v_surge - vbr) / (z_src + rdyn)
        vc_linear = vbr + i_tvs * rdyn
        mode = "clamping"
    i_conservative = v_surge / z_src

    if vc_max_v is not None:
        vc_judge = _positive(vc_max_v, "vc_max_v")
        clamp_label = "数据手册 vc_max_v"
    else:
        vc_judge = vc_linear
        clamp_label = "线性式 VBR+I·Rdyn"

    v_op = _nonneg(v_op_max_v, "v_op_max_v")
    vwm = _positive(vwm_v, "vwm_v")
    withstand = _positive(port_withstand_v, "port_withstand_v")
    margin = _nonneg(clamp_margin_v, "clamp_margin_v")
    m1 = vwm - v_op
    m2 = vbr - vwm
    m3 = withstand - vc_judge - margin
    links: list[dict[str, object]] = [
        {"link": "vop_vs_vwm", "pass": m1 >= 0.0, "margin_v": m1},
        {"link": "vwm_vs_vbr", "pass": m2 > 0.0, "margin_v": m2},
        {"link": "clamp_vs_withstand", "pass": m3 >= 0.0, "margin_v": m3},
    ]
    if ipp_rating_a is not None:
        rating = _positive(ipp_rating_a, "ipp_rating_a")
        links.append(
            {"link": "ipp_vs_rating", "pass": i_tvs <= rating, "margin_a": rating - i_tvs}
        )
    first_fail: str | None = None
    for link in links:
        if not link["pass"]:
            first_fail = str(link["link"])
            break
    notes = (
        f"工作模式={mode}；钳位判定口径={clamp_label}；"
        f"保守上界电流 I=V/Z={i_conservative:.6g} A（忽略 VBR/钳位反馈，仅登记不判读）",
        "线性化电路精确解 I=(V−VBR)/(Z+Rdyn)（VBR+Rdyn 直线模型；VC 反馈已含）",
        PYPI_EMC2_FAKE_FRIEND,
    )
    return TvsGateResult(
        verdict="FAIL" if first_fail is not None else "PASS",
        links=tuple(links),
        first_failure=first_fail,
        vc_v=vc_judge,
        ipp_a=i_tvs,
        pppm_w=vc_judge * i_tvs,
        notes=notes,
    )
