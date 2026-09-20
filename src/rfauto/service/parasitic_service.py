"""PCB 寄生提取链 service 编排（Q3D/SIwave）。

JSON 进出薄编排：把 KiCad pcell/DRC 链与 core/parasitic 确定性内核串成
PCB 无源/互连 RLC 提取链路::

    KiCad pcell PCBDesign（几何事实源）→ RF-DRC 门（adapters/kicad_drc
    纯几何规则，离线确定性）→ 主走线提取规格 → RLC 闭式锚
    （core/parasitic）→ Q3D 提取结果注入对比（可选，≤5% 门）

只做确定性算术与参数校验：无 LLM、无网络、无子进程；Q3D 真机提取由
adapters/q3d_adapter.Q3dAdapter.solve() 产出后，把 extracted 结果
（{"l_total_nh", "c_total_pf", "r_total_ohm"?}）作为 ``q3d`` 注入本服务
（真机面与编排面解耦，同 electrothermal_service 口径）。

输入 payload 形状（未知字段/缺字段显式报错，ok=False 不抛异常）::

    {
      "pcb": {  # adapters/kicad_pcell.PCBDesign.to_dict() 形状（+可选 net/sensitive 扩展键）
        "traces": [{"start": [x,y], "end": [x,y], "width": w_mm,
                    "layer"?: "F.Cu", "net"?: "RF", "sensitive"?: false}],
        "vias"?:  [{"position": [x,y], "drill": d_mm, "pad": p_mm, "net"?: "GND"}]
      },
      "substrate": {"h_mm": 0.508, "eps_r": 3.66, "tan_d"?: 0.0037,
                    "rho_ohm_m"?, "rough_mm"?},
      "trace_t_mm"?: 0.035,          # 主走线铜厚
      "freq_ghz"?: 1.0,
      "drc"?: {                       # RF-DRC 门（默认全开）
        "enabled"?: true, "freq_ghz"?, "eps_eff"?,   # 缺省用锚点 εeff
        "min_trace_width_mm"?: 0.1,
        # 其余键 = adapters/kicad_drc.RFDRCConfig 字段（via_pitch_ratio 等）
      },
      "q3d"?: {"l_total_nh": 14.2, "c_total_pf": 5.56, "r_total_ohm"?: 0.35}
    }

输出::

    {"ok": true, "chain": {"geometry": ..., "drc": ..., "anchor": ...,
                           "q3d": {...verdict} | null}}
非法输入/DRC 门不过：{"ok": false, "error"|"stage": ...}（确定性、可序列化）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from rfauto.adapters.kicad_drc import (
    Conductor,
    RFDRCConfig,
    RFDRCResult,
    RFGeometry,
    Via,
    run_rf_drc,
)
from rfauto.core.parasitic import (
    COPPER_RHO_OHM_M,
    interconnect_rlc_anchor,
    microstrip_lc_per_length,
)

#: 最小线宽规则默认值（= adapters/kicad_drc.DEFAULT_RF_RULES 的 min_trace_width）
DEFAULT_MIN_TRACE_WIDTH_MM = 0.1

#: Q3D 注入对比验收门（相对偏差，= adapters/q3d_adapter.ANCHOR_TOLERANCE）
ANCHOR_TOLERANCE = 0.05


def _as_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} 必须是对象（dict）")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where} 含未知字段: {unknown}")


def _require_key(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ValueError(f"{where} 缺少字段 {key!r}")
    return data[key]


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须是有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，收到 {value!r}")
    return out


def _point2(value: Any, where: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{where} 必须是 [x, y]，收到 {value!r}")
    return _finite(value[0], f"{where}.x"), _finite(value[1], f"{where}.y")


def pcb_to_rfdrc_geometry(pcb: Mapping[str, Any]) -> RFGeometry:
    """KiCad pcell PCBDesign 形状 → RFGeometry（DRC 链几何转换）。

    走线 net 缺省 "RF"、过孔 net 缺省 "GND"（kicad_pcell 原生数据类无
    net 字段，扩展键由本转换消费）；过孔 diameter 取 pad（铜特征直径，
    间距/缝合规则的几何口径）。traces/vias 键缺失按空处理。
    """
    conductors: list[Conductor] = []
    for i, raw in enumerate(pcb.get("traces") or []):
        tr = _as_mapping(raw, f"pcb.traces[{i}]")
        start = _point2(_require_key(tr, "start", f"pcb.traces[{i}]"),
                        f"pcb.traces[{i}].start")
        end = _point2(_require_key(tr, "end", f"pcb.traces[{i}]"),
                      f"pcb.traces[{i}].end")
        width = _positive(_require_key(tr, "width", f"pcb.traces[{i}]"),
                          f"pcb.traces[{i}].width")
        conductors.append(Conductor(
            net=str(tr.get("net", "RF")),
            points=[start, end],
            layer=str(tr.get("layer", "F.Cu")),
            width_mm=width,
            sensitive=bool(tr.get("sensitive", False)),
        ))
    vias: list[Via] = []
    for i, raw in enumerate(pcb.get("vias") or []):
        vb = _as_mapping(raw, f"pcb.vias[{i}]")
        pos = _point2(_require_key(vb, "position", f"pcb.vias[{i}]"),
                      f"pcb.vias[{i}].position")
        pad = _positive(_require_key(vb, "pad", f"pcb.vias[{i}]"),
                        f"pcb.vias[{i}].pad")
        vias.append(Via(
            x=pos[0], y=pos[1],
            net=str(vb.get("net", "GND")),
            diameter_mm=pad,
        ))
    return RFGeometry(vias=vias, conductors=conductors, slots=[])


def _primary_trace(pcb: Mapping[str, Any]) -> dict[str, Any]:
    """主提取走线 = 最长 F.Cu 走线（KiCad pcell 链几何事实源）。"""
    best: dict[str, Any] | None = None
    best_len = -1.0
    for i, raw in enumerate(pcb.get("traces") or []):
        tr = _as_mapping(raw, f"pcb.traces[{i}]")
        if str(tr.get("layer", "F.Cu")) != "F.Cu":
            continue
        start = _point2(_require_key(tr, "start", f"pcb.traces[{i}]"),
                        f"pcb.traces[{i}].start")
        end = _point2(_require_key(tr, "end", f"pcb.traces[{i}]"),
                      f"pcb.traces[{i}].end")
        width = _positive(_require_key(tr, "width", f"pcb.traces[{i}]"),
                          f"pcb.traces[{i}].width")
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length > best_len:
            best_len = length
            best = {"w_mm": width, "length_mm": length,
                    "index": i, "net": str(tr.get("net", "RF"))}
    if best is None or best_len <= 0.0:
        raise ValueError("pcb.traces 无 F.Cu 有效走线（需 >=1 条有长度走线）")
    return best


def _run_drc_gate(pcb: Mapping[str, Any], drc: Mapping[str, Any],
                  eps_eff_default: float, freq_ghz: float) -> dict[str, Any]:
    """RF-DRC 门（纯几何，离线确定性）：min_width 内联 + run_rf_drc 四规则。"""
    geometry = pcb_to_rfdrc_geometry(pcb)
    min_width = _positive(drc.get("min_trace_width_mm", DEFAULT_MIN_TRACE_WIDTH_MM),
                          "drc.min_trace_width_mm")
    violations = []
    for cond in geometry.conductors:
        if cond.width_mm < min_width:
            violations.append({
                "rule_name": "min_trace_width", "severity": "error",
                "message": (f"trace net={cond.net!r} width {cond.width_mm}mm "
                            f"< min {min_width}mm"),
                "actual_value": cond.width_mm, "expected_value": min_width,
            })
    config = RFDRCConfig(
        freq_ghz=_positive(drc.get("freq_ghz", freq_ghz), "drc.freq_ghz"),
        eps_eff=_positive(drc.get("eps_eff", eps_eff_default), "drc.eps_eff"),
    )
    rf_result: RFDRCResult = run_rf_drc(geometry, config)
    n_errors = len(violations) + rf_result.n_errors
    n_warnings = rf_result.n_warnings
    passed = n_errors == 0
    return {
        "passed": passed,
        "n_errors": n_errors,
        "n_warnings": n_warnings,
        "lambda_g_mm": rf_result.lambda_g_mm,
        "violations": violations + [v.to_dict() for v in rf_result.violations],
        "rules_checked": [r.to_dict() for r in rf_result.rules_checked],
    }


def extract_interconnect_rlc(payload: Mapping[str, Any]) -> dict[str, Any]:
    """PCB 互连 RLC 提取链编排：pcell 几何 → DRC 门 → 闭式锚 →（Q3D 注入对比）。

    Raises 不外泄：任何 ValueError 转成 {"ok": False, "error": str}；
    DRC 门不过返回 {"ok": False, "stage": "drc", ...}（不进提取）。
    """
    try:
        src = _as_mapping(payload, "payload")
        _reject_unknown(src, {"pcb", "substrate", "trace_t_mm", "freq_ghz",
                              "drc", "q3d"}, "payload")
        pcb = _as_mapping(_require_key(src, "pcb", "payload"), "pcb")
        substrate = _as_mapping(_require_key(src, "substrate", "payload"),
                                "substrate")
        _reject_unknown(substrate,
                        {"h_mm", "eps_r", "tan_d", "rho_ohm_m", "rough_mm"},
                        "substrate")
        trace_t = _positive(src.get("trace_t_mm", 0.035), "trace_t_mm")
        freq_ghz = _positive(src.get("freq_ghz", 1.0), "freq_ghz")
        h_mm = _positive(_require_key(substrate, "h_mm", "substrate"),
                         "substrate.h_mm")
        eps_r = _positive(_require_key(substrate, "eps_r", "substrate"),
                          "substrate.eps_r")
        if eps_r < 1.0:
            raise ValueError(f"substrate.eps_r 必须 >=1，收到 {eps_r!r}")
        tan_d = _finite(substrate.get("tan_d", 0.0), "substrate.tan_d")
        if tan_d < 0.0:
            raise ValueError(f"substrate.tan_d 必须 >=0，收到 {tan_d!r}")

        primary = _primary_trace(pcb)
        eps_eff = microstrip_lc_per_length(
            primary["w_mm"], h_mm, eps_r, freq_ghz)["eps_eff"]

        # ── RF-DRC 门（不过不进提取）─────────────────────────────────────
        drc_cfg = _as_mapping(src.get("drc") or {}, "drc")
        if not bool(drc_cfg.get("enabled", True)):
            drc_out = {"passed": True, "n_errors": 0, "n_warnings": 0,
                       "lambda_g_mm": None, "violations": [],
                       "rules_checked": [], "enabled": False}
        else:
            _reject_unknown(drc_cfg,
                            {"enabled", "freq_ghz", "eps_eff",
                             "min_trace_width_mm", "via_pitch_ratio",
                             "via_pitch_override_mm", "stitch_band_mm",
                             "stitch_gap_max_mm", "stitch_min_vias_per_side",
                             "min_gap_to_ground_mm", "min_gap_to_other_mm",
                             "ground_nets", "check_reference_plane_slot"},
                            "drc")
            drc_out = _run_drc_gate(pcb, drc_cfg, eps_eff, freq_ghz)
            drc_out["enabled"] = True
        if not drc_out["passed"]:
            return {"ok": False, "stage": "drc", "drc": drc_out}

        # ── RLC 闭式锚（core 单一实现）───────────────────────────────────
        rho = substrate.get("rho_ohm_m")
        rough = substrate.get("rough_mm")
        anchor = interconnect_rlc_anchor(
            length_mm=primary["length_mm"], w_mm=primary["w_mm"],
            t_mm=trace_t, h_mm=h_mm, eps_r=eps_r, freq_ghz=freq_ghz,
            loss_tangent=tan_d,
            rho_ohm_m=(float(rho) if rho is not None else COPPER_RHO_OHM_M),
            rough_mm=(float(rough) if rough is not None else 0.0),
        )

        # ── Q3D 提取注入对比（可选；真机结果由 Q3dAdapter.solve 产出）────
        q3d_out: dict[str, Any] | None = None
        q3d_raw = src.get("q3d")
        if q3d_raw is not None:
            q3d = _as_mapping(q3d_raw, "q3d")
            _reject_unknown(q3d, {"l_total_nh", "c_total_pf", "r_total_ohm"},
                            "q3d")
            l_total = _positive(_require_key(q3d, "l_total_nh", "q3d"),
                                "q3d.l_total_nh")
            c_total = _positive(_require_key(q3d, "c_total_pf", "q3d"),
                                "q3d.c_total_pf")
            r_total = q3d.get("r_total_ohm")
            length = primary["length_mm"]
            l_dev = abs(l_total / length - anchor["l_nh_per_mm"]) \
                / anchor["l_nh_per_mm"]
            c_dev = abs(c_total / length - anchor["c_pf_per_mm"]) \
                / anchor["c_pf_per_mm"]
            q3d_out = {
                "l_total_nh": l_total,
                "c_total_pf": c_total,
                "r_total_ohm": (float(r_total) if r_total is not None else None),
                "l_rel_dev": l_dev,
                "c_rel_dev": c_dev,
                "pass_5pct": bool(l_dev <= ANCHOR_TOLERANCE
                                  and c_dev <= ANCHOR_TOLERANCE),
                "dc_r_reference_ohm": anchor["dc_r_ohm"],
            }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "chain": {
        "geometry": {
            "primary_trace": primary,
            "n_traces": len(pcb.get("traces") or []),
            "n_vias": len(pcb.get("vias") or []),
            "trace_t_mm": trace_t,
            "freq_ghz": freq_ghz,
        },
        "drc": drc_out,
        "anchor": anchor,
        "q3d": q3d_out,
    }}
