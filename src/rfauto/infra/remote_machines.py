"""remote_machines —— 多机协同仿真资源注册表与通道（多机协同 WP v0）。

机器登记（configs/remote_machines.yaml，入库无凭据；
configs/remote_machines.local.yaml 覆盖凭据，gitignore）→ TCP 探活 →
SSH 传输（paramiko 懒加载，可选依赖 ``rfauto[remote]``）。

设计约束：

- **无配置=零行为变化**：配置文件不存在时 load 返回空表，adapter/service
  全部走本地路径，与无本模块时逐字节同行为。
- **凭据零入库**（铁律 8 同源）：本模块与登记文件永不持有密码；SSH 凭据
  只来自环境变量（``RFAUTO_REMOTE_SSH_USER``/``RFAUTO_REMOTE_SSH_PASSWORD``）
  或 gitignore 的 local 覆盖文件（``ssh_key_path``/``ssh_user``）。
- **可选依赖懒加载**（军规 8 同构）：paramiko 仅在 SshTransport 方法内
  import；未安装时显式报 RemoteTransportError（指明 pip install
  rfauto[remote]），不影响注册表/探活面。
- **探活零副作用**：probe 只做 TCP connect/close，不登录、不写文件。
- **主机钥 TOFU 折中**（E3-3，ge8e 审查批 W3，用户裁决）：缺省=AutoAdd
  语义+首连指纹落档告警（runs/ssh_host_fingerprints.json），指纹变更=
  error 醒目告警仍放行；``RFAUTO_SSH_STRICT=1``=严格档（无落档指纹/
  不匹配拒连）。全量严格（缺省即拒）等 mTLS 通道一起收口。

服务器侧版本口径：远程 AEDT 必须
与本机同版本（PyAEDT gRPC 客户端-服务端版本配对 + HFSS=对齐基准的数值
可比性）；服务器仅以 ``ansysedt -grpcsrv <port>`` 监听，无需装 pyaedt。
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.core.errors import RFAutoError

_LOG = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_GRPC_PORT",
    "DEFAULT_HFSS_MAX_PARALLEL",
    "DEFAULT_SSH_PORT",
    "ENV_REMOTE_SSH_PASSWORD",
    "ENV_REMOTE_SSH_USER",
    "ENV_SSH_STRICT",
    "SSH_HOST_FINGERPRINTS_FILENAME",
    "HfssMtlsCerts",
    "RemoteMachineConfig",
    "SshTransport",
    "decide_host_key_policy",
    "default_fingerprint_store_path",
    "default_remote_config_path",
    "fingerprint_of_key",
    "hfss_mtls_certs",
    "load_errors",
    "load_fingerprint_ledger",
    "load_remote_machines",
    "probe_machine",
    "probe_port",
    "record_fingerprint",
    "resolve_machine",
    "ssh_strict_enabled",
]

DEFAULT_CONFIG_FILENAME = "remote_machines.yaml"
DEFAULT_LOCAL_OVERRIDE_FILENAME = "remote_machines.local.yaml"
DEFAULT_SSH_PORT = 22
# 与 infra/config._DEFAULT_SETTINGS 的 grpc_port 同值（本地缺省端口口径）
DEFAULT_GRPC_PORT = 50051
# 远程真机并行度缺省闸（v1 调度面，--remote 路由发射侧消费）：2=实测可用档
# （HFSS 窗 --parallel 2 无 >1.5× 核争用漂移），服务器资源面 32C/128G/
# hfss_gui 100 席/单任务 ≤80GB——建议档 N≤4，加档前先实测单席 wall 漂移
# （docs/audit/server_invocation_playbook.md §2.4）。配置键 hfss.max_parallel。
DEFAULT_HFSS_MAX_PARALLEL = 2
ENV_REMOTE_SSH_USER = "RFAUTO_REMOTE_SSH_USER"
ENV_REMOTE_SSH_PASSWORD = "RFAUTO_REMOTE_SSH_PASSWORD"
# E3-3（ge8e 审查批 W3）：SSH 主机钥严格模式开关（flag 类，truthy 开启）
ENV_SSH_STRICT = "RFAUTO_SSH_STRICT"
#: 严格档 truthy 集（大小写不敏感，容忍首尾空白；其余一律缺省折中模式）
_SSH_STRICT_TRUTHY = frozenset({"1", "true", "yes", "on"})
#: 主机指纹账本文件名（落 <仓根>/runs/，结构见 :func:`load_fingerprint_ledger`）
SSH_HOST_FINGERPRINTS_FILENAME = "ssh_host_fingerprints.json"


class RemoteConfigError(RFAutoError):
    """远程机器注册表配置错误。"""


class RemoteTransportError(RFAutoError):
    """SSH 传输层错误（连接/认证/执行/sftp）。"""


class _HostKeyRejectedError(Exception):
    """主机钥策略拒绝（严格模式无记录/不匹配）——connect 特判透传处置指引。

    内部控制流异常：paramiko 缺装/异常包装路径不可见（connect 捕获后转
    :class:`RemoteTransportError` 并携带指引全文），不进模块公开面。
    """


@dataclass(frozen=True)
class HfssMtlsCerts:
    """HFSS 远程 gRPC mTLS 客户端证书三件（本地文件路径）。

    pyaedt 客户端口径（1.4.0 源码实测，desktop.py ``_get_grpcsrv_args``）：
    ``ANSYS_GRPC_CERTIFICATES`` env 指向**文件夹**，内含固定名三件
    ``ca.crt``/``client.crt``/``client.key``；本 dataclass 是配置侧的
    三路径形态（文件名不限），由 adapters/hfss_session 消费时规范化。
    """

    ca_cert: str
    client_cert: str
    client_key: str


@dataclass
class RemoteMachineConfig:
    """单台远程机器的登记信息。

    Attributes
    ----------
    name : str
        注册表键名（如 ``sim_host``）。
    host : str
        主机名或 IP（如 ``10.20.30.40``）。
    ssh_port : int
        SSH 端口（缺省 22）。
    ssh_user : str | None
        SSH 用户名（凭据面：env 或 local 覆盖文件提供，登记文件不得持有）。
    ssh_password : str | None
        SSH 密码（**仅** local 覆盖文件或 env 提供；登记 yaml 不得持有密码）。
    ssh_key_path : str | None
        SSH 私钥路径（local 覆盖文件提供；与密码二选一，key 优先）。
    hfss_version : str
        远程 AEDT 版本口径（如 ``2025.1``；必须与本机 pyaedt 配对版本一致）。
    hfss_grpc_port : int
        远程 ``ansysedt -grpcsrv`` 监听端口。
    hfss_project_root : str
        **服务器侧**项目工作根目录（远程会话中 project 路径按服务器文件
        系统解释；如 ``E:\\rfauto_remote``）。
    hfss_ansysedt_exe : str
        服务器侧 ansysedt.exe 绝对路径（SSH 拉起 grpcsrv 监听用）。
    hfss_max_parallel : int
        该机远程真机并行度上限（v1 调度面发射侧闸；缺省 2=实测可用档，
        playbook §2.4；战役驱动 --remote 路由时收敛 ``--parallel``）。
    hfss_ca_cert : str | None
        mTLS CA 证书本地路径（凭据面：local 覆盖文件提供；三键须同时
        配置或同时省略，缺一由 :func:`hfss_mtls_certs` fail-closed）。
    hfss_client_cert : str | None
        mTLS 客户端证书本地路径（同上）。
    hfss_client_key : str | None
        mTLS 客户端私钥本地路径（同上）。
    ads_hpeesof_dir : str
        服务器侧 ADS 安装根（hpeesofsim 远跑的 HPEESOF_DIR 前置）。
    probe_ports : dict[str, int]
        探活端口表（语义名→端口）。
    extra : dict
        其余键原样保留（向前兼容）。
    """

    name: str
    host: str
    ssh_port: int = DEFAULT_SSH_PORT
    ssh_user: str | None = None
    # E3-2（ge8e 审查批）：默认 dataclass 的 repr/str 会带出 ssh_password
    # 明文（exp3 实测双泄漏面）——凭据字段 repr=False，调试面其余字段保持。
    ssh_password: str | None = field(default=None, repr=False)
    ssh_key_path: str | None = None
    hfss_version: str = "2025.1"
    hfss_grpc_port: int = DEFAULT_GRPC_PORT
    hfss_project_root: str = ""
    hfss_ansysedt_exe: str = ""
    hfss_max_parallel: int = DEFAULT_HFSS_MAX_PARALLEL
    #: EC-5（2026-10-05）：HFSS HPC 核数旋钮（hfss 节 ``cores`` 键）。
    #: 0/缺省=未配置（会话 settings 零改动）；>0 时经
    #: hfss_remote_session_config 透传 HfssSession.connect（hfss_cores 键）。
    hfss_cores: int = 0
    hfss_ca_cert: str | None = None
    hfss_client_cert: str | None = None
    hfss_client_key: str | None = None
    ads_hpeesof_dir: str = ""
    probe_ports: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def default_remote_config_path() -> Path:
    """登记文件缺省路径：``configs/remote_machines.yaml``（仓根锚定）。"""
    return Path(__file__).resolve().parents[3] / "configs" / DEFAULT_CONFIG_FILENAME


def default_fingerprint_store_path() -> Path:
    """主机指纹账本缺省路径：``<仓根>/runs/ssh_host_fingerprints.json``。

    仓根锚定、**不走** runs_paths.runs_root 的 cwd 双根收敛语义：安全账本
    必须单点稳定，随 cwd 漂移会让 TOFU 基线分叉失效（#295 族反面教材）。
    """
    return Path(__file__).resolve().parents[3] / "runs" / SSH_HOST_FINGERPRINTS_FILENAME


def _host_key_id(host: str, port: int) -> str:
    """账本键形态：``host:port``。"""
    return f"{host}:{port}"


def fingerprint_of_key(key: Any) -> str:
    """主机公钥 → ``SHA256:<base64>`` 指纹（``ssh-keygen -l`` 同款，无 padding）。

    只消费 ``key.asbytes()``（duck-typing，单测用假 key 注入，零 paramiko
    依赖）；与 :func:`decide_host_key_policy` 同为策略逻辑纯函数化的载体。
    """
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def ssh_strict_enabled(environ: dict[str, str] | None = None) -> bool:
    """``RFAUTO_SSH_STRICT`` truthy 判定（纯函数，environ 可注入便于测试）。

    truthy 集 = {1, true, yes, on}（大小写不敏感，容忍首尾空白）；未设/空/
    其余值 = 缺省 TOFU 折中模式（落档+告警，不拒连）。
    """
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SSH_STRICT, "")).strip().lower() in _SSH_STRICT_TRUTHY


def decide_host_key_policy(
    recorded: str | None,
    current: str | None,
    strict: bool,
) -> tuple[str, str, bool]:
    """主机钥三态决策纯函数（E3-3 回归钉主载体；零 IO 零 paramiko）。

    Parameters
    ----------
    recorded : str | None
        账本已录指纹（None=首连/无记录）。
    current : str | None
        本次交换到的服务器指纹（None=不可得，如账本降级/键读取失败）。
    strict : bool
        ``RFAUTO_SSH_STRICT`` 严格档。

    Returns
    -------
    tuple[str, str, bool]
        ``(policy_name, warn_level, accept)`` 六态：

        ==== ====== ============ ========== ==============================
        状态  strict policy_name warn_level accept
        ==== ====== ============ ========== ==============================
        首连  False  autoadd      warning    True（放行+落档告警）
        一致  False  autoadd      none       True（静默）
        变更  False  autoadd      error      True（折中案：放行+醒目告警）
        首连  True   strict       error      False（拒绝+处置指引）
        一致  True   strict       none       True（已录匹配才连）
        变更  True   strict       error      False（拒绝）
        ==== ====== ============ ========== ==============================

    ``current is None``（指纹不可得）按"无法验证"分流：strict 拒绝
    （fail-closed）、缺省 warning 放行（降级告警，#105）。
    """
    if strict:
        if recorded is not None and current == recorded:
            return ("strict", "none", True)
        return ("strict", "error", False)
    if recorded is None or current is None:
        return ("autoadd", "warning", True)
    if current == recorded:
        return ("autoadd", "none", True)
    return ("autoadd", "error", True)


def load_fingerprint_ledger(path: str | Path) -> dict[str, Any]:
    """读主机指纹账本（``host:port`` → ``{fingerprint, first_seen}``）。

    文件不存在 = ``{}``（首连语义）；存在但不可读/非法 JSON/顶层非映射 =
    :class:`RemoteTransportError`——调用方按模式分流：严格档 fail-closed
    拒连、缺省档降级为仅告警（观测面不得挡主路径，#105）。
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RemoteTransportError(
            f"SSH 指纹账本不可读（{p}）: {type(exc).__name__}: {exc}",
            details={"path": str(p)},
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RemoteTransportError(
            f"SSH 指纹账本格式错误（{p}）：顶层必须是 JSON 映射",
            details={"path": str(p), "got_type": type(raw).__name__},
        )
    return raw


def record_fingerprint(
    path: str | Path,
    host: str,
    port: int,
    fingerprint: str,
    now: float | None = None,
    base: dict[str, Any] | None = None,
) -> str:
    """落档/更新一条主机指纹（原子 tmp+replace 写，跨进程 last-write-wins）。

    Parameters
    ----------
    base : dict | None
        调用方已装载的账本（connect 路径传入，避免重读与读写竞态窗口）；
        None=从 ``path`` 重读（损坏按 :func:`load_fingerprint_ledger`
        同款报错）。

    Returns
    -------
    str
        ``"created"``（首录）/``"updated"``（指纹变更换基线，first_seen
        随新基线刷新——变更事件在 error 日志留痕）/``"unchanged"``（已
        一致，不触发写盘）。
    """
    p = Path(path)
    key = _host_key_id(host, port)
    ledger = dict(base) if base is not None else dict(load_fingerprint_ledger(p))
    prior = ledger.get(key)
    prior_fp = prior.get("fingerprint") if isinstance(prior, dict) else None
    if prior_fp == fingerprint:
        return "unchanged"
    stamp = time.time() if now is None else now
    ledger[key] = {
        "fingerprint": fingerprint,
        "first_seen": datetime.fromtimestamp(stamp).isoformat(timespec="seconds"),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, p)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return "created" if prior_fp is None else "updated"


class _LedgerHostKeyPolicy:
    """TOFU 折中主机钥策略（paramiko duck-typing：``missing_host_key`` 回调）。

    paramiko ``SSHClient.connect`` 对不在其 known_hosts 的服务器键回调
    ``missing_host_key(client, hostname, key)``（本仓从不装载系统
    known_hosts，回调每次必达——指纹核对单源在本账本，不被用户
    known_hosts 短路）。缺省=AutoAdd 语义+落档；严格档=无记录/不匹配抛
    :class:`_HostKeyRejectedError`（connect 特判透传处置指引）。落档写
    失败 best-effort 告警（#105）；严格档 accept 仅发生在指纹一致场景
    （免写），无写失败面。
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        recorded: str | None,
        strict: bool,
        store_path: Path,
        ledger: dict[str, Any],
        ledger_ok: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.recorded = recorded
        self.strict = strict
        self.store_path = store_path
        self.ledger = ledger
        self.ledger_ok = ledger_ok

    def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
        current = fingerprint_of_key(key)
        policy_name, warn_level, accept = decide_host_key_policy(
            self.recorded, current, self.strict)
        if warn_level == "warning":
            if self.ledger_ok:
                _LOG.warning(
                    "SSH 首连 host=%s:%d 指纹=%s 已落档（TOFU——如非预期连接请核查）",
                    self.host, self.port, current,
                )
            else:
                _LOG.warning(
                    "SSH 指纹账本不可读（降级仅告警）host=%s:%d 指纹=%s"
                    "（TOFU——如非预期连接请核查）",
                    self.host, self.port, current,
                )
        elif warn_level == "error":
            _LOG.error(
                "SSH 主机钥变更 host=%s:%d 旧=%s 新=%s（疑似 MITM 或服务器重装）",
                self.host, self.port, self.recorded, current,
            )
        if not accept:
            reason = "无落档指纹" if self.recorded is None else "指纹不匹配"
            raise _HostKeyRejectedError(
                f"SSH 严格模式（RFAUTO_SSH_STRICT=1）拒绝连接 "
                f"host={self.host}:{self.port}（{reason}，新指纹={current}）"
                "——先以缺省模式连接一次落档指纹，或核对服务器身份"
            )
        if current is not None and current != self.recorded:
            # 放行且基线变化（首录/变更换基线）→ 落档（best-effort，#105）
            try:
                action = record_fingerprint(
                    self.store_path, self.host, self.port, current,
                    base=self.ledger,
                )
                _LOG.debug(
                    "SSH 指纹落档 host=%s:%d 动作=%s 策略=%s",
                    self.host, self.port, action, policy_name,
                )
            except Exception as exc:
                _LOG.warning(
                    "SSH 指纹落档失败（best-effort 不挡连接）host=%s:%d: "
                    "%s: %s",
                    self.host, self.port, type(exc).__name__, exc,
                )


def _parse_machine(name: str, raw: Any) -> RemoteMachineConfig:
    """单机器条目解析（缺失键走缺省；host 缺失=配置错误）。"""
    if not isinstance(raw, dict):
        raise RemoteConfigError(
            f"remote_machines 配置错误：机器 {name!r} 条目必须是映射",
            details={"got_type": type(raw).__name__},
        )
    host = raw.get("host", "")
    if not host:
        raise RemoteConfigError(
            f"remote_machines 配置错误：机器 {name!r} 缺少 host",
            details={"name": name},
        )
    known = {
        "host", "ssh_port", "ssh_user", "ssh_password", "ssh_key_path",
        "hfss_version", "hfss_grpc_port", "hfss_project_root",
        "hfss_ansysedt_exe", "ads_hpeesof_dir", "probe_ports",
        "ca_cert", "client_cert", "client_key",
    }
    hfss = raw.get("hfss") or {}
    ads = raw.get("ads") or {}
    probe_ports = raw.get("probe_ports")
    if not isinstance(probe_ports, dict):
        probe_ports = {}
    try:
        hfss_max_parallel = max(
            1, int(hfss.get("max_parallel", DEFAULT_HFSS_MAX_PARALLEL)))
    except (TypeError, ValueError):
        raise RemoteConfigError(
            f"remote_machines 配置错误：机器 {name!r} hfss.max_parallel "
            "必须是正整数",
            details={"name": name},
        ) from None
    # EC-5：hfss.cores（HPC 核数旋钮）——0/负/非整数一律归 0=未配置
    # （缺省零改动；非法值不炸注册表装载，旋钮生效性由 session 校验兜底）。
    try:
        hfss_cores = max(0, int(hfss.get("cores", 0) or 0))
    except (TypeError, ValueError):
        hfss_cores = 0
    return RemoteMachineConfig(
        name=name,
        host=str(host),
        ssh_port=int(raw.get("ssh_port", DEFAULT_SSH_PORT)),
        ssh_user=raw.get("ssh_user") or None,
        ssh_password=raw.get("ssh_password") or None,
        ssh_key_path=raw.get("ssh_key_path") or None,
        hfss_version=str(hfss.get("version", "2025.1")),
        hfss_grpc_port=int(hfss.get("grpc_port", DEFAULT_GRPC_PORT)),
        hfss_project_root=str(hfss.get("project_root", "")),
        hfss_ansysedt_exe=str(hfss.get("ansysedt_exe", "")),
        hfss_max_parallel=hfss_max_parallel,
        hfss_cores=hfss_cores,
        hfss_ca_cert=hfss.get("ca_cert") or None,
        hfss_client_cert=hfss.get("client_cert") or None,
        hfss_client_key=hfss.get("client_key") or None,
        ads_hpeesof_dir=str(ads.get("hpeesof_dir", "")),
        probe_ports={str(k): int(v) for k, v in probe_ports.items()},
        extra={k: v for k, v in raw.items() if k not in known
               and k not in ("hfss", "ads")},
    )


#: 最近一次 :func:`load_remote_machines` 的装载告警账本（AU-7 load_errors
#: 面同构，models/registry.py 先例）。E3-6①（ge8e 审查批）：local 覆盖
#: 文件存在但不可读/非法 YAML 不再静默跳过——根因记录于此并 logger.warning
#: 后继续（"无文件=正常"契约不变，"存在且坏"必须留痕）。每次调用前清空。
load_errors: list[str] = []


def load_remote_machines(
    config_path: str | Path | None = None,
) -> dict[str, RemoteMachineConfig]:
    """加载机器注册表。

    读取顺序：``config_path``（显式）> ``configs/remote_machines.yaml``，
    随后同目录 ``remote_machines.local.yaml`` 深合并覆盖（凭据面，gitignore）。

    文件存在但不可读（权限/被占用）或非法 YAML：记入 :data:`load_errors`
    并 warning 后跳过该文件（E3-6①），其余文件照常装载——故障不再表现为
    下游 "missing_credentials" 而无根因。

    Returns
    -------
    dict[str, RemoteMachineConfig]
        名称→配置。**文件不存在=空表**（无配置零行为变化契约）。
    """
    import yaml

    load_errors.clear()
    base = Path(config_path) if config_path is not None else default_remote_config_path()
    merged: dict[str, Any] = {}
    for path in (base, base.parent / DEFAULT_LOCAL_OVERRIDE_FILENAME):
        if not path.exists():
            continue
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            # E3-6①：原 contextlib.suppress(OSError) 静默跳过且 loaded 处于
            # 未绑定态（读失败时下一行 UnboundLocalError）——改为留痕后续行。
            record = f"{path.name}: {type(exc).__name__}: {exc}"
            load_errors.append(record)
            _LOG.warning("remote_machines 装载告警（%s 跳过）: %s", path, record)
            continue
        machines = loaded.get("machines") if isinstance(loaded, dict) else None
        if not isinstance(machines, dict):
            continue
        for name, raw in machines.items():
            name = str(name)
            if name in merged and isinstance(merged[name], dict) and isinstance(raw, dict):
                # local 覆盖面逐键深合并（凭据键覆盖，登记键保留）
                combined = dict(merged[name])
                for key, value in raw.items():
                    if isinstance(value, dict) and isinstance(combined.get(key), dict):
                        combined[key] = {**combined[key], **value}
                    else:
                        combined[key] = value
                merged[name] = combined
            else:
                merged[name] = raw

    return {
        name: _parse_machine(name, raw) for name, raw in sorted(merged.items())
    }


def resolve_machine(
    name: str | None,
    machines: dict[str, RemoteMachineConfig] | None = None,
) -> RemoteMachineConfig | None:
    """按名解析机器；``name=None`` 时返回唯一登记机器或 None。

    多台机器且未指名时显式报错（不猜默认），零台返回 None（本地路径）。
    """
    table = machines if machines is not None else load_remote_machines()
    if name is None:
        if len(table) == 1:
            return next(iter(table.values()))
        if len(table) > 1:
            names = ", ".join(sorted(table))
            raise RemoteConfigError(
                f"注册表有 {len(table)} 台机器，必须显式指名（{names}）",
                details={"machines": sorted(table)},
            )
        return None
    cfg = table.get(name)
    if cfg is None:
        raise RemoteConfigError(
            f"远程机器 {name!r} 未登记（可用：{', '.join(sorted(table)) or '无'}）",
            details={"name": name},
        )
    return cfg


def hfss_mtls_certs(cfg: RemoteMachineConfig) -> HfssMtlsCerts | None:
    """解析机器的 mTLS 证书面（fail-closed，缺一不静默降级 InsecureMode）。

    - 三键全缺 → ``None``（insecure 现行为，零变化）；
    - 部分配置 → :class:`RemoteConfigError`（三件必须同时配置或同时省略）；
    - 三键齐全 → 逐件存在性校验后返回 :class:`HfssMtlsCerts`
      （文件缺失同样显式报错，前置到 connect 之前而非 gRPC 握手期）。
    """
    triple = (
        ("ca_cert", cfg.hfss_ca_cert),
        ("client_cert", cfg.hfss_client_cert),
        ("client_key", cfg.hfss_client_key),
    )
    if all(not value for _key, value in triple):
        return None
    missing = [key for key, value in triple if not value]
    if missing:
        raise RemoteConfigError(
            f"机器 {cfg.name!r} mTLS 证书配置不完整：缺 {missing}——"
            "ca_cert/client_cert/client_key 三件必须同时配置或同时省略"
            "（缺一禁止静默降级 InsecureMode）",
            details={"machine": cfg.name, "missing": missing},
        )
    spec = HfssMtlsCerts(
        ca_cert=str(cfg.hfss_ca_cert),
        client_cert=str(cfg.hfss_client_cert),
        client_key=str(cfg.hfss_client_key),
    )
    missing_files = [
        str(p) for p in (spec.ca_cert, spec.client_cert, spec.client_key)
        if not Path(p).is_file()
    ]
    if missing_files:
        raise RemoteConfigError(
            f"机器 {cfg.name!r} mTLS 证书文件不存在：{missing_files}"
            "（fail-closed，不降级 InsecureMode）",
            details={"machine": cfg.name, "missing_files": missing_files},
        )
    return spec


def probe_port(host: str, port: int, timeout_s: float = 3.0) -> tuple[bool, float]:
    """单端口 TCP 探活。

    Returns
    -------
    tuple[bool, float]
        ``(open, latency_ms)``；连接被拒/超时 = ``(False, 耗时)``。
        零副作用（connect 后立即 close，不发送任何应用层数据）。
    """
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, (time.perf_counter() - start) * 1000.0
    except OSError:
        return False, (time.perf_counter() - start) * 1000.0


def probe_machine(
    cfg: RemoteMachineConfig,
    extra_ports: dict[str, int] | None = None,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    """机器探活：TCP 连通性 + 时延。

    Returns
    -------
    dict
        ``{"name", "host", "reachable", "ports": {语义名: {"port", "open",
        "latency_ms"}}, "probe_s"}``。
    """
    ports: dict[str, int] = {"ssh": cfg.ssh_port}
    ports.update(cfg.probe_ports)
    if extra_ports:
        ports.update(extra_ports)
    start = time.perf_counter()
    results: dict[str, Any] = {}
    for label, port in sorted(ports.items()):
        opened, latency_ms = probe_port(cfg.host, port, timeout_s=timeout_s)
        results[label] = {"port": port, "open": opened, "latency_ms": round(latency_ms, 1)}
    return {
        "name": cfg.name,
        "host": cfg.host,
        "reachable": any(r["open"] for r in results.values()),
        "ports": results,
        "probe_s": round(time.perf_counter() - start, 2),
    }


def _resolve_ssh_credentials(cfg: RemoteMachineConfig) -> dict[str, Any]:
    """凭据解析：local 覆盖（user/password/key）优先，env 兜底。

    密码只存 gitignored 的 local 覆盖文件或环境变量，绝不进 git/日志/
    异常消息；key 在位时 key 通道优先（password 仍透传作兜底）。
    """
    user = cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER) or None
    password = cfg.ssh_password or os.environ.get(ENV_REMOTE_SSH_PASSWORD) or None
    if cfg.ssh_key_path:
        return {"username": user, "key_filename": cfg.ssh_key_path,
                "password": password, "look_for_keys": False, "allow_agent": False}
    return {"username": user, "password": password,
            "look_for_keys": False, "allow_agent": False}


class SshTransport:
    """SSH/SFTP 传输（paramiko 懒加载）。

    用法::

        t = SshTransport(cfg)
        t.connect()
        rc, out, err = t.run_command("echo hi", timeout_s=30)
        t.upload_file(local, remote)
        t.download_file(remote, local)
        t.close()

    Parameters
    ----------
    fingerprint_store_path : str | Path | None
        主机指纹账本路径（E3-3）；None=:func:`default_fingerprint_store_path`
        （仓根 runs）。测试/多账本场景注入，生产路径不传。
    """

    def __init__(
        self,
        cfg: RemoteMachineConfig,
        connect_timeout_s: float = 10.0,
        fingerprint_store_path: str | Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.connect_timeout_s = connect_timeout_s
        # 路径入参第一行 Path() 收敛（#140：注解写 Path 不代表传的是 Path）
        self.fingerprint_store_path = (
            Path(fingerprint_store_path) if fingerprint_store_path is not None
            else default_fingerprint_store_path()
        )
        self._client: Any = None

    def _ensure_paramiko(self) -> Any:
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise RemoteTransportError(
                "SSH 通道需要 paramiko：pip install rfauto[remote]（或 "
                ".venv 内 python -m pip install paramiko）",
                details={"import_error": str(exc)},
            ) from exc
        return paramiko

    def _load_ledger_for_connect(
        self, strict: bool,
    ) -> tuple[dict[str, Any], str | None, bool]:
        """connect 前装载账本与已录指纹。

        Returns
        -------
        tuple[dict, str | None, bool]
            ``(ledger, recorded_fingerprint, ledger_ok)``；账本不可读时
            严格档抛（fail-closed）、缺省档降级为空账本+warning（#105）。
        """
        try:
            ledger = load_fingerprint_ledger(self.fingerprint_store_path)
        except RemoteTransportError as exc:
            if strict:
                raise RemoteTransportError(
                    "SSH 严格模式（RFAUTO_SSH_STRICT=1）指纹账本不可读"
                    "——fail-closed 拒连；修复或删除账本文件后重试",
                    details={
                        "path": str(self.fingerprint_store_path),
                        "cause": str(exc),
                    },
                ) from exc
            _LOG.warning("SSH 指纹账本不可读，降级为仅告警（缺省模式）: %s", exc)
            return {}, None, False
        entry = ledger.get(_host_key_id(self.cfg.host, self.cfg.ssh_port))
        recorded: str | None = None
        if isinstance(entry, dict):
            fp = entry.get("fingerprint")
            recorded = fp if isinstance(fp, str) and fp else None
        return ledger, recorded, True

    def connect(self) -> None:
        paramiko = self._ensure_paramiko()
        creds = _resolve_ssh_credentials(self.cfg)
        strict = ssh_strict_enabled()
        ledger, recorded, ledger_ok = self._load_ledger_for_connect(strict)
        policy = _LedgerHostKeyPolicy(
            host=self.cfg.host,
            port=self.cfg.ssh_port,
            recorded=recorded,
            strict=strict,
            store_path=self.fingerprint_store_path,
            ledger=ledger,
            ledger_ok=ledger_ok,
        )
        client = paramiko.SSHClient()
        # E3-3（ge8e 审查批 W3，用户裁决折中案）：裸 AutoAdd（TOFU 首连
        # MITM 不可检测）收口为账本策略——缺省=AutoAdd 语义+首连指纹落档
        # 告警、变更 error 醒目告警仍放行；RFAUTO_SSH_STRICT=1=无落档指纹/
        # 不匹配拒连（全量严格等 mTLS 通道一起）。
        client.set_missing_host_key_policy(policy)
        try:
            client.connect(
                self.cfg.host,
                port=self.cfg.ssh_port,
                timeout=self.connect_timeout_s,
                **creds,
            )
        except _HostKeyRejectedError as exc:
            with contextlib.suppress(Exception):
                client.close()
            raise RemoteTransportError(
                str(exc),
                details={"host": self.cfg.host, "ssh_port": self.cfg.ssh_port,
                         "strict": True},
            ) from exc
        except Exception as exc:
            with contextlib.suppress(Exception):
                client.close()
            raise RemoteTransportError(
                f"SSH 连接失败（host={self.cfg.host}:{self.cfg.ssh_port}）: "
                f"{type(exc).__name__}",
                details={"host": self.cfg.host, "ssh_port": self.cfg.ssh_port},
            ) from exc
        self._client = client

    def run_command(
        self, command: str, timeout_s: float = 60.0,
    ) -> tuple[int, str, str]:
        """远端执行命令，返回 ``(rc, stdout, stderr)``。

        凭据零泄漏：异常消息只含命令与退出码，不含连接参数。
        E3-6②（ge8e 审查批）：``recv_exit_status()`` 不受 exec_command 的
        channel timeout 约束（只约束流读）——sshd 停滞可无限挂起。守护线程
        包住等待 + ``join(timeout_s)``，超时关通道解阻塞并抛
        :class:`RemoteTransportError`（label 带 phase=recv_exit_status，
        fail-loud 不挂起）。
        """
        if self._client is None:
            raise RemoteTransportError("SSH 未连接，先 connect()")
        try:
            _stdin, stdout, stderr = self._client.exec_command(
                command, timeout=timeout_s,
            )
            channel = stdout.channel
            box: dict[str, Any] = {}

            def _wait_exit_status() -> None:
                try:
                    box["rc"] = channel.recv_exit_status()
                except Exception as exc:
                    box["exc"] = exc

            waiter = threading.Thread(
                target=_wait_exit_status, name="rfauto-ssh-exit-status",
                daemon=True)
            waiter.start()
            waiter.join(timeout_s)
            if "rc" not in box:
                # 超时或等待线程异常：关通道解阻塞流读（超时情形），再把
                # 真实原因抛出（label=phase 便于 remote_hfss_cleanup 链归因）。
                with contextlib.suppress(Exception):
                    channel.close()
                if "exc" in box:
                    raise box["exc"]
                raise RemoteTransportError(
                    f"远端命令 exit-status 等待超时（>{timeout_s}s；"
                    f"command 前 80 字符: {command[:80]!r}）",
                    details={"timeout_s": timeout_s,
                             "phase": "recv_exit_status"},
                )
            rc = box["rc"]
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return rc, out, err
        except RemoteTransportError:
            raise
        except Exception as exc:
            raise RemoteTransportError(
                f"远端命令执行失败: {type(exc).__name__}（command 前 80 字符: "
                f"{command[:80]!r}）",
                details={"timeout_s": timeout_s},
            ) from exc

    def upload_file(self, local_path: str | Path, remote_path: str) -> None:
        """本机 → 服务器 sftp 上传（远程路径按服务器文件系统解释）。"""
        if self._client is None:
            raise RemoteTransportError("SSH 未连接，先 connect()")
        sftp = self._client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
        except Exception as exc:
            raise RemoteTransportError(
                f"sftp 上传失败: {type(exc).__name__}",
                details={"remote_path": remote_path},
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                sftp.close()

    def download_file(self, remote_path: str, local_path: str | Path) -> None:
        """服务器 → 本机 sftp 下载（产物回拉主通道）。"""
        if self._client is None:
            raise RemoteTransportError("SSH 未连接，先 connect()")
        sftp = self._client.open_sftp()
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, str(local_path))
        except Exception as exc:
            raise RemoteTransportError(
                f"sftp 下载失败: {type(exc).__name__}",
                details={"remote_path": remote_path},
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                sftp.close()

    def close(self) -> None:
        """断开连接（幂等，best-effort）。"""
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        self._client = None

    def __enter__(self) -> SshTransport:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
