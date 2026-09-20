"""服务层 —— CLI 与 MCP 共用的全部业务函数。

所有服务函数 JSON 进出，保证"人能用的 Agent 就能用，Agent 能用的人也能用"（军规 10）。
长任务只返回 JobHandle，永不阻塞调用方（军规 4）。
"""

from __future__ import annotations

import contextlib
import getpass
import json
import platform
from pathlib import Path
from typing import Any

from rfauto import __version__
from rfauto.core.contracts import AdsExchangeContract
from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.core.parameters import ParameterSystem, ParamValue
from rfauto.core.state import generate_job_id, generate_run_id


def validate_recipe(recipe_path: str | Path) -> dict[str, Any]:
  """校验配方文件，返回 {ok: bool, errors: [...], warnings: [...]}。"""
  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方文件不存在: {path}"], "warnings": []}

  try:
    import yaml
    with open(path, encoding="utf-8") as f:
      data = yaml.safe_load(f)
  except Exception as e:
    return {"ok": False, "errors": [f"YAML 解析失败: {e}"], "warnings": []}

  if data is None:
    return {"ok": False, "errors": [f"配方文件为空: {path}"], "warnings": []}
  if not isinstance(data, dict):
    return {"ok": False, "errors": [f"配方顶层必须是映射（键值对），实际: {type(data).__name__}"], "warnings": []}

  errors: list[str] = []
  warnings: list[str] = []

  # 基本字段校验
  if "model" not in data:
    errors.append("缺少 'model' 字段")
  if "params" not in data:
    errors.append("缺少 'params' 字段")
  if "setup" not in data:
    warnings.append("缺少 'setup' 字段，将使用默认值")

  # 模型是否已注册
  if "model" in data:
    try:
      from rfauto.models.registry import get
      get(data["model"])
    except KeyError:
      errors.append(f"未知模型: {data['model']}")

  # 目标函数校验
  if "objectives" in data:
    for i, obj_data in enumerate(data["objectives"]):
      try:
        Objective(**obj_data)
      except Exception as e:
        errors.append(f"objectives[{i}] 校验失败: {e}")

  return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def dry_run(recipe_path: str | Path, *, adapter_name: str = "fake") -> dict[str, Any]:
  """dry-run 护栏（计划内缺口 6）——只验证不执行。

  走完 run_once 的全部前置检查（配方校验、模型注册、参数解析、
  缓存键计算、AEDT 路径检查），但不创建适配器、不建模、不求解、
  不写 runs/。返回执行计划供人工/Agent 确认后再真实提交。
  """
  validation = validate_recipe(recipe_path)
  if not validation["ok"]:
    return {"ok": False, "mode": "dry-run", "errors": validation["errors"]}

  import os

  import yaml
  with open(recipe_path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)

  model_name = recipe_data.get("model", "")
  params_data = recipe_data.get("params", {})
  resolved_params = {
    k: (v.get("value") if isinstance(v, dict) else v) for k, v in params_data.items()
  }

  param_values = {
    k: ParamValue(name=k, value=v.get("value", 0), unit=v.get("unit", "mm"))
    if isinstance(v, dict) else ParamValue(name=k, value=v)
    for k, v in params_data.items()
  }
  ps = ParameterSystem(param_values)

  aedt_version = "fake"
  adapter_ok = True
  if adapter_name == "hfss":
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if aedt_path and not Path(aedt_path).exists():
      adapter_ok = False
    # 项目 B：与 run_once 同源探测（显式路径优先，否则自动探测）
    from rfauto.infra.version_probe import resolve_aedt_install
    install = resolve_aedt_install(aedt_path or None)
    adapter_ok = adapter_ok and install is not None
    aedt_version = install["aedt_version"] if install else "unknown"
  elif adapter_name != "fake":
    return {"ok": False, "mode": "dry-run", "errors": [f"未知适配器: {adapter_name}"]}

  from rfauto.models.registry import get as get_plugin_cls
  plugin_cls = get_plugin_cls(model_name)

  # 内容寻址键（与 run_once 同一派生 components_for_run，保证 dry-run
  # 预报的 cache_hit 与真跑判定同键；why_miss 给出"为什么不会命中"）
  from rfauto.infra.result_cache import ResultCache
  cache = ResultCache()
  cache_components = cache.components_for_run(
    model_name=model_name,
    recipe_data=recipe_data,
    params_canonical_json=ps.to_canonical_json(),
    plugin_version=f"schema{plugin_cls.schema_version}",
    plugin_schema_version=plugin_cls.schema_version,
    adapter_version=adapter_name,
    aedt_version=aedt_version,
    export_contract=AdsExchangeContract.for_n_ports(plugin_cls.n_ports),
  )
  cache_key = cache.compute_content_key(**cache_components)
  cache_lookup = cache.lookup(cache_key, components=cache_components)

  return {
    "ok": True,
    "mode": "dry-run",
    "message": "仅验证未执行——确认计划后去掉 --dry-run 真实提交",
    "recipe": str(recipe_path),
    "model": model_name,
    "adapter": adapter_name,
    "adapter_ready": adapter_ok,
    "aedt_version": aedt_version,
    "params": resolved_params,
    "objectives": recipe_data.get("objectives", []),
    "setup": recipe_data.get("setup", {}),
    "plugin_version": f"schema{plugin_cls.schema_version}",
    "cache_key": cache_key,
    "cache_hit": cache_lookup["hit"],
    "cache": {
      "key": cache_key,
      "provenance": cache_lookup["provenance"],
      "why_miss": cache_lookup["why_miss"],
      "components": cache_components,
    },
    "validation": validation,
  }


def run_once(
  recipe_path: str | Path,
  *,
  adapter_name: str = "fake",
  study: str = "",
  seed: str = "",
) -> dict[str, Any]:
  """单次仿真（build → solve → post → metrics → sNp → figs）。

  adapter_name: "fake"（FakeAdapter 解析近似）或 "hfss"（真实 AEDT 全链）。
  study / seed: 仅作 provenance 作用域记入缓存 manifest 与 run meta（#158：
  **不进缓存键**——同几何不同 study 命中同一条目并标 cross_study），缺省空串。
  """
  # 校验配方
  validation = validate_recipe(recipe_path)
  if not validation["ok"]:
    return {"ok": False, "errors": validation["errors"]}

  import yaml
  with open(recipe_path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)

  run_id = generate_run_id()

  # 创建 run 目录（绝对路径：AEDT 拒绝相对项目路径，会解析到它自己的工作目录）
  from rfauto.infra.run_store import create_run_dir, snapshot_recipe, write_meta
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  snapshot_recipe(run_dir, recipe_data)

  # 获取模型插件（先于适配器：n_ports / fake_model_type 驱动契约与解析近似，
  # C4 修复：原先 fake 模式硬编码 3 端口 wilkinson，branchline/patch 的
  # fake 仿真产出的是错误模型的 S 参数）
  from rfauto.models.registry import get as get_plugin_cls
  model_name = recipe_data.get("model", "")
  try:
    plugin_cls = get_plugin_cls(model_name)
  except KeyError:
    return {"ok": False, "errors": [f"未知模型: {model_name}"]}
  plugin = plugin_cls()

  # 交换契约按插件端口数生成（3 端口时与历史默认完全一致）
  n_ports = plugin_cls.n_ports
  contract = AdsExchangeContract.for_n_ports(n_ports)

  # 解析参数（前移：缓存键依赖规范化参数串）
  params_data = recipe_data.get("params", {})
  param_values = {}
  for k, v in params_data.items():
    if isinstance(v, dict):
      param_values[k] = ParamValue(name=k, value=v.get("value", 0), unit=v.get("unit", "mm"))
    else:
      param_values[k] = ParamValue(name=k, value=v)

  ps = ParameterSystem(param_values)

  if adapter_name not in ("fake", "hfss"):
    return {"ok": False, "errors": [f"未知适配器: {adapter_name}"]}

  # ─── ResultCache：键计算与查询前移（C5 修复：原先发生在 AEDT 建会话与
  # build 之后——缓存命中仍付出完整建模成本）。aedt_version 仅由环境变量
  # 推导，无需连接。plugin_version 取插件 schema 版本（几何变更须升版本
  # 才能避开陈旧缓存；原先三处硬编码 "0.1.0" 各自为政）。──
  import os

  from rfauto.infra.result_cache import ResultCache
  from rfauto.infra.version_probe import resolve_aedt_install
  cache = ResultCache()
  aedt_version = "fake"
  if adapter_name == "hfss":
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if aedt_path and not Path(aedt_path).exists():
      return {"ok": False, "errors": [f"RFAUTO_AEDT_PATH 设置了但路径不存在: {aedt_path}"]}
    # 项目 B：版本探测收敛到 infra 层（显式路径优先，否则自动探测本机安装）
    install = resolve_aedt_install(aedt_path or None)
    if install is None:
      return {"ok": False, "errors": [
        "未找到可用 AEDT：RFAUTO_AEDT_PATH 未设置且自动探测未发现安装"
        "（可设 RFAUTO_AEDT_PATH=<AEDT 版本目录>，如 v231 安装根）"
      ]}
    aedt_version = install["aedt_version"]

  # 生产接线：内容寻址键 compute_content_key——13 成分分列
  # （recipe_version=配方 schema / schema_version=插件参数 schema，#106 不混）；
  # study/seed 显式不进键（#158），同几何异 study 命中同一条目并由 lookup 标
  # provenance="cache" + cross_study；miss 时 why_miss 给出失效原因。
  cache_components = cache.components_for_run(
    model_name=model_name,
    recipe_data=recipe_data,
    params_canonical_json=ps.to_canonical_json(),
    plugin_version=f"schema{plugin_cls.schema_version}",
    plugin_schema_version=plugin_cls.schema_version,
    adapter_version=adapter_name,
    aedt_version=aedt_version,
    export_contract=contract,
  )
  cache_key = cache.compute_content_key(**cache_components)
  cache_lookup = cache.lookup(
    cache_key, study=study, seed=seed, components=cache_components,
  )
  cached_dir = cache_lookup["path"]
  from_cache = False
  network = None
  if cached_dir is not None:
    try:
      import skrf
      s_files = sorted(Path(cached_dir).glob("params.s*p"))
      if s_files:
        network = skrf.Network(str(s_files[0]))
        from_cache = True
    except Exception:
      network = None
      from_cache = False # 缓存损坏则回退真实求解

  # 观测块（返回值与 meta 同源）：命中=cache；未命中/条目损坏回退真跑=computed
  cache_info: dict[str, Any] = {
    "key": cache_key,
    "provenance": "cache" if from_cache else "computed",
    "cross_study": bool(from_cache and cache_lookup["cross_study"]),
    "origin_study": cache_lookup["origin_study"] if from_cache else "",
    "origin_seed": cache_lookup["origin_seed"] if from_cache else "",
    "requester_study": study,
    "requester_seed": seed,
    "why_miss": [] if from_cache else list(cache_lookup["why_miss"]),
  }

  # 适配器：仅缓存未命中时创建、连接、构建
  adapter = None
  hfss_mode = False
  setup_name = "main_setup"
  if not from_cache:
    if adapter_name == "fake":
      from rfauto.adapters.fake_adapter import FakeAdapter
      adapter = FakeAdapter(n_ports=n_ports, model_type=plugin_cls.fake_model_type)
      adapter.connect({})
    else:
      from rfauto.adapters.hfss_adapter import HfssAdapter
      adapter = HfssAdapter()
      adapter.connect({"desktop_version": aedt_version, "non_graphical": True})
      design_name = recipe_data.get("design_name", "RFADesign")
      adapter.open_or_create_project(run_dir / "hfss" / "design.aedt", design_name)
      hfss_mode = True

    # 连接 + 构建 + 求解（构建/求解均带自愈编排：缺口 4）
    from rfauto.pipeline.self_heal import build_with_self_heal

    def _build():
      plugin.build(adapter, plugin.params_model(**{
        k: (v["value"] if isinstance(v, dict) else v) for k, v in params_data.items()
      }))
      ps.write_to_adapter(adapter, name_map=getattr(plugin_cls, "hfss_var_map", {}))

    build_with_self_heal(_build)

    # setup：hfss 模式按配方创建 Setup + Sweep；fake 模式用内置 main_setup
    if hfss_mode:
      setup_name = adapter.configure_setup(recipe_data.get("setup", {}))

  objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
  needs_far_field = any(o.metric == "gain_db" for o in objectives)

  report = None
  sparams_path = None
  far_field = None
  if from_cache:
    # 缓存命中：未建任何会话，直接用缓存网络计算指标
    metrics = SpecEvaluator.compute_metrics(network, objectives)
    cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
  else:
    # R5 自愈求解：掉线/健康检查失败时 ensure_connected 后重试一次
    from rfauto.pipeline.self_heal import solve_with_self_heal
    report = solve_with_self_heal(adapter, setup_name)
    if not report.success:      # 求解失败：不产出结果文件，登记后干净退出（勿让 export 异常穿透）
      meta = {
        "run_id": run_id,
        "package_version": __version__,
        "plugin_version": f"schema{plugin_cls.schema_version}",
        "schema_version": recipe_data.get("schema_version", 1),
        "adapter": adapter_name, "aedt_version": aedt_version, "ads_version": "n/a",
        "user": getpass.getuser(), "hostname": platform.node(),
        "model": model_name, "status": "solve_failed",
        "solve_message": report.message,
      }
      meta_path = write_meta(run_dir, meta)
      from rfauto.infra.run_store import record_run
      record_run(Path("runs") / "index.db", meta)
      # WP3.6 收尾钩子（best-effort，#105）：失败 run 的日志面最有诊断价值，
      # 蒸馏成 log_digest.json 供自愈环/MCP 消费；异常只记 warning 不阻断
      try:
        from rfauto.service.self_heal_service import write_log_digest_for_run
        write_log_digest_for_run(run_dir)
      except Exception as digest_exc: # pragma: no cover - 观测性兜底
        import logging as _logging
        _logging.getLogger(__name__).warning("log_digest 钩子失败（非阻断）: %s", digest_exc)
      adapter.close()
      return {
        "ok": False,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "errors": [f"求解失败: {report.message}"],
      }

    # 导出 Touchstone（扩展名按端口数, 避免 skrf 回读混淆）。
    # HfssAdapter 可能按实际端口数修正扩展名，以返回的真实路径为准
    # （缓存写回与后续读取都应用真实路径）。
    sparams_path = run_dir / "results" / f"params.s{len(contract.touchstone.port_order)}p"
    sparams_path.parent.mkdir(parents=True, exist_ok=True)
    sparams_path = Path(adapter.export_touchstone(sparams_path, contract))

    # 计算指标（gain_db 目标时先取远场数据——远场指标进 DSL，清理项）
    network = adapter.get_sparams()
    if needs_far_field:
      with contextlib.suppress(Exception):
        far_field = adapter.get_far_field(setup_name)
    metrics = SpecEvaluator.compute_metrics(network, objectives, far_field=far_field)
    cost = SpecEvaluator.evaluate_objectives(metrics, objectives)

  # 物理合理性校验（§7.5 两级校验的第二级，C5 接线：非阻断，结果落
  # metrics.json 的 checks 段；原先 sanity_check 定义后从未被调用）
  f0_candidate = params_data.get("f0_ghz", {})
  f0_ghz = (
    f0_candidate.get("value") if isinstance(f0_candidate, dict) else f0_candidate
  ) if f0_candidate else None
  sanity = SpecEvaluator.sanity_check(network, objectives, f0_ghz=f0_ghz)

  # 知识库诊断（孤岛接线）：出指标后自动诊断，结果落 metrics.json 与报告。
  # 非阻断：诊断引擎任何异常不影响主流程
  diagnosis: dict[str, Any] | None = None
  try:
    from rfauto.infra.diagnosis import diagnose_results
    diagnosis = diagnose_results(
      metrics,
      model_name=model_name,
      objectives=[o.model_dump() for o in objectives],
    )
  except Exception as diag_exc: # pragma: no cover - 防御性
    import logging as _logging
    _logging.getLogger(__name__).warning("诊断引擎失败（非阻断）: %s", diag_exc)
    diagnosis = None

  # 保存 metrics.json
  metrics_data = {
    "run_id": run_id,
    "plugin_version": f"schema{plugin_cls.schema_version}",
    "schema_version": recipe_data.get("schema_version", 1),
    "params": {k: (v["value"] if isinstance(v, dict) else v) for k, v in params_data.items()},
    "metrics": metrics,
    "cost": cost,
    "checks": {
      "passivity_ok": SpecEvaluator.check_passivity(network),
      "reciprocity_ok": SpecEvaluator.check_reciprocity(network),
      "sanity_all_ok": sanity.all_ok,
      "sanity_notes": sanity.notes,
    },
    "diagnosis": diagnosis,
  }
  metrics_path = run_dir / "results" / "metrics.json"
  metrics_path.write_text(json.dumps(metrics_data, indent=2, ensure_ascii=False), encoding="utf-8")

  # 缓存写回（仅真实求解路径；RFAUTO_CACHE!=readwrite 时 store 为空操作）。
  # components/study/seed 入 manifest：前者供 why_miss 比对，后者供跨 study
  # provenance（#158）——均不参与键。
  if not from_cache and sparams_path is not None:
    # 缓存写入失败不影响主流程
    with contextlib.suppress(Exception):
      cache.store(
        cache_key, run_dir / "results", sparams_path, metrics_path,
        model_name=model_name, study=study, seed=seed,
        components=cache_components,
      )

  # 生成 S 参数图 + report.md（P0 验收项："全链路出 S 参数图"）
  import numpy as np

  from rfauto.infra.report import generate_report

  freqs_ghz = np.asarray(network.f, dtype=float) / 1e9
  freq_data: dict[str, Any] = {"freqs": freqs_ghz.tolist()}
  freq_data["s11_db"] = (20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-15)).tolist()
  if network.s.shape[1] >= 2:
    freq_data["s21_db"] = (20.0 * np.log10(np.abs(network.s[:, 1, 0]) + 1e-15)).tolist()

  obj_specs = {
    o.metric: {"target": f"{o.op} {o.value}", "band": list(o.band)}
    for o in objectives
  }
  report_path = generate_report(
    run_dir,
    metrics,
    objectives=obj_specs,
    freq_data=freq_data,
    diagnosis=diagnosis,
  )

  # 写 meta + 登记 SQLite 索引（runs 历史不进 git，SQLite 是唯一运行索引）。
  # git_sha 不在此覆写（C5 修复：原先传 "" 覆盖 write_meta 算出的真实值，
  # replay 的版本一致性告警因此永不触发）
  from rfauto.infra.run_store import record_run
  meta_path = write_meta(run_dir, {
    "run_id": run_id,
    "package_version": __version__,
    "plugin_version": f"schema{plugin_cls.schema_version}",
    "schema_version": recipe_data.get("schema_version", 1),
    "adapter": adapter_name,
    "aedt_version": aedt_version,
    "ads_version": "n/a",
    "user": getpass.getuser(),
    "hostname": platform.node(),
    "model": model_name,
    "status": "done",
    "from_cache": from_cache,
    "cache": cache_info,
    "metrics": metrics,
  })
  meta = json.loads(meta_path.read_text(encoding="utf-8"))
  record_run(Path("runs") / "index.db", meta)

  # WP3.6 收尾钩子（best-effort，#105）：run 落盘后把日志面蒸馏成
  # runs/<id>/log_digest.json 供自愈环/MCP/UI 消费；异常只记 warning 不阻断
  try:
    from rfauto.service.self_heal_service import write_log_digest_for_run
    write_log_digest_for_run(run_dir)
  except Exception as digest_exc: # pragma: no cover - 观测性兜底
    import logging as _logging
    _logging.getLogger(__name__).warning("log_digest 钩子失败（非阻断）: %s", digest_exc)

  if adapter is not None:
    adapter.close()

  return {
    "ok": True,
    "run_id": run_id,
    "run_dir": str(run_dir),
    "metrics": metrics,
    "cost": cost,
    "from_cache": from_cache,
    "cache": cache_info,
    "solve_report": (
      {"success": True, "passes": 0, "delta_s_final": 0.0}
      if from_cache
      else {
        "success": report.success,
        "passes": report.passes,
        "delta_s_final": report.delta_s_final,
      }
    ),
    "report": str(report_path),
  }


def agent_propose(
  recipe_path: str | Path,
  params_override: dict[str, Any] | None = None,
  *,
  adapter_name: str = "fake",
) -> dict[str, Any]:
  """Agent 提案（E4b 编排闭环）：L1 白名单 + L2 dry-run + L3 确认 token。

  只 propose 不 apply。返回的 token 是 L1/L2 结果的派生哈希——
  apply 时必须原样带回，参数在 propose 后被篡改会因哈希不符被拒。
  """
  validation = validate_recipe(recipe_path)
  if not validation["ok"]:
    return {"ok": False, "stage": "validate", "errors": validation["errors"]}

  import yaml
  with open(recipe_path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)

  params_override = params_override or {}
  from rfauto.service.agent_gate import AgentGate

  gate = AgentGate()
  l1 = gate.check_l1(params_override, recipe_data)
  if not l1.passed:
    # 否决原因分类落审计（4b 质量指标数据源）
    from rfauto.service.agent_safety import append_audit_log
    append_audit_log({
      "event": "propose",
      "ok": False,
      "stage": "L1",
      "recipe": str(recipe_path),
      "reason": l1.details.get("violations", []),
    })
    return {"ok": False, "stage": "L1", "gate": l1.to_dict()}

  l2 = gate.check_l2(params_override, recipe_data)
  if not l2.passed:
    from rfauto.service.agent_safety import append_audit_log
    append_audit_log({
      "event": "propose",
      "ok": False,
      "stage": "L2",
      "recipe": str(recipe_path),
      "reason": l2.details["issues"],
    })
    return {"ok": False, "stage": "L2", "gate": l2.to_dict()}

  l3 = gate.check_l3(l1, l2, params_override)

  plan = dry_run(recipe_path, adapter_name=adapter_name)

  # ADR-0025：写操作 diff 预览 + 审批日志（token 只记哈希）
  from rfauto.service.agent_safety import append_audit_log, preview_write_diff, token_hash
  write_diff = preview_write_diff(recipe_path, params_override)
  append_audit_log({
    "event": "propose",
    "ok": True,
    "recipe": str(recipe_path),
    "params": params_override,
    "adapter": adapter_name,
    "token_hash": token_hash(l3.token),
    "write_diff": write_diff["create"],
  })
  return {
    "ok": True,
    "stage": "L3",
    "token": l3.token,
    "effective_params": {
      k: (v.get("value") if isinstance(v, dict) else v)
      for k, v in {**recipe_data.get("params", {}), **params_override}.items()
    },
    "plan": plan,
    "write_diff": write_diff,
    "message": "提案就绪：人工/编排确认后带 token 调 agent_apply 真实执行",
  }


def agent_apply(
  recipe_path: str | Path,
  token: str,
  params_override: dict[str, Any] | None = None,
  *,
  adapter_name: str = "fake",
) -> dict[str, Any]:
  """Agent 执行（E4b 编排闭环）：校验 propose 发放的 token 后真实 run。

  token 由 propose 时的 L1/L2 结果哈希派生；params_override 必须与
  propose 时一致，否则哈希不匹配直接拒绝（防 LLM 篡改重放）。
  """
  import yaml
  with open(recipe_path, encoding="utf-8") as f:
    recipe_data = yaml.safe_load(f)

  params_override = params_override or {}
  from rfauto.service.agent_gate import AgentGate

  gate = AgentGate()
  l1 = gate.check_l1(params_override, recipe_data)
  l2 = gate.check_l2(params_override, recipe_data)
  if not gate.validate_token(token, l1, l2, params_override):
    from rfauto.service.agent_safety import append_audit_log, token_hash
    append_audit_log({
      "event": "apply",
      "ok": False,
      "stage": "L3",
      "recipe": str(recipe_path),
      "token_hash": token_hash(token),
      "reason": "token 校验失败：参数与 propose 时不一致或 token 无效",
    })
    return {
      "ok": False,
      "stage": "L3",
      "errors": ["token 校验失败：参数与 propose 时不一致或 token 无效，"
            "请重新 agent_propose"],
    }

  # 合并参数生成提案配方，落到独立目录（不覆盖原始配方）
  merged = dict(recipe_data)
  merged_params = dict(recipe_data.get("params", {}))
  for k, v in params_override.items():
    merged_params[k] = {"value": v} if not isinstance(v, dict) else v
  merged["params"] = merged_params

  # ADR-0025：写路径白名单 + 审批日志（token 只记哈希）
  import hashlib as _hashlib
  import json as _json

  from rfauto.service.agent_safety import (
    append_audit_log,
    check_write_paths,
    token_hash,
  )

  proposal_dir = Path("runs") / "agent_proposals"
  proposal_dir.mkdir(parents=True, exist_ok=True)
  recipe_sha = _hashlib.sha256(
    _json.dumps(merged, sort_keys=True, default=str).encode()
  ).hexdigest()[:12]
  proposal_path = proposal_dir / f"proposal_{recipe_sha}.yaml"

  write_guard = check_write_paths([proposal_path], recipe_path)
  if not write_guard["ok"]:
    append_audit_log({
      "event": "apply",
      "ok": False,
      "stage": "write_guard",
      "recipe": str(recipe_path),
      "token_hash": token_hash(token),
      "violations": write_guard["violations"],
    })
    return {
      "ok": False,
      "stage": "write_guard",
      "errors": [f"写路径越出白名单: {p}" for p in write_guard["violations"]],
    }

  # 提案落 runs/agent_proposals/（白名单已由 check_write_paths 钉住；再经
  # recipe_guard 统一出口——受保护 recipes/ 目标缺省抛 RecipeWriteForbidden）
  from rfauto.infra.recipe_guard import write_recipe_yaml

  write_recipe_yaml(proposal_path, merged)

  result = run_once(proposal_path, adapter_name=adapter_name)

  # 4b 质量指标（历史审查补强）：改进率 = (基线 cost - 提案 cost)/基线 cost。
  # 基线复算仅 fake 档执行（真机档不双跑烧 license，指标记 None——
  # 宁可 unknown 也不阻塞主路径，#105 原则）。
  quality: dict[str, Any] = {"proposal_cost": result.get("cost"), "baseline_cost": None,
                "improvement": None}
  if adapter_name == "fake" and result.get("ok"):
    try:
      baseline = run_once(recipe_path, adapter_name="fake")
      quality["baseline_cost"] = baseline.get("cost")
      pc, bc = result.get("cost"), baseline.get("cost")
      if isinstance(pc, (int, float)) and isinstance(bc, (int, float)):
        # 分母为零的语义：基线已完全满足规格（cost=0）时，改进量按
        # 相对 1.0 计（提案也为 0 → 0.0；提案 > 0 → 负改进）
        denom = abs(bc) if abs(bc) > 1e-12 else 1.0
        quality["improvement"] = round((bc - pc) / denom, 4)
    except Exception:
      pass

  append_audit_log({
    "event": "apply",
    "ok": bool(result.get("ok")),
    "recipe": str(recipe_path),
    "proposal_recipe": str(proposal_path),
    "params": params_override,
    "adapter": adapter_name,
    "token_hash": token_hash(token),
    "run_id": result.get("run_id"),
    "quality": quality,
  })
  return dict(
    result,
    proposal_recipe=str(proposal_path),
    agent_gate="L1+L2+L3",
    write_guard=write_guard,
    quality=quality,
  )


def correlate_files(
  sim_file: str | Path,
  measured_file: str | Path,
  *,
  threshold_db: float = 3.0,
) -> dict[str, Any]:
  """仿真 vs 测量相关性分析（E9c 的 CLI 可达入口；MCP correlate_measurement 同源）。"""
  from rfauto.measurement.correlate import compute_correlation
  from rfauto.measurement.import_data import import_touchstone

  sim = import_touchstone(str(sim_file))
  measured = import_touchstone(str(measured_file))
  result = compute_correlation(sim, measured, threshold_db)
  return {"ok": True, "data": result.to_dict()}


def vna_offline_replay(
  measured_s2p: str | Path,
  sim_s2p: str | Path | None = None,
  *,
  threshold_db: float = 3.0,
  session_path: str | Path | None = None,
) -> dict[str, Any]:
  """VNA 软侧离线回放（透传）：mock 仪表采集→校准→相关全链，零硬件。

  measurement.vna_capture.run_offline_replay 的 service 面透传（JSON 进出）：
  历史 Touchstone 供数 MockVNAInstrument → capture → 与 sim_s2p（缺省=同文件）
  compute_correlation（dB 偏差门 + D12 FSV）。校准套件（CalibrationKit 对象）
  不走 JSON 入口，本透传固定 calkit=None（原样比对）。
  """
  from rfauto.measurement.vna_capture import run_offline_replay

  measured = Path(measured_s2p)
  if not measured.exists():
    return {"ok": False, "errors": [f"测量文件不存在: {measured}"]}
  if sim_s2p is not None and not Path(sim_s2p).exists():
    return {"ok": False, "errors": [f"仿真文件不存在: {sim_s2p}"]}
  return run_offline_replay(
    measured, sim_s2p, threshold_db=threshold_db, session_path=session_path)


def analyze_surrogate(
  run_id: str | None = None,
  *,
  study_name: str | None = None,
) -> dict[str, Any]:
  """离线 GP 代理模型分析（E3 的 CLI 可达入口）。

  trials 来源：runs/.optuna/optuna.db 的指定 study（study_name 缺省时
  从 run_id 的 meta.json 反查）；无 optuna trial 时报错（不伪造数据）。
  """
  if not study_name and run_id:
    meta_path = Path("runs") / run_id / "meta.json"
    if meta_path.exists():
      meta = json.loads(meta_path.read_text(encoding="utf-8"))
      study_name = meta.get("study_name")
  if not study_name:
    return {"ok": False, "errors": [
      "需要 study_name（--study）或能反查 study 的 run_id"
    ]}

  import optuna

  from rfauto.optimization.optimizer import get_storage_path

  try:
    study = optuna.load_study(
      study_name=study_name, storage=get_storage_path(),
    )
  except Exception as e:
    return {"ok": False, "errors": [f"加载 study 失败: {e}"]}

  trials_data = []
  for t in study.trials:
    if t.value is None:
      continue
    trials_data.append({"params": t.params, "cost": float(t.value)})

  if len(trials_data) < 3:
    return {"ok": False, "errors": [
      f"study '{study_name}' 只有 {len(trials_data)} 个有效 trial，"
      "代理模型分析至少需要 3 个"
    ]}

  from rfauto.optimization.surrogate_analysis import analyze_run_surrogate

  result = analyze_run_surrogate(run_id or study_name, trials_data)
  return {"ok": True, "data": result.to_dict()}


def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
  """对比两次 run 的指标（MCP compare_runs 的服务入口）。"""
  a = get_metrics(run_id_a)
  b = get_metrics(run_id_b)
  errors = [
    f"run {rid} 无指标" for rid, r in (("A", a), ("B", b)) if not r.get("ok")
  ]
  if errors:
    return {"ok": False, "errors": errors}

  ma = a["data"].get("metrics", {})
  mb = b["data"].get("metrics", {})
  keys = sorted(set(ma) | set(mb))
  delta = {}
  for k in keys:
    va, vb = ma.get(k), mb.get(k)
    delta[k] = (
      {"a": va, "b": vb, "delta": vb - va}
      if isinstance(va, (int, float)) and isinstance(vb, (int, float))
      else {"a": va, "b": vb, "delta": None}
    )
  return {
    "ok": True,
    "data": {
      "run_a": run_id_a,
      "run_b": run_id_b,
      "metrics": delta,
      "cost_a": a["data"].get("cost"),
      "cost_b": b["data"].get("cost"),
    },
  }


def start_tune(recipe_path: str | Path, *, adapter_name: str = "fake",
        max_trials: int = 60, study_name: str | None = None,
        max_wall_s: float | None = None,
        adapter_kwargs: dict[str, Any] | None = None,
        sampler: str = "tpe",
        seed: int | None = None) -> dict[str, Any]:
  """启动优化外环（Optuna，SQLite 持久化，断点续跑）。

  同步运行优化循环，返回最佳结果。
  若同一 study_name 已有历史 trial，自动从已有结果继续采样。

  Args:
    recipe_path: 配方文件路径
    adapter_name: "fake" | "hfss"
    max_trials: 最大试验次数
    study_name: 自定义 study 名称（默认从配方生成）
    max_wall_s: 总超时秒数
    adapter_kwargs: 额外适配器构造参数（如 n_ports=3）
    sampler: "tpe"（默认）| "cmaes"（缺口 5）
    seed: 采样器随机种子（None=沿用 optimizer.SAMPLER_SEED 缺省）
  """
  from rfauto.optimization.optimizer import run_optimization
  seed_kw: dict[str, Any] = {} if seed is None else {"seed": int(seed)}
  result = run_optimization(
    recipe_path,
    adapter_name=adapter_name,
    max_trials=max_trials,
    study_name=study_name,
    max_wall_s=max_wall_s,
    adapter_kwargs=adapter_kwargs,
    sampler=sampler,
    **seed_kw,
  )
  if not result.get("ok"):
    return result
  return {
    "ok": True,
    "job_id": result.get("run_id", ""),
    "run_id": result.get("run_id", ""),
    "study_name": result.get("study_name", ""),
    "best_params": result.get("best_params", {}),
    "best_cost": result.get("best_cost"),
    "best_metrics": result.get("best_metrics", {}),
    "trials_completed": result.get("trials_completed", 0),
    "trials_pruned": result.get("trials_pruned", 0),
    "trials_total": result.get("trials_total", 0),
    "elapsed_s": result.get("elapsed_s", 0),
    "existing_trials": result.get("existing_trials", 0),
  }




def start_tune_multi(
  recipe_path: str | Path,
  *,
  adapter_name: str = "fake",
  n_gen: int = 20,
  pop_size: int = 12,
  seed: int = 42,
) -> dict[str, Any]:
  """多目标优化（NSGA-II，Pareto 前沿）——计划内缺口 2 的服务入口。

  验收口径："双目标出 Pareto 前沿"。目标向量取每个 objective 的违约量。
  """
  from rfauto.optimization.optimizer import run_multi_optimization
  return run_multi_optimization(
    recipe_path,
    adapter_name=adapter_name,
    n_gen=n_gen,
    pop_size=pop_size,
    seed=seed,
  )




def run_once_async(recipe_path: str | Path, *, adapter_name: str = "fake") -> dict[str, Any]:
  """异步单次仿真——立即返回 job_id，后台执行。

  与 run_once 相同逻辑，后台线程执行；适用于 HFSS 等长时间仿真。
  job_id（job_ 前缀）由进程内 JobRegistry 关联到后台任务的真实 run_id，
  poll_job 优先查注册表、未命中回落磁盘 meta.json。

  线程为非 daemon：进程退出前会等待当前 run 结束，避免带着 AEDT 会话
  被强杀（代价是异常卡死的 run 会阻塞进程退出，可接受）。

  Args:
    recipe_path: 配方文件路径
    adapter_name: "fake" 或 "hfss"

  Returns:
    dict with keys: ok, job_id, state
  """
  import threading

  from rfauto.service.job_registry import get_job_registry, get_write_lock

  registry = get_job_registry()
  write_lock = get_write_lock()
  job_id = generate_job_id()

  def _run_in_background():
    import traceback
    try:
      # 单写锁（缺口 1）：并发 hfss job 在此排队，避免同时开多个
      # AEDT 会话抢 license。无限等待（求解本身可达小时级）。
      if not write_lock.acquire(job_id):
        registry.fail(job_id, error="未获得执行锁（单写互斥）")
        return
      try:
        # jobs cancel 语义：获锁后（真正开始执行前）检查取消——
        # 排队中的 job 在 cancel() 时已置 cancelled 终态，这里直接跳过
        if not registry.mark_started(job_id):
          return
        result = run_once(recipe_path, adapter_name=adapter_name)
      finally:
        write_lock.release(job_id)
      run_id = result.get("run_id", "")
      if registry.is_cancelled(job_id):
        # 执行中收到取消：AEDT 求解不可安全中断，跑完后按取消丢弃结果
        registry.mark_cancelled(job_id, run_id=run_id)
        return
      if result.get("ok"):
        registry.finish(job_id, run_id=run_id, result=result)
      else:
        registry.fail(job_id, run_id=run_id, result=result)
    except Exception as e:
      # 后台线程的异常无处抛出，必须带堆栈完整落进注册表供排查
      write_lock.release(job_id)
      registry.fail(job_id, error=f"{e}\n{traceback.format_exc()}")

  thread = threading.Thread(target=_run_in_background, daemon=False, name=f"rfauto-job-{job_id}")
  registry.create(job_id, thread=thread)
  thread.start()

  return {
    "ok": True,
    "job_id": job_id,
    "state": "running",
    "message": "仿真已在后台启动，使用 poll_job 查询状态",
  }


def poll_job(job_id: str) -> dict[str, Any]:
  """轮询任务状态。

  查询顺序：
  1. 进程内 JobRegistry（run_once_async 发放的 job_id，状态实时）
  2. 磁盘 runs/<job_id>/meta.json（直接以 run_id 查询历史 run，含跨进程）
  均未命中时返回 state=unknown（ok 仍为 True，与历史行为兼容）。
  """
  from rfauto.service.job_registry import get_job_registry

  job = get_job_registry().get(job_id)
  if job is not None:
    state = job["state"]
    result = job.get("result") or {}
    terminal = state in ("done", "failed", "cancelled")
    message = {
      "failed": job.get("error", ""),
      "cancelled": "任务已取消",
    }.get(state, f"job 状态: {state}")
    return {
      "ok": True,
      "job_id": job_id,
      "run_id": job.get("run_id", ""),
      "state": state,
      "progress_pct": 100.0 if terminal else 0.0,
      "message": message,
      "metrics": result.get("metrics", {}),
    }

  meta_path = Path("runs") / job_id / "meta.json"
  if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return {
      "ok": True,
      "job_id": job_id,
      "state": meta.get("status", "unknown"),
      "progress_pct": 100.0 if meta.get("status") == "done" else 0.0,
      "message": f"优化完成 ({meta.get('study_name', '')})",
      "metrics": meta.get("metrics", {}),
    }
  return {
    "ok": True,
    "job_id": job_id,
    "state": "unknown",
    "progress_pct": 0.0,
    "message": f"未找到 run: {job_id}",
  }


def replay_run(run_id: str) -> dict[str, Any]:
  """复现任一次 run：用其 recipe 快照重跑，并核对 plugin/schema 版本。

  P1 实现（验收项："rfauto replay 可复现任一次（含 plugin/schema 版本核对）"）。
  """
  run_dir = Path("runs") / run_id
  meta_path = run_dir / "meta.json"
  snapshot = run_dir / "recipe.snapshot.yaml"
  errors: list[str] = []
  if not meta_path.exists():
    errors.append(f"未找到 run: {run_id}（缺少 {meta_path}）")
  if not snapshot.exists():
    errors.append(f"缺少配方快照: {snapshot}")
  if errors:
    return {"ok": False, "errors": errors}

  meta = json.loads(meta_path.read_text(encoding="utf-8"))

  # 版本核对：plugin/schema 与当前注册的模型不一致时显式报错
  import yaml
  with open(snapshot, encoding="utf-8") as f:
    snap_data = yaml.safe_load(f)
  model_name = snap_data.get("model", "")
  try:
    from rfauto.models.registry import get as get_plugin_cls
    get_plugin_cls(model_name) # 存在性核对
  except KeyError:
    return {"ok": False, "errors": [f"快照中的模型 '{model_name}' 当前未注册"]}

  warnings: list[str] = []
  # schema 版本核对：meta 与快照不一致时降级为 warning（快照重跑仍忠实于源 run 配方）
  if "schema_version" in snap_data and str(meta.get("schema_version")) != str(snap_data["schema_version"]):
    warnings.append(
      f"schema 版本不一致: meta={meta.get('schema_version')}, 快照={snap_data['schema_version']}"
    )
  # git SHA 核对：不一致只提示（完整环境复现留给 P2 golden 回归）
  current_sha = ""
  try:
    import subprocess
    current_sha = subprocess.check_output(
      ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
    ).strip()
  except Exception:
    pass
  recorded_sha = meta.get("git_sha", "")
  if recorded_sha and current_sha and recorded_sha != current_sha:
    warnings.append(
      f"git 版本不一致: run 记录于 {recorded_sha}, 当前 HEAD 为 {current_sha}（复现结果可能有差异）"
    )

  # 用快照重跑（run_once 内部会创建新的 run 目录并再次快照）
  adapter_name = meta.get("adapter", "fake")
  result = run_once(snapshot, adapter_name=adapter_name)

  return {
    "ok": result.get("ok", False),
    "source_run_id": run_id,
    "replay_run_id": result.get("run_id"),
    "version_warnings": warnings,
    "result": result,
  }


def get_metrics(run_id: str) -> dict[str, Any]:
  """读取某次 run 的指标。"""
  metrics_path = Path("runs") / run_id / "results" / "metrics.json"
  if not metrics_path.exists():
    return {"ok": False, "errors": [f"未找到 run: {run_id}"]}
  data = json.loads(metrics_path.read_text(encoding="utf-8"))
  return {"ok": True, "data": data}


def generate_report_for_run(
  run_id: str,
  *,
  fmt: str = "markdown",
  output: str | Path | None = None,
) -> dict[str, Any]:
  """按已完成的 run 重建报告（缺口 8：CLI report 命令此前是 stub）。

  读取 runs/<run_id>/results/metrics.json 重新生成 report.md / report.html；
  output 指定输出文件时写入该路径。S 参数曲线图不重绘（结果文件已在）。
  """
  run_dir = Path("runs") / run_id
  metrics_path = run_dir / "results" / "metrics.json"
  if not metrics_path.exists():
    return {"ok": False, "errors": [f"未找到 run 指标: {metrics_path}"]}

  data = json.loads(metrics_path.read_text(encoding="utf-8"))

  # 尽量从结果目录的 Touchstone 重建 S 参数曲线（报告含图，不丢历史信息）
  freq_data = None
  try:
    import numpy as np
    import skrf

    s_files = sorted((run_dir / "results").glob("params.s*p"))
    if s_files:
      network = skrf.Network(str(s_files[0]))
      freqs_ghz = np.asarray(network.f, dtype=float) / 1e9
      freq_data = {"freqs": freqs_ghz.tolist()}
      freq_data["s11_db"] = (20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-15)).tolist()
      if network.s.shape[1] >= 2:
        freq_data["s21_db"] = (
          20.0 * np.log10(np.abs(network.s[:, 1, 0]) + 1e-15)
        ).tolist()
  except Exception:
    freq_data = None

  from rfauto.infra.report import generate_report

  dest_dir = Path(output).parent if output else run_dir
  dest_dir.mkdir(parents=True, exist_ok=True)
  # generate_report 以 run_dir 为根放置 report.md/html；指定 output 时
  # 用临时改写目标的方式最简：生成后移动
  report_path = generate_report(
    run_dir, data.get("metrics", {}), format=fmt, freq_data=freq_data,
  )
  if output and Path(report_path) != Path(output):
    Path(report_path).replace(output)
    report_path = Path(output)
  return {
    "ok": True,
    "run_id": run_id,
    "format": fmt,
    "report": str(report_path),
    "metrics": data.get("metrics", {}),
  }


def run_tolerance(
  recipe_path: str | Path,
  *,
  adapter_name: str = "fake",
  n_samples: int = 200,
) -> dict[str, Any]:
  """公差分析（孤岛接线）——`rfauto tolerance <recipe>` 服务入口。

  以 objectives 为规格、tolerance.tolerances 为公差，Monte Carlo 出良率。
  """
  from rfauto.optimization.optimizer import run_tolerance_analysis
  return run_tolerance_analysis(
    recipe_path, adapter_name=adapter_name, n_samples=n_samples,
  )


def list_models() -> dict[str, Any]:
  """列出已注册的模型插件。"""
  from rfauto.models.registry import list_models as _list_models
  return {"ok": True, "models": _list_models()}


def doctor() -> dict[str, Any]:
  """环境探测：AEDT/ADS 版本、license、路径、已测试版本组合核对。"""
  from rfauto.infra.config import doctor_check, load_settings
  settings = load_settings()
  raw = doctor_check(settings)

  checks = []
  # Python 版本
  import sys
  py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
  checks.append({"name": "Python", "status": "ok", "detail": py_ver})

  # AEDT
  aedt = raw.get("aedt", {})
  if aedt.get("exists"):
    from rfauto.infra.version_probe import compat_level
    level = compat_level("aedt", aedt.get("version", ""))
    checks.append({
      "name": "AEDT",
      "status": "ok",
      "detail": f"{aedt.get('path', '')}（版本 {aedt.get('version', '?')}，{level}）",
    })
  elif aedt.get("note") == "not configured":
    # 项目 B：未显式配置时自动探测本机安装
    from rfauto.infra.version_probe import compat_level, detect_aedt_versions
    detected = detect_aedt_versions()
    if detected:
      for inst in detected[:3]:
        level = compat_level("aedt", inst["aedt_version"])
        checks.append({
          "name": "AEDT（自动发现）",
          "status": "ok",
          "detail": f"{inst['path']}（版本 {inst['aedt_version']}，{level}，来源 {inst['source']}）",
        })
    else:
      checks.append({"name": "AEDT", "status": "未配置",
              "detail": "设置 RFAUTO_AEDT_PATH 或编辑 configs/settings.yaml；自动探测未发现安装"})
  else:
    checks.append({"name": "AEDT", "status": "缺失", "detail": f"路径不存在: {aedt.get('path', '')}"})

  # ADS
  ads = raw.get("ads", {})
  if ads.get("exists"):
    from rfauto.infra.version_probe import compat_level, detect_ads_version
    ads_version = detect_ads_version(ads.get("path", "")) or "?"
    level = compat_level("ads", ads_version)
    checks.append({
      "name": "ADS",
      "status": "ok",
      "detail": f"{ads.get('path', '')}（版本 {ads_version}，{level}）",
    })
  elif ads.get("note") == "not configured":
    checks.append({"name": "ADS", "status": "未配置", "detail": "设置 RFAUTO_HPEESOF_DIR 或编辑 configs/settings.yaml"})
  else:
    checks.append({"name": "ADS", "status": "缺失", "detail": f"路径不存在: {ads.get('path', '')}"})

  # 缓存模式
  checks.append({"name": "缓存模式", "status": "ok", "detail": settings.cache_mode})

  return {"ok": raw.get("ok", True), "checks": checks}


def run_link(
  run_id: str,
  *,
  rounds: int = 2,
  ads_dir: str | Path | None = None,
) -> dict[str, Any]:
  """把某次 HFSS 运行送入 ADS 联动链路（P3, ADR-0003, N=2 往返）。

  定位 runs/<run_id>/results 下的 Touchstone -> AdsExchangeContract ->
  HfssAdsLink.run_from_snp(二阶段 N 轮)。B 档受阻自动落 C 档保底。
  """
  run_dir = Path("runs") / run_id
  if not run_dir.exists():
    return {"ok": False, "errors": [f"run 不存在: {run_id}"]}

  results_dir = run_dir / "results"
  snp_candidates = sorted(results_dir.glob("params.s*")) if results_dir.exists() else []
  if not snp_candidates:
    return {"ok": False, "errors": [f"run 未找到 Touchstone 结果: {run_id}"]}
  snp_path = snp_candidates[0]

  contract = AdsExchangeContract()

  # 项目 A：通道选择（审计信息；实际仿真仍由 HfssAdsLink 默认 B 档执行，
  # B 档受阻时其内建 C 档保底。M/A 档按 prefer 显式启用）
  from rfauto.linkage.ads_channel import select_ads_channel

  channel_selection = select_ads_channel(ads_dir)
  if channel_selection.get("ok") and channel_selection.get("channel") == "c":
    channel_selection["note"] = "仅 C 档可用：B 档 hpeesofsim 缺失，联运将以人工保底结束"

  from rfauto.linkage.hfss_ads_link import HfssAdsLink
  ads_out = run_dir / "ads"
  link = HfssAdsLink(output_dir=ads_out, ads_dir=ads_dir)
  summary = link.run_from_snp(snp_path, contract, rounds=rounds)
  return {
    "ok": True,
    "run_id": run_id,
    "snp_path": str(snp_path),
    "ads_channel": channel_selection,
    "rounds_completed": summary["rounds_completed"],
    "summary": summary,
  }



# ─── recipe migrate（方向 7：配方版本化）────────────────────────────────────────

_CURRENT_RECIPE_VERSION = 1


def recipe_migrate(recipe_path: str | Path) -> dict[str, Any]:
  """Migrate a recipe to the current recipe_version.

  方向 7 验收口径：recipe migrate 有新旧 schema 双向测试。
  - version 0 (missing recipe_version) → adds recipe_version: 1
  - version 1 → no-op (already current)
  - unknown version → error

  Returns: {ok, recipe_path, from_version, to_version, changed}
  """
  import yaml

  path = Path(recipe_path)
  if not path.exists():
    return {"ok": False, "errors": [f"配方文件不存在: {path}"]}

  with open(path, encoding="utf-8") as f:
    data = yaml.safe_load(f)
  if not isinstance(data, dict):
    return {"ok": False, "errors": ["配方顶层必须是映射"]}

  current_ver = data.get("recipe_version", 0)

  if current_ver == _CURRENT_RECIPE_VERSION:
    return {
      "ok": True,
      "recipe_path": str(path),
      "from_version": current_ver,
      "to_version": current_ver,
      "changed": False,
      "message": f"配方已是最新版本 (v{current_ver})",
    }

  if current_ver > _CURRENT_RECIPE_VERSION:
    return {
      "ok": False,
      "errors": [f"配方版本 {current_ver} 高于当前支持的版本 {_CURRENT_RECIPE_VERSION}"],
    }

  # version 0 → 1: add recipe_version field
  # 写面守卫：`rfauto recipe migrate <path>` 是用户把目标路径作为命令本意的
  # 显式入口（explicit），允许原地升级 recipes/ 下的配方；其余库代码路径
  # 一律不得改写 recipes/ 原件（infra.recipe_guard）。
  from rfauto.infra.recipe_guard import write_recipe_text

  data["recipe_version"] = _CURRENT_RECIPE_VERSION
  write_recipe_text(
    path,
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
    explicit=True,
  )
  return {
    "ok": True,
    "recipe_path": str(path),
    "from_version": current_ver,
    "to_version": _CURRENT_RECIPE_VERSION,
    "changed": True,
    "message": f"配方已从 v{current_ver} 升级到 v{_CURRENT_RECIPE_VERSION}",
  }


# ─── repro export（方向 7：可复现性）────────────────────────────────────────────

def repro_export(run_id: str, output_dir: str | Path | None = None) -> dict[str, Any]:
  """Export a reproducibility package for a completed run.

  方向 7 验收口径：任一历史 run 的 repro 包在干净 venv 中重建并跑通
  fake 档重放。

  Exports to <output_dir>/<run_id>_repro/:
   - recipe.snapshot.yaml (final recipe)
   - meta.json       (full provenance)
   - sparams/       (Touchstone files)
   - reproduce.py     (one-click replay script)
   - provenance.json    (environment fingerprint)

  Returns: {ok, output_dir, files, message}
  """
  run_dir = Path("runs") / run_id
  if not run_dir.is_dir():
    return {"ok": False, "errors": [f"run 不存在: {run_id}"]}

  meta_path = run_dir / "meta.json"
  snapshot_path = run_dir / "recipe.snapshot.yaml"
  if not meta_path.exists():
    return {"ok": False, "errors": [f"run 缺少 meta.json: {run_id}"]}

  # Output directory
  out_base = Path(output_dir) if output_dir else Path("runs") / "repro"
  out_dir = out_base / f"{run_id}_repro"
  out_dir.mkdir(parents=True, exist_ok=True)

  files: list[str] = []

  # 1. Copy recipe snapshot
  if snapshot_path.exists():
    import shutil
    dest = out_dir / "recipe.snapshot.yaml"
    shutil.copy2(snapshot_path, dest)
    files.append("recipe.snapshot.yaml")
  else:
    return {"ok": False, "errors": [f"run 缺少配方快照: {run_id}"]}

  # 2. Copy meta.json
  import shutil
  meta_dest = out_dir / "meta.json"
  shutil.copy2(meta_path, meta_dest)
  files.append("meta.json")

  # 3. Extract provenance
  meta = json.loads(meta_path.read_text(encoding="utf-8"))
  provenance = {
    "run_id": run_id,
    "git_sha": meta.get("git_sha", "unknown"),
    "package_version": meta.get("package_version", "unknown"),
    "python_version": meta.get("python_version", "unknown"),
    "os": meta.get("os", "unknown"),
    "pip_freeze_sha": meta.get("pip_freeze_sha", "unknown"),
    "solver_versions": meta.get("solver_versions", {}),
    "optuna_seed": meta.get("optuna_seed") or meta.get("seed"),
    "aedt_version": meta.get("aedt_version", ""),
    "ads_version": meta.get("ads_version", ""),
    "timestamp": meta.get("timestamp", ""),
  }
  prov_path = out_dir / "provenance.json"
  prov_path.write_text(json.dumps(provenance, indent=2, default=str), encoding="utf-8")
  files.append("provenance.json")

  # 4. Copy S-parameter files
  sparams_dir = run_dir / "results"
  if sparams_dir.exists():
    snp_files = sorted(sparams_dir.glob("*.s*p"))
    if snp_files:
      sparams_out = out_dir / "sparams"
      sparams_out.mkdir(exist_ok=True)
      for f in snp_files:
        shutil.copy2(f, sparams_out / f.name)
        files.append(f"sparams/{f.name}")

  # 5. Copy trials data (Optuna trajectory)
  trials_dir = run_dir / "trials"
  if trials_dir.exists():
    trials_out = out_dir / "trials"
    trials_out.mkdir(exist_ok=True)
    for f in sorted(trials_dir.glob("*")):
      if f.is_file():
        shutil.copy2(f, trials_out / f.name)
        files.append(f"trials/{f.name}")

  # 6. Generate reproduce.py
  adapter = meta.get("adapter", "fake")
  recipe_name = "recipe.snapshot.yaml"
  repro_script = _generate_reproduce_py(run_id, recipe_name, adapter)
  script_path = out_dir / "reproduce.py"
  script_path.write_text(repro_script, encoding="utf-8")
  files.append("reproduce.py")

  return {
    "ok": True,
    "run_id": run_id,
    "output_dir": str(out_dir),
    "files": files,
    "message": f"复现包已导出到 {out_dir}",
  }


def _generate_reproduce_py(run_id: str, recipe_name: str, adapter: str) -> str:
  """Generate a standalone reproduce.py script."""
  lines = [
    "#!/usr/bin/env python3",
    f'"""Reproduce run {run_id}."""',
    "import json, sys",
    "from pathlib import Path",
    "",
    "def main():",
    f"  recipe = Path(__file__).parent / \"{recipe_name}\"",
    "  if not recipe.exists():",
    "    print(f\"ERROR: {recipe}\"); sys.exit(1)",
    "  from rfauto.service.api import run_once",
    f"  result = run_once(recipe, adapter_name=\"{adapter}\")",
    "  if not result.get(\"ok\"):",
    "    print(f\"ERROR: {result.get('errors')}\"); sys.exit(1)",
    "  meta_path = Path(__file__).parent / \"meta.json\"",
    "  if meta_path.exists():",
    "    orig = json.loads(meta_path.read_text(encoding=\"utf-8\")).get(\"metrics\", {})",
    "    new = result.get(\"metrics\", {})",
    "    for k in sorted(set(orig) | set(new)):",
    "      ov, nv = orig.get(k), new.get(k)",
    "      if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):",
    "        print(f\" {k}: {ov:.4f} -> {nv:.4f}\")",
    "  print(json.dumps(result.get(\"metrics\", {}), indent=2))",
    "",
    "if __name__ == \"__main__\":",
    "  main()",
  ]
  return "\n".join(lines)


# ─── v3 service re-exports ───────────────────────────────────────────────────
# 唯一事实源在 v3_services.py / r3_services.py / dataset_service.py /
# dataset_insights.py / warm_start_data.py（#108/#112 治理；补齐四模块
# 公开服务函数；收口补 dataset_insights 八接口）。
# 历史修复：本文件尾部曾残留 5 个同名旧实现（compare_runs_provenance /
# run_p0_experiment / study_inject / structured_sweep / run_multifidelity_tune），
# 遮蔽 v3_services 版本——修 v3_services 不生效的幽灵 bug 由此而来（#116）。
# 以后新增服务函数：写进对应源模块，在此 re-export，禁止在本文件写实现；
# 完整性由 tests/unit/test_api_reexport.py 钉住（缺 re-export / 尾部同名
# def 遮蔽都会身份断言失败）。
# 契约性排除：r3_services.get_chat_settings_raw（返回含 api_key 明文，
# 自述"不对外"）不入 api 公开面。

from rfauto.service.dataset_insights import annotate_ground_truth as annotate_ground_truth  # noqa: E402
from rfauto.service.dataset_insights import dataset_coverage as dataset_coverage  # noqa: E402
from rfauto.service.dataset_insights import export_hf_dataset as export_hf_dataset  # noqa: E402
from rfauto.service.dataset_insights import list_datasets as list_datasets  # noqa: E402
from rfauto.service.dataset_insights import load_dataset_sets as load_dataset_sets  # noqa: E402
from rfauto.service.dataset_insights import neural_operator_readiness as neural_operator_readiness  # noqa: E402
from rfauto.service.dataset_insights import register_public_dataset as register_public_dataset  # noqa: E402
from rfauto.service.dataset_insights import set_dataset_visibility as set_dataset_visibility  # noqa: E402
from rfauto.service.dataset_service import discover_workdir_candidates as discover_workdir_candidates  # noqa: E402
from rfauto.service.dataset_service import import_workdir_runs as import_workdir_runs  # noqa: E402
from rfauto.service.dataset_service import is_ground_truth_adapter as is_ground_truth_adapter  # noqa: E402
from rfauto.service.dataset_service import materialize_dataset as materialize_dataset  # noqa: E402
from rfauto.service.dataset_service import query_dataset as query_dataset  # noqa: E402
from rfauto.service.dataset_service import write_workdir_params_json as write_workdir_params_json  # noqa: E402
from rfauto.service.r3_services import AgentChat as AgentChat  # noqa: E402
from rfauto.service.r3_services import add_solver_to_config as add_solver_to_config  # noqa: E402
from rfauto.service.r3_services import approve_proposal as approve_proposal  # noqa: E402
from rfauto.service.r3_services import fs_list as fs_list  # noqa: E402
from rfauto.service.r3_services import get_chat_settings as get_chat_settings  # noqa: E402
from rfauto.service.r3_services import list_pending_approvals as list_pending_approvals  # noqa: E402
from rfauto.service.r3_services import list_recipes as list_recipes  # noqa: E402
from rfauto.service.r3_services import list_registered_solvers as list_registered_solvers  # noqa: E402
from rfauto.service.r3_services import list_solver_visualizations as list_solver_visualizations  # noqa: E402
from rfauto.service.r3_services import remove_solver_from_config as remove_solver_from_config  # noqa: E402
from rfauto.service.r3_services import save_chat_settings as save_chat_settings  # noqa: E402
from rfauto.service.v3_services import agent_quality_summary as agent_quality_summary  # noqa: E402
from rfauto.service.v3_services import compare_runs_provenance as compare_runs_provenance  # noqa: E402
from rfauto.service.v3_services import generate_enhanced_report as generate_enhanced_report  # noqa: E402
from rfauto.service.v3_services import hfss_import_recipe as hfss_import_recipe  # noqa: E402
from rfauto.service.v3_services import run_multifidelity_sbo_tune as run_multifidelity_sbo_tune  # noqa: E402
from rfauto.service.v3_services import run_multifidelity_tune as run_multifidelity_tune  # noqa: E402
from rfauto.service.v3_services import run_p0_experiment as run_p0_experiment  # noqa: E402
from rfauto.service.v3_services import run_sensitivity as run_sensitivity  # noqa: E402
from rfauto.service.v3_services import structured_sweep as structured_sweep  # noqa: E402
from rfauto.service.v3_services import study_inject as study_inject  # noqa: E402
from rfauto.service.warm_start_data import collect_warm_start_samples as collect_warm_start_samples  # noqa: E402
from rfauto.service.warm_start_data import (  # noqa: E402
  run_optimization_warm_start_from_dataset as run_optimization_warm_start_from_dataset,
)
