"""EM-6 core/spur_templates 单测（TS 138 104 数据面抽检 + 模板评估 + ACIR 回收）。

一致性裁判（#118 独立常数纪律）：数据面抽检值全部在**测试文件内独立键入**
（自 ETSI TS 138 104 V17.5.0 免费 PDF 原文抄录，不经被测模块；PDF/提取件
留档 runs/em6/，2026-10-02 实测）——抽检 ≥8 值覆盖 §6.6.3（ACLR/CACLR 相
对+绝对）与 §7.4.1（ACS 干扰限值+频偏）。模板正例/负例（已知合规/违例各
≥1）、ACIR 合成式回收（独立式+手算锚）、C/I 与 IM=C/(N+I) 闭式锚、未知
standard/bs_class/band_scope 负例、与 limits_registry 预留键位关系钉、模块
独立 import 面（ast）全钉。
"""

import ast
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import limits_registry as lr
from rfauto.core import spur_templates as st

# ── 测试文件内独立值面（#118：不从被测模块取数；自标准文本逐位键入）─────────

# TS 138 104 V17.5.0 §6.6.3.2 Table 6.6.3.2-1 / -1a / -2 / -3 / -3aa / -3a
# §7.4.1.2 Table 7.4.1.2-1 / -1a / -2（抄录自 runs/em6/ 提取件，2026-10-02）
_EXP_ACLR_REL = {
    ("aclr", "standard", "first", "nr"): 45.0,
    ("aclr", "standard", "second", "nr"): 45.0,
    ("aclr", "standard", "first", "eutra"): 45.0,
    ("aclr", "standard", "second", "eutra"): 45.0,
    ("aclr", "n46_n96_n102", "first", "nr"): 35.0,
    ("aclr", "n46_n96_n102", "second", "nr"): 40.0,
}
_EXP_ABS = {  # Table 6.6.3.2-2 与 6.6.3.2-3a 同值
    "cat_a_wide_area": -13.0,
    "cat_b_wide_area": -15.0,
    "medium_range": -25.0,
    "local_area": -32.0,
}
_EXP_ACS = {  # Table 7.4.1.2-1 / -1a
    ("standard", "wide_area"): -52.0,
    ("standard", "medium_range"): -47.0,
    ("standard", "local_area"): -44.0,
    ("n46_n96_n102", "medium_range"): -47.0,
    ("n46_n96_n102", "local_area"): -44.0,
}
_EXP_ACS_OFF = {  # Table 7.4.1.2-2（standard 域 15 行全录）
    5.0: 2.5025, 10.0: 2.5075, 15.0: 2.5125, 20.0: 2.5025,
    25.0: 9.4675, 30.0: 9.4725, 35.0: 9.4625, 40.0: 9.4675,
    45.0: 9.4725, 50.0: 9.4625, 60.0: 9.4725, 70.0: 9.4675,
    80.0: 9.4625, 90.0: 9.4725, 100.0: 9.4675,
}
_EXP_ACS_OFF_N46 = {10.0: 9.4675, 20.0: 9.4625, 40.0: 9.4675,
                    60.0: 9.4725, 80.0: 9.4625}


def _acir_expected(aclr_db: float, acs_db: float) -> float:
    """独立复算式（与被测实现 10^(−x/10) 形态不同路：1/(1/A+1/S) 线性比）。"""
    aclr_lin = 10.0 ** (aclr_db / 10.0)
    acs_lin = 10.0 ** (acs_db / 10.0)
    return 10.0 * math.log10(1.0 / (1.0 / aclr_lin + 1.0 / acs_lin))


# ── 1. 数据面抽检（≥8 值 vs 条款原文；本文件 ≥60 值）────────────────────────


def test_data_plane_standard_spot_check_against_clauses():
    assert len(st.STANDARD_TOKENS) == 1
    # §6.6.3.2 Table 6.6.3.2-1：NR 1st/2nd 均 45 dB
    r = st.aclr_relative_limit("aclr", "standard", "first")
    assert r.limit_db == _EXP_ACLR_REL[("aclr", "standard", "first", "nr")]
    assert r.source_id.endswith("Table 6.6.3.2-1 row 1（NR 1st 相邻道）")
    r = st.aclr_relative_limit("aclr", "standard", "second")
    assert r.limit_db == _EXP_ACLR_REL[("aclr", "standard", "second", "nr")]
    # Table 6.6.3.2-1 row 3/4（E-UTRA，Note 3）：45 dB + Square(4.5 MHz)
    eutra = [x for x in st.ACLR_RELATIVE if x.assumed_adjacent == "5 MHz E-UTRA"]
    assert len(eutra) == 2
    assert {x.limit_db for x in eutra} == {45.0}
    assert {x.measurement_filter for x in eutra} == {"square (4.5 MHz)"}
    assert {x.offset_rule for x in eutra} == {"bw_channel/2+2.5mhz",
                                              "bw_channel/2+7.5mhz"}
    assert all("Note 3" in x.source_id for x in eutra)
    # Table 6.6.3.2-1a（n46/n96/n102）：1st 35 dB / 2nd 40 dB
    r = st.aclr_relative_limit("aclr", "n46_n96_n102", "first")
    assert r.limit_db == 35.0 and "6.6.3.2-1a" in r.source_id
    r = st.aclr_relative_limit("aclr", "n46_n96_n102", "second")
    assert r.limit_db == 40.0


def test_data_plane_absolute_and_caclr_spot_check():
    # §6.6.3.2 Table 6.6.3.2-2：Cat A WA −13 / Cat B WA −15 / MR −25 / LA −32
    for cls, exp in _EXP_ABS.items():
        rec = st.absolute_psd_limit("aclr", cls)
        assert rec.limit_dbm_per_mhz == exp, (cls, rec)
        assert "Table 6.6.3.2-2" in rec.source_id
        rec_c = st.absolute_psd_limit("caclr", cls)
        assert rec_c.limit_dbm_per_mhz == exp
        assert "Table 6.6.3.2-3a" in rec_c.source_id
    # CACLR Table 6.6.3.2-3（standard 域全 45 dB，4 行）/-3aa（35/40）
    std_caclr = [x for x in st.CACLR_RELATIVE if x.band_scope == "standard"]
    assert len(std_caclr) == 4 and all(x.limit_db == 45.0 for x in std_caclr)
    n46_caclr = {x.adjacent: x.limit_db for x in st.CACLR_RELATIVE
                 if x.band_scope == "n46_n96_n102"}
    assert n46_caclr == {"first": 35.0, "second": 40.0}
    # 带宽枚举（Table 6.6.3.2-1 / -1a 首列）
    assert st.BW_CHANNEL_MHZ["standard"] == (5.0, 10.0, 15.0, 20.0, 25.0,
                                             30.0, 35.0, 40.0, 45.0, 50.0,
                                             60.0, 70.0, 80.0, 90.0, 100.0)
    assert st.BW_CHANNEL_MHZ["n46_n96_n102"] == (10.0, 20.0, 40.0, 60.0, 80.0)


def test_data_plane_acs_spot_check_against_clauses():
    # §7.4.1.2 Table 7.4.1.2-1 / -1a（wanted=PREFSENS+6，干扰限值）
    for (scope, cls), exp in _EXP_ACS.items():
        rec = st.acs_interferer_limit(cls, scope)
        assert rec.interferer_dbm == exp, (scope, cls, rec)
        assert rec.wanted_rule == "prefsens+6"
        assert "7.4.1.2" in rec.source_id
    # -1a 无 Wide Area 行（原表如实收窄）→ ValueError
    with pytest.raises(ValueError, match=r"Table 7\.4\.1\.2-1a 原表无 Wide Area"):
        st.acs_interferer_limit("wide_area", "n46_n96_n102")
    # Table 7.4.1.2-2（standard 域 15 行全量对拍）
    for bw, off in _EXP_ACS_OFF.items():
        rec = st.acs_offset_for_bw(bw)
        assert rec.offset_mhz == pytest.approx(off, abs=1e-12), (bw, rec)
        assert rec.band_scope == "standard"
    assert len(st.ACS_OFFSETS) == len(_EXP_ACS_OFF) + len(_EXP_ACS_OFF_N46)
    # n46/n96/n102 表 5 行
    for bw, off in _EXP_ACS_OFF_N46.items():
        rec = st.acs_offset_for_bw(bw, "n46_n96_n102")
        assert rec.offset_mhz == pytest.approx(off, abs=1e-12)
    # 干扰类型注记（原表 Type of interfering signal 列）
    t5 = st.acs_offset_for_bw(5.0)
    assert t5.interferer_type.startswith("5 MHz DFT-s-OFDM")
    t25 = st.acs_offset_for_bw(25.0)
    assert t25.interferer_type.startswith("20 MHz DFT-s-OFDM")


def test_data_plane_every_record_has_clause_source_id():
    for recs in (st.ACLR_RELATIVE, st.CACLR_RELATIVE, st.ACLR_ABSOLUTE,
                 st.CACLR_ABSOLUTE):
        for rec in recs:
            assert rec.source_id.startswith("ts138104_v17_5_0 §6.6.3.2")
            assert "Table" in rec.source_id
    for rec in st.ACS_INTERFERER:
        assert "§7.4.1.2" in rec.source_id and "Table" in rec.source_id
    for rec in st.ACS_OFFSETS:
        assert "§7.4.1.2" in rec.source_id and "Table" in rec.source_id
    assert st.PROVENANCE["retrieved"] == "2026-10-02"


# ── 2. 模板面：已知合规/违例正例 + 区域判定 ──────────────────────────────────

_CARRIER_REL_BINDS = {  # 43 dBm / 5 MHz Cat B：相对限值(−2) > 绝对限值(−8.01)
    "f_c_hz": 3.5e9, "p_c_dbm": 43.0, "bw_channel_mhz": 5.0,
    "bs_class": "cat_b_wide_area",
}


def test_template_compliant_case():
    rep = st.spur_template_check(
        [(3.505e9, -5.0)], "ts138104", _CARRIER_REL_BINDS)
    row = rep["rows"][0]
    assert row["region"] == "adjacent_first"
    assert row["aclr_limit_db"] == 45.0
    assert row["relative_limit_dbm"] == pytest.approx(-2.0)  # 43−45
    assert row["absolute_limit_dbm"] == pytest.approx(-15.0 + 10 * math.log10(5.0))
    assert row["effective_limit_dbm"] == pytest.approx(-2.0)  # less stringent=max
    assert row["margin_db"] == pytest.approx(3.0)
    assert row["verdict"] == "pass"
    assert rep["n_pass"] == 1 and rep["n_fail"] == 0
    assert rep["all_adjudicated_pass"] is True
    assert rep["worst_margin_row"]["verdict"] == "pass"


def test_template_violation_case():
    # +2 dBm 泄漏：相对裕量 −4（43−45=−2 上限）、绝对裕量 −6.01——双 FAIL
    rep = st.spur_template_check(
        [(3.495e9, 2.0)], "ts138104", _CARRIER_REL_BINDS)
    row = rep["rows"][0]
    assert row["region"] == "adjacent_first"
    assert row["verdict"] == "fail"
    assert row["relative_margin_db"] == pytest.approx(-4.0)
    assert row["absolute_margin_db"] == pytest.approx(
        -15.0 + 10 * math.log10(5.0) - 2.0)
    assert rep["n_fail"] == 1
    assert rep["all_adjudicated_pass"] is False
    assert rep["worst_margin_row"]["f_hz"] == 3.495e9


def test_template_less_stringent_relaxation_case():
    # §6.6.3.3/38.141-1 §6.6.3.5.3 OR 语义实证：35 dBm/5 MHz Cat B——
    # 相对限值 −10 dBm、绝对限值 −8.01 dBm（较宽松者生效）。
    carrier = {"f_c_hz": 3.5e9, "p_c_dbm": 35.0, "bw_channel_mhz": 5.0,
               "bs_class": "cat_b_wide_area"}
    rep = st.spur_template_check([(3.505e9, -9.0)], "ts138104", carrier)
    row = rep["rows"][0]
    assert row["relative_margin_db"] == pytest.approx(-1.0)   # 违 45 dB 相对
    assert row["absolute_margin_db"] == pytest.approx(0.9897) # 绝对达标
    assert row["verdict"] == "pass"                            # less stringent 生效
    assert row["effective_limit_dbm"] == pytest.approx(
        max(row["relative_limit_dbm"], row["absolute_limit_dbm"]))


def test_template_region_classification_and_boundaries():
    carrier = dict(_CARRIER_REL_BINDS)  # BW=5 MHz：assigned ≤2.5；1st ≤7.5；2nd ≤12.5
    spurs = [
        (3.5e9, 0.0),          # 中心=assigned
        (3.5e9 + 2.5e6, 0.0),  # 通道缘=assigned（双闭含端点）
        (3.5e9 + 5.0e6, 0.0),  # 1st 相邻道内域
        (3.5e9 + 7.5e6, 0.0),  # 1st/2nd 边界（3BW/2，归 1st）
        (3.5e9 + 12.5e6, 0.0),        # 2nd 外缘（5BW/2，归 2nd）
        (3.5e9 + 10.0e6, 0.0),        # 2nd 内域
        (3.5e9 + 13.0e6, 0.0),        # 越界 → 杂散域 out_of_scope
    ]
    rep = st.spur_template_check(spurs, "ts138104", carrier)
    got = [r["region"] for r in rep["rows"]]
    assert got == ["assigned_channel", "assigned_channel", "adjacent_first",
                   "adjacent_first", "adjacent_second", "adjacent_second",
                   "beyond_second_adjacent"]
    assert rep["rows"][0]["verdict"] == "no_limit_assigned_channel"
    assert rep["rows"][6]["verdict"] == "out_of_scope_spurious_domain"
    assert "§6.6.5" in rep["rows"][6]["note"]
    assert rep["n_no_limit"] == 2 and rep["n_out_of_scope"] == 1
    # 区域限值：2nd 相邻道仍 45 dB（Table 6.6.3.2-1 row 2）
    assert rep["rows"][4]["aclr_limit_db"] == 45.0
    assert rep["rows"][5]["aclr_limit_db"] == 45.0


def test_template_n46_scope_uses_35_40_db_layer():
    carrier = {"f_c_hz": 5.2e9, "p_c_dbm": 30.0, "bw_channel_mhz": 40.0,
               "bs_class": "medium_range", "band_scope": "n46_n96_n102"}
    rep = st.spur_template_check(
        [(5.2e9 + 40e6, -10.0), (5.2e9 + 100e6, -10.0)],
        "ts138104", carrier)
    r1, r2 = rep["rows"]
    assert r1["aclr_limit_db"] == 35.0  # 1st：35 dB（Table 6.6.3.2-1a）
    assert r2["aclr_limit_db"] == 40.0  # 2nd：40 dB
    assert r1["source_ids"]["aclr_relative"].endswith("6.6.3.2-1a row 1（n46/n96/n102 NR 1st 相邻道）")


def test_template_report_is_json_serializable_and_complete():
    rep = st.spur_template_check(
        [{"f_hz": 3.505e9, "level_dbm": -5.0}], "TS138104",
        _CARRIER_REL_BINDS)
    json.dumps(rep)  # 全值 JSON 可序列化
    assert rep["data_version"] == "ETSI TS 138 104 V17.5.0 (2022-04)"
    assert rep["retrieved"] == "2026-10-02"
    assert rep["carrier"]["band_scope"] == "standard"
    assert rep["n_spurs"] == 1
    row = rep["rows"][0]
    for key in ("aclr_relative", "aclr_absolute", "combine_semantics"):
        assert key in row["source_ids"]
    assert "§6.6.3.3" in row["source_ids"]["combine_semantics"]


# ── 3. ACIR 合成式回收 + BS ACS 导出 + C/I、IM 闭式 ─────────────────────────


def test_acir_synthesis_recovery():
    # 手算锚：ACIR(45,46)=42.460981 dB（独立式复算）
    assert st.acir_synthesize(45.0, 46.0) == pytest.approx(
        _acir_expected(45.0, 46.0), abs=1e-9)
    assert st.acir_synthesize(45.0, 46.0) == pytest.approx(42.460981, abs=1e-5)
    # 等比退化：ACIR(a,a)=a−10lg2（精确恒等）
    a = st.acir_synthesize(45.0, 45.0)
    assert a == pytest.approx(45.0 - 10 * math.log10(2.0), abs=1e-12)
    # 主导退化：ACS≫ACLR → ACIR→ACLR（差 <1e-8 dB）
    assert st.acir_synthesize(45.0, 145.0) == pytest.approx(45.0, abs=1e-8)
    # n46 域组合锚：ACIR(35,46)=34.668 dB
    assert st.acir_synthesize(35.0, 46.0) == pytest.approx(
        _acir_expected(35.0, 46.0), abs=1e-9)
    assert st.acir_synthesize(35.0, 46.0) == pytest.approx(34.668044, abs=1e-5)


def test_bs_acs_derivation_chain():
    # §7.4.1.2（I_max）+ 调用方 PREFSENS（§7.2.2 域，不在本批数据面）
    assert st.bs_acs_db("ts138104", "wide_area", -101.5) == pytest.approx(43.5)
    assert st.bs_acs_db("ts138104", "medium_range", -101.5) == pytest.approx(48.5)
    assert st.bs_acs_db("ts138104", "local_area", -96.5) == pytest.approx(46.5)
    # 全链回收：ACS(43.5)+ACLR(45) → ACIR=41.175 dB（手算 41.175259）
    acs = st.bs_acs_db("ts138104", "wide_area", -101.5)
    assert st.acir_synthesize(45.0, acs) == pytest.approx(41.175259, abs=1e-5)


def test_ci_and_im_closed_forms():
    assert st.carrier_to_interference_db(40.0, -95.0) == pytest.approx(135.0)
    # IM=C/(N+I)：N=−100、I=−90 → N+I=−89.586 dBm；C=40 → 129.586 dB
    n_plus_i = 10 ** (-100.0 / 10.0) + 10 ** (-90.0 / 10.0)
    expected = 40.0 - 10 * math.log10(n_plus_i)
    assert st.c_over_n_plus_i_db(40.0, -100.0, -90.0) == pytest.approx(
        expected, abs=1e-12)
    assert st.c_over_n_plus_i_db(40.0, -100.0, -90.0) == pytest.approx(
        129.586073, abs=1e-5)
    # I→0 极限退化回 C/N
    tiny_i = -300.0
    assert st.c_over_n_plus_i_db(40.0, -100.0, tiny_i) == pytest.approx(
        140.0, abs=1e-10)


# ── 4. 负例（未知 standard / class / scope / 形态守卫）───────────────────────


def test_unknown_standard_valueerror():
    with pytest.raises(ValueError, match="未知 standard"):
        st.spur_template_check([(3.5e9, 0.0)], "ts36104", _CARRIER_REL_BINDS)
    with pytest.raises(ValueError, match="未知 standard"):
        st.resolve_standard("cispr32")
    with pytest.raises(ValueError, match="未知 standard"):
        st.bs_acs_db("nope", "wide_area", -101.5)
    # 别名解析通
    assert st.resolve_standard("TS138104") == "ts138104_v17_5_0"
    assert st.resolve_standard("3gpp_ts_38_104") == "ts138104_v17_5_0"


def test_argument_guards():
    good = dict(_CARRIER_REL_BINDS)
    with pytest.raises(ValueError, match="绝对基本限值分层"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104",
                               {**good, "bs_class": "wide_area"})
    with pytest.raises(ValueError, match="原表枚举"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104",
                               {**good, "bw_channel_mhz": 7.0})
    with pytest.raises(ValueError, match="band_scope"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104",
                               {**good, "band_scope": "n41_only"})
    with pytest.raises(ValueError, match="未知键"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104", {**good, "f_max": 1.0})
    with pytest.raises(ValueError, match="缺必备键"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104",
                               {"f_c_hz": 3.5e9, "p_c_dbm": 43.0})
    with pytest.raises(ValueError, match="形态非法"):
        st.spur_template_check([3.5e9], "ts138104", good)
    with pytest.raises(ValueError, match="必须 >0"):
        st.spur_template_check([(3.5e9, 0.0)], "ts138104",
                               {**good, "aclr_meas_bw_hz": 0.0})
    for bad in (0.0, -3.0):
        with pytest.raises(ValueError, match="正 dB 功率比"):
            st.acir_synthesize(bad, 46.0)
        with pytest.raises(ValueError, match="正 dB 功率比"):
            st.acir_synthesize(45.0, bad)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="必须是有限数值"):
            st.acir_synthesize(bad, 46.0)


# ── 5. 与 EM-10（limits_registry）关系钉 ─────────────────────────────────────


def test_em10_reserved_slots_unchanged_and_independent_import_face():
    # 预留键位保持 reserved（引用锚），数据面在本模块——registry 侧零数据
    for tid in ("em6_ts138104_aclr", "em6_ts138104_acs"):
        t = lr.get_limit_table(tid)
        assert t.status == "reserved" and t.lines == ()
        with pytest.raises(LookupError, match="reserved"):
            lr.limits_query(tid, 3.5e9)
        assert "spur_templates" in t.notes[0]  # 注记指向数据面所有者
    # 本模块零 import limits_registry（独立 schema 契约，ast 静态双检）
    tree = ast.parse(Path(st.__file__).read_text(encoding="utf-8"))
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
    assert tops <= {"__future__", "math", "dataclasses"}
    assert "limits_registry" not in tops


def test_acir_formula_source_provenance_pinned():
    assert "136 942" in st.ACIR_FORMULA_SOURCE
    assert "§8.1" in st.ACIR_FORMULA_SOURCE
    assert "1/(1/ACLR + 1/ACS)" in st.ACIR_FORMULA_SOURCE
