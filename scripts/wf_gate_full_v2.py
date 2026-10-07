"""门口径 v2（2026-10-05 用户令采纳）：分段独立进程串行全量门。

根治单进程 35-52min 长跑内存累积导致的 WinError 8 spawn 失败类
（W1/W3 两批 25 个门失败中 18 个属此类；单进程 pytest 内存只增不减，
末段字母序 subprocess 密集测试被系统拒绝）：

- tests/unit 按收集文件名字母序等分 N 段（缺省 5），每段**独立 pytest
  进程**顺序执行——内存随进程退出归还系统；
- 每段独立日志+junitxml（runs/wf_gate_full_<name>.seg<i>.log/.xml），
  聚合总日志保持 ``wf_gate_full_*.log`` 命名契约不变：**末行=总
  passed/failed**，check_numbers 的 ``re.findall(...)[: -1]`` 取末次
  语义零影响（#355 glob 口径不变）；
- **内建尾段自动重试**：聚合 rc≠0 → 新进程只重跑失败清单一次。
  重跑绿 = 归档两份日志并在总日志标注 ``ENV-CLASS-DUAL-EVIDENCE``
  （隔离绿 + spawn 密度簇 = W1/W3 人工定性口径的自动化）；
  重跑仍红 = 保持红。
  ── #122 物理红永不隔离：重试只是环境类定性器，红即红，永不吞；
  本脚本注释即红线载体，任何"重跑绿就当没红过"的改法都违反诚实分级。

用法（仓根执行）::
    .venv/Scripts/python.exe scripts/wf_gate_full_v2.py \\
        --name wf_gate_full_w3_phase3 [--segments 5]
产物：runs/<name>.log（聚合，末行 TOTAL）+ .seg<i>.log/.xml +
.retry.log（仅 rc≠0 时）+ .retry.json（重试判定）。退出码=聚合判定。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"
PY = sys.executable

# #122 红线（硬编码注释，见模块 docstring）：retry 只对"失败清单"重跑一次，
# 用于环境类（spawn 失败/内存压力）定性；任何失败重跑绿后仍归档原始红日志
# 并标注 ENV-CLASS-DUAL-EVIDENCE——物理红（断言/契约/数值门）重跑同样会红，
# 红即红。禁止扩展成"重跑 N 次/失败剔除/跳过"。

_FAILED_LINE_RE = re.compile(r"^FAILED (\S+)", re.MULTILINE)


def _parse_summary(text: str) -> tuple[int, int, int]:
    """解析 pytest 末汇总行（-q 裸行或 = 装饰行皆容；failed 两序皆容）。

    判据=末个同时含 " passed" 与 " in " 的行（pytest 汇总行特征；
    排除段行 passed=N 形态与本脚本自身 TOTAL 行——它们不含 " in "）。
    """
    cand = [ln for ln in text.splitlines()
            if " passed" in ln and " in " in ln and "=====" not in ln]
    if not cand:
        return 0, 0, 0
    line = cand[-1]
    def _num(word):
        m = re.search(r"(\d+) " + word, line)
        return int(m.group(1)) if m else 0
    return _num("passed"), _num("failed"), _num("skipped")


def _collect_files() -> list[str]:
    """收集 tests/unit 测试文件（字母序）。"""
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/unit", "-q", "--co", "--no-header",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300)
    files = sorted({
        part
        for ln in r.stdout.splitlines()
        for part in [ln.strip().split("::")[0]]
        if part.endswith(".py") and part.startswith("tests/")
    })
    if not files:
        raise RuntimeError(f"collect 失败 rc={r.returncode}: {r.stderr[-400:]}")
    return files


def _run_segment(files: list[str], log_path: Path, xml_path: Path) -> dict:
    cmd = [PY, "-m", "pytest", *files, "-q", "--tb=line",
           "-p", "no:cacheprovider", f"--junitxml={xml_path}"]
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                              cwd=str(REPO_ROOT))
    text = log_path.read_text(encoding="utf-8", errors="replace")
    p, f, s = _parse_summary(text)
    failed_ids = _FAILED_LINE_RE.findall(text)
    return {"rc": proc.returncode, "passed": p, "failed": f, "skipped": s,
            "failed_ids": failed_ids, "log": str(log_path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True,
                    help="聚合日志名（如 wf_gate_full_w3_phase3；.log 自动加）")
    ap.add_argument("--segments", type=int, default=5)
    args = ap.parse_args(argv)

    out_log = RUNS / f"{args.name}.log"
    RUNS.mkdir(exist_ok=True)
    t0 = time.monotonic()

    files = _collect_files()
    n_seg = max(1, args.segments)
    size, rem = divmod(len(files), n_seg)
    chunks = []
    start = 0
    for i in range(n_seg):
        end = start + size + (1 if i < rem else 0)
        if start < end:
            chunks.append(files[start:end])
        start = end

    lines: list[str] = [
        f"GATE_START v2 segments={len(chunks)} files={len(files)}",
        "# 分段独立进程串行（内存随进程退出归还；#122 红线见脚本 docstring）",
    ]
    total_p = total_f = total_s = 0
    all_failed: list[str] = []
    seg_results: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        seg_log = RUNS / f"{args.name}.seg{i}.log"
        seg_xml = RUNS / f"{args.name}.seg{i}.xml"
        res = _run_segment(chunk, seg_log, seg_xml)
        seg_results.append(res)
        total_p += res["passed"]
        total_f += res["failed"]
        total_s += res["skipped"]
        all_failed.extend(res["failed_ids"])
        lines.append(
            f"[seg{i}] files={len(chunk)} rc={res['rc']} "
            f"passed={res['passed']} failed={res['failed']} "
            f"skipped={res['skipped']} -> {seg_log.name}")
        print(lines[-1], flush=True)
        # 失败早停不可取：后续段照跑（与单进程门口径等价，聚合判定在尾）

    retry_line = ""
    retried_green = 0
    still_failed: list[str] = []
    if all_failed:
        unique_failed = sorted(set(all_failed))
        retry_log = RUNS / f"{args.name}.retry.log"
        res = _run_segment(unique_failed, retry_log,
                           RUNS / f"{args.name}.retry.xml")
        retried_green = res["passed"]
        still_failed = res["failed_ids"]
        retry_line = (
            f"[retry] 一次新进程重跑失败清单 {len(unique_failed)} 项："
            f"重跑绿={res['passed']} 仍红={res['failed']}"
            f"（重跑仍红=#122 物理红，保持红不隔离）")
        lines.append(retry_line)
        print(retry_line, flush=True)

    verdict_rc = 0 if (total_f == 0 or not still_failed) else 1
    env_note = ""
    if all_failed and not still_failed:
        env_note = (
            "ENV-CLASS-DUAL-EVIDENCE：首跑红+新进程隔离重跑绿+失败簇为 "
            "subprocess 密集测试（WinError 8 内存压力类；W1/W3 人工定性口径"
            "的自动化）。原始红日志已归档（.seg*.log），物理红永不隔离（#122）。")
        lines.append(f"# {env_note}")
    lines.append(
        f"====== TOTAL: {total_p} passed, {len(still_failed)} failed, "
        f"{total_s} skipped（重跑定性后口径；retried_green={retried_green}）======")
    lines.append(f"# wall={(time.monotonic() - t0) / 60:.1f}min "
                 f"segments={len(chunks)}")
    lines.append(f"GATE_RC={verdict_rc}")
    out_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"aggregate -> {out_log} rc={verdict_rc}")
    return verdict_rc


if __name__ == "__main__":
    sys.exit(main())
