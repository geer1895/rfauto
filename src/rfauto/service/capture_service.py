"""C3 capture 面：会话动作捕获 → 配方草稿编译（aurora_r R-09）。

思想来源（ADS 2027 宏录制，Keysight capture-accelerate-orchestrate 的
capture 段）：用户在 GUI/Agent 里的操作序列先被"录制"为可重放事件流，
再编译成可复用资产。本模块=最小可用闭环（纯 service 面，零 CLI/MCP 叶）：

- **Recorder（录制器）**：:func:`start_capture` / :func:`record_action` /
  :func:`stop_capture` 把动作序列（kind 闭合枚举，见 :data:`ACTION_KINDS`）
  逐条追加为 JSONL 会话——``runs/capture_sessions/<session_id>.jsonl``
  （runs/ 会话产物惯例，双根收敛同 infra.runs_paths；agent_trace 同形态）。
- **Compiler（编译器）**：:func:`compile_capture` 把录制会话编译成配方
  草稿 YAML——**只落 runs/recipe_sandbox/ 沙箱**（规则 6 agent 写面隔离 +
  规则 3 分层双重守卫：recipe_guard 受保护 ``recipes/`` 生产根绝对拒绝，
  比较用 normcase+casefold，#318 口径）。草稿生效唯一通道仍是
  promote → 三层 Gate（本模块不接线 promote）。
- **诚实草稿**：无法从会话确定的段（setup/objectives/optimization，如
  sampler 配置）显式省略，并以 ``# capture-draft: <段名> 未能从会话推断``
  注释如实标注——不伪造完整配方。
- **零变化缺省**：不调用就不落盘——本模块无 import 期副作用、无自动录制
  挂钩，runs/capture_sessions 与 runs/recipe_sandbox 仅在被调用时创建。

动作 kind 语义（捕获对象=用户动作序列，对照 service/api/run_core.run_once
单次运行入口；payload 惯例键为约定非强校验，除 set_param 两必填）：

- ``run_once``  ：单次仿真。payload 惯例键：``recipe_path`` / ``model`` /
  ``template`` / ``params``（参数快照 dict）/ ``setup``。
- ``eval``      ：单点评测。payload 惯例键：``model`` / ``template`` /
  ``params``（可含 ``metric`` / ``cost`` 等观测，编译器忽略未知键）。
- ``set_param`` ：参数修改。payload **必含** ``key``（非空 str）与
  ``value``——``value=0/False`` 等假值是合法值，判缺用 ``in`` 不用真值
  （#364 falsy 陷阱）。

信封与失败面（规则 4 服务层 JSON 进出）：全部走 service.envelope 构造器。
未知 kind（fail-closed）/ set_param 缺 key/value / 会话空 / 损坏 JSONL /
沙箱越界 / recipes/ 生产路径一律 error 信封点名原因，不抛异常打断调用链；
JSONL 写失败同理以 error 信封上报——捕获是本调用的产物，静默丢动作=
数据完整性谎言（#105 的 best-effort 豁免面：观测面不阻塞主路径，但本模块
自身就是"主路径"，故 fail-visible）。

挂账处方（CLI/MCP 叶由主代合流批统一接线，#221② 防捎带）::

    rfauto capture start [--name NAME]                     → start_capture
    rfauto capture record <session> <kind> [payload-json]  → record_action
    rfauto capture stop <session>                          → stop_capture
    rfauto capture compile <session> [--name DRAFT]        → compile_capture

（MCP 叶同形态四工具：capture_start / capture_record / capture_stop /
capture_compile。）
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.infra.recipe_guard import (
    check_recipe_write_target,
    is_protected_recipe_path,
    sanitize_numpy_scalars,
    write_recipe_text,
)
from rfauto.infra.runs_paths import resolve_runs_dir
from rfauto.service.agent_sandbox import ALLOWED_SUFFIXES, SANDBOX_ROOT
from rfauto.service.agent_trace import args_summary
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "ACTION_KINDS",
    "CAPTURE_SCHEMA",
    "CAPTURE_SESSIONS_DIR",
    "MAX_PAYLOAD_CHARS",
    "UNINFERRED_SECTIONS",
    "compile_capture",
    "record_action",
    "start_capture",
    "stop_capture",
]

#: 会话行 schema 版本（recipe_version 与 schema_version 语义区分，#106）
CAPTURE_SCHEMA = "rfauto-capture-v1"

#: 会话 JSONL 目录（cwd 相对惯例形；使用处经 runs 双根收敛）
CAPTURE_SESSIONS_DIR = Path("runs") / "capture_sessions"

#: 动作 kind 闭合枚举（未知 kind 拒绝录入，fail-closed）
ACTION_KINDS = ("run_once", "eval", "set_param")

#: 编译器无法从会话推断、草稿内如实标注的配方段（含 sampler 所属 optimization）
UNINFERRED_SECTIONS = ("setup", "objectives", "optimization")

#: 单条 payload 序列化上限（字符）——捕获面防误传大对象
MAX_PAYLOAD_CHARS = 20000

#: 会话 id 白名单（文件名安全段：字母/数字/点/下划线/连字符，不以点开头）
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class _CompileError(Exception):
    """编译期可预期失败的内部信号（compile_capture 捕获后转 error 信封）。"""

    def __init__(self, messages: list[str], **fields: Any):
        super().__init__("; ".join(messages))
        self.messages = messages
        self.fields = fields


# ─── 路径与会话文件面 ─────────────────────────────────────────────────────────


def _norm(path: Path) -> str:
    """比较用规范形：normcase（Windows 大小写/分隔符归一）+ 显式 casefold
    （POSIX normcase 恒等，仅靠它放过大写变体——#318 同款）。"""
    return os.path.normcase(str(path)).lower()


def _sessions_dir() -> Path:
    return resolve_runs_dir(CAPTURE_SESSIONS_DIR)


def _session_file(session_id: Any) -> Path | None:
    """合法会话 id → 会话 JSONL 路径；非法（含路径穿越形态）→ None。"""
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        return None
    return _sessions_dir() / f"{session_id}.jsonl"


def _ts() -> str:
    """ISO 8601 本地时间带时区偏移（agent_trace W5-P3-3 同款）。"""
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _read_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """读会话 JSONL → (记录列表, 问题列表)。

    空行跳过；损坏行不中断读取（追加式日志，坏前缀不挡追加），问题按
    1 起始行号点名——由调用方决定宽容（record 追加计数）或严格（compile）。
    """
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.exists():
        return records, problems
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"第 {lineno} 行损坏 JSON: {exc.msg}")
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            problems.append(f"第 {lineno} 行非对象记录: {type(obj).__name__}")
    return records, problems


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ─── Recorder（录制器）───────────────────────────────────────────────────────


def start_capture(name: str | None = None) -> dict[str, Any]:
    """开一个捕获会话（runs/capture_sessions/<session_id>.jsonl）。

    name 缺省自动生成（cap_<时间戳>_<随机>）；给定时必须是文件名安全段
    （``[A-Za-z0-9][A-Za-z0-9._-]{0,63}``，拒绝 ``..``/分隔符=路径穿越
    fail-closed）。同名会话已存在 → error 信封（不追加混流）。
    """
    if name is None:
        session_id = (
            "cap_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_"
            + os.urandom(3).hex()
        )
    elif isinstance(name, str) and _SESSION_ID_RE.match(name):
        session_id = name
    else:
        return error_envelope(
            [f"非法会话名: {name!r}（只允许 [A-Za-z0-9][A-Za-z0-9._-]，"
             "1-64 字符，不以点开头；拒绝路径分隔符与 .. 穿越形态）"])
    directory = _sessions_dir()
    path = directory / f"{session_id}.jsonl"
    if path.exists():
        return error_envelope(
            [f"会话已存在: {session_id}（同名不追加混流；换名或删除旧会话文件）"],
            session_id=session_id, path=str(path))
    record = {
        "schema": CAPTURE_SCHEMA,
        "record": "session_start",
        "ts": _ts(),
        "session_id": session_id,
    }
    try:
        _append_record(path, record)
    except OSError as exc:
        return error_envelope(
            [f"会话文件创建失败: {exc}"], session_id=session_id)
    return ok_envelope(session_id=session_id, path=str(path), started_at=record["ts"])


def record_action(
    session_id: str, kind: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """向会话追加一条动作记录（seq/ts/kind/payload 摘要，JSONL 一行）。

    fail-closed 面：未知 kind 拒绝录入（闭合枚举）；set_param 必含
    ``key``（非空 str）与 ``value``（判缺用 ``in``——0/False 合法，#364）；
    payload 必须可 JSON 序列化且 ≤ :data:`MAX_PAYLOAD_CHARS`。
    seq=既有动作记录计数（追加序=时间序，seq 为跨进程安全的冗余计数）。
    """
    path = _session_file(session_id)
    if path is None:
        return error_envelope(
            [f"非法会话 id: {session_id!r}（只允许 [A-Za-z0-9][A-Za-z0-9._-]，"
             "1-64 字符）"])
    if not path.exists():
        return error_envelope(
            [f"会话不存在（先 start_capture）: {session_id}"],
            session_id=session_id)
    if kind not in ACTION_KINDS:
        return error_envelope(
            [f"未知动作 kind: {kind!r}（闭合枚举: {', '.join(ACTION_KINDS)}；"
             "未知 kind 拒绝录入 fail-closed）"],
            session_id=session_id, kind=str(kind))
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return error_envelope(
            ["payload 必须是 dict（键值对；None 视为空 dict）"],
            session_id=session_id, kind=kind)
    if kind == "set_param":
        key = payload.get("key")
        if not isinstance(key, str) or not key.strip():
            return error_envelope(
                ["set_param 动作 payload 必含非空字符串 key"],
                session_id=session_id, kind=kind)
        if "value" not in payload:  # 判缺用 in：value=0/False 是合法值（#364）
            return error_envelope(
                ["set_param 动作 payload 必含 value（0/False 等假值合法，"
                 "判缺用 in 不用真值）"],
                session_id=session_id, kind=kind, key=key)
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError) as exc:
        return error_envelope(
            [f"payload 不可 JSON 序列化: {exc}"],
            session_id=session_id, kind=kind)
    if len(text) > MAX_PAYLOAD_CHARS:
        return error_envelope(
            [f"payload 过大: {len(text)} > {MAX_PAYLOAD_CHARS} 字符"],
            session_id=session_id, kind=kind)
    payload_safe = json.loads(text)  # 回读保证落 JSONL 后编译器可读回
    prior, _problems = _read_records(path)  # 追加式日志：坏前缀不挡追加
    seq = sum(1 for r in prior if r.get("record") == "action")
    record = {
        "schema": CAPTURE_SCHEMA,
        "record": "action",
        "seq": seq,
        "ts": _ts(),
        "kind": kind,
        "payload": payload_safe,
        "payload_summary": args_summary(payload),
    }
    try:
        _append_record(path, record)
    except OSError as exc:
        return error_envelope(
            [f"会话文件写入失败: {exc}"], session_id=session_id, kind=kind)
    return ok_envelope(session_id=session_id, seq=seq, kind=kind, path=str(path))


def stop_capture(session_id: str) -> dict[str, Any]:
    """收束会话：追加 session_stop 行并返回动作计数/kind 直方图（幂等）。"""
    path = _session_file(session_id)
    if path is None:
        return error_envelope(
            [f"非法会话 id: {session_id!r}（只允许 [A-Za-z0-9][A-Za-z0-9._-]，"
             "1-64 字符）"])
    if not path.exists():
        return error_envelope(
            [f"会话不存在（先 start_capture）: {session_id}"],
            session_id=session_id)
    records, _problems = _read_records(path)
    actions = [r for r in records if r.get("record") == "action"]
    kinds = dict(Counter(str(r.get("kind")) for r in actions))
    if any(r.get("record") == "session_stop" for r in records):
        return ok_envelope(session_id=session_id, path=str(path),
                           already_stopped=True, actions=len(actions), kinds=kinds)
    record = {
        "schema": CAPTURE_SCHEMA,
        "record": "session_stop",
        "ts": _ts(),
        "actions": len(actions),
    }
    try:
        _append_record(path, record)
    except OSError as exc:
        return error_envelope(
            [f"会话文件写入失败: {exc}"], session_id=session_id)
    return ok_envelope(session_id=session_id, path=str(path),
                       already_stopped=False, actions=len(actions), kinds=kinds)


# ─── Compiler（编译器）───────────────────────────────────────────────────────


def _resolve_sandbox_root(sandbox_root: str | Path | None) -> Path:
    """沙箱根解析 + 受保护 recipes/ 生产根拒绝（规则 6+规则 3 双重守卫）。

    缺省 = agent_sandbox.SANDBOX_ROOT（runs/recipe_sandbox，runs 双根收敛）；
    显式给定时相对路径同样收敛，绝对路径原样。根解析后 normcase+casefold
    与 recipe_guard 受保护根比对（#318：Windows 大小写/分隔符变体、POSIX
    大写变体都不可逃逸）。
    """
    root = Path(SANDBOX_ROOT) if sandbox_root is None else Path(sandbox_root)
    root = root if root.is_absolute() else resolve_runs_dir(root)
    try:
        root = root.resolve()
    except OSError:  # pragma: no cover - 非常规文件系统状态兜底
        root = Path(os.path.abspath(root))
    if is_protected_recipe_path(root):
        raise _CompileError(
            [f"沙箱根不可指向受保护 recipes/ 生产区: {root}"
             "（规则 6 agent 写面隔离 + 规则 3；recipe_guard 受保护根 "
             "normcase 白名单同款 #318 口径）"])
    return root


def _guard_draft_path(root: Path, draft_name: str) -> Path:
    """草稿名 → 沙箱内路径（normcase 白名单包含 + 后缀白名单，#318 口径）。"""
    name = str(draft_name)
    if not name.strip() or name in (".", ".."):
        raise _CompileError([f"非法草稿名: {name!r}"])
    candidate = root / name  # 绝对名会被 pathlib 整体替换 → 包含判定兜底
    try:
        candidate = candidate.resolve()
    except OSError:  # pragma: no cover - 非常规文件系统状态兜底
        candidate = Path(os.path.abspath(candidate))
    n_root = _norm(root)
    n_draft = _norm(candidate)
    prefix = n_root if n_root.endswith(os.sep) else n_root + os.sep
    if n_draft != n_root and not n_draft.startswith(prefix):
        raise _CompileError(
            [f"草稿路径越出沙箱: {candidate}（沙箱根 {root}；"
             "normcase 白名单 #318 口径）"])
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise _CompileError(
            [f"草稿后缀只允许 {sorted(ALLOWED_SUFFIXES)}: {candidate.name}"])
    return candidate


def _extract_session_actions(
    records: list[dict[str, Any]], session_id: str
) -> list[dict[str, Any]]:
    """筛选动作记录并做防御纵深复验（录制端 fail-closed，文件面再验）。"""
    actions: list[dict[str, Any]] = []
    for r in records:
        if r.get("record") != "action":
            continue
        kind = r.get("kind")
        if kind not in ACTION_KINDS:
            raise _CompileError(
                [f"动作不支持: {kind!r}（闭合枚举: {', '.join(ACTION_KINDS)}；"
                 f"会话 {session_id} 第 {len(actions)} 个动作）"])
        payload = r.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise _CompileError(
                [f"动作 payload 非对象: {type(payload).__name__}"
                 f"（会话 {session_id} 第 {len(actions)} 个动作）"])
        actions.append({**r, "payload": payload})
    return actions


def compile_capture(
    session: str | Path,
    *,
    draft_name: str | None = None,
    sandbox_root: str | Path | None = None,
) -> dict[str, Any]:
    """录制会话 → 配方草稿 YAML（只落沙箱；诚实草稿不伪造完整配方）。

    ``session``：会话 id（runs/capture_sessions/<id>.jsonl）或显式 JSONL
    路径（含路径分隔符/``.jsonl`` 后缀且存在时按路径读）。

    提取面：模板/模型名（run_once/eval payload 的 ``model``/``template``
    惯例键，二者互斥）、参数变化轨迹（set_param 时序）、最终参数集
    （params 快照 update + set_param 覆盖，追加序=时间序）。未能推断的段
    显式省略并加 ``# capture-draft: <段名> 未能从会话推断`` 注释。

    守卫面：沙箱根/草稿路径 normcase 白名单（#318）+ 受保护 recipes/
    生产根绝对拒绝 + recipe_guard 统一写出口。编译失败（会话空/损坏
    JSONL/动作不支持/无法定模型）一律 error 信封点名原因。
    """
    try:
        return _compile_capture_impl(
            session, draft_name=draft_name, sandbox_root=sandbox_root)
    except _CompileError as exc:
        return error_envelope(exc.messages, **exc.fields)
    except Exception as exc:  # 兜底：编译器不向调用链抛裸异常
        return error_envelope([f"编译失败: {type(exc).__name__}: {exc}"])


def _compile_capture_impl(
    session: str | Path,
    *,
    draft_name: str | None,
    sandbox_root: str | Path | None,
) -> dict[str, Any]:
    s = str(session)
    if ("/" in s or "\\" in s or s.endswith(".jsonl")) and Path(s).is_file():
        path = Path(s)
        session_id = path.stem
    else:
        resolved = _session_file(s)
        if resolved is None:
            raise _CompileError(
                [f"非法会话 id: {s!r}（只允许 [A-Za-z0-9][A-Za-z0-9._-]，"
                 "1-64 字符；或给出现存 JSONL 路径）"])
        path = resolved
        session_id = s
    if not path.exists():
        raise _CompileError(
            [f"会话不存在（先 start_capture）: {session_id}"],
            session_id=session_id)

    records, problems = _read_records(path)
    if problems:
        raise _CompileError(
            [f"会话 JSONL 损坏（fail-closed，不编坏账）: {path}", *problems],
            session_id=session_id, path=str(path))
    actions = _extract_session_actions(records, session_id)
    if not actions:
        raise _CompileError(
            [f"会话无动作（录制为空，无配方可编译）: {session_id}"],
            session_id=session_id, path=str(path))

    # ── 动作序列走读：提取模型名/参数轨迹/最终参数集/可推断段 ─────────────
    model_name: str | None = None
    template_name: str | None = None
    current_params: dict[str, Any] = {}
    initial_params: dict[str, Any] | None = None
    trajectory: dict[str, list[dict[str, Any]]] = {}
    inferred: dict[str, Any] = {}
    for action in actions:
        kind = action["kind"]
        payload = action["payload"]
        if kind in ("run_once", "eval"):
            m = payload.get("model")
            t = payload.get("template")
            if model_name is None and isinstance(m, str) and m.strip():
                model_name = m.strip()
            if template_name is None and isinstance(t, str) and t.strip():
                template_name = t.strip()
            params = payload.get("params")
            if isinstance(params, dict):
                if initial_params is None:
                    initial_params = dict(params)
                current_params.update(params)
            for section in UNINFERRED_SECTIONS:
                value = payload.get(section)
                if isinstance(value, (dict, list)) and value:
                    inferred[section] = value  # 段信息最后一条动作为准
        else:  # set_param（_extract_session_actions 已验 kind 闭合）
            key = payload.get("key")
            if not isinstance(key, str) or not key.strip() or "value" not in payload:
                raise _CompileError(
                    [f"set_param 动作缺合法 key/value（会话 {session_id} "
                     f"seq={action.get('seq')}；#364：value 判缺用 in）"],
                    session_id=session_id)
            current_params[key] = payload["value"]
            trajectory.setdefault(key, []).append(
                {"seq": action.get("seq"), "value": payload["value"]})

    if model_name and template_name:
        raise _CompileError(
            [f"会话同时携带 model 与 template（配方二选一互斥，无法消歧）:"
             f" model={model_name!r} template={template_name!r}"],
            session_id=session_id)
    if not model_name and not template_name:
        raise _CompileError(
            ["无法确定模型/模板名：会话动作 payload 未携带 model/template"
             "（run_once/eval payload 惯例键）"],
            session_id=session_id)

    # ── 草稿组装（诚实草稿：未推断段省略+标注）────────────────────────────
    uninferred = [sec for sec in UNINFERRED_SECTIONS if sec not in inferred]
    body: dict[str, Any] = {
        "recipe_version": 1,
        "notes": (
            f"capture 草稿（会话 {session_id}，{len(actions)} 动作编译；"
            "未经三层 Gate 不可直接生效——promote 走 agent_sandbox 同链）"),
        "params": current_params,
    }
    if model_name:
        body["model"] = model_name
        body["schema_version"] = 1
    else:
        body["template"] = template_name
    body.update(inferred)

    root = _resolve_sandbox_root(sandbox_root)
    name = draft_name if draft_name is not None else f"capture_{session_id}.yaml"
    draft = _guard_draft_path(root, name)
    try:
        # belt-and-braces：受保护 recipes/ 生产路径绝对拒绝（含根被指到
        # 生产区的残余形态；check 抛 RecipeWriteForbidden → _CompileError）
        check_recipe_write_target(draft)
    except Exception as exc:
        raise _CompileError(
            [f"草稿目标被写守卫拒绝: {draft}（{exc}）"]) from exc

    import yaml  # lazy: 与仓内服务同款按需引入

    body_text = yaml.safe_dump(
        sanitize_numpy_scalars(body), allow_unicode=True, sort_keys=False)
    header = [
        f"# capture-draft: 由会话 {session_id} 编译（{len(actions)} 动作，{_ts()}）",
        "# capture-draft: 草稿未经三层 Gate 不可直接生效（规则 6 沙箱写面）",
    ]
    header += [f"# capture-draft: {sec} 未能从会话推断" for sec in uninferred]
    full_text = "\n".join(header) + "\n\n" + body_text
    written = write_recipe_text(draft, full_text)

    return ok_envelope(
        session_id=session_id,
        draft=str(written),
        actions=len(actions),
        form="model" if model_name else "template",
        model=model_name,
        template=template_name,
        params=current_params,
        params_initial=initial_params if initial_params is not None else {},
        param_trajectory=trajectory,
        uninferred=uninferred,
    )
