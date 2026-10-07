"""F-I P2 叠层多层化：多层介质 z 序校验 + 多基板段渲染 + KiCad dielectrics 全层消费。

方案依据：研究扩充 round5 §二 F-I 三段计划 P2——
"叠层多层化（render_script substrate 扩展 + KiCad dielectrics 全层消费）"；
schema 沿 P1 ``layout_stack.RFStackup/RFRouteLayer``（多层 dielectric+导体层序
本身已是 schema 能力，本模块补**层序语义**与**材料数值解析**，不改 P1 文件）。

边界（本模块口径，勿越界）
--------------------------
- 只产出**确定性文本/规格**：介质 Box 串联段（CSXCAD 语句文本）+ z 网格线段。
  既有 ``openems_templates.render_script`` 逐字节不动（#329 纪律：缺省路径
  unified diff 为空由"本模块是新增文件、零改动既有渲染"构造性成立）；
- **单层退化恒等式**（字节钉）：单介质层输入 + 旧路径符号约定
  （``ER``/``TAND``/``F0``/``BOARD``/``H_SUB``、prop 名 ``substrate``、
  guided 分支注释）→ 生成文本与 openems_templates 基板块**逐字节相同**
  （测试从模板源码锚定金色文本，防转录漂移）；
- 本模块不 import openems_templates（P1 同纪律：只对齐形态不产生耦合）；
  介质默认背景即空气（openEMS 缺省 background），层间空气隙合法、只报告不阻塞。

单位约定
--------
- RFStackup 侧 z/厚度一律**米**（P1 口径）；KiCad 解析侧 mm→m 显式 ``×1e-3``；
- 材料数值（epsilon_r/loss_tangent）**无量纲**，经
  :class:`MaterialProps` 按层名解析——介质层缺定义显式 ValueError，不猜（#122）。

KiCad 全层消费纪律（#210 族）
------------------------------
- 纯文本 s-expression 解析（``.kicad_pcb`` 的 ``(stackup ...)`` 节），零
  pcbnew 依赖；**层 id 不写死**——只按 ``(type "copper"|"core"|"prepreg")``
  分派、其余类型（silk/mask）如实跳过计数；层名取自文件原文；
- 解析顺序 = 文件顺序（KiCad 惯例自顶向下），叠层 z 从板底面向上累计
  （文件序反转后 z=0 起），确定性可复算；
- epsilon_r 缺失默认**严格报错**（全层消费不猜材料）；loss_tangent 缺失
  取 0.0 并如实计数（0.0 是定义值非猜测值）。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from rfauto.adapters.kicad_extract import (
    _STACKUP_FIELDS,
    _STACKUP_LAYER_SPLIT,
    _extract_stackup_block,
)
from rfauto.adapters.layout_stack import RFRouteLayer, RFStackup

__all__ = [
    "PLAN_SUBSTRATE_VERSION",
    "MaterialProps",
    "plan_substrate_boxes",
    "render_substrate_block",
    "render_substrate_mesh_block",
    "resolve_material_props",
    "stackup_from_kicad_pcb",
    "stackup_from_kicad_text",
    "validate_stackup_z_order",
]

#: 基板规格形态版本（plan_substrate_boxes 输出 dict 契约锚，渲染器 P3 消费）。
PLAN_SUBSTRATE_VERSION = 1

#: 相邻层界面近重合合并容差（米）：手写叠层两侧 z 值可能差 ulp 级，
#: 重复近重合界面线是 #152 族 CFL 塌缩源——网格段与 Box 段都按此合并口径。
_INTERFACE_MERGE_TOL_M = 1e-12

#: KiCad 介质层 type 值（文件原文口径；其余 type 如实跳过，不写死层 id）。
_KICAD_DIELECTRIC_TYPES: tuple[str, ...] = ("core", "prepreg")
_KICAD_TYPE_RX = re.compile(r'\(type\s+"([^"]+)"\)')

#: 铜层可指派的 kind（介质 kind 只能来自介质层，铜层指派 dielectric 无意义）。
_COPPER_KINDS: tuple[str, ...] = ("signal", "ground")


@dataclass(frozen=True)
class MaterialProps:
    """介质材料数值（按**层名**解析入叠层；无量纲）。"""

    epsilon_r: float
    loss_tangent: float

    def __post_init__(self) -> None:
        for field_name in ("epsilon_r", "loss_tangent"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(
                    f"MaterialProps.{field_name} 必须为数值: {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(
                    f"MaterialProps.{field_name} 必须有限: {value!r}")
        if float(self.epsilon_r) <= 0.0:
            raise ValueError(f"epsilon_r 必须为正: {self.epsilon_r!r}")
        if float(self.loss_tangent) < 0.0:
            raise ValueError(
                f"loss_tangent 必须非负: {self.loss_tangent!r}")


# ---------------------------------------------------------------------------
# 材料数值解析（层名 → MaterialProps，缺定义不猜）
# ---------------------------------------------------------------------------


def resolve_material_props(
    stackup: RFStackup, material_props: Mapping[str, MaterialProps] | None
) -> dict[str, MaterialProps]:
    """按介质层名解析材料数值。

    严格口径（不猜、不静默）：

    - 每个介质层的层名必须在 ``material_props`` 中有定义，缺失 → ValueError
      （一次列全，便于 YAML 手工叠层路径一次性补齐）；
    - ``material_props`` 中不被任何介质层引用的键 → ValueError
      （层名拼错的诚实检测，防"配了但没生效"）。

    返回 {介质层名: MaterialProps}（仅介质层）。
    """
    dielectrics = [lay for lay in stackup.layers if lay.kind == "dielectric"]
    if not dielectrics:
        raise ValueError(
            f"叠层 {stackup.name!r} 不含介质层（kind='dielectric'）——无基板可渲染；"
            "自由空间器件走模板族不走本路径")
    props_map = dict(material_props or {})
    missing = [lay.name for lay in dielectrics if lay.name not in props_map]
    if missing:
        raise ValueError(
            f"叠层 {stackup.name!r} 介质层缺材料数值定义（键=层名）: {missing}；"
            f"现有定义键: {sorted(props_map)}")
    unknown = sorted(set(props_map) - {lay.name for lay in dielectrics})
    if unknown:
        raise ValueError(
            f"material_props 含未被介质层引用的键（层名拼错?）: {unknown}；"
            f"介质层: {[lay.name for lay in dielectrics]}")
    return {name: props_map[name] for name in (lay.name for lay in dielectrics)}


# ---------------------------------------------------------------------------
# z 层序校验（多层 dielectric + 导体层序语义）
# ---------------------------------------------------------------------------


def validate_stackup_z_order(
    stackup: RFStackup, *, tol_m: float = 1e-12
) -> dict[str, Any]:
    """叠层 z 序校验 + 报告（介质 Box 串联要求正厚层层序两两不交）。

    规则（确定性，不猜）：

    - 介质层厚度必须为正（零厚介质无物理意义，显式 ValueError）；
    - 正厚层（任意 kind）z 区间 ``[zmin, zmin+thickness]`` 互不交：
      交叠超过 ``tol_m`` → ValueError（一次列全冲突对）；
    - 零厚导体片（PCB 惯例：铜厚在渲染里走零厚面）落在介质界面上=合法，
      不参与交叠判定；**正厚导体**允许存在（厚铜）但不由本模块渲染，
      如实计数 ``n_thick_conductors`` 供上游判读；
    - 层间正间隙 = 空气隙（openEMS 背景即空气）→ 合法，逐段报告 ``gaps``。

    返回 ``{"layers": [{name, kind, z_lo_m, z_hi_m}...按 zmin 升序],
    "gaps": [{below, above, gap_m}...], "n_thick_conductors": int}``。
    """
    if not stackup.layers:
        raise ValueError(f"叠层 {stackup.name!r} 层表为空")
    for lay in stackup.layers:
        if lay.kind == "dielectric" and float(lay.thickness_m) <= 0.0:
            raise ValueError(
                f"介质层 {lay.name!r} 厚度必须为正（零厚介质无物理意义）: "
                f"{lay.thickness_m!r}")
    spans = sorted(
        (
            (float(lay.zmin_m), float(lay.zmin_m) + float(lay.thickness_m), lay.name, lay.kind)
            for lay in stackup.layers
        ),
        key=lambda t: (t[0], t[1], t[2]),
    )
    overlaps: list[str] = []
    gaps: list[dict[str, Any]] = []
    for (z0a, z1a, na, _), (z0b, z1b, nb, _) in pairwise(spans):
        if (z1a - z0a) <= tol_m or (z1b - z0b) <= tol_m:
            continue  # 零厚片不参与交叠/间隙判定（界面上的导体片=惯例）
        overlap = min(z1a, z1b) - max(z0a, z0b)
        if overlap > tol_m:
            overlaps.append(
                f"层 {na!r} [{z0a!r}, {z1a!r}] 与层 {nb!r} [{z0b!r}, {z1b!r}] 重叠 {overlap!r} m")
            continue
        gap = z0b - z1a
        if gap > tol_m:
            gaps.append({"below": na, "above": nb, "gap_m": gap})
    if overlaps:
        raise ValueError(
            f"叠层 {stackup.name!r} z 序冲突（介质 Box 串联要求正厚层区间两两不交）: "
            + "；".join(overlaps))
    n_thick = sum(
        1
        for lay in stackup.layers
        if lay.kind in ("signal", "ground") and float(lay.thickness_m) > tol_m
    )
    return {
        "layers": [
            {"name": name, "kind": kind, "z_lo_m": z0, "z_hi_m": z1}
            for z0, z1, name, kind in spans
        ],
        "gaps": gaps,
        "n_thick_conductors": n_thick,
    }


# ---------------------------------------------------------------------------
# 基板 Box 规格与渲染（多介质串联；单层退化=旧路径逐字节）
# ---------------------------------------------------------------------------


def plan_substrate_boxes(
    stackup: RFStackup, material_props: Mapping[str, MaterialProps] | None
) -> list[dict[str, Any]]:
    """叠层 + 材料数值 → 介质 Box 规格列表（zmin 升序；prop 名按材料组去重）。

    prop 命名（确定性）：按发射序首个出现 ``(epsilon_r, loss_tangent)`` 组取
    ``"substrate"``（单组/首组，兼容既有消费者对 prop 名 ``substrate`` 的预期），
    第 k 个新材料组（k≥2）取 ``f"substrate_{k}"``；同组多层共享同一 prop
    （一份 AddMaterial + 多条 AddBox，物理上同材料）。

    每项::

        {"version": 1, "prop": str, "layer": 层名, "z_lo_m": float,
         "z_hi_m": float, "epsilon_r": float, "loss_tangent": float}
    """
    props = resolve_material_props(stackup, material_props)
    validate_stackup_z_order(stackup)
    dielectrics = sorted(
        (lay for lay in stackup.layers if lay.kind == "dielectric"),
        key=lambda lay: (float(lay.zmin_m), lay.name),
    )
    group_names: dict[tuple[float, float], str] = {}
    boxes: list[dict[str, Any]] = []
    for lay in dielectrics:
        p = props[lay.name]
        key = (float(p.epsilon_r), float(p.loss_tangent))
        if key not in group_names:
            group_names[key] = "substrate" if not group_names else f"substrate_{len(group_names) + 1}"
        z_lo = float(lay.zmin_m)
        z_hi = z_lo + float(lay.thickness_m)
        boxes.append(
            {
                "version": PLAN_SUBSTRATE_VERSION,
                "prop": group_names[key],
                "layer": lay.name,
                "z_lo_m": z_lo,
                "z_hi_m": z_hi,
                "epsilon_r": key[0],
                "loss_tangent": key[1],
            }
        )
    return boxes


def render_substrate_block(
    stackup: RFStackup,
    material_props: Mapping[str, MaterialProps] | None,
    *,
    x_lo: str = "-BOARD",
    y_lo: str = "-BOARD",
    x_hi: str = "BOARD",
    y_hi: str = "BOARD",
    er_expr: Callable[[MaterialProps], str] | None = None,
    tand_expr: Callable[[MaterialProps], str] | None = None,
    freq_expr: str = "F0",
    z_literal: Callable[[float], str] | None = None,
    var_name: str = "sub",
    header_comment: str | None = None,
    priority: int = 0,
) -> str:
    """介质 Box 串联段 → CSXCAD 语句文本（确定性；同输入逐字节同）。

    发射形态（对齐 openems_templates 基板块惯例）::

        {var} = CSX.AddMaterial("{prop}", epsilon={er},
                                kappa={tand} * 2 * np.pi * {freq} * 8.854187817e-12 * {er})
        {var}.AddBox(({x_lo}, {y_lo}, {z0}), ({x_hi}, {y_hi}, {z1}), priority={priority})

    - AddMaterial 每 prop 只发射一次（后续层只发 AddBox）；
    - 表达式参数：缺省**数值自包含发射**（``repr`` 浮点，生成脚本不依赖
      未定义符号）；``er_expr``/``tand_expr``/``freq_expr``/``z_literal``/
      ``x_lo..y_hi`` 供调用方注入脚本侧符号名——单介质层 + 旧路径符号约定
      即得与 openems_templates guided 分支**逐字节相同**的基板块（字节钉）；
      多材料组的符号命名由调用方表达式负责（可按 er 值分派符号）；
    - ``header_comment`` 首行注释（缺省无）；补尾换行由本函数负责；
    - 渲染前经 :func:`plan_substrate_boxes`（材料解析 + z 序校验，冲突显错）。
    """
    boxes = plan_substrate_boxes(stackup, material_props)
    er_fn = er_expr if er_expr is not None else (lambda p: repr(p.epsilon_r))
    tand_fn = tand_expr if tand_expr is not None else (lambda p: repr(p.loss_tangent))
    z_fn = z_literal if z_literal is not None else (lambda z: repr(z))
    indent = " " * len(f"{var_name} = CSX.AddMaterial(")
    lines: list[str] = []
    if header_comment:
        lines.append(header_comment if header_comment.endswith("\n") else header_comment + "\n")
    defined: set[str] = set()
    for box in boxes:
        if box["prop"] not in defined:
            props = MaterialProps(epsilon_r=box["epsilon_r"], loss_tangent=box["loss_tangent"])
            er = er_fn(props)
            tand = tand_fn(props)
            lines.append(f'{var_name} = CSX.AddMaterial("{box["prop"]}", epsilon={er},\n')
            lines.append(
                f"{indent}kappa={tand} * 2 * np.pi * {freq_expr} * 8.854187817e-12 * {er})\n")
            defined.add(box["prop"])
        lines.append(
            f'{var_name}.AddBox(({x_lo}, {y_lo}, {z_fn(box["z_lo_m"])}), '
            f'({x_hi}, {y_hi}, {z_fn(box["z_hi_m"])}), priority={int(priority)})\n')
    return "".join(lines)


def render_substrate_mesh_block(
    stackup: RFStackup,
    material_props: Mapping[str, MaterialProps] | None,
    *,
    var_name: str = "mesh",
    base_expr: str = "BASE",
) -> str:
    """介质界面 z 网格线段（所有介质 Box 上下界面入网 + SmoothMesh）。

    界面集合 = 各介质 Box 的 ``[z_lo, z_hi]`` 全体，升序 + 近重合合并
    （:data:`_INTERFACE_MERGE_TOL_M`，#152 族纪律：界面线重复/近重合是
    CFL 时间步塌缩源）。发射形态::

        {var}.AddLine("z", np.array([...]))
        {var}.SmoothMeshLines("z", {base_expr})
    """
    boxes = plan_substrate_boxes(stackup, material_props)
    faces: list[float] = []
    for box in boxes:
        for z in (box["z_lo_m"], box["z_hi_m"]):
            if all(abs(z - kept) > _INTERFACE_MERGE_TOL_M for kept in faces):
                faces.append(z)
    faces.sort()
    arr = ", ".join(repr(z) for z in faces)
    return (
        f'{var_name}.AddLine("z", np.array([{arr}]))\n'
        f"{var_name}.SmoothMeshLines(\"z\", {base_expr})\n"
    )


# ---------------------------------------------------------------------------
# KiCad dielectrics 全层消费（.kicad_pcb 文本 s-expression，零 pcbnew 依赖）
# ---------------------------------------------------------------------------


def stackup_from_kicad_text(
    pcb_text: str,
    *,
    copper_kinds: Mapping[str, str] | None = None,
    require_epsilon_r: bool = True,
    stackup_name: str = "kicad_stackup",
) -> dict[str, Any]:
    """.kicad_pcb ``(stackup ...)`` 节 → 全层 RFStackup + 按层名材料数值。

    口径（模块 docstring"KiCad 全层消费纪律"）：

    - 复用 ``kicad_extract`` 的块截取/字段正则（只读复用，#315 不改共享解析器）；
      层名取文件原文、**层 id 不写死**，按 ``(type ...)`` 分派：
      ``copper`` → 导体层（kind 由 ``copper_kinds`` 按层名指派，缺省
      ``signal``；值域 {signal, ground}）；``core``/``prepreg`` → 介质层
      （kind=dielectric，material 记 type 原文）；其余（silk/mask 等）→
      如实跳过计数；
    - 铜层/介质层 ``(thickness ...)`` 缺失 → ValueError（z 推算不猜）；
    - 介质层 epsilon_r 缺失：``require_epsilon_r=True``（缺省）→ ValueError；
      False → 该层不进 material_props（下游渲染前由 resolve_material_props
      二次显错）；loss_tangent 缺失 → 0.0 并计数 ``loss_tangent_defaulted``
      （0.0=定义值非猜测值）；
    - z 叠放：文件序（顶→底）反转后自板底 z=0 向上累计，mm→m 显式 ``×1e-3``；
    - ``copper_kinds`` 引用不存在的铜层名 → ValueError（拼错诚实检测）。

    返回 ``{"stackup": RFStackup, "material_props": {介质层名: MaterialProps},
    "stats": {n_entries, n_copper, n_dielectrics, skipped_layers,
    loss_tangent_defaulted, board_thickness_m}}``。
    """
    block = _extract_stackup_block(pcb_text)
    if block is None:
        raise ValueError(
            ".kicad_pcb 无 (stackup) 节（KiCad python 新建板默认无叠层）——"
            "多层化请改用 YAML 手工叠层路径（layout_stack.load_stackup）")
    kinds = dict(copper_kinds or {})
    bad_kind = sorted(k for k, v in kinds.items() if v not in _COPPER_KINDS)
    if bad_kind:
        raise ValueError(
            f"copper_kinds 值必须在 {_COPPER_KINDS} 内: 非法键 {bad_kind}")

    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    for chunk in _STACKUP_LAYER_SPLIT.split(block)[1:]:
        name = chunk.split('"', 1)[0] if '"' in chunk else ""
        type_match = _KICAD_TYPE_RX.search(chunk)
        layer_type = type_match.group(1) if type_match else None
        is_copper = layer_type == "copper"
        is_dielectric = layer_type in _KICAD_DIELECTRIC_TYPES
        if not is_copper and not is_dielectric:
            skipped.append(f"{name}({layer_type})")
            continue
        th_match = _STACKUP_FIELDS["thickness_mm"].search(chunk)
        entry: dict[str, Any] = {
            "name": name,
            "type": layer_type,
            "thickness_mm": float(th_match.group(1)) if th_match else None,
            "er": None,
            "tan_d": None,
        }
        if is_dielectric:
            er_match = _STACKUP_FIELDS["er"].search(chunk)
            td_match = _STACKUP_FIELDS["tan_d"].search(chunk)
            entry["er"] = float(er_match.group(1)) if er_match else None
            entry["tan_d"] = float(td_match.group(1)) if td_match else None
        entries.append(entry)

    copper_names = {e["name"] for e in entries if e["type"] == "copper"}
    unknown_kinds = sorted(set(kinds) - copper_names)
    if unknown_kinds:
        raise ValueError(
            f"copper_kinds 引用了不存在的铜层: {unknown_kinds}；铜层原文: {sorted(copper_names)}")
    no_thickness = [e["name"] for e in entries if e["thickness_mm"] is None]
    if no_thickness:
        raise ValueError(f"层缺 (thickness ...)，z 推算不猜: {no_thickness}")
    missing_er = [
        e["name"] for e in entries if e["type"] in _KICAD_DIELECTRIC_TYPES and e["er"] is None
    ]
    if require_epsilon_r and missing_er:
        raise ValueError(
            f"介质层缺 (epsilon_r ...)——全层消费不猜材料: {missing_er}；"
            "可 require_epsilon_r=False 跳过（下游渲染前仍会显错）")
    if not any(e["type"] in _KICAD_DIELECTRIC_TYPES for e in entries):
        raise ValueError("stackup 节未解析出介质层（core/prepreg）——纯铜叠层无基板可渲染")

    defaulted_tan = [
        e["name"]
        for e in entries
        if e["type"] in _KICAD_DIELECTRIC_TYPES and e["tan_d"] is None
    ]
    layers: list[RFRouteLayer] = []
    material_props_out: dict[str, MaterialProps] = {}
    z = 0.0
    for entry in reversed(entries):  # 文件序=顶→底；反转后自板底向上叠放
        thickness_m = float(entry["thickness_mm"]) * 1e-3
        if entry["type"] == "copper":
            kind = kinds.get(entry["name"], "signal")
            material = "copper"
        else:
            kind = "dielectric"
            material = str(entry["type"])
            if entry["er"] is not None:
                material_props_out[entry["name"]] = MaterialProps(
                    epsilon_r=float(entry["er"]),
                    loss_tangent=float(entry["tan_d"]) if entry["tan_d"] is not None else 0.0,
                )
        layers.append(
            RFRouteLayer(
                name=entry["name"],
                zmin_m=z,
                thickness_m=thickness_m,
                material=material,
                kind=kind,
            )
        )
        z += thickness_m
    n_copper = sum(1 for entry in entries if entry["type"] == "copper")
    return {
        "stackup": RFStackup(name=stackup_name, layers=tuple(layers)),
        "material_props": material_props_out,
        "stats": {
            "n_entries": len(entries),
            "n_copper": n_copper,
            "n_dielectrics": len(entries) - n_copper,
            "skipped_layers": skipped,
            "loss_tangent_defaulted": defaulted_tan,
            "board_thickness_m": z,
        },
    }


def stackup_from_kicad_pcb(
    pcb_path: str | Path,
    *,
    copper_kinds: Mapping[str, str] | None = None,
    require_epsilon_r: bool = True,
    stackup_name: str = "kicad_stackup",
) -> dict[str, Any]:
    """:func:`stackup_from_kicad_text` 的文件入口（UTF-8 读，errors=replace）。"""
    text = Path(pcb_path).read_text(encoding="utf-8", errors="replace")
    return stackup_from_kicad_text(
        text,
        copper_kinds=copper_kinds,
        require_epsilon_r=require_epsilon_r,
        stackup_name=stackup_name,
    )
