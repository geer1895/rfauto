"""EMP/HEMP/HIRF 常量表（round19 P3 EMP 小包，ge8c 席C6）。

标准常量数据一等对象（同 bands.py 惯例：本表是标准常量数据非计算产物，
每条带出处；不确定的数值宁可不上表——bands.py docstring 口径）。

双源逐格纪律（引用腐坏 #df6-⑨）：本模块全部数值于 2026-10-03 从**可达的
公开一手文献原文逐格转录**（PDF 下载后 pypdf 抽取核对），检索不可达的格
一律不上表（宁缺毋滥）。三处一手来源：

- **S1 = MIL-STD-464C**（DoD interface standard，2010-12-01）。本文实际
  下载 assist.dla.mil 公开副本（ema3d.com 镜像 PDF，165 页，文内下载戳
  ``assist.dla.mil -- Downloaded: 2015-01-23``）逐格抽取：
  - §5.3 External RF EME 外部射频环境表按平台分列（TABLE 1~7），本表转录
    TABLE 4（地面系统）/TABLE 5（旋翼机含 UAV）/TABLE 6（固定翼含 UAV）
    三张最可复用表（频段 0.01–50000 MHz，峰值/均值场强 V/m-rms）。
    标准原文注明：均值场 = 峰值功率×调制占空比口径。
  - §5.6 EMP：HEMP 环境本身**涉密**、现行定义在 MIL-STD-2169（非公开）——
    即 464C 本体不含公开 HEMP 数值，本模块如实记 pointer 不编数。
- **S2 = DOE-CR-MARCH-2023「HEMP Waveform Application Guide」**（EPRI 为
  美国能源部 CESER 而作，Contract DE-CR0000002，2023-07 版；energy.gov 公开
  PDF，28 页，2026-10-03 实取）。原文（§Executive Summary 段）逐句：
  E1 = 双指数，上升时间 2.5 ns、半高宽 23 ns、幅值既有威胁 25 kV/m /
  未来裕量 50 kV/m；E2 = 双指数，半高宽 693 µs、幅值 50 V/m / 100 V/m；
  E3 = E3A（blast）峰值 40 V/km / 80 V/km + E3B（heave）峰值 25 V/km /
  50 V/km；E1 频率含量"数百 MHz"量级。上游指针 [1] = DOE Memorandum
  "Physical Characteristics of HEMP Waveform Benchmarks…"（2021-01）。
- **S3 = Zhu et al., "HEMP Excited Shield Residual Electric Field Modeling
  Method Based on NARX Neural Network", PIER C, Vol. 100, 205–218, 2020**
 （jpier.org 开放获取 PDF，2026-10-03 实取）。转录其 §2 引述的
  IEC 61000-2-9 E1 双指数参数：tr = 2.5 ns、tw（半高宽）= 23 ns，对应
  ``alpha = 4.0e7 s^-1, beta = 6.0e8 s^-1, K = 6.5e4 V/m``（E(t)=K(e^{-αt}−e^{-βt})
  口径）；并引述 Bell HEMP 波形 tr = 4.1 ns、tw = 184 ns（其文献 [15]）。

双源裁定（逐格）：
- E1 tr=2.5 ns / FWHM=23 ns / 峰值 50 kV/m：S2∩S3 双源一致 → VERIFIED；
  S2 的 25 kV/m（既有威胁档）为 S2 单源 → ``sources`` 如实只挂 S2。
- E2（FWHM 693 µs、50/100 V/m）：S2 单源数值（幅值/半高宽）；时长量级
  "E2 < 10 ms" 与 API Technologies 公开白皮书一致（第三源佐证，非逐格）→
  数值格如实标单源。
- E3（E3A/E3B V/km 峰值）：S2 单源数值；E3A blast ~10 s / E3B heave
  ~1–2 min 时长与 API 白皮书一致（佐证）→ 数值格如实标单源。
- MIL-STD-464C 外部 RF EME 表：标准文本本身即记录源（S1 原文逐格抽取，
  ``assist.dla.mil`` 权威副本）。

波形内核（确定性，铁律 7 兼容）：双指数生成器与闭式频谱只对**参数齐全**
的波形（E1-IEC）开放；E2/E3 源文献未给 α/β → 不编参数，如实 None。
:func:`check_e1_self_consistency` 用数值法从 α/β/K 复算 tr/FWHM/峰值，
与文献声明值对拍（#118：数值的裁判是独立来源+复算，不是自己推导）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BELL_FWHM_S",
    "BELL_TR_S",
    "E1_ALPHA_PER_S",
    "E1_BETA_PER_S",
    "E1_K_V_PER_M",
    "EMP_SCHEMA",
    "HEMP_COMPONENTS",
    "HIRF_F_RANGE_MHZ",
    "HIRF_TABLES",
    "MIL_STD_464C_EMP_POINTER",
    "SOURCE_API_WHITEPAPER",
    "SOURCE_DOE_WF_GUIDE",
    "SOURCE_MIL_STD_464C",
    "SOURCE_PIER_C100_IEC",
    "HempComponent",
    "HirfBand",
    "check_e1_self_consistency",
    "e1_double_exponential",
    "e1_spectrum",
    "hirf_band_for",
    "hirf_peak_for",
    "hirf_platforms",
    "validate_hirf_tables",
]

#: 常量表 schema 标识（JSON 消费面稳定钉）。
EMP_SCHEMA = "rfauto-emp-hemp-v1"

#: 三处一手来源的短键（docstring 全称，条目 sources 只挂短键）。
SOURCE_MIL_STD_464C = "MIL-STD-464C"
SOURCE_DOE_WF_GUIDE = "DOE-CR-MARCH-2023-WaveformGuide"
SOURCE_PIER_C100_IEC = "PIERC100-2020-IEC61000-2-9"
SOURCE_API_WHITEPAPER = "APITech-EMP-HEMP-Whitepaper"

#: E2/E3 双源待补的如实注记（单源数值格必带）。
_SINGLE_SOURCE_NOTE = (
    "S2 单源数值（幅值/脉宽）；S1（MIL-STD-464C §5.6）HEMP 涉密指向 "
    "MIL-STD-2169 不含公开数值。时长量级另见 APITech 白皮书佐证。")


# ---------------------------------------------------------------------------
# HEMP E1/E2/E3 组件表（S2 逐格；E1 参数另有 S3 双源）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HempComponent:
    """一个 HEMP 组件的声明常量（只收源文献明确给出的格）。"""

    component: str                 # "E1" | "E2" | "E3A" | "E3B"
    unit: str                      # 幅值单位（"V/m" | "V/km"）
    amplitude_existing: float      # 既有威胁档幅值（S2）
    amplitude_future: float        # 未来裕量档幅值（S2）
    rise_time_s: float | None      # 10%-90% 上升时间（源给出才有）
    fwhm_s: float | None           # 半高宽（源给出才有）
    duration_note: str = ""        # 时长量级佐证（非逐格数值，仅注记）
    sources: tuple[str, ...] = ()  # 逐格来源短键
    dual_source: bool = False      # 幅值+时间参数是否双源逐格一致
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "unit": self.unit,
            "amplitude_existing": self.amplitude_existing,
            "amplitude_future": self.amplitude_future,
            "rise_time_s": self.rise_time_s,
            "fwhm_s": self.fwhm_s,
            "duration_note": self.duration_note,
            "sources": list(self.sources),
            "dual_source": self.dual_source,
            "note": self.note,
        }


#: E1/E2/E3 常量（S2 原文逐句转录；E1 时间参数双源 = S2∩S3）。
HEMP_COMPONENTS: dict[str, HempComponent] = {
    "E1": HempComponent(
        component="E1",
        unit="V/m",
        amplitude_existing=25_000.0,
        amplitude_future=50_000.0,
        rise_time_s=2.5e-9,
        fwhm_s=23.0e-9,
        duration_note="E1 duration < 1 us（APITech 白皮书佐证量级）",
        sources=(SOURCE_DOE_WF_GUIDE, SOURCE_PIER_C100_IEC),
        dual_source=True,
        note="tr/FWHM/50kV 峰值双源一致（S2 文字值 ∩ S3 引述 IEC α/β/K 复算）",
    ),
    "E2": HempComponent(
        component="E2",
        unit="V/m",
        amplitude_existing=50.0,
        amplitude_future=100.0,
        rise_time_s=None,          # S2 未给 E2 上升时间——不编
        fwhm_s=693.0e-6,
        duration_note="E2 duration < 10 ms（APITech 白皮书佐证量级）",
        sources=(SOURCE_DOE_WF_GUIDE,),
        dual_source=False,
        note=_SINGLE_SOURCE_NOTE,
    ),
    "E3A": HempComponent(
        component="E3A",
        unit="V/km",
        amplitude_existing=40.0,
        amplitude_future=80.0,
        rise_time_s=None,
        fwhm_s=None,
        duration_note="E3 blast ~10 s（APITech 白皮书佐证量级）",
        sources=(SOURCE_DOE_WF_GUIDE,),
        dual_source=False,
        note="blast 分量；波形参数 S2 指向 DOE memo（2021-01），本表不编" +
             _SINGLE_SOURCE_NOTE,
    ),
    "E3B": HempComponent(
        component="E3B",
        unit="V/km",
        amplitude_existing=25.0,
        amplitude_future=50.0,
        rise_time_s=None,
        fwhm_s=None,
        duration_note="E3 heave ~1-2 min（APITech 白皮书佐证量级）",
        sources=(SOURCE_DOE_WF_GUIDE,),
        dual_source=False,
        note="heave 分量；" + _SINGLE_SOURCE_NOTE,
    ),
}

#: MIL-STD-464C §5.6 EMP 涉密指针（如实登记，不编公开 HEMP 数值）。
MIL_STD_464C_EMP_POINTER = {
    "standard": "MIL-STD-464C",
    "section": "5.6 Electromagnetic pulse (EMP)",
    "status": "classified_environment_pointer",
    "statement": (
        "The system shall meet its operational performance requirements after "
        "being subjected to the EMP environment. This environment is classified "
        "and is currently defined in MIL-STD-2169."),
    "sources": (SOURCE_MIL_STD_464C,),
}


# ---------------------------------------------------------------------------
# MIL-STD-464C 外部 RF EME 表（§5.3 TABLE 4/5/6，V/m-rms）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HirfBand:
    """一个外部 RF EME 频段行（464C 表逐格；f 单位 MHz，场强 V/m-rms）。"""

    platform: str      # "ground" | "rotary_wing" | "fixed_wing"
    table: str         # "TABLE 4" | "TABLE 5" | "TABLE 6"
    f_low_mhz: float
    f_high_mhz: float
    peak_vm: float
    avg_vm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "table": self.table,
            "f_low_mhz": self.f_low_mhz,
            "f_high_mhz": self.f_high_mhz,
            "peak_vm": self.peak_vm,
            "avg_vm": self.avg_vm,
        }


def _rows(platform: str, table: str,
          raw: tuple[tuple[float, float, float, float], ...]) -> list[HirfBand]:
    return [HirfBand(platform=platform, table=table, f_low_mhz=lo,
                     f_high_mhz=hi, peak_vm=pk, avg_vm=av)
            for lo, hi, pk, av in raw]


# 逐格转录（2026-10-03 pypdf 抽取自 assist.dla.mil 副本；(f_low, f_high, peak, avg)，
# MHz / V/m-rms）。
_TABLE4_RAW: tuple[tuple[float, float, float, float], ...] = (
    (0.01, 2, 73, 73), (2, 30, 103, 103), (30, 150, 74, 74),
    (150, 225, 41, 41), (225, 400, 92, 92), (400, 700, 98, 98),
    (700, 790, 267, 267), (790, 1000, 284, 267), (1000, 2000, 2452, 155),
    (2000, 2700, 489, 155), (2700, 3600, 2450, 219), (3600, 4000, 489, 49),
    (4000, 5400, 645, 183), (5400, 5900, 6146, 155), (5900, 6000, 549, 55),
    (6000, 7900, 4081, 119), (7900, 8000, 549, 97), (8000, 8400, 1095, 110),
    (8400, 8500, 1095, 110), (8500, 11000, 1943, 139), (11000, 14000, 3454, 110),
    (14000, 18000, 8671, 243), (18000, 50000, 2793, 76),
)
_TABLE5_RAW: tuple[tuple[float, float, float, float], ...] = (
    (0.01, 2, 200, 200), (2, 30, 200, 200), (30, 150, 200, 200),
    (150, 225, 200, 200), (225, 400, 200, 200), (400, 700, 1311, 402),
    (700, 790, 700, 402), (790, 1000, 700, 402), (1000, 2000, 6057, 232),
    (2000, 2700, 3351, 200), (2700, 3600, 4220, 455), (3600, 4000, 3351, 200),
    (4000, 5400, 9179, 657), (5400, 5900, 9179, 657), (5900, 6000, 9179, 200),
    (6000, 7900, 400, 200), (7900, 8000, 400, 200), (8000, 8400, 7430, 266),
    (8400, 8500, 7430, 266), (8500, 11000, 7430, 266), (11000, 14000, 7430, 558),
    (14000, 18000, 730, 558), (18000, 50000, 1008, 200),
)
_TABLE6_RAW: tuple[tuple[float, float, float, float], ...] = (
    (0.01, 2, 88, 27), (2, 30, 64, 64), (30, 150, 67, 13),
    (150, 225, 67, 36), (225, 400, 58, 3), (400, 700, 2143, 159),
    (700, 790, 80, 80), (790, 1000, 289, 105), (1000, 2000, 3363, 420),
    (2000, 2700, 957, 209), (2700, 3600, 4220, 455), (3600, 4000, 148, 11),
    (4000, 5400, 3551, 657), (5400, 5900, 3551, 657), (5900, 6000, 148, 4),
    (6000, 7900, 344, 14), (7900, 8000, 148, 4), (8000, 8400, 187, 70),
    (8400, 8500, 187, 70), (8500, 11000, 6299, 238), (11000, 14000, 2211, 94),
    (14000, 18000, 1796, 655), (18000, 50000, 533, 38),
)

#: 平台 → 外部 RF EME 表（MIL-STD-464C §5.3 TABLE 4/5/6）。
HIRF_TABLES: dict[str, tuple[HirfBand, ...]] = {
    "ground": tuple(_rows("ground", "TABLE 4", _TABLE4_RAW)),
    "rotary_wing": tuple(_rows("rotary_wing", "TABLE 5", _TABLE5_RAW)),
    "fixed_wing": tuple(_rows("fixed_wing", "TABLE 6", _TABLE6_RAW)),
}

#: 464C 表覆盖的频率范围（MHz；各平台一致 0.01–50000）。
HIRF_F_RANGE_MHZ = (0.01, 50000.0)


def hirf_platforms() -> list[str]:
    """已登记平台键（确定性序）。"""
    return sorted(HIRF_TABLES)


def hirf_band_for(platform: str, freq_mhz: float) -> HirfBand | None:
    """频率 → 所在频段行（含端点左闭右闭；未登记平台/越界 → None 不硬凑）。

    Raises:
        TypeError: platform/freq_mhz 类型非法。
        ValueError: platform 已登记但 freq_mhz 非有限。
    """
    if not isinstance(platform, str):
        raise TypeError("platform must be str")
    bands = HIRF_TABLES.get(platform)
    if bands is None:
        return None
    f = float(freq_mhz)
    if not math.isfinite(f):
        raise ValueError("freq_mhz must be finite")
    lo, hi = HIRF_F_RANGE_MHZ
    if f < lo or f > hi:
        return None
    for b in bands:
        if b.f_low_mhz <= f <= b.f_high_mhz:
            return b
    return None  # pragma: no cover - validate_hirf_tables 保证全覆盖


def hirf_peak_for(platform: str, freq_mhz: float) -> dict[str, Any]:
    """频点 → 该平台峰值/均值场强包络（JSON 进出；未命中 ok=False 如实）。"""
    band = hirf_band_for(platform, freq_mhz)
    if band is None:
        return {"ok": False, "platform": platform, "freq_mhz": freq_mhz,
                "reason": "no_band（未登记平台或超出 0.01–50000 MHz 覆盖）"}
    out = band.to_dict()
    out.update({
        "ok": True,
        "unit": "V/m rms",
        "source": f"MIL-STD-464C section 5.3 {band.table}",
        "note": "均值场=峰值功率×调制占空比口径（464C 原文注）",
    })
    return out


def validate_hirf_tables() -> list[str]:
    """注册表完整性守卫（bands.validate_registry 同族）：返回问题清单。

    检查：每平台频段连续无重叠、单调递增、全覆盖 0.01–50000 MHz、
    峰值 ≥ 均值（464C 各行实测满足）。空清单 = 健康。
    """
    problems: list[str] = []
    for platform, bands in HIRF_TABLES.items():
        if not bands:
            problems.append(f"{platform}: empty table")
            continue
        cursor = HIRF_F_RANGE_MHZ[0]
        for i, b in enumerate(bands):
            if b.f_low_mhz != cursor:
                problems.append(
                    f"{platform}#{i}: band start {b.f_low_mhz} != cursor {cursor}")
            if b.f_high_mhz <= b.f_low_mhz:
                problems.append(f"{platform}#{i}: non-increasing band")
            if b.peak_vm < b.avg_vm:
                problems.append(f"{platform}#{i}: peak < average")
            cursor = b.f_high_mhz
        if cursor != HIRF_F_RANGE_MHZ[1]:
            problems.append(
                f"{platform}: coverage ends {cursor} != {HIRF_F_RANGE_MHZ[1]}")
    return problems


# ---------------------------------------------------------------------------
# E1 双指数波形内核（确定性；只对参数齐全的 IEC E1 开放）
# ---------------------------------------------------------------------------

#: IEC 61000-2-9 E1 双指数参数（S3 原文转录：alpha/beta 单位 s^-1，K 单位 V/m）。
E1_ALPHA_PER_S = 4.0e7
E1_BETA_PER_S = 6.0e8
E1_K_V_PER_M = 6.5e4

#: Bell HEMP 波形时间参数（S3 引述其文献 [15]；α/β/K 未给 → 不编）。
BELL_TR_S = 4.1e-9
BELL_FWHM_S = 184.0e-9


def e1_double_exponential(t_s: Any) -> Any:
    """IEC E1 双指数波形 E(t)=K(e^{-αt}−e^{-βt})（numpy 纯函数）。

    t_s：秒（标量或数组，须非负有限）。返回 V/m 同形数组。
    """
    import numpy as np

    arr = np.asarray(t_s, dtype=float)
    if np.any(arr < 0) or not np.all(np.isfinite(arr)):
        raise ValueError("t_s must be non-negative finite seconds")
    return E1_K_V_PER_M * (np.exp(-E1_ALPHA_PER_S * arr)
                           - np.exp(-E1_BETA_PER_S * arr))


def e1_spectrum(f_hz: Any) -> Any:
    """E1 双指数的连续时间傅里叶幅值 |E(f)|（闭式，V/m·s 口径）。

    E(t)=K(e^{-αt}−e^{-βt}) ⟺ E(f)=K(1/(α+j2πf)−1/(β+j2πf))。
    与 S3 Fig.4 谱覆盖（10^6–10^9 Hz 主能量）同量级口径，只作确定性
    参考谱（非标准声明的谱密度表——源文献未给逐格谱值，不编）。
    """
    import numpy as np

    f = np.asarray(f_hz, dtype=float)
    if not np.all(np.isfinite(f)):
        raise ValueError("f_hz must be finite")
    w = 2.0 * math.pi * f
    denom_a = E1_ALPHA_PER_S + 1j * w
    denom_b = E1_BETA_PER_S + 1j * w
    return np.abs(E1_K_V_PER_M * (1.0 / denom_a - 1.0 / denom_b))


def _de_metrics(alpha: float, beta: float, k: float) -> dict[str, float]:
    """数值法复算双指数 (10-90% tr, FWHM, 峰值)（#118：复算裁判）。"""
    # 峰值时刻 t_p = ln(β/α)/(β−α)，峰值解析可得；tr/FWHM 数值求根。
    t_p = math.log(beta / alpha) / (beta - alpha)
    peak = k * (math.exp(-alpha * t_p) - math.exp(-beta * t_p))
    half = peak / 2.0

    def e(t: float) -> float:
        return k * (math.exp(-alpha * t) - math.exp(-beta * t))

    def bisect(fn, lo: float, hi: float, target: float) -> float:
        flo = fn(lo) - target
        for _ in range(200):
            mid = (lo + hi) / 2.0
            fm = fn(mid) - target
            if (fm > 0) == (flo > 0):
                lo, flo = mid, fm
            else:
                hi = mid
        return (lo + hi) / 2.0

    t10 = bisect(e, 0.0, t_p, 0.1 * peak)
    t90 = bisect(e, 0.0, t_p, 0.9 * peak)
    t_h1 = bisect(e, 0.0, t_p, half)
    # 半高宽右交点在峰值后，e 单调递减区间二分
    t_h2 = bisect(e, t_p, t_p * 100.0, half)
    return {
        "rise_time_s": t90 - t10,
        "fwhm_s": t_h2 - t_h1,
        "peak_v_per_m": peak,
        "peak_time_s": t_p,
    }


def check_e1_self_consistency(
    *,
    tr_ref_s: float = 2.5e-9,
    fwhm_ref_s: float = 23.0e-9,
    peak_ref_v_per_m: float = 50_000.0,
    rel_tol: float = 0.05,
) -> dict[str, Any]:
    """从 α/β/K 数值复算 tr/FWHM/峰值并与文献声明值对拍（S2∩S3 双源核）。

    rel_tol 缺省 5%（双指数时间常数的 10-90%/半高定义对文献圆整敏感）。
    返回 {ok, metrics, refs, rel_err}；任一格超差 ok=False（如实红，不凑）。
    """
    m = _de_metrics(E1_ALPHA_PER_S, E1_BETA_PER_S, E1_K_V_PER_M)
    refs = {"rise_time_s": tr_ref_s, "fwhm_s": fwhm_ref_s,
            "peak_v_per_m": peak_ref_v_per_m}
    rel_err: dict[str, float] = {}
    for key, ref in refs.items():
        rel_err[key] = abs(m[key] - ref) / abs(ref)
    ok = all(v <= rel_tol for v in rel_err.values())
    return {"ok": ok, "metrics": m, "refs": refs, "rel_err": rel_err,
            "rel_tol": rel_tol,
            "note": "S3(IEC α/β/K) 复算 ∩ S2(S1/S2 声明值) 对拍；超差如实红"}
