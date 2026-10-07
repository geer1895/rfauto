"""remote_ads_service —— ADS 网表远跑通道（多机协同 v1）。

hpeesofsim 网表远跑四步+互斥预检：⓪发射前互斥预检（#261，
共享单源 remote_mutex_precheck，命中=候跑 SKIP）→ ①sftp 上传网表+依赖
（自包含化检查，#276）→ ②服务器侧
hpeesofsim 执行（env 形态=#272 同款）→ ③数据集 sftp 逐文件回拉+服务器
侧工作目录清理 → ④本地判读钩子（最小=dataset 路径+rc/stdout 落账；
复用既有对拍面 ``ads_netlist.parse_dataset/parse_hb_dataset`` 由调用方
在本机有 ADS 时消费，通道本体不要求本机装 ADS）。

执行模型取舍（playbook G7 连坐 / G8 缺省 shell，2026-09-29 定案）：

- **同步路径**：ADS HB/SP 网表求解一般秒-分钟级 → SSH ``run_command``
  阻塞等待（``exec_timeout_s`` 可调）。G7（Win32-OpenSSH 会话 job
  object 连坐）只威胁"通道关闭后还要活"的持久进程——同步等待期内通道
  必然存活、进程自然结束，无需 schtasks；>10min 长任务才应走 schtasks
  once 任务+产物轮询（v2 备选，本版未落，登记 playbook §6）。
- **PS 原生命令**：服务器缺省 shell=PowerShell（G8）；PS 5.1 不认
  ``&&`` 语句分隔符（cmd /c 长 && 链不可用），且双引号经 SSH→PS 链
  被剥（G5）——命令一律 PS 原生 ``;`` 分隔+单引号包裹路径（零双引号
  纪律；remote_service L2 真跑同款形态，含 ``;`` 链与 ``$_`` 管道）。
- **rc 透传**：PowerShell 对原生 exe 的会话退出码恒 0——命令尾
  ``exit $LASTEXITCODE`` 显式透传 hpeesofsim 退出码；exe 缺失/pre-check
  失败走显式 ``exit 3``（fail-closed 可判读）。
- **env 注入=#272 同款**：``HPEESOF_DIR``=服务器 ADS 安装根 + PATH 前置
  ``bin``/``adsptolemy\\lib.win32_64``/``tools\\python``（0xC0000135 缺
  DLL 同根因，服务器侧 ADS 根=注册表 ``ads.hpeesof_dir``，本机实测
  形态见 ads_netlist._build_ads_env）。

服务器侧约束（远程资源说明 §10/ 0b）：工作根=注册表
``hfss.project_root``（E:\\rfauto_remote 语义，**禁 D:\\CloudDrive**），
批次子目录 ``ads_<uuid8>`` 唯一化（并发批次不互踩）；发射前互斥预检
（#261 每机互斥，X4 批推广，共享单源
``remote_service.remote_mutex_precheck``：hpeesofsim 进程指纹直查=权威
判据 + run_server_probe.ps1 census mutex 行=旁证；命中=候跑 SKIP，
**禁止代杀**）；任务毕清理（Remove-Item + Test-Path 复核留痕，清理失败
翻 FAIL——任务毕必须清理）。

真机 opt-in 门：env ``RFAUTO_REMOTE_SMOKE=1``（与 remote_service 同门
单源 import；unit 门内一律拒绝，#139/df4⑥ 零真机零连网）。
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from rfauto.core.errors import RFAutoError
from rfauto.infra.remote_machines import (
    ENV_REMOTE_SSH_PASSWORD,
    ENV_REMOTE_SSH_USER,
    RemoteConfigError,
    SshTransport,
    load_remote_machines,
    probe_machine,
    resolve_machine,
)
from rfauto.service.envelope import skipped_envelope
from rfauto.service.remote_service import (
    REMOTE_SMOKE_ENV,
    remote_mutex_precheck,
)

__all__ = [
    "ADS_MUTEX_FINGERPRINT",
    "ADS_MUTEX_PROCESS",
    "REMOTE_ADS_ENV",
    "RemoteAdsError",
    "remote_ads_run",
]

#: 真机 opt-in 门 env 名（与 remote_service.REMOTE_SMOKE_ENV 同值单源；
#: 本域别名便于驱动/测试可读）。
REMOTE_ADS_ENV = REMOTE_SMOKE_ENV

#: #261 互斥预检进程域+指纹（X4 批推广）：本机任一 hpeesofsim 求解进程
#: 在跑=候跑（每机单席位语义，宁枉勿纵；预检发生在本批发射前=无 #261
#: 自锁面）。指纹只作命令行二次过滤（exe 名已在进程域钉住）。
ADS_MUTEX_PROCESS = "hpeesofsim.exe"
ADS_MUTEX_FINGERPRINT = "hpeesofsim"

# 网表 File= 引用扫描（双引号形态——ads_netlist.generate_netlist 产出口径；
# ADS 网表组件行 File="path" 惯例）。\bfile 边界使 Filename= 类键不误中。
_FILE_REF_RE = re.compile(r'(?i)\bfile\s*=\s*"([^"]*)"')
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_BATCH_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


class RemoteAdsError(RFAutoError):
    """ADS 远跑通道前置检查失败（自包含化/路径安全/输入非法）。"""


# ─── 纯函数前置检查（零 SSH，可独立单测） ─────────────────────────────────


def _plan_netlist_dependencies(netlist_path: Path) -> list[dict[str, str]]:
    """扫描网表 ``File="..."`` 引用，产出依赖上传计划（#276 自包含化检查）。

    - 绝对路径引用（盘符 ``X:``/UNC ``\\\\``）→ 显式报错：服务器无法解析
      本机绝对路径（#276 复用雷——SnP File= 写死临时目录的网表直接复跑
      必炸），必须先自包含化（依赖放网表旁+改相对路径）；
    - 相对路径引用 → 解析到网表同目录，本地存在才入计划（缺文件同样
      显式报错）；``..`` 越界引用拒绝（路径注入面守卫）；
    - 同一引用去重（多个组件引用同文件只传一份）。

    Returns
    -------
    list[dict]
        ``[{"ref": 原文, "local": 本地绝对路径, "remote_rel": 相对网表目录
        的远端布局（ 分隔）}]``。无 File= 引用 → 空表（自包含）。
    """
    text = netlist_path.read_text(encoding="utf-8", errors="replace")
    netlist_dir = netlist_path.resolve().parent
    plan: dict[str, dict[str, str]] = {}
    for m in _FILE_REF_RE.finditer(text):
        raw = m.group(1).strip()
        if not raw:
            continue
        if raw.startswith("\\\\") or _DRIVE_RE.match(raw):
            raise RemoteAdsError(
                f'网表引用绝对路径依赖（File="{raw}"）——服务器无法解析本机'
                "路径（#276 复用雷）；请先自包含化：依赖文件放网表旁并改"
                "相对路径后再远跑",
                details={"ref": raw[:120]},
            )
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise RemoteAdsError(
                f"网表依赖引用越界或为空（.. / 空）: {raw!r}",
                details={"ref": raw[:120]},
            )
        local = netlist_dir.joinpath(*parts)
        if not local.is_file():
            raise RemoteAdsError(
                f"网表依赖文件本地缺失: {raw}（#276：复用非自包含网表先补齐"
                "依赖文件）",
                details={"ref": raw[:120], "expected_local": str(local)},
            )
        remote_rel = "/".join(parts)
        if remote_rel not in plan:
            plan[remote_rel] = {
                "ref": raw, "local": str(local), "remote_rel": remote_rel,
            }
    return list(plan.values())


def _check_remote_safe(label: str, value: str) -> str:
    """远端命令注入面守卫：路径禁单引号与空白。

    远端命令形态=PS 原生单引号（G5 零双引号纪律），含单引号/空白的路径
    无法安全引用——fail-closed 显式拒绝（E:\\rfauto_remote /
    E:\\ADS27\\ADS2027 等登记路径均天然满足）。
    """
    v = value.replace("/", "\\")
    if "'" in v or any(ch.isspace() for ch in v):
        raise RemoteAdsError(
            f"{label} 含单引号或空白（远端 PS 命令零双引号纪律，无法安全"
            "引用）",
            details={"label": label, "value": value[:80]},
        )
    return v


def _build_hpeesofsim_command(
    ads_dir: str, work_dir: str, exe_name: str, netlist_name: str,
) -> str:
    """组装服务器侧 hpeesofsim 执行命令（PS 原生，#272 env 形态）。

    形态（零双引号，G5；``;`` 链，G8；rc 显式透传，$null 守卫防 exe
    启动失败残留上一次 $LASTEXITCODE）::

        $env:HPEESOF_DIR='<ads>';
        $env:PATH='<ads>\\bin;<ads>\\adsptolemy\\lib.win32_64;<ads>\\tools\\python;' + $env:PATH;
        Set-Location -LiteralPath '<wd>';
        if (-not (Test-Path -LiteralPath '<exe>')) { Write-Output 'HPEESOFSIM_NOT_FOUND'; exit 3 }
        & '<exe>' '<netlist>'; $rc = $LASTEXITCODE; if ($null -eq $rc) { exit 1 }; exit $rc
    """
    ads = ads_dir.replace("/", "\\")
    wd = work_dir.replace("/", "\\")
    path_pre = ";".join([
        f"{ads}\\bin",
        f"{ads}\\adsptolemy\\lib.win32_64",
        f"{ads}\\tools\\python",
    ])
    exe = f"{ads}\\bin\\{exe_name}"
    return (
        f"$env:HPEESOF_DIR='{ads}'; "
        f"$env:PATH='{path_pre};' + $env:PATH; "
        f"Set-Location -LiteralPath '{wd}'; "
        f"if (-not (Test-Path -LiteralPath '{exe}')) "
        "{ Write-Output 'HPEESOFSIM_NOT_FOUND'; exit 3 }; "
        f"& '{exe}' '{netlist_name}'; "
        "$rc = $LASTEXITCODE; if ($null -eq $rc) { exit 1 }; exit $rc"
    )


def _cleanup_remote_workdir(
    transport: SshTransport, work_dir: str,
) -> dict[str, Any]:
    """删除服务器侧批次工作目录并 Test-Path 复核（任务毕必须清理）。

    Remove-Item 带 -ErrorAction SilentlyContinue 可能 rc=0 却部分失败——
    以删后 ``Test-Path=False`` 为真判据（verified_gone）。
    """
    rc, _out, err = transport.run_command(
        f"Remove-Item -LiteralPath '{work_dir}' -Recurse -Force "
        "-ErrorAction SilentlyContinue",
        timeout_s=60.0,
    )
    _rc2, out2, _e2 = transport.run_command(
        f"Test-Path -LiteralPath '{work_dir}'", timeout_s=20.0,
    )
    verified = out2.strip() == "False"
    return {
        "ok": bool(rc == 0 and verified),
        "work_dir": work_dir,
        "rc": rc,
        "verified_gone": verified,
        "stderr_head": err[:200],
    }


# ─── 主编排（JSON 信封进出，fail-closed） ─────────────────────────────────


def remote_ads_run(
    netlist_path: str | Path,
    machine: str | None = None,
    *,
    out_dir: str | Path | None = None,
    batch_name: str | None = None,
    extra_files: list[str | Path] | None = None,
    dataset_stem: str | None = None,
    exec_timeout_s: float = 600.0,
    keep_remote: bool = False,
) -> dict[str, Any]:
    """ADS 网表远跑五步编排（**真机 opt-in**：env ``RFAUTO_REMOTE_SMOKE=1``）。

    编排：探活 → 前置检查（凭据/配置/网表自包含化，#276）→ SSH → 互斥
    预检（#261 每机互斥，X4 批推广，命中=候跑 SKIP 不上传不发射）→ 建批次
    工作目录（``<project_root>\\ads_<uuid8>``，New-Item -Force 幂等，G13）
    → sftp 上传网表+依赖+extra → 服务器侧 hpeesofsim 同步执行（#272 env
    形态，rc 经 ``exit $LASTEXITCODE`` 透传）→ 数据集 ``<stem>.ds`` sftp
    逐文件回拉本地镜像 → finally 清理服务器侧工作目录（Test-Path 复核，
    清理失败翻 FAIL；``keep_remote=True`` 调试留档须如实落账）。

    Parameters
    ----------
    netlist_path :
        本地网表文件（自包含化检查通过才上传；``File="..."`` 相对依赖自动
        同传，绝对路径/缺依赖显式报错）。
    machine :
        注册表机器名（None=唯一登记机器）。
    out_dir :
        回拉产物目录（缺省 ``runs/remote_ads/<YYYYMMDD>/``）；数据集镜像
        落 ``<out_dir>/<stem>.ds/``。
    batch_name :
        批次目录名（缺省 ``ads_<uuid8>`` 唯一化；显式给定时限
        ``[A-Za-z0-9_-]``，重复批次名会清空远端旧批次目录——调用方自负）。
    extra_files :
        额外随传文件（平铺进批次目录）。
    dataset_stem :
        数据集名（缺省=网表文件名主干；hpeesofsim 缺省产出
        ``<网表主干>.ds``，网表内显式 DATASET_EXPORT 指名时在此覆盖）。
    exec_timeout_s :
        同步执行等待上限（run_command 通道超时；超时=链路异常 fail-closed）。
    keep_remote :
        True=跳过服务器侧清理（调试留档；steps.cleanup 如实 skipped，任务
        毕须人工清理—— 0b 清理铁律不豁免只展期）。

    Returns
    -------
    dict
        成功：``{"ok": True, "verdict": "PASS", "machine", "batch",
        "work_dir_remote", "netlist_local", "netlist_remote",
        "dataset_remote", "dataset_local", "exec_rc": 0, "criteria":
        {"c0_mutex_clear", "c1_rc0", "c2_dataset_nonempty",
        "c3_workdir_cleaned"}, "steps":
        {probe/ssh/mutex/upload/exec/fetch/cleanup}}``。
        前置不满足：``{"ok": False, "skipped": True, "reason", "steps"}``；
        执行失败/异常：fail-closed 信封（rc≠0 透传、缺产物报错、清理失败
        翻 FAIL，绝不静默）。
    """
    # ── 前置（纯本地，零 SSH） ──
    if os.environ.get(REMOTE_ADS_ENV) != "1":
        return skipped_envelope(
            f"真机远跑需显式 opt-in：{REMOTE_ADS_ENV}=1（unit 门零真机）",
            ok=False,
        )
    machines = load_remote_machines()
    if machine is None and not machines:
        return skipped_envelope("无登记机器", ok=False)
    try:
        cfg = resolve_machine(machine, machines)
    except RemoteConfigError as exc:
        # 机器名未登记/多机未指名（ge5 审查 F3）：裸抛改 fail-closed 信封
        # （与 remote_oe_service 同批同构，两通道行为不分叉）。
        return skipped_envelope(
            f"机器解析失败（注册表无此名或多机未指名）: {exc}", ok=False)
    steps: dict[str, Any] = {"probe": probe_machine(cfg)}

    has_user = bool(cfg.ssh_user or os.environ.get(ENV_REMOTE_SSH_USER))
    has_secret = bool(
        cfg.ssh_key_path or cfg.ssh_password
        or os.environ.get(ENV_REMOTE_SSH_PASSWORD)
    )
    if not (has_user and has_secret):
        steps["ssh"] = {"auth": "missing_credentials"}
        return skipped_envelope(
            "SSH 凭据缺失（RFAUTO_REMOTE_SSH_USER/PASSWORD 或 local 覆盖）",
            ok=False, steps=steps,
        )
    if not cfg.ads_hpeesof_dir:
        return skipped_envelope(
            "机器未登记 ads.hpeesof_dir（服务器侧 ADS 安装根，"
            "hpeesofsim env 构造必需）",
            ok=False, steps=steps,
        )
    if not cfg.hfss_project_root:
        return skipped_envelope(
            "机器未登记 hfss.project_root（服务器侧工作根，"
            "禁 D:\\CloudDrive 语义靠此钉）",
            ok=False, steps=steps,
        )

    netlist = Path(netlist_path)
    if not netlist.is_file():
        return {
            "ok": False,
            "reason": f"本地网表不存在: {netlist}",
            "steps": steps,
        }
    try:
        deps = _plan_netlist_dependencies(netlist)
        ads_dir = _check_remote_safe("ads.hpeesof_dir", cfg.ads_hpeesof_dir)
        work_root = _check_remote_safe("hfss.project_root", cfg.hfss_project_root)
        netlist_name = _check_remote_safe("网表文件名", netlist.name)
        extra_locals = [Path(p) for p in (extra_files or [])]
        for p in extra_locals:
            if not p.is_file():
                raise RemoteAdsError(
                    f"extra 随传文件不存在: {p}", details={"path": str(p)},
                )
            _check_remote_safe("extra 文件名", p.name)
        if batch_name is not None and not _BATCH_RE.fullmatch(batch_name):
            raise RemoteAdsError(
                "batch_name 只允许字母/数字/_/-",
                details={"batch": batch_name},
            )
    except RemoteAdsError as exc:
        return {
            "ok": False,
            "reason": str(exc)[:240],
            "steps": steps,
        }

    batch = batch_name or f"ads_{uuid.uuid4().hex[:8]}"
    # hpeesofsim 数据集命名 = 网表文件全名（含扩展名）+ ".ds"——先例
    # cascade_netlist.txt → cascade_netlist.txt.ds（runs/branchline_real_anchor/
    # anchor）；真机首跑实证 <stem>.ds 推导 Test-Path=False 假阴性。
    # 显式 dataset_stem 仍最高优先（DATASET_EXPORT 指名时用）。
    ds_name = (
        f"{Path(dataset_stem).name}.ds" if dataset_stem else f"{netlist.name}.ds"
    )
    work_dir = f"{work_root}\\{batch}"
    ds_win = f"{work_dir}\\{ds_name}"
    out_path = (
        Path(out_dir) if out_dir is not None
        else Path("runs") / "remote_ads" / time.strftime("%Y%m%d")
    )
    ds_local = out_path / ds_name
    work_dir_sftp = work_dir.replace("\\", "/")

    envelope: dict[str, Any] = {
        "ok": False,
        "verdict": "FAIL",
        "skipped": False,
        "reason": None,
        "machine": cfg.name,
        "batch": batch,
        "work_dir_remote": work_dir,
        "netlist_local": str(netlist),
        "netlist_remote": f"{work_dir}\\{netlist_name}",
        "dataset_remote": ds_win,
        "dataset_local": str(ds_local),
        "exec_rc": None,
        "criteria": {"c0_mutex_clear": None},
        "steps": steps,
    }

    transport = SshTransport(cfg)
    try:
        transport.connect()
        steps["ssh"] = {"auth": "ok"}

        # ⓪ 互斥预检（#261 每机互斥，X4 批推广；命中=候跑 SKIP，不上传
        #    不发射，绝不代杀——先于批次目录创建，busy 路径零服务器落盘）。
        #    候跑信封走 skipped_envelope 构造器（契约 §4：新增信封不走裸
        #    dict；字段集与主信封同形，供消费方按 batch/work_dir 对账）。
        mutex = remote_mutex_precheck(
            transport, work_root,
            process_name=ADS_MUTEX_PROCESS,
            fingerprint=ADS_MUTEX_FINGERPRINT,
        )
        steps["mutex"] = mutex
        envelope["criteria"]["c0_mutex_clear"] = not mutex["busy"]
        if mutex["busy"]:
            return skipped_envelope(
                mutex.get("reason") or "互斥命中=候跑（#261，禁止代杀）",
                ok=False,
                machine=cfg.name,
                batch=batch,
                work_dir_remote=work_dir,
                netlist_local=str(netlist),
                netlist_remote=f"{work_dir}\\{netlist_name}",
                dataset_remote=ds_win,
                dataset_local=str(ds_local),
                exec_rc=None,
                criteria=dict(envelope["criteria"]),
                steps=steps,
            )

        # ① 上传：建批次目录（New-Item -Force 幂等，G13）→ 依赖子目录 →
        # sftp 逐文件（依赖/extra/网表）。
        rc, _out, err = transport.run_command(
            f"New-Item -ItemType Directory -Force -Path '{work_dir}' | Out-Null",
            timeout_s=20.0,
        )
        if rc != 0:
            envelope["reason"] = f"服务器侧批次目录创建失败: {err[:120]}"
            return envelope

        upload_rec: dict[str, Any] = {
            "netlist_remote": envelope["netlist_remote"],
            "deps": [],
            "extra": [],
            "n_files": 0,
            "bytes": 0,
        }

        def _do_upload(local: Path, remote_sftp: str) -> None:
            transport.upload_file(local, remote_sftp)
            upload_rec["n_files"] += 1
            upload_rec["bytes"] += local.stat().st_size

        made_dirs: set[str] = set()
        for dep in deps:
            rel_dir = dep["remote_rel"].rsplit("/", 1)[0]
            if "/" in dep["remote_rel"] and rel_dir not in made_dirs:
                sub_win = f"{work_dir}\\{rel_dir.replace('/', chr(92))}"
                rc, _o, e = transport.run_command(
                    f"New-Item -ItemType Directory -Force -Path '{sub_win}' "
                    "| Out-Null",
                    timeout_s=20.0,
                )
                if rc != 0:
                    envelope["reason"] = (
                        f"服务器侧依赖子目录创建失败: {e[:120]}"
                    )
                    return envelope
                made_dirs.add(rel_dir)
            transport.upload_file(
                Path(dep["local"]),
                f"{work_dir_sftp}/{dep['remote_rel']}",
            )
            upload_rec["deps"].append({
                "ref": dep["ref"], "remote": dep["remote_rel"],
            })
            upload_rec["n_files"] += 1
            upload_rec["bytes"] += Path(dep["local"]).stat().st_size
        for p in extra_locals:
            _do_upload(p, f"{work_dir_sftp}/{p.name}")
        _do_upload(netlist, f"{work_dir_sftp}/{netlist_name}")
        steps["upload"] = upload_rec

        # ② 执行：PS 原生同步等待（G8/G5 形态见 _build_hpeesofsim_command）。
        cmd = _build_hpeesofsim_command(
            ads_dir, work_dir, "hpeesofsim.exe", netlist_name,
        )
        t0 = time.monotonic()
        rc, out, err = transport.run_command(cmd, timeout_s=exec_timeout_s)
        wall = time.monotonic() - t0
        steps["exec"] = {
            "rc": rc,
            "wall_s": round(wall, 1),
            "command": cmd,
            "stdout_tail": out[-2000:],
            "stderr_head": err[:500],
        }
        envelope["exec_rc"] = rc
        if rc != 0:
            envelope["reason"] = (
                f"hpeesofsim 服务器侧非零退出（rc={rc}，透传；"
                f"stdout 尾: {out.strip()[-200:] or '空'}）"
            )
            return envelope

        # ③ 回拉：数据集存在性守卫 → 逐文件枚举 → sftp 本地镜像。
        rc, out, _e = transport.run_command(
            f"Test-Path -LiteralPath '{ds_win}'", timeout_s=20.0,
        )
        if out.strip() != "True":
            envelope["reason"] = (
                f"服务器侧数据集未落盘（Test-Path=False: {ds_win}）——"
                "核对网表分析块/DATASET_EXPORT 与 dataset_stem 口径"
            )
            return envelope
        _rc, listing, _e = transport.run_command(
            f"Get-ChildItem -LiteralPath '{ds_win}' -Recurse -File "
            "-ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }",
            timeout_s=30.0,
        )
        remote_files = [
            ln.strip().replace("/", "\\")
            for ln in listing.splitlines()
            if ln.strip()
        ]
        if not remote_files:
            envelope["reason"] = (
                f"数据集枚举为空（{ds_win} 在档但无文件可回拉）"
            )
            return envelope
        fetch_rec: dict[str, Any] = {
            "dataset_remote": ds_win,
            "dataset_local": str(ds_local),
            "files": len(remote_files),
            "bytes": 0,
            "items": [],
        }
        ds_prefix = ds_win.lower() + "\\"
        ds_single_file = False
        for f_win in remote_files:
            # 路径注入面守卫：枚举结果必须落在数据集目录内（大小写不敏感
            # 前缀比对；Windows 文件系统大小写不敏感语义）。等值条目=数据集
            # 单文件形态（hpeesofsim 双形态：<name>.ds 目录含
            # Master.ai_datadb，或 <name>.ds 单文件数据）——整编回拉。
            if f_win.lower() == ds_win.lower():
                ds_single_file = True
                continue
            if not f_win.lower().startswith(ds_prefix):
                raise RemoteAdsError(
                    f"数据集枚举路径越出数据集目录: {f_win[:120]}",
                )
            rel = f_win[len(ds_win):].lstrip("\\/").replace("\\", "/")
            f_sftp = f_win.replace("\\", "/")
            f_local = ds_local / rel
            f_local.parent.mkdir(parents=True, exist_ok=True)
            transport.download_file(f_sftp, f_local)
            fetch_rec["bytes"] += f_local.stat().st_size
            fetch_rec["items"].append({"remote": f_sftp, "local": str(f_local)})
        if ds_single_file:
            ds_local.parent.mkdir(parents=True, exist_ok=True)
            transport.download_file(ds_win.replace("\\", "/"), ds_local)
            fetch_rec["bytes"] += ds_local.stat().st_size
            fetch_rec["items"].append(
                {"remote": ds_win.replace("\\", "/"), "local": str(ds_local)}
            )
            fetch_rec["form"] = "single_file"
        steps["fetch"] = fetch_rec

        # ④ 本地判读钩子（最小面）：dataset 路径+rc/stdout 已落账（envelope
        # dataset_local/exec_rc + steps.exec）；ads 对拍由调用方消费
        # ads_netlist.parse_dataset(dataset_local)（本机有 ADS 时）。
        envelope["ok"] = True
        envelope["verdict"] = "PASS"
        # 原位补键（不整体替换——c0_mutex_clear 已在互斥步落账，X4）
        envelope["criteria"]["c1_rc0"] = True
        envelope["criteria"]["c2_dataset_nonempty"] = fetch_rec["files"] >= 1
        return envelope
    except Exception as exc:  # fail-closed：链路裸抛也落失败信封（L2 同构）
        envelope["ok"] = False
        envelope["verdict"] = "FAIL"
        envelope["reason"] = (
            f"ADS 远跑链路异常: {type(exc).__name__}: {str(exc)[:160]}"
        )
        return envelope
    finally:
        # 任务毕必须清理：keep_remote 显式留档如实记；清理
        # 失败翻 FAIL（数据已回拉仍不许留远端垃圾）。cleanup 失败不阻塞
        # transport 关闭（best-effort 观测性纪律，#105 同源）。
        try:
            if keep_remote:
                cleanup: dict[str, Any] = skipped_envelope(
                    "keep_remote=True（调试留档，任务毕须人工清理）",
                    work_dir=work_dir,
                )
            else:
                cleanup = _cleanup_remote_workdir(transport, work_dir)
        except Exception as exc:
            cleanup = {
                "ok": False,
                "reason": f"清理异常: {type(exc).__name__}",
                "work_dir": work_dir,
            }
        steps["cleanup"] = cleanup
        if (
            envelope.get("ok")
            and not cleanup.get("ok", False)
            and not cleanup.get("skipped", False)
        ):
            envelope["ok"] = False
            envelope["verdict"] = "FAIL"
            envelope["reason"] = (
                "服务器侧工作目录清理未通过（任务毕必须清理， 0b）"
            )
        envelope["criteria"]["c3_workdir_cleaned"] = bool(
            cleanup.get("skipped") or cleanup.get("verified_gone")
        )
        transport.close()
