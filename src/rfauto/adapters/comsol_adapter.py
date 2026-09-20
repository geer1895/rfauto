"""COMSOL Multiphysics（RF Module）求解器适配器（第三方仲裁首案例）。

定位：第三方仲裁通道（COMSOL FEM vs openEMS FDTD vs HFSS FEM 三源对拍），
稀缺 license 资源，不做日常主力。

通道：MPh（JPype）桥 → 本机 comsolmphserver 6.3。纪律（docs/comsol_references.md）：
- ``mph.start(version="6.3")`` 显式钉版本（#215：MPh 自动选最新=6.4，license 已过期）；
- 一个 Python 进程只能有一个 Client（JPype 单 JVM）→ 模块级单例 ``get_shared_client``；
- 每次求解占一个 RF license 席位 → 模块级锁 ``_SOLVE_LOCK`` 串行，同时刻只跑一个求解；
- COMSOL API 一律对照官方文档/官方例实录，禁止凭想象写。本文件每处 API 的来源：
 * 模型树骨架（component/geom/material/physics/study）：ApplicationProgrammingGuide；
 * 材料 ``propertyGroup("def").set(...)``：ApplicationProgrammingGuide p.52；
 * LumpedPort 属性名（PortName/PortType/TerminalType/Zref/PortExcitation）：
  官方例 microstrip_line_tem_via.mph 实录（API 属性 dump 存档）
  + RF Module User's Guide "Lumped Port" 节（p.143-149）；
 * Box 选择集属性（entitydim/xmin..zmax/condition）：Programming Reference Manual
  Table 2-125；网格 size 属性（custom/hmax）：同手册 mesh Size 节；
 * S 参量变量 ``comp1.<tag>.Sij`` 与 ``EvalGlobal``/``getReal``/``getImag``：
  RF Module User's Guide p.71 + Programming Reference Manual ch.7。

首案例模板 ``parallel_plate``：平行板 TEM 传输线 2 端口（板间介质 εr，板宽 W、
板距 H、长 L）。选它作首案例的理由：闭式精确（TEM：εeff=εr、Z0=η0/√εr·H/W，
S21=e^{-jβL}），无需空气盒/PML；两块 PEC 板 + 两端集总端口（官方口径：集总端口
必须跨两金属边界）+ 侧壁 PMC（User's Guide p.143：与 E 极化平行的切割面用 PMC，
TEM 模精确满足 n×H=0；若留默认 PEC 会变成截止矩形波导——建模错误的典型陷阱）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
  EMSolverAdapter,
  EMSolverConfig,
  EMSolverResult,
  EMSolverType,
  SolverCapabilities,
  get_global_registry,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
COMSOL_VERSION_PIN = "6.3" # #215：6.4 license 过期，必须显式钉 6.3
DEFAULT_COMSOL_ROOT = r"E:\COMSOL\COMSOL_63\COMSOL63\Multiphysics"
PHYSICS_TYPE = "ElectromagneticWaves" # RF Module 频域接口 API 类型串（官方例实录）
PHYSICS_TAG = "emw" # 官方默认 tag；S 变量 comp1.emw.Sij（User's Guide p.71）
# 注意（真机实证）：
# "ElectromagneticWavesFrequencyDomain" 也能创建，但该接口**没有 LumpedPort 特征**
# （Wave Optics 风格 ewfd，仅 Port）——RF 集总端口建模必须用 "ElectromagneticWaves"。
STUDY_TAG = "std1"
FREQ_STEP_TAG = "freq" # 频域步 tag（两模板统一；重解路径改其 plist 单频点）
C0 = 299792458.0
ETA0 = 376.730313668 # 自由空间波阻抗 Ω

# 首案例模板参数默认值（H 按 Z0=50Ω 反算：H = Z0·√εr·W/η0）
PARALLEL_PLATE_DEFAULTS: dict[str, float] = {
  "length_mm": 20.0,
  "width_mm": 6.0,
  "height_mm": 1.154,
  "eps_r": 2.1,
  "z_ref_ohm": 50.0,
}
# 第二案例 mline 锚模板参数默认值（WP2.1 权威口径表 §1：50Ω@rogers4350b，
# W=1.113mm 由 skrf HJ 综合；层叠同 openEMS _DEFAULT_SUB er=3.66/h=0.508）。
# 注意：COMSOL 通道按无耗建模（tanδ 不建——对 εeff/|S11| 影响 ≪ 锚 ±2% 门），
# 基板损耗偏差在 build 证据 spec_doc 里如实声明。
MLINE_DEFAULTS: dict[str, float] = {
  "w_mm": 1.113,
  "line_len_mm": 40.0,
  "eps_r": 3.66,
  "sub_h_mm": 0.508,
  "z_ref_ohm": 50.0,
}
# mline FEM 域常数（区别于 openEMS 60mm PML 板：FEM 用小域+散射边界，官方
# 例 microstrip_line_crosstalk.mph 同手法；走线=薄 Block 六面 PEC，端口面=
# 中块端面跨「地面 PEC↔走线底 PEC」，官方 User's Guide p.143 口径）
MLINE_TRACE_T_MM = 0.05 # 仅用于厚度敏感性记录：走线实际为零厚度 PEC 片
MLINE_TAN_D = 0.0037 # rogers4350b tanδ（材料表值）：闭式锚 2.85264 的口径
MLINE_AIR_SIDE_MM = 6.0
MLINE_AIR_TOP_MM = 3.5 # run5 实证：顶隙 0.8mm 时 SBC 电容加载使 εeff +14% 且吸收 10% 功率
MLINE_PORT_MARGIN_MM = 3.0 # 端口面到 y 端吸收边界的余量（真机实证约束，见 _build_mline）

# ── mline 端口链扩展（队列4 未尽 6i③：TEM 边界模端口完整链）──────────────────
# 集总端口 Uniform 准静态场形与微带模失配 → εeff 相位斜率系统性 +4.81% 如实
# FAIL（run7/11 实测）；TEM 边界模端口是官方消除该口径差的路径：
#  * 数值 TEM 官方链=官方例 cpw_numeric_tem_port.mph（本机 applications/ 实录
#   index.txt）：emw + Port 特征（PortType="TEM"、numericTEM=1）+ study
#   std=[bma(BoundaryModeAnalysis), freq(Frequency)]；
#  * 解析 TEM 官方链=官方例 microstrip_line_tem_via.mph dmodel.xml 实录（本地
#   解包存档）：Port StudyStep="std1/tbma"
#   解引用（端口模取自边界模分析步）——本适配器照此同构把 StudyStep 指向
#   "std1/bma"。run9/10 的 Cmode_1 未定义即缺这条解引用接线（端口缺省指向
#   Frequency 步，而 Cmode/Lmode 只在边界模分析步产生）。
#  * 边界模分析步类型串 "BoundaryModeAnalysis"（cpw 例 @type 实录）；
#   解析同轴变体 "TEMBoundaryModeAnalysis"（tem_via dmodel 实录）。
MLINE_PORT_CHAINS: tuple[str, ...] = ("lumped", "tem")
PORT_TYPE_TEM = "TEM" # 解析同轴 TEM 型（官方例 microstrip_line_tem_via 实录）
PORT_TYPE_NUMERIC = "Numeric" # 数值端口型（官方例 waveguide_adapter dmodel 实录；
# cpw_numeric_tem_port 官方文档 "Type of port: Numeric" + "Analyze as a TEM
# field" checkbox→ numericTEM=1；RF User's Guide p.128：TEM field 模式必须加
# Integration Line for Voltage 子特征定标端口模阻抗）
STUDY_STEP_BOUNDARY_MODE = "BoundaryModeAnalysis" # 数值 TEM 官方链（cpw 例）
STUDY_STEP_TEM_BMA = "TEMBoundaryModeAnalysis" # 解析同轴 TEM 官方链（tem_via 例）
STUDY_STEP_BMA_TAG_FMT = "bma{port}" # 每端口一个边界模分析步（官方 cpw 例：
# Step1 bma PortName=1 → dup bma PortName=2 → freq）
BMA_STEP_REF_FMT = "{study}/{step}" # 端口 StudyStep 解引用格式（官方 std1/tbma 同构）
BMA_MODE_FREQ_ATTR = "modeFreq" # 边界模分析频率属性（真机 dump 实录）
BMA_SHIFT_ATTR = "shift" # 本征值搜索偏移（官方 cpw 例 sqrt(epsr)/1.5 同源口径）
INTEGRATION_LINE_FOR_VOLTAGE = "IntegrationLineforVoltage" # 真机自校验实录
# （GUI 名 "Integration Line for Voltage" 去空格、for 小写；RF User's Guide
# p.128：数值 TEM 端口必须配电压积分线子特征定标端口模阻抗）
# tanδ 介质损耗口径（官方 RF 材料库 rf_lib.mph dmodel 实录，本地解包存档）：
# 损耗介质的属性组类型串
# "LossTangentDF"（Loss tangent, dissipation factor），组内属性 epsilonPrim
# （相对介电常数实部）+ tanDelta（损耗角正切）；def 组不再设 relpermittivity
# （Rogers 材料实录：def 组仅 relpermeability+electricconductivity）。emw 波动
# 方程特征按 *_mat="from_mat" 自动消费该组（tem_via dmodel wee1 属性块实录）。
MATERIAL_GROUP_LOSS_TANGENT = "LossTangentDF"
# 分域网格（真机验证方案）：全局粗、走线区/基板中块细。
# 全局 0.15mm 会撑爆装配内存（run3 实证 OOM）；extra_params 的 mesh_scale
# （默认 1.0）可整体缩放做网格收敛研究。
MLINE_MESH_HMAX: dict[str, float] = {
  "global": 2.0, "subM": 0.18, "subLR": 0.4, "airM": 0.8,
}

SUPPORTED_TEMPLATES: tuple[str, ...] = ("parallel_plate", "mline")

# ── 多物理扩展（a6-mwoven：官方 Microwave Oven 例复现， A6 / D3-2）──
# 加性扩展：在原「emw 频域 S 参数」链路之外，支持 emw + 传热（+ 结构）多物理、
# Frequency-Stationary / Frequency-Transient study、体积热源与温度场提取。
# **每个 API 类型串/属性名逐条对照本机 COMSOL 6.3 官方例与官方 API 清单实录**
# （禁止凭想象写 API，铁律 1c/#215）：
#  * Physics op="HeatTransfer"(tag ht) / Port(op "Port") / Impedance /
#   SymmetryPlane / MultiphysicsCoupling op="ElectromagneticHeating"(tag emh1) /
#   StudyFeature op="Frequency"/"Transient"：
#   applications/RF_Module/Microwave_Heating/microwave_oven.mph 内 dmodel.xml
#   （model 1424，usedlicenses=COMSOL+RF）；
#  * StudyFeature op="Stationary" / TemperatureBoundary / HeatFluxBoundary：
#   applications/Heat_Transfer_Module/Tutorials,_Conduction/cylinder_conduction.mph；
#  * 结果特征类型串 MaxVolume/MinVolume/AvVolume/IntVolume（及属性 expr/unit/
#   data/innerinput）：本机 doc/help/.../com.comsol.help.comsol/
#   comsol_api_results.52.003.html「Commands Grouped by Function」清单
#   + 官方 oven dmodel 的 IntVolume 节点实录；
#  * HeatFluxBoundary 的 HeatFluxType="ConvectiveHeatFlux" 与 h/Text/
#   HeatTransferCoefficientType 属性名：同上 cylinder_conduction.mph 实录。
HT_PHYSICS_TYPE = "HeatTransfer"
HT_PHYSICS_TAG = "ht"
SOLID_PHYSICS_TYPE = "SolidMechanics"
SOLID_PHYSICS_TAG = "solid"
COUPLING_TYPE = "ElectromagneticHeating" # 官方 oven dmodel MultiphysicsCoupling op
COUPLING_TAG = "emh1"
STUDY_STEP_FREQUENCY = "Frequency"
STUDY_STEP_STATIONARY = "Stationary"
# D14 stage-2 热漂移 study 步（官方例 cavity_filter_thermal_expansion.mph
# study 步 op 实录，官方例解包存档）
STUDY_STEP_EIGENFREQUENCY = "Eigenfrequency"
STUDY_STEP_TRANSIENT = "Transient" # 时间步类型串（官方 oven StudyFeature op），非 "TimeDependent"
HEAT_FLUX_CONVECTIVE = "ConvectiveHeatFlux"
SUPPORTED_MULTIPHYSICS: tuple[str, ...] = ("emw", "ht", "solid")
SUPPORTED_STUDY_KINDS: tuple[str, ...] = (
  "frequency", "frequency_stationary", "frequency_transient",
)
# 结果特征类型（体积积分/极值/均值/边界积分/点评估）
RESULT_INT_VOLUME = "IntVolume"
RESULT_MAX_VOLUME = "MaxVolume"
RESULT_MIN_VOLUME = "MinVolume"
RESULT_AV_VOLUME = "AvVolume"
# d3-2 温度场验证口径补齐：边界积分（稳态能量闭合 ∮ht.ntflux dS）与
# 点评估（官方三维截点位中心温度）——类型串逐条本机官方 API 清单实录
# （doc/help/.../comsol_api_results.52.003.html「Commands Grouped by Function」）；
# CutPoint3D 的属性名 pointx/pointy/pointz（官方截点位 wo/2, 0, rpot+bp+hp）
# 实录官方 oven dmodel.xml DatasetFeature op="CutPoint3D"。
RESULT_INT_SURFACE = "IntSurface"
RESULT_EVAL_POINT = "EvalPoint"
DATASET_CUT_POINT_3D = "CutPoint3D"

# ── 进程级资源（license 席位 / 单 JVM）────────────────────────────────────────
_SOLVE_LOCK = threading.Lock() # 同时刻只允许一个求解（每次求解占一席）
_CLIENT_LOCK = threading.Lock()
_CLIENT: Any | None = None # 进程内唯一 MPh Client（JPype 单 JVM，不可二次启动）


def mph_installed() -> bool:
  """MPh 是否可导入（不触发 import，避免误启 JVM）。"""
  return importlib.util.find_spec("mph") is not None


def get_shared_client(version: str = COMSOL_VERSION_PIN, cores: int = 2) -> Any:
  """进程级 MPh Client 单例；首次调用起 comsolmphserver（显式钉版本）。

  JPype 一个进程只能起一个 JVM——第二次调用直接复用首个 Client，
  version/cores 以首次为准（不同请求不能改）。
  """
  global _CLIENT
  with _CLIENT_LOCK:
    if _CLIENT is None:
      import mph

      _CLIENT = mph.start(version=version, cores=cores)
    return _CLIENT


# ── 纯函数：参数映射 / 闭式 / 判据（确定性内核，可无 COMSOL 单测）──────────────

def normalize_parallel_plate_params(params: dict[str, Any] | None) -> dict[str, float]:
  """平行板模板参数规范化：补默认、转 float、正数校验。"""
  spec = dict(PARALLEL_PLATE_DEFAULTS)
  for key, value in (params or {}).items():
    if key in PARALLEL_PLATE_DEFAULTS:
      spec[key] = float(value)
  for key, value in spec.items():
    if not math.isfinite(value) or value <= 0:
      raise ValueError(f"parallel_plate 参数 {key} 必须为正数，得到 {value}")
  return spec


def parallel_plate_z0(width_mm: float, height_mm: float, eps_r: float) -> float:
  """平行板 TEM 线特性阻抗闭式：Z0 = η0/√εr · (H/W)。"""
  return ETA0 / math.sqrt(eps_r) * (height_mm / width_mm)


def to_comsol_parameters(spec: dict[str, float]) -> dict[str, str]:
  """rfauto 参数（mm/Ω）→ COMSOL 全局参数表达式（带单位字符串）。

  几何/端口一律引用参数名（L/W/H/eps_r/Zref），改参数不必重建几何。
  """
  return {
    "L": f"{spec['length_mm']:g}[mm]",
    "W": f"{spec['width_mm']:g}[mm]",
    "H": f"{spec['height_mm']:g}[mm]",
    "eps_r": f"{spec['eps_r']:g}",
    "Zref": f"{spec['z_ref_ohm']:g}[ohm]",
  }


def format_plist(freqs_ghz: list[float] | np.ndarray) -> str:
  """频点列表 → FrequencyDomain study ``plist`` 字符串（显式单位，避免频率单位歧义）。"""
  return " ".join(f"{float(f):g}[GHz]" for f in freqs_ghz)


def resolve_freq_points(config: EMSolverConfig,
            params: dict[str, Any] | None) -> list[float]:
  """频点：params['freq_ghz'] 显式列表优先，否则按 freq_range_ghz 等分
  ``extra_params['n_freq']``（默认 5）个点。"""
  explicit = (params or {}).get("freq_ghz")
  if explicit is not None:
    pts = [float(f) for f in np.atleast_1d(np.asarray(explicit, dtype=float))]
    if not pts or any(f <= 0 for f in pts):
      raise ValueError("freq_ghz 必须为非空正数列表")
    return pts
  n = int((config.extra_params or {}).get("n_freq", 5))
  lo, hi = config.freq_range_ghz
  return [float(f) for f in np.linspace(lo, hi, max(n, 1))]


def tl_section_sparams(freq_ghz: np.ndarray, eps_eff: float, z_line: float,
            length_mm: float, z_ref: float = 50.0) -> np.ndarray:
  """无耗均匀传输线段闭式 S 矩阵（ABCD→S，按 z_ref 归一）。shape (n,2,2)。"""
  f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
  beta_l = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / C0 * (length_mm * 1e-3)
  a = np.cos(beta_l)
  b = 1j * z_line * np.sin(beta_l)
  c = 1j * np.sin(beta_l) / z_line
  d = a
  denom = a * z_ref + b + c * z_ref * z_ref + d * z_ref
  s = np.zeros((len(f_hz), 2, 2), dtype=complex)
  s[:, 0, 0] = (a * z_ref + b - c * z_ref * z_ref - d * z_ref) / denom
  s[:, 1, 1] = s[:, 0, 0]
  s[:, 1, 0] = 2.0 * z_ref / denom
  s[:, 0, 1] = s[:, 1, 0]
  return s


def parallel_plate_closed_form(spec: dict[str, float],
                freq_ghz: np.ndarray) -> np.ndarray:
  """平行板 TEM 线闭式 S 矩阵（εeff=εr 精确，Z0 由几何闭式）。"""
  z0 = parallel_plate_z0(spec["width_mm"], spec["height_mm"], spec["eps_r"])
  return tl_section_sparams(freq_ghz, spec["eps_r"], z0, spec["length_mm"],
               z_ref=spec["z_ref_ohm"])


def normalize_mline_params(params: dict[str, Any] | None) -> dict[str, float]:
  """mline 锚模板参数规范化：补默认、转 float、正数校验。"""
  spec = dict(MLINE_DEFAULTS)
  for key, value in (params or {}).items():
    if key in MLINE_DEFAULTS:
      spec[key] = float(value)
  for key, value in spec.items():
    if not math.isfinite(value) or value <= 0:
      raise ValueError(f"mline 参数 {key} 必须为正数，得到 {value}")
  return spec


def normalize_port_chain(extra_params: dict[str, Any] | None) -> str:
  """mline 端口链规范化：``mline_port_chain`` ∈ {"lumped", "tem"}（默认
  lumped 保持既有集总端口链路零回归；tem=数值 TEM 边界模端口完整链）。"""
  chain = str((extra_params or {}).get("mline_port_chain", "lumped"))
  if chain not in MLINE_PORT_CHAINS:
    raise ValueError(
      f"不支持 mline_port_chain {chain!r}（支持: {MLINE_PORT_CHAINS}）")
  return chain


def normalize_loss_tangent(extra_params: dict[str, Any] | None) -> float | None:
  """基板 tanδ 规范化：``loss_tangent`` 缺省 None=无耗（既有口径零回归）；
  给正数即按官方 LossTangentDF 组建模（MLINE_TAN_D=rogers4350b 表值
  0.0037）。0 或负数直接判废（损耗角正切非负、且 0 应用 None 表达）。"""
  raw = (extra_params or {}).get("loss_tangent")
  if raw is None:
    return None
  tan_d = float(raw)
  if not math.isfinite(tan_d) or tan_d <= 0:
    raise ValueError(f"loss_tangent 必须为正数（无耗传 None），得到 {raw!r}")
  return tan_d


def mline_closed_form(width_mm: float, freq_ghz: float, eps_r: float,
           sub_h_mm: float,
           tan_d: float = MLINE_TAN_D) -> tuple[float, float]:
  """mline 锚闭式参考：skrf MLine（Hammerstad-Jensen）→ (Z0, εeff)。

  与 WP1.2 引擎基准（scripts/engine_benchmark_mline.py）同一条 HJ 链路
  （core/synthesis.forward_z0），三源对拍的金标准闭式侧（#189：|Δ|≤2%）。
  tan_d 取 rogers4350b 材料表值——基准锚值 2.85264 即含损耗的 HJ 口径
  （无耗 Stackup 会得 2.85812，Δ0.2%），保持三引擎同一参照系。
  """
  from rfauto.core.synthesis import Stackup, forward_z0

  stack = Stackup(name="mline_custom", epsilon_r=eps_r,
          thickness_mm=sub_h_mm, loss_tangent=tan_d)
  return forward_z0(width_mm, freq_ghz, stack)


def to_comsol_parameters_mline(spec: dict[str, float]) -> dict[str, str]:
  """mline 参数（mm/Ω）→ COMSOL 全局参数表达式（带单位字符串）。"""
  return {
    "W": f"{spec['w_mm']:g}[mm]",
    "L": f"{spec['line_len_mm']:g}[mm]",
    "HS": f"{spec['sub_h_mm']:g}[mm]",
    "epsr": f"{spec['eps_r']:g}",
    "Zref": f"{spec['z_ref_ohm']:g}[ohm]",
  }


def extract_eps_eff(freq_ghz: np.ndarray, s21: np.ndarray, length_mm: float) -> float:
  """由 S21 解缠相位斜率反推有效介电常数：φ=-βL，β=2πf√εeff/c。"""
  f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
  if f_hz.size < 2:
    raise ValueError("至少需要 2 个频点才能拟合相位斜率")
  phase = np.unwrap(np.angle(np.asarray(s21)))
  slope = float(np.polyfit(f_hz, phase, 1)[0]) # rad/Hz
  sqrt_eps = -slope * C0 / (2.0 * np.pi * length_mm * 1e-3)
  return float(sqrt_eps * sqrt_eps)


def transmission_health(freq_ghz: np.ndarray, s: np.ndarray, *,
            s21_min_lin: float = 0.95, s11_max_db: float = -20.0,
            passivity_tol: float = 0.02) -> dict[str, Any]:
  """传输结构健康判据（确定性）：无源性 |S|≤1、|S21|≈1、|S11| 显著低。

  任一 |S|>1+tol 视为非物理（建模错误信号，回官方文档核对而不是调参）。
  """
  s = np.asarray(s)
  mag = np.abs(s)
  max_abs = float(mag.max()) if mag.size else float("nan")
  s21_min = float(np.abs(s[:, 1, 0]).min())
  s11_worst_db = float(20.0 * np.log10(max(float(np.abs(s[:, 0, 0]).max()), 1e-12)))
  checks = {
    "passivity": bool(max_abs <= 1.0 + passivity_tol),
    "s21_transmission": bool(s21_min >= s21_min_lin),
    "s11_return_loss": bool(s11_worst_db <= s11_max_db),
  }
  return {
    "ok": all(checks.values()),
    "n_freq": len(np.atleast_1d(freq_ghz)),
    "max_abs_s": max_abs,
    "s21_min_lin": s21_min,
    "s11_worst_db": s11_worst_db,
    "checks": checks,
  }


# ── 多物理纯函数（确定性内核；可无 COMSOL 单测）──────────────────────────────
# a6-mwoven：官方 Microwave Oven 例复现所需的多物理 study/温度/能量判据。
# 所有数值口径都写进 docstring 并注明独立来源；调用方只消费返回值，不在
# LLM/编排层产生物理数字（铁律 7）。

def normalize_multiphysics(physics: Any = None) -> tuple[str, ...]:
  """多物理接口清单规范化（去重保序 + 白名单校验）。

  emw 是热源前置（单向耦合 ElectromagneticHeating 的 EMHeat_physics），
  必选；ht/solid 可选。默认 ("emw", "ht")。
  """
  items = [str(p) for p in (("emw", "ht") if physics is None else physics)]
  unknown = [p for p in items if p not in SUPPORTED_MULTIPHYSICS]
  if unknown:
    raise ValueError(f"不支持的多物理接口 {unknown}（支持: {SUPPORTED_MULTIPHYSICS}）")
  if PHYSICS_TAG not in items:
    raise ValueError("多物理清单必须含 emw（频域电磁=热源前置）")
  out: list[str] = []
  for item in items:
    if item not in out:
      out.append(item)
  return tuple(out)


def study_step_plan(study_kind: str) -> tuple[tuple[str, str], ...]:
  """study 步序列 (tag, COMSOL study 步类型串)，顺序=求解顺序。

  类型串逐条官方实录：Frequency（#217②，官方 microwave_oven.mph）、
  Stationary（Heat_Transfer_Module cylinder_conduction.mph）、
  Transient（官方 oven 时间步 op，**不是** "TimeDependent"）。
  Frequency-Stationary 即 COMSOL 预设 "Frequency-Stationary, One-Way
  Electromagnetic Heating"（emw 频域 → ht 稳态；单向耦合）。
  """
  kind = str(study_kind)
  if kind == "frequency":
    return (("freq", STUDY_STEP_FREQUENCY),)
  if kind == "frequency_stationary":
    return (("freq", STUDY_STEP_FREQUENCY), ("stat", STUDY_STEP_STATIONARY))
  if kind == "frequency_transient":
    return (("freq", STUDY_STEP_FREQUENCY), ("time", STUDY_STEP_TRANSIENT))
  raise ValueError(f"不支持的 study_kind {kind!r}（支持: {SUPPORTED_STUDY_KINDS}）")


def temperature_summary(t_celsius: Any) -> dict[str, Any]:
  """温度场（degC 数组）确定性统计：max/min/mean + 非有限值守卫。"""
  arr = np.asarray(list(t_celsius), dtype=float).ravel()
  if arr.size == 0:
    raise ValueError("温度场为空，无法统计")
  finite = np.isfinite(arr)
  if not bool(finite.all()):
    raise ValueError(f"温度场含非有限值 {int((~finite).sum())} 个（解发散信号）")
  return {"n_points": int(arr.size), "t_max_c": float(arr.max()),
      "t_min_c": float(arr.min()), "t_mean_c": float(arr.mean())}


def temperature_record(t_max_c: float, t_min_c: float, t_avg_c: float,
            *, tol: float = 1e-6) -> dict[str, Any]:
  """COMSOL 体积极值/均值特征读回的标量三元组做有限性与序关系守卫。

  序关系 t_min ≤ t_avg ≤ t_max 必须成立（tol 只吸收浮点/插值舍入）。
  """
  values = {"t_max_c": float(t_max_c), "t_min_c": float(t_min_c),
       "t_avg_c": float(t_avg_c)}
  bad = [k for k, v in values.items() if not math.isfinite(v)]
  if bad:
    raise ValueError(f"温度取值非有限: {bad}")
  if not (values["t_min_c"] - tol <= values["t_avg_c"] <= values["t_max_c"] + tol):
    raise ValueError(f"温度序关系不成立: {values}")
  return values


def energy_balance(p_input_w: float, p_absorbed_w: float) -> dict[str, Any]:
  """能量守恒检查：反射功率 = 输入 − 吸收；吸收分数 ∈ [0,1]（无源性守卫）。

  conserved=域内吸收不超过输入（无源、无增益）；passive 额外放宽
  1e-6 浮点余量。官方 oven 例：1 kW 输入中约 631 W 被土豆吸收（≈63%，
  其余主要从端口反射）——本函数是那条口径的确定性判据。
  """
  p_in = float(p_input_w)
  p_abs = float(p_absorbed_w)
  if not math.isfinite(p_in) or not math.isfinite(p_abs):
    raise ValueError("功率必须为有限值")
  if p_in <= 0:
    raise ValueError(f"输入功率必须为正，得到 {p_in}")
  frac = p_abs / p_in
  return {"p_input_w": p_in, "p_absorbed_w": p_abs,
      "p_reflected_w": p_in - p_abs, "absorbed_fraction": frac,
      "passive": bool(-1e-6 <= frac <= 1.0 + 1e-6),
      "conserved": bool(0.0 <= frac <= 1.0)}


def relative_deviation(value: float, reference: float) -> float:
  """相对偏差 |value − reference| / |reference|（reference=0 抛错，防静默通过）。"""
  ref = float(reference)
  if ref == 0.0:
    raise ValueError("参考值不能为 0（相对偏差无定义）")
  return abs(float(value) - ref) / abs(ref)


def reference_agreement(value: float, reference: float,
            tol: float = 0.05) -> dict[str, Any]:
  """与独立来源参考值的一致性判定（默认 ±5% 验收门）。

  参考值必须是外部独立来源（官方例报告值/教科书闭式/文献），禁止拿本模型
  自身输出当裁判（#118/#122）。
  """
  dev = relative_deviation(value, reference)
  return {"value": float(value), "reference": float(reference),
      "rel_deviation": dev, "tolerance": float(tol),
      "ok": bool(dev <= float(tol))}


def sphere_uniform_source_center_excess(q_vol_w_m3: float, radius_m: float,
                    k_w_mk: float,
                    h_conv: float | None = None) -> float:
  """球体均匀体积热源稳态中心温升闭式（**独立教科书裁判**，非自证）。

  来源：Incropera & DeWitt《Fundamentals of Heat and Mass Transfer》
  球坐标一维稳态导热（表面定温：T_center−T_s=q·a²/(6k)）叠加表面能量
  平衡（牛顿对流：T_s−T_∞=q·a/(3h)）；亦见 Carslaw & Jaeger
  《Conduction of Heat in Solids》§9.1。合式：

    T_center − T_∞ = q·a²/(6k) [+ q·a/(3h)]

  仅作数量级裁判：真实微波源在土豆内中心峰化（官方例 Figure 2），均匀源
  是理想化下界估计，实测中心温度应不低于该值。
  """
  q = float(q_vol_w_m3)
  a = float(radius_m)
  k = float(k_w_mk)
  if not math.isfinite(q) or a <= 0.0 or k <= 0.0:
    raise ValueError(f"球体裁判参数非法: q={q}, a={a}, k={k}")
  excess = q * a * a / (6.0 * k)
  if h_conv is not None:
    h = float(h_conv)
    if not math.isfinite(h) or h <= 0.0:
      raise ValueError(f"对流系数必须为正有限值，得到 {h}")
    excess += q * a / (3.0 * h)
  return float(excess)


def transient_energy_anchor(p_absorbed_w: float, duration_s: float,
              mass_kg: float, cp_j_kg_k: float,
              t_mean_c: float, t_init_c: float,
              *, tol: float = 0.05) -> dict[str, Any]:
  """绝热瞬态能量守恒**自洽锚**（替代锚，如实标注：非官方标量）。

  口径：∫P dt = m·Cp·ΔT_mean——单向耦合（热源不随 T 变）+ 材料参数温度
  无关（官方例明示，故 P_abs 恒定）+ 绝热（ht 无任何热汇；官方 oven 的
  Transient 步只有初值 T0，无换热边界）时，能量守恒要求平均温升精确
  等于 P_abs·Δt/(m·Cp)，偏差只来自时间离散/求解器容差。

  **为什么是替代锚**：官方例温度场只有 Figure 3 瞬态中心温度曲线（图，
  无标量数值），全文唯一温度数字"中心的温度最终达到 100℃"是沸腾叙述
  且明示模型未建该非线性——无任何官方标量可对（D3-2 收口结论，
  本机官方 PDF/HTML/姊妹模型 rotating_microwave_oven 逐一检索）。
  """
  p_abs = float(p_absorbed_w)
  dt = float(duration_s)
  m = float(mass_kg)
  cp = float(cp_j_kg_k)
  t_mean = float(t_mean_c)
  t_init = float(t_init_c)
  for name, value in (("p_absorbed_w", p_abs), ("duration_s", dt),
            ("mass_kg", m), ("cp_j_kg_k", cp)):
    if not math.isfinite(value) or value <= 0.0:
      raise ValueError(f"能量锚参数 {name} 必须为正有限值，得到 {value}")
  if not (math.isfinite(t_mean) and math.isfinite(t_init)):
    raise ValueError(f"温度必须为有限值: t_mean={t_mean}, t_init={t_init}")
  predicted = p_abs * dt / (m * cp)
  measured = t_mean - t_init
  rel = abs(measured - predicted) / predicted
  return {
    "anchor": "self_consistency_energy_adiabatic",
    "official": False,
    "note": ("自洽锚非官方：∫Pdt = m·Cp·ΔT_mean（绝热单向瞬态能量守恒）；"
         "官方例无温度场标量（仅 Figure 3 瞬态曲线）"),
    "predicted_delta_t_k": predicted,
    "measured_delta_t_k": measured,
    "rel_deviation": rel,
    "tolerance": float(tol),
    "ok": bool(rel <= float(tol)),
  }


def energy_closure(p_absorbed_w: float, p_boundary_w: float,
          *, tol: float = 0.05) -> dict[str, Any]:
  """稳态能量闭合**自洽锚**（替代锚，如实标注：非官方标量）。

  口径：稳态下体积源吸收功率 = 边界净流出热流——∮ht.ntflux dS vs
  ∫ht.Qtot dV（ht.ntflux=Total Normal Heat Flux，Heat Transfer 接口
  官方变量，heat_ug_modeling.06.07.html 实录）。偏差只来自求解器残差
  （稳态解的能量不闭合即病态解信号）。
  """
  p_abs = float(p_absorbed_w)
  p_bnd = float(p_boundary_w)
  if not math.isfinite(p_abs) or not math.isfinite(p_bnd):
    raise ValueError("功率必须为有限值")
  if p_abs <= 0.0:
    raise ValueError(f"吸收功率必须为正，得到 {p_abs}")
  rel = abs(p_bnd - p_abs) / p_abs
  return {
    "anchor": "self_consistency_energy_stationary_closure",
    "official": False,
    "note": ("自洽锚非官方：∮ht.ntflux dS = ∫ht.Qtot dV（稳态能量闭合）；"
         "官方例无温度场标量（仅 Figure 3 瞬态曲线）"),
    "p_absorbed_w": p_abs,
    "p_boundary_out_w": p_bnd,
    "rel_deviation": rel,
    "tolerance": float(tol),
    "ok": bool(rel <= float(tol)),
  }


# ── 适配器 ────────────────────────────────────────────────────────────────────

class ComsolAdapter(EMSolverAdapter):
  """COMSOL RF Module 频域求解适配器（EMSolverAdapter 契约）。

  生命周期：connect（只查可用性，不起 server/不占 license）→ build_geometry
  （规范化模板参数、落 spec 证据）→ solve（串行锁内：起/复用 Client → 建模
  → 求解 → EvalGlobal 取 S）→ get_sparams → close（移除模型，Client 常驻）。

  extra_params：comsol_version（默认 "6.3"）、cores（默认 2）、comsol_root、
  n_freq、save_mph（默认 False）。
  """

  # 参数语义清单（#154 教训）：每个模板的几何参数物理角色显式声明
  param_semantics: ClassVar[dict[str, dict[str, str]]] = {
    "parallel_plate": {
      "length_mm": "平行板 TEM 线长（x 向传播长度，决定 S21 相位 -βL）",
      "width_mm": "板宽（y 向，与 H 一起决定 Z0）",
      "height_mm": "板间距（z 向，E 极化方向；集总端口电压路径）",
      "eps_r": "板间介质相对介电常数（TEM：εeff=εr 精确）",
      "z_ref_ohm": "集总端口 Cable 参考阻抗 Zref（S 参量归一基准）",
    },
    "mline": {
      "w_mm": "走线宽（skrf HJ 综合：50Ω@rogers4350b=1.113mm，权威口径表 §1）",
      "line_len_mm": "两端口间线长（S21 相位斜率 → εeff，β 金标准 #162）",
      "eps_r": "基板相对介电常数（rogers4350b=3.66）",
      "sub_h_mm": "基板厚度 mm（rogers4350b=0.508）",
      "z_ref_ohm": "集总端口 Cable 参考阻抗 Zref（S 参量归一基准）",
    },
  }

  # A5 能力声明（如实，逐行核对 + 真机过锚）：
  #  - 端口：LumpedPort（既有链）+ 数值 TEM 边界模端口完整链
  #   （mline_port_chain="tem"，真机三源对拍双锚 PASS，
  #   三档网格收敛存档）→ wave=True；
  #  - 材料：PEC 板/走线 + 无耗/有耗介质（loss_tangent>0 走官方
  #   LossTangentDF 组，tanδ 建模真机验证）；
  #  - 场导出：temperature_field/evaluate_volume_series 体积场提取（多物理，
  #   best-effort）→ field_export=True；远场 nf2ff 无实现 → False；
  #  - Touchstone：_export_touchstone（原生导出 + skrf 兜底）→ True；
  #  - 收敛报告：直接法无自适应 passes → False；
  #  - optimetrics：仅有端口激励 Parametric 扫描（PortSweepSettings），非通用
  #   优化驱动 → False；
  #  - 并行：mph.start(cores=self._cores) 共享内存多核 → shared_memory；
  #  - license：每次 solve 占一个 RF 席位（模块级串行锁）→ requires_license=True。
  CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
    solver_type="comsol",
    supports_wave_port=True,
    supports_lumped_port=True,
    supports_field_export=True,
    supports_convergence_report=False,
    supports_touchstone_export=True,
    supports_headless_solve=True,
    supports_optimetrics=False,
    dimension="3d",
    material_models=("pec", "lossless_dielectric", "lossy_dielectric"),
    parallel_backends=("shared_memory",),
    supports_sar=False,
    supports_nf2ff=False,
    supports_lumped_elements=False,
    supported_templates=SUPPORTED_TEMPLATES,
    requires_license=True,
    availability_gate="mph+comsol_root",
  )

  def __init__(self, config: EMSolverConfig,
         client_factory: Callable[[], Any] | None = None):
    super().__init__(config)
    ep = config.extra_params or {}
    self._version = str(ep.get("comsol_version", COMSOL_VERSION_PIN))
    self._cores = int(ep.get("cores", 2))
    self._comsol_root = str(
      ep.get("comsol_root")
      or os.environ.get("RFAUTO_COMSOL_ROOT")
      or DEFAULT_COMSOL_ROOT
    )
    self._client_factory = client_factory or (
      lambda: get_shared_client(self._version, self._cores))
    self._working_dir = Path(config.working_dir or "runs/comsol")
    self._template: str | None = None
    self._spec: dict[str, float] | None = None
    self._freqs_ghz: list[float] | None = None
    self._port_sweep: bool = False
    self._port_chain: str = "lumped"
    self._loss_tangent: float | None = None
    self._result: EMSolverResult | None = None
    self._model: Any | None = None
    self._client: Any | None = None
    self._model_path: Path | None = None
    self._resolve_eval_seq = 0 # 单频重解 EvalGlobal tag 唯一化计数器

  # ── 可用性 / 连接 ────────────────────────────────────────────────────────
  def is_available(self) -> bool:
    """MPh 可导入且 COMSOL 安装根目录存在（不起 server，不占 license）。"""
    return mph_installed() and Path(self._comsol_root).exists()

  def connect(self) -> bool:
    """连接=可用性确认。server/license 推迟到 solve（席位只在真求解时占）。"""
    if not self.is_available():
      return False
    self._connected = True
    return True

  # ── 建模输入 ─────────────────────────────────────────────────────────────
  def build_geometry(self, geometry: dict[str, Any]) -> bool:
    """规范化模板参数并落 spec 证据（真正的 COMSOL 建模在 solve 的锁内进行）。

    geometry: {"template": "parallel_plate"|"mline", "params": {...,
          freq_ghz: [...]}, "port_sweep": bool}
    port_sweep=True 时 solve 走官方端口扫描（Parametric 外层扫 PortName），
    产全 S 矩阵与 Touchstone（否则单激励只测 S11/S21，互易/对称补齐）。
    """
    if not self._connected:
      return False
    template = str(geometry.get("template", "parallel_plate"))
    if template not in SUPPORTED_TEMPLATES:
      logger.error("COMSOL 适配器暂不支持模板 %s（支持: %s）",
             template, SUPPORTED_TEMPLATES)
      return False
    params = geometry.get("params") or {}
    try:
      if template == "mline":
        self._spec = normalize_mline_params(params)
        self._port_chain = normalize_port_chain(self._config.extra_params)
        self._loss_tangent = normalize_loss_tangent(self._config.extra_params)
      else:
        self._spec = normalize_parallel_plate_params(params)
      self._freqs_ghz = resolve_freq_points(self._config, params)
    except (TypeError, ValueError) as exc:
      logger.error("COMSOL 参数无效: %s", exc)
      return False
    self._template = template
    self._port_sweep = bool(geometry.get("port_sweep")
                or (self._config.extra_params or {}).get("port_sweep"))
    self._working_dir.mkdir(parents=True, exist_ok=True)
    spec_doc: dict[str, Any] = {
      "template": template,
      "params": self._spec,
      "freq_ghz": self._freqs_ghz,
      "comsol_parameters": (to_comsol_parameters_mline(self._spec)
                 if template == "mline"
                 else to_comsol_parameters(self._spec)),
      "comsol_version_pin": self._version,
      "port_sweep": self._port_sweep,
    }
    if template == "mline":
      f_mid = float(np.median(self._freqs_ghz))
      z0_hj, eps_hj = mline_closed_form(
        self._spec["w_mm"], f_mid, self._spec["eps_r"],
        self._spec["sub_h_mm"])
      spec_doc["judge_freq_ghz"] = f_mid
      spec_doc["closed_form_hj"] = {"z0_ohm": round(z0_hj, 4),
                     "eps_eff": round(eps_hj, 5)}
      spec_doc["port_chain"] = self._port_chain
      spec_doc["loss_tangent"] = self._loss_tangent
      spec_doc["note"] = (
        "FEM 域=空气盒+Scattering 开放边界（官方例 "
        "microstrip_line_crosstalk 同手法；空气盒顶隙 3.5mm——0.8mm 时 "
        "SBC 电容加载使 εeff +14%，run5 实证），走线=零厚度 PEC 片"
        "（WorkPlane 印痕），端口面=内部端面跨「地面 PEC↔走线底 PEC 片」"
        "且离吸收边界 ≥3mm（真机实证：端口不得邻接吸收特征）；"
        + (
          "数值 TEM 边界模端口完整链（官方例 cpw_numeric_tem_port/"
          "microstrip_line_tem_via 同构：Port PortType=TEM+numericTEM"
          "=1，study=[bma, freq]，端口 StudyStep 解引用边界模分析步）；"
          if self._port_chain == "tem" else
          "集总端口 Uniform（准静态场形与微带模失配，εeff 系统性偏高"
          " +4.8% 已实证）；")
        + ("基板损耗按官方 RF 材料库 LossTangentDF 组建模"
          f"（epsilonPrim+tanDelta={self._loss_tangent}）。"
          if self._loss_tangent is not None else
          "无耗建模（基板 tanδ 不建，对 εeff/|S11| 影响 ≪ 锚 ±2% 门）。"))
    else:
      spec_doc["closed_form_z0_ohm"] = parallel_plate_z0(
        self._spec["width_mm"], self._spec["height_mm"], self._spec["eps_r"])
    (self._working_dir / "comsol_spec.json").write_text(
      json.dumps(spec_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return True

  # ── COMSOL 建模（API 逐条对照官方实录，见模块 docstring）───────────────────
  @staticmethod
  def _box_selection(comp: Any, tag: str, lo: tuple[float, float, float],
            hi: tuple[float, float, float]) -> None:
    """边界（entitydim=2）Box 选择集：面完全落在薄盒内（condition=inside）。

    坐标单位随几何序列（mm）——Programming Reference Manual Table 2-125。
    """
    sel = comp.selection().create(tag, "Box")
    # JPype 陷阱：Python int 在 set(String,int)/set(String,boolean) 间二义，
    # 整数属性一律传字符串（COMSOL 属性接受字符串表达式）
    sel.set("entitydim", "2")
    sel.set("xmin", lo[0])
    sel.set("ymin", lo[1])
    sel.set("zmin", lo[2])
    sel.set("xmax", hi[0])
    sel.set("ymax", hi[1])
    sel.set("zmax", hi[2])
    sel.set("condition", "inside")

  @staticmethod
  def _dielectric_material(comp: Any, tag: str, selection: str,
               eps_expr: str,
               tan_d: float | None) -> Any:
    """介质材料：无耗走 def 组 relpermittivity（既有口径零回归）；给 tan_d
    则按官方 RF 材料库 LossTangentDF 组口径（rf_lib.mph dmodel 实录）：
    propertyGroup().create("LossTangentDF") 建「损耗角正切，耗散因子」组，
    epsilonPrim=相对介电常数实部、tanDelta=损耗角正切；def 组不再设
    relpermittivity（Rogers 材料实录：def 组仅 relpermeability+
    electricconductivity）。emw 波动方程特征 *_mat="from_mat" 自动消费
    （tem_via dmodel wee1 属性块实录）。"""
    mat = comp.material().create(tag, "Common")
    mat.selection().named(selection)
    grp = mat.propertyGroup("def") # ApplicationProgrammingGuide p.52
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])
    if tan_d is None:
      grp.set("relpermittivity", [eps_expr])
    else:
      # 真机实证（tem_probe）：6.3 客户端 MaterialModelList
      # 无单参 create（javadoc 摘要与实现不符）——用两参 (tag, type)，
      # 官方材料库 dmodel 实录 op=tag=type 同名 "LossTangentDF"。
      lt = mat.propertyGroup().create(MATERIAL_GROUP_LOSS_TANGENT,
                      MATERIAL_GROUP_LOSS_TANGENT)
      lt.set("epsilonPrim", [eps_expr])
      lt.set("tanDelta", [repr(float(tan_d))])
    return mat

  def _build_model(self, client: Any) -> Any:
    """按模板分发建模（每处 API 对照官方实录，见模块 docstring）。"""
    if self._template == "mline":
      return self._build_mline(client)
    return self._build_parallel_plate(client)

  def _build_parallel_plate(self, client: Any) -> Any:
    """在 Client 内构建平行板 TEM 模型（几何/材料/物理/网格/study）。"""
    assert self._spec is not None and self._freqs_ghz is not None
    spec = self._spec
    length, width, height = spec["length_mm"], spec["width_mm"], spec["height_mm"]
    tol = 1e-3 * min(length, width, height)

    model = client.create(f"rfauto_parallel_plate_{int(time.time())}")
    j = model.java
    for name, expr in to_comsol_parameters(spec).items():
      j.param().set(name, expr)

    j.component().create("comp1", True)
    comp = j.component("comp1")
    geom = comp.geom().create("geom1", 3)
    geom.lengthUnit("mm")
    blk = geom.create("blk1", "Block")
    blk.set("size", ["L", "W", "H"])
    geom.run()

    # 材料：Basic(def) 属性组（ApplicationProgrammingGuide p.52 惯用法）
    mat = comp.material().create("mat1", "Common")
    mat.selection().all()
    grp = mat.propertyGroup("def")
    grp.set("relpermittivity", ["eps_r"])
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])

    # 六个面的 Box 选择集（薄盒 inside，避免依赖 Block 面编号假设）
    full_lo = (-tol, -tol, -tol)
    full_hi = (length + tol, width + tol, height + tol)
    self._box_selection(comp, "sel_z0", full_lo, (full_hi[0], full_hi[1], tol))
    self._box_selection(comp, "sel_zH", (full_lo[0], full_lo[1], height - tol), full_hi)
    self._box_selection(comp, "sel_x0", full_lo, (tol, full_hi[1], full_hi[2]))
    self._box_selection(comp, "sel_xL", (length - tol, full_lo[1], full_lo[2]), full_hi)
    self._box_selection(comp, "sel_y0", full_lo, (full_hi[0], tol, full_hi[2]))
    self._box_selection(comp, "sel_yW", (full_lo[0], width - tol, full_lo[2]), full_hi)

    # 物理场：EMW 频域；板=PEC、侧壁=PMC（User's Guide p.143 对称切割口径）、
    # 两端=集总端口（Uniform/Cable/Zref；仅端口 1 激励——S 参量口径 p.145）
    phys = comp.physics().create(PHYSICS_TAG, PHYSICS_TYPE, "geom1")
    for tag, sel in (("pec_bottom", "sel_z0"), ("pec_top", "sel_zH")):
      pec = phys.create(tag, "PerfectElectricConductor", 2)
      pec.selection().named(sel)
    for tag, sel in (("pmc_y0", "sel_y0"), ("pmc_yW", "sel_yW")):
      pmc = phys.create(tag, "PerfectMagneticConductor", 2)
      pmc.selection().named(sel)
    for tag, sel, name, excite in (("lport1", "sel_x0", "1", "on"),
                    ("lport2", "sel_xL", "2", "off")):
      port = phys.create(tag, "LumpedPort", 2)
      port.selection().named(sel)
      port.set("PortName", name)
      port.set("PortType", "Uniform")
      port.set("TerminalType", "Cable")
      port.set("Zref", "Zref")
      port.set("PortExcitation", excite)
    if self._port_sweep:
      # 端口扫描：两端口均设为激励候选（solver 逐端口覆盖，官方 p.145）
      phys.feature("lport1").set("PortExcitation", "on")
      phys.feature("lport2").set("PortExcitation", "on")
      j.param().set(self.PORT_SWEEP_PARAM, "1")
      self._apply_port_sweep_settings(phys)

    # 网格：自由四面体 + 自定义最大单元尺寸（mesh_resolution_mm，几何单位 mm）
    mesh = comp.mesh().create("mesh1")
    size = mesh.feature("size")
    size.set("custom", "on")
    size.set("hmax", float(self._config.mesh_resolution_mm))
    mesh.create("ftet1", "FreeTet")
    mesh.run()

    # study：频域步（类型串 "Frequency"，官方例实录；"FrequencyDomain" 在此情景
    # 报"不能创建本操作"，真机实证），plist 显式带单位
    j.study().create(STUDY_TAG)
    freq = j.study(STUDY_TAG).create(FREQ_STEP_TAG, "Frequency")
    freq.set("plist", format_plist(self._freqs_ghz))
    if self._port_sweep:
      self._add_parametric_port_step(j)
    return model

  def _build_mline(self, client: Any) -> Any:
    """在 Client 内构建 mline 锚模型（直微带线，WP2.1 权威口径同锚）。

    官方口径逐条出处（真机验证）：
    - 走线=零厚度 PEC 片：WorkPlane(z=HS)+Rectangle 印痕（官方例
     vivaldi_antenna.mph 同手法）。有限厚 Block 不可用——skrf 实测
     t=0.05mm 已使 εeff -2.0%/Z0 -1.4Ω（本锚 openEMS/HFSS/HJ 闭式
     三方均为零厚度口径）；
    - 开放边界特征类型串 "Scattering"：官方例 microstrip_line_crosstalk
     .mph sctr1 实录（"ScatteringBoundaryCondition" 报未知特征 ID）；
    - 集总端口面=内部端面（跨「地面 PEC↔走线底 PEC 片」，User's Guide
     p.143），且必须离吸收边界 ≥3mm——真机实证："集总端口不应放置在
     任何吸收特征附近"（编译方程检查，run2），故域在端口面外各延
     MLINE_PORT_MARGIN_MM 尾段；
    - 端口扫描：emw prop "PortSweepSettings" + study Parametric 步
     （pname=PortName）——官方例 h_bend_waveguide_3d.mph 实录
     （useSweep=1）。

    已知口径局限（run7 实测，如实记录）：集总端口 Uniform 的准静态场形
    与真实微带模失配（端口结电容）→ εeff 相位斜率系统性偏高
    （+4.8% vs HJ 闭式，超出锚 ±2% 门；run5→7 网格/空气盒细化各仅回
    -0.4%，排除网格/域因素）。tem 链（mline_port_chain="tem"）为该口径
    差的官方修正路径：数值 TEM 边界模端口完整链（本文件常量区实录出处
   ）——真机实证五坑：
    ① Port 特征只能放外部边界（「狭缝条件只能应用于内部边界，或者，
    端口只能放置在外部边界上」）→ 域端=端口面（官方 cpw 例同构）；
    ② StudyStep 解引用须在 bma 步创建后回填（步不存在时 set 报
    「参数值无效」）；③ BoundaryModeAnalysis 步无 plist 属性（频点概念
    在 Frequency 步；模式分析频率属性名=modeFreq）；④ 数值 TEM 端口
    PortType="Numeric"（"TEM" 值=同轴解析型）且必须配
    IntegrationLineforVoltage 电压积分线子特征（缺失 solve 报
    Cmode_1 未定义）；⑤ 每端口一个 bma 步（PortName 属性绑定，官方
    cpw 例 Step1/Step2 同型 dup）。
    """
    assert self._spec is not None and self._freqs_ghz is not None
    spec = self._spec
    w, ln = spec["w_mm"], spec["line_len_mm"]
    hs = spec["sub_h_mm"]
    xs = MLINE_AIR_SIDE_MM + w / 2 # 侧向空气隙（线心起算）
    at = MLINE_AIR_TOP_MM
    # 端口面位置：Port 特征只能放外部边界（真机实录「狭缝条件只能应用于
    # 内部边界，或者，端口只能放置在外部边界上」，tem_benchmark run1）——
    # tem 链按官方例 cpw_numeric_tem_port 结构让线体延伸到域端（端口面=
    # 模型外边界全截面，y 端不再设散射边界）；lumped 链保持既有内部端面
    # +MLINE_PORT_MARGIN_MM 余量段（集总端口不得邻接吸收特征，run2 实证）。
    ym = 0 if self._port_chain == "tem" else MLINE_PORT_MARGIN_MM
    y0, y1 = -ln / 2, ln / 2
    ye0, ye1 = y0 - ym, y1 + ym
    tol, eps_n = 1e-3, 1e-6
    scale = float((self._config.extra_params or {}).get("mesh_scale", 1.0))

    model = client.create(f"rfauto_mline_{int(time.time())}")
    j = model.java
    for name, expr in to_comsol_parameters_mline(spec).items():
      j.param().set(name, expr)
    if self._port_sweep:
      j.param().set(self.PORT_SWEEP_PARAM, "1") # 端口扫描参数（官方 h_bend）

    j.component().create("comp1", True)
    comp = j.component("comp1")
    geom = comp.geom().create("geom1", 3)
    geom.lengthUnit("mm")

    def block(tag: str, x0: float, x1: float, ya: float, yb: float,
         z0: float, z1: float) -> None:
      blk = geom.create(tag, "Block")
      blk.set("base", "corner") # 合法值小写（COMSOL 报错实录 center/corner）
      blk.set("pos", [x0, ya, z0])
      blk.set("size", [x1 - x0, yb - ya, z1 - z0])

    block("subL", -xs, -w / 2, y0, y1, 0, hs)
    block("subM", -w / 2, w / 2, y0, y1, 0, hs)
    block("subR", w / 2, xs, y0, y1, 0, hs)
    block("airL", -xs, -w / 2, y0, y1, hs, hs + at)
    block("airM", -w / 2, w / 2, y0, y1, hs, hs + at)
    block("airR", w / 2, xs, y0, y1, hs, hs + at)
    if ym > 0: # 端口余量段（仅 lumped 链；tem 链域端即端口面）
      block("subT0", -xs, xs, ye0, y0, 0, hs)
      block("subT1", -xs, xs, y1, ye1, 0, hs)
      block("airT0", -xs, xs, ye0, y0, hs, hs + at)
      block("airT1", -xs, xs, y1, ye1, hs, hs + at)
    # 走线：WorkPlane(z=HS) 内 Rectangle 零厚度片（union 印痕把基板/空气
    # 界面分出走线条带，PEC 即可施加其上）
    wp = geom.create("wp_trace", "WorkPlane")
    wp.set("quickplane", "xy")
    wp.set("quickz", "HS") # 带单位参数表达式（官方例 quickz 支持表达式）
    rect = wp.geom().create("r_trace", "Rectangle")
    rect.set("base", "corner")
    rect.set("pos", [-w / 2, y0])
    rect.set("size", [w, ln])
    if self._port_chain == "tem":
      # 电压积分线边：端面（y=±L/2）上从地（z=0）到走线（z=HS）的竖直
      # 线段，WorkPlane(yz, x=0) 印痕产生（数值 TEM 端口必须配电压积分
      # 线——RF User's Guide p.128；官方 cpw 例 "Set on a line geometry
      # between two conductive boundaries"）。方向=地→信号（决定电压
      # 符号；反了 S 参数相位差 π）。
      wpv = geom.create("wp_voltage", "WorkPlane")
      wpv.set("quickplane", "yz")
      wpv.set("quickx", "0")
      for name, y_edge in (("lv_port1", y0), ("lv_port2", y1)):
        seg = wpv.geom().create(name, "LineSegment")
        # specify=coord 必须显式设（默认=顶点选择模式，真机报
        # 「必须指定第一个顶点」；transmission_line_butler 例
        # p:specify1=coord 实录）
        seg.set("specify1", "coord")
        seg.set("specify2", "coord")
        seg.set("coord1", [y_edge, 0]) # 起点=地面（transmission_line_
        seg.set("coord2", [y_edge, hs]) # butler 例 coord1/coord2 实录）
    geom.run()

    def box_sel(tag: str, dim: int,
          lo: tuple[float, float, float],
          hi: tuple[float, float, float]) -> None:
      sel = comp.selection().create(tag, "Box")
      sel.set("entitydim", str(dim)) # JPype 整数属性传字符串（#217④）
      for axis, value in zip(("x", "y", "z"), lo, strict=True):
        sel.set(f"{axis}min", value)
      for axis, value in zip(("x", "y", "z"), hi, strict=True):
        sel.set(f"{axis}max", value)
      sel.set("condition", "inside")

    box_sel("sel_sub", 3, (-xs - tol, ye0 - tol, -tol),
        (xs + tol, ye1 + tol, hs + tol))
    box_sel("sel_air", 3, (-xs - tol, ye0 - tol, hs - tol),
        (xs + tol, ye1 + tol, hs + at + tol))
    self._dielectric_material(comp, "matl_sub", "sel_sub", "epsr",
                 self._loss_tangent)
    self._dielectric_material(comp, "matl_air", "sel_air", "1", None)

    box_sel("sel_gnd", 2, (-xs - tol, ye0 - tol, -tol),
        (xs + tol, ye1 + tol, tol))
    # 走线零厚度片（z=HS 界面印痕条带；薄盒 inside 恰选中 1 个面）
    box_sel("sel_trace", 2, (-w / 2 - tol, y0 - tol, hs - tol),
        (w / 2 + tol, y1 + tol, hs + tol))
    if self._port_chain == "tem":
      # 端口面=模型外边界全截面（基板+空气全高；官方 cpw 例同构）
      for tag, y in (("sel_port1", y0), ("sel_port2", y1)):
        box_sel(tag, 2, (-xs - tol, y - tol, -tol),
            (xs + tol, y + tol, hs + at + tol))
      # 电压积分线边选择（端面上 x=0 竖直线段；薄盒 inside 恰选中 1 边）
      for tag, y in (("sel_ilv1", y0), ("sel_ilv2", y1)):
        box_sel(tag, 1, (-tol, y - tol, -tol),
            (tol, y + tol, hs + tol))
    else:
      # 集总端口面=内部端面跨「地面 PEC↔走线底 PEC 片」
      for tag, y in (("sel_port1", y0), ("sel_port2", y1)):
        box_sel(tag, 2, (-w / 2 - tol, y - tol, -tol),
            (w / 2 + tol, y + tol, hs + eps_n))
    box_sel("sel_sbx0", 2, (-xs - tol, ye0 - tol, -tol),
        (-xs + tol, ye1 + tol, hs + at + tol))
    box_sel("sel_sbx1", 2, (xs - tol, ye0 - tol, -tol),
        (xs + tol, ye1 + tol, hs + at + tol))
    sct_sels = [("sctr_x0", "sel_sbx0"), ("sctr_x1", "sel_sbx1")]
    if self._port_chain == "lumped": # tem 链 y 端=端口面，无散射边界
      for tag, y in (("sel_sby0", ye0), ("sel_sby1", ye1)):
        box_sel(tag, 2, (-xs - tol, y - tol, -tol),
            (xs + tol, y + tol, hs + at + tol))
      sct_sels += [("sctr_y0", "sel_sby0"), ("sctr_y1", "sel_sby1")]
    box_sel("sel_sbtop", 2, (-xs - tol, ye0 - tol, hs + at - tol),
        (xs + tol, ye1 + tol, hs + at + tol))
    sct_sels.append(("sctr_top", "sel_sbtop"))

    phys = comp.physics().create(PHYSICS_TAG, PHYSICS_TYPE, "geom1")
    pec_gnd = phys.create("pec_gnd", "PerfectElectricConductor", 2)
    pec_gnd.selection().named("sel_gnd")
    pec_tr = phys.create("pec_trace", "PerfectElectricConductor", 2)
    pec_tr.selection().named("sel_trace")
    for tag, sel in sct_sels:
      sct = phys.create(tag, "Scattering", 2) # 官方例类型串实录
      sct.selection().named(sel)
    if self._port_chain == "tem":
      # 数值 TEM 边界模端口（官方例 cpw_numeric_tem_port/waveguide_adapter
      # 链）：特征类型串 "Port"、PortType="Numeric"（官方 dmodel 实录——
      # "TEM" 值是同轴解析型）+ numericTEM=1（GUI "Analyze as a TEM
      # field"）。StudyStep 解引用在 study 段回填（真机实证：引用的步
      # 不存在时报「参数值无效」，须先建 bma 步）。
      for tag, sel, name in (("port1", "sel_port1", "1"),
                  ("port2", "sel_port2", "2")):
        port = phys.create(tag, "Port", 2)
        port.selection().named(sel)
        port.set("PortName", name) # 数字串：端口扫描/Touchstone 必需
        port.set("PortType", PORT_TYPE_NUMERIC)
        port.set("numericTEM", "1")
        port.set("Zref", "Zref")
        port.set("PortExcitation",
             "on" if (self._port_sweep or name == "1") else "off")
        # 电压积分线子特征（RF User's Guide p.128：数值 TEM 必须；
        # 缺失真机报 Cmode_1 未定义——run 链 Cmode 根因之二）
        ilv = port.create(f"ilv_{tag}", INTEGRATION_LINE_FOR_VOLTAGE, 1)
        ilv.selection().named(f"sel_ilv{name}")
    else:
      for tag, sel, name in (("lport1", "sel_port1", "1"),
                  ("lport2", "sel_port2", "2")):
        port = phys.create(tag, "LumpedPort", 2)
        port.selection().named(sel)
        port.set("PortName", name) # 数字串：端口扫描/Touchstone 必需（p.143）
        port.set("PortType", "Uniform")
        port.set("TerminalType", "Cable")
        port.set("Zref", "Zref")
        port.set("PortExcitation", "on") # 扫描时 solver 逐端口覆盖（p.145）
    if self._port_sweep:
      self._apply_port_sweep_settings(phys)

    # 网格：全局粗 + 域级 Size 细（走线区/基板中块/其上空气；真机验证方案。
    # 全局细网格会撑爆装配内存——run3 实证 OOM；域级选择集按 block 划分）
    box_sel("sel_subM", 3, (-w / 2 - tol, y0 - tol, -tol),
        (w / 2 + tol, y1 + tol, hs + tol))
    box_sel("sel_subLR", 3, (-xs - tol, y0 - tol, -tol),
        (xs + tol, y1 + tol, hs + tol))
    box_sel("sel_airM", 3, (-w / 2 - tol, y0 - tol, hs - tol),
        (w / 2 + tol, y1 + tol, hs + at + tol))
    mesh = comp.mesh().create("mesh1")
    size = mesh.feature("size")
    size.set("custom", "on")
    size.set("hmax", MLINE_MESH_HMAX["global"] * scale)
    for tag, sel in (("size_subM", "sel_subM"), ("size_subLR", "sel_subLR"),
             ("size_airM", "sel_airM")):
      s1 = mesh.create(tag, "Size")
      s1.selection().named(sel) # 域级 Size+命名选择（探针实测合法）
      s1.set("custom", "on")
      s1.set("hmax", MLINE_MESH_HMAX[tag.removeprefix("size_")] * scale)
    mesh.create("ftet1", "FreeTet")
    mesh.run()

    j.study().create(STUDY_TAG)
    if self._port_chain == "tem":
      # 边界模分析步 ×2（独立 Mode Analysis 研究=study 首步，官方链
      # std=[bma1(PortName=1), bma2(PortName=2), freq]，官方 cpw 例同构
      # ——每端口一个边界模分析步）：解端口截面 TEM 模产生
      # Cmode/Lmode/端口模场，供 Frequency 步与端口 StudyStep 解引用。
      # modeFreq/shift 属性名真机 dump 实录（api_dump3）；shift 用
      # sqrt(epsr)（准 TEM neff≈√εeff 的本征值搜索起点，官方 cpw 例
      # sqrt(12.9)/1.5 同源口径）。
      f_mid = float(np.median(self._freqs_ghz))
      refs: dict[str, str] = {}
      for name in ("1", "2"):
        bma_tag = STUDY_STEP_BMA_TAG_FMT.format(port=name)
        bma = j.study(STUDY_TAG).create(bma_tag,
                        STUDY_STEP_BOUNDARY_MODE)
        bma.set("PortName", name)
        bma.set(BMA_MODE_FREQ_ATTR, format_plist([f_mid]))
        bma.set(BMA_SHIFT_ATTR, "sqrt(epsr)")
        refs[name] = BMA_STEP_REF_FMT.format(study=STUDY_TAG,
                           step=bma_tag)
      # 解引用回填（步已存在，引用合法）：端口模变量取自各自的边界模
      # 分析步——run9/10 报 Cmode_1 未定义即缺此接线（端口缺省指向
      # Frequency 步，Cmode 只在 bma 步产生）。
      phys.feature("port1").set("StudyStep", refs["1"])
      phys.feature("port2").set("StudyStep", refs["2"])
    if self._port_sweep:
      self._add_parametric_port_step(j) # 外层端口扫描（官方 h_bend 同构）
    freq = j.study(STUDY_TAG).create(FREQ_STEP_TAG, "Frequency") # #217②
    freq.set("plist", format_plist(self._freqs_ghz))
    return model

  # ── 端口扫描（官方 h_bend_waveguide_3d.mph 实录属性名，真机验证）────────────
  PORT_SWEEP_PARAM = "PortName" # 扫描参数名（官方默认；须与全局参数同名）

  def _apply_port_sweep_settings(self, phys: Any) -> None:
    """emw 接口 PortSweepSettings：启用端口扫描 + Touchstone 自动导出。"""
    ts_path = (self._working_dir / "sparams.s2p").resolve()
    for key, value in (
      ("useSweep", "1"), ("sweepOn", "Ports"),
      ("PortParamName", self.PORT_SWEEP_PARAM), ("ExportTouchstone", "1"),
      ("zref", "50[ohm]"), ("TouchstoneFile", str(ts_path)),
      ("format", "RI"), ("parameter", "S"),
      ("IfFileExists", "Overwrite"),
    ):
      phys.prop("PortSweepSettings").set(key, value)

  def _add_parametric_port_step(self, j: Any) -> None:
    """study 外层 Parametric 步扫 PortName（先建=外层；官方 h_bend 同构）。"""
    param = j.study(STUDY_TAG).create("param", "Parametric")
    param.set("pname", [self.PORT_SWEEP_PARAM])
    param.set("plistarr", [["1", "2"]])
    param.set("punit", [""])

  @staticmethod
  def _extract_sparams(model: Any) -> tuple[np.ndarray, np.ndarray]:
    """EvalGlobal 取 freq 与激励端口列 S11/S21（行=表达式、列=解号）。

    单端口激励下 COMSOL 只定义激励列（User's Guide p.145："一次只激励一个
    Cable 端口"；S12/S22 需 Port Sweep，真机实证 comp1.emw.S12 未定义）。
    v0 补齐口径（结果 field_data 显式标注）：S12=S21（互易，无源互易介质
    恒成立）、S22=S11（parallel_plate 模板几何镜像对称）。
    """
    j = model.java
    exprs = ["freq", f"comp1.{PHYSICS_TAG}.S11", f"comp1.{PHYSICS_TAG}.S21"]
    gev = j.result().numerical().create("gev_sparams", "EvalGlobal")
    gev.set("expr", exprs)
    re = np.asarray([[float(v) for v in row] for row in gev.getReal()], dtype=float)
    im = np.asarray([[float(v) for v in row] for row in gev.getImag()], dtype=float)
    if re.shape[0] != len(exprs):
      raise RuntimeError(f"EvalGlobal 返回形状异常: {re.shape}，期望 {len(exprs)} 行")
    freq_hz = re[0]
    s11 = re[1] + 1j * im[1]
    s21 = re[2] + 1j * im[2]
    n = freq_hz.size
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21 # 互易
    s[:, 1, 1] = s11 # 模板镜像对称
    return freq_hz / 1e9, s

  SPARAM_FILL_NOTE = ("measured: S11,S21 (port 1 excited); filled: S12=S21 (reciprocity), "
            "S22=S11 (parallel_plate mirror symmetry); full matrix needs Port Sweep")
  SPARAM_SWEEP_NOTE = ("measured: full 2x2 matrix via PortName parametric port sweep "
             "(official PortSweepSettings + Parametric study step)")

  @staticmethod
  def _extract_sparams_full(model: Any,
               freqs_ghz: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """端口扫描后取全 S 矩阵：EvalGlobal 行=表达式、列=解（不假设解序）。

    端口扫描把每个激励存为独立 dataset/outer（真机实证：
    dset1=
    PortName 2、dset2=PortName 1）→ 遍历 dataset × outersolnum 收集全部
    解列，每列以 freq 与 PortName（扫描参数）两行做 (频率, 激励端口) 识
    别后装配：PortName=1 列只定义 S11/S21（官方 p.145：一次只激励一个
    Cable 端口），PortName=2 列只定义 S12/S22——全矩阵实测，无需互易/
    对称补齐。
    """
    j = model.java
    p = PHYSICS_TAG
    exprs = ["freq", ComsolAdapter.PORT_SWEEP_PARAM,
         f"comp1.{p}.S11", f"comp1.{p}.S21",
         f"comp1.{p}.S12", f"comp1.{p}.S22"]
    gev = j.result().numerical().create("gev_sparams_full", "EvalGlobal")
    gev.set("expr", exprs)
    re_blocks: list = []
    im_blocks: list = []
    for dtag in j.result().dataset().tags():
      for oi in ("1", "2", "3", "4"): # 外层序号超出即属性值无效→跳过
        try:
          gev.set("data", dtag)
          gev.set("outersolnum", oi)
          re_b = np.asarray(
            [[float(v) for v in row] for row in gev.getReal()],
            dtype=float)
        except Exception: # 序号越界/属性无效=该 dataset 无此外层解
          continue
        im_b = np.asarray(
          [[float(v) for v in row] for row in gev.getImag()],
          dtype=float)
        re_blocks.append(re_b)
        im_blocks.append(im_b)
    if not re_blocks:
      raise RuntimeError("EvalGlobal 无任何解列返回（端口扫描解缺失）")
    re = np.concatenate(re_blocks, axis=1)
    im = np.concatenate(im_blocks, axis=1)
    if re.shape[0] != len(exprs):
      raise RuntimeError(f"EvalGlobal 返回形状异常: {re.shape}，期望 {len(exprs)} 行")
    freq_hz, port_col = re[0], re[1]
    s_cols = re[2:] + 1j * im[2:]
    n = len(freqs_ghz)
    s = np.full((n, 2, 2), np.nan + 1j * np.nan, dtype=complex)
    for k, f_ghz in enumerate(freqs_ghz):
      for col in range(freq_hz.size):
        if abs(freq_hz[col] - f_ghz * 1e9) > 1e4:
          continue
        exc = round(port_col[col])
        if exc == 1:
          pair, slots = (s_cols[0, col], s_cols[1, col]), ((0, 0), (1, 0))
        elif exc == 2:
          pair, slots = (s_cols[2, col], s_cols[3, col]), ((0, 1), (1, 1))
        else:
          continue
        # 未定义列守卫（tem×Parametric 真机实证）：TEM 链的
        # bma 步（modeFreq=带中值）也产生带 freq/PortName 的解数据集，
        # 其 S 表达式未定义回读为精确 0——dataset×outer 遍历中后到的
        # 零列曾覆盖真值（2.5 GHz 行 S12/S22=0，互易残差 0.98 假象；
        # 原生 Touchstone 同频点完整）。物理 2 端口激励列不可能两 S
        # 同时精确为 0，故全零列视为未定义跳过；且首个有效列不被覆盖
        # （重复数据集引用同一解，值相同）。
        if all(v == 0 for v in pair):
          continue
        for value, (i, jdx) in zip(pair, slots, strict=True):
          if np.isnan(s[k, i, jdx]):
            s[k, i, jdx] = value
    if np.isnan(s).any():
      raise RuntimeError(
        f"全 S 矩阵装配不完整（nan 残留 {int(np.isnan(s).sum())} 个）——"
        "端口扫描解缺失或 PortName 列识别失败")
    # 频轴按装配键去重（dataset×outer 遍历会产生重复解列）
    return np.asarray(freqs_ghz, dtype=float), s

  def _export_touchstone(self, model: Any, freq_ghz: np.ndarray,
              s: np.ndarray) -> dict[str, Any]:
    """Touchstone 落盘（端口扫描时优先 COMSOL 原生导出，skrf 兜底）。

    COMSOL 原生路径：PortSweepSettings.ExportTouchstone=1 在 solve 内自动
    写 TouchstoneFile；缺文件时走后处理导出特征（Programming Reference
    Manual p.1106 官方语法）。兜底路径用同一矩阵经 skrf 序列化（确定性）。
    """
    ts_path = (self._working_dir / "sparams.s2p").resolve()
    try:
      if not ts_path.exists(): # solve 内自动导出未落文件 → 后处理导出
        exp = model.java.result().export().create("ts_rfauto", "Touchstone")
        exp.set("filename", str(ts_path))
        exp.set("physicsinterface", PHYSICS_TAG)
        exp.set("parameter", "S")
        exp.set("format", "RI")
        exp.run()
      if not ts_path.exists():
        raise RuntimeError("COMSOL Touchstone 导出未产生文件")
      return {"file": str(ts_path), "writer": "comsol_native"}
    except Exception as exc:
      logger.warning("COMSOL 原生 Touchstone 导出失败，走 skrf 兜底: %s", exc)
    import skrf

    ntw = skrf.Network(
      frequency=skrf.Frequency(float(freq_ghz[0]), float(freq_ghz[-1]),
                   len(freq_ghz), unit="GHz"),
      s=s, z0=float(self._spec["z_ref_ohm"]) if self._spec else 50.0)
    ntw.write_touchstone(str(ts_path))
    return {"file": str(ts_path), "writer": "skrf_fallback"}

  # ── 持久模型单频重解（AFS 真机案例回调，⑩ 收口）────────────────────
  RESOLVE_EVAL_TAG_FMT = "gev_s21_r{seq}" # EvalGlobal 唯一 tag（避免撞名）

  def resolve_s21_at_frequency(self, model: Any, freq_ghz: float) -> complex:
    """已建模型上改频步为单频点重解并读回复数 S21（不重建几何/网格）。

    与 solve() 的全重建路线互补：AFS 自适应频扫（core.afs.afs_sample）每
    个 evaluate 回调=一次单频 FEM 求解——持久模型复用是缩减比成立的物理
    前提（几何/网格只建一次）。调用方须自行持 ``_SOLVE_LOCK`` 串行（license
    席位）。序列（官方口径逐条同既有链）：
     1. freq 步 ``plist`` 重写为单点（显式单位，format_plist）；
     2. ``model.study(STUDY_TAG).run()``（Java 建 study 按 tag 求解，#217③；
       tem 链的 bma 步无 plist 概念，模式分析频率固定在带中心，不受影响）；
     3. EvalGlobal 读 ``comp1.emw.S21``。
    坑（真机实录）：EvalGlobal 特征 tag 重复 create 会撞名抛错——本方法
    用实例级自增后缀保证唯一，且创建前 best-effort remove 同名残留（重跑
    场景兜底，#105）。
    """
    if model is None:
      raise RuntimeError("持久模型不可用（须先 build/solve 建模一次）")
    j = model.java
    j.study(STUDY_TAG).feature(FREQ_STEP_TAG).set(
      "plist", format_plist([float(freq_ghz)]))
    j.study(STUDY_TAG).run()
    self._resolve_eval_seq += 1
    tag = self.RESOLVE_EVAL_TAG_FMT.format(seq=self._resolve_eval_seq)
    num = j.result().numerical()
    with contextlib.suppress(Exception): # 同名残留兜底（#105）
      num.remove(tag)
    gev = num.create(tag, "EvalGlobal")
    gev.set("expr", ["freq", f"comp1.{PHYSICS_TAG}.S21"])
    re_rows = np.asarray(
      [[float(v) for v in row] for row in gev.getReal()], dtype=float)
    im_rows = np.asarray(
      [[float(v) for v in row] for row in gev.getImag()], dtype=float)
    if re_rows.shape != (2, 1) or im_rows.shape != (2, 1):
      raise RuntimeError(
        f"单频重解 EvalGlobal 返回形状异常: {re_rows.shape}，期望 (2, 1)")
    f_hz, s21 = re_rows[0, 0], complex(re_rows[1, 0] + 1j * im_rows[1, 0])
    if abs(f_hz - float(freq_ghz) * 1e9) > 1e4:
      raise RuntimeError(
        f"单频重解回读频率 {f_hz:.6e} Hz 与请求 {freq_ghz} GHz 不一致")
    return s21

  # ── 求解 ─────────────────────────────────────────────────────────────────
  def solve(self) -> EMSolverResult:
    """串行锁内：起/复用 Client → 建模 → 求解 → 取 S。异常→ success=False。"""
    if not self._connected or self._spec is None:
      return EMSolverResult(success=False, message="未连接或未构建几何")
    t0 = time.time()
    with _SOLVE_LOCK: # license 席位：同时刻只跑一个求解
      try:
        client = self._client_factory()
        self._client = client
        model = self._build_model(client)
        self._model = model
        # MPh Model.solve() 按节点 label 查 study（Java 建的 study label 是
        # "Study 1"/本地化名），按 tag 求解走官方 Java model.study(tag).run()
        model.java.study(STUDY_TAG).run()
        if self._port_sweep:
          freq_ghz, s = self._extract_sparams_full(model, self._freqs_ghz)
          touchstone = self._export_touchstone(model, freq_ghz, s)
          sparam_fill = self.SPARAM_SWEEP_NOTE
        else:
          freq_ghz, s = self._extract_sparams(model)
          touchstone = {}
          sparam_fill = self.SPARAM_FILL_NOTE
        if (self._config.extra_params or {}).get("save_mph"):
          self._model_path = self._working_dir / "comsol_model.mph"
          model.save(str(self._model_path.resolve()))
      except Exception as exc: # JPype 异常为 Exception 子类
        wall = time.time() - t0
        logger.error("COMSOL 求解失败: %s", exc)
        return EMSolverResult(success=False, wall_time_s=round(wall, 1),
                   message=f"COMSOL 求解失败: {exc}")
    wall = time.time() - t0
    self._write_csv(freq_ghz, s)
    mesh_info = (dict(MLINE_MESH_HMAX) if self._template == "mline"
           else float(self._config.mesh_resolution_mm))
    self._result = EMSolverResult(
      success=True, freq_ghz=freq_ghz, s_params=s,
      field_data={"sparam_fill": sparam_fill,
            "physics": f"{PHYSICS_TYPE}({PHYSICS_TAG})",
            "mesh_hmax_mm": mesh_info,
            "touchstone": touchstone,
            "template": self._template,
            "port_chain": self._port_chain,
            "loss_tangent": self._loss_tangent},
      wall_time_s=round(wall, 1),
      message=(f"COMSOL {self._version} 频域求解完成（{self._template}，"
           f"{len(freq_ghz)} 频点，"
           + ("端口扫描全 S 矩阵" if self._port_sweep
            else "EvalGlobal 取 S11/S21") + "）"),
    )
    return self._result

  def _write_csv(self, freq_ghz: np.ndarray, s: np.ndarray) -> None:
    """S 参量落 CSV（证据/可视化产物）；best-effort（#105）。"""
    try:
      self._working_dir.mkdir(parents=True, exist_ok=True)
      rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21,re_S12,im_S12,re_S22,im_S22"]
      for k, f in enumerate(freq_ghz):
        cells = [f"{f * 1e9:.6e}"]
        for (i, jdx) in ((0, 0), (1, 0), (0, 1), (1, 1)):
          cells += [f"{s[k, i, jdx].real:.9e}", f"{s[k, i, jdx].imag:.9e}"]
        rows.append(",".join(cells))
      (self._working_dir / "sparams.csv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")
    except Exception:
      logger.warning("COMSOL sparams.csv 落盘失败（不影响结果）", exc_info=True)

  def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
    """最近一次成功求解的 (freq_ghz, s_params)。"""
    if self._result is None or not self._result.success:
      raise RuntimeError("尚未成功求解，请先调用 solve()")
    return self._result.freq_ghz, self._result.s_params

  def close(self) -> None:
    """移除模型释放内存；Client 常驻（JPype 单 JVM 不可重启）。"""
    if self._model is not None and self._client is not None:
      with contextlib.suppress(Exception):
        self._client.remove(self._model)
    self._model = None
    self._connected = False

  # ── 多物理（emw + ht(+solid)）加性扩展：官方 Microwave Oven 例复现（a6-mwoven）──
  # 类型串/属性名出处见模块常量区注释（官方 oven / cylinder_conduction 的
  # dmodel.xml + 本机官方 API 清单）。原有模板（parallel_plate/mline）走原
  # 链路，这些方法只在被显式调用时生效——加性、零回归。

  @staticmethod
  def add_heat_transfer(comp: Any, *, selection: str | None = None,
             t_init: str | None = None,
             tag: str = HT_PHYSICS_TAG) -> Any:
    """加性：建 Heat Transfer in Solids（ht）接口，可选域选择与初始温度。

    官方 oven dmodel：Physics op="HeatTransfer"(tag ht)；初始值特征
    op="init" 属性 Tinit（官方例 Tinit='T0'）。
    """
    phys = comp.physics().create(tag, HT_PHYSICS_TYPE, "geom1")
    if selection:
      phys.selection().named(str(selection))
    if t_init is not None:
      # 接口创建时已自动带默认初始值特征 init1（官方 oven dmodel 同形），
      # 直接改它；缺失时才新建（避免 "feature exists" 报错）。
      try:
        init = phys.feature("init1")
      except Exception:
        init = phys.create("init1", "init", 3)
      init.set("Tinit", str(t_init))
    return phys

  @staticmethod
  def add_solid_mechanics(comp: Any, *, selection: str | None = None,
              tag: str = SOLID_PHYSICS_TAG) -> Any:
    """加性：建 Solid Mechanics（solid）接口（预留结构耦合；本项不求解）。"""
    phys = comp.physics().create(tag, SOLID_PHYSICS_TYPE, "geom1")
    if selection:
      phys.selection().named(str(selection))
    return phys

  @staticmethod
  def add_electromagnetic_heating(comp: Any, *, emw_tag: str = PHYSICS_TAG,
                  ht_tag: str = HT_PHYSICS_TAG,
                  tag: str = COUPLING_TAG) -> Any:
    """加性：emw→ht 单向耦合（官方 oven dmodel MultiphysicsCoupling op
    "ElectromagneticHeating"，属性 EMHeat_physics / Heat_physics）。"""
    cpl = comp.multiphysics().create(tag, COUPLING_TYPE, 3)
    cpl.set("EMHeat_physics", str(emw_tag))
    cpl.set("Heat_physics", str(ht_tag))
    return cpl

  @staticmethod
  def add_convective_heat_flux(ht_phys: Any, *, selection: str,
                 h_expr: str, t_ext_expr: str,
                 tag: str = "hf_conv") -> Any:
    """加性：对流换热边界（HeatFluxBoundary + HeatFluxType=ConvectiveHeatFlux）。

    稳态热必须有热沉，否则纯体积源问题奇异；属性名实录
    cylinder_conduction.mph HeatFluxBoundary（HeatFluxType /
    HeatTransferCoefficientType / h / Text）。
    """
    feat = ht_phys.create(tag, "HeatFluxBoundary", 2)
    feat.selection().named(str(selection))
    feat.set("HeatFluxType", HEAT_FLUX_CONVECTIVE)
    feat.set("HeatTransferCoefficientType", "UserDef")
    feat.set("h", str(h_expr))
    feat.set("Text", str(t_ext_expr))
    return feat

  # ── D14 stage-2：热-结构-EM 三场（solid 热膨胀 → 变形构型 → emw 本征重解）──
  # 官方参照（COMSOL"微波滤波器热漂移"官方例）：
  # applications/RF_Module/Filters/cavity_filter_thermal_expansion.mph，其
  # dmodel.xml 建模指令流已解包实录存档：Stationary(仅 solid) → Eigenfrequency(emw、关空间框架)
  # →（Parametric 温度扫描）；材料结构属性实录 MEMS_Module
  # biased_resonator_3d_basic.mph（解包存档）。
  # 以下方法全部加性、不进 solve() 主链路（真机脚本显式组装）。

  @staticmethod
  def add_structural_properties(mat: Any, *, youngs_expr: str,
                 poisson_expr: str, cte_expr: str,
                 group_tag: str = "Enu") -> Any:
    """给既有材料补结构属性：Enu 组（杨氏模量与泊松比）+ def 组热膨胀系数。

    官方实录（biased_resonator_3d_basic.mph dmodel actions）：
    - materialmodel 建 "Enu" 组（**三参 (tag, type, label)**："Young's
     modulus and Poisson's ratio"——label 是材料属性模型组的元数据，
     两参建组真机实证：solid 消费不到
     E/nu，刚度矩阵退化、稳态步残差 ~0.007 永不收敛且位移恒零），
     属性名 E / nu（标量字符串，如 "160e9[Pa]" / "0.22"）；
    - def 组 thermalexpansioncoefficient = 9 元 1/K 数组（各向同性对角）；
    - def 组同时写 youngsmodulus/poissonsratio 标准名兜底（solid 查找
     材料属性模型的顺序问题不再依赖单一组）。
    """
    enu = mat.propertyGroup().create(
      str(group_tag), str(group_tag),
      "Young's modulus and Poisson's ratio")
    enu.set("E", str(youngs_expr))
    enu.set("nu", str(poisson_expr))
    cte = str(cte_expr)
    zeros = "0"
    grp = mat.propertyGroup("def")
    grp.set("thermalexpansioncoefficient",
        [cte, zeros, zeros, zeros, cte, zeros, zeros, zeros, cte])
    grp.set("youngsmodulus", [str(youngs_expr)])
    grp.set("poissonsratio", [str(poisson_expr)])
    return enu

  @staticmethod
  def add_thermal_expansion(solid_phys: Any, *, t_ref_expr: str = "Tref",
               t_expr: str = "T1", tag: str = "te1") -> Any:
    """solid 默认线弹性特征（lemm1）下加热膨胀子特征 ThermalExpansion。

    官方实录（cavity_filter_thermal_expansion.mph actions）：
     lemm1.set("geometricNonlinearity","linear")；
     lemm1.create("te1","ThermalExpansion",3)；
     te1 set("minput_strainreferencetemperature_src","userdef") +
       set("minput_strainreferencetemperature","T0")；
     te1 set("minput_temperature_src","userdef") +
       set("minput_temperature","T1")。
    CTE 缺省 from_mat（消费材料 def 组 thermalexpansioncoefficient，
    alpha_mat=SecantCoefficient 缺省同官方）。
    """
    try:
      lemm = solid_phys.feature("lemm1")
    except Exception as exc: # solid 接口无默认线弹性特征（异常结构不再猜）
      raise RuntimeError(
        "solid 接口缺默认线弹性特征 lemm1（COMSOL 6.3 实证应为自动创建）"
      ) from exc
    lemm.set("geometricNonlinearity", "linear")
    te = lemm.create(str(tag), "ThermalExpansion", 3)
    te.set("minput_strainreferencetemperature_src", "userdef")
    te.set("minput_strainreferencetemperature", str(t_ref_expr))
    te.set("minput_temperature_src", "userdef")
    te.set("minput_temperature", str(t_expr))
    return te

  @staticmethod
  def add_point_displacement_constraint(
      solid_phys: Any, *, selection: str, tag: str = "disp_fix",
      components: tuple[int, ...] = (0, 1, 2)) -> Any:
    """点位移约束 Displacement0（几何点级，entitydim=0），抑制刚体位移。

    官方实录（cavity_filter_thermal_expansion.mph actions）：三点约束
    disp1/2/3 = create(...,"Displacement0",0) + 点选择 +
    setIndex("Direction","prescribed",0/1/2)。热膨胀自由体单点全约束
    （默认 components=(0,1,2)）对均匀应变场扰动极小（脚本记录该假设）。
    """
    feat = solid_phys.create(str(tag), "Displacement0", 0)
    feat.selection().named(str(selection))
    for idx in components:
      feat.setIndex("Direction", "prescribed", int(idx))
    return feat

  @staticmethod
  def add_mesh_displacement(comp: Any, *, selection: str | None = None,
               tag: str = "disp1",
               components: tuple[str, ...] = ("u", "v", "w"),
               ) -> Any:
    """规定网格位移 PrescribedMeshDisplacement：网格位移=solid 位移分量。

    官方实录（tunable_cavity_filter.mph，"机械调谐→EM 重解"官方例）：
    common create("disp1","PrescribedMeshDisplacement") + selection +
    set("prescribedMeshDisplacement", ["u","v","w"])——把网格位移显式
    绑定到 solid 位移分量，EM 在变形构型上重解（配合热漂移 study 的
    eig 步 setSolveFor("/frame/spatial1", false)）。
    真机实证：同域（emw 与 solid 同一
    介质域）场景这是**必需且充分**的桥梁——只建 DeformingDomain（free1）
    时 solid 位移恒零、EM 频移不含几何项（tcdk=0 时漂移精确为 0）；
    补上本特征后位移场 ~17μm（期望 18μm）、纯几何频移 +874ppm（期望
    +910ppm）。
    """
    disp = comp.common().create(str(tag), "PrescribedMeshDisplacement")
    if selection:
      disp.selection().named(str(selection))
    else:
      disp.selection().all()
    disp.set("prescribedMeshDisplacement", [str(c) for c in components])
    return disp

  @staticmethod
  def add_deforming_domain(comp: Any, *, selection: str | None = None,
               tag: str = "free1") -> Any:
    """变形域 DeformingDomain（free 网格平滑）：**跨域**变形传播用。

    官方实录（tunable_cavity_filter.mph）：common
    create("free1","DeformingDomain") 选择**无结构方程的域**（如
    EM 空气域）——网格在结构边界位移驱动下自由平滑传播；结构域本身
    走 add_mesh_displacement（规定位移）。同域（solid 与 emw 共用
    一个介质域）场景**不要建本特征**：自由平滑方程与规定位移在边界
    上冲突（真机实证：comp1.spatial.u_free 未定义报错）。
    """
    free = comp.common().create(str(tag), "DeformingDomain")
    if selection:
      free.selection().named(str(selection))
    else:
      free.selection().all()
    return free

  @staticmethod
  def build_thermal_drift_study(j: Any, *, neigs: int = 1,
                 study_tag: str = STUDY_TAG) -> Any:
    """热漂移两步 study：Stationary(仅 solid) → Eigenfrequency(emw 变形构型)。

    官方实录（cavity_filter_thermal_expansion.mph actions，D14 stage-2
    "变形几何/移动网格→EM 重解"的官方实现机制）：
    - stat 步：setSolveFor("/physics/solid",True)、("/physics/emw",False)
     ——只解结构热膨胀位移；
    - eig 步：setSolveFor("/physics/solid",False)、("/frame/spatial1",False)
     + set("neigsactive",True) + set("neigs",N)——空间框架不作为求解对象，
     solid 解出的位移场定义 material→spatial frame 映射，emw 在**变形后
     构型**上重解本征频率（形变不重解）。
    温度用全局参数（Tref/T1，minput_* 表达式引用）驱动，逐点改参数重跑。
    """
    j.study().create(study_tag)
    study = j.study(study_tag)
    stat = study.create("stat", STUDY_STEP_STATIONARY)
    stat.setSolveFor("/physics/solid", True)
    stat.setSolveFor("/physics/emw", False)
    eig = study.create("eig", STUDY_STEP_EIGENFREQUENCY)
    eig.setSolveFor("/physics/solid", False)
    eig.setSolveFor("/frame/spatial1", False)
    # JPype 陷阱：set(str,int) 在 boolean/int 重载间二义（#217④ 同族），
    # 整数属性一律传字符串（COMSOL 属性接受字符串表达式）
    eig.set("neigsactive", True)
    eig.set("neigs", str(int(neigs)))
    return study

  @staticmethod
  def configure_eigen_shift(model: Any, shift_expr: str) -> list[str]:
    """给 study 已生成的 solver 序列里的 Eigenvalue 求解器设搜索 shift。

    真机实证：java 自动序列的 Eigenvalue
    特征（默认 tag e1，属性清单含 shift/eigref/eigvf，真机 properties()
    dump）缺省 shift=0 → ARPACK 命中零空间解 → emw.freq=0（假结果）；
    set("shift", "<f0>[GHz]") 后基模 3.9176008 GHz 与闭式 3.9176007 GHz
    一致（偏差 4e-8）。shift 是数值搜索起点（模型闭式 f0），非测量结果。

    best-effort 穿透：非 Eigenvalue 特征 set("shift") 抛属性不存在异常
    直接吞（#105）；全部特征都 set 失败（序列未生成）时如实抛错。
    """
    touched: list[str] = []
    for s in model.java.sol().tags():
      sol = model.java.sol(str(s))
      for f in sol.feature().tags():
        feat = sol.feature(str(f))
        try:
          feat.set("shift", str(shift_expr))
        except Exception: # 非 Eigenvalue 特征无 shift 属性
          continue
        touched.append(f"{s}/{f}")
    if not touched:
      raise RuntimeError(
        "没有任何求解器特征接受 shift（study solver 序列未生成？先 "
        "createAutoSequences(\"all\") 或 run() 一次）")
    return touched

  @staticmethod
  def extract_eigenfrequency(model: Any, *, expr: str = "emw.freq",
                unit: str = "GHz", dataset: str | None = None,
                tag: str = "eig_freq") -> np.ndarray:
    """本征频率全局评估：EvalGlobal（官方 cavity 例 gev1 节点实录）。

    numerical().create(tag,"EvalGlobal") + set expr/unit + getReal；
    返回 shape=(n_eigs,) 数组（行=表达式、列=解号，同 evaluate_volume_series
    语义）。dataset 缺省用默认解数据集——stat+eig 两步会产生多个数据集，
    默认可能指向非本征解，调用方应显式传本征数据集 tag 或做 best-effort
    枚举（脚本侧封装）。
    """
    num = model.java.result().numerical().create(str(tag), "EvalGlobal")
    num.set("expr", [str(expr)])
    if unit is not None:
      num.set("unit", [str(unit)])
    if dataset is not None:
      num.set("data", str(dataset))
    rows = np.asarray([[float(v) for v in row] for row in num.getReal()],
             dtype=float)
    if rows.size == 0:
      raise RuntimeError(f"EvalGlobal 未返回任何数值（expr={expr}）")
    return rows[0]

  @staticmethod
  def build_multiphysics_study(j: Any, *, study_kind: str,
                 freqs_ghz: Any = None,
                 t_list: str | None = None,
                 study_tag: str = STUDY_TAG,
                 thermal_physics: tuple[str, ...] = (HT_PHYSICS_TAG,),
                 ) -> Any:
    """按 study_step_plan 建 study：Frequency → Stationary / Transient。

    - Frequency 步 plist 显式带单位（#217②）；
    - 热步只解热物理、关掉 emw，并显式打开耦合特征（属性 activate /
     activateCoupling 实录官方 oven 的 Transient 步）；
    - Transient 步 tlist 用 COMSOL range 语法（官方例 range(0,1,5)）。
    """
    plan = study_step_plan(study_kind)
    j.study().create(study_tag)
    study = j.study(study_tag)
    for step_tag, step_type in plan:
      step = study.create(step_tag, step_type)
      if step_type == STUDY_STEP_FREQUENCY:
        if freqs_ghz:
          step.set("plist", format_plist(list(freqs_ghz)))
        continue
      if step_type == STUDY_STEP_TRANSIENT:
        step.set("tlist", t_list or "range(0,1,5)")
      # Solve-for 矩阵（属性 activate，官方 oven Transient 步 p:activate
      # 同族）：交替 (物理 tag, on/off)。**只列组件里真实存在的接口**——
      # 真机实证（run1）：多写一个不存在的 tag（如无 solid 接口时的
      # "solid"）或追加 frame 项都会报「属性值无效」；缺省解序也会让
      # Frequency 步的解作为未求解变量的来源（单向耦合口径）。
      tags: list[str] = []
      for name in (PHYSICS_TAG, *thermal_physics):
        if name not in tags:
          tags.append(name)
      flags: list[str] = []
      for name in tags:
        flags += [name, ("on" if name in thermal_physics else "off")]
      step.set("activate", flags)
      step.set("activateCoupling", [COUPLING_TAG, "on"])
    return study

  @staticmethod
  def evaluate_volume_series(model: Any, *, tag: str, kind: str, expr: str,
                selection: str | None = None,
                unit: str | None = None,
                dataset: str | None = None,
                solution: str = "all") -> np.ndarray:
    """结果特征取标量序列：kind ∈ {IntVolume, MaxVolume, MinVolume,
    AvVolume, IntSurface}。

    返回 shape=(n_solutions,) 的实数数组（行=表达式、列=解号，见官方 API
    NumericalFeature.getReal 语义；本函数只建单表达式特征）。
    属性名 expr/unit/data/innerinput 实录官方 oven IntVolume 节点；
    IntSurface（边界积分，d3-2 稳态能量闭合 ∮ht.ntflux dS 用）同族类型串
    本机官方 API 清单实录。
    """
    if kind not in (RESULT_INT_VOLUME, RESULT_MAX_VOLUME, RESULT_MIN_VOLUME,
            RESULT_AV_VOLUME, RESULT_INT_SURFACE):
      raise ValueError(f"不支持的结果特征类型 {kind!r}")
    num = model.java.result().numerical().create(tag, kind)
    num.set("expr", [str(expr)])
    if unit is not None:
      num.set("unit", [str(unit)])
    if selection:
      num.selection().named(str(selection))
    if dataset:
      num.set("data", str(dataset))
    if solution:
      # 解序选择："all"=全部解列（瞬态→最后一个时间步是末态）；某些特征
      # 类型不接受该属性时退回默认解序即可，不阻塞取数（best-effort #105）。
      with contextlib.suppress(Exception):
        num.set("innerinput", str(solution))
    rows = np.asarray([[float(v) for v in row] for row in num.getReal()],
             dtype=float)
    if rows.size == 0:
      raise RuntimeError(f"{kind} 未返回任何数值（expr={expr}）")
    return rows[0]

  @classmethod
  def extract_absorbed_power(cls, model: Any, *, selection: str,
                expr: str = f"{HT_PHYSICS_TAG}.Qtot",
                unit: str = "W",
                dataset: str | None = None,
                tag: str = "int_pabs") -> float:
    """土豆吸收功率 [W]：体热源 ht.Qtot 的体积分（官方例口径 = 631 W）。

    官方 oven 的结果特征即 IntVolume(ht.Qtot)，选择 Potato；官方文本
    "The result is 631 W"（full model，1 kW 输入）。
    """
    series = cls.evaluate_volume_series(
      model, tag=tag, kind=RESULT_INT_VOLUME, expr=expr,
      selection=selection, unit=unit, dataset=dataset)
    return float(series[-1])

  @classmethod
  def extract_temperature(cls, model: Any, *, selection: str,
              unit: str = "degC",
              dataset: str | None = None,
              tag_prefix: str = "tstat") -> dict[str, Any]:
    """温度场标量摘要（degC）：MaxVolume/MinVolume/AvVolume(T)。

    体积极值/均值结果特征类型串取自本机官方 API 清单；返回
    temperature_record 校验过的 {t_max_c, t_min_c, t_avg_c}。
    """
    t_max = cls.evaluate_volume_series(
      model, tag=f"{tag_prefix}_max", kind=RESULT_MAX_VOLUME, expr="T",
      selection=selection, unit=unit, dataset=dataset)
    t_min = cls.evaluate_volume_series(
      model, tag=f"{tag_prefix}_min", kind=RESULT_MIN_VOLUME, expr="T",
      selection=selection, unit=unit, dataset=dataset)
    t_avg = cls.evaluate_volume_series(
      model, tag=f"{tag_prefix}_avg", kind=RESULT_AV_VOLUME, expr="T",
      selection=selection, unit=unit, dataset=dataset)
    return temperature_record(float(t_max[-1]), float(t_min[-1]),
                 float(t_avg[-1]))

  @staticmethod
  def evaluate_point_series(model: Any, *, expr: str,
               point_exprs: tuple[str, str, str],
               unit: str = "degC",
               dataset: str | None = None,
               tag: str = "pt_probe") -> np.ndarray:
    """官方三维截点位标量序列：CutPoint3D 数据集 + EvalPoint 数值特征。

    类型串/属性名实录（d3-2）：CutPoint3D 的 pointx/pointy/pointz
    来自官方 oven dmodel.xml（官方截点位 = "wo/2","0","rpot+bp+hp"）；
    EvalPoint 类型串本机官方 API 清单实录。返回 shape=(n_times,) 数组
    （瞬态=各输出时刻；稳态=单解）。dataset 缺省用 COMSOL 默认解数据集。
    """
    px, py, pz = (str(v) for v in point_exprs)
    cpt = model.java.result().dataset().create(f"{tag}_cpt",
                          DATASET_CUT_POINT_3D)
    cpt.set("pointx", px)
    cpt.set("pointy", py)
    cpt.set("pointz", pz)
    if dataset:
      cpt.set("data", str(dataset))
    pev = model.java.result().numerical().create(f"{tag}_ev",
                           RESULT_EVAL_POINT)
    pev.set("data", f"{tag}_cpt")
    pev.set("expr", [str(expr)])
    if unit is not None:
      pev.set("unit", [str(unit)])
    # 瞬态取全部输出时刻（属性不支持时退回默认解序，best-effort #105）
    with contextlib.suppress(Exception):
      pev.set("innerinput", "all")
    rows = np.asarray([[float(v) for v in row] for row in pev.getReal()],
             dtype=float)
    if rows.size == 0:
      raise RuntimeError(
        f"EvalPoint 未返回任何数值（expr={expr}, point={point_exprs}）")
    return rows[0]

  @classmethod
  def extract_surface_integral(cls, model: Any, *, selection: str,
                 expr: str,
                 unit: str = "W",
                 dataset: str | None = None,
                 tag: str = "int_qout") -> float:
    """边界积分标量 [W]（IntSurface）：稳态能量闭合 ∮ht.ntflux dS 用。"""
    series = cls.evaluate_volume_series(
      model, tag=tag, kind=RESULT_INT_SURFACE, expr=expr,
      selection=selection, unit=unit, dataset=dataset)
    return float(series[-1])

  @staticmethod
  def temperature_field(model: Any, *, expr: str = "T",
             unit: str = "degC") -> np.ndarray | None:
    """best-effort：取节点温度场（落 CSV / 自洽统计用）。

    真机实证：
    - MPh evaluate 返回的是**全模型**节点值（384420 个），而 T 只在土豆域
     有定义 -> 其余实体为 NaN，故只能取有限子集，不能要求全有限；
    - 数据集里既有稳态解（研究 1//解 1，T≈3565..7207 degC），也有
     "解存储"（研究 1//解存储 1，T=初值 8 degC）——按**有限值极差最大**
     选数据集，避免误取初值场；
    - 无有限值/任何异常都返回 None：观测性代码不得成为主路径故障点（#105）。
    """
    candidates: list[Any] = [None]
    try:
      for name in reversed(list(model.datasets())):
        if name not in candidates:
          candidates.append(name)
    except Exception: # MPh 版本差异 / 桩对象无数据集清单
      pass
    best: np.ndarray | None = None
    best_spread = -1.0
    for dataset in candidates:
      try:
        values = (model.evaluate(expr, unit) if dataset is None
             else model.evaluate(expr, unit, dataset))
      except Exception:
        continue
      if values is None:
        continue
      try:
        arr = np.asarray(values, dtype=float).ravel()
      except (TypeError, ValueError):
        continue
      finite = arr[np.isfinite(arr)]
      if finite.size == 0:
        continue
      spread = float(finite.max() - finite.min())
      if spread > best_spread:
        best, best_spread = finite, spread
    if best is None:
      logger.info("COMSOL 温度场未取到有限场（best-effort 返回 None）")
    return best

  # ── 能力声明（如实）──────────────────────────────────────────────────────
  def visualizations(self) -> list[dict[str, Any]]:
    viz: list[dict[str, Any]] = [
      {"kind": "sparams", "spec": {"file": str(self._working_dir / "sparams.csv")}},
    ]
    if self._model_path is not None:
      viz.append({"kind": "model3d",
            "spec": {"file": str(self._model_path), "format": "mph"}})
    return viz

  def supported_output_formats(self) -> list[str]:
    """CSV 常备；Touchstone 随端口扫描能力接入（COMSOL 原生导出/skrf 兜底）。"""
    return ["csv", "touchstone"]

  def get_status(self) -> dict[str, Any]:
    status = super().get_status()
    status.update({
      "comsol_version_pin": self._version,
      "comsol_root": self._comsol_root,
      "mph_installed": mph_installed(),
      "templates": list(SUPPORTED_TEMPLATES),
      "license_policy": "serial（模块级锁，每次求解占一席）",
    })
    return status


# ── 注册到全局注册表（与 openems_solver/palace_solver 同模式：导入即注册）──────
def register_comsol() -> None:
  """注册 COMSOL 求解器到全局注册表。"""
  get_global_registry().register(EMSolverType.COMSOL, ComsolAdapter)


with contextlib.suppress(Exception):
  register_comsol()
