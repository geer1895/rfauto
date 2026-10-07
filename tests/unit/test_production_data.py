"""PT-7 产线测试数据 schema/Pareto 单测（core/production_data + service 面期望端到端测试指南）。

裁判独立性（#118）：Pareto 排序/累计占比用测试侧独立重排对拍；判定规则
用手工边界值表；JSON 往返用 json.dumps/loads 全链。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import production_data as pd
from rfauto.service import production_service as ps


def _rec(dut: str, lot: str, item: str, measured: float, *, usl=None, lsl=None, **kw):
    base = {
        "dut_id": dut,
        "lot_id": lot,
        "test_item": item,
        "measured": measured,
        "limits": {"usl": usl, "lsl": lsl},
    }
    base.update(kw)
    return base


class TestNormalizeRecord:
    def test_limit_judge_boundaries_inclusive(self):
        # 边界含端点：measured==usl / ==lsl 均判 pass
        r = pd.normalize_record(_rec("D1", "L1", "s11_db", -10.0, usl=-10.0, lsl=-30.0))
        assert r["verdict"] == "pass"
        r2 = pd.normalize_record(_rec("D1", "L1", "s11_db", -30.0, usl=-10.0, lsl=-30.0))
        assert r2["verdict"] == "pass"
        r3 = pd.normalize_record(_rec("D1", "L1", "s11_db", -9.9, usl=-10.0))
        assert r3["verdict"] == "fail"

    def test_single_sided_limits(self):
        assert pd.normalize_record(_rec("D", "L", "il_db", 1.2, usl=1.5))["verdict"] == "pass"
        assert pd.normalize_record(_rec("D", "L", "il_db", 1.6, usl=1.5))["verdict"] == "fail"
        assert pd.normalize_record(_rec("D", "L", "power_w", 3.0, lsl=2.5))["verdict"] == "pass"
        assert pd.normalize_record(_rec("D", "L", "power_w", 2.0, lsl=2.5))["verdict"] == "fail"

    def test_conflicting_reported_verdict_recomputed_with_disclosure(self):
        # 传入 verdict=pass 但限值判 fail：以限值为准 + 两值披露（#122 不静默）
        r = pd.normalize_record(
            _rec("D", "L", "s11_db", -5.0, usl=-10.0, verdict="pass")
        )
        assert r["verdict"] == "fail"
        assert r["verdict_source"] == "recomputed"
        assert r["verdict_reported"] == "pass"

    def test_invalid_verdict_bypasses_limits(self):
        r = pd.normalize_record(_rec("D", "L", "s11_db", -5.0, usl=-10.0, verdict="invalid"))
        assert r["verdict"] == "invalid"
        assert r["verdict_source"] == "reported"

    def test_input_guards(self):
        with pytest.raises(ValueError):
            pd.normalize_record(_rec("", "L", "i", 0.0, usl=1.0))  # 空 dut_id
        with pytest.raises(ValueError):
            pd.normalize_record(_rec("D", "L", "i", True, usl=1.0))  # bool 实测
        with pytest.raises(ValueError, match="至少一侧"):
            pd.normalize_record(_rec("D", "L", "i", 0.0))  # 两侧全缺
        with pytest.raises(ValueError, match="lsl 不得超过"):
            pd.normalize_record(_rec("D", "L", "i", 0.0, usl=-5.0, lsl=5.0))
        with pytest.raises(ValueError, match="只接受"):
            pd.normalize_record(_rec("D", "L", "i", 0.0, usl=1.0, verdict="maybe"))
        with pytest.raises(ValueError):
            pd.normalize_record("not-a-dict")

    def test_optional_keys_carried(self):
        r = pd.normalize_record(
            _rec("D", "L", "esr_ohm", 0.012, usl=0.02,
                 units="ohm", vendor_part="GRM188", batch="B2026W40")
        )
        assert r["units"] == "ohm"
        assert r["vendor_part"] == "GRM188"
        assert r["batch"] == "B2026W40"
        assert r["schema"] == "rfauto-production-record/v1"


class TestFailurePareto:
    def test_ordering_and_cumulative_vs_independent_resort(self):
        records = [
            *[_rec(f"D{i}", "L1", "s11_db", 0.0, usl=-1.0) for i in range(5)],  # 5 fail
            *[_rec(f"D{i}", "L1", "il_db", 2.0, usl=1.0) for i in range(9, 13)],  # 4 fail
            *[_rec(f"D{i}", "L1", "power_w", 3.0, lsl=2.5) for i in range(13, 15)],  # 2 pass
            *[_rec(f"D{i}", "L1", "esr_ohm", 0.0, usl=0.02, verdict="invalid") for i in range(15, 17)],
        ]
        out = pd.failure_pareto(records)
        assert out["n_records"] == 13
        assert out["n_invalid"] == 2
        assert out["total_fail"] == 9
        # 独立重排裁判：(-count, name) 全键序
        counts = {"s11_db": 5, "il_db": 4}
        expect_order = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        got = [(it["test_item"], it["fail_count"]) for it in out["items"]]
        assert got == expect_order
        # 累计占比：首项 5/9、次项累计 9/9
        assert abs(out["items"][0]["cumulative_pct"] - 100.0 * 5 / 9) <= 1e-12
        assert abs(out["items"][1]["cumulative_pct"] - 100.0) <= 1e-12
        # invalid 不进分子分母
        assert all(it["test_item"] != "esr_ohm" for it in out["items"])

    def test_tie_break_by_name(self):
        records = [
            *[_rec("D1", "L", "b_item", 2.0, usl=1.0)],
            *[_rec("D2", "L", "a_item", 2.0, usl=1.0)],
        ]
        out = pd.failure_pareto(records)
        assert [it["test_item"] for it in out["items"]] == ["a_item", "b_item"]

    def test_no_fail_returns_empty_items(self):
        out = pd.failure_pareto([_rec("D1", "L", "i", 0.0, usl=1.0)])
        assert out["items"] == []
        assert out["total_fail"] == 0


class TestLotYieldAndVendorBatches:
    def test_lot_yield_excludes_invalid(self):
        records = [
            _rec("D1", "L1", "i", 0.0, usl=1.0),
            _rec("D2", "L1", "i", 2.0, usl=1.0),
            _rec("D3", "L1", "i", 0.0, usl=1.0, verdict="invalid"),
            _rec("D4", "L2", "i", 0.0, usl=1.0),
        ]
        out = pd.lot_yield(records)
        by_lot = {it["lot_id"]: it for it in out["lots"]}
        assert by_lot["L1"]["n_pass"] == 1
        assert by_lot["L1"]["n_fail"] == 1
        assert by_lot["L1"]["n_invalid"] == 1
        assert abs(by_lot["L1"]["yield_pct"] - 50.0) <= 1e-12
        assert abs(by_lot["L2"]["yield_pct"] - 100.0) <= 1e-12

    def test_vendor_batch_grouping_and_unkeyed_disclosure(self):
        records = [
            _rec("D1", "L1", "esr", 0.03, usl=0.02, vendor_part="GRM", batch="B1"),
            _rec("D2", "L1", "esr", 0.01, usl=0.02, vendor_part="GRM", batch="B1"),
            _rec("D3", "L1", "esr", 0.03, usl=0.02),  # 缺批次键
        ]
        out = pd.vendor_batch_summary(records)
        assert out["n_unkeyed"] == 1
        assert len(out["groups"]) == 1
        g = out["groups"][0]
        assert (g["vendor_part"], g["batch"]) == ("GRM", "B1")
        assert g["n_fail"] == 1
        assert abs(g["fail_rate"] - 0.5) <= 1e-12


class TestServiceFace:
    def test_envelope_and_bare_list(self):
        rows = [_rec("D1", "L1", "i", 0.0, usl=1.0)]
        assert len(ps.records_from_payload({"records": rows})) == 1
        assert len(ps.records_from_payload(rows)) == 1
        with pytest.raises(ValueError, match="records 键"):
            ps.records_from_payload({"rows": rows})

    def test_json_roundtrip_and_overview(self):
        rows = [
            _rec("D1", "L1", "s11_db", -5.0, usl=-10.0, units="dB"),
            _rec("D2", "L1", "s11_db", -18.0, usl=-10.0, units="dB"),
            _rec("D3", "L1", "s11_db", -5.0, usl=-10.0, units="dB", verdict="invalid"),
        ]
        blob = json.loads(json.dumps(rows))  # JSON 往返
        overview = ps.production_overview(blob)
        assert overview["schema"] == "rfauto-production-record/v1"
        assert overview["pareto"]["total_fail"] == 1
        assert overview["pareto"]["n_invalid"] == 1
        assert overview["lot_yield"]["lots"][0]["n_pass"] == 1
        assert overview["vendor_batches"]["n_unkeyed"] == 3

    def test_load_json_records(self, tmp_path):
        p = tmp_path / "prod.json"
        p.write_text(
            json.dumps([_rec("D1", "L1", "i", 0.0, usl=1.0)]),
            encoding="utf-8",
        )
        rows = ps.load_json_records(p)
        assert rows[0]["verdict"] == "pass"
        # 非信封裸 dict 文件 → ValueError（信封缺键如实）
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"rows": []}), encoding="utf-8")
        with pytest.raises(ValueError):
            ps.load_json_records(bad)
