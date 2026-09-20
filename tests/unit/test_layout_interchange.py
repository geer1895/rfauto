"""B2 版图互操作测试（GDSII / DXF / IPC-2581 / ODB++ 往返无损，§10.2 B2）。

验收口径：往返无损。gdsii 按 nm 数据库格点（GDS unit=1mm/precision=1nm，
KiCad nm 整数格点同源），其余格式位精确。全部用例确定性、无网络、无真机，
写入 tmp_path 隔离目录，不污染 runs/。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from rfauto.adapters.kicad_pcell import Pad, PCBDesign, Trace, Via
from rfauto.adapters.layout_interchange import (
    CIRCLE_POLYGON_SEGMENTS,
    FORMAT_ROUNDTRIP_CAPABILITIES,
    LAYOUT_INTERCHANGE_FORMATS,
    Layout,
    LayoutCircle,
    LayoutLayer,
    LayoutPath,
    LayoutPolygon,
    LayoutVia,
    _apply_laymap,
    assign_gds_layers,
    circle_to_polygon,
    export_dxf,
    export_gdsii,
    export_ipc2581,
    export_layout,
    export_odbpp,
    import_dxf,
    import_gdsii,
    import_ipc2581,
    import_layout,
    import_odbpp,
    layout_from_pcb_design,
    round_trip_delta,
    verify_round_trip,
)

# nm 格点取值（KiCad 同源：mm 值 ×1e6 = 整数 nm）
BOARD = ((0.0, 0.0), (20.0, 0.0), (20.0, 10.5), (0.0, 10.5))
TRACE = ((2.5, 5.25), (17.5, 5.25), (17.5, 7.25))


@pytest.fixture
def reference_layout() -> Layout:
    """混合几何参考版图：板框 + 折线 + 圆 + 过孔 + 注记。"""
    return Layout(
        name="b2_ref",
        layers=assign_gds_layers(["F.Cu", "Edge.Cuts"]),
        items=(
            LayoutPolygon(points=BOARD, layer="Edge.Cuts"),
            LayoutPath(points=TRACE, width_mm=0.25, layer="F.Cu"),
            LayoutCircle(center=(2.5, 5.25), radius_mm=0.5, layer="F.Cu"),
            LayoutVia(
                position=(10.0, 2.0), pad_diameter_mm=0.6, drill_diameter_mm=0.3, pad_layer="F.Cu"
            ),
        ),
        annotations={"net": "RF", "family": "cpwg"},
    )


@pytest.mark.parametrize("fmt", LAYOUT_INTERCHANGE_FORMATS)
def test_roundtrip_lossless_all_formats(tmp_path, reference_layout, fmt):
    """验收主判据：四格式导出→读回 delta == 0.0（gdsii 按 nm 格点）。"""
    verdict = verify_round_trip(reference_layout, fmt, tmp_path)
    assert verdict["lossless"] is True, f"{fmt} delta={verdict['delta']}"
    assert verdict["delta"] == 0.0
    assert Path(verdict["path"]).exists()


def test_gdsii_nm_grid_losslessness(tmp_path, reference_layout):
    """GDSII 无损口径实证：12.345 双精度读回可能 1-ulp 漂移，nm 格点差必须为 0。"""
    exported = export_gdsii(reference_layout, tmp_path / "grid.gds")
    readback = import_gdsii(exported)
    paths = [item for item in readback.items if isinstance(item, LayoutPath)]
    assert len(paths) == 1
    read_x = paths[0].points[1][0]  # 17.5 那点
    assert round(read_x * 1e6) == round(17.5 * 1e6)  # nm 格点相等
    assert round_trip_delta(reference_layout, readback, "gdsii") == 0.0


def test_gdsii_path_stays_path_record(tmp_path, reference_layout):
    """GDSII 路径写 PATH 记录（simple_path=True），读回仍是路径而非轮廓多边形。"""
    import gdstk

    exported = export_gdsii(reference_layout, tmp_path / "path.gds")
    cell = gdstk.read_gds(str(exported)).top_level()[0]
    assert len(cell.paths) == 1
    spine = [(float(x), float(y)) for x, y in cell.paths[0].path_spines()[0]]
    assert spine == list(TRACE)
    # 板框 + 圆 + 过孔盘 = 3 个 BOUNDARY
    assert len(cell.polygons) == 3


def test_gdsii_circle_becomes_deterministic_polygon(tmp_path, reference_layout):
    """GDSII 圆以 64 段内接多边形承载：读回顶点数 64，内接误差 ≤ 半径×(1-cos(π/64))。"""
    readback = import_gdsii(export_gdsii(reference_layout, tmp_path / "circ.gds"))
    polys_on_cu = [
        item
        for item in readback.items
        if isinstance(item, LayoutPolygon) and len(item.points) == CIRCLE_POLYGON_SEGMENTS
    ]
    assert len(polys_on_cu) == 2  # 圆 + 过孔盘
    bound = 0.5 * (1.0 - math.cos(math.pi / CIRCLE_POLYGON_SEGMENTS))
    approx = circle_to_polygon((2.5, 5.25), 0.5)
    assert len(approx) == CIRCLE_POLYGON_SEGMENTS
    for x, y in approx:
        assert abs(math.hypot(x - 2.5, y - 5.25) - 0.5) <= bound + 1e-12


def test_gdsii_via_drill_declared_lost(tmp_path, reference_layout):
    """GDSII/DXF 钻孔不可承载（声明能力）：读回无 Via 项，焊盘圆保留。"""
    readback = import_gdsii(export_gdsii(reference_layout, tmp_path / "drill.gds"))
    assert not any(isinstance(item, LayoutVia) for item in readback.items)
    assert len(readback.items) == len(reference_layout.items)  # 焊盘圆以多边形承载
    assert FORMAT_ROUNDTRIP_CAPABILITIES["gdsii"]["drill_carried"] is False


def test_dxf_entity_grammar(tmp_path, reference_layout):
    """DXF R12 语法抽查：$ACADVER=AC1009、LAYER 表、POLYLINE/CIRCLE、EOF。"""
    exported = export_dxf(reference_layout, tmp_path / "b2.dxf")
    text = exported.read_text(encoding="ascii")
    assert "AC1009" in text and "EOF" in text
    assert "POLYLINE" in text and "CIRCLE" in text and "SEQEND" in text
    assert "F.Cu" in text and "Edge.Cuts" in text
    # 折线带全局宽度（组码 40）
    assert "0.25" in text
    readback = import_dxf(exported)
    assert len(readback.items) == len(reference_layout.items)


def test_dxf_unknown_entity_skipped_and_counted(tmp_path):
    """ENTITIES 节内未知实体（POINT）跳过且计数；结构性记录（SECTION 等）不计数。"""
    lines = [
        "0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
        "0", "POINT", "8", "F.Cu", "10", "1.0", "20", "2.0",
        "0", "CIRCLE", "8", "F.Cu", "10", "3.0", "20", "4.0", "40", "0.5",
        "0", "ENDSEC", "0", "EOF",
    ]
    path = tmp_path / "unknown.dxf"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    readback = import_dxf(path)
    assert readback.annotations["dxf_skipped_entities"] == "1"
    assert len(readback.items) == 1  # 只剩 CIRCLE


def test_dxf_truncated_file_raises(tmp_path):
    """组码无配对值行（文件截断）→ ValueError。"""
    path = tmp_path / "bad.dxf"
    path.write_text("0\nSECTION\n2\n", encoding="ascii")
    with pytest.raises(ValueError, match="截断"):
        import_dxf(path)


def test_ipc2581_xml_structure(tmp_path, reference_layout):
    """IPC-2581 子集骨架抽查：根 revision=C、EcadName、层表、Via 钻孔属性。"""
    import xml.etree.ElementTree as ET

    exported = export_ipc2581(reference_layout, tmp_path / "b2.xml")
    root = ET.parse(str(exported)).getroot()
    assert root.tag == "IPC-2581" and root.get("revision") == "C"
    assert root.findtext("Content/EcadName") == "b2_ref"
    assert len(root.findall("Content/Layer")) == 2
    via_node = root.find("Content/StepData/Step/FeatureLayer/ViaFeature")
    assert via_node is not None
    assert float(via_node.get("drillDiameter")) == 0.3
    assert float(via_node.get("padDiameter")) == 0.6


@pytest.mark.parametrize("fmt", ("ipc2581", "odbpp"))
def test_annotations_carried(tmp_path, reference_layout, fmt):
    """IPC-2581/ODB++ 注记全承载（FORMAT_ROUNDTRIP_CAPABILITIES 声明）。"""
    readback = import_layout(export_layout(reference_layout, tmp_path / f"ann.{fmt}", fmt), fmt)
    assert readback.annotations == {"net": "RF", "family": "cpwg"}


@pytest.mark.parametrize("fmt", ("gdsii", "dxf"))
def test_annotations_declared_lost(tmp_path, reference_layout, fmt):
    """GDSII/DXF 注记不承载（声明能力）：读回无注记且几何仍无损。"""
    readback = import_layout(export_layout(reference_layout, tmp_path / f"ann2.{fmt}", fmt), fmt)
    assert readback.annotations == {}
    assert round_trip_delta(reference_layout, readback, fmt) == 0.0


def test_odbpp_directory_layout(tmp_path, reference_layout):
    """ODB++ 子集目录结构：matrix/matrix + steps/<step>/layers/<layer> + UNITS=MM。"""
    out_dir = export_odbpp(reference_layout, tmp_path / "b2_odb")
    assert (out_dir / "matrix" / "matrix").exists()
    layer_file = out_dir / "steps" / "b2_ref" / "layers" / "F.Cu"
    assert layer_file.exists()
    text = layer_file.read_text(encoding="ascii")
    assert text.splitlines()[0] == "UNITS=MM"
    assert " d=" in text  # 钻孔字段在文件里
    readback = import_odbpp(out_dir)
    assert len(readback.items) == len(reference_layout.items)
    # 过孔读回断言（避开 .17g 文本尾差）
    via = next(item for item in readback.items if isinstance(item, LayoutVia))
    assert via.drill_diameter_mm == 0.3
    assert via.pad_diameter_mm == 0.6


def test_ipc2581_bad_root_raises(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("<NotIPC-2581/>", encoding="utf-8")
    with pytest.raises(ValueError, match="根元素"):
        import_ipc2581(path)


@pytest.mark.parametrize("fmt", LAYOUT_INTERCHANGE_FORMATS)
def test_missing_file_raises_filenotfound(tmp_path, fmt):
    missing = tmp_path / f"missing_{fmt}.bin"
    with pytest.raises(FileNotFoundError):
        import_layout(missing, fmt)


def test_unknown_format_raises_valueerror(tmp_path, reference_layout):
    with pytest.raises(ValueError, match="不支持的版图互操作格式"):
        export_layout(reference_layout, tmp_path / "x.gerber", "gerber")
    with pytest.raises(ValueError, match="不支持的版图互操作格式"):
        import_layout(tmp_path / "x.gds", "gerber")


def test_item_count_mismatch_returns_inf(reference_layout):
    trimmed = Layout(
        name="b2_ref",
        layers=reference_layout.layers,
        items=reference_layout.items[:-1],  # 少过孔
    )
    assert round_trip_delta(reference_layout, trimmed, "ipc2581") == math.inf


def test_layer_mismatch_returns_inf(reference_layout):
    moved = Layout(
        name="b2_ref",
        layers=reference_layout.layers,
        items=tuple(
            LayoutPolygon(points=item.points, layer="B.Cu")
            if isinstance(item, LayoutPolygon)
            else item
            for item in reference_layout.items
        ),
    )
    assert round_trip_delta(moved, reference_layout, "ipc2581") == math.inf


def test_perturbation_detected(reference_layout):
    """非无损检出行：挪动 1µm 必给出 delta>0 且数值正确。"""
    perturbed_path = LayoutPath(
        points=((2.501, 5.25), *TRACE[1:]), width_mm=0.25, layer="F.Cu"
    )
    perturbed = Layout(
        name="b2_ref",
        layers=reference_layout.layers,
        items=(reference_layout.items[0], perturbed_path, *reference_layout.items[2:]),
    )
    delta = round_trip_delta(reference_layout, perturbed, "ipc2581")
    assert 0.0009 <= delta <= 0.0011


def test_assign_gds_layers_preferred_and_overflow():
    layers = assign_gds_layers(["F.Cu", "Edge.Cuts", "B.Cu", "F.Mask", "F.SilkS"])
    by_name = {layer.name: layer for layer in layers}
    assert by_name["F.Cu"].gds_layer == 1
    assert by_name["B.Cu"].gds_layer == 2
    assert by_name["Edge.Cuts"].gds_layer == 20
    assert by_name["F.Mask"].gds_layer == 100  # 其余按名排序自 100 起
    assert by_name["F.SilkS"].gds_layer == 101


def test_export_unregistered_layer_raises():
    layout = Layout(
        name="bad",
        layers=(LayoutLayer(name="F.Cu", gds_layer=1),),
        items=(LayoutPath(points=((0.0, 0.0), (1.0, 0.0)), width_mm=0.2, layer="B.Cu"),),
    )
    with pytest.raises(KeyError, match="未注册层"):
        export_gdsii(layout, Path("unused.gds"))


def test_b1_bridge_layout_from_pcb_design():
    """B1 桥：kicad_pcell.PCBDesign → Layout 的项映射（B2 依赖 B1）。"""
    design = PCBDesign(
        board_size=[20.0, 10.0],
        traces=[Trace(start=[2.5, 5.0], end=[17.5, 5.0], width=0.25, layer="F.Cu")],
        vias=[Via(position=[10.0, 2.0], drill=0.3, pad=0.6)],
        pads=[Pad(position=[2.5, 5.0], size=[1.0, 0.8], shape="rect", layer="F.Cu")],
    )
    layout = layout_from_pcb_design(design)
    kinds = [type(item).__name__ for item in layout.items]
    assert kinds == ["LayoutPolygon", "LayoutPath", "LayoutVia", "LayoutPolygon"]
    trace = layout.items[1]
    assert trace.width_mm == 0.25 and len(trace.points) == 2
    via = layout.items[2]
    assert via.drill_diameter_mm == 0.3 and via.pad_diameter_mm == 0.6
    rect = layout.items[3]
    assert (rect.points[1][0] - rect.points[0][0]) == pytest.approx(1.0)
    assert (rect.points[2][1] - rect.points[1][1]) == pytest.approx(0.8)


@pytest.mark.parametrize("fmt", LAYOUT_INTERCHANGE_FORMATS)
def test_b1_bridge_roundtrip_all_formats(tmp_path, fmt):
    """B1 桥产物四格式往返无损（B2+B5 合并验收的 B1 接入面）。"""
    design = PCBDesign(
        board_size=[12.345, 6.789],
        traces=[Trace(start=[1.0, 3.0], end=[11.345, 3.0], width=0.3, layer="F.Cu")],
        vias=[Via(position=[6.0, 1.5], drill=0.3, pad=0.6)],
        pads=[],
    )
    layout = layout_from_pcb_design(design)
    verdict = verify_round_trip(layout, fmt, tmp_path)
    assert verdict["lossless"] is True, f"{fmt} delta={verdict['delta']}"


def test_verify_round_trip_reports_absolute_path(tmp_path, reference_layout):
    verdict = verify_round_trip(reference_layout, "dxf", tmp_path)
    assert Path(verdict["path"]).is_absolute()
    assert verdict["path"].endswith(".dxf")


# ---------------------------------------------------------------------------
# P2⑳ laymap：GDS 导入消费外部层名映射（可选 feature；默认行为不变）
# ---------------------------------------------------------------------------

#: 判据②/③/④ 共用的具名映射（与 assign_gds_layers 首选层号 F.Cu=1/Edge.Cuts=20 同源）。
LAYMAP_NAMED = {"1": "F.Cu", "20": "Edge.Cuts"}


def test_gdsii_import_default_unchanged_no_laymap(tmp_path):
    """判据①：laymap=None 默认行为与现状一致——读回层名仍是层号串（基准 ['1','20']）。"""
    from rfauto.adapters.layout_generator import generate_microstrip

    layout = generate_microstrip({"width_mm": 0.25, "length_mm": 10.0})
    exported = export_gdsii(layout, tmp_path / "ms.gds")
    bare = import_gdsii(exported)
    assert bare.layer_names() == ["1", "20"]
    explicit = import_gdsii(exported, laymap=None)
    assert explicit.layer_names() == bare.layer_names()
    assert [lay.gds_layer for lay in explicit.layers] == [lay.gds_layer for lay in bare.layers]
    assert round_trip_delta(layout, bare, "gdsii") == 0.0


def test_gdsii_import_laymap_renames_and_aligns_original(tmp_path, reference_layout):
    """判据②：laymap 按层号改名——层表名/项层全改名，与具名原版逐项对齐。"""
    exported = export_gdsii(reference_layout, tmp_path / "ref.gds")
    readback = import_gdsii(exported, laymap=LAYMAP_NAMED)
    by_name = {lay.name: lay.gds_layer for lay in readback.layers}
    assert by_name == {"F.Cu": 1, "Edge.Cuts": 20}
    assert {item.layer for item in readback.items} == {"F.Cu", "Edge.Cuts"}
    assert round_trip_delta(reference_layout, readback, "gdsii") == 0.0


def test_gdsii_import_laymap_unmapped_layer_keeps_number_name(tmp_path):
    """判据②补：未命中层号保持层号串名（宽松不炸，真实 GDS 文件层多）。"""
    src = Layout(
        name="extra",
        layers=assign_gds_layers(["F.Cu", "Edge.Cuts", "KeepOut"]),
        items=(
            LayoutPolygon(points=BOARD, layer="Edge.Cuts"),
            LayoutPath(points=TRACE, width_mm=0.25, layer="F.Cu"),
            LayoutPath(points=TRACE, width_mm=0.25, layer="KeepOut"),
        ),
    )
    exported = export_gdsii(src, tmp_path / "extra.gds")
    readback = import_gdsii(exported, laymap=LAYMAP_NAMED)
    by_name = {lay.name: lay.gds_layer for lay in readback.layers}
    assert by_name == {"F.Cu": 1, "Edge.Cuts": 20, "100": 100}
    keepout = [item for item in readback.items if item.layer == "100"]
    assert len(keepout) == 1


def test_gdsii_import_laymap_round_trip_delta_neutral(tmp_path, reference_layout):
    """判据③：_layer_key_fn 按各侧自身 name→gds_layer 表解析层号比较——改名裁判中性。"""
    exported = export_gdsii(reference_layout, tmp_path / "ref.gds")
    bare = import_gdsii(exported)
    mapped = import_gdsii(exported, laymap=LAYMAP_NAMED)
    assert round_trip_delta(bare, mapped, "gdsii") == 0.0  # laymap 导入 vs 裸导入
    assert round_trip_delta(reference_layout, mapped, "gdsii") == 0.0  # vs 具名原版


def test_gdsii_import_laymap_reexport_stable(tmp_path, reference_layout):
    """判据④：laymap 导入→再导出→再 laymap 导入幂等；层号与 assign_gds_layers
    首选表（F.Cu=1/Edge.Cuts=20）同源，重导出层号不漂移。"""
    first = import_gdsii(export_gdsii(reference_layout, tmp_path / "a.gds"), laymap=LAYMAP_NAMED)
    second = import_gdsii(export_gdsii(first, tmp_path / "b.gds"), laymap=LAYMAP_NAMED)
    assert first.layer_names() == second.layer_names()
    by_name = {lay.name: lay.gds_layer for lay in second.layers}
    preferred = {lay.name: lay.gds_layer for lay in assign_gds_layers(second.layer_names())}
    assert by_name == preferred
    assert round_trip_delta(first, second, "gdsii") == 0.0


def test_gdsii_import_laymap_bcu_preferred_numbers_reexport(tmp_path):
    """判据④补：三分层版图（B.Cu=2）经 laymap 往返层号不漂移。"""
    src = Layout(
        name="three_layer",
        layers=assign_gds_layers(["F.Cu", "B.Cu", "Edge.Cuts"]),
        items=(
            LayoutPolygon(points=BOARD, layer="Edge.Cuts"),
            LayoutPath(points=TRACE, width_mm=0.25, layer="F.Cu"),
            LayoutPath(points=TRACE, width_mm=0.25, layer="B.Cu"),
        ),
    )
    laymap = {"1": "F.Cu", "2": "B.Cu", "20": "Edge.Cuts"}
    first = import_gdsii(export_gdsii(src, tmp_path / "a.gds"), laymap=laymap)
    second = import_gdsii(export_gdsii(first, tmp_path / "b.gds"), laymap=laymap)
    by_name = {lay.name: lay.gds_layer for lay in second.layers}
    assert by_name == {"F.Cu": 1, "B.Cu": 2, "Edge.Cuts": 20}
    assert round_trip_delta(first, second, "gdsii") == 0.0


def test_import_layout_laymap_non_gdsii_rejected(tmp_path):
    """laymap 语义仅 gdsii：fmt!=gdsii 给 laymap 显式 ValueError（静默忽略不可取）。"""
    with pytest.raises(ValueError, match="laymap"):
        import_layout(tmp_path / "missing.dxf", "dxf", laymap={"1": "F.Cu"})


def test_import_layout_laymap_gdsii_passthrough(tmp_path, reference_layout):
    """import_layout 派发器把 laymap 透传到 import_gdsii。"""
    exported = export_gdsii(reference_layout, tmp_path / "ref.gds")
    mapped = import_layout(exported, "gdsii", laymap=LAYMAP_NAMED)
    assert "F.Cu" in mapped.layer_names()
    assert round_trip_delta(reference_layout, mapped, "gdsii") == 0.0


def test_apply_laymap_via_uses_pad_layer():
    """laymap 对 Via 项走 pad_layer（GDS 读回无 Via 项，防御性钉住重命名路径）；
    laymap=None/空映射原样返回（缺省零改动）。"""
    layout = Layout(
        name="via_layout",
        layers=assign_gds_layers(["F.Cu"]),
        items=(
            LayoutVia(
                position=(1.0, 2.0), pad_diameter_mm=0.6, drill_diameter_mm=0.3, pad_layer="1"
            ),
        ),
    )
    renamed = _apply_laymap(layout, {"1": "F.Cu"})
    assert renamed.items[0].pad_layer == "F.Cu"
    assert renamed.layer_names() == ["F.Cu"]
    assert _apply_laymap(layout, None) is layout
    assert _apply_laymap(layout, {}) is layout


def test_apply_laymap_key_normalization():
    """laymap 键归一：str/int/补零串键统一按 str(int(key)) 命中层号串名。"""
    layout = Layout(
        name="k",
        layers=(LayoutLayer(name="1", gds_layer=1),),
        items=(LayoutPath(points=((0.0, 0.0), (1.0, 0.0)), width_mm=0.2, layer="1"),),
    )
    for raw in ({"1": "F.Cu"}, {1: "F.Cu"}, {"01": "F.Cu"}):
        assert _apply_laymap(layout, raw).layer_names() == ["F.Cu"]


# ---------------------------------------------------------------------------
# KiCad 10 真实导出样例对拍（tests/fixtures/external/）。
# 样例由本机 KiCad 10.0.6 kicad-cli 生成（microwave 官方 demo 板）：
#   kicad-cli pcb export ipc2581 <pcb> -o <xml>
#   kicad-cli pcb export odb <pcb> -o <dir> --compression none
# 对拍口径：读入器输出 vs 样例原文独立重数/重读（不依赖被测读入器），
# 不猜具体数字。真实文件比自产子集复杂（命名空间/字典间接引用/表面记录），
# 兼容差异与跳过口径见 import_ipc2581 / import_odbpp docstring。
# ---------------------------------------------------------------------------

_KICAD_IPC_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "external" / "kicad10_microwave.2581.xml"
)
_KICAD_ODB_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "external" / "kicad10_microwave_odb"
)


def _require_external(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"KiCad10 真实导出样例缺失: {path}")


def _raw_ipc_feature_counts(fixture: Path) -> dict[str, int]:
    """IPC 样例原文独立重数：F.Cu 的 Pad 实例数、被 F.Cu 引用的用户图元轮廓数、
    板框 Line 数（Contour/Polygon 在 DictionaryUser 定义内，经 UserPrimitiveRef 间接引用）。"""
    import xml.etree.ElementTree as ET

    root = ET.parse(str(fixture)).getroot()
    counts: dict[str, int] = {}
    counts["pads"] = len(root.findall(".//{*}LayerFeature[@layerRef='F.Cu']//{*}Pad"))
    counts["outline_lines"] = len(root.findall(".//{*}LayerFeature[@layerRef='Edge.Cuts']//{*}Line"))
    ref_ids = {
        node.get("id")
        for node in root.findall(".//{*}LayerFeature[@layerRef='F.Cu']//{*}UserPrimitiveRef")
    }
    counts["contours"] = sum(
        len(entry.findall(".//{*}Contour/{*}Polygon"))
        for entry in root.findall(".//{*}DictionaryUser/{*}EntryUser")
        if entry.get("id") in ref_ids
    )
    return counts


def _raw_ipc_text_set_count(fixture: Path) -> int:
    """IPC 样例原文独立重数：geometryUsage='TEXT' 的 Set 数（读入器按声明跳过）。"""
    import xml.etree.ElementTree as ET

    root = ET.parse(str(fixture)).getroot()
    return sum(
        1 for node in root.findall(".//{*}Set") if (node.get("geometryUsage") or "").upper() == "TEXT"
    )


def _raw_odbpp_feature_count(odb_root: Path, layer_dir: str) -> int:
    """ODB 样例原文独立重数：层 features 文件头声明的 `F <n>` 特性总数。"""
    features = odb_root / "steps" / "pcb" / "layers" / layer_dir / "features"
    for line in features.read_text(encoding="ascii", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("F "):
            return int(stripped[2:])
    return 0


def _raw_odbpp_pad_count(odb_root: Path, layer_dir: str) -> int:
    """ODB 样例原文独立重数：层 features 的 `P` 焊盘记录数。"""
    features = odb_root / "steps" / "pcb" / "layers" / layer_dir / "features"
    in_features = False
    pads = 0
    for line in features.read_text(encoding="ascii", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#Layer features"):
            in_features = True
            continue
        if in_features and stripped.startswith("P "):
            pads += 1
    return pads


@pytest.mark.parametrize(
    "fmt,fixture,expected_layers",
    (
        ("ipc2581", _KICAD_IPC_FIXTURE, ("F.Cu", "B.Cu", "Edge.Cuts", "F.Mask")),
        ("odbpp", _KICAD_ODB_FIXTURE, ("F.CU", "EDGE.CUTS", "F.SILKSCREEN")),
    ),
)
def test_kicad10_real_sample_import(fmt, fixture, expected_layers):
    """真实样例读入冒烟：名称来自样例、层名按格式惯例存在、几何非空。"""
    _require_external(fixture)
    layout = import_layout(fixture, fmt)
    assert layout.name == {"ipc2581": "microwave", "odbpp": "PCB"}[fmt]
    names = layout.layer_names()
    for expected in expected_layers:
        assert expected in names
    assert len(layout.items) > 0


def test_kicad10_ipc2581_real_pad_and_outline_alignment():
    """IPC 真实样例项级对拍：焊盘矩形/走线轮廓/板框线数 = 样例原文独立重数。"""
    _require_external(_KICAD_IPC_FIXTURE)
    raw = _raw_ipc_feature_counts(_KICAD_IPC_FIXTURE)
    layout = import_ipc2581(_KICAD_IPC_FIXTURE)
    by_layer: dict[str, list] = {}
    for item in layout.items:
        by_layer.setdefault(item.layer, []).append(item)
    # F.Cu 焊盘：Pad 实例 → 4 角矩形（DictionaryStandard RectCenter 位精确）
    rects = [i for i in by_layer.get("F.Cu", []) if isinstance(i, LayoutPolygon) and len(i.points) == 4]
    assert len(rects) == raw["pads"]
    # F.Cu 走线：UserPrimitiveRef → Contour/Polygon 轮廓（每个轮廓一个多边形）
    contours = [i for i in by_layer.get("F.Cu", []) if isinstance(i, LayoutPolygon) and len(i.points) > 4]
    assert len(contours) == raw["contours"]
    # 板框：UserSpecial Line → 描边路径（与 ODB++ 同源坐标，见跨格式用例）
    outline = [i for i in by_layer.get("Edge.Cuts", []) if isinstance(i, LayoutPath)]
    assert len(outline) == raw["outline_lines"]
    # TEXT 笔画集按声明跳过且计数（best-effort，如实不静默）
    assert layout.annotations["ipc2581_skipped"] == str(_raw_ipc_text_set_count(_KICAD_IPC_FIXTURE))


@pytest.mark.parametrize(
    "layer_dir,layer_name",
    (("f.cu", "F.CU"), ("edge.cuts", "EDGE.CUTS"), ("f.silkscreen", "F.SILKSCREEN"), ("user.drawings", "USER.DRAWINGS")),
)
def test_kicad10_odbpp_real_feature_count_alignment(layer_dir, layer_name):
    """ODB 真实样例项级对拍：每层读入项数 = features 文件头 `F <n>` 声明总数。"""
    _require_external(_KICAD_ODB_FIXTURE)
    layout = import_odbpp(_KICAD_ODB_FIXTURE)
    got = sum(1 for item in layout.items if item.layer == layer_name)
    assert got == _raw_odbpp_feature_count(_KICAD_ODB_FIXTURE, layer_dir)


def test_kicad10_odbpp_real_pad_and_width_alignment():
    """ODB 真实样例焊盘/线宽对拍：P 记录数一致、描边宽=符号表 µm 口径换算。"""
    _require_external(_KICAD_ODB_FIXTURE)
    layout = import_odbpp(_KICAD_ODB_FIXTURE)
    by_layer: dict[str, list] = {}
    for item in layout.items:
        by_layer.setdefault(item.layer, []).append(item)
    # 焊盘：P 记录 → 4 角矩形（KiCad 符号 rect<W>x<H>，µm→mm）
    rects = [i for i in by_layer["F.CU"] if isinstance(i, LayoutPolygon) and len(i.points) == 4]
    assert len(rects) == _raw_odbpp_pad_count(_KICAD_ODB_FIXTURE, "f.cu")
    # 线宽：L 记录的 round 符号 r<D>，D µm = 描边直径（0.3048mm = 板源 12mil）
    widths = {round(i.width_mm, 6) for i in by_layer["F.CU"] if isinstance(i, LayoutPath)}
    assert widths == {0.3048}
    # 走线轮廓表面（S..OB..OS..OE）读回为多边形；逐点承载口径：
    # 每岛 = OB 起点 + OS 逐点，去连续重复/闭合末点至多各 1 →
    # 总点数下界 = 原文 OS 记录数的 95%（独立重数，不猜具体点数）
    surfaces = [i for i in by_layer["F.CU"] if isinstance(i, LayoutPolygon) and len(i.points) > 4]
    raw_os = sum(
        1
        for line in (_KICAD_ODB_FIXTURE / "steps" / "pcb" / "layers" / "f.cu" / "features")
        .read_text(encoding="ascii", errors="replace")
        .splitlines()
        if line.strip().startswith("OS ")
    )
    assert len(surfaces) == sum(
        1
        for line in (_KICAD_ODB_FIXTURE / "steps" / "pcb" / "layers" / "f.cu" / "features")
        .read_text(encoding="ascii", errors="replace")
        .splitlines()
        if line.strip().startswith("S ")
    )
    assert sum(len(i.points) for i in surfaces) >= 0.95 * raw_os
    assert layout.annotations.get("odbpp_skipped") is None  # 本样例无不可摄记录


def _rect_center_size(points):
    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, max(xs) - min(xs), max(ys) - min(ys)


def test_kicad10_cross_format_pads_and_outline_consistency():
    """跨格式对拍：两格式各自读入同一块板，焊盘中心/尺寸与板框端点在
    KiCad ODB 坐标 2 位小数舍入口径（≤0.005mm）内一致。"""
    _require_external(_KICAD_IPC_FIXTURE)
    _require_external(_KICAD_ODB_FIXTURE)
    ipc = import_ipc2581(_KICAD_IPC_FIXTURE)
    odb = import_odbpp(_KICAD_ODB_FIXTURE)

    def pad_key(item):
        cx, cy, w, h = _rect_center_size(item.points)
        return (cx, cy, w, h)

    ipc_pads = sorted(
        (pad_key(i) for i in ipc.items if isinstance(i, LayoutPolygon) and i.layer == "F.Cu" and len(i.points) == 4),
        key=repr,
    )
    odb_pads = sorted(
        (pad_key(i) for i in odb.items if isinstance(i, LayoutPolygon) and i.layer == "F.CU" and len(i.points) == 4),
        key=repr,
    )
    assert len(ipc_pads) == len(odb_pads)
    for (cx1, cy1, w1, h1), (cx2, cy2, w2, h2) in zip(ipc_pads, odb_pads, strict=True):
        assert abs(cx1 - cx2) <= 0.0051
        assert abs(cy1 - cy2) <= 0.0051
        assert abs(w1 - w2) <= 1e-6
        assert abs(h1 - h2) <= 1e-6

    ipc_outline = sorted(
        (pt for i in ipc.items if isinstance(i, LayoutPath) and i.layer == "Edge.Cuts" for pt in i.points),
        key=repr,
    )
    odb_outline = sorted(
        (pt for i in odb.items if isinstance(i, LayoutPath) and i.layer == "EDGE.CUTS" for pt in i.points),
        key=repr,
    )
    assert len(ipc_outline) == len(odb_outline)
    for (x1, y1), (x2, y2) in zip(ipc_outline, odb_outline, strict=True):
        assert abs(x1 - x2) <= 0.0051
        assert abs(y1 - y2) <= 0.0051
