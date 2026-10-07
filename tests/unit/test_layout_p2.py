"""F-I P2 定向门：叠层多层化（多层介质+KiCad dielectrics 全层消费）+ 端口三来源。

判据映射（研究扩充 round5 §二 F-I P2 + 任务书交付骨架）：

- **单层退化恒等式（字节钉）**：render_substrate_block 单介质层 + 旧路径符号
  约定 → 与 openems_templates guided 分支基板块逐字节相同；金色文本的无换行
  组件在模板源码中逐字锚定（防转录漂移，#329 旋钮纪律的新增路径版——
  既有模板零改动由"新增文件"构造性成立，钉住的是新通用路径的退化行为）；
- **三来源一致性**：marker vs yaml 对同一简单版图逐位一致（交叉验证）；
- **端口冲突负例**：marker vs yaml 不一致 → 显式 ValueError 不静默；
- **启发式合成几何回收**：已知版图的开路端点/方向/宽度按解析值回收
  （T 结/共点相接/自闭合环三类拓扑）；
- **KiCad 全层消费**：4 层板全介质读取（#210 层 id 不写死）+ 缺 epsilon_r
  严格显错 + 真机 demo 板 skipif 支路。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from rfauto.adapters import openems_templates
from rfauto.adapters.kicad_extract import (
    DEMO_ER,
    DEMO_TAN_D,
    KICAD_PYTHON,
    build_demo_cpwg_pcb,
)
from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
)
from rfauto.adapters.layout_ports import (
    COMPOSE_PIN_KEYS,
    DIR_DOT_MIN,
    PORT_SOURCES,
    PORT_TYPES,
    POSITION_TOL_M,
    WIDTH_RTOL,
    LayoutPort,
    load_port_table,
    port_table_from_records,
    ports_from_marker_layer,
    ports_from_open_ends,
    resolve_ports,
)
from rfauto.adapters.layout_stack import RFRouteLayer, RFStackup
from rfauto.adapters.layout_substrate import (
    MaterialProps,
    plan_substrate_boxes,
    render_substrate_block,
    render_substrate_mesh_block,
    resolve_material_props,
    stackup_from_kicad_pcb,
    stackup_from_kicad_text,
    validate_stackup_z_order,
)

# ---------------------------------------------------------------------------
# 公共构造器
# ---------------------------------------------------------------------------

_H_SUB = 5.08e-4  # 0.508mm（米）


def _mm(x: float, y: float) -> tuple[float, float]:
    """mm 字面量 → 米（与适配器同式换算，保证逐位可比）。"""
    return (x * 1e-3, y * 1e-3)


KICAD_AVAILABLE = Path(KICAD_PYTHON).exists()
requires_kicad = pytest.mark.skipif(
    not KICAD_AVAILABLE, reason="KiCad Python 不存在（离线降级，同 test_kicad_extract 口径）")


def _diel(name: str, zmin_m: float, thickness_m: float, *, material: str = "fr4_epoxy") -> RFRouteLayer:
    return RFRouteLayer(name=name, zmin_m=zmin_m, thickness_m=thickness_m,
                        material=material, kind="dielectric")


def _metal(name: str, zmin_m: float, thickness_m: float, kind: str = "signal") -> RFRouteLayer:
    return RFRouteLayer(name=name, zmin_m=zmin_m, thickness_m=thickness_m,
                        material="copper", kind=kind)


def _single_diel_stackup() -> RFStackup:
    return RFStackup(name="single", layers=(_diel("FR4", 0.0, _H_SUB),))


def _trace(points, width_mm: float = 0.5, layer: str = "F.Cu") -> LayoutPath:
    return LayoutPath(points=tuple(points), width_mm=width_mm, layer=layer)


# ---------------------------------------------------------------------------
# 叠层 z 序校验（多层 dielectric + 导体层序语义）
# ---------------------------------------------------------------------------


class TestStackupZOrder:
    def test_single_dielectric_report_sorted(self) -> None:
        report = validate_stackup_z_order(_single_diel_stackup())
        assert report["layers"] == [
            {"name": "FR4", "kind": "dielectric", "z_lo_m": 0.0, "z_hi_m": _H_SUB}]
        assert report["gaps"] == [] and report["n_thick_conductors"] == 0

    def test_overlap_raises_with_pair_named(self) -> None:
        bad = RFStackup(layers=(
            _diel("d1", 0.0, 1e-3),
            _diel("d2", 0.5e-3, 1e-3),  # 与 d1 重叠 0.5mm
        ))
        with pytest.raises(ValueError, match="z 序冲突"):
            validate_stackup_z_order(bad)

    def test_zero_thickness_conductor_on_interface_legal(self) -> None:
        stackup = RFStackup(layers=(
            _diel("d1", 0.0, _H_SUB),
            _metal("GND", _H_SUB, 0.0, kind="ground"),
        ))
        report = validate_stackup_z_order(stackup)
        assert report["n_thick_conductors"] == 0  # 零厚片不参与交叠判定
        assert [lay["name"] for lay in report["layers"]] == ["d1", "GND"]  # 按 zmin 升序

    def test_air_gap_reported_not_raised(self) -> None:
        stackup = RFStackup(layers=(
            _diel("d1", 0.0, 0.5e-3),
            _diel("d2", 1.0e-3, 0.5e-3),  # 0.5mm 空气隙（openEMS 背景即空气）
        ))
        report = validate_stackup_z_order(stackup)
        assert len(report["gaps"]) == 1
        assert report["gaps"][0]["below"] == "d1" and report["gaps"][0]["above"] == "d2"

    def test_zero_thickness_dielectric_raises(self) -> None:
        with pytest.raises(ValueError, match="零厚介质"):
            validate_stackup_z_order(RFStackup(layers=(_diel("d1", 0.0, 0.0),)))

    def test_missing_props_lists_all_missing_layers(self) -> None:
        stackup = RFStackup(layers=(
            _diel("d1", 0.0, 0.5e-3),
            _diel("d2", 0.5e-3, 0.5e-3),
            _metal("GND", 1.0e-3, 0.0, kind="ground"),
        ))
        with pytest.raises(ValueError, match=r"缺材料数值定义.*d1.*d2") as exc:
            resolve_material_props(stackup, {})
        assert "d1" in str(exc.value) and "d2" in str(exc.value)

    def test_props_unknown_key_raises(self) -> None:
        stackup = RFStackup(layers=(_diel("FR4", 0.0, _H_SUB),))
        with pytest.raises(ValueError, match="未被介质层引用"):
            resolve_material_props(stackup, {"FR4": MaterialProps(4.4, 0.02),
                                             "FR5": MaterialProps(4.5, 0.02)})

    def test_all_metal_stackup_no_dielectric_raises(self) -> None:
        stackup = RFStackup(layers=(
            _metal("F.Cu", 0.0, 0.0), _metal("B.Cu", 1e-3, 0.0, kind="ground")))
        with pytest.raises(ValueError, match="不含介质层"):
            resolve_material_props(stackup, {})


# ---------------------------------------------------------------------------
# 多基板段渲染（单层退化=旧路径逐字节；多层=Box 串联）
# ---------------------------------------------------------------------------

#: 旧路径金色文本（openems_templates render_script 基板块 guided 分支，#329 锚）。
_LEGACY_COMMENT = "# 基板延伸到侧边界（guided；官方口径：无板边衍射）；地面 = z-min PEC 边界"
_LEGACY_BLOCK = (
    _LEGACY_COMMENT + "\n"
    'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
    "                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)\n"
    "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB), priority=0)\n"
)
#: 金色文本组件（不含换行，可逐字出现在模板源码里；防转录漂移锚）。
_LEGACY_SOURCE_PIECES = (
    "# 基板延伸到侧边界（guided；官方口径：无板边衍射）；",
    "地面 = z-min PEC 边界",
    'sub = CSX.AddMaterial("substrate", epsilon=ER,',
    "kappa=TAND * 2 * np.pi * F0 * ",
    "8.854187817e-12 * ER)",
    "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB), priority=0)",
)


class TestSubstrateRender:
    def _legacy_args(self) -> dict[str, object]:
        return {
            "er_expr": lambda _p: "ER",
            "tand_expr": lambda _p: "TAND",
            "freq_expr": "F0",
            "z_literal": {0.0: "0", _H_SUB: "H_SUB"}.__getitem__,
            "header_comment": _LEGACY_COMMENT,
        }

    def test_single_layer_byte_pin_legacy_block(self) -> None:
        """单层退化恒等式：缺省坐标符号 + 旧符号约定 → 与旧路径逐字节同。"""
        rendered = render_substrate_block(
            _single_diel_stackup(), {"FR4": MaterialProps(4.4, 0.01)}, **self._legacy_args())
        assert rendered == _LEGACY_BLOCK
        # 源码锚定：金色文本组件逐字出现在 openems_templates 源里（防转录漂移）
        source = Path(openems_templates.__file__).read_text(encoding="utf-8")
        for piece in _LEGACY_SOURCE_PIECES:
            assert piece in source

    def test_multilayer_two_dielectrics_box_chain(self) -> None:
        z2 = _H_SUB
        z3 = z2 + 2e-4
        stackup = RFStackup(layers=(
            _diel("CORE", 0.0, _H_SUB),
            _diel("PP", z2, 2e-4, material="prepreg"),
            _metal("F.Cu", z3, 0.0),
        ))
        props = {"CORE": MaterialProps(4.4, 0.02), "PP": MaterialProps(3.66, 0.03)}
        boxes = plan_substrate_boxes(stackup, props)
        assert [(b["prop"], b["layer"], b["z_lo_m"], b["z_hi_m"]) for b in boxes] == [
            ("substrate", "CORE", 0.0, _H_SUB), ("substrate_2", "PP", z2, z3)]
        rendered = render_substrate_block(stackup, props, z_literal=repr)
        assert rendered.count("CSX.AddMaterial(") == 2
        assert 'CSX.AddMaterial("substrate_2"' in rendered
        assert rendered.count("AddBox((-BOARD, -BOARD,") == 2
        assert f"0.0), (BOARD, BOARD, {z2!r})" in rendered
        assert f"{z2!r}), (BOARD, BOARD, {z3!r})" in rendered
        report = validate_stackup_z_order(stackup)
        assert report["n_thick_conductors"] == 0  # F.Cu 零厚片合法落在界面上

    def test_shared_material_single_addmaterial(self) -> None:
        stackup = RFStackup(layers=(
            _diel("d1", 0.0, 0.5e-3),
            _diel("d2", 0.5e-3, 0.5e-3),  # 同 er/tanδ → 同材料组
        ))
        props = {"d1": MaterialProps(4.4, 0.02), "d2": MaterialProps(4.4, 0.02)}
        rendered = render_substrate_block(stackup, props, z_literal=repr)
        assert rendered.count("CSX.AddMaterial(") == 1  # 一份定义
        assert rendered.count("AddBox(") == 2  # 两条 Box 串联
        assert "substrate_2" not in rendered

    def test_numeric_default_emission_self_contained(self) -> None:
        rendered = render_substrate_block(_single_diel_stackup(),
                                          {"FR4": MaterialProps(4.4, 0.01)})
        assert 'epsilon=4.4,' in rendered
        assert "kappa=0.01 * 2 * np.pi * F0 * 8.854187817e-12 * 4.4)" in rendered
        assert f"0.0), (BOARD, BOARD, {_H_SUB!r})" in rendered

    def test_render_deterministic_sha256(self) -> None:
        import hashlib

        args = self._legacy_args()
        props = {"FR4": MaterialProps(4.4, 0.01)}
        h1 = hashlib.sha256(render_substrate_block(_single_diel_stackup(), props, **args).encode())
        h2 = hashlib.sha256(render_substrate_block(_single_diel_stackup(), props, **args).encode())
        assert h1.hexdigest() == h2.hexdigest()

    def test_plan_sorted_from_unordered_input(self) -> None:
        stackup = RFStackup(layers=(
            _diel("top", 1e-3, 0.5e-3),
            _diel("bot", 0.0, 0.5e-3),
        ))
        props = {"top": MaterialProps(4.4, 0.02), "bot": MaterialProps(4.4, 0.02)}
        boxes = plan_substrate_boxes(stackup, props)
        assert [b["layer"] for b in boxes] == ["bot", "top"]  # 发射序=zmin 升序
        # 同 (er, tanδ) 材料组共享同一 prop（一份定义两条 Box）
        assert all(b["prop"] == "substrate" for b in boxes)

    def test_mesh_block_faces_sorted_and_near_merged(self) -> None:
        z_slip = 1e-3 + 1e-15  # 界面近重合（ulp 级）→ 必须合并（#152 族）
        stackup = RFStackup(layers=(
            _diel("d1", 0.0, 1e-3),
            _diel("d2", z_slip, 1e-3),
        ))
        props = {"d1": MaterialProps(4.4, 0.02), "d2": MaterialProps(4.4, 0.02)}
        block = render_substrate_mesh_block(stackup, props)
        assert block == (
            f'mesh.AddLine("z", np.array([{0.0!r}, {1e-3!r}, {z_slip + 1e-3!r}]))\n'
            'mesh.SmoothMeshLines("z", BASE)\n'
        )
        assert block.count("AddLine") == 1  # 近重合界面合并成单条数组线


# ---------------------------------------------------------------------------
# KiCad dielectrics 全层消费（.kicad_pcb 文本解析；#210 层 id 不写死）
# ---------------------------------------------------------------------------

_FOUR_LAYER_PCB = """(kicad_pcb
  (general (thickness 0.778))
  (setup
    (stackup
      (layer "F.SilkS" (type "Top Silk"))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 0.508) (epsilon_r 4.6) (loss_tangent 0.02))
      (layer "dielectric 2" (type "prepreg") (thickness 0.2) (epsilon_r 4.2) (loss_tangent 0.03))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (copper_finish "None")
      (dielectric_constraints no)
    )
  )
)
"""


class TestKiCadStackup:
    def test_four_layer_full_parse_bottom_up_stacking(self) -> None:
        out = stackup_from_kicad_text(_FOUR_LAYER_PCB)
        stackup = out["stackup"]
        assert [lay.name for lay in stackup.layers] == [
            "B.Cu", "dielectric 2", "dielectric 1", "F.Cu"]  # 文件序反转=自板底向上
        assert [lay.kind for lay in stackup.layers] == [
            "signal", "dielectric", "dielectric", "signal"]
        assert [lay.material for lay in stackup.layers] == [
            "copper", "prepreg", "core", "copper"]  # 层 id 不写死：材料记 type 原文
        z_b = 0.035 * 1e-3
        z_pp = z_b + 0.2 * 1e-3
        z_core = z_pp + 0.508 * 1e-3
        assert [lay.zmin_m for lay in stackup.layers] == pytest.approx(
            [0.0, z_b, z_pp, z_core], rel=0.0, abs=1e-15)
        assert out["material_props"].keys() == {"dielectric 1", "dielectric 2"}  # 全层消费
        assert out["material_props"]["dielectric 1"].epsilon_r == 4.6
        assert out["material_props"]["dielectric 2"].loss_tangent == 0.03
        assert out["stats"]["board_thickness_m"] == pytest.approx(0.778e-3)
        assert out["stats"]["n_copper"] == 2 and out["stats"]["n_dielectrics"] == 2

    def test_missing_epsilon_strict_raises(self) -> None:
        text = _FOUR_LAYER_PCB.replace("(epsilon_r 4.2) ", "")
        with pytest.raises(ValueError, match="epsilon_r"):
            stackup_from_kicad_text(text)
        # 宽松档：缺 er 层不进 props（下游 resolve_material_props 二次显错）
        out = stackup_from_kicad_text(text, require_epsilon_r=False)
        assert "dielectric 2" not in out["material_props"]
        assert "dielectric 1" in out["material_props"]

    def test_non_conductive_layers_skipped_and_counted(self) -> None:
        out = stackup_from_kicad_text(_FOUR_LAYER_PCB)
        skipped = out["stats"]["skipped_layers"]
        assert any(name.startswith("F.SilkS") for name in skipped)
        assert all(name.split("(")[0] != "F.Cu" for name in skipped)
        assert all(lay.name != "F.SilkS" for lay in out["stackup"].layers)

    def test_copper_kind_override_by_layer_name(self) -> None:
        out = stackup_from_kicad_text(_FOUR_LAYER_PCB, copper_kinds={"B.Cu": "ground"})
        by_name = {lay.name: lay for lay in out["stackup"].layers}
        assert by_name["B.Cu"].kind == "ground"
        assert by_name["F.Cu"].kind == "signal"  # 缺省 signal

    def test_copper_kind_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="不存在的铜层"):
            stackup_from_kicad_text(_FOUR_LAYER_PCB, copper_kinds={"B.Cux": "ground"})

    def test_missing_thickness_raises(self) -> None:
        text = _FOUR_LAYER_PCB.replace(
            '(layer "F.Cu" (type "copper") (thickness 0.035))',
            '(layer "F.Cu" (type "copper"))')
        assert text != _FOUR_LAYER_PCB  # 替换必须命中（#108 家族：防静默不替换）
        with pytest.raises(ValueError, match="thickness"):
            stackup_from_kicad_text(text)

    def test_no_dielectric_raises(self) -> None:
        text = """(kicad_pcb (setup
          (stackup
            (layer "F.Cu" (type "copper") (thickness 0.035))
            (layer "B.Cu" (type "copper") (thickness 0.035))
          )))"""
        with pytest.raises(ValueError, match="未解析出介质层"):
            stackup_from_kicad_text(text)

    def test_no_stackup_section_raises(self) -> None:
        with pytest.raises(ValueError, match="无 \\(stackup\\) 节"):
            stackup_from_kicad_text("(kicad_pcb (setup (pad_to_mask_clearance 0)))")

    def test_file_entry_roundtrip(self, tmp_path: Path) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text(_FOUR_LAYER_PCB, encoding="utf-8")
        out = stackup_from_kicad_pcb(pcb)
        assert len(out["stackup"].layers) == 4

    def test_loss_tangent_defaulted_reported(self) -> None:
        text = _FOUR_LAYER_PCB.replace(" (loss_tangent 0.03)", "")
        out = stackup_from_kicad_text(text)
        assert out["stats"]["loss_tangent_defaulted"] == ["dielectric 2"]
        assert out["material_props"]["dielectric 2"].loss_tangent == 0.0

    @requires_kicad
    def test_demo_board_integration(self, tmp_path: Path) -> None:
        out_path = tmp_path / "demo.kicad_pcb"
        build = build_demo_cpwg_pcb(out_path)
        if not build.get("success"):
            pytest.skip("KiCad demo 板构建失败（子进程侧问题，离线用例已覆盖解析器）")
        out = stackup_from_kicad_pcb(out_path)
        assert out["stats"]["n_dielectrics"] == 1
        assert out["stats"]["n_copper"] == 2
        props = out["material_props"]["dielectric 1"]
        assert props.epsilon_r == DEMO_ER and props.loss_tangent == DEMO_TAN_D
        assert [lay.name for lay in out["stackup"].layers] == ["B.Cu", "dielectric 1", "F.Cu"]


# ---------------------------------------------------------------------------
# 统一端口 schema（compose pin 契约对齐）
# ---------------------------------------------------------------------------


class TestPortSchema:
    def test_pin_dict_keys_match_compose_contract(self) -> None:
        port = LayoutPort(port_id="P1", position_m=(0.0, 0.0), direction=(1.0, 0.0),
                          width_m=5e-4, layer="F.Cu")
        pin = port.to_pin_dict()
        assert set(pin) == set(COMPOSE_PIN_KEYS)
        assert pin["pin_id"] == "P1" and pin["position"] == [0.0, 0.0]
        assert pin["direction"] == [1.0, 0.0] and pin["width_m"] == 5e-4
        assert pin["ref_plane_offset_m"] == 0.0 and pin["n_modes"] == 1
        assert pin["cross_section"] == {"layer": "F.Cu"}
        # 机器可读交叉锚：类型值域 ⊆ compose PIN_PORT_TYPES（对齐不耦合）
        from rfauto.core.compose.layout_netlist import PIN_PORT_TYPES

        assert set(PORT_TYPES) <= set(PIN_PORT_TYPES)

    def test_direction_normalized_and_negatives(self) -> None:
        port = LayoutPort(port_id="P", position_m=(0.0, 0.0), direction=(3.0, 4.0),
                          width_m=1e-3)
        assert port.direction == (0.6, 0.8)  # 构造期归一
        with pytest.raises(ValueError, match="零向量"):
            LayoutPort(port_id="P", position_m=(0.0, 0.0), direction=(0.0, 0.0), width_m=1e-3)
        with pytest.raises(ValueError, match="必须为数值"):
            LayoutPort(port_id="P", position_m=(True, 0.0), direction=(1.0, 0.0), width_m=1e-3)
        with pytest.raises(ValueError, match="port_type"):
            LayoutPort(port_id="P", position_m=(0.0, 0.0), direction=(1.0, 0.0),
                       width_m=1e-3, port_type="waveguide")  # P3+ 预留，显式拒绝
        with pytest.raises(ValueError, match="width_m"):
            LayoutPort(port_id="P", position_m=(0.0, 0.0), direction=(1.0, 0.0), width_m=0.0)


# ---------------------------------------------------------------------------
# 来源 A：标记层几何
# ---------------------------------------------------------------------------


class TestMarkerPorts:
    def test_marker_segment_port_geometry(self) -> None:
        layout = Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0))),
            _trace(((0.0, 0.0), (1.0, 0.0)), layer="PORT"),
        ))
        ports, stats = ports_from_marker_layer(layout, "PORT")
        assert stats["n_ports"] == 1 and stats["skipped"] == []
        port = ports[0]
        assert port.port_id == "P1" and port.source == "marker"
        assert port.position_m == (0.0, 0.0)  # 第 1 点=端口位置
        assert port.direction == (1.0, 0.0)  # 方向→第 2 点（指向结构内）
        assert port.width_m == 0.5 * 1e-3 and port.layer == "PORT"

    def test_marker_skips_non_segment_items(self) -> None:
        layout = Layout(items=(
            _trace(((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)), layer="PORT"),  # 3 点：非标记
            LayoutPolygon(points=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), layer="PORT"),
            LayoutCircle(center=(5.0, 5.0), radius_mm=0.5, layer="PORT"),
        ))
        ports, stats = ports_from_marker_layer(layout, "PORT")
        assert ports == []
        assert len(stats["skipped"]) == 3
        assert {s["kind"] for s in stats["skipped"]} == {"path", "LayoutPolygon", "LayoutCircle"}


# ---------------------------------------------------------------------------
# 来源 B：YAML 显式表
# ---------------------------------------------------------------------------


class TestYamlPorts:
    def test_yaml_file_roundtrip(self, tmp_path: Path) -> None:
        table = tmp_path / "ports.yaml"
        table.write_text(
            "ports:\n"
            "  - port_id: in\n"
            "    position_mm: [0.0, 0.0]\n"
            "    direction: [1, 0]\n"
            "    width_mm: 0.5\n"
            "  - port_id: out\n"
            "    position_mm: [10.0, 0.0]\n"
            "    direction: [-1, 0]\n"
            "    width_mm: 0.5\n"
            "    port_type: msl\n"
            "    layer: F.Cu\n",
            encoding="utf-8",
        )
        ports = load_port_table(table)
        assert [p.port_id for p in ports] == ["in", "out"]  # 记录顺序保持
        assert ports[1].port_type == "msl" and ports[1].layer == "F.Cu"
        assert ports[0].position_m == (0.0, 0.0) and ports[0].width_m == 0.5 * 1e-3  # mm→m
        assert ports[1].direction[0] < 0.0

    def test_records_validation_negatives(self) -> None:
        ok = {"port_id": "a", "position_mm": [0.0, 0.0], "direction": [1, 0], "width_mm": 0.5}
        with pytest.raises(ValueError, match="缺字段"):
            port_table_from_records([{"port_id": "a"}])
        with pytest.raises(ValueError, match="重复"):
            port_table_from_records([ok, dict(ok)])
        with pytest.raises(ValueError, match="零向量"):
            port_table_from_records([dict(ok, direction=[0, 0])])
        assert port_table_from_records([]) == []  # 空表合法（显式来源空=0 端口）

    def test_yaml_bad_top_level_shape_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="顶层必须是"):
            load_port_table(bad)


# ---------------------------------------------------------------------------
# 来源 C：端点启发式（合成几何回收）
# ---------------------------------------------------------------------------


class TestHeuristicPorts:
    def test_synthetic_recovery_t_junction(self) -> None:
        """T 结：主线两端 + 枝线顶端开路；枝线根被主线抑制。"""
        layout = Layout(items=(
            _trace(((0.0, 0.0), (40.0, 0.0))),
            _trace(((20.0, 0.0), (20.0, 10.0)), width_mm=0.4),
        ))
        ports, stats = ports_from_open_ends(layout, layers=["F.Cu"])
        assert stats["n_open"] == 3 and stats["n_suppressed"] == 1
        assert [(p.position_m, p.direction, p.width_m) for p in ports] == [
            (_mm(0.0, 0.0), (1.0, 0.0), 0.5e-3),
            (_mm(20.0, 10.0), (0.0, -1.0), 0.4e-3),
            (_mm(40.0, 0.0), (-1.0, 0.0), 0.5e-3),
        ]

    def test_shared_endpoint_mutual_suppression(self) -> None:
        """共点相接：两径端点互为对方线段端点 → 双双抑制。"""
        layout = Layout(items=(
            _trace(((0.0, 0.0), (40.0, 0.0))),
            _trace(((40.0, 0.0), (50.0, 5.0))),
        ))
        ports, stats = ports_from_open_ends(layout, layers=["F.Cu"])
        assert stats["n_open"] == 2 and stats["n_suppressed"] == 2
        n = math.hypot(-10.0, -5.0)
        assert [(p.position_m, p.direction) for p in ports] == [
            (_mm(0.0, 0.0), (1.0, 0.0)),
            (_mm(50.0, 5.0), (-10.0 / n, -5.0 / n)),
        ]

    def test_self_closed_loop_no_open(self) -> None:
        """折线自闭合环（首末同点）：两端点均被自身非关联段抑制。"""
        layout = Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0))),
        ))
        ports, stats = ports_from_open_ends(layout)
        assert ports == [] and stats["n_suppressed"] == 2

    def test_layer_filter_scope(self) -> None:
        """层过滤口径：抑制判定同层（跨层几何不互连）；过滤限制候选层集——
        不过滤时标记层线段两端也会被提议（噪声候选）→ 建议只传导电层。"""
        layout = Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0))),
            _trace(((0.0, 0.0), (1.0, 0.0)), layer="PORT"),
        ))
        unfiltered, stats_all = ports_from_open_ends(layout)
        assert stats_all["n_open"] == 4
        assert {p.layer for p in unfiltered} == {"F.Cu", "PORT"}
        filtered, stats_f = ports_from_open_ends(layout, layers=["F.Cu"])
        assert stats_f["n_open"] == 2
        assert {p.layer for p in filtered} == {"F.Cu"}

    def test_polygon_and_via_participate_or_skip(self) -> None:
        """多边形边界参与抑制；via 如实不参与（不崩不猜）。"""
        layout = Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0))),
            LayoutPolygon(points=((10.0, 0.0), (12.0, 0.0), (12.0, 2.0), (10.0, 2.0)),
                          layer="F.Cu"),  # 端点 (10,0) 落在多边形边界上
            LayoutVia(position=(20.0, 20.0), pad_diameter_mm=0.6,
                      drill_diameter_mm=0.3, pad_layer="F.Cu"),
        ))
        ports, stats = ports_from_open_ends(layout)
        assert stats["n_open"] == 1
        assert ports[0].position_m == _mm(0.0, 0.0)


# ---------------------------------------------------------------------------
# 三来源裁决（优先级 + 冲突显错）
# ---------------------------------------------------------------------------


class TestResolvePorts:
    def _layout(self) -> Layout:
        return Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0))),
            _trace(((0.0, 0.0), (1.0, 0.0)), layer="PORT"),
        ))

    def _grounded_layout(self) -> Layout:
        """远端接多边形地（(10,0) 落多边形角点被抑制）→ 导电层唯一开路端 (0,0)。"""
        return Layout(items=(
            _trace(((0.0, 0.0), (10.0, 0.0))),
            LayoutPolygon(points=((10.0, 0.0), (12.0, 0.0), (12.0, 2.0), (10.0, 2.0)),
                          layer="F.Cu"),
            _trace(((0.0, 0.0), (1.0, 0.0)), layer="PORT"),
        ))

    def _yaml_ok(self) -> list[dict]:
        return [{"port_id": "in", "position_mm": [0.0, 0.0], "direction": [1, 0],
                 "width_mm": 0.5}]

    def test_marker_yaml_cross_validation_exact(self) -> None:
        out = resolve_ports(self._layout(), marker_layer="PORT",
                            port_table=self._yaml_ok())
        assert out["source"] == "marker" and out["advisory"] is False  # 优先级
        assert out["cross_check"]["marker_vs_yaml"] == "agree"
        yaml_port = port_table_from_records(self._yaml_ok())[0]
        marker_port = out["ports"][0]
        assert marker_port.position_m == yaml_port.position_m  # 逐位一致
        assert marker_port.direction == yaml_port.direction
        assert marker_port.width_m == yaml_port.width_m
        assert marker_port.to_pin_dict()["port_type"] == yaml_port.to_pin_dict()["port_type"]

    def test_marker_yaml_conflict_raises(self) -> None:
        conflicting = [{"port_id": "in", "position_mm": [0.0, 0.0], "direction": [0, 1],
                        "width_mm": 0.5}]
        with pytest.raises(ValueError, match="端口来源冲突"):
            resolve_ports(self._layout(), marker_layer="PORT", port_table=conflicting)

    def test_no_source_enabled_raises(self) -> None:
        with pytest.raises(ValueError, match="未启用任何一路"):
            resolve_ports(self._layout())

    def test_heuristic_alone_is_advisory_authority(self) -> None:
        out = resolve_ports(self._layout(), heuristic=True, heuristic_layers=["F.Cu"])
        assert out["source"] == "heuristic" and out["advisory"] is True
        assert [p.position_m for p in out["ports"]] == [_mm(0.0, 0.0), _mm(10.0, 0.0)]

    def test_heuristic_report_consistent_with_explicit(self) -> None:
        out = resolve_ports(self._grounded_layout(), marker_layer="PORT",
                            heuristic=True, heuristic_layers=["F.Cu"])
        report = out["cross_check"]["heuristic"]
        assert report is not None
        assert report["n_candidates"] == 1 and report["consistent"] is True
        assert report["unmatched_candidates"] == [] and report["uncovered"] == []

    def test_heuristic_extra_candidate_reported_not_raised(self) -> None:
        layout = self._grounded_layout()
        stub = _trace(((50.0, 50.0), (60.0, 50.0)))
        layout = Layout(items=(*layout.items, stub))  # 额外孤立走线 → 启发式多出候选
        out = resolve_ports(layout, marker_layer="PORT",
                            heuristic=True, heuristic_layers=["F.Cu"])
        report = out["cross_check"]["heuristic"]
        assert out["source"] == "marker"  # 启发式不否决显式来源
        assert report["consistent"] is False
        assert len(report["unmatched_candidates"]) == 2  # 孤立走线两端=2 候选
        assert report["unmatched_candidates"][0]["position_mm"] == [50.0, 50.0]

    def test_explicit_empty_without_heuristic_raises(self) -> None:
        with pytest.raises(ValueError, match="0 端口"):
            resolve_ports(self._layout(), marker_layer="NOPE")

    def test_marker_empty_falls_back_to_heuristic(self) -> None:
        out = resolve_ports(self._layout(), marker_layer="NOPE",
                            heuristic=True, heuristic_layers=["F.Cu"])
        assert out["source"] == "heuristic" and out["advisory"] is True

    def test_yaml_empty_table_without_heuristic_raises(self) -> None:
        with pytest.raises(ValueError, match="0 端口"):
            resolve_ports(self._layout(), port_table=[])

    def test_ports_field_and_sources_constant(self) -> None:
        assert PORT_SOURCES == ("marker", "yaml", "heuristic")
        out = resolve_ports(self._layout(), marker_layer="PORT")
        assert {p.source for p in out["ports"]} == {"marker"}
        assert out["stats"]["n_ports"] == len(out["ports"])


# ---------------------------------------------------------------------------
# 容差常量契约（判据单源）
# ---------------------------------------------------------------------------


def test_tolerance_constants_anchors() -> None:
    assert POSITION_TOL_M == 1e-9
    assert WIDTH_RTOL == 1e-9
    assert DIR_DOT_MIN == 1.0 - 1e-12
