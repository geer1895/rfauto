#!/usr/bin/env python3
"""aurora_m W1-7 席：时长棘轮执法器（manifest 实测 vs committed 预算，只紧不松）。

职责与口径
----------
* 预算文件（tests/fixtures/duration_budgets.yaml，committed）由
  scripts/generate_duration_budget.py 从 durations manifest 显式再生，值只能
  紧不能松（新值>旧值需 --accept-slower+理由，见生成器 docstring）。
* 本模块是执法面：读 manifest（最新门实测）+ 预算（committed 上限）比对，
  违例逐条列出（test_id/实测/预算/超幅）。测试侧消费=tests/unit/
  test_duration_ratchet.py；CLI 供快速自查（--json 信封）。

预算覆盖面决策（数据化，实测 runs/aurora_m/durations_manifest.yaml）
------------------------------------------------------------------
* 逐条钉 ≥1s 条目（B+C 层 538 条）：A 层 28165 条合计仅 655.9s（均值 23ms，
  共 10.9min），逐条钉 28k 行预算文件的执法成本（文件体积/diff 噪声/亚秒级
  抖动误报）完全盖过信号——只钉 ≥1s。
* 全文件级合计预算（1144 文件各一条）兜底 A 层累积漂移：大量亚秒条目各自
  微涨不触发逐条线，但文件合计超 budget×1.5 且超出>1.0s 即红。
* 被否方案：全量 28703 条逐条钉（成本/信噪比失比，见上）；只钉 top-N
  （N 之外的增长无执法面）。

执法噪声余量（常量即口径，改动=代码改动=评审可见）
--------------------------------------------------
* NOISE_FACTOR=1.5（manifest 派生预算）：预算本身带争用轮 +10%~44% 上浮，
  ×1.5 即对干净轮 ≥1.65× 起红线；正常轮间抖动不误报。
* NOISE_FACTOR_REMEASURED=2.0（专用重测条目）：重测值是干净轮实测（无争用
  上浮），争用带 +44% 实测下 ×1.5 仅剩 4% 余量必误报，故此类放宽到 ×2.0
  （pool_patrol 预算 12.27s → >24.5s 才红，仍能拦住冻结化回涨 207s 级）。
* FILE_NOISE_FACTOR=1.5 + FILE_ABS_SLACK_S=1.0（文件层双条件）：大文件由
  系数主导、小文件由绝对余量主导（0.3s 新测试不红，连续累积越过 1s 即红）。
* 预算登记线 BUDGET_MIN_S=1.0：manifest 条目 ≥1s 无预算=违例（强制登记）；
  新文件合计 ≥FILE_UNREGISTERED_MIN_S=2.0=违例。<1s 亚阈条目的缓慢漂移在
  跨线前不受逐条执法（文件层兜底）——阈值化预算的固有软边界，如实声明。

运行态三态（红钱 3 钉面）
------------------------
* manifest 与预算双缺且证据区（manifest 父目录）不在 → skip（CI/公开仓/
  裁剪环境——证据在盘才执法的既有语义，非 skip 清单扩大）。
* 预算在而 manifest 缺：证据区在 → 红（执法面失明必须响亮）；证据区不在
  → skip（CI 语义）。
* manifest 在而预算缺 → 红（committed 预算被拆=执法面被拆除）。
* 双在 → sha 锚定双模式：
  - manifest sha256 == 预算记录的源 sha → self_audit 模式（manifest 即预算
    生成源，无新实测可执法；改验预算自身的只紧不松不变量：budget_s≤源值、
    覆盖完整、文件层一致、统计一致——防手改防漂移，正例绿由此而来）；
  - sha 不一致（新门产物）→ enforce 模式（逐条+文件层执法）。

manifest 快扫（性能红线：棘轮测试 <2s）
---------------------------------------
manifest 5.6MB/28703 条，yaml 全量解析实测 1.42s（超预算一半）——entries
块为单行 flow 映射，用行扫描正则直提（实测 0.036s）；显式键形态
（``? key`` / ``: {flow}``，nodeid 含 ": " 时 PyYAML 强制形态）与引号键
均处理；扫描条数必须==头部 summary.total_tests（任何静默丢行=完整性违例
响亮红，不静默降级）。

终门后刷新工作流（W1-8 接线用，两命令）
--------------------------------------
1) .venv/Scripts/python.exe scripts/build_durations_manifest.py \\
     --name <新门产物名> --agg-log runs/<新门>.log --out runs/aurora_m/durations_manifest.yaml
2) .venv/Scripts/python.exe scripts/generate_duration_budget.py
   （回涨被拦时按生成器提示 --accept-slower "理由"；冻结件重测加
   --remeasure-junit <新 junitxml>）
快速自查（可选第三步）：.venv/Scripts/python.exe scripts/check_duration_ratchet.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

EXPECTED_MANIFEST_SCHEMA = "aurora_m_durations_manifest_v2"
BUDGET_SCHEMA_VERSION = "aurora_m_duration_budget_v1"

# 执法噪声余量（依据见模块 docstring 执法噪声余量节；改动=代码改动=评审可见）
NOISE_FACTOR = 1.5
NOISE_FACTOR_REMEASURED = 2.0
FILE_NOISE_FACTOR = 1.5
FILE_ABS_SLACK_S = 1.0
BUDGET_MIN_S = 1.0
FILE_UNREGISTERED_MIN_S = 2.0
FILE_TOTAL_EPS = 0.05  # 文件合计比较容差（多位浮点求和的舍入漂移量级）

DEFAULT_MANIFEST = "runs/aurora_m/durations_manifest.yaml"
DEFAULT_BUDGET = "tests/fixtures/duration_budgets.yaml"

# entries 块行形态（build_durations_manifest 的 _Flow 紧凑映射输出）
RE_ENTRY_SIMPLE = re.compile(
    r'^  ("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^ ].*?): '
    r"\{file: (.+?), duration_s: ([0-9][0-9.eE+-]*), tier: ([ABC]), status: ([A-Za-z_]+)"
)
RE_ENTRY_EXPLICIT_KEY = re.compile(r"^  \? (.+)$")
RE_ENTRY_EXPLICIT_VALUE = re.compile(
    r"^  : \{file: (.+?), duration_s: ([0-9][0-9.eE+-]*), tier: ([ABC]), status: ([A-Za-z_]+)"
)


class RatchetError(Exception):
    """manifest/预算解析或完整性失败（执法面失明类，必须响亮）。"""


def _unquote_key(key: str) -> str:
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        body = key[1:-1]
        if key[0] == '"':
            body = body.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        else:
            body = body.replace("''", "'")
        return body
    return key


def scan_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """manifest 快扫 → 头部元数据 + {nodeid: (file, duration_s, tier)} + sha256。

    完整性 fail-loud：entries 行数 != 头部 total_tests、不可解析行、entries
    键缺失/重复 → RatchetError（不静默丢行）。
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise RatchetError(f"manifest 不存在: {manifest_path}")
    data = manifest_path.read_bytes()
    text = data.decode("utf-8")
    lines = text.splitlines()
    idx_entries = [i for i, ln in enumerate(lines) if ln == "entries:"]
    if len(idx_entries) != 1:
        raise RatchetError(
            f"manifest 顶层 entries: 键应恰出现 1 次，实测 {len(idx_entries)}（形态漂移？）"
        )
    header_text = "\n".join(lines[: idx_entries[0]])
    try:
        header = yaml.safe_load(header_text)
    except yaml.YAMLError as exc:
        raise RatchetError(f"manifest 头部解析失败: {exc}") from exc
    if not isinstance(header, dict):
        raise RatchetError("manifest 头部不是映射")
    schema_version = header.get("schema_version")
    if not schema_version:
        raise RatchetError("manifest 缺 schema_version")
    summary = header.get("summary") or {}
    total_tests = summary.get("total_tests")
    if not isinstance(total_tests, int):
        raise RatchetError("manifest 缺 summary.total_tests")

    entries: dict[str, tuple[str, float, str]] = {}
    pending_key: str | None = None
    for line in lines[idx_entries[0] + 1 :]:
        if not line.strip():
            continue
        m = RE_ENTRY_EXPLICIT_KEY.match(line)
        if m is not None:
            if pending_key is not None:
                raise RatchetError(f"显式键后缺值行: {pending_key}")
            pending_key = _unquote_key(m.group(1))
            continue
        m = RE_ENTRY_EXPLICIT_VALUE.match(line)
        if m is not None:
            if pending_key is None:
                raise RatchetError(f"显式值行缺键: {line[:120]}")
            entries[pending_key] = (
                m.group(1),
                float(m.group(2)),
                m.group(3),
            )
            pending_key = None
            continue
        m = RE_ENTRY_SIMPLE.match(line)
        if m is not None:
            entries[_unquote_key(m.group(1))] = (
                m.group(2),
                float(m.group(3)),
                m.group(4),
            )
            continue
        raise RatchetError(f"entries 块存在不可解析行（形态漂移？）: {line[:160]}")
    if pending_key is not None:
        raise RatchetError(f"显式键后缺值行（EOF）: {pending_key}")
    if len(entries) != total_tests:
        raise RatchetError(
            f"manifest 完整性违例: 扫描条数 {len(entries)} != 头部 total_tests {total_tests}"
            "（快扫正则丢行——执法面失明，禁止静默降级）"
        )
    source_run = header.get("source_run") or {}
    return {
        "path": manifest_path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "schema_version": schema_version,
        "generated_at": header.get("generated_at"),
        "source_run_name": source_run.get("name"),
        "wall_min": source_run.get("wall_min"),
        "contention_note": source_run.get("contention_note"),
        "total_tests": total_tests,
        "entries": entries,
    }


def load_budget(budget_path: str | Path) -> dict[str, Any]:
    """预算文件加载 + 最小结构校验（fail-loud）。

    CSafeLoader 优先（预算由本仓生成器确定性产出，纯数据映射；C 加载器把
    单次 check 的预算解析 0.285s→0.039s，服务棘轮 <2s 红线），缺失时回退
    纯 Python SafeLoader。
    """
    budget_path = Path(budget_path)
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        doc = yaml.load(budget_path.read_text(encoding="utf-8"), Loader=loader)
    except (OSError, yaml.YAMLError) as exc:
        raise RatchetError(f"预算文件读取/解析失败 {budget_path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise RatchetError(f"预算文件不是映射: {budget_path}")
    if doc.get("schema_version") != BUDGET_SCHEMA_VERSION:
        raise RatchetError(
            f"预算 schema 不识别: {doc.get('schema_version')!r}（期望 {BUDGET_SCHEMA_VERSION}）"
        )
    src = doc.get("source_manifest")
    if not isinstance(src, dict) or not src.get("sha256"):
        raise RatchetError("预算缺 source_manifest.sha256（来源指纹）")
    if not isinstance(doc.get("entries"), dict):
        raise RatchetError("预算缺 entries 映射")
    if not isinstance(doc.get("file_budgets"), dict):
        raise RatchetError("预算缺 file_budgets 映射")
    return doc


def _viol(
    kind: str,
    target: str,
    actual_s: float | None = None,
    budget_s: float | None = None,
    detail: str = "",
) -> dict[str, Any]:
    excess = None
    if actual_s is not None and budget_s is not None:
        excess = round(actual_s - budget_s, 3)
    return {
        "kind": kind,
        "target": target,
        "actual_s": actual_s,
        "budget_s": budget_s,
        "excess_s": excess,
        "detail": detail,
    }


def _result(
    status: str,
    mode: str | None,
    violations: list[dict[str, Any]],
    notes: list[str],
    manifest: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": mode,
        "violations": violations,
        "notes": notes,
        "manifest": manifest,
        "budget": budget,
    }


def _factor_of(entry: dict[str, Any]) -> tuple[float, str]:
    if entry.get("remeasured"):
        return NOISE_FACTOR_REMEASURED, f"×{NOISE_FACTOR_REMEASURED}(重测条目)"
    return NOISE_FACTOR, f"×{NOISE_FACTOR}"


def _self_audit(manifest: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    """sha 锚定自审：manifest 即预算生成源，验预算自身只紧不松不变量。"""
    violations: list[dict[str, Any]] = []
    entries: dict[str, tuple[str, float, str]] = manifest["entries"]
    b_entries: dict[str, Any] = budget["entries"]
    params = budget.get("generation_params") or {}
    budget_min = float(params.get("budget_min_s", BUDGET_MIN_S))

    for nid in sorted(b_entries):
        be = b_entries[nid]
        if nid not in entries:
            violations.append(
                _viol("integrity", nid, detail="预算条目不在源 manifest（手改或源错配）")
            )
            continue
        src_s = entries[nid][1]
        if float(be["budget_s"]) > src_s + 1e-9:
            violations.append(
                _viol(
                    "tighten_violation",
                    nid,
                    actual_s=float(be["budget_s"]),
                    budget_s=src_s,
                    detail="预算高于源实测——只紧不松被破坏",
                )
            )
    for nid, (_f, dur, _t) in entries.items():
        if dur >= budget_min and nid not in b_entries:
            violations.append(
                _viol("unbudgeted", nid, actual_s=dur, detail="源 manifest ≥1s 条目未登记预算")
            )

    file_totals: dict[str, float] = {}
    file_sub_ids: dict[str, list[str]] = {}
    for nid, (f, dur, _t) in entries.items():
        file_totals[f] = file_totals.get(f, 0.0) + dur
        if dur < budget_min:
            file_sub_ids.setdefault(f, []).append(nid)
    file_budgets: dict[str, Any] = budget["file_budgets"]
    for f in sorted(file_totals):
        fb = file_budgets.get(f)
        if fb is None:
            violations.append(_viol("file_budget_missing", f, detail="manifest 文件未登记文件预算"))
            continue
        if float(fb["budget_total_s"]) > file_totals[f] + FILE_TOTAL_EPS:
            violations.append(
                _viol(
                    "file_tighten_violation",
                    f,
                    actual_s=float(fb["budget_total_s"]),
                    budget_s=round(file_totals[f], 3),
                    detail="文件预算高于源合计——只紧不松被破坏",
                )
            )
        # 亚阈总体指纹对源 manifest 重算比对（防手改指纹掩护漂移）
        sub_ids = sorted(file_sub_ids.get(f, []))
        sub_sha = hashlib.sha256("\n".join(sub_ids).encode("utf-8")).hexdigest()
        sub_sum = round(sum(entries[nid][1] for nid in sub_ids), 3)
        if fb.get("sub_threshold_sha256") != sub_sha or (
            abs(float(fb.get("sub_threshold_sum_s", -1.0)) - sub_sum) > 1e-9
        ):
            violations.append(
                _viol(
                    "integrity",
                    f,
                    detail="亚阈指纹（sub_threshold_sha256/sum）与源 manifest 不一致"
                    "（手改掩护漂移或预算源错配）",
                )
            )
    stats = budget.get("stats") or {}
    if int(stats.get("entries_budgeted", -1)) != len(b_entries):
        violations.append(
            _viol(
                "integrity",
                "stats.entries_budgeted",
                detail=f"统计不一致: {stats.get('entries_budgeted')} != {len(b_entries)}",
            )
        )
    notes = [
        "self_audit 模式：manifest sha256 与预算源一致（manifest 尚未刷新，无新实测可执法）",
        f"预算条目 {len(b_entries)} / 文件预算 {len(file_budgets)} / manifest 条目 {len(entries)}",
    ]
    status = "violation" if violations else "ok"
    return _result(status, "self_audit", violations, notes, manifest, budget)


def _enforce(manifest: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    """sha 失配（新门产物）→ 逐条+文件层执法。"""
    violations: list[dict[str, Any]] = []
    src_schema = (budget.get("source_manifest") or {}).get("schema_version")
    if manifest["schema_version"] != src_schema:
        return _result(
            "violation",
            "enforce",
            [
                _viol(
                    "integrity",
                    "schema_version",
                    detail=(
                        f"manifest schema {manifest['schema_version']!r} != 预算源 schema "
                        f"{src_schema!r}——口径失配，先重生成预算（见生成器 docstring 工作流）"
                    ),
                )
            ],
            ["enforce 模式：manifest 与预算源口径失配"],
            manifest,
            budget,
        )
    entries: dict[str, tuple[str, float, str]] = manifest["entries"]
    b_entries: dict[str, Any] = budget["entries"]
    params = budget.get("generation_params") or {}
    budget_min = float(params.get("budget_min_s", BUDGET_MIN_S))
    file_unreg_min = float(params.get("file_unregistered_min_s", FILE_UNREGISTERED_MIN_S))
    file_noise = float(params.get("file_noise_factor", FILE_NOISE_FACTOR))
    file_slack = float(params.get("file_abs_slack_s", FILE_ABS_SLACK_S))

    for nid in sorted(entries):
        f, dur, _t = entries[nid]
        be = b_entries.get(nid)
        if be is None:
            if dur >= budget_min:
                violations.append(
                    _viol(
                        "unregistered",
                        nid,
                        actual_s=dur,
                        detail="新条目未登记预算（重生成预算文件登记；只紧不松届时生效）",
                    )
                )
            continue
        factor, factor_note = _factor_of(be)
        limit = float(be["budget_s"]) * factor
        if dur > limit:
            violations.append(
                _viol(
                    "exceeded",
                    nid,
                    actual_s=dur,
                    budget_s=float(be["budget_s"]),
                    detail=f"超预算（上限 {factor_note}={limit:.3f}s）",
                )
            )

    file_totals: dict[str, float] = {}
    file_counts: dict[str, int] = {}
    for _nid, (f, dur, _t) in entries.items():
        file_totals[f] = file_totals.get(f, 0.0) + dur
        file_counts[f] = file_counts.get(f, 0) + 1
    file_budgets: dict[str, Any] = budget["file_budgets"]
    for f in sorted(file_totals):
        total = file_totals[f]
        fb = file_budgets.get(f)
        if fb is None:
            if total >= file_unreg_min:
                violations.append(
                    _viol(
                        "file_unregistered",
                        f,
                        actual_s=round(total, 3),
                        detail=f"新文件合计 {total:.3f}s ≥ {file_unreg_min}s 未登记（{file_counts[f]} 条）",
                    )
                )
            continue
        fb_total = float(fb["budget_total_s"])
        limit = fb_total * file_noise
        if total > limit and total - fb_total > file_slack:
            violations.append(
                _viol(
                    "file_exceeded",
                    f,
                    actual_s=round(total, 3),
                    budget_s=fb_total,
                    detail=f"文件合计超预算（上限 ×{file_noise}={limit:.3f}s 且超出>{file_slack}s）",
                )
            )
    notes = [
        "enforce 模式：manifest 已刷新（sha 与预算源不一致）——对新实测执法",
        f"manifest 条目 {len(entries)} / 预算条目 {len(b_entries)} / 文件预算 {len(file_budgets)}",
    ]
    status = "violation" if violations else "ok"
    return _result(status, "enforce", violations, notes, manifest, budget)


def check(
    manifest_path: str | Path = DEFAULT_MANIFEST, budget_path: str | Path = DEFAULT_BUDGET
) -> dict[str, Any]:
    """三态入口：skip（证据不在盘）/ ok（自审或执法零违例）/ violation（含清单）。"""
    manifest_path = Path(manifest_path)
    budget_path = Path(budget_path)
    budget_exists = budget_path.exists()
    manifest_exists = manifest_path.exists()
    if not budget_exists:
        # 预算是 committed 执法面：其缺席默认红；双缺且证据区不在才是裁剪环境
        if not manifest_exists and not manifest_path.parent.exists():
            return _result(
                "skip",
                None,
                [],
                [
                    f"manifest 与预算双缺且证据区 {manifest_path.parent} 不在"
                    "（CI/公开仓/裁剪环境）——证据在盘才执法，skip"
                ],
            )
        return _result(
            "violation",
            None,
            [
                _viol(
                    "budget_missing",
                    budget_path.as_posix(),
                    detail="预算文件缺席——执法面被拆除（committed 资产不得缺席；"
                    "重生成见 scripts/generate_duration_budget.py docstring 工作流）",
                )
            ],
            ["预算文件缺席（manifest 在盘）"],
        )
    if not manifest_exists:
        if not manifest_path.parent.exists():
            return _result(
                "skip",
                None,
                [],
                [
                    f"manifest 不在盘且证据区 {manifest_path.parent} 不在"
                    "（CI/公开仓/裁剪环境）——证据在盘才执法，skip"
                ],
            )
        return _result(
            "violation",
            None,
            [
                _viol(
                    "manifest_missing",
                    manifest_path.as_posix(),
                    detail="证据区在而 manifest 缺——执法面失明（重生成 manifest 见"
                    " scripts/build_durations_manifest.py，或本环境确实无门产物则属裁剪环境误判）",
                )
            ],
            ["manifest 缺席（证据区在盘）"],
        )
    try:
        manifest = scan_manifest(manifest_path)
        budget = load_budget(budget_path)
    except RatchetError as exc:
        return _result(
            "violation",
            None,
            [_viol("integrity", str(manifest_path), detail=str(exc))],
            ["解析/完整性失败——执法面失明必须响亮"],
        )
    if manifest["sha256"] == budget["source_manifest"].get("sha256"):
        return _self_audit(manifest, budget)
    return _enforce(manifest, budget)


def render_result(res: dict[str, Any], max_list: int = 50) -> str:
    """结果 → 人读多行（pytest 断言消息/CLI 输出共用）。"""
    lines = [f"[duration_ratchet] status={res['status']} mode={res['mode']}"]
    lines.extend(f"  note: {n}" for n in res["notes"])
    for v in res["violations"][:max_list]:
        if v["actual_s"] is not None and v["budget_s"] is not None:
            pct = ""
            if v["budget_s"] > 0:
                pct = f" (+{v['excess_s'] / v['budget_s'] * 100:.1f}%)"
            lines.append(
                f"  [{v['kind']}] {v['target']}"
                f"  实测={v['actual_s']:.3f}s 预算={v['budget_s']:.3f}s"
                f" 超幅=+{v['excess_s']:.3f}s{pct}"
            )
        elif v["actual_s"] is not None:
            lines.append(f"  [{v['kind']}] {v['target']}  实测={v['actual_s']:.3f}s")
        else:
            lines.append(f"  [{v['kind']}] {v['target']}")
        if v["detail"]:
            lines.append(f"      {v['detail']}")
    if len(res["violations"]) > max_list:
        lines.append(f"  ... 其余 {len(res['violations']) - max_list} 条略")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="时长棘轮执法自查（manifest 实测 vs committed 预算）")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST, help="durations manifest 路径")
    ap.add_argument("--budget", default=DEFAULT_BUDGET, help="预算文件路径")
    ap.add_argument("--json", action="store_true", help="JSON 信封输出")
    args = ap.parse_args(argv)
    res = check(args.manifest, args.budget)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": res["status"] != "violation",
                    "status": res["status"],
                    "mode": res["mode"],
                    "n_violations": len(res["violations"]),
                    "violations": res["violations"],
                    "notes": res["notes"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_result(res))
    return 1 if res["status"] == "violation" else 0


if __name__ == "__main__":
    sys.exit(main())
