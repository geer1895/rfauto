"""奇偶模分解服务（DP-14 Y1；服务层 JSON 进出，分层铁律）。

规格：docs/plan_deepdive_specs_20260924.md §14.3；判据书
runs/df6_dp14y1/criteria.md。几何变换内核=core/even_odd_split.py（纯函数），
本模块是注册表驱动的模板接入层（每模板声明对称轴+几何映射函数+模阻抗
来源+端口角色语义）——数值全部出自确定性内核（#7）：

- 耦合结构（cline_coupler）：模阻抗 Z0e/Z0o 从 core/coupled_microstrip.py
  coupled_microstrip_even_odd_ohm（KJ 1984 准静态闭式）**直接读**（只读复用，
  禁改文件），端口语义=模阻抗注记（半模型端口不是单线 50Ω）；
- 单导体网络（branchline_2sect）：跨面支臂盒裁成 λ/8 半桩（13.2 口径），
  偶=开路桩/奇=短路桩；桩导纳口径由内核 stub_input_admittance 出，线宽的
  HJ εeff 注记走 core/synthesis.forward_z0（只读复用）。

几何单一事实源：adapters/openems_templates._c4_layout（只读 import——服务层
在分层契约中位于 adapters 之上；#222 语境钉死：不复制几何代码）。

#154 语义防线（criteria.md §0）：两种"半模型"语义在此显式分派——
对称面在两导体**之间**（cline：平面作用于缝内场，端口改模阻抗注释）vs
对称面**切割**导体（branchline：跨面盒裁半+开/短路桩）。新模板接入必须
先声明 axis+half_model_semantics 并过对称性检测。

主入口：
- even_odd_split(template, params, freq_ghz)：严格口径，对称性破坏 raise
  core.even_odd_split.SymmetryError；
- even_odd_split_report(...)：JSON 报告口径，不抛（ok=false+细节），
  适合 UI/MCP 只读消费。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import even_odd_split as eos
from rfauto.core.even_odd_split import SymmetryError

__all__ = [
    "EVEN_ODD_TEMPLATES",
    "SymmetryError",
    "even_odd_split",
    "even_odd_split_report",
    "template_even_odd_meta",
]

C0_M_S = 2.99792458e8

C_MM_GHZ = 299.792458

# 模板叠层（与 _c4_layout/_DEFAULT_SUB 同源口径：rogers4350b）
_SUB_ER = 3.66
_SUB_H_MM = 0.508


# ── 模板几何映射（_c4_layout 只读复用 → 内核布局 schema）─────────────────────

def _cline_layout(params: dict[str, Any]) -> dict[str, Any]:
    from rfauto.adapters.openems_templates import (
        CLINE_COUPLER_NOMINAL,
        _c4_layout,
    )

    p = {**CLINE_COUPLER_NOMINAL, **(params or {})}
    lay = _c4_layout("cline_coupler", p)
    return eos.layout_from_box_tuples("x", lay["boxes"], lay["ports"])


def _branchline_layout(params: dict[str, Any]) -> dict[str, Any]:
    from rfauto.adapters.openems_templates import (
        BRANCHLINE_2SECT_NOMINAL,
        _c4_layout,
    )

    p = {**BRANCHLINE_2SECT_NOMINAL, **(params or {})}
    lay = _c4_layout("branchline_2sect", p)
    return eos.layout_from_box_tuples("y", lay["boxes"], lay["ports"])


# ── 模阻抗/口径注记（数值只出确定性内核）─────────────────────────────────────

def _cline_mode_impedances(params: dict[str, Any], freq_ghz: float) -> dict[str, Any]:
    """耦合结构 Z0e/Z0o 直接读 KJ 闭式（coupled_microstrip_even_odd_ohm）。"""
    from rfauto.adapters.openems_templates import CLINE_COUPLER_NOMINAL
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    p = {**CLINE_COUPLER_NOMINAL, **(params or {})}
    ze, zo, ee, eo = coupled_microstrip_even_odd_ohm(
        float(p["w_mm"]), float(p["gap_mm"]), float(freq_ghz),
        er=_SUB_ER, h_mm=_SUB_H_MM)
    return {
        "even": {"z_mode_ohm": ze, "eps_eff": ee},
        "odd": {"z_mode_ohm": zo, "eps_eff": eo},
        "source": ("core.coupled_microstrip.coupled_microstrip_even_odd_ohm"
                   "（Kirschning-Jansen 1984 准静态闭式，零厚/无盖口径）"),
        "note": "半模型端口模阻抗：偶=Z0e、奇=Z0o（不是单线 50Ω；HFSS 双导体"
                "端口换算链见 runs/df6_dp14y1/handoff.md #307）",
    }


def _branchline_stub_annotations(params: dict[str, Any],
                                 freq_ghz: float) -> list[dict[str, Any]]:
    """跨面支臂 λ/8 半桩口径注记（z0/εeff 走 skrf HJ 正向，13.2 口径）。"""
    from rfauto.adapters.openems_templates import BRANCHLINE_2SECT_NOMINAL
    from rfauto.core.synthesis import Stackup, forward_z0

    p = {**BRANCHLINE_2SECT_NOMINAL, **(params or {})}
    stackup = Stackup(name="branchline", epsilon_r=_SUB_ER, thickness_mm=_SUB_H_MM)
    lay = _branchline_layout(p)
    rows: list[dict[str, Any]] = []
    for b in lay["boxes"]:
        if eos.classify_box(b, "y") != "crossing":
            continue
        w_mm = float(b["x1"]) - float(b["x0"])
        if w_mm <= 0.0:
            continue
        w_mm *= 1e3
        z0, eps = forward_z0(w_mm, float(freq_ghz), stackup)
        # 跨面盒轴区间对称（hi=−lo，对称性检测已保证）→ 半桩跨=hi
        lo_y, hi_y = float(b["y0"]), float(b["y1"])
        span_full = hi_y - lo_y
        half_span = hi_y
        theta_half = (2.0 * math.pi * float(freq_ghz) * 1e9
                      * math.sqrt(eps) * half_span / C0_M_S)
        rows.append({
            "box": b["name"],
            "w_mm": w_mm,
            "z0_hj_ohm": z0,
            "eps_eff_hj": eps,
            "span_full_m": span_full,
            "span_half_m": half_span,
            "theta_half_rad_at_f0": theta_half,
            # 纯虚导纳（开路桩 +jX / 短路桩 −jX）→ {re, im} 保 JSON 可序列化
            "y_in_even_s_at_f0": {
                "re": eos.stub_input_admittance(z0, theta_half, "even").real,
                "im": eos.stub_input_admittance(z0, theta_half, "even").imag,
            },
            "y_in_odd_s_at_f0": {
                "re": eos.stub_input_admittance(z0, theta_half, "odd").real,
                "im": eos.stub_input_admittance(z0, theta_half, "odd").imag,
            },
        })
    rows.sort(key=lambda r: r["box"])
    return rows


# ── 注册表（每模板：对称轴/几何映射/模阻抗来源/端口角色语义 #154）────────────

_REGISTRY: dict[str, dict[str, Any]] = {
    "cline_coupler": {
        "axis": "x",
        "plane": "x=0（两耦合导体的缝中）",
        "layout": _cline_layout,
        "mode_impedances": _cline_mode_impedances,
        "half_model_semantics": (
            "对称面在两导体之间：导体/馈线不跨面，半模型=保线 A（x<0）+端口"
            " {1,2}；PMC/PEC 作用于缝内场；端口模阻抗偶=Z0e/奇=Z0o（KJ 直接读）"),
        "port_roles": {
            "1": "输入（线 A 近端）——半模型保留",
            "2": "直通（线 A 远端）——半模型保留",
            "3": "耦合（线 B 近端）——弃（镜像=端口 1）",
            "4": "隔离（线 B 远端）——弃（镜像=端口 2）",
        },
        "param_roles": {
            "w_mm": "line_width_mm（耦合线单线宽）",
            "gap_mm": "gap_width_mm（耦合缝宽，缝中=对称面）",
            "coupled_len_mm": "resonator_length_mm（λ/4 耦合段）",
            "w_feed_mm": "shunt_line_width_mm（50Ω 馈线）",
        },
        "reassembly": {
            "pairing": [[1, 3], [2, 4]],
            "formulas": {
                "S11": "(Γe+Γo)/2", "S21": "(Te+To)/2",
                "S31": "(Γe−Γo)/2", "S41": "(Te−To)/2",
            },
            "note": "Γ/T=半模型（线 A）2 端口 S 的反射/传输；偶奇模各自取"
                    "KJ εeff 相速（非同步口径）；13.1/Pozar §7.6",
        },
    },
    "branchline_2sect": {
        "axis": "y",
        "plane": "y=0（水平中面，切割支臂）",
        "layout": _branchline_layout,
        "mode_impedances": None,
        "half_model_semantics": (
            "对称面切割导体：跨面支臂盒裁成 λ/8 半桩（偶=开路桩 +jY·tan(θ/2)、"
            "奇=短路桩 −jY·cot(θ/2)）；半模型=保下半（y<0）+端口 {3,4}；单导体"
            "网络端口恒 50Ω"),
        "port_roles": {
            "1": "输入（左上）——弃（镜像=端口 4）",
            "2": "直通（右上）——弃（镜像=端口 3）",
            "3": "耦合（右下）——半模型保留（半模型端口 B）",
            "4": "隔离（左下）——半模型保留（半模型端口 A）",
        },
        "param_roles": {
            "w_main_mm": "主线臂宽（Z_a=Z0）",
            "w_out_mm": "外支臂宽（Z_b1=(1+√2)Z0）",
            "w_mid_mm": "中支臂宽（Z_b2=√2·Z_a²/Z0）",
            "w_feed_mm": "shunt_line_width_mm（50Ω 馈线）",
            "sect_len_mm": "主线节 λ/4",
            "branch_len_mm": "支臂跨度（跨对称面，裁成 λ/8 半桩）",
        },
        "reassembly": {
            "pairing": [[1, 4], [2, 3]],
            "formulas": {
                "S11": "(Γe+Γo)/2", "S21": "(Te+To)/2",
                "S31": "(Te−To)/2", "S41": "(Γe−Γo)/2",
            },
            "note": "Γ/T=半模型（下半 2 端口：A=端口 4 侧、B=端口 3 侧）的"
                    "反射/传输；半电路=桩(Y_b,θ/2)·线(Z_a,θ)·…（13.2/Pozar"
                    " §7.5 推广；Levy & Lind 1968）",
        },
    },
}

EVEN_ODD_TEMPLATES: tuple[str, ...] = tuple(sorted(_REGISTRY))


def _entry(template: str) -> dict[str, Any]:
    ent = _REGISTRY.get(template)
    if ent is None:
        raise ValueError(f"未知模板 {template!r}（已接入奇偶模分解：{EVEN_ODD_TEMPLATES}）")
    return ent


def _default_freq(template: str) -> float:
    from rfauto.adapters.openems_templates import TEMPLATE_META

    return float(TEMPLATE_META[template]["f0_ghz"])


def template_even_odd_meta(template: str) -> dict[str, Any]:
    """模板奇偶模接入元数据（轴/语义/端口角色/参数角色/重装配公式）。"""
    ent = _entry(template)
    return {
        "template": template,
        "axis": ent["axis"],
        "plane": ent["plane"],
        "half_model_semantics": ent["half_model_semantics"],
        "port_roles": dict(ent["port_roles"]),
        "param_roles": dict(ent["param_roles"]),
        "reassembly": dict(ent["reassembly"]),
    }


# ── 主入口（JSON 进出）───────────────────────────────────────────────────────

def _build_report(template: str, params: dict[str, Any] | None,
                  freq_ghz: float | None) -> dict[str, Any]:
    ent = _entry(template)
    f0 = float(freq_ghz) if freq_ghz is not None else _default_freq(template)
    if not (f0 > 0.0) or not math.isfinite(f0):
        raise ValueError(f"freq_ghz 须为正有限值，得 {freq_ghz!r}")
    lay = ent["layout"](params or {})
    sym = eos.symmetry_report(lay)
    report: dict[str, Any] = {
        "ok": bool(sym["ok"]),
        "template": template,
        "axis": ent["axis"],
        "plane": ent["plane"],
        "freq_ghz": f0,
        "half_model_semantics": ent["half_model_semantics"],
        "port_roles": dict(ent["port_roles"]),
        "param_roles": dict(ent["param_roles"]),
        "symmetry_check": sym,
        "half_models": {},
        "port_rewrite_table": [],
        "mode_table": {},
        "reassembly": dict(ent["reassembly"]),
        "guards": {},
    }
    if not sym["ok"]:
        report["error"] = (
            f"布局不满足镜像对称：不配对盒={sym['unmatched_box_names']}，"
            f"不配对端口={sym['unmatched_port_labels']}（判据 c）")
        return report
    mode_imp: dict[str, Any] | None = None
    if ent["mode_impedances"] is not None:
        mode_imp = ent["mode_impedances"](params or {}, f0)
    halves: dict[str, dict[str, Any]] = {}
    guards: dict[str, Any] = {}
    for mode in eos.MODES:
        half = eos.split_half_model(lay, mode)
        halves[mode] = half
        guards[mode] = eos.split_guards(lay, half)
        if mode_imp is not None:
            note = mode_imp.get(mode)
            for p in half["ports"]:
                if note is not None:
                    p["mode_impedance_ohm"] = note["z_mode_ohm"]
                    p["mode_eps_eff"] = note["eps_eff"]
    report["half_models"] = halves
    report["guards"] = guards
    report["port_rewrite_table"] = eos.port_rewrite_table(lay, mode_imp)
    if mode_imp is not None:
        report["mode_table"] = {
            "even": {"bc": eos.PLANE_BC["even"], **mode_imp["even"]},
            "odd": {"bc": eos.PLANE_BC["odd"], **mode_imp["odd"]},
            "source": mode_imp["source"],
            "note": mode_imp.get("note", ""),
        }
    else:
        report["mode_table"] = {
            "even": {"bc": eos.PLANE_BC["even"], "port_ohm": 50.0},
            "odd": {"bc": eos.PLANE_BC["odd"], "port_ohm": 50.0},
            "stub_annotations": _branchline_stub_annotations(params or {}, f0),
            "source": ("桩导纳口径=core.even_odd_split.stub_input_admittance"
                       "（教科书恒等式）；z0/εeff 注记=skrf HJ 正向"
                       "（core.synthesis.forward_z0）"),
        }
    report["ok"] = all(guards[m]["ok"] for m in eos.MODES) and bool(sym["ok"])
    return report


def even_odd_split(template: str, params: dict[str, Any] | None = None,
                   *, freq_ghz: float | None = None) -> dict[str, Any]:
    """严格口径：对称性/守卫失败 raise SymmetryError；成功返回 JSON 报告。"""
    report = _build_report(template, params, freq_ghz)
    if not report["ok"]:
        raise SymmetryError(report.get("error", "守卫未过（见报告 guards/symmetry_check）"))
    return report


def even_odd_split_report(template: str, params: dict[str, Any] | None = None,
                          *, freq_ghz: float | None = None) -> dict[str, Any]:
    """JSON 报告口径：不抛对称性异常（ok=false + 细节），UI/MCP 只读消费。"""
    return _build_report(template, params, freq_ghz)
