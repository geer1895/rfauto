"""openEMS simulation templates.

Templates: wilkinson, patch, branchline, dipole, stepped_impedance, coupled_line.
Each template renders CSXCAD scripts for openEMS Python bindings.
每模板元数据（仿真时长/网格/S 参数提取点）见 TEMPLATE_META / template_meta()——
方向 2 参数化公约（Plan §3：防 6 个模板 6 种风格）。

网格/边界方法学（2026-09-04 频率尺度根因实验后重写，对照官方 MSL_NotchFilter
教程基线，证据链 runs/audit_freq_scale/ E1-E4）：
- 网格 base = 基板内波长 λ_sub/50（官方口径），近走线区 base/4；
  旧版 λ/20@空气 ≈4.3mm 粗网格导致谷位系统性低 30-40% 且随网格漂移；
- 地面 = z-min PEC 边界（官方口径），基板延伸到侧边界（旧版有限小板
  + 70mm 空气隙引入板边衍射）；
- z 轴翻转：基板 z∈[0,H]，金属在 z=H 顶面（官方同款）；
- 端口 FeedShift=10×NEAR、MeasPlaneShift=端口段长/3（官方口径）；
- NrTS=100000 不设 EndCriteria（官方口径；默认能量判据自动停机）。
"""

# ══ AU-1 巨石拆分 facade（2026-09-30）════════════════════════════
# 本文件原为 14k 行巨石，实现拆分至 oe_templates/ 包（registry/closedform/
# smatrix/grid/render_core/render_tl/render_ratrace_cyl/render_hairpin/…）。
# 此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir()
# 逐名相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# 兼容源锚（test_layout_p2::_LEGACY_SOURCE_PIECES 对本文件源码文本锚定，
# 金文本行自原 render_script 基板段逐字节保留；piece「地面 = z-min PEC 边界」
# 已在上文 docstring 中）：
#         "# 基板延伸到侧边界（guided；官方口径：无板边衍射）；"
# - 地面 = z-min PEC 边界（官方口径），基板延伸到侧边界（旧版有限小板
#         'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
#         "                      kappa=TAND * 2 * np.pi * F0 * "
#         "8.854187817e-12 * ER)\n"
#         "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB), priority=0)\n"

from __future__ import annotations

import math as math  # facade：保持原模块公开面（快照钉）
from dataclasses import dataclass as dataclass
from itertools import pairwise as pairwise
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

if TYPE_CHECKING:
    import numpy as np  # noqa: F401

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .oe_templates.closedform import (
    _ARR_C_MM_GHZ as _ARR_C_MM_GHZ,
)
from .oe_templates.closedform import (
    _ARR_EDGE_MARGIN_MM as _ARR_EDGE_MARGIN_MM,
)
from .oe_templates.closedform import (
    _ant2_eps_eff as _ant2_eps_eff,
)
from .oe_templates.closedform import (
    _array_patch_eps_dl as _array_patch_eps_dl,
)
from .oe_templates.closedform import (
    _fmt_list as _fmt_list,
)
from .oe_templates.closedform import (
    _open_end_delta_mm as _open_end_delta_mm,
)
from .oe_templates.closedform import (
    array_elem_len_mm as array_elem_len_mm,
)
from .oe_templates.closedform import (
    array_elem_w_mm as array_elem_w_mm,
)
from .oe_templates.closedform import (
    array_line_w_mm as array_line_w_mm,
)
from .oe_templates.closedform import (
    coupled_bpf_width_gap_from_zee_zoo as coupled_bpf_width_gap_from_zee_zoo,
)
from .oe_templates.grid import (
    _C_LIGHT_MS as _C_LIGHT_MS,
)
from .oe_templates.grid import (
    END_CRITERIA_FD as END_CRITERIA_FD,
)
from .oe_templates.grid import (
    NRTS_DT_SAFETY as NRTS_DT_SAFETY,
)
from .oe_templates.grid import (
    NRTS_MAX_TIME_FALLBACK_NS as NRTS_MAX_TIME_FALLBACK_NS,
)
from .oe_templates.grid import (
    NRTS_MAX_TIME_TEMPLATES as NRTS_MAX_TIME_TEMPLATES,
)
from .oe_templates.grid import (
    _fd_nrts_defaults as _fd_nrts_defaults,
)
from .oe_templates.grid import (
    _fd_nrts_override_block as _fd_nrts_override_block,
)
from .oe_templates.grid import (
    _near_points as _near_points,
)
from .oe_templates.grid import (
    cfl_dt_s as cfl_dt_s,
)
from .oe_templates.grid import (
    nrts_from_max_time_ns as nrts_from_max_time_ns,
)
from .oe_templates.registry import (
    _DEFAULT_SUB as _DEFAULT_SUB,
)
from .oe_templates.registry import (
    _FOUR_PORT_ROTATION_TEMPLATES as _FOUR_PORT_ROTATION_TEMPLATES,
)
from .oe_templates.registry import (
    _NWAY_PORT_ROTATION_TEMPLATES as _NWAY_PORT_ROTATION_TEMPLATES,
)
from .oe_templates.registry import (
    _SUB_CELLS_8_TEMPLATES as _SUB_CELLS_8_TEMPLATES,
)
from .oe_templates.registry import (
    _SUB_CELLS_DEFAULT as _SUB_CELLS_DEFAULT,
)
from .oe_templates.registry import (
    _TEMPLATE_PORT_AXES as _TEMPLATE_PORT_AXES,
)
from .oe_templates.registry import (
    _TEMPLATE_RADIATOR as _TEMPLATE_RADIATOR,
)
from .oe_templates.registry import (
    _THREE_PORT_ROTATION_TEMPLATES as _THREE_PORT_ROTATION_TEMPLATES,
)
from .oe_templates.registry import (
    TEMPLATE_META as TEMPLATE_META,
)
from .oe_templates.registry import (
    TEMPLATE_NOMINAL as TEMPLATE_NOMINAL,
)
from .oe_templates.registry import (
    TemplateResult as TemplateResult,
)
from .oe_templates.registry import (
    template_meta as template_meta,
)
from .oe_templates.render_antenna2 import (
    _ANT2_C_MM_GHZ as _ANT2_C_MM_GHZ,
)
from .oe_templates.render_antenna2 import (
    _ANTENNA2_FREE_SPACE_TEMPLATES as _ANTENNA2_FREE_SPACE_TEMPLATES,
)
from .oe_templates.render_antenna2 import (
    _ANTENNA2_TALL_TEMPLATES as _ANTENNA2_TALL_TEMPLATES,
)
from .oe_templates.render_antenna2 import (
    ANTENNA2_META as ANTENNA2_META,
)
from .oe_templates.render_antenna2 import (
    ANTENNA2_NOMINAL as ANTENNA2_NOMINAL,
)
from .oe_templates.render_antenna2 import (
    ANTENNA2_TEMPLATES as ANTENNA2_TEMPLATES,
)
from .oe_templates.render_antenna2 import (
    K_HELIX as K_HELIX,
)
from .oe_templates.render_antenna2 import (
    _ant2_body as _ant2_body,
)
from .oe_templates.render_antenna2 import (
    _ant2_layout as _ant2_layout,
)
from .oe_templates.render_antenna2 import (
    _helix_lines as _helix_lines,
)
from .oe_templates.render_antenna2 import (
    _ifa_lines as _ifa_lines,
)
from .oe_templates.render_antenna2 import (
    _loop_lines as _loop_lines,
)
from .oe_templates.render_antenna2 import (
    _monopole_lines as _monopole_lines,
)
from .oe_templates.render_antenna2 import (
    _pifa_lines as _pifa_lines,
)
from .oe_templates.render_antenna2 import (
    _slot_lines as _slot_lines,
)
from .oe_templates.render_antenna2 import (
    antenna2_meta as antenna2_meta,
)
from .oe_templates.render_antenna2 import (
    helix_pitch_mm as helix_pitch_mm,
)
from .oe_templates.render_antenna2 import (
    ifa_arm_len_mm as ifa_arm_len_mm,
)
from .oe_templates.render_antenna2 import (
    loop_side_mm as loop_side_mm,
)
from .oe_templates.render_antenna2 import (
    monopole_len_mm as monopole_len_mm,
)
from .oe_templates.render_antenna2 import (
    pifa_l_mm as pifa_l_mm,
)
from .oe_templates.render_antenna2 import (
    slot_len_mm as slot_len_mm,
)
from .oe_templates.render_array_eep import (
    _ARR_BOARD_MM as _ARR_BOARD_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_CORRIDOR_CLEAR_MM as _ARR_CORRIDOR_CLEAR_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_ELEM_SEMANTICS as _ARR_ELEM_SEMANTICS,
)
from .oe_templates.render_array_eep import (
    _ARR_INSET_FRAC as _ARR_INSET_FRAC,
)
from .oe_templates.render_array_eep import (
    _ARR_NOTCH_CLEAR_MM as _ARR_NOTCH_CLEAR_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_PROBE_HALF_X_MM as _ARR_PROBE_HALF_X_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_PROBE_HALF_Y_MM as _ARR_PROBE_HALF_Y_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_ROW_Y_MM as _ARR_ROW_Y_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_SERIES_FEED_MARGIN_MM as _ARR_SERIES_FEED_MARGIN_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_SERIES_N as _ARR_SERIES_N,
)
from .oe_templates.render_array_eep import (
    _ARR_SPACING_FRAC as _ARR_SPACING_FRAC,
)
from .oe_templates.render_array_eep import (
    _ARR_TREE_SEMANTICS as _ARR_TREE_SEMANTICS,
)
from .oe_templates.render_array_eep import (
    _ARR_TREE_Y_MM as _ARR_TREE_Y_MM,
)
from .oe_templates.render_array_eep import (
    _ARR_TRUNK_MM as _ARR_TRUNK_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_BOARD_MM as _EEP_BOARD_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_EDGE_MARGIN_MM as _EEP_EDGE_MARGIN_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_ELEM_SEMANTICS as _EEP_ELEM_SEMANTICS,
)
from .oe_templates.render_array_eep import (
    _EEP_NOTCH_CLEAR_MM as _EEP_NOTCH_CLEAR_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_PROBE_HALF_X_MM as _EEP_PROBE_HALF_X_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_PROBE_HALF_Y_MM as _EEP_PROBE_HALF_Y_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_ROW_Y_MM as _EEP_ROW_Y_MM,
)
from .oe_templates.render_array_eep import (
    _EEP_SPACING_FRAC as _EEP_SPACING_FRAC,
)
from .oe_templates.render_array_eep import (
    ARRAY_META as ARRAY_META,
)
from .oe_templates.render_array_eep import (
    ARRAY_NOMINAL as ARRAY_NOMINAL,
)
from .oe_templates.render_array_eep import (
    ARRAY_TEMPLATES as ARRAY_TEMPLATES,
)
from .oe_templates.render_array_eep import (
    EEP_FF_PHI_DEG as EEP_FF_PHI_DEG,
)
from .oe_templates.render_array_eep import (
    EEP_FF_THETA_DEG as EEP_FF_THETA_DEG,
)
from .oe_templates.render_array_eep import (
    EEP_META as EEP_META,
)
from .oe_templates.render_array_eep import (
    EEP_NOMINAL as EEP_NOMINAL,
)
from .oe_templates.render_array_eep import (
    EEP_TEMPLATES as EEP_TEMPLATES,
)
from .oe_templates.render_array_eep import (
    _arr_body as _arr_body,
)
from .oe_templates.render_array_eep import (
    _arr_layout as _arr_layout,
)
from .oe_templates.render_array_eep import (
    _eep_body as _eep_body,
)
from .oe_templates.render_array_eep import (
    _eep_layout as _eep_layout,
)
from .oe_templates.render_array_eep import (
    _patch_array_1x4_lines as _patch_array_1x4_lines,
)
from .oe_templates.render_array_eep import (
    _patch_array_2x2_lines as _patch_array_2x2_lines,
)
from .oe_templates.render_array_eep import (
    _patch_array_series_lines as _patch_array_series_lines,
)
from .oe_templates.render_array_eep import (
    _patch_eep_1x4_lines as _patch_eep_1x4_lines,
)
from .oe_templates.render_array_eep import (
    _patch_eep_2x2_lines as _patch_eep_2x2_lines,
)
from .oe_templates.render_array_eep import (
    array_design_params as array_design_params,
)
from .oe_templates.render_array_eep import (
    array_half_guided_len_mm as array_half_guided_len_mm,
)
from .oe_templates.render_array_eep import (
    array_meta as array_meta,
)
from .oe_templates.render_array_eep import (
    array_quarter_len_mm as array_quarter_len_mm,
)
from .oe_templates.render_array_eep import (
    eep_design_params as eep_design_params,
)
from .oe_templates.render_array_eep import (
    eep_meta as eep_meta,
)
from .oe_templates.render_array_eep import (
    eep_n_ports as eep_n_ports,
)
from .oe_templates.render_c3 import (
    _C3_C_MM_GHZ as _C3_C_MM_GHZ,
)
from .oe_templates.render_c3 import (
    _C3_CAP_LEN_MM as _C3_CAP_LEN_MM,
)
from .oe_templates.render_c3 import (
    _C3_COHN_X_MAX as _C3_COHN_X_MAX,
)
from .oe_templates.render_c3 import (
    _C3_GAP_CELLS_MIN as _C3_GAP_CELLS_MIN,
)
from .oe_templates.render_c3 import (
    _C3_L_VIA_ANCHOR_ID as _C3_L_VIA_ANCHOR_ID,
)
from .oe_templates.render_c3 import (
    _C3_R_VIA_MM as _C3_R_VIA_MM,
)
from .oe_templates.render_c3 import (
    _C3_Z0 as _C3_Z0,
)
from .oe_templates.render_c3 import (
    _MU0_H_PER_M as _MU0_H_PER_M,
)
from .oe_templates.render_c3 import (
    C3_L_VIA_CAL_H as C3_L_VIA_CAL_H,
)
from .oe_templates.render_c3 import (
    C3_TEMPLATES as C3_TEMPLATES,
)
from .oe_templates.render_c3 import (
    COMBLINE_META as COMBLINE_META,
)
from .oe_templates.render_c3 import (
    COMBLINE_NOMINAL as COMBLINE_NOMINAL,
)
from .oe_templates.render_c3 import (
    INTERDIGITAL_META as INTERDIGITAL_META,
)
from .oe_templates.render_c3 import (
    INTERDIGITAL_NOMINAL as INTERDIGITAL_NOMINAL,
)
from .oe_templates.render_c3 import (
    SIR_BPF_META as SIR_BPF_META,
)
from .oe_templates.render_c3 import (
    SIR_BPF_NOMINAL as SIR_BPF_NOMINAL,
)
from .oe_templates.render_c3 import (
    _c3_body as _c3_body,
)
from .oe_templates.render_c3 import (
    _c3_fmt_x as _c3_fmt_x,
)
from .oe_templates.render_c3 import (
    _c3_gaps_from_params as _c3_gaps_from_params,
)
from .oe_templates.render_c3 import (
    _c3_j_targets as _c3_j_targets,
)
from .oe_templates.render_c3 import (
    _c3_jlist_from_geometry as _c3_jlist_from_geometry,
)
from .oe_templates.render_c3 import (
    _c3_l_via_anchor_h as _c3_l_via_anchor_h,
)
from .oe_templates.render_c3 import (
    _c3_l_via_anchor_h_cache as _c3_l_via_anchor_h_cache,
)
from .oe_templates.render_c3 import (
    _c3_l_via_anchor_ready as _c3_l_via_anchor_ready,
)
from .oe_templates.render_c3 import (
    _c3_layout as _c3_layout,
)
from .oe_templates.render_c3 import (
    _c3_prototype as _c3_prototype,
)
from .oe_templates.render_c3 import (
    _c3_single_line as _c3_single_line,
)
from .oe_templates.render_c3 import (
    _c3_theta as _c3_theta,
)
from .oe_templates.render_c3 import (
    _c3_via_resolved_h as _c3_via_resolved_h,
)
from .oe_templates.render_c3 import (
    _c3_via_terminated_short as _c3_via_terminated_short,
)
from .oe_templates.render_c3 import (
    _c3_x_diag as _c3_x_diag,
)
from .oe_templates.render_c3 import (
    _c3_yfns_from_design as _c3_yfns_from_design,
)
from .oe_templates.render_c3 import (
    _c3_yfns_from_geometry as _c3_yfns_from_geometry,
)
from .oe_templates.render_c3 import (
    _combline_lines as _combline_lines,
)
from .oe_templates.render_c3 import (
    _interdigital_lines as _interdigital_lines,
)
from .oe_templates.render_c3 import (
    _sir_bpf_lines as _sir_bpf_lines,
)
from .oe_templates.render_c3 import (
    c3_circuit_sparams as c3_circuit_sparams,
)
from .oe_templates.render_c3 import (
    c3_cohn_j_from_x as c3_cohn_j_from_x,
)
from .oe_templates.render_c3 import (
    c3_cohn_x_from_j as c3_cohn_x_from_j,
)
from .oe_templates.render_c3 import (
    c3_coupling_j_from_gap as c3_coupling_j_from_gap,
)
from .oe_templates.render_c3 import (
    c3_gap_from_coupling_j as c3_gap_from_coupling_j,
)
from .oe_templates.render_c3 import (
    c3_gap_mesh_guard as c3_gap_mesh_guard,
)
from .oe_templates.render_c3 import (
    c3_inverter_chain_sparams as c3_inverter_chain_sparams,
)
from .oe_templates.render_c3 import (
    c3_mesh_max_mm as c3_mesh_max_mm,
)
from .oe_templates.render_c3 import (
    c3_meta as c3_meta,
)
from .oe_templates.render_c3 import (
    c3_slope_combline as c3_slope_combline,
)
from .oe_templates.render_c3 import (
    c3_slope_shorted_stub as c3_slope_shorted_stub,
)
from .oe_templates.render_c3 import (
    c3_slope_sir as c3_slope_sir,
)
from .oe_templates.render_c3 import (
    c3_via_inductance_h as c3_via_inductance_h,
)
from .oe_templates.render_c3 import (
    c3_y_combline as c3_y_combline,
)
from .oe_templates.render_c3 import (
    c3_y_shorted_stub as c3_y_shorted_stub,
)
from .oe_templates.render_c3 import (
    c3_y_sir as c3_y_sir,
)
from .oe_templates.render_c3 import (
    combline_design_from_order as combline_design_from_order,
)
from .oe_templates.render_c3 import (
    combline_theta_r as combline_theta_r,
)
from .oe_templates.render_c3 import (
    interdigital_design_from_order as interdigital_design_from_order,
)
from .oe_templates.render_c3 import (
    sir_bpf_design_from_order as sir_bpf_design_from_order,
)
from .oe_templates.render_c3 import (
    sir_theta_symmetric as sir_theta_symmetric,
)
from .oe_templates.render_c3 import (
    via_inductance_h as via_inductance_h,
)
from .oe_templates.render_c4 import (
    _C4_C_MM_GHZ as _C4_C_MM_GHZ,
)
from .oe_templates.render_c4 import (
    _C4_COUPLED_BOX_PREFIX as _C4_COUPLED_BOX_PREFIX,
)
from .oe_templates.render_c4 import (
    _C4_COUPLER_TEMPLATES as _C4_COUPLER_TEMPLATES,
)
from .oe_templates.render_c4 import (
    _C4_FEED_CLEAR_MM as _C4_FEED_CLEAR_MM,
)
from .oe_templates.render_c4 import (
    _C4_LANGE_BRIDGE_GAP_MM as _C4_LANGE_BRIDGE_GAP_MM,
)
from .oe_templates.render_c4 import (
    _C4_LANGE_BRIDGE_INSET_MM as _C4_LANGE_BRIDGE_INSET_MM,
)
from .oe_templates.render_c4 import (
    _C4_LANGE_BRIDGE_STAGGER_MM as _C4_LANGE_BRIDGE_STAGGER_MM,
)
from .oe_templates.render_c4 import (
    _C4_LANGE_BRIDGE_T_MM as _C4_LANGE_BRIDGE_T_MM,
)
from .oe_templates.render_c4 import (
    _C4_LANGE_BRIDGE_W_MM as _C4_LANGE_BRIDGE_W_MM,
)
from .oe_templates.render_c4 import (
    BRANCHLINE_2SECT_META as BRANCHLINE_2SECT_META,
)
from .oe_templates.render_c4 import (
    BRANCHLINE_2SECT_NOMINAL as BRANCHLINE_2SECT_NOMINAL,
)
from .oe_templates.render_c4 import (
    CLINE_COUPLER_META as CLINE_COUPLER_META,
)
from .oe_templates.render_c4 import (
    CLINE_COUPLER_NOMINAL as CLINE_COUPLER_NOMINAL,
)
from .oe_templates.render_c4 import (
    LANGE_META as LANGE_META,
)
from .oe_templates.render_c4 import (
    LANGE_NOMINAL as LANGE_NOMINAL,
)
from .oe_templates.render_c4 import (
    _branchline_2sect_lines as _branchline_2sect_lines,
)
from .oe_templates.render_c4 import (
    _c4_body_lines as _c4_body_lines,
)
from .oe_templates.render_c4 import (
    _c4_feed_boxes as _c4_feed_boxes,
)
from .oe_templates.render_c4 import (
    _c4_gap_midlines as _c4_gap_midlines,
)
from .oe_templates.render_c4 import (
    _c4_layout as _c4_layout,
)
from .oe_templates.render_c4 import (
    _cline_coupler_lines as _cline_coupler_lines,
)
from .oe_templates.render_c4 import (
    _lange_lines as _lange_lines,
)
from .oe_templates.render_c4 import (
    branchline_2sect_design as branchline_2sect_design,
)
from .oe_templates.render_c4 import (
    branchline_2sect_impedances as branchline_2sect_impedances,
)
from .oe_templates.render_c4 import (
    branchline_2sect_sparams as branchline_2sect_sparams,
)
from .oe_templates.render_c4 import (
    cline_coupler_design as cline_coupler_design,
)
from .oe_templates.render_c4 import (
    coupled_line_coupler_sparams as coupled_line_coupler_sparams,
)
from .oe_templates.render_c4 import (
    coupled_line_zee_zoo as coupled_line_zee_zoo,
)
from .oe_templates.render_c4 import (
    lange_design as lange_design,
)
from .oe_templates.render_c4 import (
    lange_equivalent_zee_zoo as lange_equivalent_zee_zoo,
)
from .oe_templates.render_c4 import (
    lange_pair_zee_zoo as lange_pair_zee_zoo,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_AIR_MARGIN_MM as _COAX_WG_AIR_MARGIN_MM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_F0_GHZ as _COAX_WG_F0_GHZ,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_FEED_R_OHM as _COAX_WG_FEED_R_OHM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_L_WG_MM as _COAX_WG_L_WG_MM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_PIN_LEN_RATIO as _COAX_WG_PIN_LEN_RATIO,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_PIN_R_MM as _COAX_WG_PIN_R_MM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_PORT_H_MM as _COAX_WG_PORT_H_MM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_WG_T_MM as _COAX_WG_WG_T_MM,
)
from .oe_templates.render_coax_wg import (
    _COAX_WG_WR_NAME as _COAX_WG_WR_NAME,
)
from .oe_templates.render_coax_wg import (
    COAX_WG_META as COAX_WG_META,
)
from .oe_templates.render_coax_wg import (
    COAX_WG_NOMINAL as COAX_WG_NOMINAL,
)
from .oe_templates.render_coax_wg import (
    COAX_WG_TEMPLATES as COAX_WG_TEMPLATES,
)
from .oe_templates.render_coax_wg import (
    _coax_wg_layout as _coax_wg_layout,
)
from .oe_templates.render_coax_wg import (
    _coax_wg_nominal as _coax_wg_nominal,
)
from .oe_templates.render_coax_wg import (
    coax_wg_design_params as coax_wg_design_params,
)
from .oe_templates.render_coax_wg import (
    coax_wg_geometry_spec as coax_wg_geometry_spec,
)
from .oe_templates.render_coax_wg import (
    coax_wg_render as coax_wg_render,
)
from .oe_templates.render_coil_nfc import (
    _COIL_NFC_D_OUT_MM as _COIL_NFC_D_OUT_MM,
)
from .oe_templates.render_coil_nfc import (
    COIL_NFC_META as COIL_NFC_META,
)
from .oe_templates.render_coil_nfc import (
    COIL_NFC_NOMINAL as COIL_NFC_NOMINAL,
)
from .oe_templates.render_coil_nfc import (
    COIL_NFC_TEMPLATES as COIL_NFC_TEMPLATES,
)
from .oe_templates.render_coil_nfc import (
    _coil_nfc_layout as _coil_nfc_layout,
)
from .oe_templates.render_coil_nfc import (
    _coil_nfc_nominal_dout as _coil_nfc_nominal_dout,
)
from .oe_templates.render_coil_nfc import (
    _coil_nfc_seg_box as _coil_nfc_seg_box,
)
from .oe_templates.render_coil_nfc import (
    coil_nfc_geometry_spec as coil_nfc_geometry_spec,
)
from .oe_templates.render_coil_nfc import (
    coil_nfc_render as coil_nfc_render,
)
from .oe_templates.render_core import (
    geometry_spec as geometry_spec,
)
from .oe_templates.render_core import (
    render_script as render_script,
)
from .oe_templates.render_coupled_bpf import (
    COUPLED_BPF_META as COUPLED_BPF_META,
)
from .oe_templates.render_coupled_bpf import (
    COUPLED_BPF_NOMINAL as COUPLED_BPF_NOMINAL,
)
from .oe_templates.render_coupled_bpf import (
    _abcd_line as _abcd_line,
)
from .oe_templates.render_coupled_bpf import (
    _coupled_bpf_layout as _coupled_bpf_layout,
)
from .oe_templates.render_coupled_bpf import (
    _coupled_bpf_lines as _coupled_bpf_lines,
)
from .oe_templates.render_coupled_bpf import (
    _coupled_bpf_section_lengths_mm as _coupled_bpf_section_lengths_mm,
)
from .oe_templates.render_coupled_bpf import (
    _coupled_section_s4 as _coupled_section_s4,
)
from .oe_templates.render_coupled_bpf import (
    _s2_to_abcd as _s2_to_abcd,
)
from .oe_templates.render_coupled_bpf import (
    _s4_reduce_cross_opens as _s4_reduce_cross_opens,
)
from .oe_templates.render_coupled_bpf import (
    _tl_two_port_s as _tl_two_port_s,
)
from .oe_templates.render_coupled_bpf import (
    coupled_bpf_circuit_sparams as coupled_bpf_circuit_sparams,
)
from .oe_templates.render_coupled_bpf import (
    coupled_bpf_design_from_order as coupled_bpf_design_from_order,
)
from .oe_templates.render_coupled_bpf import (
    coupled_bpf_meta as coupled_bpf_meta,
)
from .oe_templates.render_diplexer_ridged import (
    DIPLEXER_META as DIPLEXER_META,
)
from .oe_templates.render_diplexer_ridged import (
    DIPLEXER_NOMINAL as DIPLEXER_NOMINAL,
)
from .oe_templates.render_diplexer_ridged import (
    RIDGED_WG_META as RIDGED_WG_META,
)
from .oe_templates.render_diplexer_ridged import (
    RIDGED_WG_NOMINAL as RIDGED_WG_NOMINAL,
)
from .oe_templates.render_diplexer_ridged import (
    RIDGED_WG_TEMPLATES as RIDGED_WG_TEMPLATES,
)
from .oe_templates.render_diplexer_ridged import (
    _diplexer_layout as _diplexer_layout,
)
from .oe_templates.render_diplexer_ridged import (
    _diplexer_lines as _diplexer_lines,
)
from .oe_templates.render_diplexer_ridged import (
    diplexer_design_params as diplexer_design_params,
)
from .oe_templates.render_diplexer_ridged import (
    ridged_wg_design_params as ridged_wg_design_params,
)
from .oe_templates.render_diplexer_ridged import (
    ridged_wg_geometry_spec as ridged_wg_geometry_spec,
)
from .oe_templates.render_diplexer_ridged import (
    ridged_wg_layout as ridged_wg_layout,
)
from .oe_templates.render_diplexer_ridged import (
    ridged_wg_render as ridged_wg_render,
)
from .oe_templates.render_hairpin import (
    _HAIRPIN_50OHM_W_MM as _HAIRPIN_50OHM_W_MM,
)
from .oe_templates.render_hairpin import (
    _HAIRPIN_ORIENTATIONS as _HAIRPIN_ORIENTATIONS,
)
from .oe_templates.render_hairpin import (
    HAIRPIN_ALT_META as HAIRPIN_ALT_META,
)
from .oe_templates.render_hairpin import (
    HAIRPIN_ALT_NOMINAL as HAIRPIN_ALT_NOMINAL,
)
from .oe_templates.render_hairpin import (
    HAIRPIN_META as HAIRPIN_META,
)
from .oe_templates.render_hairpin import (
    HAIRPIN_NOMINAL as HAIRPIN_NOMINAL,
)
from .oe_templates.render_hairpin import (
    _hairpin_alt_layout as _hairpin_alt_layout,
)
from .oe_templates.render_hairpin import (
    _hairpin_alt_lines as _hairpin_alt_lines,
)
from .oe_templates.render_hairpin import (
    _hairpin_alt_orientation as _hairpin_alt_orientation,
)
from .oe_templates.render_hairpin import (
    _hairpin_layout as _hairpin_layout,
)
from .oe_templates.render_hairpin import (
    _hairpin_lines as _hairpin_lines,
)
from .oe_templates.render_hairpin import (
    coupled_microstrip_even_odd_ohm as coupled_microstrip_even_odd_ohm,
)
from .oe_templates.render_hairpin import (
    hairpin_alt_meta as hairpin_alt_meta,
)
from .oe_templates.render_hairpin import (
    hairpin_arm_len_mm as hairpin_arm_len_mm,
)
from .oe_templates.render_hairpin import (
    hairpin_design_from_order as hairpin_design_from_order,
)
from .oe_templates.render_hairpin import (
    hairpin_gap_mm_from_k as hairpin_gap_mm_from_k,
)
from .oe_templates.render_hairpin import (
    hairpin_k_from_gap_mm as hairpin_k_from_gap_mm,
)
from .oe_templates.render_hairpin import (
    hairpin_meta as hairpin_meta,
)
from .oe_templates.render_hairpin import (
    hairpin_qe_from_tap_frac as hairpin_qe_from_tap_frac,
)
from .oe_templates.render_hairpin import (
    hairpin_tap_frac_from_qe as hairpin_tap_frac_from_qe,
)
from .oe_templates.render_horn import (
    _PYRAMID_HORN_AIR_MARGIN_MM as _PYRAMID_HORN_AIR_MARGIN_MM,
)
from .oe_templates.render_horn import (
    _PYRAMID_HORN_L_FEED_MM as _PYRAMID_HORN_L_FEED_MM,
)
from .oe_templates.render_horn import (
    _PYRAMID_HORN_N_SEG as _PYRAMID_HORN_N_SEG,
)
from .oe_templates.render_horn import (
    PYRAMID_HORN_META as PYRAMID_HORN_META,
)
from .oe_templates.render_horn import (
    PYRAMID_HORN_NOMINAL as PYRAMID_HORN_NOMINAL,
)
from .oe_templates.render_horn import (
    PYRAMID_HORN_TEMPLATES as PYRAMID_HORN_TEMPLATES,
)
from .oe_templates.render_horn import (
    _pyramid_horn_layout as _pyramid_horn_layout,
)
from .oe_templates.render_horn import (
    _pyramid_horn_nominal as _pyramid_horn_nominal,
)
from .oe_templates.render_horn import (
    pyramid_horn_geometry_spec as pyramid_horn_geometry_spec,
)
from .oe_templates.render_horn import (
    pyramid_horn_render as pyramid_horn_render,
)
from .oe_templates.render_metasurface import (
    _MS_ARRAY_CELL_MAP as _MS_ARRAY_CELL_MAP,
)
from .oe_templates.render_metasurface import (
    _MS_EPS_EFF_SCREEN as _MS_EPS_EFF_SCREEN,
)
from .oe_templates.render_metasurface import (
    _MS_LAM0_MM as _MS_LAM0_MM,
)
from .oe_templates.render_metasurface import (
    _MS_LAMG_MM as _MS_LAMG_MM,
)
from .oe_templates.render_metasurface import (
    _MS_PATCH_NOM_PERIOD as _MS_PATCH_NOM_PERIOD,
)
from .oe_templates.render_metasurface import (
    _TEMPLATE_WALL_BC as _TEMPLATE_WALL_BC,
)
from .oe_templates.render_metasurface import (
    METASURFACE_TEMPLATES as METASURFACE_TEMPLATES,
)
from .oe_templates.render_metasurface import (
    MS_ARRAY_META as MS_ARRAY_META,
)
from .oe_templates.render_metasurface import (
    MS_ARRAY_NOMINAL as MS_ARRAY_NOMINAL,
)
from .oe_templates.render_metasurface import (
    MS_CROSS_META as MS_CROSS_META,
)
from .oe_templates.render_metasurface import (
    MS_CROSS_NOMINAL as MS_CROSS_NOMINAL,
)
from .oe_templates.render_metasurface import (
    MS_JCROSS_META as MS_JCROSS_META,
)
from .oe_templates.render_metasurface import (
    MS_JCROSS_NOMINAL as MS_JCROSS_NOMINAL,
)
from .oe_templates.render_metasurface import (
    MS_PATCH_META as MS_PATCH_META,
)
from .oe_templates.render_metasurface import (
    MS_PATCH_NOMINAL as MS_PATCH_NOMINAL,
)
from .oe_templates.render_metasurface import (
    MS_RING_PATCH_META as MS_RING_PATCH_META,
)
from .oe_templates.render_metasurface import (
    MS_RING_PATCH_NOMINAL as MS_RING_PATCH_NOMINAL,
)
from .oe_templates.render_metasurface import (
    MS_UNIT_TEMPLATES as MS_UNIT_TEMPLATES,
)
from .oe_templates.render_metasurface import (
    PORTLESS_TEMPLATES as PORTLESS_TEMPLATES,
)
from .oe_templates.render_metasurface import (
    _fmt_float_list as _fmt_float_list,
)
from .oe_templates.render_metasurface import (
    _ms_cross_lines as _ms_cross_lines,
)
from .oe_templates.render_metasurface import (
    _ms_gap_midlines as _ms_gap_midlines,
)
from .oe_templates.render_metasurface import (
    _ms_jcross_lines as _ms_jcross_lines,
)
from .oe_templates.render_metasurface import (
    _ms_nominal as _ms_nominal,
)
from .oe_templates.render_metasurface import (
    _ms_patch_lines as _ms_patch_lines,
)
from .oe_templates.render_metasurface import (
    _ms_ring_patch_lines as _ms_ring_patch_lines,
)
from .oe_templates.render_metasurface import (
    ms_array_layout as ms_array_layout,
)
from .oe_templates.render_metasurface import (
    ms_array_render as ms_array_render,
)
from .oe_templates.render_metasurface import (
    ms_geometry_spec as ms_geometry_spec,
)
from .oe_templates.render_metasurface import (
    ms_jcross_metal_boxes as ms_jcross_metal_boxes,
)
from .oe_templates.render_metasurface import (
    ms_unit_layout as ms_unit_layout,
)
from .oe_templates.render_mmwave import (
    _MMWAVE_AIR_TOP_MM as _MMWAVE_AIR_TOP_MM,
)
from .oe_templates.render_mmwave import (
    _MMWAVE_DOM_MM as _MMWAVE_DOM_MM,
)
from .oe_templates.render_mmwave import (
    _MMWAVE_FEED_MARGIN_MM as _MMWAVE_FEED_MARGIN_MM,
)
from .oe_templates.render_mmwave import (
    _MMWAVE_LOAD_R_OHM as _MMWAVE_LOAD_R_OHM,
)
from .oe_templates.render_mmwave import (
    _MMWAVE_TAN_D as _MMWAVE_TAN_D,
)
from .oe_templates.render_mmwave import (
    MMWAVE_SERIES_META as MMWAVE_SERIES_META,
)
from .oe_templates.render_mmwave import (
    MMWAVE_SERIES_NOMINAL as MMWAVE_SERIES_NOMINAL,
)
from .oe_templates.render_mmwave import (
    MMWAVE_SERIES_TEMPLATES as MMWAVE_SERIES_TEMPLATES,
)
from .oe_templates.render_mmwave import (
    _mmwave_series_layout as _mmwave_series_layout,
)
from .oe_templates.render_mmwave import (
    mmwave_series_design_params as mmwave_series_design_params,
)
from .oe_templates.render_mmwave import (
    mmwave_series_geometry_spec as mmwave_series_geometry_spec,
)
from .oe_templates.render_mmwave import (
    mmwave_series_meta as mmwave_series_meta,
)
from .oe_templates.render_mmwave import (
    mmwave_series_render as mmwave_series_render,
)
from .oe_templates.render_msl_sma import (
    _MSL_CPW_50OHM_W_MM as _MSL_CPW_50OHM_W_MM,
)
from .oe_templates.render_msl_sma import (
    _SMA_ER_FILL as _SMA_ER_FILL,
)
from .oe_templates.render_msl_sma import (
    _SMA_PORT_CELLS_FROM_BOUNDARY as _SMA_PORT_CELLS_FROM_BOUNDARY,
)
from .oe_templates.render_msl_sma import (
    _SMA_RI_MM as _SMA_RI_MM,
)
from .oe_templates.render_msl_sma import (
    _SMA_SHELL_T_MM as _SMA_SHELL_T_MM,
)
from .oe_templates.render_msl_sma import (
    MSL_CPW_META as MSL_CPW_META,
)
from .oe_templates.render_msl_sma import (
    MSL_CPW_NOMINAL as MSL_CPW_NOMINAL,
)
from .oe_templates.render_msl_sma import (
    SMA_LAUNCHER_META as SMA_LAUNCHER_META,
)
from .oe_templates.render_msl_sma import (
    SMA_LAUNCHER_NOMINAL as SMA_LAUNCHER_NOMINAL,
)
from .oe_templates.render_msl_sma import (
    _msl_cpw_lines as _msl_cpw_lines,
)
from .oe_templates.render_msl_sma import (
    _sma_launcher_lines as _sma_launcher_lines,
)
from .oe_templates.render_msl_sma import (
    sma_launcher_layout as sma_launcher_layout,
)
from .oe_templates.render_msl_sma import (
    sma_launcher_r_o_mm as sma_launcher_r_o_mm,
)
from .oe_templates.render_phase_qwt import (
    QWT_MULTISECTION_META as QWT_MULTISECTION_META,
)
from .oe_templates.render_phase_qwt import (
    QWT_MULTISECTION_NOMINAL as QWT_MULTISECTION_NOMINAL,
)
from .oe_templates.render_phase_qwt import (
    SCHIFFMAN_META as SCHIFFMAN_META,
)
from .oe_templates.render_phase_qwt import (
    SCHIFFMAN_NOMINAL as SCHIFFMAN_NOMINAL,
)
from .oe_templates.render_phase_qwt import (
    _qwt_layout as _qwt_layout,
)
from .oe_templates.render_phase_qwt import (
    _qwt_lines as _qwt_lines,
)
from .oe_templates.render_phase_qwt import (
    _schiffman_layout as _schiffman_layout,
)
from .oe_templates.render_phase_qwt import (
    _schiffman_lines as _schiffman_lines,
)
from .oe_templates.render_phase_qwt import (
    qwt_multisection_design_params as qwt_multisection_design_params,
)
from .oe_templates.render_phase_qwt import (
    schiffman_design_params as schiffman_design_params,
)
from .oe_templates.render_ratrace_cyl import (
    _CYL_ALPHA_CELLS as _CYL_ALPHA_CELLS,
)
from .oe_templates.render_ratrace_cyl import (
    _CYL_RING_AZIMUTH_DEG as _CYL_RING_AZIMUTH_DEG,
)
from .oe_templates.render_ratrace_cyl import (
    _RATRACE_K_ANCHOR_HI as _RATRACE_K_ANCHOR_HI,
)
from .oe_templates.render_ratrace_cyl import (
    _RATRACE_K_ANCHOR_LO as _RATRACE_K_ANCHOR_LO,
)
from .oe_templates.render_ratrace_cyl import (
    _RATRACE_K_BASE_HI_MM as _RATRACE_K_BASE_HI_MM,
)
from .oe_templates.render_ratrace_cyl import (
    _RATRACE_K_BASE_LO_MM as _RATRACE_K_BASE_LO_MM,
)
from .oe_templates.render_ratrace_cyl import (
    _RATRACE_RING_MESH_K as _RATRACE_RING_MESH_K,
)
from .oe_templates.render_ratrace_cyl import (
    _cyl_alpha_lines as _cyl_alpha_lines,
)
from .oe_templates.render_ratrace_cyl import (
    _cyl_azimuths_rad as _cyl_azimuths_rad,
)
from .oe_templates.render_ratrace_cyl import (
    _ratrace_lines as _ratrace_lines,
)
from .oe_templates.render_ratrace_cyl import (
    build_ratrace_cylindrical as build_ratrace_cylindrical,
)
from .oe_templates.render_ratrace_cyl import (
    ratrace_ring_mesh_k as ratrace_ring_mesh_k,
)
from .oe_templates.render_ratrace_cyl import (
    ratrace_ring_mesh_k_clamped as ratrace_ring_mesh_k_clamped,
)
from .oe_templates.render_ratrace_cyl import (
    render_ratrace_cylindrical as render_ratrace_cylindrical,
)
from .oe_templates.render_ring import (
    _C0_M_S as _C0_M_S,
)
from .oe_templates.render_ring import (
    RING_RESONATOR_F1_GHZ as RING_RESONATOR_F1_GHZ,
)
from .oe_templates.render_ring import (
    RING_RESONATOR_GAP_MM as RING_RESONATOR_GAP_MM,
)
from .oe_templates.render_ring import (
    RING_RESONATOR_META as RING_RESONATOR_META,
)
from .oe_templates.render_ring import (
    RING_RESONATOR_NOMINAL as RING_RESONATOR_NOMINAL,
)
from .oe_templates.render_ring import (
    RING_RESONATOR_W_MM as RING_RESONATOR_W_MM,
)
from .oe_templates.render_ring import (
    _ring_resonator_layout as _ring_resonator_layout,
)
from .oe_templates.render_ring import (
    _ring_resonator_lines as _ring_resonator_lines,
)
from .oe_templates.render_ring import (
    ring_resonator_design_params as ring_resonator_design_params,
)
from .oe_templates.render_sicl_nway import (
    NWAY_WILKINSON_META as NWAY_WILKINSON_META,
)
from .oe_templates.render_sicl_nway import (
    NWAY_WILKINSON_NOMINAL as NWAY_WILKINSON_NOMINAL,
)
from .oe_templates.render_sicl_nway import (
    SICL_META as SICL_META,
)
from .oe_templates.render_sicl_nway import (
    SICL_NOMINAL as SICL_NOMINAL,
)
from .oe_templates.render_sicl_nway import (
    _nway_layout as _nway_layout,
)
from .oe_templates.render_sicl_nway import (
    _nway_lines as _nway_lines,
)
from .oe_templates.render_sicl_nway import (
    _sicl_lines as _sicl_lines,
)
from .oe_templates.render_sicl_nway import (
    nway_wilkinson_design_params as nway_wilkinson_design_params,
)
from .oe_templates.render_sicl_nway import (
    sicl_design_params as sicl_design_params,
)
from .oe_templates.render_sicl_nway import (
    sicl_layout as sicl_layout,
)
from .oe_templates.render_siw import (
    _MSL_SIW_FEED_BASE as _MSL_SIW_FEED_BASE,
)
from .oe_templates.render_siw import (
    _MSL_SIW_MESH_FLOOR_M as _MSL_SIW_MESH_FLOOR_M,
)
from .oe_templates.render_siw import (
    _MSL_SIW_SEAM_NEAR as _MSL_SIW_SEAM_NEAR,
)
from .oe_templates.render_siw import (
    _SIW_MESH_FLOOR_M as _SIW_MESH_FLOOR_M,
)
from .oe_templates.render_siw import (
    _SIW_PORT_INSET_BASE as _SIW_PORT_INSET_BASE,
)
from .oe_templates.render_siw import (
    COMPOSE_CONTRACTS as COMPOSE_CONTRACTS,
)
from .oe_templates.render_siw import (
    MSL_SIW_TAPER_META as MSL_SIW_TAPER_META,
)
from .oe_templates.render_siw import (
    MSL_SIW_TAPER_NOMINAL as MSL_SIW_TAPER_NOMINAL,
)
from .oe_templates.render_siw import (
    MSL_SIW_TAPER_PORT_PINS as MSL_SIW_TAPER_PORT_PINS,
)
from .oe_templates.render_siw import (
    SIW_META as SIW_META,
)
from .oe_templates.render_siw import (
    SIW_NOMINAL as SIW_NOMINAL,
)
from .oe_templates.render_siw import (
    SIW_PORT_PINS as SIW_PORT_PINS,
)
from .oe_templates.render_siw import (
    _compose_pin as _compose_pin,
)
from .oe_templates.render_siw import (
    _msl_siw_taper_compose_layout as _msl_siw_taper_compose_layout,
)
from .oe_templates.render_siw import (
    _msl_siw_taper_lines as _msl_siw_taper_lines,
)
from .oe_templates.render_siw import (
    _siw_compose_layout as _siw_compose_layout,
)
from .oe_templates.render_siw import (
    _siw_lines as _siw_lines,
)
from .oe_templates.render_siw import (
    _siw_r_port_ohm as _siw_r_port_ohm,
)
from .oe_templates.render_siw import (
    msl_siw_taper_layout as msl_siw_taper_layout,
)
from .oe_templates.render_siw import (
    siw_layout as siw_layout,
)
from .oe_templates.render_slotline import (
    _SLOTLINE_MODE_FILE_DEFAULTS as _SLOTLINE_MODE_FILE_DEFAULTS,
)
from .oe_templates.render_slotline import (
    MARCHAND2_VIA_MODES as MARCHAND2_VIA_MODES,
)
from .oe_templates.render_slotline import (
    MARCHAND2_VIA_SIDE_MM as MARCHAND2_VIA_SIDE_MM,
)
from .oe_templates.render_slotline import (
    MARCHAND_BALUN_META as MARCHAND_BALUN_META,
)
from .oe_templates.render_slotline import (
    MARCHAND_BALUN_NOMINAL as MARCHAND_BALUN_NOMINAL,
)
from .oe_templates.render_slotline import (
    MSL_SLOT_TRANSITION_META as MSL_SLOT_TRANSITION_META,
)
from .oe_templates.render_slotline import (
    MSL_SLOT_TRANSITION_NOMINAL as MSL_SLOT_TRANSITION_NOMINAL,
)
from .oe_templates.render_slotline import (
    SLOTLINE_FAMILY_TEMPLATES as SLOTLINE_FAMILY_TEMPLATES,
)
from .oe_templates.render_slotline import (
    SLOTLINE_LUMPED_META as SLOTLINE_LUMPED_META,
)
from .oe_templates.render_slotline import (
    SLOTLINE_LUMPED_NOMINAL as SLOTLINE_LUMPED_NOMINAL,
)
from .oe_templates.render_slotline import (
    SLOTLINE_META as SLOTLINE_META,
)
from .oe_templates.render_slotline import (
    SLOTLINE_NOMINAL as SLOTLINE_NOMINAL,
)
from .oe_templates.render_slotline import (
    _slotline_family_params as _slotline_family_params,
)
from .oe_templates.render_slotline import (
    marchand2_via_geometry as marchand2_via_geometry,
)
from .oe_templates.render_slotline import (
    render_marchand2_script as render_marchand2_script,
)
from .oe_templates.render_slotline import (
    slotline_family_geometry_spec as slotline_family_geometry_spec,
)
from .oe_templates.render_slotline import (
    slotline_family_render as slotline_family_render,
)
from .oe_templates.render_tl import (
    _atten_pi_lines as _atten_pi_lines,
)
from .oe_templates.render_tl import (
    _atten_t_lines as _atten_t_lines,
)
from .oe_templates.render_tl import (
    _bend_lines as _bend_lines,
)
from .oe_templates.render_tl import (
    _branchline_lines as _branchline_lines,
)
from .oe_templates.render_tl import (
    _coupled_lines as _coupled_lines,
)
from .oe_templates.render_tl import (
    _cps_lines as _cps_lines,
)
from .oe_templates.render_tl import (
    _cpw_lines as _cpw_lines,
)
from .oe_templates.render_tl import (
    _dipole_lines as _dipole_lines,
)
from .oe_templates.render_tl import (
    _gysel_jog_lines as _gysel_jog_lines,
)
from .oe_templates.render_tl import (
    _gysel_layout as _gysel_layout,
)
from .oe_templates.render_tl import (
    _gysel_lines as _gysel_lines,
)
from .oe_templates.render_tl import (
    _mline_lines as _mline_lines,
)
from .oe_templates.render_tl import (
    _patch_lines as _patch_lines,
)
from .oe_templates.render_tl import (
    _stepped_lines as _stepped_lines,
)
from .oe_templates.render_tl import (
    _stripline_lines as _stripline_lines,
)
from .oe_templates.render_tl import (
    _suspended_stripline_lines as _suspended_stripline_lines,
)
from .oe_templates.render_tl import (
    _tjunc_lines as _tjunc_lines,
)
from .oe_templates.render_tl import (
    _via_lines as _via_lines,
)
from .oe_templates.render_tl import (
    _wilk_lines as _wilk_lines,
)
from .oe_templates.render_tl import (
    _wstep_lines as _wstep_lines,
)
from .oe_templates.render_varactor import (
    VARACTOR_BPF_META as VARACTOR_BPF_META,
)
from .oe_templates.render_varactor import (
    VARACTOR_BPF_NOMINAL as VARACTOR_BPF_NOMINAL,
)
from .oe_templates.render_varactor import (
    _varactor_bpf_lines as _varactor_bpf_lines,
)
from .oe_templates.render_varactor import (
    varactor_bpf_meta as varactor_bpf_meta,
)
from .oe_templates.smatrix import (
    loaded_ratios_to_line_basis as loaded_ratios_to_line_basis,
)
from .oe_templates.smatrix import (
    renorm_engine_s_to_ref as renorm_engine_s_to_ref,
)
from .oe_templates.smatrix import (
    tl_gamma_per_m as tl_gamma_per_m,
)
from .oe_templates.smatrix import (
    wstep_deembed_lens_m as wstep_deembed_lens_m,
)

# name → (def 模块, 全部 by-value 导入方)：facade setattr 扇出清单
_PATCH_THROUGH = {
    "_c3_l_via_anchor_ready": ("render_c3",),
    "_c3_l_via_anchor_h_cache": ("render_c3",),
    "_c3_l_via_anchor_h": ("render_c3",),
    "_open_end_delta_mm": ("closedform", "render_coupled_bpf", "render_c3",),
    "_C4_LANGE_BRIDGE_GAP_MM": ("render_c4",),
}


class _FacadeModule(_ModuleType):
    """facade setattr 双写：补丁扇出到归属+导入方子模块全局（AU-1）。"""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for owner_mod in _PATCH_THROUGH.get(name, ()):
            setattr(_importlib.import_module(
                "rfauto.adapters.oe_templates." + owner_mod),
                    name, value)


_sys.modules[__name__].__class__ = _FacadeModule
