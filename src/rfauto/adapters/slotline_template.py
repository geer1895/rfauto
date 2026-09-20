"""均匀槽线段附加模板渲染器（路线 A：NGSolve 模式文件 → openEMS WaveguidePort）。

附加模板口径（本波 openems_templates.py 归 wstep 子代理独占）：独立渲染模块 +
独立测试，**不注册** TEMPLATE_META/EXPECTED_TEMPLATES/TEMPLATE_NOMINAL（注册
四件套另行登记）；闭式用 core/slotline.py 普通函数（不加 @register_calculator，
另行登记）。

几何（layout 单一事实源 ``slotline_layout``，米）：
- 传播沿 x；金属零厚面 z=h，槽居中 |y|≤w/2 贯通全域至两端边界（端口面在
  域边界侧，馈槽直达边界=MSL 馈线到板边同口径）；
- 基板 z∈[0,h]（εr）铺满域、上下空气 z∈[−z_bot,h+z_top]；侧界 MUR、z 界 MUR
  （无地开放槽线）、端口轴 x PML_8；
- 两端 WaveguidePort（E/H 模式文件喂入，文件模式必需 SetPropagationDir）：
  激励面 X_EXC、U/I 模式匹配探针面 X_MEAS；激励面内移 PORT_INSET=16·BASE
  （PML_8≈8·BASE≈9.1mm，激励面须出 PML——sma_launcher H4 同族教训）；
- β 独立提取（不依赖端口 kc 假设）：槽跨压探针（p_type=0 跨 |y|≤w/2 @z=h）
  N_PROBE 站沿线均布 [−L/4,+L/4]，逐频相位斜率 → β_probe(f)。

网格：官方方法学基线（docs §0）base=λ_sub/50@F_MAX、近槽/近端口 NEAR=base/4、
基板 z 6 层、#152 最小间距守卫。

离线审计测试（#212）：exec 脚本头（FDTD.Run 之前）→ CSXCAD 实测金属原语
（DC 两组隔离=槽真断开）、端口/探针属性、网格线含槽缘与基板界面。

运行前置：openEMS Python 绑定（CSXCAD/openEMS）需已安装——在 PATH，
或经 RFAUTO_OPENEMS_BIN 环境变量指定 bin 目录（渲染脚本不注入固定安装路径）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

C0 = 299792458.0
N_PROBE_STATIONS = 9          # 沿线槽跨压探针站数
SUBSTRATE_Z_LAYERS = 6        # 基板 z 网格层数（官方 substrate_cells=4 起步，槽线取 6）
PORT_INSET_BASE = 16.0        # 激励面内移（×BASE，须 > PML_8 厚度 ≈8·BASE）
PORT_LEN_NEAR = 10.0          # 激励面→测量面距离（×NEAR）
PORT_BOX_INSET_BASE = 2.0     # 端口盒 y/z 各内移（×BASE）：出 MUR 边界胞层。
# 真机实证（pt1 首跑）：盒跨满截面时触发 "Excitation inside the
# Mur-ABC"，MUR 被延迟到激励结束（29534 步）才开启，开启瞬态激起悬浮双金属
# 零模 → 探针信号自 ~11ns 起纯线性 DC 漂移（15ns 内涨到信号 10 倍）。内缩
# 2·BASE 后盒缘离开边界胞层（该处模场 ≈0，无激励损失；U/I 模式探针同步内缩
# 保持与激励同一权重口径）。


@dataclass(frozen=True)
class SlotlineLayout:
    """槽线段几何/端口/探针布局（米；由 ``slotline_layout`` 计算）。"""

    w_m: float
    h_m: float
    er: float
    y_half_m: float
    z_bot_m: float
    z_top_m: float
    dom_x_m: float          # 半长
    x_exc1_m: float
    x_meas1_m: float
    x_meas2_m: float
    x_exc2_m: float
    probe_x_m: tuple[float, ...]
    base_m: float
    near_m: float
    port_inset_m: float
    port_len_m: float
    box_inset_m: float      # 端口盒 y/z 内移（出 MUR 边界胞层，见常量注）


def slotline_layout(params: dict[str, Any], freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0) -> SlotlineLayout:
    """几何/端口布局单一事实源（mm 入参 → 米）。

    line_len_mm = 两测量面间距（≈1λ' 槽波长设计值，由调用方按闭式精算）；
    y_half/z_bot/z_top 缺省取 NGSolve 截面默认（±60/−30/+30mm）——模式文件
    网格与 FDTD 域截面必须逐字节一致（文件出界夹边）。
    """
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
            raise ValueError(f"slotline_layout: {name} 必须为正有限，得到 {v!r}")
    if w >= 2 * y_half:
        raise ValueError("slotline_layout: 槽宽必须小于域半宽两倍")
    f_max = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9 \
        + (freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    base = (C0 / (f_max * math.sqrt(er)) / 50.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    port_inset = PORT_INSET_BASE * base
    port_len = PORT_LEN_NEAR * near
    dom_x = line_len / 2.0 + port_len + port_inset
    x_exc1 = -dom_x + port_inset
    x_meas1 = x_exc1 + port_len
    x_meas2 = x_meas1 + line_len
    x_exc2 = x_meas2 + port_len
    n = N_PROBE_STATIONS
    probes = tuple(-line_len / 4.0 + k * line_len / (2.0 * (n - 1)) for k in range(n))
    return SlotlineLayout(w_m=w, h_m=h, er=er, y_half_m=y_half, z_bot_m=z_bot,
                          z_top_m=z_top, dom_x_m=dom_x, x_exc1_m=x_exc1,
                          x_meas1_m=x_meas1, x_meas2_m=x_meas2, x_exc2_m=x_exc2,
                          probe_x_m=probes, base_m=base, near_m=near,
                          port_inset_m=port_inset, port_len_m=port_len,
                          box_inset_m=PORT_BOX_INSET_BASE * base)


def render_slotline_script(params: dict[str, Any],
                           freq_range_ghz: tuple[float, float],
                           e_mode_file: str, h_mode_file: str,
                           kc: complex, z_mode_ohm: float,
                           mesh_resolution_mm: float = 0.0,
                           excite_port: int = 1, nrts: int = 100000,
                           tan_d: float = 0.0037,
                           beta_ref_rad_m: float | None = None) -> str:
    """渲染自包含 openEMS 仿真脚本（端口 1 激励单跑出 S11/S21 + 探针 β(f)）。

    e_mode_file/h_mode_file：NGSolve 模式文件绝对路径（E=横向 E、H=Z_mode·H）；
    kc：f0 反解（SI 1/m，可纯虚）；z_mode_ohm：CalcPort 的 ZL/参考阻抗；
    beta_ref_rad_m：闭式 β（仅写进 meta 作对照，不参与引擎）。
    """
    lay = slotline_layout(params, freq_range_ghz, mesh_resolution_mm)
    if excite_port not in (1, 2):
        raise ValueError(f"excite_port 须为 1/2，得到 {excite_port!r}")
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = (freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    w = lay.w_m
    h = lay.h_m
    yh = lay.y_half_m
    zb, zt = lay.z_bot_m, lay.z_top_m
    n_sub = SUBSTRATE_Z_LAYERS + 1
    probe_xs = ", ".join(repr(float(x)) for x in lay.probe_x_m)
    kc_txt = f"complex({kc.real!r}, {kc.imag!r})"

    return f'''#!/usr/bin/env python3
"""openEMS slotline route-A script (rfauto, auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/slotline_template.py 模块 docstring。
模式文件路径见下方 E_FILE/H_FILE 字面量。
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
from openEMS.ports import WaveguidePort, UI_data

F0 = {f0!r}
FC = {fc!r}
ER = {lay.er!r}
TAND = {tan_d!r}
W = {w!r}
H_SUB = {h!r}
Y_HALF = {yh!r}
Z_BOT = {zb!r}
Z_TOP = {zt!r}
BASE = {lay.base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {lay.near_m!r}   # 近槽/近端口 = base/4
E_FILE = {e_mode_file!r}
H_FILE = {h_mode_file!r}
KC = {kc_txt}            # f0 反解（SI 1/m，可纯虚；带内色散假设=路线 A 已知局限）
Z_MODE = {float(z_mode_ohm)!r}   # NGSolve 功率-电压模阻抗（CalcPort ZL=参考阻抗）
NRTS = {int(nrts)}
EXCITE_PORT = {int(excite_port)}
BETA_REF = {beta_ref_rad_m if beta_ref_rad_m is not None else "None"}
X_EXC1 = {lay.x_exc1_m!r}
X_MEAS1 = {lay.x_meas1_m!r}
X_MEAS2 = {lay.x_meas2_m!r}
X_EXC2 = {lay.x_exc2_m!r}
DOM_LO = X_EXC1 - {lay.port_inset_m!r}   # 域 x 下端（= −DOM_X）
DOM_HI = X_EXC2 + {lay.port_inset_m!r}   # 域 x 上端（= +DOM_X）
PROBE_X = np.array([{probe_xs}])
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── 仿真环境（官方方法学：不设 EndCriteria，默认能量判据）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 端口轴 x PML_8；无地开放槽线：y/z 全 MUR
FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()

def _axis(ax, near_pts, dom_lo, dom_hi):
    for p_ in near_pts:
        mesh.AddLine(ax, p_)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_axis("x", [X_EXC1, X_MEAS1] + list(PROBE_X) + [X_MEAS2, X_EXC2], DOM_LO, DOM_HI)
_axis("y", [-W / 2, 0.0, W / 2], -Y_HALF, Y_HALF)
mesh.AddLine("z", np.linspace(0, H_SUB, {n_sub}))   # 基板 6 层（槽线加密档）
mesh.AddLine("z", np.array([-NEAR, 0.0, H_SUB, H_SUB + NEAR]))
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

# ── 几何：基板铺满域 + 金属面双盒（槽 |y|<W/2 贯通至两端边界）──
sub = CSX.AddMaterial("substrate", epsilon=ER, kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((DOM_LO, -Y_HALF, 0.0), (DOM_HI, Y_HALF, H_SUB), priority=0)
sl_metal = CSX.AddMetal("slot_metal")
sl_metal.AddBox((DOM_LO, -Y_HALF, H_SUB), (DOM_HI, -W / 2, H_SUB), priority=10)
sl_metal.AddBox((DOM_LO, W / 2, H_SUB), (DOM_HI, Y_HALF, H_SUB), priority=10)

# ── 端口：WaveguidePort 文件模式（E/H 由 NGSolve 模场喂入）──
# 盒 y/z 各内缩 BOX_INSET：出 MUR 边界胞层（防 "Excitation inside Mur-ABC"
# 延迟开关瞬态激起悬浮零模 → DC 漂移，pt1 首跑实证）；该处模场 ≈0 无损失
BOX_INSET = {lay.box_inset_m!r}
_P1_START = np.array([X_EXC1, -Y_HALF + BOX_INSET, -Z_BOT + BOX_INSET])
_P1_STOP = np.array([X_MEAS1, Y_HALF - BOX_INSET, H_SUB + Z_TOP - BOX_INSET])
_P2_START = np.array([X_EXC2, -Y_HALF + BOX_INSET, -Z_BOT + BOX_INSET])
_P2_STOP = np.array([X_MEAS2, Y_HALF - BOX_INSET, H_SUB + Z_TOP - BOX_INSET])
_port1 = WaveguidePort(CSX, 1, _P1_START, _P1_STOP, "x", None, None, KC,
                       excite=1 if EXCITE_PORT == 1 else 0, excite_type=0,
                       E_WG_file=E_FILE, H_WG_file=H_FILE, local_origin=None,
                       priority=10)
_port2 = WaveguidePort(CSX, 2, _P2_START, _P2_STOP, "x", None, None, KC,
                       excite=1 if EXCITE_PORT == 2 else 0, excite_type=0,
                       E_WG_file=E_FILE, H_WG_file=H_FILE, local_origin=None,
                       priority=10)

# ── β 独立提取探针：槽跨压（p_type=0，跨 |y|≤W/2 @z=h）N 站沿线均布 ──
for _k, _px in enumerate(PROBE_X):
    _vp = CSX.AddProbe("vslot_%02d" % _k, p_type=0)
    _vp.AddBox(np.array([_px, -W / 2, H_SUB]), np.array([_px, W / 2, H_SUB]))

# ── 求解 ──
FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：端口模式匹配 S 参数（交叉参考阻抗）+ 探针 β(f) ──
# 度量常数（pt2 实证）：模式加权 U=∫E·E_f（Yee 边）与 I=∫H·H_f（Yee 面）是
# 两套积分度量，对缝缘奇异模场 U/I=γ·Z_mode（本档 γ≈2.71；解析 TE10 平滑模
# γ≈1 故房式端口无此问题）。参考阻抗必须取"纯行波下的 U/I"才能精确分解；
# 为不循环论证（同一端口自己的 U_tot/I_tot 含物理反射、把它设为参考会令
# S11@f0 恒 0），**交叉取对面端口**的视入阻抗：到达 port2 的波被 PML 近全吸
# 收（Γ2≈PML 残量 ~1%），Z_app2≈Z_eff；反之对称。标量（γ 频率无关，f0 取值，
# 带边留 ~%级 S11 底噪，如实记录）。S21 约定按实证：透射波出现在 port2 的
# uf_inc（WaveguidePort 文件模式与房式 MSL 的 uf_ref 惯例相反）。
f = np.linspace(F0 - FC, F0 + FC, 201)

def _idx_f0(fv):
    return int(np.argmin(np.abs(np.asarray(fv) - F0)))

_i0 = _idx_f0(f)
_port1.CalcPort(SIM_PATH, f, ZL=Z_MODE)
_port2.CalcPort(SIM_PATH, f, ZL=Z_MODE)
_z1_raw = float(np.real(_port1.uf_tot[_idx_f0(f)] / _port1.if_tot[_idx_f0(f)]))
_z2_raw = float(np.real(_port2.uf_tot[_idx_f0(f)] / _port2.if_tot[_idx_f0(f)]))
# port2 的 I 探针 weight=direction=−1 → 到达波视入阻抗为负（pt2 实证 −285Ω）。
# port1 参考取 −z2_raw：z2 只含 port2 侧 PML 残量反射（干净），不含 port1 要
# 测的 S11（z1_raw 含 Γ1 会循环论证）；|z1|/|z2|−1 本身是 S11 的独立不变量
# （=2Γ/(1−Γ)，pt2 实测 2.17% → Γ≈1.1%）。
_z_ref1 = -_z2_raw
_z_ref2 = _z2_raw
_port1.CalcPort(SIM_PATH, f, ref_impedance=_z_ref1)
_port2.CalcPort(SIM_PATH, f, ref_impedance=_z_ref2)
_SREF = _port1.uf_inc
S11 = _port1.uf_ref / _SREF
S21 = _port2.uf_inc / _SREF          # 实证口径：透射行波=port2 的 uf_inc
S21_ALT = _port2.uf_ref / _SREF      # 诊断：备选约定（房式 MSL 口径）

# 探针槽跨压 → 沿线相位斜率 β(f)（不依赖端口 kc 假设）。
# β 用本脚本自实现工程 e^{{+jωt}} DFT（pt2 独立复算实证：UI_data 的 DFT 口径
# 相位反号且去卷积后斜率偏 ~14%，不可用；自实现 DFT 站间相位严格线性）。
_pnames = ["vslot_%02d" % _k for _k in range(len(PROBE_X))]
_vd = UI_data(_pnames, SIM_PATH, f)
_vfd = []
for _k in range(len(_pnames)):
    _t = np.asarray(_vd.ui_time[_k], dtype=float)
    _v = np.asarray(_vd.ui_val[_k], dtype=float)
    _dt = _t[1] - _t[0]
    _vfd.append((_v * np.exp(2j * np.pi * np.asarray(f)[:, None] * _t[None, :])).sum(axis=1) * _dt)
_vfd = np.array(_vfd)   # (n_sta, nf) 工程 e^{{+jωt}} 约定
_phases = np.unwrap(np.angle(_vfd), axis=0)
_amps = np.abs(_vfd)
beta_probe = np.polyfit(PROBE_X, _phases, 1)[0]   # 前行波 dφ/dx=+β（工程口径）
swr_amp = _amps.max(axis=0) / np.maximum(_amps.min(axis=0), 1e-300)

# DC 漂移守卫（pt1 首跑实证：MUR 延迟开启瞬态 → 探针尾段纯线性漂移）：
# 激励结束后（>1.3×信号长度）尾段最大幅值 / 脉冲窗（20%-60%）最大幅值
_drift_vt = np.abs(np.asarray(_vd.ui_val[0]))
_drift_t = np.asarray(_vd.ui_time[0])
_t_src = _drift_t[int(len(_drift_t) * 0.13)]
_pulse = (_drift_t > 0.2 * _drift_t[-1]) & (_drift_t < 0.6 * _drift_t[-1])
_late = _drift_t > min(1.3 * _t_src, 0.8 * _drift_t[-1])
drift_ratio = (float(_drift_vt[_late].max() / max(_drift_vt[_pulse].max(), 1e-300))
               if _pulse.any() and _late.any() else None)

# 模式纯度（p_type 10/11 信号附带的 mode_purity 列，时间序列）：取后半段均值
# （晚时≈稳态 CW）作诊断量；无该列时如实置 None
_purity = {{"u1": None, "i1": None}}
try:
    _up = np.asarray(_port1.u_mode_purity[0], dtype=float)
    _ip = np.asarray(_port1.i_mode_purity[0], dtype=float)
    _purity = {{"u1": float(np.mean(_up[len(_up) // 2:])),
                "i1": float(np.mean(_ip[len(_ip) // 2:]))}}
except Exception:
    pass

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real, S21[_i].imag])
with open(os.path.join(SCRIPT_DIR, "slotline_beta.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "beta_probe_rad_m", "beta_port_rad_m", "beta_ref_rad_m", "swr_amp"])
    for _i, _fi in enumerate(f):
        _bp = float(_port1.beta[_i]) if hasattr(_port1, "beta") else ""
        w_.writerow([_fi, beta_probe[_i], _bp, BETA_REF if BETA_REF else "", swr_amp[_i]])
summary = {{
    "ok": True,
    "excite_port": EXCITE_PORT,
    "f0_hz": F0, "fc_hz": FC,
    "w_m": W, "h_m": H_SUB, "er": ER,
    "line_len_m": float(X_MEAS2 - X_MEAS1),
    "port_inset_m": float(X_EXC1 - DOM_LO),
    "e_mode_file": E_FILE, "h_mode_file": H_FILE,
    "kc": [KC.real, KC.imag], "z_mode_ohm": Z_MODE,
    "z_ref_used_1_ohm": _z_ref1, "z_ref_used_2_ohm": _z_ref2,
    "z1_over_z2_minus_1": _z1_raw / abs(_z2_raw) - 1.0,
    "beta_ref_rad_m": BETA_REF,
    "s11_at_f0": [S11[_i0].real, S11[_i0].imag],
    "s21_at_f0": [S21[_i0].real, S21[_i0].imag],
    "s21_alt_at_f0": [S21_ALT[_i0].real, S21_ALT[_i0].imag],
    "beta_probe_at_f0": float(beta_probe[_i0]),
    "beta_port_at_f0": float(np.real(_port1.beta[_i0])) if hasattr(_port1, "beta") else None,
    "mode_purity": _purity,
    "swr_amp_at_f0": float(swr_amp[_i0]),
    "drift_ratio": drift_ratio,
    "nrts": NRTS,
}}
with open(os.path.join(SCRIPT_DIR, "slotline_summary.json"), "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto slotline route-A simulation done")
'''
