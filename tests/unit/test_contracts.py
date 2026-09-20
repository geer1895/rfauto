"""阶段 4.2：service 契约 pydantic 模型测试——真服务输出回验。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestContractsAgainstRealOutputs:
    def test_calibration_output_validates(self, recipe_path):
        from rfauto.service.calibration_service import calibrate_surrogate
        from rfauto.service.contracts import CalibrationPayload, contract_version

        result = calibrate_surrogate(recipe_path, sampler="fake",
                                     n_validation=0)
        assert result["ok"]
        ok, errors, model = CalibrationPayload.validate(result)
        assert ok, errors
        assert model.verdict in ("PASS", "FAIL")
        assert model.loocv.ok is True
        assert contract_version() >= 2

    def test_autotune_output_validates(self, recipe_path):
        from rfauto.service.autotune_service import autotune_loop
        from rfauto.service.contracts import AutotunePayload

        def sampler(params):
            return {"metrics": {"s11_db_max_in_band": -20.0},
                    "valley_ghz": 2.4}

        r = autotune_loop(recipe_path, sampler_fn=sampler, budget=2)
        ok, errors, model = AutotunePayload.validate(r)
        assert ok, errors
        assert model.verdict == "PASS"
        assert model.rounds_used == 1
        assert model.history[0].verdict == "PASS"

    def test_uq_output_validates(self, tmp_path):
        import numpy as np

        from rfauto.service.contracts import UQYieldPayload
        from rfauto.service.uq_service import surrogate_yield

        rng = np.random.default_rng(3)
        bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
        samples = []
        for _ in range(25):
            p = {"arm_len_mm": float(rng.uniform(*bounds["arm_len_mm"])),
                 "series_w_mm": float(rng.uniform(*bounds["series_w_mm"]))}
            s11 = -20.0 + 5.0 * (p["arm_len_mm"] - 20.0) ** 2 + 10.0 * (
                p["series_w_mm"] - 0.35) ** 2
            samples.append({"params": p,
                            "metrics": {"s11_db_max_in_band": float(s11)}})
        samples[0] = {"params": {"arm_len_mm": 20.0, "series_w_mm": 0.35},
                      "metrics": {"s11_db_max_in_band": -20.0}}
        data = {"bounds": bounds,
                "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                                "op": "max_below", "value": -15}],
                "samples": samples}
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        r = surrogate_yield(path, {"arm_len_mm": 0.1}, n=1000, seed=1)
        ok, errors, model = UQYieldPayload.validate(r)
        assert ok, errors
        assert 0.0 <= model.yield_rate <= 1.0

    def test_runs_summary_validates(self, tmp_path):
        from rfauto.infra.run_store import record_run
        from rfauto.service.contracts import RunsSummaryPayload
        from rfauto.service.runs_stats import runs_summary

        db = tmp_path / "index.db"
        record_run(db, {"run_id": "r1", "model": "wilkinson_power_divider",
                        "adapter": "fake", "status": "done",
                        "timestamp": "2026-09-05 01:00:00",
                        "metrics": {"rho": 0.8}})
        r = runs_summary(db)
        ok, errors, model = RunsSummaryPayload.validate(r)
        assert ok, errors
        assert model.total == 1

    def test_cross_gate_validates(self, tmp_path, recipe_path):
        from rfauto.service.contracts import CrossGatePayload
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        costs = [-10.0 + i for i in range(10)]
        samples = [{"params": {"arm_len_mm": 18.0 + i * 0.4},
                    "metrics": {"s11_db_max_in_band": c}}
                   for i, c in enumerate(costs)]
        data = {"bounds": {"arm_len_mm": [18.0, 23.0]},
                "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                                "op": "max_below", "value": -15}],
                "samples": samples}
        asset = tmp_path / "samples.json"
        asset.write_text(json.dumps(data), encoding="utf-8")
        fake_costs = {18.0 + i * 0.4: c for i, c in enumerate(costs)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        ok, errors, model = CrossGatePayload.validate(r)
        assert ok, errors
        assert model.verdict == "PASS"

    def test_cross_gate_recall_none_small_n_validates(self, tmp_path, recipe_path):
        """P2②：n<8 时 top5_recall=None（恒 1 退化，#195 同族）——契约扩
        float|None 后该合法路径不再触发契约违约。"""
        from rfauto.service.contracts import CrossGatePayload
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        costs = [-10.0 + i for i in range(6)]  # 6 对 < 8 → recall 置 None
        samples = [{"params": {"arm_len_mm": 18.0 + i * 0.4},
                    "metrics": {"s11_db_max_in_band": c}}
                   for i, c in enumerate(costs)]
        data = {"bounds": {"arm_len_mm": [18.0, 23.0]},
                "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                                "op": "max_below", "value": -15}],
                "samples": samples}
        asset = tmp_path / "samples_small_n.json"
        asset.write_text(json.dumps(data), encoding="utf-8")
        fake_costs = {18.0 + i * 0.4: c for i, c in enumerate(costs)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"], r.get("errors")
        assert r["top5_recall"] is None  # p0_gate_service 2d68012 已置 None
        ok, errors, model = CrossGatePayload.validate(r)
        assert ok, errors
        assert model.top5_recall is None
        assert model.spearman_rho is not None  # spearman_rho 登记范围冻结，仍必填


class TestContractWiring:
    """4.2 全量接线：服务点 annotate_contract best-effort 注记。"""

    def test_annotate_ok_and_violation(self):
        from rfauto.service.contracts import annotate_contract

        good = {"ok": True, "run_id": "r1", "run_dir": "runs/r1",
                "files": [], "sparams": [], "figs": []}
        out = annotate_contract("run_detail", good)
        assert out["contract_check"]["ok"] is True
        assert out["contract_check"]["contract"] == "run_detail"
        assert out["contract_check"]["schema_version"] >= 2

        bad = {"ok": {"violating": True}, "run_id": "r1"}  # dict 不能强转 bool
        out2 = annotate_contract("run_detail", bad)
        assert out2["contract_check"]["ok"] is False
        assert out2["contract_check"]["errors"]

    def test_annotate_unknown_and_nondict_passthrough(self):
        from rfauto.service.contracts import annotate_contract

        payload = ["not", "a", "dict"]
        assert annotate_contract("run_detail", payload) is payload
        marker = {"ok": True}
        assert annotate_contract("no_such_contract", marker) is marker
        assert "contract_check" not in marker

    def test_run_detail_via_service_validates(self, tmp_path):
        """真实 run_detail 输出（含产物树）过 RunDetailPayload 契约。"""
        from rfauto.infra.run_store import create_run_dir, write_meta
        from rfauto.service import ui_service
        from rfauto.service.contracts import RunDetailPayload, annotate_contract

        monkey = pytest.MonkeyPatch()
        monkey.chdir(tmp_path)
        try:
            run_dir = create_run_dir(Path(".").resolve(), "20260101_000000_ct")
            write_meta(run_dir, {"run_id": "20260101_000000_ct",
                                 "model": "wilkinson_power_divider",
                                 "adapter": "fake", "status": "done"})
            d = ui_service.run_detail("20260101_000000_ct")
            d = annotate_contract("run_detail", d)
            assert d["contract_check"]["ok"], d["contract_check"]["errors"]
            ok, errors, _ = RunDetailPayload.validate(d)
            assert ok, errors
        finally:
            monkey.undo()

    def test_sparams_and_reports_contracts(self, tmp_path):
        """3.1/3.5 新端点形状过契约（真服务输出回验，含错误路径）。"""
        from rfauto.service import ui_service
        from rfauto.service.contracts import (
            CostTimelinePayload,
            ReportsListPayload,
            SparamsSeriesPayload,
            annotate_contract,
        )

        monkey = pytest.MonkeyPatch()
        monkey.chdir(tmp_path)
        try:
            # 无 runs/ 目录的空形状也要过契约（ok + 缺省列表）
            tl = annotate_contract("cost_timeline", ui_service.cost_timeline())
            assert tl["contract_check"]["ok"], tl["contract_check"]["errors"]
            rp = annotate_contract("reports_list", ui_service.list_reports())
            assert rp["contract_check"]["ok"], rp["contract_check"]["errors"]
            # 错误路径（run 不存在）形状同样过契约
            sp = annotate_contract(
                "sparams_series", ui_service.sparams_series("ghost_run"))
            assert sp["contract_check"]["ok"], sp["contract_check"]["errors"]
            for payload, cls in ((sp, SparamsSeriesPayload),
                                 (rp, ReportsListPayload),
                                 (tl, CostTimelinePayload)):
                ok, errors, _ = cls.validate(payload)
                assert ok, errors
        finally:
            monkey.undo()
