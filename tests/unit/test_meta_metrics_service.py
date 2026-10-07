"""MT2-1（round19 P2）meta_metrics 采集/周报/sampler 单元测试。

判据预声明（全合成，tmp_path 隔离——#144 防污染真实 runs）：

1. **快照算术恒等**（基准①）：test_count=passed+failed+skipped、
   pass_rate=passed/(passed+failed)（逐条可复算）；分母 0 → None 如实；
2. **JSONL 存储恒等**：写后读回逐字段一致；追加语义（第二次写不覆盖）；
3. **漂移内核复用**（基准②）：上升时长序列 → duration drift verdict
   ∈ {warning, drifted}、平稳通过率 → stable（anchor_drift 语义）；
4. **sampler 确定性**：同 (seed,k) 重放逐位一致；k>n 全量返回；重复
   id 如实拒绝；gold 恒 None（UNVERIFIED 如实，不跑全量——三禁）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.meta_metrics_service import (
    metrics_drift_report,
    metrics_series,
    metrics_weekly_report,
    select_smoke_subset,
    snapshot_gate_metrics,
)


def _snap(gate: str, passed: int, failed: int = 0, duration: float = 1.0,
          at: str | None = None, **extra) -> dict:
    p = {"gate": gate, "passed": passed, "failed": failed,
         "duration_s": duration}
    if at:
        p["at"] = at
    p.update(extra)
    return p


@pytest.fixture()
def store(tmp_path):
    return tmp_path / "meta_metrics"


class TestSnapshotCollector:
    def test_arithmetic_identity_and_roundtrip(self, store):
        """基准①+②：写后读回逐字段一致，派生键恒等。"""
        rep = snapshot_gate_metrics(_snap("gate_full", 100, 5, 1200.5,
                                          at="2026-10-03T00:00:00+00:00"),
                                    store)
        assert rep["ok"] is True
        rec = rep["snapshot"]
        assert rec["test_count"] == 105
        assert rec["pass_rate"] == pytest.approx(100 / 105, rel=1e-12)
        idx = [json.loads(line) for line in
               (store / "index.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(idx) == 1 and idx[0] == rec
        gser = [json.loads(line) for line in
                (store / "gates" / "gate_full.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        assert gser == idx

    def test_append_not_overwrite(self, store):
        snapshot_gate_metrics(_snap("g", 10, 0, at="a1"), store)
        snapshot_gate_metrics(_snap("g", 12, 1, at="a2"), store)
        ser = metrics_series(store, "passed", gate="g")
        assert ser["values"] == [10.0, 12.0]
        assert ser["ats"] == ["a1", "a2"]

    def test_zero_denominator_pass_rate_none(self, store):
        rep = snapshot_gate_metrics(_snap("g", 0, 0, at="a1"), store)
        assert rep["ok"] is True and rep["snapshot"]["pass_rate"] is None
        ser = metrics_series(store, "pass_rate")
        assert ser["values"] == [] and ser["missing_points"] == 1

    def test_missing_out_dir_and_bad_gate_honest(self, tmp_path):
        assert snapshot_gate_metrics(_snap("g", 1), "")["ok"] is False
        assert snapshot_gate_metrics(_snap("", 1), tmp_path)["ok"] is False
        assert snapshot_gate_metrics(_snap("g", -1), tmp_path)["ok"] is False

    def test_unknown_key_honest(self, store):
        assert metrics_series(store, "nope")["ok"] is False


class TestDriftAndWeekly:
    def _feed(self, store):
        # 通过率恒稳；时长单调上升（构造使然的漂移方向）
        for i in range(10):
            snapshot_gate_metrics(_snap("gate_full", 100, 0,
                                        duration=1.0 + i,
                                        at=f"2026-10-0{i + 1}"), store)
        for i in range(6):
            snapshot_gate_metrics(_snap("gate_smoke", 20, 0, duration=0.5,
                                        at=f"2026-10-0{i + 1}"), store)

    def test_duration_drift_detected(self, store):
        """基准②：线性上升时长 → MK 趋势 → 非 stable verdict。"""
        self._feed(store)
        rep = metrics_drift_report(store, "duration_s", gate="gate_full")
        assert rep["ok"] is True
        assert rep["n_points"] == 10
        assert rep["drift"]["verdict"] in ("warning", "drifted")

    def test_stable_pass_rate_stable(self, store):
        self._feed(store)
        rep = metrics_drift_report(store, "pass_rate", gate="gate_full")
        assert rep["drift"]["verdict"] == "stable"

    def test_weekly_report_per_gate(self, store):
        self._feed(store)
        rep = metrics_weekly_report(store, window=5)
        assert rep["ok"] is True
        gates = {r["gate"]: r for r in rep["per_gate"]}
        assert set(gates) == {"gate_full", "gate_smoke"}
        assert gates["gate_smoke"]["n_snapshots"] == 5  # window 截断
        assert gates["gate_full"]["latest"]["pass_rate"] == 1.0
        assert len([line for line in rep["lines"]
                    if line.startswith("- ")]) == 2

    def test_weekly_missing_index_honest(self, tmp_path):
        assert metrics_weekly_report(tmp_path / "none")["ok"] is False


class TestSmokeSubsetSelector:
    def test_deterministic_replay(self):
        ids = [f"tests/unit/test_m{i}.py::test_a" for i in range(50)]
        a = select_smoke_subset(ids, 10, seed=7)
        b = select_smoke_subset(ids, 10, seed=7)
        assert a["subset"] == b["subset"]
        assert len(a["subset"]) == 10
        assert set(a["subset"]) | set(a["excluded"]) == set(ids)

    def test_seed_changes_subset(self):
        ids = [f"t{i}" for i in range(30)]
        a = select_smoke_subset(ids, 10, seed=1)["subset"]
        b = select_smoke_subset(ids, 10, seed=2)["subset"]
        assert a != b

    def test_k_exceeds_n_returns_all(self):
        rep = select_smoke_subset(["a", "b"], 10)
        assert rep["subset"] == ["a", "b"] and rep["excluded"] == []
        assert rep["meta"]["k"] == 2

    def test_duplicate_ids_rejected(self):
        assert select_smoke_subset(["a", "a"], 1)["ok"] is False
        assert select_smoke_subset(["a"], -1)["ok"] is False

    def test_gold_unverified_honest(self):
        """三禁口径：不跑全量 → gold 恒 None，登记 UNVERIFIED。"""
        rep = select_smoke_subset(["a", "b", "c"], 2)
        assert rep["gold"] is None
        assert "UNVERIFIED" in rep["gold_note"]
