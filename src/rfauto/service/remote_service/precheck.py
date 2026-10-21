"""机器探活/状态/license 预检/会话配置读面（remote_service T2 拆分子模块）。

零副作用读面：probe（TCP 连通性+时延）/status（+SSH 可达性，凭据缺失
如实 missing 不猜不试）、license_preflight（v1 调度面一级门，fail-closed）、
hfss_remote_session_config（settings 增量组装，无登记零行为变化契约）。
架构批 W3-S3 自 service/remote_service 巨石逐字节迁入（AU-1 facade，
函数体零改动）。
"""

from __future__ import annotations

import os
from typing import Any

from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteConfigError,
    RemoteMachineConfig,
    SshTransport,
    load_remote_machines,
    probe_machine,
    probe_port,
    resolve_machine,
)
from rfauto.service.envelope import ok_envelope

from .hfss_smoke import _attach_and_verify

# v1 调度面 license 感知诚实口径（随 license_preflight 信封落账）：
# 一级门=license 端口 TCP 探活+可选 attach health；lmutil/lmstat 席位级
# 查询未接线（服务器侧 lmutil 路径与调用形态仓内无先例——不臆造语法，
# 真机批接线后更新）。G6 教训：lmstat available≠键有效、端口 OPEN≠席位可用。
LICENSE_PREFLIGHT_SEAT_QUERY = (
    "UNVERIFIED（v1 一级门=license 端口 TCP 探活+可选 attach health 深检；"
    "lmutil/lmstat 席位级查询未接线——端口 OPEN≠席位可用，真机批补后更新）")


def remote_probe(machine: str | None = None) -> dict[str, Any]:
    """探活一台（或唯一登记）机器，返回 TCP 连通性 JSON 信封。

    无登记机器=``{"ok": True, "machines": []}``（零配置零行为变化）。
    """
    machines = load_remote_machines()
    if machine is None and not machines:
        return ok_envelope(machines=[])
    cfg = resolve_machine(machine, machines)
    result = probe_machine(cfg)
    return ok_envelope(machines=[result])


def remote_status(machine: str | None = None) -> dict[str, Any]:
    """探活 + SSH 认证可达性。

    SSH 判定规则（不猜不试）：

    - 凭据（用户名+密码或 key）缺失 → ``ssh_auth: "missing_credentials"``，
      不发起 SSH 连接；
    - 凭据在 → 真连一次取 ``uname`` 级命令回执判定
      ``ssh_auth: "ok" | "failed"``（通道失败如实上报错误类型）。
    """
    machines = load_remote_machines()
    if machine is None and not machines:
        return ok_envelope(machines=[])
    cfg = resolve_machine(machine, machines)
    result: dict[str, Any] = probe_machine(cfg)
    result["ssh"] = _ssh_status(cfg)
    return ok_envelope(machines=[result])


def _ssh_status(cfg: RemoteMachineConfig) -> dict[str, Any]:
    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    if not (has_user and has_secret):
        return {
            "auth": "missing_credentials",
            "hint": (
                "设置 RFAUTO_REMOTE_SSH_USER/RFAUTO_REMOTE_SSH_PASSWORD 或 "
                "configs/remote_machines.local.yaml（ssh_user/ssh_key_path）"
            ),
        }
    transport = SshTransport(cfg)
    try:
        transport.connect()
        rc, out, _err = transport.run_command("echo rfauto_remote_ok", timeout_s=15.0)
        return {
            "auth": "ok" if rc == 0 and out.strip() == "rfauto_remote_ok" else "failed",
            "rc": rc,
        }
    except Exception as exc:
        return {"auth": "failed", "error": type(exc).__name__}
    finally:
        transport.close()


def license_preflight(
    machine: str | None = None,
    *,
    deep: bool = False,
    probe_timeout_s: float = 3.0,
) -> dict[str, Any]:
    """发射前 license 预检（v1 调度面一级门，零副作用零凭据零写入）。

    口径（诚实边界，随信封 ``seat_level_query`` 落账）：

    - **一级门=license 端口 TCP 探活**：注册表 ``probe_ports`` 里语义名含
      ``license`` 的端口（sim_server=ansys_license 1055 / ads_license 27009）
      全 OPEN → ``verdict="PASS"``；任一不通或未登记 license 端口 →
      ``verdict="FAIL"``（fail-closed——调用方按 SKIP 记账不硬打）。
    - **席位级查询 UNVERIFIED**：lmutil/lmstat 的服务器侧路径与调用形态
      仓内无先例，本函数不臆造 lmstat 语法；端口 OPEN≠席位可用（G6 教训）。
    - **attach health 深检（``deep=True`` 可选）**：机器登记
      ``hfss.ansysedt_exe`` 且 license 门已过、gRPC 端口已有监听（有在跑
      会话）时，复用 ``_attach_and_verify`` 做一次 attach 健康读数——
      **信息面不进门**（grpcsrv 是 per-seat 拉起的，无会话在跑=预期态，
      深检缺席/失败都不翻 license 门）。

    Returns
    -------
    dict
        ``{"ok", "verdict": "PASS"/"FAIL"/"SKIP", "machine", "host",
        "reason", "gate", "seat_level_query", "steps"}``；无登记机器时
        ``{"ok": True, "skipped": True, "verdict": "SKIP", ...}``（本地
        路径零行为变化）。
    """
    machines = load_remote_machines()
    cfg = resolve_machine(machine, machines)
    if cfg is None:
        return ok_envelope(
            skipped=True,
            verdict="SKIP",
            machine=None,
            host=None,
            reason="无登记机器（本地路径不受影响）",
            gate={"kind": "tcp_license_ports", "all_open": False,
                     "closed": []},
            seat_level_query=LICENSE_PREFLIGHT_SEAT_QUERY,
            steps={},
        )
    steps: dict[str, Any] = {}
    lic_ports = {str(label): int(port)
                 for label, port in cfg.probe_ports.items()
                 if "license" in str(label).lower()}
    probe: dict[str, Any] = {}
    for label, port in sorted(lic_ports.items()):
        opened, latency_ms = probe_port(cfg.host, port,
                                        timeout_s=probe_timeout_s)
        probe[label] = {"port": port, "open": opened,
                        "latency_ms": round(latency_ms, 1)}
    steps["probe"] = probe
    closed = sorted(label for label, row in probe.items() if not row["open"])
    if not lic_ports:
        verdict = "FAIL"
        reason = ("机器未登记 license 探活端口（probe_ports 无 *license* "
                  "语义键）——fail-closed 不硬打")
    elif closed:
        verdict = "FAIL"
        detail = ", ".join(f"{label}({probe[label]['port']})"
                           for label in closed)
        reason = f"license 端口不可达: {detail}——fail-skip 不硬打"
    else:
        verdict = "PASS"
        reason = None

    if deep and verdict == "PASS" and cfg.hfss_ansysedt_exe:
        grpc_open, _ms = probe_port(cfg.host, cfg.hfss_grpc_port,
                                    timeout_s=probe_timeout_s)
        if grpc_open:
            attach_steps: dict[str, Any] = {}
            attach = _attach_and_verify(cfg, attach_steps)
            steps["attach_health"] = {
                "ok": bool(attach.get("ok")),
                "reason": attach.get("reason"),
                "steps": attach_steps,
                "note": "信息面不进门（深检失败不翻 license 门）",
            }
        else:
            steps["attach_health"] = {
                "skipped": True,
                "reason": (f"gRPC 端口 {cfg.hfss_grpc_port} 未开（无在跑会话）"
                           "——深检跳过，license 门不受影响"),
            }

    return {
        "ok": verdict == "PASS",
        "verdict": verdict,
        "machine": cfg.name,
        "host": cfg.host,
        "reason": reason,
        # A4 P1-1：all_open 与 verdict 对齐——空 license 端口表（fail-closed
        # FAIL）时 ``not closed`` 恒 True 曾与 verdict 自相矛盾（机读键会误
        # 放行）；诚实口径=探过端口且全开。
        "gate": {"kind": "tcp_license_ports",
                 "all_open": bool(lic_ports) and not closed,
                 "closed": closed},
        "seat_level_query": LICENSE_PREFLIGHT_SEAT_QUERY,
        "steps": steps,
    }


def hfss_remote_session_config(machine: str | None = None) -> dict[str, Any]:
    """HFSS 远程会话 settings 增量组装。

    消费链（审查分片 1 P3-2 口径对齐）：本函数只组装增量 dict、不写任何
    状态——调用方（v1 调度面）负责把 ``remote`` 值合并进
    ``HfssSession.connect(settings)`` 的 settings（session 消费的是
    ``settings["remote_machine"]`` 键）；生产链当前无注入点（v1 接线，
    已如实声明）。

    Returns
    -------
    dict
        ``{"ok": True, "remote": None}``（未登记/无配置——调用方按本地路径
        继续零行为变化）或 ``{"ok": True, "remote": {"remote_machine": <名>,
        "machine": <host>, "port": <grpc 端口>, "project_root": <服务器侧根>,
        "version": <AEDT 版本>, "ansysedt_exe": ...}}``。

        EC-5（2026-10-05）：注册表 hfss 节配置 ``cores: N``（≥1）时 remote
        dict 附加 ``"hfss_cores": N``（HfssSession.connect 的 HPC 旋钮键）；
        未配置时**键不存在**——消费方 settings 零改动（缺省全链路逐键不变）。

    project_root 未登记时显式拒绝（远程会话 project 路径必须落服务器侧
    已知目录，不能落本机语义路径）。
    """
    machines = load_remote_machines()
    if machine is None and not machines:
        return ok_envelope(remote=None)
    cfg = resolve_machine(machine, machines)
    if not cfg.hfss_project_root:
        raise RemoteConfigError(
            f"机器 {cfg.name!r} 未登记 hfss.project_root（远程会话 project "
            "路径必须落服务器侧目录）",
            details={"machine": cfg.name},
        )
    remote = {
        "remote_machine": cfg.name,
        "machine": cfg.host,
        "port": cfg.hfss_grpc_port,
        "project_root": cfg.hfss_project_root,
        "version": cfg.hfss_version,
        "ansysedt_exe": cfg.hfss_ansysedt_exe,
    }
    # EC-5 HPC 核数旋钮：仅显式配置时注入（缺省键不存在=零改动）。
    if cfg.hfss_cores > 0:
        remote["hfss_cores"] = cfg.hfss_cores
    return ok_envelope(remote=remote)
