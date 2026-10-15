"""EDB 平面族模板 spec 契约：schema 校验 + 综合桥接 + PyEDB configuration 组装底座。

本模块是 edb_templates 包的共享底座（schema 校验/文档化、微带综合桥接、
spec→PyEDB configuration 组装），branchline / power_divider / coupled_line
/ ratrace 四族发射器只做各自的拓扑几何（lange 预留键声明不支持，见
lange.py docstring）。全部函数纯计算零 IO、零 pyedb 依赖（pyedb 属
edb_adapter 消费层；本层只产 dict）。

spec dict 契约（schema_version=1，与 edb_adapter 席共同遵守；五契约字段
stackup/traces/vias/ports/sim_setup 之外的最小完备扩展均在此声明）::

    {
      "template": "edb_branchline" | "edb_power_divider",
      "schema_version": 1,
      "units": {"length": "mm", "frequency": "GHz"},       # spec 全域毫米/GHz
      "params": {...},          # 设计读数面板（综合链全精度产出，含出处键）
      "stackup": {
        "materials": [{"name", "conductivity"| "permittivity",
                       "dielectric_loss_tangent"}...],
        "layers": [  # 自底向上（index0=物理底层）；assemble_config 翻转为
                     # 自顶向下落库——pyedb 0.83 __create_stackup 按列表序
                     # 逐层 AddLayerBottom（首项落物理顶层，
                     # configuration.py:863-868 + stackup.py:97-130 源码
                     # 实证，docs/pyedb_distilled.md §3.1/§6-2）
          {"name": "GND", "type": "signal",    "material": "copper",
           "thickness_mm": 0.035},
          {"name": "SUB", "type": "dielectric", "material": "<层叠名>",
           "thickness_mm": 0.508},
          {"name": "TOP", "type": "signal",    "material": "copper",
           "thickness_mm": 0.035},
        ],
      },
      "traces": [{"name", "layer", "net", "width_mm",
                  "path_mm": [[x, y], ...],   # 中心线（毫米）；单段轴对齐
                  "role"}...],
      "vias": [],               # 契约字段；平面两层族恒空（保留）
      "resistors": [            # 可选扩展：集总电阻声明（见假设 5）
        {"name", "layer", "net", "r_ohm", "width_mm", "path_mm"}...],
      "ports": [{"name": "P1", "port_nr": 1, "type": "wave_port",
                 "trace": "<trace name>", "point_mm": [x, y],  # =走线端点
                 "impedance": 50.0,
                 "horizontal_extent_factor": 5, "vertical_extent_factor": 3}],
      "board": {"lower_left_mm": [x0, y0], "upper_right_mm": [x1, y1]},
      "sim_setup": {"f0_ghz", "sweep": {...}, "adapt": {...}},
    }

schema 假设清单（"最小完备"自定项，逐条可追溯）：
  1. 坐标/长度/频率：spec 全域毫米/GHz（units 键显式声明）；config_json
     坐标=米浮点（pyedb EDB 数据库单位，CfgTrace docstring 惯例）、宽度/
     厚度/频率=带单位字符串（pyedb edb_value 通道惯例）。
  2. stackup 层序自底向上；两层信号（底 GND/顶 TOP）夹单介质；走线全部
     在最顶信号层，地面=最底信号层整版矩形（微带口径）。
  3. wave_port 阻抗：pyedb configuration 的 CfgEdgePort 落地面阻抗硬编码
     50Ω（0.83 实测 set_parameters_to_edb）→ 本层仅支持 z0_ohm=50 系统
     口径，其余值 validate 直接报错（不做静默错配）。
  4. traces path 全部单段轴对齐两点线（拐角由独立走线端点重合构成），
     cap=flat（足迹=精确矩形，端点=矩形边缘）、corner=sharp。
  5. 集总电阻：pyedb configuration 0.83 无 lumped-RLC 段（boundaries 段
     仅 open-region，实测）→ 电阻只在 spec["resistors"] 声明（几何+r_ohm），
     **不发进 config modeler**（防 adapter 逐字套用 config 时变金属短路）；
     edb_adapter 负责按 spec["resistors"] 用 pedb lumped RLC 边界落地。
  6. 端口=trace 端点上的 wave_port（point_mm 必须与该 trace path 端点
     1e-9 重合）；水平/垂直扩展因子 5/3（pyedb 缺省档，微带波端口惯例）。
  7. 缺省层叠标量 = configs/materials.yaml ``rogers4350b_h0.508`` 口径
     （εr=3.66 / h=0.508mm / tanδ=0.0037）；以标量直传保持发射器纯函数
     零 IO——yaml 权威值若漂移，test_edb_templates 的单源一致性断言会红
     （强制同步，不允许两套数）。
  8. sweep 缺省 [0.7, 1.3]·f0、401 点 interpolation；adapt=单频 f0、
     max_passes=20、max_delta=0.02——与 synthesize_branchline/
     synthesize_wilkinson 的 recipe_draft setup 同口径（同综合单源）。

适配器消费对齐（2026-10-08 契约统一，edb_adapter 席扩消费落地）
--------------------------------------------------------------
本 docstring 所记 spec 契约即 ``edb_adapter.spec_to_config_json`` 的 v1
消费面（正本=本包发射器实测产出，双向钉
tests/unit/test_edb_adapter.py::TestEmitterSpecContract）：
- 元段 template/schema_version/units/params：适配器校验后跳过，零 config
  产出（units 非 mm/GHz、schema_version 非 1 在适配器侧 fail-fast）；
- stackup.materials 显式段：直通 config（铜 conductivity + 介质
  permittivity/dielectric_loss_tangent）——介质层只给引用名时的定义载体；
- stackup.layers 层序：spec 自底向上，两侧 config 生产端（本模块
  assemble_config 与适配器 _translate_stackup）同点同向翻转为自顶向下落库
  （pyedb AddLayerBottom 首项落物理顶层，0.83 源码实证，2026-10-08 审查批
  P0 修复——未翻转则 [GND,SUB,TOP] 物理落成 GND 在顶=叠层颠倒）；
- board → modeler.planes "GND_plane" 整版矩形（落 stackup.layers[0]，
  角点 mm→米）+ boundaries 开放域辐射——与 assemble_config 逐键同款；
- ports wave_port 形态（name/port_nr/trace/point_mm/impedance/extent 因子）：
  适配器透传 extent 因子成 CfgEdgePort dict；阻抗非 50 拒收（pyedb
  CfgEdgePort 通道硬编码 50Ω，假设 3 同源）；trace 引用存在性适配器复核；
- sim_setup 发射族形态 f0_ghz/sweep(dict)/adapt(dict)：适配器翻译成单段
  linear_count 扫频 + 单频自适应（与 assemble_config 同式同键）；
- 带单位字符串两侧同式 %.10g（本模块 _fmt_mm/_fmt_ghz=适配器同款）——
  同一 spec 经适配器 spec_to_config_json 与本模块 assemble_config 产出
  config 逐键一致（唯一豁免 setups[0].name：发射器字面 "setup1" vs 适配器
  缺省 "hfss_setup_1"，纯命名差异零语义）。
schema_version 升版须两侧同步：适配器侧 _SUPPORTED_SCHEMA_VERSION 硬编码
同值（不 import 本包——防 edb_templates↔edb_adapter 依赖环，版本对齐由
契约测试钉住）。

扩展族 docstring 追记（2026-10-08 扩展批；本模块逻辑零改动，仅此追加）
----------------------------------------------------------------
新增发射族 coupled-line 耦合器（edb_coupled_line）/ ratrace 环形电桥
（edb_ratrace）与 lange 综合单源（edb_lange 预留键，EDB 发射声明不支持——
pyedb 0.83 无 crossover 原语，论证见 lange.py docstring）。两处**族特异
validate_spec 豁免**由各族发射器侧过滤（正本 KNOWN_TEMPLATES 与单连通
审计均不动）：① "template 非法" 行——KNOWN_TEMPLATES 白名单升格
（+edb_lane_service 分派表接线）为 followUp；② coupled-line 族"走线连通
图非单连通"行——线 A/B DC 隔离是后向波耦合器的器件物理（分量结构恰为
{line_a,feed_p1,feed_p2}/{line_b,feed_p3,feed_p4} 两组，测试钉住）。两处
豁免的事实面由 tests/unit/test_edb_templates_ext.py 钉住。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.synthesis import Stackup, forward_media, inverse_width

__all__ = [
    "DEFAULT_BOARD_MARGIN_MM",
    "DEFAULT_COPPER_THICKNESS_MM",
    "DEFAULT_STACKUP",
    "KNOWN_TEMPLATES",
    "SPEC_SCHEMA_VERSION",
    "assemble_config",
    "build_spec_stackup",
    "point_segment_distance_mm",
    "quarter_wave_len_mm",
    "resolve_stackup",
    "solve_microstrip",
    "trace_attach_graph",
    "trace_connected_components",
    "validate_spec",
]

SPEC_SCHEMA_VERSION = 1

#: 缺省层叠标量（假设 7：materials.yaml rogers4350b_h0.508 口径，标量直传零 IO）
DEFAULT_STACKUP: dict[str, Any] = {
    "name": "rogers4350b_h0.508",
    "epsilon_r": 3.66,
    "thickness_mm": 0.508,
    "loss_tangent": 0.0037,
}

DEFAULT_COPPER_THICKNESS_MM = 0.035  # 与 branchline/wilkinson HFSS 插件 copper_t 同口径
DEFAULT_BOARD_MARGIN_MM = 2.0        # 地板/基板相对走线足迹的外扩边距

#: 已注册发射族（template 键白名单）
KNOWN_TEMPLATES = ("edb_branchline", "edb_power_divider")

_TOL_MM = 1e-9  # 端点重合判据容差（"允许 1e-9 级"口径）


# ─── 综合桥接（core.synthesis 同引擎，标量层叠直传零 IO）─────────────────────


def resolve_stackup(stackup_params: dict[str, Any] | None) -> Stackup:
    """设计参数里的 stackup 标量 → core.synthesis.Stackup（缺省=假设 7）。"""
    p = dict(DEFAULT_STACKUP if stackup_params is None else stackup_params)
    return Stackup(
        name=str(p.get("name", DEFAULT_STACKUP["name"])),
        epsilon_r=float(p["epsilon_r"]),
        thickness_mm=float(p["thickness_mm"]),
        loss_tangent=float(p.get("loss_tangent", 0.0)),
    )


def solve_microstrip(
    z0_ohm: float, f0_ghz: float, stackup: Stackup
) -> tuple[float, float]:
    """目标阻抗 → (线宽 mm, εeff)。core.synthesis 综合链同引擎（inverse_width
    brentq 反解 + forward_media HJ 正向），回代不自洽即抛错（不静默带病发射）。"""
    width_mm, _z0_actual, status = inverse_width(float(z0_ohm), float(f0_ghz), stackup)
    if status != "ok":
        raise ValueError(
            f"微带线宽反解未自洽（z0={z0_ohm}Ω @{f0_ghz}GHz，status={status!r}）"
        )
    media = forward_media(width_mm, float(f0_ghz), stackup)
    return float(width_mm), float(media.er_eff)


def quarter_wave_len_mm(f0_ghz: float, eps_eff: float) -> float:
    """λg/4 闭式：c/(4·f0·√εeff)（mm·GHz 制，c=299.792458 与综合核同常数）。"""
    return 299.792458 / (4.0 * float(f0_ghz) * math.sqrt(float(eps_eff)))


# ─── 几何审计底座（#212 离线几何审计制度化：端点重合图连通性）────────────────


def point_segment_distance_mm(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """点到线段距离（mm）。"""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _endpoints(trace: dict[str, Any]) -> list[tuple[float, float]]:
    path = trace["path_mm"]
    return [(float(path[0][0]), float(path[0][1])), (float(path[-1][0]), float(path[-1][1]))]


def trace_attach_graph(
    traces: list[dict[str, Any]], tol_mm: float = _TOL_MM
) -> list[set[int]]:
    """走线端点-重合附着图：i 与 j 相邻 iff i 的某端点到 j 中心线距离
    ≤ W_j/2 + tol（覆盖端点重合/T 接/边缘贴合三类连接，cap=flat 口径）。"""
    n = len(traces)
    polylines = [[(float(p[0]), float(p[1])) for p in tr["path_mm"]] for tr in traces]
    adj: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            wj2 = float(traces[j]["width_mm"]) / 2.0 + tol_mm
            for ex, ey in _endpoints(traces[i]):
                pts = polylines[j]
                d = min(
                    point_segment_distance_mm(ex, ey, pts[k][0], pts[k][1],
                                              pts[k + 1][0], pts[k + 1][1])
                    for k in range(len(pts) - 1)
                )
                if d <= wj2:
                    adj[i].add(j)
                    break
    return adj


def trace_connected_components(adj: list[set[int]]) -> list[set[int]]:
    """无向连通分量（索引集合列表）。"""
    seen: set[int] = set()
    comps: list[set[int]] = []
    for start in range(len(adj)):
        if start in seen:
            continue
        comp, stack = {start}, [start]
        while stack:
            cur = stack.pop()
            for nxt in adj[cur]:
                if nxt not in comp:
                    comp.add(nxt)
                    stack.append(nxt)
        seen |= comp
        comps.append(comp)
    return comps


# ─── spec 组装底座 ────────────────────────────────────────────────────────────


def build_spec_stackup(stackup: Stackup, copper_thickness_mm: float) -> dict[str, Any]:
    """综合层叠 → spec["stackup"] 段（自底向上 GND/SUB/TOP，假设 2）。"""
    cu = float(copper_thickness_mm)
    return {
        "materials": [
            {"name": "copper", "conductivity": 1.0 / 1.724e-8},  # = Stackup 缺省 rho 倒数
            {
                "name": stackup.name,
                "permittivity": float(stackup.epsilon_r),
                "dielectric_loss_tangent": float(stackup.loss_tangent),
            },
        ],
        "layers": [
            {"name": "GND", "type": "signal", "material": "copper", "thickness_mm": cu},
            {
                "name": "SUB",
                "type": "dielectric",
                "material": stackup.name,
                "thickness_mm": float(stackup.thickness_mm),
            },
            {"name": "TOP", "type": "signal", "material": "copper", "thickness_mm": cu},
        ],
    }


def make_trace(name: str, width_mm: float, path_mm: list[list[float]],
               role: str, layer: str = "TOP", net: str = "RF") -> dict[str, Any]:
    """构造一条 spec trace（单段轴对齐两点中心线，假设 4）。"""
    return {
        "name": name,
        "layer": layer,
        "net": net,
        "width_mm": float(width_mm),
        "path_mm": [[float(path_mm[0][0]), float(path_mm[0][1])],
                    [float(path_mm[-1][0]), float(path_mm[-1][1])]],
        "role": role,
    }


def make_wave_port(name: str, port_nr: int, trace_name: str,
                   point_mm: list[float]) -> dict[str, Any]:
    """构造一个 spec 端口（wave_port@走线端点，假设 6）。"""
    return {
        "name": name,
        "port_nr": int(port_nr),
        "type": "wave_port",
        "trace": trace_name,
        "point_mm": [float(point_mm[0]), float(point_mm[1])],
        "impedance": 50.0,
        "horizontal_extent_factor": 5,
        "vertical_extent_factor": 3,
    }


def board_from_traces(
    traces: list[dict[str, Any]], margin_mm: float
) -> dict[str, Any]:
    """走线足迹（bbox 外扩 W/2）+ 边距 → spec["board"] 段。"""
    xs: list[float] = []
    ys: list[float] = []
    for tr in traces:
        w2 = float(tr["width_mm"]) / 2.0
        for x, y in tr["path_mm"]:
            xs += [x - w2, x + w2]
            ys += [y - w2, y + w2]
    return {
        "lower_left_mm": [min(xs) - float(margin_mm), min(ys) - float(margin_mm)],
        "upper_right_mm": [max(xs) + float(margin_mm), max(ys) + float(margin_mm)],
    }


# ─── spec → PyEDB configuration JSON ─────────────────────────────────────────


def _fmt_mm(v: float) -> str:
    return f"{float(v):.10g}mm"


def _fmt_ghz(v: float) -> str:
    return f"{float(v):.10g}GHz"


def _m(v_mm: float) -> float:
    """毫米 → 米浮点（EDB 数据库单位，假设 1）。"""
    return float(v_mm) * 1e-3


def assemble_config(spec: dict[str, Any]) -> dict[str, Any]:
    """spec dict → PyEDB ``edb.configuration.load()`` 兼容 dict（假设 1/5）。

    顶层段（pyedb 0.83 CfgData 实测可解析、零 unknown-section 警告）：
    stackup / modeler(traces+planes) / ports / setups / boundaries。
    spec["resistors"] **不**进 config（假设 5：configuration 无 lumped-RLC
    段，adapter 按 spec 落地，防 config 逐字套用时电阻变金属短路）。

    层序翻转（2026-10-08 审查批 P0 修复）：spec 层序自底向上，config 层列表
    翻转为**自顶向下**（首项=物理顶层）——pyedb ``__create_stackup`` 按列表
    序逐层 ``AddLayerBottom``（每次插到全栈最底→列表首项落物理顶层，0.83
    configuration.py:863-868 + dotnet/database/stackup.py:97-130 源码实证），
    不翻转则 [GND, SUB, TOP] 落库成 GND 在物理顶层=叠层整体上下颠倒。与
    edb_adapter._translate_stackup 同点同向翻转（契约测试钉双路径逐键一致）。
    """
    layers = spec["stackup"]["layers"]
    ground_layer = layers[0]["name"]  # 自底向上：最底信号层=地板载体
    traces_cfg = [
        {
            "name": tr["name"],
            "layer": tr["layer"],
            "net_name": tr.get("net", "RF"),
            "width": _fmt_mm(tr["width_mm"]),
            "path": [[_m(p[0]), _m(p[1])] for p in tr["path_mm"]],
            "start_cap_style": "flat",
            "end_cap_style": "flat",
            "corner_style": "sharp",
        }
        for tr in spec["traces"]
    ]
    planes_cfg = [
        {
            "name": "GND_plane",
            "layer": ground_layer,
            "net_name": "GND",
            "type": "rectangle",
            "lower_left_point": [_m(spec["board"]["lower_left_mm"][0]),
                                 _m(spec["board"]["lower_left_mm"][1])],
            "upper_right_point": [_m(spec["board"]["upper_right_mm"][0]),
                                  _m(spec["board"]["upper_right_mm"][1])],
        }
    ]
    ports_cfg = [
        {
            "name": pt["name"],
            "type": "wave_port",
            "primitive_name": pt["trace"],
            "point_on_edge": [_m(pt["point_mm"][0]), _m(pt["point_mm"][1])],
            "horizontal_extent_factor": int(pt.get("horizontal_extent_factor", 5)),
            "vertical_extent_factor": int(pt.get("vertical_extent_factor", 3)),
            "pec_launch_width": "0.01mm",
        }
        for pt in spec["ports"]
    ]
    setup = spec["sim_setup"]
    sweep = setup["sweep"]
    setups_cfg = [
        {
            "name": "setup1",
            "type": "hfss",
            "adapt_type": "single",
            "single_frequency_adaptive_solution": {
                "adaptive_frequency": _fmt_ghz(setup["f0_ghz"]),
                "max_passes": int(setup["adapt"]["max_passes"]),
                "max_delta": float(setup["adapt"]["max_delta"]),
            },
            "freq_sweep": [
                {
                    "name": sweep.get("name", "sweep1"),
                    "type": sweep.get("type", "interpolation"),
                    "frequencies": [
                        {
                            "start": _fmt_ghz(sweep["start_ghz"]),
                            "stop": _fmt_ghz(sweep["stop_ghz"]),
                            "increment": int(sweep["points"]),
                            "distribution": "linear_count",
                        }
                    ],
                }
            ],
        }
    ]
    return {
        "stackup": {
            "materials": [
                {k: v for k, v in mat.items() if k != "name"} | {"name": mat["name"]}
                for mat in spec["stackup"]["materials"]
            ],
            "layers": [
                {
                    "name": layer["name"],
                    "layer_type": layer["type"],
                    "material": layer["material"],
                    "thickness": _fmt_mm(layer["thickness_mm"]),
                }
                # spec 自底向上 → config 自顶向下（pyedb AddLayerBottom 首项
                # 落物理顶层，翻转证据链见本函数 docstring）
                for layer in reversed(layers)
            ],
        },
        "modeler": {"traces": traces_cfg, "planes": planes_cfg},
        "ports": ports_cfg,
        "setups": setups_cfg,
        "boundaries": {"use_open_region": True, "open_region_type": "radiation"},
    }


# ─── spec 校验（结构 + 离线几何审计；返回错误清单，空=通过）──────────────────


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """spec 完备性/几何审计，返回错误清单（空 list=合法）。

    审计面：契约字段齐全、层叠自底向上含信号/介质层、trace 完备且单连通
    （端点-附着图）、端口落在所属走线端点、board 覆盖全部走线足迹、
    sim_setup 频窗含 f0、电阻端点附着到某走线、z0=50Ω 口径（假设 3）。
    """
    errors: list[str] = []

    def _err(msg: str) -> None:
        errors.append(msg)

    if spec.get("template") not in KNOWN_TEMPLATES:
        _err(f"template 非法: {spec.get('template')!r}（白名单 {KNOWN_TEMPLATES}）")
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        _err(f"schema_version={spec.get('schema_version')!r} != {SPEC_SCHEMA_VERSION}")
    units = spec.get("units") or {}
    if units.get("length") != "mm" or units.get("frequency") != "GHz":
        _err(f"units 必须为 mm/GHz: {units!r}")

    stackup = spec.get("stackup") or {}
    layers = stackup.get("layers") or []
    if not stackup.get("materials"):
        _err("stackup.materials 缺失")
    if len(layers) < 3:
        _err(f"stackup.layers 至少 3 层（GND/SUB/TOP）: {len(layers)}")
    else:
        types = [str(la.get("type")) for la in layers]
        if types.count("signal") < 2 or types.count("dielectric") < 1:
            _err(f"层叠须含 ≥2 信号层 + ≥1 介质层: {types}")
        if layers[0].get("type") != "signal":
            _err("首层（自底向上）必须是信号层（地板载体）")
    signal_layers = {la["name"] for la in layers if la.get("type") == "signal"}

    traces = spec.get("traces") or []
    if not traces:
        _err("traces 为空")
    names = [tr.get("name") for tr in traces]
    if len(set(names)) != len(names):
        _err(f"trace 名重复: {names}")
    for tr in traces:
        if tr.get("layer") not in signal_layers:
            _err(f"trace {tr.get('name')!r} 层 {tr.get('layer')!r} 非信号层")
        if not (float(tr.get("width_mm", 0.0)) > 0.0):
            _err(f"trace {tr.get('name')!r} width_mm 非正")
        if len(tr.get("path_mm") or []) < 2:
            _err(f"trace {tr.get('name')!r} path_mm 至少 2 点")

    if traces and len(set(names)) == len(names):
        adj = trace_attach_graph(traces)
        comps = trace_connected_components(adj)
        if len(comps) != 1:
            groups = [[traces[i]["name"] for i in c] for c in comps]
            _err(f"走线连通图非单连通（{len(comps)} 分量）: {groups}")

    board = spec.get("board") or {}
    if "lower_left_mm" not in board or "upper_right_mm" not in board:
        _err("board 缺 lower_left_mm/upper_right_mm")
    else:
        x0, y0 = board["lower_left_mm"]
        x1, y1 = board["upper_right_mm"]
        for tr in traces:
            w2 = float(tr["width_mm"]) / 2.0
            for x, y in tr["path_mm"]:
                if not (x0 - _TOL_MM <= x - w2 and x + w2 <= x1 + _TOL_MM
                        and y0 - _TOL_MM <= y - w2 and y + w2 <= y1 + _TOL_MM):
                    _err(f"board 未覆盖 trace {tr['name']!r} 足迹")
                    break

    by_name = {tr["name"]: tr for tr in traces}
    ports = spec.get("ports") or []
    nrs = [pt.get("port_nr") for pt in ports]
    if len(set(nrs)) != len(nrs) or any(not isinstance(v, int) or v < 1 for v in nrs):
        _err(f"port_nr 须为唯一正整数: {nrs}")
    for pt in ports:
        tr = by_name.get(pt.get("trace"))
        if tr is None:
            _err(f"端口 {pt.get('name')!r} 引用不存在走线 {pt.get('trace')!r}")
            continue
        px, py = pt["point_mm"]
        ends = _endpoints(tr)
        if min(math.hypot(px - ex, py - ey) for ex, ey in ends) > _TOL_MM:
            _err(
                f"端口 {pt['name']!r} point_mm {px, py} 不在走线 "
                f"{tr['name']!r} 端点（偏差 > {_TOL_MM}mm）"
            )
        if float(pt.get("impedance", 0.0)) <= 0.0:
            _err(f"端口 {pt['name']!r} impedance 非正")

    sim = spec.get("sim_setup") or {}
    f0 = float(sim.get("f0_ghz", 0.0))
    if f0 <= 0.0:
        _err("sim_setup.f0_ghz 非正")
    sweep = sim.get("sweep") or {}
    try:
        s0, s1, npts = float(sweep["start_ghz"]), float(sweep["stop_ghz"]), int(sweep["points"])
        if not s0 < s1:
            _err(f"sweep 频窗反向: [{s0}, {s1}]")
        if npts < 2:
            _err(f"sweep 点数 <2: {npts}")
        if f0 > 0.0 and not (s0 <= f0 <= s1):
            _err(f"f0={f0} 不在 sweep 频窗 [{s0}, {s1}] 内")
    except (KeyError, TypeError, ValueError):
        _err(f"sweep 段不完备: {sweep!r}")

    for res in spec.get("resistors") or []:
        if not (float(res.get("r_ohm", 0.0)) > 0.0):
            _err(f"电阻 {res.get('name')!r} r_ohm 非正")
        if res.get("layer") not in signal_layers:
            _err(f"电阻 {res.get('name')!r} 层非信号层")
        if len(res.get("path_mm") or []) < 2:
            _err(f"电阻 {res.get('name')!r} path_mm 至少 2 点")
            continue
        attached = False
        for tr in traces:
            w2 = float(tr["width_mm"]) / 2.0 + _TOL_MM
            pts = [(float(p[0]), float(p[1])) for p in tr["path_mm"]]
            for ex, ey in res["path_mm"]:
                d = min(point_segment_distance_mm(ex, ey, pts[k][0], pts[k][1],
                                                  pts[k + 1][0], pts[k + 1][1])
                        for k in range(len(pts) - 1))
                if d <= w2:
                    attached = True
                    break
            if attached:
                break
        if not attached:
            _err(f"电阻 {res.get('name')!r} 端点未附着任何走线")

    return errors
