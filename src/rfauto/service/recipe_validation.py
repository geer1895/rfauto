"""配方 schema 单一事实源 + did-you-mean 助手（aurora_n 旅程席 A，F-P1-1）。

三处消费同一单源（#97 防漂移）：

- ``service/api/run_core.py::validate_recipe``：键级白名单校验（CLI validate /
  run·tune·sweep ``--dry-run`` / MCP validate_recipe / UI recipe_save /
  batch validate 六通道同源）；
- ``docs/reference.md``「配方 schema」节：键表 / ops 枚举 / 指标名清单，
  由 ``tests/unit/test_recipe_schema_doc.py`` 钉住（漂移即门红）；
- ``tests/unit/test_recipe_validation.py``：行为面单测。

ops 枚举单源=``core/objectives.MetricOp``（4 值）；指标名清单单源=
``core/objectives.OBJECTIVE_METRIC_NAMES``；本模块只持有顶层键白名单与
参数面解析。did-you-mean 单源：:func:`did_you_mean`
（difflib.get_close_matches 一次实现，顶层键/参数名/指标名三处消费）。

兼容性口径（2026-10-30；recipes/ 份数 2026-10-31 复核=6 份）：
- 顶层键白名单覆盖全仓配方消费面实测键（recipes/ 6 份 + run/tune/sweep/
  tolerance/refine/p0/autotune/calibration/campaign/sandbox 服务消费键）；
  新增合法顶层键必须先落 ``RECIPE_TOP_LEVEL_KEYS``（本模块头注即登记处）。
- ``objectives`` 键**缺席**合法（plain run 只出 S 参数/指标不出 cost）；
  **在场但为空**硬错（无目标=必然无意义，UI recipe_save 同严）。
- 参数面动态解析自模型插件 ``params_model.model_fields``（4 内置模型 +
  entry-point 第三方插件同口径）；模型未注册/非标准 params_model 时跳过
  参数名校验（模型未知已另有 error，不重复报）。
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any

# ─── 顶层键白名单（单源；键 → 一句话语义） ────────────────────────────────────

RECIPE_TOP_LEVEL_KEYS: dict[str, str] = {
    "model": "目标模型（models 注册表键；必需）",
    "params": "设计参数（键=该模型 params_model 字段名；必需）",
    "setup": "仿真设置（name/sweep_name/freq_range_ghz/points/convergence_delta/"
             "max_passes/minimum_passes/solver/radiation_box；可选）",
    "objectives": "优化目标（缺席合法=plain run；在场不可为空）",
    "optimization": "调参段（params 搜索空间/constraints 约束；可选）",
    "limits": "配额（max_trials/max_wall_hours；可选）",
    "export": "导出选项（touchstone.renorm_ohm/deembed；可选）",
    "ops": "变异算子（optimization/mutation 消费；可选）",
    "tolerance": "公差分析（tolerances/n_samples；tolerance 命令消费；可选）",
    "units": "单位制 mm（缺省）/um（K9 P15 IPD 工艺；可选）",
    "design_name": "HFSS 设计名（缺省 RFADesign；可选）",
    "recipe_version": "配方 schema 版本（与插件 schema_version 语义区分，#106；可选）",
    "schema_version": "插件参数 schema 版本（可选）",
    "notes": "人类备注（可选）",
}

#: 必需键（缺席即 error；现状口径：model/params 必需，setup 缺席仅 warning）。
REQUIRED_RECIPE_KEYS: tuple[str, ...] = ("model", "params")

#: objectives 元素/optimization.constraints 元素里承载指标名的键。
_METRIC_FIELD = "metric"

# ─── did-you-mean（单源） ────────────────────────────────────────────────────


def did_you_mean(name: str, candidates: Any) -> str:
    """拼"你是不是想写 'X'？"后缀（无接近候选返回空串）。

    单源约定（任务红线）：difflib.get_close_matches 一次实现，顶层键/
    参数名/指标名三处共用；确定性（同输入同输出，#118 不适用于校验面）。
    """
    names = [str(c) for c in candidates]
    hits = get_close_matches(str(name), names, n=1, cutoff=0.6)
    return f"（你是不是想写 '{hits[0]}'？）" if hits else ""


# ─── 参数面（动态，来自模型插件 params_model） ────────────────────────────────


def template_param_surface(model_name: str) -> set[str] | None:
    """模型合法参数名集合（params_model 字段）；不可得时返回 None（跳过校验）。

    - 模型未注册 → None（validate_recipe 的"未知模型" error 已覆盖，不重复报）；
    - params_model 非 pydantic v2 形态（无 model_fields，第三方插件兜底）→
      None（宁跳过不误伤）。
    """
    from rfauto.models.registry import get  # lazy: service→models 合法向下

    try:
        plugin_cls = get(str(model_name))
    except KeyError:
        return None
    except TypeError:
        return None  # model 非字符串形态（畸形配方）——参数面跳过，不新增崩溃面
    fields = getattr(getattr(plugin_cls, "params_model", None), "model_fields", None)
    if not fields:
        return None
    return {str(k) for k in fields}


# ─── 键级白名单校验（纯函数；validate_recipe 消费） ───────────────────────────


def _metric_errors(section: str, entries: Any) -> list[str]:
    """objectives / optimization.constraints 共用的指标名白名单检查。"""
    from rfauto.core.objectives import OBJECTIVE_METRIC_NAMES  # lazy: core 轻载

    errors: list[str] = []
    if entries is None:
        return errors
    if not isinstance(entries, list):
        errors.append(f"{section} 必须是列表，实际: {type(entries).__name__}")
        return errors
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue  # 非 dict 元素交给 pydantic/Objective 构造面报错（run_core）
        metric = entry.get(_METRIC_FIELD)
        if not isinstance(metric, str) or not metric:
            continue  # 缺 metric/非字符串由 Objective 必填校验报错
        if metric not in OBJECTIVE_METRIC_NAMES:
            errors.append(
                f"{section}[{i}] 未知指标名: {metric}"
                f"{did_you_mean(metric, sorted(OBJECTIVE_METRIC_NAMES))}"
                f"（合法指标名清单见 docs/reference.md「配方 schema」节）")
    return errors


def _param_name_errors(
    section: str, params_section: Any, surface: set[str] | None,
) -> list[str]:
    """params / optimization.params 共用的参数名白名单检查。"""
    errors: list[str] = []
    if params_section is None:
        return errors
    if not isinstance(params_section, dict):
        errors.append(f"{section} 必须是映射（键=参数名），实际: "
                      f"{type(params_section).__name__}")
        return errors
    if surface is None:
        return errors  # 模型未注册/非标准参数面 → 跳过（不重复报、不误伤）
    for name in params_section:
        if not isinstance(name, str) or name in surface:
            continue
        errors.append(
            f"{section} 未知参数: {name}{did_you_mean(name, sorted(surface))}"
            f"（模型合法参数面见 rfauto models list --schema <model>）")
    return errors


def recipe_schema_errors(data: dict[str, Any]) -> list[str]:
    """键级白名单校验（F-P1-1，对齐 UI recipe_save 严格度）。

    ①未知顶层键 → error + did-you-mean；
    ②params / optimization.params 参数名不在模板参数面 → error + did-you-mean；
    ③objectives / optimization.constraints 指标名不在指标词典 → error + did-you-mean；
    ④objectives 在场但为空 → error（无目标=必然无意义；缺席合法=plain run）。

    纯函数：只读 data，不触文件/注册表重载（参数面经 models.registry
    既有进程内注册表，确定性）。
    """
    errors: list[str] = []

    # ① 顶层键白名单
    for key in data:
        if key not in RECIPE_TOP_LEVEL_KEYS:
            errors.append(
                f"未知顶层键: {key}{did_you_mean(key, RECIPE_TOP_LEVEL_KEYS)}"
                f"（合法键与语义见 docs/reference.md「配方 schema」节）")

    # 参数面一次解析（模型已注册时才有 surface；未注册 → 各参数名校验跳过）
    surface = template_param_surface(str(data["model"])) if data.get("model") else None

    # ② params 参数名
    errors.extend(_param_name_errors("params", data.get("params"), surface))

    # ③④ objectives：缺席合法；在场必须是非空列表（null/空列表均 ④ 硬错）
    objectives = data.get("objectives")
    if "objectives" in data and objectives is None:
        errors.append(
            "objectives 为空值（null）——请给出目标列表，或删除该键（plain run）")
    elif isinstance(objectives, list) and not objectives:
        errors.append(
            "objectives 为空：配方无目标=必然无意义（plain run 请删除 "
            "objectives 键；run/tune 配方至少给 1 条目标）")
    errors.extend(_metric_errors("objectives", objectives))

    # ②③ optimization 段：params 键入参数面、constraints 指标名入词典
    optimization = data.get("optimization")
    if optimization is not None and not isinstance(optimization, dict):
        errors.append(f"optimization 必须是映射，实际: {type(optimization).__name__}")
    elif isinstance(optimization, dict):
        errors.extend(_param_name_errors(
            "optimization.params", optimization.get("params"), surface))
        errors.extend(_metric_errors(
            "optimization.constraints", optimization.get("constraints")))

    return errors
