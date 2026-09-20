"""service 契约 pydantic 模型（阶段 4.2 首片：契约 schema 化 + 版本号）。

CLI/MCP/UI 四方共享的 service JSON 进出契约。原则：
- 消费方校验用：ServicePayload.validate() 返回 (ok, errors)，不抛异常
  （观测性 best-effort #105——契约违约显式报告而非炸掉调用方）；
- extra 字段忽略（服务输出允许携带超集字段，向前兼容）；
- SERVICE_SCHEMA_VERSION 随破坏性变更递增，产物头部携带。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SERVICE_SCHEMA_VERSION = 2


class _Contract(BaseModel):
    """契约基类：忽略额外字段，四方向前兼容。"""

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def validate(cls, payload: Any) -> tuple[bool, list[str], Any]:
        """校验 service 输出；返回 (ok, errors, model_or_none)。"""
        try:
            return True, [], cls.model_validate(payload)
        except Exception as exc:  # pydantic ValidationError 等
            return False, [str(exc)], None


class LoocvInfo(BaseModel):
    """LOOCV 结果（calibration/augment 共用）。"""

    model_config = ConfigDict(extra="ignore")

    ok: bool
    rho: float | None = None
    n_folds: int | None = None
    skipped: int | None = None
    error: str | None = None


class GatePayload(_Contract):
    """校准/增广 gate 契约（calibration_service 的 gate.json + 返回体）。"""

    verdict: str = Field(pattern="^(PASS|FAIL)$")
    loocv: LoocvInfo
    rho_threshold: float
    n_samples: int
    n_failures: int
    mesh_resolution_mm: float | None = None
    surrogate_kind: str | None = None


class CalibrationPayload(_Contract):
    """calibrate_surrogate / augment_calibration 返回契约。"""

    ok: bool
    run_id: str
    run_dir: str
    verdict: str
    loocv: LoocvInfo
    rho_threshold: float
    n_samples: int
    n_failures: int
    sampler: str
    elapsed_s: float
    # augment 扩展（calibrate 时缺省）
    n_seed_samples: int | None = None
    n_new_points: int | None = None
    n_new_samples: int | None = None
    mesh_resolution_mm: float | None = None


class AutotuneHistoryEntry(BaseModel):
    """自治环逐轮历史条目。"""

    model_config = ConfigDict(extra="ignore")

    round: int
    verdict: str
    cost: float | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    fixes: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class AutotunePayload(_Contract):
    """autotune_loop 返回契约（数值全部来自确定性内核）。"""

    ok: bool
    run_id: str
    run_dir: str
    verdict: str
    budget: int
    rounds_used: int
    final_params: dict[str, float]
    history: list[AutotuneHistoryEntry]
    best: dict[str, Any] | None = None
    elapsed_s: float | None = None


class SelfVerifyMilestone(BaseModel):
    """自验证环里程碑条目（decompose_milestones / proposer 覆写同形）。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    status: str = Field(pattern="^(pending|running|passed|failed|skipped)$")
    acceptance: str | None = None
    detail: str | None = None


class SelfVerifyPayload(_Contract):
    """self_verify_loop 返回契约（WP3.5 收口；AutotunePayload
    不覆盖 board_id/milestones/sandbox/loop 等新返回形状）。

    verdict：PASS=全部非 skipped 里程碑通过；FAIL=如实；TAKEN_OVER=人接管。
    history 条目形状随 phase（coarse/fine/error）有超集，extra 忽略。
    """

    ok: bool
    run_id: str
    run_dir: str
    verdict: str = Field(pattern="^(PASS|FAIL|TAKEN_OVER)$")
    loop: str = "self_verify"
    board_id: str | None = None
    proposer_note: str | None = None
    budget_coarse: int
    rounds_used: int
    final_params: dict[str, float]
    history: list[dict[str, Any]] = Field(default_factory=list)
    milestones: list[SelfVerifyMilestone] = Field(default_factory=list)
    best: dict[str, Any] | None = None
    sandbox: dict[str, Any] | None = None
    elapsed_s: float | None = None
    pause_notes: list[str] | None = None


class LoopBoardSummary(BaseModel):
    """执行看板清单单条摘要（loop_board.list_boards 条目）。"""

    model_config = ConfigDict(extra="ignore")

    board_id: str
    status: str | None = None
    recipe: str | None = None
    current_step: str | None = None
    milestones_done: int = 0
    n_milestones: int = 0
    updated_at: str | None = None


class LoopBoardsPayload(_Contract):
    """UI /api/loop/boards 返回契约（执行看板清单）。"""

    ok: bool
    boards: list[LoopBoardSummary] = Field(default_factory=list)


class LoopBoardPayload(_Contract):
    """UI /api/loop/board/{id} 返回契约（单看板文档；错误路径缺省+error）。"""

    ok: bool
    board_id: str | None = None
    status: str | None = None
    recipe: str | None = None
    current_step: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    milestones: list[SelfVerifyMilestone] = Field(default_factory=list)
    control: dict[str, Any] | None = None
    best: dict[str, Any] | None = None
    summary: str | None = None
    error: str | None = None


class LoopControlPayload(_Contract):
    """UI /api/loop/control 返回契约（pause/resume/takeover 命令回执）。"""

    ok: bool
    board_id: str | None = None
    command: str | None = Field(default=None, pattern="^(pause|resume|takeover)$")
    status: str | None = None
    error: str | None = None


class UQYieldPayload(_Contract):
    """surrogate_yield 返回契约（代理免费蒙特卡洛 UQ，6.4）。"""

    ok: bool
    samples_path: str
    surrogate_kind: str
    n_draws: int
    seed: int
    nominal_params: dict[str, float]
    yield_rate: float = Field(ge=0.0, le=1.0)
    metric_stats: dict[str, dict[str, float]]
    sensitivity_ranking: list[str]


class YieldDesignCenterPayload(_Contract):
    """yield_design_center 返回契约（良率目标函数+设计中心化，WP4.2）。"""

    ok: bool
    samples_path: str
    surrogate_kind: str
    k_sigma: float
    center: dict[str, float]
    yield_rate: float = Field(ge=0.0, le=1.0)
    initial_yield_rate: float = Field(ge=0.0, le=1.0)
    final_yield_mc: float = Field(ge=0.0, le=1.0)
    initial_yield_mc: float = Field(ge=0.0, le=1.0)
    n_evaluations: int


class TemperatureZoneYieldPayload(_Contract):
    """temperature_zone_yield 返回契约（D9 环境包络→温区良率，WP4.2）。"""

    ok: bool
    env_key: str
    sigma_c: float = Field(gt=0.0)
    half_range_c: float = Field(gt=0.0)
    nominal_params: dict[str, float]
    yield_rate: float = Field(ge=0.0, le=1.0)
    corner_pass: dict[str, bool]
    n_draws: int
    seed: int


class RunSummaryEntry(BaseModel):
    """runs 索引单条摘要。"""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    model: str | None = None
    adapter: str | None = None
    status: str | None = None
    timestamp: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class RunsSummaryPayload(_Contract):
    """runs_stats.runs_summary 返回契约（5.5 数据库化）。"""

    ok: bool
    total: int
    by_model: dict[str, int]
    by_adapter: dict[str, int]
    by_status: dict[str, int]
    recent: list[RunSummaryEntry]
    schema_version: int


class CrossGatePayload(_Contract):
    """p0 跨保真 gate 契约（1.1 资产复用通道 / 原生通道共用判定字段）。

    top5_recall 允许 None：p0_gate_service.cross_gate_from_asset 在
    n_evaluated<8 时 top5/top8 recall 恒 1 退化（#195 同族常数陷阱），
    如实置 None 仅按 ρ 门判定——契约窄类型 float 会把该合法路径判成违约。
    spearman_rho 保持 float（登记范围冻结）。
    """

    ok: bool
    verdict: str = Field(pattern="^(PASS|FAIL)$")
    spearman_rho: float
    top5_recall: float | None
    rho_threshold: float = 0.8
    n_evaluated: int


class ListRunsPayload(_Contract):
    """list_runs 返回契约（UI /api/runs 与 MCP runs 索引资源共用）。"""

    ok: bool
    runs: list[RunSummaryEntry] = Field(default_factory=list)


class RunDetailPayload(_Contract):
    """run_detail 返回契约（UI /api/runs/{rid} 与 MCP get_run_artifacts 共用）。

    files/sparams/figs 为产物明细（条目形状随 run 类型有超集，extra 忽略）；
    run_id 错误路径（run 不存在）缺省。
    """

    ok: bool
    run_id: str | None = None
    run_dir: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
    sparams: list[dict[str, Any]] = Field(default_factory=list)
    figs: list[str] = Field(default_factory=list)


class SparamsSeriesPayload(_Contract):
    """sparams_series 返回契约（UI /api/sparams/{rid}，3.1；错误路径缺省）。"""

    ok: bool
    run_id: str | None = None
    mode: str | None = Field(default=None, pattern="^(db|deg)$")
    curves: list[dict[str, Any]] = Field(default_factory=list)
    warning: str | None = None


class CostTimelinePayload(_Contract):
    """cost_timeline 返回契约（UI /api/cost_timeline，3.4）。"""

    ok: bool
    points: list[dict[str, Any]] = Field(default_factory=list)
    n_without_cost: int = 0
    latest_tune_run_id: str | None = None
    latest_tune_trials: list[dict[str, Any]] = Field(default_factory=list)


class ReportsListPayload(_Contract):
    """list_reports 返回契约（UI /api/reports，3.5）。"""

    ok: bool
    reports: list[dict[str, Any]] = Field(default_factory=list)


ALL_CONTRACTS: dict[str, type[_Contract]] = {
    "calibration": CalibrationPayload,
    "gate": GatePayload,
    "autotune": AutotunePayload,
    "self_verify": SelfVerifyPayload,
    "loop_boards": LoopBoardsPayload,
    "loop_board": LoopBoardPayload,
    "loop_control": LoopControlPayload,
    "uq_yield": UQYieldPayload,
    "yield_design_center": YieldDesignCenterPayload,
    "temperature_zone_yield": TemperatureZoneYieldPayload,
    "runs_summary": RunsSummaryPayload,
    "cross_gate": CrossGatePayload,
    "list_runs": ListRunsPayload,
    "run_detail": RunDetailPayload,
    "sparams_series": SparamsSeriesPayload,
    "cost_timeline": CostTimelinePayload,
    "reports_list": ReportsListPayload,
}


def annotate_contract(name: str, payload: Any) -> Any:
    """服务点 best-effort 契约校验（4.2 全量接线）。

    校验返回体是否符合注册契约 name，结果以 contract_check 字段注记进
    返回体——违约**不拦截响应**（观测性 best-effort #105：契约违约显式
    可见而非炸掉调用方）。未注册契约名原样返回；校验器自身异常同样只
    注记不抛出。
    """
    cls = ALL_CONTRACTS.get(name)
    if cls is None or not isinstance(payload, dict):
        return payload
    try:
        ok, errors, _model = cls.validate(payload)
    except Exception as exc:  # 校验器故障也不阻塞业务主路径
        ok, errors = False, [str(exc)]
    payload["contract_check"] = {
        "contract": name, "ok": ok, "errors": errors,
        "schema_version": SERVICE_SCHEMA_VERSION,
    }
    return payload


def contract_version() -> int:
    """契约版本号（产物头部携带；破坏性变更递增）。"""
    return SERVICE_SCHEMA_VERSION
