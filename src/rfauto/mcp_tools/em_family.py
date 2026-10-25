"""em 族五只读薄壳工具（aurora_l Wave-C C1 席，2026-10-23）。

aurora_k 落了 em doctor/sweep/diff/metrics+runs verify 全 CLI 叶，MCP 面
零覆盖（反馈 F5：MCP agent 摸不到 runs/ 历史核验、质量门判读与收敛门
结论，"猜的成分"大）。本文件补五只读/低危薄壳，全部零逻辑转发 service
层单源（规则 4/D2：信封进出在 service，本文件只做参数透传+异常兜底）；
与 CLI 域（cli/domains/em.py；runs verify 挂 surrogate.py）同源同名
service 函数。sweep 的执行面（run_sweep，真机串行+资源闸）**不上 MCP**——
v1 只读 plan 面；体检/验证/diff/metrics 全部只读 run 产物与清单文件。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope


@mcp.tool
def em_doctor_check(manifest_path: str) -> dict[str, Any]:
    """EM 模型清单体检（em doctor）：清单文件 → 16 项几何/端口语义检查报告。

    什么时候用：HFSS/AEDT 求解**之前**——清单（YAML/JSON inventory）驱动
    的 pre-solve 语义体检，把"aperture 不含金属/端口不在边界/植球短信号/
    薄层竖墙"在建模阶段拦下，而不是解出 L≈0.135 nH 假结果后再人肉追查
    （HFSS ValidateDesign 只查语法不查端口语义）。与 CLI
    ``rfauto em doctor`` 同源。无副作用（只读清单与盘上 S 参数），可安全
    调用；不用于渲染/执行（那是 create_run 的面）。清单缺失/后缀非法/
    条目畸形 → ok=False errors 如实（不猜不凑）。只读无时序约束。

    Args:
        manifest_path: 模型清单文件路径（.yaml/.yml/.json；schema 见
            service/em_doctor_service.py 模块 docstring）

    Returns:
        dict: {ok, verdict: PASS|FAIL, checks: [16 行，每行 check/table_ref/
        status/catches/detail], summary: {n_pass, n_fail, n_warn, n_skip,
        n_skip_v2}, manifest_dir}；任一 FAIL → ok=False（verdict=FAIL 是
        体检结论不是调用失败）；装载失败 → ok=False errors
    """
    from rfauto.service.em_doctor_service import doctor_from_file

    try:
        return doctor_from_file(manifest_path)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def runs_verify(run_id_or_dir: str) -> dict[str, Any]:
    """run 产物新鲜度校验（runs verify）：manifest 收官指纹 vs 盘上产物。

    什么时候用：采信一个 run 的 S 参数/指标**之前**——run 收官时登记的
    sha256 指纹逐一对照盘上 Touchstone/曲线 CSV/recipe 快照，抓"交付错配"
    （产物被顶替/丢失/手改）。与 CLI ``rfauto runs verify`` 同源。入参
    双口径：显式 run 目录优先，回退 ``runs/<run_id>``。无副作用（纯只读
    哈希比对），可安全调用。status 四态：fresh（ok=True）/stale（ok=False，
    issues 列 mismatch/missing/sidecar 明细）/legacy（ok=True，老 run 无
    manifest 放行+note 说明）/error（目录不存在等，ok=False）。只读无
    时序约束。

    Args:
        run_id_or_dir: run 目录路径，或 runs/ 湖下的 run_id 目录名

    Returns:
        dict: {ok, run_id, status: fresh|stale|legacy|error, issues: [
        {kind, path, detail, ...}], note?}；stale 的 issues 逐条给证据
        （盘上 sha vs 登记 sha）
    """
    from rfauto.service.runs_verify_service import resolve_run_dir, verify_run

    try:
        return verify_run(resolve_run_dir(run_id_or_dir))
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def em_diff_runs(run_a: str, run_b: str,
                 sections: str = "params,manifest,sparams") -> dict[str, Any]:
    """两个 run 目录的四节对比（em diff）：替代手工 diff .aedt 文本。

    什么时候用：回答"这两个 run 差在哪"——params=meta.json 逐键（新增/
    删除/变更）；manifest=em doctor 模型清单按 name 逐项（对象/端口/叠层/
    keepout 增删改，bbox 变化按轴紧凑渲染）；sparams=两 run Touchstone
    同栅对拍（差异最大频点+dev dB）；freshness=runs verify 两侧状态行
    （恒出，不随裁剪）。入参是 run **目录**路径（不是 runs 湖 run_id
    ——那是 compare_runs 的口径）。与 CLI ``rfauto em diff`` 同源。无
    副作用（纯只读），可安全调用。目录不存在/未知节名 → ok=False errors；
    缺节如实 status="skip"+原因，不伪造空 diff。只读无时序约束。

    Args:
        run_a: run 目录 A（旧）
        run_b: run 目录 B（新）
        sections: 逗号分隔对比节（params/manifest/sparams 子集；
            freshness 恒出）

    Returns:
        dict: {ok, run_a, run_b, params_changes, model_changes,
        sparam_diff: {status, worst_freq_hz, worst_dev_db, ...},
        freshness: {a, b}, summary}；失败 → ok=False errors
    """
    from rfauto.service.em_diff_service import diff_runs

    requested = [s.strip() for s in str(sections).split(",") if s.strip()]
    try:
        return diff_runs(run_a, run_b, sections=requested)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def em_metrics_from_run(run_dir: str,
                        at_ghz: float | None = None) -> dict[str, Any]:
    """run 目录器件指标提取+同族绑定（em metrics --run）：L/Q/SRF/C/R/S21。

    什么时候用：run 跑完要读器件指标——双路读数（metrics.json 主口径 +
    Touchstone 家族键补充）后按 core.metric_groups 同族绑定：series 族
    Q 在场自动附 C/R/S21 并提示"Q 随 C 变，不是纯损耗"；族判不出按原始
    读数输出+errors 如实（不猜族）。at_ghz 给定点读数频率（GHz，缺省
    None=全带）。与 CLI ``rfauto em metrics --run`` 同源。无副作用（纯
    只读），可安全调用；网格收敛两档判定（converged-with）不在本工具——
    走 CLI 叶或 service.convergence_check。目录不存在/双路全空 →
    ok=False errors。只读无时序约束。

    Args:
        run_dir: run 目录路径
        at_ghz: 定点读数频率 GHz（None=全带提取）

    Returns:
        dict: {ok, run_dir, metrics: {家族键...}, binding: {group, family,
        advisory, missing}, sources, mesh, notes, errors}；失败 →
        ok=False errors
    """
    from rfauto.service.em_metrics_service import em_metrics_from_run as _fn

    try:
        return _fn(run_dir, f_eval_ghz=at_ghz)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def em_sweep_plan(cases_yaml: str) -> dict[str, Any]:
    """DOE/矩阵 sweep 只读展开（em sweep plan 面）：cases.yaml → 逐 case 计划。

    什么时候用：跑矩阵**之前**预览展开——cases.yaml 笛卡尔全积展开成逐
    case 计划（case_id/axes/params/case_dir），报告 sweep_id/sweep_root/
    n_cases 与 resume 完成判定账（n_done/n_pending）。**不执行**：执行面
    （真机串行+内存闸+janitor）不上 MCP，确认计划后走 CLI
    ``rfauto em sweep``。与 CLI 同源同名 service 函数 plan_sweep（缺省
    resume=False=全部 pending 的纯读展开）。无副作用（零执行零落盘），
    可安全调用。cases.yaml/base_recipe 缺失、adapter 非法、矩阵畸形 →
    ok=False errors 点名原因。只读无时序约束。

    Args:
        cases_yaml: cases 配置文件路径（base_recipe 相对其所在目录解析）

    Returns:
        dict: {ok, sweep_id, sweep_root, adapter, base_recipe, n_cases,
        n_done, n_pending, convergence_axis, cases: [{case_id, axes,
        params, case_dir, status}]}；失败 → ok=False errors
    """
    from rfauto.service.em_sweep_service import plan_sweep

    try:
        return plan_sweep(cases_yaml)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
