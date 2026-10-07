"""HfssSession — gRPC 桌面会话单例（P0 桩实现）。

集中管理 AEDT Desktop 连接，供 HfssAdapter 委托使用。
所有 ansys.aedt.core import 延迟到方法内部，避免模块级导入失败。

P0 阶段：桩实现，核心方法抛出 NotImplementedError 并给出实现指引。
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rfauto.core.errors import ConnectFailedError, LicenseError

if TYPE_CHECKING:
    from rfauto.infra.remote_machines import HfssMtlsCerts

logger = logging.getLogger(__name__)

# pyaedt 1.4.0 desktop.py ``_get_grpcsrv_args.check_mtls`` 实测：mTLS 客户端
# 证书文件夹三件固定名（env ANSYS_GRPC_CERTIFICATES 指向文件夹，文件名不限
# 配置侧、消费前由 _stage_mtls_certs 规范化到此命名）。
_MTLS_CA_NAME = "ca.crt"
_MTLS_CLIENT_CERT_NAME = "client.crt"
_MTLS_CLIENT_KEY_NAME = "client.key"
_ENV_GRPC_CERTIFICATES = "ANSYS_GRPC_CERTIFICATES"

# EC-5（2026-10-05）：HFSS HPC/DSO 旋钮的 AEDT 注册表键前缀——DSO 活动
# 配置名 = ``Desktop/ActiveDSOConfigurations/<product>``（pyaedt 1.4.0
# desktop.change_active_dso_config_name 实测走 SetRegistryString 同键）。
_DSO_REGISTRY_PREFIX = "Desktop/ActiveDSOConfigurations"


def _dso_active_config(desktop: Any, product: str = "HFSS") -> str | None:
    """读 AEDT 活动 DSO 配置名（best-effort，#105：读不到返回 None 不阻塞）。

    odesktop.GetRegistryString 在 gRPC/COM 两形态下均可用（pyaedt
    change_registry_key 同键消费 SetRegistryString 的对读面）；任何异常
    一律 None——调用方据此跳过 close 的注册表回写（不猜原值，#105）。
    """
    try:
        odesktop = getattr(desktop, "odesktop", None)
        if odesktop is None:
            return None
        value = odesktop.GetRegistryString(
            f"{_DSO_REGISTRY_PREFIX}/{product}")
        return str(value) if value is not None else None
    except Exception:
        return None


class _AutoSwitches:
    """``remote_session_switches(mtls=)`` 的缺省哨兵：按活跃会话状态自动选形。"""

    __slots__ = ()


_AUTO: Any = _AutoSwitches()

# 活跃远程会话的 mTLS 证书（connect 设置/清除）。adapter 第二构造窗口
# （open_or_create_project→Hfss 构造）以**裸调用**进入
# remote_session_switches()——据此单源自动选形，hfss_adapter.py 零改动；
# remote_service L2 的裸调用同源受益（同机同证书面）。下一次 connect
# （本地或远程）都会重写本状态，无跨会话泄漏面。
_ACTIVE_MTLS_CERTS: HfssMtlsCerts | None = None


def set_active_mtls_certs(certs: HfssMtlsCerts | None) -> None:
    """设置/清除活跃远程会话的 mTLS 证书（connect 专用；测试可显式复位）。"""
    global _ACTIVE_MTLS_CERTS
    _ACTIVE_MTLS_CERTS = certs


def active_mtls_certs() -> HfssMtlsCerts | None:
    """读取活跃远程会话的 mTLS 证书（观测/测试面）。"""
    return _ACTIVE_MTLS_CERTS


def _stage_mtls_certs(mtls: HfssMtlsCerts) -> tuple[str, str | None]:
    """把证书三件规范化为 pyaedt 证书文件夹形态。

    Returns
    -------
    tuple[str, str | None]
        ``(env 目标文件夹, 暂存目录或 None)``——三件已同目录且为规范名
        （ca.crt/client.crt/client.key）时直接直用零拷贝（暂存=None）；
        否则拷贝进临时目录（CM 退出时由调用方清理）。

    Raises
    ------
    ConnectFailedError
        任一文件缺失/拷贝失败（fail-closed，绝不静默降级 InsecureMode）。
    """
    ca = Path(mtls.ca_cert)
    cert = Path(mtls.client_cert)
    key = Path(mtls.client_key)
    missing = [str(p) for p in (ca, cert, key) if not p.is_file()]
    if missing:
        raise ConnectFailedError(
            "远程 mTLS 证书文件缺失（fail-closed，不降级 InsecureMode）: "
            + ", ".join(missing),
            details={"missing": missing},
        )
    canonical = {_MTLS_CA_NAME, _MTLS_CLIENT_CERT_NAME, _MTLS_CLIENT_KEY_NAME}
    parents = {os.path.normcase(str(p.resolve().parent)) for p in (ca, cert, key)}
    if {p.name for p in (ca, cert, key)} == canonical and len(parents) == 1:
        return str(ca.resolve().parent), None
    staged = Path(tempfile.mkdtemp(prefix="rfauto_mtls_"))
    try:
        shutil.copyfile(ca, staged / _MTLS_CA_NAME)
        shutil.copyfile(cert, staged / _MTLS_CLIENT_CERT_NAME)
        shutil.copyfile(key, staged / _MTLS_CLIENT_KEY_NAME)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        raise ConnectFailedError(
            f"远程 mTLS 证书暂存失败（fail-closed，不降级 InsecureMode）: {exc}",
            details={"staged_dir": str(staged)},
        ) from exc
    return str(staged), str(staged)


@contextlib.contextmanager
def remote_session_switches(
    mtls: HfssMtlsCerts | _AutoSwitches | None = _AUTO,
):
    """远程 attach 四开关+一环境变量的作用域管理（共享单源，L1/L2/session 同款）。

    远程分支的 ``Desktop`` 构造必需（pyaedt 1.4.0 × AEDT 2025.1.0 无 SP
    实证配方，五百三十四；原实现见 remote_service
    ``_attach_and_verify``，审查分片 1 P1-1 提升到本模块共享）：

    - ``grpc_local=False``：远程走 TCP 传输（缺省 WNUA 是 Windows 本机通道）；
    - ``grpc_secure_mode=False``：服务器侧 ansysedt -grpcsrv 未配证书（内网）；
    - ``remote_rpc_session=True``：``_validate_port`` 无 machine 的首查在
      非远程语义下会把 new_desktop 翻 True（误判"无会话→新开"→远程启动
      不可用）——远程会话语义必须先设 True 再构造 Desktop；
    - ``PYAEDT_USE_PRE_GRPC_ARGS=True``：AEDT 2025.1.0（初始版无 SP）的
      客户端 C++ 插件不支持 ``host:port:InsecureMode`` 三段式（pyaedt
      "Service Pack is not detected" 警告同源）——裸 IP:port 连接即可，
      服务端 InsecureMode 监听不变。

    **secure 形态（多机 v1，mTLS）**：``mtls`` 传入证书三件
    （:class:`~rfauto.infra.remote_machines.HfssMtlsCerts`，或经活跃会话
    状态自动选形）时改为——

    - ``grpc_secure_mode=True`` + ``ANSYS_GRPC_CERTIFICATES`` env 指向
      证书文件夹（pyaedt 1.4.0 desktop.py 实测：文件夹含固定名
      ca.crt/client.crt/client.key 三件，``_get_grpcsrv_args`` 据此选
      MTLS 并 ``__repr__`` 出 ``host:port:SecureMode`` 三段式；env 缺位时
      同一函数静默回 InsecureMode 后缀——本层前置校验+fail-closed 封死
      该静默降级面）；
    - ``PYAEDT_USE_PRE_GRPC_ARGS`` 强制 ``"False"``（该 env 为 True 会把
      连接串砍成裸 IP 丢掉 SecureMode 后缀，SP1 三段式通道建立不起来）；
    - 证书文件名非规范名/不同目录时暂存规范化到临时文件夹，CM 退出清理
      （观测级 best-effort，#105）。

    缺省路径（不传 mtls 且无活跃 secure 会话）与历史逐字节相同。开关只在
    构造期消费，Desktop attach 完成后即可安全恢复（恢复点=调用方返回前）。
    """
    from ansys.aedt.core.generic.settings import settings as aedt_settings

    if isinstance(mtls, _AutoSwitches):
        mtls = _ACTIVE_MTLS_CERTS

    staged_dir: str | None = None
    if mtls is not None:
        certs_env_dir, staged_dir = _stage_mtls_certs(mtls)

    saved = {
        "grpc_local": aedt_settings.grpc_local,
        "grpc_secure_mode": aedt_settings.grpc_secure_mode,
        "remote_rpc_session": aedt_settings.remote_rpc_session,
    }
    saved_env = os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS")
    saved_certs_env = (
        os.environ.get(_ENV_GRPC_CERTIFICATES) if mtls is not None else None
    )
    aedt_settings.grpc_local = False
    aedt_settings.grpc_secure_mode = mtls is not None
    aedt_settings.remote_rpc_session = True
    if mtls is None:
        os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "True"
    else:
        os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = "False"
        os.environ[_ENV_GRPC_CERTIFICATES] = certs_env_dir
        logger.info(
            "远程 mTLS 通道启用：certificates dir=%s（暂存=%s）",
            certs_env_dir, staged_dir or "无（规范名直用）",
        )
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(aedt_settings, key, value)
        if saved_env is None:
            os.environ.pop("PYAEDT_USE_PRE_GRPC_ARGS", None)
        else:
            os.environ["PYAEDT_USE_PRE_GRPC_ARGS"] = saved_env
        if mtls is not None:
            if saved_certs_env is None:
                os.environ.pop(_ENV_GRPC_CERTIFICATES, None)
            else:
                os.environ[_ENV_GRPC_CERTIFICATES] = saved_certs_env
            if staged_dir is not None:
                shutil.rmtree(staged_dir, ignore_errors=True)


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
            # 远程会话信息（多机协同 v0）：connect(settings) 带 remote_machine
            # 键时由注册表解析填充；None=本地会话（零行为变化）。
            self._remote: dict[str, Any] | None = None
            # mTLS 证书面（多机协同 v1）：三键齐=secure 形态（session/adapter
            # 两构造窗口同源消费）；None=insecure 现行为。
            self._remote_mtls: HfssMtlsCerts | None = None
            # EC-5 HPC/DSO 旋钮生效账：connect 带 hfss_cores 时填充（生效值
            # +进入前原值）；close 恢复后清空。None=旋钮未启用（缺省路径）。
            self._hpc: dict[str, Any] | None = None
            # 旋钮启用期间的进入前原值（跨 reconnect 保持——重连重放同一
            # 旋钮时仍以**最初**原值恢复，不拿旋钮值当原值）。
            self._hpc_orig: dict[str, Any] | None = None
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
            - remote_machine : str, 注册表机器名（多机协同 v0；带该键走
              远程分支——版本配对断言 + 远程四开关 attach，见
              :func:`remote_session_switches`；调用方经
              service/remote_service.hfss_remote_session_config 组装增量）。
              注册表 hfss 节的 mTLS 三键（ca_cert/client_cert/client_key，
              多机 v1）配置齐时 attach 走 secure 形态（MTLS 三段式），
              缺一 fail-closed 拒连（不静默降级 InsecureMode）。
            - hfss_cores : int, ≥1（EC-5 HPC 旋钮，2026-10-05）。**缺省不传=
              现状零改动**（pyaedt settings.num_cores 未触碰 + DSO 注册表
              活动配置名未动）。传时 Desktop 构造前置
              ``pyaedt settings.num_cores``（pyaedt 1.4.0 口径，hasattr
              探测，spec 4.4 版本漂移保护），attach 后把 DSO 活动配置切到
              ``hfss_dso_config``（缺省 "Local"）；close/reconnect 恢复
              进入前原值（best-effort，#105 恢复失败只告警）。**接地勘误
              （#222 本席实测）：settings.num_cores 在 pyaedt 1.4.0 只被
              LSF 启动命令消费（desktop.py bsub -n），对直连 Desktop 求解
              无作用——直连路线的生效核数入口=
              ``HfssAdapter.solve(cores=, tasks=)``（analyze_setup
              Distributed 分支）+ env RFAUTO_HFSS_SOLVE_CORES/_TASKS**。
              DSO 注册表键是机器全局态——并发 HFSS 会话需互斥意识（现行
              solo 单飞 #261 天然规避；#247 同法：锁谓词同源）。

        Raises
        ------
        ConnectFailedError
            连接失败（重试后仍失败）；hfss_cores 非 ≥1 整数。
        LicenseError
            License 不可用。
        """
        if self._connected and self.desktop is not None:
            logger.info("AEDT Desktop 已连接，跳过重复连接")
            return

        self._settings = settings.copy()
        max_license_retries = int(settings.get("license_retries", 3))

        # EC-5 HPC/DSO 旋钮解析（缺省不传=零改动）：hfss_cores ≥1 整数校验
        # 显式拒绝（fail-loud，不静默夹断）；hfss_dso_config 只在 hfss_cores
        # 启用时随之切换（单旋钮族，spec 4.2 语义）。
        _hfss_cores_raw = settings.get("hfss_cores")
        _hpc_cores: int | None = None
        if _hfss_cores_raw is not None:
            try:
                # 先按 float 对齐再取整：1.5/true 等非整数量显式拒绝
                # （int() 直转对 1.5 静默截断=假配置真跑单核，fail-loud）。
                _hpc_cores_f = float(_hfss_cores_raw)
                _hpc_cores = int(_hpc_cores_f)
            except (TypeError, ValueError) as exc:
                raise ConnectFailedError(
                    "hfss_cores 必须是 ≥1 的整数，得到 "
                    f"{_hfss_cores_raw!r}",
                    details={"hfss_cores": repr(_hfss_cores_raw)},
                ) from exc
            if _hpc_cores != _hpc_cores_f or _hpc_cores < 1:
                raise ConnectFailedError(
                    f"hfss_cores 必须 ≥1 的整数，得到 {_hfss_cores_raw!r}",
                    details={"hfss_cores": repr(_hfss_cores_raw)},
                )
        _hpc_dso_config = str(
            settings.get("hfss_dso_config") or "Local")

        # 远程会话解析（多机协同 v0）：settings["remote_machine"]=注册表名
        # → infra/remote_machines 解析 host/grpc 端口透传 Desktop(machine=,
        # port=)。无该键=本地会话（零行为变化）。版本配对口径：远程 AEDT
        # 必须与本机 pyaedt 配对版本一致。
        remote_name = settings.get("remote_machine")
        remote_kwargs: dict[str, Any] = {}
        if remote_name:
            from rfauto.infra.remote_machines import (
                hfss_mtls_certs,
                resolve_machine,
            )

            cfg = resolve_machine(str(remote_name))
            # 版本配对交叉断言：
            # pyaedt gRPC 客户端-服务端版本必须配对——settings 与注册表
            # 静默失配（如 settings 2024.1 + 注册表 2025.1）会让远程 attach
            # 走错客户端插件，显式拒绝并指引改配置。
            local_version = str(settings.get("desktop_version", "2024.1")).strip()
            remote_version = str(cfg.hfss_version).strip()
            if local_version != remote_version:
                raise ConnectFailedError(
                    f"HFSS 远程版本配对失配：settings.desktop_version="
                    f"{local_version!r} 与注册表 {cfg.name!r}.hfss_version="
                    f"{remote_version!r} 不一致——pyaedt gRPC 客户端-服务端"
                    "版本必须配对；请对齐 settings 的 "
                    "desktop_version 与 configs/remote_machines.yaml 的 "
                    "hfss.version。",
                    details={
                        "settings_version": local_version,
                        "registry_version": remote_version,
                        "machine": cfg.name,
                    },
                )
            # mTLS 证书面（多机 v1）：三键齐→secure 形态；缺一/文件缺失→
            # fail-closed（RemoteConfigError，同 resolve_machine 既有传播
            # 风格）；全缺→None=insecure 现行为零变化。
            mtls_certs = hfss_mtls_certs(cfg)
            remote_kwargs = {"machine": cfg.host, "port": cfg.hfss_grpc_port}
            self._remote = {
                "name": cfg.name,
                "machine": cfg.host,
                "port": cfg.hfss_grpc_port,
                "project_root": cfg.hfss_project_root,
                "version": cfg.hfss_version,
            }
            self._remote_mtls = mtls_certs
            logger.info(
                "远程会话：machine=%s:%s（注册表 %s，服务器侧 project_root=%s，"
                "mTLS=%s）",
                cfg.host, cfg.hfss_grpc_port, cfg.name, cfg.hfss_project_root,
                "on" if mtls_certs is not None else "off",
            )
        else:
            self._remote = None
            self._remote_mtls = None

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

        # EC-5：Desktop 构造前置 pyaedt settings.num_cores（全局 settings，
        # 构造前设置才被求解调度消费）。reconnect 重放同一旋钮时保持最初
        # 原值（_hpc_orig 不被二次覆盖）。
        _hpc_saved_num_cores: Any = None
        if _hpc_cores is not None:
            from ansys.aedt.core.generic.settings import (
                settings as aedt_settings,
            )

            if hasattr(aedt_settings, "num_cores"):
                _hpc_saved_num_cores = aedt_settings.num_cores
                aedt_settings.num_cores = _hpc_cores
                logger.info(
                    "HFSS HPC 旋钮：settings.num_cores %s → %s"
                    "（Desktop 构造前）",
                    _hpc_saved_num_cores, _hpc_cores)
                if self._hpc_orig is None:
                    self._hpc_orig = {"num_cores": _hpc_saved_num_cores}
            else:
                # pyaedt 1.x API 漂移探测（EC-5 spec 4.4）：缺属性=核数
                # 旋钮本会话不生效，如实告警不假装成功。
                logger.warning(
                    "pyaedt settings 无 num_cores 属性（版本漂移）——"
                    "hfss_cores 本会话未生效（EC-5 spec 4.4 hasattr 探测）")

        def _hpc_restore_num_cores_on_failure() -> None:
            if _hpc_saved_num_cores is None:
                return
            with contextlib.suppress(Exception):
                from ansys.aedt.core.generic.settings import (
                    settings as aedt_settings,
                )

                if hasattr(aedt_settings, "num_cores"):
                    aedt_settings.num_cores = _hpc_saved_num_cores
            self._hpc_orig = None

        # License 释放感知的延迟退避重连（S8.5 R4）：
        # license 紧张时按指数退避重试，重试耗尽后才抛 LicenseError
        from rfauto.core.errors import LicenseError
        from rfauto.pipeline.watchdog import Watchdog

        last_exc: Exception | None = None
        for attempt in range(max_license_retries + 1):
            try:
                logger.info("正在连接 AEDT Desktop %s (non_graphical=%s)", version, non_graphical)
                if remote_kwargs:
                    # 远程开关+env 只在 Desktop 构造期消费（P1-1，
                    # remote_service._attach_and_verify 同款配方，共享单源
                    # remote_session_switches）：CM 进入设置、退出恢复——
                    # 恢复点=connect 返回前（desktop 已 attach）。
                    # mtls 非 None 时 CM 走 secure 形态（mTLS 三段式）；
                    # 活跃状态同步设置，供 adapter 第二构造窗口（裸调用）
                    # 与 remote_service L2 同源选形。
                    set_active_mtls_certs(self._remote_mtls)
                    with remote_session_switches(self._remote_mtls):
                        self.desktop = Desktop(
                            version=version,
                            non_graphical=non_graphical,
                            student_version=student_version,
                            new_desktop=new_session,
                            **remote_kwargs,
                        )
                else:
                    set_active_mtls_certs(None)
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
                if _hpc_cores is not None:
                    # DSO 活动配置切换（EC-5 spec 4.2）：attach 成功后记录
                    # 进入前配置名 → 切换 → close 恢复。注册表键机器全局，
                    # 读不到原值时 close 不回写（不猜原值，#105）。
                    _hpc_saved_dso = _dso_active_config(self.desktop)
                    _dso_applied: str = ""
                    try:
                        _dso_applied = str(
                            self.desktop.change_active_dso_config_name(
                                "HFSS", _hpc_dso_config))
                    except Exception as exc:
                        logger.warning(
                            "DSO 活动配置切换异常（核数面仍生效）: %s", exc)
                    if self._hpc_orig is not None:
                        self._hpc_orig.setdefault("dso_config", _hpc_saved_dso)
                    self._hpc = {
                        "num_cores": _hpc_cores,
                        "dso_config": _hpc_dso_config,
                        "saved_num_cores": _hpc_saved_num_cores,
                        "saved_dso_config": _hpc_saved_dso,
                        "applied": _dso_applied,
                    }
                    logger.info(
                        "HFSS HPC：num_cores=%s，DSO 配置 %s → %s"
                        "（原值%s，close 恢复 best-effort）",
                        _hpc_cores, _hpc_saved_dso, _hpc_dso_config,
                        "已记" if _hpc_saved_dso else "未知（不回写）")
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
                    _hpc_restore_num_cores_on_failure()
                    raise LicenseError(
                        f"AEDT License 错误: {exc}",
                        details={"license_error": True},
                    ) from exc
                _hpc_restore_num_cores_on_failure()
                raise ConnectFailedError(
                    f"连接 AEDT Desktop 失败: {exc}",
                    details={"settings": settings},
                ) from exc

        # 理论不可达（循环内必 return 或 raise）
        _hpc_restore_num_cores_on_failure()
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

    def _restore_hpc(self, hpc: dict[str, Any] | None) -> None:
        """HPC/DSO 旋钮退出恢复（best-effort，#105：失败只告警不阻塞）。

        num_cores 恢复到进入前值（跨 reconnect 保持的 ``_hpc_orig``——
        拿旋钮值当原值会让重连后的会话永远恢复不回去）；DSO 活动配置名
        仅在进入前原值读到手时回写注册表（读不到不猜）。
        """
        if not hpc:
            return
        orig = self._hpc_orig or {}
        saved_cores = orig.get("num_cores", hpc.get("saved_num_cores"))
        if saved_cores is not None:
            try:
                from ansys.aedt.core.generic.settings import (
                    settings as aedt_settings,
                )

                if hasattr(aedt_settings, "num_cores"):
                    aedt_settings.num_cores = saved_cores
                    logger.info(
                        "HFSS HPC 恢复：settings.num_cores → %s",
                        saved_cores)
            except Exception as exc:
                logger.warning(
                    "恢复 pyaedt settings.num_cores 失败（忽略）: %s", exc)
        saved_dso = orig.get("dso_config", hpc.get("saved_dso_config"))
        if saved_dso and self.desktop is not None:
            try:
                self.desktop.change_registry_key(
                    f"{_DSO_REGISTRY_PREFIX}/HFSS", str(saved_dso))
                logger.info("HFSS HPC 恢复：DSO 活动配置 → %s", saved_dso)
            except Exception as exc:
                logger.warning(
                    "恢复 DSO 活动配置名失败（忽略）: %s", exc)
        self._hpc_orig = None

    @property
    def hpc_info(self) -> dict[str, Any] | None:
        """EC-5 HPC/DSO 旋钮生效账（未启用=None）。

        键：``num_cores/dso_config/saved_num_cores/saved_dso_config/applied``
        ——升档显式生效证据（判据面）与 close 恢复语义的观测面。
        """
        return self._hpc

    def close(self, save: bool = True) -> None:
        """关闭 AEDT Desktop 会话。

        Parameters
        ----------
        save : bool
            是否保存打开的项目。
        """
        if self.desktop is not None:
            hpc = self._hpc
            self._hpc = None
            try:
                self.desktop.release_desktop(
                    close_on_exit=True,
                    close_projects=save,
                )
            except Exception as exc:
                logger.warning("关闭 Desktop 时出错: %s", exc)
            finally:
                self._restore_hpc(hpc)
                self._connected = False
                self.desktop = None
                self.hfss = None
                logger.info("AEDT Desktop 会话已关闭")

    @property
    def is_connected(self) -> bool:
        """是否已连接。"""
        return self._connected and self.desktop is not None

    @property
    def remote_info(self) -> dict[str, Any] | None:
        """远程会话信息（未启用远程=None）。

        键：``name/machine/port/project_root/version``——adapter 层据此把
        project 路径按服务器侧语义解释并透传 Hfss(machine=, port=)。
        """
        return self._remote

    @property
    def remote_mtls_certs(self) -> HfssMtlsCerts | None:
        """活跃远程会话的 mTLS 证书面（insecure/未启用远程=None）。"""
        return self._remote_mtls
