"""模板→配方通路单源（T-Q14，aurora_q Q-W1-1 席；R8 gdsfactory/LightningCLI 形态）。

外部用户实证的断点（微信反馈①，PLAN_DRAFT 〇b）：模板注册表（TEMPLATE_META
76 族）与优化模型注册表（models/registry 4 模型）名字空间互不相通——用户按
模板族名写 `model: pifa` 配方，validate 报"未知模型"死胡同。本模块把两条
注册表接通为一条"查族 → 导出配方 → validate → run"通路，三件能力全部
service 层单源（CLI/UI/MCP 薄壳同源消费，规则 4）：

1. :func:`template_model_mapping` —— 76 族逐族映射表（幂等纯派生）：
   族有对应优化模型 → ``model`` 名；无 → ``None`` + 显式边界标注
   （"该族当前经 openEMS 模板直跑"语义，判定依据写进 rationale）。
2. :func:`export_template_recipe` —— 族 → 配方 YAML：
   - 有模型的 4 族 → ``model:`` 形态（既有优化链全可用）；
   - 其余 72 族 → ``template:`` 形态（validate/run 链认识 template 键，
     run 链最小可跑走 :func:`run_template_recipe`）。
   参数值只出自确定性注册表面（TEMPLATE_NOMINAL/TEMPLATE_META 缺省 nominal，
   铁律 7：本通路零物理数值生产）。
3. :func:`run_template_recipe` —— ``template:`` 形态配方的 run 链
   （``rfauto run`` 对 template 配方自动路由至此；fake 通道解析近似零
   license，openEMS 通道真引擎——经 OpenEMSSolver 既有模板几何面）。

映射判定依据（逐族，不拍脑袋——三源实测）：
- ``TemplateSpec.hfss_plugin``（models/template_specs 注册表：模板→HFSS/
  优化模型插件绑定，branchline/patch/wilkinson 三族非 None）；
- ``models.registry.list_models()`` 与模板族同名的精确匹配（mline 先例：
  models 注册表存在 name="mline" 内置插件）；
- 其余族 = None：TEMPLATE_META 注册但无 models 插件绑定——openEMS 模板
  直跑语义（HFSS 仲裁面走 scripts/ 专项链，不占 models 插件位）。

幂等性：mapping/export 均为注册表纯读派生（同输入同输出，两次调用逐字节
一致，tests/unit/test_template_recipe_path.py 钉住）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 导出配方的缺省频带约定（与 models/template_specs._vi3_recipe_draft 同口径：
#: 带宽=f0/0.96 对称、401 点）——确定性派生自 meta f0_ghz，零手拍频带。
_EXPORT_BAND_FRAC = 0.96
#: 单端口族（n_ports==1，天线/单口谐振器）缺省宽带 = f0/0.70 对称
#: （≈2f0 全带宽；专利4 Fix3：窄带下真谐振落带外造成“整带无谷”观感——
#: 2026-11-05 实证 pifa 2.304-2.5GHz 带外 2.26GHz 谷）。
_EXPORT_BAND_FRAC_WIDE = 0.70
_EXPORT_POINTS = 401

#: template: 形态配方的 run 通道白名单（fake=解析近似零 license；
#: openEMS=真引擎，经 OpenEMSSolver 既有模板几何面）。
_TEMPLATE_RUN_ADAPTERS: tuple[str, ...] = ("fake", "openems")


def _full_template_meta() -> dict[str, dict[str, Any]]:
    """TEMPLATE_META 满员单源（76 族）。

    经 adapters.oe_templates 包门面 import——包 __init__ 链拉齐全部
    render_*.py 注册块（registry.py 内联 20 族 + 各渲染模块 import 期
    追加注册 = 76 族满员（layered_stack=Q-X6 批 2 文内注册件，
    2026-11-07）；直接 import registry 子模块不触发渲染模块注册链，
    本函数统一走门面保满员）。
    """
    from rfauto.adapters.oe_templates.registry import (
        TEMPLATE_META as _META,
    )
    return _META


def template_model_mapping() -> dict[str, Any]:
    """76 族→优化模型映射表（幂等纯派生，CLI/UI/MCP 同源消费）。

    每族一行：``{family, model, mapping_source, rationale, n_ports,
    f0_ghz, fake_model}``。``model=None`` 的族 rationale 带显式边界标注
    （openEMS 模板直跑语义）。族序=TEMPLATE_META 注册序（单源插入序，
    确定性）。
    """
    from rfauto.models.registry import list_models
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    meta = _full_template_meta()
    bootstrap_template_specs()
    models = set(list_models())
    spec_names = set(TEMPLATE_SPECS.names())

    rows: list[dict[str, Any]] = []
    for family in meta:
        spec = TEMPLATE_SPECS.get(family) if family in spec_names else None
        hfss = getattr(spec, "hfss_plugin", None)
        if hfss and hfss in models:
            model: str | None = hfss
            source = "template_spec.hfss_plugin"
            rationale = (
                f"模板 '{family}' 在 TemplateSpec 注册表绑定优化模型插件 "
                f"'{hfss}'（models/template_specs hfss_plugin，models/registry "
                "已注册）——配方用 model: 形态，validate/run/tune 全链可用")
        elif family in models:
            model = family
            source = "models.registry.name_match"
            rationale = (
                f"models 注册表存在与模板族同名的优化模型插件 '{family}'"
                "（models/registry 内置模型）——配方用 model: 形态，全链可用")
        else:
            model = None
            source = "none"
            rationale = (
                "该族当前经 openEMS 模板直跑：models 注册表无对应优化模型"
                "（TemplateSpec.hfss_plugin=None，HFSS 仲裁面走 scripts 专项"
                "链不占插件位）——配方用 template: 形态（validate/run 链认识"
                " template 键；tune 调参面暂不支持）")
        rows.append({
            "family": family,
            "model": model,
            "mapping_source": source,
            "rationale": rationale,
            "n_ports": meta[family].get("n_ports"),
            "f0_ghz": meta[family].get("f0_ghz"),
            # fake 通道可用性（FakeAdapter model_type 分派面对齐口径：
            # TemplateSpec.fake_model 注册即有解析近似前向）
            "fake_model": bool(getattr(spec, "fake_model", None)),
        })
    n_model = sum(1 for r in rows if r["model"] is not None)
    return ok_envelope(
        mapping=rows,
        total=len(rows),
        n_with_model=n_model,
        n_template_direct=len(rows) - n_model,
        model_registry=sorted(models),
    )


def _model_for_family(family: str) -> str | None:
    """映射表单族查询（与 :func:`template_model_mapping` 同一判定链）。"""
    from rfauto.models.registry import list_models
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec_names = set(TEMPLATE_SPECS.names())
    hfss = (getattr(TEMPLATE_SPECS.get(family), "hfss_plugin", None)
            if family in spec_names else None)
    if hfss and hfss in set(list_models()):
        return hfss
    if family in set(list_models()):
        return family
    return None


def build_template_recipe(family: str) -> dict[str, Any]:
    """族 → 配方 dict（纯组装零 IO；export 落盘/校验共用本体）。

    参数值单源 = TEMPLATE_NOMINAL[family]（注册表归档名义值，HJ/FD 精算
    出处见 registry 头注）；setup 频带由 meta f0_ghz 按 _EXPORT_BAND_FRAC
    确定性派生。铁律 7：本函数零物理数值生产。
    """
    from rfauto.adapters.oe_templates.registry import (
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    meta = TEMPLATE_META[family]
    f0 = float(meta["f0_ghz"])
    model = _model_for_family(family)
    # Fix3（专利4）：单端口族宽带缺省（f0/0.70 对称≈2f0 全带宽），
    # 多端口族维持窄带 0.96；整带无谷时仍应放宽频段复查（notes 提示）。
    n_ports_meta = int(meta.get("n_ports") or 2)
    band_frac = _EXPORT_BAND_FRAC_WIDE if n_ports_meta == 1 else _EXPORT_BAND_FRAC
    recipe: dict[str, Any] = {
        "recipe_version": 1,
        "notes": (
            f"{family} 模板导出配方（rfauto templates export-recipe，"
            f"名义参数=TEMPLATE_NOMINAL 注册表归档值，f0={f0}GHz；"
            f"单端口族缺省宽带 ±{round((1 - band_frac) * 100)}%）——"
            "整带无谷时应放宽频段复查（谐振可能在带外）"),
        # 有模型族 → model: 形态（既有优化链）；其余 → template: 形态
        # （模板直跑，validate/run 认识 template 键）。
        "params": {k: v for k, v in TEMPLATE_NOMINAL[family].items()},
        "setup": {
            "solver": "openEMS",
            "freq_range_ghz": [round(f0 * band_frac, 6),
                               round(f0 / band_frac, 6)],
            "points": _EXPORT_POINTS,
        },
    }
    if model is not None:
        recipe["model"] = model
        recipe["schema_version"] = 1
    else:
        recipe["template"] = family
    return recipe


def export_template_recipe(
    family: str,
    out_path: str | Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """族 → 配方 YAML（CLI ``templates export-recipe`` / UI 同源单源）。

    out_path=None：只组装不落盘（信封带 recipe/yaml 文本，UI 预览用）。
    out_path 给定：经 recipe_guard 守卫出口写出（recipes/ 受保护根=explicit
    显式档；已存在且未 overwrite → 拒绝并提示 --force）。
    """
    from rfauto.service.recipe_validation import did_you_mean

    meta = _full_template_meta()
    if family not in meta:
        return error_envelope(
            [f"未知模板族: {family}"
             f"{did_you_mean(family, list(meta))}"
             "（已注册模板族清单: rfauto templates golden-diff --template ''；"
             "76 族→模型映射表: service.template_recipe_service."
             "template_model_mapping）"])

    recipe = build_template_recipe(family)
    model = recipe.get("model")
    import yaml
    yaml_text = yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False)

    result = ok_envelope(
        family=family,
        form="model" if model is not None else "template",
        model=model,
        recipe=recipe,
        yaml=yaml_text,
    )
    if out_path is None:
        return result

    path = Path(out_path)
    if path.exists() and not overwrite:
        return error_envelope(
            [f"目标已存在: {path}（--force/--overwrite=true 覆盖，缺省拒绝"
             "防误覆盖既有配方）"],
            family=family, path=str(path))
    from rfauto.infra.recipe_guard import write_recipe_yaml  # lazy: 写出面

    written = write_recipe_yaml(path, recipe, explicit=True)
    return ok_envelope(
        **{k: v for k, v in result.items() if k != "ok"},
        path=str(written),
        overwritten=bool(getattr(written, "overwritten", False)),
    )


# ─── run 链（template: 形态配方）─────────────────────────────────────────────


def _template_freq_setup(setup: dict[str, Any]) -> tuple[float, float, int]:
    """setup 段 → (start, stop, points)；缺席回退 FakeAdapter 缺省轴。"""
    fr = setup.get("freq_range_ghz")
    pts = setup.get("points")
    if isinstance(fr, (list, tuple)) and len(fr) == 2 and pts:
        return float(fr[0]), float(fr[1]), int(pts)
    return 1.0, 4.0, 201


def run_template_recipe(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    study: str = "",
    seed: str = "",
    progress_cb: Any = None,
) -> dict[str, Any]:
    """``template:`` 形态配方单次仿真（``run_once`` 对 template 配方的路由终点）。

    - fake 通道：FakeAdapter model_type=族名分派（解析近似零 license；族无
      fake 前向模型时如实报错并指引 openEMS 通道）。
    - openEMS 通道：OpenEMSSolver 模板几何面（{"template": 族, "params"}），
      与 service/autotune_service 真引擎调用同款（铁律 7：数值全出引擎）。

    run 目录/meta/report 面与 run_once 同构（infra.run_store 单源），缓存键
    面暂未接入（models 插件 plugin_version 成分缺位，模板族如实标注
    ``cache: not_applicable``——不冒充命中语义）。
    """
    from rfauto.service.api.run_core import validate_recipe  # lazy: 解环面

    validation = validate_recipe(recipe_path)
    if not validation["ok"]:
        return error_envelope(validation["errors"])
    _report = progress_cb
    if _report is not None:
        _report(5.0, "prepared")

    import json

    import yaml
    with open(recipe_path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    family = str(recipe_data["template"])
    setup = recipe_data.get("setup") or {}
    params_data = recipe_data.get("params", {})

    from rfauto.adapters.oe_templates.registry import TEMPLATE_META

    meta = TEMPLATE_META[family]
    n_ports = int(meta["n_ports"])

    if adapter_name not in _TEMPLATE_RUN_ADAPTERS:
        from rfauto.service.recipe_validation import did_you_mean
        return error_envelope([
            f"未知适配器: {adapter_name}"
            f"{did_you_mean(adapter_name, _TEMPLATE_RUN_ADAPTERS)}"
            "（模板直跑配方可用适配器: fake/openems——fake 解析近似零 "
            "license；openEMS 真引擎）"])

    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import (
        create_run_dir,
        probe_engine_identity,
        snapshot_recipe,
        write_meta,
    )

    run_id = generate_run_id()
    # 与 run_once 同款 cwd 绝对化（#144 家族：run 目录解析在调用时取 cwd，
    # 测试配方落 tmp 必须 monkeypatch.chdir 隔离）。
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)

    network = None
    solve_meta: dict[str, Any] = {}
    # AX-3（aurora_r R-03）：引擎身份随 run 落盘（构造单源=probe_engine_
    # identity，fake/openems 两分支同源——失败降级 unknown 不阻塞 #105）。
    engine_identity: dict[str, Any] = probe_engine_identity("fake")
    if adapter_name == "fake":
        from rfauto.adapters.fake_adapter import FakeAdapter
        from rfauto.core.parameters import ParameterSystem, ParamValue
        from rfauto.pipeline.self_heal import solve_with_self_heal

        param_values = {
            k: (ParamValue(name=k, value=v.get("value", 0), unit=v.get("unit", "mm"))
                if isinstance(v, dict) else ParamValue(name=k, value=v))
            for k, v in params_data.items()
        }
        adapter = FakeAdapter(
            model_type=family, n_ports=n_ports,
            freq_ghz=_template_freq_setup(setup))
        adapter.connect({})
        try:
            ParameterSystem(param_values).write_to_adapter(adapter)
        except Exception as exc:
            adapter.close()
            return error_envelope([f"参数写入失败: {exc}"])
        if _report is not None:
            _report(15.0, "solve")
        try:
            report = solve_with_self_heal(adapter, "main_setup")
        except ValueError as exc:
            # FakeAdapter 未知 model_type 分派（族无解析近似前向模型）：
            # 如实报错并指引 openEMS 通道（不冒充求解成功）。
            adapter.close()
            return error_envelope([
                f"fake 通道不支持模板族 '{family}'（无解析近似前向模型）: {exc}"
                "——请用 openEMS 通道: rfauto run <配方> --adapter openems"])
        if not report.success:
            adapter.close()
            return error_envelope(
                [f"求解失败: {report.message}"], run_id=run_id,
                run_dir=str(run_dir))
        network = adapter.get_sparams()
        solve_meta = {"success": True, "passes": report.passes,
                      "delta_s_final": report.delta_s_final}
        adapter.close()
    else:
        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            resolve_openems_exe,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver

        engine_identity = probe_engine_identity("openems")

        resolved = {
            k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in params_data.items()
        }
        work = run_dir / "openems"
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems",
            exe_path=resolve_openems_exe(),
            working_dir=str(work),
            freq_range_ghz=_template_freq_setup(setup)[:2],
            mesh_resolution_mm=float(setup.get("mesh_resolution_mm", 0.0) or 0.0),
        ))
        if not solver.connect():
            return error_envelope([
                "openEMS 不可用（exe 未找到——设 RFAUTO_OPENEMS_BIN 或见 "
                "docs/openems_build_guide.md）；零 license 冒烟走 fake 通道: "
                "rfauto run <配方> --adapter fake"])
        if not solver.build_geometry({"template": family, "params": resolved}):
            return error_envelope(["openEMS 几何构建失败"],
                                  run_id=run_id, run_dir=str(run_dir))
        if _report is not None:
            _report(15.0, "solve")
        import time as _time
        _t_solve = _time.perf_counter()
        result = solver.solve()
        # Fix4a（专利4）：harness 级真墙钟（引擎自报 wall_time_s 实测恒 0.0
        # ——取证口径“求解耗时”须可从 run 目录自身复核）。
        _solve_wall_s = round(_time.perf_counter() - _t_solve, 6)
        if not result.success or result.s_params is None:
            return error_envelope(
                [f"openEMS 求解失败: {result.message}"],
                run_id=run_id, run_dir=str(run_dir))
        import numpy as np
        import skrf

        freq_ghz = np.asarray(result.freq_ghz, dtype=float)
        network = skrf.Network(
            frequency=skrf.Frequency(
                float(freq_ghz[0]), float(freq_ghz[-1]),
                len(freq_ghz), unit="ghz"),
            s=result.s_params, z0=50.0)
        solve_meta = {"success": True, "engine": "openEMS",
                      "wall_time_s": _solve_wall_s,
                      "engine_wall_time_s": float(result.wall_time_s)}

    # ─── 指标/落盘面（与 run_once 同构：SpecEvaluator 单源 + report/meta）──
    import getpass
    import platform

    from rfauto.infra.run_store import load_solver_versions

    def _load_solver_versions_best_effort() -> dict[str, str]:
        """Fix4c（专利4）：solver_versions 溯源 best-effort（#105——
        面不可用返回 {"provenance": "unavailable"}，不阻塞主路径）。"""
        try:
            return dict(load_solver_versions())
        except Exception as exc:
            return {"provenance": f"unavailable ({type(exc).__name__})"}

    import numpy as np

    from rfauto import __version__
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.infra.report import generate_report
    from rfauto.infra.run_store import record_run

    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    metrics = SpecEvaluator.compute_metrics(network, objectives)
    cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
    sanity = SpecEvaluator.sanity_check(network, objectives)

    # Touchstone 导出（扩展名按 network 实际秩——#248 家族修复 2026-11-05
    # 主代理真跑实证：openEMS 通道对名义 1 端口模板（pifa）回填对称 2×2
    # 矩阵（fix-g11 家族），按名义 n_ports 命名 .s1p 会让 skrf 回读广播炸
    # （(401,4)→(401,1)）。写出秩=network.s.shape[1]（数据真相单源）；
    # 名义端口数入 solve_meta 供消费方分辨填充面（#314 掩码语义）。
    from rfauto.core.contracts import AdsExchangeContract

    net_ports = int(network.s.shape[1])
    contract = AdsExchangeContract.for_n_ports(net_ports)
    sparams_path = run_dir / "results" / f"params.s{len(contract.touchstone.port_order)}p"
    sparams_path.parent.mkdir(parents=True, exist_ok=True)
    network.write_touchstone(str(sparams_path))
    if net_ports != n_ports:
        # Fix2（专利4）：填充形态头注——外部工具读 sNp 头即可识别
        # “单端口结果填充 2×2”语义，S21/S12/S22 非独立测量。
        _hdr = sparams_path.read_text(encoding="utf-8")
        _note = ("! NOTE: single-port template result filled to "
                 f"{net_ports}-port matrix (S21/S12/S22 mirrors S11; "
                 "no independent physics) [aurora_q Fix2]")
        sparams_path.write_text(_note + "\n" + _hdr, encoding="utf-8")
    solve_meta["nominal_n_ports"] = int(n_ports)
    solve_meta["exported_n_ports"] = net_ports

    metrics_data = {
        "run_id": run_id,
        "plugin_version": "template-direct",
        "schema_version": recipe_data.get("schema_version", 1),
        "params": {k: (v["value"] if isinstance(v, dict) else v)
                   for k, v in params_data.items()},
        "metrics": metrics,
        "cost": cost,
        "checks": {
            "passivity_ok": SpecEvaluator.check_passivity(network),
            "reciprocity_ok": SpecEvaluator.check_reciprocity(network),
            "sanity_all_ok": sanity.all_ok,
            "sanity_notes": sanity.notes,
        },
    }
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps(metrics_data, indent=2, ensure_ascii=False),
        encoding="utf-8")

    freqs_ghz = np.asarray(network.f, dtype=float) / 1e9
    freq_data: dict[str, Any] = {"freqs": freqs_ghz.tolist()}
    freq_data["s11_db"] = (
        20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-15)).tolist()
    if network.s.shape[1] >= 2:
        freq_data["s21_db"] = (
            20.0 * np.log10(np.abs(network.s[:, 1, 0]) + 1e-15)).tolist()
    obj_specs = {
        o.metric: {"target": f"{o.op} {o.value}", "band": list(o.band)}
        for o in objectives
    }
    report_path = generate_report(
        run_dir, metrics, objectives=obj_specs, freq_data=freq_data)

    meta_path = write_meta(run_dir, {
        "run_id": run_id,
        "package_version": __version__,
        "plugin_version": "template-direct",
        "schema_version": recipe_data.get("schema_version", 1),
        "adapter": adapter_name,
        "aedt_version": "n/a",
        "ads_version": "n/a",
        "user": getpass.getuser(),
        "hostname": platform.node(),
        "model": family,
        "template": family,
        "status": "done",
        "study_name": study or run_id,
        "cache": {"provenance": "not_applicable",
                  "note": "模板直跑配方暂未接入缓存键面（models 插件版本成分缺位）"},
        "metrics": metrics,
        # #248 家族掩码语义（#314）：名义端口 vs 导出端口（openEMS 通道
        # 对名义 1 端口模板回填对称 2×2 时二者不同——消费方据此分辨
        # 填充面，off-diagonal 非独立测量）；Fix2（专利4）：filled_ports
        # 显式布尔（外部使用者据识别“单端口填充”形态，不再判数据异常）。
        "nominal_n_ports": int(n_ports),
        "filled_ports": bool(net_ports != n_ports),
        "exported_n_ports": int(net_ports),
        # Fix4c（专利4）：solver_versions 溯源（模板链此前缺省空 dict——
        # 取证口径“求解器版本”须落 meta；best-effort=load_solver_versions
        # 的 configs/绑定版本口径，exe --version 探针=后续项）。
        "solver_versions": _load_solver_versions_best_effort(),
    }, engine_identity=engine_identity)
    record_run(record=json.loads(meta_path.read_text(encoding="utf-8")))

    if _report is not None:
        _report(100.0, "done")
    return ok_envelope(
        run_id=run_id,
        run_dir=str(run_dir),
        template=family,
        form="template",
        adapter=adapter_name,
        metrics=metrics,
        cost=cost,
        solve_report=solve_meta,
        cache={"provenance": "not_applicable"},
        report=str(report_path),
        touchstone=str(sparams_path),
    )
