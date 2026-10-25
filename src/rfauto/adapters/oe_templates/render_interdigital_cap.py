"""interdigital_cap 叉指电容族（aurora_k K12，反馈 F1）。

GaAs 薄膜 IPD 工艺叉指电容（IDC，梳齿互锁：n 根指条 A/B 两排交错，
汇流排两端引出，W/S/L 全 μm 标量参数）。整脚本渲染器
（octagonal_spiral 同款早分发）：左汇流排+A 排指条 / 右汇流排+B 排指条
+ 两端馈焊盘，**双 LumpedPort 水平桥隙串联口径**（Port1 跨馈盘A-左排
间隙、Port2 跨右排-馈盘B——端口串在信号通路里，S21→Z12 串联提取，
与用户 K8 Z12 提取链同口径：IDC 集总 C=去嵌后 173.5fF 实测路径）。

拓扑口径（#154 同名同语义）：两排导体 DC 隔离（梳齿互锁=定义性质，
缝塌缩短路即红——hairpin/coupled_bpf 同族判据）；e_tip 尖部外伸=B 排
指条越过 A 排指条端的外伸段（ Clears 左汇流排，不产生相邻缝、不进
闭式主项）。闭式耦合长度 l_c=lf−e_tip 与 CALC 键
interdigital_capacitance 同语义。

渲染零厚金属口径如实声明：openEMS 模板族惯例零厚金属面——缝电容以
槽平面场主导（侧壁项缺位），对 CALC 侧壁主项（t_um 参数）属跨口径
（真机批对拍留登记 内部证据档；C±50% 门在 CALC 面承载）。

闭式锚：sum-of-capacitances 侧壁平行板主项，单源 core/ipc_cap
（推导式非文献转写，±50% 精度类如实声明——K11 教训不凭记忆写
Gevorgian 系数）；质量门 C±50%/SRF>2×f0 由 CALC 键承载。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import TEMPLATE_META, TEMPLATE_NOMINAL

# ── §INTERDIGITAL_CAP GaAs IPD 叉指电容（2026-10-23 K12，文末注册块）────────
# 名义设计点=反馈 F1 用户实测参考同量级档（n=24, lf=220, wf=sf=5,
# e_tip=15μm → l_c=205μm → C_闭式=174.1fF，对用户实测 173.5fF（K8 Z12
# 去嵌后）偏差 +0.35%——±50% 门内同量级参考锚，用户几何未给全非逐位）；
# 基板 GaAs 半绝缘典型值（er=12.9/tanδ=0.0006/h=100μm，K11 同板）。
INTERDIGITAL_CAP_TEMPLATES: frozenset[str] = frozenset({"interdigital_cap"})

INTERDIGITAL_CAP_META: dict[str, Any] = {
    "f0_ghz": 2.0, "n_ports": 2,
    "extraction": "S21/S11 @ LumpedPort 1/2（馈盘A-左排 / 右排-馈盘B 水平"
                  "桥隙，R=50Ω CalcPort 同参考；串联提取：理想串联元 "
                  "Z=2·Z0·(1−S21)/S21→低频段 C=−1/(ω·Im(Z))，与 em "
                  "deembed 的 Z12 提取链同式——IDC 集总 C=去嵌后 173.5fF "
                  "实测路径；C±50%/SRF>2×f0 质量判据由 CALC 键 "
                  "interdigital_capacitance 承载）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_fingers", "lf_um", "wf_um", "sf_um", "e_tip_um",
               "h_mm"],
    "topology": "GaAs IPD 叉指电容：n 根指条 A/B 两排交错（A 排接左汇流"
                "排、B 排接右汇流排，B 排指条外伸 e_tip 越 A 排指条端），"
                "两端馈焊盘+双 LumpedPort 水平桥隙（Port1 跨馈盘A-左排、"
                "Port2 跨右排-馈盘B，串联口径 Z=2·Z0(1−S21)/S21）；两排"
                "导体 DC 隔离（梳齿互锁=定义性质，缝塌缩短路即红）；全域 "
                "MUR（电小器件近场主导）",
    "param_semantics": "n_fingers=总齿数 N（渲染取整，≥2 且 A/B 排各 "
                       "N/2），lf_um=齿长 L（μm），wf_um=齿宽 W（μm），"
                       "sf_um=齿间距 S（μm），e_tip_um=B 排尖部外伸（μm，"
                       " Clears 左汇流排、不产生相邻缝；闭式耦合长度 "
                       "l_c=lf−e_tip），h_mm=基板厚（仓内基板惯例 mm，"
                       "GaAs 100μm 档）；er/tan_d 走 substrate/nominal"
                       "（GaAs 半绝缘）——N/L/W/S 全 μm 为 IPD 工艺口径，"
                       "经 core.stackup.to_mm(v,'um') 单源换算（μm 帮手"
                       "函数）；"
                       "汇流排宽=wf、馈盘宽=3·wf（派生值不单列参数）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 "
                 "max(wf,sf,port_gap)/4（μm 尺度几何驱动网格，禁 λ_sub/50 "
                 "口径）；齿缘/汇流排/馈盘/端口盒边+中线精确入网（#198）；"
                 "NEAR≤min(sf,port_gap)/3 渲染期守卫（#266）；全轴 1µm 近"
                 "重合去重（#152）；端口盒三向 ≥NEAR 厚、激励向 ≥2 格"
                 "（#174/#283）",
    "smoke_note": "未冒烟（离线审计过，#212，test_k12_ipc_caps）；真机发射"
                  "留登记（C/SRF 串联提取对拍+渲染零厚 vs CALC 侧壁 t_um "
                  "差异注记待真机批，本批零发射）",
}
INTERDIGITAL_CAP_NOMINAL: dict[str, Any] = {
    "n_fingers": 24,
    "lf_um": 220.0,
    "wf_um": 5.0,
    "sf_um": 5.0,
    "e_tip_um": 15.0,
    "h_mm": 0.1,   # GaAs 100μm 薄膜 IPD 档（仓内基板惯例 mm）
    "er": 12.9, "tan_d": 0.0006,   # GaAs 半绝缘典型值
}

TEMPLATE_META["interdigital_cap"] = INTERDIGITAL_CAP_META
TEMPLATE_NOMINAL["interdigital_cap"] = INTERDIGITAL_CAP_NOMINAL


def _interdigital_cap_layout(params: dict[str, Any],
                             freq_range_ghz: tuple[float, float],
                             mesh_resolution_mm: float = 0.0) -> dict[str, Any]:
    """interdigital_cap 几何/端口/域单源（米）。

    几何拓扑（全部 z=H 顶层金属零厚面）：
    - 汇流排 A：x∈[0,w_bus]；A 排指条（偶序 i）x∈[w_bus, w_bus+lf]；
    - B 排指条（奇序 i）x∈[w_bus+e_tip, w_bus+e_tip+lf]（尖部外伸 e_tip
      Clears 左汇流排）；汇流排 B：x∈[w_bus+e_tip+lf, +w_bus]；
    - 馈盘 A/B（宽 3·wf）+ 双端口桥隙（跨距 port_gap=sf，串联口径）。
    耦合长度 l_c=lf−e_tip 与 CALC 键同语义（#154）。
    """
    from rfauto.core.stackup import assert_thin_layer, to_mm

    n = round(float(params.get("n_fingers",
                               INTERDIGITAL_CAP_NOMINAL["n_fingers"])) / 2.0) * 2
    if n < 2:
        raise ValueError(
            f"interdigital_cap: n_fingers 须为 ≥2（渲染取整到最近偶数——"
            f"A/B 排各半），收到 {params.get('n_fingers')!r}")
    # μm 参数经 to_mm(v,"um") 单源换算（IPD 工艺口径）
    lf = to_mm(float(params.get("lf_um",
                                INTERDIGITAL_CAP_NOMINAL["lf_um"])), "um") * 1e-3
    wf = to_mm(float(params.get("wf_um",
                                INTERDIGITAL_CAP_NOMINAL["wf_um"])), "um") * 1e-3
    sf = to_mm(float(params.get("sf_um",
                                INTERDIGITAL_CAP_NOMINAL["sf_um"])), "um") * 1e-3
    e_tip = to_mm(float(params.get("e_tip_um",
                                   INTERDIGITAL_CAP_NOMINAL["e_tip_um"])), "um") * 1e-3
    h = float(params.get("h_mm",
                         INTERDIGITAL_CAP_NOMINAL["h_mm"])) * 1e-3
    for name, v in (("lf_um", lf), ("wf_um", wf), ("sf_um", sf),
                    ("e_tip_um", e_tip), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"interdigital_cap: {name} 必须为正有限，得到 {v!r}")
    # P7 薄层朝向守卫接线（E1，aurora_l）：GaAs 薄膜基板盒（0.1mm 档，
    # h << 足迹——薄层朝向域）z 跨度 vs 声明厚度（h_mm→to_mm("mm")→mm→
    # ×1e-3 m 单源换算，K12 换算惯例同款）。金属梳齿=零厚面（z 跨度恒 0，
    # 无薄层厚度可校验——CALC 侧壁项 t_um 不进渲染，跨口径声明见模块头）
    # 如实跳过；介质薄层本模板无（并联空气口径），P7 主病灶面=mim_cap。
    assert_thin_layer(
        h,
        to_mm(float(params.get("h_mm",
                                INTERDIGITAL_CAP_NOMINAL["h_mm"])), "mm") * 1e-3,
        axis="z")
    l_c = lf - e_tip
    if l_c <= 0.0:
        raise ValueError(
            f"interdigital_cap: 耦合长度 l_c=lf−e_tip={l_c * 1e6:.4g}μm ≤0"
            "（减小 e_tip_um 或增大 lf_um）")
    if e_tip < sf:
        raise ValueError(
            f"interdigital_cap: e_tip={e_tip * 1e6:.4g}μm < sf="
            f"{sf * 1e6:.4g}μm（B 排尖部与左汇流排间距须 ≥sf）")
    w_bus = wf                       # 汇流排宽=齿宽（派生值，meta 已声明）
    pw = 3.0 * wf                    # 馈盘宽=3×齿宽（派生值，meta 已声明）
    gp = sf                          # 端口桥隙跨距=齿间距（派生值）
    pitch = wf + sf
    y_span = n * pitch - sf          # 齿条组 y 向总跨（首末齿外缘）
    y0 = -y_span / 2.0
    fingers_a: list[tuple[float, float, float, float]] = []
    fingers_b: list[tuple[float, float, float, float]] = []
    for i in range(n):
        yc = y0 + (i + 0.5) * pitch
        if i % 2 == 0:
            fingers_a.append((w_bus, yc - wf / 2.0, w_bus + lf, yc + wf / 2.0))
        else:
            fingers_b.append((w_bus + e_tip, yc - wf / 2.0,
                              w_bus + e_tip + lf, yc + wf / 2.0))
    bus_a = (0.0, y0, w_bus, y0 + y_span)
    x_bus_b0 = w_bus + e_tip + lf
    bus_b = (x_bus_b0, y0, x_bus_b0 + w_bus, y0 + y_span)
    pad_a = (-gp - pw, -pw / 2.0, -gp, pw / 2.0)
    x_pad_b0 = x_bus_b0 + w_bus + gp
    pad_b = (x_pad_b0, -pw / 2.0, x_pad_b0 + pw, pw / 2.0)
    port1 = (-gp, -pw / 2.0, 0.0, pw / 2.0)     # x0,y0,x1,y1（z 向 H±near/2）
    port2 = (x_bus_b0 + w_bus, -pw / 2.0, x_pad_b0, pw / 2.0)
    # 网格：显式覆盖优先；自动档=几何驱动（μm 尺度禁 λ 口径）
    base = (max(wf, sf, gp) / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if near > min(sf, gp) / 3.0:
        raise ValueError(
            f"interdigital_cap: NEAR={near * 1e6:.4g}μm > min(sf,gp)/3="
            f"{min(sf, gp) / 3.0 * 1e6:.4g}μm（#266 耦合缝守卫，收紧 "
            "mesh_resolution_mm）")
    x_min = pad_a[0]
    x_max = pad_b[2]
    margin = max(x_max - x_min, y_span) / 2.0    # 电小器件近场主导余量
    dom_x = x_max + margin
    dom_y = y_span / 2.0 + margin
    return {
        "n": n, "lf": lf, "wf": wf, "sf": sf, "e_tip": e_tip, "h": h,
        "l_c": l_c, "w_bus": w_bus, "pw": pw, "gp": gp, "pitch": pitch,
        "y_span": y_span, "y0": y0, "fingers_a": fingers_a,
        "fingers_b": fingers_b, "bus_a": bus_a, "bus_b": bus_b,
        "pad_a": pad_a, "pad_b": pad_b, "port1": port1, "port2": port2,
        "base": base, "near": near, "dom_x": dom_x, "dom_y": dom_y,
    }


def interdigital_cap_geometry_spec(params: dict[str, Any],
                                   substrate: dict[str, Any]) -> dict[str, Any]:
    """interdigital_cap UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _interdigital_cap_layout(params, (2.0, 2.0))

    def mm(v: float) -> float:
        return v * 1e3
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-mm(lay["dom_x"]), -mm(lay["dom_y"]), 0.0],
         "stop_mm": [mm(lay["dom_x"]), mm(lay["dom_y"]), mm(lay["h"])]},
        {"name": "bus_a（左汇流排）", "material": "metal",
         "start_mm": [mm(lay["bus_a"][0]), mm(lay["bus_a"][1]), mm(lay["h"])],
         "stop_mm": [mm(lay["bus_a"][2]), mm(lay["bus_a"][3]), mm(lay["h"])]},
        {"name": "bus_b（右汇流排）", "material": "metal",
         "start_mm": [mm(lay["bus_b"][0]), mm(lay["bus_b"][1]), mm(lay["h"])],
         "stop_mm": [mm(lay["bus_b"][2]), mm(lay["bus_b"][3]), mm(lay["h"])]},
        {"name": "fingers（梳齿互锁，外接框）", "material": "metal",
         "start_mm": [mm(lay["w_bus"]), mm(lay["y0"]), mm(lay["h"])],
         "stop_mm": [mm(lay["w_bus"] + lay["e_tip"] + lay["lf"]),
                     mm(lay["y0"] + lay["y_span"]), mm(lay["h"])]},
        {"name": "pad_a（馈盘 A）", "material": "metal",
         "start_mm": [mm(lay["pad_a"][0]), mm(lay["pad_a"][1]), mm(lay["h"])],
         "stop_mm": [mm(lay["pad_a"][2]), mm(lay["pad_a"][3]), mm(lay["h"])]},
        {"name": "pad_b（馈盘 B）", "material": "metal",
         "start_mm": [mm(lay["pad_b"][0]), mm(lay["pad_b"][1]), mm(lay["h"])],
         "stop_mm": [mm(lay["pad_b"][2]), mm(lay["pad_b"][3]), mm(lay["h"])]},
    ]
    ports = []
    for k, pb in ((1, lay["port1"]), (2, lay["port2"])):
        ports.append({
            "name": f"Port{k}（水平桥隙 LumpedPort，R=50Ω，串联口径）",
            "pos_mm": [mm((pb[0] + pb[2]) / 2.0), mm((pb[1] + pb[3]) / 2.0),
                       mm(lay["h"])],
            "dir": [1.0, 0.0, 0.0]})
    sub_view = dict(substrate)
    sub_view.update({"er": INTERDIGITAL_CAP_NOMINAL["er"],
                     "h_mm": INTERDIGITAL_CAP_NOMINAL["h_mm"],
                     "tan_d": INTERDIGITAL_CAP_NOMINAL["tan_d"]})
    return {"template": "interdigital_cap", "substrate": sub_view,
            "boxes": boxes, "ports": ports, "elements": []}


def interdigital_cap_render(template: str, params: dict[str, Any],
                            freq_range_ghz: tuple[float, float],
                            mesh_resolution_mm: float = 0.0,
                            substrate: dict[str, Any] | None = None,
                            excite_port: int = 1) -> str:
    """interdigital_cap 整脚本渲染器（早分发自 render_script）。

    双端口（LumpedPort 水平桥隙 ×2，串联口径）：低频段 S21→
    Z=2·Z0·(1−S21)/S21 → C=−1/(ω·Im(Z)) 提取（K8 Z12 链同口径）；
    渲染零厚金属 vs CALC 侧壁 t_um 跨口径如实声明（模块头）。域全 MUR；
    _nrts 旋钮缺省逐字节不变。er/tan_d 走 params/NOMINAL（GaAs）。
    """
    del substrate   # 板材走 params/NOMINAL（GaAs），显式弃用全局缺省
    er = float(params.get("er", INTERDIGITAL_CAP_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", INTERDIGITAL_CAP_NOMINAL["tan_d"]))
    lay = _interdigital_cap_layout(params, freq_range_ghz, mesh_resolution_mm)
    ep = max(1, min(2, int(params.get("_excite_port", excite_port) or 1)))
    if int(excite_port) != ep:
        raise ValueError(
            f"interdigital_cap: excite_port={excite_port!r} 越域"
            "（2 端口模板合法 1..2；整 S 矩阵由 openems_rotation 进程隔离"
            "轮转 #208）")
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    nrts = int(params.get("_nrts", 100000) or 100000)
    # 特征线收集（#198）：齿缘/汇流排/馈盘/端口盒边+中线
    xs: list[float] = [lay["bus_a"][0], lay["bus_a"][2],
                       lay["bus_b"][0], lay["bus_b"][2],
                       lay["pad_a"][0], lay["pad_a"][2],
                       lay["pad_b"][0], lay["pad_b"][2],
                       lay["port1"][0], lay["port1"][2],
                       lay["port2"][0], lay["port2"][2],
                       (lay["port1"][0] + lay["port1"][2]) / 2.0,
                       (lay["port2"][0] + lay["port2"][2]) / 2.0]
    ys: list[float] = [lay["bus_a"][1], lay["bus_a"][3],
                       lay["pad_a"][1], lay["pad_a"][3],
                       lay["port1"][1], lay["port1"][3]]
    for f_ in lay["fingers_a"] + lay["fingers_b"]:
        xs += [f_[0], f_[2]]
        ys += [f_[1], f_[3]]
    zs = [lay["h"] - lay["near"] / 2.0, lay["h"] + lay["near"] / 2.0]

    def dedup(vals: list[float]) -> list[float]:
        return sorted(set(round(float(v), 15) for v in vals))
    xs_t, ys_t, zs_t = dedup(xs), dedup(ys), dedup(zs)
    xs_lit = ", ".join(repr(v) for v in xs_t)
    ys_lit = ", ".join(repr(v) for v in ys_t)
    zs_lit = ", ".join(repr(v) for v in zs_t)
    fa_lit = "\n".join(
        f"idc.AddBox(({b[0]!r}, {b[1]!r}, H_SUB), ({b[2]!r}, {b[3]!r}, H_SUB), "
        "priority=10)" for b in lay["fingers_a"])
    fb_lit = "\n".join(
        f"idc.AddBox(({b[0]!r}, {b[1]!r}, H_SUB), ({b[2]!r}, {b[3]!r}, H_SUB), "
        "priority=10)" for b in lay["fingers_b"])
    return f'''#!/usr/bin/env python3
"""openEMS interdigital_cap script (rfauto aurora_k K12 auto-generated).

几何/端口/网格口径见
src/rfauto/adapters/oe_templates/render_interdigital_cap.py 模块头。
GaAs IPD μm 工艺叉指电容：双端口串联口径（Z=2·Z0(1−S21)/S21，K8 Z12
链同口径），μm 参数经 core.stackup.to_mm(v,"um") 单源换算。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         "D:/rf_workspace/vendor/openEMS/install/bin")
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
NEAR = {lay["near"]!r}   # 近特征区 = base/4
BASE = {lay["base"]!r}   # 网格 base：自动档 max(wf,sf,gp)/4（μm 几何驱动）
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 电小器件近场主导：全 MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 齿缘/汇流排/馈盘/端口盒边+中线精确入网（#198），先 NEAR 后域界
# （octagonal_spiral 同款次序）
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
mesh.AddLine("z", np.array([-0.5 * (DOM_X - NEAR), H_SUB + 0.5 * (DOM_X - NEAR)]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152×#198 联合）：显式特征线（齿缘/汇流排/馈盘/
# 端口盒边+中线，_feat_* 保护集）全部保留（nm 级自去重），其余平滑产物
# 线只在距全部已保留线 >1µm 时收编——特征线永不被去重吞掉（否则端口盒
# 边/齿缘落格漂移 ≤1µm，#283 探针吸附面），且终集无 <1µm 近重合线。
# GetLines 必须先排序：上游 0.7.0 绑定按插入序返回（docstring "sorted
# and unique" 失实，octagonal_spiral 首次真跑实证）。
_feat_x = np.array([{xs_lit}])
_feat_y = np.array([{ys_lit}])
_feat_z = np.array([{zs_lit}])
for _ax, _feat in (("x", _feat_x), ("y", _feat_y), ("z", _feat_z)):
    _ls = np.sort(np.asarray(mesh.GetLines(_ax), dtype=float))
    _keep: list = []
    for _v in np.sort(np.unique(np.round(_feat, 12))):
        if not _keep or _v - _keep[-1] > 1e-9:
            _keep.append(float(_v))
    for _v in _ls:
        if all(abs(_v - _k) > 1e-6 for _k in _keep):
            _keep.append(float(_v))
            _keep.sort()
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：GaAs 基板 + 汇流排×2 + 梳齿×{lay["n"]} + 馈盘×2 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
idc = CSX.AddMetal("idc")
# A 排指条（偶序，接左汇流排）
{fa_lit}
# B 排指条（奇序，接右汇流排；尖部外伸 E_TIP Clears 左汇流排）
{fb_lit}
# 汇流排×2
idc.AddBox(({lay["bus_a"][0]!r}, {lay["bus_a"][1]!r}, H_SUB), ({lay["bus_a"][2]!r}, {lay["bus_a"][3]!r}, H_SUB), priority=10)
idc.AddBox(({lay["bus_b"][0]!r}, {lay["bus_b"][1]!r}, H_SUB), ({lay["bus_b"][2]!r}, {lay["bus_b"][3]!r}, H_SUB), priority=10)
# 馈盘×2
idc.AddBox(({lay["pad_a"][0]!r}, {lay["pad_a"][1]!r}, H_SUB), ({lay["pad_a"][2]!r}, {lay["pad_a"][3]!r}, H_SUB), priority=10)
idc.AddBox(({lay["pad_b"][0]!r}, {lay["pad_b"][1]!r}, H_SUB), ({lay["pad_b"][2]!r}, {lay["pad_b"][3]!r}, H_SUB), priority=10)

# ── 端口：LumpedPort ×2 水平桥隙（串联口径，盒三向厚、对称跨 z=H
#    金属面；exc 沿 +x=主电流方向；主激励=_port{ep}，他端 excite=0，
#    整 S 矩阵由 openems_rotation 进程隔离轮转 #208）──
_port1 = LumpedPort(CSX, 1, 50.0,
                    np.array([{lay["port1"][0]!r}, {lay["port1"][1]!r}, {lay["h"] - lay["near"] / 2.0!r}]),
                    np.array([{lay["port1"][2]!r}, {lay["port1"][3]!r}, {lay["h"] + lay["near"] / 2.0!r}]),
                    "x", excite={1 if ep == 1 else 0}, priority=5)
_port2 = LumpedPort(CSX, 2, 50.0,
                    np.array([{lay["port2"][0]!r}, {lay["port2"][1]!r}, {lay["h"] - lay["near"] / 2.0!r}]),
                    np.array([{lay["port2"][2]!r}, {lay["port2"][3]!r}, {lay["h"] + lay["near"] / 2.0!r}]),
                    "x", excite={1 if ep == 2 else 0}, priority=5)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：port{ep} 激励单口径 S11/S21（Z=2·Z0(1−S21)/S21 串联提取，
#    K8 Z12 链同口径；全矩阵经 openems_rotation 进程隔离轮转 #208）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
_port2.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port{ep}.uf_ref / _port{ep}.uf_inc
S21 = _port{3 - ep}.uf_ref / _port{ep}.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag,
                     S21[_i].real, S21[_i].imag])
summary = {{
    "ok": True,
    "template": "interdigital_cap",
    "f0_hz": F0, "fc_hz": FC,
    "n_fingers": {lay["n"]},
    "lf_m": {lay["lf"]!r}, "wf_m": {lay["wf"]!r}, "sf_m": {lay["sf"]!r},
    "e_tip_m": {lay["e_tip"]!r}, "l_c_m": {lay["l_c"]!r},
    "w_bus_m": {lay["w_bus"]!r}, "pad_w_m": {lay["pw"]!r},
    "port_gap_m": {lay["gp"]!r},
    "h_sub_m": H_SUB,
    "er": ER, "tan_d": TAND,
    "judgement_note": "串联提取：Z=2·Z0(1−S21)/S21→C=−1/(ω·Im(Z)) 低频段"
                      "（Z12 提取链同式）；渲染零厚金属 vs CALC 侧壁 "
                      "t_um 差异如实声明（render 模块头）；质量判据 C±50%/"
                      "SRF>2×f0 见 CALC interdigital_capacitance",
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "interdigital_cap_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto interdigital_cap simulation done")
'''
