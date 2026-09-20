"""P1 收尾基建单测：watchdog 退避、SQLite runs 索引、replay 版本核对。"""

from __future__ import annotations

import json

from rfauto.infra.run_store import list_runs, record_run
from rfauto.pipeline.watchdog import Watchdog


class TestLicenseBackoff:
    """watchdog R4：license 释放感知的延迟退避。"""

    def test_backoff_is_exponential_and_bounded(self):
        delays = [Watchdog.license_backoff(a, base_delay=1.0, max_delay=60.0, jitter=0.0)
                  for a in range(8)]
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0
        # 指数增长但封顶于 max_delay（1*2^6=64 → 60）
        assert delays[5] == 32.0
        assert delays[6] == 60.0
        assert delays[7] == 60.0

    def test_backoff_with_jitter_stays_bounded(self):
        for _ in range(20):
            d = Watchdog.license_backoff(3, base_delay=1.0, max_delay=10.0, jitter=0.1)
            assert 8.0 <= d <= 10.0 + 8.0 * 0.1 + 1e-9


class TestRunsIndex:
    """SQLite runs 索引（单一运行索引，runs/ 不入 git）。"""

    def test_record_and_list(self, tmp_path):
        db = tmp_path / "index.db"
        assert record_run(db, {
            "run_id": "r1", "model": "wilkinson_power_divider",
            "adapter": "fake", "status": "done",
            "timestamp": "2026-08-29T00:00:00Z",
            "metrics": {"s11_db_max_in_band": -10.5},
        })
        assert record_run(db, {
            "run_id": "r2", "model": "wilkinson_power_divider",
            "adapter": "hfss", "status": "done",
            "timestamp": "2026-08-29T01:00:00Z",
            "metrics": {"s11_db_max_in_band": -14.7},
        })
        rows = list_runs(db)
        assert len(rows) == 2
        # 最新在前
        assert rows[0]["run_id"] == "r2"
        assert rows[0]["metrics"]["s11_db_max_in_band"] == -14.7
        assert rows[1]["adapter"] == "fake"

    def test_upsert_same_run_id(self, tmp_path):
        db = tmp_path / "index.db"
        record_run(db, {"run_id": "r1", "status": "running"})
        record_run(db, {"run_id": "r1", "status": "done"})
        rows = list_runs(db)
        assert len(rows) == 1
        assert rows[0]["status"] == "done"

    def test_list_missing_db(self, tmp_path):
        assert list_runs(tmp_path / "nope.db") == []

    def test_internal_keys_not_persisted(self, tmp_path):
        db = tmp_path / "index.db"
        record_run(db, {"run_id": "r1", "_run_dir": "secret"})
        rows = list_runs(db)
        assert "_run_dir" not in json.dumps(rows)


class TestIsoS23Metric:
    """防再犯：iso_s23_db 必须用 0 基索引访问 3 端口网络（P1 真机 run 踩坑）。"""

    def test_iso_s23_on_3port_network(self):
        import numpy as np
        import skrf as rf

        freq = rf.Frequency(2.3, 2.5, 11, "GHz")
        s = np.zeros((11, 3, 3), dtype=complex)
        s[:, 0, 0] = 0.1          # S11
        s[:, 1, 0] = 0.7          # S21
        s[:, 0, 1] = 0.7
        s[:, 2, 0] = 0.7
        s[:, 0, 2] = 0.7
        s[:, 1, 2] = 0.05         # S23（工程记号）→ 0 基 [1,2]
        s[:, 2, 1] = 0.05
        ntwk = rf.Network(frequency=freq, s=s)
        from rfauto.core.objectives import Objective, SpecEvaluator
        metrics = SpecEvaluator.compute_metrics(
            ntwk, [Objective(metric="iso_s23_db", band=[2.3, 2.5], op="min_above", value=20)]
        )
        expected = -20 * np.log10(0.05)  # ≈ 26.02 dB
        assert abs(metrics["iso_s23_db_min_in_band"] - expected) < 0.1
