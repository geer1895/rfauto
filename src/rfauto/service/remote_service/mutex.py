"""#261 每机互斥预检共享单源（remote_service T2 拆分子模块）。

三通道（HFSS gRPC/ADS hpeesofsim/openEMS runner）同构复用的互斥探针
命令构造与预检判定，指纹按通道语义词分（OE=python runner 家族 /
ADS=hpeesofsim / HFSS=本机注册端口 grpcsrv）；X4 批自
remote_oe_service._remote_mutex 提升泛化。aurora_h W3-S3 自
service/remote_service 巨石逐字节迁入（AU-1 facade，函数体零改动）。
"""

from __future__ import annotations

import re
from typing import Any

from rfauto.infra.remote_machines import SshTransport

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
