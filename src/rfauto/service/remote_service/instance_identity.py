"""grpcsrv 实例身份绑定（VB-4，aurora_r R-15；思想级化用 ADR-0004）。

问题面：服务器 8 路并行后 gRPC 端口复用风险真实（A22"跨席实例 attach"
教训）——attach 侧此前无身份核验，端口上是谁就消费谁。本模块给
``ansysedt -grpcsrv`` 实例落**实例记录**（发射时）+ **attach 侧核验**
（pyaedt 1.9.0 ``Desktop.aedt_process_id``＝gRPC 连接后服务端
``GetProcessID()`` 实证，desktop.py ``@property aedt_process_id``），
判定失配/记录缺失/记录损坏一律拒连，**永不回退**到"该端口上任意实例"
（ADR-0004 口径：记录=候选非鉴权、错误/歧义/未命中永不回退、已消失的
选择不得跟随到另一实例）。

身份锚定三要素（记录只是候选，核对的是活实例）：

- PID：attach 后 ``desktop.aedt_process_id`` 与记录比对（端口被他人实例
  占用 → PID 不符拒）；
- 进程创建时刻：SSH→PowerShell ``Win32_Process.CreationDate`` 查询与记录
  比对（同 PID 复用 → 时刻不符拒）；
- 记录完备性：缺 key/坏 JSON/类型错/时刻不可解析 → 记录损坏拒（读取失败
  同损坏，永不回退）。

边界（如实登记）：核验面＝hfss_smoke L1/L2 发射-attach 链；``attach``
语义是 pyaedt API 顺序决定的——``aedt_process_id`` 只有连接建立后才可得，
"拒连"＝拒绝消费已建立的连接并在 finally 释放（不回退、不换目标继续）。
``license_preflight`` 的 deep attach 为信息面读数（无发射记录可核），保持
informational 语义不接本核验。开关缺省关（env
``RFAUTO_REMOTE_INSTANCE_VERIFY`` 未设时发射/attach/清理全链路逐字节
零变化）。

命令构造遵守 G5/SSH→PS 纪律：全程**零双引号**（单引号不经 argv 层存活，
W7-B §1.5-1 证据链），``$_`` 经 paramiko 直达远端 PS（无本地 shell 展开）；
含单引号或空白的路径无法安全引用 → fail-closed 拒写拒删（不猜不试）。

记录目录权限：本地副本目录 0700/文件 0600（best-effort，Windows chmod
语义受限但方向正确）；服务器侧落 E 盘中间文件根（规则 0b：唯一中间根
``hfss_project_root``＝登记表现值 E:\\rfauto_remote，禁写生产云盘），
依赖该根本身既有的访问模型。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any

from rfauto.infra.remote_machines import RemoteMachineConfig, SshTransport

#: 核验开关（缺省关＝零行为变化；truthy 集 = {1,true,yes,on} 大小写不敏感）
REMOTE_INSTANCE_VERIFY_ENV = "RFAUTO_REMOTE_INSTANCE_VERIFY"

_VERIFY_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: 记录必含键（恰好七键：多 key/缺 key 都判损坏——ADR-0004"匹配完整记录"）
RECORD_KEYS = frozenset({
    "port", "pid", "process_create_time", "seat", "project_root", "uuid",
    "created_at",
})

#: 记录文件名前缀（人类可读审计面；uuid 段保证并发发射不互撞）
RECORD_FILENAME_PREFIX = "grpcsrv_instance_p"

#: 服务器侧记录目录名（挂在登记表 ``hfss_project_root``＝E 盘中间根下）
REMOTE_RECORD_DIRNAME = "instance_records"

#: 进程创建时刻的规范形态：``yyyyMMddHHmmss.ffffff``（可选 DMTF 时区偏移
#: 后缀 ``+480``/``-0700``——同机同命令产出两侧，形态自洽；解析后比对）
_CREATION_RE = re.compile(
    r"^(\d{14})(?:\.(\d{1,10}))?(?:([+-])(\d{3,4}))?$"
)

#: 查询产出协议行（``pid|creation``；非协议行——计数/表头/空行——不误判）
_QUERY_LINE_RE = re.compile(r"^(\d+)\|(.*)$")


class InstanceRecordError(ValueError):
    """实例记录构造/落盘/远端路径不安全类失败（fail-closed 载体）。"""


def instance_verify_enabled(environ: dict[str, str] | None = None) -> bool:
    """核验开关判定（纯函数；缺省关＝零行为变化契约）。"""
    env = os.environ if environ is None else environ
    return str(env.get(REMOTE_INSTANCE_VERIFY_ENV, "")).strip().lower() \
        in _VERIFY_TRUTHY


def parse_creation_to_key(raw: str | None) -> tuple[str, int, str] | None:
    """进程创建时刻字符串 → 规范比对键（纯函数；不可解析 → ``None``）。

    键形态 ``(yyyyMMddHHmmss, 微秒, 时区偏移原文|"")``：同键=同一创建时刻。
    小数秒右侧补零到微秒（``.5`` ≡ ``.500000``）；时区偏移保留原文入键
    （无偏移与有偏移不同键——fail-closed，不做跨时区换算猜测）。
    """
    if raw is None:
        return None
    m = _CREATION_RE.match(str(raw).strip())
    if m is None:
        return None
    base, frac, _sign, offset = m.groups()
    micros = int((frac or "").ljust(6, "0")[:6]) if frac else 0
    return (base, micros, offset or "")


def build_instance_record(
    *,
    port: int,
    pid: int,
    process_create_time: str,
    seat: str | None,
    project_root: str,
) -> dict[str, Any]:
    """构造实例记录（uuid/created_at 就地生成；形状不合即抛）。"""
    record: dict[str, Any] = {
        "port": int(port),
        "pid": int(pid),
        "process_create_time": str(process_create_time),
        "seat": str(seat) if seat else "unknown",
        "project_root": str(project_root),
        "uuid": uuid_mod.uuid4().hex,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    validate_instance_record(record)
    return record


def validate_instance_record(data: Any) -> None:
    """记录形状校验（纯函数）：不合 → :class:`InstanceRecordError`。

    恰好七键 + port/pid 为 int（bool 排除——bool 是 int 子类陷阱）+
    其余五键为 str + 创建时刻可解析。校验器与加载器共用（读写同规）。
    """
    if not isinstance(data, dict):
        raise InstanceRecordError("记录不是 JSON object")
    if set(data) != set(RECORD_KEYS):
        missing = sorted(set(RECORD_KEYS) - set(data))
        extra = sorted(set(data) - set(RECORD_KEYS))
        raise InstanceRecordError(
            f"记录键集不合（缺={missing} 多={extra}）"
        )
    for key in ("port", "pid"):
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise InstanceRecordError(f"记录键 {key} 不是 int")
    for key in ("process_create_time", "seat", "project_root", "uuid",
                "created_at"):
        if not isinstance(data[key], str):
            raise InstanceRecordError(f"记录键 {key} 不是 str")
    if parse_creation_to_key(data["process_create_time"]) is None:
        raise InstanceRecordError("process_create_time 不可解析")


def record_filename(record: dict[str, Any]) -> str:
    """记录文件名：``grpcsrv_instance_p<port>_<uuid 前 8>.json``。"""
    return f"{RECORD_FILENAME_PREFIX}{record['port']}_{record['uuid'][:8]}.json"


def write_instance_record(record: dict[str, Any], local_dir: Path | str) -> dict[str, Any]:
    """落本地副本（目录 0700/文件 0600 best-effort）并返回路径信息。"""
    validate_instance_record(record)
    directory = Path(local_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with_context = _chmod_best_effort(directory, 0o700)
    path = directory / record_filename(record)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    file_context = _chmod_best_effort(path, 0o600)
    return {
        "local_path": str(path),
        "filename": path.name,
        "dir_mode_applied": with_context,
        "file_mode_applied": file_context,
    }


def _chmod_best_effort(path: Path, mode: int) -> bool:
    """chmod 尽力而为（#105 观测性零故障点纪律：失败不阻塞主路径）。"""
    try:
        os.chmod(path, mode)
        return True
    except OSError:
        return False


def load_instance_record(path: Path | str) -> tuple[str, dict[str, Any] | None]:
    """读实例记录 → ``(state, record)``；state ∈ ok/missing/corrupt。

    文件不存在 → ``missing``；JSON 坏/形状不合/读取失败 → ``corrupt``
    （读取失败同损坏拒——ADR-0004 永不回退，不猜不试）。state=``ok`` 时
    ``record`` 已过校验器（judge 消费侧免重复防御）。
    """
    file_path = Path(path)
    try:
        if not file_path.is_file():
            return ("missing", None)
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return ("corrupt", None)
    try:
        data = json.loads(text)
    except ValueError:
        return ("corrupt", None)
    try:
        validate_instance_record(data)
    except InstanceRecordError:
        return ("corrupt", None)
    return ("ok", data)


# ─── SSH→PS 查询命令构造（G5：全程零双引号） ────────────────────────────────

_CREATION_PROJECTION = (
    "ForEach-Object { '{0}|{1}' -f $_.ProcessId, "
    "$_.CreationDate.ToString('yyyyMMddHHmmss.ffffff') }"
)


def query_creation_by_fingerprint_command(
    process_name: str, fingerprint: str,
) -> str:
    """按进程名+命令行指纹查 ``pid|creation``（发射侧定位本批实例）。

    形态与 :func:`remote_mutex_command` 同源（G5 单引号零双引号），投影
    换为创建时刻——单次查询同时取 PID 与时刻，避免两次往返间进程换代。
    """
    return (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -eq '{process_name}' -and "
        f"$_.CommandLine -match '{fingerprint}' }} | "
        + _CREATION_PROJECTION
    )


def query_creation_by_pid_command(pid: int) -> str:
    """按 PID 查 ``pid|creation``（attach 侧核验：活实例创建时刻）。"""
    return (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.ProcessId -eq {int(pid)} }} | "
        + _CREATION_PROJECTION
    )


def parse_creation_query_output(out: str) -> list[tuple[int, str]]:
    """解析 ``pid|creation`` 协议行（纯函数；非协议行忽略，防表头假阳）。"""
    hits: list[tuple[int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        m = _QUERY_LINE_RE.match(line)
        if m is None:
            continue
        pid_s, creation = m.groups()
        creation = creation.strip()
        if not creation:
            continue
        hits.append((int(pid_s), creation))
    return hits


# ─── 远端记录路径（E 盘中间根惯例，接地 hfss_project_root） ─────────────────


def remote_record_paths(project_root: str, filename: str) -> dict[str, str]:
    """记录的远端三形态路径（win 目录/sftp 路径/win 文件）；不安全即抛。

    G5：含单引号或空白的路径无法安全引用 → fail-closed（不猜不试）。
    """
    root = str(project_root).replace("/", "\\")
    if not root or "'" in root or any(ch.isspace() for ch in root):
        raise InstanceRecordError(
            f"project_root 不安全（空/单引号/空白），无法按 G5 引用: {root!r}"
        )
    if "'" in filename or any(ch.isspace() for ch in filename) or "/" in filename \
            or "\\" in filename:
        raise InstanceRecordError(f"记录文件名不安全: {filename!r}")
    win_dir = f"{root}\\{REMOTE_RECORD_DIRNAME}"
    sftp_dir = win_dir.replace("\\", "/")
    win_file = f"{win_dir}\\{filename}"
    return {
        "win_dir": win_dir,
        "sftp_file": f"{sftp_dir}/{filename}",
        "win_file": win_file,
    }


def write_launch_instance_record(
    cfg: RemoteMachineConfig,
    transport: SshTransport,
    *,
    fingerprint: str,
    seat: str | None = None,
    local_dir: Path | str | None = None,
    steps: dict[str, Any],
) -> dict[str, Any] | None:
    """发射侧落实例记录（编排；L1/L2 共享单源）。

    流程：端口指纹查 ``pid|creation`` → **恰一命中**才可记录（零命中=
    进程已亡/指纹漂移；多命中=歧义——ADR-0004 错误/歧义/未命中永不回退，
    一律失败拒 attach）→ 构造记录 → 本地副本（runs 证据区）→ sftp 上传
    服务器 E 盘中间根。

    Returns
    -------
    dict | None
        ``None``＝成功（steps 已写入 ``instance_record``）；非 None＝
        失败片段（``{"reason": ...}``，调用方转失败信封并走 finally 清理）。
    """
    query = query_creation_by_fingerprint_command("ansysedt.exe", fingerprint)
    rc, out, err = transport.run_command(query, timeout_s=30.0)
    if rc != 0:
        steps["instance_record"] = {"query_rc": rc,
                                    "stderr_head": err[:160]}
        return {"reason": f"实例身份查询失败 rc={rc}（fail-closed 拒 attach）"}
    hits = parse_creation_query_output(out)
    if len(hits) != 1:
        steps["instance_record"] = {"query_rc": rc, "hits": len(hits)}
        return {
            "reason": (
                f"实例身份查询命中 {len(hits)} 例（恰一才可记录；"
                "零命中=进程已亡/多命中=歧义，ADR-0004 永不回退）"
            ),
        }
    pid, creation = hits[0]
    try:
        record = build_instance_record(
            port=cfg.hfss_grpc_port,
            pid=pid,
            process_create_time=creation,
            seat=seat,
            project_root=cfg.hfss_project_root,
        )
        directory = (
            Path(local_dir) if local_dir is not None
            else Path("runs") / "remote_instance_records"
        )
        written = write_instance_record(record, directory)
        paths = remote_record_paths(cfg.hfss_project_root,
                                    written["filename"])
        transport.run_command(
            f"New-Item -ItemType Directory -Force -Path "
            f"'{paths['win_dir']}' | Out-Null",
            timeout_s=20.0,
        )
        transport.upload_file(written["local_path"], paths["sftp_file"])
    except Exception as exc:  # 记录面任何失败=拒绝发射记录（fail-closed）
        steps["instance_record"] = {"error": type(exc).__name__}
        return {
            "reason": (
                f"实例记录构造/落盘失败 {type(exc).__name__}: "
                f"{str(exc)[:120]}（fail-closed 拒 attach）"
            ),
        }
    steps["instance_record"] = {
        "local_path": written["local_path"],
        "remote_path": paths["win_file"],
        "sftp_path": paths["sftp_file"],
        "pid": record["pid"],
        "process_create_time": record["process_create_time"],
        "uuid": record["uuid"],
        "seat": record["seat"],
    }
    return None


def verify_attached_instance(
    transport: SshTransport | None,
    record_path: Path | str | None,
    live_pid: int | None,
    *,
    steps: dict[str, Any],
) -> dict[str, Any]:
    """attach 侧核验编排：读记录 → SSH 查活实例创建时刻 → 纯函数判定。

    ``live_pid`` 来自 pyaedt ``Desktop.aedt_process_id``（gRPC 连接后
    服务端 ``GetProcessID()``）。任何 I/O 故障都折算进 fail-closed 判定
    （查询异常 → live_unverifiable 拒），绝不回退放行。
    """
    state, record = (
        load_instance_record(record_path)
        if record_path is not None else ("missing", None)
    )
    live_creation: str | None = None
    query_error: str | None = None
    if live_pid is not None and transport is not None:
        try:
            rc, out, _err = transport.run_command(
                query_creation_by_pid_command(int(live_pid)), timeout_s=30.0,
            )
            if rc == 0:
                hits = [c for p, c in parse_creation_query_output(out)
                        if p == int(live_pid)]
                if len(hits) == 1:
                    live_creation = hits[0]
                elif len(hits) > 1:
                    query_error = f"PID 查询命中 {len(hits)} 例（歧义）"
            else:
                query_error = f"PID 查询 rc={rc}"
        except Exception as exc:  # 传输层裸抛折算拒连（fail-closed）
            query_error = f"{type(exc).__name__}: {str(exc)[:120]}"
    elif live_pid is None:
        query_error = "desktop.aedt_process_id 不可得"
    else:
        query_error = "transport 不可用（无法核验活实例时刻）"
    verdict = judge_instance_identity(state, record, live_pid, live_creation)
    if query_error and verdict["verdict"] == "match":
        # 防御性兜底：判定面理应已把查不到时刻的活实例拒掉；到达此处
        # 说明内部不一致——按 fail-closed 翻拒，不凑绿（#122 同族）。
        verdict = {
            "verdict": "live_unverifiable", "allowed": False,
            "reason": f"内部不一致兜底拒连: {query_error}",
        }
    outcome: dict[str, Any] = dict(verdict)
    outcome.update({
        "record_state": state,
        "live_pid": live_pid,
        "live_creation": live_creation,
        "query_error": query_error,
    })
    steps["instance_verify"] = outcome
    return outcome


def judge_instance_identity(
    record_state: str,
    record: dict[str, Any] | None,
    live_pid: int | None,
    live_creation: str | None,
) -> dict[str, Any]:
    """实例身份判定（**纯函数**，五态钉+活实例不可验态；永不回退）。

    判定序（前态优先，逐态语义互斥）：

    1. ``record_missing``——记录缺失 → 拒；
    2. ``record_corrupt``——记录损坏（坏 JSON/形状不合/时刻不可解析/读取
       失败）→ 拒；
    3. ``live_unverifiable``——attach 侧拿不到活 PID → 拒；
    4. ``pid_mismatch``——记录 PID ≠ 活 PID（端口被他人实例占用）→ 拒；
    5. ``live_unverifiable``——PID 相等但活实例创建时刻查不到 → 拒；
    6. ``record_corrupt``——防御：ok 记录的时刻解析失败（加载器已挡，
       双保险）→ 拒；
    7. ``create_time_mismatch``——PID 相等、时刻不同键（PID 复用）→ 拒；
    8. ``match``——全要素一致 → 放行。

    Returns
    -------
    dict
        ``{"verdict", "allowed", "reason"}``；``allowed=True`` 仅 ``match``。
    """
    if record_state == "missing":
        return {"verdict": "record_missing", "allowed": False,
                "reason": "实例记录缺失（永不回退，ADR-0004）"}
    if record_state != "ok" or record is None:
        return {"verdict": "record_corrupt", "allowed": False,
                "reason": f"实例记录损坏（state={record_state}；永不回退）"}
    if live_pid is None:
        return {"verdict": "live_unverifiable", "allowed": False,
                "reason": "attach 侧活 PID 不可得（永不回退）"}
    if record["pid"] != int(live_pid):
        return {
            "verdict": "pid_mismatch", "allowed": False,
            "reason": (
                f"PID 不符（记录 {record['pid']} ≠ 活实例 {live_pid}）"
                "——端口可能被其他实例占用（永不回退）"
            ),
        }
    live_key = parse_creation_to_key(live_creation)
    if live_key is None:
        return {
            "verdict": "live_unverifiable", "allowed": False,
            "reason": "活实例创建时刻不可得/不可解析（永不回退）",
        }
    record_key = parse_creation_to_key(record["process_create_time"])
    if record_key is None:
        return {"verdict": "record_corrupt", "allowed": False,
                "reason": "记录创建时刻不可解析（防御拒，永不回退）"}
    if record_key != live_key:
        return {
            "verdict": "create_time_mismatch", "allowed": False,
            "reason": (
                "进程创建时刻不符（PID 复用嫌疑：记录 "
                f"{record['process_create_time']} ≠ 活实例 {live_creation}）"
                "——永不回退"
            ),
        }
    return {"verdict": "match", "allowed": True, "reason": None}
