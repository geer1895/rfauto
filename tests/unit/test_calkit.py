"""A4 cal kit 知识库测试：按 ID 加载 + 响应式校准 + VNA 集成。"""

from __future__ import annotations

import numpy as np
import pytest


class TestLoadCalkit:
    def test_load_by_id(self):
        # 真实知识库：knowledge/calkits/catalog.yaml
        from rfauto.measurement.calibration import load_calkit
        kit = load_calkit("wl_2g5_solt_smoke")
        assert kit.name == "wl_2g5_solt_smoke"
        types = {s.standard_type for s in kit.standards}
        assert {"through", "load", "short", "open"} <= types
        # 频率轴一致
        for s in kit.standards:
            assert len(s.network.f) == 201

    def test_unknown_id_raises(self):
        from rfauto.measurement.calibration import load_calkit
        with pytest.raises(KeyError):
            load_calkit("no_such_kit")

    def test_missing_standard_file_raises(self, tmp_path):
        import yaml

        from rfauto.measurement.calibration import load_calkit
        (tmp_path / "catalog.yaml").write_text(
            yaml.safe_dump({"calkits": {"bad": {
                "method": "solt", "standards": {"thru": "ghost.s2p"}}}}),
            encoding="utf-8")
        with pytest.raises(KeyError, match="缺失"):
            load_calkit("bad", directory=tmp_path)


class TestResponseCalibration:
    def test_normalization_deembeds_thru(self):
        import skrf

        from rfauto.measurement.calibration import apply_response_calibration
        from rfauto.measurement.import_data import MeasurementData

        freq = skrf.Frequency(2.0, 3.0, 11, unit="GHz")
        thru = skrf.Network(frequency=freq,
                            s=np.array([[[0, 1], [1, 0]]] * 11, dtype=complex))
        # DUT = 10dB 衰减器（透射 0.316），级联直通参考面
        dut = skrf.Network(frequency=freq,
                           s=np.array([[[0, 0.316], [0.316, 0]]] * 11, dtype=complex))
        raw = dut ** thru  # 测量面上看：DUT 后再过一段直通
        measured = MeasurementData(network=raw, metadata=None, source_file="mock",
                                   n_ports=2, freq_range_ghz=(2.0, 3.0))
        result = apply_response_calibration(measured, thru)
        assert result.is_calibrated
        # 去嵌直通后应还原 DUT 本征透射
        assert np.allclose(np.abs(result.calibrated_network.s[:, 0, 1]), 0.316, atol=0.01)


class TestVNAApplyCalkit:
    def test_vna_apply_cal_kit_logs(self):
        import skrf

        from rfauto.measurement.calibration import load_calkit
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface

        freq = skrf.Frequency(2.0, 3.0, 11, unit="GHz")
        net = skrf.Network(frequency=freq,
                           s=np.array([[[0, 0.5], [0.5, 0]]] * 11, dtype=complex))
        vna = VNAInterface(VNAConfig(address="MOCK"))
        vna._connected = True
        kit = load_calkit("wl_2g5_response")
        result = vna.apply_cal_kit(kit, net)
        assert result["is_calibrated"]
        assert any(e.command == "apply_cal_kit" for e in vna._session_log)
