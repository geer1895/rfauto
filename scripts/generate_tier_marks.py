#!/usr/bin/env python3
"""aurora_m W1-8 席：tier 分层名单生成器 → tests/fixtures/test_tiers.yaml（committed）。

职责与口径
----------
* 数据源 = runs/aurora_m/durations_manifest.yaml（W0-1 canonical 画像，28703 条）
  的 tier 字段直读；**W1-1/1-2 冻结件三文件例外**——其条目时长用现树专用重测
  （runs/aurora_m/w1_7/remeasure_frozen.xml，W1-7 席产物）替换后机械重判层，
  消化 manifest 争用轮对冻结件的巨大失真（pool_patrol 冠军 288.259s 系争用
  历史值，现树实测 12.454s）。
* 冻结件重判裁定（任务书明示，2026-10-28）：**重测后仍 ≥C 阈值者保 B 档**
  （"pool_patrol 12s=B 档而非 C"）——冻结件已不再按历史重件口径逐出日常门，
  B 层=日常门本就执行，误判方向=保守多跑；时长执法不靠层、靠 W1-7 棘轮
  （该两条预算 24.9s/14.6s，207s 级回涨必红）。逐条证据落 fixture
  frozen_retier.ruling_overrides。
* 只存 B+C 名单 + 生成参数（A=缺省不在名单即 A，28k 行全存浪费）；
  消费面 = tests/conftest.py（pytest_collection_modifyitems 施加
  tier_b/tier_c marker，纯元数据）+ scripts/gate_daily.py（-m 过滤调度）。
* 边界复核：4.5-5.5s 带内条目（争用上浮对 5s 边界的少量误判可接受口径，
  任务书）逐条落 fixture boundary_review 供人工复核。
* meta 注记：manifest 系 2026-10-27 争用轮（+10~40% 噪声），且落后于现树
  （W1-3/1-4/1-5/1-6/1-7/w2-* 已落盘，新增测试缺省落 A；W1-5/1-6 语料降
  规模使部分重件变快仍挂 C——方向保守，随下次终门 manifest 刷新再生即收敛）。

确定性：同输入两次运行输出逐字节一致——generated_at 取输入 mtime 最大值，
全部列表显式排序；--verify 自证面（collect-only 三层并集比对）落 JSON 证据。

用法（仓根）::
    .venv/Scripts/python.exe scripts/generate_tier_marks.py             # 再生名单
    .venv/Scripts/python.exe scripts/generate_tier_marks.py --verify    # 生成+并集自证
    # 测试消费：--manifest/--remeasure/--out 指向合成输入（test_tier_marks.py 钉）
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "aurora_m_test_tiers_v1"

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_DEFAULT = "runs/aurora_m/durations_manifest.yaml"
REMEASURE_DEFAULT = "runs/aurora_m/w1_7/remeasure_frozen.xml"
OUT_DEFAULT = "tests/fixtures/test_tiers.yaml"

C_THRESHOLD_S = 5.0
B_THRESHOLD_S = 1.0
BOUNDARY_BAND_S = (4.5, 5.5)

VERIFY_OUT_DEFAULT = "runs/aurora_m/w1_8/tier_union_check.json"

RULING_NOTE = (
    "任务书裁定（W1-8 席转记，2026-10-28）：W1-1/1-2 冻结件用现树重测时长重判层，"
    "重测后仍 >=C 阈值者保 B 档（'pool_patrol 12s=B 档而非 C'）——冻结件不再按"
    "历史重件口径逐出日常门；误判方向=保守多跑（B 层日常门本就执行）；时长回涨"
    "执法由 W1-7 时长棘轮兜底（remeasured 系数 x2.0），层只管调度不管执法"
)

META_NOTES = [
    "manifest 系 2026-10-27 争用轮（wall=89.2min，+10~40% 噪声），1s/5s 边界的"
    "少量误判可接受（任务书口径）；边界条目 4.5-5.5s 带逐条落 boundary_review",
    "manifest 落后于现树：其后落盘的 W1-3/1-4/1-5/1-6/1-7/w2-* 新测试不在名单"
    "=缺省 A（新增测试缺省进日常门，方向保守）；W1-5/1-6 语料降规模使部分重件"
    "变快仍挂 C（被逐出日常门，方向保守）——随下次终门 manifest 刷新再生即收敛",
    "marker 纯元数据：tier_b/tier_c 只供调度面（gate_daily -m 过滤）消费，任何门"
    "缺省行为零变化；终门永远全量（v2 口径），夜门口径不变",
    "duration_budgets.yaml 的 tier 字段是 manifest 生成源口径（冻结五条仍标 C），"
    "与本名单的现树重判口径（B/A）不同属预期——两文件消费面不同（棘轮执法 vs "
    "marker 调度），互不引用",
]


def _load_module(tag: str, script_name: str):
    """按文件路径装载 scripts/ 模块（scripts 非包，wf_gate_full_v2 同款）。"""
    path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(tag, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[tag] = mod
    spec.loader.exec_module(mod)
    return mod


def _tier_of(duration_s: float) -> str:
    """时长 → 层号（A=[0,1) / B=[1,5) / C=[5,∞)，与 manifest tier_rules 同口径）。"""
    if duration_s >= C_THRESHOLD_S:
        return "C"
    if duration_s >= B_THRESHOLD_S:
        return "B"
    return "A"


def _load_remeasure(
    remeasure_xml: Path, test_files: frozenset[str]
) -> dict[str, tuple[str, float]]:
    """重测 junitxml → {nodeid: (file, seconds)}（build_durations_manifest 同款解析）。"""
    bdm = _load_module("_gtm_bdm", "build_durations_manifest.py")
    root = ET.parse(remeasure_xml).getroot()
    out: dict[str, tuple[str, float]] = {}
    for tc in root.iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        file_path, cid = bdm._split_classname(classname, name, test_files)
        out[f"{file_path}::{cid}"] = (file_path, float(tc.get("time") or 0.0))
    return out


def _load_test_file_set() -> frozenset[str]:
    """tests/ 全部 .py 的 posix 相对路径集（单源委托 build_durations_manifest）。"""
    bdm = _load_module("_gtm_bdm", "build_durations_manifest.py")
    return bdm._load_test_file_set(REPO_ROOT / "tests")


def _fingerprint(path: Path) -> dict[str, Any]:
    """输入指纹（相对路径/sha256/mtime——确定性输出的一部分）。"""
    data = path.read_bytes()
    try:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = path.resolve().as_posix()
    mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
        timespec="seconds"
    )
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "mtime": mtime}


def build_tiers(
    manifest_path: Path, remeasure_path: Path
) -> dict[str, Any]:
    """主装配：manifest 直读 + 冻结件现树重判 → fixture dict（确定性）。"""
    cdr = _load_module("_gtm_cdr", "check_duration_ratchet.py")
    scanned = cdr.scan_manifest(manifest_path)
    entries = scanned["entries"]  # {nodeid: (file, duration_s, tier)}

    test_files = _load_test_file_set()
    remeasured = _load_remeasure(remeasure_path, test_files)
    frozen_files = sorted({file for file, _ in remeasured.values()})

    tier_b: list[str] = []
    tier_c: list[str] = []
    ruling_overrides: list[dict[str, Any]] = []
    coverage_gaps: list[str] = []
    boundary_review: list[dict[str, Any]] = []
    n_remeasured_applied = 0
    for nodeid in sorted(entries):
        file, duration_s, tier_manifest = entries[nodeid]
        tier = tier_manifest
        eff_s = duration_s
        if file in frozen_files:
            if nodeid in remeasured:
                eff_s = remeasured[nodeid][1]
                n_remeasured_applied += 1
                tier = _tier_of(eff_s)
                if tier == "C":
                    # 任务书裁定：冻结件重测后仍重者保 B（证据逐条落账）
                    ruling_overrides.append(
                        {
                            "nodeid": nodeid,
                            "manifest_s": duration_s,
                            "remeasured_s": eff_s,
                            "tier": "B",
                            "reason": RULING_NOTE,
                        }
                    )
                    tier = "B"
            else:
                # 重测 xml 未覆盖（冻结后该文件新增测试）——保 manifest 口径，
                # 缺口如实落账（下次终门 manifest 刷新再生即收敛）
                coverage_gaps.append(f"{nodeid} (manifest_s={duration_s})")
        if BOUNDARY_BAND_S[0] <= eff_s <= BOUNDARY_BAND_S[1]:
            boundary_review.append(
                {"nodeid": nodeid, "duration_s": round(eff_s, 3), "tier": tier}
            )
        if tier == "B":
            tier_b.append(nodeid)
        elif tier == "C":
            tier_c.append(nodeid)

    generated_at = max(
        datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        for p in (manifest_path, remeasure_path)
    ).isoformat(timespec="seconds")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generator": "scripts/generate_tier_marks.py",
        "params": {
            "c_threshold_s": C_THRESHOLD_S,
            "b_threshold_s": B_THRESHOLD_S,
            "boundary_review_band_s": list(BOUNDARY_BAND_S),
            "rule": "A=[0,1) 缺省不在名单 / B=[1,5) / C=[5,∞)；冻结件例外见 frozen_retier",
        },
        "sources": [
            {**_fingerprint(manifest_path), "role": "canonical durations (W0-1)"},
            {
                **_fingerprint(remeasure_path),
                "role": "W1-1/1-2 冻结件现树重测（W1-7 席）",
                "n_testcases": len(remeasured),
            },
        ],
        "frozen_retier": {
            "note": RULING_NOTE,
            "files": frozen_files,
            "remeasured_entries_applied": n_remeasured_applied,
            "coverage_gaps": coverage_gaps,
            "ruling_overrides": ruling_overrides,
        },
        "meta_notes": META_NOTES,
        "boundary_review": boundary_review,
        "tier_b": {"count": len(tier_b), "nodeids": tier_b},
        "tier_c": {"count": len(tier_c), "nodeids": tier_c},
    }


def _collect_nodeids(pytest_root: Path) -> tuple[set[str], str]:
    """collect-only 全量 nodeid 集（-q 一行一 id 形态）。"""
    cmd = [
        sys.executable, "-m", "pytest", "tests/unit", "-q", "--collect-only",
        "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(
        cmd, cwd=str(pytest_root), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    nodeids = {
        ln.strip()
        for ln in proc.stdout.splitlines()
        if ln.startswith("tests/") and "::" in ln
    }
    if proc.returncode != 0 and not nodeids:
        raise RuntimeError(f"collect-only 失败 rc={proc.returncode}: {proc.stderr[-400:]}")
    return nodeids, proc.stdout


def run_verify(out_path: Path, verify_out: Path) -> int:
    """三层并集自证：collect-only 全量 id 集 vs 名单（验收硬门槛证据）。"""
    fixture = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    tier_b = set(fixture["tier_b"]["nodeids"])
    tier_c = set(fixture["tier_c"]["nodeids"])
    collected, _raw = _collect_nodeids(REPO_ROOT)
    matched_b = tier_b & collected
    matched_c = tier_c & collected
    a_count = len(collected - tier_b - tier_c)
    stale_b = sorted(tier_b - collected)
    stale_c = sorted(tier_c - collected)
    union_ok = len(collected) == len(matched_b) + len(matched_c) + a_count
    report = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fixture": _fingerprint(out_path),
        "collected_total": len(collected),
        "tier_b_matched": len(matched_b),
        "tier_c_matched": len(matched_c),
        "tier_a_by_default": a_count,
        "union_identity": union_ok,
        "union_note": (
            "A=缺省不在名单 ∪ B 名单 ∪ C 名单 == 全量收集集（结构性恒等；"
            "硬门槛实为 B/C 名单对现树零缺失零陈旧）"
        ),
        "stale_tier_b": stale_b,
        "stale_tier_c": stale_c,
    }
    verify_out.parent.mkdir(parents=True, exist_ok=True)
    verify_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"VERIFY collected={len(collected)} B={len(matched_b)} C={len(matched_c)} "
        f"A={a_count} union_ok={union_ok} stale_B={len(stale_b)} stale_C={len(stale_c)}"
    )
    print(f"evidence -> {verify_out}")
    return 0 if (union_ok and not stale_b and not stale_c) else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="aurora_m W1-8 tier 分层名单生成器")
    ap.add_argument("--manifest", default=MANIFEST_DEFAULT)
    ap.add_argument("--remeasure", default=REMEASURE_DEFAULT)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument(
        "--verify", action="store_true",
        help="生成后跑一次 collect-only 做三层并集自证（~34s，勿与终门并行）",
    )
    ap.add_argument("--verify-out", default=VERIFY_OUT_DEFAULT)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest_path = Path(args.manifest)
    remeasure_path = Path(args.remeasure)
    for p in (manifest_path, remeasure_path):
        if not p.exists():
            raise SystemExit(f"输入不存在: {p}")
    tiers = build_tiers(manifest_path, remeasure_path)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        tiers, sort_keys=False, allow_unicode=True, width=4096,
        default_flow_style=False,
    )
    out_path.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"OK {out_path}: tier_b={tiers['tier_b']['count']} "
        f"tier_c={tiers['tier_c']['count']} "
        f"ruling_overrides={len(tiers['frozen_retier']['ruling_overrides'])} "
        f"boundary_review={len(tiers['boundary_review'])} "
        f"coverage_gaps={len(tiers['frozen_retier']['coverage_gaps'])}"
    )
    if args.verify:
        return run_verify(out_path, Path(args.verify_out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
