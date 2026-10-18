"""R8 #6 锚 freshness 审计门单测：纯分类逻辑钉行为 + rc 语义 + 伪造样本抓出。

伪造超龄/缺验证样本走合成 records（R8 #6 验收口径"伪造超龄样本抓出"）；
实树测试只钉"现值 ≤ 棘轮"（棘轮语义：计数下降后人工下调，==钉会误伤改善）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit_anchor_freshness as mod
from rfauto.infra.anchors_store import load_anchors

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def _rec(aid: str, status: str, at: str | None = None) -> dict:
    lv = {"at": at, "residual": 0.0} if at else None
    return {"anchor_id": aid, "status": status, "last_verified": lv}


def test_missing_last_verified_flagged_retired_and_awaiting_exempt():
    records = [
        _rec("a.x.fdref-v1", "active", "2026-10-01T00:00:00+00:00"),
        _rec("b.y.closedform-v1", "experimental"),  # 缺验证 → 棘轮面
        _rec("c.z.closedform-v1", "retired"),  # retired 豁免
        _rec("d.w.closedform-v1", "awaiting_data"),  # 预声明语义豁免
    ]
    rep = mod.audit_records(records, NOW, ratchet=1)
    assert rep["missing_last_verified"] == ["b.y.closedform-v1"]
    assert rep["retired"] == 1
    assert rep["status_counts"] == {
        "active": 1, "experimental": 1, "retired": 1, "awaiting_data": 1}
    assert rep["red"] is False  # 1 ≤ 棘轮 1


def test_unparseable_at_counts_as_missing():
    records = [_rec("a.x.fdref-v1", "active", "not-a-date")]
    rep = mod.audit_records(records, NOW, ratchet=0)
    assert rep["missing_last_verified"] == ["a.x.fdref-v1"]
    assert rep["red"] is True
    assert mod.verdict(rep) == 1


def test_naive_timestamp_treated_as_utc_not_missing():
    # naive at 按 UTC 容错，不判"不可解析"
    records = [_rec("a.x.fdref-v1", "active", "2026-10-10T00:00:00")]
    rep = mod.audit_records(records, NOW, ratchet=0)
    assert rep["missing_last_verified"] == []
    assert mod.verdict(rep) == 0


def test_over_age_reported_but_never_red():
    old = (NOW - timedelta(days=40)).isoformat()
    very_old = (NOW - timedelta(days=120)).isoformat()
    records = [
        _rec("exp.old.fdref-v1", "experimental", old),  # >30d experimental
        _rec("act.older.fdref-v1", "active", very_old),  # >90d active
        _rec("act.fresh.fdref-v1", "active",
             (NOW - timedelta(days=5)).isoformat()),  # 新鲜
        _rec("exp.fresh.fdref-v1", "experimental",
             (NOW - timedelta(days=29)).isoformat()),  # 30 天内
    ]
    rep = mod.audit_records(records, NOW, ratchet=0)
    assert [d["anchor_id"] for d in rep["over_age_experimental"]] == [
        "exp.old.fdref-v1"]
    assert [d["anchor_id"] for d in rep["over_age_active"]] == [
        "act.older.fdref-v1"]
    assert rep["red"] is False  # 超龄=报告面，永不红
    assert mod.verdict(rep) == 0


def test_forged_missing_anchor_trips_ratchet():
    # 伪造样本抓出：现值 0 缺验证 + 新增 1 条不带 last_verified → 红
    records = [_rec("a.x.fdref-v1", "active", "2026-10-01T00:00:00+00:00"),
               _rec("forged.new.closedform-v1", "active")]
    rep = mod.audit_records(records, NOW, ratchet=0)
    assert rep["red"] is True
    assert mod.verdict(rep) == 1


def test_verdict_skip_on_error_and_empty():
    assert mod.verdict({"error": "registry 不可读"}) == 2
    assert mod.verdict(mod.audit_records([], NOW, ratchet=0)) == 2


def test_parse_ts_z_suffix_and_none():
    assert mod._parse_ts("2026-10-01T00:00:00Z").tzinfo is not None
    assert mod._parse_ts(None) is None
    assert mod._parse_ts("") is None


def test_record_to_dict_shape():
    fake = SimpleNamespace(anchor_id="a.x.fdref-v1", status="active",
                           last_verified={"at": "2026-10-01", "residual": 0.0})
    d = mod._record_to_dict(fake)
    rep = mod.audit_records([d], NOW, ratchet=0)
    assert rep["missing_last_verified"] == []


def test_real_tree_baseline_within_ratchet():
    # 实树现值基线：缺验证 ≤ 棘轮（绿色）；超龄计数与 JSON 证据面一致口径
    anchor_set = load_anchors(force_reload=True)
    records = [mod._record_to_dict(r) for r in anchor_set.records]
    rep = mod.audit_records(records, datetime.now(timezone.utc),
                            ratchet=mod.FRESH_RATCHET_MISSING)
    assert rep["total"] == 79  # 单源口径：core EXPECTED_ANCHOR_COUNT 同值（W3-S15 批 75→79 沿革）
    assert len(rep["missing_last_verified"]) <= rep["ratchet"]
    assert mod.verdict(rep) == 0


def test_main_rc0_and_json(tmp_path, monkeypatch):
    out = tmp_path / "rep.json"
    rc = mod.main(["--json", str(out), "--registry",
                   str(_write_tmp_registry(tmp_path))])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == mod.REPORT_SCHEMA
    assert data["total"] == 1


def _write_tmp_registry(tmp_path: Path) -> Path:
    """最小合法 anchors.yaml（constant 锚带 last_verified）→ loader 可读。"""
    p = tmp_path / "anchors.yaml"
    p.write_text(
        "schema: anchors/v1\n"
        "anchors:\n"
        "  - anchor_id: tiny.x.openems-v1\n"
        "    kind: constant\n"
        "    status: active\n"
        "    value: 1.0\n"
        "    quantity: {name: x, unit: ohm}\n"
        "    last_verified: {at: '2026-10-01T00:00:00+00:00', residual: 0.0}\n",
        encoding="utf-8")
    return p


def test_main_rc2_on_missing_registry(tmp_path):
    rc = mod.main(["--registry", str(tmp_path / "nope.yaml")])
    assert rc == 2


def test_main_rc1_on_forged_unverified(tmp_path, monkeypatch):
    p = tmp_path / "anchors.yaml"
    p.write_text(
        "schema: anchors/v1\n"
        "anchors:\n"
        "  - anchor_id: tiny.x.openems-v1\n"
        "    kind: constant\n"
        "    status: active\n"
        "    value: 1.0\n"
        "    quantity: {name: x, unit: ohm}\n",
        encoding="utf-8")
    # 棘轮为模块常量 35；单条缺验证本不至于红——用 monkeypatch 收紧棘轮
    # 模拟"现值基线=0"的注册表，验证 main 链路 red → rc 1
    monkeypatch.setattr(mod, "FRESH_RATCHET_MISSING", 0)
    rc = mod.main(["--registry", str(p)])
    assert rc == 1
