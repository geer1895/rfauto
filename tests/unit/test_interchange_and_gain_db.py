"""清理项测试——远场指标 gain_db 进 DSL + interchange.py 覆盖补齐。"""

from __future__ import annotations

import numpy as np
import pytest
import skrf

from rfauto.adapters.interchange import (
    export_touchstone,
    read_touchstone,
    validate_frequency_range,
)
from rfauto.core.contracts import TouchstoneContract
from rfauto.core.errors import ContractViolationError
from rfauto.core.objectives import Objective, SpecEvaluator


def _network(n_ports: int = 3, z0: float = 50.0) -> skrf.Network:
    freq = skrf.Frequency(1.5, 3.5, 21, unit="GHz")
    s = np.zeros((21, n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        s[:, i, i] = 0.1
    if n_ports >= 2:
        s[:, 1, 0] = 0.7
        s[:, 0, 1] = 0.7
    return skrf.Network(frequency=freq, s=s, z0=z0)


class TestGainDbInDsl:
    def test_compute_metrics_with_far_field(self):
        ff = {"theta": list(range(0, 180, 5)), "gain_db": [float(-i) for i in range(0, 180, 5)]}
        metrics = SpecEvaluator.compute_metrics(
            _network(), [Objective(metric="gain_db", band=[], op="min_above", value=0)],
            far_field=ff,
        )
        assert metrics["gain_db_max"] == 0.0

    def test_gain_db_skipped_without_far_field(self):
        metrics = SpecEvaluator.compute_metrics(
            _network(), [Objective(metric="gain_db", band=[], op="min_above", value=0)],
        )
        assert "gain_db_max" not in metrics

    def test_run_once_gain_db_objective(self, tmp_path, monkeypatch):
        """端到端：run_once 带 gain_db 目标 → FakeAdapter 远场 → gain_db_max。"""
        import yaml

        monkeypatch.chdir(tmp_path)
        recipe = {
            "model": "patch_antenna",
            "schema_version": 1,
            "params": {"f0_ghz": 2.4},
            "objectives": [
                {"metric": "gain_db", "band": [], "op": "min_above", "value": 0},
            ],
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.service.api import run_once

        result = run_once(path, adapter_name="fake")
        assert result["ok"], result.get("errors")
        assert "gain_db_max" in result["metrics"]
        assert result["metrics"]["gain_db_max"] == pytest.approx(0.0)


class TestInterchange:
    def test_read_export_roundtrip_with_contract(self, tmp_path):
        contract = TouchstoneContract(port_order=["P1", "P2", "P3"], renormalization_ohm=50.0)
        net = _network(3)
        out = export_touchstone(net, tmp_path / "params.s3p", contract)
        assert out.exists()
        back = read_touchstone(out, contract)
        assert back.number_of_ports == 3
        assert np.allclose(np.abs(back.s), np.abs(net.s))

    def test_read_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_touchstone(tmp_path / "no_such.s2p")

    def test_port_count_violation(self, tmp_path):
        contract = TouchstoneContract(port_order=["P1", "P2", "P3", "P4"],
                                      renormalization_ohm=50.0)
        with pytest.raises(ContractViolationError, match="端口数"):
            export_touchstone(_network(3), tmp_path / "params.s4p", contract)

    def test_z0_violation(self, tmp_path):
        contract = TouchstoneContract(port_order=["P1", "P2", "P3"],
                                      renormalization_ohm=75.0)
        with pytest.raises(ContractViolationError, match="参考阻抗"):
            export_touchstone(_network(3), tmp_path / "params.s3p", contract)

    def test_validate_frequency_range(self):
        net = _network()
        assert validate_frequency_range(net, 1.5, 3.5) is True
        assert validate_frequency_range(net, 1.0, 5.0) is False
