"""柱坐标 rat-race 渲染离线几何审计（§10.20 补强①；#212 零仿真模式）。

口径：柱坐标下环带 = 常数 r 精确圆环（r 网格线即带缘）、径向馈逐 r 网格
单元等物理宽栅格化，渲染半径 = 物理 R=17.344mm（k=1，无网格慢波伪象补偿，
#219 根治路线）。
官方 API 依据（铁律 1c，已核对官方例）：openEMS(CoordSystem=1) +
CSXCAD.ContinuousStructure(CoordSystem=1)；(r, a, z) 网格；
mesh.AddLine('r'/'a'/'z', ...) / SmoothMeshLines(0/1/2, ...)；
mesh.a = linspace(-pi, pi, N) = 全 2π 闭合网格（openEMS 作者 discussion
#196 定谳）；端口 MSLPort(prop_dir='r', exc_dir='z')。
审计手法（#212）：render→exec 几何段→CSXCAD 实测原语/网格，秒级零仿真。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

W_RING = 0.6035
W_FEED = 1.1134
R_PHYS = 17.344
R_IN_MM = 12.0
R_DOM_MM = 28.0
AZ_DEG = (0.0, 60.0, 120.0, 300.0)


def _render(mesh_mm: float = 0.4, excite_port: int = 1) -> str:
    from rfauto.adapters.openems_templates import render_ratrace_cylindrical

    return render_ratrace_cylindrical(
        {"w_ring_mm": W_RING, "w_feed_mm": W_FEED},
        (2.25, 2.75), mesh_resolution_mm=mesh_mm, excite_port=excite_port,
        r_in_mm=R_IN_MM, r_dom_mm=R_DOM_MM)


def _exec_geometry(tmp_path, text: str) -> dict:
    head = text[:text.index("FDTD.Run(")]
    g: dict = {"__name__": "__main__",
               "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "sim", "exec"), g)
    return g


def _metal_boxes(csx) -> list[tuple[float, float, float, float]]:
    """金属原语 (r_lo_mm, r_hi_mm, a_lo_rad, a_hi_rad)；r/a 均升序。"""
    boxes = []
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) != "Metal":
            continue
        for prim in prop.GetAllPrimitives():
            s = np.array(prim.GetStart(), dtype=float)
            e = np.array(prim.GetStop(), dtype=float)
            r0, r1 = sorted((s[0] * 1e3, e[0] * 1e3))
            a0, a1 = sorted((s[1], e[1]))
            boxes.append((r0, r1, a0, a1))
    return boxes


def _port_props(g: dict) -> dict[str, int]:
    csx = g["CSX"]
    out: dict[str, int] = {}
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        out[str(prop.GetName())] = out.get(str(prop.GetName()), 0) + 1
    return out


def test_cylindrical_script_compiles_and_k1() -> None:
    """脚本语法门 + k=1（无引擎常数补偿）+ 柱坐标口径存在性。"""
    text = _render()
    compile(text, "gen", "exec")
    assert "CoordSystem=1" in text
    assert "ContinuousStructure(CoordSystem=1)" in text
    assert 'prop_dir="r"' in text and 'exc_dir="z"' in text
    for n in (1, 2, 3, 4):
        assert f"MSLPort(CSX, port_nr={n}" in text
    # k=1：渲染半径 = 物理 17.344mm，脚本内不得出现引擎常数/补偿
    assert "_RATRACE_RING_MESH_K" not in text
    assert "0.017344" in text
    assert "1.0975" not in text
    # 全 2π a 网格 + 最小间距守卫（#152）
    assert "linspace(-np.pi, np.pi, 601)" in text
    assert 'for _ax in ("r", "a", "z")' in text


def test_cylindrical_mesh_full_2pi_and_gap_guard(tmp_path) -> None:
    """实测网格：a 向 = linspace(-pi, pi, 601) 全 2π 闭合；r 域环域
    [r_in, r_dom]；环带两缘精确入网；全部相邻线间距 >1µm（#152 守卫）。"""
    g = _exec_geometry(tmp_path, _render())
    mesh = g["mesh"]
    a = np.asarray(mesh.GetLines("a"), dtype=float)
    assert len(a) == 601
    assert a[0] == pytest.approx(-np.pi, abs=1e-12)
    assert a[-1] == pytest.approx(np.pi, abs=1e-12)
    np.testing.assert_allclose(np.diff(a), 2 * np.pi / 600, atol=1e-12)
    r = np.asarray(mesh.GetLines("r"), dtype=float)
    assert r.min() == pytest.approx(R_IN_MM * 1e-3, abs=1e-9)
    assert r.max() == pytest.approx(R_DOM_MM * 1e-3, abs=1e-9)
    for edge_mm in (R_PHYS - W_RING / 2, R_PHYS, R_PHYS + W_RING / 2):
        assert np.min(np.abs(r - edge_mm * 1e-3)) < 1e-9, f"r={edge_mm} 未入网"
    for ax in ("r", "a", "z"):
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        assert np.all(np.diff(ls) > 1e-6), f"{ax} 轴存在 <1µm 近重合线"


def test_cylindrical_ring_band_exact_and_k1(tmp_path) -> None:
    """环带 = 常数 r 精确圆环：单一全 2π 盒，外/内半径 = R±W_R/2（带宽
    = W_R），中心 = 物理 R（k=1，非 R/1.0975）。"""
    g = _exec_geometry(tmp_path, _render())
    boxes = _metal_boxes(g["CSX"])
    ring = [b for b in boxes if (b[3] - b[2]) > 2 * np.pi - 1e-6]
    assert len(ring) == 1, f"全 2π 环带盒应为 1 个，实测 {len(ring)}"
    r0, r1, a0, a1 = ring[0]
    assert a0 == pytest.approx(-np.pi, abs=1e-9)
    assert a1 == pytest.approx(np.pi, abs=1e-9)
    assert (r1 - r0) == pytest.approx(W_RING, abs=1e-6), "环带带宽 ≠ W_R"
    assert r0 == pytest.approx(R_PHYS - W_RING / 2, abs=1e-6)
    assert r1 == pytest.approx(R_PHYS + W_RING / 2, abs=1e-6)
    # k=1 回归守卫：若误施加 1.0975 补偿，外缘会到 ≈16.10mm
    r_eng = R_PHYS / 1.0975
    assert abs(r1 - (r_eng + W_RING / 2)) > 1.0, "环半径被引擎常数补偿"


def test_cylindrical_feeds_connect_to_ring(tmp_path) -> None:
    """四条径向馈：方位角 = 0/60/120/300°（300°归一化到 -60°），
    r∈[R, R_DOM]；**物理等宽**（逐 r 网格单元 a 半宽 = W_F/(2·r_c)，
    避免常数 azimuth 单盒的 R_DOM/R 锥化）；与环带正面积重叠（#174）。"""
    from rfauto.adapters.openems_templates import _cyl_azimuths_rad

    g = _exec_geometry(tmp_path, _render())
    boxes = _metal_boxes(g["CSX"])
    want = list(_cyl_azimuths_rad())
    assert len(want) == len(AZ_DEG) == 4
    r_lo_ring, r_hi_ring = R_PHYS - W_RING / 2, R_PHYS + W_RING / 2
    # 逐单元馈段（r 宽 ≤0.4mm；排除环带盒与 MSLPort 全段盒）
    segs = [b for b in boxes if (b[1] - b[0]) < 0.5]
    assert len(segs) >= 40, f"逐单元馈段不足: {len(segs)}"
    for b in segs:
        ac = 0.5 * (b[2] + b[3])
        assert min(abs(ac - a) for a in want) < 1e-9, f"馈段方位 {ac} 非规范"
    for a_k in want:
        grp = [b for b in segs if abs(0.5 * (b[2] + b[3]) - a_k) < 1e-9]
        assert grp, f"方位 {a_k} 无馈段"
        assert min(b[0] for b in grp) == pytest.approx(R_PHYS, abs=1e-6)
        assert max(b[1] for b in grp) == pytest.approx(R_DOM_MM, abs=1e-6)
        for r0, r1, a0, a1 in grp:
            rm = 0.5 * (r0 + r1)
            assert (a1 - a0) * rm == pytest.approx(W_FEED, rel=0.02), \
                f"r={rm:.2f} 处馈宽 {(a1 - a0) * rm:.4f} ≠ W_F"
    innermost = min(segs, key=lambda b: b[0])
    assert innermost[0] <= r_hi_ring
    assert min(innermost[1], r_hi_ring) - max(innermost[0], r_lo_ring) > 0, \
        "馈与环带无正面积重叠"


def test_cylindrical_ports_on_radial_boundary(tmp_path) -> None:
    """端口面贴 r=R_DOM 外边界；prop_dir='r'、exc_dir='z'；MSLPort 自画
    馈线与模板馈重叠；excite_port 单激励列（第 k 端口 excite=1）。"""
    for ep in (1, 2, 3, 4):
        g = _exec_geometry(tmp_path, _render(excite_port=ep))
        r_lines = np.asarray(g["mesh"].GetLines("r"), dtype=float)
        for k in (1, 2, 3, 4):
            p = g[f"_port{k}"]
            assert p.prop_ny == 0 and p.exc_ny == 2
            assert p.start[0] == pytest.approx(R_DOM_MM * 1e-3, abs=1e-9)
            assert p.start[0] == pytest.approx(r_lines.max(), abs=1e-9), \
                "端口面未贴 r 外边界"
            assert p.stop[0] == pytest.approx(R_PHYS * 1e-3, abs=1e-9)
            assert p.start[1] != p.stop[1], "端口 a 向零宽"
            expected = 1 if k == ep else 0
            assert float(p.excite) == float(expected)
        names = _port_props(g)
        assert f"port_excite_{ep}" in names
        for other in (1, 2, 3, 4):
            if other != ep:
                assert f"port_excite_{other}" not in names, \
                    "非激励端口不应创建激励属性"


def test_cylindrical_no_zero_width_metal(tmp_path) -> None:
    """无零宽盒（在 r/a 面内）：所有金属原语 r 宽、a 宽均 > 0（z 零厚
    是平面金属的既定口径）。"""
    g = _exec_geometry(tmp_path, _render())
    boxes = _metal_boxes(g["CSX"])
    assert boxes, "无金属原语"
    for r0, r1, a0, a1 in boxes:
        assert (r1 - r0) > 1e-9, f"零宽 r 盒: {r0, r1, a0, a1}"
        assert (a1 - a0) > 1e-9, f"零宽 a 盒: {r0, r1, a0, a1}"


def test_cylindrical_build_function_matches_render(tmp_path) -> None:
    """build_ratrace_cylindrical 生成的 body 与 render 装配一致（API 存在性
    + 参数透传：r_dom/馈方位半宽）。"""
    from rfauto.adapters.openems_templates import (
        _cyl_alpha_lines,
        build_ratrace_cylindrical,
    )

    n_alpha, da = _cyl_alpha_lines()
    assert n_alpha == 601
    assert da == pytest.approx(2 * math.pi / 600, abs=1e-12)
    body = build_ratrace_cylindrical(
        {"w_ring_mm": W_RING, "w_feed_mm": W_FEED}, r_dom_m=R_DOM_MM * 1e-3,
        excite_port=1)
    assert body.count("MSLPort(CSX, port_nr=") == 4
    # 1 环带 AddBox + 1 径向馈 AddBox（循环展开 4 次）
    assert body.count("ratrace.AddBox(") == 2
    assert "for _ak in _AZ:" in body
    text = _render()
    # 几何段（金属构建，不含端口 Feeding 参数）逐字一致
    geom_start = body.index("ratrace = CSX.AddMetal")
    geom_end = body.index("_port1 = MSLPort")
    assert body[geom_start:geom_end] in text, "render 未装配 build 的几何段"
