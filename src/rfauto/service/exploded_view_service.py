"""版图 3D 爆炸视图渲染服务（T-Q37 席位 Q-X37，aurora_q 方向 CAD 3D）。

消费链（单源直通，零几何重算——铁律 7）：
- ``layered_stack`` 源：:mod:`rfauto.adapters.layered_stack_spec` 的
  :func:`layered_stack_layout`（分层围合布局单源）直通消费——渲染坐标
  =layout 产出的一手 mm 坐标 + explode 偏移（explode_factor 为调用方显式
  声明参数，逐值落信封 ``explode`` 键，零手拍）；
- ``kicad`` 源：``.kicad_pcb`` 文本 s-expression 解析——叠层复用
  :func:`rfauto.adapters.layout_substrate.stackup_from_kicad_text`
  （括号配平线性扫描+字段正则单源，米→mm 显式 ×1e3）；segment/via/
  gr_rect 块提取沿用同款**线性扫描纪律**（str.find 起点+深度计数到闭合，
  块内小正则，禁跨千行嵌套量词——kicad_sexpr_surgery_guard 家法，本文件
  正则无"量化组体内含量化原子"签名）；KiCad 屏幕系 y 向下→模型右手系
  y_model=−y_kicad（声明式符号约定，顶视与 KiCad 画面同向不镜像）。

三形态输出：
- **交互式 SVG**：内置缩放（滚轮）/平移（拖拽）/旋转（Shift+拖拽，场景组
  CSS transform）/分层筛选（点击图例按钮 toggle 层组 display）——全部
  内联 CSS/JS 常量（零外部引用、零时间戳、逐字节确定性）；
- **Three.js 兼容 JSON**：three.js ObjectLoader 场景图结构
  （metadata/geometries/materials/object.children——BoxGeometry 实体 +
  PlaneGeometry 零厚片+节点 translation 携带爆炸偏移），JSON 直出；
- **静态 PNG**：matplotlib Agg OO API（Figure+FigureCanvasAgg）+
  :mod:`rfauto.core.plot_style` 单源（Q-W8-4 家法：dpi/figsize 不新造
  数值），轴测投影与 SVG 同一投影常量（两形态同观感），零时间戳确定性。

geometry_lint 消费闭环（Q-X37 验收核心口径）：渲染前 lint 全六检查，
**零 ERROR 才渲染**（ERROR=拦截渲染返回 error_envelope，渲染产物零落盘）；
WARN 不拦截，lint 报告信封 ``lint`` 键随附+``<stem>_lint.json`` 与渲染
产物同目录落盘。layered_stack 源 lint 投影复用
:func:`layered_stack_lint_projection`（adapters 单源）；kicad 源 lint
投影=层板+走线零厚片声明式 boxes（过孔 v0 不进 lint 投影——柱体盒近似
会与层板部分相交误报检查④，如实声明不猜；无端口→检查①②③自然空转）。

导出接口预留（v0 未实现，签名+docstring 声明边界）：:func:`export_step`
（STEP AP214 需 B-rep 内核——OCC/cadquery 类，仓内零依赖禁引新依赖）与
:func:`export_glb`（glTF 2.0 二进制容器，可由 three.js JSON 面升级）。
v0 受理面=SVG/JSON/PNG 三形态。

确定性：同输入两跑逐字节同（SVG/JSON 文本 LF+固定小数位；PNG 显式
metadata 零 Date——hfss_run_report 同款先例），sha256 随信封 outputs 落档。

信封（规则 4+AU-2 契约）：:func:`ok_envelope`/:func:`error_envelope`
构造器，禁裸 dict ok（test_envelope_contract AST 棘轮面）。本模块不设
``__all__``：无 __all__ 的非门面文件不进 tests/gold/public_api.json
（layered_stack_spec/geometry_lint_service 同款，金快照零漂移）。

冻结面声明：layered_stack_spec.py / kicad_edb_bridge.py /
geometry_lint_service.py 为只读单源——本模块纯消费零改动。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from rfauto.adapters.layered_stack_spec import (
    MATERIALS,
    LayeredStackSpec,
    layered_stack_layout,
    layered_stack_lint_projection,
)
from rfauto.adapters.layout_substrate import stackup_from_kicad_text
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.geometry_lint_service import lint_geometry

# ── 版本与口径常量（v0 声明值，逐条出处）────────────────────────────────

#: 视图 schema 版本（信封 view_schema 键；消费方版本兼容判据）
_EXPLODED_VIEW_SCHEMA_VERSION = "exploded-view/v0"

#: 爆炸系数缺省（任务书文法 ``--explode-factor 1.5`` 的声明缺省；≥0，
#: 0=收拢回名义叠放）
EXPLODE_FACTOR_DEFAULT = 1.5

#: 层距来源声明（信封 explode.gap_mm_source；铁律 7：层距=max 层厚，
#: 非手拍固定值——薄介质族层距随叠层声明自适应）
LAYER_GAP_SOURCE = "max_layer_thickness"

#: 轴测投影角（度；v0 声明轴测角，SVG/PNG 两形态共用同一投影常量）
PROJ_ALPHA_DEG = 30.0
_PROJ_COS = math.cos(math.radians(PROJ_ALPHA_DEG))
_PROJ_SIN = math.sin(math.radians(PROJ_ALPHA_DEG))

#: 材料着色表（v0 声明调色板；铁律 7 注记：本表是渲染样式声明值非物理量
#: ——gold/copper=金属惯例色、silicon 取 core.plot_style.PAPER_COLORS[5]
#: 棕色族（半导体衬底）、core/prepreg=介质浅色族 v0 声明；未知材料回落
#: DEFAULT_DIELECTRIC_COLOR 不猜不炸）
MATERIAL_COLORS: dict[str, str] = {
    "silicon": "#8c564b",
    "gold": "#ffd700",
    "copper": "#b87333",
    "core": "#d6eaf8",
    "prepreg": "#d5f5e3",
    "pec": "#c0c0c0",
}
#: 未知材料回落色（v0 声明浅蓝）
DEFAULT_DIELECTRIC_COLOR = "#aed6f1"
#: 腔体/挖除区透明化色与不透明度（v0 声明；挖除区=半透明+dashed 边）
CAVITY_COLOR = "#85c1e9"
CAVITY_OPACITY = 0.35
#: 实体/零厚片不透明度（v0 声明）
SOLID_OPACITY = 0.95
SHEET_OPACITY = 1.0
#: KiCad 铜层包络不透明度（v0 声明）：铜层物理上只在走线/焊盘处有铜，
#: 整板实体铜板会遮挡走线且物理误导（#212 离线目检实证）——铜层渲染为
#: 半透明 dashed 包络，真实铜=走线/过孔不透明
ENVELOPE_OPACITY = 0.15
#: 面明暗系数（z 顶面 1.0 / x 侧 0.82 / y 侧 0.65——v0 声明，伪 3D 立体感）
_SHADE_Z = 1.0
_SHADE_X = 0.82
_SHADE_Y = 0.65
#: three.js ObjectLoader metadata 版本声明（v0 兼容声明）
_THREE_METADATA_VERSION = "4.5"
#: PlaneGeometry 直角（three.js 节点 rotation 用，弧度）
_PLANE_HALF_PI = math.pi / 2.0


# ── KiCad .kicad_pcb s-expression 线性扫描（括号配平+块内小正则）────────


_NUM_RE = r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
_START_RE = re.compile(r"\(start\s+(" + _NUM_RE + r")\s+(" + _NUM_RE + r")\s*\)")
_END_RE = re.compile(r"\(end\s+(" + _NUM_RE + r")\s+(" + _NUM_RE + r")\s*\)")
_AT_RE = re.compile(r"\(at\s+(" + _NUM_RE + r")\s+(" + _NUM_RE + r")\s*\)")
_WIDTH_RE = re.compile(r"\(width\s+(" + _NUM_RE + r")\s*\)")
_SIZE_RE = re.compile(r"\(size\s+(" + _NUM_RE + r")\s*\)")
_LAYER_NAME_RE = re.compile(r'\(layer\s+"([^"]*)"\s*\)')
#: net 双格式（#15 家法）：新式名称制 ``(net "名")`` 优先、旧式 ``(net 码)`` 回落
_NET_RE = re.compile(r'\(net\s+(?:"([^"]*)"|([0-9]+))\s*\)')


def _balanced_chunks(text: str, token: str) -> list[str]:
    """提取全部以 token 起头的括号配平块（线性扫描，零回溯——surgery 纪律）。

    未闭合文件如实停止（截断处之后的块不计，不猜）。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while True:
        j = text.find(token, i)
        if j < 0:
            return out
        depth = 0
        k = j
        end = -1
        while k < n:
            c = text[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
            k += 1
        if end < 0:
            return out  # 未闭合：如实截断
        out.append(text[j:end])
        i = end


def _f1(m: re.Match[str] | None) -> float | None:
    if m is None:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _f2(m: re.Match[str] | None) -> tuple[float, float] | None:
    if m is None:
        return None
    try:
        x = float(m.group(1))
        y = float(m.group(2))
    except ValueError:
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def _kicad_board_outline_mm(pcb_text: str) -> tuple[float, float, float, float] | None:
    """Edge.Cuts 层 gr_rect 板框 (x0, y0, x1, y1) mm；无则 None（如实）。"""
    for chunk in _balanced_chunks(pcb_text, "(gr_rect"):
        lm = _LAYER_NAME_RE.search(chunk)
        if lm is None or lm.group(1) != "Edge.Cuts":
            continue
        s = _f2(_START_RE.search(chunk))
        e = _f2(_END_RE.search(chunk))
        if s is None or e is None:
            continue
        return (min(s[0], e[0]), min(s[1], e[1]), max(s[0], e[0]), max(s[1], e[1]))
    return None


def _kicad_segments_mm(pcb_text: str) -> list[dict[str, Any]]:
    """(segment ...) 块 → 走线段声明（mm 原值直通；坏块如实跳过计数）。"""
    out: list[dict[str, Any]] = []
    for chunk in _balanced_chunks(pcb_text, "(segment"):
        s = _f2(_START_RE.search(chunk))
        e = _f2(_END_RE.search(chunk))
        w = _f1(_WIDTH_RE.search(chunk))
        lm = _LAYER_NAME_RE.search(chunk)
        nm = _NET_RE.search(chunk)
        if s is None or e is None or w is None or w <= 0.0 or lm is None:
            continue  # 形态不完整如实跳过（跳过数由调用方如实登记）
        net = ""
        if nm is not None:
            net = nm.group(1) if nm.group(1) is not None else nm.group(2)
        out.append({"start": s, "end": e, "width_mm": w,
                    "layer": lm.group(1), "net": net})
    return out


def _kicad_vias_mm(pcb_text: str) -> list[dict[str, Any]]:
    """(via ...) 块 → 过孔声明（mm 原值直通；坏块如实跳过计数）。"""
    out: list[dict[str, Any]] = []
    for chunk in _balanced_chunks(pcb_text, "(via"):
        at = _f2(_AT_RE.search(chunk))
        size = _f1(_SIZE_RE.search(chunk))
        nm = _NET_RE.search(chunk)
        if at is None or size is None or size <= 0.0:
            continue
        net = ""
        if nm is not None:
            net = nm.group(1) if nm.group(1) is not None else nm.group(2)
        out.append({"x_mm": at[0], "y_mm": at[1], "pad_mm": size, "net": net})
    return out


# ── 内容 → 场景装配（爆炸偏移单源）──────────────────────────────────────


def _explode_offsets(n_layers: int, gap_mm: float, factor: float) -> dict[str, float]:
    """层爆炸偏移单源（mm）：bottom→top 对称展开 off_i=(i−中心)·gap·factor。

    居中展开（和恒 0）保持场景质心不漂；factor=0 全零=收拢回名义叠放。
    """
    center = (n_layers - 1) / 2.0
    return {str(i): (float(i) - center) * gap_mm * factor for i in range(n_layers)}


def _assemble_scene(
    *,
    source_kind: str,
    scene_name: str,
    layers: list[dict[str, Any]],
    solids: list[dict[str, Any]],
    cavity: dict[str, Any] | None,
    explode_factor: float,
    notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """场景装配单源：偏移挂载+计数+schema 戳（两内容源共用）。"""
    gap = max(float(lay["thickness_mm"]) for lay in layers)
    offsets = _explode_offsets(len(layers), gap, float(explode_factor))
    for lay in layers:
        lay["offset_mm"] = offsets[str(lay["index"])]
    for ent in solids:
        idx = ent.get("layer_index")
        ent["offset_mm"] = offsets[str(idx)] if idx is not None else 0.0
    if cavity is not None:
        cavity["offset_mm"] = offsets[str(cavity["layer_index"])]
    counts = {
        "n_layers": len(layers),
        "n_solids": sum(1 for s in solids if s["kind"] == "solid"),
        "n_sheets": sum(1 for s in solids if s["kind"] == "sheet"),
        "n_traces": sum(1 for s in solids if s["kind"] == "trace"),
        "n_vias": sum(1 for s in solids if s["kind"] == "via"),
        "n_cavity": 1 if cavity is not None else 0,
    }
    return {
        "schema": _EXPLODED_VIEW_SCHEMA_VERSION,
        "source_kind": source_kind,
        "scene_name": str(scene_name),
        "units": "mm",
        "explode": {
            "axis": "z",
            "factor": float(explode_factor),
            "gap_mm": gap,
            "gap_mm_source": LAYER_GAP_SOURCE,
            "offsets_mm": offsets,
        },
        "layers": layers,
        "solids": solids,
        "cavity": cavity,
        "notes": dict(notes or {}),
        "counts": counts,
    }


def _layer_color(material: str) -> str:
    return MATERIAL_COLORS.get(material, DEFAULT_DIELECTRIC_COLOR)


def _layered_scene(content: dict[str, Any], *, explode_factor: float) -> dict[str, Any]:
    """layered_stack 源 → 场景（layered_stack_layout 单源直通，零几何重算）。"""
    spec_data = content.get("spec", {})
    if spec_data is None:
        spec_data = {}
    if not isinstance(spec_data, dict):
        raise ValueError(f"spec 键必须为 JSON 对象（得 {type(spec_data).__name__}）")
    spec = LayeredStackSpec.model_validate(spec_data)
    layout = layered_stack_layout(spec)
    zr = layout["z_ranges_mm"]
    ci = spec.conductor_index()
    layers: list[dict[str, Any]] = []
    for i, (mat, thick) in enumerate(spec.layers):
        is_metal = MATERIALS[mat].is_metal
        layers.append({
            "index": i, "name": f"{i}:{mat}",
            "kind": "metal" if is_metal else "dielectric",
            "material": mat, "thickness_mm": float(thick),
            "z0_mm": float(zr[i][0]), "z1_mm": float(zr[i][1]),
        })
    solids: list[dict[str, Any]] = []
    for seg in layout["stack_solids"]:
        x0, x1, y0, y1, z0, z1 = seg["box"]
        solids.append({
            "name": str(seg["name"]), "layer_index": int(seg["layer"]),
            "kind": "solid", "material": str(seg["material"]),
            "box_mm": [x0, y0, z0, x1, y1, z1],
        })
    for sh in layout["metal_sheets"]:
        x0, x1, y0, y1, z0, z1 = sh["box"]
        solids.append({
            "name": str(sh["name"]), "layer_index": ci,
            "kind": "sheet", "material": "pec",
            "box_mm": [x0, y0, z0, x1, y1, z1],
        })
    sx0, sx1, sy0, sy1, sz0, sz1 = layout["strip"]
    solids.append({
        "name": "strip", "layer_index": ci, "kind": "sheet",
        "material": "pec", "box_mm": [sx0, sy0, sz0, sx1, sy1, sz1],
    })
    cav = layout["cavity_mm"]
    lh = layout["l_half_mm"]
    cavity = {
        "name": "cavity", "layer_index": ci,
        "box_mm": [-lh, cav["y0"], cav["z0"], lh, cav["y1"], cav["z1"]],
    }
    scene_name = content.get("scene_name") or "layered_stack"
    return _assemble_scene(
        source_kind="layered_stack", scene_name=str(scene_name),
        layers=layers, solids=solids, cavity=cavity,
        explode_factor=explode_factor,
        notes={"vacuum_box_mm": list(layout["vacuum_box_mm"]),
               "lint_source": "layered_stack_lint_projection（adapters 单源）"},
    )


def _trace_quad(seg: list[list[float]], width: float,
                z: float) -> list[tuple[float, float, float]]:
    """走线足迹四边形（沿段方向的定向矩形，两端各延 w/2=方帽近似 KiCad 圆帽）。

    方帽近似为 v0 声明（KiCad 走线端帽为圆；方帽使相接段在拐角无缝，
    且足迹不小于真实圆帽轮廓）。轴向段与斜向段同一公式——零轴向特判。
    """
    (sx, sy), (ex, ey) = seg
    length = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / length, (ey - sy) / length
    nx, ny = -uy, ux
    h = width / 2.0
    ax, ay = sx - ux * h, sy - uy * h
    bx, by = ex + ux * h, ey + uy * h
    return [(ax + nx * h, ay + ny * h, z), (bx + nx * h, by + ny * h, z),
            (bx - nx * h, by - ny * h, z), (ax - nx * h, ay - ny * h, z)]


def _kicad_scene(
    content: dict[str, Any], *, explode_factor: float, spec_path: str | Path | None,
) -> dict[str, Any]:
    """kicad 源 → 场景（stackup_from_kicad_text 单源+s-expr 线性扫描）。"""
    pcb_path = content.get("pcb_path")
    if not isinstance(pcb_path, str) or not pcb_path.strip():
        raise ValueError(
            "kicad source 需要 pcb_path（.kicad_pcb 文件路径字符串）——显式声明"
            "不落缺省位（#144 同族）")
    p = Path(pcb_path)
    if not p.is_absolute() and spec_path is not None:
        p = Path(spec_path).resolve().parent / p
    if not p.exists():
        raise ValueError(f"pcb_path 不存在: {p}")
    text = p.read_text(encoding="utf-8")
    copper_kinds_raw = content.get("copper_kinds") or {}
    if not isinstance(copper_kinds_raw, dict):
        raise ValueError("copper_kinds 必须为 JSON 对象（层名→signal|ground）")
    require_er = content.get("require_epsilon_r", True)
    parsed = stackup_from_kicad_text(
        text,
        copper_kinds={str(k): str(v) for k, v in copper_kinds_raw.items()},
        require_epsilon_r=bool(require_er),
    )
    warnings: list[str] = []
    stackup = parsed["stackup"]
    board_z0 = 0.0
    board_z1 = float(parsed["stats"]["board_thickness_m"]) * 1e3
    z_by_name = {
        lay.name: (lay.zmin_m * 1e3, (lay.zmin_m + lay.thickness_m) * 1e3)
        for lay in stackup.layers
    }
    index_by_name = {lay.name: i for i, lay in enumerate(stackup.layers)}

    outline = _kicad_board_outline_mm(text)
    segs = _kicad_segments_mm(text)
    vias = _kicad_vias_mm(text)
    # KiCad 坐标系=屏幕系 y 向下（pcbnew 2D 画面口径）→ 模型右手系（z 向上）
    # y_model=−y_kicad：顶视与 KiCad 画面同向不镜像（声明式符号约定，非数值
    # 修饰；用 0.0−y 而非 −y，避免 y=0 产出 −0.0 噪声）
    if outline is not None:
        outline = (outline[0], 0.0 - outline[3], outline[2], 0.0 - outline[1])
    segs = [{**s, "start": (s["start"][0], 0.0 - s["start"][1]),
             "end": (s["end"][0], 0.0 - s["end"][1])} for s in segs]
    vias = [{**v, "y_mm": 0.0 - v["y_mm"]} for v in vias]

    xs: list[float] = []
    ys: list[float] = []
    if outline is not None:
        xs += [outline[0], outline[2]]
        ys += [outline[1], outline[3]]
    else:
        warnings.append(
            "无 Edge.Cuts gr_rect 板框——板幅取走线包络（v1 声明回落，零编造）")
    for seg in segs:
        xs += [seg["start"][0], seg["end"][0]]
        ys += [seg["start"][1], seg["end"][1]]
    if not xs or not ys:
        raise ValueError(
            "无法确定板幅（无 Edge.Cuts 板框且无 segment 走线）——显式声明失败，"
            "不编造缺省板框")
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    layers: list[dict[str, Any]] = []
    for i, lay in enumerate(stackup.layers):
        is_metal = lay.kind != "dielectric"
        layers.append({
            "index": i, "name": lay.name,
            "kind": "metal" if is_metal else "dielectric",
            "material": lay.material,
            "thickness_mm": lay.thickness_m * 1e3,
            "z0_mm": lay.zmin_m * 1e3,
            "z1_mm": (lay.zmin_m + lay.thickness_m) * 1e3,
        })

    solids: list[dict[str, Any]] = []
    for i, lay in enumerate(stackup.layers):
        solids.append({
            "name": f"layer{i:02d}_{lay.name}", "layer_index": i,
            "kind": "solid", "material": lay.material,
            # 铜层=半透明包络（真实铜=走线/过孔）；介质层=实体
            "envelope": lay.kind != "dielectric",
            "box_mm": [x0, y0, lay.zmin_m * 1e3, x1, y1,
                       (lay.zmin_m + lay.thickness_m) * 1e3],
        })
    n_skip_layer = 0
    n_zero_len = 0
    known_layers = set(index_by_name)
    for i, seg in enumerate(segs):
        if seg["layer"] not in known_layers:
            n_skip_layer += 1
            continue
        s, e, w = seg["start"], seg["end"], seg["width_mm"]
        if s == e:
            n_zero_len += 1  # 零长段无方向（足迹不可定向）：如实跳过计数
            continue
        z_top = z_by_name[seg["layer"]][1]
        segment = [[s[0], s[1]], [e[0], e[1]]]
        quad = _trace_quad(segment, w, z_top)
        solids.append({
            "name": f"trace_{i:04d}", "layer_index": index_by_name[seg["layer"]],
            "kind": "trace", "material": "copper", "net": seg["net"],
            "segment_mm": segment, "width_mm": w,
            # box=渲染足迹四边形的精确 AABB（任意走向同一口径，零轴向特判）
            "box_mm": [min(q[0] for q in quad), min(q[1] for q in quad), z_top,
                       max(q[0] for q in quad), max(q[1] for q in quad), z_top],
        })
    if n_skip_layer:
        warnings.append(
            f"{n_skip_layer} 条 segment 层名不在叠层名单（如实跳过，不猜归属）")
    if n_zero_len:
        warnings.append(
            f"{n_zero_len} 条 segment 零长（start=end，足迹不可定向）——如实跳过")
    for i, via in enumerate(vias):
        half = via["pad_mm"] / 2.0
        solids.append({
            "name": f"via_{i:04d}", "layer_index": None, "kind": "via",
            "material": "copper", "net": via["net"],
            "box_mm": [via["x_mm"] - half, via["y_mm"] - half, board_z0,
                       via["x_mm"] + half, via["y_mm"] + half, board_z1],
        })
    cavity = None  # kicad 源 v0 无挖除区声明（挖除区透明化为 layered_stack 腔体形态）
    scene_name = content.get("scene_name") or "kicad_pcb"
    scene = _assemble_scene(
        source_kind="kicad", scene_name=str(scene_name),
        layers=layers, solids=solids, cavity=cavity,
        explode_factor=explode_factor,
        notes={
            "board_outline_mm": list(outline) if outline is not None else None,
            "board_z_mm": [board_z0, board_z1],
            "kicad_axis_convention": "y_model=−y_kicad（屏幕系 y 向下→右手系 z 向上）",
            "skipped_stackup_layers": list(parsed["stats"]["skipped_layers"]),
            "loss_tangent_defaulted": list(parsed["stats"]["loss_tangent_defaulted"]),
            "vias_lint_excluded": True,
            "lint_source": "层板+走线零厚片声明式投影（过孔不进 lint，"
                           "柱体盒近似会与层板部分相交误报检查④）",
        },
    )
    scene["warnings"] = warnings
    return scene


def build_scene(
    content: dict[str, Any],
    *,
    explode_factor: float = EXPLODE_FACTOR_DEFAULT,
    spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """声明式 spec JSON → 渲染场景 dict（渲染三形态与 lint 共用的中间形态）。

    Raises
    ------
    ValueError
        source 缺失/未知、factor 非法、kicad pcb_path 缺失/不存在、
        叠层解析失败等——fail-loud（K7 哲学：报错而不是渲染假视图）。
    """
    if not isinstance(content, dict):
        raise ValueError(f"content 必须为 JSON 对象（得 {type(content).__name__}）")
    if (isinstance(explode_factor, bool)
            or not isinstance(explode_factor, (int, float))
            or not math.isfinite(float(explode_factor))
            or float(explode_factor) < 0.0):
        raise ValueError(
            f"explode_factor 必须为 ≥0 的有限数，得到 {explode_factor!r}")
    src = content.get("source")
    if src == "layered_stack":
        return _layered_scene(content, explode_factor=float(explode_factor))
    if src == "kicad":
        return _kicad_scene(
            content, explode_factor=float(explode_factor), spec_path=spec_path)
    raise ValueError(
        f"spec.source 必须为 'layered_stack' 或 'kicad'，得到 {src!r}")


# ── geometry_lint 闭环（零 ERROR 才渲染）────────────────────────────────


def _lint_projection_kicad(scene: dict[str, Any]) -> dict[str, Any]:
    """kicad 场景 → LintGeometry 兼容 dict（层板+走线零厚片；过孔不进）。"""
    boxes: list[dict[str, Any]] = []
    for ent in scene["solids"]:
        if ent["kind"] == "via":
            continue  # 声明面：过孔盒近似会与层板部分相交误报④（notes 同口径）
        bx0, by0, bz0, bx1, by1, bz1 = ent["box_mm"]
        is_metal = ent["material"] == "copper"
        boxes.append({
            "name": str(ent["name"]), "material": ent["material"],
            "solve_inside": not is_metal,
            "coords": (bx0, by0, bz0, bx1, by1, bz1),
            "is_metal": is_metal,
        })
    return {"model_units": "mm", "boxes": boxes, "ports": [], "variables": []}


def _lint_report_for_scene(scene: dict[str, Any],
                           content: dict[str, Any]) -> dict[str, Any]:
    """场景 → geometry_lint 六检查报告（两源各自的单源投影）。

    layered_stack 源投影用调用方 spec 原文（非名义缺省——非名义 spec 的
    lint 报告必须对应该 spec 本体，Q-X4 口径镜面）。
    """
    if scene["source_kind"] == "layered_stack":
        spec_data = content.get("spec") or {}
        spec = LayeredStackSpec.model_validate(spec_data)
        proj = layered_stack_lint_projection(layered_stack_layout(spec))
    else:
        proj = _lint_projection_kicad(scene)
    return lint_geometry(proj)


def _gate_errors(lint_report: dict[str, Any]) -> list[str]:
    """lint 报告 → 渲染拦截错误清单（零 ERROR 才放行；WARN 不拦截）。"""
    if not lint_report.get("ok"):
        errs = lint_report.get("errors") or ["lint 报告信封异常 ok=False（无明细）"]
        return ["geometry_lint 未产出有效报告——渲染拦截"] + [str(e) for e in errs]
    n_err = int(lint_report.get("counts", {}).get("error", 0))
    if n_err > 0:
        msgs = [f"geometry_lint ERROR {n_err} 条——渲染拦截（零 ERROR 才渲染）"]
        for it in lint_report.get("issues", []):
            if it.get("level") == "ERROR":
                msgs.append(f"[{it.get('check')}] {it.get('objects')}: "
                            f"{it.get('message', '')[:120]}")
        return msgs
    return []


# ── 投影与多边形（SVG/PNG 共面）─────────────────────────────────────────


def _project(x: float, y: float, z: float) -> tuple[float, float]:
    """轴测投影（度=PROJ_ALPHA_DEG 声明角）：px=(x−y)·cosα，py=(x+y)·sinα−z。"""
    return ((x - y) * _PROJ_COS, (x + y) * _PROJ_SIN - z)


def _shade_hex(color: str, factor: float) -> str:
    r = max(0, min(255, round(int(color[1:3], 16) * factor)))
    g = max(0, min(255, round(int(color[3:5], 16) * factor)))
    b = max(0, min(255, round(int(color[5:7], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _solid_faces(box_mm: list[float]) -> list[tuple[list[tuple[float, float, float]], float]]:
    """盒 → 可见面四边形（相机在 (+x,+y,+z) 半轴：x1/y1/z1 三面）。

    零厚轴自动退化（sheet/壁只剩所在平面那一枚四边形）——零编造面。
    """
    x0, y0, z0, x1, y1, z1 = box_mm
    faces: list[tuple[list[tuple[float, float, float]], float]] = []
    if x1 > x0 and y1 > y0:
        faces.append(([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
                      _SHADE_Z))
    if y1 > y0 and z1 > z0:
        faces.append(([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
                      _SHADE_X))
    if x1 > x0 and z1 > z0:
        faces.append(([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
                      _SHADE_Y))
    return faces


def _scene_polygons(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """全部渲染多边形（painter 远→近排序，depth=x+y+2·sinα·z **升序**）。

    投影几何推导：屏幕轴 r=(cosα,−cosα,0)、s=(sinα,sinα,−1) 与视线正交
    ⇒ 相机方向 ∝ +(1,1,2·sinα)——该式越大越**近**相机，故升序=远先画
    （画家算法）；可见面同步为 +x/+y/+z 三面（_solid_faces）。
    每项：pts3（3D 顶点×4）/ fill / stroke / opacity / dashed / group 键。
    排序为声明式启发（v0 简化：分层板间少量交叠按远→近近似，如实声明）。
    """
    polys: list[dict[str, Any]] = []

    def _emit(pts3: list[tuple[float, float, float]], color: str, shade: float,
              opacity: float, group: str, dashed: bool = False) -> None:
        depth = sum(p[0] + p[1] + 2.0 * _PROJ_SIN * p[2] for p in pts3) / len(pts3)
        polys.append({
            "pts3": pts3, "fill": _shade_hex(color, shade),
            "stroke": _shade_hex(color, 0.45), "opacity": float(opacity),
            "dashed": bool(dashed), "group": group, "_depth": depth,
        })

    for ent in scene["solids"]:
        lay = scene["layers"][ent["layer_index"]] if ent["layer_index"] is not None else None
        if ent["material"] in ("pec", "copper"):
            color = _layer_color(ent["material"])
        elif lay is not None:
            color = _layer_color(lay["material"])
        else:
            color = _layer_color(ent["material"])
        off = float(ent.get("offset_mm", 0.0))
        group = f"l{ent['layer_index']}" if ent["layer_index"] is not None else "via"
        bx = list(ent["box_mm"])
        bx[2] += off
        bx[5] += off
        if ent.get("envelope"):
            opacity, dashed = ENVELOPE_OPACITY, True
        elif ent["kind"] in ("sheet", "trace"):
            opacity, dashed = SHEET_OPACITY, False
        else:
            opacity, dashed = SOLID_OPACITY, False
        if ent["kind"] == "trace":
            # 走线=定向足迹四边形（非 AABB——斜向/竖向段 AABB 会失真或退化）
            _emit(_trace_quad(ent["segment_mm"], ent["width_mm"], bx[2]),
                  color, _SHADE_Z, opacity, group, dashed=dashed)
            continue
        for pts3, shade in _solid_faces(bx):
            _emit(pts3, color, shade, opacity, group, dashed=dashed)
    cav = scene.get("cavity")
    if cav is not None:
        off = float(cav.get("offset_mm", 0.0))
        bx = list(cav["box_mm"])
        bx[2] += off
        bx[5] += off
        for pts3, shade in _solid_faces(bx):
            _emit(pts3, CAVITY_COLOR, shade, CAVITY_OPACITY,
                  f"l{cav['layer_index']}", dashed=True)
    polys.sort(key=lambda p: p["_depth"])
    for p in polys:
        p.pop("_depth")
    return polys


def _scene_labels(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """每层一条文字标注（锚=层盒 (x0, y1, z 中点+偏移) 投影点）。"""
    labels: list[dict[str, Any]] = []
    for lay in scene["layers"]:
        i = int(lay["index"])
        xs = [s["box_mm"][0] for s in scene["solids"] if s["layer_index"] == i]
        ys = [s["box_mm"][4] for s in scene["solids"] if s["layer_index"] == i]
        if not xs or not ys:
            continue
        px, py = _project(min(xs), max(ys), (lay["z0_mm"] + lay["z1_mm"]) / 2.0
                          + float(lay.get("offset_mm", 0.0)))
        labels.append({"index": i, "text": f"{i} {lay['name']}",
                       "px": px, "py": py,
                       "color": _layer_color(lay["material"])})
    return labels


# ── 形态 1：交互式 SVG ──────────────────────────────────────────────────

_SVG_CSS = """
  #ev-root { background: #ffffff; }
  text { font-family: DejaVu Sans, Arial, sans-serif; fill: #333333; }
  .ev-btn { cursor: pointer; }
  .ev-btn:hover rect { stroke: #1f77b4; stroke-width: 1; }
  .ev-btn-off rect { fill: #dddddd; }
  .ev-btn-off text { fill: #999999; text-decoration: line-through; }
  .ev-off-g { display: none; }
"""

_SVG_JS = """(function () {
  var svg = document.getElementById('ev-root');
  if (!svg) { return; }
  var scene = document.getElementById('ev-scene');
  var vb = svg.viewBox.baseVal;
  var INIT = { x: vb.x, y: vb.y, w: vb.width, h: vb.height };
  var state = { x: INIT.x, y: INIT.y, w: INIT.w, h: INIT.h, rot: 0 };
  function apply() {
    vb.x = state.x; vb.y = state.y; vb.width = state.w; vb.height = state.h;
    if (scene) {
      var cx = state.x + state.w / 2;
      var cy = state.y + state.h / 2;
      scene.setAttribute('transform',
        'rotate(' + state.rot + ' ' + cx + ' ' + cy + ')');
    }
  }
  function toScene(evt) {
    var pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    var m = svg.getScreenCTM();
    if (!m) { return null; }
    var p = pt.matrixTransform(m.inverse());
    return { x: p.x, y: p.y };
  }
  function toggle(idx) {
    var btn = document.querySelector('.ev-btn[data-layer="' + idx + '"]');
    var off = !(btn && btn.classList.contains('ev-btn-off'));
    var els = document.querySelectorAll('.ev-l-' + idx);
    for (var i = 0; i < els.length; i++) { els[i].classList.toggle('ev-off-g', off); }
    if (btn) { btn.classList.toggle('ev-btn-off', off); }
  }
  var drag = null;
  svg.addEventListener('pointerdown', function (e) {
    var btn = e.target.closest ? e.target.closest('.ev-btn') : null;
    drag = { pt: toScene(e), shift: e.shiftKey, btn: btn, moved: 0 };
  });
  svg.addEventListener('pointermove', function (e) {
    if (!drag || !drag.pt) { return; }
    var p = toScene(e);
    if (!p) { return; }
    var dx = p.x - drag.pt.x;
    var dy = p.y - drag.pt.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.shift) { state.rot += (dx + dy) * 0.3; }
    else { state.x -= dx; state.y -= dy; }
    drag.pt = p;
    apply();
  });
  svg.addEventListener('pointerup', function () {
    if (drag && drag.btn && drag.moved < 3) {
      toggle(drag.btn.getAttribute('data-layer'));
    }
    drag = null;
  });
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var p = toScene(e);
    if (!p) { return; }
    var k = e.deltaY < 0 ? 0.85 : 1 / 0.85;
    state.x = p.x - (p.x - state.x) * k;
    state.y = p.y - (p.y - state.y) * k;
    state.w *= k; state.h *= k;
    apply();
  }, { passive: false });
  svg.addEventListener('dblclick', function () {
    state.x = INIT.x; state.y = INIT.y;
    state.w = INIT.w; state.h = INIT.h; state.rot = 0;
    apply();
  });
})();
"""


def _fmt(v: float) -> str:
    return f"{v:.4f}"


def render_svg(scene: dict[str, Any]) -> str:
    """场景 → 交互式 SVG 文本（内置缩放/平移/旋转/分层筛选，零外部引用）。"""
    polys = _scene_polygons(scene)
    labels = _scene_labels(scene)
    pts2_all: list[tuple[float, float]] = []
    for p in polys:
        for (x, y, z) in p["pts3"]:
            pts2_all.append(_project(x, y, z))
    for lab in labels:
        pts2_all.append((lab["px"], lab["py"]))
    if not pts2_all:
        raise ValueError("场景无可见多边形（空场景不可渲染——fail-loud）")
    minx = min(p[0] for p in pts2_all)
    maxx = max(p[0] for p in pts2_all)
    miny = min(p[1] for p in pts2_all)
    maxy = max(p[1] for p in pts2_all)
    diag = max(maxx - minx, maxy - miny, 1.0)
    margin = diag * 0.06
    vb = (minx - margin, miny - margin,
          (maxx - minx) + 2 * margin, (maxy - miny) + 2 * margin)

    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append(
        f'<svg id="ev-root" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(vb[0])} {_fmt(vb[1])} {_fmt(vb[2])} {_fmt(vb[3])}" '
        f'width="100%">')
    out.append(f'<title>{_xml_escape(scene["scene_name"])}</title>')
    out.append(f"<style>{_SVG_CSS}</style>")

    out.append('<g id="ev-scene">')
    # 多边形保持全局画家序（远→近），按层 class 标记——分层筛选按 class
    # 切换（不按 DOM 分组：分组会破坏跨层画家序）
    for p in polys:
        pts = " ".join(
            f"{_fmt(q[0])},{_fmt(q[1])}" for q in (_project(*pt) for pt in p["pts3"]))
        dash = ' stroke-dasharray="4 3"' if p["dashed"] else ""
        layer_key = p["group"][1:] if p["group"].startswith("l") else p["group"]
        out.append(
            f'<polygon class="ev-l ev-l-{layer_key}" points="{pts}" '
            f'fill="{p["fill"]}" fill-opacity="{p["opacity"]}" '
            f'stroke="{p["stroke"]}" stroke-width="{_fmt(diag * 0.0012)}"'
            f'{dash} stroke-linejoin="round"/>')
    for lab in labels:
        out.append(
            f'<g id="ev-layer-g-{lab["index"]}">'
            f'<text class="ev-l ev-l-{lab["index"]}" '
            f'x="{_fmt(lab["px"] - diag * 0.015)}" y="{_fmt(lab["py"])}" '
            f'text-anchor="end" font-size="{_fmt(diag * 0.024)}">'
            f'{_xml_escape(lab["text"])}</text></g>')
    out.append("</g>")

    # 图例筛选面板（场景组外——旋转不随动）
    layers = scene["layers"]
    row_h = diag * 0.045
    btn_w = diag * 0.30
    fs = diag * 0.024
    ux = vb[0] + diag * 0.02
    uy = vb[1] + diag * 0.02
    n_rows = len(layers) + (1 if scene["counts"]["n_vias"] else 0)
    panel_h = row_h * (n_rows + 3.4)
    out.append(
        f'<g id="ev-ui"><rect x="{_fmt(ux - fs * 0.5)}" y="{_fmt(uy - fs * 0.7)}" '
        f'width="{_fmt(btn_w + fs)}" height="{_fmt(panel_h)}" fill="#ffffff" '
        f'fill-opacity="0.88" stroke="#bbbbbb" stroke-width="{_fmt(diag * 0.0015)}" '
        f'rx="{_fmt(fs * 0.3)}"/>')
    out.append(
        f'<text x="{_fmt(ux)}" y="{_fmt(uy + fs)}" font-size="{_fmt(fs)}" '
        f'font-weight="bold">layers（点击筛选）</text>')
    row = 0
    for lay in layers:
        i = int(lay["index"])
        label_text = f"{i} {lay['name']}"
        ry = uy + row_h * (row + 1.3)
        out.append(
            f'<g class="ev-btn" data-layer="{i}">'
            f'<rect x="{_fmt(ux)}" y="{_fmt(ry - fs)}" width="{_fmt(btn_w)}" '
            f'height="{_fmt(row_h * 0.9)}" fill="{_layer_color(lay["material"])}" '
            f'fill-opacity="0.35" stroke="#999999" stroke-width="{_fmt(diag * 0.001)}" '
            f'rx="{_fmt(fs * 0.2)}"/>'
            f'<text x="{_fmt(ux + fs * 0.3)}" y="{_fmt(ry + fs * 0.35)}" '
            f'font-size="{_fmt(fs)}">{_xml_escape(label_text)}</text></g>')
        row += 1
    if scene["counts"]["n_vias"]:
        ry = uy + row_h * (row + 1.3)
        out.append(
            f'<text x="{_fmt(ux + fs * 0.3)}" y="{_fmt(ry + fs * 0.35)}" '
            f'font-size="{_fmt(fs)}">via ×{scene["counts"]["n_vias"]}（恒显）</text>')
        row += 1
    hy = uy + row_h * (row + 1.6)
    out.append(
        f'<text x="{_fmt(ux)}" y="{_fmt(hy)}" font-size="{_fmt(fs * 0.8)}" '
        f'fill="#777777">滚轮=缩放 拖拽=平移 Shift+拖拽=旋转 双击=复位</text>')
    out.append("</g>")

    out.append(f"<script><![CDATA[{_SVG_JS}]]></script>")
    out.append("</svg>")
    out.append("")
    return "\n".join(out)


# ── 形态 2：Three.js 兼容 JSON（ObjectLoader 场景图）────────────────────


def render_threejson(scene: dict[str, Any]) -> dict[str, Any]:
    """场景 → three.js ObjectLoader 兼容场景图 dict（JSON 直出即用）。

    实体=BoxGeometry；零厚片=PlaneGeometry+节点 rotation（映射关系：
    dz=0→XY 面无旋转、dy=0→绕 X 转 π/2（高落 z）、dx=0→绕 Y 转 π/2
    （宽落 z））；爆炸偏移随节点 position z 落档（explode 元数据在 extras）。
    """
    geometries: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    mat_key_idx: dict[tuple[str, float, float, float], str] = {}

    def _material(color_hex: str, opacity: float, metal: bool) -> str:
        metalness = 0.9 if metal else 0.0
        roughness = 0.3 if metal else 0.8
        key = (color_hex, float(opacity), metalness, roughness)
        if key in mat_key_idx:
            return mat_key_idx[key]
        idx = len(materials)
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        uuid = f"ev-mat-{idx:03d}"
        materials.append({
            "uuid": uuid, "type": "MeshStandardMaterial",
            "color": (r << 16) | (g << 8) | b,
            "metalness": metalness, "roughness": roughness,
            "transparent": opacity < 1.0, "opacity": float(opacity),
            "side": 2,
        })
        mat_key_idx[key] = uuid
        return uuid

    def _emit_node(name: str, geom: dict[str, Any], mat_uuid: str,
                   position: list[float], rotation: list[float] | None) -> None:
        gidx = len(geometries)
        geom["uuid"] = f"ev-geom-{gidx:04d}"
        geometries.append(geom)
        node: dict[str, Any] = {
            "uuid": f"ev-node-{len(children):04d}", "type": "Mesh",
            "name": name, "geometry": geom["uuid"], "material": mat_uuid,
            "position": position, "castShadow": False, "receiveShadow": False,
        }
        if rotation is not None:
            node["rotation"] = rotation
        children.append(node)

    for ent in scene["solids"]:
        lay = scene["layers"][ent["layer_index"]] if ent["layer_index"] is not None else None
        if ent["material"] in ("pec", "copper"):
            color = _layer_color(ent["material"])
        elif lay is not None:
            color = _layer_color(lay["material"])
        else:
            color = _layer_color(ent["material"])
        metal = ent["material"] in ("copper", "pec") or (
            lay is not None and lay["kind"] == "metal")
        if ent.get("envelope"):
            opacity = ENVELOPE_OPACITY
        elif ent["kind"] in ("sheet", "trace"):
            opacity = SHEET_OPACITY
        else:
            opacity = SOLID_OPACITY
        bx0, by0, bz0, bx1, by1, bz1 = ent["box_mm"]
        off = float(ent.get("offset_mm", 0.0))
        if ent["kind"] == "trace":
            # 走线=定向 PlaneGeometry：宽=段长+w（方帽）、高=w、绕 z 转段方位角
            (sx, sy), (ex, ey) = ent["segment_mm"]
            w = float(ent["width_mm"])
            _emit_node(str(ent["name"]),
                       {"type": "PlaneGeometry",
                        "width": math.hypot(ex - sx, ey - sy) + w, "height": w},
                       _material(color, opacity, metal),
                       [(sx + ex) / 2.0, (sy + ey) / 2.0, bz0 + off],
                       [0.0, 0.0, math.atan2(ey - sy, ex - sx)])
            continue
        dx, dy, dz = bx1 - bx0, by1 - by0, bz1 - bz0
        cx, cy, cz = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0, (bz0 + bz1) / 2.0 + off
        if dx > 0 and dy > 0 and dz > 0:
            _emit_node(str(ent["name"]),
                       {"type": "BoxGeometry", "width": dx, "height": dy,
                        "depth": dz, "widthSegments": 1, "heightSegments": 1,
                        "depthSegments": 1},
                       _material(color, opacity, metal), [cx, cy, cz], None)
        elif dz == 0:
            _emit_node(str(ent["name"]),
                       {"type": "PlaneGeometry", "width": dx, "height": dy},
                       _material(color, opacity, metal), [cx, cy, cz],
                       [0.0, 0.0, 0.0])
        elif dy == 0:
            _emit_node(str(ent["name"]),
                       {"type": "PlaneGeometry", "width": dx, "height": dz},
                       _material(color, opacity, metal), [cx, cy, cz],
                       [_PLANE_HALF_PI, 0.0, 0.0])
        elif dx == 0:
            _emit_node(str(ent["name"]),
                       {"type": "PlaneGeometry", "width": dz, "height": dy},
                       _material(color, opacity, metal), [cx, cy, cz],
                       [0.0, _PLANE_HALF_PI, 0.0])
    cav = scene.get("cavity")
    if cav is not None:
        bx0, by0, bz0, bx1, by1, bz1 = cav["box_mm"]
        off = float(cav.get("offset_mm", 0.0))
        _emit_node(str(cav["name"]),
                   {"type": "BoxGeometry", "width": bx1 - bx0,
                    "height": by1 - by0, "depth": bz1 - bz0,
                    "widthSegments": 1, "heightSegments": 1, "depthSegments": 1},
                   _material(CAVITY_COLOR, CAVITY_OPACITY, False),
                   [(bx0 + bx1) / 2.0, (by0 + by1) / 2.0,
                    (bz0 + bz1) / 2.0 + off], None)
    return {
        "metadata": {
            "version": _THREE_METADATA_VERSION, "type": "Object",
            "generator": f"rfauto exploded_view_service {_EXPLODED_VIEW_SCHEMA_VERSION}",
        },
        "geometries": geometries,
        "materials": materials,
        "object": {
            "uuid": "ev-root", "type": "Group",
            "name": scene["scene_name"], "children": children,
        },
        "extras": {
            "units": scene["units"], "schema": scene["schema"],
            "source_kind": scene["source_kind"], "explode": scene["explode"],
            "counts": scene["counts"], "notes": scene["notes"],
            "layers": scene["layers"],
        },
    }


# ── 形态 3：静态 PNG（matplotlib Agg）───────────────────────────────────


def render_png(scene: dict[str, Any], out_path: str | Path) -> None:
    """场景 → 静态 PNG（Agg OO API + plot_style 单源 + 零时间戳确定性）。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import PolyCollection
    from matplotlib.figure import Figure
    from matplotlib.patches import Patch

    from rfauto.core.plot_style import PAPER_FIGSIZE_DOUBLE, STYLE, paper_figure_context

    polys = _scene_polygons(scene)
    labels = _scene_labels(scene)
    verts: list[list[tuple[float, float]]] = []
    facecolors: list[tuple[float, float, float, float]] = []
    edgecolors: list[str] = []
    for p in polys:
        pts2 = [_project(*pt) for pt in p["pts3"]]
        verts.append(pts2)
        c = p["fill"]
        facecolors.append((int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0,
                           int(c[5:7], 16) / 255.0, float(p["opacity"])))
        edgecolors.append(p["stroke"])
    pts2_all = [pt for v in verts for pt in v]
    for lab in labels:
        pts2_all.append((lab["px"], lab["py"]))
    if not pts2_all:
        raise ValueError("场景无可见多边形（空场景不可渲染——fail-loud）")
    minx = min(p[0] for p in pts2_all)
    maxx = max(p[0] for p in pts2_all)
    miny = min(p[1] for p in pts2_all)
    maxy = max(p[1] for p in pts2_all)
    diag = max(maxx - minx, maxy - miny, 1.0)
    pad = diag * 0.06

    with paper_figure_context():
        fig = Figure(figsize=PAPER_FIGSIZE_DOUBLE, dpi=100)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)
        if verts:
            ax.add_collection(PolyCollection(
                verts, closed=True, facecolors=facecolors, edgecolors=edgecolors,
                linewidths=0.4))
        for lab in labels:
            ax.text(lab["px"] - diag * 0.015, lab["py"], lab["text"],
                    ha="right", va="center", fontsize=7.0, color="#333333")
        ax.set_xlim(minx - pad, maxx + pad)
        ax.set_ylim(miny - pad, maxy + pad)
        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.axis("off")
        ax.set_title(
            f"{scene['scene_name']} · explode ×{scene['explode']['factor']:g} "
            f"· {scene['source_kind']} · units mm", fontsize=9.0)
        handles = [
            Patch(facecolor=_layer_color(lay["material"]),
                  edgecolor=_shade_hex(_layer_color(lay["material"]), 0.45),
                  alpha=SOLID_OPACITY,
                  label=f"{lay['index']} {lay['name']}")
            for lay in scene["layers"]
        ]
        if scene.get("cavity") is not None:
            handles.append(Patch(facecolor=CAVITY_COLOR, alpha=CAVITY_OPACITY,
                                 linestyle="--", label="cavity (carved void)"))
        if scene["counts"]["n_vias"]:
            handles.append(Patch(facecolor=_layer_color("copper"),
                                 label=f"via ×{scene['counts']['n_vias']}"))
        ax.legend(handles=handles, loc="upper right", fontsize=6.5,
                  framealpha=0.85)
        fig.tight_layout()
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(out), format="png", dpi=int(STYLE["savefig.dpi"]),
                    metadata={"Software": "rfauto exploded_view_service"})


# ── 服务入口（信封编排）─────────────────────────────────────────────────

_ALLOWED_FORMATS = ("svg", "json", "png")


def _sanitize_stem(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("._-")
    return s or "exploded_view"


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text_deterministic(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return len(data)


def render_exploded_view(
    spec: dict[str, Any],
    *,
    explode_factor: float = EXPLODE_FACTOR_DEFAULT,
    formats: tuple[str, ...] | list[str] | str = ("svg", "json", "png"),
    out_dir: str | Path | None = None,
    spec_path: str | Path | None = None,
) -> dict[str, Any]:
    """爆炸视图渲染入口（规则 4 服务层 JSON 进出；lint 零 ERROR 闭环）。

    Parameters
    ----------
    spec : dict
        声明式 spec：``{"source": "layered_stack", "spec": {...}|缺省名义}``
        或 ``{"source": "kicad", "pcb_path": "...kicad_pcb",
        "copper_kinds"?: {...}, "require_epsilon_r"?: bool,
        "scene_name"?: str}``。
    explode_factor : float
        爆炸系数（≥0；0=收拢；声明参数随信封 explode 键落档——铁律 7）。
    formats : 序列|str
        ``svg|json|png`` 子集或 ``"all"``。
    out_dir : 路径|None
        产物根（缺省=spec 文件同目录；再缺省=cwd）；渲染产物
        ``<stem>.svg/.json/.png`` + ``<stem>_lint.json``（lint 报告附输出）。
    spec_path : 路径|None
        spec 文件路径（pcb_path 相对解析锚+产物缺省目录锚，#144 零 cwd 依赖）。
    """
    if (isinstance(explode_factor, bool)
            or not isinstance(explode_factor, (int, float))
            or not math.isfinite(float(explode_factor))
            or float(explode_factor) < 0.0):
        return error_envelope(
            f"explode_factor 必须为 ≥0 的有限数，得到 {explode_factor!r}")
    factor = float(explode_factor)
    if isinstance(formats, str):
        formats = (formats,)
    fmts: list[str] = []
    for f in formats:
        if f == "all":
            fmts.extend(_ALLOWED_FORMATS)
        elif f in _ALLOWED_FORMATS:
            fmts.append(f)
        else:
            return error_envelope(
                f"未知 format {f!r}（可用 svg|json|png|all）")
    fmts = list(dict.fromkeys(fmts))
    if not fmts:
        return error_envelope("formats 为空——至少一个 svg|json|png|all")
    if not isinstance(spec, dict):
        return error_envelope(
            f"spec 必须为 JSON 对象（得 {type(spec).__name__}）")
    try:
        scene = build_scene(spec, explode_factor=factor, spec_path=spec_path)
    except ValueError as exc:
        return error_envelope(f"spec 解析失败: {exc}")
    except (OSError, UnicodeDecodeError) as exc:
        return error_envelope(f"pcb_path 读取失败: {exc}")

    lint_report = _lint_report_for_scene(scene, spec)
    gate_errs = _gate_errors(lint_report)
    if gate_errs:
        return error_envelope(
            gate_errs, lint=lint_report, lint_pass=False,
            view_schema=_EXPLODED_VIEW_SCHEMA_VERSION, scene_name=scene["scene_name"],
            rendered=False)

    stem = _sanitize_stem(scene["scene_name"])
    if out_dir is not None:
        root = Path(out_dir)
    elif spec_path is not None:
        root = Path(spec_path).resolve().parent
    else:
        root = Path.cwd()
    root.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Any] = {}
    if "svg" in fmts:
        p = root / f"{stem}.svg"
        n = _write_text_deterministic(p, render_svg(scene))
        outputs["svg"] = {"path": str(p), "bytes": n, "sha256": _sha256_of(p)}
    if "json" in fmts:
        p = root / f"{stem}.json"
        text = json.dumps(render_threejson(scene), indent=1,
                          ensure_ascii=False) + "\n"
        n = _write_text_deterministic(p, text)
        outputs["json"] = {"path": str(p), "bytes": n, "sha256": _sha256_of(p)}
    if "png" in fmts:
        p = root / f"{stem}.png"
        render_png(scene, p)
        outputs["png"] = {"path": str(p), "bytes": p.stat().st_size,
                          "sha256": _sha256_of(p)}
    lint_path = root / f"{stem}_lint.json"
    lint_text = json.dumps(lint_report, indent=1, ensure_ascii=False) + "\n"
    _write_text_deterministic(lint_path, lint_text)
    outputs["lint_json"] = {"path": str(lint_path),
                            "bytes": lint_path.stat().st_size,
                            "sha256": _sha256_of(lint_path)}
    return ok_envelope(
        view_schema=_EXPLODED_VIEW_SCHEMA_VERSION,
        scene_name=scene["scene_name"],
        source_kind=scene["source_kind"],
        units=scene["units"],
        explode=scene["explode"],
        counts=scene["counts"],
        outputs=outputs,
        lint={k: lint_report[k] for k in
              ("lint_pass", "issues", "counts", "model_units", "summary")},
        lint_pass=bool(lint_report.get("lint_pass")),
        warnings=scene.get("warnings", []),
        view=scene,
        out_dir=str(root),
    )


# ── 导出接口预留（v0 未实现——签名+边界声明）────────────────────────────


def export_step(scene: dict[str, Any], out_path: str | Path) -> None:
    """导出 STEP（AP214）——**v0 接口预留，未实现**。

    边界声明：STEP 需要 B-rep 建模内核（OCC / cadquery 类）；仓内零该依赖，
    铁律 4（零新依赖）下不引入——受理面=SVG/JSON/PNG 三形态。后续落地方向：
    由本场景的盒原语逐盒生成 B-rep 实体（盒面合围，零布尔），单位 mm。
    """
    raise NotImplementedError(
        "STEP 导出为接口预留（exploded-view/v0 未实现）——v0 受理面="
        "svg|json|png 三形态；STEP 需 B-rep 内核（OCC 类），零新依赖约束下"
        "后续批次落地（见模块 docstring 导出接口预留节）")


def export_glb(scene: dict[str, Any], out_path: str | Path) -> None:
    """导出 GLB（glTF 2.0 二进制容器）——**v0 接口预留，未实现**。

    边界声明：GLB=glTF 2.0 的 JSON+二进制 buffer 打包；升级路径=把
    :func:`render_threejson` 的盒/面原语转为 glTF meshes+accessors+buffer
    （position 数组逐字节直通，零几何重算——铁律 7）。v0 受理面=三形态。
    """
    raise NotImplementedError(
        "GLB 导出为接口预留（exploded-view/v0 未实现）——v0 受理面="
        "svg|json|png 三形态；升级路径=render_threejson 场景图 → glTF 2.0 "
        "meshes/accessors/buffer 打包（见模块 docstring）")
