#!/usr/bin/env python
"""QM-9 mutmut 三段路 runner（round16 P2，验证与质量方法论）。

三段路（round16 原文口径，本脚本是固化载体）：
  ① 抽样轮换：ROTATION_PLAN 月度批（每批 1-3 个高价值内核模块）——
     mutmut 全仓（589 文件）no-go（成本不可控），批内轮换可持续；
  ② 等价台账：XML/JSONL 台账（runs/qm9_mutmut/equivalent_ledger.jsonl）
     ——幸存者里确证等价变异的逐条登记（mutant_id+理由+登记人），
     报告面把台账内幸存者重分类 equivalent（#122 如实：生存子=缺口
     候选，非清零运动——确证等价的不再占缺口计数）；
  ③ 幸存者全量复放：mutmut 测试选择优化会产"选择伪幸存"（round16
     方法学发现：mutmut 3.8 选择优化致伪幸存；2.5.1 --runner 窄测
     同理只证"窄测不杀"，未证"全量不杀"）——本脚本为每个幸存者
     生成全量复放命令（apply→全量 pytest→还原），--replay-execute
     逐个执行并按内容哈希核还原。

Windows 勘误（2026-10-03 实测）：mutmut 3.8 无原生 Windows 支持
（CLI 自述 "please use the WSL"，issue #397）——本仓批钉
mutmut==2.5.1（subprocess 跑批，Windows 原生可用，round16 首批
rw_tables/bias_tee 试点同代际）。换大版本必须重验 CLI 面。

用法::

    python scripts/qm9_mutmut_run.py --plan                 # 段① 轮换计划
    python scripts/qm9_mutmut_run.py --run <batch>          # 段② 跑批
    python scripts/qm9_mutmut_run.py --report <batch>       # 报告落 runs/
    python scripts/qm9_mutmut_run.py --replay-plan <batch>  # 段③ 复放计划
    python scripts/qm9_mutmut_run.py --replay-execute <id> <module> <batch>

退出码：0=无真幸存（或纯计划面），2=存在真幸存（复放后仍存活），
1=执行失败，3=mutmut 不可用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]

#: 报告/台账落地根（runs 面不受文档三禁约束）。
REPORT_DIR = _REPO / "runs" / "qm9_mutmut"

#: 等价台账（JSONL；逐条人工登记，脚本只读消费）。
EQUIVALENT_LEDGER = REPORT_DIR / "equivalent_ledger.jsonl"

#: 段① 抽样轮换计划（月度批；新增批=manual 编辑本表，月度推进）。
#: module=被变异源文件（mutmut paths_to_mutate 单文件口径）；tests=段②
#: 窄测 runner 的测试目标；replay_targets=段③ 全量复放的宽测目标。
ROTATION_PLAN: dict[str, list[dict[str, str]]] = {
    # 2026-09 首批（round16 已完成）：rw_tables 84.8% / bias_tee 86.0%
    #   ——结果与"选择伪幸存"方法学发现见 round16 §五现状行（历史批次，
    #   归档在 ，不在本表重复排班）。
    "2026-10": [
        {"module": "src/rfauto/core/quantity.py",
         "tests": "tests/unit/test_quantity.py",
         "replay_targets": "tests/unit/test_quantity.py tests/unit/test_check_numbers.py",
         "rationale": "单位换算内核（quantity 桥，B2-2）——数值正确性的单点"},
    ],
}

#: mutmut run 退出码位（2.5.1 文档口径）。
_EXIT_SURVIVED = 2
_EXIT_TIMEOUT = 4
_EXIT_SLOW = 8

#: `mutmut results` 段头（2.5.1 实测格式：段名 → 空/模块头 → id 段落；
#: id 行形态 "1-2, 19, 24, 51-54"——区间+离散混排）。
_SURVIVED_HEADER_RE = re.compile(r"^Survived\b")
_SECTION_HEADERS = ("Survived", "Killed", "Timeout", "Suspicious",
                    "Untested/skipped", "Skipped")
_ID_RANGE_RE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


def parse_mutmut_results_text(text: str) -> dict[str, list[int]]:
    """`mutmut results` 文本 → 各段 id 表（纯函数；2.5.1 实测格式）。

    形态（2026-10-03 实测）::

        Survived 🙁 (124)

        ---- src/rfauto/core/quantity.py (124) ----

        1-2, 19, 24, 26, 51-54, ...

        Untested/skipped (169)
        ...

    段头行切段；段内跳过模块头（``---- path (N) ----``），剩余行按
    "区间/离散 id" 展开。前导用法说明（apply/show 提示）不在任何段内
    天然忽略。
    """
    sections: dict[str, list[int]] = {}
    current: str | None = None
    ids: list[int] = []
    for raw in text.splitlines():
        ln = raw.strip()
        header = next((h for h in _SECTION_HEADERS if ln.startswith(h)), None)
        if header is not None:
            if current is not None:
                sections[current] = ids
            current, ids = header, []
            continue
        if current is None or not ln:
            continue
        if ln.startswith("----"):
            continue
        if _ID_RANGE_RE.search(ln) is None:
            continue
        for m in _ID_RANGE_RE.finditer(ln):
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            ids.extend(range(lo, hi + 1))
    if current is not None:
        sections[current] = ids
    return sections


def parse_survivors() -> list[int]:
    """`mutmut results` → 幸存 mutant id 表（段②→段③ 的交接面）。

    注：mutmut 2.5.1 不打印 Killed 段（killed=总数−各段，见
    summarize_results）。
    """
    exe = _mutmut_exe()
    proc = subprocess.run([exe, "results"], cwd=str(_REPO),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    sections = parse_mutmut_results_text(proc.stdout or "")
    return sorted(set(sections.get("Survived", [])))


def summarize_results() -> dict[str, Any]:
    """结果段 → 分数汇总（killed 由 max_id−各段 推算；无 Killed 段）。"""
    exe = _mutmut_exe()
    proc = subprocess.run([exe, "results"], cwd=str(_REPO),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    sections = parse_mutmut_results_text(proc.stdout or "")
    all_ids = sorted({i for ids in sections.values() for i in ids})
    n_total = (max(all_ids) if all_ids else 0)
    accounted = sum(len(v) for k, v in sections.items() if k != "Killed")
    n_killed = max(n_total - accounted, 0)
    return {"n_total_mutants": n_total,
            "n_killed": n_killed,
            "n_survived": len(sections.get("Survived", [])),
            "n_suspicious": len(sections.get("Suspicious", [])),
            "n_untested": len(sections.get("Untested/skipped", [])),
            "mutation_score_pct": (round(100.0 * n_killed / n_total, 1)
                                   if n_total else None),
            "note": ("killed 无独立段，由 max_id−(survived+suspicious+"
                     "untested) 推算（2.5.1 结果面实测）；分数是测量值非"
                     "验收门——round16 口径：报告缺口，不清零运动")}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mutmut_exe() -> str:
    """mutmut 可执行定位（venv Scripts 优先， PATH 兜底；无则 RuntimeError）。"""
    candidate = Path(sys.executable).parent / "mutmut.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("mutmut")
    if found:
        return found
    raise RuntimeError(
        "mutmut 不可用（dev extras 未装或版本漂移）——"
        "pip install 'mutmut==2.5.1'（3.x 无原生 Windows 支持，issue #397）")


# ─── 段① 抽样轮换 ───────────────────────────────────────────────────────────


def plan_rotation(batch: str | None = None) -> dict[str, Any]:
    """轮换计划（确定性）：全部批或指定批的模块清单。"""
    if batch is not None:
        if batch not in ROTATION_PLAN:
            raise KeyError(f"批 {batch!r} 不在 ROTATION_PLAN（可用: "
                           f"{sorted(ROTATION_PLAN)}）")
        return {"ok": True, "batch": batch,
                "modules": list(ROTATION_PLAN[batch])}
    return {"ok": True, "batches": {b: list(m) for b, m in
                                    sorted(ROTATION_PLAN.items())}}


# ─── 段② 跑批 ───────────────────────────────────────────────────────────────


def run_batch(batch: str, *, timeout_s: float = 3600.0) -> dict[str, Any]:
    """对批内模块逐个跑 mutmut（subprocess；窄测 runner）。"""
    plan = plan_rotation(batch)
    exe = _mutmut_exe()
    results = []
    for entry in plan["modules"]:
        module = entry["module"]
        if not (_REPO / module).is_file():
            results.append({"module": module, "ok": False,
                            "error": f"模块不存在: {module}"})
            continue
        runner = (f'"{sys.executable}" -m pytest -x -q {entry["tests"]}')
        cmd = [exe, "run",
               f"--paths-to-mutate={module}",
               f"--runner={runner}",
               "--tests-dir=tests/unit",
               "--no-progress"]
        proc = subprocess.run(cmd, cwd=str(_REPO), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout_s)
        results.append({
            "module": module,
            "ok": True,
            "exit_code": proc.returncode,
            "survived_flag": bool(proc.returncode & _EXIT_SURVIVED),
            "timeout_flag": bool(proc.returncode & _EXIT_TIMEOUT),
            "slow_flag": bool(proc.returncode & _EXIT_SLOW),
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
        })
    return {"ok": all(r.get("ok") for r in results), "batch": batch,
            "results": results, "ran_at": _now()}


# ─── 等价台账（段② 的 #122 出口）────────────────────────────────────────────


def load_equivalent_ids(ledger_path: str | Path | None = None
                        ) -> dict[int, dict[str, str]]:
    """台账 → {mutant_id: {reason, registered_by, registered_at}}。

    坏行跳过留痕（#105 best-effort，台账是低风险登记面）。
    （#291 族：缺省参急切求值陷阱——None 缺省+调用点解析，模块级
    EQUIVALENT_LEDGER 的 monkeypatch 才生效。）
    """
    path = Path(ledger_path) if ledger_path is not None else EQUIVALENT_LEDGER
    out: dict[int, dict[str, str]] = {}
    if not path.is_file():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
            out[int(rec["mutant_id"])] = {
                "reason": str(rec.get("reason", "")),
                "registered_by": str(rec.get("registered_by", "")),
                "registered_at": str(rec.get("registered_at", "")),
            }
        except Exception:
            continue
    return out


def classify_survivors(survivor_ids: list[int],
                       ledger_path: str | Path | None = None,
                       ) -> dict[str, list[int]]:
    """幸存者二分类：真幸存（缺口候选）vs 台账等价（已确证不占缺口）。"""
    eq = load_equivalent_ids(ledger_path)
    equivalent = sorted(i for i in survivor_ids if i in eq)
    real = sorted(i for i in survivor_ids if i not in eq)
    return {"real_survivors": real, "equivalent": equivalent}


# ─── 段③ 幸存者全量复放 ─────────────────────────────────────────────────────


def replay_command(mutant_id: int, module: str, replay_targets: str) -> str:
    """幸存者全量复放命令（apply→宽测→还原；按内容哈希核还原是脚本
    --replay-execute 的职责，命令行形态供手工执行）。"""
    return (f'mutmut apply {mutant_id} && '
            f'"{sys.executable}" -m pytest -q {replay_targets}; '
            f'git checkout -- {module}')


def build_replay_plan(batch: str) -> dict[str, Any]:
    """批内全部真幸存者的全量复放计划（确定性）。"""
    plan = plan_rotation(batch)
    survivors = parse_survivors()
    classified = classify_survivors(survivors)
    entries = []
    for entry in plan["modules"]:
        for mid in classified["real_survivors"]:
            entries.append({
                "mutant_id": mid,
                "module": entry["module"],
                "replay_targets": entry["replay_targets"],
                "command": replay_command(mid, entry["module"],
                                          entry["replay_targets"]),
                "note": ("窄测不杀≠全量不杀（round16 选择伪幸存发现）；"
                         "复放仍存活=真缺口候选，进等价台账或补测"),
            })
    return {"ok": True, "batch": batch,
            "n_survivors_raw": len(survivors),
            "n_real": len(classified["real_survivors"]),
            "n_equivalent": len(classified["equivalent"]),
            "equivalent_ids": classified["equivalent"],
            "replay_plan": entries}


def _file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay_execute(mutant_id: int, module: str, batch: str, *,
                   timeout_s: float = 1800.0) -> dict[str, Any]:
    """执行单个幸存者的全量复放（apply→宽测→按哈希核还原）。

    还原守卫：apply 前记录模块内容哈希；复放后 `git checkout --` 还原
    并复算哈希——不一致=还原失败（记 ERROR 并把原内容从 apply 前快照
    回写，工作树不残留变异体）。
    """
    plan = plan_rotation(batch)
    entry = next((e for e in plan["modules"] if e["module"] == module), None)
    if entry is None:
        raise KeyError(f"模块 {module!r} 不在批 {batch!r}")
    target = _REPO / module
    sha_before = _file_sha256(target)
    # apply 前快照（还原失败的兜底回写源）
    snapshot = target.read_bytes()
    exe = _mutmut_exe()
    apply_rc = subprocess.run([exe, "apply", str(mutant_id)], cwd=str(_REPO),
                              capture_output=True, text=True).returncode
    if apply_rc != 0:
        return {"ok": False, "mutant_id": mutant_id,
                "error": f"mutmut apply 退出码 {apply_rc}"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *entry["replay_targets"].split()],
            cwd=str(_REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s)
        still_survives = proc.returncode != 0
        tail = (proc.stdout or "")[-2000:]
    except subprocess.TimeoutExpired:
        still_survives = True
        tail = "replay timeout"
    finally:
        subprocess.run(["git", "checkout", "--", module], cwd=str(_REPO),
                       capture_output=True)
        if _file_sha256(target) != sha_before:
            target.write_bytes(snapshot)   # 兜底回写（工作树不残留变异体）
            restored = "snapshot_fallback"
        else:
            restored = "git_checkout"
    return {"ok": True, "mutant_id": mutant_id, "module": module,
            "still_survives_full_replay": still_survives,
            "restored_via": restored, "sha256_restored": _file_sha256(target),
            "pytest_tail": tail}


# ─── 报告 ───────────────────────────────────────────────────────────────────


def write_report(batch: str, *, run_result: dict[str, Any] | None = None
                 ) -> Path:
    """批报告落 runs/qm9_mutmut/（JSON+MD；确定性文件名带时间戳）。"""
    report: dict[str, Any] = {
        "schema": "rfauto-qm9-mutmut-v1",
        "batch": batch,
        "rotation": plan_rotation(batch),
        "run": run_result,
        "ran_at": _now(),
        "mutmut_pin": "2.5.1（3.x 无原生 Windows 支持，issue #397）",
    }
    try:
        survivors = parse_survivors()
        report["survivors_raw"] = survivors
        report.update(classify_survivors(survivors))
        report["replay"] = build_replay_plan(batch)
        report["summary"] = summarize_results()
    except RuntimeError as exc:
        report["results_error"] = str(exc)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"report_{batch}_{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    md_path = REPORT_DIR / f"report_{batch}_{stamp}.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# QM-9 mutmut 批报告：{report.get('batch', '?')}", "",
             f"- ran_at：{report.get('ran_at')}｜mutmut 钉版："
             f"{report.get('mutmut_pin')}"]
    rot = report.get("rotation", {})
    for m in rot.get("modules", []):
        lines.append(f"- 模块：{m['module']}（窄测 {m['tests']}；"
                     f"理由：{m['rationale']}）")
    if "survivors_raw" in report:
        summary = report.get("summary", {})
        lines += [f"- 总突变体：{summary.get('n_total_mutants', '?')}｜"
                  f"killed：{summary.get('n_killed', '?')}｜survived："
                  f"{summary.get('n_survived', '?')}｜suspicious："
                  f"{summary.get('n_suspicious', '?')}",
                  f"- **突变分数（测量值）：{summary.get('mutation_score_pct', '?')}%"
                  "（round16 口径：测量与报告，不清零运动）**",
                  f"- 幸存者（raw）：{len(report['survivors_raw'])}",
                  f"- 真幸存（缺口候选）：{len(report['real_survivors'])}",
                  f"- 台账等价：{len(report['equivalent'])}",
                  "", "## 真幸存者全量复放计划", ""]
        for e in report.get("replay", {}).get("replay_plan", []):
            lines.append(f"- mutant {e['mutant_id']}（{e['module']}）："
                         f"`{e['command']}`")
        if not report.get("replay", {}).get("replay_plan"):
            lines.append("-（无真幸存者——复放计划空）")
    if "results_error" in report:
        lines.append(f"- results 解析失败：{report['results_error']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="QM-9 mutmut 三段路 runner")
    ap.add_argument("--plan", action="store_true", help="段① 打印轮换计划")
    ap.add_argument("--run", metavar="BATCH", help="段② 跑批")
    ap.add_argument("--report", metavar="BATCH", help="批报告落 runs/")
    ap.add_argument("--replay-plan", metavar="BATCH", help="段③ 复放计划")
    ap.add_argument("--replay-execute", nargs=3, metavar=("MUTANT_ID", "MODULE", "BATCH"),
                    help="段③ 执行单幸存者复放")
    ap.add_argument("--timeout", type=float, default=3600.0)
    args = ap.parse_args()

    try:
        if args.plan:
            print(json.dumps(plan_rotation(args.run or None), ensure_ascii=False,
                             indent=1))
            return 0
        if args.run:
            exe = _mutmut_exe()
            print(f"[qm9] mutmut={exe}")
            r = run_batch(args.run, timeout_s=args.timeout)
            out = write_report(args.run, run_result=r)
            print(f"[qm9] 报告：{out}")
            if any(x.get("survived_flag") for x in r["results"]):
                return 2
            return 0 if r["ok"] else 1
        if args.report:
            out = write_report(args.report)
            print(f"[qm9] 报告：{out}")
            return 0
        if args.replay_plan:
            print(json.dumps(build_replay_plan(args.replay_plan),
                             ensure_ascii=False, indent=1))
            return 0
        if args.replay_execute:
            mid, module, batch = args.replay_execute
            r = replay_execute(int(mid), module, batch, timeout_s=args.timeout)
            print(json.dumps(r, ensure_ascii=False, indent=1))
            if not r["ok"]:
                return 1
            return 2 if r["still_survives_full_replay"] else 0
    except RuntimeError as exc:
        print(f"[qm9] {exc}", file=sys.stderr)
        return 3
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
