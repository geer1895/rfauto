"""F-I P3 离线面：layout_sim_service——版图 → openEMS render_script 组装 + 发射面产物清单。

方案依据：研究扩充 round5 §二 F-I 三段计划 P3——
"layout_sim_service+render_layout（openEMS 平行渲染器）+HFSS sheet 渲染+#212
离线审计+论文 GDS 复现首例"；本模块承担其中**离线面**：service 组装层
（stackup+ports+版图几何 → 完整 render_script 文本）+ 发射面（产物清单/预算
注记）。真机求解、HFSS sheet 渲染与多激励 S 矩阵装配属 P3 真机窗（本面零
FDTD 执行，`zero_solve=True` 恒真——组装产物是给发射器执行的文本，不是执行）。

组装口径（读后对齐，零行为变化）
--------------------------------
- **叠层/介质段**：直接消费 P2 :func:`render_substrate_block` /
  :func:`render_substrate_mesh_block` 的产物文本（**逐字节拼入不转写**——
  #329 旋钮纪律：既有渲染组件进来不变，测试以字节包含钉住）；
- **几何段**：P1 :func:`bridge_layout_to_stackup` 渲染原语 →
  ``AddPolygon(([xs], [ys]), norm_dir="z", elevation=z, priority=p)``
  字面量（kicad_board_render._polygon_args 同款惯例，米制 repr 浮点）；
  孔洞按 kicad 同款"基板材料同面更高 priority 多边形切除"发射；
- **端口段**：P2 :func:`resolve_ports` 归一端口 → LumpedPort（官方
  ``AddLumpedPort(port_nr, R, start, stop, axis, excite)`` 口径，
  openems_templates CPS 段同款）。参考地规则（确定性）：端口层下方有
  ground 层 → 垂直端口（z 从参考地层顶到端口层 zmin，微带/带状线板）；
  否则同 z 共面地 → 零厚面内端口（沿方向正交轴居中展开 width，CPS 槽线
  族同款，方向须轴对齐）；无参考地 → ok=False 不猜。
  ``port_type="msl"`` **v1 显式拒绝**（MSLPort 的 MeasPlaneShift/
  FeedShift 守卫依赖终网格，#347；属 P3 真机窗接线）；
- **网格段**：介质界面 z 线（P2 逐字节）+ 金属面 z 线 + 端口位置 x/y 精确线
  （端口面必须落格，#154 前节）+ NEAR/BASE 官方平滑配方 + 最小间距守卫
  （#152，与 openems_templates 生成脚本同款去重循环）。

发射面（产物清单/预算注记）
---------------------------
- ``artifacts``：simulation.py（渲染脚本，含 sha256/字节数）、_rfauto_runner.py
  （openems_solver 求解期按 exe_path 生成，条件产物）、sparams.csv（预期产物）、
  fdtd/（引擎工作目录，引擎自管）；
- ``budget``：NrTS 预算**占位注记**——dt 下界按 base 网格 CFL（courant=1.0
  上界 → 步数下界口径）；真预算必须按终网格最小格 CFL 实算（#328/#312），
  本占位只作发射面预算参考，不回写脚本 NrTS（脚本用显式 nrts 或官方缺省
  100000）。

诚实边界（v1，预声明）
----------------------
1. ``port_type="msl"`` → ok=False（真机窗接线）；LumpedPort 需要参考地
   （端口层下方 ground 层 → 垂直模式；同 z 共面地 → 面内模式，方向须轴
   对齐）；两者皆无 → ok=False 不猜；
2. 孔洞切除 v1 仅支持**单介质材料组**叠层（多材料组的 ``sub`` 变量在
   render_substrate_block 中被重绑，孔洞归属不唯一）→ 多组+孔洞 ok=False；
   且 B2 ``LayoutPolygon`` 无孔洞字段——带孔几何只能走 ``primitives``
   直通面（P1 渲染原语契约形态）进入本服务；
3. 几何段 spec 二选一：``layout``（B2 载荷 → P1 桥）或 ``primitives``
   （P1 原语直通）；直通面端口只接受显式记录表（marker/启发式通道需要
   B2 版图对象）；
4. 单激励 S11 提取；整 S 矩阵走 N×单激励装配（#208 openems_rotation 模式，
   求解面）；
5. 域对称（±DOM 以原点为中心）+ 全 MUR 边界；PEC 底板/PML 端口轴等
   guided 精化属真机窗调参面。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from rfauto.adapters.layout_ports import (
    COMPOSE_PIN_KEYS,
    LayoutPort,
    port_table_from_records,
    resolve_ports,
)
from rfauto.adapters.layout_stack import (
    PRIMITIVE_SCHEMA_VERSION,
    RFStackup,
    bridge_layout_to_stackup,
    stackup_from_dict,
)
from rfauto.adapters.layout_substrate import (
    PLAN_SUBSTRATE_VERSION,
    MaterialProps,
    plan_substrate_boxes,
    render_substrate_block,
    render_substrate_mesh_block,
)

# F-13 批 2（W6-E）：载荷守卫单源化（#116 删净）。文案分歧件已声明统一：
# 原「payload 必须为映射: X」→ 单源「payload 必须是 JSON 对象，实际 X」
# （try/except ValueError 捕获进 errors 的 ok=False 语义逐位不变，文案
# 变更见 W6-E 报告）。
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.layout_service import layout_from_payload

__all__ = [
    "LAYOUT_SIM_SERVICE_SCHEMA_VERSION",
    "layout_sim_prepare",
]

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
LAYOUT_SIM_SERVICE_SCHEMA_VERSION = "1.0"

#: 引擎口径（P3 离线面只组装 openEMS 渲染文本）
_ENGINE = "openEMS"

#: 官方缺省 NrTS（openems_templates 官方口径）
_NRTS_OFFICIAL_DEFAULT = 100000

#: 官方 substrate_cells（z 向介质格数，dz 占位估算用；#313 z 向地板项）
_SUB_CELLS = 4

#: 官方近走线区比例（NEAR = BASE/4）
_NEAR_RATIO = 4

#: 真空光速（m/s，CFL 占位估算用）
_C0 = 299792458.0

#: 域外扩缺省（mm，v1 确定性缺省，可经 sim.domain_pad_mm 覆盖）
_DOMAIN_PAD_DEFAULT_MM = 10.0

#: 金属属性 priority 起点（基板 Box priority=0，金属层按 z 升序自此递增）
_PRIORITY_BASE = 10

#: 端口层参考地搜索容差（米）：ground 层顶 ≤ 端口层 zmin − 容差才算"下方"
_GROUND_BELOW_TOL_M = 1e-12

#: 面内端口方向轴对齐判据（归一方向的单分量下限：|另一分量| 低于此值视为 0）
_AXIS_ALIGNED_TOL = 1e-9

#: python 变量名清洗：非字母数字 → 下划线
_VAR_RX = re.compile(r"\W")

#: 频点数（官方 MSL_NotchFilter 口径 401）
_N_FREQ = 401


# ---------------------------------------------------------------------------
# 小工具（确定性发射）
# ---------------------------------------------------------------------------


def _require_number(value: Any, what: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{what} 必须为数值: {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{what} 必须有限: {out!r}")
    return out


def _polygon_args(coords: list[tuple[float, float]]) -> str:
    """闭合多边形点列（米）→ AddPolygon 的 ([xs], [ys]) 参数字面量
    （kicad_board_render._polygon_args 同款惯例，repr 浮点保往返）。"""
    xs = "[" + ", ".join(repr(float(p[0])) for p in coords) + "]"
    ys = "[" + ", ".join(repr(float(p[1])) for p in coords) + "]"
    return f"({xs}, {ys})"


def _metal_var(layer_name: str, used: set[str]) -> str:
    """层名 → 无冲突 python 变量名/CSX 属性名（确定性：首见序 + 数字后缀）。

    变量名与 AddMetal 属性名同串（清洗后的安全标识符，原层名仅存活于
    provenance var_map 的键）。
    """
    base = "metal_" + _VAR_RX.sub("_", layer_name)
    var = base
    k = 2
    while var in used:
        var = f"{base}_{k}"
        k += 1
    used.add(var)
    return var


# ---------------------------------------------------------------------------
# 输入归一
# ---------------------------------------------------------------------------


def _normalize_ports(
    layout: Any, ports: Any
) -> tuple[list[LayoutPort], dict[str, Any]]:
    """payload["ports"] → resolve_ports 归一结果。

    合法形态（显式，不猜）：
    - 记录列表 = YAML 显式表记录（port_table 通道）；
    - ``{"port_table": [...]}``（可与 ``"marker_layer"`` 并给 → 双显式来源
      交叉验证，裁决规则全在 P2 resolve_ports）；
    - ``{"marker_layer": "..."}``（标记层通道）；
    - 可选 ``"port_layer": "<导体层名>"``：标记层来源的端口 layer 记的是
      标记层名（P2 marker 通道惯例），物理上端口落在哪层导体须由调用方
      显式指派——给定后逐端口 ``dataclasses.replace`` 覆写 layer（交叉
      验证判据不含 layer，覆写不影响裁决结果）。
    """
    if isinstance(ports, list):
        return resolve_ports(layout, port_table=ports)
    if isinstance(ports, dict):
        marker = ports.get("marker_layer")
        table = ports.get("port_table")
        port_layer = ports.get("port_layer")
        if table is None and marker is None:
            raise ValueError(
                'ports 映射形态必须含 "port_table" 或 "marker_layer" 键: '
                f"{sorted(ports)}")
        if table is not None and not isinstance(table, list):
            raise ValueError(f"ports.port_table 必须为列表: {type(table).__name__}")
        if port_layer is not None and not isinstance(port_layer, str):
            raise ValueError(f"ports.port_layer 必须为字符串: {port_layer!r}")
        resolved = resolve_ports(layout, marker_layer=marker, port_table=table)
        if port_layer:
            resolved["ports"] = [
                replace(p, layer=port_layer) for p in resolved["ports"]
            ]
        return resolved
    raise ValueError(f"ports 必须为记录列表或映射: {type(ports).__name__}")


def _resolve_geometry(
    payload: dict[str, Any], stackup: RFStackup
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """几何段 spec → 渲染原语（两来源，显式二选一，不猜）：

    - ``layout``：B2 版图载荷 → P1 桥（bridge_layout_to_stackup）；
    - ``primitives``：P1 渲染原语 dict 直通（PRIMITIVE_SCHEMA_VERSION=1
      形态，米制）——B2 ``LayoutPolygon`` 无孔洞字段（v1 边界：带孔几何
      只能走本直通面，如 GDS 布尔导入产物），最小形态校验在此收口。

    返回 ``(primitives, info)``，info 含几何来源与桥统计（直通面统计为空）。
    """
    layout_data = payload.get("layout")
    primitives_spec = payload.get("primitives")
    if layout_data is not None and primitives_spec is not None:
        raise ValueError("layout 与 primitives 二选一（几何段 spec 不猜）")
    if layout_data is not None:
        layout = layout_from_payload(layout_data)
        bridge = bridge_layout_to_stackup(layout, stackup)
        return bridge["primitives"], {
            "source": "layout_bridge",
            "bridge_stats": bridge["stats"],
            "unmatched_layers": bridge["unmatched_layers"],
        }
    if isinstance(primitives_spec, list):
        if not primitives_spec:
            raise ValueError("primitives 直通列表为空（几何段 spec 不接受空）")
        out: list[dict[str, Any]] = []
        for i, prim in enumerate(primitives_spec):
            if not isinstance(prim, dict):
                raise ValueError(f"primitives[{i}] 必须为映射: {type(prim).__name__}")
            missing = [k for k in ("kind", "coords", "layer", "layer_kind", "zmin_m")
                       if k not in prim]
            if missing:
                raise ValueError(f"primitives[{i}] 缺字段 {missing}")
            if prim["kind"] != "polygon":
                raise ValueError(
                    f"primitives[{i}] kind 必须为 polygon（PRIMITIVE_SCHEMA_VERSION=1）: "
                    f"{prim['kind']!r}")
            if prim["layer_kind"] not in ("signal", "ground"):
                raise ValueError(
                    f"primitives[{i}] layer_kind 必须为 signal/ground: "
                    f"{prim['layer_kind']!r}")
            coords = [(float(x), float(y)) for x, y in prim["coords"]]
            if len(coords) < 3:
                raise ValueError(f"primitives[{i}] coords 至少 3 点: {len(coords)}")
            out.append({
                "kind": "polygon",
                "coords": coords,
                "holes": [[(float(x), float(y)) for x, y in ring]
                          for ring in (prim.get("holes") or [])],
                "layer": str(prim["layer"]),
                "layer_kind": str(prim["layer_kind"]),
                "zmin_m": float(prim["zmin_m"]),
                "mesh_hint_mm": (float(prim["mesh_hint_mm"])
                                 if prim.get("mesh_hint_mm") is not None else None),
            })
        return out, {"source": "primitives_direct", "bridge_stats": None,
                     "unmatched_layers": []}
    raise ValueError("payload 缺几何段 spec（layout 或 primitives 二选一）")


def _validate_ports_for_emission(
    ports: list[LayoutPort], stackup: RFStackup
) -> list[dict[str, Any]]:
    """端口 → 发射规格（LumpedPort 几何；显式规则，不猜）。

    参考地规则（确定性，逐端口）：
    - 端口层**下方**存在 ground 层（顶 ≤ z_metal − 容差）→ ``vertical`` 模式：
      z 从最近参考地层顶到端口层 zmin（微带/带状线板惯例）；端口面内方向
      不参与几何（如实记录）；
    - 否则同 z 存在 ground 层（共面地，CPW 槽线族惯例）→ ``inplane`` 模式：
      端口元沿**方向的正交轴**居中展开 width（CPS 模板 AddLumpedPort 同款
      零厚面内端口）；方向必须轴对齐（非轴对齐显式 ValueError，不猜）；
    - 两者皆无 → ValueError（无参考地的端口不发射）。

    每项 ``{"port", "mode", "axis", "start", "stop", "priority",
    "ground_layer"}``。
    """
    by_name = {lay.name: lay for lay in stackup.layers}
    metal_zs = sorted(
        {float(lay.zmin_m) for lay in stackup.layers
         if lay.kind in ("signal", "ground")})
    z_rank = {z: _PRIORITY_BASE + i for i, z in enumerate(metal_zs)}
    specs: list[dict[str, Any]] = []
    for port in ports:
        if port.port_type != "lumped":
            raise ValueError(
                f"端口 {port.port_id!r} port_type={port.port_type!r}：v1 离线"
                "组装面只发 LumpedPort；msl 端口发射属 P3 真机窗接线"
                "（MSLPort MeasPlaneShift/FeedShift 守卫依赖终网格，#347）")
        if port.layer is None:
            raise ValueError(
                f"端口 {port.port_id!r} 缺 layer 关联——端口需要导体层定 z，不猜")
        lay = by_name.get(port.layer)
        if lay is None or lay.kind not in ("signal", "ground"):
            raise ValueError(
                f"端口 {port.port_id!r} layer {port.layer!r} 不是叠层中的"
                "导体层（kind=signal/ground）——检查叠层选择器与端口表")
        z_metal = float(lay.zmin_m)
        ground_tops = [
            (float(g.zmin_m) + float(g.thickness_m), g.name)
            for g in stackup.layers
            if g.kind == "ground"
            and float(g.zmin_m) + float(g.thickness_m) <= z_metal - _GROUND_BELOW_TOL_M
        ]
        spec: dict[str, Any] = {"port": port, "z_metal_m": z_metal,
                                "priority": z_rank[z_metal]}
        px, py = float(port.position_m[0]), float(port.position_m[1])
        if ground_tops:
            z_ground, g_name = max(ground_tops)
            spec.update({"mode": "vertical", "axis": "z",
                         "start": (px, py, z_ground), "stop": (px, py, z_metal),
                         "ground_layer": g_name})
        else:
            coplanar = [
                g.name for g in stackup.layers
                if g.kind == "ground" and abs(float(g.zmin_m) - z_metal) <= _GROUND_BELOW_TOL_M
            ]
            if not coplanar:
                raise ValueError(
                    f"端口 {port.port_id!r}（层 {port.layer!r}）无参考地——"
                    "下方无 ground 层且同层无共面地；垂直 LumpedPort 需要"
                    "参考地，不发射无参考端口")
            dx, dy = port.direction
            if abs(dx) > _AXIS_ALIGNED_TOL and abs(dy) > _AXIS_ALIGNED_TOL:
                raise ValueError(
                    f"端口 {port.port_id!r} 方向 {(dx, dy)!r} 非轴对齐——共面地"
                    "面内端口 v1 只支持轴对齐方向（正交轴展开），非轴对齐走 "
                    "P3 真机窗接线")
            # 正交轴居中展开 width（CPS 零厚面内端口同款）
            if abs(dx) > _AXIS_ALIGNED_TOL:  # 方向沿 x → 端口元沿 y
                axis, half_vec = "y", (0.0, port.width_m / 2.0)
            else:
                axis, half_vec = "x", (port.width_m / 2.0, 0.0)
            spec.update({
                "mode": "inplane", "axis": axis,
                "start": (px - half_vec[0], py - half_vec[1], z_metal),
                "stop": (px + half_vec[0], py + half_vec[1], z_metal),
                "ground_layer": coplanar[0]})
        specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# 脚本组装（各段确定性文本）
# ---------------------------------------------------------------------------


def _emit_header(oe_bin_dir: str | None) -> str:
    lines = [
        "#!/usr/env/python3\n",
        '"""openEMS script (rfauto layout_sim auto-generated; layout-driven,\n',
        "offline-assembled by layout_sim_service — do not hand-edit).\n",
        '"""\n',
        "import csv\n",
        "import os\n",
        "\n",
    ]
    if oe_bin_dir:
        # 同 openems_templates 惯例：绑定 DLL 目录注入（发射面显式给 bin 时）
        lines += [
            f"_OE_BIN = {str(Path(oe_bin_dir).resolve())!r}\n",
            "if os.path.isdir(_OE_BIN):\n",
            '    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")\n',
            "    os.add_dll_directory(_OE_BIN)\n",
            "\n",
        ]
    lines += [
        "import numpy as np\n",
        "from CSXCAD import ContinuousStructure\n",
        "from openEMS import openEMS\n",
        "from openEMS.ports import LumpedPort\n",
        "\n",
    ]
    return "".join(lines)


def _emit_constants(f0_hz: float, fc_hz: float, base_m: float, near_m: float,
                    nrts: int) -> str:
    return "".join([
        f"F0 = {f0_hz!r}\n",
        f"FC = {fc_hz!r}\n",
        f"BASE = {base_m!r}   # 网格 base（λ_sub/50 官方口径或显式覆盖）\n",
        f"NEAR = {near_m!r}   # 近走线区 = BASE/{_NEAR_RATIO}（官方口径）\n",
        'CSV_NAME = "sparams.csv"\n',
        'SIM_PATH = os.path.abspath("fdtd")\n',
        "CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_NAME)\n",
        f"\nCSX = ContinuousStructure()\nFDTD = openEMS(NrTS={int(nrts)!r})\n",
        "FDTD.SetCSX(CSX)\n",
        "FDTD.SetGaussExcite(F0, FC)\n",
        'FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])\n',
        "\nmesh = CSX.GetGrid()\n",
    ])


def _emit_domain(dom_x_m: float, dom_y_m: float, z_lo_m: float, z_hi_m: float) -> str:
    return "".join([
        f"DOM_X = {dom_x_m!r}\nDOM_Y = {dom_y_m!r}\n",
        f"Z_LO = {z_lo_m!r}\nZ_HI = {z_hi_m!r}\n",
    ])


def _emit_mesh(near_xs_m: list[float], near_ys_m: list[float],
               metal_zs_m: list[float]) -> str:
    """网格段：介质界面 z 线由 P2 mesh block 承担（外部逐字节拼入），
    这里补金属面 z 线、端口位置 x/y 精确线、域界线、官方平滑与 #152 守卫。"""
    lines: list[str] = []
    if metal_zs_m:
        arr = ", ".join(repr(z) for z in sorted(set(metal_zs_m)))
        lines.append(f'mesh.AddLine("z", np.array([{arr}]))\n')
    if near_xs_m:
        arr = ", ".join(repr(x) for x in sorted(set(near_xs_m)))
        lines.append(f'mesh.AddLine("x", np.array([{arr}]))\n')
    if near_ys_m:
        arr = ", ".join(repr(y) for y in sorted(set(near_ys_m)))
        lines.append(f'mesh.AddLine("y", np.array([{arr}]))\n')
    lines.append('mesh.SmoothMeshLines("x", NEAR)\n')
    lines.append('mesh.SmoothMeshLines("y", NEAR)\n')
    lines.append('mesh.AddLine("x", np.array([-DOM_X, DOM_X]))\n')
    lines.append('mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))\n')
    lines.append('mesh.AddLine("z", np.array([Z_LO, Z_HI]))\n')
    lines.append('mesh.SmoothMeshLines("x", BASE)\n')
    lines.append('mesh.SmoothMeshLines("y", BASE)\n')
    # 最小间距守卫（#152；与 openems_templates 生成脚本同款去重循环）
    lines += [
        "# 近重合网格线守卫：浮点误差线可能只差 nm~µm 级，把时间步压塌\n"
        "# （#152）。平滑后按最小间距 1µm 去重。\n",
        'for _ax in ("x", "y", "z"):\n',
        "    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)\n",
        "    _keep = [_ls[0]]\n",
        "    for _v in _ls[1:]:\n",
        "        if _v - _keep[-1] > 1e-6:\n",
        "            _keep.append(_v)\n",
        "    mesh.SetLines(_ax, np.array(_keep))\n",
        "\n",
    ]
    return "".join(lines)


def _emit_metal_geometry(
    primitives: list[dict[str, Any]], substrate_var: str, substrate_groups: int
) -> tuple[str, dict[str, str], int]:
    """渲染原语 → 金属几何段。返回 (文本, 层名→变量映射, 孔洞切除数)。

    - 每导体层一个 AddMetal 属性（变量 ``metal_<清洗层名>``，首见序去重）；
    - 外环 ``AddPolygon(..., priority=p_layer)``，孔洞 = 基板材料同面
      ``priority=p_layer+1`` 切除多边形（kicad_board_render 同款机制）；
    - 孔洞 v1 仅支持单介质材料组（``substrate_var`` 归属唯一）；多组时若仍
      出现孔洞由调用方预检显错。
    """
    var_map: dict[str, str] = {}
    used: set[str] = set()
    lines: list[str] = [
        "# ── 版图金属几何（P1 桥渲染原语 → AddPolygon；米制 repr 浮点）──\n",
    ]
    n_cuts = 0
    for prim in primitives:
        layer = str(prim["layer"])
        var = var_map.get(layer)
        if var is None:
            var = _metal_var(layer, used)
            var_map[layer] = var
            lines.append(f'{var} = CSX.AddMetal("{var}")\n')
        coords = [(float(x), float(y)) for x, y in prim["coords"]]
        priority = int(prim["priority"])
        lines.append(
            f'{var}.AddPolygon({_polygon_args(coords)}, norm_dir="z", '
            f'elevation={float(prim["zmin_m"])!r}, priority={priority})\n')
        for hi, hole in enumerate(prim.get("holes") or []):
            if substrate_groups > 1:
                raise ValueError(
                    f"层 {layer!r} 图元带孔洞但叠层含多介质材料组——孔洞切除的"
                    f"基板属性归属不唯一（v1 边界）；孔洞层请走单材料组叠层")
            ring = [(float(x), float(y)) for x, y in hole]
            lines.append(
                f'{substrate_var}.AddPolygon({_polygon_args(ring)}, norm_dir="z", '
                f'elevation={float(prim["zmin_m"])!r}, priority={priority + 1})'
                f"  # 孔洞切除 {layer}#{hi}\n")
            n_cuts += 1
    lines.append("\n")
    return "".join(lines), var_map, n_cuts


def _emit_ports(specs: list[dict[str, Any]], excite_port: int) -> str:
    lines: list[str] = [
        "# ── 端口段（LumpedPort；官方 AddLumpedPort 口径，单激励）──\n",
    ]
    for i, spec in enumerate(specs, start=1):
        excite = 1.0 if i == excite_port else 0.0
        (sx, sy, sz), (ex, ey, ez) = spec["start"], spec["stop"]
        lines.append(
            f"_port{i} = FDTD.AddLumpedPort({i}, R_PORT, "
            f"np.array([{sx!r}, {sy!r}, {sz!r}]), "
            f"np.array([{ex!r}, {ey!r}, {ez!r}]), "
            f'"{spec["axis"]}", {excite!r}, priority={spec["priority"]})\n')
    lines.append("\n")
    return "".join(lines)


def _emit_run_and_extract(excite_port: int, z_ref: float) -> str:
    e = int(excite_port)
    return (
        "# cleanup：清掉同目录旧 run 的 port/et 输出——CalcPort 读旧信号会\n"
        "# 静默 NaN（openems_templates 同款纪律）\n"
        "FDTD.Run(SIM_PATH, verbose=0, cleanup=True)\n"
        "\n"
        "f = np.linspace(F0 - FC, F0 + FC, 401)\n"
        f"_port{e}.CalcPort(SIM_PATH, f, ref_impedance=R_PORT)\n"
        f"S11 = _port{e}.uf_ref / _port{e}.uf_inc\n"
        "with open(CSV_PATH, \"w\", newline=\"\") as fh:\n"
        "    w = csv.writer(fh)\n"
        "    w.writerow([\"freq_hz\", \"re_S11\", \"im_S11\"])\n"
        "    for i, fi in enumerate(f):\n"
        "        w.writerow([fi, S11[i].real, S11[i].imag])\n"
        f"# v1 单激励 S11 提取（z_ref={z_ref!r}）；整 S 矩阵 = N×单激励装配\n"
        "# （#208 openems_rotation 模式，P3 求解面）。\n"
    )


# ---------------------------------------------------------------------------
# 预算占位（发射面注记；不回写脚本 NrTS）
# ---------------------------------------------------------------------------


def _budget_annotation(
    boxes: list[dict[str, Any]], base_m: float, f0_hz: float, fc_hz: float,
    nrts_explicit: int | None,
) -> dict[str, Any]:
    """CFL 占位预算：dt 稳定上界（courant=1.0）→ 给定窗长的步数**下界**。

    真预算必须按终网格最小格 CFL 实算（#328/#312）——本占位只作发射面
    预算注记，不回写脚本 NrTS。
    """
    dz = min(
        (float(b["z_hi_m"]) - float(b["z_lo_m"])) / _SUB_CELLS for b in boxes
    ) if boxes else base_m
    dt_cfl = 1.0 / (_C0 * math.sqrt(2.0 / base_m**2 + 1.0 / dz**2))
    window_ns = 2.0 / fc_hz / 1e-9  # 高斯激励时长量级（2/FC，占位口径）
    nrts_effective = (
        int(nrts_explicit) if nrts_explicit is not None else _NRTS_OFFICIAL_DEFAULT)
    return {
        "estimation": "placeholder_lower_bound",
        "dt_cfl_upper_bound_s": dt_cfl,
        "grid_basis": {"axis_m": base_m, "dz_m": dz, "sub_cells": _SUB_CELLS},
        "window_ns_placeholder": window_ns,
        "nrts_lower_bound": math.ceil(window_ns * 1e-9 / dt_cfl),
        "nrts_effective": nrts_effective,
        "nrts_basis": "explicit" if nrts_explicit is not None else "official_default",
        "note": "真预算必须按终网格最小格 CFL 实算（#328/#312）；"
                "本占位按 base 网格 courant=1.0 上界给出步数下界，不回写脚本 NrTS",
    }


# ---------------------------------------------------------------------------
# 主入口（JSON 信封，ok=False 不抛）
# ---------------------------------------------------------------------------


def layout_sim_prepare(payload: dict[str, Any]) -> dict[str, Any]:
    """版图仿真准备（离线面）：组装完整 openEMS render_script 文本 + 发射面注记。

    输入 payload::

        {
          "stackup": {...},            # 必填，P1 RFStackup dict（stackup_from_dict 形态）
          "material_props": {"<介质层名>": {"epsilon_r": .., "loss_tangent": ..}},
          "layout": {...},             # 几何段 spec 二选一：B2 版图载荷
          "primitives": [...],         #   或 P1 渲染原语直通（米制，契约形态）
          "ports": [...] | {"port_table": [...], "marker_layer": "..."},
          "sim": {"f0_ghz": .., "fc_ghz": ..,          # 必填
                  "mesh_base_mm": ..|null, "nrts": ..|null,
                  "excite_port": 1, "z_ref_ohm": 50.0,
                  "domain_pad_mm": 10.0},
          "oe_bin_dir": "..." | null   # 可选，发射脚本 bin PATH 注入
        }

    成功信封::

        {"ok": True, "schema_version", "engine": "openEMS", "zero_solve": True,
         "render_script", "artifacts": [...], "budget": {...},
         "ports": {"source", "advisory", "n_ports", "pin_dicts"},
         "geometry": {"n_primitives", "n_metal_layers", "n_hole_cuts",
                       "unmatched_layers", "stackup_layers_unused"},
         "provenance": {...}}

    失败信封 ``{"ok": False, "errors": [...]}``——任何输入/组装错误都不抛出。
    """
    try:
        payload = _require_payload_dict(payload)
        errors: list[str] = []
        stackup_data = payload.get("stackup")
        layout_data = payload.get("layout")
        ports_spec = payload.get("ports")
        sim = payload.get("sim")
        if stackup_data is None:
            errors.append("payload 缺 stackup")
        if layout_data is None and payload.get("primitives") is None:
            errors.append("payload 缺几何段 spec（layout 或 primitives 二选一）")
        if ports_spec is None:
            errors.append("payload 缺 ports")
        if not isinstance(sim, dict):
            errors.append("payload 缺 sim（f0_ghz/fc_ghz 必填）")
        if errors:
            return error_envelope(errors, )
        assert sim is not None
        f0_hz = _require_number(sim.get("f0_ghz"), "sim.f0_ghz") * 1e9
        fc_hz = _require_number(sim.get("fc_ghz"), "sim.fc_ghz") * 1e9
        if fc_hz <= 0.0:
            raise ValueError(f"sim.fc_ghz 必须为正: {sim.get('fc_ghz')!r}")
        excite_port = int(sim.get("excite_port", 1) or 1)
        z_ref = _require_number(sim.get("z_ref_ohm", 50.0), "sim.z_ref_ohm")
        if z_ref <= 0.0:
            raise ValueError(f"sim.z_ref_ohm 必须为正: {z_ref!r}")
        pad_m = _require_number(
            sim.get("domain_pad_mm", _DOMAIN_PAD_DEFAULT_MM),
            "sim.domain_pad_mm") * 1e-3
        if pad_m <= 0.0:
            raise ValueError(f"sim.domain_pad_mm 必须为正: {sim.get('domain_pad_mm')!r}")
        nrts_explicit = sim.get("nrts")
        if nrts_explicit is not None:
            nrts_explicit = int(nrts_explicit)
            if nrts_explicit <= 0:
                raise ValueError(f"sim.nrts 必须为正整数: {sim.get('nrts')!r}")

        stackup = stackup_from_dict(stackup_data)
        raw_props = payload.get("material_props")
        if not isinstance(raw_props, dict):
            raise ValueError("payload 缺 material_props（介质层名 → 数值映射）")
        material_props = {
            str(k): MaterialProps(
                epsilon_r=_require_number(v.get("epsilon_r"), f"material_props[{k!r}].epsilon_r"),
                loss_tangent=_require_number(v.get("loss_tangent"), f"material_props[{k!r}].loss_tangent"),
            )
            for k, v in raw_props.items()
        }
        primitives, geo_info = _resolve_geometry(payload, stackup)
        if not primitives:
            raise ValueError(
                "版图无匹配几何（n_primitives=0）——检查叠层选择器与版图层名"
                f"（unmatched={geo_info['unmatched_layers']}）")
        if geo_info["source"] == "layout_bridge":
            assert layout_data is not None
            layout = layout_from_payload(layout_data)
            ports_res = _normalize_ports(layout, ports_spec)
        else:
            # primitives 直通面：无 B2 版图对象，端口只接受显式记录表
            # （marker/启发式通道需要版图几何，天然不可用）
            table = (ports_spec if isinstance(ports_spec, list)
                     else ports_spec.get("port_table")
                     if isinstance(ports_spec, dict) else None)
            if not isinstance(table, list):
                raise ValueError(
                    'primitives 直通面的 ports 只接受记录列表或 '
                    '{"port_table": [...]}（marker/启发式需要版图几何）')
            ports_res = {
                "ports": port_table_from_records(table),
                "source": "yaml", "advisory": False,
                "cross_check": {"marker_vs_yaml": None, "heuristic": None},
                "stats": {"enabled_sources": ["yaml"]},
            }
        ports = ports_res["ports"]
        specs = _validate_ports_for_emission(ports, stackup)
        if not 1 <= excite_port <= len(specs):
            raise ValueError(
                f"sim.excite_port={excite_port} 超出端口范围 1..{len(specs)}")

        boxes = plan_substrate_boxes(stackup, material_props)
        groups = {b["prop"] for b in boxes}
        n_material_groups = len(groups)
        if n_material_groups > 1 and any(p.get("holes") for p in primitives):
            raise ValueError(
                "多介质材料组叠层且版图图元带孔洞——孔洞切除基板属性归属不唯一"
                "（v1 边界，见模块 docstring 诚实边界 2）")

        # 金属面 z 升序 → priority 递增，标注进原语（桥产物 dict 为本次组装
        # 新建对象，就地标注不外泄共享状态）
        metal_zs_stack = sorted({
            float(lay.zmin_m) for lay in stackup.layers
            if lay.kind in ("signal", "ground")})
        z_rank = {z: _PRIORITY_BASE + i for i, z in enumerate(metal_zs_stack)}
        for prim in primitives:
            prim["priority"] = z_rank[float(prim["zmin_m"])]

        # 域与网格（对称域：±DOM 以原点为中心，openems_templates 同款）
        xs = [x for p in primitives for x, _ in p["coords"]]
        ys = [y for p in primitives for _, y in p["coords"]]
        for spec in specs:
            xs.append(float(spec["port"].position_m[0]))
            ys.append(float(spec["port"].position_m[1]))
        dom_x = max(abs(min(xs)), abs(max(xs))) + pad_m
        dom_y = max(abs(min(ys)), abs(max(ys))) + pad_m
        z_lo = min([float(b["z_lo_m"]) for b in boxes]
                   + [float(s["start"][2]) for s in specs]) - pad_m
        z_hi = max([float(b["z_hi_m"]) for b in boxes]
                   + [float(s["z_metal_m"]) for s in specs]) + pad_m

        f_max = f0_hz + fc_hz
        er_max = max(float(b["epsilon_r"]) for b in boxes)
        base_mm = sim.get("mesh_base_mm")
        if base_mm is not None:
            base_m = _require_number(base_mm, "sim.mesh_base_mm") * 1e-3
            if base_m <= 0.0:
                raise ValueError(f"sim.mesh_base_mm 必须为正: {base_mm!r}")
            base_basis = "explicit"
        else:
            base_m = _C0 / (f_max * math.sqrt(er_max)) / 50.0
            base_basis = "auto_lambda_sub_over_50"
        near_m = base_m / _NEAR_RATIO
        hints = [
            float(p["mesh_hint_mm"]) * 1e-3
            for p in primitives if p.get("mesh_hint_mm") is not None
        ]
        near_basis = "official_base_over_4"
        if hints:
            near_hint = min(hints)
            if near_hint < near_m:
                near_m = near_hint
                near_basis = "min_mesh_hint_mm"

        substrate_var = "sub"
        substrate_block = render_substrate_block(
            stackup, material_props,
            x_lo="-DOM_X", x_hi="DOM_X", y_lo="-DOM_Y", y_hi="DOM_Y")
        substrate_mesh_block = render_substrate_mesh_block(stackup, material_props)
        metal_block, metal_var_map, n_cuts = _emit_metal_geometry(
            primitives, substrate_var, n_material_groups)
        metal_zs = sorted({float(s["z_metal_m"]) for s in specs}
                          | {float(p["zmin_m"]) for p in primitives})
        port_block = _emit_ports(specs, excite_port)

        script = "".join([
            _emit_header(payload.get("oe_bin_dir")),
            _emit_constants(f0_hz, fc_hz, base_m, near_m,
                            nrts_explicit if nrts_explicit is not None
                            else _NRTS_OFFICIAL_DEFAULT),
            _emit_domain(dom_x, dom_y, z_lo, z_hi),
            "\n",
            "# ── 基板段（P2 render_substrate_block 产物逐字节拼入，#329）──\n",
            substrate_block,
            "\n",
            "# ── 网格段（介质界面 z 线 = P2 mesh block 逐字节拼入；其余官方配方）──\n",
            substrate_mesh_block,
            _emit_mesh(
                [float(s["port"].position_m[0]) for s in specs],
                [float(s["port"].position_m[1]) for s in specs],
                metal_zs),
            metal_block,
            f"R_PORT = {z_ref!r}\n\n",
            port_block,
            _emit_run_and_extract(excite_port, z_ref),
        ])
        script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()

        artifacts = [
            {"name": "simulation.py", "kind": "render_script",
             "bytes": len(script.encode("utf-8")), "sha256": script_sha},
            {"name": "_rfauto_runner.py", "kind": "runner_shim",
             "conditional": True,
             "note": "openems_solver 求解期按 exe_path 生成（DLL 目录注入引导）"},
            {"name": "sparams.csv", "kind": "expected_output",
             "columns": ["freq_hz", "re_S11", "im_S11"]},
            {"name": "fdtd/", "kind": "engine_workdir",
             "note": "openEMS 引擎自管工作目录（FDTD.Run(SIM_PATH)）"},
        ]
        warnings: list[str] = []
        # 噪声过滤：marker 通道的标记层名出现在 unmatched 是预期（标记几何
        # 本就不该渲染成金属）；介质层永远不经版图匹配消费（走基板 Box）。
        bridge_stats = geo_info["bridge_stats"]
        marker_name = (ports_spec.get("marker_layer")
                       if isinstance(ports_spec, dict) else None)
        unmatched_noise = {marker_name} if marker_name else set()
        real_unmatched = [n for n in geo_info["unmatched_layers"]
                          if n not in unmatched_noise]
        if real_unmatched:
            warnings.append(
                f"版图层未匹配叠层（几何被跳过）: {real_unmatched}")
        conductor_unused = [
            name for name in (bridge_stats or {}).get("stackup_layers_unused", [])
            if (lay := next((candidate for candidate in stackup.layers
                             if candidate.name == name), None))
            is not None and lay.kind in ("signal", "ground")
        ]
        if conductor_unused:
            warnings.append(
                f"叠层导体层未被任何版图层命中: {conductor_unused}")
        if (bridge_stats or {}).get("skipped_vias"):
            warnings.append(
                f"过孔 v1 跳过未渲染（n={bridge_stats['skipped_vias']}，P1 桥边界）")
        if ports_res["advisory"]:
            warnings.append("端口来自启发式候选（advisory）——建议改显式来源复核")

        budget = _budget_annotation(boxes, base_m, f0_hz, fc_hz, nrts_explicit)
        return ok_envelope(
            schema_version=LAYOUT_SIM_SERVICE_SCHEMA_VERSION,
            engine=_ENGINE,
            zero_solve=True,
            render_script=script,
            artifacts=artifacts,
            budget=budget,
            ports={
                "source": ports_res["source"],
                "advisory": ports_res["advisory"],
                "n_ports": len(ports),
                "pin_dicts": [p.to_pin_dict() for p in ports],
            },
            geometry={
                "n_primitives": len(primitives),
                "n_metal_layers": len(metal_var_map),
                "metal_var_map": metal_var_map,
                "n_hole_cuts": n_cuts,
                "n_material_groups": n_material_groups,
                "source": geo_info["source"],
                "unmatched_layers": geo_info["unmatched_layers"],
                "stackup_layers_unused": (bridge_stats or {}).get(
                    "stackup_layers_unused", []),
            },
            provenance={
                "schema_version": LAYOUT_SIM_SERVICE_SCHEMA_VERSION,
                "engine": _ENGINE,
                "zero_solve": True,
                "component_versions": {
                    "primitive_schema": PRIMITIVE_SCHEMA_VERSION,
                    "plan_substrate": PLAN_SUBSTRATE_VERSION,
                },
                "script_sha256": script_sha,
                "mesh": {"base_mm": base_m * 1e3, "base_basis": base_basis,
                         "near_mm": near_m * 1e3, "near_basis": near_basis},
                "sim": {"f0_ghz": f0_hz / 1e9, "fc_ghz": fc_hz / 1e9,
                        "excite_port": excite_port, "z_ref_ohm": z_ref,
                        "domain_pad_mm": pad_m * 1e3,
                        "nrts": nrts_explicit if nrts_explicit is not None
                        else _NRTS_OFFICIAL_DEFAULT},
                "ports": {"source": ports_res["source"],
                          "advisory": ports_res["advisory"],
                          "cross_check": ports_res["cross_check"],
                          "stats": ports_res["stats"],
                          "pin_contract_keys": list(COMPOSE_PIN_KEYS)},
                "geometry": {"n_primitives": len(primitives),
                             "n_hole_cuts": n_cuts,
                             "n_material_groups": n_material_groups},
                "boundaries": [
                    "v1 端口只发 LumpedPort（msl 属 P3 真机窗，#347）；"
                    "参考地规则：下方 ground→垂直，共面 ground→面内（方向轴对齐）",
                    "v1 单激励 S11；整 S 矩阵 = N×单激励装配（#208）",
                    "v1 域对称 + 全 MUR 边界；PEC 底板/PML 端口轴精化属真机窗",
                    "预算 NrTS 为占位下界；真预算按终网格最小格 CFL 实算（#328/#312）",
                ],
                "warnings": warnings,
            },
        )
    except Exception as exc:  # 信封契约：任何输入/组装错误 ok=False 不抛（规则 4）
        return error_envelope([f"{type(exc).__name__}: {exc}"])
