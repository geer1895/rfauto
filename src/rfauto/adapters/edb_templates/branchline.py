"""Branchline 3dB 定向耦合器——声明式 EDB spec 发射器（数据集 EDB 快车道）。

拓扑：标准角馈 branchline（与 openEMS 渲染器 ``oe_templates/render_tl.py
_branchline_lines`` 同一布局口径，对照 Microwaves101/PMC）——矩形环四臂 +
四角 50Ω 馈线，端口全部经馈线引出到板内自由端（wave_port 落馈线端点）::

      P4(隔离) ←── feed_p4        feed_p3 ──→ P3(耦合)
                   └── arm_top（series 35.35Ω λ/4）──┘
                        │                        │
                 arm_left（shunt 50Ω λ/4）  arm_right（shunt 50Ω λ/4）
                        │                        │
                   └── arm_bottom（series 35.35Ω λ/4）──┘
      P1(输入) ←── feed_p1        feed_p2 ──→ P2(直通)

端口语义（与 linkage.field_circuit_anchor.branchline_smatrix 一致）：
串联臂 1-2 / 4-3（横臂 series_w=Z0/√2），并联臂 1-4 / 2-3（竖臂
shunt_w=Z0）；S21=直通、S31=耦合、S41=隔离。

尺寸全部由 core.synthesis 闭式综合产出（禁止手抄毫米数）：
  - series_w  = inverse_width(Z0/√2)（HJ 反解，35.35Ω 串联臂）；
  - shunt_w   = inverse_width(Z0)（50Ω 并联臂/馈线，50Ω 宽单源口径）；
  - series_len/shunt_len = λg/4 @ 各臂自身线宽的 εeff（XA-3 迭代序：
    inverse_width → forward_media(εeff) → c/(4·f0·√εeff)，两臂 εeff 差数
    个百分点故矩形环异臂长——与 synthesize_branchline 同式同源）。

纯函数：``emit_branchline_spec(params) -> (spec, config_json)``，无 IO 无
全局态；spec/config schema 与假设清单见 edb_templates/schema.py docstring。
名义参数口径与已注册 branchline 模板（models/template_specs "branchline"
行 + synthesize_branchline）同综合单源——一致性由
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

__all__ = ["emit_branchline_spec"]

#: 缺省馈线长度 mm（与 branchline HFSS 插件固定结构参数 feed_len 同口径）
DEFAULT_FEED_LEN_MM = 5.0


def emit_branchline_spec(params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Branchline 耦合器发射器：设计参数 dict → (spec dict, config_json dict)。

    Args:
        params: 设计参数。
            - ``f0_ghz``（必填，>0）：中心频率。
            - ``z0_ohm``（缺省 50.0）：系统阻抗；仅支持 50（假设 3）。
            - ``stackup``（缺省 rogers4350b_h0.508 标量，假设 7）：
              ``{"name", "epsilon_r", "thickness_mm", "loss_tangent"}``。
            - ``feed_len_mm``（缺省 5.0）：四角馈线长。
            - ``copper_thickness_mm``（缺省 0.035）。
            - ``board_margin_mm``（缺省 2.0）：地板/基板相对走线足迹外扩。
            - ``sweep``（缺省 [0.7, 1.3]·f0、401 点 interpolation，假设 8）：
              ``{"start_ghz", "stop_ghz", "points", "type"}``。
            - ``adapt``（缺省单频 f0、20 passes、ΔS=0.02）：
              ``{"max_passes", "max_delta"}``。

    Returns:
        (spec, config_json) 二元组；config_json 为 PyEDB
        ``edb.configuration.load()`` 兼容 dict。内部先 validate_spec 自检，
        校验失败抛 ValueError（发射器不产出带病 spec）。

    Raises:
        ValueError: f0 缺失/非法、z0_ohm != 50、综合回代不自洽或 spec
            自检失败。
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

    stackup = resolve_stackup(params.get("stackup"))
    # 综合链（core.synthesis 同引擎同序）：臂宽 HJ 反解 → 臂长 λ/4@自身 εeff
    series_w, eps_series = solve_microstrip(z0_ohm / math.sqrt(2.0), f0_ghz, stackup)
    shunt_w, eps_shunt = solve_microstrip(z0_ohm, f0_ghz, stackup)
    series_len = quarter_wave_len_mm(f0_ghz, eps_series)
    shunt_len = quarter_wave_len_mm(f0_ghz, eps_shunt)

    hx, hy = series_len / 2.0, shunt_len / 2.0
    traces = [
        make_trace("arm_top", series_w, [[-hx, hy], [hx, hy]], "series_arm"),
        make_trace("arm_bottom", series_w, [[-hx, -hy], [hx, -hy]], "series_arm"),
        make_trace("arm_left", shunt_w, [[-hx, -hy], [-hx, hy]], "shunt_arm"),
        make_trace("arm_right", shunt_w, [[hx, -hy], [hx, hy]], "shunt_arm"),
        make_trace("feed_p1", shunt_w, [[-hx, -hy], [-hx, -hy - feed_len_mm]], "feed"),
        make_trace("feed_p2", shunt_w, [[hx, -hy], [hx + feed_len_mm, -hy]], "feed"),
        make_trace("feed_p3", shunt_w, [[hx, hy], [hx, hy + feed_len_mm]], "feed"),
        make_trace("feed_p4", shunt_w, [[-hx, hy], [-hx - feed_len_mm, hy]], "feed"),
    ]
    ports = [
        make_wave_port("P1", 1, "feed_p1", [-hx, -hy - feed_len_mm]),
        make_wave_port("P2", 2, "feed_p2", [hx + feed_len_mm, -hy]),
        make_wave_port("P3", 3, "feed_p3", [hx, hy + feed_len_mm]),
        make_wave_port("P4", 4, "feed_p4", [-hx - feed_len_mm, hy]),
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
        "template": "edb_branchline",
        "schema_version": SPEC_SCHEMA_VERSION,
        "units": {"length": "mm", "frequency": "GHz"},
        "params": {
            "f0_ghz": f0_ghz,
            "z0_ohm": z0_ohm,
            "z_series_ohm": z0_ohm / math.sqrt(2.0),
            "series_w_mm": series_w,
            "shunt_w_mm": shunt_w,
            "series_len_mm": series_len,
            "shunt_len_mm": shunt_len,
            "eps_eff_series": eps_series,
            "eps_eff_shunt": eps_shunt,
            "feed_len_mm": feed_len_mm,
            "copper_thickness_mm": copper_t,
            "board_margin_mm": margin_mm,
            "synthesis_source": "core.synthesis inverse_width/forward_media"
                                "（与 synthesize_branchline 同引擎同序）",
            "port_roles": "P1 输入/P2 直通/P3 耦合/P4 隔离"
                          "（串联臂 1-2、4-3，并联臂 1-4、2-3）",
        },
        "stackup": build_spec_stackup(stackup, copper_t),
        "traces": traces,
        "vias": [],
        "resistors": [],
        "ports": ports,
        "board": board_from_traces(traces, margin_mm),
        "sim_setup": sim_setup,
    }
    errors = validate_spec(spec)
    if errors:
        raise ValueError(f"branchline spec 自检失败: {errors}")
    return spec, assemble_config(spec)
