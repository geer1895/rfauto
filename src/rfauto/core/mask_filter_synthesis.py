"""mask→滤波器规格综合闭环（ge6 Wave1 / Ph5 池「开源空白旗舰件」）。

来源（先接地）：方案池 第十二轮 +
研究扩充 round6 中件包二——「FCC/ETSI/3GPP 免费
遮罩库→Chebyshev 阶数闭式→优化环」；开源空白（无生产级 Python 库做
遮罩→最小阶→耦合矩阵闭环），本仓现成资产 cm_core（C13 广义切比雪夫原型
→Cameron N+2 综合）直接复用，不重写综合内核。

物理口径（docstring 逐式给出处）：
- 低通→带通几何映射 Ω=(f/f0−f0/f)/fbw（cm_core coupling_matrix_response
  同式）；通带边缘=f0±channel_bw/2 处恰好 Ω=±1 由
  fbw=u(2+u)/(1+u)（u=channel_bw/(2·f0)）**精确反解**（对 (1+x)−1/(1+x)
  求逆；fbw≈channel_bw/f0 的一阶捷径带二阶偏差，不采用）。
- 切比雪夫阻带衰减闭式（Pozar §8.3 / Cameron ch.6 经典式）：
  A(Ω)=10·lg(1+cosh²(N·acoshΩ)/K)，K=10^(RL/10)−1（RL=带内回损分配，
  带内纹波 ripple=10·lg(1+1/K)）。最小阶
  N=ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs))；多段遮罩逐段取最大。
- 遮罩语义=**点态包络（psd 口径）**：段内限值 limit_dbc（负 dBc）→
  所需衰减 A=−limit_dbc（把全通道功率保守集中在考察频偏；FCC/IEEE 型
  psd 遮罩的本义，ACLR 型积分语义的点态预检化在模板 notes 显式标注）。
  全极点切比雪夫 |S21| 在阻带单调降 ⟹ 段的约束点=裁剪后内缘；报告
  另评段外缘/中点取最小裕量（不依赖单调性假设漏报）。
- **滤波器责任起点=通带边缘+guard_offset_ghz**（调制滚降信用区，设计
  输入非规范数值）：贴边段（内缘恰在通带边缘）在 Ω=1 处滤波器只能提供
  纹波电平衰减——要求超过纹波电平时 min_order/synthesize 显式 ValueError
  （不静默放宽），mask_margin_report 如实按负裕量 FAIL。
- 阶数闭环：闭式最小阶起步 → cm_core 出 (N+2) 耦合矩阵 → 矩阵频响
  逐段回验裕量 → 不足自动 +1（max_order_extra 上限），轨迹逐阶报告。

铁律 7：全部数值由确定性闭式/线性代数内核产出（本模块零随机、零 IO）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from .calc_families.cm_core import (
    _cm_response_raw,
    _cm_to_list,
    _cm_transversal_exact,
    _gcheb_prototype,
)

_FP_TOL = 1e-9  # 恰等容差（ge1③：浮点恰等不得翻 False/虚增 +1）
_S21_FLOOR = 1e-300  # |S21| 深阻带下溢地板（log10 参数）


# ─── 遮罩数据模型 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MaskSegment:
    """单个遮罩阶梯段：频偏区间 [offset_low, offset_high)（GHz）内限值
    limit_dbc（≤0，dBc=相对参考通道功率/参考 psd 的 dB 数）。

    offset_high=None 表示开放段（延续到无穷远；如 FCC §15.247 的 −50 dBc 段）。
    """

    offset_low_ghz: float
    offset_high_ghz: float | None
    limit_dbc: float

    def to_dict(self) -> dict[str, Any]:
        return {"offset_low_ghz": self.offset_low_ghz,
                "offset_high_ghz": self.offset_high_ghz,
                "limit_dbc": self.limit_dbc}


@dataclass(frozen=True)
class MaskSpec:
    """发射遮罩规格（免费遮罩库条目：内置模板=公开规范限值事实+设计示例参数）。

    Attributes:
        name: 遮罩名（snake_case）。
        source: 规范出处（标准号+条款/表号，必填；bands.py 纪律：无数值出处不上表）。
        f0_ghz: 载波/中心频率（GHz）。
        channel_bw_ghz: 参考通道带宽（GHz）=滤波器通带设计带宽。
        ref_power_dbm: 参考通道功率（dBc 基准；信息性，点态包络数学不消费）。
        segments: 单侧阻带阶梯（按 axis 语义；另一侧对称评估）。
        axis: 段频偏轴语义："channel_edge"（距通带边缘，FCC/ACLR 惯例）
            | "center"（距中心频率，IEEE 802.11 惯例）。
        rl_db: 回波损耗分配（dB，>0；通带纹波由它闭式导出）。
        guard_offset_ghz: 滤波器责任起点距通带边缘的信用区宽度（GHz，≥0）。
            该区内遮罩限值由发射波形/调制滚降承担；0=无信用（贴边段如实判）。
        mask_type: "sem_psd"（点态 psd 遮罩）| "aclr_envelope"（ACLR 积分
            语义的点态包络预检形态——报告注明口径差异）。
        notes: 语义注记（RBW/参考口径/积分语义警告等）。
    """

    name: str
    source: str
    f0_ghz: float
    channel_bw_ghz: float
    ref_power_dbm: float
    segments: tuple[MaskSegment, ...]
    axis: str = "channel_edge"
    rl_db: float = 20.0
    guard_offset_ghz: float = 0.0
    mask_type: str = "sem_psd"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source,
                "f0_ghz": self.f0_ghz, "channel_bw_ghz": self.channel_bw_ghz,
                "ref_power_dbm": self.ref_power_dbm,
                "segments": [s.to_dict() for s in self.segments],
                "axis": self.axis, "rl_db": self.rl_db,
                "guard_offset_ghz": self.guard_offset_ghz,
                "mask_type": self.mask_type, "notes": self.notes}

    @classmethod
    def from_dict(cls, data: Any) -> MaskSpec:
        """JSON dict → MaskSpec（显式校验；未知键/非法值显式报错，不静默收窄）。"""
        if not isinstance(data, dict):
            raise ValueError("mask 须为 JSON dict（MaskSpec.to_dict() 形态）")
        known = {"name", "source", "f0_ghz", "channel_bw_ghz", "ref_power_dbm",
                 "segments", "axis", "rl_db", "guard_offset_ghz", "mask_type",
                 "notes"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"mask 含未知键: {unknown}（合法键: {sorted(known)}）")
        missing = [k for k in ("name", "source", "f0_ghz", "channel_bw_ghz",
                               "ref_power_dbm", "segments") if k not in data]
        if missing:
            raise ValueError(f"mask 缺必填键: {missing}")
        f0 = _num(data["f0_ghz"], "f0_ghz")
        ch = _num(data["channel_bw_ghz"], "channel_bw_ghz")
        ref = _num(data["ref_power_dbm"], "ref_power_dbm")
        rl = _num(data.get("rl_db", 20.0), "rl_db")
        guard = _num(data.get("guard_offset_ghz", 0.0), "guard_offset_ghz")
        axis = data.get("axis", "channel_edge")
        if axis not in ("channel_edge", "center"):
            raise ValueError("axis 须为 channel_edge|center")
        mask_type = data.get("mask_type", "sem_psd")
        if mask_type not in ("sem_psd", "aclr_envelope"):
            raise ValueError("mask_type 须为 sem_psd|aclr_envelope")
        if f0 <= 0:
            raise ValueError("f0_ghz 必须 >0")
        if not 0 < ch < 2.0 * f0:
            raise ValueError("channel_bw_ghz 须在 (0, 2·f0_ghz)")
        if rl <= 0:
            raise ValueError("rl_db 必须 >0（回波损耗分配）")
        if guard < 0:
            raise ValueError("guard_offset_ghz 必须 ≥0（信用区宽度）")
        raw_segs = data["segments"]
        if not isinstance(raw_segs, (list, tuple)) or not raw_segs:
            raise ValueError("segments 须为非空列表（至少一个遮罩段）")
        segs: list[MaskSegment] = []
        for i, raw in enumerate(raw_segs):
            if not isinstance(raw, dict):
                raise ValueError(f"segments[{i}] 须为 dict")
            unk = set(raw) - {"offset_low_ghz", "offset_high_ghz", "limit_dbc"}
            if unk:
                raise ValueError(f"segments[{i}] 含未知键: {sorted(unk)}")
            for k in ("offset_low_ghz", "limit_dbc"):
                if k not in raw:
                    raise ValueError(f"segments[{i}] 缺 {k}")
            lo = _num(raw["offset_low_ghz"], f"segments[{i}].offset_low_ghz")
            hi_raw = raw.get("offset_high_ghz")
            hi = None if hi_raw is None else _num(hi_raw, f"segments[{i}].offset_high_ghz")
            lim = _num(raw["limit_dbc"], f"segments[{i}].limit_dbc")
            if lo < 0:
                raise ValueError(f"segments[{i}].offset_low_ghz 必须 ≥0（单侧轴）")
            if hi is not None and hi <= lo:
                raise ValueError(f"segments[{i}].offset_high_ghz 须 > offset_low_ghz")
            if lim > 0:
                raise ValueError(f"segments[{i}].limit_dbc 必须 ≤0（dBc 限值）")
            segs.append(MaskSegment(offset_low_ghz=lo, offset_high_ghz=hi,
                                    limit_dbc=lim))
        segs.sort(key=lambda s: s.offset_low_ghz)
        # pairwise 相邻对（单段=空序列，天然无重叠可查）
        for a, b in pairwise(segs):
            a_hi = math.inf if a.offset_high_ghz is None else a.offset_high_ghz
            if b.offset_low_ghz < a_hi - _FP_TOL:
                raise ValueError(
                    f"遮罩段频偏区间重叠: [{a.offset_low_ghz}, {a_hi}] 与 "
                    f"[{b.offset_low_ghz}, …]（阶梯段须不重叠）")
        return cls(name=str(data["name"]), source=str(data["source"]),
                   f0_ghz=f0, channel_bw_ghz=ch, ref_power_dbm=ref,
                   segments=tuple(segs), axis=axis, rl_db=rl,
                   guard_offset_ghz=guard, mask_type=mask_type,
                   notes=str(data.get("notes", "")))


def _num(value: Any, name: str) -> float:
    """数值入参收敛：显式拒收 bool（df7+⑯）+ 有限数。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须为数值（不接受 bool/字符串）")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须为有限数")
    return v


# ─── 内置模板（免费遮罩库：限值=公开规范事实；f0/通道/RL=设计示例参数）────────
# bands.py 纪律：不确定的数值不上表。三模板的阶梯数值均为广泛公布的规范
# 限值事实，出处逐条写入 source/notes；实例化参数（f0/通道带宽/RL/guard）
# 是设计选择，不冒充规范数值。

def _fcc_15_247_dts() -> MaskSpec:
    return MaskSpec(
        name="fcc_15_247_dts_2g4",
        source="47 CFR §15.247(c)(3)(i)-(iii)（100 kHz RBW，dB 相对带内最高 "
               "100 kHz 分量）",
        f0_ghz=2.44, channel_bw_ghz=0.020, ref_power_dbm=20.0,
        segments=(
            MaskSegment(0.00024, 0.0015, -20.0),
            MaskSegment(0.0015, 0.0025, -30.0),
            MaskSegment(0.0025, None, -50.0),
        ),
        axis="channel_edge", rl_db=20.0, guard_offset_ghz=0.0,
        mask_type="sem_psd",
        notes="阶梯：>240 kHz 处 −20 dBc、>1.5 MHz 处 −30 dBc、>2.5 MHz 处 "
              "−50 dBc（首限值自带 240 kHz 过渡带，guard 可取 0）。"
              "f0/通道带宽为设计示例（非规范数值）；240 kHz 贴边过渡使闭式"
              "阶数显著偏高是规范物理（点态包络口径的诚实结论）。")


def _ieee_80211_dsss() -> MaskSpec:
    return MaskSpec(
        name="ieee_80211_dsss_2g4",
        source="IEEE Std 802.11-2016 §16.3.9.3 Transmit spectrum mask for "
               "DSSS（dBr 相对峰值功率谱密度）",
        f0_ghz=2.44, channel_bw_ghz=0.022, ref_power_dbm=20.0,
        segments=(
            MaskSegment(0.011, 0.020, -30.0),
            MaskSegment(0.020, 0.030, -50.0),
            MaskSegment(0.030, None, -70.0),
        ),
        axis="center", rl_db=20.0, guard_offset_ghz=0.0,
        mask_type="sem_psd",
        notes="阶梯：|f−f0|≥11 MHz −30 dBr、≥20 MHz −50 dBr、≥30 MHz −70 dBr。"
              "首段贴通带边缘（11 MHz=22 MHz 通道半宽）：全极点滤波器在 Ω=1 "
              "只能提供纹波电平衰减，guard_offset_ghz=0 时如实报不可达；"
              "实用需设 guard（调制滚降信用，设计输入）。")


def _nr_aclr_envelope() -> MaskSpec:
    return MaskSpec(
        name="nr_aclr_20mhz_envelope",
        source="3GPP TS 38.101-1 §6.5.2.3 表 6.5.2.3.1-1（NR_acLR=30 dB、"
               "UTRA_acLR=33 dB）",
        f0_ghz=2.44, channel_bw_ghz=0.020, ref_power_dbm=20.0,
        segments=(
            MaskSegment(0.0, 0.020, -30.0),
            MaskSegment(0.020, 0.040, -33.0),
        ),
        axis="channel_edge", rl_db=20.0, guard_offset_ghz=0.0,
        mask_type="aclr_envelope",
        notes="ACLR 为邻道**积分功率**语义（dBc 相对总发射功率）；本条目是"
              "点态包络预检形态——贴边段在点态口径下如实报不可达，实用需设 "
              "guard（调制滚降信用）或走积分口径（本内核不覆盖，如实标注）。"
              "40 MHz 外属杂散域（另行治理），非本遮罩范围。")


_TEMPLATE_BUILDERS = {
    "fcc_15_247_dts_2g4": _fcc_15_247_dts,
    "ieee_80211_dsss_2g4": _ieee_80211_dsss,
    "nr_aclr_20mhz_envelope": _nr_aclr_envelope,
}


def mask_template_names() -> list[str]:
    """内置遮罩模板名（字典序）。"""
    return sorted(_TEMPLATE_BUILDERS)


def get_mask_template(name: str) -> MaskSpec:
    """按名取内置遮罩模板（未知名显式 KeyError 并列出可用名）。"""
    try:
        return _TEMPLATE_BUILDERS[name]()
    except KeyError:
        raise KeyError(f"未知遮罩模板: {name!r}（可用: {mask_template_names()}）") from None


# ─── 映射与闭式内核 ──────────────────────────────────────────────────────────

def channel_fbw(f0_ghz: float, channel_bw_ghz: float) -> float:
    """通道带宽→滤波器相对带宽（几何映射精确反解）：u=ch/(2f0)，
    fbw=u(2+u)/(1+u)，使 Ω(±channel_bw/2)=±1 逐位成立。"""
    u = channel_bw_ghz / (2.0 * f0_ghz)
    return u * (2.0 + u) / (1.0 + u)


def offset_to_omega(f0_ghz: float, fbw: float, offset_ghz: float) -> float:
    """频偏（距中心，GHz）→ 归一化低通 Ω（几何映射）。"""
    x = offset_ghz / f0_ghz
    return ((1.0 + x) - 1.0 / (1.0 + x)) / fbw


def omega_to_offset(f0_ghz: float, fbw: float, omega: float) -> float:
    """归一化低通 Ω → 频偏（GHz）（映射解析反解：x²+(2−y)x−y=0 正根，
    y=Ω·fbw；测试与诊断用，与 offset_to_omega 互为独立两式）。"""
    y = omega * fbw
    x = (-(2.0 - y) + math.sqrt((2.0 - y) ** 2 + 4.0 * y)) / 2.0
    return f0_ghz * x


def ripple_from_rl(rl_db: float) -> float:
    """回损分配→带内纹波（|S21| 峰峰，dB）：ripple=10·lg(1+1/K)，
    K=10^(RL/10)−1（RL=20 → 0.0436 dB）。"""
    k = 10.0 ** (rl_db / 10.0) - 1.0
    return 10.0 * math.log10(1.0 + 1.0 / k)


def chebyshev_min_order(atten_req_db: float, rl_db: float, omega_edge: float
                        ) -> int:
    """切比雪夫最小阶闭式（Pozar §8.3 / Cameron ch.6 经典式）。

    N=ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs))，K=10^(RL/10)−1。
    - Ω_edge ≤ 1（约束点在通带内/边缘）：要求衰减 ≤ 纹波电平 → 任何阶
      免费满足（返回 0）；否则全极点滤波器在 Ω=1 只能提供纹波电平衰减，
      显式 ValueError（不静默放宽——贴边段需 guard_offset_ghz 或放宽遮罩）。
    - arg ≤ 1 等价于要求衰减 ≤ 纹波（同上免费，返回 0）。
    - ceil 带 1e-9 容差：n_raw 恰为整数时不多加一阶（fp 恰等纪律）。
    """
    if atten_req_db < 0:
        raise ValueError("atten_req_db 必须 ≥0（所需衰减）")
    if rl_db <= 0:
        raise ValueError("rl_db 必须 >0")
    om = max(float(omega_edge), 1.0)  # 裁剪到通带边缘（#140 收敛纪律）
    k = 10.0 ** (rl_db / 10.0) - 1.0
    arg = (10.0 ** (atten_req_db / 10.0) - 1.0) * k
    if arg <= 1.0:
        return 0
    if om <= 1.0 + _FP_TOL:
        ripple = ripple_from_rl(rl_db)
        raise ValueError(
            f"遮罩约束点落在通带边缘（Ω=1）且所需衰减 {atten_req_db:.4g} dB "
            f"超过带内纹波 {ripple:.4g} dB——全极点切比雪夫在通带边缘只能提供"
            "纹波电平衰减；请设 guard_offset_ghz（调制滚降信用区）或放宽该段"
            "限值（纯全极点拓扑不可达，如实拒绝不静默放宽）")
    n_raw = math.acosh(math.sqrt(arg)) / math.acosh(om)
    return max(1, math.ceil(n_raw - 1e-9))


# ─── 遮罩→最小阶（闭式）──────────────────────────────────────────────────────

def _governing_offset(mask: MaskSpec, seg: MaskSegment) -> tuple[float, bool]:
    """段的约束频偏（距中心，GHz）+ 是否贴滤波器责任起点。

    axis 折算到中心轴 → 裁剪到 max(段内缘, 边缘+guard)。
    """
    band_edge = mask.channel_bw_ghz / 2.0
    low = seg.offset_low_ghz
    if mask.axis == "channel_edge":
        low = band_edge + low
    duty_start = band_edge + mask.guard_offset_ghz
    gov = max(low, duty_start)
    return gov, gov <= duty_start + _FP_TOL


def min_order_for_mask(mask: MaskSpec, *, topology: str = "chebyshev",
                       required_margin_db: float = 0.0) -> dict[str, Any]:
    """遮罩→切比雪夫最小阶（经典 acosh 闭式，多段逐段取最大）。

    返回阶数/回损分配/纹波/逐段 Ω 与需求明细；topology 仅支持 "chebyshev"
    （其他拓扑显式拒绝，预留扩展点）。required_margin_db>0 时各段所需衰减
    按其抬升（设计裕量进闭式，闭环首试即应满足）。
    """
    if topology != "chebyshev":
        raise ValueError(f"topology {topology!r} 未支持（当前仅 chebyshev 全极点）")
    if required_margin_db < 0:
        raise ValueError("required_margin_db 必须 ≥0")
    fbw = channel_fbw(mask.f0_ghz, mask.channel_bw_ghz)
    seg_details: list[dict[str, Any]] = []
    seg_orders: list[int] = []
    for i, seg in enumerate(mask.segments):
        gov, at_edge = _governing_offset(mask, seg)
        required = -seg.limit_dbc + required_margin_db
        omega_g = max(offset_to_omega(mask.f0_ghz, fbw, gov), 1.0)
        n_seg = chebyshev_min_order(required, mask.rl_db, omega_g)
        seg_orders.append(n_seg)
        seg_details.append({
            "segment_index": i,
            "offset_low_ghz": round(seg.offset_low_ghz, 12),
            "offset_high_ghz": (None if seg.offset_high_ghz is None
                                else round(seg.offset_high_ghz, 12)),
            "limit_dbc": round(seg.limit_dbc, 9),
            "required_atten_db": round(required, 9),
            "governing_offset_ghz": round(gov, 12),
            "at_duty_start": bool(at_edge),
            "omega_norm": round(omega_g, 12),
            "segment_order": int(n_seg)})
    order = max(1, max(seg_orders)) if seg_orders else 1
    gov_idx = max(range(len(seg_details)),
                  key=lambda i: seg_details[i]["omega_norm"])
    return {"ok": True, "topology": "chebyshev", "order": int(order),
            "rl_db": round(mask.rl_db, 9),
            "ripple_db": round(ripple_from_rl(mask.rl_db), 9),
            "epsilon": round(1.0 / math.sqrt(10.0 ** (mask.rl_db / 10.0) - 1.0), 12),
            "f0_ghz": round(mask.f0_ghz, 12),
            "channel_bw_ghz": round(mask.channel_bw_ghz, 12),
            "fbw": round(fbw, 12),
            "required_margin_db": round(required_margin_db, 9),
            "segments": seg_details,
            "governing_segment": int(gov_idx),
            "mask_type": mask.mask_type, "source": mask.source,
            "note": "最小阶=逐段 ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs)) "
                    "取最大（K=10^(RL/10)−1）；约束点=段内缘裁剪到 "
                    "边缘+guard（阻带 |S21| 单调降的内缘绑定口径）"}


# ─── 耦合矩阵响应回验（cm_core 复用）─────────────────────────────────────────

def _cm_for_order(order: int, rl_db: float) -> list:
    """阶数→cm_core Cameron N+2 横向矩阵（全极点切比雪夫；列表形态）。"""
    proto = _gcheb_prototype(int(order), float(rl_db), ())
    m = _cm_transversal_exact(int(order), proto)
    return _cm_to_list(m)


def _s21_atten_at_offsets(mask: MaskSpec, matrix: list, offsets: list[float]
                          ) -> list[float]:
    """耦合矩阵频响在各频偏（距中心，GHz）处的衰减 dB（−20lg|S21|，
    低通→带通映射后经 _cm_response_raw 求解——综合产物本体，非多项式捷径）。"""
    fbw = channel_fbw(mask.f0_ghz, mask.channel_bw_ghz)
    m = np.array(
        [[[c[0] + 1j * c[1] for c in row] for row in matrix]], dtype=complex
    )[0]
    out = []
    for off in offsets:
        om = max(offset_to_omega(mask.f0_ghz, fbw, off), 1.0)
        _, s21 = _cm_response_raw(m, 1.0, 1.0, om)
        out.append(-20.0 * math.log10(max(abs(s21), _S21_FLOOR)))
    return out


def _segment_eval_offsets(mask: MaskSpec, seg: MaskSegment) -> list[float]:
    """段的评估频偏集（距中心）：约束点+外缘+中点（有限者；单调降下内缘
    为绑定，多点评取最小裕量不依赖单调性假设漏报）。"""
    gov, _ = _governing_offset(mask, seg)
    pts = {gov}
    band_edge = mask.channel_bw_ghz / 2.0
    hi = seg.offset_high_ghz
    if hi is not None:
        h = hi if mask.axis == "center" else band_edge + hi
        if h > gov + _FP_TOL:
            pts.add(h)
            pts.add((gov + h) / 2.0)
    return sorted(pts)


def mask_margin_report(mask: MaskSpec, order: int,
                       required_margin_db: float = 0.0) -> dict[str, Any]:
    """给定阶数的遮罩裕量报告（逐段裕量 dB + 最紧段 + PASS/FAIL 判定）。

    每段在约束点/外缘/中点经耦合矩阵频响评估衰减，margin=衰减−所需；
    贴滤波器责任起点的段如实标注 at_duty_start（Ω=1 处衰减≈纹波电平，
    裕量为负即 FAIL，不静默放宽）。含该阶耦合矩阵与响应采样（上侧频偏轴）。
    """
    if required_margin_db < 0:
        raise ValueError("required_margin_db 必须 ≥0")
    order = int(order)
    if order < 1:
        raise ValueError("order 必须 ≥1")
    fbw = channel_fbw(mask.f0_ghz, mask.channel_bw_ghz)
    matrix = _cm_for_order(order, mask.rl_db)
    seg_reports: list[dict[str, Any]] = []
    for i, seg in enumerate(mask.segments):
        gov, at_duty = _governing_offset(mask, seg)
        pts = _segment_eval_offsets(mask, seg)
        attens = _s21_atten_at_offsets(mask, matrix, pts)
        achieved = min(attens)
        required = -seg.limit_dbc
        margin = achieved - required
        seg_reports.append({
            "segment_index": i,
            "offset_low_ghz": round(seg.offset_low_ghz, 12),
            "offset_high_ghz": (None if seg.offset_high_ghz is None
                                else round(seg.offset_high_ghz, 12)),
            "limit_dbc": round(seg.limit_dbc, 9),
            "required_atten_db": round(required, 9),
            "governing_offset_ghz": round(gov, 12),
            "at_duty_start": bool(at_duty),
            "omega_norm": round(max(offset_to_omega(mask.f0_ghz, fbw, gov), 1.0), 12),
            "achieved_atten_db": round(achieved, 6),
            "margin_db": round(margin, 6),
            "pass": bool(margin >= required_margin_db - _FP_TOL)})
    all_pass = all(s["pass"] for s in seg_reports)
    tight = min(seg_reports, key=lambda s: s["margin_db"]) if seg_reports else None
    # 响应采样（上侧频偏轴，约束点跨度均匀 161 点；开段封顶=最远约束×1.5）
    govs = [_governing_offset(mask, s)[0] for s in mask.segments]
    span_lo = min(govs)
    finite_hi = [s.offset_high_ghz for s in mask.segments
                 if s.offset_high_ghz is not None]
    if finite_hi:
        hi_abs = max(finite_hi if mask.axis == "center"
                     else [mask.channel_bw_ghz / 2.0 + v for v in finite_hi])
    else:
        hi_abs = max(govs) * 1.5
    span_hi = max(hi_abs, max(govs))
    n_sample = 161
    sample_offsets = [span_lo + (span_hi - span_lo) * k / (n_sample - 1)
                      for k in range(n_sample)]
    sample_attens = _s21_atten_at_offsets(mask, matrix, sample_offsets)
    return {
        "ok": True, "pass": bool(all_pass),
        "order": order, "topology": "chebyshev",
        "rl_db": round(mask.rl_db, 9),
        "ripple_db": round(ripple_from_rl(mask.rl_db), 9),
        "f0_ghz": round(mask.f0_ghz, 12),
        "channel_bw_ghz": round(mask.channel_bw_ghz, 12),
        "fbw": round(fbw, 12),
        "required_margin_db": round(required_margin_db, 9),
        "segments": seg_reports,
        "tightest_segment": (None if tight is None
                             else int(tight["segment_index"])),
        "min_margin_db": (None if tight is None else round(tight["margin_db"], 6)),
        "coupling_matrix": matrix,
        "matrix_shape": [order + 2, order + 2],
        "external_q": [1.0, 1.0],
        "response_sample": {
            "offset_ghz": [round(v, 12) for v in sample_offsets],
            "atten_db": [round(v, 6) for v in sample_attens]},
        "mask_type": mask.mask_type,
        "source": mask.source,
        "note": "衰减经 cm_core (N+2) 耦合矩阵频响评估（−20lg|S21|）；"
                + ("mask_type=aclr_envelope：ACLR 为积分语义，本报告为点态"
                   "包络预检口径" if mask.mask_type == "aclr_envelope" else
                   "点态 psd 包络口径")}


# ─── 闭环：最小阶→综合→回验→（不足 +1）───────────────────────────────────────

def synthesize_from_mask(mask: MaskSpec, *, topology: str = "chebyshev",
                         required_margin_db: float = 0.0,
                         max_order_extra: int = 3,
                         min_order_override: int | None = None
                         ) -> dict[str, Any]:
    """mask→滤波器规格综合闭环：闭式最小阶起步，逐阶 cm_core 耦合矩阵+
    矩阵频响回验遮罩裕量，不足自动 +1（max_order_extra 上限），报告各阶
    裕量轨迹。min_order_override 给定时从该阶起步（轨迹演示/调用方钉阶）。

    返回 ok=False（含轨迹）当上限内无阶满足；闭式不可达（贴边段）透传
    ValueError（不静默放宽）。
    """
    closed = min_order_for_mask(mask, topology=topology,
                                required_margin_db=required_margin_db)
    start = int(min_order_override) if min_order_override is not None \
        else int(closed["order"])
    if start < 1:
        raise ValueError("min_order_override 必须 ≥1")
    if int(max_order_extra) < 0:
        raise ValueError("max_order_extra 必须 ≥0")
    last_cap = start + int(max_order_extra)
    trajectory: list[dict[str, Any]] = []
    final_report: dict[str, Any] | None = None
    for n in range(start, last_cap + 1):
        rep = mask_margin_report(mask, n, required_margin_db)
        trajectory.append({"order": n,
                           "min_margin_db": rep["min_margin_db"],
                           "pass": rep["pass"]})
        if rep["pass"]:
            final_report = rep
            break
    out: dict[str, Any] = {
        "ok": final_report is not None,
        "pass": final_report is not None,
        "topology": "chebyshev",
        "min_order_closed_form": int(closed["order"]),
        "start_order": start,
        "max_order_extra": int(max_order_extra),
        "required_margin_db": round(required_margin_db, 9),
        "trajectory": trajectory,
        "closed_form_detail": closed,
        "source": mask.source,
        "mask": mask.to_dict()}
    if final_report is not None:
        out.update({"order": final_report["order"],
                    "coupling_matrix": final_report["coupling_matrix"],
                    "matrix_shape": final_report["matrix_shape"],
                    "external_q": final_report["external_q"],
                    "margin_report": {
                        k: final_report[k] for k in (
                            "segments", "tightest_segment", "min_margin_db",
                            "fbw", "ripple_db", "response_sample")}})
    else:
        out["order"] = None
        out["note"] = (
            f"阶数上限 {last_cap} 内无解（闭式最小阶 "
            f"{closed['order']}，起点 {start}）；轨迹如实报告各阶裕量")
    return out


__all__ = [
    "MaskSegment",
    "MaskSpec",
    "channel_fbw",
    "chebyshev_min_order",
    "get_mask_template",
    "mask_margin_report",
    "mask_template_names",
    "min_order_for_mask",
    "offset_to_omega",
    "omega_to_offset",
    "ripple_from_rl",
    "synthesize_from_mask",
]
