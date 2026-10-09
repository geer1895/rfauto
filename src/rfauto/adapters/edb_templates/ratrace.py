"""Rat-race 环形电桥（hybrid ring）——声明式 EDB spec 发射器。

拓扑：环形电桥 = 特征阻抗 √2·Z0 的闭合环传输线、周长 1.5λg（环线自身
εeff），四端口按环弧位接入：Σ=弧位 0、out1=+λ/4、out2=−λ/4、Δ=+λ/2
（环相位 90°/−90°/180°；与注册 openEMS 模板
``oe_templates/render_ratrace_cyl._ratrace_lines`` 规范角位 Σ=0°/out1=
60°/Δ=120°/out2=300° 同弧位口径——geo 60°×1.5λ 环=弧 λ/4，geo 240° 弧位
=λ≡环相位 0° 回到 Σ，故 Δ 只能在 geo 120°/+λ/2 弧位）。

EDB 平面族几何纪律=全轴对齐两点线段（schema 假设 4），圆环不可表示——
本发射器用**方形环**（同周长同弧位的拓扑等价实现）：中心线周长
P=1.5λg 精确（电长度零偏差）、边长 S=P/4，端口位置按中心线弧长精确定位
（Σ=右边中点、out1/out2=±λ/4 弧位、Δ=+λ/2 弧位）；圆→方的形状偏差只剩
四个 90° 拐角不连续（未切角 miter）——与 branchline 发射器矩形环四拐角
同类二阶效应（branchline 口径已 HFSS 仲裁背书），冒烟判读按引擎偏差项
对待、不进闭式裁判::

      P2(out1) ←── feed_p2          feed_p3 ──→ P3(Δ，Σ 激励时隔离)
                   └────── side_top ────────┘
                   │                       │
         side_left（√2·Z0 环带）    side_right（√2·Z0 环带）
                   │                       │
                   └────── side_bottom ────┘
      P1(Σ 输入) ←── feed_p1（右边中点水平引出）    feed_p4 ↓ P4(out2）

行为（与注册模板同口径）：Σ 激励 → out1/out2 各 −3dB 同相；Σ↔Δ 隔离；
out1↔out2 互隔离；Δ 激励 → out1/out2 等分反相（180° 差）。

环带在四个端口接入点处分段（side_right_low/high、side_top_e/mid/w、
side_bottom_e/w、side_left 共 8 段）：接入点=相邻段共享端点（端点-重合
=双向附着边，走 trace_attach_graph/trace_connected_components 冻结底座）；
分段只是矩形划分，并集几何与整环逐点一致，中心线弧长不变。

尺寸全部由 core.synthesis 闭式综合产出（禁止手抄毫米数 #252；与注册
ratrace 模板综合函数 ``synthesize_ratrace_model`` 同式同源——该函数经
``Stackup.from_materials_yaml`` 读档属 IO，发射器零 IO 契约下以同序闭式
复刻，一致性由 tests/unit/test_edb_templates_ext.py 对照钉舍入档）：
  - z_ring = √2·Z0（70.7Ω@50Ω，多来源确证）；
  - w_ring = inverse_width(z_ring)（HJ 反解，同 wilkinson 臂手法）；
  - εeff_ring = forward_media(w_ring)；
  - λg = c/(f0·√εeff_ring)（=4·λg/4，quarter_wave_len_mm 同常数单源）、
    周长 P = 1.5·λg、边长 S = P/4；
  - w_feed = solve_microstrip(Z0)（50Ω 单源，与 nominal_width_mm 逐位）。

族特异性 schema 豁免（本发射器声明并过滤，schema.py 正本逻辑不改动）：
template 白名单未扩（本席只许追加 schema.py docstring），validate_spec 的
"template 非法" 行由发射器侧过滤；白名单升格（KNOWN_TEMPLATES +
edb_lane_service 分派表接线）为 followUp。环+四馈线单连通，其余审计面
（端点附着图/board 覆盖/端口落位）全量走 validate_spec 正本。

纯函数：``emit_ratrace_spec(params) -> (spec, config_json)``，无 IO 无
全局态；spec/config schema 与假设清单见 edb_templates/schema.py docstring。
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

__all__ = ["DEFAULT_FEED_LEN_MM", "emit_ratrace_spec"]

#: 缺省馈线长度 mm（与 branchline 发射器 DEFAULT_FEED_LEN_MM 同口径）
DEFAULT_FEED_LEN_MM = 5.0

#: 本族 validate_spec 豁免行前缀（template 白名单升格 followUp，见 docstring）
_FAMILY_VALIDATE_EXEMPT_PREFIXES = ("template 非法:",)


def emit_ratrace_spec(
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rat-race 环形电桥发射器：设计参数 dict → (spec dict, config_json dict)。

    Args:
        params: 设计参数。
            - ``f0_ghz``（必填，>0）：中心频率。
            - ``z0_ohm``（缺省 50.0）：系统阻抗；仅支持 50（假设 3）。
            - ``stackup``（缺省 rogers4350b_h0.508 标量，假设 7）。
            - ``feed_len_mm``（缺省 5.0）：四条 50Ω 馈线长。
            - ``copper_thickness_mm``（缺省 0.035）/ ``board_margin_mm``
              （缺省 2.0）。
            - ``sweep`` / ``adapt``：同 branchline（缺省 [0.7,1.3]·f0、
              401 点、单频 f0 adapt，假设 8）。

    Returns:
        (spec, config_json) 二元组；config_json 为 PyEDB
        ``edb.configuration.load()`` 兼容 dict。内部 validate_spec 自检
        （族豁免见模块 docstring），失败抛 ValueError。

    Raises:
        ValueError: f0 缺失/非法、z0_ohm != 50、feed_len 非正、综合回代
            不自洽或 spec 自检失败。
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
    feed_len_mm = float(params.get("feed_len_mm", DEFAULT_FEED_LEN_MM))
    copper_t = float(params.get("copper_thickness_mm", DEFAULT_COPPER_THICKNESS_MM))
    margin_mm = float(params.get("board_margin_mm", DEFAULT_BOARD_MARGIN_MM))
    if feed_len_mm <= 0.0:
        raise ValueError(f"feed_len_mm 必须为正: {feed_len_mm}")

    stackup = resolve_stackup(params.get("stackup"))
    # 综合链（synthesize_ratrace_model 同式同序，零 IO 复刻见模块 docstring）
    z_ring = math.sqrt(2.0) * z0_ohm
    w_ring, eps_ring = solve_microstrip(z_ring, f0_ghz, stackup)
    lam_g = 4.0 * quarter_wave_len_mm(f0_ghz, eps_ring)  # c/(f0·√εeff)，mm
    perimeter = 1.5 * lam_g
    side = perimeter / 4.0
    w_feed, _eps_feed = solve_microstrip(z0_ohm, f0_ghz, stackup)  # 50Ω 单源
    if min(w_ring, lam_g, perimeter, side, w_feed) <= 0.0:
        raise ValueError(
            f"综合几何须 >0: w_ring={w_ring}, λg={lam_g}, side={side}, "
            f"w_feed={w_feed}"
        )

    # 几何：方形环（中心线周长 P=1.5λg 精确）+ 四馈线。中心线半边长 h=P/8；
    # 端口弧位（自 Σ 沿环中心线计量）：out1/out2=±λ/4 → 坐标 (±λg/8, ±h)
    # 镜像；Δ=+λ/2 → (−λg/8, +h)；Σ=(h, 0)。环带在端口接入点**分段**（接入
    # 点=相邻段共享端点，端点-重合=双向附着边——trace_attach_graph 端点-
    # 重合语义，Σ/端口.mid-span 单向附着会让冻结的连通分量底座漏并；分段
    # 只是矩形划分，并集几何与整环逐点一致）；馈线自接入点沿边中心线向外
    # 引出（馈线矩形跨接入点、与两侧环带段各 (w_ring/2)×(wf/2) 面积重叠
    # =连通，flat cap）。
    half = side / 2.0
    off = lam_g / 8.0
    traces = [
        make_trace("side_right_low", w_ring, [[half, -half], [half, 0.0]], "ring"),
        make_trace("side_right_high", w_ring, [[half, 0.0], [half, half]], "ring"),
        make_trace("side_top_e", w_ring, [[half, half], [off, half]], "ring"),
        make_trace("side_top_mid", w_ring, [[off, half], [-off, half]], "ring"),
        make_trace("side_top_w", w_ring, [[-off, half], [-half, half]], "ring"),
        make_trace("side_left", w_ring, [[-half, half], [-half, -half]], "ring"),
        make_trace("side_bottom_w", w_ring, [[-half, -half], [off, -half]], "ring"),
        make_trace("side_bottom_e", w_ring, [[off, -half], [half, -half]], "ring"),
        make_trace("feed_p1", w_feed, [[half, 0.0], [half + feed_len_mm, 0.0]], "feed"),
        make_trace("feed_p2", w_feed, [[off, half], [off, half + feed_len_mm]], "feed"),
        make_trace("feed_p3", w_feed, [[-off, half], [-off, half + feed_len_mm]], "feed"),
        make_trace("feed_p4", w_feed, [[off, -half], [off, -half - feed_len_mm]], "feed"),
    ]
    ports = [
        make_wave_port("P1", 1, "feed_p1", [half + feed_len_mm, 0.0]),
        make_wave_port("P2", 2, "feed_p2", [off, half + feed_len_mm]),
        make_wave_port("P3", 3, "feed_p3", [-off, half + feed_len_mm]),
        make_wave_port("P4", 4, "feed_p4", [off, -half - feed_len_mm]),
    ]

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
        "template": "edb_ratrace",
        "schema_version": SPEC_SCHEMA_VERSION,
        "units": {"length": "mm", "frequency": "GHz"},
        "params": {
            "f0_ghz": f0_ghz,
            "z0_ohm": z0_ohm,
            "z_ring_ohm": z_ring,
            "w_ring_mm": w_ring,
            "eps_eff_ring": eps_ring,
            "lam_g_mm": lam_g,
            "perimeter_mm": perimeter,
            "side_mm": side,
            "r_ring_equivalent_mm": perimeter / (2.0 * math.pi),
            "w_feed_mm": w_feed,
            "feed_len_mm": feed_len_mm,
            "copper_thickness_mm": copper_t,
            "board_margin_mm": margin_mm,
            "synthesis_source": "core.synthesis inverse_width/forward_media 闭式"
                                "复刻（与注册 ratrace 模板 synthesize_ratrace_"
                                "model 同式同序：环阻抗 √2·Z0、周长 1.5λg、"
                                "R=P/2π 对照口径）；w_feed=solve_microstrip "
                                "50Ω 单源",
            "port_roles": "P1 Σ（和端口，输入）/P2 out1/P4 out2——Σ 激励"
                          "各 −3dB 同相；P3 Δ（差端口）——Σ 激励时隔离、"
                          "Δ 激励时 out1/out2 等分反相；out1↔out2 互隔离",
            "topology_note": "方形环拓扑等价实现（轴对齐纪律）：周长 1.5λg 与"
                             "端口弧位（0/±λ/4/+λ/2）精确，圆→方偏差=四拐角"
                             "不连续（未 miter，与 branchline 矩形环同类二阶"
                             "效应）；弧位口径与注册 openEMS ratrace 模板"
                             "（Σ=0°/out1=60°/Δ=120°/out2=300°）一致",
        },
        "stackup": build_spec_stackup(stackup, copper_t),
        "traces": traces,
        "vias": [],
        "resistors": [],
        "ports": ports,
        "board": board_from_traces(traces, margin_mm),
        "sim_setup": sim_setup,
    }
    # 自检：validate_spec 正本逻辑不动，族豁免行由发射器侧过滤
    errors = [e for e in validate_spec(spec)
              if not e.startswith(_FAMILY_VALIDATE_EXEMPT_PREFIXES)]
    if errors:
        raise ValueError(f"ratrace spec 自检失败: {errors}")
    return spec, assemble_config(spec)
