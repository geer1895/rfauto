"""WR 矩形波导标准尺寸/推荐工作带表（EIA WR 系，月度增强计划 ME-4）。

数据口径
--------
每行字段 {wr_name, a_mm, b_mm, f_start_ghz, f_end_ghz, fc10_ghz}，另含
可选法兰注记列 flange_ug 与逐行来源标注列 source。单位：尺寸 mm、频率
GHz；c=299792458 m/s（SI 定义值，与 core/rwg_mmt.py 的 C0 同值——
rwg_mmt 内部 SI 米制，本表 mm/GHz 实用制，跨模块一致性由单测钉住）。

三源一致性（ME-4 判据核心）
--------------------------
计划点名三源：Copper Mountain 波导指南、RF Essentials、A-Info 表。
2026-09-26 实测检索（限流下 3 次命中）逐行核对：RF Essentials
（rfessentials.com，计划点名源）与同业多源（QuinStar、Keysight、
Mi-Wave、HASCO、Dolph Microwave、TT Telecom 波导/法兰交叉表）；
Copper Mountain 与 A-Info 页面未直接命中，以同业多源替代交叉。
来源等级逐行标注于 source 字段（诚实口径）：

- ``3src``：教科书 EIA 表 + 检索多源一致 + fc=c/2a 恒等式自洽（12 行）
- ``2src``：教科书 EIA 表 + 恒等式自洽，未获检索逐行交叉（5 行：
  WR-51/75/340/430/650）
- ``2src-thz``：THz 段扩容 9 行（WR-8..WR-1.0，2026-10-05 W4-D TH-1），
  逐行双源一致才入表——来源 A=VDI Waveguide Band Designations
  （vadiodes.com，2014-01 版 PDF 实测转录）；来源 B=Spinner
  TD-00036 Issue N（2019-03-12，IEC 60153-2:2016/EIA RS-261-B/
  IEEE 1785.1-2012 交叉表，microwaves101.com/uploads 托管，即
  Microwaves101 尺寸页声明"原表过时"后指向的替代承载）。尺寸/推荐带
  逐格双源比对全部一致；WR-8..WR-3.4 按仓内惯例取英寸定义值 ×25.4
  精确换算（与双源打印微米值差 ≤0.5 µm 舍入），WR-2.8..WR-1.0 无
  英寸定义（IEEE 1785.1 微米值为主定义），按微米精确值入表。法兰：
  UG-387 变体族未获双源逐行确认，一律 None（不凑值）。
- 单源行不收（本表无）。

主自洽判据：fc10_ghz == c/(2*a_mm)（TE10 截止恒等式，全表单测 rtol
1e-9 扫描）。fc10_ghz 由 cutoff_te10 建表时同源计算，杜绝手抄漂移。

法兰注记：仅收录经典 EIA UG 型（cover/方法兰）且检索多源一致的 9 行；
FBM/CMR 系未做逐行三源核对，一律 None（如实留空，不凑值）。

查找语义
--------
- wr_lookup：大小写不敏感，"WR" 前缀/连字符/空格/下划线容错（纯数字
  入参按缺 WR 前缀解析，如 "90" 等价 "WR-90"）；未知名 KeyError。
- wr_from_frequency：推荐带按闭区间 [f_start, f_end] 含端点命中；
  教科书推荐带本身重叠（如 9.5 GHz 同落 WR-112 与 WR-90），命中多行
  显式并列返回元组（表序），带外返回 None。与计划书签名
  ``WRRecord | None`` 的偏离（多命中列表）系数据实情：重叠带存在，
  静默取其一为不诚实口径，已按任务书"重叠带显式并列"授权收窄。
- bands 联动：wr_bands() 产出与 core/bands.py BandEntry 字段同构的
  适配序列（字段名与 to_dict 键集逐一对齐）；kind 用字符串
  "waveguide"（BandKind 四值 licensed/ism/srd/emc 均不适用于物理波导
  推荐带，误标 licensed 会污染监管频段消费面；bands.py 只读不改）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

C0 = 299792458.0  # m/s，SI 定义值；与 core/rwg_mmt.py C0 同值

_SOURCE_3SRC = "3src：教科书EIA表+检索多源一致+fc=c/2a恒等式自洽"
_SOURCE_2SRC = "2src：教科书EIA表+fc=c/2a恒等式自洽（检索限流未逐行交叉）"
_SOURCE_2SRC_THZ = (
    "2src-thz：VDI频段表+Spinner TD-00036（IEC 60153-2/IEEE 1785.1）"
    "逐行双源一致+fc=c/2a自洽"
)


def _reject_non_positive_finite(value: float, name: str) -> None:
    """数值入参守卫：显式拒收 bool 与非正/非有限值（df7+ 坑16 惯例）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为正有限数，得到 bool {value!r}")
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")


@dataclass(frozen=True)
class WRRecord:
    """单个 WR 标准波导条目。

    Attributes:
        wr_name: EIA 型号（如 "WR-90"）
        a_mm: 波导宽边内尺寸（mm）
        b_mm: 波导窄边内尺寸（mm）
        f_start_ghz: 推荐工作带下端（GHz，闭区间含端点）
        f_end_ghz: 推荐工作带上端（GHz，闭区间含端点）
        fc10_ghz: TE10 截止频率（GHz）= c/(2*a_mm)，建表时同源计算
        flange_ug: 经典 EIA UG 法兰注记（仅检索多源一致行；否则 None）
        source: 来源等级标注（3src/2src 前缀，语义见模块 docstring）
    """

    wr_name: str
    a_mm: float
    b_mm: float
    f_start_ghz: float
    f_end_ghz: float
    fc10_ghz: float
    flange_ug: str | None
    source: str


def cutoff_te10(a_m: float) -> float:
    """矩形波导 TE10 截止频率（Hz）。a_m 为宽边内尺寸（米）；fc = c/(2a)。"""
    _reject_non_positive_finite(a_m, "a_m")
    return C0 / (2.0 * a_m)


def wavelength_g(f_ghz: float, a_mm: float) -> float:
    """矩形波导 TE10 导波波长（mm）：λg = λ0/√(1−(fc/f)²)。

    f_ghz 工作频率（GHz），a_mm 宽边内尺寸（mm）。f ≤ fc 无传播解，
    显式 ValueError（不返回复数/NaN 静默污染下游）。
    """
    _reject_non_positive_finite(f_ghz, "f_ghz")
    _reject_non_positive_finite(a_mm, "a_mm")
    fc_hz = cutoff_te10(a_mm * 1e-3)
    f_hz = f_ghz * 1e9
    if f_hz <= fc_hz:
        raise ValueError(
            f"f={f_ghz:g} GHz 不高于 TE10 截止 {fc_hz / 1e9:.6f} GHz（a={a_mm} mm），无传播解"
        )
    ratio = fc_hz / f_hz
    lam0_mm = C0 / f_hz * 1e3
    return lam0_mm / math.sqrt(1.0 - ratio * ratio)


def _rec(
    wr_name: str,
    a_mm: float,
    b_mm: float,
    f_start_ghz: float,
    f_end_ghz: float,
    flange_ug: str | None,
    source: str,
) -> WRRecord:
    """建行辅助：fc10 由恒等式同源计算，杜绝手抄漂移。"""
    return WRRecord(
        wr_name=wr_name,
        a_mm=a_mm,
        b_mm=b_mm,
        f_start_ghz=f_start_ghz,
        f_end_ghz=f_end_ghz,
        fc10_ghz=cutoff_te10(a_mm * 1e-3) / 1e9,
        flange_ug=flange_ug,
        source=source,
    )


# 主流表（26 行 = 种子 17 行 + THz 扩容 9 行 WR-8..WR-1.0；按 f_start 降序）。
# 种子行：英寸定义值 ×25.4 精确换算；带端点为教科书 EIA 推荐口径。
# 来源等级：12 行 3src（检索多源一致）、5 行 2src（教科书+恒等式）、
# 9 行 2src-thz（VDI+Spinner 双源逐行一致），无单源行。
WR_TABLE: tuple[WRRecord, ...] = (
    # ── THz 扩容（W4-D TH-1，2026-10-05）：WR-8..WR-1.0，双源口径见模块 docstring ──
    _rec("WR-1.0", 0.2500, 0.1250, 750.0, 1100.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-1.5", 0.3800, 0.1900, 500.0, 750.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-2.2", 0.5700, 0.2850, 330.0, 500.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-2.8", 0.7100, 0.3550, 260.0, 400.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-3.4", 0.8636, 0.4318, 220.0, 330.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-4.3", 1.0922, 0.5461, 170.0, 260.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-5.1", 1.2954, 0.6477, 140.0, 220.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-6.5", 1.6510, 0.8255, 110.0, 170.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-8", 2.0320, 1.0160, 90.0, 140.0, None, _SOURCE_2SRC_THZ),
    _rec("WR-10", 2.5400, 1.2700, 75.0, 110.0, "UG-387/U-M", _SOURCE_3SRC),
    _rec("WR-12", 3.0988, 1.5494, 60.0, 90.0, None, _SOURCE_3SRC),
    _rec("WR-15", 3.7592, 1.8796, 50.0, 75.0, None, _SOURCE_3SRC),
    _rec("WR-22", 5.6896, 2.8448, 33.0, 50.0, None, _SOURCE_3SRC),
    _rec("WR-28", 7.1120, 3.5560, 26.5, 40.0, "UG-599/U", _SOURCE_3SRC),
    _rec("WR-42", 10.6680, 4.3180, 18.0, 26.5, "UG-595/U", _SOURCE_3SRC),
    _rec("WR-51", 12.9540, 6.4770, 15.0, 22.0, None, _SOURCE_2SRC),
    _rec("WR-62", 15.7988, 7.8994, 12.4, 18.0, "UG-419/U", _SOURCE_3SRC),
    _rec("WR-75", 19.0500, 9.5250, 10.0, 15.0, None, _SOURCE_2SRC),
    _rec("WR-90", 22.8600, 10.1600, 8.2, 12.4, "UG-39/U", _SOURCE_3SRC),
    _rec("WR-112", 28.4988, 12.6238, 7.05, 10.0, "UG-51/U", _SOURCE_3SRC),
    _rec("WR-137", 34.8488, 15.7988, 5.85, 8.2, "UG-34/U", _SOURCE_3SRC),
    _rec("WR-187", 47.5488, 22.1488, 3.95, 5.85, "UG-148/U", _SOURCE_3SRC),
    _rec("WR-284", 72.1360, 34.0360, 2.6, 3.95, "UG-53/U", _SOURCE_3SRC),
    _rec("WR-340", 86.3600, 43.1800, 2.2, 3.3, None, _SOURCE_2SRC),
    _rec("WR-430", 109.2200, 54.6100, 1.7, 2.6, None, _SOURCE_2SRC),
    _rec("WR-650", 165.1000, 82.5500, 1.12, 1.72, None, _SOURCE_2SRC),
)

assert len(WR_TABLE) >= 26, "ME-4 种子 17 行 + TH-1 扩容 9 行：主流行不少于 26 行"


def _norm_wr_name(name: str) -> str:
    """WR 型号归一：去空白/连字符/下划线并大写（"wr-90"/"WR_90"/"wr 90" 均归 "WR90"）。"""
    return name.strip().upper().replace("-", "").replace(" ", "").replace("_", "")


_WR_INDEX: dict[str, WRRecord] = {_norm_wr_name(r.wr_name): r for r in WR_TABLE}


def wr_lookup(name: str) -> WRRecord:
    """按型号查 WR 记录（大小写不敏感 + WR 前缀容错）；未知名 KeyError。"""
    if not isinstance(name, str):
        raise KeyError(f"WR 型号必须为字符串，得到 {type(name).__name__}")
    key = _norm_wr_name(name)
    if key not in _WR_INDEX and key.isdigit():
        key = "WR" + key  # 纯数字入参按缺 WR 前缀解析（"90" → "WR90"）
    try:
        return _WR_INDEX[key]
    except KeyError:
        available = ", ".join(r.wr_name for r in WR_TABLE)
        raise KeyError(f"未知 WR 型号 {name!r}；可用型号：{available}") from None


def wr_from_frequency(f_ghz: float) -> tuple[WRRecord, ...] | None:
    """按频率查推荐带命中的 WR 记录。

    闭区间 [f_start, f_end] 含端点；教科书推荐带存在重叠（如 8.2–10 GHz
    同落 WR-112 与 WR-90），命中多行按表序显式并列返回；带外返回 None。
    """
    _reject_non_positive_finite(f_ghz, "f_ghz")
    hits = tuple(r for r in WR_TABLE if r.f_start_ghz <= f_ghz <= r.f_end_ghz)
    return hits or None  # 空元组即"带外"，统一返回 None（语义显式，非 #117 游离字典场景）


@dataclass(frozen=True)
class WRBandEntry:
    """与 core/bands.py BandEntry 字段同构的 WR 推荐带适配条目。

    字段名与 to_dict 键集和 BandEntry 逐一对齐（单测钉住结构同构）；
    kind 用字符串 "waveguide" 扩值——BandKind 四值均不适用于物理波导
    推荐带，bands.py 只读不改（ME-4 禁改清单）。
    """

    key: str
    standard: str
    name: str
    f_low_ghz: float
    f_high_ghz: float
    region: str = "global"
    kind: str = "waveguide"
    notes: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为与 BandEntry.to_dict 同键集的字典。"""
        return {
            "key": self.key,
            "standard": self.standard,
            "name": self.name,
            "f_low_ghz": self.f_low_ghz,
            "f_high_ghz": self.f_high_ghz,
            "region": self.region,
            "kind": self.kind,
            "notes": self.notes,
            "source": self.source,
        }


def wr_bands() -> tuple[WRBandEntry, ...]:
    """全表 WR 推荐带 → BandEntry 同构适配序列（只读消费，不注册进 bands 注册表）。"""
    return tuple(
        WRBandEntry(
            key=f"{_norm_wr_name(r.wr_name).lower()}_waveguide",
            standard="EIA WR 矩形波导标准尺寸系（IEC 60153-2 系）",
            name=f"{r.wr_name} 推荐工作带 {r.f_start_ghz:g}-{r.f_end_ghz:g} GHz",
            f_low_ghz=r.f_start_ghz,
            f_high_ghz=r.f_end_ghz,
            region="global",
            kind="waveguide",
            notes=(
                f"TE10 截止 {r.fc10_ghz:.4f} GHz；物理波导标准推荐带（非监管频段）"
                + (f"；法兰 {r.flange_ug}" if r.flange_ug else "")
            ),
            source=r.source,
        )
        for r in WR_TABLE
    )


__all__ = [
    "C0",
    "WR_TABLE",
    "WRBandEntry",
    "WRRecord",
    "cutoff_te10",
    "wavelength_g",
    "wr_bands",
    "wr_from_frequency",
    "wr_lookup",
]
