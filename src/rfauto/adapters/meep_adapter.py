"""Meep FDTD 适配器（第二开源 FDTD 交叉验证 + 采样扩容）。

定位：EMSolverRegistry 第四个开源通道（openEMS/Palace/NGSolve 之外），
mline 锚 β 三方对照（Meep/openEMS/HJ）互差 ≤5% 的 Meep 腿。

**部署口径（CI-only，冻结裁决）**：Meep 官方仅 conda-on-Linux
（Windows 仅 WSL2，违反本机约束）——本机不出报告，交叉验证在 Linux CI
runner 上跑（回退链见 knowledge/compat_matrix.yaml
meep 条目）。因此本适配器 = 「脚本生成 → 子进程执行 → CSV 解析」的
openEMS/Palace 同构模式，exe 指向**装有 meep 的 Python 解释器**
（configs/solvers.yaml exe_path / RFAUTO_MEEP_PYTHON 环境变量 /
PATH 上 python3 兜底）。

诚实边界（本机无 Meep）：
- 生成脚本按官方文档口径编写（API 逐条对照 meep.readthedocs.io
 Python_User_Interface / Python_Tutorials.Mode_Decomposition，见各处
 注释引用），**未经本机真跑验证**——首次 CI 真跑若发现 API/行为偏差，
 修脚本模板并回写本 docstring；
- β 提取做了版本兼容降级（EigenmodeData.k 缺失 → NaN，不阻塞 S 主路）；
- 介质损耗走常值 D_conductivity（官方 Materials 口径 σ_D=2π·f̃·tanδ），
 钉频带中心 f_pin=FCEN——与 openEMS 金锚 kappa=TAND·2π·F0·ε0·εr 的常 σ
 损耗模型同基准。常 σ ⇒ 有效 tanδ(f)=tanδ_pin·f_pin/f ∝ 1/f：带边损耗
 相对钉频值偏高/低，带宽越宽近似误差越大（诚实边界 #122；mline 锚为
 窄带对照用途，带内成立）；
- v1 仅 mline 锚 2 端口（采样扩容 = 参数化 w_mm/line_len_mm/频段经
 build_geometry 批量渲染，服务层编排后续 WP 接入）。

β 三方对照确定性内核（compare_beta_three_way）+ HJ 腿
（hj_beta_series，复用 core.synthesis.forward_z0 的 skrf HJ 模型，
零漂移）同模块交付。
"""

from __future__ import annotations

import contextlib
import csv
import itertools
import logging
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
  EMSolverAdapter,
  EMSolverConfig,
  EMSolverResult,
  SolverCapabilities,
)
from rfauto.core.synthesis import Stackup, forward_z0

logger = logging.getLogger(__name__)

_C0_M_S = 299792458.0
#: Meep 长度单位（脚本/解析两侧共用；1 LU = 1 mm）
MEEP_LENGTH_UNIT_M = 1e-3

#: openEMS port_beta.csv 同 schema（#162 β 金标准列名，两侧产物直接互比）
_BETA_CSV_HEADER = ("freq_hz", "beta_rad_per_m")
_SPARAMS_CSV_HEADER = ("freq_hz", "re_sxx", "im_sxx", "re_syx", "im_syx")

#: mline 锚默认参数（单一事实来源 openems_templates.TEMPLATE_NOMINAL["mline"]
# ：50Ω @rogers4350b = 1.113mm skrf HJ 精算；拿不到时字面量兜底同值）
_MLINE_FALLBACK = {"w_mm": 1.113, "line_len_mm": 40.0}


def mline_anchor_defaults() -> dict[str, float]:
  """mline 锚默认几何（w_mm/line_len_mm，mm）——从 openEMS 模板表取。"""
  with contextlib.suppress(Exception):
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    entry = TEMPLATE_NOMINAL.get("mline") or {}
    return {
      "w_mm": float(entry.get("w_mm", _MLINE_FALLBACK["w_mm"])),
      "line_len_mm": float(entry.get("line_len_mm", _MLINE_FALLBACK["line_len_mm"])),
    }
  return dict(_MLINE_FALLBACK)


def default_stackup() -> Stackup:
  """锚默认层叠 rogers4350b（er=3.66 / h=0.508mm / tanδ=0.0037，
  与 openems_templates 头注与 docs/rf_template_references.md 权威口径一致）。"""
  return Stackup(name="rogers4350b", epsilon_r=3.66, thickness_mm=0.508,
          loss_tangent=0.0037)


# ─── 单位换算内核（确定性；脚本与断言两侧共用）───────────────────────────────

def freq_hz_to_meep(freq_hz: float, length_unit_m: float = MEEP_LENGTH_UNIT_M) -> float:
  """SI 频率 Hz → Meep 无量纲频率（f̃ = f·LU/c0，c=1）。"""
  if length_unit_m <= 0:
    raise ValueError(f"长度单位必须为正: {length_unit_m}")
  return float(freq_hz) * length_unit_m / _C0_M_S


def beta_meep_to_si(beta_meep: float, length_unit_m: float = MEEP_LENGTH_UNIT_M) -> float:
  """Meep k（不含 2π，官方相位惯例 exp(i·2π·k·d)）→ SI rad/m：β=2π|k|/LU。"""
  if length_unit_m <= 0:
    raise ValueError(f"长度单位必须为正: {length_unit_m}")
  return 2.0 * math.pi * abs(float(beta_meep)) / length_unit_m


def tand_to_d_conductivity(
  freq_hz: float,
  loss_tangent: float,
  length_unit_m: float = MEEP_LENGTH_UNIT_M,
) -> float:
  """介质 tanδ → Meep D_conductivity σ_D（无量纲；官方 Materials 口径）。

  Meep 电导以 σ_D·D 入 Maxwell（与教科书 σ·E 本构差 ε 因子）：
    Im ε = ε∞·σ_D/(2πf̃)，tanδ = Im ε / Re ε
  ⇒ σ_D = 2π·f̃·tanδ（f̃ = f·LU/c0；εr 相消）。
  SI 式同值互证：σ_SI = 2πf·ε0·εr·tanδ ⇒ σ_D = (LU/c0)·σ_SI/(εr·ε0)。
  官方 worked 例：ε = 3.4+0.101i @ f̃ = 0.42 → σ_D = 2π·0.42·(0.101/3.4)。
  常值 σ_D 钉频带中心 f_pin ⇒ 有效 tanδ(f) = tanδ_pin·f_pin/f（1/f 特性，
  诚实边界见模块 docstring）。无损路径（tanδ≤0）不走本内核——渲染侧
  直接省略 D_conductivity 关键字。
  """
  if length_unit_m <= 0:
    raise ValueError(f"长度单位必须为正: {length_unit_m}")
  if freq_hz <= 0:
    raise ValueError(f"钉频必须为正（Hz）: {freq_hz}")
  if loss_tangent <= 0:
    raise ValueError(
      f"损耗正切必须为正（无损路径不走本内核）: {loss_tangent}")
  f_tilde = float(freq_hz) * length_unit_m / _C0_M_S
  return 2.0 * math.pi * f_tilde * float(loss_tangent)


# ─── 生成脚本模板（@TOKEN@ 占位——脚本体含 dict 字面量，不走 f-string）───────

_SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meep mline 锚仿真脚本（rfauto A1 MeepSolver 自动生成——勿手改）。

口径（A1）：
- S 参数：get_eigenmode_coefficients 正/反向 alpha 分解（官方 Mode
 Decomposition 教程惯例：alpha[..., 0]=+法向 / alpha[..., 1]=−法向，
 S = 出射系数/入射系数，同一几何单跑即可，无需归一化空跑）；
- β 金标准：get_eigenmode(...).k 传播方向分量（官方 Python User
 Interface：k = "the Bloch wavevector of the mode in direction"；
 meep k 不含 2π → beta_SI = 2*pi*abs(k_y)/LU）；
- 介质损耗：常值 D_conductivity 钉频带中心（有效 tanδ ∝ 1/f，
 见常量区注释与适配器 docstring 诚实边界）。

结构（镜像 openEMS mline 锚：地 z=0 / 基板 0..H / 顶面信号带，guided
口径基板延展到侧域边）：信号带 y 向贯穿全域穿过端口面进 PML 吸收。

单位：Meep 无量纲 c=1，长度单位 LU=@LU_M@ m；CSV 输出一律 SI：
 meep_sparams_p{N}.csv  freq_hz,re_sxx,im_sxx,re_syx,im_syx
 meep_port_beta_p{N}.csv freq_hz,beta_rad_per_m（与 openEMS #162 金标准同 schema）
用法：python3 meep_mline_sim.py --excite-port {1|2}
依赖：Meep >= 1.17（get_eigenmode 公开 API / stop_when_dft_decayed）。
"""
import argparse
import csv
import math

import meep as mp
import numpy as np

C0 = 299792458.0
LU = @LU_M@
W = @W_MM@      # 线宽（meep 单位=mm，LU=1mm 时 1:1）
H = @H_MM@      # 基板厚
L = @L_MM@      # 两端口间线长
ER = @ER@
RES = @RES@     # 分辨率 px/LU
DPML = @DPML_MM@
SRC_GAP = @SRC_GAP_MM@
MARGIN_X = @MARGIN_X_MM@
AIR_TOP = @AIR_TOP_MM@
FREQS_HZ = np.array(@FREQS_HZ@, dtype=float)
FREQS_MEEP = FREQS_HZ * LU / C0
FCEN = float((FREQS_MEEP[0] + FREQS_MEEP[-1]) / 2)
DF = float(FREQS_MEEP[-1] - FREQS_MEEP[0])
NFREQ = int(len(FREQS_MEEP))
T_METAL = 1.0 / RES  # 金属板厚=1 网格（FDTD 零厚度金属不可表达，薄 PEC 板惯例）
Y1 = -L / 2.0
Y2 = L / 2.0
YP1 = Y1 - SRC_GAP  # 端口 1 激励/监视面
YP2 = Y2 + SRC_GAP  # 端口 2 激励/监视面
CELL = mp.Vector3(W + 2 * MARGIN_X + 2 * DPML,
         L + 2 * SRC_GAP + 2 * DPML,
         2 * DPML + H + AIR_TOP)
TAND = @TAND@    # 介质损耗正切（≤0 = 无损路径，SUB 不带 D_conductivity）
SIGD = @SIGD@    # D_conductivity = 2π·f̃_pin·tanδ（无量纲，官方 Materials 口径）
# 常值 σ_D 钉频带中心（f_pin=FCEN，SI 侧为频带中点）：与 openEMS 金锚
# kappa=TAND·2π·F0·ε0·εr 的常 σ 损耗模型同基准。常 σ ⇒ 有效
# tanδ(f) = tanδ·f_pin/f ∝ 1/f——带边损耗偏离钉频值，带宽越宽偏差越大
# （诚实边界，见适配器 docstring）。
SUB = @SUB_EXPR@
MON_X = W + 2 * MARGIN_X  # 监视面 x 内域（PML 内不设监视）
MON_Z = H + AIR_TOP    # 监视面 z 内域
MON_ZC = (H + AIR_TOP) / 2.0


def _port_plane(y_center):
  """端口监视面/模体积（y 法向平面：x-z 截面，零 y 厚）。"""
  return mp.Vector3(0, y_center, MON_ZC), mp.Vector3(MON_X, 0, MON_Z)


def build_sim(excite_port: int):
  """构建仿真（几何 + 激励 + DFT 监视），返回 (sim, monitors dict)。"""
  center1, size1 = _port_plane(YP1)
  center2, size2 = _port_plane(YP2)
  geometry = [
    mp.Block(center=mp.Vector3(0, 0, -(DPML + T_METAL) / 2),
         size=mp.Vector3(mp.inf, mp.inf, DPML + T_METAL),
         material=mp.metal),
    mp.Block(center=mp.Vector3(0, 0, H / 2),
         size=mp.Vector3(mp.inf, mp.inf, H),
         material=SUB),
    mp.Block(center=mp.Vector3(0, 0, H + T_METAL / 2),
         size=mp.Vector3(W, mp.inf, T_METAL),
         material=mp.metal),
  ]
  excite_center = center1 if excite_port == 1 else center2
  sources = [mp.EigenModeSource(src=mp.GaussianSource(frequency=FCEN, fwidth=DF),
                 center=excite_center,
                 size=size1,
                 eig_band=1,
                 eig_match_freq=True)]
  sim = mp.Simulation(resolution=RES,
            cell_size=CELL,
            boundary_layers=[mp.PML(DPML)],
            geometry=geometry,
            sources=sources,
            default_material=mp.Medium(epsilon=1.0))
  flux1 = sim.add_flux(FCEN, DF, NFREQ, mp.FluxRegion(center=center1, size=size1))
  flux2 = sim.add_flux(FCEN, DF, NFREQ, mp.FluxRegion(center=center2, size=size2))
  return sim, {"flux1": flux1, "flux2": flux2,
         "plane1": (center1, size1), "plane2": (center2, size2)}


def _beta_at(sim, plane, f_meep: float) -> float:
  """端口面模 beta（rad/m，SI）。best-effort：失败/属性缺失降级 NaN，
  不阻塞 S 参数主路（观测性代码不阻塞主路径，#105 同源纪律）。"""
  center, size = plane
  try:
    mode = sim.get_eigenmode(float(f_meep), mp.Y,
                 mp.Volume(center=center, size=size),
                 1, mp.Vector3(0, math.sqrt(ER) * f_meep, 0))
  except Exception as exc:
    print(f"[meep_mline] beta@{f_meep:.6g} 提取失败: {exc}")
    return float("nan")
  k_vec = getattr(mode, "k", None)
  if k_vec is None:
    print("[meep_mline] EigenmodeData.k 缺失（Meep 版本过旧）-> NaN")
    return float("nan")
  return 2.0 * math.pi * abs(float(k_vec.y)) / LU


def run_port(excite_port: int, out_dir: str = ".") -> None:
  """单激励求解 + S 参数/beta 落盘（两端口进程隔离由适配器编排）。"""
  sim, mon = build_sim(excite_port)
  sim.run(until_after_sources=mp.stop_when_dft_decayed())
  res1 = sim.get_eigenmode_coefficients(mon["flux1"], [1], eig_parity=mp.NO_PARITY)
  res2 = sim.get_eigenmode_coefficients(mon["flux2"], [1], eig_parity=mp.NO_PARITY)
  a1 = res1.alpha[0]  # (NFREQ, 2)：[.., 0]=+y 正向，[.., 1]=-y 反向
  a2 = res2.alpha[0]
  excite_plane = mon["plane1"] if excite_port == 1 else mon["plane2"]
  p_rows = []
  b_rows = []
  for i in range(NFREQ):
    f_hz = float(FREQS_HZ[i])
    if excite_port == 1:
      inc = a1[i, 0]
      sxx = a1[i, 1] / inc  # S11（同面反向/入射）
      syx = a2[i, 0] / inc  # S21（对面正向/入射）
    else:
      inc = a2[i, 0]
      sxx = a2[i, 1] / inc  # S22
      syx = a1[i, 0] / inc  # S12
    p_rows.append([f_hz, sxx.real, sxx.imag, syx.real, syx.imag])
    b_rows.append([f_hz, _beta_at(sim, excite_plane, float(FREQS_MEEP[i]))])
  tag = "p%d" % excite_port
  with open(f"{out_dir}/meep_sparams_{tag}.csv", "w", newline="",
       encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "re_sxx", "im_sxx", "re_syx", "im_syx"])
    w.writerows(p_rows)
  with open(f"{out_dir}/meep_port_beta_{tag}.csv", "w", newline="",
       encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "beta_rad_per_m"])
    w.writerows(b_rows)
  betas = [r[1] for r in b_rows if r[1] == r[1]]
  if betas:
    print(f"[meep_mline] {tag} 完成：{NFREQ} 频点，beta 范围 "
       f"[{min(betas):.3f}, {max(betas):.3f}] rad/m")
  else:
    print(f"[meep_mline] {tag} 完成：{NFREQ} 频点，beta 全 NaN（需查版本兼容层）")


def main() -> None:
  ap = argparse.ArgumentParser(description="mline 锚 Meep 仿真（rfauto A1 生成）")
  ap.add_argument("--excite-port", type=int, choices=(1, 2), default=1)
  args = ap.parse_args()
  run_port(args.excite_port)


if __name__ == "__main__":
  main()
'''


def render_mline_script(
  w_mm: float,
  line_len_mm: float,
  stackup: Stackup,
  freqs_hz: list[float],
  *,
  resolution: float,
  dpml_mm: float = 2.0,
  src_gap_mm: float = 2.0,
  margin_x_mm: float | None = None,
  air_top_mm: float | None = None,
  length_unit_m: float = MEEP_LENGTH_UNIT_M,
) -> str:
  """渲染 mline 锚 Meep 仿真脚本（纯字符串，不落盘不执行）。

  空气边距默认 max(3W, 3H)（x 向与 z 向同口径，模场衰减 + PML 余量）。
  介质损耗：stackup.loss_tangent > 0 时 SUB 走常值 D_conductivity
  （tand_to_d_conductivity 内核，钉频带中心 f_pin=(f_first+f_last)/2，
  与脚本 FCEN 同点）；≤0 保持无关键字的 lossless 路径。
  """
  if resolution <= 0:
    raise ValueError(f"分辨率必须为正: {resolution}")
  if len(freqs_hz) < 2:
    raise ValueError("至少 2 个频点（DF=0 会使高斯源退化为直流）")
  if any(f <= 0 for f in freqs_hz):
    raise ValueError("频点必须为正（Hz）")
  margin = margin_x_mm if margin_x_mm is not None else max(3.0 * w_mm, 3.0 * stackup.thickness_mm)
  air_top = air_top_mm if air_top_mm is not None else max(3.0 * w_mm, 3.0 * stackup.thickness_mm)
  freqs_repr = "[" + ", ".join(repr(float(f)) for f in freqs_hz) + "]"
  loss_tangent = float(stackup.loss_tangent)
  lossy = loss_tangent > 0
  # 钉频 = 频带中心（首末频点中点；与脚本 FCEN 同一物理点，f̃ 线性于 f）
  f_pin_hz = 0.5 * (float(freqs_hz[0]) + float(freqs_hz[-1]))
  sigd = (tand_to_d_conductivity(f_pin_hz, loss_tangent, length_unit_m)
      if lossy else 0.0)
  sub_expr = ("mp.Medium(epsilon=ER, D_conductivity=SIGD)" if lossy
        else "mp.Medium(epsilon=ER)")
  script = _SCRIPT_TEMPLATE
  for token, value in (
    ("@LU_M@", repr(float(length_unit_m))),
    ("@W_MM@", repr(float(w_mm))),
    ("@H_MM@", repr(float(stackup.thickness_mm))),
    ("@L_MM@", repr(float(line_len_mm))),
    ("@ER@", repr(float(stackup.epsilon_r))),
    ("@TAND@", repr(loss_tangent)),
    ("@SIGD@", repr(float(sigd))),
    ("@SUB_EXPR@", sub_expr),
    ("@RES@", repr(float(resolution))),
    ("@DPML_MM@", repr(float(dpml_mm))),
    ("@SRC_GAP_MM@", repr(float(src_gap_mm))),
    ("@MARGIN_X_MM@", repr(float(margin))),
    ("@AIR_TOP_MM@", repr(float(air_top))),
    ("@FREQS_HZ@", freqs_repr),
  ):
    script = script.replace(token, value)
  return script


# ─── HJ 腿与 β 三方对照确定性内核 ─────────────────────────────────────────────

def hj_beta_series(
  width_mm: float,
  freq_ghz: np.ndarray | list[float] | tuple[float, ...],
  stackup: Stackup | None = None,
) -> np.ndarray:
  """HJ 闭式腿：线宽+频点 → β 序列（rad/m）。

  复用 core.synthesis.forward_z0（skrf MLine Hammerstad-Jensen，与
  openEMS 线宽综合同一模型，零漂移）；εeff → β = 2π·f·√εeff/c0。
  """
  st = stackup or default_stackup()
  out: list[float] = []
  for f in np.atleast_1d(np.asarray(freq_ghz, dtype=float)):
    if f <= 0:
      raise ValueError(f"频率必须为正（GHz）: {f}")
    _, eeff = forward_z0(float(width_mm), float(f), st)
    out.append(2.0 * math.pi * float(f) * 1e9 * math.sqrt(eeff) / _C0_M_S)
  return np.array(out, dtype=float)


def _sym_rel_diff(a: float, b: float) -> float:
  """对称相对差 |a−b| / mean(|a|,|b|)（"互差"口径，双方对称无锚定偏置）。"""
  denom = (abs(a) + abs(b)) / 2.0
  if denom == 0.0:
    return 0.0
  return abs(a - b) / denom


@dataclass(frozen=True)
class BetaTriadReport:
  """β 三方对照（Meep/openEMS/HJ， A1 验收内核）结果。"""
  n_freq: int
  tol_rel: float
  #: 全频点三对两两互差的最大值（判定量：≤tol_rel 即 passed）
  max_pairwise_rel: float
  #: 每对腿的全频点最大互差（键序 "hj-openems"/"hj-meep"/"openems-meep"）
  per_pair_max_rel: dict[str, float]
  worst_freq_ghz: float
  culprit_pair: str
  passed: bool

  def to_dict(self) -> dict[str, Any]:
    return {
      "n_freq": self.n_freq,
      "tol_rel": self.tol_rel,
      "max_pairwise_rel": self.max_pairwise_rel,
      "per_pair_max_rel": dict(self.per_pair_max_rel),
      "worst_freq_ghz": self.worst_freq_ghz,
      "culprit_pair": self.culprit_pair,
      "passed": self.passed,
    }


def compare_beta_three_way(
  freq_ghz: np.ndarray | list[float],
  beta_hj: np.ndarray | list[float],
  beta_openems: np.ndarray | list[float],
  beta_meep: np.ndarray | list[float],
  tol_rel: float = 0.05,
) -> BetaTriadReport:
  """β 三方互差判定（确定性内核；A1 验收：互差 ≤5%）。

  三腿必须在同一频点网格上（长度一致；网格对齐由调用方经
  geometry["freqs_ghz"] 显式传频点实现）。任何一腿含 NaN/Inf/非正值的
  频点即 ValueError（β>0 物理量，静默吞掉等于假绿）。
  """
  grids = [np.asarray(x, dtype=float) for x in (freq_ghz, beta_hj, beta_openems, beta_meep)]
  n = len(grids[0])
  if any(len(g) != n for g in grids):
    raise ValueError(f"三方 β 频点长度不一致: {[len(g) for g in grids]}")
  if n == 0:
    raise ValueError("空频点网格")
  for name, arr in zip(("freq", "hj", "openems", "meep"), grids, strict=True):
    if not np.all(np.isfinite(arr)):
      raise ValueError(f"{name} 腿含 NaN/Inf（频点 {int(np.argmin(np.isfinite(arr)))}）")
  if np.any(grids[1] <= 0) or np.any(grids[2] <= 0) or np.any(grids[3] <= 0):
    raise ValueError("β 必须为正（物理传播常数）")
  legs = {"hj": grids[1], "openems": grids[2], "meep": grids[3]}
  pairs = (("hj", "openems"), ("hj", "meep"), ("openems", "meep"))
  per_pair: dict[str, float] = {}
  worst_pair = ""
  worst_val = -1.0
  worst_freq = 0.0
  for a, b in pairs:
    diffs = np.array([_sym_rel_diff(float(x), float(y))
             for x, y in zip(legs[a], legs[b], strict=True)])
    i = int(np.argmax(diffs))
    per_pair[f"{a}-{b}"] = float(diffs[i])
    if diffs[i] > worst_val:
      worst_val = float(diffs[i])
      worst_pair = f"{a}-{b}"
      worst_freq = float(grids[0][i])
  return BetaTriadReport(
    n_freq=n,
    tol_rel=float(tol_rel),
    max_pairwise_rel=worst_val,
    per_pair_max_rel=per_pair,
    worst_freq_ghz=worst_freq,
    culprit_pair=worst_pair,
    passed=worst_val <= float(tol_rel),
  )


# ─── 适配器 ──────────────────────────────────────────────────────────────────

class MeepSolver(EMSolverAdapter):
  """Meep FDTD 适配器（子进程 + 结果文件，与 openEMS/Palace 同构）。

  exe_path 语义 = **装有 meep 的 Python 解释器**（CI Linux conda env /
  WSL2 内 python）。solve() 对生成的脚本执行两次子进程
  （--excite-port 1/2，进程隔离编排——两端口全 S 矩阵），解析
  meep_sparams_p{1,2}.csv 与 meep_port_beta_p{1,2}.csv。
  """

  # A5 能力声明（如实，逐条核对；本机无 Meep，声明只覆盖
  # 适配器实际实现面，不虚报引擎理论能力）：
  #  - 端口：EigenModeSource + get_eigenmode_coefficients 模式端口
  #   （官方 Mode Decomposition 口径）→ wave=True；无集总元件实现
  #   → lumped/lumped_elements=False；
  #  - 材料：epsilon + 常值 D_conductivity（tanδ 钉频带中心，官方
  #   Materials 口径）+ PEC 板 → pec+lossless+lossy；
  #  - Touchstone：仅解析/产出 CSV → False（supported_output_formats
  #   同步如实 ["csv"]）；
  #  - 场导出/收敛报告/optimetrics/nf2ff/SAR：适配器无对应实现 → False；
  #  - 模板：v1 仅 mline 锚脚本渲染 → ("mline",)；
  #  - 并行：subprocess 不传 mpirun/MPI 开关 → 空元组；license：开源 → False。
  CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
    solver_type="meep",
    supports_wave_port=True,
    supports_lumped_port=False,
    supports_field_export=False,
    supports_convergence_report=False,
    supports_touchstone_export=False,
    supports_headless_solve=True,
    supports_optimetrics=False,
    dimension="3d",
    material_models=("pec", "lossless_dielectric", "lossy_dielectric"),
    parallel_backends=(),
    supports_sar=False,
    supports_nf2ff=False,
    supports_lumped_elements=False,
    supported_templates=("mline",),
    requires_license=False,
    availability_gate="python_exe+meep_import",
  )

  def __init__(self, config: EMSolverConfig):
    super().__init__(config)
    self._exe_path: str | None = config.exe_path
    self._script_path: Path | None = None

  # ── 生命周期 ────────────────────────────────────────────────────────────

  def connect(self) -> bool:
    exe = self._exe_path or self._find_exe()
    if exe is None or not Path(exe).exists():
      return False
    self._exe_path = exe
    self._connected = True
    return True

  def is_available(self) -> bool:
    exe = self._exe_path or self._find_exe()
    return exe is not None and Path(exe).exists()

  def _find_exe(self) -> str | None:
    """解析 meep 解释器：RFAUTO_MEEP_PYTHON → PATH 上 python3/python。"""
    env = os.environ.get("RFAUTO_MEEP_PYTHON")
    if env and Path(env).exists():
      return env
    for cand in ("python3", "python"):
      found = shutil.which(cand)
      if found:
        return found
    return None

  def verify_import(self, timeout_s: int = 120) -> tuple[bool, str]:
    """可用性深度探测：解释器能否 import meep（best-effort，离线快照用）。

    is_available() 只验 exe 存在（快路径）；本方法真跑一次 import——
    CI 探测/诊断入口，不在求解主路径上。
    """
    exe = self._exe_path or self._find_exe()
    if exe is None or not Path(exe).exists():
      return False, "meep 解释器不存在"
    try:
      proc = subprocess.run(
        [str(exe), "-c", "import meep; print(getattr(meep, '__version__', 'unknown'))"],
        capture_output=True, text=True, timeout=timeout_s, check=False,
      )
    except (subprocess.TimeoutExpired, OSError) as exc:
      return False, f"meep import 探测失败: {exc}"
    if proc.returncode != 0:
      return False, f"import meep 失败（退出码 {proc.returncode}）: {proc.stderr[-200:]}"
    return True, proc.stdout.strip() or "unknown"

  # ── 配置生成 ────────────────────────────────────────────────────────────

  def build_geometry(self, geometry: dict[str, Any]) -> bool:
    """渲染 mline 锚脚本到 working_dir/meep_mline_sim.py。

    geometry 契约（v1 仅 mline 锚 2 端口）:
      template: "mline"     —— 缺省即 mline，显式给其他值报 False
      params: {w_mm, line_len_mm} —— 可选，缺省取 openEMS 模板锚同源默认
      stackup: {epsilon_r, thickness_mm, loss_tangent, name} — 可选
      freqs_ghz: [f1, ...]    —— 可选显式频点（与 openEMS 网格对齐用），
                     缺省 freq_range_ghz 上均匀 n_freq 点
      n_freq: int        —— 可选（默认 41；≥2）
      resolution: float     —— 可选 px/LU（默认 1/mesh_resolution_mm）
      dpml_mm/src_gap_mm/margin_x_mm/air_top_mm —— 可选几何覆盖
    """
    if not self._connected:
      return False
    template = str(geometry.get("template", "mline"))
    if template != "mline":
      logger.error("MeepSolver v1 仅支持 mline 锚模板，收到: %s", template)
      return False
    params = dict(geometry.get("params") or {})
    defaults = mline_anchor_defaults()
    w_mm = float(params.get("w_mm", defaults["w_mm"]))
    line_len_mm = float(params.get("line_len_mm", defaults["line_len_mm"]))
    if w_mm <= 0 or line_len_mm <= 0:
      logger.error("mline 几何参数必须为正: w_mm=%s line_len_mm=%s", w_mm, line_len_mm)
      return False
    st_in = geometry.get("stackup") or {}
    st = Stackup(
      name=str(st_in.get("name", "rogers4350b")),
      epsilon_r=float(st_in.get("epsilon_r", default_stackup().epsilon_r)),
      thickness_mm=float(st_in.get("thickness_mm", default_stackup().thickness_mm)),
      loss_tangent=float(st_in.get("loss_tangent", default_stackup().loss_tangent)),
    )
    n_freq = int(geometry.get("n_freq", 41))
    if n_freq < 2:
      logger.error("n_freq 必须 ≥2（DF=0 高斯源退化），收到: %s", n_freq)
      return False
    freqs_ghz = geometry.get("freqs_ghz")
    lo, hi = self._config.freq_range_ghz
    fs = ([float(f) for f in freqs_ghz] if freqs_ghz is not None
       else list(np.linspace(lo, hi, n_freq)))
    if len(fs) < 2:
      logger.error("频点网格须 ≥2 点（DF=0 高斯源退化）: %s", fs[:5])
      return False
    if any(f <= 0 for f in fs):
      logger.error("频点必须为正（GHz）")
      return False
    if any(b <= a for a, b in itertools.pairwise(fs)):
      logger.error("频点网格须严格递增: %s", fs[:5])
      return False
    resolution = float(geometry.get("resolution") or (1.0 / self._config.mesh_resolution_mm))
    freqs_hz = [f * 1e9 for f in fs]
    try:
      script = render_mline_script(
        w_mm, line_len_mm, st, freqs_hz,
        resolution=resolution,
        dpml_mm=float(geometry.get("dpml_mm", 2.0)),
        src_gap_mm=float(geometry.get("src_gap_mm", 2.0)),
        margin_x_mm=geometry.get("margin_x_mm"),
        air_top_mm=geometry.get("air_top_mm"),
      )
    except ValueError as exc:
      logger.error("mline 脚本渲染失败: %s", exc)
      return False
    workdir = Path(self._config.working_dir or ".")
    workdir.mkdir(parents=True, exist_ok=True)
    self._script_path = workdir / "meep_mline_sim.py"
    self._script_path.write_text(script, encoding="utf-8")
    return True

  # ── 求解与解析 ──────────────────────────────────────────────────────────

  def solve(self, timeout_s: int = 3600) -> EMSolverResult:
    """两激励子进程求解（进程隔离编排）→ 全 S 矩阵 + β。"""
    if not self._connected:
      return EMSolverResult(success=False, message="Not connected")
    if self._script_path is None or not self._script_path.exists():
      return EMSolverResult(success=False, message="build_geometry() 未生成仿真脚本")
    workdir = Path(self._config.working_dir or ".")
    t0 = time.time()
    for port in (1, 2):
      cmd = [str(self._exe_path), self._script_path.name,
          "--excite-port", str(port)]
      try:
        proc = subprocess.run(
          cmd, cwd=workdir, capture_output=True, text=True,
          timeout=timeout_s, check=False,
        )
      except subprocess.TimeoutExpired:
        return EMSolverResult(success=False,
                   message=f"Meep 求解超时（>{timeout_s}s，port {port}）")
      except OSError as exc:
        return EMSolverResult(success=False, message=f"Meep 启动失败: {exc}")
      if proc.returncode != 0:
        return EMSolverResult(
          success=False, wall_time_s=round(time.time() - t0, 1),
          message=(f"Meep 退出码 {proc.returncode}（port {port}）: "
               f"{proc.stderr[-400:]}"))
    wall = round(time.time() - t0, 1)
    paths = [workdir / f"meep_sparams_p{n}.csv" for n in (1, 2)]
    if not all(p.exists() for p in paths):
      missing = [p.name for p in paths if not p.exists()]
      return EMSolverResult(success=False, wall_time_s=wall,
                 message=f"Meep 未产出结果 CSV: {missing}")
    try:
      freq_hz, s1, b1 = self._parse_port_csv(paths[0])
      freq2_hz, s2, b2 = self._parse_port_csv(paths[1])
    except Exception as exc:
      return EMSolverResult(success=False, wall_time_s=wall,
                 message=f"Meep CSV 解析失败: {exc}")
    if not np.allclose(freq_hz, freq2_hz):
      return EMSolverResult(success=False, wall_time_s=wall,
                 message="两次激励的频点网格不一致（脚本生成异常）")
    n = len(freq_hz)
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s1[:, 0]  # S11 = p1 跑：port1 反向/入射
    s[:, 1, 0] = s1[:, 1]  # S21 = p1 跑：port2 正向/入射
    s[:, 1, 1] = s2[:, 0]  # S22 = p2 跑
    s[:, 0, 1] = s2[:, 1]  # S12 = p2 跑
    field_data: dict[str, Any] = {
      "freq_hz": freq_hz,
      "beta_rad_per_m": b1,    # 激励 port1 面（传播方向 β 主腿）
      "beta_p2_rad_per_m": b2,
    }
    message = "Meep solve ok（2 激励子进程）"
    if bool(np.all(np.isnan(b1))):
      message += "；β 全 NaN（检查 EigenmodeData.k 版本兼容层）"
    return EMSolverResult(success=True, freq_ghz=freq_hz / 1e9, s_params=s,
               field_data=field_data, wall_time_s=wall,
               message=message)

  @staticmethod
  def _parse_port_csv(path: Path) -> tuple[Any, Any, Any]:
    """解析单激励产物：→ (freq_hz, s 矩阵 (n,2) 复数 [sxx, syx], beta (n,))。"""
    with open(path, encoding="utf-8") as f:
      rows = list(csv.reader(f))
    if len(rows) < 2:
      raise ValueError(f"结果为空: {path.name}")
    header = [h.strip().lower() for h in rows[0]]
    if not header or header[0] != _BETA_CSV_HEADER[0]:
      raise ValueError(f"CSV 表头不符合契约（首列须 freq_hz）: {path.name}: {header}")
    if len(header) > 1 and tuple(header[:5]) != _SPARAMS_CSV_HEADER:
      raise ValueError(f"S 参数 CSV 表头不符合契约: {path.name}: {header}")
    freqs: list[float] = []
    svals: list[tuple[complex, complex]] = []
    for r in rows[1:]:
      if not r or not r[0].strip():
        continue
      freqs.append(float(r[0]))
      if len(r) >= 5:
        svals.append((complex(float(r[1]), float(r[2])),
               complex(float(r[3]), float(r[4]))))
      else:
        svals.append((complex(float(r[1])), 0j))
    freq_arr = np.array(freqs, dtype=float)
    s_arr = np.array(svals, dtype=complex)
    # beta 伴生文件（同名 _beta_）：缺失时回退 NaN 序列（不阻塞 S 主路）
    beta_path = path.parent / path.name.replace("meep_sparams_", "meep_port_beta_")
    beta_arr = np.full(len(freqs), np.nan)
    if beta_path.exists():
      with open(beta_path, encoding="utf-8") as f:
        brows = list(csv.reader(f))
      betas: list[float] = []
      for r in brows[1:]:
        if not r or not r[0].strip():
          continue
        betas.append(float(r[1]))
      if len(betas) == len(freqs):
        beta_arr = np.array(betas, dtype=float)
    return freq_arr, s_arr, beta_arr

  def get_sparams(self) -> Any:
    """读取最近一次 solve 的 S 参数（与 PalaceSolver 同约定）。"""
    workdir = Path(self._config.working_dir or ".")
    paths = [workdir / f"meep_sparams_p{n}.csv" for n in (1, 2)]
    if not all(p.exists() for p in paths):
      return None
    try:
      freq_hz, s1, _ = self._parse_port_csv(paths[0])
      freq2_hz, s2, _ = self._parse_port_csv(paths[1])
    except Exception:
      return None
    if not np.allclose(freq_hz, freq2_hz):
      return None
    s = np.zeros((len(freq_hz), 2, 2), dtype=complex)
    s[:, 0, 0] = s1[:, 0]
    s[:, 1, 0] = s1[:, 1]
    s[:, 1, 1] = s2[:, 0]
    s[:, 0, 1] = s2[:, 1]
    return freq_hz / 1e9, s

  def get_beta(self) -> tuple[Any, Any] | None:
    """读取最近一次 solve 的 β 主腿（激励 port1 面，rad/m）。"""
    workdir = Path(self._config.working_dir or ".")
    beta_path = workdir / "meep_port_beta_p1.csv"
    if not beta_path.exists():
      return None
    try:
      with open(beta_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
      freqs = [float(r[0]) for r in rows[1:] if r and r[0].strip()]
      betas = [float(r[1]) for r in rows[1:] if r and r[0].strip()]
    except Exception:
      return None
    return np.array(freqs) / 1e9, np.array(betas)

  def close(self) -> None:
    self._connected = False
    self._script_path = None

  # ── 6g 产物视图协议 ────────────────────────────────────────────────────

  def visualizations(self) -> list[dict[str, Any]]:
    workdir = self._config.working_dir or "."
    return [
      {"kind": "model3d", "spec": {"script": "meep_mline_sim.py",
                     "format": "meep-python"}},
      {"kind": "sparams", "spec": {"file": str(Path(workdir) / "meep_sparams_p1.csv")}},
    ]

  def supported_output_formats(self) -> list[str]:
    return ["csv"]


def register_meep() -> None:
  """注册 Meep 求解器到全局注册表（与 palace_solver 同模式）。"""
  from rfauto.adapters.em_solver_base import EMSolverType, get_global_registry
  get_global_registry().register(EMSolverType.MEEP, MeepSolver)


"""Register on import (same pattern as palace_solver; never blocks import)."""
with contextlib.suppress(Exception):
  register_meep()
