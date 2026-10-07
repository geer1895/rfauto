"""渲染骨架（render_script 总装配 + geometry_spec；族导入序=注册序）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

# isort: skip_file
# 族导入顺序=TEMPLATE_META 注册顺序（不得重排，插入序守恒；
# isort 会按字母重排致注册序漂移——放文件头才生效，2026-09-30 实证）
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass
from .registry import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _DEFAULT_SUB,
    _FOUR_PORT_ROTATION_TEMPLATES,
    _NWAY_PORT_ROTATION_TEMPLATES,
    _SUB_CELLS_8_TEMPLATES,
    _SUB_CELLS_DEFAULT,
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    _THREE_PORT_ROTATION_TEMPLATES,
)
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .grid import _fd_nrts_defaults, _fd_nrts_override_block, _near_points
from .render_hairpin import (
    _hairpin_alt_layout,
    _hairpin_alt_lines,
    _hairpin_layout,
    _hairpin_lines,
)
from .render_coupled_bpf import _coupled_bpf_layout, _coupled_bpf_lines
from .render_msl_sma import (
    _msl_cpw_lines,
    _sma_launcher_lines,
    sma_launcher_layout,
)
from .render_antenna2 import (
    ANTENNA2_TEMPLATES,
    _ANTENNA2_FREE_SPACE_TEMPLATES,
    _ANTENNA2_TALL_TEMPLATES,
    _ant2_layout,
    _helix_lines,
    _ifa_lines,
    _loop_lines,
    _monopole_lines,
    _pifa_lines,
    _slot_lines,
)
from .render_c3 import (
    C3_TEMPLATES,
    _c3_layout,
    _combline_lines,
    _interdigital_lines,
    _sir_bpf_lines,
    c3_gap_mesh_guard,
)
from .render_array_eep import (
    ARRAY_TEMPLATES,
    EEP_FF_PHI_DEG,
    EEP_FF_THETA_DEG,
    EEP_TEMPLATES,
    _arr_layout,
    _eep_layout,
    _patch_array_1x4_lines,
    _patch_array_2x2_lines,
    _patch_array_series_lines,
    _patch_eep_1x4_lines,
    _patch_eep_2x2_lines,
)
from .render_c4 import (
    _C4_COUPLER_TEMPLATES,
    _branchline_2sect_lines,
    _c4_layout,
    _cline_coupler_lines,
    _lange_lines,
)
from .render_siw import (
    _msl_siw_taper_lines,
    _siw_lines,
    _siw_r_port_ohm,
    msl_siw_taper_layout,
    siw_layout,
)
from .render_slotline import (
    SLOTLINE_FAMILY_TEMPLATES,
    slotline_family_geometry_spec,
    slotline_family_render,
)
from .render_metasurface import (
    METASURFACE_TEMPLATES,
    MS_UNIT_TEMPLATES,
    PORTLESS_TEMPLATES,
    _TEMPLATE_WALL_BC,
    _ms_cross_lines,
    _ms_jcross_lines,
    _ms_patch_lines,
    _ms_ring_patch_lines,
    ms_array_render,
    ms_geometry_spec,
    ms_unit_layout,
)
from .render_coil_nfc import (
    COIL_NFC_TEMPLATES,
    coil_nfc_geometry_spec,
    coil_nfc_render,
)
from .render_mmwave import (
    MMWAVE_SERIES_TEMPLATES,
    mmwave_series_geometry_spec,
    mmwave_series_render,
)
from .render_ring import _ring_resonator_lines
from .render_horn import (
    PYRAMID_HORN_TEMPLATES,
    pyramid_horn_geometry_spec,
    pyramid_horn_render,
)
from .render_coax_wg import (
    COAX_WG_TEMPLATES,
    coax_wg_geometry_spec,
    coax_wg_render,
)
from .render_varactor import VARACTOR_BPF_NOMINAL, _varactor_bpf_lines
from .render_phase_qwt import _qwt_lines, _schiffman_lines
from .render_sicl_nway import _nway_lines, _sicl_lines, sicl_layout
from .render_diplexer_ridged import (
    RIDGED_WG_TEMPLATES,
    _diplexer_lines,
    ridged_wg_geometry_spec,
    ridged_wg_render,
)
from .render_ta_wave_a import (
    _fgcpw_lines,
    _hmsiw_lines,
    _inverted_ms_lines,
    hmsiw_layout,
)
from .render_ta_wave_b import (
    _isl_lines,
    _vivaldi_lines,
    isl_layout,
)
from .render_ta_wave_c import (
    _embedded_ms_lines,
    _xcheb_bpf4_layout,
    _xcheb_bpf4_lines,
)
from .render_ratrace_cyl import _ratrace_lines
from .render_tl import (
    _atten_pi_lines,
    _atten_t_lines,
    _bend_lines,
    _branchline_lines,
    _coupled_lines,
    _cps_lines,
    _cpw_lines,
    _dipole_lines,
    _gysel_layout,
    _gysel_lines,
    _mline_lines,
    _patch_lines,
    _stepped_lines,
    _stripline_lines,
    _suspended_stripline_lines,
    _tjunc_lines,
    _via_lines,
    _wilk_lines,
    _wstep_lines,
)



def geometry_spec(
    template: str,
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Template geometry spec (mm units) for UI 3D preview."""
    substrate = substrate or _DEFAULT_SUB
    if template in SLOTLINE_FAMILY_TEMPLATES:
        # 槽线族：盒/端口清单由各 layout 单源换算（文末 SLOTLINE_FAMILY 段）
        return slotline_family_geometry_spec(template, params, substrate)
    if template in METASURFACE_TEMPLATES:
        # §MS_METASURFACE 族（文末 MS_METASURFACE 段）：盒/端口由
        # ms_geometry_spec 单源换算（ms_array_NxN 无端口 ports=[]）
        return ms_geometry_spec(template, params, substrate)
    if template in COIL_NFC_TEMPLATES:
        # §COIL_NFC（文末 COIL_NFC 段）：盒/端口由 coil_nfc_geometry_spec
        # 单源换算（单端口馈隙 LumpedPort）
        return coil_nfc_geometry_spec(params, substrate)
    if template in MMWAVE_SERIES_TEMPLATES:
        # §MMWAVE_SERIES_ARRAY（文末 MMWAVE_SERIES_ARRAY 段）：盒/端口由
        # mmwave_series_geometry_spec 单源换算（单端口 MSLPort 行波串馈）
        return mmwave_series_geometry_spec(params, substrate)
    if template in PYRAMID_HORN_TEMPLATES:
        # §ME-7 角锥喇叭（文末 PYRAMID_HORN 段）：盒/端口由
        # pyramid_horn_geometry_spec 单源换算（单波导口 RectWGPort TE10）
        return pyramid_horn_geometry_spec(params, substrate)
    if template in COAX_WG_TEMPLATES:
        # §ME-6 波导-同轴过渡（文末 COAX_WG 段）：盒/端口由
        # coax_wg_geometry_spec 单源换算（探针基集总桥 + RectWGPort TE10）
        return coax_wg_geometry_spec(params, substrate)
    if template in RIDGED_WG_TEMPLATES:
        # TA-6 空气脊波导（render_diplexer_ridged 文末注册块）：盒/端口由
        # ridged_wg_geometry_spec 单源换算（双 RectWGPort TE10 打在加宽馈段）
        return ridged_wg_geometry_spec(params, substrate)
    h = float(substrate["h_mm"])
    boxes: list[dict[str, Any]] = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-60.0, -60.0, 0.0], "stop_mm": [60.0, 60.0, h]},
        {"name": "ground", "material": "metal",
         "start_mm": [-60.0, -60.0, 0.0], "stop_mm": [60.0, 60.0, 0.0]},
    ]
    ports: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    ZM = h  # 金属面 z（顶面，与 render_script 新 z 口径一致）

    if template == "wilkinson":
        w_in = float(params.get("shunt_w_mm", _nominal_width.W50_MM_R3))
        w_arm = float(params.get("series_w_mm", 0.604))
        l_arm = float(params.get("arm_len_mm", 18.1))
        gap = 8.0
        xa = gap / 2 + w_arm / 2
        y_t = -30.0
        y_end = y_t + l_arm
        boxes += [
            {"name": "t_junction", "material": "metal",
             "start_mm": [-xa - w_arm / 2, y_t, ZM], "stop_mm": [xa + w_arm / 2, y_t + w_arm, ZM]},
            {"name": "arm_left", "material": "metal",
             "start_mm": [-xa - w_arm / 2, y_t, ZM], "stop_mm": [-xa + w_arm / 2, y_end, ZM]},
            {"name": "arm_right", "material": "metal",
             "start_mm": [xa - w_arm / 2, y_t, ZM], "stop_mm": [xa + w_arm / 2, y_end, ZM]},
            # 馈线段由 MSLPort 自画（同几何同宽度），预览补画仅供显示
            {"name": "feed_in", "material": "metal",
             "start_mm": [-w_in / 2, -60.0, ZM], "stop_mm": [w_in / 2, y_t, ZM]},
            {"name": "feed_out_left", "material": "metal",
             "start_mm": [-xa - w_in / 2, y_end, ZM], "stop_mm": [-xa + w_in / 2, 60.0, ZM]},
            {"name": "feed_out_right", "material": "metal",
             "start_mm": [xa - w_in / 2, y_end, ZM], "stop_mm": [xa + w_in / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出1）", "pos_mm": [-xa, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（输出2）", "pos_mm": [xa, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
        elements = [{"name": "isolation_resistor", "kind": "lumped_r", "r_ohm": 100.0,
                     "ny": "x", "span_mm": [-gap / 2, gap / 2], "y_mm": y_end}]
    elif template == "branchline":
        # 标准角馈 branchline（2026-09-05 重构，对照 Microwaves101/PMC）：
        # 环=正方形（横臂 series_w=35.35Ω、竖臂 shunt_w=50Ω，各 λ/4），
        # 四角 50Ω 馈线到端口面；port4（隔离端）2026-09-16 起为真 MSLPort。
        arm_l = float(params.get("arm_len_mm", 20.5))
        sw = float(params.get("series_w_mm", 1.87))    # 横臂 35.35Ω
        shw = float(params.get("shunt_w_mm", 1.11))    # 竖臂/馈线 50Ω
        half = arm_l / 2
        boxes += [
            {"name": "arm_top（35.35Ω 串联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, half - sw / 2, ZM],
             "stop_mm": [half + shw / 2, half + sw / 2, ZM]},
            {"name": "arm_bottom（35.35Ω 串联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, -half - sw / 2, ZM],
             "stop_mm": [half + shw / 2, -half + sw / 2, ZM]},
            {"name": "arm_left（50Ω 并联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, -half, ZM],
             "stop_mm": [-half + shw / 2, half, ZM]},
            {"name": "arm_right（50Ω 并联臂）", "material": "metal",
             "start_mm": [half - shw / 2, -half, ZM],
             "stop_mm": [half + shw / 2, half, ZM]},
            {"name": "feed_p1（50Ω，左下角向下）", "material": "metal",
             "start_mm": [-half - shw / 2, -60.0, ZM],
             "stop_mm": [-half + shw / 2, -half, ZM]},
            {"name": "feed_p2（50Ω，右下角向右）", "material": "metal",
             "start_mm": [half, -half - shw / 2, ZM],
             "stop_mm": [60.0, -half + shw / 2, ZM]},
            {"name": "feed_p3（50Ω，右上角向上）", "material": "metal",
             "start_mm": [half - shw / 2, half, ZM],
             "stop_mm": [half + shw / 2, 60.0, ZM]},
            {"name": "feed_p4（50Ω，左上角向左，隔离端 MSLPort）", "material": "metal",
             "start_mm": [-60.0, half - shw / 2, ZM],
             "stop_mm": [-half, half + shw / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，左下）", "pos_mm": [-half, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通，右下）", "pos_mm": [60.0, -half, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port3（耦合，右上）", "pos_mm": [half, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port4（隔离，左上；2026-09-16 起真 MSLPort）", "pos_mm": [-60.0, half, ZM], "dir": [-1.0, 0.0, 0.0]},
        ]
    elif template == "dipole":
        dip_len = float(params.get("dipole_len_mm", 58.0))
        dip_w = float(params.get("dipole_w_mm", 2.0))
        gap = float(params.get("gap_mm", 2.0))
        feed_w = 2.0
        boxes += [
            {"name": "dipole_left", "material": "metal",
             "start_mm": [-dip_len / 2, -dip_w / 2, ZM], "stop_mm": [-gap / 2, dip_w / 2, ZM]},
            {"name": "dipole_right", "material": "metal",
             "start_mm": [gap / 2, -dip_w / 2, ZM], "stop_mm": [dip_len / 2, dip_w / 2, ZM]},
            {"name": "feed_stub", "material": "metal",
             "start_mm": [-feed_w / 2, -60.0, ZM], "stop_mm": [feed_w / 2, -gap / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（馈电）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "coupled_line":
        cl_len = float(params.get("coupled_len_mm", 20.0))
        cl_w = float(params.get("line_w_mm", 1.0))
        cl_gap = float(params.get("gap_mm", 0.5))
        boxes += [
            {"name": "line_left", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, -cl_len / 2, ZM],
             "stop_mm": [-cl_gap / 2, cl_len / 2, ZM]},
            {"name": "line_right", "material": "metal",
             "start_mm": [cl_gap / 2, -cl_len / 2, ZM],
             "stop_mm": [cl_gap / 2 + cl_w, cl_len / 2, ZM]},
            {"name": "feed_left_in", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, -60.0, ZM],
             "stop_mm": [-cl_gap / 2, -cl_len / 2, ZM]},
            {"name": "feed_left_out", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, cl_len / 2, ZM],
             "stop_mm": [-cl_gap / 2, 60.0, ZM]},
            {"name": "feed_right_in", "material": "metal",
             "start_mm": [cl_gap / 2, -60.0, ZM],
             "stop_mm": [cl_gap / 2 + cl_w, -cl_len / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（直通入）", "pos_mm": [-cl_w - cl_gap / 4, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通出）", "pos_mm": [-cl_w - cl_gap / 4, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（耦合）", "pos_mm": [cl_gap / 2 + cl_w / 2, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "stepped_impedance":
        z1_w = float(params.get("z1_width_mm", 0.3))
        z2_w = float(params.get("z2_width_mm", 3.0))
        # feed 独立宽（六百七十一/#1c 修复批，与 _stepped_lines 同源同缺省：
        # 无 feed_w_mm 回退 z1=修复前口径）
        feed_w = float(params.get("feed_w_mm", z1_w))
        seg_len = float(params.get("seg_len_mm", 5.0))
        n_segs = int(params.get("n_segments", 5))
        total = n_segs * seg_len
        boxes.append({"name": "feed_in", "material": "metal",
                       "start_mm": [-feed_w / 2, -60.0, ZM], "stop_mm": [feed_w / 2, -total / 2, ZM]})
        for i in range(n_segs):
            w = z1_w if i % 2 == 0 else z2_w
            y0 = -total / 2 + i * seg_len
            boxes.append({"name": f"seg_{i}", "material": "metal",
                          "start_mm": [-w / 2, y0, ZM], "stop_mm": [w / 2, y0 + seg_len, ZM]})
        boxes.append({"name": "feed_out", "material": "metal",
                       "start_mm": [-feed_w / 2, total / 2, ZM], "stop_mm": [feed_w / 2, 60.0, ZM]})
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "mline":
        w = float(params.get("w_mm", _nominal_width.W50_MM_R3))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "uniform_line", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
            # 馈线段由 MSLPort 自画（同宽），预览补画仅供显示
            {"name": "feed_in", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -length / 2, ZM]},
            {"name": "feed_out", "material": "metal",
             "start_mm": [-w / 2, length / 2, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "cpw":
        w = float(params.get("w_mm", 0.849))
        gap = float(params.get("gap_mm", 0.2))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "cpw_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
            {"name": "gnd_left", "material": "metal",
             "start_mm": [-60.0, -60.0, ZM],
             "stop_mm": [-w / 2 - gap, 60.0, ZM]},
            {"name": "gnd_right", "material": "metal",
             "start_mm": [w / 2 + gap, -60.0, ZM],
             "stop_mm": [60.0, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "stripline":
        w = float(params.get("w_mm", 0.5554))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "stripline_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "cps":
        # C9 共面带：两条等宽带（沿 y）夹中央缝，无地；两端 LumpedPort 跨缝
        # 差分馈/端接（端口在域内 y=∓L/2，与 _cps_lines 同几何口径）
        w = float(params.get("w_mm", 2.95))
        gap = float(params.get("gap_mm", 0.5))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "cps_strip_left", "material": "metal",
             "start_mm": [-gap / 2 - w, -length / 2, ZM],
             "stop_mm": [-gap / 2, length / 2, ZM]},
            {"name": "cps_strip_right", "material": "metal",
             "start_mm": [gap / 2, -length / 2, ZM],
             "stop_mm": [gap / 2 + w, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（LumpedPort 跨缝差分馈，y=−L/2）",
             "pos_mm": [0.0, -length / 2, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port2（LumpedPort 跨缝差分端接，y=+L/2）",
             "pos_mm": [0.0, length / 2, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "suspended_stripline":
        # C9 悬置带线：带在腔中面 z=b/2（基板 H_SUB 以带为中面对称悬浮）
        w = float(params.get("w_mm", 0.9058))
        b_cav = float(params.get("b_mm", 1.016))
        length = float(params.get("line_len_mm", 40.0))
        zc = b_cav / 2.0
        boxes += [
            {"name": "suspended_stripline_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, zc],
             "stop_mm": [w / 2, length / 2, zc]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, zc], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, zc], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "wstep":
        w1 = float(params.get("w1_mm", _nominal_width.W50_MM))
        w2 = float(params.get("w2_mm", 1.897))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "wstep_seg1", "material": "metal",
             "start_mm": [-w1 / 2, -length / 2, ZM],
             "stop_mm": [w1 / 2, 0.0, ZM]},
            {"name": "wstep_seg2", "material": "metal",
             "start_mm": [-w2 / 2, 0.0, ZM],
             "stop_mm": [w2 / 2, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "tjunc":
        wf = float(params.get("w_feed_mm", _nominal_width.W50_MM))
        tl = float(params.get("through_len_mm", 25.0))
        bl = float(params.get("branch_len_mm", 20.0))
        boxes += [
            {"name": "tjunc_through", "material": "metal",
             "start_mm": [-wf / 2, -tl, ZM], "stop_mm": [wf / 2, tl, ZM]},
            {"name": "tjunc_branch", "material": "metal",
             "start_mm": [0.0, -wf / 2, ZM], "stop_mm": [bl, wf / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（支臂）", "pos_mm": [60.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "bend":
        w = float(params.get("w_mm", _nominal_width.W50_MM))
        a = float(params.get("arm_len_mm", 20.0))
        boxes += [
            {"name": "bend_arm_y", "material": "metal",
             "start_mm": [-w / 2, -a, ZM], "stop_mm": [w / 2, 0.0, ZM]},
            {"name": "bend_arm_x", "material": "metal",
             "start_mm": [0.0, -w / 2, ZM], "stop_mm": [a, w / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [60.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "via":
        w = float(params.get("w_mm", _nominal_width.W50_MM))
        boxes += [
            {"name": "via_top_strip", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, 0.0, ZM]},
            {"name": "via_bot_strip", "material": "metal",
             "start_mm": [-w / 2, 0.0, 0.0], "stop_mm": [w / 2, 60.0, 0.0]},
            {"name": "via_barrel", "material": "metal",
             "start_mm": [-0.15, -0.15, 0.0], "stop_mm": [0.15, 0.15, ZM]},
        ]
        ports = [
            {"name": "Port1（顶层输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（底层输出）", "pos_mm": [0.0, 60.0, 0.0], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "atten_pi":
        w = float(params.get("w_mm", _nominal_width.W50_MM))
        boxes += [
            {"name": "pi_feed_low", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -0.5, ZM]},
            {"name": "pi_feed_high", "material": "metal",
             "start_mm": [-w / 2, 0.5, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "atten_t":
        w = float(params.get("w_mm", _nominal_width.W50_MM))
        boxes += [
            {"name": "t_feed_low", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -5.75, ZM]},
            {"name": "t_feed_mid", "material": "metal",
             "start_mm": [-w / 2, -5.75, ZM], "stop_mm": [w / 2, 5.75, ZM]},
            {"name": "t_feed_high", "material": "metal",
             "start_mm": [-w / 2, 5.75, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "ratrace":
        r = 17.35
        boxes += [
            {"name": "ratrace_ring", "material": "metal",
             "start_mm": [-r, -r, ZM], "stop_mm": [r, r, ZM]},
        ]
        ports = [
            {"name": "Port1（Σ 输入）", "pos_mm": [30.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port2（out1）", "pos_mm": [0.0, 30.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（Δ 隔离）", "pos_mm": [-30.0, 0.0, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port4（out2）", "pos_mm": [0.0, -30.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "gysel":
        # 六节环 L-jog 等长变体（P2⑪ 拓扑重设计，#206 理论核验轮定版基础上）：
        # 下边双臂 70.7Ω（P1 中点分叉，角=P2/P3），左右竖边 50Ω 隔离线竖直段
        # YJ，顶端 L-jog 横移 jog=|arm_len−iso_len| 到 Δ 节点 x=±iso_len，顶边
        # 50Ω 桥带跨度 2·iso_len（λ/2 精确，中点开路），Δ1/Δ2 各接 50Ω 端接。
        # 三端口全部在 y=-BOARD 边（单轴 PML）。几何统一由 _gysel_layout 给出。
        lay = _gysel_layout(params)
        wa, wf, xa = lay["wa"], lay["wf"], lay["xa"]
        yj, xb = lay["yj"], lay["xb"]
        boxes += [
            {"name": "gysel_arm_bottom（70.7Ω 双臂）", "material": "metal",
             "start_mm": [-xa, -wa / 2, ZM], "stop_mm": [xa, wa / 2, ZM]},
            {"name": "gysel_iso_left（50Ω 隔离线竖直段 YJ）", "material": "metal",
             "start_mm": [-xa - wf / 2, 0.0, ZM], "stop_mm": [-xa + wf / 2, yj, ZM]},
            {"name": "gysel_iso_right（50Ω 隔离线竖直段 YJ）", "material": "metal",
             "start_mm": [xa - wf / 2, 0.0, ZM], "stop_mm": [xa + wf / 2, yj, ZM]},
            {"name": "gysel_jog_left（隔离线 L-jog 横移段 → Δ1）", "material": "metal",
             "start_mm": [min(-xa, -xb) - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [max(-xa, -xb) + wf / 2, yj + wf / 2, ZM]},
            {"name": "gysel_jog_right（隔离线 L-jog 横移段 → Δ2）", "material": "metal",
             "start_mm": [min(xa, xb) - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [max(xa, xb) + wf / 2, yj + wf / 2, ZM]},
            {"name": "gysel_bridge_top（50Ω λ/2 桥带，跨度 2·iso_len）",
             "material": "metal",
             "start_mm": [-xb - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [xb + wf / 2, yj + wf / 2, ZM]},
            # 馈线段由 MSLPort 自画（同宽），预览补画仅供显示
            {"name": "feed_p1", "material": "metal",
             "start_mm": [-wf / 2, -60.0, ZM], "stop_mm": [wf / 2, -wa / 2, ZM]},
            {"name": "feed_p2", "material": "metal",
             "start_mm": [-xa - wf / 2, -60.0, ZM],
             "stop_mm": [-xa + wf / 2, -wa / 2, ZM]},
            {"name": "feed_p3", "material": "metal",
             "start_mm": [xa - wf / 2, -60.0, ZM],
             "stop_mm": [xa + wf / 2, -wa / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出1）", "pos_mm": [-xa, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port3（输出2）", "pos_mm": [xa, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
        elements = [
            {"name": "iso_load1", "kind": "lumped_r", "r_ohm": 50.0,
             "pos_mm": [-xb, yj]},
            {"name": "iso_load2", "kind": "lumped_r", "r_ohm": 50.0,
             "pos_mm": [xb, yj]},
        ]
    elif template == "hairpin":
        # 发夹线 BPF（WP2.3 Tier1 附加模板）：N 个 U 形 λg/2 谐振器 + 抽头馈线。
        # 几何统一由 _hairpin_layout 计算（render_script/_near_points/此处共用）。
        lay = _hairpin_layout(params)
        wm = lay["wf"] * 1e3
        y0m, y1m = lay["y0"] * 1e3, lay["y1"] * 1e3
        ytm = lay["y_tap"] * 1e3
        xs_mm = [v * 1e3 for v in lay["xs"]]
        for _i in range(lay["n"]):
            _xl, _xr = xs_mm[2 * _i], xs_mm[2 * _i + 1]
            boxes += [
                {"name": f"hairpin_r{_i + 1}_arm_l", "material": "metal",
                 "start_mm": [_xl - wm / 2, y0m, ZM],
                 "stop_mm": [_xl + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_arm_r", "material": "metal",
                 "start_mm": [_xr - wm / 2, y0m, ZM],
                 "stop_mm": [_xr + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_bend", "material": "metal",
                 "start_mm": [_xl - wm / 2, y1m - wm / 2, ZM],
                 "stop_mm": [_xr + wm / 2, y1m + wm / 2, ZM]},
            ]
        boxes += [
            {"name": "feed_in_tap", "material": "metal",
             "start_mm": [-60.0, ytm - wm / 2, ZM],
             "stop_mm": [xs_mm[0], ytm + wm / 2, ZM]},
            {"name": "feed_out_tap", "material": "metal",
             "start_mm": [xs_mm[-1], ytm - wm / 2, ZM],
             "stop_mm": [60.0, ytm + wm / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，抽头）",
             "pos_mm": [-60.0, ytm, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（输出，抽头）",
             "pos_mm": [60.0, ytm, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "varactor_bpf":
        # 变容管调谐 BPF（M-5）：hairpin 同族盒清单（几何单源 _hairpin_layout）
        # + 每 U 左臂开路端变容管装载盒进 elements（lumped_c，c_pf=C 字面量
        # C(V)−C_geo 与渲染逐位同源（#252 族扣除，P2）；几何签名与 hairpin
        # 逐盒同构，C 值不进导体——审计 LUMPED_VALUE_PARAMS）
        from rfauto.core.varactor import (
            abrupt_junction_capacitance_pf,
            varactor_box_geo_capacitance_pf,
        )

        lay = _hairpin_layout(params)
        sub = substrate or _DEFAULT_SUB
        wm = lay["wf"] * 1e3
        y0m, y1m = lay["y0"] * 1e3, lay["y1"] * 1e3
        ytm = lay["y_tap"] * 1e3
        yt_out = lay["y_tap_out"] * 1e3
        xs_mm = [v * 1e3 for v in lay["xs"]]
        for _i in range(lay["n"]):
            _xl, _xr = xs_mm[2 * _i], xs_mm[2 * _i + 1]
            boxes += [
                {"name": f"varactor_bpf_r{_i + 1}_arm_l", "material": "metal",
                 "start_mm": [_xl - wm / 2, y0m, ZM],
                 "stop_mm": [_xl + wm / 2, y1m, ZM]},
                {"name": f"varactor_bpf_r{_i + 1}_arm_r", "material": "metal",
                 "start_mm": [_xr - wm / 2, y0m, ZM],
                 "stop_mm": [_xr + wm / 2, y1m, ZM]},
                {"name": f"varactor_bpf_r{_i + 1}_bend", "material": "metal",
                 "start_mm": [_xl - wm / 2, y1m - wm / 2, ZM],
                 "stop_mm": [_xr + wm / 2, y1m + wm / 2, ZM]},
            ]
        boxes += [
            {"name": "feed_in_tap", "material": "metal",
             "start_mm": [-60.0, ytm - wm / 2, ZM],
             "stop_mm": [xs_mm[0], ytm + wm / 2, ZM]},
            {"name": "feed_out_tap", "material": "metal",
             "start_mm": [xs_mm[-1], yt_out - wm / 2, ZM],
             "stop_mm": [60.0, yt_out + wm / 2, ZM]},
        ]
        cj0_pf = float(params.get("cj0_pf", VARACTOR_BPF_NOMINAL["cj0_pf"]))
        phi_v = float(params.get("phi_v", VARACTOR_BPF_NOMINAL["phi_v"]))
        bias_v = float(params.get("bias_v", VARACTOR_BPF_NOMINAL["bias_v"]))
        _c_design_pf = abrupt_junction_capacitance_pf(bias_v, cj0_pf, phi_v)
        _c_pf = (_c_design_pf
                 - varactor_box_geo_capacitance_pf(
                     wm, float(sub["h_mm"]), float(sub["er"])))
        elements = [{"name": f"varactor_c{_k}", "kind": "lumped_c",
                     "c_pf": _c_pf,
                     "pos_mm": [xs_mm[2 * (_k - 1)],
                                y0m + wm / 2]}
                    for _k in range(1, lay["n"] + 1)]
        ports = [
            {"name": "Port1（输入，抽头）",
             "pos_mm": [-60.0, ytm, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（输出，抽头）",
             "pos_mm": [60.0, yt_out, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "hairpin_alt":
        # 交替取向发夹线 BPF（2026-09-18 w2g，0dk 根修）：奇数序谐振器上下翻转
        # （弯带 y 逐腔轮替 YBEND[i]、开路端互补），输出抽头随末腔取向自其开路端计。
        # 几何单源 _hairpin_alt_layout（render/_near_points/此处共用，#212）。
        lay = _hairpin_alt_layout(params)
        wm = lay["wf"] * 1e3
        y0m, y1m = lay["y0"] * 1e3, lay["y1"] * 1e3
        yb_mm = [v * 1e3 for v in lay["y_bend"]]
        yt_in, yt_out = lay["y_taps"][0] * 1e3, lay["y_taps"][1] * 1e3
        xs_mm = [v * 1e3 for v in lay["xs"]]
        for _i in range(lay["n"]):
            _xl, _xr = xs_mm[2 * _i], xs_mm[2 * _i + 1]
            boxes += [
                {"name": f"hairpin_r{_i + 1}_arm_l", "material": "metal",
                 "start_mm": [_xl - wm / 2, y0m, ZM],
                 "stop_mm": [_xl + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_arm_r", "material": "metal",
                 "start_mm": [_xr - wm / 2, y0m, ZM],
                 "stop_mm": [_xr + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_bend", "material": "metal",
                 "start_mm": [_xl - wm / 2, yb_mm[_i] - wm / 2, ZM],
                 "stop_mm": [_xr + wm / 2, yb_mm[_i] + wm / 2, ZM]},
            ]
        boxes += [
            {"name": "feed_in_tap", "material": "metal",
             "start_mm": [-60.0, yt_in - wm / 2, ZM],
             "stop_mm": [xs_mm[0], yt_in + wm / 2, ZM]},
            {"name": "feed_out_tap", "material": "metal",
             "start_mm": [xs_mm[-1], yt_out - wm / 2, ZM],
             "stop_mm": [60.0, yt_out + wm / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，抽头）",
             "pos_mm": [-60.0, yt_in, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（输出，抽头）",
             "pos_mm": [60.0, yt_out, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "coupled_bpf":
        # 平行耦合 BPF：盒清单由 _coupled_bpf_layout 统一给出（防两处漂移）
        lay = _coupled_bpf_layout(params)
        for _i, (_bx0, _by0, _bx1, _by1) in enumerate(lay["boxes"]):
            boxes.append({"name": lay["box_names"][_i], "material": "metal",
                          "start_mm": [_bx0 * 1e3, _by0 * 1e3, ZM],
                          "stop_mm": [_bx1 * 1e3, _by1 * 1e3, ZM]})
        ports = [
            {"name": "Port1（输入 50Ω 馈）",
             "pos_mm": [lay["xs"][0] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出 50Ω 馈）",
             "pos_mm": [lay["xs"][-1] * 1e3, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "msl_cpw":
        # MSL↔CPWG 过渡（WP2.5，与 _msl_cpw_lines 同几何口径，mm 单位）
        wm = float(params.get("w_msl_mm", _nominal_width.W50_MM))
        wc = float(params.get("w_cpw_mm", 0.849))
        gp = float(params.get("gap_cpw_mm", 0.2))
        length = float(params.get("line_len_mm", 40.0))
        trans = float(params.get("trans_len_mm", 10.0))
        y0, ym, yt, y1 = -length / 2, -trans / 2, trans / 2, length / 2
        boxes += [
            {"name": "msl_section", "material": "metal",
             "start_mm": [-wm / 2, y0, ZM], "stop_mm": [wm / 2, ym, ZM]},
            {"name": "taper（阶梯渐变）", "material": "metal",
             "start_mm": [-wm / 2, ym, ZM], "stop_mm": [wm / 2, yt, ZM]},
            {"name": "cpw_center", "material": "metal",
             "start_mm": [-wc / 2, yt, ZM], "stop_mm": [wc / 2, y1, ZM]},
            {"name": "cpw_gnd_left", "material": "metal",
             "start_mm": [-60.0, yt, ZM], "stop_mm": [-(wc / 2 + gp), 60.0, ZM]},
            {"name": "cpw_gnd_right", "material": "metal",
             "start_mm": [wc / 2 + gp, yt, ZM], "stop_mm": [60.0, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（MSL 侧）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（CPWG 侧）", "pos_mm": [0.0, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "sma_launcher":
        # SMA 边缘弹射（夹具口径，几何单源 sma_launcher_layout，预览按 0.4mm
        # 收敛档 base 定 port1 面；mm 单位）：基板/地随 PCB 抬高 Z_G 重写
        lay = sma_launcher_layout(params, h * 1e-3, 0.4e-3)
        z_g, z_top, z_ax = lay["z_g"] * 1e3, lay["z_top"] * 1e3, lay["z_ax"] * 1e3
        ros, ri, ro = lay["ros"] * 1e3, lay["ri"] * 1e3, lay["ro"] * 1e3
        y_b, y_p0, y_e = lay["y_b"] * 1e3, lay["y_p0"] * 1e3, lay["y_e"] * 1e3
        y_pe, y1, wm = lay["y_pe"] * 1e3, lay["y1"] * 1e3, lay["w_m"] * 1e3
        boxes[0] = {"name": "substrate", "material": "substrate",
                    "start_mm": [-60.0, y_e, z_g], "stop_mm": [60.0, 60.0, z_top]}
        boxes[1] = {"name": "ground", "material": "metal",
                    "start_mm": [-60.0, y_e, 0.0], "stop_mm": [60.0, 60.0, z_g]}
        boxes += [
            {"name": "coax_shell（弹射壳体）", "material": "metal",
             "start_mm": [-ros, y_b, 0.0], "stop_mm": [ros, y_e, 2 * ros]},
            {"name": "body_face（连接器体前脸，孔径按优先级挖空）", "material": "metal",
             "start_mm": [-lay["f_w"] * 1e3, (lay["y_e"] - lay["f_t"]) * 1e3, 0.0],
             "stop_mm": [lay["f_w"] * 1e3, y_e, lay["f_z"] * 1e3]},
            {"name": "coax_pin（中心针）", "material": "metal",
             "start_mm": [-ri, y_b, z_ax - ri], "stop_mm": [ri, y_pe, z_ax + ri]},
            {"name": "solder（搭焊）", "material": "metal",
             "start_mm": [-wm / 2, y_e, z_top], "stop_mm": [wm / 2, y_pe, z_ax]},
            {"name": "msl_feed", "material": "metal",
             "start_mm": [-wm / 2, y_e, z_top], "stop_mm": [wm / 2, y1, z_top]},
        ]
        ports = [
            {"name": "Port1（SMA 同轴截面集总桥）",
             "pos_mm": [0.0, y_p0, z_ax + 0.5 * (ri + ro)],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（MSL 50Ω）", "pos_mm": [0.0, 60.0, z_top],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template in C3_TEMPLATES:
        # §C3 滤波器族 II：盒/过孔/电容清单由 _c3_layout 单源给出（米 → mm）；
        # 过孔柱以 2r 方盒进预览，装载电容进 elements（lumped_c）
        lay = _c3_layout(template, params)
        for (_bx0, _by0, _bx1, _by1), _nm in zip(lay["boxes"], lay["box_names"],
                                                strict=True):
            boxes.append({"name": _nm, "material": "metal",
                          "start_mm": [_bx0 * 1e3, _by0 * 1e3, ZM],
                          "stop_mm": [_bx1 * 1e3, _by1 * 1e3, ZM]})
        _rv = lay["r_via"]
        for _k, (_vx, _vy) in enumerate(lay["vias"], start=1):
            boxes.append({"name": f"via{_k}（接地过孔 r={_rv * 1e3:.2f}mm）",
                          "material": "metal",
                          "start_mm": [(_vx - _rv) * 1e3, (_vy - _rv) * 1e3, 0.0],
                          "stop_mm": [(_vx + _rv) * 1e3, (_vy + _rv) * 1e3, ZM]})
        if template == "combline":
            _c_pf = float(params.get("c_load_pf",
                                     TEMPLATE_NOMINAL["combline"]["c_load_pf"]))
            elements = [{"name": f"c_load{_k}", "kind": "lumped_c",
                         "c_pf": _c_pf,
                         "pos_mm": [0.5 * (_cx0 + _cx1) * 1e3,
                                    0.5 * (_cy0 + _cy1) * 1e3]}
                        for _k, (_cx0, _cy0, _cx1, _cy1)
                        in enumerate(lay["caps"], start=1)]
        ports = [
            {"name": "Port1（输入 50Ω 馈，缝耦合）",
             "pos_mm": [lay["xs"][0] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出 50Ω 馈，缝耦合，同边）",
             "pos_mm": [lay["xs"][-1] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
        ]
    elif template in _C4_COUPLER_TEMPLATES:
        # §C4 耦合器族 II：盒/端口清单由 _c4_layout 单源给出（米 → mm）。
        # lange 的 air-bridge（抬高薄金属 + 竖直立柱）作为独立盒进预览，
        # 让 3D 预览与 #212 连通性审计看到同一份几何。
        lay = _c4_layout(template, params)
        for (_nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": _nm, "material": "metal",
                          "start_mm": [_x0 * 1e3, _y0 * 1e3, _z0 * 1e3],
                          "stop_mm": [_x1 * 1e3, _y1 * 1e3, _z1 * 1e3]})
        for _pt in lay["ports"]:
            _s = _pt["start"]
            _ax = 0 if _pt["prop_dir"] == "x" else 1
            _sign = -1.0 if _s[_ax] < 0.0 else 1.0
            _dir = [0.0, 0.0, 0.0]
            _dir[_ax] = _sign
            _pos = [(_pt["start"][0] + _pt["stop"][0]) / 2.0 * 1e3,
                    (_pt["start"][1] + _pt["stop"][1]) / 2.0 * 1e3, ZM]
            _pos[_ax] = _s[_ax] * 1e3
            ports.append({"name": f"Port{_pt['nr']}（{_pt['label']}）",
                          "pos_mm": _pos, "dir": _dir})
    elif template in ANTENNA2_TEMPLATES:
        # §10.3 C1 天线族 II：盒/端口清单由 _ant2_layout 单源给出（mm）。
        # monopole/helix 无介质板（像理论口径）→ 去掉默认基板盒；slot 地面为
        # 有限留槽金属板（布局自带 4 盒）→ 去掉默认整板地盒；loop 自由空间
        # （无板无地，2026-09-16）→ 两盒都去（布局 substrate/ground 标志单源）。
        lay = _ant2_layout(template, params, substrate)
        if not lay["substrate"]:
            boxes = [b for b in boxes if b["name"] != "substrate"]
        if not lay["ground"]:
            boxes = [b for b in boxes if b["name"] != "ground"]
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        _axis_index = {"x": 0, "y": 1, "z": 2}
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            if _pt["kind"] == "lumped":
                _dir = [0.0, 0.0, 0.0]
                _dir[_axis_index[_pt["exc_dir"]]] = 1.0
                ports.append({
                    "name": f"Port{_nr}（LumpedPort 集总馈口，E 沿 {_pt['exc_dir']}）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                               (_s[2] + _t[2]) / 2.0],
                    "dir": _dir})
            else:
                _ax = _axis_index[_pt["prop_dir"]]
                _sign = -1.0 if _s[_ax] < _t[_ax] else 1.0
                _dir = [0.0, 0.0, 0.0]
                _dir[_ax] = _sign
                ports.append({
                    "name": f"Port{_nr}（MSLPort 50Ω 馈）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0 if _ax != 0 else _s[0],
                               (_s[1] + _t[1]) / 2.0 if _ax != 1 else _s[1],
                               ZM],
                    "dir": _dir})
    elif template in ARRAY_TEMPLATES:
        # §10.3 C2 阵列族：盒/端口/单元中心由 _arr_layout 单源给出（mm）；接地
        # 贴片阵 → 默认基板盒与整板地盒均保留
        lay = _arr_layout(template, params, substrate)
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            if _pt["kind"] == "lumped":
                ports.append({
                    "name": f"Port{_nr}（LumpedPort 底探针 50Ω，E 沿 z）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                               (_s[2] + _t[2]) / 2.0],
                    "dir": [0.0, 0.0, 1.0]})
            else:
                ports.append({
                    "name": f"Port{_nr}（MSLPort 50Ω 馈）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, _s[1], ZM],
                    "dir": [0.0, -1.0 if _s[1] < _t[1] else 1.0, 0.0]})
        elements = [{"name": f"elem{_i}", "kind": "patch_element",
                     "center_mm": [float(_cx), float(_cy)]}
                    for _i, (_cx, _cy) in enumerate(lay["elements_mm"])]
    elif template in EEP_TEMPLATES:
        # §DP-4 P3 EEP 阵列族：盒/端口/单元中心由 _eep_layout 单源给出（mm）；
        # 接地贴片阵 → 默认基板盒与整板地盒均保留；端口次序=行主序契约
        lay = _eep_layout(template, params, substrate)
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            ports.append({
                "name": f"Port{_nr}（EEP 底探针 50Ω，E 沿 z）",
                "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                           (_s[2] + _t[2]) / 2.0],
                "dir": [0.0, 0.0, 1.0]})
        elements = [{"name": f"elem{_i}", "kind": "patch_element",
                     "center_mm": [float(_cx), float(_cy)]}
                    for _i, (_cx, _cy) in enumerate(lay["elements_mm"])]
    elif template == "siw":
        # SIW 族首族：矩形域（layout 单源，审计档 0.4mm base 口径）；过孔藩篱
        # 预览按列条带绘制（每孔小盒 ×77×2 过密，UI 只需拓扑示意）
        lay = siw_layout(params, (9.75, 10.25), 0.4e-3,
                         float(params.get("h_mm", h)) * 1e-3)
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "plate_bottom", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3, 0.0]},
            {"name": "plate_top", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "via_fence_left", "material": "metal",
             "start_mm": [(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
            {"name": "via_fence_right", "material": "metal",
             "start_mm": [-(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [-(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
        ]
        ports = [
            {"name": "Port1（LumpedPort z 桥，R=Z_PV 闭式）",
             "pos_mm": [0.0, lay["y1"] * 1e3, lay["h"] * 1e3 / 2.0],
             "dir": [0.0, 0.0, 1.0]},
            {"name": "Port2（LumpedPort z 桥，R=Z_PV 闭式）",
             "pos_mm": [0.0, lay["y2"] * 1e3, lay["h"] * 1e3 / 2.0],
             "dir": [0.0, 0.0, 1.0]},
        ]
    elif template == "msl_siw_taper":
        # SIW 族第二成员：矩形域（layout 单源，审计档 0.4mm base 口径）；
        # 锥形段以包络盒示意（UI 拓扑预览）
        lay = msl_siw_taper_layout(params, (9.75, 10.25), 0.4e-3,
                                   float(params.get("h_mm", h)) * 1e-3)
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "plate_bottom", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["y_plate"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["y_plate"] * 1e3, 0.0]},
            {"name": "plate_top_siw", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["y_plate"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["dom_x"] * 1e3, lay["y_plate"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "feed_p1（50Ω MSL）", "material": "metal",
             "start_mm": [-lay["w50"] / 2 * 1e3, -lay["dom_y"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w50"] / 2 * 1e3, -lay["y_feed_in"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "feed_p2（50Ω MSL）", "material": "metal",
             "start_mm": [-lay["w50"] / 2 * 1e3, lay["y_feed_in"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w50"] / 2 * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "taper_p1（线性锥 w50→w_end 包络）", "material": "metal",
             "start_mm": [-lay["w_end"] / 2 * 1e3, -lay["y_feed_in"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w_end"] / 2 * 1e3, -lay["y_plate"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "taper_p2（线性锥 w50→w_end 包络）", "material": "metal",
             "start_mm": [-lay["w_end"] / 2 * 1e3, lay["y_plate"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w_end"] / 2 * 1e3, lay["y_feed_in"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "via_fence_left", "material": "metal",
             "start_mm": [(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
            {"name": "via_fence_right", "material": "metal",
             "start_mm": [-(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [-(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
        ]
        ports = [
            {"name": "Port1（MSLPort 50Ω 馈，线基）",
             "pos_mm": [0.0, -lay["dom_y"] * 1e3, lay["h"] * 1e3],
             "dir": [0.0, 1.0, 0.0]},
            {"name": "Port2（MSLPort 50Ω 馈，线基）",
             "pos_mm": [0.0, lay["dom_y"] * 1e3, lay["h"] * 1e3],
             "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "ring_resonator":
        # §F-A M3 环形谐振器预览：环带以 4 条基点直带近似（UI 预览口径，
        # 精确环带=渲染端逐行栅格化）；端口数与 meta n_ports 一致（审计钉）
        w = float(params.get("w_mm", _nominal_width.W50_MM))
        fw = float(params.get("feed_w_mm", _nominal_width.W50_MM))
        gap = float(params.get("gap_mm", 0.4))
        rm = float(params.get("r_mean_mm", 11.299802692199101))
        r_out = rm + w / 2
        r_in = rm - w / 2
        c45 = rm * 0.5 ** 0.5   # 45° 弦半宽（基点直带端头）
        y_end = r_out + gap
        boxes += [
            {"name": "ring_top", "material": "metal",
             "start_mm": [-c45, r_in, ZM], "stop_mm": [c45, r_out, ZM]},
            {"name": "ring_bottom", "material": "metal",
             "start_mm": [-c45, -r_out, ZM], "stop_mm": [c45, -r_in, ZM]},
            {"name": "ring_left", "material": "metal",
             "start_mm": [-r_out, -c45, ZM], "stop_mm": [-r_in, c45, ZM]},
            {"name": "ring_right", "material": "metal",
             "start_mm": [r_in, -c45, ZM], "stop_mm": [r_out, c45, ZM]},
            # 馈线段（MSLPort 同宽重叠自画，预览补画仅供显示）
            {"name": "feed_in", "material": "metal",
             "start_mm": [-fw / 2, -60.0, ZM], "stop_mm": [fw / 2, -y_end, ZM]},
            {"name": "feed_out", "material": "metal",
             "start_mm": [-fw / 2, y_end, ZM], "stop_mm": [fw / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，间隙耦合）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出，间隙耦合）", "pos_mm": [0.0, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "schiffman":
        # TA-1 Schiffman 移相器预览：耦合段 C-section（双带条+桥带）+ 参考段；
        # 端口数与 meta n_ports 一致（审计钉）
        from .render_phase_qwt import _schiffman_layout

        lay = _schiffman_layout(dict(params))
        gx = lay["gap"] * 1e3
        w = lay["w"] * 1e3
        y0 = lay["y0"] * 1e3
        y1 = lay["y1"] * 1e3
        xr = lay["xr"] * 1e3
        wr = lay["wr"] * 1e3
        lr = lay["lr"] * 1e3
        boxes += [
            {"name": "coupled_line_a", "material": "metal",
             "start_mm": [-gx - w, y0, ZM], "stop_mm": [-gx, y1, ZM]},
            {"name": "coupled_line_b", "material": "metal",
             "start_mm": [gx, y0, ZM], "stop_mm": [gx + w, y1, ZM]},
            {"name": "bridge（远端桥带）", "material": "metal",
             "start_mm": [-gx - w, y1, ZM], "stop_mm": [gx + w, y1 + w, ZM]},
            {"name": "reference_line", "material": "metal",
             "start_mm": [xr - wr / 2, -lr / 2, ZM],
             "stop_mm": [xr + wr / 2, lr / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（耦合段近端 A）", "pos_mm": [-gx - w / 2, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（耦合段近端 B）", "pos_mm": [gx + w / 2, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port3（参考段输入）", "pos_mm": [xr, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port4（参考段输出）", "pos_mm": [xr, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "qwt_multisection":
        # TA-2 多节 λ/4 变换器预览：馈线 + N 节级联 + 端接盒；端口数与
        # meta n_ports 一致（审计钉）
        from .render_phase_qwt import _qwt_layout

        lay = _qwt_layout(dict(params))
        fw = lay["fw"] * 1e3
        y0 = lay["y0"] * 1e3
        boxes += [{"name": "feed", "material": "metal",
                   "start_mm": [-fw / 2, -60.0, ZM],
                   "stop_mm": [fw / 2, y0, ZM]}]
        y_prev = y0
        for k, (wv, lv) in enumerate(zip(lay["w_list_m"], lay["l_list_m"],
                                         strict=True), start=1):
            y_next = y_prev + lv * 1e3
            boxes.append({"name": f"section_{k}", "material": "metal",
                          "start_mm": [-wv * 1e3 / 2, y_prev, ZM],
                          "stop_mm": [wv * 1e3 / 2, y_next, ZM]})
            y_prev = y_next
        elements = [{"name": "load_termination", "kind": "lumped_r",
                     "r_ohm": float(lay["zl"]), "ny": "z",
                     "span_mm": [lay["load_lo"] * 1e3,
                                 lay["y_end"] * 1e3], "y_mm": y_prev}]
        ports = [
            {"name": "Port1（输入，50Ω 馈线）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "sicl":
        # TA-3 SICL 预览：上下地板+内导体条带+过孔墙（墙按名义栅格抽样画，
        # 预览示意）+双 StripLinePort；端口数与 meta n_ports 一致（审计钉）
        from .render_sicl_nway import sicl_layout

        lay = sicl_layout(dict(params), (2.25, 2.75), 0.4e-3,
                          float(params.get("h_mm", 1.016)) * 1e-3)
        zc = float(params.get("h_mm", 1.016)) / 2.0
        boxes += [
            {"name": "plate_top", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3,
                          float(params.get("h_mm", 1.016))],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         float(params.get("h_mm", 1.016))]},
            {"name": "strip", "material": "metal",
             "start_mm": [-lay["w"] * 1e3 / 2, lay["y0"] * 1e3, zc],
             "stop_mm": [lay["w"] * 1e3 / 2, lay["y1"] * 1e3, zc]},
        ]
        for _vy in lay["via_y"][::4]:
            for _vx in (-lay["a"] / 2.0, lay["a"] / 2.0):
                boxes.append(
                    {"name": "via_wall", "material": "metal",
                     "start_mm": [_vx * 1e3, _vy * 1e3, 0.0],
                     "stop_mm": [_vx * 1e3, _vy * 1e3,
                                 float(params.get("h_mm", 1.016))]})
        ports = [
            {"name": "Port1（StripLinePort）",
             "pos_mm": [0.0, -lay["dom_y"] * 1e3, zc],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（StripLinePort）",
             "pos_mm": [0.0, lay["dom_y"] * 1e3, zc],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "nway_wilkinson":
        # TA-4 N-way 树形功分器预览：T 条/臂/支线盒清单（layout 单源）+
        # 隔离电阻 + 5 端口；端口数与 meta n_ports 一致（审计钉）
        from .render_sicl_nway import _nway_layout

        lay = _nway_layout(dict(params))
        for _nm, _x0, _y0, _x1, _y1 in lay["boxes"]:
            boxes.append({"name": _nm, "material": "metal",
                          "start_mm": [_x0 * 1e3, _y0 * 1e3, ZM],
                          "stop_mm": [_x1 * 1e3, _y1 * 1e3, ZM]})
        for _nm, _x0, _y0, _x1, _y1 in lay["res_boxes"]:
            elements.append({"name": _nm, "kind": "lumped_r",
                             "r_ohm": float(lay["iso_r"]),
                             "span_mm": [_y0 * 1e3, _y1 * 1e3],
                             "x_mm": (_x0 + _x1) * 0.5e3})
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
        ]
        for _k, _xo in enumerate(lay["out_x"], start=2):
            ports.append({"name": f"Port{_k}（输出）",
                          "pos_mm": [_xo * 1e3, 60.0, ZM],
                          "dir": [0.0, 1.0, 0.0]})
    elif template == "diplexer":
        # TA-5 Diplexer 预览（round15 TA-5）：输入馈线/双臂盒清单（layout
        # 单源）+ 一阶 CR 对集总元件 + 3 端口；端口数与 meta n_ports 一致
        # （审计钉）
        from .render_diplexer_ridged import _diplexer_layout

        lay = _diplexer_layout(dict(params))
        wf = lay["wf"] * 1e3
        xe = lay["x_e"] * 1e3
        xeg = (lay["x_e"] + lay["gap"]) * 1e3
        boxes += [
            {"name": "diplexer_feed（输入馈线）", "material": "metal",
             "start_mm": [-wf / 2, -60.0, ZM], "stop_mm": [wf / 2, 0.0, ZM]},
            {"name": "lpf_seg1", "material": "metal",
             "start_mm": [0.0, -wf / 2, ZM], "stop_mm": [xe, wf / 2, ZM]},
            {"name": "lpf_seg2", "material": "metal",
             "start_mm": [xeg, -wf / 2, ZM], "stop_mm": [60.0, wf / 2, ZM]},
            {"name": "hpf_seg1", "material": "metal",
             "start_mm": [-xe, -wf / 2, ZM], "stop_mm": [0.0, wf / 2, ZM]},
            {"name": "hpf_seg2", "material": "metal",
             "start_mm": [-60.0, -wf / 2, ZM], "stop_mm": [-xeg, wf / 2, ZM]},
        ]
        elements = [
            {"name": "lpf_l", "kind": "lumped_l", "l_nh": float(
                params.get("l_lpf_nh", 3.1831)),
             "span_mm": [xe, xeg]},
            {"name": "hpf_c", "kind": "lumped_c", "c_pf": float(
                params.get("c_hpf_pf", 1.2732)),
             "span_mm": [-xeg, -xe]},
        ]
        ports = [
            {"name": "Port1（antenna 公共口）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（LP 输出）", "pos_mm": [60.0, 0.0, ZM],
             "dir": [1.0, 0.0, 0.0]},
            {"name": "Port3（HP 输出）", "pos_mm": [-60.0, 0.0, ZM],
             "dir": [-1.0, 0.0, 0.0]},
        ]
    elif template == "inverted_ms":
        # TA-7 倒置微带预览：地面（域 PEC 底界示意）+悬浮条带+基板浮盒+双
        # MSLPort；端口数与 meta n_ports 一致（审计钉）
        w = float(params.get("w_mm", 2.1359))
        ha = float(params.get("h_air_mm", 0.508))
        ln = float(params.get("line_len_mm", 40.0))
        hs = float(params.get("h_sub_mm", 0.508))
        boxes += [
            {"name": "strip（倒置条带 z=h_air）", "material": "metal",
             "start_mm": [-w / 2, -ln / 2, ha],
             "stop_mm": [w / 2, ln / 2, ha]},
            {"name": "substrate（悬浮 [h_air, h_air+h_sub]）", "material": "substrate",
             "start_mm": [-60.0, -60.0, ha], "stop_mm": [60.0, 60.0, ha + hs]},
        ]
        ports = [
            {"name": "Port1（MSLPort 板边）", "pos_mm": [0.0, -60.0, ha],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（MSLPort 板边）", "pos_mm": [0.0, 60.0, ha],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "embedded_ms":
        # TA-11 嵌入式微带预览：地面（域 PEC 底界示意）+条带 z=H_SUB+基板/
        # 覆盖层（同 εr 单盒 [0, H_SUB+H2]）+双 MSLPort；端口数与 meta
        # n_ports 一致（审计钉）
        w = float(params.get("w_mm", 1.0014))
        h2 = float(params.get("h2_mm", 0.254))
        ln = float(params.get("line_len_mm", 40.0))
        hs = float(params.get("h_mm", 0.508))
        boxes += [
            {"name": "strip（嵌埋条带 z=H_SUB）", "material": "metal",
             "start_mm": [-w / 2, -ln / 2, hs],
             "stop_mm": [w / 2, ln / 2, hs]},
            {"name": "substrate（基板+覆盖层 [0, H_SUB+H2]）",
             "material": "substrate",
             "start_mm": [-60.0, -60.0, 0.0],
             "stop_mm": [60.0, 60.0, hs + h2]},
        ]
        ports = [
            {"name": "Port1（MSLPort 板边）", "pos_mm": [0.0, -60.0, hs],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（MSLPort 板边）", "pos_mm": [0.0, 60.0, hs],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "xcheb_bpf4":
        # TA-14 交叉耦合开路环四重奏预览：四环盒+双抽头馈线+双 MSLPort；
        # 几何单源 _xcheb_bpf4_layout（审计档 0.35mm base 过 #266 守卫）
        lay = _xcheb_bpf4_layout(dict(params), 0.35e-3)
        for _i, _b in enumerate(lay["boxes"]):
            boxes.append({"name": f"ring_box_{_i}", "material": "metal",
                          "start_mm": [_b[0] * 1e3, _b[1] * 1e3, 0.508],
                          "stop_mm": [_b[2] * 1e3, _b[3] * 1e3, 0.508]})
        for _i, _b in enumerate(lay["feeds"]):
            boxes.append({"name": f"feed_{_i}", "material": "metal",
                          "start_mm": [_b[0] * 1e3, _b[1] * 1e3, 0.508],
                          "stop_mm": [_b[2] * 1e3, _b[3] * 1e3, 0.508]})
        ports = [
            {"name": "Port1（MSLPort 板边，环 1 抽头）",
             "pos_mm": [-60.0, lay["y_taps"][0] * 1e3, 0.508],
             "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（MSLPort 板边，环 4 抽头）",
             "pos_mm": [-60.0, lay["y_taps"][1] * 1e3, 0.508],
             "dir": [-1.0, 0.0, 0.0]},
        ]
    elif template == "hmsiw":
        # TA-8 HM-SIW 预览：底板+基板+单列过孔藩篱（按名义栅格抽样画，示意）
        # +两端面 LumpedPort；端口数与 meta n_ports 一致（审计钉）
        from .render_ta_wave_a import hmsiw_layout

        lay = hmsiw_layout(dict(params), (9.75, 10.25), 0.4e-3,
                           float(params.get("h_mm", 0.508)) * 1e-3)
        h = float(params.get("h_mm", 0.508))
        boxes += [
            {"name": "substrate（矩形域）", "material": "substrate",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3, h]},
            {"name": "plate_bottom", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3, 0.0]},
        ]
        for _vy in lay["via_y"][::4]:
            boxes.append(
                {"name": "via_wall", "material": "metal",
                 "start_mm": [lay["w"] * 1e3 / 2, _vy * 1e3, 0.0],
                 "stop_mm": [lay["w"] * 1e3 / 2, _vy * 1e3, h]})
        ports = [
            {"name": "Port1（LumpedPort 端面）",
             "pos_mm": [0.0, lay["y1"] * 1e3, h / 2],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（LumpedPort 端面）",
             "pos_mm": [0.0, lay["y2"] * 1e3, h / 2],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "fgcpw":
        # TA-9 FGCPW 预览：中心条带+两有限宽地（全长度）+双 CPWPort；端口数
        # 与 meta n_ports 一致（审计钉）
        w = float(params.get("w_mm", 4.3466))
        gap = float(params.get("gap_mm", 0.2))
        gnd = float(params.get("gnd_mm", 4.0))
        ln = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "strip", "material": "metal",
             "start_mm": [-w / 2, -ln / 2, ZM], "stop_mm": [w / 2, ln / 2, ZM]},
            {"name": "ground_left", "material": "metal",
             "start_mm": [-(w / 2 + gap + gnd), -ln / 2, ZM],
             "stop_mm": [-(w / 2 + gap), ln / 2, ZM]},
            {"name": "ground_right", "material": "metal",
             "start_mm": [w / 2 + gap, -ln / 2, ZM],
             "stop_mm": [w / 2 + gap + gnd, ln / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（CPWPort 板边）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（CPWPort 板边）", "pos_mm": [0.0, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "isl_shielded":
        # TA-10 ISL 预览（ge8b WB 席 B9）：悬浮基板+条带+顶板+两列藩篱
        # +双 MSLPort；端口数与 meta n_ports 一致（审计钉）
        from .render_ta_wave_b import isl_layout

        lay = isl_layout(dict(params), 0.4e-3,
                         float(substrate["h_mm"]) * 1e-3)
        boxes += [
            {"name": "strip（ISL 条带 z=g+h）", "material": "metal",
             "start_mm": [-lay["w"] * 1e3 / 2, -lay["line_len"] * 1e3 / 2,
                          lay["z_strip"] * 1e3],
             "stop_mm": [lay["w"] * 1e3 / 2, lay["line_len"] * 1e3 / 2,
                         lay["z_strip"] * 1e3]},
            {"name": "wall（屏蔽顶板）", "material": "metal",
             "start_mm": [-(lay["wall_x"] + lay["d"] / 2) * 1e3,
                          -lay["line_len"] * 1e3 / 2, lay["z_wall"] * 1e3],
             "stop_mm": [(lay["wall_x"] + lay["d"] / 2) * 1e3,
                         lay["line_len"] * 1e3 / 2, lay["z_wall"] * 1e3]},
            {"name": "substrate（悬浮 [g, g+h_sub]）", "material": "substrate",
             "start_mm": [-60.0, -60.0, lay["g"] * 1e3],
             "stop_mm": [60.0, 60.0, lay["z_strip"] * 1e3]},
        ]
        for _vy in lay["via_y"][::4]:
            for _sx in (-lay["wall_x"], lay["wall_x"]):
                boxes.append(
                    {"name": "via_wall", "material": "metal",
                     "start_mm": [_sx * 1e3, _vy * 1e3, 0.0],
                     "stop_mm": [_sx * 1e3, _vy * 1e3, lay["z_wall"] * 1e3]})
        ports = [
            {"name": "Port1（MSLPort 板边）", "pos_mm": [0.0, -60.0,
                                                        lay["z_strip"] * 1e3],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（MSLPort 板边）", "pos_mm": [0.0, 60.0,
                                                        lay["z_strip"] * 1e3],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "vivaldi_tsa":
        # AP-11 Vivaldi 预览（ge8b WB 席 B9）：阶梯化地面+跨槽馈线+双
        # MSLPort；端口数与 meta n_ports 一致（审计钉）
        from .render_ta_wave_b import vivaldi_layout

        lay = vivaldi_layout(dict(params))
        stations = list(zip(lay["stations_y"][:-1], lay["stations_y"][1:],
                            lay["stations_hw"][:-1], strict=True))
        for _ya, _yb, _hw in stations:
            boxes.append(
                {"name": "gnd_stair_L", "material": "metal",
                 "start_mm": [-60.0, _ya, 0.0], "stop_mm": [-_hw, _yb, 0.0]})
            boxes.append(
                {"name": "gnd_stair_R", "material": "metal",
                 "start_mm": [_hw, _ya, 0.0], "stop_mm": [60.0, _yb, 0.0]})
        boxes.append(
            {"name": "gnd_tail（口面外地）", "material": "metal",
             "start_mm": [-60.0, lay["y_mouth"], 0.0],
             "stop_mm": [60.0, 60.0, 0.0]})
        boxes.append(
            {"name": "feed（跨槽微带）", "material": "metal",
             "start_mm": [-60.0, lay["y_feed"] - lay["feed_w"] / 2, ZM],
             "stop_mm": [60.0, lay["y_feed"] + lay["feed_w"] / 2, ZM]})
        ports = [
            {"name": "Port1（MSLPort 板边 x-）",
             "pos_mm": [-60.0, lay["y_feed"], ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（MSLPort 板边 x+）",
             "pos_mm": [60.0, lay["y_feed"], ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    else:  # patch (default fallback)
        pl = float(params.get("patch_len_mm", 34.9))
        pw = float(params.get("patch_w_mm", 50.0))
        off = float(params.get("feed_offset_mm", 5.5))
        boxes += [
            {"name": "patch", "material": "metal",
             "start_mm": [-pl / 2, -pw / 2, ZM], "stop_mm": [pl / 2, pw / 2, ZM]},
            # 底馈探针（官方口径：x=-feed_offset，y 向 2mm、x 向 0.2mm、z 跨基板）
            {"name": "feed_probe", "material": "metal",
             "start_mm": [-off - 0.1, -1.0, 0.0], "stop_mm": [-off + 0.1, 1.0, h]},
        ]
        ports = [
            {"name": "Port1（底馈探针 50Ω）",
             "pos_mm": [-off, 0.0, 0.0], "dir": [0.0, 0.0, 1.0]},
        ]
        elements = [{"name": "feed_port", "kind": "lumped_port", "r_ohm": 50.0,
                     "feed_offset_mm": off}]

    return {"template": template, "substrate": substrate, "boxes": boxes, "ports": ports,
            "elements": elements}


def _debye_pole_fit(
    er: float,
    tan_d: float,
    freq_range_ghz: tuple[float, float],
    n_poles: int = 2,
) -> tuple[float, float, list[float]]:
    """等 Δε Debye 极点对平坦 tanD 目标的最小二乘拟合（EC-12，2026-10-05）。

    官方 MSL_Debye_Substrate 例（openEMS 上游 2026-10-02 commit 6761a36，
    ``fit_poles`` 逐式对抄，禁止凭想象写 API 同律 #215）：

    - 弛豫频率在 ``[f_lo, 2·f_hi]``（激励带 GHz → Hz）对数均布——官方
      medium 档口径（1..5 GHz 带 → 1..10 GHz 弛豫）；
    - 检查网格 = 激励带 60 点对数均布（官方 ``f_band`` 口径）；
    - 设计矩阵 ``[1, Σ1/(1+(ωτ)²)]``/``[0, Σωτ/(1+(ωτ)²)]`` 对平坦目标
      ``(er, er·tan_d)`` 最小二乘 → ``(eps_inf, eps_delta)``。

    确定性内核（规则 7）：同入参逐位同输出；LLM/配方层只传 typed 键。

    Returns
    -------
    tuple[float, float, list[float]]
        ``(eps_inf, eps_delta, tau_s)``——CSPropDebyeMaterial 三参数组
        （``epsilon=eps_inf``，逐极点 ``eps_delta``/``eps_relax`` 秒）。
    """
    import numpy as np

    f_lo_hz = float(freq_range_ghz[0]) * 1e9
    f_hi_hz = float(freq_range_ghz[1]) * 1e9
    if not (f_hi_hz > f_lo_hz > 0):
        raise ValueError(
            f"debye 拟合需要正频带，得到 {freq_range_ghz!r}")
    # 官方 medium 档：弛豫跨 [f_lo, 2·f_hi]（1..5GHz 带对 1..10GHz 弛豫）
    tau = 1.0 / (2.0 * np.pi * np.logspace(
        np.log10(f_lo_hz), np.log10(2.0 * f_hi_hz), int(n_poles)))
    w = 2.0 * np.pi * np.logspace(np.log10(f_lo_hz), np.log10(f_hi_hz), 60)
    a_re = np.column_stack(
        [np.ones_like(w), sum(1 / (1 + (w * t) ** 2) for t in tau)])
    a_im = np.column_stack(
        [np.zeros_like(w), sum(w * t / (1 + (w * t) ** 2) for t in tau)])
    a = np.vstack([a_re, a_im])
    b = np.concatenate([np.full_like(w, float(er)),
                        np.full_like(w, float(er) * float(tan_d))])
    eps_inf, d_eps = np.linalg.lstsq(a, b, rcond=None)[0]
    # 拟合质量守卫（审查 P2-2，2026-10-05）：坏拟合静默渲染=错误基底固化
    # （#1b 家法）——残差相对目标量级超门即 fail-loud 带诊断（极点数不足/
    # 频带病态时加 poles 或收带，禁静默出卡）。
    resid = a @ np.array([eps_inf, d_eps]) - b
    rel = float(np.linalg.norm(resid) / np.linalg.norm(b))
    if rel > 0.05:
        raise ValueError(
            "debye 极点拟合质量门 FAIL："
            f"相对残差 {rel:.3g} > 0.05（er={er} tan_d={tan_d} "
            f"带 {freq_range_ghz} poles={n_poles}）——坏拟合禁静默渲染，"
            "处置=增 n_poles 或收窄频带")
    return float(eps_inf), float(d_eps), [float(t) for t in tau]


def render_script(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    far_field: bool = False,
    sar: bool = False,
) -> str:
    """Render template to CSXCAD script text（官方方法学基线）。

    excite_port：主激励端口号（1 基）。多端口模板的整 S 矩阵由适配器层
    按 excite_port=1..N 渲染 N 份脚本、进程隔离各跑一次后装配（#208
    pt3/pt4 教训：进程内跨 Run 复用 CSX/端口包装器踩绑定对象生命周期
    雷——Run(cleanup=True) 会销毁激励属性乃至 CSX 本体）。

    far_field（WP4.1/D4）：辐射模板（patch/dipole）注入官方 nf2ff 盒
    （CreateNF2FFBox，域缩 4×网格，Simple Patch Antenna 教程口径）；
    run 后 CalcNF2FF 落盘 farfield_cut.csv / farfield3d.csv /
    farfield_meta.json（方向图/Dmax/效率 η=Prad/P_acc）。nf2ff 依赖
    dump 面输出，注入时 Run 不再传 disable_dumps=True。
    sar：仅 dipole（官方 Dipole SAR 教程口径）——组织等效模型盒
    （皮肤层文献值 εr=50/κ=0.65/ρ=1100）+ DumpType 29 原始 SAR dump +
    SAR_Calculation(mass=1g, IEEE_62704) → sar.csv。
    """
    params = dict(params)
    # excite_port 校验（TA 批 nway_wilkinson 起 meta n_ports 感知：越域显式
    # 拒绝保持既有契约——test_coax_wg test_render_rejects_far_field_and_bad_port
    # 钉 excite_port 越域 ValueError；轮转模板 1..n_ports 内合法）
    _ep_max = int(TEMPLATE_META.get(template, {}).get("n_ports", 4) or 4)
    _ep_req = int(excite_port)
    if _ep_req < 1 or _ep_req > _ep_max:
        raise ValueError(
            f"excite_port={_ep_req} 越域（{template} n_ports={_ep_max}，"
            f"合法 1..{_ep_max}）")
    params["_excite_port"] = _ep_req
    # F-D NrTS/EndCriteria 缺省接线（wf:nrts-fix）：PORTLESS 早分发模板不在此
    # 判定（ms_array_render 自调 _fd_nrts_defaults，避免同一 params 双重判定）
    _fd_max_time_ns = (
        None if template in PORTLESS_TEMPLATES
        else _fd_nrts_defaults(template, params))
    # rm-oe-c9 合规网格/步数旋钮（真机复跑消费；缺省=旧口径逐字节不变）：
    #   _near_ratio → NEAR = base/_near_ratio（缺省 4=官方 base/4；SSL 复跑 10
    #                 使 NEAR=0.114mm ≤ w/6=0.1218mm）
    #   _sub_cells  → 基板 z 向格数（G3 2026-09-22 缺省分档：CPW/槽下场族
    #                 msl_cpw/cpw 缺省 8——zconv 定案 GRID_UNDERRES+SATURATED_
    #                 RESIDUAL（runs/msl_cpw_zconv，网格份额 78%，sub8 回 ±2%
    #                 锚门内；_SUB_CELLS_8_TEMPLATES 见模块头）；其余模板缺省
    #                 4=官方 substrate_cells=4 旧口径逐字节不变；#313 z 向
    #                 地板项；微带/lange 等 z 块同消费，SSL/CPS 各自点数换算
    #                 见 _sub_half_pts/_cps_sub_pts。显式传参仍最高优先）
    #   _nrts       → FDTD 步数上限（缺省 100000 官方口径；细网格 dt 减半后
    #                 抬到 150000 防 NrTS 触顶误判未收敛，#266/#268）
    _knob_near_ratio = float(params.get("_near_ratio", 4) or 4)
    _knob_sub_cells_default = (
        8 if template in _SUB_CELLS_8_TEMPLATES else _SUB_CELLS_DEFAULT)
    _knob_sub_cells = int(
        params.get("_sub_cells", _knob_sub_cells_default)
        or _knob_sub_cells_default)
    _nrts = int(params.get("_nrts", 100000) or 100000)
    #   _end_criteria → 显式 EndCriteria（如 1e-8=−80dB；cps_xrefine addendum：
    #                 缺省 −60dB 能量判据在长脉冲激励末 ~95% 处提前自停，
    #                 port_ut 时窗不覆盖激励全程触发 V1 截断门，runs/cps_xrefine/
    #                 run1 实证）——缺省 None 不加参逐字节不变（官方口径）
    _knob_end_criteria = params.get("_end_criteria")
    _end_criteria_repr = (
        repr(float(_knob_end_criteria)) if _knob_end_criteria else None)
    _end_criteria_src = (
        f", EndCriteria={_end_criteria_repr}" if _end_criteria_repr else "")
    #   _x_refine   → cps 缝区 x 向加密对照（wf:cps-xrefine；缺省 0=逐字节
    #                 不变）：N>0 把缝 [−gap/2, gap/2] 等分 2N 格、内部线精确
    #                 入网（#311 缝中点精确入网法推广；SmoothMeshLines 不细分
    #                 <NEAR 区间——显式 AddLine 恒保留）。单变量对照旋钮：
    #                 只动 x 缝区线，y/z/BASE/激励/NrTS/提取链逐项不变。
    _knob_x_refine = int(params.get("_x_refine", 0) or 0)
    #   _board_mm   → 板边半宽覆盖（wf:varactor-locate 囚禁模定位对照；缺省
    #                 None=60mm 字面量逐字节不变）。BOARD 是共享字面量（基板盒/
    #                 抽头馈线起点/域 x-y 边界/端口面）——单变量改一处全链一致
    #                 （MeasPlaneShift 公式含 BOARD 符号自动随动）。
    #   _air_top_m  → guided 模板顶空气隙覆盖（缺省 None=5mm 逐字节不变；
    #                 z 顶 MUR 位置单变量——z 向盒模指纹对照）。
    #   _field_dump → 囚禁模定位场快照（dict，缺省 None=无 dump 块且
    #                 disable_dumps=True 逐字节不变）：{"freqs_ghz": [...],
    #                 "slabs": [{"name","z0_mm","z1_mm","sub_sample"}]}。
    #                 dump_type=10（FD E 场，CSProperties.pyx L1407 官方枚举）、
    #                 file_type=1（hdf5，L1427）、dump_mode=2（cell 插值——E 场
    #                 node 插值在金属/材料突变处假幅值，官方 docstring 警示
    #                 L1444）、sub_sampling 官方 kwargs（L1433）。FD dump 的
    #                 DFT 全 run 累积、晚窗慢振铃主导 → /FieldData/FD/f<i>
    #                 空间分布即囚禁模定位证据（读法 scripts/varactor_smoke.py
    #                 locate-judge）。
    _knob_board_m = (float(params["_board_mm"]) * 1e-3
                     if params.get("_board_mm") else None)
    _knob_air_top_m = (float(params["_air_top_m"])
                       if params.get("_air_top_m") else None)
    _knob_field_dump = params.get("_field_dump")
    substrate = substrate or _DEFAULT_SUB
    far_field = bool(far_field)
    sar = bool(sar)
    if (far_field or sar) and not _TEMPLATE_RADIATOR.get(template, False):
        raise ValueError(
            f"far_field/sar 仅支持辐射模板（patch/dipole），不支持: {template}")
    if sar and template != "dipole":
        raise ValueError("sar 仅支持 dipole（官方 Dipole SAR 教程口径）；"
                         "patch 请用 far_field")
    if template in SLOTLINE_FAMILY_TEMPLATES:
        # 槽线族：整脚本渲染器（附加模块升格正式入口，分发见文末 SLOTLINE_FAMILY 段）
        return slotline_family_render(template, params, freq_range_ghz,
                                      mesh_resolution_mm=mesh_resolution_mm,
                                      substrate=substrate,
                                      excite_port=params["_excite_port"])
    if template in PORTLESS_TEMPLATES:
        # §MS_METASURFACE 阵模板（文末 MS_METASURFACE 段）：无端口软平面
        # 照明散射体整脚本渲染器（nf2ff 散射远场；无 sparams.csv）
        return ms_array_render(template, params, freq_range_ghz,
                               mesh_resolution_mm=mesh_resolution_mm,
                               substrate=substrate)
    if template in COIL_NFC_TEMPLATES:
        # §COIL_NFC NFC 线圈（文末 COIL_NFC 段）：单端口馈隙 LumpedPort
        # 整脚本渲染器（MQS 频段几何驱动网格；中跳线桥 + 全 MUR）
        return coil_nfc_render(template, params, freq_range_ghz,
                               mesh_resolution_mm=mesh_resolution_mm,
                               substrate=substrate,
                               excite_port=params["_excite_port"])
    if template in MMWAVE_SERIES_TEMPLATES:
        # §MMWAVE_SERIES_ARRAY 行波串馈毫米波阵（文末 MMWAVE_SERIES_ARRAY 段）：
        # 单端口 MSLPort（PML_8 域边入）+ 链末匹配集总负载到地整脚本渲染器
        return mmwave_series_render(template, params, freq_range_ghz,
                                    mesh_resolution_mm=mesh_resolution_mm,
                                    substrate=substrate,
                                    far_field=far_field)
    if template in PYRAMID_HORN_TEMPLATES:
        # §ME-7 角锥喇叭（文末 PYRAMID_HORN 段）：单波导口 RectWGPort
        # 解析 TE10 + 四壁 3D 阶梯化整脚本渲染器（mmwave 同款早分发）
        return pyramid_horn_render(template, params, freq_range_ghz,
                                   mesh_resolution_mm=mesh_resolution_mm,
                                   excite_port=params["_excite_port"],
                                   far_field=far_field)
    if template in COAX_WG_TEMPLATES:
        # §ME-6 波导-同轴过渡（文末 COAX_WG 段）：探针基集总桥 + RectWGPort
        # 解析 TE10 整脚本渲染器（pyramid_horn 同款早分发）
        return coax_wg_render(template, params, freq_range_ghz,
                              mesh_resolution_mm=mesh_resolution_mm,
                              excite_port=params["_excite_port"],
                              far_field=far_field)
    if template in RIDGED_WG_TEMPLATES:
        # TA-6 空气脊波导（render_diplexer_ridged 文末注册块）：双 RectWGPort
        # 解析 TE10 打在加宽馈段整脚本渲染器（pyramid_horn 同款早分发）
        return ridged_wg_render(template, params, freq_range_ghz,
                                mesh_resolution_mm=mesh_resolution_mm,
                                excite_port=params["_excite_port"],
                                far_field=far_field)
    render_fns = {
        "wilkinson": _wilk_lines, "patch": _patch_lines,
        "branchline": _branchline_lines, "dipole": _dipole_lines,
        "stepped_impedance": _stepped_lines, "coupled_line": _coupled_lines,
        "mline": _mline_lines, "cpw": _cpw_lines,
        "wstep": _wstep_lines, "stripline": _stripline_lines,
        # C9 传输线族 II：共面带（LumpedPort 差分直馈）/ 悬置带线（StripLinePort）
        "cps": _cps_lines, "suspended_stripline": _suspended_stripline_lines,
        "tjunc": _tjunc_lines, "bend": _bend_lines,
        "via": _via_lines, "atten_pi": _atten_pi_lines,
        "atten_t": _atten_t_lines, "ratrace": _ratrace_lines,
        "gysel": _gysel_lines, "hairpin": _hairpin_lines,
        # 交替取向 hairpin 变体（几何单源 _hairpin_layout(orientation=...)，w2g）
        "hairpin_alt": _hairpin_alt_lines,
        "coupled_bpf": _coupled_bpf_lines,
        # M-5 变容管调谐 BPF（hairpin 同族布局 + 开路端 lumped C(V)，几何单源
        # _hairpin_layout）
        "varactor_bpf": _varactor_bpf_lines,
        "msl_cpw": _msl_cpw_lines, "sma_launcher": _sma_launcher_lines,
        # §10.3 C1 天线族 II（附加模板段，几何段单源 _ant2_body）
        "monopole": _monopole_lines, "pifa": _pifa_lines, "ifa": _ifa_lines,
        "loop": _loop_lines, "helix": _helix_lines, "slot": _slot_lines,
        # §C3 滤波器族 II（几何段单源 _c3_body）
        "interdigital": _interdigital_lines, "combline": _combline_lines,
        "sir_bpf": _sir_bpf_lines,
        # §C4 耦合器族 II（附加模板段，几何段单源 _c4_layout）
        "cline_coupler": _cline_coupler_lines,
        "branchline_2sect": _branchline_2sect_lines,
        "lange": _lange_lines,
        # §10.3 C2 阵列族（几何段单源 _arr_layout / _arr_body，文末 C2 段）
        "patch_array_1x4": _patch_array_1x4_lines,
        "patch_array_2x2": _patch_array_2x2_lines,
        "patch_array_series": _patch_array_series_lines,
        # §DP-4 P3 EEP 阵列族（几何段单源 _eep_layout / _eep_body，文末 EEP 段）
        "patch_eep_2x2": _patch_eep_2x2_lines,
        "patch_eep_1x4": _patch_eep_1x4_lines,
        # SIW 族首族（文末 SIW 段，几何/端口/域单源 siw_layout）
        "siw": _siw_lines,
        # SIW 族第二成员（文末 MSL_SIW_TAPER 段，几何/端口/域单源
        # msl_siw_taper_layout；df6 A2）
        "msl_siw_taper": _msl_siw_taper_lines,
        # §MS_METASURFACE 超表面/FSS 单元族（文末 MS_METASURFACE 段，几何/
        # 端口/域单源 ms_unit_layout；df6 DP-10）；阵模板 ms_array_NxN 走
        # 整脚本渲染器早分发（render_script 顶部 PORTLESS 分发）
        "ms_patch": _ms_patch_lines,
        "ms_cross": _ms_cross_lines,
        "ms_jcross": _ms_jcross_lines,
        "ms_ring_patch": _ms_ring_patch_lines,
        # §F-A M3 环形谐振器（文末 RING_RESONATOR 段，几何单源
        # _ring_resonator_layout/_ring_resonator_lines；2026-09-26）
        "ring_resonator": _ring_resonator_lines,
        # TA 批（2026-10-02）：TA-1 Schiffman 移相器（四端口轮转）/ TA-2
        # 多节 λ/4 变换器（单端口集总端接），几何单源 _schiffman_layout /
        # _qwt_layout（render_phase_qwt 文末注册块）
        "schiffman": _schiffman_lines,
        "qwt_multisection": _qwt_lines,
        # TA 批第二批（2026-10-02）：TA-3 SICL 基片集成同轴线（StripLinePort，
        # 矩形域）/ TA-4 N-way 树形功分器（5 端口轮转），几何单源 sicl_layout
        # / _nway_layout（render_sicl_nway 文末注册块）
        "sicl": _sicl_lines,
        "nway_wilkinson": _nway_lines,
        # TA 批第三批（2026-10-02）：TA-5 Diplexer（3 端口单激励列轮转），
        # 几何单源 _diplexer_layout（render_diplexer_ridged 文末注册块）
        "diplexer": _diplexer_lines,
        # TA Wave A 席 1（2026-10-03）：TA-7 倒置微带 / TA-8 HM-SIW（layout
        # 单源 _hmsiw_layout，siw 同款机制）/ TA-9 有限地 FGCPW，几何单源
        # core/inverted_ms、core/hmsiw、core/fgcpw 设计链（render_ta_wave_a
        # 注册块）
        "inverted_ms": _inverted_ms_lines,
        "hmsiw": _hmsiw_lines,
        "fgcpw": _fgcpw_lines,
        # TA/AP Wave B 席 B9（2026-10-03，render_ta_wave_b 注册块）：
        # TA-10 ISL 屏蔽悬置线（layout 单源 _isl_layout，hmsiw 同款机制）
        # + AP-11 Vivaldi 端射张口槽线天线（layout 纯函数直调，
        # _ant2_body 同构），闭式链 core/isl_line、core/vivaldi_tsa
        "isl_shielded": _isl_lines,
        "vivaldi_tsa": _vivaldi_lines,
        # TA Wave C 席 D2（2026-10-03，render_ta_wave_c 注册块）：TA-11
        # 嵌入式微带（inverted_ms 同款均匀线结构，覆盖层 z 预算字面注入）+
        # TA-14 交叉耦合开路环四重奏 BPF（layout 单源 _xcheb_bpf4_layout，
        # hmsiw 同款机制），闭式链 core/embedded_line、core/cross_coupled_map
        # （cm_core 纯消费）
        "embedded_ms": _embedded_ms_lines,
        "xcheb_bpf4": _xcheb_bpf4_lines,
    }
    # cps：LumpedPort R=闭式 Z0（CPS 无地共形闭式 _cps_ri，按本次渲染的基板
    # er/h 精算，惰性导入；同时作 CalcPort 参考阻抗——R≠50 时若仍按 50Ω 归一，
    # 匹配线会显示 |(R−50)/(R+50)| 的假失配）。其余模板参考阻抗文本保持 "50"
    # 逐字节不变。
    z_ref_txt = "50"
    if template == "cps":
        from rfauto.core.calculators import _cps_ri

        _cps_z0 = _cps_ri(float(params.get("w_mm", 2.95)),
                          float(params.get("gap_mm", 0.5)),
                          float(substrate["h_mm"]), float(substrate["er"]))[1]
        params["_cps_r_ohm"] = round(_cps_z0, 4)
        z_ref_txt = repr(params["_cps_r_ohm"])
    elif template == "siw":
        # R=Z_PV=2b·Z_TE/w_eff 闭式（文末 SIW 段 _siw_r_port_ohm）；正常路径
        # 已由 siw_layout 注入 _siw_r_ohm，此处只兜底直调缺键
        if "_siw_r_ohm" not in params:
            params["_siw_r_ohm"] = round(_siw_r_port_ohm(
                float(params.get("w_mm", 12.1317)),
                float(params.get("d_mm", 0.6)),
                float(params.get("s_mm", 1.0)),
                float(substrate["er"]),
                float(params.get("h_mm", substrate["h_mm"])),
                (freq_range_ghz[0] + freq_range_ghz[1]) / 2), 4)
        z_ref_txt = repr(params["_siw_r_ohm"])
    elif template == "hmsiw":
        # R=Z_PV=2h·Z_TE/w_eff 闭式（TA-8，core/hmsiw.hmsiw_z_pv_ohm）；正常
        # 路径已由 hmsiw_layout 注入 _hmsiw_r_ohm，此处只兜底直调缺键（不经
        # layout——base 未定，闭式链自足）
        if "_hmsiw_r_ohm" not in params:
            from rfauto.core.hmsiw import hmsiw_closed_form, hmsiw_z_pv_ohm

            _h_ch = hmsiw_closed_form(
                float(params.get("w_mm", 5.5829)),
                float(substrate["h_mm"]),
                float(substrate["er"]),
                float(params.get("d_mm", 0.6)),
                float(params.get("s_mm", 1.0)))
            _h_r, _ = hmsiw_z_pv_ohm(
                _h_ch["w_eff_hmsiw_mm"], float(substrate["h_mm"]),
                float(substrate["er"]),
                (freq_range_ghz[0] + freq_range_ghz[1]) / 2)
            params["_hmsiw_r_ohm"] = round(_h_r, 4)
        z_ref_txt = repr(params["_hmsiw_r_ohm"])
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：TEM 波导模拟器片
        # 端口 R=η0·a/b（方胞=η0），CalcPort 同参考——R≠50 时按 50Ω 归一会
        # 显示 |(R−50)/(R+50)| 假失配（cps 同款口径）；layout 注入在 base_m
        # 就绪后的布局单源块（几何/守卫/近场线同源）
        from rfauto.core.metasurface_lut import ETA0_OHM

        z_ref_txt = repr(round(ETA0_OHM, 4))
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(substrate["h_mm"]) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    # EC-12 loss_model 旋钮（2026-10-05）：kappa_f0（缺省=单频 κ 近似，
    # 现行为逐字节不变 #329）| debye（等 Δε 极点平坦 tanD——宽带扫频
    # 时 kappa 档 tanD∝1/f 斜率失真的物理修复，官方 MSL_Debye_Substrate
    # 例口径）。极点参数渲染期确定性拟合（_debye_pole_fit，拟合点见
    # substrate_block 前的 _sub_head 装配段）后字面量注入；生效值随渲染
    # 文本自留痕（#283 惯例：生成脚本即 meta 落痕载体）。
    _loss_model = str(substrate.get("loss_model") or "kappa_f0")
    if _loss_model not in ("kappa_f0", "debye"):
        raise ValueError(
            f"substrate.loss_model={_loss_model!r} 不支持"
            "（合法 kappa_f0|debye）")
    _kappa_sub_head = (
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n")
    _sub_head = _kappa_sub_head
    _debye_import = ""
    f_max = f0 + fc  # 频段最高频率（激励带 edge）
    # 官方口径：base = 基板内波长 /50；mesh_resolution_mm>0 时作为 base 覆盖
    base_m = (3e8 / (f_max * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    # ratrace：渲染半径 R/k(BASE) 随网格档标度（ratrace_ring_mesh_k）——base
    # 先于 body 计算并经 params 注入，几何段与近场线同 BASE 同 k
    params["_base_mm"] = base_m * 1e3
    # sma_launcher：几何单源 sma_launcher_layout 一次计算，字面量注入 body /
    # z 网格 / 基板块（夹具口径 Z_G 抬板），近场线同源（_near_points 分支）
    params["_h_sub_mm"] = h_m * 1e3
    params["_sub_er"] = er      # 几何段闭式消费（varactor C_geo 等；通用键）
    if template == "sma_launcher":
        params["_sma_layout"] = sma_launcher_layout(params, h_m, base_m)
    if template == "siw":
        # siw：几何/端口/域单源 siw_layout（文末 SIW 段；矩形域 DOM_X/DOM_Y
        # 字面注入见 f-string _dom_x_txt/_dom_y_txt）。h_mm 模板参数优先于
        # substrate（slotline_family_params 同款合并），z 网格/基板盒/body/
        # 近场线全部同源消费
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_siw_layout"] = siw_layout(params, freq_range_ghz, base_m, h_m)
        params["_siw_r_ohm"] = round(params["_siw_layout"]["r_port"], 4)
    elif template == "msl_siw_taper":
        # msl_siw_taper：几何/端口/域单源 msl_siw_taper_layout（文末
        # MSL_SIW_TAPER 段；矩形域 DOM_X/DOM_Y 字面注入同 siw）。h_mm 模板
        # 参数优先于 substrate（siw 同款合并），锥宽设计链/z 网格/近场线同源
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_msl_siw_taper_layout"] = msl_siw_taper_layout(
            params, freq_range_ghz, base_m, h_m)
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：几何/端口/域/
        # 近场线单源 ms_unit_layout（守卫在此层：NEAR≤最小缝/3 违反抛错）
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_ms_layout"] = ms_unit_layout(
            template, params, freq_range_ghz, base_m, h_m)
    elif template == "sicl":
        # sicl（round15 TA-3，render_sicl_nway 文末注册块）：几何/端口/域单源
        # sicl_layout；矩形域 DOM_X/DOM_Y 字面注入同 siw。h_mm 模板参数（腔
        # 高 b=H_SUB）优先于 substrate，z 网格/基板盒/body/近场线同源消费
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_sicl_layout"] = sicl_layout(
            params, freq_range_ghz, base_m, h_m)
    elif template == "hmsiw":
        # hmsiw（TA-8，render_ta_wave_a 注册块）：几何/端口/域单源
        # hmsiw_layout；矩形域 DOM_X/DOM_Y 字面注入同 siw。h_mm 模板参数
        # （式 (13) 声明域内基板厚）优先于 substrate，z 网格/基板盒/body/
        # 近场线同源消费
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_hmsiw_layout"] = hmsiw_layout(
            params, freq_range_ghz, base_m, h_m)
        params["_hmsiw_r_ohm"] = round(params["_hmsiw_layout"]["r_port"], 4)
    elif template == "isl_shielded":
        # TA-10 ISL（render_ta_wave_b 注册块，ge8b Wave B 席 B9）：几何/
        # 端口/域单源 isl_layout；基板悬浮 [Z_G, Z_G+H_SUB]（TA-7 对偶
        # z 序：空气隙在基板之下），h_m=substrate 基板厚直通
        params["_isl_layout"] = isl_layout(params, base_m, h_m)
    elif template == "xcheb_bpf4":
        # TA-14 开路环四重奏（render_ta_wave_c 注册块，ge8d Wave D 席 D2）：
        # 几何/端口单源 _xcheb_bpf4_layout（#266 缝守卫在 layout 内，base_m
        # 已就绪）；近场线/geometry_spec 同源消费
        params["_xcheb_layout"] = _xcheb_bpf4_layout(params, base_m)
    body = render_fns.get(template, _patch_lines)(params)
    near_m = base_m / _knob_near_ratio
    if template in C3_TEMPLATES:
        # §C3 耦合缝网格守卫（#266）：NEAR ≤ 最小耦合缝/3，违反即抛错——缺省
        # mesh=0（λ_sub/50）下 NEAR 0.285mm > 外缝 0.139~0.242mm 曾致缝内零
        # 内部线、外 Q 建模粗、峰位 −5%；不许静默粗网格
        c3_gap_mesh_guard(template, params, near_m)
    radiator = _TEMPLATE_RADIATOR.get(template, False)
    air_top = (3e8 / f_max / 4) if radiator else 5e-3
    air_side = (3e8 / f_max / 4) if radiator else 0.0
    if _knob_air_top_m is not None:
        if _knob_air_top_m <= 0:
            raise ValueError(f"_air_top_m 须为正，得 {_knob_air_top_m}")
        air_top = _knob_air_top_m
    port_axes = _TEMPLATE_PORT_AXES.get(template, ("y",))
    b_x0, b_x1 = "PML_8" if "x" in port_axes else "MUR", \
        "PML_8" if "x" in port_axes else "MUR"
    b_y0, b_y1 = "PML_8" if "y" in port_axes else "MUR", \
        "PML_8" if "y" in port_axes else "MUR"
    # §MS_METASURFACE 波导模拟器对壁（文末 MS_METASURFACE 段）：x 对壁 PEC /
    # y 对壁 PMC ≡ 法向入射无限阵（E∥x 极化前提）——覆盖 port_axes 缺省
    if template in _TEMPLATE_WALL_BC:
        b_x0, b_x1, b_y0, b_y1 = _TEMPLATE_WALL_BC[template]
    near_x, near_y = _near_points(template, params, base_mm=params["_base_mm"])
    if template == "cps" and _knob_x_refine > 0:
        # cps 缝区 x 向加密（wf:cps-xrefine，单变量对照）：缝 [−gap/2, gap/2]
        # 等分 2N 格，内部线（含缝中线 x=0 去重）精确入网。CPS 奇模场集中于
        # 缝区——引擎 εeff +13.3% 归因候选①"缝 0.5mm 仅 2 格"的收敛性验证档
        # （runs/cps_xrefine/criteria.md 预声明；c9 复跑遗留 TODO）。
        _gap_half_m = float(params.get("gap_mm", 0.5)) * 1e-3 / 2.0
        near_x.extend(_xv for _xv in (
            _gap_half_m * (_i / _knob_x_refine - 1.0)
            for _i in range(1, 2 * _knob_x_refine))
            if all(abs(_xv - _e) > 1e-9 for _e in near_x))
        near_x.sort()

    # tjunc：三端口 β 的 CSV 必须在 _port3.CalcPort 之后写（固定槽位的
    # beta_block 只覆盖 port1/2），独立第二插桩槽 + 存在性守卫
    beta_block3 = ""
    if template == "tjunc":
        beta_block3 = (
            '# tjunc 锚：三端口 β 金标准（对照闭式 εeff，|Δ|≤2%）\n'
            '_b3 = getattr(_port3, "beta", None)\n'
            'if _b3 is not None:\n'
            '    with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
            '              "w", newline="") as _bfh:\n'
            '        _bw = csv.writer(_bfh)\n'
            '        _bw.writerow(["freq_hz", "beta1_rad_per_m", '
            '"beta2_rad_per_m", "beta3_rad_per_m"])\n'
            '        for _i, _fi in enumerate(f):\n'
            '            _bw.writerow([_fi, float(np.real(_port1.beta[_i])), '
            'float(np.real(_port2.beta[_i])), '
            'float(np.real(_port3.beta[_i]))])\n'
        )


    # dipole（WP1.3）：自由空间器件特判——底边界 MUR（非 PEC 地，
    # 镜像破坏输入阻抗）、域 z 向下延 λ0/4、无基板（官方 Helical/
    # Dipole-SAR 教程口径）
    is_dipole = template == "dipole"
    # §10.3 C1 loop（2026-09-16 自由空间改造）：dipole 同款——环面 z=0、无基板
    # 无地、底 MUR、域 z 向下延 λ0/4（贴地口径镜像抵消辐射 R=0.56Ω 实证）
    is_free_space = is_dipole or template in _ANTENNA2_FREE_SPACE_TEMPLATES
    # slot：地面=z=0 有限金属板（槽向下辐射），底 MUR（dipole 同款；
    # PEC 底边界会短路槽）
    # cps（C9）：无地共面带，基板下方空气——底 MUR + 域向下延 AIR_TOP
    # ms_cross/ms_jcross（DP-10）：透射型 FSS——屏浮于空气区，底 MUR（ms_patch
    # 反射型保持 PEC=地面）
    bottom_bc = ("MUR" if (is_free_space
                           or template in ("via", "slot", "cps", "fgcpw",
                                           "ms_cross", "ms_jcross",
                                           "vivaldi_tsa"))
                 else "PEC")
    # stripline / suspended_stripline / siw / sicl：对称双面敷铜（siw/sicl=
    # 上下金属板），上地 = z-max PEC 边界（下地 = z-min PEC）
    top_bc = "PEC" if template in ("stripline", "suspended_stripline",
                                   "siw", "sicl") else "MUR"
    # rm-oe-c9 单变量对照旋钮：_boundary 六元覆盖 [x0,x1,y0,y1,bot,top]
    # （缺省 None=模板映射逐字节不变；CPS MUR→PML_8 归因对照跑用）
    if params.get("_boundary"):
        _bc_ovr = [str(v) for v in params["_boundary"]]
        if len(_bc_ovr) != 6:
            raise ValueError(
                f"_boundary 需 6 元 [x0,x1,y0,y1,bot,top]，得 {len(_bc_ovr)}")
        b_x0, b_x1, b_y0, b_y1, bottom_bc, top_bc = _bc_ovr

    # ── H-01 掩码自描述（W6-E，2026-10-06；ra_criteria SPECS §六 B 案）──
    # sparams.csv 本体无掩码/无自描述（5 列单激励的 S21 列可能是 S11 逐位
    # 副本，R6-4 实测）→ 写出端并排落 sparams.mask.json sidecar：csv 字节
    # 零漂移（B 案核心承诺，render_input_sha256/字面量裁决链不破坏），
    # measured_mask/filler_columns/reciprocity_filled/symmetry_filled/
    # excite_port/schema_version 随产物自描述（#314 全语义）。消费端
    # health_service._load_sparams_csv sidecar 权威→无 sidecar 回退启发式
    # （旧归档永续可读）。
    def _rotation_mask_literal(n: int, ep: int) -> str:
        """轮转单激励列掩码字面量：excite_port 列全测（行=响应口），其余未测。"""
        return "[" + ", ".join(
            "[" + ", ".join("True" if j == ep - 1 else "False"
                            for j in range(n)) + "]"
            for _i in range(n)) + "]"

    def _mask_sidecar_block(n_ports: int, excite_port: int,
                            mask_literal: str, *,
                            filler_literal: str = "{}",
                            reciprocity_literal: str = "[]",
                            symmetry_literal: str = "[]") -> str:
        """生成 sidecar 写出代码（渲染脚本内执行；仅追加不触碰 csv 写出段）。"""
        return (
            "# sparams.mask.json sidecar（H-01 掩码自描述 B 案，W6-E）：紧随\n"
            "# csv 落盘，csv 字节零漂移；掩码/填充/激励口随产物自描述（#314）。\n"
            "import json as _mask_json\n"
            "_mask_doc = {\n"
            '    "schema_version": "1",\n'
            f'    "n_ports": {n_ports},\n'
            f'    "excite_port": {excite_port},\n'
            f'    "measured_mask": {mask_literal},\n'
            f'    "filler_columns": {filler_literal},\n'
            f'    "reciprocity_filled": {reciprocity_literal},\n'
            f'    "symmetry_filled": {symmetry_literal},\n'
            "}\n"
            'with open(CSV_PATH.replace("sparams.csv", "sparams.mask.json"),\n'
            '          "w", encoding="utf-8") as _mask_fh:\n'
            "    _mask_json.dump(_mask_doc, _mask_fh, ensure_ascii=False,\n"
            "                    indent=1)\n"
        )

    # 尾部插桩（#208）：默认模板 = S31/S23 双激励路径（+ tjunc beta_block3）；
    # ratrace/§C4 四端口族 = 单激励 4 探针全记录（一列 9 列 CSV）。整 4×4 矩阵
    # 由适配器层按 excite_port=1..4 渲染 4 份脚本、进程隔离各跑一次后装配
    # （skrf .s4p 主产物）——进程内跨 Run 复用 CSX/端口包装器踩绑定对
    # 象生命周期雷（Run(cleanup=True) 销毁激励属性/CSX，pt3/pt4 实测）。
    if template in _FOUR_PORT_ROTATION_TEMPLATES:
        ep = max(1, min(4, int(params.get("_excite_port", 1) or 1)))
        loop_block = ""
        s31_block = (
            '# ' + template + ' 单激励列（进程隔离轮转的第 ' + str(ep) +
            ' 列）：excite=0 端口仅探针仍记录，一列四元素全出。\n'
            '_port3.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '_port4.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '_SREF = _port' + str(ep) + '.uf_inc\n'
            'S11 = _port1.uf_ref / _SREF\n'
            'S21 = _port2.uf_ref / _SREF\n'
            'S31 = _port3.uf_ref / _SREF\n'
            'S41 = _port4.uf_ref / _SREF\n'
            'with open(CSV_PATH, "w", newline="") as fh:\n'
            '    w = csv.writer(fh)\n'
            '    w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", '
            '"im_S21", "re_S31", "im_S31", "re_S41", "im_S41"])\n'
            '    for _i, _fi in enumerate(f):\n'
            '        w.writerow([_fi, S11[_i].real, S11[_i].imag, '
            'S21[_i].real, S21[_i].imag, S31[_i].real, S31[_i].imag, '
            'S41[_i].real, S41[_i].imag])\n'
            + _mask_sidecar_block(4, ep, _rotation_mask_literal(4, ep))
            + '_LOOP_DONE = True\n'
        )
    elif template in _NWAY_PORT_ROTATION_TEMPLATES:
        # TA-4 nway_wilkinson（5 端口轮转，#208 口径推广）：11 列单激励 CSV
        # （freq + 5×(re,im)，openems_rotation _load_round_csv P2⑬ 通用列
        # 消费）——列生成按 meta n_ports 参数化，4 端口分支逐字节不动
        ep = max(1, min(5, int(params.get("_excite_port", 1) or 1)))
        loop_block = ""
        _calc = "".join(
            f'_port{k}.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            for k in range(1, 6))
        _sdefs = "".join(
            f'S{k}1 = _port{k}.uf_ref / _SREF\n' for k in range(1, 6))
        _hdr = ", ".join(
            f'"re_S{k}1", "im_S{k}1"' for k in range(1, 6))
        _rows = ", ".join(
            f'S{k}1[_i].real, S{k}1[_i].imag' for k in range(1, 6))
        s31_block = (
            '# ' + template + ' 单激励列（进程隔离轮转的第 ' + str(ep) +
            ' 列）：excite=0 端口仅探针仍记录，一列五元素全出。\n'
            + _calc
            + '_SREF = _port' + str(ep) + '.uf_inc\n'
            + _sdefs
            + 'with open(CSV_PATH, "w", newline="") as fh:\n'
            '    w = csv.writer(fh)\n'
            '    w.writerow(["freq_hz", ' + _hdr + '])\n'
            '    for _i, _fi in enumerate(f):\n'
            '        w.writerow([_fi, ' + _rows + '])\n'
            + _mask_sidecar_block(5, ep, _rotation_mask_literal(5, ep))
            + '_LOOP_DONE = True\n'
        )
    elif template in _THREE_PORT_ROTATION_TEMPLATES:
        # TA-5 diplexer（3 端口轮转，#208 口径 N=3 档）：7 列单激励 CSV
        # （freq + 3×(re,im)）；主判读列=port1（antenna 公共口：能量守恒/
        # 互补/交越三判读量均在 port1 列），port2/3 轮仅补全 S 矩阵
        ep = max(1, min(3, int(params.get("_excite_port", 1) or 1)))
        loop_block = ""
        _calc = "".join(
            f'_port{k}.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            for k in range(1, 4))
        _sdefs = "".join(
            f'S{k}1 = _port{k}.uf_ref / _SREF\n' for k in range(1, 4))
        _hdr = ", ".join(
            f'"re_S{k}1", "im_S{k}1"' for k in range(1, 4))
        _rows = ", ".join(
            f'S{k}1[_i].real, S{k}1[_i].imag' for k in range(1, 4))
        s31_block = (
            '# ' + template + ' 单激励列（进程隔离轮转的第 ' + str(ep) +
            ' 列）：excite=0 端口仅探针仍记录，一列三元素全出。\n'
            + _calc
            + '_SREF = _port' + str(ep) + '.uf_inc\n'
            + _sdefs
            + 'with open(CSV_PATH, "w", newline="") as fh:\n'
            '    w = csv.writer(fh)\n'
            '    w.writerow(["freq_hz", ' + _hdr + '])\n'
            '    for _i, _fi in enumerate(f):\n'
            '        w.writerow([_fi, ' + _rows + '])\n'
            + _mask_sidecar_block(3, ep, _rotation_mask_literal(3, ep))
            + '_LOOP_DONE = True\n'
        )
    else:
        loop_block = ""
        s31_block = (
            '# S31 免费（port3 探针在 port1 激励的同一 run 里已记录）；S23 需第二激励\n'
            '# （port3 激励）——翻转激励使能后新建 FDTD 复用 CSX/网格重跑（时间 ×2，\n'
            '# 2026-09-04）。任何一步不可用就跳过对应列，不阻塞主 S 参数输出。\n'
            'S31 = None\n'
            'S23 = None\n'
            'try:\n'
            '    _port3.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '    S31 = _port3.uf_ref / _port1.uf_inc\n'
            'except Exception:\n'
            '    S31 = None\n'
            'if S31 is not None:\n'
            '    try:\n'
            '        _SIM3 = SIM_PATH + "_p3exc"\n'
            '        # 找金属属性对象（body 里变量名随模板不同：mline/patch/filt...）\n'
            '        _metal3 = None\n'
            '        for _i in range(CSX.GetQtyProperties()):\n'
            '            _pr = CSX.GetProperty(_i)\n'
            '            if str(_pr.GetTypeString()) == "Metal" and str(_pr.GetName()) != "ground":\n'
            '                _metal3 = _pr\n'
            '                break\n'
            '        assert _metal3 is not None\n'
            '        # port3 的激励副本（excite=0 的端口不创建激励属性，无法就地翻转——\n'
            '        # 2026-09-04 实测）：PortNamePrefix 隔离探针命名，几何复用 _port3\n'
            '        _port3e = MSLPort(CSX, port_nr=3, metal_prop=_metal3,\n'
            '                          start=np.array(_port3.start), stop=np.array(_port3.stop),\n'
            '                          prop_dir=int(_port3.prop_ny), exc_dir=int(_port3.exc_ny),\n'
            '                          excite=1, FeedShift=10 * NEAR,\n'
            '                          MeasPlaneShift=float(_port3.measplane_shift),\n'
            '                          PortNamePrefix="e3_")\n'
            '        # 第二激励轮前禁用旧激励属性：port1 excite=1 的激励属性仍\n'
            '        # 随 CSX 存活，不禁止则第二 run 双激励、S23 被同相 -3dB 直\n'
            '        # 通污染（gysel pt1 实测 S23=-3.1dB 且相位=S21=-130°）。\n'
            '        # 直接操作 CSX 属性、不经旧 wrapper（#208 生命周期雷）；\n'
            '        # GetTypeString()=="Excitation" 绑定实测锚定。\n'
            '        for _i in range(CSX.GetQtyProperties()):\n'
            '            _pr = CSX.GetProperty(_i)\n'
            '            if (str(_pr.GetTypeString()) == "Excitation"\n'
            '                    and not str(_pr.GetName()).startswith("e3_")):\n'
            '                _pr.SetEnabled(0)\n'
            '        _FDTD3 = openEMS(NrTS=' + repr(_nrts) + ')\n'
            '        _FDTD3.SetCSX(CSX)\n'
            '        _FDTD3.SetGaussExcite(F0, FC)\n'
            '        _FDTD3.SetBoundaryCond(["@BX0@", "@BX1@", "@BY0@", '
            '"@BY1@", "@BBOT@", "@BTOP@"])\n'
            '        _FDTD3.Run(_SIM3, verbose=0, disable_dumps=True, cleanup=True)\n'
            '        _port3e.CalcPort(_SIM3, f, ref_impedance=50)\n'
            '        _port2.CalcPort(_SIM3, f, ref_impedance=50)\n'
            '        S23 = _port2.uf_ref / _port3e.uf_inc\n'
            '    except Exception:\n'
            '        S23 = None\n'
            '\n'
        )
        s31_block += beta_block3
    # 边界条件 token 注入（s31_block/loop_block 是普通字符串，不吃外层
    # f-string 的替换——用 @TOKEN@ 占位此处统一填入，避免双重转义）
    _bc_map = {
        '"@BX0@"': f'"{b_x0}"', '"@BX1@"': f'"{b_x1}"',
        '"@BY0@"': f'"{b_y0}"', '"@BY1@"': f'"{b_y1}"',
        '"@BBOT@"': f'"{bottom_bc}"', '"@BTOP@"': f'"{top_bc}"',
    }
    for _tok, _val in _bc_map.items():
        s31_block = s31_block.replace(_tok, _val)
        loop_block = loop_block.replace(_tok, _val)

    def fmt_list(vs: list[float]) -> str:
        return "[" + ", ".join(repr(v) for v in vs) + "]"

    # 均匀线锚模板（mline/cpw）：额外写 CalcPort 自算 β（金标准判据
    # #162——uf_ref/uf_inc 相位含端口分解伪象不可判读 #161，β 才是与
    # 闭式 εeff 对照的正确量）
    # cpw/fgcpw 需要额外的端口类 import（footer 固定 import 不含 CPWPort）
    extra_ports_import = ", CPWPort" if template in ("cpw", "msl_cpw", "fgcpw") else ""
    extra_ports_import += (", StripLinePort"
                           if template in ("stripline", "suspended_stripline",
                                           "sicl")
                           else "")
    extra_ports_import += (
        ", LumpedPort" if "LumpedPort" not in extra_ports_import else "")
    beta_block = ""
    if template in ("mline", "cpw", "stripline", "suspended_stripline",
                    "wstep", "bend", "via",
                    "atten_pi", "atten_t", "ratrace", "gysel", "branchline",
                    "hairpin", "hairpin_alt", "coupled_bpf", "varactor_bpf",
                    "msl_cpw", "sma_launcher",
                    "cline_coupler", "branchline_2sect", "lange",
                    "interdigital", "combline", "sir_bpf", "cps", "siw",
                    "msl_siw_taper", "qwt_multisection", "sicl",
                    "inverted_ms", "hmsiw", "fgcpw"):
        if template == "wstep":
            # 双段两 β + 引擎自算线阻抗 ZL（W2⑤ 定案 (a)，2026-09-16）：
            # ReadUIData 用三探针算 Z_ref=sqrt(Et·dEt/(Ht·dHt))（驻波因子精确
            # 抵消，激励端亦有效），随后 CalcPort(ref_impedance=50) 把它覆盖——
            # 此处重读一次恢复 ZL 落盘（uf_inc/uf_ref 不受影响，S 列口径不变；
            # sparams.csv 契约不动）。ZL 供后处理 renorm_engine_s_to_ref 做
            # 引擎自洽基（HJ-vs-引擎 Z 偏差诊断），β 仍是金标准锚（#162）。
            beta_block = (
                '# wstep 锚：双端口 β 金标准（对照两段闭式 εeff，|Δ|≤2%）+ 引擎\n'
                '# 自算线阻抗 ZL（ReadUIData 重读恢复被 CalcPort ref=50 覆盖的 Z_ref）\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta1_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i]))])\n"
            )
        elif template == "mline":
            # mline 单 β 金标准 + 引擎自算线阻抗 ZL 双端口落盘（W3②，2026-09-16）：
            # 与 wstep 同法 ReadUIData 重读恢复被 CalcPort(ref=50) 覆盖的 Z_ref。
            # 列契约：前两列 freq_hz,beta_rad_per_m **逐字节不变**（scripts/
            # wp39_followup_run.read_port_beta_csv / engine_benchmark_mline._beta_eps
            # 按列位置读 r[0]/r[1]；health_service 按 "beta*rad_per_m" 名匹配），
            # 追加 beta2 + re/im_zl{1,2}_ohm 供 wp39 引擎 ZL 基匹配判据
            # （service/wp39_benchmark.mline_port_match_health）——H1 实证：50Ω 基
            # |S11| 伪底 ≡ |Γ(ZL_engine,50)|（归档 6 档残差 ≤0.94dB，换基后 −50dB）。
            beta_block = (
                '# mline 锚：β 金标准（对照闭式 εeff，|Δ|≤2%）+ 引擎自算线阻抗 ZL\n'
                '# （ReadUIData 重读恢复被 CalcPort ref=50 覆盖的 Z_ref；两端口）\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i]))])\n"
            )
        elif template in ("via", "msl_cpw"):
            # 双段两 β：port1/port2 各自 CalcPort β → 分段 εeff 锚
            beta_block = (
                f'# {template} 锚：双端口 β 金标准（对照两段闭式 εeff，|Δ|≤2%）\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta1_rad_per_m", '
                '"beta2_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i]))])\n"
            )
        elif template == "sma_launcher":
            # port1 = 同轴截面集总桥（LumpedPort 无 beta 属性，直取会
            # AttributeError）；β 金标准只写 port2（MSL HJ 闭式锚）
            beta_block = (
                '# sma_launcher 锚：port2 β 金标准（对照 MSL HJ 闭式 εeff，'
                '|Δ|≤2%）；port1=同轴截面集总桥无 β\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta2_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port2.beta[_i]))])\n"
            )
        elif template == "cps":
            # C9 cps 端口几何落盘（2026-09-18 w2f 后续定标批 ②，同 SSL beta 块
            # 先例）：LumpedPort 无 β 属性（sma_launcher 同坑），εeff=S21 解缠
            # 相位斜率口径的线长不确定度=端口元落格——端口参考面=端口元 E 场
            # 节点（Yee y 向 cell 中心），相对名义 Y0/Y1 可吸附 ±1 格 → 标称线
            # 长口径 εeff 地板 ±5.7%（±1.14mm/40mm，pt1 postmortem）。按终网格
            # 实测 port_y1/2_m 与 plane_dist_m 落盘，判读器 G2 用实测线长替代
            # 标称 L，地板压到 ~±1%（±半格/40mm）。
            beta_block = (
                '# cps 锚：端口元 y 坐标/实测差分线长（LumpedPort 无 β，'
                'w2f 定标批 ②）\n'
                '_ys = np.asarray(mesh.GetLines("y"), dtype=float)\n'
                'def _y_node(_yv):\n'
                '    _j = int(np.clip(np.searchsorted(_ys, _yv) - 1, 0, '
                '_ys.size - 2))\n'
                '    return float(0.5 * (_ys[_j] + _ys[_j + 1]))\n'
                '_y1_node = _y_node(Y0)\n'
                '_y2_node = _y_node(Y1)\n'
                '_plane_dist = _y2_node - _y1_node\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "port_y1_m", "port_y2_m", '
                '"plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, _y1_node, _y2_node, _plane_dist])\n"
            )
        elif template == "siw":
            # siw 锚：端口元 y 坐标/实测差分线长（cps 同契约；LumpedPort 无 β，
            # criteria §3）——S21 解缠相位斜率 ÷ plane_dist = β 测量（OE 锚 G1
            # 主判）；Y0/Y1=端口盒中心（测量面），落格坐标由终网格实测
            beta_block = (
                '# siw 锚：端口元 y 坐标/实测差分线长（LumpedPort 无 β，'
                'cps 同契约）\n'
                '_ys = np.asarray(mesh.GetLines("y"), dtype=float)\n'
                'def _y_node(_yv):\n'
                '    _j = int(np.clip(np.searchsorted(_ys, _yv) - 1, 0, '
                '_ys.size - 2))\n'
                '    return float(0.5 * (_ys[_j] + _ys[_j + 1]))\n'
                '_y1_node = _y_node(Y0)\n'
                '_y2_node = _y_node(Y1)\n'
                '_plane_dist = _y2_node - _y1_node\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "port_y1_m", "port_y2_m", '
                '"plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, _y1_node, _y2_node, _plane_dist])\n"
            )
        elif template == "hmsiw":
            # hmsiw 锚：端口元 y 坐标/实测差分线长（cps/siw 同契约；
            # LumpedPort 无 β）——S21 解缠相位斜率 ÷ plane_dist = β 测量，
            # 对照式 (12) 链（Lai-Fumeaux 2009 T-MTT）；Y0/Y1=端口盒中心，
            # 落格坐标由终网格实测
            beta_block = (
                '# hmsiw 锚：端口元 y 坐标/实测差分线长（LumpedPort 无 β，'
                'cps/siw 同契约）\n'
                '_ys = np.asarray(mesh.GetLines("y"), dtype=float)\n'
                'def _y_node(_yv):\n'
                '    _j = int(np.clip(np.searchsorted(_ys, _yv) - 1, 0, '
                '_ys.size - 2))\n'
                '    return float(0.5 * (_ys[_j] + _ys[_j + 1]))\n'
                '_y1_node = _y_node(Y0)\n'
                '_y2_node = _y_node(Y1)\n'
                '_plane_dist = _y2_node - _y1_node\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "port_y1_m", "port_y2_m", '
                '"plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, _y1_node, _y2_node, _plane_dist])\n"
            )
        elif template == "msl_siw_taper":
            # msl_siw_taper 锚：双端口 β（MSLPort 线基=馈线 β，HJ 锚参照
            # mline 口径）+ 引擎自算线阻抗 ZL（ReadUIData 重读恢复被 CalcPort
            # ref=50 覆盖的 Z_ref，wstep/mline W3② 法）+ 测量面间距（SSL 同式
            # 2·DOM_Y−两 measplane_shift）——line_z0="engine" 线基反演判读
            # 旋钮（#250/#280）消费 zl 列；前两列 freq_hz,beta_rad_per_m 契约
            # 逐字节不变（health_service 按名匹配）
            beta_block = (
                '# msl_siw_taper 锚：双端口 β 金标准 + 引擎自算 ZL + 测量面间距\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                '_plane_dist = float(2 * DOM_Y - _port1.measplane_shift '
                '- _port2.measplane_shift)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm", "plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i])), _plane_dist])\n"
            )
        elif template == "suspended_stripline":
            # C9 悬置带线（2026-09-18 w2f-c9-refs 判读口径审）：前两列 freq_hz,
            # beta_rad_per_m 契约逐字节不变（smoke 判读器按列位置读）；追加
            # port2 β、两端口引擎自算线阻抗 ZL（ReadUIData 重读恢复被
            # CalcPort ref=50 覆盖的 Z_ref，同 mline W3② 法）与两测量面间距
            # plane_dist_m（2·BOARD − 两端口 measplane_shift；S21 相位斜率与
            # 端口三点差分 β 的自洽门 G0 需精确面距，网格吸附 ±BASE/2 不再
            # 进入判读不确定度）。
            beta_block = (
                '# suspended_stripline 锚：β 金标准 + 引擎 ZL + 测量面间距\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                '_plane_dist = float(2 * BOARD - _port1.measplane_shift '
                '- _port2.measplane_shift)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm", "plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i])), _plane_dist])\n"
            )
        elif template == "sicl":
            # sicl 锚（round15 TA-3，suspended_stripline 同构）：β 金标准
            # （StripLinePort，εeff=εr TEM 对照）+ 引擎自算线阻抗 ZL
            # （ReadUIData 重读，W3② 法）+ 测量面间距 plane_dist_m
            # （矩形域=2·DOM_Y − 两端口 measplane_shift，msl_siw_taper 同式）
            beta_block = (
                '# sicl 锚：β 金标准 + 引擎 ZL + 测量面间距\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                '_plane_dist = float(2 * DOM_Y - _port1.measplane_shift '
                '- _port2.measplane_shift)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm", "plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i])), _plane_dist])\n"
            )
        else:
            beta_block = (
                f'# {template} 锚：β 金标准数据（对照闭式 εeff，|Δ|≤2%）\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i]))])\n"
            )

    # sma_launcher z 网格字面量（米，几何单源 _sma_layout：夹具口径，见
    # sma_launcher_layout）：z=0 夹具底板 / Z_AX−RO 壳内壁底 / Z_G PCB 地 /
    # 基板 4 层 → Z_TOP（=针底切线）/ Z_AX 针轴 / +RI 针顶（桥下电极）/ +RO
    # 壳内壁顶（桥上电极）/ +ROS 壳外顶 / 壳顶上方 AIR_TOP
    _sma_lay = params.get("_sma_layout") if template == "sma_launcher" else None
    # TA-10 ISL z 网格字面量（米，几何单源 _isl_layout：空气隙/顶板同源）
    _isl_lay = params.get("_isl_layout") if template == "isl_shielded" else None
    if template == "isl_shielded" and _isl_lay is None:
        raise ValueError("isl_shielded: 缺 _isl_layout（必须经 render_script 渲染）")
    _sma_z_lines = ""
    _sma_z_top = 0.0
    if _sma_lay is not None:
        _sma_z_lines = ", ".join(repr(v) for v in (
            0.0, _sma_lay["z_ax"] - _sma_lay["ro"], _sma_lay["z_ax"],
            _sma_lay["z_ax"] + _sma_lay["ri"], _sma_lay["z_ax"] + _sma_lay["ro"],
            _sma_lay["z_ax"] + _sma_lay["ros"], _sma_lay["f_z"]))
        _sma_z_top = _sma_lay["z_ax"] + _sma_lay["ros"] + air_top
    # C9 suspended_stripline z 预算（米，字面注入，z 网格/基板盒/端口同源）：
    # 腔高 B=b_mm，基板厚 H_SUB 以带中面 B/2 对称悬浮 [B/2−H/2, B/2+H/2]
    _ssl_b = float(params.get("b_mm", 1.016)) * 1e-3
    if template == "suspended_stripline" and not (h_m < _ssl_b):
        raise ValueError(
            f"suspended_stripline: 基板厚 H_SUB={h_m * 1e3:.4g}mm 必须小于腔高 "
            f"b={_ssl_b * 1e3:.4g}mm（基板不得越出接地板腔）")
    _ssl_zlo = _ssl_b / 2.0 - h_m / 2.0
    _ssl_zmid = _ssl_b / 2.0
    _ssl_zhi = _ssl_b / 2.0 + h_m / 2.0
    # TA-7 inverted_ms z 预算（米，字面注入，z 网格/基板盒/body 同源）：
    # 地面 z=0（域 PEC 底界），空气隙 [0, Z_AIR]，基板 [Z_AIR, Z_AIR+H_SUB]——
    # 条带 z=Z_AIR=空气隙顶=基板下表面（金属/介质 z 序对调，TA-7 定义）
    _inv_zair = float(params.get("h_air_mm", 0.508)) * 1e-3
    # TA-11 embedded_ms 覆盖层预算（米，字面注入，z 网格/基板盒/body 同源）：
    # 地面 z=0（域 PEC 底界），基板 [0, H_SUB]，覆盖层 [H_SUB, H_SUB+H2]
    # ——条带 z=H_SUB=基板上表面=覆盖层下界面（嵌埋定义）
    _emb_h2 = float(params.get("h2_mm", 0.254)) * 1e-3
    # 基板 z 格数 → linspace 点数（SSL 半腔每 span、CPS 整腔）：缺省 4 格
    # =旧口径（SSL 3 点/半腔、CPS 5 点整腔）逐字节不变
    _sub_half_pts = max(2, _knob_sub_cells // 2 + 1)   # SSL：每半腔格数+1 点
    _cps_sub_pts = max(2, _knob_sub_cells + 1)         # CPS：整腔格数+1 点
    _sub_pts = max(2, _knob_sub_cells + 1)             # 微带/lange 等：整腔格数+1 点
    # §10.3 C1 antenna2 立体器件（monopole/helix）z 网格预算：布局单源
    # （馈口顶/元件面 mm → 米字面量 + 元件顶上方 AIR_TOP）
    if template in _ANTENNA2_TALL_TEMPLATES:
        _lay_z = _ant2_layout(template, params)
        _ant2_z_list = ", ".join(repr(z * 1e-3) for z in _lay_z["z_lines_mm"])
        _ant2_z_top = _lay_z["element_top_mm"] * 1e-3 + air_top
    else:
        _ant2_z_list, _ant2_z_top = "", 0.0
    # §C4 lange：air-bridge 抬高薄金属的 z 底/顶面精确入网（布局单源，米）。
    # 去桥变体（_bridge=0）z_lines 为空 → 哨兵 "H_SUB"：CSRectGrid.AddLine
    # 拒绝空数组（assert len>0，runs/c4_debridge/audit_nobridge.py exec 实证），
    # H_SUB 与基板 linspace 末点重合、脚本内 1µm 去重守卫随后移除重复线——
    # 最终 z 网格与"桥面线不再入网"等价。
    if template == "lange":
        _lange_z_vals = _c4_layout("lange", params)["z_lines"]
        _lange_z_list = (", ".join(repr(z) for z in _lange_z_vals)
                         if _lange_z_vals else "H_SUB")
    else:
        _lange_z_list = ""
    # dipole / loop（自由空间族）：域 z 向下延 λ0/4（元件面 z=0 居中，底 MUR 无地）
    z_mesh_block = (
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        "mesh.AddLine(\"z\", AIR_TOP)\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if is_free_space else (
        # via：双层板 0..2·H_SUB（内层地 z=H）+ 顶带上方/底带下方各
        # 留 AIR_TOP——两条带都必须是域内面（贴域边界的带=半边模场
        # 缺失/MUR 侵蚀，pt1 β 爆炸 + pt2 底带 β 崩坏实证）
        'mesh.AddLine("z", -AIR_TOP)\n'
        'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))\n'
        "mesh.AddLine(\"z\", 2 * H_SUB + AIR_TOP)\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "via" else (
        # stripline：对称板 0..2·H_SUB（带在 H_SUB 中面），半高 4 层 ×2；
        # 上边界即上地（PEC），无 AIR_TOP（场被屏蔽，域到上地为止）
        'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "stripline" else (
        # C9 suspended_stripline：腔 0..B_CAV（上下地=域 z 边界 PEC），带在中面
        # B/2，基板 H_SUB 以带为中面对称悬浮 [B/2−H/2, B/2+H/2]；基板两面/
        # 中面/壳边全部精确入网（#198），各层间 2 段过渡后 BASE 平滑
        # （基板两 span 的格数走 _sub_half_pts 旋钮，缺省=3 点逐字节不变）
        'mesh.AddLine("z", np.linspace(0.0, ' + repr(_ssl_zlo) + ', 3))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zlo) + ', '
        + repr(_ssl_zmid) + ', ' + repr(_sub_half_pts) + '))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zmid) + ', '
        + repr(_ssl_zhi) + ', ' + repr(_sub_half_pts) + '))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zhi) + ', '
        + repr(_ssl_b) + ', 3))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "suspended_stripline" else (
        # C9 cps + TA-9 fgcpw：无底地（基板下方空气——底 MUR + 域向下延
        # AIR_TOP）+ 基板层（cps _cps_sub_pts 点缺省=4 格旧口径；fgcpw 走
        # _SUB_CELLS_8_TEMPLATES G3 分档 8 层）+ 上方 AIR_TOP
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_cps_sub_pts) + '))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in ("cps", "fgcpw") else (
        # TA-7 inverted_ms：地面=z=0 域 PEC 底界，空气隙 [0, Z_AIR] 2 层 +
        # 基板 [Z_AIR, Z_AIR+H_SUB] _sub_cells 层 + 顶 AIR_TOP（金属/介质 z 序
        # 对调：条带悬于 z=Z_AIR=空气隙顶=基板下表面，z 字面与基板盒同源）
        'mesh.AddLine("z", np.linspace(0, ' + repr(_inv_zair) + ', 3))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_inv_zair) + ', '
        + repr(_inv_zair) + ' + H_SUB, ' + repr(_sub_pts) + '))\n'
        'mesh.AddLine("z", ' + repr(_inv_zair) + ' + H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "inverted_ms" else (
        # TA-11 embedded_ms：地面 z=0 域 PEC 底界，基板 [0, H_SUB] _sub_cells
        # 层 + 覆盖层 [H_SUB, H_SUB+H2] _sub_cells 层 + 顶 AIR_TOP（条带
        # z=H_SUB 恰在网格线，覆盖层厚字面 _emb_h2 与基板盒同源）
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))\n'
        'mesh.AddLine("z", np.linspace(H_SUB, H_SUB + ' + repr(_emb_h2)
        + ', ' + repr(_sub_pts) + '))\n'
        'mesh.AddLine("z", H_SUB + ' + repr(_emb_h2) + ' + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "embedded_ms" else (
        # sma_launcher（夹具口径，2026-09-16 根治）：z=0 夹具底板 → 壳内壁底 →
        # Z_G PCB 地 → 基板 4 层 → Z_TOP（微带面=针底切线）→ 针轴/针顶/壳内壁顶/
        # 壳外顶（同轴三半径柱面界恰在网格上）→ 壳顶上方 AIR_TOP（根治前域顶距壳顶
        # 仅 0.25mm=1 cell，H5）。字面量与 body 同源（_sma_layout）
        f'mesh.AddLine("z", np.array([{_sma_z_lines}]))\n'
        'mesh.AddLine("z", np.linspace('
        + (repr(_sma_lay["z_g"]) if _sma_lay else "0")
        + ", " + (repr(_sma_lay["z_top"]) if _sma_lay else "H_SUB")
        + ', 5))   # 基板 4 层（官方 substrate_cells=4，抬板 Z_G 起）\n'
        f'mesh.AddLine("z", {_sma_z_top!r})   # 壳顶 + AIR_TOP\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "sma_launcher" else (
        # §10.3 C1 antenna2 立体器件（monopole/helix）：无基板，z=0 PEC
        # 地 + 馈口顶/元件面精确入网 + 元件顶上方 AIR_TOP（字面注入，米）
        'mesh.AddLine("z", np.array([' + _ant2_z_list + ', '
        + repr(_ant2_z_top) + ']))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in _ANTENNA2_TALL_TEMPLATES else (
        # slot：地面=z=0 有限板，槽向下半空间也辐射 → 底 AIR_TOP（MUR）
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        'mesh.AddLine("z", np.linspace(0, H_SUB, 5))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in ("slot", "vivaldi_tsa") else (
        # §C4 lange：基板 _sub_cells 层 + air-bridge 薄金属 z 底/顶面（字面注入，
        # 米）+ 顶空气隙；桥面不入网即抬高盒不进网格（#174 零体积/#198 家族）
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.AddLine("z", np.array([' + _lange_z_list + ']))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "lange" else (
        # siw/sicl：封闭双板腔（上下板=域 z 边界 PEC），无空气区——基板 z
        # _sub_cells 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项，criteria §4.8；
        # sicl 条带中面 z=H_SUB/2 落格依赖偶数格，缺省 4 格生成期断言兜底）
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in ("siw", "sicl") else (
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：z 面字面注入
        # （基板内 linspace + 贴片面/端口片/域顶，layout 单源米制）；
        # ms_patch 无底空气区（z 底=地面 PEC 边界），cross/jcross 屏两侧
        # 空气区含端口片与 MUR 余量
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))\n'
        'mesh.AddLine("z", np.array(['
        + ", ".join(repr(z) for z in params["_ms_layout"]["z_lines"]) + ']))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in MS_UNIT_TEMPLATES else (
        # TA-10 isl_shielded（render_ta_wave_b 注册块）：空气隙 [0,Z_G] 2 层
        # + 基板 [Z_G, Z_G+H_SUB] _sub_cells 层（条带 z=Z_G+H_SUB=基板上
        # 表面恰在网格线）+ 顶板 Z_WALL 精确线 + 顶板上方 AIR_TOP（字面
        # 与基板盒/条带/顶板同源 _isl_layout）
        'mesh.AddLine("z", np.linspace(0, ' + repr(_isl_lay["g"]) + ', 3)) \n'
        'mesh.AddLine("z", np.linspace(' + repr(_isl_lay["g"]) + ', '
        + repr(_isl_lay["g"]) + ' + H_SUB, ' + repr(_sub_pts) + ')) \n'
        'mesh.AddLine("z", ' + repr(_isl_lay["z_wall"]) + ') \n'
        'mesh.AddLine("z", ' + repr(_isl_lay["z_wall"]) + ' + AIR_TOP) \n'
        'mesh.SmoothMeshLines("z", BASE) \n'
    ) if template == "isl_shielded" else (
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    )
    # EC-12 debye 档装配（kappa_f0 缺省=_kappa_sub_head 逐字节不变）：
    # 基板材料卡头部唯一化——12+ 模板族分支共享同一 AddMaterial 头文本，
    # 旋钮只换头部（AddBox 几何逐分支不变）。无基板模板（自由空间/天线2
    # 高杆族：comment-only substrate_block）显式拒绝 debye（无介质可建，
    # 静默 no-op 旋钮是陷阱，#1b 家法 fail-loud）。
    if _loss_model == "debye":
        if is_free_space or template in _ANTENNA2_TALL_TEMPLATES:
            raise ValueError(
                f"loss_model=debye 不适用于无介质基板模板 {template!r}"
                "（自由空间/纯 PEC 族无基板可建）")
        _n_poles_raw = params.get("_debye_poles")
        # 显式 0/负 = 配置错误 fail-loud（#364：`or 缺省`惯语禁用于
        # 显式非法值面——0 是"错了"不是"没传"）
        _n_poles = 2 if _n_poles_raw is None else int(_n_poles_raw)
        if _n_poles < 1:
            raise ValueError(
                f"_debye_poles 必须 ≥1，得到 {_n_poles}")
        _eps_inf, _d_eps, _tau = _debye_pole_fit(
            er, tan_d, freq_range_ghz, n_poles=_n_poles)
        _debye_import = (
            "\nfrom CSXCAD.CSProperties import CSPropDebyeMaterial\n")
        _sub_head = (
            "# Debye 色散基板（loss_model=debye；官方 MSL_Debye_Substrate\n"
            "# 例 fit_poles 口径：等 Δε 极点弛豫对数均布，eps_inf/Δε 对\n"
            "# 平坦目标 (ER, TAND) 在激励带内最小二乘——EC-12）\n"
            f"_sub_eps_inf = {_eps_inf!r}\n"
            f"_sub_eps_delta = {_d_eps!r}\n"
            f"_sub_tau = {_tau!r}\n"
            "sub = CSPropDebyeMaterial(CSX.GetParameterSet(), "
            f"order={len(_tau)}, epsilon=_sub_eps_inf)\n"
            'sub.SetName("substrate")\n'
            "CSX.AddProperty(sub)\n"
            "for _k, _t in enumerate(_sub_tau):\n"
            "    sub.SetDispersiveMaterialProperty(\n"
            "        _k, eps_delta=_sub_eps_delta, eps_relax=float(_t))\n"
        )

    substrate_block = (
        "# dipole/loop：自由空间器件，无基板无地（官方 Helical/Dipole-SAR 口径）\n"
        "# monopole/helix：理想 PEC 地面悬空导体，无介质板（像理论口径）\n"
    ) if (is_free_space or template in _ANTENNA2_TALL_TEMPLATES) else (
        # stripline：基板填满 0..2·H_SUB（上下地面之间）；无空气区
        _sub_head +
        'sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, 2 * H_SUB), priority=0)\n'
    ) if template in ("stripline", "via") else (
        # C9 suspended_stripline：基板 H_SUB 以带为中面对称悬浮于腔中
        # （面坐标与 z 网格字面值逐字节同源，零厚面恰在网格线）
        "# suspended_stripline：腔高 B_CAV（上下地=域 z 边界 PEC），基板厚 H_SUB "
        "对称悬浮 [B/2−H/2, B/2+H/2]，两侧空气隙各 (B−H)/2\n"
        "B_CAV = " + repr(_ssl_b) + "\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, " + repr(_ssl_zlo) + "), (BOARD, BOARD, "
        + repr(_ssl_zhi) + "), priority=0)\n"
    ) if template == "suspended_stripline" else (
        # sma_launcher 夹具口径：PCB 抬高 Z_G（=r_os−r_i−H_SUB，几何单源
        # _sma_layout 字面量）使针底切线=基板顶；z=0 PEC 边界=夹具底板，PCB 地
        # =body 里的夹具金属块顶；板边切口（y<Y_E）由 body 的空气盒覆盖
        "# sma_launcher：基板抬至 [Z_G, Z_G+H_SUB]（夹具口径，见 _sma_launcher_lines）\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, "
        + (repr(_sma_lay["z_g"]) if _sma_lay else "0") + "), (BOARD, BOARD, "
        + (repr(_sma_lay["z_top"]) if _sma_lay else "H_SUB") + "), priority=0)\n"
    ) if template == "sma_launcher" else (
        # msl_siw_taper：基板填满矩形域（DOM_X/DOM_Y 由 msl_siw_taper_layout
        # 注入；底=域 z 边界 PEC，顶=MUR 开放——MSL 区微带环境）
        "# msl_siw_taper：基板填满矩形域（SIW 顶壁=显式零厚板见 body）\n"
        + _sub_head +
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "msl_siw_taper" else (
        # sicl：基板（均匀介质填充）填满矩形域（上下板=域 z 边界 PEC +
        # 显式零厚板见 body）
        "# sicl：基板填满矩形域（上下板=域 z 边界 PEC + 显式零厚板见 body）\n"
        + _sub_head +
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "sicl" else (
        # hmsiw（TA-8）：基板填满矩形域（底板=域 z 边界 PEC + 显式零厚板见
        # body；顶开放=MUR——HMSIW 定义性质）
        "# hmsiw：基板填满矩形域（底=域 z 边界 PEC+显式零厚底板见 body；"
        "顶开放 MUR）\n"
        + _sub_head +
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "hmsiw" else (
        # TA-7 inverted_ms：基板悬浮于空气隙顶 [Z_AIR, Z_AIR+H_SUB]（金属/
        # 介质 z 序对调；z 字面与 z 网格/条带同源 _inv_zair）
        "# inverted_ms：基板悬浮 [Z_AIR, Z_AIR+H_SUB]（地面=z=0 域 PEC 底界，"
        "条带 z=Z_AIR 见 body）\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, " + repr(_inv_zair) + "), (BOARD, BOARD, "
        + repr(_inv_zair) + " + H_SUB), priority=0)\n"
    ) if template == "inverted_ms" else (
        # TA-11 embedded_ms：基板+覆盖层同 εr 单盒 [0, H_SUB+H2]（均匀嵌埋
        # 电气精确；覆盖层厚字面 _emb_h2 与 z 网格/body 同源）
        "# embedded_ms：基板+覆盖层单盒 [0, H_SUB+H2]（条带 z=H_SUB 见 body）\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB + "
        + repr(_emb_h2) + "), priority=0)\n"
    ) if template == "embedded_ms" else (
        # TA-10 isl_shielded（render_ta_wave_b 注册块）：基板悬浮于空气隙顶
        # [Z_G, Z_G+H_SUB]（TA-7 对偶 z 序：空气隙在基板之下；z 字面与 z
        # 网格/条带/顶板同源 _isl_layout）
        "# isl_shielded：基板悬浮 [Z_G, Z_G+H_SUB]（地面=z=0 域 PEC 底界，"
        "条带 z=Z_G+H_SUB 见 body）\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, " + repr(_isl_lay["g"]) + "), "
        "(BOARD, BOARD, " + repr(_isl_lay["g"]) + " + H_SUB), priority=0)\n"
    ) if template == "isl_shielded" else (
        # siw：基板填满矩形域（上下板=域 z 边界 PEC + 显式零厚板见 body）
        "# siw：基板填满矩形域（上下板=域 z 边界 PEC + 显式零厚板见 body）\n"
        + _sub_head +
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "siw" else (
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：基板填满单胞域
        # （ms_patch 地=z 底 PEC 边界；cross/jcross 屏浮，底 MUR 见 bottom_bc）
        "# ms 单元：基板填满单胞方形域（波导模拟器，屏/贴片零厚面见 body）\n"
        + _sub_head +
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template in MS_UNIT_TEMPLATES else (
        "# 基板延伸到侧边界（guided；官方口径：无板边衍射）；"
        "地面 = z-min PEC 边界\n"
        + _sub_head +
        "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB), priority=0)\n"
    )

    # ── WP4.1 nf2ff / SAR 注入块 ─────────────────────────────────────────────
    # 官方口径锚（docs/rf_template_references.md §8 + wiki 教程）：
    # Simple Patch Antenna（nf2ff 盒 = SimBox 缩 4×max_res；f_res 从 S11 谷取；
    # η = Prad/P_in）、Dipole SAR（DumpType 29 + CalcSAR mass=1g IEEE_62704）。
    _ff_on = far_field or sar
    sar_setup_block = ""
    if sar:
        # 组织等效模型（官方皮肤层文献值 @1GHz tissue database）；
        # CellConstantMaterial=1 官方要求（每 Yee 元单值材料，SAR 正确性）
        sar_setup_block = (
            '# ── SAR 组织等效模型（官方 Dipole SAR 教程：皮肤层 εr=50、'
            'κ=0.65 S/m、ρ=1100 kg/m³）──\n'
            'phantom = CSX.AddMaterial("phantom", epsilon=50.0, kappa=0.65,\n'
            "                          density=1100.0)\n"
            'phantom.AddBox((-25e-3, 20e-3, -15e-3), (25e-3, 65e-3, 15e-3), '
            "priority=0)\n"
            "# 模型盒边入网格（边界必须落网格线，#198/#212 家族教训）\n"
            'mesh.AddLine("x", np.array([-25e-3, 25e-3]))\n'
            'mesh.AddLine("y", np.array([20e-3, 65e-3]))\n'
            'mesh.AddLine("z", np.array([-15e-3, 15e-3]))\n'
            'mesh.SmoothMeshLines("x", BASE)\n'
            'mesh.SmoothMeshLines("y", BASE)\n'
            'mesh.SmoothMeshLines("z", BASE)\n'
            "# 最小间距守卫（#152）：新加线与既有线撞出 nm 级近重合会塌时间步\n"
            "for _ax in (\"x\", \"y\", \"z\"):\n"
            "    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)\n"
            "    _keep = [_ls[0]]\n"
            "    for _v in _ls[1:]:\n"
            "        if _v - _keep[-1] > 1e-6:\n"
            "            _keep.append(_v)\n"
            "    mesh.SetLines(_ax, np.array(_keep))\n"
            "# SAR 原始数据 dump：DumpType 29（FD 电场+体元+κ+密度）、HDF5、\n"
            "# cell 模式；盒比模型略大（官方口径：非零 κ/密度体元才计入）\n"
            '_sar_dump = CSX.AddDump("SAR_raw", dump_type=29, frequency=[F0],\n'
            "                        file_type=1, dump_mode=2)\n"
            "_sar_dump.AddBox((-27e-3, 18e-3, -17e-3), (27e-3, 67e-3, 17e-3))\n"
        )
    ff_setup_block = ""
    if _ff_on:
        # 接地辐射模板（patch + §10.3 C1 antenna2 地面族 + §10.3 C2 贴片阵）：
        # z 底=PEC 边界，CreateNF2FFBox 依 BC 自动排除 z- 面并置 PEC 镜像；
        # slot / loop（自由空间，2026-09-16）走六面全包分支（底 MUR）
        if template in ("patch", "pifa", "ifa", "monopole", "helix",
                        "patch_array_1x4", "patch_array_2x2", "patch_array_series",
                        "patch_eep_2x2", "patch_eep_1x4"):
            # z 底=PEC 边界：CreateNF2FFBox 依 BC 自动排除 z- 面并置 PEC 镜像
            # （绑定源码 openEMS.pyx CreateNF2FFBox：BC_type==0 → direction
            # False + mirror=1）；盒必须包住贴片+探针（z 从 0 起）
            ff_setup_block = (
                "# ── nf2ff 盒（官方 Simple Patch Antenna：域缩 4×网格）──\n"
                "_FF_MARGIN = 4 * BASE\n"
                "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, 0.0])\n"
                "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
                "                     H_SUB + AIR_TOP - _FF_MARGIN])\n"
                "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n"
            )
        else:  # dipole / slot / loop：自由空间（或底 MUR）六面全包
            ff_setup_block = (
                "# ── nf2ff 盒（官方教程：域缩 4×网格，六面全包）──\n"
                "_FF_MARGIN = 4 * BASE\n"
                "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN,\n"
                "                      -AIR_TOP + _FF_MARGIN])\n"
                "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
                "                     AIR_TOP - _FF_MARGIN])\n"
                "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n"
            )
    # nf2ff 依赖 dump 面输出（nf2ff_E_n.h5/nf2ff_H_n.h5），disable_dumps 会
    # 连带禁掉 → 注入时不传该开关；其余产物文件照常
    # ── 囚禁模定位场快照注入块（wf:varactor-locate，_field_dump 旋钮）──────
    # 缺省 None → field_dump_block="" 且 _run_kwargs 逐字节不变。
    field_dump_block = ""
    if _knob_field_dump:
        _fd_spec = _knob_field_dump if isinstance(_knob_field_dump, dict) else {}
        _fd_freqs = [float(x) * 1e9 for x in (_fd_spec.get("freqs_ghz") or [])]
        if not _fd_freqs:
            raise ValueError("_field_dump.freqs_ghz 缺——FD dump 必须给频点")
        for _fq in _fd_freqs:
            if not (f0 - fc - 1.0 <= _fq <= f0 + fc + 1.0):
                raise ValueError(
                    f"dump 频点 {_fq / 1e9:g}GHz 出激励带 "
                    f"[{(f0 - fc) / 1e9:g},{(f0 + fc) / 1e9:g}]GHz"
                    "（带外模不被泵浦，场分布无意义）")
        _fd_slabs = ""
        for _i, _sl in enumerate(_fd_spec.get("slabs") or []):
            _z0 = float(_sl["z0_mm"]) * 1e-3
            _z1 = float(_sl["z1_mm"]) * 1e-3
            _nm = str(_sl.get("name") or f"trap_E{_i}")
            _ss_raw = _sl.get("sub_sample") or [2, 2, 1]
            # CSXCAD SetSubSampling 收 list/array 长 3（CSProperties.pyx
            # L1470 断言 "'val' must be a list or array of length 3"）——
            # docstring 的 '2,2,4' 串示例与实现不符，渲染端统一转 int 列表
            if isinstance(_ss_raw, str):
                _ss = [int(x) for x in _ss_raw.replace(",", " ").split()]
            else:
                _ss = [int(x) for x in _ss_raw]
            if len(_ss) != 3 or any(v < 1 for v in _ss):
                raise ValueError(f"dump slab {_nm} sub_sample={_ss_raw!r} "
                                 "须为 3 个 ≥1 整数")
            if not (0.0 <= _z0 < _z1 <= h_m + air_top + 1e-9):
                raise ValueError(
                    f"dump slab {_nm} z=[{_z0:e},{_z1:e}] 越域 "
                    f"[0,{h_m + air_top:e}]")
            _fd_slabs += (
                f"_dump{_i} = CSX.AddDump({_nm!r}, dump_type=10, "
                f"frequency={_fd_freqs!r}, file_type=1, dump_mode=2,\n"
                f"                      sub_sampling={_ss!r})\n"
                f"_dump{_i}.AddBox((-BOARD, -BOARD, {_z0!r}), "
                f"(BOARD, BOARD, {_z1!r}))\n")
        if not _fd_slabs:
            raise ValueError("_field_dump.slabs 缺——至少一个 dump 盒")
        field_dump_block = (
            "# ── 囚禁模定位场快照（wf:varactor-locate，_field_dump 旋钮）──\n"
            "# dump_type=10=FD E 场（官方枚举 CSProperties.pyx L1407）、\n"
            "# dump_mode=2=cell 插值（E 场 node 插值在金属面假幅值，官方\n"
            "# docstring 警示 L1444）、file_type=1=hdf5；FD DFT 全 run 累积\n"
            "# →晚窗慢振铃主导→/FieldData/FD/f<i> 空间分布=囚禁模定位证据\n"
            + _fd_slabs)
    _run_kwargs = "" if (_ff_on or field_dump_block) else "disable_dumps=True, "
    ff_calc_block = ""
    if _ff_on and template in EEP_TEMPLATES:
        # ── DP-4 P3 EEP 单激励轮专用块：f_res=F0 固定（轮间同频方可叠加，J4d）+
        # farfield3d_cplx.csv 复数 3D dump（core.farfield 契约同表头，多余列
        # 容忍）。非 EEP 辐射模板走下方既有块（argmin|S11| 口径）——本分支
        # 不改其渲染字节（#315 兼容纪律）。功率口径（Prad/Dmax/η）非 EEP 轮
        # 消费面，不产出（PEC 镜像只影响功率积分、不影响 E 场复分量）。
        ff_calc_block = (
            "\n# ── nf2ff 远场（DP-4 P3 EEP 单激励轮：f_res=F0 固定口径）──\n"
            "# EEPₙ=第 n 元有源方向图（其余元 50Ω 集总元端接被动在场；nf2ff 以\n"
            "# 全局原点为相位参考，位置相位免手工补偿）。辅助产物 best-effort\n"
            "# （#105）：任何失败不阻塞主 S 参数输出。\n"
            "_FF_DIR = __import__(\"os\").path.dirname(\n"
            "    __import__(\"os\").path.abspath(__file__))\n"
            "import json as _json\n"
            "try:\n"
            "    _f_res = F0\n"
            "    _THETA3 = np.arange(" + repr(EEP_FF_THETA_DEG[0]) + ", "
            + repr(EEP_FF_THETA_DEG[1] + EEP_FF_THETA_DEG[2] * 0.5) + ", "
            + repr(EEP_FF_THETA_DEG[2]) + ")\n"
            "    _PHI3 = np.arange(" + repr(EEP_FF_PHI_DEG[0]) + ", "
            + repr(EEP_FF_PHI_DEG[1] + EEP_FF_PHI_DEG[2] * 0.5) + ", "
            + repr(EEP_FF_PHI_DEG[2]) + ")\n"
            "    _ff3 = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA3, _PHI3,\n"
            "                         outfile='farfield_3d.h5')\n"
            "    _et3 = np.asarray(_ff3.E_theta[0], dtype=complex)\n"
            "    _ep3 = np.asarray(_ff3.E_phi[0], dtype=complex)\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield3d_cplx.csv\"), \"w\", newline=\"\") as _f3h:\n"
            "        _f3w = csv.writer(_f3h)\n"
            "        _f3w.writerow([\"theta_deg\", \"phi_deg\", \"re_e_theta\", "
            "\"im_e_theta\", \"re_e_phi\", \"im_e_phi\"])\n"
            "        for _it in range(len(_THETA3)):\n"
            "            for _ip in range(len(_PHI3)):\n"
            "                _f3w.writerow([_THETA3[_it], _PHI3[_ip], "
            "_et3[_it, _ip].real, _et3[_it, _ip].imag,\n"
            "                               _ep3[_it, _ip].real, "
            "_ep3[_it, _ip].imag])\n"
            "    _ff_meta = {\n"
            "        \"ok\": True,\n"
            f"        \"template\": {template!r},\n"
            "        \"eep\": True,\n"
            f"        \"excite_port\": {int(params.get('_excite_port', 1) or 1)},\n"
            "        \"f_res_ghz\": F0 / 1e9,\n"
            "        \"f_res_mode\": \"fixed_F0\",\n"
            "        \"freq_band_ghz\": [(F0 - FC) / 1e9, (F0 + FC) / 1e9],\n"
            f"        \"grid_theta_deg\": {list(EEP_FF_THETA_DEG)!r},\n"
            f"        \"grid_phi_deg\": {list(EEP_FF_PHI_DEG)!r},\n"
            "        \"phase_reference\": \"nf2ff global origin\",\n"
            "        \"power_metrics\": None,\n"
            "        \"power_note\": (\"EEP 轮不产出 Prad/Dmax/η（功率口径非本产物\"\n"
            "                        \"消费面；PEC 镜像只影响功率积分不影响 E 场）\"),\n"
            "        \"nf2ff_box_start_m\": np.asarray(_FF_START).tolist(),\n"
            "        \"nf2ff_box_stop_m\": np.asarray(_FF_STOP).tolist(),\n"
            "        \"radius_m\": 1.0,\n"
            "    }\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "        _json.dump(_ff_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    try:\n"
            "        with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "                \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "            _json.dump({\"ok\": False, \"error\": str(_ffe)}, _mh,\n"
            "                       ensure_ascii=False)\n"
            "    except Exception:\n"
            "        pass\n"
            "    print(\"rfauto nf2ff 链失败（不阻塞 S 参数）:\", _ffe)\n"
        )
    elif _ff_on:
        ff_calc_block = (
            "\n# ── nf2ff 远场计算（WP4.1；官方口径 f_res=|S11| 谷，η=Prad/P_acc）──\n"
            "# 辅助产物：任何一步失败不阻塞主 S 参数输出（写 farfield_meta.json\n"
            "  # ok=false 留痕，观测性 best-effort #105）\n"
            "_FF_DIR = __import__(\"os\").path.dirname(\n"
            "    __import__(\"os\").path.abspath(__file__))\n"
            "import json as _json\n"
            "try:\n"
            "    _f_res_i = int(np.argmin(np.abs(S11)))\n"
            "    _f_res = float(f[_f_res_i])\n"
            "    _p_acc = float(np.real(_port1.P_acc[_f_res_i]))\n"
            "    _THETA_CUT = np.arange(-180.0, 181.0, 1.0)\n"
            "    _PHI_CUT = [0.0, 90.0]\n"
            "    _ffr = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA_CUT, _PHI_CUT)\n"
            "    _Dmax = float(np.atleast_1d(_ffr.Dmax)[0])\n"
            "    _Prad = float(np.atleast_1d(_ffr.Prad)[0])\n"
            "    _eta = (_Prad / _p_acc) if _p_acc > 0 else None\n"
            "    # 3D 方向图（官方 Outfile='3D_Pattern.h5' 口径）\n"
            "    _ff3 = _FF.CalcNF2FF(SIM_PATH, _f_res,\n"
            "                         np.arange(0.0, 181.0, 5.0),\n"
            "                         np.arange(0.0, 360.0, 5.0),\n"
            "                         outfile='farfield_3d.h5')\n"
            "    _en3 = np.asarray(_ff3.E_norm[0], dtype=float)\n"
            "    _db3 = 20 * np.log10(_en3 / max(_en3.max(), 1e-300) + 1e-300)\n"
            "    _th3 = np.arange(0.0, 181.0, 5.0)\n"
            "    _ph3 = np.arange(0.0, 360.0, 5.0)\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_cut.csv\"), \"w\", newline=\"\") as _ffh:\n"
            "        _fw = csv.writer(_ffh)\n"
            "        _fw.writerow([\"phi_deg\", \"theta_deg\", \"re_e_theta\", "
            "\"im_e_theta\", \"re_e_phi\", \"im_e_phi\", \"e_norm\", \"p_rad\"])\n"
            "        for _ip, _phv in enumerate(_PHI_CUT):\n"
            "            for _it, _thv in enumerate(_THETA_CUT):\n"
            "                _et = complex(_ffr.E_theta[0][_it, _ip])\n"
            "                _ep = complex(_ffr.E_phi[0][_it, _ip])\n"
            "                _fw.writerow([_phv, _thv, _et.real, _et.imag, "
            "_ep.real, _ep.imag,\n"
            "                              float(_ffr.E_norm[0][_it, _ip]),\n"
            "                              float(_ffr.P_rad[0][_it, _ip])])\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield3d.csv\"), \"w\", newline=\"\") as _f3h:\n"
            "        _f3w = csv.writer(_f3h)\n"
            "        _f3w.writerow([\"theta_deg\", \"phi_deg\", \"e_norm_db\"])\n"
            "        for _it in range(len(_th3)):\n"
            "            for _ip in range(len(_ph3)):\n"
            "                _f3w.writerow([_th3[_it], _ph3[_ip], "
            "float(_db3[_it, _ip])])\n"
            "    _ff_meta = {\n"
            "        \"ok\": True,\n"
            f"        \"template\": {template!r},\n"
            "        \"f_res_ghz\": _f_res / 1e9,\n"
            "        \"freq_band_ghz\": [(F0 - FC) / 1e9, (F0 + FC) / 1e9],\n"
            "        \"prad_w\": _Prad, \"p_acc_w\": _p_acc,\n"
            "        \"dmax_linear\": _Dmax,\n"
            "        \"dmax_dbi\": 10 * np.log10(max(_Dmax, 1e-300)),\n"
            "        \"efficiency\": _eta,\n"
            "        \"gain_max_dbi\": (10 * np.log10(max(_Dmax, 1e-300)) +\n"
            "                          10 * np.log10(_eta)) if _eta else None,\n"
            "        \"power_budget_closure\": (abs(_p_acc - _Prad) / _p_acc\n"
            "                                  if _p_acc > 0 else None),\n"
            "        \"nf2ff_box_start_m\": np.asarray(_FF_START).tolist(),\n"
            "        \"nf2ff_box_stop_m\": np.asarray(_FF_STOP).tolist(),\n"
            "        \"radius_m\": 1.0,\n"
            "    }\n"
            "    # ── PEC 地镜像修正（#249：CreateNF2FFBox 遇 PEC 底面置 mirror=1 →\n"
            "    # AddMirrorPlane 对每个积分面追加镜像通量，Prad=2×物理、Dmax −3.01dB）。\n"
            "    # 口径与 core.farfield.correct_pec_mirror 同式（渲染脚本保持纯净不 import\n"
            "    # 内核；单测钉住两者逐键数值一致）：盒底 z_start==0 → k=2，Prad/k、\n"
            "    # Dmax×k、η/闭合/增益重算；修正前六指标原值留 raw；六面全包（z_start<0）\n"
            "    # k=1 原值不动。服务层读到 pec_mirror_factor 即幂等直通，不二次折半。\n"
            "    # RFAUTO_PEC_MIRROR_BEGIN\n"
            "    _k_mirror = (2.0 if abs(float(_ff_meta[\"nf2ff_box_start_m\"][2])) < 1e-9\n"
            "                 else 1.0)\n"
            "    _ff_meta[\"pec_mirror_factor\"] = _k_mirror\n"
            "    if _k_mirror != 1.0:\n"
            "        _ff_meta[\"raw\"] = {_kk: _ff_meta.get(_kk) for _kk in (\n"
            "            \"prad_w\", \"dmax_linear\", \"dmax_dbi\", \"efficiency\",\n"
            "            \"gain_max_dbi\", \"power_budget_closure\")}\n"
            "        _Prad = float(_ff_meta[\"prad_w\"]) / _k_mirror\n"
            "        _Dmax = float(_ff_meta[\"dmax_linear\"]) * _k_mirror\n"
            "        _p_acc = float(_ff_meta[\"p_acc_w\"])\n"
            "        _eta = (_Prad / _p_acc) if _p_acc > 0 else None\n"
            "        _ff_meta[\"prad_w\"] = _Prad\n"
            "        _ff_meta[\"dmax_linear\"] = _Dmax\n"
            "        _ff_meta[\"dmax_dbi\"] = 10.0 * np.log10(max(_Dmax, 1e-300))\n"
            "        _ff_meta[\"efficiency\"] = _eta\n"
            "        _ff_meta[\"gain_max_dbi\"] = ((_ff_meta[\"dmax_dbi\"]\n"
            "                                      + 10.0 * np.log10(_eta))\n"
            "                                     if _eta else None)\n"
            "        _ff_meta[\"power_budget_closure\"] = (abs(_p_acc - _Prad) / _p_acc\n"
            "                                            if _p_acc > 0 else None)\n"
            "    # RFAUTO_PEC_MIRROR_END\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "        _json.dump(_ff_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    try:\n"
            "        with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "                \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "            _json.dump({\"ok\": False, \"error\": str(_ffe)}, _mh,\n"
            "                       ensure_ascii=False)\n"
            "    except Exception:\n"
            "        pass\n"
            "    print(\"rfauto nf2ff 链失败（不阻塞 S 参数）:\", _ffe)\n"
        )
        if sar:
            ff_calc_block += (
                "\n# ── SAR 计算（绑定已随包：SAR_Calculation mass=1g IEEE_62704）──\n"
                "try:\n"
                "    from openEMS.sar_calculation import SAR_Calculation\n"
                "    from openEMS.sar_utils import readSAR\n"
                "    _sc = SAR_Calculation(mass=1.0, method='IEEE_62704')\n"
                "    _sc.CalcFromHDF5(__import__(\"os\").path.join(SIM_PATH, "
                "'SAR_raw.h5'),\n"
                "                     __import__(\"os\").path.join(SIM_PATH, "
                "'SAR_1g.h5'))\n"
                "    _sar, _smesh, _smeta = readSAR(__import__(\"os\").path.join(\n"
                "        SIM_PATH, 'SAR_1g.h5'))\n"
                "    _p_abs = float(_smeta.get('power', 0.0) or 0.0)\n"
                "    _sar_max = float(np.max(_sar)) if _sar is not None else 0.0\n"
                "    with open(__import__(\"os\").path.join(_FF_DIR, \"sar.csv\"),\n"
                "              \"w\", newline=\"\") as _sfh:\n"
                "        _sw = csv.writer(_sfh)\n"
                "        _sw.writerow([\"metric\", \"value\"])\n"
                "        _sw.writerow([\"freq_hz\", _f_res])\n"
                "        _sw.writerow([\"mass_g\", 1.0])\n"
                "        _sw.writerow([\"p_acc_w\", _p_acc])\n"
                "        _sw.writerow([\"p_abs_w\", _p_abs])\n"
                "        _sw.writerow([\"sar_max_w_per_kg\", _sar_max])\n"
                "        _sw.writerow([\"sar_max_w_per_kg_per_1w_acc\",\n"
                "                      (_sar_max / _p_acc) if _p_acc > 0 else "
                "float('nan')])\n"
                "except Exception as _sare:\n"
                "    print(\"rfauto SAR 链失败（不阻塞 S 参数）:\", _sare)\n"
            )

    # 囚禁模定位对照（wf:varactor-locate）：板边覆盖字面量（缺省 60e-3
    # 逐字节不变）+ 几何容纳守卫——板边必须满足端口测量面在板内：
    # MeasPlaneShift=(XS±BOARD)−10·NEAR−4·H_SUB>0 → BOARD > reach+12·NEAR+4·H_SUB
    if _knob_board_m is not None:
        _reach = max([abs(v) for v in list(near_x) + list(near_y)] or [0.0])
        _b_min = _reach + 12 * near_m + 4 * h_m
        if _knob_board_m <= _b_min:
            raise ValueError(
                f"_board_mm={_knob_board_m * 1e3:g}mm ≤ 几何可达 "
                f"{_reach * 1e3:g}mm+12*NEAR+4*H_SUB={_b_min * 1e3:g}mm"
                "——板边必须包住全部走线且端口测量面（MeasPlaneShift）为正")
        _board_txt = repr(_knob_board_m)
    else:
        _board_txt = "60e-3"

    # 域半宽文本：缺省=BOARD 共享字面量（逐字节不变）；siw 矩形域由 layout
    # 字面注入（BOARD=60mm 对 SIW 自动档 ~20M cells 超预算，criteria §2）
    _dom_x_txt = "BOARD + AIR_SIDE"
    _dom_y_txt = "BOARD + AIR_SIDE"
    if template == "siw":
        _dom_x_txt = repr(params["_siw_layout"]["dom_x"])
        _dom_y_txt = repr(params["_siw_layout"]["dom_y"])
    elif template == "sicl":
        # sicl 矩形域（round15 TA-3）：过孔墙外平行板泄漏区截断 + 端口面出
        # PML_8（layout 单源字面注入，siw 同口径）
        _dom_x_txt = repr(params["_sicl_layout"]["dom_x"])
        _dom_y_txt = repr(params["_sicl_layout"]["dom_y"])
    elif template == "msl_siw_taper":
        _dom_x_txt = repr(params["_msl_siw_taper_layout"]["dom_x"])
        _dom_y_txt = repr(params["_msl_siw_taper_layout"]["dom_y"])
    elif template == "hmsiw":
        # hmsiw 矩形域（TA-8）：开路边 MUR 余量+藩篱端孔吸收（layout 单源
        # 字面注入，siw 同口径）
        _dom_x_txt = repr(params["_hmsiw_layout"]["dom_x"])
        _dom_y_txt = repr(params["_hmsiw_layout"]["dom_y"])
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单胞：域=单胞方形截面（period/2，layout 单源）
        _dom_x_txt = repr(params["_ms_layout"]["dom_x"])
        _dom_y_txt = repr(params["_ms_layout"]["dom_y"])

    # wf:nrts-fix：F-D 模板 Run 前 NrTS 终网格折算块（非 F-D 模板=空串逐字节
    # 不变）；置于 body 之后、FDTD.Run 之前=终网格点（body 可能补线，#311）
    _fd_nrts_block = (
        _fd_nrts_override_block(_fd_max_time_ns) if _fd_max_time_ns else "")

    return f'''#!/usr/env/python3
"""openEMS script (rfauto {template} template auto-generated, official-method mesh)."""
import csv
import os

# CSXCAD/openEMS 扩展模块的依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里，
# 必须 add_dll_directory（仅 os.environ PATH 会 ImportError: DLL load
# failed——2026-09-03 审计实测）。目录可用 RFAUTO_OPENEMS_BIN 覆盖。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\openEMS\\install\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
# LumpedElement 隔离电阻走 CSXCAD 原语 CSX.AddLumpedElement（模板内联），
# 不从 openEMS.ports 导入（该模块并无 LumpedElement，导入即崩——审计实测）
from openEMS.ports import LumpedPort, MSLPort{extra_ports_import}{_debye_import}

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {near_m!r}   # {'近走线区 = base/4（官方口径）' if _knob_near_ratio == 4 else f'近走线区 = base/{_knob_near_ratio:g}（_near_ratio 旋钮）'}
CSV_NAME = "sparams.csv"
SIM_PATH = __import__("os").path.abspath("fdtd")
# 绑定库运行中可能改写解释器 cwd：CSV 一律写脚本自身目录（绝对路径），
# 否则产物静默落到进程启动目录（2026-09-03 审计实测踩坑）
CSV_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    CSV_NAME)

# ── 仿真环境：官方 MSL_NotchFilter 教程方法学（2026-09-04 频率尺度根因
# 实验后定稿；旧版 λ/20@空气粗网格 + 有限小板使 λ/4 谷位系统性低 30-40%
# 且随网格漂移，证据链 runs/audit_freq_scale/ E1-E4）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS={_nrts!r}{_end_criteria_src}{', CellConstantMaterial=1' if sar else ''})   # 官方口径：不设 EndCriteria，默认能量判据停机{'；EndCriteria=显式停机判据（_end_criteria 旋钮）' if _end_criteria_src else ''}{'；CellConstantMaterial=1 = 官方 SAR 要求（每 Yee 元单值材料）' if sar else ''}
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 端口面所在轴 PML_8（官方），z 底 {bottom_bc}{'_（自由空间，无地）' if is_free_space else ' 当地面（官方）'}，其余 MUR
FDTD.SetBoundaryCond(["{b_x0}", "{b_x1}", "{b_y0}", "{b_y1}", "{bottom_bc}", "{top_bc}"])

AIR_TOP = {air_top!r}     # 辐射器件 λ0/4，guided 5mm
AIR_SIDE = {air_side!r}   # 辐射器件侧向空气隙，guided 0（基板顶到边界）

mesh = CSX.GetGrid()
BOARD = {_board_txt}   # 板边（端口面/基板边缘）= guided 模板域边界
DOM_X = {_dom_x_txt}
DOM_Y = {_dom_y_txt}

def _axis(ax: str, near_pts, dom_lo, dom_hi) -> None:
    """官方网格配方：走线近场 NEAR 精细区 + 全轴 BASE 渐变（SmoothMesh）。"""
    for p in near_pts:
        mesh.AddLine(ax, p)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_near_x = {fmt_list(near_x)}
_near_y = {fmt_list(near_y)}
_axis("x", _near_x, -DOM_X, DOM_X)
_axis("y", _near_y, -DOM_Y, DOM_Y)
{z_mesh_block}# 近重合网格线守卫：浮点误差线可能只差 nm~µm 级，把时间步压塌
# （2026-09-03 B 点审计实测）。平滑后按最小间距 1µm 去重。
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

{substrate_block}{body}
{sar_setup_block}{ff_setup_block}{field_dump_block}{_fd_nrts_block}
# cleanup：清掉同目录旧 run 的 port/et 输出——不清理时 CalcPort 会读到
# 上一版结构的旧信号文件，S 参数静默变 NaN（实测踩坑）
FDTD.Run(SIM_PATH, verbose=0, {_run_kwargs}cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
# 官方 MSL_NotchFilter 口径：CalcPort 显式 ref_impedance=50；透射 S21 取
# port2 的 uf_ref（=到达 port2 的行波）。注意 uf_ref/uf_inc 的相位含端口
# 分解伪象，只能用幅值与 β（CalcPort 自算）做物理判读（E3 实测）。
_port1.CalcPort(SIM_PATH, f, ref_impedance={z_ref_txt})
_S21_FILLER = False
try:
    _port2.CalcPort(SIM_PATH, f, ref_impedance={z_ref_txt})
    S21 = _port2.uf_ref / _port1.uf_inc
except Exception:
    S21 = _port1.uf_ref / _port1.uf_inc  # single-port fallback
    _S21_FILLER = True
S11 = _port1.uf_ref / _port1.uf_inc
{ff_calc_block}{beta_block}
_LOOP_DONE = False
{s31_block}{loop_block}if not _LOOP_DONE:
    with open(CSV_PATH, "w", newline="") as fh:
        w = csv.writer(fh)
        if S31 is not None and S23 is not None:
            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                        "re_S31", "im_S31", "re_S23", "im_S23"])
            for i, fi in enumerate(f):
                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real,
                            S21[i].imag, S31[i].real, S31[i].imag,
                            S23[i].real, S23[i].imag])
        else:
            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
            for i, fi in enumerate(f):
                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real, S21[i].imag])
    # sparams.mask.json sidecar（H-01 B 案，W6-E）：default 分支掩码运行时
    # 按实际产物形态落盘（9 列双激励 vs 5 列单激励；port2 CalcPort 失败时
    # S21 列=S11 逐位副本（R6-4 实测）→ filler_columns 如实标记不冒充测量）。
    _S21_MEASURED = not _S21_FILLER
    if S31 is not None and S23 is not None:
        _mask_doc = {{"schema_version": "1", "n_ports": 3, "excite_port": 1,
                      "measured_mask": [[True, False, False], [True, False, True],
                                        [True, False, False]],
                      "filler_columns": {{}},
                      "reciprocity_filled": [[2, 1]],
                      "symmetry_filled": []}}
    else:
        _mask_doc = {{"schema_version": "1", "n_ports": 2, "excite_port": 1,
                      "measured_mask": [[True, False], [_S21_MEASURED, False]],
                      "filler_columns": ({{'S21': 'S11_copy'}}
                                         if not _S21_MEASURED else {{}}),
                      "reciprocity_filled": ([[0, 1]] if _S21_MEASURED else []),
                      "symmetry_filled": [[1, 1]]}}
    with open(CSV_PATH.replace("sparams.csv", "sparams.mask.json"), "w",
              encoding="utf-8") as _mask_fh:
        import json as _mask_json
        _mask_json.dump(_mask_doc, _mask_fh, ensure_ascii=False, indent=1)
print("rfauto openEMS simulation done")
'''
