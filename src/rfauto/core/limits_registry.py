"""EM-10 标准限值机读库统一：统一 schema + 三适配器 + 查询（事实兼容零迁移）。

规格：研究扩充 round17 EM-10 段——统一 schema
{standard,port,radius,detector,segments,source,retrieved}（emi_filter.segments
事实兼容零迁移）。本模块是三个既有限值文件的**统一机读写面**：

- 零迁移纪律：emi_filter.py / emc_radiated.py / exposure_limits.py 三文件
  **一字不改**（原函数/常量照旧供既有消费者使用）；本模块不新增任何限值
  数值——一切值面来自三文件的既有函数与常量（只读 import 复用）。
- 统一 schema：LimitLine（单条限值线：频段×检波×量，逐线 source_id 溯源）
  + LimitTable（一张表：standard/port/radius/segments/source/retrieved 全
  具备，与 EM-10 规格 schema 对齐）。
- 三适配器：from_emi_filter()（传导，§15.107）/ from_emc_radiated()（辐射，
  §15.109(b)+CISPR 32；任务书原文写法 from_emsc_radiated 亦提供为同函数
  别名）/ from_exposure()（RF 暴露，FCC §1.1310 + ICNIRP 2020）。
- 查询：limits_query(table_id, f_hz, detector=...)——值面 **native 委托**
  原模块求值器（emi_filter._eval_fcc_line / exposure_limits.mpe_limit），
  与既有消费者（margin_report / radiated_margin / mpe_limit）逐位一致；
  line_id/source_id 溯源随行。
- 段语义 per-table 显式注记（不隐式归一）：
  * emi/emc 两族＝双闭区间、逐点取覆盖段最小值（"lower limit applies at
    band edges"）、带外 NaN 不判读（band_rule="closed_min"）；段内 flat 或
    log_linear（对频线性，仅 §15.107 首段）。
  * exposure 族＝[lo, hi) 半开、末段双闭、带外显式 ValueError（越域拒绝不
    外推）（band_rule="half_open_last_closed"）；段内幂律公式（原表 formula
    元组）；返回值=原 mpe_limit 的 round-9 口径。
- 检波维度：peak|qp|avg（本批数据面只出现 qp/avg；peak 为 CISPR 25 等后续
  车载面预留 token）；exposure 表无检波维度，线面 detector="na"。
- 单位 token 用 ASCII 机读形态：dBuV=dBµV、dBuV/m=dBµV/m、W/m^2=W/m²、
  V/m、A/m（原文件中文注记保留在 source/notes）。
- EM-6 预留：TS 138 104 ACLR（§6.6.3）/ ACS（§7.4.1）引用键位（PV-012 已
  verified）——本批只留 status="reserved" 空 schema 位不录数据，查询显式
  拒绝。
- margin 比对面零迁移沿用原实现（emi_filter.margin_report /
  emc_radiated.radiated_margin 直收原 dict）——本模块不另起炉灶。

普查清单：runs/em10/limits_survey_20261002.md。
"""

from __future__ import annotations

import math
import types
from dataclasses import dataclass

import numpy as np

from rfauto.core import emc_radiated, emi_filter, exposure_limits

__all__ = [
    "LimitLine",
    "LimitTable",
    "from_emc_radiated",
    "from_emi_filter",
    "from_emsc_radiated",
    "from_exposure",
    "get_limit_table",
    "limits_query",
    "list_limit_tables",
]

#: 检波 token 全集（canonical 形态；peak 为 CISPR 25 等后续面预留）。
DETECTOR_TOKENS = ("peak", "qp", "avg", "na")

#: 单位 token 全集（ASCII 机读形态，映射见模块 docstring）。
UNIT_TOKENS = ("dBuV", "dBuV/m", "V/m", "A/m", "W/m^2")

#: 暴露限量列 token → 原函数返回键 / 单位。
_EXPOSURE_QUANTITIES: dict[str, tuple[str, str]] = {
    "e_field": ("e_v_per_m", "V/m"),
    "h_field": ("h_a_per_m", "A/m"),
    "power_density": ("s_w_per_m2", "W/m^2"),
}

_DET_ALIASES = {
    "qp": "qp",
    "quasi-peak": "qp",
    "quasi_peak": "qp",
    "avg": "avg",
    "average": "avg",
    "peak": "peak",
    "na": "na",
}


def _canon_detector(detector: object) -> str:
    token = str(detector).strip().lower()
    if token not in _DET_ALIASES:
        raise ValueError(
            f"未知 detector {detector!r}（允许 {'|'.join(DETECTOR_TOKENS)}；"
            "quasi-peak/average 为原表写法别名）"
        )
    return _DET_ALIASES[token]


def _fmt_mhz(f_hz: float) -> str:
    return "%g" % (f_hz / 1e6)


# ─── 统一 schema ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LimitLine:
    """单条限值线（频段×检波×量），逐线 source_id 溯源（EM-10 统一 schema）。

    interp 语义（per-table 注记见 LimitTable.interp_note）：
    - "flat"：段内常值 limit_value（limit_value_hi 与之同值）。
    - "log_linear"：段内对频线性内插（emi_filter._eval_fcc_line 同式）——
      limit_value=f_lo 端值、limit_value_hi=f_hi 端值。
    - "formula"：幂律公式段（exposure 原表 formula 元组），limit_value=None，
      求值 native 委托 exposure_limits._eval_formula。
    """

    line_id: str
    f_lo_hz: float
    f_hi_hz: float
    limit_value: float | None
    unit: str
    detector: str  # peak|qp|avg|na
    distance_ref: str | None
    source_id: str
    quantity: str = "field_strength"
    interp: str = "flat"  # flat|log_linear|formula
    limit_value_hi: float | None = None
    formula: tuple | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LimitTable:
    """一张限值表（EM-10 规格 schema：standard/port/radius/detector/segments/
    source/retrieved 对齐；segments=lines，detector 落到逐线）。"""

    table_id: str
    title: str
    standard: str
    source: str
    retrieved: str
    lines: tuple[LimitLine, ...]
    family: str  # emi_conducted|emc_radiated|exposure|em6_reserved
    band_rule: str  # closed_min|half_open_last_closed|none
    outside_rule: str  # nan_out_of_band|valueerror_domain_guard|none
    native_kind: str  # emi_fcc_segments|exposure_mpe|none
    native_key: object = None  # 原模块求值上下文（只读；勿改）
    port: str | None = None
    detector_policy: str = "per_line"  # per_line|na
    default_quantity: str | None = None
    distance_ref: str | None = None
    interp_note: str = ""
    status: str = "active"  # active|reserved
    notes: tuple[str, ...] = ()


# ─── 适配器 1：emi_filter（47 CFR §15.107 传导发射，QP+Avg 双检波）────────────


def _seg_to_line(
    table_id: str,
    source_id: str,
    seg: dict[str, object],
    detector: str,
    unit: str,
    quantity: str,
    distance_ref: str | None,
) -> LimitLine:
    """emi_filter/emc_radiated 段 dict（MHz/dBµV 系 schema）→ LimitLine（Hz）。"""
    kind = str(seg["kind"])
    lo = float(seg["f_lo_mhz"]) * 1e6  # type: ignore[arg-type]
    hi = float(seg["f_hi_mhz"]) * 1e6  # type: ignore[arg-type]
    v_lo = float(seg["dbuv_lo"])  # type: ignore[arg-type]
    v_hi = float(seg["dbuv_hi"])  # type: ignore[arg-type]
    if kind == "log_linear":
        interp = "log_linear"
    elif kind == "flat":
        interp = "flat"
        v_hi = v_lo
    else:
        raise ValueError(f"未知段 kind {kind!r}（{table_id} / {source_id}）")
    return LimitLine(
        line_id=f"{table_id}:{detector}:{_fmt_mhz(lo)}-{_fmt_mhz(hi)}MHz",
        f_lo_hz=lo,
        f_hi_hz=hi,
        limit_value=v_lo,
        unit=unit,
        detector=detector,
        distance_ref=distance_ref,
        source_id=source_id,
        quantity=quantity,
        interp=interp,
        limit_value_hi=v_hi,
    )


def from_emi_filter(class_b: bool = True) -> LimitTable:
    """收编 emi_filter.fcc_limits_part15（§15.107 传导发射，零迁移）。

    QP/Avg 双检波列收编为同一张表的 detector 标注线；native 求值委托
    emi_filter._eval_fcc_line（与 margin_report dict 路径逐位一致）。
    """
    ref = emi_filter.fcc_limits_part15(class_b=class_b)
    klass = "B" if class_b else "A"
    table_id = f"emi_fcc_part15_conducted_class_{klass.lower()}"
    lines: list[LimitLine] = []
    native: dict[str, object] = {}
    for det, key in (("qp", "segments_qp"), ("avg", "segments_avg")):
        segs = tuple(types.MappingProxyType(dict(s)) for s in ref[key])  # type: ignore[arg-type]
        native[det] = segs
        for seg in segs:
            lo = float(seg["f_lo_mhz"])  # type: ignore[arg-type]
            hi = float(seg["f_hi_mhz"])  # type: ignore[arg-type]
            source_id = (
                f"47 CFR §{ref['paragraph']} Class {klass} "
                f"{det.upper()} {lo:g}-{hi:g} MHz"
            )
            lines.append(
                _seg_to_line(table_id, source_id, dict(seg), det, "dBuV",
                             "conducted_voltage", None)
            )
    return LimitTable(
        table_id=table_id,
        title=f"FCC Part 15 §15.107 传导发射限值线 Class {klass}"
              f"（dBµV QP/Avg，150 kHz–30 MHz）",
        standard="47 CFR Part 15 §15.107",
        source=str(ref["source"]),
        retrieved=str(ref["retrieved"]),
        lines=tuple(lines),
        family="emi_conducted",
        band_rule="closed_min",
        outside_rule="nan_out_of_band",
        native_kind="emi_fcc_segments",
        native_key=native,
        port=str(ref["measurement"]),
        detector_policy="per_line",
        default_quantity="conducted_voltage",
        interp_note=(
            "段内 flat / log_linear（对频线性，仅首段）；段间双闭区间逐点取"
            "覆盖段最小值（'lower limit applies at band edges'，B-QP 5 MHz "
            "边界=56）；带外 NaN 不判读。求值 native 委托 "
            "emi_filter._eval_fcc_line（与 margin_report dict 路径逐位一致）。"
        ),
        notes=(
            "margin_report 对本族原 dict 取 segments_avg 保守包络口径"
            "（Avg 线恒低 QP 10/13 dB）——保守判读请用 detector='avg'。",
        ),
    )


# ─── 适配器 2：emc_radiated（§15.109(b) + CISPR 32 Table A.4 辐射发射）────────


def _detector_for_segment(
    det_map: dict[str, object], seg: dict[str, object]
) -> str:
    """按原表 detector dict（"30_960_mhz"/"above_960_mhz"/"all" 键）定段检波。"""
    mid = (float(seg["f_lo_mhz"]) + float(seg["f_hi_mhz"])) / 2.0  # type: ignore[arg-type]
    for key, raw in det_map.items():
        det = _canon_detector(raw)
        if key == "all":
            return det
        if key.startswith("above_"):
            lo = float(key[len("above_") : -len("_mhz")])
            if mid > lo:
                return det
        else:
            lo_s, hi_s = key[: -len("_mhz")].split("_", 1)
            if float(lo_s) <= mid <= float(hi_s):
                return det
    raise ValueError(f"detector dict {det_map!r} 未覆盖段中点 {mid} MHz")


def from_emc_radiated() -> tuple[LimitTable, LimitTable]:
    """收编 emc_radiated 两张辐射发射限值表（零迁移）。

    检波归属按原表 detector dict 解析（FCC：30–960 QP / >960 avg；
    CISPR 32：全段 QP）；native 求值委托 emi_filter._eval_fcc_line
    （radiated_margin 同引擎，逐位一致）。
    """
    fcc = emc_radiated.fcc_part15b_radiated_limits()
    cispr = emc_radiated.cispr32_classb_radiated_limits()
    return (_from_radiated_dict(fcc, "emc_fcc_part15b_radiated_class_b",
                               "FCC Part 15 §15.109(b) Class B 辐射发射限值线"
                               "（dBµV/m @3 m，30 MHz–6 GHz）",
                               "47 CFR Part 15 §15.109(b)"),
            _from_radiated_dict(cispr, "emc_cispr32_classb_radiated",
                                "CISPR 32:2015 Table A.4 Class B 辐射发射限值线"
                                "（dBµV/m QP @3 m，30 MHz–1 GHz）",
                                "CISPR 32:2015"))


#: 任务书原文写法别名（from_emsc_radiated == from_emc_radiated）。
from_emsc_radiated = from_emc_radiated


def _from_radiated_dict(
    ref: dict[str, object], table_id: str, title: str, standard: str
) -> LimitTable:
    det_map = ref["detector"]
    if not isinstance(det_map, dict):
        raise ValueError(f"{table_id}：原表 detector 键不是 dict（{det_map!r}）")
    lines: list[LimitLine] = []
    segs_by_det: dict[str, list[types.MappingProxyType]] = {}
    for seg in ref["segments"]:  # type: ignore[union-attr]
        det = _detector_for_segment(det_map, seg)  # type: ignore[arg-type]
        segs_by_det.setdefault(det, []).append(types.MappingProxyType(dict(seg)))
        lo = float(seg["f_lo_mhz"])  # type: ignore[arg-type]
        hi = float(seg["f_hi_mhz"])  # type: ignore[arg-type]
        source_id = f"{standard} Class {ref['device_class']} {det.upper()} {lo:g}-{hi:g} MHz"
        lines.append(
            _seg_to_line(table_id, source_id, dict(seg), det, "dBuV/m",
                         "field_strength", "3m")
        )
    notes = [str(n) for n in ref.get("notes", [])]  # type: ignore[arg-type]
    if det_map != {"all": "quasi-peak"}:
        notes.append(
            "registry 查询按 detector 过滤后求值（检波感知）；原 radiated_margin "
            "对双闭边界点取全段最小（检波盲）——仅在边界单点可能差一档"
            "（如 960 MHz：det=qp 与原一致=46；det=avg=54 为检波感知口径）。"
        )
    return LimitTable(
        table_id=table_id,
        title=title,
        standard=standard,
        source=str(ref["source"]),
        retrieved=str(ref["retrieved"]),
        lines=tuple(lines),
        family="emc_radiated",
        band_rule="closed_min",
        outside_rule="nan_out_of_band",
        native_kind="emi_fcc_segments",
        native_key={det: tuple(segs) for det, segs in segs_by_det.items()},
        port="radiated field",
        detector_policy="per_line",
        default_quantity="field_strength",
        distance_ref="3m",
        interp_note=(
            "全段 flat；双闭区间逐点取覆盖段最小值；带外 NaN 不判读。求值 "
            "native 委托 emi_filter._eval_fcc_line（与 radiated_margin 逐位"
            "一致）。"
        ),
        notes=tuple(notes),
    )


# ─── 适配器 3：exposure_limits（FCC §1.1310 + ICNIRP 2020 RF 暴露）────────────

_EXPOSURE_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "fcc_occupational",
        "exposure_fcc_occupational",
        "RF 暴露 MPE 限值——FCC §1.1310(e)(1) Table 1 (i) Occupational/Controlled",
        "(i)",
        "47 CFR §1.1310(e)(1) Table 1 MPE 限值（eCFR 当前版实测取表，"
        "2026-09-29 更新版；2026-09-30 逐段回原文核对逐位抄录——"
        "exposure_limits.py 模块 docstring 口径）；S 列 mW/cm² 已 ×10 换算 SI 入库",
    ),
    (
        "fcc_general",
        "exposure_fcc_general",
        "RF 暴露 MPE 限值——FCC §1.1310(e)(1) Table 1 (ii) General Population/Uncontrolled",
        "(ii)",
        "47 CFR §1.1310(e)(1) Table 1 MPE 限值（eCFR 当前版实测取表，"
        "2026-09-29 更新版；2026-09-30 逐段回原文核对逐位抄录）；"
        "公众 30–300 MHz 段 H=0.073 为 eCFR 表原文两位写法",
    ),
    (
        "icnirp_public",
        "exposure_icnirp_public",
        "RF 暴露参考水平——ICNIRP 2020 Table 5 General public（全身平均 30 min）",
        "General public",
        "ICNIRP 2020 Guidelines Table 5 General public 全身平均参考水平"
        "（Health Phys. 118(5):483-524；官方 PDF 本地逐位核对）；"
        "occupational 行不入库（本仓域=公众限值，如实收窄）",
    ),
)


def from_exposure() -> tuple[LimitTable, LimitTable, LimitTable]:
    """收编 exposure_limits 三张 MPE/参考水平表（零迁移）。

    每频段 E/H/S 三列按有值收编为独立 LimitLine（quantity 区分；公式段
    保留原表 formula 元组）；查询值面 native 委托 mpe_limit（round-9 口径
    与原函数逐位一致）。
    """
    tables: list[LimitTable] = []
    for std, table_id, title, row_tag, source in _EXPOSURE_SPECS:
        bands = exposure_limits._STANDARDS[std]  # 只读复用原表常量（零迁移）
        fcc_clause = std.startswith("fcc")
        lines: list[LimitLine] = []
        for band in bands:
            (f_lo, f_hi, e_val, e_form, h_val, h_form, s_val, s_form,
             pw_equiv, _avg_min) = band
            lo, hi = float(f_lo) * 1e6, float(f_hi) * 1e6
            span = f"{f_lo:g}-{f_hi:g} MHz"
            span_id = f"{f_lo:g}-{f_hi:g}MHz"
            for col, const, form, quantity, unit in (
                ("E", e_val, e_form, "e_field", "V/m"),
                ("H", h_val, h_form, "h_field", "A/m"),
                ("S", s_val, s_form, "power_density", "W/m^2"),
            ):
                if const is None and form is None:
                    continue  # 该段该量未列（如 ICNIRP 0.1–30 MHz S=NA）——如实无线
                prefix = (
                    f"47 CFR §1.1310(e)(1) Table 1 {row_tag} {col} {span}"
                    if fcc_clause
                    else f"ICNIRP 2020 Table 5 {row_tag} {col} {span}"
                )
                line_notes: tuple[str, ...] = ()
                if quantity == "power_density" and pw_equiv:
                    line_notes = ("S 列为平面波等效口径（原表脚注 *）",)
                if const is not None:
                    lines.append(LimitLine(
                        line_id=f"{table_id}:{quantity}:{span_id}",
                        f_lo_hz=lo, f_hi_hz=hi, limit_value=float(const),
                        unit=unit, detector="na", distance_ref=None,
                        source_id=prefix, quantity=quantity, interp="flat",
                        limit_value_hi=float(const), notes=line_notes,
                    ))
                else:
                    lines.append(LimitLine(
                        line_id=f"{table_id}:{quantity}:{span_id}",
                        f_lo_hz=lo, f_hi_hz=hi, limit_value=None,
                        unit=unit, detector="na", distance_ref=None,
                        source_id=prefix, quantity=quantity, interp="formula",
                        formula=tuple(form),  # type: ignore[arg-type]
                        notes=line_notes,
                    ))
        tables.append(LimitTable(
            table_id=table_id,
            title=title,
            standard=("47 CFR §1.1310(e)(1) Table 1" if fcc_clause
                      else "ICNIRP 2020 Table 5"),
            source=source,
            retrieved="2026-09-30",
            lines=tuple(lines),
            family="exposure",
            band_rule="half_open_last_closed",
            outside_rule="valueerror_domain_guard",
            native_kind="exposure_mpe",
            native_key=std,
            port=None,
            detector_policy="na",
            default_quantity="e_field",
            interp_note=(
                "段内幂律公式（原表 formula 元组）/常量；[lo, hi) 半开、末段"
                "双闭（原 _find_band 口径）；带外显式 ValueError（越域拒绝不"
                "外推）。查询值面 native 委托 mpe_limit（round-9 口径与原函数"
                "逐位一致）；段未列的量（如 ICNIRP 0.1–30 MHz S=NA）查询返回 "
                "value=None 如实。"
            ),
        ))
    return (tables[0], tables[1], tables[2])


# ─── EM-6 预留键位（本批只留 schema 位，不录数据；PV-012 已 verified）─────────


def _reserved_tables() -> tuple[LimitTable, ...]:
    common = dict(
        family="em6_reserved",
        band_rule="none",
        outside_rule="none",
        native_kind="none",
        detector_policy="per_line",
        retrieved="2026-10-02",
        status="reserved",
    )
    return (
        LimitTable(
            table_id="em6_ts138104_aclr",
            title="3GPP TS 38.104（ETSI TS 138 104）BS ACLR 限值（EM-6 预留键位）",
            standard="3GPP TS 38.104 / ETSI TS 138 104",
            source="ETSI TS 138 104 §6.6.3（ACLR）——PV-012 verified"
                   "（etsi.org TS 138 104 v17.5.0 免费版可核，"
                   "docs/pending_verifications.yaml retrieved 2026-10-02）；"
                   "本批只留 schema 键位不录数据",
            lines=(),
            notes=("EM-6 预留键位：ACLR 为载波相对（dB）+BS class 分层语义，"
                   "非 LimitLine 带线 schema 可承载——数据面在 "
                   "rfauto.core.spur_templates（EM-6 杂散模板库，"
                   "TS 138 104 V17.5.0 §6.6.3 实测录入）；本键位保持 "
                   "reserved 作引用锚，不录带线数据",),
            **common,  # type: ignore[arg-type]
        ),
        LimitTable(
            table_id="em6_ts138104_acs",
            title="3GPP TS 38.104（ETSI TS 138 104）BS ACS 要求（EM-6 预留键位）",
            standard="3GPP TS 38.104 / ETSI TS 138 104",
            source="ETSI TS 138 104 §7.4.1（ACS）——PV-012 verified"
                   "（etsi.org TS 138 104 v17.5.0 免费版可核，"
                   "docs/pending_verifications.yaml retrieved 2026-10-02）；"
                   "本批只留 schema 键位不录数据",
            lines=(),
            notes=("EM-6 预留键位：ACS 为接收机等级分层（BS class）语义，"
                   "非 LimitLine 带线 schema 可承载——数据面在 "
                   "rfauto.core.spur_templates（EM-6 杂散模板库，"
                   "TS 138 104 V17.5.0 §7.4.1 实测录入）；本键位保持 "
                   "reserved 作引用锚，不录带线数据",),
            **common,  # type: ignore[arg-type]
        ),
    )


# ─── registry 与查询 ──────────────────────────────────────────────────────────

_REGISTRY: dict[str, LimitTable] = {}


def _build_registry() -> dict[str, LimitTable]:
    reg: dict[str, LimitTable] = {}
    for table in (
        from_emi_filter(class_b=True),
        from_emi_filter(class_b=False),
        *from_emc_radiated(),
        *from_exposure(),
        *_reserved_tables(),
    ):
        if table.table_id in reg:
            raise ValueError(f"limit table_id 重复：{table.table_id}")
        reg[table.table_id] = table
    return reg


_REGISTRY = _build_registry()


def get_limit_table(table_id: str) -> LimitTable:
    """按 id 取表；未知 id → LookupError（列可用 id）。"""
    try:
        return _REGISTRY[table_id]
    except KeyError:
        raise LookupError(
            f"未知限值表 {table_id!r}（可用：{sorted(_REGISTRY)}）"
        ) from None


def list_limit_tables(include_reserved: bool = True) -> tuple[LimitTable, ...]:
    """列出全部限值表（stable 顺序；include_reserved=False 剔除预留键位）。"""
    return tuple(
        t for t in _REGISTRY.values()
        if include_reserved or t.status == "active"
    )


def _generic_line_value(line: LimitLine, f_hz: float) -> float:
    """registry 线面通用求值（线选择/防御性核对用；返回值以 native 为准）。"""
    if line.interp == "log_linear":
        if line.limit_value is None or line.limit_value_hi is None:
            raise ValueError(f"log_linear 线端值缺失：{line.line_id}")
        lo = line.f_lo_hz / 1e6
        hi = line.f_hi_hz / 1e6
        frac = math.log10((f_hz / 1e6) / lo) / math.log10(hi / lo)
        return line.limit_value + (line.limit_value_hi - line.limit_value) * frac
    if line.interp == "formula":
        return float(exposure_limits._eval_formula(line.formula, f_hz / 1e6))
    return float(line.limit_value)  # type: ignore[arg-type]


def _native_emi_value(segs: object, f_hz: float) -> float:
    """native 委托 emi_filter._eval_fcc_line（单点；与 margin_report 逐位一致）。"""
    arr = np.array([f_hz / 1e6], dtype=float)
    return float(emi_filter._eval_fcc_line(list(segs), arr)[0])  # type: ignore[arg-type]


def _query_emi(
    table: LimitTable,
    f_hz: float,
    detector: str | None,
    quantity: str | None,
) -> dict[str, object]:
    q = quantity if quantity is not None else table.default_quantity
    if q is None:
        q = table.lines[0].quantity
    lines = [ln for ln in table.lines if ln.quantity == q]
    if not lines:
        raise ValueError(
            f"{table.table_id} 无 quantity={q!r} 的线"
            f"（可用：{sorted({ln.quantity for ln in table.lines})}）"
        )
    if detector is not None:
        det = _canon_detector(detector)
        if det == "na":
            raise ValueError(f"{table.table_id} 为检波维表，detector 不能为 'na'")
        lines = [ln for ln in lines if ln.detector == det]
    cov = [ln for ln in lines if ln.f_lo_hz <= f_hz <= ln.f_hi_hz]
    dets = sorted({ln.detector for ln in cov})
    if detector is None and len(dets) > 1:
        raise LookupError(
            f"{table.table_id} f={f_hz:g} Hz 被多检波线覆盖（{dets}）——"
            "双闭边界歧义，须显式传 detector"
        )
    if not cov:
        raise LookupError(
            f"{table.table_id} f={f_hz:g} Hz 无覆盖线"
            f"（detector={detector!r}；带外——原表语义 NaN 不判读，"
            "单点查询面显式拒绝）"
        )
    det = dets[0]
    if table.native_key is None or det not in table.native_key:
        raise RuntimeError(
            f"{table.table_id} native 求值上下文缺检波 {det!r}"
            f"（native_key={type(table.native_key).__name__}）"
        )
    val = _native_emi_value(table.native_key[det], f_hz)
    if math.isnan(val):
        raise LookupError(
            f"{table.table_id} f={f_hz:g} Hz 带外（原表语义 NaN 不判读）"
        )
    best: tuple[float, LimitLine] | None = None
    for line in cov:
        v = _generic_line_value(line, f_hz)
        if best is None or v < best[0]:
            best = (v, line)
    if best is None or abs(best[0] - val) > 1e-12 * max(1.0, abs(val)):
        raise RuntimeError(
            f"registry 线面与原求值器失配（{table.table_id} @ {f_hz:g} Hz）："
            f"generic={best[0]!r} native={val!r}"
        )
    line = best[1]
    return {
        "table_id": table.table_id,
        "line_id": line.line_id,
        "f_hz": f_hz,
        "value": val,
        "unit": line.unit,
        "detector": det,
        "quantity": line.quantity,
        "source_id": line.source_id,
        "standard": table.standard,
        "family": table.family,
        "retrieved": table.retrieved,
        "interp": line.interp,
        "band_rule": table.band_rule,
        "outside_rule": table.outside_rule,
        "distance_ref": line.distance_ref if line.distance_ref else table.distance_ref,
        "port": table.port,
        "title": table.title,
        "source": table.source,
    }


def _query_exposure(
    table: LimitTable,
    f_hz: float,
    detector: str | None,
    quantity: str | None,
) -> dict[str, object]:
    if detector is not None and _canon_detector(detector) != "na":
        raise ValueError(
            f"{table.table_id} 为暴露限值表（无检波维度，detector 固定 na），"
            f"收到 {detector!r}"
        )
    q = quantity if quantity is not None else table.default_quantity
    if q not in _EXPOSURE_QUANTITIES:
        raise ValueError(
            f"quantity {q!r} 非法（允许：{sorted(_EXPOSURE_QUANTITIES)}）"
        )
    col, unit = _EXPOSURE_QUANTITIES[q]
    # native 委托原 mpe_limit：带外 ValueError（越域拒绝不外推）原样传播；
    # 返回值=原函数 round-9 口径（事实兼容）。
    ref = exposure_limits.mpe_limit(f_hz, standard=str(table.native_key))
    val = ref[col]
    band = ref["band_mhz"]
    lo_hz, hi_hz = float(band[0]) * 1e6, float(band[1]) * 1e6
    line = next(
        (
            ln for ln in table.lines
            if ln.quantity == q and ln.f_lo_hz == lo_hz and ln.f_hi_hz == hi_hz
        ),
        None,
    )
    if val is None and line is not None:
        raise RuntimeError(
            f"{table.table_id} 线面与原表失配：{q} 在段 "
            f"[{lo_hz / 1e6:g}, {hi_hz / 1e6:g}] MHz 原表未列但 registry 有线"
        )
    return {
        "table_id": table.table_id,
        "line_id": None if val is None else (line.line_id if line else None),
        "f_hz": f_hz,
        "value": None if val is None else float(val),
        "unit": unit,
        "detector": "na",
        "quantity": q,
        "source_id": None if line is None else line.source_id,
        "standard": table.standard,
        "family": table.family,
        "retrieved": table.retrieved,
        "interp": line.interp if line else "none",
        "band_rule": table.band_rule,
        "outside_rule": table.outside_rule,
        "band_mhz": [float(band[0]), float(band[1])],
        "averaging_time_min": ref["averaging_time_min"],
        "plane_wave_equiv_s": ref["plane_wave_equiv_s"],
        "native": ref,
        "title": table.title,
        "source": table.source,
    }


def limits_query(
    table_id: str,
    f_hz: float,
    detector: str | None = None,
    quantity: str | None = None,
) -> dict[str, object]:
    """单点查值：table_id + 频率（Hz）→ {value, unit, line_id, source_id, ...}。

    值面 native 委托原模块求值器（emi_filter._eval_fcc_line /
    exposure_limits.mpe_limit）——与既有消费者逐位一致（事实兼容零迁移）；
    line_id/source_id 溯源随行。

    Args:
        table_id: 限值表 id（见 list_limit_tables）。
        f_hz: 频率 Hz（>0 有限；exposure 表带外 ValueError 原样传播，
            emi/emc 表带外 LookupError——原表 NaN 不判读语义的单点映射）。
        detector: "peak"|"qp"|"avg"（quasi-peak/average 别名可）；多检波表
            （§15.107 传导）必选；单检波表可省；边界双闭歧义点须显式。
        quantity: 暴露表为 "e_field"|"h_field"|"power_density"（缺省
            e_field）；emi/emc 表缺省（conducted_voltage / field_strength）。

    Returns:
        dict：{"table_id","line_id","f_hz","value","unit","detector",
        "quantity","source_id","standard","family","retrieved","interp",
        "band_rule","outside_rule",...}；exposure 另含 band_mhz/
        averaging_time_min/plane_wave_equiv_s/native（原 mpe_limit 全量
        dict）。预留键位（EM-6）→ LookupError。

    Raises:
        LookupError: 未知表 / 带外 / 多检波歧义 / 预留键位。
        ValueError: 非法参数（detector/quantity/f_hz）或原表域守卫
            （exposure 带外）。
    """
    table = get_limit_table(table_id)
    if table.status == "reserved":
        raise LookupError(
            f"{table_id} 是预留键位（status=reserved，EM-6 本批只留 schema 位"
            f"不录数据）：{table.notes[0] if table.notes else ''}"
        )
    f = float(f_hz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"f_hz 必须 >0 且有限，收到 {f_hz!r}")
    if table.native_kind == "exposure_mpe":
        return _query_exposure(table, f, detector, quantity)
    if table.native_kind == "emi_fcc_segments":
        return _query_emi(table, f, detector, quantity)
    raise RuntimeError(f"{table_id}：未知 native_kind {table.native_kind!r}")


#: 段 kind 白名单（_seg_to_line 校验用；模块级常量供测试/审计引用）。
SEG_KINDS = ("flat", "log_linear")
