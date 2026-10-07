"""pyramid_horn 角锥喇叭族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

# ═══ §ME-7 角锥喇叭 pyramid_horn（2026-09-26 ME-7 离线段，文末注册块）══════════
# 方案锚：月度增强方案 §三 A 流 ME-7——标准增益
# 公式综合入 core（core/horn_synthesis.py，Orfanidis Ch.21 × Balanis Ch.13
# 双源闭式，锚例 Ex21.5.1/21.5.2 钉）+ openEMS 全波验证（方向图/真机冒烟=
# Ph3 窗，本批零发射）。波纹喇叭按方案降级处理（不排）。
# 几何（轴 +y，喉部面 y=0，口径面 y=l_flare）：WR 波导馈电直管（y∈
# [−DOM_Y,0]，四壁 PEC，端口面贴 y=−DOM_Y PML_8 域边）+ 四壁梯形喇叭
# 口径（H 面宽沿 x a→a1、E 面高沿 z b→b1）。FDTD 只支持轴对齐盒：斜壁以
# N_SEG 段矩形截面阶梯链逼近（段间阶梯框面闭合，链内全 PEC 封闭腔；段
# 半尺寸取段中截面——阶梯化近似如实登记 meta smoke_note）。
# 名义值：导入期由 synthesize_pyramid_horn（15 dB@10 GHz WR-90，Balanis
# 最优厚度档 σh=√1.5/σe=1 ⇔ δ_H=3λ/8、δ_E=λ/4）精算字面落表（coil_nfc
# 同款，避免名义手抄毫米数 #1c）。
# 端口：RectWGPort 解析 TE10 模式（Pozar 模式函数，openEMS.ports 原生）。
# **绑定参数序**：a=第一横向轴（exc_dir=y 时=z）、b=第二横向轴（=x）——
# 本喇叭物理宽边沿 x（E 场沿 z）⇒ 绑定 a=b_phys、b=a_phys、mode="TE01"
# （M=0,N=1：E 沿 z、半波沿 x，kc=π/a_phys 由绑定自算，审计测试钉 kc）。
# 空气填充（无介质板）：RectWGPort.CalcPort 解析 β 按 C0 真空口径自洽；
# er=1.0 只进渲染脚本 summary 的 TE10 截止/波导波长回显，h_mm=0.0 为
# 无介质板器件占位键（审计④矩形域分支口径），二者均不动导体几何
# （MATERIAL_VALUE_PARAMS 豁免登记）。
# 边界：y 轴（端口轴）双端 PML_8（#154 端口面贴 PML_8 口径），x/z MUR。

#: 角锥喇叭族模板名集（render_script/geometry_spec 早分发，mmwave 同款）
PYRAMID_HORN_TEMPLATES: frozenset[str] = frozenset({"pyramid_horn"})

#: 阶梯化分段数（斜壁→矩形截面链；段中截面采样，8 段对 15 dB 档阶梯
#: ≥2.9mm ≫ 网格 NEAR，阶梯化误差由 Ph3 网格收敛研究定档）
_PYRAMID_HORN_N_SEG = 8
#: 侧向/口径向空气余量（mm，≈λ0/4@10GHz+4mm 的圆整档）
_PYRAMID_HORN_AIR_MARGIN_MM = 11.5
#: 馈电直管最短长（mm；渲染时实际管长=max(l_feed, l_flare+λ0/4+4mm)——
#: 口径侧空气域余量自动保证 #174 族，单参数扰动可独立成立；60 为名义档）
_PYRAMID_HORN_L_FEED_MM = 60.0


def _pyramid_horn_nominal() -> dict[str, Any]:
    """名义设计点（mm，导入期综合单源，零手抄毫米数 #1c）。"""
    from rfauto.core.horn_synthesis import synthesize_pyramid_horn

    r = synthesize_pyramid_horn(15.0, 10.0, "WR-90")
    return {
        "a_mm": r["a_mm"],
        "b_mm": r["b_mm"],
        "a1_mm": r["a1_mm"],
        "b1_mm": r["b1_mm"],
        "l_feed_mm": _PYRAMID_HORN_L_FEED_MM,
        "l_flare_mm": r["l_mm"],
        "er": 1.0,
        "h_mm": 0.0,
    }


PYRAMID_HORN_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 1,
    "extraction": "S11 @ RectWGPort 1（解析 TE10 模式端口，Z_ref=解析波导"
                  "阻抗 ZL=k·Z0/β 口径）；增益判读=口径场闭式"
                  "（core/horn_synthesis）对照，方向图/nf2ff=Ph3 真机窗",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["a_mm", "b_mm", "a1_mm", "b1_mm", "l_feed_mm", "l_flare_mm"],
    "topology": "标准增益角锥喇叭：WR-90 波导馈电直管（端口面贴 y=−DOM_Y "
                "PML_8 域边）+ 四壁梯形口径段（喉部 y=0、口径 y=l_flare；"
                "H 面宽沿 x a→a1、E 面高沿 z b→b1）；斜壁以 8 段矩形截面"
                "阶梯链逼近（段间框面闭合=全 PEC 封闭腔）；空气填充无介质"
                "板，y 轴双端 PML_8、x/z MUR",
    "param_semantics": "a_mm=波导口宽边（H 面，x 向，WR 口径）；b_mm=波导口"
                       "窄边（E 面，z 向）；a1_mm=口径宽边（H 面，综合目标"
                       "增益下 Orfanidis(21.5.1)+Balanis δ_H=3λ/8 设计方程"
                       "解）；b1_mm=口径窄边（E 面，δ_E=λ/4 同链）；"
                       "l_feed_mm=馈电直管最短长（实际管长=max(l_feed, "
                       "l_flare+λ0/4+4mm) 口径侧空气域自动保证）；"
                       "l_flare_mm=喇叭轴向长（同设计链）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50"
                 "（空气口径，官方 base 级）；NEAR=base/4；全部壁面站线"
                 "（波导口缘/逐段截面缘/阶梯框/口径面/端口面）显式入网"
                 "（#198）+ 全轴 1µm 近重合去重（#152）；渲染守卫：阶梯"
                 "步距 ≥4·NEAR（#266 族）、a1>a 且 b1>b；口径侧空气域 "
                 "≥λ0/4+4mm 由管长自动外推保证（#174 族）",
    "smoke_note": "未冒烟（离线审计过，#212，test_pyramid_horn_template）；"
                  "近似级别如实登记：①斜壁 8 段阶梯化（矩形截面链，段中"
                  "截面采样）；②闭式口径面模型不含壁损耗/口面反射/边缘"
                  "绕射；③方向图/nf2ff 与真机冒烟=Ph3 窗（本批零发射）",
}


def _pyramid_horn_layout(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """角锥喇叭几何/端口/域/网格单源（mm 入出；渲染器/预览 spec 同消费）。

    守卫（渲染期显式抛错）：口径>波导口、阶梯步距 ≥4·NEAR（#266 族）；
    口径侧空气域 ≥λ0/4+4mm 由管长自动外推保证（#174 族，l_feed 语义=
    最短长）。
    """
    nom = PYRAMID_HORN_NOMINAL
    a_mm = float(params.get("a_mm", nom["a_mm"]))
    b_mm = float(params.get("b_mm", nom["b_mm"]))
    a1_mm = float(params.get("a1_mm", nom["a1_mm"]))
    b1_mm = float(params.get("b1_mm", nom["b1_mm"]))
    l_feed_mm = float(params.get("l_feed_mm", nom["l_feed_mm"]))
    l_flare_mm = float(params.get("l_flare_mm", nom["l_flare_mm"]))
    er = float(params.get("er", nom["er"]))
    if a1_mm <= a_mm or b1_mm <= b_mm:
        raise ValueError(
            f"pyramid_horn: 口径必须大于波导口（a1={a1_mm:.3f} vs "
            f"a={a_mm:.3f}, b1={b1_mm:.3f} vs b={b_mm:.3f}）")
    f0 = 0.5 * (freq_range_ghz[0] + freq_range_ghz[1])
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2.0
    lambda0_mm = 299.792458 / (f0 + fc)   # 频带最高频空气波长（保守 base）
    base_mm = (float(mesh_resolution_mm) if mesh_resolution_mm
               else lambda0_mm / 50.0)
    near_mm = base_mm / 4.0
    step_x = (a1_mm - a_mm) / 2.0 / _PYRAMID_HORN_N_SEG
    step_z = (b1_mm - b_mm) / 2.0 / _PYRAMID_HORN_N_SEG
    if min(step_x, step_z) < 4.0 * near_mm:
        raise ValueError(
            f"pyramid_horn: 阶梯步距 {min(step_x, step_z):.4f}mm < "
            f"4·NEAR={4.0 * near_mm:.4f}mm（#266 族守卫）——请加密 "
            f"mesh_resolution_mm 或增减口径")
    air_need = lambda0_mm / 4.0 + 4.0
    # 馈电直管长：l_feed 语义=最短长——l_flare 扰动/综合变化时自动外推，
    # 保证口径侧空气域 ≥λ0/4+4mm（#174 族；单参数扰动可独立成立）
    tube_mm = max(l_feed_mm, l_flare_mm + air_need)
    dom_x_mm = a1_mm / 2.0 + _PYRAMID_HORN_AIR_MARGIN_MM
    dom_y_mm = tube_mm
    dom_z_mm = b1_mm / 2.0 + _PYRAMID_HORN_AIR_MARGIN_MM
    # 阶梯段：截面半尺寸取段中截面（线性锥的阶梯化，#198 逐段盒）
    n = _PYRAMID_HORN_N_SEG
    xh = [a_mm / 2.0 + (a1_mm - a_mm) / 2.0 * (k + 0.5) / n
          for k in range(n)]
    zh = [b_mm / 2.0 + (b1_mm - b_mm) / 2.0 * (k + 0.5) / n
          for k in range(n)]
    yk = [l_flare_mm * k / n for k in range(n + 1)]
    boxes: list[tuple[str, float, float, float, float, float, float]] = []
    # 馈电直管四壁（y∈[−dom_y, 0]；零厚 PEC 片）
    boxes += [
        ("feed_wall_xp", a_mm / 2, -dom_y_mm, -b_mm / 2,
         a_mm / 2, 0.0, b_mm / 2),
        ("feed_wall_xm", -a_mm / 2, -dom_y_mm, -b_mm / 2,
         -a_mm / 2, 0.0, b_mm / 2),
        ("feed_wall_zp", -a_mm / 2, -dom_y_mm, b_mm / 2,
         a_mm / 2, 0.0, b_mm / 2),
        ("feed_wall_zm", -a_mm / 2, -dom_y_mm, -b_mm / 2,
         a_mm / 2, 0.0, -b_mm / 2),
    ]
    for k in range(n):
        y0, y1 = yk[k], yk[k + 1]
        xk, zk = xh[k], zh[k]
        boxes += [
            (f"flare{k}_wall_xp", xk, y0, -zk, xk, y1, zk),
            (f"flare{k}_wall_xm", -xk, y0, -zk, -xk, y1, zk),
            (f"flare{k}_wall_zp", -xk, y0, zk, xk, y1, zk),
            (f"flare{k}_wall_zm", -xk, y0, -zk, xk, y1, -zk),
        ]
        # 段间阶梯框面（y=y0 平面，环形四块，闭合腔壁零泄漏）；k=0 的框
        # 面补馈电口（段中截面采样使首段截面 > 波导口，缺框=喉部环形开口
        # 腔断为两分量，#212 连通性审计实测抓出）
        xp, zp = ((a_mm / 2, b_mm / 2) if k == 0
                  else (xh[k - 1], zh[k - 1]))
        boxes += [
            (f"frame{k}_zp", -xk, y0, zp, xk, y0, zk),
            (f"frame{k}_zm", -xk, y0, -zk, xk, y0, -zp),
            (f"frame{k}_xp", xp, y0, -zp, xk, y0, zp),
            (f"frame{k}_xm", -xk, y0, -zp, -xp, y0, zp),
        ]
    # 端口面纪律（审查轨 B P0-1）：WaveguidePort 的激励盒在 start 面、
    # 模式匹配探针在 stop 面（openEMS ports.py L427-534）——两面都必须在
    # PML_8 之外的物理域内（PML 占域内首/末 8 胞，非域外追加）。
    # 端口内移 ≥16·BASE（slotline_template 纪律），meas_len 同步抬下限。
    port_inset_mm = 16.0 * base_mm
    meas_len_mm = max(6.0 * near_mm, 1.0, port_inset_mm)
    if dom_y_mm < port_inset_mm + meas_len_mm + 4.0 * base_mm:
        # 馈管必须容纳端口两面+余量（l_feed 语义=最短长，#174 族自动外推）
        dom_y_mm = port_inset_mm + meas_len_mm + 4.0 * base_mm
    port_y0_mm = -dom_y_mm + port_inset_mm
    port_y1_mm = port_y0_mm + meas_len_mm
    x_lines = sorted({v for k in range(n) for v in (xh[k], -xh[k])}
                     | {a_mm / 2, -a_mm / 2})
    z_lines = sorted({v for k in range(n) for v in (zh[k], -zh[k])}
                     | {b_mm / 2, -b_mm / 2})
    y_lines = sorted({-dom_y_mm, port_y0_mm, port_y1_mm, 0.0} | set(yk))
    return {
        "a_mm": a_mm, "b_mm": b_mm, "a1_mm": a1_mm, "b1_mm": b1_mm,
        "l_feed_mm": l_feed_mm, "l_flare_mm": l_flare_mm, "er": er,
        "f0_ghz": f0, "fc_ghz": fc, "lambda0_mm": lambda0_mm,
        "base_mm": base_mm, "near_mm": near_mm,
        "dom_x_mm": dom_x_mm, "dom_y_mm": dom_y_mm, "dom_z_mm": dom_z_mm,
        "n_seg": n, "boxes": boxes,
        "x_lines_mm": x_lines, "y_lines_mm": y_lines, "z_lines_mm": z_lines,
        "meas_len_mm": meas_len_mm,
        "port": {"start_mm": [-a_mm / 2, port_y0_mm, -b_mm / 2],
                 "stop_mm": [a_mm / 2, port_y1_mm, b_mm / 2],
                 # 绑定 a=第一横向轴(z)=b_phys、b=第二横向轴(x)=a_phys
                 "a_bind_mm": b_mm, "b_bind_mm": a_mm},
    }


def pyramid_horn_geometry_spec(
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """pyramid_horn UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    del substrate   # 空气填充器件，无板材（段头注释）
    lay = _pyramid_horn_layout(
        params, (PYRAMID_HORN_META["f0_ghz"], PYRAMID_HORN_META["f0_ghz"]))
    a, b = lay["a_mm"], lay["b_mm"]
    a1, b1 = lay["a1_mm"], lay["b1_mm"]
    lf, lfed = lay["l_flare_mm"], lay["dom_y_mm"]
    boxes = [
        {"name": "feed_wall_xp（波导馈电段）", "material": "metal",
         "start_mm": [a / 2, -lfed, -b / 2], "stop_mm": [a / 2, 0.0, b / 2]},
        {"name": "feed_wall_xm（波导馈电段）", "material": "metal",
         "start_mm": [-a / 2, -lfed, -b / 2],
         "stop_mm": [-a / 2, 0.0, b / 2]},
        {"name": "feed_wall_zp（波导馈电段）", "material": "metal",
         "start_mm": [-a / 2, -lfed, b / 2], "stop_mm": [a / 2, 0.0, b / 2]},
        {"name": "feed_wall_zm（波导馈电段）", "material": "metal",
         "start_mm": [-a / 2, -lfed, -b / 2],
         "stop_mm": [a / 2, 0.0, -b / 2]},
        {"name": "flare（四壁梯形口径段，8 段阶梯包络）", "material": "metal",
         "start_mm": [-a1 / 2, 0.0, -b1 / 2],
         "stop_mm": [a1 / 2, lf, b1 / 2]},
    ]
    ports = [{"name": "Port1（RectWGPort，解析 TE10）",
              "pos_mm": [0.0, -lfed, 0.0], "dir": [0.0, 1.0, 0.0]}]
    return {"template": "pyramid_horn",
            "substrate": {"er": lay["er"], "h_mm": 0.0, "tan_d": 0.0},
            "boxes": boxes, "ports": ports, "elements": []}


def pyramid_horn_render(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    *,
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    far_field: bool = False,
) -> str:
    """pyramid_horn 整脚本渲染器（早分发自 render_script；mmwave 同款结构）。

    单波导口 RectWGPort（解析 TE10，Z_ref=解析波导阻抗）；y 轴双端
    PML_8、x/z MUR；空气填充无介质板（段头注释）。far_field/sar 不接受
    （方向图/nf2ff=Ph3 真机窗接线，显式报错不静默降级）。
    """
    del template, substrate   # 单模板渲染器；板材/域全由 params/NOMINAL 单源
    if far_field:
        raise ValueError(
            "pyramid_horn: far_field/nf2ff 属 Ph3 方向图窗，v1 离线段未接线"
            "（显式拒绝，不静默降级）")
    if int(excite_port) != 1:
        raise ValueError(f"pyramid_horn 单端口模板，excite_port={excite_port}")
    lay = _pyramid_horn_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = lay["f0_ghz"] * 1e9
    fc = lay["fc_ghz"] * 1e9
    er = lay["er"]
    base = lay["base_mm"] * 1e-3
    near = lay["near_mm"] * 1e-3
    dom_x = lay["dom_x_mm"] * 1e-3
    dom_y = lay["dom_y_mm"] * 1e-3
    dom_z = lay["dom_z_mm"] * 1e-3
    nrts = int(params.get("_nrts", 100000) or 100000)

    def m(v: float) -> float:
        return float(v) * 1e-3

    box_lit = "\n".join(
        f'wall.AddBox(({m(bx[1])!r}, {m(bx[2])!r}, {m(bx[3])!r}), '
        f'({m(bx[4])!r}, {m(bx[5])!r}, {m(bx[6])!r}), priority=10)  # '
        f'{bx[0]}'
        for bx in lay["boxes"])
    x_lit = ", ".join(repr(m(v)) for v in lay["x_lines_mm"])
    y_lit = ", ".join(repr(m(v)) for v in lay["y_lines_mm"])
    z_lit = ", ".join(repr(m(v)) for v in lay["z_lines_mm"])
    p = lay["port"]
    port_lit = (
        f"    start=np.array([{m(p['start_mm'][0])!r}, "
        f"{m(p['start_mm'][1])!r}, {m(p['start_mm'][2])!r}]),\n"
        f"    stop=np.array([{m(p['stop_mm'][0])!r}, "
        f"{m(p['stop_mm'][1])!r}, {m(p['stop_mm'][2])!r}]),\n")
    a_bind = m(p["a_bind_mm"])
    b_bind = m(p["b_bind_mm"])
    a_wr = m(lay["a_mm"])
    return f'''#!/usr/bin/env python3
"""openEMS pyramid_horn script (rfauto ME-7 auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末
PYRAMID_HORN 段。标准增益角锥喇叭（WR 波导馈电 + 四壁梯形口径段 8 段
阶梯化）；闭式综合/增益=core/horn_synthesis（Orfanidis×Balanis 双源）；
真机冒烟与方向图=Ph3 窗（本批零发射）。
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
from openEMS.ports import RectWGPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}   # 空气填充（TE10 截止/波导波长 summary 回显消费；无介质板）
H_SUB = 0.0   # 无介质板器件占位（审计④域口径；段头注释）
BASE = {base!r}   # 网格 base：自动档 λ0/50（空气口径）
NEAR = {near!r}   # 近特征区 = base/4
DOM_X = {dom_x!r}
DOM_Y = {dom_y!r}
DOM_Z = {dom_z!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 喇叭=辐射器件：y 轴（端口轴）双端 PML_8（端口面贴 y=-DOM_Y PML 域边，
# #154 前节），x/z MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 全部壁面站线显式入网（#198）：特征区 NEAR 细分→域界补入→空气区 BASE
# 粗化（双档平滑把细格限于壁面走廊）；渲染守卫已断阶梯步距 ≥4·NEAR
for _x in np.array([{x_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{y_lit}]):
    mesh.AddLine("y", _y)
for _z in np.array([{z_lit}]):
    mesh.AddLine("z", _z)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.SmoothMeshLines("z", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.array([-DOM_Z, DOM_Z]))
mesh.SmoothMeshLines("x", BASE)
mesh.SmoothMeshLines("y", BASE)
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：波导馈电直管 + 四壁梯形口径段（8 段矩形截面阶梯链，段间
#    框面闭合=全 PEC 封闭腔；零厚 PEC 片，段头注释）──
wall = CSX.AddMetal("horn_wall")
{box_lit}

# ── 端口：RectWGPort 解析 TE10（Pozar 模式函数，绑定自算 kc=π/a_phys）──
# 绑定参数序：a=第一横向轴（exc_dir=y 时=z）、b=第二横向轴（=x）；本喇叭
# 物理宽边沿 x、E 场沿 z ⇒ 绑定 a={a_bind!r}（=b_phys）、
# b={b_bind!r}（=a_phys）、mode="TE01"（M=0,N=1：E 沿 z、半波沿 x）。
# Z_ref 缺省=解析波导阻抗 ZL=k·Z0/β（WaveguidePort.CalcPort）。
_port1 = RectWGPort(CSX, port_nr=1,
{port_lit}    exc_dir="y", a={a_bind!r}, b={b_bind!r},
    mode_name="TE01", excite=1)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（Z_ref=解析 TE10 波导阻抗）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])

# TE10 截止/导波波长闭式回显（er 消费面；WR 口径自洽由审计测试钉）
_fc_te10 = 299792458.0 / (2.0 * {a_wr!r} * (ER ** 0.5))
_lam_g = (299792458.0 / F0) / (1.0 - (_fc_te10 / F0) ** 2) ** 0.5
summary = dict(
    ok=True, template="pyramid_horn", f0_hz=F0, fc_hz=FC,
    wr_a_mm={lay["a_mm"]!r}, wr_b_mm={lay["b_mm"]!r},
    a1_mm={lay["a1_mm"]!r}, b1_mm={lay["b1_mm"]!r},
    l_feed_mm={lay["l_feed_mm"]!r}, l_flare_mm={lay["l_flare_mm"]!r},
    h_sub_placeholder_mm=H_SUB, fc_te10_hz=float(_fc_te10),
    lambda_g_mm=float(_lam_g), nrts=NRTS,
    mesh_lines=[int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
)
with open(os.path.join(SCRIPT_DIR, "pyramid_horn_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto pyramid_horn simulation done")
'''


# ── 注册：同对象入表（单一事实源；尾部追加 #247——pyramid_horn 居尾 2）──
PYRAMID_HORN_NOMINAL: dict[str, Any] = _pyramid_horn_nominal()
TEMPLATE_META["pyramid_horn"] = PYRAMID_HORN_META
TEMPLATE_NOMINAL["pyramid_horn"] = PYRAMID_HORN_NOMINAL
_TEMPLATE_PORT_AXES["pyramid_horn"] = ("y",)
_TEMPLATE_RADIATOR["pyramid_horn"] = True
