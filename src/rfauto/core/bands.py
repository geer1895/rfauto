"""D9 标准频段/法规掩模注册表。

3GPP/Wi-Fi/UWB/ISM 频段预设 + EMC 限值线（CISPR/FCC）作为一等可查对象，
喂 SpecEvaluator objectives 的 band 字段（[f_low, f_high] GHz，core/objectives.py）
与优化 bounds。本表是标准常量数据（非计算产物），每条带出处
（标准号+版本），数值以公开标准文本为准——不确定的数值宁可不上表。

kind 语义：
    licensed = 持牌/受保护业务划分（3GPP NR、RNSS）
    ism      = ITU-R RR 5.150/5.138 指定的 ISM 频段
    srd      = 免执照短距/超宽带规则（FCC Part 15、CEPT ERC 70-03）
    emc      = EMC 辐射发射限值线（非工作频段；f_low/f_high 为限值段，
               限值数值与检波器/距离在 notes）

region 语义：global（国际统一）/ eu / us / cn（区域监管口径）。

本模块另含**环境包络注册表**（温度/试验等级一等对象，
ENVIRONMENTS）。它与频段表严格分离，把"温区"变成确定性可查对象，并给出
"温区 → ΔT 上下限"的确定性转换（env_to_delta_t / env_to_uq_axis），供
温区扫描、UQ、良率分析把温度作为维度消费。数值出处逐条写入
_ENV_SEED 上方注释与条目 source；不确定的数值不上表。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BandKind(str, Enum):
    """频段种类（见模块 docstring 语义）。"""
    LICENSED = "licensed"
    ISM = "ism"
    SRD = "srd"
    EMC = "emc"


@dataclass(frozen=True)
class BandEntry:
    """单个频段/限值线条目。

    Attributes:
        key: 注册表唯一键（snake_case，如 "gpp_n78"）
        standard: 标准号（如 "3GPP TS 38.101-1"）
        name: 人类可读名称
        f_low_ghz: 频段下端（GHz）
        f_high_ghz: 频段上端（GHz）
        region: 适用区域（global/eu/us/cn…）
        kind: 频段种类（BandKind）
        notes: 备注（EMC 条目在此携带限值数值/检波器/测量距离）
        source: 出处（标准号+表号/条款，必填）
    """
    key: str
    standard: str
    name: str
    f_low_ghz: float
    f_high_ghz: float
    region: str = "global"
    kind: BandKind = BandKind.LICENSED
    notes: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "key": self.key,
            "standard": self.standard,
            "name": self.name,
            "f_low_ghz": self.f_low_ghz,
            "f_high_ghz": self.f_high_ghz,
            "region": self.region,
            "kind": self.kind.value,
            "notes": self.notes,
            "source": self.source,
        }


# 种子注册表（D9，2026-09-09）。数值出处逐条标注；不确定的数值不上表。
# EMC 限值线拆成逐段条目（限值分段跳变无法用单条 [lo, hi] 表达）。
_BAND_SEED: tuple[BandEntry, ...] = (
    # ── EMC 辐射发射限值线（kind=emc，限值在 notes）───────────────────────────
    BandEntry(
        key="cispr32_classb_rad_30m_230m",
        standard="CISPR 32:2015",
        name="CISPR 32 Class B 辐射发射限值（30–230 MHz）",
        f_low_ghz=0.030, f_high_ghz=0.230,
        region="global", kind=BandKind.EMC,
        notes="限值 40 dBμV/m@3m，QP 检波（Table A.4）",
        source="CISPR 32:2015 Table A.4（Class B，≤1 GHz，3 m）",
    ),
    BandEntry(
        key="cispr32_classb_rad_230m_1g",
        standard="CISPR 32:2015",
        name="CISPR 32 Class B 辐射发射限值（230 MHz–1 GHz）",
        f_low_ghz=0.230, f_high_ghz=1.000,
        region="global", kind=BandKind.EMC,
        notes="限值 47 dBμV/m@3m，QP 检波（Table A.4）",
        source="CISPR 32:2015 Table A.4（Class B，≤1 GHz，3 m）",
    ),
    BandEntry(
        key="fcc15b_rad_30m_88m",
        standard="47 CFR Part 15",
        name="FCC Part 15 Class B 辐射发射限值（30–88 MHz）",
        f_low_ghz=0.030, f_high_ghz=0.088,
        region="us", kind=BandKind.EMC,
        notes="限值 40 dBμV/m@3m（100 μV/m），QP 检波",
        source="47 CFR §15.109(b)（Class B，3 m）",
    ),
    BandEntry(
        key="fcc15b_rad_88m_216m",
        standard="47 CFR Part 15",
        name="FCC Part 15 Class B 辐射发射限值（88–216 MHz）",
        f_low_ghz=0.088, f_high_ghz=0.216,
        region="us", kind=BandKind.EMC,
        notes="限值 43.5 dBμV/m@3m（150 μV/m），QP 检波",
        source="47 CFR §15.109(b)（Class B，3 m）",
    ),
    BandEntry(
        key="fcc15b_rad_216m_960m",
        standard="47 CFR Part 15",
        name="FCC Part 15 Class B 辐射发射限值（216–960 MHz）",
        f_low_ghz=0.216, f_high_ghz=0.960,
        region="us", kind=BandKind.EMC,
        notes="限值 46 dBμV/m@3m（200 μV/m），QP 检波",
        source="47 CFR §15.109(b)（Class B，3 m）",
    ),
    BandEntry(
        key="fcc15b_rad_above_960m",
        standard="47 CFR Part 15",
        name="FCC Part 15 Class B 辐射发射限值（960 MHz 以上）",
        f_low_ghz=0.960, f_high_ghz=6.000,
        region="us", kind=BandKind.EMC,
        notes="限值 54 dBμV/m@3m（500 μV/m），avg 检波；6 GHz 上界取 "
              "§15.33(a) 对数字电路的测量范围上限惯例",
        source="47 CFR §15.109(b)（above 960 MHz 行）+ §15.33(a)（测量范围）",
    ),
    # ── ISM（ITU-R 无线电规则指定）──────────────────────────────────────────
    BandEntry(
        key="ism_13m56",
        standard="ITU-R RR",
        name="ISM 13.56 MHz（NFC/RFID）",
        f_low_ghz=0.013553, f_high_ghz=0.013567,
        region="global", kind=BandKind.ISM,
        notes="13.553–13.567 MHz，工科医（ISM）指定频段",
        source="ITU-R Radio Regulations No. 5.150",
    ),
    BandEntry(
        key="ism_433m",
        standard="ITU-R RR",
        name="ISM 433 MHz（短距遥测/遥控）",
        f_low_ghz=0.43305, f_high_ghz=0.43479,
        region="eu", kind=BandKind.ISM,
        notes="433.05–434.79 MHz，ITU 第 1 区 ISM 设备指定（Region 1）",
        source="ITU-R Radio Regulations No. 5.138（Region 1）",
    ),
    BandEntry(
        key="ism_915m_us",
        standard="ITU-R RR / 47 CFR",
        name="ISM 915 MHz（Region 2）",
        f_low_ghz=0.902, f_high_ghz=0.928,
        region="us", kind=BandKind.ISM,
        notes="902–928 MHz，ITU 第 2 区 ISM 指定；免执照跳频/数字调制走 §15.247",
        source="ITU-R Radio Regulations No. 5.150（Region 2）；47 CFR §15.247(a)(1)",
    ),
    BandEntry(
        key="ism_2g4",
        standard="ITU-R RR",
        name="ISM 2.4 GHz",
        f_low_ghz=2.400, f_high_ghz=2.500,
        region="global", kind=BandKind.ISM,
        notes="2400–2500 MHz 全球 ISM 指定（Wi-Fi/BLE/Zigbee 共存主战场）",
        source="ITU-R Radio Regulations No. 5.150",
    ),
    BandEntry(
        key="ism_5g8",
        standard="ITU-R RR",
        name="ISM 5.8 GHz",
        f_low_ghz=5.725, f_high_ghz=5.875,
        region="global", kind=BandKind.ISM,
        notes="5725–5875 MHz 全球 ISM 指定（与 U-NII-3/DSRC 部分重叠）",
        source="ITU-R Radio Regulations No. 5.150",
    ),
    # ── 免执照短距/宽带（SRD / Part 15）────────────────────────────────────
    BandEntry(
        key="srd_868m_eu",
        standard="ERC Rec. 70-03",
        name="EU SRD 868 MHz",
        f_low_ghz=0.863, f_high_ghz=0.870,
        region="eu", kind=BandKind.SRD,
        notes="863–870 MHz CEPT 短距设备（SRD）通用频段，子带功率/占空比各异",
        source="CEPT ERC Recommendation 70-03 Annex 1；EC Decision 2006/771/EC",
    ),
    BandEntry(
        key="wifi_2g4",
        standard="IEEE 802.11 / 47 CFR",
        name="Wi-Fi 2.4 GHz（11b/g/n/ax）",
        f_low_ghz=2.400, f_high_ghz=2.4835,
        region="global", kind=BandKind.SRD,
        notes="免执照运行于 2400–2483.5 MHz（信道 1–13 覆盖内）",
        source="47 CFR §15.247(a)(2)；IEEE 802.11-2020 2.4 GHz PHY",
    ),
    BandEntry(
        key="wifi_unii1",
        standard="47 CFR Part 15",
        name="Wi-Fi 5 GHz U-NII-1",
        f_low_ghz=5.150, f_high_ghz=5.250,
        region="us", kind=BandKind.SRD,
        notes="5150–5250 MHz（室内）",
        source="47 CFR §15.407(a)（U-NII-1）",
    ),
    BandEntry(
        key="wifi_unii2a",
        standard="47 CFR Part 15",
        name="Wi-Fi 5 GHz U-NII-2A",
        f_low_ghz=5.250, f_high_ghz=5.350,
        region="us", kind=BandKind.SRD,
        notes="5250–5350 MHz（DFS 雷达检测要求）",
        source="47 CFR §15.407(a)（U-NII-2A）",
    ),
    BandEntry(
        key="wifi_unii2c",
        standard="47 CFR Part 15",
        name="Wi-Fi 5 GHz U-NII-2C",
        f_low_ghz=5.470, f_high_ghz=5.725,
        region="us", kind=BandKind.SRD,
        notes="5470–5725 MHz（DFS/TPC 要求）",
        source="47 CFR §15.407(a)（U-NII-2C）",
    ),
    BandEntry(
        key="wifi_unii3",
        standard="47 CFR Part 15",
        name="Wi-Fi 5 GHz U-NII-3 / ISM 5.8 重叠",
        f_low_ghz=5.725, f_high_ghz=5.850,
        region="us", kind=BandKind.SRD,
        notes="5725–5850 MHz（与 ISM 5.8 GHz 重叠段）",
        source="47 CFR §15.407(a)（U-NII-3）；§15.247(a)(2)",
    ),
    BandEntry(
        key="wifi6e_us",
        standard="47 CFR Part 15",
        name="Wi-Fi 6E（US 6 GHz，U-NII-5..8）",
        f_low_ghz=5.925, f_high_ghz=7.125,
        region="us", kind=BandKind.SRD,
        notes="5925–7125 MHz，FCC 2020 年 6 GHz 决议（标准功率/室内低功率双规）",
        source="47 CFR §15.407(a)（U-NII-5 至 U-NII-8）；FCC 20-51 R&O",
    ),
    BandEntry(
        key="wifi6e_eu",
        standard="EC Decision (EU) 2021/1067",
        name="Wi-Fi 6E（EU lower 6 GHz，WAS/RLAN）",
        f_low_ghz=5.945, f_high_ghz=6.425,
        region="eu", kind=BandKind.SRD,
        notes="5945–6425 MHz（欧盟仅开放 lower 6 GHz），室内/户外 25 dBm 参考限",
        source="EC Decision (EU) 2021/1067；CEPT Rec. (23)01",
    ),
    BandEntry(
        key="uwb_fcc",
        standard="47 CFR Part 15 Subpart F",
        name="UWB 超宽带（FCC 掩模核心频段）",
        f_low_ghz=3.100, f_high_ghz=10.600,
        region="us", kind=BandKind.SRD,
        notes="3.1–10.6 GHz 内 EIRP ≤ −41.3 dBm/MHz（通用掩模平台段）",
        source="47 CFR §15.503(a)（UWB 定义）；§15.505(a)（−41.3 dBm/MHz）",
    ),
    # ── 持牌移动/受保护业务 ────────────────────────────────────────────────
    BandEntry(
        key="gpp_n41",
        standard="3GPP TS 38.101-1",
        name="5G NR n41（2.5 GHz）",
        f_low_ghz=2.496, f_high_ghz=2.696,
        region="global", kind=BandKind.LICENSED,
        notes="2496–2696 MHz（NR FR1）",
        source="3GPP TS 38.101-1 Table 5.2-1（NR operating bands）",
    ),
    BandEntry(
        key="gpp_n78",
        standard="3GPP TS 38.101-1",
        name="5G NR n78（3.5 GHz）",
        f_low_ghz=3.300, f_high_ghz=3.800,
        region="global", kind=BandKind.LICENSED,
        notes="3300–3800 MHz（NR FR1），全球 5G 主力子6G 频段",
        source="3GPP TS 38.101-1 Table 5.2-1（NR operating bands）",
    ),
    BandEntry(
        key="gpp_n79",
        standard="3GPP TS 38.101-1",
        name="5G NR n79（4.8 GHz）",
        f_low_ghz=4.400, f_high_ghz=5.000,
        region="global", kind=BandKind.LICENSED,
        notes="4400–5000 MHz（NR FR1），CN/JP 主用",
        source="3GPP TS 38.101-1 Table 5.2-1（NR operating bands）",
    ),
    BandEntry(
        key="cn_5g_3g3_3g6",
        standard="工信部 5G 频段批复（2017）",
        name="中国 5G 3.3–3.6 GHz",
        f_low_ghz=3.300, f_high_ghz=3.600,
        region="cn", kind=BandKind.LICENSED,
        notes="3300–3600 MHz 用于 5G 系统（与 n78 重叠；3300–3400 侧重室内）",
        source="工业和信息化部《关于第五代移动通信系统使用 3300-3600MHz 和 "
              "4800-5000MHz 频段的批复》（2017）",
    ),
    BandEntry(
        key="gnss_l1",
        standard="ITU-R RR",
        name="GNSS L1（RNSS 受保护频段）",
        f_low_ghz=1.559, f_high_ghz=1.610,
        region="global", kind=BandKind.LICENSED,
        notes="1559–1610 MHz RNSS/ARNS 划分；GPS L1 中心 1575.42 MHz，"
              "BDS B1/BDS-3 1561.098 MHz，Galileo E1 1575.42 MHz",
        source="ITU-R Radio Regulations Article 5（1559–1610 MHz RNSS 划分，"
              "No. 5.443B 相关）",
    ),
)


def _build_registry(seed: tuple[BandEntry, ...]) -> dict[str, BandEntry]:
    """构建注册表并做导入期一致性校验（数据写错立即暴露，fail fast）。"""
    registry: dict[str, BandEntry] = {}
    issues: list[str] = []
    for e in seed:
        if e.key in registry:
            issues.append(f"重名 key: {e.key}")
            continue
        if not (e.f_low_ghz < e.f_high_ghz):
            issues.append(f"{e.key}: f_low({e.f_low_ghz}) >= f_high({e.f_high_ghz})")
        if not e.source:
            issues.append(f"{e.key}: source 为空（D9 要求逐条出处）")
        if not e.standard or not e.name:
            issues.append(f"{e.key}: standard/name 为空")
        if not isinstance(e.kind, BandKind):
            issues.append(f"{e.key}: kind 非法（{e.kind!r}）")
        registry[e.key] = e
    if issues:
        raise RuntimeError(f"频段注册表种子数据不一致: {issues}")
    return registry


BANDS: dict[str, BandEntry] = _build_registry(_BAND_SEED)


def band_keys() -> list[str]:
    """全部注册键（注册顺序）。"""
    return list(BANDS.keys())


def get_band(key: str) -> BandEntry:
    """按键取频段条目。未知 key → KeyError（带可用键列表）。"""
    key = str(key)
    if key not in BANDS:
        raise KeyError(f"未知频段: {key}，可用: {band_keys()}")
    return BANDS[key]


def find_bands(freq_ghz: float) -> list[BandEntry]:
    """包含给定频率的全部条目（两端闭区间，注册顺序）。

    频率单位 GHz；非正数/非有限值显式报错（0 GHz 无物理意义）。
    """
    freq_ghz = float(freq_ghz)
    if not (freq_ghz > 0.0) or freq_ghz == float("inf"):
        raise ValueError(f"freq_ghz 必须为正有限数，收到: {freq_ghz}")
    return [e for e in BANDS.values() if e.f_low_ghz <= freq_ghz <= e.f_high_ghz]


def search(
    standard: str | None = None,
    kind: str | None = None,
    region: str | None = None,
) -> list[BandEntry]:
    """条件过滤（AND 语义）。

    standard: 大小写不敏感子串匹配（如 "38.101"、"CISPR"）
    kind:     BandKind 值精确匹配（大小写不敏感，如 "emc"）
    region:   region 精确匹配（大小写不敏感，如 "cn"）
    全部 None → 全表。
    """
    kind_val: str | None = None
    if kind is not None:
        k = str(kind).lower()
        if k not in [m.value for m in BandKind]:
            raise ValueError(f"未知 kind: {kind}，合法值: {[m.value for m in BandKind]}")
        kind_val = k
    std = str(standard).lower() if standard is not None else None
    reg = str(region).lower() if region is not None else None
    out: list[BandEntry] = []
    for e in BANDS.values():
        if std is not None and std not in e.standard.lower():
            continue
        if kind_val is not None and e.kind.value != kind_val:
            continue
        if reg is not None and e.region.lower() != reg:
            continue
        out.append(e)
    return out


def to_spec_bounds(key: str) -> dict[str, list[float]]:
    """频段条目 → SpecEvaluator Objective.band 字段结构（{"band": [lo, hi]} GHz）。

    用法（平铺进 objectives）：
        bounds = to_spec_bounds("gpp_n78")     # {"band": [3.3, 3.8]}
        Objective(metric="s11_db_min", band=bounds["band"], op=..., value=...)
    """
    e = get_band(key)
    return {"band": [e.f_low_ghz, e.f_high_ghz]}


def validate_registry() -> list[str]:
    """注册表完整性体检（单测/服务自检用）。空列表 = 合格。"""
    issues: list[str] = []
    seen: set[str] = set()
    for e in BANDS.values():
        if e.key in seen:
            issues.append(f"重名 key: {e.key}")
        seen.add(e.key)
        if not (e.f_low_ghz < e.f_high_ghz):
            issues.append(f"{e.key}: f_low >= f_high")
        if not e.source:
            issues.append(f"{e.key}: source 为空")
        if not e.standard or not e.name:
            issues.append(f"{e.key}: standard/name 为空")
        if not isinstance(e.kind, BandKind):
            issues.append(f"{e.key}: kind 非法")
    return issues


# ── D9 环境包络注册表（温度/试验等级一等对象）────────────────────────────────
# 与频段表严格分离（独立 registry），不改变 BANDS 计数与 SpecEvaluator band
# 掩模语义。每条包络给出工作温区 [t_min_c, t_max_c]（°C）与参考温度 t_ref_c
# （ΔT 转换基准，默认 25 °C 室温），供温区扫描 / UQ / 良率分析把
# "温区"作为确定性维度消费：
#     ΔT ∈ [t_min_c − t_ref_c, t_max_c − t_ref_c]
#
# 数值出处（标准文本/等同采用文本，不编造）：
# - AEC-Q100（Automotive Electronics Council）现行版定义 Grade 0–3 四档环境
#   工作温度范围：Grade 0 −40/+150、Grade 1 −40/+125、Grade 2 −40/+105、
#   Grade 3 −40/+85 °C（powertrain/engine 等最恶劣车载场景用 Grade 0）。
# - ECSS-Q-ST-60-13C Rev.1 DIR1（2021-05-17）：
#   §4.2.2.6d/§5.2.2.6d/§6.2.2.6d 商用 EEE 元件运行温区 ≥ (−40/+85) °C；
#   §4.2.2.6e 等 商用陶瓷电容温区 ≥ (−40/+125) °C；
#   Annex 试验流程 step 7 温度循环 500 T/C −55°/+125 °C。
# - IEC 60068-2-1:2007 试验 A（低温）严酷等级集合
#   {−65, −55, −40, −25, −10, −5, +5} °C；
#   IEC 60068-2-2:2007 试验 B（高温）严酷等级集合
#   {+30, +35, +40, +45, +50, +55, +60, +65, +70, +85, +100, +125, +155,
#    +175, +200, +250, +315, +400, +500, +630, +800, +1000} °C。
#   （GB/T 2423.1-2008 / GB/T 2423.2-2008 等同采用 IEC，等级集合一致。）
# - 工业级 −40/+85 °C：工业元件通用工作温区惯例；ECSS-Q-ST-60-13C 对商用
#   EEE 元件规定同一数值。
# ─────────────────────────────────────────────────────────────────────────────


class EnvKind(str, Enum):
    """环境包络种类（见上方出处注释）。"""

    INDUSTRIAL = "industrial"   # 工业级元件通用工作温区
    AUTOMOTIVE = "automotive"   # AEC-Q100 车规温度等级
    SPACE = "space"             # ECSS 航天 EEE 元件温区
    TEST = "test"               # IEC 60068 环境试验严酷等级集合


@dataclass(frozen=True)
class EnvEntry:
    """单个环境包络条目。

    Attributes:
        key: 注册表唯一键（snake_case，如 "aec_q100_grade1"）
        standard: 标准号（如 "AEC-Q100"）
        name: 人类可读名称
        kind: 包络种类（EnvKind）
        t_min_c: 温区下端（°C）
        t_max_c: 温区上端（°C）
        t_ref_c: ΔT 转换参考温度（°C，默认 25 °C 室温）
        severities_c: 标准给出的离散严酷等级（°C，仅 TEST 类非空；
            其 min/max 必须等于 t_min_c/t_max_c）
        notes: 备注
        source: 出处（标准号+条款/表号，必填）
    """

    key: str
    standard: str
    name: str
    kind: EnvKind
    t_min_c: float
    t_max_c: float
    t_ref_c: float = 25.0
    severities_c: tuple[float, ...] = ()
    notes: str = ""
    source: str = ""

    @property
    def span_c(self) -> float:
        """温区跨度 = t_max_c − t_min_c（°C/K 数值相同）。"""
        return self.t_max_c - self.t_min_c

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "key": self.key,
            "standard": self.standard,
            "name": self.name,
            "kind": self.kind.value,
            "t_min_c": self.t_min_c,
            "t_max_c": self.t_max_c,
            "t_ref_c": self.t_ref_c,
            "span_c": self.span_c,
            "severities_c": list(self.severities_c),
            "notes": self.notes,
            "source": self.source,
        }


_ENV_SEED: tuple[EnvEntry, ...] = (
    # ── 工业级 ──────────────────────────────────────────────────────────────
    EnvEntry(
        key="industrial_grade_40_85",
        standard="工业级（industrial grade）通用口径",
        name="工业级工作温区 −40…+85 °C",
        kind=EnvKind.INDUSTRIAL,
        t_min_c=-40.0, t_max_c=85.0,
        notes="工业元件通用工作温区惯例；ECSS-Q-ST-60-13C 对商用 EEE 元件 "
              "规定同一最低值 (−40/+85) °C",
        source="工业级通用口径；ECSS-Q-ST-60-13C Rev.1 DIR1 §4.2.2.6d",
    ),
    # ── AEC-Q100 车规温度等级 ───────────────────────────────────────────────
    EnvEntry(
        key="aec_q100_grade0",
        standard="AEC-Q100",
        name="AEC-Q100 Grade 0（−40…+150 °C）",
        kind=EnvKind.AUTOMOTIVE,
        t_min_c=-40.0, t_max_c=150.0,
        notes="最恶劣车载场景（powertrain/engine 控制等）",
        source="AEC-Q100 环境工作温度等级 Grade 0（现行版四档 0–3 之一）",
    ),
    EnvEntry(
        key="aec_q100_grade1",
        standard="AEC-Q100",
        name="AEC-Q100 Grade 1（−40…+125 °C）",
        kind=EnvKind.AUTOMOTIVE,
        t_min_c=-40.0, t_max_c=125.0,
        notes="车身/动力总成周边主流车规等级",
        source="AEC-Q100 环境工作温度等级 Grade 1（现行版四档 0–3 之一）",
    ),
    EnvEntry(
        key="aec_q100_grade2",
        standard="AEC-Q100",
        name="AEC-Q100 Grade 2（−40…+105 °C）",
        kind=EnvKind.AUTOMOTIVE,
        t_min_c=-40.0, t_max_c=105.0,
        notes="座舱/一般车载电子等级",
        source="AEC-Q100 环境工作温度等级 Grade 2（现行版四档 0–3 之一）",
    ),
    EnvEntry(
        key="aec_q100_grade3",
        standard="AEC-Q100",
        name="AEC-Q100 Grade 3（−40…+85 °C）",
        kind=EnvKind.AUTOMOTIVE,
        t_min_c=-40.0, t_max_c=85.0,
        notes="车载舱内温和环境等级（与工业级温区一致）",
        source="AEC-Q100 环境工作温度等级 Grade 3（现行版四档 0–3 之一）",
    ),
    # ── ECSS 航天 EEE 元件温区 ──────────────────────────────────────────────
    EnvEntry(
        key="ecss_commercial_eee_40_85",
        standard="ECSS-Q-ST-60-13C Rev.1 DIR1",
        name="ECSS 商用 EEE 元件运行温区下限（−40…+85 °C）",
        kind=EnvKind.SPACE,
        t_min_c=-40.0, t_max_c=85.0,
        notes="§4.2.2.6b 另要求厂商最大温区比应用温区至少高 10 °C",
        source="ECSS-Q-ST-60-13C Rev.1 DIR1 §4.2.2.6d/§5.2.2.6d/§6.2.2.6d"
               "（商用 EEE 元件运行温区 ≥ (−40/+85) °C）",
    ),
    EnvEntry(
        key="ecss_ceramic_capacitor_40_125",
        standard="ECSS-Q-ST-60-13C Rev.1 DIR1",
        name="ECSS 商用陶瓷电容温区下限（−40…+125 °C）",
        kind=EnvKind.SPACE,
        t_min_c=-40.0, t_max_c=125.0,
        notes="商用陶瓷电容的专门下限，高于通用商用元件",
        source="ECSS-Q-ST-60-13C Rev.1 DIR1 §4.2.2.6e/§5.2.2.6e/§6.2.2.6e"
               "（商用陶瓷电容温区 ≥ (−40/+125) °C）",
    ),
    EnvEntry(
        key="ecss_thermal_cycling_55_125",
        standard="ECSS-Q-ST-60-13C Rev.1 DIR1",
        name="ECSS 航天 EEE 温度循环温区（−55…+125 °C）",
        kind=EnvKind.SPACE,
        t_min_c=-55.0, t_max_c=125.0,
        notes="500 次温度循环；或厂商贮存温区取更严者",
        source="ECSS-Q-ST-60-13C Rev.1 DIR1 Annex 试验流程 step 7"
               "（500 T/C −55°/+125 °C，MIL-STD-750 method 1051 cond.B / "
               "MIL-STD-883 method 1010 cond.B）",
    ),
    # ── IEC 60068 环境试验严酷等级集合 ──────────────────────────────────────
    EnvEntry(
        key="iec60068_2_1_cold",
        standard="IEC 60068-2-1:2007",
        name="IEC 60068-2-1 试验 A：低温严酷等级集合（−65…+5 °C）",
        kind=EnvKind.TEST,
        t_min_c=-65.0, t_max_c=5.0,
        severities_c=(-65.0, -55.0, -40.0, -25.0, -10.0, -5.0, 5.0),
        notes="温区为该严酷等级集合的包络（非单一试验剖面）；"
              "持续时间 2/16/72/96 h，容差 ±3 K",
        source="IEC 60068-2-1:2007 试验 A 低温严酷等级"
               "（GB/T 2423.1-2008 等同采用）",
    ),
    EnvEntry(
        key="iec60068_2_2_dry_heat",
        standard="IEC 60068-2-2:2007",
        name="IEC 60068-2-2 试验 B：高温严酷等级集合（+30…+1000 °C）",
        kind=EnvKind.TEST,
        t_min_c=30.0, t_max_c=1000.0,
        severities_c=(30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0,
                      85.0, 100.0, 125.0, 155.0, 175.0, 200.0, 250.0, 315.0,
                      400.0, 500.0, 630.0, 800.0, 1000.0),
        notes="温区为该严酷等级集合的包络（非单一试验剖面）；"
              "持续时间 2/16/72/96/168/240/336/1000 h",
        source="IEC 60068-2-2:2007 试验 B 高温严酷等级"
               "（GB/T 2423.2-2008 等同采用）",
    ),
)


def _finite_temp(value: Any, name: str) -> float:
    """把温度类入参收敛为有限 float，非法即显式报错。"""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为有限数，收到: {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到: {value!r}")
    return out


def _build_env_registry(seed: tuple[EnvEntry, ...]) -> dict[str, EnvEntry]:
    """构建环境包络注册表并做导入期一致性校验（fail fast）。"""
    registry: dict[str, EnvEntry] = {}
    issues: list[str] = []
    for e in seed:
        if e.key in registry:
            issues.append(f"重名 key: {e.key}")
            continue
        if not (e.t_min_c < e.t_max_c):
            issues.append(f"{e.key}: t_min_c({e.t_min_c}) >= t_max_c({e.t_max_c})")
        if not math.isfinite(e.t_ref_c):
            issues.append(f"{e.key}: t_ref_c 非有限数")
        if not e.source:
            issues.append(f"{e.key}: source 为空（D9 要求逐条出处）")
        if not e.standard or not e.name:
            issues.append(f"{e.key}: standard/name 为空")
        if not isinstance(e.kind, EnvKind):
            issues.append(f"{e.key}: kind 非法（{e.kind!r}）")
        if e.severities_c:
            sev = tuple(float(s) for s in e.severities_c)
            if list(sev) != sorted(sev) or len(set(sev)) != len(sev):
                issues.append(f"{e.key}: severities_c 必须严格递增")
            elif (sev[0], sev[-1]) != (e.t_min_c, e.t_max_c):
                issues.append(
                    f"{e.key}: severities_c 端点与温区不一致"
                    f"（{sev[0]}/{sev[-1]} vs {e.t_min_c}/{e.t_max_c}）")
        registry[e.key] = e
    if issues:
        raise RuntimeError(f"环境包络注册表种子数据不一致: {issues}")
    return registry


ENVIRONMENTS: dict[str, EnvEntry] = _build_env_registry(_ENV_SEED)


def env_keys() -> list[str]:
    """全部环境包络键（注册顺序）。"""
    return list(ENVIRONMENTS.keys())


def get_env(key: str) -> EnvEntry:
    """按键取环境包络条目。未知 key → KeyError（带可用键列表）。"""
    key = str(key)
    if key not in ENVIRONMENTS:
        raise KeyError(f"未知环境包络: {key}，可用: {env_keys()}")
    return ENVIRONMENTS[key]


def find_envs(t_c: float) -> list[EnvEntry]:
    """温区包含给定温度的全部条目（两端闭区间，注册顺序）。

    温度单位 °C；非有限值显式报错。
    """
    t = _finite_temp(t_c, "t_c")
    return [e for e in ENVIRONMENTS.values() if e.t_min_c <= t <= e.t_max_c]


def search_env(standard: str | None = None,
               kind: str | None = None) -> list[EnvEntry]:
    """条件过滤（AND 语义）。

    standard: 大小写不敏感子串匹配（如 "AEC"、"ECSS"）
    kind:     EnvKind 值精确匹配（大小写不敏感，如 "automotive"）
    全部 None → 全表。
    """
    kind_val: str | None = None
    if kind is not None:
        k = str(kind).lower()
        if k not in [m.value for m in EnvKind]:
            raise ValueError(
                f"未知环境包络 kind: {kind}，合法值: {[m.value for m in EnvKind]}")
        kind_val = k
    std = str(standard).lower() if standard is not None else None
    out: list[EnvEntry] = []
    for e in ENVIRONMENTS.values():
        if std is not None and std not in e.standard.lower():
            continue
        if kind_val is not None and e.kind.value != kind_val:
            continue
        out.append(e)
    return out


def env_to_delta_t(key: str, t_ref_c: float | None = None) -> dict[str, Any]:
    """环境包络 → 相对参考温度的 ΔT 上下限（温区扫描/UQ/良率消费接口）。

    ΔT_min = t_min_c − t_ref_c，ΔT_max = t_max_c − t_ref_c（K/°C 数值相同）。
    t_ref_c=None 时用条目自身参考温度（默认 25 °C）；降温方向为负 ΔT。
    """
    e = get_env(key)
    ref = e.t_ref_c if t_ref_c is None else _finite_temp(t_ref_c, "t_ref_c")
    lo = e.t_min_c - ref
    hi = e.t_max_c - ref
    return {
        "key": e.key,
        "t_min_c": e.t_min_c,
        "t_max_c": e.t_max_c,
        "t_ref_c": ref,
        "delta_t_min_c": lo,
        "delta_t_max_c": hi,
        "delta_t_span_c": hi - lo,
    }


def env_delta_t_bounds(key: str, t_ref_c: float | None = None) -> tuple[float, float]:
    """(ΔT_min, ΔT_max) 元组便捷形式（供扫描/UQ 直接迭代）。"""
    d = env_to_delta_t(key, t_ref_c=t_ref_c)
    return (d["delta_t_min_c"], d["delta_t_max_c"])


def env_temperature_points(key: str, n: int = 5) -> list[float]:
    """温区等距采样点（含两端），供温区扫描的确定性网格。"""
    e = get_env(key)
    if isinstance(n, bool) or not isinstance(n, int):
        raise ValueError(f"n 必须为整数，收到: {n!r}")
    if n < 2:
        raise ValueError(f"n 必须 >=2，收到: {n}")
    lo, hi = e.t_min_c, e.t_max_c
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def env_to_uq_axis(key: str, t_ref_c: float | None = None,
                   k_sigma: float = 3.0) -> dict[str, Any]:
    """环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。

    项目公差惯例（optimization/tolerance.py）：公差半宽 = k_sigma·σ，默认 3σ。
    名义点取 t_ref_c；对称公差半径 = max(|ΔT_min|, |ΔT_max|)，即以名义点为中心的
    公差盒完整覆盖该环境包络（单侧可能略外扩，由调用方按需裁剪）。
    """
    k = _finite_temp(k_sigma, "k_sigma")
    if k <= 0.0:
        raise ValueError(f"k_sigma 必须 >0，收到: {k_sigma!r}")
    d = env_to_delta_t(key, t_ref_c=t_ref_c)
    radius = max(abs(d["delta_t_min_c"]), abs(d["delta_t_max_c"]))
    return {
        "key": d["key"],
        "param": "t_c",
        "nominal_c": d["t_ref_c"],
        "k_sigma": k,
        "half_range_c": radius,
        "sigma_c": radius / k,
        "delta_t_min_c": d["delta_t_min_c"],
        "delta_t_max_c": d["delta_t_max_c"],
    }


def validate_env_registry() -> list[str]:
    """环境包络注册表完整性体检（单测/服务自检用）。空列表 = 合格。"""
    issues: list[str] = []
    seen: set[str] = set()
    for e in ENVIRONMENTS.values():
        if e.key in seen:
            issues.append(f"重名 key: {e.key}")
        seen.add(e.key)
        if not (e.t_min_c < e.t_max_c):
            issues.append(f"{e.key}: t_min_c >= t_max_c")
        if not math.isfinite(e.t_ref_c):
            issues.append(f"{e.key}: t_ref_c 非有限数")
        if not e.source:
            issues.append(f"{e.key}: source 为空")
        if not e.standard or not e.name:
            issues.append(f"{e.key}: standard/name 为空")
        if not isinstance(e.kind, EnvKind):
            issues.append(f"{e.key}: kind 非法")
    return issues

