"""均匀槽线段·LumpedPort 跨槽近似渲染器（路线 B，openEMS）。

路线定位（定案，两条路线并行验证）：openEMS 无 slotline 端口原语，
路线 A 用 NGSolve 模场喂 WaveguidePort（自研端口，
`slotline_template.py`，只读复用其几何口径）；本路线用**官方 LumpedPort
跨槽集总馈**（refs §8 AddLumpedPort 范式、§11.1 CPS 同法）——不需要模式
文件，代价是集总近似失配（|S11| 如实记录）。HFSS 波端口仲裁基准见
`scripts/hfss_slotline_arbitration.py`。

几何（layout 单一事实源 ``slotline_lumped_layout``，米；与路线 A 逐键同口径）：
- 传播沿 x；金属零厚面 z=h，槽居中 |y|≤w/2；基板 z∈[0,h]（εr）铺满域；
  上下空气 z∈[−z_bot, h+z_top]；侧界/z 界 MUR（无地开放槽线）、x 轴 PML_8；
- **金属/基板/槽贯通整个域直入 PML**（路线 A 同款：PML 端接槽线=匹配，
  避免"金属止于端口"的开口边辐射把泄漏算进 S21）；
- 两端 LumpedPort 跨槽桥接于 x=±L/2（线两端参考面，与 HFSS 端口面/路线 A
  测量面同距 L）：盒 x∈[xp−NEAR/2, xp+NEAR/2]、y∈[−w/2, w/2]（exc_dir='y'，
  电压=槽电压）、z∈[h−NEAR/2, h+NEAR/2]（对称跨金属面，u 探针恰在 z=h）；
  盒三向边全部入网（#198/#174 零体积激励陷阱）；R=线阻抗档（闭式 Z0 或
  HFSS Zpv，调用方注入）；port1 激励、port2 R 端接；
- 端口到 PML 净距 PORT_INSET=16·BASE（PML_8≈8·BASE，sma_launcher H4 教训）；
- β 独立提取：槽跨压探针 N 站均布 [−L/4,+L/4]（=λ'/2 一个驻波周期，端口
  2 残余失配的相位涟漪整周期平均掉），逐频沿 x 解缠后线性拟合相位斜率。

S 参数口径（#250 单激励带载比值）：CalcPort 参考=R；R=线 Z0 档时端接=匹配，
带载比值即线基真波比值，再由 `openems_templates.renorm_engine_s_to_ref`
（loaded→line basis→skrf renormalize）统一到 50Ω 对拍口径；两口全同+互易
→ 单激励对称装配 S=[[S11,S21],[S21,S11]]（假设显式记录）。S21 取 port2 的
uf_ref/uf_inc 中幅值大者（匹配端接下恰一者≡0，另一者=到达波；哪一者非零
取决于 openEMS LumpedPort 电流符号约定——按幅值判读并记录约定）。

离线审计（#212）：exec 脚本头（FDTD.Run 之前）→ CSXCAD 实测金属原语 DC 隔离
（槽真断开）、LumpedPort 盒三向非零且边在网格线上、探针数/位置、网格含槽缘
与基板界面与端口盒边。

运行前置：openEMS Python 绑定（CSXCAD/openEMS）需已安装——在 PATH，
或经 RFAUTO_OPENEMS_BIN 环境变量指定 bin 目录（渲染脚本不注入固定安装路径）。
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from typing import Any

C0 = 299792458.0
N_PROBE_STATIONS = 9          # 沿线槽跨压探针站数（路线 A 同）
SUBSTRATE_Z_LAYERS = 6        # 基板 z 网格层数
PORT_INSET_BASE = 16.0        # 端口→PML 边界净距（×BASE，须 > PML_8≈8·BASE）
RUN_MARKER = "# ── 求解 ──"    # 离线审计 exec 截断标记（FDTD.Run 之前）


@dataclass(frozen=True)
class SlotlineLumpedLayout:
    """槽线 LumpedPort 段几何/端口/探针布局（米）。"""

    w_m: float
    h_m: float
    er: float
    y_half_m: float
    z_bot_m: float
    z_top_m: float
    line_len_m: float
    dom_x_m: float          # 半长（= L/2 + PORT_INSET）
    x_port1_m: float        # = −L/2
    x_port2_m: float        # = +L/2
    probe_x_m: tuple[float, ...]
    base_m: float
    near_m: float
    port_inset_m: float
    port_dx_m: float        # 端口盒 x 厚（=NEAR）
    port_dz_m: float        # 端口盒 z 厚（=NEAR，对称跨 z=h）


def slotline_lumped_layout(params: dict[str, Any],
                           freq_range_ghz: tuple[float, float],
                           mesh_resolution_mm: float = 0.0) -> SlotlineLumpedLayout:
    """几何/端口布局单一事实源（mm 入参 → 米）。缺省=路线 A 设计点。"""
    w = float(params.get("w_mm", 1.0)) * 1e-3
    h = float(params.get("h_mm", 1.524)) * 1e-3
    er = float(params.get("er", 3.66))
    line_len = float(params.get("line_len_mm", 93.4624)) * 1e-3
    y_half = float(params.get("y_half_mm", 60.0)) * 1e-3
    z_bot = float(params.get("z_bot_mm", 30.0)) * 1e-3
    z_top = float(params.get("z_top_mm", 30.0)) * 1e-3
    for name, v in (("w_mm", w), ("h_mm", h), ("line_len_mm", line_len),
                    ("y_half_mm", y_half), ("z_bot_mm", z_bot), ("z_top_mm", z_top)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"slotline_lumped_layout: {name} 必须为正有限，得到 {v!r}")
    if w >= 2 * y_half:
        raise ValueError("slotline_lumped_layout: 槽宽必须小于域半宽两倍")
    if not (1.0 < float(er) < 20.0):
        raise ValueError(f"slotline_lumped_layout: er={er!r} 非物理")
    f_max = max(float(freq_range_ghz[0]), float(freq_range_ghz[1])) * 1e9
    base = (C0 / (f_max * math.sqrt(er)) / 50.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if h < 2 * near:
        # 端口盒 z∈[h−NEAR/2, h+NEAR/2] 需完整落在基板上半层内侧以上
        raise ValueError("slotline_lumped_layout: 基板过薄，端口盒 z 厚 NEAR 超过 h/2")
    port_inset = PORT_INSET_BASE * base
    dom_x = line_len / 2.0 + port_inset
    n = N_PROBE_STATIONS
    probes = tuple(-line_len / 4.0 + k * line_len / (2.0 * (n - 1)) for k in range(n))
    return SlotlineLumpedLayout(
        w_m=w, h_m=h, er=er, y_half_m=y_half, z_bot_m=z_bot, z_top_m=z_top,
        line_len_m=line_len, dom_x_m=dom_x, x_port1_m=-line_len / 2.0,
        x_port2_m=line_len / 2.0, probe_x_m=probes, base_m=base, near_m=near,
        port_inset_m=port_inset, port_dx_m=near, port_dz_m=near)


def render_slotline_lumped_script(params: dict[str, Any],
                                  freq_range_ghz: tuple[float, float],
                                  r_port_ohm: float,
                                  mesh_resolution_mm: float = 0.0,
                                  nrts: int = 100000,
                                  tan_d: float = 0.0037,
                                  beta_ref_rad_m: float | None = None,
                                  excite_port: int = 1) -> str:
    """渲染自包含 openEMS 脚本（port1 激励单跑：S11/S21 带载比值 + 探针 β(f)）。

    r_port_ohm：两端 LumpedPort R（=CalcPort 参考阻抗），调用方按档注入
    （闭式 Z0 / HFSS Zpv）；beta_ref_rad_m 仅写进 summary 作对照。
    """
    lay = slotline_lumped_layout(params, freq_range_ghz, mesh_resolution_mm)
    if excite_port not in (1, 2):
        raise ValueError(f"excite_port 须为 1/2，得到 {excite_port!r}")
    r_port = float(r_port_ohm)
    if not (math.isfinite(r_port) and r_port > 0):
        raise ValueError(f"r_port_ohm 必须为正有限，得到 {r_port_ohm!r}")
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    n_sub = SUBSTRATE_Z_LAYERS + 1
    probe_xs = ", ".join(repr(float(x)) for x in lay.probe_x_m)
    two_wave_src = inspect.getsource(two_wave_beta_fit)   # 单源注入（脚本自包含）

    return f'''#!/usr/bin/env python3
"""openEMS slotline route-B script (rfauto, auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/slotline_lumped_template.py 模块 docstring。
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
from openEMS.ports import LumpedPort, UI_data

F0 = {f0!r}
FC = {fc!r}
ER = {lay.er!r}
TAND = {tan_d!r}
W = {lay.w_m!r}
H_SUB = {lay.h_m!r}
Y_HALF = {lay.y_half_m!r}
Z_BOT = {lay.z_bot_m!r}
Z_TOP = {lay.z_top_m!r}
BASE = {lay.base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {lay.near_m!r}   # 近槽/近端口 = base/4
R_PORT = {r_port!r}     # LumpedPort R = 线阻抗档（CalcPort 参考同值）
NRTS = {int(nrts)}
EXCITE_PORT = {int(excite_port)}
BETA_REF = {beta_ref_rad_m if beta_ref_rad_m is not None else "None"}
LINE_LEN = {lay.line_len_m!r}
X_P1 = {lay.x_port1_m!r}
X_P2 = {lay.x_port2_m!r}
DOM_LO = {-lay.dom_x_m!r}
DOM_HI = {lay.dom_x_m!r}
PORT_DX = {lay.port_dx_m!r}
PORT_DZ = {lay.port_dz_m!r}
PROBE_X = np.array([{probe_xs}])
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 仿真环境（官方方法学：不设 EndCriteria，默认能量判据）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 端口轴 x PML_8（槽线直入 PML=匹配端接）；无地开放槽线：y/z 全 MUR
FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()

def _axis(ax, near_pts, dom_lo, dom_hi):
    for p_ in near_pts:
        mesh.AddLine(ax, p_)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

# 端口盒三向边全部入网（#198；零体积激励陷阱 #174）
_PORT_X_EDGES = [X_P1 - PORT_DX / 2, X_P1 + PORT_DX / 2, X_P2 - PORT_DX / 2, X_P2 + PORT_DX / 2]
_PORT_Z_EDGES = [H_SUB - PORT_DZ / 2, H_SUB + PORT_DZ / 2]
_axis("x", [X_P1, X_P2] + _PORT_X_EDGES + list(PROBE_X), DOM_LO, DOM_HI)
_axis("y", [-W / 2, 0.0, W / 2], -Y_HALF, Y_HALF)
mesh.AddLine("z", np.linspace(0, H_SUB, {n_sub}))   # 基板 6 层
mesh.AddLine("z", np.array([-NEAR, 0.0, H_SUB, H_SUB + NEAR] + _PORT_Z_EDGES))
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", NEAR)
mesh.AddLine("z", np.array([-Z_BOT, H_SUB + Z_TOP]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：基板铺满域 + 金属面双盒（槽 |y|<W/2 贯通至两端边界直入 PML）──
sub = CSX.AddMaterial("substrate", epsilon=ER, kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((DOM_LO, -Y_HALF, 0.0), (DOM_HI, Y_HALF, H_SUB), priority=0)
sl_metal = CSX.AddMetal("slot_metal")
sl_metal.AddBox((DOM_LO, -Y_HALF, H_SUB), (DOM_HI, -W / 2, H_SUB), priority=10)
sl_metal.AddBox((DOM_LO, W / 2, H_SUB), (DOM_HI, Y_HALF, H_SUB), priority=10)

# ── 端口：LumpedPort 跨槽桥接（官方 AddLumpedPort 范式；盒对称跨 z=h）──
# start→stop 沿 +y（exc_dir='y'）：电压=槽电压（u 探针在盒心 z=h）；
# R 对槽两缘金属桥接；port1 激励、port2 R 端接（+探针）
_P1_START = np.array([X_P1 - PORT_DX / 2, -W / 2, H_SUB - PORT_DZ / 2])
_P1_STOP = np.array([X_P1 + PORT_DX / 2, W / 2, H_SUB + PORT_DZ / 2])
_P2_START = np.array([X_P2 - PORT_DX / 2, -W / 2, H_SUB - PORT_DZ / 2])
_P2_STOP = np.array([X_P2 + PORT_DX / 2, W / 2, H_SUB + PORT_DZ / 2])
_port1 = LumpedPort(CSX, 1, R_PORT, _P1_START, _P1_STOP, "y",
                    excite=1.0 if EXCITE_PORT == 1 else 0, priority=5)
_port2 = LumpedPort(CSX, 2, R_PORT, _P2_START, _P2_STOP, "y",
                    excite=1.0 if EXCITE_PORT == 2 else 0, priority=5)

# ── β 独立提取探针：槽跨压（p_type=0，跨 |y|≤W/2 @z=h）N 站沿线均布 ──
for _k, _px in enumerate(PROBE_X):
    _vp = CSX.AddProbe("vslot_%02d" % _k, p_type=0)
    _vp.AddBox(np.array([_px, -W / 2, H_SUB]), np.array([_px, W / 2, H_SUB]))

{RUN_MARKER}
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：带载比值 S（CalcPort 参考=R）+ 探针 β(f) ──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f)
_port2.CalcPort(SIM_PATH, f)
_exc = _port1 if EXCITE_PORT == 1 else _port2
_oth = _port2 if EXCITE_PORT == 1 else _port1
_SREF = _exc.uf_inc
S11 = _exc.uf_ref / _SREF
S21_REF = _oth.uf_ref / _SREF      # 官方约定候选：到达波=被动口 uf_ref
S21_INC = _oth.uf_inc / _SREF      # 备选约定：到达波=被动口 uf_inc

def _idx_f0(fv):
    return int(np.argmin(np.abs(np.asarray(fv) - F0)))

_i0 = _idx_f0(f)
# 匹配端接下二者恰一者≈0：按 f0 幅值取到达波，另一者=端接残余（记录）
if abs(S21_REF[_i0]) >= abs(S21_INC[_i0]):
    S21, S21_RESID, S21_CONV = S21_REF, S21_INC, "uf_ref"
else:
    S21, S21_RESID, S21_CONV = S21_INC, S21_REF, "uf_inc"

# 探针槽跨压 → β(f)：主口径=双行波模型拟合（two_wave_beta_fit，模块单源注入；
# 端接失配下线性相位斜率有偏 ≈−|Γ|·50%，只作诊断列）
{two_wave_src}

_pnames = ["vslot_%02d" % _k for _k in range(len(PROBE_X))]
_vd = UI_data(_pnames, SIM_PATH, f)
_vals = np.array([np.asarray(_vd.ui_f_val[_k]) for _k in range(len(_pnames))])  # (n_probe, n_f)
_phases = np.unwrap(np.angle(_vals), axis=0)
_amps = np.abs(_vals)
beta_slope = -np.polyfit(PROBE_X, _phases, 1)[0]     # 诊断：线性斜率法 (n_f,)
_prior = (BETA_REF * f / F0) if BETA_REF else beta_slope   # β∝f 一阶先验（±50% 窗）
beta_probe, gamma_load, fit_resid = two_wave_beta_fit(PROBE_X, _vals, _prior, span=0.5)
swr_amp = _amps.max(axis=0) / np.maximum(_amps.min(axis=0), 1e-300)

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21", "re_S21_resid", "im_S21_resid"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real, S21[_i].imag,
                     S21_RESID[_i].real, S21_RESID[_i].imag])
with open(os.path.join(SCRIPT_DIR, "slotline_beta.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "beta_probe_rad_m", "beta_slope_rad_m", "gamma_load_mag",
                 "fit_resid_rel", "beta_ref_rad_m", "swr_amp"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, beta_probe[_i], beta_slope[_i], gamma_load[_i], fit_resid[_i],
                     BETA_REF if BETA_REF else "", swr_amp[_i]])
summary = {{
    "ok": True,
    "route": "B (openEMS LumpedPort across slot)",
    "excite_port": EXCITE_PORT,
    "f0_hz": F0, "fc_hz": FC,
    "w_m": W, "h_m": H_SUB, "er": ER, "tan_d": TAND,
    "line_len_m": float(X_P2 - X_P1),
    "port_inset_m": float(X_P1 - DOM_LO),
    "r_port_ohm": R_PORT,
    "beta_ref_rad_m": BETA_REF,
    "s11_at_f0": [S11[_i0].real, S11[_i0].imag],
    "s21_at_f0": [S21[_i0].real, S21[_i0].imag],
    "s21_resid_at_f0": [S21_RESID[_i0].real, S21_RESID[_i0].imag],
    "s21_convention": S21_CONV,
    "beta_probe_at_f0": float(beta_probe[_i0]),
    "beta_slope_at_f0": float(beta_slope[_i0]),
    "gamma_load_mag_at_f0": float(gamma_load[_i0]),
    "fit_resid_rel_at_f0": float(fit_resid[_i0]),
    "swr_amp_at_f0": float(swr_amp[_i0]),
    "nrts": NRTS,
    "n_probes": int(len(PROBE_X)),
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "slotline_summary.json"), "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto slotline route-B simulation done")
'''


def beta_from_probe_phases(probe_x_m: Any, v_probe: Any) -> Any:
    """【诊断量，非主口径】槽跨压探针复电压 (n_probe, n_f) → 线性相位斜率 β(f)。

    合成自检实证（test_slotline_route_b）：端接失配 |Γ|=0.2 时该法 β 偏 ≈−10%——
    驻波涟漪 Γ·sin(2βx') 在整周期上的线性回归斜率并不为零（∫x·sin 不为零）。
    主口径用 `two_wave_beta_fit`；本函数只作对照列写进 CSV。
    """
    import numpy as np

    x = np.asarray(probe_x_m, dtype=float)
    v = np.asarray(v_probe, dtype=complex)
    if v.ndim != 2 or v.shape[0] != len(x):
        raise ValueError(f"v_probe 须为 (n_probe={len(x)}, n_f)，得 {v.shape}")
    phases = np.unwrap(np.angle(v), axis=0)
    return -np.polyfit(x, phases, 1)[0]


def two_wave_beta_fit(probe_x_m, v_probe, beta_prior, span=0.5, n_grid=1201):
    """双行波模型 V(x)=A·e^{-jβx}+B·e^{+jβx} 拟合 → (β(f), |B/A|(f), 相对残差(f))。

    β 在 [(1−span),(1+span)]×prior 网格上扫描（每个 β 一次 2 列线性 LS，全频
    向量化），取残差最小点再三点抛物线精化；|B/A|=端接（port2）残余失配幅值
    诊断。数值稳健性：探针跨度 λ'/2 使两列近正交；探针间距 ≪ 2π/β 无混叠。
    渲染脚本通过 inspect.getsource 注入本函数（单源、自包含），依赖仅 numpy。
    """
    import numpy as np

    x = np.asarray(probe_x_m, dtype=float)
    v = np.asarray(v_probe, dtype=complex)
    if v.ndim != 2 or v.shape[0] != len(x) or len(x) < 3:
        raise ValueError("v_probe 须为 (n_probe>=3, n_f)")
    prior = np.broadcast_to(np.asarray(beta_prior, dtype=float), (v.shape[1],))
    b_lo = float(np.min(prior)) * (1.0 - span)
    b_hi = float(np.max(prior)) * (1.0 + span)
    grid = np.linspace(b_lo, b_hi, int(n_grid))
    n_f = v.shape[1]
    resid = np.empty((len(grid), n_f))
    coef = np.empty((len(grid), 2, n_f), dtype=complex)
    vnorm = np.maximum(np.sum(np.abs(v) ** 2, axis=0), 1e-300)
    for k, b in enumerate(grid):
        m = np.stack([np.exp(-1j * b * x), np.exp(1j * b * x)], axis=1)   # (n_probe, 2)
        c = np.linalg.pinv(m) @ v                                           # (2, n_f)
        r = v - m @ c
        resid[k] = np.sum(np.abs(r) ** 2, axis=0) / vnorm
        coef[k] = c
    i_min = np.argmin(resid, axis=0)
    beta = grid[i_min].astype(float)
    # 三点抛物线精化（内点）
    for j in range(n_f):
        i = int(i_min[j])
        if 0 < i < len(grid) - 1:
            y0, y1, y2 = resid[i - 1, j], resid[i, j], resid[i + 1, j]
            den = y0 - 2.0 * y1 + y2
            if den > 0:
                beta[j] = grid[i] + 0.5 * (y0 - y2) / den * (grid[1] - grid[0])
    a = coef[i_min, 0, np.arange(n_f)]
    bcoef = coef[i_min, 1, np.arange(n_f)]
    gamma_mag = np.abs(bcoef) / np.maximum(np.abs(a), 1e-300)
    return beta, gamma_mag, resid[i_min, np.arange(n_f)]


def assemble_route_b_sparams(s11_raw: Any, s21_raw: Any, r_port_ohm: float,
                             z_out_ohm: float = 50.0) -> Any:
    """单激励带载比值 → 对称装配 2×2 → 50Ω 基（#250，helper 复用）。

    两口全同 + 互易 → S=[[S11,S21],[S21,S11]]（假设显式）；CalcPort 参考=R=
    端接=假设线 Z0 → `renorm_engine_s_to_ref(z_line=R, z_ref=R)` 的 loaded→
    line 一步恒等，再 skrf renormalize 到 z_out。返回 (N,2,2)。
    """
    import numpy as np

    from rfauto.adapters.openems_templates import renorm_engine_s_to_ref

    s11 = np.asarray(s11_raw, dtype=complex)
    s21 = np.asarray(s21_raw, dtype=complex)
    if s11.shape != s21.shape or s11.ndim != 1:
        raise ValueError("s11_raw/s21_raw 须为同长一维数组")
    s = np.empty((len(s11), 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 1] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21
    r = float(r_port_ohm)
    return renorm_engine_s_to_ref(s, z_line_ohm=r, z_ref_ohm=r,
                                  z_out_ohm=[float(z_out_ohm)] * 2)


def tap_network_sparams(z0, r_port, gamma, line_len_m):
    """"PML 匹配线 + 两处并联 LumpedPort 抽头"解析模型 → (S11_raw, S21_raw)（带载比值口径）。

    拓扑（本模板真机首跑实证，r_closed：|S11|=−6.6dB/|S21|=−7.4dB 与本模型 R=Z0、
    βL=2π 时 S11=−1/2、S21=+1/2 一致）：无限长线 Z0（两端 PML=匹配），抽头 1（x=0）
    =Thevenin 源 Vs 串 R（openEMS LumpedPort：uf_inc=(u+R·i)/2=Vs/2），抽头 2（x=L）
    =并联 R。推导：Z_end=R∥Z0，Z_right=Z0·(Z_end+Z0·th)/(Z0+Z_end·th)（th=tanh(γL)），
    Z_L1=Z0∥Z_right，S11=(Z_L1−R)/(Z_L1+R)；Γ_end=(Z_end−Z0)/(Z_end+Z0)，
    S21=2·u2/Vs=2·Z_L1/(R+Z_L1)·e^{−γL}(1+Γ_end)/(1+Γ_end·e^{−2γL})。
    z0/r_port 实或复标量或 (N,) 数组；gamma=α+jβ (N,)（rad/m）。忽略抽头盒寄生电抗与
    辐射——反演 Z0 时只取 Re，caveat 见 fit_z0_from_tap_s11。
    """
    import numpy as np

    z0 = np.asarray(z0, dtype=complex)
    r = np.asarray(r_port, dtype=complex)
    g = np.asarray(gamma, dtype=complex)
    gl = g * float(line_len_m)
    th = np.tanh(gl)
    z_end = r * z0 / (r + z0)
    z_right = z0 * (z_end + z0 * th) / (z0 + z_end * th)
    z_l1 = z0 * z_right / (z0 + z_right)
    s11 = (z_l1 - r) / (z_l1 + r)
    g_end = (z_end - z0) / (z_end + z0)
    e1 = np.exp(-gl)
    s21 = 2.0 * z_l1 / (r + z_l1) * e1 * (1.0 + g_end) / (1.0 + g_end * e1 * e1)
    return s11, s21


def fit_z0_from_tap_s11(s11_raw, r_port, gamma, line_len_m, z0_lo=20.0, z0_hi=300.0,
                        n_grid=2801):
    """抽头模型反演：逐频在实 Z0 网格上最小化 |S11_raw − S11_model(Z0)| → Z0_tap(f)。

    返回 (z0_fit (N,), resid (N,))。caveat：模型无抽头盒寄生电抗/辐射负载，实测
    Γ 的虚部失配全部进 resid；Z0_tap 为"抽头视在线阻抗"，只作 HFSS Zpv/闭式的
    第三方旁证，不作生产口径。
    """
    import numpy as np

    s11 = np.asarray(s11_raw, dtype=complex)
    g = np.asarray(gamma, dtype=complex)
    grid = np.linspace(float(z0_lo), float(z0_hi), int(n_grid))
    best = np.empty(len(s11))
    resid = np.empty(len(s11))
    for k in range(len(s11)):
        s_model, _ = tap_network_sparams(grid, r_port, np.full(len(grid), g[k]), line_len_m)
        err = np.abs(s_model - s11[k])
        i = int(np.argmin(err))
        best[k] = grid[i]
        resid[k] = err[i]
    return best, resid
