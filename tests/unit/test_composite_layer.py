"""覆铜板复合层组板 + DXF 导出 + 悬空孔过滤 单元测试（ge5 Goal Wave3 F 组）.

规范来源：E:\\协助调研\\cad导出\\改动总结-复合层DXF导出.md §1.1/§2.3/§2.4
（只读借鉴）。全部合成几何、零 HFSS/零网络（ezdxf 已在 venv fab extra）。

钉住的规范点：
- 复合层=介质板+Z 向贴合金属按物理贴合自动组板（非「HFSS 对象=一块板」）；
- 图层固定 M1/M2/sub/patch，通孔完整圆不简化（CIRCLE 实体在档）；
- 无依托孔（板外/骑边）物理过滤 + 删除留痕清单，keep_edge 参数化。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf, write_composite_dxf
from rfauto.core.fab_export.composite_layer import (
    COMPOSITE_LAYERS,
    CompositeObject,
    classify_object,
    filter_unsupported_holes,
    group_composite_layers,
)
from rfauto.service.fab_export_service import fab_composite_export

BOARD = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]


def _board(z0: float = 0.0, z1: float = 1.0, name: str = "sub1") -> CompositeObject:
    return CompositeObject(
        name=name, material="dielectric", z0=z0, z1=z1, outlines=[list(BOARD)]
    )


def _metal(name: str, z0: float, z1: float, outlines: list | None = None) -> CompositeObject:
    return CompositeObject(
        name=name,
        material="metal",
        z0=z0,
        z1=z1,
        outlines=outlines if outlines is not None else [list(BOARD)],
    )


# ─── 组板：Z 向物理贴合 ──────────────────────────────────────────────


def test_group_minimal_sub_two_metals_via():
    """最小例：介质+顶铜+底铜+过孔 → M1/M2/sub/patch 各归其位."""
    objs = [
        _board(0.0, 1.0),
        _metal("G_top", 1.0, 1.035),
        _metal("G_bot", -0.035, 0.0),
        CompositeObject(
            name="via_1",
            material="metal",
            z0=-0.035,
            z1=1.035,
            circles=[((5.0, 4.0), 0.15)],
        ),
    ]
    g = group_composite_layers(objs)
    assert [o.name for o in g.M1] == ["G_top"]
    assert [o.name for o in g.M2] == ["G_bot"]
    assert [o.name for o in g.sub] == ["sub1"]
    assert [o.name for o in g.patch] == ["via_1"]
    assert g.unassigned == []
    assert g.as_dict() == {
        "M1": ["G_top"],
        "M2": ["G_bot"],
        "sub": ["sub1"],
        "patch": ["via_1"],
        "unassigned": [],
    }


def test_group_same_side_multi_piece_all_preserved():
    """同侧多片金属：全部进同图层（合并=图层语义，非几何丢弃）."""
    top_pad = _metal("G_p1", 1.0, 1.035, outlines=[[(0, 0), (2, 0), (2, 2), (0, 2)]])
    top_line = _metal("G_p2", 1.0, 1.035, outlines=[[(4, 0), (6, 0), (6, 2), (4, 2)]])
    g = group_composite_layers([_board(0.0, 1.0), top_pad, top_line])
    assert [o.name for o in g.M1] == ["G_p1", "G_p2"]
    assert g.M2 == []


def test_group_hfss_object_is_not_one_board():
    """「HFSS 对象=一块板」证伪：三小层对象组出一块复合板而非三块."""
    g = group_composite_layers(
        [
            _board(0.0, 1.0),
            _metal("G_top", 1.0, 1.035),
            _metal("G_bot", -0.035, 0.0),
        ]
    )
    # 一块介质、两片金属、零 unassigned——复合层是板+贴合金属的组
    assert len(g.sub) == 1 and len(g.M1) == 1 and len(g.M2) == 1
    assert g.unassigned == []


def test_group_adjacency_gap_beyond_tol_unassigned():
    """金属与介质不贴合（间隙 > ADJ_TOL）→ unassigned，不静默归类."""
    floating = _metal("G_float", 1.0 + 0.01, 1.035 + 0.01)
    g = group_composite_layers([_board(0.0, 1.0), floating])
    assert g.M1 == [] and g.M2 == []
    assert [o.name for o in g.unassigned] == ["G_float"]


def test_group_embedded_metal_nearest_face_with_note():
    """板厚内嵌金属：按近侧归属并留 note（不静默丢弃）."""
    # 板 0..1，内嵌金属 0.60..0.62（近顶面：d_top=0.38 < d_bot=0.60）
    embedded = _metal("G_inner", 0.60, 0.62)
    g = group_composite_layers([_board(0.0, 1.0), embedded])
    assert [o.name for o in g.M1] == ["G_inner"]
    assert any("embedded metal" in n for n in g.notes)


def test_group_bonding_metal_touches_both_sides_note():
    """F9 负例钉：两板间键合金属（z 双侧贴板）→ 归 M1 + note 留痕.

    四图层模型无内层，键合金属按惯例归 M1 并显式 note（不静默、
    不 unassigned）——composite_layer.py L169-175 分支此前零覆盖。
    """
    lower = _board(0.0, 1.0, name="sub_low")
    upper = _board(1.0, 2.0, name="sub_up")
    bonding = _metal("G_bond", 1.0, 1.0)  # 底面贴 lower 顶面、顶面贴 upper 底面
    g = group_composite_layers([lower, upper, bonding])
    assert [o.name for o in g.M1] == ["G_bond"]
    assert g.M2 == [] and g.unassigned == []
    assert any("bonding metal" in n and "G_bond" in n for n in g.notes)


def test_name_semantics_via_chao_sub_and_material_fallback():
    """对象名语义：via*/chao*→patch、sub*→sub；无语义时材质兜底."""
    assert classify_object(CompositeObject("via_pad", "metal", 0, 1)) == "patch"
    assert classify_object(CompositeObject("chao_2", "metal", 0, 1)) == "patch"
    assert classify_object(CompositeObject("sub2", "dielectric", 0, 1)) == "sub"
    assert classify_object(CompositeObject("Gnd", "metal", 0, 1)) == "metal"
    # 材质缺失时名字 G 前缀兜底
    assert classify_object(CompositeObject("g1", "", 0, 1)) == "metal"
    assert classify_object(CompositeObject("plate", "dielectric", 0, 1)) == "sub"


def test_group_unknown_material_object_unassigned():
    """既非金属也非介质也非过孔 → unassigned（多报不放过）."""
    weird = CompositeObject("blob", "unknown", 0.0, 1.0, outlines=[list(BOARD)])
    g = group_composite_layers([_board(0.0, 1.0), weird])
    assert [o.name for o in g.unassigned] == ["blob"]


def test_composite_layers_fixed_layer_names():
    assert COMPOSITE_LAYERS == ("M1", "M2", "sub", "patch")


# ─── 悬空孔物理过滤 ──────────────────────────────────────────────────


def test_filter_inside_hole_kept():
    holes = [("h1", (5.0, 4.0), 0.3)]
    res = filter_unsupported_holes(holes, [[BOARD]])
    assert [h[0] for h in res["kept"]] == ["h1"]
    assert res["removed"] == []
    assert res["counts"] == {"kept": 1, "removed": 0, "total": 1}


def test_filter_outside_and_edge_holes_removed_with_trace():
    holes = [
        ("out1", (20.0, 20.0), 0.3),   # 完全在板外
        ("edge1", (9.85, 4.0), 0.3),   # 骑边（圆心在板内但圆出边，clearance=-0.15）
        ("in1", (5.0, 4.0), 0.3),
    ]
    res = filter_unsupported_holes(holes, [[BOARD]])
    assert [h[0] for h in res["kept"]] == ["in1"]
    reasons = {r.name: r.reason for r in res["removed"]}
    assert reasons == {"out1": "outside", "edge1": "edge"}
    # 留痕含圆心/半径可回溯（删除清单语义）
    out_trace = next(r for r in res["removed"] if r.name == "out1")
    assert out_trace.center == (20.0, 20.0) and out_trace.radius == pytest.approx(0.3)


def test_filter_keep_edge_threshold_parameterized():
    """keep_edge 边距阈值入参：留边 0.35 在 0.3 阈值下保留、0.4 下删除."""
    holes = [("near_edge", (0.65, 4.0), 0.3)]  # 圆缘到板边留边 = 0.65-0.3 = 0.35
    keep = filter_unsupported_holes(holes, [[BOARD]], keep_edge_mm=0.3)
    drop = filter_unsupported_holes(holes, [[BOARD]], keep_edge_mm=0.4)
    assert [h[0] for h in keep["kept"]] == ["near_edge"]
    assert keep["removed"] == []
    assert drop["counts"] == {"kept": 0, "removed": 1, "total": 1}
    assert drop["removed"][0].reason == "edge"


def test_filter_board_cutout_inner_loop_even_odd():
    """板内开槽（内环）：槽内孔=无介质依托 → 删；材料区内孔 → 留."""
    board_with_slot = [
        # 单板双环：外环+内槽环（板内 even-odd 解释内外）
        [list(BOARD), [(4.0, 3.0), (6.0, 3.0), (6.0, 5.0), (4.0, 5.0)]],
    ]
    holes = [
        ("slot_hole", (5.0, 4.0), 0.2),  # 槽内
        ("solid_hole", (2.0, 4.0), 0.2),  # 实体材料区
    ]
    res = filter_unsupported_holes(holes, board_with_slot)
    assert [h[0] for h in res["kept"]] == ["solid_hole"]
    assert res["removed"][0].name == "slot_hole"
    assert res["removed"][0].reason == "outside"


def test_filter_multi_board_overlap_no_parity_cancellation():
    """F8 负例钉：多板 XY 重叠叠层逐板判定，奇偶不跨板混计.

    修复前缺陷：全部板环统一 even-odd 计数——偶数块 XY 重叠板把板内
    合法孔抵消成"板外"全删，且行为随板数奇偶翻转（1 板 kept / 2 板
    removed / 3 板 kept）。逐板判定后：孔被任一单板包含即有依托。
    """
    boards = [[list(BOARD)], [list(BOARD)], [list(BOARD)]]  # 2/3 块 XY 重叠板
    holes = [("in_overlap", (5.0, 4.0), 0.2), ("out1", (20.0, 20.0), 0.3)]
    for n in (2, 3):
        res = filter_unsupported_holes(holes, boards[:n])
        assert [h[0] for h in res["kept"]] == ["in_overlap"], n
        reasons = {r.name: r.reason for r in res["removed"]}
        assert reasons == {"out1": "outside"}, n


def test_filter_multi_board_clearance_min_over_supporting_boards():
    """依托板边距取最小值：孔贴近其中一块板边时按最近边判骑边."""
    board_a = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]
    board_b = [(-20.0, 0.0), (-10.0, 0.0), (-10.0, 8.0), (-20.0, 8.0)]  # 不重叠
    # 孔圆心 (9.65, 4.0) r=0.3：距 board_a 右边 0.05（骑边）、
    # 距 board_b 远——最小依托边距 < keep_edge → edge 删除
    holes = [("near_a_edge", (9.65, 4.0), 0.3)]
    res = filter_unsupported_holes(holes, [[board_a], [board_b]], keep_edge_mm=0.1)
    assert res["kept"] == []
    assert res["removed"][0].reason == "edge"


def test_filter_no_outline_removes_all_with_trace():
    res = filter_unsupported_holes([("h", (1.0, 1.0), 0.2)], [])
    assert res["counts"]["kept"] == 0 and res["counts"]["removed"] == 1
    assert res["rule"] == "no-outline"


# ─── DXF 写/读回（四图层、完整圆不简化） ─────────────────────────────


def _minimal_layers() -> dict:
    return {
        "M1": [_metal("G_top", 1.0, 1.035)],
        "M2": [_metal("G_bot", -0.035, 0.0)],
        "sub": [_board(0.0, 1.0)],
        "patch": [
            CompositeObject("via_1", "metal", -0.035, 1.035, circles=[((5.0, 4.0), 0.15)]),
            CompositeObject("via_2", "metal", -0.035, 1.035, circles=[((2.0, 2.0), 0.3)]),
        ],
    }


def test_write_read_composite_dxf_layers(tmp_path: Path):
    out = write_composite_dxf(_minimal_layers(), tmp_path / "lam" / "L1.dxf")
    assert out.exists()
    rb = read_composite_dxf(out)
    assert set(rb) == set(COMPOSITE_LAYERS)
    # 外形：M1/M2/sub 各一个矩形环 → 4 段
    for layer in ("M1", "M2", "sub"):
        assert len(rb[layer]["segments"]) == 4, layer
    # patch：两个完整圆（CIRCLE 实体，圆心/半径精确读回，不简化成多边形）
    assert rb["patch"]["segments"] == []
    radii = sorted(r for _, r in rb["patch"]["circles"])
    assert radii == pytest.approx([0.15, 0.3])
    centers = sorted(c for c, _ in rb["patch"]["circles"])
    assert centers == [(2.0, 2.0), (5.0, 4.0)]


def test_dxf_via_circle_full_not_simplified(tmp_path: Path):
    """通孔=完整圆：DXF 实体级核验（CIRCLE 实体在 patch 层，不折线）."""
    import ezdxf  # type: ignore

    out = write_composite_dxf(_minimal_layers(), tmp_path / "L1.dxf")
    doc = ezdxf.readfile(str(out))
    circles = [e for e in doc.modelspace() if e.dxftype() == "CIRCLE"]
    assert len(circles) == 2
    assert {e.dxf.layer for e in circles} == {"patch"}
    r15 = next(e for e in circles if abs(e.dxf.radius - 0.15) < 1e-12)
    assert (r15.dxf.center.x, r15.dxf.center.y) == (5.0, 4.0)


def test_dxf_layer_colors_match_source_convention(tmp_path: Path):
    """ACI 颜色沿用源仓口径（M1=30/M2=140/sub=5/patch=1）."""
    import ezdxf  # type: ignore

    out = write_composite_dxf(_minimal_layers(), tmp_path / "c.dxf")
    doc = ezdxf.readfile(str(out))
    aci = {name: doc.layers.get(name).color for name in COMPOSITE_LAYERS}
    assert aci == {"M1": 30, "M2": 140, "sub": 5, "patch": 1}


# ─── service 信封 ────────────────────────────────────────────────────


def _service_objects() -> list[dict]:
    return [
        {"name": "sub1", "material": "dielectric", "z0": 0.0, "z1": 1.0, "outlines": [BOARD]},
        {"name": "G_top", "material": "metal", "z0": 1.0, "z1": 1.035, "outlines": [BOARD]},
        {"name": "G_bot", "material": "metal", "z0": -0.035, "z1": 0.0, "outlines": [BOARD]},
        {"name": "via_1", "material": "metal", "z0": -0.035, "z1": 1.035,
         "circles": [[[5.0, 4.0], 0.15]]},
        {"name": "via_susp", "material": "metal", "z0": -0.035, "z1": 1.035,
         "circles": [[[20.0, 20.0], 0.3]]},
    ]


def test_service_fab_composite_export_envelope(tmp_path: Path):
    env = fab_composite_export(_service_objects(), tmp_path / "L1.dxf")
    assert env["ok"] is True, env.get("errors")
    assert Path(env["path"]).exists()
    assert env["grouping"]["M1"] == ["G_top"]
    assert env["grouping"]["patch"] == ["via_1", "via_susp"]
    # 悬空孔删除 + 留痕清单
    assert env["hole_filter"]["counts"] == {"kept": 1, "removed": 1, "total": 2}
    assert env["hole_filter"]["removed"][0]["name"] == "via_susp"
    assert env["hole_filter"]["removed"][0]["reason"] == "outside"
    # 读回自证：patch 只剩保留孔的 1 个圆
    assert env["dxf_entity_counts"]["patch"]["circles"] == 1
    assert env["dxf_entity_counts"]["sub"]["segments"] == 4


def test_service_fab_composite_export_unassigned_rejects(tmp_path: Path):
    objs = [
        {"name": "sub1", "material": "dielectric", "z0": 0.0, "z1": 1.0, "outlines": [BOARD]},
        {"name": "blob", "material": "unknown", "z0": 5.0, "z1": 6.0, "outlines": [BOARD]},
    ]
    env = fab_composite_export(objs, tmp_path / "x.dxf")
    assert env["ok"] is False
    assert "unassigned" in env["errors"][0]
    assert not (tmp_path / "x.dxf").exists()


def test_service_two_core_stack_via_in_overlap_kept(tmp_path: Path):
    """F8 service 级钉：2 芯 XY 重叠叠层（4 层 PCB 常态）过孔不丢.

    修复前 service 面 board_loops=全部 sub 外形拍平 union——2 芯即偶数
    块，重叠区合法过孔被奇偶抵消判"板外"全删。
    """
    objs = [
        {"name": "sub1", "material": "dielectric", "z0": 0.0, "z1": 1.0, "outlines": [BOARD]},
        {"name": "sub2", "material": "dielectric", "z0": 1.0, "z1": 2.0, "outlines": [BOARD]},
        {"name": "via_1", "material": "metal", "z0": 0.0, "z1": 2.0,
         "circles": [[[5.0, 4.0], 0.15]]},
    ]
    env = fab_composite_export(objs, tmp_path / "stack.dxf")
    assert env["ok"] is True, env.get("errors")
    assert env["hole_filter"]["counts"] == {"kept": 1, "removed": 0, "total": 1}
    assert env["dxf_entity_counts"]["patch"]["circles"] == 1


def test_service_multi_circle_patch_first_only_with_note(tmp_path: Path):
    """F10 钉：多圆 patch 对象只导出/过滤首圆，其余圆 note 留痕不静默."""
    objs = [
        {"name": "sub1", "material": "dielectric", "z0": 0.0, "z1": 1.0,
         "outlines": [BOARD]},
        {"name": "via_multi", "material": "metal", "z0": -0.035, "z1": 1.035,
         "circles": [[[5.0, 4.0], 0.15], [[2.0, 2.0], 0.3]]},
    ]
    env = fab_composite_export(objs, tmp_path / "mc.dxf")
    assert env["ok"] is True, env.get("errors")
    assert env["dxf_entity_counts"]["patch"]["circles"] == 1
    assert any("multi-circle patch 'via_multi'" in n and "2 circles" in n
               for n in env["notes"])
