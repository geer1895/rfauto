"""pool_patrol 冻结帧夹具刷新器（显式动作，不进任何门）。

把 tests/unit/test_pool_patrol.py::TestGoldCalibrationRealRepo::
test_default_gold_rate_is_one 的输入帧（真仓活扫）再提取为 committed
夹具 tests/fixtures/pool_patrol_frame.json。单元门测试读夹具（秒级），
本脚本是唯一的夹具再生成通道。

【它扫什么】真仓帧=池登记文档 docs/plan_expansion_pool_20260924.md +
git 全史（git log --all，两趟：消息/文件清单）+ impl 面（src/tests/
scripts *.py 全文）。注意：runs/ 数据湖从不进扫描面；门时长膨胀源是
git 史与 impl 面随开发增长，夹具化后单元门成本与仓库增长脱钩。

【夹具内容】最小证据帧：全量扫描后只保留金标集（DEFAULT_GOLD_CLOSED/
DEFAULT_GOLD_OPEN 22 ID）裁决所需的 commit（消息命中 gold token）与
文件（实际产出 code evidence 命中者；不足时自动升级 token/关键词超集
过滤），外加池文档全文快照。写入前内建等价门：夹具集重扫 vs 全量扫
描，gold 键 tag/code 证据与校准表逐键一致才落盘；活扫 rate!=1.0 时拒
绝落盘（先修工具或重裁金标，不许把红态洗进单元门）。

【何时该刷新】
1. 池登记文档新增轮次/金标 ID 迁移（DEFAULT_GOLD_* 变更）；
2. 引擎判据修订（pool_patrol_service 判据/消歧逻辑改动）后需要把新
   判据下的真实帧证据重新锚定；
3. 显式活扫对照发现夹具与活帧裁决漂移（先跑
   RFAUTO_POOL_PATROL_LIVE=1 pytest tests/integration/test_pool_
   patrol_live.py 对照，确认是合法湖演化而非工具回归）。

用法：
    .venv/Scripts/python.exe scripts/refresh_pool_patrol_fixture.py
        # 重扫活帧 → 落盘夹具 → 打印与现夹具的 diff 摘要
    .venv/Scripts/python.exe scripts/refresh_pool_patrol_fixture.py --check
        # 只验证：重扫活帧并与现夹具逐字节比对，不写盘（漂移 exit 1）

幂等性：夹具内不含墙钟时间戳（快照时点由 source_head+source_stats 承
载），仓库无变化时重复执行输出逐字节一致（git diff 空）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.pool_patrol_service import (  # noqa: E402
    _SELF_PATH_MARK,
    DEFAULT_GOLD_CLOSED,
    DEFAULT_GOLD_OPEN,
    _git_log_commits,
    _load_impl_face,
    _resolve_gold_id,
    calibrate,
    judge_item,
    parse_pool_doc,
    scan_code_evidence,
    scan_commit_evidence,
    token_pattern,
)

DEFAULT_FIXTURE = REPO / "tests" / "fixtures" / "pool_patrol_frame.json"
POOL_DOC = REPO / "docs" / "plan_expansion_pool_20260924.md"


def _rel_path(p: str, repo_root: Path) -> str:
    """绝对 impl 面路径 → 仓相对 posix 路径（夹具可移植）。"""
    q = Path(p)
    try:
        return q.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return q.as_posix()


def _items_by_key(items: list) -> dict:
    return {(it.round_no, it.token): it for it in items}


def _scan_live(repo_root: Path) -> dict:
    """全量活扫（阶段计时）。返回帧与证据。"""
    t0 = time.perf_counter()
    text = POOL_DOC.read_text(encoding="utf-8", errors="replace")
    items = parse_pool_doc(text)
    t_parse = time.perf_counter() - t0

    t0 = time.perf_counter()
    commits = _git_log_commits(repo_root, None)
    t_git = time.perf_counter() - t0

    t0 = time.perf_counter()
    files = _load_impl_face(repo_root)
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    tag_ev = scan_commit_evidence(items, commits, None)
    code_ev = scan_code_evidence(items, files, None)
    t_scan = time.perf_counter() - t0

    print(f"[live] items={len(items)} commits={len(commits)} files={len(files)} "
          f"impl_bytes={sum(len(v) for v in files.values())}")
    print(f"[live] timing parse={t_parse:.2f}s git_log={t_git:.2f}s "
          f"load_impl={t_load:.2f}s scan={t_scan:.2f}s")
    return {
        "text": text, "items": items, "commits": commits, "files": files,
        "tag_ev": tag_ev, "code_ev": code_ev,
    }


def _gold_keys(items: list) -> set:
    keys = set()
    for name in (*DEFAULT_GOLD_CLOSED, *DEFAULT_GOLD_OPEN):
        it = _resolve_gold_id(name, items)
        if it is not None:
            keys.add((it.round_no, it.token))
    return keys


def _verdicts_of(items, tag_ev, code_ev) -> dict:
    return {(it.round_no, it.token): judge_item(it, tag_ev[(it.round_no, it.token)],
                                               code_ev[(it.round_no, it.token)])
            for it in items}


def _extract_minimal(live: dict, gold_keys: set) -> tuple[list, dict]:
    """最小证据帧：gold 命中 commit + 实际产出 code 命中的文件。

    文件键保持与活扫同锚（绝对路径）——等价门要逐键比对证据；落盘时才
    相对化（_build_fixture）。排序次序不受锚影响（统一前缀剥离保序）。"""
    gold_tokens = sorted({tok for (_r, tok) in gold_keys})
    pats = {tok: token_pattern(tok) for tok in gold_tokens}
    keep_commits = [c for c in live["commits"]
                    if any(p.search(c.message) for p in pats.values())]
    hit_paths = sorted({h["path"] for k in gold_keys for h in live["code_ev"][k]})
    keep_files = {}
    for p in hit_paths:
        if _SELF_PATH_MARK in p.lower():
            continue
        keep_files[p] = live["files"][p]
    return keep_commits, keep_files


def _extract_superset(live: dict, gold_keys: set) -> tuple[list, dict]:
    """超集兜底帧：gold token/强关键词/文件名压缩形任一命中即保留。"""
    from rfauto.service.pool_patrol_service import _compact

    gold_tokens = sorted({tok for (_r, tok) in gold_keys})
    pats = {tok: token_pattern(tok) for tok in gold_tokens}
    keep_commits = [c for c in live["commits"]
                    if any(p.search(c.message) for p in pats.values())]
    by_key = _items_by_key(live["items"])
    kws = set()
    for k in gold_keys:
        kws.update(by_key[k].keywords_strong)
    compact_tokens = {tok: _compact(tok) for tok in gold_tokens}
    keep_files = {}
    for p, ftext in live["files"].items():
        if _SELF_PATH_MARK in p.lower():
            continue
        cp = _compact(Path(p).name)
        if (any(ct and ct in cp for ct in compact_tokens.values())
                or any(pt.search(ftext) for pt in pats.values())
                or any(kw in ftext for kw in kws)):
            keep_files[p] = ftext
    return keep_commits, keep_files


def _verify_equivalence(live: dict, keep_commits: list, keep_files: dict,
                        gold_keys: set) -> tuple[bool, list, dict, dict]:
    """夹具集重扫 vs 全量：gold 键证据+裁决+校准逐键一致才算过。"""
    tag2 = scan_commit_evidence(live["items"], keep_commits, None)
    code2 = scan_code_evidence(live["items"], keep_files, None)
    bad = []
    for k in sorted(gold_keys):
        if live["tag_ev"][k] != tag2[k]:
            bad.append(("tag", k))
        if live["code_ev"][k] != code2[k]:
            bad.append(("code", k))
    cal_full = calibrate(_verdicts_of(live["items"], live["tag_ev"], live["code_ev"]),
                         live["items"])
    cal_fix = calibrate(_verdicts_of(live["items"], tag2, code2), live["items"])
    for field in ("rated", "agree", "rate"):
        if cal_full[field] != cal_fix[field]:
            bad.append(("calibration", field))
    if [m["id"] for m in cal_full["mismatches"]] != [m["id"] for m in cal_fix["mismatches"]]:
        bad.append(("calibration", "mismatches"))
    return (not bad), bad, cal_full, cal_fix


def _build_fixture(live: dict, keep_commits: list, keep_files: dict,
                   tier: str) -> str:
    """组夹具 JSON 文本（手工分片序列化：头/commits/每文件各一行，git diff
    可按行读）。无墙钟时间戳（幂等）；快照时点=source_head+source_stats。"""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    stats = {
        "git_commits_total": len(live["commits"]),
        "impl_files_total": len(live["files"]),
        "impl_bytes_total": sum(len(v) for v in live["files"].values()),
        "pool_doc_lines": live["text"].count("\n") + 1,
        "gold_ids": len(DEFAULT_GOLD_CLOSED) + len(DEFAULT_GOLD_OPEN),
    }
    parts: list[str] = []
    parts.append("{")
    parts.append(f' "schema_version": {json.dumps("pool_patrol_frame/1.0")},')
    parts.append(f' "extraction_tier": {json.dumps(tier)},')
    parts.append(f' "source_head": {json.dumps(head)},')
    parts.append(' "source_stats": ' + json.dumps(stats, ensure_ascii=False) + ",")
    parts.append(' "pool_doc_sha256": '
                 + json.dumps(hashlib.sha256(POOL_DOC.read_bytes()).hexdigest()) + ",")
    parts.append(' "gold_closed": ' + json.dumps(list(DEFAULT_GOLD_CLOSED)) + ",")
    parts.append(' "gold_open": ' + json.dumps(list(DEFAULT_GOLD_OPEN)) + ",")
    parts.append(' "pool_doc_text": ' + json.dumps(live["text"], ensure_ascii=False) + ",")
    parts.append(' "commits": [')
    for i, c in enumerate(keep_commits):
        rec = {"sha": c.sha, "date": c.date, "subject": c.subject,
               "body": c.body, "files": list(c.files)}
        comma = "," if i < len(keep_commits) - 1 else ""
        parts.append("  " + json.dumps(rec, ensure_ascii=False) + comma)
    parts.append("],")
    parts.append(' "files": {')
    rel_files = {_rel_path(p, REPO): ftext for p, ftext in keep_files.items()}
    for i, (p, ftext) in enumerate(sorted(rel_files.items())):
        comma = "," if i < len(rel_files) - 1 else ""
        parts.append("  " + json.dumps(p, ensure_ascii=False) + ": "
                     + json.dumps(ftext, ensure_ascii=False) + comma)
    parts.append("}")
    parts.append("}")
    return "\n".join(parts) + "\n"


def _diff_summary(old: dict | None, new: dict) -> list[str]:
    """与现夹具的人类可读 diff 摘要（不含全文比对）。"""
    lines: list[str] = []
    if old is None:
        lines.append("diff: 无现夹具（首次生成）")
        return lines
    if old.get("source_head") != new.get("source_head"):
        lines.append(f"diff: source_head {old.get('source_head')[:10]} -> "
                     f"{new.get('source_head')[:10]}")
    if old.get("pool_doc_sha256") != new.get("pool_doc_sha256"):
        lines.append("diff: 池登记文档已演化（sha256 变化）")
    oc = {c["sha"] for c in old.get("commits", [])}
    nc = {c["sha"] for c in new["commits"]}
    added, removed = nc - oc, oc - nc
    if added or removed:
        lines.append(f"diff: commits +{len(added)}/-{len(removed)}")
        for sha in sorted(added)[:5]:
            subj = next((c["subject"] for c in new["commits"] if c["sha"] == sha), "")
            lines.append(f"  + {sha[:10]} {subj[:80]}")
        for sha in sorted(removed)[:5]:
            lines.append(f"  - {sha[:10]}")
    of = set(old.get("files", {}))
    nf = set(new["files"])
    fadd, frem = nf - of, of - nf
    if fadd or frem:
        lines.append(f"diff: files +{len(fadd)}/-{len(frem)}")
        for p in sorted(fadd)[:8]:
            lines.append(f"  + {p}")
        for p in sorted(frem)[:8]:
            lines.append(f"  - {p}")
    if not lines:
        lines.append("diff: 现夹具已是最新帧（无结构差异）")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh_pool_patrol_fixture.py",
        description="pool_patrol 冻结帧夹具刷新器（显式动作；活扫 ~4min）")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                        help="夹具输出路径（缺省 tests/fixtures/pool_patrol_frame.json）")
    parser.add_argument("--check", action="store_true",
                        help="只验证不写盘：重扫活帧与现夹具逐字节比对")
    args = parser.parse_args(argv)

    live = _scan_live(REPO)
    gold_keys = _gold_keys(live["items"])
    print(f"[extract] gold_keys={len(gold_keys)}")

    tier = "minimal"
    keep_commits, keep_files = _extract_minimal(live, gold_keys)
    ok, bad, cal_full, _cal_fix = _verify_equivalence(live, keep_commits, keep_files,
                                                      gold_keys)
    if not ok:
        tier = "superset"
        keep_commits, keep_files = _extract_superset(live, gold_keys)
        ok, bad, cal_full, _cal_fix = _verify_equivalence(
            live, keep_commits, keep_files, gold_keys)
    print(f"[extract] tier={tier} commits={len(keep_commits)} "
          f"files={len(keep_files)} file_bytes={sum(len(v) for v in keep_files.values())}")
    if not ok:
        print(f"[verify] FAIL 等价门不过: {bad}", file=sys.stderr)
        return 3
    print("[verify] 等价门 PASS（gold 键证据+校准逐键一致）")
    print(f"[calibration] live rated={cal_full['rated']} agree={cal_full['agree']} "
          f"rate={cal_full['rate']} mismatches={[m['id'] for m in cal_full['mismatches']]}")
    if cal_full["rate"] != 1.0:
        print("[gate] 活帧金标 rate!=1.0——先修工具或重裁金标，拒绝把红态洗进夹具"
              "（详见 [calibration] 行）", file=sys.stderr)
        return 4

    text = _build_fixture(live, keep_commits, keep_files, tier)
    old: dict | None = None
    if args.fixture.is_file():
        try:
            old = json.loads(args.fixture.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[diff] 现夹具不可解析（将覆盖）: {exc}")
    if args.check:
        if old is None:
            print("[check] 无现夹具可验证", file=sys.stderr)
            return 2
        if old == json.loads(text):
            print("[check] PASS 夹具与活帧一致")
            return 0
        for line in _diff_summary(old, json.loads(text)):
            print(line)
        print("[check] DRIFT 夹具落后于活帧——重跑本脚本（不带 --check）刷新",
              file=sys.stderr)
        return 1

    args.fixture.parent.mkdir(parents=True, exist_ok=True)
    args.fixture.write_text(text, encoding="utf-8", newline="\n")
    print(f"[write] {args.fixture} ({args.fixture.stat().st_size} bytes, "
          f"time={time.strftime('%Y-%m-%dT%H:%M:%S')})")
    for line in _diff_summary(old, json.loads(text)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
