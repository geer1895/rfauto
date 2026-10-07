"""diagnose/compare_runs/get_run_artifacts/get_model_3d/list_calculators/run_calculator（run 判读与计算器注册表）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import _run_model_name as _run_model_name
from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope


@mcp.tool
def diagnose(run_id: str) -> dict[str, Any]:
    """run 规则诊断（runs 域）：run_id → 指标规则诊断（确定性零 LLM）。

    读取 run 的指标（metrics.json）并重跑规则诊断；模型名 best-effort
    取自 run 的 meta.json（决定规则适用域）。结果可复现，与 create_run
    落盘的 metrics.json diagnosis 段同源同语义；不修改 run 状态。
    无副作用，可安全调用。run 缺失/无指标 → ok=False errors 如实。
    只读无时序约束。

    Args:
        run_id: 运行 ID

    Returns:
        dict: {ok, data: {diagnoses, suggestions, initial_values, rules_applied}}
    """
    from rfauto.service.api import get_metrics as _get_metrics
    fetched = _get_metrics(run_id)
    if not fetched.get("ok"):
        return error_envelope(
            fetched.get("errors") or [f"未找到 run: {run_id}"])
    metrics = (fetched.get("data") or {}).get("metrics")
    if not isinstance(metrics, dict):
        return error_envelope([f"run 无指标数据: {run_id}"])
    from rfauto.infra.diagnosis import diagnose_results
    result = diagnose_results(metrics, model_name=_run_model_name(run_id))
    return ok_envelope(data=result)

# ─── 12. compare_runs ─────────────────────────────────────────────────────────

@mcp.tool
def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    """双 run 对比（runs 域）：A/B run id → 逐指标 B-A 增量+cost 对照。

    无副作用，可安全调用；不用于单 run 判读（走 get_metrics/diagnose）。
    任一 run 缺失 → ok=False 如实。只读无时序约束。

    Args:
        run_id_a: 基准 run ID
        run_id_b: 对比 run ID

    Returns:
        dict: {ok, data: {metrics: {k: {a, b, delta}}, cost_a, cost_b}}；
        run 缺失 → ok=False
    """
    from rfauto.service.api import compare_runs as _compare_runs
    return _compare_runs(run_id_a, run_id_b)


# ─── run_monitor（SO-1 孤儿接线批 W1-A 单元 15a：run 周期体检面） ─────────────

@mcp.tool
def run_monitor(run_dir: str, cycle: bool = False,
                nr_ts: int | None = None) -> dict[str, Any]:
    """run 体检（runs 域）：run 目录 → 四类时序判据 verdict（零 LLM）。

    G11 门周批化。判据：进度（port_ut 末行时间轴 #268）/截断嫌疑（et 末值/
    峰值比 #262）/NrTS 触顶（给了 nr_ts 才判）/能量停滞（衰减率下限 #323）。
    目录无时域产物 → verdict=unknown 如实回显；目录不存在 → ok=False。
    只读 run 产物，无副作用，可安全调用，无时序约束。

    Args:
        run_dir: run 目录（--cycle 时为 runs 根目录，产物在目录本身或 fdtd）
        cycle: true=周期面（对目录下全部 run 逐个体检并聚合红/黄/unknown
            名单与 snapshots）；false（缺省）=单 run 体检
        nr_ts: 引擎 NrTS 上限（给了才做触顶判据，取自 meta/config）

    Returns:
        dict: 单 run ``{ok, run_id, verdict: green|yellow|red|unknown,
        checks, reasons}``；周期面 ``{ok, n_monitored, verdicts, red,
        yellow, unknown, snapshots}``；目录不存在 → ok=False
    """
    from rfauto.service.runtime_monitor_service import monitor_cycle, monitor_run_dir

    if cycle:
        return monitor_cycle(run_dir, nr_ts=nr_ts)
    return monitor_run_dir(run_dir, nr_ts=nr_ts)


# ─── 13/14. 人工核验辅助（rfauto ui 同源服务层） ──────────────────────────────

@mcp.tool
def get_run_artifacts(run_id: str) -> dict[str, Any]:
    """run 产物清单（runs 域）：run_id → 文件清单+metrics+S 参数摘要。

    无副作用，可安全调用；人工核验请打开 rfauto ui（CLI: rfauto ui），
    本工具不用于产物修改。run 缺失 → ok=False 如实。只读无时序约束。

    Args:
        run_id: 运行 ID（runs/ 目录名）

    Returns:
        dict: {ok, data: {files: [...], metrics: {...}, sparams: [...]}}；
        run 缺失 → ok=False
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.ui_service import run_detail
    return annotate_contract("run_detail", run_detail(run_id))


@mcp.tool
def get_model_3d(recipe_path: str) -> dict[str, Any]:
    """配方 3D 几何 spec（runs 域）：配方路径 → 毫米 boxes 列表（核验面）。

    无副作用，可安全调用；仅 wilkinson/patch 模板支持，其余模板 →
    ok=False 如实（不硬造几何）；不用于渲染执行。只读无时序约束。

    Args:
        recipe_path: 配方文件路径（YAML 格式）

    Returns:
        dict: {ok, data: {template, substrate, boxes: [{name, material, start_mm, stop_mm}]}}；
        不支持的模板 → ok=False
    """
    from rfauto.service.ui_service import model3d_for_recipe
    return model3d_for_recipe(recipe_path)


@mcp.tool
def list_calculators(include_experimental: bool = True) -> dict[str, Any]:
    """计算器名单（runs 域）：注册表 → 名字/说明/参数表（mm/GHz/Ω/dB）。

    E4。只读注册表面，无副作用；纯清单面恒 ok=True（无 ok=False 分支），
    空注册如实回空清单。实验性公式（experimental=True，如符号回归归纳
    公式）默认一并列出并带 experimental: true 标签；运行仍需
    run_calculator(allow_experimental=True) 或配置放行；不用于执行（走
    run_calculator）。只读无时序约束。

    Args:
        include_experimental: False 时清单剔除实验键（n_experimental/
            experimental 名单仍如实报告）

    Returns:
        dict: {ok, calculators: [{name, description, params, experimental}],
               include_experimental, n_experimental, experimental: [名单]}
    """
    from rfauto.service.calculator_service import list_calculators as _list
    return _list(include_experimental=include_experimental)


@mcp.tool
def run_calculator(
    name: str,
    params: dict[str, Any] | None = None,
    allow_experimental: bool | None = None,
) -> dict[str, Any]:
    """执行微波闭式计算器（微带/CPW/带状线正反解、λ/4 变换、π/T 衰减器、
    驻波换算、λg、贴片谐振长度）。

    名单先 list_calculators 查询。示例：
    run_calculator("microstrip_synthesis", {"z0_ohm": 50, "freq_ghz": 2.4,
    "epsilon_r": 3.66, "h_mm": 0.508})

    实验性公式（list_calculators 标 experimental: true）默认拒跑：
    allow_experimental=True 显式放行；False 显式拒绝（优先于配置）；
    缺省（null）读配置 calculators.allow_experimental / 环境变量
    RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL。数值只出自确定性内核（铁律 7）。
    未知名/非法参数 → ok=False error 信封；不用于时域仿真。只读无时序约束。

    Args:
        name: 计算器名
        params: 参数字典（mm/GHz/Ω/dB 口径）
        allow_experimental: 实验性公式放行开关（True/False/null 三态）

    Returns:
        dict: {ok, calculator, params, result, experimental} 或
              {ok: False, error, experimental?}
    """
    from rfauto.service.calculator_service import run_calculator as _run
    return _run(name, params, allow_experimental=allow_experimental)
