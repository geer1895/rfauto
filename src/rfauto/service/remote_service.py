"""remote_service —— 多机协同仿真资源服务面（多机协同 WP v0）。

薄服务层（规则 4：JSON 进出，CLI/MCP 是薄壳）。能力：

- ``remote_probe``：机器探活（TCP 连通性+时延，零副作用零凭据）。
- ``remote_status``：探活 + SSH 可达性判定（凭据缺失如实
  ``ssh_auth: missing_credentials``，不猜不试密码）。
- ``license_preflight``：发射前 license 预检（v1 调度面一级门）——license
  端口 TCP 探活（注册表 ``probe_ports`` 语义名含 ``license`` 键）+
  可选 attach health 深检（信息面不进门）；席位级 lmstat 查询登记
  UNVERIFIED（端口 OPEN≠席位可用，G6 教训）。
- ``hfss_remote_session_config``：组装 HFSS 远程会话 settings 增量
  （``remote_machine`` 键），供调用方（v1 调度面）合并进 connect
  settings——HfssSession 消费的是 ``settings["remote_machine"]`` 键，
  本函数不直接写任何状态——无登记返回 ``{"ok": True, "remote": None}``
  （无配置零行为变化契约）。
- ``remote_hfss_smoke``：L1 attach 冒烟编排（真机 opt-in，env
  ``RFAUTO_REMOTE_SMOKE=1`` 门；#139/df4⑥ 真跑集成测试规矩——unit 门
  内只跑 mock 路径，绝不真连网）。
- ``remote_hfss_l2_smoke``：L2 求解冒烟编排（远程建模→求解→Touchstone
  回拉→判读；opt-in 门与共享前置段同 L1）。
- ``remote_mutex_command``/``remote_mutex_precheck``：#261 每机互斥预检
  **共享单源**（X4 批自 remote_oe_service._remote_mutex 提升泛化）——
  进程指纹直查=权威判据 + 服务器探针 census mutex 行=旁证；三通道
  （HFSS gRPC/ADS hpeesofsim/openEMS runner）同构复用，指纹按通道语义词
  分（OE=python runner 家族 / ADS=hpeesofsim / HFSS=本机注册端口 grpcsrv）。

通道拓扑：HFSS gRPC 本机客户端→服务器 ``ansysedt -grpcsrv``；文件走
SSH sftp（服务器云盘 SMB 为生产资料库，禁测试写入——远程资源说明 §11.7）。
"""

from __future__ import annotations

import contextlib
import os
import re
import uuid
from typing import Any

from rfauto.adapters.hfss_session import remote_session_switches
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
from rfauto.service.envelope import ok_envelope, skipped_envelope

__all__ = [
    "LICENSE_PREFLIGHT_SEAT_QUERY",
    "REMOTE_SMOKE_ENV",
    "hfss_remote_session_config",
    "license_preflight",
    "remote_hfss_cleanup",
    "remote_hfss_l2_smoke",
    "remote_hfss_smoke",
    "remote_mutex_command",
    "remote_mutex_precheck",
    "remote_probe",
    "remote_status",
]

REMOTE_SMOKE_ENV = "RFAUTO_REMOTE_SMOKE"

# v1 调度面 license 感知诚实口径（随 license_preflight 信封落账）：
# 一级门=license 端口 TCP 探活+可选 attach health；lmutil/lmstat 席位级
# 查询未接线（服务器侧 lmutil 路径与调用形态仓内无先例——不臆造语法，
# 真机批接线后更新）。G6 教训：lmstat available≠键有效、端口 OPEN≠席位可用。
LICENSE_PREFLIGHT_SEAT_QUERY = (
    "UNVERIFIED（v1 一级门=license 端口 TCP 探活+可选 attach health 深检；"
    "lmutil/lmstat 席位级查询未接线——端口 OPEN≠席位可用，真机批补后更新）")

# ─── L2 求解冒烟常量（几何单一事实源=docs/templates/mline/meta.yaml；
#     材料单一事实源=configs/materials.yaml rogers4350b_h0.508；
#     线宽/εeff 为 skrf HJ 精算（core/synthesis.py，#1c 禁沿用毫米数） ───
L2_W_MM = 1.113            # nominal_params.w_mm（HJ 50Ω@2.5GHz 精算 1.1134）
L2_LEN_MM = 40.0           # nominal_params.line_len_mm（=S21 参考面跨度，见判据④）
L2_ER = 3.66               # substrate.er
L2_TAND = 0.0037           # materials.yaml loss_tangent
L2_H_MM = 0.508            # substrate.h_mm
L2_F0_GHZ = 2.5            # meta.yaml f0_ghz
L2_BOARD_W_MM = 24.0       # 板宽=空气盒宽（波端口满截面，见 _l2_model_solve_export）
L2_AIR_TOP_MM = 4.0        # 空气盒顶高（≈8h，场衰减 e^{-π·Δ/h} 足够）
L2_F_START_GHZ = 2.0       # 扫频窗（覆盖 f0±0.5GHz）
L2_F_STOP_GHZ = 2.8
L2_N_POINTS = 41
L2_SPAN_M = L2_LEN_MM * 1e-3   # S21 相位斜率参考面跨度（端口面=线端，无馈线延伸）
# 判据④窗口（#122 预声明）：HJ 预报 εeff=2.8526，窗 ±0.25 覆盖端口馈电
# 效应/参考面小偏差余量（#364 口径已按端口面间距 40mm 取）
L2_EFF_EXPECT = 2.8526
L2_EFF_WINDOW = (2.60, 3.10)
L2_S11_GATE_DB = -10.0     # 判据②
L2_S21_GATE_DB = -1.0      # 判据③
_C_M_S = 299792458.0       # 真空光速（εeff 反演用）

# ─── #261 每机互斥预检共享单源（X4 批自 remote_oe_service._remote_mutex
#     提升泛化；三通道同构复用，指纹按通道语义词分） ────────────────────────

#: 命中行协议形态（remote_mutex_command 产出 ``pid|commandline``）
_MUTEX_HIT_LINE_RE = re.compile(r"^\d+\|")


def remote_mutex_command(process_name: str, fingerprint: str) -> str:
    """#261 服务器侧互斥探针命令（PS 原生零双引号；命中行=pid|commandline）。

    G5 纪律：``$_`` 管道经 paramiko 直达远端 PS（无本地 shell 层展开），
    全程单引号零双引号；指纹为正则（调用方负责点号等元字符转义）。
    三通道单源：OE=``("python.exe", "_rfauto_runner|simulation\\.py|...")``、
    ADS=``("hpeesofsim.exe", "hpeesofsim")``、HFSS=``("ansysedt.exe",
    "grpcsrv.*:<port>:")``（端口域=per-seat gRPC 语义下只挡本注册端口
    实例，不误伤他端口合法会话）。
    """
    return (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -eq '{process_name}' -and "
        f"$_.CommandLine -match '{fingerprint}' }} | "
        "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"
    )


def remote_mutex_precheck(
    transport: SshTransport,
    work_root: str | None,
    *,
    process_name: str,
    fingerprint: str,
) -> dict[str, Any]:
    """互斥预检（#261 每机互斥，三通道共享单源）：进程指纹直查=权威判据
    + 服务器探针（``<work_root>\\kit\\06_tools\\run_server_probe.ps1``）
    census mutex 行=旁证。直查 rc≠0（验不了）→ busy=True fail-closed。
    命中=候跑，**禁止代杀**（本模块无任何杀进程命令；调用方不得在候跑
    路径触发按指纹杀进程的清理）。

    命中行按协议形态严格解析（``pid|commandline``，:data:`_MUTEX_HIT_LINE_RE`
   ）——探针 stdout 里的非协议行（计数、census 表头等）不误判为进程命中；
    真实进程行恒为 ``数字|`` 前缀，零漏判。

    旁证解析（2026-10-01 真机输出实证）：探针 census **表头行**含 "mutex"
    字样（"current solver-process census (#261 mutex precheck)"）而值行
    形态为 "mutex CLEAR" / "BUSY: PID=..."（后者不含 mutex 字样）——按
    「含 busy / 含 mutex 且非 clear 且非表头」双扫描判忙，防表头行假阳性
    永久堵门。``work_root`` 未登记或含单引号/空白（无法安全引用，G5）时
    旁证跳过如实登记——权威直查不内嵌路径，不受影响。

    Returns
    -------
    dict
        ``{"busy", "fail_closed", "hits", "probe", "reason"}``；调用方
        约定：busy=True → 候跑 SKIP 不发射。
    """
    rc, out, err = transport.run_command(
        remote_mutex_command(process_name, fingerprint), timeout_s=30.0)
    hits = [
        ln.strip() for ln in out.splitlines()
        if _MUTEX_HIT_LINE_RE.match(ln.strip())
    ]
    wr = str(work_root or "").replace("/", "\\")
    mutex_lines: list[str] = []
    if wr and "'" not in wr and not any(ch.isspace() for ch in wr):
        probe_cmd = (
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            f"{wr}\\kit\\06_tools\\run_server_probe.ps1")
        prc, pout, perr = transport.run_command(probe_cmd, timeout_s=180.0)
        low = [ln.strip().lower() for ln in pout.splitlines() if ln.strip()]
        mutex_lines = [ln for ln in low if "mutex" in ln]
        probe: dict[str, Any] = {
            "rc": prc, "mutex_lines": pout.splitlines()[-40:],
            "output_tail": pout[-400:], "stderr_head": perr[:200],
        }
        probe_busy = (
            any("busy" in ln for ln in low)
            or any("mutex" in ln and "clear" not in ln
                   and "census" not in ln and "precheck" not in ln
                   for ln in mutex_lines)
        )
    else:
        probe = {"skipped": True,
                 "reason": ("work_root 未登记或含单引号/空白（G5 无法安全"
                            "引用）——census 旁证跳过，指纹直查=权威不受"
                            "影响")}
        probe_busy = False
    if rc != 0:
        return {"busy": True, "fail_closed": True, "hits": [], "probe": probe,
                "reason": (f"互斥进程查询失败 rc={rc}（验不了=不发射，"
                           f"fail-closed）{err[:120]}")}
    if hits:
        reason = f"互斥命中 {len(hits)} 例=候跑（#261，禁止代杀）: {hits[0][:80]}"
    elif probe_busy:
        bad = [ln for ln in mutex_lines if "clear" not in ln][:1]
        detail = bad[0] if bad else "BUSY 行在档"
        reason = f"互斥旁证非 CLEAR=候跑（run_server_probe: {detail}）"
    else:
        reason = None
    return {"busy": bool(hits or probe_busy), "fail_closed": False,
            "hits": hits, "probe": probe, "reason": reason}


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
      ``license`` 的端口（sim_host=ansys_license 1055 / ads_license 27009）
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
        "gate": {"kind": "tcp_license_ports", "all_open": not closed,
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
    五百三十三已如实声明）。

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


def remote_hfss_smoke(
    machine: str | None = None,
    grpc_wait_s: float = 60.0,
) -> dict[str, Any]:
    """L1 attach 冒烟（**真机 opt-in**：env ``RFAUTO_REMOTE_SMOKE=1`` 门）。

    编排：探活 → SSH 拉 ``ansysedt -grpcsrv <port>``（凭据缺失如实 unknown，
    不猜）→ 本机 pyaedt Desktop/Hfss attach（版本配对断言）→ health_check →
    停机清理（本机 release_desktop finally + 服务器侧 ``remote_hfss_cleanup``
    兜底，P2-1 与 L2 同构——launch 成功后的任何失败路径都收掉服务器侧
    ansysedt 与 schtasks 任务，#265 孤儿桌面铁律）。

    unit 门内（env 未设）直接拒绝执行——真机绝不混进测试（df4⑥）。
    """
    if os.environ.get(REMOTE_SMOKE_ENV) != "1":
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                f"真机冒烟需显式 opt-in：{REMOTE_SMOKE_ENV}=1（unit 门零真机）"
            ),
        }
    machines = load_remote_machines()
    if machine is None and not machines:
        return {"ok": False, "skipped": True, "reason": "无登记机器"}
    cfg = resolve_machine(machine, machines)
    steps: dict[str, Any] = {"probe": probe_machine(cfg)}

    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    if not (has_user and has_secret):
        steps["ssh"] = {"auth": "missing_credentials"}
        return {
            "ok": False,
            "skipped": True,
            "reason": "SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 local 覆盖）",
            "steps": steps,
        }

    if not cfg.hfss_ansysedt_exe:
        return {
            "ok": False,
            "skipped": True,
            "reason": "机器未登记 hfss.ansysedt_exe（无法拉起 grpcsrv 监听）",
            "steps": steps,
        }

    # SSH 拉起 ansysedt -grpcsrv：Win32-OpenSSH 的 sshd 把会话内进程放进
    # job object，通道关闭整树被杀（Start-Process 分离也逃不出）——持久
    # 进程必须走 Task Scheduler（schtasks /run 启动的进程在服务侧 job 外）。
    # 流程：sftp 传 .bat 到服务器侧工作根 → schtasks 注册 once 任务 →
    # /run 触发 → 轮询 gRPC 端口 → 本机 attach →（调用方判读后）清理。
    transport = SshTransport(cfg)
    try:
        transport.connect()
        steps["ssh"] = {"auth": "ok"}

        # ① 互斥预检（#261 每机互斥，X4 批推广至 HFSS 通道）：本注册端口
        #    的 grpcsrv 实例已在跑 → 候跑 SKIP（防陈旧实例劫持 attach/
        #    端口冲突；绝不停靠代杀——finally 清理段按 _mutex_busy 让位）。
        mutex = remote_mutex_precheck(
            transport, cfg.hfss_project_root,
            process_name="ansysedt.exe",
            fingerprint=f"grpcsrv.*:{cfg.hfss_grpc_port}:",
        )
        steps["mutex"] = mutex
        if mutex["busy"]:
            steps["_mutex_busy"] = True
            return skipped_envelope(
                mutex.get("reason") or "互斥命中=候跑（#261，禁止代杀）",
                ok=False, steps=steps,
            )

        failure = _launch_grpcsrv(cfg, transport, steps, grpc_wait_s)
        if failure is not None:
            return failure

        # 本机 attach（pyaedt 懒加载；版本配对断言在 settings 里钉）
        return _attach_and_verify(cfg, steps)
    except Exception as exc:  # fail-closed：链路裸抛也落失败信封（L2 同构）
        steps["l1_error"] = type(exc).__name__
        return {
            "ok": False,
            "reason": f"L1 链路异常: {type(exc).__name__}: {str(exc)[:160]}",
            "steps": steps,
        }
    finally:
        transport.close()
        # 服务器侧清理兜底（P2-1，L2 finally 同构）：launch 成功后的
        # attach 失败/超时/裸抛路径都要收掉本次拉起的 ansysedt + schtasks
        # 任务——cleanup 自建 transport、幂等；进程杀按命令行含 -grpcsrv
        # 且含本机端口指纹（":<port>:"）精确匹配，不误杀共享机他人实例。
        # launch 未到 schtasks 注册时 task_name 缺失 → 清扫 grpcsrv_smoke*
        # 残留任务（元数据级，不影响并发冒烟的进程面）。
        # 互斥候跑路径（_mutex_busy）例外：本次零发射零落盘，且按端口
        # 指纹杀进程恰会命中使他者候跑的在跑实例——清理让位（#261
        # 禁止代杀），steps.cleanup 如实记 skipped。
        if steps.get("_mutex_busy"):
            cleanup: dict[str, Any] = skipped_envelope(
                "互斥候跑未发射——无本批 schtasks/进程可清"
                "（禁止代杀服务器侧在跑实例，#261）",
            )
        else:
            cleanup = remote_hfss_cleanup(
                machine,
                task_name=steps.get("schtasks", {}).get("task_name"),
                grpc_match=f":{cfg.hfss_grpc_port}:",
            )
        steps["cleanup"] = cleanup


def _launch_grpcsrv(
    cfg: RemoteMachineConfig,
    transport: SshTransport,
    steps: dict[str, Any],
    grpc_wait_s: float,
    extra_cli_args: str = "",
) -> dict[str, Any] | None:
    """SSH 拉起服务器侧 ``ansysedt -grpcsrv``（L1/L2 共享前置段）。

    步骤：建服务器侧工作根 → sftp 传 .bat → schtasks 注册+触发 → 轮询
    gRPC 端口。成功返回 ``None``（steps 就地写入 bat_upload/schtasks/
    grpc_port 三键）；失败返回失败信封（steps 已并入，调用方原样 return）。

    ``extra_cli_args``：追加给 ansysedt 的命令行开关（如 L2 建模需
    ``-ng`` 非图形化；L1 缺省空串=bat 逐字节与 L1 验证版一致）。
    """
    exe = cfg.hfss_ansysedt_exe.replace("/", "\\")
    port = cfg.hfss_grpc_port
    work_root = cfg.hfss_project_root.replace("/", "\\")
    rc, _out, err = transport.run_command(
        f"New-Item -ItemType Directory -Force -Path '{work_root}' | Out-Null",
        timeout_s=20.0,
    )
    if rc != 0:
        return {"ok": False, "reason": f"服务器侧工作根创建失败: {err[:120]}",
                "steps": steps}

    bat_remote = f"{cfg.hfss_project_root}/launch_grpcsrv.bat".replace("\\", "/")
    # grpcsrv 参数携带传输模式（pyaedt launch_aedt 同构）：
    # <host>:<port>:InsecureMode——裸端口会让 AEDT 按自身缺省（secure）
    # 监听，客户端 INSECURE 握手被拒（GrpcApiError，2026-09-28 实证）。
    # 内网冒烟用 insecure；正式通道 v1 换 ANSYS_GRPC_CERTIFICATES mTLS。
    prefix = f"{extra_cli_args} " if extra_cli_args else ""
    bat_lines = (
        "@echo off\r\n"
        f'"{exe}" {prefix}-grpcsrv {cfg.host}:{port}:InsecureMode\r\n'
    )
    import tempfile
    from pathlib import Path as StdPath

    with tempfile.TemporaryDirectory() as td:
        bat_local = StdPath(td) / "launch_grpcsrv.bat"
        bat_local.write_bytes(bat_lines.encode("ascii"))
        transport.upload_file(bat_local, bat_remote)
    steps["bat_upload"] = {"remote": bat_remote}

    # 任务名唯一后缀（P2-2）：两路并发冒烟不互踩（cleanup 按同名删）；
    # 先登记进 steps（schtasks 部分失败路径也带名，cleanup 据此精确删）。
    task_name = f"RFAuto\\grpcsrv_smoke_{uuid.uuid4().hex[:8]}"
    schtasks: dict[str, Any] = {"task_name": task_name}
    steps["schtasks"] = schtasks
    cmds = [
        (f"schtasks /create /f /tn \"{task_name}\" /tr "
         f"\"{cfg.hfss_project_root}\\launch_grpcsrv.bat\" "
         f"/sc once /st 23:59", "create"),
        (f"schtasks /run /tn \"{task_name}\"", "run"),
    ]
    for cmd, label in cmds:
        rc, _out, err = transport.run_command(cmd, timeout_s=30.0)
        schtasks[label] = rc
        if rc != 0:
            schtasks["stderr_head"] = err[:200]
            return {"ok": False, "reason": f"schtasks {label} 非零退出（rc={rc}）",
                    "steps": steps}

    # 等 gRPC 端口开（探活轮询）
    import time

    deadline = time.monotonic() + grpc_wait_s
    from rfauto.infra.remote_machines import probe_port

    grpc_open = False
    while time.monotonic() < deadline:
        grpc_open, _ = probe_port(cfg.host, port, timeout_s=2.0)
        if grpc_open:
            break
        time.sleep(3.0)
    steps["grpc_port"] = {"port": port, "open": grpc_open}
    if not grpc_open:
        return {"ok": False, "reason": f"gRPC 端口 {port} 未在 {grpc_wait_s}s 内开启",
                "steps": steps}
    return None


def remote_hfss_cleanup(
    machine: str | None = None,
    *,
    task_name: str | None = None,
    grpc_match: str | None = None,
) -> dict[str, Any]:
    """冒烟清理：按 PID 精确杀远程 grpcsrv ansysedt +删 schtasks 任务+sftp bat。

    精确化口径（审查分片 1 P2-2，共享机不误杀）：

    - 进程杀：先 Query ``Win32_Process`` 取 ansysedt 的 ``ProcessId +
      CommandLine``，只杀命令行含 ``-grpcsrv`` 且（``grpc_match`` 给定时）
      含 ``grpc_match``（launch 的端口指纹 ``":<port>:"``，唯一标识本次
      拉起的实例——#261 自排除同源）的进程；无匹配=0 杀如实上报。
      绝不再 ``taskkill /IM ansysedt.exe`` 全杀——共享机他人 GUI/其他
      端口 grpcsrv 实例不受影响（杀后全量复数 ``ansysedt_after`` 如实
      留痕，残留>0 不阻塞清理成功判定）；
    - 任务删：``task_name`` 给定时只删该唯一名（launch 侧 uuid4 后缀，
      并发冒烟不互踩）；``task_name=None``（独立运维调用）清扫
      ``grpcsrv_smoke`` 残留任务（元数据级，不影响并发冒烟的进程面）。

    env 门同 remote_hfss_smoke（RFAUTO_REMOTE_SMOKE=1）。
    """
    if os.environ.get(REMOTE_SMOKE_ENV) != "1":
        return {"ok": False, "skipped": True,
                "reason": f"清理需显式 opt-in：{REMOTE_SMOKE_ENV}=1"}
    machines = load_remote_machines()
    if machine is None and not machines:
        return {"ok": False, "skipped": True, "reason": "无登记机器"}
    cfg = resolve_machine(machine, machines)
    transport = SshTransport(cfg)
    steps: dict[str, Any] = {}
    try:
        transport.connect()
        # 1) 按命令行精确识别目标实例（PID + CommandLine，管道分隔逐行解析）
        _rc, out, _err = transport.run_command(
            "Get-CimInstance Win32_Process -Filter \"Name='ansysedt.exe'\" | "
            "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }",
            timeout_s=30.0,
        )
        target_pids: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            pid_s, _, cmdline = line.partition("|")
            if not pid_s.strip().isdigit():
                continue
            lowered = cmdline.lower()
            if "grpcsrv" not in lowered:
                continue
            if grpc_match is not None and grpc_match.lower() not in lowered:
                continue
            target_pids.append(pid_s.strip())
        steps["ansysedt_grpcsrv_pids"] = target_pids
        if target_pids:
            kill_cmd = "taskkill /F " + " ".join(
                f"/PID {p}" for p in target_pids
            )
            kill_rc, _out, _err = transport.run_command(kill_cmd, timeout_s=30.0)
            steps["kill_rc"] = kill_rc
        # 2) 杀后复数（全 ansysedt 口径，残留>0 如实上报不阻塞判定）
        _rc, out_after, _err = transport.run_command(
            "Get-Process ansysedt -ErrorAction SilentlyContinue | "
            "Measure-Object | Select-Object -ExpandProperty Count",
            timeout_s=20.0,
        )
        steps["ansysedt_after"] = int(out_after.strip() or 0)
        # 3) schtasks 清理：有名删名（精确），无名清扫 grpcsrv_smoke* 残留
        if task_name:
            transport.run_command(
                f"schtasks /delete /f /tn \"{task_name}\"", timeout_s=20.0,
            )
            steps["deleted_tasks"] = [task_name]
        else:
            _rc, task_out, _err = transport.run_command(
                "schtasks /query /fo csv /nh | Select-String -SimpleMatch "
                "\"grpcsrv_smoke\"", timeout_s=30.0,
            )
            names: list[str] = []
            for line in task_out.splitlines():
                if "grpcsrv_smoke" not in line:
                    continue
                name = line.strip().split('","')[0].strip().strip('"')
                if name and name not in names:
                    names.append(name)
            for name in names:
                transport.run_command(
                    f"schtasks /delete /f /tn \"{name}\"", timeout_s=20.0,
                )
            steps["deleted_tasks"] = names
        return ok_envelope(steps=steps)
    except Exception as exc:
        steps["error"] = type(exc).__name__
        return {"ok": False, "reason": f"清理失败: {type(exc).__name__}",
                "steps": steps}
    finally:
        transport.close()


def _attach_and_verify(cfg: RemoteMachineConfig, steps: dict[str, Any]) -> dict[str, Any]:
    """本机 pyaedt attach 远程会话并做 L1 判定（调用方保证 finally release）。

    远程三开关+一环境变量（pyaedt 1.4.0 × AEDT 2025.1.0 无 SP 实证，
    attach 后恢复原值防污染本地会话）：

    - ``grpc_local=False``：远程走 TCP 传输（缺省 WNUA 是 Windows 本机通道）；
    - ``grpc_secure_mode=False``：服务器侧 ansysedt -grpcsrv 未配证书（内网）；
    - ``remote_rpc_session=True``：``_validate_port`` 无 machine 的首查在
      非远程语义下会把 new_desktop 翻 True（误判"无会话→新开"→远程启动
      不可用）——远程会话语义必须先设 True 再构造 Desktop；
    - ``PYAEDT_USE_PRE_GRPC_ARGS=True``：AEDT 2025.1.0（初始版无 SP）的
      客户端 C++ 插件不支持 ``host:port:InsecureMode`` 三段式（pyaedt
      "Service Pack is not detected" 警告同源）——裸 IP:port 连接即可，
      服务端 InsecureMode 监听不变。
    """
    try:
        from ansys.aedt.core import Desktop
        from ansys.aedt.core.generic.settings import settings
    except ImportError as exc:
        steps["attach"] = {"error": f"pyaedt 未安装: {exc}"}
        return {"ok": False, "reason": "本机缺 pyaedt（rfauto[hfss] extra）",
                "steps": steps}
    saved = {
        "grpc_local": settings.grpc_local,
        "grpc_secure_mode": settings.grpc_secure_mode,
        "remote_rpc_session": settings.remote_rpc_session,
    }
    saved_env = os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS")
    settings.grpc_local = False
    settings.grpc_secure_mode = False
    settings.remote_rpc_session = True
    os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "True"
    desktop = None
    try:
        desktop = Desktop(
            version=cfg.hfss_version,
            non_graphical=True,
            new_desktop=False,
            machine=cfg.host,
            port=cfg.hfss_grpc_port,
        )
        version = desktop.current_version
        health = version is not None and len(str(version)) > 0
        steps["attach"] = {"version": str(version), "health": health}
        return {
            "ok": bool(health),
            "reason": None if health else "attach 后 version 读取为空",
            "steps": steps,
        }
    except Exception as exc:
        steps["attach"] = {"error": type(exc).__name__}
        return {"ok": False, "reason": f"attach 失败: {type(exc).__name__}",
                "steps": steps}
    finally:
        if desktop is not None:
            with contextlib.suppress(Exception):
                desktop.release_desktop(close_on_exit=True, close_projects=False)
        for key, value in saved.items():
            setattr(settings, key, value)
        if saved_env is None:
            os.environ.pop("PYAEDT_USE_PRE_GRPC_ARGS", None)
        else:
            os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = saved_env


# 远程四开关作用域管理已提升为共享单源：rfauto.adapters.hfss_session
# .remote_session_switches（审查分片 1 P1-1；session/L1/L2 同款配方），
# 本模块经模块头 import 直接消费，不再保留本地副本。


def remote_hfss_l2_smoke(
    machine: str | None = None,
    grpc_wait_s: float = 90.0,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """L2 求解冒烟：远程建模→求解→Touchstone 回拉→判读（**真机 opt-in**）。

    env ``RFAUTO_REMOTE_SMOKE=1`` 门同 L1（unit 门内一律拒绝，零真机零连网）。

    编排：探活 → SSH 前置段（``_launch_grpcsrv``：schtasks 起
    ``ansysedt -grpcsrv``+端口轮询）→ 本机 pyaedt attach（四开关）→
    服务器侧 ``<project_root>\\l2_smoke\\proj.aedt`` 建 mline
    （几何/材料单一事实源=docs/templates/mline/meta.yaml +
    configs/materials.yaml rogers4350b_h0.508：w=1.113mm / L=40mm /
    εr=3.66 / h=0.508mm / f0=2.5GHz，HJ 精算口径）→ Driven Modal
    离散扫频 2.0-2.8GHz 41 点 → solve → export Touchstone（50Ω 重归一）
    到服务器侧路径 → sftp 回拉 ``out_dir``（缺省 ``runs/remote_l2/<日期>/``）
    → skrf 判读 → finally：release_desktop + ``remote_hfss_cleanup``
    （杀服务器 ansysedt+删 schtasks）。

    判据（#122 预声明，全部过=PASS，任何一项不过=FAIL 如实附数字）：

    - ① 回拉文件 skrf 可读且为 2 端口 41 点；
    - ② 带内 min|S11| ≤ -10 dB（50Ω 匹配线）；
    - ③ 带内 min|S21| ≥ -1 dB（40mm RO4350B 最坏值：线损+失配）；
    - ④ εeff_app ∈ [2.60, 3.10]：S21 相位斜率反演（β/εeff 旁证），
      参考面跨度=端口面间距 40mm=线长（端口贴线端、无馈线延伸，#364
      口径核对）；HJ 预报 2.8526（forward_z0(1.113, 2.5, rogers4350b)）。
      另报 S11 谷位 f_dip 供参考但**不进门**——均匀匹配线 S11 谷位受
      两端口小失配干涉支配（纹波周期 c/(2·n·L)≈2.2GHz > 扫频带 0.8GHz），
      带内单谷位置无物理保证，预声明不作为判据。

    导出用 50Ω 重归一（DoRenorm=True, RenormImped=50），判据口径=50Ω 基。

    Parameters
    ----------
    machine : str, optional
        注册表机器名（None=唯一登记机器）。
    grpc_wait_s : float
        gRPC 端口轮询超时。
    out_dir : str, optional
        回拉产物目录（缺省 ``runs/remote_l2/<YYYYMMDD>/``，runs/ 原布局语义）。

    Returns
    -------
    dict
        ``{"ok", "verdict": "PASS"/"FAIL", "reason", "machine", "project",
        "touchstone_remote", "touchstone_local", "criteria", "steps"}``。
        fail-closed：任何异常都落 FAIL 信封，不凑绿。
    """
    if os.environ.get(REMOTE_SMOKE_ENV) != "1":
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                f"真机冒烟需显式 opt-in：{REMOTE_SMOKE_ENV}=1（unit 门零真机）"
            ),
        }
    machines = load_remote_machines()
    if machine is None and not machines:
        return {"ok": False, "skipped": True, "reason": "无登记机器"}
    cfg = resolve_machine(machine, machines)
    steps: dict[str, Any] = {"probe": probe_machine(cfg)}

    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    if not (has_user and has_secret):
        steps["ssh"] = {"auth": "missing_credentials"}
        return {
            "ok": False,
            "skipped": True,
            "reason": "SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 local 覆盖）",
            "steps": steps,
        }
    if not cfg.hfss_ansysedt_exe:
        return {
            "ok": False,
            "skipped": True,
            "reason": "机器未登记 hfss.ansysedt_exe（无法拉起 grpcsrv 监听）",
            "steps": steps,
        }
    if not cfg.hfss_project_root:
        return {
            "ok": False,
            "skipped": True,
            "reason": "机器未登记 hfss.project_root（L2 project 必须落服务器侧目录）",
            "steps": steps,
        }

    import time
    from pathlib import Path as StdPath

    out_path = (
        StdPath(out_dir) if out_dir is not None
        else StdPath("runs") / "remote_l2" / time.strftime("%Y%m%d")
    )

    project_path = f"{cfg.hfss_project_root}\\l2_smoke\\proj.aedt"
    s2p_remote_win = f"{cfg.hfss_project_root}\\l2_smoke\\l2_smoke.s2p"
    s2p_remote_sftp = f"{cfg.hfss_project_root}/l2_smoke/l2_smoke.s2p".replace("\\", "/")
    s2p_local = out_path / "l2_smoke.s2p"

    envelope: dict[str, Any] = {
        "ok": False,
        "verdict": "FAIL",
        "reason": None,
        "machine": cfg.name,
        "project": project_path,
        "touchstone_remote": s2p_remote_win,
        "touchstone_local": str(s2p_local),
        "criteria": {},
    }

    transport = SshTransport(cfg)
    try:
        transport.connect()
        steps["ssh"] = {"auth": "ok"}

        # ① 互斥预检（#261 每机互斥，X4 批推广，L1 同构）：本注册端口的
        #    grpcsrv 实例已在跑 → 候跑 SKIP（finally 清理段按 _mutex_busy
        #    让位，绝不代杀在跑实例）。
        mutex = remote_mutex_precheck(
            transport, cfg.hfss_project_root,
            process_name="ansysedt.exe",
            fingerprint=f"grpcsrv.*:{cfg.hfss_grpc_port}:",
        )
        steps["mutex"] = mutex
        if mutex["busy"]:
            steps["_mutex_busy"] = True
            return skipped_envelope(
                mutex.get("reason") or "互斥命中=候跑（#261，禁止代杀）",
                ok=False, steps=steps,
            )

        # 服务器侧 L2 工作目录（proj.aedt / .s2p 落点）；先清陈旧产物
        # （上次失败残留的 proj.aedt 会让本次打开旧工程——新跑必须新工程，
        # #368 同源纪律）。
        work_dir = f"{cfg.hfss_project_root}\\l2_smoke".replace("/", "\\")
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{work_dir}' | Out-Null; "
            f"Remove-Item '{work_dir}\\*' -Force -Recurse -ErrorAction SilentlyContinue",
            timeout_s=30.0,
        )
        if rc != 0:
            envelope["reason"] = f"服务器侧 L2 工作目录创建失败: {err[:120]}"
            envelope["steps"] = steps
            return envelope

        # -ng 非图形化（pyaedt launch_aedt non_graphical 同款开关）+ -Logfile
        # 落 AEDT 消息窗日志（否则 schtasks 会话的 stdout 丢失，InsertDesign
        # 类服务端报错无从判读——2026-09-29 两轮远跑实证盲区）：schtasks
        # 拉起的会话无交互桌面，graphical ansysedt 的 InsertDesign 实测阻塞
        # ~7min 后返回 None（本地同代码秒级通过）。
        console_log = f"{cfg.hfss_project_root}\\aedt_console.log"
        failure = _launch_grpcsrv(
            cfg, transport, steps, grpc_wait_s,
            extra_cli_args=f'-ng -Logfile "{console_log}"',
        )
        if failure is not None:
            failure["verdict"] = "FAIL"
            for key in ("machine", "project", "touchstone_remote",
                        "touchstone_local", "criteria"):
                failure.setdefault(key, envelope[key])
            return failure

        build = _l2_model_solve_export(cfg, project_path, s2p_remote_win, steps)
        if not build.get("ok"):
            envelope["reason"] = build.get("reason") or "L2 建模/求解/导出失败"
            # 失败证据：拉服务器侧 AEDT 控制台日志尾（-Logfile 落盘；含
            # FlexNet 许可错误等根因——best-effort 不阻塞 fail-closed 判定）
            with contextlib.suppress(Exception):
                _rc, tail, _err = transport.run_command(
                    f"Get-Content '{cfg.hfss_project_root}\\aedt_console.log' "
                    "-Tail 40 -ErrorAction SilentlyContinue | Out-String",
                    timeout_s=20.0,
                )
                if tail.strip():
                    steps["aedt_console_tail"] = tail.strip()[:2000]
            envelope["steps"] = steps
            return envelope

        # 服务器侧产物存在性守卫（导出成功≠文件在位）
        rc, out, _err = transport.run_command(
            f"Test-Path '{s2p_remote_win}'", timeout_s=20.0)
        if out.strip() != "True":
            envelope["reason"] = "服务器侧 Touchstone 导出后未落盘（Test-Path=False）"
            envelope["steps"] = steps
            return envelope

        transport.download_file(s2p_remote_sftp, s2p_local)
        steps["download"] = {
            "remote": s2p_remote_sftp,
            "local": str(s2p_local),
            "bytes": s2p_local.stat().st_size,
        }

        import skrf as rf

        net = rf.Network(str(s2p_local))
        criteria = _judge_l2(net)
        envelope["criteria"] = criteria
        failed = [k for k, v in criteria.items() if k.startswith("c") and not v]
        envelope["verdict"] = "PASS" if not failed else "FAIL"
        envelope["ok"] = not failed
        if failed:
            envelope["reason"] = f"判据不过: {', '.join(failed)}"
        envelope["steps"] = steps
        return envelope
    except Exception as exc:  # fail-closed：任何链路异常=FAIL，不凑绿
        envelope["reason"] = f"L2 链路异常: {type(exc).__name__}: {str(exc)[:160]}"
        envelope["steps"] = steps
        return envelope
    finally:
        transport.close()
        # 服务器侧清理兜底（launch 成功路径的任何失败都要收，P2-1 同构）；
        # task_name/grpc_match 取 launch 登记值（P2-2 精确杀/精确删）。
        # 互斥候跑路径例外（L1 同构）：零发射零落盘，清理让位不代杀。
        if steps.get("_mutex_busy"):
            cleanup: dict[str, Any] = skipped_envelope(
                "互斥候跑未发射——无本批 schtasks/进程可清"
                "（禁止代杀服务器侧在跑实例，#261）",
            )
        else:
            cleanup = remote_hfss_cleanup(
                machine,
                task_name=steps.get("schtasks", {}).get("task_name"),
                grpc_match=f":{cfg.hfss_grpc_port}:",
            )
        steps["cleanup"] = cleanup


def _l2_model_solve_export(
    cfg: RemoteMachineConfig,
    project_path: str,
    s2p_remote: str,
    steps: dict[str, Any],
) -> dict[str, Any]:
    """远程建模→求解→导出 Touchstone（pyaedt 直连，L2 本体）。

    几何（单位 mm，模型坐标）：板 40×24×0.508（x∈[0,40]），地=底面薄板
    z=0，导带=z=h 薄片 y∈[-w/2,w/2]；空气盒 40×24×4.0 与板同 x/y 域；
    波端口=空气盒两端**满截面**（端口面=解域边界，无"端口小于端面需
    辐射补面"的二义性；积分线=地面(z=0)→导带上缘(y=0, z=h)，df6⑪ 口径
    积分线止于导带不穿带）。薄片导电走 ``assign_perfecte_to_sheets``
    （#356①：零厚度盒 material="pec" 不导电）。

    Returns
    -------
    dict
        ``{"ok": bool, "reason": str|None}``；异常信息写 steps["build"]。
    """
    try:
        from ansys.aedt.core import Desktop, Hfss
        from ansys.aedt.core.generic.settings import settings
    except ImportError as exc:
        return {"ok": False, "reason": f"本机缺 pyaedt（rfauto[hfss] extra）: {exc}"}

    desktop = None
    hfss = None
    try:
        with remote_session_switches():
            desktop = Desktop(
                version=cfg.hfss_version,
                non_graphical=True,
                new_desktop=False,
                machine=cfg.host,
                port=cfg.hfss_grpc_port,
            )
            steps["attach"] = {"version": str(desktop.current_version)}
            # remote_rpc_session 在 Desktop attach 语义是 bool（_validate_port
            # 远程判定），但 Hfss 设计初始化的 project_properties 加载分支按
            # rpyc 客户端对象消费（settings.remote_rpc_session.filemanager，
            # pyaedt 1.4 design.py）——裸 True 进 Hfss 必炸 AttributeError。
            # attach 完成后置 None（gRPC machine/port 显式传参，不依赖该
            # 对象；CM 退出时恢复原值）。
            settings.remote_rpc_session = None
            hfss = Hfss(
                project=project_path,
                solution_type="DrivenModal",
                version=cfg.hfss_version,
                non_graphical=True,
                machine=cfg.host,
                port=cfg.hfss_grpc_port,
            )
            modeler = hfss.modeler
            modeler.model_units = "mm"

            mat = hfss.materials.add_material("rfauto_ro4350b")
            mat.permittivity = L2_ER
            mat.dielectric_loss_tangent = L2_TAND

            w = L2_W_MM
            half_w = w / 2.0
            hw = L2_BOARD_W_MM / 2.0
            modeler.create_box(
                origin=[0, -hw, 0], sizes=[L2_LEN_MM, L2_BOARD_W_MM, L2_H_MM],
                name="sub", material="rfauto_ro4350b",
            )
            modeler.create_rectangle(
                orientation="XY", origin=[0, -hw, 0],
                sizes=[L2_LEN_MM, L2_BOARD_W_MM], name="gnd",
            )
            modeler.create_rectangle(
                orientation="XY", origin=[0, -half_w, L2_H_MM],
                sizes=[L2_LEN_MM, w], name="trace",
            )
            air = modeler.create_box(
                origin=[0, -hw, 0], sizes=[L2_LEN_MM, L2_BOARD_W_MM, L2_AIR_TOP_MM],
                name="air", material="air",
            )
            hfss.assign_perfecte_to_sheets(["gnd", "trace"], name="PECMetal")

            # 辐射边界：空气盒除两端端口面（x=0/x=L）与底面（z=0，被地
            # 覆盖）外的全部面。#285：面心是模型单位（mm），加非空守卫。
            port_face_ids: list[int] = []
            rad_face_ids: list[int] = []
            tol = 1e-4
            for face in air.faces:
                c = face.center
                if abs(c[0] - 0.0) < tol or abs(c[0] - L2_LEN_MM) < tol:
                    port_face_ids.append(face.id)
                elif abs(c[2] - 0.0) < tol:
                    continue  # 底面被 PerfectE 地覆盖，不赋辐射
                else:
                    rad_face_ids.append(face.id)
            if len(port_face_ids) != 2 or not rad_face_ids:
                return {
                    "ok": False,
                    "reason": (
                        f"空气盒面分类异常（端口面 {len(port_face_ids)}/2，"
                        f"辐射面 {len(rad_face_ids)}）——模型单位/几何核对"
                    ),
                }
            hfss.assign_radiation_boundary_to_faces(rad_face_ids, name="Rad1")

            # 波端口（满截面薄片 + 积分线地面→导带上缘，1 模，50Ω 重归一）
            for name, x0 in (("P1", 0.0), ("P2", float(L2_LEN_MM))):
                modeler.create_rectangle(
                    orientation="YZ", origin=[x0, -hw, 0],
                    sizes=[L2_BOARD_W_MM, L2_AIR_TOP_MM], name=name,
                )
                hfss.wave_port(
                    assignment=name,
                    integration_line=[
                        [f"{x0}mm", "0mm", "0mm"],
                        [f"{x0}mm", "0mm", f"{L2_H_MM}mm"],
                    ],
                    modes=1,
                    impedance=50,
                    renormalize=True,
                    name=name,
                )

            setup = hfss.create_setup("SetupL2")
            setup.props["Frequency"] = f"{L2_F0_GHZ}GHz"
            setup.props["MaximumPasses"] = 8
            setup.props["MaximumDeltaS"] = 0.02
            setup.update()
            sweep = hfss.create_linear_count_sweep(
                setup="SetupL2", name="SweepL2", unit="GHz",
                start_frequency=L2_F_START_GHZ, stop_frequency=L2_F_STOP_GHZ,
                num_of_freq_points=L2_N_POINTS, sweep_type="Discrete",
                save_fields=False,
            )
            if sweep is False:
                return {"ok": False, "reason": "扫频创建失败（create_linear_count_sweep=False）"}

            hfss.save_project()
            steps["solve_started"] = True
            analyze_ok = hfss.analyze("SetupL2")
            if analyze_ok is False:
                return {"ok": False, "reason": "求解失败（analyze 返回 False）"}
            steps["solve_done"] = True
            hfss.save_project()

            # 导出（50Ω 重归一，绕 pyaedt 包装同 #112 家族 adapter 直连口径）
            osolution = hfss.osolution
            if osolution is None:
                return {"ok": False, "reason": "hfss.osolution 不可用"}
            osolution.ExportNetworkData(
                "",                                   # DesignVariations（nominal）
                ["SetupL2:SweepL2"],
                3,                                    # FileFormat: Touchstone
                s2p_remote.replace("\\", "/"),
                ["all"],
                True,                                 # DoRenorm → 50Ω 基
                50,
                "S",
                -1,
                0,
                15,
                False,
                False,
                False,
            )
            steps["export"] = {"remote": s2p_remote}
            return ok_envelope(reason=None)
    except Exception as exc:
        steps["build"] = {"error": type(exc).__name__, "detail": str(exc)[:200]}
        return {"ok": False, "reason": f"L2 建模/求解失败: {type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        # #265 孤儿桌面铁律：finally 必 release（close_on_exit=True 让服务器
        # ansysedt 退出；清理段兜底 taskkill）。
        if hfss is not None:
            with contextlib.suppress(Exception):
                hfss.save_project()
        if desktop is not None:
            with contextlib.suppress(Exception):
                desktop.release_desktop(close_on_exit=True, close_projects=False)


def _judge_l2(
    net: Any,
    n_ports: int = 2,
    n_points: int = L2_N_POINTS,
    span_m: float = L2_SPAN_M,
    f_start_ghz: float = L2_F_START_GHZ,
    f_stop_ghz: float = L2_F_STOP_GHZ,
    f0_ghz: float = L2_F0_GHZ,
) -> dict[str, Any]:
    """L2 判据计算（纯函数：skrf.Network → 逐判据数字+布尔）。

    判据口径见 ``remote_hfss_l2_smoke`` docstring（#122 预声明）。
    εeff_app = (-slope·c·span/(2π))²，slope=S21 展开相位对频率的线性拟合
    斜率（rad/Hz），φ21=-2πf·√εeff·span/c。f_dip 只报告不进门（预声明）。
    """
    import numpy as np

    freq_ghz = np.asarray(net.frequency.f, dtype=float) * 1e-9
    s = np.asarray(net.s)
    n = len(freq_ghz)

    c1 = bool(net.nports == n_ports and n == n_points)

    if n >= 2 and net.nports >= 2:
        s11_db = 20.0 * np.log10(np.maximum(np.abs(s[:, 0, 0]), 1e-12))
        s21_db = 20.0 * np.log10(np.maximum(np.abs(s[:, 1, 0]), 1e-12))
        s11_db_min = float(s11_db.min())
        s21_db_min = float(s21_db.min())
        dip_idx = int(np.argmin(s11_db))
        f_dip_ghz = float(freq_ghz[dip_idx])

        phase = np.unwrap(np.angle(s[:, 1, 0]))
        slope = float(np.polyfit(freq_ghz, phase, 1)[0])  # rad/GHz
        # φ(f_GHz) = -2π·1e9·√εeff·L/c·f_GHz → √εeff = -slope·1e-9·c/(2π·L)
        sqrt_eff = -slope * 1e-9 * _C_M_S / (2.0 * np.pi * span_m)
        eps_eff_app = float(sqrt_eff * sqrt_eff) if sqrt_eff > 0 else float("nan")

        c2 = bool(s11_db_min <= L2_S11_GATE_DB)
        c3 = bool(s21_db_min >= L2_S21_GATE_DB)
        lo, hi = L2_EFF_WINDOW
        c4 = bool(lo <= eps_eff_app <= hi)
        # f_dip 谷位旁证窗（仅报告：出窗记 note，不翻 verdict——见预声明）
        f_dip_note = None
        if abs(f_dip_ghz - f0_ghz) > 0.15:
            f_dip_note = (
                f"S11 谷位 {f_dip_ghz:.4f}GHz 偏离 f0={f0_ghz}±0.15GHz"
                "（预声明：均匀匹配线谷位受端口失配干涉支配，不进门）"
            )
    else:
        s11_db_min = s21_db_min = float("nan")
        f_dip_ghz = eps_eff_app = float("nan")
        slope = float("nan")
        c2 = c3 = c4 = False
        f_dip_note = None

    return {
        "c1_readback": c1,
        "c2_s11_min_db": c2,
        "c3_s21_min_db": c3,
        "c4_eps_eff_window": c4,
        "n_ports": int(net.nports),
        "n_points": int(n),
        "s11_db_min": _round_or_nan(s11_db_min),
        "s21_db_min": _round_or_nan(s21_db_min),
        "f_dip_ghz": _round_or_nan(f_dip_ghz),
        "f_dip_note": f_dip_note,
        "eps_eff_app": _round_or_nan(eps_eff_app),
        "eps_eff_expected": L2_EFF_EXPECT,
        "eps_eff_window": list(L2_EFF_WINDOW),
        "s21_phase_slope_rad_per_ghz": _round_or_nan(slope),
        "span_m": span_m,
        "band_ghz": [f_start_ghz, f_stop_ghz],
    }


def _round_or_nan(value: float, digits: int = 4) -> float:
    """数值取整（NaN 原样传递——判据附表禁止 None/字符串混型）。"""
    if value != value:  # NaN
        return float("nan")
    return round(float(value), digits)
