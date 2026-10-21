"""锚 freshness 审计门（架构批 R8 可立项 #6 落地；2026-10-11 A7-D 席）。

R8 侦察（runs/架构批/R8_other_optimizations.md 面 7）：60 锚中 35 锚无
last_verified、陈旧锚无审计面——本脚本把"锚时效健康度"制度化：

- 结构性缺验证=硬门（棘轮）：非 retired 且非 awaiting_data 的锚缺
  last_verified（或 last_verified.at 缺失/不可解析）计数超过
  FRESH_RATCHET_MISSING（2026-10-14 SENS-ANC 批 +10 顺移 45、
  同日 ANCH-D 批 +5 顺移 50；2026-10-18 架构批 W3-S15 批 +4 顺移 54
  （ms_lattice v2/tjunc×2/mline，新锚真机首判前 last_verified 如实空）；
  2026-10-19 架构批活体代码验证回填 53 锚后人工下调 54→0
  （内部活体验证驱动+报告在档；closure 层闭式恒等口径，
  EM 首判窗未结如实注记）→ rc=1。
  判定面是静态的：只随 anchors.yaml 增删而变，时间推移不触发——挂
  merge_preflight 常驻面不会因时间流逝打红无关席位。棘轮只收不放：
  计数下降（补验证/retire）后人工下调；上调=新锚不带验证入库，须在
  战役台账给理由（口径同 test_w2_c_json_coverage WITHOUT_JSON 棘轮
  先例）。awaiting_data 缺验证属预声明语义（DP-3：骨架锚如实登记，
  data 回填后翻 active），不进棘轮、只在报告面计数。
- 时效超龄=报告面（永不红）：experimental 锚 last_verified 超过
  EXPERIMENTAL_OVER_AGE_DAYS（30 天）、active/stale 锚超过
  ACTIVE_OVER_AGE_DAYS（90 天）→ 清单报告（--verbose 逐条天数）。
  时间相关判定不进硬门；降级/复验处置权在人工（anchors.yaml 头注：
  运行时只读，写入只经人工 commit）。

装载走 infra.anchors_store.load_anchors 单源（mtime 缓存；单锚结构坏
进 load_errors 不拖垮整表），本脚本零写面。

rc：0=绿（缺验证 ≤ 棘轮）；1=红（新增未验证锚超棘轮）；2=注册表不可
读/空集——loader best-effort 空集无从判别，诚实降级 SKIP（merge_
preflight 同 pip-audit 口径：不判绿也不判红，#122 三分法环境类）。

用法：
  .venv/Scripts/python.exe scripts/audit_anchor_freshness.py
      [--registry <path>] [--json <out>] [--verbose] [--now <ISO8601>]

--now 仅供单测注入时钟；生产禁用。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.infra.anchors_store import (  # noqa: E402
    default_anchors_path,
    load_anchors,
)

REPORT_SCHEMA = "r8/anchor_freshness/1"

#: 结构性缺验证棘轮（2026-10-11 现值基线实测冻结=35；2026-10-14 SENS-ANC 批
#: +10 实测顺移=45；同日 ANCH-D 批 +5 实测顺移=50——新锚真机首判前 last_verified
#: 如实空，验证随首判回填后人工下调；只收不放，见模块 docstring）。
#: 2026-10-18 架构批 W3-S15 批 +4 顺移=54（ms_lattice v2/tjunc×2/mline）。
#: 2026-10-19 架构批 W3-S4 批人工下调 54→0：全仓 53 锚缺验证经活体代码
#: 验证驱动（内部证据目录+报告 JSON 在档）逐锚 PASS 回填
#: last_verified（closure 层闭式/公式恒等口径，EM 真机首判窗未结如实注记、
#: experimental status 零改动）——missing 实测=0，棘轮随计数下调归零；此后
#: 新锚不带 last_verified 入库即红（"新锚必须带 last_verified"全强度生效）。
FRESH_RATCHET_MISSING = 0

#: experimental 锚超龄报告阈值（天）——R8 #6 原文口径（"如 >30 天"）。
EXPERIMENTAL_OVER_AGE_DAYS = 30

#: active/stale 锚超龄报告阈值（天）。
ACTIVE_OVER_AGE_DAYS = 90

# 不进结构性棘轮的状态：retired=历史归档（时效语义不适用）；
# awaiting_data=骨架锚预声明语义（DP-3 P1 批）。
_STRUCTURAL_EXEMPT = frozenset({"retired", "awaiting_data"})
_AGE_EXEMPT = frozenset({"retired", "awaiting_data"})


def _parse_ts(value: object) -> datetime | None:
    """last_verified.at → aware datetime；缺失/不可解析返回 None。

    naive 时间戳按 UTC 处理（registry 内既有 ISO 带时区，naive 属历史
    手写容错）；时区缺失不作为"不可解析"惩罚。
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def audit_records(
    records: list[dict],
    now: datetime,
    ratchet: int = FRESH_RATCHET_MISSING,
) -> dict:
    """纯分类逻辑（无 IO）：records 为
    ``{"anchor_id", "status", "last_verified"}`` 字典列表。

    返回报告 dict（missing_last_verified/over_age_*/status_counts/ratchet/
    red）——over_age 永不影响 red；red 只由结构性缺验证超棘轮决定。
    """
    status_counts: dict[str, int] = {}
    missing: list[str] = []
    over_exp: list[dict] = []
    over_act: list[dict] = []
    retired = 0
    for rec in records:
        aid = str(rec.get("anchor_id") or "")
        status = str(rec.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "retired":
            retired += 1
            continue
        if status in _STRUCTURAL_EXEMPT:  # awaiting_data：预声明缺验证
            continue
        lv = rec.get("last_verified")
        ts = _parse_ts(lv.get("at") if isinstance(lv, dict) else None)
        if ts is None:
            missing.append(aid)
            continue
        age_days = (now - ts).days
        if status == "experimental" and age_days > EXPERIMENTAL_OVER_AGE_DAYS:
            over_exp.append({"anchor_id": aid, "age_days": age_days})
        elif status in ("active", "stale") and age_days > ACTIVE_OVER_AGE_DAYS:
            over_act.append({"anchor_id": aid, "age_days": age_days})
    missing.sort()
    return {
        "schema": REPORT_SCHEMA,
        "total": len(records),
        "status_counts": status_counts,
        "retired": retired,
        "missing_last_verified": missing,
        "ratchet": ratchet,
        "red": len(missing) > ratchet,
        "over_age_experimental": sorted(
            over_exp, key=lambda d: -d["age_days"]),
        "over_age_active": sorted(over_act, key=lambda d: -d["age_days"]),
    }


def verdict(report: dict) -> int:
    """报告 → 退出码（0 绿 / 1 红 / 2 环境类 SKIP）。"""
    if report.get("error"):
        return 2
    if report.get("total", 0) == 0:
        return 2
    return 1 if report.get("red") else 0


def _record_to_dict(rec: object) -> dict:
    """AnchorRecord（或同形对象）→ 审计入参 dict（测试用 SimpleNamespace 同形）。"""
    return {
        "anchor_id": getattr(rec, "anchor_id", ""),
        "status": getattr(rec, "status", ""),
        "last_verified": getattr(rec, "last_verified", None),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="锚 freshness 审计门（R8 #6）")
    ap.add_argument("--registry", default="", help="覆盖注册表路径（缺省单源口径）")
    ap.add_argument("--json", dest="json_out", default="",
                    help="报告 JSON 落盘路径（缺省只打印摘要）")
    ap.add_argument("--verbose", action="store_true",
                    help="超龄/缺验证清单逐条打印")
    ap.add_argument("--now", default="",
                    help="注入当前时刻 ISO8601（仅供单测；生产禁用）")
    args = ap.parse_args(argv)

    path = Path(args.registry) if args.registry else default_anchors_path()
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(timezone.utc)
    )
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    report: dict = {"schema": REPORT_SCHEMA, "registry_path": str(path)}
    if not path.exists():
        report["error"] = f"registry 不可读（不存在）: {path}"
    else:
        anchor_set = load_anchors(path, force_reload=True)
        records = [_record_to_dict(r) for r in anchor_set.records]
        # ratchet 显式传参（缺省参数在 def 期绑定，读模块全局须调用点直取）
        report.update(audit_records(records, now,
                                    ratchet=FRESH_RATCHET_MISSING))
        report["load_errors"] = list(anchor_set.load_errors)

    rc = verdict(report)
    if rc == 2:
        print(f"[SKIP] 锚 freshness 审计：{report.get('error', '注册表空集')}"
              "——诚实降级（环境类，不判绿不判红 #122）")
        return 2

    n_missing = len(report["missing_last_verified"])
    print(
        f"anchors={report['total']} "
        f"status={report['status_counts']} "
        f"missing_last_verified={n_missing}/{report['ratchet']}(棘轮) "
        f"over_age(exp>{EXPERIMENTAL_OVER_AGE_DAYS}d)="
        f"{len(report['over_age_experimental'])} "
        f"over_age(act>{ACTIVE_OVER_AGE_DAYS}d)="
        f"{len(report['over_age_active'])} "
        f"load_errors={len(report.get('load_errors', []))} "
        f"-> {'RED' if report['red'] else 'GREEN'}"
    )
    if args.verbose:
        for aid in report["missing_last_verified"]:
            print(f"  missing: {aid}")
        for item in report["over_age_experimental"]:
            print(f"  over-age(exp): {item['anchor_id']} "
                  f"{item['age_days']}d")
        for item in report["over_age_active"]:
            print(f"  over-age(active): {item['anchor_id']} "
                  f"{item['age_days']}d")
    if report["red"]:
        print(f"[FAIL] 缺验证锚 {n_missing} > 棘轮 {report['ratchet']}"
              "——新锚必须带 last_verified；棘轮只收不放，上调须在战役台账"
              "给理由（scripts/audit_anchor_freshness.py 头注口径）")
    if report.get("load_errors"):
        print(f"[WARN] {len(report['load_errors'])} 条 load_error"
              "（schema 面，归 validate 门管；此处仅留痕）")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
