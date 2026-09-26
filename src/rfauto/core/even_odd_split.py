"""对称结构奇偶模分解几何变换内核（纯函数零 IO；DP-14 Y1，2026-09-24）。

规格：docs/plan_deepdive_specs_20260924.md §14.3；判据书：
runs/df6_dp14y1/criteria.md（判据预声明）。口径权威：
docs/rf_template_references.md §13.1（耦合线 cline_coupler）/§13.2
（两节分支线 branchline_2sect）。

职责边界（铁律 7：数值只在确定性内核；本模块是"参数化布局几何变换"，
不是渲染文本改写——不感知 openems_templates 渲染器）：

- 对称性检测：镜像反射多重集与原布局逐位比对（反射=轴坐标取负，IEEE 取负
  精确），任何盒/端口镜像配对失败 → SymmetryError（判据 c：显式报错不静默
  降级）；
- 半模型裁剪：偶模=PMC 磁壁（对称面开路口径）、奇模=PEC 电壁（短路口径）；
  跨对称面的盒裁到 [lo, 0]、跨面端口线段裁到下半段（λ/4 支臂 → λ/8 半桩
  口径，13.2）+ 裁切面边界标记；
- 端口语义改写表：保侧端口附模阻抗注记（值由调用方传入并带来源——耦合结构
  Z0e/Z0o 从 core.coupled_microstrip 的 KJ 闭式直接读，本内核不自算阻抗）；
- #310 家族 bounding_box 自审守卫：split→镜像重装配逐位还原 == 恒等、
  连通分量计数、孤儿端口、半模型 bbox 轴侧 max≤0。

两种"半模型"语义必须显式分派（#154 家族防线，见 criteria.md §0）：
对称面在两导体**之间**（cline：平面作用于缝内场，导体不跨面、端口改模阻抗
注释）vs 对称面**切割**导体（branchline：跨面盒裁半、跨面处开路/短路桩）。

布局 schema（纯 dict；长度单位不敏感——仓内几何单一事实源 _c4_layout 为米）::

    {
        "axis": "x" | "y",            # 对称面法向轴；对称面 = 该轴坐标 0
        "boxes": [{"name": str, "kind": "metal"|"via",  # kind 缺省 "metal"
                   "x0", "y0", "z0", "x1", "y1", "z1": float}],
        "ports": [{"nr": int, "start": [x, y, z], "stop": [x, y, z],
                   "label"?: str, "prop_dir"?: "x"|"y", ...额外键原样保留}],
    }

重装配恒等的精确性（#310 家族逐位口径）：盒裁剪只动轴区间端点（置 0 精确）；
跨面端口交点每个镜像对只插值一次（对侧取逐位取负，input 序确定性缓存），
故 split→镜像重装配与原布局的几何多重集比对为 exact float 逐位相等。

确定性：内核无任何随机源（random_state 无关）；零 IO、不 import
numpy/scipy/skrf（纯 math/cmath）。耦合微带闭式（裁判）在
core/coupled_microstrip.py:98 coupled_microstrip_even_odd_ohm（本模块只读
复用方=service 层）。
"""

from __future__ import annotations

import cmath
import math
from collections import Counter
from collections.abc import Iterable
from typing import Any

__all__ = [
    "BC_NOTE",
    "MODES",
    "PLANE_BC",
    "SymmetryError",
    "classify_box",
    "classify_port",
    "connectivity_components",
    "layout_from_box_tuples",
    "mirror_reassembly_checksum",
    "normalize_box",
    "normalize_layout",
    "orphan_ports",
    "port_rewrite_table",
    "reflect_box",
    "reflect_port",
    "split_guards",
    "split_half_model",
    "stub_input_admittance",
    "stub_shunt_abcd",
    "symmetry_report",
    "transmission_line_abcd",
]

MODES: tuple[str, ...] = ("even", "odd")
PLANE_BC: dict[str, str] = {"even": "PMC", "odd": "PEC"}
BC_NOTE: dict[str, str] = {
    "PMC": "磁壁（对称面 H 切向=0）→ 开路口径：跨面元=开路半桩 Y_in=+jY0·tan(θ/2)",
    "PEC": "电壁（对称面 E 切向=0）→ 短路口径：跨面元=短路半桩 Y_in=−jY0·cot(θ/2)",
}
_AXES = ("x", "y")


class SymmetryError(ValueError):
    """布局不满足镜像对称（判据 c：显式报错，不静默降级）。"""


# ── 布局归一化（#140 同族：入口先收敛入参形态）───────────────────────────────

def _as_float(v: Any, ctx: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx} 不是数值: {v!r}") from exc
    if not math.isfinite(f):
        raise ValueError(f"{ctx} 非有限: {v!r}")
    return f


def normalize_box(box: Any) -> dict[str, Any]:
    """盒入参收敛：7 元组（名,x0,y0,z0,x1,y1,z1，_c4_layout 口径）或 dict。"""
    if isinstance(box, dict):
        b = dict(box)
        name = str(b.get("name", ""))
        coords: dict[str, float] = {}
        for k in ("x0", "y0", "z0", "x1", "y1", "z1"):
            coords[k] = _as_float(b[k], f"盒 {name!r} 的 {k}")
        for ax in ("x", "y", "z"):
            lo, hi = coords[f"{ax}0"], coords[f"{ax}1"]
            if lo > hi:
                raise ValueError(f"盒 {name!r} 的 {ax} 区间反序: [{lo}, {hi}]")
        return {"name": name, "kind": str(b.get("kind", "metal")), **coords}
    seq = tuple(box)
    if len(seq) != 7:
        raise ValueError(f"盒元组须 7 元 (名,x0,y0,z0,x1,y1,z1)，得 {len(seq)} 元")
    name = str(seq[0])
    vals = [_as_float(v, f"盒 {name!r} 坐标") for v in seq[1:]]
    for ax, lo, hi in (("x", vals[0], vals[3]), ("y", vals[1], vals[4]),
                       ("z", vals[2], vals[5])):
        if lo > hi:
            raise ValueError(f"盒 {name!r} 的 {ax} 区间反序: [{lo}, {hi}]")
    return {"name": name, "kind": "metal", "x0": vals[0], "y0": vals[1],
            "z0": vals[2], "x1": vals[3], "y1": vals[4], "z1": vals[5]}


def _normalize_port(port: Any) -> dict[str, Any]:
    if not isinstance(port, dict):
        raise ValueError(f"端口须为 dict，得 {type(port).__name__}")
    p = dict(port)
    if "nr" not in p:
        raise ValueError(f"端口缺 nr: {p!r}")
    out: dict[str, Any] = {"nr": int(p["nr"])}
    for key in ("start", "stop"):
        seq = tuple(p[key])
        if len(seq) != 3:
            raise ValueError(f"端口 {out['nr']} 的 {key} 须 3 元 [x,y,z]")
        out[key] = [_as_float(v, f"端口 {out['nr']} {key}") for v in seq]
    for k, v in p.items():
        if k not in ("nr", "start", "stop"):
            out[k] = v
    return out


def normalize_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """布局入参收敛+校验（axis/盒/端口；输出序=输入序，确定性）。"""
    if not isinstance(layout, dict):
        raise ValueError("布局须为 dict")
    axis = str(layout.get("axis", ""))
    if axis not in _AXES:
        raise ValueError(f"axis 须为 {_AXES}（对称面法向轴；对称面=该轴坐标 0），得 {axis!r}")
    boxes = [normalize_box(b) for b in layout.get("boxes", ())]
    ports = [_normalize_port(p) for p in layout.get("ports", ())]
    return {"axis": axis, "boxes": boxes, "ports": ports}


def layout_from_box_tuples(
    axis: str,
    boxes: Iterable[tuple[str, float, float, float, float, float, float]],
    ports: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """_c4_layout 口径（盒 7 元组+端口 dict）→ 内核布局 schema 的便捷转换。"""
    return normalize_layout({"axis": axis, "boxes": list(boxes), "ports": list(ports)})


# ── 分类 / 反射 ───────────────────────────────────────────────────────────────

def _axis_idx(axis: str) -> int:
    return 0 if axis == "x" else 1


def _box_interval(box: dict[str, Any], axis: str) -> tuple[float, float]:
    return float(box[f"{axis}0"]), float(box[f"{axis}1"])


def classify_box(box: dict[str, Any], axis: str) -> str:
    """盒分类："lower"（全在 −半，含触面）/"upper"/"crossing"/"on_plane"。

    严格比较无容差（确定性）：跨面=lo<0<hi；lo==hi==0 → "on_plane"（躺在
    对称面内的退化盒，两半共有）；hi≤0 → "lower"；lo≥0 → "upper"。
    """
    lo, hi = _box_interval(box, axis)
    if lo < 0.0 < hi:
        return "crossing"
    if lo == 0.0 and hi == 0.0:
        return "on_plane"
    if hi <= 0.0:
        return "lower"
    return "upper"


def classify_port(port: dict[str, Any], axis: str) -> str:
    """端口按积分线段 AABB 的轴区间分类（同 classify_box 口径）。"""
    s, e = tuple(float(v) for v in port["start"]), tuple(float(v) for v in port["stop"])
    k = _axis_idx(axis)
    a, b = min(s[k], e[k]), max(s[k], e[k])
    if a < 0.0 < b:
        return "crossing"
    if a == 0.0 and b == 0.0:
        return "on_plane"
    if b <= 0.0:
        return "lower"
    return "upper"


def reflect_box(box: dict[str, Any], axis: str) -> dict[str, Any]:
    """盒镜像反射（轴坐标取负并交换端点；IEEE 取负精确，逐位可逆）。"""
    lo, hi = _box_interval(box, axis)
    out = dict(box)
    out[f"{axis}0"], out[f"{axis}1"] = -hi, -lo
    return out


def reflect_port(port: dict[str, Any], axis: str) -> dict[str, Any]:
    """端口镜像反射（两端点轴坐标取负；其余键原样保留）。"""
    out = dict(port)
    idx = _axis_idx(axis)
    for key in ("start", "stop"):
        pt = list(out[key])
        pt[idx] = -float(pt[idx])
        out[key] = pt
    return out


# ── 几何键（对称性/重装配多重集比对的最小单位；名字/编号不进键）──────────────

def _box_geom_key(box: dict[str, Any]) -> tuple:
    return (box["kind"], float(box["x0"]), float(box["y0"]), float(box["z0"]),
            float(box["x1"]), float(box["y1"]), float(box["z1"]))


def _port_geom_key(port: dict[str, Any]) -> tuple:
    """端口几何键=积分线段 AABB 的规范形（各轴区间排序二元组+prop_dir）。

    用 AABB（面区域）而非端点逐位：MSLPort 积分线的对角走向是提取约定
    （同一物理端口面的线可以连 face 的不同角），镜像对称性活在面区域。
    """
    s, e = tuple(float(v) for v in port["start"]), tuple(float(v) for v in port["stop"])
    spans = tuple((min(s[k], e[k]), max(s[k], e[k])) for k in range(3))
    return (spans, str(port.get("prop_dir", "")))


def symmetry_report(layout: dict[str, Any]) -> dict[str, Any]:
    """镜像对称性检测报告（不抛异常；判定方调用后自行决定 raise/降级）。

    口径：全体盒（端口）的镜像反射多重集必须与原多重集**逐位相等**
    （几何键比对，名字/编号不要求成对相同——如 line_a↔line_b、端口 1↔3）。
    """
    lay = normalize_layout(layout)
    axis = lay["axis"]
    boxes, ports = lay["boxes"], lay["ports"]
    refl_keys_b = [_box_geom_key(reflect_box(b, axis)) for b in boxes]
    orig_b = Counter(_box_geom_key(b) for b in boxes)
    refl_b = Counter(refl_keys_b)
    diff_b = (orig_b - refl_b) + (refl_b - orig_b)
    bad_b = sorted({b["name"] for b, rk in zip(boxes, refl_keys_b, strict=True)
                    if _box_geom_key(b) in diff_b or rk in diff_b})
    refl_keys_p = [_port_geom_key(reflect_port(p, axis)) for p in ports]
    orig_p = Counter(_port_geom_key(p) for p in ports)
    refl_p = Counter(refl_keys_p)
    diff_p = (orig_p - refl_p) + (refl_p - orig_p)
    bad_p = sorted({str(p.get("label", p["nr"]))
                    for p, rk in zip(ports, refl_keys_p, strict=True)
                    if _port_geom_key(p) in diff_p or rk in diff_p})
    return {
        "ok": not diff_b and not diff_p,
        "axis": axis,
        "n_boxes": len(boxes),
        "n_ports": len(ports),
        "unmatched_box_names": bad_b,
        "unmatched_port_labels": bad_p,
    }


def _require_symmetric(layout: dict[str, Any]) -> dict[str, Any]:
    rep = symmetry_report(layout)
    if not rep["ok"]:
        raise SymmetryError(
            f"布局不满足镜像对称（axis={rep['axis']}）：不配对盒="
            f"{rep['unmatched_box_names']}，不配对端口={rep['unmatched_port_labels']}"
            "（判据 c：显式报错）")
    return layout


# ── 半模型裁剪 ───────────────────────────────────────────────────────────────

def _clip_point(pt_lo: list[float], pt_hi: list[float], axis: str) -> list[float]:
    """线段在轴坐标 0 处的交点（pt_lo 轴坐标 <0 < pt_hi 轴坐标）。"""
    idx = _axis_idx(axis)
    s = float(pt_lo[idx])
    e = float(pt_hi[idx])
    t = (0.0 - s) / (e - s)
    out = [pt_lo[k] + t * (pt_hi[k] - pt_lo[k]) for k in range(3)]
    out[idx] = 0.0        # 对称面按定义恰在 0（吸附精确值，重装配逐位可还原）
    return out


def _port_segment_key(port: dict[str, Any]) -> tuple:
    """端口线段键（端点排序规范形；区分同一 AABB 的不同对角线段）。"""
    pts = sorted(tuple(float(v) for v in port[k]) for k in ("start", "stop"))
    return (pts[0], pts[1])


def _crossing_port_lower_half(
    port: dict[str, Any], axis: str,
    cache: dict[tuple, list[float]],
) -> dict[str, Any]:
    """跨面端口 → 下半段（保轴坐标 ≤0 的端点+面上交点；half_width 标记）。

    每个镜像对的面交点只插值一次（首见端口，线段键缓存），对侧端口取逐位
    取负（input 序处理=确定性），保证镜像重装配语义一致。注意：镜像查找用
    线段键而非 AABB 键——AABB 规范形会把互为镜像的两条对角线段折叠成同键。
    """
    idx = _axis_idx(axis)
    s, e = list(port["start"]), list(port["stop"])
    key_self = _port_segment_key(port)
    if key_self in cache:
        plane_pt = list(cache[key_self])
    else:
        key_refl = _port_segment_key(reflect_port(port, axis))
        if key_refl in cache:      # 对侧已算：逐位取负（轴坐标吸附回 +0.0）
            cached = cache[key_refl]
            plane_pt = [-float(cached[k]) for k in range(3)]
            plane_pt[idx] = 0.0
            cache[key_self] = plane_pt
        else:
            s_ax, e_ax = float(s[idx]), float(e[idx])
            lo_pt, hi_pt = (s, e) if s_ax < e_ax else (e, s)
            plane_pt = _clip_point(lo_pt, hi_pt, axis)
            cache[key_self] = plane_pt
    lower = s if float(s[idx]) <= 0.0 else e
    out = dict(port)
    out["start"] = list(lower)
    out["stop"] = plane_pt
    out["half_width"] = True
    out["full_segment"] = [list(s), list(e)]
    return out


def split_half_model(layout: dict[str, Any], mode: str) -> dict[str, Any]:
    """对称布局 → 单侧半模型（偶=PMC/奇=PEC；先过对称性检测，破坏即 raise）。

    规则（criteria.md §0）：
    - 盒：lower/on_plane 原样保留；upper 弃（镜像冗余）；crossing 裁到
      [lo, 0] 并标记 {"clipped": True, "plane_face": "hi", "span_full"/"span_half"}
      （λ/4 支臂 → λ/8 半桩口径）；
    - 端口：lower 保留；upper 弃；crossing 裁到下半段 + {"half_width": True,
      "full_segment"}（跨面端口改半宽口径）；
    - 对称面边界标记：plane_boundary = {axis, mode, bc, faces=[{box, face}]}。
    """
    if mode not in MODES:
        raise ValueError(f"mode 须为 {MODES}，得 {mode!r}")
    lay = _require_symmetric(normalize_layout(layout))
    axis = lay["axis"]
    bc = PLANE_BC[mode]
    out_boxes: list[dict[str, Any]] = []
    faces: list[dict[str, str]] = []
    for b in lay["boxes"]:
        cls = classify_box(b, axis)
        if cls == "upper":
            continue
        if cls == "crossing":
            lo, hi = _box_interval(b, axis)
            clipped = dict(b)
            clipped[f"{axis}1"] = 0.0
            clipped["clipped"] = True
            clipped["plane_face"] = "hi"
            clipped["span_full"] = hi - lo
            clipped["span_half"] = -lo
            out_boxes.append(clipped)
            faces.append({"box": b["name"], "face": "hi"})
            continue
        if cls == "on_plane":
            marked = dict(b)
            marked["on_plane"] = True
            out_boxes.append(marked)
            continue
        out_boxes.append(dict(b))
    cache: dict[tuple, list[float]] = {}
    out_ports: list[dict[str, Any]] = []
    dropped: list[int] = []
    for p in lay["ports"]:
        cls = classify_port(p, axis)
        if cls == "upper":
            dropped.append(int(p["nr"]))
            continue
        if cls == "crossing":
            out_ports.append(_crossing_port_lower_half(p, axis, cache))
            continue
        out_ports.append(dict(p))
    return {
        "mode": mode,
        "bc": bc,
        "bc_note": BC_NOTE[bc],
        "axis": axis,
        "boxes": out_boxes,
        "ports": out_ports,
        "dropped_port_nrs": sorted(dropped),
        "plane_boundary": {"axis": axis, "mode": mode, "bc": bc, "faces": faces},
    }


def port_rewrite_table(
    layout: dict[str, Any],
    mode_impedances: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """端口语义改写表（原布局逐端口：处置/镜像配对/模阻抗注记槽）。

    mode_impedances（可选，由 service 层传入并带来源）：{"even": {...},
    "odd": {...}, "source": str}——耦合结构 Z0e/Z0o 直接读 KJ（#7：内核不自算
    阻抗）；kept 端口附 even/odd 模阻抗注记，crossing 端口附 half_width。
    """
    lay = _require_symmetric(normalize_layout(layout))
    axis = lay["axis"]
    refl_to_nr: dict[tuple, int] = {}
    for p in lay["ports"]:
        refl_to_nr.setdefault(_port_geom_key(reflect_port(p, axis)), int(p["nr"]))
    rows: list[dict[str, Any]] = []
    for p in lay["ports"]:
        nr = int(p["nr"])
        cls = classify_port(p, axis)
        row: dict[str, Any] = {
            "nr": nr,
            "label": str(p.get("label", "")),
            "disposition": {"lower": "kept", "upper": "dropped",
                            "crossing": "clipped", "on_plane": "kept"}[cls],
            "mirror_of": refl_to_nr.get(_port_geom_key(p)),
        }
        if cls == "crossing":
            row["half_width"] = True
        if cls in ("lower", "on_plane") and mode_impedances:
            note = {m: mode_impedances[m] for m in MODES if m in mode_impedances}
            if "source" in mode_impedances:
                note["source"] = mode_impedances["source"]
            row["mode_impedance_note"] = note
        rows.append(row)
    rows.sort(key=lambda r: r["nr"])
    return rows


# ── #310 家族自审守卫 ─────────────────────────────────────────────────────────

def mirror_reassembly_checksum(layout: dict[str, Any],
                               half: dict[str, Any]) -> dict[str, Any]:
    """split→镜像重装配 == 恒等 的逐位守卫（#310 家族 bounding_box 自审口径）。

    组合律：lower 元=自身+镜像各计一次；on_plane 元只计一次（自镜像）；
    跨面元=自身下半段 ∪ 镜像伙伴下半段的反射（伙伴按几何键查找，名字不作
    配对依据）。结果几何多重集与原布局**逐位相等**（exact float，无容差）。
    """
    lay = normalize_layout(layout)
    axis = lay["axis"]
    half_b_by_name = {b["name"]: b for b in half["boxes"]}
    half_p_by_nr = {int(p["nr"]): p for p in half["ports"]}
    # 伙伴查找：几何键（反射后）→ 名/编号（首个命中；重复几何为退化输入）
    b_key_to_name: dict[tuple, str] = {}
    for b in lay["boxes"]:
        b_key_to_name.setdefault(_box_geom_key(reflect_box(b, axis)), b["name"])
    p_key_to_nr: dict[tuple, int] = {}
    for p in lay["ports"]:
        p_key_to_nr.setdefault(_port_geom_key(reflect_port(p, axis)), int(p["nr"]))

    got_b: list[tuple] = []
    fail_b: list[str] = []
    for b in lay["boxes"]:
        cls = classify_box(b, axis)
        if cls == "upper":
            continue
        if cls == "on_plane":
            got_b.append(_box_geom_key(b))
            continue
        if cls == "lower":
            got_b.append(_box_geom_key(b))
            got_b.append(_box_geom_key(reflect_box(b, axis)))
            continue
        me = half_b_by_name.get(b["name"])
        pn = b_key_to_name.get(_box_geom_key(b))
        mp = half_b_by_name.get(pn) if pn is not None else None
        if me is None or mp is None or not me.get("clipped") or not mp.get("clipped"):
            fail_b.append(b["name"])
            continue
        lo = float(me[f"{axis}0"])
        hi = -float(mp[f"{axis}0"])     # reflect(mp) 的下沿 = −(mp 裁半下沿)
        uni = dict(b)
        uni[f"{axis}0"], uni[f"{axis}1"] = lo, hi
        got_b.append(_box_geom_key(uni))

    got_p: list[tuple] = []
    fail_p: list[int] = []
    for p in lay["ports"]:
        cls = classify_port(p, axis)
        if cls == "upper":
            continue
        if cls == "on_plane":
            got_p.append(_port_geom_key(p))
            continue
        if cls == "lower":
            got_p.append(_port_geom_key(p))
            got_p.append(_port_geom_key(reflect_port(p, axis)))
            continue
        me = half_p_by_nr.get(int(p["nr"]))
        pn = p_key_to_nr.get(_port_geom_key(p))
        mp = half_p_by_nr.get(pn) if pn is not None else None
        if (me is None or mp is None or not me.get("half_width")
                or not mp.get("half_width")):
            fail_p.append(int(p["nr"]))
            continue
        # 跨面端口结构还原：轴区间并集逐位 == 原轴区间；非轴区间为包含关系
        # （对角积分线的面上交点截断使非轴 AABB 一般仅包含；轴对齐端口取等）。
        o_s, o_e = (tuple(float(v) for v in p["start"]),
                    tuple(float(v) for v in p["stop"]))
        k = _axis_idx(axis)
        orig_spans = tuple((min(o_s[j], o_e[j]), max(o_s[j], o_e[j]))
                           for j in range(3))
        me_bb = _port_geom_key(me)[0]
        mp_bb = _port_geom_key(reflect_port(mp, axis))[0]
        axis_ok = (min(me_bb[k][0], mp_bb[k][0]) == orig_spans[k][0]
                   and max(me_bb[k][1], mp_bb[k][1]) == orig_spans[k][1])
        nonaxis_ok = all(
            me_bb[j][0] >= orig_spans[j][0] and me_bb[j][1] <= orig_spans[j][1]
            and mp_bb[j][0] >= orig_spans[j][0] and mp_bb[j][1] <= orig_spans[j][1]
            for j in range(3) if j != k)
        if not (axis_ok and nonaxis_ok):
            fail_p.append(int(p["nr"]))
    orig_b = Counter(_box_geom_key(b) for b in lay["boxes"])
    orig_p = Counter(_port_geom_key(p) for p in lay["ports"]
                     if classify_port(p, axis) != "crossing")
    boxes_equal = not fail_b and orig_b == Counter(got_b)
    ports_equal = not fail_p and orig_p == Counter(got_p)
    return {
        "boxes_equal": boxes_equal,
        "ports_equal": ports_equal,
        "n_boxes_original": len(lay["boxes"]),
        "n_boxes_reassembled": len(got_b),
        "unmatched_boxes": sorted(fail_b),
        "unmatched_ports": sorted(fail_p),
    }


def _touches(a_lo: float, a_hi: float, b_lo: float, b_hi: float,
             tol: float) -> bool:
    return a_lo <= b_hi + tol and b_lo <= a_hi + tol


def connectivity_components(
    boxes: Iterable[dict[str, Any]], *, tol: float = 1e-9,
) -> list[list[str]]:
    """金属盒连通分量（三轴区间重叠/相触即连通；并查集；按名排序确定性）。"""
    bs = sorted((normalize_box(b) for b in boxes), key=lambda b: b["name"])
    n = len(bs)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            bi, bj = bs[i], bs[j]
            if all(_touches(bi[f"{a}0"], bi[f"{a}1"], bj[f"{a}0"], bj[f"{a}1"], tol)
                   for a in ("x", "y", "z")):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[str]] = {}
    for i, b in enumerate(bs):
        groups.setdefault(find(i), []).append(b["name"])
    return sorted(sorted(g) for g in groups.values())


def orphan_ports(
    boxes: Iterable[dict[str, Any]], ports: Iterable[dict[str, Any]],
    *, tol: float = 1e-9,
) -> list[int]:
    """端口线段不触任何金属盒的孤儿编号（#212 连通审计同族守卫）。"""
    bs = [normalize_box(b) for b in boxes]
    orphans: list[int] = []
    for p in ports:
        s, e = p["start"], p["stop"]
        bb = {"x0": min(s[0], e[0]), "x1": max(s[0], e[0]),
              "y0": min(s[1], e[1]), "y1": max(s[1], e[1]),
              "z0": min(s[2], e[2]), "z1": max(s[2], e[2])}
        if not any(all(_touches(bb[f"{a}0"], bb[f"{a}1"], b[f"{a}0"], b[f"{a}1"], tol)
                       for a in ("x", "y", "z")) for b in bs):
            orphans.append(int(p["nr"]))
    return sorted(orphans)


def split_guards(layout: dict[str, Any], half: dict[str, Any]) -> dict[str, Any]:
    """半模型守卫汇总：镜像重装配逐位 / 连通分量 / 孤儿端口 / bbox 轴侧。"""
    lay = normalize_layout(layout)
    axis = lay["axis"]
    chk = mirror_reassembly_checksum(lay, half)
    comp_full = connectivity_components(lay["boxes"])
    comp_half = connectivity_components(half["boxes"])
    orph_full = orphan_ports(lay["boxes"], lay["ports"])
    orph_half = orphan_ports(half["boxes"], half["ports"])
    bbox_max = max((float(b[f"{axis}1"]) for b in half["boxes"]), default=0.0)
    ok = (chk["boxes_equal"] and chk["ports_equal"]
          and len(comp_half) <= len(comp_full)
          and not orph_half and bbox_max <= 0.0)
    return {
        "ok": ok,
        "mirror_reassembly": chk,
        "components_full": comp_full,
        "components_half": comp_half,
        "n_components_full": len(comp_full),
        "n_components_half": len(comp_half),
        "orphan_ports_full": orph_full,
        "orphan_ports_half": orph_half,
        "bbox_half_axis_max": bbox_max,
    }


# ── 跨面元电路口径（闭式恒等式，供装配消费；教科书公式）─────────────────────

def stub_input_admittance(z0_ohm: float, theta_half_rad: float, mode: str) -> complex:
    """跨面半桩输入导纳（偶=开路桩/奇=短路桩；θ_half=半桩电长度）。

    教科书恒等式（13.2 口径）：偶模 PMC → Y_in=+j·Y0·tan(θ_half)；
    奇模 PEC → Y_in=−j·Y0·cot(θ_half)。θ_half=π/4（λ/8 半桩）→ Y=±j·Y0。
    """
    if mode not in MODES:
        raise ValueError(f"mode 须为 {MODES}，得 {mode!r}")
    z0 = float(z0_ohm)
    if z0 <= 0.0:
        raise ValueError(f"z0_ohm 须 >0，得 {z0}")
    y0 = 1.0 / z0
    t = math.tan(float(theta_half_rad))
    if mode == "even":
        return 1j * y0 * t
    return -1j * y0 / t


def stub_shunt_abcd(
    z0_ohm: float, theta_half_rad: float, mode: str,
) -> tuple[tuple[float, float], tuple[complex, float]]:
    """半桩并联 ABCD（(A,B),(C,D)；B=0、D=1、C=Y_in）。"""
    y = stub_input_admittance(z0_ohm, theta_half_rad, mode)
    return (1.0, 0.0), (y, 1.0)


def transmission_line_abcd(
    z0_ohm: float, theta_rad: float,
) -> tuple[tuple[complex, complex], tuple[complex, complex]]:
    """均匀线 ABCD（教科书恒等式）：[[cosθ, jZ sinθ], [j sinθ/Z, cosθ]]。"""
    z0 = float(z0_ohm)
    if z0 <= 0.0:
        raise ValueError(f"z0_ohm 须 >0，得 {z0}")
    th = float(theta_rad)
    c, s = cmath.cos(th), cmath.sin(th)
    return (c, 1j * z0 * s), (1j * s / z0, c)
