"""HfssSession — gRPC 桌面会话单例（P0 桩实现）。

集中管理 AEDT Desktop 连接，供 HfssAdapter 委托使用。
所有 ansys.aedt.core import 延迟到方法内部，避免模块级导入失败。

P0 阶段：桩实现，核心方法抛出 NotImplementedError 并给出实现指引。
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rfauto.core.errors import (
    ConnectFailedError,
    HfssSessionDeadError,
    LicenseError,
)

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


# ─── P2/P5 用户实战反馈兜底（2026-10-23 aurora_j S-B 席）─────────────────────
# 来源：pyaedt 1.4 × AEDT 2025.1 链路真实用户实测（三项全真机复现）——
# P2 create_setup(**kwargs) 透传、P5 CJK 工程路径 analyze() 内 save macro error。

#: P2 校验表——配方 setup 段（``configure_setup(setup_cfg)``）已知字段白名单。
#: 病灶（2026-10 用户实测）：pyaedt 1.4 ``create_setup(**kwargs)`` 对未知
#: kwarg 的透传在真机上触发 ``GrpcApiError: EditSetup``（求解直接失败），
#: 而原生接口支持该字段（参考工程 .aedt 内 ``MinimumPasses: 1``）。本仓
#: 策略：setup 段只收白名单键；AEDT 原生 setup 字段一律走 ``setup.props``
#: 属性字典（与 Frequency/MaxDeltaS/MaximumPasses 既有写法同惯例）；
#: 白名单外键一律 ValueError——宁可契约错误，不裸 gRPC、不静默丢键
#: （历史上未知键被静默丢弃，用户以为字段生效实则没有，同属契约错误）。
HFSS_SETUP_KNOWN_KEYS: frozenset[str] = frozenset({
    # configure_setup 直消键（setup/sweep 命名与频段面）
    "name", "sweep_name", "freq_range_ghz", "points",
    # 收敛面（本表解析进 setup.props；AEDT 原生大小写作别名同收）
    "convergence_delta", "max_passes", "minimum_passes",
    "MaxDeltaS", "MaximumPasses", "MinimumPasses",
    # 配方 setup 段既有键（configure_setup 不消费——模板/插件构建层消费；
    # 收进白名单防历史配方被误伤）
    "solver", "radiation_box",
})

#: recipe 键（snake_case 与 AEDT 原生大小写别名等价）→ setup.props 原生键。
HFSS_SETUP_PROPS_ALIASES: dict[str, str] = {
    "convergence_delta": "MaxDeltaS",
    "MaxDeltaS": "MaxDeltaS",
    "max_passes": "MaximumPasses",
    "MaximumPasses": "MaximumPasses",
    "minimum_passes": "MinimumPasses",
    "MinimumPasses": "MinimumPasses",
}

#: 收敛面字段缺省（configure_setup 历史缺省原样保真——键缺省时回填，
#: 既有调用行为逐字节不变）。
HFSS_SETUP_PROPS_DEFAULTS: dict[str, Any] = {
    "MaxDeltaS": 0.02,
    "MaximumPasses": 12,
}


def validate_setup_config(setup_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """P2 白名单校验 + 收敛面 props 解析（hfss_adapter.configure_setup 消费）。

    - 白名单外键 → ValueError（列未知键 + 合法键 + MinimumPasses 指引）；
    - 收敛面三字段（MaxDeltaS/MaximumPasses/MinimumPasses）按别名解析：
      snake_case 与 AEDT 原生大小写等价；同字段双形态同给且值不等 →
      ValueError（歧义拒绝）；类型校验：整数面（MaximumPasses/
      MinimumPasses）须可收敛为 ≥1 整数（bool 显式拒绝），MaxDeltaS 须
      可收敛为 >0 数值——配置错误 fail-loud，绝不带病进 AEDT；
    - 返回 ``{props键: 值}``：MaxDeltaS/MaximumPasses 缺省回填历史值
      （键缺失时）；MinimumPasses 未给则不含该键（零行为变化）。
    """
    if not isinstance(setup_cfg, Mapping):
        raise ValueError(
            f"setup 配置须为 dict/Mapping，得到 {type(setup_cfg).__name__}")
    unknown = sorted(k for k in setup_cfg if k not in HFSS_SETUP_KNOWN_KEYS)
    if unknown:
        raise ValueError(
            f"setup 配置含未知字段: {unknown}——该字段在 pyaedt 1.4 × "
            "AEDT 2025.1 链路不受支持（直传 create_setup(**kwargs) 会透传"
            "成 EditSetup 的 GrpcApiError，求解直接失败；静默忽略又会丢配"
            "置）。合法字段: " + ", ".join(sorted(HFSS_SETUP_KNOWN_KEYS))
            + "。AEDT 原生 setup 字段（如 MinimumPasses）请写"
              " minimum_passes/MinimumPasses，本仓自动走 setup.props 原生"
              "属性字典。")
    resolved: dict[str, Any] = {}
    for props_key in ("MaxDeltaS", "MaximumPasses", "MinimumPasses"):
        forms = [k for k, v in HFSS_SETUP_PROPS_ALIASES.items()
                 if v == props_key and k in setup_cfg]
        if not forms:
            if props_key in HFSS_SETUP_PROPS_DEFAULTS:
                resolved[props_key] = HFSS_SETUP_PROPS_DEFAULTS[props_key]
            continue
        raw_values = [setup_cfg[k] for k in forms]
        if len(forms) > 1 and len({repr(v) for v in raw_values}) > 1:
            raise ValueError(
                f"setup 配置字段 {props_key} 双形态同给且值不等: "
                f"{dict(zip(forms, raw_values, strict=True))}——歧义拒绝，请只写一种形态")
        raw = raw_values[0]
        if props_key == "MaxDeltaS":
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"setup 配置 MaxDeltaS 须为 >0 数值，得到 {raw!r}") from exc
            if not value > 0:
                raise ValueError(
                    f"setup 配置 MaxDeltaS 须为 >0 数值，得到 {raw!r}")
            resolved[props_key] = value
            continue
        # 整数面：MaximumPasses / MinimumPasses（bool 显式拒绝——bool 是
        # int 子类，True 会静默变成 1）
        if isinstance(raw, bool):
            raise ValueError(
                f"setup 配置 {props_key} 须为 ≥1 整数，得到布尔值 {raw!r}")
        try:
            fval = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"setup 配置 {props_key} 须为 ≥1 整数，得到 {raw!r}") from exc
        ival = int(fval)
        if ival != fval or ival < 1:
            raise ValueError(
                f"setup 配置 {props_key} 须为 ≥1 整数，得到 {raw!r}")
        resolved[props_key] = ival
    return resolved


def has_non_ascii(path: str | Path) -> bool:
    """P5 守卫谓词：路径含任何非 ASCII 字符（CJK 工程路径检测）。

    病灶（2026-10 用户实测）：CJK 工程路径（如 ``D:\\IPD调研\\...``）能建
    能解，但 ``analyze()`` 内部 ``save_project`` 报 macro error——纯路径
    问题（AEDT 脚本面对非 ASCII 路径字节），与建模正确性无关。
    """
    return any(ord(ch) > 127 for ch in str(path))


def ascii_workdir_path(project_path: str | Path) -> Path:
    """P5 重定向目标：``%TEMP%/rfauto_ascii_work/<原路径摘要12>/rfauto_work.aedt``。

    目标按原路径 SHA-1 摘要确定——同一原工程跨会话重跑落到同一 ASCII
    工作目录（AEDT reopen 语义成立）；文件名与各级目录恒 ASCII。
    """
    digest = hashlib.sha1(str(project_path).encode("utf-8")).hexdigest()[:12]
    return (Path(tempfile.gettempdir()) / "rfauto_ascii_work" / digest
            / "rfauto_work.aedt")


def prepare_ascii_workdir(original: Path, work: Path) -> Path:
    """原工程（若已存在）播到 ASCII 工作副本，返回工作副本路径。

    - 原 .aedt 不存在（新建工程）→ 只建父目录，零拷贝；
    - 工作副本缺失或比原工程旧 → ``shutil.copy2`` 刷新（保元数据）；
    - 工作副本比原工程新（疑似上次会话崩溃未交付）→ **保留工作副本**
      并告警（里面可能有未交付的新解，覆盖=丢数据——P1 同源教训）。
    """
    work.parent.mkdir(parents=True, exist_ok=True)
    if not original.is_file():
        return work
    try:
        if work.exists() and \
                work.stat().st_mtime >= original.stat().st_mtime:
            logger.warning(
                "ascii_workdir: 工作副本比原工程新（疑似上次会话未交付），"
                "保留工作副本继续: %s", work)
            return work
    except OSError:
        pass  # mtime 探测失败按"刷新拷贝"走（copy2 失败会显式抛）
    shutil.copy2(original, work)
    return work


def deliver_ascii_workdir(work: Path, original: Path) -> list[str]:
    """P5 交付拷回：工作副本 .aedt + .aedtresults/ → 原目标；逐项入账不抛。

    拷回面（与丢数据场景对齐）：<work>.aedt → <original>；工作副本旁
    ``rfauto_work.aedtresults/``（存在才拷）→ 原 .aedt 旁同名目录（逐
    文件拷贝，单文件失败只入账不中断）。返回错误清单（空=全量交付成功）；
    工作副本**永不删除**（交付失败供人工兜底——如实报不静默）。工作副本
    不存在=新建工程从未保存（无物可交付），告警后干净返回（原目标保持
    原样，零数据面变化）。
    """
    errors: list[str] = []
    if work.is_file():
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work, original)
        except OSError as exc:
            errors.append(f".aedt 拷回失败: {work} -> {original}（{exc}）")
    else:
        logger.warning(
            "ascii_workdir 交付: 工作副本不存在（新建工程未保存/未求解），"
            "无物可交付，原目标保持原样: %s", original)
    results_src = work.parent / f"{work.stem}.aedtresults"
    if results_src.is_dir():
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append(f"原目标父目录不可创建: {original.parent}（{exc}）")
            return errors
        results_dst = original.parent / f"{original.stem}.aedtresults"
        for src in sorted(results_src.rglob("*")):
            if not src.is_file():
                continue
            dst = results_dst / src.relative_to(results_src)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except OSError as exc:
                errors.append(
                    f".aedtresults 拷回失败: {src} -> {dst}（{exc}）")
    return errors


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


def last_desktop_message(desktop: Any) -> str | None:
    """best-effort 取 AEDT 最后一条 Desktop 错误消息（#413；#105 绝不二次抛）。

    与 pyaedt 同源配方（``general_methods`` 的 "Last Electronics Desktop
    Message" 提取链）：``odesktop.GetMessages("", "", 2)``（severity=2 错误
    级）取回消息列表，定位 ``[error]`` 标记从标记处截取——与日志行
    ``PyAEDT ERROR: Last Electronics Desktop Message - [error] ...`` 同一
    字段；全列表无标记时回落到末条消息原文。

    Parameters
    ----------
    desktop : Any
        pyaedt Desktop 实例（或裸 odesktop 对象）；None 亦可。

    Returns
    -------
    str | None
        消息文本；取不到（无 desktop/无 odesktop/调用异常/无消息）一律
        None——调用方注明 unknown，绝不因取消息而二次抛错（#105）。
    """
    try:
        target = getattr(desktop, "odesktop", None) or desktop
        if target is None or not hasattr(target, "GetMessages"):
            return None
        messages = [str(m) for m in (target.GetMessages("", "", 2) or [])]
    except Exception:
        return None
    if not messages:
        return None
    for message in reversed(messages):
        low = message.lower()
        if "[error]" in low:
            extracted = message[low.index("[error]"):].strip()
            return extracted or message.strip()
    return messages[-1].strip() or None


def _grpcsrv_port_from_cmdline(cmdline: str) -> int | None:
    """从 ansysedt 命令行解析 ``-grpcsrv`` 监听端口（#265 兜底武装）。

    实测形态（AEDT 2025.1 本机 WNUA，w8_pid_probe/probe_result.json）：
    ``"...ansysedt.exe" -grpcsrv 61359 -ng``（裸端口）；pyaedt 1.4.0
    ``_get_grpcsrv_args`` 另产出 ``host:port:InsecureMode`` 三段式
    （TCP/mTLS）。取 ``-grpcsrv`` 后随 token 按双形解析；无该旗标或
    不可解析一律 None（不猜）。
    """
    tokens = str(cmdline).split()
    for i, token in enumerate(tokens):
        if token == "-grpcsrv" and i + 1 < len(tokens):
            parts = tokens[i + 1].split(":")
            raw = parts[1] if len(parts) >= 2 else parts[0]
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def extract_desktop_pid(desktop: Any) -> int | None:
    """读 pyaedt Desktop 实例的 ``aedt_process_id``（#265 兜底武装）。

    该属性**只存在于 Desktop 类**（pyaedt 1.4.0 desktop.py:934 property；
    gRPC 形态由 ``__initialize`` 的 ``odesktop.GetProcessID()`` 赋值，
    desktop.py:3067）。app 级（Hfss/Hfss3dLayout）没有该属性——
    ``getattr(hfss, "aedt_process_id", None)`` 恒 None（W5/W6 误读根因，
    w8_pid_probe 静态+真机双证）。非整型值（mock/漂移形态）收敛 None。
    """
    pid = getattr(desktop, "aedt_process_id", None)
    if pid is None:
        return None
    try:
        return int(pid)
    except (TypeError, ValueError):
        return None


def resolve_desktop_pid(desktop: Any, *, fallback_cmdline_scan: bool = True) -> int | None:
    """会话 ansysedt PID 解析：主源属性 + 命令行扫描兜底（#265 兜底武装）。

    主源=:func:`extract_desktop_pid`（Desktop 级属性，实测本地新起/单例
    复用两路均有值，w8_pid_probe 真机双证）。兜底=desktop_guard 单源
    枚举（Get-CimInstance，pid/cmdline）取 ``-grpcsrv`` 端口与本会话
    ``desktop.port`` 一致的唯一进程——唯一才采信（多候选=端口歧义，不
    猜）；枚举失败/无匹配/端口缺失一律 None（best-effort，#105：观测
    不得阻塞主路径）。**远程会话传 ``fallback_cmdline_scan=False``**：
    枚举只看本机进程，远程 PID 属服务器侧，本地扫描会张冠李戴。

    Parameters
    ----------
    desktop : Any
        pyaedt Desktop 实例（或兼容 duck-type：aedt_process_id + port）。
    fallback_cmdline_scan : bool
        主源缺失时是否允许本机命令行扫描兜底（本地会话 True）。

    Returns
    -------
    int | None
        ansysedt PID；取不到 None（调用方按"兜底降级"如实记档）。
    """
    pid = extract_desktop_pid(desktop)
    if pid is not None:
        return pid
    if not fallback_cmdline_scan:
        return None
    port = getattr(desktop, "port", None)
    try:
        port_num = int(port) if port is not None else 0
    except (TypeError, ValueError):
        return None
    if port_num <= 0:
        return None
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes

        candidates = [
            proc["pid"] for proc in list_ansysedt_processes()
            if _grpcsrv_port_from_cmdline(proc["cmdline"]) == port_num
        ]
    except Exception:
        return None
    return candidates[0] if len(candidates) == 1 else None


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
) -> Iterator[None]:
    """远程 attach 四开关+一环境变量的作用域管理（共享单源，L1/L2/session 同款）。

    远程分支的 ``Desktop`` 构造必需（pyaedt 1.4.0 × AEDT 2025.1.0 无 SP
    实证配方，内部证据档；原实现见 remote_service
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
            # 本会话 ansysedt PID（#265 兜底武装，w8_pid_probe 批）：
            # connect 捕获（Desktop 级属性+命令行扫描兜底），close 清空。
            # 远程会话=服务器侧 PID（本地存活判定无意义，只记档）。
            self._desktop_pid: int | None = None
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
        # 必须与本机 pyaedt 配对版本一致（内核立规注记 规则 0）。
        remote_name = settings.get("remote_machine")
        remote_kwargs: dict[str, Any] = {}
        if remote_name:
            from rfauto.infra.remote_machines import (
                hfss_mtls_certs,
                resolve_machine,
            )

            cfg = resolve_machine(str(remote_name))
            # 版本配对交叉断言（内核立规注记 规则 0，审查分片 1 P1-1 附带项）：
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
                    "版本必须配对（AGENTS 规则 0）；请对齐 settings 的 "
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
                # #265 兜底武装：捕获本会话 ansysedt PID（Desktop 级属性
                # 主源+本地命令行扫描兜底；远程只取属性值记档，不做本机
                # 扫描——枚举看不到远端进程，w8_pid_probe 批）。
                self._desktop_pid = resolve_desktop_pid(
                    self.desktop,
                    fallback_cmdline_scan=self._remote is None,
                )
                logger.info(
                    "AEDT Desktop 连接成功 (%s%s)", version,
                    f", pid={self._desktop_pid}"
                    if self._desktop_pid is not None
                    else "，PID 未捕获（#265 兜底降级——残留清场走 "
                         "desktop_guard 枚举）")
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

    def check_session_health(self) -> dict[str, Any]:
        """会话毒化探针（#413）：依次调设计元数据原始查询，None=毒化。

        失败的边界/端口赋值后（#413，pyaedt 1.4.0 × AEDT 2025 R1 gRPC
        实证），AEDT 设计元数据查询面由 [] 静默转 None：
        ``oboundary.GetBoundaries()``/``odesign.GetVariables()``/
        ``GetSolutionType()``——后续所有操作连环失败且自动化脚本的
        finally 清理路径必死。本探针按 **返回值 None=毒化、[]/非
        None=健康** 判读；探针自身 try 全包绝不抛（#105）。

        探针源（键面恒定四探针，源对象未建立=unavailable 不计入毒化）：

        - ``self.hfss``（Hfss 实例，adapter open_or_create_project 挂载）：
          ``oboundary.GetBoundaries``/``odesign.GetVariables``/
          ``odesign.GetSolutionType``（#413 三签名）；
        - ``self.desktop``：``odesktop.GetProjectList``（桌面面活性，
          #413 实证桌面进程存活——若它也返 None 属更深层毒化，一并拦）。

        Returns
        -------
        dict[str, Any]
            键：

            - ``connected`` : bool，会话连接状态（is_connected）；
            - ``poisoned`` : bool，任一**可得**探针返回 None（#413 签名）；
            - ``probes`` : dict，逐探针状态——``healthy``（[]/非 None）/
              ``poisoned``（None）/``unavailable``（源对象未建立，如未开
              设计）/``error``（调用抛异常，传输级故障归 health_check/
              reconnect_with_backoff 面，不计入毒化）；
            - ``errors`` : dict，error 探针的异常摘要（观测面，#105）。
        """
        targets: list[tuple[str, Any, str, str]] = [
            ("oboundary.GetBoundaries", self.hfss, "oboundary",
             "GetBoundaries"),
            ("odesign.GetVariables", self.hfss, "odesign", "GetVariables"),
            ("odesign.GetSolutionType", self.hfss, "odesign",
             "GetSolutionType"),
            ("odesktop.GetProjectList", self.desktop, "odesktop",
             "GetProjectList"),
        ]

        probes: dict[str, str] = {}
        errors: dict[str, str] = {}
        poisoned = False
        for name, source, attr, method in targets:
            if source is None:
                probes[name] = "unavailable"
                continue
            try:
                obj = getattr(source, attr, None)
                if obj is None:
                    probes[name] = "unavailable"
                    continue
                value = getattr(obj, method)()
            except Exception as exc:
                probes[name] = "error"
                errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            if value is None:
                probes[name] = "poisoned"
                poisoned = True
            else:
                probes[name] = "healthy"
        return {
            "connected": self.is_connected,
            "poisoned": poisoned,
            "probes": probes,
            "errors": errors,
        }

    def require_healthy(self) -> dict[str, Any]:
        """关键操作前的毒化 fail-fast 门（#413）。

        任一可得探针返回 None 即抛
        :class:`~rfauto.core.errors.HfssSessionDeadError`（消息附 AEDT
        最后 Desktop 消息，取不到注明 unknown——:func:`last_desktop_message`
        best-effort，#105）；健康/不可探（如未开设计）原样返回探针结果。
        不自动重建——重建决策（:meth:`reconnect`）留给上层，业务操作
        不自动重试。

        Returns
        -------
        dict[str, Any]
            :meth:`check_session_health` 的探针结果（poisoned=False）。

        Raises
        ------
        HfssSessionDeadError
            #413 毒化签名（元数据查询返回 None）。
        """
        health = self.check_session_health()
        if not health["poisoned"]:
            return health
        poisoned_probes = [
            name for name, status in health["probes"].items()
            if status == "poisoned"
        ]
        last_msg = last_desktop_message(self.desktop)
        raise HfssSessionDeadError(
            "AEDT 会话已毒化（#413）：设计元数据查询返回 None（探针 "
            + ", ".join(poisoned_probes)
            + "）——最后 Desktop 消息: " + (last_msg or "unknown")
            + "；可用 HfssSession.reconnect() 重建会话（业务操作重试由"
            "上层决策）。",
            details={
                "probes": health["probes"],
                "probe_errors": health["errors"],
                "last_desktop_message": last_msg,
            },
        )

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
        self._desktop_pid = None

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

    def reconnect(self, settings: dict[str, Any] | None = None) -> None:
        """毒化后重建会话（#413 自动重建钩子，复用 connect 路径）。

        与 :meth:`reconnect_with_backoff` 的差异：单次直连不退避等待
        （#413 毒化不是 License 释放问题，等无用）；旧桌面优雅释放
        best-effort（``close_on_exit=False`` 不杀 AEDT 进程，只解绑
        gRPC 客户端）。业务操作不自动重试——失败的赋值不会因重建而
        变对，重试决策留给上层。

        Parameters
        ----------
        settings : dict, optional
            覆盖连接配置；缺省复用上次 connect 的配置
            （从未 connect 过=空配置走 connect 缺省值）。

        Raises
        ------
        ConnectFailedError
            重建失败（connect 路径既有传播，含 LicenseError 分支）。
        """
        eff_settings = (
            dict(settings) if settings is not None else dict(self._settings))
        try:
            if self.desktop is not None:
                self.desktop.release_desktop(
                    close_on_exit=False, close_projects=False)
        except Exception as exc:
            logger.warning("断开毒化旧连接时出错（忽略，#105）: %s", exc)
        self._connected = False
        self.desktop = None
        self.hfss = None
        self._desktop_pid = None
        self.connect(eff_settings)

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

    def _warn_pid_residue(self) -> None:
        """release 后 PID 残留探针（#265 武装，warn-only，#105 best-effort）。

        本地会话且已捕获 PID 时，release_desktop 返回后若该 PID 仍存活
        （pyaedt ``QuitApplication``+``os.kill(pid, 9)`` 兜底失效的
        #265 孤儿形态）记 warning 留 desktop_guard 清场/人工核对——
        **不就地击杀**：杀进程原语单源在 infra/desktop_guard.py（df5
        静态钉），且 release 异常/超时形态下桌面可能仍在求解，杀否由
        上层清场决策。远程会话 PID 属服务器侧，本地存活判定无意义，
        一律跳过。任何异常吞掉（探针绝不阻塞 close 主路径）。
        """
        if self._desktop_pid is None or self._remote is not None:
            return
        try:
            from rfauto.infra.desktop_guard import process_alive

            alive = process_alive(self._desktop_pid)
            if alive:
                logger.warning(
                    "release 后 ansysedt pid=%s 仍存活（#265 孤儿风险）"
                    "——留 desktop_guard 清场或人工核对命令行后处置",
                    self._desktop_pid)
        except Exception as exc:
            logger.warning("PID 残留探针失败（忽略，#105）: %s", exc)

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
                self._warn_pid_residue()
                self._restore_hpc(hpc)
                self._connected = False
                self.desktop = None
                self.hfss = None
                self._desktop_pid = None
                logger.info("AEDT Desktop 会话已关闭")

    @property
    def desktop_pid(self) -> int | None:
        """本会话 ansysedt 进程 PID（#265 兜底武装；未连接/未捕获=None）。

        本地会话=本机 PID（可喂 desktop_guard 精确击杀/存活判定）；
        远程会话=服务器侧 PID（只记档，服务器侧清场消费，内核立规注记 规则
        0b 任务毕清理）。
        """
        return self._desktop_pid

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
