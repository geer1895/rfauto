"""MA-7 厂商板材材料库工程内核（round17 §六 MA-7：datasheet 数值数字化 +
εr(T,f)/tanδ(T,f) 插值 schema + Dk 容差带 + 替代推荐）。

数据录入口径（#118 铁律：无可达单源精确数不虚构精确值）：

- **全部 Rogers 条目数值 2026-10-02 本会话逐值核对**两处官方来源：
  (a) RO3000 系列 datasheet PDF（Publication #92-130，2015 rev，经
  bayareacircuits.com 镜像逐字段读出，rogerscorp.cn 官方 PDF 同名同源）；
  (b) rogerscorp.com 产品页属性对比表（web_reader 直读原文）。
  RO4003C/RO4350B 另与本仓 configs/materials.yaml（2026-09-25 verified-web
  逐字核对）三方一致。
- **来源等级字段（source_level）**六档：``vendor_datasheet_verified``（官方
  datasheet PDF 本会话逐值核对）/ ``vendor_web_verified``（厂商官网页本会话
  核对）/ ``repo_verified_web``（本仓既档 verified-web 沿用）/
  ``literature_secondary``（二手文献）/ ``UNVERIFIED_band``（带值、逐源数字
  核对未做）/ ``UNVERIFIED_single_source``（单源待证）——后两档沿用
  PRINT_MATERIALS（core/luneburg_lens.py）先例口径：状态字段如实登记，
  数值只进 schema 不进判据。
- **Design Dk 与 process Dk 分开登记，禁止互串**（Coonrod「Design Dk」
  范式，研究扩充「Design Dk 锚」节）：process
  Dk=原材料夹持带线法（IPC-TM-650 2.5.5.5）；Design Dk=电路法差分相位
  长度，与设计链可比。两者数值可差 ~5%（RO3003 实证：process 3.00 vs
  官网工具 Design 3.1629）——同一材料"不同方法各自正确"的 Dk 方法域
  现象，正是 MA-8 78GHz Design Dk 锚的量化对象。
- **频域域守卫（extrapolate forbidden，锚先例）**：datasheet 明文给出
  Design Dk 适用频带的（RO3000 系 8–40 GHz），出域显式报错不外推——
  78 GHz 调用 RO3003 design 档即触发，报错文案指向 Design Dk 锚
  （MA-8 case_78ghz_design_dk 量化其必要性）。
- **同页冲突如实登记**：RO3003 官网属性表 process 容差 ±0.047 vs 特征栏
  与 datasheet ±0.04 并存、官网 Design Dk 3.1629 vs datasheet 3.00
  （8–40 GHz）并存——全部写进 ``conflict_notes``，不擅自裁决取舍（#122：
  如实不凑一致）。

温度模型：datasheet 只给 Thermal Coefficient of εr（ppm/°C，线性系数，
带适用温度域），故 εr(T) 走线性系数模型 Dk(T)=Dk(T_ref)·(1+tc_ppm_c·
1e-6·(T−T_ref))——**域内线性近似，出域报错**；未给系数的条目（如实）
T 档返回 unavailable，不编数。tanδ(T) 无官方公开点值——schema 有位
（``df_temperature_coeff``）一律 None，不编。

分层与注册：core 层纯函数零 IO（规则 7 数值只在确定性内核）；**不进
calculators 注册表**（F-C P1 域内约定，同 cryo_materials.py 先例），规格
MA-7 未列 CLI/MCP 面——消费者后续走 service 薄壳（本批不建）。

接口：全部函数返回 JSON 可序列化 dict/list/float/str/bool/None；数值
0.0 合法（判缺失一律 ``is not None``，#364④）；bool 显式拒收
（df7+⑯）；非有限拒收。
"""

from __future__ import annotations

import itertools
import math
from typing import Any

__all__ = [
    "SOURCE_DATASHEET_VERIFIED",
    "SOURCE_LITERATURE_SECONDARY",
    "SOURCE_REPO_VERIFIED_WEB",
    "SOURCE_UNVERIFIED_BAND",
    "SOURCE_UNVERIFIED_SINGLE_SOURCE",
    "SOURCE_WEB_VERIFIED",
    "VENDOR_LAMINATES",
    "dk_at_temperature",
    "dk_tolerance_band",
    "get_laminate",
    "interpolate_vs_frequency",
    "laminate_df",
    "laminate_dk",
    "list_laminates",
    "recommend_substitutes",
    "validate_material_entry",
]

# ─── 来源等级常量（schema 枚举位；文案即语义，禁自由字符串）──────────────────

#: 官方 datasheet PDF，本会话逐值核对
SOURCE_DATASHEET_VERIFIED = "vendor_datasheet_verified"
#: 厂商官网页面，本会话核对
SOURCE_WEB_VERIFIED = "vendor_web_verified"
#: 本仓 configs/materials.yaml 既档 verified-web（沿用）
SOURCE_REPO_VERIFIED_WEB = "repo_verified_web"
#: 二手文献（可达但未逐位核对原文）
SOURCE_LITERATURE_SECONDARY = "literature_secondary"
#: 带值、逐源数字核对未做（PRINT_MATERIALS UNVERIFIED_band 口径）
SOURCE_UNVERIFIED_BAND = "UNVERIFIED_band"
#: 单源待证（PRINT_MATERIALS UNVERIFIED_single_source 口径）
SOURCE_UNVERIFIED_SINGLE_SOURCE = "UNVERIFIED_single_source"

#: 合法来源等级全集（validator 与推荐器共用单源）
SOURCE_LEVELS = (
    SOURCE_DATASHEET_VERIFIED,
    SOURCE_WEB_VERIFIED,
    SOURCE_REPO_VERIFIED_WEB,
    SOURCE_LITERATURE_SECONDARY,
    SOURCE_UNVERIFIED_BAND,
    SOURCE_UNVERIFIED_SINGLE_SOURCE,
)

#: Design Dk 官方来源等级白名单（design 档只允许官方核对位）
_DESIGN_OK_LEVELS = (SOURCE_DATASHEET_VERIFIED, SOURCE_WEB_VERIFIED,
                     SOURCE_REPO_VERIFIED_WEB)


# ─── 入参收敛守卫（aging/cryo 同口径）───────────────────────────────────────


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，收到 {out}")
    return out


# ─── schema 校验 ─────────────────────────────────────────────────────────────


def _check_source_level(level: Any, where: str) -> str:
    if level not in SOURCE_LEVELS:
        raise ValueError(
            f"{where} source_level={level!r} 不在合法集 {list(SOURCE_LEVELS)}")
    return str(level)


def validate_material_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """校验材料条目 schema（就地检查，返回原 dict）。

    必填：``id``（非空 str）/ ``vendor`` / ``product`` / ``source_level``。
    结构位（出现即按结构校验）：

    - ``dk_process``：{value>0, tol≥0, f_ghz>0, t_c 有限, method 非空}
    - ``dk_design``：{value>0, f_ghz 可选>0, f_band_ghz 可选 [lo,hi]（lo<hi）,
      method 非空}；source_level 必须官方核对位（design 值禁二手/带值冒充）
    - ``df_process``：{value≥0, f_ghz>0, t_c 可选}
    - ``dk_vs_f``：非空点表 [{f_ghz>0, value>0, ...}]，频率无重复
    - ``df_vs_f``：同上（value≥0）
    - ``dk_temp_coeff_ppm_c``：有限 float；``t_coeff_domain_c``：[lo,hi]
    - ``status``：{unverified: bool, single_source: bool, conflict_notes: list}
    - ``sources``：非空 str 列表

    Raises:
        ValueError: 任一必填/结构/域约束违约（文案含字段路径）。
    """
    if not isinstance(entry, dict):
        raise ValueError(f"材料条目必须是 dict，收到 {type(entry).__name__}")
    for key in ("id", "vendor", "product"):
        val = entry.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"{key} 必须为非空 str，收到 {val!r}")
    _check_source_level(entry.get("source_level"), entry["id"])
    sources = entry.get("sources")
    if not isinstance(sources, list) or not sources or not all(
            isinstance(s, str) and s.strip() for s in sources):
        raise ValueError(f"{entry['id']} sources 必须为非空字符串列表")

    dk_p = entry.get("dk_process")
    if dk_p is not None:
        if not isinstance(dk_p, dict):
            raise ValueError(f"{entry['id']} dk_process 必须为 dict")
        _positive(dk_p.get("value"), f"{entry['id']}.dk_process.value")
        tol = _finite(dk_p.get("tol", 0.0), f"{entry['id']}.dk_process.tol")
        if tol < 0.0:
            raise ValueError(f"{entry['id']}.dk_process.tol 必须 ≥0，收到 {tol}")
        _positive(dk_p.get("f_ghz"), f"{entry['id']}.dk_process.f_ghz")

    dk_d = entry.get("dk_design")
    if dk_d is not None:
        if not isinstance(dk_d, dict):
            raise ValueError(f"{entry['id']} dk_design 必须为 dict")
        _positive(dk_d.get("value"), f"{entry['id']}.dk_design.value")
        level = dk_d.get("source_level", entry["source_level"])
        if level not in _DESIGN_OK_LEVELS:
            raise ValueError(
                f"{entry['id']}.dk_design.source_level={level!r} 非官方核对位"
                f"{list(_DESIGN_OK_LEVELS)}——Design 值禁二手/带值冒充（#118）")
        band = dk_d.get("f_band_ghz")
        if band is not None:
            if (not isinstance(band, (list, tuple)) or len(band) != 2):
                raise ValueError(
                    f"{entry['id']}.dk_design.f_band_ghz 必须为 [lo, hi]")
            lo = _positive(band[0], f"{entry['id']}.dk_design.f_band_ghz[0]")
            hi = _positive(band[1], f"{entry['id']}.dk_design.f_band_ghz[1]")
            if lo >= hi:
                raise ValueError(
                    f"{entry['id']}.dk_design.f_band_ghz 须 lo<hi，收到 [{lo},{hi}]")

    df_p = entry.get("df_process")
    if df_p is not None:
        if not isinstance(df_p, dict):
            raise ValueError(f"{entry['id']} df_process 必须为 dict")
        val = _finite(df_p.get("value"), f"{entry['id']}.df_process.value")
        if val < 0.0:
            raise ValueError(f"{entry['id']}.df_process.value 必须 ≥0，收到 {val}")
        _positive(df_p.get("f_ghz"), f"{entry['id']}.df_process.f_ghz")

    for table_key in ("dk_vs_f", "df_vs_f"):
        table = entry.get(table_key)
        if table is None:
            continue
        if not isinstance(table, list) or not table:
            raise ValueError(f"{entry['id']}.{table_key} 必须为非空点表")
        seen_f: list[float] = []
        for pt in table:
            if not isinstance(pt, dict):
                raise ValueError(f"{entry['id']}.{table_key} 点必须为 dict")
            f_pt = _positive(pt.get("f_ghz"), f"{entry['id']}.{table_key}.f_ghz")
            val = _finite(pt.get("value"), f"{entry['id']}.{table_key}.value")
            if table_key == "dk_vs_f" and val <= 0.0:
                raise ValueError(f"{entry['id']}.{table_key}.value 必须 >0")
            if table_key == "df_vs_f" and val < 0.0:
                raise ValueError(f"{entry['id']}.{table_key}.value 必须 ≥0")
            for f_seen in seen_f:
                if f_seen == f_pt:
                    raise ValueError(
                        f"{entry['id']}.{table_key} 频率重复：{f_pt} GHz"
                        "（冲突值禁同表并存，走 conflict_notes）")
            seen_f.append(f_pt)

    tc = entry.get("dk_temp_coeff_ppm_c")
    if tc is not None:
        _finite(tc, f"{entry['id']}.dk_temp_coeff_ppm_c")
        domain = entry.get("t_coeff_domain_c")
        if domain is not None:
            if not isinstance(domain, (list, tuple)) or len(domain) != 2:
                raise ValueError(f"{entry['id']}.t_coeff_domain_c 必须为 [lo, hi]")
            lo = _finite(domain[0], f"{entry['id']}.t_coeff_domain_c[0]")
            hi = _finite(domain[1], f"{entry['id']}.t_coeff_domain_c[1]")
            if lo >= hi:
                raise ValueError(
                    f"{entry['id']}.t_coeff_domain_c 须 lo<hi，收到 [{lo},{hi}]")

    status = entry.get("status")
    if status is not None:
        if not isinstance(status, dict):
            raise ValueError(f"{entry['id']} status 必须为 dict")
        for bool_key in ("unverified", "single_source"):
            if not isinstance(status.get(bool_key, False), bool):
                raise ValueError(f"{entry['id']}.status.{bool_key} 必须为 bool")
        notes = status.get("conflict_notes", [])
        if not isinstance(notes, list) or not all(
                isinstance(n, str) for n in notes):
            raise ValueError(f"{entry['id']}.status.conflict_notes 必须为 str 列表")
    return entry


# ─── 数据（全部来源见各条目 sources；2026-10-02 核对）─────────────────────────

_DS_RO3000 = (
    "RO3000 系列 datasheet PDF（Rogers Publication #92-130，2015 rev；"
    "rogerscorp.cn 官方 PDF 同名同源；2026-10-02 经 bayareacircuits.com "
    "镜像逐字段读出核对）"
)
_WEB_RO3000 = "rogerscorp.com RO3003™ 产品页属性表（2026-10-02 web_reader 直读原文）"
_WEB_RO4000 = (
    "rogerscorp.com RO4350B™ 产品页属性对比表（RO4003C/RO4350B 两列，"
    "2026-10-02 web_reader 直读原文）"
)
_REPO_XCHECK = (
    "本仓 configs/materials.yaml（2026-09-25 verified-web 逐字核对）三方一致"
)

#: 厂商板材库（MA-7 数据面）。校验锚：tests/unit/test_material_library.py
#: 对全表逐条 validate_material_entry；新增条目先过 schema 再进表。
VENDOR_LAMINATES: dict[str, dict[str, Any]] = {
    "rogers_ro3003": {
        "id": "rogers_ro3003",
        "vendor": "Rogers",
        "product": "RO3003",
        "family": "RO3000",
        "dk_process": {
            "value": 3.00, "tol": 0.04, "f_ghz": 10.0, "t_c": 23.0,
            "method": "IPC-TM-650 2.5.5.5 clamped stripline（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_design": {
            "value": 3.00, "f_band_ghz": [8.0, 40.0],
            "method": "differential phase length（微带差分相位长度，Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "df_process": {
            "value": 0.0010, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": -3.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.50, 0.75, 1.52],
        "thickness_note": "datasheet 英制标称 0.005/0.010/0.020/0.030/0.060 in"
                          "（毫米为 inch 换算修约；C10d 精算口径 0.005 in="
                          "0.127 mm）",
        "application_note": "datasheet 明文适用至 77 GHz（车规雷达口径）",
        "source_level": SOURCE_DATASHEET_VERIFIED,
        "status": {
            "unverified": False,
            "single_source": False,
            "conflict_notes": [
                "官网属性表 process 容差另示 ±0.047（vs datasheet 特征栏"
                "±0.04）——本表从 datasheet ±0.04，页面值记冲突不采信也不删证",
                "官网属性表 Design Dk 3.1629（@10GHz 口径标注）vs datasheet "
                "Design Dk 3.00（8–40 GHz 差分相位长度）——两官方口径 +5.4% "
                "方法域差并存，正是「Design Dk 锚」动机的现象本体；本表 "
                "dk_design 从 datasheet，官网值记 conflict 不采信",
            ],
        },
        "sources": [_DS_RO3000, _WEB_RO3000],
    },
    "rogers_ro3035": {
        "id": "rogers_ro3035",
        "vendor": "Rogers",
        "product": "RO3035",
        "family": "RO3000",
        "dk_process": {
            "value": 3.50, "tol": 0.05, "f_ghz": 10.0, "t_c": 23.0,
            "method": "IPC-TM-650 2.5.5.5 clamped stripline（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_design": {
            "value": 3.60, "f_band_ghz": [8.0, 40.0],
            "method": "differential phase length（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "df_process": {
            "value": 0.0015, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": -45.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.50, 0.75, 1.52],
        "source_level": SOURCE_DATASHEET_VERIFIED,
        "status": {"unverified": False, "single_source": False,
                   "conflict_notes": []},
        "sources": [_DS_RO3000, _WEB_RO3000],
    },
    "rogers_ro3006": {
        "id": "rogers_ro3006",
        "vendor": "Rogers",
        "product": "RO3006",
        "family": "RO3000",
        "dk_process": {
            "value": 6.15, "tol": 0.15, "f_ghz": 10.0, "t_c": 23.0,
            "method": "IPC-TM-650 2.5.5.5 clamped stripline（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_design": {
            "value": 6.50, "f_band_ghz": [8.0, 40.0],
            "method": "differential phase length（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "df_process": {
            "value": 0.0020, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": -262.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.64, 1.28],
        "source_level": SOURCE_DATASHEET_VERIFIED,
        "status": {
            "unverified": False,
            "single_source": False,
            "conflict_notes": [
                "官网属性表 Design Dk 6.4 vs datasheet 6.50（8–40 GHz）——"
                "修约口径差并存，记冲突",
            ],
        },
        "sources": [_DS_RO3000, _WEB_RO3000],
    },
    "rogers_ro3010": {
        "id": "rogers_ro3010",
        "vendor": "Rogers",
        "product": "RO3010",
        "family": "RO3000",
        "dk_process": {
            "value": 10.2, "tol": 0.30, "f_ghz": 10.0, "t_c": 23.0,
            "method": "IPC-TM-650 2.5.5.5 clamped stripline（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_design": {
            "value": 11.20, "f_band_ghz": [8.0, 40.0],
            "method": "differential phase length（Z 轴）",
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "df_process": {
            "value": 0.0022, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_DATASHEET_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": -395.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.64, 1.28],
        "source_level": SOURCE_DATASHEET_VERIFIED,
        "status": {"unverified": False, "single_source": False,
                   "conflict_notes": []},
        "sources": [_DS_RO3000, _WEB_RO3000],
    },
    "rogers_ro4003c": {
        "id": "rogers_ro4003c",
        "vendor": "Rogers",
        "product": "RO4003C",
        "family": "RO4000",
        "dk_process": {
            "value": 3.38, "tol": 0.05, "f_ghz": 10.0, "t_c": 23.0,
            "method": "clamped stripline process specification",
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "dk_design": {
            "value": 3.55, "method": "Rogers 阻抗设计名义（Design Dk）",
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "df_process": {
            "value": 0.0027, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": 40.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.50, 0.81],
        "thickness_note": "常见标称档（0.008 in=0.203 mm 亦流通）——本面只录"
                          "官方页可见口径，完整档以 datasheet 为准",
        "source_level": SOURCE_WEB_VERIFIED,
        "status": {"unverified": False, "single_source": False,
                   "conflict_notes": []},
        "sources": [_WEB_RO4000, _REPO_XCHECK],
    },
    "rogers_ro4350b": {
        "id": "rogers_ro4350b",
        "vendor": "Rogers",
        "product": "RO4350B",
        "family": "RO4000",
        "dk_process": {
            "value": 3.48, "tol": 0.05, "f_ghz": 10.0, "t_c": 23.0,
            "method": "clamped stripline process specification",
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "dk_design": {
            "value": 3.66, "method": "Rogers 阻抗设计名义（Design Dk；本仓 "
                                    "materials.yaml epsilon_r 即取此口径）",
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "df_process": {
            "value": 0.0037, "f_ghz": 10.0, "t_c": 23.0,
            "source_level": SOURCE_WEB_VERIFIED,
        },
        "dk_temp_coeff_ppm_c": 50.0,
        "t_coeff_domain_c": [-50.0, 150.0],
        "thicknesses_mm": [0.13, 0.25, 0.50, 0.76, 1.52],
        "thickness_note": "本仓 rogers4350b_h0.508 层叠用 0.508 mm（0.020 in）",
        "source_level": SOURCE_WEB_VERIFIED,
        "status": {"unverified": False, "single_source": False,
                   "conflict_notes": []},
        "sources": [_WEB_RO4000, _REPO_XCHECK],
    },
    "fr4_generic": {
        "id": "fr4_generic",
        "vendor": "（多厂商）",
        "product": "FR-4（generic）",
        "family": "epoxy-glass",
        "dk_process": {
            "value": 4.4, "tol": 0.0, "f_ghz": 1.0, "t_c": 23.0,
            "method": "通用典型值（树脂含量/玻璃布样式依赖，无单一 datasheet）",
            "source_level": SOURCE_UNVERIFIED_BAND,
        },
        "df_process": {
            "value": 0.020, "f_ghz": 1.0,
            "source_level": SOURCE_UNVERIFIED_BAND,
        },
        "er_band": [4.2, 4.8],
        "df_band": [0.015, 0.025],
        "source_level": SOURCE_UNVERIFIED_BAND,
        "status": {
            "unverified": True,
            "single_source": False,
            "conflict_notes": [
                "FR-4 介电常数随树脂含量/玻璃布样式/频率显著变化——带值登记"
                "（PK-5/PRINT_MATERIALS UNVERIFIED_band 先例口径），4.4/0.020 "
                "为本仓 materials.yaml fr4_h1.6 名义档引用值，不冒充仲裁值",
            ],
        },
        "sources": [
            "PK-5/PRINT_MATERIALS UNVERIFIED_band 口径（core/luneburg_lens.py）；"
            "本仓 configs/materials.yaml fr4_h1.6 名义 4.4/0.02",
        ],
    },
}

for _entry in VENDOR_LAMINATES.values():
    validate_material_entry(_entry)


def get_laminate(laminate_id: str) -> dict[str, Any]:
    """按 id 取条目（缺显式 KeyError，可用集随文案）。"""
    if laminate_id not in VENDOR_LAMINATES:
        raise KeyError(
            f"未知板材 id: {laminate_id!r}，可用: {sorted(VENDOR_LAMINATES)}")
    return VENDOR_LAMINATES[laminate_id]


def list_laminates() -> list[dict[str, Any]]:
    """全表摘要（id/vendor/product/source_level/status——推荐器展示面）。"""
    return [
        {
            "id": e["id"],
            "vendor": e["vendor"],
            "product": e["product"],
            "source_level": e["source_level"],
            "unverified": bool(e.get("status", {}).get("unverified", False)),
        }
        for e in (VENDOR_LAMINATES[k] for k in sorted(VENDOR_LAMINATES))
    ]


# ─── 插值与温度模型 ──────────────────────────────────────────────────────────


def interpolate_vs_frequency(
    points: list[dict[str, Any]],
    f_ghz: float,
    *,
    allow_extrapolate: bool = False,
) -> float:
    """频点表逐段线性插值（域外默认显式报错——extrapolate forbidden 先例）。

    Args:
        points: [{f_ghz, value}, ...]（频率有限正数，无重复；顺序无关）。
        f_ghz: 目标频率（GHz）。
        allow_extrapolate: True 时端点外线性外推（须显式意图；缺省 False）。

    Returns:
        插值 value。单点表：域内任意 f 返回该点值（无斜率可外推——单点域
        只有该频率本身，非端点即报错）。
    """
    f = _positive(f_ghz, "f_ghz")
    if not points:
        raise ValueError("频点表为空")
    pts = sorted(
        (_positive(p["f_ghz"], "points.f_ghz"), float(p["value"])) for p in points)
    for lo_f, lo_v in pts:
        if lo_f == f:
            return lo_v
    if f < pts[0][0] or f > pts[-1][0]:
        if not allow_extrapolate:
            raise ValueError(
                f"f={f} GHz 超出表域 [{pts[0][0]}, {pts[-1][0]}] GHz——"
                "外推禁用（锚先例）；须外推请显式 allow_extrapolate=True")
        if len(pts) == 1:
            raise ValueError("单点表无斜率，外推不可定义")
    if len(pts) == 1:
        return pts[0][1]
    for (f0, v0), (f1, v1) in itertools.pairwise(pts):
        if f0 <= f <= f1:
            return v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    # allow_extrapolate 端点外：用最近段斜率
    if f < pts[0][0]:
        (f0, v0), (f1, v1) = pts[0], pts[1]
    else:
        (f0, v0), (f1, v1) = pts[-2], pts[-1]
    return v0 + (v1 - v0) * (f - f0) / (f1 - f0)


def dk_at_temperature(
    dk: float,
    tc_ppm_c: float,
    t_c: float,
    *,
    t_ref_c: float = 23.0,
    domain_c: tuple[float, float] | list[float] | None = None,
) -> float:
    """线性 TCDk 模型 Dk(T)=Dk(T_ref)·(1+tc_ppm_c·1e-6·(T−T_ref))。

    Args:
        dk: 参考温度 Dk（T_ref 处）。
        tc_ppm_c: Thermal Coefficient of εr（ppm/°C；datasheet 口径）。
        t_c: 目标温度（°C）。
        t_ref_c: 参考温度（缺省 23°C，datasheet 条件口径）。
        domain_c: 系数适用温度域 [lo, hi]（datasheet 给域即传；None 不守卫）。

    Returns:
        Dk(T)。恒等锚：T=t_ref_c → dk 逐位；T=domain 端点合法。
    """
    dk_v = _positive(dk, "dk")
    tc = _finite(tc_ppm_c, "tc_ppm_c")
    t = _finite(t_c, "t_c")
    t_ref = _finite(t_ref_c, "t_ref_c")
    if domain_c is not None:
        lo = _finite(domain_c[0], "domain_c[0]")
        hi = _finite(domain_c[1], "domain_c[1]")
        if not (lo <= t <= hi):
            raise ValueError(
                f"t_c={t} °C 超出 TCDk 适用域 [{lo}, {hi}] °C——外推禁用")
    return dk_v * (1.0 + tc * 1e-6 * (t - t_ref))


def _resolve_temperature(
    entry: dict[str, Any],
    value: float,
    t_c: float | None,
    what: str,
) -> float:
    """温度档换算（系数缺位如实返回原值并标注——不编数）。"""
    if t_c is None:
        return value
    tc = entry.get("dk_temp_coeff_ppm_c")
    if tc is None:
        raise ValueError(
            f"{entry['id']} 未登记 dk_temp_coeff_ppm_c——{what} 温度档不可用"
            "（不编数；如需请补官方系数来源）")
    domain = entry.get("t_coeff_domain_c")
    return dk_at_temperature(value, float(tc), t_c, domain_c=domain)


def _design_domain_covers(entry: dict[str, Any], f_ghz: float) -> bool | None:
    """design Dk 适用频带是否覆盖 f（无带声明→None 如实）。"""
    band = entry.get("dk_design", {}).get("f_band_ghz")
    if band is None:
        return None
    return bool(band[0] <= f_ghz <= band[1])


def laminate_dk(
    entry_or_id: dict[str, Any] | str,
    *,
    f_ghz: float | None = None,
    t_c: float | None = None,
    dk_kind: str = "design",
) -> dict[str, Any]:
    """解析条目 Dk（design 档缺省；频域域守卫+温度修正）。

    Args:
        entry_or_id: 条目 dict 或 ``VENDOR_LAMINATES`` 键。
        f_ghz: 目标频率。design 档有官方频带声明时**域外显式报错**（不外推）
            ——RO3003@78GHz 即触发此路径（报错文案指向 Design Dk 锚）；
            process 档只回测量频点标注（process 值无官方频带语义）。
        t_c: 目标温度（°C；None=不修正，参考温度口径原值）。
        dk_kind: "design"（缺省）或 "process"。

    Returns:
        {id, dk, kind, measured_f_ghz, f_within_design_domain, t_c,
        applied_temp_coeff_ppm_c, source_level, note}
    """
    entry = get_laminate(entry_or_id) if isinstance(entry_or_id, str) \
        else validate_material_entry(entry_or_id)
    if dk_kind not in ("design", "process"):
        raise ValueError(f"dk_kind 须 design|process，收到 {dk_kind!r}")
    if dk_kind == "design":
        spec = entry.get("dk_design")
        if spec is None:
            raise ValueError(
                f"{entry['id']} 未登记 dk_design（UNVERIFIED 条目不冒充 "
                "Design 值，#118）——可查 dk_process 档")
    else:
        spec = entry.get("dk_process")
        if spec is None:
            raise ValueError(f"{entry['id']} 未登记 dk_process")
    value = _positive(spec["value"], f"{entry['id']}.{dk_kind}.value")
    measured_f = spec.get("f_ghz")
    band = spec.get("f_band_ghz")

    note = ""
    covers: bool | None = None
    if f_ghz is not None:
        f = _positive(f_ghz, "f_ghz")
        if band is not None:
            covers = _design_domain_covers(entry, f) if dk_kind == "design" \
                else None
            if dk_kind == "design" and covers is False:
                raise ValueError(
                    f"{entry['id']} design Dk 官方适用域 "
                    f"[{band[0]}, {band[1]}] GHz 不覆盖 f={f} GHz——外推禁止"
                    f"（锚先例）。mmWave 出域场景请改用电路域 Design Dk 锚"
                    "（MA-8 case_78ghz_design_dk / 锚 mmwave.design_dk."
                    "ro3003-oe-hfss-v2 口径），datasheet 值不可直移（#302 方法域）")
        table = entry.get("dk_vs_f")
        if table is not None:
            value = interpolate_vs_frequency(table, f)
            note = "值取自 dk_vs_f 频点表插值"
        elif measured_f is not None and f != float(measured_f):
            note = (f"官方测量点 {measured_f} GHz，无频点表——按点值引用"
                    "（频响未声明，如实标注）")
    if t_c is not None:
        value = _resolve_temperature(entry, value, t_c, f"{dk_kind} Dk")
    return {
        "id": entry["id"],
        "dk": value,
        "kind": dk_kind,
        "measured_f_ghz": measured_f,
        "f_band_ghz": list(band) if band is not None else None,
        "f_within_design_domain": covers,
        "t_c": t_c,
        "applied_temp_coeff_ppm_c": entry.get("dk_temp_coeff_ppm_c")
        if t_c is not None else None,
        "source_level": spec.get("source_level", entry["source_level"]),
        "note": note,
    }


def laminate_df(
    entry_or_id: dict[str, Any] | str,
    *,
    f_ghz: float | None = None,
    t_c: float | None = None,
) -> dict[str, Any]:
    """解析条目 tanδ（process 档；频点表插值+域守卫同 Dk 面结构）。"""
    entry = get_laminate(entry_or_id) if isinstance(entry_or_id, str) \
        else validate_material_entry(entry_or_id)
    spec = entry.get("df_process")
    if spec is None:
        raise ValueError(f"{entry['id']} 未登记 df_process")
    value = _finite(spec["value"], f"{entry['id']}.df_process.value")
    if value < 0.0:
        raise ValueError(f"{entry['id']}.df_process.value 必须 ≥0")
    measured_f = spec.get("f_ghz")
    note = ""
    if f_ghz is not None:
        f = _positive(f_ghz, "f_ghz")
        table = entry.get("df_vs_f")
        if table is not None:
            value = interpolate_vs_frequency(table, f)
            note = "值取自 df_vs_f 频点表插值"
        elif measured_f is not None and f != float(measured_f):
            note = (f"官方测量点 {measured_f} GHz，无频点表——按点值引用"
                    "（频响未声明，如实标注）")
    if t_c is not None:
        value = _resolve_temperature(entry, value, t_c, "tanδ")
    return {
        "id": entry["id"],
        "df": value,
        "measured_f_ghz": measured_f,
        "t_c": t_c,
        "source_level": spec.get("source_level", entry["source_level"]),
        "note": note,
    }


def dk_tolerance_band(entry_or_id: dict[str, Any] | str) -> dict[str, Any]:
    """Dk 容差带（process ±tol 半宽；带值条目给 band——两口径互斥如实）。"""
    entry = get_laminate(entry_or_id) if isinstance(entry_or_id, str) \
        else validate_material_entry(entry_or_id)
    spec = entry.get("dk_process")
    if spec is None:
        raise ValueError(f"{entry['id']} 未登记 dk_process")
    value = _positive(spec["value"], f"{entry['id']}.dk_process.value")
    band = entry.get("er_band")
    if band is not None:
        lo, hi = _positive(band[0], "er_band[0]"), _positive(band[1], "er_band[1]")
        return {
            "id": entry["id"], "kind": "band", "low": lo, "high": hi,
            "half_width": (hi - lo) / 2.0, "nominal": value,
            "source_level": SOURCE_UNVERIFIED_BAND,
            "note": "带值条目（UNVERIFIED_band）：±tol 未声明，带即如实口径",
        }
    tol = _finite(spec.get("tol", 0.0), f"{entry['id']}.dk_process.tol")
    if tol < 0.0:
        raise ValueError(f"{entry['id']}.dk_process.tol 必须 ≥0")
    rel_pct = (tol / value) * 100.0
    return {
        "id": entry["id"], "kind": "plus_minus_tol",
        "low": value - tol, "high": value + tol,
        "half_width": tol, "nominal": value,
        "relative_half_width_pct": rel_pct,
        "source_level": spec.get("source_level", entry["source_level"]),
        "note": "process Dk ±tol（官方容差带，@测量频点/温度口径）",
    }


# ─── 替代推荐（确定性打分；推荐非判据，#118）────────────────────────────────


def recommend_substitutes(
    dk_target: float,
    *,
    f_ghz: float | None = None,
    max_df: float | None = None,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """按目标 Dk（±可选损耗上限）从库内确定性排序推荐替代板材。

    打分（主序=|dk−target|/target；次序=tanδ；同级按 id 字典序——全确定性）：
    Dk 取 design 档（有则）否则 process 档（UNVERIFIED 条目如实带 unverified
    标记参与排序，不排除也不冒充）。``max_df`` 按 df_process 硬过滤。
    频域语义只作 ``design_domain_covered`` 标注字段（推荐器不做域守卫——
    守卫职责在 :func:`laminate_dk`）。

    Returns:
        [{id, product, dk_ref, df, dk_rel_err, design_domain_covered,
        unverified, reasons}]（≤top_n，升序）。
    """
    target = _positive(dk_target, "dk_target")
    if top_n < 1:
        raise ValueError(f"top_n 须 ≥1，收到 {top_n}")
    df_cap = _finite(max_df, "max_df") if max_df is not None else None
    if df_cap is not None and df_cap < 0.0:
        raise ValueError(f"max_df 须 ≥0，收到 {df_cap}")
    f = _positive(f_ghz, "f_ghz") if f_ghz is not None else None

    ranked: list[dict[str, Any]] = []
    for key in sorted(VENDOR_LAMINATES):
        entry = VENDOR_LAMINATES[key]
        dk_spec = entry.get("dk_design") or entry.get("dk_process")
        if dk_spec is None:
            continue
        dk_ref = float(dk_spec["value"])
        df_spec = entry.get("df_process")
        df_val = float(df_spec["value"]) if df_spec is not None else None
        if df_cap is not None and (df_val is None or df_val > df_cap):
            continue
        unverified = bool(entry.get("status", {}).get("unverified", False))
        reasons = [
            f"dk_ref={dk_ref}（{entry.get('product')}，相对目标 "
            f"{abs(dk_ref - target) / target * 100:.2f}%）",
        ]
        if df_val is not None:
            reasons.append(f"tanδ={df_val}（@{df_spec.get('f_ghz')} GHz 口径）")
        covered = _design_domain_covers(entry, f) if f is not None else None
        if covered is True:
            reasons.append(f"design Dk 官方域覆盖 f={f} GHz")
        elif covered is False:
            reasons.append(
                f"design Dk 官方域不覆盖 f={f} GHz（出域需 Design Dk 锚）")
        if unverified:
            reasons.append("UNVERIFIED 带值条目（不进判据，仅参考）")
        ranked.append({
            "id": entry["id"],
            "product": entry.get("product"),
            "dk_ref": dk_ref,
            "df": df_val,
            "dk_rel_err": abs(dk_ref - target) / target,
            "design_domain_covered": covered,
            "unverified": unverified,
            "reasons": reasons,
        })
    ranked.sort(key=lambda r: (r["dk_rel_err"],
                               r["df"] if r["df"] is not None else float("inf"),
                               r["id"]))
    return ranked[:top_n]
