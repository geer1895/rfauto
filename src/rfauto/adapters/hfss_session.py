"""HfssSession — gRPC 桌面会话单例（P0 桩实现）。

集中管理 AEDT Desktop 连接，供 HfssAdapter 委托使用。
所有 ansys.aedt.core import 延迟到方法内部，避免模块级导入失败。

P0 阶段：桩实现，核心方法抛出 NotImplementedError 并给出实现指引。
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import os
import re
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


# ─── T-Q26a HFSS 护栏（2026-11-06 晶圆键合外部使用者实测三坑，Q-X1 席）────────
# 来源：D:/晶圆键合/rfauto_反馈与实测经验.md §3 P0（坑①积分线表达式字符串、
# 坑② sweep 重名静默改名→导出 solution not found、坑③非 ASCII 路径无提示）。
# 坑③通用面在 infra.ascii_paths（ensure_ascii_workdir），工程文件专用面在
# 本模块 P5 节（既有）。

#: T-Q26a 坑① 修法指引（报错文案共用段——错误类型必须是"参数错误"而非
#: "边界创建失败"：pyaedt 对表达式字符串入参抛 'Failed to create boundary
#: Wave Port' 且 traceback 指向 material 检查，误导排查）。
_INTEGRATION_LINE_GUIDANCE = (
    "——pyaedt 对表达式/变量名字符串入参以 'Failed to create boundary Wave "
    "Port'（波端口）或同类边界创建失败报错，且 traceback 指向 material 检查，"
    "误导排查（晶圆键合用户实测 P0-3.1，2026-11-06）。修法=在 Python 侧先"
    "求值为 float 再传入：坐标按 model_units 解释，变量值可用 "
    "value_with_units / hfss['变量名'] 先取值。")


def validate_integration_line(
    integration_line: Any, *, param: str = "integration_line"
) -> None:
    """波端口/集总端口积分线数值前置校验（T-Q26a 坑①，反馈 P0-3.1）。

    校验坐标表形态的积分线（``[[起点 x,y,z], [终点 x,y,z]]``）每一坐标项
    为数值（``int``/``float``，``bool`` 显式拒绝——bool 是 int 子类）；
    非数值（表达式/变量名字符串如 ``'-L_cav/2'``、单位串等）→
    ``ValueError``（**参数错误**，先于任何 pyaedt 调用——绝不落到"边界
    创建失败"的误导性 traceback 里）。

    直通形态（不做坐标校验，交 pyaedt 原生处理）：

    - ``None``——pyaedt 自动积分线；
    - 非 list/tuple 入参——方向式积分线（pyaedt ``Gravity`` 枚举、
      ``"ZPos"`` 方向串等），仓内 wilkinson/branchline/patch 插件在用。

    用法（外部借用 rfauto 运行时直接调 pyaedt 的使用者，wave_port 与
    lumped_port 同一口径）::

        from rfauto.adapters.hfss_session import validate_integration_line

        line = [[-2.5, 0.0, -0.2], [-2.5, 0.0, 0.2]]   # 数值坐标（mm=model_units）
        validate_integration_line(line)                # 不通过即 ValueError
        hfss.wave_port(assignment=sheet, integration_line=line)

    Notes
    -----
    仓内既有坐标表路径（hfss_builder_utils.wave_port_cpw 等）走规划器数值
    → 单位串换算（``"-2.5mm"`` 形态，K7/remote 真机验证过 pyaedt 可解析），
    **不经本校验器**；本校验器面向"直接传坐标"的调用面，按反馈实测口径
    只放行数值。
    """
    if integration_line is None:
        return
    if not isinstance(integration_line, (list, tuple)):
        # 方向式积分线（Gravity 枚举 / 方向串）直通 pyaedt
        return
    if len(integration_line) != 2 or not all(
        isinstance(p, (list, tuple)) for p in integration_line
    ):
        raise ValueError(
            f"{param} 坐标表形态需为 [[起点 x,y,z], [终点 x,y,z]]（两点，"
            f"每点 2-3 个数值坐标项），得到 {integration_line!r}。"
            "方向式积分线请传 pyaedt 方向枚举/方向串（如 Gravity.ZPos 或 "
            "'ZPos'），不要与坐标表混用。")
    for point in integration_line:
        if len(point) not in (2, 3):
            raise ValueError(
                f"{param} 每点需 2-3 个坐标项 [x, y(, z)]，得到 {point!r}")
        for item in point:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValueError(
                    f"{param} must be numeric coordinates in model units; "
                    f"got {item!r}{_INTEGRATION_LINE_GUIDANCE}")


def normalize_sweep_names(sweeps_raw: Any) -> list[str]:
    """``hfss.get_sweeps`` 返回面归一（str 与对象 ``.name`` 双形态）。

    pyaedt 各版本 get_sweeps 返回 str 列表或 SweepHFSS 对象列表（hfss_adapter
    既有消费惯例双形态兼容）；归一为 str 名单，逐项取 ``.name`` 时任何异常
    跳过该项（best-effort，观测面不阻塞主路径，#105）。
    """
    if not sweeps_raw:
        return []
    names: list[str] = []
    for item in sweeps_raw:
        if isinstance(item, str):
            names.append(item)
        else:
            name = getattr(item, "name", None)
            if isinstance(name, str):
                names.append(name)
    return names


def resolve_sweep_actual_name(
    hfss: Any,
    setup_name: str,
    requested: str,
    created: Any = None,
) -> str:
    """``create_linear_count_sweep`` 重名静默改名捕获（T-Q26a 坑②前半）。

    病灶（晶圆键合用户实测，反馈 P0-3.2）：AEDT 对重名 sweep **静默改名**
    （``WARNING: Sweep Sweep is already present. Sweep has been renamed in
    Sweep_NVR7O5``），pyaedt 不透传该改名——调用方拿请求名去导出即底层
    gRPC ``solution 'setup1:sweep' was not found``，无改名提示。

    解析实际名（best-effort，查询失败一律回退请求名不阻塞主流程 #105）：

    1. ``created`` 对象带 str ``.name``（SweepHFSS 形态）→ 直接取（pyaedt
       改名发生在返回前，obj.name 即实际名）；
    2. 否则读 ``hfss.get_sweeps(setup_name)``（双形态归一）：
       请求名在列 → 请求名；恰有一个候选以 ``f"{requested}_"`` 开头
       （AEDT 改名惯例 ``<原名>_<随机后缀>``）→ 该候选并 **warning 带
       两侧名字**；无匹配 → 请求名。
    """
    created_name = getattr(created, "name", None) if created is not None else None
    if isinstance(created_name, str) and created_name:
        if created_name != requested:
            logger.warning(
                "sweep 重名被 AEDT 静默改名: 请求 '%s' → 实际 '%s'"
                "（后续导出/判读一律用实际名）", requested, created_name)
        return created_name
    try:
        names = normalize_sweep_names(hfss.get_sweeps(setup_name))
    except Exception as exc:
        logger.debug("get_sweeps(%s) 查询失败（改名捕获跳过）: %s",
                     setup_name, exc)
        return requested
    if requested in names:
        return requested
    renamed = [n for n in names if n.startswith(f"{requested}_")]
    if len(renamed) == 1:
        logger.warning(
            "sweep 重名被 AEDT 静默改名: 请求 '%s' → 实际 '%s'"
            "（后续导出/判读一律用实际名；导出用请求名即 'solution not "
            "found'）", requested, renamed[0])
        return renamed[0]
    return requested


def resolve_export_sweep_name(
    hfss: Any,
    setup_name: str,
    sweep: str | None = None,
) -> str | None:
    """导出侧 sweep 解析（T-Q26a 坑②后半，反馈 P0-3.2 建议口径）。

    - ``sweep`` 显式给定 → 先对 ``get_sweeps(setup_name)`` 实名核对：
      不在列 → ``ValueError`` 列出候选名 + 改名指引（把底层 gRPC
      ``solution not found`` 前置成可行动的参数错误）；查询失败（通道
      抖动）→ 放行显式名交 pyaedt（best-effort 核对，#105）；
    - ``sweep=None`` → 单 sweep 自动采用；零 sweep → ``None``（setup 主
      解口径，既有行为）；**多 sweep → ``ValueError`` 列候选名**并要求
      显式指定（多 sweep 静默取第一个正是坑②的病灶形态——导出的可能
      不是调用方想要的 sweep）。
    """
    try:
        names = normalize_sweep_names(hfss.get_sweeps(setup_name))
    except Exception as exc:
        if sweep is not None:
            logger.debug("get_sweeps(%s) 查询失败（显式名放行）: %s",
                         setup_name, exc)
            return sweep
        logger.debug("get_sweeps(%s) 查询失败（回退 setup 主解）: %s",
                     setup_name, exc)
        return None
    if sweep is not None:
        if sweep in names or not names:
            return sweep
        raise ValueError(
            f"sweep '{sweep}' 不存在于 setup '{setup_name}'；候选: "
            f"{', '.join(names)}。注意 pyaedt/AEDT 对重名 sweep 会静默改名"
            "（如 'Sweep' → 'Sweep_NVR7O5'，晶圆键合用户实测 P0-3.2）——"
            "用旧名导出的症状即底层 gRPC solution not found；请用实际名"
            "（可先 create 后取 resolve_sweep_actual_name 结果）。")
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        raise ValueError(
            f"setup '{setup_name}' 有多个 sweep（{', '.join(names)}）——"
            "请显式指定 sweep=<名>（自动取第一个会把导出口径押在未声明的"
            "隐式选择上；重名静默改名后用旧名导出即 solution not found，"
            "晶圆键合用户实测 P0-3.2）。")
    return None


# ─── T-Q26c HFSS 杂项簇（2026-11-07 晶圆键合外部使用者实测四件，Q-X8 席）──────
# 来源：D:/晶圆键合/rfauto_反馈与实测经验.md §3.5/§3.6/P2 表（四件全实测）：
# 件①deembed 单位语义未文档化（P1-3.5）；件②validate_full_design 返回顺序
# 反直觉（P1-3.6，(messages, success) 与生态惯例 (ok, msgs) 相反）；件③工程
# 复用累积对象 + 求解前不检测文件占用（P2 前两项）；件④export_model_picture
# 方向名合法值未文档化 + 非图形模式报误导性 'NoneType' object has no
# attribute 'recreate_application'（P2 后两项）。
# 仓内不经 deembed/export_model_picture 直调面（全仓 grep 零调用点）——四件
# 全按 Q-X1 validate_integration_line 先例落**session 公共校验器/守卫函数**，
# 供直接借 rfauto venv 调 pyaedt 的外部使用者在调用前显式消费；只增不改
# 既有函数。pyaedt 1.9.0 源码口径（本 venv 实测）：hfss.py wave_port 把
# deembed 经 ``value_with_units`` 写入 ``DeembedDist``（数值型补工程模型单位）；
# validate_full_design 返回 ``(val_list, validation_ok)``；export_model_picture
# 的 orientation 直传 AEDT ``ExportModelImageToFile``，非图形判据在
# ``desktop_class.non_graphical``。

#: T-Q26c 件③ 锁文本属主字段与读取上限（与 service/resource_janitor 的
#: ``DesktopProcessID`` 解析同源口径；adapters 层禁 import service——本模块
#: 局部复刻最小判据，语义以 janitor 为准）。实测锁文本格式：顶层
#: ``DesktopProcessID=<pid>`` 一行 + Marshall 块内 ``ProcID=`` 同值（只取顶层行）。
_AEDT_PROJ_SUFFIX = ".aedt"
_LOCK_SUFFIX = ".lock"
_AEDT_NAME_PREFIX = "ansysedt"
_LOCK_TEXT_READ_LIMIT = 64 * 1024
_RE_LOCK_DESKTOP_PID = re.compile(r"^\s*DesktopProcessID=(\d+)\s*$", re.MULTILINE)


def _is_aedt_lock_file(path: Path) -> bool:
    """``*.aedt.lock`` 命名，或与同名 ``*.aedt`` 工程文件伴生的 ``*.lock``。

    与 service/resource_janitor_service._is_aedt_lock 同语义（分支次序有
    意义：``x.aedt.lock`` 的 ``with_suffix('.aedt')`` 会得 ``x.aedt.aedt``，
    必须先走命名分支——janitor 同款次序）。
    """
    if path.suffix.lower() != _LOCK_SUFFIX:
        return False
    if path.name.lower().endswith(_AEDT_PROJ_SUFFIX + _LOCK_SUFFIX):
        return True
    return path.with_suffix(_AEDT_PROJ_SUFFIX).is_file()


def find_aedt_locks(target: str | Path) -> list[Path]:
    """定位工程/目录旁的 AEDT 锁文件（件③证据链第一环）。

    - 入参是目录 → 扫描**直接子项**（一层，不递归——工作目录形态）；
    - 入参是 ``.aedt`` 工程文件 → 查两种伴生锁形（``<工程>.aedt.lock`` 与
      ``<工程>.lock``，后者以同目录伴生 ``.aedt`` 为条件，janitor 同口径）；
    - 入参是 ``.lock`` 文件本身 → 原样返回；
    - 路径不存在/无锁 → 空列表。

    排序输出（确定性行为，跨调用可比较）。
    """
    p = Path(target)
    if p.is_dir():
        # 文件锁与目录锁都收（AEDT 亦有目录形锁；janitor _scan_locks 同口径）
        return sorted(
            child for child in p.iterdir() if _is_aedt_lock_file(child)
        )
    if p.is_file():
        if _is_aedt_lock_file(p):
            return [p]
        if p.name.lower().endswith(_AEDT_PROJ_SUFFIX):
            candidates = [Path(str(p) + _LOCK_SUFFIX), p.with_suffix(_LOCK_SUFFIX)]
            return sorted({c for c in candidates if c.exists()})
        return []
    if p.name.lower().endswith(_AEDT_PROJ_SUFFIX):
        # 工程尚不存在——锁也不该存在；两种伴生形均查（自然为空）
        candidates = [Path(str(p) + _LOCK_SUFFIX), p.with_suffix(_LOCK_SUFFIX)]
        return sorted({c for c in candidates if c.exists()})
    return []


def _read_lock_text(lock_path: Path) -> str | None:
    """读锁文本（目录锁/不可读/解码全败 → None=属主不可判，janitor 同语义）。"""
    if lock_path.is_dir():
        return None
    try:
        raw = lock_path.read_bytes()[:_LOCK_TEXT_READ_LIMIT]
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except ValueError:
        try:
            return raw.decode("latin-1")
        except ValueError:
            return None


def _is_aedt_family_name(name: Any) -> bool:
    return bool(name) and str(name).lower().startswith(_AEDT_NAME_PREFIX)


def _lock_owner_liveness(pid: int) -> str:
    """锁属主进程存活三态：``alive`` / ``dead`` / ``unknown``（件③）。

    主源=psutil（venv 在装但 pyproject 未声明——janitor 同款**可选增强**
    模式：可导入时按进程名做 ansysedt 族核验，PID 被非 ansysedt 进程复用
    判 dead）；不可导入时兜底 infra.desktop_guard.process_alive（PowerShell
    存活判定，无族名核验——属主是否真 ansysedt 由 DesktopProcessPath 佐证
    面接管）；查询超时/异常一律 unknown（fail-unknown，E3-8 同源）。
    """
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            name = psutil.Process(int(pid)).name()
        except psutil.Error:
            return "dead"
        except Exception:
            return "unknown"
        if not isinstance(name, str) or not name:
            return "unknown"
        return "alive" if _is_aedt_family_name(name) else "dead"
    try:
        from rfauto.infra.desktop_guard import process_alive

        state = process_alive(pid)
    except Exception:
        return "unknown"
    if state is True:
        return "alive"
    if state is False:
        return "dead"
    return "unknown"


def _cmdline_references(cmdline: str, target: Path) -> bool:
    """ansysedt 命令行是否引用目标路径（件③证据链第二环，#265 家法）。

    全路径与文件名两针**都带边界**匹配（normcase 后逐次出现点检查前后
    界符）：名字前后须是引号/空白/路径分隔——防 ``my_proj.aedt`` 误匹配
    ``proj.aedt``、``proj.aedt.lock`` 误匹配 ``proj.aedt`` 的子串假阳性；
    尾边界含 ``\\``（目录目标可被其内文件路径前缀命中——工作目录占用
    证据）。命令行引用工程是 GUI 以文件方式启动/OpenProject 留痕的
    best-effort 通道：gRPC 会话打开工程不走命令行，锁文件才是权威通道
    （本函数只作补充证据）。
    """
    norm = os.path.normcase(str(cmdline))
    full = os.path.normcase(str(target))
    name = os.path.normcase(target.name)
    boundary_before = ('"', "'", " ", "\\", "/", "")
    boundary_after = ('"', "'", " ", "\\", "")
    for needle in (full, name):
        if not needle:
            continue
        start = 0
        while True:
            idx = norm.find(needle, start)
            if idx < 0:
                break
            before = norm[idx - 1] if idx > 0 else ""
            end = idx + len(needle)
            after = norm[end] if end < len(norm) else ""
            if before in boundary_before and after in boundary_after:
                return True
            start = idx + 1
    return False


def detect_project_occupancy(project_path: str | Path) -> dict[str, Any]:
    """工程占用检测（件③ P2：solve 前检测 `.aedt.lock`/已运行 ansysedt）。

    病灶（晶圆键合用户实测，反馈 P2）：另一 AEDT GUI 已打开同一 ``.aedt``
    时求解报 ``Error updating solution state for solution: LastAdaptive``——
    看不出是文件占用。本函数把该面提前为**显式证据链**，solve/重建前调用。

    证据链（两通道并取，占优者定 occupied）：

    1. **锁通道**（权威）：工程旁 ``.aedt.lock``/伴生 ``.lock``（
       :func:`find_aedt_locks`）→ 解析顶层 ``DesktopProcessID`` →
       属主存活判定（:func:`_lock_owner_liveness`）；
    2. **进程命令行通道**（补充）：infra.desktop_guard 枚举 ansysedt
       （pid/ppid/cmdline，#265 家法——核对命令行）→ 带边界匹配本工程
       （:func:`_cmdline_references`）。

    Returns
    -------
    dict[str, Any]
        具名结构（janitor ``lock_owner_verdict`` 同款普通 dict 惯例）：

        - ``occupied`` : ``True``/``False``/``None``——None=不可判定
          （枚举失败、属主存活查不出、目录锁无属主文本；fail-unknown）；
        - ``lock_present`` / ``lock_path`` / ``owner_pid`` / ``owner_alive``
          （``alive``/``dead``/``unknown``/``None``=无属主可查）/
          ``ansysedt_matching_pids`` / ``stale``（锁在但属主已死且无进程
          引用=陈旧锁，janitor 清理面可清）/ ``reason``（人类可读判据）。

    观测面 best-effort（#105）：枚举/读锁任何失败折 None/空表，绝不抛——
    占用判定不阻塞主路径；破坏性方向（删除/击杀）的 fail-closed 由
    :func:`prepare_fresh_workdir` 另行把守。
    """
    p = Path(project_path)
    locks = find_aedt_locks(p)
    lock_path = locks[0] if locks else None
    owner_pid: int | None = None
    owner_alive: str | None = None
    for lock in locks:
        text = _read_lock_text(lock)
        if text is None:
            continue
        match = _RE_LOCK_DESKTOP_PID.search(text)
        if match is not None:
            owner_pid = int(match.group(1))
            owner_alive = _lock_owner_liveness(owner_pid)
            break

    matching_pids: list[int] = []
    enum_error: str | None = None
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes

        procs = list_ansysedt_processes()
    except Exception as exc:
        enum_error = f"{type(exc).__name__}: {exc}"
        procs = []
    for proc in procs or []:
        cmdline = proc.get("cmdline") or ""
        if _cmdline_references(cmdline, p):
            pid = proc.get("pid")
            try:
                matching_pids.append(int(pid))
            except (TypeError, ValueError):
                continue

    stale: bool | None = None
    if matching_pids:
        occupied: bool | None = True
        reason = (
            f"检测到 {len(matching_pids)} 个 ansysedt 进程命令行引用本工程"
            f"（pid={matching_pids}，#265 家法核对命令行）——工程被 GUI/会话占用"
        )
    elif not locks:
        if enum_error:
            occupied = None
            reason = (
                f"无 AEDT 锁文件，但 ansysedt 进程枚举失败（fail-unknown）: "
                f"{enum_error}"
            )
        else:
            occupied = False
            reason = "无 AEDT 锁文件、无命令行匹配的 ansysedt 进程——工程未被占用"
    elif owner_pid is None:
        occupied = None
        reason = (
            f"锁文件存在但无 DesktopProcessID 属主（目录锁或非标格式），占用"
            f"不可判定: {lock_path}"
        )
    elif owner_alive == "alive":
        occupied = True
        stale = False
        reason = f"锁属主 ansysedt 进程存活（pid={owner_pid}）——工程被 GUI/会话占用"
    elif owner_alive == "dead":
        occupied = False
        stale = not matching_pids
        reason = (
            f"锁属主已退出或 PID 已被复用（pid={owner_pid}）——陈旧锁可清"
            "（resource_janitor/remote_hfss_cleanup 清理面）"
        )
    else:
        occupied = None
        stale = None
        reason = (
            f"锁属主存活不可判定（pid={owner_pid}，psutil 缺失或查询异常，"
            "fail-unknown）: " + str(lock_path)
        )
    return {
        "occupied": occupied,
        "lock_present": bool(locks),
        "lock_path": str(lock_path) if lock_path else None,
        "owner_pid": owner_pid,
        "owner_alive": owner_alive,
        "ansysedt_matching_pids": matching_pids,
        "stale": stale,
        "reason": reason,
    }


def ensure_project_not_occupied(project_path: str | Path) -> dict[str, Any]:
    """solve/重建前置门（件③）：占用即 ValueError，未知态告警放行。

    ``occupied=True`` → ``ValueError``（消息带证据链 + 清场指引——把反馈
    实测的 ``Error updating solution state`` 暗坑前置为可行动错误）；
    ``occupied=None``（fail-unknown）→ warning 放行并注明（求解进被占工程
    是可恢复失败，不值得为探测面故障阻塞；破坏性方向另行
    :func:`prepare_fresh_workdir` fail-closed）；``False`` 原样放行。
    返回 :func:`detect_project_occupancy` 报告（调用方留档/续链）。
    """
    report = detect_project_occupancy(project_path)
    if report["occupied"] is True:
        raise ValueError(
            f"工程被 GUI/会话占用——拒绝继续: {project_path}（{report['reason']}）。"
            "请先关闭占用该工程的 AEDT GUI 会话，或经 desktop_guard/"
            "remote_hfss_cleanup 清场（核对命令行后只杀目标 PID，#265/#245 家法）。"
            "反馈实测（P2，2026-11-06）：另一 AEDT GUI 已打开同一 .aedt 时求解"
            "报 'Error updating solution state for solution: LastAdaptive'，"
            "看不出是文件占用——本门把该面提前到 solve 前。"
        )
    if report["occupied"] is None:
        logger.warning(
            "工程占用不可判定（fail-unknown，放行继续）: %s —— %s",
            project_path, report["reason"],
        )
    return report


def prepare_fresh_workdir(path: str | Path) -> Path:
    """显式重建工作目录（件③ P2 `fresh_project`/`rebuild` 语义）。

    病灶（反馈 P2）：复用上次失败的工程再建一次 → 对象与 sweep 累积
    （``Box1_1``、``Sweep_NVR7O5``）。本函数=**调用方显式指令**的清目录
    入口：删除整个工作目录树后重建空目录（不可恢复）。

    责任声明（防误删，AGENTS 规则 3 白名单删除精神）：

    - **rfauto 任何链路都不会自动调用本函数**（禁自动 rmtree——重建只
      能由调用方显式发起）；
    - 调用前自行确认目录内容无需要保留的产物（runs/ 湖、账本、工程外
      手工文件一律禁传本函数）；
    - 传**工作目录**（工程 ``.aedt`` 所在目录）或期望新建的目录路径；
      盘根/文件系统根（``parent == 自身``）显式拒绝；
    - 目录内存在**活属主锁/命令行匹配的 ansysedt** → ValueError 拒删
      （先关 GUI/清场）；占用**不可判定**（枚举失败/属主查不出/目录锁
      无属主）→ 一律拒删（删除是破坏性方向，fail-closed 同
      desktop_guard.kill_orphan_ansysedt_desktops strict=True 口径）；
      陈旧锁（属主已死）随目录一并清除，无需预清。

    Returns
    -------
    Path
        归一化（abspath）后的工作目录路径——已存在且为空，可直接
        ``open_or_create_project``。

    Raises
    ------
    ValueError
        盘根/非目录/占用或占用不可判定。
    RuntimeError
        目录树删除失败（文件被占——先关 AEDT）。
    """
    p = Path(os.path.abspath(str(Path(path))))
    if p.parent == p:
        raise ValueError(
            f"prepare_fresh_workdir 拒绝清空文件系统根/盘根: {p}——"
            "请传工程工作目录（.aedt 所在目录或期望新建目录）"
        )
    if p.exists() and not p.is_dir():
        raise ValueError(f"prepare_fresh_workdir 目标不是目录: {p}")
    if p.is_dir():
        report = detect_project_occupancy(p)
        if report["occupied"] is True:
            raise ValueError(
                f"工作目录内工程被 GUI/会话占用——拒绝删除: {p}"
                f"（{report['reason']}）。先关闭 AEDT GUI/清场后再重建"
                "（desktop_guard/remote_hfss_cleanup 面）。"
            )
        if report["occupied"] is None:
            raise ValueError(
                f"工作目录占用不可判定——拒绝删除（破坏性方向 fail-closed，"
                f"同 kill_orphan_ansysedt_desktops strict=True 口径）: {p}"
                f"（{report['reason']}）"
            )
    if p.is_dir():
        try:
            shutil.rmtree(p)
        except OSError as exc:
            raise RuntimeError(
                f"工作目录删除失败（文件被占用——先关闭 AEDT 会话）: {p}（{exc}）"
            ) from exc
    p.mkdir(parents=True, exist_ok=True)
    logger.info("prepare_fresh_workdir: 工作目录已重建（空）: %s", p)
    return p


# ─── T-Q26c 件①（P1-3.5）deembed 单位语义 ────────────────────────────────────
# pyaedt 1.9.0 hfss.py 源码口径：wave_port(deembed=...) →
# ``props["DeembedDist"] = self.value_with_units(deembed)``——value_with_units
# 对数值入参追加 ``units.length``（**工程 model_units**，HFSS 新工程缺省
# mm；pyaedt docstring 写 "in millimeters" 只在 model_units=mm 时严格成立），
# 对**带单位字符串**原样透传（decompose 检测到单位即直通），对不带单位的
# 表达式串追加 model_units 后交 AEDT 求值。


def validate_deembed_distance(deembed: Any, *, param: str = "deembed") -> None:
    """波端口 deembed 距离前置校验 + 单位语义文档化（件①，反馈 P1-3.5）。

    病灶（晶圆键合用户实测）：``wave_port(..., deembed=0.3)`` 签名只写
    ``float``，无法确认按 ``model_units``(mm) 还是 m 解释，只能靠结果反推。

    单位语义（pyaedt 1.9.0 源码实测定谳，写死在此防再查）：

    - **数值型（int/float）**：按工程 **model_units** 解释——pyaedt 经
      ``value_with_units(deembed)`` 追加 ``units.length`` 写入
      ``DeembedDist``（HFSS 新工程缺省 mm，传 0.3 即 0.3mm）；
    - **字符串型**：带单位距离串（``"0.3mm"``）被 ``value_with_units``
      原样透传；不带单位的表达式/变量名串由 AEDT 按 model_units 求值。
      注意 AEDT **表达式内裸数**按内部 SI（米）解释——``w_s+0.04`` 的
      0.04 是 0.04 m（反馈 §4 变量单位坑的相邻面），与本参数数值型补
      model_units 语义**不同**；
    - **None**：pyaedt ``DoDeembed=False``（禁用 deembed），直通。

    校验口径（Q-X1 validate_integration_line 同款——参数错误 fail-loud，
    先于任何 pyaedt 调用）：``None``/数值（有限、≥0；``bool`` 显式拒绝）/
    非空字符串放行；负距离（deembed=0 即禁用，负值非物理）、NaN/Inf、
    空串、其余类型 → ``ValueError``。

    用法（外部借 rfauto venv 直调 pyaedt 的使用者）::

        from rfauto.adapters.hfss_session import validate_deembed_distance

        validate_deembed_distance(0.3)       # 0.3 mm=model_units（HFSS 缺省）
        validate_deembed_distance("0.3mm")   # 带单位，原样透传
        hfss.wave_port(assignment=sheet, deembed=0.3)
    """
    if deembed is None:
        return
    if isinstance(deembed, bool):
        raise ValueError(
            f"{param} 须为 float | str | None，得到布尔值 {deembed!r}"
            "（bool 是 int 子类，True 会静默当 1.0 个 model_units 距离）")
    if isinstance(deembed, (int, float)):
        value = float(deembed)
        if not math.isfinite(value):
            raise ValueError(
                f"{param} 须为有限数值，得到 {deembed!r}（NaN/Inf 经 "
                "value_with_units 写入 DeembedDist 即垃圾几何，fail-loud）")
        if value < 0:
            raise ValueError(
                f"{param} 距离须 ≥0（0=禁用 deembed，pyaedt DoDeembed=False），"
                f"得到 {deembed!r}——负距离非物理，请确认是否想传 None 禁用")
        return
    if isinstance(deembed, str):
        if not deembed.strip():
            raise ValueError(
                f"{param} 字符串形态不可为空——带单位距离串（如 '0.3mm'）"
                "或表达式/变量名（AEDT 按 model_units 求值）")
        return
    raise ValueError(
        f"{param} 须为 float | str | None（数值按 model_units 解释；字符串"
        "带单位原样透传/表达式由 AEDT 求值），得到 "
        f"{type(deembed).__name__}: {deembed!r}——单位语义见本函数 docstring"
        "（反馈 P1-3.5：0.3 按 HFSS 缺省 model_units 即 mm，非 m）")


# ─── T-Q26c 件②（P1-3.6）validate_full_design 具名包装 ──────────────────────


def validate_design_named(
    hfss: Any,
    *,
    design: str | None = None,
    ports: int | None = None,
) -> dict[str, Any]:
    """``validate_full_design`` 具名包装（件②，反馈 P1-3.6）。

    病灶（晶圆键合用户实测）：pyaedt 返回 ``(messages, success)``——解包
    顺序与 pyaedt 生态惯例 ``(ok, msgs)`` **相反**；按后者写时把 list 当
    bool 用，``len()`` 直接 TypeError。本包装返回**具名结构**消除解包歧义。

    Returns
    -------
    dict[str, Any]
        键面（janitor/check_session_health 同款普通 dict 惯例）：

        - ``ok`` : bool——pyaedt ``validation_ok``（validate_simple 判定 +
          端口数核对，**权威判定面**；不因消息文本里出现 [error] 降级——
          Desktop 消息队列可能带本次校验之前的旧消息，观察面不回写判定）；
        - ``errors`` / ``warnings`` : list[str]——消息文本 ``[error]``/
          ``[warning]`` 标记分类（大小写不敏感；观察面，供判读与留档）；
        - ``raw`` : list[str]——pyaedt 原始消息列表原样保真。

    Parameters
    ----------
    hfss : Any
        pyaedt Hfss 实例（``None``/缺方法 → ValueError，拒绝静默伪结果）。
    design : str | None
        目标设计名（None=当前设计，pyaedt 语义透传）。
    ports : int | None
        期望激励数（含模数合计；None=不核对，pyaedt 语义透传）。

    Raises
    ------
    ValueError
        hfss 缺失/无方法、返回形态漂移（非 2 元组、第二元素非 bool——
        具名包装拒绝猜测解包，版本漂移 fail-loud）。
    """
    if hfss is None:
        raise ValueError(
            "hfss 实例缺失——validate_design_named 需要已连接的 pyaedt Hfss "
            "实例（未连接先 HfssSession.connect / open_or_create_project）")
    validate = getattr(hfss, "validate_full_design", None)
    if not callable(validate):
        raise ValueError(
            f"hfss 无 validate_full_design 方法（类型 {type(hfss).__name__}）"
            "——pyaedt 版本漂移或传入了非 Hfss 对象")
    result = validate(design=design, output_dir=None, ports=ports)
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise ValueError(
            "validate_full_design 返回形态漂移（期望 2 元组 (messages, ok)），"
            f"得到 {type(result).__name__}——具名包装拒绝猜测解包"
            "（反馈 P1-3.6 的病灶即解包歧义）")
    raw_items, ok_flag = result
    if not isinstance(ok_flag, bool):
        raise ValueError(
            "validate_full_design 第二返回值须为 bool（成功标志），得到 "
            f"{type(ok_flag).__name__}: {ok_flag!r}——注意解包顺序是 "
            "(messages, success)（反馈 P1-3.6），具名结构已消除该歧义")
    raw = [str(m) for m in (raw_items or []) if m is not None]
    errors = [m for m in raw if "[error]" in m.lower()]
    warnings = [m for m in raw if "[warning]" in m.lower()]
    return {
        "ok": bool(ok_flag),
        "errors": errors,
        "warnings": warnings,
        "raw": raw,
    }


# ─── T-Q26c 件④（P2 后两项）export_model_picture 合法值 + 非图形守卫 ─────────

#: ``post.export_model_picture(orientation=...)`` 合法方向名常量表（件④）。
#: pyaedt 1.9.0 post_common_3d.export_model_picture docstring 口径：``"top"``
#: ``"bottom"`` ``"right"`` ``"left"`` ``"front"`` ``"back"`` ``"trimetric"``
#: ``"dimetric"`` ``"isometric"``，或已加入 Orientation List 的自定义视图名。
#: 本表取 AEDT 报告器/GUI 拼写（首字母大写，反馈实测 ``"Isometric"`` 可用；
#: AEDT 匹配大小写不敏感，本函数归一到此拼写）。
MODEL_PICTURE_ORIENTATIONS: tuple[str, ...] = (
    "Isometric",
    "Trimetric",
    "Dimetric",
    "Top",
    "Bottom",
    "Front",
    "Back",
    "Left",
    "Right",
)

#: orientation 缺省（pyaedt 1.9.0 签名缺省 "isometric" 同目标，归一拼写）。
DEFAULT_MODEL_PICTURE_ORIENTATION = "Isometric"


def normalize_model_picture_orientation(
    orientation: Any, *, allow_custom: bool = False,
) -> str:
    """export_model_picture 方向名归一/校验（件④，反馈 P2）。

    病灶（晶圆键合用户实测）：传 ``"iso"`` → AEDT 报
    ``orientation name iso doesn't exist`` 且**无候选提示**。

    - ``None`` → :data:`DEFAULT_MODEL_PICTURE_ORIENTATION`；
    - 字符串大小写不敏感匹配 :data:`MODEL_PICTURE_ORIENTATIONS` → 返回
      AEDT 拼写规范形（``"isometric"``/``"TOP"``/``"  front "`` 皆可）；
    - 不在表内 → ``ValueError`` 列全候选 + 反馈指引；**缩写不支持**
      （``"iso"`` 必红）；已加入 Orientation List 的自定义视图名用
      ``allow_custom=True`` 显式放行（原样返回，AEDT 侧判定）；
    - 非 str 非 None → ``ValueError``。
    """
    if orientation is None:
        return DEFAULT_MODEL_PICTURE_ORIENTATION
    if not isinstance(orientation, str):
        raise ValueError(
            f"orientation 须为 str | None，得到 {type(orientation).__name__}: "
            f"{orientation!r}——合法值见 MODEL_PICTURE_ORIENTATIONS")
    candidate = orientation.strip()
    lowered = candidate.lower()
    for canonical in MODEL_PICTURE_ORIENTATIONS:
        if canonical.lower() == lowered:
            return canonical
    if allow_custom:
        return candidate
    raise ValueError(
        f"orientation '{orientation}' 不在合法集 "
        f"{list(MODEL_PICTURE_ORIENTATIONS)}——AEDT 侧症状是 "
        f"'orientation name {candidate} doesn't exist' 且无候选提示"
        "（晶圆键合用户实测 P2，2026-11-06：传 'iso' 即此）。缩写不支持，"
        "请用完整名（大小写不敏感，本函数归一为 AEDT 报告器拼写）；"
        "自定方向（已加入 Orientation List 的自定义视图名）用 "
        "allow_custom=True 显式放行。")


def _probe_non_graphical(app: Any) -> bool | None:
    """non_graphical duck-type 三探测（件④守卫的判据面）。

    探测序：pyaedt 1.9.0 真实消费路径 ``app.desktop_class.non_graphical``
    → 旧代 App 级 ``app.non_graphical`` → rfauto HfssSession ``_settings``
    映射（未连接/已配置态也可判，pre-connect fail-fast 用）。全部探不到
    → None（不可判定，调用方放行——best-effort，#105：只在**正向确知**
    无头时提前拦截，探测失败不得阻塞图形会话的正常导出）。
    """
    desktop_class = getattr(app, "desktop_class", None)
    if desktop_class is not None:
        value = getattr(desktop_class, "non_graphical", None)
        if value is not None:
            return bool(value)
    value = getattr(app, "non_graphical", None)
    if value is not None:
        return bool(value)
    settings_map = getattr(app, "_settings", None)
    if isinstance(settings_map, Mapping):
        value = settings_map.get("non_graphical")
        if value is not None:
            return bool(value)
    return None


def ensure_graphical_session(app: Any) -> None:
    """export_model_picture 非图形模式前置守卫（件④，反馈 P2）。

    病灶（晶圆键合用户实测）：非图形模式下直调 pyaedt
    ``export_model_picture`` 报 ``'NoneType' object has no attribute
    'recreate_application'``——看不出需要图形会话。

    ``non_graphical`` 正向确知为 True → ``RuntimeError``（消息含规定短语
    ``requires graphical session`` + 反馈实测病灶 + 修法指引）；False →
    放行；不可判定（None，探测链全空）→ 放行（best-effort，#105——不因
    探测失败阻塞图形会话）。app 可为 pyaedt Hfss/Desktop 实例或 rfauto
    :class:`HfssSession`（duck-type 三探测，见 :func:`_probe_non_graphical`）。
    """
    non_graphical = _probe_non_graphical(app)
    if non_graphical is True:
        raise RuntimeError(
            "export_model_picture requires graphical session——当前会话为 "
            "non_graphical（无头）模式。反馈实测（P2，2026-11-06）：无头模式"
            "直调 pyaedt export_model_picture 报 'NoneType' object has no "
            "attribute 'recreate_application'，误导排查；本守卫把该面提前为"
            "明确错误。修法=以 non_graphical=False 连接（HfssSession.connect "
            "settings 键 / Desktop(non_graphical=False)）后再导出图片。")


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


# ── VB-8 交互式 AEDT 会话弹窗预检（aurora_r R-17 席，opt-in 预检开关）──────

#: 图形/共享会话求解前弹窗预检开关（缺省关=零行为变化，不触碰窗口枚举
#: 面）。开启后 blocked/indeterminate 均拦发（见
#: :func:`hfss_dialog_guard_preflight`）。
ENV_DIALOG_GUARD = "RFAUTO_HFSS_DIALOG_GUARD"

_DIALOG_GUARD_TRUTHY = frozenset({"1", "true", "yes", "on"})


def hfss_dialog_guard_preflight(session: Any) -> dict[str, Any]:
    """图形/共享会话求解前弹窗预检（VB-8：三态只读巡检，opt-in）。

    病灶（AGENTS 踩坑速查）：GUI 已开同一工程时求解报错看不出占用；
    模态弹窗卡住的交互式 AEDT 会吃掉 gRPC 请求且报错面看不出根因。
    本预检把"会话是否被模态对话框占用"提前为显式三态证据（clear/
    blocked/indeterminate，**indeterminate 不等于空闲**——探测不到
    不冒充干净），由求解路径在发送前消费。

    开关契约（opt-in，fail-closed 只在开启后生效）：

    - ``RFAUTO_HFSS_DIALOG_GUARD`` 未设/非真值令牌 → **缺省关**：直接
      返回放行信封，**零行为变化**（不 import 探针、不枚举窗口、
      不读会话属性——调用形状钉住 tests/unit/test_window_probe.py）。
    - 真值令牌 = ``{"1","true","yes","on"}``（license_gate 同款家法）。

    预检适用域（applicable=False 直接放行并注明，不落 indeterminate）：

    - 无头会话（non_graphical 正向确知 True）——没有窗口面可巡检；
    - 远程会话（remote_info 在场）——服务器侧窗口不在本机窗口站，
      本机探针结构性不可达，不装样子（远程预检留 followUp）。

    判定链（applicable）：PID 解析（``desktop_pid`` 属性 →
    :func:`resolve_desktop_pid` 兜底）→ infra.window_probe 只读探针
    （EnumWindows/GetWindowThreadProcessId/GetClassNameW——**不发消息、
    不改窗、不点按钮、不关窗**，归属以 PID/owner 判不以标题判）→
    三态映射：

    - ``blocked`` → ``send_allowed=False`` + ``outcome="not_started"``
      + ``request_sent=False``（not_started 型信封，对齐
      infra.request_receipt.OUTCOME_NOT_STARTED——调用方**一个字节都
      不得发给 AEDT**）；
    - ``indeterminate`` → 同样拦发（fail-closed；探测不可证≠空闲，
      未知来源弹窗一律留人工，DIGEST §6 第 1 条）；
    - ``clear`` → 放行（``send_allowed=True``）。

    本函数自身**永不发送任何请求**（零 AEDT 调用；PID 解析只读
    Python 侧属性/命令行枚举）；``request_sent`` 记录的是预检时刻
    该请求的发送事实（未发送=False，其余=None 不适用）。

    Args:
        session: :class:`HfssSession` 实例或 duck-type 兼容对象
            （``desktop_pid``/``desktop``/``non_graphical``/
            ``remote_info`` 任一面可缺，缺面按不可知处理）。

    Returns:
        dict[str, Any]：具名信封（普通 dict 惯例，同
        ``detect_project_occupancy``）——键：``enabled``/``applicable``/
        ``verdict``（clear/blocked/indeterminate/not_applicable/None）/
        ``send_allowed``/``request_sent``/``outcome``/``pid``/``reason``
        /``probe``（探针证据链 dict 或 None）。
    """
    from rfauto.infra.request_receipt import OUTCOME_NOT_STARTED

    raw = os.environ.get(ENV_DIALOG_GUARD)
    enabled = raw is not None and raw.strip().lower() in _DIALOG_GUARD_TRUTHY
    if not enabled:
        return {
            "enabled": False, "applicable": None, "verdict": None,
            "send_allowed": True, "request_sent": None, "outcome": None,
            "pid": None,
            "reason": "预检开关缺省关——零行为变化（不触碰窗口枚举面）",
            "probe": None,
        }
    non_graphical = _probe_non_graphical(session)
    if non_graphical is True:
        return {
            "enabled": True, "applicable": False, "verdict": "not_applicable",
            "send_allowed": True, "request_sent": None, "outcome": None,
            "pid": None,
            "reason": "无头会话（non_graphical）无窗口面，预检不适用",
            "probe": None,
        }
    remote = getattr(session, "remote_info", None)
    if remote:
        return {
            "enabled": True, "applicable": False, "verdict": "not_applicable",
            "send_allowed": True, "request_sent": None, "outcome": None,
            "pid": None,
            "reason": "远程会话——服务器侧窗口不在本机窗口站，本机探针"
                      "结构性不可达（远程预检留 followUp）",
            "probe": None,
        }
    pid: int | None = None
    getter = getattr(session, "desktop_pid", None)
    if callable(getter):
        try:
            pid = getter()
        except Exception:
            pid = None
    elif isinstance(getter, int) and not isinstance(getter, bool):
        pid = getter
    if pid is None:
        desktop = getattr(session, "desktop", None)
        try:
            pid = resolve_desktop_pid(
                desktop if desktop is not None else session)
        except Exception:
            pid = None
    try:
        from rfauto.infra import window_probe

        result = window_probe.probe_pid_windows(pid)
    except Exception as exc:  # 探针面自身故障按不可证折 fail-closed
        return {
            "enabled": True, "applicable": True,
            "verdict": "indeterminate", "send_allowed": False,
            "request_sent": False,
            "outcome": OUTCOME_NOT_STARTED,
            "pid": pid if isinstance(pid, int) else None,
            "reason": f"探针不可用折不可证（indeterminate 不等于空闲）"
                      f"：{exc!r}",
            "probe": None,
        }
    send_allowed = result.verdict == "clear"
    envelope: dict[str, Any] = {
        "enabled": True, "applicable": True, "verdict": result.verdict,
        "send_allowed": send_allowed,
        "request_sent": False if not send_allowed else None,
        "outcome": None if send_allowed else OUTCOME_NOT_STARTED,
        "pid": result.pid,
        "reason": result.reason,
        "probe": result.as_dict(),
    }
    return envelope


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
    实证配方，DEVLOG 五百三十四；原实现见 remote_service
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
        # 必须与本机 pyaedt 配对版本一致（AGENTS 规则 0）。
        remote_name = settings.get("remote_machine")
        remote_kwargs: dict[str, Any] = {}
        if remote_name:
            from rfauto.infra.remote_machines import (
                hfss_mtls_certs,
                resolve_machine,
            )

            cfg = resolve_machine(str(remote_name))
            # 版本配对交叉断言（AGENTS 规则 0，审查分片 1 P1-1 附带项）：
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
        远程会话=服务器侧 PID（只记档，服务器侧清场消费，AGENTS 规则
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
