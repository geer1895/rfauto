"""EP-1 审查报告生成器内核（round18 规格研究扩充 round18 §二）。

**只做确定性聚合（铁律 7）**：读 verdict/gates/产物清单，归一判级、汇总门表、
分区异常、逐条在案证据路径——零 LLM 零网络零物理数字（阈值/实测值只从输入
行透传，本模块永不产生）。语义基准=既有三值纪律：design_lint_service 的
status 五词（pass/fail/warn/unknown/info）与门判级四级
PASS|FAIL|PARTIAL|UNKNOWN（#122 不凑绿、#316 缺方向多报）。

EP-1 checklist schema（severity + auto_check 关联 + waiver）::

    {"id": "CK-001",
     "severity": "block" | "advisory" | "info",   # 缺省 block（fail-safe）
     "auto_check": "constraints"?,                # 关联门名（门表 name 精确匹配）
     "waiver": {"approved_by": "...", "reason": "...",
                "expiry": "2026-12-31"}?}         # 三键全非空才有效

**验收语义（规格原文）**：waiver 过期自动翻 FAIL——block 级门红 + 有效
waiver → 豁免（不拦，但报告判级降为 PARTIAL，不冒充干净）；waiver 过期/
缺失/畸形 → 照常 FAIL 拦下。畸形 waiver（缺键/expiry 不可解析）按无豁免
处理（多报不放过，#316 方向），date-only expiry 当日含尾有效。

判级归一（normalize_grade）：精确词表 + 最长字面前缀（兼容带尾注串如
``FAIL(insufficient_data)``，vv_mapping._lookup 同款先例）::

    PASS    ← pass/passed/ok/healthy/clean/sat/true/AGREE_*/CERTIFIED_*/info*
    FAIL    ← fail/failed/unhealthy/issues/unsat/false/SENTINEL_FAIL/FAIL(…)
    PARTIAL ← partial/warn/warning/suspect/attention/SPLIT_*/conditionally_validated
    UNKNOWN ← unknown/undecided/undecidable/skipped/not_run/absent/none/error/其余

``info`` 是 design_lint 的信息性行语义（跑通产出参考界、verdict 不受影响）
→ PASS + informational=True，汇总单列不计入判级 rollup；error 是执行/基础
设施失败≠门决定 → UNKNOWN。

报告 schema（JSON 进出）::

    {"schema": "rfauto-review-report-v1", "generated_utc": ...,
     "inputs": {...}, "summary": {verdict, 门计数, 异常计数, waiver 计数},
     "gates_table": [{name, grade, verdict_raw, threshold, measured, source,
                      origin?, detail?, criteria_ref?, informational?,
                      severity, waived?, waiver_expired?, waiver?}...],
     "verdicts": [{name, verdict_raw, grade, informational, criteria_ref?,
                   source_path?, n_gates}...],
     "checklist": [{id, severity, auto_check, matched_gates, item_grade,
                    item_effective, waiver_state, waiver?}...]（未提供=[]）,
     "anomalies": {"gate_failures": [...], "data_quality": [...]},
     "evidence_paths": [...]}

输入面三选一（组合可）：``verdicts``（内存 verdict 集：单 dict/名→dict 映射/
dict 列表/JSON 文件路径或其列表）、``run_dir``（按 VERDICT_GLOBS 递归扫
可判级产物，坏文件进 data_quality 不中断）、``checklist``（上述 schema 列
表）。零输入/收集不到任何 verdict → ValueError（程序性错误如实抛）。

CLI 接线（``rfauto lint --report`` 出 PDF/typst）属集成批次；本模块交付
JSON+Markdown 双出内核（render_markdown/write_review_report），service 薄壳
后续按分层架构挂线。纯函数零真机，锚树 tests/unit/test_review_report.py。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "GRADES",
    "REVIEW_REPORT_SCHEMA",
    "SEVERITIES",
    "VERDICT_GLOBS",
    "generate_review_report",
    "normalize_grade",
    "render_markdown",
    "write_review_report",
]

REVIEW_REPORT_SCHEMA = "rfauto-review-report-v1"
"""报告 schema 版本（配方 schema_version/recipe_version 语义辨析见 #106）。"""

GRADES = ("PASS", "FAIL", "PARTIAL", "UNKNOWN")
"""门判级四级（任务书口径；rollup 严重序 FAIL > PARTIAL > UNKNOWN > PASS）。"""

SEVERITIES = ("block", "advisory", "info")
"""EP-1 checklist severity 三级（缺省 block=fail-safe，未管理门红必拦）。"""

VERDICT_GLOBS = ("*verdict*.json", "*health*.json", "gates.json")
"""run_dir 扫描的可判级产物 glob（meta.json 非判级产物，刻意不入集）。"""

_GRADE_ORDER = {"PASS": 0, "UNKNOWN": 1, "PARTIAL": 2, "FAIL": 3}

_GRADE_EXACT: dict[str, tuple[str, bool]] = {
    # 精确词表：(判级, informational)
    "pass": ("PASS", False), "passed": ("PASS", False), "ok": ("PASS", False),
    "healthy": ("PASS", False), "clean": ("PASS", False), "sat": ("PASS", False),
    "true": ("PASS", False),
    "info": ("PASS", True),  # design_lint 信息性行：跑通产出参考界，不设门
    "fail": ("FAIL", False), "failed": ("FAIL", False), "unhealthy": ("FAIL", False),
    "issues": ("FAIL", False), "unsat": ("FAIL", False), "false": ("FAIL", False),
    "sentinel_fail": ("FAIL", False),
    "partial": ("PARTIAL", False), "warn": ("PARTIAL", False),
    "warning": ("PARTIAL", False), "suspect": ("PARTIAL", False),
    "attention": ("PARTIAL", False), "conditionally_validated": ("PARTIAL", False),
    "unknown": ("UNKNOWN", False), "undecided": ("UNKNOWN", False),
    "undecidable": ("UNKNOWN", False), "skipped": ("UNKNOWN", False),
    "not_run": ("UNKNOWN", False), "absent": ("UNKNOWN", False),
    "none": ("UNKNOWN", False),
    "error": ("UNKNOWN", False),  # 执行/基础设施失败 ≠ 门决定
}
"""归一精确词表（小写键；不可识别词如实 UNKNOWN）。"""

_GRADE_PREFIXES: tuple[tuple[str, str], ...] = (
    # 最长字面前缀优先（带尾注串兼容：FAIL(insufficient_data)/AGREE_OPENEMS…）
    ("SENTINEL_FAIL", "FAIL"),
    ("UNDECIDABLE", "UNKNOWN"),
    ("UNDECIDED", "UNKNOWN"),
    ("UNKNOWN", "UNKNOWN"),
    ("CERTIFIED", "PASS"),
    ("AGREE", "PASS"),
    ("PARTIAL", "PARTIAL"),
    ("SPLIT", "PARTIAL"),
    ("WARN", "PARTIAL"),
    ("FAIL", "FAIL"),
    ("PASS", "PASS"),
)
"""vv_mapping._lookup 同款前缀归一（带尾注 verdict 串的项目既存形态）。"""

_VERDICT_KEYS = ("verdict", "status", "grade", "replay_verdict")
"""行级判级键优先序（recast 用 replay_verdict，design_lint/health 用 verdict/status）。"""

_THRESHOLD_KEYS = ("threshold", "limit", "limit_value")
_MEASURED_KEYS = ("measured", "actual", "measured_value")

_SINGLE_HINT_KEYS = (*_VERDICT_KEYS, "checks", "gates", "name", "ok", "summary")
"""dict 输入单 verdict 形态判别键（命中任一→按单个 verdict 处理，否则名→dict 映射）。"""


# ─── 判级归一 ────────────────────────────────────────────────────────────────


def normalize_grade(raw: Any) -> tuple[str, bool]:
    """原始判级词 → (四级判级, informational)。不可识别如实 UNKNOWN（不编）。

    bool 先按真值映射（True→PASS/False→FAIL）；其余非串 str() 后走词表。
    """
    if isinstance(raw, bool):
        return ("PASS", False) if raw else ("FAIL", False)
    text = raw if isinstance(raw, str) else str(raw)
    key = text.strip().lower()
    hit = _GRADE_EXACT.get(key)
    if hit is not None:
        return hit
    upper = text.strip().upper()
    for prefix, grade in _GRADE_PREFIXES:
        if upper.startswith(prefix):
            return grade, False
    return "UNKNOWN", False


def _grade_of_row(row: dict[str, Any]) -> tuple[str | None, Any, bool]:
    """行判级键探测：→(grade|None, verdict_raw, informational)。"""
    for key in _VERDICT_KEYS:
        if key in row:
            grade, info = normalize_grade(row[key])
            return grade, row[key], info
    return None, None, False


def _first_key(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    nested = row.get("result")
    if isinstance(nested, dict):
        for key in keys:
            if key in nested and nested[key] is not None:
                return nested[key]
    return None


# ─── verdict 集收集 ──────────────────────────────────────────────────────────


def _looks_like_mapping(d: dict[str, Any]) -> bool:
    """名→verdict 映射形态判别：全值 dict 且不含任何单 verdict 提示键。"""
    return bool(d) and all(isinstance(v, dict) for v in d.values()) \
        and not any(k in d for k in _SINGLE_HINT_KEYS)


def _entry_name(data: dict[str, Any], fallback: str) -> str:
    name = data.get("name")
    return name if isinstance(name, str) and name.strip() else fallback


def _load_json_file(path: Path,
                    data_quality: list[dict[str, Any]]) -> Any | None:
    """读单个 JSON；坏文件落 data_quality（证据损坏留痕，不中断）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        data_quality.append({"kind": "unreadable", "path": str(path),
                             "detail": f"读取失败: {exc}"})
    except json.JSONDecodeError as exc:
        data_quality.append({"kind": "corrupt_json", "path": str(path),
                             "detail": f"JSON 解析失败: {exc}"})
    return None


def _entries_from_payload(
    payload: Any,
    path_hint: Path | None,
    data_quality: list[dict[str, Any]],
    default_name: str = "verdict",
) -> list[dict[str, Any]]:
    """单载荷（内存 dict/文件 JSON）→ verdict 条目列。

    条目 = {"name", "data", "source_path"}；形状坏（标量 JSON/条目非 dict）
    → data_quality，返回空。
    """
    stem = path_hint.stem if path_hint is not None else default_name
    src = str(path_hint.resolve()) if path_hint is not None else None
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for i, item in enumerate(payload):
            if isinstance(item, dict):
                out.append({"name": _entry_name(item, f"{stem}[{i}]"),
                            "data": item, "source_path": src})
            else:
                data_quality.append(
                    {"kind": "malformed_entry", "path": src,
                     "detail": f"{stem}[{i}] 非 dict（{type(item).__name__}）"})
        return out
    if isinstance(payload, dict):
        if _looks_like_mapping(payload):
            return [{"name": f"{stem}:{key}" if path_hint is not None else key,
                     "data": val, "source_path": src}
                    for key, val in payload.items()]
        return [{"name": _entry_name(payload, stem), "data": payload,
                 "source_path": src}]
    data_quality.append({"kind": "bad_shape", "path": src,
                         "detail": f"{stem} 顶层既非 dict 也非 list"
                                   f"（{type(payload).__name__}）"})
    return []


def _collect_entries(
    verdicts: Any,
    run_dir: str | Path | None,
    data_quality: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """verdicts/run_dir → (条目列, 实际读过的文件绝对路径)。"""
    entries: list[dict[str, Any]] = []
    read_files: list[str] = []
    if verdicts is not None:
        items = verdicts if isinstance(verdicts, (list, tuple)) else [verdicts]
        for i, item in enumerate(items):
            if isinstance(item, (str, Path)):
                path = Path(item)
                read_files.append(str(path.resolve()))
                payload = _load_json_file(path, data_quality)
                if payload is not None:
                    entries.extend(_entries_from_payload(payload, path, data_quality))
            elif isinstance(item, (dict, list, tuple)):
                entries.extend(_entries_from_payload(
                    item, None, data_quality, default_name=f"verdict_{i}"))
            else:
                raise ValueError(
                    f"verdicts 条目类型非法: {type(item).__name__}"
                    "（只收 dict/str/Path）")
    if run_dir is not None:
        root = Path(run_dir)
        if not root.is_dir():
            raise ValueError(f"run_dir 不存在或非目录: {root}")
        seen: set[str] = set()
        found: list[Path] = []
        for pattern in VERDICT_GLOBS:
            for path in root.rglob(pattern):
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(path)
        found.sort(key=lambda p: str(p))
        for path in found:
            read_files.append(str(path.resolve()))
            payload = _load_json_file(path, data_quality)
            if payload is not None:
                entries.extend(_entries_from_payload(payload, path, data_quality))
    if not entries:
        raise ValueError(
            "空输入：未收集到任何 verdict（verdicts 为空或 run_dir 下无可判级产物；"
            f"扫描面={VERDICT_GLOBS}）。坏产物留痕 data_quality={len(data_quality)} 条")
    return entries, sorted(set(read_files))


# ─── 门表/verdict 链构建 ─────────────────────────────────────────────────────


def _sub_gate_row(sub: Any, name_hint: str, entry: dict[str, Any],
                  data_quality: list[dict[str, Any]]) -> dict[str, Any] | None:
    """子门行（checks/gates 成员）→ 门表行；畸形子行落 data_quality 返回 None。"""
    if isinstance(sub, str):
        grade, info = normalize_grade(sub)
        return {"name": name_hint, "grade": grade, "verdict_raw": sub,
                "threshold": None, "measured": None,
                "source": entry["name"], "source_path": entry["source_path"],
                "criteria_ref": _criteria_ref(entry), "informational": info}
    if not isinstance(sub, dict):
        data_quality.append({"kind": "malformed_check_row", "path": entry["source_path"],
                             "detail": f"{entry['name']}/{name_hint} 子行非 dict/"
                                       f"非串（{type(sub).__name__}）"})
        return None
    grade, raw, info = _grade_of_row(sub)
    if grade is None:
        data_quality.append({"kind": "malformed_check_row", "path": entry["source_path"],
                             "detail": f"{entry['name']}/{name_hint} 缺判级键"
                                       f"（{_VERDICT_KEYS} 全缺）"})
        return None
    return {"name": str(sub.get("name") or sub.get("gate") or name_hint),
            "grade": grade, "verdict_raw": raw,
            "threshold": _first_key(sub, _THRESHOLD_KEYS),
            "measured": _first_key(sub, _MEASURED_KEYS),
            "source": entry["name"], "source_path": entry["source_path"],
            "criteria_ref": _criteria_ref(entry), "informational": info,
            "detail": sub.get("detail"), "origin": sub.get("source")}


def _criteria_ref(entry: dict[str, Any]) -> str | None:
    for key in ("criteria_ref", "criteria"):
        val = entry["data"].get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _is_verdictish(data: dict[str, Any]) -> bool:
    """条目是否含可判级材料（判级键或 checks/gates 子结构）。"""
    return any(key in data for key in _VERDICT_KEYS) \
        or "checks" in data or "gates" in data


def _build_rows(
    entries: list[dict[str, Any]],
    data_quality: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """条目 → (门表行, verdict 链行)。有 checks/gates 则子行成门、本体只进链；
    非 verdictish 条目（已由调用方落 data_quality）不产任何行。"""
    gates: list[dict[str, Any]] = []
    chain: list[dict[str, Any]] = []
    for entry in entries:
        data = entry["data"]
        if not _is_verdictish(data):
            continue
        grade, raw, info = _grade_of_row(data)
        sub_specs: list[tuple[str, Any]] = []
        checks = data.get("checks")
        if isinstance(checks, list):
            sub_specs.extend((f"check[{i}]", c) for i, c in enumerate(checks))
        elif checks is not None:
            data_quality.append({"kind": "bad_shape", "path": entry["source_path"],
                                 "detail": f"{entry['name']}.checks 非 list"})
        gates_block = data.get("gates")
        if isinstance(gates_block, dict):
            sub_specs.extend(sorted(gates_block.items()))
        elif isinstance(gates_block, list):
            sub_specs.extend((f"gate[{i}]", g) for i, g in enumerate(gates_block))
        elif gates_block is not None:
            data_quality.append({"kind": "bad_shape", "path": entry["source_path"],
                                 "detail": f"{entry['name']}.gates 非 dict/list"})
        n_gates = 0
        for hint, sub in sub_specs:
            row = _sub_gate_row(sub, hint, entry, data_quality)
            if row is not None:
                gates.append(row)
                n_gates += 1
        if not sub_specs and grade is not None:
            # 单 verdict 即单门（anchor/health/pdn 类）：本体成门行
            gates.append({"name": entry["name"], "grade": grade, "verdict_raw": raw,
                          "threshold": _first_key(data, _THRESHOLD_KEYS),
                          "measured": _first_key(data, _MEASURED_KEYS),
                          "source": entry["name"], "source_path": entry["source_path"],
                          "criteria_ref": _criteria_ref(entry),
                          "informational": info})
            n_gates = 1
        chain.append({"name": entry["name"], "verdict_raw": raw, "grade": grade,
                      "informational": info, "criteria_ref": _criteria_ref(entry),
                      "source_path": entry["source_path"], "n_gates": n_gates})
    return gates, chain


# ─── EP-1 checklist：severity + auto_check + waiver ─────────────────────────


def _parse_expiry(text: str) -> datetime | None:
    """expiry 串 → aware UTC datetime；date-only 当日含尾（23:59:59.999999）。

    date-only 分支必须显式前置判别：py3.11+ 的 datetime.fromisoformat 也收
    "YYYY-MM-DD"（解析成当日 00:00），绕行会使「当日含尾有效」语义失效。
    """
    value = text.strip()
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            d = date.fromisoformat(value)
        except ValueError:
            return None
        return datetime(d.year, d.month, d.day, 23, 59, 59, 999999,
                        tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # naive 一律按 UTC（口径显式）
    return dt.astimezone(timezone.utc)


def _eval_waiver(waiver: Any, now: datetime) -> tuple[str, str | None]:
    """waiver 三键校验 → (状态, 说明)。状态 ∈ absent|valid|expired|malformed。"""
    if waiver is None:
        return "absent", None
    if not isinstance(waiver, dict):
        return "malformed", f"waiver 非对象（{type(waiver).__name__}）"
    missing = [key for key in ("approved_by", "reason", "expiry")
               if not isinstance(waiver.get(key), str) or not waiver.get(key, "").strip()]
    if missing:
        return "malformed", f"waiver 缺非空字段: {missing}"
    expiry_dt = _parse_expiry(str(waiver["expiry"]))
    if expiry_dt is None:
        return "malformed", f"expiry 不可解析: {waiver['expiry']}"
    if now > expiry_dt:
        return "expired", f"waiver 已于 {expiry_dt.isoformat()} 过期"
    return "valid", f"waiver 有效至 {expiry_dt.isoformat()}"


def _process_checklist(
    checklist: Any,
    gates: list[dict[str, Any]],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """checklist → (清单行, 门名→{severity, waived, waiver_expired, waiver} 元数据)。

    程序性错误（checklist 非 list/条目缺 id/severity 非法）ValueError 如实抛；
    waiver 数据坏按 malformed→无豁免处理（多报不放过）。
    """
    if checklist is None:
        return [], {}
    if not isinstance(checklist, list):
        raise ValueError(f"checklist 必须是列表（得 {type(checklist).__name__}）")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for gate in gates:
        by_name.setdefault(str(gate["name"]), []).append(gate)
    rows: list[dict[str, Any]] = []
    meta: dict[str, dict[str, Any]] = {}
    for item in checklist:
        if not isinstance(item, dict):
            raise ValueError("checklist 条目必须是对象")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"checklist 条目缺非空 id: {item!r}")
        severity = item.get("severity", "block")
        if severity not in SEVERITIES:
            raise ValueError(
                f"checklist {item_id} severity 非法: {severity!r}（可用 {SEVERITIES}）")
        auto_check = item.get("auto_check")
        if auto_check is not None and not isinstance(auto_check, str):
            raise ValueError(f"checklist {item_id} auto_check 必须是串或省略")
        matched = by_name.get(auto_check, []) if auto_check is not None else []
        worst: str | None = None
        for gate in matched:
            if worst is None or _GRADE_ORDER[gate["grade"]] > _GRADE_ORDER[worst]:
                worst = gate["grade"]
        waiver = item.get("waiver")
        waiver_state, waiver_detail = _eval_waiver(waiver, now)
        waived = worst == "FAIL" and waiver_state == "valid"
        waiver_expired = worst == "FAIL" and waiver_state == "expired"
        effective = ("WAIVED" if waived else "FAIL") if worst == "FAIL" else worst
        rows.append({"id": item_id, "severity": severity,
                     "auto_check": auto_check,
                     "matched_gates": [str(g["name"]) for g in matched],
                     "item_grade": worst, "item_effective": effective,
                     "waiver_state": waiver_state,
                     "waiver_detail": waiver_detail,
                     "waiver": dict(waiver) if isinstance(waiver, dict) else None})
        if auto_check is not None:
            for gate in matched:
                meta[str(gate["name"])] = {"severity": severity, "waived": waived,
                                           "waiver_expired": waiver_expired,
                                           "waiver_state": waiver_state,
                                           "waiver": dict(waiver) if isinstance(waiver, dict) else None}
    return rows, meta


# ─── 汇总与报告组装 ──────────────────────────────────────────────────────────


def _rollup(gates: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    """门表 → (报告判级, 计数)。informational 行只计数不进 rollup（design_lint
    同语义）；零门行=未判 → UNKNOWN（不冒充干净，#316 方向）。"""
    if not gates:
        return "UNKNOWN", {"pass": 0, "fail": 0, "partial": 0,
                           "unknown": 0, "info": 0}
    counts = {"pass": 0, "fail": 0, "partial": 0, "unknown": 0, "info": 0}
    fail_hit = partial_hit = unknown_hit = False
    for gate in gates:
        grade = gate["grade"]
        if grade == "PASS":
            counts["info" if gate["informational"] else "pass"] += 1
            continue
        counts[grade.lower()] += 1
        if grade == "FAIL":
            severity = gate.get("severity", "block")
            if gate.get("waived"):
                partial_hit = True  # 有效豁免：不拦但报告不得冒充干净
            elif severity == "block":
                fail_hit = True
            elif severity == "advisory":
                partial_hit = True
            # severity == "info"：记录不判
        elif grade == "PARTIAL":
            partial_hit = True
        elif grade == "UNKNOWN":
            unknown_hit = True
    if fail_hit:
        verdict = "FAIL"
    elif partial_hit:
        verdict = "PARTIAL"
    elif unknown_hit:
        verdict = "UNKNOWN"
    else:
        verdict = "PASS"
    return verdict, counts


def generate_review_report(
    verdicts: Any = None,
    run_dir: str | Path | None = None,
    checklist: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """verdict 集/run 目录/checklist → 结构化审查报告（纯聚合，确定性）。

    同输入（含注入 now）两次调用逐位一致；缺产物如实 UNKNOWN 不编；
    门红与数据坏分区（anomalies.gate_failures / anomalies.data_quality）；
    证据路径逐条在案。空输入/收集不到 verdict → ValueError。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise ValueError(f"now 必须是 datetime（得 {type(now).__name__}）")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    data_quality: list[dict[str, Any]] = []
    entries, read_files = _collect_entries(verdicts, run_dir, data_quality)
    for entry in entries:
        if not _is_verdictish(entry["data"]):
            data_quality.append(
                {"kind": "malformed_entry", "path": entry["source_path"],
                 "detail": f"{entry['name']} 既缺判级键（{_VERDICT_KEYS}）"
                           "也无 checks/gates 子结构"})
    gates, chain = _build_rows(entries, data_quality)

    checklist_rows, gate_meta = _process_checklist(checklist, gates, now)
    for gate in gates:
        meta = gate_meta.get(str(gate["name"]), {})
        gate["severity"] = meta.get("severity", "block")
        gate["waived"] = bool(meta.get("waived", False))
        gate["waiver_expired"] = bool(meta.get("waiver_expired", False))
        if meta.get("waiver") is not None:
            gate["waiver"] = meta["waiver"]

    verdict, counts = _rollup(gates)
    gate_failures = [
        {"name": g["name"], "grade": "FAIL",
         "source": g["source"], "source_path": g["source_path"],
         "detail": g.get("detail"),
         "threshold": g.get("threshold"), "measured": g.get("measured"),
         "criteria_ref": g.get("criteria_ref"),
         "waived": bool(g.get("waived")),
         "waiver_expired": bool(g.get("waiver_expired"))}
        for g in gates if g["grade"] == "FAIL"
    ]
    summary = {"verdict": verdict, "n_gates": len(gates),
               "pass": counts["pass"], "fail": counts["fail"],
               "partial": counts["partial"], "unknown": counts["unknown"],
               "n_info": counts["info"],
               "n_anomalies_gate": len(gate_failures),
               "n_anomalies_data": len(data_quality),
               "n_waived": sum(1 for g in gates if g.get("waived")),
               "n_waiver_expired": sum(1 for g in gates if g.get("waiver_expired")),
               "n_checklist": len(checklist_rows),
               "n_checklist_unmatched": sum(
                   1 for c in checklist_rows
                   if c["auto_check"] is not None and not c["matched_gates"])}
    evidence = sorted(set(read_files)
                      | {str(e["source_path"]) for e in entries if e["source_path"]})
    return {"schema": REVIEW_REPORT_SCHEMA,
            "generated_utc": now.isoformat(),
            "inputs": {"run_dir": str(Path(run_dir).resolve()) if run_dir is not None else None,
                       "n_entries": len(entries), "n_files_read": len(read_files),
                       "n_checklist_items": len(checklist_rows)},
            "summary": summary,
            "gates_table": gates,
            "verdicts": chain,
            "checklist": checklist_rows,
            "anomalies": {"gate_failures": gate_failures,
                          "data_quality": data_quality},
            "evidence_paths": evidence}


# ─── Markdown 渲染（全 section 恒在，空面标「（无）」） ────────────────────────


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)


def _fmt_grade(gate: dict[str, Any]) -> str:
    text = str(gate["grade"])
    if gate.get("informational"):
        text += " (info)"
    if gate.get("waived"):
        text += " (waived)"
    if gate.get("waiver_expired"):
        text += " (waiver_expired)"
    return text


def render_markdown(report: dict[str, Any]) -> str:
    """报告 dict → Markdown（门表/verdict 链/检查清单/异常/证据全 section 恒在）。"""
    if not isinstance(report, dict) or report.get("schema") != REVIEW_REPORT_SCHEMA:
        raise ValueError(
            f"render_markdown 只收 {REVIEW_REPORT_SCHEMA} 报告 dict")
    s = report["summary"]
    lines: list[str] = []
    lines.append(f"# 审查报告（{REVIEW_REPORT_SCHEMA}）")
    lines.append("")
    lines.append(f"- 判级：**{s['verdict']}**")
    lines.append(f"- 生成时刻：{report['generated_utc']}")
    inputs = report["inputs"]
    lines.append(f"- 输入：run_dir={_fmt(inputs['run_dir'])}；"
                 f"verdict 条目 {inputs['n_entries']}（读文件 "
                 f"{inputs['n_files_read']}）；检查清单 {inputs['n_checklist_items']} 条")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for key, label in (("n_gates", "门总数"), ("pass", "PASS"), ("fail", "FAIL"),
                       ("partial", "PARTIAL"), ("unknown", "UNKNOWN"),
                       ("n_info", "info 行"), ("n_anomalies_gate", "门红"),
                       ("n_anomalies_data", "数据坏"), ("n_waived", "有效豁免"),
                       ("n_waiver_expired", "waiver 过期翻 FAIL"),
                       ("n_checklist", "清单条目"),
                       ("n_checklist_unmatched", "清单未匹配门")):
        lines.append(f"| {label} | {s[key]} |")
    lines.append("")
    lines.append("## 门表")
    lines.append("")
    if report["gates_table"]:
        lines.append("| 门名 | 判级 | 阈值 | 实测 | 来源 | 判据引用 |")
        lines.append("|---|---|---|---|---|---|")
        for g in report["gates_table"]:
            lines.append(f"| {g['name']} | {_fmt_grade(g)} | {_fmt(g.get('threshold'))} "
                         f"| {_fmt(g.get('measured'))} | {g['source']} "
                         f"| {_fmt(g.get('criteria_ref'))} |")
    else:
        lines.append("（无门行）")
    lines.append("")
    lines.append("## verdict 链")
    lines.append("")
    if report["verdicts"]:
        for v in report["verdicts"]:
            bits = [f"- `{v['name']}`：{_fmt(v['verdict_raw'])} → {v['grade'] or 'N/A'}"]
            if v.get("criteria_ref"):
                bits.append(f"判据: {v['criteria_ref']}")
            if v.get("source_path"):
                bits.append(f"source: {v['source_path']}")
            lines.append("；".join(bits))
    else:
        lines.append("（无 verdict）")
    lines.append("")
    lines.append("## 检查清单")
    lines.append("")
    if report["checklist"]:
        lines.append("| id | severity | auto_check | 判级 | 生效 | waiver |")
        lines.append("|---|---|---|---|---|---|")
        for c in report["checklist"]:
            lines.append(f"| {c['id']} | {c['severity']} | {_fmt(c['auto_check'])} "
                         f"| {_fmt(c['item_grade'])} | {_fmt(c['item_effective'])} "
                         f"| {_fmt(c['waiver_state'])} |")
    else:
        lines.append("（未提供检查清单）")
    lines.append("")
    lines.append("## 异常")
    lines.append("")
    lines.append("### 门红")
    lines.append("")
    failures = report["anomalies"]["gate_failures"]
    if failures:
        for a in failures:
            tag = "（waiver 过期翻 FAIL）" if a.get("waiver_expired") else \
                  ("（有效豁免）" if a.get("waived") else "")
            lines.append(f"- `{a['name']}`{tag}：{_fmt(a.get('detail'))} "
                         f"［来源 {a['source']}］")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("### 数据坏")
    lines.append("")
    if report["anomalies"]["data_quality"]:
        for a in report["anomalies"]["data_quality"]:
            lines.append(f"- [{a['kind']}] {_fmt(a.get('path'))}：{a['detail']}")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 证据路径")
    lines.append("")
    if report["evidence_paths"]:
        for p in report["evidence_paths"]:
            lines.append(f"- {p}")
    else:
        lines.append("（无）")
    lines.append("")
    return "\n".join(lines)


def write_review_report(
    report: dict[str, Any],
    out_dir: str | Path,
    stem: str = "review_report",
) -> dict[str, str]:
    """报告双出（JSON+Markdown）到 out_dir；返回 {"json", "markdown"} 路径。"""
    if not isinstance(report, dict) or report.get("schema") != REVIEW_REPORT_SCHEMA:
        raise ValueError(f"write_review_report 只收 {REVIEW_REPORT_SCHEMA} 报告 dict")
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{stem}.json"
    md_path = root / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
