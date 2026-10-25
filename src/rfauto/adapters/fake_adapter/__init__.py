"""FakeAdapter — 解析近似仿真器 + 故障注入（§9.5）。

无需许可证，秒级返回合成 skrf.Network。
用于单元测试、CI 流水线、优化回路干跑。
"""


from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .adapter import (
    AdapterCapabilities as AdapterCapabilities,
)
from .adapter import (
    Callable as Callable,
)
from .adapter import (
    FakeAdapter as FakeAdapter,
)
from .adapter import (
    ModelBuildError as ModelBuildError,
)
from .adapter import (
    SimulationFailedError as SimulationFailedError,
)
from .adapter import (
    SimulatorAdapter as SimulatorAdapter,
)
from .adapter import (
    SolveReport as SolveReport,
)
from .adapter import (
    math as math,
)
from .adapter import (
    np as np,
)
from .adapter import (
    skrf as skrf,
)
from .antenna_family import (
    _ANT2_C_MM_GHZ as _ANT2_C_MM_GHZ,
)
from .antenna_family import (
    _ANT2_Q as _ANT2_Q,
)
from .antenna_family import (
    _ANT2_R_RAD_OHM as _ANT2_R_RAD_OHM,
)
from .antenna_family import (
    _ANT2_SLOT_Q as _ANT2_SLOT_Q,
)
from .antenna_family import (
    _ANT2_SLOT_R_S_OHM as _ANT2_SLOT_R_S_OHM,
)
from .antenna_family import (
    _ANT2_TEMPLATES as _ANT2_TEMPLATES,
)
from .antenna_family import (
    _ARRAY_C_MM_GHZ as _ARRAY_C_MM_GHZ,
)
from .antenna_family import (
    _ARRAY_Q as _ARRAY_Q,
)
from .antenna_family import (
    _ARRAY_TEMPLATES as _ARRAY_TEMPLATES,
)
from .antenna_family import (
    _EEP_COUP_LINEAR as _EEP_COUP_LINEAR,
)
from .antenna_family import (
    _EEP_TEMPLATES as _EEP_TEMPLATES,
)
from .antenna_family import (
    _MMWAVE_SERIES_TEMPLATES as _MMWAVE_SERIES_TEMPLATES,
)
from .antenna_family import (
    _antenna2_sparams as _antenna2_sparams,
)
from .antenna_family import (
    _array_sparams as _array_sparams,
)
from .antenna_family import (
    _dipole_sparams as _dipole_sparams,
)
from .antenna_family import (
    _eep_sparams as _eep_sparams,
)
from .antenna_family import (
    _hj_eps_eff as _hj_eps_eff,
)
from .antenna_family import (
    _mmwave_series_sparams as _mmwave_series_sparams,
)
from .antenna_family import (
    _patch_sparams_1port as _patch_sparams_1port,
)
from .antenna_family import (
    antenna2_resonance_ghz as antenna2_resonance_ghz,
)
from .antenna_family import (
    array_edge_rin_ohm as array_edge_rin_ohm,
)
from .antenna_family import (
    array_feed_rin_ohm as array_feed_rin_ohm,
)
from .antenna_family import (
    array_resonance_ghz as array_resonance_ghz,
)
from .antenna_family import (
    eep_element_positions_mm as eep_element_positions_mm,
)
from .calibration import (
    _CAL_CACHE as _CAL_CACHE,
)
from .calibration import (
    _DEFAULT_CALIBRATION as _DEFAULT_CALIBRATION,
)
from .calibration import (
    Any as Any,
)
from .calibration import (
    Path as Path,
)
from .calibration import (
    load_fake_calibration as load_fake_calibration,
)
from .capacitor_family import (
    _interdigital_cap_sparams as _interdigital_cap_sparams,
)
from .capacitor_family import (
    _mim_cap_sparams as _mim_cap_sparams,
)
from .coupler_family import (
    _branchline_2sect_sparams as _branchline_2sect_sparams,
)
from .coupler_family import (
    _branchline_sparams as _branchline_sparams,
)
from .coupler_family import (
    _cline_coupler_sparams as _cline_coupler_sparams,
)
from .coupler_family import (
    _coupled_line_sparams as _coupled_line_sparams,
)
from .coupler_family import (
    _lange_sparams as _lange_sparams,
)
from .coupler_family import (
    _stepped_impedance_sparams as _stepped_impedance_sparams,
)
from .coupler_family import (
    _wilkinson_sparams_2port as _wilkinson_sparams_2port,
)
from .coupler_family import (
    _wilkinson_sparams_3port as _wilkinson_sparams_3port,
)
from .fault import (
    FaultInjection as FaultInjection,
)
from .filter_family import (
    _C3_L_VIA_ANCHOR_ID as _C3_L_VIA_ANCHOR_ID,
)
from .filter_family import (
    _C3_L_VIA_CAL_FALLBACK_H as _C3_L_VIA_CAL_FALLBACK_H,
)
from .filter_family import (
    _C3_TEMPLATES as _C3_TEMPLATES,
)
from .filter_family import (
    _HAIRPIN_F0_CORR as _HAIRPIN_F0_CORR,
)
from .filter_family import (
    _HAIRPIN_QE_CORR as _HAIRPIN_QE_CORR,
)
from .filter_family import (
    _c3_l_via_anchor_h as _c3_l_via_anchor_h,
)
from .filter_family import (
    _c3_l_via_anchor_h_cache as _c3_l_via_anchor_h_cache,
)
from .filter_family import (
    _c3_l_via_anchor_ready as _c3_l_via_anchor_ready,
)
from .filter_family import (
    _c3_sparams as _c3_sparams,
)
from .filter_family import (
    _coupled_bpf_sparams as _coupled_bpf_sparams,
)
from .filter_family import (
    _hairpin_sparams as _hairpin_sparams,
)
from .filter_family import (
    hairpin_coupling_matrix as hairpin_coupling_matrix,
)
from .inductor_family import (
    _octagonal_spiral_sparams as _octagonal_spiral_sparams,
)
from .slotline_family import (
    _coil_nfc_sparams as _coil_nfc_sparams,
)
from .slotline_family import (
    _marchand_balun_sparams as _marchand_balun_sparams,
)
from .slotline_family import (
    _msl_slot_transition_sparams as _msl_slot_transition_sparams,
)
from .slotline_family import (
    _slotline_gamma as _slotline_gamma,
)
from .slotline_family import (
    _slotline_route_a_sparams as _slotline_route_a_sparams,
)
from .slotline_family import (
    _slotline_route_b_sparams as _slotline_route_b_sparams,
)
from .tl_family import (
    _atten_pi_sparams as _atten_pi_sparams,
)
from .tl_family import (
    _atten_t_sparams as _atten_t_sparams,
)
from .tl_family import (
    _bend_sparams as _bend_sparams,
)
from .tl_family import (
    _cps_sparams as _cps_sparams,
)
from .tl_family import (
    _cpw_sparams as _cpw_sparams,
)
from .tl_family import (
    _gysel_sparams as _gysel_sparams,
)
from .tl_family import (
    _mline_sparams as _mline_sparams,
)
from .tl_family import (
    _msl_cpw_sparams as _msl_cpw_sparams,
)
from .tl_family import (
    _msl_siw_taper_sparams as _msl_siw_taper_sparams,
)
from .tl_family import (
    _ratrace_sparams as _ratrace_sparams,
)
from .tl_family import (
    _siw_sparams as _siw_sparams,
)
from .tl_family import (
    _sma_launcher_sparams as _sma_launcher_sparams,
)
from .tl_family import (
    _suspended_stripline_sparams as _suspended_stripline_sparams,
)
from .tl_family import (
    _tjunc_sparams as _tjunc_sparams,
)
from .tl_family import (
    _tl_gamma as _tl_gamma,
)
from .tl_family import (
    _via_sparams as _via_sparams,
)
from .tl_family import (
    _wstep_sparams as _wstep_sparams,
)

# ══ AU-1 b4 fake 私有名公开化（2026-09-30）═══════════════════════
# 下列 fake 模型函数被 models/template_specs.py 跨层消费（models→adapters
# 依赖方向合法、私有符号不合法）——升格公开名作为跨层契约；私有名保留为
# 向后兼容别名（仓内 tests/scripts 既有私有拼法继续可用），同一函数对象、
# 零行为变化。新代码一律用公开名。

wilkinson_sparams_3port = _wilkinson_sparams_3port
branchline_sparams = _branchline_sparams
patch_sparams_1port = _patch_sparams_1port
mline_sparams = _mline_sparams
cpw_sparams = _cpw_sparams
dipole_sparams = _dipole_sparams
cps_sparams = _cps_sparams
suspended_stripline_sparams = _suspended_stripline_sparams
msl_cpw_sparams = _msl_cpw_sparams
sma_launcher_sparams = _sma_launcher_sparams
wstep_sparams = _wstep_sparams
tjunc_sparams = _tjunc_sparams
bend_sparams = _bend_sparams
via_sparams = _via_sparams
atten_pi_sparams = _atten_pi_sparams
atten_t_sparams = _atten_t_sparams
ratrace_sparams = _ratrace_sparams
gysel_sparams = _gysel_sparams
hairpin_sparams = _hairpin_sparams
coupled_bpf_sparams = _coupled_bpf_sparams
antenna2_sparams = _antenna2_sparams
cline_coupler_sparams = _cline_coupler_sparams
branchline_2sect_sparams = _branchline_2sect_sparams
lange_sparams = _lange_sparams
stepped_impedance_sparams = _stepped_impedance_sparams
coupled_line_sparams = _coupled_line_sparams
c3_sparams = _c3_sparams
array_sparams = _array_sparams
eep_sparams = _eep_sparams
siw_sparams = _siw_sparams
msl_siw_taper_sparams = _msl_siw_taper_sparams
slotline_route_a_sparams = _slotline_route_a_sparams
slotline_route_b_sparams = _slotline_route_b_sparams
msl_slot_transition_sparams = _msl_slot_transition_sparams
marchand_balun_sparams = _marchand_balun_sparams
coil_nfc_sparams = _coil_nfc_sparams
octagonal_spiral_sparams = _octagonal_spiral_sparams
mim_cap_sparams = _mim_cap_sparams
interdigital_cap_sparams = _interdigital_cap_sparams
mmwave_series_sparams = _mmwave_series_sparams


# ══ R1#8 巨石拆分 facade（aurora_h W4-S2，2026-10-19）══════════════════
# 本文件原为单文件巨石 adapters/fake_adapter.py（3137 行），实现按模板物理
# 域迁入上方 re-export 的子模块（calibration/fault/tl_family/coupler_family/
# filter_family/antenna_family/slotline_family/adapter）；此处逐名显式
# re-export 全部模块级名（公开面快照钉：拆分前后 dir() 逐名相等，
# runs/aurora_h/w4s2_ns_snapshot.py 一次性证明；redundant-alias=PEP 484
# 显式 re-export 惯例）。原件无 __all__（DP-17 公开 API 快照不入册，共享
# 计数面零碰），门面同样保持无 __all__；文末 AU-1 b4 公开别名块（37 行）
# 原件逐字节保留在门面（RHS 私有名经上方 re-export 在位，identity 不变）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数，如 solve() 经本模块 globals 解析的各族 sparams
# 函数与 test_anchor_wire_df7 的 _c3_l_via_anchor_* 状态对）。扇出清单
# 由各子模块 globals 按名自动构建。
_SUBMODULES = (['adapter', 'antenna_family', 'calibration', 'coupler_family',
                'fault', 'filter_family', 'slotline_family', 'tl_family'])


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
