"""service/schematic_read_service.py（T-Q6 实体级读入口）测试。

.sch 夹具=T-Q22 生成器产物（双证：本文件内同 spec 重渲染逐字节对拍夹具）；
.kicad_pcb BOM 夹具=手写最小板。全离线零网络零真机，确定性双跑钉死。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.adapters.kicad_sch_gen import GenComponent, GenNet, render_schematic
from rfauto.service.schematic_read_service import bom_overview, schematic_overview

_FIXTURES = Path(__file__).parent / "fixtures"
_SCH = _FIXTURES / "schematic_read" / "amp_chain.kicad_sch"
_PCB = _FIXTURES / "schematic_read" / "bom_board.kicad_pcb"

# 与 runs/aurora_q/qw71_gen_fixture.py 同一 spec（夹具双证源）
_COMPS = [
    GenComponent(ref="R1", value="10k", lib_id="Device:R",
                 footprint="Resistor_SMD:R_0603"),
    GenComponent(ref="R2", value="22k", lib_id="Device:R",
                 footprint="Resistor_SMD:R_0603"),
    GenComponent(ref="C1", value="100n", lib_id="Device:C",
                 footprint="Capacitor_SMD:C_0603"),
    GenComponent(ref="Q1", value="2N3904",
                 lib_id="Transistor_BJT:2N3904",
                 footprint="Package_TO_SOT_THT:TO-92_Inline",
                 pins=("1", "2", "3")),
]
_NETS = [
    GenNet(name="VIN", pins=(("R1", "1"),)),
    GenNet(name="MID", pins=(("R1", "2"), ("C1", "1"), ("Q1", "1"))),
    GenNet(name="GND", pins=(("C1", "2"), ("Q1", "3"))),
    GenNet(name="OUT", pins=(("R2", "1"),)),
]


def _j(env: dict) -> str:
    return json.dumps(env, ensure_ascii=False)


class TestSchematicOverview:
    def test_ok_envelope_and_sheet_params(self):
        out = schematic_overview(_SCH)
        assert out["ok"] is True
        assert out["kind"] == "kicad_sch"
        assert out["schema_version"] == "1.0"
        # 图纸参数：token 原文（生成器钉 20250114/A4/rfauto）
        assert out["sheet"]["version"] == "20250114"
        assert out["sheet"]["generator"] == "rfauto"
        assert out["sheet"]["paper"] == "A4"
        assert out["sheet"]["uuid"]  # 根 uuid 存在（uuid5 内容键）
        assert out["sheet"]["generator_version"] == "1.0"

    def test_instances_entity_list(self):
        out = schematic_overview(_SCH)
        insts = {i["ref"]: i for i in out["instances"]}
        assert set(insts) == {"R1", "R2", "C1", "Q1"}
        assert insts["R1"]["value"] == "10k"
        assert insts["R1"]["lib_id"] == "Device:R"
        assert insts["R1"]["footprint"] == "Resistor_SMD:R_0603"
        assert insts["R1"]["at"] == ["50.8", "50.8"]  # 首槽位原文
        assert insts["Q1"]["lib_id"] == "Transistor_BJT:2N3904"
        assert out["stats"]["n_instances"] == 4
        assert out["stats"]["n_lib_symbols"] == 3

    def test_nets_connectivity(self):
        """连通性=复用 readback_nets（union-find）：net→pins 对拍 spec。"""
        out = schematic_overview(_SCH)
        nets = {k: {tuple(p) for p in v} for k, v in out["nets"].items()}
        assert nets == {
            "VIN": {("R1", "1")},
            "MID": {("R1", "2"), ("C1", "1"), ("Q1", "1")},
            "GND": {("C1", "2"), ("Q1", "3")},
            "OUT": {("R2", "1")},
        }
        assert out["stats"]["n_nets"] == 4

    def test_unnamed_pins_and_labels(self):
        out = schematic_overview(_SCH)
        # Q1.2/R2.2 不入任何 net（spec 声明）——如实信号非缺陷
        assert out["unnamed_pins"] == [["Q1", "2"], ["R2", "2"]]
        # 每 net 引脚一 stub 一 label：VIN1+MID3+GND2+OUT1=7
        assert out["stats"]["n_labels_local"] == 7
        assert out["stats"]["n_wires"] == 7
        assert out["labels"]["local_by_name"] == {
            "GND": 2, "MID": 3, "OUT": 1, "VIN": 1}
        # 自产文件无 global/hierarchical label（如实 0）
        assert out["labels"]["n_global"] == 0
        assert out["labels"]["n_hierarchical"] == 0

    def test_fixture_is_generator_output_double_evidence(self):
        """夹具=生成器产物（双证）：同 spec 重渲染与夹具逐字节同。"""
        out = schematic_overview(_SCH)
        assert out["ok"] is True
        assert _SCH.read_text(encoding="utf-8") == render_schematic(
            _COMPS, _NETS)

    def test_double_run_byte_identical(self):
        a = _j(schematic_overview(_SCH))
        b = _j(schematic_overview(_SCH))
        assert a == b

    def test_bad_root_rejected(self, tmp_path: Path):
        bad = tmp_path / "sch_as_pcb.kicad_sch"
        bad.write_text("(kicad_pcb (version 20241229))\n", encoding="utf-8")
        out = schematic_overview(bad)
        assert out["ok"] is False
        assert "kicad_sch" in out["errors"][0]

    def test_broken_sexpr_rejected(self, tmp_path: Path):
        bad = tmp_path / "broken.kicad_sch"
        bad.write_text("(kicad_sch (version 20250114)\n", encoding="utf-8")
        out = schematic_overview(bad)
        assert out["ok"] is False
        assert "s-expr 解析失败" in out["errors"][0]

    def test_missing_file_rejected(self, tmp_path: Path):
        out = schematic_overview(tmp_path / "nope.kicad_sch")
        assert out["ok"] is False
        assert "不可读" in out["errors"][0]


class TestBomOverview:
    def test_per_ref_fields_property_and_fallback(self):
        """R1 有 Footprint 属性（路径 1 原文）；R2/C1 无属性回退 lib_id。"""
        out = bom_overview(_PCB)
        assert out["ok"] is True
        assert out["kind"] == "bom"
        assert out["schema_version"] == "1.0"
        assert out["per_ref"]["R1"] == {
            "value": "10k",
            "footprint": "Resistor_SMD:R_0805",  # 属性原文（≠lib_id 判别）
            "lib_id": "Resistor_SMD:R_0603",
        }
        assert out["per_ref"]["R2"]["footprint"] == "Resistor_SMD:R_0603"
        assert out["per_ref"]["R2"]["lib_id"] == "Resistor_SMD:R_0603"
        assert out["per_ref"]["C1"]["footprint"] == "Capacitor_SMD:C_0603"

    def test_by_value_groups_and_total(self):
        out = bom_overview(_PCB)
        assert out["by_value"] == {"": 1, "10k": 2}
        assert out["n_components"] == 3

    def test_missing_value_verbatim_empty(self):
        """C1 无 Value 属性 → 空串如实（不猜），且入 by_value 空串组。"""
        out = bom_overview(_PCB)
        assert out["per_ref"]["C1"]["value"] == ""

    def test_double_run_byte_identical(self):
        a = _j(bom_overview(_PCB))
        b = _j(bom_overview(_PCB))
        assert a == b

    def test_bad_file_rejected(self, tmp_path: Path):
        bad1 = tmp_path / "pcb_as_sch.kicad_pcb"
        bad1.write_text("(kicad_sch (version 20250114))\n", encoding="utf-8")
        out = bom_overview(bad1)
        assert out["ok"] is False
        assert "kicad_pcb" in out["errors"][0]
        bad2 = tmp_path / "broken.kicad_pcb"
        bad2.write_text("(kicad_pcb (version 20241229)\n", encoding="utf-8")
        assert bom_overview(bad2)["ok"] is False

    def test_duplicate_ref_first_wins(self, tmp_path: Path):
        p = tmp_path / "dup.kicad_pcb"
        p.write_text(
            "(kicad_pcb (version 20241229)\n"
            '  (footprint "Device:R" (property "Reference" "R1" (at 0 0))\n'
            '    (property "Value" "1k" (at 0 0)))\n'
            '  (footprint "Device:R" (property "Reference" "R1" (at 0 0))\n'
            '    (property "Value" "2k" (at 0 0)))\n'
            ")\n", encoding="utf-8")
        out = bom_overview(p)
        assert out["ok"] is True
        assert out["n_components"] == 1
        assert out["per_ref"]["R1"]["value"] == "1k"  # 首个保留不覆盖
        assert out["n_duplicate_refs"] == 1

    def test_missing_reference_counted(self, tmp_path: Path):
        p = tmp_path / "noref.kicad_pcb"
        p.write_text(
            "(kicad_pcb (version 20241229)\n"
            '  (footprint "Device:R" (property "Value" "1k" (at 0 0)))\n'
            ")\n", encoding="utf-8")
        out = bom_overview(p)
        assert out["ok"] is True
        assert "" in out["per_ref"]  # 空串键如实入列
        assert out["n_missing_reference"] == 1
        assert out["per_ref"][""]["value"] == "1k"

    def test_missing_file_rejected(self, tmp_path: Path):
        assert bom_overview(tmp_path / "nope.kicad_pcb")["ok"] is False


@pytest.mark.parametrize("entry", [schematic_overview, bom_overview])
def test_wrong_format_cross_rejected(entry, tmp_path: Path):
    """负例统一面：把对方格式的根表达式喂进来必须显式报错不静默。"""
    p = tmp_path / "cross.txt"
    p.write_text("(completely (unrelated) root)\n", encoding="utf-8")
    out = entry(p)
    assert out["ok"] is False
