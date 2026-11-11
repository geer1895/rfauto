"""GDSII 解析内核+服务+CLI 单测（aurora_q 席位 Q-X58，2026-11-07）。

夹具纪律（任务书口径）：**测试内程序化合成 GDSII 字节流**——本文件自带
小 builder（``rec``/``i2``/``i4``/``xy``/``enc_real8``/``enc_real4``/
``ascii_padded``），构 1 库 2 结构（顶层含 BOUNDARY 2+PATH 1+SREF 2
（含反射+90°）+AREF 1+TEXT 1；子结构 1 BOUNDARY）+UNITS 双实数真值。
零外部夹具文件、零写盘（服务/CLI 测试经 tmp_path 落盘隔离，#144 run
湖零写入）、零网络零真机。

覆盖面（任务书 ≥60 条）：

- 实数解码表驱动（real8/real4：0/-0.0/1/-1/0.5/0.25/2/16/0.03125 期望
  值自算参考 + 1e-3 最近 double 精确口径 + 双曲格点往返逐位相等）；
- 记录流逐类（HEADER/LIBNAME/UNITS/未知记录号/零 length 停流/头截断/
  声明长度越界/ENDLIB 尾巴）、ASCII 尾 NUL 清理、bitarray/int2/int4；
- 结构化输出逐键（六桶/单位/重名合并/缺字段如实 None/XY 奇负载截断/
  BOX）；拓扑三函数（引用计数/未定义引用构造/孤儿构造/反射+90° 展开坐
  标手算断言/任意角度与 mag≠1 skip/AREF 端点极值/循环引用守卫/深度
  守卫）；fail-soft（截断流保留已收面/ENDLIB 缺失文件级截断/未收口元
  素截断态物化/warning 同文去重）；服务信封三态；CLI 两叶 --json 双路
  径（CliRunner 直连 gdsii_app——不触共享 app，零金快照漂移）+ 计数链
  字面钉 + cli.main 零导入钉。
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.gdsii import gdsii_app
from rfauto.core.gdsii_parser import (
    DT_BITARRAY,
    DT_INT2,
    DT_INT4,
    DT_REAL8,
    PARSER_SCHEMA_VERSION,
    GdsiiParseError,
    dbu_to_um,
    decode_gds_ascii,
    decode_gds_real4,
    decode_gds_real8,
    gdsii_expand_bbox,
    gdsii_hierarchy_stats,
    gdsii_layer_summary,
    parse_gdsii_bytes,
)
from rfauto.service import gdsii_service

runner = CliRunner()

# ══════════════════════════ GDSII 字节流 builder ══════════════════════════
# （测试夹具专用编码器；与 core 解码器互为往返验证，期望值手算注释在案）

def rec(rectype: int, payload: bytes = b"", datatype: int = 0x00) -> bytes:
    """单记录：2B 大端 length（含头 4 字节）+1B 类型+1B 数据类型+负载。"""
    length = 4 + len(payload)
    assert 4 <= length <= 0xFFFF
    return length.to_bytes(2, "big") + bytes([rectype, datatype]) + payload

def i2(*vals: int) -> bytes:
    return struct.pack(f">{len(vals)}h", *vals)

def i4(*vals: int) -> bytes:
    return struct.pack(f">{len(vals)}l", *vals)

def bit(value: int) -> bytes:
    return struct.pack(">H", value)

def xy(points: list[tuple[int, int]]) -> bytes:
    return i4(*[coord for point in points for coord in point])

def ascii_padded(text: str) -> bytes:
    raw = text.encode("ascii")
    return raw + b"\x00" * (len(raw) % 2)

def enc_real8(value: float) -> bytes:
    """GDSII real8 编码（测试侧参考编码器；dyadic 值与解码逐位往返）。"""
    if value == 0.0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0
    x = abs(value)
    e = 0
    while x >= 1.0:
        x /= 16.0
        e += 1
    while x < 1.0 / 16.0:
        x *= 16.0
        e -= 1
    mant = round(x * 2.0 ** 56)
    if mant >= 2 ** 56:
        mant //= 16
        e += 1
    return bytes([sign | (e + 64)]) + mant.to_bytes(7, "big")

def enc_real4(value: float) -> bytes:
    if value == 0.0:
        return b"\x00" * 4
    sign = 0x80 if value < 0 else 0
    x = abs(value)
    e = 0
    while x >= 1.0:
        x /= 16.0
        e += 1
    while x < 1.0 / 16.0:
        x *= 16.0
        e -= 1
    mant = round(x * 2.0 ** 24)
    if mant >= 2 ** 24:
        mant //= 16
        e += 1
    return bytes([sign | (e + 64)]) + mant.to_bytes(3, "big")

def ts() -> bytes:
    """12×int2 时间戳占位（输出不含时间戳，占位值不进断言面）。"""
    return i2(*([0] * 12))

def boundary_records(layer: int, datatype: int,
                     points: list[tuple[int, int]]) -> bytes:
    return (rec(0x08) + rec(0x0D, i2(layer), DT_INT2)
            + rec(0x0E, i2(datatype), DT_INT2)
            + rec(0x10, xy(points), DT_INT4) + rec(0x11))

def path_records(layer: int, datatype: int, width: int, pathtype: int,
                 points: list[tuple[int, int]]) -> bytes:
    return (rec(0x09) + rec(0x0D, i2(layer), DT_INT2)
            + rec(0x0E, i2(datatype), DT_INT2)
            + rec(0x0F, i4(width), DT_INT4)
            + rec(0x21, i2(pathtype), DT_INT2)
            + rec(0x10, xy(points), DT_INT4) + rec(0x11))

def sref_records(sname: str, x: int, y: int, *, strans: int | None = None,
                 mag: float | None = None,
                 angle: float | None = None) -> bytes:
    body = rec(0x0A)
    if strans is not None:
        body += rec(0x1A, bit(strans), DT_BITARRAY)
    if mag is not None:
        body += rec(0x1B, enc_real8(mag), DT_REAL8)
    if angle is not None:
        body += rec(0x1C, enc_real8(angle), DT_REAL8)
    body += rec(0x12, ascii_padded(sname))
    body += rec(0x10, xy([(x, y)]), DT_INT4)
    return body + rec(0x11)

def aref_records(sname: str, cols: int, rows: int,
                 anchors: list[tuple[int, int]], *,
                 strans: int | None = None, mag: float | None = None,
                 angle: float | None = None) -> bytes:
    body = rec(0x0B)
    if strans is not None:
        body += rec(0x1A, bit(strans), DT_BITARRAY)
    if mag is not None:
        body += rec(0x1B, enc_real8(mag), DT_REAL8)
    if angle is not None:
        body += rec(0x1C, enc_real8(angle), DT_REAL8)
    body += rec(0x12, ascii_padded(sname))
    body += rec(0x13, i2(cols, rows), DT_INT2)
    body += rec(0x10, xy(anchors), DT_INT4)
    return body + rec(0x11)

def text_records(layer: int, texttype: int, string: str, x: int, y: int,
                 presentation: int = 5) -> bytes:
    return (rec(0x0C) + rec(0x0D, i2(layer), DT_INT2)
            + rec(0x16, i2(texttype), DT_INT2)
            + rec(0x17, bit(presentation), DT_BITARRAY)
            + rec(0x10, xy([(x, y)]), DT_INT4)
            + rec(0x19, ascii_padded(string)) + rec(0x11))

def box_records(layer: int, boxtype: int,
                points: list[tuple[int, int]]) -> bytes:
    return (rec(0x2D) + rec(0x0D, i2(layer), DT_INT2)
            + rec(0x2E, i2(boxtype), DT_INT2)
            + rec(0x10, xy(points), DT_INT4) + rec(0x11))

def build_library(
    structures: list[tuple[str, list[bytes]]],
    *,
    lib_name: str | None = "QX58_LIB",
    version: int = 600,
    with_units: bool = True,
    with_endlib: bool = True,
    extra_prefix: bytes = b"",
    extra_suffix: bytes = b"",
) -> bytes:
    """1 库 N 结构合成（主夹具与变体共用；变体经 extra_prefix/suffix 注入）。"""
    out = rec(0x00, i2(version), DT_INT2) + rec(0x01, ts())
    if lib_name is not None:
        out += rec(0x02, ascii_padded(lib_name))
    if with_units:
        out += rec(0x03, enc_real8(0.001) + enc_real8(1.0), DT_REAL8)
    out += extra_prefix
    for name, body in structures:
        out += rec(0x05, ts()) + rec(0x06, ascii_padded(name))
        out += b"".join(body)
        out += rec(0x07)
    out += extra_suffix
    if with_endlib:
        out += rec(0x04)
    return out

# 主夹具（任务书口径）：1 库 2 结构；TOP=BOUNDARY 2+PATH 1+SREF 2
# （含反射+90°）+AREF 1+TEXT 1；SUB=BOUNDARY 1。包围盒手算参考：
#   SUB 局部 [0,0,2,1]
#   SREF 平移 @(10,20)  → [10,20,12,21]
#   SREF 反射+90° @(100,0)：反射 y→−y 后 90° 旋转 → [0,0,1,2]+(100,0)
#     = [100,0,101,2]
#   AREF 2×2 锚 [(40,0),(42,0),(40,2)] → [40,0,44,3]
#   TOP 总 bbox = [0,0,101,21]
TOP_BODY = [
    boundary_records(1, 0, [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]),
    boundary_records(1, 5, [(0, 0), (2, 0), (0, 2), (0, 0)]),
    path_records(2, 0, 200, 0, [(0, 0), (10, 0), (10, 5)]),
    sref_records("SUB", 10, 20),
    sref_records("SUB", 100, 0, strans=0x8000, mag=1.0, angle=90.0),
    aref_records("SUB", 2, 2, [(40, 0), (42, 0), (40, 2)]),
    text_records(5, 0, "TOP_TEXT", 1, 1, presentation=5),
]
SUB_BODY = [boundary_records(3, 0, [(0, 0), (2, 0), (2, 1), (0, 1), (0, 0)])]

MAIN_BYTES = build_library([("TOP", TOP_BODY), ("SUB", SUB_BODY)])
MAIN_DOC = parse_gdsii_bytes(MAIN_BYTES)

def write_main(tmp_path: Path) -> Path:
    """主夹具落盘（tmp_path 隔离，#144 run 湖零写入）。"""
    p = tmp_path / "sample.gds"
    p.write_bytes(MAIN_BYTES)
    return p

# ══════════════════════════ builder 自检 ══════════════════════════

class TestBuilder:
    def test_rec_length_includes_header(self) -> None:
        assert rec(0x11)[:2] == (4).to_bytes(2, "big")
        assert rec(0x10, xy([(1, 2)]), DT_INT4)[:2] == (12).to_bytes(2, "big")

    def test_enc_real8_known_bytes(self) -> None:
        # 手算参考：1.0=e=1,mant=2^52 → 0x4110...；0.5=e=0,mant=2^55 →
        # 0x4080...；-1.0=符号位+同 1.0
        assert enc_real8(1.0) == bytes.fromhex("4110000000000000")
        assert enc_real8(0.5) == bytes.fromhex("4080000000000000")
        assert enc_real8(-1.0) == bytes.fromhex("C110000000000000")
        assert enc_real8(0.0) == b"\x00" * 8

    def test_enc_real4_known_bytes(self) -> None:
        assert enc_real4(1.0) == bytes.fromhex("41100000")
        assert enc_real4(-1.0) == bytes.fromhex("C1100000")

# ══════════════════════════ 实数解码（表驱动）══════════════════════════

class TestRealDecode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (b"\x00" * 8, 0.0),                                  # 全零特判
            (bytes.fromhex("4110000000000000"), 1.0),
            (bytes.fromhex("C110000000000000"), -1.0),
            (bytes.fromhex("4080000000000000"), 0.5),
            (bytes.fromhex("4040000000000000"), 0.25),
            (bytes.fromhex("4120000000000000"), 2.0),
            (bytes.fromhex("4210000000000000"), 16.0),
            (bytes.fromhex("3F80000000000000"), 0.03125),
            (bytes.fromhex("4160000000000000"), 6.0),
        ],
    )
    def test_real8_table(self, raw: bytes, expected: float) -> None:
        assert decode_gds_real8(raw) == expected

    def test_real8_negative_zero_sign_only(self) -> None:
        value = decode_gds_real8(b"\x80" + b"\x00" * 7)
        assert value == 0.0
        assert math.copysign(1.0, value) == -1.0  # -0.0 如实保留

    def test_real8_1e3_nearest_double(self) -> None:
        # 0.001 非二分可精表示：0.256=0.001×256 ∈ [1/16,1) → e=-2、
        # mant=round(0.256×2^56)；期望值=该整数移位后的最近 double（自算
        # 参考），与 0.001 相对误差 < 1e-18。
        mant = round(0.001 * 256.0 * 2.0 ** 56)
        expected = mant / (1 << 64)
        got = decode_gds_real8(b"\x3e" + mant.to_bytes(7, "big"))
        assert got == expected
        assert abs(got - 0.001) < 1e-18

    @pytest.mark.parametrize(
        "value",
        [1.0, -1.0, 0.5, -0.5, 0.25, 2.0, -2.0, 16.0, 0.03125, 1024.5,
         -4096.25, 0.0625, 65536.0],
    )
    def test_real8_roundtrip_dyadic_exact(self, value: float) -> None:
        assert decode_gds_real8(enc_real8(value)) == value

    @pytest.mark.parametrize("value", [0.001, 1e-9, 123.456, -0.007])
    def test_real8_roundtrip_non_dyadic_tolerance(
        self, value: float
    ) -> None:
        got = decode_gds_real8(enc_real8(value))
        assert abs(got - value) <= abs(value) * 2.0 ** -52

    def test_real8_bad_length_raises(self) -> None:
        with pytest.raises(GdsiiParseError, match="real8"):
            decode_gds_real8(b"\x00" * 7)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (b"\x00" * 4, 0.0),
            (bytes.fromhex("41100000"), 1.0),
            (bytes.fromhex("C1100000"), -1.0),
            (bytes.fromhex("40800000"), 0.5),
            (bytes.fromhex("41200000"), 2.0),
        ],
    )
    def test_real4_table(self, raw: bytes, expected: float) -> None:
        assert decode_gds_real4(raw) == expected

    @pytest.mark.parametrize(
        "value", [1.0, -1.0, 0.5, 2.0, 16.0, 0.03125, 1024.5]
    )
    def test_real4_roundtrip(self, value: float) -> None:
        assert decode_gds_real4(enc_real4(value)) == value

    def test_real4_bad_length_raises(self) -> None:
        with pytest.raises(GdsiiParseError, match="real4"):
            decode_gds_real4(b"\x00" * 3)

# ══════════════════════════ ASCII / 换算 ══════════════════════════

class TestAsciiAndConvert:
    def test_ascii_trailing_nul_stripped(self) -> None:
        assert decode_gds_ascii(b"TOP\x00") == "TOP"
        assert decode_gds_ascii(b"AB\x00\x00") == "AB"

    def test_ascii_interior_bytes_kept(self) -> None:
        assert decode_gds_ascii(b"A B\x00") == "A B"

    def test_ascii_non_ascii_replaced(self) -> None:
        # 非 ASCII 字节 → U+FFFD 替换如实显示（不猜编码）
        assert decode_gds_ascii(b"AB\x80\x00") == "AB\ufffd"

    def test_ascii_empty(self) -> None:
        assert decode_gds_ascii(b"") == ""
        assert decode_gds_ascii(b"\x00\x00") == ""

    def test_dbu_to_um_factor(self) -> None:
        units = {"db_um": 0.001}
        assert dbu_to_um(1000, units) == pytest.approx(1.0)
        assert dbu_to_um(-500, units) == pytest.approx(-0.5)

    def test_dbu_to_um_missing_units_none(self) -> None:
        assert dbu_to_um(1, {}) is None
        assert dbu_to_um(1, {"db_um": None}) is None

    def test_dbu_to_um_missing_key_none(self) -> None:
        assert dbu_to_um(1, {"user_um": 1.0}) is None

# ══════════════════════════ 主夹具结构化输出逐键 ══════════════════════════

class TestStructuredOutput:
    def test_lib_name_and_version(self) -> None:
        assert MAIN_DOC["lib_name"] == "QX58_LIB"
        assert MAIN_DOC["version"] == 600

    def test_units_keys(self) -> None:
        units = MAIN_DOC["units"]
        assert units["db_um"] == pytest.approx(0.001)
        assert units["user_um"] == 1.0
        raw = MAIN_DOC["units_raw"]
        assert len(raw) == 2 and raw[1] == 1.0

    def test_units_missing_all_none(self) -> None:
        doc = parse_gdsii_bytes(build_library([], with_units=False))
        assert doc["units"] == {"db_um": None, "user_um": None}
        assert doc["units_raw"] == [None, None]

    def test_structure_order(self) -> None:
        assert list(MAIN_DOC["structures"]) == ["TOP", "SUB"]

    def test_boundary_first(self) -> None:
        b = MAIN_DOC["structures"]["TOP"]["boundaries"][0]
        assert b["layer"] == 1 and b["datatype"] == 0
        assert b["points_xy"] == [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]

    def test_boundary_second_datatype5(self) -> None:
        b = MAIN_DOC["structures"]["TOP"]["boundaries"][1]
        assert b["layer"] == 1 and b["datatype"] == 5
        assert b["points_xy"][-1] == [0, 0]

    def test_path_fields(self) -> None:
        p = MAIN_DOC["structures"]["TOP"]["paths"][0]
        assert p["layer"] == 2 and p["datatype"] == 0
        assert p["width"] == 200 and p["pathtype"] == 0
        assert p["points_xy"] == [[0, 0], [10, 0], [10, 5]]

    def test_sref_plain_defaults(self) -> None:
        s = MAIN_DOC["structures"]["TOP"]["srefs"][0]
        assert s == {"sname": "SUB", "x": 10, "y": 20, "angle": 0.0,
                     "mag": 1.0, "reflected": False}

    def test_sref_reflected_90(self) -> None:
        s = MAIN_DOC["structures"]["TOP"]["srefs"][1]
        assert s["sname"] == "SUB" and s["x"] == 100 and s["y"] == 0
        assert s["reflected"] is True and s["angle"] == 90.0
        assert s["mag"] == 1.0

    def test_aref_cols_rows_anchors(self) -> None:
        a = MAIN_DOC["structures"]["TOP"]["arefs"][0]
        assert a["sname"] == "SUB"
        assert a["cols"] == 2 and a["rows"] == 2
        assert a["xy"] == [[40, 0], [42, 0], [40, 2]]
        assert a["x"] == 40 and a["y"] == 0

    def test_text_fields(self) -> None:
        t = MAIN_DOC["structures"]["TOP"]["texts"][0]
        assert t["string"] == "TOP_TEXT"
        assert t["layer"] == 5 and t["texttype"] == 0
        assert t["presentation"] == 5
        assert t["x"] == 1 and t["y"] == 1
        assert t["reflected"] is False

    def test_sref_mag_parsed(self) -> None:
        body = sref_records("SUB", 0, 0, mag=2.0)
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        assert doc["structures"]["T"]["srefs"][0]["mag"] == 2.0

    def test_sref_missing_sname_none(self) -> None:
        body = rec(0x0A) + rec(0x10, xy([(1, 2)]), DT_INT4) + rec(0x11)
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        s = doc["structures"]["T"]["srefs"][0]
        assert s["sname"] is None and s["x"] == 1
        assert any("SNAME" in w for w in doc["warnings"])

    def test_sref_missing_xy_none(self) -> None:
        body = rec(0x0A) + rec(0x12, ascii_padded("SUB")) + rec(0x11)
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        s = doc["structures"]["T"]["srefs"][0]
        assert s["x"] is None and s["y"] is None
        assert any("XY" in w for w in doc["warnings"])

    def test_xy_odd_payload_truncates(self) -> None:
        # XY 负载 12 字节（1.5 点）→ 截到 1 整点 + warning
        body = (rec(0x08) + rec(0x10, i4(1, 2, 3), DT_INT4) + rec(0x11))
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        b = doc["structures"]["T"]["boundaries"][0]
        assert b["points_xy"] == [[1, 2]]
        assert any("非 8 倍数" in w for w in doc["warnings"])

    def test_box_element(self) -> None:
        body = box_records(6, 0, [(0, 0), (3, 0), (3, 2), (0, 2), (0, 0)])
        doc = parse_gdsii_bytes(build_library([("B", [body])]))
        box = doc["structures"]["B"]["boxes"][0]
        assert box["layer"] == 6 and box["boxtype"] == 0
        assert len(box["points_xy"]) == 5

    def test_duplicate_structure_merges(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("TOP", TOP_BODY), ("TOP", SUB_BODY)]))
        assert list(doc["structures"]) == ["TOP"]
        assert len(doc["structures"]["TOP"]["boundaries"]) == 3
        assert any("重名" in w for w in doc["warnings"])

    def test_element_outside_structure_discarded(self) -> None:
        stray = boundary_records(9, 9, [(0, 0), (1, 1), (0, 0)])
        doc = parse_gdsii_bytes(build_library(
            [], extra_suffix=stray))
        assert doc["structures"] == {}
        assert any("STRNAME 领衔" in w for w in doc["warnings"])

    def test_stats_counts(self) -> None:
        st = MAIN_DOC["stats"]
        assert st["n_structures"] == 2
        assert st["n_boundaries"] == 3
        assert st["n_paths"] == 1
        assert st["n_srefs"] == 2
        assert st["n_arefs"] == 1
        assert st["n_texts"] == 1
        assert st["n_boxes"] == 0
        assert st["n_warnings"] == len(MAIN_DOC["warnings"])

    def test_schema_version_and_determinism(self) -> None:
        assert MAIN_DOC["schema"] == f"gdsii/{PARSER_SCHEMA_VERSION}"
        again = parse_gdsii_bytes(MAIN_BYTES)
        assert json.dumps(MAIN_DOC, sort_keys=True) == \
            json.dumps(again, sort_keys=True)

# ══════════════════════════ 记录流 fail-soft ══════════════════════════

class TestRecordStreamFailSoft:
    def test_empty_bytes_raises(self) -> None:
        with pytest.raises(GdsiiParseError, match="零字节"):
            parse_gdsii_bytes(b"")

    def test_short_bytes_raises(self) -> None:
        with pytest.raises(GdsiiParseError, match="过短"):
            parse_gdsii_bytes(b"\x00\x01")

    def test_garbage_raises(self) -> None:
        with pytest.raises(GdsiiParseError, match="非 GDSII"):
            parse_gdsii_bytes(b"hello world, not gds")

    def test_unknown_record_warns_and_continues(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("TOP", TOP_BODY), ("SUB", SUB_BODY)],
            extra_suffix=rec(0x37, b"\x01\x02", DT_INT2)))
        assert doc["truncated"] is False
        assert any("未知记录号 0x37" in w for w in doc["warnings"])
        assert doc["structures"]["TOP"]["srefs"][0]["sname"] == "SUB"

    def test_unknown_reserved_high_record(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("T", [])], extra_suffix=rec(0x7F)))
        assert any("0x7F" in w for w in doc["warnings"])

    def test_zero_length_stops_stream(self) -> None:
        head = MAIN_BYTES[: len(MAIN_BYTES) - len(rec(0x04))]
        doc = parse_gdsii_bytes(head + b"\x00\x00\x04\x00")
        assert doc["truncated"] is True
        assert any("流停止" in w for w in doc["warnings"])
        assert "TOP" in doc["structures"]  # 已收面如实保留

    def test_truncated_header_stops(self) -> None:
        # 流尾留 1 字节（< 最小记录头 4 字节）：真"头截断"形态
        doc = parse_gdsii_bytes(build_library(
            [("T", [])], with_endlib=False, extra_suffix=b"\x00"))
        assert doc["truncated"] is True
        assert any("记录头截断" in w for w in doc["warnings"])

    def test_declared_length_overflow_stops(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("T", [])], extra_suffix=b"\xff\xff\x08\x00"))
        assert doc["truncated"] is True
        assert any("超出剩余" in w for w in doc["warnings"])

    def test_length_below_four_stops(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("T", [])], extra_suffix=b"\x00\x02\x08\x00"))
        assert doc["truncated"] is True
        assert any("记录长度 2 < 4" in w for w in doc["warnings"])

    def test_trailing_bytes_after_endlib(self) -> None:
        doc = parse_gdsii_bytes(MAIN_BYTES + rec(0x11))
        assert doc["truncated"] is False
        assert any("ENDLIB 后仍有" in w for w in doc["warnings"])

    def test_truncated_midstream_keeps_structures(self) -> None:
        doc = parse_gdsii_bytes(MAIN_BYTES[:-3])
        assert doc["truncated"] is True
        assert list(doc["structures"]) == ["TOP", "SUB"]
        assert doc["structures"]["SUB"]["boundaries"][0]["layer"] == 3

    def test_missing_endlib_is_truncation(self) -> None:
        doc = parse_gdsii_bytes(MAIN_BYTES[:-len(rec(0x04))])
        assert doc["truncated"] is True
        assert any("ENDLIB" in w for w in doc["warnings"])

    def test_partial_element_at_endstr_materializes(self) -> None:
        partial = rec(0x08) + rec(0x0D, i2(7), DT_INT2)  # 无 DATATYPE/XY/ENDEL
        doc = parse_gdsii_bytes(build_library([("T", [partial])]))
        b = doc["structures"]["T"]["boundaries"]
        assert len(b) == 1 and b[0]["layer"] == 7
        assert b[0]["datatype"] is None and b[0]["points_xy"] == []
        assert any("截断态物化" in w for w in doc["warnings"])

    def test_structure_without_endstr_at_eof(self) -> None:
        out = (rec(0x00, i2(600), DT_INT2) + rec(0x01, ts())
               + rec(0x05, ts()) + rec(0x06, ascii_padded("T"))
               + boundary_records(1, 0, [(0, 0), (1, 1), (0, 0)]))
        doc = parse_gdsii_bytes(out)
        assert doc["truncated"] is True
        assert doc["structures"]["T"]["boundaries"][0]["layer"] == 1
        assert any("缺 ENDSTR" in w for w in doc["warnings"])

    def test_warning_dedupe_same_text(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("T", [])],
            extra_suffix=rec(0x37) + rec(0x37) + rec(0x38)))
        unknowns = [w for w in doc["warnings"] if w.startswith("未知记录号")]
        assert len(unknowns) == 2  # 同文 0x37 去重、异号 0x38 独立

    def test_node_textnode_skips_with_warning(self) -> None:
        node = rec(0x15) + rec(0x0D, i2(1), DT_INT2) \
            + rec(0x10, xy([(0, 0)]), DT_INT4) + rec(0x11)
        doc = parse_gdsii_bytes(build_library([("T", [node])]))
        assert any("NODE" in w for w in doc["warnings"])
        assert doc["structures"]["T"]["boxes"] == []

    def test_zero_length_buckets_intact(self) -> None:
        # 零 length 停流后的既有六桶键面完整（fail-soft 不破坏 schema）
        head = MAIN_BYTES[: len(MAIN_BYTES) - len(rec(0x04))]
        doc = parse_gdsii_bytes(head + b"\x00\x00\x04\x00")
        for bucket in ("boundaries", "paths", "srefs", "arefs", "texts",
                       "boxes"):
            assert bucket in doc["structures"]["TOP"]

# ══════════════════════════ 拓扑 1：层级统计 ══════════════════════════

class TestHierarchyStats:
    def test_reference_counts(self) -> None:
        st = gdsii_hierarchy_stats(MAIN_DOC)
        assert st["reference_counts"] == {"TOP": 0, "SUB": 3}

    def test_undefined_reference(self) -> None:
        body = [*TOP_BODY, sref_records("GHOST", 1, 1)]
        doc = parse_gdsii_bytes(build_library([("TOP", body), ("SUB",
                                                               SUB_BODY)]))
        st = gdsii_hierarchy_stats(doc)
        assert st["undefined_references"] == [{"sname": "GHOST",
                                               "n_refs": 1}]
        assert st["reference_counts"]["SUB"] == 3

    def test_undefined_counts_aggregate(self) -> None:
        body = [*TOP_BODY, sref_records("GHOST", 0, 0),
                aref_records("GHOST", 2, 2, [(0, 0), (1, 0), (0, 1)])]
        doc = parse_gdsii_bytes(build_library(
            [("TOP", body), ("SUB", SUB_BODY)]))
        st = gdsii_hierarchy_stats(doc)
        assert st["undefined_references"] == [{"sname": "GHOST",
                                               "n_refs": 2}]
        assert st["reference_counts"]["SUB"] == 3

    def test_orphan_structure(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("TOP", TOP_BODY), ("SUB", SUB_BODY), ("EMPTY", [])]))
        st = gdsii_hierarchy_stats(doc)
        assert st["orphan_structures"] == ["EMPTY"]  # 零引用且零元素

    def test_unreferenced_superset(self) -> None:
        st = gdsii_hierarchy_stats(MAIN_DOC)
        # 宁多报口径：零引用桶含非空顶层 TOP；SUB 被引用不在桶内
        assert st["unreferenced_structures"] == ["TOP"]
        assert st["orphan_structures"] == []

    def test_hierarchy_empty_doc(self) -> None:
        st = gdsii_hierarchy_stats(parse_gdsii_bytes(build_library([])))
        assert st == {
            "n_structures": 0, "reference_counts": {},
            "undefined_references": [], "orphan_structures": [],
            "unreferenced_structures": [],
        }

    def test_sref_none_sname_ignored(self) -> None:
        body = rec(0x0A) + rec(0x10, xy([(0, 0)]), DT_INT4) + rec(0x11)
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        st = gdsii_hierarchy_stats(doc)
        assert st["undefined_references"] == []

# ══════════════════════════ 拓扑 2：层汇总 ══════════════════════════

class TestLayerSummary:
    def test_layer_keys_sorted(self) -> None:
        ls = gdsii_layer_summary(MAIN_DOC)
        assert ls["n_layer_keys"] == 5
        keys = [(e["layer"], e["datatype"]) for e in ls["layers"]]
        assert keys == [(1, 0), (1, 5), (2, 0), (3, 0), (5, 0)]

    def test_layer_bbox_boundary(self) -> None:
        ls = gdsii_layer_summary(MAIN_DOC)
        assert ls["layers"][0]["bbox_dbu"] == [0, 0, 4, 4]
        assert ls["layers"][0]["by_kind"] == {"boundary": 1}
        assert ls["layers"][1]["bbox_dbu"] == [0, 0, 2, 2]

    def test_layer_bbox_path_and_text(self) -> None:
        ls = gdsii_layer_summary(MAIN_DOC)
        assert ls["layers"][2]["bbox_dbu"] == [0, 0, 10, 5]
        assert ls["layers"][4]["bbox_dbu"] == [1, 1, 1, 1]
        assert ls["layers"][4]["by_kind"] == {"text": 1}

    def test_layer_same_key_aggregates_kinds(self) -> None:
        body = [boundary_records(4, 1, [(0, 0), (1, 1), (0, 0)]),
                path_records(4, 1, 10, 0, [(2, 2), (5, 5)])]
        doc = parse_gdsii_bytes(build_library([("T", body)]))
        ls = gdsii_layer_summary(doc)
        assert ls["n_layer_keys"] == 1
        ent = ls["layers"][0]
        assert ent["n_elements"] == 2
        assert ent["by_kind"] == {"boundary": 1, "path": 1}
        assert ent["bbox_dbu"] == [0, 0, 5, 5]

    def test_layer_summary_empty(self) -> None:
        ls = gdsii_layer_summary(parse_gdsii_bytes(build_library([])))
        assert ls == {"n_layer_keys": 0, "layers": []}

    def test_text_uses_texttype_as_datatype(self) -> None:
        body = text_records(5, 3, "L", 0, 0)
        doc = parse_gdsii_bytes(build_library([("T", [body])]))
        ls = gdsii_layer_summary(doc)
        assert (ls["layers"][0]["layer"], ls["layers"][0]["datatype"]) == \
            (5, 3)

# ══════════════════════════ 拓扑 3：递归展开包围盒 ══════════════════════════

class TestExpandBBox:
    def test_expand_top_hand_computed(self) -> None:
        bb = gdsii_expand_bbox(MAIN_DOC, "TOP")
        assert bb["bbox_dbu"] == [0, 0, 101, 21]
        assert bb["stats"]["n_refs_seen"] == 3
        assert bb["stats"]["n_refs_expanded"] == 3
        assert bb["skipped_refs"] == []
        assert bb["warnings"] == []

    def test_expand_sub_and_um(self) -> None:
        bb = gdsii_expand_bbox(MAIN_DOC, "SUB")
        assert bb["bbox_dbu"] == [0, 0, 2, 1]
        assert bb["bbox_um"] is not None
        assert bb["bbox_um"][2] == pytest.approx(0.002)
        assert bb["bbox_um"][3] == pytest.approx(0.001)

    def test_expand_90_rotation_hand(self) -> None:
        # SUB [0,0,2,1] 旋转 90°（无反射）：角点 (x,y)→(−y,x) →
        # [−1,0,0,2] + 偏移 (5,5) = [4,5,5,7]
        body = [sref_records("SUB", 5, 5, angle=90.0)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        bb = gdsii_expand_bbox(doc, "T")
        assert bb["bbox_dbu"] == [4, 5, 5, 7]

    def test_expand_180_rotation_hand(self) -> None:
        # [0,0,2,1] 旋转 180° → [−2,−1,0,0] + (3,3) = [1,2,3,3]
        body = [sref_records("SUB", 3, 3, angle=180.0)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [1, 2, 3, 3]

    def test_expand_270_rotation_hand(self) -> None:
        # [0,0,2,1] 旋转 270°：(x,y)→(y,−x) → [0,−2,1,0] + (4,2) = [4,0,5,2]
        body = [sref_records("SUB", 4, 2, angle=270.0)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [4, 0, 5, 2]

    def test_expand_reflection_only_hand(self) -> None:
        # [0,0,2,1] 反射 y→−y → [0,−1,2,0] + (0,10) = [0,9,2,10]
        body = [sref_records("SUB", 0, 10, strans=0x8000)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [0, 9, 2, 10]

    def test_expand_reflected_90_combo(self) -> None:
        # 主夹具 SREF2：反射+90° @(100,0) → [100,0,101,2]（手算参考）
        doc = parse_gdsii_bytes(build_library(
            [("T", [sref_records("SUB", 100, 0, strans=0x8000,
                                 angle=90.0)]),
             ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [100, 0, 101, 2]

    def test_expand_arbitrary_angle_skipped(self) -> None:
        body = [sref_records("SUB", 1, 1, angle=45.0),
                boundary_records(1, 0, [(0, 0), (2, 2), (0, 0)])]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        bb = gdsii_expand_bbox(doc, "T")
        assert bb["bbox_dbu"] == [0, 0, 2, 2]  # 仅自身边界，不近似展开
        assert bb["stats"]["n_refs_skipped"] == 1
        assert bb["skipped_refs"][0]["reason"] == "任意角度不精确展开"
        assert any("45.0" in w for w in bb["warnings"])

    def test_expand_negative_angle_normalized_to_exact(self) -> None:
        # -90° ≡ 270°（模 360 归一）：[0,0,2,1] → [0,−2,1,0] + (2,2)
        body = [sref_records("SUB", 2, 2, angle=-90.0)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        bb = gdsii_expand_bbox(doc, "T")
        assert bb["bbox_dbu"] == [2, 0, 3, 2]
        assert bb["stats"]["n_refs_skipped"] == 0

    def test_expand_mag2_skipped(self) -> None:
        body = [sref_records("SUB", 1, 1, mag=2.0)]
        doc = parse_gdsii_bytes(build_library(
            [("T", body), ("SUB", SUB_BODY)]))
        bb = gdsii_expand_bbox(doc, "T")
        assert bb["bbox_dbu"] is None  # 无其他元素，跳过后空
        assert bb["skipped_refs"][0]["reason"] == "mag≠1 不近似展开"

    def test_expand_aref_endpoints_hand(self) -> None:
        # 2×2 锚 [(40,0),(42,0),(40,2)]：格位均匀落段 → 端点极值
        # 元素 [0,0,2,1] + x∈{40,42}, y∈{0,2} → [40,0,44,3]
        bb = gdsii_expand_bbox(MAIN_DOC, "TOP")
        assert bb["bbox_dbu"] == [0, 0, 101, 21]  # 含 AREF 面
        doc2 = parse_gdsii_bytes(build_library(
            [("T", [aref_records("SUB", 2, 2, [(40, 0), (42, 0), (40, 2)])]),
             ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc2, "T")["bbox_dbu"] == [40, 0, 44, 3]

    def test_expand_aref_3x3_noninteger_step(self) -> None:
        # 3×3 锚 [(0,0),(4,0),(0,4)]：列步进 2（整除）；端点极值法对
        # 中间格位无依赖 → bbox [0,0,6,5]（元素 [0,0,2,1]+max anchor）
        doc = parse_gdsii_bytes(build_library(
            [("T", [aref_records("SUB", 3, 3, [(0, 0), (4, 0), (0, 4)])]),
             ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [0, 0, 6, 5]

    def test_expand_aref_single_cell_ignores_far_anchors(self) -> None:
        # cols=rows=1：步进未定义，仅锚 0 计入（远锚点如实忽略）
        doc = parse_gdsii_bytes(build_library(
            [("T", [aref_records("SUB", 1, 1, [(0, 0), (99, 99), (98, 98)])]),
             ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [0, 0, 2, 1]

    def test_expand_aref_rotated_content(self) -> None:
        # AREF 携带 90° 旋转（STRANS 只作用于被引用内容、锚点在父坐标）：
        # 元素 [0,0,2,1] 旋转后 [−1,0,0,2]；锚 2×2 [(10,0),(12,0),(10,2)]
        # → x∈{10,12}, y∈{0,2} → [9,0,12,4]
        doc = parse_gdsii_bytes(build_library(
            [("T", [aref_records("SUB", 2, 2, [(10, 0), (12, 0), (10, 2)],
                                angle=90.0)]),
             ("SUB", SUB_BODY)]))
        assert gdsii_expand_bbox(doc, "T")["bbox_dbu"] == [9, 0, 12, 4]

    def test_expand_cycle_guard(self) -> None:
        self_ref = [sref_records("SELF", 0, 0),
                    boundary_records(1, 0, [(0, 0), (1, 1), (0, 0)])]
        doc = parse_gdsii_bytes(build_library([("SELF", self_ref)]))
        bb = gdsii_expand_bbox(doc, "SELF")
        assert bb["bbox_dbu"] == [0, 0, 1, 1]  # 自身边界仍在
        assert any("循环引用" in w for w in bb["warnings"])

    def test_expand_mutual_cycle(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("A", [sref_records("B", 0, 0)]),
             ("B", [sref_records("A", 0, 0),
                    boundary_records(1, 0, [(0, 0), (2, 2), (0, 0)])])]))
        bb = gdsii_expand_bbox(doc, "A")
        assert any("循环引用" in w for w in bb["warnings"])
        assert bb["bbox_dbu"] == [0, 0, 2, 2]  # B 自身边界经平移 0 计入

    def test_expand_undefined_ref(self) -> None:
        body = [sref_records("GHOST", 5, 5)]
        doc = parse_gdsii_bytes(build_library([("T", body)]))
        bb = gdsii_expand_bbox(doc, "T")
        assert bb["bbox_dbu"] is None
        assert bb["stats"]["n_refs_undefined"] == 1
        assert any("未定义" in w for w in bb["warnings"])

    def test_expand_empty_structure_none(self) -> None:
        doc = parse_gdsii_bytes(build_library([("EMPTY", [])]))
        bb = gdsii_expand_bbox(doc, "EMPTY")
        assert bb["bbox_dbu"] is None and bb["bbox_um"] is None

    def test_expand_unknown_name_raises(self) -> None:
        with pytest.raises(KeyError, match="NOPE"):
            gdsii_expand_bbox(MAIN_DOC, "NOPE")

    def test_expand_missing_units_um_none(self) -> None:
        doc = parse_gdsii_bytes(build_library(
            [("SUB", SUB_BODY)], with_units=False))
        bb = gdsii_expand_bbox(doc, "SUB")
        assert bb["bbox_dbu"] == [0, 0, 2, 1]
        assert bb["bbox_um"] is None

    def test_expand_depth_guard(self) -> None:
        # 300 级链式引用：深度守卫（256）触发 warning，前段仍精确展开
        structures = []
        for k in range(300):
            target = f"S{k + 1:03d}" if k < 299 else "TAIL"
            structures.append((
                f"S{k:03d}",
                [sref_records(target, 0, 0),
                 boundary_records(1, 0, [(0, 0), (2, 1), (0, 0)])]))
        structures.append(("TAIL", [boundary_records(
            1, 0, [(0, 0), (2, 1), (0, 0)])]))
        doc = parse_gdsii_bytes(build_library(structures))
        bb = gdsii_expand_bbox(doc, "S000")
        assert any("引用深度超" in w for w in bb["warnings"])
        assert bb["bbox_dbu"] == [0, 0, 2, 1]
        assert bb["stats"]["n_refs_empty"] >= 1

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_envelope_keys(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = gdsii_service.parse_gdsii_file(p)
        assert result["ok"] is True
        assert result["path"] == str(p)
        assert result["lib_name"] == "QX58_LIB"
        assert result["version"] == 600
        assert result["units"]["db_um"] == pytest.approx(0.001)
        assert set(result["structures"]) == {"TOP", "SUB"}
        assert result["stats"]["n_structures"] == 2
        assert isinstance(result["warnings"], list)

    def test_parse_missing_file_error(self, tmp_path: Path) -> None:
        result = gdsii_service.parse_gdsii_file(tmp_path / "no.gds")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert "不存在" in result["errors"][0]

    def test_parse_garbage_error(self, tmp_path: Path) -> None:
        p = tmp_path / "garbage.gds"
        p.write_bytes(b"not a gdsii stream at all")
        result = gdsii_service.parse_gdsii_file(p)
        assert result["ok"] is False
        assert "GDSII 解析失败" in result["errors"][0]

    def test_parse_truncated_error_with_diagnostics(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "trunc.gds"
        p.write_bytes(MAIN_BYTES[:-3])
        result = gdsii_service.parse_gdsii_file(p)
        assert result["ok"] is False
        assert "截断" in result["errors"][0]
        assert result["n_structures_parsed"] == 2
        assert isinstance(result["warnings"], list)

    def test_layer_report_envelope(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = gdsii_service.gdsii_layer_report(p)
        assert result["ok"] is True
        assert result["n_layer_keys"] == 5
        assert result["layers"][0]["bbox_dbu"] == [0, 0, 4, 4]

    def test_layer_report_missing_error(self, tmp_path: Path) -> None:
        result = gdsii_service.gdsii_layer_report(tmp_path / "no.gds")
        assert result["ok"] is False

    def test_hierarchy_report_envelope(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = gdsii_service.gdsii_hierarchy_report(p)
        assert result["ok"] is True
        assert result["reference_counts"] == {"TOP": 0, "SUB": 3}
        assert result["undefined_references"] == []
        assert result["orphan_structures"] == []
        assert result["unreferenced_structures"] == ["TOP"]

    def test_service_deterministic(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        a = gdsii_service.parse_gdsii_file(p)
        b = gdsii_service.parse_gdsii_file(p)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

# ══════════════════════════ CLI 两叶 ══════════════════════════

class TestCli:
    def test_parse_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(gdsii_app,
                            ["parse", "--file", str(write_main(tmp_path)),
                             "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["lib_name"] == "QX58_LIB"
        assert envelope["stats"]["n_boundaries"] == 3

    def test_parse_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(
            gdsii_app, ["parse", "--file", str(tmp_path / "no.gds"),
                        "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_layers_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(gdsii_app,
                            ["layers", "--file", str(write_main(tmp_path)),
                             "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["n_layer_keys"] == 5

    def test_layers_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(
            gdsii_app, ["layers", "--file", str(tmp_path / "no.gds"),
                        "--json"])
        assert res.exit_code == 1
        assert json.loads(res.output)["ok"] is False

    def test_parse_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(gdsii_app,
                            ["parse", "--file", str(write_main(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "QX58_LIB" in res.output
        assert "TOP" in res.output and "SUB" in res.output

    def test_layers_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(gdsii_app,
                            ["layers", "--file", str(write_main(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "layer=1" in res.output

    def test_help_builds_no_bare_percent(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["parse", "--help"], ["layers", "--help"]):
            res = runner.invoke(gdsii_app, leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_missing_file_flag_fails(self) -> None:
        res = runner.invoke(gdsii_app, ["parse"])
        assert res.exit_code != 0

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：gdsii 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(gdsii_service.__file__).parent.parent.joinpath(
            "cli", "domains", "gdsii.py").read_text(encoding="utf-8")
        assert source.count('@gdsii_app.command("parse")') == 1
        assert source.count('@gdsii_app.command("layers")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
