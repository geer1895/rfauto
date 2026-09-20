"""sma_launcher 精确几何接触审计（真机 FAIL 根治·离线先行，#1b/#212）。

背景：pt2 真机 FAIL（|S11|=+5.42dB 非物理、
|S21|≈−375dB、port2 表观 εeff≈2866）。渲染代码只读审计得到三条结构线索
（按 #221⑥ 标"假设/待证"，本脚本以**精确实体相交**（圆柱/柱壳截面圆盘/
圆环-矩形距离判据，禁 bbox 近似）出逐导体接触图证实/证伪）：
  H1  地侧针与接地壳/接地墙无实接触（净距 1.489mm）——串馈集总口基准端悬空；
  H2  引脚柱盒与壳底壁实交叠（y 重叠 0.635mm × z[0.508,0.855] 全落柱盒 z 域）
      ——信号链接地壳短路（与 |S21|≈−375dB 精确零传输一致）；
  H4  port1 集总口落在 y-min PML_8 吸收层内（前 8 条网格线）；
  H5  域顶 MUR 边界与壳顶净距过小（0.25mm=1 cell）。
（H3 文献几何对照见 docs/rf_template_references.md SMA 节。）

接触图内核（exact_contact/exact_components）供
tests/unit/test_sma_launcher_template.py 复用；纪律 1b：归因在接触图证实前
一律"假设/待证"。

运行（工作区根目录）：
  .venv/Scripts/python.exe scripts/diag_sma_launcher.py
  .venv/Scripts/python.exe scripts/diag_sma_launcher.py --json <out.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters.openems_templates import (  # noqa: E402
    SMA_LAUNCHER_NOMINAL,
    render_script,
)

TOL = 1e-9   # m 级接触容差（远小于网格 cell）


@dataclass
class Solid:
    """一个 CSXCAD 原语的精确实体（米）：盒 / 轴向柱 / 轴向柱壳。"""

    prop: str            # 所属 CSXCAD 属性名
    kind: str            # 属性类型串：Metal / Material / LumpedElement / ...
    shape: str           # "box" | "cyl" | "shell"
    lo: np.ndarray       # 包围盒下角
    hi: np.ndarray       # 包围盒上角
    axis: int | None = None          # 柱/柱壳轴向（box=None）
    center: tuple[float, float] | None = None  # 横截面圆心（轴外两轴，升序）
    r_out: float = 0.0                # 柱半径 / 柱壳外径
    r_in: float = 0.0                 # 柱壳内径（cyl 恒 0）
    priority: int = 0
    # 被更高优先级介质柱系挖空的孔径（金属盒专用，如连接器体前脸的同轴孔）：
    # (轴向, 截面圆心, 孔半径, 轴向下界, 轴向上界)
    bore: tuple[int, tuple[float, float], float, float, float] | None = None

    @property
    def z_min(self) -> float:
        return float(self.lo[2])

    @property
    def z_max(self) -> float:
        return float(self.hi[2])


def extract_solids(csx) -> list[Solid]:
    """CSXCAD 属性表 → 精确实体列表（box=1 / cyl=5 / shell=6）。"""
    out: list[Solid] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        kind = str(prop.GetTypeString())
        name = str(prop.GetName())
        for prim in prop.GetAllPrimitives():
            ptype = str(prim.GetType())
            start = np.asarray(prim.GetStart(), dtype=float)
            stop = np.asarray(prim.GetStop(), dtype=float)
            lo = np.minimum(start, stop)
            hi = np.maximum(start, stop)
            prio = int(prim.GetPriority())
            if ptype == "1":
                out.append(Solid(name, kind, "box", lo, hi, priority=prio))
                continue
            if ptype not in ("5", "6"):
                raise ValueError(f"未支持的 CSXCAD 原语类型 {ptype}（{name}）")
            axis = int(np.argmax(hi - lo))
            t_ax = tuple(j for j in range(3) if j != axis)
            r_mid = float(prim.GetRadius())
            width = float(prim.GetShellWidth()) if ptype == "6" else 0.0
            r_in = r_mid - width / 2.0
            r_out = r_mid + width / 2.0
            center = (float(lo[t_ax[0]]), float(lo[t_ax[1]]))
            # 包围盒按外径在横向两轴外扩（真实包围盒；截面判据用 center/r）
            for j in t_ax:
                lo[j] -= r_out
                hi[j] += r_out
            out.append(Solid(name, kind, "shell" if ptype == "6" else "cyl",
                             lo, hi, axis=axis, center=center,
                             r_out=r_out, r_in=r_in, priority=prio))
    _attach_bores(out)
    return out


def _attach_bores(solids: list[Solid]) -> None:
    """金属盒被更高优先级的介质柱系（PTFE 环/柱）贯穿 → 记孔径（CSXCAD 优先级
    挖空语义：盒内 r ≤ 介质外径 的区域不是金属）。只对同轴柱系（轴向外扩后
    包围盒相交）生效；孔半径取介质外径。"""
    for box in solids:
        if box.shape != "box" or box.kind != "Metal":
            continue
        for mat in solids:
            if mat.kind != "Material" or mat.shape == "box" or mat.priority <= box.priority:
                continue
            if not bool(np.all(np.minimum(box.hi, mat.hi) - np.maximum(box.lo, mat.lo) >= -TOL)):
                continue
            assert mat.axis is not None and mat.center is not None
            k = mat.axis
            box.bore = (k, mat.center, mat.r_out, float(mat.lo[k]), float(mat.hi[k]))
            break


def _iv_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """一维区间交叠长度（<0 = 分离，恰触=0）。"""
    return min(a1, b1) - max(a0, b0)


def _dist_point_rect(c: tuple[float, float], rect: np.ndarray) -> float:
    """点到轴对齐矩形最小距离（矩形 [lo_x,hi_x]×[lo_y,hi_y]，内点=0）。"""
    dx = max(rect[0, 0] - c[0], 0.0, c[0] - rect[1, 0])
    dy = max(rect[0, 1] - c[1], 0.0, c[1] - rect[1, 1])
    return float(np.hypot(dx, dy))


def _dist_rect_max(c: tuple[float, float], rect: np.ndarray) -> float:
    """点到矩形最大距离（= 到四角最大值）。"""
    return max(float(np.hypot(x - c[0], y - c[1]))
               for x in (rect[0, 0], rect[1, 0])
               for y in (rect[0, 1], rect[1, 1]))


def _rect_in_disk(rect: np.ndarray, c: tuple[float, float],
                  r: float) -> bool:
    """矩形整体落在圆内（四角全入，凸性充分）。"""
    return all(np.hypot(x - c[0], y - c[1]) <= r + TOL
               for x in (rect[0, 0], rect[1, 0])
               for y in (rect[0, 1], rect[1, 1]))


def _disk_in_disk(c1, r1, c2, r2) -> bool:
    return float(np.hypot(c1[0] - c2[0], c1[1] - c2[1])) + r1 <= r2 + TOL


def _bbox_contact(a: Solid, b: Solid) -> bool:
    lo = np.maximum(a.lo, b.lo)
    hi = np.minimum(a.hi, b.hi)
    if not bool(np.all(hi - lo >= -TOL)):
        return False
    # 挖空孔径：交叠区若整体落在某方的孔径圆柱内（横截面矩形 ⊂ 孔圆盘、轴向在
    # 孔范围内）→ 该处不是金属，不算接触
    for s in (a, b):
        if s.bore is None:
            continue
        k, c, r, ax_lo, ax_hi = s.bore
        if lo[k] < ax_lo - TOL or hi[k] > ax_hi + TOL:
            continue
        t_ax = tuple(j for j in range(3) if j != k)
        rect = np.array([[lo[t_ax[0]], lo[t_ax[1]]], [hi[t_ax[0]], hi[t_ax[1]]]])
        if _rect_in_disk(rect, c, r):
            return False
    return True


def _cyl_vs_box(cyl: Solid, box: Solid) -> bool:
    """轴向柱/柱壳 vs 盒：轴向区间交叠 + 横截面圆盘/圆环 vs 矩形精确判据
    （盒带孔径且柱盘整体在孔内、轴向交叠在孔范围内 → 不接触）。"""
    k = cyl.axis
    assert k is not None and cyl.center is not None
    if _iv_overlap(cyl.lo[k], cyl.hi[k], box.lo[k], box.hi[k]) < -TOL:
        return False
    if box.bore is not None and cyl.shape == "cyl" and box.bore[0] == k:
        _k, c, r, ax_lo, ax_hi = box.bore
        ov_lo = max(cyl.lo[k], box.lo[k])
        ov_hi = min(cyl.hi[k], box.hi[k])
        if ov_lo >= ax_lo - TOL and ov_hi <= ax_hi + TOL and \
                _disk_in_disk(cyl.center, cyl.r_out, c, r):
            return False
    t_ax = tuple(j for j in range(3) if j != k)
    rect = np.array([[box.lo[t_ax[0]], box.lo[t_ax[1]]],
                     [box.hi[t_ax[0]], box.hi[t_ax[1]]]])
    dmin = _dist_point_rect(cyl.center, rect)
    if cyl.shape == "cyl":
        return dmin <= cyl.r_out + TOL
    # 圆环 ∩ 矩形 ≠ ∅ ⟺ 最近点 ≤ 外径 且 最远点 ≥ 内径（矩形连通，距离连续）
    return dmin <= cyl.r_out + TOL and \
        _dist_rect_max(cyl.center, rect) >= cyl.r_in - TOL


def _cyl_vs_cyl(a: Solid, b: Solid) -> bool:
    """同轴向柱系互判：轴向交叠 + 横截面圆盘/圆环互交（同心精确；非同心
    圆环按外盘保守近似——只会多报接触，不会漏报短路）。"""
    if a.axis != b.axis:
        return _bbox_contact(a, b)
    k = a.axis
    assert k is not None and a.center is not None and b.center is not None
    if _iv_overlap(a.lo[k], a.hi[k], b.lo[k], b.hi[k]) < -TOL:
        return False
    d = float(np.hypot(a.center[0] - b.center[0], a.center[1] - b.center[1]))

    def reach(s: Solid) -> tuple[float, float]:
        # s 截面内各点到另一轴心距离的可达区间
        if s.shape == "shell" and d <= TOL:
            return s.r_in, s.r_out
        return max(d - s.r_out, 0.0), d + s.r_out

    lo_a, hi_a = reach(a)
    lo_b, hi_b = reach(b)
    if d <= TOL:
        # 同心：a 的径向区间与 b 的径向区间相交即接触
        return lo_a <= hi_b + TOL and lo_b <= hi_a + TOL
    # 非同心：b 的径向带 [r_in,r_out] 与 a 可达距离区间相交（对盘 r_in=0）
    return lo_a <= b.r_out + TOL and hi_a >= b.r_in - TOL and \
        lo_b <= a.r_out + TOL and hi_b >= a.r_in - TOL


def exact_contact_pair(a: Solid, b: Solid) -> bool:
    """两实体精确相交判定（恰触=接触）：box-box 区间；柱系-盒 截面几何；
    柱系-柱系 同轴精确（本模板柱系全部沿 y 同轴）。"""
    if a.shape == "box" and b.shape == "box":
        return _bbox_contact(a, b)
    if a.shape == "box":
        return _cyl_vs_box(b, a)
    if b.shape == "box":
        return _cyl_vs_box(a, b)
    return _cyl_vs_cyl(a, b)


def touches_pec_floor(s: Solid, z0: float = 0.0) -> bool:
    return s.z_min <= z0 + TOL


@dataclass
class ContactGraph:
    solids: list[Solid]
    pairs: list[tuple[int, int]] = field(default_factory=list)

    def components(self) -> list[int]:
        parent = list(range(len(self.solids)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, j in self.pairs:
            parent[find(i)] = find(j)
        return [find(i) for i in range(len(self.solids))]


def build_contact_graph(solids: list[Solid],
                        kinds: tuple[str, ...] = ("Metal", "LumpedElement"),
                        include_floor: bool = True) -> ContactGraph:
    """导体实体接触图（kinds 限参与实体；include_floor 挂 z≤0 PEC 底板节点）。"""
    nodes = [s for s in solids if s.kind in kinds]
    g = ContactGraph(solids=nodes)
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if exact_contact_pair(nodes[i], nodes[j]):
                g.pairs.append((i, j))
    if include_floor:
        floor = Solid("PEC_FLOOR", "Boundary", "box",
                      np.array([-1.0, -1.0, -0.5]), np.array([1.0, 1.0, 0.0]))
        nodes.append(floor)
        g.solids = nodes
        idx = len(nodes) - 1
        for i, s in enumerate(nodes[:-1]):
            if touches_pec_floor(s):
                g.pairs.append((i, idx))
    return g


def load_geometry_solids(params: dict | None = None, mesh_mm: float = 0.4):
    """渲染 sma_launcher → exec 几何段 → (scope, 精确实体列表)。"""
    resolved = dict(SMA_LAUNCHER_NOMINAL if params is None else params)
    text = render_script("sma_launcher", resolved, (2.25, 2.75),
                         mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_sma_diag_sim.py")}
    exec(compile(head, "sma_diag", "exec"), scope)
    return scope, extract_solids(scope["CSX"])


def structural_checks(scope: dict, g: ContactGraph) -> dict:
    """结构判据（新几何属性名锚定；旧几何启发式回退只服务根治前留档）。"""
    names = [s.prop for s in g.solids]
    comp = g.components()
    by_comp: dict[int, list[str]] = {}
    for i, s in enumerate(g.solids):
        by_comp.setdefault(comp[i], []).append(s.prop)

    report: dict = {"components": {str(k): v for k, v in by_comp.items()}}
    # 金属-only 图（剔除集总桥）：信号链 {pin, strip} 与地链 {shell, gnd, 底板}
    # 必须是两个互不相交的分量；再含桥的全图里两链必须被桥接为一体
    g_metal = build_contact_graph([s for s in g.solids if s.kind == "Metal"],
                                  kinds=("Metal",), include_floor=True)
    comp_m = g_metal.components()

    def comp_metal(name: str) -> set[int]:
        return {comp_m[i] for i, s in enumerate(g_metal.solids) if s.prop == name}

    signal_names = [n for n in ("sma_pin", "sma_strip") if n in names]
    ground_names = [n for n in ("sma_shell", "sma_gnd", "sma_face", "PEC_FLOOR")
                    if n in names]
    signal_m = set().union(*[comp_metal(n) for n in signal_names]) if signal_names else set()
    ground_m = set().union(*[comp_metal(n) for n in ground_names]) if ground_names else set()
    report["signal_chain_one_component"] = len(signal_m) == 1
    report["ground_chain_one_component"] = len(ground_m) == 1
    report["short_between_signal_and_ground"] = bool(signal_m & ground_m)
    lumped = [i for i, s in enumerate(g.solids) if s.kind == "LumpedElement"]
    report["port1_bridges_both_chains"] = bool(
        signal_names and ground_names and lumped
        and all(comp[i] == comp[lumped[0]] for i, s in enumerate(g.solids)
                if s.prop in signal_names + ground_names))
    # 根治前几何（sma_coax 单属性混装壳/针/柱/墙）：按形状+位置启发式拆角色，
    # 直接回答 H1（地侧针悬空）/H2（引脚柱-壳短路）——留档用
    if "sma_coax" in names and "sma_shell" not in names:
        coax = [(i, s) for i, s in enumerate(g.solids) if s.prop == "sma_coax"]
        shell_i = [i for i, s in coax if s.shape == "shell"]
        cyls = sorted([(i, s) for i, s in coax if s.shape == "cyl"],
                      key=lambda t: float(t[1].hi[1]))
        boxes = [(i, s) for i, s in coax if s.shape == "box"]
        walls_i = [i for i, s in boxes if s.z_min <= TOL]
        column_i = [i for i, s in boxes if s.z_min > TOL]
        floor_i = [i for i, s in enumerate(g.solids) if s.prop == "PEC_FLOOR"]
        stub_i, driven_i = ([cyls[0][0]], [cyls[-1][0]]) if len(cyls) >= 2 \
            else ([], [])
        pair_set = {tuple(p) for p in g.pairs} | {(j, i) for i, j in g.pairs}

        def touch(ia: list[int], ib: list[int]) -> bool:
            return any((i, j) in pair_set for i in ia for j in ib)

        report["legacy_H1_stub_touches_shell"] = touch(stub_i, shell_i)
        report["legacy_H1_stub_touches_walls"] = touch(stub_i, walls_i)
        report["legacy_H1_stub_touches_floor"] = touch(stub_i, floor_i)
        report["legacy_H1_stub_grounded_any"] = any(
            comp[i] in {comp[j] for j in shell_i + walls_i + floor_i}
            for i in stub_i)
        report["legacy_H2_column_touches_shell"] = touch(column_i, shell_i)
        report["legacy_H2_driven_touches_shell"] = touch(driven_i, shell_i)
        report["legacy_walls_touch_shell"] = touch(walls_i, shell_i)
        report["legacy_walls_touch_floor"] = touch(walls_i, floor_i)
    # H4：port1 是否整体在 y-min PML_8（前 8 条网格线）内
    p1 = scope.get("_port1")
    if p1 is not None:
        y_lines = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
        pml_edge = float(y_lines[8])
        y0 = float(min(p1.start[1], p1.stop[1]))
        y1 = float(max(p1.start[1], p1.stop[1]))
        report["pml8_edge_y_m"] = pml_edge
        report["port1_y_m"] = [y0, y1]
        report["port1_inside_pml8"] = bool(y1 <= pml_edge + TOL)
    z_lines = np.asarray(scope["mesh"].GetLines("z"), dtype=float)
    z_top = float(z_lines[-1])
    z_max_solid = max(s.z_max for s in g.solids if s.kind == "Metal")
    report["domain_top_z_m"] = z_top
    report["max_metal_z_m"] = z_max_solid
    report["top_clearance_m"] = z_top - z_max_solid
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="报告落盘路径（JSON）")
    ap.add_argument("--mesh", type=float, default=0.4)
    args = ap.parse_args()
    scope, solids = load_geometry_solids(mesh_mm=args.mesh)
    g = build_contact_graph(solids)
    comp = g.components()
    print("== 导体接触对（精确判据）==")
    for i, j in g.pairs:
        a, b = g.solids[i], g.solids[j]
        print(f"  {a.prop}({a.shape}) -- {b.prop}({b.shape})")
    print("== 连通分量 ==")
    by_comp: dict[int, list[str]] = {}
    for i, s in enumerate(g.solids):
        by_comp.setdefault(comp[i], []).append(f"{s.prop}({s.shape})")
    for k, v in sorted(by_comp.items()):
        print(f"  #{k}: {v}")
    rep = structural_checks(scope, g)
    print("== 结构判据 ==")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps({"pairs": [[g.solids[i].prop, g.solids[i].shape,
                                   g.solids[j].prop, g.solids[j].shape]
                                  for i, j in g.pairs], **rep},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
