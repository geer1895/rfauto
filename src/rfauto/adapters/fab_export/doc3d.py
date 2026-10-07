"""3D 交付：glTF + 等轴测 PDF + HTML 查看器（无 mplot3d，避免卡顿）.

审查项 R7（已修）：原型 write_html_viewer 里 ``B={a + 2 * wall}`` 复用了
a（应为 b + 2·wall），线框俯视截面被画成方形——本版修正。
审查项 R8（如实记录不修）：``vm.get("L") or 60.0`` 是 falsy-缺省惯语，
L=0 非物理入参不设防（#367 家族口径：数值可达 0 的面禁 or 缺省——此处
L=0 意味着零长零件，属上游配置错误，保持原型容错行为）。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.schema import DimsDocument


def _box_mesh(w: float, h: float, d: float, origin: tuple[float, float, float] = (0, 0, 0)):
    x0, y0, z0 = origin
    x1, y1, z1 = x0 + w, y0 + h, z0 + d
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    idx = [
        0, 1, 2, 0, 2, 3,
        4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1,
        1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3,
        3, 7, 4, 3, 4, 0,
    ]
    return v, idx


def write_gltf_from_dims(
    out_path: str | Path,
    dims: DimsDocument,
    *,
    length: float | None = None,
    use_wr90_shell: bool = True,
) -> Path:
    vm = {v.name: v.value for v in dims.variables}
    L = float(length or vm.get("L") or vm.get("length") or 60.0)
    a = float(vm.get("a") or 22.86)
    b = float(vm.get("b") or 10.16)
    wall = float(vm.get("wall") or 1.27)
    A, B = a + 2 * wall, b + 2 * wall

    all_pos: list[float] = []
    all_idx: list[int] = []
    base = 0
    for w, h, d, org in [
        (A, L, B, (0.0, 0.0, 0.0)),
        (a, max(L - 0.1, 1.0), b, (wall, 0.05, wall)),
    ]:
        v, idx = _box_mesh(w, h, d, org)
        for p in v:
            all_pos.extend(p)
        for i in idx:
            all_idx.append(i + base)
        base += len(v)

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "fab_export"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": dims.part_id}],
        "meshes": [{"name": dims.part_id, "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": 0, "uri": Path(out_path).with_suffix(".bin").name}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(all_pos) * 4, "target": 34962},
            {"buffer": 0, "byteOffset": len(all_pos) * 4, "byteLength": len(all_idx) * 4, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(all_pos) // 3,
                "type": "VEC3",
                "min": [min(all_pos[0::3] or [0]), min(all_pos[1::3] or [0]), min(all_pos[2::3] or [0])],
                "max": [max(all_pos[0::3] or [1]), max(all_pos[1::3] or [1]), max(all_pos[2::3] or [1])],
            },
            {"bufferView": 1, "componentType": 5125, "count": len(all_idx), "type": "SCALAR"},
        ],
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    bin_path = p.with_suffix(".bin")
    with bin_path.open("wb") as f:
        f.write(struct.pack(f"<{len(all_pos)}f", *all_pos))
        f.write(struct.pack(f"<{len(all_idx)}I", *all_idx))
    gltf["buffers"][0]["byteLength"] = bin_path.stat().st_size
    p.write_text(json.dumps(gltf, indent=2), encoding="utf-8")
    return p


def write_html_viewer(out_path: str | Path, dims: DimsDocument, gltf_rel: str = "model.gltf") -> Path:
    vm = {v.name: v.value for v in dims.variables}
    L = float(vm.get("L") or 60.0)
    a = float(vm.get("a") or 22.86)
    b = float(vm.get("b") or 10.16)
    wall = float(vm.get("wall") or 1.27)
    A = a + 2 * wall
    B = b + 2 * wall  # R7 修复：原型误写 a + 2 * wall（截面画成方形）
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>{dims.part_id} 3D 预览</title>
<style>body{{font-family:sans-serif;margin:16px;background:#111;color:#eee}}
canvas{{background:#1a1a1a;border:1px solid #333}}</style></head>
<body>
<h2>{dims.part_id} Rev{dims.rev} — 3D 预览（线框）</h2>
<p>单位 mm · glTF: <a href="{gltf_rel}">{gltf_rel}</a></p>
<canvas id="c" width="800" height="500"></canvas>
<script>
const L={L}, A={A}, B={B};
const pts=[[-A/2,0,-B/2],[A/2,0,-B/2],[A/2,L,-B/2],[-A/2,L,-B/2],
[-A/2,0,B/2],[A/2,0,B/2],[A/2,L,B/2],[-A/2,L,B/2]];
const edges=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
const ctx=document.getElementById('c').getContext('2d');
function draw(t){{
ctx.clearRect(0,0,800,500);
const ry=t*0.002, rx=0.5;
const proj=pts.map(p=>{{
let x=p[0],y=p[1]-L/2,z=p[2];
let x1=x*Math.cos(ry)-z*Math.sin(ry), z1=x*Math.sin(ry)+z*Math.cos(ry);
let y1=y*Math.cos(rx)-z1*Math.sin(rx), z2=y*Math.sin(rx)+z1*Math.cos(rx);
const s=280/(60+z2);
return [400+x1*s,250-y1*s];
}});
ctx.strokeStyle='#6cf';
for(const e of edges){{ctx.beginPath();ctx.moveTo(proj[e[0]][0],proj[e[0]][1]);ctx.lineTo(proj[e[1]][0],proj[e[1]][1]);ctx.stroke();}}
requestAnimationFrame(draw);}}
requestAnimationFrame(draw);
</script></body></html>
"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p


def write_3d_pdf(out_path: str | Path, dims: DimsDocument) -> Path:
    """工程 3D 参考 PDF：2D 等轴测线框（快速、无 mplot3d）+ 参数表."""
    try:
        import matplotlib  # type: ignore

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("3D PDF 需要 matplotlib") from e

    vm = {v.name: v.value for v in dims.variables}
    L = float(vm.get("L") or 60.0)
    a = float(vm.get("a") or 22.86)
    b = float(vm.get("b") or 10.16)
    wall = float(vm.get("wall") or 1.27)
    A, B = a + 2 * wall, b + 2 * wall

    fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))
    fig.suptitle(f"{dims.part_id} Rev{dims.rev}  3D reference (mm) — iso wireframe", fontsize=11)

    def iso(ax, w, h, d, ox=0, oy=0, title=""):
        # 简单斜二测投影
        def pr(x, y, z):
            return ox + (x - z) * 0.7071, oy + y - (x + z) * 0.3536

        corners = [
            (0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0),
            (0, 0, d), (w, 0, d), (w, h, d), (0, h, d),
        ]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        pts = [pr(*c) for c in corners]
        for e0, e1 in edges:
            ax.plot([pts[e0][0], pts[e1][0]], [pts[e0][1], pts[e1][1]], "k-", lw=0.8)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.axis("off")

    iso(axes[0][0], A, L, B, title="Shell")
    iso(axes[0][1], a, max(L - 1, 1), b, title="Cavity")
    iso(axes[1][0], A, L, B, title="Envelope")
    axes[1][1].axis("off")
    rows = [f"{v.name} = {v.value:g} mm [{v.tol_class}]" for v in dims.variables[:14]]
    axes[1][1].text(0.02, 0.98, "\n".join(rows) or "(no vars)", va="top", family="monospace", fontsize=9)
    axes[1][1].set_title("Parameters")

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(p), dpi=120)
    plt.close(fig)
    return p
