"""门口径 v2（2026-10-05 用户令采纳）：分段独立进程串行全量门。

根治单进程 35-52min 长跑内存累积导致的 WinError 8 spawn 失败类
（W1/W3 两批 25 个门失败中 18 个属此类；单进程 pytest 内存只增不减，
末段字母序 subprocess 密集测试被系统拒绝）：

- tests/unit 按收集文件名字母序等分 N 段（缺省 5），每段**独立 pytest
  进程**顺序执行——内存随进程退出归还系统；
- 每段独立日志+junitxml 落 **runs/gate_parts/** 子目录（#355 四犯根治
  2026-10-05：seg/retry 日志含 ``full`` 命名、落顶层则命中 check_numbers
  全量门口径 ``*gate*full*.log`` glob（Path.glob 非递归只扫顶层）——终门
  运行期"最新匹配文件=刚写完的单段日志"，单段 passed 污染 docs_site/
  gallery 再生钉与 count_tests（门自指伪象，goal_final2 实证 seg2 阶段
  docs_site 钉红）；改道子目录后顶层 glob 只可能拾取聚合日志）；
- 聚合总日志保持 ``runs/wf_gate_full_<name>.log`` 顶层命名路径不变：
  **末行=总 passed/failed**，check_numbers 的 ``re.findall(...)[: -1]``
  取末次语义零影响（#355 glob 口径不变）——唯一权威数字源；
- 启动器约定：Start-Process 重定向日志同样落 gate_parts/（
  ``runs/<name>_launcher.log`` 命名指纹同族会命中顶层 glob；当前因只含
  ``passed=N`` 等号形态、无 "N passed" 汇总行被 count_tests 跳过，仍勿
  再落顶层）；
- **段级守卫（ge9 审查批 R6 P1-1，2026-10-08）**：段进程 rc≠0 且零红项
  可解析（收集错误段 "N errors in"/进程硬杀段无汇总行）→ 该段文件按
  "仍红未定性"计入重跑清单，永不假绿（崩坏进程不产生绿证据）；
- **内建尾段自动重试**：聚合 rc≠0 → 新进程只重跑失败清单一次。
  重跑绿 = 归档两份日志并在总日志标注 ``ENV-CLASS-DUAL-EVIDENCE``
  （隔离绿 + spawn 密度簇 = W1/W3 人工定性口径的自动化）；
  重跑仍红 = 保持红。
  ── #122 物理红永不隔离：重试只是环境类定性器，红即红，永不吞；
  本脚本注释即红线载体，任何"重跑绿就当没红过"的改法都违反诚实分级。
- **durations 分层报告（门口径 v2 ④ followUp 清偿，2026-10-11 W2-D）**：
  段进程带 ``--durations=20``，聚合日志在 TOTAL 前落分层表（>=60s /
  10-60s / 1-10s 三层计数 + 最慢 top-20 明细）——常驻慢测试从"门总时长
  涨了"变"谁在涨"直接可见。段日志的 durations 表行不含 "N passed"
  形态（_parse_summary 末次匹配语义不受扰，test 钉）。

用法（仓根执行）::
    .venv/Scripts/python.exe scripts/wf_gate_full_v2.py \\
        --name wf_gate_full_w3_phase3 [--segments 5]
产物：runs/<name>.log（聚合，末行 TOTAL，顶层唯一权威数字源）+
gate_parts/<name>.seg<i>.log/.xml + gate_parts/<name>.retry.log/.xml
（仅 rc≠0 时）。退出码=聚合判定。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"
# #355 四犯根治（2026-10-05）：seg/retry 等分段产物一律落 runs/ 的此子目录
# ——check_numbers.FULL_GATE_LOG_GLOBS 的 ``*gate*full*.log`` 只扫 runs/
# 顶层（Path.glob 非递归），聚合日志因此是顶层唯一权威数字源。
# 禁止往 runs/ 顶层新增任何含 ``full`` 的非聚合日志（#355 已四犯）。
GATE_PARTS_SUBDIR = "gate_parts"
PY = sys.executable

#: 每段 pytest 进程 --durations 取最慢前 N（门口径 v2 ④ followUp，2026-10-11）
DURATIONS_TOP = 20

# #122 红线（硬编码注释，见模块 docstring）：retry 只对"失败清单"重跑一次，
# 用于环境类（spawn 失败/内存压力）定性；任何失败重跑绿后仍归档原始红日志
# 并标注 ENV-CLASS-DUAL-EVIDENCE——物理红（断言/契约/数值门）重跑同样会红，
# 红即红。禁止扩展成"重跑 N 次/失败剔除/跳过"。

_FAILED_LINE_RE = re.compile(r"^FAILED (\S+)", re.MULTILINE)

# durations 表行（实测形态：``0.30s call     tests/unit/test_x.py::test_y``；
# ms/s 双单位皆容）。行不含 " in "/"N passed" 形态——_parse_summary 末次
# 匹配语义与 check_numbers 数字源均不受扰（tests 钉）。
_DUR_LINE_RE = re.compile(
    r"^\s*([\d.]+)(ms|s)\s+(setup|call|teardown)\s+(\S+)\s*$", re.MULTILINE)


def _parse_durations(text: str) -> dict[str, float]:
    """段日志 ``--durations`` 表 → {nodeid: 秒}（同测多相取 max——分层看
    最慢相；表外行如 hidden 注记/汇总行天然不匹配）。"""
    out: dict[str, float] = {}
    for m in _DUR_LINE_RE.finditer(text):
        val = float(m.group(1)) * (0.001 if m.group(2) == "ms" else 1.0)
        nodeid = m.group(4)
        if val > out.get(nodeid, 0.0):
            out[nodeid] = val
    return out


def durations_tier_lines(durations: dict[str, float],
                         top: int = DURATIONS_TOP) -> list[str]:
    """合并 durations → 分层报告行（进聚合日志 TOTAL 前）。

    层级：>=60s（红层，逐段独立进程也压不下去的常驻大）/ >=10s（黄层，
    sleep 类常驻守卫的捕猎区）/ >=1s / 其余；明细=最慢 top-N。行以 "# DUR"
    前缀起，不带 passed/failed 字样（#355 数字源兼容）。
    """
    if not durations:
        return []
    vals = list(durations.values())
    n_ge60 = sum(1 for v in vals if v >= 60.0)
    n_ge10 = sum(1 for v in vals if 10.0 <= v < 60.0)
    n_ge1 = sum(1 for v in vals if 1.0 <= v < 10.0)
    lines = [
        f"# DURATIONS 分层（门口径 v2 ④）：>=60s={n_ge60} 10-60s={n_ge10} "
        f"1-10s={n_ge1} <1s={len(vals) - n_ge60 - n_ge10 - n_ge1}"
        f"（合计 {len(vals)} 项，明细=最慢 top-{top}）",
    ]
    ranked = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
    for nodeid, sec in ranked[:top]:
        lines.append(f"# DUR {sec:8.2f}s {nodeid}")
    return lines


def _parse_summary(text: str) -> tuple[int, int, int]:
    """解析 pytest 末汇总行（-q 裸行或 = 装饰行皆容；failed 两序皆容）。

    判据=末个含 " in " 且带 " passed"/" failed"/" error" 计数的行（pytest
    汇总行特征，= 装饰行亦容；排除段行 passed=N 形态与本脚本自身 TOTAL
    行——它们不含 " in " 或含 "TOTAL:" 字面）。
    failed-only 形态（"1 failed in 0.71s"，全败段）必须解析出 failed——
    2026-10-07 门完整性修复：旧判据要求 " passed" 在行内，全败段解析成
    (0,0,0) 致 verdict 的 total_f==0 短路假绿（TOTAL 写 failed 而 GATE_RC=0）。
    error-only 形态（"2 errors in 0.30s"，收集错误段）必须解析出非零——
    ge9 审查批 R6 P1-1（2026-10-08）：errors 计入 failed 语义（红向），
    否则解析 (0,0,0) 且零 FAILED 行，verdict 短路假绿。
    """
    cand = [ln for ln in text.splitlines()
            if " in " in ln and "TOTAL:" not in ln
            and (" passed" in ln or " failed" in ln or " error" in ln)]
    if not cand:
        return 0, 0, 0
    line = cand[-1]
    def _num(word):
        m = re.search(r"(\d+) " + word, line)
        return int(m.group(1)) if m else 0
    return _num("passed"), _num("failed") + _num("error"), _num("skipped")


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


def _slow_mode_args() -> list[str]:
    """慢件分层三态（aurora_h R3 #2，RFAUTO_GATE_SLOW_MODE）。

    缺省/未知值=空（无差别全量，终门口径与数字链零影响）；
    ``day``=-m "not slow"（日常轮跳过 slow 件）；``night``=-m slow
    （只跑慢件夜档）。收官终门按约定不带 env 全量跑（#122：分层只是
    日常轮省时，slow 件照常进终门，物理红永不隔离语义不变）。
    """
    mode = os.environ.get("RFAUTO_GATE_SLOW_MODE", "").strip().lower()
    if mode == "day":
        return ["-m", "not slow"]
    if mode == "night":
        return ["-m", "slow"]
    return []


def _run_segment(files: list[str], log_path: Path, xml_path: Path) -> dict:
    cmd = [PY, "-m", "pytest", *files, "-q", "--tb=line",
           "-p", "no:cacheprovider", f"--durations={DURATIONS_TOP}",
           f"--junitxml={xml_path}", *_slow_mode_args()]
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                              cwd=str(REPO_ROOT))
    text = log_path.read_text(encoding="utf-8", errors="replace")
    p, f, s = _parse_summary(text)
    failed_ids = _FAILED_LINE_RE.findall(text)
    return {"rc": proc.returncode, "passed": p, "failed": f, "skipped": s,
            "failed_ids": failed_ids, "log": str(log_path),
            "durations": _parse_durations(text)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True,
                    help="聚合日志名（如 wf_gate_full_w3_phase3；.log 自动加）")
    ap.add_argument("--segments", type=int, default=5)
    args = ap.parse_args(argv)

    out_log = RUNS / f"{args.name}.log"
    parts = RUNS / GATE_PARTS_SUBDIR
    RUNS.mkdir(exist_ok=True)
    parts.mkdir(exist_ok=True)
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

    slow_mode = os.environ.get("RFAUTO_GATE_SLOW_MODE", "").strip().lower()
    lines: list[str] = [
        f"GATE_START v2 segments={len(chunks)} files={len(files)}"
        + (f" slow_mode={slow_mode}" if slow_mode in ("day", "night") else ""),
        "# 分段独立进程串行（内存随进程退出归还；#122 红线见脚本 docstring）",
    ]
    total_p = total_f = total_s = 0
    all_failed: list[str] = []
    seg_broken: list[str] = []
    seg_results: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        seg_log = parts / f"{args.name}.seg{i}.log"
        seg_xml = parts / f"{args.name}.seg{i}.xml"
        res = _run_segment(chunk, seg_log, seg_xml)
        seg_results.append(res)
        total_p += res["passed"]
        total_f += res["failed"]
        total_s += res["skipped"]
        all_failed.extend(res["failed_ids"])
        lines.append(
            f"[seg{i}] files={len(chunk)} rc={res['rc']} "
            f"passed={res['passed']} failed={res['failed']} "
            f"skipped={res['skipped']} -> {parts.name}/{seg_log.name}")
        print(lines[-1], flush=True)
        # 失败早停不可取：后续段照跑（与单进程门口径等价，聚合判定在尾）
        # 段级守卫（ge9 审查批 R6 P1-1，与 retry 臂同律）：段进程 rc≠0 且
        # 解析不出任何红项（failed==0 且零 FAILED 行）=收集错误段/进程硬杀
        # 段——旧判据下 (0,0,0)+零 FAILED 进三源合取 → retry 不触发 →
        # GATE_RC=0 假绿。该段文件按仍红未定性计入重跑清单（崩坏进程不产生
        # 绿证据），由隔离重跑定性：重跑绿=环境类标注（GATE_RC 仍红）、
        # 重跑仍崩=:176 律 still_failed 全量——红即红，永不吞。
        if res["rc"] != 0 and res["failed"] == 0 and not res["failed_ids"]:
            seg_broken.extend(chunk)
            lines.append(
                f"# [seg{i}] 段级守卫：rc={res['rc']} 零红项可解析"
                f"（收集错误/进程硬杀），{len(chunk)} 文件按仍红未定性计入重跑清单")
            print(lines[-1], flush=True)

    all_failed.extend(seg_broken)

    retry_line = ""
    retried_green = 0
    still_failed: list[str] = []
    retry_broken = False
    if all_failed:
        unique_failed = sorted(set(all_failed))
        retry_log = parts / f"{args.name}.retry.log"
        res = _run_segment(unique_failed, retry_log,
                           parts / f"{args.name}.retry.xml")
        retried_green = res["passed"]
        still_failed = res["failed_ids"]
        # 门完整性（2026-10-07）：重跑进程本身失败（rc≠0）且解析不出任何
        # 仍红项=空跑——按"仍红未定性"处理，永不贴环境类戳、门保持红
        # （#122 红线：绿证据必须来自真隔离重跑，不来自重跑进程崩坏）。
        if res["rc"] != 0 and not still_failed:
            retry_broken = True
            still_failed = list(unique_failed)
        retry_line = (
            f"[retry] 一次新进程重跑失败清单 {len(unique_failed)} 项："
            f"重跑绿={res['passed']} 仍红={res['failed']}"
            + ("（重跑进程 rc≠0 空跑——按仍红未定性，禁贴环境类戳）"
               if retry_broken else
               "（重跑仍红=#122 物理红，保持红不隔离）"))
        lines.append(retry_line)
        print(retry_line, flush=True)

    verdict_rc = 1 if (total_f or still_failed or all_failed) else 0
    env_note = ""
    if all_failed and not still_failed and not retry_broken:
        env_note = (
            "ENV-CLASS-DUAL-EVIDENCE：首跑红+新进程隔离重跑绿+失败簇为 "
            "subprocess 密集测试（WinError 8 内存压力类；W1/W3 人工定性口径"
            "的自动化）。原始红日志已归档（gate_parts/），物理红永不隔离"
            "（#122）。")
        lines.append(f"# {env_note}")
    # durations 分层（门口径 v2 ④）：跨段合并（同 nodeid 取 max），TOTAL
    # 前落分层表——常驻慢测试从"门总时长涨了"变"谁在涨"直接可见
    merged_durations: dict[str, float] = {}
    for res in seg_results:
        for nid, sec in (res.get("durations") or {}).items():
            if sec > merged_durations.get(nid, 0.0):
                merged_durations[nid] = sec
    lines.extend(durations_tier_lines(merged_durations))
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
