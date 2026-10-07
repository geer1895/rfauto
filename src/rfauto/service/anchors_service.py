"""DP-3 锚注册表 JSON 薄面（服务层，规则 4：JSON 进出，CLI/MCP 是薄壳）。

一切返回 dict 且 JSON 可序列化；ok=False 时带 error 字段。消费接线
（synthesize_*/渲染链 resolve_anchor 接入）为 DP-3 第二批——本批只开
数据面（list/inspect/validate/resolve 四个只读入口）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from rfauto.core.anchor_drift import (
    ALPHA_DEFAULT,
    anchor_drift_report,
    drift_fingerprint,
)
from rfauto.core.anchors import (
    EXPECTED_ANCHORS,
    anchor_correction_provenance,
    apply_anchor_correction,
)
from rfauto.infra.anchors_store import (
    default_anchors_path,
    load_anchors,
    validate_anchor_set,
)

_SUMMARY_FIELDS = ("anchor_id", "kind", "status", "version",
                   "template_family", "engine_pair", "quantity", "value",
                   "uncertainty", "domain", "fallback")

#: anchors 报告域 schema 版本（AU-2③ 按域推广，PDN 惯例；旧档案无键照
#: 读=消费面向后兼容。与快照库 payload 的 ``schema`` 键（_SNAPSHOT_SCHEMA）
#: 语义区分：后者是库文件格式标识，本常量只进 service 返回信封）。
ANCHORS_REPORT_SCHEMA_VERSION = "1.0"


def _stamped(envelope: dict[str, Any]) -> dict[str, Any]:
    """返回信封补域版本戳（已有则不动）。"""
    envelope.setdefault("schema_version", ANCHORS_REPORT_SCHEMA_VERSION)
    return envelope


def list_anchors(path: str | None = None) -> dict[str, Any]:
    """列出全部已登记锚（摘要行，按 anchor_id 排序）。"""
    anchor_set = load_anchors(path)
    anchors = []
    for rec in anchor_set.records:
        row = {k: rec.raw.get(k) for k in _SUMMARY_FIELDS}
        row["version"] = rec.version
        anchors.append(row)
    return _stamped({
        "ok": True,
        "registry": str(default_anchors_path() if path is None else path),
        "count": len(anchor_set),
        "expected_count": len(EXPECTED_ANCHORS),
        "load_errors": list(anchor_set.load_errors),
        "anchors": anchors,
    })


def inspect_anchor(anchor_id: str, path: str | None = None) -> dict[str, Any]:
    """单锚全量记录（raw 透传 + 解析字段）。"""
    anchor_set = load_anchors(path)
    rec = anchor_set.get(str(anchor_id))
    if rec is None:
        return _stamped({"ok": False,
                         "error": f"未知锚: {anchor_id}（已知: {anchor_set.anchor_ids}）"})
    return _stamped({"ok": True, "anchor": rec.to_dict()})


def validate_registry(path: str | None = None) -> dict[str, Any]:
    """schema + provenance 校验 + 单源计数核对（CLI/MCP validate 门）。"""
    anchor_set = load_anchors(path)
    report = validate_anchor_set(anchor_set, registry_path=path or None)
    report["ok"] = bool(report["ok"]) and not anchor_set.load_errors
    return _stamped(report)


def resolve_anchor_request(anchor_id: str,
                           params: dict[str, float] | None = None,
                           path: str | None = None) -> dict[str, Any]:
    """resolve_anchor 的 JSON 面：{ok, result: {hit, value, source, ...}}。"""
    anchor_set = load_anchors(path)
    result = anchor_set.resolve_anchor(str(anchor_id), params or {})
    return _stamped({"ok": True, "result": result})


def note_anchor_residual_request(anchor_id: str, point: dict[str, float],
                                 observed: float,
                                 path: str | None = None) -> dict[str, Any]:
    """漂移检测的 JSON 面（内存面翻 stale；YAML 零改写，落盘走人工 commit）。"""
    anchor_set = load_anchors(path)
    outcome = anchor_set.note_anchor_residual(str(anchor_id), point,
                                              float(observed))
    return _stamped({"ok": bool(outcome.get("ok")), "result": outcome})


# ---------------------------------------------------------------------------
# XC-A 锚→设计自动修正（规格 §B-2；JSON 面，core 内核薄壳）
# ---------------------------------------------------------------------------

def find_anchors_request(template_family: str, quantity: str, *,
                         active_only: bool = True,
                         engine: str | None = None,
                         path: str | None = None) -> dict[str, Any]:
    """族×量锚查询的 JSON 面：{ok, count, anchors: [摘要行]}（零匹配空表）。"""
    anchor_set = load_anchors(path)
    records = anchor_set.find_anchors(str(template_family), str(quantity),
                                      active_only=active_only, engine=engine)
    anchors = []
    for rec in records:
        row = {k: rec.raw.get(k) for k in _SUMMARY_FIELDS}
        row["version"] = rec.version
        anchors.append(row)
    return _stamped({
        "ok": True,
        "registry": str(default_anchors_path() if path is None else path),
        "template_family": str(template_family),
        "quantity": str(quantity),
        "active_only": bool(active_only),
        "engine": engine,
        "count": len(anchors),
        "anchors": anchors,
    })


def apply_anchor_correction_request(
    family: str,
    quantity: str,
    params: dict[str, float] | None = None,
    *,
    design_value: float | None = None,
    engine: str | None = None,
    uncertainty_rel_max: float | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """XC-A 偏差面修正的 JSON 面：{ok, result: 修正包络, provenance: 五元组}。

    内核（core.anchors.apply_anchor_correction）永不抛、拒绝分支结构化
    reason——本薄壳 ok 恒 True（调用本身成功），修正是否生效看
    result.applied / result.reason。uncertainty_rel_max=None 走内核缺省
    （UNCERTAINTY_REL_MAX_DEFAULT=0.10）。
    """
    anchor_set = load_anchors(path)
    kwargs: dict[str, Any] = {"engine": engine,
                              "anchor_set": anchor_set}
    if uncertainty_rel_max is not None:
        kwargs["uncertainty_rel_max"] = float(uncertainty_rel_max)
    if design_value is not None:
        kwargs["design_value"] = float(design_value)
    result = apply_anchor_correction(str(family), str(quantity),
                                     dict(params or {}), **kwargs)
    return _stamped({
        "ok": True,
        "registry": str(default_anchors_path() if path is None else path),
        "result": result,
        "provenance": anchor_correction_provenance(result),
    })


def to_json(payload: dict[str, Any], *, indent: int | None = 1) -> str:
    """统一 JSON 序列化出口（中文原样）。"""
    return json.dumps(payload, ensure_ascii=False, indent=indent,
                      default=str)


# ---------------------------------------------------------------------------
# 新鲜度报告（QW-3：last_verified 龄期 + stale 判定；只读，零改写）
# ---------------------------------------------------------------------------

#: stale 缺省阈值（天）：last_verified 距今严格大于该值判 stale
STALE_THRESHOLD_DAYS_DEFAULT = 30.0


def _parse_anchor_verified_at(value: Any) -> datetime.datetime | None:
    """last_verified 的 at 字段 → tz-aware datetime（naive 按 UTC；失败 None）。"""
    if value is None:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def anchors_stale_report(
    threshold_days: float = STALE_THRESHOLD_DAYS_DEFAULT,
    *,
    path: str | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """锚新鲜度报告（QW-3，JSON 进出；只读，YAML 零改写）。

    逐锚输出 last_verified 龄期与 stale 判定。stale 判据：last_verified
    距今**严格大于** threshold_days（天，浮点比较）。无 last_verified
    字段（或 at 不可解析）的锚如实标注 ``date_kind="no_date"``、
    ``stale=None``——不虚构日期、不算 stale。

    Args:
        threshold_days: stale 阈值（天，≥0；缺省 30）。
        path: 注册表路径覆盖（缺省 knowledge/anchors.yaml）。
        now: 参考时刻注入（测试确定性用；缺省当前 UTC）。

    Returns:
        {ok, registry, threshold_days, as_of, count, stale_count,
        no_date_count, load_errors, anchors: [{anchor_id, status,
        last_verified_at, residual, age_days, stale, date_kind}]}；
        负阈值 → ok=False。
    """
    if threshold_days < 0:
        return _stamped({"ok": False,
                         "error": f"threshold_days 须 ≥0，实际 {threshold_days}"})
    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    anchor_set = load_anchors(path)
    rows: list[dict[str, Any]] = []
    stale_count = 0
    no_date_count = 0
    for rec in sorted(anchor_set.records, key=lambda r: r.anchor_id):
        lv = rec.last_verified
        at_raw: Any = None
        residual: Any = None
        if isinstance(lv, dict):
            at_raw = lv.get("at")
            residual = lv.get("residual")
        elif lv is not None:  # 裸字符串日期变体（防御性兼容）
            at_raw = lv
        at_dt = _parse_anchor_verified_at(at_raw)
        if at_dt is None:
            no_date_count += 1
            rows.append({"anchor_id": rec.anchor_id, "status": rec.status,
                         "last_verified_at": (str(at_raw)
                                              if at_raw is not None else None),
                         "residual": residual, "age_days": None,
                         "stale": None, "date_kind": "no_date"})
            continue
        age_days = (now_dt - at_dt).total_seconds() / 86400.0
        is_stale = bool(age_days > float(threshold_days))
        if is_stale:
            stale_count += 1
        rows.append({"anchor_id": rec.anchor_id, "status": rec.status,
                     "last_verified_at": str(at_raw),
                     "residual": residual,
                     "age_days": round(age_days, 3),
                     "stale": is_stale, "date_kind": "dated"})
    return _stamped({
        "ok": True,
        "registry": str(default_anchors_path() if path is None else path),
        "threshold_days": float(threshold_days),
        "as_of": now_dt.isoformat(timespec="seconds"),
        "count": len(anchor_set),
        "stale_count": stale_count,
        "no_date_count": no_date_count,
        "load_errors": list(anchor_set.load_errors),
        "anchors": rows,
    })


# ---------------------------------------------------------------------------
# 漂移预警（QW-16：Mann-Kendall 趋势 + 分布指纹；只读注册表 + 独立快照库）
# ---------------------------------------------------------------------------

#: 指纹快照库缺省路径（runs/ 数据域，永不清理；独立于注册表 anchors.yaml
#: ——注册表运行时只读纪律不变，快照写面只落本库）。
DEFAULT_SNAPSHOT_STORE = (Path(__file__).resolve().parent.parent.parent.parent
                          / "runs" / "anchor_drift" / "snapshots.json")

_SNAPSHOT_SCHEMA = "rfauto-anchor-drift-snapshots-v1"


def _resolve_store(store_path: str | Path | None) -> Path:
    return Path(store_path) if store_path is not None else DEFAULT_SNAPSHOT_STORE


def _read_store(store_path: Path) -> list[dict[str, Any]]:
    if not store_path.is_file():
        return []
    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []  # 快照库损坏 best-effort 空表（#105：观测面不阻塞）
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"),
                                                    list):
        return []
    return [dict(s) for s in data["snapshots"] if isinstance(s, dict)]


def record_anchor_drift_snapshot(
    anchor_id: str, values: list[float], *, at: str | None = None,
    store_path: str | Path | None = None,
) -> dict[str, Any]:
    """存一条指纹快照（QW-16 数据积累机制：现在存快照，下次起可比对）。

    快照 = {anchor_id, at, values, fingerprint, recorded_at}；values 为
    该锚当批复验/观测残差（≥1 个）。快照库为独立 JSON（缺省
    runs/anchor_drift/snapshots.json），追加语义零改写注册表。

    Returns:
        {ok, anchor_id, snapshot_index, n_values, fingerprint, store_path}；
        values 空/非法 → ok=False（error 字段）。
    """
    try:
        clean = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        return _stamped({"ok": False, "error": f"values 含非数值: {exc}",
                         "anchor_id": str(anchor_id)})
    if not clean:
        return _stamped({"ok": False, "error": "values 为空（至少 1 个残差）",
                         "anchor_id": str(anchor_id)})
    fingerprint = drift_fingerprint(clean)
    store = _resolve_store(store_path)
    snaps = _read_store(store)
    entry = {
        "anchor_id": str(anchor_id),
        "at": str(at) if at is not None
        else datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"),
        "values": clean,
        "fingerprint": fingerprint,
    }
    snaps.append(entry)
    store.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SNAPSHOT_SCHEMA, "snapshots": snaps}
    tmp = store.with_suffix(store.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(store)
    return _stamped({"ok": True, "anchor_id": str(anchor_id),
                     "snapshot_index": len(snaps) - 1, "n_values": len(clean),
                     "fingerprint": fingerprint, "store_path": str(store)})


def load_anchor_drift_snapshots(
    anchor_id: str | None = None, *, store_path: str | Path | None = None,
) -> dict[str, Any]:
    """读指纹快照库（anchor_id 给出则过滤；库缺失/损坏如实空表）。"""
    store = _resolve_store(store_path)
    snaps = _read_store(store)
    if anchor_id is not None:
        wanted = str(anchor_id)
        snaps = [s for s in snaps if s.get("anchor_id") == wanted]
    return _stamped({"ok": True, "count": len(snaps), "snapshots": snaps,
                     "store_path": str(store)})


def anchor_drift_status(
    anchor_id: str,
    history: Any = None,
    *,
    alpha: float = ALPHA_DEFAULT,
    path: str | None = None,
    store_path: str | Path | None = None,
) -> dict[str, Any]:
    """单锚漂移预警状态（QW-16 服务面，JSON 进出；只读注册表）。

    数据源选择（显式 history 优先，其余按序回退、来源如实标注）：
    1. ``history`` 非空 → 直接消费（序列或快照形态，source="caller"）；
    2. 快照库有该锚快照 → 快照模式（source="snapshot_store"）；
    3. 注册表 last_verified.residual 单点 → 单点序列
       （source="registry.last_verified"，n=1 如实判 insufficient）；
    4. 全无 → 空序列（source="none"，empty_series=True 判 no_data）。

    序列数据积累期语义见 core/anchor_drift 模块 docstring。

    Returns:
        {ok, anchor_id, status, last_verified_at, last_verified_residual,
        history_source, empty_series, report}；未知锚 → ok=False。
    """
    anchor_set = load_anchors(path)
    rec = anchor_set.get(str(anchor_id))
    if rec is None:
        return _stamped({"ok": False,
                         "error": f"未知锚: {anchor_id}（已知: {anchor_set.anchor_ids}）"})
    lv_at: Any = None
    lv_residual: Any = None
    if isinstance(rec.last_verified, dict):
        lv_at = rec.last_verified.get("at")
        lv_residual = rec.last_verified.get("residual")
    elif rec.last_verified is not None:
        lv_at = rec.last_verified
    if history is not None and (not isinstance(history, (list, tuple))
                                or len(history) == 0):
        history = None  # 空壳 history 等价未给（回退链如实走）
    if history is not None:
        source = "caller"
        points = list(history)
    else:
        snaps = load_anchor_drift_snapshots(str(anchor_id),
                                            store_path=store_path)
        if snaps["count"] > 0:
            source = "snapshot_store"
            points = snaps["snapshots"]
        elif lv_residual is not None:
            source = "registry.last_verified"
            try:
                points = [float(lv_residual)]
            except (TypeError, ValueError):
                points = []
        else:
            source = "none"
            points = []
    report = anchor_drift_report(points, alpha=alpha)
    return _stamped({
        "ok": True,
        "anchor_id": rec.anchor_id,
        "status": rec.status,
        "last_verified_at": str(lv_at) if lv_at is not None else None,
        "last_verified_residual": lv_residual,
        "history_source": source,
        "empty_series": report["verdict"] == "no_data",
        "report": report,
    })
