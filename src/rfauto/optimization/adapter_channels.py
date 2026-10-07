"""optimizer 求解通道注册表（AU-6）——fake/hfss/openems 具体类 lazy import
收拢单点（基类+注册表模式，参照 adapters.em_solver_base.EMSolverRegistry）。

改前形态（本模块收拢的对象）：optimization/optimizer.py ``_create_adapter``
内联 if/elif 三分支，各分支体内散置 ``from rfauto.adapters.* import …``
lazy import——新通道只能继续往该函数加分支（注册缝，F3 曾裁定缓办，
AU-6 立项收拢）。

设计要点（runs/au3_audit/au6_design.md 全文）：
- **注册时机**：本模块 import 时以「工厂函数引用」注册内置三通道——
  注册动作零副作用（不触发任何 adapter 模块 import），重复注册幂等
  覆盖（后注册者胜，同 EMSolverRegistry.register 语义）；
- **惰性导入面**：具体适配器类的 import 全部在工厂函数体内，通道被
  选中（create 被调）时才发生——与改前逐分支 lazy import 时机逐位
  一致；``import rfauto.optimization.optimizer`` 后 sys.modules 不出现
  ``rfauto.adapters.*``（tests/unit/test_adapter_channels.py 钉死）；
- **零行为变化**：三工厂函数体自 optimizer 分支**逐字迁移**（含 openems
  通道的宽兜 warning + ``(None, "")``、hfss 通道安装探测失败 ``(None,
  "")``、fake 通道插件元数据推导 KeyError 兜底）；未知通道返回
  ``(None, "")`` 与改前 fallthrough 逐位一致（测试钉）；
- **消费面**：optimizer._create_adapter 只做公共预处理（setup/freq 提取，
  保留原"分支前先取 setup_cfg"的报错语义）+ 注册表分发；sweep_backend
  经 optimizer 同名函数委托（改前即如此），p0_gate_service/scripts 的
  ``from rfauto.optimization.optimizer import _create_adapter`` 入口不变。

分层：optimization 层（可 import adapters/infra/core）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "ChannelFactory",
    "channel_names",
    "create_via_channel",
    "register_channel",
]

logger = logging.getLogger(__name__)

#: 通道工厂签名：入参=optimizer._create_adapter 的公共预处理结果；
#: 返回 (adapter | None, aedt_version_str)。
ChannelFactory = Callable[..., tuple[Any | None, str]]

#: 通道注册表（名 → 工厂）。值是函数引用不是类：三通道构造签名不同
#: （fake/openems 吃 freq_range/points+kwargs，hfss 走安装探测），
#: 由工厂函数吸收差异（与 EMSolverRegistry「值=类」的均匀签名不同源，
#: 逐字迁移优先于强行同签名）。
_CHANNEL_FACTORIES: dict[str, ChannelFactory] = {}


def register_channel(name: str, factory: ChannelFactory) -> None:
    """注册（或覆盖）一个求解通道工厂（幂等，后注册者胜）。"""
    _CHANNEL_FACTORIES[str(name)] = factory


def channel_names() -> tuple[str, ...]:
    """已注册通道名（排序稳定，供注册面测试/诊断消费）。"""
    return tuple(sorted(_CHANNEL_FACTORIES))


def create_via_channel(
    name: str,
    *,
    setup_cfg: dict[str, Any],
    freq_range: list[float],
    freq_points: int,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """按通道名分发到已注册工厂；未注册名返回 (None, "")。

    ``(None, "")`` 语义与改前 _create_adapter 的 fallthrough 逐位一致：
    上层（run_optimization/sweep_backend）报"适配器创建失败"并终止该 run。
    """
    factory = _CHANNEL_FACTORIES.get(str(name))
    if factory is None:
        return None, ""
    return factory(
        setup_cfg=setup_cfg,
        freq_range=freq_range,
        freq_points=freq_points,
        adapter_kwargs=adapter_kwargs,
        recipe_data=recipe_data,
    )


# ─── 内置通道工厂（自 optimizer._create_adapter 分支逐字迁移） ────────────────


def _create_fake_channel(
    *,
    setup_cfg: dict[str, Any],
    freq_range: list[float],
    freq_points: int,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """fake 通道：FakeAdapter（解析近似；n_ports/model_type 缺省时从插件
    元数据推导，C4）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    kwargs = dict(adapter_kwargs or {})
    freq_ghz = (freq_range[0], freq_range[1], freq_points)
    n_ports = kwargs.pop("n_ports", None)
    model_type = kwargs.pop("model_type", None)
    # 未显式指定时从插件元数据推导（C4：branchline 4 端口 / patch 2 端口）
    if n_ports is None or model_type is None:
        try:
            from rfauto.models.registry import get as _get_plugin
            plugin_cls = _get_plugin(recipe_data.get("model", ""))
            n_ports = n_ports if n_ports is not None else plugin_cls.n_ports
            model_type = (model_type if model_type is not None
                          else plugin_cls.fake_model_type)
        except KeyError:
            pass
    adapter = FakeAdapter(
        freq_ghz=freq_ghz,
        n_ports=n_ports if n_ports is not None else 3,
        model_type=model_type or "wilkinson",
        **kwargs,
    )
    adapter.connect({})
    return adapter, "fake"


def _create_hfss_channel(
    *,
    setup_cfg: dict[str, Any],
    freq_range: list[float],
    freq_points: int,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """hfss 通道：安装探测（RFAUTO_AEDT_PATH → resolve_aedt_install）+
    HfssAdapter gRPC 连接；探测失败返回 (None, "")。"""
    import os

    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.version_probe import resolve_aedt_install

    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if aedt_path and not Path(aedt_path).exists():
        return None, ""
    # 项目 B：版本探测收敛（显式路径优先，否则自动探测本机安装）
    install = resolve_aedt_install(aedt_path or None)
    if install is None:
        return None, ""
    aedt_version = install["aedt_version"]
    adapter = HfssAdapter()
    adapter.connect({"desktop_version": aedt_version, "non_graphical": True})
    return adapter, aedt_version


def _create_openems_channel(
    *,
    setup_cfg: dict[str, Any],
    freq_range: list[float],
    freq_points: int,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """openEMS 真评估优化通道（产物化自 e11 战役层补丁，（二百六十
    一）：OpenEMSOptAdapter 逐评估整脚本重渲染 + OpenEMSSolver 子进程求
    解，与 fake/hfss 分支同构消费优化回路。"""
    from rfauto.adapters.openems_optimizer_adapter import (
        OpenEMSOptAdapter,
        template_for_model,
    )

    kwargs = dict(adapter_kwargs or {})
    try:
        # 模板解析：显式 adapter_kwargs.template > 插件 openems_template
        # ClassVar > 子串映射（与 service._template_hint 同口径）
        template = str(kwargs.pop("template", "") or "")
        if not template:
            try:
                from rfauto.models.registry import get as _get_plugin
                plugin_cls = _get_plugin(str(recipe_data.get("model", "")))
                template = str(getattr(plugin_cls, "openems_template", "") or "")
            except KeyError:
                template = ""
        if not template:
            template = template_for_model(str(recipe_data.get("model", "")))
        adapter = OpenEMSOptAdapter(
            (float(freq_range[0]), float(freq_range[1])),
            template=template, **kwargs)
        if not adapter.connect({}):
            return None, ""
        return adapter, "openems"
    except Exception as e:
        # openems 通道选择宽兜：lazy import 失败/模板解析/渲染初始化/
        # connect 抛出的任意异常（原 optimizer 分支同款语义，AU-6 迁移保留）。
        # warning 后返回 (None, "")——上层报"适配器创建失败"并终止该 run；
        # 具体原因在本条 warning 日志（含 exc_info traceback）可见。
        logger.warning("openems 适配器创建失败: %s", e, exc_info=True)
        return None, ""


# 内置三通道注册（import 时执行，仅函数引用——不触发 adapter 模块 import）
register_channel("fake", _create_fake_channel)
register_channel("hfss", _create_hfss_channel)
register_channel("openems", _create_openems_channel)
