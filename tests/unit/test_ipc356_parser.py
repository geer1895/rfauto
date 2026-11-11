"""IPC-D-356/356A 解析内核+服务+CLI 单测（aurora_q 席位 Q-X65，2026-11-07）。

夹具纪律（任务书口径）：内嵌小 356A 文本——``IPC356_MAIN``=头部全量
（P 2.10 版本+RECORD 类目文档行+C10000 缩放因子+M10/M20+CM 注释）+
317 元件 2（旗标紧凑形态+空格分派形态）+378 焊盘 5（跨 GND/VCC 两 net
+NET_SOLO 单点 net 构造，含 R/C 形状与 M 中点标志）+367 过孔 1+357 探针
1；``IPC356_LEGACY``=356 旧式固定列变体段（%NETNAME 模态 net 名段+空 %
清模态+未挂 net 焊盘）。变体形态（317XT/378XT、363、362、无孔、负坐标、
未知类目）以测试内小片段覆盖。零外部夹具文件；服务/CLI 测试经 tmp_path
落盘隔离（#144 run 湖零写入），零网络零真机。

覆盖面（任务书 ≥60 条）：C 因子换算表驱动已知量（#118 家法）、版本双
形态、头部逐项、记录类目逐类（317/378/367/362/363/357+XT 变体+未知类目
warning）、nets 映射+单点 net 清单+未挂 net 焊盘、查询三函数、
fab_pair_check（越界焊盘构造+钻孔覆盖计数+容差参数+skip 如实）、截断
fail-soft、文件级错误、信封契约、CLI --json 双路径+help 真构建（#305）
+计数链字面钉+cli.main 零导入钉。
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains.ipc356 import ipc356_app
from rfauto.core.ipc356_parser import (
    Ipc356ParseError,
    parse_ipc356,
    scale_to_mm,
)
from rfauto.service import ipc356_service

runner = CliRunner()

def _wired_app() -> typer.Typer:
    """合流接线形态镜像（接线两步处方的第 1 步；零共享 app 触碰）。

    typer 单命令 app 独立调用会塌缩成单命令（`report` 名不出现）——
    本席恰一叶，测试经 add_typer 包一层组根，与接线后
    ``rfauto ipc356 report ...`` 调用形态逐参一致。
    """
    root = typer.Typer()
    root.add_typer(ipc356_app, name="ipc356")
    return root

def _invoke(*args: object):
    """按接线后形态调用：``<组根> ipc356 <args>``（list/tuple 参数平铺）。"""
    argv: list[str] = []
    for arg in args:
        if isinstance(arg, (list, tuple)):
            argv.extend(str(item) for item in arg)
        else:
            argv.append(str(arg))
    return runner.invoke(_wired_app(), ["ipc356", *argv])

# ══════════════════════════ 夹具 ══════════════════════════

IPC356_MAIN = """\
P 2.10
RECORD 3 Class 317 Component
C10000
M10 RFAUTO TEST USER
M20 DATE 11-07-2026
CM CAMPAIGN Q-X65 FIXTURE BOARD
C317
317XU1X00100Y00200R90
317 R2 X00300Y00200 R0
378XU1-1X01000Y01000X0092S0003 GND
378XU1-2X02000Y01000X0092R0003 GND
378XR2-1X01000Y02000X0060C0002 VCC
378 R2-2 X02000Y02000 X0060 C0002 VCC
378XTP1X03000Y02000X0080S0004 NET_SOLO M
367XV1X01500Y01500X0035S0001
357XPROBE1X01000Y01000
9999
"""

#: 356 旧式固定列变体段：%NETNAME 模态 net 名段 + 空 % 清模态 + 未挂 net 焊盘。
IPC356_LEGACY = """\
P 2.10
C10000
M10 LEGACY TOOL
%
%NETNAME NET_L1
378XK1-1X00100Y00100X0060S0003
367XVK1X00200Y00200X0035S0001
%
378XK2-1X00300Y00100X0060S0003
9999
"""

#: P 3.00 版本行变体 + 317XT 元件变体。
IPC356_V3 = """\
P 3.00
C10000
317XTSW1X00400Y00200R270
9999
"""

def _parse(text: str) -> dict[str, Any]:
    return parse_ipc356(text)

def _doc() -> dict[str, Any]:
    return parse_ipc356(IPC356_MAIN)

def _legacy() -> dict[str, Any]:
    return parse_ipc356(IPC356_LEGACY)

def _write(tmp_path: Path, text: str, name: str = "board.d356") -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)

#: 配对面夹具（Q-X59 产物只读消费的测试输入）。
GERBER_BOARD = """\
%FSLAX34Y34*%
%MOMM*%
%ADD10C,0.5*%
D10*
X0Y0D02*
X400000Y0D01*
X400000Y300000D01*
X0Y300000D01*
X0Y0D01*
M02*
"""

#: 越界构造：pad A (10,10) 在 [0,40]×[0,30] 内；pad B (50,10) x 越界。
IPC356_OOB = """\
P 2.10
C10000
378XA1-1X01000Y01000X0060S0003 GND
378XB1-1X05000Y01000X0060S0003 GND
9999
"""

#: 钻孔覆盖构造：两孔正落 pad (10,10)/(20,10)，一孔 (25,25) 远离全部 pad。
EXCELLON_PADS = """\
M48
METRIC,LZ
T01C0.9
%
T01
X10000000Y10000000
X20000000Y10000000
X25000000Y25000000
M30
"""

#: 无 C 缩放因子的 356（坐标全未知 fail-soft 面）。
IPC356_NO_SCALE = """\
P 2.10
378XA1-1X01000Y01000X0060S0003 GND
9999
"""

# ══════════════════════════ C 因子换算（表驱动已知量 #118 家法）══════════════════════════

class TestScaleConversion:
    def test_known_c1000000(self):
        # 任务书钉定已知量：C1000000 + X0012345 → 1.2345 mm
        assert float(scale_to_mm(12345, 1000000)) == 1.2345

    def test_known_c100000(self):
        assert float(scale_to_mm(12345, 100000)) == 12.345

    def test_known_c10000(self):
        assert float(scale_to_mm(12345, 10000)) == 123.45

    def test_exact_fraction(self):
        # Fraction 精确十进制（12345*100/1000000 = 2469/2000）
        assert scale_to_mm(12345, 1000000) == Fraction(2469, 2000)

    def test_negative_coordinate(self):
        assert float(scale_to_mm(-1000, 10000)) == -10.0

    def test_none_raw(self):
        assert scale_to_mm(None, 10000) is None

    def test_none_factor(self):
        assert scale_to_mm(12345, None) is None

    def test_zero_factor(self):
        assert scale_to_mm(12345, 0) is None

    def test_negative_factor(self):
        assert scale_to_mm(12345, -100) is None

# ══════════════════════════ 头部逐项 ══════════════════════════

class TestHeader:
    def test_version_210(self):
        assert _doc()["version"] == "2.10"

    def test_version_300_variant(self):
        assert _parse(IPC356_V3)["version"] == "3.00"

    def test_scale_factor(self):
        assert _doc()["scale_factor"] == 10000

    def test_media_collects_cm_and_record_doc(self):
        media = _doc()["media"]
        assert "CAMPAIGN Q-X65 FIXTURE BOARD" in media
        assert "C317" in media  # ≤3 位 C 码=记录类目文档行

    def test_comments_collect_record_line(self):
        assert "RECORD 3 Class 317 Component" in _doc()["comments"]

    def test_cm_comment_in_comments(self):
        assert "CAMPAIGN Q-X65 FIXTURE BOARD" in _doc()["comments"]

    def test_user_name(self):
        assert _doc()["user_name"] == "RFAUTO TEST USER"

    def test_date(self):
        assert _doc()["date"] == "DATE 11-07-2026"

    def test_unknown_m_code_warns(self):
        doc = _parse("P 2.10\nC10000\nM30 WHATEVER\n9999\n")
        assert any("M30" in w for w in doc["warnings"])
        assert doc["user_name"] is None and doc["date"] is None

    def test_cm_multiple_lines(self):
        doc = _parse("P 2.10\nC10000\nCM ONE\nCM TWO\n9999\n")
        assert doc["media"] == ["ONE", "TWO"]

    def test_c_scale_zero_ineffective(self):
        doc = _parse("P 2.10\nC0000\n378XA1X00100Y00100S0003 GND\n9999\n")
        assert doc["scale_factor"] is None
        assert any("为 0" in w for w in doc["warnings"])
        assert doc["pads"][0]["x_mm"] is None  # 单位不明不猜

    def test_c_scale_duplicate_keeps_first(self):
        doc = _parse("P 2.10\nC10000\nC20000\n9999\n")
        assert doc["scale_factor"] == 10000
        assert any("重复登记" in w for w in doc["warnings"])

    def test_no_scale_warns_and_mm_none(self):
        doc = _parse(IPC356_NO_SCALE)
        assert doc["scale_factor"] is None
        assert any("无 C 坐标缩放因子" in w for w in doc["warnings"])
        assert doc["pads"][0]["x_mm"] is None
        assert doc["pads"][0]["raw"]["x"] == 1000  # 原始整数如实保留

    def test_unknown_header_statement_warns(self):
        doc = _parse("P 2.10\nC10000\nFOO BAR BAZ\n9999\n")
        assert any("FOO BAR BAZ" in w for w in doc["warnings"])

    def test_c_three_digit_is_record_doc_not_scale(self):
        doc = _parse("P 2.10\nC317\nC9999\n9999\n")
        assert doc["scale_factor"] == 9999
        assert "C317" in doc["media"]

# ══════════════════════════ 记录类目逐类 ══════════════════════════

class TestRecords:
    def test_component_count(self):
        assert len(_doc()["components"]) == 2

    def test_component_flag_form(self):
        c = _doc()["components"][0]
        assert c == {"record": "317", "refdes": "U1", "x_mm": 1.0,
                     "y_mm": 2.0, "rotation": 90,
                     "raw": {"x": 100, "y": 200}}

    def test_component_spaced_form(self):
        c = _doc()["components"][1]
        assert c["refdes"] == "R2"
        assert (c["x_mm"], c["y_mm"], c["rotation"]) == (3.0, 2.0, 0)

    def test_component_317xt_variant(self):
        c = _parse(IPC356_V3)["components"][0]
        assert c["refdes"] == "TSW1"
        assert (c["x_mm"], c["y_mm"], c["rotation"]) == (4.0, 2.0, 270)

    def test_363_dip_record(self):
        doc = _parse("P 2.10\nC10000\n363XD1X00500Y00600R0\n9999\n")
        assert doc["components"][0] == {
            "record": "363", "refdes": "D1", "x_mm": 5.0, "y_mm": 6.0,
            "rotation": 0, "raw": {"x": 500, "y": 600}}

    def test_pad_count(self):
        assert len(_doc()["pads"]) == 5

    def test_pad_full_fields(self):
        p = _doc()["pads"][0]
        assert p["record"] == "378"
        assert p["net"] == "GND"
        assert p["refdes"] == "U1" and p["pin"] == "1"
        assert (p["x_mm"], p["y_mm"]) == (10.0, 10.0)
        assert p["hole_mm"] == 0.92
        assert p["shape"] == "square" and p["size_raw"] == 3
        assert p["midpoint"] is False

    def test_pad_rectangle_shape(self):
        p = _doc()["pads"][1]
        assert p["shape"] == "rectangle" and p["size_raw"] == 3
        assert (p["x_mm"], p["y_mm"]) == (20.0, 10.0)

    def test_pad_circle_shape(self):
        p = _doc()["pads"][2]
        assert p["shape"] == "circle" and p["size_raw"] == 2
        assert p["hole_mm"] == 0.6

    def test_pad_spaced_form(self):
        p = _doc()["pads"][3]
        assert (p["net"], p["refdes"], p["pin"]) == ("VCC", "R2", "2")
        assert (p["x_mm"], p["y_mm"], p["hole_mm"]) == (20.0, 20.0, 0.6)
        assert p["shape"] == "circle"

    def test_pad_midpoint_flag(self):
        p = _doc()["pads"][4]
        assert p["midpoint"] is True
        assert p["net"] == "NET_SOLO" and p["refdes"] == "TP1"
        assert p["pin"] is None  # designator 无分隔=全 refdes

    def test_pad_raw_fields(self):
        p = _doc()["pads"][0]
        assert p["raw"] == {"x": 1000, "y": 1000, "hole": 92}

    def test_via_record(self):
        v = _doc()["vias"]
        assert len(v) == 1
        assert v[0]["record"] == "367"
        assert v[0]["net"] is None
        assert (v[0]["x_mm"], v[0]["y_mm"], v[0]["hole_mm"]) == (
            15.0, 15.0, 0.35)
        assert v[0]["shape"] == "square" and v[0]["size_raw"] == 1

    def test_via_with_net(self):
        doc = _parse("P 2.10\nC10000\n367XV1X00200Y00200X0035S0001 NETZ\n9999\n")
        assert doc["vias"][0]["net"] == "NETZ"
        assert doc["nets"] == {}  # 过孔不入 net→pads 映射（测试点=pads 口径）

    def test_362_non_test_face_pin(self):
        doc = _parse(
            "P 2.10\nC10000\n362XJ2-1X00200Y00300X0050S0002 NET_E\n9999\n")
        p = doc["pads"][0]
        assert p["record"] == "362"
        assert (p["net"], p["refdes"], p["pin"]) == ("NET_E", "J2", "1")
        assert (p["x_mm"], p["y_mm"], p["hole_mm"]) == (2.0, 3.0, 0.5)

    def test_pad_without_hole(self):
        doc = _parse("P 2.10\nC10000\n378XA1-1X00100Y00100S0003 GND\n9999\n")
        assert doc["pads"][0]["hole_mm"] is None
        assert doc["pads"][0]["raw"]["hole"] is None

    def test_negative_coordinates(self):
        doc = _parse(
            "P 2.10\nC10000\n378XA1-1X-01000Y-00200S0003 GND\n9999\n")
        p = doc["pads"][0]
        assert (p["x_mm"], p["y_mm"]) == (-10.0, -2.0)
        assert p["refdes"] == "A1" and p["pin"] == "1"

    def test_probe_record(self):
        pr = _doc()["probes"]
        assert len(pr) == 1
        assert pr[0] == {"record": "357", "name": "PROBE1",
                         "x_mm": 10.0, "y_mm": 10.0}

    def test_unknown_record_class_warns(self):
        doc = _parse("P 2.10\nC10000\n397XJUNKX00100Y00100\n9999\n")
        assert any("397" in w for w in doc["warnings"])
        assert doc["pads"] == [] and doc["components"] == []

    def test_unknown_statement_warns(self):
        doc = _parse("P 2.10\nC10000\n999XJUNK\n9999\n")
        assert any("999XJUNK" in w for w in doc["warnings"])

    def test_designator_without_x_digit_prefix(self):
        # designator 形如 R1（电阻惯例）在旗标形态下保真
        doc = _parse(
            "P 2.10\nC10000\n378XR1-1X01000Y00200X0060S0003 GND\n9999\n")
        assert (doc["pads"][0]["refdes"], doc["pads"][0]["pin"]) == ("R1", "1")

# ══════════════════════════ net 映射/单点 net/未挂 net ══════════════════════════

class TestNetTopology:
    def test_nets_map_exact(self):
        assert _doc()["nets"] == {"GND": [0, 1], "VCC": [2, 3],
                                  "NET_SOLO": [4]}

    def test_nets_sorted_names(self):
        assert sorted(_doc()["nets"]) == ["GND", "NET_SOLO", "VCC"]

    def test_single_point_nets_exact(self):
        assert _doc()["stats"]["single_point_nets"] == ["NET_SOLO"]

    def test_unassigned_pads_exact(self):
        doc = _legacy()
        ua = doc["stats"]["unassigned_pads"]
        assert ua == [{"index": 1, "refdes": "K2", "pin": "1",
                       "record": "378"}]
        assert doc["stats"]["n_unassigned_pads"] == 1

    def test_legacy_modal_net(self):
        doc = _legacy()
        assert doc["pads"][0]["net"] == "NET_L1"

    def test_legacy_empty_percent_clears_modal(self):
        doc = _legacy()
        assert doc["pads"][1]["net"] is None  # 空 % 行清模态 → 未挂 net

    def test_legacy_single_point(self):
        assert _legacy()["stats"]["single_point_nets"] == ["NET_L1"]

    def test_stats_counts(self):
        s = _doc()["stats"]
        assert s["n_components"] == 2
        assert s["n_pads"] == 5
        assert s["n_vias"] == 1
        assert s["n_probes"] == 1
        assert s["n_nets"] == 3

    def test_percent_plain_net_name_form(self):
        # 356 旧式第二形态：% 后直接 net 名（无 NETNAME 关键字）
        doc = _parse("P 2.10\nC10000\n% NET_X\n378XA1X00100Y00100S0003\n9999\n")
        assert doc["pads"][0]["net"] == "NET_X"

    def test_pad_level_net_overrides_modal(self):
        doc = _parse(
            "P 2.10\nC10000\n% NET_X\n378XA1X00100Y00100S0003 NET_Y\n9999\n")
        assert doc["pads"][0]["net"] == "NET_Y"

# ══════════════════════════ 查询三函数 ══════════════════════════

class TestQueries:
    def test_net_pads_returns_all_test_points(self):
        from rfauto.core.ipc356_parser import ipc356_net_pads
        got = ipc356_net_pads(_doc(), "GND")
        assert [p["pin"] for p in got] == ["1", "2"]
        assert all(p["net"] == "GND" for p in got)

    def test_net_pads_order_by_index(self):
        from rfauto.core.ipc356_parser import ipc356_net_pads
        got = ipc356_net_pads(_doc(), "VCC")
        assert [(p["refdes"], p["pin"]) for p in got] == [("R2", "1"),
                                                          ("R2", "2")]

    def test_net_pads_unknown_net_raises(self):
        from rfauto.core.ipc356_parser import ipc356_net_pads
        with pytest.raises(ValueError) as ei:
            ipc356_net_pads(_doc(), "NOPE")
        assert "NOPE" in str(ei.value)
        assert "可用" in str(ei.value)

    def test_component_pins_u1(self):
        from rfauto.core.ipc356_parser import ipc356_component_pins
        got = ipc356_component_pins(_doc(), "U1")
        assert [(p["pin"], p["x_mm"]) for p in got] == [("1", 10.0),
                                                        ("2", 20.0)]

    def test_component_pins_r2(self):
        from rfauto.core.ipc356_parser import ipc356_component_pins
        got = ipc356_component_pins(_doc(), "R2")
        assert [(p["refdes"], p["pin"]) for p in got] == [("R2", "1"),
                                                          ("R2", "2")]

    def test_component_pins_unknown_raises(self):
        from rfauto.core.ipc356_parser import ipc356_component_pins
        with pytest.raises(ValueError) as ei:
            ipc356_component_pins(_doc(), "Q7")
        assert "Q7" in str(ei.value)
        assert "U1" in str(ei.value)  # 可用名录随异常给出

    def test_single_point_nets_query(self):
        from rfauto.core.ipc356_parser import ipc356_single_point_nets
        assert ipc356_single_point_nets(_doc()) == ["NET_SOLO"]
        assert ipc356_single_point_nets(_legacy()) == ["NET_L1"]

# ══════════════════════════ fail-soft/文件级错误 ══════════════════════════

class TestFailSoft:
    def test_truncated_true_without_end_marker(self):
        doc = _parse("P 2.10\nC10000\n378XA1X00100Y00100S0003 GND\n")
        assert doc["truncated"] is True
        assert any("9999" in w for w in doc["warnings"])

    def test_truncated_false_with_9999(self):
        assert _doc()["truncated"] is False

    def test_end_marker_00000_accepted(self):
        doc = _parse("P 2.10\nC10000\n378XA1X00100Y00100S0003 GND\n00000\n")
        assert doc["truncated"] is False

    def test_empty_text_raises(self):
        with pytest.raises(Ipc356ParseError):
            parse_ipc356("")

    def test_whitespace_only_raises(self):
        with pytest.raises(Ipc356ParseError):
            parse_ipc356("   \n  \n")

    def test_no_version_raises(self):
        with pytest.raises(Ipc356ParseError) as ei:
            parse_ipc356("C10000\n378XA1X00100Y00100S0003 GND\n9999\n")
        assert "版本行" in str(ei.value)

    def test_garbage_raises(self):
        with pytest.raises(Ipc356ParseError) as ei:
            parse_ipc356("hello world\nnot a netlist\n")
        assert "不像" in str(ei.value)

    def test_deterministic(self):
        a = parse_ipc356(IPC356_MAIN)
        b = parse_ipc356(IPC356_MAIN)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

# ══════════════════════════ 服务信封 ══════════════════════════

class TestService:
    def test_parse_file_ok_envelope(self, tmp_path: Path):
        result = ipc356_service.parse_ipc356_file(_write(tmp_path, IPC356_MAIN))
        assert result["ok"] is True
        assert result["kind"] == "ipc356"
        assert result["path"].endswith("board.d356")
        assert result["version"] == "2.10"
        assert len(result["pads"]) == 5

    def test_parse_file_error_envelope_errors_list(self, tmp_path: Path):
        missing = str(tmp_path / "no.d356")
        result = ipc356_service.parse_ipc356_file(missing)
        assert result["ok"] is False
        assert isinstance(result["errors"], list)
        assert all(isinstance(e, str) for e in result["errors"])
        assert "不可读" in result["errors"][0]

    def test_parse_file_empty(self, tmp_path: Path):
        result = ipc356_service.parse_ipc356_file(_write(tmp_path, ""))
        assert result["ok"] is False
        assert "解析失败" in result["errors"][0]

    def test_parse_file_no_version(self, tmp_path: Path):
        result = ipc356_service.parse_ipc356_file(
            _write(tmp_path, "C10000\n378XA1X00100Y00100S0003 GND\n9999\n"))
        assert result["ok"] is False
        assert "版本行" in result["errors"][0]

    def test_parse_file_directory_unreadable(self, tmp_path: Path):
        result = ipc356_service.parse_ipc356_file(tmp_path)
        assert result["ok"] is False
        assert "不可读" in result["errors"][0]

    def test_parse_file_latin1_tolerant(self, tmp_path: Path):
        p = tmp_path / "latin.d356"
        p.write_bytes(b"P 2.10\nC10000\nCM caf\xe9 note\n9999\n")
        result = ipc356_service.parse_ipc356_file(str(p))
        assert result["ok"] is True
        assert "caf" in result["media"][0]

    def test_report_envelope(self, tmp_path: Path):
        result = ipc356_service.ipc356_report(_write(tmp_path, IPC356_MAIN))
        assert result["ok"] is True
        assert result["kind"] == "ipc356_report"
        assert result["version"] == "2.10"
        assert result["scale_factor"] == 10000
        assert result["nets"] == ["GND", "NET_SOLO", "VCC"]
        assert result["single_point_nets"] == ["NET_SOLO"]
        assert result["stats"]["n_pads"] == 5
        assert result["truncated"] is False

    def test_report_bbox(self, tmp_path: Path):
        result = ipc356_service.ipc356_report(_write(tmp_path, IPC356_MAIN))
        # 焊盘+过孔已知坐标聚合：(10,10)..(30,20)
        assert result["bbox_mm"] == [10.0, 10.0, 30.0, 20.0]

    def test_report_bbox_none_when_all_unknown(self, tmp_path: Path):
        result = ipc356_service.ipc356_report(_write(tmp_path, IPC356_NO_SCALE))
        assert result["bbox_mm"] is None

    def test_report_missing_file_error(self, tmp_path: Path):
        result = ipc356_service.ipc356_report(str(tmp_path / "no.d356"))
        assert result["ok"] is False
        assert isinstance(result["errors"], list)

    def test_pair_requires_at_least_one_side(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN))
        assert result["ok"] is False
        assert "至少" in result["errors"][0]

    def test_pair_gerber_only(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN, "b.d356"),
            _write(tmp_path, GERBER_BOARD, "top.gbr"))
        assert result["ok"] is True
        assert result["kind"] == "ipc356_pair_check"
        assert result["n_pads"] == 5 and result["n_pads_known"] == 5
        assert result["bbox_mm"] == [0.0, 0.0, 40.0, 30.0]
        assert result["n_out_of_bounds"] == 0
        assert result["drill_available"] is False

    def test_pair_drill_only_coverage(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN, "b.d356"),
            drill_path=_write(tmp_path, EXCELLON_PADS, "board.drl"))
        assert result["ok"] is True
        assert result["gerber_available"] is False
        assert result["n_holes"] == 3
        assert result["n_covered"] == 2
        assert result["n_uncovered"] == 1
        row = result["uncovered"][0]
        assert (row["x_mm"], row["y_mm"]) == (25.0, 25.0)
        assert row["nearest_pad_mm"] == pytest.approx(7.0710678, rel=1e-6)
        assert row["nearest_pad_xy"] == [20.0, 20.0]

    def test_pair_drill_tol_widens_coverage(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN, "b.d356"),
            drill_path=_write(tmp_path, EXCELLON_PADS, "board.drl"),
            tol_mm=10.0)
        assert result["n_covered"] == 3
        assert result["n_uncovered"] == 0

    def test_pair_both_sides(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN, "b.d356"),
            _write(tmp_path, GERBER_BOARD, "top.gbr"),
            _write(tmp_path, EXCELLON_PADS, "board.drl"))
        assert result["ok"] is True
        assert result["n_out_of_bounds"] == 0
        assert result["n_covered"] == 2 and result["n_uncovered"] == 1

    def test_pair_out_of_bounds_constructed(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_OOB, "oob.d356"),
            _write(tmp_path, GERBER_BOARD, "top.gbr"))
        assert result["ok"] is True
        assert result["n_out_of_bounds"] == 1
        row = result["out_of_bounds"][0]
        assert row["index"] == 1
        assert row["refdes"] == "B1" and row["pin"] == "1"
        assert row["axis"] == "x" and row["value_mm"] == 50.0
        assert (row["x_mm"], row["y_mm"]) == (50.0, 10.0)
        assert result["n_pads_skipped_bounds"] == 0

    def test_pair_gerber_fail_fast(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_MAIN, "b.d356"),
            str(tmp_path / "missing.gbr"))
        assert result["ok"] is False
        assert isinstance(result["errors"], list)

    def test_pair_ipc_fail_fast(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            str(tmp_path / "missing.d356"),
            _write(tmp_path, GERBER_BOARD, "top.gbr"))
        assert result["ok"] is False
        assert "IPC-D-356" in result["errors"][0]

    def test_pair_unknown_pad_coords_skip_all(self, tmp_path: Path):
        result = ipc356_service.ipc356_fab_pair_check(
            _write(tmp_path, IPC356_NO_SCALE, "ns.d356"),
            _write(tmp_path, GERBER_BOARD, "top.gbr"),
            _write(tmp_path, EXCELLON_PADS, "board.drl"))
        assert result["ok"] is True
        assert result["n_pads_known"] == 0
        assert result["n_pads_skipped_bounds"] == 1
        assert result["n_holes_skipped"] == 3
        assert result["n_covered"] == 0 and result["n_uncovered"] == 0
        assert any("全未知" in n for n in result["notes"])

    def test_service_deterministic(self, tmp_path: Path):
        path = _write(tmp_path, IPC356_MAIN)
        a = ipc356_service.ipc356_report(path)
        b = ipc356_service.ipc356_report(path)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_error_envelopes_shape(self, tmp_path: Path):
        missing = str(tmp_path / "x.d356")
        for env in (ipc356_service.parse_ipc356_file(missing),
                    ipc356_service.ipc356_report(missing),
                    ipc356_service.ipc356_fab_pair_check(missing, missing)):
            assert env["ok"] is False
            assert isinstance(env["errors"], list)
            assert all(isinstance(e, str) for e in env["errors"])

# ══════════════════════════ CLI 一叶 ══════════════════════════

class TestCli:
    def test_report_json_envelope(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_MAIN), "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is True
        assert envelope["kind"] == "ipc356_report"
        assert envelope["single_point_nets"] == ["NET_SOLO"]
        assert envelope["bbox_mm"] == [10.0, 10.0, 30.0, 20.0]

    def test_report_json_failure_envelope(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", str(tmp_path / "no.d356"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_report_human_output(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_MAIN)])
        assert res.exit_code == 0, res.output
        assert "IPC-D-356 报告" in res.output
        assert "pads=5" in res.output
        assert "NET_SOLO" in res.output  # 单点 net（开路嫌疑）清单

    def test_report_human_failure_exit_1(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", str(tmp_path / "no.d356")])
        assert res.exit_code == 1
        assert "IPC-D-356 报告失败" in res.output

    def test_pair_json_envelope(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_MAIN, "b.d356"),
            "--check-gerber", _write(tmp_path, GERBER_BOARD, "top.gbr"),
            "--check-drill", _write(tmp_path, EXCELLON_PADS, "board.drl"),
            "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["kind"] == "ipc356_pair_check"
        assert envelope["n_out_of_bounds"] == 0
        assert envelope["n_covered"] == 2 and envelope["n_uncovered"] == 1

    def test_pair_human_output(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_MAIN, "b.d356"),
            "--check-gerber", _write(tmp_path, GERBER_BOARD, "top.gbr")])
        assert res.exit_code == 0, res.output
        assert "IPC-D-356 配对校验" in res.output
        assert "越界焊盘=0" in res.output

    def test_pair_oob_json(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_OOB, "oob.d356"),
            "--check-gerber", _write(tmp_path, GERBER_BOARD, "top.gbr"),
            "--json"])
        assert res.exit_code == 0, res.output
        envelope = json.loads(res.output)
        assert envelope["n_out_of_bounds"] == 1
        assert envelope["out_of_bounds"][0]["refdes"] == "B1"

    def test_pair_failure_json_envelope(self, tmp_path: Path):
        res = _invoke("report", [
            "--file", _write(tmp_path, IPC356_MAIN, "b.d356"),
            "--check-gerber", str(tmp_path / "missing.gbr"), "--json"])
        assert res.exit_code == 1
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert isinstance(envelope["errors"], list)

    def test_missing_file_flag_fails(self):
        res = _invoke("report")
        assert res.exit_code != 0

    def test_help_builds_no_bare_percent(self):
        # #305 家法：--help 真构建 + 零裸 %
        for leaf in (["report", "--help"], ["--help"]):
            res = _invoke(*leaf)
            assert res.exit_code == 0, res.output
            assert "%" not in res.output

    def test_cli_leaf_literal_pin(self):
        # 计数链钉：ipc356 域恰 1 叶（report）、带 --json（新叶无 --json 即红）
        source = Path(ipc356_service.__file__).parent.parent.joinpath(
            "cli", "domains", "ipc356.py").read_text(encoding="utf-8")
        assert source.count('@ipc356_app.command("report")') == 1
        assert source.count("@ipc356_app.command(") == 1
        assert source.count("json_output: bool = typer.Option") == 1
        assert '--json", "-j"' in source
