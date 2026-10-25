"""ui_service.runs_recipes —— runs/ 与配方写面端点（list_runs/run_detail/events/recipe_view·save·create/tune_trials/sandbox/model3d）。

自 ui_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

from rfauto.service._helpers import safe_run_id
from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.template_hints import _template_hint  # T1 解环：模板名映射叶化

from .cache import (
    _RUN_SCAN_CACHE,
    RUNS_DIR,
    _file_signature,
    _runs_dir_key,
)

_LOG = logging.getLogger(__name__)


def list_runs(limit: int = 50) -> dict[str, Any]:
    """run 列表（UI 首页；缺省注册表路径，同 run_store 缺省解析链）。"""
    from rfauto.infra.run_store import list_runs as _list_runs

    runs = _list_runs(limit=limit)
    return ok_envelope(runs=runs)


#: P-1 终态事件类型：流读到其一即判战役结束（流自然收束，前端收 end 帧）。
RUN_TERMINAL_EVENT_TYPES = frozenset({"run_completed", "run_failed"})


def read_run_events(run_id: str, offset: int = 0) -> dict[str, Any]:
    """读单 run 的 events.jsonl 增量（P-1 SSE 桥读面，零副作用）。

    Args:
        run_id: run 目录名（``runs/<run_id>/events.jsonl``）。
        offset: 字节偏移（调用方回传上次返回值即增量续读；0=从头）。

    Returns:
        dict: {"ok", "exists", "events": [dict...], "offset", "terminal"}。
        events.jsonl 不存在→exists=False（ok=True，空流不是错误）；
        单行解析失败跳过不阻塞（#105 best-effort）；offset 恒为下一次
        续读位置（文件被截断/轮转时 offset 回退 0 全量重放）；terminal=
        **本增量内**见到终态事件（run_completed/run_failed）——按偏移
        顺序读的调用方在收到 terminal=True 后收束即可（SSE 桥口径）。
    """
    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:
        return error_envelope([f"非法 run_id: {run_id!r}"],
                              exists=False, events=[], offset=0,
                              terminal=False)
    path = RUNS_DIR / run_id_clean / "events.jsonl"
    if not path.is_file():
        return ok_envelope(exists=False, events=[], offset=0,
                           terminal=False)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(max(0, int(offset)))
            raw = f.read()
            new_offset = f.tell()
    except (OSError, ValueError) as exc:
        return error_envelope([f"events 读取失败: {exc}"],
                              exists=True, events=[], offset=0,
                              terminal=False)
    events: list[dict[str, Any]] = []
    terminal = False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue  # 半行/损坏行跳过（#105）
        if isinstance(ev, dict):
            events.append(ev)
            if str(ev.get("event_type")) in RUN_TERMINAL_EVENT_TYPES:
                terminal = True
    return ok_envelope(exists=True, events=events,
                       offset=new_offset, terminal=terminal)


def append_run_event(
    run_id: str,
    event_type: str | Any,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生产写入单条 run 事件到 runs/<run_id>/events.jsonl（U4 SSE 生产写入方）。

    背景（W0_recon §1.3 U4 定谳，2026-10）：events.jsonl 此前**只读不写**
    ——读侧 :func:`read_run_events`（P-1 SSE 桥 + runs 镜像流）的生产行
    写入方缺位：core.events.EventBus 的 set_jsonl_sink 零生产调用方，
    orchestration_wiring/agent_graph 的 emit 全部落空（无 sink 不落盘）。
    本函数补最小写入面：构造 core.events.Event（schema rfauto-event/1
    统一信封，与读侧/校验面同源）追加一行 JSONL——调参/战役终态经此落
    事件后，「写入→SSE 端点可读」端到端真实发生（terminal 事件触发 runs
    镜像流收束 end 帧）。

    不走 core 全局单例总线（进程级单 sink 会把多 run 事件互写错目录），
    直写目标 run 的文件——与读侧同一路径解析、同一路径段守卫。**不建目录**
    （run 目录由 run 链路负责创建，与读侧零副作用对称；目录缺席=run_id
    失真，open 追加抛 OSError → error 信封如实回传，不虚构 run 目录）。

    Args:
        run_id: run 目录名（``runs/<run_id>/events.jsonl``；路径段守卫
            与读侧 read_run_events 同款，穿越/分隔符一律拒）。
        event_type: EventType 枚举或其字符串值（未识别 → error 信封）。
        message: 人读语义一行（写侧不截断，调用方自律）。
        data: 结构化载荷（必须 JSON 安全映射；调用方负责可序列化值）。

    Returns:
        dict: ok 信封 ``{run_id, event_type, event_id, path}`` 或 error
        信封。写面 OSError 不抛（error 信封回传；观测面故障不得影响业务
        主路径，#105——调用方接线处再加 best-effort 兜底）。
    """
    from rfauto.core.events import Event, EventType

    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:
        return error_envelope([f"非法 run_id: {run_id!r}"])
    et_val = str(getattr(event_type, "value", event_type) or "")
    try:
        et = EventType(et_val)
    except ValueError:
        return error_envelope(
            [f"未识别 event_type: {et_val!r}（值域见 core.events.EventType）"])
    ev = Event(event_type=et, run_id=run_id_clean,
               message=str(message or ""), data=dict(data or {}))
    path = RUNS_DIR / run_id_clean / "events.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(ev.to_jsonl() + "\n")
    except OSError as exc:
        return error_envelope([f"events 写入失败: {exc}"])
    return ok_envelope(run_id=run_id_clean, event_type=et_val,
                       event_id=ev.event_id, path=str(path))


def _run_detail_signature(run_dir: Path) -> tuple[Any, ...] | None:
    """run_detail 缓存签名（aurora_f W1-S4，R3 Top1-b）。

    组成（全部廉价调用，深层嵌套树零遍历）：
    - run 根 / results/ / results/figs/ 三层 scandir **条目名集**——
      结构性变化（产物新增/删除/改名）即刻失效，不依赖目录 mtime
      （NTFS 懒更新 racy 面→TTL 兜底，与五端点族同一保守口径）；
    - metrics.json / recipe.snapshot.yaml / 逐 Touchstone (s2p/s3p) 的
      (mtime_ns, size)——语义输入的就地改写即刻失效（report.md /
      model_3d.html 只出路径不出内容，无需入签名）；
    - 深层嵌套产物（trials/checkpoints/fdtd 等仅进 files 清单）变化
      由 _UI_SCAN_TTL_S 兜底（宁多扫不多旧）。
    stat/scandir 失败 → None（直通不缓存）。
    """
    try:
        root_names: tuple[str, ...] | None
        with os.scandir(run_dir) as it:
            root_names = tuple(sorted(e.name for e in it))
        res = run_dir / "results"
        res_names: tuple[str, ...] | None = None
        figs_names: tuple[str, ...] | None = None
        if res.is_dir():
            with os.scandir(res) as it:
                res_names = tuple(sorted(e.name for e in it))
            figs = res / "figs"
            if figs.is_dir():
                with os.scandir(figs) as it:
                    figs_names = tuple(sorted(e.name for e in it))
        sp_sigs: list[tuple[Any, ...]] = []
        for pat in ("*.s2p", "*.s3p"):
            if res.is_dir():
                for sp in sorted(res.glob(pat)):
                    fs = _file_signature(sp)
                    sp_sigs.append((sp.name, fs[0] if fs else None,
                                    fs[1] if fs else None))
        return (
            root_names, res_names, figs_names,
            _file_signature(run_dir / "results" / "metrics.json"),
            _file_signature(run_dir / "recipe.snapshot.yaml"),
            tuple(sp_sigs),
        )
    except OSError:
        return None


def _freshness_block(run_dir: Path) -> dict[str, Any]:
    """run 目录 → freshness 观测块（C2 aurora_l，R1 #14/15）。

    run 详情页红条数据源：K4 ``runs_verify_service.verify_run`` 单源
    （只读）；stale 附 issue 种类摘要（``stale_kinds``）供前端红条
    "人话+摘要"消费。verify 面自身故障 → ``status="unknown"`` 不阻塞
    详情主路径（观测面 #105，与 batch_ops/em_diff 消费口同款语义）。
    """
    try:
        from rfauto.service.runs_verify_service import verify_run

        verdict = verify_run(run_dir)
    except Exception as exc:  # 新鲜度观测面故障如实 unknown 不阻塞（#105）
        return {"status": "unknown", "ok": None, "run_id": run_dir.name,
                "issues_n": 0, "stale_kinds": "",
                "note": f"新鲜度校验不可用（非阻断）: {exc}"}
    status = str(verdict.get("status", "unknown"))
    issues = [i for i in (verdict.get("issues") or []) if isinstance(i, dict)]
    kinds = ",".join(sorted({
        str(issue.get("kind")) for issue in issues if issue.get("kind")}))
    note = str(verdict.get("note") or "")
    if status == "stale":
        note = f"stale（{kinds}）：盘上产物与 run 收官指纹不符，采信前先复核"
    elif not note:  # error 等无 note 态：错误串透出（信封 errors 单源）
        note = "; ".join(str(e) for e in (verdict.get("errors") or []))
    return {
        "status": status,
        "ok": verdict.get("ok"),
        "run_id": str(verdict.get("run_id") or run_dir.name),
        "issues_n": len(issues),
        "stale_kinds": kinds,
        "note": note,
    }


def run_detail(run_id: str) -> dict[str, Any]:
    """单次 run 的全部中间产物（人工核验主页面数据）。

    聚合：metrics、S 参数曲线数据（解析 Touchstone）、产物文件清单、
    配方快照、报告路径、freshness 新鲜度观测块（C2 aurora_l）。

    缓存（aurora_f W1-S4，R3 Top1-b；aurora72 R8 Top9 落地）：per-run
    (path, mtime, size) 签名 + TTL 键控的进程内缓存（_RUN_SCAN_CACHE，
    RFAUTO_UI_CACHE=0 直通）——rglob 全树遍历与 Touchstone 重解析
    （大 run 族中–秒级）降为命中路径 sub-ms；签名语义见
    :func:`_run_detail_signature`。返回 deepcopy——调用方可自由变换
    返回值不污染缓存（与端点快照同一约定）。

    freshness **不进缓存**：新鲜度判定的是"当前盘面"（manifest 被顶替/
    损坏等形态不在 :func:`_run_detail_signature` 签名面内，缓存期内文件
    错配会出假 fresh），故缓存命中后逐请求现算（verify_run 只读哈希
    比对，代价可承受）；故障 unknown 不阻塞（#105）。
    """
    run_id_clean = safe_run_id(run_id)
    if run_id_clean is None:
        # P9-13（aurora_g W1-S1）：``RUNS_DIR / ".."`` 仓根 is_dir 通过 →
        # rglob 全仓枚举（worker 阻塞+结构泄漏）——路径段守卫前置拦截。
        return error_envelope([f"非法 run_id: {run_id!r}"])
    run_dir = RUNS_DIR / run_id_clean
    if not run_dir.is_dir():
        return error_envelope([f"run 不存在: {run_id}"])

    def _produce() -> dict[str, Any]:
        detail: dict[str, Any] = ok_envelope(run_id=run_id, run_dir=str(run_dir))

        # 产物清单（相对路径 + 大小）
        files = [
            {"path": str(p.relative_to(run_dir)).replace("\\", "/"),
             "size_bytes": p.stat().st_size}
            for p in sorted(run_dir.rglob("*")) if p.is_file()
        ]
        detail["files"] = files

        # 指标
        metrics_path = run_dir / "results" / "metrics.json"
        if metrics_path.exists():
            detail["metrics"] = json.loads(
                metrics_path.read_text(encoding="utf-8"))

        # S 参数曲线数据（|S| dB，供前端 canvas 画图）
        curves = []
        try:
            import numpy as np

            from rfauto.measurement.import_data import import_touchstone

            for sp in sorted((run_dir / "results").glob("*.s2p")) + sorted(
                (run_dir / "results").glob("*.s3p")
            ):
                data = import_touchstone(sp)
                s = data.s
                n_ports = s.shape[1]
                for m in range(n_ports):
                    for n in range(n_ports):
                        name = f"S{m + 1}{n + 1}"
                        curves.append({
                            "file": sp.name,
                            "name": name,
                            "freq_ghz": [round(float(f), 6)
                                         for f in data.freq_ghz],
                            "db": [round(float(20 * np.log10(
                                abs(s[i, m, n]) + 1e-12)), 4)
                                for i in range(s.shape[0])],
                        })
        except Exception as e:  # 无 Touchstone/解析失败不阻塞页面
            detail["sparams_warning"] = str(e)
        detail["sparams"] = curves

        # 配方快照（文本，前端展示/下载）
        snap = run_dir / "recipe.snapshot.yaml"
        if snap.exists():
            detail["recipe_snapshot"] = snap.read_text(encoding="utf-8")

        # 报告与 3D 预览
        for key, rel in (("report_md", "report.md"),
                         ("model3d_html", "model_3d.html")):
            p = run_dir / rel
            if p.exists():
                detail[key] = str(p).replace("\\", "/")

        # fake 通道无 Touchstone 时前端回退显示曲线 PNG
        detail["figs"] = [
            "runs/" + run_id + "/" + str(p.relative_to(run_dir))
            .replace("\\", "/")
            for p in sorted((run_dir / "results" / "figs").glob("*.png"))
        ]

        # 3D spec 由服务端从快照解析（前端不做 YAML 解析）
        detail["model3d"] = _model3d_from_snapshot(run_dir)
        return detail

    cached = _RUN_SCAN_CACHE.get(
        (_runs_dir_key(), os.path.normcase(str(run_dir.absolute())),
         "run_detail"),
        _run_detail_signature(run_dir), _produce)
    detail = copy.deepcopy(cached)
    # freshness 观测块（C2 aurora_l，R1 #14/15）：缓存命中后逐请求现算
    # （不进 _RUN_SCAN_CACHE——签名面盖不住 manifest 顶替/损坏，见上）；
    # verify 面故障 unknown 不阻塞（#105）。
    detail["freshness"] = _freshness_block(run_dir)
    return detail


def _model3d_from_snapshot(run_dir: Path) -> dict[str, Any] | None:
    """从配方快照解析 3D 几何 spec；模板不支持/解析失败返回 None。"""
    import yaml

    snap = run_dir / "recipe.snapshot.yaml"
    if not snap.exists():
        return None
    try:
        with open(snap, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        template = _template_hint(data)
        if template is None:
            return None
        params = {}
        for name, spec in (data.get("params") or {}).items():
            params[name] = spec.get("value") if isinstance(spec, dict) else spec
        from rfauto.adapters.openems_templates import geometry_spec

        return dict(geometry_spec(template, params), ok=True)
    except Exception:
        return None


def _workcopy_rel(path: Path) -> str | None:
    """工作副本判定（C22）：路径在 runs/recipe_workcopy/ 下则返回其相对
    recipes 根的 posix 相对路径，否则 None（#140：Path 收敛 + 双形态尝试）。"""
    from rfauto.infra.recipe_guard import WORKCOPY_SUBDIR

    root = Path(*WORKCOPY_SUBDIR)
    for probe, probe_root in ((path, root),
                              (path.resolve(),
                               (Path.cwd() / root).resolve())):
        try:
            return probe.relative_to(probe_root).as_posix()
        except ValueError:
            continue
    return None


def recipe_view(
    recipe_path: str | Path, allow_outside_roots: bool = False
) -> dict[str, Any]:
    """配方的表单化视图（人不需要写 YAML）。

    params 展开 {name: {value, unit, bounds}}，optimization/setup/objectives
    原样结构化返回。C22：工作副本（runs/recipe_workcopy/ 下）视图带
    ``is_workcopy=True`` + ``source_recipe``（对应原件路径）+
    ``review_hint``（人工审阅入库提示，指向既有审批链）；原件视图
    ``is_workcopy=False`` 且不带后两键。

    读围栏（S-3，code_audit_slice6 审查）：/api/recipe 与 MCP
    get_model_3d 是单文件读暴露面，缺省与 fs_list 同一围栏
    （:func:`rfauto.service.r3_services.fs_read_fence`：cwd + RFAUTO_FS_ROOT
    根围栏 + configs / *.local.yaml / chat_settings.yaml 敏感过滤）。
    错误走信封单源 ``error_envelope``（``{"ok": False, "errors": [...]}``
    形状不变，AU-2 批）；
    ``allow_outside_roots=True`` 只放宽根围栏（供确需根外读的调用点显式
    放行），敏感过滤不放宽。当前仓内消费者（ui/server /api/recipe、
    model3d_for_recipe ← mcp_server/前端的路径全部来自 cwd 内目录列举）
    无需放行，默认 False。
    """
    import yaml

    from rfauto.service.r3_services import WORKCOPY_REVIEW_HINT, fs_read_fence

    path = Path(recipe_path)
    fence_err = fs_read_fence(path, allow_outside_roots=allow_outside_roots)
    if fence_err is not None:
        return error_envelope([fence_err])
    if not path.exists():
        return error_envelope([f"配方不存在: {recipe_path}"])
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        # 坏 YAML 裸抛 ParserError 曾穿透到 GET /api/recipe → 500 纯文本
        # （review_aurora_next A4 P0-1）；本函数自述契约=错误走信封单源。
        return error_envelope([f"配方 YAML 解析失败: {exc}"])
    if data is None:
        data = {}  # 空文件维持既有语义（空表单）
    elif not isinstance(data, dict):
        return error_envelope([f"配方文件不是 YAML 映射（顶层为 "
                               f"{type(data).__name__}）: {recipe_path}"])

    params = []
    for name, spec in (data.get("params") or {}).items():
        if isinstance(spec, dict):
            params.append({
                "name": name,
                "value": spec.get("value"),
                "unit": spec.get("unit", ""),
                "bounds": spec.get("bounds"),
            })
        else:
            params.append({"name": name, "value": spec, "unit": "", "bounds": None})

    opt = data.get("optimization") or {}
    out: dict[str, Any] = ok_envelope(
        recipe_path=str(path).replace("\\", "/"),
        model=data.get("model", ""),
        template_hint=_template_hint(data),
        is_workcopy=False,
        params=params,
        setup=data.get("setup") or {},
        objectives=data.get("objectives") or [],
        optimization={
            "n_trials": opt.get("n_trials"),
            "sampler": opt.get("sampler", "tpe"),
            "params": {
                k: {"low": v.get("low"), "high": v.get("high")}
                for k, v in (opt.get("params") or {}).items()
            },
        },
    )
    workcopy_rel = _workcopy_rel(path)
    if workcopy_rel is not None:
        out["is_workcopy"] = True
        out["source_recipe"] = "recipes/" + workcopy_rel
        out["review_hint"] = WORKCOPY_REVIEW_HINT
    return out


def recipe_save(
    recipe_path: str | Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """把表单改动写回配方（先校验后落盘）。

    updates 允许的键：params（{name: value} 平铺，逐项带 bounds 校验）、
    setup、objectives、optimization（整段替换）。

    写面守卫（配方污染根修，处置账 待办清单「fix-recipe-pollution」条）：
    整文档 ``yaml.safe_dump`` 会丢注释/
    引号并把表单归一化的 optimization 段整段写回——2026-09-17 17:18 正是此链把
    recipes/branchline_coupler_v1.yaml 重序列化（diff 85 行）。recipes/ 原件
    一律不再原地覆盖：落 ``runs/recipe_workcopy/<同名>`` 工作副本并在返回的
    ``recipe_path`` 给出实际路径（``workcopy=True``），UI 后续「运行」应消费
    该路径；非受保护路径（tmp/沙箱/用户自定目录）行为不变。

    np 标量收敛（R3-C-02，c9920eb 复现）：落盘 payload 先经
    :func:`rfauto.infra.recipe_guard.sanitize_numpy_scalars` 递归转原生类型
    （与 :func:`write_recipe_yaml` 同一出口口径），综合内核 np.float64 透传
    不再抛 ``RepresenterError``。
    """
    import yaml

    from rfauto.infra.recipe_guard import (
        resolve_recipe_write_target,
        sanitize_numpy_scalars,
    )

    path = Path(recipe_path)
    if not path.exists():
        return error_envelope([f"配方不存在: {recipe_path}"])
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        # 坏 YAML 裸抛 ParserError 同 A4 P0-1（recipe_save 保存前先读旧文档，
        # 坏档同样穿透 → POST /api/recipe 500）；错误走信封单源。
        return error_envelope([f"配方 YAML 解析失败: {exc}"])
    if data is None:
        data = {}  # 空文件维持既有语义
    elif not isinstance(data, dict):
        return error_envelope([f"配方文件不是 YAML 映射（顶层为 "
                               f"{type(data).__name__}）: {recipe_path}"])

    unknown = set(updates) - {"params", "setup", "objectives", "optimization"}
    if unknown:
        return error_envelope([f"不允许修改的字段: {sorted(unknown)}"])

    if "params" in updates:
        current = data.get("params") or {}
        for name, value in updates["params"].items():
            if name not in current:
                return error_envelope([f"未知参数: {name}"])
            if isinstance(current[name], dict):
                current[name]["value"] = value
            else:
                current[name] = value
        data["params"] = current
    for key in ("setup", "objectives", "optimization"):
        if key in updates:
            data[key] = updates[key]

    # 落盘前先过一遍校验器（落临时文件校验，避免半成品写回）。
    # 目标经守卫决策：recipes/ 原件 → 工作副本；临时文件与目标同目录以保原子替换。
    # payload 先套 sanitize_numpy_scalars（与 write_recipe_yaml 同一出口口径）：
    # UI/前端透传的综合内核 np 标量（np.float64 等）直接 yaml.safe_dump 会抛
    # RepresenterError（c9920eb 复现），根修在写出前递归转原生类型。
    target = resolve_recipe_write_target(path, redirect=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".yaml.ui-tmp")
    tmp.write_text(
        yaml.safe_dump(sanitize_numpy_scalars(data), allow_unicode=True,
                       sort_keys=False),
        encoding="utf-8")
    # T1 解环轴：经服务定位器取门面动作（不再 实现→api 直连）
    from rfauto.service.agent_actions import validate_recipe

    try:
        validation = validate_recipe(tmp)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return error_envelope([str(e)])
    if not validation["ok"]:
        tmp.unlink(missing_ok=True)
        return error_envelope(validation["errors"],
                              warnings=validation.get("warnings", []))
    tmp.replace(target)
    redirected = target != path
    out: dict[str, Any] = ok_envelope(
        recipe_path=str(target).replace("\\", "/"),
        source_recipe=str(path).replace("\\", "/"),
        workcopy=redirected,
    )
    if redirected:
        out["message"] = (f"recipes/ 原件受保护未改动，已另存工作副本 {out['recipe_path']}"
                          "（运行/调参请用该副本；入库请人工审阅后提交）")
    return out


def recipe_create(
    recipe_path: str | Path,
    data: dict[str, Any],
) -> dict[str, Any]:
    """新建配方（工程导入向导用）：整体写入 YAML。

    与 recipe_save 同属 UI 写面；YAML 序列化与落盘在 service，UI 层只传
    路径 + 结构化 payload（#90/#92）。新建语义为整体覆盖写入。

    写面守卫：路径由用户在向导中显式键入（explicit 入口），允许在 recipes/
    下**新建**；但"新建"不得覆盖 recipes/ 既有原件——同名已存在即拒绝。
    """
    from rfauto.infra.recipe_guard import is_protected_recipe_path, write_recipe_yaml

    path = Path(recipe_path)  # PathLike/字符串统一收敛（#140）
    if not path.name:
        return error_envelope(["缺少配方路径"])
    if not isinstance(data, dict):
        # 非 dict payload（list/标量）照写后 view 即 AttributeError → 同族
        # 500（A4 P0-1 子项）；入口显式守卫，先校验后落盘与 recipe_save 同纪律。
        return error_envelope([f"配方 payload 必须是对象（dict），收到 "
                               f"{type(data).__name__}"])
    if path.exists() and is_protected_recipe_path(path):
        return error_envelope([
            f"recipes/ 原件受保护，新建不可覆盖既有配方: {path}（请换名，或另存 runs/ 下）"])
    written = write_recipe_yaml(path, data, explicit=True)
    return ok_envelope(path=str(written))


def tune_trials(
    run_id: str | None = None, limit: int = 500
) -> dict[str, Any]:
    """优化调参的 trial 级数据（UI 实时监控）。

    数据源是 optimizer 每 trial 落盘的 runs/<run_id>/trials/trial_<n>.json。
    run_id 缺省时取最近有 trials/ 目录的 run（本地单用户 UI 的"当前任务"语义）。
    """
    if run_id:
        run_id_clean = safe_run_id(run_id)
        if run_id_clean is None:  # P9-13 路径段守卫（单源 safe_run_id）
            return error_envelope([f"非法 run_id: {run_id!r}"])
        run_dir = RUNS_DIR / run_id_clean
    else:
        candidates = [
            p for p in RUNS_DIR.glob("*/trials") if p.is_dir()
        ]
        if not candidates:
            return ok_envelope(run_id=None, trials=[])
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        run_dir = newest.parent
    trials_dir = run_dir / "trials"
    if not trials_dir.is_dir():
        return ok_envelope(run_id=run_dir.name, trials=[])
    trials = []
    for p in sorted(trials_dir.glob("trial_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # 单个 trial 损坏不阻塞整表（写入方是原子性较好的小文件）
        trials.append(data)
    return ok_envelope(run_id=run_dir.name, trials=trials[-limit:])


def sandbox_drafts() -> dict[str, Any]:
    """Agent 配方沙箱草稿列表（含与真实配方的匹配 + 参数差异摘要）。"""
    from rfauto.service.agent_sandbox import RecipeSandbox

    sandbox = RecipeSandbox()
    drafts = sandbox.list_drafts().get("drafts", [])
    # 反查草稿来源：对 recipes/ 下每个配方重算确定性草稿名（stem+路径哈希）
    known: dict[str, str] = {}
    for recipe in sorted(Path("recipes").rglob("*.yaml")):
        try:
            known[str(sandbox.draft_path(recipe))] = str(recipe).replace("\\", "/")
        except Exception:
            continue
    items = []
    for draft in drafts:
        recipe = known.get(draft)
        item: dict[str, Any] = {"draft": draft, "recipe": recipe}
        if recipe:
            try:
                d = sandbox.diff(recipe)
                if d.get("ok"):
                    item["params_changed"] = d["params_changed"]
                    item["has_text_diff"] = bool(d.get("unified_diff"))
            except Exception as e:
                item["diff_error"] = str(e)
        items.append(item)
    return ok_envelope(drafts=items)


def sandbox_diff(recipe_path: str | Path) -> dict[str, Any]:
    """单个沙箱草稿与真实配方的 diff（unified diff + 参数差异表）。"""
    from rfauto.service.agent_sandbox import RecipeSandbox, SandboxViolation

    try:
        return RecipeSandbox().diff(recipe_path)
    except SandboxViolation as e:
        return {"ok": False, "error": str(e)}


def sandbox_promote(
    recipe_path: str | Path, adapter_name: str = "fake"
) -> dict[str, Any]:
    """草稿差异送三层 Gate（生成提案进收件箱，等人工批准才生效）。"""
    from rfauto.service.agent_sandbox import RecipeSandbox, SandboxViolation

    try:
        return RecipeSandbox().promote(recipe_path, adapter_name=adapter_name)
    except SandboxViolation as e:
        return {"ok": False, "error": str(e)}


def model3d_for_recipe(recipe_path: str | Path) -> dict[str, Any]:
    """配方的 3D 几何 spec（毫米；前端 three.js 渲染）。"""
    view = recipe_view(recipe_path)
    if not view["ok"]:
        return view
    from rfauto.adapters.openems_templates import geometry_spec

    template = view["template_hint"]
    if template is None:
        return error_envelope(
            ["配方模型无 3D 模板映射（仅 wilkinson/branchline/patch 支持）"])
    params = {p["name"]: p["value"] for p in view["params"]}
    # 模板参数名归一（arm_len_mm 等与配方同名；unit 忽略）
    spec = geometry_spec(template, params)
    spec["ok"] = True
    spec["recipe_path"] = view["recipe_path"]
    return spec


def model3d_for_params(
    template: str,
    params: dict[str, Any] | None = None,
    substrate: Any = None,
) -> dict[str, Any]:
    """按模板 + 参数直接计算 3D 几何 spec（无配方文件；前端滑条实时预览）。

    几何计算是确定性内核（adapters/openems_templates.geometry_spec），
    UI 层只传模板名与参数字典（#90/#92）。
    """
    from rfauto.adapters.openems_templates import geometry_spec

    return dict(geometry_spec(template, params or {}, substrate), ok=True)
