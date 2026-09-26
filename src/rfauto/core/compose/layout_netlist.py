"""DP-8 几何组合引擎：netlist → 单一 simulation.py（布局合并路线，纯确定性）。

规格=docs/plan_deepdive_specs_20260924.md §DP-8；判据预声明
runs/df6_dp8compose/criteria.md。关键路线裁决（规格 §3）：**不做渲染文本
拼接**——实例契约拆为 layout(params, frame)→{pins, 图元, 域/板/守卫声明}
+ 引擎单一文本发射器（图元→CSXCAD 语句逐条渲染），杜绝 CSX/FDTD/mesh
头尾与守卫段的重复拼接。

分层（core 分层契约/.importlinter）：本模块属 core，零 I/O、零 adapters 依赖
——实例契约（布局/图元）由调用方（service/adapters）注入 ``contracts``；
pin schema（TEMPLATE_META[t]["port_pins"]）经 ``schema_map`` 注入做 opt-in
一致性校验。契约形态（adapters/openems_templates.py COMPOSE_CONTRACTS）::

    layout(params, freq_range_ghz, base_m, h_m, frame) -> {
        "pins": {pin_id: pin 字典},             # 已按 frame 仿射到全局
        "dom": (x0, y0, x1, y1),                # 实例域盒（全局）
        "bbox": (x0, y0, x1, y1),               # 结构盒（全局）
        "primitives": [图元字典...],            # box/polygon/cylinder/port
        "plates_top": [(x0, y0, x1, y1)...],    # z=H_SUB 显式顶板（D2 消费）
        "bottom_plate": (x0, y0, x1, y1),       # z=0 底板覆盖声明（D2 消费）
        "bc_compat": str,                       # 边界类（D5：全实例一致）
        "face_on_boundary": {pin_id: bool},     # exposed 端口面须贴域界（D1）
        "clearance_m": {pin_id: float},         # exposed 端口净距要求（D1）
        "span_m": {pin_id: float},              # pin 面到实例远端跨度（P4）
        "substrate": {"h_m", "er", "tan_d"},    # D6 实例级一致性
        "guards_text": [str...],                # 契约自带生成期断言（逐字发射）
    }

pin 字典（layout 解析实值；schema 静态声明见 TEMPLATE_META[t]["port_pins"]）::

    {"pin_id", "position": [x, y], "direction": [dx, dy], "z_ref_ohm",
     "ref_plane_offset_m", "port_type", "n_modes", "cross_section": {...},
     "width_m"}        # 截面特征宽（米，D2 结缝覆盖判定）

图元字典（引擎单一文本发射器消费）::

    {"kind": "box", "prop", "start": [x,y,z], "stop": [x,y,z], "priority"}
    {"kind": "polygon", "prop", "xs": [...], "ys": [...], "elevation", "priority"}
    {"kind": "cylinder", "prop", "start", "stop", "radius", "priority"}
    {"kind": "port", "pin", "port_type", "prop", "start", "stop",
     "axis", "feed_shift", "meas_plane_shift", "priority"}

netlist（rfauto-netlist-v1，gdsfactory 三段式同构）::

    schema: rfauto-netlist-v1
    band_ghz: [9.75, 10.25]
    mesh_resolution_mm: 0.4          # 0=自动 λ_sub/50
    substrate: {h_mm, er, tan_d}
    instances: [{id, template, params}]
    connections: [{a: [inst, pin], b: [inst, pin], allow_mismatch?}]
    exposed_ports: [{instance, pin}]   # 顺序=端口编号 1..M
    global_params: {excite_port?, nrts?}

摆位由 connections 吸附：首实例 identity，其余 rot180+平移求解（全向
transforms 预留——不可对向/斜摆显式 ValueError，不静默）。守卫两族：
P1-P5 连接守卫（规格 §2）与 D1-D6 合并守卫（规格 §3），全部显式
ComposeError(ValueError) 报双 pin id+坐标+差值。provenance=compose_meta
（确定性内容、无时间戳；netlist/渲染 sha256、pin→端口映射、守卫结果、
藩篱跨缝间隙诊断、dt/NrTS 估算）。
"""

from __future__ import annotations

import hashlib
import json
import math
from itertools import pairwise
from typing import Any

#: netlist schema 版本串。
COMPOSE_NETLIST_SCHEMA = "rfauto-netlist-v1"
#: compose_meta schema 版本串（确定性内容，无时间戳——C5 重渲染复验友好）。
COMPOSE_META_SCHEMA = "rfauto-compose-meta-v1"
#: pin 端口类型（schema 声明域；lumped/msl 本批发射器支持，
#: waveguide/field=P3+ 预留显式拒绝）。
PIN_PORT_TYPES: tuple[str, ...] = ("lumped", "msl", "waveguide", "field")
#: 组合发射支持的 exposed 端口数上限（render_script _excite_port 同口径）。
MAX_EXPOSED_PORTS = 4
#: P1 位置共点容差（米级，规格 §2）。
POSITION_TOL_M = 1e-9
#: P3 阻抗失配相对容差 |R_A−R_B| ≤ 1e-6·R。
IMPEDANCE_RTOL = 1e-6
#: #349 显式近场线最小间距地板（合并集重跑；与 siw/taper 契约同值）。
MERGED_MESH_FLOOR_M = 10e-6
#: 同名几何线浮点噪声合并容差（米）：契约各图元对同一坐标可能经不同算术
#: 路径求得（k·s+d/2 vs 板缘字面量），nm 级差异=同一条结构线——合并期先按
#: 此容差聚簇取首，再跑 #349 地板（1e-9 ≪ 10µm，真近撞不受掩护；口径与
#: #283 落格断言 1e-9 容差一致）。
COALESCE_EPS_M = 1e-9
#: CFL 时间步估算常数（均匀网格上限口径：dt = h_min/(c·√3)）。
_C0 = 299792458.0


class ComposeError(ValueError):
    """组合守卫失败（P1-P5/D1-D6/schema）；ValueError 子类，报双 pin id。"""


# ── Frame：rot180 + 平移（全向 transforms 预留）─────────────────────────────

def frame_apply_point(frame: tuple[float, float, bool],
                      xy: tuple[float, float]) -> tuple[float, float]:
    """帧仿射作用点：rot180 → (tx−x, ty−y)；identity → (tx+x, ty+y)。"""
    tx, ty, rot = frame
    x, y = float(xy[0]), float(xy[1])
    return (tx - x, ty - y) if rot else (tx + x, ty + y)


def frame_apply_dir(frame: tuple[float, float, bool],
                    dxy: tuple[float, float]) -> tuple[float, float]:
    """帧仿射作用方向向量（rot180 → 取反；平移不改方向）。"""
    _tx, _ty, rot = frame
    dx, dy = float(dxy[0]), float(dxy[1])
    return (-dx, -dy) if rot else (dx, dy)


def _fmt_frame(frame: tuple[float, float, bool]) -> str:
    return f"({frame[0]!r}, {frame[1]!r}, rot180={frame[2]!r})"


# ── netlist schema 校验与规范化 ─────────────────────────────────────────────

def _req(cond: bool, msg: str) -> None:
    if not cond:
        raise ComposeError(msg)


def _as_pair(v: Any, what: str) -> list[str]:
    _req(isinstance(v, (list, tuple)) and len(v) == 2,
         f"{what} 必须为二元 [实例id, pin_id]，得到 {v!r}")
    return [str(v[0]), str(v[1])]


def normalize_netlist(netlist: dict) -> dict:
    """netlist 深拷贝规范化（schema 校验；canonical JSON 键序确定性）。"""
    _req(isinstance(netlist, dict), f"netlist 必须为 dict，得到 {type(netlist)!r}")
    _req(str(netlist.get("schema")) == COMPOSE_NETLIST_SCHEMA,
         f"netlist schema 必须为 {COMPOSE_NETLIST_SCHEMA!r}，得到 "
         f"{netlist.get('schema')!r}")
    band = netlist.get("band_ghz")
    _req(isinstance(band, (list, tuple)) and len(band) == 2,
         "band_ghz 必须为 [f_lo, f_hi] 二元")
    blo, bhi = float(band[0]), float(band[1])
    _req(math.isfinite(blo) and math.isfinite(bhi) and bhi > blo > 0,
         f"band_ghz 必须为正有限且 f_hi>f_lo，得到 {band!r}")
    sub = netlist.get("substrate")
    _req(isinstance(sub, dict) and {"h_mm", "er"} <= set(sub),
         "substrate 必须为含 h_mm/er 的 dict")
    h_mm, er = float(sub["h_mm"]), float(sub["er"])
    tan_d = float(sub.get("tan_d", 0.0037))
    mesh_mm = float(netlist.get("mesh_resolution_mm", 0.0) or 0.0)
    _req(math.isfinite(mesh_mm) and mesh_mm >= 0,
         f"mesh_resolution_mm 必须为非负有限（0=自动），得到 {mesh_mm!r}")
    instances = netlist.get("instances")
    _req(isinstance(instances, list) and instances,
         "instances 必须为非空列表")
    ids: set[str] = set()
    norm_inst: list[dict] = []
    for inst in instances:
        _req(isinstance(inst, dict) and str(inst.get("id", "")).strip()
             and str(inst.get("template", "")).strip(),
             f"instance 必须含非空 id/template，得到 {inst!r}")
        iid = str(inst["id"])
        _req(iid.isidentifier(),
             f"instance id {iid!r} 必须为合法标识符（发射属性命名空间后缀）")
        _req(iid not in ids, f"instance id 重复: {iid!r}")
        ids.add(iid)
        norm_inst.append({"id": iid, "template": str(inst["template"]),
                          "params": dict(inst.get("params") or {})})
    conns = netlist.get("connections")
    _req(isinstance(conns, list) and conns, "connections 必须为非空列表")
    norm_conn: list[dict] = []
    for conn in conns:
        _req(isinstance(conn, dict), f"connection 必须为 dict，得到 {conn!r}")
        a = _as_pair(conn.get("a"), "connection.a")
        b = _as_pair(conn.get("b"), "connection.b")
        for iid, _pid in (a, b):
            _req(iid in ids, f"connection 引用未声明实例 {iid!r}")
        _req(a != b, f"connection 自连: {a!r}")
        norm_conn.append({"a": a, "b": b,
                          "allow_mismatch": bool(conn.get("allow_mismatch",
                                                          False))})
    exposed = netlist.get("exposed_ports")
    _req(isinstance(exposed, list) and exposed,
         "exposed_ports 必须为非空列表（组合链至少 1 端口）")
    _req(len(exposed) <= MAX_EXPOSED_PORTS,
         f"exposed_ports 数 {len(exposed)} > {MAX_EXPOSED_PORTS}（D4 上限）")
    norm_exp: list[dict] = []
    for exp in exposed:
        _req(isinstance(exp, dict), f"exposed_port 必须为 dict，得到 {exp!r}")
        iid, pin = str(exp.get("instance", "")), str(exp.get("pin", ""))
        _req(iid in ids, f"exposed_ports 引用未声明实例 {iid!r}")
        norm_exp.append({"instance": iid, "pin": pin})
    gp = dict(netlist.get("global_params") or {})
    excite = int(gp.get("excite_port", 1) or 1)
    _req(1 <= excite <= len(norm_exp),
         f"global_params.excite_port={excite} 超出 exposed 端口范围 "
         f"1..{len(norm_exp)}")
    gp["excite_port"] = excite
    gp["nrts"] = int(gp.get("nrts", 100000) or 100000)
    return {"schema": COMPOSE_NETLIST_SCHEMA, "band_ghz": [blo, bhi],
            "mesh_resolution_mm": mesh_mm,
            "substrate": {"h_mm": h_mm, "er": er, "tan_d": tan_d},
            "instances": norm_inst, "connections": norm_conn,
            "exposed_ports": norm_exp, "global_params": gp}


def canonical_json(obj: Any) -> str:
    """确定性 JSON 文本（sort_keys；sha256 键源）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1,
                      default=str)


# ── 布局求解：connections 吸附摆位 ──────────────────────────────────────────

def _layout_instance(contract: dict, inst: dict, band: list[float],
                     base_m: float, h_m: float,
                     frame: tuple[float, float, bool]) -> dict:
    fn = contract.get("layout")
    _req(callable(fn), f"契约 {inst['template']!r} 缺 layout 函数")
    lay = fn(dict(inst["params"]), (float(band[0]), float(band[1])),
             base_m, h_m, frame)
    _req(isinstance(lay, dict) and lay.get("pins") and lay.get("primitives")
         is not None and lay.get("dom") and lay.get("bbox"),
         f"契约 {inst['template']!r} layout 返回缺 pins/primitives/dom/bbox")
    return lay


def _solve_frame(dir_a: tuple[float, float],
                 dir_b: tuple[float, float],
                 pos_a: tuple[float, float],
                 pos_b: tuple[float, float],
                 label: str) -> tuple[float, float, bool]:
    """由对向方向约束解 rot180，再由位置约束解平移（不可对向 → P2 显式错）。"""
    da = (float(dir_a[0]), float(dir_a[1]))
    db = (float(dir_b[0]), float(dir_b[1]))
    if db == (-da[0], -da[1]):
        rot = False
    elif db == da:
        rot = True
    else:
        dot = da[0] * db[0] + da[1] * db[1]
        raise ComposeError(
            f"P2 方向对向失败（{label}）：pin A 方向 {da!r} 与 pin B 局部方向 "
            f"{db!r} 在 rot180 帧内不可对向（dot={dot!r} ≠ ±1 同/对向轴）"
            "——全向 transforms 预留（DP-8 P3+），斜摆/正交对接显式拒绝")
    base = (0.0, 0.0, rot)
    tx = pos_a[0] - frame_apply_point(base, pos_b)[0]
    ty = pos_a[1] - frame_apply_point(base, pos_b)[1]
    return (tx, ty, rot)


# ── 守卫：P1-P5（连接级，报双 pin id+坐标+差值）────────────────────────────

def _pin_label(inst_id: str, pin_id: str) -> str:
    return f"{inst_id}.{pin_id}"


def _guard_p1(pin_a: dict, pin_b: dict, label: str) -> None:
    pa, pb = pin_a["position"], pin_b["position"]
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    dist = math.hypot(dx, dy)
    if not dist <= POSITION_TOL_M:
        raise ComposeError(
            f"P1 位置共点失败（{label}）：pin A={pin_a['pin_id']!r} @ "
            f"({pa[0]!r}, {pa[1]!r}) vs pin B={pin_b['pin_id']!r} @ "
            f"({pb[0]!r}, {pb[1]!r})：|Δ|={dist!r} m（dx={dx!r}, dy={dy!r}，"
            f"tol={POSITION_TOL_M!r}）")


def _guard_p2(pin_a: dict, pin_b: dict, label: str) -> None:
    da, db = pin_a["direction"], pin_b["direction"]
    dot = da[0] * db[0] + da[1] * db[1]
    if dot != -1.0:
        raise ComposeError(
            f"P2 方向对向失败（{label}）：pin A={pin_a['pin_id']!r} 方向 "
            f"{da!r} vs pin B={pin_b['pin_id']!r} 方向 {db!r}：dot={dot!r} "
            "≠ −1（外法向须严格对向）")


def _guard_p3(pin_a: dict, pin_b: dict, label: str,
              allow_mismatch: bool) -> dict | None:
    ra, rb = float(pin_a["z_ref_ohm"]), float(pin_b["z_ref_ohm"])
    diff = abs(ra - rb)
    if diff <= IMPEDANCE_RTOL * max(abs(ra), abs(rb), 1e-300):
        return None
    if allow_mismatch:
        return {"pin_a": pin_a["pin_id"], "pin_b": pin_b["pin_id"],
                "z_ref_a_ohm": ra, "z_ref_b_ohm": rb, "abs_diff_ohm": diff,
                "exempted_by": "connection.allow_mismatch"}
    raise ComposeError(
        f"P3 阻抗失配（{label}）：pin A={pin_a['pin_id']!r} z_ref={ra!r}Ω vs "
        f"pin B={pin_b['pin_id']!r} z_ref={rb!r}Ω：|ΔR|={diff!r}Ω > "
        f"{IMPEDANCE_RTOL!r}·R——如需组合须在该 connection 显式 "
        "allow_mismatch: true（豁免留痕进 compose_meta.p3_impedance_exemptions）")


def _guard_p4(pin_a: dict, pin_b: dict, label: str, span_a: float,
              span_b: float) -> None:
    for pin, span in ((pin_a, span_a), (pin_b, span_b)):
        off = float(pin["ref_plane_offset_m"])
        if not (math.isfinite(off) and 0.0 <= off <= span):
            raise ComposeError(
                f"P4 参考面越界（{label}）：pin {pin['pin_id']!r} "
                f"ref_plane_offset_m={off!r} 不在 [0, 实例跨度 {span!r}] 内"
                "（offset 望远镜不越界）")


def _guard_p5(pin_a: dict, pin_b: dict, label: str) -> None:
    xa, xb = pin_a["cross_section"], pin_b["cross_section"]
    fa = {k: v for k, v in xa.items() if k != "kind"}
    fb = {k: v for k, v in xb.items() if k != "kind"}
    bad: list[str] = []
    for key in ("h_mm", "er"):
        va, vb = float(fa.get(key, float("nan"))), float(fb.get(key, float("nan")))
        if not (math.isfinite(va) and math.isfinite(vb)
                and abs(va - vb) <= 1e-12 * max(abs(va), abs(vb), 1.0)):
            bad.append(f"{key}: {va!r} vs {vb!r}")
    if xa.get("kind") == xb.get("kind"):
        for key in sorted((set(fa) & set(fb)) - {"h_mm", "er"}):
            va, vb = float(fa[key]), float(fb[key])
            if abs(va - vb) > 1e-9 * max(abs(va), abs(vb), 1.0):
                bad.append(f"{key}: {va!r} vs {vb!r}")
    if bad:
        raise ComposeError(
            f"P5 截面不兼容（{label}）：pin A={pin_a['pin_id']!r} 截面 {xa!r} "
            f"vs pin B={pin_b['pin_id']!r} 截面 {xb!r}：失配字段 "
            + "；".join(bad) + "（基板 h/εr 必须一致；同 kind 特征尺寸一致）")


# ── 守卫：D1-D6（合并级）───────────────────────────────────────────────────

def _union_box(boxes: list[tuple[float, float, float, float]]
               ) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _interval_union_coverage(intervals: list[tuple[float, float]],
                             target: tuple[float, float]) -> bool:
    """1D 区间并集覆盖 target（D2 结缝导体连通分量判定）。"""
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return any(lo <= target[0] and target[1] <= hi for lo, hi in merged)


def _near_lines_from_primitives(primitives: list[dict]
                                ) -> dict[str, list[float]]:
    """从图元派生显式近场线候选集（#198/#283 单源：带缘=结构线=网格线）。"""
    xs: list[float] = []
    ys: list[float] = []
    for prim in primitives:
        kind = prim.get("kind")
        if kind in ("box", "cylinder", "port"):
            s, t = prim["start"], prim["stop"]
            xs += [float(s[0]), float(t[0])]
            ys += [float(s[1]), float(t[1])]
            if kind == "cylinder":
                r = float(prim["radius"])
                xs += [float(s[0]) - r, float(s[0]) + r]
                ys += [float(s[1]) - r, float(s[1]) + r]
                ys += [float(s[1]) - r, float(s[1]) + r]
        elif kind == "polygon":
            xs += [float(v) for v in prim["xs"]]
            ys += [float(v) for v in prim["ys"]]
        else:
            raise ComposeError(f"未知图元 kind: {kind!r}")
    return {"x": xs, "y": ys}


def _dedup_strict(values: list[float]) -> list[float]:
    """排序 + 浮点噪声聚簇（≤1e-9 取首，同 #283 容差口径）+ 严格 > 去重
    （#152/#283 口径）。"""
    out: list[float] = []
    for v in sorted(float(v) for v in values):
        if out and v - out[-1] <= COALESCE_EPS_M:
            continue  # 同名几何线的浮点噪声路径，聚簇取首
        if not out or v - out[-1] > 0.0:
            out.append(v)
    return out


# ── 文本发射（引擎单一发射器）──────────────────────────────────────────────

def _emit_primitive(prim: dict, port_nr: int | None, excite: float) -> list[str]:
    """图元 → CSXCAD 语句文本（确定性；浮点全 repr 往返）。"""
    kind = prim["kind"]
    if kind == "box":
        s, t = prim["start"], prim["stop"]
        return [f'{prim["prop"]}.AddBox(({s[0]!r}, {s[1]!r}, {s[2]!r}), '
                f'({t[0]!r}, {t[1]!r}, {t[2]!r}), '
                f'priority={int(prim["priority"])})']
    if kind == "polygon":
        return [f'{prim["prop"]}.AddPolygon(({prim["xs"]!r}, {prim["ys"]!r}), '
                f'norm_dir="z", elevation={prim["elevation"]!r}, '
                f'priority={int(prim["priority"])})']
    if kind == "cylinder":
        s, t = prim["start"], prim["stop"]
        return [f'{prim["prop"]}.AddCylinder(({s[0]!r}, {s[1]!r}, {s[2]!r}), '
                f'({t[0]!r}, {t[1]!r}, {t[2]!r}), '
                f'radius={prim["radius"]!r}, '
                f'priority={int(prim["priority"])})']
    if kind == "port":
        _req(prim["port_type"] in ("msl", "lumped"),
             f"D4 exposed port_type={prim['port_type']!r} 未支持发射器"
             "（waveguide/field 为 P3+ 预留，显式拒绝）")
        s, t = prim["start"], prim["stop"]
        nr = int(port_nr or 0)
        lines = []
        if prim["port_type"] == "msl":
            _req("feed_shift" in prim and "meas_plane_shift" in prim,
                 "契约 msl 端口图元缺 feed_shift/meas_plane_shift"
                 "（发射器必备标量；MSLPort 构造契约）")
            lines.append(f"_port{nr} = MSLPort(CSX, port_nr={nr}, "
                         f'metal_prop={prim["prop"]},')
            lines.append(f"                 start=np.array([{s[0]!r}, "
                         f"{s[1]!r}, {s[2]!r}]),")
            lines.append(f"                 stop=np.array([{t[0]!r}, "
                         f"{t[1]!r}, {t[2]!r}]),")
            lines.append(f'                 prop_dir={prim["axis"]!r}, '
                         f'exc_dir="z", excite={excite!r},')
            lines.append(f'                 FeedShift={prim["feed_shift"]!r}, '
                         f'MeasPlaneShift={prim["meas_plane_shift"]!r}, '
                         f'priority={int(prim["priority"])})')
        else:  # lumped（z 桥/端面口径，siw v2 同构；R=契约闭式注入值）
            z = float(prim["ref_impedance"])
            ref = "50" if z == 50.0 else repr(z)
            lines.append(f"_port{nr} = FDTD.AddLumpedPort({nr}, {ref}, "
                         f"np.array([{s[0]!r}, {s[1]!r}, {s[2]!r}]),")
            lines.append(f"                            np.array([{t[0]!r}, "
                         f"{t[1]!r}, {t[2]!r}]), {prim['axis']!r}, "
                         f"{excite!r},")
            lines.append(f'                            priority='
                         f'{int(prim["priority"])})')
        return lines
    raise ComposeError(f"未知图元 kind: {kind!r}")


def _render(*, netlist: dict, frames: dict[str, tuple[float, float, bool]],
            dom: tuple[float, float, float, float],
            near_x: list[float], near_y: list[float], f0: float, fc: float,
            er: float, h_m: float, tan_d: float, base_m: float,
            near_m: float, nrts: int, instance_blocks: list[str],
            port_classes: list[str], ports: list[dict],
            assert_pairs: list[tuple[str, float]]) -> str:
    """完整 simulation.py（引擎单一发射；头/守卫/尾结构镜像 render_script
    官方口径；y 域非对称 → Y_MIN/Y_MAX 字面量，x 对称 → DOM_X 半宽）。"""
    inst_line = " | ".join(
        f"{i['id']}={i['template']}@{_fmt_frame(frames[i['id']])}"
        for i in netlist["instances"])
    ports_import_line = (f"from openEMS.ports import {', '.join(port_classes)}"
                         if port_classes
                         else "# 端口全为 FDTD.AddLumpedPort（openEMS 自带，无需 ports 导入）")
    calc_lines: list[str] = []
    for p in ports:
        z = float(p["z_ref_ohm"])
        ref = "50" if z == 50.0 else repr(z)
        calc_lines.append(f"_port{p['port_nr']}.CalcPort(SIM_PATH, f, "
                          f"ref_impedance={ref})")
    s_rows = [f"S{p['port_nr']}1 = _port{p['port_nr']}.uf_ref / _port1.uf_inc"
              for p in ports]
    header_cols = ["freq_hz"]
    row_terms = ["fi"]
    for p in ports:
        header_cols += [f"re_S{p['port_nr']}1", f"im_S{p['port_nr']}1"]
        row_terms += [f"S{p['port_nr']}1[i].real", f"S{p['port_nr']}1[i].imag"]
    hdr_src = ", ".join(repr(c) for c in header_cols)
    chunked = [", ".join(row_terms[i:i + 4])
               for i in range(0, len(row_terms), 4)]
    row_src = ",\n                   ".join(chunked)
    assert_src = "\n".join(f'        ("{ax}", {v!r}),' for ax, v in assert_pairs)
    dom_x_half = max(abs(dom[0]), abs(dom[2]))
    return f'''#!/usr/env/python3
"""openEMS script (rfauto compose auto-generated, {COMPOSE_NETLIST_SCHEMA}).
Instances: {inst_line}
DP-8 几何组合引擎发射（布局合并路线：逐实例 layout→帧仿射→合并→单脚本，
非渲染文本拼接——runs/df6_dp8compose/criteria.md §0）。"""
import csv
import os

# CSXCAD/openEMS 扩展模块的依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里，
# 必须 add_dll_directory（仅 os.environ PATH 会 ImportError: DLL load
# failed——2026-09-03 审计实测）。目录可用 RFAUTO_OPENEMS_BIN 覆盖。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\openEMS\\install\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
{ports_import_line}

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}   # 网格 base：netlist mesh_resolution_mm 显式档
NEAR = {near_m!r}   # 近走线区 = base/4（官方口径）
CSV_NAME = "sparams.csv"
SIM_PATH = __import__("os").path.abspath("fdtd")
# 绑定库运行中可能改写解释器 cwd：CSV 一律写脚本自身目录（绝对路径），
# 否则产物静默落到进程启动目录（2026-09-03 审计实测踩坑）
CSV_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    CSV_NAME)

# ── 仿真环境：官方 MSL_NotchFilter 教程方法学（组合域 D5 合并口径：端口轴
# PML_8、x 侧 MUR、z 底 PEC 当地面、顶 MUR——MSL 区微带环境开放顶，SIW 顶壁
# =各实例显式零厚板见 body；runs/df6_dp8compose/criteria.md §1）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS={nrts!r})   # 官方口径：不设 EndCriteria，默认能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"])

AIR_TOP = 5e-3     # guided 顶空气隙
AIR_SIDE = 0.0     # guided 侧向无空气隙

mesh = CSX.GetGrid()
DOM_X = {dom_x_half!r}    # 合并域 x 半宽（对称；全实例同截面 D5/D6）
Y_MIN = {dom[1]!r}    # 合并域 y 下界（∪dom，D1）
Y_MAX = {dom[3]!r}    # 合并域 y 上界（∪dom，D1）

def _axis(ax: str, near_pts, dom_lo, dom_hi) -> None:
    """官方网格配方：走线近场 NEAR 精细区 + 全轴 BASE 渐变（SmoothMesh）。"""
    for p in near_pts:
        mesh.AddLine(ax, p)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_near_x = {near_x!r}
_near_y = {near_y!r}
_axis("x", _near_x, -DOM_X, DOM_X)
_axis("y", _near_y, Y_MIN, Y_MAX)
mesh.AddLine("z", np.linspace(0, H_SUB, 5))   # 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）
mesh.AddLine("z", H_SUB + AIR_TOP)
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫：浮点误差线可能只差 nm~µm 级，把时间步压塌
# （2026-09-03 B 点审计实测）。平滑后按最小间距 1µm 去重。
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# 合并域基板（D6：全实例同 substrate；底=域 z 边界 PEC，顶=MUR 开放）
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, Y_MIN, 0), (DOM_X, Y_MAX, H_SUB), priority=0)
# 统一整域底板（D2：禁板缝断——全实例 z=0 底板声明并入合并域后单盒发射）
compose_bot = CSX.AddMetal("compose_bot")
compose_bot.AddBox((-DOM_X, Y_MIN, 0.0), (DOM_X, Y_MAX, 0.0), priority=10)

{chr(10).join(instance_blocks)}
# 生成期网格守卫（合并集重跑，D3）：#152 去重后全轴最小间距复测（CFL 塌缩
# 哨兵）+ #283 合并结构边落格断言（盒边/带缘=结构线，缺线即断言红）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("compose #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _compose_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (
{assert_src}
):
    if not _compose_on_line(_ax, _v):
        raise SystemExit("compose #" + "283" + ": 合并结构边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")

# cleanup：清掉同目录旧 run 的 port/et 输出——不清理时 CalcPort 会读到
# 上一版结构的旧信号文件，S 参数静默变 NaN（实测踩坑）
FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
# 官方 MSL_NotchFilter 口径：CalcPort ref_impedance=exposed pin 契约值
# （msl=50；其余=契约闭式注入）；S_i1=第 i 端口对第 1 激励口带载比值
#（#250 口径：单激励 uf_ref/uf_inc，相位含端口分解伪象只作幅值判读）。
{chr(10).join(calc_lines)}
{chr(10).join(s_rows)}
with open(CSV_PATH, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow([{hdr_src}])
    for i, fi in enumerate(f):
        w.writerow([{row_src}])
print("rfauto openEMS simulation done")
'''


def _seam_via_gap(placed: dict[str, dict], a_id: str, b_id: str,
                  seam_y: float) -> float | None:
    """跨缝藩篱间隙（两侧圆柱 y 心跨缝最近距）；任一侧无藩篱 → None。"""
    def _centers(iid: str, side: str) -> list[float]:
        out = []
        for prim in placed[iid]["primitives"]:
            if prim.get("kind") == "cylinder":
                y = float(prim["start"][1])
                if (side == "lo" and y < seam_y - POSITION_TOL_M) or (
                        side == "hi" and y > seam_y + POSITION_TOL_M):
                    out.append(y)
        return out

    lo = _centers(a_id, "lo")
    hi = _centers(b_id, "hi")
    if not lo or not hi:
        return None
    return min(hi) - max(lo)


# ── 引擎主入口 ─────────────────────────────────────────────────────────────

def compose_netlist(netlist: dict, contracts: dict[str, dict],
                    schema_map: dict[str, list] | None = None
                    ) -> tuple[str, dict]:
    """netlist+契约 → (simulation.py 文本, compose_meta 字典)。纯确定性。

    contracts: {template: {"layout": callable}}（adapters 注入，core 零反向
    依赖）；schema_map: {template: TEMPLATE_META[t]["port_pins"]}（opt-in
    校验：未注册模板显式报错、契约 pin_id 集与 schema 声明一致）。
    """
    nl = normalize_netlist(netlist)
    band = nl["band_ghz"]
    sub = nl["substrate"]
    # 官方口径 band/base（render_script 同式）
    f0 = (band[0] + band[1]) / 2 * 1e9
    fc = max((band[1] - band[0]) / 2 * 1e9, 1e6)
    er = float(sub["er"])
    h_m = float(sub["h_mm"]) * 1e-3
    tan_d = float(sub["tan_d"])
    f_max = f0 + fc
    mesh_mm = float(nl["mesh_resolution_mm"])
    base_m = (3e8 / (f_max * (er ** 0.5)) / 50 if not mesh_mm
              else mesh_mm * 1e-3)
    near_m = base_m / 4.0

    # ① 实例契约解析（opt-in：未注册模板显式报错）+ 局部布局（identity）
    insts = nl["instances"]
    local: dict[str, dict] = {}
    for inst in insts:
        tid = inst["template"]
        contract = contracts.get(tid)
        if contract is None:
            raise ComposeError(
                f"模板 {tid!r} 未注册组合契约（opt-in 渐进：已注册 "
                f"{sorted(contracts)}）——未注册模板不可被组合引用，不阻塞"
                "其余模板")
        lay = _layout_instance(contract, inst, band, base_m, h_m,
                               (0.0, 0.0, False))
        if schema_map is not None and tid in schema_map:
            declared = {str(p.get("pin_id")) for p in (schema_map[tid] or [])}
            _req(declared == set(lay["pins"]),
                 f"模板 {tid!r} port_pins 声明 {sorted(declared)} 与契约布局 "
                 f"pin {sorted(lay['pins'])} 不一致")
        _req(bool(lay.get("bc_compat")),
             f"契约 {tid!r} 缺 bc_compat（D5 边界类声明）")
        local[inst["id"]] = lay

    # ② D6 实例级一致性（band 全局唯一；substrate 逐实例对账）
    for inst in insts:
        s_i = local[inst["id"]].get("substrate") or {}
        for key, gv in (("h_m", h_m), ("er", er), ("tan_d", tan_d)):
            iv = float(s_i.get(key, float("nan")))
            gv_f = float(gv)
            if not (math.isfinite(iv) and abs(iv - gv_f)
                    <= 1e-12 * max(abs(iv), abs(gv_f), 1.0)):
                raise ComposeError(
                    f"D6 一致性失败：实例 {inst['id']!r} substrate.{key}="
                    f"{iv!r} 与 netlist {gv_f!r} 漂移（band/substrate 必须"
                    "一致；跨基板组合不是 DP-8 范围）")

    # ③ 摆位求解（connections 吸附：首实例 identity，rot180+平移）
    frames: dict[str, tuple[float, float, bool]] = {
        insts[0]["id"]: (0.0, 0.0, False)}
    conn_list = nl["connections"]
    pending = list(conn_list)
    while pending:
        progressed = False
        rest: list[dict] = []
        for conn in pending:
            a_id, a_pin = conn["a"]
            b_id, b_pin = conn["b"]
            a_placed, b_placed = a_id in frames, b_id in frames
            if a_placed and b_placed:
                progressed = True  # 校验型连接，⑤统一复核
                continue
            if not a_placed and not b_placed:
                rest.append(conn)
                continue
            ref_id, ref_pin = (a_id, a_pin) if a_placed else (b_id, b_pin)
            new_id, new_pin = (b_id, b_pin) if a_placed else (a_id, b_pin)
            ref_lay, new_lay = local[ref_id], local[new_id]
            _req(ref_pin in ref_lay["pins"] and new_pin in new_lay["pins"],
                 f"connection 引用未声明 pin: {_pin_label(ref_id, ref_pin)}/"
                 f"{_pin_label(new_id, new_pin)}（契约 pin 集="
                 f"{sorted(ref_lay['pins'])}/{sorted(new_lay['pins'])}）")
            rp = dict(ref_lay["pins"][ref_pin])
            rp["position"] = frame_apply_point(frames[ref_id], rp["position"])
            rp["direction"] = frame_apply_dir(frames[ref_id],
                                              rp["direction"])
            np_local = dict(new_lay["pins"][new_pin])
            label = f"{_pin_label(a_id, a_pin)} ↔ {_pin_label(b_id, b_pin)}"
            frames[new_id] = _solve_frame(
                (rp["direction"][0], rp["direction"][1]),
                (np_local["direction"][0], np_local["direction"][1]),
                (rp["position"][0], rp["position"][1]),
                (np_local["position"][0], np_local["position"][1]), label)
            progressed = True
        if not progressed:
            raise ComposeError(
                f"connections 图不连通/无锚点：{len(pending)} 条连接无法吸附"
                "到已摆位实例（首实例=netlist instances[0] identity）")
        pending = rest
    orphans = [i["id"] for i in insts if i["id"] not in frames]
    _req(not orphans,
         f"孤立实例未通过 connections 摆位: {orphans}（每实例须被连接图"
         "锚定；悬空实例无全局坐标，显式拒绝）")

    # ④ 帧内重布局（图元/域/板全部仿射到全局）
    placed: dict[str, dict] = {}
    for inst in insts:
        placed[inst["id"]] = _layout_instance(contracts[inst["template"]],
                                              inst, band, base_m, h_m,
                                              frames[inst["id"]])

    # ⑤ 连接守卫 P1-P5（全部连接，含校验型；placed 布局已帧内仿射=全局）
    p3_notes: list[dict] = []
    for conn in conn_list:
        a_id, a_pin = conn["a"]
        b_id, b_pin = conn["b"]
        pa = dict(placed[a_id]["pins"][a_pin])
        pb = dict(placed[b_id]["pins"][b_pin])
        label = f"{_pin_label(a_id, a_pin)} ↔ {_pin_label(b_id, b_pin)}"
        _guard_p1(pa, pb, label)
        _guard_p2(pa, pb, label)
        note = _guard_p3(pa, pb, label, bool(conn["allow_mismatch"]))
        if note:
            p3_notes.append({"connection": label, **note})
        _guard_p4(pa, pb, label,
                  float(placed[a_id]["span_m"][a_pin]),
                  float(placed[b_id]["span_m"][b_pin]))
        _guard_p5(pa, pb, label)

    # ⑥ D4 端口重编：exposed 编号 1..M；内部 pin 不生成 FDTD 端口
    exposed = nl["exposed_ports"]
    excite_port = int(nl["global_params"]["excite_port"])
    port_map: dict[tuple[str, str], int] = {}
    for k, exp in enumerate(exposed, start=1):
        iid, pin = exp["instance"], exp["pin"]
        _req(pin in placed[iid]["pins"],
             f"exposed_ports 引用未声明 pin: {_pin_label(iid, pin)}")
        port_map[(iid, pin)] = k
    emitted_ports: list[dict] = []
    blocks: list[str] = []
    near_x_all: list[float] = []
    near_y_all: list[float] = []
    port_classes: list[str] = []
    for inst in insts:
        iid = inst["id"]
        lay = placed[iid]
        # 属性命名空间：prop→"{prop}__{iid}"（契约用裸名，引擎管命名防跨实例
        # 属性串线；CSX 属性=材料网格布尔并集，跨实例同属性反而假连通）
        prims: list[dict] = []
        for prim in lay["primitives"]:
            if prim.get("kind") != "port":
                prims.append({**prim, "prop": f"{prim['prop']}__{iid}"})
                continue
            pin_id = str(prim["pin"])
            key = (iid, pin_id)
            if key not in port_map:
                # D4：内部 pin 不生成 FDTD 端口；msl 内连=馈线缺失，显式拒绝
                _req(str(prim.get("port_type", "lumped")) != "msl",
                     f"D4 内部 pin 不生成 FDTD 端口：{_pin_label(iid, pin_id)}"
                     " 为 msl 型——msl 内连需馈线延伸（DP-8 P3+ 预留），显式"
                     "拒绝（内部波导/lumped pin 静默省略端口即可）")
                continue
            prims.append({**prim, "prop": f"{prim['prop']}__{iid}",
                          "_nr": port_map[key]})
        body_lines: list[str] = []
        seen_props: list[str] = []
        for prim in prims:
            prop = prim.get("prop")
            if prop and prop not in seen_props:
                seen_props.append(prop)
                body_lines.append(f'{prop} = CSX.AddMetal("{prop}")')
            nr = None
            excite = 0.0
            if prim.get("kind") == "port":
                nr = int(prim["_nr"])
                excite = 1.0 if nr == excite_port else 0.0
                # lumped 走 FDTD.AddLumpedPort（openEMS 自带，无需导入）
                if (prim["port_type"] == "msl"
                        and "MSLPort" not in port_classes):
                    port_classes.append("MSLPort")
            body_lines += _emit_primitive(prim, nr, excite)
        for gt in lay.get("guards_text") or []:
            body_lines.append(str(gt))
        for prop in seen_props:
            body_lines += [f"for _prim in {prop}.GetAllPrimitives():",
                           "    if _prim.GetPriority() < 10:",
                           "        _prim.SetPriority(10)"]
        blocks.append(
            f"# ═══ instance {iid}: {inst['template']} "
            f"frame={_fmt_frame(frames[iid])} ═══\n" + "\n".join(body_lines))
        for prim in prims:
            if prim.get("kind") == "port":
                nr = int(prim["_nr"])
                emitted_ports.append({
                    "port_nr": nr, "instance": iid,
                    "pin": str(prim["pin"]),
                    "port_type": str(prim["port_type"]),
                    "z_ref_ohm": float(
                        lay["pins"][str(prim["pin"])]["z_ref_ohm"])})
        near = _near_lines_from_primitives(prims)
        near_x_all += near["x"]
        near_y_all += near["y"]
    emitted_ports.sort(key=lambda p: p["port_nr"])
    _req(len(emitted_ports) == len(exposed),
         f"D4 端口重编失败：发射端口 {len(emitted_ports)} ≠ exposed "
         f"{len(exposed)}（D4 门：FDTD 端口数=exposed 数）")

    # ⑦ D1 域合并：∪dom；结构/pin 出域检查；exposed 面贴界/净距重验
    dom = _union_box([placed[i["id"]]["dom"] for i in insts])
    dom_x_half = max(abs(dom[0]), abs(dom[2]))
    for inst in insts:
        iid = inst["id"]
        lay = placed[iid]
        bx = lay["bbox"]
        _req(bx[0] >= dom[0] - POSITION_TOL_M
             and bx[1] >= dom[1] - POSITION_TOL_M
             and bx[2] <= dom[2] + POSITION_TOL_M
             and bx[3] <= dom[3] + POSITION_TOL_M,
             f"D1 结构出域：实例 {iid!r} bbox {bx!r} 越出合并域 {dom!r}")
        for pin_id, pin in lay["pins"].items():
            px, py = float(pin["position"][0]), float(pin["position"][1])
            _req(dom[0] - POSITION_TOL_M <= px <= dom[2] + POSITION_TOL_M
                 and dom[1] - POSITION_TOL_M <= py <= dom[3] + POSITION_TOL_M,
                 f"D1 pin 出域：{_pin_label(iid, pin_id)} @ ({px!r}, {py!r}) "
                 f"越出合并域 {dom!r}")
            if (iid, pin_id) in port_map:
                face = bool(lay["face_on_boundary"].get(pin_id, False))
                clear = float(lay["clearance_m"].get(pin_id, 0.0))
                if face:
                    on_edge = (min(abs(py - dom[1]), abs(py - dom[3]))
                               <= POSITION_TOL_M)
                    _req(on_edge,
                         f"D1 exposed 端口面不贴域界："
                         f"{_pin_label(iid, pin_id)} y={py!r} vs 合并域 "
                         f"y=[{dom[1]!r}, {dom[3]!r}]（msl 口径：端口面=域"
                         "边界贴 PML_8，#174）")
                else:
                    margin = min(py - dom[1], dom[3] - py)
                    _req(margin >= clear - POSITION_TOL_M,
                         f"D1 exposed 端口净距不足："
                         f"{_pin_label(iid, pin_id)} 净距 {margin!r} m < "
                         f"契约要求 {clear!r} m（16·BASE 出 PML_8 口径按合并"
                         "域重验，D5/#253）")

    # ⑧ D2 底板整域声明 + 结缝导体同连通分量 + 藩篱跨缝间隙诊断
    for inst in insts:
        bb = placed[inst["id"]]["bottom_plate"]
        _req(bb[0] >= dom[0] - POSITION_TOL_M
             and bb[1] >= dom[1] - POSITION_TOL_M
             and bb[2] <= dom[2] + POSITION_TOL_M
             and bb[3] <= dom[3] + POSITION_TOL_M,
             f"D2 底板声明出域：实例 {inst['id']!r} bottom_plate {bb!r} 越出"
             f"合并域 {dom!r}")
    seam_notes: list[dict] = []
    for conn in conn_list:
        a_id, a_pin = conn["a"]
        b_id, b_pin = conn["b"]
        # placed 布局已帧内仿射=全局（④），直读 pin 坐标
        seam_y = float(placed[a_id]["pins"][a_pin]["position"][1])
        seam_covered = True
        widths: list[tuple[float, float]] = []
        for iid, pin_id in ((a_id, a_pin), (b_id, b_pin)):
            pin = placed[iid]["pins"][pin_id]
            px, py_i = float(pin["position"][0]), float(pin["position"][1])
            half = float(pin["width_m"]) / 2.0
            widths.append((px - half, px + half))
            ivals = [(float(bx[0]), float(bx[2]))
                     for bx in placed[iid]["plates_top"]
                     if bx[1] - POSITION_TOL_M <= py_i <= bx[3] + POSITION_TOL_M]
            if not _interval_union_coverage(ivals, widths[-1]):
                seam_covered = False
        _req(seam_covered,
             f"D2 结缝导体不连续（{_pin_label(a_id, a_pin)} ↔ "
             f"{_pin_label(b_id, b_pin)}）：seam y={seam_y!r} 处结缝两侧顶板"
             f"（z=H_SUB 显式板）未各自覆盖 pin 截面宽 {widths!r}"
             "（禁板缝断；结缝两侧导体须同连通分量）")
        seam_notes.append({
            "connection": f"{a_id}.{a_pin} ↔ {b_id}.{b_pin}",
            "seam_y_m": seam_y,
            "seam_via_gap_m": _seam_via_gap(placed, a_id, b_id, seam_y)})

    # ⑨ D3 网格衔接：合并集严格>去重 + #349 地板重跑 + #283 落格集
    near_x = _dedup_strict(near_x_all)
    near_y = _dedup_strict(near_y_all)
    for axis, vals in (("x", near_x), ("y", near_y)):
        gaps = [b - a for a, b in pairwise(vals)]
        gmin = min(gaps) if gaps else float("inf")
        _req(gmin > MERGED_MESH_FLOOR_M,
             f"D3 合并集近线最小间距 {gmin * 1e6:.3f}µm ≤ "
             f"{MERGED_MESH_FLOOR_M * 1e6:.0f}µm 地板（#349 在合并集重跑；"
             f"{axis} 向跨实例结构线近撞，调整摆位/参数）")
    # #283 落格断言集=合并集（图元坐标全部经近场线派生入网；聚簇后逐条断言）
    assert_pairs = sorted({("x", v) for v in near_x}
                          | {("y", v) for v in near_y}
                          | {("z", 0.0), ("z", h_m)},
                          key=lambda p: (p[0], p[1]))

    # ⑩ D5 边界类一致 + dt/NrTS 预算估算（#328：估算值，真预算按终网格 CFL）
    bc_set = {placed[i["id"]]["bc_compat"] for i in insts}
    _req(len(bc_set) == 1,
         f"D5 边界类不一致：实例 bc_compat 集 {sorted(bc_set)}（组合域边界"
         "口径必须唯一：siw_family=端口轴 PML_8+z 底 PEC+顶 MUR 显式板）")
    gaps_all = ([b - a for a, b in pairwise(near_x)]
                + [b - a for a, b in pairwise(near_y)])
    min_space = min([*gaps_all, near_m]) if gaps_all else near_m
    dt_est = min_space / (_C0 * math.sqrt(3.0))
    nrts = int(nl["global_params"]["nrts"])

    # ⑪ 发射（引擎单一文本发射器）
    text = _render(netlist=nl, frames=frames, dom=dom, near_x=near_x,
                   near_y=near_y, f0=f0, fc=fc, er=er, h_m=h_m, tan_d=tan_d,
                   base_m=base_m, near_m=near_m, nrts=nrts,
                   instance_blocks=blocks, port_classes=port_classes,
                   ports=emitted_ports, assert_pairs=assert_pairs)

    # ⑫ provenance（确定性；无时间戳——C5 重渲染复验友好）
    inst_meta: list[dict] = []
    for inst in insts:
        iid = inst["id"]
        pins_out: dict[str, dict] = {}
        for pin_id, pin in placed[iid]["pins"].items():
            # 帧内布局已仿射到全局（④），此处直读全局 pin
            pos = (float(pin["position"][0]), float(pin["position"][1]))
            pins_out[pin_id] = {
                "position_m": [pos[0], pos[1]],
                "direction": [float(pin["direction"][0]),
                              float(pin["direction"][1])],
                "z_ref_ohm": float(pin["z_ref_ohm"]),
                "ref_plane_offset_m": float(pin["ref_plane_offset_m"]),
                "port_type": pin["port_type"],
                "n_modes": pin.get("n_modes"),
                "cross_section": pin["cross_section"],
                "width_m": float(pin["width_m"]),
                "exposed": (iid, pin_id) in port_map,
                "port_nr": port_map.get((iid, pin_id))}
        inst_meta.append({"id": iid, "template": inst["template"],
                          "params": dict(inst["params"]),
                          "frame": [frames[iid][0], frames[iid][1],
                                    frames[iid][2]],
                          "pins": pins_out})
    meta = {
        "schema": COMPOSE_META_SCHEMA,
        "netlist_schema": COMPOSE_NETLIST_SCHEMA,
        "netlist": nl,
        "netlist_sha256": hashlib.sha256(
            canonical_json(nl).encode("utf-8")).hexdigest(),
        "band_ghz": [float(band[0]), float(band[1])],
        "substrate": {"h_mm": float(sub["h_mm"]), "er": er, "tan_d": tan_d},
        "base_m": base_m, "near_m": near_m,
        "domain_m": {"x_half": dom_x_half, "y_min": dom[1], "y_max": dom[3]},
        "instances": inst_meta,
        "exposed_ports": emitted_ports,
        "connections": seam_notes,
        "p3_impedance_exemptions": p3_notes,
        "guards": {"D1": "ok", "D2": "ok", "D3": "ok", "D4": "ok",
                   "D5": "ok", "D6": "ok",
                   "P1": "ok", "P2": "ok", "P3": "ok", "P4": "ok",
                   "P5": "ok"},
        "estimates": {"dt_s": dt_est,
                      "dt_basis": "min(合并集近线间距, NEAR)/(c·√3) 上限口径"
                                  "（#328：真预算按终网格 CFL 实算）",
                      "nrts": nrts, "time_window_s": nrts * dt_est},
        "render_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return text, meta
