#!/usr/bin/env python3
"""aurora_m W1-7 席：时长棘轮预算生成器（manifest → committed 预算，只紧不松）。

职责与铁律
----------
* 读 durations manifest（scripts/build_durations_manifest.py 产物，
  schema=aurora_m_durations_manifest_v2），生成/更新 committed 预算文件
  tests/fixtures/duration_budgets.yaml（schema=aurora_m_duration_budget_v1，
  执法器=scripts/check_duration_ratchet.py）。
* **只紧不松（红线 1）**：预算值只能由本脚本显式再生成动作更新，且——
  新值 ≤ 旧值（容差 JITTER_EPS_S=0.05s，吸收轮间毫秒级抖动）→ 自动接受；
  新值 > 旧值 + 容差 → 拒绝写盘并列出全部回涨条目，必须显式
  ``--accept-slower "理由"`` 放行（理由+新旧值+条目清单落盘 slower_acceptances
  历史段，防语料回涨悄悄过关）。文件层同理（见下）。
* 确定性：generated_at 取 manifest 的 generated_at（非墙钟）；全部输入附
  sha256 指纹；同 manifest 两跑逐字节一致（幂等，验收钉）。

预算覆盖面（数据化决策，实测 aurora_m base manifest）
----------------------------------------------------
* 逐条预算：manifest duration ≥ BUDGET_MIN_S(1.0s) 的条目（B+C 层 538 条）。
  A 层 28165 条合计仅 655.9s（均值 23ms）——逐条钉 28k 行的执法成本与亚秒
  抖动误报完全盖过信号。
* 文件层预算：全部 1144 文件各一条（合计预算），兜底亚秒条目累积漂移。
* 执法系数/余量常量定义在 check_duration_ratchet.py（执法面单一来源），本
  脚本回显进 generation_params——改动系数=代码改动=评审可见。

--remeasure-junit（冻结件诚实回填）
------------------------------------
* 传一个或多个 junitxml（对指定文件真跑 pytest 的产物），条目 nodeid 命中
  处以 xml 实测覆盖预算值（remeasured: true，执法系数用 ×2.0 重测档）。
* 重测值按只紧不松封顶：min(重测值, manifest 源值)——上限只降不升。
* 用途：W1-1/1-2 冻结件（pool_patrol 207→12s、league/criteria 29.5→8.4s）
  的 manifest 数字系争用轮历史，预算必须诚实反映现树。**不带 --remeasure-junit
  再生成时，冻结件新值（manifest 288s）> 旧预算（12s）会被只紧不松拦下**——
  这是有意的：刷新必须携带重测证据或显式 --accept-slower。

文件层只紧不松的"新增测试豁免"语义
----------------------------------
* 文件合计含新增测试时长属"登记"非"回涨"——比较基准 =
  Σ(新旧两代都在册的预算条目新时长) + 亚阈质量贡献；后者按亚阈总体指纹
  分派：sub_threshold_sha256（该文件 <1s 条目 id 排序串的 sha256）一致
  （无增删测试）→ 新亚阈合计全额计入基准（既有条目漂移被拦）；指纹不一致
  （有增删）→ min(新合计, 旧合计)（新增测试的增量豁免，幸存条目漂移被
  新增增量掩护属已知软边界，下轮无增删再生成时补拦）。基准 > 旧文件预算 +
  0.05s 才算回涨需 --accept-slower；新增预算条目（≥1s）另经逐条
  unregistered 线与文件层执法线（×1.5+1s）双重执法。
* 亚阈指纹进预算文件（sub_threshold_sum_s/sub_threshold_sha256），自审
  （sha 锚定模式）对 manifest 重算比对——手改指纹掩护漂移会被抓。
* 残余软边界（阈值化预算固有，如实声明）：亚阈（<1s）既有条目在"同轮既
  有新增测试"掩护下的漂移到下轮补拦；跨过 1s 登记线后按新值登记（登记
  动作=显式再生成，diff 可见）。

终门后刷新工作流（W1-8 接线用，两命令）
--------------------------------------
1) .venv/Scripts/python.exe scripts/build_durations_manifest.py \\
     --name <新门产物名> --agg-log runs/<新门>.log --out runs/aurora_m/durations_manifest.yaml
2) .venv/Scripts/python.exe scripts/generate_duration_budget.py
   （拦截时按提示 --accept-slower "理由"；冻结件重测加 --remeasure-junit）
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "runs/aurora_m/durations_manifest.yaml"
DEFAULT_BUDGET = REPO_ROOT / "tests/fixtures/duration_budgets.yaml"
TESTS_ROOT = REPO_ROOT / "tests"

SCHEMA_VERSION = "aurora_m_duration_budget_v1"
JITTER_EPS_S = 0.05  # 只紧不松比较容差（轮间毫秒级抖动；上限可被无声漂移的幅度）

_RATCHET_SPEC_NAME = "duration_ratchet_core_for_budget_gen"

# 装载缓存（同进程多次 main() 不重复 exec 模块——棘轮测试模块总时长 <2s 红线）
_RATCHET_CORE: Any = None
_BUILD_DURATIONS: Any = None


def _load_ratchet_core():
    """经 importlib 装载执法器模块（复用快扫器+常量，单一来源）。"""
    global _RATCHET_CORE
    if _RATCHET_CORE is not None:
        return _RATCHET_CORE
    path = Path(__file__).resolve().parent / "check_duration_ratchet.py"
    spec = importlib.util.spec_from_file_location(_RATCHET_SPEC_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _RATCHET_CORE = mod
    return mod


def _load_build_durations():
    """经 importlib 装载 manifest 生成器（复用 nodeid 推导/指纹函数，防漂移）。"""
    global _BUILD_DURATIONS
    if _BUILD_DURATIONS is not None:
        return _BUILD_DURATIONS
    path = Path(__file__).resolve().parent / "build_durations_manifest.py"
    spec = importlib.util.spec_from_file_location("build_durations_manifest_for_budget", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _BUILD_DURATIONS = mod
    return mod


class _Flow(dict):
    """标记 flow-style 的映射（逐条紧凑单行，控制产物体积）。"""


class _BudgetDumper(yaml.SafeDumper):
    """SafeDumper + _Flow 紧凑映射支持。"""


_BudgetDumper.add_representer(
    _Flow,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=True
    ),
)


def _load_remeasure_map(xml_paths: list[Path]) -> dict[str, float]:
    """junitxml 列表 → {nodeid: 实测秒}（nodeid 推导复用 manifest 生成器，防漂移）。"""
    bdm = _load_build_durations()
    test_files = bdm._load_test_file_set(TESTS_ROOT)
    mapping: dict[str, float] = {}
    for xp in xml_paths:
        root = ET.parse(xp).getroot()
        n = 0
        for tc in root.iter("testcase"):
            classname = tc.get("classname") or ""
            name = tc.get("name") or ""
            file_path, cid = bdm._split_classname(classname, name, test_files)
            mapping[f"{file_path}::{cid}"] = float(tc.get("time") or 0.0)
            n += 1
        if n == 0:
            raise SystemExit(f"--remeasure-junit 无 testcase: {xp}")
    return mapping


def _fingerprint(path: Path) -> dict[str, Any]:
    """输入指纹（路径相对仓根/大小/sha256/mtime——确定性输出的一部分）。"""
    bdm = _load_build_durations()
    return bdm._fingerprint(Path(path), REPO_ROOT)


def _build_budget(
    manifest: dict[str, Any],
    manifest_rel_path: str,
    old_budget: dict[str, Any] | None,
    remeasure_map: dict[str, float],
    remeasure_sources: list[dict[str, Any]],
    accept_slower_reason: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """装配预算文档；返回 (budget_doc, slower_list, regen_diff)。

    slower_list 非空且 accept_slower_reason 为 None 时由调用方拒绝写盘。
    """
    ratchet = _load_ratchet_core()
    entries_src: dict[str, tuple[str, float, str]] = manifest["entries"]
    source_s: dict[str, float] = {nid: round(v[1], 3) for nid, v in entries_src.items()}
    old_entries: dict[str, Any] = (old_budget or {}).get("entries") or {}
    old_files: dict[str, Any] = (old_budget or {}).get("file_budgets") or {}
    budget_min = ratchet.BUDGET_MIN_S

    # ---- 逐条预算（≥1s；重测命中则以 min(重测, 源值) 覆盖——上限只降不升）----
    new_entries: dict[str, Any] = {}
    for nid in sorted(entries_src):
        dur = source_s[nid]
        if dur < budget_min:
            continue
        remeasured = nid in remeasure_map
        value = round(min(remeasure_map[nid], dur), 3) if remeasured else dur
        new_entries[nid] = _Flow(
            budget_s=value,
            source_s=dur,
            tier=entries_src[nid][2],
            file=entries_src[nid][0],
            remeasured=remeasured,
        )

    # ---- 生效时长（文件层/基准计算用：重测命中处用重测值）----
    eff_dur: dict[str, float] = {}
    for nid, v in entries_src.items():
        eff_dur[nid] = round(min(remeasure_map[nid], v[1]), 3) if nid in remeasure_map else v[1]

    # ---- 文件层合计（全部文件）+ 亚阈总体指纹（生成期新增豁免的判别依据）----
    file_totals: dict[str, float] = {}
    file_counts: dict[str, int] = {}
    file_sub_ids: dict[str, list[str]] = {}
    for nid, v in entries_src.items():
        f = v[0]
        file_totals[f] = file_totals.get(f, 0.0) + eff_dur[nid]
        file_counts[f] = file_counts.get(f, 0) + 1
        if v[1] < budget_min:
            file_sub_ids.setdefault(f, []).append(nid)
    new_files: dict[str, Any] = {}
    for f in sorted(file_totals):
        sub_ids = sorted(file_sub_ids.get(f, []))
        new_files[f] = _Flow(
            budget_total_s=round(file_totals[f], 3),
            n_tests=file_counts[f],
            sub_threshold_sum_s=round(
                sum(entries_src[nid][1] for nid in sub_ids), 3
            ),
            sub_threshold_sha256=hashlib.sha256("\n".join(sub_ids).encode("utf-8")).hexdigest(),
        )

    # ---- 只紧不松对账（vs 旧预算）----
    slower: list[dict[str, Any]] = []
    diff = {
        "tightened": 0,
        "loosened": 0,
        "new": 0,
        "dropped": 0,
        "files_tightened": 0,
        "files_loosened": 0,
        "files_new": 0,
        "files_dropped": 0,
    }
    if old_budget is not None:
        for nid in sorted(new_entries):
            old = old_entries.get(nid)
            new_s = float(new_entries[nid]["budget_s"])
            if old is None:
                diff["new"] += 1
                continue
            old_s = float(old["budget_s"])
            if new_s > old_s + JITTER_EPS_S:
                slower.append(
                    {"kind": "test", "target": nid, "old_s": old_s, "new_s": new_s}
                )
            elif new_s < old_s - JITTER_EPS_S:
                diff["tightened"] += 1
        diff["dropped"] = sum(1 for nid in old_entries if nid not in new_entries)
        for f in sorted(new_files):
            old_fb = old_files.get(f)
            new_total = float(new_files[f]["budget_total_s"])
            if old_fb is None:
                diff["files_new"] += 1
                continue
            old_total = float(old_fb["budget_total_s"])
            # 新增测试豁免：基准 = 新旧都在册的预算条目新时长 + 亚阈质量贡献
            # （亚阈指纹一致=无增删→新合计全额计入=既有条目漂移被拦；
            #   指纹不一致=有增删→min(新,旧) 差值豁免，见模块 docstring）
            old_sub_sum = float(old_fb.get("sub_threshold_sum_s", 0.0))
            old_sub_sha = old_fb.get("sub_threshold_sha256")
            new_sub_sum = float(new_files[f]["sub_threshold_sum_s"])
            if old_sub_sha is not None and new_files[f]["sub_threshold_sha256"] == old_sub_sha:
                sub_contrib = new_sub_sum
            else:
                sub_contrib = min(new_sub_sum, old_sub_sum)
            baseline = sum(
                eff_dur[nid]
                for nid in old_entries
                if nid in entries_src and entries_src[nid][0] == f
            ) + sub_contrib
            if baseline > old_total + ratchet.FILE_TOTAL_EPS:
                slower.append(
                    {
                        "kind": "file",
                        "target": f,
                        "old_s": old_total,
                        "new_s": round(new_total, 3),
                    }
                )
            elif baseline < old_total - ratchet.FILE_TOTAL_EPS:
                diff["files_tightened"] += 1
        diff["files_dropped"] = sum(1 for f in old_files if f not in new_files)
    diff["loosened"] = len([s for s in slower if s["kind"] == "test"])
    diff["files_loosened"] = len([s for s in slower if s["kind"] == "file"])

    # ---- 装配（确定性插入序）----
    gen_at = manifest["generated_at"]
    slower_acceptances = list((old_budget or {}).get("only_tighten", {}).get(
        "slower_acceptances", []
    ))
    if slower and accept_slower_reason is not None:
        slower_acceptances.append(
            {
                "generated_at": gen_at,
                "reason": accept_slower_reason,
                "entries": [
                    _Flow(
                        kind=s["kind"],
                        target=s["target"],
                        old_s=s["old_s"],
                        new_s=s["new_s"],
                    )
                    for s in sorted(slower, key=lambda x: (x["kind"], x["target"]))
                ],
            }
        )
    params = {
        "budget_min_s": ratchet.BUDGET_MIN_S,
        "noise_factor": ratchet.NOISE_FACTOR,
        "noise_factor_remeasured": ratchet.NOISE_FACTOR_REMEASURED,
        "file_noise_factor": ratchet.FILE_NOISE_FACTOR,
        "file_abs_slack_s": ratchet.FILE_ABS_SLACK_S,
        "file_unregistered_min_s": ratchet.FILE_UNREGISTERED_MIN_S,
        "note": (
            "常量单一来源=scripts/check_duration_ratchet.py（执法面），此处为回显；"
            "系数依据（争用带 +44% 实测/重测档放宽/文件层双条件）见该模块 docstring"
        ),
    }
    budget_doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": gen_at,
        "generator": "scripts/generate_duration_budget.py",
        "source_manifest": {
            "path": manifest_rel_path,
            "sha256": manifest["sha256"],
            "schema_version": manifest["schema_version"],
            "generated_at": manifest["generated_at"],
            "source_run_name": manifest["source_run_name"],
            "wall_min": manifest["wall_min"],
            "contention_note": manifest["contention_note"],
        },
        "generation_params": params,
        "remeasure": {
            "note": (
                "W1-1/1-2 冻结件诚实回填：manifest 数字系争用轮历史，"
                "预算按现树专用重测回填（remeasured 条目执法系数 ×2.0）"
            )
            if remeasure_sources
            else None,
            "sources": remeasure_sources,
        },
        "only_tighten": {
            "rule": (
                f"再生成时新值≤旧值+{JITTER_EPS_S}s 容差自动接受；超出需显式 "
                '--accept-slower "理由"（理由+新旧值落本段历史，防语料回涨悄悄过关）'
            ),
            "slower_acceptances": slower_acceptances,
        },
        "stats": {
            "manifest_entries": len(entries_src),
            "entries_budgeted": len(new_entries),
            "files_budgeted": len(new_files),
            "budgeted_sum_s": round(
                sum(float(e["budget_s"]) for e in new_entries.values()), 3
            ),
            "file_totals_sum_s": round(sum(file_totals.values()), 3),
            # regen_diff 只进 stdout 运行报告不落盘——保证"同 manifest 两跑逐字节
            # 一致"（首次生成与再生成的 diff 语义不同，落盘会破坏幂等验收钉）
        },
        "entries": new_entries,
        "file_budgets": new_files,
    }
    return budget_doc, slower, diff


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="时长棘轮预算生成器（只紧不松）")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="durations manifest 路径")
    ap.add_argument("--out", default=str(DEFAULT_BUDGET), help="预算文件输出路径")
    ap.add_argument(
        "--remeasure-junit",
        action="append",
        default=[],
        help="冻结件重测 junitxml（可多次）；命中条目以重测值回填并标 remeasured",
    )
    ap.add_argument(
        "--accept-slower",
        metavar="REASON",
        default=None,
        help="放行本轮回涨条目（必须给出理由；理由+新旧值落盘 slower_acceptances）",
    )
    args = ap.parse_args(argv)

    ratchet = _load_ratchet_core()
    manifest_path = Path(args.manifest)
    out_path = Path(args.out)
    try:
        manifest = ratchet.scan_manifest(manifest_path)
    except ratchet.RatchetError as exc:
        print(f"[duration-budget] 输入不可用: {exc}", file=sys.stderr)
        return 3
    if manifest["schema_version"] != ratchet.EXPECTED_MANIFEST_SCHEMA:
        print(
            f"[duration-budget] manifest schema 不识别: {manifest['schema_version']!r}",
            file=sys.stderr,
        )
        return 3
    try:
        manifest_rel_path = manifest_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        manifest_rel_path = manifest_path.resolve().as_posix()

    old_budget: dict[str, Any] | None = None
    if out_path.exists():
        try:
            old_budget = ratchet.load_budget(out_path)
        except ratchet.RatchetError as exc:
            print(f"[duration-budget] 既有预算不可读（拒绝覆盖，先人工处置）: {exc}", file=sys.stderr)
            return 3

    remeasure_paths = [Path(p) for p in args.remeasure_junit]
    missing = [p for p in remeasure_paths if not p.exists()]
    if missing:
        print(f"[duration-budget] --remeasure-junit 不存在: {missing}", file=sys.stderr)
        return 3
    remeasure_map = _load_remeasure_map(remeasure_paths) if remeasure_paths else {}
    remeasure_sources = [_fingerprint(p) for p in remeasure_paths]
    for src in remeasure_sources:
        src["n_overrides"] = sum(
            1
            for nid in remeasure_map
            if nid in manifest["entries"] and manifest["entries"][nid][1] >= ratchet.BUDGET_MIN_S
        )

    budget_doc, slower, diff = _build_budget(
        manifest,
        manifest_rel_path,
        old_budget,
        remeasure_map,
        remeasure_sources,
        args.accept_slower,
    )
    if slower and args.accept_slower is None:
        print("[duration-budget] 只紧不松拦截：以下条目新值 > 旧预算（拒绝写盘）。", file=sys.stderr)
        print("[duration-budget] 处置：查明回涨原因；确属正当（环境/语料变更）再执行", file=sys.stderr)
        print(
            '[duration-budget]   ... --accept-slower "理由" 放行（将落盘审计历史）。',
            file=sys.stderr,
        )
        for s in sorted(slower, key=lambda x: (x["kind"], x["target"])):
            print(
                f"  [{s['kind']}] {s['target']}  旧={s['old_s']:.3f}s 新={s['new_s']:.3f}s"
                f" (+{s['new_s'] - s['old_s']:.3f}s)",
                file=sys.stderr,
            )
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(
        budget_doc,
        Dumper=_BudgetDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
        default_flow_style=False,
    )
    out_path.write_text(text, encoding="utf-8", newline="\n")

    stats = budget_doc["stats"]
    slower_note = (
        f"（--accept-slower 放行 {len(slower)} 条，理由已落盘）" if slower else ""
    )
    print(
        f"OK {out_path}: 逐条预算 {stats['entries_budgeted']}"
        f"（≥{ratchet.BUDGET_MIN_S}s）/ 文件预算 {stats['files_budgeted']} / "
        f"manifest 条目 {stats['manifest_entries']} / 重测覆盖 {len(remeasure_map)} 条"
        f"{slower_note}"
    )
    if old_budget is not None:
        print(f"  regen_diff: {diff}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
