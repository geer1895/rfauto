"""MSL↔slotline 过渡 + Marchand 双槽臂巴伦 openEMS 渲染器（附加模板口径）。

**附加模板**（不进 openems_templates.py/TEMPLATE_META/EXPECTED_TEMPLATES，
注册四件套另行登记）。理论口径与设计式见 `core/slotline_transitions.py`
docstring（Roberts 1957 / Knorr 1974 / Schuppert 1988 / Garg-Bahl-Bozzi 3rd ed /
Marchand 1944）；复用路线 B 的双行波 β 拟合与抽头拓扑口径（只读 import
`slotline_lumped_template.two_wave_beta_fit`，inspect 单源注入渲染脚本）。

几何（layout 单一事实源，米；设计点与路线 A/B 同：f0=2.5GHz、RO4350B
h=1.524/εr=3.66/tanδ=0.0037、槽宽 1.0mm → 闭式 Z0=110.92Ω/λ'=93.4624mm；
微带 50Ω w=3.3439mm/εeff=2.8530 → 支节=λg_m/4+Δl=18.3725mm、短路臂=23.3656mm）：

render_msl_slot_transition（2 口，Roberts/Knorr 过渡）：
- 双层板：基板 z∈[0,h]；底层地板 z=0 开槽（|y|≤s/2，沿 x）；顶层微带 z=h；
- 槽开口 x∈[−dom_x, +x_sh]，+x_sh 处金属封口=λg'/4 短路臂（跨越点 x=0 右侧，
  虚开路）；输出臂向 −x 至 P2（LumpedPort 跨槽，R=闭式 Z0；端口距 PML 净距
  16·BASE，槽贯通直入 PML=匹配端接，路线 B 同款）；
- 微带 P1（MSLPort 自画馈线 y∈[−dom_y, y0]）沿 y 在 x=0 跨槽，继续延伸开路
  支节 λg_m/4+Δl 至 y=+s/2+l_stub（虚短路）；
- 域：x 轴 PML_8×2；y−面为 P1 端口面、y+ 面 MUR；z 全 MUR（开放结构，带槽
  地板向下泄漏需 z_bot 空气）。

render_marchand_balun（3 口，双槽臂最小 Marchand）：
- 底层地板两条平行槽（中心距 d_c=w_m+s，中条宽=微带宽）：槽 1（y=+d_c/2）
  开口 x∈[−x_sh, +dom_x] 右端输出 P2、左端 x=−x_sh 封口短路；槽 2 镜像（左端
  输出 P3、右端 +x_sh 封口）——底层金属五盒枚举（M1/M2 外地、M3 中条、
  M4/M5 封口桥），M4/M5 与 M3 在 x=±x_sh 精确共边（该处网格线已钉，PEC 共棱
  连通；与过渡段封口的 SEAM 搭接不同：搭接会关槽，此处只能共边）；
- 微带 P1 自 y=+dom_y 边沿 −y 穿两槽，跨槽 2 后延伸开路支节至 y=−(a2+l_stub)；
- **极性约定**：P2/P3 的 start/stop 均按 y 递增（槽 1 口跨[中条→外地]、槽 2 口
  跨[外地→中条]）——该约定下 push-pull 平衡 ⇒ S21/S31 同相（phase_diff≈0°）；
  读出 ≈180° ⇒ 结构实为同相分配器。幅度/回损/隔离门与极性无关。

端口与 S 参数口径：
- P1 MSLPort：线基（CalcPort 自算 Z_ref(f)/β(f)——微带 β 锚白得）；
- P2/P3 LumpedPort 跨槽 = 路线 B **并联抽头拓扑**（#250）：原始 S 含抽头物理
  基线（理想 DUT：接收抽头读 |1+Γ|，Γ=(R∥Z0−Z0)/(R∥Z0+Z0)；R=Z0 时 =2/3
  → −3.52dB；抽头作源口再乘同量级发射因子 2·Zp/(R+Zp)）。混合口功率归一
  S_2j=(uf2/ufj_inc)·sqrt(Z_ref1/R2)；抽头修正 `tap_receive_factor_db` /
  `tap_source_factor_db`——**判据门按修正值，原始值并列如实报告**；
- S23（隔离）需第二激励（excite_port=2，#208 进程隔离单激励渲染）；S12 由
  互易与 S21 对拍（信息项）。

离线审计（#212）：exec 脚本头（RUN_MARKER 前）→ CSXCAD 实测金属连通分组
（槽真断开/中条真隔离）、端口盒三向非零、探针与网格边。

运行前置：openEMS Python 绑定（CSXCAD/openEMS）需已安装——在 PATH，
或经 RFAUTO_OPENEMS_BIN 环境变量指定 bin 目录（渲染脚本不注入固定安装路径）。
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.adapters.slotline_lumped_template import two_wave_beta_fit
from rfauto.core.slotline_transitions import (
    MarchandDesign,
    marchand_design,
    transition_design,
)

C0 = 299792458.0
N_PROBE_STATIONS = 7          # 每臂槽跨压探针站数
SUBSTRATE_Z_LAYERS = 6        # 基板 z 网格层数
PORT_INSET_BASE = 16.0        # 端口→PML 净距（×BASE；须 > PML_8≈8·BASE）
MSL_PORT_CLEAR_BASE = 14.0    # MSLPort 段起点→边界净距（×BASE；H4：段须出
                              # PML_8≈8·BASE + FeedShift 2.5·BASE 仍留净空）
METAL_SEAM_OVERLAP = 3.0      # 过渡段封口安全搭接（×NEAR；不关槽方向）
RUN_MARKER = "# ── 求解 ──"    # 离线审计 exec 截断标记（FDTD.Run 之前）

_DESIGN_DEFAULTS = {"w_slot_mm": 1.0, "h_mm": 1.524, "er": 3.66,
                    "tan_d": 0.0037, "f0_ghz": 2.5, "x_port_mm": 40.0,
                    "dom_y_mm": 50.0, "msl_port_len_mm": 10.0,
                    "z_bot_mm": 30.0, "z_top_mm": 20.0}


@dataclass(frozen=True)
class TransitionLayout:
    """Roberts/Knorr 过渡几何/端口/探针布局（米）。"""

    s_m: float
    h_m: float
    er: float
    w_msl_m: float
    l_short_m: float              # x_sh：跨越点→封口（λg'/4）
    l_stub_m: float
    y_stub_tip_m: float           # = +s/2 + l_stub
    x_port_m: float
    dom_x_m: float
    dom_y_m: float
    z_bot_m: float
    z_top_m: float
    y_p1_edge_m: float            # MSLPort 段起点（近边界侧，出 PML）
    y_p1_inner_m: float           # MSLPort 馈线段内端（y0）
    probe_x_m: tuple[float, ...]  # 输出臂探针 x（负半轴）
    base_m: float
    near_m: float
    port_dx_m: float
    port_dz_m: float
    r_slot_ohm: float             # 槽线闭式 Z0（端口 R 与抽头修正基线）
    beta_slot_f0: float           # 槽线闭式 β@f0（双行波先验）
    beta_msl_f0: float            # 微带 HJ β@f0（对照锚，仅记录）


@dataclass(frozen=True)
class MarchandLayout(TransitionLayout):
    """双槽臂 Marchand 巴伦布局（过渡布局 + 槽距/双臂探针）。"""

    d_center_m: float = 0.0
    a1_m: float = 0.0             # 槽内缘 |y|（中条半宽）
    a2_m: float = 0.0             # 槽外缘 |y|
    probe_a_x_m: tuple[float, ...] = ()   # 臂 1（+x 输出）探针 x
    probe_b_x_m: tuple[float, ...] = ()   # 臂 2（−x 输出）探针 x


def _base_mesh(params: dict[str, Any], freq_range_ghz: tuple[float, float],
               mesh_resolution_mm: float) -> tuple[float, float]:
    """(base, near) 米：λ_sub/50@F_MAX 或显式覆盖；near=base/4（路线 B 同）。"""
    er = float(params.get("er", _DESIGN_DEFAULTS["er"]))
    f_max = max(float(freq_range_ghz[0]), float(freq_range_ghz[1])) * 1e9
    base = (C0 / (f_max * math.sqrt(er)) / 50.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    return base, base / 4.0


def _common_mm(params: dict[str, Any], freq_range_ghz: tuple[float, float],
               mesh_resolution_mm: float) -> dict[str, float]:
    """公共几何量校验与换算（米）。"""
    d = {k: float(params.get(k, v)) for k, v in _DESIGN_DEFAULTS.items()}
    for k in ("w_slot_mm", "h_mm", "x_port_mm", "dom_y_mm",
              "msl_port_len_mm", "z_bot_mm", "z_top_mm"):
        if not (math.isfinite(d[k]) and d[k] > 0):
            raise ValueError(
                f"slotline_transitions: {k} 必须为正有限，得到 {d[k]!r}")
    if not (1.0 < d["er"] < 20.0):
        raise ValueError(f"slotline_transitions: er={d['er']!r} 非物理")
    base, near = _base_mesh(params, freq_range_ghz, mesh_resolution_mm)
    if d["h_mm"] * 1e-3 < 2 * near:
        raise ValueError("slotline_transitions: 基板过薄（<2·NEAR）")
    if d["msl_port_len_mm"] * 1e-3 < 8 * base:
        raise ValueError("slotline_transitions: MSL 端口段过短（<8·BASE）")
    return {**d, "base_m": base, "near_m": near}


def _probe_stations(x_port_m: float, n: int = N_PROBE_STATIONS) -> tuple:
    """输出臂探针 x：[10%, 90%]·x_port 均布（避开端口盒与跨越点）。"""
    lo, hi = 0.10 * x_port_m, 0.90 * x_port_m
    return tuple(lo + k * (hi - lo) / (n - 1) for k in range(n))


def _design_common(params: dict[str, Any], freq_range_ghz: tuple[float, float],
                   mesh_resolution_mm: float,
                   f0_ghz: float | None) -> tuple[dict, Any, float, float]:
    d = _common_mm(params, freq_range_ghz, mesh_resolution_mm)
    f0 = f0_ghz if f0_ghz is not None else d["f0_ghz"]
    design = transition_design(f0, d["h_mm"], d["er"], d["w_slot_mm"],
                               d["tan_d"])
    return d, design, d["base_m"], d["near_m"]


def msl_slot_transition_layout(params: dict[str, Any],
                               freq_range_ghz: tuple[float, float],
                               mesh_resolution_mm: float = 0.0,
                               f0_ghz: float | None = None) -> TransitionLayout:
    """过渡段几何/端口/探针布局单一事实源（mm 入参 → 米）。"""
    d, design, base, near = _design_common(params, freq_range_ghz,
                                           mesh_resolution_mm, f0_ghz)
    s = d["w_slot_mm"] * 1e-3
    x_port = d["x_port_mm"] * 1e-3
    dom_y = d["dom_y_mm"] * 1e-3
    dom_x = x_port + PORT_INSET_BASE * base
    x_sh = design.l_short_mm * 1e-3
    y_tip = s / 2.0 + design.l_stub_mm * 1e-3
    if x_sh + METAL_SEAM_OVERLAP * near >= dom_x:
        raise ValueError("msl_slot_transition_layout: 封口位置越过域界")
    if y_tip + 5 * base >= dom_y:
        raise ValueError("msl_slot_transition_layout: 开路支节端距 MUR 过近")
    k0 = 2 * math.pi * design.f0_ghz * 1e9 / C0
    return TransitionLayout(
        s_m=s, h_m=d["h_mm"] * 1e-3, er=d["er"], w_msl_m=design.w_msl_mm * 1e-3,
        l_short_m=x_sh, l_stub_m=design.l_stub_mm * 1e-3, y_stub_tip_m=y_tip,
        x_port_m=x_port, dom_x_m=dom_x, dom_y_m=dom_y,
        z_bot_m=d["z_bot_mm"] * 1e-3, z_top_m=d["z_top_mm"] * 1e-3,
        y_p1_edge_m=-dom_y + MSL_PORT_CLEAR_BASE * base,
        y_p1_inner_m=-dom_y + (MSL_PORT_CLEAR_BASE * base
                               + d["msl_port_len_mm"] * 1e-3),
        probe_x_m=tuple(-x for x in _probe_stations(x_port)),
        base_m=base, near_m=near, port_dx_m=near, port_dz_m=near,
        r_slot_ohm=design.z_slot_ohm, beta_slot_f0=design.eps_eff_slot ** 0.5 * k0,
        beta_msl_f0=design.eps_eff_msl ** 0.5 * k0)


def marchand_balun_layout(params: dict[str, Any],
                          freq_range_ghz: tuple[float, float],
                          mesh_resolution_mm: float = 0.0,
                          f0_ghz: float | None = None) -> MarchandLayout:
    """巴伦几何/端口/探针布局单一事实源（mm 入参 → 米）。"""
    d, design, base, near = _design_common(params, freq_range_ghz,
                                           mesh_resolution_mm, f0_ghz)
    mdesign = marchand_design(design.f0_ghz, d["h_mm"], d["er"],
                              d["w_slot_mm"], d["tan_d"])
    assert isinstance(mdesign, MarchandDesign)
    s = d["w_slot_mm"] * 1e-3
    x_port = d["x_port_mm"] * 1e-3
    dom_y = d["dom_y_mm"] * 1e-3
    dom_x = x_port + PORT_INSET_BASE * base
    x_sh = mdesign.l_short_mm * 1e-3
    a1, a2 = mdesign.a1_mm * 1e-3, mdesign.a2_mm * 1e-3
    y_tip = -(a2 + mdesign.l_stub_mm * 1e-3)
    if not (0.0 < a1 < a2):
        raise ValueError("marchand_balun_layout: 槽几何非正（a1<a2 要求）")
    if x_sh + METAL_SEAM_OVERLAP * near >= dom_x:
        raise ValueError("marchand_balun_layout: 封口位置越过域界")
    if abs(y_tip) + 5 * base >= dom_y:
        raise ValueError("marchand_balun_layout: 开路支节端距 MUR 过近")
    k0 = 2 * math.pi * mdesign.f0_ghz * 1e9 / C0
    probes = _probe_stations(x_port)
    return MarchandLayout(
        s_m=s, h_m=d["h_mm"] * 1e-3, er=d["er"], w_msl_m=mdesign.w_msl_mm * 1e-3,
        l_short_m=x_sh, l_stub_m=mdesign.l_stub_mm * 1e-3, y_stub_tip_m=y_tip,
        x_port_m=x_port, dom_x_m=dom_x, dom_y_m=dom_y,
        z_bot_m=d["z_bot_mm"] * 1e-3, z_top_m=d["z_top_mm"] * 1e-3,
        y_p1_edge_m=dom_y - MSL_PORT_CLEAR_BASE * base,
        y_p1_inner_m=dom_y - (MSL_PORT_CLEAR_BASE * base
                              + d["msl_port_len_mm"] * 1e-3),
        probe_x_m=probes,
        base_m=base, near_m=near, port_dx_m=near, port_dz_m=near,
        r_slot_ohm=mdesign.z_slot_ohm,
        beta_slot_f0=mdesign.eps_eff_slot ** 0.5 * k0,
        beta_msl_f0=mdesign.eps_eff_msl ** 0.5 * k0,
        d_center_m=mdesign.d_center_mm * 1e-3, a1_m=a1, a2_m=a2,
        probe_a_x_m=probes, probe_b_x_m=tuple(-x for x in probes))


def tap_receive_factor_db(r_port_ohm: float, z0_line_ohm: float) -> float:
    """并联抽头口"到达波读数"因子（dB）：|1+Γ|，Γ=(R∥Z0−Z0)/(R∥Z0+Z0)。

    理想 DUT（PML 匹配线 + 单接收抽头）下原始读数=真波幅×|1+Γ|；R=Z0 时
    =2/3 → −3.52dB（路线 B 抽头模型 #250 的单抽头接收侧推广）。
    """
    r, z0 = float(r_port_ohm), float(z0_line_ohm)
    if not (r > 0 and z0 > 0):
        raise ValueError("tap_receive_factor_db: R/Z0 必须为正")
    z_node = r * z0 / (r + z0)
    gam = (z_node - z0) / (z_node + z0)
    return float(20.0 * np.log10(abs(1.0 + gam)))


def tap_source_factor_db(r_port_ohm: float, z0_line_ohm: float) -> float:
    """并联抽头作源口的发射因子（dB）：2·Zp/(R+Zp)，Zp=Z0∥Z_DUT≈Z0/2（匹配）。

    理想匹配下与接收因子同值（R=Z0 → 2/3）；S23/S22 原始读数基线=源+收因子。
    """
    r, z0 = float(r_port_ohm), float(z0_line_ohm)
    if not (r > 0 and z0 > 0):
        raise ValueError("tap_source_factor_db: R/Z0 必须为正")
    z_p = z0 / 2.0
    return float(20.0 * np.log10(2.0 * z_p / (r + z_p)))


# ─────────────────────────────── 渲染：过渡段 ───────────────────────────────

def render_msl_slot_transition(params: dict[str, Any],
                               freq_range_ghz: tuple[float, float],
                               mesh_resolution_mm: float = 0.0,
                               nrts: int = 100000,
                               excite_port: int = 1) -> str:
    """渲染 Roberts/Knorr 过渡自包含 openEMS 脚本（P1 微带 MSLPort 激励）。"""
    if excite_port != 1:
        raise ValueError(f"过渡段只有 P1（微带）激励，得 {excite_port!r}")
    lay = msl_slot_transition_layout(params, freq_range_ghz, mesh_resolution_mm)
    tan_d = float(params.get("tan_d", _DESIGN_DEFAULTS["tan_d"]))
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    n_sub = SUBSTRATE_Z_LAYERS + 1
    two_wave_src = inspect.getsource(two_wave_beta_fit)
    rx_db = tap_receive_factor_db(lay.r_slot_ohm, lay.r_slot_ohm)
    probes = ", ".join(repr(float(x)) for x in lay.probe_x_m)
    port_len = abs(lay.y_p1_edge_m - lay.y_p1_inner_m)
    return f'''#!/usr/bin/env python3
"""openEMS slotline transition script (rfauto, auto-generated).

几何/端口/网格口径与理论出处见
src/rfauto/adapters/slotline_transitions_template.py 与
src/rfauto/core/slotline_transitions.py 模块 docstring。
运行前置：openEMS Python 绑定需已安装——在 PATH，或经 RFAUTO_OPENEMS_BIN
环境变量指定 bin 目录。
"""
import csv
import json
import os

# openEMS Python 绑定（CSXCAD/openEMS）需已安装并在 PATH；也可用
# RFAUTO_OPENEMS_BIN 环境变量显式指定 bin 目录（未给出时不注入任何路径）。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", "")
if _OE_BIN and os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import LumpedPort, MSLPort, UI_data

F0 = {f0!r}
FC = {fc!r}
ER = {lay.er!r}
TAND = {tan_d!r}
S_W = {lay.s_m!r}         # 槽宽
H_SUB = {lay.h_m!r}
W_MSL = {lay.w_msl_m!r}   # 微带 50Ω 线宽（skrf HJ 综合）
X_SH = {lay.l_short_m!r}  # 槽线短路臂 λg'/4（封口 x）
Y_TIP = {lay.y_stub_tip_m!r}   # 微带开路支节端 y
X_PORT = {lay.x_port_m!r}
DOM_X = {lay.dom_x_m!r}
DOM_Y = {lay.dom_y_m!r}
Z_BOT = {lay.z_bot_m!r}
Z_TOP = {lay.z_top_m!r}
Y_P1E = {lay.y_p1_edge_m!r}    # MSLPort 段起点（出 PML，14·BASE 净空）
Y0 = {lay.y_p1_inner_m!r}      # MSLPort 馈线段内端
PORT_DX = {lay.port_dx_m!r}
PORT_DZ = {lay.port_dz_m!r}
BASE = {lay.base_m!r}
NEAR = {lay.near_m!r}
R_SLOT = {lay.r_slot_ohm!r}    # 槽线闭式 Z0（P2 R=CalcPort 参考）
RX_DB = {rx_db!r}              # 接收抽头读数基线（理想 DUT，|1+Γ|）
BETA_SLOT_F0 = {lay.beta_slot_f0!r}
BETA_MSL_F0 = {lay.beta_msl_f0!r}
NRTS = {int(nrts)}
PROBE_X = np.array([{probes}])
SEAM = {METAL_SEAM_OVERLAP!r} * NEAR
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 仿真环境（官方方法学：不设 EndCriteria，默认能量判据）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()

def _axis(ax, near_pts, dom_lo, dom_hi):
    for p_ in near_pts:
        mesh.AddLine(ax, p_)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_axis("x", [0.0, W_MSL / 2, -W_MSL / 2, X_SH, -X_PORT,
            -X_PORT - PORT_DX / 2, -X_PORT + PORT_DX / 2] + list(PROBE_X),
      -DOM_X, DOM_X)
_axis("y", [0.0, S_W / 2, -S_W / 2, Y_TIP, Y_P1E, Y0], -DOM_Y, DOM_Y)
mesh.AddLine("z", np.linspace(0, H_SUB, {n_sub}))
mesh.AddLine("z", np.array([-NEAR, 0.0, NEAR, H_SUB, H_SUB + NEAR,
                            -PORT_DZ / 2, PORT_DZ / 2]))
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", NEAR)
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", BASE)
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：基板铺满域；底层地板开槽（封口=λg'/4 短路臂）；顶层微带支节 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
gnd = CSX.AddMetal("gnd_slot")
# 槽 |y|<S_W/2 开口 x∈[-DOM_X, X_SH]（贯通直入 PML=匹配端接）；A/B 向 +x 搭接
# SEAM 防共棱浮岛（搭接区在 |y|>S_W/2 金属内，不关槽）；C 盒封口+短路面
gnd.AddBox((-DOM_X, S_W / 2, 0.0), (X_SH + SEAM, DOM_Y, 0.0), priority=10)
gnd.AddBox((-DOM_X, -DOM_Y, 0.0), (X_SH + SEAM, -S_W / 2, 0.0), priority=10)
gnd.AddBox((X_SH, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
msl = CSX.AddMetal("msl_top")
# 微带整线自画：从域边（贯通 PML=端接）到开路支节端；MSLPort 段自画盒与之重叠
msl.AddBox((-W_MSL / 2, -DOM_Y, H_SUB), (W_MSL / 2, Y_TIP, H_SUB),
           priority=10)

# ── 端口 ──
# P1：MSLPort（微带，线基：CalcPort 自算 Z_ref(f)/β(f)）；P2：LumpedPort 跨槽
# （R=槽线 Z0，并联抽头拓扑 #250——原始 S 含抽头基线，判读按 RX_DB 修正口径）
_port1 = MSLPort(CSX, port_nr=1, metal_prop=msl,
                 start=np.array([W_MSL / 2, Y_P1E, H_SUB]),
                 stop=np.array([-W_MSL / 2, Y0, 0.0]),
                 prop_dir="y", exc_dir="z", excite=1.0,
                 FeedShift=10 * NEAR, MeasPlaneShift={port_len / 3!r},
                 priority=10)
for _prim in msl.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
_p2_start = np.array([-X_PORT - PORT_DX / 2, -S_W / 2, -PORT_DZ / 2])
_p2_stop = np.array([-X_PORT + PORT_DX / 2, S_W / 2, PORT_DZ / 2])
_port2 = LumpedPort(CSX, 2, R_SLOT, _p2_start, _p2_stop, "y", excite=0,
                    priority=5)

# ── β 探针：输出臂槽跨压（p_type=0，z=0 金属面）N 站均布 ──
for _k, _px in enumerate(PROBE_X):
    _vp = CSX.AddProbe("vslot_%02d" % _k, p_type=0)
    _vp.AddBox(np.array([_px, -S_W / 2, 0.0]), np.array([_px, S_W / 2, 0.0]))

{RUN_MARKER}
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：S11（P1 线基）+ S21（抽头基线修正口径）+ 双行波 β ──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f)
_port2.CalcPort(SIM_PATH, f)
S11 = _port1.uf_ref / _port1.uf_inc
Z1 = np.abs(_port1.Z_ref)                 # 微带线基阻抗（逐频，CalcPort 自算）
BETA_MSL = np.real(_port1.beta)
_pnorm = np.sqrt(Z1 / R_SLOT)             # 混合口功率归一（50Ω↔槽线）
S21_REF = _port2.uf_ref / _port1.uf_inc * _pnorm   # 官方约定候选
S21_INC = _port2.uf_inc / _port1.uf_inc * _pnorm   # 备选约定
_i0 = int(np.argmin(np.abs(f - F0)))
if abs(S21_REF[_i0]) >= abs(S21_INC[_i0]):
    S21, S21_RESID, S21_CONV = S21_REF, S21_INC, "uf_ref"
else:
    S21, S21_RESID, S21_CONV = S21_INC, S21_REF, "uf_inc"

{two_wave_src}

_pnames = ["vslot_%02d" % _k for _k in range(len(PROBE_X))]
_vd = UI_data(_pnames, SIM_PATH, f)
_vals = np.array([np.asarray(_vd.ui_f_val[_k]) for _k in range(len(_pnames))])
_prior = BETA_SLOT_F0 * f / F0
beta_slot, gamma_load, fit_resid = two_wave_beta_fit(PROBE_X, _vals, _prior,
                                                     span=0.5)

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                 "re_S21_resid", "im_S21_resid"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real,
                     S21[_i].imag, S21_RESID[_i].real, S21_RESID[_i].imag])
with open(os.path.join(SCRIPT_DIR, "slotline_beta.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "beta_slot_rad_m", "gamma_load_mag",
                 "fit_resid_rel", "beta_slot_cf_rad_m", "beta_msl_rad_m",
                 "beta_msl_hj_rad_m"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, beta_slot[_i], gamma_load[_i], fit_resid[_i],
                     BETA_SLOT_F0 * _fi / F0, BETA_MSL[_i], BETA_MSL_F0])
summary = {{
    "ok": True,
    "kind": "msl_slot_transition (Roberts/Knorr)",
    "excite_port": 1,
    "f0_hz": F0, "fc_hz": FC,
    "s_slot_m": S_W, "h_m": H_SUB, "er": ER, "tan_d": TAND,
    "w_msl_m": W_MSL, "x_sh_m": X_SH, "l_stub_m": float(Y_TIP - S_W / 2),
    "x_port_m": X_PORT, "dom_x_m": DOM_X, "dom_y_m": DOM_Y,
    "port_inset_m": float(DOM_X - X_PORT),
    "r_slot_ohm": R_SLOT, "rx_baseline_db": RX_DB,
    "beta_slot_f0": float(beta_slot[_i0]),
    "beta_slot_cf_f0": BETA_SLOT_F0,
    "beta_msl_f0": float(BETA_MSL[_i0]), "beta_msl_hj_f0": BETA_MSL_F0,
    "s11_at_f0": [S11[_i0].real, S11[_i0].imag],
    "s21_at_f0": [S21[_i0].real, S21[_i0].imag],
    "s21_convention": S21_CONV,
    "gamma_load_mag_f0": float(gamma_load[_i0]),
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "summary.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto slotline transition simulation done")
'''


# ─────────────────────────────── 渲染：巴伦 ───────────────────────────────

def render_marchand_balun(params: dict[str, Any],
                          freq_range_ghz: tuple[float, float],
                          mesh_resolution_mm: float = 0.0,
                          nrts: int = 100000,
                          excite_port: int = 1,
                          f0_ghz: float | None = None) -> str:
    """渲染双槽臂 Marchand 巴伦自包含脚本（excite_port∈{{1,2,3}}，#208 单激励）。"""
    if excite_port not in (1, 2, 3):
        raise ValueError(f"excite_port 须为 1/2/3，得到 {excite_port!r}")
    lay = marchand_balun_layout(params, freq_range_ghz, mesh_resolution_mm,
                                f0_ghz)
    tan_d = float(params.get("tan_d", _DESIGN_DEFAULTS["tan_d"]))
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    n_sub = SUBSTRATE_Z_LAYERS + 1
    two_wave_src = inspect.getsource(two_wave_beta_fit)
    rx_db = tap_receive_factor_db(lay.r_slot_ohm, lay.r_slot_ohm)
    src_db = tap_source_factor_db(lay.r_slot_ohm, lay.r_slot_ohm)
    probes_a = ", ".join(repr(float(x)) for x in lay.probe_a_x_m)
    probes_b = ", ".join(repr(float(x)) for x in lay.probe_b_x_m)
    port_len = abs(lay.y_p1_edge_m - lay.y_p1_inner_m)
    return f'''#!/usr/bin/env python3
"""openEMS Marchand balun script (rfauto, auto-generated, excite={excite_port}).

几何/端口/网格口径、极性约定与理论出处见
src/rfauto/adapters/slotline_transitions_template.py 与
src/rfauto/core/slotline_transitions.py 模块 docstring。
运行前置：openEMS Python 绑定需已安装——在 PATH，或经 RFAUTO_OPENEMS_BIN
环境变量指定 bin 目录。
"""
import csv
import json
import os

# openEMS Python 绑定（CSXCAD/openEMS）需已安装并在 PATH；也可用
# RFAUTO_OPENEMS_BIN 环境变量显式指定 bin 目录（未给出时不注入任何路径）。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", "")
if _OE_BIN and os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import LumpedPort, MSLPort, UI_data

F0 = {f0!r}
FC = {fc!r}
ER = {lay.er!r}
TAND = {tan_d!r}
S_W = {lay.s_m!r}
H_SUB = {lay.h_m!r}
W_MSL = {lay.w_msl_m!r}
X_SH = {lay.l_short_m!r}      # 封口臂 λg'/4（槽1 左端 / 槽2 右端）
A1 = {lay.a1_m!r}             # 槽内缘 |y|（中条半宽）
A2 = {lay.a2_m!r}             # 槽外缘 |y|
Y_TIP = {lay.y_stub_tip_m!r}  # 微带开路支节端 y（负）
X_PORT = {lay.x_port_m!r}
DOM_X = {lay.dom_x_m!r}
DOM_Y = {lay.dom_y_m!r}
Z_BOT = {lay.z_bot_m!r}
Z_TOP = {lay.z_top_m!r}
Y_P1E = {lay.y_p1_edge_m!r}   # MSLPort 段起点（+y 侧，出 PML）
Y0 = {lay.y_p1_inner_m!r}     # MSLPort 馈线段内端（传播 −y）
PORT_DX = {lay.port_dx_m!r}
PORT_DZ = {lay.port_dz_m!r}
BASE = {lay.base_m!r}
NEAR = {lay.near_m!r}
R_SLOT = {lay.r_slot_ohm!r}
RX_DB = {rx_db!r}             # 接收抽头基线；SRC_DB 抽头源口发射基线
SRC_DB = {src_db!r}
BETA_SLOT_F0 = {lay.beta_slot_f0!r}
BETA_MSL_F0 = {lay.beta_msl_f0!r}
NRTS = {int(nrts)}
EXCITE_PORT = {int(excite_port)}
PROBE_A = np.array([{probes_a}])   # 臂 1（+x 输出）
PROBE_B = np.array([{probes_b}])   # 臂 2（−x 输出）
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEAM = {METAL_SEAM_OVERLAP!r} * NEAR   # 支节-馈线盒搭接（同金属，不关槽）

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()

def _axis(ax, near_pts, dom_lo, dom_hi):
    for p_ in near_pts:
        mesh.AddLine(ax, p_)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_axis("x", [0.0, W_MSL / 2, -W_MSL / 2, X_SH, -X_SH, X_PORT, -X_PORT,
            X_PORT - PORT_DX / 2, X_PORT + PORT_DX / 2,
            -X_PORT - PORT_DX / 2, -X_PORT + PORT_DX / 2]
      + list(PROBE_A) + list(PROBE_B), -DOM_X, DOM_X)
_axis("y", [0.0, A1, -A1, A2, -A2, Y_TIP, Y_P1E, Y0], -DOM_Y, DOM_Y)
mesh.AddLine("z", np.linspace(0, H_SUB, {n_sub}))
mesh.AddLine("z", np.array([-NEAR, 0.0, NEAR, H_SUB, H_SUB + NEAR,
                            -PORT_DZ / 2, PORT_DZ / 2]))
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", NEAR)
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", BASE)
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：基板；底层五盒（M1/M2 外地、M3 中条、M4/M5 封口桥：M4 桥接槽 2
# 右端（x=X_SH 起）、M5 桥接槽 1 左端——M4/M5 与 M3 在 x=±X_SH 精确共边，
# 该处网格线已钉，PEC 共棱连通）；顶层微带支节 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
gnd = CSX.AddMetal("gnd_slot")
gnd.AddBox((-DOM_X, A2, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)      # M1
gnd.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, -A2, 0.0), priority=10)    # M2
gnd.AddBox((-DOM_X, -A1, 0.0), (DOM_X, A1, 0.0), priority=10)        # M3 中条
gnd.AddBox((X_SH, -A2, 0.0), (DOM_X, -A1, 0.0), priority=10)         # M4 槽2封口
gnd.AddBox((-DOM_X, A1, 0.0), (-X_SH, A2, 0.0), priority=10)         # M5 槽1封口
msl = CSX.AddMetal("msl_top")
# 微带整线自画：从域边（贯通 PML）到开路支节端；MSLPort 段自画盒与之重叠
msl.AddBox((-W_MSL / 2, Y_TIP, H_SUB), (W_MSL / 2, DOM_Y, H_SUB),
           priority=10)

# ── 端口（P1 MSLPort 线基；P2/P3 跨槽抽头 R=Z0；极性约定见模块 docstring）──
_port1 = MSLPort(CSX, port_nr=1, metal_prop=msl,
                 start=np.array([W_MSL / 2, Y_P1E, H_SUB]),
                 stop=np.array([-W_MSL / 2, Y0, 0.0]),
                 prop_dir="y", exc_dir="z",
                 excite=1.0 if EXCITE_PORT == 1 else 0,
                 FeedShift=10 * NEAR, MeasPlaneShift={port_len / 3!r},
                 priority=10)
for _prim in msl.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
_p2_start = np.array([X_PORT - PORT_DX / 2, A1, -PORT_DZ / 2])
_p2_stop = np.array([X_PORT + PORT_DX / 2, A2, PORT_DZ / 2])
_p3_start = np.array([-X_PORT - PORT_DX / 2, -A2, -PORT_DZ / 2])
_p3_stop = np.array([-X_PORT + PORT_DX / 2, -A1, PORT_DZ / 2])
_port2 = LumpedPort(CSX, 2, R_SLOT, _p2_start, _p2_stop, "y",
                    excite=1.0 if EXCITE_PORT == 2 else 0, priority=5)
_port3 = LumpedPort(CSX, 3, R_SLOT, _p3_start, _p3_stop, "y",
                    excite=1.0 if EXCITE_PORT == 3 else 0, priority=5)

# ── β 探针：双臂槽跨压 ──
for _k, _px in enumerate(PROBE_A):
    _vp = CSX.AddProbe("vslot_a_%02d" % _k, p_type=0)
    _vp.AddBox(np.array([_px, A1, 0.0]), np.array([_px, A2, 0.0]))
for _k, _px in enumerate(PROBE_B):
    _vp = CSX.AddProbe("vslot_b_%02d" % _k, p_type=0)
    _vp.AddBox(np.array([_px, -A2, 0.0]), np.array([_px, -A1, 0.0]))

{RUN_MARKER}
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：激励行 S + 互易/隔离 + 双臂双行波 β ──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f)
_port2.CalcPort(SIM_PATH, f)
_port3.CalcPort(SIM_PATH, f)
Z1 = np.abs(_port1.Z_ref)
BETA_MSL = np.real(_port1.beta)
_i0 = int(np.argmin(np.abs(f - F0)))
_pnorm_in = np.sqrt(Z1 / R_SLOT)

def _pick(passive, src_u, label):
    _a = passive.uf_ref / src_u
    _b = passive.uf_inc / src_u
    if abs(_a[_i0]) >= abs(_b[_i0]):
        return _a, _b, label + ":uf_ref"
    return _b, _a, label + ":uf_inc"

if EXCITE_PORT == 1:
    _src = _port1.uf_inc
    S11 = _port1.uf_ref / _src
    S21, S21_RES, S21_CONV = _pick(_port2, _src, "S21")
    S31, S31_RES, S31_CONV = _pick(_port3, _src, "S31")
    S21 = S21 * _pnorm_in
    S31 = S31 * _pnorm_in
    S23 = None
elif EXCITE_PORT == 2:
    _src = _port2.uf_inc
    S22 = _port2.uf_ref / _src            # 抽头基线（-9.5dB 量级，非匹配指标）
    S12 = _port1.uf_ref / _src / _pnorm_in
    S23, S23_RES, S23_CONV = _pick(_port3, _src, "S23")
    S11 = S21 = S31 = None
else:
    _src = _port3.uf_inc
    S33 = _port3.uf_ref / _src
    S13 = _port1.uf_ref / _src / _pnorm_in
    S23, S23_RES, S23_CONV = _pick(_port2, _src, "S23")
    S11 = S21 = S31 = None

{two_wave_src}

def _arm_beta(names):
    _vd = UI_data(names, SIM_PATH, f)
    _v = np.array([np.asarray(_vd.ui_f_val[_k]) for _k in range(len(names))])
    _b, _g, _r = two_wave_beta_fit(PROBE_A if names[0][7] == "a" else PROBE_B,
                                   _v, BETA_SLOT_F0 * f / F0, span=0.5)
    return _b, _g, _r

beta_a, gamma_a, resid_a = _arm_beta(
    ["vslot_a_%02d" % _k for _k in range(len(PROBE_A))])
beta_b, gamma_b, resid_b = _arm_beta(
    ["vslot_b_%02d" % _k for _k in range(len(PROBE_B))])

_rows = {{"S11": S11, "S21": S21, "S31": S31, "S22": S22 if EXCITE_PORT == 2 else None,
          "S12": S12 if EXCITE_PORT == 2 else None,
          "S33": S33 if EXCITE_PORT == 3 else None,
          "S13": S13 if EXCITE_PORT == 3 else None,
          "S23": S23}}
with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    _cols = [k for k, v in _rows.items() if v is not None]
    w_.writerow(["freq_hz"] + ["re_" + c for c in _cols]
                + ["im_" + c for c in _cols])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi] + [v for c in _cols for v in
                             (_rows[c][_i].real, _rows[c][_i].imag)])
with open(os.path.join(SCRIPT_DIR, "slotline_beta.csv"), "w",
          newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "beta_a_rad_m", "beta_b_rad_m",
                 "gamma_a_mag", "gamma_b_mag", "beta_slot_cf_rad_m"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, beta_a[_i], beta_b[_i], gamma_a[_i], gamma_b[_i],
                     BETA_SLOT_F0 * _fi / F0])
summary = {{
    "ok": True,
    "kind": "marchand_balun_dual_slot",
    "excite_port": EXCITE_PORT,
    "f0_hz": F0, "fc_hz": FC,
    "s_slot_m": S_W, "h_m": H_SUB, "er": ER, "tan_d": TAND,
    "w_msl_m": W_MSL, "x_sh_m": X_SH,
    "d_center_m": float(2 * A1 + S_W), "a1_m": A1, "a2_m": A2,
    "x_port_m": X_PORT, "dom_x_m": DOM_X, "dom_y_m": DOM_Y,
    "r_slot_ohm": R_SLOT, "rx_baseline_db": RX_DB, "src_baseline_db": SRC_DB,
    "beta_a_f0": float(beta_a[_i0]), "beta_b_f0": float(beta_b[_i0]),
    "beta_slot_cf_f0": BETA_SLOT_F0,
    "beta_msl_f0": float(BETA_MSL[_i0]), "beta_msl_hj_f0": BETA_MSL_F0,
    "s21_conventions": {{"S21": S21_CONV if EXCITE_PORT == 1 else None,
               "S31": S31_CONV if EXCITE_PORT == 1 else None,
               "S23": S23_CONV if EXCITE_PORT in (2, 3) else None}},
    "gamma_load_a_f0": float(gamma_a[_i0]),
    "gamma_load_b_f0": float(gamma_b[_i0]),
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "summary.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto marchand balun simulation done (excite=%d)" % EXCITE_PORT)
'''


def balun_ideal_baselines_db(r_port_ohm: float, z0_line_ohm: float) -> dict:
    """巴伦各原始读数的理想 DUT 基线（dB，负值；判据门按 raw−baseline 修正）。

    S21/S31（P1 激励，单接收抽头）：RX；S23（抽头源+抽头收）：SRC+RX；
    S12（抽头源+MSL 收）：SRC。R=Z0 时全为 2/3 → 单 −3.52 / 双 −7.04dB。
    """
    rx = tap_receive_factor_db(r_port_ohm, z0_line_ohm)
    src = tap_source_factor_db(r_port_ohm, z0_line_ohm)
    return {"s21_s31_baseline_db": rx, "s23_baseline_db": src + rx,
            "s12_s13_baseline_db": src, "s22_s33_note":
                "抽头自反射 raw≈−9.5dB（R=Z0）系拓扑必然，非匹配指标"}
