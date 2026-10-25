"""Wilkinson 功分器——声明式 EDB spec 发射器（数据集 EDB 快车道）。

拓扑：T 结两等分 Wilkinson（与 HFSS 插件 ``models/wilkinson_power_divider
plugin`` 同布局口径，Y 正向=输入方向）::

                 P1(输入, y=+in_len)
                    │ trace_input（50Ω, shunt_w）
                    │
      ──────────────┴────────────── trace_junction（横杆, series_w）
      │                              │
      │ trace_arm2（70.7Ω λ/4）      │ trace_arm1（70.7Ω λ/4）
      │                              │
      ├──[ RISO = 2·Z0 = 100Ω ]──────┤   ← spec["resistors"]（臂端内侧壁间）
      │                              │
      │ trace_out2（50Ω）            │ trace_out1（50Ω）
   P3(左出)                        P2(右出)

尺寸全部由 core.synthesis 闭式综合产出（禁止手抄毫米数）：
  - series_w（70.7Ω=Z0·√2 臂）与 shunt_w（50Ω 馈线）= inverse_width HJ 反解；
  - arm_len = λg/4 @ 臂线宽自身 εeff（XA-3 迭代序，与 synthesize_wilkinson
    同式同源：inverse_width → forward_media(εeff) → c/(4·f0·√εeff)）；
  - 隔离电阻 R = 2·Z0 = 100Ω（闭式，非手抄）。

几何与 HFSS 插件的差异（planar 口径，均为本层声明假设）：
  - HFSS 插件的隔离电阻是竖片（XZ 面，跨铜厚、距臂端 resistor_offset 缩进）；
    EDB planar 用共面矩形（两臂端内侧壁之间、中心线过 y=-arm_len）——
    集总 R 值相同，纵向位置差为二阶效应；
  - T 结横杆以走线矩形重叠实现连通（HFSS 插件为 junction 盒 + unite）。

隔离电阻发射纪律（schema.py 假设 5）：pyedb configuration 0.83 无
lumped-RLC 段 → 电阻只在 spec["resistors"] 声明（几何 + r_ohm），
**不发进 config_json modeler**（防 adapter 逐字套用 config 时变金属短路）；
edb_adapter 负责按 spec 用 pedb lumped RLC 边界落地。

纯函数：``emit_power_divider_spec(params) -> (spec, config_json)``，无 IO
无全局态；结构常量 in_len/out_len 与 HFSS 插件固定参数同口径
（10.0/5.0 mm）；**gap 缺省 6.0 mm 与插件口径 2.0 有意分叉**——EDB/3D
Layout 波端口物理片宽=水平扩展因子 5×线宽（50Ω 馈线约 5.57mm@缺省
层叠），两输出口中心距 2.0mm 时 P2/P3 端口片互相交叠，AEDT 网格生成
失败 rc=103（``Port#Port2 intersects mesh body: Port#Port3``，W1 真机
冒烟实证 2026-10-09，内部证据档 REPORT §3.3）。

渲染期守卫（#347 家法）：发射时按 ``gap_mm ≤ 因子×shunt_w + 浮点余量``
fail-fast 抛 ValueError，报错带建议放宽值（最小可行间隙上取 0.5mm 网格
+5% 工程余量）；守卫因子从发射端口自带的 ``horizontal_extent_factor``
读取（与 schema.make_wave_port 单源，不另立字面量）。

门语义落档（W1 冒烟门语义仲裁 2026-10-09，同 REPORT §3.2）：本族已在
``service/edb_health_gate.S_WINDOW_DB_BY_TEMPLATE`` 登记 |S21|/|S31|@f0
等分分配窗 **[-3.8, -2.5] dB**（双边界闭区间，两腿各自落窗内才算过）：
理想等分分配损耗 -3.01dB，下界=3dB 分配+0.8dB 实现容差（健康实测
-3.19/-3.26 有余量），上界排除异常增益/提取伪象——冒烟任务书字面门
"各 ≤-3.8dB" 是单边下界语义错位，会误杀任何健康功分器，已按窗语义
裁定替换。名义参数口径与已注册 wilkinson 模板（models/template_specs
"wilkinson" 行 + synthesize_wilkinson）同综合单源——一致性由
tests/unit/test_edb_templates.py 对照钉住（舍入档容差）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.adapters.edb_templates.schema import (
    DEFAULT_BOARD_MARGIN_MM,
    DEFAULT_COPPER_THICKNESS_MM,
    SPEC_SCHEMA_VERSION,
    assemble_config,
    board_from_traces,
    build_spec_stackup,
    make_trace,
    make_wave_port,
    quarter_wave_len_mm,
    resolve_stackup,
    solve_microstrip,
    validate_spec,
)

__all__ = ["emit_power_divider_spec"]

#: 固定结构参数：in_len/out_len 与 wilkinson HFSS 插件 set_variables 固定
#: 项同口径；gap 缺省 6.0mm 与插件口径 2.0 有意分叉（波端口扩展因子 5
#: 下端口片宽 5×shunt_w≈5.57mm@缺省层叠 > 2.0mm，P2/P3 端口片交叠
#: → AEDT rc=103，W1 真机冒烟实证；2.0mm 缺省 emit 现被渲染期守卫拦下，
#: 报错自带建议放宽值）。不足值的最低可行界=因子×shunt_w（见发射器守卫）。
DEFAULT_GAP_MM = 6.0       # 两臂中心距（波端口扩展守卫约束下的缺省）
DEFAULT_IN_LEN_MM = 10.0   # 输入馈线长
DEFAULT_OUT_LEN_MM = 5.0   # 输出馈线长

#: 守卫浮点余量（#347 家法：恰等/近恰等也会炸——比较留相对余量，
#: gap == 因子×w 的边界值同样拦下）。
_GAP_GUARD_REL_EPS = 1e-6

#: 守卫建议放宽值的工程余量（最小可行间隙 ×1.05 后上取 0.5mm 网格，
#: 缺省层叠下建议值恰为 6.0mm=W1 冒烟实证可用值）。
_GAP_SUGGEST_HEADROOM = 1.05
_GAP_SUGGEST_GRID_MM = 0.5


def emit_power_divider_spec(
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Wilkinson 功分器发射器：设计参数 dict → (spec dict, config_json dict)。

    Args:
        params: 设计参数。
            - ``f0_ghz``（必填，>0）：中心频率。
            - ``z0_ohm``（缺省 50.0）：系统阻抗；仅支持 50（假设 3）。
            - ``stackup``（缺省 rogers4350b_h0.508 标量，假设 7）。
            - ``gap_mm``（缺省 6.0）/ ``in_len_mm``（缺省 10.0）/
              ``out_len_mm``（缺省 5.0）：结构常量（in/out 与 HFSS 插件
              同口径；gap 受波端口扩展守卫约束，见下）。
            - ``copper_thickness_mm``（缺省 0.035）/ ``board_margin_mm``
              （缺省 2.0）。
            - ``sweep`` / ``adapt``：同 branchline（缺省 [0.7,1.3]·f0、
              401 点、单频 f0 adapt，假设 8）。

    Returns:
        (spec, config_json) 二元组；config_json 为 PyEDB
        ``edb.configuration.load()`` 兼容 dict。内部 validate_spec 自检，
        失败抛 ValueError。

    Raises:
        ValueError: f0 缺失/非法、z0_ohm != 50、gap_mm 不足波端口扩展
            守卫（``gap_mm ≤ horizontal_extent_factor×shunt_w``，报错带
            建议放宽值）、综合回代不自洽或 spec 自检失败。
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
    gap_mm = float(params.get("gap_mm", DEFAULT_GAP_MM))
    in_len_mm = float(params.get("in_len_mm", DEFAULT_IN_LEN_MM))
    out_len_mm = float(params.get("out_len_mm", DEFAULT_OUT_LEN_MM))
    copper_t = float(params.get("copper_thickness_mm", DEFAULT_COPPER_THICKNESS_MM))
    margin_mm = float(params.get("board_margin_mm", DEFAULT_BOARD_MARGIN_MM))
    if gap_mm <= 0.0 or in_len_mm <= 0.0 or out_len_mm <= 0.0:
        raise ValueError(
            f"gap/in_len/out_len 必须为正: gap={gap_mm}, in={in_len_mm}, out={out_len_mm}"
        )

    stackup = resolve_stackup(params.get("stackup"))
    # 综合链（core.synthesis 同引擎同序）：臂宽 HJ 反解 → 臂长 λ/4@臂 εeff
    series_w, eps_series = solve_microstrip(z0_ohm * math.sqrt(2.0), f0_ghz, stackup)
    shunt_w, eps_shunt = solve_microstrip(z0_ohm, f0_ghz, stackup)
    arm_len = quarter_wave_len_mm(f0_ghz, eps_series)
    iso_r = 2.0 * z0_ohm  # Wilkinson 隔离电阻闭式（Pozar §7.3）

    half_g = gap_mm / 2.0
    y_end = -arm_len
    y_out = -arm_len - out_len_mm
    traces = [
        make_trace("trace_input", shunt_w, [[0.0, 0.0], [0.0, in_len_mm]], "feed"),
        make_trace("trace_junction", series_w, [[-half_g, 0.0], [half_g, 0.0]], "junction"),
        make_trace("trace_arm1", series_w, [[half_g, 0.0], [half_g, y_end]], "series_arm"),
        make_trace("trace_arm2", series_w, [[-half_g, 0.0], [-half_g, y_end]], "series_arm"),
        make_trace("trace_out1", shunt_w, [[half_g, y_end], [half_g, y_out]], "feed"),
        make_trace("trace_out2", shunt_w, [[-half_g, y_end], [-half_g, y_out]], "feed"),
    ]
    # 隔离电阻：共面矩形连接两臂端内侧壁（中心线过臂端 y=-arm_len）。
    # 只进 spec["resistors"]（schema 假设 5），config 不发金属。
    resistors = [
        {
            "name": "RISO",
            "layer": "TOP",
            "net": "RF",
            "r_ohm": iso_r,
            "width_mm": series_w,  # 电阻体宽=臂宽（集总边界，纵横比二阶）
            "path_mm": [
                [-(half_g - series_w / 2.0), y_end],
                [half_g - series_w / 2.0, y_end],
            ],
            "role": "isolation_resistor",
        }
    ]
    ports = [
        make_wave_port("P1", 1, "trace_input", [0.0, in_len_mm]),
        make_wave_port("P2", 2, "trace_out1", [half_g, y_out]),
        make_wave_port("P3", 3, "trace_out2", [-half_g, y_out]),
    ]

    # 波端口扩展守卫（fail-fast，#347 家法留浮点余量）：真实端口片宽=
    # 水平扩展因子×线宽（因子从发射端口自带声明读取，与
    # schema.make_wave_port 单源）。两输出口 P2/P3 中心距=gap_mm，端口片
    # 不互相交叠要求 gap_mm ≥ 因子×shunt_w——缺省 2.0mm 违背此界时 AEDT
    # 网格生成失败 rc=103（"Port#Port2 intersects mesh body: Port#Port3"，
    # W1 真机冒烟实证 2026-10-09）。恰等/近恰等边界同样拦下（浮点余量
    # _GAP_GUARD_REL_EPS，#347：恰等会炸）。
    extent = max(int(p["horizontal_extent_factor"]) for p in ports)
    min_gap_mm = extent * shunt_w
    if gap_mm <= min_gap_mm * (1.0 + _GAP_GUARD_REL_EPS):
        suggest_mm = math.ceil(
            min_gap_mm * _GAP_SUGGEST_HEADROOM / _GAP_SUGGEST_GRID_MM
        ) * _GAP_SUGGEST_GRID_MM
        raise ValueError(
            f"gap_mm={gap_mm:.4g} 不足：波端口水平扩展因子 {extent} 下"
            f" P2/P3 端口片宽={min_gap_mm:.3f}mm（因子×50Ω 馈线宽），"
            "两输出口端口片将互相交叠（AEDT 网格生成失败 rc=103，W1"
            " 真机冒烟实证）——请放宽 gap_mm ≥ "
            f"{suggest_mm:g}mm"
        )

    sweep = params.get("sweep") or {}
    sweep_spec = {
        "name": "sweep1",
        "type": str(sweep.get("type", "interpolation")),
        "start_ghz": float(sweep.get("start_ghz", 0.7 * f0_ghz)),
        "stop_ghz": float(sweep.get("stop_ghz", 1.3 * f0_ghz)),
        "points": int(sweep.get("points", 401)),
    }
    adapt = params.get("adapt") or {}
    sim_setup = {
        "f0_ghz": f0_ghz,
        "sweep": sweep_spec,
        "adapt": {
            "max_passes": int(adapt.get("max_passes", 20)),
            "max_delta": float(adapt.get("max_delta", 0.02)),
        },
    }

    spec: dict[str, Any] = {
        "template": "edb_power_divider",
        "schema_version": SPEC_SCHEMA_VERSION,
        "units": {"length": "mm", "frequency": "GHz"},
        "params": {
            "f0_ghz": f0_ghz,
            "z0_ohm": z0_ohm,
            "z_series_ohm": z0_ohm * math.sqrt(2.0),
            "arm_len_mm": arm_len,
            "series_w_mm": series_w,
            "shunt_w_mm": shunt_w,
            "eps_eff_series": eps_series,
            "eps_eff_shunt": eps_shunt,
            "iso_r_ohm": iso_r,
            "gap_mm": gap_mm,
            "in_len_mm": in_len_mm,
            "out_len_mm": out_len_mm,
            "copper_thickness_mm": copper_t,
            "board_margin_mm": margin_mm,
            "synthesis_source": "core.synthesis inverse_width/forward_media"
                                "（与 synthesize_wilkinson 同引擎同序）",
            "port_roles": "P1 输入/P2 右出/P3 左出（等分 -3dB，RISO=2·Z0 隔离）",
        },
        "stackup": build_spec_stackup(stackup, copper_t),
        "traces": traces,
        "vias": [],
        "resistors": resistors,
        "ports": ports,
        "board": board_from_traces(traces, margin_mm),
        "sim_setup": sim_setup,
    }
    errors = validate_spec(spec)
    if errors:
        raise ValueError(f"power_divider spec 自检失败: {errors}")
    return spec, assemble_config(spec)
