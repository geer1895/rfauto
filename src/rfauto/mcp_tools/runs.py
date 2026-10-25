"""diagnose/compare_runs/get_run_artifacts/get_model_3d/list_calculators/run_calculator（run 判读与计算器注册表）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。

aurora_l Wave-C C4（2026-10-23，R1 #17）：diagnose/compare_runs 接
verify 四态——诊断/对比结论此前建立在未验产物上（用户病灶：交付图引用
旧 sNp 而无机制发现）。diagnose 响应增 ``freshness`` 块（四态+issues
摘要；stale 时结论头部加醒目 ``stale_warning`` 行）；compare_runs 增
行级 freshness 列（照 aurora_l Wave-A A3 席 batch_ops 行级列先例）。
校验走 ``runs_verify_service.verify_run`` 单源只读；观测面故障不阻塞
主路径（#105）。本文件仍不产数值（铁律 7）：freshness 只是既有内核的
只读校验结果透传。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.mcp_tools._core import _run_model_name as _run_model_name
from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

#: stale 时诊断结论头部的醒目提示行（agent 可读人话，R1 #17 验收原话）。
_STALE_DIAG_WARNING = "结果文件与 run 记录不符，以下诊断可能基于旧产物"

#: freshness 块 issues 摘要明细条数上限（防巨 issues 刷爆 agent 上下文；
#: 全量计数走 n_issues，判读看 status 与 note 不看逐条）。
_FRESHNESS_ISSUES_CAP = 8


def _run_freshness(run_dir: Path) -> dict[str, Any]:
    """run 目录 → freshness 摘要块（runs_verify_service.verify_run 单源只读）。

    四态透传：fresh/stale/legacy/error（verify 信封 status 原样）+
    unknown（校验面自身故障，#105 观测面不阻塞主路径）。形态对齐
    aurora_l Wave-A A3 席 batch_ops_service._freshness_column 行级列
    （stale 注记点名 kinds；legacy 放行带 note）；verify 的 issues 全量
    摘成 kind+path 紧凑行（上限 _FRESHNESS_ISSUES_CAP 条，n_issues 记
    全量）。
    """
    try:
        from rfauto.service.runs_verify_service import verify_run

        verdict = verify_run(run_dir)
    except Exception as exc:  # 校验面故障如实 unknown 不阻塞（#105）
        return {"status": "unknown",
                "note": f"新鲜度校验不可用（非阻断）: {exc}",
                "issues": [], "n_issues": 0}
    status = str(verdict.get("status", "unknown"))
    note = str(verdict.get("note") or "")
    issues = [issue for issue in (verdict.get("issues") or [])
              if isinstance(issue, dict)]
    if status == "stale":
        kinds = ",".join(sorted({str(issue.get("kind")) for issue in issues
                                 if issue.get("kind")}))
        note = f"stale（{kinds}）：盘上产物与 run 收官指纹不符，采信前先复核"
    return {
        "status": status,
        "note": note,
        "issues": [{"kind": str(issue.get("kind")),
                    "path": str(issue.get("path", ""))}
                   for issue in issues[:_FRESHNESS_ISSUES_CAP]],
        "n_issues": len(issues),
    }


@mcp.tool
def diagnose(run_id: str) -> dict[str, Any]:
    """run 规则诊断（runs 域）：run_id → 指标规则诊断（确定性零 LLM）。

    重跑规则诊断并与 create_run 落盘 diagnosis 同源同语义；响应带
    freshness 四态块（stale 时结论头部加 stale_warning 提示行——诊断
    数字可能基于旧产物，采信前先复核，不硬拒）。
    无副作用，可安全调用。run 缺失/无指标 → ok=False errors 如实。
    只读无时序约束。

    Args:
        run_id: 运行 ID

    Returns:
        dict: {ok, data: {diagnoses, suggestions, initial_values,
        rules_applied, freshness: {status: fresh/stale/legacy/error|
        unknown, note, issues: [{kind, path}], n_issues}}}；stale 时
        data 头部另有 stale_warning 提示行（freshness 语义细则：
        verify_run 单源只读 K4，校验面故障如实 unknown——AD-5 载荷
        守卫增量 ≤120，模型名 best-effort 取 meta.json）
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
    # freshness 校验（aurora_l Wave-C C4，R1 #17）：诊断读的就是
    # runs/<run_id>/results/metrics.json——校验同一根的收官指纹，产物
    # 被顶替/漏拷（stale）时结论头部醒目提示"可能基于旧产物"。
    freshness = _run_freshness(Path("runs") / run_id)
    if freshness["status"] == "stale":
        result = {"stale_warning": _STALE_DIAG_WARNING, **result}
    result["freshness"] = freshness
    return ok_envelope(data=result)

# ─── 12. compare_runs ─────────────────────────────────────────────────────────

@mcp.tool
def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    """双 run 对比（runs 域）：A/B run id → 逐指标 B-A 增量+cost 对照，
    逐侧带四态 freshness 行级列（stale 标红不硬拒，notes 点名脏侧）。
    无副作用；不用于单 run 判读（走 get_metrics/diagnose）。
    任一 run 缺失 → ok=False 如实。

    Args:
        run_id_a: 基准 run ID
        run_id_b: 对比 run ID

    Returns:
        dict: {ok, data: {metrics: {k: {a, b, delta}}, cost_a, cost_b,
        freshness: [{side, run_id, freshness, freshness_note}], notes?}}；
        run 缺失 → ok=False
    """
    from rfauto.service.api import compare_runs as _compare_runs
    result = _compare_runs(run_id_a, run_id_b)
    if not result.get("ok"):
        return result
    # freshness 列（aurora_l Wave-C C4，R1 #17）：对比结论此前建立在
    # 未验产物上——逐侧 verify_run 出行级列；校验目录与 get_metrics
    # 同根（runs/<run_id>），验证的就是刚读的产物。
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for side, rid in (("a", run_id_a), ("b", run_id_b)):
        freshness = _run_freshness(Path("runs") / rid)
        rows.append({"side": side, "run_id": rid,
                     "freshness": freshness["status"],
                     "freshness_note": freshness["note"]})
        if freshness["status"] == "stale":
            notes.append(
                f"freshness: {rid} 标记 stale（盘上产物与 run 收官指纹"
                "不符）——对比结论采信前先处理该侧数据")
    data = result.setdefault("data", {})
    data["freshness"] = rows
    if notes:
        data["notes"] = notes
    return result


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
        run_dir: run 目录（--cycle 时为 runs 根目录，产物在目录本身或 fdtd/）
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
