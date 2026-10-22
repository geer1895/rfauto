"""指标词典服务（aurora_i R3 设计 M2；W2-S2 席 2026-10-19）。

数据单一事实源：knowledge/metric_glossary.yaml（数据湖实测 38 个指标键，
schema 见该文件头注：metric_key/plain_zh/plain_en/unit 必填，good_when/
gate/gate_semantics/pitfall_refs/related_terms/computed_by/notes 可选）。
三入口全部只读、不抛异常，ok 信封（同 terminology_service 设计红线）：

- load_metric_glossary()：YAML 原文结构读取（缺失/损坏 → 空表不抛）；
- list_metric_glossary()：全量清单信封（count/entries/keys，前端一次拉
  全量缓存后本地判定着色——tooltip 是高频小查询，不打逐键请求）；
- get_metric(metric_key)：单键查询（大小写不敏感；未知 → ok=False）；
- judge_metric(metric_key, value)：现值 vs 机读判据三态判定
  （good/bad/neutral——gate 缺席或 value 非数值一律 neutral 中性）。

铁律 7 面一致：本模块只搬运 YAML 既有文本与机读判据，不产生任何物理
数字；判定op 集合固定（max_below/min_above/abs_le/bool_true），未知 op
如实落 neutral 不臆测。

公开面说明：本模块刻意**不带 __all__**（anchors_service 同例）——
check_public_api 按 __all__ 登记公开面，现值金快照已有他席在制漂移
（campaign_queue_daemon/remote_scheduler_service 两处），本席不翻公开名、
不重钉金快照；函数保持可 import 消费，后续快照重生成批再显式登记。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）。
#: 1.0=首批 38 键口径（aurora_i W2-S2）。
METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION = "1.0"

#: 机读判据 op 全集（knowledge/metric_glossary.yaml gate.op 合法值；
#: 前端 kit.js metricGateVerdict 同表——两端同构由 test_metric_glossary 钉）。
METRIC_GATE_OPS = ("max_below", "min_above", "abs_le", "bool_true")


def load_metric_glossary() -> dict[str, Any]:
    """读取 knowledge/metric_glossary.yaml；缺失/损坏时返回空表（不抛异常）。"""
    if not _GLOSSARY_PATH.exists():
        return {}
    try:
        with open(_GLOSSARY_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entries_raw() -> list[dict[str, Any]]:
    entries = load_metric_glossary().get("entries")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def list_metric_glossary() -> dict[str, Any]:
    """全量指标词典清单（JSON 进出信封）。

    entries 按文件序原样透传；keys 为派生键清单（前端 tooltip 索引用）；
    gate_ops 为机读判据 op 全集（前端判定同构依据）。
    """
    entries = _entries_raw()
    return ok_envelope(
        schema_version=METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION,
        schema=str(load_metric_glossary().get("schema") or ""),
        count=len(entries),
        keys=[str(e.get("metric_id", "")) for e in entries],
        gate_ops=list(METRIC_GATE_OPS),
        entries=entries,
    )


def get_metric(metric_key: str) -> dict[str, Any]:
    """单键查询（metric_key 大小写不敏感精确匹配；未知 → ok=False）。"""
    key = str(metric_key).strip().lower()
    for e in _entries_raw():
        if str(e.get("metric_id", "")).strip().lower() == key:
            return ok_envelope(
                schema_version=METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION,
                metric=e)
    return error_envelope(
        f"unknown metric_key: {metric_key!r}（见 list_metric_glossary 的 "
        f"keys 清单）",
        schema_version=METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION,
    )


def judge_metric(metric_key: str, value: Any) -> dict[str, Any]:
    """现值 vs 机读判据三态判定（前端着色的确定性内核）。

    返回 ok 信封：verdict ∈ {"good", "bad", "neutral"}——
    - 词条/机读 gate 缺席、value 非有限数值、gate.op 不在合法集 → neutral；
    - bool_true：真值（true/1，"false"/"0" 视为假）→ good/bad；
    - max_below/min_above/abs_le：value 与 gate.good 数值比较。
    neutral 是"无判据可判"的如实态，不是 PASS 也不是 FAIL（#122 同族：
    不凑绿也不冒充 FAIL）。
    """
    lookup = get_metric(metric_key)
    if not lookup.get("ok"):
        return ok_envelope(
            schema_version=METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION,
            metric_key=str(metric_key), verdict="neutral",
            reason="unknown_metric_key")
    entry = lookup.get("metric") or {}
    verdict, reason = _judge_entry(entry, value)
    return ok_envelope(
        schema_version=METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION,
        metric_key=str(metric_key), verdict=verdict, reason=reason,
        gate=entry.get("gate") or {})


def _judge_entry(entry: dict[str, Any], value: Any) -> tuple[str, str]:
    """单词条判定（纯函数面，node 侧 kit.js metricGateVerdict 同构）。"""
    gate = entry.get("gate")
    if not isinstance(gate, dict):
        return "neutral", "no_gate"
    op = str(gate.get("op", ""))
    if op not in METRIC_GATE_OPS:
        return "neutral", "unknown_op"
    if op == "bool_true":
        truthy = value is True or value == 1 or (
            isinstance(value, str) and value.strip().lower() == "true")
        falsy = value is False or value == 0 or (
            isinstance(value, str) and value.strip().lower() == "false")
        if not (truthy or falsy):
            return "neutral", "non_boolean_value"
        return ("good", "gate_bool_true") if truthy else ("bad", "gate_bool_true")
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or value != value or value in (float("inf"), float("-inf")):
        # bool 是 int 子类须排除；NaN 自不等；±inf 非有限读数——前端
        # kit.js isFinite 同构（非有限数值一律中性不判）。
        return "neutral", "non_numeric_value"
    good = gate.get("good")
    if not isinstance(good, (int, float)) or isinstance(good, bool):
        return "neutral", "gate_good_missing"
    v, g = float(value), float(good)
    passed = (v <= g if op == "max_below"
              else v >= g if op == "min_above"
              else abs(v) <= g)
    return ("good", f"gate_{op}") if passed else ("bad", f"gate_{op}")


_GLOSSARY_PATH = (
    Path(__file__).resolve().parents[3] / "knowledge" / "metric_glossary.yaml"
)
