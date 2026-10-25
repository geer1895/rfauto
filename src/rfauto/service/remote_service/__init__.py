"""remote_service —— 多机协同仿真资源服务面（多机协同 WP v0）。

薄服务层（规则 4：JSON 进出，CLI/MCP 是薄壳）。能力：

- ``remote_probe``：机器探活（TCP 连通性+时延，零副作用零凭据）。
- ``remote_status``：探活 + SSH 可达性判定（凭据缺失如实
  ``ssh_auth: missing_credentials``，不猜不试密码）。
- ``license_preflight``：发射前 license 预检（v1 调度面一级门）——license
  端口 TCP 探活（注册表 ``probe_ports`` 语义名含 ``license`` 键）+
  可选 attach health 深检（信息面不进门）；席位级 lmstat 查询登记
  UNVERIFIED（端口 OPEN≠席位可用，G6 教训）。
- ``hfss_remote_session_config``：组装 HFSS 远程会话 settings 增量
  （``remote_machine`` 键），供调用方（v1 调度面）合并进 connect
  settings——HfssSession 消费的是 ``settings["remote_machine"]`` 键，
  本函数不直接写任何状态——无登记返回 ``{"ok": True, "remote": None}``
  （无配置零行为变化契约）。
- ``remote_hfss_smoke``：L1 attach 冒烟编排（真机 opt-in，env
  ``RFAUTO_REMOTE_SMOKE=1`` 门；#139/df4⑥ 真跑集成测试规矩——unit 门
  内只跑 mock 路径，绝不真连网）。
- ``remote_hfss_l2_smoke``：L2 求解冒烟编排（远程建模→求解→Touchstone
  回拉→判读；opt-in 门与共享前置段同 L1）。
- ``remote_mutex_command``/``remote_mutex_precheck``：#261 每机互斥预检
  **共享单源**（X4 批自 remote_oe_service._remote_mutex 提升泛化）——
  进程指纹直查=权威判据 + 服务器探针 census mutex 行=旁证；三通道
  （HFSS gRPC/ADS hpeesofsim/openEMS runner）同构复用，指纹按通道语义词
  分（OE=python runner 家族 / ADS=hpeesofsim / HFSS=本机注册端口 grpcsrv）。

通道拓扑：HFSS gRPC 本机客户端→服务器 ``ansysedt -grpcsrv``；文件走
SSH sftp（服务器云盘 SMB 为生产资料库，禁测试写入——服务器说明 §11.7）。

T2 巨石拆分（aurora_h W3-S3，2026-10-19）：实现按通道意图迁入子模块——
``mutex``（#261 共享互斥单源）/``hfss_smoke``（HFSS L1/L2 冒烟编排与
清理）/``precheck``（探活/状态/license 预检/会话配置读面）；本包
``__init__`` 是 facade，逐名显式 re-export 全部原模块级名（公开面快照
钉：拆分前后 dir() 逐名相等；redundant-alias=PEP 484 显式 re-export
惯例，函数体逐字节零改动）。
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .hfss_smoke import (
    _C_M_S as _C_M_S,
)
from .hfss_smoke import (
    ENV_REMOTE_SSH_PASSWORD as ENV_REMOTE_SSH_PASSWORD,
)
from .hfss_smoke import (
    ENV_REMOTE_SSH_USER as ENV_REMOTE_SSH_USER,
)
from .hfss_smoke import (
    L2_AIR_TOP_MM as L2_AIR_TOP_MM,
)
from .hfss_smoke import (
    L2_BOARD_W_MM as L2_BOARD_W_MM,
)
from .hfss_smoke import (
    L2_EFF_EXPECT as L2_EFF_EXPECT,
)
from .hfss_smoke import (
    L2_EFF_WINDOW as L2_EFF_WINDOW,
)
from .hfss_smoke import (
    L2_ER as L2_ER,
)
from .hfss_smoke import (
    L2_F0_GHZ as L2_F0_GHZ,
)
from .hfss_smoke import (
    L2_F_START_GHZ as L2_F_START_GHZ,
)
from .hfss_smoke import (
    L2_F_STOP_GHZ as L2_F_STOP_GHZ,
)
from .hfss_smoke import (
    L2_H_MM as L2_H_MM,
)
from .hfss_smoke import (
    L2_LEN_MM as L2_LEN_MM,
)
from .hfss_smoke import (
    L2_N_POINTS as L2_N_POINTS,
)
from .hfss_smoke import (
    L2_S11_GATE_DB as L2_S11_GATE_DB,
)
from .hfss_smoke import (
    L2_S21_GATE_DB as L2_S21_GATE_DB,
)
from .hfss_smoke import (
    L2_SPAN_M as L2_SPAN_M,
)
from .hfss_smoke import (
    L2_TAND as L2_TAND,
)
from .hfss_smoke import (
    L2_W_MM as L2_W_MM,
)
from .hfss_smoke import (
    REMOTE_SMOKE_ENV as REMOTE_SMOKE_ENV,
)
from .hfss_smoke import (
    RemoteMachineConfig as RemoteMachineConfig,
)
from .hfss_smoke import (
    _attach_and_verify as _attach_and_verify,
)
from .hfss_smoke import (
    _judge_l2 as _judge_l2,
)
from .hfss_smoke import (
    _l2_model_solve_export as _l2_model_solve_export,
)
from .hfss_smoke import (
    _launch_grpcsrv as _launch_grpcsrv,
)
from .hfss_smoke import (
    _round_or_nan as _round_or_nan,
)
from .hfss_smoke import (
    contextlib as contextlib,
)
from .hfss_smoke import (
    load_remote_machines as load_remote_machines,
)
from .hfss_smoke import (
    ok_envelope as ok_envelope,
)
from .hfss_smoke import (
    os as os,
)
from .hfss_smoke import (
    probe_machine as probe_machine,
)
from .hfss_smoke import (
    record_pull_manifest as record_pull_manifest,
)
from .hfss_smoke import (
    remote_hfss_cleanup as remote_hfss_cleanup,
)
from .hfss_smoke import (
    remote_hfss_l2_smoke as remote_hfss_l2_smoke,
)
from .hfss_smoke import (
    remote_hfss_smoke as remote_hfss_smoke,
)
from .hfss_smoke import (
    remote_session_switches as remote_session_switches,
)
from .hfss_smoke import (
    resolve_machine as resolve_machine,
)
from .hfss_smoke import (
    skipped_envelope as skipped_envelope,
)
from .hfss_smoke import (
    uuid as uuid,
)
from .mutex import (
    _MUTEX_HIT_LINE_RE as _MUTEX_HIT_LINE_RE,
)
from .mutex import (
    Any as Any,
)
from .mutex import (
    SshTransport as SshTransport,
)
from .mutex import (
    re as re,
)
from .mutex import (
    remote_mutex_command as remote_mutex_command,
)
from .mutex import (
    remote_mutex_precheck as remote_mutex_precheck,
)
from .precheck import (
    LICENSE_PREFLIGHT_SEAT_QUERY as LICENSE_PREFLIGHT_SEAT_QUERY,
)
from .precheck import (
    RemoteConfigError as RemoteConfigError,
)
from .precheck import (
    _ssh_status as _ssh_status,
)
from .precheck import (
    hfss_remote_session_config as hfss_remote_session_config,
)
from .precheck import (
    license_preflight as license_preflight,
)
from .precheck import (
    probe_port as probe_port,
)
from .precheck import (
    remote_probe as remote_probe,
)
from .precheck import (
    remote_status as remote_status,
)

__all__ = [
    "LICENSE_PREFLIGHT_SEAT_QUERY",
    "REMOTE_SMOKE_ENV",
    "hfss_remote_session_config",
    "license_preflight",
    "remote_hfss_cleanup",
    "remote_hfss_l2_smoke",
    "remote_hfss_smoke",
    "remote_mutex_command",
    "remote_mutex_precheck",
    "remote_probe",
    "remote_status",
]

# ══ T2 巨石拆分 facade（aurora_h W3-S3，2026-10-19）══════════════════
# 本文件原为单文件巨石（1321 行），实现按通道意图迁入上方 re-export 的
# 子模块；此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后
# dir() 逐名相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = ("mutex", "hfss_smoke", "precheck")


class _FacadeModule(_ModuleType):
    """facade setattr 双写：补丁扇出到持有该名的全部子模块（AU-1）。"""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _sub in _FANOUT.get(name, ()):
            setattr(_importlib.import_module(__name__ + "." + _sub),
                    name, value)


_FANOUT: dict[str, list[str]] = {}


def _build_fanout() -> None:
    for _sub in _SUBMODULES:
        _mod = _importlib.import_module(__name__ + "." + _sub)
        for _name in list(vars(_mod)):
            _FANOUT.setdefault(_name, []).append(_sub)


_build_fanout()
del _build_fanout
_sys.modules[__name__].__class__ = _FacadeModule
