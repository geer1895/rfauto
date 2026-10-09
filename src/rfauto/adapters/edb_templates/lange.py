"""Lange 耦合器——综合单源提供 + EDB 发射**声明不支持**（诚实>凑数）。

任务裁定（2026-10-08）：pyedb 0.83 configuration 无 crossover/跨线原语，
Lange 四指互联是否以"跳线+桥接"近似发射——本模块选择**声明不支持**，
论证如下（docstring 即裁定记录）：

  1. **单层走线拓扑不可行（平面性定理级障碍）**。展开型 Lange（注册
     openEMS 模板 ``oe_templates/render_c4.py`` lange 同拓扑）：网络 A=
     指 1/3、网络 B=指 2/4，每网络在**每端**各需一次跨指互联（每端两条
     桥）。端部边界序 1,2,3,4 交错 → 连线 1-3 与 2-4 在端部外侧同一半
     平面内的平面投影必相交（Jordan 曲线论证：弦 1-3 分离 2 与 4）——
     这正是真实 Lange 必须用 air-bridge（MMIC）或键合线（Lange 1969 原
     始版）的拓扑根源，任何单层 EDB 走线版（含"绕端 U 形跳线"）都无法
     同时实现 1-3 与 2-4 而不短路。
  2. **pyedb 0.83 configuration 无 crossover 原语**（schema 假设 5 同源
     实测：boundaries 段仅 open-region；modeler 段 traces/planes 全平面
     单层）——同层跨越=金属合并短路；CfgTrace 无抬高架桥形态。
  3. **"跳线+桥接" PCB 式近似（第二信号层埋线 + 每端 2 过孔、共 4 过
     孔）拓扑可行**（spec["vias"] 契约与 edb_adapter._translate_vias 支
     持过孔），但（a）过孔电感 + 埋线对 GND 平面电容的寄生恰落在决定
     3dB 正交桥幅度平衡/相位正交性的耦合路径上，量级未经真机标定；
     （b）需引入第三金属层 + 第二介质层，偏离本族"两层信号夹单介质"
     平面族契约（schema 假设 2）。按建模纪律（修正之前先验证
     模型本身正确）与任务裁定"不确定就选声明不支持"，未经 HFSS/EDA 真
     机仲裁前不发射该近似几何。

综合链照常提供（``lange_synth``）：与注册 lange 模板设计函数
``oe_templates.render_c4.lange_design`` 同函数同参（Pozar §7.6 Lange 节
设计式 C→相邻对 (Z0e,Z0o)、四线等效 (Ze4,Zo4)、KJ 二维反解 (w,s)、指长
λ/4@平均 εeff、50Ω 馈宽单源），供离线设计与未来升格复用。升格前置条件：
pyedb crossover 原语，或经真机仲裁的过孔跳线口径 + schema 契约层扩展
（KNOWN_TEMPLATES/层叠/vias 消费面）；template 键预留 ``"edb_lange"``。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.adapters.edb_templates.schema import resolve_stackup
from rfauto.adapters.oe_templates.render_c4 import lange_design

__all__ = ["LANGE_EDB_SUPPORTED", "TEMPLATE_KEY_RESERVED", "emit_lange_spec", "lange_synth"]

#: EDB 发射能力旗：False=emit_lange_spec 恒 NotImplementedError（见 docstring）
LANGE_EDB_SUPPORTED = False

#: 升格时预留的 template 键（当前不产 spec，不进 validate_spec 白名单）
TEMPLATE_KEY_RESERVED = "edb_lange"


def lange_synth(params: dict[str, Any]) -> dict[str, Any]:
    """Lange 综合链（注册 lange 模板同款单源，纯函数零 IO）。

    Args:
        params: ``f0_ghz``（必填，>0）、``z0_ohm``（缺省 50，仅支持 50）、
            ``coupling_db``（缺省 3.0103=3dB）、``stackup``（缺省
            rogers4350b_h0.508 标量，取 epsilon_r/thickness_mm 两标量）。

    Returns:
        注册模板 ``lange_design`` 同款读数 dict：coupling_db/z0_ohm/f0_ghz/
        zee_pair_ohm/zoo_pair_ohm/ze4_ohm/zo4_ohm/c/w_mm/s_mm/ere_e/ere_o/
        finger_len_mm/w_feed_mm/notes（notes 为注册模板原产中文注记）。

    Raises:
        ValueError: f0 非法、z0_ohm != 50、coupling 超出设计式可达域或 KJ
            反解不可达。
    """
    f0_ghz = float(params["f0_ghz"])
    if not (f0_ghz > 0.0) or not math.isfinite(f0_ghz):
        raise ValueError(f"f0_ghz 必须为正有限数: {params.get('f0_ghz')!r}")
    z0_ohm = float(params.get("z0_ohm", 50.0))
    if z0_ohm != 50.0:
        raise ValueError(
            f"仅支持 50Ω 系统口径（pyedb wave_port 配置面阻抗固定 50，假设 3）:"
            f" z0_ohm={z0_ohm}"
        )
    coupling_db = float(params.get("coupling_db", 3.0103))
    stackup = resolve_stackup(params.get("stackup"))
    return lange_design(
        f0_ghz=f0_ghz, z0_ohm=z0_ohm, coupling_db=coupling_db,
        er=stackup.epsilon_r, h_mm=stackup.thickness_mm,
    )


def emit_lange_spec(
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lange 耦合器 EDB 发射——**声明不支持**（恒 NotImplementedError）。

    输入校验按族契约先行（坏入参 ValueError 优先于能力门，与 branchline
    族同款口径）；校验通过后抛 NotImplementedError——理由与升格路径见模
    块 docstring（单层平面性障碍 + pyedb 0.83 无 crossover 原语 + 过孔跳
    线近似未经真机仲裁）。综合数值需求走 :func:`lange_synth`。

    Args:
        params: 同 :func:`lange_synth`（f0_ghz 必填）。

    Raises:
        ValueError: f0 缺失/非法或 z0_ohm != 50（输入校验，先于能力门）。
        NotImplementedError: 恒抛——EDB 平面族契约下 Lange 跨线不可表达
            （LANGE_EDB_SUPPORTED = False）。
    """
    f0_ghz = float(params["f0_ghz"])
    if not (f0_ghz > 0.0) or not math.isfinite(f0_ghz):
        raise ValueError(f"f0_ghz 必须为正有限数: {params.get('f0_ghz')!r}")
    z0_ohm = float(params.get("z0_ohm", 50.0))
    if z0_ohm != 50.0:
        raise ValueError(
            f"仅支持 50Ω 系统口径（pyedb wave_port 配置面阻抗固定 50，假设 3）:"
            f" z0_ohm={z0_ohm}"
        )
    raise NotImplementedError(
        "edb_templates.lange：Lange 耦合器 EDB 发射声明不支持"
        "（LANGE_EDB_SUPPORTED=False）。跨线（crossover/air-bridge）在"
        " pyedb 0.83 configuration 无对应原语：同层跨越=金属短路，单层"
        " U 形跳线因网络 A(指1/3)/B(指2/4) 端部交错连线平面性障碍不可行；"
        " 第二层埋线+过孔跳线近似未经真机仲裁（过孔 L/埋线 C 寄生恰落在"
        " 3dB 正交桥耦合路径上）。综合数值走 lange_synth()；升格前置条件"
        " 见模块 docstring。"
    )
