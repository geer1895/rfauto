"""aedt_migrate 批量迁移通道 service 决策树（aurora_r AM-S1，2026-11-10）。

把合作者遗留的老版本 .aedt 工程批量、可审计、不凑绿地迁移到 AEDT 2025 R1
（设计稿：aedt_migrate_design_handoff.md §1 五阶段决策树）。本模块是
**纯离线编排面**：决策树核是纯函数 + 注入式阶段执行器（executor），零
AEDT 依赖；真机执行器（2025 R1 直开/体检/-BatchSave 桥接）归 AM-S2/S3
adapters 席，本席只定义**执行器契约**与全路由决策语义。

五阶段（设计稿 §1，每工程独立流转，产物=迁移报告）::

    S0 盘点+备份规划（本地纯文件，零 AEDT）
       sha256 原件 → backup/ 路径规划（**纯路径计算，不执行拷贝**——
       拷贝归 S2 实机席）→ 尽力读取工程版本指纹（读不到如实 unavailable）
    S1 直开尝试（2025 R1，-ng；executor 注入三态 success/cutoff/error）
       success → S2；cutoff → S4；其他失败 → FAILED_OPEN（如实终态）
    S2 体检（executor 注入：checks 存在性 + geometry_error 旗标）
       全过 → S3；geometry 类错误 → S5；其他 → FAILED_HEALTH 附消息原文
    S3 新旧结果对比（tolerance 按族预声明入配置，不许事后改门）
       达标 → MIGRATED_*_PASS；超差 → MIGRATED_DIRECT_FAIL_COMPARISON；
       无基线 → NO_BASELINE（三者皆诚实终态，不伪造不重试）
    S4 桥接（2023 R2，可选依赖）
       配置 bridge_2023R2: null（未装桥接机）或 bridge executor 未注入
       → BLOCKED_NO_BRIDGE_HOST（**前提不满足≠失败，不误报 FAIL**）；
       bridge 成功 → 桥接产物重入 S1/S2/S3（stage_reached 记 S1b/S2b/S3b 链），
       重入后仍拒开/失败 → FAILED_BRIDGE（桥接链失败，如实）
    S5 抢救（几何坏）
       rescue executor 产出重建清单 → NEEDS_CAD_REEXPORT；
       重建本身一期 NEEDS_MANUAL（Discovery 修复=人工，报告给指引）

verdict 枚举（设计稿七值 → 字面 9 枚举；铁律 #122：FAILED_*/NO_BASELINE/
BLOCKED_* 每个都是诚实终态，编排层零重试零凑绿）::

    MIGRATED_DIRECT_PASS / MIGRATED_DIRECT_FAIL_COMPARISON /
    MIGRATED_VIA_BRIDGE_PASS / NEEDS_CAD_REEXPORT / NO_BASELINE /
    FAILED_OPEN | FAILED_HEALTH | FAILED_BRIDGE /
    BLOCKED_NO_BRIDGE_HOST

报告 schema（v1， mandated 键集）::

    {schema, project, project_path, source_sha256, backup_path,
     source_version_best_effort, stage_reached, verdict, checks,
     messages, engine_identity, comparison|null, rescue|null,
     timestamps}

engine_identity 段消费既有 infra/run_store.build_engine_identity（AX-3
单源；executor 自报 ansysedt_version → canonical version 键，machine
best-effort hostname）——Token Zhang 调研 AX-3 一石二鸟。

数值只在确定性内核（铁律 7）：对比 deltas 由 compare executor（S2 实装
确定性判读核）产出，本模块零数值语义，只做"预声明 tolerance 消费 + 阈值
比较 + verdict 路由"。对比 fail-closed：executor 声明有基线但零 deltas →
按超差处理（诚实红，不凑绿）。

原 .aedt 只读铁律：全链无任何写原件路径——S0 只算 sha256/规划备份路径/
读文件头指纹（只读）；一切产物（inventory/报告/备份）落 work_root。

幂等：报告落 ``work_root/reports/<stem>__<sha8>.json``（sha8=source_sha256
前 8 位，同名工程防撞+内容变更即新身份）；批量重跑跳过 verdict∈MIGRATED_*
（迁移已完成——含 FAIL_COMPARISON：同门不重跑赌不同数字，正是 #122 反
"重试凑绿"语义）；FAILED_*/BLOCKED_*/NO_BASELINE/NEEDS_CAD_REEXPORT
允许重跑（桥接机装好后 BLOCKED 应能转真，如实再记录）。

配置（只写解析器+缺省值，不改 configs/settings.local.yaml 本体）::

    aedt_migrate:
      bridge_2023R2: null        # null=桥接机未装 → BLOCKED；mapping=已装
      tolerances: {default: 0.05, <族>: <rel_tol>}
      work_root: runs/aedt_migrate

executor 契约（callables，签名 ``(project_path: Path, context: dict) -> dict``，
context 携带 work_root/inventory_entry/config）::

    direct_open -> {outcome: success|cutoff|error, messages: [...],
                    engine_identity?: {ansysedt_version, machine},
                    migrated_path?: str}
    health      -> {ok: bool, geometry_error: bool,
                    checks: {materials|boundaries|mesh|setups|optimetrics: bool},
                    messages, engine_identity?}
    compare     -> {has_baseline: bool, baseline_kind?: str, family?: str,
                    deltas: {metric: 相对偏差}, messages}
    bridge      -> {outcome: success|error, bridge_artifact?: str(path),
                    messages, engine_identity?}
    rescue      -> {rebuild_list: [str, ...], messages}

executor 内部抛异常 = 基础设施故障（非迁移结局）——不折算成 verdict 伪造
结局，直接向批量层传播；migrate_batch 捕获逐工程记 error 行不炸整批。

CLI/MCP 挂账处方（归 AM-S4，本席不接线）::

    CLI（cli/domains/aedt_migrate.py）: ``rfauto aedt-migrate run/status/report``
    —— run 消费 migrate_batch（--json 棘轮 #W2-C、路径参数 str 注解 #269）、
    status/report 消费 read_migration_report；信封走
    service.envelope ok_envelope/error_envelope 构造器（AU-2 单源）。
    MCP（mcp_tools/）：aedt_migrate_run / aedt_migrate_report 两薄壳，
    工具一致性五钉（df6②清单）+ 注册序/public_api 金快照重生成归 S4 同笔。
    接线五钉自证：merge_preflight 前移（AGENTS 硬限制 1 门口径 v2 附则）。
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# ---------------------------------------------------------------------------
# schema / verdict / 契约常量（单源）
# ---------------------------------------------------------------------------

#: 迁移报告 schema 版本（形状变更升位）
REPORT_SCHEMA = "rfauto-aedt-migrate-report/1"
#: Stage 0 盘点文件 schema 版本
INVENTORY_SCHEMA = "rfauto-aedt-migrate-inventory/1"

VERDICT_MIGRATED_DIRECT_PASS = "MIGRATED_DIRECT_PASS"
VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON = "MIGRATED_DIRECT_FAIL_COMPARISON"
VERDICT_MIGRATED_VIA_BRIDGE_PASS = "MIGRATED_VIA_BRIDGE_PASS"
VERDICT_NEEDS_CAD_REEXPORT = "NEEDS_CAD_REEXPORT"
VERDICT_NO_BASELINE = "NO_BASELINE"
VERDICT_FAILED_OPEN = "FAILED_OPEN"
VERDICT_FAILED_HEALTH = "FAILED_HEALTH"
VERDICT_FAILED_BRIDGE = "FAILED_BRIDGE"
VERDICT_BLOCKED_NO_BRIDGE_HOST = "BLOCKED_NO_BRIDGE_HOST"

#: verdict 全集（设计稿 §1 七值 → 字面 9 枚举；新值=显式评审动作）
MIGRATION_VERDICTS: tuple[str, ...] = (
    VERDICT_MIGRATED_DIRECT_PASS,
    VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON,
    VERDICT_MIGRATED_VIA_BRIDGE_PASS,
    VERDICT_NEEDS_CAD_REEXPORT,
    VERDICT_NO_BASELINE,
    VERDICT_FAILED_OPEN,
    VERDICT_FAILED_HEALTH,
    VERDICT_FAILED_BRIDGE,
    VERDICT_BLOCKED_NO_BRIDGE_HOST,
)

#: 幂等跳过前缀（verdict 以此开头 = 迁移已完成，批量重跑跳过；#122：
#: FAIL_COMPARISON 也在跳过集——同门不重跑赌不同数字）
MIGRATED_VERDICT_PREFIX = "MIGRATED_"

#: 体检存在性检查键（设计稿 §0-4 迁移后必做清单；schema mandated）
CHECK_KEYS: tuple[str, ...] = ("materials", "boundaries", "mesh", "setups", "optimetrics")

#: 执行器契约键（direct_open/health/compare 必注入；bridge/rescue 可选，
#: 缺位走各自诚实语义 BLOCKED / NEEDS_CAD_REEXPORT+空清单）
EXECUTOR_KEYS: tuple[str, ...] = ("direct_open", "health", "compare", "bridge", "rescue")
_REQUIRED_EXECUTORS: tuple[str, ...] = ("direct_open", "health", "compare")

#: 配置缺省值（configs/settings.local.yaml ``aedt_migrate:`` 块可逐键覆盖）
AEDT_MIGRATE_CONFIG_DEFAULTS: dict[str, Any] = {
    "bridge_2023R2": None,
    "tolerances": {"default": 0.05},
    "work_root": "runs/aedt_migrate",
}

#: 配置文件缺省路径（相对 cwd；只读，不改本体——本席铁律）
DEFAULT_CONFIG_YAML = Path("configs") / "settings.local.yaml"

#: 配置块键名
CONFIG_BLOCK_KEY = "aedt_migrate"

#: 版本指纹尽力扫描字节数（.aedt 文件头；只读）
_FINGERPRINT_MAX_BYTES = 65536

#: cutoff 官方口径短语（Jim Sherman/Ansys 支持转述；执行器可复用本分类器，
#: 单源防漂移——匹配不到按普通 error 保守处理）
_CUTOFF_PHRASES: tuple[str, ...] = (
    "legacy project files can no longer be opened",
    "please use release",
)

#: 版本指纹尽力正则（AEVersion 优先；\b 防 AEVersion 误命中 Version 档）
_VERSION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AEVersion\D{0,20}?(\d{4}\.\d)"), "AEVersion"),
    (re.compile(r"\bVersion\D{0,5}?['\"]?(\d{4}\.\d)"), "Version"),
)

StageExecutor = Callable[[Path, dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# 配置解析（只写解析器+缺省值，不改 configs/settings.local.yaml 本体）
# ---------------------------------------------------------------------------

def parse_aedt_migrate_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """``aedt_migrate`` 配置块归一解析（缺省合并+类型守卫，响亮报错）。

    Args:
        raw: 配置块 dict（可缺键/None=全缺省）；键超集忽略未知键（前向
            兼容），已知键类型不对 → ``ValueError``（配置错误要响，不静默
            降级——静默降级会把 BLOCKED/FAIL 判错门）。

    Returns:
        归一 dict：``{bridge_2023R2: None|Mapping, tolerances: {族: float},
        work_root: str}``。
    """
    cfg = dict(AEDT_MIGRATE_CONFIG_DEFAULTS)
    cfg["tolerances"] = dict(AEDT_MIGRATE_CONFIG_DEFAULTS["tolerances"])
    if raw is None:
        return cfg
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"{CONFIG_BLOCK_KEY} 配置块必须是 mapping，得到 {type(raw).__name__}")
    bridge = raw.get("bridge_2023R2")
    if bridge is not None and not isinstance(bridge, Mapping):
        raise ValueError(
            "aedt_migrate.bridge_2023R2 只接受 null（桥接机未装 → BLOCKED）"
            "或 mapping（桥接机描述），得到 "
            f"{type(bridge).__name__}")
    if bridge is not None:
        cfg["bridge_2023R2"] = dict(bridge)
    tolerances = raw.get("tolerances")
    if tolerances is not None:
        if not isinstance(tolerances, Mapping) or not tolerances:
            raise ValueError("aedt_migrate.tolerances 必须是非空 mapping")
        parsed_tol: dict[str, float] = {}
        for family, tol in tolerances.items():
            try:
                tol_f = float(tol)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"tolerances[{family!r}] 不是数值：{tol!r}") from exc
            if not tol_f > 0:
                raise ValueError(
                    f"tolerances[{family!r}] 必须 > 0（预声明门不许 0/负）")
            parsed_tol[str(family)] = tol_f
        # default 档恒在场（族回退的兜底锚）：用户只声明部分族时不至于
        # 回退落空——兜底值仍取缺省单源，非事后改门
        parsed_tol.setdefault(
            "default", float(AEDT_MIGRATE_CONFIG_DEFAULTS["tolerances"]["default"]))
        cfg["tolerances"] = parsed_tol
    work_root = raw.get("work_root")
    if work_root is not None:
        if not isinstance(work_root, (str, Path)):
            raise ValueError(
                f"aedt_migrate.work_root 必须是 str/Path，得到 {type(work_root).__name__}")
        cfg["work_root"] = str(work_root)
    return cfg


def load_aedt_migrate_config(
    yaml_path: str | Path | None = None,
) -> dict[str, Any]:
    """读 ``configs/settings.local.yaml`` 的 ``aedt_migrate`` 块 → 归一配置。

    缺文件/缺块 → 全缺省（BLOCKED 语义缺省关，设计稿 Stage 4 前提）；
    yaml 语法坏/块非 mapping → ``ValueError`` 响亮。只读，不改本体。
    """
    path = Path(yaml_path) if yaml_path is not None else Path(DEFAULT_CONFIG_YAML)
    if not path.is_file():
        return parse_aedt_migrate_config(None)
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"配置文件 YAML 解析失败：{path}（{exc}）") from exc
    if not isinstance(data, Mapping):
        return parse_aedt_migrate_config(None)
    return parse_aedt_migrate_config(data.get(CONFIG_BLOCK_KEY))


# ---------------------------------------------------------------------------
# S0 纯文件面：sha256 / 备份路径规划 / 版本指纹 / 工程收集
# ---------------------------------------------------------------------------

def classify_open_error(message: str) -> str:
    """直开报错分类（cutoff 硬拒 vs 其他失败）——S2 执行器共用单源。

    官方口径短语（大小写不敏感）命中 → ``"cutoff"``；其余 → ``"error"``。
    保守策略：匹配不到不猜 cutoff（cutoff 触发桥接链，误判会把可直修的
    失败误送 BLOCKED/桥接）。
    """
    lowered = str(message).lower()
    if any(phrase in lowered for phrase in _CUTOFF_PHRASES):
        return "cutoff"
    return "error"


def sha256_file(path: str | Path) -> str:
    """流式 sha256（只读）。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_backup_path(
    project_path: str | Path, work_root: str | Path, sha256_hex: str
) -> Path:
    """备份路径**纯规划**（不执行拷贝——拷贝归 S2 实机席，本席纯离线）。

    形态 ``<work_root>/backup/<stem>__<sha8>.aedt``：sha8 锚定内容身份，
    同名工程防撞、原件事后可校验未变。返回值恒 ≠ 原件路径（只读铁律）。
    """
    project_path = Path(project_path)
    return Path(work_root) / "backup" / f"{project_path.stem}__{sha256_hex[:8]}.aedt"


def read_source_version_fingerprint(
    path: str | Path, *, max_bytes: int = _FINGERPRINT_MAX_BYTES
) -> dict[str, Any]:
    """尽力读取工程版本指纹（文件头扫描，只读；读不到如实降级不伪造）。

    Returns:
        ``{"source_version": str|None, "fingerprint_source": str}``——
        fingerprint_source ∈ ``header:AEVersion|header:Version|unavailable|
        unreadable``。真实 .aedt 头格式的语料级核对归 S2/S5（真语料），
        本 helper 只承诺"读得到就报、读不到如实"。
    """
    p = Path(path)
    try:
        with p.open("rb") as fh:
            head = fh.read(max_bytes).decode("utf-8", errors="ignore")
    except OSError:
        return {"source_version": None, "fingerprint_source": "unreadable"}
    for pattern, name in _VERSION_PATTERNS:
        found = pattern.search(head)
        if found:
            return {
                "source_version": found.group(1),
                "fingerprint_source": f"header:{name}",
            }
    return {"source_version": None, "fingerprint_source": "unavailable"}


def build_project_inventory_entry(
    project_path: str | Path, work_root: str | Path
) -> dict[str, Any]:
    """S0 单工程盘点（sha256+备份路径规划+版本指纹尽力读；纯文件零 AEDT）。"""
    p = Path(project_path)
    digest = sha256_file(p)
    fingerprint = read_source_version_fingerprint(p)
    return {
        "project": p.stem,
        "path": str(p),
        "size_bytes": p.stat().st_size,
        "sha256": digest,
        "sha8": digest[:8],
        "backup_path": str(plan_backup_path(p, work_root, digest)),
        "source_version": fingerprint["source_version"],
        "fingerprint_source": fingerprint["fingerprint_source"],
    }


def collect_aedt_projects(
    inputs: str | Path | Iterable[str | Path],
) -> list[Path]:
    """``--input <file|dir>`` 收集 *.aedt（目录递归；确定性排序）。

    文件入参必须 .aedt 后缀；不存在/无匹配 → ``ValueError``（调用方错误
    要响，不静默空跑）。
    """
    items = [inputs] if isinstance(inputs, (str, Path)) else list(inputs)
    if not items:
        raise ValueError("inputs 为空——给 .aedt 文件或目录")
    found: list[Path] = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            found.extend(sorted(p.rglob("*.aedt")))
        elif p.is_file():
            if p.suffix.lower() != ".aedt":
                raise ValueError(f"输入文件不是 .aedt：{p}")
            found.append(p)
        else:
            raise ValueError(f"输入不存在：{p}")
    if not found:
        raise ValueError(f"输入下未找到任何 *.aedt：{items}")
    # 同一文件可能经多条输入重复命中——按解析后绝对路径去重，保序
    seen: set[str] = set()
    unique: list[Path] = []
    for p in found:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def is_migrated_verdict(verdict: str) -> bool:
    """verdict 是否属"迁移已完成"幂等跳过集（MIGRATED_* 前缀族）。"""
    return str(verdict).startswith(MIGRATED_VERDICT_PREFIX)


def read_migration_report(report_path: str | Path) -> dict[str, Any]:
    """读迁移报告 JSON（CLI status/report 薄壳消费；坏文件响亮抛 OSError/
    ValueError，调用方决定呈现）。"""
    return json.loads(Path(report_path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 归一 helpers（checks / engine_identity / 时间戳）
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _best_effort_hostname() -> str:
    try:
        return socket.gethostname() or "unknown"
    except Exception:  # pragma: no cover - 观测面兜底（#105）
        return "unknown"


def _normalize_checks(raw: Any) -> dict[str, bool | None]:
    """体检结果 → CHECK_KEYS 键集归一（bool|None；缺失/None=未知如实，
    多余键丢弃——报告 checks 键集恒定，schema 可校验）。"""
    source = raw if isinstance(raw, Mapping) else {}
    out: dict[str, bool | None] = {}
    for key in CHECK_KEYS:
        value = source.get(key)
        out[key] = bool(value) if isinstance(value, bool) else None
    return out


def _absorb_engine_identity(
    sink: dict[str, Any], executor_result: Mapping[str, Any]
) -> None:
    """executor 自报 engine_identity 首见键吸收（先到先得，不覆盖）。"""
    raw = executor_result.get("engine_identity")
    if not isinstance(raw, Mapping):
        return
    for key, value in raw.items():
        if value is not None and key not in sink:
            sink[key] = value


def _build_engine_identity(raw: Mapping[str, Any]) -> dict[str, Any]:
    """executor 自报 → AX-3 canonical（infra/run_store.build_engine_identity
    单源消费；ansysedt_version → version 键映射；machine 缺省 best-effort
    hostname；全缺 → unknown 如实，不伪造）。惰性导入保持 service import
    面最小（infra 在 service 之下）。"""
    from rfauto.infra.run_store import build_engine_identity

    info: dict[str, Any] = {"engine": "aedt"}
    version = raw.get("ansysedt_version") or raw.get("version")
    if version:
        info["version"] = version
    info["machine"] = raw.get("machine") or _best_effort_hostname()
    return build_engine_identity(info)


def _executor_context(
    project_path: Path, config: Mapping[str, Any], work_root: Path,
    inventory_entry: Mapping[str, Any],
) -> dict[str, Any]:
    """执行器注入 context（JSON 形态，路径 str 化）。"""
    return {
        "project_path": str(project_path),
        "work_root": str(work_root),
        "config": dict(config),
        "inventory_entry": dict(inventory_entry),
    }


def _absorb_messages(messages: list[str], executor_result: Mapping[str, Any]) -> None:
    """executor 消息原文吸收（str=单条语义；list/tuple 逐条；其余忽略）。"""
    raw = executor_result.get("messages")
    if raw is None or isinstance(raw, Mapping):
        return
    if isinstance(raw, str):
        messages.append(raw)
    elif isinstance(raw, Iterable):
        messages.extend(str(m) for m in raw)


# ---------------------------------------------------------------------------
# 决策树核（纯编排，executor 注入；零 AEDT 依赖）
# ---------------------------------------------------------------------------

def migrate_project(
    project_path: str | Path,
    config: Mapping[str, Any] | None,
    executors: Mapping[str, StageExecutor],
    *,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    """单工程五阶段决策树 → 迁移报告 dict（schema 见模块 docstring）。

    Args:
        project_path: 原 .aedt 路径（**只读铁律：全链零写此路径**）。
        config: 配置 dict（原块或已归一均可，内部再归一）；None=全缺省。
        executors: 阶段执行器 mapping——``direct_open/health/compare`` 必
            注入（缺 → ``ValueError``，能力缺位要响，不伪造结局）；
            ``bridge/rescue`` 可选（缺位走 BLOCKED / 空重建清单诚实语义）。
        work_root: 产物根（缺省取 config work_root）。

    Raises:
        FileNotFoundError: 原件不在场。
        ValueError: 必需 executor 缺位 / 配置非法。
        Exception: executor 内部异常原样传播（基础设施故障不折算 verdict），
            批量层逐工程捕获记 error 行。
    """
    project_path = Path(project_path)  # #140 PathLike 收敛
    if not project_path.is_file():
        raise FileNotFoundError(f"原 .aedt 不存在：{project_path}")
    cfg = parse_aedt_migrate_config(dict(config) if config is not None else None)
    for name in _REQUIRED_EXECUTORS:
        if not callable(executors.get(name)):
            raise ValueError(f"必需 executor 未注入或不可调用：{name}")

    root = Path(work_root) if work_root is not None else Path(cfg["work_root"])

    chain: list[str] = ["S0"]
    messages: list[str] = []
    stage_times: dict[str, str] = {}
    engine_raw: dict[str, Any] = {}
    checks = _normalize_checks(None)
    comparison: dict[str, Any] | None = None
    rescue_section: dict[str, Any] | None = None

    def _stamp(stage: str) -> None:
        stage_times[stage] = _now_utc()

    # ---- Stage 0 盘点+备份规划（纯文件，零 AEDT，零写原件路径） ----
    entry = build_project_inventory_entry(project_path, root)
    _stamp("S0")

    current_target = project_path
    context = _executor_context(current_target, cfg, root, entry)
    via_bridge = False

    # ---- Stage 1 直开尝试（executor 三态：success / cutoff / error） ----
    chain.append("S1")
    _stamp("S1")
    open_res = executors["direct_open"](current_target, context)
    if not isinstance(open_res, Mapping):
        open_res = {}
    _absorb_messages(messages, open_res)
    _absorb_engine_identity(engine_raw, open_res)
    outcome = str(open_res.get("outcome", "error"))

    if outcome == "cutoff":
        # ---- Stage 4 桥接（可选依赖；null/缺 executor → BLOCKED 非 FAIL） ----
        chain.append("S4")
        _stamp("S4")
        bridge_cfg = cfg["bridge_2023R2"]
        bridge_exec = executors.get("bridge")
        if bridge_cfg is None:
            messages.append(
                "bridge_2023R2=null（桥接机未配置）——Stage 4 前提不满足，"
                "如实 BLOCKED 非 FAIL（设计稿 Stage 4）")
            return _finalize_report(
                entry, project_path, chain, VERDICT_BLOCKED_NO_BRIDGE_HOST,
                checks, messages, engine_raw, comparison, rescue_section,
                stage_times, root)
        if not callable(bridge_exec):
            messages.append(
                "bridge executor 未注入——桥接能力缺位，如实 BLOCKED 非 FAIL")
            return _finalize_report(
                entry, project_path, chain, VERDICT_BLOCKED_NO_BRIDGE_HOST,
                checks, messages, engine_raw, comparison, rescue_section,
                stage_times, root)
        bridge_res = bridge_exec(current_target, context)
        if not isinstance(bridge_res, Mapping):
            bridge_res = {}
        _absorb_messages(messages, bridge_res)
        _absorb_engine_identity(engine_raw, bridge_res)
        if str(bridge_res.get("outcome")) != "success":
            messages.append("桥接执行器未报 success——桥接链失败，如实 FAILED_BRIDGE")
            return _finalize_report(
                entry, project_path, chain, VERDICT_FAILED_BRIDGE,
                checks, messages, engine_raw, comparison, rescue_section,
                stage_times, root)
        artifact = bridge_res.get("bridge_artifact")
        if not artifact:
            messages.append(
                "桥接执行器 success 但缺 bridge_artifact（契约违约）——"
                "重开目标不可知，如实 FAILED_BRIDGE")
            return _finalize_report(
                entry, project_path, chain, VERDICT_FAILED_BRIDGE,
                checks, messages, engine_raw, comparison, rescue_section,
                stage_times, root)
        # 桥接成功 → 桥接产物重入 S1/S2/S3（stage_reached 记 S*b 链）
        current_target = Path(artifact)
        context = _executor_context(current_target, cfg, root, entry)
        via_bridge = True
        chain.append("S1b")
        _stamp("S1b")
        open_res = executors["direct_open"](current_target, context)
        if not isinstance(open_res, Mapping):
            open_res = {}
        _absorb_messages(messages, open_res)
        _absorb_engine_identity(engine_raw, open_res)
        outcome = str(open_res.get("outcome", "error"))
        if outcome != "success":
            messages.append(
                f"桥接产物重入直开仍失败（outcome={outcome}）——"
                "桥接未达成可直开形态，如实 FAILED_BRIDGE")
            return _finalize_report(
                entry, project_path, chain, VERDICT_FAILED_BRIDGE,
                checks, messages, engine_raw, comparison, rescue_section,
                stage_times, root)
    elif outcome != "success":
        # ---- 直开失败（非 cutoff）→ FAILED_OPEN 如实终态 ----
        messages.append(
            f"直开失败且未命中 cutoff 口径（outcome={outcome}）——如实终态不重试")
        return _finalize_report(
            entry, project_path, chain, VERDICT_FAILED_OPEN,
            checks, messages, engine_raw, comparison, rescue_section,
            stage_times, root)

    # ---- Stage 2 体检（executor 注入；geometry 错 → S5，其他失败 → FAILED_HEALTH） ----
    chain.append("S2b" if via_bridge else "S2")
    _stamp(chain[-1])
    health_res = executors["health"](current_target, context)
    if not isinstance(health_res, Mapping):
        health_res = {}
    _absorb_messages(messages, health_res)
    _absorb_engine_identity(engine_raw, health_res)
    checks = _normalize_checks(health_res.get("checks"))

    if health_res.get("geometry_error"):
        # ---- Stage 5 抢救（几何坏；重建一期 NEEDS_MANUAL） ----
        chain.append("S5")
        _stamp("S5")
        rescue_exec = executors.get("rescue")
        rebuild_list: list[str] = []
        if callable(rescue_exec):
            rescue_res = rescue_exec(current_target, context)
            if isinstance(rescue_res, Mapping):
                _absorb_messages(messages, rescue_res)
                rebuild_list = [
                    str(item) for item in (rescue_res.get("rebuild_list") or [])]
        else:
            messages.append(
                "rescue executor 未注入——重建清单空；NEEDS_CAD_REEXPORT 如实，"
                "重建一期 NEEDS_MANUAL（Discovery 修复=人工）")
        rescue_section = {
            "rebuild_list": rebuild_list,
            "rebuild_status": "NEEDS_MANUAL",
            "source_hint": "老版本（或桥接机 2023 R2）导出 Parasolid(.x_t/.x_b)/STEP(.stp)"
                           "→ 2025 R1 导入 → 材质/边界/激励重建（设计稿 §0-5）",
        }
        return _finalize_report(
            entry, project_path, chain, VERDICT_NEEDS_CAD_REEXPORT,
            checks, messages, engine_raw, comparison, rescue_section,
            stage_times, root)
    if not health_res.get("ok", False):
        messages.append("体检未全过且非 geometry 类——如实 FAILED_HEALTH，附消息原文")
        return _finalize_report(
            entry, project_path, chain, VERDICT_FAILED_HEALTH,
            checks, messages, engine_raw, comparison, rescue_section,
            stage_times, root)

    # ---- Stage 3 新旧结果对比（tolerance 预声明消费；不凑绿） ----
    chain.append("S3b" if via_bridge else "S3")
    _stamp(chain[-1])
    cmp_res = executors["compare"](current_target, context)
    if not isinstance(cmp_res, Mapping):
        cmp_res = {}
    _absorb_messages(messages, cmp_res)

    if not cmp_res.get("has_baseline", False):
        messages.append(
            "原件无已存解/无基线——NO_BASELINE 如实（不伪造对比结论，设计稿 Stage 3）")
        return _finalize_report(
            entry, project_path, chain, VERDICT_NO_BASELINE,
            checks, messages, engine_raw, comparison, rescue_section,
            stage_times, root)

    family = str(cmp_res.get("family") or "default")
    tolerances = cfg["tolerances"]
    if family not in tolerances:
        messages.append(
            f"tolerances 无预声明族 {family!r}——回退 default 档（预声明值，非事后改门）")
        family = "default"
    tolerance = float(tolerances[family])
    deltas_raw = cmp_res.get("deltas")
    deltas: dict[str, float] = {}
    if isinstance(deltas_raw, Mapping):
        for metric, value in deltas_raw.items():
            try:
                deltas[str(metric)] = float(value)
            except (TypeError, ValueError):
                messages.append(f"delta {metric!r} 非数值（{value!r}）——按超差计入 fail-closed")
                deltas[str(metric)] = float("inf")
    if not deltas:
        within = False
        messages.append(
            "executor 声明有基线但零 deltas（契约缺口）——fail-closed 按超差，"
            "诚实红不凑绿（#122）")
    else:
        within = all(abs(d) <= tolerance for d in deltas.values())
    comparison = {
        "baseline_kind": str(cmp_res.get("baseline_kind") or "unknown"),
        "family": family,
        "tolerance": tolerance,
        "deltas": deltas,
        "within_tolerance": within,
        "via_bridge": via_bridge,
    }
    if within:
        verdict = (
            VERDICT_MIGRATED_VIA_BRIDGE_PASS if via_bridge
            else VERDICT_MIGRATED_DIRECT_PASS)
    else:
        verdict = VERDICT_MIGRATED_DIRECT_FAIL_COMPARISON
        messages.append(
            "对比超差——MIGRATED_DIRECT_FAIL_COMPARISON 如实红"
            + ("（via bridge）" if via_bridge else "（direct）"))
    return _finalize_report(
        entry, project_path, chain, verdict,
        checks, messages, engine_raw, comparison, rescue_section,
        stage_times, root)


def _finalize_report(
    entry: Mapping[str, Any],
    project_path: Path,
    chain: list[str],
    verdict: str,
    checks: Mapping[str, bool | None],
    messages: list[str],
    engine_raw: Mapping[str, Any],
    comparison: dict[str, Any] | None,
    rescue_section: dict[str, Any] | None,
    stage_times: Mapping[str, str],
    work_root: Path,
) -> dict[str, Any]:
    """报告总装（schema mandated 键集；comparison/rescue 非 S3/S5 达成=null）。"""
    started = stage_times.get("S0") or _now_utc()
    return {
        "schema": REPORT_SCHEMA,
        "project": entry["project"],
        "project_path": str(project_path),
        "source_sha256": entry["sha256"],
        "backup_path": entry["backup_path"],
        "source_version_best_effort": entry["source_version"],
        "fingerprint_source": entry["fingerprint_source"],
        "stage_reached": "→".join(chain),
        "verdict": verdict,
        "checks": dict(checks),
        "messages": list(messages),
        "engine_identity": _build_engine_identity(engine_raw),
        "comparison": comparison,
        "rescue": rescue_section,
        "timestamps": {
            "started_utc": started,
            "ended_utc": _now_utc(),
            "stages": dict(stage_times),
            "work_root": str(work_root),
        },
    }


# ---------------------------------------------------------------------------
# 批量编排（幂等 + inventory + 信封）
# ---------------------------------------------------------------------------

def _report_path_for(entry: Mapping[str, Any], root: Path) -> Path:
    return root / "reports" / f"{entry['stem_report_name']}.json"


def _read_prior_verdict(report_path: Path) -> str | None:
    """读既有报告 verdict（坏/缺文件 → None=不可跳过；不因脏历史炸批）。"""
    try:
        prior = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    verdict = prior.get("verdict") if isinstance(prior, Mapping) else None
    return str(verdict) if verdict else None


def migrate_batch(
    inputs: str | Path | Iterable[str | Path],
    *,
    config: Mapping[str, Any] | None = None,
    executors: Mapping[str, StageExecutor] | None = None,
    work_root: str | Path | None = None,
    yaml_path: str | Path | None = None,
) -> dict[str, Any]:
    """批量迁移编排（信封进出，规则 4）：收集 → S0 盘点 inventory.json →
    逐工程决策树（幂等跳过 MIGRATED_*）→ 报告落 ``work_root/reports/``。

    Args:
        inputs: .aedt 文件/目录（递归）/二者列表。
        config: 配置块（None=读 yaml 缺省链路）；executors=None 透传
            migrate_project 的必注入校验（响亮 ValueError 逐工程记行）。
        work_root: 产物根覆盖；缺省 config work_root（cwd 相对，#144 家族
            提醒：测试一律显式传 tmp 绝对路径）。
        yaml_path: 配置文件显式路径（缺省 configs/settings.local.yaml，
            只读）。

    Returns:
        ok_envelope：``{work_root, inventory_path, total, results, counts}``
        —— results 逐工程行（migrated 行 / skipped 幂等行 / error 行），
        counts=verdict 直方图+skipped/error 计数；输入收集失败 →
        error_envelope。
    """
    cfg = (
        parse_aedt_migrate_config(dict(config))
        if config is not None
        else load_aedt_migrate_config(yaml_path)
    )
    try:
        projects = collect_aedt_projects(inputs)
    except ValueError as exc:
        return error_envelope(str(exc))

    root = Path(work_root) if work_root is not None else Path(cfg["work_root"])
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    row_by_path: dict[str, dict[str, Any]] = {}
    for p in projects:
        try:
            entry = build_project_inventory_entry(p, root)
        except OSError as exc:
            row = {"project": p.name, "ok": False, "errors": [str(exc)]}
            row_by_path[str(p)] = row
            continue
        entry["stem_report_name"] = f"{entry['project']}__{entry['sha8']}"
        entries.append(entry)
        row_by_path[entry["path"]] = {"project": entry["project"], "ok": True}

    inventory_path = root / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema": INVENTORY_SCHEMA,
                "generated_utc": _now_utc(),
                "work_root": str(root),
                # S0 纯盘点事实；stem_report_name 是批量层内部键，不入盘点面
                "projects": [
                    {k: v for k, v in e.items() if k != "stem_report_name"}
                    for e in entries
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for entry in entries:
        prior_row = row_by_path[entry["path"]]
        if not prior_row.get("ok"):
            results.append(prior_row)
            counts["input_error"] = counts.get("input_error", 0) + 1
            continue
        report_path = _report_path_for(entry, root)
        prior_verdict = _read_prior_verdict(report_path)
        if prior_verdict is not None and is_migrated_verdict(prior_verdict):
            results.append({
                "project": entry["project"],
                "ok": True,
                "skipped": True,
                "prior_verdict": prior_verdict,
                "report_path": str(report_path),
            })
            counts["skipped"] = counts.get("skipped", 0) + 1
            continue
        try:
            report = migrate_project(
                entry["path"], cfg, executors or {}, work_root=root)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append({
                "project": entry["project"],
                "ok": True,
                "skipped": False,
                "verdict": report["verdict"],
                "stage_reached": report["stage_reached"],
                "report_path": str(report_path),
            })
            verdict = str(report["verdict"])
            counts[verdict] = counts.get(verdict, 0) + 1
        except Exception as exc:  # 单工程故障不炸整批（#105 观测/编排面惯例）
            results.append({
                "project": entry["project"],
                "ok": False,
                "errors": [f"{type(exc).__name__}: {exc}"],
            })
            counts["error"] = counts.get("error", 0) + 1
    return ok_envelope(
        work_root=str(root),
        inventory_path=str(inventory_path),
        total=len(entries),
        results=results,
        counts=counts,
    )
