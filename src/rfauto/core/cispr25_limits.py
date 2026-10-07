"""NX-9 车载 CISPR 25 限值数据面（Class 5 传导电压 CEV + 辐射 ALSE RE）。

规格：研究扩充 round14 §四 NX-9——"CISPR
25:2021 零部件辐射限值表（次级源双源纪律仿 emc_tvs_gate）+ALSE 1m 场强
折算复用 emc_radiated+ISO 11452-2"；宏图依赖链 EM-10(限值库) ─→ EM-6 ─→
NX-9 并入。任务书 ge8b Wave A 席4：NX-9 若 EM-6/EM-10 已含车载限值面则
记并入完成——#222 接地实测（2026-10-03）：limits_registry.py 峰值检波
token 为 CISPR 25 "后续面预留"、emi_filter 仅有 CISPR 25 5µH LISN 电路
（无限值表）——**限值数据面不在**，且 EM-6/EM-10 既有文件禁改，故本
模块独立成面、schema 兼容（segments 语义同 emi_filter 事实标准），注册
表 adapter 接线留 followUp（禁改面）。

纪律（#122/#412：单源录入错值会静默固化——逐格双源核对，分歧格不录）
------------------------------------------------------------------
**检索 2026-10-03，双源实现**（web 检索+PDF 逐格读数）：
1. Tekbox《Pre-Compliance Conducted Emission Measurements》PDF p.14
   （tekbox.com，CISPR 25 传导 CEV 全类表，pypdf 读数）。
2. EMCCalc CISPR 25 限值页（emccalc.com/limits/cispr25-cev/ 与
   /limits/cispr25-re/，标注 CISPR 25:2016 Ed4/2021 Ed5 Table 5/7 口径）。

**逐格核对结果（Class 5）**：
- CEV 传导（dBµV）：LW 0.15–0.3 (70/57/50)、MW 0.53–1.8 (54/41/34)、
  SW 5.9–6.2 (53/40/33)、CB 26–28 与 VHF 30–54 (44/31/24)、TV-I 41–88
  (PK 34/AV 24)、FM 76–108 (PK 38/QP 25)——两源逐格一致 ✓。
- **分歧格不录**：88–108 MHz AVG（Tekbox 28 vs EMCCalc 18）、41–88 QP
  （Tekbox 25 vs EMCCalc 缺格）——两源冲突按 #122 如实弃录并在
  provenance 记分歧（后续持标准正文者裁定）。
- RE 辐射 ALSE 1m（dBµV/m）：全表单源（EMCCalc Table 7 口径）+ 部分
  点核（TU Dortmund 论文引 Class 5 ALSE avg=18 dBµV/m@100 MHz/300 MHz，
  与 EMCCalc FM/RKE AV=18 一致）——单源格标 dual_source=False。

模块面
------
- ``CISPR25_CEV_CLASS5`` / ``CISPR25_RE_ALSE_CLASS5``：段表常量（拷贝面）。
- ``cispr25_class5_cev`` / ``cispr25_class5_re_alse``：表+provenance 出口。
- ``cispr25_margin_report``：测量点 (f, level, detector) → 适用段限值/
  裕量（margin = limit − level）；detector ∈ {peak, qp, avg}，段内该
  detector 无格（None）→ 如实 verdict="not_defined" 不虚构。
- ``ALSE_1M_NOTE``：ALSE 1m 场强口径文档面（折算链消费 emc_radiated，
  本模块不做折算数值）。

出处
----
round14 §四 NX-9；CISPR 25:2016/2021（标准正文收费，只作口径名）；
次级源双源见各 PROVENANCE 常量。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "ALSE_1M_NOTE",
    "CISPR25_CEV_CLASS5",
    "CISPR25_RE_ALSE_CLASS5",
    "CISPR25_SOURCE_NOTE",
    "cispr25_class5_cev",
    "cispr25_class5_re_alse",
    "cispr25_margin_report",
]

CISPR25_SOURCE_NOTE = (
    "CISPR 25:2016 (Ed4)/2021 (Ed5)（标准正文收费，只作口径名）；次级源"
    "双源：Tekbox app note PDF p.14 + EMCCalc 限值页（CEV 逐格双源，"
    "分歧格弃录）；RE ALSE 全表单源+TU Dortmund avg 点核；检索 2026-10-03"
)

#: CEV（电源端子传导电压，dBµV）Class 5 段表。
#: 每段 {service, f_lo_mhz, f_hi_mhz, peak, qp, avg, dual_source}——None=该
#: 检波器此段无格/分歧弃录（调用方按 not_defined 处理，不虚构）。
CISPR25_CEV_CLASS5: list[dict[str, Any]] = [
    {"service": "LW broadcast", "f_lo_mhz": 0.15, "f_hi_mhz": 0.30,
     "peak": 70.0, "qp": 57.0, "avg": 50.0, "dual_source": True},
    {"service": "MW broadcast", "f_lo_mhz": 0.53, "f_hi_mhz": 1.8,
     "peak": 54.0, "qp": 41.0, "avg": 34.0, "dual_source": True},
    {"service": "SW broadcast", "f_lo_mhz": 5.9, "f_hi_mhz": 6.2,
     "peak": 53.0, "qp": 40.0, "avg": 33.0, "dual_source": True},
    {"service": "CB", "f_lo_mhz": 26.0, "f_hi_mhz": 28.0,
     "peak": 44.0, "qp": 31.0, "avg": 24.0, "dual_source": True},
    {"service": "VHF mobile 30-54", "f_lo_mhz": 30.0, "f_hi_mhz": 54.0,
     "peak": 44.0, "qp": 31.0, "avg": 24.0, "dual_source": True},
    {"service": "TV Band I", "f_lo_mhz": 41.0, "f_hi_mhz": 88.0,
     "peak": 34.0, "qp": None, "avg": 24.0, "dual_source": True},
    {"service": "VHF mobile 68-87", "f_lo_mhz": 68.0, "f_hi_mhz": 87.0,
     "peak": 38.0, "qp": 25.0, "avg": None, "dual_source": False},
    {"service": "FM broadcast", "f_lo_mhz": 76.0, "f_hi_mhz": 108.0,
     "peak": 38.0, "qp": 25.0, "avg": None, "dual_source": False},
]

#: RE（辐射发射，ALSE 法 1 m，dBµV/m）Class 5 段表（EMCCalc Table 7 口径；
#: TU Dortmund avg 点核 FM/RKE 两格）。
CISPR25_RE_ALSE_CLASS5: list[dict[str, Any]] = [
    {"service": "LW broadcast", "f_lo_mhz": 0.15, "f_hi_mhz": 0.30,
     "peak": 46.0, "qp": 33.0, "avg": 26.0, "dual_source": False},
    {"service": "MW broadcast", "f_lo_mhz": 0.53, "f_hi_mhz": 1.8,
     "peak": 40.0, "qp": 27.0, "avg": 20.0, "dual_source": False},
    {"service": "SW broadcast", "f_lo_mhz": 5.9, "f_hi_mhz": 6.2,
     "peak": 40.0, "qp": 27.0, "avg": 20.0, "dual_source": False},
    {"service": "CB", "f_lo_mhz": 26.0, "f_hi_mhz": 28.0,
     "peak": 40.0, "qp": 27.0, "avg": 20.0, "dual_source": False},
    {"service": "VHF mobile 30-54", "f_lo_mhz": 30.0, "f_hi_mhz": 54.0,
     "peak": 40.0, "qp": 27.0, "avg": 20.0, "dual_source": False},
    {"service": "TV Band I", "f_lo_mhz": 41.0, "f_hi_mhz": 88.0,
     "peak": 28.0, "qp": None, "avg": 18.0, "dual_source": True},
    {"service": "VHF mobile 68-87", "f_lo_mhz": 68.0, "f_hi_mhz": 87.0,
     "peak": 35.0, "qp": 22.0, "avg": 15.0, "dual_source": False},
    {"service": "FM broadcast", "f_lo_mhz": 76.0, "f_hi_mhz": 108.0,
     "peak": 38.0, "qp": 25.0, "avg": 18.0, "dual_source": True},
    {"service": "VHF mobile 142-175", "f_lo_mhz": 142.0, "f_hi_mhz": 175.0,
     "peak": 35.0, "qp": 22.0, "avg": 15.0, "dual_source": False},
    {"service": "TV Band III", "f_lo_mhz": 174.0, "f_hi_mhz": 230.0,
     "peak": 32.0, "qp": None, "avg": 22.0, "dual_source": False},
    {"service": "UHF mobile 380-512", "f_lo_mhz": 380.0, "f_hi_mhz": 512.0,
     "peak": 38.0, "qp": 25.0, "avg": 18.0, "dual_source": False},
    {"service": "TV Band IV/V", "f_lo_mhz": 468.0, "f_hi_mhz": 944.0,
     "peak": 41.0, "qp": None, "avg": 31.0, "dual_source": False},
    {"service": "UHF mobile 820-960", "f_lo_mhz": 820.0, "f_hi_mhz": 960.0,
     "peak": 44.0, "qp": 31.0, "avg": 24.0, "dual_source": False},
    {"service": "GPS L1 civil", "f_lo_mhz": 1567.0, "f_hi_mhz": 1583.0,
     "peak": None, "qp": None, "avg": 10.0, "dual_source": False},
    {"service": "RKE 300", "f_lo_mhz": 300.0, "f_hi_mhz": 330.0,
     "peak": 32.0, "qp": None, "avg": 18.0, "dual_source": True},
    {"service": "RKE 420", "f_lo_mhz": 420.0, "f_hi_mhz": 450.0,
     "peak": 32.0, "qp": None, "avg": 18.0, "dual_source": False},
    {"service": "BT/802.11 2.4G", "f_lo_mhz": 2400.0, "f_hi_mhz": 2500.0,
     "peak": 44.0, "qp": None, "avg": 24.0, "dual_source": False},
]

ALSE_1M_NOTE = (
    "ALSE 法 1 m 口径：EUT+50 mm 离地线束、1 m 天线距离；远场场强折算"
    "（3 m↔1 m 等）消费 emc_radiated 链路，本模块不做折算数值；"
    "ISO 11452-2 为抗扰侧口径名"
)

_DETECTORS = ("peak", "qp", "avg")


def _copy_table(table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(seg) for seg in table]


def cispr25_class5_cev() -> dict[str, Any]:
    """CEV Class 5 表 + provenance（拷贝面，防外部改表）。"""
    return {
        "standard": "CISPR 25:2016/2021 Table 5 口径（CEV 电压法）",
        "unit": "dBuV",
        "distance_m": None,
        "segments": _copy_table(CISPR25_CEV_CLASS5),
        "provenance": {
            "primary": "CISPR 25:2016/2021（正文收费，次级源双源交叉核对口径）",
            "secondary": [
                "Tekbox Pre-Compliance Conducted Emission Measurements PDF "
                "p.14（tekbox.com，pypdf 逐格读数，检索 2026-10-03）",
                "EMCCalc /limits/cispr25-cev/（标注 Ed4/Ed5 Table 5 口径，"
                "检索 2026-10-03）",
            ],
            "disputed_omitted": [
                "88-108 MHz AVG（Tekbox 28 vs EMCCalc 18——弃录，#122）",
                "41-88 MHz QP（Tekbox 25 vs EMCCalc 无格——弃录，#122）",
            ],
            "retrieved": "2026-10-03",
        },
    }


def cispr25_class5_re_alse() -> dict[str, Any]:
    """RE ALSE Class 5 表 + provenance（拷贝面）。"""
    return {
        "standard": "CISPR 25:2016/2021 Table 7 口径（ALSE 法）",
        "unit": "dBuV/m",
        "distance_m": 1.0,
        "segments": _copy_table(CISPR25_RE_ALSE_CLASS5),
        "provenance": {
            "primary": "CISPR 25:2016/2021（正文收费，次级源口径）",
            "secondary": [
                "EMCCalc /limits/cispr25-re/（Table 7 口径全表，检索 "
                "2026-10-03）——全表单源",
                "TU Dortmund 论文点核：Class 5 ALSE avg=18 dBuV/m @100/300 "
                "MHz（检索 2026-10-03，与 EMCCalc FM/RKE AV 一致）",
            ],
            "disputed_omitted": [],
            "retrieved": "2026-10-03",
        },
    }


def _finite(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须为有限数，实际 {x!r}")
    return v


def cispr25_margin_report(face: str, freq_mhz: Any, level: Any,
                          detector: str) -> dict[str, Any]:
    """测量点 → 适用段限值与裕量（margin = limit − level，正=合规）。

    face ∈ {"cev", "re_alse"}；detector ∈ {peak, qp, avg}。freq 落在
    多段重叠区（TV-I 与 VHF mobile 等服务重叠）时取**最严限值**（最小）
    并列全部适用段；无适用段 → verdict="no_band"；段内该检波器无格 →
    verdict="not_defined"（不虚构，#122）。
    """
    if face == "cev":
        table = CISPR25_CEV_CLASS5
        unit = "dBuV"
    elif face == "re_alse":
        table = CISPR25_RE_ALSE_CLASS5
        unit = "dBuV/m"
    else:
        raise ValueError(f"face 须 'cev'|'re_alse'，实际 {face!r}")
    if detector not in _DETECTORS:
        raise ValueError(f"detector 须 ∈ {_DETECTORS}，实际 {detector!r}")
    f = _finite(freq_mhz, "freq_mhz")
    if f <= 0.0:
        raise ValueError("freq_mhz 须为正")
    lvl = _finite(level, "level")
    hits = [seg for seg in table if seg["f_lo_mhz"] <= f <= seg["f_hi_mhz"]]
    if not hits:
        return {"verdict": "no_band", "freq_mhz": f, "detector": detector,
                "unit": unit, "segments": []}
    entries = []
    for seg in hits:
        limit = seg[detector]
        if limit is None:
            entries.append({"service": seg["service"],
                            "verdict": "not_defined", "limit": None,
                            "dual_source": seg["dual_source"]})
            continue
        entries.append({
            "service": seg["service"],
            "limit": float(limit),
            "margin_db": float(limit) - lvl,
            "verdict": "pass" if lvl <= float(limit) else "fail",
            "dual_source": seg["dual_source"],
        })
    defined = [e for e in entries if e["verdict"] != "not_defined"]
    if not defined:
        return {"verdict": "not_defined", "freq_mhz": f,
                "detector": detector, "unit": unit, "segments": entries}
    strict = min(defined, key=lambda e: e["limit"])
    return {
        "verdict": strict["verdict"],
        "freq_mhz": f,
        "detector": detector,
        "unit": unit,
        "worst_limit": strict["limit"],
        "margin_db": strict["margin_db"],
        "n_bands": len(hits),
        "segments": entries,
    }
