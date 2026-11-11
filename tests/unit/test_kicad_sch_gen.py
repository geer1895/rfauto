"""T-Q22 KiCad 原理图生成+一致性闭环 单测（全离线零真机零网络）。

覆盖面：
- adapters/kicad_sch_gen：s-expr 结构钉/声明式布局规则钉/round-trip 回读
  正例+断线/改标负例/ERC rpt 解析（KiCad 10.0.6 真机样本 fixture）/
  adapters 零第三方依赖静态钉；
- service/kicad_sch_service：SchSpec schema 校验/生成信封/二值证书三正例
  一负例/run_erc 子进程封装（subprocess 全 mock，exit 0/5/3 口径+skipped+
  timeout+解析降级）。

真机（kicad-cli ERC/netlist 实跑）不在本文件——证据件在
runs/aurora_q/qcad1_smoke/（Y-flip 约定与 exit code 口径的真机对拍实录）。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rfauto.adapters.kicad_sch_gen import (
    GenComponent,
    GenNet,
    SchGridLayout,
    derive_pin_map,
    parse_erc_report,
    parse_sexpr,
    pin_local_offset,
    pin_world_pos,
    readback_nets,
    render_schematic,
    symbol_slot_xy,
)
from rfauto.service.kicad_sch_service import (
    SCH_SPEC_SCHEMA,
    SchSpec,
    generate_schematic,
    round_trip_certificate,
    run_erc,
    spec_from_payload,
    spec_to_gen,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kicad_sch"

TWO_RES = {
    "schema": SCH_SPEC_SCHEMA,
    "components": [
        {"ref": "R1", "value": "10k", "lib_id": "Device:R"},
        {"ref": "R2", "value": "20k", "lib_id": "Device:R"},
    ],
    "nets": [
        {"name": "VIN", "pins": [{"ref": "R1", "pin": "1"}]},
        {"name": "MID", "pins": [{"ref": "R1", "pin": "2"},
                                 {"ref": "R2", "pin": "1"}]},
        {"name": "GND", "pins": [{"ref": "R2", "pin": "2"}]},
    ],
}


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _spec(comps: dict, nets: dict) -> dict:
    return {"schema": SCH_SPEC_SCHEMA, "components": comps, "nets": nets}


def _gen(spec: dict) -> str:
    from rfauto.service.kicad_sch_service import spec_to_gen
    sp = spec_from_payload(spec)
    comps, nets = spec_to_gen(sp)
    return render_schematic(comps, nets)


# ---------------------------------------------------------------------------
# s-expr 结构钉（生成器）
# ---------------------------------------------------------------------------


class TestRenderSchematic:
    def test_header_tokens(self):
        text = _gen(TWO_RES)
        root = parse_sexpr(text)[0]
        assert root[0] == "kicad_sch"
        assert ["version", "20250114"] in [[c[0], c[1]] for c in root[1:]
                                           if isinstance(c, list)
                                           and len(c) > 1 and c[0] == "version"]
        gen = next(c for c in root[1:] if isinstance(c, list)
                   and c[0] == "generator")
        assert gen[1] == "rfauto"
        paper = next(c for c in root[1:] if isinstance(c, list)
                     and c[0] == "paper")
        assert paper[1] == "A4"

    def test_lib_symbol_per_distinct_libid(self):
        spec = _spec(
            [{"ref": "R1", "value": "a", "lib_id": "Device:R"},
             {"ref": "R2", "value": "b", "lib_id": "Device:R"},
             {"ref": "C1", "value": "c", "lib_id": "Device:C"}], [])
        root = parse_sexpr(_gen(spec))[0]
        libs = next(c for c in root[1:] if isinstance(c, list)
                    and c[0] == "lib_symbols")
        names = [c[1] for c in libs[1:]
                 if isinstance(c, list) and c[0] == "symbol"]
        assert names == ["Device:R", "Device:C"]
        # 子块命名 <name>_0_1（公共图形）/<name>_1_1（unit 1 引脚）
        r = next(c for c in libs[1:] if isinstance(c, list) and c[1] == "Device:R")
        child_names = [c[1] for c in r[2:]
                       if isinstance(c, list) and c[0] == "symbol"]
        assert child_names == ["R_0_1", "R_1_1"]

    def test_instance_blocks_and_properties(self):
        spec = _load_fixture("spec_rc_lowpass.json")
        text = _gen(spec)
        root = parse_sexpr(text)[0]
        insts = [c for c in root[1:] if isinstance(c, list)
                 and c[0] == "symbol"]
        assert len(insts) == 3
        by_ref = {}
        for s in insts:
            props = {p[1]: p[2] for p in s[1:] if isinstance(p, list)
                     and p[0] == "property"}
            by_ref[props["Reference"]] = props
        assert by_ref["C1"]["Footprint"] == "Capacitor_SMD:C_0402_1005Metric"
        assert by_ref["R1"]["Value"] == "10k"
        # instances 归档块：project/path/reference/unit 四层
        inst = insts[0]
        arch = next(c for c in inst[1:] if isinstance(c, list)
                    and c[0] == "instances")
        proj = next(c for c in arch[1:] if isinstance(c, list)
                    and c[0] == "project")
        path = next(c for c in proj[1:] if isinstance(c, list)
                    and c[0] == "path")
        refs = [c[1] for c in path[1:] if isinstance(c, list)
                and c[0] == "reference"]
        assert refs == ["R1"]

    def test_stub_and_label_per_net_pin(self):
        text = _gen(TWO_RES)
        # 4 个 net 引脚 → 4 导线 4 label（VIN1/MID2/GND1）
        assert text.count("(wire") == 4
        assert len(re.findall(r'\(label "VIN"\n', text)) == 1
        assert len(re.findall(r'\(label "MID"\n', text)) == 2
        assert len(re.findall(r'\(label "GND"\n', text)) == 1

    def test_stub_outward_direction_rule(self):
        """声明式 stub 规则：左侧向外=−x、右侧向外=+x（R1.1 左脚实例）。"""
        lay = SchGridLayout()
        text = _gen(TWO_RES)
        inst = symbol_slot_xy(0, lay)
        px, py = pin_world_pos(0, 2, inst, lay)  # R1.1：偶序=左
        assert f"(xy {px:g} {py:g}) (xy {px - lay.stub_len_mm:g} {py:g})" in text
        # R1.2：奇序=右
        px2, py2 = pin_world_pos(1, 2, inst, lay)
        assert f"(xy {px2:g} {py2:g}) (xy {px2 + lay.stub_len_mm:g} {py2:g})" \
            in text

    def test_deterministic_byte_identical(self):
        t1 = _gen(TWO_RES)
        t2 = _gen(TWO_RES)
        assert t1 == t2
        # 不同位号（网表同步改名）→ uuid5 内容键不同 → 全文不同
        other = _spec(
            [{"ref": "R3", "value": "10k", "lib_id": "Device:R"},
             {"ref": "R4", "value": "20k", "lib_id": "Device:R"}],
            [{"name": "VIN", "pins": [{"ref": "R3", "pin": "1"}]},
             {"name": "MID", "pins": [{"ref": "R3", "pin": "2"},
                                      {"ref": "R4", "pin": "1"}]},
             {"name": "GND", "pins": [{"ref": "R4", "pin": "2"}]}])
        assert _gen(other) != t1

    def test_empty_components_raises(self):
        with pytest.raises(ValueError, match="components 必须非空"):
            render_schematic([], [])

    def test_footprint_optional_hidden(self):
        text = _gen(TWO_RES)
        assert '(property "Footprint" ""' in text  # 缺省=空串（隐藏属性）


# ---------------------------------------------------------------------------
# 声明式布局规则钉（铁律 7：坐标/间距=显式参数）
# ---------------------------------------------------------------------------


class TestDeclarativeLayout:
    def test_grid_defaults_on_1p27mm_grid(self):
        """全部缺省参数=1.27mm（KiCad 连接栅格 50mil）整数倍。

        离栅坐标触发 ERC endpoint_off_grid 警告（KiCad 10.0.6 真机实测，
        runs/aurora_q/qcad1_smoke/）；origin 也不例外。
        """
        lay = SchGridLayout()
        for name in ("origin_x_mm", "origin_y_mm", "col_pitch_mm",
                     "row_pitch_mm", "stub_len_mm", "pin_pitch_mm",
                     "body_w_mm", "min_body_h_mm", "pin_len_mm"):
            v = getattr(lay, name)
            k = v / 1.27
            assert abs(k - round(k)) < 1e-9, f"{name}={v} 离栅（{k}×1.27）"

    def test_slot_xy_grid_mapping(self):
        lay = SchGridLayout(per_row=2, col_pitch_mm=10.0, row_pitch_mm=20.0,
                            origin_x_mm=1.0, origin_y_mm=2.0)
        assert symbol_slot_xy(0, lay) == (1.0, 2.0)
        assert symbol_slot_xy(1, lay) == (11.0, 2.0)
        assert symbol_slot_xy(2, lay) == (1.0, 22.0)
        assert symbol_slot_xy(5, lay) == (11.0, 42.0)

    def test_pin_offset_alternation_rule(self):
        """交替取边（偶左奇右）+ 同侧自上而下（slot 0 最上，y 向下）。"""
        lay = SchGridLayout(pin_pitch_mm=2.54)
        # 4 引脚：0/2 左，1/3 右；左 0 在上（dy<0）
        assert pin_local_offset(0, 4, lay) == ("left", -1.27)
        assert pin_local_offset(1, 4, lay) == ("right", -1.27)
        assert pin_local_offset(2, 4, lay) == ("left", 1.27)
        assert pin_local_offset(3, 4, lay) == ("right", 1.27)
        # 3 引脚：左 2 右 1；右单脚居中
        assert pin_local_offset(0, 3, lay) == ("left", -1.27)
        assert pin_local_offset(1, 3, lay) == ("right", 0.0)
        assert pin_local_offset(2, 3, lay) == ("left", 1.27)

    def test_pin_world_pos_y_flip_convention(self):
        """Y 翻转约定钉：world=(inst_x±half, inst_y+dy_world)（angle=0）。

        约定真值源=kicad-cli ``sch export netlist`` 真机对拍（stub 精确落
        引脚=连通正确，runs/aurora_q/qcad1_smoke/ 证据件）——本钉防约定
        被无声改动。4 引脚：0/2 左（上/下），1/3 右（上/下）。
        """
        lay = SchGridLayout()
        inst = (100.0, 200.0)
        half = lay.body_w_mm / 2 + lay.pin_len_mm
        x, y = pin_world_pos(0, 4, inst, lay)
        assert x == pytest.approx(100.0 - half)
        assert y == pytest.approx(200.0 - 1.27)  # 左上（y 向下坐标）
        x2, y2 = pin_world_pos(1, 4, inst, lay)
        assert x2 == pytest.approx(100.0 + half)
        assert y2 == pytest.approx(200.0 - 1.27)
        x3, y3 = pin_world_pos(3, 4, inst, lay)
        assert x3 == pytest.approx(100.0 + half)
        assert y3 == pytest.approx(200.0 + 1.27)

    def test_body_height_rule(self):
        from rfauto.adapters.kicad_sch_gen import body_height_mm
        lay = SchGridLayout(min_body_h_mm=7.62, pin_pitch_mm=2.54)
        assert body_height_mm(2, lay) == pytest.approx(7.62)  # 下限
        assert body_height_mm(8, lay) == pytest.approx((4 + 2) * 2.54)

    def test_derive_pin_map_union_and_sort(self):
        comps = [GenComponent("U1", "ic", "lib:U", pins=("3",)),
                 GenComponent("R1", "r", "lib:R")]
        nets = [GenNet("A", (("U1", "1"), ("R1", "2"))),
                GenNet("B", (("U1", "2"),))]
        got = derive_pin_map(comps, nets)
        assert got["U1"] == ["1", "2", "3"]  # 显式 ∪ nets 引用，数值序
        assert got["R1"] == ["2"]

    def test_derive_pin_map_numeric_before_alpha(self):
        comps = [GenComponent("U1", "ic", "lib:U")]
        nets = [GenNet("A", (("U1", "A1"), ("U1", "10"), ("U1", "2")))]
        assert derive_pin_map(comps, nets)["U1"] == ["2", "10", "A1"]


# ---------------------------------------------------------------------------
# s-expr 解析 + round-trip 回读
# ---------------------------------------------------------------------------


class TestParseSexpr:
    def test_nested_and_quoted(self):
        top = parse_sexpr('(a (b "hello world") (c "x\\"y" 1.5))')
        assert len(top) == 1
        node = top[0]
        assert node[0] == "a"
        assert node[1] == ["b", "hello world"]
        assert node[2] == ["c", 'x"y', "1.5"]

    def test_unbalanced_raises(self):
        with pytest.raises(ValueError, match="括号不配对"):
            parse_sexpr("(a (b)) )")
        with pytest.raises(ValueError, match="括号不配对"):
            parse_sexpr("(a (b ")


class TestReadbackNets:
    def test_roundtrip_matches_spec(self):
        rb = readback_nets(_gen(TWO_RES))
        assert rb.nets == {"VIN": [("R1", "1")],
                           "MID": [("R1", "2"), ("R2", "1")],
                           "GND": [("R2", "2")]}
        assert rb.unnamed_pins == []

    def test_readback_rc_lowpass_fixture(self):
        rb = readback_nets(_gen(_load_fixture("spec_rc_lowpass.json")))
        assert rb.nets["MID"] == [("C1", "1"), ("R1", "2"), ("R2", "1")]
        assert rb.nets["GND"] == [("C1", "2"), ("R2", "2")]
        assert rb.unnamed_pins == []

    def test_missing_wire_breaks_connectivity(self):
        """断线负例：删一条 stub 导线 → 该引脚失联（证书必现形）。"""
        text = _gen(TWO_RES)
        broken = re.sub(r"\t\(wire\n(?:\t{2,}.*\n)*?\t\)\n", "", text, count=1)
        assert broken != text
        rb = readback_nets(broken)
        # 第一条导线=R1.1（VIN）——label 仍在原位但与引脚断开
        assert rb.nets["VIN"] == []
        assert ("R1", "1") in rb.unnamed_pins

    def test_relabel_merges_nets(self):
        """改标负例：MID→MIDX —— 连通集随 label 名走（名称制语义）。"""
        text = _gen(TWO_RES)
        mutated = text.replace('(label "MID"', '(label "MIDX"')
        rb = readback_nets(mutated)
        assert "MID" not in rb.nets
        assert rb.nets["MIDX"] == [("R1", "2"), ("R2", "1")]

    def test_nonzero_angle_rejected(self):
        text = _gen(TWO_RES)
        mutated = text.replace("(at 50.8 50.8 0)", "(at 50.8 50.8 90)")
        with pytest.raises(ValueError, match="angle"):
            readback_nets(mutated)

    def test_not_kicad_sch_rejected(self):
        with pytest.raises(ValueError, match="kicad_sch"):
            readback_nets("(other (version 1))")
        with pytest.raises(ValueError, match="括号不配对"):
            readback_nets("(kicad_sch (version")


# ---------------------------------------------------------------------------
# ERC 报告解析（KiCad 10.0.6 真机样本 fixture）
# ---------------------------------------------------------------------------


class TestErcReportParser:
    def test_real_sample_counts_and_items(self):
        rpt = (_FIXTURES / "erc_report_sample.rpt").read_text(encoding="utf-8")
        got = parse_erc_report(rpt)
        assert got["ok"] is True
        assert got["total_count"] == 4
        assert got["error_count"] == 0
        assert got["warning_count"] == 4
        assert [i["type"] for i in got["items"]] == [
            "isolated_pin_label", "lib_symbol_mismatch",
            "lib_symbol_mismatch", "lib_symbol_mismatch"]
        assert all(i["severity"] == "warning" for i in got["items"])
        first = got["items"][0]
        assert first["title"] == "Label connected to only one pin"
        assert any("Label 'VIN'" in d for d in first["details"])

    def test_real_errors_sample(self):
        rpt = (_FIXTURES / "erc_report_errors.rpt").read_text(encoding="utf-8")
        got = parse_erc_report(rpt)
        assert got["ok"] is True
        assert got["total_count"] == 8
        assert got["error_count"] == 2
        assert got["warning_count"] == 6
        sev = {i["type"]: i["severity"] for i in got["items"]}
        assert sev["pin_not_connected"] == "error"
        assert sev["endpoint_off_grid"] == "warning"
        assert sev["lib_symbol_issues"] == "warning"

    def test_malformed_no_summary(self):
        for bad in ("", "hello world", "ERC report\nno summary here\n"):
            got = parse_erc_report(bad)
            assert got["ok"] is False
            assert got["error_count"] is None  # 不伪造 0
            assert got["warning_count"] is None
            assert got["errors"]

    def test_summary_and_items_independent(self):
        """--severity 过滤面：条目可少于汇总计数（两口径不合并）。"""
        rpt = (_FIXTURES / "erc_report_sample.rpt").read_text(encoding="utf-8")
        filtered = re.sub(r"\[lib_symbol_mismatch\][^\n]*\n"
                          r"(?:    ;.*\n    @.*\n|\s+@.*\n)", "", rpt)
        got = parse_erc_report(filtered)
        assert got["ok"] is True
        assert got["warning_count"] == 4  # 汇总行恒全量
        assert len(got["items"]) == 1  # 条目已过滤


# ---------------------------------------------------------------------------
# adapters 零第三方依赖（静态 AST 钉）
# ---------------------------------------------------------------------------


class TestAdapterZeroDeps:
    def test_stdlib_only_imports(self):
        src = Path(
            __file__).resolve().parents[2] / "src" / "rfauto" / "adapters" \
            / "kicad_sch_gen.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module:
                mods.add(node.module.split(".")[0])
        allowed = {"__future__", "collections", "dataclasses", "itertools",
                   "re", "uuid"}
        assert mods <= allowed, f"第三方/越界 import: {mods - allowed}"


# ---------------------------------------------------------------------------
# SchSpec schema（Pydantic 严格契约）
# ---------------------------------------------------------------------------


class TestSchSpecSchema:
    def test_payload_schema_string_pinned(self):
        assert spec_from_payload(TWO_RES).components[0].ref == "R1"
        with pytest.raises(ValueError, match="schema"):
            spec_from_payload({"schema": "wrong-v9", **{}}
                              | {"components": TWO_RES["components"],
                                 "nets": TWO_RES["nets"]})

    def test_schspec_instance_passthrough(self):
        sp = SchSpec.model_validate(
            {k: v for k, v in TWO_RES.items() if k != "schema"})
        assert spec_from_payload(sp) is sp

    def test_duplicate_refs_rejected(self):
        with pytest.raises(ValidationError, match="位号重复"):
            SchSpec.model_validate({
                "components": [{"ref": "R1", "lib_id": "Device:R"},
                               {"ref": "R1", "lib_id": "Device:R"}],
                "nets": []})

    def test_duplicate_net_names_rejected(self):
        with pytest.raises(ValidationError, match="网络名重复"):
            SchSpec.model_validate({
                "components": [{"ref": "R1", "lib_id": "Device:R"}],
                "nets": [{"name": "A", "pins": [{"ref": "R1", "pin": "1"}]},
                         {"name": "A", "pins": [{"ref": "R1", "pin": "2"}]}]})

    def test_duplicate_pin_within_net_rejected(self):
        with pytest.raises(ValidationError, match="引脚重复"):
            SchSpec.model_validate({
                "components": [{"ref": "R1", "lib_id": "Device:R"}],
                "nets": [{"name": "A", "pins": [{"ref": "R1", "pin": "1"},
                                                {"ref": "R1", "pin": "1"}]}]})

    def test_empty_components_rejected(self):
        with pytest.raises(ValidationError):
            SchSpec.model_validate({"components": [], "nets": []})

    def test_dangling_net_ref_rejected_at_projection(self):
        sp = SchSpec.model_validate({
            "components": [{"ref": "R1", "lib_id": "Device:R"}],
            "nets": [{"name": "A", "pins": [{"ref": "R9", "pin": "1"}]}]})
        with pytest.raises(ValueError, match="未声明元件"):
            spec_to_gen(sp)

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            SchSpec.model_validate({
                "components": [{"ref": "R1", "lib_id": "Device:R",
                                "unknown_key": 1}], "nets": []})


# ---------------------------------------------------------------------------
# 生成编排 + 二值证书（三正例一负例=验收冻结口径）
# ---------------------------------------------------------------------------


class TestGenerateSchematic:
    def test_envelope_and_file_written(self, tmp_path):
        out = tmp_path / "two_res.kicad_sch"
        env = generate_schematic(TWO_RES, out)
        assert env["ok"] is True
        assert env["n_components"] == 2
        assert env["n_nets"] == 3
        assert env["certificate"]["pass"] is True
        assert out.is_file()
        assert out.read_text(encoding="utf-8").startswith("(kicad_sch")

    @pytest.mark.parametrize("fixture", ["spec_two_res.json",
                                         "spec_rc_lowpass.json",
                                         "spec_ic8.json"])
    def test_certificate_three_positive_cases(self, tmp_path, fixture):
        env = generate_schematic(_load_fixture(fixture),
                                 tmp_path / fixture.replace(".json", ".sch"))
        assert env["ok"] is True, env
        cert = env["certificate"]
        assert cert["pass"] is True
        assert cert["diff"] == []
        assert cert["n_nets_expected"] == cert["n_nets_readback"]
        assert cert["unnamed_pins"] == []

    def test_certificate_fail_on_relabel_negative(self, tmp_path):
        """验收冻结负例：故意改标 → 证书 FAIL 带 diff 清单。"""
        sp = spec_from_payload(TWO_RES)
        text = _gen(TWO_RES)
        mutated = text.replace('(label "MID"', '(label "MIDX"')
        cert = round_trip_certificate(sp, mutated)
        assert cert["pass"] is False
        kinds = {(d["kind"], d["net"]) for d in cert["diff"]}
        assert ("missing_net", "MID") in kinds
        assert ("extra_net", "MIDX") in kinds

    def test_certificate_fail_on_pin_mismatch(self, tmp_path):
        # spec 删 MID 网络的 R2.1 引脚引用（与生成文本不一致）
        broken = SchSpec.model_validate({
            "components": [{k: v for k, v in c.items() if k != "schema"}
                           for c in TWO_RES["components"]],
            "nets": [{"name": "MID",
                      "pins": [{"ref": "R1", "pin": "2"}]},
                     *[n for n in TWO_RES["nets"] if n["name"] != "MID"]]})
        cert = round_trip_certificate(broken, _gen(TWO_RES))
        assert cert["pass"] is False
        entry = next(d for d in cert["diff"] if d["kind"] == "pin_mismatch")
        assert entry["net"] == "MID"
        assert ("R2", "1") in entry["extra_pins"]

    def test_invalid_spec_error_envelope_no_file(self, tmp_path):
        out = tmp_path / "x.kicad_sch"
        env = generate_schematic({"schema": "nope"}, out)
        assert env["ok"] is False
        assert env["errors"]
        assert not out.exists()

    def test_unwritable_out_error_envelope(self, tmp_path):
        env = generate_schematic(TWO_RES, tmp_path / "no_dir" / "x.kicad_sch")
        assert env["ok"] is False
        assert "写出失败" in env["errors"][0]

    def test_certificate_false_skips_readback(self, tmp_path):
        out = tmp_path / "x.kicad_sch"
        env = generate_schematic(TWO_RES, out, certificate=False)
        assert env["ok"] is True
        assert env["certificate"] is None


# ---------------------------------------------------------------------------
# run_erc 子进程封装（subprocess 全 mock；真机=runs/ 冒烟证据件）
# ---------------------------------------------------------------------------


def _mock_cli(monkeypatch, returncode=5, rpt_text="", stdout="", stderr=""):
    """钉住 kicad-cli 探测与 subprocess.run（单测零真机）。"""
    import rfauto.service.layout_step_service as step_svc

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=returncode, stdout=stdout,
                               stderr=stderr)

    monkeypatch.setattr(step_svc, "resolve_kicad_cli",
                        lambda p=None: Path("C:/fake/kicad-cli.exe"))
    monkeypatch.setattr("rfauto.service.kicad_sch_service.subprocess.run",
                        fake_run)
    return calls


class TestRunErc:
    def test_exit5_violations_ok_envelope(self, tmp_path, monkeypatch):
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        rpt = tmp_path / "x.erc.rpt"
        rpt.write_text((_FIXTURES / "erc_report_errors.rpt")
                       .read_text(encoding="utf-8"), encoding="utf-8")
        calls = _mock_cli(monkeypatch, returncode=5)
        env = run_erc(sch)
        assert env["ok"] is True  # 违例不是服务失败
        assert env["exit_code"] == 5
        assert env["error_count"] == 2
        assert env["warning_count"] == 6
        assert env["report_path"] == str(rpt)
        assert "--exit-code-violations" in calls[0]
        assert calls[0][1:3] == ["sch", "erc"]

    def test_exit0_clean(self, tmp_path, monkeypatch):
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        (tmp_path / "x.erc.rpt").write_text(
            "ERC report\n\n ** ERC messages: 0  Errors 0  Warnings 0\n",
            encoding="utf-8")
        _mock_cli(monkeypatch, returncode=0)
        env = run_erc(sch)
        assert env["ok"] is True
        assert env["error_count"] == 0
        assert env["warning_count"] == 0

    def test_exit3_load_failure_error_envelope(self, tmp_path, monkeypatch):
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        _mock_cli(monkeypatch, returncode=3, stderr="加载原理图失败")
        env = run_erc(sch)
        assert env["ok"] is False
        assert env["exit_code"] == 3
        assert "加载失败" in env["errors"][0]

    def test_cli_missing_skipped(self, tmp_path, monkeypatch):
        import rfauto.service.layout_step_service as step_svc
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        monkeypatch.setattr(step_svc, "resolve_kicad_cli",
                            lambda p=None: None)
        env = run_erc(sch)
        assert env["ok"] is True
        assert env["skipped"] is True
        assert "kicad-cli" in env["reason"]

    def test_timeout_error_envelope(self, tmp_path, monkeypatch):
        import subprocess as sp_mod
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        _mock_cli(monkeypatch)

        def fake_run(args, **kwargs):
            raise sp_mod.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

        monkeypatch.setattr("rfauto.service.kicad_sch_service.subprocess.run",
                            fake_run)
        env = run_erc(sch, timeout_s=1.0)
        assert env["ok"] is False
        assert "超时" in env["errors"][0]

    def test_missing_sch_file_error(self, tmp_path):
        env = run_erc(tmp_path / "ghost.kicad_sch")
        assert env["ok"] is False
        assert "不存在" in env["errors"][0]

    def test_parse_failure_degrades_not_fabricates(self, tmp_path,
                                                   monkeypatch):
        """rc=5 但报告缺汇总行 → error 降级（不伪造计数，#331 族）。"""
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        (tmp_path / "x.erc.rpt").write_text("no summary at all\n",
                                            encoding="utf-8")
        _mock_cli(monkeypatch, returncode=5)
        env = run_erc(sch)
        assert env["ok"] is False
        assert env["exit_code"] == 5
        assert env["error_count"] is None

    def test_without_violations_flag(self, tmp_path, monkeypatch):
        sch = tmp_path / "x.kicad_sch"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        (tmp_path / "x.erc.rpt").write_text(
            "** ERC messages: 0  Errors 0  Warnings 0\n", encoding="utf-8")
        calls = _mock_cli(monkeypatch, returncode=0)
        env = run_erc(sch, exit_code_violations=False)
        assert env["ok"] is True
        assert "--exit-code-violations" not in calls[0]
