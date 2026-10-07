"""PT-7 产线测试数据 schema 与失效率 Pareto 确定性内核。

规格书 研究扩充 round18 §四 PT-7：DUT/批次/测项/
限值/判定 schema + 按测项失效率 Pareto（vendor_passives 批次键在本模块以
vendor_part/batch 字段承接；vendor_passives.py 本体接线留归属面批次批，
本席文件面只新增——如实登记，不臆改既有模块）。

口径（铁律 5 来源写 docstring；铁律 7 数值只在确定性内核）：

- **产线测试记录 schema**（rfauto-production-record/v1）::

      {"dut_id": "DUT-0001",        # 必填，非空字符串
       "lot_id": "LOT-2026W40",     # 必填，非空字符串（批次键）
       "test_item": "s11_db",       # 必填，非空字符串（测项键）
       "measured": -18.2,           # 必填，有限数（bool 拒收，df7+⑯）
       "limits": {"usl": -10.0, "lsl": null},   # 至少一侧；数值有限
       "units": "dB",               # 可选
       "vendor_part": "...",        # 可选（vendor_passives 批次键承接）
       "batch": "...",              # 可选（供应商批次/料批）
       "verdict": "pass"}           # 可选；缺省由限值确定性重判

  判定规则（确定性裁判，限值缺侧=该侧不设限）：lsl ≤ measured ≤ usl
  （边界含端点）→ pass，否则 fail；verdict 输入与限值重判冲突时以限值
  重判为准并置 ``verdict_source: "recomputed"``（限值是客观判据，手工
  标记可错；两值随行披露不静默吞，#122 不凑绿）。``invalid`` 语义=测项
  本身无效（数据坏），须显式传入 verdict="invalid" 且此时限值不得参与
  重判（invalid 不进良率/Pareto 分母也不进分子，单列计数——#316 方向：
  数据坏如实单列，不冒充 pass 也不冒充 fail）。
- **Pareto**（按测项失效计数降序 + 累计占比）：排序键 (-fail_count,
  test_item 升名) 确定性全序（同计数并列按键名升序，杜绝键序漂移）；
  累计占比 cumulative_pct 相对总 fail 计数。经典 80/20 切面以
  ``cumulative_pct`` 供读，内核不硬切（切面是判读语义非数据语义）。
  J. M. Juran Pareto 分析口径（质量管理教科书标准工具，无公式分歧）。

接口纪律：同 core/acceptance_sampling.py（纯 numpy/stdlib、dict 进出
JSON 可序列化、bool 显式拒收、缺失 is not None、非法 ValueError、无 IO）。
"""

from __future__ import annotations

import math
from typing import Any

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_INVALID = "invalid"

__all__ = [
    "PRODUCTION_SCHEMA_VERSION",
    "failure_pareto",
    "lot_yield",
    "normalize_record",
    "normalize_records",
    "vendor_batch_summary",
]

PRODUCTION_SCHEMA_VERSION = "rfauto-production-record/v1"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空字符串")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染判定）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _limit(value: Any, name: str) -> float | None:
    if value is None:
        return None
    return _finite(value, name)


def normalize_record(raw: Any) -> dict[str, Any]:
    """产线测试记录归一+确定性判定（schema 见模块头注）。

    返回 dict：原字段（归一后）+ ``verdict``/``verdict_source``；
    verdict 重判与传入值冲突时保留重判值并把传入值放
    ``verdict_reported``（两值披露，不静默，#122）。
    """
    if not isinstance(raw, dict):
        raise ValueError("记录必须为 dict（rfauto-production-record/v1）")
    dut_id = _text(raw.get("dut_id"), "dut_id")
    lot_id = _text(raw.get("lot_id"), "lot_id")
    test_item = _text(raw.get("test_item"), "test_item")
    measured = _finite(raw.get("measured"), "measured")
    limits = raw.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("limits 必须为 dict（至少 usl/lsl 一侧）")
    usl = _limit(limits.get("usl"), "limits.usl")
    lsl = _limit(limits.get("lsl"), "limits.lsl")
    if usl is not None and lsl is not None and lsl > usl:
        raise ValueError("limits.lsl 不得超过 limits.usl")
    reported = raw.get("verdict")
    if reported is not None:
        reported = _text(reported, "verdict")
        if reported not in (VERDICT_PASS, VERDICT_FAIL, VERDICT_INVALID):
            raise ValueError("verdict 只接受 pass/fail/invalid")

    out: dict[str, Any] = {
        "schema": PRODUCTION_SCHEMA_VERSION,
        "dut_id": dut_id,
        "lot_id": lot_id,
        "test_item": test_item,
        "measured": measured,
        "limits": {"usl": usl, "lsl": lsl},
    }
    for key in ("units", "vendor_part", "batch"):
        if raw.get(key) is not None:
            out[key] = _text(raw.get(key), key)

    if reported == VERDICT_INVALID:
        out["verdict"] = VERDICT_INVALID
        out["verdict_source"] = "reported"
        return out

    # 确定性限值裁判（至少一侧有限才可判；两侧全缺=数据不完整多报不放过）
    if usl is None and lsl is None:
        raise ValueError("limits.usl/lsl 至少一侧须为有限数（两侧全缺无法判定）")
    ok = True
    if lsl is not None and measured < lsl:
        ok = False
    if usl is not None and measured > usl:
        ok = False
    judged = VERDICT_PASS if ok else VERDICT_FAIL
    out["verdict"] = judged
    if reported is not None and reported != judged:
        out["verdict_source"] = "recomputed"
        out["verdict_reported"] = reported
    else:
        out["verdict_source"] = "recomputed" if reported is None else "reported_and_matched"
    return out


def normalize_records(records: Any) -> list[dict[str, Any]]:
    """批量归一（列表进出；单条非法整批 ValueError，指明条目下标）。"""
    if not isinstance(records, (list, tuple)):
        raise ValueError("records 必须为 list/tuple")
    return [normalize_record(r) for r in records]


def failure_pareto(records: Any) -> dict[str, Any]:
    """按测项失效率 Pareto（fail 计数降序 + 累计占比，全键序确定）。

    invalid 记录单列 ``n_invalid``，不进任何分母/分子（#316：数据坏如实
    单列）；无 fail 时 items 为空表 + total_fail=0 如实返回（非报错）。
    """
    rows = normalize_records(records)
    n_invalid = 0
    fail_by_item: dict[str, int] = {}
    total_by_item: dict[str, int] = {}
    for r in rows:
        if r["verdict"] == VERDICT_INVALID:
            n_invalid += 1
            continue
        item = r["test_item"]
        total_by_item[item] = total_by_item.get(item, 0) + 1
        if r["verdict"] == VERDICT_FAIL:
            fail_by_item[item] = fail_by_item.get(item, 0) + 1
    total_fail = sum(fail_by_item.values())
    ordered = sorted(fail_by_item.items(), key=lambda kv: (-kv[1], kv[0]))
    items: list[dict[str, Any]] = []
    cum = 0
    for item, cnt in ordered:
        cum += cnt
        items.append(
            {
                "test_item": item,
                "fail_count": cnt,
                "n_tested": total_by_item.get(item, 0),
                "fail_rate": (cnt / total_by_item[item]) if total_by_item.get(item) else None,
                "fail_share": (cnt / total_fail) if total_fail else None,
                "cumulative_pct": (100.0 * cum / total_fail) if total_fail else None,
            }
        )
    return {
        "schema": PRODUCTION_SCHEMA_VERSION,
        "n_records": len(rows),
        "n_invalid": n_invalid,
        "total_fail": total_fail,
        "items": items,
    }


def lot_yield(records: Any) -> dict[str, Any]:
    """按批次良率（pass 数 / (pass+fail)，invalid 单列不入分母）。"""
    rows = normalize_records(records)
    lots: dict[str, dict[str, int]] = {}
    for r in rows:
        slot = lots.setdefault(r["lot_id"], {"pass": 0, "fail": 0, "invalid": 0})
        slot[r["verdict"]] += 1
    items: list[dict[str, Any]] = []
    for lot in sorted(lots):
        slot = lots[lot]
        denom = slot["pass"] + slot["fail"]
        items.append(
            {
                "lot_id": lot,
                "n_pass": slot["pass"],
                "n_fail": slot["fail"],
                "n_invalid": slot["invalid"],
                "yield_pct": (100.0 * slot["pass"] / denom) if denom else None,
            }
        )
    return {"schema": PRODUCTION_SCHEMA_VERSION, "lots": items}


def vendor_batch_summary(records: Any) -> dict[str, Any]:
    """vendor_passives 批次键承接：按 (vendor_part, batch) 分组良率摘要。

    仅统计带批次键的记录；缺键记录计入 ``n_unkeyed`` 如实披露（不静默丢）。
    """
    rows = normalize_records(records)
    groups: dict[tuple[str, str], dict[str, int]] = {}
    n_unkeyed = 0
    for r in rows:
        part = r.get("vendor_part")
        batch = r.get("batch")
        if part is None or batch is None:
            n_unkeyed += 1
            continue
        slot = groups.setdefault((part, batch), {"pass": 0, "fail": 0, "invalid": 0})
        slot[r["verdict"]] += 1
    items: list[dict[str, Any]] = []
    for (part, batch) in sorted(groups):
        slot = groups[(part, batch)]
        denom = slot["pass"] + slot["fail"]
        items.append(
            {
                "vendor_part": part,
                "batch": batch,
                "n_pass": slot["pass"],
                "n_fail": slot["fail"],
                "n_invalid": slot["invalid"],
                "fail_rate": (slot["fail"] / denom) if denom else None,
            }
        )
    return {
        "schema": PRODUCTION_SCHEMA_VERSION,
        "n_unkeyed": n_unkeyed,
        "groups": items,
    }
