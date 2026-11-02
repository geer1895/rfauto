"""KiCad 电源对自动提取（B5-5，pdn P3 登记件的独立批；纯文本 s-expression 解析侧）。

语义（以 pdn_service 既有数据模型为准定义，任务书"范围宁小勿大"）：

- **「电源对」= (电源网络, 地网络) 平面偶**。pdn 面的两个消费点：
  1. *平面腔体 span*：同铜层上电源网 zone 与地网 zone 的 bbox 正面积重叠
     区（矩形腔近似）→ :func:`rfauto.core.pdn.plane_cavity_modes` 的
     (a_m, b_m) 输入（pdn_analyze/pdn_gate 的 ``plane`` 参数候选）；
  2. *过孔对间距*：每颗电源网过孔的最近地网过孔 →
     :func:`rfauto.core.pdn.mount_inductance` 的 ``via_pair_spacing_m``
     输入（DecapSpec.mount_l_h 估计链）。
- 铁律 7：本模块零物理数字——全部几何量出自板文件文本；网分类默认启发式
  只做"名字→类别"判定（不产生电气数值），调用方可显式覆盖（power_nets/
  ground_nets 给出时**替换**启发式）。
- 实现路线：.kicad_pcb 是 s-expression 文本，过孔/zone/网络名全部可文本
  解析——**不走 pcbnew 子进程**（绕开 KiCad Python 3.11 ABI 面与 SWIG 坑
  族 #210/#214/#220；层身份用层名字符串，天然规避层 id 重排）。全离线，
  单测零 KiCad 安装依赖。v1 已知简化（如实声明）：zone 轮廓 bbox 近似
  （不做多边形精确交）、bbox 交集不判 L 形分割平面、zone 弧段轮廓（arc
  primitive）不含 xy 点会被跳过并告警。

net 字段双格式兼容：KiCad ≤7 旧式 ``(net 2 "+3V3")``（顶层 ``(net 2
"+3V3")`` 声明表 + 条目 ``（net 2）`` 查表）与 KiCad 10 新式条目内联
``(net "GND")``（实测 runs/kicad_b6_stage2 demo 板与 parts/test_minimal）
均支持；zone 另有 ``(net_name "...")`` 优先。

JSON 信封（service :func:`rfauto.service.pdn_service.pdn_power_pairs` 薄壳
转发）：成功 ``{"ok": True, "nets", "counts", "plane_pairs",
"via_pairs", "via_pair_stats", "pdn_plane_inputs", "warnings", ...}``；
失败 ``{"ok": False, "errors": [...]}``。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: 过孔对明细列表缺省上限（统计量照常对全部对计算，列表截断并告警）
VIA_PAIR_LIST_DEFAULT = 200

#: 最近邻配对暴力法操作量上限（power×ground；超过则跳过配对并如实告警，
#: 不静默 O(n²) 拖死大板）
_VIA_PAIRING_OP_CAP = 4_000_000

#: 电源网启发式前缀（KiCad 电源符号惯例：+3V3/+5V 以 "+" 开头；VCC/VDD 族）
_POWER_PREFIXES = ("+", "VCC", "VDD", "VBAT", "VIN", "VBUS", "VSYS", "VRAIL")
#: 地网启发式（GND 子串含 AGND/DGND/PGND/GNDA；VSS 族是地）
_GROUND_SUBSTR = "GND"
_GROUND_PREFIXES = ("VSS",)

_EPSILON_R_RE = re.compile(r"\(epsilon_r\s+([0-9.eE+-]+)\s*\)")


# ─── s-expression 解析（文本面唯一入口，无 pcbnew） ─────────────────────────


def parse_sexp(text: str) -> list[Any]:
    """解析 s-expression 文本为嵌套列表（字符串与原子均收敛为 str）。

    引号串支持反斜杠转义（``\\"``/``\\\\`` 等：转义符取下一字符字面量）。
    括号不配平/字符串未闭合 → ValueError（调用侧转 ok=False 信封）。
    """
    stack: list[list[Any]] = [[]]
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            node: list[Any] = []
            stack[-1].append(node)
            stack.append(node)
            i += 1
        elif ch == ")":
            if len(stack) == 1:
                raise ValueError("s-expression 括号不配平：多余的右括号")
            stack.pop()
            i += 1
        elif ch == '"':
            i += 1
            buf: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                buf.append(text[i])
                i += 1
            if i >= n:
                raise ValueError("s-expression 字符串字面量未闭合")
            i += 1
            stack[-1].append("".join(buf))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if len(stack) != 1:
        raise ValueError("s-expression 括号不配平：括号未闭合")
    return stack[0]


def _first(node: list[Any], tag: str) -> list[Any] | None:
    """node 直接子节点里第一个 (tag ...) 列表；无则 None。"""
    for child in node:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _strings(node: list[Any]) -> list[str]:
    """字符串子元素（**跳过 node[0] 标签**：`(net "GND")` → ["GND"]）。"""
    return [c for c in node[1:] if isinstance(c, str)]


def _is_number(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _names(node: list[Any]) -> list[str]:
    """非数字字符串子元素（跳过标签；`(net 1 "GND")` → ["GND"]）。"""
    return [s for s in _strings(node) if not _is_number(s)]


def _numbers(node: list[Any]) -> list[float]:
    """数值子元素（跳过标签；`(at 15 12.5)` → [15.0, 12.5]）。"""
    out: list[float] = []
    for c in _strings(node):
        try:
            out.append(float(c))
        except ValueError:
            continue
    return out


def _iter_nodes(node: Any, tag: str) -> Iterator[list[Any]]:
    """深度优先枚举全部 (tag ...) 子节点（zone/via 可在 footprint/group 内）。"""
    if not isinstance(node, list):
        return
    for child in node:
        if isinstance(child, list) and child:
            if child[0] == tag:
                yield child
            yield from _iter_nodes(child, tag)


def _net_declarations(root: list[Any]) -> dict[int, str]:
    """顶层 (net <code> "<name>") 声明表（旧式格式）；code→name。"""
    out: dict[int, str] = {}
    for child in root:
        if not (isinstance(child, list) and child and child[0] == "net"):
            continue
        nums = _numbers(child)
        names = _names(child)
        if nums and names:
            out[int(nums[0])] = names[0]
    return out


def _resolve_net(item: list[Any], net_map: dict[int, str]) -> str:
    """条目级 net 解析：新式 (net "名") 内联优先，旧式 (net 码) 查声明表。"""
    net = _first(item, "net")
    if net is None:
        return ""
    inline = _names(net)
    if inline:
        return inline[0]
    nums = _numbers(net)
    if nums:
        return net_map.get(int(nums[0]), "")
    return ""


# ─── 板件抽取（via / zone → 纯 dict 中间形态，单位 mm） ──────────────────────


def _parse_vias(root: list[Any], net_map: dict[int, str]) -> list[dict[str, Any]]:
    """(via ...) 全量 → [{net, x_mm, y_mm, pad_diameter_mm, drill_mm, layers}]。

    drill 椭圆形态 (drill oval a b) 取首数值；无 size/drill 字段如实 None。
    输出按 (net, x, y) 排序保证确定性。
    """
    vias: list[dict[str, Any]] = []
    for via in _iter_nodes(root, "via"):
        at = _first(via, "at")
        nums = _numbers(at) if at is not None else []
        if len(nums) < 2:
            continue
        size = _first(via, "size")
        drill = _first(via, "drill")
        layers_node = _first(via, "layers")
        vias.append({
            "net": _resolve_net(via, net_map),
            "x_mm": nums[0],
            "y_mm": nums[1],
            "pad_diameter_mm": (_numbers(size)[0] if size is not None and _numbers(size) else None),
            "drill_mm": (_numbers(drill)[0] if drill is not None and _numbers(drill) else None),
            "layers": _strings(layers_node) if layers_node is not None else [],
        })
    vias.sort(key=lambda v: (v["net"], v["x_mm"], v["y_mm"]))
    return vias


def _parse_zones(
    root: list[Any], net_map: dict[int, str], warnings: list[str],
) -> list[dict[str, Any]]:
    """(zone ...) 全量 → [{net, layers, outline_mm, n_polygons}]。

    span 取首个 (polygon ...) 的 (xy ...) 点列 bbox（切割/挖空等多边形
    不并入——span 语义=主轮廓范围）；弧段轮廓无 xy 点 → 跳过并告警。
    """
    zones: list[dict[str, Any]] = []
    for zone in _iter_nodes(root, "zone"):
        net = _resolve_net(zone, net_map)
        net_name = _first(zone, "net_name")
        if net_name is not None:
            named = [s for s in _strings(net_name) if s]
            if named:
                net = named[0]
        layers: list[str] = []
        for tag in ("layers", "layer"):
            node = _first(zone, tag)
            if node is not None:
                layers = _strings(node)
                if layers:
                    break
        polygons = [c for c in zone if isinstance(c, list) and c and c[0] == "polygon"]
        outline: list[tuple[float, float]] = []
        if polygons:
            pts = _first(polygons[0], "pts")
            if pts is not None:
                for xy in _iter_nodes(pts, "xy"):
                    nums = _numbers(xy)
                    if len(nums) >= 2:
                        outline.append((nums[0], nums[1]))
        if not layers:
            warnings.append(f"zone(net={net or '<unnamed>'}) 无层信息，跳过平面配对")
            continue
        if len(outline) < 3:
            warnings.append(f"zone(net={net or '<unnamed>'}, layers={layers}) 轮廓点 <3（弧段/空轮廓），跳过 span 提取")
            continue
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        zones.append({
            "net": net,
            "layers": layers,
            "outline_mm": [[x, y] for x, y in outline],
            "n_polygons": len(polygons),
            "bbox": (min(xs), min(ys), max(xs), max(ys)),
        })
    zones.sort(key=lambda z: (z["net"], tuple(z["layers"]),
                              z["outline_mm"][0][0], z["outline_mm"][0][1]))
    return zones


# ─── 网分类（启发式 + 调用方覆盖；零电气数值） ───────────────────────────────


def _classify_nets(
    nets: list[str],
    power_nets: list[str] | None,
    ground_nets: list[str] | None,
) -> dict[str, list[str]]:
    """网络名 → {ground, power, unclassified}（各自按名排序保确定性）。

    覆盖语义：power_nets/ground_nets 非空列表时**替换**对应类启发式（不是
    追加）；ground 判定先于 power（同串双命中归地）。
    """
    if ground_nets:
        ground = {n for n in nets if n in set(ground_nets)}
    else:
        upper = {n: n.upper() for n in nets}
        ground = {n for n in nets
                  if _GROUND_SUBSTR in upper[n]
                  or upper[n].startswith(_GROUND_PREFIXES)}
    rest = [n for n in nets if n not in ground]
    if power_nets:
        power = {n for n in rest if n in set(power_nets)}
    else:
        power = {n for n in rest if n.upper().startswith(_POWER_PREFIXES)}
    unclassified = [n for n in rest if n not in power]
    return {
        "ground": sorted(ground),
        "power": sorted(power),
        "unclassified": sorted(unclassified),
    }


# ─── 配对（平面偶 span / 过孔对间距） ────────────────────────────────────────


def _bbox_intersection(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    """bbox 交集（正面积才返回；仅贴边=零面积 → None）。"""
    left = max(a[0], b[0])
    bottom = max(a[1], b[1])
    right = min(a[2], b[2])
    top = min(a[3], b[3])
    if right <= left or top <= bottom:
        return None
    return (left, bottom, right, top)


def _pair_plane_zones(
    zones: list[dict[str, Any]],
    power: set[str],
    ground: set[str],
) -> list[dict[str, Any]]:
    """同层电源/地 zone 对 → 平面偶 span 清单（bbox 交集，按面积降序）。"""
    p_zones = [z for z in zones if z["net"] in power]
    g_zones = [z for z in zones if z["net"] in ground]
    pairs: list[dict[str, Any]] = []
    for pz in p_zones:
        for gz in g_zones:
            shared = sorted(set(pz["layers"]) & set(gz["layers"]))
            for layer in shared:
                inter = _bbox_intersection(pz["bbox"], gz["bbox"])
                if inter is None:
                    continue
                left, bottom, right, top = inter
                a_mm = right - left
                b_mm = top - bottom
                pairs.append({
                    "pair_key": f"{pz['net']}__{gz['net']}",
                    "power_net": pz["net"],
                    "ground_net": gz["net"],
                    "layer": layer,
                    "a_mm": a_mm,
                    "b_mm": b_mm,
                    "overlap_area_mm2": a_mm * b_mm,
                    "source": "zone_bbox_intersection",
                    "n_power_zone_polygons": pz["n_polygons"],
                    "n_ground_zone_polygons": gz["n_polygons"],
                })
    pairs.sort(key=lambda p: (p["power_net"], p["ground_net"], p["layer"],
                              -p["overlap_area_mm2"]))
    return pairs


def _pair_vias(
    power_vias: list[dict[str, Any]],
    ground_vias: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """每颗电源过孔的最近地过孔 → 过孔对清单（spacing=对心距，mm 升序）。"""
    def dist(p: dict[str, Any], q: dict[str, Any]) -> float:
        return math.hypot(p["x_mm"] - q["x_mm"], p["y_mm"] - q["y_mm"])

    pairs: list[dict[str, Any]] = []
    for pv in power_vias:
        if not ground_vias:
            break
        gv = min(ground_vias, key=lambda g: dist(pv, g))
        pairs.append({
            "pair_key": f"{pv['net']}__{gv['net']}",
            "power_net": pv["net"],
            "ground_net": gv["net"],
            "spacing_mm": dist(pv, gv),
            "power_via": {k: pv[k] for k in ("x_mm", "y_mm", "layers", "pad_diameter_mm", "drill_mm")},
            "ground_via": {k: gv[k] for k in ("x_mm", "y_mm", "layers", "pad_diameter_mm", "drill_mm")},
        })
    pairs.sort(key=lambda p: (p["spacing_mm"], p["power_via"]["x_mm"],
                              p["power_via"]["y_mm"]))
    return pairs


def _spacing_stats(spacings: list[float]) -> dict[str, float | int] | None:
    """spacing 统计（min/median/max；空表 None）。"""
    if not spacings:
        return None
    xs = sorted(spacings)
    mid = len(xs) // 2
    median = xs[mid] if len(xs) % 2 else 0.5 * (xs[mid - 1] + xs[mid])
    return {"min": xs[0], "median": median, "max": xs[-1], "n": len(xs)}


# ─── 去耦电容簇（B5-5 剩余件：跨电源/地两网的最小封装识别） ──────────────────


def _parse_footprints(
    root: list[Any], net_map: dict[int, str],
) -> list[dict[str, Any]]:
    """(footprint ...) 全量 → 位置+焊盘网归属的最小中间形态。

    - 位置取 footprint 级 ``(at x y)``（焊盘相对位/旋转不展开——簇质心
      语义用封装中心已足够，最小实现不做几何展开）；
    - Reference/Value 取 ``(property "Reference"/"Value" ...)`` 文本
      （KiCad 6+），旧式 ``(module ...)`` 回退 ``(fp_text reference/value
      "..." ...)``，缺失如实空串；
    - 焊盘网走 :func:`_resolve_net` 同源双格式（新式内联名 / 旧式码查表）。
    输出按 (reference, x, y) 排序保证确定性。
    """
    out: list[dict[str, Any]] = []
    for tag in ("footprint", "module"):
        for fp in _iter_nodes(root, tag):
            at = _first(fp, "at")
            nums = _numbers(at) if at is not None else []
            props: dict[str, str] = {}
            for prop in _iter_nodes(fp, "property"):
                names = _strings(prop)
                if len(names) >= 2:
                    props[names[0]] = names[1]
            for role in ("reference", "value"):
                if role in props:
                    continue
                for ft in _iter_nodes(fp, "fp_text"):
                    ft_names = _strings(ft)
                    if ft_names and ft_names[0] == role and len(ft_names) >= 2:
                        props[role] = ft_names[1]
                        break
            pads: list[dict[str, Any]] = []
            for pad in _iter_nodes(fp, "pad"):
                numbers = _strings(pad)
                if not numbers:
                    continue
                pads.append({"number": numbers[0], "net": _resolve_net(pad, net_map)})
            fp_name = ""
            atoms = [c for c in fp if isinstance(c, str)]
            if len(atoms) >= 2:
                fp_name = atoms[1]
            out.append({
                "footprint": fp_name,
                "reference": props.get("Reference", props.get("reference", "")),
                "value": props.get("Value", props.get("value", "")),
                "x_mm": nums[0] if len(nums) >= 2 else 0.0,
                "y_mm": nums[1] if len(nums) >= 2 else 0.0,
                "pads": pads,
            })
    out.sort(key=lambda f: (f["reference"], f["x_mm"], f["y_mm"]))
    return out


def _cluster_decaps(
    footprints: list[dict[str, Any]],
    power: set[str],
    ground: set[str],
) -> list[dict[str, Any]]:
    """去耦电容簇：焊盘同时桥接电源网与地网的封装，按 (电源网, 地网) 聚簇。

    判据是电气桥接（≥1 焊盘在电源网且 ≥1 焊盘在地网），不按封装名/值
    猜器件类型——名称只作 ``footprint``/``value`` 字段如实随行。多电源
    焊盘的封装对每个 (电源, 地) 组合各计入一次（如实反映多轨桥接）。
    簇内按 reference 排序，簇间按 pair_key 排序，位置取封装中心。
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fp in footprints:
        pad_nets = {p["net"] for p in fp["pads"] if p["net"]}
        p_hits = pad_nets & power
        g_hits = pad_nets & ground
        if not p_hits or not g_hits:
            continue
        entry = {
            "reference": fp["reference"],
            "footprint": fp["footprint"],
            "value": fp["value"],
            "x_mm": fp["x_mm"],
            "y_mm": fp["y_mm"],
        }
        for pn in sorted(p_hits):
            for gn in sorted(g_hits):
                buckets.setdefault((pn, gn), []).append(entry)
    clusters: list[dict[str, Any]] = []
    for (pn, gn), members in sorted(buckets.items()):
        members = sorted(members, key=lambda m: (m["reference"], m["x_mm"], m["y_mm"]))
        clusters.append({
            "pair_key": f"{pn}__{gn}",
            "power_net": pn,
            "ground_net": gn,
            "n_decaps": len(members),
            "centroid_mm": [
                sum(m["x_mm"] for m in members) / len(members),
                sum(m["y_mm"] for m in members) / len(members),
            ],
            "refs": [m["reference"] for m in members],
            "decaps": members,
        })
    return clusters


def _stackup_er(pcb_text: str) -> float | None:
    """(stackup ...) 节首条 dielectric 的 epsilon_r（同 kicad_extract 家法）。

    无 stackup 节/未存 epsilon_r → None（er 由调用方补，pdn plane.er 必填）。
    """
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
                block = pcb_text[start:i + 1]
                chunks = re.split(r'\(layer\s+"', block)[1:]
                for chunk in chunks:
                    name = chunk.split('"', 1)[0] if '"' in chunk else ""
                    if "dielectric" not in name.lower():
                        continue
                    m = _EPSILON_R_RE.search(chunk)
                    if m:
                        return float(m.group(1))
                return None
    return None


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def extract_power_pairs(
    pcb_path: str | Path,
    power_nets: list[str] | None = None,
    ground_nets: list[str] | None = None,
    max_via_pairs: int | None = None,
) -> dict[str, Any]:
    """从 .kicad_pcb 文本提取电源对（平面偶 span + 过孔对间距），JSON 信封。

    Args:
        pcb_path: .kicad_pcb 文件路径（纯文本解析，不依赖 KiCad 安装）。
        power_nets: 电源网显式名单（给出时替换 "+" /VCC 族启发式）。
        ground_nets: 地网显式名单（给出时替换 GND/VSS 族启发式）。
        max_via_pairs: 过孔对明细列表上限（统计量恒对全部对计算；None=缺省
            :data:`VIA_PAIR_LIST_DEFAULT`）。

    Returns:
        dict: 成功 ``{"ok": True, "pcb_path", "board", "nets", "counts",
        "plane_pairs", "via_pairs", "via_pair_stats", "via_pair_note",
        "decap_clusters", "pdn_plane_inputs", "warnings"}``；文件不存在/
        文本解析失败/实参非法 ``{"ok": False, "errors": [...]}``。
        ``decap_clusters``：焊盘同时桥接电源/地两网的封装（去耦电容的
        电气判据，不按封装名猜器件类型）按 (电源网, 地网) 聚簇——
        簇含 refs/质心/逐颗位置，供安装电感与分布评估的输入面。
        ``pdn_plane_inputs`` 每 (电源网, 地网) 取重叠面积最大的平面偶，
        换算米制并附 stackup er（缺失为 None+告警）——可直接作为
        pdn_analyze/pdn_gate ``plane`` 参数候选。
    """
    path = Path(pcb_path)
    warnings: list[str] = []
    if not path.exists():
        return {"ok": False, "pcb_path": str(path),
                "errors": [f"PCB 文件不存在: {path}"]}
    if max_via_pairs is None:
        max_via_pairs = VIA_PAIR_LIST_DEFAULT
    if not isinstance(max_via_pairs, int) or isinstance(max_via_pairs, bool) or max_via_pairs < 1:
        return {"ok": False, "pcb_path": str(path),
                "errors": [f"max_via_pairs 必须为正整数，实际 {max_via_pairs!r}"]}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        root = parse_sexp(text)
    except (OSError, ValueError) as exc:
        return {"ok": False, "pcb_path": str(path),
                "errors": [f".kicad_pcb 文本读取/解析失败: {exc}"]}
    # parse_sexp 返回最外层包装列表；良构板文件顶层恰一个 (kicad_pcb ...) 节点
    board = root[0] if len(root) == 1 and isinstance(root[0], list) and root[0] else root

    net_map = _net_declarations(board)
    vias = _parse_vias(board, net_map)
    zones = _parse_zones(board, net_map, warnings)
    footprints = _parse_footprints(board, net_map)

    named_nets = sorted({v["net"] for v in vias if v["net"]}
                        | {z["net"] for z in zones if z["net"]}
                        | {p["net"] for f in footprints for p in f["pads"]
                           if p["net"]})
    classification = _classify_nets(named_nets, power_nets, ground_nets)
    power = set(classification["power"])
    ground = set(classification["ground"])

    plane_pairs = _pair_plane_zones(zones, power, ground)
    decap_clusters = _cluster_decaps(footprints, power, ground)

    power_via_list = [v for v in vias if v["net"] in power]
    ground_via_list = [v for v in vias if v["net"] in ground]
    via_pair_note = "ok"
    if power_via_list and ground_via_list:
        if len(power_via_list) * len(ground_via_list) > _VIA_PAIRING_OP_CAP:
            via_pair_note = "skipped_op_cap"
            warnings.append(
                f"过孔对配对跳过：电源过孔 {len(power_via_list)} × 地过孔 "
                f"{len(ground_via_list)} 超操作量上限 {_VIA_PAIRING_OP_CAP}（不静默拖死大板）")
            raw_via_pairs = []
        else:
            raw_via_pairs = _pair_vias(power_via_list, ground_via_list)
    else:
        via_pair_note = "no_power_or_ground_vias"
        if not power_via_list:
            warnings.append("无电源网过孔，过孔对配对为空（检查网分类或板面）")
        if not ground_via_list:
            warnings.append("无地网过孔，过孔对配对为空（检查网分类或板面）")
        raw_via_pairs = []

    all_spacings = [p["spacing_mm"] for p in raw_via_pairs]
    by_pair: dict[str, list[float]] = {}
    for p in raw_via_pairs:
        by_pair.setdefault(p["pair_key"], []).append(p["spacing_mm"])
    via_pair_stats = {
        "overall": _spacing_stats(all_spacings),
        "by_pair": {k: _spacing_stats(v) for k, v in sorted(by_pair.items())},
    }
    via_pairs_out = raw_via_pairs[:max_via_pairs]
    if len(raw_via_pairs) > max_via_pairs:
        warnings.append(
            f"过孔对明细截断：全部 {len(raw_via_pairs)} 对只列前 {max_via_pairs} 对"
            f"（按 spacing 升序；统计量仍是全量的）")

    # pdn plane 参数候选：每 (电源网, 地网) 取重叠面积最大平面偶（跨层）。
    er = _stackup_er(text)
    if er is None:
        warnings.append("stackup 未见 dielectric epsilon_r：pdn_plane_inputs.er=None"
                        "（pdn plane.er 必填，调用方需补叠层值）")
    best: dict[str, dict[str, Any]] = {}
    n_candidates: dict[str, int] = {}
    for p in plane_pairs:
        key = p["pair_key"]
        n_candidates[key] = n_candidates.get(key, 0) + 1
        if key not in best or p["overlap_area_mm2"] > best[key]["overlap_area_mm2"]:
            best[key] = p
    pdn_plane_inputs = []
    for key, p in sorted(best.items()):
        pdn_plane_inputs.append({
            "pair_key": key,
            "power_net": p["power_net"],
            "ground_net": p["ground_net"],
            "layer": p["layer"],
            "a_m": p["a_mm"] / 1000.0,
            "b_m": p["b_mm"] / 1000.0,
            "er": er,
            "n_candidate_plane_pairs": n_candidates[key],
            "note": ("zone bbox 交集近似（矩形腔近似，#F-B 风险③：非矩形/分割平面"
                     "由上层标 unsupported）；er 取 stackup 首条 dielectric"),
        })

    version_node = _first(board, "version")
    version_vals = _numbers(version_node) if version_node is not None else []
    return {
        "ok": True,
        "pcb_path": str(path),
        "board": {
            "version": (version_vals[0] if version_vals else None),
            "net_count": len(net_map) or len(named_nets),
        },
        "nets": classification,
        "counts": {
            "vias_total": len(vias),
            "power_vias": len(power_via_list),
            "ground_vias": len(ground_via_list),
            "zones_total": len(zones),
            "power_zones": len([z for z in zones if z["net"] in power]),
            "ground_zones": len([z for z in zones if z["net"] in ground]),
            "footprints_total": len(footprints),
            "decaps_total": sum(c["n_decaps"] for c in decap_clusters),
            "decap_clusters": len(decap_clusters),
        },
        "plane_pairs": plane_pairs,
        "via_pairs": via_pairs_out,
        "via_pair_stats": via_pair_stats,
        "via_pair_note": via_pair_note,
        "decap_clusters": decap_clusters,
        "pdn_plane_inputs": pdn_plane_inputs,
        "warnings": warnings,
    }
