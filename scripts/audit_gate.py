"""依赖漏洞常态化门（QM-4 周期化，2026-10-05 W1-E）——audit_deps 的门包装。

职责（runs/w1_phase1/criteria.md §W1-E）：
- 周期触发入口：本地计划任务/CI 定时跑本脚本；产物（门日志 + audit_deps
  门报告 JSON）按时间戳落 ``runs/audit_gate/``（#242 惯例：门命令一律先
  落日志文件再判读——stdout 直消费有 256KB cap 且管道吃退出码）；
- **pip-audit 未安装 → 明确 FAIL（rc=3），不静默过**：缺审计器的"绿"是
  伪造门（与 audit_deps 网络降级 rc=2 的诚实 skip 语义衔接但更快失败）；
- rc 原样透传：audit_deps 的 rc 语义（0=绿 / 1=有未豁免漏洞 /
  2=审计本体跑不起来的诚实 skip）本包装不吞不改（门红不掩盖、门 skip
  不冒充绿）；
- 日志落盘失败 → rc=4（门不可留痕=不判绿，诚实降级，#242 同源）。

周期化方式（本脚本只做门，不替操作者注册计划任务——schtasks 隐藏形态
按  规则 0b-2 避免静默形态，注册属运维动作）：
- CI：cron/GitHub schedule 步骤跑
  ``.venv/Scripts/python.exe scripts/audit_gate.py``，rc!=0 即门红；
- 本地：任务计划程序 console 可见形态直指本脚本（避免 0b-2 隐藏形态）。

真跑示例（需联网查 PyPI/OSV 漏洞库）：
    .venv/Scripts/python.exe scripts/audit_gate.py
    .venv/Scripts/python.exe scripts/audit_gate.py --requirements req.txt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
_DEFAULT_LOG_DIR = _REPO_ROOT / "runs" / "audit_gate"

#: 退出码表（0/1/2 为 audit_deps 语义透传；3/4 为本包装新增）
RET_OK = 0  # 绿：无未豁免漏洞
RET_RED = 1  # 有未豁免漏洞（audit_deps 红透传）
RET_SKIPPED = 2  # 审计本体跑不起来（audit_deps 诚实 skip 透传）
RET_PIP_AUDIT_MISSING = 3  # pip-audit 未安装——门不静默过
RET_LOG_WRITE_FAILED = 4  # 日志落盘失败——门不可留痕不判绿


def pip_audit_installed() -> bool:
    """pip-audit 可导入探测（importlib 探测，零副作用零网络）。"""
    import importlib.util

    return importlib.util.find_spec("pip_audit") is not None


def build_audit_cmd(report_json: Path) -> list[str]:
    """构造 audit_deps 子进程命令行（同解释器同 venv；离线可测）。"""
    return [
        sys.executable,
        str(_SCRIPTS_DIR / "audit_deps.py"),
        "--json",
        str(report_json),
    ]


def _run_audit(cmd: list[str], timeout_s: int) -> tuple[str, str, int]:
    """跑 audit_deps 子进程；超时/启动失败归入 rc=2 诚实 skip 语义。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return "", f"audit_deps 超时（>{timeout_s}s，按诚实 skip 语义处置）", RET_SKIPPED
    except OSError as exc:
        return "", f"audit_deps 启动失败：{exc}", RET_SKIPPED
    return proc.stdout, proc.stderr, proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="依赖漏洞常态化门（QM-4 周期化，audit_deps 门包装）")
    parser.add_argument(
        "--log-dir", default=None,
        help="门日志目录（缺省 runs/audit_gate；测试注入 tmp 目录）")
    parser.add_argument(
        "--requirements", default=None,
        help="透传 audit_deps --requirements（审计 lock 导出面而非当前环境）")
    parser.add_argument(
        "--timeout-s", type=int, default=1800,
        help="audit_deps 子进程超时秒数")
    args = parser.parse_args(argv)

    # 门前置：审计器缺失必须显式失败，绝不静默放行（伪造绿比红更危险）
    if not pip_audit_installed():
        print("[audit-gate] FAIL：pip-audit 未安装"
              "（.venv 执行 pip install pip-audit 后重跑）——门不静默过")
        return RET_PIP_AUDIT_MISSING

    try:
        log_dir = Path(args.log_dir) if args.log_dir else _DEFAULT_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[audit-gate] FAIL：日志目录不可建（{exc}）——门不可留痕不判绿")
        return RET_LOG_WRITE_FAILED

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"audit_gate_{stamp}.log"
    report_json = log_dir / f"audit_deps_report_{stamp}.json"

    cmd = build_audit_cmd(report_json)
    if args.requirements:
        cmd += ["--requirements", str(args.requirements)]
    stdout, stderr, rc = _run_audit(cmd, timeout_s=args.timeout_s)

    body = (f"[audit-gate] cmd={' '.join(cmd)}\n"
            f"[audit-gate] rc={rc}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}\n")
    try:
        log_path.write_text(body, encoding="utf-8")
    except OSError as exc:
        print(f"[audit-gate] FAIL：日志落盘失败（{exc}）：{log_path}"
              f"——门不可留痕不判绿；门输出如下：\n{body}")
        return RET_LOG_WRITE_FAILED

    print(f"[audit-gate] 日志: {log_path}")
    print(f"[audit-gate] 报告: {report_json}")
    print(body.rstrip())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
