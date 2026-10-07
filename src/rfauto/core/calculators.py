"""E4 CalculatorRegistry：微波闭式计算器（纯函数，零 IO，单位口径显式）。

方案 WP0.2 / 扩展点 E4：一个计算器 = 注册表条目（名字 + 参数说明 + 纯
函数），UI/CLI/MCP 三壳共享同一 service 入口。单位约定：长度 mm、频率
GHz、阻抗 Ω、衰减 dB；返回值一律 JSON 可序列化 dict。

权威口径（铁律 1c）：
- 微带正/反解：skrf MLine (Hammerstad-Jensen)——与 core/synthesis.py 同链
- CPW：skrf CPW（quasi-static，含基底厚度 h）
- 带状线：零厚度对称结构椭圆积分共形映射闭式（t=0 精确；
  参照 w/b=1、er=1 → ≈65.4Ω，AGM 可复算：
  core.calc_families.rf_line._stripline_z0(1,1,1)=65.3989 Ω（2026-10-04
  venv 实测复算；旧"≈68Ω 文献锚"系陈旧值勘误，A-12）
- 贴片谐振：Balanis 口径（W/εeff/ΔL/L），与 synthesis.synthesize_patch
  同公式——两者数值一致性有单测钉住
"""

# ══ AU-1 巨石拆分·批2 facade（2026-09-30）═══════════════════════
# 本文件原为 5707 行巨石，实现拆分至 core/calc_families/ 包（registry/
# rf_line/rf_match/cm_core/cm_extract/thermal/cavity/symbolic/
# slotline_siw/budget/cm_diag/taper/kqe/rfid/shield 共 15 族）。
# 此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir()
# 逐名相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# 注册序：下方首个相对导入触发 calc_families/__init__，按原文件定义
# 顺序导入全部族模块 → CALCULATOR_REGISTRY._specs 插入序与原单文件
# 逐位一致（re-export 块按 isort 典则序仅承载命名，不承载注册序）。

from __future__ import annotations

import ast as ast  # facade：保持原模块公开面（快照钉）
import math as math
from collections.abc import Callable as Callable
from collections.abc import Mapping as Mapping
from collections.abc import Sequence as Sequence
from dataclasses import dataclass as dataclass
from functools import lru_cache as lru_cache
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

import numpy as np  # noqa: F401  # 实名 alias 非 re-export 形态

if TYPE_CHECKING:
    from rfauto.core.symbolic_fit import CandidateFormula  # noqa: F401

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .calc_families.array_synth import (
    array_bayliss_weights as array_bayliss_weights,  # RB-ALG-1/2（Phase3 W3-E）
)
from .calc_families.array_synth import array_quantized_milp as array_quantized_milp
from .calc_families.array_synth import array_schelkunoff_nulls as array_schelkunoff_nulls
from .calc_families.array_synth import array_villeneuve_weights as array_villeneuve_weights
from .calc_families.budget import cascade_budget as cascade_budget
from .calc_families.budget import if_plan_sweep as if_plan_sweep
from .calc_families.budget import spur_search as spur_search
from .calc_families.cavity import _points_inside_mesh as _points_inside_mesh
from .calc_families.cavity import _te101_field_integrals_box as _te101_field_integrals_box
from .calc_families.cavity import cavity_perturbation_shift as cavity_perturbation_shift
from .calc_families.cm_core import _cm_cong_rot as _cm_cong_rot
from .calc_families.cm_core import _cm_folded_family as _cm_folded_family
from .calc_families.cm_core import _cm_folded_keepers as _cm_folded_keepers
from .calc_families.cm_core import _cm_folded_keepers_shifted as _cm_folded_keepers_shifted
from .calc_families.cm_core import _cm_from_list as _cm_from_list
from .calc_families.cm_core import _cm_pack as _cm_pack
from .calc_families.cm_core import _cm_pattern_viol as _cm_pattern_viol
from .calc_families.cm_core import _cm_polish as _cm_polish
from .calc_families.cm_core import _cm_poly_max_err as _cm_poly_max_err
from .calc_families.cm_core import _cm_reduce_arrow as _cm_reduce_arrow
from .calc_families.cm_core import _cm_reduce_folded as _cm_reduce_folded
from .calc_families.cm_core import _cm_response_raw as _cm_response_raw
from .calc_families.cm_core import _cm_s21_phase_flipped as _cm_s21_phase_flipped
from .calc_families.cm_core import _cm_sign_normalize as _cm_sign_normalize
from .calc_families.cm_core import _cm_to_list as _cm_to_list
from .calc_families.cm_core import _cm_transversal_exact as _cm_transversal_exact
from .calc_families.cm_core import _cm_unpack as _cm_unpack
from .calc_families.cm_core import _gcheb_fn as _gcheb_fn
from .calc_families.cm_core import _gcheb_fn_explicit as _gcheb_fn_explicit
from .calc_families.cm_core import _gcheb_prototype as _gcheb_prototype
from .calc_families.cm_core import _gcheb_prototype_explicit as _gcheb_prototype_explicit
from .calc_families.cm_core import _gcheb_reflection_zeros as _gcheb_reflection_zeros
from .calc_families.cm_core import _gcheb_reflection_zeros_explicit as _gcheb_reflection_zeros_explicit
from .calc_families.cm_core import _gcheb_x_factor as _gcheb_x_factor
from .calc_families.cm_core import _gcheb_yprod as _gcheb_yprod
from .calc_families.cm_core import _poly_response as _poly_response
from .calc_families.cm_core import _tz_explicit_check as _tz_explicit_check
from .calc_families.cm_core import chebyshev_prototype as chebyshev_prototype
from .calc_families.cm_core import chebyshev_prototype_asym as chebyshev_prototype_asym
from .calc_families.cm_core import chebyshev_refl_fn as chebyshev_refl_fn
from .calc_families.cm_core import coupling_matrix_arrow as coupling_matrix_arrow
from .calc_families.cm_core import coupling_matrix_folded as coupling_matrix_folded
from .calc_families.cm_core import coupling_matrix_response as coupling_matrix_response
from .calc_families.cm_core import coupling_matrix_synthesize_explicit as coupling_matrix_synthesize_explicit
from .calc_families.cm_core import coupling_matrix_synthesize_n2 as coupling_matrix_synthesize_n2
from .calc_families.cm_diag import _CAT_C_REFLECTION as _CAT_C_REFLECTION
from .calc_families.cm_diag import _CAT_C_TRANSMISSION as _CAT_C_TRANSMISSION
from .calc_families.cm_diag import _dp2_band_pairs as _dp2_band_pairs
from .calc_families.cm_diag import _dp2_cm_model as _dp2_cm_model
from .calc_families.cm_diag import _dp2_group_delay_phys as _dp2_group_delay_phys
from .calc_families.cm_diag import _dp2_omega_norm as _dp2_omega_norm
from .calc_families.cm_diag import _dp2_pole_map_to_omega as _dp2_pole_map_to_omega
from .calc_families.cm_diag import _dp2_prominent_peaks as _dp2_prominent_peaks
from .calc_families.cm_diag import _dp2_response_batch as _dp2_response_batch
from .calc_families.cm_diag import _dp2_support_set as _dp2_support_set
from .calc_families.cm_diag import _dp2_theta_pack as _dp2_theta_pack
from .calc_families.cm_diag import _dp2_vf_fit as _dp2_vf_fit
from .calc_families.cm_diag import _dp2_vf_rational_polys as _dp2_vf_rational_polys
from .calc_families.cm_diag import _dp2_vf_s11_rational as _dp2_vf_s11_rational
from .calc_families.cm_diag import _q_circle_channel as _q_circle_channel
from .calc_families.cm_diag import _taubin_circle_fit as _taubin_circle_fit
from .calc_families.cm_diag import cat_critique as cat_critique
from .calc_families.cm_diag import cm_extract_vf as cm_extract_vf
from .calc_families.cm_diag import cm_refine_lm as cm_refine_lm
from .calc_families.cm_diag import q_factor_circle as q_factor_circle
from .calc_families.cm_diag import q_factor_vf as q_factor_vf
from .calc_families.cm_diag import q_factor_vf_zero as q_factor_vf_zero
from .calc_families.cm_extract import _CM_DEROT_COMPLEX_TOL as _CM_DEROT_COMPLEX_TOL
from .calc_families.cm_extract import _cm_as_complex as _cm_as_complex
from .calc_families.cm_extract import _cm_band_edges as _cm_band_edges
from .calc_families.cm_extract import _cm_derotate as _cm_derotate
from .calc_families.cm_extract import _cm_derotation_residual as _cm_derotation_residual
from .calc_families.cm_extract import _cm_extract_from_fit as _cm_extract_from_fit
from .calc_families.cm_extract import _cm_fit_rms as _cm_fit_rms
from .calc_families.cm_extract import _cm_mag2_fit as _cm_mag2_fit
from .calc_families.cm_extract import _cm_rational_fit as _cm_rational_fit
from .calc_families.cm_extract import _cm_refine_f0 as _cm_refine_f0
from .calc_families.cm_extract import _cm_refine_ref_delay as _cm_refine_ref_delay
from .calc_families.cm_extract import _cm_spectral_factor as _cm_spectral_factor
from .calc_families.cm_extract import _x_to_s_even as _x_to_s_even
from .calc_families.cm_extract import coupling_matrix_extract as coupling_matrix_extract
from .calc_families.kqe import _KSPLIT_RULE as _KSPLIT_RULE
from .calc_families.kqe import _ksplit_bias_invert as _ksplit_bias_invert
from .calc_families.kqe import _ksplit_find_mode_pair as _ksplit_find_mode_pair
from .calc_families.kqe import _ksplit_parabolic_refine as _ksplit_parabolic_refine
from .calc_families.kqe import k_split_pair as k_split_pair
from .calc_families.kqe import qe_group_delay as qe_group_delay
from .calc_families.registry import C_MM_GHZ as C_MM_GHZ
from .calc_families.registry import CALCULATOR_REGISTRY as CALCULATOR_REGISTRY
from .calc_families.registry import CalculatorRegistry as CalculatorRegistry
from .calc_families.registry import CalculatorSpec as CalculatorSpec
from .calc_families.registry import register_calculator as register_calculator
from .calc_families.rf_line import _C0_MS as _C0_MS
from .calc_families.rf_line import _CPS_GAMMA_ER_ANCHOR_ID as _CPS_GAMMA_ER_ANCHOR_ID
from .calc_families.rf_line import _EPS0 as _EPS0
from .calc_families.rf_line import _SIW_W_EFF_ANCHOR_ID as _SIW_W_EFF_ANCHOR_ID
from .calc_families.rf_line import CPS_CORNER2D_AH_MAX as CPS_CORNER2D_AH_MAX
from .calc_families.rf_line import CPS_CORNER2D_AH_MIN as CPS_CORNER2D_AH_MIN
from .calc_families.rf_line import CPS_CORNER2D_BH_MAX as CPS_CORNER2D_BH_MAX
from .calc_families.rf_line import CPS_CORNER2D_COEFFS as CPS_CORNER2D_COEFFS
from .calc_families.rf_line import CPS_CORNER2D_ER_MAX as CPS_CORNER2D_ER_MAX
from .calc_families.rf_line import CPS_CORNER2D_ER_MIN as CPS_CORNER2D_ER_MIN
from .calc_families.rf_line import CPS_H_EFF_GAMMA_C as CPS_H_EFF_GAMMA_C
from .calc_families.rf_line import CPS_H_EFF_GAMMA_P as CPS_H_EFF_GAMMA_P
from .calc_families.rf_line import SSL_D as SSL_D
from .calc_families.rf_line import SSL_P as SSL_P
from .calc_families.rf_line import SSL_Q_G1 as SSL_Q_G1
from .calc_families.rf_line import SSL_Q_G2 as SSL_Q_G2
from .calc_families.rf_line import _ad_hoc_stackup as _ad_hoc_stackup
from .calc_families.rf_line import _cps_gamma_er_anchor_value as _cps_gamma_er_anchor_value
from .calc_families.rf_line import _cps_ri as _cps_ri
from .calc_families.rf_line import _cpw_media as _cpw_media
from .calc_families.rf_line import _cpwg_ri as _cpwg_ri
from .calc_families.rf_line import _kk_ratio as _kk_ratio
from .calc_families.rf_line import _kk_ratio_tanh as _kk_ratio_tanh
from .calc_families.rf_line import _lambda_g_mm as _lambda_g_mm
from .calc_families.rf_line import _live_anchor_set as _live_anchor_set
from .calc_families.rf_line import _media_z0_eps as _media_z0_eps
from .calc_families.rf_line import _microstrip_media as _microstrip_media
from .calc_families.rf_line import _siw_w_eff_anchor_value as _siw_w_eff_anchor_value
from .calc_families.rf_line import _stripline_z0 as _stripline_z0
from .calc_families.rf_line import _suspended_stripline_ri as _suspended_stripline_ri
from .calc_families.rf_line import cps_analysis as cps_analysis
from .calc_families.rf_line import cps_corner2d_gamma_factor as cps_corner2d_gamma_factor
from .calc_families.rf_line import cps_effective_thickness_factor as cps_effective_thickness_factor
from .calc_families.rf_line import cps_synthesis as cps_synthesis
from .calc_families.rf_line import cpw_analysis as cpw_analysis
from .calc_families.rf_line import cpw_synthesis as cpw_synthesis
from .calc_families.rf_line import cpwg_analysis as cpwg_analysis
from .calc_families.rf_line import cpwg_synthesis as cpwg_synthesis
from .calc_families.rf_line import microstrip_analysis as microstrip_analysis
from .calc_families.rf_line import microstrip_lambda_g as microstrip_lambda_g
from .calc_families.rf_line import microstrip_synthesis as microstrip_synthesis
from .calc_families.rf_line import stripline_analysis as stripline_analysis
from .calc_families.rf_line import stripline_synthesis as stripline_synthesis
from .calc_families.rf_line import suspended_stripline_analysis as suspended_stripline_analysis
from .calc_families.rf_line import suspended_stripline_synthesis as suspended_stripline_synthesis
from .calc_families.rf_match import attenuator_bridged_t as attenuator_bridged_t
from .calc_families.rf_match import attenuator_pi as attenuator_pi
from .calc_families.rf_match import attenuator_t as attenuator_t
from .calc_families.rf_match import patch_length as patch_length
from .calc_families.rf_match import quarter_wave_transformer as quarter_wave_transformer
from .calc_families.rf_match import vswr_convert as vswr_convert
from .calc_families.rfid import _db_to_lin as _db_to_lin
from .calc_families.rfid import _dbm_to_w as _dbm_to_w
from .calc_families.rfid import _rfid_num as _rfid_num
from .calc_families.rfid import _uhf_wavelength_m as _uhf_wavelength_m
from .calc_families.rfid import _w_to_dbm as _w_to_dbm
from .calc_families.rfid import rfid_backscatter_link as rfid_backscatter_link
from .calc_families.rfid import rfid_forward_link as rfid_forward_link
from .calc_families.shield import _ETA0_OHM as _ETA0_OHM
from .calc_families.shield import _MU0_H_PER_M as _MU0_H_PER_M
from .calc_families.shield import _SHIELD_MATERIALS as _SHIELD_MATERIALS
from .calc_families.shield import shielding_effectiveness as shielding_effectiveness
from .calc_families.slotline_siw import siw_analysis as siw_analysis
from .calc_families.slotline_siw import siw_beta_rad_m as siw_beta_rad_m
from .calc_families.slotline_siw import siw_check_design_rules as siw_check_design_rules
from .calc_families.slotline_siw import siw_effective_width_mm as siw_effective_width_mm
from .calc_families.slotline_siw import siw_synthesis as siw_synthesis
from .calc_families.slotline_siw import slotline_analysis as slotline_analysis
from .calc_families.slotline_siw import slotline_synthesis as slotline_synthesis
from .calc_families.symbolic import _ALLOWED_SYMBOLIC_BINOPS as _ALLOWED_SYMBOLIC_BINOPS
from .calc_families.symbolic import _ALLOWED_SYMBOLIC_FUNCS as _ALLOWED_SYMBOLIC_FUNCS
from .calc_families.symbolic import _compile_symbolic_terms as _compile_symbolic_terms
from .calc_families.symbolic import _eval_symbolic_terms as _eval_symbolic_terms
from .calc_families.symbolic import _register_e13_patch_f0 as _register_e13_patch_f0
from .calc_families.symbolic import _validate_symbolic_node as _validate_symbolic_node
from .calc_families.symbolic import register_symbolic_formula as register_symbolic_formula
from .calc_families.taper import _klopfenstein_impedance_profile as _klopfenstein_impedance_profile
from .calc_families.taper import _microstrip_width_for_z0 as _microstrip_width_for_z0
from .calc_families.taper import _mline_z0_of_width as _mline_z0_of_width
from .calc_families.taper import _mline_z0_table as _mline_z0_table
from .calc_families.taper import klopfenstein_taper as klopfenstein_taper
from .calc_families.thermal import _C0_M_PER_S as _C0_M_PER_S
from .calc_families.thermal import _DIELECTRIC_STRENGTH_MV_PER_M as _DIELECTRIC_STRENGTH_MV_PER_M
from .calc_families.thermal import _ECSS_FD_TABLE as _ECSS_FD_TABLE
from .calc_families.thermal import _ECSS_INFLEXION as _ECSS_INFLEXION
from .calc_families.thermal import _ECSS_MATERIAL_ALIASES as _ECSS_MATERIAL_ALIASES
from .calc_families.thermal import _IPC2152_EXTERNAL as _IPC2152_EXTERNAL
from .calc_families.thermal import _IPC2152_INTERNAL_1OZ as _IPC2152_INTERNAL_1OZ
from .calc_families.thermal import _IPC2152_INTERNAL_2OZ as _IPC2152_INTERNAL_2OZ
from .calc_families.thermal import _IPC2152_INTERNAL_3OZ as _IPC2152_INTERNAL_3OZ
from .calc_families.thermal import _IPC2152_INTERNAL_HALF_OZ as _IPC2152_INTERNAL_HALF_OZ
from .calc_families.thermal import _IPC2152_SPLIT_1OZ_2OZ as _IPC2152_SPLIT_1OZ_2OZ
from .calc_families.thermal import _IPC2152_SPLIT_2OZ_3OZ as _IPC2152_SPLIT_2OZ_3OZ
from .calc_families.thermal import _IPC2152_SPLIT_HALF_1OZ as _IPC2152_SPLIT_HALF_1OZ
from .calc_families.thermal import _MIL_PER_MM as _MIL_PER_MM
from .calc_families.thermal import _MIL_PER_OZ as _MIL_PER_OZ
from .calc_families.thermal import _ecss_lookup as _ecss_lookup
from .calc_families.thermal import _finite as _finite
from .calc_families.thermal import _ipc2152_coefficients as _ipc2152_coefficients
from .calc_families.thermal import ecss_multipactor_fd as ecss_multipactor_fd
from .calc_families.thermal import ipc2152_trace_temp_rise as ipc2152_trace_temp_rise
from .calc_families.thermal import microstrip_loss_heat as microstrip_loss_heat
from .calc_families.thermal import parallel_plate_breakdown_margin as parallel_plate_breakdown_margin
from .calc_families.thermal import resonator_thermal_drift as resonator_thermal_drift
from .calc_families.thermal import thermal_resistance_stack as thermal_resistance_stack

# name → (def 模块, 全部 by-value 引用方)：facade setattr 扇出清单
_PATCH_THROUGH = {
    "_cm_poly_max_err": ("cm_core",),
    "_cm_transversal_exact": ("cm_core", "cm_extract",),
}


class _FacadeModule(_ModuleType):
    """facade setattr 双写：补丁扇出到归属+引用方子模块全局（AU-1 批 2）。"""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for owner_mod in _PATCH_THROUGH.get(name, ()):
            setattr(_importlib.import_module(
                "rfauto.core.calc_families." + owner_mod),
                    name, value)


_sys.modules[__name__].__class__ = _FacadeModule
