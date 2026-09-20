"""测量数据导入。

职责：
- 导入 Touchstone 文件（.s1p/.s2p/.s3p/.s4p）
- 导入 CSV 格式的测量数据
- 解析测量元数据（仪器/校准件/IF 带宽/温度/日期）

设计决策：
- 新层 measurement/，不放 adapters/（import-linter 按目录判层）
- 实测数据默认不进 git（含敏感设计数据，.gitignore 兜底）
- E9a 文件导入先行，E9d SCPI 硬件后置
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import skrf


@dataclass
class MeasurementMetadata:
    """测量元数据。"""
    instrument: str = ""
    calibration_kit: str = ""
    if_bandwidth_hz: float | None = None
    temperature_c: float | None = None
    date: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "calibration_kit": self.calibration_kit,
            "if_bandwidth_hz": self.if_bandwidth_hz,
            "temperature_c": self.temperature_c,
            "date": self.date,
            "notes": self.notes,
        }


@dataclass
class MeasurementData:
    """测量数据容器。"""
    network: skrf.Network
    metadata: MeasurementMetadata
    source_file: str
    n_ports: int
    freq_range_ghz: tuple[float, float]

    @property
    def s_params(self) -> np.ndarray:
        """S 参数矩阵。"""
        return self.network.s

    @property
    def freq_ghz(self) -> np.ndarray:
        """频率轴 (GHz)。"""
        return self.network.f / 1e9

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "n_ports": self.n_ports,
            "freq_range_ghz": list(self.freq_range_ghz),
            "n_freq_points": len(self.network.f),
            "metadata": self.metadata.to_dict(),
        }


def import_touchstone(
    file_path: str | Path,
    metadata: MeasurementMetadata | None = None,
) -> MeasurementData:
    """导入 Touchstone 文件。

    Args:
        file_path: .s1p/.s2p/.s3p/.s4p 文件路径
        metadata: 测量元数据（可选）

    Returns:
        MeasurementData

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 不支持的文件格式
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"测量文件不存在: {path}")

    # 检查文件扩展名
    ext = path.suffix.lower()
    if ext not in ('.s1p', '.s2p', '.s3p', '.s4p', '.snp'):
        raise ValueError(f"不支持的文件格式: {ext}")

    # 使用 skrf 导入
    try:
        network = skrf.Network(str(path))
    except Exception as e:
        raise ValueError(f"Touchstone 文件解析失败: {e}") from e

    # 提取频率范围
    freq_hz = network.f
    freq_range = (float(freq_hz[0]) / 1e9, float(freq_hz[-1]) / 1e9)

    return MeasurementData(
        network=network,
        metadata=metadata or MeasurementMetadata(),
        source_file=str(path),
        n_ports=network.nports,
        freq_range_ghz=freq_range,
    )


def import_csv_sparams(
    file_path: str | Path,
    freq_col: int = 0,
    s11_col: int = 1,
    s21_col: int = 2,
    s12_col: int = 3,
    s22_col: int = 4,
    freq_unit: str = "GHz",
    z0: float = 50.0,
    metadata: MeasurementMetadata | None = None,
) -> MeasurementData:
    """导入 CSV 格式的 S 参数数据。

    CSV 格式假设：
    - 第一列：频率
    - 后续列：S11_real, S11_imag, S21_real, S21_imag, ...（实部/虚部交替）

    Args:
        file_path: CSV 文件路径
        freq_col: 频率列索引
        s11_col, s21_col, s12_col, s22_col: S 参数列索引（实部，虚部在下一列）
        freq_unit: 频率单位 ("Hz", "kHz", "MHz", "GHz")
        z0: 参考阻抗
        metadata: 测量元数据

    Returns:
        MeasurementData
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {path}")

    # 读取 CSV
    try:
        data = np.loadtxt(str(path), delimiter=',', skiprows=1)
    except Exception as e:
        raise ValueError(f"CSV 文件解析失败: {e}") from e

    # 频率单位转换
    freq_multipliers = {"Hz": 1, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}
    if freq_unit not in freq_multipliers:
        raise ValueError(f"不支持的频率单位: {freq_unit}")

    freq_hz = data[:, freq_col] * freq_multipliers[freq_unit]
    n_freq = len(freq_hz)

    # 构建 S 矩阵
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    s[:, 0, 0] = data[:, s11_col] + 1j * data[:, s11_col + 1]  # S11
    s[:, 1, 0] = data[:, s21_col] + 1j * data[:, s21_col + 1]  # S21
    s[:, 0, 1] = data[:, s12_col] + 1j * data[:, s12_col + 1]  # S12
    s[:, 1, 1] = data[:, s22_col] + 1j * data[:, s22_col + 1]  # S22

    # 创建 skrf.Network
    freq = skrf.Frequency.from_f(freq_hz, unit="Hz")
    network = skrf.Network(frequency=freq, s=s, z0=z0)

    freq_range = (float(freq_hz[0]) / 1e9, float(freq_hz[-1]) / 1e9)

    return MeasurementData(
        network=network,
        metadata=metadata or MeasurementMetadata(),
        source_file=str(path),
        n_ports=2,
        freq_range_ghz=freq_range,
    )


def list_measurement_files(
    directory: str | Path,
    extensions: list[str] | None = None,
) -> list[Path]:
    """列出目录下的测量文件。

    Args:
        directory: 目录路径
        extensions: 文件扩展名过滤（默认 .s1p/.s2p/.s3p/.s4p/.csv）

    Returns:
        文件路径列表
    """
    if extensions is None:
        extensions = ['.s1p', '.s2p', '.s3p', '.s4p', '.csv']

    dir_path = Path(directory)
    if not dir_path.exists():
        return []

    files = []
    for ext in extensions:
        files.extend(dir_path.glob(f"*{ext}"))

    return sorted(files)
