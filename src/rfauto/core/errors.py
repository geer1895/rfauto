"""RFAuto 异常体系（§7.6）。

层次结构：
RFAutoError
├── ConfigError               # 配方/参数非法 → 直接拒绝，不消耗 license
├── ContractViolationError    # 交换契约校验失败 → 硬失败，禁止继续
├── AdapterError
│   ├── ConnectFailedError    # 重试3次退避 → 硬失败
│   ├── ModelBuildError       # 几何无效 → 自愈 R1
│   └── SimulationFailedError # 优化器跳过该组
├── LicenseError              # 立即暂停任务入队等待
├── OptimizationDivergedError # 收缩搜索域回滚至最近 checkpoint
└── SolveTimeoutError         # 操作超时（求解/连接等）
"""

from __future__ import annotations

from typing import Any


class RFAutoError(Exception):
    """所有 RFAuto 异常的基类。"""

    error_type: str = "RFAutoError"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """结构化输出，供 ErrorEnvelope / events.jsonl 使用。"""
        return {
            "error_type": self.error_type,
            "message": str(self),
            "details": self.details,
        }


class ConfigError(RFAutoError):
    """配方/参数非法 → 直接拒绝，不消耗 license。"""

    error_type = "ConfigError"


class ContractViolationError(RFAutoError):
    """交换契约校验失败（端口顺序/参考阻抗不符）→ 硬失败，禁止继续。"""

    error_type = "ContractViolationError"


class AdapterError(RFAutoError):
    """适配器相关错误基类。"""

    error_type = "AdapterError"


class ConnectFailedError(AdapterError):
    """连接 EDA 软件失败（重试 3 次退避后仍失败）。"""

    error_type = "ConnectFailedError"


class ModelBuildError(AdapterError):
    """几何建模失败（无效几何/布尔失败）→ 触发自愈 R1。"""

    error_type = "ModelBuildError"


class SimulationFailedError(AdapterError):
    """仿真求解失败 → 优化器跳过该参数组。"""

    error_type = "SimulationFailedError"


class LicenseError(RFAutoError):
    """License 占用/不可用 → 立即暂停任务入队等待。"""

    error_type = "LicenseError"


class OptimizationDivergedError(RFAutoError):
    """优化发散 → 收缩搜索域回滚至最近 checkpoint。"""

    error_type = "OptimizationDivergedError"


class SolveTimeoutError(RFAutoError):
    """操作超时（求解/连接等）。

    原名 TimeoutError 会遮蔽内置 TimeoutError——`except TimeoutError` 将
    永远捕不到 socket/subprocess 的内置超时异常，故更名。
    """

    error_type = "SolveTimeoutError"
