"""HFSS 远程通道 L1/L2 冒烟编排（remote_service T2 拆分子模块）。

L1 attach 冒烟、L2 求解冒烟（远程建模→求解→Touchstone 回拉→判读）、
grpcsrv 拉起（schtasks）/按 PID 精确清理/attach 四开关、L2 判据纯函数；
真机 opt-in 门 env ``RFAUTO_REMOTE_SMOKE=1``（unit 门零真机零连网，
#139/df4⑥）。aurora_h W3-S3 自 service/remote_service 巨石逐字节迁入
（AU-1 facade，函数体零改动）；L2 几何/材料单一事实源见常量区注记。
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import Any

from rfauto.adapters.hfss_session import remote_session_switches
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteMachineConfig,
    SshTransport,
    load_remote_machines,
    probe_machine,
    resolve_machine,
)
from rfauto.service.envelope import ok_envelope, skipped_envelope
from rfauto.service.remote_sftp_pull import record_pull_manifest

from .mutex import remote_mutex_command, remote_mutex_precheck

REMOTE_SMOKE_ENV = "RFAUTO_REMOTE_SMOKE"


# ─── L2 求解冒烟常量（几何单一事实源=docs/templates/mline/meta.yaml；
#     材料单一事实源=configs/materials.yaml rogers4350b_h0.508；
#     线宽/εeff 为 skrf HJ 精算（core/synthesis.py，#1c 禁沿用毫米数）） ───
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

    - 进程杀：先查 ``Win32_Process`` 取 ansysedt 的 ``ProcessId +
      CommandLine``，只杀命令行含 ``-grpcsrv`` 且（``grpc_match`` 给定时）
      含 ``grpc_match``（launch 的端口指纹 ``":<port>:"``，唯一标识本次
      拉起的实例——#261 自排除同源）的进程；无匹配=0 杀如实上报。
      绝不再 ``taskkill /IM ansysedt.exe`` 全杀——共享机他人 GUI/其他
      端口 grpcsrv 实例不受影响（杀后全量复数 ``ansysedt_after`` 如实
      留痕，残留>0 不阻塞清理成功判定）；
    - 任务删：``task_name`` 给定时只删该唯一名（launch 侧 uuid4 后缀，
      并发冒烟不互踩）；``task_name=None``（独立运维调用）清扫
      ``grpcsrv_smoke`` 残留任务（元数据级，不影响并发冒烟的进程面）。
    - 引号契约（A7 P2-5）：本函数全部远端命令构造**零双引号**（G5 单源
      形态，``remote_mutex_command`` 同规——双引号在部分传输路径被
      CommandLineToArgvW 当 argv 分组符消费，单引号不经 argv 层存活；
      schtasks 任务名无空白，双/单引号形态语义等价、实为一致性收敛，
      证据链见 W7-B §1.5-1）。

    W7-B §1.5-1 复诊（2026-10-07，复现证据 ``内部证据档``）：旧实现
    用 ``Get-CimInstance -Filter "Name='ansysedt.exe'"`` 查指纹，经 SSH
    exec 通道**静默失效**（killed=[] 而进程活着）。根因（字节级实证）：
    Win32-OpenSSH 把命令串拼进 CreateProcess 命令行 → 双引号被
    CommandLineToArgvW 当 argv 分组符消费 → PowerShell 收到裸 token
    ``Name='ansysedt.exe'``，参数模式分词把中段单引号当字符串起始拼接 →
    WQL 实得 ``Name=ansysedt.exe``（值失引号）→ CimException「无效查询」
    （rc=1+空 stdout；同命令交互通道引号存活=正常，W7-B 席位侧手敲
    核归属因此能用）。修法：查询复用 :func:`remote_mutex_command` 单源
    形态（G5 全程单引号零双引号——单引号不经 argv 层）；查询 rc/stderr
    落 steps（``fingerprint_query_rc`` 等）不再静默——按 #105 仍不阻塞
    清理主路径（best-effort），但任何传输层失真在信封可见。

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
        #    W7-B §1.5-1 修复：复用互斥单源命令形态（全程单引号零双引号，
        #    根因与证据链见函数 docstring）——PS 侧预筛 Name+grpcsrv，本侧
        #    grpc_match 精筛+协议行解析（防御纵深，循环内 grpcsrv 判据保留）。
        fp_cmd = remote_mutex_command("ansysedt.exe", "grpcsrv")
        fp_rc, out, fp_err = transport.run_command(fp_cmd, timeout_s=30.0)
        steps["fingerprint_query_rc"] = fp_rc
        if fp_rc != 0:
            steps["fingerprint_query_stderr_head"] = fp_err[:160]
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
        #    （A7 P2-5：命令构造单引号形态，本函数零双引号——docstring
        #    引号契约；任务名无空白，形态收敛不改变远端语义）
        if task_name:
            transport.run_command(
                f"schtasks /delete /f /tn '{task_name}'", timeout_s=20.0,
            )
            steps["deleted_tasks"] = [task_name]
        else:
            _rc, task_out, _err = transport.run_command(
                "schtasks /query /fo csv /nh | Select-String -SimpleMatch "
                "'grpcsrv_smoke'", timeout_s=30.0,
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
                    f"schtasks /delete /f /tn '{name}'", timeout_s=20.0,
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
        # 尾程项 11 薄接线：L2 单文件回拉也落回拉清单 JSON（remote_sftp_pull
        # 的清单构造器，纯本地写；best-effort 不阻塞判读——#105 观测性
        # 零故障点纪律，写失败 suppress 判读面零感知）。
        with contextlib.suppress(Exception):
            manifest_rec = record_pull_manifest(
                out_path,
                files=[{
                    "remote": s2p_remote_sftp,
                    "local": str(s2p_local),
                    "bytes": s2p_local.stat().st_size,
                    "status": "pulled",
                }],
                machine=cfg.name,
                remote_dir=f"{cfg.hfss_project_root}/l2_smoke",
            )
            steps["pull_manifest"] = {
                "path": manifest_rec.get("path"),
                "counts": manifest_rec.get("counts"),
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
