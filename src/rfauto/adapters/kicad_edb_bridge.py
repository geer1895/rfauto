"""KiCad 提取产物 → EDB 分层版图 spec 桥接（先进封装 SI/PI 方向种子件，spike）。

== 设计说明（spike 半数价值在此）=========================================

**现状**。KiCad 侧已有 pcbnew 直读提取器 ``kicad_extract.extract_pcb``
（B6：子进程 KiCad Python → stdout JSON 契约），产物是板级几何事实源：
铜层名序、板总厚、(stackup) 介质节、聚合走线折线、过孔、zone、
footprint 焊盘、板框，全部 mm。EM 求解侧已有 openEMS/HFSS/ADS 等适配器，
但尚无 EDB（HFSS 3D Layout / SIwave 原生版图数据库）接入。先进封装
（封装基板 / RDL / 过孔阵列）在 EDB 里的本质表达就是"分层叠层 +
中心线走线 + 焊盘 + 过孔"的分层版图，与 KiCad 板级提取产物同构——
本模块是二者的最小可行桥：**纯函数、零 pyedb 依赖、spec dict 即终点**；
pyedb 落库由消费方 ``edb_adapter``（并行席次另行落地）承担。本模块
不 import pcbnew/pyedb，属 adapters 层纯数据变换，离线可测。

**EDB spec 输出契约（edb_adapter 的消费面）**::

    {
      "ok": True, "bridge": ..., "units": "mm", "stackup_policy": "auto",
      "stackup": {
        "order": "bottom_to_top",     # EDB/pyedb 惯例：index 0 = 底层
        "layers": [
          {"name": "B.Cu", "type": "copper", "thickness_mm": None,
           "material": "copper"},
          {"name": "dielectric 1", "type": "dielectric",
           "thickness_mm": 0.508, "material": None, "er": 3.66,
           "tan_d": 0.0037},
          {"name": "F.Cu", "type": "copper", ...},
        ],
        "copper_layer_count", "total_thickness_mm", "substrate_er",
        "dielectric_source": "kicad_stackup" | "placeholder_unresolved",
        "copper_thickness_source": "unresolved_kicad_extract_contract",
        "kicad_to_edb_layers": {"F.Cu": "F.Cu", ...},  # auto=同名直通
      },
      "traces": [{"name", "net", "layer", "width_mm", "points_mm"}],
      "vias":   [{"name", "net", "x_mm", "y_mm", "pad_diameter_mm",
                  "drill_mm", "start_layer", "stop_layer"}],
      "pads":   [{"name", "reference", "number", "net", "layers",
                  "x_mm", "y_mm", "w_mm", "h_mm", "shape_code", "shape"}],
      "outline": {...extract 直通...},
      "warnings": [...], "counts": {...}, "errors": [],
    }

**映射规则表**（stackup_policy="auto"，按层序号）：

- ``board.copper_layers``（KiCad 层 id 升序 = 物理顶→底）→
  ``stackup.layers`` 反转排列成 bottom→top（EDB/pyedb 栈序惯例）；
  层名同名直通（EDB 层名为任意字符串，保留 KiCad 名即溯源），
  ``kicad_to_edb_layers`` 显式记录映射表。
- ``board.stackup.dielectrics``（文件序顶→底）→ 相邻铜层之间的
  dielectric 层；恰 N-1 条（N=铜层数）时按序插入；数目失配 →
  ``unresolved_dielectric_k`` 占位（厚度/er/tan_d 全 None）+ warning，
  不按板总厚均摊编造。
- ``traces[i]``（net/layer/width_mm/points_mm 折线中心线）→
  ``traces[i]`` 数值恒等直传；layer 不在 copper_layers 名单 → 跳过 +
  warning。
- ``vias[i]``（extract 契约无 layer pair 字段）→ 几何恒等直传；
  铜层数==2 时 start/stop_layer 可确证为 F.Cu/B.Cu（KiCad via 必有
  层对、两层板唯一可能）；否则 None + 一次性 warning。
- ``footprints[].pads[]`` → 每 pad 一条；layers 与铜层名单取交集，
  交集空 → 跳过 + warning、部分映射 → 保留已映射层 + warning；
  shape 为 KiCad pad_shapes.h 整数码直传 + 已知码名对照（未知码 None）。
- ``outline`` → 直通（EDB 版图外框参考）；缺失/非 dict → warning。
- ``zones`` → spike 暂不映射（平面原语列路标）；产物含非空 zones 时
  如实 warning 计数，绝不静默丢弃。

**warnings 语义**：元素级跳过（未知层/坏几何/焊盘层集不交）与结构
失配（介质数目、via 层对不可确证、产物缺键）如实入列；契约级已知
空缺（铜层厚度、介质材料名）以 None + ``*_source`` 元数据表达、不
入 warnings——**warnings 为空即"逐元素零跳过"**。

**单位纪律**：KiCad pcbnew 内部长度 = nm 整数（1e6 nm = 1 mm）；
``extract_pcb`` 产物侧已做 nm/1e6 无损换算（``_nm_to_mm``），故本
桥接层输入输出全部是 mm 浮点、几何数值**恒等直传（零算术）**——
不引入任何浮点误差，与输入逐点一致（1e-9 容差）。EDB spec 固定
mm（``spec["units"] == "mm"``）。

**已知限制**：
1. zone（GND 平面/填充纹理）暂不映射——SI/PI 里平面意义重大，列路标
   （extract 产物 filled_polys_mm 已备好数据面）。
2. via layer pair 不在 extract 契约，仅两层板可确证；盲埋孔信息缺失。
3. 铜层厚度 extract 契约未含（``_parse_stackup`` 只收 dielectric 节）
   → None；介质材料名/er/tan_d 缺失时 None——均不编造。
4. 弧段走线在提取层即被排除（extract 只分流 PCB_TRACK/PCB_VIA，
   PCB_ARC 类不落 segments）——桥接侧只见折线。
5. pad shape 已知 0..6 码对照（KiCad pad_shapes.h），未知码 None。
6. spec 不保证 EDB schema 全量（材料库/端口/net class/叠层容差等
   由消费方 edb_adapter 补齐）。

**后续路标**：
1. SIwave DC / IR drop（PI 主战场）：zones→EDB 平面原语、电压源/
   sink 语义、过孔电流路径；先补 zones 映射与盲埋孔层对。
2. HFSS 3D Layout 全波：pad→port（lumped/wave port）、padstack 精确
   化、弧段（需扩展 extract 分流 PCB_ARC）。
3. 盲埋孔：扩展 kicad_extract 输出 via 层对（PCB_VIA TopLayer/
   BottomLayer），桥接侧透传即可。
4. stackup_policy="explicit"：用户显式给 KiCad→EDB 层名/厚度/材料表
   （参数位已预留，见 ``STACKUP_POLICIES``）。
5. 先进封装细结构（RDL <10 µm 线宽/介质）：KiCad nm 整数精度无损
   （1e-6 mm）；Gerber/ODB++ 侧入口见 layout_interchange，未来对齐
   IPC-2581（KiCad 10 ODB++ 导出口径已在仓内实证）。
"""

from __future__ import annotations

import math
from typing import Any

#: 桥接标识（spec["bridge"]/["bridge_version"]，消费方版本兼容判据）
BRIDGE_NAME = "kicad_edb_bridge"
BRIDGE_VERSION = "kicad_edb_bridge/v0"

#: 叠层映射策略注册面（spike 只实现 auto="按层序号"；explicit 列路标）
STACKUP_POLICIES = ("auto",)

#: KiCad pad shape 整数码 → 名称（KiCad pad_shapes.h 口径，PAD_SHAPE_*）
_KNOWN_PAD_SHAPES: dict[int, str] = {
    0: "circle",
    1: "rectangle",
    2: "oblong",
    3: "trapezoid",
    4: "roundrect",
    5: "chamfered_rect",
    6: "custom",
}


def _num(value: Any) -> float | None:
    """数值收敛：int/float（非 bool、有限）→ float，其余一律 None。

    bool 是 int 子类、字符串数字不收——桥接层宁可 None + warning 也
    不做隐式转换编造数值。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _fail(errors: list[str]) -> dict[str, Any]:
    """失败契约（与成功契约同形：ok/errors/warnings 三键恒在）。"""
    return {"ok": False, "errors": errors, "warnings": []}


def _copper_layer(cu_name: str) -> dict[str, Any]:
    """EDB 铜层条目。厚度 None=extract 契约未含（不编造），见 docstring。"""
    return {"name": cu_name, "type": "copper", "thickness_mm": None,
            "material": "copper"}


def _dielectric_layer(d: dict[str, Any], index: int) -> dict[str, Any]:
    """EDB 介质层条目（来自 KiCad (stackup) 节解析产物）。"""
    return {
        "name": str(d.get("name") or f"dielectric {index}"),
        "type": "dielectric",
        "thickness_mm": _num(d.get("thickness_mm")),
        "material": None,
        "er": _num(d.get("er")),
        "tan_d": _num(d.get("tan_d")),
    }


def _unresolved_dielectric(index: int) -> dict[str, Any]:
    """介质占位层：KiCad 无 (stackup) 节（python 新建板）时如实表达。"""
    return {"name": f"unresolved_dielectric_{index}", "type": "dielectric",
            "thickness_mm": None, "material": None, "er": None, "tan_d": None}


def _trace_points(points_mm: Any) -> list[list[float]] | None:
    """折线点列收敛：全 [x, y] 有限数且 ≥2 点 → 点列，否则 None。"""
    if not isinstance(points_mm, list):
        return None
    pts: list[list[float]] = []
    for p in points_mm:
        px = _num(p[0]) if (isinstance(p, (list, tuple)) and len(p) == 2) else None
        py = _num(p[1]) if px is not None else None
        if px is None or py is None:
            return None
        pts.append([px, py])
    return pts if len(pts) >= 2 else None


def kicad_to_edb_spec(kicad_data: dict, stackup_policy: str = "auto") -> dict:
    """KiCad 提取产物（``extract_pcb`` 契约，mm）→ EDB 分层版图 spec dict。

    消费形态与映射规则见模块 docstring 设计说明。核心纪律：
    几何数值恒等直传（零算术）、无法映射的元素如实跳过并记
    ``warnings``、未知属性以 None 表达绝不编造；本函数是纯函数，
    不真调 pyedb——spec dict 即终点，消费方是 edb_adapter。

    Args:
        kicad_data: ``kicad_extract.extract_pcb`` 的成功契约
            （``{"ok": True, "board": ..., "traces": ..., ...}``）。
        stackup_policy: 叠层映射策略，spike 仅 "auto"（按层序号）。

    Returns:
        成功：``{"ok": True, "stackup": ..., "traces": ..., "vias": ...,
        "pads": ..., "outline": ..., "warnings": [...], "counts": ...,
        "errors": []}``；输入不可用（失败契约/缺 board/空铜层名单/非法
        策略/元素容器类型错）→ ``{"ok": False, "errors": [...],
        "warnings": []}``。
    """
    if stackup_policy not in STACKUP_POLICIES:
        return _fail([f"未知 stackup_policy: {stackup_policy!r}"
                      f"（可用: {list(STACKUP_POLICIES)}）"])
    if not isinstance(kicad_data, dict):
        return _fail(
            [f"kicad_data 非 dict（得 {type(kicad_data).__name__}）"])
    if not kicad_data.get("ok"):
        errs = kicad_data.get("errors") or ["extract 产物 ok=False（无明细）"]
        return _fail(["kicad_data 为失败契约（ok=False）"]
                     + [str(e) for e in errs])

    board = kicad_data.get("board")
    if not isinstance(board, dict):
        return _fail(["extract 产物缺 board 键或非 dict，无法构建 EDB 叠层"])
    copper_top_down = [str(x) for x in board.get("copper_layers") or []]
    if not copper_top_down:
        return _fail(["board.copper_layers 为空，无法构建 EDB 叠层"])
    n_cu = len(copper_top_down)
    cu_set = set(copper_top_down)
    warnings: list[str] = []

    # ---- 元素容器预检：缺键按空处理（warning），类型错为致命 ----
    errors: list[str] = []
    raw_lists: dict[str, list] = {}
    for key in ("traces", "vias", "footprints"):
        val = kicad_data.get(key)
        if val is None:
            warnings.append(
                f"extract 产物缺 {key!r} 键（非契约形态），按空处理")
            raw_lists[key] = []
        elif isinstance(val, list):
            raw_lists[key] = val
        else:
            errors.append(
                f"extract 产物 {key!r} 非 list（得 {type(val).__name__}）")
    if errors:
        return _fail(errors)

    # ---- 叠层（auto：copper_layers 列表序=KiCad 层 id 升序=物理顶→底；
    #      EDB 栈序惯例 bottom→top，故反转排列）----
    stackup_node = board.get("stackup")
    dielectrics = (stackup_node.get("dielectrics")
                   if isinstance(stackup_node, dict) else None)
    if dielectrics is None:
        dielectrics = []
    if not isinstance(dielectrics, list):
        warnings.append("board.stackup.dielectrics 非 list，按无介质信息处理")
        dielectrics = []
    expected_diel = n_cu - 1
    seq_top_down: list[dict[str, Any]] = []
    if len(dielectrics) == expected_diel:
        dielectric_source = "kicad_stackup"
        for k, cu_name in enumerate(copper_top_down):
            seq_top_down.append(_copper_layer(cu_name))
            if k < expected_diel:
                d = dielectrics[k] if isinstance(dielectrics[k], dict) else {}
                seq_top_down.append(_dielectric_layer(d, k + 1))
    else:
        dielectric_source = "placeholder_unresolved"
        warnings.append(
            f"介质层数目失配：extract 产物 {len(dielectrics)} 条 vs 期望 "
            f"{expected_diel} 条（N-1，KiCad 板可能无 (stackup) 节）——"
            "EDB 介质层以 unresolved 占位（厚度/er/tan_d=None）如实表达，"
            "不按板总厚均摊编造")
        for k, cu_name in enumerate(copper_top_down):
            seq_top_down.append(_copper_layer(cu_name))
            if k < expected_diel:
                seq_top_down.append(_unresolved_dielectric(k + 1))

    # ---- 走线：layer 必须在铜层名单，几何恒等直传 ----
    spec_traces: list[dict[str, Any]] = []
    for i, t in enumerate(raw_lists["traces"]):
        if not isinstance(t, dict):
            warnings.append(f"trace[{i}] 非 dict，跳过")
            continue
        layer = t.get("layer")
        net = str(t.get("net", ""))
        if layer not in cu_set:
            warnings.append(
                f"trace[{i}] layer={layer!r} 不在 copper_layers"
                f"（net={net!r}），跳过")
            continue
        width = _num(t.get("width_mm"))
        if width is None or width <= 0:
            warnings.append(
                f"trace[{i}] width_mm 非正有限数"
                f"（net={net!r} layer={layer!r}），跳过")
            continue
        pts = _trace_points(t.get("points_mm"))
        if pts is None:
            warnings.append(
                f"trace[{i}] points_mm 非法（<2 个有效 [x,y] 点或含"
                f"非有限数值，net={net!r}），跳过")
            continue
        spec_traces.append({
            "name": f"TRACE_{i:04d}", "net": net, "layer": str(layer),
            "width_mm": width, "points_mm": pts,
        })

    # ---- 过孔：extract 契约无 layer pair，仅两层板可确证全叠层层对 ----
    spec_vias: list[dict[str, Any]] = []
    if raw_lists["vias"] and n_cu != 2:
        warnings.append(
            f"extract 契约无 via layer pair——铜层数 N={n_cu}"
            "（仅两层板可确证层对），via start/stop_layer 置 None")
    via_start = copper_top_down[0] if n_cu == 2 else None
    via_stop = copper_top_down[-1] if n_cu == 2 else None
    for i, v in enumerate(raw_lists["vias"]):
        if not isinstance(v, dict):
            warnings.append(f"via[{i}] 非 dict，跳过")
            continue
        x_mm = _num(v.get("x_mm"))
        y_mm = _num(v.get("y_mm"))
        pad_d = _num(v.get("pad_diameter_mm"))
        drill = _num(v.get("drill_mm"))
        if None in (x_mm, y_mm, pad_d, drill):
            warnings.append(
                f"via[{i}] 几何字段含非有限数值"
                f"（net={v.get('net')!r}），跳过")
            continue
        spec_vias.append({
            "name": f"VIA_{i:04d}", "net": str(v.get("net", "")),
            "x_mm": x_mm, "y_mm": y_mm,
            "pad_diameter_mm": pad_d, "drill_mm": drill,
            "start_layer": via_start, "stop_layer": via_stop,
        })

    # ---- 焊盘：footprint 展开，层集与铜层名单取交集 ----
    spec_pads: list[dict[str, Any]] = []
    pad_idx = 0
    for fi, fp in enumerate(raw_lists["footprints"]):
        if not isinstance(fp, dict):
            warnings.append(f"footprint[{fi}] 非 dict，跳过")
            continue
        ref = str(fp.get("reference", ""))
        pads_raw = fp.get("pads")
        if pads_raw is None:
            warnings.append(
                f"footprint[{fi}]（{ref!r}）缺 pads 键，按无焊盘处理")
            pads_raw = []
        elif not isinstance(pads_raw, list):
            warnings.append(
                f"footprint[{fi}]（{ref!r}）pads 非 list，按无焊盘处理")
            pads_raw = []
        for pi, p in enumerate(pads_raw):
            if not isinstance(p, dict):
                warnings.append(
                    f"footprint[{fi}] pad[{pi}] 非 dict，跳过")
                continue
            number = str(p.get("number", ""))
            label = (f"{ref}-{number}" if ref and number
                     else f"footprint[{fi}].pads[{pi}]")
            layers_raw = p.get("layers")
            layers_raw = layers_raw if isinstance(layers_raw, list) else []
            names_all = [str(x) for x in layers_raw]
            mapped_layers = [x for x in names_all if x in cu_set]
            unmapped = [x for x in names_all if x not in cu_set]
            if unmapped:
                warnings.append(
                    f"pad {label} 层集含未映射层 {unmapped!r}，"
                    f"仅保留已映射层 {mapped_layers!r}")
            if not mapped_layers:
                warnings.append(f"pad {label} 层集与铜层名单无交集，跳过")
                continue
            x_mm = _num(p.get("x_mm"))
            y_mm = _num(p.get("y_mm"))
            w_mm = _num(p.get("w_mm"))
            h_mm = _num(p.get("h_mm"))
            if None in (x_mm, y_mm, w_mm, h_mm):
                warnings.append(f"pad {label} 几何字段含非有限数值，跳过")
                continue
            shape_raw = p.get("shape")
            shape_code = (shape_raw if isinstance(shape_raw, int)
                          and not isinstance(shape_raw, bool) else None)
            spec_pads.append({
                "name": label, "reference": ref, "number": number,
                "net": str(p.get("net", "")), "layers": mapped_layers,
                "x_mm": x_mm, "y_mm": y_mm, "w_mm": w_mm, "h_mm": h_mm,
                "shape_code": shape_code,
                "shape": _KNOWN_PAD_SHAPES.get(shape_code),
            })
            pad_idx += 1

    # ---- 板框直通；zones 如实告警不静默丢弃 ----
    outline_raw = kicad_data.get("outline")
    if isinstance(outline_raw, dict) and outline_raw:
        outline: dict[str, Any] = dict(outline_raw)
    else:
        outline = {}
        warnings.append(
            "板框缺失或非 dict——EDB 版图外框需消费方另行给定"
            "（KiCad 板框多边形提取失败时 extract 契约 outline={}）")
    zones_raw = kicad_data.get("zones")
    if isinstance(zones_raw, list) and zones_raw:
        warnings.append(
            f"zones[{len(zones_raw)}] 暂不映射（spike 已知限制：平面原语"
            "列路标，见模块 docstring）——如实不入 spec")

    return {
        "ok": True,
        "bridge": BRIDGE_NAME,
        "bridge_version": BRIDGE_VERSION,
        "units": "mm",
        "stackup_policy": stackup_policy,
        "source_kicad_version": str(board.get("kicad_version", "")),
        "stackup": {
            "order": "bottom_to_top",
            "layers": list(reversed(seq_top_down)),
            "copper_layer_count": n_cu,
            "total_thickness_mm": _num(board.get("thickness_mm")),
            "substrate_er": _num(board.get("substrate_er")),
            "dielectric_source": dielectric_source,
            "copper_thickness_source": "unresolved_kicad_extract_contract",
            "kicad_to_edb_layers": {n: n for n in copper_top_down},
        },
        "traces": spec_traces,
        "vias": spec_vias,
        "pads": spec_pads,
        "outline": outline,
        "warnings": warnings,
        "counts": {
            "traces": len(spec_traces),
            "vias": len(spec_vias),
            "pads": len(spec_pads),
            "warnings": len(warnings),
        },
        "errors": [],
    }
