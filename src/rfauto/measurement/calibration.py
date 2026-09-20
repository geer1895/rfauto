"""校准框架。

TRL/SOLT 校准支持：
- 使用 skrf.calibration 进行标准件校准
- 无标准件时只能"原样比对"并标注 cal=None

设计决策：
- 色散 PCB 夹具必须走 TRL/SOLT 标准件测量集
- "夹具级联求逆"只对频率无关夹具成立（v1 技术错误修正）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import skrf

from rfauto.measurement.import_data import MeasurementData


class CalibrationMethod(str, Enum):
    """校准方法。"""
    TRL = "trl"      # Through-Reflect-Line
    SOLT = "solt"    # Short-Open-Load-Through
    NONE = "none"    # 无校准（原样比对）


@dataclass
class CalibrationStandard:
    """校准标准件。"""
    name: str
    network: skrf.Network
    standard_type: str  # "through", "reflect", "line", "short", "open", "load"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.standard_type,
            "n_ports": self.network.nports,
            "freq_range_ghz": [
                float(self.network.f[0]) / 1e9,
                float(self.network.f[-1]) / 1e9,
            ],
        }


@dataclass
class CalibrationKit:
    """校准套件。"""
    name: str
    method: CalibrationMethod
    standards: list[CalibrationStandard]
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method.value,
            "n_standards": len(self.standards),
            "standards": [s.to_dict() for s in self.standards],
            "metadata": self.metadata,
        }


@dataclass
class CalibrationResult:
    """校准结果。"""
    method: CalibrationMethod
    calkit: CalibrationKit | None
    calibrated_network: skrf.Network | None
    error_terms: dict[str, Any] = None
    is_calibrated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "is_calibrated": self.is_calibrated,
            "calkit_name": self.calkit.name if self.calkit else None,
            "error_terms": self.error_terms,
        }


def apply_solt_calibration(
    measured: MeasurementData,
    calkit: CalibrationKit,
) -> CalibrationResult:
    """应用 SOLT 校准。

    Args:
        measured: 测量数据
        calkit: 校准套件（必须包含 Short/Open/Load/Through 标准件）

    Returns:
        CalibrationResult
    """
    if calkit.method != CalibrationMethod.SOLT:
        raise ValueError(f"校准套件方法不匹配: {calkit.method.value} != solt")

    # 提取标准件
    standards = {s.standard_type: s for s in calkit.standards}
    required = ["short", "open", "load", "through"]
    for std_type in required:
        if std_type not in standards:
            raise ValueError(f"缺少校准标准件: {std_type}")

    # 使用 skrf 的 SOLT 校准
    try:
        # 构建校准标准件列表
        cal_standards = [
            standards["short"].network,
            standards["open"].network,
            standards["load"].network,
            standards["through"].network,
        ]

        # 创建校准对象
        cal = skrf.calibration.SOLT(
            ideals=cal_standards,
            measured=[s for s in measured.network.s],  # 简化：使用测量数据
        )

        # 应用校准
        cal.apply_cal()

        return CalibrationResult(
            method=CalibrationMethod.SOLT,
            calkit=calkit,
            calibrated_network=cal.network,
            is_calibrated=True,
        )
    except Exception as e:
        return CalibrationResult(
            method=CalibrationMethod.SOLT,
            calkit=calkit,
            calibrated_network=None,
            error_terms={"error": str(e)},
            is_calibrated=False,
        )


def apply_trl_calibration(
    measured: MeasurementData,
    calkit: CalibrationKit,
) -> CalibrationResult:
    """应用 TRL 校准。

    Args:
        measured: 测量数据
        calkit: 校准套件（必须包含 Through/Reflect/Line 标准件）

    Returns:
        CalibrationResult
    """
    if calkit.method != CalibrationMethod.TRL:
        raise ValueError(f"校准套件方法不匹配: {calkit.method.value} != trl")

    # 提取标准件
    standards = {s.standard_type: s for s in calkit.standards}
    required = ["through", "reflect", "line"]
    for std_type in required:
        if std_type not in standards:
            raise ValueError(f"缺少校准标准件: {std_type}")

    # 使用 skrf 的 TRL 校准
    try:
        cal_standards = [
            standards["through"].network,
            standards["reflect"].network,
            standards["line"].network,
        ]

        cal = skrf.calibration.TRL(
            ideals=cal_standards,
            measured=[s for s in measured.network.s],
        )

        cal.apply_cal()

        return CalibrationResult(
            method=CalibrationMethod.TRL,
            calkit=calkit,
            calibrated_network=cal.network,
            is_calibrated=True,
        )
    except Exception as e:
        return CalibrationResult(
            method=CalibrationMethod.TRL,
            calkit=calkit,
            calibrated_network=None,
            error_terms={"error": str(e)},
            is_calibrated=False,
        )


def apply_calibration(
    measured: MeasurementData,
    calkit: CalibrationKit | None,
) -> CalibrationResult:
    """应用校准（自动选择方法）。

    无标准件时返回未校准结果（原样比对）。

    Args:
        measured: 测量数据
        calkit: 校准套件（None = 无校准）

    Returns:
        CalibrationResult
    """
    if calkit is None:
        return CalibrationResult(
            method=CalibrationMethod.NONE,
            calkit=None,
            calibrated_network=measured.network,
            is_calibrated=False,
        )

    if calkit.method == CalibrationMethod.SOLT:
        return apply_solt_calibration(measured, calkit)
    elif calkit.method == CalibrationMethod.TRL:
        return apply_trl_calibration(measured, calkit)
    else:
        return CalibrationResult(
            method=CalibrationMethod.NONE,
            calkit=None,
            calibrated_network=measured.network,
            is_calibrated=False,
        )


# ─── cal kit 知识库（方向 3：按 ID 引用，不硬编码路径）───────────────────────

_DEFAULT_CALKIT_DIR = Path(__file__).resolve().parents[3] / "knowledge" / "calkits"

# catalog standards 键 → CalibrationStandard.standard_type 语义
_STANDARD_TYPE_MAP = {
    "thru": "through", "line": "line", "reflect": "reflect",
    "short": "short", "open": "open", "load": "load",
}


def load_calkit(calkit_id: str, directory: str | Path | None = None) -> CalibrationKit:
    """按 ID 从 knowledge/calkits/catalog.yaml 加载校准套件。

    标准件 Touchstone 文件与 catalog 同目录；响应式（response）kit 只含
    thru，加载为 CalibrationMethod.NONE 语义的透传件（配合 skrf 归一化）。

    Raises:
        KeyError: catalog 中无此 ID / 标准件文件缺失。
    """
    import yaml

    d = Path(directory) if directory else _DEFAULT_CALKIT_DIR
    catalog_path = d / "catalog.yaml"
    if not catalog_path.exists():
        raise KeyError(f"cal kit 目录不存在 catalog.yaml: {d}")
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    entry = (data.get("calkits") or {}).get(calkit_id)
    if entry is None:
        raise KeyError(f"catalog 中无此校准套件: {calkit_id}")

    method = CalibrationMethod(entry.get("method", "none")) \
        if entry.get("method") in ("trl", "solt") else CalibrationMethod.NONE
    standards = []
    for key, fname in (entry.get("standards") or {}).items():
        fpath = d / fname
        if not fpath.exists():
            raise KeyError(f"标准件文件缺失: {fname}（kit {calkit_id}）")
        net = skrf.Network(str(fpath))
        standards.append(CalibrationStandard(
            name=f"{calkit_id}.{key}", network=net,
            standard_type=_STANDARD_TYPE_MAP.get(key, key)))
    return CalibrationKit(
        name=calkit_id, method=method, standards=standards,
        metadata={"description": entry.get("description", ""), "directory": str(d)},
    )


def apply_response_calibration(
    measured: MeasurementData,
    thru_network: skrf.Network,
) -> CalibrationResult:
    """响应式（归一化）校准：measured ** thru⁻¹ 去嵌直通参考面。

    适合无标准件实测数据时的冒烟级校准；全 SOLT/TRL 语义见上方两函数。
    """
    try:
        corrected = measured.network ** thru_network.inv
        return CalibrationResult(
            method=CalibrationMethod.NONE, calkit=None,
            calibrated_network=corrected,
            error_terms={"method": "response_normalization"},
            is_calibrated=True,
        )
    except Exception as e:
        return CalibrationResult(
            method=CalibrationMethod.NONE, calkit=None,
            calibrated_network=measured.network,
            error_terms={"error": str(e)}, is_calibrated=False,
        )
