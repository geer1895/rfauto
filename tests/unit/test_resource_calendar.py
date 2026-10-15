"""资源日历机读化单测（UX-B8/E62 席 2026-10-08）。

全离线零网络：窗判定是纯函数（固定钟注入），文件装载走 tmp_path 与
仓内 configs/resource_calendar.yaml（schema 钉）。
覆盖：HH:MM 解析/跨午夜环绕窗判定、装载 fail-open（缺文件/非法 YAML/
顶层非映射=恒可发降级）、非法条目跳过记 warning 不整文件拒载、
calendar_launch_view 三态（open/risk/blocked——维护窗优先于备份窗、
许可峰谷标注面不进门）、calendar_view 信封（ok 恒 True 首键）、
resources_view 消费日历输出 launchable 字段。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_scheduler_service as rss
from rfauto.service.remote_scheduler_service import (
    CALENDAR_SCHEMA,
    _parse_hhmm,
    _peak_span,
    _window_bounds,
    _window_contains,
    calendar_launch_view,
    calendar_view,
    load_resource_calendar,
)

REPO = Path(__file__).resolve().parents[2]


def _clock(hh: int, mm: int = 0):
    return lambda: time.struct_time(
        (2026, 10, 8, hh, mm, 0, 2, 281, 0))


def _write_calendar(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "resource_calendar.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# ─── 解析原语 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("02:50", 170), ("5:35", 335), ("24:00", 1440), (" 10:00 ", 600),
    ("", None), ("25:00", None), ("12:60", None), ("bad", None),
    (None, None), (170, None),
])
def test_parse_hhmm(raw, expect):
    assert _parse_hhmm(raw) == expect


def test_window_bounds_and_wraparound():
    assert _window_bounds({"start": "02:50", "end": "05:35"}) == (170, 335)
    assert _window_bounds({"start": "23:00", "end": "02:00"}) == (1380, 120)
    assert _window_bounds({"start": "x", "end": "05:35"}) is None
    assert _window_bounds("02:50-05:35") is None  # 必须是 {start,end}
    # 环绕窗判定：23:00-02:00 命中 23:30/01:00，不命中 12:00
    wrap = _window_bounds({"start": "23:00", "end": "02:00"})
    assert _window_contains(wrap, 23 * 60 + 30)
    assert _window_contains(wrap, 60)
    assert not _window_contains(wrap, 12 * 60)
    # 闭区间边界
    assert _window_contains((170, 335), 170)
    assert _window_contains((170, 335), 335)
    assert not _window_contains((170, 335), 336)


def test_peak_span_string_form():
    assert _peak_span("10:00-12:00") == (600, 720)
    assert _peak_span(" 14:00 - 18:00 ") == (840, 1080)
    assert _peak_span("bad") is None
    assert _peak_span({"start": "10:00", "end": "12:00"}) is None  # 字符串形态专用


# ─── 装载（fail-open #105） ─────────────────────────────────────────────────

def test_load_missing_file_fails_open(tmp_path):
    cal = load_resource_calendar(tmp_path / "nope.yaml")
    assert cal["ok"] is True and cal["loaded"] is False
    assert "恒可发" in cal["reason"]


def test_load_broken_yaml_fails_open(tmp_path):
    p = _write_calendar(tmp_path, "backup_windows: [ {start: 02:50, end\n")
    cal = load_resource_calendar(p)
    assert cal["loaded"] is False and cal["ok"] is True
    assert "降级恒可发" in cal["reason"]


def test_load_top_level_not_mapping_fails_open(tmp_path):
    p = _write_calendar(tmp_path, "- a\n- b\n")
    cal = load_resource_calendar(p)
    assert cal["loaded"] is False and cal["ok"] is True


def test_load_repo_calendar_schema_and_windows():
    cal = load_resource_calendar()  # 仓内缺省 configs/resource_calendar.yaml
    assert cal["loaded"] is True
    assert cal["schema"] == CALENDAR_SCHEMA
    assert cal["backup_windows"] == [(170, 335)]  # 02:50-05:35 机读化单源
    assert cal["license_peaks"]["hfss"] == (600, 720)
    assert cal["machine_caps"]["sim_host"]["memory_gb"] == 80
    assert cal["warnings"] == []


def test_load_invalid_entries_skipped_with_warning(tmp_path):
    p = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
backup_windows:
  - {{start: "02:50", end: "05:35"}}
  - {{start: "bad", end: "06:00"}}
maintenance_windows:
  - "not-a-mapping"
license_seats:
  hfss:
    peak: "10:00-12:00"
  ads:
    peak: "junk"
machine_caps:
  sim_host:
    memory_gb: 80
""")
    cal = load_resource_calendar(p)
    assert cal["loaded"] is True
    assert cal["backup_windows"] == [(170, 335)]
    assert len(cal["warnings"]) == 3  # 非法备份窗+非映射维护窗+非法峰谷
    assert cal["license_peaks"] == {"hfss": (600, 720)}


def test_load_schema_mismatch_warns_but_loads(tmp_path):
    p = _write_calendar(tmp_path, 'schema: future-v9\nbackup_windows: []\n')
    cal = load_resource_calendar(p)
    assert cal["loaded"] is True
    assert any("future-v9" in w for w in cal["warnings"])


# ─── 三态判定 ────────────────────────────────────────────────────────────────

def test_launch_view_missing_calendar_always_open(tmp_path):
    v = calendar_launch_view(now_fn=_clock(3, 0),
                             path=tmp_path / "nope.yaml")
    assert v["state"] == "open" and v["launchable"] is True
    assert "恒可发" in v["reason"] and v["loaded"] is False


def test_launch_view_backup_window_is_risk(tmp_path):
    p = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
backup_windows:
  - {{start: "02:50", end: "05:35"}}
""")
    v = calendar_launch_view(now_fn=_clock(3, 0), path=p)
    assert v["state"] == "risk" and v["launchable"] is True
    assert v["backup_risk"] is True
    assert v["windows_hit"] == ["backup_windows[0] 02:50-05:35"]
    # 窗外（05:36）回 open
    v2 = calendar_launch_view(now_fn=_clock(5, 36), path=p)
    assert v2["state"] == "open" and v2["backup_risk"] is False


def test_launch_view_maintenance_window_blocks_and_dominates(tmp_path):
    p = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
backup_windows:
  - {{start: "00:00", end: "23:59"}}
maintenance_windows:
  - {{start: "03:00", end: "04:00"}}
""")
    v = calendar_launch_view(now_fn=_clock(3, 30), path=p)
    assert v["state"] == "blocked" and v["launchable"] is False
    assert "维护窗" in v["reason"]
    # 同刻仅备份窗覆盖（维护窗外）→ risk
    p2 = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
backup_windows:
  - {{start: "02:50", end: "05:35"}}
maintenance_windows:
  - {{start: "06:00", end: "07:00"}}
""")
    v2 = calendar_launch_view(now_fn=_clock(3, 0), path=p2)
    assert v2["state"] == "risk" and v2["launchable"] is True


def test_launch_view_wraparound_maintenance(tmp_path):
    p = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
maintenance_windows:
  - {{start: "23:00", end: "02:00"}}
""")
    assert calendar_launch_view(now_fn=_clock(23, 30), path=p)["state"] == "blocked"
    assert calendar_launch_view(now_fn=_clock(1, 0), path=p)["state"] == "blocked"
    assert calendar_launch_view(now_fn=_clock(12, 0), path=p)["state"] == "open"


def test_launch_view_license_peak_is_annotation_only(tmp_path):
    p = _write_calendar(tmp_path, f"""schema: {CALENDAR_SCHEMA}
license_seats:
  hfss:
    peak: "10:00-12:00"
""")
    v = calendar_launch_view(now_fn=_clock(11, 0), path=p)
    assert v["state"] == "open" and v["launchable"] is True  # 标注面不进门


def test_launch_view_injected_calendar_reuse(tmp_path):
    cal = load_resource_calendar()
    v = calendar_launch_view(now_fn=_clock(3, 0), calendar=cal)
    assert v["state"] == "risk"  # 仓内日历备份窗命中（复用装载零二次读盘）


# ─── 信封与消费面 ────────────────────────────────────────────────────────────

def test_calendar_view_envelope_contract(tmp_path):
    env = calendar_view(now_fn=_clock(3, 0),
                        path=tmp_path / "nope.yaml")
    assert next(iter(env)) == "ok" and env["ok"] is True  # 缺文件不翻 ok
    assert env["launch"]["state"] == "open"
    assert env["calendar"]["loaded"] is False
    env2 = calendar_view(now_fn=_clock(3, 0))
    assert env2["ok"] is True
    assert env2["calendar"]["backup_windows"] == [
        {"start": "02:50", "end": "05:35"}]
    assert env2["calendar"]["license_peaks"]["hfss"] == {
        "start": "10:00", "end": "12:00"}
    assert env2["calendar"]["machine_caps"]["sim_host"] == {"memory_gb": 80}


def test_resources_view_carries_calendar(monkeypatch):
    """resources_view 消费日历：「当前是否可发」字段随信封（UX-B8 消费口）。"""
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    monkeypatch.setattr(rss, "_ps_capture",
                        lambda cmd, timeout_s=30.0: (True, ""))
    monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
    env = rss.resources_view(None)
    assert env["ok"] is True
    assert env["calendar"]["launchable"] is True
    assert env["calendar"]["state"] in ("open", "risk")  # 仓内日历无维护窗


def test_launch_view_json_serializable():
    v = calendar_launch_view(now_fn=_clock(3, 0))
    json.dumps(v, ensure_ascii=False)  # 机读化：信封可直落 JSON
