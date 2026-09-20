"""HfssSession — gRPC 桌面会话单例（P0 桩实现）。

集中管理 AEDT Desktop 连接，供 HfssAdapter 委托使用。
所有 ansys.aedt.core import 延迟到方法内部，避免模块级导入失败。

P0 阶段：桩实现，核心方法抛出 NotImplementedError 并给出实现指引。
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from rfauto.core.errors import ConnectFailedError, LicenseError

logger = logging.getLogger(__name__)


class HfssSession:
    """AEDT Desktop gRPC 会话单例。

    使用方式::

        session = HfssSession.instance()
        session.connect({"desktop_version": "2024.1", "non_graphical": True})
        # ... 使用 session.desktop 操作 AEDT
        session.close()

    Attributes
    ----------
    desktop : Any
        ansys.aedt.core.Desktop 实例（connect 后可用）。
    hfss : Any
        ansys.aedt.core.Hfss 实例（connect 后可用）。
    """

    _instance: HfssSession | None = None
    _initialized: bool = False

    def __new__(cls) -> HfssSession:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not self._initialized:
            self.desktop: Any = None
            self.hfss: Any = None
            self._connected: bool = False
            self._settings: dict[str, Any] = {}
            HfssSession._initialized = True

    @classmethod
    def instance(cls) -> HfssSession:
        """获取单例实例。"""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """重置单例（仅用于测试）。"""
        if cls._instance is not None:
            with contextlib.suppress(Exception):
                cls._instance.close(save=False)
        cls._instance = None
        cls._initialized = False

    def connect(self, settings: dict[str, Any]) -> None:
        """幂等连接到 AEDT Desktop。

        Parameters
        ----------
        settings : dict
            连接配置，支持的键：
            - desktop_version : str, 如 "2024.1"
            - non_graphical : bool, 无头模式
            - student_version : bool, 学生版
            - port : int, gRPC 端口（已知实例时使用）
            - new_desktop_session : bool, 是否启动新实例

        Raises
        ------
        ConnectFailedError
            连接失败（重试后仍失败）。
        LicenseError
            License 不可用。
        """
        if self._connected and self.desktop is not None:
            logger.info("AEDT Desktop 已连接，跳过重复连接")
            return

        self._settings = settings.copy()
        max_license_retries = int(settings.get("license_retries", 3))

        # 延迟 import：仅在 adapter 实现内引入 EDA SDK（军规 8）
        try:
            from ansys.aedt.core import Desktop
        except ImportError as exc:
            raise ConnectFailedError(
                f"无法导入 ansys.aedt.core: {exc}\n"
                "请确认已安装 AEDT PyAEDT 包: pip install ansys-aedt-core",
                details={"import_error": str(exc)},
            ) from exc

        version = settings.get("desktop_version", "2024.1")
        non_graphical = settings.get("non_graphical", True)
        student_version = settings.get("student_version", False)
        new_session = settings.get("new_desktop_session", True)

        # License 释放感知的延迟退避重连（S8.5 R4）：
        # license 紧张时按指数退避重试，重试耗尽后才抛 LicenseError
        from rfauto.core.errors import LicenseError
        from rfauto.pipeline.watchdog import Watchdog

        last_exc: Exception | None = None
        for attempt in range(max_license_retries + 1):
            try:
                logger.info("正在连接 AEDT Desktop %s (non_graphical=%s)", version, non_graphical)
                self.desktop = Desktop(
                    version=version,
                    non_graphical=non_graphical,
                    student_version=student_version,
                    new_desktop=new_session,
                )
                # 2025.1 gRPC（#191）：此处不再建占位 Hfss 实例——
                # 双 Hfss 实例共存会让后建实例的设计变量管理器失效
                # （GetVariables 返回 None/Rename gRPC 失败；2023.1 可用，
                # 属版本漂移）。唯一的 Hfss 实例由
                # HfssAdapter.open_or_create_project 按目标项目创建。
                self.hfss = None
                self._connected = True
                logger.info("AEDT Desktop 连接成功 (%s)", version)
                return
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                is_license = "license" in msg or "flexlm" in msg or "lmgrd" in msg
                if is_license and attempt < max_license_retries:
                    delay = Watchdog.license_backoff(attempt)
                    logger.warning(
                        "License 不可用（第 %d/%d 次重试前等待 %.1fs）: %s",
                        attempt + 1, max_license_retries, delay, exc,
                    )
                    time.sleep(delay)
                    continue
                if is_license:
                    raise LicenseError(
                        f"AEDT License 错误: {exc}",
                        details={"license_error": True},
                    ) from exc
                raise ConnectFailedError(
                    f"连接 AEDT Desktop 失败: {exc}",
                    details={"settings": settings},
                ) from exc

        # 理论不可达（循环内必 return 或 raise）
        raise ConnectFailedError(
            f"连接 AEDT Desktop 失败: {last_exc}",
            details={"settings": settings},
        )

    def health_check(self) -> bool:
        """检查 AEDT Desktop 连接是否存活。

        Returns
        -------
        bool
            True 表示连接正常。
        """
        if not self._connected or self.desktop is None:
            return False

        try:
            # 用 current_version 属性验证连接（替代不存在的 version_keys）
            version = self.desktop.current_version
            return version is not None and len(str(version)) > 0
        except Exception:
            self._connected = False
            return False

    def reconnect_with_backoff(
        self,
        max_retries: int = 3,
        backoff_s: float = 10.0,
    ) -> None:
        """带退避的重连——License 释放感知。

        重连前先尝试优雅断开旧连接，等待 License 释放。

        Parameters
        ----------
        max_retries : int
            最大重试次数。
        backoff_s : float
            基础退避时间（秒），每次重试翻倍。

        Raises
        ------
        ConnectFailedError
            重试耗尽后仍失败。
        """
        # 先尝试优雅断开
        try:
            if self.desktop is not None:
                self.desktop.release_desktop(close_on_exit=False, close_projects=False)
        except Exception as exc:
            logger.warning("断开旧连接时出错（忽略）: %s", exc)

        self._connected = False
        self.desktop = None
        self.hfss = None

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            wait_time = backoff_s * (2 ** (attempt - 1))
            logger.info(
                "重连尝试 %d/%d，等待 %.1f 秒（License 释放）...",
                attempt, max_retries, wait_time,
            )
            time.sleep(wait_time)

            try:
                self.connect(self._settings)
                logger.info("重连成功（第 %d 次尝试）", attempt)
                return
            except (ConnectFailedError, LicenseError) as exc:
                last_error = exc
                logger.warning("重连失败（第 %d 次）: %s", attempt, exc)
                # 如果是 License 错误，额外等待
                if isinstance(exc, LicenseError):
                    logger.info("检测到 License 错误，额外等待 %.1f 秒", backoff_s)
                    time.sleep(backoff_s)

        raise ConnectFailedError(
            f"重连失败（已重试 {max_retries} 次）: {last_error}",
            details={"max_retries": max_retries, "last_error": str(last_error)},
        ) from last_error

    def close(self, save: bool = True) -> None:
        """关闭 AEDT Desktop 会话。

        Parameters
        ----------
        save : bool
            是否保存打开的项目。
        """
        if self.desktop is not None:
            try:
                self.desktop.release_desktop(
                    close_on_exit=True,
                    close_projects=save,
                )
            except Exception as exc:
                logger.warning("关闭 Desktop 时出错: %s", exc)
            finally:
                self._connected = False
                self.desktop = None
                self.hfss = None
                logger.info("AEDT Desktop 会话已关闭")

    @property
    def is_connected(self) -> bool:
        """是否已连接。"""
        return self._connected and self.desktop is not None
