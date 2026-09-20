"""calibrate_surrogate：代理自动校准服务（v1，设计文档 §3）。

流程（全自动，"放入配方即校准"）：
1. 读配方 → 调参 bounds / objectives / 频段 / 模板名
2. Taguchi 正交采样（默认 3 水平，9-27 点）
3. 采样执行（sampler="openems" 真跑 / "fake" 测试与演示）→ 每点 metrics
4. PolyRidgeSurrogate 拟合 + LOOCV ρ 留一验收（P0 gate 口径 ≥0.8）
5. LHS 验证点实跑复核（预测 vs 实际 Δ 逐指标记录）
6. 产物落 runs/<rid>/calibration/（样本/gate/报告），meta 登记

模块解耦（设计红线）：采样执行与采样设计分离（sampler_fn 注入）；
代理训练与代理使用分离（产物是标准 SurrogateModel 配置，tune 链路
只认注册表）。gate FAIL 是正常返回（verdict="FAIL"），不是异常。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SAMPLER_REPORT_KEYS = ("ok", "verdict", "run_id")


def _template_for(model: str) -> str:
  from rfauto.service.ui_service import _template_hint

  hint = _template_hint({"model": model})
  if hint is None:
    raise ValueError(f"模型无 openEMS 模板映射: {model}")
  return hint


def _make_sampler(sampler: str, template: str, freq_range: tuple[float, float],
         objectives: list[Any], work_root: Path,
         mesh_resolution_mm: float = 0.5):
  """构造采样执行函数 params→metrics（采样执行与设计分离）。"""
  if sampler == "fake":
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.objectives import SpecEvaluator

    def run_fake(params: dict[str, float]) -> dict[str, float]:
      ad = FakeAdapter(model_type=template, n_ports=3,
               freq_ghz=(freq_range[0], freq_range[1], 201))
      ad.connect({})
      ad.set_variables({k: f"{v}mm" for k, v in params.items()})
      ad.solve("main_setup")
      metrics = SpecEvaluator.compute_metrics(
        ad.get_sparams(), objectives)
      ad.close()
      return metrics

    return run_fake
  if sampler == "openems":
    from rfauto.adapters.em_solver_base import (
      EMSolverConfig,
      resolve_openems_exe,
    )
    from rfauto.adapters.openems_solver import OpenEMSSolver

    def run_openems(params: dict[str, float]) -> dict[str, float]:
      import skrf

      from rfauto.core.objectives import SpecEvaluator

      work = work_root / f"pt_{int(time.time() * 1000) % 10**10}"
      solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems",
        exe_path=resolve_openems_exe(),
        working_dir=str(work),
        freq_range_ghz=tuple(freq_range),
        mesh_resolution_mm=mesh_resolution_mm,
        # 高 Q 结构/辐射器件单点可超默认 2.78h（patch 冒烟实测超时），
        # 放宽到 10h——NrTS=100000 硬上限仍在，超时兜底不取消
        extra_params={"solve_timeout_s": 36000},
      ))
      if not solver.connect():
        raise RuntimeError("openEMS 不可用（exe 未找到）")
      if not solver.build_geometry({"template": template, "params": params}):
        raise RuntimeError("openEMS 几何构建失败")
      result = solver.solve()
      if not result.success or result.s_params is None:
        raise RuntimeError(f"openEMS 求解失败: {result.message}")
      network = skrf.Network(
        frequency=skrf.Frequency(
          result.freq_ghz[0], result.freq_ghz[-1],
          len(result.freq_ghz), unit="ghz"),
        s=result.s_params, z0=50.0)
      return SpecEvaluator.compute_metrics(network, objectives)

    return run_openems
  raise ValueError(f"未知 sampler: {sampler}（可选 fake|openems）")


def _run_point(config: dict, params: dict[str, float]) -> dict[str, float]:
  """池化 worker 入口（模块级=可 pickle）：config→采样函数→单点执行。"""
  from rfauto.core.objectives import Objective

  run_fn = _make_sampler(
    config["sampler"], config["template"], tuple(config["freq_range"]),
    [Objective(**o) for o in config["objectives"]],
    Path(config["work_root"]),
    mesh_resolution_mm=config.get("mesh_resolution_mm", 0.5))
  return run_fn(params)


# --------------------------------------------------------------------------- #
# D12 FSV 曲线级等级（补强）
# --------------------------------------------------------------------------- #
# 曲线级等级字段（fsv_curve_levels / fsv_validation_levels / compare.fsv）与
# 既有单点容差判定（validation_max_delta / rho / recall）并行暴露、数值互不影响；
# verdict 并入走 fsv_grade_gate 的等级门语义（收口：GDM 评级并入
# verdict 口径）——FSV 不可用时门降级，verdict 回既有单点口径，不因缺曲线 FAIL。

#: FSV 等级门默认门限：GDM 等级序 ≤ Fair（Ex/VG/G/F）可接受；Poor/Very Poor
#: = 曲线级一致性不足，verdict 降级 FAIL（六级界 GRADE_BOUNDS 0.8/1.6 处）。
FSV_GRADE_THRESHOLD = "F"


def fsv_grade_gate(
  section: Any,
  *,
  threshold: str = FSV_GRADE_THRESHOLD,
) -> dict[str, Any]:
  """FSV 段 → 等级门判定（verdict 并入的共享语义，JSON 安全）。

  兼容两种 FSV 段形状：单曲线（fsv_curve_levels：gdm_grade）与多曲线
  （fsv_validation_levels / fsv_levels_from_curves：worst_gdm_grade）。
  门语义：
  - 段可用且等级序 ≤ 门限序 → pass=True（不影响 verdict）；
  - 段可用且等级序 > 门限序 → pass=False（verdict 降级 FAIL 依据）；
  - 段不可用/缺失/门限非法 → degraded=True、pass=None：门**不参与**判定，
   调用方必须按既有单点口径判定（降级路径——禁止因 FSV 缺席而 FAIL）。
  """
  from rfauto.core.fsv import GRADE_CODES

  thr = str(threshold).upper()
  if thr not in GRADE_CODES:
    return {"threshold": str(threshold), "grade": None, "pass": None,
        "degraded": True, "reason": f"未知门限等级: {threshold}"}
  if not isinstance(section, dict) or not section.get("ok"):
    err = section.get("error") if isinstance(section, dict) else None
    return {"threshold": thr, "grade": None, "pass": None,
        "degraded": True,
        "reason": err or "FSV 段不可用（点数不足/无曲线）"}
  grade = section.get("worst_gdm_grade") or section.get("gdm_grade")
  if not grade:
    return {"threshold": thr, "grade": None, "pass": None,
        "degraded": True, "reason": "FSV 段无 GDM 等级"}
  gi = GRADE_CODES.index(str(grade))
  ti = GRADE_CODES.index(thr)
  gate_pass = gi <= ti
  reason = (f"GDM 等级 {grade}（序 {gi}）≤ 门限 {thr}（序 {ti}）"
       if gate_pass else
       f"GDM 等级 {grade} 差于门限 {thr}（曲线级一致性不足，序 {gi}>{ti}）")
  return {"threshold": thr, "grade": str(grade), "pass": gate_pass,
      "degraded": False, "reason": reason}

#: dB 幅度下限（避免 log10(0)）；与 core/macromodel 同口径数量级。
_DB_FLOOR = 1e-9

#: openEMS sparams.csv 列序 → S 矩阵 (out, in) 下标（见 health_service 解析器）。
_S_PARAM_INDEX: dict[str, tuple[int, int]] = {
  "S11": (0, 0), "S21": (1, 0), "S31": (2, 0),
}


def _numeric(value: object) -> float | None:
  """数值（int/float/numpy 标量）→ float；bool/str/其它 → None。"""
  if isinstance(value, (bool, str)):
    return None
  try:
    return float(value) # type: ignore[arg-type]
  except (TypeError, ValueError):
    return None


def _grade_label(code: str) -> str:
  """FSV 六级短码 → 全称（Excellent/Very Good/...）。"""
  from rfauto.core.fsv import GRADE_CODES, GRADE_LABELS

  return GRADE_LABELS[GRADE_CODES.index(code)]


def fsv_curve_levels(
  freq_a: object,
  val_a: object,
  freq_b: object,
  val_b: object,
  *,
  n_points: int | None = None,
  include_offset: bool = True,
) -> dict[str, Any]:
  """曲线对 → FSV ADM/FDM/GDM 六级等级（JSON 安全，core/fsv 唯一计算路径）。

  加性接口：与既有单点容差判定**并行暴露**，供后续切换为曲线级判据。
  非法输入 / 无公共横轴区间 / 公共轴点数不足一律 best-effort 返回
  {"ok": False, "error": ...}，不抛异常（#105：观测性不得成为故障点）。
  """
  from rfauto.core.fsv import fsv, to_jsonable

  try:
    raw = to_jsonable(fsv(freq_a, val_a, freq_b, val_b,
               n_points=n_points,
               include_offset=include_offset))
  except Exception as exc: # 非法输入/无公共区间/点数不足 → best-effort
    return {"ok": False, "error": str(exc)}
  return {
    "ok": True,
    "adm_grade": raw["adm_grade"],
    "adm_grade_label": _grade_label(str(raw["adm_grade"])),
    "fdm_grade": raw["fdm_grade"],
    "fdm_grade_label": _grade_label(str(raw["fdm_grade"])),
    "gdm_grade": raw["gdm_grade"],
    "gdm_grade_label": _grade_label(str(raw["gdm_grade"])),
    "adm_mean": raw["adm_mean"],
    "fdm_mean_abs": raw["fdm_mean_abs"],
    "gdm_mean": raw["gdm_mean"],
    "gdm_grade_level": raw["gdm_grade_level"],
    "gdm_spread": raw["gdm_spread"],
    "n_points": raw["n_points"],
    "band": raw["band"],
    "include_offset": bool(include_offset),
  }


def _worst_gdm_grade(entries: dict[str, Any]) -> str | None:
  """多条曲线里最差（等级下标最大）的 GDM 短码；全失败 → None。"""
  from rfauto.core.fsv import GRADE_CODES, grade_index_of

  worst = -1
  for entry in entries.values():
    if entry.get("ok"):
      worst = max(worst, grade_index_of(float(entry["gdm_mean"])))
  return GRADE_CODES[worst] if worst >= 0 else None


def _fsv_summary_line(section: Any) -> str:
  """把 FSV 段渲染成报告一行（best-effort；不可用即写原因，不抛）。"""
  if not isinstance(section, dict):
    return "未计算"
  if not section.get("ok"):
    return f"不可用（{section.get('error', '无曲线')}）"
  entries = section.get("entries") or {}
  parts = [f"{k}={v.get('gdm_grade')}"
       for k, v in sorted(entries.items()) if v.get("ok")]
  worst = section.get("worst_gdm_grade")
  return f"worst GDM={worst}（" + ", ".join(parts) + "）"


def _fsv_gate_summary_line(gate: Any) -> str:
  """把 FSV 等级门渲染成报告一行（best-effort，不抛）。"""
  if not isinstance(gate, dict):
    return "未计算"
  grade = gate.get("grade")
  if gate.get("degraded") or grade is None:
    return f"降级（{gate.get('reason', '等级门不参与')}）"
  return (f"{'PASS' if gate.get('pass') else 'FAIL'}"
      f"（worst GDM {grade} vs 门限 {gate.get('threshold')}）")


def fsv_levels_from_curves(
  curves: dict[str, tuple[object, object]],
  *,
  reference: str | None = None,
  n_points: int | None = None,
  include_offset: bool = True,
) -> dict[str, Any]:
  """多曲线 → 参考曲线 vs 其余各条的 FSV 等级（曲线级判读，JSON 安全）。

  curves: {名称: (横轴, 纵轴)}；参考缺省取名称排序首个。逐条失败
  best-effort 落到 entries[name]["ok"]=False，不影响其余曲线。
  """
  if not curves:
    return {"ok": False, "error": "空曲线集", "reference": None,
        "n_curves": 0, "entries": {}, "worst_gdm_grade": None}
  names = sorted(curves)
  ref = reference if reference in curves else names[0]
  freq_ref, val_ref = curves[ref]
  entries: dict[str, Any] = {}
  for name in names:
    if name == ref:
      continue
    freq_b, val_b = curves[name]
    entries[name] = fsv_curve_levels(
      freq_ref, val_ref, freq_b, val_b,
      n_points=n_points, include_offset=include_offset)
  return {
    "ok": any(e.get("ok") for e in entries.values()),
    "reference": ref,
    "n_curves": len(names),
    "entries": entries,
    "worst_gdm_grade": _worst_gdm_grade(entries),
  }


def fsv_validation_levels(
  validation: list[dict[str, Any]],
  *,
  include_offset: bool = True,
) -> dict[str, Any]:
  """验证点序列上的「实际 vs 代理预测」曲线级 FSV 等级（逐指标，JSON 安全）。

  横轴 = 验证点序号（LHS 点序，确定性）。**加性**：既有单点容差口径
  （validation_max_delta / 各点 abs_delta）原样保留、数值不变。
  有效点 < core.fsv.MIN_POINTS 时如实返回不可用（曲线级判读需 ≥16 点）。
  """
  from rfauto.core.fsv import MIN_POINTS

  pts = [v for v in validation
      if isinstance(v, dict) and "error" not in v
      and isinstance(v.get("actual"), dict)
      and isinstance(v.get("predicted"), dict)]
  n = len(pts)
  if n < MIN_POINTS:
    return {"ok": False,
        "error": (f"有效验证点 {n} < MIN_POINTS={MIN_POINTS}，"
             "曲线级 FSV 不可用（单点容差不受影响）"),
        "n_validation": n, "min_points": MIN_POINTS,
        "entries": {}, "worst_gdm_grade": None}
  keys = set(pts[0]["actual"]) & set(pts[0]["predicted"])
  for p in pts[1:]:
    keys &= set(p["actual"]) & set(p["predicted"])
  keys = {k for k in keys
      if all(_numeric(p["actual"].get(k)) is not None
          and _numeric(p["predicted"].get(k)) is not None
          for p in pts)}
  x = [float(i) for i in range(n)]
  entries = {
    key: fsv_curve_levels(
      x, [float(p["actual"][key]) for p in pts],
      x, [float(p["predicted"][key]) for p in pts],
      include_offset=include_offset)
    for key in sorted(keys)
  }
  return {"ok": any(e.get("ok") for e in entries.values()),
      "n_validation": n, "x_axis": "验证点序号（LHS 点序）",
      "entries": entries,
      "worst_gdm_grade": _worst_gdm_grade(entries)}


def fsv_run_curve_levels(
  run_dir: str | Path,
  *,
  s_param: str = "S11",
  db: bool = True,
  reference: str | None = None,
  n_points: int | None = None,
  include_offset: bool = True,
  pattern: str = "sparams.csv",
  max_curves: int | None = None,
) -> dict[str, Any]:
  """读 run 归档 sparams.csv 曲线 → 曲线级 FSV 等级（判读复算，JSON 安全）。

  把「单点指标容差」判读升级为曲线级判读（patch v2 复算用）。归档不全
  时用**可得曲线**，缺失/解析失败逐条记入 errors 并如实返回；目录不存在
  或无曲线 → ok=False。解析复用 health_service 的 openEMS sparams.csv
  解析器（杜绝第二实现漂移， ⑥）。
  """
  import numpy as np

  from rfauto.service.health_service import _parse_sparams_csv

  root = Path(run_dir)
  if not root.is_dir():
    return {"ok": False, "error": f"run 目录不存在: {root}",
        "entries": {}, "errors": []}
  key = s_param.upper()
  idx = _S_PARAM_INDEX.get(key)
  if idx is None:
    return {"ok": False,
        "error": f"不支持的 s_param: {s_param}"
             f"（可选 {sorted(_S_PARAM_INDEX)}）",
        "entries": {}, "errors": []}
  i, j = idx
  curves: dict[str, tuple[list[float], list[float]]] = {}
  errors: list[str] = []
  for path in sorted(root.rglob(pattern)):
    if max_curves is not None and len(curves) >= max_curves:
      break
    rel = str(path.relative_to(root)).replace("\\", "/")
    try:
      parsed = _parse_sparams_csv(path)
    except Exception as exc:
      errors.append(f"{rel}: {exc}")
      continue
    if parsed is None:
      errors.append(f"{rel}: 解析为空（行/列数不足）")
      continue
    freq_hz, s = parsed
    if s.ndim < 3 or s.shape[1] <= i or s.shape[2] <= j:
      errors.append(f"{rel}: 端口数不足，无 {key}")
      continue
    mag = np.abs(s[:, i, j])
    vals = 20.0 * np.log10(np.maximum(mag, _DB_FLOOR)) if db else mag
    curves[rel] = ([float(v) for v in freq_hz], [float(v) for v in vals])
  if not curves:
    return {"ok": False, "error": f"未找到可用曲线（pattern={pattern}）",
        "entries": {}, "errors": errors}
  levels = fsv_levels_from_curves(
    curves, reference=reference, n_points=n_points,
    include_offset=include_offset)
  return levels | {
    "run_dir": str(root), "s_param": key, "db": bool(db),
    "n_curves": len(curves),
    "curve_files": sorted(curves),
    "errors": errors,
  }


def calibrate_surrogate(
  recipe_path: str | Path,
  *,
  sampler: str = "fake",
  n_levels: int = 3,
  n_validation: int = 2,
  order: int = 2,
  ridge_lambda: float = 0.1,
  seed: int = 42,
  rho_threshold: float = 0.8,
  mesh_resolution_mm: float = 0.5,
  n_workers: int = 1,
) -> dict[str, Any]:
  """校准代理并自动验收；返回 JSON 友好 dict（service 层契约）。

  n_workers>1 走进程池并行采样（4.3 worker 池）；默认 1=串行
  （openEMS 内存纪律：每 worker 1-2GB，按可用内存设置）。
  """
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta
  from rfauto.optimization.sample_design import lhs_points, taguchi_points
  from rfauto.optimization.surrogate import PolyRidgeSurrogate, loocv_rho

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方不存在: {path}"]}
  with open(path, encoding="utf-8") as f:
    recipe = yaml.safe_load(f) or {}
  opt = recipe.get("optimization") or {}
  bounds = {k: (float(v["low"]), float(v["high"]))
       for k, v in (opt.get("params") or {}).items()}
  if not bounds:
    return {"ok": False, "errors": ["配方无 optimization.params（搜索空间）"]}
  objectives = [Objective(**o) for o in recipe.get("objectives", [])]
  if not objectives:
    return {"ok": False, "errors": ["配方无 objectives，代理无从校准"]}
  freq_range = tuple(
    (recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))

  run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  calib_dir = run_dir / "calibration"
  calib_dir.mkdir(parents=True, exist_ok=True)
  work_root = calib_dir / "openems_work"

  template = _template_for(str(recipe.get("model", "")))
  run_fn = _make_sampler(sampler, template, freq_range, objectives, work_root,
              mesh_resolution_mm=mesh_resolution_mm)

  # ① Taguchi 主采样（n_workers>1 走进程池，4.3 worker 池）
  t0 = time.time()
  design = taguchi_points(bounds, n_levels=n_levels)
  samples: list[dict[str, Any]] = []
  failures: list[dict[str, Any]] = []
  if n_workers > 1:
    from functools import partial

    from rfauto.optimization.sampler_pool import run_sampling_pool

    pool_cfg = {"sampler": sampler, "template": template,
          "freq_range": list(freq_range),
          "objectives": recipe.get("objectives", []),
          "work_root": str(work_root),
          "mesh_resolution_mm": mesh_resolution_mm}
    pooled = run_sampling_pool(design["points"],
                  partial(_run_point, pool_cfg),
                  max_workers=n_workers)
    samples = [{"params": item["params"], "metrics": item["result"]}
          for item in pooled["results"]]
    failures = [{"point": f["params"], "error": f["error"]}
          for f in pooled["failures"]]
  else:
    for pt in design["points"]:
      try:
        metrics = run_fn(pt)
        samples.append({"params": pt, "metrics": metrics})
      except Exception as exc: # 单点失败不阻塞校准（如发散/网格失败）
        failures.append({"point": pt, "error": str(exc)})

  # ② 拟合 + LOOCV 验收
  def make_model() -> PolyRidgeSurrogate:
    # 注意：metrics 键留空 = 从样本自动取数值键并集（SpecEvaluator 的
    # 派生键如 s11_db_max_in_band，而非 objectives 的 s11_db 原名）
    return PolyRidgeSurrogate(config={
      "bounds": bounds, "order": order,
      "ridge_lambda": ridge_lambda})

  def cost_of(sample: dict[str, Any]) -> float:
    return SpecEvaluator.evaluate_objectives(sample["metrics"], objectives)

  loocv = loocv_rho(samples, cost_of, make_model) if samples else {
    "ok": False, "error": "无有效采样点"}

  # ③ LHS 验证点实跑复核
  validation = []
  if n_validation > 0 and samples:
    val_design = lhs_points(bounds, n_validation, seed=seed,
                include=[s["params"] for s in samples],
                min_dist=0.15)
    model = make_model()
    model.fit(samples)
    for pt in val_design["points"]:
      try:
        actual = run_fn(pt)
        pred = model.predict(pt)
        deltas = {k: abs(float(pred.get(k, 0)) - float(actual[k]))
             for k in actual if k in pred}
        validation.append({"params": pt, "actual": actual,
                  "predicted": pred, "abs_delta": deltas})
      except Exception as exc:
        validation.append({"params": pt, "error": str(exc)})

  elapsed = time.time() - t0

  # ④ gate 判定：LOOCV ρ ≥ 阈值 且验证点无失败；FSV 等级门（⑥
  # 收口）可用时否决 Poor/Very Poor 曲线级一致性，不可用即降级不参与
  rho = loocv.get("rho") if loocv.get("ok") else None
  val_failed = [v for v in validation if "error" in v]
  fsv_section = fsv_validation_levels(validation)
  fsv_gate = fsv_grade_gate(fsv_section)
  verdict = "PASS" if (
    rho is not None and rho >= rho_threshold and samples
    and not val_failed
    and fsv_gate["pass"] is not False) else "FAIL"

  result: dict[str, Any] = {
    "ok": True,
    "run_id": run_id,
    "run_dir": str(run_dir),
    "verdict": verdict,
    "loocv": loocv,
    "rho_threshold": rho_threshold,
    "n_samples": len(samples),
    "n_failures": len(failures),
    "n_validation": len(validation),
    "validation_max_delta": _max_delta(validation),
    # D12 FSV 曲线级等级（⑥）：等级经 fsv_grade_gate 并入 verdict
    "fsv_validation": fsv_section,
    "fsv_gate": fsv_gate,
    "design": design["design"],
    "sampler": sampler,
    "mesh_resolution_mm": mesh_resolution_mm,
    "elapsed_s": round(elapsed, 1),
  }
  if failures:
    result["failures"] = failures

  # ⑤ 产物落盘（校准数据是资产：v2 换 NN 代理时同一样本可复用）
  (calib_dir / "samples.json").write_text(
    json.dumps({"bounds": {k: list(v) for k, v in bounds.items()},
          "objectives": recipe.get("objectives", []),
          "samples": samples,
          "validation": validation,
          "design": design["design"],
          "mesh_resolution_mm": mesh_resolution_mm},
          ensure_ascii=False, indent=1), encoding="utf-8")
  (calib_dir / "gate.json").write_text(
    json.dumps({k: result[k] for k in
          ("verdict", "loocv", "rho_threshold", "validation_max_delta",
           "fsv_validation", "fsv_gate", "n_samples", "n_failures",
           "mesh_resolution_mm")},
          ensure_ascii=False, indent=1), encoding="utf-8")
  model = make_model()
  if samples:
    model.fit(samples)
  (calib_dir / "surrogate.json").write_text(
    json.dumps({"kind": model.KIND, "config": model.config,
          "metric_keys": sorted(getattr(model, "metric_keys", []))},
          ensure_ascii=False, indent=1), encoding="utf-8")
  (calib_dir / "report.md").write_text(
    _report_md(path, result, samples, validation), encoding="utf-8")
  write_meta(run_dir, {
    "run_id": run_id, "model": str(recipe.get("model", "")),
    "status": "done", "adapter": f"calibration:{sampler}",
    "algorithm": "surrogate_calibration",
    "metrics": {"verdict": verdict, "rho": rho,
          "n_samples": len(samples)}})
  return {k: v for k, v in result.items() if k not in _SAMPLER_REPORT_KEYS} | {
    k: result[k] for k in _SAMPLER_REPORT_KEYS}


def _max_delta(validation: list[dict[str, Any]]) -> float | None:
  deltas = [d for v in validation
       for d in (v.get("abs_delta") or {}).values()
       if isinstance(d, (int, float))]
  return max(deltas) if deltas else None


def _make_model(surrogate_kind: str, bounds: dict[str, tuple[float, float]],
        order: int, ridge_lambda: float):
  """按注册表构造代理（任意已注册 kind；训练与使用分离）。"""
  from rfauto.optimization.surrogate import surrogate_registry

  config: dict[str, Any] = {"bounds": bounds}
  if surrogate_kind == "poly_ridge":
    config.update({"order": order, "ridge_lambda": ridge_lambda})
  elif surrogate_kind not in surrogate_registry.available():
    raise ValueError(f"未知代理类型: {surrogate_kind}"
             f"（可用: {surrogate_registry.available()}）")
  return surrogate_registry.create(surrogate_kind, config=config)


def _lhs_augment_points(bounds: dict[str, tuple[float, float]],
            existing: list[dict[str, float]], n_new: int,
            seed: int, min_dist: float,
            max_rounds: int = 8) -> list[dict[str, float]]:
  """生成与既有点保持归一化最小距离的 n_new 个 LHS 增广点（多轮补齐）。"""

  from rfauto.optimization.sample_design import lhs_points, np_rel

  names = sorted(bounds)
  lower = [bounds[n][0] for n in names]
  span = [max(bounds[n][1] - bounds[n][0], 1e-12) for n in names]

  def dist_to_pool(pt: dict[str, float], pool: list[dict[str, float]]) -> float:
    pn = np_rel(pt, names, lower, span)
    if not pool:
      return float("inf")
    return min(sum((pn[n] - q.get(n, pn[n])) ** 2 for n in names) ** 0.5
          for q in pool)

  accepted: list[dict[str, float]] = []
  pool = [dict(p) for p in existing]
  for rnd in range(max_rounds):
    need = n_new - len(accepted)
    if need <= 0:
      break
    cand = lhs_points(bounds, need * 4 + 4, seed=seed + rnd,
             include=pool, min_dist=min_dist)["points"]
    progressed = False
    for pt in cand:
      if len(accepted) >= n_new:
        break
      if dist_to_pool(pt, pool) >= min_dist:
        accepted.append(pt)
        pool.append(dict(pt))
        progressed = True
    if not progressed:
      break # 空间饱和：min_dist 过大，如实返回已得点
  return accepted


def augment_calibration(
  recipe_path: str | Path,
  seed_samples_path: str | Path,
  *,
  sampler: str = "fake",
  n_new: int = 16,
  n_validation: int = 2,
  order: int = 2,
  ridge_lambda: float = 0.1,
  seed: int = 42,
  rho_threshold: float = 0.8,
  mesh_resolution_mm: float = 0.45, # 新语义=网格 base 覆盖；0.45≈λ_sub/100 收敛档
  min_dist: float = 0.12,
  surrogate_kind: str = "poly_ridge",
  n_workers: int = 1,
) -> dict[str, Any]:
  """LHS 增广校准（0.2）：从种子样本集出发补采 n_new 点 → 合并重拟合 → gate。

  种子数据集是资产（runs/<rid>/calibration/samples.json），增广只跑新增点，
  旧样本原样复用——样本量是 0.3mm ρ=0.75→0.8 gate 缺口的主控变量。
  """
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta
  from rfauto.optimization.sample_design import lhs_points
  from rfauto.optimization.surrogate import loocv_rho

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方不存在: {path}"]}
  seed_path = Path(seed_samples_path)
  if not seed_path.exists():
    return {"ok": False, "errors": [f"种子样本集不存在: {seed_path}"]}
  with open(path, encoding="utf-8") as f:
    recipe = yaml.safe_load(f) or {}
  opt = recipe.get("optimization") or {}
  bounds = {k: (float(v["low"]), float(v["high"]))
       for k, v in (opt.get("params") or {}).items()}
  if not bounds:
    return {"ok": False, "errors": ["配方无 optimization.params（搜索空间）"]}
  objectives = [Objective(**o) for o in recipe.get("objectives", [])]
  if not objectives:
    return {"ok": False, "errors": ["配方无 objectives，代理无从校准"]}
  freq_range = tuple(
    (recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))

  seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
  seed_samples = list(seed_data.get("samples") or [])
  if not seed_samples:
    return {"ok": False, "errors": [f"种子样本集为空: {seed_path}"]}
  seed_bounds = seed_data.get("bounds") or {}
  mismatched = [k for k in bounds
         if k in seed_bounds and list(map(float, seed_bounds[k]))
         != list(bounds[k])]
  seed_only = [k for k in seed_bounds if k not in bounds]
  if seed_only or (seed_bounds and any(
      k not in seed_bounds for k in bounds)):
    return {"ok": False, "errors": [
      f"种子样本集与配方搜索空间不一致: seed_only={seed_only} "
      f"missing_in_seed={[k for k in bounds if k not in seed_bounds]}"]}
  if mismatched:
    return {"ok": False, "errors": [f"种子样本集边界与配方不一致: {mismatched}"]}

  run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  calib_dir = run_dir / "calibration"
  calib_dir.mkdir(parents=True, exist_ok=True)
  work_root = calib_dir / "openems_work"

  template = _template_for(str(recipe.get("model", "")))
  run_fn = _make_sampler(sampler, template, freq_range, objectives, work_root,
              mesh_resolution_mm=mesh_resolution_mm)

  t0 = time.time()
  new_points = _lhs_augment_points(
    bounds, [s["params"] for s in seed_samples], n_new, seed, min_dist)
  new_samples: list[dict[str, Any]] = []
  failures: list[dict[str, Any]] = []
  if n_workers > 1:
    # 新增点走进程池（同 calibrate_surrogate 的 4.3 worker 池口径）
    from functools import partial

    from rfauto.optimization.sampler_pool import run_sampling_pool

    pool_cfg = {"sampler": sampler, "template": template,
          "freq_range": list(freq_range),
          "objectives": recipe.get("objectives", []),
          "work_root": str(work_root),
          "mesh_resolution_mm": mesh_resolution_mm}
    pooled = run_sampling_pool(new_points,
                  partial(_run_point, pool_cfg),
                  max_workers=n_workers)
    new_samples = [{"params": item["params"], "metrics": item["result"]}
            for item in pooled["results"]]
    failures = [{"point": f["params"], "error": f["error"]}
          for f in pooled["failures"]]
  else:
    for pt in new_points:
      try:
        metrics = run_fn(pt)
        new_samples.append({"params": pt, "metrics": metrics})
      except Exception as exc: # 单点失败不阻塞增广
        failures.append({"point": pt, "error": str(exc)})
  merged = seed_samples + new_samples

  def make_model():
    return _make_model(surrogate_kind, bounds, order, ridge_lambda)

  def cost_of(sample: dict[str, Any]) -> float:
    return SpecEvaluator.evaluate_objectives(sample["metrics"], objectives)

  loocv = loocv_rho(merged, cost_of, make_model) if len(merged) > 2 else {
    "ok": False, "error": "合并样本不足"}

  validation = []
  if n_validation > 0 and len(merged) > 2:
    val_design = lhs_points(bounds, n_validation, seed=seed,
                include=[s["params"] for s in merged],
                min_dist=min_dist)
    model = make_model()
    model.fit(merged)
    for pt in val_design["points"]:
      try:
        actual = run_fn(pt)
        pred = model.predict(pt)
        deltas = {k: abs(float(pred.get(k, 0)) - float(actual[k]))
             for k in actual if k in pred}
        validation.append({"params": pt, "actual": actual,
                  "predicted": pred, "abs_delta": deltas})
      except Exception as exc:
        validation.append({"params": pt, "error": str(exc)})

  elapsed = time.time() - t0
  rho = loocv.get("rho") if loocv.get("ok") else None
  val_failed = [v for v in validation if "error" in v]
  # FSV 等级门（收口）：与 calibrate_surrogate 同语义
  fsv_section = fsv_validation_levels(validation)
  fsv_gate = fsv_grade_gate(fsv_section)
  verdict = "PASS" if (
    rho is not None and rho >= rho_threshold and new_samples
    and not val_failed
    and fsv_gate["pass"] is not False) else "FAIL"

  result: dict[str, Any] = {
    "ok": True,
    "run_id": run_id,
    "run_dir": str(run_dir),
    "verdict": verdict,
    "loocv": loocv,
    "rho_threshold": rho_threshold,
    "surrogate_kind": surrogate_kind,
    "n_seed_samples": len(seed_samples),
    "n_new_points": len(new_points),
    "n_new_samples": len(new_samples),
    "n_samples": len(merged),
    "n_failures": len(failures),
    "n_validation": len(validation),
    "validation_max_delta": _max_delta(validation),
    # D12 FSV 曲线级等级（⑥）：等级经 fsv_grade_gate 并入 verdict
    "fsv_validation": fsv_section,
    "fsv_gate": fsv_gate,
    "design": {"kind": "lhs_augment", "n_new": len(new_points),
          "seed": seed, "min_dist": min_dist},
    "sampler": sampler,
    "mesh_resolution_mm": mesh_resolution_mm,
    "augmented_from": str(seed_path),
    "elapsed_s": round(elapsed, 1),
  }
  if failures:
    result["failures"] = failures
  if mismatched:
    result["bounds_warnings"] = mismatched

  (calib_dir / "samples.json").write_text(
    json.dumps({"bounds": {k: list(v) for k, v in bounds.items()},
          "objectives": recipe.get("objectives", []),
          "samples": merged,
          "validation": validation,
          "design": result["design"],
          "augmented_from": str(seed_path),
          "seed_sample_count": len(seed_samples)},
          ensure_ascii=False, indent=1), encoding="utf-8")
  (calib_dir / "gate.json").write_text(
    json.dumps({k: result[k] for k in
          ("verdict", "loocv", "rho_threshold", "validation_max_delta",
           "fsv_validation", "fsv_gate", "n_samples", "n_failures",
           "surrogate_kind", "mesh_resolution_mm")},
          ensure_ascii=False, indent=1), encoding="utf-8")
  model = make_model()
  if len(merged) > 2:
    model.fit(merged)
  (calib_dir / "surrogate.json").write_text(
    json.dumps({"kind": model.KIND, "config": model.config,
          "metric_keys": sorted(getattr(model, "metric_keys", []))},
          ensure_ascii=False, indent=1), encoding="utf-8")
  (calib_dir / "report.md").write_text(
    _augment_report_md(path, result, seed_samples, new_samples, failures,
              validation), encoding="utf-8")
  write_meta(run_dir, {
    "run_id": run_id, "model": str(recipe.get("model", "")),
    "status": "done", "adapter": f"calibration:{sampler}",
    "algorithm": "surrogate_calibration_augment",
    "metrics": {"verdict": verdict, "rho": rho,
          "n_samples": len(merged),
          "n_new_samples": len(new_samples)}})
  return {k: v for k, v in result.items() if k not in _SAMPLER_REPORT_KEYS} | {
    k: result[k] for k in _SAMPLER_REPORT_KEYS}


def _augment_report_md(recipe_path: Path, result: dict[str, Any],
            seed_samples: list[dict[str, Any]],
            new_samples: list[dict[str, Any]],
            failures: list[dict[str, Any]],
            validation: list[dict[str, Any]]) -> str:
  loocv = result.get("loocv", {})
  rho = loocv.get("rho")
  lines = [
    "# LHS 增广校准报告",
    "",
    f"- 配方：{recipe_path}",
    f"- 种子样本集：{result['augmented_from']}（{result['n_seed_samples']} 点复用）",
    f"- 判定：**{result['verdict']}**（LOOCV ρ={rho if rho is None else round(rho, 3)}"
    f" / 阈值 {result['rho_threshold']}，代理 {result['surrogate_kind']}）",
    f"- 增广：LHS 新采 {result['n_new_points']} 点（有效 {result['n_new_samples']}，"
    f"失败 {result['n_failures']}），合并样本 {result['n_samples']} 点",
    f"- 网格：{result['mesh_resolution_mm']}mm；验证点 {result['n_validation']}，"
    f"最大指标偏差 {result['validation_max_delta']}",
    f"- D12 曲线级 FSV：{_fsv_summary_line(result.get('fsv_validation'))}",
    f"- D12 FSV 等级门：{_fsv_gate_summary_line(result.get('fsv_gate'))}",
    f"- 耗时：{result['elapsed_s']}s",
    "",
    "## 新增采样点",
    "",
  ]
  for s in new_samples:
    params = ", ".join(f"{k}={v}" for k, v in s["params"].items())
    metrics = ", ".join(f"{k}={v:.3f}" if isinstance(v, (int, float))
              else f"{k}={v}"
              for k, v in s["metrics"].items())
    lines.append(f"- {params} → {metrics}")
  for f_ in failures:
    lines.append(f"- {f_['point']} → 失败: {f_['error']}")
  if validation:
    lines += ["", "## 验证点（预测 vs 实际）", ""]
    for v in validation:
      if "error" in v:
        lines.append(f"- {v['params']} → 失败: {v['error']}")
      else:
        lines.append(f"- {v['params']} → Δ {v['abs_delta']}")
  lines += ["", "## 种子样本（复用）", ""]
  for s in seed_samples:
    params = ", ".join(f"{k}={v}" for k, v in s["params"].items())
    lines.append(f"- {params}")
  return "\n".join(lines) + "\n"


def compare_surrogates(
  samples_path: str | Path,
  kinds: tuple[str, ...] = ("poly_ridge", "nn"),
  *,
  rho_threshold: float = 0.8,
  fsv_curves: dict[str, tuple[object, object]] | None = None,
  fsv_reference: str | None = None,
) -> dict[str, Any]:
  """代理选型基准（阶段 1.2 第一片）：同一样本集离线对比各注册代理。

  只消费 samples.json（校准资产），零真机求解——LOOCV ρ + 拟合信息
  逐代理排序，胜者为默认预筛代理候选。gate 判定沿用 ρ≥阈值。

  加性（⑥）：可选 fsv_curves={名称: (横轴, 纵轴)} 提供曲线级判读，
  结果多出 "fsv" 段；缺省（标量样本集无曲线）时该段如实记 ok=False，
  既有 ρ / ranking / gate 契约与数值逐字不变。
  """
  path = Path(samples_path)
  if not path.exists():
    return {"ok": False, "errors": [f"样本集不存在: {path}"]}
  data = json.loads(path.read_text(encoding="utf-8"))
  samples = list(data.get("samples") or [])
  bounds_raw = data.get("bounds") or {}
  if not samples:
    return {"ok": False, "errors": ["样本集为空"]}
  bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds_raw.items()}
  objectives = data.get("objectives") or []

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.optimization.surrogate import loocv_rho

  objs = [Objective(**o) for o in objectives]

  def cost_of(sample: dict[str, Any]) -> float:
    return SpecEvaluator.evaluate_objectives(sample["metrics"], objs)

  rows = []
  for kind in kinds:
    try:
      _make_model(kind, bounds, order=2, ridge_lambda=0.1)
    except (KeyError, ValueError) as exc:
      rows.append({"kind": kind, "ok": False, "error": str(exc)})
      continue
    loocv = loocv_rho(samples, cost_of, lambda k=kind: _make_model(
      k, bounds, order=2, ridge_lambda=0.1))
    row: dict[str, Any] = {
      "kind": kind, "ok": bool(loocv.get("ok")),
      "rho": loocv.get("rho"),
      "gate": ("PASS" if loocv.get("ok") and
           (loocv.get("rho") or -1) >= rho_threshold else "FAIL"),
      "n_samples": len(samples),
    }
    if not row["ok"]:
      row["error"] = loocv.get("error")
    rows.append(row)
  ranked = sorted(
    (r for r in rows if r.get("ok")),
    key=lambda r: r.get("rho") or -1.0, reverse=True)
  fsv = (fsv_levels_from_curves(fsv_curves, reference=fsv_reference)
      if fsv_curves else
      {"ok": False,
      "error": "未提供曲线（代理选型只消费标量 metrics）；"
           "传 fsv_curves={名称: (横轴, 纵轴)} 启用曲线级判读",
      "entries": {}, "worst_gdm_grade": None})
  return {"ok": True, "samples_path": str(path), "rho_threshold": rho_threshold,
      "results": rows, "ranking": [r["kind"] for r in ranked],
      "best": ranked[0]["kind"] if ranked else None,
      "fsv": fsv}


def _report_md(recipe_path: Path, result: dict[str, Any],
        samples: list[dict[str, Any]],
        validation: list[dict[str, Any]]) -> str:
  loocv = result.get("loocv", {})
  rho = loocv.get("rho")
  lines = [
    "# 代理校准报告",
    "",
    f"- 配方：{recipe_path}",
    f"- 判定：**{result['verdict']}**（LOOCV ρ={rho if rho is None else round(rho, 3)}"
    f" / 阈值 {result['rho_threshold']}）",
    f"- 采样：{result['design']}，有效 {result['n_samples']} 点，"
    f"失败 {result['n_failures']}；验证点 {result['n_validation']}",
    f"- 网格：{result['mesh_resolution_mm']}mm"
    f"（base 覆盖；0=官方自动 λ_sub/50）",
    f"- 验证点最大指标偏差：{result['validation_max_delta']}",
    f"- D12 曲线级 FSV：{_fsv_summary_line(result.get('fsv_validation'))}",
    f"- D12 FSV 等级门：{_fsv_gate_summary_line(result.get('fsv_gate'))}",
    f"- 耗时：{result['elapsed_s']}s",
    "",
    "## 采样点",
    "",
  ]
  for s in samples:
    metrics = ", ".join(f"{k}={v:.3f}" if isinstance(v, (int, float)) else f"{k}={v}"
              for k, v in s["metrics"].items())
    params = ", ".join(f"{k}={v}" for k, v in s["params"].items())
    lines.append(f"- {params} → {metrics}")
  if validation:
    lines += ["", "## 验证点（预测 vs 实际）", ""]
    for v in validation:
      if "error" in v:
        lines.append(f"- {v['params']} → 失败: {v['error']}")
      else:
        lines.append(f"- {v['params']} → Δ {v['abs_delta']}")
  return "\n".join(lines) + "\n"
