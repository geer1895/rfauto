"""数据工厂 M4·摊销台账（长期指标"随采集自然累积"的机制化，B1 小项批）。

背景：一期 M4 实测摊销盈亏平衡 K=3.35 场（墙钟门
ratio=0.1398=7.15×）；≥5× 摊销需 K≈16.7 场（df1_next 候选队列#4）。
**"一场" = 一次对数据工厂库存发起的代理寻优战役（``run_surrogate_loop`` 类）**，
即"查库存 + 代理环"代替"逐点从头真解"的那类战役——库存采集成本
C_collect 由后续每场战役摊销。

K 语义（宁窄勿宽，诚实原则）::

    自动计数（counted）必须同时满足两个可辨识指纹：
      1. surrogate_loop 类战役指纹——JSON 结构上任一命中：
         ``loop.algorithm == "surrogate_loop"``（M4 bench 档，如
         runs/datafactory_m4/m4_offline.json）、
         ``algorithm ∈ {surrogate_loop, multifidelity_surrogate_loop}``、
         ``schema == "wp39_mvp_campaign_v1" 且 engine == "sbo"``；
      2. 数据工厂库存关联——stock.path 引用 datasets/ 下 parquet，或全文
         引用 ``points.parquet`` / （``datafactory`` 且 ``datasets``）。
    只满足指纹 1 而无库存关联的战役（如 wp39_mvp 系引擎真解 SBO 战役）
    **不计入 K**，作为 excluded 明细列出供人工复核；
    结构性模糊（关键字命中但 JSON 解析失败/字段缺失）一律不计数、进
    unreadable 如实列出——禁凑数。
    数不清的部分给手工登记口：``--add <id>`` 追加 runs/factory_m4_ledger/
    entries.jsonl（按 id 幂等），适用例如"M4 run2 谷芯加密验证腿"（复用
    run1 同一战役的 GP/环最优锚，无独立 surrogate_loop 指纹，是否单算一场
    留人工判定）。

每次 ``--scan`` 产出 ``runs/factory_m4_ledger/ledger.json``：K 当前值、
盈亏平衡 3.35、≥5× 目标 16.7、当前摊销状态（回收中/已回收/≥5×达成）+
各期战役明细。盈亏平衡常数优先读
``runs/datafactory_m4/m4_verdict.json`` 的 amortization 实测值
（k_breakeven_measured/k_for_5x_amortized），缺档回退预声明常数。

用法（cwd=仓库根）::

    python scripts/factory_m4_ledger.py --scan                      # 扫描+写台账
    python scripts/factory_m4_ledger.py --add m4-run2-refine --date 2026-09-20 --note "..."
    python scripts/factory_m4_ledger.py --scan --runs-dir runs      # 同缺省

只写 runs/factory_m4_ledger/ 两个文件；扫描只读 runs/（跳过 datasets/
openems_cache 数据/缓存目录）。零真机、零网络。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

__all__ = [
    "add_manual_entry",
    "amortization_status",
    "breakeven_constants",
    "build_ledger",
    "load_manual_entries",
    "scan_campaigns",
    "write_ledger",
]

#: 台账落盘目录（相对 runs 根）。
LEDGER_DIRNAME = "factory_m4_ledger"
#: 手工登记条目（JSONL，按 id 幂等）。
ENTRIES_FILENAME = "entries.jsonl"
#: 台账汇总。
LEDGER_FILENAME = "ledger.json"

#: 预声明常数（一期 M4 实测口径；verdict 档缺省时回退）。
DECLARED_BREAKEVEN_K = 3.35
DECLARED_TARGET_5X_K = 16.7
#: 一期 M4 verdict 归档（实测常数优先源，相对 runs 根）。
M4_VERDICT_REL = "datafactory_m4/m4_verdict.json"

#: surrogate_loop 类战役的结构指纹（逐文件 JSON 解析后判定）。
SURROGATE_LOOP_ALGORITHMS = frozenset({"surrogate_loop", "multifidelity_surrogate_loop"})
WP39_CAMPAIGN_SCHEMA = "wp39_mvp_campaign_v1"

#: 扫描跳过的目录名（数据/缓存，非战役产物；量级防护）。
SKIP_DIR_NAMES = frozenset({"openems_cache", "datasets", "__pycache__", ".git"})
#: 单文件读取上限（战役档都在 KB 量级；超限按 unreadable 如实列出）。
MAX_FILE_BYTES = 4_000_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_candidate_files(runs_dir: Path):
    """确定性（排序）遍历 runs/ 下候选 JSON，剪掉数据/缓存目录。"""
    for root, dirnames, filenames in os.walk(runs_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for name in sorted(filenames):
            if name.endswith(".json"):
                yield Path(root) / name


def _read_payload(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """读 JSON；返回 (payload, error)。超限/IO/解析失败如实返回 error。"""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None, "file too large"
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"io error: {exc}"
    try:
        payload = json.loads(text)
    except ValueError:
        return None, "json parse error"
    return (payload if isinstance(payload, dict) else None), (
        None if isinstance(payload, dict) else "top level not an object"
    )


def _is_stock_linked(payload: dict[str, Any], raw_text: str) -> bool:
    """数据工厂库存关联：stock.path 引用 datasets parquet，或全文引用。"""
    stock = payload.get("stock")
    if isinstance(stock, dict):
        stock_path = str(stock.get("path", "")).replace("\\", "/").lower()
        if "points.parquet" in stock_path or "datasets" in stock_path:
            return True
    lowered = raw_text.lower()
    if "points.parquet" in lowered:
        return True
    return "datafactory" in lowered and "datasets" in lowered


def _campaign_entry(rel_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """从战役档提取明细字段（缺省 None，不猜）。"""
    loop = payload.get("loop") if isinstance(payload.get("loop"), dict) else {}
    algorithm = payload.get("algorithm") or loop.get("algorithm")
    stock = payload.get("stock") if isinstance(payload.get("stock"), dict) else {}
    n_queries = payload.get("n_queries")
    if n_queries is None:
        n_queries = loop.get("n_queries")
    entry = {
        "path": rel_path,
        "created_at": payload.get("created_at"),
        "algorithm": str(algorithm) if algorithm else None,
        "stock_ref": (str(stock.get("path")).replace("\\", "/")
                      if stock.get("path") else None),
        "n_queries": n_queries if isinstance(n_queries, int) else None,
    }
    return entry


def _is_surrogate_loop_class(payload: dict[str, Any]) -> bool:
    """指纹 1：surrogate_loop 类战役（结构判定，宁窄勿宽不猜字符串）。"""
    loop = payload.get("loop") if isinstance(payload.get("loop"), dict) else {}
    algorithm = payload.get("algorithm") or loop.get("algorithm")
    if isinstance(algorithm, str) and algorithm in SURROGATE_LOOP_ALGORITHMS:
        return True
    schema = payload.get("schema")
    return schema == WP39_CAMPAIGN_SCHEMA and payload.get("engine") == "sbo"


def scan_campaigns(runs_dir: str | Path) -> dict[str, Any]:
    """扫描 runs/ 归档，产出 {counted, excluded, unreadable} 三类清单。

    counted：surrogate_loop 类指纹 + 库存关联双指纹齐备（自动计入 K）；
    excluded：有战役指纹但无库存关联（引擎真解类，不计 K，明细供人工复核）；
    unreadable：关键字命中但读取/解析失败（不计数，如实列出）。
    """
    runs = Path(runs_dir)
    counted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    if not runs.is_dir():
        return {"counted": counted, "excluded": excluded, "unreadable": unreadable}

    seen_rel: set[str] = set()
    for path in _iter_candidate_files(runs):
        rel = path.relative_to(runs).as_posix()
        # 先做廉价文本预筛，避免全量 JSON 解析
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '"algorithm"' not in raw_text and WP39_CAMPAIGN_SCHEMA not in raw_text:
            continue
        payload, error = _read_payload(path)
        if payload is None:
            unreadable.append({"path": rel, "reason": error or "unreadable"})
            continue
        if not _is_surrogate_loop_class(payload):
            continue
        if rel in seen_rel:
            continue
        seen_rel.add(rel)
        entry = _campaign_entry(rel, payload)
        if _is_stock_linked(payload, raw_text):
            counted.append(entry)
        else:
            entry["reason"] = "surrogate_loop 类战役但无数据工厂库存引用（不计 K）"
            excluded.append(entry)
    return {
        "counted": counted,
        "excluded": excluded,
        "unreadable": unreadable,
    }


def breakeven_constants(runs_dir: str | Path) -> dict[str, Any]:
    """盈亏平衡常数：verdict 实测优先，缺档回退预声明（来源如实记录）。"""
    verdict_path = Path(runs_dir) / M4_VERDICT_REL
    try:
        payload = json.loads(verdict_path.read_text(encoding="utf-8"))
        amort = payload.get("amortization") or {}
        breakeven = amort.get("k_breakeven_measured")
        target = amort.get("k_for_5x_amortized")
        if isinstance(breakeven, (int, float)) and breakeven > 0:
            source = f"runs/{M4_VERDICT_REL}:amortization"
            if not isinstance(target, (int, float)) or target <= 0:
                target = DECLARED_TARGET_5X_K
                source += "+declared target"
            return {"breakeven_k": float(breakeven), "target_5x_k": float(target),
                    "source": source}
    except (OSError, ValueError):
        pass
    return {
        "breakeven_k": DECLARED_BREAKEVEN_K,
        "target_5x_k": DECLARED_TARGET_5X_K,
        "source": f"declared（{M4_VERDICT_REL} 缺档回退，一期 M4 实测口径）",
    }


def amortization_status(k_current: float, breakeven_k: float,
                        target_5x_k: float) -> str:
    """摊销状态三档：回收中 / 已回收 / ≥5×达成。"""
    if k_current >= target_5x_k:
        return "≥5×达成"
    if k_current >= breakeven_k:
        return "已回收"
    return "回收中"


def _ledger_dir(runs_dir: str | Path) -> Path:
    return Path(runs_dir) / LEDGER_DIRNAME


def load_manual_entries(runs_dir: str | Path) -> list[dict[str, Any]]:
    """读手工登记条目（JSONL；坏行如实跳过并保留在 errors）。"""
    path = _ledger_dir(runs_dir) / ENTRIES_FILENAME
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("id"):
            entries.append(payload)
    return entries


def add_manual_entry(runs_dir: str | Path, entry_id: str, *,
                     date: str | None = None, note: str = "") -> dict[str, Any]:
    """手工追加一场战役登记（按 id 幂等：已存在则不重复追加）。"""
    entry_id = str(entry_id).strip()
    if not entry_id:
        return {"ok": False, "errors": ["--id 不能为空"]}
    entries = load_manual_entries(runs_dir)
    if any(e.get("id") == entry_id for e in entries):
        return {"ok": True, "already_present": True, "id": entry_id,
                "n_entries": len(entries)}
    entry: dict[str, Any] = {
        "id": entry_id,
        "date": date,
        "note": note,
        "added_at": _now_iso(),
        "origin": "manual",
    }
    d = _ledger_dir(runs_dir)
    d.mkdir(parents=True, exist_ok=True)
    with (d / ENTRIES_FILENAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"ok": True, "already_present": False, "id": entry_id,
            "n_entries": len(entries) + 1}


def build_ledger(runs_dir: str | Path) -> dict[str, Any]:
    """扫描 + 手工登记合并 -> 台账汇总（JSON 原生，落 ledger.json 前的形态）。"""
    scan = scan_campaigns(runs_dir)
    manual = load_manual_entries(runs_dir)
    constants = breakeven_constants(runs_dir)
    k_auto = len(scan["counted"])
    k_manual = len(manual)
    k_current = k_auto + k_manual
    status = amortization_status(float(k_current), constants["breakeven_k"],
                                 constants["target_5x_k"])
    return {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "generated_by": "scripts/factory_m4_ledger.py",
        "semantics": {
            "unit": "一场 = 一次对数据工厂库存发起的代理寻优战役（run_surrogate_loop 类）",
            "count_rule": "自动计数须双指纹齐备：surrogate_loop 类结构指纹 + 数据工厂"
                          "库存引用（stock.path/points.parquet）；只满足战役指纹的"
                          "引擎真解类（wp39_mvp 系）不计 K、列 excluded；解析失败列"
                          " unreadable 不凑数；数不清的走 --add 手工登记口。",
            "known_unauto_countable": [
                "M4 run2 谷芯加密验证腿（复用 run1 战役 GP/环最优锚，无独立 "
                "surrogate_loop 指纹）——如判单算一场请 --add 手工登记",
            ],
        },
        "constants": {
            **constants,
            "declared_fallback": {
                "breakeven_k": DECLARED_BREAKEVEN_K,
                "target_5x_k": DECLARED_TARGET_5X_K,
            },
        },
        "k_current": k_current,
        "k_auto": k_auto,
        "k_manual": k_manual,
        "amortization_status": status,
        "campaigns": scan["counted"],
        "excluded_candidates": scan["excluded"],
        "unreadable": scan["unreadable"],
        "manual_entries": manual,
    }


def write_ledger(runs_dir: str | Path, ledger: dict[str, Any]) -> Path:
    d = _ledger_dir(runs_dir)
    d.mkdir(parents=True, exist_ok=True)
    out = d / LEDGER_FILENAME
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 摊销台账（K 场累计/盈亏平衡/状态）")
    parser.add_argument("--scan", action="store_true", help="扫描 runs/ 并写 ledger.json")
    parser.add_argument("--add", dest="add_id", default=None,
                        help="手工追加一场战役登记（id，幂等）")
    parser.add_argument("--date", default=None, help="手工条目日期（可选）")
    parser.add_argument("--note", default="", help="手工条目备注（可选）")
    parser.add_argument("--runs-dir", default="runs", help="runs 根目录（默认 runs）")
    args = parser.parse_args(argv)
    if not args.scan and args.add_id is None:
        parser.print_help()
        return 2

    runs_dir = Path(args.runs_dir)
    if args.add_id is not None:
        result = add_manual_entry(runs_dir, args.add_id, date=args.date,
                                  note=args.note)
        if not result.get("ok"):
            print(json.dumps(result, ensure_ascii=False))
            return 1
        print(("已存在（幂等跳过）: " if result["already_present"] else "已追加: ")
              + result["id"])
    if args.scan:
        ledger = build_ledger(runs_dir)
        out = write_ledger(runs_dir, ledger)
        print(f"K 当前 = {ledger['k_current']} "
              f"(自动 {ledger['k_auto']} + 手工 {ledger['k_manual']})，"
              f"盈亏平衡 {ledger['constants']['breakeven_k']}，"
              f"≥5× 目标 {ledger['constants']['target_5x_k']}，"
              f"状态: {ledger['amortization_status']}")
        print(f"excluded（有战役指纹无库存引用）: {len(ledger['excluded_candidates'])}"
              f"；unreadable: {len(ledger['unreadable'])}")
        print(f"ledger -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
