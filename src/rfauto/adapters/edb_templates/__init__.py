"""EDB 平面族模板发射器（声明式 spec dict + PyEDB configuration JSON）。

数据集生成 "EDB 快车道" 的 spec 发射层：平面族（branchline 耦合器 /
wilkinson 功分器 / coupled-line 耦合器 / ratrace 环形电桥；lange 耦合器
综合单源提供、EDB 发射声明不支持——跨线原语缺失，见 lange.py docstring）
→ 声明式 spec dict（stackup/traces/vias/ports/sim_setup 契约字段，schema
见 schema.py docstring）+ PyEDB ``edb.configuration.load()`` 兼容 config
dict。消费契约::

    from rfauto.adapters.edb_adapter import EdbAdapter   # edb_adapter 席
    adapter = EdbAdapter(workdir=Path(...))
    result = adapter.build(spec)                          # spec: dict

数值纪律：全部尺寸由综合单源闭式产出（inverse_width HJ 反解 + KJ 耦合线
二维反解 + forward_media εeff + λg 闭式），与已注册 openEMS/HFSS 模板同
综合单源；发射器纯函数零 IO 零 pyedb 依赖，pyedb 属 edb_adapter 消费层。

扩展族 schema 豁免注记（2026-10-08 扩展批；schema.py 正本逻辑未动）：
KNOWN_TEMPLATES 白名单仍是 ("edb_branchline", "edb_power_divider")——新族
template 键（edb_coupled_line/edb_ratrace）的 validate_spec "template 非法"
行由各族发射器侧过滤（升格 followUp）；coupled-line 族另有连通图两分量
豁免（线 A/B DC 隔离=器件物理）。两处豁免由
tests/unit/test_edb_templates_ext.py 钉住。edb_lane_service 分派表接线同
属升格 followUp（本批未动服务层）。
"""

from __future__ import annotations

from rfauto.adapters.edb_templates.branchline import emit_branchline_spec
from rfauto.adapters.edb_templates.coupled_line import emit_coupled_line_spec
from rfauto.adapters.edb_templates.lange import (
    LANGE_EDB_SUPPORTED,
    TEMPLATE_KEY_RESERVED,
    emit_lange_spec,
    lange_synth,
)
from rfauto.adapters.edb_templates.power_divider import emit_power_divider_spec
from rfauto.adapters.edb_templates.ratrace import emit_ratrace_spec
from rfauto.adapters.edb_templates.schema import (
    KNOWN_TEMPLATES,
    SPEC_SCHEMA_VERSION,
    assemble_config,
    quarter_wave_len_mm,
    solve_microstrip,
    trace_attach_graph,
    trace_connected_components,
    validate_spec,
)

__all__ = [
    "KNOWN_TEMPLATES",
    "LANGE_EDB_SUPPORTED",
    "SPEC_SCHEMA_VERSION",
    "TEMPLATE_KEY_RESERVED",
    "assemble_config",
    "emit_branchline_spec",
    "emit_coupled_line_spec",
    "emit_lange_spec",
    "emit_power_divider_spec",
    "emit_ratrace_spec",
    "lange_synth",
    "quarter_wave_len_mm",
    "solve_microstrip",
    "trace_attach_graph",
    "trace_connected_components",
    "validate_spec",
]
