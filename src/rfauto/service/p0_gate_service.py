"""p0_gate_service：跨保真 gate 资产复用通道（阶段 1.1 降耗件）。

背景：1.1 原生 p0 --high-adapter openems 需 15 点 × ~20min 真机重解。
0.2 校准战役（augment_calibration）已产出同配方、同 mesh、同 SpecEvaluator
口径的 openEMS 真采样资产（25 点，runs/<rid>/calibration/samples.json）。
openEMS FDTD 确定性（同脚本哈希逐位复现），重解只会得到相同数字——
直接复用资产即严格等价（n=25 还大于计划 15，统计功效更高），零真机开销。

等价性边界（如实记录，不夸大）：
- 高保真臂：资产的 metrics 就是 p0 高保真臂会算出的同一批数（同求解器、
 同参数、同 mesh、同频段、同指标口径），cost 重算即可；
- 低保真臂：fake 通道确定性但依赖调用路径——本服务镜像 p0 原生 fake
 路径（_create_adapter + plugin.build + solve），与历史 p0 数字可比；
- gate 数学：Spearman ρ 与 top5/top8 recall 直接复用
 scripts/p0_experiment.py 的函数（importlib 加载，杜绝第二实现漂移）；
- 差异点：采样设计不同（p0=均匀随机 seed，本服务=campaign 的
 Taguchi+LHS 点集）——跨保真 gate 的定义只要求"同参数点双通道配对"，
 不约束点集来源；provenance 里如实记录资产来源。
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

_RHO_THRESHOLD = 0.8
_RECALL_THRESHOLD = 0.8


def _load_p0_module():
  """加载 scripts/p0_experiment.py（复用其排序一致性数学，同源实现）。"""
  script = (Path(__file__).resolve().parent.parent.parent.parent
       / "scripts" / "p0_experiment.py")
  if not script.exists():
    raise FileNotFoundError(f"p0 脚本不存在: {script}")
  spec = importlib.util.spec_from_file_location("p0_experiment", str(script))
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


def _default_fake_cost_fn(recipe_path: Path, params: dict[str, float]) -> float:
  """p0 原生 fake 通道镜像（_create_adapter + plugin.build + solve）。

  与 scripts/p0_experiment.py::_evaluate_fake 逐行同构——fake 排序必须
  与历史 p0 数字可比，不允许换调用路径。
  """
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.models.registry import get as get_plugin
  from rfauto.optimization.optimizer import _create_adapter

  with open(recipe_path, encoding="utf-8") as f:
    recipe = yaml.safe_load(f) or {}
  objectives = [Objective(**o) for o in recipe.get("objectives", [])]
  plugin_cls = get_plugin(str(recipe.get("model", "")))
  adapter, _ver = _create_adapter("fake", None, recipe)
  if adapter is None:
    raise RuntimeError("fake adapter 不可用")
  try:
    plugin = plugin_cls()
    plugin.build(adapter, plugin.params_model(**params))
    report = adapter.solve("main_setup")
    if not report.success:
      raise RuntimeError(f"fake solve 失败: {report.message}")
    network = adapter.get_sparams()
    metrics = SpecEvaluator.compute_metrics(network, objectives)
    return float(SpecEvaluator.evaluate_objectives(metrics, objectives))
  finally:
    adapter.close()


def _fsv_cost_levels(
  low_costs: list[float],
  high_costs: list[float],
) -> dict[str, Any]:
  """两通道 cost 序列的曲线级 FSV 等级（⑥，additive，JSON 安全）。

  横轴 = 配对点序号（同一样本集的双通道 cost 剖面，确定性）。配对点
  < core.fsv.MIN_POINTS 时 best-effort 记不可用（此时等级门降级，
  verdict 回 ρ/recall 单点口径）。曲线级等级由
  calibration_service.fsv_curve_levels 统一计算（杜绝第二实现）。
  """
  from rfauto.core.fsv import MIN_POINTS
  from rfauto.service.calibration_service import fsv_curve_levels

  n = min(len(low_costs), len(high_costs))
  if n < MIN_POINTS:
    return {"ok": False,
        "error": (f"配对点 {n} < MIN_POINTS={MIN_POINTS}，"
             "曲线级 FSV 不可用（排序/recall 判定不受影响）"),
        "n_points": n, "min_points": MIN_POINTS}
  x = [float(i) for i in range(n)]
  level = fsv_curve_levels(
    x, [float(c) for c in low_costs[:n]],
    x, [float(c) for c in high_costs[:n]])
  return level | {
    "x_axis": "配对点序号（同一样本集双通道 cost 剖面）",
    "n_points": n,
    "channels": ["low_fidelity_cost", "high_fidelity_cost"],
  }


def cross_gate_from_asset(
  recipe_path: str | Path,
  samples_path: str | Path,
  *,
  fake_cost_fn: Callable[[Path, dict[str, float]], float] | None = None,
  rho_threshold: float = _RHO_THRESHOLD,
  recall_threshold: float = _RECALL_THRESHOLD,
  fsv_grade_threshold: str | None = None,
) -> dict[str, Any]:
  """0.2 资产复用的跨保真 gate（1.1 验收，JSON 契约）。

  fake_cost_fn 可注入（单测）；缺省用 p0 镜像路径。返回
  {ok, gate, verdict, spearman_rho, top5_recall, n_evaluated, fsv,
   fsv_gate, provenance}。
  verdict=PASS 需同时满足 ρ≥阈值、recall≥阈值 且 FSV 等级门不否决
  （收口：曲线级 GDM 评级并入 verdict——排序一致但数值剖面
  畸变的配对（ρ/recall 失明）由等级门拦下）；fsv_grade_threshold=None
  取 calibration_service.FSV_GRADE_THRESHOLD（默认 Fair，单一真源）；
  例外 1：n<8 时 top5/top8 recall 恒 1（无效统计量），置 None 并只按
  ρ 门与 FSV 门判定，verdict_reason 注明"样本 <8 recall 无效"；
  例外 2（降级路径）：配对点 < core.fsv.MIN_POINTS 等 FSV 不可用情形
  时等级门降级（fsv_gate.pass=None），verdict 回既有单点口径，verdict_
  reason 注明——禁止因 FSV 缺席而 FAIL。
  """
  import yaml

  from rfauto.core.objectives import Objective, SpecEvaluator

  recipe = Path(recipe_path)
  asset = Path(samples_path)
  if not recipe.exists():
    return {"ok": False, "errors": [f"配方不存在: {recipe}"]}
  if not asset.exists():
    return {"ok": False, "errors": [f"样本资产不存在: {asset}"]}
  with open(recipe, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f) or {}
  data = json.loads(asset.read_text(encoding="utf-8"))
  asset_objectives = data.get("objectives") or []
  recipe_objectives = recipe_data.get("objectives") or []
  if asset_objectives != recipe_objectives:
    return {"ok": False, "errors": [
      "资产 objectives 与配方不一致——跨通道 cost 口径必须同源"]}
  samples = list(data.get("samples") or [])
  if len(samples) < 5:
    return {"ok": False, "errors": [f"资产样本不足（{len(samples)} < 5）"]}

  objectives = [Objective(**o) for o in recipe_objectives]

  # 高保真臂：资产 metrics 重算 cost（零求解）
  high_costs: list[float] = []
  points: list[dict[str, float]] = []
  for s in samples:
    metrics = s.get("metrics") or {}
    try:
      high_costs.append(
        float(SpecEvaluator.evaluate_objectives(metrics, objectives)))
      points.append({k: float(v) for k, v in s["params"].items()})
    except Exception:
      continue # 单点失败不阻塞（与 p0 容错语义一致）
  if len(high_costs) < 5:
    return {"ok": False, "errors": ["有效高保真点不足（<5）"]}

  # 低保真臂：p0 镜像 fake 路径逐点求 cost
  fn = fake_cost_fn or _default_fake_cost_fn
  low_costs: list[float] = []
  valid: list[dict[str, Any]] = []
  failures: list[dict[str, Any]] = []
  for pt, ch in zip(points, high_costs, strict=True):
    try:
      cl = float(fn(recipe, pt))
    except Exception as exc:
      failures.append({"params": pt, "error": str(exc)})
      continue
    low_costs.append(cl)
    valid.append({"params": pt, "cost_low": cl, "cost_high": ch})
  if len(low_costs) < 5:
    return {"ok": False, "errors": ["有效配对点不足（<5）"],
        "failures": failures}

  # gate 数学：与 p0 同源函数
  p0 = _load_p0_module()
  rho = p0._spearman_rank_corr(low_costs, high_costs)
  n_eval = len(low_costs)
  reasons: list[str] = []
  if n_eval < 8:
    # n<8 时 high_top8=全集、low_top5⊆全集 → recall 恒 1（与 #195
    # "窄带 max 恒定"同族的统计量退化陷阱）——置 None 并在 verdict
    # 理由注明，ρ 门保持不变
    recall = None
    reasons.append(f"样本 {n_eval} < 8，top5/top8 recall 无效"
            "（恒 1），本次仅按 ρ 门判定")
  else:
    low_order = sorted(range(n_eval), key=lambda i: low_costs[i])
    high_order = sorted(range(n_eval), key=lambda i: high_costs[i])
    low_top5 = set(low_order[:5])
    high_top8 = set(high_order[:8])
    recall = len(low_top5 & high_top8) / max(len(low_top5), 1)

  # FSV 等级门（收口）：曲线级 GDM 评级并入 verdict；
  # 不可用即降级（pass=None），verdict 回既有单点口径
  from rfauto.service.calibration_service import FSV_GRADE_THRESHOLD, fsv_grade_gate
  fsv_section = _fsv_cost_levels(low_costs, high_costs)
  fsv_gate = fsv_grade_gate(
    fsv_section,
    threshold=fsv_grade_threshold or FSV_GRADE_THRESHOLD)
  base_pass = (rho is not None and rho >= rho_threshold
         and (recall is None or recall >= recall_threshold))
  verdict = "PASS" if base_pass and fsv_gate["pass"] is not False else "FAIL"
  if fsv_gate["degraded"]:
    reasons.append(f"FSV 等级门降级（{fsv_gate['reason']}），"
            "verdict 按既有 ρ/recall 单点口径")
  elif fsv_gate["pass"] is False:
    reasons.append(f"FSV 等级门否决：{fsv_gate['reason']}")
  result: dict[str, Any] = {
    "ok": True,
    "gate": "cross_fidelity_asset_reuse",
    "verdict": verdict,
    "spearman_rho": rho,
    "top5_recall": recall,
    "rho_threshold": rho_threshold,
    "recall_threshold": recall_threshold,
    "n_evaluated": len(low_costs),
    "n_failures": len(failures),
    "provenance": {
      "recipe": str(recipe),
      "asset_samples": str(asset),
      "high_channel": "openEMS 真采样资产复用（0.2 战役，FDTD 确定性等价）",
      "low_channel": "fake 镜像 p0 _evaluate_fake 路径（plugin.build）",
      "gate_math": "scripts/p0_experiment.py::_spearman_rank_corr（同源）",
      "sampling_design": "campaign Taguchi(9)+LHS(16) 点集（非 p0 均匀随机）",
    },
    # D12 FSV 曲线级等级（⑥）：等级经 fsv_grade_gate 并入 verdict
    "fsv": fsv_section,
    "fsv_gate": fsv_gate,
    "samples": valid[:10],
  }
  if reasons:
    result["verdict_reason"] = "；".join(reasons)
  if failures:
    result["failures"] = failures[:10]
  return result


def _fsv_line(section: Any) -> str:
  """把 FSV 段渲染成报告一行（best-effort；不可用即写原因，不抛）。"""
  if not isinstance(section, dict):
    return "未计算"
  if not section.get("ok"):
    return f"不可用（{section.get('error', '无曲线')}）"
  return (f"ADM={section.get('adm_grade')} / FDM={section.get('fdm_grade')}"
      f" / GDM={section.get('gdm_grade')}"
      f"（均值 {section.get('gdm_mean')}，n={section.get('n_points')}）")


def _fsv_gate_line(gate: Any) -> str:
  """把 FSV 等级门渲染成报告一行（best-effort，不抛）。"""
  if not isinstance(gate, dict):
    return "未计算"
  grade = gate.get("grade")
  if gate.get("degraded") or grade is None:
    return f"降级（{gate.get('reason', '等级门不参与')}）"
  return (f"{'PASS' if gate.get('pass') else 'FAIL'}"
      f"（GDM {grade} vs 门限 {gate.get('threshold')}）")


def emit_gate_artifact(recipe_path: str | Path,
            samples_path: str | Path) -> dict[str, Any]:
  """计算 gate 并落 run 产物（gate.json/report.md/meta.json，v1 收官归档）。"""
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta

  result = cross_gate_from_asset(recipe_path, samples_path)
  if not result.get("ok"):
    return result
  run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  (run_dir / "gate.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1, default=str),
    encoding="utf-8")
  lines = [
    "# P0 跨保真 gate（资产复用通道，阶段 1.1）",
    "",
    f"- verdict：**{result['verdict']}**"
    f"（ρ={result['spearman_rho']:.3f} / recall={result['top5_recall']:.2f}，"
    f"阈值 ρ≥{result['rho_threshold']} & recall≥{result['recall_threshold']}"
    f" + FSV 等级门{'（降级不参与）' if (result.get('fsv_gate') or {}).get('degraded') else ''}）",
    f"- 配对点：{result['n_evaluated']}（来自 0.2 战役资产，零重解）",
    f"- D12 曲线级 FSV：{_fsv_line(result.get('fsv'))}",
    f"- D12 FSV 等级门：{_fsv_gate_line(result.get('fsv_gate'))}",
    f"- 来源：{result['provenance']['asset_samples']}",
    "",
    "原生 p0 重跑命令（如需全流程 provenance）：",
    "`set RFAUTO_OPENEMS_MESH=0.45&& rfauto p0 recipes/wilkinson_pd_v1.yaml "
    "--high-adapter openems --cross-samples 15`",
    "",
  ]
  (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
  _gate = result.get("fsv_gate") or {}
  write_meta(run_dir, {
    "run_id": run_id, "model": "p0_cross_gate", "status": "done",
    "adapter": "p0_gate:asset_reuse",
    "algorithm": "cross_fidelity_gate_from_asset",
    "metrics": {"verdict": result["verdict"],
          "rho": result["spearman_rho"],
          "top5_recall": result["top5_recall"],
          "n_evaluated": result["n_evaluated"],
          "fsv_gdm_grade": (result.get("fsv") or {}).get("gdm_grade"),
          "fsv_gate": {"grade": _gate.get("grade"),
                 "pass": _gate.get("pass"),
                 "degraded": _gate.get("degraded")}}})
  return result | {"run_id": run_id, "run_dir": str(run_dir),
           "elapsed_note": "资产复用通道：无真机求解"}
