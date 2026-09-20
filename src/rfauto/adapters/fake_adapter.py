"""FakeAdapter — 解析近似仿真器 + 故障注入（§9.5）。

无需许可证，秒级返回合成 skrf.Network。
用于单元测试、CI 流水线、优化回路干跑。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.core.errors import (
  ModelBuildError,
  SimulationFailedError,
)
from rfauto.core.interfaces import (
  AdapterCapabilities,
  SimulatorAdapter,
  SolveReport,
)

# ─── fake 联合校准（fake ↔ openEMS，铁律：先验模型再校准）──────────

_CAL_CACHE: dict[str, Any] | None = None

# 默认物理锚（无配置文件时使用；来源见各字段注释）
# v0：wilkinson 不再有 eps_eff 锚——谐振频率由
# synthesis.forward_z0 按线宽物理计算 εeff（旧锚 3.28 是 branchline 真机
# 值，误用于 wilkinson 会把 f0 压低 10%，P0 FAIL 复盘时发现）。
_DEFAULT_CALIBRATION: dict[str, dict[str, float]] = {
  "branchline": {"eps_eff": 3.28},
  "patch": {"eps_eff": 2.33},
}


def load_fake_calibration(path: str | Path | None = None) -> dict[str, dict[str, float]]:
  """读取 configs/fake_calibration.yaml（best-effort；缺失/损坏返回默认锚）。

  配置来源与含义：eps_eff 为该模型 fake 谐振公式的有效介电常数锚；
  s11_floor_db 为谐振深度下限（真实谐振器非零深）；s11_edge_scale 为
  带边反射斜率。数值以 knowledge/reference/openems_nominal/ 的收敛
  openEMS 曲线为准（多模态审计确认模型正确后的联合校准）。
  """
  global _CAL_CACHE
  if _CAL_CACHE is not None:
    return _CAL_CACHE
  merged = {k: dict(v) for k, v in _DEFAULT_CALIBRATION.items()}
  try:
    import yaml
    p = Path(path) if path else Path(__file__).resolve().parents[3] / "configs" / "fake_calibration.yaml"
    if p.exists():
      data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
      for model, kv in (data.get("models") or {}).items():
        if isinstance(kv, dict):
          merged.setdefault(model, {}).update(
            {k: float(v) for k, v in kv.items() if isinstance(v, (int, float))})
  except Exception:
    pass # best-effort（#105）：校准缺失不阻塞求解
  _CAL_CACHE = merged
  return merged


# ─── 故障注入配置 ────────────────────────────────────────────────────────────

class FaultInjection:
  """可配置的故障注入器，用于测试错误处理路径。

  Parameters
  ----------
  fail_connect : bool
    connect() 时抛出 ConnectFailedError。
  fail_build : bool
    build_and_setup() 时抛出 ModelBuildError。
  fail_solve : bool
    solve() 时抛出 SimulationFailedError。
  passivity_violation : bool
    solve() 返回的网络包含非被动 S 参数（|S|>1）。
  slow_solve_s : float
    模拟求解延迟（秒），0 表示无延迟。
  """

  def __init__(
    self,
    fail_connect: bool = False,
    fail_build: bool = False,
    fail_solve: bool = False,
    passivity_violation: bool = False,
    slow_solve_s: float = 0.0,
  ) -> None:
    self.fail_connect = fail_connect
    self.fail_build = fail_build
    self.fail_solve = fail_solve
    self.passivity_violation = passivity_violation
    self.slow_solve_s = slow_solve_s


# ─── 解析近似模型 ────────────────────────────────────────────────────────────
# v0 物理映射（代理校准设计文档口径）：
# - S11 形状统一为 Lorentzian 谐振谷：f0 处深度 = s11_min_lin（由设计变量的
#  物理失配计算，见 solve()），向带边抬升到 s11_edge_scale。
#  旧版"谐振点取峰/常数 floor+edge"物理倒置且对参数不敏感（P0 真机 FAIL
#  实证：rank_flip 5/6），语义已废除。
# - 参数响应来源：arm_len → f0（λ/4 反推）；series_w/shunt_w → 线宽失配；
#  patch: patch_len → f_res，feed_offset/patch_w → 馈电匹配。

def _wilkinson_sparams_2port(
  freq_ghz: np.ndarray,
  z0: float = 50.0,
  f0_ghz: float = 2.4,
  rng: np.random.Generator | None = None,
  s11_min_lin: float = 0.12,
  s11_far_lin: float = 0.7,
  bw_frac: float = 0.25,
) -> np.ndarray:
  """Wilkinson 功分器 S 参数解析近似（2 端口简化版，v0 物理映射）。

  |S11|：远离 f0 趋近全反射 s11_far_lin（失谐的 λ/4 线不匹配），在 f0
  处下陷到 s11_min_lin（线宽失配的物理计算值，Lorentzian 谷形）。
  S21 于 f0 时 = 1/√2 ≈ -3.01 dB。

  Returns shape (n_freq, 2, 2) complex S-matrix.
  """
  if rng is None:
    rng = np.random.default_rng()
  n = len(freq_ghz)
  s = np.zeros((n, 2, 2), dtype=complex)

  theta = (np.pi / 2) * (freq_ghz / f0_ghz)
  delta = freq_ghz / f0_ghz - 1.0
  resonance = 1.0 / (1.0 + (delta / bw_frac) ** 2)
  s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
  s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
  s11_mag = s11_far - (s11_far - s11_min) * resonance

  # S21：f0 时 = 1/√2，传输相位 -θ
  s21_complex = (1 / np.sqrt(2)) * np.exp(-1j * theta)

  s[:, 0, 0] = s11_mag * np.exp(1j * rng.uniform(0, 0.1, n)) # S11
  s[:, 1, 0] = s21_complex # S21
  s[:, 0, 1] = s21_complex # S12（互易）
  s[:, 1, 1] = s11_mag * np.exp(1j * rng.uniform(0, 0.1, n)) # S22

  # 确保 passivity：归一化使 |S| ≤ 0.98
  max_mag = np.max(np.abs(s))
  if max_mag > 0.98:
    s = s * (0.95 / max_mag)

  return s


def _wilkinson_sparams_3port(
  freq_ghz: np.ndarray,
  z0: float = 50.0,
  f0_ghz: float = 2.4,
  rng: np.random.Generator | None = None,
  s11_min_lin: float = 0.12,
  s11_far_lin: float = 0.7,
  bw_frac: float = 0.25,
) -> np.ndarray:
  """Wilkinson 功分器 S 参数解析近似（3 端口完整版，v0 物理映射）。

  S11 同 2 端口（谐振谷形，深度 = 线宽失配物理值）。
  S21 = S31 = -j/√2 @f0（等分）；S23 隔离在 f0 最好（一阶近似：
  随失谐 |Δf|/f0 线性退化，实际由隔离电阻+两臂对称性决定）。

  Returns shape (n_freq, 3, 3) complex S-matrix.
  """
  if rng is None:
    rng = np.random.default_rng()
  n = len(freq_ghz)
  s = np.zeros((n, 3, 3), dtype=complex)

  theta = (np.pi / 2) * (freq_ghz / f0_ghz)
  delta = freq_ghz / f0_ghz - 1.0
  resonance = 1.0 / (1.0 + (delta / bw_frac) ** 2)
  s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
  s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
  s11_mag = s11_far - (s11_far - s11_min) * resonance

  # 传输：S21 = S31 = -j/√2 @f0（等功率分配 + 传输相位 -θ）
  s21_complex = (1 / np.sqrt(2)) * np.exp(-1j * theta)

  # 隔离：f0 处最好（一阶 -30dB），随失谐线性退化（封顶 -15dB）
  s23_mag = 0.03 + 0.12 * np.minimum(np.abs(delta), 0.3)

  # 各端口的相位扰动（独立随机，保持对称性）
  p1 = np.exp(1j * rng.uniform(0, 0.1, n))
  p2 = np.exp(1j * rng.uniform(0, 0.1, n))
  p3 = np.exp(1j * rng.uniform(0, 0.1, n))

  # 对角线：反射
  s[:, 0, 0] = s11_mag * p1 # S11
  s[:, 1, 1] = s11_mag * p2 # S22
  s[:, 2, 2] = s11_mag * p3 # S33

  # 输入 → 输出（互易）
  s[:, 1, 0] = s21_complex # S21
  s[:, 0, 1] = s21_complex # S12
  s[:, 2, 0] = s21_complex # S31
  s[:, 0, 2] = s21_complex # S13

  # 输出间隔离（互易）
  s23_complex = s23_mag * p2 * p3.conj()
  s[:, 1, 2] = s23_complex # S23
  s[:, 2, 1] = s23_complex # S32

  # 确保 passivity：逐行归一化
  for i in range(n):
    row_mag = np.sum(np.abs(s[i]) ** 2, axis=1)
    scale = np.sqrt(row_mag)
    max_scale = np.max(scale)
    if max_scale > 0.99:
      s[i] *= 0.95 / max_scale

  return s


def _branchline_sparams(
  freq_ghz: np.ndarray,
  z0: float = 50.0,
  f0_ghz: float = 2.4,
  series_w_mm: float = 1.87,
  shunt_w_mm: float = 1.11,
) -> np.ndarray:
  """分支线耦合器 S 参数解析近似（真机校准版）。

  3dB 90° 耦合器。f0 处理想值：S21(Through) = -j/√2，
  S31(Coupled) = -1/√2，S11 = S41 = 0。

  真机校准（2026-09 二维调参）：
  - S11 深度依赖于 series_w/shunt_w 的阻抗匹配度
  - 最优 S11 约 -9.3 dB（arm_len≈18mm, series_w≈1.5mm, shunt_w≈1.1mm）
  - 线宽偏离最优值时 S11 退化（模拟阻抗失配效应）

  Returns shape (n_freq, 4, 4) complex S-matrix.
  """
  n = len(freq_ghz)
  s = np.zeros((n, 4, 4), dtype=complex)

  theta = np.pi / 2 * (freq_ghz / f0_ghz) # 电长度

  coupling = 1 / math.sqrt(2)

  # 频率响应包络
  envelope = np.sin(theta) / (np.sin(theta) + 1j * np.cos(theta))

  # 真机校准：S11 深度依赖于线宽匹配度
  # 最优线宽：series_w≈1.5mm, shunt_w≈1.1mm → S11≈-9.3 dB
  # 偏离最优值时 S11 退化（模拟阻抗失配）
  series_w_opt = 1.50 # 真机最优值
  shunt_w_opt = 1.12  # 真机最优值（接近50Ω）
  series_dev = abs(series_w_mm - series_w_opt) / series_w_opt
  shunt_dev = abs(shunt_w_mm - shunt_w_opt) / shunt_w_opt
  # S11 系数：最优时约0.34（-9.3 dB），偏离时增大（S11变差）
  s11_coeff = 0.34 * (1 + 2.0 * series_dev + 1.5 * shunt_dev)
  s11_coeff = min(s11_coeff, 0.95) # 限制最大值

  s[:, 0, 0] = s11_coeff * envelope # S11 (回波)
  s[:, 1, 0] = -1j * coupling * envelope # S21 (直通)
  s[:, 2, 0] = -coupling * envelope # S31 (耦合)
  s[:, 3, 0] = s11_coeff * envelope # S41 (隔离)

  # 互易性
  s[:, 0, 1] = s[:, 1, 0]
  s[:, 0, 2] = s[:, 2, 0]
  s[:, 0, 3] = s[:, 3, 0]

  # 对称性（简化）
  s[:, 1, 1] = s[:, 0, 0]
  s[:, 2, 2] = s[:, 0, 0]
  s[:, 3, 3] = s[:, 0, 0]

  # 归一化确保 passivity
  for i in range(n):
    row_mag = np.sum(np.abs(s[i]) ** 2, axis=1)
    scale = np.sqrt(row_mag)
    max_scale = np.max(scale)
    if max_scale > 0.99:
      s[i] *= 0.95 / max_scale

  return s




def _patch_sparams_2port(
  freq_ghz: np.ndarray,
  z0: float = 50.0,
  f0_ghz: float = 2.4,
  patch_len_mm: float = 40.0,
  feed_offset_mm: float = 10.0,
  patch_w_mm: float = 30.0,
  eps_eff: float = 2.33,
  s11_min_lin: float = 0.25,
  s11_far_lin: float = 0.7,
  bw_frac: float = 0.05,
) -> np.ndarray:
  """贴片天线 S 参数解析近似（v0 物理映射版）。

  矩形贴片：λ/2 谐振器，|S11| 远离 f_res 趋近全反射 s11_far_lin，
  在 f_res 处下陷到 s11_min_lin（馈电匹配物理值，Lorentzian 谷形）。
  匹配深度物理来源（一阶传输线模型）：
    R_in(x0) = R_edge·cos²(π·x0/L)，R_edge ≈ 60·λ0/W
  其中 x0 自辐射边起算（Balanis 谐振腔模型一阶近似，忽略 G12 与有限
  基板厚度修正）；s11_min = |（R_in-Z0)/(R_in+Z0)|。
  patch_len 决定 f_res（λ/2 反推），patch_w/feed_offset 决定谷深。
  """
  n = len(freq_ghz)
  s = np.zeros((n, 2, 2), dtype=complex)

  # 谐振频率由 patch_len 决定（λ/2 谐振）；eps_eff 联合校准锚（A1）
  _C = 3.0e8
  patch_len_m = patch_len_mm * 1e-3
  f_res_ghz = _C / (2 * patch_len_m * math.sqrt(eps_eff)) / 1e9

  # 频率失谐
  delta_f = (freq_ghz - f_res_ghz) / f_res_ghz
  # 谐振曲线（Lorentzian 型，谐振点=1）
  resonance = 1.0 / (1.0 + (delta_f / bw_frac) ** 2)

  # |S11|：远离谐振趋近全反射，谐振点下陷到 s11_min（馈电匹配物理值）
  s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
  s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
  s11_mag = s11_far - (s11_far - s11_min) * resonance
  s11_mag = np.clip(s11_mag, 0.0, 0.95)

  # S21（传输）：谐振时匹配最好、传输最大
  s21_mag = np.sqrt(np.maximum(1.0 - s11_mag ** 2, 0.0))

  # 组装 S 矩阵
  phase = np.exp(1j * np.random.uniform(0, 0.1, n))
  s[:, 0, 0] = s11_mag * phase # S11
  s[:, 1, 0] = s21_mag * phase # S21
  s[:, 0, 1] = s21_mag * phase # S12（互易）
  s[:, 1, 1] = s11_mag * phase # S22

  # 确保 passivity
  for i in range(n):
    row_mag = np.sum(np.abs(s[i]) ** 2, axis=1)
    scale = np.sqrt(row_mag)
    max_scale = np.max(scale)
    if max_scale > 0.99:
      s[i] *= 0.95 / max_scale

  return s


def _mline_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  line_len_mm: float = 40.0,
  tan_d: float = 0.0037,
) -> np.ndarray:
  """均匀微带线解析（WP2.1 锚模板，确定性闭式）。

  理想匹配：S11=S22≈0（1e-4 数值底——判废信号是 |S11| 显著非零）；
  S21 = exp(-αL)·exp(-jβL)，β=2πf√εeff/c（相速闭式，锚的核心判据），
  α=介质损耗 Np/m（α_d=πf√εeff·tanδ/c）。
  """
  f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
  c0 = 299792458.0
  beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / c0
  alpha_np = np.pi * f_hz * math.sqrt(eps_eff) * tan_d / c0
  length_m = line_len_mm * 1e-3
  s21 = np.exp(-alpha_np * length_m) * np.exp(-1j * beta * length_m)
  n = len(f_hz)
  s = np.zeros((n, 2, 2), dtype=complex)
  s[:, 0, 0] = 1e-4
  s[:, 1, 1] = 1e-4
  s[:, 0, 1] = s21
  s[:, 1, 0] = s21
  return s


def _cpw_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  line_len_mm: float = 40.0,
  tan_d: float = 0.0037,
) -> np.ndarray:
  """均匀共面波导解析（WP2.1 CPW 锚）——闭式同 _mline_sparams，
  εeff 由调用方按 skrf CPW 给出。"""
  return _mline_sparams(freq_ghz, eps_eff=eps_eff,
             line_len_mm=line_len_mm, tan_d=tan_d)


def _cps_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  line_len_mm: float = 40.0,
  tan_d: float = 0.0037,
) -> np.ndarray:
  """共面带 CPS 解析（C9 传输线族 II）——匹配端接均匀线闭式同 _mline_sparams
  （LumpedPort R=闭式 Z0 → S11≈0），εeff 由调用方按 _cps_ri 给出。"""
  return _mline_sparams(freq_ghz, eps_eff=eps_eff,
             line_len_mm=line_len_mm, tan_d=tan_d)


def _suspended_stripline_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  line_len_mm: float = 40.0,
  tan_d: float = 0.0037,
) -> np.ndarray:
  """悬置带线解析（C9 传输线族 II）——均匀线闭式同 _mline_sparams，
  εeff 由调用方按 _suspended_stripline_ri 给出。"""
  return _mline_sparams(freq_ghz, eps_eff=eps_eff,
             line_len_mm=line_len_mm, tan_d=tan_d)

def _wstep_sparams(
  freq_ghz: np.ndarray,
  eps_eff1: float,
  eps_eff2: float,
  z1: float,
  z2: float,
  seg_len_mm: float = 20.0,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
  *,
  seg2_len_mm: float | None = None,
  seg1_tan_d: float | None = None,
) -> np.ndarray:
  """微带宽度阶跃解析（WP2.2 基元）——两段理想 TL 的 ABCD 级联。

  确定性闭式裁判的 fake 侧同型：每段 γ=α+jβ（HJ εeff + 介质损耗），
  ABCD 级联后按 50Ω 归一成 S。理想阶跃=仅阻抗跳变（无阶梯寄生；
  引擎对照理想级的偏差正是锚判据要测的阶梯贡献）。

  S 矩阵按 Pozar T4.2 全矩阵口径（阻抗形式 denom=AZ0+B+CZ0²+DZ0）：
  S11=(AZ0+B−CZ0²−DZ0)/den、S22=(−AZ0+B−CZ0²+DZ0)/den——两段 Z 不同
  （z1≠z2，非对称是常态）时 S22≠S11，不得复用 S11（真值线性差
  0.43-0.74 的实证见 WP2.2 审查）；S12=S21=2Z0/den 依赖级联互易
  （det(ABCD)=1，TL 段精确成立）。

  seg2_len_mm（WP2.5 Tier 2 扩展，keyword-only）：第二段独立长度
  （sma_launcher 弹射的同轴短壳+长微带两级联）；None=同长（wstep/
  bend/via 原口径不变）。seg1_tan_d（sma tan_d_fill 变体）：
  第一段独立介质损耗（同轴 PTFE tanδ ≠ 微带基板 tanδ）；None=同 tan_d。

  级联序（第一性原理审查）：ABCD 总矩阵=输入侧段矩阵在左
  （M=M1@M2，series-then-shunt 的 Zin=Z+1/Y 检验锚定）——旧实现
  cur@prev 把第二段放在输入侧，端口标号镜像（|S11|≈|S22| 且 S21 互易
  不变，dB 域旧测试不可见）；修正后 port1=z1 侧与 openEMS 模板端口
  几何一致。
  """
  f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
  c0 = 299792458.0
  length_m = seg_len_mm * 1e-3
  length2_m = (seg2_len_mm if seg2_len_mm is not None
         else seg_len_mm) * 1e-3
  tan1 = tan_d if seg1_tan_d is None else float(seg1_tan_d)
  s = np.zeros((len(f_hz), 2, 2), dtype=complex)
  abcd_prev = np.eye(2, dtype=complex)
  for eps_eff, z_seg, seg_m, seg_tan in ((eps_eff1, z1, length_m, tan1),
                      (eps_eff2, z2, length2_m, tan_d)):
    beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / c0
    alpha_np = np.pi * f_hz * math.sqrt(eps_eff) * seg_tan / c0
    gamma = alpha_np + 1j * beta
    gl = gamma * seg_m
    ch, sh = np.cosh(gl), np.sinh(gl)
    # 逐频点 2x2 ABCD → 级联（输入侧矩阵在左：M_total = M1 @ M2）
    cur = np.empty((len(f_hz), 2, 2), dtype=complex)
    cur[:, 0, 0] = ch
    cur[:, 0, 1] = z_seg * sh
    cur[:, 1, 0] = sh / z_seg
    cur[:, 1, 1] = ch
    abcd_prev = abcd_prev @ cur
  a, b = abcd_prev[:, 0, 0], abcd_prev[:, 0, 1]
  cc, d = abcd_prev[:, 1, 0], abcd_prev[:, 1, 1]
  denom = a * z_ref + b + cc * z_ref * z_ref + d * z_ref
  s11 = (a * z_ref + b - cc * z_ref * z_ref - d * z_ref) / denom
  s21 = 2.0 * z_ref / denom
  s22 = (-a * z_ref + b - cc * z_ref * z_ref + d * z_ref) / denom
  s[:, 0, 0] = s11
  s[:, 1, 1] = s22
  s[:, 0, 1] = s21
  s[:, 1, 0] = s21
  return s


def _tjunc_sparams(
  freq_ghz: np.ndarray,
  z_arm: float,
  eps_eff: float,
  through_len_mm: float,
  branch_len_mm: float,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
) -> np.ndarray:
  """微带 T 接头解析（WP2.2 基元）——理想三端口结点 + 三条 HJ 线。

  确定性裁判同型：等臂无损结点 S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]
  （幺正互易），三条微带线（HJ εeff/模阻抗）经 skrf connect 逐一
  级联到结点。理想输入匹配地板 Sii=-1/3（-9.55dB）——无损互易
  三端口不可能全匹配（wilkinson 隔离电阻存在的物理原因）。
  """
  import skrf

  f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
  freq = skrf.Frequency(f_hz[0] / 1e9, f_hz[-1] / 1e9, len(f_hz),
             unit="GHz")
  node = np.array([[-1.0, 2.0, 2.0], [2.0, -1.0, 2.0],
           [2.0, 2.0, -1.0]]) / 3.0
  s_node = np.tile(node, (len(f_hz), 1, 1)) # skrf 需 (nfreq,n,n)
  net = skrf.Network(frequency=freq, s=s_node, z0=z_ref)
  # 三条臂线：HJ εeff 的均匀线（模阻抗用 z_arm 归一，保证结点口径一致）
  line_thru = skrf.media.DefinedGammaZ0(
    frequency=freq, z0=z_arm, gamma=_tl_gamma(f_hz, eps_eff, tan_d)
  ).line(through_len_mm, unit="mm", z0=z_arm)
  line_branch = skrf.media.DefinedGammaZ0(
    frequency=freq, z0=z_arm, gamma=_tl_gamma(f_hz, eps_eff, tan_d)
  ).line(branch_len_mm, unit="mm", z0=z_arm)
  net = skrf.network.connect(net, 0, line_thru, 0)
  net = skrf.network.connect(net, 1, line_thru, 0)
  net = skrf.network.connect(net, 0, line_branch, 0)
  net.renormalize([z_ref, z_ref, z_ref])
  s = np.zeros((len(f_hz), 3, 3), dtype=complex)
  s[:, :, :] = net.s
  return s


def _tl_gamma(freq_hz: np.ndarray, eps_eff: float, tan_d: float) -> np.ndarray:
  """均匀 TL 复传播常数 γ=α+jβ（介质损耗一阶）。"""
  c0 = 299792458.0
  beta = 2.0 * np.pi * freq_hz * math.sqrt(eps_eff) / c0
  alpha_np = np.pi * freq_hz * math.sqrt(eps_eff) * tan_d / c0
  return alpha_np + 1j * beta


def _bend_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  arm_len_mm: float = 20.0,
  z_arm: float = 50.0,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
) -> np.ndarray:
  """微带直角弯折解析（WP2.2 基元）——理想级联（两段同宽 TL 级联）。

  同宽两段直接级联在闭式里完全匹配（弯角寄生为零）——引擎对照
  理想的唯一偏差即弯角寄生贡献，|S11| 绝对门 -15dB（未切角直角
  弯折文献口径）。
  """
  return _wstep_sparams(freq_ghz, eps_eff1=eps_eff, eps_eff2=eps_eff,
             z1=z_arm, z2=z_arm, seg_len_mm=arm_len_mm,
             tan_d=tan_d, z_ref=z_ref)


def _via_sparams(
  freq_ghz: np.ndarray,
  eps_eff: float,
  feed_len_mm: float = 60.0,
  z_feed: float = 50.0,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
) -> np.ndarray:
  """过孔过渡解析（WP2.2 收官基元）——理想过孔=两馈线直接级联。

  确定性裁判口径：同宽两段 50Ω 馈线级联完全匹配（过孔寄生为零的
  闭式极限）；引擎对照理想（skrf 同源）的唯一偏差=过孔柱+反焊盘
  的寄生贡献，|S11| 绝对门 -10dB（设计良好的过孔量级）。
  """
  return _wstep_sparams(freq_ghz, eps_eff1=eps_eff, eps_eff2=eps_eff,
             z1=z_feed, z2=z_feed, seg_len_mm=feed_len_mm,
             tan_d=tan_d, z_ref=z_ref)


def _atten_pi_sparams(
  freq_ghz: np.ndarray,
  atten_db: float = 10.0,
  z_ref: float = 50.0,
) -> np.ndarray:
  """π 型衰减器解析（WP2.3 首族）——理想电阻网络 ABCD 闭式。

  电阻值由 E4 attenuator_pi 闭式给出（ABCD 校验），理想 lumped 无
  频率相依：|S21| = -atten_db 平坦、S11 = 0（按设计匹配）。
  引擎对照理想的偏差= lumped 寄生（锚判据测的量）。
  """
  k = 10 ** (atten_db / 20.0)
  r_sh = z_ref * (k + 1) / (k - 1)
  r_ser = z_ref * (k * k - 1) / (2.0 * k)
  n = len(freq_ghz)
  s = np.zeros((n, 2, 2), dtype=complex)
  # ABCD = Shunt(1/R_sh) · Series(R_ser) · Shunt(1/R_sh)
  a = 1.0 + r_ser / r_sh
  b = r_ser
  c = 2.0 / r_sh + r_ser / (r_sh * r_sh)
  d = a
  denom = a + b / z_ref + c * z_ref + d
  s[:, 0, 0] = (a + b / z_ref - c * z_ref - d) / denom
  s[:, 0, 1] = 2.0 / denom
  s[:, 1, 0] = 2.0 / denom
  s[:, 1, 1] = s[:, 0, 0]
  return s


def _atten_t_sparams(
  freq_ghz: np.ndarray,
  atten_db: float = 10.0,
  z_ref: float = 50.0,
) -> np.ndarray:
  """T 型衰减器解析（WP2.3 横向变体）——理想电阻网络 ABCD 闭式。

  Series(R_s) · Shunt(R_mid) · Series(R_s) 级联，|S21|=-atten_db
  平坦、S11=0（按设计匹配）。引擎偏差= lumped 寄生贡献。
  """
  k = 10 ** (atten_db / 20.0)
  r_ser = z_ref * (k - 1) / (k + 1)
  r_mid = z_ref * 2.0 * k / (k * k - 1)
  n = len(freq_ghz)
  s = np.zeros((n, 2, 2), dtype=complex)
  abcd_prev = np.eye(2, dtype=complex)
  for abcd in (np.array([[1.0, r_ser], [0.0, 1.0]]),
         np.array([[1.0, 0.0], [1.0 / r_mid, 1.0]]),
         np.array([[1.0, r_ser], [0.0, 1.0]])):
    abcd_prev = abcd @ abcd_prev
  a, b = abcd_prev[0, 0], abcd_prev[0, 1]
  c, d = abcd_prev[1, 0], abcd_prev[1, 1]
  denom = a + b / z_ref + c * z_ref + d
  s[:, 0, 0] = (a + b / z_ref - c * z_ref - d) / denom
  s[:, 0, 1] = 2.0 / denom
  s[:, 1, 0] = 2.0 / denom
  s[:, 1, 1] = s[:, 0, 0]
  return s


def _ratrace_sparams(
  freq_ghz: np.ndarray,
  atten_split_db: float = 3.0103,
  z_ref: float = 50.0,
) -> np.ndarray:
  """rat-race 环形电桥解析（WP2.3）——理想 180° 混合环 S 矩阵（f0 闭式）。

  端口标签与 openEMS 模板一致（#208 理论核验轮定版）：1=Σ（geo 0°）、
  2=out1（60°）、3=Δ（120°）、4=out2（300°，Σ 另一侧 λ/4）；
  arcs λ/4×3 + 3λ/4
  （环 70.7Ω，周长 1.5λg）。

  推导（Y 矩阵装配，理论核验）：环按四弧拆解为节点导纳
  矩阵，λ/4 弧 Y12=j/Zr（csc90），3λ/4 弧 Y12=−j/Zr（csc270），节点
  对角为零（cot90=cot270=0）→ M=[[0,1,0,1],[1,0,1,0],[0,1,0,−1],
  [1,0,−1,0]]，M²=2I；Z0/Zr=1/√2 时 S=(I−jgM)(I+jgM)⁻¹=−jM/√2。

  性质：Σ 激励 → out1/out2 各 −j/√2（同相 −3dB）、Δ 隔离、全匹配；
  Δ 激励 → out1=−j/√2 / out2=+j/√2（反相，180° 混合环定义性质）；
  out1↔out2 互相隔离（旧版"Pozar 教材编号"把输出放在 2/3、Δ 在 4，
  与模板端口几何错位——#154 同族，#208 修正）。
  """
  s = np.zeros((len(freq_ghz), 4, 4), dtype=complex)
  g = 1.0 / math.sqrt(2.0)
  s[:, 1, 0] = s[:, 0, 1] = -1j * g  # Σ ↔ out1
  s[:, 3, 0] = s[:, 0, 3] = -1j * g  # Σ ↔ out2（同相）
  s[:, 2, 1] = s[:, 1, 2] = -1j * g  # out1 ↔ Δ
  s[:, 3, 2] = s[:, 2, 3] = 1j * g  # Δ ↔ out2（反相耦合）
  # 隔离对（Σ↔Δ、out1↔out2）保持 0；诊断地板（数值零）
  s[:, 2, 0] = s[:, 0, 2] = 1e-10
  s[:, 3, 1] = s[:, 1, 3] = 1e-10
  return s


def _gysel_sparams(
  freq_ghz: np.ndarray,
  atten_split_db: float = 3.0103,
  z_ref: float = 50.0,
) -> np.ndarray:
  """Gysel 功分器解析（WP2.3 横向变体）——理想六节环 S 矩阵（f0 闭式）。

  拓扑（#206 理论核验轮定版，对照 Microwaves101 "Gysel even/odd mode
  analysis"）：P1—[√2·Z0 λ/4 臂]—P2/P3；P2/P3—[Z0 λ/4 隔离线]—Δ1/Δ2；
  Δ1—[Z0 λ/2 桥带，中点开路]—Δ2；Δ1/Δ2 各端接 Z0 负载。端口标签与
  openEMS 模板一致：1=输入 P1、2/3=输出 P2/P3（3 端口对外，负载为
  内部端接）。

  推导（偶/奇模半电路，skrf 六段线+双负载 Y 装配 @f0 数值实证）：
  偶模：λ/4 臂把 Σ 结点 2·Z0 变换为 Z0（Γe=0）；桥带中点开路经 λ/4
  变短路压 Δ 点、再经 λ/4 隔离线变开路——负载支路输出端不可见。
  奇模：P1 结点/桥带中点=虚拟地，臂与桥带 λ/4 变开路，输出只见 λ/4
  隔离线端接 Z0（Γo=0，被吸收）。S22=(Γe+Γo)/2=0、S32=(Γe−Γo)/2=0。
  判废锚（同轮对照）：无桥带朴素拓扑 S21=-6.53dB/S11=-9.5dB；合并
  单负载拓扑 S21=-9.03dB/S32=-2.5dB——λ/2 桥带是隔离的必要环节。

  性质：P1 激励 → P2/P3 各 −j/√2（同相 −3.01dB，λ/4 臂传输相位）、
  全端口匹配、P2↔P3 互隔离（大功率设计：隔离负载外置可独立散热）。
  窄带理想化：匹配/均分/隔离在 f0 处准确（同 ratrace fake 口径）。
  """
  s = np.zeros((len(freq_ghz), 3, 3), dtype=complex)
  g = 1.0 / math.sqrt(2.0)
  s[:, 1, 0] = s[:, 0, 1] = -1j * g  # P1 ↔ P2（λ/4 臂，-90°）
  s[:, 2, 0] = s[:, 0, 2] = -1j * g  # P1 ↔ P3（同相）
  # 隔离对（P2↔P3）与全对角保持 0；诊断地板（数值零）
  s[:, 2, 1] = s[:, 1, 2] = 1e-10
  s[:, 0, 0] = s[:, 1, 1] = s[:, 2, 2] = 1e-10
  return s


# hairpin 抽头外部 Q 的真机修正 c(τ)=Q_e_EM/Q_e_closed（线性 c0+c1·τ）：
# 单谐振器双抽头 τ 扫描真机标定产物（scripts/hairpin_q_extract.py --analyze），
# 数值只在内核（铁律 7）、不得手改。
# 真机实测（τ=0.30/0.36/0.40/0.43 四点）：过质量门（0.3/0.5dB
# 两窗曲率一致 + FWHM≤窗半）τ=0.40（Q_e_EM=17.659 vs 闭式 16.450，c=1.0735）与 τ=0.43
# （34.691 vs 33.009，c=1.0509）两点线性；τ=0.30/0.36 强过耦合（直通背景平台、FWHM>窗半，
# 非窄带单极点）如实排除。标定域 τ∈[0.40,0.43]，域外为线性外推。
_HAIRPIN_QE_CORR: tuple[float, float] = (1.37437, -0.75218)
# hairpin 谐振频率真机修正 c_f0=f0_EM/f0_closed（同一 arm_len）：N=3
# 复跑真机标定（通带中心 2.5925GHz vs 闭式
# λg/2 设计 2.5 → 1.0370；U 弯+开路端等效缩短，pt0-pt3 四轮同值 +3.7%）。名义 arm_len
# 按 L·f0_act/f0（f∝1/L）定版后，fake 与 EM 在名义处同 f0；数值只在内核、不得手改。
_HAIRPIN_F0_CORR: float = 1.0370


def hairpin_coupling_matrix(k_list: list[float], qe: float,
              fbw_g: float = 0.05) -> list[list[float]]:
  """(k_list, Q_e) → N+2 归一化耦合矩阵（对角 0；规范 fbw_g 任意，响应不变）。

  M_{i,i+1}=k_i/fbw_g、M_{0,1}=M_{N,N+1}=√(1/(fbw_g·Q_e))（Hong §5.2/§5.3 映射
  k=FBW·|M|、Q_e=1/(FBW·|M_{0,1}|²) 的精确逆），喂 coupling_matrix_response
  (fbw=fbw_g, external_q=[1,1])。
  #1b 模型审计（test_hairpin_template 钉住）：fbw_g∈{0.02,0.05,0.10,
  0.5,1.0} 五规范 max|ΔS|=0（精确规范不变——源/载对角项 1 与 m01∝g^-1/2、内耦合
  ∝g^-1、ω∝g^-1 在响应中联合消去 g）；历史"fbw=1 偏差 6000dB"是把固定归一化
  矩阵直接换 fbw 喂响应（未按上式重归一）的实现口径，不是物理。
  """
  ks = [float(k) for k in k_list]
  n = len(ks) + 1
  g = float(fbw_g)
  q = float(qe)
  if not 0.0 < g <= 1.0:
    raise ValueError("fbw_g 须在 (0,1]")
  if q <= 0.0 or any(k <= 0.0 for k in ks):
    raise ValueError("Q_e 与 k 须 >0")
  m = np.zeros((n + 2, n + 2), dtype=float)
  m01 = math.sqrt(1.0 / (g * q))
  m[0, 1] = m[1, 0] = m01
  m[n, n + 1] = m[n + 1, n] = m01
  for i, k in enumerate(ks, start=1):
    m[i, i + 1] = m[i + 1, i] = k / g
  return m.tolist()


def _hairpin_sparams(
  freq_ghz: np.ndarray,
  f0_ghz: float = 2.5,
  order: int = 3,
  fbw: float = 0.05,
  rl_db: float = 20.0,
  z_ref: float = 50.0,
  *,
  k_list: list[float] | None = None,
  qe: float | None = None,
) -> np.ndarray:
  """发夹线带通滤波器解析（WP2.3 滤波器族）——耦合矩阵理想频响。

  电气量 (k_list, Q_e) 优先：由几何反演给出（gap→k KJ 闭式、tap_frac→Q_e 抽头
  闭式 × c(τ)，在适配器派发处完成，收口 A4 接通）；缺省时退回 C13
  设计点（fbw/rl_db 常数锚：k=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)，与旧口径
  逐位一致）。矩阵经 hairpin_coupling_matrix 以规范 fbw_g=fbw 重归一（规范不变，
  见其 docstring），响应走 core/calculators coupling_matrix_response（S22=S11/
  S12=S21 对称口径）。f0 由调用方按 λg/2 反演传入（arm_len_mm 下降沿响应）。
  """
  from rfauto.core.calculators import coupling_matrix_response

  n = int(order)
  if k_list is None or qe is None:
    from rfauto.core.synthesis import synthesize_bpf_model

    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                   fbw=float(fbw), rl_db=float(rl_db),
                   topology="folded")
    if not synth.get("ok"):
      raise ValueError(f"hairpin fake: C13 综合失败: {synth.get('errors')}")
    arr = np.asarray(synth["coupling_matrix"], dtype=float)
    if arr.ndim == 3:
      arr = np.hypot(arr[..., 0], arr[..., 1])
    if k_list is None:
      k_list = [float(fbw) * abs(arr[i, i + 1]) for i in range(1, n)]
    if qe is None:
      qe = 1.0 / (float(fbw) * abs(arr[0, 1]) ** 2)
  if len(k_list) != n - 1:
    raise ValueError(f"hairpin fake: k_list 长度须为 order-1={n - 1}")
  resp = coupling_matrix_response(
    freq_ghz=[float(v) for v in freq_ghz], f0_ghz=float(f0_ghz),
    fbw=float(fbw), matrix=hairpin_coupling_matrix(k_list, qe, float(fbw)),
    z_ref=float(z_ref))
  cube = np.asarray(resp["s_matrix"], dtype=float)  # (n,2,2,[re,im])
  return cube[..., 0] + 1j * cube[..., 1]


def _msl_cpw_sparams(
  freq_ghz: np.ndarray,
  eps_eff1: float,
  eps_eff2: float,
  z1: float,
  z2: float,
  seg_len_mm: float,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
) -> np.ndarray:
  """MSL↔CPWG 过渡解析（WP2.5 Tier 2）——两段等长理想 TL 的 ABCD 级联。

  wstep 族同型裁判：理想过渡 = MSL 直段 + CPWG 直段直接级联（阶梯渐变/
  地缘突变/接地过孔栅栏寄生为零的闭式极限）；引擎对照理想的偏差即过渡
  寄生贡献。z1/z2、εeff1/εeff2 各自独立（HJ 微带口径 / CPWG 共形映射
  口径），渐变区长度 trans_len 不进理想级联（理想=突变对接）。
  """
  return _wstep_sparams(freq_ghz, eps_eff1=eps_eff1, eps_eff2=eps_eff2,
             z1=z1, z2=z2, seg_len_mm=seg_len_mm,
             tan_d=tan_d, z_ref=z_ref)


def _sma_launcher_sparams(
  freq_ghz: np.ndarray,
  eps_eff_coax: float,
  eps_eff_msl: float,
  z_coax: float,
  z_msl: float,
  coax_len_mm: float,
  msl_len_mm: float,
  tan_d: float = 0.0037,
  z_ref: float = 50.0,
  *,
  tan_d_coax: float | None = None,
) -> np.ndarray:
  """SMA 边缘弹射解析（WP2.5 Tier 2）——同轴段+微带段理想级联。

  理想弹射 = 同轴 TEM 段（PTFE 填充 εeff=εr 精确）+ MSL 段直接级联
  （搭焊段/切口/壳端开口寄生为零的闭式极限）；引擎对照理想的偏差即
  弹射寄生贡献，|S11| 对照文献曲线（edge-launch SMA 带内回损常规 15-20dB、
  保守地板 -10dB）。两段长度独立（seg2_len_mm 口径）；tan_d=微带基板
  tanδ，tan_d_coax=同轴 PTFE tanδ（模板 tan_d_fill 变体，None=同 tan_d）。
  """
  return _wstep_sparams(freq_ghz, eps_eff1=eps_eff_coax,
             eps_eff2=eps_eff_msl, z1=z_coax, z2=z_msl,
             seg_len_mm=coax_len_mm, tan_d=tan_d, z_ref=z_ref,
             seg2_len_mm=msl_len_mm, seg1_tan_d=tan_d_coax)


def _dipole_sparams(
  freq_ghz: np.ndarray,
  dipole_len_mm: float = 58.0,
  z0: float = 50.0,
  r_rad: float = 73.0,
  q: float = 6.0,
) -> np.ndarray:
  """半波振子单端口解析（WP1.3）：λ/2 自由空间谐振闭式 + 串联谐振一阶模型。

  f_res = c/(2L)（自由空间 λ/2 设计口径，端效应忽略）；R_rad≈73Ω
  （Balanis 半波振子辐射电阻）；X(f) = R·Q·(f/f0 − f0/f)。谷深
  ≈−14.5dB、谷位随 L 精确移动——数据工厂语义：L 是唯一进判据的
  自由度，带宽/谷深为一阶近似（不进锚判据）。单端口 (n,1,1)。
  """
  f_res_ghz = 299.792458 / (2.0 * dipole_len_mm)
  x = r_rad * q * (freq_ghz / f_res_ghz - f_res_ghz / freq_ghz)
  s11 = (r_rad + 1j * x - z0) / (r_rad + 1j * x + z0)
  s = np.zeros((len(freq_ghz), 1, 1), dtype=complex)
  s[:, 0, 0] = s11
  return s


def _coupled_bpf_sparams(
  freq_ghz: np.ndarray,
  widths_mm: list[float] | tuple[float, ...],
  gaps_mm: list[float] | tuple[float, ...],
  res_len_mm: float,
  feed_len_mm: float,
  f0_ghz: float = 2.5,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
) -> np.ndarray:
  """平行耦合 BPF 解析（WP2.3 BPF 族锚）——几何 → 耦合段电气量 → 电路级联。

  裁判同源闭式：openems_templates.coupled_bpf_circuit_sparams（每耦合段
  = 偶/奇模 2 端口叠加 4 端口 S、两交叉口开路端接压成 2 端口、与 50Ω 馈线
  ABCD 级联；无耗/互易由构造保证，test_coupled_bpf_template 钉住）。

  #154 纪律（列表参数两通道同索引同语义，与 _coupled_bpf_layout 逐参数对齐）：
  - widths_mm[j] / gaps_mm[j] = 第 j 个耦合段线宽 / 边到边缝
   （j=0 输入馈-腔 … j=N 腔-输出馈；长度 N+1 ⇒ order=N 由列表长度推出）；
   每段 (w,s) → KJ 1984 准静态 (Z0e,Z0o,εeff_e,εeff_o)
   （coupled_microstrip_even_odd_ohm @f0，同综合链口径）。
  - res_len_mm = 谐振器 1 物理长；耦合段长逐段 =
   _coupled_bpf_section_lengths_mm 逐端 Δl 修正派生（与 openEMS 渲染
   _coupled_bpf_layout 同源 helper，防双源漂移），以 design
   "section_len_mm" 传入裁判（缺键回退均匀 lc=res_len/2）。
  - feed_len_mm = 50Ω 馈线物理长（裁判馈线 = 理想 z_ref 线，相位按物理长）。
  - w_feed_mm 只进几何（50Ω 线宽由 HJ 综合定），不进电气模型——同
   atten_pi/atten_t 的 w_mm 口径，如实标注。
  已知口径限制同裁判：宽度台阶不连续性、开路端边缘导纳残差、KJ 色散
  不进模型（EM 冒烟实测其总量，平行耦合 BPF 段）。
  """
  from rfauto.adapters.openems_templates import (
    _coupled_bpf_section_lengths_mm,
    coupled_bpf_circuit_sparams,
    coupled_microstrip_even_odd_ohm,
  )

  widths = [float(v) for v in widths_mm]
  gaps = [float(v) for v in gaps_mm]
  if len(widths) != len(gaps) or len(widths) < 2:
    raise ValueError(
      f"coupled_bpf fake: widths_mm/gaps_mm 须等长且 ≥2（order+1），得 "
      f"{len(widths)}/{len(gaps)}")
  if any(v <= 0.0 for v in (*widths, *gaps)):
    raise ValueError("coupled_bpf fake: widths_mm/gaps_mm 须 >0")
  if not (float(res_len_mm) > 0.0 and float(feed_len_mm) > 0.0):
    raise ValueError("coupled_bpf fake: res_len_mm/feed_len_mm 须 >0")
  sections = []
  for w, s in zip(widths, gaps, strict=True):
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
      w, s, float(f0_ghz), float(er), float(h_mm))
    sections.append({"zee_ohm": ze, "zoo_ohm": zo,
             "ere_e": ere_e, "ere_o": ere_o})
  design = {
    "order": len(widths) - 1,
    "f0_ghz": float(f0_ghz),
    "feed_len_mm": float(feed_len_mm),
    # 逐端 Δl 修正段长（与渲染同源 helper）——防双源漂移
    "section_len_mm": _coupled_bpf_section_lengths_mm(
      widths, float(res_len_mm), float(f0_ghz), float(er),
      float(h_mm)),
    "sections": sections,
  }
  return coupled_bpf_circuit_sparams(
    np.asarray(freq_ghz, dtype=float), design, z_ref=float(z_ref))


# C3 滤波器族 II（interdigital/combline/sir_bpf，注册）：模块内常量
# 副本（同 _ANT2_TEMPLATES 口径：fake 对 openems_templates 只做惰性导入）
_C3_TEMPLATES: tuple[str, ...] = ("interdigital", "combline", "sir_bpf")


def _c3_sparams(
  freq_ghz: np.ndarray,
  template: str,
  params: dict[str, Any],
  f0_ghz: float = 2.5,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
  *,
  l_via_h: float | None = 0.0,
) -> np.ndarray:
  """C3 滤波器族解析（交指/梳状/SIR）——几何 → KJ 倒置器 → 并联谐振 J 链。

  裁判同源闭式：openems_templates.c3_circuit_sparams 几何模式（缝列表经 KJ
  1984 回代倒置器值 |J|=(Z0e−Z0o)/(2Z0eZ0o)、谐振棒 HJ 阻抗/介质 + 开路端 Δl
  等效长度、理想 z_ref 馈线，ABCD 级联；无耗/互易由构造保证，test_c3_*
  钉住）。同一模板下 fake 与电路裁判只差参数舍入（同源，非拟合）。

  l_via_h=接地过孔电感（H，§C3 口径 8/10）：0.0（缺省）=理想短路——正式
  契约，逐位复现旧名义（旧黄金钉保持，登记⑨ 保守判定）；None=按几何自动取
  c3_via_inductance_h(h_mm)（真机裁判口径，配补偿后名义几何用）；显式
  float=指定电感（H）。

  #154 纪律（三通道同索引同语义，与 _c3_layout 逐参数对齐）：
  - gaps_mm[j]=第 j 缝边到边（j=0 输入馈-棒1 … j=N 棒N-输出馈；长度 N+1
   ⇒ order 由列表长度校验）；耦合区棒宽 = w_mm（interdigital/combline）或
   w_low_mm（sir_bpf 低阻段）。
  - interdigital：res_len_mm=棒物理长（λ/4−Δl−过孔缩短），谐振
   Y=−j·cotθ/Z_r（过孔端接式见口径 8）；
   combline：res_len_mm + c_load_pf 独立进裁判（可失调），Y=jωC−j·cotθ/Z_r；
   sir_bpf：l_low_mm/l_high_mm 两段物理长 + w_low/w_high 定 Z_lo/Z_hi。
  - feed_len_mm=50Ω 馈线物理长（裁判馈线=理想 z_ref 线，相位按物理长）；
   馈线宽只进几何。
  已知口径限制同裁判：邻耦合近似（非邻耦合不进模型）、棒端/过孔寄生、
  KJ 色散——EM 冒烟实测其总量（openems_templates §C3 段首假设清单）。
  """
  from rfauto.adapters.openems_templates import C3_TEMPLATES, c3_circuit_sparams

  if template not in C3_TEMPLATES:
    raise ValueError(f"c3 fake: 非 C3 模板 {template}（可用 {C3_TEMPLATES}）")
  return c3_circuit_sparams(
    template, np.asarray(freq_ghz, dtype=float), dict(params),
    f0_ghz=float(f0_ghz), er=float(er), h_mm=float(h_mm),
    z_ref=float(z_ref), l_via_h=l_via_h)


def _cline_coupler_sparams(
  freq_ghz: np.ndarray,
  w_mm: float,
  gap_mm: float,
  coupled_len_mm: float,
  f0_ghz: float = 2.5,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
  *,
  synchronous_tem: bool = False,
) -> np.ndarray:
  """耦合线定向耦合器解析（§C4 口径 1）——几何 → KJ 偶/奇模 → 4 端口频响。

  裁判同源闭式 openems_templates.coupled_line_coupler_sparams：(w,s) →
  Kirschning-Jansen (Z0e,Z0o,εeff_e,εeff_o) @f0 → 偶/奇模 2 端口叠加 4 端口
  （无耗/互易由构造保证）。端口 1/2=线 A 近/远端（输入/直通）、3/4=线 B
  近/远端（耦合/隔离）。默认真非同步相速（coupled_bpf 同口径；名义 10dB
  设计 @f0 残差 S41≈−23dB/S11≈−33dB=微带定向性固有极限）；
  synchronous_tem=True 为理想 TEM 裁判极限（f0 处 |S31|=C、S11=S41=0）。
  w_feed_mm 只进几何（50Ω 线宽由 HJ 综合定），不进电气模型。
  """
  from rfauto.adapters.openems_templates import (
    coupled_line_coupler_sparams,
    coupled_microstrip_even_odd_ohm,
  )

  if min(float(w_mm), float(gap_mm), float(coupled_len_mm)) <= 0.0:
    raise ValueError("cline_coupler fake: w_mm/gap_mm/coupled_len_mm 须 >0")
  ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
    float(w_mm), float(gap_mm), float(f0_ghz), float(er), float(h_mm))
  return coupled_line_coupler_sparams(
    np.asarray(freq_ghz, dtype=float), ze, zo, float(coupled_len_mm),
    ere_e, ere_o, synchronous_tem=synchronous_tem, z_ref=float(z_ref))


def _lange_sparams(
  freq_ghz: np.ndarray,
  w_mm: float,
  gap_mm: float,
  finger_len_mm: float,
  f0_ghz: float = 2.5,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
) -> np.ndarray:
  """Lange 电桥解析（§C4 口径 3）——相邻指 KJ → 四线等效两线 → 理想偶/奇模。

  (w,s) → KJ 相邻对 (Z0e,Z0o) → Pozar 四线换算 (Ze4,Zo4) →
  coupled_line_coupler_sparams(synchronous_tem=True)：相邻对 KJ εeff_e/
  εeff_o 不是四线等效模的相速（多导体模式），只取其平均作 λ/4 电长口径，
  Lange 只给理想裁判（ratrace/gysel 窄带理想化同口径）。f0 处
  |S21|=|S31|=−3.01dB、S31=+1/√2 同相、S21=−j/√2、S11=S41=0。
  """
  from rfauto.adapters.openems_templates import (
    coupled_line_coupler_sparams,
    coupled_microstrip_even_odd_ohm,
    lange_equivalent_zee_zoo,
  )

  if min(float(w_mm), float(gap_mm), float(finger_len_mm)) <= 0.0:
    raise ValueError("lange fake: w_mm/gap_mm/finger_len_mm 须 >0")
  ze_p, zo_p, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
    float(w_mm), float(gap_mm), float(f0_ghz), float(er), float(h_mm))
  ze4, zo4 = lange_equivalent_zee_zoo(ze_p, zo_p)
  return coupled_line_coupler_sparams(
    np.asarray(freq_ghz, dtype=float), ze4, zo4, float(finger_len_mm),
    ere_e, ere_o, synchronous_tem=True, z_ref=float(z_ref))


def _branchline_2sect_sparams(
  freq_ghz: np.ndarray,
  w_main_mm: float,
  w_out_mm: float,
  w_mid_mm: float,
  sect_len_mm: float,
  branch_len_mm: float,
  f0_ghz: float = 2.5,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
) -> np.ndarray:
  """两节分支线解析（§C4 口径 2）——线宽 → HJ (Z,εeff) → 偶/奇模二分频响。

  裁判同源闭式 openems_templates.branchline_2sect_sparams：三种线宽各经
  skrf HJ 正向得 (Z_a,Z_b1,Z_b2) 与 εeff，主线节/支臂电长按各自物理长
  独立评估（几何参数变化有真实频响）；f0 处经典点 |S21|=|S31|=−3.01dB、
  S21=−1/√2（−180°）、S31=+j/√2、S11=S41=0。w_feed_mm 只进几何。
  """
  from rfauto.adapters.openems_templates import branchline_2sect_sparams
  from rfauto.core.synthesis import Stackup, forward_z0

  if min(float(w_main_mm), float(w_out_mm), float(w_mid_mm),
      float(sect_len_mm), float(branch_len_mm)) <= 0.0:
    raise ValueError("branchline_2sect fake: 几何参数须 >0")
  stackup = Stackup(name="branchline_2sect", epsilon_r=float(er),
           thickness_mm=float(h_mm))
  za, ere_a = forward_z0(float(w_main_mm), float(f0_ghz), stackup)
  zb1, ere_b1 = forward_z0(float(w_out_mm), float(f0_ghz), stackup)
  zb2, ere_b2 = forward_z0(float(w_mid_mm), float(f0_ghz), stackup)
  return branchline_2sect_sparams(
    np.asarray(freq_ghz, dtype=float), za, zb1, zb2,
    float(sect_len_mm), float(branch_len_mm), ere_a, ere_b1, ere_b2,
    z_ref=float(z_ref))


def _stepped_impedance_sparams(
  freq_ghz: np.ndarray,
  z1_width_mm: float,
  z2_width_mm: float,
  seg_len_mm: float,
  n_segments: int,
  f0_ghz: float = 2.4,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
) -> np.ndarray:
  """阶梯阻抗线解析（初始模板补注册）——HJ (Z,εeff) → cosim
  ABCD 级联频响（无耗/互易由构造保证）。

  几何口径（openems_templates._stepped_lines 渲染同源，#154 同名同语义）：
  段链奇偶交替——偶数段（0 基）宽 z1_width_mm、奇数段宽 z2_width_mm，每段
  物理长 seg_len_mm；两端 feed 段（板边 BOARD=60mm → 段链端点）宽=z1 宽、
  长各 = BOARD − n·seg_len/2（进模型：MSLPort 端口面在板边）。每段独立
  HJ 正向 (Z_i, εeff_i)（core/synthesis.forward_z0 唯一介质口径，铁律 1c），
  电长 θ_i(f)=2πf√εeff_i·L_i/c；级联走 core.cosim.cascade_two_port_networks
  （ABCD 乘法，数据工厂与 cosim 复用同一内核，不自造级联）。
  独立裁判：skrf 级联同链 ≤1e-10（test_stepped_coupled_line_specs）。
  已知口径限制：阶梯跳宽处边缘场/不连续性不进模型（EM 冒烟实测其总量，
  wstep 同口径假设清单）。
  """
  from rfauto.adapters.openems_templates import _tl_two_port_s
  from rfauto.core.cosim import CascadeBlock, cascade_two_port_networks
  from rfauto.core.synthesis import Stackup, forward_z0

  if not (float(z1_width_mm) > 0.0 and float(z2_width_mm) > 0.0
      and float(seg_len_mm) > 0.0 and int(n_segments) >= 1):
    raise ValueError("stepped_impedance fake: 几何参数须 >0 且 n_segments ≥ 1")
  f = np.asarray(freq_ghz, dtype=float)
  stackup = Stackup(name="stepped_impedance", epsilon_r=float(er),
           thickness_mm=float(h_mm))
  z1, ere1 = forward_z0(float(z1_width_mm), float(f0_ghz), stackup)
  z2, ere2 = forward_z0(float(z2_width_mm), float(f0_ghz), stackup)
  board_mm = 60.0            # _stepped_lines 渲染 BOARD 字面量
  feed_len_mm = board_mm - int(n_segments) * float(seg_len_mm) / 2.0
  if feed_len_mm <= 0.0:
    raise ValueError("stepped_impedance fake: 段链总长超出板边（feed ≤0）")

  def _sec_s(z_ohm: float, ere: float, len_mm: float) -> np.ndarray:
    theta = 2.0 * np.pi * f * math.sqrt(ere) * len_mm / _ANT2_C_MM_GHZ
    return np.stack([_tl_two_port_s(z_ohm, float(th), float(z_ref))
             for th in theta])

  blocks = [CascadeBlock(name="feed_in", s_params=_sec_s(z1, ere1, feed_len_mm),
              freq_ghz=f)]
  for i in range(int(n_segments)):
    z_i, ere_i = (z1, ere1) if i % 2 == 0 else (z2, ere2)
    blocks.append(CascadeBlock(
      name=f"seg_{i}", s_params=_sec_s(z_i, ere_i, float(seg_len_mm)),
      freq_ghz=f))
  blocks.append(CascadeBlock(name="feed_out",
                s_params=_sec_s(z1, ere1, feed_len_mm),
                freq_ghz=f))
  return cascade_two_port_networks(blocks)


def _coupled_line_sparams(
  freq_ghz: np.ndarray,
  coupled_len_mm: float,
  line_w_mm: float,
  gap_mm: float,
  f0_ghz: float = 2.4,
  er: float = 3.66,
  h_mm: float = 0.508,
  z_ref: float = 50.0,
) -> np.ndarray:
  """耦合线解析（初始模板补注册）——KJ 偶/奇模 → 4 端口
  port4 端接 z_ref 化 3 端口频响。

  (w,s) → Kirschning-Jansen (Z0e,Z0o,εeff_e,εeff_o) @f0（复用 adapters 层
  既有内核 coupled_microstrip_even_odd_ohm，铁律 7：不自造物理数字）→
  _coupled_section_s4 偶/奇模 2 端口叠加 4 端口（端口 1/2=线 A 近/远端、
  3/4=线 B 近/远端，与 _coupled_lines 渲染的 Port1/2/3 对齐）→ port4
  （线 B 远端）端接 50Ω（匹配负载 a4=0 ⇒ 3 端口 S = s4[:3,:3]）。
  独立裁判：|S31|@f0 vs 闭式电压耦合系数 C=(Z0e−Z0o)/(Z0e+Z0o)——
  Z0e·Z0o≈Z0² 时恒等（test_stepped_coupled_line_specs 钉 ≤0.5dB）。
  口径注：渲染几何线 B 远端为开路（旧模板三端口画法），fake 按 50Ω 端接
  的理想耦合器口径（设计裁判；与渲染开路端差异由 EM 冒烟实测其总量）。
  """
  from rfauto.adapters.openems_templates import (
    _coupled_section_s4,
    coupled_microstrip_even_odd_ohm,
  )

  if min(float(line_w_mm), float(gap_mm), float(coupled_len_mm)) <= 0.0:
    raise ValueError("coupled_line fake: 几何参数须 >0")
  f = np.asarray(freq_ghz, dtype=float)
  ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
    float(line_w_mm), float(gap_mm), float(f0_ghz), float(er),
    float(h_mm))
  s = np.zeros((len(f), 3, 3), dtype=complex)
  for i, fi in enumerate(f):
    the = 2.0 * math.pi * float(fi) * math.sqrt(ere_e) \
      * float(coupled_len_mm) / _ANT2_C_MM_GHZ
    tho = 2.0 * math.pi * float(fi) * math.sqrt(ere_o) \
      * float(coupled_len_mm) / _ANT2_C_MM_GHZ
    s[i] = _coupled_section_s4(ze, the, zo, tho, float(z_ref))[:3, :3]
  return s


# 天线族 II 一阶谐振模型常数（首次注册口径，未经真机标定不进锚判据；
# 与 _dipole_sparams 的 r_rad=73/q=6 同一约定层级）：
# - 接地 λ/4 族（monopole/pifa/ifa/helix）R_rad=36.5Ω（Balanis：单极子 =
#  半偶极子，73/2）；loop（断口馈自由谐振环）沿用 dipole 当量 73Ω；
# - q=6 同 dipole（决定谷宽，一阶）；
# - slot：串联"并联 RLC"辐射元 R_s=500Ω（@谐振 |S21|=2Z0/(2Z0+R_s)=−15.6dB，
#  量级取首跑实测 −16.4dB 的圆整，不做拟合）、Q_slot=10（一阶）。
_ANT2_C_MM_GHZ = 299.792458
_ANT2_TEMPLATES: tuple[str, ...] = (
  "monopole", "pifa", "ifa", "loop", "helix", "slot")
_ANT2_R_RAD_OHM: dict[str, float] = {
  "monopole": 36.5, "pifa": 36.5, "ifa": 36.5, "helix": 36.5, "loop": 73.0,
}
_ANT2_Q = 6.0
_ANT2_SLOT_R_S_OHM = 500.0
_ANT2_SLOT_Q = 10.0


def _hj_eps_eff(w_mm: float, freq_ghz: float, er: float, h_mm: float) -> float:
  """微带 εeff（skrf HJ 正向，core/synthesis 唯一介质口径，铁律 1c）。"""
  from rfauto.core.synthesis import Stackup, forward_z0

  stackup = Stackup(name="antenna2_fake", epsilon_r=float(er),
           thickness_mm=float(h_mm))
  _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
  return float(ere)


def antenna2_resonance_ghz(
  template: str,
  params: dict[str, Any],
  eps_eval_ghz: float = 2.4,
  er: float = 3.66,
  h_mm: float = 0.508,
) -> float:
  """天线族 II 谐振频率 = openems_templates 闭式设计函数的精确逆（GHz）。

  设计式（openems_templates C1 段）↔ 本逆式逐模板一一对应：
  monopole L=λ0/4 ⇒ f=c/(4L)；pifa L=λ0/(4√εeff(W))（L 路径式定版：居中短路板不绕行，W/Ws 不进谐振式）⇒ f=c/(4L√εeff)；
  ifa 臂=λ0/(4√εeff(w))；loop 4a=λ0（自由空间口径：无板无地
  εeff→1）⇒ f=c/(4a)；helix 4dN+Np=k_helix·λ0/4（K_HELIX 单源）；slot L=λ0/(2√((1+εr)/2))。εeff
  在 eps_eval_ghz 处取值（hairpin fake 同口径：设计中心频率处 HJ，弱色散）。
  设计式不做端效应预补偿（#190：引擎常数须经仲裁才进设计公式）。
  """
  c = _ANT2_C_MM_GHZ
  if template == "monopole":
    ln = float(params["mon_len_mm"])
    if ln <= 0.0:
      raise ValueError("mon_len_mm 须正")
    return c / (4.0 * ln)
  if template == "pifa":
    ln = float(params["pifa_l_mm"])
    w = float(params["pifa_w_mm"])
    ws = float(params["pifa_ws_mm"])
    if not (ln > 0.0 and w > 0.0 and 0.0 < ws <= w):
      raise ValueError("pifa 几何非法：L>0、W>0 且 0<Ws≤W")
    return c / (4.0 * ln * math.sqrt(_hj_eps_eff(w, eps_eval_ghz, er, h_mm)))
  if template == "ifa":
    ln = float(params["ifa_arm_mm"])
    w = float(params["ifa_w_mm"])
    if not (ln > 0.0 and w > 0.0):
      raise ValueError("ifa 几何须正")
    return c / (4.0 * ln * math.sqrt(_hj_eps_eff(w, eps_eval_ghz, er, h_mm)))
  if template == "loop":
    a = float(params["loop_side_mm"])
    w = float(params["loop_w_mm"])
    if not (a > 0.0 and w > 0.0):
      raise ValueError("loop 几何须正")
    return c / (4.0 * a)
  if template == "helix":
    # k_helix 定版（HFSS 同几何仲裁 AGREE，openems_templates.K_HELIX
    # 单源）：设计式 4dN+Np = k·λ0/4 ⇒ 精确逆 f = k·c/(4·wire)（名义回代=f0）。
    from rfauto.adapters.openems_templates import K_HELIX

    d = float(params["helix_d_mm"])
    n = int(params["helix_turns"])
    p = float(params["helix_pitch_mm"])
    wire = 4.0 * d * n + n * p
    if not (d > 0.0 and n >= 1 and p > 0.0):
      raise ValueError("helix 几何须正且 N ≥ 1")
    return K_HELIX * c / (4.0 * wire)
  if template == "slot":
    ln = float(params["slot_l_mm"])
    if ln <= 0.0:
      raise ValueError("slot_l_mm 须正")
    return c / (2.0 * ln * math.sqrt(0.5 * (1.0 + float(er))))
  raise ValueError(f"未知 antenna2 模板: {template}")


def _antenna2_sparams(
  freq_ghz: np.ndarray,
  template: str,
  params: dict[str, Any],
  z0: float = 50.0,
  er: float = 3.66,
  h_mm: float = 0.508,
  eps_eval_ghz: float = 2.4,
) -> np.ndarray:
  """天线族 II 解析（C1）：闭式谐振逆 + 一阶谐振电路（数据工厂语义）。

  单端口族（monopole/pifa/ifa/loop/helix）：串联谐振 Zin=R+jRQ(f/f0−f0/f)
  （_dipole_sparams 同形），f0 由 antenna2_resonance_ghz 精确逆给出——谐振
  尺寸参数是唯一进判据的自由度，R/Q 为一阶常数（_ANT2_R_RAD_OHM/_ANT2_Q）。
  slot（2 端口）：微带线中串入"并联 RLC"辐射元 Z_s=R_s/(1+jQ(f/f0−f0/f))
  ⇒ S11=Z_s/(Z_s+2Z0)、S21=2Z0/(Z_s+2Z0)（互易；1−|S11|²−|S21|² = R_s 吸收
  = 辐射功率，S21 在缝谐振处出辐射凹——真机锚签名；真机 S11 全带
  −0.5~−2.8dB 的有限地/底 MUR 口径寄生不复现）。
  真机冒烟对照见 openems_templates
  ANTENNA2_META 段注：monopole/ifa/slot PASS；pifa 旧通式标称 FAIL → L 路径
  式定版（override 17.08 PASS，设计式/标称同步）；loop 贴地镜像
  FAIL → 自由空间改造；helix 口径 FAIL——本 fake 是设计口径
  裁判，不为其"凑绿"。
  """
  f = np.asarray(freq_ghz, dtype=float)
  f_res = antenna2_resonance_ghz(template, params, eps_eval_ghz, er, h_mm)
  if template == "slot":
    zs = _ANT2_SLOT_R_S_OHM / (1.0 + 1j * _ANT2_SLOT_Q * (f / f_res - f_res / f))
    den = zs + 2.0 * z0
    s = np.zeros((len(f), 2, 2), dtype=complex)
    s[:, 0, 0] = s[:, 1, 1] = zs / den
    s[:, 0, 1] = s[:, 1, 0] = 2.0 * z0 / den
    return s
  r_rad = _ANT2_R_RAD_OHM[template]
  x = r_rad * _ANT2_Q * (f / f_res - f_res / f)
  s = np.zeros((len(f), 1, 1), dtype=complex)
  s[:, 0, 0] = (r_rad + 1j * x - z0) / (r_rad + 1j * x + z0)
  return s


# C2 阵列族一阶谐振模型（首次注册口径；R/Q 未经真机标定不进锚
# 判据，与 _antenna2_sparams / _dipole_sparams 同一约定层级）：
# - 谐振 f0 = openems_templates.array_elem_len_mm 设计式的精确逆（Balanis Ch.14
#  传输线模型 f0 = c/(2(L+2ΔL)√εeff(W))，与 core/symbolic_fit.patch_resonance_hj_ghz
#  独立裁判同式）；三模板单元同型 → 一阶谐振同频（互联/变换树不改一阶谐振）。
# - R：单缝辐射电导小缝近似 G1 ≈ (W/λ0)²/90 → 边馈 Rin(0) = 1/(2·G1)（G12 互导
#  忽略，Balanis Ch.14）；1×4/2×2 插入馈 Rin(y0) = Rin(0)·cos²(π·y0/L)
#  （y0 = elem_feed_mm），串馈边接 Rin(0)。5.8GHz 标称：Rin(0)=419.4Ω、
#  Rin(0.3L)=144.9Ω ⇒ |S11|@f0 ≈ −6.2dB（插入）/ −2.1dB（边馈）——一阶未匹配
#  口径，如实不凑深；谷位（设计精确逆）才是进判据的量。
# - Q = 10（薄基板贴片一阶常数，决定谷宽）。S 参数不含方向图物理（方向图裁判
#  在 core/array_synthesis 闭式：patch_element_field × array_factor）。
_ARRAY_TEMPLATES: tuple[str, ...] = (
  "patch_array_1x4", "patch_array_2x2", "patch_array_series")
_ARRAY_Q = 10.0
_ARRAY_C_MM_GHZ = 299.792458


def array_resonance_ghz(
  template: str,
  params: dict[str, Any],
  er: float = 3.66,
  h_mm: float = 0.508,
) -> float:
  """C2 阵列单元谐振频率 = array_elem_len_mm 设计式的精确逆（GHz）。

  L = c/(2f√εeff) − 2ΔL ⇔ f = c/(2(L+2ΔL)√εeff)，εeff/ΔL 为 Hammerstad 准静态式
  （只依赖 W/h/εr，无频率项，故逆式闭合精确）。
  """
  if template not in _ARRAY_TEMPLATES:
    raise ValueError(f"未知 C2 阵列模板: {template}")
  length = float(params["elem_len_mm"])
  width = float(params["elem_w_mm"])
  if not (length > 0.0 and width > 0.0 and float(h_mm) > 0.0 and float(er) > 1.0):
    raise ValueError("C2 阵列几何须正且 εr > 1")
  ee = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / width) ** -0.5
  dl = (0.824 * h_mm * (ee + 0.3) / (ee - 0.258)
     * (width / h_mm + 0.264) / (width / h_mm + 0.8))
  return _ARRAY_C_MM_GHZ / (2.0 * (length + 2.0 * dl) * math.sqrt(ee))


def array_edge_rin_ohm(w_mm: float, f0_ghz: float) -> float:
  """贴片边馈输入电阻一阶闭式 Rin(0) = 1/(2·G1)，G1 ≈ (W/λ0)²/90（Balanis Ch.14）。"""
  w = float(w_mm)
  if not (w > 0.0 and float(f0_ghz) > 0.0):
    raise ValueError("W/f0 须正")
  lam0 = _ARRAY_C_MM_GHZ / float(f0_ghz)
  g1 = (w / lam0) ** 2 / 90.0
  return 1.0 / (2.0 * g1)


def array_feed_rin_ohm(template: str, params: dict[str, Any], f0_ghz: float) -> float:
  """馈点输入电阻：插入馈 Rin(0)·cos²(π·y0/L)（1×4/2×2），串馈边接 Rin(0)。"""
  r_edge = array_edge_rin_ohm(float(params["elem_w_mm"]), f0_ghz)
  if template == "patch_array_series":
    return r_edge
  length = float(params["elem_len_mm"])
  y0 = float(params["elem_feed_mm"])
  if not (0.0 <= y0 < length / 2):
    raise ValueError(f"插入深度 {y0} 须落在 [0, L/2={length / 2})")
  return r_edge * math.cos(math.pi * y0 / length) ** 2


def _array_sparams(
  freq_ghz: np.ndarray,
  template: str,
  params: dict[str, Any],
  z0: float = 50.0,
  er: float = 3.66,
  h_mm: float = 0.508,
) -> np.ndarray:
  """C2 阵列族解析（C2）：单元设计式精确逆 + 一阶串联谐振（数据工厂语义）。

  单端口：Zin = R·(1 + jQ(f/f0 − f0/f))，f0 = array_resonance_ghz、R =
  array_feed_rin_ohm（一阶常数不进锚）。谐振尺寸 elem_len_mm 与单元宽 elem_w_mm
  是进判据的自由度（尺度律：L×k ⇒ 谷位÷k 一阶）；elem_feed_mm 只改谷深。
  本 fake 是设计口径裁判，不为真机"凑绿"；S 参数不含方向图物理。
  """
  f = np.asarray(freq_ghz, dtype=float)
  f_res = array_resonance_ghz(template, params, er, h_mm)
  r = array_feed_rin_ohm(template, params, f_res)
  x = r * _ARRAY_Q * (f / f_res - f_res / f)
  s = np.zeros((len(f), 1, 1), dtype=complex)
  s[:, 0, 0] = (r + 1j * x - z0) / (r + 1j * x + z0)
  return s


# ─── FakeAdapter 实现 ─────────────────────────────────────────────────────────

class FakeAdapter(SimulatorAdapter):
  """解析近似仿真适配器。

  无需 HFSS 许可证，基于闭式公式返回合成 S 参数。
  支持故障注入以测试错误处理路径。

  Parameters
  ----------
  model_type : str
    "wilkinson" | "branchline"，决定使用的解析模型。
  n_ports : int
    端口数。wilkinson 模型：2（向后兼容）或 3（完整隔离度）。
    默认 2，P2 调优循环应显式设 3。
  fault : FaultInjection | None
    故障注入配置。
  freq_ghz : tuple[float, float, int]
    频率范围 (start, stop, num_points)。
  z0 : float
    参考阻抗，默认 50 Ω。
  f0_ghz : float
    中心频率（GHz），默认 2.4。
  """

  def __init__(
    self,
    model_type: str = "wilkinson",
    fault: FaultInjection | None = None,
    freq_ghz: tuple[float, float, int] = (1.0, 4.0, 201),
    z0: float = 50.0,
    n_ports: int = 2,
    f0_ghz: float = 2.4,
    seed: int = 42,
  ) -> None:
    self.model_type = model_type
    self.fault = fault or FaultInjection()
    self.freq_ghz = freq_ghz
    self.z0 = z0
    self.n_ports = n_ports
    self.f0_ghz = f0_ghz
    # 阻抗计算用层叠（v0 物理映射）；配方变量里的 substrate 字符串优先
    self._substrate_name = "rogers4350b_h0.508"
    # 种子化随机：同配置可复现（C4；原先用全局 np.random 不可复现）
    self._rng = np.random.default_rng(seed)
    self._connected = False
    self._variables: dict[str, str] = {}
    self._network: skrf.Network | None = None

  # ─── SimulatorAdapter 接口实现 ───────────────────────────────────────────

  def connect(self, settings: dict[str, Any]) -> None:
    """幂等连接——FakeAdapter 无需真实连接。"""
    if self.fault.fail_connect:
      from rfauto.core.errors import ConnectFailedError
      raise ConnectFailedError(
        "FakeAdapter 故障注入：connect() 失败",
        details={"fault": "fail_connect"},
      )
    self._connected = True

  def open_or_create_project(self, path: str | Path, design_name: str) -> None:
    """FakeAdapter 无项目概念，静默通过。"""
    if not self._connected:
      raise RuntimeError("未连接，请先调用 connect()")

  def set_variables(self, vars: dict[str, str]) -> None:
    """记录设计变量（FakeAdapter 用于后续解析计算）。"""
    if not self._connected:
      raise RuntimeError("未连接，请先调用 connect()")
    self._variables.update(vars)

  def build_and_setup(
    self,
    builder: Callable[[SimulatorAdapter], None],
    setup: Any,
  ) -> None:
    """执行构建器 + 故障注入。"""
    if not self._connected:
      raise RuntimeError("未连接，请先调用 connect()")

    if self.fault.fail_build:
      raise ModelBuildError(
        "FakeAdapter 故障注入：build_and_setup() 建模失败",
        details={"fault": "fail_build", "variables": self._variables},
      )

    # 调用 builder 回调（通常用于记录构建步骤）
    builder(self)

  def _parse_variable(self, name: str, default: float) -> float:
    """从变量中解析数值（带单位剥离）。"""
    for var_name in [name, name.replace("_mm", "")]:
      if var_name in self._variables:
        try:
          val_str = self._variables[var_name].strip()
          if val_str.endswith("mm"):
            val_str = val_str[:-2]
          elif val_str.endswith("m"):
            val_str = val_str[:-1]
          return float(val_str)
        except (ValueError, AttributeError):
          continue
    return default

  def _parse_list_variable(self, name: str, default: list[float]) -> list[float]:
    """解析列表型变量（coupled_bpf 的 widths_mm/gaps_mm）：list/tuple 直接取，
    字符串按逗号切分（容忍方括号与 mm 后缀）；缺失/不可解析回退 default。"""
    raw = self._variables.get(name)
    if raw is None:
      return list(default)
    if isinstance(raw, (list, tuple)):
      try:
        return [float(v) for v in raw]
      except (TypeError, ValueError):
        return list(default)
    text = str(raw).strip().strip("[]()")
    out: list[float] = []
    for item in text.split(","):
      token = item.strip()
      if token.endswith("mm"):
        token = token[:-2]
      if not token:
        continue
      try:
        out.append(float(token))
      except ValueError:
        return list(default)
    return out if out else list(default)

  def _compute_f0_from_variables(self, eps_eff: float | None = None) -> float:
    """从变量中动态计算谐振频率（GHz，λ/4 反推）。

    按物理角色 resonator_length_mm 取谐振段长度（arm_len_mm /
    patch_len_mm 等候选，见 core/physics_roles.py）；无长度变量时
    使用 init 指定的 f0_ghz。

    eps_eff：联合校准锚（A1）——来自 configs/fake_calibration.yaml；
    未提供时由调用方以 synthesis.forward_z0 按线宽物理计算后传入，
    缺省 3.28（branchline 真机 HFSS 校准值）。
    """
    _C = 3.0e8 # 光速 m/s
    # branchline 真机校准：arm_len≈17.2mm@2.4GHz → εeff≈3.28。
    _EPS_EFF = eps_eff if eps_eff is not None else 3.28

    from rfauto.core.physics_roles import resolve_role

    arm_len_mm = resolve_role(
      "resonator_length_mm", self._variables,
      candidates=("arm_len_mm", "arm_len"),
    )
    if arm_len_mm is not None:
      arm_len_m = arm_len_mm * 1e-3
      f0_hz = _C / (4 * arm_len_m * math.sqrt(_EPS_EFF))
      return f0_hz / 1e9
    return self.f0_ghz

  def _wilkinson_s11_min(
    self, series_w_mm: float, shunt_w_mm: float, f0_ghz: float,
    stackup_name: str | None = None,
  ) -> tuple[float, float]:
    """由线宽物理计算 Wilkinson 的带内最小反射（线幅值）与 εeff。

    一阶失配模型：两段 λ/4 线（目标阻抗 Zt=Z0·√2 与 Z0）的实现阻抗
    由 synthesis.forward_z0（skrf MLine HJ）给出，反射系数按最坏
    叠加合成，再叠加结寄生底噪 0.12（T 型结/阶梯不连续性/端口效应，
    一阶公式未建模——真机校准锚：HFSS 名义点 -12.93dB / 最优
    -15.8dB 与本模型 -13.0/-15.8 对齐，v0）。
    这是 fake 对调参变量（series_w/shunt_w）的排序响应来源
    （v0 修复：旧版公式里线宽根本没进公式）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml(
      stackup_name or self._substrate_name)
    zt = self.z0 * math.sqrt(2)
    z_series, eps_eff = forward_z0(series_w_mm, f0_ghz, stackup)
    z_shunt, _ = forward_z0(shunt_w_mm, f0_ghz, stackup)
    gamma_s = abs((z_series - zt) / (z_series + zt))
    gamma_sh = abs((z_shunt - self.z0) / (z_shunt + self.z0))
    s11_min = math.hypot(gamma_s + gamma_sh, 0.12)
    return min(s11_min, 0.68), eps_eff

  def solve(self, setup_name: str, timeout_s: int = 3600) -> SolveReport:
    """解析求解——基于闭式公式返回合成 S 参数。"""
    import time

    if not self._connected:
      raise RuntimeError("未连接，请先调用 connect()")

    if self.fault.fail_solve:
      raise SimulationFailedError(
        "FakeAdapter 故障注入：solve() 求解失败",
        details={"fault": "fail_solve", "setup": setup_name},
      )

    # 模拟延迟
    if self.fault.slow_solve_s > 0:
      time.sleep(self.fault.slow_solve_s)

    # 生成频率轴
    f_start, f_stop, f_pts = self.freq_ghz
    freq = skrf.Frequency(f_start, f_stop, f_pts, unit="GHz")

    # 根据模型类型计算 S 参数
    # 联合校准锚（A1）：configs/fake_calibration.yaml per-model 覆盖；
    # v0 起 wilkinson 的 s11 深度由线宽失配物理计算，常数锚只留
    # eps_eff / edge_scale。
    cal = load_fake_calibration().get(self.model_type, {})
    if isinstance(self._variables.get("substrate"), str):
      self._substrate_name = self._variables["substrate"]

    if self.model_type == "wilkinson":
      from rfauto.core.physics_roles import resolve_role

      series_w = resolve_role(
        "impedance_line_width_mm", self._variables, default=0.33)
      shunt_w = resolve_role(
        "shunt_line_width_mm", self._variables, default=1.10)
      s11_min_lin, eps_eff_series = self._wilkinson_s11_min(
        series_w, shunt_w, self.f0_ghz, self._substrate_name)
      f0_ghz = self._compute_f0_from_variables(
        eps_eff=cal.get("eps_eff", eps_eff_series))
      if self.n_ports == 3:
        s_data = _wilkinson_sparams_3port(
          freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz, rng=self._rng,
          s11_min_lin=s11_min_lin,
        )
      else:
        s_data = _wilkinson_sparams_2port(
          freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz, rng=self._rng,
          s11_min_lin=s11_min_lin,
        )
    elif self.model_type == "branchline":
      # f0 同样由 arm_len 变量驱动（λ/4 关系），参数变化有真实响应
      # 真机校准：S11 深度依赖于 series_w/shunt_w
      f0_ghz = self._compute_f0_from_variables(eps_eff=cal.get("eps_eff"))
      series_w = self._parse_variable("series_w_mm", default=1.87)
      shunt_w = self._parse_variable("shunt_w_mm", default=1.11)
      s_data = _branchline_sparams(
        freq.f / 1e9, z0=self.z0, f0_ghz=f0_ghz,
        series_w_mm=series_w, shunt_w_mm=shunt_w,
      )
    elif self.model_type == "patch":
      # 贴片天线：patch_len → λ/2 谐振频率；feed_offset/patch_w →
      # 馈电匹配深度（谐振腔一阶模型，v0 修复：旧版 feed_offset
      # 签名里有、公式里没用）。
      from rfauto.core.physics_roles import resolve_role

      patch_len = resolve_role(
        "resonator_length_mm", self._variables,
        candidates=("patch_len_mm", "patch_len"), default=40.0)
      feed_offset = resolve_role(
        "feed_offset_mm", self._variables, default=10.0)
      patch_w = resolve_role(
        "patch_width_mm", self._variables, default=30.0)
      lambda0_mm = 300.0 / self.f0_ghz
      # 一阶谐振腔模型：R_edge ≈ 60λ0/W，R_in = R_edge·cos²(π·x0/L)
      # （x0 自辐射边起算；忽略 G12 与有限 h 修正）
      r_edge = 60.0 * lambda0_mm / patch_w
      r_in = r_edge * math.cos(math.pi * feed_offset / patch_len) ** 2
      gamma_in = abs((r_in - self.z0) / (r_in + self.z0))
      s_data = _patch_sparams_2port(
        freq.f / 1e9, z0=self.z0, f0_ghz=self.f0_ghz,
        patch_len_mm=patch_len,
        feed_offset_mm=feed_offset,
        patch_w_mm=patch_w,
        eps_eff=cal.get("eps_eff", 2.33),
        s11_min_lin=gamma_in,
      )
    elif self.model_type == "mline":
      # 均匀微带线（WP2.1 锚）：w → εeff（skrf HJ 闭式）→ 相速/损耗。
      # 数据工厂/仲裁探针口径：变量驱动真实响应（w 变→εeff 变→相位斜率变）。
      from rfauto.adapters.openems_templates import template_meta
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup, forward_z0

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=1.113)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      _, eps_eff = forward_z0(w, self.f0_ghz, stackup)
      s_data = _mline_sparams(
        freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
        tan_d=float(template_meta("mline")["substrate"].get("tan_d", 0.0037)),
      )
    elif self.model_type == "cpw":
      # 均匀共面波导（WP2.1 锚族）：w/gap → εeff（CPWG 共形映射
      # 闭式，#198 参照系修正：openEMS 官方口径 z-min=PEC 强制地，
      # 实际结构是 CPWG，无地 skrf CPW 口径作废）→ 相速/损耗
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=0.849)
      gap = resolve_role("gap_width_mm", self._variables,
                candidates=("gap_mm",), default=0.2)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      from rfauto.core.calculators import _cpwg_ri
      eps_eff = _cpwg_ri(w, gap, stackup.thickness_mm,
                stackup.epsilon_r)[0]
      s_data = _cpw_sparams(
        freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
        tan_d=stackup.loss_tangent)
    elif self.model_type == "dipole":
      # 半波振子（WP1.3 官方口径重写后）：L → λ/2 自由空间谐振
      # 闭式 → 单端口谐振谷（数据工厂语义：谷位随 L 精确移动）
      from rfauto.core.physics_roles import resolve_role

      dip_len = resolve_role(
        "resonator_length_mm", self._variables,
        candidates=("dipole_len_mm",), default=58.0)
      s_data = _dipole_sparams(
        freq.f / 1e9, dipole_len_mm=dip_len, z0=self.z0)
    elif self.model_type == "stripline":
      # 均匀带状线（WP2.1 锚族）：TEM 模 εeff=εr（精确，无色散
      # 一阶项）→ 相速/损耗闭式同 mline
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      s_data = _mline_sparams(
        freq.f / 1e9, eps_eff=stackup.epsilon_r,
        line_len_mm=line_len, tan_d=stackup.loss_tangent)
    elif self.model_type == "cps":
      # 共面带 CPS（C9 传输线族 II）：w/gap → εeff（无地有限厚基板共形
      # 映射闭式 _cps_ri，refs §11；#154 同名参数逐参对语义：w_mm=单带宽、
      # gap_mm=两带间缝，与 openEMS _cps_lines 同口径）→ 相速/损耗闭式
      # 同 mline（匹配端接 LumpedPort R=Z0 → S11≈0 口径）
      from rfauto.core.calculators import _cps_ri
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=2.95)
      gap = resolve_role("gap_width_mm", self._variables,
                candidates=("gap_mm",), default=0.5)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      eps_eff = _cps_ri(w, gap, stackup.thickness_mm,
               stackup.epsilon_r)[0]
      s_data = _cps_sparams(
        freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
        tan_d=stackup.loss_tangent)
    elif self.model_type == "suspended_stripline":
      # 悬置带线（C9 传输线族 II）：w/b（基板厚=stackup h 居中对称填充）
      # → εeff（共形电容比闭式 _suspended_stripline_ri，两支精确极限锚
      # 回到 stripline）→ 相速/损耗闭式同 mline
      from rfauto.core.calculators import _suspended_stripline_ri
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=0.9058)
      b_cav = self._parse_variable("b_mm", default=1.016)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      eps_eff = _suspended_stripline_ri(
        w, b_cav, stackup.thickness_mm, stackup.epsilon_r)[0]
      s_data = _suspended_stripline_sparams(
        freq.f / 1e9, eps_eff=eps_eff, line_len_mm=line_len,
        tan_d=stackup.loss_tangent)
    elif self.model_type == "msl_cpw":
      # MSL↔CPWG 过渡（WP2.5 Tier 2，正式注册）：wstep 式两段
      # 等长理想 TL 级联——微带段 skrf HJ MLine（w_msl）、CPWG 段共形映射
      # 闭式 _cpwg_ri（w_cpw/gap）；#154 同名参数逐参对语义：w_msl_mm/
      # w_cpw_mm/gap_cpw_mm/line_len_mm 与 openEMS _msl_cpw_lines 同口径
      # （理想=突变对接，渐变区 trans_len 不进理想级联）
      from rfauto.core.calculators import _cpwg_ri
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      # resolve_role 显式候选名：数值/带单位字符串都可解析（_parse_variable
      # 对裸数值 .strip() 抛 AttributeError 静默回退默认值——尺度律测试传数值）
      w_msl = resolve_role("line_width_mm", self._variables,
                 candidates=("w_msl_mm",), default=1.1134)
      w_cpw = resolve_role("step_width_mm", self._variables,
                 candidates=("w_cpw_mm",), default=0.849)
      gap = resolve_role("gap_width_mm", self._variables,
                candidates=("gap_cpw_mm",), default=0.2)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      m1 = skrf.media.MLine(frequency=f_mid, w=w_msl * 1e-3,
                 h=stackup.thickness_mm * 1e-3,
                 ep_r=stackup.epsilon_r)
      eps2, z2 = _cpwg_ri(w_cpw, gap, stackup.thickness_mm,
                stackup.epsilon_r)
      s_data = _msl_cpw_sparams(
        freq.f / 1e9,
        eps_eff1=float(np.real(m1.ep_reff[0])), eps_eff2=float(eps2),
        z1=float(abs(m1.z0[0])), z2=float(z2),
        seg_len_mm=line_len / 2.0,
        tan_d=stackup.loss_tangent, z_ref=self.z0)
    elif self.model_type == "sma_launcher":
      # SMA 边缘弹射（WP2.5 Tier 2，正式注册）：同轴段（PTFE
      # 填充 TEM εeff=er_fill 精确、Z0=(60/√εr)·ln(r_o/r_i) 闭式）+ 微带段
      # （skrf HJ MLine @w_msl）理想级联；coax_len=shell_len、msl_len=
      # line_len（openEMS _sma_launcher_lines 同口径，#154）。理想弹射
      # 寄生为零，引擎-理想偏差即弹射寄生（文献曲线门在真机侧）
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      def _var(name: str, default: float) -> float:
        return float(resolve_role(name, self._variables,
                     candidates=(name,), default=default))

      w_msl = _var("w_msl_mm", 1.1134)
      r_i = _var("r_i_mm", 0.635)
      r_o = _var("r_o_mm", 2.1244)
      er_fill = _var("er_fill", 2.1)
      shell_len = _var("shell_len_mm", 5.0)
      line_len = _var("line_len_mm", 40.0)
      tan_d_fill = _var("tan_d_fill", 0.0)  # PTFE tanδ（变体，nominal 无耗）
      if not (r_i > 0.0 and r_o > r_i and er_fill > 1.0):
        raise ValueError(
          f"sma_launcher fake: 同轴几何/填充非法 r_i={r_i} r_o={r_o} "
          f"er_fill={er_fill}（须 0<r_i<r_o、εr>1）")
      z_coax = 60.0 / math.sqrt(er_fill) * math.log(r_o / r_i)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      m2 = skrf.media.MLine(frequency=f_mid, w=w_msl * 1e-3,
                 h=stackup.thickness_mm * 1e-3,
                 ep_r=stackup.epsilon_r)
      s_data = _sma_launcher_sparams(
        freq.f / 1e9, eps_eff_coax=float(er_fill),
        eps_eff_msl=float(np.real(m2.ep_reff[0])),
        z_coax=float(z_coax), z_msl=float(abs(m2.z0[0])),
        coax_len_mm=shell_len, msl_len_mm=line_len,
        tan_d=stackup.loss_tangent, z_ref=self.z0,
        tan_d_coax=tan_d_fill)
    elif self.model_type == "wstep":
      # 微带宽度阶跃（WP2.2 基元）：两段 HJ 闭式 TL 的 ABCD 级联
      # （理想阶跃=仅阻抗跳变；w→εeff/Z0 各自独立进判据）
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w1 = resolve_role("line_width_mm", self._variables,
               candidates=("w1_mm",), default=1.1134)
      w2 = resolve_role("step_width_mm", self._variables,
               candidates=("w2_mm",), default=1.897)
      line_len = resolve_role("line_length_mm", self._variables,
                  candidates=("line_len_mm",), default=40.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      m1 = skrf.media.MLine(frequency=f_mid, w=w1 * 1e-3,
                 h=stackup.thickness_mm * 1e-3,
                 ep_r=stackup.epsilon_r)
      m2 = skrf.media.MLine(frequency=f_mid, w=w2 * 1e-3,
                 h=stackup.thickness_mm * 1e-3,
                 ep_r=stackup.epsilon_r)
      s_data = _wstep_sparams(
        freq.f / 1e9,
        eps_eff1=float(np.real(m1.ep_reff[0])),
        eps_eff2=float(np.real(m2.ep_reff[0])),
        z1=float(abs(m1.z0[0])), z2=float(abs(m2.z0[0])),
        seg_len_mm=line_len / 2.0,
        tan_d=stackup.loss_tangent, z_ref=self.z0)
    elif self.model_type == "tjunc":
      # 微带 T 接头（WP2.2 基元）：理想结点+三条 HJ 线裁判，
      # 三端口 (n,3,3)。全臂同宽 50Ω，εeff 走 HJ 闭式。
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_feed_mm",), default=1.1134)
      tl = resolve_role("line_length_mm", self._variables,
               candidates=("through_len_mm",), default=25.0)
      bl = resolve_role("branch_length_mm", self._variables,
               candidates=("branch_len_mm",), default=20.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                   h=stackup.thickness_mm * 1e-3,
                   ep_r=stackup.epsilon_r)
      eps_eff = float(np.real(media.ep_reff[0]))
      s_data = _tjunc_sparams(
        freq.f / 1e9, z_arm=self.z0, eps_eff=eps_eff,
        through_len_mm=tl, branch_len_mm=bl,
        tan_d=stackup.loss_tangent, z_ref=self.z0)
    elif self.model_type == "bend":
      # 微带直角弯折（WP2.2 基元）：理想级联（同宽两段），
      # εeff 走 HJ 闭式；弯角寄生是引擎唯一反射源
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=1.1134)
      a = resolve_role("line_length_mm", self._variables,
               candidates=("arm_len_mm",), default=20.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                   h=stackup.thickness_mm * 1e-3,
                   ep_r=stackup.epsilon_r)
      eps_eff = float(np.real(media.ep_reff[0]))
      s_data = _bend_sparams(
        freq.f / 1e9, eps_eff=eps_eff, arm_len_mm=a,
        z_arm=self.z0, tan_d=stackup.loss_tangent, z_ref=self.z0)
    elif self.model_type == "via":
      # 过孔过渡（WP2.2 收官）：理想过孔=两馈线直接级联，
      # εeff 走 HJ 闭式；过孔+反焊盘寄生是引擎唯一偏差源
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",), default=1.1134)
      feed = resolve_role("line_length_mm", self._variables,
                default=60.0)
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      f_mid = skrf.Frequency(self.f0_ghz, self.f0_ghz, 1, unit="GHz")
      media = skrf.media.MLine(frequency=f_mid, w=w * 1e-3,
                   h=stackup.thickness_mm * 1e-3,
                   ep_r=stackup.epsilon_r)
      eps_eff = float(np.real(media.ep_reff[0]))
      s_data = _via_sparams(
        freq.f / 1e9, eps_eff=eps_eff, feed_len_mm=feed,
        z_feed=self.z0, tan_d=stackup.loss_tangent, z_ref=self.z0)
    elif self.model_type == "atten_pi":
      # π 型衰减器（WP2.3 首族）：理想电阻网络 ABCD 闭式
      # （电阻值由 E4 attenuator_pi 同源公式给出，平坦无频响）
      from rfauto.core.physics_roles import resolve_role

      atten = resolve_role("attenuation_db", self._variables,
                 candidates=("atten_db",), default=10.0)
      s_data = _atten_pi_sparams(freq.f / 1e9, atten_db=atten,
                    z_ref=self.z0)
    elif self.model_type == "atten_t":
      # T 型衰减器（WP2.3 横向变体）：理想电阻网络 ABCD 闭式
      from rfauto.core.physics_roles import resolve_role

      atten = resolve_role("attenuation_db", self._variables,
                 candidates=("atten_db",), default=10.0)
      s_data = _atten_t_sparams(freq.f / 1e9, atten_db=atten,
                   z_ref=self.z0)
    elif self.model_type == "ratrace":
      # rat-race 环形电桥（WP2.3）：理想 180° 混合环裁判
      # （窄带理想化——匹配/均分/隔离在 f0 处准确）
      s_data = _ratrace_sparams(freq.f / 1e9, z_ref=self.z0)
    elif self.model_type == "gysel":
      # Gysel 功分器（WP2.3 横向变体）：理想六节环 f0 闭式裁判
      # （#206 理论核验轮：均分 -3dB 同相/全匹配/输出互隔离；
      # 参数敏感度由引擎对照提供，fake 为确定性理想裁判）
      s_data = _gysel_sparams(freq.f / 1e9, z_ref=self.z0)
    elif self.model_type in ("hairpin", "hairpin_alt"):
      # 发夹线带通滤波器（WP2.3 滤波器族；电气通道已接通）：
      # arm_len→f0（λg/2 反演，εeff 走 HJ；同 hairpin_arm_len_mm 闭式的精确逆）
      # + gap_mm/gaps_mm→k（KJ 闭式 hairpin_k_from_gap_mm；#154 与渲染同语义：
      # 相邻谐振器外臂缝，逐缝列表优先）+ tap_frac→Q_e（抽头闭式
      # hairpin_qe_from_tap_frac × 真机修正 c(τ) _HAIRPIN_QE_CORR）
      # → hairpin_coupling_matrix → 耦合矩阵理想频响。设计链几何下与 C13
      # 理想响应逐位一致（单测 ≤1e-9）；gap↑→带宽单调窄、τ→0.5→Q_e↑（单测）。
      # hairpin_alt（交替取向根修变体）：同一电气通道，唯一差异
      # = gap→k **不乘**同向结构修正 c(gap)（该表是同向 U 相消效应的真机标定，
      # 对交替取向不适用；c_alt≈1 为预声明假设，待真机 k(gap) 图谱判读）。
      from rfauto.adapters.openems_templates import (
        HAIRPIN_ALT_NOMINAL,
        HAIRPIN_NOMINAL,
      )
      from rfauto.core.coupled_microstrip import (
        hairpin_k_from_gap_mm,
        hairpin_qe_from_tap_frac,
      )
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup, forward_z0

      is_alt = self.model_type == "hairpin_alt"
      nominal = HAIRPIN_ALT_NOMINAL if is_alt else HAIRPIN_NOMINAL
      w = resolve_role("line_width_mm", self._variables,
               candidates=("w_mm",),
               default=float(nominal["w_mm"]))
      arm_len = resolve_role("resonator_length_mm", self._variables,
                  candidates=("arm_len_mm",))
      raw_order = self._variables.get("order",
                      nominal["order"])
      try:
        order = int(float(raw_order))
      except (TypeError, ValueError):
        order = int(nominal["order"])
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      # εeff/KJ 一律用无耗准静态 Stackup（与 hairpin_arm_len_mm/coupled_microstrip
      # 同口径）：materials.yaml 的 tanδ 会让 skrf ep_reff 偏 −0.19%（f0 偏 +0.1%），
      # 设计几何便无法逐位复现 C13 理想响应（A4 实测 max|ΔS|=0.079）
      stackup = Stackup(name=stackup.name, epsilon_r=stackup.epsilon_r,
               thickness_mm=stackup.thickness_mm)
      f0_ghz = self.f0_ghz
      if arm_len is not None and arm_len > 0.0:
        _, eps_eff = forward_z0(w, self.f0_ghz, stackup)
        # λg/2 反演（hairpin_arm_len_mm 的精确逆）：c/(2·L·√εeff)，再乘真机
        # 谐振修正 c_f0（B2 pt4：U 弯+开路端等效缩短使 EM 谐振高于闭式 +3.7%）
        # 单位 Hz → GHz（同 _compute_f0_from_variables 的 /1e9 口径）
        f0_ghz = _HAIRPIN_F0_CORR * (299792458.0 / (2.0 * arm_len * 1e-3
                              * math.sqrt(eps_eff))) / 1e9
      # gap→k：gaps_mm 列表（长度 order−1）优先，否则标量 gap_mm 等缝；
      # KJ 在设计 f0 处求值（与 hairpin_design_from_order 同口径，往返精确）。
      # W4④：乘 hairpin 结构经验修正 c(gap)=k_EM/k_KJ（并排同向 U
      # 相邻臂开路端对齐 → 电/磁耦合反号相消，N=2 弱抽头真机标定表
      # core.coupled_microstrip.HAIRPIN_KGAP_TABLE_MM，c≈0.12-0.26、k_EM 上限 ~0.0155；
      # 闭式本身经 NGSolve 独立核实无误）；域外 clamp 取端点 c（fake 前向裁判的
      # 显式假设，非外推口径——设计反解 hairpin_gap_mm_from_k 仍 raise）。
      gaps = self._parse_list_variable("gaps_mm", [])
      if len(gaps) != order - 1:
        gap = resolve_role("gap_width_mm", self._variables,
                  candidates=("gap_mm",),
                  default=float(nominal["gap_mm"]))
        gaps = [float(gap)] * (order - 1)
      k_list = [hairpin_k_from_gap_mm(g_mm, w, self.f0_ghz,
                      stackup.epsilon_r,
                      stackup.thickness_mm,
                      structural_correction=not is_alt,
                      extrapolate="clamp")
           for g_mm in gaps]
      raw_tau = self._variables.get("tap_frac",
                     nominal["tap_frac"])
      try:
        tau = float(raw_tau)
      except (TypeError, ValueError):
        tau = float(nominal["tap_frac"])
      c0, c1 = _HAIRPIN_QE_CORR
      qe = hairpin_qe_from_tap_frac(tau) * (c0 + c1 * tau)
      s_data = _hairpin_sparams(freq.f / 1e9, f0_ghz=f0_ghz,
                   order=order, z_ref=self.z0,
                   k_list=k_list, qe=qe)
    elif self.model_type == "coupled_bpf":
      # 平行耦合 BPF（WP2.3 BPF 族锚，注册）：几何列表
      # widths_mm/gaps_mm（与 openEMS 渲染同索引同语义，#154）→ KJ
      # 偶/奇模电气量 → 电路级联裁判同源闭式 _coupled_bpf_sparams。
      # 列表变量可为 list/tuple 或 "a,b,c" / "[a, b, c]" 字符串。
      from rfauto.adapters.openems_templates import COUPLED_BPF_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      widths = self._parse_list_variable(
        "widths_mm", list(COUPLED_BPF_NOMINAL["widths_mm"]))
      gaps = self._parse_list_variable(
        "gaps_mm", list(COUPLED_BPF_NOMINAL["gaps_mm"]))
      res_len = resolve_role(
        "resonator_length_mm", self._variables,
        candidates=("res_len_mm",),
        default=float(COUPLED_BPF_NOMINAL["res_len_mm"]))
      feed_len = resolve_role(
        "line_length_mm", self._variables,
        candidates=("feed_len_mm",),
        default=float(COUPLED_BPF_NOMINAL["feed_len_mm"]))
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      s_data = _coupled_bpf_sparams(
        freq.f / 1e9, widths_mm=widths, gaps_mm=gaps,
        res_len_mm=res_len, feed_len_mm=feed_len,
        f0_ghz=self.f0_ghz, er=stackup.epsilon_r,
        h_mm=stackup.thickness_mm, z_ref=self.z0)
    elif self.model_type in _C3_TEMPLATES:
      # C3 滤波器族 II（交指/梳状/SIR，注册）：几何参数
      # （缝列表与渲染同索引同语义，#154）→ KJ 倒置器 → 并联谐振 J 链
      # 裁判同源闭式 _c3_sparams。列表变量可为 list/tuple 或字符串。
      from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      nominal = TEMPLATE_NOMINAL[self.model_type]
      c3_params: dict[str, Any] = {}
      for key, default in nominal.items():
        if isinstance(default, list):
          c3_params[key] = self._parse_list_variable(key, list(default))
        elif key == "order":
          raw_order = self._variables.get("order", default)
          try:
            c3_params[key] = int(float(raw_order))
          except (TypeError, ValueError):
            c3_params[key] = int(default)
        else:
          c3_params[key] = float(resolve_role(
            key, self._variables, candidates=(key,),
            default=float(default)))
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      # 过孔电感开关（登记⑨）：缺省 0.0=理想短路（旧名义逐位不变，旧黄金钉
      # 保持）；变量 "l_via_h" 显式开启——"auto"=按几何取
      # c3_via_inductance_h(h_mm)（真机裁判口径），数值=指定电感（H）。
      # 补偿后的再生名义几何配 l_via_h="auto" 裁判时谐振回 f0。
      lv_raw = self._variables.get("l_via_h")
      l_via: float | None = 0.0
      if lv_raw is not None:
        l_via = (None if isinstance(lv_raw, str)
             and lv_raw.strip().lower() == "auto" else float(lv_raw))
      s_data = _c3_sparams(
        freq.f / 1e9, self.model_type, c3_params,
        f0_ghz=self.f0_ghz, er=stackup.epsilon_r,
        h_mm=stackup.thickness_mm, z_ref=self.z0, l_via_h=l_via)
    elif self.model_type in ("cline_coupler", "lange", "branchline_2sect"):
      # §C4 耦合器族 II（注册）：几何 → HJ/KJ 电气量 → 偶/奇模
      # 裁判同源闭式（cline 真非同步相速；lange 四线等效理想；两节分支线
      # 二分频响）。变量名与 openEMS 渲染同名同语义（#154）；
      # w_feed_mm 只进几何。
      from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      nominal = TEMPLATE_NOMINAL[self.model_type]
      c4: dict[str, float] = {
        key: float(resolve_role(key, self._variables, candidates=(key,),
                    default=float(default)))
        for key, default in nominal.items()}
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      common = {"f0_ghz": self.f0_ghz, "er": stackup.epsilon_r,
           "h_mm": stackup.thickness_mm, "z_ref": self.z0}
      if self.model_type == "cline_coupler":
        s_data = _cline_coupler_sparams(
          freq.f / 1e9, w_mm=c4["w_mm"], gap_mm=c4["gap_mm"],
          coupled_len_mm=c4["coupled_len_mm"], **common)
      elif self.model_type == "lange":
        s_data = _lange_sparams(
          freq.f / 1e9, w_mm=c4["w_mm"], gap_mm=c4["gap_mm"],
          finger_len_mm=c4["finger_len_mm"], **common)
      else:
        s_data = _branchline_2sect_sparams(
          freq.f / 1e9, w_main_mm=c4["w_main_mm"],
          w_out_mm=c4["w_out_mm"], w_mid_mm=c4["w_mid_mm"],
          sect_len_mm=c4["sect_len_mm"],
          branch_len_mm=c4["branch_len_mm"], **common)
    elif self.model_type in ("stepped_impedance", "coupled_line"):
      # 初始模板补注册：阶梯阻抗线（HJ (Z,εeff) → cosim
      # ABCD 级联）/ 耦合线（KJ 偶/奇模 → 4 端口 port4 端接 50Ω 化 3 端口）。
      # 变量名与渲染同名同语义（#154）；n_segments 整数解析同 helix_turns。
      from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      nominal = TEMPLATE_NOMINAL[self.model_type]
      geom: dict[str, Any] = {}
      for key, default in nominal.items():
        value = resolve_role(key, self._variables, candidates=(key,),
                   default=float(default))
        geom[key] = (round(float(value)) if key == "n_segments"
               else float(value))
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      common = {"f0_ghz": self.f0_ghz, "er": stackup.epsilon_r,
           "h_mm": stackup.thickness_mm, "z_ref": self.z0}
      if self.model_type == "stepped_impedance":
        s_data = _stepped_impedance_sparams(
          freq.f / 1e9, z1_width_mm=geom["z1_width_mm"],
          z2_width_mm=geom["z2_width_mm"], seg_len_mm=geom["seg_len_mm"],
          n_segments=geom["n_segments"], **common)
      else:
        s_data = _coupled_line_sparams(
          freq.f / 1e9, coupled_len_mm=geom["coupled_len_mm"],
          line_w_mm=geom["line_w_mm"], gap_mm=geom["gap_mm"], **common)
    elif self.model_type in _ANT2_TEMPLATES:
      # 天线族 II（C1，注册）：几何参数 → 闭式设计函数
      # 精确逆 f0 → 一阶谐振电路（设计口径裁判；R/Q 常数未标定不进锚）
      from rfauto.adapters.openems_templates import ANTENNA2_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      nominal = ANTENNA2_NOMINAL[self.model_type]
      params: dict[str, Any] = {}
      for key, default in nominal.items():
        value = resolve_role(key, self._variables, candidates=(key,),
                   default=float(default))
        params[key] = (round(float(value)) if key == "helix_turns"
                else float(value))
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      s_data = _antenna2_sparams(
        freq.f / 1e9, self.model_type, params, z0=self.z0,
        er=stackup.epsilon_r, h_mm=stackup.thickness_mm,
        eps_eval_ghz=self.f0_ghz)
    elif self.model_type in _ARRAY_TEMPLATES:
      # C2 阵列族（注册）：几何参数 → 单元设计式精确逆 f0
      # → 一阶串联谐振（设计口径裁判；R/Q 一阶常数未标定不进锚）
      from rfauto.adapters.openems_templates import ARRAY_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      nominal = ARRAY_NOMINAL[self.model_type]
      arr_params: dict[str, Any] = {
        key: float(resolve_role(key, self._variables, candidates=(key,),
                    default=float(default)))
        for key, default in nominal.items()}
      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      s_data = _array_sparams(
        freq.f / 1e9, self.model_type, arr_params, z0=self.z0,
        er=stackup.epsilon_r, h_mm=stackup.thickness_mm)
    elif self.model_type in ("slotline", "slotline_lumped",
                 "msl_slot_transition", "marchand_balun"):
      # 槽线族：几何 → 槽线闭式 γ（core/slotline，
      # 域外显式报错不外推）→ 各路线 fake 裁判（路线 A 匹配线/路线 B 并联
      # 抽头 #250/过渡 Knorr 一阶等效/巴伦两节对称耦合段电路级）。变量名与
      # 渲染同名同语义（#154）；h_mm=模板参数（设计点 1.524，理由见
      # SLOTLINE_NOMINAL 注）——禁用 stackup.thickness_mm（0.508 落闭式域外）。
      from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
      from rfauto.core.physics_roles import resolve_role
      from rfauto.core.synthesis import Stackup

      stackup = Stackup.from_materials_yaml(
        self._substrate_name or "rogers4350b_h0.508")
      nominal = TEMPLATE_NOMINAL[self.model_type]
      fam: dict[str, float] = {
        key: float(resolve_role(key, self._variables, candidates=(key,),
                    default=float(default)))
        for key, default in nominal.items()
        if isinstance(default, (int, float))}
      fam["er"] = stackup.epsilon_r
      fam["tan_d"] = stackup.loss_tangent
      fam["f0_ghz"] = self.f0_ghz
      common = {"er": fam["er"], "tan_d": fam["tan_d"],
           "f0_ghz": fam["f0_ghz"]}
      if self.model_type == "slotline":
        s_data = _slotline_route_a_sparams(
          freq.f / 1e9, w_mm=fam["w_mm"],
          line_len_mm=fam["line_len_mm"], h_mm=fam["h_mm"], **common)
      elif self.model_type == "slotline_lumped":
        s_data = _slotline_route_b_sparams(
          freq.f / 1e9, w_mm=fam["w_mm"],
          line_len_mm=fam["line_len_mm"], h_mm=fam["h_mm"],
          r_port_ohm=self._variables.get("r_port_ohm"), **common)
      elif self.model_type == "msl_slot_transition":
        s_data = _msl_slot_transition_sparams(
          freq.f / 1e9, w_slot_mm=fam["w_slot_mm"],
          x_port_mm=fam["x_port_mm"], h_mm=fam["h_mm"], **common)
      else:
        s_data = _marchand_balun_sparams(
          freq.f / 1e9, w_slot_mm=fam["w_slot_mm"], h_mm=fam["h_mm"],
          **common)
    else:
      raise ValueError(f"未知模型类型: {self.model_type}")

    # 故障注入：非被动 S 参数
    if self.fault.passivity_violation:
      # 强制使某些频点的 |S| > 1
      s_data[0, 0, 0] = 1.5 + 0j # S11 > 1 → passivity violation

    # 创建 skrf.Network
    self._network = skrf.Network(
      frequency=freq,
      s=s_data,
      z0=self.z0,
    )

    return SolveReport(
      success=True,
      passes=1,
      delta_s_final=0.001,
      wall_time_s=0.01,
      message=f"FakeAdapter 解析求解完成 ({self.model_type})",
    )

  def get_sparams(self) -> skrf.Network:
    """返回合成的 S 参数网络。"""
    if self._network is None:
      raise RuntimeError("尚未求解，请先调用 solve()")
    return self._network

  def export_touchstone(
    self,
    path: str | Path,
    contract: Any = None,
  ) -> Path:
    """导出 Touchstone 文件。"""
    if self._network is None:
      raise RuntimeError("尚未求解，请先调用 solve()")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 契约校验（如果提供）—— 兼容 AdsExchangeContract 与 TouchstoneContract
    if contract is not None:
      from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
      tc = contract.touchstone if isinstance(contract, AdsExchangeContract) else contract
      if isinstance(tc, TouchstoneContract) and self._network.nports != len(tc.port_order):
        from rfauto.core.errors import ContractViolationError
        raise ContractViolationError(
          f"端口数不匹配：契约 {len(tc.port_order)}，"
          f"网络 {self._network.nports}",
        )

    self._network.write_touchstone(str(path))
    return path

  def get_far_field(self, setup_name: str, freq_ghz: float = 2.4) -> dict[str, Any] | None:
    "FakeAdapter 远场数据（解析近似）。返回理想贴片天线方向图近似。"
    import numpy as np
    theta = np.linspace(0, 180, 37).tolist()
    phi = np.linspace(0, 360, 73).tolist()
    gain_db = [float(10 * np.log10(max(np.cos(np.radians(t)), 0.01))) for t in theta]
    return {"theta": theta, "phi": phi, "gain_db": gain_db, "pattern_type": "cosine_approx", "freq_ghz": freq_ghz}

  def close(self, save: bool = True) -> None:
    """关闭会话。"""
    self._connected = False
    self._network = None

  def capabilities(self) -> AdapterCapabilities:
    """FakeAdapter 能力声明。"""
    return AdapterCapabilities(
      supports_wave_port=False,
      supports_lumped_port=True,
      supports_field_export=False,
      supports_convergence_report=True,
      supports_touchstone_export=True,
      supports_headless_solve=True,
      supports_optimetrics=False,
    )

  def health_check(self) -> bool:
    """健康检查——FakeAdapter 始终健康。"""
    return self._connected

  def ensure_connected(self) -> None:
    """自愈重连（缺口 4 R5）——FakeAdapter 无真实会话，直接复连。"""
    self._connected = True

# ─── 槽线族 fake 解析模型（注册；数值只在 core 闭式内核，铁律 7）───
# #154 同名同语义：变量名与 openEMS 渲染/TEMPLATE_NOMINAL 逐键一致；
# h_mm 从模板参数取（缺省 1.524 设计点）——缺省叠层 0.508@2.5GHz 落 Janaswamy–
# Schaubert 闭式域外，越域 ValueError 如实上抛。


def _slotline_gamma(w_mm: float, h_mm: float, er: float, freq_ghz: Any,
          tan_d: float = 0.0037) -> Any:
  """槽线复传播常数 γ=α+jβ（闭式 β 逐频；α=介质损耗一阶近似，mline fake 同式）。"""
  from rfauto.core.slotline import slotline_closed_form

  f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
  gamma = np.empty(len(f_arr), dtype=complex)
  for i, f_ghz in enumerate(f_arr):
    r = slotline_closed_form(float(w_mm), float(h_mm), float(er), float(f_ghz))
    f_hz = float(f_ghz) * 1e9
    alpha_np = np.pi * f_hz * math.sqrt(r.eps_eff) * float(tan_d) / 299792458.0
    gamma[i] = alpha_np + 1j * r.beta_rad_m
  return gamma


def _slotline_route_a_sparams(freq_ghz: Any, w_mm: float = 1.0,
               line_len_mm: float = 93.4624, h_mm: float = 1.524,
               er: float = 3.66, tan_d: float = 0.0037,
               **_: Any) -> Any:
  """路线 A fake：PML 匹配均匀槽线段（交叉参考阻抗口径）——S11≈数值底（匹配线）、
  S21=e^{−γL}（探针 β 锚：谷判据量=相位/β 随 w 精确移动）。"""
  gamma = _slotline_gamma(w_mm, h_mm, er, freq_ghz, tan_d)
  length_m = float(line_len_mm) * 1e-3
  s21 = np.exp(-gamma * length_m)
  n = len(gamma)
  s = np.zeros((n, 2, 2), dtype=complex)
  s[:, 0, 0] = s[:, 1, 1] = 1e-4
  s[:, 0, 1] = s[:, 1, 0] = s21
  return s


def _slotline_route_b_sparams(freq_ghz: Any, w_mm: float = 1.0,
               line_len_mm: float = 93.4624, h_mm: float = 1.524,
               er: float = 3.66, tan_d: float = 0.0037,
               r_port_ohm: float | None = None, **_: Any) -> Any:
  """路线 B fake：并联抽头拓扑解析（tap_network_sparams，#250）→ 50Ω 基装配。

  γ 端接（z0=闭式 Z0、r_port 缺省=同值）：原始 S11=−1/2/S21=+1/2 量级（βL=2π
  解析必然），装配后为"50Ω 对拍口径"的抽头顶基真波量——判读口径见模板 meta。
  """
  from rfauto.adapters.slotline_lumped_template import (
    assemble_route_b_sparams,
    tap_network_sparams,
  )
  from rfauto.core.slotline import slotline_closed_form

  f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
  r = slotline_closed_form(float(w_mm), float(h_mm), float(er), float(f_arr[0]))
  z0 = float(r.z0_ohm)
  r_port = float(r_port_ohm) if r_port_ohm is not None else z0
  gamma = _slotline_gamma(w_mm, h_mm, er, f_arr, tan_d)
  s11_raw, s21_raw = tap_network_sparams(z0, r_port, gamma,
                      float(line_len_mm) * 1e-3)
  return assemble_route_b_sparams(s11_raw, s21_raw, r_port)


def _msl_slot_transition_sparams(freq_ghz: Any, w_slot_mm: float = 1.0,
                 x_port_mm: float = 40.0, h_mm: float = 1.524,
                 er: float = 3.66, tan_d: float = 0.0037,
                 f0_ghz: float = 2.5, **_: Any) -> Any:
  """Roberts/Knorr 过渡 fake：Knorr 1974 一阶等效电路（串联开路支节 + 理想
  变压器 n²=Z_m/Z_s（f0 匹配比）+ 槽侧短路臂并联 + 输出臂 TL），2 端口混合
  参考（Z1=50、Z2=槽线 Z0）→ skrf renormalize 到 50Ω 管道口径。

  f0 处：支节虚短路（cot θm=0）、短路臂虚开路（tan θs=∞）→ Z_in=n²·Z_s=Z_m
  匹配 ✓；带外呈带通形（两 λ/4 结构失谐）。**一阶口径如实**：无结区寄生/非同步
  相速/损耗（真机基线见模板 meta smoke_note）。
  """
  from skrf.network import renormalize_s

  from rfauto.core.slotline_transitions import transition_design

  d = transition_design(float(f0_ghz), float(h_mm), float(er),
             float(w_slot_mm), float(tan_d))
  z_m, z_s = 50.0, float(d.z_slot_ohm)
  n2 = z_m / z_s            # f0 匹配变压器阻抗比
  f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
  c0 = 299792458.0
  out = np.empty((len(f_arr), 2, 2), dtype=complex)
  for i, f_ghz in enumerate(f_arr):
    f_hz = float(f_ghz) * 1e9
    k0 = 2.0 * np.pi * f_hz / c0
    bm = k0 * math.sqrt(d.eps_eff_msl)
    bs = k0 * math.sqrt(d.eps_eff_slot)
    z_stub = -1j * z_m / math.tan(bm * d.l_stub_mm * 1e-3)
    th_s = bs * d.l_short_mm * 1e-3
    z_arm = 1j * z_s * math.tan(th_s)
    th_l = bs * float(x_port_mm) * 1e-3
    # ABCD（端口1 微带侧 → 端口2 槽侧）：串联支节·变压器(n²)·并联短路臂·输出臂
    a00 = math.cos(th_l)
    a01 = 1j * z_s * math.sin(th_l)
    a10 = 1j * math.sin(th_l) / z_s
    a11 = math.cos(th_l)
    # shunt Z_arm（左乘 [[1,0],[1/Z,1]]）→ transformer（左乘 [[n,0],[0,1/n]]，
    # n=√(Z_m/Z_s) 电压比）→ series z_stub（左乘 [[1,Z],[0,1]]）
    b00, b01 = a00, a01
    b10, b11 = a00 / z_arm + a10, a01 / z_arm + a11
    nn = math.sqrt(n2)
    c00, c01 = nn * b00, nn * b01
    c10, c11 = b10 / nn, b11 / nn
    d00, d01 = c00 + z_stub * c10, c01 + z_stub * c11
    d10, d11 = c10, c11
    den = d00 * z_s + d01 + d10 * z_m * z_s + d11 * z_m
    s11 = (d00 * z_s + d01 - d10 * z_m * z_s - d11 * z_m) / den
    s21 = 2.0 * math.sqrt(z_m * z_s) / den
    s12 = 2.0 * math.sqrt(z_m * z_s) * (d00 * d11 - d01 * d10) / den
    s22 = (-d00 * z_s + d01 - d10 * z_m * z_s + d11 * z_m) / den
    out[i] = [[s11, s12], [s21, s22]]
  return renormalize_s(out, [z_m, z_s], [50.0, 50.0])


def _marchand_balun_sparams(freq_ghz: Any, w_slot_mm: float = 1.0,
              h_mm: float = 1.524, er: float = 3.66,
              tan_d: float = 0.0037, f0_ghz: float = 2.5,
              **_: Any) -> Any:
  """Marchand fake：两节对称耦合段电路级裁判（3 端口，P1 50Ω/P2P3 50Ω 单端）。

  **口径如实**：模板双槽臂几何已被两引擎互证证伪，本
  fake 与模板几何不同源——数值来自 core/slotline_transitions 两节对称耦合段
  电路级内核（synthesize_marchand_two_section + marchand_two_section_sparams，
  确定性/可复现），差分负载取 2×槽线 Z0（双槽臂输出口径）。
  """
  from rfauto.core.slotline import slotline_closed_form
  from rfauto.core.slotline_transitions import (
    marchand_two_section_sparams,
    synthesize_marchand_two_section,
  )

  z_slot = float(slotline_closed_form(float(w_slot_mm), float(h_mm),
                    float(er), float(f0_ghz)).z0_ohm)
  design = synthesize_marchand_two_section(float(f0_ghz), 50.0, 2.0 * z_slot,
                       er=float(er), h_mm=float(h_mm),
                       tan_d=float(tan_d), s_min_mm=0.02)
  return marchand_two_section_sparams(freq_ghz, float(f0_ghz),
                    design.z0e_realized_ohm,
                    design.z0o_realized_ohm, 50.0,
                    design.z_bal_se_ohm)
