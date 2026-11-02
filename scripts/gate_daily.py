#!/usr/bin/env python3
"""aurora_m W1-8：分层日常门运行器（A+B 层缺省，C 重件层显式排除）。

口径与红线
----------
* **终门永远全量**：真终门 = scripts/wf_gate_full_v2.py（分段独立进程串行，
  零过滤），本脚本不替代终门；--tier all 仅供"三层并集==全量收集集"自证
  （配 --collect-only 数收集数即可，不必真跑终门）。
* 缺省 --tier ab：A 钉子层 + B 数值不变量层（-m "not tier_c"——C 重件层显式
  排除）；--tier a：仅 A 层（W2-3 合流门预留口径）；--tier all：全量（不加
  tier 过滤）。层名单 = tests/fixtures/test_tiers.yaml（committed，由
  tests/conftest.py 在收集期施加 marker；名单缺席 → 无标记 → -m 过滤零命中
  =全量语义，诚实降级）。
* 缺省并行：-n 4 --dist=loadfile（pytest-xdist）；--serial 串行档；--workers N
  可调但**硬顶 8**——用户硬约束"worker 数探底不探顶"（挂死前科：8w→20 进程
  10.4GB 零计算，TODO 终门提速条目登记），N>8 截断到 8 并告警。
* --segments N（缺省 1=单进程形态）：N>1 时按 v2 门同款字母序分 N 段独立
  进程顺序执行（每段独立日志+junitxml 落 gate_parts/，聚合 TOTAL 落本日志）。
  **W1-8 实测注记（2026-10-29）**：单进程整跑（serial 或 xdist worker）会在
  starlette TestClient portal 会话族死锁（证据 runs/aurora_m/w1_8/
  serial_hang_evidence.json：serial 2/2 + 并行 worker 1/4 + TestClient 簇
  单独跑 1/1 冻结；根因嫌疑=10+ UI 测试文件 ``return TestClient(...)`` 无
  ``with``（无 lifespan 关闭，线程泄漏），2026-10-12..10-21 落盘，晚于最后
  一次单进程全量绿（2026-09-27）——v2 五段门每段会话密度被稀释故统计上躲过。
  **泄漏根治前日常门建议 --segments 3 起步**。
* 并行臂 deselect solo（计时敏感测试 xdist 争用假红防护，r4 批 million-rows
  实证；对齐 gate_parallel.py 既有口径与 solo marker 语义"仅串行全量门与 CI
  执行"）；串行臂不 deselect（solo 在串行下本就是合法执行形态）。
* OPENBLAS_NUM_THREADS=1 在子进程 env 构造期钉死（#258：worker×BLAS 线程
  超订实测慢 85×，对齐 gate_parallel.py）。
* 日志：缺省 runs/gate_daily_<yyyymmdd_hhmm>.log + junitxml 落
  runs/gate_logs/——命名**不含 "full"**，check_numbers 门口径 glob
  （``*gate*full*.log`` / ``gate_baseline_2*.log``，#355 家族）零命中；
  --seg-log NAME 落 runs/gate_parts/NAME.log（分段产物子目录，同样 glob 安全；
  NAME 禁含 "full"，违者拒绝发射）。
* 退出码 = pytest rc（红即红；本脚本**无 retry 面**——#122 红线：隔离重跑
  是 v2 门的环境类定性器，日常门不做任何失败吞咽）。
* **禁与终门/重型构建并行**（内存竞争放大 WinError 8 spawn 失败类，AGENTS
  全量门失败定性三分法①）；长跑轮询用存活探针护跑（probe_gate_alive.ps1
  实践，TODO 终门提速条目登记）——勿在前台 sleep 占终端，日志尾部 mtime/
  行数增长即活证据。
* 尾部打印：本批收集/通过/失败/跳过/排除数 + 三层并集自证提示
  （A=缺省不在名单 ∪ tier_b 名单 ∪ tier_c 名单 == 全量收集集）。

用法（仓根）::
    .venv/Scripts/python.exe scripts/gate_daily.py                  # A+B 并行（缺省）
    .venv/Scripts/python.exe scripts/gate_daily.py --serial         # A+B 串行
    .venv/Scripts/python.exe scripts/gate_daily.py --tier all --collect-only  # 终门清单自证
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"
GATE_PARTS = RUNS / "gate_parts"
GATE_LOGS = RUNS / "gate_logs"

#: 并行 worker 探底缺省值（用户硬约束：探底不探顶；硬顶 MAX_WORKERS）
DEFAULT_WORKERS = 4
MAX_WORKERS = 8

#: --tier 取值 → tier 维度 marker 过滤（None=不加 tier 过滤=全量口径）
TIER_FILTERS = {
    "ab": "not tier_c",
    "a": "not tier_c and not tier_b",
    "all": None,
}

# 汇总行解析（与 scripts/wf_gate_full_v2.py _parse_summary 同款口径——单脚本
# 自包含不跨脚本 import，两处判据一致性由 tests/unit/test_tier_marks.py 钉）：
# 判据=末个含 " in " 且带 " passed"/" failed"/" error" 计数的行；failed-only/
# error-only 形态必须解析出非零（全败段假绿教训，2026-10-07 门完整性修复）。
_FAILED_LINE_RE = re.compile(r"^FAILED (\S+)", re.MULTILINE)
_DESELECTED_RE = re.compile(r"(\d+) deselected")


def _tier_counts_applied(counts_path) -> tuple[int, int] | None:
    """段进程 marker 施加计数聚合（conftest RFAUTO_TIER_COUNTS_OUT JSONL）。

    返回 (applied_b, applied_c)；文件缺/坏/含坏行 → None——调用方回退到
    pytest 终端 "N deselected" 解析（宁回退不假数，#316 同方向）。"""
    sum_b = sum_c = 0
    try:
        for ln in counts_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            rec = json.loads(ln)
            sum_b += int(rec.get("applied_b") or 0)
            sum_c += int(rec.get("applied_c") or 0)
    except (OSError, ValueError, AttributeError):
        return None
    return sum_b, sum_c


def _deselected_for(tier: str, counts_path) -> int | None:
    """tier 过滤语义下的真 deselect 数：ab=C / a=B+C / all=0。

    文件缺/坏 → None（调用方回退 pytest 终端 "N deselected" 解析）。"""
    applied = _tier_counts_applied(counts_path)
    if applied is None:
        return None
    sum_b, sum_c = applied
    if tier == "all":
        return 0
    if tier == "a":
        return sum_b + sum_c
    return sum_c
_COLLECTED_RE = re.compile(r"(\d+) tests? collected")


def _parse_summary(text: str) -> tuple[int, int, int]:
    """pytest 末汇总行 → (passed, failed+error, skipped)（v2 同款判据）。"""
    cand = [ln for ln in text.splitlines()
            if " in " in ln and "TOTAL:" not in ln
            and (" passed" in ln or " failed" in ln or " error" in ln)]
    if not cand:
        return 0, 0, 0
    line = cand[-1]

    def _num(word: str) -> int:
        m = re.search(r"(\d+) " + word, line)
        return int(m.group(1)) if m else 0

    return _num("passed"), _num("failed") + _num("error"), _num("skipped")


def build_marker_args(tier: str, serial: bool) -> list[str]:
    """tier 档位 × 串并行 → marker 过滤参数（测试钉矩阵）。

    并行臂追加 "not solo"（xdist 争用假红防护）；串行臂不加（solo 合法执行
    形态）；--tier all 不加 tier 过滤（终门口径自证），但并行臂仍保 solo
    deselect（xdist 安全纪律与 tier 口径正交）。
    """
    if tier not in TIER_FILTERS:
        raise SystemExit(f"--tier 取值非法: {tier}（合法 {sorted(TIER_FILTERS)}）")
    parts = []
    if TIER_FILTERS[tier] is not None:
        parts.append(TIER_FILTERS[tier])
    if not serial:
        parts.append("not solo")
    return ["-m", " and ".join(parts)] if parts else []


def resolve_log_path(seg_log: str | None, ts: str) -> Path:
    """日志落盘路径：缺省 runs/gate_daily_<ts>.log；--seg-log NAME →
    runs/gate_parts/NAME.log。两者均避开 #355 门口径 glob（不含 full）。"""
    if seg_log:
        if "full" in seg_log.lower():
            raise SystemExit(
                f"--seg-log 名禁含 'full'（#355 门口径 glob 防污染）: {seg_log}")
        name = seg_log if seg_log.endswith(".log") else f"{seg_log}.log"
        return GATE_PARTS / name
    return RUNS / f"gate_daily_{ts}.log"


def _collect_file_list() -> list[str]:
    """收集 tests/unit 测试文件（字母序，v2 门 _collect_files 同款口径）——
    --segments>1 的分段切分输入。"""
    cmd = [sys.executable, "-m", "pytest", "tests/unit", "-q", "--co",
           "--no-header", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=300)
    files = sorted({
        part
        for ln in proc.stdout.splitlines()
        for part in [ln.strip().split("::")[0]]
        if part.endswith(".py") and part.startswith("tests/")
    })
    if not files:
        raise RuntimeError(
            f"collect 失败 rc={proc.returncode}: {proc.stderr[-400:]}")
    return files


def _run_pytest(cmd: list[str], log_path: Path, header: str,
                env: dict[str, str]) -> tuple[int, str]:
    """发射一次 pytest 进程（stdout 落文件；返回 rc 与日志全文）。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        log.write(header.encode("utf-8"))
        log.flush()
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return proc.returncode, text


def _aggr_trailer(tier: str, mode: str, wall_s: float, rc: int,
                  collected: int, deselected: int, passed: int,
                  failed: int, skipped: int, failed_ids: list[str]) -> str:
    """聚合尾块（汇总行形态对齐 v2 门惯例：TOTAL + GATE_RC）。"""
    lines = [
        f"\n# finished: {datetime.now().isoformat()}",
        f"# wall_clock_s: {wall_s:.1f} ({wall_s / 60:.1f} min)",
        f"# pytest_rc: {rc}",
        f"# collected={collected} deselected={deselected} "
        f"(tier={tier} mode={mode})",
        f"# passed={passed} failed={failed} skipped={skipped}",
    ]
    if failed_ids:
        lines.append(f"# failed_ids: {failed_ids[:20]}"
                     + (" ..." if len(failed_ids) > 20 else ""))
    lines += [
        "# 三层并集自证：A（缺省不在名单）∪ tier_b 名单 ∪ tier_c 名单 == 全量收集集",
        "#   名单复核/再生：scripts/generate_tier_marks.py --verify（collect-only 比对）",
        f"====== TOTAL: {passed} passed, {failed} failed, {skipped} skipped"
        f"（tier={tier} deselected={deselected}；层名单="
        "tests/fixtures/test_tiers.yaml）======",
        f"GATE_RC={rc}",
    ]
    return "\n".join(lines) + "\n"


def _run_single(args, ts: str, mode: str, log_path: Path, xml_path: Path,
                dist_args: list[str], marker_args: list[str],
                env: dict[str, str]) -> int:
    """--segments=1 形态：单进程一次发射（行为=规格缺省）。"""
    cmd = [
        sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=line",
        "-p", "no:cacheprovider", *dist_args, *marker_args,
    ]
    if args.collect_only:
        cmd.append("--collect-only")
    else:
        GATE_LOGS.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--junitxml={xml_path}")
    header = (
        f"# W1-8 gate_daily tier={args.tier} mode={mode}"
        + (" collect_only=1" if args.collect_only else "")
        + "\n"
        f"# cmd: {' '.join(cmd)}\n"
        f"# marker filter: {' '.join(marker_args[1:]) if marker_args else '(无=全量口径)'}\n"
        f"# OPENBLAS_NUM_THREADS={env['OPENBLAS_NUM_THREADS']} (forced)\n"
        + ("" if args.collect_only else f"# junitxml: {xml_path}\n")
        + f"# started: {datetime.now().isoformat()}\n"
        "# 红线：终门永远全量（wf_gate_full_v2）；本脚本禁与终门/重型构建并行；\n"
        "#       长跑轮询用存活探针（probe_gate_alive.ps1 实践），勿前台 sleep\n\n"
    )
    t0 = time.monotonic()
    rc, text = _run_pytest(cmd, log_path, header, env)
    wall_s = time.monotonic() - t0
    passed, failed, skipped = _parse_summary(text)
    m_desel = _DESELECTED_RE.search(text)
    deselected = int(m_desel.group(1)) if m_desel else 0
    cnt = _deselected_for(args.tier,
                          GATE_LOGS / f"gate_daily_{ts}.tier_counts.jsonl")
    if cnt is not None:
        deselected = cnt
    m_coll = _COLLECTED_RE.search(text)
    collected = int(m_coll.group(1)) if m_coll else passed + failed + skipped
    failed_ids = _FAILED_LINE_RE.findall(text)
    trailer = _aggr_trailer(args.tier, mode, wall_s, rc, collected, deselected,
                            passed, failed, skipped, failed_ids)
    with open(log_path, "ab") as log:
        log.write(trailer.encode("utf-8"))
    print(f"tier={args.tier} mode={mode} rc={rc} wall={wall_s:.1f}s "
          f"collected={collected} deselected={deselected}")
    print(f"log: {log_path}")
    return rc


def _run_segmented(args, ts: str, mode: str, log_path: Path,
                   dist_args: list[str], marker_args: list[str],
                   env: dict[str, str], n_seg: int) -> int:
    """--segments=N>1 形态：v2 门同款分段独立进程（每段独立日志+junitxml 落
    gate_parts/；聚合 TOTAL 落本日志；段级守卫同 v2——rc≠0 且零红项可解析=
    段崩坏计红，永不假绿）。本脚本无 retry 面（#122：隔离重跑是终门环境类
    定性器，日常门不吞失败）。"""
    files = _collect_file_list()
    size, rem = divmod(len(files), n_seg)
    chunks: list[list[str]] = []
    start = 0
    for i in range(n_seg):
        end = start + size + (1 if i < rem else 0)
        if start < end:
            chunks.append(files[start:end])
        start = end
    head = (
        f"# W1-8 gate_daily tier={args.tier} mode={mode} segments={len(chunks)}"
        "（v2 同款分段独立进程）\n"
        f"# marker filter: {' '.join(marker_args[1:]) if marker_args else '(无=全量口径)'}\n"
        f"# OPENBLAS_NUM_THREADS={env['OPENBLAS_NUM_THREADS']} (forced)\n"
        f"# started: {datetime.now().isoformat()}\n"
        "# 红线：终门永远全量（wf_gate_full_v2）；本脚本禁与终门/重型构建并行\n\n"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        log.write(head.encode("utf-8"))
    t0 = time.monotonic()
    total_p = total_f = total_s = 0
    all_failed: list[str] = []
    seg_broken: list[str] = []
    lines: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        seg_log = GATE_PARTS / f"gate_daily_{ts}.seg{i}.log"
        seg_xml = GATE_LOGS / f"gate_daily_{ts}.seg{i}.xml"
        cmd = [
            sys.executable, "-m", "pytest", *chunk, "-q", "--tb=line",
            "-p", "no:cacheprovider", *dist_args, *marker_args,
            f"--junitxml={seg_xml}",
        ]
        rc, text = _run_pytest(cmd, seg_log, f"# seg{i} cmd: {' '.join(cmd)}\n\n",
                               env)
        p, f, s = _parse_summary(text)
        seg_failed_ids = _FAILED_LINE_RE.findall(text)
        total_p += p
        total_f += f
        total_s += s
        all_failed.extend(seg_failed_ids)
        lines.append(
            f"[seg{i}] files={len(chunk)} rc={rc} passed={p} failed={f} "
            f"skipped={s} -> {seg_log.relative_to(REPO_ROOT).as_posix()}")
        print(lines[-1], flush=True)
        if rc != 0 and f == 0 and not seg_failed_ids:
            seg_broken.extend(chunk)
            lines.append(f"# [seg{i}] 段级守卫：rc={rc} 零红项可解析（收集错误/"
                         f"进程硬杀），{len(chunk)} 文件按仍红未定性计红")
            print(lines[-1], flush=True)
    all_failed.extend(seg_broken)
    wall_s = time.monotonic() - t0
    verdict_rc = 1 if (total_f or all_failed) else 0
    with open(log_path, "ab") as log:
        log.write(("\n".join(lines) + "\n").encode("utf-8"))
    trailer = _aggr_trailer(args.tier, mode, wall_s, verdict_rc,
                            total_p + total_f + total_s + len(seg_broken),
                            _deselected_for(args.tier, GATE_LOGS /
                                            f"gate_daily_{ts}.tier_counts.jsonl")
                            or 0, total_p, total_f, total_s, all_failed)
    with open(log_path, "ab") as log:
        log.write(trailer.encode("utf-8"))
    print(f"tier={args.tier} mode={mode} segments={len(chunks)} rc={verdict_rc} "
          f"wall={wall_s:.1f}s passed={total_p} failed={total_f}")
    print(f"log: {log_path}")
    return verdict_rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="aurora_m W1-8 分层日常门（A+B 缺省并行；终门口径不在此）")
    parser.add_argument("--tier", default="ab", choices=sorted(TIER_FILTERS),
                        help="ab=A+B（缺省，日常口径）/ a=仅 A 钉子层（W2-3 预留）"
                             "/ all=全量（终门口径自证用）")
    parser.add_argument("--serial", action="store_true",
                        help="串行档（-n0；solo 用例照跑）")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"xdist worker 数（缺省 {DEFAULT_WORKERS}，硬顶 "
                             f"{MAX_WORKERS}；探底不探顶）")
    parser.add_argument("--seg-log", default=None,
                        help="自定义日志名（落 runs/gate_parts/NAME.log；"
                             "缺省 runs/gate_daily_<ts>.log）")
    parser.add_argument("--segments", type=int, default=1,
                        help="分段独立进程数（缺省 1=单进程形态；TestClient "
                             "portal 泄漏根治前建议 3，见模块 docstring W1-8 "
                             "实测注记）")
    parser.add_argument("--collect-only", action="store_true",
                        help="只收集不执行（三层并集/终门清单自证用，秒级-分钟级）")
    args = parser.parse_args(argv)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "serial" if args.serial else f"parallel_n{min(args.workers, MAX_WORKERS)}"
    log_path = resolve_log_path(args.seg_log, ts)
    xml_path = GATE_LOGS / f"gate_daily_{ts}.xml"

    if args.workers > MAX_WORKERS:
        print(f"# WARN --workers={args.workers} > 硬顶 {MAX_WORKERS}，截断"
              "（用户硬约束：探底不探顶，挂死前科 8w→20 进程 10.4GB）")

    dist_args = (["-n0"] if args.serial
                 else ["-n", str(min(args.workers, MAX_WORKERS)),
                       "--dist=loadfile"])
    marker_args = build_marker_args(args.tier, args.serial)

    # #258 超订守卫：必须在 pytest/numpy import 之前生效——子进程 env 构造
    # 期注入，本进程（父）只 import stdlib，不会提前加载 numpy。
    env = os.environ.copy()
    env["OPENBLAS_NUM_THREADS"] = "1"
    # 真实 deselected 计数（conftest env 门控观测，#105）：pytest -q 终端
    # 不吐 "N deselected" 行，段进程把 marker 施加计数落 JSONL 供聚合。
    counts_path = GATE_LOGS / f"gate_daily_{ts}.tier_counts.jsonl"
    counts_path.parent.mkdir(parents=True, exist_ok=True)
    if counts_path.exists():
        counts_path.unlink()
    env["RFAUTO_TIER_COUNTS_OUT"] = str(counts_path)

    if args.collect_only or args.segments <= 1:
        return _run_single(args, ts, mode, log_path, xml_path, dist_args,
                           marker_args, env)
    return _run_segmented(args, ts, mode, log_path, dist_args, marker_args,
                          env, args.segments)


if __name__ == "__main__":
    sys.exit(main())
