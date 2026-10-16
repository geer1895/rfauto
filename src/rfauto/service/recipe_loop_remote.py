"""recipe-loop 远跑执行面（交接书尾程项 11 末件）。

recipe 驱动的优化环（optimization/surrogate_loop 的 SBO 环）的远程批次
发射面。既有环的求解执行与环逻辑本就分离——``run_surrogate_loop`` 的
evaluate_fn 注入缝（「真跑执行与环逻辑分离：evaluate_fn 注入（params→
metrics，失败抛异常由环记为 failure sample，不炸整环）」）——本模块在该
缝上装发射/记账/续跑执行体，环内核零改动（只读复用，未改任何既有
loop/service 文件语义；最小接线点=evaluate_fn 注入，既有设计缝）。

职责链（loop 会话 → 评估点参数 → 发射 → 结果回收 → 回填 loop 历史）：

1. ``LoopLauncher`` 协议（评估一次=一次求解发射）：
   ``evaluate(params: dict) -> EvalResult``；
   - ``LocalLoopLauncher``：本地实现——直调既有本地评估入口（params→
     metrics callable；标准来源=surrogate_optimize_service._make_evaluate_fn
     的产物：param_system.update→write_to_adapter→solve_with_self_heal→
     get_sparams→SpecEvaluator.compute_metrics，与 Optuna 直优化/SBO 环
     同一求解/指标口径；run_once 是 recipe 文件级入口，不在环评估缝上）；
   - ``RemoteLoopLauncher``：远端实现——本期接口+ssh 形态占位（evaluate
     一律 NotImplementedError，补齐路标见类 docstring；诚实占位不硬编，
     服务器修复后按清单接线）。
2. 幂等记账（断点续跑）：每次评估落 JSONL 账本（run_dir/
   recipe_loop_ledger.jsonl），记录 trial_id/params_hash/params/status/
   metrics/error/artifact_path/launcher/ts；重启后 params_hash 命中
   status=done 的记录 → 回放 metrics 不再发射（status=failed 不跳过
   ——失败点重试）。环内 LHS/虚拟寻优全链种子确定（seed 贯穿），同
   配置重启的采样点逐一命中已 done 记录 → 整环零发射完整回放。
3. ``run_recipe_loop_remote``：组装会话→注入环→回收→把发射统计回填
   loop 结果（remote_exec 键）并落 run_dir/recipe_loop_remote.json。

JSONL 账本逐行 append+flush：中断（进程死/断电）最多丢"正在发射中的一
条"，已落账记录完好；损坏行（半行写入撕裂）读账时跳过并计数
（n_ledger_corrupt），不冒充有效记录（#316 多报方向）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from rfauto.core.objectives import Objective

__all__ = [
    "LEDGER_FILENAME",
    "RESULT_FILENAME",
    "STATUS_DONE",
    "STATUS_FAILED",
    "EvalResult",
    "LocalLoopLauncher",
    "LoopLauncher",
    "LoopLedger",
    "RecipeLoopRemoteSession",
    "RemoteLoopLauncher",
    "params_fingerprint",
    "run_recipe_loop_remote",
]

LEDGER_FILENAME = "recipe_loop_ledger.jsonl"
RESULT_FILENAME = "recipe_loop_remote.json"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass
class EvalResult:
    """单次发射的评估结果（launcher → 会话的回收载体）。

    ok=True 时 metrics 必须为非空 dict（params→metrics 契约，与
    SpecEvaluator.compute_metrics 同构）；ok=False 时 error 必填。
    artifact 为本次求解的产物路径（Touchstone/判读产物等，launcher
    自证；拿不到如实 None，不造路径）。
    """

    ok: bool
    metrics: dict[str, float] | None = None
    error: str | None = None
    artifact: str | None = None

    @classmethod
    def from_metrics(
        cls, metrics: dict[str, float], *, artifact: str | None = None
    ) -> EvalResult:
        return cls(ok=True, metrics=dict(metrics), artifact=artifact)

    @classmethod
    def from_error(
        cls, error: str, *, artifact: str | None = None
    ) -> EvalResult:
        return cls(ok=False, error=str(error), artifact=artifact)


@runtime_checkable
class LoopLauncher(Protocol):
    """环评估发射器协议：评估一次 = 一次求解发射。

    实现方约定：
    - ``name: str`` 属性用于账本溯源（local / remote:<machine> / fake:…，
      会话层以 getattr(launcher, "name", 类名) 兜底）；
    - evaluate 失败可抛异常或返回 ok=False 的 EvalResult——会话层统一
      落 status=failed 账本后向环上抛（环记 failure sample，不炸整环）；
    - 幂等去重归会话层（params_hash 账本），launcher 不必自带缓存。
    """

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        """评估一个参数点（一次求解发射）。"""
        ...


class LocalLoopLauncher:
    """本地 launcher：直调既有本地评估入口（params→metrics callable）。

    evaluate_fn 标准来源=surrogate_optimize_service._make_evaluate_fn 的
    产物（与 run_optimization/SBO 环同一 solve_with_self_heal+SpecEvaluator
    求解/指标口径，对照实验同基线）；亦接受直接返回 EvalResult 的
    callable（自带产物路径的进阶入口）。launcher 自身不捕获异常——
    异常透传给会话层统一记账。
    """

    def __init__(
        self,
        evaluate_fn: Callable[[dict[str, float]], Any],
        *,
        name: str = "local",
    ) -> None:
        self.evaluate_fn = evaluate_fn
        self.name = str(name)

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        out = self.evaluate_fn(dict(params))
        if isinstance(out, EvalResult):
            return out
        if not isinstance(out, dict):
            return EvalResult.from_error(
                f"本地评估入口返回 {type(out).__name__}，契约要求 "
                "metrics dict 或 EvalResult")
        return EvalResult.from_metrics(out)


class RemoteLoopLauncher:
    """远端 launcher——本期接口占位（诚实占位不硬编：evaluate 一律抛
    NotImplementedError，绝不伪造远端评估结果）。

    服务器修复后的补齐路标（按版本对齐/工作根/发射形态纪律与 remote_service
    既有通道，接线时逐条落地）：

    1. ``infra/remote_machines.resolve_machine(machine)`` 取登记（凭据在
       gitignored 的 configs/remote_machines.local.yaml，本类不持有凭据）；
    2. 参数点+配方快照经 ``SshTransport.upload_file`` 上服务器——服务器
       侧一切临时目录/中间文件一律落服务器工作盘（注册表工作根为唯一
       中间文件根），禁写生产云盘（服务器运维约定）；
    3. 发射形态=console 可见 bat 直指（禁 schtasks 隐藏标志/wscript 静默
       ——发射形态纪律），发射后存活复核（console log 公告+CPU/ws 增长
       探针）；
    4. 求解通道按 adapter 分派：HFSS=gRPC attach（remote_service.
       hfss_remote_session_config 组装 remote_machine 键，服务器
       ``ansysedt -grpcsrv``，版本必须=本机——版本对齐纪律）；openEMS=runner
       家族（remote_oe_service 互斥预检，#261 每机互斥）；
    5. 结果（Touchstone/metrics 原料）SFTP 回拉后走本地 SpecEvaluator
       统一指标口径——数值只在确定性内核，远端不回传
       "算好的 cost"；
    6. 任务毕清理（remote_hfss_cleanup：杀 ansysedt/删 schtasks/删临时
       目录）。
    """

    REMOTE_PLACEHOLDER_MSG = (
        "RemoteLoopLauncher 未接线（本期接口占位；服务器修复后按类 "
        "docstring 路标补齐 ssh 形态发射/回收，本占位不伪造远端结果）")

    def __init__(self, machine: str = "", *, reason: str | None = None) -> None:
        self.machine = str(machine)
        self.name = f"remote:{self.machine}" if self.machine else "remote"
        self.reason = (
            str(reason) if reason is not None
            else "服务器修复后接线（ssh 形态，路标见类 docstring）")

    def evaluate(self, params: dict[str, float]) -> EvalResult:
        raise NotImplementedError(
            f"{self.REMOTE_PLACEHOLDER_MSG} machine={self.machine!r}")


def params_fingerprint(params: dict[str, float]) -> str:
    """参数点指纹：canonical JSON（排序键）的 sha256 十六进制（幂等键）。

    同一环内同一采样点逐位一致（json float 走 repr 精度）；跨环相近点
    本就不是同一点，不承诺指纹相等。
    """
    canonical = json.dumps(dict(params), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LoopLedger:
    """评估账本（JSONL，逐行 append+flush，断点续跑的幂等凭据）。

    行 schema：trial_id / params_hash / params / status("done"|"failed")
    / metrics / error / artifact_path / launcher / ts。params_hash 是幂等
    键；trial_id=hash 前缀派生的稳定 id（跨重启不变，人读用）。
    """

    def __init__(self, path: str | Path) -> None:
        # 路径入参第一行 Path() 收敛（#140）
        self.path = Path(path)
        self._records: list[dict[str, Any]] = []
        self.n_corrupt = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    # 半行写入撕裂（中断）：跳过并计数，不冒充有效记录
                    self.n_corrupt += 1
                    continue
                if isinstance(rec, dict):
                    self._records.append(rec)

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        rec = dict(record)
        rec.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        self._records.append(rec)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()
        return rec

    def completed_map(self) -> dict[str, dict[str, Any]]:
        """params_hash → 最近一条 status=done 记录（后写覆盖先写）。

        failed 记录不进此表——失败点重启后重试而非跳过（任务书口径：
        只跳过"已完成项"）。
        """
        out: dict[str, dict[str, Any]] = {}
        for rec in self._records:
            h = rec.get("params_hash")
            if rec.get("status") == STATUS_DONE and h:
                out[str(h)] = rec
        return out

    def count_status(self, status: str) -> int:
        return sum(1 for r in self._records if r.get("status") == status)


class RecipeLoopRemoteSession:
    """loop 会话：环评估入口的发射/记账/回放执行体。

    ``evaluate`` 即 run_surrogate_loop 的 evaluate_fn 缝（params→metrics，
    失败抛异常由环记 failure sample，不炸整环）；会话层在缝前后做幂等
    账本：

    - params_hash 命中 status=done → 回放账本 metrics（零发射）；
    - 未命中 → launcher 发射一次（评估一次=一次求解发射）并落账；
    - launcher 异常 / ok=False / metrics 契约违约 → 落 status=failed
      账本后抛 RuntimeError（失败如实记账；重启后失败点重试）。
    """

    def __init__(
        self,
        run_dir: str | Path,
        launcher: Any,
        *,
        ledger_name: str = LEDGER_FILENAME,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.launcher = launcher
        self.launcher_name = str(
            getattr(launcher, "name", type(launcher).__name__))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = LoopLedger(self.run_dir / ledger_name)
        self._completed = self.ledger.completed_map()
        # 同会话幂等口径与跨重启一致：done 记账即时并入缓存（否则同一
        # 参数点在会话内第二次评估会重新发射真求解，与"params_hash 命中
        # status=done → 回放不再发射"的账本回放语义相悖）
        self.n_launched = 0
        self.n_replayed = 0
        self.n_failed = 0

    def trial_id(self, params_hash: str) -> str:
        """稳定 trial id（hash 前缀派生，跨重启不变）。"""
        return f"tl-{params_hash[:12]}"

    def _evaluate_one(
        self, params: dict[str, float]
    ) -> tuple[str, dict[str, float] | None, str | None]:
        """单点评估：返回 (action, metrics, error)。

        action ∈ {"replayed", "launched", "failed"}；failed 时 metrics 为
        None 且 error 已落账本。
        """
        p = dict(params)
        h = params_fingerprint(p)
        done = self._completed.get(h)
        if done is not None and isinstance(done.get("metrics"), dict):
            self.n_replayed += 1
            return "replayed", dict(done["metrics"]), None

        tid = self.trial_id(h)
        self.n_launched += 1
        try:
            res = self.launcher.evaluate(p)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._record(tid, h, p, STATUS_FAILED, None, error, None)
            return "failed", None, error

        if not isinstance(res, EvalResult):
            error = (f"launcher 返回 {type(res).__name__}，契约要求 "
                     "EvalResult")
            self._record(tid, h, p, STATUS_FAILED, None, error, None)
            return "failed", None, error
        if not res.ok:
            error = res.error or "launcher 报告评估失败（无 error 明细）"
            self._record(tid, h, p, STATUS_FAILED, None, error, res.artifact)
            return "failed", None, error
        if not isinstance(res.metrics, dict) or not res.metrics:
            error = "launcher 报告成功但 metrics 非空 dict 契约违约"
            self._record(tid, h, p, STATUS_FAILED, None, error, res.artifact)
            return "failed", None, error
        try:
            metrics = {str(k): float(v) for k, v in res.metrics.items()}
        except (TypeError, ValueError) as exc:
            error = f"metrics 含非数值，无法记账: {exc}"
            self._record(tid, h, p, STATUS_FAILED, None, error, res.artifact)
            return "failed", None, error
        self._record(tid, h, p, STATUS_DONE, metrics, None, res.artifact)
        # done 即时并入幂等缓存（同会话内同参数点第二次评估=回放，与
        # 重启回放同口径；failed 不入表——失败点会话内同样重试）
        self._completed[h] = self.ledger.records[-1]
        return "launched", metrics, None

    def _record(
        self,
        tid: str,
        h: str,
        params: dict[str, float],
        status: str,
        metrics: dict[str, float] | None,
        error: str | None,
        artifact: str | None,
    ) -> None:
        if status == STATUS_FAILED:
            self.n_failed += 1
        self.ledger.append({
            "trial_id": tid,
            "params_hash": h,
            "params": params,
            "status": status,
            "metrics": metrics,
            "error": error,
            "artifact_path": artifact,
            "launcher": self.launcher_name,
        })

    def evaluate(self, params: dict[str, float]) -> dict[str, float]:
        """环注入缝（run_surrogate_loop 的 evaluate_fn 同契约）。

        失败抛 RuntimeError——由环记 failure sample，不炸整环。
        """
        action, metrics, error = self._evaluate_one(params)
        if action == "failed":
            raise RuntimeError(error)
        assert metrics is not None  # launched/replayed 恒带 metrics
        return metrics

    def evaluate_batch(
        self, points: list[dict[str, float]]
    ) -> list[dict[str, Any]]:
        """批量发射（评估点参数 → 发射 → 结果回收）；逐点独立，失败不炸批。"""
        outcomes: list[dict[str, Any]] = []
        for pt in points:
            p = dict(pt)
            action, metrics, error = self._evaluate_one(p)
            row: dict[str, Any] = {"params": p, "action": action}
            if metrics is not None:
                row["metrics"] = metrics
            if error is not None:
                row["error"] = error
            outcomes.append(row)
        return outcomes

    @property
    def stats(self) -> dict[str, Any]:
        """发射统计（回填 loop 结果 remote_exec 键的口径）。"""
        return {
            "launcher": self.launcher_name,
            "ledger_path": str(self.ledger.path),
            "n_launched": self.n_launched,
            "n_replayed": self.n_replayed,
            "n_failed": self.n_failed,
            "n_ledger_done": self.ledger.count_status(STATUS_DONE),
            "n_ledger_failed": self.ledger.count_status(STATUS_FAILED),
            "n_ledger_corrupt": self.ledger.n_corrupt,
        }


def run_recipe_loop_remote(
    bounds: dict[str, tuple[float, float]],
    objectives: list[Objective],
    launcher: LoopLauncher,
    run_dir: str | Path,
    *,
    ledger_name: str = LEDGER_FILENAME,
    **loop_kwargs: Any,
) -> dict[str, Any]:
    """recipe 环远跑执行体：会话 → 注入环 → 回收 → 回填 loop 历史。

    bounds/objectives 与 run_surrogate_loop 同契约（服务层按配方解析，
    装配参照 surrogate_optimize_service.surrogate_optimize——本函数不复制
    装配，单一事实源）；launcher 决定发射通道（LocalLoopLauncher 直调
    本地评估入口 / RemoteLoopLauncher 占位）。环内核零改动：evaluate_fn
    注入缝是既有设计；发射统计以 ``remote_exec`` 键回填环结果，并把回填
    后结果落 run_dir/recipe_loop_remote.json（best-effort，#105）。

    空 bounds/objectives：环按既有契约返回 ok=False 错误信封——零发射、
    账本零记录（本函数不前置复制环的校验）。
    """
    run_dir_p = Path(run_dir)
    session = RecipeLoopRemoteSession(
        run_dir_p, launcher, ledger_name=ledger_name)
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    result = run_surrogate_loop(
        bounds, objectives, session.evaluate, **loop_kwargs)
    result["remote_exec"] = session.stats
    # 结果落盘 best-effort（#105）：失败时内存中的回填结果不受影响
    with contextlib.suppress(OSError):
        (run_dir_p / RESULT_FILENAME).write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
    return result
