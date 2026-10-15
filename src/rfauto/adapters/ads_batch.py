"""ADS 网表批求解发射-回收执行面（ads_batch，发射器可插拔）。

hpeesofsim 通道的 one-shot 批处理执行面：每求解一个独立短命进程，
发射器（launcher）可插拔（registry 缝，``register_launcher`` 扩展）——

- ``local``：本机 subprocess 直跑 ``<ads>\\bin\\hpeesofsim.exe``。env 构造
  **导入复用** ``ads_netlist._build_ads_env``/``_resolve_ads_dir``（零复制）：
  与 ``ads_python_api.AdsPythonApiAdapter.run_simulation`` 的内联构造同域
  （HPEESOF_DIR + PATH 前置 bin / adsptolemy\\lib.win32_64 / tools\\python，
  0xC0000135 缺 DLL 同根因）；ads_python_api 该逻辑是方法内联不可导入，
  且其 PATH 顺序为"bin 前置、adsptolemy/tools 后置"，而 ads_netlist 三者
  全前置是 hpeesofsim 真机实证口径（真跑 exit 0），
  故复用后者。目录解析链=显式参数 > RFAUTO_HPEESOF_DIR env >
  configs/settings.local.yaml 的 hpeesof_dir > 兜底默认（_resolve_ads_dir
  既有链，含存在性校验）。
- ``ssh``：参数化主机 ssh 命令行发射。远端命令形态与
  ``service.remote_ads_service`` 同一定案（分层纪律 adapters 不得 import
  service，故同形实现于此并注记出处）：#272 env 形态（HPEESOF_DIR+PATH
  前置）/ G5 零双引号（路径一律单引号包裹，含单引号/空白的路径发射前
  fail-closed 拒绝，见 ``check_remote_path_safe``）/ G8 PS 原生 ``;`` 分隔 /
  ``exit $LASTEXITCODE`` rc 显式透传（PS 对原生 exe 会话退出码恒 0）。
  凭据零持有：ssh argv 带 ``-o BatchMode=yes``（防密码交互悬挂），凭据由
  调用方 ssh config/agent/key 供给，本模块不读不传。

复用面（hfss_batch 同款模式，import 复用其工具函数）：
- 超时看门 pipeline.watchdog.Watchdog + 整树击杀 hfss_batch._kill_process_tree
  （只对自己 Popen 拉起的子进程，pid 由句柄持有不存在误伤，#245 不盲杀）；
- console 输出重定向追加进 logfile（句柄直写无管道死锁面）+ 失败判读
  尾部回读（read_logfile_tail）；
- 产物扫描回收（best-effort #105，扫描异常降级为已收部分不抛；网表
  ``File=`` 引用输入从产物清单排除——输入依赖与产物同为 .sNp 形态）。

网表自包含纪律（#276）：发射前正则扫 ``File="..."`` 引用（双引号形态=
generate_netlist 产出口径；``\\bfile`` 边界使 Filename= 类键不误中）——
引用文件本地缺失 → 结构化 fail-fast（零 Popen 零落盘）；ssh 发射额外
拒绝绝对路径引用（盘符/UNC——远端主机无法解析本机路径，#276 复用雷：
SnP File= 写死临时目录的网表直接复跑必炸）与 ``..`` 越界（路径注入面
守卫）。

工作目录语义：缺省=网表所在目录原位执行（零复制）；显式 workdir 且
网表不在其中时，网表+相对引用依赖按相对子结构 staging 进 workdir 后
执行副本（hpeesofsim 相对引用以 CWD 解析，staging 保其可解析；staged
清单随结果落账）。

ssh 通道边界（诚实面）：本模块只负责"发射+等停+命令/rc/日志落账"。
ssh 模式产物枚举/sftp 回拉归 ``service.remote_ads_run`` 五步通道（本机
无需装 ADS），此处 ``artifacts=[]``、``remote_dataset`` 给出远端数据集
预期路径（``<remote_work_dir>\\<网表全名>.ds``，hpeesofsim 数据集命名
=网表文件全名+.ds，remote_ads 通道实证）；超时击杀只及本地 ssh 客户端
进程树，远端孤儿面由该通道互斥预检（#261）+任务毕清理兜底。

测试口径：unit 全 fake（Popen 替身，零真机零连网）；local 真机验证走
env 门 ``RFAUTO_ADS_BATCH_REAL=1``（tests/unit/test_ads_batch.py opt-in，
df4⑥ 真跑不进缺省 unit 门）。刻意不定义 ``__all__``（public_api 金快照
按 __all__ 收录，翻公开面须显式评审——pipeline.watchdog 先例）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.adapters.ads_netlist import _build_ads_env, _resolve_ads_dir
from rfauto.adapters.hfss_batch import (
    MAX_ARTIFACTS,
    _is_touchstone,
    _kill_process_tree,
    read_logfile_tail,
)
from rfauto.core.errors import RFAutoError
from rfauto.pipeline.watchdog import Watchdog

logger = logging.getLogger(__name__)

#: ADS 通道 console 日志文件名形态（落工作目录，hfss_batch.BATCH_LOGFILE_FMT
#: 同款命名纪律；hpeesofsim 自身产物日志不重名不互踩）。
BATCH_LOGFILE_FMT = "hpeesofsim_batch_{stem}.log"

#: 失败判读回读的 logfile 尾部行数（非全量回拖，hfss_batch 同语义）。
LOGFILE_TAIL_LINES = 40

#: 网表 ``File="..."`` 引用扫描（双引号形态；``\\bfile`` 边界使 Filename=
#: 类键不误中；与 service.remote_ads_service._FILE_REF_RE 同款纪律）。
_FILE_REF_RE = re.compile(r'(?i)\bfile\s*=\s*"([^"]*)"')

#: 绝对路径判别（盘符 ``X:``；UNC ``\\\\`` 另判）。
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

#: ADS 通道产物扩展名白名单（Touchstone 之外）：.plt 曲线 / .ds 数据集
#: （目录或单文件双形态，均按一条记）/ .log 日志。
_ADS_RESULT_EXTS = (".plt", ".ds", ".log")

#: ssh 缺省选项：BatchMode=yes 防密码交互悬挂（凭据由 ssh config/agent
#: 供给，本模块零凭据持有）。
_SSH_DEFAULT_OPTIONS = ("BatchMode=yes",)

#: 远端 hpeesofsim exe 名（服务器侧 Windows 形态）。
_REMOTE_EXE_NAME = "hpeesofsim.exe"


class AdsBatchError(RFAutoError):
    """ADS 批求解发射面前置检查失败（自包含化/路径安全/发射器参数）。"""


# ─── 发射器注册表（可插拔缝）─────────────────────────────────────────────────

#: 发射器签名：``(netlist_name, work_dir, log_handle, opts) ->
#: (command argv, Popen, meta)``。meta 并入结果信封（ads_dir /
#: remote_command / remote_dataset 等发射器特有落账）。
LauncherFn = Callable[[str, Path, Any, dict[str, Any]],
                      tuple[list[str], Any, dict[str, Any]]]

_LAUNCHERS: dict[str, LauncherFn] = {}


def register_launcher(name: str) -> Callable[[LauncherFn], LauncherFn]:
    """发射器注册装饰器（local/ssh 为内置；注册新名即扩展，无需改主入口）。"""
    def _deco(fn: LauncherFn) -> LauncherFn:
        _LAUNCHERS[name] = fn
        return fn
    return _deco


# ─── 网表自包含检查（#276，纯函数零副作用）────────────────────────────────────

def scan_netlist_file_refs(netlist_path: str | Path) -> list[str]:
    """扫描网表 ``File="..."`` 引用（原文保序去重；无引用=空表）。"""
    text = Path(netlist_path).read_text(encoding="utf-8", errors="replace")
    seen: dict[str, None] = {}
    for m in _FILE_REF_RE.finditer(text):
        raw = m.group(1).strip()
        if raw:
            seen.setdefault(raw, None)
    return list(seen)


def validate_netlist_self_containment(
    netlist_path: str | Path, *, portable: bool = False,
) -> list[str]:
    """网表自包含检查（#276）：返回错误清单（空=通过），不抛。

    - 引用文件本地缺失 → 一律报错（调用方据此结构化 fail-fast，零 Popen）；
    - ``portable=True``（ssh 发射）：绝对路径引用（盘符/UNC）额外报错——
      远端主机无法解析本机路径，须先自包含化（依赖放网表旁改相对路径）；
    - ``..`` 越界 / 空引用一律报错（路径注入面守卫，本地远端同一纪律）。
    """
    netlist_path = Path(netlist_path)
    netlist_dir = netlist_path.resolve().parent
    errors: list[str] = []
    for raw in scan_netlist_file_refs(netlist_path):
        if raw.startswith("\\\\") or _DRIVE_RE.match(raw):
            if portable:
                errors.append(
                    f'网表引用绝对路径依赖 File="{raw[:120]}"——远端主机无法解析'
                    "本机路径（#276），请先自包含化（依赖放网表旁并改相对路径）")
                continue
            if not Path(raw).is_file():
                errors.append(
                    f'网表引用文件本地缺失: File="{raw[:120]}"（#276 发射前 '
                    "fail-fast）")
            continue
        parts = [p for p in raw.replace("\\", "/").split("/")
                 if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            errors.append(f"网表依赖引用越界或为空（.. / 空）: {raw[:120]!r}")
            continue
        if not netlist_dir.joinpath(*parts).is_file():
            errors.append(
                f'网表引用文件本地缺失: File="{raw[:120]}"（#276 发射前 '
                "fail-fast）")
    return errors


# ─── 远端命令构造（纯函数，测试钉字面）───────────────────────────────────────

def check_remote_path_safe(label: str, value: str) -> str:
    """远端命令注入面守卫：路径禁单引号与空白（抛 AdsBatchError）。

    与 service.remote_ads_service._check_remote_safe 同款纪律（分层不可
    import，同形实现并注记）：远端命令零双引号（G5）、路径单引号包裹，
    含单引号/空白的值无法安全引用——fail-closed 拒绝（登记路径如
    E:\\rfauto_remote / E:\\ADS\\ADS27 均天然满足）。
    """
    v = value.replace("/", "\\")
    if "'" in v or any(ch.isspace() for ch in v):
        raise AdsBatchError(
            f"{label} 含单引号或空白（远端命令零双引号纪律，无法安全引用）",
            details={"label": label, "value": value[:80]},
        )
    return v


def build_remote_hpeesofsim_command(
    ads_dir: str, work_dir: str, netlist_name: str,
) -> str:
    """组装远端 hpeesofsim 执行命令（PS 原生单串）。

    形态定案出处：service.remote_ads_service._build_hpeesofsim_command
    同形（#272 env / G5 零双引号 / G8 ``;`` 链 / rc 透传，PS 对原生 exe
    会话退出码恒 0；``$null`` 守卫防 exe 启动失败残留上一次
    $LASTEXITCODE）；exe 缺失走显式 ``exit 3``（fail-closed 可判读）::

        $env:HPEESOF_DIR='<ads>';
        $env:PATH='<ads>\\bin;<ads>\\adsptolemy\\lib.win32_64;<ads>\\tools\\python;' + $env:PATH;
        Set-Location -LiteralPath '<wd>';
        if (-not (Test-Path -LiteralPath '<exe>')) { Write-Output 'HPEESOFSIM_NOT_FOUND'; exit 3 }
        & '<exe>' '<netlist>'; $rc = $LASTEXITCODE; if ($null -eq $rc) { exit 1 }; exit $rc

    引号转义纪律：路径一律单引号包裹；含单引号/空白的路径无法安全引用，
    由 ``check_remote_path_safe`` 在发射前 fail-closed 拒绝（本函数不内联
    转义，拒绝优于转义——PS 单引号串内单引号需翻倍，错误路径宁可不跑）。
    """
    ads = ads_dir.replace("/", "\\")
    wd = work_dir.replace("/", "\\")
    path_pre = ";".join([
        f"{ads}\\bin",
        f"{ads}\\adsptolemy\\lib.win32_64",
        f"{ads}\\tools\\python",
    ])
    exe = f"{ads}\\bin\\{_REMOTE_EXE_NAME}"
    return (
        f"$env:HPEESOF_DIR='{ads}'; "
        f"$env:PATH='{path_pre};' + $env:PATH; "
        f"Set-Location -LiteralPath '{wd}'; "
        f"if (-not (Test-Path -LiteralPath '{exe}')) "
        "{ Write-Output 'HPEESOFSIM_NOT_FOUND'; exit 3 }; "
        f"& '{exe}' '{netlist_name}'; "
        "$rc = $LASTEXITCODE; if ($null -eq $rc) { exit 1 }; exit $rc"
    )


def build_ssh_command(
    ssh_exe: str,
    host: str,
    remote_command: str,
    *,
    port: int | None = None,
    extra_options: list[str] | None = None,
) -> list[str]:
    """拼 ssh 发射 argv（远端命令恒为单个末位 argv 元素=一整条远端命令串）。

    - ``-o BatchMode=yes`` 缺省（防密码交互悬挂；凭据由 ssh config/agent
      供给）；``extra_options`` 追加原始 token（如 ``["-o",
      "StrictHostKeyChecking=accept-new"]``）；
    - argv 列表直传 CreateProcess（不经 shell），host/命令串无注入面；
      命令串内部的单引号安全由 ``check_remote_path_safe`` 上游守卫。
    """
    argv = [str(ssh_exe)]
    for opt in _SSH_DEFAULT_OPTIONS:
        argv += ["-o", opt]
    argv += [str(t) for t in (extra_options or [])]
    if port:
        argv += ["-p", str(int(port))]
    argv += [str(host), remote_command]
    return argv


# ─── 产物回收（best-effort #105：扫描失败不翻求解结果）───────────────────────

def collect_ads_artifacts(
    workdir: str | Path, limit: int = MAX_ARTIFACTS,
    exclude: set[str] | None = None,
) -> list[str]:
    """求解完成后扫描工作目录产物路径清单（ADS 通道白名单）。

    命中=Touchstone（.sNp，复用 hfss_batch._is_touchstone）+ .plt/.ds/.log
    白名单；.ds 目录形态整目录记一条（不递归展开）。``exclude``：按
    normcase 绝对路径排除的条目（调用方传入网表 ``File=`` 引用输入的
    落盘路径——输入依赖与产物同在白名单扩展名内，不排除会混入清单）。
    排序稳定、截断于 ``limit``；任何扫描异常降级为已收集部分（不抛，
    #105）。
    """
    root = Path(workdir)
    excl = {os.path.normcase(p) for p in (exclude or set())}
    found: set[str] = set()
    try:
        for entry in root.rglob("*"):
            name = entry.name
            if not (_is_touchstone(name)
                    or name.lower().endswith(_ADS_RESULT_EXTS)):
                continue
            if not (entry.is_file() or entry.suffix.lower() == ".ds"):
                continue
            if os.path.normcase(str(entry)) in excl:
                continue
            found.add(str(entry))
            if len(found) >= limit:
                break
    except OSError:
        pass  # 单根扫描失败降级（#105），已收部分照常返回
    return sorted(found)[:limit]


def _netlist_input_paths_in_workdir(
    netlist_path: Path, work_dir: Path,
) -> set[str]:
    """网表 ``File=`` 引用输入在 work_dir 内的落盘路径集（normcase）。

    绝对引用按原路径、相对引用按 work_dir/相对结构解析（staging 与原位
    两态下相对依赖都落 work_dir）；``..`` 引用已被 validate 拦截，此处
    跳过。
    """
    out: set[str] = set()
    for raw in scan_netlist_file_refs(netlist_path):
        if raw.startswith("\\\\") or _DRIVE_RE.match(raw):
            out.add(os.path.normcase(str(Path(raw))))
            continue
        parts = [p for p in raw.replace("\\", "/").split("/")
                 if p not in ("", ".")]
        if parts and not any(p == ".." for p in parts):
            out.add(os.path.normcase(str(work_dir.joinpath(*parts))))
    return out


# ─── 工作目录 staging（自包含执行副本）───────────────────────────────────────

def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def stage_netlist_bundle(
    netlist_path: Path, work_dir: Path,
) -> tuple[Path, list[str]]:
    """网表+相对引用依赖 staging 进 work_dir（保持相对子结构）。

    网表已在 work_dir 内 → 原位零复制返回（staged 空）。返回
    ``(staged 网表路径, staged 相对名清单)``；绝对路径引用不复制（本地
    原样解析，存在性已由 validate 保证）。``..`` 引用已在 validate 拦截，
    此处跳过不复制。
    """
    staged: list[str] = []
    netlist_dir = netlist_path.resolve().parent
    for raw in scan_netlist_file_refs(netlist_path):
        if raw.startswith("\\\\") or _DRIVE_RE.match(raw):
            continue
        parts = [p for p in raw.replace("\\", "/").split("/")
                 if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            continue
        src = netlist_dir.joinpath(*parts)
        dst = work_dir.joinpath(*parts)
        if src.is_file() and not _same_path(src, dst):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            staged.append("/".join(parts))
    if _same_path(netlist_dir, work_dir.resolve()):
        return netlist_path, staged
    dst_nl = work_dir / netlist_path.name
    shutil.copy2(netlist_path, dst_nl)
    staged.insert(0, netlist_path.name)
    return dst_nl, staged


# ─── 内置发射器 ──────────────────────────────────────────────────────────────

@register_launcher("local")
def _launch_local(
    netlist_name: str, work_dir: Path, log_handle: Any, opts: dict[str, Any],
) -> tuple[list[str], Any, dict[str, Any]]:
    """local 发射器：本机 subprocess 直跑 hpeesofsim（cwd=工作目录）。

    env 构造导入复用 ads_netlist._build_ads_env（HPEESOF_DIR + PATH 前置
    bin/adsptolemy/tools-python，ads_python_api.run_simulation 内联构造的
    同域可复用形态，见模块 docstring 出注）。
    """
    ads_dir = _resolve_ads_dir(opts.get("ads_dir"))
    env = _build_ads_env(ads_dir)
    cmd = [str(ads_dir / "bin" / "hpeesofsim.exe"), netlist_name]
    proc = subprocess.Popen(
        cmd, cwd=str(work_dir), env=env,
        stdout=log_handle, stderr=subprocess.STDOUT,
    )
    logger.info("ads_batch[local]: %s (cwd=%s)", " ".join(cmd), work_dir)
    return cmd, proc, {"ads_dir": str(ads_dir)}


@register_launcher("ssh")
def _launch_ssh(
    netlist_name: str, work_dir: Path, log_handle: Any, opts: dict[str, Any],
) -> tuple[list[str], Any, dict[str, Any]]:
    """ssh 发射器：参数化主机 ssh 命令行（远端命令串 PS 原生形态）。

    远端命令串内路径经 ``check_remote_path_safe`` fail-closed 守卫（单
    引号/空白拒绝，见 build_remote_hpeesofsim_command 引号转义纪律）。
    本地 cwd 不参与远端语义（远端自行 Set-Location）。
    """
    host = opts.get("ssh_host")
    remote_ads = check_remote_path_safe(
        "remote_hpeesof_dir", str(opts.get("remote_hpeesof_dir") or ""))
    remote_wd = check_remote_path_safe(
        "remote_work_dir", str(opts.get("remote_work_dir") or ""))
    name = check_remote_path_safe("网表文件名", netlist_name)
    remote_cmd = build_remote_hpeesofsim_command(remote_ads, remote_wd, name)
    argv = build_ssh_command(
        str(opts.get("ssh_exe") or "ssh"), str(host), remote_cmd,
        port=opts.get("ssh_port"), extra_options=opts.get("ssh_options"),
    )
    proc = subprocess.Popen(argv, stdout=log_handle, stderr=subprocess.STDOUT)
    logger.info("ads_batch[ssh]: %s@%s", host, remote_wd)
    return argv, proc, {
        "ads_dir": remote_ads,
        "remote_command": remote_cmd,
        "remote_dataset": f"{remote_wd}\\{name}.ds",
        "ssh_host": str(host),
    }


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def ads_batch_solve(
    netlist_path: str | Path,
    launcher: str = "local",
    *,
    ads_dir: str | Path | None = None,
    workdir: str | Path | None = None,
    timeout_s: float = 3600.0,
    artifact_limit: int = MAX_ARTIFACTS,
    ssh_host: str | None = None,
    ssh_port: int | None = None,
    ssh_exe: str = "ssh",
    ssh_options: list[str] | None = None,
    remote_hpeesof_dir: str | None = None,
    remote_work_dir: str | None = None,
) -> dict[str, Any]:
    """ADS 网表批求解（发射器可插拔：local 直跑 / ssh 参数化主机）。

    流程：网表存在性 → ssh 参数完备性（ssh 模式）→ 自包含检查（#276
    fail-fast，零 Popen 零落盘）→ 工作目录解析+staging → 发射器 dispatch
    → ``Watchdog`` 超时整树击杀（hfss_batch._kill_process_tree 复用）→
    logfile 尾部回读 + 产物扫描（local）→ 结构化结果。

    参数：
    - ``launcher``：``"local"``（缺省）或 ``"ssh"``（registry 可扩展）。
    - ``ads_dir``：local 模式 ADS 安装根（None 走 _resolve_ads_dir 链：
      RFAUTO_HPEESOF_DIR env > settings.local.yaml hpeesof_dir > 兜底）。
    - ``workdir``：工作目录（缺省=网表所在目录原位执行；显式给出且网表
      不在其中时 staging 网表+相对依赖进该目录执行副本）。
    - ``timeout_s``：看门超时（秒），到点整树击杀并如实记 ``timed_out``；
      ``<=0`` 不设超时（hfss_batch 同语义）。ssh 模式击杀只及本地 ssh
      客户端进程树（远端孤儿面见模块 docstring 诚实面）。
    - ``artifact_limit``：产物扫描条目上限（防巨型目录拖死返回面）。
    - ``ssh_host``/``ssh_port``/``ssh_exe``/``ssh_options``：ssh 发射参数
      （host 可 ``user@host`` 形态；凭据零持有走 BatchMode）。
    - ``remote_hpeesof_dir``/``remote_work_dir``：远端 ADS 安装根 / 批次
      工作目录（禁 D:\\CloudDrive 语义由调用方遵守；路径禁单引号/空白）。

    返回（hfss_batch.solve_project_batch 同形结构化 dict，零数值面）：
    ``{ok, rc, timed_out, launcher, command, ads_dir, netlist, workdir,
    logfile, logfile_tail, artifacts, staged, remote_command,
    remote_dataset, elapsed_s, errors}``——``ok`` 仅在 ``rc==0 且未超时``
    为真；``rc=None`` 表示前置失败未拉起进程（此时 ``errors`` 说明原因）。
    ssh 模式 ``artifacts=[]``（远端枚举/回拉归 service.remote_ads_run 通道），
    ``remote_dataset`` 给出远端数据集预期路径。
    """
    started = time.monotonic()
    errors: list[str] = []
    netlist = Path(netlist_path)

    def _fail(msgs: list[str], **fields: Any) -> dict[str, Any]:
        env: dict[str, Any] = {
            "ok": False, "rc": None, "timed_out": False,
            "launcher": launcher, "command": [],
            "ads_dir": "", "netlist": str(netlist),
            "workdir": "", "logfile": "", "logfile_tail": "",
            "artifacts": [], "staged": [],
            "remote_command": None, "remote_dataset": None,
            "elapsed_s": round(time.monotonic() - started, 3),
            "errors": list(msgs),
        }
        env.update(fields)
        if env["logfile"]:
            env["logfile_tail"] = read_logfile_tail(
                env["logfile"], LOGFILE_TAIL_LINES)
        return env

    if launcher not in _LAUNCHERS:
        return _fail([f"未知发射器: {launcher!r}（可用: {sorted(_LAUNCHERS)}）"])
    if not netlist.is_file():
        return _fail([f"网表文件不存在: {netlist}"])
    if launcher == "ssh":
        missing = [
            nm for nm, v in (
                ("ssh_host", ssh_host),
                ("remote_hpeesof_dir", remote_hpeesof_dir),
                ("remote_work_dir", remote_work_dir),
            ) if not v
        ]
        if missing:
            return _fail(
                [f"ssh 发射缺少参数: {', '.join(missing)}（远端主机/ADS 根/"
                 "批次工作目录为必填）"])

    # 自包含检查（#276 fail-fast：缺失/绝对路径越界即拒，零 Popen 零落盘）
    ref_errors = validate_netlist_self_containment(
        netlist, portable=(launcher == "ssh"))
    if ref_errors:
        return _fail(ref_errors)

    # 工作目录解析 + staging
    work_dir = Path(workdir) if workdir else netlist.parent
    staged: list[str] = []
    run_netlist = netlist
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        run_netlist, staged = stage_netlist_bundle(netlist, work_dir)
    except OSError as exc:
        return _fail([f"工作目录不可用或 staging 失败: {work_dir}（{exc}）"],
                     workdir=str(work_dir))

    logfile = work_dir / BATCH_LOGFILE_FMT.format(stem=run_netlist.stem)
    opts: dict[str, Any] = {
        "ads_dir": ads_dir,
        "ssh_host": ssh_host, "ssh_port": ssh_port, "ssh_exe": ssh_exe,
        "ssh_options": ssh_options,
        "remote_hpeesof_dir": remote_hpeesof_dir,
        "remote_work_dir": remote_work_dir,
    }
    cmd: list[str] = []
    meta: dict[str, Any] = {}
    timed_out = False
    rc: int | None = None
    try:
        # console 输出追加进 logfile（句柄直写无管道死锁面，hfss_batch 同款）
        with open(logfile, "ab") as log_handle:
            cmd, proc, meta = _LAUNCHERS[launcher](
                run_netlist.name, work_dir, log_handle, opts)
            guard = Watchdog()
            if timeout_s and timeout_s > 0:
                guard.start(timeout_s, lambda: _on_watchdog_fire(proc.pid))
            try:
                rc = proc.wait()
            except BaseException:
                # 异常路径（含 KeyboardInterrupt）也整树回收，不留孤儿进程
                guard.cancel()
                _kill_process_tree(proc.pid)
                with contextlib.suppress(subprocess.SubprocessError):
                    proc.wait(timeout=10.0)
                raise
            finally:
                guard.cancel()
            timed_out = guard.fired
    except AdsBatchError as exc:
        return _fail([f"发射前置检查失败: {exc}"],
                     workdir=str(work_dir), logfile=str(logfile))
    except FileNotFoundError as exc:
        # _resolve_ads_dir：找不到可用 ADS 安装（含 tried 清单的明确报错）
        return _fail([f"ADS 安装不可用: {exc}"],
                     workdir=str(work_dir), logfile=str(logfile))
    except OSError as exc:
        return _fail([f"{launcher} 发射进程拉起失败: {exc}"],
                     workdir=str(work_dir), logfile=str(logfile))

    if timed_out:
        msg = (f"求解超时（>{timeout_s:.0f}s），进程树已整树击杀"
               f"（击杀后退出码 rc={rc}）")
        if launcher == "ssh":
            msg += ("（ssh 发射：仅本地 ssh 客户端被回收，远端孤儿面由 "
                    "remote_ads 通道互斥预检+任务毕清理兜底）")
        errors.append(msg)
    elif rc != 0:
        errors.append(
            f"{launcher} 发射进程退出码非零: rc={rc}（详见 logfile 尾部）")

    # 产物扫描仅 local（ssh 模式远端枚举/sftp 回拉归 service.remote_ads_run）；
    # 网表 File= 引用输入从清单排除（输入依赖与产物同为 .sNp 白名单形态）
    artifacts = (
        collect_ads_artifacts(
            work_dir, artifact_limit,
            exclude=_netlist_input_paths_in_workdir(run_netlist, work_dir))
        if launcher == "local" else []
    )

    return {
        "ok": bool(rc == 0 and not timed_out),
        "rc": rc,
        "timed_out": bool(timed_out),
        "launcher": launcher,
        "command": cmd,
        "ads_dir": str(meta.get("ads_dir", "")),
        "netlist": str(run_netlist),
        "workdir": str(work_dir),
        "logfile": str(logfile),
        "logfile_tail": read_logfile_tail(logfile, LOGFILE_TAIL_LINES),
        "artifacts": artifacts,
        "staged": staged,
        "remote_command": meta.get("remote_command"),
        "remote_dataset": meta.get("remote_dataset"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "errors": errors,
    }


def _on_watchdog_fire(pid: int) -> None:
    """watchdog 到点回调：整树击杀（只对自己 Popen 的子进程，#245 不盲杀）。"""
    logger.warning("ads_batch: pid=%s 超时，整树击杀", pid)
    _kill_process_tree(pid)
