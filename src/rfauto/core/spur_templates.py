"""EM-6 杂散模板库：TS 138 104 V17.5.0 ACLR/ACS 数据面 + 杂散限值模板 + ACIR 合成式。

规格：研究扩充 round17 §四 EM-6——"C/I 与
IM=C/(N+I) 闭式 + ACIR 合成 + 杂散模板库（ETSI TS 38 104 免费 PDF 表数字化）"；
PV-012 已 verified（引用口径 = TS 138 104 §6.6.3 + §7.4.1 合成）。

数据面（每值带条款号 source_id；全部自 ETSI 免费版 PDF 逐位实测录入，
2026-10-02 下载，证据链 runs/em6/EM6_EVIDENCE.md）：

- ETSI TS 138 104 V17.5.0 (2022-04) §6.6.3.2：ACLR 相对限值
  （Table 6.6.3.2-1 standard 域 NR/E-UTRA 1st/2nd 相邻道均 45 dB；
  Table 6.6.3.2-1a n46/n96/n102 域 35/40 dB）、ACLR 绝对基本限值
  （Table 6.6.3.2-2：Cat A WA −13 / Cat B WA −15 / MR −25 / LA −32
  dBm/MHz）、CACLR（Table 6.6.3.2-3 / -3aa / -3a 同构）。
- ETSI TS 138 104 V17.5.0 §7.4.1.2：ACS 要求（Table 7.4.1.2-1：wanted=
  PREFSENS+6 dB，干扰限值 WA −52 / MR −47 / LA −44 dBm；Table 7.4.1.2-1a
  n46/n96/n102 域无 WA 行如实收窄）、ACS 干扰频偏（Table 7.4.1.2-2 及
  n46/n96/n102 表——正文两表同编号 "Table 7.4.1.2-2"，按原文如实记录）。
- ACIR 合成式出处：ETSI TR 136 942 V17.0.0 §8.1（免费 PDF 实测）：
  ACIR = 1/(1/ACLR + 1/ACS)（线性功率比）；ACIR 语义补充定义
  ETSI TR 125 942 V17.0.0 §5.1.1.3。
- 「whichever is less stringent」合并语义：TS 138 104 §6.6.3.3 原文 +
  3GPP TS 38.141-1 V18.1.0 §6.6.3.5.3 conformance 佐证（"Conformance
  can be shown by meeting the ACLR limit ... or the absolute basic
  limits ..., whichever is less stringent"）——即相邻道泄漏 ≤ max(
  相对限值, 绝对限值) 即合规（满足任一较宽松者即合规）。

模板面：
- spur_template_check(spurs, standard, carrier)：杂散列表 (f, level) 对
  TS 138 104 相邻道 ACLR 限值逐条评估 → margin 表。区域判定按载波中心
  频偏（assigned ≤ BW/2；1st/2nd 相邻道至 5·BW/2；更远=杂散域
  §6.6.5——不在本批数据面，如实 out_of_scope 不判）。
- acir_synthesize(aclr_db, acs_db)：TR 136 942 §8.1 合成式。
- bs_acs_db(standard, bs_class, prefsens_dbm)：由 §7.4.1.2 表列
  （wanted=PREFSENS+6, 干扰限值）导出的等效 ACS 比值（dB）——
  I_max − (REFSENS+6)；PREFSENS 由调用方按 §7.2.2 提供（不在本批数据面）。
- carrier_to_interference_db / c_over_n_plus_i_db：C/I 与 IM=C/(N+I) 闭式
  （round17 EM-6 原文口径；dB 域）。

与邻接面的关系声明：
- 与 EM-10（core/limits_registry）：**独立 schema，不填 reserved 键位**。
  ACLR/ACS 是"载波相对（dB）+等级相对（按 BS class 分层）"语义，不是
  LimitLine 频段×检波×绝对场强带线——limits_registry 的
  em6_ts138104_aclr/acs 预留键位保持 status="reserved"（其注记指向本
  模块为数据面所有者）；本模块零 import limits_registry（分层各自独立，
  消费方可同时查两边）。
- 与 cascade.spur_search：**互补不重复**——spur_search 是混频杂散频率
  几何搜索（纯 m·f_RF±n·f_LO 枚举、不报电平）；本模块是"电平 vs 标准
  限值"的逐条评估（spur_search 的落带产物可交本模块评 margin）。
- dpd_static 明示"ACPR/ACLR 精确预测需非线性仿真、本内核不产数字"
  （铁律 7）——本模块同样**只做限值评估与闭式合成，不预测发射机 ACLR**；
  spur 电平是测量/调用方输入。

铁律 7：全部数值由确定性闭式内核产出（本模块零随机、零 IO、零网络）；
每值溯源 source_id 见各 dataclass。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "ABSOLUTE_BS_CLASSES",
    "ACIR_FORMULA_SOURCE",
    "ACLR_ABSOLUTE",
    "ACLR_RELATIVE",
    "ACS_BS_CLASSES",
    "ACS_INTERFERER",
    "ACS_OFFSETS",
    "BW_CHANNEL_MHZ",
    "CACLR_ABSOLUTE",
    "CACLR_RELATIVE",
    "PROVENANCE",
    "STANDARD_TOKENS",
    "AbsolutePsdLimit",
    "AclrRelativeLimit",
    "AcsInterfererLimit",
    "AcsOffset",
    "absolute_psd_limit",
    "acir_synthesize",
    "aclr_relative_limit",
    "acs_interferer_limit",
    "acs_offset_for_bw",
    "bs_acs_db",
    "c_over_n_plus_i_db",
    "carrier_to_interference_db",
    "resolve_standard",
    "spur_template_check",
]

# ─── standard token 与出处 ────────────────────────────────────────────────────

#: 数据面唯一录入版本（免测版 PDF 实测；runs/em6/ 留档）。
STANDARD_TOKENS = ("ts138104_v17_5_0",)

#: 回溯出处（检索方式/日期/证据文件——PROVENANCE["evidence"] 相对 runs/em6）。
PROVENANCE: dict[str, object] = {
    "standard": "ETSI TS 138 104 V17.5.0 (2022-04) = 3GPP TS 38.104 v17.5.0 Release 17",
    "retrieved": "2026-10-02",
    "url": "https://www.etsi.org/deliver/etsi_ts/138100_138199/138104/17.05.00_60/"
           "ts_138104v170500p.pdf",
    "evidence": "runs/em6/EM6_EVIDENCE.md",
}

#: ACIR 合成式出处（TR 136 942 §8.1 实测原文：ACIR = 1/(1/ACLR + 1/ACS)）。
ACIR_FORMULA_SOURCE = (
    "ETSI TR 136 942 V17.0.0 §8.1（ACIR = 1/(1/ACLR + 1/ACS)，线性功率比；"
    "3GPP TR 36.942 免费 PDF 实测，runs/em6/tr_136942.pdf）；ACIR 语义补充 "
    "ETSI TR 125 942 V17.0.0 §5.1.1.3"
)

_STANDARD_ALIASES: dict[str, str] = {
    "ts138104_v17_5_0": "ts138104_v17_5_0",
    "ts138104": "ts138104_v17_5_0",
    "ts_138_104": "ts138104_v17_5_0",
    "etsi_ts_138_104": "ts138104_v17_5_0",
    "3gpp_ts_38_104": "ts138104_v17_5_0",
    "ts_38_104": "ts138104_v17_5_0",
    "38_104": "ts138104_v17_5_0",
    "ts38104_v17.5.0": "ts138104_v17_5_0",
}

_BAND_SCOPES = ("standard", "n46_n96_n102")

#: Table 6.6.3.2-1 / -1a 首列：BS 信道带宽枚举（MHz，按 band scope）。
BW_CHANNEL_MHZ: dict[str, tuple[float, ...]] = {
    "standard": (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0,
                 60.0, 70.0, 80.0, 90.0, 100.0),
    "n46_n96_n102": (10.0, 20.0, 40.0, 60.0, 80.0),
}

_ABS_ADJACENT = ("first", "second")

# ─── 数据面：ACLR/CACLR 相对限值（§6.6.3.2）──────────────────────────────────


@dataclass(frozen=True)
class AclrRelativeLimit:
    """单条相对限值（dB，相对载波/参考通道功率），逐条 source_id 溯源。

    Attributes:
        requirement: "aclr" | "caclr"（CACLR=子块/Inter RF Bandwidth 间隙
            内两侧载波累计口径；本模板面只消费 aclr，caclr 数据如实入库）。
        band_scope: "standard" | "n46_n96_n102"。
        adjacent: "first" | "second"（相邻道序）。
        assumed_adjacent: 假定相邻道载波（informative 列）。
        offset_rule: 相邻道中心频偏规则（相对最低/最高载波中心）。
        measurement_filter: 相邻道测量滤波器（方根滤波口径注记）。
        limit_db: 限值（dB，正值=ACLR 下限；允许泄漏功率=参考功率−limit_db）。
        source_id: 条款+表号+行溯源。
    """

    requirement: str
    band_scope: str
    adjacent: str
    assumed_adjacent: str
    offset_rule: str
    measurement_filter: str
    limit_db: float
    source_id: str
    notes: str = ""


_A = "ts138104_v17_5_0 §6.6.3.2"

ACLR_RELATIVE: tuple[AclrRelativeLimit, ...] = (
    AclrRelativeLimit(
        "aclr", "standard", "first", "NR of same BW", "bw_channel",
        "square (BWConfig)", 45.0,
        f"{_A} Table 6.6.3.2-1 row 1（NR 1st 相邻道）",
    ),
    AclrRelativeLimit(
        "aclr", "standard", "second", "NR of same BW", "2x_bw_channel",
        "square (BWConfig)", 45.0,
        f"{_A} Table 6.6.3.2-1 row 2（NR 2nd 相邻道）",
    ),
    AclrRelativeLimit(
        "aclr", "standard", "first", "5 MHz E-UTRA", "bw_channel/2+2.5mhz",
        "square (4.5 MHz)", 45.0,
        f"{_A} Table 6.6.3.2-1 row 3（E-UTRA 1st 相邻道；Note 3：band 同时"
        "定义 E-UTRA/UTRA 时适用）",
    ),
    AclrRelativeLimit(
        "aclr", "standard", "second", "5 MHz E-UTRA", "bw_channel/2+7.5mhz",
        "square (4.5 MHz)", 45.0,
        f"{_A} Table 6.6.3.2-1 row 4（E-UTRA 2nd 相邻道；Note 3 同上）",
    ),
    AclrRelativeLimit(
        "aclr", "n46_n96_n102", "first", "NR of same BW", "bw_channel",
        "square (BWConfig)", 35.0,
        f"{_A} Table 6.6.3.2-1a row 1（n46/n96/n102 NR 1st 相邻道）",
    ),
    AclrRelativeLimit(
        "aclr", "n46_n96_n102", "second", "NR of same BW", "2x_bw_channel",
        "square (BWConfig)", 40.0,
        f"{_A} Table 6.6.3.2-1a row 2（n46/n96/n102 NR 2nd 相邻道）",
    ),
)

_CACLR = "ts138104_v17_5_0 §6.6.3.2"

CACLR_RELATIVE: tuple[AclrRelativeLimit, ...] = (
    AclrRelativeLimit(
        "caclr", "standard", "first", "NR of same BW", "2.5mhz",
        "square (BWConfig)", 45.0,
        f"{_CACLR} Table 6.6.3.2-3 row 1（Wgap 条件：5≤Wgap<15 或 "
        "5≤Wgap<45，随对侧载波 BW）",
    ),
    AclrRelativeLimit(
        "caclr", "standard", "second", "NR of same BW", "7.5mhz",
        "square (BWConfig)", 45.0,
        f"{_CACLR} Table 6.6.3.2-3 row 2（Wgap 条件：10<Wgap<20 或 "
        "10≤Wgap<50，随对侧载波 BW）",
    ),
    AclrRelativeLimit(
        "caclr", "standard", "first", "NR of same BW", "10mhz",
        "square (BWConfig)", 45.0,
        f"{_CACLR} Table 6.6.3.2-3 row 3（25–100 MHz BW；20≤Wgap<60 或 "
        "20≤Wgap<30）",
    ),
    AclrRelativeLimit(
        "caclr", "standard", "second", "NR of same BW", "30mhz",
        "square (BWConfig)", 45.0,
        f"{_CACLR} Table 6.6.3.2-3 row 4（25–100 MHz BW；40<Wgap<80 或 "
        "40≤Wgap<50）",
    ),
    AclrRelativeLimit(
        "caclr", "n46_n96_n102", "first", "NR of same BW", "10mhz",
        "square (BWConfig)", 35.0,
        f"{_CACLR} Table 6.6.3.2-3aa row 1（n46/n96/n102；20≤Wgap<60）",
    ),
    AclrRelativeLimit(
        "caclr", "n46_n96_n102", "second", "NR of same BW", "30mhz",
        "square (BWConfig)", 40.0,
        f"{_CACLR} Table 6.6.3.2-3aa row 2（n46/n96/n102；40<Wgap<80）",
        "CACLR 作用于子块/Inter RF Bandwidth 间隙内（间隙场景需 gap 几何，"
        "本模板面不消费——如实入库供查询）",
    ),
)


@dataclass(frozen=True)
class AbsolutePsdLimit:
    """ACLR/CACLR 绝对基本限值（dBm/MHz，按 BS category/class 分层）。"""

    requirement: str  # "aclr" | "caclr"
    bs_class: str
    limit_dbm_per_mhz: float
    source_id: str


_ABS_BS = "BS category / BS class 分层"

ABSOLUTE_BS_CLASSES = ("cat_a_wide_area", "cat_b_wide_area", "medium_range",
                       "local_area")

_AABS = "ts138104_v17_5_0 §6.6.3.2"

ACLR_ABSOLUTE: tuple[AbsolutePsdLimit, ...] = (
    AbsolutePsdLimit("aclr", "cat_a_wide_area", -13.0,
                     f"{_AABS} Table 6.6.3.2-2 row 1（{_ABS_BS}）"),
    AbsolutePsdLimit("aclr", "cat_b_wide_area", -15.0,
                     f"{_AABS} Table 6.6.3.2-2 row 2（{_ABS_BS}）"),
    AbsolutePsdLimit("aclr", "medium_range", -25.0,
                     f"{_AABS} Table 6.6.3.2-2 row 3（{_ABS_BS}）"),
    AbsolutePsdLimit("aclr", "local_area", -32.0,
                     f"{_AABS} Table 6.6.3.2-2 row 4（{_ABS_BS}）"),
)

CACLR_ABSOLUTE: tuple[AbsolutePsdLimit, ...] = (
    AbsolutePsdLimit("caclr", "cat_a_wide_area", -13.0,
                     f"{_AABS} Table 6.6.3.2-3a row 1（{_ABS_BS}）"),
    AbsolutePsdLimit("caclr", "cat_b_wide_area", -15.0,
                     f"{_AABS} Table 6.6.3.2-3a row 2（{_ABS_BS}）"),
    AbsolutePsdLimit("caclr", "medium_range", -25.0,
                     f"{_AABS} Table 6.6.3.2-3a row 3（{_ABS_BS}）"),
    AbsolutePsdLimit("caclr", "local_area", -32.0,
                     f"{_AABS} Table 6.6.3.2-3a row 4（{_ABS_BS}）"),
)

# ─── 数据面：ACS（§7.4.1.2）──────────────────────────────────────────────────


@dataclass(frozen=True)
class AcsInterfererLimit:
    """单条 ACS 干扰限值（dBm，wanted=PREFSENS+6 dB 口径，§7.4.1.2）。"""

    band_scope: str
    bs_class: str
    interferer_dbm: float
    wanted_rule: str
    bw_channel_mhz: tuple[float, ...]
    source_id: str


ACS_BS_CLASSES = ("wide_area", "medium_range", "local_area")

_ACS_BW_STD = BW_CHANNEL_MHZ["standard"]
_ACS_BW_N46 = BW_CHANNEL_MHZ["n46_n96_n102"]

ACS_INTERFERER: tuple[AcsInterfererLimit, ...] = (
    AcsInterfererLimit(
        "standard", "wide_area", -52.0, "prefsens+6", _ACS_BW_STD,
        "ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-1（Wide Area BS 行）",
    ),
    AcsInterfererLimit(
        "standard", "medium_range", -47.0, "prefsens+6", _ACS_BW_STD,
        "ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-1（Medium Range BS 行）",
    ),
    AcsInterfererLimit(
        "standard", "local_area", -44.0, "prefsens+6", _ACS_BW_STD,
        "ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-1（Local Area BS 行）",
    ),
    AcsInterfererLimit(
        "n46_n96_n102", "medium_range", -47.0, "prefsens+6", _ACS_BW_N46,
        "ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-1a（Medium Range BS 行）",
    ),
    AcsInterfererLimit(
        "n46_n96_n102", "local_area", -44.0, "prefsens+6", _ACS_BW_N46,
        "ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-1a（Local Area BS 行；"
        "原表无 Wide Area 行，如实收窄）",
    ),
)


@dataclass(frozen=True)
class AcsOffset:
    """单条 ACS 干扰频偏（Table 7.4.1.2-2；双侧 ±，offset_mhz 取幅值）。"""

    band_scope: str
    bw_channel_mhz: float
    offset_mhz: float
    interferer_type: str
    source_id: str


_T5 = "5 MHz DFT-s-OFDM NR signal, 15 kHz SCS, 25 RBs"
_T20 = "20 MHz DFT-s-OFDM NR signal, 15 kHz SCS, 100 RBs"

#: §7.4.1.2 Table 7.4.1.2-2（standard 域 15 行；offset 幅值 MHz）。
_ACS_OFF_STD_VALUES: tuple[tuple[float, float], ...] = (
    (5.0, 2.5025), (10.0, 2.5075), (15.0, 2.5125), (20.0, 2.5025),
    (25.0, 9.4675), (30.0, 9.4725), (35.0, 9.4625), (40.0, 9.4675),
    (45.0, 9.4725), (50.0, 9.4625), (60.0, 9.4725), (70.0, 9.4675),
    (80.0, 9.4625), (90.0, 9.4725), (100.0, 9.4675),
)

#: §7.4.1.2 第二张 "Table 7.4.1.2-2"（band n46/n96/n102 表；正文两表同
#: 编号，按原文如实记录）。
_ACS_OFF_N46_VALUES: tuple[tuple[float, float], ...] = (
    (10.0, 9.4675), (20.0, 9.4625), (40.0, 9.4675), (60.0, 9.4725),
    (80.0, 9.4625),
)

ACS_OFFSETS: tuple[AcsOffset, ...] = tuple(
    AcsOffset(
        "standard", bw, off,
        _T5 if bw <= 20.0 else _T20,
        f"ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-2 row BW={bw:g} MHz",
    )
    for bw, off in _ACS_OFF_STD_VALUES
) + tuple(
    AcsOffset(
        "n46_n96_n102", bw, off, _T20,
        f"ts138104_v17_5_0 §7.4.1.2 Table 7.4.1.2-2（n46/n96/n102 表）"
        f" row BW={bw:g} MHz",
    )
    for bw, off in _ACS_OFF_N46_VALUES
)

# ─── 查询/守卫 ────────────────────────────────────────────────────────────────


def resolve_standard(standard: object) -> str:
    """standard token/别名 → canonical token；未知 → ValueError（负例契约）。"""
    if isinstance(standard, str):
        key = standard.strip().lower()
        if key in _STANDARD_ALIASES:
            return _STANDARD_ALIASES[key]
    raise ValueError(
        f"未知 standard {standard!r}（本模板库现只录入 "
        f"{'|'.join(STANDARD_TOKENS)}；别名 ts138104/3gpp_ts_38_104 等）"
    )


def _finite(x: object, name: str) -> float:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是有限数值，收到 {x!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须是有限数值，收到 {x!r}")
    return v


def _carrier_scope(carrier: dict) -> str:
    scope = carrier.get("band_scope", "standard")
    if scope not in _BAND_SCOPES:
        raise ValueError(
            f"band_scope {scope!r} 非法（允许 {'|'.join(_BAND_SCOPES)}）"
        )
    return str(scope)


def aclr_relative_limit(
    requirement: str, band_scope: str, adjacent: str
) -> AclrRelativeLimit:
    """按（requirement, band_scope, adjacent）取相对限值记录；未知组合 ValueError。"""
    if requirement not in ("aclr", "caclr"):
        raise ValueError(f"requirement {requirement!r} 非法（aclr|caclr）")
    if band_scope not in _BAND_SCOPES:
        raise ValueError(f"band_scope {band_scope!r} 非法（{'|'.join(_BAND_SCOPES)}）")
    if adjacent not in _ABS_ADJACENT:
        raise ValueError(f"adjacent {adjacent!r} 非法（{'|'.join(_ABS_ADJACENT)}）")
    table = ACLR_RELATIVE if requirement == "aclr" else CACLR_RELATIVE
    for rec in table:
        if rec.band_scope == band_scope and rec.adjacent == adjacent:
            return rec
    raise ValueError(
        f"{requirement}/{band_scope}/{adjacent} 无录入行（n46 域 assumed "
        "adjacent 仅 NR；E-UTRA 行仅 standard 域）"
    )


def absolute_psd_limit(requirement: str, bs_class: str) -> AbsolutePsdLimit:
    """按（requirement, bs_class）取绝对基本限值记录；未知组合 ValueError。"""
    if requirement not in ("aclr", "caclr"):
        raise ValueError(f"requirement {requirement!r} 非法（aclr|caclr）")
    if bs_class not in ABSOLUTE_BS_CLASSES:
        raise ValueError(
            f"未知 bs_class {bs_class!r}（绝对基本限值分层："
            f"{'|'.join(ABSOLUTE_BS_CLASSES)}；ACS 侧无 Cat A/B 区分，"
            f"见 ACS_BS_CLASSES）"
        )
    table = ACLR_ABSOLUTE if requirement == "aclr" else CACLR_ABSOLUTE
    for rec in table:
        if rec.bs_class == bs_class:
            return rec
    raise RuntimeError(f"unreachable: {requirement}/{bs_class}")


def acs_interferer_limit(bs_class: str, band_scope: str = "standard"
                         ) -> AcsInterfererLimit:
    """按（bs_class, band_scope）取 ACS 干扰限值记录；未知组合 ValueError。"""
    if band_scope not in _BAND_SCOPES:
        raise ValueError(f"band_scope {band_scope!r} 非法（{'|'.join(_BAND_SCOPES)}）")
    if bs_class not in ACS_BS_CLASSES:
        raise ValueError(
            f"未知 bs_class {bs_class!r}（ACS 分层：{'|'.join(ACS_BS_CLASSES)}）"
        )
    for rec in ACS_INTERFERER:
        if rec.bs_class == bs_class and rec.band_scope == band_scope:
            return rec
    raise ValueError(
        f"ACS {bs_class!r} 在 band_scope={band_scope!r} 无录入行"
        "（Table 7.4.1.2-1a 原表无 Wide Area 行）"
    )


def acs_offset_for_bw(bw_channel_mhz: float, band_scope: str = "standard"
                      ) -> AcsOffset:
    """按带宽取 ACS 干扰频偏记录（Table 7.4.1.2-2）；未知组合 ValueError。"""
    if band_scope not in _BAND_SCOPES:
        raise ValueError(f"band_scope {band_scope!r} 非法（{'|'.join(_BAND_SCOPES)}）")
    bw = _finite(bw_channel_mhz, "bw_channel_mhz")
    for rec in ACS_OFFSETS:
        if rec.band_scope == band_scope and rec.bw_channel_mhz == bw:
            return rec
    known = tuple(r.bw_channel_mhz for r in ACS_OFFSETS
                  if r.band_scope == band_scope)
    raise ValueError(
        f"band_scope={band_scope!r} 无 BW={bw:g} MHz 的 ACS 频偏行"
        f"（原表枚举：{known}）"
    )


# ─── 模板面：spur_template_check ─────────────────────────────────────────────

_CARRIER_KEYS = {
    "f_c_hz", "p_c_dbm", "bw_channel_mhz", "bs_class",
    "band_scope", "aclr_meas_bw_hz",
}


def _parse_carrier(carrier: object) -> dict[str, object]:
    if not isinstance(carrier, dict):
        raise ValueError("carrier 须为 dict（f_c_hz/p_c_dbm/bw_channel_mhz/"
                         "bs_class 必备；band_scope/aclr_meas_bw_hz 可选）")
    unknown = set(carrier) - _CARRIER_KEYS
    if unknown:
        raise ValueError(f"carrier 含未知键 {sorted(unknown)}（允许 "
                         f"{sorted(_CARRIER_KEYS)}）")
    for key in ("f_c_hz", "p_c_dbm", "bw_channel_mhz", "bs_class"):
        if key not in carrier:
            raise ValueError(f"carrier 缺必备键 {key!r}")
    f_c = _finite(carrier["f_c_hz"], "carrier['f_c_hz']")
    if f_c <= 0.0:
        raise ValueError(f"carrier['f_c_hz'] 必须 >0，收到 {f_c!r}")
    p_c = _finite(carrier["p_c_dbm"], "carrier['p_c_dbm']")
    scope = _carrier_scope(carrier)
    bw = _finite(carrier["bw_channel_mhz"], "carrier['bw_channel_mhz']")
    if bw not in BW_CHANNEL_MHZ[scope]:
        raise ValueError(
            f"carrier['bw_channel_mhz']={bw:g} 不在 band_scope={scope!r} "
            f"原表枚举 {BW_CHANNEL_MHZ[scope]} 内"
        )
    bs_class = carrier["bs_class"]
    if bs_class not in ABSOLUTE_BS_CLASSES:
        raise ValueError(
            f"carrier['bs_class']={bs_class!r} 非法（绝对基本限值分层："
            f"{'|'.join(ABSOLUTE_BS_CLASSES)}）"
        )
    meas_bw_raw = carrier.get("aclr_meas_bw_hz", bw * 1e6)
    meas_bw = _finite(meas_bw_raw, "carrier['aclr_meas_bw_hz']")
    if meas_bw <= 0.0:
        raise ValueError(f"carrier['aclr_meas_bw_hz'] 必须 >0，收到 {meas_bw!r}")
    return {
        "f_c_hz": f_c, "p_c_dbm": p_c, "bw_channel_mhz": bw,
        "bs_class": bs_class, "band_scope": scope, "aclr_meas_bw_hz": meas_bw,
    }


def _parse_spurs(spurs: object) -> list[tuple[float, float]]:
    if isinstance(spurs, dict) or not hasattr(spurs, "__iter__"):
        raise ValueError(
            "spurs 须为可迭代序列（元素=(f_hz, level_dbm) 元组或 "
            '{"f_hz":..., "level_dbm":...} dict）'
        )
    out: list[tuple[float, float]] = []
    for i, item in enumerate(spurs):
        if isinstance(item, dict):
            unknown = set(item) - {"f_hz", "level_dbm"}
            if unknown:
                raise ValueError(f"spurs[{i}] 含未知键 {sorted(unknown)}")
            if "f_hz" not in item or "level_dbm" not in item:
                raise ValueError(f"spurs[{i}] 缺 f_hz/level_dbm")
            f_hz = _finite(item["f_hz"], f"spurs[{i}]['f_hz']")
            level = _finite(item["level_dbm"], f"spurs[{i}]['level_dbm']")
        else:
            try:
                f_raw, l_raw = item  # type: ignore[misc]
            except (TypeError, ValueError):
                raise ValueError(
                    f"spurs[{i}]={item!r} 形态非法（须 (f_hz, level_dbm)）"
                ) from None
            f_hz = _finite(f_raw, f"spurs[{i}][0]")
            level = _finite(l_raw, f"spurs[{i}][1]")
        if f_hz <= 0.0:
            raise ValueError(f"spurs[{i}] f_hz 必须 >0，收到 {f_hz!r}")
        out.append((f_hz, level))
    return out


def spur_template_check(spurs: object, standard: object, carrier: object
                        ) -> dict[str, object]:
    """杂散列表对 TS 138 104 相邻道 ACLR 限值逐条评估 → margin 表。

    区域判定（|Δf|=|f−f_c|，BW=BWChannel）：assigned Δf≤BW/2（ACLR 只约束
    BS RF Bandwidth 之外，§6.6.3.1——如实 no_limit 不判）；1st 相邻
    (BW/2, 3BW/2]；2nd 相邻 (3BW/2, 5BW/2]；更远=杂散域（§6.6.5，不在本批
    数据面——out_of_scope 如实不判，不伪造限值）。

    合规语义（§6.6.3.3「whichever is less stringent」+ 38.141-1
    §6.6.3.5.3 conformance 佐证）：相邻道泄漏 ≤ max(相对限值=P_c−ACLR_dB,
    绝对限值=psd+10lg(meas_bw)) 即合规；margin_db>0 pass / <0 fail /
    =0 pass（恰在限值上）。两 track 的限值与裕量都随行报告，不藏信息。

    Args:
        spurs: [(f_hz, level_dbm), ...] 或 [{"f_hz":..., "level_dbm":...},
            ...]。level_dbm 语义=该相邻道测量滤波器（square BWConfig，缺省
            积分带宽=BWChannel，可用 carrier['aclr_meas_bw_hz'] 覆盖）内的
            功率。
        standard: 数据面 token（ts138104 系别名；未知 ValueError）。
        carrier: dict——f_c_hz / p_c_dbm / bw_channel_mhz / bs_class 必备，
            band_scope（缺省 standard）/ aclr_meas_bw_hz 可选。

    Returns:
        dict：standard/carrier 回显 + rows（逐条 margin）+ 判读汇总
        （n_pass/n_fail/n_out_of_scope/worst_margin_row/all_adjudicated_pass）。
        全部值 JSON 可序列化。

    Raises:
        ValueError: 未知 standard / carrier 或 spur 形态非法 / 带宽越表。
    """
    std = resolve_standard(standard)
    c = _parse_carrier(carrier)
    f_c = float(c["f_c_hz"])  # type: ignore[arg-type]
    p_c = float(c["p_c_dbm"])  # type: ignore[arg-type]
    bw_mhz = float(c["bw_channel_mhz"])  # type: ignore[arg-type]
    scope = str(c["band_scope"])
    bs_class = str(c["bs_class"])
    meas_bw = float(c["aclr_meas_bw_hz"])  # type: ignore[arg-type]
    half_hz = bw_mhz * 1e6 / 2.0
    abs_rec = absolute_psd_limit("aclr", bs_class)
    # dBm/MHz → dBm：积分带宽换算 10·lg(BW/1MHz)（psd 基准=1 MHz，不是 1 Hz）
    absolute_limit_dbm = (abs_rec.limit_dbm_per_mhz
                          + 10.0 * math.log10(meas_bw / 1e6))
    rows: list[dict[str, object]] = []
    for f_hz, level_dbm in _parse_spurs(spurs):
        delta = abs(f_hz - f_c)
        if delta <= half_hz:
            rows.append({
                "f_hz": f_hz, "level_dbm": level_dbm, "offset_hz": delta,
                "region": "assigned_channel",
                "verdict": "no_limit_assigned_channel",
                "note": "ACLR 只约束 BS RF Bandwidth 之外（§6.6.3.1）",
                "margin_db": None, "effective_limit_dbm": None,
            })
            continue
        if delta <= 3.0 * half_hz:
            region, adjacent = "adjacent_first", "first"
        elif delta <= 5.0 * half_hz:
            region, adjacent = "adjacent_second", "second"
        else:
            rows.append({
                "f_hz": f_hz, "level_dbm": level_dbm, "offset_hz": delta,
                "region": "beyond_second_adjacent",
                "verdict": "out_of_scope_spurious_domain",
                "note": "杂散域限值=TS 138 104 §6.6.5（不在本批数据面）",
                "margin_db": None, "effective_limit_dbm": None,
            })
            continue
        rel_rec = aclr_relative_limit("aclr", scope, adjacent)
        relative_limit_dbm = p_c - rel_rec.limit_db
        effective_limit_dbm = max(relative_limit_dbm, absolute_limit_dbm)
        margin_db = effective_limit_dbm - level_dbm
        rows.append({
            "f_hz": f_hz, "level_dbm": level_dbm, "offset_hz": delta,
            "region": region,
            "aclr_limit_db": rel_rec.limit_db,
            "relative_limit_dbm": relative_limit_dbm,
            "relative_margin_db": relative_limit_dbm - level_dbm,
            "absolute_psd_dbm_per_mhz": abs_rec.limit_dbm_per_mhz,
            "absolute_limit_dbm": absolute_limit_dbm,
            "absolute_margin_db": absolute_limit_dbm - level_dbm,
            "effective_limit_dbm": effective_limit_dbm,
            "margin_db": margin_db,
            "verdict": "pass" if margin_db >= 0.0 else "fail",
            "band_scope": scope,
            "source_ids": {"aclr_relative": rel_rec.source_id,
                           "aclr_absolute": abs_rec.source_id,
                           "combine_semantics":
                               "ts138104_v17_5_0 §6.6.3.3 + 38.141-1 "
                               "§6.6.3.5.3（less stringent=满足任一）"},
        })
    adj = [r for r in rows if r["verdict"] in ("pass", "fail")]
    margins = [r["margin_db"] for r in adj]  # type: ignore[misc]
    worst_idx = (min(range(len(adj)), key=lambda k: margins[k])
                 if adj else None)
    worst_row = (adj[worst_idx] if worst_idx is not None else None)
    return {
        "standard": std,
        "data_version": "ETSI TS 138 104 V17.5.0 (2022-04)",
        "retrieved": PROVENANCE["retrieved"],
        "carrier": c,
        "rows": rows,
        "n_spurs": len(rows),
        "n_pass": sum(1 for r in adj if r["verdict"] == "pass"),
        "n_fail": sum(1 for r in adj if r["verdict"] == "fail"),
        "n_no_limit": sum(1 for r in rows
                          if r["verdict"] == "no_limit_assigned_channel"),
        "n_out_of_scope": sum(1 for r in rows
                              if r["verdict"] == "out_of_scope_spurious_domain"),
        "worst_margin_row": worst_row,
        "all_adjudicated_pass": (all(r["verdict"] == "pass" for r in adj)
                                 if adj else None),
    }


# ─── ACIR 合成与 C/I、IM=C/(N+I) 闭式 ────────────────────────────────────────


def _positive_ratio_db(x: object, name: str) -> float:
    v = _finite(x, name)
    if v <= 0.0:
        raise ValueError(
            f"{name} 须为正 dB 功率比（>0），收到 {v!r}——ACLR/ACS 按定义"
            "为「有用/泄漏」之比，0 或负 dB 无物理意义"
        )
    return v


def acir_synthesize(aclr_db: object, acs_db: object) -> float:
    """ACIR 合成式（TR 136 942 §8.1）：ACIR = 1/(1/ACLR + 1/ACS)，dB 出。

    Args:
        aclr_db: 发射侧 ACLR（dB，正功率比）。
        acs_db: 接收侧 ACS（dB，正功率比；BS 等效值可用 bs_acs_db 导出）。

    Returns:
        ACIR [dB]（原始 float，不取整）。
    """
    a = _positive_ratio_db(aclr_db, "aclr_db")
    s = _positive_ratio_db(acs_db, "acs_db")
    return 10.0 * math.log10(1.0 / (10.0 ** (-a / 10.0) + 10.0 ** (-s / 10.0)))


def bs_acs_db(standard: object, bs_class: object, prefsens_dbm: object,
              band_scope: str = "standard") -> float:
    """由 §7.4.1.2 表列导出 BS 等效 ACS 比值（dB）：I_max − (PREFSENS+6)。

    语义：ACS 试验以 wanted=PREFSENS+6 dB、干扰=表列 I_max 判 ≥95% 吞吐——
    等效选择度比值（线性）=I_max/(PREFSENS+6)。PREFSENS 由调用方按 §7.2.2
    取值提供（不在本批数据面——§7.2.2 表未录入，不越面产核）。

    Raises:
        ValueError: 未知 standard/bs_class/scope 或 prefsens 非有限。
    """
    resolve_standard(standard)
    rec = acs_interferer_limit(str(bs_class), band_scope)
    p = _finite(prefsens_dbm, "prefsens_dbm")
    return rec.interferer_dbm - (p + 6.0)


def carrier_to_interference_db(c_dbm: object, i_dbm: object) -> float:
    """C/I 闭式（dB）：C_dBm − I_dBm（round17 EM-6 原文口径）。"""
    c = _finite(c_dbm, "c_dbm")
    i = _finite(i_dbm, "i_dbm")
    return c - i


def c_over_n_plus_i_db(c_dbm: object, n_dbm: object, i_dbm: object) -> float:
    """IM=C/(N+I) 闭式（dB）：C_dBm − 10·lg(10^(N/10)+10^(I/10))。

    N、I 以 dBm 功率线性相加（round17 EM-6 原文口径 IM=C/(N+I)）。
    """
    c = _finite(c_dbm, "c_dbm")
    n = _finite(n_dbm, "n_dbm")
    i = _finite(i_dbm, "i_dbm")
    n_plus_i = 10.0 ** (n / 10.0) + 10.0 ** (i / 10.0)
    return c - 10.0 * math.log10(n_plus_i)
