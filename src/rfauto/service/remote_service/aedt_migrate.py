"""aedt_migrate 远程桥接发射配方（remote_service 子模块，aurora_r AM-S3）。

蓝图：aedt_migrate 批量迁移通道设计（2026-11-10 主会话交接稿）§1 Stage 4
远程腿 + §2 remote_service 通道。**本席只交付配方与发射清单（manifest），
不真发射**——2023 R2 桥接机未装（实验室现状，蓝图 Stage 4 前提），真机
窗口挂账主代/用户窗口；env 显式意图门常量
:data:`AEDT_MIGRATE_REMOTE_ENV`（S2 real_edt 门同款形态）为将来真发射
入口的预声明门（本模块不提供发射函数=无死壳，#270 纪律）。

配方内容（清单产出的全部要件，发射窗口照单执行）：

- 发射脚本模板：save-as IronPython 脚本（单源
  :func:`rfauto.service.aedt_migrate_bridge.build_bridge_saveas_script`
  ，本地腿/远程腿同一脚本，零漂移）+ console 可见直指 bat
  （:func:`build_bridge_task_bat`，三代发射家法形态）；
- amasya 中间根唯一：任务目录一律落 ``E:\\rfauto_remote``（服务器说明
  §10 铁律；用户令 2026-10-05 重申"服务器临时目录一律 E 盘"）——配方
  对任何其他 work_root **error_envelope 拒绝**（含生产
  云盘，禁写铁律双保险）；
- #261 互斥自检含 ansysedt 命令行：互斥探针命令经共享单源
  ``remote_mutex_command("ansysedt.exe", 指纹)`` 进清单（指纹=本腿
  RunScript 脚本名，只挡本通道实例不误伤他通道）；
- 发射存活复核（0b-2）：60s/120s 双 CPU 采样步骤写进清单（执行归发射
  窗口）；
- schtasks once /Delete 补刀 + 任务毕 verified_gone 清理：删除命令形态
  与"回拉后逐路径 Test-Path=False 复核"清单进 manifest cleanup 段；
- 杀进程按互斥查询所得 PID 精确 taskkill（绝无 /IM 全杀——共享机纪律）。

分层：service 层（remote_service 子模块，T2 拆分惯例）；向下消费
``rfauto.service.aedt_migrate_bridge``（脚本单源）与 ``.mutex``（互斥
命令单源）。facade re-export 见包 ``__init__``（``__all__`` 快照钉未动
——公开名扩面归 S4 金快照同笔，本席申报制挂账）。
"""

from __future__ import annotations

import os
from typing import Any

from rfauto.infra.remote_machines import (
    RemoteConfigError,
    RemoteMachineConfig,
    load_remote_machines,
    resolve_machine,
)
from rfauto.service.aedt_migrate_bridge import (
    BRIDGE_SCRIPT_NAME,
    build_bridge_saveas_script,
)
from rfauto.service.envelope import error_envelope, ok_envelope

from .mutex import remote_mutex_command

#: 真机发射显式意图门（S2 real_edt 门 RFAUTO_AEDT_MIGRATE_REAL 同款形态）：
#: 将来真发射入口必须此 env=1 才执行（unit 门零真机零连网，#139/df4⑥）。
#: 本模块只交付配方不提供发射函数——门常量即挂账预声明。
AEDT_MIGRATE_REMOTE_ENV = "RFAUTO_AEDT_MIGRATE_REMOTE"

#: 服务器侧唯一中间根（amasya；服务器说明 §10：E 盘唯一中间文件根，
#: 禁生产云盘直写）。配方对其他 work_root 一律拒绝。
AEDT_MIGRATE_REMOTE_WORK_ROOT = "E:\\rfauto_remote"

#: 任务目录名前缀（确定性命名：``<prefix>_<sha8>``——sha8 锚定工程内容
#: 身份，同 S0 报告命名口径；已存在=fail-closed 不复用，发射窗口执行）。
AEDT_MIGRATE_TASK_PREFIX = "aedt_migrate_bridge"

#: #261 互斥指纹（本通道 RunScript 脚本名；正则安全——字面段无元字符，
#: 只挡本通道 ansysedt 实例，不误伤 grpcsrv/他通道会话）。
AEDT_MIGRATE_MUTEX_FINGERPRINT = f"RunScript.*{BRIDGE_SCRIPT_NAME.removesuffix('.py')}"

#: #261 互斥进程名（含 ansysedt 命令行自检——发射窗口互斥预检用）。
AEDT_MIGRATE_MUTEX_PROCESS = "ansysedt.exe"

#: console 可见 bat 模板（三代发射家法；对照 remote_oe_service
#: .build_run_task_bat：直指 exe 无 wscript/无 -WindowStyle Hidden，
#: stdout 走 console+AEDT 消息走 -Logfile，launch_rc.txt 落盘行（qx28
#: 家法 delta），结尾 exit /b %RC% 留痕；CRLF 由本模块 join 保证）。
_BRIDGE_TASK_BAT_TEMPLATE = """\
@echo off
rem aedt_migrate bridge launch (console-visible direct form; 0b-2
rem anti-AV-silent-kill discipline; generator=remote_service.aedt_migrate)
set "TASK_DIR={task_dir}"
if not exist "%TASK_DIR%\\out" mkdir "%TASK_DIR%\\out"
echo [bridge] %date% %time% task=%TASK_DIR%
"{ansysedt_exe}" -ng -Logfile "{log_path}" -RunScript "{script_path}"
set RC=%errorlevel%
echo [bridge done] rc=%RC% at %date% %time%
(echo rc=%RC%)> "%TASK_DIR%\\launch_rc.txt"
echo product-census:
dir /b "%TASK_DIR%"
exit /b %RC%
"""


def build_bridge_task_bat(
    task_dir: str,
    ansysedt_exe: str,
    script_path: str,
    log_path: str,
) -> bytes:
    """发射 bat 字节（**CRLF**；console 可见直指形态，0b-2 纪律）。

    模板要点（三代家法）：bat 直指 ansysedt（无 wscript/静默窗形态——
    服务器杀毒对隐蔽形态静默击杀，0b-2）；``-Logfile`` 收 AEDT 自身消息
    （schtasks 会话 stdout 丢失盲区，L2 通道 2026-09-29 实证同源）；
    ``-RunScript`` 操作数恒末位（#374 参数序纪律）；
    ``launch_rc.txt`` 落盘行供收割档 rc 判读（qx28 家法 delta）；括号包
    echo 防 ``rc=0>`` 句柄重定向陷阱。
    """
    lines = _BRIDGE_TASK_BAT_TEMPLATE.format(
        task_dir=task_dir,
        ansysedt_exe=ansysedt_exe,
        log_path=log_path,
        script_path=script_path,
    ).splitlines()
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def _norm_root(path: str) -> str:
    """根路径归一（normcase+去尾分隔符——唯一中间根判定用）。"""
    return os.path.normcase(str(path).replace("/", "\\")).rstrip("\\")


def aedt_migrate_remote_recipe(
    project_name: str,
    sha8: str,
    *,
    ansysedt_exe: str | None = None,
    machine: str | None = None,
    machine_cfg: RemoteMachineConfig | None = None,
    work_root: str | None = None,
) -> dict[str, Any]:
    """远程桥接发射清单（**纯本地配方，零 SSH 零发射**；信封进出）。

    Args:
        project_name: 工程 stem（清单路径命名用）。
        sha8: 工程 sha256 前 8 位（任务目录确定性命名 + 产物锚名）。
        ansysedt_exe: 桥接机 2023 R2 ansysedt.exe 绝对路径（真机窗口由
            用户提供；None=清单 bat 段 pending 如实，不造占位路径）。
        machine: 注册表机器名（解析 enrich host；解析失败=error 信封）。
        machine_cfg: 显式注入机器配置（测试离线注入用；优先于 machine）。
        work_root: 服务器侧工作根覆盖（缺省 machine_cfg 的
            hfss_project_root，再缺省 :data:`AEDT_MIGRATE_REMOTE_WORK_ROOT`
            唯一中间根）；**非唯一中间根一律 error_envelope 拒绝**。

    Returns:
        ok_envelope（manifest）：``task/paths/script_content/bat_content/
        mutex/launch/cleanup/work_root/machine`` 段——发射窗口照单执行；
        根不合规/机器解析失败 → error_envelope（ok=False + errors）。
    """
    root = work_root
    machine_info: dict[str, Any] | None = None
    if machine_cfg is None and machine is not None:
        try:
            machine_cfg = resolve_machine(machine, load_remote_machines())
        except RemoteConfigError as exc:
            return error_envelope(
                f"机器解析失败: {exc}", channel="aedt_migrate_bridge_remote")
    if machine_cfg is not None:
        machine_info = {"name": machine_cfg.name, "host": machine_cfg.host}
        if root is None:
            root = machine_cfg.hfss_project_root
    if root is None:
        root = AEDT_MIGRATE_REMOTE_WORK_ROOT
    if _norm_root(root) != _norm_root(AEDT_MIGRATE_REMOTE_WORK_ROOT):
        return error_envelope(
            f"work_root 非唯一中间根: {root}——远程桥接任务目录一律落 "
            f"{AEDT_MIGRATE_REMOTE_WORK_ROOT}（服务器说明 §10；禁写 "
            "生产云盘根）",
            channel="aedt_migrate_bridge_remote",
        )

    task_name = f"{AEDT_MIGRATE_TASK_PREFIX}_{sha8}"
    task_dir = rf"{root}\tasks\{task_name}"
    input_staged = rf"{task_dir}\input\{project_name}.aedt"
    script_path = rf"{task_dir}\{BRIDGE_SCRIPT_NAME}"
    log_path = rf"{task_dir}\bridge_2023r2.log"
    artifact_out = rf"{task_dir}\out\{project_name}__{sha8}.aedt"

    script_content = build_bridge_saveas_script(input_staged, artifact_out)

    bat_content: str | None = None
    bat_pending: str | None = None
    if ansysedt_exe:
        bat_content = build_bridge_task_bat(
            task_dir, ansysedt_exe, script_path, log_path).decode("ascii")
    else:
        bat_pending = (
            "ansysedt_exe 未提供（桥接机 2023 R2 安装路径待用户在真机窗口"
            "给出）——bat 段 pending 如实，不造占位路径")

    mutex_command = remote_mutex_command(
        AEDT_MIGRATE_MUTEX_PROCESS, AEDT_MIGRATE_MUTEX_FINGERPRINT)
    manifest = {
        "channel": "aedt_migrate_bridge_remote",
        "project": project_name,
        "sha8": sha8,
        "work_root": root,
        "machine": machine_info,
        "task": {"name": task_name, "dir": task_dir,
                 "dir_sftp": task_dir.replace("\\", "/")},
        "paths": {
            "input_staged": input_staged,
            "script": script_path,
            "log": log_path,
            "artifact_out": artifact_out,
            "artifact_out_sftp": artifact_out.replace("\\", "/"),
            "console_log": log_path,
        },
        "script_content": script_content,
        "bat_content": bat_content,
        "bat_pending_reason": bat_pending,
        "mutex": {
            "process": AEDT_MIGRATE_MUTEX_PROCESS,
            "fingerprint": AEDT_MIGRATE_MUTEX_FINGERPRINT,
            "command": mutex_command,
            "note": "#261 互斥预检（发射窗口第一步；命中=候跑不发射"
                    "不代杀）",
        },
        "launch": {
            "pending": True,
            "env_gate": AEDT_MIGRATE_REMOTE_ENV,
            "steps": [
                f"env 门（{AEDT_MIGRATE_REMOTE_ENV}=1）显式意图后由发射窗口执行",
                "#261 互斥预检（mutex.command）",
                "任务目录创建（已存在=fail-closed 不复用）",
                "sftp 上传四件（input_staged/script/bat/无——bat 内容由"
                "清单渲染落盘，CRLF 字节校验）",
                "schtasks once 注册+触发（bat 直指 console 可见，0b-2）",
                "60s/120s 双 CPU 采样存活复核（0b-2 静默击杀嫌疑探针）",
                "schtasks once /Delete 补刀（防 23:59 二次发射）",
                "轮询 out/ 产物落盘（launch_rc.txt rc 判读互证）",
                "sftp 回拉 artifact_out → 桥接产物重入 2025 R1 "
                "S1/S2/S3 链（aedt_migrate_service 既有 re-entry 路由）",
            ],
            "executor": "挂账主代/用户窗口——本席只交付配方，不真发射"
                        "（2023 R2 未装）",
        },
        "cleanup": {
            "schtasks_delete_form": 'schtasks /delete /f /tn "<task_name>"'
                                    "（once 注册补刀+任务毕双保险）",
            "kill_form": "taskkill /F /PID <pid,...>（PID 来自 mutex.command"
                         " 查询，按命令行指纹精确匹配；禁止按进程名全杀）",
            "verified_gone": [task_dir, input_staged, artifact_out],
            "note": "任务毕回拉后逐路径 Test-Path=False 复核（verified_gone"
                    "）；复核不通过如实登记不凑绿",
        },
    }
    return ok_envelope(**manifest)
