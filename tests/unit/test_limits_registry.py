"""EM-10 core/limits_registry 单测（统一 schema + 三适配器 + native 逐位一致性）。

一致性裁判（#118 双路径/独立常数纪律）：registry 查询值 native 委托原模块
求值器（emi_filter._eval_fcc_line / exposure_limits.mpe_limit）；本文件对拍
三路——①原函数公开面（margin_report / radiated_margin / mpe_limit）逐位；
②测试文件内独立键入的标准值面（47 CFR §15.107/§15.109(b)、CISPR 32
Table A.4、FCC §1.1310 Table 1、ICNIRP 2020 Table 5，不经被测模块）；
③exposure 幂律常数独立复算（容差=原函数 round-9 舍入带 5.1e-9）。
≥10 点/表；边界（双闭内边界取最小/半开/末段闭）、带外拒绝、检波歧义、
EM-6 预留键位、schema/溯源完整性全钉。
"""

import copy
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import emc_radiated as er
from rfauto.core import emi_filter as ef
from rfauto.core import exposure_limits as el
from rfauto.core import limits_registry as lr

# ── 测试文件内独立值面（#118：不从被测模块取数，逐值键自标准文本）─────────────


def _expected_fcc107(f_mhz: float, class_b: bool, det: str) -> float:
    """47 CFR §15.107 传导发射限值（eCFR 现行文本口径；双闭区间取覆盖段最小）。"""
    qp_b = [(0.15, 0.5, 66.0, 56.0, "ll"), (0.5, 5.0, 56.0, 56.0, "flat"),
            (5.0, 30.0, 60.0, 60.0, "flat")]
    avg_b = [(0.15, 0.5, 56.0, 46.0, "ll"), (0.5, 5.0, 46.0, 46.0, "flat"),
             (5.0, 30.0, 50.0, 50.0, "flat")]
    qp_a = [(0.15, 0.5, 79.0, 79.0, "flat"), (0.5, 30.0, 73.0, 73.0, "flat")]
    avg_a = [(0.15, 0.5, 66.0, 66.0, "flat"), (0.5, 30.0, 60.0, 60.0, "flat")]
    segs = {(True, "qp"): qp_b, (True, "avg"): avg_b,
            (False, "qp"): qp_a, (False, "avg"): avg_a}[(class_b, det)]
    vals = []
    for lo, hi, v_lo, v_hi, kind in segs:
        if lo <= f_mhz <= hi:
            if kind == "ll":
                frac = math.log10(f_mhz / lo) / math.log10(hi / lo)
                vals.append(v_lo + (v_hi - v_lo) * frac)
            else:
                vals.append(v_lo)
    return min(vals) if vals else float("nan")


def _expected_fcc109b(f_mhz: float) -> float:
    """47 CFR §15.109(b) Class B 辐射发射限值（dBµV/m @3 m；QP 行，双闭取最小）。"""
    vals = [v for lo, hi, v in ((30.0, 88.0, 40.0), (88.0, 216.0, 43.5),
                                (216.0, 960.0, 46.0), (960.0, 6000.0, 54.0))
            if lo <= f_mhz <= hi]
    return min(vals) if vals else float("nan")


def _expected_cispr32(f_mhz: float) -> float:
    """CISPR 32:2015 Table A.4 Class B（dBµV/m QP @3 m）。"""
    vals = [v for lo, hi, v in ((30.0, 230.0, 40.0), (230.0, 1000.0, 47.0))
            if lo <= f_mhz <= hi]
    return min(vals) if vals else float("nan")


def _orig_eval_fcc_line(segs, f_hz: float) -> float:
    """原模块求值器（接线核对通道；registry native 委托同源 → 应逐位相等）。"""
    return float(ef._eval_fcc_line(list(segs), np.array([f_hz / 1e6]))[0])


# ── 1. registry 目录与 schema 完整性 ──────────────────────────────────────────

_ACTIVE_TABLE_LINE_COUNTS = {
    "emi_fcc_part15_conducted_class_b": 6,   # QP 3 段 + Avg 3 段
    "emi_fcc_part15_conducted_class_a": 4,   # QP 2 段 + Avg 2 段
    "emc_fcc_part15b_radiated_class_b": 4,   # 3 QP + 1 avg
    "emc_cispr32_classb_radiated": 2,
    "exposure_fcc_occupational": 11,         # E3+H3+S5
    "exposure_fcc_general": 11,
    "exposure_icnirp_public": 9,             # E4+H4+S... E2+H3+S4=9（段列缺失如实收窄）
}
_RESERVED_IDS = {"em6_ts138104_aclr", "em6_ts138104_acs"}


def test_registry_catalog_schema_integrity():
    tables = lr.list_limit_tables()
    active = [t for t in tables if t.status == "active"]
    assert {t.table_id for t in active} == set(_ACTIVE_TABLE_LINE_COUNTS)
    counts = {t.table_id: len(t.lines) for t in active}
    assert counts == _ACTIVE_TABLE_LINE_COUNTS
    assert {t.table_id for t in tables if t.status == "reserved"} == _RESERVED_IDS
    for t in active:
        assert t.lines and t.source and re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.retrieved)
        assert t.band_rule in ("closed_min", "half_open_last_closed")
        for line in t.lines:
            assert 0.0 < line.f_lo_hz < line.f_hi_hz
            assert line.detector in lr.DETECTOR_TOKENS
            assert line.unit in lr.UNIT_TOKENS
            assert line.source_id, (t.table_id, line.line_id)
            assert line.quantity in ("conducted_voltage", "field_strength",
                                     "e_field", "h_field", "power_density")
            if line.interp in ("flat", "log_linear"):
                assert line.limit_value is not None
            else:
                assert line.interp == "formula"
                assert line.limit_value is None and line.formula is not None
            if line.interp == "flat":
                assert line.limit_value_hi == line.limit_value
        if t.family == "emc_radiated":
            assert all(ln.distance_ref == "3m" and ln.unit == "dBuV/m"
                       and ln.detector in ("qp", "avg") for ln in t.lines)
        if t.family == "exposure":
            assert all(ln.detector == "na" for ln in t.lines)
            assert t.default_quantity in lr._EXPOSURE_QUANTITIES
        if t.family == "emi_conducted":
            assert all(ln.interp in lr.SEG_KINDS for ln in t.lines)
            assert any(ln.interp == "log_linear" for ln in t.lines) is t.table_id.endswith("_b")


def test_task_literal_alias_and_list_filter():
    assert lr.from_emsc_radiated is lr.from_emc_radiated
    ids_active = {t.table_id for t in lr.list_limit_tables(include_reserved=False)}
    assert ids_active.isdisjoint(_RESERVED_IDS)
    assert {t.table_id for t in lr.list_limit_tables()} >= _RESERVED_IDS


def test_adapters_are_zero_migration_readonly():
    before_b = copy.deepcopy(ef.fcc_limits_part15(True))
    before_a = copy.deepcopy(ef.fcc_limits_part15(False))
    before_rad = copy.deepcopy(er.fcc_part15b_radiated_limits())
    before_cispr = copy.deepcopy(er.cispr32_classb_radiated_limits())
    before_std = copy.deepcopy(el._STANDARDS)
    lr.from_emi_filter(True)
    lr.from_emi_filter(False)
    lr.from_emc_radiated()
    lr.from_exposure()
    assert ef.fcc_limits_part15(True) == before_b
    assert ef.fcc_limits_part15(False) == before_a
    assert er.fcc_part15b_radiated_limits() == before_rad
    assert er.cispr32_classb_radiated_limits() == before_cispr
    assert before_std == el._STANDARDS
    # 原函数键面事实兼容（segments schema 未动）
    assert {"segments_qp", "segments_avg", "source", "retrieved"} <= set(before_b)
    # registry native 段为只读映射（防消费者改库）
    segs = lr.get_limit_table("emi_fcc_part15_conducted_class_b").native_key["qp"]
    with pytest.raises(TypeError):
        segs[0]["f_lo_mhz"] = 1.0  # type: ignore[index]


# ── 2. emi_filter 适配：§15.107 传导（三路对拍，≥10 点/表/检波）────────────────


def test_emi_conducted_consistency_three_way():
    pts_b = [0.15, 0.2, 0.25, 0.3, 0.5, 1.0, 3.0, 5.0, 7.7, 10.0, 20.0, 29.9999, 30.0]
    pts_a = [0.15, 0.2, 0.3, 0.5, 1.0, 5.0, 10.0, 20.0, 25.0, 30.0]
    for class_b, pts in ((True, pts_b), (False, pts_a)):
        table_id = f"emi_fcc_part15_conducted_class_{'b' if class_b else 'a'}"
        ref = ef.fcc_limits_part15(class_b=class_b)
        assert len(pts) >= 10
        for det, key in (("qp", "segments_qp"), ("avg", "segments_avg")):
            for fm in pts:
                f_hz = fm * 1e6
                q = lr.limits_query(table_id, f_hz, detector=det)
                # ① 原求值器逐位（接线核对：段映射/Hz 换算/边界）
                assert q["value"] == _orig_eval_fcc_line(ref[key], f_hz), (table_id, det, fm)
                # ② 测试文件独立值面（#118 不自证）
                assert q["value"] == pytest.approx(
                    _expected_fcc107(fm, class_b, det), rel=1e-12), (table_id, det, fm)
                assert q["unit"] == "dBuV" and q["detector"] == det
                assert q["quantity"] == "conducted_voltage"
                assert q["source_id"].startswith(f"47 CFR §15.107({'a' if class_b else 'b'})")


def test_emi_boundary_min_rule_and_log_linear_and_out_of_band():
    # B-QP 内边界 5 MHz：两段（56/60）双闭覆盖取最小=56（"lower limit applies"）
    q = lr.limits_query("emi_fcc_part15_conducted_class_b", 5.0e6, detector="qp")
    assert q["value"] == 56.0
    assert q["line_id"] == "emi_fcc_part15_conducted_class_b:qp:0.5-5MHz"
    assert q["source_id"] == "47 CFR §15.107(a) Class B QP 0.5-5 MHz"
    assert q["interp"] == "flat"
    # log_linear 段（0.15–0.5 MHz QP 66→56）单点抽检
    q2 = lr.limits_query("emi_fcc_part15_conducted_class_b", 0.25e6, detector="qp")
    assert q2["interp"] == "log_linear"
    assert q2["line_id"] == "emi_fcc_part15_conducted_class_b:qp:0.15-0.5MHz"
    expect = 66.0 + (56.0 - 66.0) * math.log10(0.25 / 0.15) / math.log10(0.5 / 0.15)
    assert q2["value"] == pytest.approx(expect, rel=1e-12)
    # 带外（原表 NaN 不判读语义 → 单点查询面显式 LookupError）
    for f in (0.1e6, 30.0001e6, 100e6):
        with pytest.raises(LookupError, match="带外"):
            lr.limits_query("emi_fcc_part15_conducted_class_b", f, detector="qp")


def test_emi_margin_report_crosscheck_avg_envelope():
    """公开消费面 margin_report（dict 路径取 segments_avg 保守包络）逐位对拍。"""
    ref = ef.fcc_limits_part15(True)
    f_hz = np.array([0.2e6, 0.5e6, 2.0e6, 10e6, 30e6])
    res = ef.margin_report(f_hz, np.zeros(5), ref)
    assert res["detector"] == "avg_envelope"
    for i, f in enumerate(f_hz):
        q = lr.limits_query("emi_fcc_part15_conducted_class_b", float(f), detector="avg")
        assert q["value"] == float(res["limit_dbuv"][i]), float(f)


# ── 3. emc_radiated 适配：§15.109(b) + CISPR 32（≥10 点/表）───────────────────


def test_emc_radiated_consistency_vs_radiated_margin():
    fcc_pts = [30.0, 45.0, 88.0, 150.0, 216.0, 400.0, 959.9999, 960.0, 1200.0, 6000.0]
    cispr_pts = [30.0, 45.0, 60.0, 100.0, 229.9999, 230.0, 400.0, 700.0, 999.9999, 1000.0]
    ref = er.fcc_part15b_radiated_limits()
    res = er.radiated_margin(np.array([f * 1e6 for f in fcc_pts]),
                             np.zeros(len(fcc_pts)), ref)
    for i, fm in enumerate(fcc_pts):
        det = "qp" if fm <= 960.0 else None  # >960 仅 avg 覆盖，det 可省
        q = lr.limits_query("emc_fcc_part15b_radiated_class_b", fm * 1e6, detector=det)
        assert q["value"] == float(res["limit_dbuv"][i]), fm  # 公开面逐位
        assert q["value"] == pytest.approx(_expected_fcc109b(fm), rel=1e-12), fm
        assert q["unit"] == "dBuV/m" and q["distance_ref"] == "3m"
        assert q["quantity"] == "field_strength"
    ref = er.cispr32_classb_radiated_limits()
    res = er.radiated_margin(np.array([f * 1e6 for f in cispr_pts]),
                             np.zeros(len(cispr_pts)), ref)
    for i, fm in enumerate(cispr_pts):
        q = lr.limits_query("emc_cispr32_classb_radiated", fm * 1e6)
        assert q["value"] == float(res["limit_dbuv"][i]), fm
        assert q["value"] == pytest.approx(_expected_cispr32(fm), rel=1e-12), fm
        assert q["detector"] == "qp"


def test_emc_radiated_detector_edge_semantics():
    # 960 MHz 双闭边界：det=qp=46 与原检波盲最小值一致；det=avg=54 为检波感知口径
    # （表 notes 文档化的单点差异）
    assert lr.limits_query("emc_fcc_part15b_radiated_class_b", 960e6,
                           detector="qp")["value"] == 46.0
    assert lr.limits_query("emc_fcc_part15b_radiated_class_b", 960e6,
                           detector="avg")["value"] == 54.0
    with pytest.raises(LookupError, match="多检波"):
        lr.limits_query("emc_fcc_part15b_radiated_class_b", 960e6)
    q = lr.limits_query("emc_fcc_part15b_radiated_class_b", 2000e6)
    assert q["value"] == 54.0 and q["detector"] == "avg"
    q = lr.limits_query("emc_fcc_part15b_radiated_class_b", 935e6)
    assert q["line_id"] == "emc_fcc_part15b_radiated_class_b:qp:216-960MHz"
    assert q["source_id"] == "47 CFR Part 15 §15.109(b) Class B QP 216-960 MHz"


# ── 4. exposure 适配：mpe_limit 逐位 + 幂律独立复算（≥10 点/表）────────────────

_EXPOSURE_PLANS = (
    ("exposure_fcc_occupational", "fcc_occupational",
     [0.4e6, 2.0e6, 5e6, 29.9e6, 30e6, 100e6, 299e6, 500e6, 1000e6,
      1499.9e6, 1500e6, 99999e6, 100000e6]),
    ("exposure_fcc_general", "fcc_general",
     [0.4e6, 1.0e6, 1.34e6, 2.0e6, 10e6, 29.999e6, 30e6, 100e6, 299.9e6,
      300e6, 700e6, 1499e6, 1500e6, 100000e6]),
    ("exposure_icnirp_public", "icnirp_public",
     [0.1e6, 1e6, 10e6, 29.9e6, 30e6, 399.9e6, 400e6, 900e6, 1999.9e6,
      2000e6, 300000e6]),
)


def test_exposure_consistency_vs_mpe_limit_bitwise():
    cols = {"e_field": "e_v_per_m", "h_field": "h_a_per_m",
            "power_density": "s_w_per_m2"}
    for table_id, std, freqs in _EXPOSURE_PLANS:
        assert len(freqs) >= 10
        for f in freqs:
            ref = el.mpe_limit(f, standard=std)
            for qn, col in cols.items():
                got = lr.limits_query(table_id, f, quantity=qn)
                if ref[col] is None:
                    assert got["value"] is None and got["line_id"] is None
                    continue
                # 逐位（查询值面=原函数 round-9 口径）
                assert got["value"] == ref[col], (table_id, f, qn)
                assert got["unit"] == {"e_field": "V/m", "h_field": "A/m",
                                       "power_density": "W/m^2"}[qn]
                assert got["band_mhz"] == ref["band_mhz"]
                assert got["averaging_time_min"] == ref["averaging_time_min"]


def test_exposure_independent_formula_recompute():
    """幂律常数测试文件内独立键入（容差=原函数 round-9 舍入带）。"""
    cases = (
        ("exposure_fcc_general", 10.0e6, "e_field", 824.0 / 10.0),
        ("exposure_fcc_general", 10.0e6, "h_field", 2.19 / 10.0),
        ("exposure_fcc_general", 10.0e6, "power_density", 1800.0 / 100.0),
        ("exposure_fcc_general", 700.0e6, "power_density", 700.0 / 150.0),
        ("exposure_fcc_general", 50.0e6, "e_field", 27.5),
        ("exposure_fcc_occupational", 2.0e6, "e_field", 614.0),
        ("exposure_fcc_occupational", 2.0e6, "h_field", 1.63),
        ("exposure_fcc_occupational", 2.0e6, "power_density", 1000.0),
        ("exposure_fcc_occupational", 5.0e6, "e_field", 1842.0 / 5.0),
        ("exposure_fcc_occupational", 5.0e6, "h_field", 4.89 / 5.0),
        ("exposure_fcc_occupational", 5.0e6, "power_density", 9000.0 / 25.0),
        ("exposure_fcc_occupational", 100.0e6, "e_field", 61.4),
        ("exposure_fcc_occupational", 2000.0e6, "power_density", 50.0),
        ("exposure_icnirp_public", 1.0e6, "e_field", 300.0 / 1.0 ** 0.7),
        ("exposure_icnirp_public", 1.0e6, "h_field", 2.2 / 1.0),
        ("exposure_icnirp_public", 100.0e6, "e_field", 27.7),
        ("exposure_icnirp_public", 900.0e6, "e_field", 1.375 * 30.0),
        ("exposure_icnirp_public", 900.0e6, "power_density", 900.0 / 200.0),
        ("exposure_icnirp_public", 5000.0e6, "power_density", 10.0),
    )
    for table_id, f, qn, expected in cases:
        got = lr.limits_query(table_id, f, quantity=qn)
        assert got["value"] == pytest.approx(expected, abs=5.1e-9), (table_id, f, qn)


def test_exposure_domain_guard_and_na_and_extras():
    for table_id, f in (
        ("exposure_fcc_general", 0.29e6),
        ("exposure_fcc_general", 100001e6),
        ("exposure_icnirp_public", 0.09e6),
        ("exposure_icnirp_public", 300001e6),
    ):
        with pytest.raises(ValueError, match="定义域外"):
            lr.limits_query(table_id, f)  # 原表越域拒绝不外推，原样传播
    got = lr.limits_query("exposure_icnirp_public", 1e6, quantity="power_density")
    assert got["value"] is None and got["line_id"] is None  # 段未列（S=NA）如实
    assert got["unit"] == "W/m^2"
    got = lr.limits_query("exposure_fcc_general", 100e6)
    assert got["averaging_time_min"] == 30.0
    assert got["plane_wave_equiv_s"] is True
    assert got["band_mhz"] == [30.0, 300.0]
    assert got["native"]["e_v_per_m"] == 27.5
    # 半开区间边界归属：1.34 MHz 落第二段（[1.34, 30)），非 614 V/m 段
    got = lr.limits_query("exposure_fcc_general", 1.34e6)
    assert got["band_mhz"] == [1.34, 30.0]
    assert got["value"] == pytest.approx(824.0 / 1.34, abs=5.1e-9)
    # 末段双闭：ICNIRP 300 GHz 落 [2000, 300000] MHz 闭端
    got = lr.limits_query("exposure_icnirp_public", 300000e6, quantity="power_density")
    assert got["value"] == 10.0


# ── 5. 溯源完整性 ─────────────────────────────────────────────────────────────


def test_provenance_source_and_retrieved_per_line():
    expectations = {
        "emi_fcc_part15_conducted_class_b": ("2026-09-26", "47 CFR"),
        "emi_fcc_part15_conducted_class_a": ("2026-09-26", "47 CFR"),
        "emc_fcc_part15b_radiated_class_b": ("2026-09-27", "47 CFR"),
        "emc_cispr32_classb_radiated": ("2026-09-27", "CISPR"),
        "exposure_fcc_occupational": ("2026-09-30", "47 CFR"),
        "exposure_fcc_general": ("2026-09-30", "47 CFR"),
        "exposure_icnirp_public": ("2026-09-30", "ICNIRP"),
    }
    for tid, (retrieved, marker) in expectations.items():
        t = lr.get_limit_table(tid)
        assert t.retrieved == retrieved, tid
        assert marker in t.source, tid
        for line in t.lines:
            assert line.source_id.count(marker) >= 1, (tid, line.source_id)
    # 逐线 source_id 携带表号/条款行（抽查格式）
    t = lr.get_limit_table("emc_cispr32_classb_radiated")
    assert t.lines[0].source_id == "CISPR 32:2015 Class B QP 30-230 MHz"
    t = lr.get_limit_table("exposure_icnirp_public")
    assert all(ln.source_id.startswith("ICNIRP 2020 Table 5 General public")
               for ln in t.lines)
    t = lr.get_limit_table("emi_fcc_part15_conducted_class_a")
    assert any(ln.source_id == "47 CFR §15.107(b) Class A AVG 0.5-30 MHz"
               for ln in t.lines)


# ── 6. EM-6 预留键位（PV-012 已 verified；本批 schema 位不录数据）──────────────


def test_em6_reserved_slots_present_but_query_refuses():
    for tid, clause in (("em6_ts138104_aclr", "§6.6.3"),
                        ("em6_ts138104_acs", "§7.4.1")):
        t = lr.get_limit_table(tid)
        assert t.status == "reserved" and t.lines == ()
        assert clause in t.source and "PV-012" in t.source
        assert "138 104" in t.standard
        with pytest.raises(LookupError, match="reserved"):
            lr.limits_query(tid, 3.5e9)


# ── 7. 参数守卫 ───────────────────────────────────────────────────────────────


def test_query_argument_guards():
    with pytest.raises(LookupError, match="未知限值表"):
        lr.limits_query("nope", 1e6)
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="必须 >0 且有限"):
            lr.limits_query("emc_cispr32_classb_radiated", bad)
    # 多检波表 det 必选（QP/Avg 全带重叠）
    with pytest.raises(LookupError, match="多检波"):
        lr.limits_query("emi_fcc_part15_conducted_class_b", 1e6)
    with pytest.raises(ValueError, match="未知 detector"):
        lr.limits_query("emi_fcc_part15_conducted_class_b", 1e6, detector="bogus")
    with pytest.raises(ValueError, match="quantity"):
        lr.limits_query("emi_fcc_part15_conducted_class_b", 1e6,
                        detector="qp", quantity="e_field")
    # 检波在带无覆盖
    with pytest.raises(LookupError):
        lr.limits_query("emc_fcc_part15b_radiated_class_b", 100e6, detector="avg")
    # 暴露表无检波维度 / quantity 白名单
    with pytest.raises(ValueError, match="暴露限值表"):
        lr.limits_query("exposure_fcc_general", 1e6, detector="qp")
    with pytest.raises(ValueError, match="quantity"):
        lr.limits_query("exposure_fcc_general", 1e6, quantity="vswr")
