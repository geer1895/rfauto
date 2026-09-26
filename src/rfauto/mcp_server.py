"""MCP Server（§7.7）—— fastmcp 首版 7 个核心工具。

设计红线：
- mutating 工具必须显式描述副作用
- 不提供 delete 类破坏性工具
- 所有工具返回 {ok, data|error} 信封
- input schema 直接复用 pydantic 生成的 JSON Schema
- 写操作受 JobRegistry/单写约束；长仿真用 create_run_async（C3 修复）
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ─── Lifespan：解决 uv venv python shim + fastmcp stdio 首工具卡死 ──────────
# 根因（2026-08-30 排障）：uv venv python shim 重定向子进程时，
# 首个 call_tool 触发的延迟 import 在 stdio 管道上产生初始化阻塞。
# 对策：在 lifespan startup 预导入核心模块 + 静音 pyaedt，将初始化
# 成本从首次工具调用提前到服务器启动阶段。

@asynccontextmanager
async def _server_lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """服务器启动生命周期：预导入核心模块，解决首工具卡死。"""
    # 1. 静音 pyaedt 屏幕日志（stdio 通道保护）
    _silence_pyaedt_screen_logs()
    # 2. 预导入核心模块——flush 出延迟 import 的初始化副作用
    try:
        import rfauto.core.objectives
        import rfauto.core.parameters
        import rfauto.models.registry
        import rfauto.service.api  # noqa: F401
    except Exception:
        pass  # fake 通道/无 license 环境不受影响
    yield {}


# 创建 MCP 服务器实例
mcp = FastMCP(
    name="rfauto",
    instructions=(
        "rfauto HFSS ↔ ADS 自动化仿真调优框架的 MCP 服务器。"
        "提供环境探测、模型管理、配方校验、仿真执行、任务轮询、指标读取等工具。"
    ),
    lifespan=_server_lifespan,
)


def _silence_pyaedt_screen_logs() -> None:
    """静音 pyaedt 的屏幕日志（真机排障发现，2026-08-30）。

    stdio 传输下 server 的 stdout 是 MCP 协议通道；pyaedt 默认把
    "PyAEDT INFO: ..." 写到 stdout，客户端会收到非法 JSONRPC 消息。
    SDK 只在适配器内使用（军规 8），此处 import 失败则静默跳过
    （fake 通道/无 license 环境不受影响）。
    """
    try:
        from ansys.aedt.core.generic.settings import settings

        settings.enable_screen_logs = False
    except Exception:
        pass


# ─── 1. doctor ─────────────────────────────────────────────────────────────

@mcp.tool
def doctor() -> dict[str, Any]:
    """环境探测：检查 AEDT/ADS 版本、license、路径、已测试版本组合核对。

    无副作用，可安全调用。

    Returns:
        dict: {ok: bool, checks: [{name, status, detail}]}
    """
    from rfauto.service.api import doctor as _doctor
    return _doctor()


# ─── 2. list_models ────────────────────────────────────────────────────────

@mcp.tool
def list_models() -> dict[str, Any]:
    """列出已注册的模型插件。

    无副作用，可安全调用。

    Returns:
        dict: {ok: bool, models: [str]}
    """
    from rfauto.service.api import list_models as _list_models
    return _list_models()


# ─── 3. validate_recipe ────────────────────────────────────────────────────

@mcp.tool
def validate_recipe(recipe_path: str) -> dict[str, Any]:
    """校验配方文件，不执行仿真。

    无副作用，可安全调用。

    Args:
        recipe_path: 配方文件路径（YAML 格式）

    Returns:
        dict: {ok: bool, errors: [str], warnings: [str]}
    """
    from rfauto.service.api import validate_recipe as _validate_recipe
    return _validate_recipe(recipe_path)


# ─── 4. create_run ─────────────────────────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def create_run(
    recipe_path: str,
    adapter: str = "fake",
) -> dict[str, Any]:
    """提交仿真任务，返回 run_id。

    副作用：创建 run 目录、写入 meta.json、登记 SQLite 索引。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        adapter: 适配器名称，"fake"（默认）或 "hfss"

    Returns:
        dict: {ok: bool, run_id: str, run_dir: str, metrics: dict, cost: float}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.api import run_once
    result = run_once(recipe_path, adapter_name=adapter)
    return result


# ─── 5. create_run_async ────────────────────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def create_run_async(
    recipe_path: str,
    adapter: str = "fake",
) -> dict[str, Any]:
    """异步提交仿真任务，立即返回 job_id（适用于 HFSS 等长仿真）。

    副作用：后台线程执行 create_run 的全部动作（创建 run 目录、写 meta.json、
    登记 SQLite 索引）。用 poll_job(job_id) 轮询状态。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        adapter: 适配器名称，"fake"（默认）或 "hfss"

    Returns:
        dict: {ok: bool, job_id: str, state: str}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.api import run_once_async
    return run_once_async(recipe_path, adapter_name=adapter)


# ─── 6. poll_job ───────────────────────────────────────────────────────────

@mcp.tool
def poll_job(job_id: str) -> dict[str, Any]:
    """轮询任务状态。

    无副作用，可安全调用。与 CLI rfauto jobs status 读同一份持久化状态。

    Args:
        job_id: 任务 ID（即 run_id）

    Returns:
        dict: {ok: bool, job_id: str, state: str, progress_pct: float, message: str, metrics: dict}
    """
    from rfauto.service.api import poll_job as _poll_job
    return _poll_job(job_id)

@mcp.tool
def cancel_job(job_id: str) -> dict[str, Any]:
    """协作取消长任务（DP-14 A1：透传 JobRegistry.cancel；硬杀求解进程不支持）。

    取消语义：置 cancelled 标志，运行中的仿真在下一个协作检查点退出；
    cancel 后 poll_job 终态=cancelled。

    Args:
        job_id: create_run_async 返回的任务 id

    Returns:
        dict: {ok, job_id, status, ...}
    """
    from rfauto.service.job_registry import get_job_registry
    reg = get_job_registry()
    out = reg.cancel(job_id)
    if out is None:
        return {"ok": False, "error": f"未知 job_id: {job_id}"}
    return {"ok": True, **out}


@mcp.tool
def wait_job(job_id: str, timeout_s: float = 600.0,
             poll_interval_s: float = 5.0) -> dict[str, Any]:
    """阻塞等待长任务终态并流式回报进度（DP-14 A1：progressToken 语义）。

    fastmcp 以 progress 通知回报 0..1 进度（客户端收通知即重置超时时钟，
    2025-06 规范语义）；终态前每 poll_interval_s 轮询一次，超 timeout_s
    返回 ok=False+最后已知状态（不抛异常）。无副作用（只读轮询）。

    Args:
        job_id: create_run_async 返回的任务 id
        timeout_s: 最长等待秒数（缺省 600）
        poll_interval_s: 轮询间隔秒数（缺省 5）

    Returns:
        dict: {ok, job_id, status, progress, ...}（终态或超时快照）
    """
    import time as _time

    from rfauto.service.api import poll_job as _poll_job

    deadline = _time.monotonic() + float(timeout_s)
    last: dict[str, Any] = {}
    while True:
        last = _poll_job(job_id)
        status = str(last.get("status", ""))
        if status in ("completed", "failed", "cancelled"):
            return {**last, "ok": True, "wait": "terminal"}
        if _time.monotonic() >= deadline:
            return {"ok": False, "job_id": job_id, "status": status or "unknown",
                    "wait": "timeout", "error": f"wait_job 超时 {timeout_s}s"}
        _time.sleep(float(poll_interval_s))



# ─── 7. get_metrics ─────────────────────────────────────────────────────────

@mcp.tool
def get_metrics(run_id: str) -> dict[str, Any]:
    """读取某次 run 的指标。

    无副作用，可安全调用。

    Args:
        run_id: 运行 ID

    Returns:
        dict: {ok: bool, data: {run_id, metrics, cost, ...}}
    """
    from rfauto.service.api import get_metrics as _get_metrics
    return _get_metrics(run_id)


# ─── 服务器启动入口 ────────────────────────────────────────────────────────



# ─── 8. synthesize (E6a) ──────────────────────────────────────────────────────

@mcp.tool
def synthesize(
    z0_target: float,
    freq_ghz: float = 2.4,
    stackup: str = "rogers4350b_h0.508",
) -> dict[str, Any]:
    """微带线综合：目标阻抗 → 线宽。

    使用 skrf MLine (Hammerstad-Jensen) + brentq 反解。

    Args:
        z0_target: 目标特性阻抗 (Ω)
        freq_ghz: 频率 (GHz)
        stackup: 层叠名称 (materials.yaml 键)

    Returns:
        dict: {ok, data: {width_mm, z0_actual, epsilon_eff, status}}
    """
    from rfauto.core.synthesis import synthesize_mline
    try:
        result = synthesize_mline(z0_target, freq_ghz, stackup)
        return {"ok": True, "data": result.to_dict()}
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}


# ─── 8b. synthesize_bpf (C13 耦合矩阵综合) ────────────────────────────────────

@mcp.tool
def synthesize_bpf(
    order: int,
    f0_ghz: float,
    fbw: float,
    rl_db: float,
    transmission_zeros_ghz: list[float] | None = None,
    topology: str = "folded",
) -> dict[str, Any]:
    """C13 带通滤波器综合：广义切比雪夫 → Cameron N+2 耦合矩阵 → folded/arrow。

    确定性内核（core/synthesis.synthesize_bpf_model）：Y 留数法闭式横向矩阵 +
    复正交合同旋转拓扑约简，频响与原型多项式逐点一致。

    Args:
        order: 阶数 N（≥1）
        f0_ghz: 中心频率 (GHz)
        fbw: 相对带宽 (0,1]
        rl_db: 带内回波损耗 (dB，>0)
        transmission_zeros_ghz: 传输零点频率列表 (GHz，须在阻带；±对口径)
        topology: folded | arrow

    Returns:
        dict: synthesize_bpf_model 的 JSON（ok/coupling_matrix/nominal/
        cross_family/response_max_err/pattern_residual/notes 或 errors）
    """
    from rfauto.core.synthesis import synthesize_bpf_model
    try:
        return synthesize_bpf_model(
            order=order, f0_ghz=f0_ghz, fbw=fbw, rl_db=rl_db,
            transmission_zeros_ghz=list(transmission_zeros_ghz or []),
            topology=topology)
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}


# ─── 9. budget_analysis (E8c) ─────────────────────────────────────────────────

@mcp.tool
def budget_analysis(
    chain: list[str],
    catalog: str = "parts/catalog.yaml",
) -> dict[str, Any]:
    """链路预算：Friis 噪声级联分析。

    Args:
        chain: 级联器件名列表
        catalog: 器件目录路径

    Returns:
        dict: {ok, data: {cascade_gain_db, cascade_nf_db, stages}}
    """
    from rfauto.core.block_spec import DeviceCatalog
    from rfauto.core.budget import LinkBudget
    try:
        dev_catalog = DeviceCatalog.from_yaml(catalog)
        budget = LinkBudget()
        for name in chain:
            spec = dev_catalog.get(name)
            budget.add_stage(
                name=name,
                gain_db=spec.gain_db or -(spec.conversion_loss_db or 0),
                nf_db=spec.nf_db or spec.conversion_loss_db or 0,
                p1db_dbm=spec.p1db_dbm,
                oip3_dbm=spec.oip3_dbm,
            )
        result = budget.compute()
        return {"ok": True, "data": result.to_dict()}
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}


# ─── 9b. cascade 预算/杂散/IF 规划 (DP-5) ─────────────────────────────────────

@mcp.tool
def cascade_budget(
    stages: list[dict],
    snr_min_db: float = 10.0,
    rx_power_dbm: float | None = None,
    bw_hz: float | None = None,
) -> dict[str, Any]:
    """系统级级联预算（DP-5）：增益/Friis NF/IIP3·OIP3 级联/P1dB/噪声底/SFDR/灵敏度。

    Args:
        stages: 级表（顺序=信号流向）。schema: {type: amp|mixer|filter|atten|cable,
                gain_db, nf_db?, iip3_dbm?, p1db_dbm?, bw_hz?, network_path?/il_db?}；
                filter/atten 插损来源=network_path（skrf 实取 S21，需配 il_freq_hz）
                或常数 il_db，显式二选一；无源级 NF 缺省=插损（T0）
        snr_min_db: 解调最小 SNR (dB)
        rx_power_dbm: 接收功率 (dBm)，给定时输出链路裕量
        bw_hz: 系统噪声带宽 (Hz)，缺省取末级 bw_hz

    Returns:
        dict: {ok, result: {gain_total_db, nf_total_db, iip3_total_dbm, sfdr_db, ...}}
    """
    from rfauto.service.cascade_service import cascade_budget_report
    try:
        report = cascade_budget_report(stages, snr_min_db=snr_min_db,
                                       rx_power_dbm=rx_power_dbm, bw_hz=bw_hz)
        return report
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def spur_search(
    f_rf_hz: float,
    f_lo_hz: float,
    if_center_hz: float | None = None,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """混频杂散落带搜索（DP-5）：f_spur=|m·f_RF±n·f_LO| 枚举+落带判定+危险等级。

    Args:
        f_rf_hz: RF 中心频率 (Hz)
        f_lo_hz: 本振频率 (Hz)
        if_center_hz: 目标 IF 中心 (Hz)，缺省 |f_RF−f_LO|
        if_bw_hz: 目标带宽 (Hz)
        rf_bw_hz: RF 信号带宽 (Hz)（谐波带宽线性缩放）
        max_order: 最大阶数 m+n（缺省 7）

    Returns:
        dict: {ok, result: {n_products, n_spurs_in_band, spurs: [...]}}
    """
    from rfauto.service.cascade_service import spur_search_report
    try:
        return spur_search_report(f_rf_hz, f_lo_hz, if_center_hz=if_center_hz,
                                  if_bw_hz=if_bw_hz, rf_bw_hz=rf_bw_hz,
                                  max_order=max_order)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def if_plan_sweep(
    f_rf_hz: float,
    if_lo_hz: float,
    if_hi_hz: float,
    side: str = "low",
    n_points: int = 201,
    if_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """IF 频率规划扫掠（DP-5）：候选 IF 逐点杂散判定 → spurious-free 窗口表。

    Args:
        f_rf_hz: RF 中心频率 (Hz)
        if_lo_hz: IF 扫掠下限 (Hz)
        if_hi_hz: IF 扫掠上限 (Hz)（low 侧须 < f_rf_hz）
        side: 注入侧 "low"（f_LO=f_RF−IF）或 "high"（f_LO=f_RF+IF）
        n_points: 网格点数
        if_bw_hz: 目标带宽 (Hz)
        max_order: 最大阶数 m+n（缺省 7）

    Returns:
        dict: {ok, result: {points: [...], windows: [{start_hz, end_hz, n_points}]}}
    """
    from rfauto.service.cascade_service import if_plan_report
    try:
        return if_plan_report(f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz,
                              side=side, n_points=n_points, if_bw_hz=if_bw_hz,
                              max_order=max_order)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 9c. CM 诊断三件套 (DP-2) ─────────────────────────────────────────────────

@mcp.tool
def cm_diagnose_q(
    network_path: str | None = None,
    freq_ghz: list[float] | None = None,
    s11: list | None = None,
    f0_hint_ghz: float | None = None,
    q_e: list[float] | None = None,
) -> dict[str, Any]:
    """单腔 Q 双通道诊断（DP-2）：VF 极点法 × Kajfez 圆拟合互证 + skrf 第三方仲裁。

    互证 |ΔQu|/Qu≤10% → AGREE，超阈 UNDECIDABLE；三方极差 ≤15% 如实报。

    Args:
        network_path: Touchstone 路径（.s1p/.s2p；与 freq_ghz+s11 二选一）
        freq_ghz: 频率轴 GHz（直接给数据时必填）
        s11: 复 S11 [re,im] 对列表
        f0_hint_ghz: 谐振频率提示 GHz
        q_e: 外部 Q 列表（给定时输出 Q_unloaded）

    Returns:
        dict: {ok, result: {vf, circle, verdict, cross_diff_pct, third_opinion}}
    """
    from rfauto.service.diagnosis_service import diagnose_q
    try:
        return diagnose_q({"touchstone_path": network_path,
                           "freq_ghz": freq_ghz, "s11": s11,
                           "f0_hint_ghz": f0_hint_ghz, "q_e": q_e})
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def cm_extract_refine(
    network_path: str | None = None,
    freq_ghz: list[float] | None = None,
    s11: list | None = None,
    s21: list | None = None,
    order: int | None = None,
    f0_ghz: float | None = None,
    fbw: float | None = None,
    topology: str = "folded",
    target_matrix: list | None = None,
) -> dict[str, Any]:
    """耦合矩阵反向提取（DP-2）：VF 定阶+结构 → LM 固定拓扑精化 → 可选目标
    逐元素偏差表（门 5%）。

    Args:
        network_path: 2 端口 Touchstone 路径（与 freq_ghz+s11+s21 二选一）
        freq_ghz: 频率轴 GHz
        s11: 复 S11 [re,im] 对列表
        s21: 复 S21 [re,im] 对列表
        order: 阶数（缺省=VF 自动判）
        f0_ghz: 中心频率提示 GHz
        fbw: 相对带宽提示
        topology: "folded"（缺省）| "arrow"
        target_matrix: 目标 (N+2)×(N+2) 矩阵（[re,im] 对嵌套列表；给定时输出偏差表）

    Returns:
        dict: {ok, result: {extract, refine, target_check?}}
    """
    from rfauto.service.diagnosis_service import diagnose_cm
    try:
        return diagnose_cm({"touchstone_path": network_path,
                            "freq_ghz": freq_ghz, "s11": s11, "s21": s21,
                            "order": order, "f0_ghz": f0_ghz, "fbw": fbw,
                            "topology": topology,
                            "target_matrix": target_matrix})
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def cm_cat_critique(
    freq_ghz: list[float],
    s21: list | None = None,
    s11: list | None = None,
    f0_ghz: float = 0.0,
    fbw: float = 0.0,
    target_matrix: list | None = None,
    current_params: dict | None = None,
    bounds: dict | None = None,
    tol: float = 0.1,
) -> dict[str, Any]:
    """Dishal 顺序调谐 critique（DP-2）：τ(f) 峰数指纹 + Qe/k 偏差 + typed fixes。

    C 系数钉死：S21 透射泄漏 C=2、S11 反射全通 C=4（合成回收裁决）；
    k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)。

    Args:
        freq_ghz: 频率轴 GHz
        s21: 复 S21 [re,im] 对列表（透射口径，与 s11 恰给其一）
        s11: 复 S11 [re,im] 对列表（反射口径）
        f0_ghz: 目标中心频率 GHz
        fbw: 相对带宽
        target_matrix: 目标 (N+2)×(N+2) 矩阵
        current_params: 当前可调参数 {name: value}
        bounds: 参数界 {name: [lo, hi]}
        tol: 相对容差（缺省 0.1）

    Returns:
        dict: {ok, result: {n_peaks, qe_measured?, k_measured?, issues, fixes, verdict}}
    """
    from rfauto.service.diagnosis_service import diagnose_cat
    try:
        return diagnose_cat({"freq_ghz": freq_ghz, "s21": s21, "s11": s11,
                             "f0_ghz": f0_ghz, "fbw": fbw,
                             "target_matrix": target_matrix,
                             "current_params": current_params,
                             "bounds": bounds, "tol": tol})
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 10. correlate_measurement (E9c) ──────────────────────────────────────────

@mcp.tool
def correlate_measurement(
    sim_file: str,
    measured_file: str,
    threshold_db: float = 3.0,
) -> dict[str, Any]:
    """仿真 vs 测量相关性分析。

    Args:
        sim_file: 仿真结果文件 (.s2p)
        measured_file: 测量数据文件 (.s2p)
        threshold_db: 偏差阈值 (dB)

    Returns:
        dict: {ok, data: {is_correlated, metrics, warnings}}
    """
    from rfauto.measurement.correlate import compute_correlation
    from rfauto.measurement.import_data import import_touchstone
    try:
        sim = import_touchstone(sim_file)
        measured = import_touchstone(measured_file)
        result = compute_correlation(sim, measured, threshold_db)
        return {"ok": True, "data": result.to_dict()}
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}


# ─── 11. diagnose ─────────────────────────────────────────────────────────────

def _run_model_name(run_id: str) -> str:
    """best-effort 读 run 元数据里的模型名（决定规则适用域），失败回退 "all"。

    #105：元数据读取不阻塞主路径——meta.json 缺失/损坏时回退 "all"，
    仅保留通用规则（R002/R003/R004），模型限定规则（R001/R006/R007/R009）
    自动跳过，不臆测模型名。
    """
    meta_path = Path("runs") / run_id / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return "all"
    name = meta.get("model") if isinstance(meta, dict) else None
    return str(name) if name else "all"


@mcp.tool
def diagnose(run_id: str) -> dict[str, Any]:
    """诊断仿真结果（知识库规则引擎，确定性、无 LLM）。

    读取 run 的指标（metrics.json）并重跑规则诊断；模型名 best-effort
    取自 run 的 meta.json（决定规则适用域）。结果可复现，与 create_run
    落盘的 metrics.json diagnosis 段同源同语义。

    无副作用，可安全调用。

    Args:
        run_id: 运行 ID

    Returns:
        dict: {ok, data: {diagnoses, suggestions, initial_values, rules_applied}}
    """
    from rfauto.service.api import get_metrics as _get_metrics
    fetched = _get_metrics(run_id)
    if not fetched.get("ok"):
        return {
            "ok": False,
            "errors": list(fetched.get("errors") or [f"未找到 run: {run_id}"]),
        }
    metrics = (fetched.get("data") or {}).get("metrics")
    if not isinstance(metrics, dict):
        return {"ok": False, "errors": [f"run 无指标数据: {run_id}"]}
    from rfauto.infra.diagnosis import diagnose_results
    result = diagnose_results(metrics, model_name=_run_model_name(run_id))
    return {"ok": True, "data": result}

# ─── 12. compare_runs ─────────────────────────────────────────────────────────

@mcp.tool
def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    """对比两次 run 的指标与 cost（逐指标给出 B-A 增量）。

    无副作用，可安全调用。

    Args:
        run_id_a: 基准 run ID
        run_id_b: 对比 run ID

    Returns:
        dict: {ok, data: {metrics: {k: {a, b, delta}}, cost_a, cost_b}}
    """
    from rfauto.service.api import compare_runs as _compare_runs
    return _compare_runs(run_id_a, run_id_b)


# ─── 13/14. 人工核验辅助（rfauto ui 同源服务层） ──────────────────────────────

@mcp.tool
def get_run_artifacts(run_id: str) -> dict[str, Any]:
    """列出某次 run 的全部中间产物与指标（文件清单、metrics、S 参数摘要）。

    无副作用，可安全调用。人工核验请打开 rfauto ui（CLI: rfauto ui）。

    Returns:
        dict: {ok, data: {files: [...], metrics: {...}, sparams: [...]}}
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.ui_service import run_detail
    return annotate_contract("run_detail", run_detail(run_id))


@mcp.tool
def get_model_3d(recipe_path: str) -> dict[str, Any]:
    """获取配方的 3D 几何 spec（毫米，boxes 列表，供外部渲染/核验）。

    无副作用，可安全调用。仅 wilkinson/patch 模板支持。

    Returns:
        dict: {ok, data: {template, substrate, boxes: [{name, material, start_mm, stop_mm}]}}
    """
    from rfauto.service.ui_service import model3d_for_recipe
    return model3d_for_recipe(recipe_path)


@mcp.tool
def list_calculators(include_experimental: bool = True) -> dict[str, Any]:
    """列出全部微波闭式计算器（E4）：名字/说明/参数表（mm/GHz/Ω/dB 口径）。

    实验性公式（experimental=True，如符号回归归纳公式）默认一并列出并带
    experimental: true 标签；运行仍需 run_calculator(allow_experimental=True)
    或配置 calculators.allow_experimental 放行。

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


# ─── WP3.3 MCP 工具面全量开放：从 service 注册表自动生成工具清单 ─────────────
# 四域（方案 §4 WP3.3 行）：calculators（上两个工具已有）/模板库/战役状态/
# 数据集查询；bands 十接口为 D9 行归口 WP3.3 的 MCP 薄壳。全部只做参数
# 转发的薄壳（规则 4），数值只在确定性内核（铁律 7）——清单由注册表
# describe() 自动生成，无手工静态名单。


# ─── 17. 模板库（E2 TemplateSpec 注册表） ─────────────────────────────────────

@mcp.tool
def list_template_specs() -> dict[str, Any]:
    """列出全部模板 spec（模板库注册表自动生成清单）。

    每条含组件齐备性（render_script/synthesizer/fake_model/hfss_plugin）、
    meta 键与 physics_roles。无副作用，可安全调用。

    Returns:
        dict: {ok, templates: [{name, components, meta_keys, physics_roles}]}
    """
    from rfauto.service.template_spec_service import list_template_specs as _list
    return _list()


@mcp.tool
def draft_recipe_from_spec(
    name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按模板 spec 的综合入口产出配方草稿（零求解、零 license）。

    线宽等几何数值由确定性综合内核（core/synthesis，skrf HJ）精算，
    本工具不产生任何物理数字。模板名单先 list_template_specs 查询。

    Args:
        name: 模板名（如 "mline"、"wilkinson"）
        params: 综合入口参数（如 {"z0_ohm": 50, "freq_ghz": 2.5}）；
            缺省用各参数默认值

    Returns:
        dict: {ok, template, recipe_draft} 或 {ok: False, error}
    """
    from rfauto.service.template_spec_service import draft_recipe_from_spec as _draft
    return _draft(name, params)


# ─── 18. 战役状态（campaign_manager 确定性状态机） ────────────────────────────

@mcp.tool
def plan_campaign(
    recipe_path: str,
    high_adapter: str = "hfss",
    mid_adapter: str = "openems",
    calibrate_samples: int = 9,
    tune_budget: int | None = None,
) -> dict[str, Any]:
    """把配方确定性拆解为战役阶段队列（calibrate→prefilter→tune→tolerance
    →report→final_verify），含依赖/预算/license 门槛。

    无副作用（只返回内存计划）；要跨调用持久先 save_campaign_plan 落盘，
    之后 get_campaign_status 查询。

    Args:
        recipe_path: 配方文件路径（YAML）
        high_adapter: 终验适配器（"hfss"；"none" 则不加终验阶段）
        mid_adapter: 中保真精算适配器（默认 "openems"）
        calibrate_samples: 校准阶段样本预算
        tune_budget: tune 阶段预算；缺省取配方 limits.max_trials，再缺省 30

    Returns:
        dict: {ok, recipe, model, stages: [...], high_adapter, mid_adapter}
    """
    from rfauto.service.campaign_manager import plan_campaign as _plan
    return _plan(
        recipe_path,
        high_adapter=high_adapter,
        mid_adapter=mid_adapter,
        calibrate_samples=calibrate_samples,
        tune_budget=tune_budget,
    )


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def save_campaign_plan(plan: dict[str, Any], out_dir: str) -> dict[str, Any]:
    """把战役计划落盘为 <out_dir>/campaign.plan.json（幂等覆盖）。

    副作用：创建 out_dir 目录并写入 campaign.plan.json。

    Args:
        plan: plan_campaign 返回的计划 dict
        out_dir: 落盘目录（通常 runs/<campaign_id>/）

    Returns:
        dict: {ok, path} 或 {ok: False, errors}
    """
    from rfauto.service.campaign_manager import save_plan as _save
    try:
        path = _save(plan, out_dir)
    except (TypeError, OSError) as exc:
        return {"ok": False, "errors": [f"战役计划落盘失败: {exc}"]}
    return {"ok": True, "path": str(path)}


@mcp.tool
def get_campaign_status(plan_path: str) -> dict[str, Any]:
    """读回已落盘战役计划的状态（verdict/各阶段 status/n_done/n_dead）。

    无副作用，可安全调用。plan_path 可为 campaign.plan.json 文件或其
    所在目录。状态推进（stage_done/stage_failed）走 CLI rfauto campaign
    同源服务层 apply_event。

    Args:
        plan_path: campaign.plan.json 文件路径或其父目录

    Returns:
        dict: {ok, path, plan} 或 {ok: False, errors}
    """
    from rfauto.service.campaign_manager import load_plan as _load
    return _load(plan_path)


# ─── 19. 数据集查询（数据面注册表） ───────────────────────────────────────

@mcp.tool
def list_datasets(
    visibility: str | None = None,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """列出数据集注册表总览（逐数据集点数/GT 标注/可见性/HF 导出态）。

    无副作用，可安全调用。清单由盘面 manifest 自动汇总，非手工名单。

    Args:
        visibility: 按 "public"/"private" 过滤；缺省不过滤
        out_dir: 数据集根目录（默认 runs/datasets）

    Returns:
        dict: {ok, datasets: [{name, n_points, visibility, ...}], n_datasets}
    """
    from rfauto.service.dataset_insights import list_datasets as _list
    return _list(out_dir=out_dir, visibility=visibility)


@mcp.tool
def query_dataset(
    name: str,
    where: str | None = None,
    columns: list[str] | None = None,
    limit: int = 100,
    model: str | None = None,
    study_name: str | None = None,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """DuckDB 直查数据集 Parquet（谓词下推/列裁剪，只读）。

    无副作用，可安全调用。where 是单条 SQL WHERE 片段（如
    "cost < 0.1"），经白名单校验；model/study_name 等值过滤走参数
    绑定（值不拼进 SQL）。数据集名单先 list_datasets 查询。

    Args:
        name: 数据集名（datasets materialize 产物）
        where: SQL WHERE 片段；缺省不过滤
        columns: 列裁剪名单；缺省取全部列
        limit: 返回行数上限（>=1，默认 100）
        model: 按模板族等值过滤（model 列）；缺省不过滤
        study_name: 按来源 study 名等值过滤；缺省不过滤
        out_dir: 数据集根目录（默认 runs/datasets）

    Returns:
        dict: {ok, rows, n_rows, columns, dataset, where, filters, limit}
    """
    from rfauto.service.dataset_service import query_dataset as _query
    return _query(
        name, where=where, columns=columns, limit=limit,
        model=model, study_name=study_name, out_dir=out_dir,
    )


@mcp.tool
def discover_workdir_runs(
    runs_root: str = "runs",
    models: list[str] | None = None,
) -> dict[str, Any]:
    """发现工作目录形态真机产物（无 meta.json 的 runs 子目录，只读）。

    无副作用，可安全调用。slotline/hairpin/marchand/mline/helix 等战役把
    sparams.csv / *.sNp 直接落在 runs/<工作目录>/<点目录>/，不在 materialize
    契约里；本工具列出可导入候选（逐目录曲线数/引擎/端口数），入库走
    import_workdir_runs。

    Args:
        runs_root: runs 根目录（默认 runs）
        models: 器件族过滤名单（slotline/hairpin/marchand/mline/helix）；缺省全部

    Returns:
        dict: {ok, n_candidates, per_family, candidates: [{run_id, family,
            n_curves, adapters, curves}]} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_service import discover_workdir_candidates as _disc
    return _disc(runs_root, models=models)


@mcp.tool
def import_workdir_runs(
    name: str,
    run_ids: list[str] | None = None,
    runs_root: str = "runs",
    out_dir: str = "runs/datasets",
    models: list[str] | None = None,
    health_gate: bool = True,
    fmt: str = "parquet",
) -> dict[str, Any]:
    """工作目录形态真机产物导入数据集注册表（写 <out_dir>/<name>/）。

    有副作用：写数据集目录（不改 runs/ 下任何产物）。每个曲线产物一行，
    设计参数只从内核落盘 JSON 按固定键路径取值；provenance 带来源目录/
    时间戳/touchstone 路径/n_ports；G11 目录级健康门默认开。候选先用
    discover_workdir_runs 查看。

    Args:
        name: 数据集名（目录名，字母数字-_）
        run_ids: 工作目录名清单；缺省=所选族全部候选
        runs_root: runs 根目录（默认 runs）
        out_dir: 数据集输出根目录（默认 runs/datasets）
        models: 器件族过滤名单；缺省五族全导
        health_gate: 是否启用 G11 目录级健康门（默认 True）
        fmt: 物化格式 parquet/hdf5（默认 parquet）

    Returns:
        dict: {ok, name, dataset_dir, n_candidates, n_curves, n_points, n_rows,
            n_dup, n_points_skipped, unhealthy_points, source_runs, ...}
    """
    from rfauto.service.dataset_service import import_workdir_runs as _import
    return _import(
        run_ids, name=name, runs_root=runs_root, out_dir=out_dir,
        models=models, health_gate=health_gate, fmt=fmt,
    )


# ─── 20. 频段/环境包络注册表（D9 归口 WP3.3 的 MCP 薄壳） ─────────────────────

@mcp.tool
def bands_list(
    standard: str | None = None,
    kind: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """列出标准频段注册表（3GPP/Wi-Fi/UWB/ISM/EMC 等条目，自动生成清单）。

    无副作用，可安全调用。

    Args:
        standard: 按 standard 子串过滤（如 "3GPP"）；缺省不过滤
        kind: 按类型过滤（如 "cellular"/"ism"）；缺省不过滤
        region: 按区域过滤；缺省不过滤

    Returns:
        dict: {ok, count, total, bands: [...]}
    """
    from rfauto.service.bands_service import bands_list as _list
    return _list(standard=standard, kind=kind, region=region)


@mcp.tool
def bands_get(key: str) -> dict[str, Any]:
    """按 key 取单条频段详情（边界/出处/区域）。

    无副作用，可安全调用。未知 key 返回 ok=False 且 error 带可用键列表。

    Args:
        key: 频段键（如 "gpp_n78"）

    Returns:
        dict: {ok, band} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_get as _get
    return _get(key)


@mcp.tool
def bands_find(freq_ghz: float) -> dict[str, Any]:
    """查包含给定频率的全部频段条目。

    无副作用，可安全调用。

    Args:
        freq_ghz: 频率 (GHz，正有限数)

    Returns:
        dict: {ok, freq_ghz, count, bands: [...]}
    """
    from rfauto.service.bands_service import bands_find as _find
    return _find(freq_ghz)


@mcp.tool
def bands_spec_bounds(key: str) -> dict[str, Any]:
    """频段键 → SpecEvaluator band 结构 {"band": [f_low, f_high]}。

    无副作用，可安全调用。喂 objectives 的 band 定义与优化 bounds。

    Args:
        key: 频段键（如 "gpp_n78"）

    Returns:
        dict: {ok, key, spec_bounds, kind} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_spec_bounds as _bounds
    return _bounds(key)


@mcp.tool
def bands_env_list(
    standard: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """列出环境包络注册表（工业/AEC-Q100/ECSS/IEC 60068 温区等级）。

    无副作用，可安全调用。

    Args:
        standard: 按 standard 子串过滤；缺省不过滤
        kind: 按类型过滤；缺省不过滤

    Returns:
        dict: {ok, count, total, environments: [...]}
    """
    from rfauto.service.bands_service import bands_env_list as _list
    return _list(standard=standard, kind=kind)


@mcp.tool
def bands_env_get(key: str) -> dict[str, Any]:
    """按 key 取单条环境包络详情（温区/等级/出处）。

    无副作用，可安全调用。未知 key 返回 ok=False 且 error 带可用键列表。

    Args:
        key: 环境包络键（如 "iec_industrial"）

    Returns:
        dict: {ok, environment} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_get as _get
    return _get(key)


@mcp.tool
def bands_env_find(t_c: float) -> dict[str, Any]:
    """查温区覆盖给定温度的全部环境包络。

    无副作用，可安全调用。

    Args:
        t_c: 温度 (°C)

    Returns:
        dict: {ok, t_c, count, environments: [...]}
    """
    from rfauto.service.bands_service import bands_env_find as _find
    return _find(t_c)


@mcp.tool
def bands_env_delta_t(key: str, t_ref_c: float | None = None) -> dict[str, Any]:
    """环境包络 → ΔT 上下限（D3 温区扫描 / D8 UQ / WP4.2 良率消费）。

    无副作用，可安全调用。数值只出自 core/bands.py 标准常量表。

    Args:
        key: 环境包络键
        t_ref_c: 参考温度 (°C)；缺省用条目自身参考温度

    Returns:
        dict: {ok, delta_t_low, delta_t_high, ...} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_delta_t as _dt
    return _dt(key, t_ref_c)


@mcp.tool
def bands_env_uq_axis(
    key: str,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
) -> dict[str, Any]:
    """环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。

    无副作用，可安全调用。

    Args:
        key: 环境包络键
        t_ref_c: 参考温度 (°C)；缺省用条目自身参考温度
        k_sigma: σ 倍数（默认 3.0）

    Returns:
        dict: {ok, t_nominal_c, sigma, t_low_c, t_high_c, ...}
        或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_uq_axis as _uq
    return _uq(key, t_ref_c, k_sigma)


@mcp.tool
def bands_env_points(key: str, n: int = 5) -> dict[str, Any]:
    """环境包络温区等距采样点（含两端，供 D3 温区扫描）。

    无副作用，可安全调用。

    Args:
        key: 环境包络键
        n: 采样点数（默认 5）

    Returns:
        dict: {ok, key, count, temperatures_c: [...]} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_points as _points
    return _points(key, n)


# ─── 15. warm_start_optimize (warm-start 数据面) ─────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def warm_start_optimize(
    recipe_path: str,
    dataset: str,
    model: str | None = None,
    source_study: str | None = None,
    adapter: str = "fake",
    max_trials: int = 60,
) -> dict[str, Any]:
    """数据集历史样本 → warm-start 先验注入优化。

    副作用：创建 run 目录、写 Optuna study（enqueue WAITING 先验点）。

    Args:
        recipe_path: 配方文件路径（YAML 格式）
        dataset: 数据集名（datasets materialize 产物）
        model: 按模板族过滤（model 列精确匹配）；缺省不过滤
        source_study: 按来源 study 名过滤；缺省不过滤
        adapter: 适配器名称，"fake"（默认）或 "hfss"
        max_trials: 最大 trial 数

    Returns:
        dict: {ok, warm_start_data: {n_samples, n_skipped_invalid, ...},
        warm_start_n, best_params, best_cost}——相似度门拒绝时
        warm_start_n=0（降级冷启动，ok 仍为 True）。
    """
    from rfauto.service.warm_start_data import (
        run_optimization_warm_start_from_dataset as _run,
    )
    return _run(
        recipe_path, dataset, model=model, source_study=source_study,
        adapter_name=adapter, max_trials=max_trials,
    )


# ─── 16. export_report_pdf (WP4.7 报告 PDF) ──────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def export_report_pdf(
    run_id: str,
    filename: str = "report.pdf",
    narrative: str | None = None,
) -> dict[str, Any]:
    """把已完成 run 的指标导出为多页 PDF 报告（WP4.7）。

    副作用：在 run 目录（或指定名）写入 PDF 文件。

    Args:
        run_id: 运行 ID（runs/<run_id>/results/metrics.json 须存在）
        filename: 输出文件名（写入 run 目录，默认 report.pdf）
        narrative: 叙述文本（F9 位；不触发任何 LLM 调用）

    Returns:
        dict: {ok, run_id, report: str, metrics: dict}
    """
    from pathlib import Path

    from rfauto.infra.report import export_report_pdf as _export
    from rfauto.service.api import get_metrics as _get_metrics
    result = _get_metrics(run_id)
    if not result.get("ok"):
        return {"ok": False, "errors": list(result.get("errors") or ["读取 run 指标失败"])}
    data = result.get("data") or {}
    try:
        report_path = _export(
            Path("runs") / run_id,
            metrics=data.get("metrics", {}),
            narrative=narrative,
            filename=filename,
        )
    except Exception as e:
        return {"ok": False, "errors": [str(e)]}
    return {
        "ok": True,
        "run_id": run_id,
        "report": str(report_path),
        "metrics": data.get("metrics", {}),
    }


# ─── 21. 回归门（WP3.7/F6：goldset + AgentBench 薄壳） ───────────────
# 两道门离线、确定性、零网络：不带轨迹/记录时用 service 离线参考回放
# （门自洽正控，绝不空跑绿），同 rfauto bench 子命令口径。

@mcp.tool
def goldset_regression(
    trajectories: list[dict[str, Any]] | None = None,
    goldset_path: str | None = None,
    runtime_tools: list[str] | None = None,
    min_tsa: float = 0.9,
    min_fca: float = 0.9,
    min_pass3: float = 0.0,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    """工具调用层金标回归门（runtime/协议变更后一键回归，WP3.7/0ar）。

    无副作用（只读金标集）。trajectories 缺省时用离线参考回放做正控。

    Args:
        trajectories: 已记录轨迹 [{"id", "trajectory": [...]}]；缺省=参考回放
        goldset_path: 金标集路径（缺省 tests/gold/agent_goldset.yaml）
        runtime_tools: 当前 runtime 工具名列表；给定时校验协议面覆盖
        min_tsa: TSA 阈值
        min_fca: FCA 阈值
        min_pass3: pass3 阈值
        require_full_coverage: 轨迹是否必须覆盖全部金标任务

    Returns:
        dict: {ok, verdict, reasons, report, ...}（run_goldset_regression 契约）
    """
    from rfauto.service.goldset_service import (
        reference_trajectory_provider,
        run_goldset_regression,
    )
    return run_goldset_regression(
        trajectories,
        goldset_path=goldset_path,
        runtime_tools=runtime_tools,
        trajectory_provider=None if trajectories else reference_trajectory_provider,
        min_tsa=min_tsa, min_fca=min_fca, min_pass3=min_pass3,
        require_full_coverage=require_full_coverage,
    )


@mcp.tool
def agentbench_regression(
    records: list[dict[str, Any]] | None = None,
    public_path: str | None = None,
    private_path: str | None = None,
    runtime_tools: list[str] | None = None,
    min_abstraction: float = 0.9,
    min_execution: float = 0.8,
    require_private: bool = False,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    """AgentBench 智能体基准回归门（两轴打分 + 公开/私有双集防污染，WP3.7）。

    无副作用（只读任务集）。records 缺省时用离线参考回放做正控。

    Args:
        records: 已记录埋点 [{"id", "trajectory", "artifacts", "numeric"}]；缺省=参考回放
        public_path: 公开集路径（缺省 tests/gold/agentbench_public.yaml）
        private_path: 私有集路径（缺省读 RFAUTO_AGENTBENCH_PRIVATE_SET）
        runtime_tools: 当前 runtime 工具名列表；给定时校验协议面覆盖
        min_abstraction: 任务抽象轴阈值
        min_execution: 执行轴阈值
        require_private: 私有集未配置即 FAIL（终评口径）
        require_full_coverage: 记录是否必须覆盖全部基准任务

    Returns:
        dict: {ok, verdict, reasons, report, ...}（run_agentbench_regression 契约）
    """
    from rfauto.service.agent_bench import (
        reference_agentbench_provider,
        run_agentbench_regression,
    )
    return run_agentbench_regression(
        records,
        trajectory_provider=None if records else reference_agentbench_provider,
        public_path=public_path, private_path=private_path,
        runtime_tools=runtime_tools,
        min_abstraction=min_abstraction, min_execution=min_execution,
        require_private=require_private,
        require_full_coverage=require_full_coverage,
    )


# ─── 22. 多 Agent 编排三层栈（WP3.8 薄壳：4 内核工具 + 端到端） ────────
# 铁律 7：rf_run_sampler 是唯一产数环节（引擎采样器），其余三个只做
# typed 提议/评判/加权 cost；multi_agent_run 缺省真机 openEMS 采样器（串行）。

@mcp.tool
def rf_propose_params(
    bounds: dict[str, list[float]],
    current_params: dict[str, float] | None = None,
    fixes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """调优内核：界中点初值 / typed fixes 落参 + 探测候选展开（无数字产出）。

    无副作用，可安全调用。

    Args:
        bounds: 参数界 {name: [low, high]}
        current_params: 当前参数点；缺省=界中点初值
        fixes: critique 给出的 typed fixes（op=scale|coord_probe）

    Returns:
        dict: {ok, tool, result: {params, candidates, applied_kinds}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_propose_params", {
        "bounds": bounds, "current_params": current_params, "fixes": fixes or []})


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def rf_run_sampler(
    recipe_path: str,
    params: dict[str, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """验证内核：params → {metrics, valley_ghz}（唯一产数环节，真机 openEMS）。

    副作用：按配方构造 openEMS 快验证采样器并求解一点（runs/multi_agent_work_*）。

    Args:
        recipe_path: 配方文件路径（取 model/setup/objectives）
        params: 待评估参数点
        mesh_resolution_mm: openEMS 网格 base 覆盖 mm（0=自动）

    Returns:
        dict: {ok, tool, result: {metrics, valley_ghz}} 或 {ok: False, errors}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool(
        "rf_run_sampler", {"params": params},
        recipe_path=recipe_path, mesh_resolution_mm=mesh_resolution_mm)


@mcp.tool
def rf_critique_point(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
    valley_ghz: float | None = None,
    bounds: dict[str, list[float]] | None = None,
    current_params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """评审内核：metrics+objectives(+谷位) → PASS/issues/typed fixes（确定性）。

    无副作用，可安全调用。

    Args:
        metrics: 指标字典（如 s11_db_max_in_band）
        objectives: 配方 objectives 列表
        valley_ghz: |S11| 谷位 GHz（缺省不做频率尺度规则）
        bounds: 参数界 {name: [low, high]}（给定才产 typed fixes）
        current_params: 当前参数点

    Returns:
        dict: {ok, tool, result: {verdict, issues, fixes, violations}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_critique_point", {
        "metrics": metrics, "objectives": objectives, "valley_ghz": valley_ghz,
        "bounds": bounds or {}, "current_params": current_params})


@mcp.tool
def rf_spec_cost(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
) -> dict[str, Any]:
    """评审内核：SpecEvaluator 加权 cost（≥0，越小越好，0=全满足）。

    无副作用，可安全调用。

    Args:
        metrics: 指标字典
        objectives: 配方 objectives 列表

    Returns:
        dict: {ok, tool, result: {cost}}
    """
    from rfauto.service.multi_agent_service import call_kernel_tool
    return call_kernel_tool("rf_spec_cost",
                            {"metrics": metrics, "objectives": objectives})


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def multi_agent_run(
    recipe_path: str,
    max_rounds: int = 4,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """评审/调优/验证三角色端到端（LangGraph 式图 + MCP 工具层 + A2A，WP3.8）。

    副作用：真机 openEMS 采样（串行纪律），工作目录 runs/multi_agent_work_*。
    FAIL 如实上报不凑绿；采样器异常=ERROR 与评审 FAIL 语义分立。

    Args:
        recipe_path: 配方文件路径（optimization.params 为搜索空间）
        max_rounds: 评审面轮次预算
        mesh_resolution_mm: openEMS 网格 base 覆盖 mm（0=自动）
        f0_tolerance: 谷位/带中心容差
        rl_floor_db: 回损地板 dB
        max_step_pct: 单轮修正步长上限（比例）

    Returns:
        dict: {ok, verdict, rounds, params, metrics, cost, history, graph, a2a, mcp}
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.multi_agent_service import multi_agent_run as _run
    return _run(
        recipe_path, max_rounds=max_rounds, mesh_resolution_mm=mesh_resolution_mm,
        f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
        max_step_pct=max_step_pct)


# ─── 23. 自验证环（WP3.5 收口，薄壳） ────────────────────────────────────

@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def autotune_self_verify(
    recipe_path: str,
    budget_coarse: int = 3,
    mesh_coarse_mm: float = 1.0,
    mesh_fine_mm: float = 0.5,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
    fine_epsilon: float = 0.2,
    sandbox: bool = True,
    board: bool = True,
) -> dict[str, Any]:
    """自验证环：propose→verify→fix 闭环 + 里程碑分解（M1..M5）+ 执行看板。

    副作用：真机 openEMS 粗→细双采样器求解（串行），产物 runs/<run_id>/
    autotune.json、看板 runs/loop_boards/<board_id>.json、沙箱草稿（M5）。
    verdict PASS|FAIL|TAKEN_OVER 如实；返回体带 self_verify 契约注记。

    Args:
        recipe_path: 配方文件路径
        budget_coarse: 粗网格轮数预算
        mesh_coarse_mm: 粗网格 base mm
        mesh_fine_mm: 细网格 base mm（0 或与粗相同=关闭 M4 复验）
        f0_tolerance: 谷位/带中心容差
        rl_floor_db: 回损地板 dB
        max_step_pct: 单轮修正步长上限（比例）
        fine_epsilon: M4 细网格 cost 容许劣化比例
        sandbox: 是否把 best 落沙箱草稿（M5）
        board: 是否创建执行看板（UI 可暂停/接管）

    Returns:
        dict: SelfVerifyPayload 契约 + contract_check
    """
    _silence_pyaedt_screen_logs()
    from rfauto.service.autotune_service import self_verify_loop
    from rfauto.service.contracts import annotate_contract
    result = self_verify_loop(
        recipe_path, budget_coarse=budget_coarse, mesh_coarse_mm=mesh_coarse_mm,
        mesh_fine_mm=mesh_fine_mm, f0_tolerance=f0_tolerance,
        rl_floor_db=rl_floor_db, max_step_pct=max_step_pct,
        fine_epsilon=fine_epsilon, sandbox=sandbox, board=board)
    if not result.get("ok"):
        return result
    return annotate_contract("self_verify", result)


# ─── 24. 公差/良率收口（WP4.2，薄壳） ───────────────────────────────────

@mcp.tool
def uq_yield_at(
    samples_path: str,
    tolerances: dict[str, float],
    nominal: dict[str, float],
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """显式名义点的代理蒙特卡洛良率（良率目标函数点值形式）。

    无副作用（只读校准样本集）。

    Args:
        samples_path: 校准样本集 samples.json
        tolerances: 公差 σ {参数名: σ}
        nominal: 名义点（须覆盖全部公差参数）
        n: 蒙特卡洛抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: {ok, yield_rate, metric_stats, nominal_params, ...}
    """
    from rfauto.service.uq_service import surrogate_yield_at
    return surrogate_yield_at(samples_path, tolerances, nominal, n=n, seed=seed,
                              kind=kind)


@mcp.tool
def robustness_report(
    source: str,
    specs: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    tolerances: dict[str, float] | None = None,
    n_mc: int = 100000,
    seed: int = 42,
    kind: str = "poly_ridge",
    form_engine: str = "auto",
    persist: bool = False,
    store_name: str | None = None,
) -> dict[str, Any]:
    """稳健性报告：良率 MC（向量化）+FORM Pf+worst-case 角点+逐规范 Cpk。

    只读消费数据集/run/samples.json（persist=True 时写 Parquet 数据集）。

    Args:
        source: samples.json 路径 | 数据集名 | run id
        specs: 规范限列表 [{metric, op, value, weight?}]（op: max_below|min_above 等）
        profile: 公差剖面 dict（load_tolerance_profile schema，优先于 tolerances）
        tolerances: 公差 σ {参数名: σ}（无 profile 时生效）
        n_mc: MC 抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn
        form_engine: FORM 引擎 auto|internal|openturns|uqpy
        persist: MC 抽样落盘 Parquet
        store_name: 落盘数据集名

    Returns:
        dict: {ok, yield_mc, form, worst_case, cpk, uncertainty_status, ...}
    """
    from rfauto.service.robustness_service import robustness_report
    return robustness_report(source, specs, profile=profile, tolerances=tolerances,
                             n_mc=n_mc, seed=seed, kind=kind,
                             form_engine=form_engine, persist=persist,
                             store_name=store_name)


@mcp.tool
def uq_design_center(
    samples_path: str,
    tolerances: dict[str, float],
    k_sigma: float = 3.0,
    n_levels: int = 3,
    max_iter: int = 40,
    n_mc: int = 2000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """良率目标函数 + 设计中心化（容差盒网格违约 cost≤0 良率，坐标搜索）。

    无副作用（只读校准样本集；MC 只做前后认证不入环）。

    Args:
        samples_path: 校准样本集 samples.json
        tolerances: 公差 σ {参数名: σ}
        k_sigma: 容差盒半宽 = k_sigma·σ
        n_levels: 每维网格层数
        max_iter: 坐标搜索最大迭代
        n_mc: 前后认证 MC 抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: YieldDesignCenterPayload 契约 + contract_check
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import yield_design_center
    return annotate_contract("yield_design_center", yield_design_center(
        samples_path, tolerances, k_sigma=k_sigma, n_levels=n_levels,
        max_iter=max_iter, n_mc=n_mc, seed=seed, kind=kind))


@mcp.tool
def uq_temperature_zone(
    samples_path: str,
    env_key: str,
    tolerances: dict[str, float] | None = None,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """温区良率（D9 环境包络 → 温度轴 σ 并入 MC + 温区两端角点确定性评估）。

    无副作用（只读样本集；要求样本集含 t_c 维）。角点不满足规格如实 FAIL。

    Args:
        samples_path: 校准样本集 samples.json（含 t_c 维）
        env_key: 环境包络键（bands_env_list 查询）
        tolerances: 几何公差 σ（可空，只做温度维扰动）
        t_ref_c: 参考温度 °C（缺省用包络自身参考温度）
        k_sigma: σ_c = 包络半宽/k_sigma
        n: 蒙特卡洛抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: TemperatureZoneYieldPayload 契约 + contract_check
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import temperature_zone_yield
    return annotate_contract("temperature_zone_yield", temperature_zone_yield(
        samples_path, dict(tolerances or {}), env_key, t_ref_c=t_ref_c,
        k_sigma=k_sigma, n=n, seed=seed, kind=kind))


# ─── 25. 远场（WP4.1 nf2ff 薄壳） ──────────────────────────────────────

@mcp.tool
def farfield_runs(limit: int = 50) -> dict[str, Any]:
    """含远场/SAR 产物的 run 清单（nf2ff 极坐标页候选）。

    无副作用，可安全调用。

    Args:
        limit: 返回条数上限

    Returns:
        dict: {ok, runs: [{run_id, ...}]}
    """
    from rfauto.service.nf2ff_service import farfield_runs as _runs
    return _runs(limit=limit)


@mcp.tool
def farfield_view(run_id: str) -> dict[str, Any]:
    """单 run 远场视图：φ 切面 θ-dB 序列 + Dmax/效率/HPBW/F/B + SAR。

    无副作用，可安全调用。数值全部出自 core/farfield 确定性解析。

    Args:
        run_id: 含 nf2ff 产物的 run ID

    Returns:
        dict: {ok, run_id, cuts, metrics, sar, ...} 或 {ok: False, errors}
    """
    from rfauto.service.nf2ff_service import farfield_view as _view
    return _view(run_id)


# ─── 26. KiCad PCB→EM（B6 stage-2 薄壳） ───────────────────────────────

@mcp.tool
def kicad_extract(pcb_path: str, kicad_python: str | None = None) -> dict[str, Any]:
    """从 .kicad_pcb 提取叠层/走线/过孔/板框/zone/footprint（子进程 KiCad Python）。

    无写副作用（只读板文件；启动 KiCad 自带 Python 3.11 子进程）。

    Args:
        pcb_path: .kicad_pcb 路径
        kicad_python: KiCad Python 可执行文件（缺省取 adapters 内置常量路径）

    Returns:
        dict: {ok, board, traces, vias, outline, zones, footprints}
    """
    from rfauto.service.kicad_em_service import extract_pcb_facts
    return extract_pcb_facts(pcb_path, kicad_python=kicad_python)


@mcp.tool
def kicad_optimize_cpw(
    pcb_path: str,
    target_z0_ohm: float | None = None,
    freq_ghz: float | None = None,
    z0_tol_ohm: float | None = None,
) -> dict[str, Any]:
    """PCB 提取 → CPWG 闭式代理寻优环（|z0−target|≤tol 判据，FAIL 附修正 w*）。

    无写副作用。数值只出自 core 闭式内核（_cpwg_ri + synthesize_cpw_model）。

    Args:
        pcb_path: .kicad_pcb 路径
        target_z0_ohm: 目标阻抗 Ω（缺省 50）
        freq_ghz: 工作频率 GHz（缺省 2.5）
        z0_tol_ohm: 判据容差 Ω（缺省 2）

    Returns:
        dict: {ok, design, analysis, optimization, verdict, recipe_draft}
    """
    from rfauto.service.kicad_em_service import optimize_cpw_from_pcb
    return optimize_cpw_from_pcb(pcb_path, target_z0_ohm=target_z0_ohm,
                                 freq_ghz=freq_ghz, z0_tol_ohm=z0_tol_ohm)


# ─── 27. 电-热 / 寄生（WP4.4a/4.4b 薄壳） ─────────────────────────

@mcp.tool
def electrothermal_chain(payload: dict[str, Any]) -> dict[str, Any]:
    """Wilkinson 隔离电阻损耗 → 温升 → 材料温漂 → S 参数失谐（+带内判据）。

    无副作用，纯确定性闭式（core/electrothermal）。payload 形状见
    service/electrothermal_service 模块文档（case/thermal/material/resonator/band）。

    Args:
        payload: 电-热链输入（未知字段/缺字段显式报错）

    Returns:
        dict: {ok, chain: {power, thermal, material, drift, band}} 或 {ok: False, error}
    """
    from rfauto.service.electrothermal_service import run_wilkinson_electrothermal
    return run_wilkinson_electrothermal(payload)


@mcp.tool
def parasitic_extract_rlc(payload: dict[str, Any]) -> dict[str, Any]:
    """PCB 互连 RLC 提取链：pcell 几何 → RF-DRC 门 → 闭式锚 →（Q3D 注入对比）。

    无副作用，纯确定性（core/parasitic + adapters/kicad_drc 几何规则）。
    payload 形状见 service/parasitic_service 模块文档（pcb/substrate/...）。

    Args:
        payload: 寄生提取链输入（未知字段/缺字段显式报错）

    Returns:
        dict: {ok, chain: {geometry, drc, anchor, q3d}} 或 {ok: False, error|stage}
    """
    from rfauto.service.parasitic_service import extract_interconnect_rlc
    return extract_interconnect_rlc(payload)


# ─── 28. 生成式综合 E10（WP4.6 薄壳） ──────────────────────────────────

@mcp.tool
def topology_propose(
    spec: dict[str, Any],
    proposer: str = "rule_based",
    campaign: bool = False,
    n_trials: int = 80,
    seed: int = 20260914,
    sandbox_name: str | None = None,
    promote: bool = False,
) -> dict[str, Any]:
    """滤波器拓扑提议（typed，禁数值字段）→ 综合初值 →（可选）小战役精算。

    无真机副作用（电路裁判/几何审计离线秒级）；sandbox_name 给定时写沙箱草稿
    （runs/recipe_sandbox，不 promote）；promote=True（需 sandbox_name）时草稿
    继续走 L1 白名单/L2 模板离线试运行/L3 token 准入链迁 promoted/。
    数字全部出自综合链/裁判（铁律 7）。

    Args:
        spec: FilterSpec 字段 {f0_ghz, fbw, rl_db, stop_rejection_db?, order_hint?, family_hint?}
        proposer: 提议器注册名（rule_based；llm 需注入不可经此入口）
        campaign: 是否跑小战役精算（仅 campaign_capable 家族）
        n_trials: 战役 TPE 试验数
        seed: 战役随机种子
        sandbox_name: 沙箱草稿名（缺省不落盘）
        promote: 草稿继续走三层 Gate 准入链（需 sandbox_name）

    Returns:
        dict: {ok, proposer, proposal, initial, campaign, sandbox, promote} 或 {ok: False, error}
    """
    from rfauto.service.topology_service import propose_topology
    return propose_topology(spec, proposer=proposer, campaign=campaign,
                            n_trials=n_trials, seed=seed, sandbox_name=sandbox_name,
                            promote=promote)


# ─── 29. 数据集余量（WP2.4：coverage/annotate/visibility/export） ───────────

@mcp.tool
def dataset_coverage(
    name: str,
    bins: int = 10,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """数据集点数分布 + 参数空间覆盖度（逐维占用率/最弱维，喂 LHS 增广决策）。

    无副作用，可安全调用。常数维不虚报 100%。

    Args:
        name: 数据集名
        bins: 等宽分箱数（>=2）
        out_dir: 数据集根目录

    Returns:
        dict: {ok, n_rows, by_model, coverage: {...}, weakest_key, ...}
    """
    from rfauto.service.dataset_insights import dataset_coverage as _cov
    return _cov(name, out_dir=out_dir, bins=bins)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_annotate_ground_truth(
    name: str,
    threshold: int = 100,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """ground truth 标注（白名单 hfss/openems/comsol/meas）+ 6.3 解锁进度回写。

    副作用：回写数据集 manifest 的 ground_truth 块（幂等重算）。

    Args:
        name: 数据集名
        threshold: 神经算子族级解锁门槛（点数）
        out_dir: 数据集根目录

    Returns:
        dict: {ok, ground_truth: {...}, unlocked, ...}
    """
    from rfauto.service.dataset_insights import annotate_ground_truth
    return annotate_ground_truth(name, threshold=threshold, out_dir=out_dir)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_set_visibility(
    name: str,
    visibility: str,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """公开/私有双集切换（public 是 HF 导出放行前提）。

    副作用：回写数据集 manifest 的 visibility 字段。

    Args:
        name: 数据集名
        visibility: public | private
        out_dir: 数据集根目录

    Returns:
        dict: {ok, name, visibility} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_insights import set_dataset_visibility
    return set_dataset_visibility(name, visibility, out_dir=out_dir)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_export_hf(
    name: str,
    license: str = "",
    allow_private: bool = False,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """HF datasets 本地目录布局导出（parquet 分片 + README 数据卡，确定性）。

    副作用：写 <dataset_dir>/hf/。private 数据集默认拒绝（防战役数据误发布）。

    Args:
        name: 数据集名
        license: 数据卡 license 字段
        allow_private: 显式允许导出 private 数据集
        out_dir: 数据集根目录

    Returns:
        dict: {ok, hf_dir, files, ...} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_insights import export_hf_dataset
    return export_hf_dataset(name, out_dir=out_dir, license=license,
                             allow_private=allow_private)


# ─── 30. VNA 软侧离线回放（透传薄壳） ──────────────────────────

@mcp.tool
def vna_offline_replay(
    measured_s2p: str,
    sim_s2p: str | None = None,
    threshold_db: float = 3.0,
    session_path: str | None = None,
) -> dict[str, Any]:
    """mock 仪表采集→校准→相关全链回放（历史 Touchstone 供数，零硬件）。

    无硬件副作用；session_path 给定时 best-effort 落会话 JSONL。

    Args:
        measured_s2p: 历史测量 Touchstone（供 MockVNAInstrument）
        sim_s2p: 仿真 Touchstone（缺省=同 measured_s2p 自比对）
        threshold_db: 相关性 dB 偏差门
        session_path: 会话 JSONL 落盘路径（可选）

    Returns:
        dict: {ok, connect, calibrate, capture, calibration, correlation}
    """
    from rfauto.service.api import vna_offline_replay as _replay
    return _replay(measured_s2p, sim_s2p, threshold_db=threshold_db,
                   session_path=session_path)


# ─── 30b. DP-11 VNA 测量闭环：En 相关性报告（measurement/en_report 薄壳） ─────

@mcp.tool
def vna_en_report(
    lab_s2p: str,
    ref_s2p: str,
    traces: list[str] | None = None,
    delta_t_c: float | None = None,
    anchor_uncertainty_db: float | None = None,
    hfss_residual_db: float | None = None,
    markdown_path: str | None = None,
) -> dict[str, Any]:
    """En 计量学相关性报告（DP-11）：|En|≤1 判满意，深谷自动切线性域。

    U_meas=GUM 预算表（configs/uncertainty_budgets.yaml 默认模板），
    U_sim=锚 uncertainty→HFSS 仲裁残差→兜底（source=fallback 如实标注）。
    频轴对齐 argmin 最近邻+ulp 容差（#287/#294）。

    Args:
        lab_s2p: 实测 Touchstone
        ref_s2p: 仿真参考 Touchstone
        traces: 迹线名列表（缺省 ["S11","S21"]）
        delta_t_c: 温差覆盖（°C；缺省用预算表 delta_t_c）
        anchor_uncertainty_db: 锚不确定度（U_sim 第一优先）
        hfss_residual_db: HFSS 仲裁残差（U_sim 第二优先）
        markdown_path: Markdown 报告落盘路径（可选）

    Returns:
        dict: {ok, traces: {…}, summary, markdown}
    """
    from rfauto.service.vna_service import vna_en_report as _report
    return _report(
        lab_s2p, ref_s2p,
        traces=tuple(traces) if traces else ("S11", "S21"),
        delta_t_c=delta_t_c,
        anchor_uncertainty_db=anchor_uncertainty_db,
        hfss_residual_db=hfss_residual_db,
        markdown_path=markdown_path)


# ─── 31. F9 报告叙述位 / F11 经验记忆（0bj / 0z 薄壳） ────────────────────────

@mcp.tool
def report_narrative(
    run_id: str,
    narrative: str | None = None,
    on_unauthorized: str = "reject",
) -> dict[str, Any]:
    """F9 设计报告叙述：run 白名单 → 确定性模板叙述，或审计外来叙述的数字。

    无副作用；不触发任何 LLM 调用（LLM 只作 service 层可注入接口）。
    narrative 给定时返回 canonical 化文本 + violations（未授权数字定位）。

    Args:
        run_id: 已完成 run（runs/<run_id>/meta.json 须存在）
        narrative: 外来叙述文本；缺省=生成模板叙述
        on_unauthorized: reject | fallback（仅 LLM 路径生效）

    Returns:
        dict: {ok, run_id, mode, narrative, violations, provenance, ...}
    """
    from rfauto.service.report_narrative import report_narrative_for_run
    return report_narrative_for_run(run_id, narrative=narrative,
                                    on_unauthorized=on_unauthorized)


@mcp.tool
def rationale_recall(
    task: str,
    memory_path: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """F11 经验记忆检索：任务描述 → 命中历史坑/核对表/动作（确定性，无 embedding）。

    无副作用，可安全调用。缺省用内置经验（#198/#219/#152 网格伪象核对表）。

    Args:
        task: 任务描述文本（模板名/场景关键词）
        memory_path: 外部经验记忆 JSON（save_entries 产物）；缺省仅内置
        top_k: 返回命中数上限

    Returns:
        dict: {ok, hits, checklists, actions, require_offline_audit}
    """
    from rfauto.service.rationale_memory import recall_with_memory
    return recall_with_memory(task, memory_path=memory_path, top_k=top_k)


@mcp.tool
def rationale_checklist(
    template: str,
    extras: str | None = None,
    memory_path: str | None = None,
) -> dict[str, Any]:
    """F11 冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计）。

    无副作用，可安全调用。返回 markdown 章节供报告/设计任务描述直接嵌入。

    Args:
        template: 模板名（如 patch、cyl_grid）
        extras: 场景补充关键词（可选）
        memory_path: 外部经验记忆 JSON；缺省仅内置

    Returns:
        dict: {ok, template, checklists, actions, hits, require_offline_audit, gate, markdown}
    """
    from rfauto.service.rationale_memory import checklist_with_memory
    return checklist_with_memory(template, extras=extras, memory_path=memory_path)


# ─── 32. RAG 知识库检索（薄壳，只读词法 BM25） ──────────────────────────

@mcp.tool
def rag_query(
    text: str,
    top_k: int = 5,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
) -> dict[str, Any]:
    """RAG 知识库词法检索（BM25，只读；citation 文件+标题+行号可溯）。

    索引仓库文档（docs/**/*.md）与 runs/ 战役元数据（meta.json +
    recipe.snapshot.yaml）；确定性、零网络、无 embedding/向量库。
    agent 开工前知识命中核对：与 rationale_checklist（F11 核对表门禁）
    配套使用，命中 citation 可直接打开原文核对。

    Args:
        text: 查询文本（中英文皆可，CJK bigram 分词）
        top_k: 返回命中数上限
        docs_dir: 文档目录（传 null 跳过该来源）
        runs_dir: runs 历史目录（传 null 跳过该来源）
        runs_limit: 最多索引 N 个 run 目录

    Returns:
        dict: {ok, query, query_terms, n_indexed, n_hits, n_matched,
               hits: [{rank, score, chunk_id, source_kind, citation, snippet}]}
    """
    from rfauto.service.rag_service import query_corpus
    return query_corpus(text, top_k=top_k, docs_dir=docs_dir,
                        runs_dir=runs_dir, base_dir=".", runs_limit=runs_limit)


@mcp.tool
def rag_explain(
    text: str,
    top_k: int = 5,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
) -> dict[str, Any]:
    """RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。

    同 rag_query（只读词法检索、citation 可溯），额外给出每个命中的
    逐词打分明细，便于核对"为什么命中/排名"。

    Args:
        text: 查询文本（中英文皆可）
        top_k: 返回命中数上限
        docs_dir: 文档目录（传 null 跳过该来源）
        runs_dir: runs 历史目录（传 null 跳过该来源）
        runs_limit: 最多索引 N 个 run 目录

    Returns:
        dict: 同 rag_query，hits[].score_breakdown 附逐词明细
    """
    from rfauto.service.rag_service import explain_corpus
    return explain_corpus(text, top_k=top_k, docs_dir=docs_dir,
                          runs_dir=runs_dir, base_dir=".", runs_limit=runs_limit)


# ─── 33. 接线层装车（审查 D 分片 M1/M5 + C 分片 D1：自愈环/LogDistiller/色散） ──
# 三个"造了零件没装上车"的内核接进只读生产路径；全部零逻辑转发 service
# 信封（规则 4），数值/判定只在确定性内核（铁律 7），不打印 stdout（#242）。

@mcp.tool
def self_heal_run(run_id: str, retries: int = 0) -> dict[str, Any]:
    """对既有 run 跑一次只读自愈环（F5/WP3.5）：日志面蒸馏 → 确定性 critique
    （11 失败签名根因目录）→ 根因/教训编号/建议动作。

    无副作用（只读 runs/<run_id>；attempt=重读日志面，零真机、零网络）。
    **只诊断+建议**：不自动修改配方——落地动作走既有三层 Gate/沙箱
    （agent propose/apply）。llm_used 恒为 False（铁律 7，LLM 不判定）。

    Args:
        run_id: 已落盘 run（runs/<run_id>/meta.json 须存在）
        retries: 自愈环重试次数（只读模式下 attempt 确定性重读，默认 0）

    Returns:
        dict: {ok, run_id, verdict: clean|diagnosed|unknown_failure,
               root_cause_id, root_cause, lesson_ref, severity, causes,
               actions, signatures, digest, history, attempts, llm_used,
               advisory_only, note} 或 {ok: False, errors}
    """
    from rfauto.service.self_heal_service import self_heal_run_for_run
    return self_heal_run_for_run(run_id, retries=retries)


@mcp.tool
def log_digest(path: str, source: str = "auto") -> dict[str, Any]:
    """日志文件 / 审计 JSON / run 目录 → 结构化 digest（WP3.6 LogDistiller）。

    无副作用（只读，不落文件；run 收尾自动落的 runs/<id>/log_digest.json
    由 create_run 主路径 best-effort 产出）。纯规则确定性：rc/errors/
    warnings/关键指标/失败签名，数值只取自日志原文不做物理推断。

    Args:
        path: 日志文件（openEMS stdout / PyAEDT 日志 / 审计 JSON）或 run 目录
        source: 数据源标识（auto|openems|hfss|audit_json|generic；auto 按内容判定）

    Returns:
        dict: {ok, path, digest: {ok, source, rc, errors, warnings, metrics,
               signatures, n_lines, truncated, notes}} 或 {ok: False, errors}
    """
    from rfauto.service.self_heal_service import log_digest_for_path
    return log_digest_for_path(path, source=source)


@mcp.tool
def dispersion_report(
    material: str,
    band_ghz: list[float] | None = None,
    max_eps_r_drift: float = 0.02,
) -> dict[str, Any]:
    """材料色散适应性报告（D1）：Djordjevic-Sarkar 模型算带内 εr/tanδ 漂移，
    判"常数 εr 近似是否成立"（默认 ≤2% 门），不成立给 openEMS/HFSS 修正参数。

    无副作用（只读 configs/materials.yaml，零求解器）。**不改任何模板/适配器
    渲染行为**——模板接色散渲染属语义变更需锚重跑。已配 RO4350B
    色散条目 rogers4350b_h0.508_dispersion（Dk=3.66/Df=0.0037 @10GHz）。

    Args:
        material: materials.yaml 材料键（须含 dispersion 条目）
        band_ghz: [f_low, f_high]（GHz）；缺省用该材料 D-S 拟合频带端点
        max_eps_r_drift: 常数 εr 近似门（相对漂移，默认 0.02）

    Returns:
        dict: {ok, material, band_ghz, f_meas_ghz, eps_r_at_meas,
               tan_delta_at_meas, samples, eps_r_drift_pct, tan_delta_drift_pct,
               gate: {passed, verdict, ...}, correction?, config_note,
               follow_up_note} 或 {ok: False, errors, available_dispersion_materials}
    """
    from rfauto.service.dispersion_service import dispersion_fitness_report
    return dispersion_fitness_report(
        material, band_ghz, max_eps_r_drift=max_eps_r_drift)


# ─── 34. db 注册表薄壳（SQLite 事务型注册表 + DuckDB 分析直读） ──────────
# 六工具零逻辑转发 service/db_service（规则 4）；query 走只读 SELECT 白名单
# （拒绝进信封不抛出）；数值/物理语义不经过本层（铁律 7）。db_path 缺省
# 取 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite（相对当前工作目录）。

@mcp.tool
def db_init(db_path: str | None = None) -> dict[str, Any]:
    """注册表数据库建库 + 幂等迁移（SQLite；首次 applied=1，重放 applied=0）。

    有副作用：创建/迁移 SQLite 文件（runs/ 已 gitignore）。等价 db_migrate。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, path, schema_version, applied, backend}
    """
    from rfauto.service.db_service import db_init as _db_init
    return _db_init(db_path)


@mcp.tool
def db_migrate(db_path: str | None = None) -> dict[str, Any]:
    """注册表数据库幂等迁移（schema_version 表递增；重复执行零变更）。

    有副作用：迁移 SQLite 文件（不存在则创建）。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, path, schema_version, applied, backend}
    """
    from rfauto.service.db_service import db_migrate as _db_migrate
    return _db_migrate(db_path)


@mcp.tool
def db_status(db_path: str | None = None) -> dict[str, Any]:
    """注册表状态盘点：路径/存在性/schema 版本/各表行数（文件不存在不创建）。

    无副作用，可安全调用。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, backend, path, exists, schema_version, tables: {表名: 行数}}
    """
    from rfauto.service.db_service import db_status as _db_status
    return _db_status(db_path)


@mcp.tool
def db_reindex_runs(runs_dir: str = "runs",
                    db_path: str | None = None) -> dict[str, Any]:
    """扫 runs/*/meta.json 重建注册表 runs 表（upsert 幂等可重放）。

    有副作用：写注册表 runs 表；单个 meta.json 失败不阻塞整体（#105），
    runs 目录不存在如实返回零值不建目录。

    Args:
        runs_dir: runs 目录（扫 */meta.json）
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, reindexed, failed, errors(截断 20 条), db_path, note?}
    """
    from rfauto.service.db_service import reindex_runs
    return reindex_runs(runs_dir, db_path=db_path)


@mcp.tool
def db_query(
    sql: str,
    params: list[str | int | float | bool | None] | None = None,
    limit: int = 200,
    db_path: str | None = None,
) -> dict[str, Any]:
    """只读查询注册表：仅单条 SELECT + ? 占位符参数绑定（白名单纵深防御）。

    无副作用（只读）。非 SELECT/多语句/注释/禁用关键词/非法字符一律拒绝，
    拒绝原因与执行错误进 {ok: False, errors} 信封不抛出。行数上限 5000，
    超出截断并标记 truncated。示例：
    db_query("SELECT run_id, model FROM runs WHERE adapter = ?", ["hfss"])

    Args:
        sql: 单条只读 SELECT（? 占位符）
        params: 占位符标量参数列表（str/int/float/bool/null）
        limit: 返回行数上限（默认 200，最大 5000）
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）

    Returns:
        dict: {ok, columns, rows, row_count, truncated, limit} 或 {ok: False, errors, sql}
    """
    from rfauto.service.db_service import db_query_safe
    return db_query_safe(sql, params, limit=limit, db_path=db_path)


@mcp.tool
def db_analytics_attach(db_path: str | None = None,
                        sample_limit: int = 3) -> dict[str, Any]:
    """DuckDB sqlite 扩展直读注册表文件（零拷贝分析面）：逐表计数 + 最近 runs 示例。

    无副作用（只读附加为 reg）。duckdb 未装/扩展不可加载/文件不存在 →
    ok=False + reason 如实返回，绝不 raise（#105）。

    Args:
        db_path: 注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB 或 runs/registry.sqlite）
        sample_limit: 示例查询最近 runs 条数

    Returns:
        dict: {ok, path, attached_as, duckdb_version, tables, sample_runs} 或
              {ok: False, reason, path, attached_as}
    """
    from rfauto.service.db_service import analytics_attach
    return analytics_attach(db_path, sample_limit=sample_limit)


# ─── 35. 槽线与过渡薄壳（slotline / transitions） ─────────────────────────
# 五工具零逻辑转发 service/slotline_service（规则 4）；数值只出确定性内核
# （铁律 7：core/slotline Janaswamy–Schaubert 闭式、core/slotline_transitions
# Roberts/Knorr 过渡 + Marchand 两节耦合段电路级综合）；越有效域拒绝进
# {ok: False, error} 信封不外推；realizable=False 是合法结果非错误（#122）。

@mcp.tool
def slotline_analysis(w_mm: float, h_mm: float, epsilon_r: float,
                      freq_ghz: float) -> dict[str, Any]:
    """槽线（slotline）闭式分析：Janaswamy–Schaubert 1986 分段拟合 (w, h, εr, f) →
    λ'/λ0、εeff、β、Z0（功率-电压定义）、槽波长 λ'。

    无副作用，可安全调用。有效域 0.006≤d/λ0≤0.06、窄槽段 0.0015≤W/λ0≤0.075、
    εr∈[2.22,9.8] 两段；越域 ok=False 显式拒绝不外推（宽槽段/高 εr 段未实现）。

    Args:
        w_mm: 槽宽 mm（金属面上的缝）
        h_mm: 基板厚 mm（单面金属、基板下为空气）
        epsilon_r: 基板相对介电常数（2.22–3.8 / 3.8–9.8 两段拟合）
        freq_ghz: 频率 GHz（W/λ0、d/λ0 进入拟合式，必需）

    Returns:
        dict: {ok, result: {z0_ohm, eps_eff, lambda_ratio, beta_rad_m, lambda_g_mm,
               segment, w_over_lambda0, d_over_lambda0}} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import slotline_analysis as _analysis
    return _analysis(w_mm, h_mm, epsilon_r, freq_ghz)


@mcp.tool
def slotline_synthesis(z0_ohm: float, h_mm: float, epsilon_r: float,
                       freq_ghz: float) -> dict[str, Any]:
    """槽线（slotline）综合：目标 Z0 → 槽宽 w（窄槽段括号 brentq 反解 + 闭式回代自洽）。

    无副作用，可安全调用。目标超窄槽段可达范围 = 合法结果 realizable=False
    （ok=True + reason 含可达范围，与 marchand 两节语义统一）；基板/频率越域
    等参数非法仍 ok=False 显式拒绝（error 含域信息）。

    Args:
        z0_ohm: 目标特性阻抗 Ω（功率-电压定义）
        h_mm: 基板厚 mm
        epsilon_r: 基板相对介电常数
        freq_ghz: 频率 GHz

    Returns:
        dict: {ok, realizable, result: {w_mm, z0_actual_ohm, eps_eff,
               lambda_ratio, beta_rad_m, lambda_g_mm, segment}}；
               不可达 = {ok: True, realizable: False, reason}；非法 = {ok: False, error}
    """
    from rfauto.service.slotline_service import slotline_synthesis as _synthesis
    return _synthesis(z0_ohm, h_mm, epsilon_r, freq_ghz)


@mcp.tool
def msl_slot_transition_design(f0_ghz: float, h_mm: float, er: float,
                               w_slot_mm: float, tan_d: float = 0.0037,
                               z_msl_target: float = 50.0) -> dict[str, Any]:
    """Roberts/Knorr MSL↔槽线过渡设计参数：微带 skrf HJ 综合 + 槽线闭式精算。

    无副作用，可安全调用。开路支节 l_stub=λg_m/4+Δl_open（Hammerstad 开路端修正）、
    槽线短路臂 l_short=λg'/4；越槽线有效域 ok=False 不外推。gates 为预声明过渡门
    （带内 max|S11|≤−10dB、f0 超额损耗 ≤1dB），供真机判读同源。

    Args:
        f0_ghz: 设计中心频率 GHz
        h_mm: 基板厚 mm
        er: 基板相对介电常数
        w_slot_mm: 槽宽 mm
        tan_d: 基板损耗角正切（默认 0.0037，RO4350B）
        z_msl_target: 微带馈线目标阻抗 Ω（默认 50）

    Returns:
        dict: {ok, design: {f0_ghz, w_slot_mm, h_mm, er, z_slot_ohm, eps_eff_slot,
               lambda_slot_mm, l_short_mm, w_msl_mm, z_msl_ohm, eps_eff_msl,
               l_stub_mm, dl_open_mm}, gates} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import msl_slot_transition_design as _design
    return _design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_target)


@mcp.tool
def marchand_balun_design(f0_ghz: float, h_mm: float, er: float,
                          w_slot_mm: float, tan_d: float = 0.0037,
                          z_msl_target: float = 50.0) -> dict[str, Any]:
    """双槽臂 Marchand 巴伦（最小族）设计参数：过渡参数 + 槽距 d_c=w_msl+s_slot。

    无副作用，可安全调用。两跨越点共享开路支节与两段 λg'/4 短路臂；a1/a2 为
    槽内/外缘到中线距离。注意：该单支节串接族已被两引擎互证不满足巴伦四门
    （设计级结论：单支节串接已被两引擎互证证伪），保留作对照几何；真 Marchand 走
    marchand_two_section_synthesis。gates 为预声明巴伦门。

    Args:
        f0_ghz: 设计中心频率 GHz
        h_mm: 基板厚 mm
        er: 基板相对介电常数
        w_slot_mm: 槽宽 mm
        tan_d: 基板损耗角正切（默认 0.0037）
        z_msl_target: 微带馈线目标阻抗 Ω（默认 50）

    Returns:
        dict: {ok, design: {…过渡参数…, d_center_mm, a1_mm, a2_mm}, gates}
              或 {ok: False, error}
    """
    from rfauto.service.slotline_service import marchand_balun_design as _design
    return _design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_target)


@mcp.tool
def marchand_two_section_synthesis(
    f0_ghz: float = 2.5,
    z_unbal_ohm: float = 50.0,
    z_bal_diff_ohm: float = 280.0,
    er: float = 3.66,
    h_mm: float = 1.524,
    tan_d: float = 0.0037,
    s_min_mm: float = 0.1,
    w_max_mm: float = 6.0,
    z_c_ohm: float | None = None,
    band_ghz: list[float] | None = None,
) -> dict[str, Any]:
    """两节对称 Marchand 巴伦电路级综合：f0 匹配闭式 → (Z0e,Z0o) → KJ 几何反解 (w,s)
    → 节长 λ/4 → 电路级 3 端口 S 自检门（确定性内核，无耗 TEM 理想耦合线）。

    无副作用，可安全调用（数十次 brentq，秒级）。匹配不变量 L_req=√(Z_s·Z_t/2)；
    z_c_ohm 缺省沿等 L 族自动扫描取首个满足 s≥s_min、w≤w_max 的可达点。
    **realizable=False 是合法结果**（边耦合微带不可达 → 钳位最近点 + 门如实），
    不进 error；参数非法/越域 ok=False。缺省名义点 50Ω→280Ω 差分 @RO4350B 60mil。

    Args:
        f0_ghz: 设计中心频率 GHz（默认 2.5）
        z_unbal_ohm: 不平衡端阻抗 Ω（默认 50）
        z_bal_diff_ohm: 平衡端差分阻抗 Ω（单端参考 Z_L/2；默认 280）
        er: 基板相对介电常数（默认 3.66）
        h_mm: 基板厚 mm（默认 1.524）
        tan_d: 基板损耗角正切（默认 0.0037）
        s_min_mm: 可制造最小耦合缝 mm（默认 0.1）
        w_max_mm: 耦合段线宽上限 mm（默认 6.0）
        z_c_ohm: 耦合段 Z_c=√(Z0e·Z0o) Ω（缺省 None 自动扫描）
        band_ghz: 自检带 [f_lo, f_hi] GHz（缺省 f0±10%）

    Returns:
        dict: {ok, design: {realizable, coupling, coupling_db, z0e_ohm, z0o_ohm,
               z0e_realized_ohm, z0o_realized_ohm, w_mm, s_mm, l_sect_mm, w_feed_mm,
               w_bal_line_mm, slot_balanced, model_metrics: {…, gates, all_gates_pass},
               notes, …}, nominal_params, gates} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import (
        marchand_two_section_synthesis as _synthesis,
    )
    return _synthesis(f0_ghz, z_unbal_ohm, z_bal_diff_ohm, er, h_mm, tan_d,
                      s_min_mm, w_max_mm, z_c_ohm, band_ghz)


# ─── MCP resources（E4c 版本化只读资源，v2 尾巴） ────────────────────────────
# 资源只读、无副作用；内容与 CLI/服务层同源（注册表 runs 表 + YAML 知识库文件）。

@mcp.resource("rfauto://runs/index")
def runs_index_resource() -> dict[str, Any]:
    """runs 索引（缺省注册表最近 20 条，同 run_store.list_runs）。"""
    from rfauto.infra.run_store import list_runs
    return {"runs": list_runs(limit=20)}


@mcp.resource("rfauto://knowledge/materials")
def materials_resource() -> dict[str, Any]:
    """材料库（configs/materials.yaml 原文结构）。"""
    import yaml

    with open("configs/materials.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@mcp.resource("rfauto://knowledge/compat_matrix")
def compat_matrix_resource() -> dict[str, Any]:
    """版本兼容矩阵（knowledge/compat_matrix.yaml 原文结构）。"""
    import yaml

    with open("knowledge/compat_matrix.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ─── 32. DP-1 MMT 秒级段表求解（mmt_service 薄壳） ────────────────────────────

@mcp.tool
def mmt_solve(
    sections: list[dict[str, Any]],
    freqs_ghz: list[float] | None = None,
    eps_r: float = 1.0,
    tan_d: float = 0.0,
    sigma_s_m: float | None = None,
    mode_policy: dict[str, Any] | None = None,
    z0_ref: float = 50.0,
    freq_start_ghz: float | None = None,
    freq_stop_ghz: float | None = None,
    n_freq: int = 41,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """自研 RWG/SIW 模基 MMT（GSM）段表求解（DP-1：秒级零外部进程）。

    段表三型（mm 口径）：uniform（a_mm/b_mm/length_mm）、hstep（a_left_mm/
    b_left_mm/a_right_mm/b_right_mm，缺省几何居中）、iris（a_mm/b_mm/
    aperture_mm/thickness_mm，零厚度=零长段三件级联）。SIW 膜片/阶梯的
    w_eff 须由调用方经 siw_effective_width_mm 折算后传入。

    无外部进程/license；undetermined 频点（近截止/过传）S=null 不外推；
    膜片/阶梯绝对 S 值 UNDECIDABLE 待 HFSS 仲裁（随信封 absolute_s_note）。

    Args:
        sections: 段表列表（mm 口径三型，见上）
        freqs_ghz: 显式频点网格 GHz（≥2 点严格递增；与 start/stop 二选一）
        eps_r: 顶层缺省相对介电常数（段内可覆盖）
        tan_d: 顶层缺省损耗正切
        sigma_s_m: 顶层缺省导体电导率 S/m（None=PEC 壁）
        mode_policy: 模式数策略（n_modes_ref/n_modes_max/n_doublings_max 等）
        z0_ref: 端口参考阻抗 Ω（缺省 50）
        freq_start_ghz: 均匀网格起点（freqs_ghz 缺省时用）
        freq_stop_ghz: 均匀网格终点
        n_freq: 均匀网格点数（缺省 41）
        work_dir: 产物目录（缺省临时目录；写 sparams.csv/mmt.s2p/mmt_meta.json）

    Returns:
        dict: {ok, freqs_ghz, s11/s21/s12/s22, z_pv_ports, beta_te10_ports,
        converged, warnings, undetermined_freqs_ghz, artifacts, ...}
    """
    from rfauto.service.mmt_service import solve_mmt

    payload: dict[str, Any] = {
        "sections": sections,
        "eps_r": eps_r,
        "tan_d": tan_d,
        "z0_ref": z0_ref,
        "n_freq": n_freq,
    }
    if freqs_ghz is not None:
        payload["freqs_ghz"] = freqs_ghz
    if sigma_s_m is not None:
        payload["sigma_s_m"] = sigma_s_m
    if mode_policy is not None:
        payload["mode_policy"] = mode_policy
    if freq_start_ghz is not None:
        payload["freq_start_ghz"] = freq_start_ghz
    if freq_stop_ghz is not None:
        payload["freq_stop_ghz"] = freq_stop_ghz
    return solve_mmt(payload, work_dir=work_dir)


@mcp.tool
def compose_netlist(netlist: dict, out_dir: str | None = None) -> dict[str, Any]:
    """模板几何组合（DP-8）：netlist 三段式 → 单一 simulation.py（布局合并路线）。

    Args:
        netlist: rfauto-netlist-v1 三段式 netlist（schema 详见
            service/compose_service.py 模块头；instances/connections/
            exposed_ports 三段式）
        out_dir: 产物目录（None=runs/compose_<ts>）

    Returns:
        dict: {ok, out_dir, simulation_py, compose_meta, netlist_yaml, ...}
    """
    from rfauto.service.compose_service import compose_from_netlist, compose_write
    try:
        if out_dir:
            return compose_write(netlist, out_dir)
        return compose_from_netlist(netlist)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def nfmeas_ffs_info(path: str) -> dict[str, Any]:
    """审计 HFSS .ffs 远场文件头（频率/三功率/网格规模/轴序）。无副作用。"""
    from rfauto.service.nf_measurement_service import ffs_info
    return ffs_info(path)

@mcp.tool()
def nfmeas_cut_view(path: str, freq_index: int = 0, phi_deg: float | None = None,
                    theta_deg: float | None = None) -> dict[str, Any]:
    """.ffs 单频块切面视图（固定 phi 取 θ 扫描，或反之），幅度+归一 dB。"""
    from rfauto.service.nf_measurement_service import ffs_cut_view
    return ffs_cut_view(path, freq_index=freq_index, phi_deg=phi_deg,
                        theta_deg=theta_deg)

@mcp.tool()
def nfc_coil_evaluate(shape: str, n_turns: float, d_out_mm: float,
                      w_um: float, s_um: float) -> dict[str, Any]:
    """Mohan 1999 三表达式平面螺旋电感评估（nH）。几何不可行显式报错。"""
    from rfauto.service.nfc_coil_service import coil_evaluate
    return coil_evaluate(shape, n_turns, d_out_mm * 1e-3, w_um * 1e-6, s_um * 1e-6)

@mcp.tool()
def nfc_coil_synthesize(target_l_nh: float, shape: str, n_turns: float,
                        w_um: float, s_um: float,
                        expression: str = "current_sheet") -> dict[str, Any]:
    """目标电感 → 外径二分反解（回代自洽 ≤1e-10）。"""
    from rfauto.service.nfc_coil_service import coil_synthesize
    return coil_synthesize(target_l_nh * 1e-9, shape, n_turns, w_um * 1e-6,
                           s_um * 1e-6, expression=expression)

@mcp.tool()
def nfc_coil_q(f_mhz: float, l1_nh: float, r1_ohm: float, m_nh: float = 0.0,
               l2_nh: float = 0.0, r2_ohm: float = 0.0) -> dict[str, Any]:
    """有载/无载 Q（互感 T 模型精确式）；R₁≤0 → Q 如实 None。"""
    from rfauto.service.nfc_coil_service import coil_q
    return coil_q(f_mhz * 1e6, l1_nh * 1e-9, r1_ohm, m_nh * 1e-9,
                  l2_nh * 1e-9, r2_ohm)

@mcp.tool()
def sar_analytic_plane_wave(freq_mhz: float, e0_v_per_m: float,
                            sigma_s_per_m: float, epsilon_r: float,
                            rho_kg_m3: float,
                            depth_mm: list[float]) -> dict[str, Any]:
    """有耗半空间平面波 SAR 闭式对照（α 闭式+随深衰减，判据锚）。"""
    from rfauto.service.sar_service import sar_analytic_plane_wave
    return sar_analytic_plane_wave(freq_mhz * 1e6, e0_v_per_m, sigma_s_per_m,
                                   epsilon_r, rho_kg_m3,
                                   [d * 1e-3 for d in depth_mm])

@mcp.tool
def explain_run(run_dir: str, playbook_path: str | None = None) -> dict[str, Any]:
    """失败指纹解释（DP-17 W2）：run 目录→确定性指纹匹配→候选根因族。

    多证并击只出候选族（按命中数降序），不下黑箱结论；无 LLM。
    无副作用（只读 run 产物与 playbook）。

    Args:
        run_dir: run 目录（runs/<id>）
        playbook_path: playbook.yaml 路径（缺省 knowledge/diagnostics/playbook.yaml）

    Returns:
        dict: {ok, run_dir, matches:[{root_cause_family, evidence, pit_refs}], ...}
    """
    from rfauto.service.explain_run import explain_run
    return explain_run(run_dir, playbook_path=playbook_path)


@mcp.tool
def list_composable_templates() -> dict[str, Any]:
    """列出已注册组合契约模板与 pin schema（DP-8 opt-in 台账）。

    Returns:
        dict: {ok, result: {templates: [{template, port_pins,
               schema_declared}], n_templates}}——port_pins 每 pin 含
               pin_id/position（局部坐标米）/direction（外法向）/
               z_ref_ohm（None=闭式同源注入）/ref_plane_offset_m/
               port_type（lumped|msl|waveguide|field）/n_modes（预留）/
               cross_section（截面指纹）
    """
    from rfauto.service.compose_service import list_composable_templates
    try:
        return list_composable_templates()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 锚注册表 (DP-3) ──────────────────────────────────────────────────────────

@mcp.tool
def anchors_list() -> dict[str, Any]:
    """列出物理标定锚注册表全部锚（DP-3，knowledge/anchors.yaml）。

    无副作用，可安全调用。

    Returns:
        dict: {ok, registry, count, expected_count, load_errors,
               anchors: [{anchor_id, kind, status, version, engine_pair,
               quantity, value, uncertainty, domain, fallback}]}
    """
    from rfauto.service.anchors_service import list_anchors
    try:
        return list_anchors()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def anchors_inspect(anchor_id: str) -> dict[str, Any]:
    """单锚全量记录（DP-3）：provenance/uncertainty/domain/consumers。

    无副作用，可安全调用。

    Args:
        anchor_id: 锚 id（如 c3.l_via_h.openems-hfss-v1）

    Returns:
        dict: {ok, anchor: {全量字段 + version}}
    """
    from rfauto.service.anchors_service import inspect_anchor
    try:
        return inspect_anchor(anchor_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 33. df7 T2 SI 通道报告（si_channel_service 薄壳） ────────────────────────

@mcp.tool
def si_channel_report(
    source: str,
    passivity_tol: float = 0.01,
    causality_threshold: float = 0.02,
    pre_cursor_guard_ns: float = 1.0,
    tdr_window_ns: float = 2.0,
    fext_paths: list[str] | None = None,
    next_paths: list[str] | None = None,
    markdown: bool = False,
) -> dict[str, Any]:
    """SI 通道一键报告（df7 T2：无源性/因果性/TDR/COM 四段，纯后处理）。

    无源性=全频段 σmax(S)≤1+tol（numpy SVD）；因果性=IEEE P370 风格
    （带限 IFFT 负时间能量占比 + 低频视在群延迟符号，自实现口径如实标注）；
    TDR=S11 阶跃响应阻抗剖面（前 2ns 均值/全程 min/max/平坦度+降采样剖面）；
    COM=IEEE 93A 冻结口径（PyChOpMarg，4 端口文件可用，2 端口如实
    not_applicable，pychopmarg 缺装/失败 degraded 不阻塞，#105）。

    Args:
        source: Touchstone 文件路径（.sNp）或 run 目录（sparams.csv 掩码
            口径优先，或 Touchstone 产物）
        passivity_tol: 无源性容差（max σmax ≤ 1+tol）
        causality_threshold: 负时间能量占比阈值
        pre_cursor_guard_ns: 因果性循环尾窗宽度 ns
        tdr_window_ns: TDR 统计窗 ns
        fext_paths: COM 远端串扰 4 端口文件列表（可选）
        next_paths: COM 近端串扰 4 端口文件列表（可选）
        markdown: True 时附带 markdown 渲染文本

    Returns:
        dict: {ok, source, passivity, causality, tdr, com, provenance,
        warnings, markdown?}
    """
    from rfauto.service.si_channel_service import si_channel_report
    try:
        return si_channel_report(
            source,
            passivity_tol=passivity_tol,
            causality_threshold=causality_threshold,
            pre_cursor_guard_ns=pre_cursor_guard_ns,
            tdr_window_ns=tdr_window_ns,
            fext_paths=fext_paths,
            next_paths=next_paths,
            markdown=markdown,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 34. df7 F3 runs 湖（lake_service 薄壳；MCP 面最小化注记） ────────────────
# MCP 面只暴露只读查询（lake_query_runs）与本地归档产出（lake_pack_campaign）。
# index/verify/restore 属本地运维面（index 写索引库、verify/restore 处理本地
# 归档落盘/恢复），不进 MCP——最小面原则；本地运维走 CLI `rfauto lake ...`。

@mcp.tool
def lake_query_runs(
    db_path: str | None = None,
    template: str | None = None,
    adapter: str | None = None,
    study: str | None = None,
    campaign: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """runs/ 湖索引只读查询（df7 F3）：等值过滤+日期段，参数化 ? 绑定。

    查询前需先建索引库（CLI `rfauto lake index` 或 service build_runs_index，
    属本地运维面不进 MCP）；库不存在/过滤值非法 → ok=False 如实不抛出。

    Args:
        db_path: 湖索引 DuckDB 路径（None=缺省 runs/.lake_index.duckdb）
        template: 模板过滤（meta.model 等值；None/空串不过滤）
        adapter: 适配器过滤（meta.adapter 等值；None/空串不过滤）
        study: study 过滤（meta.study_name 等值；None/空串不过滤）
        campaign: 战役目录名过滤（None/空串不过滤）
        date_from: 起始日期 YYYY-MM-DD（created_date 闭区间；None 不过滤）
        date_to: 截止日期 YYYY-MM-DD（created_date 闭区间；None 不过滤）
        limit: 返回行数上限（最小 1）

    Returns:
        dict: {ok, rows: [dict], n_rows, db_path, table}
    """
    from rfauto.service.lake_service import query_runs_index
    try:
        return query_runs_index(
            db_path, template=template, adapter=adapter, study=study,
            campaign=campaign, date_from=date_from, date_to=date_to,
            limit=limit)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def lake_pack_campaign(campaign_dir: str, out_path: str) -> dict[str, Any]:
    """战役目录打包为 tar.zst + 偏移清单（df7 F3 冷层压实，只读原目录）。

    确定性排序+归一化 tar 头（同内容重打包 pack_sha256 逐位一致）；偏移
    清单落 ``<out_path>.manifest.json``（每文件 path/offset/size/sha256 +
    整包 pack_sha256 内容寻址锚）。校验（verify）与恢复（restore）属本地
    运维面不进 MCP，走 CLI ``rfauto lake verify/restore``。

    Args:
        campaign_dir: 战役目录（只读，原目录零改动；不存在/无文件 ok=False）
        out_path: 归档落点（.tar.zst）

    Returns:
        dict: {ok, pack_path, manifest_path, n_files, total_bytes,
        pack_sha256, pack_size_bytes}
    """
    from rfauto.service.lake_service import pack_campaign
    try:
        return pack_campaign(campaign_dir, out_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 35. df7+ R4 渲染前声明式几何约束（render_constraint_service 薄壳） ───────
# z3 缺装降级在 core 内完成（status="unavailable" 进 verdict 不抛出）；
# config 形状非法的 ValueError 在此收进 ok=False 信封（不炸会话）。

@mcp.tool
def render_constraint_check(config: dict[str, Any]) -> dict[str, Any]:
    """渲染前声明式几何约束一次求解（R4：z3，UNSAT 全量冲突组+witness）。

    对渲染脚本的既有 if 链守卫做声明式前置检查（#266 缝格/#152 最小间距/
    #311 缝内线存在性/参数 bounds/NEAR=BASE/n 定义）；数值只在确定性内核
    （规则 7）：全部数字出自 z3 求解（witness）或本 config 输入。

    Args:
        config: 约束配置对象（键全部可选，缺项即不组装对应规则）：
            mesh_resolution_mm（float 钉值或 {low, high} 可取域）、
            near_ratio（缺省 4）、gaps_mm（缝宽列表取最小）或 min_gap_mm、
            gap_cells_min（缺省 3）、min_line_spacing_mm（缺省 1e-3）、
            mesh_lines_mm（{轴: [线位 mm]}，逐轴最小间距）、
            param_bounds（{变量: {low, high}}）、
            max_conflict_groups（缺省 8）

    Returns:
        dict: {ok, status, conflict_rule_ids, conflict_groups, rules,
        witness, near_mm, assembled, reason, solver}；z3 缺装时
        ok=False/status="unavailable"；config 非法 → ok=False/error 信封
    """
    from rfauto.service.render_constraint_service import evaluate_render_constraints
    try:
        return evaluate_render_constraints(config)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_mcp_server() -> FastMCP:
    """获取 MCP Server 实例。"""
    return mcp


def main() -> None:
    """console script 入口（pyproject ``[project.scripts] rfauto-mcp``）：
    stdio 传输启动 MCP Server。与 ``python -m rfauto.mcp_server`` 同源。

    保持零参数、零 stdout 打印：stdio 传输把 stdout 当协议信道，任何
    额外输出都会污染 JSON-RPC 帧（F4 发布口径）。
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    # 直接运行时启动 stdio 传输
    main()
