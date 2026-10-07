"""E9a 测量数据导入单元测试。

验收标准（扩展方案 §E9a）：
① Touchstone 文件导入（.s2p）
② CSV 格式导入
③ 元数据解析
④ 文件列表功能
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.measurement.import_data import (
    MeasurementData,
    MeasurementMetadata,
    import_csv_sparams,
    import_touchstone,
    list_measurement_files,
)


@pytest.fixture()
def sample_touchstone(tmp_path: Path) -> Path:
    """创建一个示例 .s2p 文件。"""
    freq = skrf.Frequency(1, 3, 5, unit="GHz")
    s = np.random.rand(5, 2, 2) + 1j * np.random.rand(5, 2, 2)
    network = skrf.Network(frequency=freq, s=s)
    path = tmp_path / "test.s2p"
    network.write_touchstone(str(path))
    return path


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    """创建一个示例 CSV 文件。"""
    freq = np.linspace(1e9, 3e9, 5)
    data = []
    for f in freq:
        # S11, S21, S12, S22 (real, imag pairs)
        data.append([f, -0.1, 0.2, 0.9, -0.1, 0.9, -0.1, -0.1, 0.2])

    path = tmp_path / "test.csv"
    with open(path, 'w') as f:
        f.write("freq,s11_re,s11_imag,s21_re,s21_imag,s12_re,s12_imag,s22_re,s22_imag\n")
        for row in data:
            f.write(",".join(str(x) for x in row) + "\n")
    return path


class TestImportTouchstone:
    """Touchstone 导入测试。"""

    def test_import_s2p(self, sample_touchstone):
        """① 导入 .s2p 文件。"""
        data = import_touchstone(sample_touchstone)
        assert isinstance(data, MeasurementData)
        assert data.n_ports == 2
        assert len(data.network.f) == 5

    def test_import_with_metadata(self, sample_touchstone):
        """③ 元数据解析。"""
        meta = MeasurementMetadata(
            instrument="Keysight PNA-X",
            calibration_kit="N4694C",
            temperature_c=25.0,
            date="2026-09-01",
        )
        data = import_touchstone(sample_touchstone, metadata=meta)
        assert data.metadata.instrument == "Keysight PNA-X"
        assert data.metadata.temperature_c == 25.0

    def test_import_nonexistent_raises(self):
        """不存在的文件应抛异常。"""
        with pytest.raises(FileNotFoundError):
            import_touchstone("/nonexistent/file.s2p")

    def test_to_dict(self, sample_touchstone):
        """序列化。"""
        data = import_touchstone(sample_touchstone)
        d = data.to_dict()
        assert "n_ports" in d
        assert "freq_range_ghz" in d


class TestImportCSV:
    """CSV 导入测试。"""

    def test_import_csv(self, sample_csv):
        """② 导入 CSV 文件。"""
        data = import_csv_sparams(sample_csv)
        assert isinstance(data, MeasurementData)
        assert data.n_ports == 2
        assert len(data.network.f) == 5

    def test_import_nonexistent_raises(self):
        """不存在的文件应抛异常。"""
        with pytest.raises(FileNotFoundError):
            import_csv_sparams("/nonexistent/file.csv")


class TestListFiles:
    """文件列表测试。"""

    def test_list_files(self, sample_touchstone, sample_csv):
        """④ 文件列表功能。"""
        files = list_measurement_files(sample_touchstone.parent)
        assert len(files) >= 2  # .s2p + .csv

    def test_list_empty_dir(self, tmp_path):
        """空目录应返回空列表。"""
        files = list_measurement_files(tmp_path)
        assert files == []


class TestMeasurementMetadata:
    """元数据测试。"""

    def test_default_metadata(self):
        meta = MeasurementMetadata()
        assert meta.instrument == ""
        assert meta.temperature_c is None

    def test_to_dict(self):
        meta = MeasurementMetadata(instrument="VNA", temperature_c=23.5)
        d = meta.to_dict()
        assert d["instrument"] == "VNA"
        assert d["temperature_c"] == 23.5


class TestSnpExtensionRemovedFromWhitelist:
    """S-1 C-06③ 2026-10-04：'.snp' 移出导入白名单——skrf 按 .sNp 扩展名
    数字推端口秩（#248），'.snp' 无秩可推，留在白名单只会把明确的扩展名
    错误降级成下游 skrf 解析错误。"""

    def test_snp_extension_rejected_upfront(self, tmp_path):
        path = tmp_path / "data.snp"
        path.write_text("# Hz S RI R 50\n", encoding="utf-8")
        with pytest.raises(ValueError, match="不支持的文件格式"):
            import_touchstone(path)

    def test_s4p_still_accepted(self, sample_touchstone):
        assert import_touchstone(sample_touchstone).n_ports == 2


class TestMetadataNoneNormalization:
    """S-1 C-07 2026-10-04：MeasurementData(metadata=None) 归一为缺省实例。

    vna_capture apply_cal_kit/mock 链两处传 None 构造，消费面调
    self.metadata.to_dict() 即 AttributeError 裸炸（latent footgun）。"""

    def test_metadata_none_normalized_to_default(self, sample_touchstone):
        data = import_touchstone(sample_touchstone)
        md = MeasurementData(network=data.network, metadata=None,
                             source_file="mock", n_ports=2,
                             freq_range_ghz=(1.0, 3.0))
        assert isinstance(md.metadata, MeasurementMetadata)
        dumped = md.to_dict()                 # 旧实现此处 AttributeError
        assert dumped["metadata"]["instrument"] == ""

    def test_explicit_metadata_preserved(self, sample_touchstone):
        data = import_touchstone(sample_touchstone)
        meta = MeasurementMetadata(instrument="VNA-X")
        md = MeasurementData(network=data.network, metadata=meta,
                             source_file="mock", n_ports=2,
                             freq_range_ghz=(1.0, 3.0))
        assert md.metadata is meta
