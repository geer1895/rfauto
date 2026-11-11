"""Q-X35（aurora_q）：CITIfile 结构化解析内核测试。

全离线零网络零真机：hex 位型往返（struct 大端）、格式 A/B/E 精确解码、
C/D unsupported_width 诚实语义（raw 保留、零编数）、包结构
（header/变量/常量/设备关键字）、SEG/MODE/SEG_LIST/多包拆分、
截断与杂行负例、JSON 安全输出。fixture=手写 tests/unit/fixtures/citi/
sample_citi.cti（1 端口 S11 hex 对 + PortZ ASCII 列）。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.citi_parser import (
    CITI_FORMAT_WIDTHS,
    CitiDecodeError,
    CitiParseError,
    decode_citi_field,
    decode_hex_double,
    decode_hex_float,
    package_to_dict,
    parse_citi_file,
    parse_citi_text,
)

FIXTURE = Path(__file__).parent / "fixtures" / "citi" / "sample_citi.cti"


# ── 单值解码钉（格式 A/B/E 精确 + C/D 诚实两态） ──────────────────────────


def test_format_a_hex_double_roundtrip_bit_exact():
    # 任意 double 的 16-hex 大端位型 → 解码逐位相等（struct 同源双向）
    for value in (0.1, -3.54545e-2, 1e9, -0.0, 1e-300, 2.2250738585072014e-308):
        encoded = struct.pack(">d", value).hex().upper()
        assert decode_hex_double(encoded) == value


def test_format_a_width_violation_rejected():
    with pytest.raises(CitiDecodeError, match="16 hex"):
        decode_hex_double("3FB999999999999")      # 15 位
    with pytest.raises(CitiDecodeError, match="非 hex"):
        decode_hex_double("3FB999999999999G")     # 非 hex 字符


def test_format_b_hex_float_roundtrip_bit_exact():
    # f32 可精确表示的值：8-hex 位型往返逐位相等
    for value in (1.5, -0.25, 2.75, 0.0, 100.0):
        encoded = struct.pack(">f", value).hex().upper()
        assert decode_hex_float(encoded) == value


def test_format_b_width_violation_rejected():
    with pytest.raises(CitiDecodeError, match="8 hex"):
        decode_hex_float("3FC0000")               # 7 位


def test_format_e_ascii_and_unknown_letter():
    assert decode_citi_field("E", "1.25E+002") == 125.0
    with pytest.raises(CitiDecodeError, match="ASCII float"):
        decode_citi_field("E", "not-a-number")
    with pytest.raises(CitiDecodeError, match="未知 CITI 格式字母"):
        decode_citi_field("Z", "0")


def test_format_c_d_unsupported_width_honest():
    # 任务书契约：C=%10F（40bit）/D=%6E（24bit）无 IEEE-754 标准映射
    # → 拒解码，message 带 unsupported_width 标记；绝不编造数值
    for letter, token in (("C", "3FB9999999"), ("D", "ABCDEF")):
        with pytest.raises(CitiDecodeError, match="unsupported_width"):
            decode_citi_field(letter, token)
    assert CITI_FORMAT_WIDTHS["C"] == ("%10F", 10)
    assert CITI_FORMAT_WIDTHS["D"] == ("%6E", 6)


# ── 包结构钉（header/版本/变量/常量/设备关键字） ──────────────────────────


def test_fixture_package_header_and_version():
    pkgs = parse_citi_file(FIXTURE)
    assert len(pkgs) == 1
    pkg = pkgs[0]
    assert pkg.version == "A.01.01"
    assert pkg.version_keyword == "CITIFILE"
    assert pkg.name == "RAW_DATA"
    # 任务书扩展包头关键字全数收编（RAWDATE/OUTPERHA/AUTOLOAD/INSPFILE）
    assert pkg.header["RAWDATE"] == "Mon Nov 02 10:11:12 2026"
    assert pkg.header["OUTPERHA"] == "?"
    assert pkg.header["AUTOLOAD"] == "NO"
    assert pkg.header["INSPFILE"] == "''"
    assert pkg.constants["TIME"] == "2026 11 02 10 11 12"
    assert pkg.header["#NA"] == "IFBW 1.0E4"
    assert pkg.warnings == []


def test_cvg_version_header_form():
    # IC-CAP/ADS 形态：CVG VERSION 版本行 + 同一组包头关键字
    text = (
        "CVG VERSION A.01.10\n"
        "NAME ads_data\n"
        "RAWDATE Thu Mar 03 14:22:05 2021\n"
        "OUTPERHA ?\n"
        "AUTOLOAD NO\n"
        "INSPFILE ''\n"
        "VAR freq HZ 2\n"
        "BEGIN\n1e9\n2e9\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    assert pkg.version_keyword == "CVG VERSION"
    assert pkg.version == "A.01.10"
    assert pkg.header["RAWDATE"].startswith("Thu Mar 03")
    assert pkg.header["OUTPERHA"] == "?"
    assert pkg.variables[0].values == [1e9, 2e9]


def test_var_list_values_and_occurrences():
    pkg = parse_citi_file(FIXTURE)[0]
    assert len(pkg.variables) == 1
    var = pkg.variables[0]
    assert var.name == "FREQ"
    assert var.occurrences == 5
    assert var.values == [1e9, 1.25e9, 1.5e9, 1.75e9, 2e9]


# ── ASCII 数据块钉（RI/MAGANGLE/DBANGLE） ──────────────────────────


def test_data_ri_pairs_decode_complex():
    text = (
        "CITIFILE A.01.00\nNAME MEMORY\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "DATA S RI\nBEGIN\n-3.54545E-2, -1.38601E-3\n0.25, -0.5\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    assert len(pkg.segments) == 1
    seg = pkg.segments[0]
    assert seg.type == "DATA"
    assert seg.format == "RI"
    assert seg.decode_status == "ok"
    dep = seg.dependent_vars[0]
    assert dep.value_kind == "complex"
    assert dep.values == [complex(-3.54545e-2, -1.38601e-3), complex(0.25, -0.5)]


def test_data_magangle_dbangle_decode():
    text = (
        "CITIFILE A.01.00\nNAME FORMATTED\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "DATA S MAGANGLE\nBEGIN\n0.5, 90\nEND\n"
        "DATA S_db DBANGLE\nBEGIN\n-6.0206, 0\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg_ma, seg_db = pkg.segments
    assert abs(seg_ma.dependent_vars[0].values[0] - 0.5j) < 1e-12
    # -6.0206 dB → 0.5 幅值（20log10 口径）
    assert abs(abs(seg_db.dependent_vars[0].values[0]) - 0.5) < 1e-4
    assert abs(seg_db.dependent_vars[0].values[0].imag) < 1e-12


def test_data_unknown_format_honest_raw():
    text = (
        "CITIFILE A.01.00\nNAME MEMORY\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "DATA V SWR\nBEGIN\n1.5\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "ascii_unknown_format"
    assert seg.dependent_vars[0].values is None
    assert seg.raw_records == ["1.5"]


# ── SEG 打包段钉（A/B/E 精确 + C/D raw 保留 + 布局分配） ──────────────────


def test_fixture_seg_a_a_ri_pairs_exact():
    # SEG A_A（2×16hex 字段）×1 dependent → F==2K → RI 对 complex（位型精确）
    pkg = parse_citi_file(FIXTURE)[0]
    seg = next(s for s in pkg.segments if s.var_name == "S[1,1]")
    assert seg.type == "SEG"
    assert seg.format == "A_A"
    assert seg.decode_status == "ok"
    assert seg.n_records == 5 == seg.n_records_expected
    dep = seg.dependent_vars[0]
    assert dep.value_kind == "complex"
    assert dep.values == [0.1 + 0.05j, 0.2 - 0.1j, 0.3 + 0.15j,
                          -0.4 + 0.2j, 0.5 - 0.25j]
    indep = seg.independent_var
    assert indep.name == "freq" and indep.unit == "HZ"
    assert indep.values == [1e9, 1.25e9, 1.5e9, 1.75e9, 2e9]
    assert seg.raw_records is None


def test_fixture_seg_e_ascii_column():
    # SEG E（1 字段）×1 dependent → F==K → float 列
    pkg = parse_citi_file(FIXTURE)[0]
    seg = next(s for s in pkg.segments if s.var_name == "PortZ[1]")
    assert seg.format == "E"
    assert seg.decode_status == "ok"
    dep = seg.dependent_vars[0]
    assert dep.value_kind == "float"
    assert dep.values == [50.0, 49.0, 48.0, 47.0, 46.0]


def test_seg_mixed_width_letters_per_field():
    # 逐字段格式字母：A_B = 第1字段 16hex double + 第2字段 8hex f32
    re_vals = [0.25, -0.5]
    im_vals = [1.5, -2.5]           # f32 可精确表示
    rows = "\n".join(
        struct.pack(">d", r).hex().upper() + "," + struct.pack(">f", i).hex().upper()
        for r, i in zip(re_vals, im_vals, strict=True))
    text = (
        "CITIFILE A.01.00\nNAME MIX_WIDTH\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 2\n"
        "DEPENDENT re_part REAL\nDEPENDENT im_part REAL\n"
        f"SEG A_B 2\nBEGIN\n{rows}\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "ok"
    d0, d1 = seg.dependent_vars
    assert d0.values == re_vals and d1.values == im_vals
    assert d0.value_kind == "float"


def test_seg_three_fields_three_dependents():
    rows = "\n".join(["1.0 2.0 3.0", "4.0 5.0 6.0"])
    text = (
        "CITIFILE A.01.00\nNAME F3K3\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 2\n"
        "DEPENDENT a REAL\nDEPENDENT b REAL\nDEPENDENT c REAL\n"
        f"SEG E_E_E 2\nBEGIN\n{rows}\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "ok"
    assert [d.values for d in seg.dependent_vars] == [
        [1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]


def test_seg_layout_ambiguous_honest():
    # F=2 字段对 K=3 dependent（非 F==K 亦非 F==2K）→ 不猜，raw 保留
    text = (
        "CITIFILE A.01.00\nNAME AMBIG\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 1\n"
        "DEPENDENT a REAL\nDEPENDENT b REAL\nDEPENDENT c REAL\n"
        "SEG E_E 1\nBEGIN\n1.0, 2.0\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "layout_ambiguous"
    assert all(d.values is None for d in seg.dependent_vars)
    assert seg.raw_records == ["1.0, 2.0"]


def test_seg_c_d_unsupported_width_raw_preserved():
    # C/D 段：结构保留（格式/记录数/raw 原文），零数值产出（铁律 7）
    text = (
        "CITIFILE A.01.00\nNAME RAW_CD\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 2\n"
        "DEPENDENT cmplx_raw CMPLX\n"
        "SEG C 2\nBEGIN\n3FB9999999\nCCCCCCCCCC\nEND\n"
        "DEPENDENT f_raw SHORT\n"
        "SEG D 2\nBEGIN\nABCDEF\n123456\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg_c, seg_d = pkg.segments
    assert seg_c.decode_status == "unsupported_width"
    assert seg_c.format == "C"
    assert seg_c.n_records == 2
    assert seg_c.raw_records == ["3FB9999999", "CCCCCCCCCC"]
    assert seg_c.dependent_vars[0].values is None
    assert seg_d.decode_status == "unsupported_width"
    assert seg_d.raw_records == ["ABCDEF", "123456"]
    # fabrication guard：全树无任何从 C/D 段伪造出的数值
    assert not any(isinstance(v, float)
                   for d in (seg_c.dependent_vars + seg_d.dependent_vars)
                   for v in (d.values or []))


def test_seg_format_b_records_decode():
    vals = [1.5, -0.25]
    rows = "\n".join(struct.pack(">f", v).hex().upper() for v in vals)
    text = (
        "CITIFILE A.01.00\nNAME F32\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 2\n"
        "DEPENDENT gain MAG\n"
        f"SEG B 2\nBEGIN\n{rows}\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "ok"
    assert seg.dependent_vars[0].values == vals


def test_mode_block_decode():
    vals = [0.25, -1.5, 2.0]
    rows = "\n".join(struct.pack(">d", v).hex().upper() for v in vals)
    text = (
        "CITIFILE A.01.00\nNAME MODE_DATA\nVAR FREQ MAG 3\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\n3e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 3\n"
        "DEPENDENT gains MAG\n"
        "BEGIN_MODE\n"
        f"MODE A %16E\n{rows}\nEND\n"
        "END_MODE\n"
    )
    pkg = parse_citi_text(text)[0]
    assert len(pkg.segments) == 1
    seg = pkg.segments[0]
    assert seg.type == "MODE"
    assert seg.format == "%16E"
    assert seg.decode_status == "ok"
    assert seg.dependent_vars[0].values == vals
    assert seg.independent_var.values == [1e9, 2e9, 3e9]


# ── 拆包/SEG_LIST/负例/JSON 安全钉 ──────────────────────────


def test_multi_package_split():
    text = (
        "CITIFILE A.01.00\nNAME PKG1\n"
        "VAR FREQ MAG 1\nVAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "CITIFILE A.01.01\nNAME PKG2\n"
        "VAR FREQ MAG 1\nVAR_LIST_BEGIN\n2e9\nVAR_LIST_END\n"
    )
    pkgs = parse_citi_text(text)
    assert len(pkgs) == 2
    assert [p.name for p in pkgs] == ["PKG1", "PKG2"]
    assert [p.version for p in pkgs] == ["A.01.00", "A.01.01"]
    assert [p.variables[0].values for p in pkgs] == [[1e9], [2e9]]


def test_seg_list_linear_synthesis_ansys_formula():
    # Ansys Circuit 文档口径：F(n) = start + (n-1)*(stop-start)/(count-1)
    text = (
        "CITIFILE A.01.00\nNAME SEG_LIST_DATA\nVAR FREQ MAG 4\n"
        "SEG_LIST_BEGIN\nSEG 1000000000 4000000000 4\nSEG_LIST_END\n"
        "INDEPENDENT freq HZ 4\n"
        "DEPENDENT mag LIN\n"
        "SEG E 4\nBEGIN\n0.1\n0.2\n0.3\n0.4\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    indep = pkg.segments[0].independent_var
    assert indep.values == [1e9, 2e9, 3e9, 4e9]


def test_no_version_line_rejected():
    with pytest.raises(CitiParseError, match="非 CITI"):
        parse_citi_text("NAME not_citi\nVAR FREQ MAG 1\n")
    with pytest.raises(CitiParseError, match="非 CITI"):
        parse_citi_text("")
    with pytest.raises(CitiParseError, match="非 CITI"):
        parse_citi_text("<xml/>")


def test_unterminated_begin_truncated_honest():
    text = (
        "CITIFILE A.01.00\nNAME TRUNC\nVAR FREQ MAG 3\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\n3e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 3\n"
        "DEPENDENT d REAL\n"
        "SEG E 3\nBEGIN\n1.0\n2.0\n"          # 声明 3 条实收 2 条，无 END
    )
    pkg = parse_citi_text(text)[0]
    assert any("截断" in w for w in pkg.warnings)
    assert len(pkg.segments) == 1
    seg = pkg.segments[0]
    assert seg.n_records == 2 != seg.n_records_expected
    assert seg.dependent_vars[0].values == [1.0, 2.0]
    assert any("不一致" in w for w in seg.warnings)


def test_unknown_stray_line_warned_not_silent():
    text = (
        "CITIFILE A.01.00\nNAME STRAY\nsome lowercase garbage line\n"
    )
    pkg = parse_citi_text(text)[0]
    assert any("无法归类" in w for w in pkg.warnings)


def test_record_count_and_field_mismatch_warned():
    text = (
        "CITIFILE A.01.00\nNAME BADREC\nVAR FREQ MAG 2\n"
        "VAR_LIST_BEGIN\n1e9\n2e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 2\n"
        "DEPENDENT d REAL\n"
        "SEG E 2\nBEGIN\n1.0\nnot-a-number\nEND\n"
    )
    pkg = parse_citi_text(text)[0]
    seg = pkg.segments[0]
    assert seg.decode_status == "decode_error"
    assert seg.raw_records == ["1.0", "not-a-number"]
    assert any("解码失败" in w for w in pkg.warnings)


def test_package_to_dict_json_safe_roundtrip():
    pkgs = parse_citi_file(FIXTURE)
    d = package_to_dict(pkgs[0], package_index=0, n_packages=1)
    blob = json.dumps(d, ensure_ascii=False)          # JSON 可序列化
    back = json.loads(blob)
    assert back["header"]["RAWDATE"] == "Mon Nov 02 10:11:12 2026"
    assert back["metadata"]["n_packages"] == 1
    seg = back["segments"][0]
    # complex 值的 JSON 形态=[re, im] 对
    assert seg["dependent_vars"][0]["value_kind"] == "complex"
    assert seg["dependent_vars"][0]["values"][0] == [0.1, 0.05]
    assert seg["independent_var"]["values"][0] == 1e9
    assert seg["format"] == "A_A"
    assert seg["type"] == "SEG"


def test_comments_and_device_keywords_captured():
    pkg = parse_citi_file(FIXTURE)[0]
    assert any("Q-X35" in c for c in pkg.comments)
    assert pkg.header["#NA"] == "IFBW 1.0E4"
