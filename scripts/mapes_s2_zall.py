r"""A8 MAPES stage-2：openEMS 单层像素板 Z_ALL 实采 + Schur 闭式对拍（6×6）。

链路（stage-1 未尽项承接）：
1. **Z_ALL 实采**：6×6 像素单层 PCB（底面地 + 基板 + 36 浮地贴片），Q=150
   端口（io×2 + pixel 36 + h/v 60 + diag 50 + via_ground 2，PixelLayout
   stage-1 槽序）。进程隔离激励轮转（#208 同款）：每端口渲染一份单激励
   全端口探针脚本、独立子进程跑一次，逐轮断点缓存（脚本逐字节一致+CSV
   可解析才复用，同 adapters/openems_rotation.py 语义）。
2. **装配**：全端口 S（全端口 50Ω 匹配端接口径）→ `core/mapes.s_to_z`
   → Z_ALL 落 <out-dir>/z_all.npz（缺省 runs/mapes_s4）；`z_all_quality` 出互易/无源/条件数
   逐频诊断；轮转实测互易 |S_ik − S_ki| 独立复检。
3. **对拍**：图案（全空/单像素/整行/棋盘）直接全波（金属化短路的真实
   结构，无虚拟口元件）×2 激励 vs 同 Z_ALL 的 Schur 闭式（MapesModel），
   首组误差数字落 report.json。

规模控制（硬要求）：先跑 p1/p2 计时冒烟 → Q×单激励时长推演；
>4h 不启动全量（或中断后如实 PARTIAL）。轮转中途每轮打印 ETA。

物理实现口径（core/mapes.pixel_board_geom docstring 详述）：贴片永远在
场（固定结构），图案只经"在场=金属短路/缺席=开路"的对角负载进入——
在场像素=贴片-地金属化过孔，耦合槽=缝隙金属桥，与 stage-1 占用→负载
语义逐槽对应。β/α 校准超参不在 stage-2（stage-3 #190 范式）。

stage-4 增补（残模根治）：缺省产物目录改为 runs/mapes_s4
（runs/mapes_s2 原档只读留存）；横向空气垫 EDGE_PAD_MM 1→6mm（PML 不再
覆盖外圈端口——真根因，见常量注释）；``gamma`` 子命令对任一轮 fdtd/
port_ut·port_it 时域档做零仿真逐口端接质量诊断；``--base-mm`` 细网格档、
``plan --grid N`` 规模推演。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py plan [--grid 10]
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py rotate --ports 1-2 --fresh
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py rotate
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py patterns
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py gamma --round p1
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py gamma --round-dir runs/mapes_s2/rounds/p1
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py reassemble
        （stage-5：零仿真重推导——150 轮原始 port_ut/port_it → 跨轮 Z_ui 漂移
        诊断先行 → current-only 装配 + 互易势场增益校准 + 对称化（±最小无源
        投影）→ runs/mapes_s5_diag/z_all_s5.npz + reassemble_report.json；
        不覆盖 s4 装配产物）
    .venv/Scripts/python.exe scripts/mapes_s2_zall.py drift
        （#257：只做跨轮 Z_ui 漂移诊断——装配矩阵类先做跨轮漂移诊断，逐口/
        逐类中位·最大相对偏差 → runs/mapes_s5_diag/drift_report.json）

探针装配侧根因修复（#257，core.mapes stage-5b 节）：渲染时每
端口盒三轴中线全部落硬网格线（u 探针横断面中心 + i 探针激励轴中面按
openEMS ports.py 字面口径逐位落位），并以 ``probe_box_guard`` 做终网格
≥2 格守卫（缺中线/半跨不足/中线贴邻线即 raise，先于任何真跑）。副作用：
端口盒内局部网格加密（x/y 最小格 0.2→0.1mm），dt 约减半，同 NrTS 下模拟
时窗随之减半——若出现截断纹波（#262 家族）用 ``--nr-ts`` 上调。中线改变
脚本字节 → 旧轮断点缓存全部失配，重提取属司机（真机）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.mapes import (
    VIA_GROUND,
    MapesModel,
    PixelBoardGeom,
    PixelLayout,
    apply_port_gain,
    assemble_s_from_ui,
    fit_reciprocity_gain,
    gauge_factor,
    occupancy_to_load,
    passive_project_z,
    pixel_board_geom,
    port_probe_axes,
    probe_box_guard,
    probe_midlines,
    reciprocity_caliber_matrix,
    s_to_z,
    ui_cross_round_drift,
    z_all_gate,
    z_all_gate_caliber,
    z_all_quality,
    z_to_s,
)

REPO = Path(__file__).resolve().parents[1]
# 缺省产物根目录 = runs/mapes_s4（stage-4 质量版）；stage-2 原档 runs/mapes_s2
# 只读留存（原始 Z_ALL 与 150 轮时域档零覆盖，硬要求）。可用 --out-dir 覆盖。
OUT_DIR = REPO / "runs" / "mapes_s4"
FREQ_RANGE_GHZ = (1.0, 6.0)
N_FREQ_POINTS = 41
Z0 = 50.0
SUB = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b（house 默认）
STACKUP = "rogers4350b_h0.508"
# XY 网格 base：λ_sub(f_max)/50=0.52mm 的加粗档 0.6mm（λ_sub/43 @6GHz）——
# stage-2 规模控制档（Q×单激励时长推演 ≤4h 硬要求）；裁判面 = 同网格
# 闭式 vs 直接全波对拍 + 互易/无源（网格无关），绝对精度留给 stage-3
# #190 HFSS 仲裁校准范式。
BASE_M = 0.6e-3
ROUND_TIMEOUT_S = 5400
BUDGET_S = 4.0 * 3600.0
# 横向空气垫（贴片阵四侧到域界的距离，mm）。stage-2 首版 1.0mm 的实测后果
# （stage-4 逐口 Z_ui 离线复算，runs/mapes_s2/rounds/p1）：
# PML_8 在 0.6mm 平滑网格下厚 ~4.8mm，1mm 垫意味着**最外圈贴片及其全部
# 端口（io/via/外圈 pixel/h/v 口）整体落在 PML 区内**——内圈 4×4 全部
# 端口端接实测 |Z|≈50Ω 完美、外圈全部 600~1400Ω 失效；同时外圈 PML 掠射
# 反射囚禁横向高 Q 模（-18.5dB 能量 plateau 的真根因，猜测后经实证）。
# 6mm 垫 > PML 4.8mm + 1.2mm 余量：任何端口/金属不再进 PML。
EDGE_PAD_MM = 6.0
# FDTD 步数上限：6×6 实测场能在脉冲结束后恒定在峰值 −18.5dB 附近的高 Q
# 数值残模上（衰减 0.01dB/千步量级，10 万步与 3 万步残差同阶）——加长
# 仿真无收益，按规模控制（Q×单激励 ≤4h）取 30000 步（dt≈0.254ps，
# 7.6ns ≈ 23 周期 @1GHz）。截断纹波如实进对拍/互易数字并记 followUp。
NR_TS = 30000

_SCRIPT_HEADER = """#!/usr/env/python3
\"\"\"openEMS pixel-board round script (rfauto MAPES stage-2 auto-generated).\"\"\"
import csv
import os

# CSXCAD/openEMS 扩展模块依赖 DLL 不在 Python 3.8+ PATH 搜索里（审计实测）。
# 目录可用 RFAUTO_OPENEMS_BIN 覆盖。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", "")
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
H_SUB = {h_m!r}
TAND = {tand!r}
BASE = {base_m!r}   # stage-2 规模控制档（λ_sub/50 加粗，见模块 docstring）
NEAR = {near_m!r}
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sparams.csv")
SIM_PATH = os.path.abspath("fdtd")

CSX = ContinuousStructure()
FDTD = openEMS(NrTS={nr_ts!r})   # 场能高 Q 残模 plateau：加长无收益（见脚本头注释）
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 像素阵列辐射器件：四侧+顶 PML_8；底 PEC 边界即连续地（house guided 口径）
FDTD.SetBoundaryCond(["PML_8", "PML_8", "PML_8", "PML_8", "PEC", "PML_8"])

mesh = CSX.GetGrid()
"""


def build_layout(n: int = 6) -> PixelLayout:
    """stage-2 固定拓扑：6×6 单层 + 双 via_ground 槽（对角角位）。

    ``n`` 只服务 stage-4 ⑦ 的规模推演（10×10 → Q=446=444+2via，
    via 槽仍取反对角角位 (0,n-1)/(n-1,0)）；缺省 6 与 runs/mapes_s2·s4 数据同拓扑。
    """
    n = int(n)
    return PixelLayout(n, n, 1, 2, ((0, n - 1, VIA_GROUND), (n - 1, 0, VIA_GROUND)))


def build_geom(layout: PixelLayout | None = None,
               edge_pad_mm: float | None = None) -> PixelBoardGeom:
    """装配几何（全部端口 = 竖直集总探针口，见 core.pixel_board_geom docstring）。

    ``edge_pad_mm``：横向空气垫（缺省模块常量 EDGE_PAD_MM=6.0，PML 不重叠
    任何端口/金属的域扩口径，见该常量注释）。
    """
    return pixel_board_geom(
        layout or build_layout(), sub_h_mm=SUB["h_mm"],
        edge_pad_mm=EDGE_PAD_MM if edge_pad_mm is None else float(edge_pad_mm))


def _fmt_list(vs: list[float]) -> str:
    return "[" + ", ".join(repr(v) for v in vs) + "]"


def mesh_lines(geom: PixelBoardGeom) -> tuple[list[float], list[float], list[float]]:
    """结构硬线（贴片边/端口盒边/馈线边/域界）；z 另含缝隙口底与贴片面。"""
    xs: set[float] = set()
    ys: set[float] = set()
    zs: set[float] = set()
    x0, y0, x1, y1 = geom.domain
    xs |= {x0, x1}
    ys |= {y0, y1}
    zs |= {0.0, geom.sub_h_m}
    for px0, py0, px1, py1 in geom.patches:
        xs |= {px0, px1}
        ys |= {py0, py1}
    for port in geom.ports:
        s, t = port.start, port.stop
        xs |= {s[0], t[0]}
        ys |= {s[1], t[1]}
        zs |= {s[2], t[2]}
    return sorted(xs), sorted(ys), sorted(zs)


def render_mesh_lines(
    geom: PixelBoardGeom,
) -> tuple[list[float], list[float], list[float], dict[str, Any]]:
    """渲染线集 = 结构硬线 ∪ 每端口盒三轴中线（#257 中心硬线），并过终网格
    ≥2 格守卫；守卫失败直接 raise（先于任何真跑）。返回 (xs, ys, zs, guard)。

    中线语义（core.mapes.probe_midlines）：u 探针横断面中心线 + i 探针激励
    轴中面线；盒边已是结构线，三线齐备 → 每盒每轴恰 ≥2 格，探针逐位落位，
    不再被吸附到盒角/PEC 面（跨轮漂移根因）。
    """
    xs, ys, zs = mesh_lines(geom)
    mid_x, mid_y, mid_z = probe_midlines(geom)
    xs = sorted(set(xs) | set(mid_x))
    ys = sorted(set(ys) | set(mid_y))
    zs = sorted(set(zs) | set(mid_z))
    guard = probe_box_guard(geom, (xs, ys, zs))
    if not guard["pass"]:
        head = "; ".join(
            f"p{v['port']}({v['label']})/{v['axis']}: {v['reason']}"
            for v in guard["violations"][:8])
        raise ValueError(
            f"探针盒 ≥2 格守卫失败（#257，探针吸附=跨轮装配漂移根因）："
            f"{head}（共 {guard['n_violations']} 处）")
    guard["midline_counts"] = {"x": len(mid_x), "y": len(mid_y), "z": len(mid_z)}
    return xs, ys, zs, guard


def _pattern_defs() -> dict[str, np.ndarray]:
    idx = np.arange(6)
    single = np.zeros((6, 6), dtype=bool)
    single[2, 3] = True
    row2 = np.zeros((6, 6), dtype=bool)
    row2[2, :] = True
    checker = np.add.outer(idx, idx) % 2 == 0
    return {
        "all_empty": np.zeros((6, 6), dtype=bool),
        "single_2_3": single,
        "row2": row2,
        "checker": checker,
    }


def bleed_boxes(geom: PixelBoardGeom) -> list[tuple[float, float, float, float]]:
    """每贴片一个 10kΩ 直流泄放电阻的落位（x0,y0,x1,y1，贴片局部 → 全局）。

    动机（p1 verbose 实测）：LumpedPort 的 R 元件 caps=True
    （openEMS.ports 硬编码）串电容隔断直流，高斯激励经端口注入的净电荷
    困在浮地贴片阵上，场能恒定在峰值 −18.6dB 永不衰减（数值静电模）。
    每贴片并联 10kΩ（|Z|≫50Ω，RF 近开路，负载语义不变；τ=R·C≈2ns 电荷
    秒放）后参考结构与图案直接全波共用同一泄放，对拍口径一致。落位复用
    既有网格阶梯线（过孔口盒位；过孔槽贴片让位到对角锚盒位），零新增
    网格线。
    """
    layout = geom.layout
    n = layout.n_cols
    a = geom.cell_m
    hx = 0.1e-3
    hy = 0.15e-3
    # 该贴片上 (a/2, a/4) 默认位已被占用（过孔口/io2）→ 让位：
    # 对角锚角区（无对角口的过孔贴片）或 NE 角区（io2 的贴片 (M-1,N-1)）
    via_or_io_patches: dict[int, str] = {}
    for r, c, _ in layout.via_slots:
        via_or_io_patches[r * n + c] = "corner"
    via_or_io_patches[(layout.n_rows - 1) * n + (layout.n_cols - 1)] = "north"
    boxes: list[tuple[float, float, float, float]] = []
    for idx, (px0, py0, _, _) in enumerate(geom.patches):
        where = via_or_io_patches.get(idx)
        if where == "corner":
            boxes.append((px0 + 0.15e-3, py0 + 0.15e-3,
                          px0 + 0.15e-3 + 2 * hx, py0 + 0.15e-3 + 2 * hx))
        elif where == "north":
            # NE 角区盒（该贴片无 diag_main 口，角区空闲；边线=阶梯线）
            boxes.append((px0 + a - 0.35e-3, py0 + a - 0.35e-3,
                          px0 + a - 0.15e-3, py0 + a - 0.15e-3))
        else:
            boxes.append((px0 + a / 2 - hx, py0 + a / 4 - hy,
                          px0 + a / 2 + hx, py0 + a / 4 + hy))
    return boxes


def render_round_script(
    geom: PixelBoardGeom,
    *,
    excite_port: int,
    virtual_ports: bool,
    short_numbers: tuple[int, ...] = (),
    nr_ts: int | None = None,
) -> str:
    """渲染一份自洽单激励脚本（子进程只依赖 numpy/openEMS/CSXCAD）。

    ``virtual_ports=True``：Q 端口参考结构（全部虚拟口 50Ω 匹配端接 +
    探针），CSV 出全 Q 列。``False``：图案直接全波（仅 io 两口，无任何
    虚拟口元件；``short_numbers`` 槽位端口几何处画金属短路体）。
    ``nr_ts``：FDTD 步数上限覆盖（缺省模块常量 NR_TS；#257 中线加密后 dt
    约减半，截断纹波时上调）。网格线集经 :func:`render_mesh_lines`（结构线
    ∪ 探针中线 + ≥2 格守卫，失败 raise）。
    """
    layout = geom.layout
    q = layout.n_ports
    if not (1 <= excite_port <= q):
        raise ValueError(f"excite_port 越界：{excite_port} (1..{q})")
    steps = NR_TS if nr_ts is None else int(nr_ts)
    if steps < 1:
        raise ValueError(f"nr_ts 必须 ≥1，实得 {nr_ts!r}")
    er = SUB["er"]
    tand = SUB["tan_d"]
    f0 = (FREQ_RANGE_GHZ[0] + FREQ_RANGE_GHZ[1]) / 2 * 1e9
    fc = max((FREQ_RANGE_GHZ[1] - FREQ_RANGE_GHZ[0]) / 2 * 1e9, 1e6)
    f_max = f0 + fc
    base = BASE_M
    near = base / 4
    air_top = 3e8 / f_max / 4  # 辐射器件 λ0/4（house 口径）
    xs, ys, zs, guard = render_mesh_lines(geom)
    zs = sorted(set(zs) | {geom.sub_h_m + air_top})

    lines: list[str] = [_SCRIPT_HEADER.format(
        f0=f0, fc=fc, er=er, h_m=geom.sub_h_m, tand=tand,
        base_m=base, near_m=near, nr_ts=steps)]
    mc = guard["midline_counts"]
    lines.append(
        f"# probe midlines (#257 u-center + i-midplane hard lines): "
        f"x={mc['x']} y={mc['y']} z={mc['z']}; guard >=2 cells/axis PASS "
        f"(min half-span {guard['min_half_span_m'] * 1e3:.4f}mm, "
        f"min mid-gap {guard['min_mid_gap_m'] * 1e3:.4f}mm, ports={guard['n_ports']})")
    lines.append(f"mesh.AddLine(\"x\", {_fmt_list(xs)})")
    lines.append(f"mesh.AddLine(\"y\", {_fmt_list(ys)})")
    lines.append(f"mesh.AddLine(\"z\", {_fmt_list(zs)})")
    lines.append("mesh.SmoothMeshLines(\"x\", BASE)")
    lines.append("mesh.SmoothMeshLines(\"y\", BASE)")
    lines.append("mesh.SmoothMeshLines(\"z\", 1.2e-3)")
    lines.append(
        "# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重\n"
        "for _ax in (\"x\", \"y\", \"z\"):\n"
        "    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)\n"
        "    _keep = [_ls[0]]\n"
        "    for _v in _ls[1:]:\n"
        "        if _v - _keep[-1] > 1e-6:\n"
        "            _keep.append(_v)\n"
        "    mesh.SetLines(_ax, np.array(_keep))")
    dx0, dy0, dx1, dy1 = geom.domain
    lines.append(
        "sub = CSX.AddMaterial(\"substrate\", epsilon=ER,\n"
        "                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)\n"
        f"sub.AddBox(({dx0!r}, {dy0!r}, 0), ({dx1!r}, {dy1!r}, H_SUB), priority=0)")
    lines.append("pixels = CSX.AddMetal(\"pixels\")")
    for px0, py0, px1, py1 in geom.patches:
        lines.append(
            f"pixels.AddBox(({px0!r}, {py0!r}, H_SUB), "
            f"({px1!r}, {py1!r}, H_SUB), priority=10)")
    if short_numbers:
        lines.append("shorts = CSX.AddMetal(\"shorts\")")
        for num in short_numbers:
            port = geom.port_by_number(num)
            s, t = port.start, port.stop
            lines.append(
                f"shorts.AddBox(({s[0]!r}, {s[1]!r}, {s[2]!r}), "
                f"({t[0]!r}, {t[1]!r}, {t[2]!r}), priority=10)")
    # 10kΩ 直流泄放（净电荷静电模治理，见 bleed_boxes docstring）：
    # 参考轮与图案轮同在，对拍口径一致。
    lines.append(
        "bleeds = CSX.AddLumpedElement(\"bleeds\", ny=2, caps=False, R=10000.0)")
    for bx0, by0, bx1, by1 in bleed_boxes(geom):
        lines.append(
            f"bleeds.AddBox(({bx0!r}, {by0!r}, 0), ({bx1!r}, {by1!r}, H_SUB), "
            "priority=5)")
    lines.append("_ports = {}")
    for port in geom.ports:
        if not virtual_ports and port.slot_index >= 0:
            continue  # 图案直接全波：虚拟口不置口（开路=无元件），仅留 io 探针
        s, t = port.start, port.stop
        # 激励轴单一事实源 core.mapes.port_probe_axes（探针中线按同轴落位）：
        # 缝隙横向口按缝隙跨度轴向；io 与像素/过孔/对角口同为竖直贴片-地口
        # （exc_dir 必为 z——首版三元链优先级写反，全部竖直口被置成 x 向，
        # 整板被口元件横短）
        exc_dir = ("x", "y", "z")[port_probe_axes(port)]
        lines.append(
            f"_port{port.number} = LumpedPort(CSX, port_nr={port.number}, "
            f"R={Z0!r},\n"
            f"    start=np.array([{s[0]!r}, {s[1]!r}, {s[2]!r}]),\n"
            f"    stop=np.array([{t[0]!r}, {t[1]!r}, {t[2]!r}]),\n"
            f"    exc_dir={exc_dir!r}, "
            f"excite={1 if port.number == excite_port else 0}, priority=5)")
        lines.append(f"_ports[{port.number}] = _port{port.number}")
    lines.append(
        "FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)\n"
        f"f = np.linspace(F0 - FC, F0 + FC, {N_FREQ_POINTS})\n"
        "for _pn in sorted(_ports):\n"
        "    _ports[_pn].CalcPort(SIM_PATH, f, ref_impedance=50)\n"
        f"_SREF = _ports[{excite_port}].uf_inc\n"
        "with open(CSV_PATH, \"w\", newline=\"\") as fh:\n"
        "    w = csv.writer(fh)")
    measured = ([p.number for p in geom.ports if p.slot_index < 0]
                if not virtual_ports else list(range(1, q + 1)))
    header_cols = ["freq_hz"]
    for i in measured:
        header_cols += [f"re_S{i}{excite_port}", f"im_S{i}{excite_port}"]
    lines.append("    w.writerow(" + repr(header_cols) + ")")
    for i in measured:
        lines.append(
            f"    _S{i} = _ports[{i}].uf_ref / _SREF")
    body_rows = ", ".join(
        f"_S{i}[_i].real, _S{i}[_i].imag" for i in measured)
    lines.append(
        "    for _i in range(len(f)):\n"
        f"        w.writerow([f[_i], {body_rows}])\n"
        "print(\"rfauto mapes stage-2 round done\")")
    return "\n".join(lines) + "\n"


def _parse_round_csv(csv_path: Path, n_cols: int) -> tuple[Any, list[Any]] | None:
    """读轮次 CSV → (freq_hz, [复数列])；缺失/损坏返回 None（调用方重跑）。"""
    try:
        data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1, ndmin=2)
        if data.shape[0] < 1 or data.shape[1] < 1 + 2 * n_cols:
            return None
        cols = [data[:, 1 + 2 * i] + 1j * data[:, 2 + 2 * i]
                for i in range(n_cols)]
        return data[:, 0], cols
    except Exception:
        return None


def _run_round(
    work_dir: Path, script_text: str, n_cols: int, *, resume: bool,
) -> tuple[Any, list[Any], float, bool]:
    """跑（或复用）一轮；返回 (freq_hz, 列, 耗时s, 是否断点复用)。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    script_path = work_dir / "simulation.py"
    csv_path = work_dir / "sparams.csv"
    if resume:
        prev: str | None = None
        try:
            prev = script_path.read_text(encoding="utf-8")
        except OSError:
            prev = None
        if prev == script_text:
            parsed = _parse_round_csv(csv_path, n_cols)
            if parsed is not None:
                return parsed[0], parsed[1], 0.0, True
    script_path.write_text(script_text, encoding="utf-8")
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(script_path.resolve())], capture_output=True,
        text=True, timeout=ROUND_TIMEOUT_S, cwd=str(work_dir.resolve()))
    elapsed = time.time() - t0
    parsed = _parse_round_csv(csv_path, n_cols)
    if parsed is None:
        tail = (proc.stderr or "")[-1200:]
        raise RuntimeError(
            f"轮次 {work_dir.name} 无产物/不可解析（rc={proc.returncode}）；"
            f"stderr 尾:\n{tail}")
    return parsed[0], parsed[1], elapsed, False


def stage_plan(args: argparse.Namespace) -> int:
    grid_n = int(getattr(args, "grid", 6) or 6)
    layout = build_layout(grid_n)
    geom = build_geom(layout)
    print(f"[plan] topology={layout.topology_key}")
    print(f"[plan] Q={layout.n_ports} (io=2 + load={layout.n_load_ports})")
    dom = geom.domain
    print(f"[plan] domain mm: x[{dom[0]*1e3:.2f},{dom[2]*1e3:.2f}] "
          f"y[{dom[1]*1e3:.2f},{dom[3]*1e3:.2f}] h={geom.sub_h_m*1e3:.3f}")
    xs, ys, zs = mesh_lines(geom)
    print(f"[plan] hard mesh lines: x={len(xs)} y={len(ys)} z={len(zs)}")
    log = OUT_DIR / "rotate_log.jsonl"
    times = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("resumed", False):
                times.append(float(rec["elapsed_s"]))
    if times:
        mean_t = float(np.mean(times))
        # 计时记录来自 OUT_DIR 已跑拓扑（缺省 6×6）；其他规模按域面积比投影
        # （同网格密度下 cell 数 ∝ 面积、dt 不变 → 单轮耗时 ∝ 面积，近似口径）
        ref_geom = build_geom(build_layout(6))
        rd = ref_geom.domain
        area_ref = (rd[2] - rd[0]) * (rd[3] - rd[1])
        area = (dom[2] - dom[0]) * (dom[3] - dom[1])
        scale = area / area_ref
        eta = mean_t * scale * layout.n_ports
        print(f"[plan] fresh rounds done={len(times)} mean={mean_t:.1f}s "
              f"(6x6 ref) area_scale={scale:.2f} -> 单轮投影 {mean_t*scale:.1f}s，"
              f"全量 {layout.n_ports} 轮推演 {eta/3600:.2f}h（预算 {BUDGET_S/3600:.0f}h）"
              f" {'OK' if eta <= BUDGET_S else 'OVER'}")
    else:
        print("[plan] 无计时记录：先 rotate --ports 1-2 --fresh 计时冒烟")
    return 0


def stage_rotate(args: argparse.Namespace) -> int:
    layout = build_layout()
    geom = build_geom(layout)
    q = layout.n_ports
    rounds = _parse_ports(args.ports, q)
    nr_ts = getattr(args, "nr_ts", None)
    steps = NR_TS if nr_ts is None else int(nr_ts)
    # #257 探针守卫先于任何真跑（失败即 raise；数字进 meta）
    _, _, _, guard = render_mesh_lines(geom)
    print(f"[rotate] probe guard PASS: midlines x/y/z="
          f"{guard['midline_counts']['x']}/{guard['midline_counts']['y']}/"
          f"{guard['midline_counts']['z']} min_half_span="
          f"{guard['min_half_span_m'] * 1e3:.4f}mm nr_ts={steps}", flush=True)
    log_path = OUT_DIR / "rotate_log.jsonl"
    fresh_times: list[float] = []
    if log_path.exists() and not args.fresh:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("resumed", False):
                fresh_times.append(float(rec["elapsed_s"]))

    freq_hz: Any = None
    s_all: Any = None
    for k in rounds:
        script = render_round_script(geom, excite_port=k, virtual_ports=True,
                                     nr_ts=steps)
        work = OUT_DIR / "rounds" / f"p{k}"
        try:
            fh, cols, elapsed, resumed = _run_round(
                work, script, q, resume=not args.fresh)
        except subprocess.TimeoutExpired:
            print(f"[rotate] p{k} 超时（>{ROUND_TIMEOUT_S}s），如实终止",
                  flush=True)
            return 2
        if freq_hz is None:
            freq_hz = fh
            s_all = np.zeros((len(fh), q, q), dtype=complex)
        elif not np.allclose(fh, freq_hz):
            print(f"[rotate] p{k} 频率轴与 p1 不一致，如实终止", flush=True)
            return 2
        for i in range(q):
            s_all[:, i, k - 1] = cols[i]
        if not resumed:
            fresh_times.append(elapsed)
        mean_t = float(np.mean(fresh_times))
        remaining = q - len(fresh_times)
        print(f"[rotate] p{k} done elapsed={elapsed:.1f}s resumed={resumed} "
              f"fresh_mean={mean_t:.1f}s eta_all={mean_t * q / 3600:.2f}h "
              f"remaining~{remaining * mean_t / 60:.0f}min", flush=True)
        with open(log_path, "a", encoding="utf-8") as fh_log:
            fh_log.write(json.dumps({
                "round": k, "elapsed_s": round(elapsed, 2),
                "resumed": resumed}) + "\n")

    if args.ports:
        print(f"[rotate] 子集轮转完成（{len(rounds)} 轮），不装配 Z_ALL")
        return 0

    z_all = s_to_z(s_all, reference_impedance=Z0)
    np.savez_compressed(
        OUT_DIR / "z_all.npz", freq_hz=freq_hz, s_all=s_all, z_all=z_all)
    quality = z_all_quality(z_all, n_io=layout.n_io_ports)
    z_sym = 0.5 * (z_all + np.swapaxes(z_all, -1, -2))
    quality_sym = z_all_quality(z_sym, n_io=layout.n_io_ports)
    reciprocity_s = float(np.max(np.abs(
        s_all - np.swapaxes(s_all, -1, -2))))
    smax = np.linalg.norm(s_all, ord=2, axis=(-2, -1))
    meta = {
        "stage": "stage-2 (openEMS Z_ALL 实采)",
        "topology_key": layout.topology_key,
        "n_ports": q,
        "freq_ghz": [float(v) / 1e9 for v in freq_hz],
        "freq_range_ghz": list(FREQ_RANGE_GHZ),
        "n_freq_points": N_FREQ_POINTS,
        "reference_impedance": Z0,
        "sub": SUB,
        "stackup": STACKUP,
        "nr_ts": steps,
        "edge_pad_mm": EDGE_PAD_MM,
        "probe_guard": {
            "pass": bool(guard["pass"]),
            "n_ports": guard["n_ports"],
            "midline_counts": guard["midline_counts"],
            "min_half_span_m": guard["min_half_span_m"],
            "min_mid_gap_m": guard["min_mid_gap_m"],
            "note": (
                "#257 装配侧根因修复：每端口盒三轴中线落硬网格线（u 探针横断面"
                "中心 + i 探针激励轴中面按 openEMS ports.py 字面口径逐位落位），"
                "终网格 ≥2 格守卫 PASS。副作用：盒内局部网格加密 → dt 约减半，"
                "同 NrTS 模拟时窗减半；截断纹波时用 --nr-ts 上调。"),
        },
        "known_artifact": (
            "stage-4 根因已定：stage-2 原档的端口端接失效/高 Q 残模/互易破缺 "
            "同源于横向 PML_8（厚约 4.8mm@0.6mm 网格）整体覆盖最外圈贴片及"
            "其端口（edge_pad=1mm 域垫不足）——逐口 Z_ui 复算实证内圈 4x4 全"
            "部 |Z|≈50Ω 完美、外圈全部 600~1400Ω。本 stage-4 域扩 "
            f"edge_pad={EDGE_PAD_MM}mm 后 150 口全部端接生效（带内 |Re Z|∈"
            "[38,57]Ω）。残余伪影：逐端口类 u/i 探针空间采样相位偏（等效 "
            "~1.3ps，随 f 线性增长），同贴片口对互易破缺 max|S-S^T|="
            "3.38e-2@6GHz（跨贴片对中位 4.6e-5），σmax(S)=1.0344>1，raw 口径"
            "互易≤1e-3 与 passive=True 双门失守 → 对拍判读切 (Z+Z^T)/2 sym "
            "口径（互易精确成立，min_eig_re_min=-0.853 仍非严格无源，如实"
            "记录；根治属网格细化/探针重采样，留 followUp）"),
        "root_cause_fix": (
            "PML 与端口/金属重叠（stage-2 edge_pad=1mm）为互易破缺/无源违"
            "反/σmax>1/能量 plateau 的共同根因；域扩修复后 plateau 消失"
            "（激励口 ut 尾段 -82dB 量级、EndCriteria 提前停机，单轮 14s）"),
        "domain_m": list(geom.domain),
        "port_classes": {
            "io": 2,
            "pixel": layout.n_rows * layout.n_cols,
            "pixel_h": layout.n_rows * (layout.n_cols - 1),
            "pixel_v": (layout.n_rows - 1) * layout.n_cols,
            "diag_main": (layout.n_rows - 1) * (layout.n_cols - 1),
            "diag_anti": (layout.n_rows - 1) * (layout.n_cols - 1),
            "via_ground": len(layout.via_slots),
        },
        "s_reciprocity_max_abs": reciprocity_s,
        "s_sigma_max": float(np.max(smax)),
        "fresh_round_mean_s": float(np.mean(fresh_times)),
        "total_elapsed_s": float(np.sum(fresh_times)),
        "z_quality": quality,
        "z_quality_sym": quality_sym,
    }
    (OUT_DIR / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[rotate] Z_ALL 落盘 {OUT_DIR / 'z_all.npz'}")
    print(f"[rotate] S 互易 max|S-S^T|={reciprocity_s:.3e}  "
          f"σmax(S)={float(np.max(smax)):.4f}")
    print(f"[rotate] Z 互易(rel)max={quality['reciprocity_max_rel']:.3e}  "
          f"passive={quality['passive']}  min_eig_re_min="
          f"{quality['min_eig_re_min']:.3e}  cond(Z22)max={quality['cond_z22_max']:.3e}")
    return 0


def stage_patterns(args: argparse.Namespace) -> int:
    layout = build_layout()
    geom = build_geom(layout)
    npz = OUT_DIR / "z_all.npz"
    if not npz.exists():
        print("[patterns] 缺 z_all.npz：先完成 rotate", flush=True)
        return 2
    with np.load(npz) as data:
        freq_hz = data["freq_hz"]
        z_all = data["z_all"]
    model = MapesModel(layout, z_all, freq_hz, reference_impedance=Z0)
    only = set(args.patterns.split(",")) if args.patterns else None
    nr_ts = getattr(args, "nr_ts", None)
    steps = NR_TS if nr_ts is None else int(nr_ts)

    report: dict[str, Any] = {"stage": "stage-2 pattern cross-check",
                              "nr_ts": steps,
                              "patterns": {}}
    vias = np.zeros(len(layout.via_slots), dtype=int)  # 图案：过孔槽全开路
    for name, pattern in _pattern_defs().items():
        if only is not None and name not in only:
            continue
        params = layout.flatten(pattern, vias)
        loads = occupancy_to_load(pattern, layout, vias)
        short_numbers = tuple(
            int(i) + 3 for i in np.flatnonzero(np.isfinite(loads)))
        s_direct = np.zeros((len(freq_hz), 2, 2), dtype=complex)
        for exc in (1, 2):
            script = render_round_script(
                geom, excite_port=exc, virtual_ports=False,
                short_numbers=short_numbers, nr_ts=steps)
            work = OUT_DIR / "patterns" / name / f"p{exc}"
            try:
                fh, cols, elapsed, resumed = _run_round(
                    work, script, 2, resume=not args.fresh)
            except subprocess.TimeoutExpired:
                print(f"[patterns] {name} p{exc} 超时（>{ROUND_TIMEOUT_S}s）",
                      flush=True)
                return 2
            if not np.allclose(fh, freq_hz):
                print(f"[patterns] {name} p{exc} 频率轴不一致", flush=True)
                return 2
            s_direct[:, 0, exc - 1] = cols[0]
            s_direct[:, 1, exc - 1] = cols[1]
            print(f"[patterns] {name} p{exc} done elapsed={elapsed:.1f}s "
                  f"resumed={resumed}", flush=True)
        closed = model.evaluate(params).s_external
        delta = np.abs(closed - s_direct)
        center = len(freq_hz) // 2
        rec_direct = float(np.max(np.abs(s_direct - np.swapaxes(s_direct, -2, -1))))
        smax_direct = float(np.max(np.linalg.norm(s_direct, ord=2, axis=(-2, -1))))
        rec_closed = float(np.max(np.abs(closed - np.swapaxes(closed, -2, -1))))
        entry = {
            "n_short_slots": len(short_numbers),
            "max_abs_delta_s": float(np.max(delta)),
            "per_entry_max_abs_delta_s": [
                [float(np.max(delta[:, i, j])) for j in range(2)] for i in range(2)],
            "center_freq_ghz": float(freq_hz[center]) / 1e9,
            "closed_center": [[complex_str(closed[center, i, j]) for j in range(2)]
                              for i in range(2)],
            "direct_center": [[complex_str(s_direct[center, i, j]) for j in range(2)]
                              for i in range(2)],
            "direct_reciprocity_max_abs": rec_direct,
            "closed_reciprocity_max_abs": rec_closed,
            "direct_sigma_max": smax_direct,
        }
        report["patterns"][name] = entry
        print(f"[patterns] {name}: max|ΔS|={entry['max_abs_delta_s']:.4e} "
              f"rec(direct)={rec_direct:.2e} σmax(direct)={smax_direct:.4f}",
              flush=True)
    worst = max(v["max_abs_delta_s"] for v in report["patterns"].values())
    report["worst_max_abs_delta_s"] = worst
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[patterns] report -> {OUT_DIR / 'report.json'} "
          f"(worst max|ΔS|={worst:.4e})")
    return 0


def complex_str(v: Any) -> str:
    return f"{complex(v).real:+.5f}{complex(v).imag:+.5f}j"


# --------------------------------------------------------------------------- #
# gamma：任一轮 fdtd/port_ut·port_it 时域档 → 逐口 Γ 端接质量诊断（零仿真）
# --------------------------------------------------------------------------- #

#: 端接合格门：非激励口 |Z_ui/Z0 + 1| ≤ 0.05（相对理想匹配负载 −Z0 的偏差，
#: stage-4 max|Γ|≤0.05 口径在非激励口的无歧义等价量——完美匹配时
#: uf_inc=(U+Z0·I)/2≡0，b/a 是 0/0 不可用，实测定版）
GAMMA_MATCH_TOL = 0.05
#: 尾段能量 plateau 判读：激励口 ut 末 1/4 窗 RMS 相对峰值 ≤ −40dB 视为已衰减
UT_TAIL_PLATEAU_DB = -40.0


def port_classes(geom: PixelBoardGeom) -> dict[int, str]:
    """端口号 → 类别标签（io / pixel / pixel_h / pixel_v / diag_main / diag_anti / via_ground）。"""
    slots = geom.layout.load_slots()
    out: dict[int, str] = {}
    for port in geom.ports:
        out[port.number] = ("io" if port.slot_index < 0
                            else slots[port.slot_index].category)
    return out


def read_port_ui_dump(fdtd_dir: Path, number: int) -> tuple[Any, Any, Any] | None:
    """读 ``port_ut_{n}`` / ``port_it_{n}``（openEMS 探针文本，% 注释）→ (t, u, i)。

    两文件时间轴不同（u 在整步、i 在半步，引擎口径）；按 openEMS ``UI_data``
    原样各用各的时间轴做 DFT（复刻 ports.py ReadUIData 语义）。缺档返回 None。
    """
    ut = fdtd_dir / f"port_ut_{number}"
    it = fdtd_dir / f"port_it_{number}"
    if not (ut.exists() and it.exists()):
        return None
    du = np.loadtxt(str(ut), comments="%", ndmin=2)
    di = np.loadtxt(str(it), comments="%", ndmin=2)
    if du.shape[0] < 2 or di.shape[0] < 2 or du.shape[1] < 2 or di.shape[1] < 2:
        return None
    return (du[:, 0], du[:, 1]), (di[:, 0], di[:, 1]), None


def summarize_round_gamma(
    round_dir: Path,
    geom: PixelBoardGeom,
    *,
    freq_hz: Any,
    excite_port: int,
    z0: float = Z0,
    tol: float = GAMMA_MATCH_TOL,
) -> dict[str, Any]:
    """一轮时域档 → 逐口端接质量 + 逐类汇总 + 激励口尾段 plateau 指标。

    量的定义（core.mapes.port_gamma / wave_decompose_ui 同式）：
    - ``z_ui`` = uf_tot/if_tot（逐频）。非激励口 = 该口实际端接阻抗（无激励
      污染），理想 50Ω 吸收在引擎 u/i 方向约定下读 **−Z0**（出射波
      U=−Z0·I）；``term_err`` = |z_ui/Z0 + 1| 的带内最大即端接偏差，
      ``matched`` = term_err ≤ tol。激励口 z_ui 含源电流，不判 matched。
    - ``gamma`` = uf_ref/uf_inc：激励口即 S_kk（结构输入匹配，物理量）；
      非激励口完美匹配时 uf_inc≡0 → 0/0，只留档不判门。
    """
    from rfauto.core.mapes import dft_time2freq, port_gamma  # 惰性：脚本级依赖清晰

    fdtd = round_dir / "fdtd"
    freqs = np.asarray(freq_hz, dtype=float)
    classes = port_classes(geom)
    ports: dict[str, Any] = {}
    by_class: dict[str, dict[str, Any]] = {}
    missing: list[int] = []
    tail_db: float | None = None
    excited_s_kk_max: float | None = None
    for port in geom.ports:
        n = port.number
        rec = read_port_ui_dump(fdtd, n)
        if rec is None:
            missing.append(n)
            continue
        (tu, u), (ti, i), _ = rec
        uf = dft_time2freq(tu, u, freqs)
        if_ = dft_time2freq(ti, i, freqs)
        gamma = port_gamma(uf, if_, reference_impedance=z0)
        safe = np.abs(if_) > 1e-30
        z_ui = np.full(freqs.shape, np.nan + 0j, dtype=complex)
        z_ui[safe] = uf[safe] / if_[safe]
        term_err = np.abs(z_ui / z0 + 1.0)
        term_err_max = float(np.nanmax(term_err)) if np.any(safe) else float("inf")
        g_abs = np.abs(gamma)
        k_worst = int(np.argmax(g_abs))
        zmed = complex(np.nanmedian(z_ui.real), np.nanmedian(z_ui.imag))
        excited = bool(n == excite_port)
        entry = {
            "class": classes[n],
            "excited": excited,
            "term_err_max": term_err_max,
            "z_ui_median": complex_str(zmed),
            "gamma_max_abs": float(g_abs[k_worst]),
            "gamma_worst_freq_ghz": float(freqs[k_worst]) / 1e9,
            "matched": (None if excited else bool(term_err_max <= tol)),
        }
        ports[str(n)] = entry
        cls = by_class.setdefault(classes[n], {
            "n": 0, "n_non_excited": 0, "n_matched": 0, "term_err_max": 0.0,
            "worst_port": None, "z_ui_median_re": [], "z_ui_median_im": []})
        cls["n"] += 1
        if excited:
            excited_s_kk_max = float(g_abs[k_worst])
            u_abs = np.abs(np.asarray(u, dtype=float))
            n_tail = max(1, u_abs.shape[0] // 4)
            peak = float(np.max(u_abs))
            tail_rms = float(np.sqrt(np.mean(u_abs[-n_tail:] ** 2)))
            tail_db = float(20.0 * np.log10(max(tail_rms, 1e-30) / max(peak, 1e-30)))
            continue
        cls["n_non_excited"] += 1
        cls["n_matched"] += int(bool(entry["matched"]))
        cls["z_ui_median_re"].append(zmed.real)
        cls["z_ui_median_im"].append(zmed.imag)
        if term_err_max > cls["term_err_max"]:
            cls["term_err_max"] = term_err_max
            cls["worst_port"] = n
    for cls in by_class.values():
        cls["z_ui_median_re"] = (float(np.median(cls["z_ui_median_re"]))
                                 if cls["z_ui_median_re"] else float("nan"))
        cls["z_ui_median_im"] = (float(np.median(cls["z_ui_median_im"]))
                                 if cls["z_ui_median_im"] else float("nan"))
    non_exc = [v for v in ports.values() if not v["excited"]]
    worst_non_excited = (max(v["term_err_max"] for v in non_exc)
                         if non_exc else float("nan"))
    return {
        "round_dir": str(round_dir),
        "excite_port": excite_port,
        "n_ports_read": len(ports),
        "missing_ports": missing,
        "freq_range_ghz": [float(freqs[0]) / 1e9, float(freqs[-1]) / 1e9],
        "z0": z0,
        "match_tol": tol,
        "non_excited_term_err_max": worst_non_excited,
        "all_non_excited_matched": bool(non_exc) and all(v["matched"] for v in non_exc),
        "excited_s_kk_max_abs": excited_s_kk_max,
        "excited_ut_tail_rms_db": tail_db,
        "excited_ut_tail_decayed": (tail_db is not None and tail_db <= UT_TAIL_PLATEAU_DB),
        "by_class": by_class,
        "ports": ports,
    }


def stage_gamma(args: argparse.Namespace) -> int:
    layout = build_layout()
    geom = build_geom(layout)
    round_dir = (Path(args.round_dir) if args.round_dir
                 else OUT_DIR / "rounds" / args.round)
    if not (round_dir / "fdtd").is_dir():
        print(f"[gamma] 缺 {round_dir / 'fdtd'}：该轮无时域档", flush=True)
        return 2
    if args.excite is not None:
        excite = int(args.excite)
    else:
        name = round_dir.name
        excite = int(name[1:]) if name.startswith("p") and name[1:].isdigit() else 1
    f0 = (FREQ_RANGE_GHZ[0] + FREQ_RANGE_GHZ[1]) / 2 * 1e9
    fc = (FREQ_RANGE_GHZ[1] - FREQ_RANGE_GHZ[0]) / 2 * 1e9
    freqs = np.linspace(f0 - fc, f0 + fc, N_FREQ_POINTS)
    rep = summarize_round_gamma(
        round_dir, geom, freq_hz=freqs, excite_port=excite, z0=Z0,
        tol=float(args.tol))
    out = Path(args.out) if args.out else round_dir / "gamma_report.json"
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[gamma] {round_dir.name} excite={excite} ports={rep['n_ports_read']} "
          f"missing={len(rep['missing_ports'])}")
    for cls, v in rep["by_class"].items():
        print(f"[gamma]   {cls:10s} n={v['n']:3d} non_exc={v['n_non_excited']:3d} "
              f"matched={v['n_matched']:3d} max term_err={v['term_err_max']:.4f} "
              f"(worst p{v['worst_port']}) "
              f"Z_ui~{v['z_ui_median_re']:+.1f}{v['z_ui_median_im']:+.1f}jΩ")
    print(f"[gamma] non-excited max term_err={rep['non_excited_term_err_max']:.4f} "
          f"all_matched={rep['all_non_excited_matched']}  "
          f"excited |S_kk|max={rep['excited_s_kk_max_abs']}  "
          f"ut tail={rep['excited_ut_tail_rms_db']}dB "
          f"decayed={rep['excited_ut_tail_decayed']}")
    print(f"[gamma] report -> {out}")
    return 0


# --------------------------------------------------------------------------- #
# reassemble：150 轮原始 port_ut/port_it → 重推导 Z_ALL（stage-5，零仿真）
# --------------------------------------------------------------------------- #

#: stage-5 缺省产物目录（原 s4 装配产物 runs/mapes_s4/z_all.npz 留痕不覆盖）
S5_OUT_DIR = REPO / "runs" / "mapes_s5_diag"


def read_rounds_ui(
    rounds_dir: Path, q: int, freq_hz: Any,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """读全部 q 轮 fdtd/port_ut·port_it → (uf_all, if_all) (q, q, nf) + 元数据。

    各档用自身时间轴 DFT（vendored ReadUIData 语义，core.dft_time2freq 复刻）；
    任一轮缺档显式报错（重推导不接受缺轮静默补零）。
    """
    from rfauto.core.mapes import dft_time2freq  # 惰性：脚本级依赖清晰

    freqs = np.asarray(freq_hz, dtype=float)
    uf_all = np.zeros((q, q, freqs.size), dtype=complex)
    if_all = np.zeros((q, q, freqs.size), dtype=complex)
    n_samples = np.zeros((q, q), dtype=int)
    t_end = np.zeros((q, q), dtype=float)
    for k in range(1, q + 1):
        fdtd = rounds_dir / f"p{k}" / "fdtd"
        for p in range(1, q + 1):
            rec = read_port_ui_dump(fdtd, p)
            if rec is None:
                raise RuntimeError(f"轮 p{k} 缺端口 {p} 的 port_ut/port_it 时域档：{fdtd}")
            (tu, u), (ti, i), _ = rec
            uf_all[k - 1, p - 1] = dft_time2freq(tu, u, freqs)
            if_all[k - 1, p - 1] = dft_time2freq(ti, i, freqs)
            n_samples[k - 1, p - 1] = tu.size
            t_end[k - 1, p - 1] = float(tu[-1])
    meta = {
        "n_samples_min": int(n_samples.min()), "n_samples_max": int(n_samples.max()),
        "t_end_min_s": float(t_end.min()), "t_end_max_s": float(t_end.max()),
    }
    return uf_all, if_all, meta


def _analysis_freqs() -> np.ndarray:
    """stage-2/5 统一分析频轴（与轮脚本 ``f = linspace(F0-FC, F0+FC, N)`` 同式）。"""
    f0 = (FREQ_RANGE_GHZ[0] + FREQ_RANGE_GHZ[1]) / 2 * 1e9
    fc = (FREQ_RANGE_GHZ[1] - FREQ_RANGE_GHZ[0]) / 2 * 1e9
    return np.linspace(f0 - fc, f0 + fc, N_FREQ_POINTS)


def load_raw_ui(
    rounds_dir: Path, out_dir: Path, q: int, freq_hz: Any, *, fresh: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """读/复用 ``<out_dir>/raw_ui.npz`` 原始 u/i 缓存（reassemble 与 drift 共用）。

    缓存形状 (q,q,nf) 或频轴不符即重读时域档并覆盖缓存；``fresh`` 强制重读。
    """
    freqs = np.asarray(freq_hz, dtype=float)
    cache = Path(out_dir) / "raw_ui.npz"
    if cache.exists() and not fresh:
        with np.load(cache) as d:
            uf_all, if_all = d["uf_all"], d["if_all"]
            if uf_all.shape == (q, q, freqs.size) and np.allclose(d["freq_hz"], freqs):
                return uf_all, if_all, {"cache": str(cache)}
        print(f"[raw_ui] 缓存 {cache} 形状/频轴不符，重读", flush=True)
    uf_all, if_all, meta = read_rounds_ui(Path(rounds_dir), q, freqs)
    np.savez_compressed(cache, freq_hz=freqs, uf_all=uf_all, if_all=if_all)
    return uf_all, if_all, meta


def _finite_or_none(v: Any) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None


def drift_report_json(drift: dict[str, Any]) -> dict[str, Any]:
    """core.mapes.ui_cross_round_drift 结果 → JSON 友好（NaN→None，数组→列表）。"""
    return {
        "n_ports": int(drift["n_ports"]),
        "n_freq": int(drift["n_freq"]),
        "rel_floor": float(drift["rel_floor"]),
        "n_ports_defined": int(drift["n_ports_defined"]),
        "median_of_port_median": _finite_or_none(drift["median_of_port_median"]),
        "max_of_port_max": _finite_or_none(drift["max_of_port_max"]),
        "max_of_port_max_freqmedian": _finite_or_none(drift["max_of_port_max_freqmedian"]),
        "worst_port": (None if drift["worst_port"] is None else int(drift["worst_port"])),
        "snr_buckets": drift["snr_buckets"],
        "port_median_rel": [_finite_or_none(v) for v in drift["port_median_rel"]],
        "port_max_rel": [_finite_or_none(v) for v in drift["port_max_rel"]],
        "port_max_freqmedian_rel": [
            _finite_or_none(v) for v in drift["port_max_freqmedian_rel"]],
        "port_zui_abs_median": [_finite_or_none(v) for v in drift["port_zui_abs_median"]],
        "n_valid_samples": [int(v) for v in drift["n_valid_samples"]],
        "definition": (
            "端口 p 取轮 k≠p 的 Z_ui=uf/if；逐频以各轮实/虚部中位为中心，"
            "相对偏差 |z_k−c|/(|c|+1e-9)；逐端口报 (轮,频) 中位与最大，及"
            "逐轮频中位的跨轮最大（压单频尖峰，定位坏轮）。snr_buckets 按"
            "|if|/该口跨轮中位|if| 固定桶边制表（弱耦合远端轮的比值噪声 vs 探针"
            "几何拾取底分层）；rel_floor>0 时 snr<rel_floor 样本不进逐端口统计。"
            "物理端接轮不变 → 漂移 = 探针装配偏差观测量（#257）"),
    }


def _print_snr_buckets(tag: str, drift: dict[str, Any]) -> None:
    for b in drift["snr_buckets"]:
        hi = "inf" if b["snr_hi"] is None else f"{b['snr_hi']:g}"
        print(f"[{tag}]   snr[{b['snr_lo']:g},{hi}) n={b['n']:7d} "
              f"rel median={_fmt_rel(b['rel_median'])} p95={_fmt_rel(b['rel_p95'])} "
              f"max={_fmt_rel(b['rel_max'])}", flush=True)


def drift_by_class(drift: dict[str, Any], classes: dict[int, str]) -> dict[str, dict[str, Any]]:
    """逐端口漂移按端口类别（io/pixel/…）汇总：类内端口中位数的中位、原始最大、
    频中位最大（坏轮定位口径）与最差端口。"""
    out: dict[str, dict[str, Any]] = {}
    med = np.asarray(drift["port_median_rel"], dtype=float)
    mx = np.asarray(drift["port_max_rel"], dtype=float)
    fm = np.asarray(drift["port_max_freqmedian_rel"], dtype=float)
    for number, cls in sorted(classes.items()):
        p = int(number) - 1
        entry = out.setdefault(cls, {"n": 0, "n_defined": 0, "medians": [], "maxes": [],
                                     "fmeds": [], "worst_port": None, "worst_fmed": -1.0})
        entry["n"] += 1
        if p < med.size and np.isfinite(med[p]):
            entry["n_defined"] += 1
            entry["medians"].append(float(med[p]))
            entry["maxes"].append(float(mx[p]))
            f_val = float(fm[p]) if np.isfinite(fm[p]) else float(mx[p])
            entry["fmeds"].append(f_val)
            if f_val > entry["worst_fmed"]:
                entry["worst_fmed"] = f_val
                entry["worst_port"] = int(number)
    for entry in out.values():
        meds, maxes, fmeds = entry.pop("medians"), entry.pop("maxes"), entry.pop("fmeds")
        entry.pop("worst_fmed")
        entry["median_of_port_median"] = float(np.median(meds)) if meds else None
        entry["max_of_port_max"] = float(np.max(maxes)) if maxes else None
        entry["max_of_port_max_freqmedian"] = float(np.max(fmeds)) if fmeds else None
    return out


def _fmt_rel(v: Any) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{float(v):.3e}"


def _print_drift_summary(tag: str, drift: dict[str, Any]) -> None:
    print(f"[{tag}] 跨轮 Z_ui 漂移（#257 先行诊断）: 端口中位数的中位 "
          f"{_fmt_rel(drift['median_of_port_median'])} / (轮,频) 最大 "
          f"{_fmt_rel(drift['max_of_port_max'])} / 逐轮频中位最大 "
          f"{_fmt_rel(drift['max_of_port_max_freqmedian'])}（最差 p{drift['worst_port']}，"
          f"有效端口 {drift['n_ports_defined']}/{drift['n_ports']}）", flush=True)


def stage_drift(args: argparse.Namespace) -> int:
    """#257 跨轮 Z_ui 漂移诊断（零仿真；装配矩阵类先做跨轮漂移诊断）。"""
    layout = build_layout()
    q = layout.n_ports
    rounds_dir = Path(args.rounds_dir) if args.rounds_dir else OUT_DIR / "rounds"
    out_dir = Path(args.s5_out) if args.s5_out else S5_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = _analysis_freqs()
    t0 = time.time()
    uf_all, if_all, meta = load_raw_ui(
        rounds_dir, out_dir, q, freqs, fresh=bool(getattr(args, "fresh", False)))
    rel_floor = float(getattr(args, "rel_floor", 0.0) or 0.0)
    drift = ui_cross_round_drift(uf_all, if_all, rel_floor=rel_floor)
    classes = port_classes(build_geom(layout))
    by_class = drift_by_class(drift, classes)
    report = {
        "stage": "#257 跨轮 Z_ui 漂移诊断（零仿真，原始 port_ut/port_it）",
        "rounds_dir": str(rounds_dir),
        "raw_meta": meta,
        "freq_range_ghz": [float(freqs[0]) / 1e9, float(freqs[-1]) / 1e9],
        "rel_floor": rel_floor,
        "drift": drift_report_json(drift),
        "by_class": by_class,
    }
    out = out_dir / "drift_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _print_drift_summary("drift", drift)
    _print_snr_buckets("drift", drift)
    for cls, v in by_class.items():
        print(f"[drift]   {cls:10s} n={v['n']:3d} defined={v['n_defined']:3d} "
              f"median={_fmt_rel(v['median_of_port_median'])} "
              f"max={_fmt_rel(v['max_of_port_max'])} "
              f"fmed_max={_fmt_rel(v['max_of_port_max_freqmedian'])} (worst p{v['worst_port']})")
    print(f"[drift] report -> {out} ({time.time() - t0:.0f}s)")
    return 0


def reassemble_z_all(
    uf_all: np.ndarray,
    if_all: np.ndarray,
    freq_hz: np.ndarray,
    *,
    numerator: str = "current",
    gain_cal: bool = True,
    gauge: tuple[float, float] | None = None,
    project: bool = True,
) -> dict[str, Any]:
    """stage-5 重推导管线（纯内核编排，零仿真）：

    S1 = assemble_s_from_ui(numerator)（缺省 current-only：端接口 b=−Z0·I）
    S2 = S1·diag(e^x)，x=fit_reciprocity_gain（互易势场；全局尺度不可辨识）
    S3 = sym(S2)                       互易精确
    S3g = g(f)·S3（可选显式全局规范 g0,τ；缺省不加——见 reassemble 报告的裁判冲突）
    Z4 = passive_project_z(Z3g)（可选；数值口径，量级如实回报）
    返回各阶段矩阵与门指标 dict。
    """
    freqs = np.asarray(freq_hz, dtype=float)
    stages: dict[str, Any] = {}
    s1 = assemble_s_from_ui(uf_all, if_all, reference_impedance=Z0, numerator=numerator)
    stages["S1_" + numerator] = {"s": s1, "gate": z_all_gate(s1, reference_impedance=Z0)}
    s_cur = s1
    gain_info: dict[str, Any] | None = None
    x = None
    if gain_cal:
        x, gain_info = fit_reciprocity_gain(s1)
        s_cur = apply_port_gain(s1, x)
        stages["S2_gain_cal"] = {"s": s_cur, "gate": z_all_gate(s_cur, reference_impedance=Z0)}
    s_sym = 0.5 * (s_cur + np.swapaxes(s_cur, -1, -2))
    if gauge is not None:
        g0, tau_ps = float(gauge[0]), float(gauge[1])
        s_sym = s_sym * gauge_factor(freqs, g0, tau_ps * 1e-12)[:, None, None]
    stages["S3_sym"] = {"s": s_sym, "gate": z_all_gate(s_sym, reference_impedance=Z0)}
    z_sym = s_to_z(s_sym, reference_impedance=Z0)
    out: dict[str, Any] = {
        "stages": stages, "gain_info": gain_info, "log_gamma": x,
        "z_cal_sym": z_sym, "s_cal_sym": s_sym, "gauge": gauge,
    }
    if project:
        z_proj, proj_info = passive_project_z(z_sym)
        s_proj = z_to_s(z_proj, reference_impedance=Z0)
        stages["S4_passive_proj"] = {
            "s": s_proj, "gate": z_all_gate(s_proj, reference_impedance=Z0)}
        out["z_cal_sym_proj"] = z_proj
        out["s_cal_sym_proj"] = s_proj
        out["projection_info"] = proj_info
    return out


def stage_reassemble(args: argparse.Namespace) -> int:
    layout = build_layout()
    q = layout.n_ports
    rounds_dir = Path(args.rounds_dir) if args.rounds_dir else OUT_DIR / "rounds"
    out_dir = Path(args.s5_out) if args.s5_out else S5_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = _analysis_freqs()
    t0 = time.time()
    uf_all, if_all, meta = load_raw_ui(
        rounds_dir, out_dir, q, freqs, fresh=bool(getattr(args, "fresh", False)))
    print(f"[reassemble] raw u/i ready ({time.time() - t0:.0f}s) {meta}", flush=True)

    # #257：装配矩阵类先做跨轮漂移诊断（同端口跨轮 Z_ui 应轮不变；漂移 =
    # 探针装配偏差直接观测量），数字随报告落盘，不设门限（数值纪律）。
    drift = ui_cross_round_drift(uf_all, if_all)
    _print_drift_summary("reassemble", drift)
    _print_snr_buckets("reassemble", drift)

    gauge = None
    if args.gauge:
        g0_s, tau_s = args.gauge.split(",")
        gauge = (float(g0_s), float(tau_s))
    # OpenBLAS 多线程在 150×150 批量 solve 上实测慢 85×（9.7s vs 0.11s），
    # 重推导阶段限单线程；threadpoolctl 为 sklearn 传递依赖，缺则跳过
    try:
        from threadpoolctl import threadpool_limits
    except Exception:  # pragma: no cover - 可选加速
        threadpool_limits = None
    if threadpool_limits is not None:
        with threadpool_limits(limits=1):
            res = reassemble_z_all(
                uf_all, if_all, freqs, numerator=args.numerator,
                gain_cal=not args.no_gain_cal, gauge=gauge, project=not args.no_project)
    else:
        res = reassemble_z_all(
            uf_all, if_all, freqs, numerator=args.numerator,
            gain_cal=not args.no_gain_cal, gauge=gauge, project=not args.no_project)

    report: dict[str, Any] = {
        "stage": "stage-5 Z_ALL 重推导（零仿真，runs/mapes_s4 150 轮原始时域档）",
        "rounds_dir": str(rounds_dir),
        "numerator": args.numerator,
        "gain_cal": not args.no_gain_cal,
        "gauge_g0_tau_ps": list(gauge) if gauge else None,
        "projected": not args.no_project,
        "raw_meta": meta,
        "cross_round_drift": drift_report_json(drift),
        "gain_fit": res["gain_info"],
        "projection_info": res.get("projection_info"),
        "stages": {k: v["gate"] for k, v in res["stages"].items()},
        "caliber_note": (
            "S3_sym = current-only 装配 + 互易势场增益校准 + 对称化（物理步骤，无门拟合）；"
            "S4_passive_proj = 再加 Re(Z) 特征值最小钳位（数值口径），钳位量级见 "
            "projection_info。全局复尺度由互易不可辨识，直接全波干净腿与装配腿共用同类 "
            "LumpedPort 探针（同源偏差），不能作绝对幅度裁判（见 runs/mapes_s5_diag/"
            "gauge_report.json 裁判冲突记录）；绝对尺度待 HFSS 仲裁（#190）。"),
    }
    save: dict[str, Any] = {
        "freq_hz": freqs, "s_cal_sym": res["s_cal_sym"], "z_cal_sym": res["z_cal_sym"],
    }
    if res["log_gamma"] is not None:
        save["log_gamma"] = res["log_gamma"]
    # S2 口径矩阵顺带落盘（此前只在分析时算出）：
    # 管线 S2_gain_cal 阶段矩阵 = S1(numerator)·diag(e^x)。
    if "S2_gain_cal" in res["stages"]:
        save["s2_gain_cal"] = res["stages"]["S2_gain_cal"]["s"]
    # 口径纪律：S2 数值口径显式消费——verdict 记录所用量径与
    # 消费矩阵；缺省 caliber="raw" 不新增任何键（报告/落盘与现状逐字节一致）。
    caliber = getattr(args, "caliber", "raw") or "raw"
    if caliber != "raw":
        s_caliber, _prov = reciprocity_caliber_matrix(
            uf_all, if_all, caliber=caliber, reference_impedance=Z0)
        report["caliber"] = caliber
        report["caliber_gate"] = z_all_gate_caliber(
            uf_all, if_all, caliber=caliber, reference_impedance=Z0)
        save["s_caliber_matrix"] = s_caliber
        cg = report["caliber_gate"]
        print(f"[reassemble] caliber={caliber} "
              f"rec={cg['reciprocity_max']:.3e} "
              f"target5e3={'met' if cg['reciprocity_target_met'] else 'NOT-met'} "
              f"gate_pass={cg['pass']} (circular={cg['caliber_circular']})",
              flush=True)
    if "z_cal_sym_proj" in res:
        save["z_cal_sym_proj"] = res["z_cal_sym_proj"]
        save["s_cal_sym_proj"] = res["s_cal_sym_proj"]
    np.savez_compressed(out_dir / "z_all_s5.npz", **save)
    (out_dir / "reassemble_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, v in report["stages"].items():
        print(f"[reassemble] {name:16s} rec={v['reciprocity_max']:.3e} "
              f"min_eig={v['min_eig_re_min']:+.3e} smax={v['sigma_max']:.5f} "
              f"pass={v['pass']}", flush=True)
    if res.get("projection_info"):
        pi = res["projection_info"]
        print(f"[reassemble] projection clip_max={pi['max_eig_clip_ohm']:.3e}Ω "
              f"rel_fro={pi['rel_fro']:.3e}", flush=True)
    print(f"[reassemble] -> {out_dir / 'z_all_s5.npz'} / reassemble_report.json "
          f"({time.time() - t0:.0f}s)")
    return 0


def _parse_ports(spec: str | None, q: int) -> list[int]:
    if not spec:
        return list(range(1, q + 1))
    rounds: list[int] = []
    for chunk in spec.split(","):
        if "-" in chunk:
            lo, hi = chunk.split("-")
            rounds.extend(range(int(lo), int(hi) + 1))
        else:
            rounds.append(int(chunk))
    bad = [k for k in rounds if not (1 <= k <= q)]
    if bad:
        raise ValueError(f"端口号越界：{bad} (1..{q})")
    return rounds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=None,
                        help="产物根目录（缺省 runs/mapes_s4；stage-2 原档 runs/mapes_s2 零覆盖）")
    parser.add_argument("--base-mm", type=float, default=None,
                        help="XY 网格 base（米，缺省模块常量；σmax 排查用细档如 0.4/0.3）")
    sub = parser.add_subparsers(dest="stage", required=True)
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--grid", type=int, default=6,
                        help="像素阵边长 N（N×N；10 → Q=446 规模推演，不启动真跑）")
    p_rot = sub.add_parser("rotate")
    p_rot.add_argument("--ports", default=None,
                       help="子集，如 '1-2'（计时冒烟）；缺省全量")
    p_rot.add_argument("--fresh", action="store_true", help="忽略断点缓存")
    p_rot.add_argument("--nr-ts", type=int, default=None,
                       help="FDTD 步数上限覆盖（缺省 NR_TS；#257 中线加密后 dt 约减半，"
                            "截断纹波时上调）")
    p_pat = sub.add_parser("patterns")
    p_pat.add_argument("--patterns", default=None, help="逗号分隔子集")
    p_pat.add_argument("--fresh", action="store_true")
    p_pat.add_argument("--nr-ts", type=int, default=None,
                       help="FDTD 步数上限覆盖（与 rotate 保持同值以便对拍）")
    p_gam = sub.add_parser("gamma")
    p_gam.add_argument("--round", default="p1", help="轮名（rounds/ 下，如 p1）")
    p_gam.add_argument("--round-dir", default=None,
                       help="直接给轮目录（含 fdtd/ 的路径），优先于 --round")
    p_gam.add_argument("--excite", type=int, default=None,
                       help="激励端口号（缺省按轮名 p<k> 推断）")
    p_gam.add_argument("--tol", type=float, default=GAMMA_MATCH_TOL)
    p_gam.add_argument("--out", default=None, help="报告 JSON 落盘路径")
    p_re = sub.add_parser("reassemble",
                          help="stage-5：150 轮原始 port_ut/port_it 重推导 Z_ALL（零仿真）")
    p_re.add_argument("--rounds-dir", default=None,
                      help="轮目录（缺省 <out-dir>/rounds，即 runs/mapes_s4/rounds）")
    p_re.add_argument("--s5-out", default=None,
                      help="产物目录（缺省 runs/mapes_s5_diag；不覆盖 s4 装配产物）")
    p_re.add_argument("--numerator", choices=("current", "wave"), default="current",
                      help="端接口出射波口径：current=−Z0·I（缺省）/ wave=引擎波分解")
    p_re.add_argument("--no-gain-cal", action="store_true",
                      help="跳过互易势场增益校准")
    p_re.add_argument("--gauge", default=None,
                      help="显式全局规范 'g0,tau_ps'（缺省不加；互易不可辨识）")
    p_re.add_argument("--no-project", action="store_true", help="跳过无源投影")
    p_re.add_argument("--caliber", default="raw",
                      choices=("raw", "wave", "s2"),
                      help="互易判读量径：raw=current-only "
                           "原始装配（缺省，报告零新增键）/ wave=波分解 / "
                           "s2=互易势场数值口径（循环量，达标档）。非 raw 时报告增 "
                           "caliber/caliber_gate 且 npz 落盘 s_caliber_matrix；"
                           "门阈值常量不动")
    p_re.add_argument("--fresh", action="store_true", help="忽略 raw_ui.npz 缓存重读时域档")
    p_dr = sub.add_parser("drift",
                          help="#257：跨轮 Z_ui 漂移诊断（零仿真；装配矩阵类先做跨轮漂移诊断）")
    p_dr.add_argument("--rounds-dir", default=None,
                      help="轮目录（缺省 <out-dir>/rounds，即 runs/mapes_s4/rounds）")
    p_dr.add_argument("--s5-out", default=None,
                      help="产物/缓存目录（缺省 runs/mapes_s5_diag，与 reassemble 共用 raw_ui.npz）")
    p_dr.add_argument("--fresh", action="store_true", help="忽略 raw_ui.npz 缓存重读时域档")
    p_dr.add_argument("--rel-floor", type=float, default=0.0,
                      help="信噪门：|if|/该口跨轮中位|if| 低于此值的样本不进逐端口统计"
                           "（缺省 0=全样本；分桶表恒报）")
    args = parser.parse_args()
    global OUT_DIR, BASE_M
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)
    if args.base_mm:
        BASE_M = float(args.base_mm) * 1e-3
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.stage == "plan":
        return stage_plan(args)
    if args.stage == "rotate":
        return stage_rotate(args)
    if args.stage == "gamma":
        return stage_gamma(args)
    if args.stage == "reassemble":
        return stage_reassemble(args)
    if args.stage == "drift":
        return stage_drift(args)
    return stage_patterns(args)


if __name__ == "__main__":
    raise SystemExit(main())
