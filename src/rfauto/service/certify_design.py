"""certify_design：可认证设计（阶段 7.6 首片，形式化方法借鉴的保守版）。

用代理 + 确定性误差界做**区间传播**：给定参数公差盒，把代理预测的
指标不确定性传播为区间 [lo, hi]，对每条 objective 给出三值证书：
- PASS：区间整体满足 spec（公差内必然合格——可认证）；
- FAIL：区间整体违反 spec；
- UNKNOWN：区间横跨阈值（样本不足/公差过大，如实不证明）。

误差界口径（保守、可复核）：代理在参数盒上的 Lipschitz 常数 L_i 由
有限差分网格估计（每轴 n_grid 点），指标区间 = 中心预测 ± Σ L_i·Δx_i。
这是 sound-but-conservative 界（低估 L 会漏报，故网格足够密并随
n_grid 增大单调收紧——测试覆盖该单调性）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def certify_design(
  samples_path: str | Path,
  params_center: dict[str, float],
  *,
  tolerance_pct: float = 0.02,
  n_grid: int = 9,
  kind: str = "poly_ridge",
) -> dict[str, Any]:
  """公差盒 → 指标区间证书（确定性内核）。

  tolerance_pct：每参数 ±公差（相对该轴搜索空间 span 的百分比）。
  """
  from rfauto.core.objectives import Objective

  path = Path(samples_path)
  if not path.exists():
    return {"ok": False, "errors": [f"样本集不存在: {path}"]}
  data = json.loads(path.read_text(encoding="utf-8"))
  samples = list(data.get("samples") or [])
  bounds_raw = data.get("bounds") or {}
  objectives_raw = data.get("objectives") or []
  if len(samples) < 5:
    return {"ok": False, "errors": ["样本点不足（需 ≥5）"]}
  if not objectives_raw:
    return {"ok": False, "errors": ["样本集无 objectives，无法出证书"]}
  bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds_raw.items()}
  names = sorted(bounds)
  missing = [n for n in names if n not in params_center]
  if missing:
    return {"ok": False,
        "errors": [f"params_center 缺轴: {missing}"]}

  from rfauto.service.calibration_service import _make_model

  model = _make_model(kind, bounds, order=2, ridge_lambda=0.1)
  model.fit(samples)
  objectives = [Objective(**o) for o in objectives_raw]

  def metrics_at(pt: dict[str, float]) -> dict[str, float]:
    pred = model.predict(pt)
    return {k: float(v) for k, v in pred.items()
        if isinstance(v, (int, float))}

  center = {n: float(params_center[n]) for n in names}
  deltas = {n: (bounds[n][1] - bounds[n][0]) * tolerance_pct / 2.0
       for n in names}
  center_metrics = metrics_at(center)

  def metric_key(metric: str) -> str | None:
    """objective.metric → 代理产出指标名（s11_db → s11_db_max_in_band）。"""
    if metric in center_metrics:
      return metric
    prefix = metric + "_"
    for k in center_metrics:
      if k.startswith(prefix):
        return k
    return None

  # Lipschitz 估计：每轴在 [x_i-Δ, x_i+Δ] 上 n_grid 点有限差分
  lipschitz: dict[str, dict[str, float]] = {n: {} for n in names}
  for n in names:
    for m in center_metrics:
      vals = []
      for gi in range(n_grid):
        frac = gi / (n_grid - 1) * 2 - 1 # -1..1
        pt = dict(center)
        pt[n] = min(max(center[n] + frac * deltas[n],
                bounds[n][0]), bounds[n][1])
        v = metrics_at(pt).get(m)
        if v is not None:
          vals.append(abs(v - center_metrics[m])
                / max(abs(frac) * deltas[n], 1e-12))
      lipschitz[n][m] = max(vals) if vals else 0.0

  certificates: list[dict[str, Any]] = []
  n_pass = n_fail = n_unknown = 0
  for obj in objectives:
    m = metric_key(obj.metric)
    if m is None:
      certificates.append({"metric": obj.metric, "verdict": "UNKNOWN",
                 "reason": "代理不产出该指标"})
      n_unknown += 1
      continue
    radius = sum(lipschitz[n].get(m, 0.0) * deltas[n] for n in names)
    lo = center_metrics[m] - radius
    hi = center_metrics[m] + radius
    thr = float(obj.value)
    op = str(getattr(obj.op, "value", obj.op))
    if op == "max_below":     # 指标 ≤ thr 为合格（|S11|dB 负值口径）
      ok_lo, ok_hi = lo <= thr, hi <= thr
    else:             # min_above：指标 ≥ thr 为合格（隔离/增益）
      ok_lo, ok_hi = lo >= thr, hi >= thr
    if ok_lo and ok_hi:
      verdict = "PASS"
      n_pass += 1
    elif not ok_lo and not ok_hi:
      verdict = "FAIL"
      n_fail += 1
    else:
      verdict = "UNKNOWN"
      n_unknown += 1
    certificates.append({
      "metric": obj.metric, "metric_key": m, "op": obj.op,
      "threshold": thr,
      "band": obj.band, "center_value": round(center_metrics[m], 4),
      "interval": [round(lo, 4), round(hi, 4)],
      "radius": round(radius, 4), "verdict": verdict,
    })

  overall = ("CERTIFIED" if n_unknown == 0 and n_fail == 0
        else "FAIL" if n_fail and not n_pass and n_unknown == 0
        else "PARTIAL")
  return {
    "ok": True,
    "samples_path": str(path),
    "surrogate_kind": kind,
    "params_center": {n: round(center[n], 6) for n in names},
    "tolerance_pct": tolerance_pct,
    "lipschitz_grid": n_grid,
    "certificates": certificates,
    "n_pass": n_pass, "n_fail": n_fail, "n_unknown": n_unknown,
    "verdict": overall,
    "note": "保守界：Lipschitz 有限差分估计；UNKNOWN=证据不足，如实不证明",
  }


# ---------------------------------------------------------------------------
# NASA-STD-7009 八因素可信度证据包（）
# ---------------------------------------------------------------------------
# 汇流三源（只搬运既有确定性结果，不新造物理数字，数值铁律）：
#  G11 service/health_service.health_check_run → core/solve_health（九因子）
#  D12 service/calibration_service.fsv_curve_levels → core/fsv（ADM/FDM/GDM）
#  D10 service/koh_service.KOHCalibrator.predict（调用方给出已算好的 95% 区间）
# 每个字段带 provenance；缺源如实标 UNKNOWN，不编造。

#: 八因素键（七因素 + 结论；顺序固定、可复核）
NASA_FACTORS: tuple[str, ...] = (
  "v_and_v",
  "input_pedigree",
  "uncertainty_characterization",
  "results_robustness",
  "ms_history",
  "data_history",
  "vv_history",
  "conclusion",
)

#: 因素标签（渲染用，不参与判定）
NASA_FACTOR_LABELS: dict[str, str] = {
  "v_and_v": "Verification & Validation（G11 求解健康度）",
  "input_pedigree": "Input Pedigree（输入溯源）",
  "uncertainty_characterization": "Uncertainty Characterization（不确定性表征）",
  "results_robustness": "Results Robustness（公差鲁棒性）",
  "ms_history": "M&S History（模型与仿真历史）",
  "data_history": "Data History（数据历史）",
  "vv_history": "V&V History（D12 FSV 等级 + 教训引用）",
  "conclusion": "Conclusion（结论）",
}

#: G11 verdict → 八因素状态
_G11_STATUS: dict[str, str] = {
  "healthy": "PASS",
  "suspect": "WARN",
  "unhealthy": "FAIL",
}


def _factor_entry(
  name: str,
  status: str,
  detail: str,
  provenance: dict[str, Any],
  evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """构造单条八因素条目（JSON 友好；provenance 必填，字段 100% 可溯）。"""
  entry: dict[str, Any] = {
    "factor": name,
    "label": NASA_FACTOR_LABELS[name],
    "status": status,
    "detail": detail,
    "provenance": provenance,
  }
  if evidence:
    entry["evidence"] = evidence
  return entry


def _rollup_verdict(statuses: list[str]) -> str:
  """七因素状态 → 顶层结论（FAIL 支配；任一非 PASS → PARTIAL）。"""
  if "FAIL" in statuses:
    return "FAIL"
  if any(s != "PASS" for s in statuses):
    return "PARTIAL"
  return "CERTIFIED"


def _worst_gdm(entries: list[dict[str, Any]]) -> tuple[int, str | None]:
  """FSV 条目里最差 GDM 等级下标与短码（无有效条目 → (-1, None)）。"""
  from rfauto.core.fsv import GRADE_CODES, grade_index_of

  worst = -1
  for entry in entries:
    if entry.get("ok"):
      worst = max(worst, grade_index_of(float(entry["gdm_mean"])))
  return worst, (GRADE_CODES[worst] if worst >= 0 else None)


def _json_safe(value: Any) -> Any:
  """递归收敛为 JSON 原生类型（numpy 标量/数组 → python；不改数值）。"""
  import numpy as np

  if isinstance(value, dict):
    return {str(k): _json_safe(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_json_safe(v) for v in value]
  if isinstance(value, np.ndarray):
    return [_json_safe(v) for v in value.tolist()]
  if isinstance(value, np.bool_):
    return bool(value)
  if isinstance(value, np.integer):
    return int(value)
  if isinstance(value, np.floating):
    return float(value)
  return value


def _fsv_entries(
  fsv_pairs: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
  """D12：曲线对列表 → FSV 等级条目 + 失败原因（best-effort，逐条不传染）。"""
  from rfauto.service.calibration_service import fsv_curve_levels

  entries: list[dict[str, Any]] = []
  failures: list[str] = []
  for index, pair in enumerate(fsv_pairs or []):
    if not isinstance(pair, dict):
      failures.append(f"pair{index}: 非 dict，跳过")
      continue
    label = str(pair.get("label", f"pair{index + 1}"))
    computed = fsv_curve_levels(
      pair.get("freq_a"), pair.get("val_a"),
      pair.get("freq_b"), pair.get("val_b"),
      n_points=pair.get("n_points"),
      include_offset=bool(pair.get("include_offset", True)),
    )
    entry = {
      "label": label,
      "metric": pair.get("metric"),
      "provenance": dict(pair.get("provenance") or {}),
    }
    entry.update(computed)
    entries.append(entry)
    if not computed.get("ok"):
      failures.append(f"{label}: {computed.get('error')}")
  return entries, failures


def _koh_row(koh_interval: dict[str, Any] | None) -> tuple[bool, dict[str, Any] | None]:
  """D10：KOH predict 输出 → (是否有效区间, JSON 友好副本)。"""
  if not isinstance(koh_interval, dict):
    return False, None
  try:
    lo = float(koh_interval["lo95"])
    hi = float(koh_interval["hi95"])
    mean = float(koh_interval["mean"])
  except (KeyError, TypeError, ValueError):
    return False, None
  import math

  if not (math.isfinite(lo) and math.isfinite(hi) and math.isfinite(mean)):
    return False, None
  if lo > hi:
    return False, None
  return True, _json_safe(dict(koh_interval))


def certify_design_evidence(
  *,
  design: str,
  samples_path: str | Path | None = None,
  params_center: dict[str, float] | None = None,
  tolerance_pct: float = 0.02,
  n_grid: int = 9,
  kind: str = "poly_ridge",
  health: dict[str, Any] | None = None,
  fsv_pairs: list[dict[str, Any]] | None = None,
  koh_interval: dict[str, Any] | None = None,
  run_id: str | None = None,
  run_dir: str | Path | None = None,
  runs_dir: str | Path = "runs",
  extra_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  """产出 NASA-STD-7009 八因素「可认证设计」证据包（加性，JSON 安全）。

  参数
  ----
  design    : 设计名（仅标注，不参与判定）。
  samples_path : 公差盒证书样本集（certify_design 同款 schema）；缺省时
          证书类因素（鲁棒性等）如实标 UNKNOWN，不编造。
  params_center: 与 samples_path 配套的中心参数（提供 samples 时必填）。
  health    : G11 health_check_run 返回（九因子）；缺省 → UNKNOWN。
  fsv_pairs  : D12 曲线对列表，每条 {label, metric, freq_a, val_a, freq_b,
          val_b[, n_points, include_offset, provenance]}，逐条经
          service 层 fsv_curve_levels（core/fsv 唯一计算路径）。
  koh_interval : D10 KOHCalibrator.predict 输出（mean/lo95/hi95/...）；
          缺省或结构不合法 → 该证据不并入（UNKNOWN/WARN）。
  run_id/run_dir/runs_dir : runs/ 归档定位（meta.json 作 M&S History）。
  extra_inputs : 额外输入来源 [{label, path}]，逐条记 exists。

  返回顶层 ok=True 表示证据包成功组装（**不等于**设计通过）；设计结论见
  verdict（CERTIFIED/PARTIAL/FAIL）。致命输入错误（samples 不可读/缺
  params_center）→ ok=False + errors，不抛异常（#105）。缺源因素 → UNKNOWN。
  """
  errors: list[str] = []

  if samples_path is not None and params_center is None:
    return {
      "ok": False, "design": design, "standard": "NASA-STD-7009",
      "errors": ["提供 samples_path 时必须给 params_center"],
    }

  # ---- 证书（公差盒鲁棒性，唯一数值来源=既有确定性内核） ----
  certificate: dict[str, Any] | None = None
  if samples_path is not None:
    certificate = certify_design(
      samples_path, params_center,
      tolerance_pct=tolerance_pct, n_grid=n_grid, kind=kind,
    )
    if not certificate.get("ok"):
      return {
        "ok": False, "design": design, "standard": "NASA-STD-7009",
        "errors": list(certificate.get("errors") or ["证书计算失败"]),
        "design_certificate": certificate,
        "samples_path": str(samples_path),
      }

  # ---- 归档 meta（M&S History / 输入 provenance） ----
  meta: dict[str, Any] | None = None
  run_path: Path | None = None
  if run_dir is not None:
    run_path = Path(run_dir)
  elif run_id is not None:
    run_path = Path(runs_dir) / run_id
  if run_path is not None:
    meta_file = run_path / "meta.json"
    if meta_file.exists():
      try:
        loaded = json.loads(meta_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
          meta = loaded
      except Exception as exc: # best-effort（#105）
        errors.append(f"meta.json 解析失败: {meta_file}: {exc}")

  # ---- 样本集元信息（Data History） ----
  samples_meta: dict[str, Any] | None = None
  if certificate is not None and samples_path is not None:
    sample_path = Path(samples_path)
    try:
      data = json.loads(sample_path.read_text(encoding="utf-8"))
      samples_meta = {
        "path": str(sample_path),
        "n_samples": len(list(data.get("samples") or [])),
        "bounds": {str(k): [float(x) for x in v]
              for k, v in (data.get("bounds") or {}).items()},
        "objectives": list(data.get("objectives") or []),
      }
    except Exception as exc:
      errors.append(f"样本集元信息读取失败: {sample_path}: {exc}")

  # ---- 额外输入来源 ----
  extra_entries: list[dict[str, Any]] = []
  for item in extra_inputs or []:
    if not isinstance(item, dict):
      continue
    raw_path = item.get("path")
    entry: dict[str, Any] = {
      "label": str(item.get("label", "input")),
      "path": str(raw_path) if raw_path is not None else None,
    }
    if raw_path is not None:
      entry["exists"] = Path(raw_path).exists()
    extra_entries.append(entry)

  # ---- G11：九因子健康度 ----
  g11_factors: list[dict[str, Any]] = []
  if isinstance(health, dict):
    for item in health.get("factors") or []:
      if isinstance(item, dict):
        g11_factors.append({
          "factor": item.get("factor"),
          "status": item.get("status"),
          "lesson_ref": item.get("lesson_ref"),
          "detail": item.get("detail"),
        })
  if not isinstance(health, dict):
    f_vv = _factor_entry(
      "v_and_v", "UNKNOWN",
      "未提供 G11 health_check_run 结果——不臆断健康度（如实 unknown）",
      {"source": "G11 core/solve_health", "provided": False},
    )
  else:
    hverdict = str(health.get("verdict", ""))
    f_vv = _factor_entry(
      "v_and_v", _G11_STATUS.get(hverdict, "UNKNOWN"),
      f"G11 求解健康度 verdict={hverdict or 'unknown'}（九因子见 evidence）",
      {
        "source": "G11 core/solve_health（经 health_service.health_check_run）",
        "run_id": health.get("run_id", run_id),
        "run_dir": health.get("run_dir") or (str(run_path) if run_path else None),
      },
      {
        "health_verdict": hverdict,
        "g11_factors": g11_factors,
        "counts": {
          s: sum(1 for f in g11_factors if f.get("status") == s)
          for s in ("PASS", "WARN", "FAIL", "UNKNOWN")
        },
      },
    )

  # ---- 输入 pedigree ----
  ped_sources: list[dict[str, Any]] = []
  if samples_meta is not None:
    ped_sources.append({"kind": "samples", "path": samples_meta["path"],
              "exists": True})
  if run_path is not None:
    ped_sources.append({"kind": "run_meta", "path": str(run_path / "meta.json"),
              "exists": meta is not None})
  ped_sources.extend(extra_entries)
  n_present = sum(1 for s in ped_sources if s.get("exists"))
  f_ped = _factor_entry(
    "input_pedigree",
    "PASS" if n_present else "UNKNOWN",
    f"{len(ped_sources)} 个输入来源，存在 {n_present} 个"
    + ("" if n_present else "——输入 pedigree 未知"),
    {"source": "caller-supplied inputs + runs/ 归档", "inputs": ped_sources},
    {
      "params_center": {k: float(v) for k, v in (params_center or {}).items()},
      "tolerance_pct": float(tolerance_pct),
      "surrogate_kind": kind,
      "lipschitz_grid": int(n_grid),
    },
  )

  # ---- 不确定性表征（证书区间 + D10 KOH） ----
  cert_rows = list(certificate.get("certificates") or []) if certificate else []
  cert_rows = [c for c in cert_rows if isinstance(c, dict)]
  cert_with_interval = [c for c in cert_rows if "interval" in c]
  koh_valid, koh_row = _koh_row(koh_interval)
  if koh_interval is not None and not koh_valid:
    u_status = "WARN"
    u_detail = "KOH 区间结构不合法（缺 mean/lo95/hi95 或 lo95>hi95），未并入"
  elif certificate is None and not koh_valid:
    u_status = "UNKNOWN"
    u_detail = "无公差盒证书也无 KOH 偏差区间——不确定性未表征"
  elif certificate is not None and len(cert_with_interval) < len(cert_rows):
    u_status = "WARN"
    u_detail = "部分 objective 代理不产出指标/无区间——不确定性部分表征"
  else:
    u_status = "PASS"
    u_detail = (f"公差盒证书 {len(cert_with_interval)} 项区间"
          + (" + KOH 95% 区间" if koh_valid else ""))
  f_uq = _factor_entry(
    "uncertainty_characterization", u_status, u_detail,
    {
      "source": ("D10 service/koh_service.KOHCalibrator.predict + "
            "certify_design Lipschitz 保守界"),
      "koh_provenance": (koh_interval or {}).get("provenance")
      if isinstance(koh_interval, dict) else None,
    },
    {
      "certificate_intervals": [
        {"metric": c.get("metric"), "interval": c.get("interval"),
         "radius": c.get("radius"), "center_value": c.get("center_value")}
        for c in cert_with_interval
      ],
      "koh_provided": koh_interval is not None,
      "koh_interval": koh_row,
    },
  )

  # ---- 结果鲁棒性（证书 verdict 统计） ----
  if not cert_rows:
    r_status = "UNKNOWN"
    r_detail = "无公差盒证书（samples 缺省）——公差鲁棒性未评估"
  else:
    n_fail = sum(1 for c in cert_rows if c.get("verdict") == "FAIL")
    n_unknown = sum(1 for c in cert_rows if c.get("verdict") == "UNKNOWN")
    if n_fail:
      r_status, r_detail = "FAIL", f"{n_fail} 项 objective 违反 spec（公差内必然不合格）"
    elif n_unknown:
      r_status = "WARN"
      r_detail = f"{n_unknown} 项 objective 证据不足（区间横跨阈值/代理不产出）"
    else:
      r_status, r_detail = "PASS", "全部 objective 在公差盒内必然合格"
  f_rb = _factor_entry(
    "results_robustness", r_status, r_detail,
    {"source": "certify_design 公差盒证书（Lipschitz 保守界）",
     "samples_path": certificate.get("samples_path") if certificate else None},
    {
      "n_pass": certificate.get("n_pass") if certificate else None,
      "n_fail": certificate.get("n_fail") if certificate else None,
      "n_unknown": certificate.get("n_unknown") if certificate else None,
      "tolerance_pct": float(tolerance_pct),
      "certificate_verdict": certificate.get("verdict") if certificate else None,
      "certificates": [{"metric": c.get("metric"), "verdict": c.get("verdict")}
               for c in cert_rows],
    },
  )

  # ---- M&S 历史 ----
  meta_keys = ("run_id", "model", "adapter", "status", "study_name",
         "schema_version", "git_sha", "timestamp")
  if meta is not None:
    m_status = "PASS"
    meta_summary = {k: meta[k] for k in meta_keys if k in meta}
    m_detail = f"归档 meta.json 在读（run_id={meta.get('run_id', run_id)}）"
  else:
    m_status, meta_summary = "UNKNOWN", {}
    m_detail = "无 runs/<run_id>/meta.json 归档——M&S 历史未知"
  f_ms = _factor_entry(
    "ms_history", m_status, m_detail,
    {"source": str(run_path / "meta.json") if run_path is not None else None,
     "run_id": run_id, "run_dir": str(run_path) if run_path is not None else None},
    {"meta": meta_summary},
  )

  # ---- 数据历史 ----
  if samples_meta is not None:
    d_status = "PASS"
    d_detail = (f"样本集 {samples_meta['n_samples']} 点 / "
          f"{len(samples_meta['objectives'])} objective")
  elif any(e.get("exists") for e in extra_entries):
    d_status, d_detail = "PASS", "仅额外输入归档可用（无公差盒样本集）"
  else:
    d_status, d_detail = "UNKNOWN", "无样本集/额外数据归档——数据历史未知"
  f_data = _factor_entry(
    "data_history", d_status, d_detail,
    {"source": "samples_path + extra_inputs"},
    {"samples_meta": samples_meta, "extra_inputs": extra_entries},
  )

  # ---- V&V 历史（D12 FSV + G11 教训引用） ----
  fsv_entries, fsv_failures = _fsv_entries(fsv_pairs)
  worst_idx, worst_code = _worst_gdm(fsv_entries)
  if worst_idx < 0:
    v_status = "UNKNOWN"
    v_detail = "无有效 D12 曲线对——V&V 历史未知（不编造 grade）"
  elif worst_idx <= 2:
    v_status = "PASS"
    v_detail = f"最差 GDM={worst_code}（Ex/VG/G）"
  elif worst_idx == 3:
    v_status = "WARN"
    v_detail = f"最差 GDM={worst_code}（Fair）"
  else:
    v_status = "FAIL"
    v_detail = f"最差 GDM={worst_code}（Poor/Very Poor）"
  lessons = sorted({f.get("lesson_ref") for f in g11_factors if f.get("lesson_ref")})
  f_hist = _factor_entry(
    "vv_history", v_status, v_detail,
    {"source": "D12 core/fsv（经 calibration_service.fsv_curve_levels）",
     "fsv_pair_sources": [e.get("provenance") for e in fsv_entries]},
    {"fsv": fsv_entries, "fsv_errors": fsv_failures,
     "worst_gdm_grade": worst_code, "lessons": lessons},
  )

  # ---- 结论（确定性 roll-up） ----
  seven = [f_vv, f_ped, f_uq, f_rb, f_ms, f_data, f_hist]
  statuses = [str(f["status"]) for f in seven]
  verdict = _rollup_verdict(statuses)
  f_concl = _factor_entry(
    "conclusion",
    {"CERTIFIED": "PASS", "PARTIAL": "WARN", "FAIL": "FAIL"}[verdict],
    "七因素状态: " + ", ".join(
      f"{f['factor']}={f['status']}" for f in seven) + f" → {verdict}",
    {"source": "derived: deterministic roll-up of the seven factors",
     "rule": "FAIL 支配；任一非 PASS → PARTIAL；全 PASS → CERTIFIED"},
    {"verdict": verdict},
  )

  package: dict[str, Any] = {
    "ok": True,
    "design": design,
    "standard": "NASA-STD-7009",
    "verdict": verdict,
    "verdict_rule": "FAIL 支配；任一非 PASS → PARTIAL；全 PASS → CERTIFIED",
    "factors": [*seven, f_concl],
    "design_certificate": certificate,
    "sources": {
      "samples_path": str(samples_path) if samples_path is not None else None,
      "run_id": run_id,
      "run_dir": str(run_path) if run_path is not None else None,
      "runs_dir": str(runs_dir),
      "extra_inputs": extra_entries,
    },
    "note": ("证据包只搬运 G11/D12/D10 与 certify_design 已有确定性结果；"
         "缺源因素如实 UNKNOWN，不生成新物理数字"),
  }
  if errors:
    package["errors"] = errors
  return _json_safe(package)

