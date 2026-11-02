"""aurora_p A5 PCB 叠层 3D 等轴预览钉（core/stackup_preview + service + CLI --preview）。

验收面（任务书冻结 A-G）：
A. 层序/zmin/厚度与 RFStackup 逐层一致——装配计划逐键断言（zmin_source=
   "input" 原值直通；声明式路径 zmin_source="layout" 由布局几何得出并与
   自顶累计互证）；
B. PNG 确定性——同输入两次渲染逐字节相同（core bytes / service 文件 /
   CLI 文件三层）+ PNG chunk 清单零 tEXt/tIME（零时间戳零软件串）+ IHDR
   尺寸==plan canvas；
C. 标注原值原样（铁律 7）——thickness_text==format_number(输入值)、label
   含 ``t=<原值> <unit>``、material/er 原值；Z 比例尺只改 px 不改文本；
D. CLI --preview 缺省零变化（.drawio A/B 逐字节 + 信封键集不变）+ 旗标
   生效出 PNG（sha256 与信封互证）+ 预览失败 exit 1 不隐瞒；
E. 既有 test_stackup_diagram 零改动（本文件不触其钉；service ``__all__``
   仍恰两名）；
G. 图内零 CJK——label/title 全 ASCII（含 CJK 输入的 \\uXXXX 转义+warnings）。
另：颜色单源（KIND_COLORS ⊇ 2D KIND_TABLE、ground==plane）、比例尺单源
（Z_PX_PER_UNIT 两档==200px/mm）、等轴投影常数字面（零三角调用 grep 面）、
core 顶层零 adapters/matplotlib import（分层契约）、负例（空叠层/零厚度/
未知 kind/未知单位/画布超限/非 dict/YAML 缺失）、warnings 谱系（薄带/
缝隙/重叠/无介质/无导体/非 ASCII）。合成 fixture 零湖读；产物全落 tmp_path。
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rfauto.core.stackup_preview as spv
from rfauto.adapters.layout_stack import RFRouteLayer, RFStackup, dump_stackup
from rfauto.cli.main import app as root_app
from rfauto.core.stackup_diagram import KIND_TABLE, PX_PER_MM, format_number
from rfauto.core.stackup_preview import (
    BOARD_D_PX,
    BOARD_W_PX,
    KIND_COLORS,
    LABEL_GAP,
    LABEL_H,
    LABEL_VGAP,
    MAX_CANVAS_PX,
    PREVIEW_DPI,
    Z_PX_PER_UNIT,
    build_preview_plan,
    preview_spec_from_declarative,
    preview_spec_from_rfstackup,
    render_preview_png,
)
from rfauto.service.diagram_stackup_service import (
    PREVIEW_SOURCE_DECLARATIVE,
    PREVIEW_SOURCE_RFSTACKUP,
    PREVIEW_SOURCE_RFSTACKUP_YAML,
    generate_stackup_diagram,
    generate_stackup_preview,
)

# ─── 合成 fixtures（零湖读） ────────────────────────────────────────────────


def _rf(name: str, zmin: float, t: float, mat: str, kind: str) -> RFRouteLayer:
    return RFRouteLayer(name=name, zmin_m=zmin, thickness_m=t, material=mat, kind=kind)


#: 6 层板 S/G/S/P/G/S（RFStackup 米制，自底向上 zmin 连续；11 slab）
RF_6L = RFStackup(name="six_layer_SGSPGS", layers=(
    _rf("L6_BOT", 0.0, 35e-6, "Cu", "signal"),
    _rf("PP3", 35e-6, 200e-6, "FR4 PP", "dielectric"),
    _rf("L5_GND", 235e-6, 35e-6, "Cu", "ground"),
    _rf("CORE2", 270e-6, 500e-6, "FR4 core", "dielectric"),
    _rf("L4_PWR", 770e-6, 35e-6, "Cu", "ground"),
    _rf("PP2", 805e-6, 200e-6, "FR4 PP", "dielectric"),
    _rf("L3_SIG", 1005e-6, 35e-6, "Cu", "signal"),
    _rf("CORE1", 1040e-6, 500e-6, "FR4 core", "dielectric"),
    _rf("L2_GND", 1540e-6, 35e-6, "Cu", "ground"),
    _rf("PP1", 1575e-6, 200e-6, "FR4 PP", "dielectric"),
    _rf("L1_TOP", 1775e-6, 35e-6, "Cu", "signal"),
))

#: 2 层板（RFStackup：TOP/SUB/GND 3 slab；声明序故意顶→底=非 zmin 升序，
#: 钉 draw_order 排序与 index 声明序分离）
RF_2L = RFStackup(name="two_layer_ro4350b", layers=(
    _rf("TOP", 543e-6, 35e-6, "Cu", "signal"),
    _rf("SUB", 35e-6, 508e-6, "RO4350B", "dielectric"),
    _rf("GND", 0.0, 35e-6, "Cu", "ground"),
))

#: 声明式（T-O3 schema，自顶向下；与 test_stackup_diagram 同构但本地定义）
DECL_6L = {
    "title": "6 layer S/G/S/P/G/S",
    "layers": [
        {"name": "L1_TOP", "kind": "signal", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "PP1", "kind": "dielectric", "thickness_mm": 0.2, "material": "FR4 PP", "er": 4.2},
        {"name": "L2_GND", "kind": "plane", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "CORE1", "kind": "dielectric", "thickness_mm": 0.5, "material": "FR4 core", "er": 4.5},
        {"name": "L3_SIG", "kind": "signal", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "PP2", "kind": "dielectric", "thickness_mm": 0.2, "material": "FR4 PP", "er": 4.2},
        {"name": "L4_PWR", "kind": "plane", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "CORE2", "kind": "dielectric", "thickness_mm": 0.5, "material": "FR4 core", "er": 4.5},
        {"name": "L5_GND", "kind": "plane", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "PP3", "kind": "dielectric", "thickness_mm": 0.2, "material": "FR4 PP", "er": 4.2},
        {"name": "L6_BOT", "kind": "signal", "thickness_mm": 0.035, "material": "Cu"},
    ],
    "width_annotations": [{"layer": "L1_TOP", "width_mm": 0.36, "note": "50 ohm"}],
}

DECL_2L = {
    "title": "microstrip 50 ohm",
    "layers": [
        {"name": "TOP", "kind": "signal", "thickness_mm": 0.035, "material": "Cu"},
        {"name": "SUB", "kind": "dielectric", "thickness_mm": 0.508, "material": "RO4350B", "er": 3.66},
        {"name": "GND", "kind": "plane", "thickness_mm": 0.035, "material": "Cu"},
    ],
}


def _copy(obj):
    return json.loads(json.dumps(obj))


def _png_chunks(data: bytes) -> list[str]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    i, out = 8, []
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        out.append(data[i + 4:i + 8].decode("ascii"))
        i += 12 + n
    return out


def _png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


def _envelope(result) -> dict:
    out = result.output
    assert out.strip(), f"空输出（exit={result.exit_code}）"
    payload, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
    return payload


def _invoke(args: list[str]):
    return CliRunner().invoke(root_app, args)


# ─── 验收 A：RFStackup 逐层一致（原值直通） ───────────────────────────────────


@pytest.mark.parametrize("stack", [RF_6L, RF_2L], ids=["6L", "2L"])
def test_rfstackup_layers_order_zmin_thickness_verbatim(stack):
    spec = preview_spec_from_rfstackup(stack)
    assert spec["unit"] == "m" and spec["name"] == stack.name
    plan = build_preview_plan(spec)
    assert plan["n_layers"] == len(stack.layers)
    for i, (echo, lay) in enumerate(zip(plan["layers"], stack.layers, strict=True)):
        assert echo["index"] == i
        assert echo["name"] == lay.name
        assert echo["kind"] == lay.kind
        assert echo["material"] == lay.material
        assert echo["er"] is None  # RFStackup 无 εr 字段：不猜
        assert echo["thickness"] == lay.thickness_m
        assert echo["zmin"] == lay.zmin_m
        assert echo["zmax"] == round(lay.zmin_m + lay.thickness_m, 12)
        assert echo["zmin_source"] == "input"
    # 总厚 = Σthickness 确定性加法（round 12）
    assert plan["total_thickness"] == round(sum(lay.thickness_m for lay in stack.layers), 12)


def test_draw_order_ascending_zmin_independent_of_declaration_order():
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_2L))
    # 声明序 TOP/SUB/GND，画序按 zmin 升序 GND/SUB/TOP（index 不变）
    assert [lay["name"] for lay in plan["layers"]] == ["TOP", "SUB", "GND"]
    assert plan["draw_order"] == [2, 1, 0]
    zs = [plan["layers"][k]["zmin"] for k in plan["draw_order"]]
    assert zs == sorted(zs)
    plan6 = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    assert plan6["draw_order"] == list(range(11))
    assert not plan6["warnings"]  # 连续堆叠、1oz 铜 7px 过阈值：零提示


# ─── 验收 A'：声明式路径（layout zmin 与自顶累计互证） ────────────────────────


def test_declarative_layout_zmin_matches_top_down_cumulative():
    spec = preview_spec_from_declarative(DECL_6L)
    assert spec["unit"] == "mm" and spec["name"] == DECL_6L["title"]
    plan = build_preview_plan(spec)
    ths = [lay["thickness_mm"] for lay in DECL_6L["layers"]]
    total = round(sum(ths), 12)
    assert plan["total_thickness"] == total == 1.81
    depth = 0.0
    for i, (echo, raw) in enumerate(zip(plan["layers"], DECL_6L["layers"], strict=True)):
        assert echo["name"] == raw["name"] and echo["kind"] == raw["kind"]
        assert echo["thickness"] == raw["thickness_mm"]
        assert echo["material"] == raw.get("material")
        assert echo["er"] == raw.get("er")
        assert echo["zmin_source"] == "layout"
        # slab 底 z（自底向上）= total − 自顶深度 − 本层厚（round 6）
        assert math.isclose(echo["zmin"], total - depth - raw["thickness_mm"], abs_tol=1e-9), i
        depth += raw["thickness_mm"]
    assert plan["layers"][0]["zmax"] == total      # 顶层顶面=总厚
    assert plan["layers"][-1]["zmin"] == 0.0       # 底层底面=0
    assert plan["draw_order"] == list(range(10, -1, -1))  # 声明顶→底，画序底→顶
    assert not [w for w in plan["warnings"] if "gap" in w or "overlap" in w]


def test_declarative_width_annotations_ignored_but_validated():
    # 线宽标注不进 3D 预览面，但 schema 仍走 normalize_stackup 单源校验
    bad = _copy(DECL_6L)
    bad["width_annotations"] = [{"layer": "PP1", "width_mm": 1.0}]
    with pytest.raises(ValueError, match="介质层"):
        preview_spec_from_declarative(bad)
    plan = build_preview_plan(preview_spec_from_declarative(DECL_6L))
    assert "width_annotations" not in plan


# ─── 验收 C：标注原值原样 + 比例尺只改 px ──────────────────────────────────────


def test_label_text_verbatim_input_values():
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    for echo, lay in zip(plan["layers"], RF_6L.layers, strict=True):
        assert echo["thickness_text"] == format_number(lay.thickness_m) == str(lay.thickness_m)
        assert echo["label"] == (f"{lay.name} [{lay.kind}] {lay.material} "
                                 f"t={echo['thickness_text']} m")
    assert plan["layers"][0]["label"] == "L6_BOT [signal] Cu t=3.5e-05 m"
    plan_d = build_preview_plan(preview_spec_from_declarative(DECL_2L))
    assert plan_d["layers"][1]["label"] == "SUB [dielectric] RO4350B t=0.508 mm er=3.66"
    assert plan_d["layers"][0]["label"] == "TOP [signal] Cu t=0.035 mm"
    # 无材料层：标签省略材料段而非写 None
    plan_n = build_preview_plan({"unit": "mm", "layers": [
        {"name": "D", "kind": "dielectric", "thickness": 1.0, "zmin": 0.0}]})
    assert plan_n["layers"][0]["label"] == "D [dielectric] t=1 mm"


def test_z_scale_single_source_and_height_proportional():
    assert Z_PX_PER_UNIT == {"mm": PX_PER_MM, "m": PX_PER_MM * 1000.0}
    assert Z_PX_PER_UNIT["mm"] == 200.0 and Z_PX_PER_UNIT["m"] == 200000.0
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    assert plan["z_px_per_unit"] == 200000.0
    for echo, lay in zip(plan["layers"], RF_6L.layers, strict=True):
        assert math.isclose(echo["height_px"], lay.thickness_m * 200000.0, abs_tol=1e-6)
        assert math.isclose(echo["z0_px"], lay.zmin_m * 200000.0, abs_tol=1e-6)
        assert math.isclose(echo["z1_px"], (lay.zmin_m + lay.thickness_m) * 200000.0, abs_tol=1e-6)
    copper = {plan["layers"][i]["height_px"] for i in (0, 2, 4, 6, 8, 10)}
    assert copper == {7.0}                              # 1oz 铜 35µm → 7px
    assert plan["layers"][3]["height_px"] / plan["layers"][1]["height_px"] == 0.5 / 0.2
    # 两路同尺度：米制 35µm 与毫米制 0.035 同为 7px（跨图可比）
    plan_d = build_preview_plan(preview_spec_from_declarative(DECL_6L))
    assert plan_d["layers"][0]["height_px"] == 7.0
    assert plan_d["layers"][0]["thickness_text"] == "0.035"   # 文本仍是输入原值


# ─── 颜色单源 / 投影几何 / 标注列 ───────────────────────────────────────────────


def test_kind_colors_single_source_with_2d_table():
    assert set(KIND_COLORS) == {"signal", "plane", "dielectric", "ground"}
    for k, v in KIND_TABLE.items():
        assert KIND_COLORS[k] == v
    assert KIND_COLORS["ground"] == KIND_COLORS["plane"]
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    for echo in plan["layers"]:
        fill, edge = KIND_COLORS[echo["kind"]]
        assert echo["colors"]["top"] == fill and echo["colors"]["edge"] == edge
        # 侧面=固定因子加深（三通道均 ≤ top）
        for face in ("left", "right"):
            c = echo["colors"][face]
            assert len(c) == 7 and c.startswith("#")
            for i in (1, 3, 5):
                assert int(c[i:i + 2], 16) <= int(fill[i:i + 2], 16)
    assert plan["layers"][0]["colors"] == {"top": "#f8cecc", "left": "#c1a19f",
                                           "right": "#dfb9b8", "edge": "#b85450"}


def test_isometric_faces_geometry():
    cos30, sin30 = 0.8660254037844386, 0.5
    w, d = BOARD_W_PX, BOARD_D_PX
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_2L))
    assert plan["board_px"] == {"w": w, "d": d}
    for echo in plan["layers"]:
        z0, z1 = echo["z0_px"], echo["z1_px"]
        f = echo["faces"]
        # left 面（x=0）/ right 面（y=0）/ top 面（z=z1）各四点
        assert f["left"] == [(0.0, z0), (round(-cos30 * d, 6), round(sin30 * d + z0, 6)),
                             (round(-cos30 * d, 6), round(sin30 * d + z1, 6)), (0.0, z1)]
        assert f["right"] == [(0.0, z0), (round(cos30 * w, 6), round(sin30 * w + z0, 6)),
                              (round(cos30 * w, 6), round(sin30 * w + z1, 6)), (0.0, z1)]
        assert f["top"][0] == (0.0, z1)
        assert f["top"][2] == (round(cos30 * (w - d), 6), round(sin30 * (w + d) + z1, 6))
        # 标注锚=right 面远端竖边中点
        assert echo["label_anchor"] == (round(cos30 * w, 6), round(sin30 * w + (z0 + z1) / 2, 6))


def _assert_label_column_invariants(plan: dict) -> list[int]:
    """标注列不变量：起点=锚+GAP、只上推不下拉、最底卡在理想位、相邻净距≥VGAP；
    返回被上推的层索引（画序）。"""
    prev = None
    pushed: list[int] = []
    for k in plan["draw_order"]:
        echo = plan["layers"][k]
        au, av = echo["label_anchor"]
        lu, lv = echo["label_pos"]
        assert lu == round(au + LABEL_GAP, 6)
        assert lv >= av - 1e-9, "标注只许上推不许下拉"
        if prev is None:
            assert lv == av   # 最底层卡在理想位
        else:
            assert lv >= prev + LABEL_H + LABEL_VGAP - 1e-9, "标注互叠"
        if lv > av + 1e-9:
            pushed.append(k)
        prev = lv
    return pushed


def test_label_column_greedy_push_up_only_with_gap():
    # 6 层样例：单行卡 14px、锚距 ≥23.5px（铜 7px 与 PP 40px 交替）→ 零上推、零互叠
    assert _assert_label_column_invariants(
        build_preview_plan(preview_spec_from_rfstackup(RF_6L))) == []
    # 密集：4 片 1oz 铜直接相叠（锚距 7px < 16px）→ 贪心上推生效（首卡不动、其余三卡上推）
    dense = RFStackup(layers=tuple(
        _rf(f"C{i}", i * 35e-6, 35e-6, "Cu", "ground") for i in range(4)))
    plan = build_preview_plan(preview_spec_from_rfstackup(dense))
    assert _assert_label_column_invariants(plan) == [1, 2, 3]
    vs = [plan["layers"][k]["label_pos"][1] for k in plan["draw_order"]]
    assert vs == [vs[0] + i * (LABEL_H + LABEL_VGAP) for i in range(4)]   # 等距紧排


def test_title_precedence_and_ascii_subtitle():
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_2L))
    assert plan["title_source"] == "spec"
    assert plan["title"] == ("two_layer_ro4350b - 3 layers, total t=0.000578 m, "
                             "z scale 200000 px/m")
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_2L), title="Explicit")
    assert plan["title_source"] == "param" and plan["title"].startswith("Explicit - 3 layers")
    plan = build_preview_plan({"unit": "mm", "layers": [
        {"name": "D", "kind": "dielectric", "thickness": 1.0, "zmin": 0.0}]})
    assert plan["title_source"] == "default"
    assert plan["title"].startswith("PCB stackup isometric preview - 1 layers")


# ─── 验收 G：图内零 CJK ──────────────────────────────────────────────────────────


def test_all_figure_text_ascii_with_cjk_input_escaped_and_warned():
    stack = RFStackup(name="六层板", layers=(
        _rf("顶层", 0.0, 35e-6, "铜", "signal"),
        _rf("SUB", 35e-6, 200e-6, "FR4", "dielectric"),
    ))
    plan = build_preview_plan(preview_spec_from_rfstackup(stack))
    assert plan["title"].isascii()
    assert all(lay["label"].isascii() for lay in plan["layers"])
    assert plan["layers"][0]["label"] == "\\u9876\\u5c42 [signal] \\u94dc t=3.5e-05 m"
    assert plan["layers"][1]["label"] == "SUB [dielectric] FR4 t=0.0002 m"   # ASCII 层零转义
    assert plan["layers"][0]["name"] == "顶层"          # plan 字段仍是原值
    assert plan["layers"][0]["material"] == "铜"
    assert plan["title"].startswith("\\u516d\\u5c42\\u677f - 2 layers")
    ws = plan["warnings"]
    assert "layers[0] label contains non-ASCII characters" in ws[0]
    assert any(w.startswith("title contains non-ASCII") for w in ws)
    assert len([w for w in ws if "non-ASCII" in w]) == 2   # 层 0 + 标题；层 1 全 ASCII 不报
    # ASCII 输入：零转义零提示
    plan_ok = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    assert not [w for w in plan_ok["warnings"] if "non-ASCII" in w]


# ─── 验收 B：确定性 ──────────────────────────────────────────────────────────────


def test_plan_deterministic_and_json_serializable():
    a = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    b = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_png_two_renders_byte_identical_no_metadata_chunks():
    plan = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    png_a = render_preview_png(plan)
    png_b = render_preview_png(build_preview_plan(preview_spec_from_rfstackup(RF_6L)))
    assert png_a == png_b
    assert len(png_a) > 1000
    chunks = _png_chunks(png_a)
    assert chunks[0] == "IHDR" and chunks[-1] == "IEND"
    assert not {"tEXt", "zTXt", "iTXt", "tIME"} & set(chunks), chunks   # 零时间戳零软件串
    assert _png_size(png_a) == (plan["canvas"]["w_px"], plan["canvas"]["h_px"])
    assert plan["canvas"]["dpi"] == PREVIEW_DPI == 100


def test_canvas_adapts_to_content_and_is_integer_1to1():
    p2 = build_preview_plan(preview_spec_from_rfstackup(RF_2L))
    p6 = build_preview_plan(preview_spec_from_rfstackup(RF_6L))
    for p in (p2, p6):
        c = p["canvas"]
        assert isinstance(c["w_px"], int) and isinstance(c["h_px"], int)
        assert c["x1"] - c["x0"] == c["w_px"] and c["y1"] - c["y0"] == c["h_px"]
    assert p6["canvas"]["h_px"] > p2["canvas"]["h_px"]      # 更厚更高
    assert _png_size(render_preview_png(p2)) == (p2["canvas"]["w_px"], p2["canvas"]["h_px"])


# ─── service 三形态 + 信封 ────────────────────────────────────────────────────────


def test_service_rfstackup_instance_envelope_and_file(tmp_path):
    out = tmp_path / "six.png"
    r = generate_stackup_preview(RF_6L, out)
    assert r["ok"] is True, r
    assert r["source"] == PREVIEW_SOURCE_RFSTACKUP == "rfstackup"
    assert r["stackup_path"] is None
    assert r["unit"] == "m" and r["n_layers"] == 11
    assert r["total_thickness"] == 0.00181 and r["total_thickness_text"] == "0.00181"
    assert r["canvas"] == {"w_px": 823, "h_px": 718}
    data = out.read_bytes()
    assert r["png_bytes"] == len(data)
    assert r["png_sha256"] == hashlib.sha256(data).hexdigest()
    assert _png_size(data) == (823, 718)
    assert [lay["name"] for lay in r["layers"]] == [lay.name for lay in RF_6L.layers]
    assert set(r["layers"][0]) == {"index", "name", "kind", "material", "er", "thickness",
                                   "thickness_text", "zmin", "zmax", "zmin_source",
                                   "height_px", "label"}
    assert r["layers"][10] == {
        "index": 10, "name": "L1_TOP", "kind": "signal", "material": "Cu", "er": None,
        "thickness": 3.5e-05, "thickness_text": "3.5e-05", "zmin": 0.001775,
        "zmax": 0.00181, "zmin_source": "input", "height_px": 7.0,
        "label": "L1_TOP [signal] Cu t=3.5e-05 m"}
    assert r["warnings"] == []


def test_service_yaml_path_via_load_stackup(tmp_path):
    yml = dump_stackup(RF_2L, tmp_path / "two.yaml")
    out = tmp_path / "two.png"
    r = generate_stackup_preview(str(yml), out)
    assert r["ok"] is True, r
    assert r["source"] == PREVIEW_SOURCE_RFSTACKUP_YAML == "rfstackup_yaml"
    assert r["stackup_path"] == str(yml)
    assert r["n_layers"] == 3 and r["unit"] == "m"
    assert r["total_thickness_text"] == "0.000578"
    assert out.exists()
    # Path 入参同路径（PathLike 收敛 #140）
    r2 = generate_stackup_preview(Path(yml), tmp_path / "two2.png")
    assert r2["ok"] and r2["png_sha256"] == r["png_sha256"]


def test_service_declarative_envelope(tmp_path):
    out = tmp_path / "decl.png"
    r = generate_stackup_preview(_copy(DECL_2L), out, title="MS")
    assert r["ok"] is True, r
    assert r["source"] == PREVIEW_SOURCE_DECLARATIVE == "declarative"
    assert r["unit"] == "mm" and r["n_layers"] == 3
    assert r["total_thickness"] == 0.578
    assert r["title"].startswith("MS - 3 layers, total t=0.578 mm")
    assert all(lay["zmin_source"] == "layout" for lay in r["layers"])
    assert r["layers"][1]["label"] == "SUB [dielectric] RO4350B t=0.508 mm er=3.66"
    assert out.exists()


def test_service_determinism_two_files_byte_identical(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    ra = generate_stackup_preview(RF_6L, a)
    rb = generate_stackup_preview(RF_6L, b)
    assert ra["ok"] and rb["ok"]
    assert a.read_bytes() == b.read_bytes()
    assert {k: v for k, v in ra.items() if k != "out_path"} == {
        k: v for k, v in rb.items() if k != "out_path"}


def test_service_negatives_error_envelopes(tmp_path):
    out = tmp_path / "neg.png"
    # 空叠层（RFStackup 缺省构造合法，但无立体可画）
    r = generate_stackup_preview(RFStackup(), out)
    assert r["ok"] is False and "非空层列表" in r["errors"][0]
    # 零厚度层（RFStackup 合法零厚金属片 → 预览显式拒绝）
    zero = RFStackup(layers=(_rf("TOP", 0.0, 0.0, "Cu", "signal"),))
    r = generate_stackup_preview(zero, out)
    assert r["ok"] is False
    assert "thickness 必须 >0" in r["errors"][0] and "'TOP'" in r["errors"][0]
    # 输出目录不存在（不自动补救）
    r = generate_stackup_preview(RF_2L, tmp_path / "nodir" / "x.png")
    assert r["ok"] is False and "输出目录不存在" in r["errors"][0]
    # YAML 缺失
    r = generate_stackup_preview(str(tmp_path / "ghost.yaml"), out)
    assert r["ok"] is False and r["errors"][0].startswith("FileNotFoundError")
    # 类型不认
    for bad in (42, ["x"], None):
        r = generate_stackup_preview(bad, out)
        assert r["ok"] is False and "三形态" not in r["errors"][0]
        assert "RFStackup" in r["errors"][0]
    # 声明式 schema 违约
    bad = _copy(DECL_2L)
    bad["layers"][0]["kind"] = "copper"
    r = generate_stackup_preview(bad, out)
    assert r["ok"] is False and "kind 未知" in r["errors"][0]
    assert not out.exists()
    assert list(r) == ["ok", "errors"]


# ─── 内核负例（显式报错，不静默） ────────────────────────────────────────────────


def test_core_negative_empty_and_zero_thickness():
    with pytest.raises(ValueError, match="非空层列表"):
        build_preview_plan({"unit": "m", "layers": []})
    with pytest.raises(ValueError, match="非空层列表"):
        build_preview_plan(preview_spec_from_rfstackup(RFStackup()))
    with pytest.raises(ValueError, match="thickness 必须 >0"):
        build_preview_plan(preview_spec_from_rfstackup(
            RFStackup(layers=(_rf("Z", 0.0, 0.0, "Cu", "signal"),))))
    with pytest.raises(ValueError, match="thickness_mm"):
        preview_spec_from_declarative({"layers": [
            {"name": "Z", "kind": "signal", "thickness_mm": 0}]})
    with pytest.raises(ValueError, match="非空层卡列表"):
        preview_spec_from_declarative({"layers": []})


@pytest.mark.parametrize("bad, needle", [
    ({"unit": "um", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0}]}, "unit 未知"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "copper", "thickness": 1, "zmin": 0}]}, "kind 未知"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": -1, "zmin": 0}]}, "thickness 必须 >0"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": float("nan"), "zmin": 0}]}, "thickness"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": float("inf")}]}, "zmin"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0},
                               {"name": "A", "kind": "plane", "thickness": 1, "zmin": 1}]}, "重名"),
    ({"unit": "mm", "layers": [{"name": " ", "kind": "signal", "thickness": 1, "zmin": 0}]}, "非空字符串"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0, "er": 0.5}]}, "er"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0, "color": "red"}]}, "未支持键"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0,
                                "zmin_source": "guess"}]}, "zmin_source"),
    ({"unit": "mm", "layers": [{"name": "A", "kind": "signal", "thickness": 1, "zmin": 0}], "scale": 2}, "未支持键"),
    ({"unit": "mm", "layers": ["A"]}, "必须是 dict"),
    ("stack", "必须是 dict"),
])
def test_core_negative_spec_schema(bad, needle):
    with pytest.raises(ValueError, match=needle):
        build_preview_plan(bad)


def test_core_negative_title_and_duck_type():
    with pytest.raises(ValueError, match="title"):
        build_preview_plan(preview_spec_from_rfstackup(RF_2L), title="  ")
    with pytest.raises(ValueError, match="缺 layers 属性"):
        preview_spec_from_rfstackup(object())
    with pytest.raises(ValueError, match="缺属性 'zmin_m'"):
        preview_spec_from_rfstackup(type("S", (), {"layers": [type("L", (), {
            "name": "A", "kind": "signal", "thickness_m": 1e-3, "material": "Cu"})()]})())
    with pytest.raises(ValueError, match="plan 必须是"):
        render_preview_png({"nope": 1})


def test_canvas_limit_explicit_error_on_unit_mismatch():
    # 毫米值误填进 m 档：0.035 m × 2e5 px/m = 7000px 单层；两层即超 8000 上限
    bad = {"unit": "m", "layers": [
        {"name": "A", "kind": "signal", "thickness": 0.035, "zmin": 0.0},
        {"name": "B", "kind": "dielectric", "thickness": 0.035, "zmin": 0.035}]}
    with pytest.raises(ValueError, match=f"超上限 {MAX_CANVAS_PX}px"):
        build_preview_plan(bad)
    # 同数值在 mm 档正常（7px）
    ok = build_preview_plan({**bad, "unit": "mm"})
    assert ok["layers"][0]["height_px"] == 7.0


# ─── warnings 谱系 ───────────────────────────────────────────────────────────────


def test_warnings_gap_overlap_thin_no_dielectric_no_conductor():
    gap = RFStackup(layers=(_rf("A", 0.0, 35e-6, "Cu", "signal"),
                            _rf("B", 50e-6, 200e-6, "FR4", "dielectric")))
    ws = build_preview_plan(preview_spec_from_rfstackup(gap))["warnings"]
    assert ws == ["z gap between layer 'A' (zmax=3.5e-05) and layer 'B' (zmin=5e-05) "
                  "in draw order; slabs drawn at declared z, gap left empty"]
    overlap = RFStackup(layers=(_rf("A", 0.0, 35e-6, "Cu", "signal"),
                                _rf("B", 20e-6, 200e-6, "FR4", "dielectric")))
    ws = build_preview_plan(preview_spec_from_rfstackup(overlap))["warnings"]
    assert len(ws) == 1 and ws[0].startswith("z overlap between layer 'A' (zmax=3.5e-05) and layer 'B'")
    # 薄带：0.5oz 铜 17.5µm → 3.5px < 6px
    thin = RFStackup(layers=(_rf("A", 0.0, 17.5e-6, "Cu", "signal"),
                             _rf("B", 17.5e-6, 200e-6, "FR4", "dielectric")))
    ws = build_preview_plan(preview_spec_from_rfstackup(thin))["warnings"]
    assert ws == ["layer 'A' slab height 3.5px (<6px visible threshold; height stays "
                  "proportional to thickness, zoom to inspect)"]
    only_cu = build_preview_plan({"unit": "mm", "layers": [
        {"name": "C", "kind": "ground", "thickness": 0.1, "zmin": 0}]})["warnings"]
    assert only_cu == ["no dielectric layer (conductor-only declaration; drawn as given)"]
    only_d = build_preview_plan({"unit": "mm", "layers": [
        {"name": "D", "kind": "dielectric", "thickness": 0.5, "zmin": 0}]})["warnings"]
    assert only_d == ["no conductor layer (signal/plane/ground all absent; dielectric-only stack)"]
    # warnings 全 ASCII（信封与图面同口径）
    for w in ws + only_cu + only_d:
        assert w.isascii()


# ─── 验收 D：CLI --preview（缺省零变化 / 旗标生效 / 失败 exit 1） ─────────────────


def test_cli_preview_absent_zero_change_drawio_and_envelope(tmp_path):
    a, b = tmp_path / "a.drawio", tmp_path / "b.drawio"
    ra = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_6L),
                  "--out", str(a), "--json"])
    rb = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_6L),
                  "--out", str(b), "--preview", str(tmp_path / "b.png"), "--json"])
    assert ra.exit_code == 0 and rb.exit_code == 0, (ra.output[:300], rb.output[:300])
    assert a.read_bytes() == b.read_bytes()          # .drawio 逐字节不随旗标变
    pa, pb = _envelope(ra), _envelope(rb)
    assert "preview" not in pa                       # 缺省信封键集零变化
    assert list(pa) == ["ok", "out_path", "n_layers", "n_width_annotations",
                        "layers", "width_annotations", "warnings"]
    assert list(pb) == [*pa, "preview"]
    assert {k: v for k, v in pa.items() if k != "out_path"} == {
        k: v for k, v in pb.items() if k not in ("out_path", "preview")}
    # 与 service 直出逐字节同（CLI 是薄壳）
    direct = tmp_path / "direct.drawio"
    assert generate_stackup_diagram(_copy(DECL_6L), direct)["ok"]
    assert direct.read_bytes() == a.read_bytes()


def test_cli_preview_flag_writes_png_and_envelope_matches(tmp_path):
    png = tmp_path / "six.png"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_6L),
                 "--out", str(tmp_path / "six.drawio"), "--preview", str(png), "--json"])
    assert r.exit_code == 0, r.output[:400]
    pv = _envelope(r)["preview"]
    assert pv["ok"] is True and pv["source"] == "declarative" and pv["unit"] == "mm"
    assert pv["n_layers"] == 11 and pv["total_thickness_text"] == "1.81"
    data = png.read_bytes()
    assert hashlib.sha256(data).hexdigest() == pv["png_sha256"]
    assert _png_size(data) == (pv["canvas"]["w_px"], pv["canvas"]["h_px"])
    assert not {"tEXt", "tIME"} & set(_png_chunks(data))
    # 两跑逐字节（CLI 层）
    png2 = tmp_path / "six2.png"
    r2 = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_6L),
                  "--out", str(tmp_path / "six2.drawio"), "--preview", str(png2), "--json"])
    assert r2.exit_code == 0
    assert png2.read_bytes() == data
    # --title 同时作用于 .drawio 与预览标题
    r3 = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_2L),
                  "--out", str(tmp_path / "t.drawio"), "--preview", str(tmp_path / "t.png"),
                  "--title", "MyBoard", "--json"])
    assert _envelope(r3)["preview"]["title"].startswith("MyBoard - 3 layers")


def test_cli_preview_rich_output_escaped(tmp_path):
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_2L),
                 "--out", str(tmp_path / "ms.drawio"), "--preview", str(tmp_path / "ms.png")])
    assert r.exit_code == 0, r.output[:400]
    assert "[signal]" in r.output                 # 既有动态段 escape 不被吞
    assert "3D 预览" in r.output and "3 层" in r.output
    assert "预览已写出" in r.output
    assert (tmp_path / "ms.png").exists()
    # 缺省不给旗标：人读输出不出现预览段
    r0 = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_2L),
                  "--out", str(tmp_path / "ms0.drawio")])
    assert r0.exit_code == 0 and "预览" not in r0.output


def test_cli_preview_failure_exit1_not_hidden(tmp_path):
    missing = tmp_path / "nodir" / "x.png"
    out = tmp_path / "ok.drawio"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_2L),
                 "--out", str(out), "--preview", str(missing), "--json"])
    assert r.exit_code == 1
    p = _envelope(r)
    assert p["ok"] is False
    assert p["errors"] == [f"3D 预览生成失败: {p['preview']['errors'][0]}"]
    assert "输出目录不存在" in p["errors"][0]
    assert p["preview"]["ok"] is False
    assert p["n_layers"] == 3 and out.exists()   # .drawio 已写出的事实不隐瞒
    assert not missing.exists()
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(DECL_2L),
                 "--out", str(tmp_path / "ok2.drawio"), "--preview", str(missing)])
    assert r.exit_code == 1 and "3D 预览生成失败" in r.output
    # .drawio 本身失败时不尝试预览（无半成品 PNG）
    bad = _copy(DECL_2L)
    bad["layers"][0]["kind"] = "copper"
    r = _invoke(["diagram", "stackup", "--stackup", json.dumps(bad),
                 "--out", str(tmp_path / "bad.drawio"), "--preview", str(tmp_path / "bad.png"),
                 "--json"])
    assert r.exit_code == 1
    assert "preview" not in _envelope(r)
    assert not (tmp_path / "bad.png").exists()


def test_cli_help_lists_preview_flag_no_new_leaf():
    import typer.main

    r = _invoke(["diagram", "stackup", "--help"])
    assert r.exit_code == 0 and "--preview" in r.output
    group = typer.main.get_command(root_app)
    # 合流重钉（主代理，2026-11-01）：C3 落 to-svg 第六叶——本钉原意"本席零新叶"
    # 扩为全叶清单钉（前五叶序不变+schematic 后接 to-svg）；再变叶数时改此钉
    # +计数面同笔。
    assert list(group.commands["diagram"].commands) == [
        "link", "testsetup", "annotate", "stackup", "schematic", "to-svg"]


# ─── 公开面 / 分层 / 零换算 ───────────────────────────────────────────────────────


def test_public_surfaces_and_layering_guard():
    import rfauto.service.diagram_stackup_service as svc

    assert spv.__all__ == [
        "BOARD_D_PX", "BOARD_W_PX", "KIND_COLORS", "MAX_CANVAS_PX", "PREVIEW_DPI",
        "Z_PX_PER_UNIT", "build_preview_plan", "preview_spec_from_declarative",
        "preview_spec_from_rfstackup", "render_preview_png"]
    # service __all__ 由 test_stackup_diagram 钉死恰两名（A1 重钉，本席零改动）；
    # 预览入口显式路径可 import 但不入 __all__（docstring 如实登记）
    assert svc.__all__ == ["generate_stackup_diagram", "synthesis_width_annotation"]
    assert callable(generate_stackup_preview)
    src = inspect.getsource(spv)
    tree = ast.parse(src)
    top_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            top_imports.add(node.module)
        elif isinstance(node, ast.Import):
            top_imports.update(a.name for a in node.names)
    assert top_imports == {"__future__", "io", "math", "itertools", "typing",
                           "rfauto.core.stackup_diagram"}, top_imports
    # 分层契约：core 顶层零 adapters/service/matplotlib（matplotlib 只在渲染函数内）
    assert not any(m.startswith(("rfauto.adapters", "rfauto.service", "matplotlib"))
                   for m in top_imports)
    # 零换算红线（铁律 7）：装配/投影面无对数/幂/三角调用——投影常数为字面
    for banned in ("log10", "math.log", "math.exp", "math.pow", "10 **", "10**",
                   "pow(", "math.sin", "math.cos", "math.tan", "radians("):
        assert banned not in src, f"预览模块出现换算逻辑 {banned!r}"
