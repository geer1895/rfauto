"""E1a openEMS 适配器单元测试。"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.adapters.openems_adapter import (
    OpenEMSAdapter,
    OpenEMSConfig,
    OpenEMSResult,
    parse_openems_csv,
)


class TestOpenEMSAdapter:
    def test_adapter_creation(self):
        adapter = OpenEMSAdapter()
        assert adapter is not None
        assert not adapter._connected

    def test_config(self):
        config = OpenEMSConfig(exe_path="/path/to/openEMS")
        adapter = OpenEMSAdapter(config)
        assert adapter._config.exe_path == "/path/to/openEMS"

    def test_get_status(self):
        adapter = OpenEMSAdapter()
        status = adapter.get_status()
        assert "connected" in status
        assert "available" in status

    def test_is_available_without_openems(self):
        """没有安装 openEMS 时应返回 False。"""
        adapter = OpenEMSAdapter(OpenEMSConfig(exe_path="C:/nonexistent/openEMS.exe"))
        assert not adapter.is_available()


class TestParseCSV:
    def test_parse_csv(self, tmp_path):
        """解析 openEMS CSV 输出。"""
        # 创建测试 CSV
        csv_path = tmp_path / "test.csv"
        freq = np.linspace(1e9, 5e9, 5)
        s11_re = np.random.rand(5)
        s11_im = np.random.rand(5)
        s21_re = np.random.rand(5)
        s21_im = np.random.rand(5)

        with open(csv_path, 'w') as f:
            f.write("freq,re(S11),im(S11),re(S21),im(S21)\n")
            for i in range(5):
                f.write(f"{freq[i]},{s11_re[i]},{s11_im[i]},{s21_re[i]},{s21_im[i]}\n")

        freq_ghz, s11_db, s21_db = parse_openems_csv(csv_path)
        assert len(freq_ghz) == 5
        assert len(s11_db) == 5
        assert len(s21_db) == 5
        assert np.all(freq_ghz >= 1.0)
        assert np.all(freq_ghz <= 5.0)

    def test_parse_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_openems_csv("/nonexistent/file.csv")


class TestOpenEMSResult:
    def test_result_creation(self):
        result = OpenEMSResult(success=True, message="OK")
        assert result.success
        assert result.message == "OK"

    def test_to_dict(self):
        result = OpenEMSResult(
            success=True,
            freq_ghz=np.array([1.0, 2.0, 3.0]),
            message="test",
        )
        d = result.to_dict()
        assert d["success"]
        assert d["n_freq_points"] == 3
