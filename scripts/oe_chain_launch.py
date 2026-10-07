"""OE 链式发射器（oe_chain_waiter 家族的版本化消费器，H1-5 收编）。

出处链：runs/ge8_followup/oe_chain_waiter.py（ge8b 批，gitignored 档案）
把战役 rc 只记日志不判链，而 fd_oe_campaign 修复前主退出码恒 0——全座
SKIP 被记成"OE 链完毕"（oe_chain.log 2026-10-03 K-7 实证，靠人工
k7_retry/k7_msring6 补位）→ H1 席审查 H1-5 → F6 修复席：fd_oe_campaign
按座位状态聚合退出码（表见其模块 docstring），本消费器按 rc 判链：
**上一步 rc==0 才串发下一项**，非 0 立即中止并透传该 rc。
runs/ 旧档案零改写（历史证据），新链式发射一律走本脚本。

census 守望门消费 scripts/census_status.py（H1-4 收编单源，宽匹配旁证，
宁枉勿纵：探针异常/非 CLEAR 一律不发射）。窄指纹直查的权威互斥门在
驱动与 remote_oe_service 内部，本脚本不重复实现。

退出码（scripts 退出码总表见 runs/review_ge8e/f6_scripts_fix/REPORT.md）：
  0=链内全部步骤 rc==0；其他=首个非 0 步骤的 rc 透传（链中止，步骤自身
  语义按 fd_oe_campaign 退出码表判读）；4=父心跳超时自尽（df7 范式）；
  2=等待 census CLEAR 超时交还人；64=argparse 用法错。

用法（--chain 传 JSON 步骤表，[{"tag","argv","log","env"}]，argv 相对
仓根解析；log/env 可缺省）：
  .venv/Scripts/python.exe scripts/oe_chain_launch.py --chain runs/xxx/chain.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CENSUS_CHK = REPO / "scripts" / "census_status.py"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"

CENSUS_POLL_S = 180
EXIT_WAIT_TIMEOUT = 2      # census 等待超时（交还人；与历史 oe_chain_waiter 同码）
EXIT_PARENT_TIMEOUT = 4    # 父心跳超时自尽（df7 范式，同 campaign_wait_launch）
EXIT_USAGE = 64            # argparse 用法错（避开 rc2 双义，H1-6 同族）


def log(msg: str, log_path: str | os.PathLike[str] | None = None) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def chain_should_continue(rc: int) -> tuple[bool, str]:
    """链闸（纯函数；waiter 侧 rc 判定函数——H1-5 回归钉面）。

    rc==0 → (True, "")；否则 (False, 原因)。修复前 oe_chain_waiter 对
    rc 只记不判，恒 0 的战役退出码让全座 SKIP 冒充链成功。"""
    if rc == 0:
        return True, ""
    return False, f"上一步 rc={rc} != 0——链中止（H1-5：rc 0 才算步完成）"


def run_chain(steps: list[dict], spawn, log_fn=log) -> int:
    """串行发射链（spawn 注入可离线钉）：任一步 rc!=0 即中止透传；
    全 0 → 0 并记"链完毕"。steps 元素为 {"tag", ...} dict。"""
    for step in steps:
        rc = int(spawn(step))
        log_fn(f"{step.get('tag', '?')} rc={rc}")
        ok, reason = chain_should_continue(rc)
        if not ok:
            log_fn(reason)
            return rc
    log_fn("OE 链完毕（全部步骤 rc=0）")
    return 0


def census_clear(run_census) -> bool:
    """census 宽匹配判定（纯注入面）：run_census() 返回探针单行输出；
    非 CLEAR（BUSY/异常/空）一律 False=不发射（宁枉勿纵，守望 best-effort
    不得转成盲发）。"""
    try:
        head = (run_census() or "").strip()
    except Exception as exc:
        log(f"census 检查异常（保守判忙）：{exc}")
        return False
    return head.startswith("CLEAR")


def wait_clear(run_census, *, max_wait_s: float, poll_s: float = CENSUS_POLL_S,
               heartbeat_path: str | os.PathLike[str] | None = None,
               heartbeat_timeout_s: float = 5400.0, sleep_fn=time.sleep,
               now_fn=time.time) -> int:
    """等 census CLEAR（轮询）：超时=EXIT_WAIT_TIMEOUT；父心跳超时自尽
    =EXIT_PARENT_TIMEOUT（df7 范式：会话死了守望者不得无人监督发射）；
    CLEAR=0。heartbeat 文件缺失时自 touch（与历史 oe_chain_waiter 同口径：
    心跳由发射会话周期续写，此处只做超时判读+兜底自持）。"""
    t0 = now_fn()
    while now_fn() - t0 < max_wait_s:
        if heartbeat_path is not None:
            try:
                if now_fn() - os.stat(heartbeat_path).st_mtime \
                        > heartbeat_timeout_s:
                    log("父心跳超时——链式守望自尽 exit 4")
                    return EXIT_PARENT_TIMEOUT
            except OSError:
                with open(heartbeat_path, "a", encoding="utf-8"):
                    pass
        if census_clear(run_census):
            return 0
        sleep_fn(poll_s)
    log(f"等待超时未得 CLEAR（{max_wait_s:.0f}s）——退出 exit "
        f"{EXIT_WAIT_TIMEOUT}")
    return EXIT_WAIT_TIMEOUT


def _resolve_arg(a: str) -> str:
    """argv 仓根锚定：scripts/、runs/、.venv 开头的相对段按仓根解析，
    其余（旗标/纯参数）与绝对路径原样透传。"""
    if Path(a).is_absolute() or not a.startswith(("scripts", "runs", ".venv")):
        return a
    return str(REPO / a)


def _spawn_step(step: dict) -> int:
    """真实步骤发射：venv python -u 执行 argv（cwd=仓根），stdout/stderr
    落步骤 log 文件（缺省 runs/oe_chain_launch/<tag>.log）。"""
    argv = [_resolve_arg(a) for a in step["argv"]]
    log_p = Path(step.get("log")
                 or (REPO / "runs" / "oe_chain_launch"
                     / f"{step.get('tag', 'step')}.log"))
    log_p.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(step.get("env") or {})
    log(f"{step.get('tag', '?')} 发射：{' '.join(argv[:3])}…")
    with open(log_p, "w", encoding="utf-8") as fh:
        proc = subprocess.run([str(PYTHON), "-u", *argv], cwd=str(REPO),
                              env=env, stdout=fh, stderr=subprocess.STDOUT)
    return int(proc.returncode)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--chain", required=True,
                        help="链步骤表 JSON（[{tag,argv,log,env}]；argv 相对"
                             "仓根解析）")
    parser.add_argument("--census-wait", action="store_true",
                        help="发射前等 census CLEAR（消费 scripts/"
                             "census_status.py；缺省直接发射）")
    parser.add_argument("--census-max-wait-s", type=float, default=8 * 3600)
    parser.add_argument("--parent-heartbeat", default=None,
                        help="父会话心跳文件（超时自尽 exit 4，df7 范式）")
    parser.add_argument("--parent-heartbeat-timeout-s", type=float,
                        default=5400.0)
    args = parser.parse_args(argv)
    try:
        steps = json.loads(Path(args.chain).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[oe-chain] 链表读取失败: {exc}", file=sys.stderr, flush=True)
        return EXIT_USAGE
    if not isinstance(steps, list) or not all(
            isinstance(s, dict) and "argv" in s for s in steps):
        print("[oe-chain] 链表形态非法（须为 [{tag,argv,log,env}] 列表）",
              file=sys.stderr, flush=True)
        return EXIT_USAGE

    def _run_census() -> str:
        proc = subprocess.run(
            [str(PYTHON), str(CENSUS_CHK)], capture_output=True, text=True,
            timeout=200)
        return (proc.stdout or "") + (proc.stderr or "")

    if args.census_wait:
        wrc = wait_clear(
            _run_census, max_wait_s=args.census_max_wait_s,
            heartbeat_path=args.parent_heartbeat,
            heartbeat_timeout_s=args.parent_heartbeat_timeout_s)
        if wrc != 0:
            return wrc
    return run_chain(steps, _spawn_step)


if __name__ == "__main__":
    sys.exit(main())
