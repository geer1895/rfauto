"""STDF 解析内核+服务+CLI 单测（aurora_q 席位 Q-X88，2026-11-08）。

夹具纪律（任务书口径）：**测试内程序化合成 STDF 字节流**——本文件自带
小 builder（``StreamBuilder.append_rec(typ, sub, payload)`` 按字节序编
码 REC_LEN+载荷；``_mir``/``_prr``/``_ptr``/``_ftr`` 字段编码 helper），
构 FAR（CPU_TYPE=1 大端主夹具 + CPU_TYPE=2 小端变体，同语义双字节序）+
MIR（3 命名字段链）+PIR/PRR 3 器件含 1 fail+PTR 4 测项含 1 fail/极限对
/UNITS+FTR 1+PCR 2+ATR 1+未知 REC_TYPE+零载荷 EPS+截断变体。零外部夹
具文件、零写盘（服务/CLI 测试经 tmp_path 落盘隔离，#144 run 湖零写入）、
零网络零真机。

覆盖面（任务书 ≥55 条）：

- 字节序自描述双向（CPU_TYPE=1 大端 / =2 小端同语义流解析等值；
  CPU_TYPE 0/3/255 fail-closed）；
- 记录头三分派（REC_LEN 载荷语义+恒大端/随 CPU_TYPE、REC_TYP、REC_SUB；
  已知不深解记录计数、未知类型/未知子类型整条跳过+计数、零载荷 EPS、
  重复 FAR 告警跳过）；
- 解码表驱动（U*1/U*2/U*4/I*2/I*4/R*4/R*8 双端已知量钉；C*n 空/ASCII/
  非 ASCII U+FFFD；D*n raw；字段截断 None+warning）；
- PTR flag 位域（TEST_FLG bit6 无判定→pass=None、bit7 fail、bit1 注记）
  /PART_FLG（bit3 fail、bit4 无判定）/MIR 链读（定长+变长串链+尾省略
  +raw tail）/FTR 链读（计数控阵列 raw 跳过+尾串链）/PCR 尾省略；
- 截断停流（记录头截断/声明载荷越界→truncated=True 已收面保留）；
- 查询三函数（fail_parts/test_lookup 流序/未知空表/yield 两口径：PCR
  汇总/PCR 逐 site/PRR 兜底/零器件 None 不猜/未判定计数）；
- 服务信封三态（ok/error/truncated 非 error）+确定性；CLI 两叶 --json
  双路径（CliRunner 直连 stdf_app——不触共享 app，零金快照漂移）+
  --help 真构建 #305 家法 + 计数链字面钉 + cli.main 零导入钉。

任务书"REC_LEN<4 停流"按公开规范重释（REC_LEN 数载荷字节、0 合法——
lot2.stdf 703 条 EPS 实证），停流条件=记录头截断/声明载荷越界，见
core/stdf_parser docstring 注记；本文件截断类测试按重释口径钉。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains.stdf import stdf_app
from rfauto.core.stdf_parser import (
    PARSER_SCHEMA_VERSION,
    PART_FLG_FAIL_BIT,
    PART_FLG_NO_PF_BIT,
    PCR_HEAD_SUMMARY,
    StdfParseError,
    parse_stdf_bytes,
    stdf_fail_parts,
    stdf_test_lookup,
    stdf_yield,
)
from rfauto.service import stdf_service

runner = CliRunner()

# ══════════════════════════ STDF 字节流 builder ══════════════════════════
# （测试夹具专用编码器；与 core 解码器互为往返验证，期望值手算注释在案）

class StreamBuilder:
    """按 CPU 字节序累积合成 STDF 记录流（记录头 REC_LEN 随 CPU_TYPE
    字节序——CPU_TYPE=2 真实文件实证口径；载荷多字节字段同序）。"""

    def __init__(self, cpu_type: int = 1) -> None:
        assert cpu_type in (1, 2)
        self.cpu_type = cpu_type
        self.endian = ">" if cpu_type == 1 else "<"
        self._chunks: list[bytes] = []

    def append_rec(self, typ: int, sub: int, payload: bytes = b"") -> None:
        """追加单记录：2B REC_LEN（随 CPU_TYPE 字节序，只数载荷）+
        1B REC_TYP + 1B REC_SUB + 载荷。"""
        self._chunks.append(
            len(payload).to_bytes(2, "big" if self.cpu_type == 1 else "little")
            + bytes([typ, sub]) + payload)

    def build(self) -> bytes:
        return b"".join(self._chunks)

def u1(v: int) -> bytes:
    return bytes([v])

def u2(v: int, e: str) -> bytes:
    return struct.pack(e + "H", v)

def u4(v: int, e: str) -> bytes:
    return struct.pack(e + "I", v)

def i1(v: int, e: str) -> bytes:
    return struct.pack(e + "b", v)

def i2(v: int, e: str) -> bytes:
    return struct.pack(e + "h", v)

def i4(v: int, e: str) -> bytes:
    return struct.pack(e + "i", v)

def r4(v: float, e: str) -> bytes:
    return struct.pack(e + "f", v)

def cn(s: str) -> bytes:
    """C*n 变长串（1B 长度+ASCII 字节）。"""
    raw = s.encode("ascii")
    assert len(raw) <= 255
    return bytes([len(raw)]) + raw

def _far(b: StreamBuilder, stdf_ver: int = 4) -> None:
    b.append_rec(0, 10, u1(b.cpu_type) + u1(stdf_ver))

def _atr(b: StreamBuilder) -> None:
    b.append_rec(0, 20, u4(1700000000, b.endian) + cn("rfauto filter"))

def _mir(b: StreamBuilder) -> None:
    """MIR：8 定长字段 + 3 命名字段链（lot_id/part_typ/oper_nam，
    中段 node_nam..sblot_id 空串占位——链序按公开规范定序）。"""
    payload = (
        u4(1700000000, b.endian)      # SETUP_T
        + u4(1700000100, b.endian)    # START_T
        + u1(1)                       # STAT_NUM
        + b"P"                        # MODE_COD
        + b" "                        # RTST_COD
        + b" "                        # PROT_COD
        + u2(0, b.endian)             # BURN_TIM
        + b" "                        # CMOD_COD
        + cn("LOT-A")                 # LOT_ID
        + cn("CHIP")                  # PART_TYP
        + cn("")                      # NODE_NAM
        + cn("")                      # TSTR_TYP
        + cn("")                      # JOB_NAM
        + cn("")                      # JOB_REV
        + cn("")                      # SBLOT_ID
        + cn("eng")                   # OPER_NAM
    )
    b.append_rec(1, 10, payload)

def _pcr(b: StreamBuilder, head: int, site: int, part: int, good: int,
         full: bool = True) -> None:
    payload = (u1(head) + u1(site) + u4(part, b.endian) + u4(0, b.endian)
               + (u4(0, b.endian) + u4(good, b.endian) + u4(0, b.endian)
                  if full else b""))
    b.append_rec(1, 30, payload)

def _pir(b: StreamBuilder) -> None:
    b.append_rec(5, 10, u1(1) + u1(1))

def _prr(b: StreamBuilder, part_id: str, *, failed: bool = False,
         no_pf: bool = False) -> None:
    """PRR：PART_FLG bit3=failed / bit4=无判定（bit4 设定时 bit3 无效）。"""
    flg = 0
    if failed:
        flg |= PART_FLG_FAIL_BIT
    if no_pf:
        flg |= PART_FLG_NO_PF_BIT
    payload = (
        u1(1) + u1(1) + u1(flg)
        + u2(10, b.endian)            # NUM_TEST
        + u2(5 if failed else 1, b.endian)   # HARD_BIN
        + u2(5 if failed else 1, b.endian)   # SOFT_BIN
        + i2(19, b.endian) + i2(-3, b.endian)  # X/Y_COORD
        + u4(1000, b.endian)          # TEST_T
        + cn(part_id) + cn("")
    )
    b.append_rec(5, 20, payload)

def _ptr(b: StreamBuilder, test_num: int, meas: float, *, failed: bool = False,
         no_pf: bool = False, no_result: bool = False, units: str = "V",
         lo: float = 0.5, hi: float = 2.5, res_scal: int = 0,
         with_spec: bool = False, txt: str | None = None) -> None:
    """PTR：TEST_FLG bit7=failed / bit6=无判定 / bit1=无 datalog 值注记；
    OPT_FLAG bit1 保留必须 1；with_spec 时补 LO_SPEC/HI_SPEC（注记口径：
    位域不控在场——bit2/3 置 1 字段仍在，core 如实解码）。"""
    flg = 0
    if failed:
        flg |= 0x80
    if no_pf:
        flg |= 0x40
    if no_result:
        flg |= 0x02
    opt = 0x02 | ((0x04 | 0x08) if with_spec else 0)
    body = (
        u4(test_num, b.endian) + u1(1) + u1(1) + u1(flg) + u1(0)
        + r4(meas, b.endian)
        + cn(txt if txt is not None else f"test_{test_num}")
        + cn("")                      # ALARM_ID
        + u1(opt)
        + i1(res_scal, b.endian) + i1(0, b.endian) + i1(0, b.endian)
        + r4(lo, b.endian) + r4(hi, b.endian)
        + cn(units)
    )
    if with_spec:
        body += r4(0.4, b.endian) + r4(3.0, b.endian)
    b.append_rec(15, 10, body)

def _ftr(b: StreamBuilder, test_num: int, *, failed: bool = False,
         num_fail: int = 2, txt: str = "func_test") -> None:
    """FTR：RTN_ICNT/PGM_ICNT=2 计数控阵列 raw（占位字节）；FAIL_PIN/
    SPIN_MAP D*n 0 位；尾链 vect_nam/test_txt。"""
    flg = 0x80 if failed else 0
    body = (
        u4(test_num, b.endian) + u1(1) + u1(1) + u1(flg) + u1(0xC0)
        + u4(1000, b.endian)          # CYCL_CNT
        + u4(0, b.endian)             # REL_VADR
        + u4(1, b.endian)             # REPT_CNT
        + u4(num_fail, b.endian)      # NUM_FAIL
        + i4(3, b.endian) + i4(-1, b.endian)  # X/YFAIL_AD
        + i2(0, b.endian)             # VECT_OFF
        + u2(2, b.endian) + u2(1, b.endian)   # RTN_ICNT / PGM_ICNT
        # RTN_INDX(2×2B) + RTN_STAT(半字节 1B) + PGM_INDX(1×2B) + PGM_STAT(1B)
        + b"\x00\x01\x00\x02" + b"\x1f" + b"\x00\x05" + b"\x03"
        + u2(0, b.endian)             # FAIL_PIN D*n：0 位
        + cn("vec1") + cn("") + cn("") + cn(txt) + cn("") + cn("") + cn("")
        + u1(1)                       # PATG_NUM
        + u2(0, b.endian)             # SPIN_MAP D*n：0 位
    )
    b.append_rec(15, 20, body)

def _unknown_rec(b: StreamBuilder, typ: int = 0x99, sub: int = 0x77) -> None:
    b.append_rec(typ, sub, b"\xde\xad\xbe\xef")

def _eps(b: StreamBuilder) -> None:
    b.append_rec(20, 20, b"")     # 零载荷记录（REC_LEN=0 合法）

def build_main(cpu_type: int = 1, *, with_trailer: bytes = b"",
               with_unknown: bool = True, with_eps: bool = True) -> bytes:
    """主夹具：FAR+ATR+MIR+PIR/PRR×3（P1 pass、P2 fail、P3 pass）+
    PTR×4（100 pass V / 200 fail A / 300 no_pf / 400 pass 换单位 Ω）+
    FTR×1（pass）+PCR×2（site + 汇总）+未知记录+EPS+trailer 注入。"""
    b = StreamBuilder(cpu_type)
    _far(b)
    _atr(b)
    _mir(b)
    _pir(b)
    _prr(b, "P1")
    _ptr(b, 100, 1.25, txt="vdd_meas")
    _ptr(b, 200, 3.75, failed=True, units="A", lo=0.1, hi=2.0)
    _ptr(b, 300, 1.0, no_pf=True, res_scal=-3)
    _ptr(b, 400, 9.5, units="ohm", lo=8.0, hi=11.0, with_spec=True)
    _ptr(b, 500, 0.0, no_result=True)
    _ftr(b, 600)
    _ftr(b, 700, failed=True, num_fail=7, txt="scan_test")
    _prr(b, "P2", failed=True)
    _pir(b)
    _prr(b, "P3")
    _pcr(b, 1, 1, 3, 2, full=False)          # site PCR（尾省略：无 GOOD_CNT）
    _pcr(b, PCR_HEAD_SUMMARY, PCR_HEAD_SUMMARY, 3, 2)
    if with_unknown:
        _unknown_rec(b)
        _unknown_rec(b, typ=0, sub=0x63)     # 已知类型+未知子类型
    if with_eps:
        _eps(b)
    b._chunks.append(with_trailer)
    return b.build()

MAIN_DOC = parse_stdf_bytes(build_main())

def write_main(tmp_path: Path, cpu_type: int = 1, **kw: bytes) -> Path:
    """主夹具落盘（tmp_path 隔离，#144 run 湖零写入）。"""
    suffix = "le" if cpu_type == 2 else "be"
    p = tmp_path / f"sample_{suffix}.stdf"
    p.write_bytes(build_main(cpu_type, **kw))
    return p

# ══════════════════════════ builder 自检 ══════════════════════════

class TestBuilder:
    def test_rec_len_counts_payload_only(self) -> None:
        # 公开规范 "Bytes of data following header"：REC_LEN 只数载荷，
        # FAR 总长 6 字节（含头）而 REC_LEN=2——demofile.stdf 实证同形。
        stream = build_main()
        assert stream[:2] == b"\x00\x02"
        assert stream[2:4] == b"\x00\x0a"

    def test_little_endian_header_rec_len(self) -> None:
        # CPU_TYPE=2 文件记录头 REC_LEN 小端（tsmap 真实文件实证口径）。
        stream = build_main(cpu_type=2)
        assert stream[:2] == b"\x02\x00"
        assert stream[4] == 2  # CPU_TYPE

    def test_builder_roundtrip_far(self) -> None:
        doc = parse_stdf_bytes(build_main(cpu_type=2))
        assert doc["far"] == {"cpu_type": 2, "cpu_endian": "little",
                              "stdf_ver": 4}

# ══════════════════════════ FAR/字节序自描述 ══════════════════════════

class TestFarEndian:
    def test_far_big_endian(self) -> None:
        assert MAIN_DOC["far"] == {"cpu_type": 1, "cpu_endian": "big",
                                   "stdf_ver": 4}

    def test_far_little_endian(self) -> None:
        doc = parse_stdf_bytes(build_main(cpu_type=2))
        assert doc["far"]["cpu_endian"] == "little"

    def test_both_endians_same_semantics(self) -> None:
        be = parse_stdf_bytes(build_main(1))
        le = parse_stdf_bytes(build_main(2))
        # 同语义双字节序流：字段值逐键相等（schema/truncated 键面一致）。
        assert be["far"]["cpu_endian"] != le["far"]["cpu_endian"]
        assert be["mir_summary"]["lot_id"] == le["mir_summary"]["lot_id"]
        assert [t["meas_val"] for t in be["parametric_tests"]] == \
            [t["meas_val"] for t in le["parametric_tests"]]
        assert [p["part_id"] for p in be["parts"]] == \
            [p["part_id"] for p in le["parts"]]
        assert be["stats"]["n_parts_passed"] == le["stats"]["n_parts_passed"]

    @pytest.mark.parametrize("cpu_type", [0, 3, 127, 255])
    def test_cpu_type_fail_closed(self, cpu_type: int) -> None:
        b = StreamBuilder(1)
        b.append_rec(0, 10, u1(cpu_type) + u1(4))
        b.append_rec(1, 10, b"\x00" * 8)
        with pytest.raises(StdfParseError, match="fail-closed"):
            parse_stdf_bytes(b.build())

    def test_empty_file_raises(self) -> None:
        with pytest.raises(StdfParseError, match="空文件"):
            parse_stdf_bytes(b"")

    def test_short_file_raises(self) -> None:
        with pytest.raises(StdfParseError, match="过短"):
            parse_stdf_bytes(b"\x00\x02\x00")

    def test_first_record_not_far_raises(self) -> None:
        # FAR 缺失（MIR 领衔）：载荷字节序无从自描述，文件级错误。
        b = StreamBuilder(1)
        b.append_rec(1, 10, b"\x00" * 16)
        with pytest.raises(StdfParseError, match="首记录非 FAR"):
            parse_stdf_bytes(b.build())

    def test_far_without_cpu_type_raises(self) -> None:
        b = StreamBuilder(1)
        b._chunks = [b"\x00\x00\x00\x0a"]  # REC_LEN=0 无载荷
        b.append_rec(1, 10, b"\x00" * 8)
        with pytest.raises(StdfParseError, match="CPU_TYPE"):
            parse_stdf_bytes(b.build())

    def test_stdf_ver_non4_warns(self) -> None:
        b = StreamBuilder(1)
        _far(b, stdf_ver=3)
        b.append_rec(1, 10, b"\x00" * 16)
        doc = parse_stdf_bytes(b.build())
        assert any("STDF_VER" in w for w in doc["warnings"])

# ══════════════════════════ 记录头三分派与流状态机 ══════════════════════════

class TestRecordStream:
    def test_zero_payload_eps_consumed(self) -> None:
        # REC_LEN=0 合法（lot2.stdf 703 条 EPS 实证）——不触发停流。
        doc = parse_stdf_bytes(build_main())
        assert doc["stats"]["per_type_counts"].get("20/20") == 1
        assert doc["truncated"] is False

    def test_header_truncation_stops(self) -> None:
        doc = parse_stdf_bytes(build_main(with_trailer=b"\x00\x02"))
        assert doc["truncated"] is True
        assert any("记录头截断" in w for w in doc["warnings"])
        # 已收面如实保留
        assert doc["stats"]["n_parts"] == 3

    def test_declared_payload_overflow_stops(self) -> None:
        # REC_LEN=100 而载荷仅 3 字节 → 声明越界停流（任务书截断意图的
        # 规范正确形态）。
        doc = parse_stdf_bytes(build_main(with_trailer=b"\x00\x64\x05\x0aabc"))
        assert doc["truncated"] is True
        assert any("声明载荷" in w for w in doc["warnings"])

    def test_unknown_type_skipped_and_counted(self) -> None:
        doc = parse_stdf_bytes(build_main())
        assert doc["stats"]["n_unknown_skipped"] == 2
        assert any("未知记录 153/119" in w for w in doc["warnings"])
        assert any("未知子类型 0/99" in w for w in doc["warnings"])

    def test_known_types_counted_not_decoded(self) -> None:
        doc = parse_stdf_bytes(build_main())
        per = doc["stats"]["per_type_counts"]
        assert per["20/20"] == 1          # EPS
        assert per["0/20"] == 1           # ATR（深解）
        assert "10/30" not in per          # TSR 不在夹具
        # 已知不深解记录不进深解计数
        assert doc["counts"] == {"n_atr": 1, "n_mir": 1, "n_pcr": 2,
                                 "n_pir": 2, "n_prr": 3, "n_ptr": 5,
                                 "n_ftr": 2}

    def test_duplicate_far_warns_and_skips(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        _mir(b)
        _far(b)  # 流中重复 FAR（规范：FAR 必居首）
        doc = parse_stdf_bytes(b.build())
        assert doc["far"]["cpu_type"] == 1
        assert any("重复 FAR" in w for w in doc["warnings"])

    def test_stats_counts(self) -> None:
        st = MAIN_DOC["stats"]
        # FAR+ATR+MIR+PIR+PRR+5PTR+2FTR+PRR+PIR+PRR+2PCR+2unknown+EPS = 20
        assert st["n_records_total"] == 20
        assert st["n_parts"] == 3
        assert st["n_parts_passed"] == 2
        assert st["n_unknown_skipped"] == 2

    def test_schema_version_and_determinism(self) -> None:
        assert MAIN_DOC["schema_version"] == PARSER_SCHEMA_VERSION
        a = parse_stdf_bytes(build_main())
        b = parse_stdf_bytes(build_main())
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_stream_order_preserved(self) -> None:
        # parametric_tests/parts 均流序平表（结构子集边界：不按 head/site
        # 构器件归属边）。
        assert [t["test_num"] for t in MAIN_DOC["parametric_tests"]] == \
            [100, 200, 300, 400, 500]
        assert [p["part_id"] for p in MAIN_DOC["parts"]] == ["P1", "P2", "P3"]

# ══════════════════════════ 解码表驱动 ══════════════════════════

class TestDecodeTypes:
    def test_u4_i2_r4_big_table(self) -> None:
        # 已知量钉（大端）：builder 编码 vs core 解码往返 + 手算期望。
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(0, 20, u4(0x5F5E1000, ">") + cn("x"))  # ATR MOD_TIM
        doc = parse_stdf_bytes(b.build())
        assert doc["atr_records"][0]["mod_tim"] == 0x5F5E1000
        assert doc["atr_records"][0]["cmd_line"] == "x"

    def test_u4_little_endian(self) -> None:
        b = StreamBuilder(2)
        _far(b)
        b.append_rec(0, 20, u4(1, "<") + cn("y"))
        doc = parse_stdf_bytes(b.build())
        assert doc["atr_records"][0]["mod_tim"] == 1

    def test_r4_value_from_ptr(self) -> None:
        # PTR 100 meas=1.25（2 的幂，双字节序下 R*4 逐位一致）
        t = MAIN_DOC["parametric_tests"][0]
        assert t["meas_val"] == pytest.approx(1.25)
        le = parse_stdf_bytes(build_main(2))
        assert le["parametric_tests"][0]["meas_val"] == pytest.approx(1.25)

    def test_r4_negative(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        _ptr(b, 7, -0.66)
        doc = parse_stdf_bytes(b.build())
        assert doc["parametric_tests"][0]["meas_val"] == pytest.approx(-0.66)

    def test_cn_empty_string(self) -> None:
        t = MAIN_DOC["parametric_tests"][0]
        assert t["alarm_id"] == ""

    def test_cn_ascii(self) -> None:
        assert MAIN_DOC["mir_summary"]["lot_id"] == "LOT-A"

    def test_cn_non_ascii_replaced(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(0, 20, u4(0, ">") + b"\x03ab\xff")  # 高位字节
        doc = parse_stdf_bytes(b.build())
        assert doc["atr_records"][0]["cmd_line"] == "ab\ufffd"

    def test_truncated_field_none_with_warning(self) -> None:
        # C*n 声明长度超出剩余 → 字段 None + warning（fail-soft 宁缺不猜）
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(0, 20, u4(0, ">") + b"\x05ab")  # 声明 5 只剩 2
        doc = parse_stdf_bytes(b.build())
        assert doc["atr_records"][0]["cmd_line"] is None
        assert any("声明长度" in w for w in doc["warnings"])

    def test_insufficient_fixed_field_none(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(0, 20, b"\x00\x01")  # U*4 只有 2 字节
        doc = parse_stdf_bytes(b.build())
        assert doc["atr_records"][0]["mod_tim"] is None
        assert any("载荷不足" in w for w in doc["warnings"])

# ══════════════════════════ MIR 链读 ══════════════════════════

class TestMir:
    def test_three_named_fields(self) -> None:
        mir = MAIN_DOC["mir_summary"]
        assert mir["lot_id"] == "LOT-A"
        assert mir["part_typ"] == "CHIP"
        assert mir["oper_nam"] == "eng"

    def test_fixed_fields(self) -> None:
        mir = MAIN_DOC["mir_summary"]
        assert mir["setup_t"] == 1700000000
        assert mir["start_t"] == 1700000100
        assert mir["stat_num"] == 1
        assert mir["mode_cod"] == "P"
        assert mir["burn_tim"] == 0
        assert mir["cmod_cod"] == " "

    def test_middle_empty_strings(self) -> None:
        mir = MAIN_DOC["mir_summary"]
        assert mir["node_nam"] == ""
        assert mir["tstr_typ"] == ""
        assert mir["job_nam"] == ""
        assert mir["sblot_id"] == ""

    def test_tail_omission_none(self) -> None:
        # OPER_NAM 之后的已知字段（exec_typ..supr_nam）尾省略 → None。
        mir = MAIN_DOC["mir_summary"]
        assert mir["exec_typ"] is None
        assert mir["supr_nam"] is None
        assert mir["raw_tail_bytes"] == 0

    def test_raw_tail_bytes_beyond_known_chain(self) -> None:
        # SUPR_NAM 之后残余字节 = 供应商扩展 raw 跳过 + 计数 + warning。
        b = StreamBuilder(1)
        _far(b)
        payload = (
            u4(0, ">") + u4(0, ">") + u1(0) + b"   " + u2(0, ">") + b" "
            + cn("L") + cn("T") + cn("") * 28   # lot/part + 中段 28 串全空
            + cn("L")                     # SUPR_NAM 之后的供应商扩展
        )
        b.append_rec(1, 10, payload)
        doc = parse_stdf_bytes(b.build())
        assert doc["mir_summary"]["raw_tail_bytes"] == 2
        assert any("供应商扩展" in w for w in doc["warnings"])

    def test_mir_exhaustion_mid_chain(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(1, 10, u4(1, ">") + u4(2, ">"))  # 只有 8 字节
        doc = parse_stdf_bytes(b.build())
        mir = doc["mir_summary"]
        assert mir["setup_t"] == 1 and mir["start_t"] == 2
        assert mir["stat_num"] is None
        assert any("载荷耗尽" in w for w in doc["warnings"])

# ══════════════════════════ PIR/PRR 与 PART_FLG 位域 ══════════════════════════

class TestPirPrr:
    def test_three_parts_stream_order(self) -> None:
        assert [p["part_id"] for p in MAIN_DOC["parts"]] == ["P1", "P2", "P3"]

    def test_part_flg_fail_bit(self) -> None:
        # PART_FLG bit3=1 → failed（公开规范）；bit3=0 → passed。
        assert MAIN_DOC["parts"][0]["pass"] is True
        assert MAIN_DOC["parts"][1]["pass"] is False
        assert MAIN_DOC["parts"][1]["part_flg"] == PART_FLG_FAIL_BIT

    def test_part_flg_no_pf_bit(self) -> None:
        # bit4=1 无 pass/fail 判定（bit3 无效）→ pass=None 如实。
        b = StreamBuilder(1)
        _far(b)
        _prr(b, "PX", failed=True, no_pf=True)
        doc = parse_stdf_bytes(b.build())
        part = doc["parts"][0]
        assert part["pass"] is None
        assert part["part_flg"] == (PART_FLG_FAIL_BIT | PART_FLG_NO_PF_BIT)

    def test_part_counts_and_coords(self) -> None:
        p = MAIN_DOC["parts"][0]
        assert p["head_num"] == 1 and p["site_num"] == 1
        assert p["num_test"] == 10
        assert p["hard_bin"] == 1 and p["soft_bin"] == 1
        assert p["x_coord"] == 19 and p["y_coord"] == -3
        assert p["test_t"] == 1000

    def test_fail_part_bins(self) -> None:
        p = MAIN_DOC["parts"][1]
        assert p["hard_bin"] == 5 and p["soft_bin"] == 5

    def test_prr_fixed_only_part_id_none(self) -> None:
        # 17 字节定长形态（尾省略 PART_ID/PART_TXT/PART_FIX）→ None。
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(5, 20, u1(1) + u1(1) + u1(0) + u2(1, ">") + u2(1, ">")
                     + u2(1, ">") + i2(-32768, ">") + i2(32767, ">")
                     + u4(0, ">"))
        doc = parse_stdf_bytes(b.build())
        p = doc["parts"][0]
        assert p["part_id"] is None
        assert p["part_txt"] is None
        assert p["pass"] is True

    def test_n_pir_counted(self) -> None:
        assert MAIN_DOC["counts"]["n_pir"] == 2
        assert MAIN_DOC["counts"]["n_prr"] == 3

# ══════════════════════════ PTR 链读与 TEST_FLG 位域 ══════════════════════════

class TestPtr:
    def test_five_tests_stream_order(self) -> None:
        assert [t["test_num"] for t in MAIN_DOC["parametric_tests"]] == \
            [100, 200, 300, 400, 500]

    def test_meas_val_and_pass(self) -> None:
        t = MAIN_DOC["parametric_tests"][0]
        assert t["meas_val"] == pytest.approx(1.25)
        assert t["pass"] is True
        assert t["test_txt"] == "vdd_meas"

    def test_fail_flag_bit7(self) -> None:
        t = MAIN_DOC["parametric_tests"][1]
        assert t["pass"] is False
        assert t["test_flg_raw"] == 0x80
        assert t["units"] == "A"
        assert t["lo_limit"] == pytest.approx(0.1)
        assert t["hi_limit"] == pytest.approx(2.0)

    def test_no_pf_flag_bit6(self) -> None:
        t = MAIN_DOC["parametric_tests"][2]
        assert t["pass"] is None
        assert t["test_flg_raw"] == 0x40
        assert t["res_scal"] == -3

    def test_units_and_limits(self) -> None:
        t = MAIN_DOC["parametric_tests"][3]
        assert t["units"] == "ohm"
        assert t["lo_limit"] == pytest.approx(8.0)
        assert t["hi_limit"] == pytest.approx(11.0)
        assert t["lo_spec"] == pytest.approx(0.4)
        assert t["hi_spec"] == pytest.approx(3.0)
        assert t["opt_flag_raw"] == 0x0E

    def test_no_result_annotation_only(self) -> None:
        # TEST_FLG bit1=1 语义=无 datalog 值（原值注记）；位域不控字段
        # 在场——夹具照写 RESULT，core 如实解码（真实文件位域注记口径）。
        t = MAIN_DOC["parametric_tests"][4]
        assert t["test_flg_raw"] == 0x02
        assert t["meas_val"] == pytest.approx(0.0)

    def test_result_omitted_by_exhaustion(self) -> None:
        # 记录尾真省略形态：只写 TEST_NUM..PARM_FLG 8 字节 → meas_val
        # None（字节门控）。
        b = StreamBuilder(1)
        _far(b)
        b.append_rec(15, 10, u4(9, ">") + u1(1) + u1(1) + u1(0) + u1(0))
        doc = parse_stdf_bytes(b.build())
        t = doc["parametric_tests"][0]
        assert t["test_num"] == 9
        assert t["meas_val"] is None
        assert t["pass"] is True

    def test_scale_bytes_grouped_before_limits(self) -> None:
        # 公开规范定序：RES/LLM/HLM 三 scale 连排在前、两 limit 随后
        # （demofile.stdf PTR#1 逐字节实证口径）。
        t = MAIN_DOC["parametric_tests"][0]
        assert (t["res_scal"], t["llm_scal"], t["hlm_scal"]) == (0, 0, 0)

    def test_ptr_head_site(self) -> None:
        t = MAIN_DOC["parametric_tests"][0]
        assert t["head_num"] == 1 and t["site_num"] == 1

# ══════════════════════════ FTR 链读 ══════════════════════════

class TestFtr:
    def test_ftr_pass_and_txt(self) -> None:
        f = MAIN_DOC["functional_tests"][0]
        assert f["test_num"] == 600
        assert f["pass"] is True
        assert f["test_txt"] == "func_test"
        assert f["vect_nam"] == "vec1"

    def test_ftr_fail_flag(self) -> None:
        f = MAIN_DOC["functional_tests"][1]
        assert f["pass"] is False
        assert f["num_fail"] == 7
        assert f["test_txt"] == "scan_test"

    def test_ftr_optional_fields(self) -> None:
        f = MAIN_DOC["functional_tests"][0]
        assert f["cycl_cnt"] == 1000
        assert f["rept_cnt"] == 1
        assert f["rel_vadr"] == 0
        assert f["xfail_ad"] == 3 and f["yfail_ad"] == -1
        assert f["vect_off"] == 0
        assert f["patg_num"] == 1

    def test_ftr_count_controlled_arrays_raw_skip(self) -> None:
        # RTN_ICNT/PGM_ICNT 计数控阵列 raw 跳过不展开——计数落键、
        # 尾链（vect_nam/test_txt）仍正确解码。
        f = MAIN_DOC["functional_tests"][0]
        assert f["rtn_icnt"] == 2 and f["pgm_icnt"] == 1
        assert f["vect_nam"] == "vec1"
        assert f["alarm_id"] == ""

    def test_ftr_no_pf(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        _ftr(b, 1, failed=False)
        doc = parse_stdf_bytes(b.build())
        assert doc["functional_tests"][0]["pass"] is True

    def test_ftr_counted(self) -> None:
        assert MAIN_DOC["counts"]["n_ftr"] == 2

# ══════════════════════════ PCR 与截断 ══════════════════════════

class TestPcr:
    def test_summary_pcr_full(self) -> None:
        pcr = next(p for p in MAIN_DOC["pcr_records"]
                   if p["head_num"] == PCR_HEAD_SUMMARY)
        assert pcr["part_cnt"] == 3
        assert pcr["good_cnt"] == 2
        assert pcr["func_cnt"] == 0

    def test_site_pcr_tail_omission(self) -> None:
        # 10 字节形态（截到 RTST_CNT）→ ABRT/GOOD/FUNC None + warning
        # （lot2.stdf PCR 载荷 10 字节实证同形）。
        pcr = next(p for p in MAIN_DOC["pcr_records"]
                   if p["head_num"] != PCR_HEAD_SUMMARY)
        assert pcr["part_cnt"] == 3
        assert pcr["rtst_cnt"] == 0
        assert pcr["good_cnt"] is None
        assert any("PCR 载荷耗尽" in w for w in MAIN_DOC["warnings"])

    def test_pcr_counted(self) -> None:
        assert MAIN_DOC["counts"]["n_pcr"] == 2

    def test_atr_records(self) -> None:
        assert MAIN_DOC["atr_records"] == [
            {"mod_tim": 1700000000, "cmd_line": "rfauto filter"}]

# ══════════════════════════ 查询三函数 ══════════════════════════

class TestQueries:
    def test_fail_parts(self) -> None:
        fails = stdf_fail_parts(MAIN_DOC)
        assert [p["part_id"] for p in fails] == ["P2"]
        assert all(p["pass"] is False for p in fails)

    def test_fail_parts_none_not_included(self) -> None:
        # 未判定（pass=None）≠失败——如实口径不入 fail 清单。
        b = StreamBuilder(1)
        _far(b)
        _prr(b, "PA", no_pf=True)
        doc = parse_stdf_bytes(b.build())
        assert stdf_fail_parts(doc) == []

    def test_test_lookup_sequence(self) -> None:
        # 单测项单点：meas/pass/units/limits 随行。
        pts = stdf_test_lookup(MAIN_DOC, 100)
        assert len(pts) == 1
        assert pts[0]["meas_val"] == pytest.approx(1.25)
        assert pts[0]["pass"] is True
        assert pts[0]["units"] == "V"
        assert pts[0]["lo_limit"] == pytest.approx(0.5)

    def test_test_lookup_multi_point_order(self) -> None:
        # 同 test_num 多次记录 → 流序点列。
        b = StreamBuilder(1)
        _far(b)
        _ptr(b, 42, 1.0)
        _ptr(b, 42, 2.0)
        _ptr(b, 42, 3.0)
        doc = parse_stdf_bytes(b.build())
        pts = stdf_test_lookup(doc, 42)
        assert [p["meas_val"] for p in pts] == [pytest.approx(1.0),
                                                pytest.approx(2.0),
                                                pytest.approx(3.0)]

    def test_test_lookup_unknown_empty(self) -> None:
        assert stdf_test_lookup(MAIN_DOC, 99999) == []

    def test_yield_pcr_summary_wins(self) -> None:
        # PCR 优先：HEAD_NUM=255 汇总记录在场且 GOOD_CNT 在场 → PCR 口径。
        y = stdf_yield(MAIN_DOC)
        assert y["source"] == "pcr_summary"
        assert y["n_parts"] == 3
        assert y["n_passed"] == 2
        assert y["yield_ratio"] == pytest.approx(2 / 3)

    def test_yield_pcr_sites_aggregate(self) -> None:
        # 无汇总 → 逐 site PCR 求和（两 site 均带 GOOD_CNT）。
        b = StreamBuilder(1)
        _far(b)
        _pcr(b, 1, 1, 10, 8)
        _pcr(b, 1, 2, 10, 7)
        doc = parse_stdf_bytes(b.build())
        y = stdf_yield(doc)
        assert y["source"] == "pcr_sites"
        assert y["n_parts"] == 20 and y["n_passed"] == 15
        assert y["yield_ratio"] == pytest.approx(0.75)

    def test_yield_prr_fallback_on_pcr_without_good_cnt(self) -> None:
        # PCR GOOD_CNT 缺失（尾省略形态）→ PRR 统计兜底（None 当 0 会
        # 伪造 yield=0，禁止）。
        b = StreamBuilder(1)
        _far(b)
        _prr(b, "P1")
        _prr(b, "P2", failed=True)
        _pcr(b, PCR_HEAD_SUMMARY, PCR_HEAD_SUMMARY, 2, 0, full=False)
        doc = parse_stdf_bytes(b.build())
        y = stdf_yield(doc)
        assert y["source"] == "prr"
        assert y["n_parts"] == 2 and y["n_passed"] == 1
        assert y["yield_ratio"] == pytest.approx(0.5)

    def test_yield_pcr_zero_parts_falls_to_prr(self) -> None:
        b = StreamBuilder(1)
        _far(b)
        _prr(b, "P1")
        _pcr(b, PCR_HEAD_SUMMARY, PCR_HEAD_SUMMARY, 0, 0)
        doc = parse_stdf_bytes(b.build())
        y = stdf_yield(doc)
        assert y["source"] == "prr"

    def test_yield_prr_undecided_counted(self) -> None:
        # pass=None 器件计 n_undecided（不计通过也不冒充失败）。
        b = StreamBuilder(1)
        _far(b)
        _prr(b, "P1")
        _prr(b, "P2", no_pf=True)
        doc = parse_stdf_bytes(b.build())
        y = stdf_yield(doc)
        assert y["n_parts"] == 2 and y["n_passed"] == 1
        assert y["n_undecided"] == 1
        assert y["yield_ratio"] == pytest.approx(0.5)

    def test_yield_zero_parts_none(self) -> None:
        # 零器件（无 PCR 且无 PRR）→ yield_ratio=None 不猜。
        b = StreamBuilder(1)
        _far(b)
        doc = parse_stdf_bytes(b.build())
        y = stdf_yield(doc)
        assert y == {"source": None, "n_parts": 0, "n_passed": 0,
                     "n_undecided": 0, "yield_ratio": None}

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_envelope_keys(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = stdf_service.parse_stdf_file(p)
        assert result["ok"] is True
        assert result["path"] == str(p)
        assert result["far"]["cpu_type"] == 1
        assert result["mir_summary"]["lot_id"] == "LOT-A"
        assert result["stats"]["n_parts"] == 3
        assert result["truncated"] is False
        assert isinstance(result["warnings"], list)

    def test_parse_missing_file_error(self, tmp_path: Path) -> None:
        result = stdf_service.parse_stdf_file(tmp_path / "no.stdf")
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert "不存在" in result["errors"][0]

    def test_parse_garbage_far_missing_error(self, tmp_path: Path) -> None:
        p = tmp_path / "garbage.stdf"
        p.write_bytes(b"not stdf at all....")
        result = stdf_service.parse_stdf_file(p)
        assert result["ok"] is False
        assert "STDF 解析失败" in result["errors"][0]

    def test_parse_truncated_ok_with_flag(self, tmp_path: Path) -> None:
        # 流中截断不是 error（ATE 崩溃半截文件是常态）——ok=True +
        # truncated=True + 已收面如实。
        p = write_main(tmp_path, with_trailer=b"\x00\x64\x05\x0aabc")
        result = stdf_service.parse_stdf_file(p)
        assert result["ok"] is True
        assert result["truncated"] is True
        assert result["stats"]["n_parts"] == 3

    def test_report_envelope(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = stdf_service.stdf_report(p)
        assert result["ok"] is True
        assert result["lot_id"] == "LOT-A"
        assert result["part_typ"] == "CHIP"
        assert result["yield_stats"]["source"] == "pcr_summary"
        assert result["yield_stats"]["n_passed"] == 2
        assert len(result["fail_parts"]) == 1

    def test_report_missing_error(self, tmp_path: Path) -> None:
        result = stdf_service.stdf_report(tmp_path / "no.stdf")
        assert result["ok"] is False

    def test_test_detail_envelope(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = stdf_service.stdf_test_detail(p, 100)
        assert result["ok"] is True
        assert result["test_num"] == 100
        assert result["n_points"] == 1
        assert result["points"][0]["meas_val"] == pytest.approx(1.25)

    def test_test_detail_unknown_error(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        result = stdf_service.stdf_test_detail(p, 424242)
        assert result["ok"] is False
        assert "无 PTR 记录" in result["errors"][0]

    def test_service_deterministic(self, tmp_path: Path) -> None:
        p = write_main(tmp_path)
        a = stdf_service.parse_stdf_file(p)
        b = stdf_service.parse_stdf_file(p)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

# ══════════════════════════ CLI 两叶 ══════════════════════════

class TestCli:
    def test_parse_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(stdf_app,
                            ["parse", "--file", str(write_main(tmp_path)),
                             "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["mir_summary"]["lot_id"] == "LOT-A"
        assert envelope["stats"]["n_parts"] == 3

    def test_parse_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(
            stdf_app, ["parse", "--file", str(tmp_path / "no.stdf"),
                       "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_json_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(stdf_app,
                            ["report", "--file", str(write_main(tmp_path)),
                             "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["yield_stats"]["n_parts"] == 3
        assert len(envelope["fail_parts"]) == 1

    def test_report_json_failure_envelope(self, tmp_path: Path) -> None:
        res = runner.invoke(
            stdf_app, ["report", "--file", str(tmp_path / "no.stdf"),
                       "--json"])
        assert res.exit_code == 1
        assert json.loads(res.output)["ok"] is False

    def test_parse_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(stdf_app,
                            ["parse", "--file", str(write_main(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "LOT-A" in res.output
        assert "ptr=5" in res.output

    def test_report_human_output(self, tmp_path: Path) -> None:
        res = runner.invoke(stdf_app,
                            ["report", "--file", str(write_main(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "良率" in res.output
        assert "P2" in res.output

    def test_help_builds_no_bare_percent(self) -> None:
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["parse", "--help"], ["report", "--help"],
                     ["--help"]):
            res = runner.invoke(stdf_app, leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_missing_file_flag_fails(self) -> None:
        res = runner.invoke(stdf_app, ["parse"])
        assert res.exit_code != 0

    def test_cli_leaves_literal_pin(self) -> None:
        # 计数链钉：stdf 域恰 2 叶、每叶带 --json（新叶无 --json 即红）
        source = Path(stdf_service.__file__).parent.parent.joinpath(
            "cli", "domains", "stdf.py").read_text(encoding="utf-8")
        assert source.count('@stdf_app.command("parse")') == 1
        assert source.count('@stdf_app.command("report")') == 1
        assert source.count("json_output: bool = typer.Option") == 2
        assert '--json", "-j"' in source
