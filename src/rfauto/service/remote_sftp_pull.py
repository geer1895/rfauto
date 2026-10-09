"""remote_sftp_pull —— 远程求解产物 sftp 回拉执行体（多机协同尾程项 11）。

薄服务层（规则 4：JSON 进出）。职责链：**连接 → 远端产物清单 → 按白名单
拉取 → 完整性校验（大小+可选 sha256，失败重试一次）→ 本地落位
（resolve_runs_dir 双根收敛惯例）→ 回拉清单 JSON**。

口径与纪律：

- **远端路径来自 remote 配置**（注册表 ``hfss_project_root`` 等，按服务器
  文件系统解释）；服务器侧一切临时目录/中间文件的唯一合法根是
  ``E:\\rfauto_remote``（远程工作根约定）——本模块不臆造缺省
  远端根，``remote_dir`` 必须由调用方从配置给出。服务器云盘
  生产资料库（云盘同步目录）禁测试写入。
- **依赖**：sftp 通道复用 :class:`rfauto.infra.remote_machines.SshTransport`
  （paramiko 懒加载，可选依赖 ``rfauto[remote]``）——本模块零直接
  paramiko import，未装时经 SshTransport 的明确报错转为 error 信封。
- **测试/编排注入**：``transport`` 给定时直接消费且不负责连接/关闭生命周期
  （调用方所有）；``transport=None`` 时自建 SshTransport 并 connect/finally
  close。unit 门内一律走 fake transport（#139：零真连零网络）。
- **诚实口径**：远端缺文件=如实跳过+告警；校验失败重试一次后仍不过=该文件
  如实 ``failed``（不冒充成功，#122）；本地同名冲突=跳过+告警不覆盖。
  回拉清单 JSON 逐文件落账（远端/本地路径/字节数/sha256/状态）。
- **fail-closed**：清单枚举 rc≠0、清单行解析失败、路径越出产物目录、
  PowerShell 单引号注入面（G5）一律显式报错，不静默降级为空产物。

Returns
-------
dict
    成功链：``ok_envelope(verdict=..., machine=..., remote_dir=..., out_dir=...,
    files=[...], counts={...}, warnings=[...], manifest_path=...)``；
    内容失败（verdict=FAIL）走 ``error_envelope``（errors=逐文件原因）；
    skipped（无登记机器/凭据缺失）走 ``skipped_envelope(ok=False)``（与
    remote_hfss_l2_smoke 前置段同形）。
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteConfigError,
    RemoteMachineConfig,
    RemoteTransportError,
    SshTransport,
    load_remote_machines,
    resolve_machine,
)
from rfauto.infra.runs_paths import resolve_runs_dir
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

__all__ = [
    "L2_PRODUCT_PATTERNS",
    "MANIFEST_SCHEMA",
    "PULL_ATTEMPTS",
    "PULL_MANIFEST_NAME",
    "RemotePullError",
    "enumerate_remote_files",
    "pull_artifacts",
    "record_pull_manifest",
    "resolve_pull_out_dir",
    "sha256_file",
]

#: 回拉清单文件名（落 ``out_dir`` 根）。
PULL_MANIFEST_NAME = "pull_manifest.json"

#: 回拉清单 schema 版本（清单形状变更时升位）。
MANIFEST_SCHEMA = "remote_pull_manifest/1"

#: 单文件最大拉取次数（首次+校验失败重试一次；仍不过=如实 failed）。
PULL_ATTEMPTS = 2

#: L2 产物建议白名单（调用方经 ``include_patterns`` 显式选用；fnmatch 对
#: 远端文件名匹配）。``include_patterns=None``=不过滤（全量镜像，与
#: remote_oe_service._fetch_task_dir 全拉语义一致）。
L2_PRODUCT_PATTERNS: tuple[str, ...] = ("*.s2p", "*.csv", "*.json", "*.log")

_FILE_STATUSES = ("pulled", "skipped_exists", "missing_remote", "filtered",
                  "failed")


class RemotePullError(RuntimeError):
    """回拉链路错误（枚举失败/清单行解析失败/路径越界/引号注入面）。"""


def sha256_file(path: str | Path) -> str:
    """本地文件流式 sha256（小写十六进制；与 Get-FileHash 比较时双端 lower）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pull_out_dir(out_dir: str | Path | None = None) -> Path:
    """本地落位根解析（仓内 resolve_root 惯例：cwd 相对走 runs 双根收敛）。

    - ``None`` → ``runs/remote_pull/<YYYYMMDD_HHMMSS>``（经
      :func:`resolve_runs_dir` 收敛，chdir 仓内子目录不分叉，#295 族）；
    - 绝对路径 → 原样（测试/调用方显式注入）；
    - 相对路径 → 经 :func:`resolve_runs_dir` 收敛。
    """
    if out_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return resolve_runs_dir("runs/remote_pull") / stamp
    p = Path(out_dir)  # 路径入参第一行收敛（#140）
    if p.is_absolute():
        return p
    return resolve_runs_dir(p)


def _win_path(path: str) -> str:
    return str(path).replace("/", "\\")


def _ps_quote_guard(path: str, what: str) -> None:
    """PowerShell 单引号注入面守卫（G5 纪律：单引号内无法安全转义）。"""
    if "'" in str(path):
        raise RemotePullError(
            f"{what} 含单引号（G5 无法安全引用，拒绝执行）: {str(path)[:120]}")


def _listing_command(remote_dir: str) -> str:
    """远端产物清单命令（Windows 服务器口径，全程单引号零双引号）。

    输出行协议=``FullName|Length``（``'{0}|{1}' -f``）；Windows 文件名禁
    ``|``，rpartition 解析安全。
    """
    return (
        "Get-ChildItem -LiteralPath '" + _win_path(remote_dir) + "' -Recurse -File "
        "-ErrorAction SilentlyContinue | "
        "ForEach-Object { '{0}|{1}' -f $_.FullName, $_.Length }"
    )


def _test_path_command(remote_path: str) -> str:
    return f"Test-Path -LiteralPath '{_win_path(remote_path)}'"


def _hash_command(remote_path: str) -> str:
    return f"(Get-FileHash -LiteralPath '{_win_path(remote_path)}' -Algorithm SHA256).Hash"


def enumerate_remote_files(transport: Any, remote_dir: str) -> list[dict[str, Any]]:
    """枚举远端产物目录全文件（fail-closed）。

    Returns
    -------
    list[dict]
        逐文件 ``{"remote": 全路径(正斜杠), "remote_bytes": 声明字节数,
        "rel": 相对 remote_dir 的镜像相对路径}``。

    Raises
    ------
    RemotePullError
        remote_dir 含单引号 / 枚举 rc≠0 / 清单行非 ``path|size`` 形态
        （#331 观察面失真防线：解析失败如实报，不静默丢行）/ 路径越出
        产物目录 / 相对段含 ``..``（前缀检查的逃逸面，fail-closed）。
    """
    _ps_quote_guard(remote_dir, "remote_dir")
    root_win = _win_path(remote_dir)
    rc, out, err = transport.run_command(
        _listing_command(remote_dir), timeout_s=120.0)
    if rc != 0:
        raise RemotePullError(
            f"远端产物目录枚举失败 rc={rc}（fail-closed，不冒充空产物）: "
            f"{(err or '')[:120]}")
    prefix = root_win.lower().rstrip("\\") + "\\"
    artifacts: list[dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        path_s, sep, size_s = line.rpartition("|")
        if not sep or not size_s.isdigit():
            raise RemotePullError(
                f"远端清单行解析失败（非 path|size 形态）: {line[:120]}")
        f_win = path_s.replace("/", "\\")
        if not f_win.lower().startswith(prefix):
            raise RemotePullError(
                f"远端清单路径越出产物目录（fail-closed）: {f_win[:120]}")
        rel = f_win[len(root_win):].lstrip("\\/").replace("\\", "/")
        # 前缀检查挡不住 ``dir\..\..\x`` 形态（字符串上仍以根为前缀）——
        # 相对段含 ``..`` 一律 fail-closed（防本地落位越出 out_dir 镜像根）
        if any(seg == ".." for seg in rel.split("/")):
            raise RemotePullError(
                f"远端清单相对路径含 .. 段（fail-closed 防落位越界）: "
                f"{f_win[:120]}")
        artifacts.append({
            "remote": f_win.replace("\\", "/"),
            "remote_bytes": int(size_s),
            "rel": rel,
        })
    return artifacts


def _credentials_ready(cfg: RemoteMachineConfig) -> bool:
    """凭据齐备判定（remote_service 同款：env 或 local 覆盖，不猜不试）。"""
    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    return has_user and has_secret


def _single_attempt(
    transport: Any,
    artifact: dict[str, Any],
    local_path: Path,
    *,
    verify_sha256: bool,
) -> tuple[str | None, dict[str, Any]]:
    """单次拉取+校验。成功返回 ``(None, info)``；失败返回 ``(原因, {})``。"""
    transport.download_file(artifact["remote"], local_path)
    size = local_path.stat().st_size
    declared = artifact.get("remote_bytes")
    if declared is not None and size != declared:
        return f"size_mismatch: 远端 {declared}B vs 本地 {size}B", {}
    info: dict[str, Any] = {"bytes": size, "sha256": sha256_file(local_path)}
    if verify_sha256:
        rc, out, _err = transport.run_command(
            _hash_command(artifact["remote"]), timeout_s=120.0)
        if rc != 0:
            return "remote_hash_unavailable: Get-FileHash 非零退出", {}
        remote_hash = out.strip().lower()
        if remote_hash != info["sha256"]:
            return (f"sha256_mismatch: 远端 {remote_hash[:12]}… vs 本地 "
                    f"{info['sha256'][:12]}…"), {}
    return None, info


def _download_verify(
    transport: Any,
    artifact: dict[str, Any],
    local_path: Path,
    *,
    verify_sha256: bool,
) -> tuple[str, dict[str, Any]]:
    """拉取+校验，失败重试一次（:data:`PULL_ATTEMPTS`）；失败路径清半截产物。"""
    attempts = 0
    last_reason = "unreachable"
    while attempts < PULL_ATTEMPTS:
        attempts += 1
        try:
            reason, info = _single_attempt(
                transport, artifact, local_path, verify_sha256=verify_sha256)
        except Exception as exc:  # 传输/落盘异常按本次失败计（重试一次）
            reason, info = f"download_error: {type(exc).__name__}", {}
        if reason is None:
            info["attempts"] = attempts
            return "pulled", info
        last_reason = reason
        with contextlib.suppress(OSError):
            local_path.unlink(missing_ok=True)
    return "failed", {"attempts": attempts, "error": last_reason}


def pull_artifacts(
    machine: str | None = None,
    *,
    remote_dir: str,
    remote_files: list[str] | None = None,
    out_dir: str | Path | None = None,
    include_patterns: list[str] | tuple[str, ...] | None = None,
    verify_sha256: bool = False,
    transport: Any = None,
) -> dict[str, Any]:
    """sftp 回拉执行体：清单→白名单→拉取→校验→落位→回拉清单 JSON。

    Parameters
    ----------
    machine : str, optional
        注册表机器名（``transport=None`` 时必经解析；``None``=唯一登记机器，
        多台未指名显式报错）。``transport`` 注入时仅作清单落账标签。
    remote_dir : str
        远端产物目录（来自 remote 配置，按服务器文件系统解释；枚举模式根）。
    remote_files : list[str], optional
        显式远端文件清单（调用方已知产物路径，如 L2 的 .s2p）——给定时跳过
        目录枚举，逐文件 Test-Path 守卫后**扁平落位**到 ``out_dir`` 根；
        远端缺文件=如实 ``missing_remote`` 跳过+告警。
    out_dir : str | Path, optional
        本地落位根（缺省 ``runs/remote_pull/<时间戳>``，resolve_root 惯例）。
    include_patterns : sequence[str], optional
        文件名白名单（fnmatch）；``None``=不过滤。可选用
        :data:`L2_PRODUCT_PATTERNS`。未命中文件=``filtered`` 如实落账不拉取。
    verify_sha256 : bool
        远端 sha256 校验（Get-FileHash 逐文件；缺省只做大小校验）。
    transport : optional
        注入的 SSH 通道（必须已 connect；调用方所有，本函数不 close）；
        ``None``=自建 :class:`SshTransport` 并管理 connect/close 生命周期。

    Returns
    -------
    dict
        见模块 docstring。``verdict``：``FAIL``（有 failed 或零产物）/
        ``PARTIAL``（有 missing_remote 但有产物）/ ``PASS``（全部目标文件
        pulled 或本地已存在）。
    """
    machine_label: str | None = machine
    if not str(remote_dir or "").strip():
        return error_envelope(
            "remote_dir 缺失（远端产物目录必须由调用方从 remote 配置给出）",
            stage="validate")
    try:
        _ps_quote_guard(remote_dir, "remote_dir")
    except RemotePullError as exc:
        return error_envelope(str(exc), stage="validate", remote_dir=remote_dir)

    owner = transport is None
    cfg: RemoteMachineConfig | None = None
    t = transport
    if owner:
        machines = load_remote_machines()
        if machine is None and not machines:
            return skipped_envelope(
                "无登记机器（本地路径零行为变化）", ok=False, machine=None)
        try:
            cfg = resolve_machine(machine, machines)
        except RemoteConfigError as exc:
            return error_envelope(str(exc), stage="resolve_machine")
        if cfg is None:
            return skipped_envelope(
                "无登记机器（本地路径零行为变化）", ok=False, machine=None)
        machine_label = cfg.name
        if not _credentials_ready(cfg):
            return skipped_envelope(
                "SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 local 覆盖）",
                ok=False, machine=machine_label,
                steps={"ssh": {"auth": "missing_credentials"}},
            )

    out_path = resolve_pull_out_dir(out_dir)
    warnings: list[str] = []
    files_out: list[dict[str, Any]] = []
    manifest_path: str | None = None
    try:
        if owner:
            t = SshTransport(cfg)  # type: ignore[arg-type]
            t.connect()

        if remote_files:
            artifacts = []
            for rf_path in remote_files:
                rf_norm = str(rf_path).replace("\\", "/")
                _ps_quote_guard(rf_norm, "remote file")
                rc, out, _err = t.run_command(
                    _test_path_command(rf_norm), timeout_s=30.0)
                if rc != 0:
                    raise RemotePullError(
                        f"远端存在性探测失败 rc={rc}（fail-closed）: {rf_norm[:120]}")
                if out.strip() != "True":
                    warnings.append(f"远端缺文件，如实跳过: {rf_norm}")
                    files_out.append({
                        "remote": rf_norm,
                        "local": str(out_path / Path(rf_norm).name),
                        "status": "missing_remote",
                    })
                    continue
                artifacts.append({
                    "remote": rf_norm,
                    "remote_bytes": None,
                    "rel": Path(rf_norm).name,
                })
        else:
            artifacts = enumerate_remote_files(t, remote_dir)

        patterns = (
            tuple(str(p) for p in include_patterns)
            if include_patterns else None
        )
        for art in artifacts:
            name = Path(art["remote"]).name
            if patterns and not any(
                    fnmatch.fnmatch(name.lower(), pat.lower())
                    for pat in patterns):
                files_out.append({
                    "remote": art["remote"],
                    "local": str(out_path / art["rel"]),
                    "status": "filtered",
                })
                continue
            local_path = out_path / art["rel"]
            if local_path.exists():
                warnings.append(f"本地已存在同名文件，跳过不覆盖: {local_path}")
                files_out.append({
                    "remote": art["remote"],
                    "local": str(local_path),
                    "status": "skipped_exists",
                })
                continue
            status, payload = _download_verify(
                t, art, local_path, verify_sha256=verify_sha256)
            entry: dict[str, Any] = {
                "remote": art["remote"],
                "local": str(local_path),
                "status": status,
            }
            entry.update(payload)
            files_out.append(entry)
    except RemotePullError as exc:
        return error_envelope(
            str(exc), stage="pull", machine=machine_label,
            remote_dir=remote_dir, out_dir=str(out_path),
            warnings=warnings, files=files_out)
    except RemoteTransportError as exc:
        return error_envelope(
            f"回拉连接失败: {exc}", stage="connect", machine=machine_label,
            remote_dir=remote_dir, out_dir=str(out_path))
    except Exception as exc:  # fail-closed：链路裸抛也落失败信封（L2 同构）
        return error_envelope(
            f"回拉链路异常: {type(exc).__name__}: {str(exc)[:160]}",
            stage="pull", machine=machine_label, remote_dir=remote_dir,
            out_dir=str(out_path), warnings=warnings, files=files_out)
    finally:
        if owner and t is not None:
            t.close()

    counts = {k: 0 for k in _FILE_STATUSES}
    for f in files_out:
        counts[f["status"]] = counts.get(f["status"], 0) + 1

    manifest_env = record_pull_manifest(
        out_path, files=files_out, machine=machine_label,
        remote_dir=remote_dir, warnings=warnings)
    if not manifest_env.get("ok"):
        return error_envelope(
            manifest_env.get("errors"), stage="manifest",
            machine=machine_label, remote_dir=remote_dir,
            out_dir=str(out_path), files=files_out, counts=counts,
            warnings=warnings)
    manifest_path = str(manifest_env["path"])

    if counts["failed"] or (counts["pulled"] == 0
                            and counts["skipped_exists"] == 0):
        verdict = "FAIL"
    elif counts["missing_remote"]:
        verdict = "PARTIAL"
    else:
        verdict = "PASS"

    common = dict(
        verdict=verdict,
        machine=machine_label,
        remote_dir=remote_dir,
        out_dir=str(out_path),
        files=files_out,
        counts=counts,
        warnings=warnings,
        manifest_path=manifest_path,
    )
    if verdict == "FAIL":
        errors = [
            f"{f['remote']}: {f['error']}"
            for f in files_out if f["status"] == "failed"
        ]
        if not errors:
            errors = ["零产物回拉（pulled=0，不冒充成功）"]
        return error_envelope(errors, **common)
    return ok_envelope(**common)


def record_pull_manifest(
    out_dir: str | Path,
    *,
    files: list[dict[str, Any]],
    machine: str | None = None,
    remote_dir: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """写回拉清单 JSON（纯本地，零网络）并返回 ok 信封。

    逐文件行键=``remote / local / bytes / sha256 / status``（可选
    ``attempts / error``）；``bytes``/``sha256`` 缺失且本地文件在位时自动
    回填（stat + 流式 sha256）——薄接线点（如 L2 单文件回拉）只需给
    remote/local/status 三键。

    Returns
    -------
    dict
        ``ok_envelope(path=<清单路径>, counts=..., machine=..., remote_dir=...)``；
        写盘失败走 ``error_envelope``（清单是回拉的记账产物，fail-closed）。
    """
    out_path = resolve_pull_out_dir(out_dir)
    rows: list[dict[str, Any]] = []
    for f in files:
        row = dict(f)
        local = Path(row["local"]) if row.get("local") else None
        if row.get("bytes") is None and local is not None and local.is_file():
            row["bytes"] = local.stat().st_size
        if (not row.get("sha256") and local is not None and local.is_file()
                and row.get("status") != "missing_remote"):
            row["sha256"] = sha256_file(local)
        clean: dict[str, Any] = {
            "remote": row.get("remote"),
            "local": row.get("local"),
            "bytes": row.get("bytes"),
            "sha256": row.get("sha256"),
            "status": row.get("status"),
        }
        for opt in ("attempts", "error"):
            if row.get(opt) is not None:
                clean[opt] = row[opt]
        rows.append(clean)

    counts = {k: 0 for k in _FILE_STATUSES}
    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] = counts.get(status, 0) + 1

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "machine": machine,
        "remote_dir": remote_dir,
        "out_dir": str(out_path),
        "counts": counts,
        "warnings": list(warnings or []),
        "files": rows,
    }
    try:
        out_path.mkdir(parents=True, exist_ok=True)
        mpath = out_path / PULL_MANIFEST_NAME
        # 原子写（同目录临时文件+os.replace）：清单是回拉的记账产物
        # （fail-closed），半写崩溃态不落正式清单档
        tmp = mpath.with_name(mpath.name + ".tmp")
        tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        os.replace(tmp, mpath)
    except OSError as exc:
        return error_envelope(
            f"回拉清单写入失败: {exc}", stage="manifest",
            out_dir=str(out_path))
    return ok_envelope(
        path=str(mpath), counts=counts, machine=machine, remote_dir=remote_dir)
