"""人工核验 UI 服务层（rfauto ui 后端）。

原则（分层纪律）：服务层 JSON 进出；cli/mcp 是薄壳；写操作只经
本模块落盘（配方保存走 validate_recipe 校验 + 单写锁由 run 链路负责）。

页面数据：
- list_runs / run_detail：runs 产物索引与单次 run 全量中间产物
- recipe_view / recipe_save：配方的表单化读改（人不需要写 YAML）
- model3d_for_recipe：3D 预览几何 spec（毫米）
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

RUNS_DIR = Path("runs")


def list_runs(limit: int = 50) -> dict[str, Any]:
  """run 列表（UI 首页）。"""
  from rfauto.infra.run_store import list_runs as _list_runs

  runs = _list_runs(RUNS_DIR / "index.db", limit=limit)
  return {"ok": True, "runs": runs}


def run_detail(run_id: str) -> dict[str, Any]:
  """单次 run 的全部中间产物（人工核验主页面数据）。

  聚合：metrics、S 参数曲线数据（解析 Touchstone）、产物文件清单、
  配方快照、报告路径。
  """
  run_dir = RUNS_DIR / run_id
  if not run_dir.is_dir():
    return {"ok": False, "errors": [f"run 不存在: {run_id}"]}

  detail: dict[str, Any] = {"ok": True, "run_id": run_id, "run_dir": str(run_dir)}

  # 产物清单（相对路径 + 大小）
  files = [
    {"path": str(p.relative_to(run_dir)).replace("\\", "/"),
     "size_bytes": p.stat().st_size}
    for p in sorted(run_dir.rglob("*")) if p.is_file()
  ]
  detail["files"] = files

  # 指标
  metrics_path = run_dir / "results" / "metrics.json"
  if metrics_path.exists():
    detail["metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))

  # S 参数曲线数据（|S| dB，供前端 canvas 画图）
  curves = []
  try:
    import numpy as np

    from rfauto.measurement.import_data import import_touchstone

    for sp in sorted((run_dir / "results").glob("*.s2p")) + sorted(
      (run_dir / "results").glob("*.s3p")
    ):
      data = import_touchstone(sp)
      s = data.s
      n_ports = s.shape[1]
      for m in range(n_ports):
        for n in range(n_ports):
          name = f"S{m + 1}{n + 1}"
          curves.append({
            "file": sp.name,
            "name": name,
            "freq_ghz": [round(float(f), 6) for f in data.freq_ghz],
            "db": [round(float(20 * np.log10(abs(s[i, m, n]) + 1e-12)), 4)
                for i in range(s.shape[0])],
          })
  except Exception as e: # 无 Touchstone/解析失败不阻塞页面
    detail["sparams_warning"] = str(e)
  detail["sparams"] = curves

  # 配方快照（文本，前端展示/下载）
  snap = run_dir / "recipe.snapshot.yaml"
  if snap.exists():
    detail["recipe_snapshot"] = snap.read_text(encoding="utf-8")

  # 报告与 3D 预览
  for key, rel in (("report_md", "report.md"), ("model3d_html", "model_3d.html")):
    p = run_dir / rel
    if p.exists():
      detail[key] = str(p).replace("\\", "/")

  # fake 通道无 Touchstone 时前端回退显示曲线 PNG
  detail["figs"] = [
    "runs/" + run_id + "/" + str(p.relative_to(run_dir)).replace("\\", "/")
    for p in sorted((run_dir / "results" / "figs").glob("*.png"))
  ]

  # 3D spec 由服务端从快照解析（前端不做 YAML 解析）
  detail["model3d"] = _model3d_from_snapshot(run_dir)
  return detail


def _model3d_from_snapshot(run_dir: Path) -> dict[str, Any] | None:
  """从配方快照解析 3D 几何 spec；模板不支持/解析失败返回 None。"""
  import yaml

  snap = run_dir / "recipe.snapshot.yaml"
  if not snap.exists():
    return None
  try:
    with open(snap, encoding="utf-8") as f:
      data = yaml.safe_load(f) or {}
    template = _template_hint(data)
    if template is None:
      return None
    params = {}
    for name, spec in (data.get("params") or {}).items():
      params[name] = spec.get("value") if isinstance(spec, dict) else spec
    from rfauto.adapters.openems_templates import geometry_spec

    return dict(geometry_spec(template, params), ok=True)
  except Exception:
    return None


def recipe_view(recipe_path: str | Path) -> dict[str, Any]:
  """配方的表单化视图（人不需要写 YAML）。

  params 展开 {name: {value, unit, bounds}}，optimization/setup/objectives
  原样结构化返回。
  """
  import yaml

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方不存在: {recipe_path}"]}
  with open(path, encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

  params = []
  for name, spec in (data.get("params") or {}).items():
    if isinstance(spec, dict):
      params.append({
        "name": name,
        "value": spec.get("value"),
        "unit": spec.get("unit", ""),
        "bounds": spec.get("bounds"),
      })
    else:
      params.append({"name": name, "value": spec, "unit": "", "bounds": None})

  opt = data.get("optimization") or {}
  return {
    "ok": True,
    "recipe_path": str(path).replace("\\", "/"),
    "model": data.get("model", ""),
    "template_hint": _template_hint(data),
    "params": params,
    "setup": data.get("setup") or {},
    "objectives": data.get("objectives") or [],
    "optimization": {
      "n_trials": opt.get("n_trials"),
      "sampler": opt.get("sampler", "tpe"),
      "params": {
        k: {"low": v.get("low"), "high": v.get("high")}
        for k, v in (opt.get("params") or {}).items()
      },
    },
  }


def recipe_save(
  recipe_path: str | Path,
  updates: dict[str, Any],
) -> dict[str, Any]:
  """把表单改动写回配方（先校验后落盘）。

  updates 允许的键：params（{name: value} 平铺，逐项带 bounds 校验）、
  setup、objectives、optimization（整段替换）。

  写面守卫（配方污染根修）：整文档 ``yaml.safe_dump`` 会丢注释/
  引号并把表单归一化的 optimization 段整段写回——UI「保存并运行」正是经此链把
  recipes/branchline_coupler_v1.yaml 重序列化（diff 85 行）。recipes/ 原件
  一律不再原地覆盖：落 ``runs/recipe_workcopy/<同名>`` 工作副本并在返回的
  ``recipe_path`` 给出实际路径（``workcopy=True``），UI 后续「运行」应消费
  该路径；非受保护路径（tmp/沙箱/用户自定目录）行为不变。

  np 标量收敛（R3-C-02，c9920eb 复现）：落盘 payload 先经
  :func:`rfauto.infra.recipe_guard.sanitize_numpy_scalars` 递归转原生类型
  （与 :func:`write_recipe_yaml` 同一出口口径），综合内核 np.float64 透传
  不再抛 ``RepresenterError``。
  """
  import yaml

  from rfauto.infra.recipe_guard import (
    resolve_recipe_write_target,
    sanitize_numpy_scalars,
  )

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方不存在: {recipe_path}"]}
  with open(path, encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

  unknown = set(updates) - {"params", "setup", "objectives", "optimization"}
  if unknown:
    return {"ok": False, "errors": [f"不允许修改的字段: {sorted(unknown)}"]}

  if "params" in updates:
    current = data.get("params") or {}
    for name, value in updates["params"].items():
      if name not in current:
        return {"ok": False, "errors": [f"未知参数: {name}"]}
      if isinstance(current[name], dict):
        current[name]["value"] = value
      else:
        current[name] = value
    data["params"] = current
  for key in ("setup", "objectives", "optimization"):
    if key in updates:
      data[key] = updates[key]

  # 落盘前先过一遍校验器（落临时文件校验，避免半成品写回）。
  # 目标经守卫决策：recipes/ 原件 → 工作副本；临时文件与目标同目录以保原子替换。
  # payload 先套 sanitize_numpy_scalars（与 write_recipe_yaml 同一出口口径）：
  # UI/前端透传的综合内核 np 标量（np.float64 等）直接 yaml.safe_dump 会抛
  # RepresenterError（c9920eb 复现），根修在写出前递归转原生类型。
  target = resolve_recipe_write_target(path, redirect=True)
  target.parent.mkdir(parents=True, exist_ok=True)
  tmp = target.with_suffix(".yaml.ui-tmp")
  tmp.write_text(
    yaml.safe_dump(sanitize_numpy_scalars(data), allow_unicode=True,
            sort_keys=False),
    encoding="utf-8")
  from rfauto.service.api import validate_recipe

  try:
    validation = validate_recipe(tmp)
  except Exception as e:
    tmp.unlink(missing_ok=True)
    return {"ok": False, "errors": [str(e)]}
  if not validation["ok"]:
    tmp.unlink(missing_ok=True)
    return {"ok": False, "errors": validation["errors"],
        "warnings": validation.get("warnings", [])}
  tmp.replace(target)
  redirected = target != path
  out: dict[str, Any] = {
    "ok": True,
    "recipe_path": str(target).replace("\\", "/"),
    "source_recipe": str(path).replace("\\", "/"),
    "workcopy": redirected,
  }
  if redirected:
    out["message"] = (f"recipes/ 原件受保护未改动，已另存工作副本 {out['recipe_path']}"
             "（运行/调参请用该副本；入库请人工审阅后提交）")
  return out


def recipe_create(
  recipe_path: str | Path,
  data: dict[str, Any],
) -> dict[str, Any]:
  """新建配方（工程导入向导用）：整体写入 YAML。

  与 recipe_save 同属 UI 写面；YAML 序列化与落盘在 service，UI 层只传
  路径 + 结构化 payload（#90/#92）。新建语义为整体覆盖写入。

  写面守卫：路径由用户在向导中显式键入（explicit 入口），允许在 recipes/
  下**新建**；但"新建"不得覆盖 recipes/ 既有原件——同名已存在即拒绝。
  """
  from rfauto.infra.recipe_guard import is_protected_recipe_path, write_recipe_yaml

  path = Path(recipe_path) # PathLike/字符串统一收敛（#140）
  if not path.name:
    return {"ok": False, "errors": ["缺少配方路径"]}
  if path.exists() and is_protected_recipe_path(path):
    return {"ok": False, "errors": [
      f"recipes/ 原件受保护，新建不可覆盖既有配方: {path}（请换名，或另存 runs/ 下）"]}
  written = write_recipe_yaml(path, data, explicit=True)
  return {"ok": True, "path": str(written)}


def tune_trials(
  run_id: str | None = None, limit: int = 500
) -> dict[str, Any]:
  """优化调参的 trial 级数据（UI 实时监控）。

  数据源是 optimizer 每 trial 落盘的 runs/<run_id>/trials/trial_<n>.json。
  run_id 缺省时取最近有 trials/ 目录的 run（本地单用户 UI 的"当前任务"语义）。
  """
  if run_id:
    run_dir = RUNS_DIR / run_id
  else:
    candidates = [
      p for p in RUNS_DIR.glob("*/trials") if p.is_dir()
    ]
    if not candidates:
      return {"ok": True, "run_id": None, "trials": []}
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    run_dir = newest.parent
  trials_dir = run_dir / "trials"
  if not trials_dir.is_dir():
    return {"ok": True, "run_id": run_dir.name, "trials": []}
  trials = []
  for p in sorted(trials_dir.glob("trial_*.json")):
    try:
      data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
      continue # 单个 trial 损坏不阻塞整表（写入方是原子性较好的小文件）
    trials.append(data)
  return {
    "ok": True,
    "run_id": run_dir.name,
    "trials": trials[-limit:],
  }


def sandbox_drafts() -> dict[str, Any]:
  """Agent 配方沙箱草稿列表（含与真实配方的匹配 + 参数差异摘要）。"""
  from rfauto.service.agent_sandbox import RecipeSandbox

  sandbox = RecipeSandbox()
  drafts = sandbox.list_drafts().get("drafts", [])
  # 反查草稿来源：对 recipes/ 下每个配方重算确定性草稿名（stem+路径哈希）
  known: dict[str, str] = {}
  for recipe in sorted(Path("recipes").rglob("*.yaml")):
    try:
      known[str(sandbox.draft_path(recipe))] = str(recipe).replace("\\", "/")
    except Exception:
      continue
  items = []
  for draft in drafts:
    recipe = known.get(draft)
    item: dict[str, Any] = {"draft": draft, "recipe": recipe}
    if recipe:
      try:
        d = sandbox.diff(recipe)
        if d.get("ok"):
          item["params_changed"] = d["params_changed"]
          item["has_text_diff"] = bool(d.get("unified_diff"))
      except Exception as e:
        item["diff_error"] = str(e)
    items.append(item)
  return {"ok": True, "drafts": items}


def sandbox_diff(recipe_path: str | Path) -> dict[str, Any]:
  """单个沙箱草稿与真实配方的 diff（unified diff + 参数差异表）。"""
  from rfauto.service.agent_sandbox import RecipeSandbox, SandboxViolation

  try:
    return RecipeSandbox().diff(recipe_path)
  except SandboxViolation as e:
    return {"ok": False, "error": str(e)}


def sandbox_promote(
  recipe_path: str | Path, adapter_name: str = "fake"
) -> dict[str, Any]:
  """草稿差异送三层 Gate（生成提案进收件箱，等人工批准才生效）。"""
  from rfauto.service.agent_sandbox import RecipeSandbox, SandboxViolation

  try:
    return RecipeSandbox().promote(recipe_path, adapter_name=adapter_name)
  except SandboxViolation as e:
    return {"ok": False, "error": str(e)}


def model3d_for_recipe(recipe_path: str | Path) -> dict[str, Any]:
  """配方的 3D 几何 spec（毫米；前端 three.js 渲染）。"""
  view = recipe_view(recipe_path)
  if not view["ok"]:
    return view
  from rfauto.adapters.openems_templates import geometry_spec

  template = view["template_hint"]
  if template is None:
    return {"ok": False,
        "errors": ["配方模型无 3D 模板映射（仅 wilkinson/branchline/patch 支持）"]}
  params = {p["name"]: p["value"] for p in view["params"]}
  # 模板参数名归一（arm_len_mm 等与配方同名；unit 忽略）
  spec = geometry_spec(template, params)
  spec["ok"] = True
  spec["recipe_path"] = view["recipe_path"]
  return spec


def model3d_for_params(
  template: str,
  params: dict[str, Any] | None = None,
  substrate: Any = None,
) -> dict[str, Any]:
  """按模板 + 参数直接计算 3D 几何 spec（无配方文件；前端滑条实时预览）。

  几何计算是确定性内核（adapters/openems_templates.geometry_spec），
  UI 层只传模板名与参数字典（#90/#92）。
  """
  from rfauto.adapters.openems_templates import geometry_spec

  return dict(geometry_spec(template, params or {}, substrate), ok=True)


def _template_hint(recipe_data: dict[str, Any]) -> str | None:
  """配方 model 名 → 3D 模板名。"""
  model = str(recipe_data.get("model", ""))
  if "wilkinson" in model:
    return "wilkinson"
  if "branchline" in model:
    return "branchline"
  if "patch" in model:
    return "patch"
  if "mline" in model:
    return "mline"
  if "cpw" in model:
    return "cpw"
  return None


# ─── 校准工作台（阶段 3.2）与跨保真对比（3.3）数据源 ────────────────────────

def calibration_runs() -> dict[str, Any]:
  """扫描 runs/ 下的校准产物清单（工作台首页列表）。"""
  entries = []
  for run in sorted(RUNS_DIR.iterdir(), reverse=True):
    gate_p = run / "calibration" / "gate.json"
    if not run.is_dir() or not gate_p.exists():
      continue
    try:
      gate = json.loads(gate_p.read_text(encoding="utf-8"))
    except Exception:
      continue
    model = adapter = None
    meta_p = run / "meta.json"
    if meta_p.exists():
      try:
        m = json.loads(meta_p.read_text(encoding="utf-8"))
        model, adapter = m.get("model"), m.get("adapter")
      except Exception:
        pass
    loocv = gate.get("loocv") or {}
    entries.append({
      "run_id": run.name, "model": model, "adapter": adapter,
      "verdict": gate.get("verdict"), "rho": loocv.get("rho"),
      "n_samples": gate.get("n_samples"),
      "n_failures": gate.get("n_failures"),
      "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
      "surrogate_kind": gate.get("surrogate_kind"),
    })
  return {"ok": True, "runs": entries}


def calibration_view(run_id: str) -> dict[str, Any]:
  """单次校准详情：gate + 样本点（cost 着色）+ 验证点 + 报告文本。"""
  from rfauto.core.objectives import Objective, SpecEvaluator

  calib = RUNS_DIR / run_id / "calibration"
  if not calib.exists():
    return {"ok": False, "errors": [f"该 run 无校准产物: {run_id}"]}

  def _load_json(name: str) -> dict[str, Any] | None:
    p = calib / name
    if not p.exists():
      return None
    try:
      return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
      return None

  gate = _load_json("gate.json") or {}
  samples_doc = _load_json("samples.json") or {}
  report_p = calib / "report.md"
  report_md = (report_p.read_text(encoding="utf-8")
         if report_p.exists() else None)

  objectives = [Objective(**o)
         for o in (samples_doc.get("objectives") or [])]
  points = []
  for s in samples_doc.get("samples") or []:
    row = {k: float(v) for k, v in (s.get("params") or {}).items()}
    try:
      row["cost"] = float(SpecEvaluator.evaluate_objectives(
        s.get("metrics") or {}, objectives))
    except Exception:
      row["cost"] = None
    points.append(row)
  return {
    "ok": True, "run_id": run_id, "gate": gate,
    "bounds": samples_doc.get("bounds") or {},
    "objectives": samples_doc.get("objectives") or [],
    "points": points,
    "seed_sample_count": samples_doc.get("seed_sample_count"),
    "augmented_from": samples_doc.get("augmented_from"),
    "mesh_resolution_mm": samples_doc.get("mesh_resolution_mm"),
    "validation": samples_doc.get("validation") or [],
    "report_md": report_md,
  }


def cross_fidelity_view() -> dict[str, Any]:
  """跨保真对比数据（3.3）：ρ/recall 随样本量与网格档的演化曲线。"""
  import glob

  surrogate_evolution = []
  cross_evolution = []
  for run in sorted(RUNS_DIR.iterdir()):
    if not run.is_dir():
      continue
    gate_p = run / "calibration" / "gate.json"
    if gate_p.exists():
      try:
        gate = json.loads(gate_p.read_text(encoding="utf-8"))
        loocv = gate.get("loocv") or {}
        surrogate_evolution.append({
          "run_id": run.name, "rho": loocv.get("rho"),
          "n_samples": gate.get("n_samples"),
          "mesh_resolution_mm": gate.get("mesh_resolution_mm"),
          "verdict": gate.get("verdict"),
          "surrogate_kind": gate.get("surrogate_kind"),
        })
      except Exception:
        pass
    meta_p = run / "meta.json"
    if meta_p.exists():
      try:
        m = json.loads(meta_p.read_text(encoding="utf-8"))
      except Exception:
        m = {}
      if m.get("algorithm") == "cross_fidelity_gate_from_asset":
        metrics = m.get("metrics") or {}
        cross_evolution.append({
          "run_id": run.name,
          "algorithm": m.get("algorithm"),
          "rho": metrics.get("rho"),
          "top5_recall": metrics.get("top5_recall"),
          "n_evaluated": metrics.get("n_evaluated"),
          "verdict": metrics.get("verdict"),
        })
  for p in sorted(glob.glob(str(RUNS_DIR / "p0_*result.json"))):
    try:
      d = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
      continue
    cross_evolution.append({
      "run_id": Path(p).stem, "algorithm": "p0_native",
      "rho": d.get("spearman_rho"),
      "top5_recall": d.get("top5_recall"),
      "n_evaluated": d.get("n_evaluated"),
      "verdict": ("PASS" if (d.get("spearman_rho") or -1) >= 0.8
            else "FAIL"),
    })
  return {"ok": True, "surrogate_evolution": surrogate_evolution,
      "cross_evolution": cross_evolution}


# ─── S 参数交互视图（3.1）/ 成本时间线（3.4）/ 报告中心（3.5）数据源 ────────

def sparams_series(
  run_id: str, mode: str = "db"
) -> dict[str, Any]:
  """单次 run 的 S 参数交互序列（3.1）。

  mode="db" 返回 |S| dB；mode="deg" 返回沿频率轴解缠绕的相位（度）。
  曲线按 S 行列全对输出，前端只渲染（图例开关/缩放/悬停读数）。
  """
  if mode not in ("db", "deg"):
    return {"ok": False, "errors": [f"未知 mode: {mode}（db|deg）"]}
  run_dir = RUNS_DIR / run_id
  results = run_dir / "results"
  if not results.is_dir():
    return {"ok": False, "errors": [f"该 run 无 results 产物: {run_id}"]}

  import numpy as np

  from rfauto.measurement.import_data import import_touchstone

  curves: list[dict[str, Any]] = []
  warning = None
  try:
    for sp in sorted(results.glob("*.s2p")) + sorted(results.glob("*.s3p")):
      data = import_touchstone(sp)
      s = data.s_params
      n = s.shape[1]
      for m in range(n):
        for k in range(n):
          if mode == "db":
            y = 20 * np.log10(np.abs(s[:, m, k]) + 1e-12)
          else:
            y = np.unwrap(np.angle(s[:, m, k])) * 180 / np.pi
          curves.append({
            "file": sp.name,
            "name": f"S{m + 1}{k + 1}",
            "freq_ghz": [round(float(x), 6)
                   for x in data.freq_ghz],
            "y": [round(float(v), 4) for v in y],
          })
  except Exception as e: # 无 Touchstone/解析失败不阻塞（返回空曲线+警告）
    warning = str(e)
  return {"ok": True, "run_id": run_id, "mode": mode,
      "curves": curves, "warning": warning}


def external_sparams(path: str, mode: str = "db") -> dict[str, Any]:
  """外部 Touchstone 导入（WP0.3/E8）：曲线与 run 版同构，供叠加对比。

  只读操作；解析失败/非 .sNp 显式报错（errors 列表，同 sparams_series
  惯例），不阻塞页面。
  """
  if mode not in ("db", "deg"):
    return {"ok": False, "errors": [f"未知 mode: {mode}（db|deg）"]}
  p = Path(path) # PathLike/字符串统一收敛（#140）
  if not p.is_file():
    return {"ok": False, "errors": [f"文件不存在: {p}"]}
  if p.suffix.lower() not in (".s1p", ".s2p", ".s3p", ".s4p"):
    return {"ok": False,
        "errors": [f"非 Touchstone 文件: {p.name}（需 .s1p-.s4p）"]}

  import numpy as np

  from rfauto.measurement.import_data import import_touchstone

  try:
    data = import_touchstone(p)
  except Exception as e:
    return {"ok": False, "errors": [f"解析失败: {p.name}: {e}"]}
  s = data.s_params
  n = s.shape[1]
  curves: list[dict[str, Any]] = []
  for m in range(n):
    for k in range(n):
      y = 20 * np.log10(np.abs(s[:, m, k]) + 1e-12) if mode == "db" else np.unwrap(np.angle(s[:, m, k])) * 180 / np.pi
      curves.append({
        "file": p.name,
        "name": f"S{m + 1}{k + 1}",
        "freq_ghz": [round(float(x), 6) for x in data.freq_ghz],
        "y": [round(float(v), 4) for v in y],
      })
  return {"ok": True, "path": str(p), "file": p.name, "mode": mode,
      "curves": curves, "n_points": int(s.shape[0])}


def sparams_compare_png(
  run_id: str, files: list[str], out_path: str | None = None,
) -> dict[str, Any]:
  """run 产物与外部 Touchstone 的 PNG 叠画对比（WP0.3/E8 验收渲染）。

  out_path 为空默认落 runs/sparams_compare/<时间戳>.png；曲线一律 dB，
  run 与外部文件以 run:/ext: 前缀区分；任一文件失败整体显式报错。
  """
  import time

  base = sparams_series(run_id, mode="db")
  if not base.get("ok"):
    return base
  run_curves = base.get("curves") or []
  if not run_curves:
    return {"ok": False,
        "errors": [f"该 run 无可画的 Touchstone 曲线: {run_id}"]}
  series: list[dict[str, Any]] = [
    {"label": f"run:{c['file']}·{c['name']}",
     "freq": c["freq_ghz"], "y": c["y"]}
    for c in run_curves
  ]
  for f in files:
    ext = external_sparams(f, mode="db")
    if not ext.get("ok"):
      return ext
    series += [{"label": f"ext:{c['file']}·{c['name']}",
          "freq": c["freq_ghz"], "y": c["y"]}
          for c in ext["curves"]]
  out = (Path(out_path) if out_path
      else Path("runs") / "sparams_compare"
      / f"{time.strftime('%Y%m%d_%H%M%S')}.png")
  out.parent.mkdir(parents=True, exist_ok=True)
  import matplotlib

  matplotlib.use("Agg") # headless（infra/report.py 同款）
  import matplotlib.pyplot as plt

  fig, ax = plt.subplots(figsize=(9, 5))
  for s_ in series:
    ax.plot(s_["freq"], s_["y"], linewidth=1.2, label=s_["label"])
  ax.set_xlabel("Frequency (GHz)")
  ax.set_ylabel("|S| (dB)")
  ax.grid(True, alpha=0.3)
  ax.legend(fontsize=8)
  fig.tight_layout()
  fig.savefig(out, dpi=150)
  plt.close(fig)
  return {"ok": True, "png": str(out), "n_curves": len(series),
      "n_sources": 1 + len(files)}


def cost_timeline(limit: int = 300) -> dict[str, Any]:
  """run 级目标成本时间线（3.4）。

  数据源 runs_stats.query_runs（SQLite 索引）；cost 对有配方快照的
  run 用快照 objectives 确定性重算（与校准详情页同法），无快照/无
  metrics 的 run cost=null（计数返回，前端不画点）。
  """
  from rfauto.core.objectives import Objective, SpecEvaluator
  from rfauto.service.runs_stats import query_runs

  q = query_runs(limit=limit)
  if not q.get("ok"):
    return q
  points: list[dict[str, Any]] = []
  n_without_cost = 0
  for run in reversed(q.get("runs", [])): # 时间升序（时间线从左到右）
    cost = None
    snap_p = RUNS_DIR / run["run_id"] / "recipe.snapshot.yaml"
    metrics = run.get("metrics") or {}
    if snap_p.exists() and metrics:
      try:
        import yaml

        with open(snap_p, encoding="utf-8") as f:
          objectives = [Objective(**o)
                 for o in (yaml.safe_load(f)
                      or {}).get("objectives") or []]
        if objectives:
          cost = float(SpecEvaluator.evaluate_objectives(
            metrics, objectives))
      except Exception:
        cost = None
    if cost is None:
      n_without_cost += 1
      continue
    points.append({
      "run_id": run["run_id"], "timestamp": run["timestamp"],
      "adapter": run["adapter"], "model": run["model"],
      "cost": cost,
    })
  tr = tune_trials()
  return {"ok": True, "points": points,
      "n_without_cost": n_without_cost,
      "latest_tune_run_id": tr.get("run_id"),
      "latest_tune_trials": tr.get("trials", [])[-200:]}


_REPORT_FILES = (
  ("run", "report.md"),
  ("sim_ci", "sim_ci_report.md"),
  ("calibration", "calibration/report.md"),
)


def list_reports() -> dict[str, Any]:
  """报告中心清单（3.5）：扫描 runs/ 下人读报告（kind+路径+元信息）。"""
  entries: list[dict[str, Any]] = []
  if not RUNS_DIR.exists():
    return {"ok": True, "reports": []}
  for run in sorted(RUNS_DIR.iterdir(), reverse=True):
    if not run.is_dir():
      continue
    model = None
    meta_p = run / "meta.json"
    if meta_p.exists():
      with contextlib.suppress(Exception):
        model = (json.loads(meta_p.read_text(encoding="utf-8"))
             or {}).get("model")
    for kind, rel in _REPORT_FILES:
      p = run / rel
      if not p.is_file():
        continue
      try:
        size = p.stat().st_size
        mtime = p.stat().st_mtime
      except OSError:
        continue
      entries.append({
        "run_id": run.name, "kind": kind, "model": model,
        "path": str(p).replace("\\", "/"),
        "size_bytes": size, "mtime": mtime,
      })
  return {"ok": True, "reports": entries}


def report_content(path: str) -> dict[str, Any]:
  """读取单份报告文本（路径白名单：只允许 runs/ 下的 .md）。

  附带 run_id（路径首段），报告中心前端据此把相对图片引用重写到
  /api/runs/<run_id>/figs/ 白名单路由（修复裂图）。
  """
  p = Path(path)
  try:
    resolved = p.resolve()
    rel = resolved.relative_to(RUNS_DIR.resolve())
  except (ValueError, OSError):
    return {"ok": False, "errors": [f"路径越界（只允许 runs/）: {path}"]}
  if resolved.suffix != ".md" or not resolved.is_file():
    return {"ok": False, "errors": [f"不是 runs/ 下的 .md 报告: {path}"]}
  try:
    text = resolved.read_text(encoding="utf-8")
  except OSError as e:
    return {"ok": False, "errors": [f"报告读取失败: {e}"]}
  run_id = rel.parts[0] if len(rel.parts) > 1 else None
  return {"ok": True, "path": str(resolved).replace("\\", "/"),
      "run_id": run_id, "content": text}


#: 报告图片白名单：只服务 runs/<run_id>/results/figs/ 下的位图/矢量图
_FIG_SUFFIXES = (".png", ".svg")
#: report.md 里图片引用的固定子目录（裂图修复：相对引用重写到白名单路由）
REPORT_FIG_SUBDIR = "results/figs"
#: pareto_runs 目录扫描硬上限（防 runs/ 失控增长拖垮下拉；正常远小于此）
_PARETO_RUNS_SCAN_CAP = 4000


def run_fig_file(run_id: str, name: str) -> Path | None:
  """报告图片白名单解析（项 2 裂图修复，路径穿越防护）。

  只允许 runs/<run_id>/results/figs/ 下的 .png/.svg：
  - run_id 必须是单段目录名（拒 / \\ .. 等）；
  - name 是 report.md 里的相对引用（如 results/figs/s11_curve.png，
   也接受裸文件名），resolve 后必须仍落在该 run 的 figs 目录内；
  - 文件不存在/后缀不符 → None（路由层转 404，前端显示占位）。
  """
  run_id = str(run_id).strip()
  name = str(name).replace("\\", "/").strip().lstrip("/")
  if (not run_id or not name
      or run_id in (".", "..")
      or "/" in run_id or "\\" in run_id or ".." in run_id):
    return None
  if "/" not in name:
    name = f"{REPORT_FIG_SUBDIR}/{name}"
  figs_root = (RUNS_DIR / run_id / REPORT_FIG_SUBDIR).resolve()
  try:
    candidate = (RUNS_DIR / run_id / name).resolve()
    candidate.relative_to(figs_root)
  except (ValueError, OSError):
    return None
  if candidate.suffix.lower() not in _FIG_SUFFIXES or not candidate.is_file():
    return None
  return candidate


def pareto_runs(limit: int = 200) -> dict[str, Any]:
  """优化洞察页 run 清单（项 3：下拉过滤与分组）。

  三档 tier：front（有 results/pareto_front.json，直读前沿）>
  trials（有 trials/*.json，可现算约束 Pareto）> single（单点仿真，
  无优化轨迹）。优化 run 排前、单点 run 排后——前端据此分组下拉、
  无数据 run 标注并给人话空态。
  """
  entries: list[dict[str, Any]] = []
  if RUNS_DIR.exists():
    # 全量扫目录再排序后切 limit：字典序里 w* 等字母目录排在日期目录前，
    # 若先切片会被字母目录占满名额把日期 run 截掉（tier 语义优先于字典序）
    run_dirs = sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()),
             reverse=True)
    if len(run_dirs) > _PARETO_RUNS_SCAN_CAP: # 内部扫描硬上限（防失控）
      run_dirs = run_dirs[:_PARETO_RUNS_SCAN_CAP]
    for run in run_dirs:
      has_front = (run / "results" / "pareto_front.json").is_file()
      trials_dir = run / "trials"
      n_trials = (sum(1 for _ in trials_dir.glob("*.json"))
            if trials_dir.is_dir() else 0)
      tier = "front" if has_front else ("trials" if n_trials else "single")
      model = adapter = None
      meta_p = run / "meta.json"
      if meta_p.exists():
        with contextlib.suppress(Exception):
          meta = json.loads(meta_p.read_text(encoding="utf-8")) or {}
          model, adapter = meta.get("model"), meta.get("adapter")
      entries.append({
        "run_id": run.name, "model": model, "adapter": adapter,
        "tier": tier, "has_pareto": has_front, "n_trials": n_trials,
      })
  tier_rank = {"front": 0, "trials": 1, "single": 2}
  # 两次稳定排序：tier 内 run_id 倒序（新 run 在前），tier 升序（优化 run 排前）
  entries.sort(key=lambda e: e["run_id"], reverse=True)
  entries.sort(key=lambda e: tier_rank.get(e["tier"], 3))
  return {"ok": True, "runs": entries[:max(0, int(limit))]}


def loop_boards(limit: int = 20) -> dict[str, Any]:
  """执行看板清单（WP3.5 v1.2 增强；自治环步骤可视的列表侧）。"""
  from rfauto.service.loop_board import list_boards

  return list_boards(limit=limit)


def loop_board_view(board_id: str) -> dict[str, Any]:
  """单个执行看板：当前步骤 + 里程碑验收表 + 步骤历史。"""
  from rfauto.service.loop_board import read_board

  return read_board(board_id)


def loop_board_control(board_id: str, action: str) -> dict[str, Any]:
  """向执行看板发控制命令（pause/resume/takeover），环在步骤边界响应。"""
  from rfauto.service.loop_board import board_control

  return board_control(board_id, action)


# ═══ G9 场可视化 3D + Smith 圆图（G9 余量；服务层 JSON 进出）═══════
#
# 数据源：openEMS 真跑 run 的 DumpHDF5 产物（nf2ff 盒六面 nf2ff_E_*.h5、
# SAR_raw.h5/SAR_1g.h5 体 dump）+ CalcNF2FF 原生 farfield_3d.h5/nf2ff.h5；
# 数值全部由 infra.visualization 确定性内核变换（|E| 包络/切片/等值面/dB
# 归一/Γ→Z），本层只做产物定位与 JSON 组装。任一子产物失败只记 warning
# （#105 best-effort），不阻塞页面。

#: DumpHDF5 浅层落盘位置（run 根=模板脚本目录，fdtd/=SIM_PATH），免全树 rglob
FIELD_DUMP_SUBDIRS: tuple[str, ...] = ("", "fdtd")
#: CalcNF2FF 原生 HDF5 名（优先 3D 全球面，其次 φ 切面）
FARFIELD_H5_NAMES: tuple[str, ...] = ("farfield_3d.h5", "nf2ff.h5")


def _is_field_dump(path: Path) -> bool:
  """DumpHDF5 契约辨识：Mesh + FieldData 组（nf2ff.h5 是 nf2ff 组，排除）。"""
  try:
    import h5py

    with h5py.File(path, "r") as h:
      return "Mesh" in h and "FieldData" in h
  except Exception:
    return False


def _field_dump_candidates(run_dir: Path) -> list[Path]:
  """run 根与 fdtd/ 下的场 dump（体 dump 优先于 nf2ff 盒面 dump，再按名排序）。"""
  found: list[Path] = []
  for sub in FIELD_DUMP_SUBDIRS:
    base = run_dir / sub if sub else run_dir
    if not base.is_dir():
      continue
    found.extend(p for p in sorted(base.glob("*.h5")) if _is_field_dump(p))
  return sorted(found, key=lambda p: (p.name.startswith("nf2ff_"), p.name))


def _farfield_h5(run_dir: Path) -> Path | None:
  for name in FARFIELD_H5_NAMES:
    for sub in FIELD_DUMP_SUBDIRS:
      cand = (run_dir / sub if sub else run_dir) / name
      if cand.is_file():
        return cand
  return None


def _viz3d_available() -> bool:
  from rfauto.infra.visualization import viz3d_available

  return viz3d_available()


# ─── patch 族修正后 η 物理合理门 ──
#
# 数字依据链（坑 #118：裁判 = 收敛真跑实测 + 独立来源解析式，不是自己的推导）：
# * 解析式（Balanis 单腔损耗分解，PEC 导体 Q_c→∞）：η = Q_d/(Q_d+Q_rad)，
#  Q_d = 1/tanδ；RO4350B tanδ=0.0037 → Q_d = 270.27。
# * 实测锚（域扩后真收敛冒烟：能量
#  −60.3dB、nf2ff 盒顶余量 40.5mm ≥ λ/4 33.9mm、两口径 Dmax 差 0.015dB）：
#  η_corr = 0.5711 → Q_rad = Q_d·(1−η)/η = 203（≈200）。
# * 伪象幅度（同几何、仅 AIR_TOP 26.79→45mm 差异的
#  紧贴盒轮）：η_corr 0.6215 = 较锚值 Prad 虚高 +8.82% → 守卫带取该观测值。
# * 下沿 = Q_d/(Q_d + 203×1.0882) = 270.27/491.13 = 0.5503 ≈ 0.55（旧门 0.62
#  出自早期 "Q_rad~60–80" 估计，被实测 2.5× 否定）；上沿保留 0.79（对应
#  Q_rad≈72，即 Prad 较锚值虚高 ~2.8× 才触线，作镜像修正失效/盒伪象检测线）。
# 作用域：仅 template=="patch"（dipole 全包盒 η=0.99 属另一族，不套此窗）。
PATCH_ETA_GATE: tuple[float, float] = (0.55, 0.79)
#: 门的实测锚（回归钉用；两轮真跑数字均出自 runs/ 判读 json，非推导）
PATCH_ETA_GATE_BASIS: dict[str, float] = {
  "tan_delta": 0.0037,
  "eta_anchor_converged": 0.5711170472292979,  # patch_field_smoke_recheck
  "eta_tight_box_run": 0.621490823071419,    # patch_field_smoke（紧贴盒）
}


def patch_eta_gate(metrics: dict[str, Any]) -> dict[str, Any]:
  """修正后 η 的 patch 族物理合理性判读（确定性比较；η 缺失如实 unknown）。

  返回 {gate:[lo,hi], value, ok(True/False/None), reason}；ok=None 表示不可
  判读（P_acc 缺失/非正 → η None），不虚构（#105）。
  """
  lo, hi = PATCH_ETA_GATE
  eta = metrics.get("efficiency")
  out: dict[str, Any] = {"gate": [lo, hi], "value": eta, "ok": None, "reason": ""}
  if eta is None:
    out["reason"] = "η 不可得（P_acc 缺失或非正）"
    return out
  eta = float(eta)
  out["value"] = eta
  if not (0.0 < eta < 1.0):
    out["ok"] = False
    out["reason"] = f"η={eta:.4f} 非物理（须 0<η<1；≥1 常为 PEC 镜像双计未修正）"
  elif eta < lo:
    out["ok"] = False
    out["reason"] = f"η={eta:.4f} 低于下沿 {lo}（欠辐射/收敛或盒余量存疑）"
  elif eta > hi:
    out["ok"] = False
    out["reason"] = f"η={eta:.4f} 超上沿 {hi}（Prad 虚高伪象嫌疑）"
  else:
    out["ok"] = True
    out["reason"] = f"η={eta:.4f} 落 [{lo}, {hi}]"
  return out


def field_runs(limit: int = 50) -> dict[str, Any]:
  """含场 dump 产物的 run 清单（场可视化页下拉；战役多 run 逐个可选）。"""
  hits: list[dict[str, Any]] = []
  if RUNS_DIR.is_dir():
    for run_dir in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir()):
      dumps = _field_dump_candidates(run_dir)
      if not dumps:
        continue
      hits.append({
        "run_id": run_dir.name,
        "dumps": [d.name for d in dumps],
        "n_dumps": len(dumps),
        "has_farfield_h5": _farfield_h5(run_dir) is not None,
        "mtime": max(d.stat().st_mtime for d in dumps),
      })
  hits.sort(key=lambda h: -h["mtime"])
  return {"ok": True, "runs": hits[: max(1, int(limit))],
      "viz3d_available": _viz3d_available()}


def field_view(
  run_id: str,
  dump: str | None = None,
  engine: str = "auto",
  levels_db: tuple[float, ...] | None = None,
  slice_index: dict[str, int] | None = None,
) -> dict[str, Any]:
  """单 run 场可视化视图：切片热图 + 等值面/等值线 + 远场 3D 图 + D4 指标。

  dump 缺省取候选首个（体 dump 优先）；engine=auto|pyvista|numpy 透传内核；
  levels_db 等值电平（相对峰值 dB）；slice_index 各轴切片索引（缺省中面）。
  远场 3D 图（farfield_3d.h5）与 farfield_meta.json 指标为 D4 联动，缺失
  置 None 并记 warning。指标经 PEC 地镜像修正（core.farfield.correct_pec_mirror，
  与 nf2ff_service 同一函数；修正前原值留 raw）并附 patch 族 η 门判读 eta_gate
  （非 patch 模板为 None）。
  """
  from rfauto.infra.visualization import (
    DEFAULT_ISO_LEVELS_DB,
    farfield_pattern_from_h5,
    field_isosurface,
    field_slices,
    read_field_dump,
  )

  run_dir = RUNS_DIR / run_id
  if not run_dir.is_dir():
    return {"ok": False, "errors": [f"run 不存在: {run_id}"]}
  dumps = _field_dump_candidates(run_dir)
  if not dumps:
    return {"ok": False,
        "errors": [f"该 run 无 openEMS 场 dump（需 far_field/sar=True 或 DumpHDF5 真跑）: {run_id}"]}
  if dump:
    picked = next((d for d in dumps if d.name == dump), None)
    if picked is None:
      return {"ok": False, "errors": [f"dump 不存在: {dump}（可选 {[d.name for d in dumps]}）"]}
  else:
    picked = dumps[0]

  warnings: list[str] = []
  try:
    vol = read_field_dump(picked)
  except Exception as e:
    return {"ok": False, "errors": [f"dump 读取失败 {picked.name}: {e}"]}

  levels = tuple(float(v) for v in levels_db) if levels_db else DEFAULT_ISO_LEVELS_DB
  try:
    slices = field_slices(vol, indices=slice_index)
  except Exception as e: # 切片是主视图；失败如实报错
    return {"ok": False, "errors": [f"切片失败: {e}"]}
  try:
    iso = field_isosurface(vol, levels_db=levels, engine=engine)
    warnings.extend(iso.get("warnings") or [])
  except Exception as e: # 等值面 best-effort（#105）
    iso = {"ok": False, "engine": engine, "errors": [str(e)]}
    warnings.append(f"等值面失败: {e}")

  pattern3d: dict[str, Any] | None = None
  ff_h5 = _farfield_h5(run_dir)
  if ff_h5 is not None:
    try:
      pattern3d = farfield_pattern_from_h5(ff_h5)
    except Exception as e:
      warnings.append(f"远场 HDF5 解析失败 {ff_h5.name}: {e}")

  farfield_metrics: dict[str, Any] | None = None
  try:
    from rfauto.core.farfield import (
      FARFIELD_META_NAME,
      correct_pec_mirror,
      find_artifacts,
    )

    found = find_artifacts(run_dir)
    if FARFIELD_META_NAME in found:
      meta = json.loads(found[FARFIELD_META_NAME].read_text(encoding="utf-8"))
      if meta.get("ok"):
        # PEC 地镜像修正：与 nf2ff_service._read_metrics 同一内核函数
        # （core.farfield.correct_pec_mirror，#249），修正前原值留 raw。
        fixed = correct_pec_mirror(meta)
        farfield_metrics = {k: fixed.get(k) for k in
                  ("f_res_ghz", "dmax_dbi", "gain_max_dbi",
                   "efficiency", "power_budget_closure", "template")}
        farfield_metrics["pec_mirror_factor"] = fixed.get("pec_mirror_factor", 1.0)
        if "raw" in fixed:
          farfield_metrics["raw"] = fixed["raw"]
        farfield_metrics["eta_gate"] = (
          patch_eta_gate(farfield_metrics)
          if farfield_metrics.get("template") == "patch" else None)
  except Exception as e:
    warnings.append(f"farfield_meta.json 解析失败: {e}")

  return {
    "ok": True,
    "run_id": run_id,
    "dumps": [d.name for d in dumps],
    "selected": picked.name,
    "volume": {
      "shape": list(vol.shape),
      "domain": vol.domain,
      "dump_type": vol.dump_type,
      "frequency_ghz": (vol.frequency_hz / 1e9 if vol.frequency_hz else None),
      "n_timesteps": vol.n_timesteps,
      "peak": iso.get("peak", vol.peak),
      "x_mm": [round(float(v) * 1e3, 4) for v in (vol.x_m[0], vol.x_m[-1])],
      "y_mm": [round(float(v) * 1e3, 4) for v in (vol.y_m[0], vol.y_m[-1])],
      "z_mm": [round(float(v) * 1e3, 4) for v in (vol.z_m[0], vol.z_m[-1])],
    },
    "slices": slices,
    "isosurface": iso,
    "engine": iso.get("engine", engine),
    "pattern3d": pattern3d,
    "farfield_metrics": farfield_metrics,
    "polar_link": f"/api/farfield/{run_id}", # D4 极坐标页联动
    "warnings": warnings,
  }


def _smith_traces_from_touchstone(path: Path) -> tuple[list[dict[str, Any]], float]:
  """Touchstone → 各端口反射系数 S_ii 的 Smith 点列（网格几何单独给一次）。"""
  import numpy as np

  from rfauto.infra.visualization import smith_chart_data
  from rfauto.measurement.import_data import import_touchstone

  data = import_touchstone(path)
  net = data.network
  z0 = float(np.real(np.asarray(net.z0)[0, 0])) if np.asarray(net.z0).size else 50.0
  traces: list[dict[str, Any]] = []
  for i in range(net.nports):
    sm = smith_chart_data(data.freq_ghz, net.s[:, i, i], z0=z0, with_grid=False)
    traces.append({"file": path.name, "name": f"S{i + 1}{i + 1}", "port": i + 1, **sm})
  return traces, z0


def smith_view(run_id: str) -> dict[str, Any]:
  """单 run Smith 圆图数据（S 参数页增强）：各 Touchstone 的 S_ii 轨迹 + 网格。"""
  from rfauto.infra.visualization import smith_grid

  run_dir = RUNS_DIR / run_id
  results = run_dir / "results"
  if not results.is_dir():
    return {"ok": False, "errors": [f"该 run 无 results 产物: {run_id}"]}
  traces: list[dict[str, Any]] = []
  z0 = 50.0
  warning = None
  try:
    files = [p for ext in (".s1p", ".s2p", ".s3p", ".s4p")
         for p in sorted(results.glob(f"*{ext}"))]
    for sp in files:
      t, z0 = _smith_traces_from_touchstone(sp)
      traces.extend(t)
  except Exception as e: # 解析失败不阻塞（同 sparams_series 惯例）
    warning = str(e)
  return {"ok": True, "run_id": run_id, "z0": z0, "traces": traces,
      "grid": smith_grid(), "warning": warning}


def smith_external(path: str) -> dict[str, Any]:
  """外部 Touchstone → Smith 轨迹（与 external_sparams 同构，只读）。"""
  from rfauto.infra.visualization import smith_grid

  p = Path(path) # PathLike/字符串统一收敛（#140）
  if not p.is_file():
    return {"ok": False, "errors": [f"文件不存在: {p}"]}
  if p.suffix.lower() not in (".s1p", ".s2p", ".s3p", ".s4p"):
    return {"ok": False, "errors": [f"非 Touchstone 文件: {p.name}（需 .s1p-.s4p）"]}
  try:
    traces, z0 = _smith_traces_from_touchstone(p)
  except Exception as e:
    return {"ok": False, "errors": [f"Touchstone 解析失败: {e}"]}
  return {"ok": True, "path": str(p), "file": p.name, "z0": z0,
      "traces": traces, "grid": smith_grid()}


# ─── 优化洞察（E9 Pareto 前沿视图 / E10 可行性热图）─────────────────────────

def _load_run_trials(run_dir: Path) -> list[dict[str, Any]]:
  """读 run 的 trials/*.json 审计文件（与 v3_services._load_run_trials
  同口径：按文件名排序、坏文件跳过）。"""
  tdir = run_dir / "trials"
  if not tdir.is_dir():
    return []
  trials: list[dict[str, Any]] = []
  for f in sorted(tdir.glob("trial_*.json")):
    try:
      trials.append(json.loads(f.read_text(encoding="utf-8")))
    except Exception:
      continue
  return trials


def _run_dir_or_error(run_id: str) -> tuple[Path | None, dict[str, Any] | None]:
  run_dir = RUNS_DIR / run_id
  if not run_dir.is_dir():
    return None, {"ok": False, "errors": [f"run 不存在: {run_id}"]}
  return run_dir, None


def pareto_view(run_id: str) -> dict[str, Any]:
  """E9 Pareto 前沿视图（优化洞察页，只读）。

  双源（历史登记的"optimizer 有 pareto_points 但未接 UI"）：
  - results/pareto_front.json 存在（nsga2 run，E9 起落盘）→ 直读；
  - 缺产物（旧 run / TPE run）→ 从 trials/*.json 现算约束 Pareto：
   目标向量 = 逐 objective 违约量（与 run_multi_optimization 同口径，
   配方快照解析），约束违约量取 trial 审计的 constraint_values（无则
   视为无约束）；约束支配走 pareto_tools.constrained_pareto_front
   确定性内核。
  """
  run_dir, err = _run_dir_or_error(run_id)
  if err:
    return err
  front_path = run_dir / "results" / "pareto_front.json"
  if front_path.is_file():
    try:
      doc = json.loads(front_path.read_text(encoding="utf-8"))
    except Exception as exc:
      return {"ok": False, "errors": [f"pareto_front.json 解析失败: {exc}"]}
    return {"ok": True, "run_id": run_id, "source": "pareto_front.json",
        "objective_names": doc.get("objective_names", []),
        "param_names": doc.get("param_names", []),
        "n_pareto": doc.get("n_pareto", len(doc.get("pareto_points", []))),
        "hv_convergence": doc.get("hv_convergence"),
        "constraint_names": doc.get("constraint_names", []),
        "points": doc.get("pareto_points", [])}

  trials = _load_run_trials(run_dir)
  points = [t for t in trials
       if isinstance(t.get("params"), dict) and t.get("metrics")]
  if not points:
    return {"ok": False, "errors": [
      f"run {run_id} 无 pareto_front.json 且 trials 无可评估样本，"
      "前沿不可算（如实缺省，不凑绿 #122）"]}
  snap = run_dir / "recipe.snapshot.yaml"
  if not snap.is_file():
    return {"ok": False, "errors": [
      f"run {run_id} 无配方快照，trials 目标向量无法重建"]}
  import yaml

  try:
    recipe = yaml.safe_load(snap.read_text(encoding="utf-8")) or {}
  except Exception as exc:
    return {"ok": False, "errors": [f"配方快照解析失败: {exc}"]}
  from rfauto.core.objectives import Objective
  from rfauto.optimization.optimizer import _single_objective_cost
  from rfauto.optimization.pareto_tools import constrained_pareto_front

  objectives = [Objective(**o) for o in recipe.get("objectives", [])]
  if len(objectives) < 2:
    return {"ok": False, "errors": [
      "配方 objectives 少于 2 个，无 Pareto 前沿语义（单目标 run 走成本曲线）"]}
  obj_names = [o.metric for o in objectives]
  obj_mat: list[list[float]] = []
  viol_mat: list[list[float]] = []
  kept: list[dict[str, Any]] = []
  for t in points:
    metrics = t["metrics"]
    obj_mat.append([_single_objective_cost(metrics, o) for o in objectives])
    cv = t.get("constraint_values") or []
    viol_mat.append([float(v) for v in cv])
    kept.append(t)
  front_idx = constrained_pareto_front(obj_mat, viol_mat if any(viol_mat) else None)
  out_points: list[dict[str, Any]] = []
  for i in front_idx:
    t = kept[i]
    p: dict[str, Any] = {
      "params": t["params"],
      "objectives": {obj_names[j]: float(obj_mat[i][j])
              for j in range(len(obj_names))},
      "cost": t.get("cost"),
    }
    if any(viol_mat):
      cv = viol_mat[i]
      p["constraint_values"] = cv
      p["feasible"] = all(v <= 0.0 for v in cv) if cv else None
    out_points.append(p)
  return {"ok": True, "run_id": run_id, "source": "trials_recomputed",
      "objective_names": obj_names,
      "param_names": sorted({k for t in kept for k in t["params"]}),
      "n_pareto": len(out_points),
      "hv_convergence": None,
      "constraint_names": [c["metric"] for c in
                 (recipe.get("optimization") or {}).get("constraints", [])
                 if isinstance(c, dict) and c.get("metric")],
      "points": out_points,
      "n_trials_used": len(kept)}


def feasibility_heatmap(
  run_id: str,
  x_param: str,
  y_param: str,
  grid_n: int = 12,
) -> dict[str, Any]:
  """E10 可行性热图（优化洞察页，只读）：trials 审计 → (x,y) 网格可行率。

  读 trials/*.json 的 params + constraint_values（optimizer.py 落盘口径，
  ≤0=可行），对 (x_param, y_param) 做**确定性分箱**（无插值无新依赖）：
  每格给点数 / 可行点数 / 可行率 / 平均总违约量。无约束 run（审计无
  constraint_values）如实报错不凑绿（#122）。
  """
  run_dir, err = _run_dir_or_error(run_id)
  if err:
    return err
  x_param = str(x_param)
  y_param = str(y_param)
  if x_param == y_param:
    return {"ok": False, "errors": ["x_param 与 y_param 不能相同"]}
  grid_n = max(2, min(int(grid_n), 64))
  trials = _load_run_trials(run_dir)
  used: list[dict[str, Any]] = []
  total = len(trials)
  for t in trials:
    params = t.get("params")
    cv = t.get("constraint_values")
    if (isinstance(params, dict) and x_param in params and y_param in params
        and isinstance(cv, list) and len(cv) > 0):
      used.append(t)
  if not used:
    if total:
      return {"ok": False, "errors": [
        f"run {run_id} 的 {total} 条 trial 审计均无 (params, "
        "constraint_values) 记录：非约束 run 或旧 run 无 E10 审计，"
        "可行性热图不可算（如实缺省）"]}
    return {"ok": False, "errors": [f"run {run_id} 无 trials 审计文件"]}

  xs = [float(t["params"][x_param]) for t in used]
  ys = [float(t["params"][y_param]) for t in used]
  x_lo, x_hi = min(xs), max(xs)
  y_lo, y_hi = min(ys), max(ys)
  if x_hi <= x_lo or y_hi <= y_lo:
    return {"ok": False, "errors": [
      f"{x_param}/{y_param} 在已评样本中无展宽（单点或退化），"
      "热图网格不可分箱"]}

  def _cell(v: float, lo: float, hi: float) -> int:
    # 确定性分箱：等宽格，右端点归末格（无浮点边界抖动逃逸）
    idx = int((v - lo) / (hi - lo) * grid_n)
    return min(max(idx, 0), grid_n - 1)

  cells: dict[tuple[int, int], dict[str, Any]] = {}
  for t in used:
    ci = (_cell(float(t["params"][x_param]), x_lo, x_hi),
       _cell(float(t["params"][y_param]), y_lo, y_hi))
    cv = [float(v) for v in t["constraint_values"]]
    feasible = all(v <= 0.0 for v in cv)
    total_viol = sum(max(0.0, v) for v in cv)
    c = cells.setdefault(ci, {"n": 0, "n_feasible": 0, "violation_sum": 0.0})
    c["n"] += 1
    c["n_feasible"] += int(feasible)
    c["violation_sum"] += total_viol
  out_cells: list[dict[str, Any]] = []
  for (i, j) in sorted(cells):
    c = cells[(i, j)]
    out_cells.append({
      "i": i, "j": j, "n": c["n"], "n_feasible": c["n_feasible"],
      "feasible_rate": round(c["n_feasible"] / c["n"], 6),
      "mean_total_violation": round(c["violation_sum"] / c["n"], 6),
    })
  n_feasible_total = sum(1 for t in used
              if all(float(v) <= 0.0 for v in t["constraint_values"]))
  return {"ok": True, "run_id": run_id,
      "x_param": x_param, "y_param": y_param, "grid_n": grid_n,
      "x_edges": [round(x_lo + (x_hi - x_lo) * k / grid_n, 9)
            for k in range(grid_n + 1)],
      "y_edges": [round(y_lo + (y_hi - y_lo) * k / grid_n, 9)
            for k in range(grid_n + 1)],
      "cells": out_cells,
      "n_trials_used": len(used), "n_trials_total": total,
      "n_feasible_total": n_feasible_total}
