#!/usr/bin/env python
"""QM-10 mypy 棘轮门（round16 P2，验证与质量方法论）。

口径（#97 实测不臆造）：
- 基线=**本机实测**全仓计数：``mypy src/rfauto`` 于 2026-10-03 实测
  **1709 errors / 331 files / 694 checked**（mypy 2.3.1，Windows，
  venv Python 3.12）。写进常量 BASELINE_ERRORS 的数字只能来自本脚本
  --measure 的实测输出，禁止沿用历史文档数字。
- 棘轮门=**不劣化**：current ≤ baseline 即 PASS；current < baseline
  时提示"基线可收紧"（新基线=manual commit 动作——棘轮只紧不松，
  自动降基线会让偶发环境的低计数固化成假门）。
- 高价值模块钉（standalone 单文件口径，与全仓跑分属不同噪声面——
  独立测量独立钉）：本批新模块出生即清零（closed_form_oracle/
  publication_standards=0），synthesis.py 实测 11（存量子集，钉防
  新增）。钉=上限：超钉即红，低钉不自动收紧（同棘轮只紧不松）。

python_version=3.12 勘误声明：[tool.mypy] 钉 python_version="3.10"，
但 mypy 2.3.1 以 3.10 语义解析 site-packages 里 jax 的 PEP 695 桩
（``Type parameter lists are only supported in Python 3.12``）直接
崩溃（errors prevented further checking）——实测环境 venv=3.12，本
脚本以 --python-version=3.12 作为测量环境口径（解析层兼容桩；类型
语义差异对"错误计数棘轮"无碍，换 mypy/环境版本必须 --measure 重钉）。

用法::

    python scripts/qm10_mypy_baseline.py            # 棘轮门（比较模式）
    python scripts/qm10_mypy_baseline.py --measure  # 实测并打印重钉建议
    python scripts/qm10_mypy_baseline.py --json out.json  # 报告落盘

退出码：0=门绿（不劣化），1=劣化（新增错误），2=mypy 运行失败。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_TARGET = "src/rfauto"

#: 测量环境口径（见模块 docstring 勘误声明）。
MYPY_PYTHON_VERSION = "3.12"

#: 全仓棘轮基线（2026-10-03 实测 1709；重钉只准 --measure 后 manual commit）。
BASELINE_ERRORS = 1709

#: 基线测量环境元数据（重钉时必须同步更新——数字与出处绑定）。
BASELINE_META = {
    "measured_at": "2026-10-03",
    "mypy_version": "2.3.1",
    "python_version": MYPY_PYTHON_VERSION,
    "files_with_errors": 331,
    "checked_files": 694,
}

#: 高价值模块钉（standalone 单文件口径；0=出生清零钉，正数=存量防新增钉）。
MODULE_PINS: dict[str, int] = {
    "src/rfauto/core/closed_form_oracle.py": 0,
    "src/rfauto/core/publication_standards.py": 0,
    "src/rfauto/core/synthesis.py": 11,
    "src/rfauto/core/quantity.py": 0,
    "src/rfauto/core/anchors.py": 0,
    "src/rfauto/service/pdn_service.py": 0,
}

_SUMMARY_RE = re.compile(r"Found (\d+) error[s]? in (\d+) file[s]?")
_OK_RE = re.compile(r"Success: no issues found in (\d+) source file[s]?")


def run_mypy(target: str, *, timeout_s: float = 900.0) -> dict[str, Any]:
    """跑一次 mypy（repo 配置 + 测量环境口径），返回结构化计数。"""
    cmd = [sys.executable, "-m", "mypy", target,
           f"--python-version={MYPY_PYTHON_VERSION}"]
    try:
        proc = subprocess.run(cmd, cwd=str(_REPO), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "errors": [], "n_errors": -1, "n_files": -1,
                "checked_files": -1, "raw_tail": f"timeout: {exc}"}
    text = (proc.stdout or "") + (proc.stderr or "")
    summary = _SUMMARY_RE.search(text)
    ok_hit = _OK_RE.search(text)
    errors = [ln for ln in text.splitlines() if ": error:" in ln]
    if summary:
        n_err, n_files = int(summary.group(1)), int(summary.group(2))
        checked = _CHECKED_RE.search(text)
        return {"ok": True, "errors": errors, "n_errors": n_err,
                "n_files": n_files,
                "checked_files": int(checked.group(1)) if checked else -1,
                "raw_tail": text.strip().splitlines()[-1] if text.strip() else ""}
    if ok_hit:
        return {"ok": True, "errors": [], "n_errors": 0, "n_files": 0,
                "checked_files": int(ok_hit.group(1)),
                "raw_tail": text.strip().splitlines()[-1] if text.strip() else ""}
    return {"ok": False, "errors": errors, "n_errors": -1, "n_files": -1,
            "checked_files": -1, "raw_tail": text.strip()[-400:]}


_CHECKED_RE = re.compile(r"Found \d+ errors? in \d+ files? \(checked (\d+) source files?\)")


def ratchet_check(*, run_full: bool = True, run_pins: bool = True,
                  timeout_s: float = 900.0) -> dict[str, Any]:
    """棘轮门：全仓不劣化 + 模块钉不超（测量与报告，#122）。"""
    report: dict[str, Any] = {
        "schema": "rfauto-qm10-mypy-ratchet-v1",
        "baseline": BASELINE_ERRORS,
        "baseline_meta": dict(BASELINE_META),
        "module_pins": dict(MODULE_PINS),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    verdicts: list[bool] = []
    if run_full:
        full = run_mypy(_TARGET, timeout_s=timeout_s)
        if not full["ok"] or full["n_errors"] < 0:
            report["full"] = full
            report["verdict"] = "ERROR"
            report["issues"] = [f"mypy 运行失败：{full['raw_tail']}"]
            return report
        delta = full["n_errors"] - BASELINE_ERRORS
        report["full"] = {"n_errors": full["n_errors"],
                          "n_files": full["n_files"],
                          "checked_files": full["checked_files"],
                          "delta_vs_baseline": delta}
        verdicts.append(delta <= 0)
        report["full_verdict"] = "PASS" if delta <= 0 else "REGRESSED"
        if delta < 0:
            report["suggest"] = (f"全仓计数比基线低 {-delta}——基线可收紧"
                                 "（--measure 实测后 manual 重钉，棘轮只紧不松）")
    if run_pins:
        pin_rows: dict[str, Any] = {}
        pin_ok = True
        for mod, allowed in MODULE_PINS.items():
            m = run_mypy(mod, timeout_s=timeout_s)
            n = m["n_errors"] if m["ok"] and m["n_errors"] >= 0 else -1
            ok = n >= 0 and n <= allowed
            pin_ok = pin_ok and ok
            pin_rows[mod] = {"n_errors": n, "pin": allowed,
                             "verdict": "PASS" if ok else
                             ("ERROR" if n < 0 else "OVER_PIN")}
            if not ok and n >= 0:
                pin_rows[mod]["detail"] = m["errors"][:8]
        report["pins"] = pin_rows
        report["pins_verdict"] = "PASS" if pin_ok else "OVER_PIN"
        verdicts.append(pin_ok)
    report["verdict"] = "PASS" if all(verdicts) and verdicts else "NO_RUN" \
        if not verdicts else "FAIL"
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="QM-10 mypy 棘轮门")
    ap.add_argument("--measure", action="store_true",
                    help="实测模式：只跑全仓计数并打印重钉建议（不判门）")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="报告落盘路径（runs/ 面）")
    ap.add_argument("--no-pins", action="store_true", help="跳过模块钉")
    ap.add_argument("--no-full", action="store_true", help="跳过全仓（只跑钉）")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    if args.measure:
        r = run_mypy(_TARGET, timeout_s=args.timeout)
        if not r["ok"] or r["n_errors"] < 0:
            print(f"[qm10] mypy 运行失败：{r['raw_tail']}", file=sys.stderr)
            return 2
        print(f"[qm10] 实测 {r['n_errors']} errors / {r['n_files']} files / "
              f"{r['checked_files']} checked")
        print("[qm10] 重钉：把 BASELINE_ERRORS/BASELINE_META 更新为上数并 "
              "manual commit（棘轮只紧不松）")
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(
                r, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0

    report = ratchet_check(run_full=not args.no_full,
                           run_pins=not args.no_pins, timeout_s=args.timeout)
    if args.json_path:
        Path(args.json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_path).write_text(json.dumps(
            report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[qm10] verdict={report['verdict']}")
    if "full" in report:
        print(f"[qm10] full: {report['full']['n_errors']} errors "
              f"(baseline={BASELINE_ERRORS}, delta="
              f"{report['full']['delta_vs_baseline']:+d})")
    if "pins" in report:
        for mod, row in report["pins"].items():
            print(f"[qm10] pin {mod}: {row['n_errors']}/{row['pin']} "
              f"{row['verdict']}")
    if report.get("suggest"):
        print(f"[qm10] {report['suggest']}")
    if report["verdict"] == "ERROR":
        return 2
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
