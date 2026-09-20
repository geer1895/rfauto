"""器件 BlockSpec 协议。

BlockSpec：器件规格的数据模型，用于 co-sim 和链路预算。
物理事实：无源 sNp 级联推不出有源 NF/P1dB/IP3——
这些来自 catalog 的 datasheet 值。

ADR-0010 只增不改：新协议不影响现有 SimulatorAdapter 八方法。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class DeviceType(str, Enum):
    """器件类型。"""
    PASSIVE = "passive"
    ACTIVE = "active"
    MIXER = "mixer"


@dataclass(frozen=True)
class BlockSpec:
    """器件规格。

    Attributes:
        name: 器件名（catalog.yaml 键）
        device_type: 器件类型
        s_params_path: S 参数文件路径（可选，无源器件必须有）
        z0: 参考阻抗
        ports: 端口名列表
        freq_range_ghz: 适用频段 [f_low, f_high]
        gain_db: 增益 (dB)，有源器件必须有
        nf_db: 噪声系数 (dB)，有源器件必须有
        p1db_dbm: 1dB 压缩点 (dBm)，有源器件可选
        oip3_dbm: 三阶截点 (dBm)，有源器件可选
        conversion_loss_db: 转换损耗 (dB)，混频器必须有
        source: 数据来源 (datasheet/vendor/仿真/实测)
        notes: 备注
    """
    name: str
    device_type: DeviceType
    s_params_path: str | None = None
    z0: float = 50.0
    ports: list[str] = None
    freq_range_ghz: list[float] = None
    gain_db: float | None = None
    nf_db: float | None = None
    p1db_dbm: float | None = None
    oip3_dbm: float | None = None
    conversion_loss_db: float | None = None
    source: str = "unknown"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.ports is None:
            object.__setattr__(self, "ports", [])
        if self.freq_range_ghz is None:
            object.__setattr__(self, "freq_range_ghz", [0.0, 100.0])

    @property
    def n_ports(self) -> int:
        return len(self.ports)

    def is_active(self) -> bool:
        return self.device_type == DeviceType.ACTIVE

    def is_passive(self) -> bool:
        return self.device_type == DeviceType.PASSIVE

    def is_mixer(self) -> bool:
        return self.device_type == DeviceType.MIXER

    def validate(self) -> list[str]:
        """校验器件规格的完整性。

        Returns:
            问题列表（空=合格）
        """
        issues: list[str] = []

        # 有源器件必须有 NF 和 P1dB
        if self.is_active():
            if self.nf_db is None:
                issues.append(f"{self.name}: 有源器件必须有 nf_db")
            if self.gain_db is None:
                issues.append(f"{self.name}: 有源器件必须有 gain_db")

        # 混频器必须有转换损耗
        if self.is_mixer() and self.conversion_loss_db is None:
            issues.append(f"{self.name}: 混频器必须有 conversion_loss_db")

        # 无源器件应该有 S 参数文件
        if self.is_passive() and self.s_params_path is None:
            issues.append(f"{self.name}: 无源器件建议提供 s_params_path")

        return issues

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "name": self.name,
            "type": self.device_type.value,
            "s_params": self.s_params_path,
            "z0": self.z0,
            "ports": self.ports,
            "freq_range_ghz": self.freq_range_ghz,
            "gain_db": self.gain_db,
            "nf_db": self.nf_db,
            "p1db_dbm": self.p1db_dbm,
            "oip3_dbm": self.oip3_dbm,
            "conversion_loss_db": self.conversion_loss_db,
            "source": self.source,
            "notes": self.notes,
        }


class DeviceCatalog:
    """器件目录（从 catalog.yaml 加载）。

    用法：
        catalog = DeviceCatalog.from_yaml("parts/catalog.yaml")
        lna = catalog.get("lna_2ghz")
        print(lna.gain_db, lna.nf_db)
    """

    def __init__(self, devices: dict[str, BlockSpec]) -> None:
        self._devices = devices

    def get(self, name: str) -> BlockSpec:
        if name not in self._devices:
            raise KeyError(f"未知器件: {name}，可用: {list(self._devices.keys())}")
        return self._devices[name]

    def list_devices(self, device_type: DeviceType | None = None) -> list[str]:
        """列出器件名（可选按类型过滤）。"""
        if device_type is None:
            return list(self._devices.keys())
        return [n for n, d in self._devices.items() if d.device_type == device_type]

    @property
    def all(self) -> dict[str, BlockSpec]:
        return dict(self._devices)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DeviceCatalog:
        """从 catalog.yaml 加载。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"catalog.yaml 不存在: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        devices: dict[str, BlockSpec] = {}
        for name, spec in data.get("devices", {}).items():
            devices[name] = BlockSpec(
                name=name,
                device_type=DeviceType(spec.get("type", "passive")),
                s_params_path=spec.get("s_params"),
                z0=float(spec.get("z0", 50.0)),
                ports=spec.get("ports", []),
                freq_range_ghz=spec.get("freq_range_ghz", [0.0, 100.0]),
                gain_db=spec.get("gain_db"),
                nf_db=spec.get("nf_db"),
                p1db_dbm=spec.get("p1db_dbm"),
                oip3_dbm=spec.get("oip3_dbm"),
                conversion_loss_db=spec.get("conversion_loss_db"),
                source=spec.get("source", "unknown"),
                notes=spec.get("notes", ""),
            )

        return cls(devices)
