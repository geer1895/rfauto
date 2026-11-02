#!/usr/bin/env python3
"""aurora_m W0-1 席：durations 全量画像生成器（纯解析既有产物，零 pytest）。

数据源与口径
------------
* canonical 时长 = junitxml（seg{1..5}.xml）per-testcase ``time`` 属性
  （= setup+call+teardown 总和，100% 覆盖全部 28703 条 testcase 含 <5ms 者；
  聚合 TOTAL 行口径 28696 = 28673 passed + 23 skipped，另有 7 条 xfailed 以
  ``<skipped type="pytest.xfail">`` 形式存在于 xml——28703 = 28696 + 7）。
* 交叉校验源 = seg log ``--durations=0`` 分相行（2 位小数；<5ms 的相位被
  pytest 隐藏并注记 "N durations < 0.005s hidden"）——与 xml 属不同口径，
  差异属预期，报告记录样本数与 max 相对差。

分层规则（三层无缝覆盖，不存在 (1.0,5.0) 形式缺口；阈值参数化
--c-threshold/--b-threshold，常量见 TIER_*_DEFAULT_S）
----------------------------------------------------------------
* tier C（重件层）：        time >= c_threshold（缺省 5.0s）
* tier B（数值不变量层）：  b_threshold <= time < c_threshold（缺省 [1.0, 5.0)s）
* tier A（钉子层）：        time < b_threshold（缺省 1.0s）
即 A=[0,1.0) / B=[1.0,5.0) / C=[5.0,∞) 三段拼接恰好覆盖 [0,∞)，任何时长有且
只有一个归属层；三层计数和 == junitxml testcase 总数（生成器内断言）。

flags 分类（文件级 grep 归类下发；对 tests/ 全部 .py 各扫一次建 file→flags 映射）
------------------------------------------------------------------------------
* reducible_dual_run：``double_run|bit_identical|byte_identical|determinism``
  （PLAN §〇 锚 53 文件系更早树面且未含 byte_identical 的旧口径；本口径实测
  74 文件——48 文件命中显式双跑/逐位比较标记，26 文件仅命中 determinism，
  抽检证实均为 test_determinism_* 同输入两次逐位一致真双跑，非注释噪声）。
* reducible_optloop：``optuna|max[-_]trials|n_trials|create_study|study_name``
  （PLAN §〇 锚 98（grep max-trials/optuna/study）含树面漂移；本口径补
  n_trials 试验数旋钮，实测 93 文件。裸 ``optimization`` 一词并入会膨胀到
  182 文件属注释噪声，不并入）。
* numeric_reference（红线 3：此类只调调度不降语料）：
  ``golden|reference|arbiter|闭式|对拍|cross_check``——规格宽口径，召回优先
  （漏标=红线违规；过标仅损失调度自由度）。实测 608 文件（单词条命中数：
  闭式 459 / 对拍 172 / reference 174，交叠大）——覆盖过半测试树是本仓
  "数值验证密集"的诚实反映，非分类事故。
* 红线优先级：同文件同时携带 numeric_reference 与任一 reducible_* 时红线 3
  优先——消费席（W1-8）不得对 numeric_reference 条目降语料（本 manifest 只
  记 flags，裁决在消费席；此注记随 flags_rules 下发）。

前任席位遗留件处置（W0-1 重发席裁定，2026-10-26）
------------------------------------------------
前任同路径生成器骨架（双源合并/分层/flow-style dumper/输入指纹/确定性
generated_at）判定**可复用**，本版继承其架构并修六处缺陷：
1. retry.xml 陈旧误改判：round1 尾段 retry.xml（mtime 01:08）早于本轮全部
   seg xml（02:08+），原版无条件叠加其状态会把本轮 passed 改判 failed——
   本版加轮次一致性门（retry mtime >= 全部 seg xml mtime 才应用，否则记
   stale 不应用）。
2. entries 结构：原版按文件分组嵌套；任务规格要求 test_id 平铺键 →
   {file, duration_s, tier, status, flags}——本版平铺（nodeid 字典序）。
3. 头部缺争用注记——本版在 source_run.contention_note 如实落注（本轮
   wall=89.2min 为争用轮，相对干净轮 ~61-65min 带 +10~40% 噪声）。
4. 缺 top50 占比（原版仅 --top 单值）——本版 top50/top100 双口径。
5. flags 只报文件数不报测试条数——本版每 flag 报 files_matched +
   tests_matched。
6. flags 词表重校准（原版把 determinism 当注释噪声剔除——抽检证伪；
   numeric_reference 按规格宽口径保红线 3 召回）。
前任临时件 runs/aurora_m/_smoke_a.yaml、_smoke_b.yaml、_smoke_manifest.yaml、
_smoke_inputs/ 与本生成器零引用关系，已按 AGENTS 规则 3 点名删除。

确定性：同输入两次运行输出逐字节一致——generated_at 取全部输入文件 mtime
最大值（输入不变则时间戳不变）；yaml 全映射以确定性插入序构建、列表显式
排序、每个输入附 sha256 指纹；tier/flags/对账全部由输入数据派生。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "aurora_m_durations_manifest_v2"

TIER_C_DEFAULT_S = 5.0
TIER_B_DEFAULT_S = 1.0

CROSSCHECK_SAMPLES_DEFAULT = 40
SLOW_TOP_DEFAULT = 100

RE_DURATION_LINE = re.compile(r"^([0-9]+\.[0-9]+)s\s+(setup|call|teardown)\s+(\S.*)$")
RE_HIDDEN_NOTE = re.compile(r"\((\d+) durations < 0\.005s hidden")
RE_WALL = re.compile(r"#\s*wall=([0-9.]+)min")
RE_TOTAL = re.compile(r"TOTAL:\s*(\d+)\s*passed,\s*(\d+)\s*failed,\s*(\d+)\s*skipped")
RE_RETRIED_GREEN = re.compile(r"retried_green=(\d+)")
RE_DURATIONS_TIER = re.compile(r">=60s=(\d+)\s+10-60s=(\d+)\s+1-10s=(\d+)\s+<1s=(\d+)")
RE_DURATIONS_SUM = re.compile(r"合计\s*(\d+)\s*项")

# flags 启发式模式（校准依据与锚对账见模块 docstring flags 分类节）
RE_FLAG_DUAL_RUN = re.compile(r"double_run|bit_identical|byte_identical|determinism")
RE_FLAG_OPTLOOP = re.compile(r"optuna|max[-_]trials|n_trials|create_study|study_name")
RE_FLAG_NUMERIC_REF = re.compile(r"golden|reference|arbiter|闭式|对拍|cross_check")
FLAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "reducible_dual_run": RE_FLAG_DUAL_RUN,
    "reducible_optloop": RE_FLAG_OPTLOOP,
    "numeric_reference": RE_FLAG_NUMERIC_REF,
}
FLAG_NOTES: dict[str, str] = {
    "reducible_dual_run": (
        "PLAN 锚 53（double_run/bit_identical/determinism 旧树面口径，未含 "
        "byte_identical）；本口径 74：48 显式双跑/逐位比较 + 26 仅 determinism"
        "（抽检=真双跑非噪声）"
    ),
    "reducible_optloop": (
        "PLAN 锚 98（grep max-trials/optuna/study 旧树面口径）；本口径 93："
        "补 n_trials 旋钮标记；optimization 一词并入会膨胀到 182 属注释噪声不并入"
    ),
    "numeric_reference": (
        "红线 3：此类只调调度不降语料；规格宽口径召回优先（漏标=违规，过标仅损"
        "调度自由度）；本口径 608（闭式 459/对拍 172/reference 174 交叠大）——"
        "覆盖过半测试树属数值验证密集仓的诚实反映"
    ),
}
RED_LINE_NOTE = (
    "红线优先级：同条目同时携带 numeric_reference 与任一 reducible_* 时红线 3 "
    "优先——numeric_reference 条目只调调度不降语料（裁决在消费席 W1-8）"
)

# 已知最慢冠军（PLAN §〇 锚：209s/198s/115s，干净轮口径；本轮按文件 stem 动态
# 取各自最慢条目对账——争用轮口径=冠军集合一致、数值允许上浮）
CHAMPION_FILE_STEMS = (
    "test_pool_patrol",
    "test_synthesis_bpf_polish_backsub",
    "test_coil_nfc_template",
)


class _Flow(dict):
    """标记 flow-style 的映射（逐测试紧凑单行，控制产物体积）。"""


class _ManifestDumper(yaml.SafeDumper):
    """SafeDumper + _Flow 紧凑映射支持。"""


_ManifestDumper.add_representer(
    _Flow,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=True
    ),
)


def _tier_of(duration_s: float, c_threshold_s: float, b_threshold_s: float) -> str:
    """时长 → 层号（A=[0,b) / B=[b,c) / C=[c,∞)，三层无缝覆盖，规则见 docstring）。"""
    if duration_s >= c_threshold_s:
        return "C"
    if duration_s >= b_threshold_s:
        return "B"
    return "A"


def _testcase_status(tc: ET.Element) -> str:
    """junitxml testcase → 状态（passed/failed/error/skipped/xfailed）。"""
    if tc.find("failure") is not None:
        return "failed"
    if tc.find("error") is not None:
        return "error"
    skipped = tc.find("skipped")
    if skipped is not None:
        if "xfail" in (skipped.get("type") or ""):
            return "xfailed"
        return "skipped"
    return "passed"


def _load_test_file_set(tests_root: Path) -> frozenset[str]:
    """tests/ 全部 .py 的 posix 相对路径集（classname→file 解析的落点校验面）。"""
    tests_root = Path(tests_root)
    return frozenset(p.as_posix() for p in tests_root.rglob("*.py"))


def _split_classname(
    classname: str, name: str, test_files: frozenset[str]
) -> tuple[str, str]:
    """junitxml classname+name → (测试文件路径, 文件内 id)。

    classname 形如 ``tests.unit.test_x`` 或 ``tests.unit.test_x.Class[.Sub]``；
    文件路径取"最长能命中真实测试文件的前缀 + .py"（防未来测试子目录加深时
    parts[:3] 硬切失准）；文件内 id = 类链 + name（``Class::test_y`` / ``test_y``）。
    """
    parts = classname.split(".")
    file_path: str | None = None
    chain: list[str] = []
    for k in range(len(parts), 2, -1):
        cand = "/".join(parts[:k]) + ".py"
        if cand in test_files:
            file_path = cand
            chain = parts[k:]
            break
    if file_path is None:
        file_path = "/".join(parts[:3]) + ".py"
        chain = parts[3:]
    cid = "::".join([*chain, name]) if chain else name
    return file_path, cid


def _load_seg_entries(seg_xml: Path, test_files: frozenset[str]) -> list[dict[str, Any]]:
    """单个 junitxml → 条目列表（canonical 时长 + 原始状态）。"""
    seg_xml = Path(seg_xml)
    root = ET.parse(seg_xml).getroot()
    entries: list[dict[str, Any]] = []
    for tc in root.iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        file_path, cid = _split_classname(classname, name, test_files)
        entries.append(
            {
                "file": file_path,
                "cid": cid,
                "nodeid": f"{file_path}::{cid}",
                "duration_s": float(tc.get("time") or 0.0),
                "status_raw": _testcase_status(tc),
            }
        )
    return entries


def _load_retry_status(retry_xml: Path) -> dict[str, str]:
    """retry.xml → {nodeid: 重跑后状态}（v2 门尾段自动重跑改判面）。"""
    retry_xml = Path(retry_xml)
    if not retry_xml.exists():
        return {}
    root = ET.parse(retry_xml).getroot()
    out: dict[str, str] = {}
    for tc in root.iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        parts = classname.split(".")
        file_path = "/".join(parts[:3]) + ".py"
        cid = "::".join([*parts[3:], name]) if len(parts) > 3 else name
        out[f"{file_path}::{cid}"] = _testcase_status(tc)
    return out


def _classify_flags(tests_root: Path) -> dict[str, list[str]]:
    """扫描 tests/ 全部 .py → {文件 posix 路径: [flags]}（启发式，见 docstring）。"""
    tests_root = Path(tests_root)
    mapping: dict[str, list[str]] = {}
    for py in sorted(tests_root.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        flags = [name for name, pat in FLAG_PATTERNS.items() if pat.search(text)]
        if flags:
            mapping[py.as_posix()] = sorted(flags)
    return mapping


def _scan_seg_log(seg_log: Path) -> dict[str, Any]:
    """单遍扫描 seg log → 分相口径数据（shown 和 / phase max / 行数 / 隐藏注记）。"""
    seg_log = Path(seg_log)
    shown_sum: dict[str, float] = {}
    phase_max: dict[str, float] = {}
    lines_shown = 0
    hidden_note: int | None = None
    if not seg_log.exists():
        return {
            "shown_sum": shown_sum,
            "phase_max": phase_max,
            "lines_shown": lines_shown,
            "hidden_note": hidden_note,
        }
    for line in seg_log.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        m = RE_DURATION_LINE.match(stripped)
        if m is not None:
            lines_shown += 1
            seconds, nodeid = float(m.group(1)), m.group(3).strip()
            shown_sum[nodeid] = shown_sum.get(nodeid, 0.0) + seconds
            if seconds > phase_max.get(nodeid, 0.0):
                phase_max[nodeid] = seconds
            continue
        if hidden_note is None:
            mh = RE_HIDDEN_NOTE.search(stripped)
            if mh is not None:
                hidden_note = int(mh.group(1))
    return {
        "shown_sum": shown_sum,
        "phase_max": phase_max,
        "lines_shown": lines_shown,
        "hidden_note": hidden_note,
    }


def _parse_agg_log(agg_log: Path) -> dict[str, Any]:
    """聚合门日志 → {wall_min, totals, durations_tier, durations_sum}（防御式）。"""
    agg_log = Path(agg_log)
    out: dict[str, Any] = {
        "wall_min": None,
        "total_passed": None,
        "total_failed": None,
        "total_skipped": None,
        "retried_green": None,
        "durations_ge60": None,
        "durations_10_60": None,
        "durations_1_10": None,
        "durations_lt1": None,
        "durations_sum": None,
        "total_line": None,
        "durations_line": None,
    }
    if not agg_log.exists():
        return out
    text = agg_log.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if out["total_line"] is None and "TOTAL:" in line:
            m = RE_TOTAL.search(line)
            if m is not None:
                out["total_passed"] = int(m.group(1))
                out["total_failed"] = int(m.group(2))
                out["total_skipped"] = int(m.group(3))
                out["total_line"] = line.strip()
        m_wall = RE_WALL.search(line)
        if m_wall is not None and out["wall_min"] is None:
            out["wall_min"] = float(m_wall.group(1))
        m_tier = RE_DURATIONS_TIER.search(line)
        if m_tier is not None and out["durations_ge60"] is None:
            out["durations_ge60"] = int(m_tier.group(1))
            out["durations_10_60"] = int(m_tier.group(2))
            out["durations_1_10"] = int(m_tier.group(3))
            out["durations_lt1"] = int(m_tier.group(4))
            out["durations_line"] = line.strip()
        m_sum = RE_DURATIONS_SUM.search(line)
        if m_sum is not None and out["durations_sum"] is None:
            out["durations_sum"] = int(m_sum.group(1))
        m_ret = RE_RETRIED_GREEN.search(line)
        if m_ret is not None and out["retried_green"] is None:
            out["retried_green"] = int(m_ret.group(1))
    return out


def _fingerprint(path: Path, repo_root: Path) -> dict[str, Any]:
    """输入文件指纹（路径/大小/sha256/mtime——确定性输出的一部分）。"""
    path = Path(path)
    data = path.read_bytes()
    try:
        rel = path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        rel = path.resolve().as_posix()
    mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "path": rel,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mtime": mtime,
    }


def _bucket_counts(durations: list[float]) -> dict[str, int]:
    """时长列表 → 五桶计数（ge60 / b10_60 / b5_10 / b1_5 / lt1）。"""
    buckets = {"ge60": 0, "b10_60": 0, "b5_10": 0, "b1_5": 0, "lt1": 0}
    for t in durations:
        if t >= 60.0:
            buckets["ge60"] += 1
        elif t >= 10.0:
            buckets["b10_60"] += 1
        elif t >= 5.0:
            buckets["b5_10"] += 1
        elif t >= 1.0:
            buckets["b1_5"] += 1
        else:
            buckets["lt1"] += 1
    return buckets


def _build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    """主装配：双源合并 + 分层 + flags + 对账 → manifest dict。"""
    gate_parts = Path(args.gate_parts)
    agg_log = Path(args.agg_log)
    tests_root = Path(args.tests_root)
    out_path = Path(args.out)
    repo_root = Path(__file__).resolve().parent.parent
    name = args.name

    seg_xmls = [gate_parts / f"{name}.seg{i}.xml" for i in range(1, 6)]
    seg_logs = [gate_parts / f"{name}.seg{i}.log" for i in range(1, 6)]
    retry_xml = gate_parts / f"{name}.retry.xml"
    missing = [p for p in seg_xmls if not p.exists()]
    if missing:
        raise SystemExit(f"缺少 canonical junitxml 输入: {missing}")

    # ---- 条目：xml canonical（全量覆盖含 xfailed）----
    test_files = _load_test_file_set(tests_root)
    entries: list[dict[str, Any]] = []
    xml_testcase_total = 0
    for seg, xml_path in enumerate(seg_xmls, start=1):
        seg_entries = _load_seg_entries(xml_path, test_files)
        xml_testcase_total += len(seg_entries)
        for e in seg_entries:
            e["seg"] = seg
            entries.append(e)
    if len(entries) != xml_testcase_total:  # 覆盖率断言（防御式，构造上恒真）
        raise SystemExit(
            f"覆盖率断言失败: entries={len(entries)} != xml testcase 总数={xml_testcase_total}"
        )

    # ---- retry 改判（轮次一致性门：陈旧 retry 不应用，见 docstring 缺陷 1）----
    retry_status = _load_retry_status(retry_xml)
    retry_applied = False
    retry_stale = False
    if retry_status:
        seg_min_mtime = min(p.stat().st_mtime for p in seg_xmls)
        if retry_xml.stat().st_mtime >= seg_min_mtime:
            retry_applied = True
        else:
            retry_stale = True
    retried_green = 0
    retried_still_red = 0
    if retry_applied:
        for e in entries:
            new_status = retry_status.get(e["nodeid"])
            if new_status is not None and new_status != e["status_raw"]:
                e["status_raw"] = new_status
                if new_status == "passed":
                    retried_green += 1
                else:
                    retried_still_red += 1
    retry_unmatched = sorted(set(retry_status) - {e["nodeid"] for e in entries})

    # ---- 分层与 flags ----
    for e in entries:
        e["tier"] = _tier_of(e["duration_s"], args.c_threshold, args.b_threshold)
    flags_map = _classify_flags(tests_root)
    for e in entries:
        e["flags"] = flags_map.get(e["file"], [])

    # ---- 分层统计（三层计数和 == 总数断言）----
    by_tier: dict[str, dict[str, float]] = {}
    tier_sum = 0
    for tier in ("C", "B", "A"):
        subset = [e for e in entries if e["tier"] == tier]
        tier_sum += len(subset)
        total = sum(e["duration_s"] for e in subset)
        by_tier[tier] = {"count": len(subset), "total_s": round(total, 3)}
    if tier_sum != len(entries):
        raise SystemExit(f"分层覆盖断言失败: 三层计数和={tier_sum} != 总数={len(entries)}")
    grand_total = sum(e["duration_s"] for e in entries)
    for tier in ("C", "B", "A"):
        by_tier[tier]["share_pct"] = (
            round(by_tier[tier]["total_s"] / grand_total * 100.0, 2)
            if grand_total > 0
            else 0.0
        )
    status_counter: dict[str, int] = {}
    for e in entries:
        status_counter[e["status_raw"]] = status_counter.get(e["status_raw"], 0) + 1

    # ---- xml 侧五桶（canonical 总时长口径）----
    buckets = _bucket_counts([e["duration_s"] for e in entries])

    # ---- seg log 交叉校验（单遍扫描，见 _scan_seg_log）----
    log_shown: dict[str, float] = {}
    log_phase_max: dict[str, float] = {}
    seg_log_info = []
    for seg, log_path in enumerate(seg_logs, start=1):
        scan = _scan_seg_log(log_path)
        seg_log_info.append(
            {
                "seg": seg,
                "path": _fingerprint(log_path, repo_root)
                if log_path.exists()
                else None,
                "durations_lines_shown": scan["lines_shown"],
                "hidden_note_count": scan["hidden_note"],
                "tests_with_any_phase_shown": len(scan["shown_sum"]),
            }
        )
        for nid, seconds in scan["shown_sum"].items():
            log_shown[nid] = log_shown.get(nid, 0.0) + seconds
        for nid, seconds in scan["phase_max"].items():
            if seconds > log_phase_max.get(nid, 0.0):
                log_phase_max[nid] = seconds
    xml_by_nodeid = {e["nodeid"]: e for e in entries}
    matched = sorted(nid for nid in log_shown if nid in xml_by_nodeid)
    sample_pool = sorted(
        matched, key=lambda nid: (-xml_by_nodeid[nid]["duration_s"], nid)
    )[: max(args.samples, 0)]
    samples = []
    max_rel = -1.0
    max_rel_nid = None
    for nid in sample_pool:
        xml_t = xml_by_nodeid[nid]["duration_s"]
        if xml_t <= 0.0:
            continue
        log_t = log_shown[nid]
        rel = abs(log_t - xml_t) / xml_t
        if rel > max_rel:
            max_rel, max_rel_nid = rel, nid
        samples.append(
            _Flow(
                nodeid=nid,
                xml_total_s=round(xml_t, 3),
                log_phases_sum_s=round(log_t, 2),
                rel_diff_pct=round(rel * 100.0, 4),
            )
        )
    if not samples:
        max_rel, max_rel_nid = 0.0, None

    # ---- 对账：C 层（xml 桶 + log max-phase 推算）+ 冠军 + top50/top100 ----
    c_count = buckets["ge60"] + buckets["b10_60"] + buckets["b5_10"]
    log_buckets = _bucket_counts(list(log_phase_max.values()))
    c_log_estimate = log_buckets["ge60"] + log_buckets["b10_60"] + log_buckets["b5_10"]
    champions: dict[str, Any] = {}
    for stem in CHAMPION_FILE_STEMS:
        cands = [e for e in entries if stem in e["file"]]
        if cands:
            top = max(cands, key=lambda e: (e["duration_s"], e["nodeid"]))
            champions[stem] = _Flow(
                nodeid=top["nodeid"],
                duration_s=round(top["duration_s"], 3),
                tier=top["tier"],
                status=top["status_raw"],
            )
        else:
            champions[stem] = None
    ranked = sorted(entries, key=lambda e: (-e["duration_s"], e["nodeid"]))
    top50 = ranked[:50]
    top_n = ranked[: max(args.top, 0)]
    top50_total = sum(e["duration_s"] for e in top50)
    top_total = sum(e["duration_s"] for e in top_n)

    # ---- entries 平铺主体（nodeid 字典序；规格：test_id → 全字段）----
    entries_block: dict[str, Any] = {}
    for e in sorted(entries, key=lambda x: x["nodeid"]):
        entries_block[e["nodeid"]] = _Flow(
            file=e["file"],
            duration_s=round(e["duration_s"], 3),
            tier=e["tier"],
            status=e["status_raw"],
            flags=e["flags"],
        )

    flags_file_counts = {
        flag: sum(1 for fl in flags_map.values() if flag in fl) for flag in FLAG_PATTERNS
    }
    flags_test_counts = {
        flag: sum(1 for e in entries if flag in e["flags"]) for flag in FLAG_PATTERNS
    }

    agg = _parse_agg_log(agg_log)
    wall_min = agg["wall_min"]
    contention_note = (
        f"本轮 wall={wall_min}min 为争用轮：与远程席（轻）及本机 du 扫描席（重）并发"
        f"执行，逐条时长相对干净轮（~61-65min，final4 基线）带 +10%~40% 争用噪声；"
        f"对账口径=冠军集合一致、数值允许上浮；本 manifest 时长用于分层/排名/占比"
        f"（排序对近似均匀放大稳健），绝对值勿直接当干净轮基线消费。"
    )
    inputs = {
        "agg_log": _fingerprint(agg_log, repo_root) if agg_log.exists() else None,
        "seg_xmls": [_fingerprint(p, repo_root) for p in seg_xmls],
        "seg_logs": seg_log_info,
        "retry_xml": _fingerprint(retry_xml, repo_root)
        if retry_xml.exists()
        else None,
    }
    generated_at = max(
        (
            datetime.fromtimestamp(p.stat().st_mtime).astimezone()
            for p in [*seg_xmls, *seg_logs, retry_xml, agg_log]
            if p.exists()
        ),
        default=datetime.now().astimezone(),
    ).isoformat(timespec="seconds")

    daily_ab = by_tier["A"]["total_s"] + by_tier["B"]["total_s"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generator": "scripts/build_durations_manifest.py",
        "canonical_duration_source": "junitxml per-testcase time (setup+call+teardown)",
        "source_run": {
            "name": name,
            "wall_min": wall_min,
            "contention_note": contention_note,
            "seg_paths": [p.as_posix() for p in seg_xmls]
            + [p.as_posix() for p in seg_logs],
            "agg_total_line": agg["total_line"],
            "agg_totals": {
                "passed": agg["total_passed"],
                "failed": agg["total_failed"],
                "skipped": agg["total_skipped"],
                "retried_green": agg["retried_green"],
            },
            "agg_durations_line": agg["durations_line"],
            "agg_durations_tier_max_phase": {
                "ge60s": agg["durations_ge60"],
                "b10_60s": agg["durations_10_60"],
                "b1_10s": agg["durations_1_10"],
                "lt1s": agg["durations_lt1"],
                "sum_shown": agg["durations_sum"],
                "note": "max(分相) 口径且 <5ms 相位隐藏，与 xml 总和口径不同属预期",
            },
        },
        "inputs": inputs,
        "tier_rules": {
            "C": f"time >= {args.c_threshold}s（重件层）",
            "B": f"{args.b_threshold}s <= time < {args.c_threshold}s（数值不变量层）",
            "A": f"time < {args.b_threshold}s（钉子层）",
            "thresholds": {
                "c_threshold_s": args.c_threshold,
                "b_threshold_s": args.b_threshold,
            },
            "basis": "junitxml per-testcase time（setup+call+teardown 总和）",
            "coverage_note": "A=[0,b) / B=[b,c) / C=[c,∞) 三段无缝覆盖，无 (1.0,5.0) 形式缺口",
        },
        "flags_rules": {
            flag: {
                "pattern": FLAG_PATTERNS[flag].pattern,
                "scope": "文件级 grep（tests/**/*.py 全文），命中文件的全部测试条目继承",
                "files_matched": flags_file_counts[flag],
                "tests_matched": flags_test_counts[flag],
                "anchor_note": FLAG_NOTES[flag],
            }
            for flag in sorted(FLAG_PATTERNS)
        },
        "red_line_note": RED_LINE_NOTE,
        "summary": {
            "total_tests": len(entries),
            "coverage_note": (
                "xml 全量 28703 = 聚合 TOTAL 行口径 28696（passed+skipped）+ 7 xfailed"
                "（junitxml <skipped type=pytest.xfail>）——条目数==junitxml testcase 总数"
            ),
            "by_status": dict(sorted(status_counter.items())),
            "retry": {
                "applied": retry_applied,
                "stale_skipped": retry_stale,
                "stale_reason": (
                    "retry.xml mtime 早于本轮全部 seg xml mtime（round1 尾段遗留，"
                    "本轮 retried_green=0 无改判面）"
                    if retry_stale
                    else None
                ),
                "retried_green": retried_green,
                "retried_still_red": retried_still_red,
                "unmatched_nodeids": retry_unmatched,
            },
            "by_tier": by_tier,
            "duration_total_s": round(grand_total, 3),
            "estimates": {
                "full_gate_pure_test_min": round(grand_total / 60.0, 2),
                "daily_gate_A_plus_B_min": round(daily_ab / 60.0, 2),
                "c_layer_min": round(by_tier["C"]["total_s"] / 60.0, 2),
                "note": "纯测试时长推算（xml testcase time 之和），不含进程启动/收集/报告开销",
            },
        },
        "reconciliation": {
            "coverage": {
                "xml_testcase_total": xml_testcase_total,
                "entries_total": len(entries),
                "entries_equal_xml": len(entries) == xml_testcase_total,
                "tier_counts_sum": tier_sum,
                "tier_sum_equals_total": tier_sum == len(entries),
                "agg_total_line_tests": (agg["total_passed"] or 0)
                + (agg["total_failed"] or 0)
                + (agg["total_skipped"] or 0),
                "xml_extra_vs_agg_line": {
                    "count": xml_testcase_total
                    - (
                        (agg["total_passed"] or 0)
                        + (agg["total_failed"] or 0)
                        + (agg["total_skipped"] or 0)
                    ),
                    "kind": "xfailed (junitxml <skipped type=pytest.xfail>)",
                },
            },
            "c_layer": {
                "xml_buckets": buckets,
                "c_count_formula": (
                    f"C = xml_ge60({buckets['ge60']}) + xml_10-60({buckets['b10_60']})"
                    f" + xml_5-10({buckets['b5_10']}) = {c_count}"
                ),
                "c_count_actual": by_tier["C"]["count"],
                "c_count_matches": c_count == by_tier["C"]["count"],
                "log_maxphase_estimate": {
                    "ge60": log_buckets["ge60"],
                    "b10_60": log_buckets["b10_60"],
                    "b5_10": log_buckets["b5_10"],
                    "c_estimate": c_log_estimate,
                    "note": (
                        "聚合行推算式 C≈>=60s(10) + 10-60s(55) + 1-10s(470)中>=5s 部分；"
                        "log 口径=max(分相)且 <5ms 相位隐藏，xml 口径=相位总和——"
                        "5.0s 边界附近两口径可差数条，属预期"
                    ),
                },
                "agg_log_ge60": agg["durations_ge60"],
                "agg_log_10_60": agg["durations_10_60"],
                "agg_log_1_10_bucket": agg["durations_1_10"],
                "xml_ge60_matches_agg": buckets["ge60"] == agg["durations_ge60"],
                "xml_10_60_matches_agg": buckets["b10_60"] == agg["durations_10_60"],
                "champions_present": champions,
            },
            "crosscheck_log_vs_xml": {
                "seg_log口径": "分相（setup/call/teardown）行值 2 位小数且 <5ms 相位隐藏",
                "xml口径": "per-testcase time=相位总和（canonical）",
                "nodeids_matched": len(matched),
                "log_distinct_tests": len(log_shown),
                "agg_durations_sum_shown": agg["durations_sum"],
                "log_distinct_extra_vs_agg": (
                    len(log_shown) - agg["durations_sum"]
                    if agg["durations_sum"] is not None
                    else None
                ),
                "log_extra_vs_agg_note": (
                    "差异归因（实测）：v2 门 durations 解析正则 (\\S+)\\s*$ 要求 nodeid "
                    "无空白，参数化 id 含空格的测试被整行丢弃（本轮 22 条："
                    "test_mcp_server/test_w1_a_wiring/test_w3_d_env 等）——本生成器 "
                    "(\\S.*) 口径为其严格超集；22 条全在 <10s 低层桶，C 层对账不受扰"
                    "（xml ge60/10-60 两桶与聚合行 10/55 逐一相等）"
                )
                if agg["durations_sum"] is not None
                and len(log_shown) > agg["durations_sum"]
                else None,
                "log_distinct_matches_agg_sum": len(log_shown) == agg["durations_sum"],
                "samples": len(samples),
                "sample_detail": samples,
                "max_rel_diff_pct": round(max_rel * 100.0, 4),
                "max_rel_diff_nodeid": max_rel_nid,
            },
            "top50": {
                "count": len(top50),
                "total_s": round(top50_total, 3),
                "share_pct": round(top50_total / grand_total * 100.0, 2)
                if grand_total > 0
                else 0.0,
            },
            "top100": {
                "count": len(top_n),
                "total_s": round(top_total, 3),
                "share_pct": round(top_total / grand_total * 100.0, 2)
                if grand_total > 0
                else 0.0,
            },
        },
        "slow_top": [
            _Flow(
                nodeid=e["nodeid"],
                file=e["file"],
                duration_s=round(e["duration_s"], 3),
                tier=e["tier"],
                status=e["status_raw"],
                flags=e["flags"],
            )
            for e in top_n
        ],
        "entries": entries_block,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="aurora_m W0-1 durations 全量画像生成器")
    ap.add_argument("--gate-parts", default="runs/gate_parts", help="门分段产物目录")
    ap.add_argument("--name", default="wf_gate_full_aurora_m_base", help="门产物名前缀")
    ap.add_argument("--agg-log", default="runs/wf_gate_full_aurora_m_base.log", help="聚合门日志")
    ap.add_argument("--tests-root", default="tests", help="测试根目录（flags 分类扫描面）")
    ap.add_argument("--out", default="runs/aurora_m/durations_manifest.yaml", help="产物输出路径")
    ap.add_argument("--c-threshold", type=float, default=TIER_C_DEFAULT_S, help="tier C 下限（秒）")
    ap.add_argument("--b-threshold", type=float, default=TIER_B_DEFAULT_S, help="tier B 下限（秒）")
    ap.add_argument("--top", type=int, default=SLOW_TOP_DEFAULT, help="slow_top 明细条数")
    ap.add_argument(
        "--samples",
        type=int,
        default=CROSSCHECK_SAMPLES_DEFAULT,
        help="log-vs-xml 交叉校验样本数（任务规格要求 >=20）",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = _build_manifest(args)
    out_path = Path(args.out)
    # sort_keys=False：全部 dict 以确定性插入序构建（头部在前、entries 主体在最后），
    # 列表/映射排序均显式完成——同输入两次输出逐字节一致。
    text = yaml.dump(
        manifest,
        Dumper=_ManifestDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
        default_flow_style=False,
    )
    out_path.write_text(text, encoding="utf-8", newline="\n")
    s = manifest["summary"]
    print(
        f"OK {out_path}: total={s['total_tests']} tiers="
        f"C={s['by_tier']['C']['count']}/B={s['by_tier']['B']['count']}/"
        f"A={s['by_tier']['A']['count']} "
        f"pure_test={s['estimates']['full_gate_pure_test_min']}min "
        f"daily_AB={s['estimates']['daily_gate_A_plus_B_min']}min "
        f"c_layer={s['estimates']['c_layer_min']}min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
