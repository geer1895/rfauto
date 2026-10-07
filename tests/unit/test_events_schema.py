"""W3 飞行记录仪统一事件 schema 回收钉（月计划 B4；core/events.py 增量）。

判据预声明（模块 docstring 同源）：
- 写出侧：Event 携带 schema=rfauto-event/1 落盘（to_dict/to_jsonl）；
- 读出面：validate_event_payload 非抛出清单、normalize_event_payload
  抛 EventSchemaError 汇总报文、parse_event_line 损坏行=None（#105）；
- 旧档案兼容：无 schema 键照读（缺失不报错）；schema 值不识别报错
  （声明错版本比缺失严重）；
- 归一零原地改：输入 dict 逐键不变，副本补 schema；
- EventBus jsonl 端到端：emit→落盘→逐行 validate 全绿（写出统一性证明）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.events import (
    EVENT_REQUIRED_KEYS,
    EVENT_SCHEMA,
    Event,
    EventBus,
    EventSchemaError,
    EventType,
    normalize_event_payload,
    parse_event_line,
    validate_event_payload,
)

# ── 写出侧统一（schema 标识落盘） ───────────────────────────────────────────

class TestWriterSideSchema:
    def test_to_dict_carries_schema(self):
        ev = Event(event_type=EventType.RUN_CREATED, run_id="r1")
        d = ev.to_dict()
        assert d["schema"] == EVENT_SCHEMA
        assert d["event_type"] == "run_created"

    def test_jsonl_roundtrip_validates_clean(self):
        ev = Event(event_type=EventType.TRIAL_COMPLETED, run_id="r1",
                   data={"cost": 1.5})
        payload = json.loads(ev.to_jsonl())
        assert validate_event_payload(payload) == []
        assert payload["schema"] == EVENT_SCHEMA

    def test_jsonl_sink_end_to_end(self, tmp_path):
        bus = EventBus()
        bus.set_jsonl_sink(tmp_path / "events.jsonl")
        for et in (EventType.RUN_STARTED, EventType.PROGRESS,
                   EventType.RUN_COMPLETED):
            bus.emit(Event(event_type=et, run_id="r1"))
        lines = (tmp_path / "events.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            payload = parse_event_line(line)
            assert payload is not None
            assert validate_event_payload(payload) == []


# ── 读出面：validate / normalize / parse ────────────────────────────────────

def _good_payload() -> dict:
    return {"event_type": "run_completed", "run_id": "r1", "job_id": "",
            "message": "done", "data": {}, "timestamp": 1.0,
            "event_id": "abc123", "schema": EVENT_SCHEMA}


class TestValidateEventPayload:
    def test_good_payload_clean(self):
        assert validate_event_payload(_good_payload()) == []

    def test_legacy_payload_without_schema_is_valid(self):
        payload = _good_payload()
        del payload["schema"]
        assert validate_event_payload(payload) == []  # 旧档案缺失合法

    def test_non_mapping_rejected(self):
        errs = validate_event_payload(["not", "a", "dict"])
        assert errs and "映射" in errs[0]

    @pytest.mark.parametrize("key", list(EVENT_REQUIRED_KEYS))
    def test_missing_required_key_flagged(self, key):
        payload = _good_payload()
        del payload[key]
        errs = validate_event_payload(payload)
        assert any(key in e for e in errs)

    def test_unknown_event_type_rejected_with_vocabulary(self):
        payload = _good_payload()
        payload["event_type"] = "banana"
        errs = validate_event_payload(payload)
        assert any("banana" in e and "run_completed" in e for e in errs)

    def test_bool_timestamp_rejected(self):
        payload = _good_payload()
        payload["timestamp"] = True
        assert any("timestamp" in e for e in validate_event_payload(payload))

    def test_empty_event_id_rejected(self):
        payload = _good_payload()
        payload["event_id"] = "  "
        assert any("event_id" in e for e in validate_event_payload(payload))

    def test_non_str_run_id_rejected(self):
        payload = _good_payload()
        payload["run_id"] = 42
        assert any("run_id" in e for e in validate_event_payload(payload))

    def test_non_mapping_data_rejected(self):
        payload = _good_payload()
        payload["data"] = [1, 2]
        assert any("data" in e for e in validate_event_payload(payload))

    def test_wrong_schema_version_rejected(self):
        payload = _good_payload()
        payload["schema"] = "rfauto-event/999"
        errs = validate_event_payload(payload)
        assert any("schema" in e for e in errs)

    def test_event_type_enum_instance_accepted(self):
        assert validate_event_payload({"event_type": EventType.ERROR,
                                       "timestamp": 1.0,
                                       "event_id": "x"}) == []


class TestNormalizeEventPayload:
    def test_legacy_gains_schema_and_original_untouched(self):
        legacy = {"event_type": "run_failed", "timestamp": 5.0,
                  "event_id": "e1", "run_id": "r9"}
        out = normalize_event_payload(legacy)
        assert out["schema"] == EVENT_SCHEMA
        assert legacy == {"event_type": "run_failed", "timestamp": 5.0,
                          "event_id": "e1", "run_id": "r9"}  # 零原地改

    def test_enum_event_type_normalized_to_str(self):
        out = normalize_event_payload({"event_type": EventType.ERROR,
                                       "timestamp": 1.0, "event_id": "x"})
        assert out["event_type"] == "error"

    def test_invalid_raises_aggregated(self):
        payload = _good_payload()
        del payload["event_id"]
        payload["timestamp"] = "soon"
        with pytest.raises(EventSchemaError) as ei:
            normalize_event_payload(payload)
        msg = str(ei.value)
        assert "event_id" in msg and "timestamp" in msg  # 清单全量汇总


class TestParseEventLine:
    def test_valid_line(self):
        line = Event(event_type=EventType.CACHE_HIT).to_jsonl()
        assert parse_event_line(line) is not None

    def test_garbage_line_none(self):
        assert parse_event_line("{not json") is None

    def test_empty_and_blank_none(self):
        assert parse_event_line("") is None
        assert parse_event_line("   \n") is None

    def test_non_mapping_json_none(self):
        assert parse_event_line("[1,2,3]") is None

    def test_truncated_half_line_none(self):
        line = Event(event_type=EventType.PROGRESS, run_id="r").to_jsonl()
        assert parse_event_line(line[: len(line) // 2]) is None
