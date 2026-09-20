"""KiCad PCB→EM 提取器（B6 stage-1，pcbnew 直读侧）。

子进程惯例同 kicad_pcell/kicad_drc：生成提取脚本 → KiCad 自带
Python（3.11）执行 → stdout JSON 产物（标记包裹）→ 项目侧解析。

KiCad 10.0.6 API 探查结论（子进程 dir() 实测，写死依据）：
- 几何：BOARD.GetTracks() 同时含 PCB_TRACK 与 PCB_VIA（按 GetClass 分流）；
  PCB_TRACK.GetStart/GetEnd/GetWidth/GetLength/GetLayerName/GetNetname，
  PCB_VIA.GetPosition/GetWidth(焊盘)/GetDrill/GetNetname——内部单位 nm，
  1e6 nm = 1 mm。
- 铜层名：KiCad 10 层 id 重排（B_Cu=2 而非旧 31），遍历
  0..GetCopperLayerStackMaxId() 用 pcbnew.IsCopperLayer(id) 过滤后
  GetLayerName(id)，禁止写死 id。
- 板厚：GetDesignSettings().GetBoardThickness()（nm）。
- 板框：BOARD.GetBoardOutline() 在 KiCad 10 返回裸 SwigPyObject（无
  wrapper/Cast，不可用）→ 改用
  GetBoardPolygonOutlines(SHAPE_POLY_SET, True) 填充后取 BBox()。
- 叠层 er：GetDesignSettings().GetStackupDescriptor() 同样返回裸
  SwigPyObject（无 BOARD_STACKUP wrapper / Cast_to_BOARD_STACKUP），
  API 路不可用 → er 从 .kicad_pcb 文本 (stackup ...) s-expression 解析
  （_parse_stackup）；板无 stackup 节（python 新建板默认如此）时
  返回 None 并注明。
- ZONE_FILLER.Fill 单参调用段错误（10.0.6 实测），必须 Fill(zones, False)。
- ZONE 自带 GetLayerName() 恒返回 "F.Cu"（stage-2 探针实测，
  B.Cu zone 亦然）——zone 层名必须走 board.GetLayerName(int(z.GetLayer()))。

extract_pcb JSON 契约：
成功 {"ok": True, "board": {...}, "traces": [...], "vias": [...],
      "outline": {...}, "zones": [...], "footprints": [...]}
失败 {"ok": False, "errors": [str, ...]}

traces 为折线聚合结果：同 (net, layer, width) 且端点重合（±1 nm）的
连续段拼成一条 polyline（points_mm 首尾相连），跨 net/宽度不拼。

zones（B6 stage-2 深化）：每 zone 给 net/layer/layers/clearance_mm/
min_thickness_mm/priority/filled/outline_points_mm（首轮廓点列，nm→mm
无损换算）/n_outlines；clearance 未设（-1）时为 None。stage-2 深化
新增三键：outlines_mm（全部设计轮廓点列）、holes_mm
（填充多边形孔洞点列，跨填充轮廓展平）、filled_polys_mm（填充纹理
[{outer_mm, holes_mm}]）。KiCad 实测坑：填充多边形以**断裂**
（fractured）形式存储——孔洞被编码成外轮廓上的零宽狭缝，直接
HoleCount() 恒为 0；必须拷贝 SHAPE_POLY_SET 后 Unfracture() 才还原
孔洞（GetFilledPolysList 返回 shared_ptr，拷贝构造隔离、不动 zone
自有存储）。提取脚本本体只读：绝不触发 ZONE_FILLER，未填充板
（IsFilled=False）如实 filled=False 且 filled_polys_mm 为空。
footprints（B6 stage-2 深化）：每 footprint 给 reference/value/位置 +
pads（number/net/shape 码/位置/尺寸/layers）。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

KICAD_PYTHON = r"E:\KiCad\bin\python.exe"
KICAD_SITE_PACKAGES = r"E:\KiCad\bin\Lib\site-packages"

_NM_PER_MM = 1e6
_JSON_START = "KICAD_EXTRACT_JSON_START"
_JSON_END = "KICAD_EXTRACT_JSON_END"
_CHAIN_EPS_NM = 1  # 段端点重合判定容差（KiCad 内部单位 nm）
_SUBPROCESS_TIMEOUT_S = 120

# demo 板（CPWG 往返锚）标称：与 openems_templates TEMPLATE_NOMINAL["cpw"]
# 一致（w=0.849/gap=0.2/L=40，rogers4350b h=0.508 er=3.66 口径）。
DEMO_W_MM = 0.849
DEMO_GAP_MM = 0.2
DEMO_LINE_LEN_MM = 40.0
DEMO_BOARD_MM = (60.0, 30.0)
DEMO_TRACE_ORIGIN_MM = (10.0, 15.0)
DEMO_VIA_XS_MM = (12.0, 24.0, 36.0, 48.0)
DEMO_VIA_Y_MM = 18.0  # 主线 y=15 下移 3mm 的地过孔行
DEMO_VIA_DRILL_MM = 0.3
DEMO_VIA_PAD_MM = 0.6
DEMO_PAD_W_MM = 0.8  # 端射焊盘（w×h 故意不等，抓轴交换）
DEMO_PAD_H_MM = 0.6
DEMO_COPPER_THICK_MM = 0.035
DEMO_CORE_THICK_MM = 0.508
DEMO_ER = 3.66
DEMO_TAN_D = 0.0037

_EXTRACT_SCRIPT_TEMPLATE = '''
import sys
sys.path.insert(0, r"{site_packages}")
import json
import pcbnew

errors = []
raw = {"ok": False, "errors": errors}
try:
    board = pcbnew.LoadBoard(r"{pcb_path}")
    raw["kicad_version"] = str(pcbnew.GetBuildVersion())
    ds = board.GetDesignSettings()
    raw["layer_count"] = int(ds.GetCopperLayerCount())
    raw["thickness_nm"] = int(ds.GetBoardThickness())

    copper_layers = []
    max_id = int(board.GetCopperLayerStackMaxId())
    for lid in range(0, max_id + 1):
        try:
            if pcbnew.IsCopperLayer(lid):
                copper_layers.append(
                    {"id": lid, "name": str(board.GetLayerName(lid))})
        except Exception:
            pass
    raw["copper_layers"] = copper_layers

    segments = []
    vias = []
    for item in board.GetTracks():
        cls = str(item.GetClass())
        if cls == "PCB_TRACK":
            s = item.GetStart()
            e = item.GetEnd()
            segments.append({
                "net": str(item.GetNetname()),
                "layer": str(item.GetLayerName()),
                "width_nm": int(item.GetWidth()),
                "x1_nm": int(s.x), "y1_nm": int(s.y),
                "x2_nm": int(e.x), "y2_nm": int(e.y),
                "length_nm": int(round(float(item.GetLength()))),
            })
        elif cls == "PCB_VIA":
            # KiCad 10 padstack 口径：GetWidth() 无参调用触发 assert
            # （会挂住进程），必须带层参数；回退 GetFrontWidth。
            try:
                pad_nm = int(item.GetWidth(pcbnew.F_Cu))
            except Exception:
                pad_nm = int(item.GetFrontWidth())
            p = item.GetPosition()
            vias.append({
                "net": str(item.GetNetname()),
                "x_nm": int(p.x), "y_nm": int(p.y),
                "pad_nm": pad_nm,
                "drill_nm": int(item.GetDrill()),
            })
    raw["segments"] = segments
    raw["vias"] = vias

    # B6 stage-2 深化：zone（GND 平面/缝宽事实源）+ footprint/pad。
    zones = []
    for z in board.Zones():
        lid = int(z.GetLayer())
        # KiCad 10 坑：z.GetLayerName() 恒返回 "F.Cu"，层名走 board 侧。
        layer_names = []
        try:
            layer_names = [str(board.GetLayerName(int(i)))
                           for i in z.GetLayerSet().Seq()]
        except Exception:
            pass
        outlines = []
        poly = z.Outline()
        for oi in range(poly.OutlineCount()):
            chain = poly.Outline(oi)
            outlines.append([[int(chain.GetPoint(vi).x),
                              int(chain.GetPoint(vi).y)]
                             for vi in range(chain.PointCount())])
        try:
            clearance_nm = int(z.GetLocalClearance())
        except Exception:
            clearance_nm = -1
        # 填充纹理（B6 stage-2 深化）：HasFilledPolysForLayer 先探 →
        # GetFilledPolysList 拷贝 → Unfracture 还原孔洞（KiCad 填充存储
        # 为断裂多边形，孔洞=外轮廓零宽狭缝、直接 HoleCount 恒 0，
        # demo 板实测）。best-effort：单 zone 填充提取失败
        # 不拖垮整个提取（#105）。
        filled_polys = []
        try:
            if z.IsFilled() and z.HasFilledPolysForLayer(lid):
                fps = pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(lid))
                fps.Unfracture()
                for fi in range(fps.OutlineCount()):
                    fc = fps.Outline(fi)
                    outer = [[int(fc.GetPoint(vi).x), int(fc.GetPoint(vi).y)]
                             for vi in range(fc.PointCount())]
                    holes = []
                    for hi in range(fps.HoleCount(fi)):
                        hc = fps.Hole(fi, hi)
                        holes.append([[int(hc.GetPoint(vi).x),
                                       int(hc.GetPoint(vi).y)]
                                      for vi in range(hc.PointCount())])
                    filled_polys.append({"outer_nm": outer,
                                         "holes_nm": holes})
        except Exception:
            filled_polys = []
        zones.append({
            "net": str(z.GetNetname()),
            "layer_id": lid,
            "layer": str(board.GetLayerName(lid)),
            "layers": layer_names,
            "clearance_nm": clearance_nm,
            "min_thickness_nm": int(z.GetMinThickness()),
            "priority": int(z.GetAssignedPriority()),
            "filled": bool(z.IsFilled()),
            "outlines_nm": outlines,
            "filled_polys_nm": filled_polys,
        })

    footprints = []
    for fp in board.GetFootprints():
        pads = []
        for p in fp.Pads():
            sz = p.GetSize()
            try:
                pad_layers = [str(board.GetLayerName(int(i)))
                              for i in p.GetLayerSet().Seq()]
            except Exception:
                pad_layers = []
            pads.append({
                "number": str(p.GetNumber()),
                "net": str(p.GetNetname()),
                "shape": int(p.GetShape()),
                "x_nm": int(p.GetPosition().x),
                "y_nm": int(p.GetPosition().y),
                "w_nm": int(sz.x), "h_nm": int(sz.y),
                "layers": pad_layers,
            })
        pads.sort(key=lambda d: (d["x_nm"], d["y_nm"], d["number"]))
        footprints.append({
            "reference": str(fp.GetReference()),
            "value": str(fp.GetValue()),
            "x_nm": int(fp.GetPosition().x),
            "y_nm": int(fp.GetPosition().y),
            "pads": pads,
        })
    footprints.sort(key=lambda f: (f["reference"], f["x_nm"], f["y_nm"]))
    raw["zones"] = zones
    raw["footprints"] = footprints

    poly = pcbnew.SHAPE_POLY_SET()
    got = bool(board.GetBoardPolygonOutlines(poly, True))
    if got and poly.OutlineCount() > 0:
        bb = poly.BBox()
        raw["outline_bbox_nm"] = [int(bb.GetLeft()), int(bb.GetTop()),
                                  int(bb.GetRight()), int(bb.GetBottom())]
    else:
        errors.append("GetBoardPolygonOutlines 未得到板框多边形")
        raw["outline_bbox_nm"] = None
    raw["ok"] = True
except Exception as exc:  # noqa: BLE001 —— 产物侧统一转 ok=False
    errors.append("{}: {}".format(type(exc).__name__, exc))

print("{json_start}")
print(json.dumps(raw, ensure_ascii=False))
print("{json_end}")
'''.replace("{site_packages}", KICAD_SITE_PACKAGES)


def _nm_to_mm(nm: float) -> float:
    return nm / _NM_PER_MM


def _parse_stdout_json(stdout: str) -> dict[str, Any] | None:
    """从子进程 stdout 提取标记包裹的 JSON（pcbnew/图片库可能打印杂音）。"""
    if _JSON_START not in stdout or _JSON_END not in stdout:
        return None
    body = stdout.split(_JSON_START, 1)[1].split(_JSON_END, 1)[0]
    return json.loads(body)


def _run_extract_script(pcb_path: Path, kicad_python: str) -> dict[str, Any]:
    """跑 KiCad 子进程提取，返回原始 nm 产物或 ok=False 契约。"""
    script = (
        _EXTRACT_SCRIPT_TEMPLATE
        .replace("{pcb_path}", str(pcb_path))
        .replace("{json_start}", _JSON_START)
        .replace("{json_end}", _JSON_END)
    )
    try:
        result = subprocess.run(
            [kicad_python, "-X", "faulthandler", "-c", script],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"ok": False, "errors": [f"KiCad Python 不存在: {kicad_python}"]}
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "errors": [f"KiCad 提取超时（>{_SUBPROCESS_TIMEOUT_S}s）"]}
    except Exception as exc:
        return {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}

    if result.returncode != 0:
        stderr = (result.stderr or "")[-500:]
        return {"ok": False, "errors": [
            f"KiCad 提取退出码 {result.returncode}: {stderr}"]}
    try:
        raw = _parse_stdout_json(result.stdout or "")
    except json.JSONDecodeError as exc:
        return {"ok": False, "errors": [f"提取产物 JSON 解析失败: {exc}"]}
    if raw is None:
        return {"ok": False, "errors": ["KiCad 提取产物无 JSON 标记",
                                        (result.stdout or "")[-300:]]}
    if not raw.get("ok"):
        return {"ok": False,
                "errors": raw.get("errors") or ["KiCad 提取失败（无明细）"]}
    return raw


def _chain_group(
    segs: list[tuple[int, int, int, int, int]],
) -> list[list[tuple[int, int]]]:
    """把同组（同 net/layer/width）的段按端点重合拼成折线。

    segs 元素：(x1, y1, x2, y2, length_nm)。返回点列列表（nm 整数）。
    """
    def same(p: tuple[int, int], q: tuple[int, int]) -> bool:
        return (abs(p[0] - q[0]) <= _CHAIN_EPS_NM
                and abs(p[1] - q[1]) <= _CHAIN_EPS_NM)

    remaining = list(segs)
    polylines: list[list[tuple[int, int]]] = []
    while remaining:
        x1, y1, x2, y2, _ = remaining.pop(0)
        pts = [(x1, y1), (x2, y2)]
        changed = True
        while changed:
            changed = False
            head, tail = pts[0], pts[-1]
            for i, (ax, ay, bx, by, _) in enumerate(remaining):
                a, b = (ax, ay), (bx, by)
                if same(tail, a):
                    pts.append(b)
                elif same(tail, b):
                    pts.append(a)
                elif same(head, b):
                    pts.insert(0, a)
                elif same(head, a):
                    pts.insert(0, b)
                else:
                    continue
                remaining.pop(i)
                changed = True
                break
        polylines.append(pts)
    return polylines


def _aggregate_traces(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原始段（nm）→ 聚合 trace 列表（mm 折线）。

    分组键 (net, layer, width_nm)；组内端点重合（±1 nm）即拼接；
    输出按 (net, layer, width_mm, 首点 x, y) 排序保证确定性。
    """
    groups: dict[tuple[str, str, int], list[tuple[int, int, int, int, int]]] = {}
    for seg in raw_segments:
        key = (seg["net"], seg["layer"], int(seg["width_nm"]))
        groups.setdefault(key, []).append(
            (int(seg["x1_nm"]), int(seg["y1_nm"]),
             int(seg["x2_nm"]), int(seg["y2_nm"]),
             int(seg["length_nm"])))

    traces: list[dict[str, Any]] = []
    for (net, layer, width_nm), segs in groups.items():
        for pts in _chain_group(segs):
            length_nm = 0
            for i in range(len(pts) - 1):
                dx = pts[i + 1][0] - pts[i][0]
                dy = pts[i + 1][1] - pts[i][1]
                length_nm += round((dx * dx + dy * dy) ** 0.5)
            traces.append({
                "net": net,
                "layer": layer,
                "width_mm": _nm_to_mm(width_nm),
                "length_mm": _nm_to_mm(length_nm),
                "points_mm": [[_nm_to_mm(x), _nm_to_mm(y)] for x, y in pts],
            })
    traces.sort(key=lambda t: (t["net"], t["layer"], t["width_mm"],
                               t["points_mm"][0][0], t["points_mm"][0][1]))
    return traces


_STACKUP_LAYER_SPLIT = re.compile(r'\(layer\s+"')
_STACKUP_FIELDS: dict[str, re.Pattern[str]] = {
    "thickness_mm": re.compile(r"\(thickness\s+([0-9.eE+-]+)\s*\)"),
    "er": re.compile(r"\(epsilon_r\s+([0-9.eE+-]+)\s*\)"),
    "tan_d": re.compile(r"\(loss_tangent\s+([0-9.eE+-]+)\s*\)"),
}


def _extract_stackup_block(pcb_text: str) -> str | None:
    """按括号配平截取 (stackup ...) 块；无则 None。"""
    start = pcb_text.find("(stackup")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(pcb_text)):
        if pcb_text[i] == "(":
            depth += 1
        elif pcb_text[i] == ")":
            depth -= 1
            if depth == 0:
                return pcb_text[start:i + 1]
    return None


def _parse_stackup(pcb_text: str) -> dict[str, Any]:
    """解析 .kicad_pcb 文本里的 (stackup ...) 节。

    返回 {"dielectrics": [{name, thickness_mm, er, tan_d}, ...],
          "er": float | None, "note": str}。
    KiCad 10 python 绑定暴露不了 BOARD_STACKUP（裸 SwigPyObject），
    文本 s-expression 是 er 的唯一稳定来源；python 新建板无 stackup 节。
    """
    block = _extract_stackup_block(pcb_text)
    if block is None:
        return {"dielectrics": [], "er": None,
                "note": "KiCad 板无 stackup 节，er 未存（python 新建板默认）"}
    dielectrics: list[dict[str, Any]] = []
    chunks = _STACKUP_LAYER_SPLIT.split(block)[1:]
    for chunk in chunks:
        name = chunk.split('"', 1)[0] if '"' in chunk else ""
        if "dielectric" not in name.lower():
            continue
        entry: dict[str, Any] = {"name": name}
        for field, rx in _STACKUP_FIELDS.items():
            m = rx.search(chunk)
            entry[field] = float(m.group(1)) if m else None
        dielectrics.append(entry)
    er = next((d["er"] for d in dielectrics if d["er"] is not None), None)
    note = ("er 来自 .kicad_pcb (stackup) s-expression 文本解析"
            if er is not None else
            "KiCad 板有 stackup 节但介质层未存 epsilon_r")
    return {"dielectrics": dielectrics, "er": er, "note": note}


def _pts_mm(pts_nm: list[Any]) -> list[list[float]]:
    """nm 整数点列 → mm 浮点点列（无损换算）。"""
    return [[_nm_to_mm(int(x)), _nm_to_mm(int(y))] for x, y in pts_nm]


def _parse_zones(raw_zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原始 zone（nm）→ 契约 zone 列表（mm）。

    输出按 (net, layer, 首轮廓首点) 排序保证确定性。旧键 outline_points_mm
    仍只给首轮廓点列（cpw_design_from_extract 兼容）；stage-2 深化新增
    outlines_mm（全部设计轮廓）、filled_polys_mm（填充纹理 [{outer_mm,
    holes_mm}]，未填充板为空）、holes_mm（填充孔洞跨轮廓展平）。
    """
    zones: list[dict[str, Any]] = []
    for z in raw_zones:
        outlines = z.get("outlines_nm") or []
        first = outlines[0] if outlines else []
        clearance_nm = int(z.get("clearance_nm", -1))
        fill_polys: list[dict[str, Any]] = []
        for fp in z.get("filled_polys_nm") or []:
            fill_polys.append({
                "outer_mm": _pts_mm(fp.get("outer_nm") or []),
                "holes_mm": [_pts_mm(h) for h in fp.get("holes_nm") or []],
            })
        zones.append({
            "net": str(z.get("net", "")),
            "layer": str(z.get("layer", "")),
            "layers": [str(x) for x in z.get("layers", [])],
            "clearance_mm": (_nm_to_mm(clearance_nm) if clearance_nm >= 0
                             else None),
            "min_thickness_mm": _nm_to_mm(int(z.get("min_thickness_nm", 0))),
            "priority": int(z.get("priority", 0)),
            "filled": bool(z.get("filled", False)),
            "outline_points_mm": _pts_mm(first),
            "n_outlines": len(outlines),
            "outlines_mm": [_pts_mm(o) for o in outlines],
            "holes_mm": [h for fp in fill_polys for h in fp["holes_mm"]],
            "filled_polys_mm": fill_polys,
        })
    zones.sort(key=lambda z: (z["net"], z["layer"],
                              z["outline_points_mm"][0][0]
                              if z["outline_points_mm"] else 0.0,
                              z["outline_points_mm"][0][1]
                              if z["outline_points_mm"] else 0.0))
    return zones


def _parse_footprints(raw_fps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原始 footprint/pad（nm）→ 契约列表（mm），按 reference 排序。"""
    fps: list[dict[str, Any]] = []
    for fp in raw_fps:
        fps.append({
            "reference": str(fp.get("reference", "")),
            "value": str(fp.get("value", "")),
            "x_mm": _nm_to_mm(int(fp.get("x_nm", 0))),
            "y_mm": _nm_to_mm(int(fp.get("y_nm", 0))),
            "pads": [{
                "number": str(p.get("number", "")),
                "net": str(p.get("net", "")),
                "shape": int(p.get("shape", 0)),
                "x_mm": _nm_to_mm(int(p.get("x_nm", 0))),
                "y_mm": _nm_to_mm(int(p.get("y_nm", 0))),
                "w_mm": _nm_to_mm(int(p.get("w_nm", 0))),
                "h_mm": _nm_to_mm(int(p.get("h_nm", 0))),
                "layers": [str(x) for x in p.get("layers", [])],
            } for p in fp.get("pads", [])],
        })
    fps.sort(key=lambda f: (f["reference"], f["x_mm"], f["y_mm"]))
    return fps


def extract_pcb(
    pcb_path: str | Path, kicad_python: str | None = None
) -> dict[str, Any]:
    """从 .kicad_pcb 提取叠层/走线/过孔/板框/zone/footprint（B6 直读侧）。

    返回契约见模块 docstring。文件不存在/KiCad 子进程失败时
    {"ok": False, "errors": [...]}。
    """
    path = Path(pcb_path)
    python_exe = kicad_python or KICAD_PYTHON
    if not path.exists():
        return {"ok": False, "errors": [f"PCB 文件不存在: {path}"]}

    raw = _run_extract_script(path, python_exe)
    if not raw.get("ok"):
        return {"ok": False, "errors": raw.get("errors") or ["提取失败"]}

    stackup = _parse_stackup(path.read_text(encoding="utf-8", errors="replace"))
    bbox = raw.get("outline_bbox_nm")
    outline: dict[str, Any] = {}
    if bbox is not None:
        left, top, right, bottom = bbox
        outline = {
            "min_mm": [_nm_to_mm(left), _nm_to_mm(top)],
            "max_mm": [_nm_to_mm(right), _nm_to_mm(bottom)],
            "width_mm": _nm_to_mm(right - left),
            "height_mm": _nm_to_mm(bottom - top),
        }

    return {
        "ok": True,
        "board": {
            "kicad_version": raw.get("kicad_version", ""),
            "layer_count": int(raw.get("layer_count", 0)),
            "copper_layers": [c["name"] for c in raw.get("copper_layers", [])],
            "thickness_mm": _nm_to_mm(int(raw.get("thickness_nm", 0))),
            "substrate_er": stackup["er"],
            "substrate_note": stackup["note"],
            "stackup": {"dielectrics": stackup["dielectrics"]},
        },
        "traces": _aggregate_traces(raw.get("segments", [])),
        "vias": sorted(({
            "net": v.get("net", ""),
            "x_mm": _nm_to_mm(int(v["x_nm"])),
            "y_mm": _nm_to_mm(int(v["y_nm"])),
            "pad_diameter_mm": _nm_to_mm(int(v["pad_nm"])),
            "drill_mm": _nm_to_mm(int(v["drill_nm"])),
        } for v in raw.get("vias", [])),
            key=lambda v: (v["net"], v["x_mm"], v["y_mm"])),
        "outline": outline,
        "zones": _parse_zones(raw.get("zones", [])),
        "footprints": _parse_footprints(raw.get("footprints", [])),
    }


# ---------------------------------------------------------------------------
# demo 板构建（CPWG 往返锚板）
# ---------------------------------------------------------------------------

_FILL_SCRIPT_TEMPLATE = '''
import sys
sys.path.insert(0, r"{site_packages}")
import json
import pcbnew

errors = []
out = {"ok": False, "errors": errors}

def fill():
    board = pcbnew.LoadBoard(r"{pcb_path}")
    zones = list(board.Zones())
    # #214：Fill 必须两参（aCheck=False）。fill 腿独立子进程（与建板
    # 分离、LoadBoard 走已保存文件）——同会话建板+Fill 曾间歇段错误
    # （#210 家族），进程隔离根治；5 次重试兜底在调用侧（#191）。
    ok = pcbnew.ZONE_FILLER(board).Fill(zones, False)
    if not ok:
        errors.append("ZONE_FILLER.Fill 返回 False")
        return False
    if not pcbnew.SaveBoard(r"{pcb_path}", board):
        errors.append("SaveBoard 失败")
        return False
    return True

try:
    out["ok"] = bool(fill())
except Exception as exc:  # noqa: BLE001 —— 统一转契约失败
    errors.append("{}: {}".format(type(exc).__name__, exc))

print("{json_start}")
print(json.dumps(out, ensure_ascii=False))
print("{json_end}")
'''.replace("{site_packages}", KICAD_SITE_PACKAGES)


def _run_kicad_with_retry(
    script: str, python_exe: str,
) -> tuple[subprocess.CompletedProcess | None, list[str], str | None]:
    """KiCad 子进程跑脚本；原生崩溃（非零退出）重试至多 5 次。

    #191 兜底哲学：原生 0xC0000005 无法进程内捕获，只能进程隔离重试；
    重试间 sleep(0.5) 冷却（#210 KiCad 配置/锁文件残留避让）。

    返回 (result, 逐次错误列表, 致命类别)。致命类别 "spawn"/"timeout"
    时 result=None，调用方直接转失败契约；其余走产物解析路径。
    """
    result: subprocess.CompletedProcess | None = None
    errors: list[str] = []
    for attempt in range(5):
        try:
            result = subprocess.run(
                [python_exe, "-X", "faulthandler", "-c", script],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
            )
        except FileNotFoundError:
            return None, [python_exe], "spawn"
        except subprocess.TimeoutExpired:
            return None, [], "timeout"
        if result.returncode == 0:
            break
        errors.append(
            f"KiCad 退出码 {result.returncode}（第 {attempt + 1} 次尝试）: "
            f"{(result.stderr or '')[-800:]}")
        time.sleep(0.5)  # 进程间冷却：KiCad 配置/锁文件残留避让（#210）
    return result, errors, None


def _fill_demo_zones(pcb_path: Path, python_exe: str) -> tuple[bool, list[str]]:
    """opt-in fill 腿：独立子进程 ZONE_FILLER(board).Fill(zones, False)。

    返回 (填充是否成功, 过程错误列表)。失败不修改板文件语义之外的
    状态——板仍是建板子进程产出的未填充板。
    """
    script = (
        _FILL_SCRIPT_TEMPLATE
        .replace("{pcb_path}", str(pcb_path))
        .replace("{json_start}", _JSON_START)
        .replace("{json_end}", _JSON_END)
    )
    result, errors, fatal = _run_kicad_with_retry(script, python_exe)
    if fatal is not None:
        errors.append(f"KiCad 填充子进程致命错误（{fatal}）")
        return False, errors
    try:
        raw = _parse_stdout_json(result.stdout or "") if result else None
    except json.JSONDecodeError:
        raw = None
    if raw is None:
        errors.append((result.stdout or "")[-300:] or "填充产物无输出")
        if result is not None and result.stderr:
            errors.append(result.stderr[-500:])
        return False, errors
    if not raw.get("ok"):
        errors.extend(raw.get("errors") or ["KiCad 填充失败（无明细）"])
        return False, errors
    return True, errors


_BUILD_SCRIPT_TEMPLATE = '''
import sys
sys.path.insert(0, r"{site_packages}")
import json
import pcbnew

errors = []
out = {"ok": False, "errors": errors}

def build():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness({thickness_nm})

    # 板框：Edge.Cuts 矩形（4 段）
    x0 = int({bx0_mm} * 1e6); y0 = int({by0_mm} * 1e6)
    x1 = int({bx1_mm} * 1e6); y1 = int({by1_mm} * 1e6)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s = corners[i]; e = corners[(i + 1) % 4]
        sh.SetStart(pcbnew.VECTOR2I(s[0], s[1]))
        sh.SetEnd(pcbnew.VECTOR2I(e[0], e[1]))
        sh.SetLayer(pcbnew.Edge_Cuts)
        sh.SetWidth(10000)
        board.Add(sh)

    # 网络：RF1（主线）/ GND（平面+地孔）
    net_rf = pcbnew.NETINFO_ITEM(board, "RF1"); board.Add(net_rf)
    net_gnd = pcbnew.NETINFO_ITEM(board, "GND"); board.Add(net_gnd)

    # CPWG 主线（F.Cu）
    ty = int({ty_mm} * 1e6)
    tx0 = int({tx0_mm} * 1e6); tx1 = int({tx1_mm} * 1e6)
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(pcbnew.VECTOR2I(tx0, ty))
    tr.SetEnd(pcbnew.VECTOR2I(tx1, ty))
    tr.SetWidth(int({w_mm} * 1e6))
    tr.SetLayer(pcbnew.F_Cu)
    tr.SetNetCode(net_rf.GetNetCode())
    board.Add(tr)

    # GND 平面（F.Cu 缝隙=clearance 口径 + B.Cu 实平面）+ 地过孔
    def make_zone(layer):
        z = pcbnew.ZONE(board)
        # 轮廓一律经官方 ZONE::AppendCorner(pt, aHoleIdx=-1) 写进 zone
        # 自有的 m_Poly（首点自动 NewOutline）。禁止 SetOutline(Python 建的
        # SHAPE_POLY_SET)：C++ 侧 `SetOutline(p){ m_Poly = p; }` 裸指针接管、
        # `~ZONE(){ delete m_Poly; }`，而 SWIG 包装对象 thisown=1，函数返回即
        # 被 Python 释放 → SaveBoard 序列化 zone 轮廓读悬空指针（#210 ③
        # "间歇 0xC0000005 @ pcbnew.py SaveBoard" 的真根因，是否触雷取决于
        # 堆复用，故随环境漂移、全量下重试也会耗尽）。
        for gx, gy in [({bx0_mm} - 2, {by0_mm} - 2), ({bx1_mm} + 2, {by0_mm} - 2),
                       ({bx1_mm} + 2, {by1_mm} + 2), ({bx0_mm} - 2, {by1_mm} + 2)]:
            z.AppendCorner(pcbnew.VECTOR2I(int(gx * 1e6), int(gy * 1e6)), -1)
        z.SetLayer(layer)
        z.SetNetCode(net_gnd.GetNetCode())
        z.SetLocalClearance(int({gap_mm} * 1e6))
        z.SetMinThickness(100000)
        board.Add(z)
        return z

    zones = [make_zone(pcbnew.F_Cu), make_zone(pcbnew.B_Cu)]
    for vx in [{via_xs}]:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(int(vx * 1e6),
                                        int({via_y_mm} * 1e6)))
        via.SetDrill(int({drill_mm} * 1e6))
        via.SetWidth(int({pad_mm} * 1e6))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNetCode(net_gnd.GetNetCode())
        board.Add(via)

    # 端射焊盘（footprint X1，B6 stage-2 pad 提取往返锚；w×h 不等抓轴
    # 交换。层集 LSET()+AddLayer——10.0.6 无 LAYER_RANGE 绑定、
    # LSET(单id) 构造重载不收 Python int）。
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference("X1")
    fp.SetValue("CPWG_LAUNCH")
    fp.SetPosition(pcbnew.VECTOR2I(int({tx0_mm} * 1e6),
                                   int({ty_mm} * 1e6)))
    board.Add(fp)
    f_cu_only = pcbnew.LSET()
    f_cu_only.AddLayer(pcbnew.F_Cu)
    for pi, px in enumerate([{tx0_mm}, {tx1_mm}]):
        pd = pcbnew.PAD(fp)
        pd.SetNumber(str(pi + 1))
        # 默认属性是 PTH（铜层=全铜层）；SMD 才能钉住单面 F.Cu。
        pd.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pd.SetShape(pcbnew.PAD_SHAPE_RECT)
        pd.SetSize(pcbnew.VECTOR2I(int({pad_w_mm} * 1e6),
                                   int({pad_h_mm} * 1e6)))
        pd.SetPosition(pcbnew.VECTOR2I(int(px * 1e6),
                                       int({ty_mm} * 1e6)))
        pd.SetLayerSet(f_cu_only)
        pd.SetNetCode(net_rf.GetNetCode())
        fp.Add(pd)

    # KiCad 10.0.6 实测：ZONE_FILLER 即使 Save→Load 后仍间歇段错误
    # （0xC0000005，约 1/3 概率，子进程整体带走 JSON 输出）。fill 纹理
    # 对提取往返（读 track/via/outline）与 EM 锚（走 cpw 模板解析地）
    # 均非必需——移出关键路径：只保存带 zone 轮廓的板；要"真铜"演示
    # 板可在 KiCad GUI 手动填充（B6 stage-1 冒烟判据不依赖 fill）。
    if not pcbnew.SaveBoard(r"{output_path}", board):
        errors.append("SaveBoard 失败")
        return False
    return True

try:
    out["ok"] = bool(build())
except Exception as exc:  # noqa: BLE001 —— 统一转契约失败
    errors.append("{}: {}".format(type(exc).__name__, exc))

print("{json_start}")
print(json.dumps(out, ensure_ascii=False))
print("{json_end}")
'''


def _inject_demo_stackup(pcb_path: Path) -> None:
    """给 demo 板写入 rogers4350b 叠层。

    KiCad 10 绑定无 BOARD_STACKUP wrapper，文本注入是可靠路径；KiCad
    LoadBoard 实测接受，重载时按叠层和重算 (general) thickness。
    """
    text = pcb_path.read_text(encoding="utf-8")
    if "(stackup" in text:
        return
    cu = DEMO_COPPER_THICK_MM
    stackup = (
        "\t\t(stackup\n"
        "\t\t\t(layer \"F.SilkS\" (type \"Top Silk\"))\n"
        f"\t\t\t(layer \"F.Cu\" (type \"copper\") (thickness {cu}))\n"
        "\t\t\t(layer \"dielectric 1\" (type \"core\") "
        f"(thickness {DEMO_CORE_THICK_MM}) (epsilon_r {DEMO_ER}) "
        f"(loss_tangent {DEMO_TAN_D}))\n"
        f"\t\t\t(layer \"B.Cu\" (type \"copper\") (thickness {cu}))\n"
        "\t\t\t(copper_finish \"None\")\n"
        "\t\t\t(dielectric_constraints no)\n"
        "\t\t)\n"
    )
    marker = "\t(setup\n"
    if marker not in text:
        raise ValueError(f"{pcb_path}: 无 (setup 节，无法注入 stackup")
    text = text.replace(marker, marker + stackup, 1)
    pcb_path.write_text(text, encoding="utf-8")


def build_demo_cpwg_pcb(
    output_path: str | Path,
    w_mm: float = DEMO_W_MM,
    gap_mm: float = DEMO_GAP_MM,
    line_len_mm: float = DEMO_LINE_LEN_MM,
    kicad_python: str | None = None,
    fill_zones: bool = False,
) -> dict[str, Any]:
    """生成 CPWG demo 板（B6 往返锚输入）。

    双层板 60×30mm，F.Cu 主线 net=RF1（w×L，起点 (10,15)），F.Cu GND
    平面（缝宽=clearance gap_mm，CPWG 口径）+ B.Cu GND 实平面 + 4 颗
    地过孔（drill 0.3/pad 0.6，y=18 一行）+ 端射焊盘 footprint X1
    （2 颗 RECT pad_w×pad_h @ 线两端，net RF1，仅 F.Cu），叠层
    rogers4350b：铜 0.035/芯板 0.508 er=3.66 tanδ=0.0037/铜 0.035
    （总厚 0.578）。参数与 openems_templates TEMPLATE_NOMINAL["cpw"]
    名义一致。

    fill_zones=True 时追加 opt-in fill 腿（B6 stage-2 填充纹理提取链的
    真填充板来源）：独立子进程 ZONE_FILLER(board).Fill(zones, False)
    （#214 两参铁律；与建板进程隔离——同会话建板+Fill 曾间歇段错误，
    #210 家族）。填充失败 → success=False 如实上报（板文件为未填充
    半成品）。默认 False 保持历史口径（未填充板）。

    返回 {"success": bool, "output_path": str|None, "message": str,
          "errors": [...], "filled": bool}。
    """
    out_path = Path(output_path)
    python_exe = kicad_python or KICAD_PYTHON
    if not Path(python_exe).exists():
        return {"success": False, "output_path": None,
                "message": f"KiCad Python 不存在: {python_exe}",
                "errors": [], "filled": False}

    tx0, ty = DEMO_TRACE_ORIGIN_MM
    thickness_nm = round(
        (DEMO_CORE_THICK_MM + 2 * DEMO_COPPER_THICK_MM) * _NM_PER_MM)
    script = (
        _BUILD_SCRIPT_TEMPLATE
        .replace("{site_packages}", KICAD_SITE_PACKAGES)
        .replace("{json_start}", _JSON_START)
        .replace("{json_end}", _JSON_END)
        .replace("{thickness_nm}", str(thickness_nm))
        .replace("{bx0_mm}", repr(0.0))
        .replace("{by0_mm}", repr(0.0))
        .replace("{bx1_mm}", repr(DEMO_BOARD_MM[0]))
        .replace("{by1_mm}", repr(DEMO_BOARD_MM[1]))
        .replace("{tx0_mm}", repr(tx0))
        .replace("{tx1_mm}", repr(tx0 + line_len_mm))
        .replace("{ty_mm}", repr(ty))
        .replace("{w_mm}", repr(w_mm))
        .replace("{gap_mm}", repr(gap_mm))
        .replace("{via_xs}", ", ".join(repr(x) for x in DEMO_VIA_XS_MM))
        .replace("{via_y_mm}", repr(DEMO_VIA_Y_MM))
        .replace("{drill_mm}", repr(DEMO_VIA_DRILL_MM))
        .replace("{pad_mm}", repr(DEMO_VIA_PAD_MM))
        .replace("{pad_w_mm}", repr(DEMO_PAD_W_MM))
        .replace("{pad_h_mm}", repr(DEMO_PAD_H_MM))
        .replace("{output_path}", str(out_path))
    )
    # 历史"SaveBoard 间歇访问违例（0xC0000005，faulthandler 钉在序列化
    # zone）"的根因是 make_zone 里 SetOutline 接管了 Python 持有的
    # SHAPE_POLY_SET（悬空指针，见脚本内注释），已改走 AppendCorner 根治。
    # 子进程级重试保留为兜底（#191 重试哲学）：原生崩溃无法进程内捕获。
    result, errors, fatal = _run_kicad_with_retry(script, python_exe)
    if fatal == "spawn":
        return {"success": False, "output_path": None,
                "message": "KiCad 子进程启动失败", "errors": errors,
                "filled": False}
    if fatal == "timeout":
        return {"success": False, "output_path": None,
                "message": "demo 板生成超时", "errors": errors,
                "filled": False}
    try:
        raw = _parse_stdout_json(result.stdout or "") if result else None
    except json.JSONDecodeError:
        raw = None
    except Exception as exc:
        return {"success": False, "output_path": None,
                "message": f"{type(exc).__name__}: {exc}", "errors": [],
                "filled": False}

    if raw is None:
        errors.append((result.stdout or "")[-300:] or "无产物输出")
        if result.stderr:
            errors.append(result.stderr[-500:])
        ok = False
    else:
        ok = bool(raw.get("ok"))
        errors.extend(raw.get("errors") or [])
    if result.returncode != 0:
        ok = False
        errors.append(
            f"KiCad 退出码 {result.returncode}: {(result.stderr or '')[-300:]}")
    filled = False
    fill_failed = False
    if ok and out_path.exists() and fill_zones:
        filled, fill_errors = _fill_demo_zones(out_path, python_exe)
        errors.extend(fill_errors)
        fill_failed = not filled
        ok = filled  # 要了填充但没填上 = 半成品，如实失败
    if ok and out_path.exists():
        _inject_demo_stackup(out_path)
    success = ok and out_path.exists()
    if success:
        message = "demo 板生成成功" + ("（含 zone 填充）" if fill_zones else "")
    elif fill_failed:
        message = "demo 板 zone 填充失败（板文件为未填充半成品）"
    else:
        message = "demo 板生成失败"
    return {
        "success": success,
        "output_path": str(out_path) if success else None,
        "message": message,
        "errors": errors,
        "filled": filled and success,
    }
