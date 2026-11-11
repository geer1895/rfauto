"""STDF V4 二进制结构确定性解析内核（aurora_q 席位 Q-X88，2026-11-08）。

半导体 ATE 产线测试记录事实标准 STDF（Standard Test Data Format，
Teradyne 公开规范 **STDF V4** 口径——2007 增补版官方 PDF 逐节核对 +
pySTDF 开源实现（其记录 docstring 系原版 V4 规范原文）+ 4 份真实 STDF
文件（a595/demofile/lot2/lot3）字节级实证三方互证）的只读**结构子集**
解析：记录级流状态机 + 测试结果两记录面（parametric/functional），
**非全 V4 规范**（TSR/WIR/WRR/WCR/PMR/PGR/PLR/SDR/HBR/SBR/MPR/STR/
GDR/DTR 等已知记录只计数不深解——边界如实声明，见文末）。纯 Python
字节级解析，**零第三方依赖**；结构化数字只出自数据源字节本身（铁律 7）；
服务包装见 :mod:`rfauto.service.stdf_service`（规则 4 JSON 进出），CLI
薄壳见 cli/domains/stdf.py。

格式口径（公开规范，逐条落地；与任务书的两处偏差实测证伪后按公开规范
落地——gdsii_parser Q-X58 先例）：

- **记录头 = 4 字节**：2 字节 REC_LEN（**大端、只数头后载荷字节**，
  公开规范原文 "Bytes of data following header"）+ 1 字节 REC_TYP +
  1 字节 REC_SUB。任务书"REC_LEN 含头 4 字节"系笔误——实证：真实文件
  FAR 记录 REC_LEN=0x0002 而总长 6 字节（含头），若含头则 FAR 载荷
  解析错位；pySTDF/全部开源实现一致按"载荷长度"消费；
- **记录头 REC_LEN 字节序随 CPU_TYPE**（与载荷数据字段同序）：CPU_TYPE
  单字节定位于固定偏移 4（头长恒 4 字节），探测与字节序无关。实证：
  CPU_TYPE=1 文件（lot2/lot3/demofile/a595，FAR 头字节 00 02）头大端
  全流解析到 EOF；CPU_TYPE=2 文件（wafertools/tsmap 四件，FAR 头字节
  02 00）头小端全流解析到 EOF、大端解析 4-89 条即错位——pySTDF 参考
  实现同口径（探测后全流按 CPU_TYPE 字节序消费）；
- **载荷字节序自描述**（任务书口径）：FAR.CPU_TYPE 1=Sun/68000（大端）、
  2=80x86（小端）；**非此二值（含 0=VAX）fail-closed** 抛
  :class:`StdfParseError`（VAX F/D 浮点非 IEEE，本席不猜）；
- **数据类型记法**（公开规范表）：C*n（1B 长度+字节）/B*n（1B 长度+位
  编码 raw）/U*1/U*2/U*4/I*1/I*2/I*4/R*4/R*8——解码器
  :func:`_read_field` 表驱动已知量钉；D*n（2B 位计数+ceil(bits/8) 字节）
  与 N*1 半字节阵列 **raw 记数不展开**（任务书 "G*4/M 交替实数如实登记
  不展开"口径——V4 规范数据类型表无 G*4 类型，MPR 多结果阵列同 raw）；
- 任务书 "PTR MEAS_VAL（R*8 或 G*4 按 flag）"按公开规范落地为：PTR 测量
  值字段规范名 **RESULT，类型 R*4，TEST_FLG bit1=1 时整字段省略**（输出
  键 meas_val 映射规范 RESULT）；V4 规范 PTR 无 G*4 切换、无 TEST_MIN/
  TEST_MAX 字段（TEST_MIN/MAX 属 TSR 记录）——实测 demofile.stdf PTR：
  TEST_NUM U*4 大端 + RESULT R*4 + TEST_TXT C*n，与规范逐字节吻合；
- 任务书 "REC_LEN<4 停流"按载荷语义重释：REC_LEN 数载荷，0 是合法值
  （lot2.stdf 实测 703 条 EPS 记录 REC_LEN=0）——**停流条件=记录头截断
  （余字节 <4）或声明载荷越界（REC_LEN > 剩余字节）**，两条件即任务书
  截断意图的规范正确形态；零进展守卫（#208 家法）在循环内显式断言
  （新偏移 ≤ 旧偏移即停流+warning）。

记录流状态机（任务书口径）：FAR 必居首（非 FAR 领衔→文件级
:class:`StdfParseError`，字节序无从自描述）；深解记录 = FAR（CPU_TYPE/
STDF_VER）/ATR（MOD_TIM+CMD_LINE，可多条）/MIR（37 字段变长链读：8 定
长字段 + 30 个 C*n 串按规范定序串链，载荷耗尽如实置 None，SUPR_NAM 之
后残余字节 raw 跳过+计数——任务书"未知字段序 raw 跳过"）/PCR（part 统
计计数链）/PIR（HEAD+SITE）/PRR（PART_ID+PART_FLG pass/fail 位域）/
PTR（TEST_NUM/TEST_FLG bit7 pass-fail/RESULT/TEST_TXT/UNITS/极限链）/
FTR（TEST_NUM/TEST_TXT/TEST_FLG/NUM_FAIL/RTN·PGM 阵列 raw 跳链/尾串
链）。已知不深解记录（MRR/TSR/WIR/WRR/WCR/PMR/HBR/SBR/SDR/VUR/PSR/
NMR/CNR/SSR/SCR/BPS/EPS/GDR/DTR/MPR/STR）按 REC_LEN 整条跳过+计数；
**未知 (REC_TYP,REC_SUB) 整条跳过+warning 计数**（任务书 fail-soft）。

flag 位域口径出处（官方规范原文，pySTDF V4.py docstring 逐字保留）：
- PTR/FTR TEST_FLG：bit0 alarm / **bit1=1 无 datalog 值（RESULT 语义
  无效）** / bit2 unreliable / bit3 timeout / bit4 not executed /
  bit5 aborted / **bit6=1 无 pass/fail 判定（输出 pass=None 如实）/
  bit7=1 test failed（0=passed）**；
- PRR PART_FLG：bit0/1 supersede（重测标志）/ bit2=1 异常终测 /
  **bit3=1 part failed（0=passed）/ bit4=1 无 pass/fail 判定（bit3 无效）**，
  bits5-7 保留；PART_FLG 原值随 part 落键 part_flg 供消费方；
- PTR OPT_FLAG：bit0=1 RES_SCAL 语义无效 / bit2=1 无低规格限 /
  bit3=1 无高规格限 / bit4 或 bit6=1 低限语义无效 / bit5 或 bit7=1
  高限语义无效 / bit1 保留必须 1；
- FTR OPT_FLAG：bit0=1 CYCL_CNT 无效 / bit1=1 REL_VADR 无效 /
  bit2=1 REPT_CNT 无效 / bit3=1 NUM_FAIL 无效 / bit4=1 XFAIL_AD+
  YFAIL_AD 无效 / bit5=1 VECT_OFF 无效 / bits6-7 保留必须 1；
- **OPT_FLAG/TEST_FLG 位域只作原值注记、不控字段在场**（无条件链读
  +字节余量门控——实证：lot2.stdf PTR#42 bit6=1 仍落 LO_LIMIT=0.0
  占位、coordless 文件 bit2/3=1 仍落 LO_SPEC/HI_SPEC=0.0/0.0，按位域
  跳读与真实文件错位；pySTDF 参考实现同为无条件链读）。
- PTR 可选字段省略规则：规范"任一字段若是记录末字段可省略"+ OPT_FLAG
  位域省略——链读逐字段按剩余字节+flag 判定，载荷耗尽如实置 None
  （fail-soft 宁缺不猜）。

结构化输出（键面单源）::

    {
      "schema_version": PARSER_SCHEMA_VERSION,
      "far": {"cpu_type", "cpu_endian", "stdf_ver"} | None,
      "atr_records": [{"mod_tim", "cmd_line"}, ...],
      "mir_summary": {37 键全链（缺省 None）, "raw_tail_bytes"},
      "pcr_records": [{"head_num", "site_num", "part_cnt", ...}, ...],
      "parts": [{"part_id", "pass", "part_flg_raw", "head_num", "site_num",
                 "num_test", "hard_bin", "soft_bin", "x_coord", "y_coord",
                 "test_t", "part_txt"}, ...],          # PRR 派生，流序
      "parametric_tests": [{"test_num", "test_txt", "meas_val", "pass",
                            "units", "lo_limit", "hi_limit", "head_num",
                            "site_num", "res_scal", "alarm_id"}, ...],
      "functional_tests": [{"test_num", "test_txt", "pass", "num_fail",
                            "cycl_cnt", "rel_vadr", "rept_cnt", "vect_nam",
                            "head_num", "site_num"}, ...],
      "counts": {"n_atr", "n_mir", "n_pcr", "n_pir", "n_prr", "n_ptr",
                 "n_ftr"},                                # 深解面计数
      "stats": {"n_records_total", "per_type_counts", "n_unknown_skipped",
                "n_parts", "n_parts_passed", "n_warnings"},
      "warnings": [str, ...],
      "truncated": bool,      # 流中截断（已收面如实保留）
    }

per_type_counts 键 = ``"{REC_TYP}/{REC_SUB}"``（十进制，规范原生编码）。
查询三函数（输入 = 本模块结构化文档 dict，纯派生零 IO）：

- :func:`stdf_fail_parts`：pass=False 器件清单（流序）；
- :func:`stdf_test_lookup`：按 test_num 的 PTR 测量值序列（流序，
  未知名→空表如实）；
- :func:`stdf_yield`：良率两口径——PCR 优先（HEAD_NUM=255 汇总记录
  优先，否则逐 site PCR 求和；PART_CNT=0 落 PRR 兜底），PRR 统计兜底
  （pass=None 器件计入 n_undecided），零器件 yield_ratio=None 不猜。

确定性（同输入同输出）、零 IO 消费面（bytes 进 dict 出）、零第三方
依赖。本模块不设 ``__all__``（无 __all__ 文件不进 tests/gold/
public_api.json——gdsii_parser 同款先例，新模块零金快照漂移）。

已知边界（如实声明）：多 Site 记录 SDR 不深解；MPR 多结果阵列、GDR/DTR
V*n 变长数据、SDR 站点描述均只计数；PTR/FTR 与 PIR/PRR 的器件归属联接
（HEAD_NUM/SITE_NUM 配对）不构边——parametric_tests/functional_tests
为流序平表，器件归属由 head_num/site_num 原值随行落键供消费方自查；
MIR 链为 V4 已知字段全集（2007 增补未扩 MIR），供应商扩展字节 raw 计数。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

# ── REC_TYP 常量（公开规范 2007 版记录分类表）───────────────────────────────

RT_HEADER = 0        # FAR/ATR/VUR
RT_LOT = 1           # MIR/MRR/PCR/HBR/SBR/PMR/PGR/PLR/RDR/SDR/PSR/...
RT_WAFER = 2         # WIR/WRR/WCR
RT_PART = 5          # PIR/PRR
RT_TEST = 10         # TSR
RT_MEAS = 15         # PTR/MPR/FTR/STR
RT_PROGRAM = 20      # BPS/EPS
RT_GENERIC = 50      # GDR/DTR

#: FAR (File Attributes Record) — 必居首，字节序自描述。
SUB_FAR = 10
SUB_ATR = 20
SUB_VUR = 30
SUB_MIR = 10
SUB_MRR = 20
SUB_PCR = 30
SUB_HBR = 40
SUB_SBR = 50
SUB_PMR = 60
SUB_PGR = 62
SUB_PLR = 63
SUB_RDR = 70
SUB_SDR = 80
SUB_PIR = 10
SUB_PRR = 20
SUB_TSR = 30
SUB_PTR = 10
SUB_MPR = 15
SUB_FTR = 20
SUB_STR = 30
SUB_BPS = 10
SUB_EPS = 20
SUB_GDR = 10
SUB_DTR = 30

#: 已知记录全集（(REC_TYP, REC_SUB) → 名称；不在表内=未知记录，fail-soft
#: 整条跳过+计数）。V4-2007 官方记录分类表全量。
RECORD_NAMES: dict[tuple[int, int], str] = {
    (RT_HEADER, SUB_FAR): "FAR",
    (RT_HEADER, SUB_ATR): "ATR",
    (RT_HEADER, SUB_VUR): "VUR",
    (RT_LOT, SUB_MIR): "MIR",
    (RT_LOT, SUB_MRR): "MRR",
    (RT_LOT, SUB_PCR): "PCR",
    (RT_LOT, SUB_HBR): "HBR",
    (RT_LOT, SUB_SBR): "SBR",
    (RT_LOT, SUB_PMR): "PMR",
    (RT_LOT, SUB_PGR): "PGR",
    (RT_LOT, SUB_PLR): "PLR",
    (RT_LOT, SUB_RDR): "RDR",
    (RT_LOT, SUB_SDR): "SDR",
    (RT_LOT, 90): "PSR",
    (RT_LOT, 91): "NMR",
    (RT_LOT, 92): "CNR",
    (RT_LOT, 93): "SSR",
    (RT_LOT, 94): "SCR",
    (RT_WAFER, 10): "WIR",
    (RT_WAFER, 20): "WRR",
    (RT_WAFER, 30): "WCR",
    (RT_PART, SUB_PIR): "PIR",
    (RT_PART, SUB_PRR): "PRR",
    (RT_TEST, SUB_TSR): "TSR",
    (RT_MEAS, SUB_PTR): "PTR",
    (RT_MEAS, SUB_MPR): "MPR",
    (RT_MEAS, SUB_FTR): "FTR",
    (RT_MEAS, SUB_STR): "STR",
    (RT_PROGRAM, SUB_BPS): "BPS",
    (RT_PROGRAM, SUB_EPS): "EPS",
    (RT_GENERIC, SUB_GDR): "GDR",
    (RT_GENERIC, SUB_DTR): "DTR",
}

#: 深解记录名单（本席契约内的记录；其余已知记录只计数不展开）。
DEEP_DECODED: frozenset[str] = frozenset({
    "FAR", "ATR", "MIR", "PCR", "PIR", "PRR", "PTR", "FTR",
})

#: FAR CPU_TYPE → 载荷字节序（公开规范：1=Sun/68000 大端，2=80x86 小端；
#: 0=PDP-11/VAX 为 F/D 非 IEEE 浮点——fail-closed 不猜）。
CPU_TYPE_ENDIAN: dict[int, str] = {1: "big", 2: "little"}

#: MIR 定序字段链（公开规范 MIR 全 37 字段：8 定长 + 30 个 C*n 变长串；
#: 变长链按此序串读，载荷耗尽如实置 None——尾省略是规范合法形态）。
_MIR_FIXED = (
    ("setup_t", "U4"), ("start_t", "U4"), ("stat_num", "U1"),
    ("mode_cod", "C1"), ("rtst_cod", "C1"), ("prot_cod", "C1"),
    ("burn_tim", "U2"), ("cmod_cod", "C1"),
)
_MIR_STRINGS = (
    "lot_id", "part_typ", "node_nam", "tstr_typ", "job_nam", "job_rev",
    "sblot_id", "oper_nam", "exec_typ", "exec_ver", "test_cod", "tst_temp",
    "user_txt", "aux_file", "pkg_typ", "famly_id", "date_cod", "facil_id",
    "floor_id", "proc_id", "oper_frq", "spec_nam", "spec_ver", "flow_id",
    "setup_id", "dsgn_rev", "eng_id", "rom_cod", "serl_num", "supr_nam",
)

#: PRR 定长前缀字段（PART_FLG 之后到 TEST_T 固定 16 字节；PART_ID/PART_TXT/
#: PART_FIX 为尾链可省略）。
_PRR_FIXED = (
    ("head_num", "U1"), ("site_num", "U1"), ("part_flg", "B1"),
    ("num_test", "U2"), ("hard_bin", "U2"), ("soft_bin", "U2"),
    ("x_coord", "I2"), ("y_coord", "I2"), ("test_t", "U4"),
)

#: PCR 定长字段链（尾省略合法：真实文件常见 10 字节形态=截到 RTST_CNT）。
_PCR_FIELDS = (
    ("head_num", "U1"), ("site_num", "U1"), ("part_cnt", "U4"),
    ("rtst_cnt", "U4"), ("abrt_cnt", "U4"), ("good_cnt", "U4"),
    ("func_cnt", "U4"),
)

#: PCR 汇总记录 HEAD_NUM 约定值（公开规范：255=全 site 汇总）。
PCR_HEAD_SUMMARY = 255

#: PRR PART_FLG 位域（公开规范）。
PART_FLG_FAIL_BIT = 0x08        # bit3: 1=failed, 0=passed
PART_FLG_NO_PF_BIT = 0x10       # bit4: 1=无 pass/fail 判定（bit3 无效）

#: PTR/FTR TEST_FLG 位域（公开规范）。
TEST_FLG_ALARM_BIT = 0x01       # bit0: alarm detected
TEST_FLG_NO_RESULT_BIT = 0x02   # bit1: PTR RESULT 省略（无 datalog 值）
TEST_FLG_UNRELIABLE_BIT = 0x04  # bit2: result unreliable
TEST_FLG_TIMEOUT_BIT = 0x08     # bit3: timeout
TEST_FLG_NOT_EXECUTED_BIT = 0x10  # bit4: test not executed
TEST_FLG_ABORT_BIT = 0x20       # bit5: aborted
TEST_FLG_NO_PF_BIT = 0x40       # bit6: 无 pass/fail 判定（bit7 无效）
TEST_FLG_FAIL_BIT = 0x80        # bit7: 1=failed, 0=passed

#: PTR OPT_FLAG 位域（公开规范；bit1 保留必须 1）。
PTR_OPT_NO_RES_SCAL = 0x01      # bit0: RES_SCAL 省略
PTR_OPT_NO_LO_SPEC = 0x04       # bit2: 无 LO_SPEC
PTR_OPT_NO_HI_SPEC = 0x08       # bit3: 无 HI_SPEC
PTR_OPT_NO_LO_LIMIT = 0x50      # bit4 或 bit6: 无 LLM_SCAL+LO_LIMIT
PTR_OPT_NO_HI_LIMIT = 0xA0      # bit5 或 bit7: 无 HLM_SCAL+HI_LIMIT

#: FTR OPT_FLAG 位域（公开规范；bits6-7 保留必须 1）。
FTR_OPT_NO_CYCL_CNT = 0x01      # bit0
FTR_OPT_NO_REL_VADR = 0x02      # bit1
FTR_OPT_NO_REPT_CNT = 0x04      # bit2
FTR_OPT_NO_NUM_FAIL = 0x08      # bit3
FTR_OPT_NO_FAIL_AD = 0x10       # bit4: XFAIL_AD+YFAIL_AD
FTR_OPT_NO_VECT_OFF = 0x20      # bit5


class StdfParseError(ValueError):
    """STDF 文件级错误（零字节/过短/FAR 缺失/CPU_TYPE fail-closed——
    非流中截断；流中截断走 fail-soft warnings + truncated=True）。"""


# ── fail-soft 告警与单值解码（表驱动）───────────────────────────────────────


def _warn(warnings: list[str], message: str) -> None:
    """同文去重追加（fail-soft 告警逐条披露不改据、不刷屏）。"""
    if message not in warnings:
        warnings.append(message)


#: 定长字段 struct 码表（表驱动已知量钉；载荷字节序由 FAR CPU_TYPE 决定，
#: B1=1 字节位编码 flag 域按无符号字节解）。
_STRUCT_CODES: dict[str, str] = {
    "B1": "B", "U1": "B", "I1": "b", "U2": "H", "I2": "h",
    "U4": "I", "I4": "i", "R4": "f", "R8": "d",
}

#: 已知 REC_TYP 全集（V4-2007 官方记录分类表；不在表内=未知类型）。
_KNOWN_REC_TYPES = frozenset({RT_HEADER, RT_LOT, RT_WAFER, RT_PART,
                              RT_TEST, RT_MEAS, RT_PROGRAM, RT_GENERIC})


def _read_field(
    buf: bytes, off: int, code: str, endian: str, warnings: list[str],
    label: str,
) -> tuple[Any, int]:
    """按 STDF 数据类型码读单字段：返回 (value, new_off)。

    表驱动已知量（公开规范数据类型表）：U1/U2/U4/I1/I2/I4/R4/R8 定长
    struct 解；C1 单字符；C*n 变长串（1B 长度+字节，ascii 替换解码）；
    B*n 位编码 raw（1B 长度+字节）；D*n 位串 raw（2B 位计数+ceil(bits/8)
    字节）。载荷不足 → (None, off) + warning（fail-soft 宁缺不猜）。
    """
    n = len(buf)
    if code in _STRUCT_CODES:
        size = struct.calcsize(_STRUCT_CODES[code])
        if off + size > n:
            _warn(warnings, f"{label} 载荷不足（需 {size} 字节，余 "
                            f"{n - off}），字段如实置 None")
            return None, off
        fmt = "<" if endian == "little" else ">"
        (val,) = struct.unpack_from(fmt + _STRUCT_CODES[code], buf, off)
        return val, off + size
    if code == "C1":
        if off + 1 > n:
            _warn(warnings, f"{label} 载荷不足（需 1 字节），字段如实置 None")
            return None, off
        return buf[off:off + 1].decode("ascii", errors="replace"), off + 1
    if code in ("Cn", "Bn"):
        if off + 1 > n:
            _warn(warnings, f"{label} 长度字节缺失，字段如实置 None")
            return None, off
        ln = buf[off]
        end = off + 1 + ln
        if end > n:
            _warn(warnings, f"{label} 声明长度 {ln} 超出剩余 {n - off - 1} "
                            "字节，字段如实置 None")
            return None, off
        if code == "Cn":
            return buf[off + 1:end].decode("ascii", errors="replace"), end
        return bytes(buf[off + 1:end]), end
    if code == "Dn":
        if off + 2 > n:
            _warn(warnings, f"{label} 位计数字段缺失，字段如实置 None")
            return None, off
        (nbits,) = struct.unpack_from(">H", buf, off)
        size = (nbits + 7) // 8
        end = off + 2 + size
        if end > n:
            _warn(warnings, f"{label} 位串声明 {nbits} 位（{size} 字节）"
                            f"超出剩余 {n - off - 2} 字节，字段如实置 None")
            return None, off
        return {"n_bits": nbits, "raw": bytes(buf[off + 2:end])}, end
    _warn(warnings, f"{label} 未知数据类型码 {code!r}，字段如实置 None")
    return None, off


def _test_pass(test_flg: int | None) -> bool | None:
    """PTR/FTR TEST_FLG → pass 三态：bit6=1 无判定 → None；否则
    bit7=0 → True（passed）、bit7=1 → False（failed）。缺 flag → None。"""
    if test_flg is None:
        return None
    if test_flg & TEST_FLG_NO_PF_BIT:
        return None
    return not bool(test_flg & TEST_FLG_FAIL_BIT)


def _part_pass(part_flg: int | None) -> bool | None:
    """PRR PART_FLG → pass 三态：bit4=1 无判定（bit3 无效）→ None；
    否则 bit3=0 → True（passed）、bit3=1 → False（failed）。"""
    if part_flg is None:
        return None
    if part_flg & PART_FLG_NO_PF_BIT:
        return None
    return not bool(part_flg & PART_FLG_FAIL_BIT)


# ── 深解记录链读器（逐字段剩余字节+flag 判定，尾省略合法）───────────────────


def _read_fixed_chain(
    buf: bytes, off: int, fields: tuple[tuple[str, str], ...], endian: str,
    warnings: list[str], label: str,
) -> tuple[dict[str, Any], int]:
    """定长字段链（载荷耗尽即停，缺字段如实 None——尾省略合法形态）。"""
    out: dict[str, Any] = {}
    for name, code in fields:
        if off >= len(buf):
            _warn(warnings, f"{label} 载荷耗尽，{name} 如实置 None")
            out[name] = None
            continue
        out[name], off = _read_field(buf, off, code, endian, warnings,
                                     f"{label}.{name}")
    return out, off


def _parse_far(payload: bytes, warnings: list[str]) -> dict[str, Any]:
    """FAR：CPU_TYPE/STDF_VER；CPU_TYPE 非 1/2 → fail-closed。"""
    out: dict[str, Any] = {"cpu_type": None, "cpu_endian": None,
                           "stdf_ver": None}
    if len(payload) < 1:
        raise StdfParseError("FAR 载荷无 CPU_TYPE 字节，字节序无从自描述")
    cpu_type = payload[0]
    if cpu_type not in CPU_TYPE_ENDIAN:
        raise StdfParseError(
            f"FAR CPU_TYPE={cpu_type} 非 1（大端）/2（小端），本席 fail-closed"
            "（VAX F/D 浮点非 IEEE 不猜）")
    out["cpu_type"] = cpu_type
    out["cpu_endian"] = CPU_TYPE_ENDIAN[cpu_type]
    if len(payload) >= 2:
        out["stdf_ver"] = payload[1]
        if out["stdf_ver"] != 4:
            _warn(warnings, f"FAR STDF_VER={out['stdf_ver']} 非 4（本席"
                            "V4 结构子集口径），解析继续如实登记")
    else:
        _warn(warnings, "FAR 载荷缺 STDF_VER 字节，如实置 None")
    return out


def _parse_atr(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """ATR：MOD_TIM U*4 + CMD_LINE C*n（可多条，逐条落 atr_records）。"""
    out: dict[str, Any] = {"mod_tim": None, "cmd_line": None}
    out["mod_tim"], off = _read_field(payload, 0, "U4", endian, warnings,
                                      "ATR.mod_tim")
    if off < len(payload):
        out["cmd_line"], _ = _read_field(payload, off, "Cn", endian,
                                         warnings, "ATR.cmd_line")
    return out


def _parse_mir(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """MIR：8 定长 + 30 个 C*n 定序串链；链尾残余字节 raw 跳过+计数
    （任务书"未知字段序 raw 跳过"；尾省略=载荷耗尽字段如实 None）。"""
    out: dict[str, Any] = {}
    out["raw_tail_bytes"] = 0
    off = 0
    for name, code in _MIR_FIXED:
        if off >= len(payload):
            _warn(warnings, f"MIR 载荷耗尽，{name} 如实置 None")
            out[name] = None
            continue
        out[name], off = _read_field(payload, off, code, endian, warnings,
                                     f"MIR.{name}")
    for name in _MIR_STRINGS:
        if off >= len(payload):
            out[name] = None
            continue
        out[name], off = _read_field(payload, off, "Cn", endian, warnings,
                                     f"MIR.{name}")
    if off < len(payload):
        out["raw_tail_bytes"] = len(payload) - off
        _warn(warnings, f"MIR 载荷尾部 {out['raw_tail_bytes']} 字节超出 V4 "
                        "已知字段链（供应商扩展），raw 跳过")
    return out


def _parse_pir(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """PIR：HEAD_NUM + SITE_NUM（2 字节定长）。"""
    out: dict[str, Any] = {"head_num": None, "site_num": None}
    out["head_num"], off = _read_field(payload, 0, "U1", endian, warnings,
                                       "PIR.head_num")
    if off < len(payload):
        out["site_num"], _ = _read_field(payload, off, "U1", endian,
                                         warnings, "PIR.site_num")
    return out


def _parse_prr(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """PRR：定长前缀链 + PART_ID/PART_TXT/PART_FIX 尾链；pass 三态
    按 PART_FLG bit4（无判定→None）/bit3（1=failed）。"""
    out, off = _read_fixed_chain(payload, 0, _PRR_FIXED, endian, warnings,
                                 "PRR")
    part_flg = out.get("part_flg")
    out["pass"] = _part_pass(part_flg)
    out["part_id"] = None
    out["part_txt"] = None
    if off < len(payload):
        out["part_id"], off = _read_field(payload, off, "Cn", endian,
                                          warnings, "PRR.part_id")
    if off < len(payload):
        out["part_txt"], off = _read_field(payload, off, "Cn", endian,
                                           warnings, "PRR.part_txt")
    if off < len(payload):
        out["part_fix"], off = _read_field(payload, off, "Bn", endian,
                                           warnings, "PRR.part_fix")
    else:
        out["part_fix"] = None
    return out


def _parse_pcr(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """PCR：7 字段定长链（真实文件常见尾省略形态——lot2.stdf PCR 载荷
    10 字节截到 RTST_CNT）。"""
    out, _off = _read_fixed_chain(payload, 0, _PCR_FIELDS, endian, warnings,
                                  "PCR")
    return out


def _parse_ptr(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """PTR（Parametric Test Record，REC_TYP=15/REC_SUB=10）：

    链序（公开规范定序，pySTDF 参考实现 + 4 真实文件 109,001 条 PTR
    逐字节实证）：TEST_NUM U*4 → HEAD_NUM U*1 → SITE_NUM U*1 →
    TEST_FLG B*1 → PARM_FLG B*1 → **RESULT R*4（输出键 meas_val）** →
    TEST_TXT C*n → ALARM_ID C*n → OPT_FLAG B*1 → RES_SCAL I*1 →
    LLM_SCAL I*1 → HLM_SCAL I*1 → LO_LIMIT R*4 → HI_LIMIT R*4 →
    UNITS C*n → C_RESFMT/C_LLMFMT/C_HLMFMT C*n → LO_SPEC R*4 →
    HI_SPEC R*4——**三个 scale 字节连排在前、两个 limit 随后**
    （demofile PTR#1 实证：RES/LLM/HLM=0,0,0 连排后 LO_LIMIT
    bf666666=-0.9、HI_LIMIT becccccd=-0.4、UNITS='v'，与 pySTDF 参考
    解析逐字段一致）。

    **字段在场策略=无条件顺序链读、逐字段字节余量门控**（载荷耗尽
    如实置 None——尾省略合法）：TEST_FLG/OPT_FLAG 各位域（省略/无效
    语义见模块 docstring 常量注记）**只作原值注记不控字段在场**——
    实证：lot2.stdf PTR#42 OPT_FLAG bit6=1（"无低限"）而写入方仍落
    LO_LIMIT=0.0 占位、coordless 文件 bit2/3=1 仍落 LO_SPEC/HI_SPEC
    =0.0/0.0；若按位域跳读将与真实文件错位（pySTDF 参考实现同为无
    条件链读、EndOfRecord 门控）。记录尾真省略形态由字节门控天然覆
    盖（demofile PTR#1 在 OPT_FLAG bit2/3=1 时 C_HLMFMT 后即记录尾，
    LO_SPEC/HI_SPEC 缺席= None）。

    pass 三态：TEST_FLG bit6=1 无判定 → None；否则 bit7=0 → True
    （passed）/1 → False（failed）。meas_val 有效性：TEST_FLG bit1=1
    表示无 datalog 值（原值注记，消费方按规范判读，本席不替代业务
    判据）。
    """
    out: dict[str, Any] = {
        "test_num": None, "head_num": None, "site_num": None,
        "test_flg_raw": None, "parm_flg_raw": None, "opt_flag_raw": None,
        "meas_val": None, "test_txt": None, "alarm_id": None,
        "res_scal": None, "llm_scal": None, "hlm_scal": None,
        "lo_limit": None, "hi_limit": None, "units": None,
        "c_resfmt": None, "c_llmfmt": None, "c_hlmfmt": None,
        "lo_spec": None, "hi_spec": None,
    }
    out["pass"] = None
    off = 0
    out["test_num"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "PTR.test_num")
    out["head_num"], off = _read_field(payload, off, "U1", endian, warnings,
                                       "PTR.head_num")
    out["site_num"], off = _read_field(payload, off, "U1", endian, warnings,
                                       "PTR.site_num")
    test_flg, off = _read_field(payload, off, "B1", endian, warnings,
                                "PTR.test_flg")
    out["test_flg_raw"] = test_flg
    out["pass"] = _test_pass(test_flg)
    parm_flg, off = _read_field(payload, off, "B1", endian, warnings,
                                "PTR.parm_flg")
    out["parm_flg_raw"] = parm_flg
    # RESULT：无条件链读（TEST_FLG bit1 只作原值注记——见 docstring
    # 在场策略节；位域跳读与真实文件错位实证）。
    if off < len(payload):
        out["meas_val"], off = _read_field(payload, off, "R4", endian,
                                           warnings, "PTR.result")
    if off >= len(payload):
        return out
    out["test_txt"], off = _read_field(payload, off, "Cn", endian, warnings,
                                       "PTR.test_txt")
    if off >= len(payload):
        return out
    out["alarm_id"], off = _read_field(payload, off, "Cn", endian, warnings,
                                       "PTR.alarm_id")
    if off >= len(payload):
        return out
    opt_flag, off = _read_field(payload, off, "B1", endian, warnings,
                                "PTR.opt_flag")
    out["opt_flag_raw"] = opt_flag
    if opt_flag is None or off >= len(payload):
        return out
    # 三个 scale 字节连排（RES/LLM/HLM），随后两个 limit R*4——公开规范
    # 定序；OPT_FLAG 位域不控在场（无条件链读，字节余量门控）。
    out["res_scal"], off = _read_field(payload, off, "I1", endian, warnings,
                                       "PTR.res_scal")
    out["llm_scal"], off = _read_field(payload, off, "I1", endian, warnings,
                                       "PTR.llm_scal")
    out["hlm_scal"], off = _read_field(payload, off, "I1", endian, warnings,
                                       "PTR.hlm_scal")
    out["lo_limit"], off = _read_field(payload, off, "R4", endian, warnings,
                                       "PTR.lo_limit")
    out["hi_limit"], off = _read_field(payload, off, "R4", endian, warnings,
                                       "PTR.hi_limit")
    if off >= len(payload):
        return out
    out["units"], off = _read_field(payload, off, "Cn", endian, warnings,
                                    "PTR.units")
    for key in ("c_resfmt", "c_llmfmt", "c_hlmfmt"):
        if off >= len(payload):
            return out
        out[key], off = _read_field(payload, off, "Cn", endian, warnings,
                                    f"PTR.{key}")
    if off < len(payload):
        out["lo_spec"], off = _read_field(payload, off, "R4", endian,
                                          warnings, "PTR.lo_spec")
    if off < len(payload):
        out["hi_spec"], off = _read_field(payload, off, "R4", endian,
                                          warnings, "PTR.hi_spec")
    return out


def _parse_ftr(payload: bytes, endian: str,
               warnings: list[str]) -> dict[str, Any]:
    """FTR（Functional Test Record，REC_TYP=15/REC_SUB=20）：

    链序（公开规范定序）：TEST_NUM U*4 → HEAD_NUM → SITE_NUM →
    TEST_FLG → OPT_FLAG → CYCL_CNT/REL_VADR/REPT_CNT/NUM_FAIL（U*4 ×4）
    → XFAIL_AD/YFAIL_AD（I*4 ×2）→ VECT_OFF（I*2）→ RTN_ICNT/PGM_ICNT
    （U*2 ×2）→ RTN_INDX/RTN_STAT/PGM_INDX/PGM_STAT（计数控阵列，
    N*1 半字节——**raw 跳过不展开**）→ FAIL_PIN（D*n 位串 raw）→
    VECT_NAM/TIME_SET/OP_CODE/TEST_TXT/ALARM_ID/PROG_TXT/RSLT_TXT
    （C*n 尾链）→ PATG_NUM U*1 → SPIN_MAP D*n raw。

    **字段在场策略=无条件顺序链读、逐字段字节余量门控**（与 PTR 同一
    实证口径：OPT_FLAG 位域只作原值注记不控在场；a595.stdf 75 条 FTR
    无条件链读逐字节恰尽）。pass 三态同 PTR（TEST_FLG bit6/bit7）。
    """
    out: dict[str, Any] = {
        "test_num": None, "head_num": None, "site_num": None,
        "test_flg_raw": None, "opt_flag_raw": None,
        "cycl_cnt": None, "rel_vadr": None, "rept_cnt": None,
        "num_fail": None, "xfail_ad": None, "yfail_ad": None,
        "vect_off": None, "rtn_icnt": None, "pgm_icnt": None,
        "vect_nam": None, "time_set": None, "op_code": None,
        "test_txt": None, "alarm_id": None, "prog_txt": None,
        "rslt_txt": None, "patg_num": None,
    }
    out["pass"] = None
    off = 0
    out["test_num"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "FTR.test_num")
    out["head_num"], off = _read_field(payload, off, "U1", endian, warnings,
                                       "FTR.head_num")
    out["site_num"], off = _read_field(payload, off, "U1", endian, warnings,
                                       "FTR.site_num")
    test_flg, off = _read_field(payload, off, "B1", endian, warnings,
                                "FTR.test_flg")
    out["test_flg_raw"] = test_flg
    out["pass"] = _test_pass(test_flg)
    if off >= len(payload):
        return out
    opt_flag, off = _read_field(payload, off, "B1", endian, warnings,
                                "FTR.opt_flag")
    out["opt_flag_raw"] = opt_flag
    if off >= len(payload):
        return out
    out["cycl_cnt"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "FTR.cycl_cnt")
    out["rel_vadr"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "FTR.rel_vadr")
    out["rept_cnt"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "FTR.rept_cnt")
    out["num_fail"], off = _read_field(payload, off, "U4", endian, warnings,
                                       "FTR.num_fail")
    out["xfail_ad"], off = _read_field(payload, off, "I4", endian, warnings,
                                       "FTR.xfail_ad")
    out["yfail_ad"], off = _read_field(payload, off, "I4", endian, warnings,
                                       "FTR.yfail_ad")
    out["vect_off"], off = _read_field(payload, off, "I2", endian, warnings,
                                       "FTR.vect_off")
    if off >= len(payload):
        return out
    out["rtn_icnt"], off = _read_field(payload, off, "U2", endian, warnings,
                                       "FTR.rtn_icnt")
    out["pgm_icnt"], off = _read_field(payload, off, "U2", endian, warnings,
                                       "FTR.pgm_icnt")
    # 计数控阵列：RTN_INDX/PGM_INDX（U*2 数组）与 RTN_STAT/PGM_STAT
    # （N*1 半字节）raw 跳过不展开——计数原值落 rtn_icnt/pgm_icnt。
    for cnt_key, elem_size, label in (
        ("rtn_icnt", 2, "FTR.rtn_indx"),
        ("pgm_icnt", 2, "FTR.pgm_indx"),
    ):
        cnt = out.get(cnt_key)
        if cnt is None:
            _warn(warnings, f"{label} 计数控缺失，阵列 raw 跳过")
            continue
        need = cnt * elem_size
        if off + need > len(payload):
            _warn(warnings, f"{label} 声明 {need} 字节超出剩余 "
                            f"{len(payload) - off}，阵列 raw 跳过")
            return out
        off += need
    for cnt_key, label in (("rtn_icnt", "FTR.rtn_stat"),
                           ("pgm_icnt", "FTR.pgm_stat")):
        cnt = out.get(cnt_key)
        if cnt is None:
            continue
        need = (cnt + 1) // 2  # N*1 半字节阵列
        if off + need > len(payload):
            _warn(warnings, f"{label} 声明 {need} 字节超出剩余 "
                            f"{len(payload) - off}，阵列 raw 跳过")
            return out
        off += need
    if off < len(payload):
        _, off = _read_field(payload, off, "Dn", endian, warnings,
                             "FTR.fail_pin")
    for key in ("vect_nam", "time_set", "op_code", "test_txt", "alarm_id",
                "prog_txt", "rslt_txt"):
        if off >= len(payload):
            return out
        out[key], off = _read_field(payload, off, "Cn", endian, warnings,
                                    f"FTR.{key}")
    if off < len(payload):
        out["patg_num"], off = _read_field(payload, off, "U1", endian,
                                           warnings, "FTR.patg_num")
    if off < len(payload):
        _read_field(payload, off, "Dn", endian, warnings, "FTR.spin_map")
    return out


# ── 记录流状态机 ────────────────────────────────────────────────────────────


def parse_stdf_bytes(data: bytes) -> dict[str, Any]:
    """STDF 字节流 → 结构化文档（确定性、零 IO、fail-soft warnings）。

    见模块 docstring 全键面。零字节/过短/FAR 缺失或非 1/2 CPU_TYPE →
    :class:`StdfParseError`（文件级错误，服务层分型 ok=False）；流中
    截断/未知记录/链读缺陷 → warning + 已收面如实保留 + truncated=True。
    """
    warnings: list[str] = []
    doc: dict[str, Any] = {
        "schema_version": PARSER_SCHEMA_VERSION,
        "far": None,
        "atr_records": [],
        "mir_summary": None,
        "pcr_records": [],
        "parts": [],
        "parametric_tests": [],
        "functional_tests": [],
        "counts": {},
        "stats": {},
        "warnings": warnings,
        "truncated": False,
    }
    n = len(data)
    if n == 0:
        raise StdfParseError("空文件：零字节非 STDF")
    if n < 4:
        raise StdfParseError(
            f"文件过短（{n} 字节 < 最小记录头 4 字节），非 STDF")
    if data[2] != RT_HEADER or data[3] != SUB_FAR:
        raise StdfParseError(
            "首记录非 FAR（REC_TYP=0/REC_SUB=10），STDF 载荷字节序"
            "无从自描述，本席 fail-closed")
    if n < 5:
        raise StdfParseError("FAR 载荷无 CPU_TYPE 字节，字节序无从自描述")
    cpu_type = data[4]
    if cpu_type not in CPU_TYPE_ENDIAN:
        raise StdfParseError(
            f"FAR CPU_TYPE={cpu_type} 非 1（大端）/2（小端），本席 fail-closed"
            "（VAX F/D 浮点非 IEEE 不猜）")
    # 记录头 REC_LEN 字节序随 CPU_TYPE（1=大端 2=小端）——CPU_TYPE=2
    # 真实文件（wafertools/tsmap 四件，FAR 头字节 02 00）实证小端全流
    # 解析到 EOF、大端 4-89 条即错位；CPU_TYPE 本身是单字节、定位于
    # 固定偏移 4（头长恒 4 字节），探测与字节序无关。
    endian = CPU_TYPE_ENDIAN[cpu_type]
    far_len = int.from_bytes(data[:2], endian)
    if far_len < 1:
        raise StdfParseError(
            "FAR REC_LEN=0（无 CPU_TYPE 载荷），字节序无从自描述，"
            "本席 fail-closed")
    doc["far"] = _parse_far(data[4:4 + far_len], warnings)

    pos = 0
    n_records = 0
    n_unknown = 0
    per_type: dict[str, int] = {}
    counts = {"n_atr": 0, "n_mir": 0, "n_pcr": 0, "n_pir": 0,
              "n_prr": 0, "n_ptr": 0, "n_ftr": 0}
    truncated = False
    saw_far = False

    while pos < n:
        if pos + 4 > n:
            _warn(warnings, f"记录头截断（偏移 {pos}，余 {n - pos} 字节 "
                            "< 4），流停止")
            truncated = True
            break
        old_pos = pos
        # 记录头 REC_LEN 随 CPU_TYPE 字节序（见上文探测节）。
        rec_len = int.from_bytes(data[pos:pos + 2], endian)
        rec_typ = data[pos + 2]
        rec_sub = data[pos + 3]
        end = pos + 4 + rec_len
        if end > n:
            _warn(warnings,
                  f"记录声明载荷 {rec_len} 字节超出剩余 {n - pos - 4} 字节"
                  f"（偏移 {pos}，类型 {rec_typ}/{rec_sub}），流停止（截断）")
            truncated = True
            break
        payload = data[pos + 4:end]
        pos = end
        n_records += 1
        if pos <= old_pos:
            # 零进展守卫（#208 家法）：4+REC_LEN ≥ 4 恒应成立，显式断言
            # 防偏移回跳死循环（Q-X80 词法/坐标教训同型）。
            _warn(warnings, f"记录 {rec_typ}/{rec_sub} 偏移未推进，流停止")
            truncated = True
            break

        if (rec_typ, rec_sub) == (RT_HEADER, SUB_FAR):
            if not saw_far:
                saw_far = True  # FAR 已在探测节解析入 doc（首记录契约）
                continue
            _warn(warnings, "流中重复 FAR 记录（规范：FAR 必居首），跳过")
            continue
        if rec_typ not in _KNOWN_REC_TYPES:
            n_unknown += 1
            key = f"{rec_typ}/{rec_sub}"
            _warn(warnings,
                  f"未知记录 {key}（负载 {len(payload)} 字节），整条跳过")
            continue
        per_type[f"{rec_typ}/{rec_sub}"] = \
            per_type.get(f"{rec_typ}/{rec_sub}", 0) + 1

        kind = RECORD_NAMES.get((rec_typ, rec_sub))
        if kind is None:
            n_unknown += 1
            key = f"{rec_typ}/{rec_sub}"
            _warn(warnings,
                  f"未知子类型 {key}（负载 {len(payload)} 字节），整条跳过")
            continue
        if kind == "ATR":
            counts["n_atr"] += 1
            doc["atr_records"].append(_parse_atr(payload, endian, warnings))
        elif kind == "MIR":
            counts["n_mir"] += 1
            doc["mir_summary"] = _parse_mir(payload, endian, warnings)
        elif kind == "PCR":
            counts["n_pcr"] += 1
            doc["pcr_records"].append(_parse_pcr(payload, endian, warnings))
        elif kind == "PIR":
            counts["n_pir"] += 1
        elif kind == "PRR":
            counts["n_prr"] += 1
            doc["parts"].append(_parse_prr(payload, endian, warnings))
        elif kind == "PTR":
            counts["n_ptr"] += 1
            doc["parametric_tests"].append(
                _parse_ptr(payload, endian, warnings))
        elif kind == "FTR":
            counts["n_ftr"] += 1
            doc["functional_tests"].append(
                _parse_ftr(payload, endian, warnings))
        # 其余已知记录（MRR/TSR/WIR/WRR/WCR/PMR/HBR/SBR/SDR/VUR/PSR/
        # NMR/CNR/SSR/SCR/BPS/EPS/GDR/DTR/MPR/STR）：按 REC_LEN 整条
        # 跳过（per_type_counts 已计数，结构子集边界如实声明）。

    if n_records == 0 or doc["far"] is None:
        raise StdfParseError(
            f"非 STDF 文件：流首即不可读或 FAR 缺失（文件 {n} 字节，"
            f"可读记录 {n_records} 条）")
    if truncated:
        doc["truncated"] = True

    parts = doc["parts"]
    doc["counts"] = counts
    doc["stats"] = {
        "n_records_total": n_records,
        "per_type_counts": per_type,
        "n_unknown_skipped": n_unknown,
        "n_parts": len(parts),
        "n_parts_passed": sum(1 for p in parts if p.get("pass") is True),
        "n_warnings": len(warnings),
    }
    return doc


def parse_stdf_file(path: str | Path) -> dict[str, Any]:
    """读文件字节并解析（OSError 原样上抛由服务层分型；解析语义同
    :func:`parse_stdf_bytes`）。"""
    data = Path(path).read_bytes()
    return parse_stdf_bytes(data)


# ── 查询三函数（纯派生，零 IO）──────────────────────────────────────────────


def stdf_fail_parts(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """pass=False 器件清单（PRR 派生 parts 流序子集，pass=None 不入——
    未判定≠失败，如实口径）。"""
    return [p for p in (doc.get("parts") or []) if p.get("pass") is False]


def stdf_test_lookup(doc: dict[str, Any], test_num: int) -> list[dict[str, Any]]:
    """按 test_num 的 PTR 测量值序列（parametric_tests 流序过滤）。

    每点键面：meas_val/pass/units/lo_limit/hi_limit/head_num/site_num；
    未知名（无该 test_num 的 PTR）→ 空表如实（不猜不抛）。
    """
    return [
        {
            "meas_val": t.get("meas_val"),
            "pass": t.get("pass"),
            "units": t.get("units"),
            "lo_limit": t.get("lo_limit"),
            "hi_limit": t.get("hi_limit"),
            "head_num": t.get("head_num"),
            "site_num": t.get("site_num"),
        }
        for t in (doc.get("parametric_tests") or [])
        if t.get("test_num") == test_num
    ]


def stdf_yield(doc: dict[str, Any]) -> dict[str, Any]:
    """良率两口径（任务书：PCR 优先 PRR 统计兜底；零器件 None 不猜）。

    - PCR 优先：HEAD_NUM=255 汇总记录（公开规范约定）优先；无汇总则逐
      site PCR 求和。**PCR 可用判据 = PART_CNT>0 且 GOOD_CNT 在场**
      （真实文件常见 PCR 尾省略截到 RTST_CNT——lot2.stdf PCR 载荷 10
      字节无 GOOD_CNT，此时按 None 当 0 计会伪造 yield=0，必须落 PRR
      兜底）；PART_CNT=0 或 GOOD_CNT 缺失 → PRR 兜底；
    - PRR 兜底：parts 全量计数、pass=True 计数；pass=None 器件计入
      n_undecided（未判定不计通过，也不冒充失败）；
    - 零器件（无 PCR 且无 PRR）：yield_ratio=None 如实不猜。
    """
    pcrs = doc.get("pcr_records") or []
    parts = doc.get("parts") or []
    if pcrs:
        summary = next((p for p in pcrs
                        if p.get("head_num") == PCR_HEAD_SUMMARY), None)
        if summary is not None:
            n_total = summary.get("part_cnt") or 0
            n_good = summary.get("good_cnt")
            source = "pcr_summary"
        else:
            n_total = sum(p.get("part_cnt") or 0 for p in pcrs)
            n_good = None
            if all(p.get("good_cnt") is not None for p in pcrs):
                n_good = sum(p.get("good_cnt") or 0 for p in pcrs)
            source = "pcr_sites"
        if n_total > 0 and n_good is not None:
            return {
                "source": source,
                "n_parts": n_total,
                "n_passed": n_good,
                "n_undecided": 0,
                "yield_ratio": n_good / n_total,
            }
    if parts:
        n_passed = sum(1 for p in parts if p.get("pass") is True)
        n_undecided = sum(1 for p in parts if p.get("pass") is None)
        return {
            "source": "prr",
            "n_parts": len(parts),
            "n_passed": n_passed,
            "n_undecided": n_undecided,
            "yield_ratio": n_passed / len(parts),
        }
    return {
        "source": None,
        "n_parts": 0,
        "n_passed": 0,
        "n_undecided": 0,
        "yield_ratio": None,
    }
