"""A3 场-路协同（非线性/谐波平衡）回归锚（A3）。

方案行口径（原文）
------------------
"A3 Xyce 电路协同 | 场-路协同（EM S 参数→电路仿真，谐波平衡/非线性） |
对照 ngspice 参考解"。

链路与裁判
----------
1. **EM 数据段**：2 端口 Touchstone（真机用法 = openEMS/HFSS
  export_touchstone 的匹配/滤波网络产物；离线回归 =
  :func:`lsection_smatrix` 的闭式 L 截面替身——串（L+ESR）/并 C，
  与 field_circuit_anchor 的闭式 branchline 同范式）。
2. **电路段（谐波平衡）**：S →Y（core.circuit_hb.s_to_y，逐谐波插值）
  → EM N 端口 + 50Ω 源 + Shockley 二极管 + RC 负载的检波器
  （最经典非线性场-路首案例）→ core.circuit_hb 谐波-Newton 求解。
3. **参考段（ngspice 真机）**：同一物理 RLC 电路渲染 ngspice 瞬态网表
  （.tran gear + .meas AVG + .four，adapters.spice_netlist），批处理
  运行 ngspice-47（本机实测可用），解析谐波幅相/直流。
4. **裁判**：HB（频域）vs ngspice（时域）逐量互差（DC/基波/高次谐波
  相对误差）+ HB K 阶梯加密自检（投影截断收敛性）。

诚实边界
--------
- **ngspice 参考侧以"同一物理 RLC"渲染**：频域 Y 网络无法直接进时域
 瞬态；替身两侧物理一致（Y(S) 与物理网表的等价性由单测以两条独立
 导出路径钉死）。任意真机 EM S 数据的参考链须先经 D13 有理宏模型
 综合（followUp）。
- **Xyce 通道**：本机无 Xyce 二进制（GitHub Release 仅源码/说明），仅
 留 adapters.spice_netlist 可用性探测钩子；渲染器须对照 Xyce Reference
 Guide 后补（#215 纪律）。谐波平衡/非线性能力由本仓确定性内核承载，
 不依赖外部 HB 引擎。
- 离线单测不跑 ngspice（与 WP4.3 同纪律）；真机对照由
 tests/real_edt/test_field_circuit_nonlinear_real.py + runs/ 证据承载。

分层：linkage，可 import adapters/core/同层 linkage；不 import service 以上。
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.adapters import spice_netlist
from rfauto.core.circuit_hb import (
  HBCapacitor,
  HBCircuit,
  HBDiode,
  HBEmNPort,
  HBInductor,
  HBResistor,
  HBVSource,
  s_to_y,
  solve_harmonic_balance,
)

logger = logging.getLogger(__name__)

#: 检波器电路节点编号（HB 电路：EM 端口替代 L 截面）。
NODE_SRC = 1
NODE_P1 = 2 # EM 端口 1（源侧）
NODE_P2 = 3 # EM 端口 2（二极管侧）
NODE_OUT = 4
#: 参考电路（物理 RLC）节点编号：多一个 ES R 中间节点。
RNODE_PX = 3
RNODE_P2 = 4
RNODE_OUT = 5
#: 参考电路网表节点名（下标=节点号，0=地）。
REFERENCE_NODE_NAMES = ["0", "src", "p1", "px", "p2", "out"]
#: HB 电路网表节点名（渲染参考时不用；.four 目标名对齐参考电路）。
HB_NODE_NAMES = ["0", "src", "p1", "p2", "out"]


@dataclass(frozen=True)
class DetectorSpec:
  """二极管检波器 + EM L 截面替身参数（SI 单位；离线锚缺省值）。

  L 截面 = 串（L + ESR）/并 C（ESR 使 DC 导纳有限且两侧物理一致）；
  二极管 = Shockley 纯指数结（ngspice `.model D(Is,N)` 最小口径）。
  """
  f0_hz: float = 1.0e9
  amp_v: float = 1.0
  source_phase_deg: float = -90.0
  rs_ohm: float = 50.0
  l_h: float = 7.9e-9
  esr_ohm: float = 0.5
  c_f: float = 1.6e-12
  rl_ohm: float = 10.0e3
  cl_f: float = 50.0e-12
  diode_is_a: float = 1.0e-14
  diode_n: float = 1.0
  z0_ohm: float = 50.0


# --------------------------------------------------------------------------- #
# EM 替身：闭式 L 截面 S 参数
# --------------------------------------------------------------------------- #

def lsection_smatrix(
  freq_hz: np.ndarray, spec: DetectorSpec,
) -> np.ndarray:
  """串（ESR+L）/并 C 二端口 S 参数（闭式 ABCD，确定性）。

  ABCD = [1, Z; 0, 1]·[1, 0; Yc, 1] = [1+Z·Yc, Z; Yc, 1]，
  S11=(A+B/z0−C·z0−D)/den，S21=S12=2/den（互易 det=1），
  S22=(−A+B/z0−C·z0+D)/den，den=A+B/z0+C·z0+D。
  """
  f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
  w = 2.0 * np.pi * f
  z0 = float(spec.z0_ohm)
  s = np.zeros((f.size, 2, 2), dtype=complex)
  for k in range(f.size):
    z_ser = complex(spec.esr_ohm) + 1j * w[k] * spec.l_h
    y_sh = 1j * w[k] * spec.c_f
    a, b, c, d = 1.0 + z_ser * y_sh, z_ser, y_sh, 1.0 + 0j
    den = a + b / z0 + c * z0 + d
    s[k, 0, 0] = (a + b / z0 - c * z0 - d) / den
    s[k, 1, 0] = 2.0 / den
    s[k, 0, 1] = 2.0 / den
    s[k, 1, 1] = (-a + b / z0 - c * z0 + d) / den
  return s


def standin_dc_y(spec: DetectorSpec) -> np.ndarray:
  """替身 DC 导纳（闭式）：L 短路（余 ESR）、C 开路 → 纯 ESR 导纳矩阵。"""
  g = 1.0 / float(spec.esr_ohm)
  return np.array([[g, -g], [-g, g]])


def build_em_standin_touchstone(
  path: str | Path,
  spec: DetectorSpec | None = None,
  *,
  max_harmonic: int = 9,
  n_points: int = 1401,
  band_margin: float = 1.2,
) -> Path:
  """闭式替身 → .s2p（真机链与离线回归共用的 EM 数据形态）。

  频带自动覆盖 ``band_margin·max_harmonic·f0``（谐波插值全程带内，
  max_harmonic 含 K 加密自检档）。真机用法：把 openEMS/HFSS 的 .s2p
  放同一路径位即可，下游零改动。
  """
  import skrf

  spec = spec or DetectorSpec()
  f_max = band_margin * max_harmonic * spec.f0_hz
  f_min = 0.2 * spec.f0_hz
  freq = np.linspace(f_min, f_max, int(n_points))
  s = lsection_smatrix(freq, spec)
  network = skrf.Network(
    frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=float(spec.z0_ohm),
    name="em_lsection_standin",
  )
  out = Path(path)
  out.parent.mkdir(parents=True, exist_ok=True)
  network.write_touchstone(str(out), form="ri")
  logger.info("EM L 截面替身已写出: %s (%d 点)", out, n_points)
  return out


def y_harmonics_from_touchstone(
  snp_path: str | Path,
  harmonics_hz: np.ndarray,
  *,
  z0_ohm: float = 50.0,
) -> np.ndarray:
  """Touchstone → 逐谐波 Y 矩阵 (len(harmonics), n, n)。

  插值口径：S 数据复数线性插值（与 ADS SnP InterpMode="linear" 同惯例）
  后逐频点 s_to_y；谐波出带即显式报错（不外推——诚实失败）。
  """
  import skrf

  net = skrf.Network(str(snp_path))
  f = np.asarray(net.f, dtype=float)
  s = np.asarray(net.s, dtype=complex)
  h = np.atleast_1d(np.asarray(harmonics_hz, dtype=float))
  if h.size and (h.min() < f[0] or h.max() > f[-1]):
    raise ValueError(
      f"谐波频率出带: [{h.min():.4g}, {h.max():.4g}] ⊄ Touchstone "
      f"[{f[0]:.4g}, {f[-1]:.4g}]（不外推）"
    )
  n = s.shape[1]
  s_h = np.zeros((h.size, n, n), dtype=complex)
  for i in range(n):
    for j in range(n):
      s_h[:, i, j] = np.interp(h, f, s[:, i, j].real) + 1j * np.interp(
        h, f, s[:, i, j].imag,
      )
  return s_to_y(s_h, z0_ohm)


# --------------------------------------------------------------------------- #
# 电路装配（HB 侧：EM 端口；参考侧：物理 RLC）
# --------------------------------------------------------------------------- #

def build_hb_circuit(
  y_at_harmonics: np.ndarray,
  y_dc: np.ndarray | None,
  spec: DetectorSpec,
  *,
  n_harmonics: int = 7,
  n_samples: int = 256,
) -> HBCircuit:
  """检波器 HB 电路：源+Rs+EM N 端口+二极管+RC（n_nodes=5）。

  ``y_at_harmonics``: shape (K, 2, 2)，行 k−1 = k·f0 导纳（不含 DC 行，
  与 core.circuit_hb.HBEmNPort 口径一致）；DC 由 ``y_dc`` 显式给出。
  """
  if y_at_harmonics.shape[0] < n_harmonics:
    raise ValueError("y_at_harmonics 需覆盖 k=1..K 共 K 行（不含 DC）")
  c = HBCircuit(n_nodes=5, f0_hz=spec.f0_hz, n_harmonics=n_harmonics, n_samples=n_samples)
  c.add(HBVSource(NODE_SRC, 0, 0.0, spec.amp_v, phase_deg=spec.source_phase_deg))
  c.add(HBResistor(NODE_SRC, NODE_P1, spec.rs_ohm))
  c.add(HBEmNPort((NODE_P1, NODE_P2), y_at_harmonics[:n_harmonics], y_dc=y_dc))
  c.add(HBDiode(NODE_P2, NODE_OUT, spec.diode_is_a, emission_n=spec.diode_n))
  c.add(HBResistor(NODE_OUT, 0, spec.rl_ohm))
  c.add(HBCapacitor(NODE_OUT, 0, spec.cl_f))
  return c


def build_physical_circuit(spec: DetectorSpec) -> tuple[HBCircuit, list[str]]:
  """物理 RLC 电路（ngspice 参考网表容器；亦可作 HB 侧等价性对拍）。"""
  c = HBCircuit(n_nodes=6, f0_hz=spec.f0_hz)
  c.add(HBVSource(NODE_SRC, 0, 0.0, spec.amp_v, phase_deg=spec.source_phase_deg))
  c.add(HBResistor(NODE_SRC, NODE_P1, spec.rs_ohm))
  c.add(HBInductor(NODE_P1, RNODE_PX, spec.l_h))
  c.add(HBResistor(RNODE_PX, RNODE_P2, spec.esr_ohm))
  c.add(HBCapacitor(RNODE_P2, 0, spec.c_f))
  c.add(HBDiode(RNODE_P2, RNODE_OUT, spec.diode_is_a, emission_n=spec.diode_n))
  c.add(HBResistor(RNODE_OUT, 0, spec.rl_ohm))
  c.add(HBCapacitor(RNODE_OUT, 0, spec.cl_f))
  return c, list(REFERENCE_NODE_NAMES)


# --------------------------------------------------------------------------- #
# ngspice 参考段
# --------------------------------------------------------------------------- #

def run_ngspice_reference(
  spec: DetectorSpec,
  out_dir: str | Path,
  *,
  n_harmonics: int = 7,
  exe: str | Path | None = None,
  n_periods_total: int = 2000,
  n_periods_meas: int = 500,
  samples_per_period_max: float = 400.0,
  method: str = "gear",
) -> dict[str, Any]:
  """渲染→运行→解析 ngspice 瞬态参考解。

  返回 {"netlist", "run", "parsed"}；parsed 形态见
  adapters.spice_netlist.parse_ngspice_output。
  """
  out_dir = Path(out_dir)
  out_dir.mkdir(parents=True, exist_ok=True)
  circuit, node_names = build_physical_circuit(spec)
  plan = spice_netlist.transient_plan_for(
    spec.f0_hz,
    n_periods_total=n_periods_total,
    n_periods_meas=n_periods_meas,
    samples_per_period_max=samples_per_period_max,
  )
  netlist = spice_netlist.render_ngspice_netlist(
    circuit,
    out_dir / "reference_transient.cir",
    node_names,
    tstop_s=plan["tstop_s"],
    tstart_s=plan["tstart_s"],
    tmax_s=plan["tmax_s"],
    meas_from_s=plan["meas_from_s"],
    method=method,
    four_nodes=["p1", "p2", "out"],
    meas_avg={"vdc_out": "out"},
    title="rfauto A3 field-circuit nonlinear anchor / ngspice reference",
  )
  run = spice_netlist.run_ngspice(netlist, exe=exe)
  parsed = spice_netlist.parse_ngspice_output(run["stdout"])
  return {"netlist": netlist, "run": run, "parsed": parsed}


# --------------------------------------------------------------------------- #
# HB vs ngspice 对拍
# --------------------------------------------------------------------------- #

#: 对拍量清单：(信号节点, 谐波次)。0 = 直流。
DEFAULT_COMPARE_QUANTITIES: tuple[tuple[str, int], ...] = (
  ("out", 0), ("out", 1), ("p2", 1), ("p2", 2), ("p2", 3),
)
#: 相对误差门限（按量：DC 0.5% / 谐波 2%；纹波量级小放宽到 8%）。
DEFAULT_TOLERANCES: dict[str, float] = {"dc": 0.005, "harmonic": 0.02, "ripple": 0.08}
#: 参考量绝对地板（低于它不判相对误差，记 None——小量不谎报）。
AMPLITUDE_FLOOR = 1e-7


def _hb_quantity(
  hb: dict[str, Any], node: str, harmonic: int,
) -> float:
  entry = hb[node]
  if harmonic == 0:
    return float(entry["dc"])
  return float(entry["amplitude"][str(harmonic)])


def _ref_quantity(ref: dict[str, Any], node: str, harmonic: int) -> float:
  sig = ref["fourier"].get(node)
  if sig is None:
    raise KeyError(f"ngspice .four 缺少信号 v({node})")
  if harmonic == 0:
    if sig.get("dc") is None:
      raise KeyError(f"ngspice .four v({node}) 缺 0 次行")
    return float(sig["dc"])
  h = sig["harmonics"].get(harmonic)
  if h is None:
    raise KeyError(f"ngspice .four v({node}) 缺 {harmonic} 次谐波")
  return float(h["magnitude"])


def _tolerance_for(node: str, harmonic: int) -> str:
  if harmonic == 0:
    return "dc"
  if node == "out":
    return "ripple"
  return "harmonic"


def compare_hb_vs_ngspice(
  hb: dict[str, Any],
  ref: dict[str, Any],
  *,
  quantities: tuple[tuple[str, int], ...] = DEFAULT_COMPARE_QUANTITIES,
  tolerances: dict[str, float] | None = None,
) -> dict[str, Any]:
  """逐量相对误差对拍与判定（所有被判定量 ≤ 门限才算通过）。

  ``hb``/``ref`` 为 :func:`harmonic_summary` 与 ngspice parsed 形态。
  """
  tolerances = tolerances or DEFAULT_TOLERANCES
  rows: list[dict[str, Any]] = []
  all_ok = True
  for node, harmonic in quantities:
    tol_kind = _tolerance_for(node, harmonic)
    tol = float(tolerances[tol_kind])
    try:
      hb_v = _hb_quantity(hb, node, harmonic)
      ref_v = _ref_quantity(ref, node, harmonic)
    except KeyError as exc:
      rows.append({
        "node": node, "harmonic": harmonic, "status": "missing",
        "error": str(exc),
      })
      all_ok = False
      continue
    scale = max(abs(ref_v), AMPLITUDE_FLOOR)
    rel = abs(hb_v - ref_v) / scale
    ok = bool(rel <= tol)
    all_ok = all_ok and ok
    rows.append({
      "node": node, "harmonic": harmonic, "hb": hb_v, "ngspice": ref_v,
      "rel_err": float(rel), "tolerance": tol, "tolerance_kind": tol_kind,
      "ok": ok, "status": "ok",
    })
  return {"quantities": rows, "all_ok": bool(all_ok), "amplitude_floor": AMPLITUDE_FLOOR}


def harmonic_summary(
  solution: Any,
  node_names: dict[int, str],
  *,
  max_harmonic: int = 3,
) -> dict[str, Any]:
  """HBSolution → {节点: {dc, amplitude: {k: 峰值}, phase_deg_cos: {k: 相位}}}。

  相位为余弦参考（core.circuit_hb 口径）；ngspice 侧换算见
  adapters.spice_netlist.ngspice_phase_to_cosine。
  """
  out: dict[str, Any] = {}
  for num, name in node_names.items():
    if num == 0:
      continue
    amps: dict[str, float] = {}
    phas: dict[str, float] = {}
    for k in range(1, max_harmonic + 1):
      ph = solution.node_phasor(num, k)
      amps[str(k)] = abs(ph)
      phas[str(k)] = float(math.degrees(math.atan2(ph.imag, ph.real)))
    out[name] = {
      "dc": solution.node_dc(num),
      "amplitude": amps,
      "phase_deg_cos": phas,
    }
  return out


# --------------------------------------------------------------------------- #
# 端到端编排
# --------------------------------------------------------------------------- #

def run_field_circuit_nonlinear_anchor(
  out_dir: str | Path,
  *,
  snp_path: str | Path | None = None,
  spec: DetectorSpec | None = None,
  n_harmonics: int = 7,
  n_samples: int = 256,
  k_refine_step: int = 2,
  exe: str | Path | None = None,
  ngspice_runner: Any = None,
  tolerances: dict[str, float] | None = None,
  k_conv_tol: float = 0.005,
  n_periods_total: int = 2000,
  n_periods_meas: int = 500,
) -> dict[str, Any]:
  """端到端 A3 锚：EM S 参数 → HB 非线性电路 → ngspice 参考对拍。

  Args:
    snp_path: EM Touchstone（None 时生成闭式替身到 ``out_dir``）。
    ngspice_runner: 注入替身（离线回归：``(spec, out_dir, exe=...) ->
      {"parsed": ...}``；与 run_ngspice_reference 同签名）——离线单测
      只验管线，不充当裁判；验收数字由真机运行承载。
    k_refine_step: K 加密自检步长（解一次 K+step，投影截断漂移
      须 ≤ ``k_conv_tol``）。

  Returns:
    JSON 原生 summary（含 ``ok``），并写 ``<out_dir>/anchor_report.json``。
    任一段失败如实降级记录，不掩盖（锚是裁判不是业务主路径）。
  """
  spec = spec or DetectorSpec()
  out_dir = Path(out_dir)
  out_dir.mkdir(parents=True, exist_ok=True)
  t0 = time.time()
  summary: dict[str, Any] = {
    "plan_ref": "field_circuit_nonlinear 模块方案说明",
    "spec": asdict(spec),
    "n_harmonics": int(n_harmonics),
    "n_samples": int(n_samples),
  }
  ok = True

  # --- EM 数据段 ---
  try:
    y_dc: np.ndarray | None
    k_refine = n_harmonics + k_refine_step
    if snp_path is None:
      snp_path = build_em_standin_touchstone(
        out_dir / "em_lsection_standin.s2p", spec, max_harmonic=k_refine,
      )
      y_dc = standin_dc_y(spec)
      summary["em"] = {"source": "closed_form_standin", "path": str(snp_path)}
    else:
      # 外部真机 Touchstone：无 DC 点，按"DC 开路"诚实降级（解里标注）
      y_dc = None
      summary["em"] = {"source": "touchstone", "path": str(snp_path)}
    harmonics = np.array([k * spec.f0_hz for k in range(1, k_refine + 1)])
    y_all = y_harmonics_from_touchstone(snp_path, harmonics, z0_ohm=spec.z0_ohm)
    summary["em"]["dc_mode"] = "closed_form_standin" if y_dc is not None else "open"
  except Exception as exc:
    summary["em"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    summary["ok"] = False
    _write_report(summary, out_dir)
    return summary

  # --- HB 求解段（K 与 K+step 双解，投影收敛自检） ---
  hb_results: dict[int, Any] = {}
  try:
    for k_use in sorted({n_harmonics, n_harmonics + k_refine_step}):
      circ = build_hb_circuit(y_all, y_dc, spec, n_harmonics=k_use, n_samples=n_samples)
      sol = solve_harmonic_balance(circ)
      hb_results[k_use] = {
        "summary": harmonic_summary(sol, {i: nm for i, nm in enumerate(HB_NODE_NAMES)}),
        "converged": sol.converged,
        "n_iterations": sol.n_iterations,
        "residual_inf": sol.residual_inf,
        "em_dc_open": sol.em_dc_open,
        "used_homotopy": sol.used_homotopy,
        "solution": sol,
      }
    base = hb_results[n_harmonics]
    refined = hb_results[n_harmonics + k_refine_step]
    k_drifts: dict[str, float] = {}
    for node, harmonic in DEFAULT_COMPARE_QUANTITIES:
      a = _hb_quantity(base["summary"], node, harmonic)
      b = _hb_quantity(refined["summary"], node, harmonic)
      k_drifts[f"{node}_h{harmonic}"] = float(abs(b - a) / max(abs(b), AMPLITUDE_FLOOR))
    k_conv_ok = max(k_drifts.values()) <= k_conv_tol
    summary["harmonic_balance"] = {
      "status": "ok",
      "converged": base["converged"],
      "n_iterations": base["n_iterations"],
      "residual_inf": base["residual_inf"],
      "used_homotopy": base["used_homotopy"],
      "k_refine": {
        "k_base": int(n_harmonics),
        "k_refined": int(n_harmonics + k_refine_step),
        "max_rel_drift": max(k_drifts.values()),
        "drifts": k_drifts,
        "tol": k_conv_tol,
        "ok": bool(k_conv_ok),
      },
      "quantities": base["summary"],
    }
    ok = ok and base["converged"] and k_conv_ok
  except Exception as exc:
    summary["harmonic_balance"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    summary["ok"] = False
    _write_report(summary, out_dir)
    return summary

  # --- ngspice 参考段 ---
  try:
    if ngspice_runner is not None:
      ref_run = ngspice_runner(spec, out_dir, exe=exe)
    else:
      ref_run = run_ngspice_reference(
        spec, out_dir, n_harmonics=n_harmonics, exe=exe,
        n_periods_total=n_periods_total, n_periods_meas=n_periods_meas,
      )
    ref_parsed = ref_run["parsed"]
    ref_errors = ref_run.get("run", {}).get("errors", [])
    summary["ngspice"] = {
      "status": "ok",
      "netlist": str(ref_run.get("netlist", "")),
      "errors": ref_errors,
      "fourier": ref_parsed["fourier"],
      "meas": ref_parsed["meas"],
    }
    if ref_errors:
      summary["ngspice"]["status"] = "error_flags"
      ok = False
  except Exception as exc:
    summary["ngspice"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    summary["ok"] = False
    _write_report(summary, out_dir)
    return summary

  # --- 对拍段 ---
  try:
    comparison = compare_hb_vs_ngspice(
      base["summary"], summary["ngspice"], tolerances=tolerances,
    )
    summary["comparison"] = comparison
    ok = ok and comparison["all_ok"]
    # 参考侧内部一致性：.four 0 次（其窗口均值）vs .meas AVG（稳态窗）
    # 互差大 = .four 窗口未落在稳态（参考解不可信），如实判红。
    four_dc = summary["ngspice"]["fourier"].get("out", {}).get("dc")
    meas_dc = summary["ngspice"]["meas"].get("vdc_out")
    if four_dc is not None and meas_dc is not None and abs(meas_dc) > AMPLITUDE_FLOOR:
      dc_cross = abs(float(four_dc) - float(meas_dc)) / abs(float(meas_dc))
      dc_cross_ok = dc_cross <= 1e-3
      summary["comparison"]["ngspice_dc_cross_check"] = {
        "four_dc": float(four_dc), "meas_avg": float(meas_dc),
        "rel_diff": dc_cross, "tol": 1e-3, "ok": dc_cross_ok,
      }
      ok = ok and dc_cross_ok
    # 相位护栏：p2 基波相位互差（余弦参考口径，ngspice 正弦参考换算）
    ref_p2 = summary["ngspice"]["fourier"].get("p2", {}).get("harmonics", {}).get(1)
    if ref_p2 is not None:
      hb_phase = base["summary"]["p2"]["phase_deg_cos"]["1"]
      ref_phase = spice_netlist.ngspice_phase_to_cosine(ref_p2["phase_deg"])
      dph = float((hb_phase - ref_phase + 180.0) % 360.0 - 180.0)
      summary["comparison"]["phase_p2_h1_deg"] = {
        "hb_cos_ref": hb_phase, "ngspice_cos_ref": ref_phase, "delta": dph,
      }
  except Exception as exc:
    summary["comparison"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    ok = False

  summary["ok"] = bool(ok)
  summary["wall_time_s"] = time.time() - t0
  _write_report(summary, out_dir)
  logger.info("A3 场路协同锚完成: ok=%s 报告=%s", ok, out_dir / "anchor_report.json")
  return summary


def _write_report(summary: dict[str, Any], out_dir: Path) -> None:
  out_dir = Path(out_dir)
  out_dir.mkdir(parents=True, exist_ok=True)
  (out_dir / "anchor_report.json").write_text(
    json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8",
  )


def _jsonable(value: Any) -> Any:
  """summary → JSON 原生（numpy/复数收敛；HBSolution 剥离）。"""
  if isinstance(value, dict):
    return {str(k): _jsonable(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_jsonable(v) for v in value]
  if isinstance(value, complex):
    return {"re": value.real, "im": value.imag}
  if isinstance(value, (np.floating, float)):
    v = float(value)
    return None if not math.isfinite(v) else v
  if isinstance(value, np.integer):
    return int(value)
  if isinstance(value, np.bool_):
    return bool(value)
  if isinstance(value, Path):
    return str(value)
  return value
