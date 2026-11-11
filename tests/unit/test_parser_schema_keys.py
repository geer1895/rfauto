"""R-22（aurora_r 扩展池批）——core parser 集群自描述键统一升位钉。

背景（runs/aurora_q/qx74_audit/FINAL_AUDIT.md P2-1/P2-2）：19 个 core
parser 的输出自描述键三代漂移——``"schema":"域/1.0"``（5 件）/
``"schema_version":"1.0"``（7 件）/无自描述键（7 件）；stats 缺
``n_warnings`` 键 6 件。本批统一：

统一口径定案：**自描述键 = ``"schema"``，值 = ``"<域>/<N.0>"`` 复合串**
（版本起步一律 "1.0"——core 面全部 PARSER_SCHEMA_VERSION 常量（含
audit 后新代 bsdl/spectre/stdf/veriloga）均为 "1.0"，无 >1.0 先例，
无递进需求）。裁定理由（三代择形依据）：

1. 消费面实据：``core/netlist_semantic_overlay.py`` 按
   ``doc["schema"]`` 前缀分派（``spice_netlist/*``/``spectre_netlist/*``
   → 规则族，其他 schema 显式 ValueError）并把 ``doc["schema"]`` 嵌入
   ``parser_schema`` 溯源键——复合键是唯一能承载域身份的形态；裸
   ``"schema_version"`` 键在 19 parser 产物上全仓 grep（#315 家法）：
   **恰 1 处代码读点**——``service/lvs_compare_service.py``
   ``_normalize_verilog_graph_generic`` 的 detail 溯源串读 verilog 旧键
   （首派接力批 grep 漏检，重派席复核抓出），另 4 处仓内测试断言
   （gdsii/lef_def/odbpp×2）随本批同笔更新。
2. 方向性：audit 后新代（bsdl/spectre）与 R-02 诊断层
   （``parse_diagnostic/<N.0>``）均采复合形态；service 面
   spice/sdf/skill 信封已透传/构造复合键——复合键是集群演进方向。
3. 自描述语义完整性：裸版本键无域身份，跨域消费时不可辨识。

键落位规则：parser 产物为 dict 文档 → 键在 core 文档顶层；产物为
组树/包列表（liberty/citi/ibis/skill）→ 键由 service 主解析信封携带
（skill_service 先例，``"schema"`` 信封键=附加键不改既有键语义）。

n_warnings（P2-2）：warnings 列表已在其面者补计数字段（附加键零破
坏）——spice(summary)/citi(metadata)/touchstone(stats 新建单键)/
skill_definitions(stats)/ibis(service stats)。**liberty 如实登记
N/A**：全文 fail-closed 无 warnings 面（P2-3 同源，docstring 明示
"未识别组/属性一律 attrs 透传+错误抛"）——count-of-nothing 属伪造
统计面，不补。

改名安全性：``schema_version``→``schema`` 为键名变更，grep 全仓按件
清点（#315 家法）：verilog 旧键有 1 处仓内消费者（lvs_compare_service
detail 串）→ **双层兼容**（新旧键并存一版，旧键 deprecated 注记，
下一升位批移除——避免破坏他席 Q-X49 面；单列报告项）；其余 6 件
（gdsii/gerber/excellon/ipc356/lef_def/odbpp）旧键零代码读点 → 单键
直改；4 处仓内测试断言随本批同笔更新。

本文件 = 键形统一钉单源（19 件参数化全表）+n_warnings 补键钉（5 件
参数化）。禁改面未触碰：spef/vcd 的 R-02 diagnostics 键面（叠加不冲
突）、cli/、mcp_tools/、mcp_server*、docs_site/、tests 锚与 gold。
"""

from __future__ import annotations

import struct
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.drc_parser import parse_drc_rules
from rfauto.core.excellon_parser import parse_excellon
from rfauto.core.gdsii_parser import parse_gdsii_bytes
from rfauto.core.gerber_parser import parse_gerber
from rfauto.core.ipc356_parser import parse_ipc356
from rfauto.core.lef_def_parser import parse_def, parse_lef
from rfauto.core.odbpp_parser import parse_odb_matrix
from rfauto.core.sdc_parser import parse_sdc
from rfauto.core.sdf_parser import parse_sdf
from rfauto.core.skill_parser import parse_skill, skill_definitions
from rfauto.core.spef_parser import parse_spef
from rfauto.core.spice_netlist_parser import parse_spice_netlist_text
from rfauto.core.stil_parser import parse_stil
from rfauto.core.touchstone_parser import parse_touchstone
from rfauto.core.vcd_parser import parse_vcd
from rfauto.core.verilog_netlist_parser import parse_verilog
from rfauto.service import (
    citi_service,
    ibis_service,
    liberty_service,
    skill_service,
)

TESTS_DIR = Path(__file__).resolve().parent
LIBERTY_FIXTURE = TESTS_DIR.parent / "fixtures" / "liberty" / "sample.lib"
CITI_FIXTURE = TESTS_DIR / "fixtures" / "citi" / "sample_citi.cti"
IBIS_FIXTURE = TESTS_DIR / "fixtures" / "ibis" / "sample.ibs"


# ════════════════ 统一断言 helper（单源） ════════════════

def check_schema(doc: Mapping[str, Any], domain: str, *,
                 version: str = "1.0",
                 legacy_compat: bool = False) -> None:
    """键形统一钉（单源）：自描述键=``"schema"``，值=``"<域>/<N.0>"``。

    同时钉旧键归零：``"schema_version"`` 不得残留（三代漂移复发哨兵
    ——树形域的信封无此键、dict 域改键后不得回潮）。唯一例外=
    ``legacy_compat``（verilog_netlist：旧键有仓内消费者
    lvs_compare_service，双层兼容并存一版、值恒等于版本常量）。
    """
    if legacy_compat:
        assert doc["schema_version"] == version, (
            f"{domain}: 双层兼容旧键值漂移 "
            f"{doc['schema_version']!r} != {version!r}")
    else:
        assert "schema_version" not in doc, (
            f"{domain}: 旧代际 schema_version 键残留（三代漂移复发）")
    assert doc["schema"] == f"{domain}/{version}", (
        f"{domain}: doc['schema']={doc['schema']!r} != "
        f"{domain}/{version!r}")


def check_n_warnings(doc: Mapping[str, Any], face: Mapping[str, Any],
                     warnings: Any, domain: str) -> None:
    """n_warnings 补键钉（单源）：计数 == 同 doc warnings 列表长度。"""
    assert isinstance(warnings, list), f"{domain}: warnings 非列表"
    assert face["n_warnings"] == len(warnings), (
        f"{domain}: n_warnings={face['n_warnings']!r} != len(warnings)"
        f"={len(warnings)}")


# ════════════════ 最小内联夹具（probe 实证可解析） ════════════════

SPICE_MINI = """* t
V1 in 0 DC 0 AC 1 0
R1 in out 1k
C1 out 0 1u
.end
"""

SDC_MINI = "create_clock -name clk -period 10 [get_ports clk]\n"

DRC_MINI = ('{"rules": [{"name": "w1", "type": "min_width", '
            '"value": 0.15, "unit": "mm"}]}')

VERILOG_MINI = ("module top(input a, output y);\n"
                "assign y = a;\nendmodule\n")

LEF_MINI = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS
  DATABASE MICRONS 2000 ;
END UNITS
END LIBRARY
"""

DEF_MINI = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
END DESIGN
"""

GERBER_MINI = """%FSLAX34Y34*%
%MOIN*%
%ADD10C,0.5*%
D10*
X0Y0D02*
X25400Y0D01*
M02*
"""

EXCELLON_MINI = """M48
METRIC,LZ
T01C0.8
%
T01
X10000Y10000
T0
M30
"""

SPEF_MINI = """*SPEF "IEEE 1481-1998"
*DESIGN "top"
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*10001 clk

*PORTS
clk I

*D_NET *10001 1.5
*CONN
*P clk I
*CAP
1 *10001 0.5
*RES
1 *10001 *10001 10.0
*END
"""

SDF_MINI = '(DELAYFILE (SDFVERSION "3.0") (TIMESCALE 1ns))'

VCD_MINI = """$timescale 1ps $end
$scope module top $end
$var wire 1 ! a $end
$upscope $end
$enddefinitions $end
#10
0!
"""

STIL_MINI = """STIL 1.0;
Signals {
    clk = In;
    WFC_0 = '0';
    WFC_1 = '1';
}
"""

IPC356_MINI = """P 2.10
C10000
M10 RFAUTO TEST USER
317XU1X00100Y00200R90
9999
"""

ODBPP_MATRIX_MINI = """LAYER {
    ROW=1
    CONTEXT=BOARD
    TYPE=SIGNAL
    NAME=F.CU
}
"""

TOUCHSTONE_MINI = "# GHZ S RI R 50\n1.0 1 0 0 0 0.5 0.5 0.2 -0.1\n"

SKILL_MINI = "(define (f x) x)\n"


def _mini_gdsii_bytes() -> bytes:
    """最小合法 GDSII 字节流（HEADER/BGNLIB/LIBNAME/UNITS+单结构单边界）。"""
    def rec(rt: int, payload: bytes = b"", dt: int = 0x00) -> bytes:
        return (4 + len(payload)).to_bytes(2, "big") + bytes([rt, dt]) + payload

    def i2(*vals: int) -> bytes:
        return struct.pack(f">{len(vals)}h", *vals)

    def i4(*vals: int) -> bytes:
        return struct.pack(f">{len(vals)}l", *vals)

    def real8(val: float) -> bytes:
        if val == 0.0:
            return b"\x00" * 8
        sign = 0x80 if val < 0 else 0
        x, e = abs(val), 0
        while x >= 1.0:
            x /= 16.0
            e += 1
        while x < 1.0 / 16.0:
            x *= 16.0
            e -= 1
        return bytes([sign | (e + 64)]) + round(x * 2.0 ** 56).to_bytes(7, "big")

    def ascii_padded(text: str) -> bytes:
        raw = text.encode("ascii")
        return raw + b"\x00" * (len(raw) % 2)

    ts = i2(*([0] * 12))
    return (rec(0x00, i2(600), 0x02) + rec(0x01, ts)
            + rec(0x02, ascii_padded("T"))
            + rec(0x03, real8(0.001) + real8(1.0), 0x05)
            + rec(0x05, ts) + rec(0x06, ascii_padded("TOP"))
            + rec(0x08) + rec(0x0D, i2(1), 0x02) + rec(0x0E, i2(0), 0x02)
            + rec(0x10, i4(0, 0, 4, 0, 4, 4, 0, 4, 0, 0), 0x03)
            + rec(0x11) + rec(0x07) + rec(0x04))


# ════════════════ 19 域参数化全表（producer → 待钉 doc 列表） ════════════════

def _spice_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_spice_netlist_text(SPICE_MINI)]


def _liberty_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [liberty_service.parse_liberty_file(LIBERTY_FIXTURE)]


def _citi_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [citi_service.citi_info(CITI_FIXTURE)]


def _sdc_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_sdc(SDC_MINI)]


def _ibis_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [ibis_service.parse_ibis_file(IBIS_FIXTURE)]


def _verilog_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_verilog(VERILOG_MINI)]


def _drc_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_drc_rules(DRC_MINI)]


def _lef_def_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    # LEF/DEF 双文档同键（子形态由既有 "format" 键区分，本批不动）。
    return [parse_lef(LEF_MINI), parse_def(DEF_MINI)]


def _gdsii_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_gdsii_bytes(_mini_gdsii_bytes())]


def _gerber_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_gerber(GERBER_MINI)]


def _excellon_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_excellon(EXCELLON_MINI)]


def _spef_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_spef(SPEF_MINI)]


def _sdf_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_sdf(SDF_MINI)]


def _skill_docs(tmp_path: Path) -> list[Mapping[str, Any]]:
    p = tmp_path / "mini.il"
    p.write_text(SKILL_MINI, encoding="utf-8")
    return [skill_service.parse_skill_file(p)]


def _vcd_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_vcd(VCD_MINI)]


def _touchstone_docs(tmp_path: Path) -> list[Mapping[str, Any]]:
    p = tmp_path / "mini.s2p"
    p.write_text(TOUCHSTONE_MINI, encoding="utf-8")
    return [parse_touchstone(p)]


def _ipc356_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_ipc356(IPC356_MINI)]


def _stil_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    return [parse_stil(STIL_MINI)]


def _odbpp_docs(_tmp: Path) -> list[Mapping[str, Any]]:
    # matrix 子文档（无 stats 面——odbpp 全树文档 parse_odb_dir 的
    # stats.n_warnings 由 test_odbpp_parser 既有钉覆盖，不在 P2-2 六件）。
    return [parse_odb_matrix(ODBPP_MATRIX_MINI)]


#: 域 → producer（tmp_path 入参统一；多数不用）。19 域全表。
#: ``LEGACY_COMPAT``=双层兼容域（verilog_netlist 旧键有仓内消费者，
#: 新旧并存一版——见模块 docstring「改名安全性」节）。
PRODUCERS: dict[str, Callable[..., list[Mapping[str, Any]]]] = {
    "spice_netlist": _spice_docs,
    "liberty": _liberty_docs,
    "citi": _citi_docs,
    "sdc": _sdc_docs,
    "ibis": _ibis_docs,
    "verilog_netlist": _verilog_docs,
    "drc": _drc_docs,
    "lef_def": _lef_def_docs,
    "gdsii": _gdsii_docs,
    "gerber": _gerber_docs,
    "excellon": _excellon_docs,
    "spef": _spef_docs,
    "sdf": _sdf_docs,
    "skill": _skill_docs,
    "vcd": _vcd_docs,
    "touchstone": _touchstone_docs,
    "ipc356": _ipc356_docs,
    "stil": _stil_docs,
    "odbpp": _odbpp_docs,
}


#: 双层兼容域集合（旧键并存，deprecated 注记在 parser 侧）。
LEGACY_COMPAT_DOMAINS = frozenset({"verilog_netlist"})


@pytest.mark.parametrize("domain", sorted(PRODUCERS))
def test_schema_key_unified(domain: str, tmp_path: Path) -> None:
    """19 件各 1 键形钉：``"schema"="<域>/1.0"`` + 旧键归零。

    verilog_netlist 例外=双层兼容（旧键并存且值钉死版本常量）。
    """
    for doc in PRODUCERS[domain](tmp_path):
        check_schema(doc, domain,
                     legacy_compat=domain in LEGACY_COMPAT_DOMAINS)


# ════════════════ n_warnings 补键钉（P2-2 六件；liberty N/A 如实） ════════════════

def _nwarn_spice(_tmp: Path) -> None:
    doc = parse_spice_netlist_text(SPICE_MINI)
    check_n_warnings(doc, doc["summary"], doc["warnings"], "spice_netlist")


def _nwarn_citi(_tmp: Path) -> None:
    env = citi_service.citi_info(CITI_FIXTURE)
    pkg = env["packages"][0]["metadata"]
    check_n_warnings(env, pkg, pkg["warnings"], "citi")


def _nwarn_ibis(_tmp: Path) -> None:
    env = ibis_service.parse_ibis_file(IBIS_FIXTURE)
    check_n_warnings(env, env["stats"], env["warnings"], "ibis")


def _nwarn_touchstone(tmp_path: Path) -> None:
    p = tmp_path / "mini.s2p"
    p.write_text(TOUCHSTONE_MINI, encoding="utf-8")
    doc = parse_touchstone(p)
    check_n_warnings(doc, doc["stats"], doc["warnings"], "touchstone")


def _nwarn_skill(_tmp: Path) -> None:
    doc = skill_definitions(parse_skill(SKILL_MINI))
    check_n_warnings(doc, doc["stats"], doc["warnings"], "skill")


#: 域 → n_warnings 钉（P2-2 六件中 5 件；liberty fail-closed 无
#: warnings 面（P2-3 同源）=结构性 N/A，count-of-nothing 不补——
#: 本表刻意不含 liberty，登记见模块 docstring）。
NWARN_CHECKS: dict[str, Callable[..., None]] = {
    "spice_netlist": _nwarn_spice,
    "citi": _nwarn_citi,
    "ibis": _nwarn_ibis,
    "touchstone": _nwarn_touchstone,
    "skill": _nwarn_skill,
}


@pytest.mark.parametrize("domain", sorted(NWARN_CHECKS))
def test_n_warnings_present(domain: str, tmp_path: Path) -> None:
    """P2-2 补键钉：n_warnings 键在且与 warnings 列表等长。"""
    NWARN_CHECKS[domain](tmp_path)
