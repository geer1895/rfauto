"""census 宽匹配状态输出（H1-4 收编入仓版；runs/ 原版逻辑保持不变）。

出处链：ge8 批服务器作战（oe_chain.log 2026-10-03：K-7 全座 SKIP 被
"rc=0=链完毕"吞掉，人工 k7_retry 补位）→ H1 席审查 H1-4（守望判定与
驱动门"同源"靠约定不靠代码——原版散落在 gitignored 的
runs/ge8_server_batch/census_status.py，无版本控制、REPO 锚随位置巧合、
in_census 死变量）→ F6 修复席收编（2026-10-04，runs/ 原版零改写留档）。

语义（与 runs/ 原版逐行为同源）：SSH 跑服务器 kit census 探针
（run_server_probe.ps1），输出单行 ``CLEAR`` 或 ``BUSY:<cmd>``，供
oe_chain 守望家族消费。宽匹配判据=strip() 后以**大小写敏感** ``BUSY:``
开头的行（宁枉勿纵方向安全：判 BUSY ⇒ 服务器必有求解器进程；判 CLEAR
时驱动侧窄指纹直查仍为权威，见 remote_oe_service._remote_mutex）。
原版 29-32 行的 in_census 死变量（H1-4 登记：赋值从未消费）在此删除，
零行为差异。

单源立规（宽/窄双轨"同源"兑现为代码级）：宽匹配解析只此一份
（parse_census_probe），守望消费方（scripts/oe_chain_launch.py）只
import/调用本文件，禁止第三份副本；窄指纹单源=
rfauto.service.remote_oe_service._MUTEX_FINGERPRINT / build_mutex_command。
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ 的上一级=仓根（收编后层级：runs/ 原版用 parents[2] 因其多埋一层）。
REPO = Path(__file__).resolve().parents[1]
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rfauto.infra.remote_machines import SshTransport, load_remote_machines, resolve_machine  # noqa: E402

PROBE_COMMAND = (
    "powershell -NoProfile -ExecutionPolicy Bypass -File "
    "E:\\rfauto_remote\\kit\\06_tools\\run_server_probe.ps1")
PROBE_TIMEOUT_S = 180.0
MACHINE = "sim_host"


def parse_census_probe(text: str) -> str:
    """探针输出 → 单行 ``CLEAR`` / ``BUSY:<cmd>``（纯函数，离线可测）。

    与 runs/ 原版逐行为同源（H1-4 收编钉）：BUSY 行=strip() 后以
    大小写敏感 ``BUSY:`` 开头的行（``busy:`` 小写不命中=原版口径，宽匹配
    只认探针大写协议行）；命中时输出取**首个** BUSY 行 ``CMD=`` 前段
    （命令行截断防超长）；无命中=CLEAR。
    """
    busy = [ln for ln in text.splitlines() if ln.strip().startswith("BUSY:")]
    if not busy:
        return "CLEAR"
    return "BUSY:" + busy[0].split("BUSY:", 1)[1].split("CMD=")[0]


def main() -> int:
    cfg = resolve_machine(MACHINE, load_remote_machines())
    t = SshTransport(cfg)
    t.connect()
    try:
        _rc, out, err = t.run_command(PROBE_COMMAND,
                                      timeout_s=PROBE_TIMEOUT_S)
    finally:
        t.close()
    text = out or err or ""
    print(parse_census_probe(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
