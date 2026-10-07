"""coil_nfc NFC 线圈族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import TEMPLATE_META, TEMPLATE_NOMINAL


# ─── §COIL_NFC NFC/WPC 线圈族（2026-09-26 df7 C10b，文末注册块，#304 口径）─────
# 单端口方螺旋线圈（13.56MHz NFC 频段）：FR4 类基板 + 阶梯方螺旋 + 中跳线桥
# （lange air-bridge 同法：抬高 z 越过下层走线）+ 外圈馈隙 LumpedPort 单端口
# （slotline_lumped 跨隙集总馈同源口径）。名义尺寸全闭式精算（#1c/#252）：
# L_target = 1/((2π·f0)²·C_tune)（f0=13.56MHz、C_tune=47pF 标准 NP0 档）→
# core/nfc_coil.synthesize_coil 二分反解 d_out（导入期计算非手抄）。
# 真机面：13.56MHz 全波 FDTD 预算 ~小时-天/点（MQS 频段无 MQS 求解器，
# 见 runs/df7_nfc/criteria.md §e），本批仅离线审计不发射。
def _coil_nfc_nominal_dout() -> float:
    """名义外径闭式合成（mm，导入期；core 单源，零手抄毫米数）。"""

    from rfauto.core.nfc_coil import synthesize_coil

    l_target = 1.0 / ((2.0 * math.pi * 13.56e6) ** 2 * 47e-12)
    result = synthesize_coil(l_target, "square", 7, 0.5e-3, 0.5e-3)
    return round(float(result["d_out_m"]) * 1e3, 4)


COIL_NFC_TEMPLATES: frozenset[str] = frozenset({"coil_nfc"})
_COIL_NFC_D_OUT_MM = _coil_nfc_nominal_dout()

COIL_NFC_META: dict[str, Any] = {
    "f0_ghz": 0.01356, "n_ports": 1,
    "extraction": "S11 @ LumpedPort 1（外圈馈隙桥接，R=50Ω CalcPort 同参考；"
                  "f0 谷=串联谐振 1/(2π√(L_self·C_tune))，C_tune=外匹配电容"
                  "不进几何，fake 同源 47pF 口径）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_turns", "d_out_mm", "w_mm", "s_mm", "gap_mm", "h_mm"],
    "topology": "NFC/WPC 平面线圈：FR4 类基板（无地平面）+ 阶梯方螺旋（外圈"
                "馈隙=端口位）+ 中跳线桥（抬高 z 越过螺旋，lange air-bridge "
                "同法）把内端引出到外端端口对侧——单导体通路，端口跨馈隙；"
                "全域 MUR（无地，辐射口径；13.56MHz 电小，近场主导）",
    "param_semantics": "n_turns=匝数（渲染取整），d_out_mm=外圈外缘宽（跨面宽"
                       "口径），w_mm=线宽，s_mm=匝间距，gap_mm=外圈馈隙长"
                       "（端口 y 向跨距），h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal（FR4 类）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 max(w,s,gap)/4"
                 "（MQS 频段几何驱动网格，禁 λ_sub/50 口径——13.56MHz 下"
                 "λ_sub/50≈250mm 装不下线圈）；螺旋缘/馈隙缘/桥面/过孔棱精确"
                 "入网（#198）；NEAR≤min(s,gap)/3 渲染期守卫（#266）；全轴"
                 "1µm 近重合去重（#152）；端口盒三向 ≥NEAR 厚、边全入网"
                 "（#174/#283）",
    "smoke_note": "未冒烟（离线审计过，#212，test_coil_nfc_template）；真机"
                  "发射面=13.56MHz FDTD 预算审计（runs/df7_nfc/criteria.md "
                  "§e：小时-天/点量级，建议几何等比缩放阶梯研究后由主代理"
                  "决定），本批零发射",
}
COIL_NFC_NOMINAL: dict[str, Any] = {
    "n_turns": 7,
    "d_out_mm": _COIL_NFC_D_OUT_MM,   # 导入期闭式合成（§块头注释）
    "w_mm": 0.5, "s_mm": 0.5, "gap_mm": 0.4,
    "h_mm": 1.6, "er": 4.4, "tan_d": 0.02,   # FR4 类板材
}

TEMPLATE_META["coil_nfc"] = COIL_NFC_META
TEMPLATE_NOMINAL["coil_nfc"] = COIL_NFC_NOMINAL


def _coil_nfc_layout(params: dict[str, Any],
                     freq_range_ghz: tuple[float, float],
                     mesh_resolution_mm: float = 0.0) -> dict[str, Any]:
    """coil_nfc 几何/端口/域单源（米）。

    几何拓扑（全部 z=H_SUB 顶层金属除桥/过孔）：
    - 阶梯方螺旋：turn k 中心线半宽 A_k=A_0−k·p（p=w+s），A_0=d_out/2−w/2；
      换匝过渡=内圈右边缘 p 长尾（R_k 自 y=−A_{k−1} 起）；最内圈底边止于
      x=0（内端）；
    - 中跳线桥：内端 (0,−A_{n−1}) 过孔上引 z=H+h_b，沿 −y 越过全部底边，
      再沿 +x 至 (A_0,y_pad)，过孔下引落 pad；
    - 馈隙端口：pad 顶缘 ↔ R_0 底端，y 向跨距=gap_mm（LumpedPort 盒
      x=w/z=NEAR 厚，跨 z=H 金属面对称）。
    """

    n = int(float(params.get("n_turns", COIL_NFC_NOMINAL["n_turns"])))
    if n < 1:
        raise ValueError(f"coil_nfc: n_turns 须 ≥1，收到 {n}")
    d_out = float(params.get("d_out_mm", COIL_NFC_NOMINAL["d_out_mm"])) * 1e-3
    w = float(params.get("w_mm", COIL_NFC_NOMINAL["w_mm"])) * 1e-3
    s = float(params.get("s_mm", COIL_NFC_NOMINAL["s_mm"])) * 1e-3
    gap = float(params.get("gap_mm", COIL_NFC_NOMINAL["gap_mm"])) * 1e-3
    h = float(params.get("h_mm", COIL_NFC_NOMINAL["h_mm"])) * 1e-3
    for name, v in (("d_out_mm", d_out), ("w_mm", w), ("s_mm", s),
                    ("gap_mm", gap), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"coil_nfc: {name} 必须为正有限，得到 {v!r}")
    a0 = d_out / 2.0 - w / 2.0
    pitch = w + s
    a_min = a0 - (n - 1) * pitch
    if a_min <= 2.0 * w:
        raise ValueError(
            f"coil_nfc: 几何不可行（内圈半宽 {a_min * 1e3:.4g}mm ≤ 2w，"
            "减小 n_turns 或线宽/间距）")
    # 网格：显式覆盖优先；自动档=几何驱动（MQS 频段禁 λ 口径，meta mesh_note）
    base = (max(w, s, gap) / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if near > min(s, gap) / 3.0:
        raise ValueError(
            f"coil_nfc: NEAR={near * 1e3:.4g}mm > min(s,gap)/3="
            f"{min(s, gap) / 3.0 * 1e3:.4g}mm（#266 耦合缝守卫，收紧 "
            "mesh_resolution_mm）")
    h_bridge = max(2.0 * near, base)   # 桥高（≥base，桥面独立 z 网格层）
    y_pad = -(a0 + w + gap)            # pad 中心线 y（桥落点/端口下缘）
    # 螺旋中心线段（z=H）：设计口径见 docstring
    segs: list[tuple[float, float, float, float]] = []
    for k in range(n):
        a_k = a0 - k * pitch
        if k == 0:
            segs.append((a0, -a0, a0, a0))            # R0：外端自馈隙上引
        else:
            segs.append((a_k, -(a0 - (k - 1) * pitch), a_k, a_k))  # Rk 带尾
        segs.append((a_k, a_k, -a_k, a_k))            # T_k
        segs.append((-a_k, a_k, -a_k, -a_k))          # L_k
        if k < n - 1:
            segs.append((-a_k, -a_k, a0 - (k + 1) * pitch, -a_k))  # B_k
        else:
            segs.append((-a_k, -a_k, 0.0, -a_k))      # B_{n-1} 止于内端
    via_up = (0.0, -a_min)
    via_down = (a0, y_pad)
    bridge_segs = [(0.0, -a_min, 0.0, y_pad), (0.0, y_pad, a0, y_pad)]
    dom_x = a0 + w / 2.0 + 2.0e-3
    dom_y = max(a0 + w / 2.0, -(y_pad - w / 2.0)) + 2.0e-3
    port_box = (a0 - w / 2.0, y_pad + w / 2.0, a0 + w / 2.0,
                -a0 - w / 2.0)   # x0,y0,x1,y1（y_pad+w/2 < −a0−w/2）
    if port_box[1] >= port_box[3] - 1e-12:
        raise ValueError("coil_nfc: 馈隙端口 y 跨距非正（gap_mm 过小）")
    return {
        "n": n, "d_out": d_out, "w": w, "s": s, "gap": gap, "h": h,
        "a0": a0, "pitch": pitch, "a_min": a_min,
        "base": base, "near": near, "h_bridge": h_bridge,
        "y_pad": y_pad, "segs": segs, "bridge_segs": bridge_segs,
        "via_up": via_up, "via_down": via_down,
        "port_box": port_box, "dom_x": dom_x, "dom_y": dom_y,
    }


def _coil_nfc_seg_box(x0: float, y0: float, x1: float, y1: float,
                      w: float, z: float) -> tuple[float, float, float,
                                                    float, float, float]:
    """中心线段（轴对齐）→ 金属薄盒 (x0,y0,z0,x1,y1,z1)，横向加宽 w/2。"""
    if abs(y0 - y1) <= 1e-15:      # 水平段
        return (min(x0, x1), y0 - w / 2.0, z,
                max(x0, x1), y0 + w / 2.0, z)
    return (x0 - w / 2.0, min(y0, y1), z,
            x0 + w / 2.0, max(y0, y1), z)


def coil_nfc_geometry_spec(params: dict[str, Any],
                           substrate: dict[str, Any]) -> dict[str, Any]:
    """coil_nfc UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _coil_nfc_layout(params, (0.01356, 0.01356))

    def to_mm(v: float) -> float:
        return v * 1e3
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-to_mm(lay["dom_x"]), -to_mm(lay["dom_y"]), 0.0],
         "stop_mm": [to_mm(lay["dom_x"]), to_mm(lay["dom_y"]),
                     to_mm(lay["h"])]},
        {"name": "spiral（阶梯方螺旋）", "material": "metal",
         "start_mm": [-to_mm(lay["a0"] + lay["w"] / 2.0),
                      -to_mm(lay["a0"] + lay["w"] / 2.0), to_mm(lay["h"])],
         "stop_mm": [to_mm(lay["a0"] + lay["w"] / 2.0),
                     to_mm(lay["a0"] + lay["w"] / 2.0), to_mm(lay["h"])]},
        {"name": "bridge（中跳线桥）", "material": "metal",
         "start_mm": [-to_mm(lay["w"] / 2.0), to_mm(lay["y_pad"]),
                      to_mm(lay["h"] + lay["h_bridge"])],
         "stop_mm": [to_mm(lay["w"] / 2.0), to_mm(-lay["a_min"]),
                     to_mm(lay["h"] + lay["h_bridge"])]},
    ]
    ports = [{"name": "Port1（馈隙 LumpedPort，R=50Ω）",
              "pos_mm": [to_mm(lay["a0"]),
                         to_mm((lay["port_box"][1] + lay["port_box"][3]) / 2),
                         to_mm(lay["h"])],
              "dir": [0.0, 1.0, 0.0]}]
    sub_view = dict(substrate)
    sub_view.update({"er": COIL_NFC_NOMINAL["er"],
                     "h_mm": COIL_NFC_NOMINAL["h_mm"],
                     "tan_d": COIL_NFC_NOMINAL["tan_d"]})
    return {"template": "coil_nfc", "substrate": sub_view,
            "boxes": boxes, "ports": ports, "elements": []}


def coil_nfc_render(template: str, params: dict[str, Any],
                    freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0,
                    substrate: dict[str, Any] | None = None,
                    excite_port: int = 1) -> str:
    """coil_nfc 整脚本渲染器（早分发自 render_script；slotline 族同款结构）。

    单端口（LumpedPort 跨外圈馈隙）：S11=串联谐振谷口径（f0 谷，fake 同
    源 1/(2π√(LC)) 判读）；域全 MUR；_nrts 旋钮缺省逐字节不变。
    er/tan_d/h 从 params/NOMINAL 消费（模板自带 FR4 类板材；render_script
    顶层会把缺省 substrate 重绑为 RO4350B——本族不用全局缺省板材，
    ms 族「er/tan_d 走 substrate/nominal」同口径）。
    """
    er = float(params.get("er", COIL_NFC_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", COIL_NFC_NOMINAL["tan_d"]))
    lay = _coil_nfc_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    nrts = int(params.get("_nrts", 100000) or 100000)
    # 特征线收集（全部盒的边 + 端口盒边 + 桥/过孔棱；#198 精确入网）
    trace_boxes = [_coil_nfc_seg_box(*s, lay["w"], lay["h"])
                   for s in lay["segs"]]
    bridge_boxes = [_coil_nfc_seg_box(*s, lay["w"],
                                      lay["h"] + lay["h_bridge"])
                    for s in lay["bridge_segs"]]
    w2 = lay["w"] / 2.0
    via_u = (lay["via_up"][0] - w2, lay["via_up"][1] - w2, lay["h"],
             lay["via_up"][0] + w2, lay["via_up"][1] + w2,
             lay["h"] + lay["h_bridge"])
    via_d = (lay["via_down"][0] - w2, lay["via_down"][1] - w2, lay["h"],
             lay["via_down"][0] + w2, lay["via_down"][1] + w2,
             lay["h"] + lay["h_bridge"])
    pad = (lay["a0"] - w2, lay["y_pad"] - w2, lay["a0"] + w2,
           lay["y_pad"] + w2, lay["h"])
    px0, py0, px1, py1 = lay["port_box"]
    metal_boxes = trace_boxes + bridge_boxes + [via_u, via_d]
    xs: list[float] = []
    ys: list[float] = []
    for b in metal_boxes:
        xs += [b[0], b[3]]
        ys += [b[1], b[4]]
    xs += [px0, px1, 0.0]                       # 端口盒 x 边 + 桥中线
    ys += [py0, py1, (py0 + py1) / 2.0]         # 端口盒 y 边 + 馈隙中线（#283）
    zs = [lay["h"] - lay["near"] / 2.0, lay["h"] + lay["near"] / 2.0,
          lay["h"] + lay["h_bridge"]]

    def dedup(vals: list[float]) -> list[float]:
        return sorted(set(round(float(v), 15) for v in vals))
    xs_t, ys_t, zs_t = dedup(xs), dedup(ys), dedup(zs)
    xs_lit = ", ".join(repr(v) for v in xs_t)
    ys_lit = ", ".join(repr(v) for v in ys_t)
    zs_lit = ", ".join(repr(v) for v in zs_t)
    tb_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in trace_boxes)
    bb_lit = "\n".join(
        f"bridge.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in bridge_boxes)
    via_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in (via_u, via_d))
    return f'''#!/usr/bin/env python3
"""openEMS coil_nfc script (rfauto df7 C10b auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末 COIL_NFC 段。
13.56MHz MQS 频段：几何驱动网格（禁 λ 口径），真机预算见
runs/df7_nfc/criteria.md §e。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         r"D:/rf_workspace\\\\vendor\\\\openEMS\\\\install\\\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import LumpedPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
TAND = {tan_d!r}
H_SUB = {lay["h"]!r}
H_BRIDGE = {lay["h_bridge"]!r}   # 跳线桥离板高（桥面=抬高金属层）
NEAR = {lay["near"]!r}   # 近特征区 = base/4
BASE = {lay["base"]!r}   # 网格 base：自动档 max(w,s,gap)/4（MQS 几何驱动）
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 无地平面线圈（辐射口径；13.56MHz 电小、近场主导）：全 MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 螺旋/桥/过孔/端口全部特征线精确入网（#198），先 NEAR 后 BASE 平滑，
# 域界最后补入（平滑保线，slotline 族 _axis 同款次序）
for _x in np.array([{xs_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{ys_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([{zs_lit}]))
mesh.AddLine("z", np.array([-1.5e-3, H_SUB + 2.0e-3]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：按最小间距 1µm 去重。GetLines 必须先排序：
# 上游 0.7.0 绑定 GetLines 按插入序返回（AddLine 尾插不排序，docstring
# "sorted and unique" 失实）——本脚本域界线于平滑后尾插，不排序时守卫从
# 最左特征线起步、走到尾部 -DOM 负间隙即静默丢弃域界线（首次真跑实测
# -DOM_X/-DOM_Y 双丢，x 域下界恰漂 2mm=域余量；test_template_geometry_
# audit coil_nfc 红）。排序对新引擎是修正、对旧引擎（本就有序返回）恒等。
for _ax in ("x", "y", "z"):
    _ls = np.sort(np.asarray(mesh.GetLines(_ax), dtype=float))
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：FR4 类基板（无地平面）+ 阶梯方螺旋 + 中跳线桥 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
coil = CSX.AddMetal("coil")
{tb_lit}
# 过孔×2（内端上引 / 桥端下引落 pad）
{via_lit}
# 中跳线桥（抬高 z=H+H_BRIDGE，越下层走线不接触；lange air-bridge 同法）
bridge = CSX.AddMetal("bridge")
{bb_lit}
# 端口落 pad（外圈馈隙下侧）
coil.AddBox(({pad[0]!r}, {pad[1]!r}, {pad[4]!r}), ({pad[2]!r}, {pad[3]!r}, {pad[4]!r}), priority=10)

# ── 端口：LumpedPort 跨外圈馈隙（slotline_lumped 同口径，盒三向厚、
#    对称跨 z=H 金属面；exc 沿 +y=主电流方向）──
_port1 = LumpedPort(CSX, 1, 50.0,
                    np.array([{px0!r}, {py0!r}, {lay["h"] - lay["near"] / 2.0!r}]),
                    np.array([{px1!r}, {py1!r}, {lay["h"] + lay["near"] / 2.0!r}]),
                    "y", excite=1, priority=5)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（串联谐振谷=f0 判读位；R=50Ω 同参考）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])
summary = {{
    "ok": True,
    "template": "coil_nfc",
    "f0_hz": F0, "fc_hz": FC,
    "n_turns": {lay["n"]},
    "d_out_m": {lay["d_out"]!r}, "w_m": {lay["w"]!r}, "s_m": {lay["s"]!r},
    "gap_m": {lay["gap"]!r}, "h_sub_m": H_SUB,
    "er": ER, "tan_d": TAND,
    "c_tune_pf_note": "C_tune=外匹配电容不进几何；f0 谷判读=1/(2π√(L·C))",
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "coil_nfc_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto coil_nfc simulation done")
'''
