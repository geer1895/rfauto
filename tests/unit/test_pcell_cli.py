"""LC-2 pcell CLI 消费接线测试（孤儿复活：list/show/eval/render + 渲染桥）。

锚树（消费链端到端，离线零仿真）：
- 注册面：pcell 子应用四命令在 click 树（list/show/eval/render）；
- 渲染桥：PCellGeometry → Layout（求值产物直产）结构/层表/注记锚；
- CLI 面容错：未知单元/未知参数/非法 --param → 退出码 2；
- 导出面：DXF（纯文本写出器）往返 + GDSII（gdstk 可用时）往返无损。

薄壳口径：CLI 零逻辑，数值全部出自 core/pcell_dsl 确定性内核（铁律 7）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app

runner = CliRunner()

LC2_MM_CELLS = ("ms_bend", "gnd_void", "gnd_via_quad", "rf_taper",
                "rf_miter_bend", "rf_round_bend", "via_rail")


# ─── 注册面（五钉之消费面钉）─────────────────────────────────────────────

def test_pcell_subapp_registered_with_four_commands() -> None:
    from typer.main import get_command

    cmd = get_command(app)
    pcell_cmd = cmd.commands["pcell"]
    assert set(pcell_cmd.commands) == {"list", "show", "eval", "render"}


# ─── list / show（库清单与定义面）────────────────────────────────────────

def test_pcell_list_json_envelope() -> None:
    result = runner.invoke(app, ["pcell", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["n_cells"] >= 8  # LC-2 验收：8+ PCell
    names = {c["name"] for c in data["cells"]}
    assert set(LC2_MM_CELLS) <= names
    assert {"mline", "cpw", "wstep"} <= names  # 迁移三元组仍在库


def test_pcell_show_yaml_defines_evaluable_cell() -> None:
    result = runner.invoke(app, ["pcell", "show", "ms_bend"])
    assert result.exit_code == 0, result.output
    assert "paths:" in result.output and "rotate:" in result.output
    # --json 面出的 def dict 可独立求值（DSL 往返经 CLI 出口成立；
    # 非 JSON 面经 rich 换行不宜再作机器解析面）
    result_j = runner.invoke(app, ["pcell", "show", "ms_bend", "--json"])
    assert result_j.exit_code == 0, result_j.output
    definition = json.loads(result_j.output)["data"]["definition"]
    from rfauto.core.pcell_dsl import def_from_dict, evaluate_pcell

    geo = evaluate_pcell(def_from_dict(definition), {}, {})
    assert geo.paths[0].width == pytest.approx(1.113)


def test_pcell_show_unknown_cell_exits_2() -> None:
    result = runner.invoke(app, ["pcell", "show", "no_such"])
    assert result.exit_code == 2


# ─── eval（求值面：JSON 进出 + 负例）─────────────────────────────────────

def test_pcell_eval_json_payload_anchor() -> None:
    result = runner.invoke(app, [
        "pcell", "eval", "ms_bend", "--param", "rot_deg=90", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["pcell"] == "ms_bend"
    assert data["n_primitives"] == 1
    row = data["primitives"][0]
    assert row["kind"] == "path" and row["layer"] == "F.Cu"
    pts = row["points"]
    for (gx, gy), (wx, wy) in zip(
            pts, ((0.0, 0.0), (0.0, 10.0), (-8.0, 10.0)), strict=True):
        assert gx == pytest.approx(wx, abs=1e-12)
        assert gy == pytest.approx(wy, abs=1e-12)


def test_pcell_eval_migrated_cell_needs_context() -> None:
    result = runner.invoke(app, ["pcell", "eval", "mline", "--json"])
    assert result.exit_code == 2  # 缺 H_SUB/BOARD/NEAR 上下文 → 显式报错


def test_pcell_eval_migrated_cell_with_context() -> None:
    result = runner.invoke(app, [
        "pcell", "eval", "mline",
        "--context", "H_SUB=5.08e-4", "--context", "BOARD=0.06",
        "--context", "NEAR=1e-4", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["n_primitives"] == 1
    assert data["primitives"][0]["kind"] == "box"


def test_pcell_eval_unknown_param_exits_2() -> None:
    result = runner.invoke(app, [
        "pcell", "eval", "ms_bend", "--param", "nope=1", "--json"])
    assert result.exit_code == 2


def test_pcell_eval_malformed_param_exits_2() -> None:
    result = runner.invoke(app, [
        "pcell", "eval", "ms_bend", "--param", "w_mm", "--json"])
    assert result.exit_code == 2


# ─── 渲染桥（求值产物直产 Layout）────────────────────────────────────────

def _bridge_layout(name: str, params: list[str] | None = None):
    from rfauto.cli.domains.scattered import _pcell_geometry_to_layout
    from rfauto.core.pcell_dsl import evaluate_pcell, get_pcell

    overrides = ({k: float(v) for k, v in
                  (p.split("=", 1) for p in params)} if params else {})
    geo = evaluate_pcell(get_pcell(name), overrides, {})
    return geo, _pcell_geometry_to_layout(geo)


def test_bridge_structure_and_annotations() -> None:
    geo, layout = _bridge_layout("via_rail", ["n=3"])
    assert len(layout.items) == 3
    assert layout.name == "via_rail"
    assert layout.annotations["source"] == "pcell_dsl"
    assert layout.annotations["pcell"] == "via_rail"
    assert json.loads(layout.annotations["params_json"]) == geo.params
    layers = layout.layer_names()
    assert layers == ["F.Cu"]
    assert layout.require_layer("F.Cu").gds_layer == 1  # 铜层优先号


def test_bridge_mixed_primitives_item_type_coverage() -> None:
    from rfauto.adapters.layout_interchange import (
        LayoutPath,
        LayoutPolygon,
        LayoutVia,
    )

    _, layout = _bridge_layout("ms_bend")
    assert len(layout.items) == 1
    assert isinstance(layout.items[0], LayoutPath)
    assert layout.items[0].width_mm == pytest.approx(1.113)
    _, void = _bridge_layout("gnd_void")
    assert isinstance(void.items[0], LayoutPolygon)
    _, quad = _bridge_layout("gnd_via_quad")
    assert len(quad.items) == 4
    assert all(isinstance(it, LayoutVia) for it in quad.items)
    assert quad.items[0].pad_diameter_mm == pytest.approx(0.6)
    assert quad.items[0].drill_diameter_mm == pytest.approx(0.3)


def test_bridge_multilayer_assigns_distinct_gds_ids() -> None:
    # 双层单元（盒层 F.Cu 之外的层名走 100 起确定性分配）
    from rfauto.adapters.layout_interchange import assign_gds_layers

    layers = assign_gds_layers(["F.Cu", "Edge.Cuts", "gnd"])
    by_name = {layer.name: layer for layer in layers}
    assert by_name["F.Cu"].gds_layer == 1
    assert by_name["Edge.Cuts"].gds_layer == 20
    assert by_name["gnd"].gds_layer == 100


# ─── render（导出面：DXF/GDSII 往返）────────────────────────────────────

def test_pcell_render_dxf_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "bend.dxf"
    result = runner.invoke(app, [
        "pcell", "render", "ms_bend", "--out", str(out), "--fmt", "dxf",
        "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["n_items"] == 1 and data["out"] == str(out)
    assert out.exists()
    # 往返：DXF 读回 → 中心线折线与宽度无损
    from rfauto.adapters.layout_interchange import import_layout

    back = import_layout(out, "dxf")
    paths = [it for it in back.items if hasattr(it, "width_mm")]
    assert len(paths) == 1
    assert paths[0].width_mm == pytest.approx(1.113)
    assert len(paths[0].points) == 3


def test_pcell_render_gdsii_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("gdstk")
    out = tmp_path / "rail.gds"
    result = runner.invoke(app, [
        "pcell", "render", "via_rail", "--param", "n=4",
        "--out", str(out), "--fmt", "gdsii", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["n_items"] == 4
    from rfauto.adapters.layout_interchange import import_layout

    # GDSII 口径：via 钻孔不可承载 → 按焊盘圆内接多边形回读（export_gdsii 文档）
    back = import_layout(out, "gdsii", laymap={"1": "F.Cu"})
    polys = list(back.items)
    assert len(polys) == 4 and all(
        p.layer == "F.Cu" for p in polys)
    centers = sorted(
        (sum(x for x, _ in p.points) / len(p.points),
         sum(y for _, y in p.points) / len(p.points))
        for p in polys)
    assert centers == pytest.approx([(float(k), 0.0) for k in range(4)])


def test_pcell_render_bad_fmt_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, [
        "pcell", "render", "ms_bend", "--out", str(tmp_path / "x.zip"),
        "--fmt", "gerber", "--json"])
    assert result.exit_code == 2
