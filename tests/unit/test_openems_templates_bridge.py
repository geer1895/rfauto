"""lange 去桥对照旋钮（_bridge=0）单测：缺省逐字节不变 + 去桥恰桥相关行。

c4-去桥单变量对照（判据预声明）：
params["_bridge"]=0 → 桥金属 4 盒+立柱 8 盒不渲染、桥面 z 网格线不再入网
（哨兵 np.array([H_SUB])——CSRectGrid.AddLine 拒绝空数组）、_near_y 恰去 8 个
桥 y 缘值；缺省（无键或 =1）渲染与旋钮落位前快照逐字节不变（离线自证
IDENTITY_OK 归档：基线渲染脚本 + 渲染差异清单）。
本文件钉行为契约：旋钮缺省不动分毫、=0 单变量干净、几何仍合法（去桥后
无端口悬空，指2/指3 悬浮 PEC 为预声明语义）。
"""

from __future__ import annotations

import ast
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    _c4_layout,
    render_script,
)
from tests.unit import _geometry_audit_helpers as gh

FREQ = (2.0, 3.0)
MESH_MM = 0.4
NRTS = 200000.0


def _params(extra: dict[str, float] | None = None) -> dict[str, float]:
    p = {k: float(v) for k, v in TEMPLATE_NOMINAL["lange"].items()}
    p["_nrts"] = NRTS
    if extra:
        p.update(extra)
    return p


def _render(extra: dict[str, float] | None = None, port: int = 1) -> str:
    return render_script("lange", _params(extra), FREQ,
                         mesh_resolution_mm=MESH_MM, excite_port=port)


def _near_y_values(text: str) -> list[float]:
    for line in text.splitlines():
        if line.startswith("_near_y = ["):
            return [float(v)
                    for v in ast.literal_eval(line[len("_near_y = "):])]
    raise AssertionError("渲染文本缺 _near_y 字面清单")


def test_default_render_has_bridge_and_is_knob_free():
    """缺省渲染含桥（4）/立柱（8）盒，且 params 无 _bridge 键与 =1 逐字节一致。"""
    base = _render()
    assert sum(1 for ln in base.splitlines() if "# bridge_" in ln) == 4
    assert sum(1 for ln in base.splitlines() if "# post_" in ln) == 8
    assert "0.000608" in base and "0.000658" in base
    assert _render({"_bridge": 1.0}) == base
    lay = _c4_layout("lange", _params())
    assert len([b for b in lay["boxes"] if b[0].startswith("bridge_")]) == 4
    assert len([b for b in lay["boxes"] if b[0].startswith("post_")]) == 8
    assert len(lay["z_lines"]) == 2


def test_bridge_off_single_variable_diff():
    """_bridge=0：恰 12 条 AddBox 消失、_near_y 恰去 8 桥缘、z 行变哨兵、余不变。"""
    base = _render().splitlines()
    off = _render({"_bridge": 0.0}).splitlines()
    removed = [ln for ln in base if ln not in off]
    added = [ln for ln in off if ln not in base]
    box_rm = [ln for ln in removed if ".AddBox(" in ln]
    assert len(box_rm) == 12
    assert all("# bridge_" in ln or "# post_" in ln for ln in box_rm)
    other_rm = [ln for ln in removed if ".AddBox(" not in ln]
    assert len(other_rm) == 2
    assert any(ln.startswith("_near_y = [") for ln in other_rm)
    assert any(ln.startswith('mesh.AddLine("z", np.array([') for ln in other_rm)
    assert len(added) == 2
    assert any(ln.strip() == 'mesh.AddLine("z", np.array([H_SUB]))'
               for ln in added)
    ny_on = _near_y_values("\n".join(base))
    ny_off = _near_y_values("\n".join(off))
    assert len(ny_on) - len(ny_off) == 8
    dropped = {round(v, 15) for v in ny_on} - {round(v, 15) for v in ny_off}
    assert len(dropped) == 8    # 4 桥 × (yk−wb/2, yk+wb/2)，互不重复


def test_bridge_off_layout_is_valid():
    """去桥布局：恰 4 指+8 馈盒、无桥/柱名、z_lines 空、四端口仍在。"""
    lay_off = _c4_layout("lange", _params({"_bridge": 0.0}))
    lay_on = _c4_layout("lange", _params())
    names = [b[0] for b in lay_off["boxes"]]
    assert not [n for n in names if n.startswith(("bridge_", "post_"))]
    assert len([n for n in names if n.startswith("finger_")]) == 4
    assert len([n for n in names if n.startswith("feed_p")]) == 8
    assert lay_off["z_lines"] == []
    assert [p["nr"] for p in lay_off["ports"]] == [1, 2, 3, 4]
    assert lay_off["ports"] == lay_on["ports"]


def test_bridge_off_exec_geometry_and_mesh():
    """去桥渲染 exec 几何+网格段（#212，零仿真）：哨兵行可执行、桥面线不在
    最终 z 网格、H_SUB 恰 1 条（与 linspace 末点去重合并）、缝内内部线 ≥1。"""
    scope, prims = gh.load_geometry("lange", params=_params({"_bridge": 0.0}),
                                    mesh_mm=MESH_MM)
    zm = float(scope["H_SUB"])
    conductors = [p for p in prims if gh.is_conductor(p)]
    assert not [p for p in conductors if p.extent[2] > 1e-12]      # 无厚盒
    assert max(p.hi[2] for p in conductors) == zm                  # 无桥面金属
    zl = gh.mesh_lines(scope, "z")
    assert all(not bool(np.any(np.abs(zl - v) < 1e-9))
               for v in (0.000608, 0.000658))                      # 桥面线不在
    assert int(np.sum(np.abs(zl - zm) < 1e-9)) == 1                # 哨兵去重合并
    xl = gh.mesh_lines(scope, "x")
    fingers = sorted((b for b in _c4_layout("lange", _params({"_bridge": 0.0}))
                      ["boxes"] if b[0].startswith("finger_")), key=lambda b: b[1])
    for a, b in pairwise(fingers):
        lo, hi = float(a[4]), float(b[1])
        assert bool(np.min(np.abs(xl - lo)) < 1e-12)               # 缘入网 #311
        assert bool(np.min(np.abs(xl - hi)) < 1e-12)
        assert int(xl[(xl > lo + 1e-12) & (xl < hi - 1e-12)].size) >= 1
    for ax in "xyz":
        dmin = float(np.min(np.diff(gh.mesh_lines(scope, ax))) * 1e6)
        assert dmin >= 10.0, f"{ax} 轴最小线距 {dmin:.1f}µm < 10µm（#349）"
    labels = gh.component_labels(conductors)
    feed = {n: gh.containing_labels(gh.port_feed_point(pt), conductors, labels)
            for n, pt in gh.port_objects(scope).items()}
    assert set(feed[1]) & set(feed[2]) and set(feed[3]) & set(feed[4])
    assert not (set(feed[1]) & set(feed[4]))                       # 两组不短路
