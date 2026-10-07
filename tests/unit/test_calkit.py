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


class TestLoadCalkitMethodValidation:
    """S-1 C-05 2026-10-04：未识别 method 显式 KeyError（列合法值清单）。

    旧实现任何非枚举值（含大小写笔误 "SOLT"、拼错 "soltt"）都静默降级
    CalibrationMethod.NONE——症状是"校准从未发生"而无迹可查。三形态合法：
    枚举成员 / 'response' 响应式透传别名（真实 catalog wl_2g5_response）/
    method 键缺省（v1 schema 兼容）。"""

    @staticmethod
    def _kit_dir(tmp_path, method):
        """写一个只含 thru 标准件的最小 kit 目录（method 可为 None=缺键）。"""
        import skrf
        import yaml
        freq = skrf.Frequency(2.0, 3.0, 11, unit="GHz")
        thru = skrf.Network(
            frequency=freq,
            s=np.array([[[0, 1], [1, 0]]] * 11, dtype=complex))
        thru.write_touchstone(str(tmp_path / "thru.s2p"))
        entry = {"standards": {"thru": "thru.s2p"}}
        if method is not None:
            entry["method"] = method
        (tmp_path / "catalog.yaml").write_text(
            yaml.safe_dump({"calkits": {"k": entry}}), encoding="utf-8")

    def test_typo_method_raises_with_valid_list(self, tmp_path):
        from rfauto.measurement.calibration import load_calkit
        self._kit_dir(tmp_path, "soltt")            # 拼错（solt → soltt）
        with pytest.raises(KeyError, match="soltt"):
            load_calkit("k", directory=tmp_path)

    def test_uppercase_method_not_silently_none(self, tmp_path):
        from rfauto.measurement.calibration import CalibrationMethod, load_calkit
        self._kit_dir(tmp_path, "SOLT")             # 大小写笔误
        with pytest.raises(KeyError):
            load_calkit("k", directory=tmp_path)
        # 对照：小写枚举值正常装载为 SOLT
        self._kit_dir(tmp_path, "solt")
        assert load_calkit("k", directory=tmp_path).method \
            == CalibrationMethod.SOLT

    def test_response_alias_maps_to_none(self, tmp_path):
        from rfauto.measurement.calibration import CalibrationMethod, load_calkit
        self._kit_dir(tmp_path, "response")
        kit = load_calkit("k", directory=tmp_path)
        assert kit.method == CalibrationMethod.NONE
        assert len(kit.standards) == 1

    def test_absent_method_defaults_none(self, tmp_path):
        from rfauto.measurement.calibration import CalibrationMethod, load_calkit
        self._kit_dir(tmp_path, None)               # method 键缺省（v1）
        assert load_calkit("k", directory=tmp_path).method \
            == CalibrationMethod.NONE
