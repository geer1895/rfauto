"""api.run_core —— 运行核心（validate_recipe/dry_run/run_once 与 agent_propose/agent_apply 门面动作）。

自 api.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁；本域是包内依赖叶（tuning/reporting 从这里单向导入）。
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
from rfauto.core.state import generate_run_id
from rfauto.service.envelope import error_envelope, ok_envelope


def validate_recipe(recipe_path: str | Path) -> dict[str, Any]:
    """校验配方文件，返回 {ok: bool, errors: [...], warnings: [...]}。"""
    path = Path(recipe_path)
    if not path.exists():
        return error_envelope([f"配方文件不存在: {path}"], warnings=[])

    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return error_envelope([f"YAML 解析失败: {e}"], warnings=[])

    if data is None:
        return error_envelope([f"配方文件为空: {path}"], warnings=[])
    if not isinstance(data, dict):
        return error_envelope(
            [f"配方顶层必须是映射（键值对），实际: {type(data).__name__}"],
            warnings=[])

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
            from rfauto.models.registry import get  # lazy: run-path（执行面按需取用）
            get(data["model"])
        except KeyError:
            errors.append(f"未知模型: {data['model']}")

    # K9（aurora_k，P15）：顶层可选 units 字段——"mm"（缺省，现状零变化）|
    # "um"（IPD 工艺 μm 配方）。此处只做装载侧 schema 校验；几何换算 helper
    # 在 core.stackup.to_mm（渲染入口单源），各模板接线归模板族席逐步迁移。
    if "units" in data:
        try:
            from rfauto.core.errors import ConfigError  # lazy: recipe-schema 面
            from rfauto.core.stackup import normalize_units  # lazy: core 轻载
            units = normalize_units(data["units"])
        except ConfigError as e:
            errors.append(f"'units' 字段非法: {e}")
        else:
            if units != "mm":
                warnings.append(
                    f"units={units!r} 已登记（P15 IPD 工艺口径）——换算 helper "
                    "core.stackup.to_mm 已就绪，但各模板渲染接线尚未迁移"
                    "（模板族席），当前模板参数单位语义不变")

    # 目标函数校验
    if "objectives" in data:
        for i, obj_data in enumerate(data["objectives"]):
            try:
                Objective(**obj_data)
            except Exception as e:
                errors.append(f"objectives[{i}] 校验失败: {e}")

    if errors:
        return error_envelope(errors, warnings=warnings)
    return ok_envelope(errors=errors, warnings=warnings)


def dry_run(recipe_path: str | Path, *, adapter_name: str = "fake") -> dict[str, Any]:
    """dry-run 护栏（计划内缺口 6）——只验证不执行。

    走完 run_once 的全部前置检查（配方校验、模型注册、参数解析、
    缓存键计算、AEDT 路径检查），但不创建适配器、不建模、不求解、
    不写 runs/。返回执行计划供人工/Agent 确认后再真实提交。
    """
    validation = validate_recipe(recipe_path)
    if not validation["ok"]:
        return error_envelope(validation["errors"], mode="dry-run")

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
        from rfauto.infra.version_probe import resolve_aedt_install  # lazy: run-path（执行面按需取用）
        install = resolve_aedt_install(aedt_path or None)
        adapter_ok = adapter_ok and install is not None
        aedt_version = install["aedt_version"] if install else "unknown"
    elif adapter_name != "fake":
        return error_envelope([f"未知适配器: {adapter_name}"], mode="dry-run")

    from rfauto.models.registry import get as get_plugin_cls  # lazy: run-path（执行面按需取用）
    plugin_cls = get_plugin_cls(model_name)

    # P2①：内容寻址键（与 run_once 同一派生 components_for_run，保证 dry-run
    # 预报的 cache_hit 与真跑判定同键；why_miss 给出"为什么不会命中"）
    from rfauto.infra.result_cache import ResultCache  # lazy: run-path（执行面按需取用）
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

    return ok_envelope(
        mode="dry-run",
        message="仅验证未执行——确认计划后去掉 --dry-run 真实提交",
        recipe=str(recipe_path),
        model=model_name,
        adapter=adapter_name,
        adapter_ready=adapter_ok,
        aedt_version=aedt_version,
        params=resolved_params,
        objectives=recipe_data.get("objectives", []),
        setup=recipe_data.get("setup", {}),
        plugin_version=f"schema{plugin_cls.schema_version}",
        cache_key=cache_key,
        cache_hit=cache_lookup["hit"],
        cache={
            "key": cache_key,
            "provenance": cache_lookup["provenance"],
            "why_miss": cache_lookup["why_miss"],
            "components": cache_components,
        },
        validation=validation,
    )


def clear_result_cache(model_name: str | None = None) -> dict[str, Any]:
    """手动清理结果缓存（``jobs cache-clear`` 单源；W11-S3 T8 收口）。

    清理本体归 ``infra.result_cache.ResultCache.clear``（service→infra
    合法向下）；信封键 ``{ok, removed, model}`` 与 cli 原地构造逐字节一致。
    """
    from rfauto.infra.result_cache import ResultCache  # lazy: run-path（执行面按需取用）

    removed = ResultCache().clear(model_name=model_name)
    return ok_envelope(removed=removed, model=model_name)


def _make_progress_reporter(progress_cb: Any) -> Any:
    """SN-10：把裸回调包成 best-effort 播报器（None → no-op）。

    回调异常一律吞掉（#105：观测面不阻塞求解主路径）；无回调时返回的
    no-op 调用开销为零（热路径无 if 判断成本——闭包内判空一次定型）。
    """
    if progress_cb is None:
        def _noop(pct: float, stage: str = "") -> None:
            return None
        return _noop

    def _safe(pct: float, stage: str = "") -> None:
        try:
            progress_cb(max(0.0, min(100.0, float(pct))), str(stage))
        except Exception:  # pragma: no cover - 观测面兜底（#105）
            return
    return _safe


def run_once(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    study: str = "",
    seed: str = "",
    progress_cb: Any = None,
) -> dict[str, Any]:
    """单次仿真（build → solve → post → metrics → sNp → figs）。

    adapter_name: "fake"（FakeAdapter 解析近似）或 "hfss"（真实 AEDT 全链）。
    study / seed: 仅作 provenance 作用域记入缓存 manifest 与 run meta（#158：
    **不进缓存键**——同几何不同 study 命中同一条目并标 cross_study），缺省空串。
    progress_cb（SN-10，2026-10-06 W6-A）: 可选 ``cb(pct: float, stage: str)``
    逐阶段播报（prepared 5 → build 10 → solve 15 → post 90 → done 100；
    solve 段引擎无统一进度钩子，15→90 为诚实粗粒度区间，不臆造细粒度）。
    None（缺省）零行为零开销；回调异常一律吞掉（#105：观测面不阻塞主路径）。
    """
    _report = _make_progress_reporter(progress_cb)

    # 校验配方
    validation = validate_recipe(recipe_path)
    if not validation["ok"]:
        return error_envelope(validation["errors"])
    _report(5.0, "prepared")

    import yaml
    with open(recipe_path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    run_id = generate_run_id()

    # 创建 run 目录（绝对路径：AEDT 拒绝相对项目路径，会解析到它自己的工作目录）
    from rfauto.infra.run_store import create_run_dir, snapshot_recipe, write_meta  # lazy: run-path（执行面按需取用）
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)

    # 获取模型插件（先于适配器：n_ports / fake_model_type 驱动契约与解析近似，
    # C4 修复：原先 fake 模式硬编码 3 端口 wilkinson，branchline/patch 的
    # fake 仿真产出的是错误模型的 S 参数）
    from rfauto.models.registry import get as get_plugin_cls  # lazy: run-path（执行面按需取用）
    model_name = recipe_data.get("model", "")
    try:
        plugin_cls = get_plugin_cls(model_name)
    except KeyError:
        return error_envelope([f"未知模型: {model_name}"])
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
        return error_envelope([f"未知适配器: {adapter_name}"])

    # ─── ResultCache：键计算与查询前移（C5 修复：原先发生在 AEDT 建会话与
    # build 之后——缓存命中仍付出完整建模成本）。aedt_version 仅由环境变量
    # 推导，无需连接。plugin_version 取插件 schema 版本（几何变更须升版本
    # 才能避开陈旧缓存；原先三处硬编码 "0.1.0" 各自为政）。──
    import os

    from rfauto.infra.result_cache import ResultCache  # lazy: run-path（执行面按需取用）
    from rfauto.infra.version_probe import resolve_aedt_install  # lazy: run-path（执行面按需取用）
    cache = ResultCache()
    aedt_version = "fake"
    if adapter_name == "hfss":
        aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
        if aedt_path and not Path(aedt_path).exists():
            return error_envelope(
                [f"RFAUTO_AEDT_PATH 设置了但路径不存在: {aedt_path}"])
        # 项目 B：版本探测收敛到 infra 层（显式路径优先，否则自动探测本机安装）
        install = resolve_aedt_install(aedt_path or None)
        if install is None:
            return error_envelope([
                "未找到可用 AEDT：RFAUTO_AEDT_PATH 未设置且自动探测未发现安装"
                "（可设 RFAUTO_AEDT_PATH=<版本目录>，如 E:\\HFSS\\v231）"
            ])
        aedt_version = install["aedt_version"]

    # P2①（§10.20 ⑨ 生产接线）：内容寻址键 compute_content_key——13 成分分列
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
            from_cache = False  # 缓存损坏则回退真实求解

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
        _report(10.0, "build")
        if adapter_name == "fake":
            from rfauto.adapters.fake_adapter import FakeAdapter  # lazy: run-path（执行面按需取用）
            adapter = FakeAdapter(n_ports=n_ports, model_type=plugin_cls.fake_model_type)
            adapter.connect({})
        else:
            from rfauto.adapters.hfss_adapter import HfssAdapter  # lazy: run-path（执行面按需取用）
            adapter = HfssAdapter()
            adapter.connect({"desktop_version": aedt_version, "non_graphical": True})
            design_name = recipe_data.get("design_name", "RFADesign")
            adapter.open_or_create_project(run_dir / "hfss" / "design.aedt", design_name)
            hfss_mode = True

        # 连接 + 构建 + 求解（构建/求解均带自愈编排：缺口 4）
        from rfauto.pipeline.self_heal import build_with_self_heal  # lazy: run-path（执行面按需取用）

        def _build():
            plugin.build(adapter, plugin.params_model(**{
                k: (v["value"] if isinstance(v, dict) else v) for k, v in params_data.items()
            }))
            ps.write_to_adapter(adapter, name_map=getattr(plugin_cls, "hfss_var_map", {}))

        build_with_self_heal(_build)
        _report(15.0, "solve")

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
        _report(90.0, "post")
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
    else:
        # R5 自愈求解：掉线/健康检查失败时 ensure_connected 后重试一次
        from rfauto.pipeline.self_heal import solve_with_self_heal  # lazy: run-path（执行面按需取用）
        report = solve_with_self_heal(adapter, setup_name)
        if not report.success:            # 求解失败：不产出结果文件，登记后干净退出（勿让 export 异常穿透）
            meta = {
                "run_id": run_id,
                "package_version": __version__,
                "plugin_version": f"schema{plugin_cls.schema_version}",
                "schema_version": recipe_data.get("schema_version", 1),
                "adapter": adapter_name, "aedt_version": aedt_version, "ads_version": "n/a",
                "user": getpass.getuser(), "hostname": platform.node(),
                "model": model_name, "status": "solve_failed",
                "solve_message": report.message,
                # H-10（W1-F）：run_once 无 optuna study，study_name 取 run_id
                # （dataset_service 导入面同款口径）——湖 runs 索引 study 列不再 null
                "study_name": run_id,
            }
            meta_path = write_meta(run_dir, meta)
            from rfauto.infra.run_store import record_run  # lazy: run-path（执行面按需取用）
            record_run(record=meta)
            # WP3.6 收尾钩子（best-effort，#105）：失败 run 的日志面最有诊断价值，
            # 蒸馏成 log_digest.json 供自愈环/MCP 消费；异常只记 warning 不阻断
            try:
                from rfauto.service.self_heal_service import write_log_digest_for_run  # lazy: cycle-break（T1 解环面）
                write_log_digest_for_run(run_dir)
            except Exception as digest_exc:  # pragma: no cover - 观测性兜底
                import logging as _logging
                _logging.getLogger(__name__).warning("log_digest 钩子失败（非阻断）: %s", digest_exc)
            adapter.close()
            return error_envelope(
                [f"求解失败: {report.message}"],
                run_id=run_id,
                run_dir=str(run_dir),
            )

        # 导出 Touchstone（扩展名按端口数, 避免 skrf 回读混淆）。
        # HfssAdapter 可能按实际端口数修正扩展名，以返回的真实路径为准
        # （缓存写回与后续读取都应用真实路径）。
        _report(90.0, "post")
        sparams_path = run_dir / "results" / f"params.s{len(contract.touchstone.port_order)}p"
        sparams_path.parent.mkdir(parents=True, exist_ok=True)
        sparams_path = Path(adapter.export_touchstone(sparams_path, contract))

        # K4（aurora_k，P11/F7）：Touchstone 落盘点旁写 sidecar 指纹
        # （run_id+sha256+设计名+导出时间，best-effort #105——失败只记
        # warning 不阻塞求解产物）。文件级自描述：交付拷贝错配（旧工程
        # s1p 混进新 run 目录）在文件本体旁即有哈希证据可查。
        try:
            from rfauto.service.runs_verify_service import write_touchstone_sidecar  # lazy: run-path（执行面按需取用）
            write_touchstone_sidecar(
                sparams_path, run_id=run_id,
                design_name=str(recipe_data.get("design_name", "RFADesign")),
                setup=str(setup_name))
        except Exception as sidecar_exc:  # pragma: no cover - 观测面兜底（#105）
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Touchstone sidecar 写入失败（非阻断）: %s", sidecar_exc)

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
        from rfauto.infra.diagnosis import diagnose_results  # lazy: run-path（执行面按需取用）
        diagnosis = diagnose_results(
            metrics,
            model_name=model_name,
            objectives=[o.model_dump() for o in objectives],
        )
    except Exception as diag_exc:  # pragma: no cover - 防御性
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

    from rfauto.infra.report import generate_report  # lazy: run-path（执行面按需取用）

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
    from rfauto.infra.run_store import record_run  # lazy: run-path（执行面按需取用）
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
        # H-10（W1-F）：run_once 无 optuna study，study_name 取 run_id
        # （dataset_service 导入面同款口径）——湖 runs 索引 study 列不再 null
        "study_name": run_id,
        "from_cache": from_cache,
        "cache": cache_info,
        "metrics": metrics,
    })
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    record_run(record=meta)

    # K4（aurora_k，P11/F7）：run 收官指纹落盘 manifest.json（best-effort
    # #105——失败只记 warning 不阻塞收官）。聚合 recipe 快照哈希 + 全部
    # Touchstone 清单（sha256/size/mtime）+ meta 关键字段引用；`rfauto runs
    # verify` 与 report 新鲜度门消费——旧产物混入新 run 不能再静默通过。
    try:
        from rfauto.service.runs_verify_service import write_manifest  # lazy: run-path（执行面按需取用）
        write_manifest(run_dir)
    except Exception as manifest_exc:  # pragma: no cover - 观测面兜底（#105）
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "run manifest 写入失败（非阻断）: %s", manifest_exc)

    # WP3.6 收尾钩子（best-effort，#105）：run 落盘后把日志面蒸馏成
    # runs/<id>/log_digest.json 供自愈环/MCP/UI 消费；异常只记 warning 不阻断
    try:
        from rfauto.service.self_heal_service import write_log_digest_for_run  # lazy: cycle-break（T1 解环面）
        write_log_digest_for_run(run_dir)
    except Exception as digest_exc:  # pragma: no cover - 观测性兜底
        import logging as _logging
        _logging.getLogger(__name__).warning("log_digest 钩子失败（非阻断）: %s", digest_exc)

    # AD-7 skill 自动沉淀钩子（ge8e J1-1 接线，best-effort，#105）：run 收官
    # 成功后按 run_id 走 health 判定自动沉淀（同 run 幂等沉淀一次；沉淀产物
    # 落 run 目录内 skills/ 子目录，不污染仓根技能库）；异常只记 warning 不阻断
    try:
        from rfauto.service.skill_autopilot import auto_deposit_hook  # lazy: cycle-break（T1 解环面）

        auto_deposit_hook(run_id=run_id, output_dir=run_dir / "skills")
    except Exception as skill_exc:  # pragma: no cover - 观测性兜底
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "skill 自动沉淀钩子失败（非阻断）: %s", skill_exc)

    if adapter is not None:
        adapter.close()

    _report(100.0, "done")
    return ok_envelope(
        run_id=run_id,
        run_dir=str(run_dir),
        metrics=metrics,
        cost=cost,
        from_cache=from_cache,
        cache=cache_info,
        solve_report=(
            {"success": True, "passes": 0, "delta_s_final": 0.0}
            if from_cache
            else {
                "success": report.success,
                "passes": report.passes,
                "delta_s_final": report.delta_s_final,
            }
        ),
        report=str(report_path),
    )


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
        return error_envelope(validation["errors"], stage="validate")

    import yaml
    with open(recipe_path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    params_override = params_override or {}
    from rfauto.service.agent_gate import AgentGate  # lazy: cycle-break（T1 解环面）

    gate = AgentGate()
    l1 = gate.check_l1(params_override, recipe_data)
    if not l1.passed:
        # 否决原因分类落审计（4b 质量指标数据源）
        from rfauto.service.agent_audit import append_audit_log  # lazy: cycle-break（T1 解环：审计叶）
        append_audit_log({
            "event": "propose",
            "ok": False,
            "stage": "L1",
            "recipe": str(recipe_path),
            "reason": l1.details.get("violations", []),
        })
        return error_envelope(
            l1.details.get("violations") or ["L1 白名单门未通过"],
            stage="L1", gate=l1.to_dict())

    l2 = gate.check_l2(params_override, recipe_data)
    if not l2.passed:
        from rfauto.service.agent_audit import append_audit_log  # lazy: cycle-break（T1 解环：审计叶）
        append_audit_log({
            "event": "propose",
            "ok": False,
            "stage": "L2",
            "recipe": str(recipe_path),
            "reason": l2.details["issues"],
        })
        return error_envelope(
            l2.details["issues"] or ["L2 dry-run 门未通过"],
            stage="L2", gate=l2.to_dict())

    l3 = gate.check_l3(l1, l2, params_override)

    plan = dry_run(recipe_path, adapter_name=adapter_name)

    # ADR-0025：写操作 diff 预览 + 审批日志（token 只记哈希）
    from rfauto.service.agent_audit import append_audit_log, token_hash  # lazy: cycle-break（T1 解环：审计叶）
    from rfauto.service.agent_safety import preview_write_diff  # lazy: cycle-break（T1 解环面）
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
    return ok_envelope(
        stage="L3",
        token=l3.token,
        effective_params={
            k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in {**recipe_data.get("params", {}), **params_override}.items()
        },
        plan=plan,
        write_diff=write_diff,
        message="提案就绪：人工/编排确认后带 token 调 agent_apply 真实执行",
    )


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
    from rfauto.service.agent_gate import AgentGate  # lazy: cycle-break（T1 解环面）

    gate = AgentGate()
    l1 = gate.check_l1(params_override, recipe_data)
    l2 = gate.check_l2(params_override, recipe_data)
    if not gate.validate_token(token, l1, l2, params_override):
        from rfauto.service.agent_audit import append_audit_log, token_hash  # lazy: cycle-break（T1 解环：审计叶）
        append_audit_log({
            "event": "apply",
            "ok": False,
            "stage": "L3",
            "recipe": str(recipe_path),
            "token_hash": token_hash(token),
            "reason": "token 校验失败：参数与 propose 时不一致或 token 无效",
        })
        return error_envelope(
            ["token 校验失败：参数与 propose 时不一致或 token 无效，"
             "请重新 agent_propose"],
            stage="L3",
        )

    # 合并参数生成提案配方，落到独立目录（不覆盖原始配方）
    merged = dict(recipe_data)
    merged_params = dict(recipe_data.get("params", {}))
    for k, v in params_override.items():
        merged_params[k] = {"value": v} if not isinstance(v, dict) else v
    merged["params"] = merged_params

    # ADR-0025：写路径白名单 + 审批日志（token 只记哈希）
    import hashlib as _hashlib
    import json as _json

    # F-6/S3：提案目录走 runs 双根收敛（与 agent_safety.allowed_write_roots
    # 同根）——chdir 仓内子目录时写侧与白名单侧同收敛回仓库 runs/，不自锁。
    from rfauto.infra.runs_paths import resolve_runs_dir  # lazy: run-path（执行面按需取用）
    from rfauto.service.agent_audit import (  # lazy: cycle-break（T1 解环：审计叶）
        append_audit_log,
        token_hash,
    )
    from rfauto.service.agent_safety import check_write_paths  # lazy: cycle-break（T1 解环面）

    proposal_dir = resolve_runs_dir(Path("runs") / "agent_proposals")
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
        return error_envelope(
            [f"写路径越出白名单: {p}" for p in write_guard["violations"]],
            stage="write_guard",
        )

    # 提案落 runs/agent_proposals/（白名单已由 check_write_paths 钉住；再经
    # recipe_guard 统一出口——受保护 recipes/ 目标缺省抛 RecipeWriteForbidden）
    from rfauto.infra.recipe_guard import write_recipe_yaml  # lazy: run-path（执行面按需取用）

    write_recipe_yaml(proposal_path, merged)

    result = run_once(proposal_path, adapter_name=adapter_name)

    # 4b 质量指标（审查缺口 #16）：改进率 = (基线 cost - 提案 cost)/基线 cost。
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
        except Exception as exc:
            # F-1/S3：基线复算失败留痕不吞——quality_error 一行进结果与
            # 审计日志（#105 观测面 best-effort：不阻塞主路径但可审计）。
            quality["quality_error"] = str(exc)

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
