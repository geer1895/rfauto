"""EDB 快车道优化环发射器（LoopLauncher 协议的 EDB 实现，2026-10-08）。

把 EDB 快车道（edb_lane_service 一站式发射→建库→批解→Touchstone 导出）
接进 recipe 优化环的评估缝：``service/recipe_loop_remote.LoopLauncher``
协议（evaluate(params) -> EvalResult）的 EDB 实现——与 LocalLoopLauncher
（本地评估入口直调）/ RemoteLoopLauncher（远端占位）并列的第三通道。

链路（evaluate 一次 = 一次 EDB 发射）::

    params(设计参数，含 f0_ghz) → edb_lane_service.edb_build_solve
    （发射→建库→ansysedt 批解→批后 Touchstone 导出）
    → edb_health_gate.check_edb_batch_health（三态健康门判读）
    → 指标提取（判读报告单源）→ EvalResult(metrics, artifact)

- 指标单源（任务书口径）：metrics 全部从健康门判读报告（schema
  edb-health-gate-v1 的 criteria/summary）提取，勿 skrf 二次直读双实现；
  判读门本身消费 Touchstone（skrf），本模块不重复解析。
- 缺省目标语义（任务书口径）：cost = fail_penalty × 健康门 FAIL 判据数
  + S11@f0（dB 原值，负）。谷越深 dB 越负 → cost 越低——环按 min(cost)
  寻优语义下「越深越好」，与任务书公式 cost = −谷深幅值 + FAIL 惩罚
  等价（谷深幅值 = |S11@f0|，单列为 s11_dip_depth_db 指标）。
  fail_penalty 是无量纲算法常数非物理量（量级对齐 surrogate_loop 软
  约束罚权 P2⑥，铁律 7 不涉物理数字）。判读 FAIL 不算评估失败——
  照常产出 metrics（环按惩罚 cost 排序自然淘汰坏点），ok=False 只留给
  「无法产出指标」的发射级失败。注入 metric_extractor（Protocol 缝）
  时指标/cost 语义整体由提取器接管（缺省口径不再叠加）。
- 判读缺 S11@f0 实测值（Touchstone 缺失/f0 出跨度/skrf 环境缺失等
  UNKNOWN）→ 缺省口径无法产 cost，如实 EvalResult.from_error（#122
  不造数）；健康门 spec 上下文由同一发射器纯函数重出（单一事实源，
  与建库同参同 spec）。
- 本模块只读消费 recipe_loop_remote / edb_lane_service / edb_health_gate
  （零源文件改动）；执行体三处惰性解析走「构造器注入 > 模块属性」双缝
  （测试 fake 注入或 monkeypatch 模块属性皆可，真机走模块属性=单源）。
  不定义 __all__（公开 API 快照口径，同 edb_lane_service/edb_health_gate：
  新模块出生不触发 public_api 金快照重钉动作）。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from rfauto.service.recipe_loop_remote import EvalResult, params_fingerprint

if TYPE_CHECKING:
    from collections.abc import Callable

# 注意：本模块不定义 __all__（公开 API 快照口径，见模块 docstring）。

#: 健康 FAIL 惩罚缺省值（无量纲算法常数，非物理量）：每条 FAIL 判据给
#: cost 加一份，量级对齐 optimization/surrogate_loop 软约束罚权 P2⑥
#: （任意带 FAIL 的点在环排序中支配任意健康点）。只影响环排序不影响判读。
DEFAULT_FAIL_PENALTY = 1e3

#: 健康门判读 verdict 词汇（edb_health_gate.VERDICT_FAIL 同值；JSON 契约
#: 面，schema=edb-health-gate-v1——不引模块常量保持本模块轻导入）。
_VERDICT_FAIL = "FAIL"

#: 判读 criteria 里承载 S11@f0 / 分配腿读数的 factor 键（edb_health_gate
#: FACTOR_* 同值；evidence 键名同源：s11_db_at_f0 / s21_db_at_f0 / s31_db_at_f0）。
_FACTOR_S11_DIP = "s11_dip"
_FACTOR_S_SPLIT_WINDOW = "s_split_window"


@runtime_checkable
class HealthMetricExtractor(Protocol):
    """判读报告 → 环 metrics 的提取缝（调用方注入时接管缺省口径）。

    契约：入参 = ``check_edb_batch_health`` 判读报告 dict（schema
    edb-health-gate-v1：verdict/criteria/summary/touchstone）；返回
    metrics ``dict[str, float]``（cost 语义由提取器自定义，会话层逐值
    float 化入账本）；返回 None = 无法产出（launcher 转 EvalResult
    失败态，如实不造数）。抛异常同 launcher 异常语义（透传给会话层
    记账）。
    """

    def __call__(self, report: dict[str, Any]) -> dict[str, float] | None:
        """判读报告 → metrics（None=无法产出，不造数）。"""
        ...


def _evidence_db(factor: str, evidence_key: str,
                 report: dict[str, Any]) -> float | None:
    """判读报告 criteria 里指定 factor 的 evidence 读数（缺失/非数值→None）。"""
    for c in report.get("criteria") or []:
        if not isinstance(c, dict) or c.get("factor") != factor:
            continue
        ev = c.get("evidence")
        if isinstance(ev, dict) and ev.get(evidence_key) is not None:
            try:
                return float(ev[evidence_key])
            except (TypeError, ValueError):
                return None
    return None


def default_edb_metrics(
    report: dict[str, Any],
    *,
    fail_penalty: float = DEFAULT_FAIL_PENALTY,
) -> dict[str, float] | None:
    """缺省指标提取：判读报告单源 → cost=FAIL 惩罚+S11@f0 谷深口径。

    指标键（判读报告 evidence 单源，非 skrf 二次直读）：

    - ``s11_dip_db``：S11@f0（dB 原值，负；=判读 evidence s11_db_at_f0）；
    - ``s11_dip_depth_db``：谷深幅值（=-s11_dip_db，正，任务书"谷深"量）；
    - ``s21_db_at_f0`` / ``s31_db_at_f0``：分配腿读数（登记族
      s_split_window 判据生效时才有，缺席不造）；
    - ``health_fail_count`` / ``health_unknown_count``：判据红/未知计数；
    - ``health_verdict_fail``：verdict==FAIL 的 0/1 旗标（账本 float 化）；
    - ``cost``：``fail_penalty × health_fail_count + s11_dip_db``——
      谷越深 dB 越负 cost 越低（环 min-cost 寻优下「越深越好」），
      FAIL 惩罚按判据条数叠加。

    Returns:
        metrics dict；判读无 S11@f0 实测值（UNKNOWN/无 Touchstone）或
        summary 缺失（报告形态非法）→ None（调用方转失败态，#122 不造数）。
    """
    if not isinstance(report, dict):
        return None
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return None
    s11_db = _evidence_db(_FACTOR_S11_DIP, "s11_db_at_f0", report)
    if s11_db is None:
        return None
    raw_fail = summary.get("n_fail")
    raw_unknown = summary.get("n_unknown")
    n_fail = float(raw_fail) if raw_fail is not None else 0.0
    n_unknown = float(raw_unknown) if raw_unknown is not None else 0.0
    metrics: dict[str, float] = {
        "s11_dip_db": s11_db,
        "s11_dip_depth_db": -s11_db,
        "health_fail_count": n_fail,
        "health_unknown_count": n_unknown,
        "health_verdict_fail": 1.0 if report.get("verdict") == _VERDICT_FAIL
        else 0.0,
        "cost": fail_penalty * n_fail + s11_db,
    }
    s21_db = _evidence_db(_FACTOR_S_SPLIT_WINDOW, "s21_db_at_f0", report)
    if s21_db is not None:
        metrics["s21_db_at_f0"] = s21_db
    s31_db = _evidence_db(_FACTOR_S_SPLIT_WINDOW, "s31_db_at_f0", report)
    if s31_db is not None:
        metrics["s31_db_at_f0"] = s31_db
    return metrics


def _load_expected_freshness(out_file: Any) -> dict[str, Any] | None:
    """Touchstone 指纹 sidecar → 第 8 判据 expected 块（缺失→None=SKIP）。

    aurora_l Wave-F F2 接线：构建链（edb_lane_service.edb_solve）在
    Touchstone 写盘后落 ``<touchstone>.freshness.json`` 指纹 sidecar；
    本读取经 ``freshness_sidecar_path`` 单源派生同路径（writer/reader
    命名同源防漂移）。sidecar 在档=门启用（``{sha256, generated_at}``
    透传健康门，比对全归门）；缺失/不可读/形态非法/无可核对字段一律
    None=SKIP（判据未启用态，与 C3 增量兼容语义一致——老信封/手构
    信封零变化，verdict 与七判据时代逐位一致）。best-effort（#105）：
    IO/解析失败不抛异常不阻塞评估链。
    """
    if not out_file:
        return None
    try:
        from rfauto.service.edb_lane_service import freshness_sidecar_path

        raw = json.loads(freshness_sidecar_path(str(out_file)).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    expected: dict[str, Any] = {}
    sha = raw.get("sha256")
    if isinstance(sha, str) and sha.strip():
        expected["sha256"] = sha
    gen = raw.get("generated_at")
    if gen is not None:
        expected["generated_at"] = gen
    return expected or None


def _resolve_entry(
    injected: Callable[..., Any] | None,
    module_name: str,
    attr_name: str,
) -> Callable[..., Any]:
    """执行体解析：构造器注入优先，否则惰性取模块属性（调用时解析——
    monkeypatch 模块属性同样生效；真机路径=模块属性单源）。"""
    if injected is not None:
        return injected
    return getattr(importlib.import_module(module_name), attr_name)


class EdbLoopLauncher:
    """EDB 快车道 launcher：params → edb_build_solve → 健康门 → EvalResult。

    Args:
        template: EDB 发射模板键（edb_branchline / edb_power_divider /
            edb_coupled_line / edb_ratrace；lange 预留键在建库段即被拒）。
        params: 固定设计参数底座（stackup/sweep 等不参与寻优的键）；
            evaluate 的 params 同键覆盖（环参数窗内的设计参数逐点注入）。
        workdir: 产物根目录（.aedb/Touchstone 落点；真机按 内核立规注记 规则 0
            磁盘纪律显式给，勿落系统盘）。
        name: 账本溯源名（缺省 ``edb:<template>``；LoopLauncher 协议
            name 属性约定）。
        timeout_s: 批解/导出每段 watchdog 超时（透传 edb_build_solve）。
        fail_penalty: 缺省 cost 口径的每条 FAIL 判据惩罚（算法常数）。
        s11_dip_gate_db: 显式 S11@f0 谷深门（透传健康门；None=登记表/
            通用缺省门分派）。
        s_split_window_db: 显式 |S21|/|S31|@f0 分配窗（透传健康门；
            None=登记表分派）。
        metric_extractor: 指标提取缝（None=缺省 S11 谷深口径，见
            :func:`default_edb_metrics`）。
        build_solve_fn / emit_spec_fn / health_gate_fn: 执行体注入缝
            （测试 fake；None=真机模块属性惰性解析）。

    evaluate 失败语义（与 LocalLoopLauncher 同口径）：发射/判读链异常
    **透传**（会话层落 failed 账本）；信封级失败（建库/批解 ok=False）
    与「判读无 S11@f0 可产指标」→ ``EvalResult.from_error``；判读 FAIL
    是健康结论不是评估失败（照常产 metrics，惩罚进 cost）。
    """

    def __init__(
        self,
        template: str,
        *,
        params: dict[str, Any] | None = None,
        workdir: str | Path = "runs/edb_lane",
        name: str | None = None,
        timeout_s: float = 3600.0,
        fail_penalty: float = DEFAULT_FAIL_PENALTY,
        s11_dip_gate_db: float | None = None,
        s_split_window_db: tuple[float, float] | None = None,
        metric_extractor: HealthMetricExtractor | None = None,
        build_solve_fn: Callable[..., dict[str, Any]] | None = None,
        emit_spec_fn: Callable[..., dict[str, Any]] | None = None,
        health_gate_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.template = str(template)
        self.base_params = dict(params or {})
        self.workdir = str(workdir)
        self.name = str(name) if name is not None else f"edb:{self.template}"
        self.timeout_s = float(timeout_s)
        self.fail_penalty = float(fail_penalty)
        self.s11_dip_gate_db = (
            float(s11_dip_gate_db) if s11_dip_gate_db is not None else None)
        # s_split_window_db 是 (lo, hi) 二元组原样透传：数值校验归健康门
        # （#105 显式窗形态非法回退登记表），本层不复制校验。
        self.s_split_window_db = s_split_window_db
        self.metric_extractor = metric_extractor
        self._build_solve_fn = build_solve_fn
        self._emit_spec_fn = emit_spec_fn
        self._health_gate_fn = health_gate_fn

    # ── 执行体解析（注入 > 模块属性惰性解析） ────────────────────────────

    def _build_solve(self) -> Callable[..., dict[str, Any]]:
        return _resolve_entry(
            self._build_solve_fn, "rfauto.service.edb_lane_service",
            "edb_build_solve")

    def _emit_spec(self) -> Callable[..., dict[str, Any]]:
        return _resolve_entry(
            self._emit_spec_fn, "rfauto.service.edb_lane_service",
            "edb_emit_spec")

    def _health_gate(self) -> Callable[..., dict[str, Any]]:
        return _resolve_entry(
            self._health_gate_fn, "rfauto.service.edb_health_gate",
            "check_edb_batch_health")

    # ── 评估发射（LoopLauncher 协议） ────────────────────────────────────

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        """评估一个参数点（一次 EDB 发射：建库+批解+导出+判读）。"""
        full: dict[str, Any] = {**self.base_params, **dict(params or {})}
        # 逐点产物名：模板键+参数指纹前缀（确定性——重启重评同点写同路径，
        # 幂等回放友好；多点并发不互踩；模板键无路径分隔符，适配器 fail-fast 面）
        stem = f"{self.template}_{params_fingerprint(full)[:10]}"
        envelope = self._build_solve()(
            self.template, full, workdir=self.workdir, name=stem,
            solve=True, timeout_s=self.timeout_s, export=True)
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            if isinstance(envelope, dict):
                errors = [str(e) for e in envelope.get("errors") or
                          [f"edb build/solve 失败（ok={envelope.get('ok')}）"]]
                build = envelope.get("build")
                aedb = (build or {}).get("aedb_path") \
                    if isinstance(build, dict) else None
            else:
                errors = [
                    f"edb build/solve 返回 {type(envelope).__name__}，"
                    "契约要求信封 dict"]
                aedb = None
            return EvalResult.from_error(
                "；".join(errors),
                artifact=str(aedb) if aedb else None)

        # 判读上下文：spec 由同一发射器纯函数重出（与建库同参同 spec，
        # 单一事实源）；失败降级 spec=None（健康门相关判据如实 UNKNOWN，
        # #122），错误留痕到指标缺失时的 EvalResult error。
        spec: dict[str, Any] | None = None
        spec_note = ""
        try:
            spec_env = self._emit_spec()(self.template, full)
        except Exception as exc:  # 发射器纯函数，异常即上下文留痕（#105）
            spec_note = f"spec 重出异常: {type(exc).__name__}: {exc}"
        else:
            if isinstance(spec_env, dict) and isinstance(
                    spec_env.get("spec"), dict):
                spec = spec_env["spec"]
            elif isinstance(spec_env, dict) and not spec_env.get("ok"):
                spec_note = "；".join(
                    str(e) for e in spec_env.get("errors") or ["spec 重出失败"])

        solve_env = envelope.get("solve") or {}
        solve_view = solve_env.get("solve") or {}
        export_view = solve_env.get("export") or {}
        # 服务信封 → hfss_batch 回执契约（健康门消费面；键映射逐键对齐
        # solve_project_batch 回执字段）
        batch_result: dict[str, Any] = {
            "ok": solve_env.get("ok"),
            "rc": solve_view.get("rc"),
            "timed_out": solve_view.get("timed_out"),
            "project": solve_env.get("project"),
            "logfile": solve_view.get("logfile"),
            "artifacts": solve_view.get("artifacts"),
            "export": export_view or None,
            "elapsed_s": solve_view.get("elapsed_s"),
            "errors": solve_env.get("errors"),
        }
        # 第 8 判据 result_freshness 接线（aurora_l Wave-F F2）：从构建链
        # 指纹 sidecar 读 expected 块——缺失=expected None=SKIP（判据未
        # 启用态，不参与 verdict 聚合，增量兼容）。
        expected_freshness = _load_expected_freshness(
            export_view.get("out_file"))
        report = self._health_gate()(
            batch_result, spec=spec, template=self.template,
            s11_dip_gate_db=self.s11_dip_gate_db,
            s_split_window_db=self.s_split_window_db,
            expected_freshness=expected_freshness)
        if not isinstance(report, dict):
            return EvalResult.from_error(
                f"健康门返回 {type(report).__name__}，契约要求判读报告 dict",
                artifact=self._pick_artifact(envelope, None))

        if self.metric_extractor is not None:
            metrics = self.metric_extractor(report)
        else:
            metrics = default_edb_metrics(
                report, fail_penalty=self.fail_penalty)
        if not isinstance(metrics, dict) or not metrics:
            summary = report.get("summary")
            summary = summary if isinstance(summary, dict) else {}
            detail = (f"verdict={report.get('verdict')} "
                      f"fail={summary.get('fail_factors')} "
                      f"unknown={summary.get('unknown_factors')}")
            note = f"（{spec_note}）" if spec_note else ""
            return EvalResult.from_error(
                "指标提取未产出（缺省口径需 S11@f0 实测值——检查 "
                f"Touchstone 导出/扫频跨度/f0 声明；判读态 {detail}）{note}",
                artifact=self._pick_artifact(envelope, report))
        return EvalResult.from_metrics(
            metrics, artifact=self._pick_artifact(envelope, report))

    @staticmethod
    def _pick_artifact(
        envelope: dict[str, Any], report: dict[str, Any] | None,
    ) -> str | None:
        """产物路径自证：判读 Touchstone（判读产物）> .aedb 工程（拿不到
        判读产物时）；都拿不到如实 None，不造路径（EvalResult 契约）。"""
        if isinstance(report, dict):
            ts = report.get("touchstone")
            if ts:
                return str(ts)
        build = envelope.get("build")
        if isinstance(build, dict):
            aedb = build.get("aedb_path")
            if aedb:
                return str(aedb)
        return None
