"""Q-X16 layered_stack HFSS 仲裁判读函数单源（aurora_q 席位 Q-X16）。

跨引擎仲裁 HFSS 侧（#190 对齐基准）：HFSS=精确键合体（止于 ±L/2、双波
端口落腔端截面，§2.1 实测形态），对拍**冻结的外部实测锚**（D:/晶圆键合/
rfauto_反馈与实测经验.md §2.1：|S11|max=−23.5dB、|S21|mean=−0.07dB、
εeff≈1.59/Z0≈50.2@w=0.52）与**仓内闭式现场重算锚**（w=名义设计点反解）。
判据门限**复用 Q-X9 spec 冻结门限**（G1-G5 同阈，runs/aurora_q/qx9_anchor/
spec.md §5）；openEMS 侧 verdict 数据源（qx10 冒烟 C 档/qx11 服务器 A_auto
档）只作引用登记非门（本席 HFSS 侧先立对齐基准）。

本模块 = 判读纯函数单源（真跑驱动 runs/aurora_q/qx16_hfss_arb/
qx16_hfss_runner.py 经 ``from tests.unit.test_qx16_arb_verdict import ...``
复算同一判读面——判据先冻结后跑（#122，冻结书=runs/aurora_q/qx16_hfss_arb/
criteria_qx16.md），真跑后不因结果改门；闭式锚不硬编码，每次判读由
``_suspended_stripline_ri`` + ``design_params`` 现场重算=独立复算锚）。

预声明门（criteria_qx16.md §5 冻结，阈值=唯一事实源）：
  G0（锚自洽，二值）: design_params 名义点正向复算 |ΔZ0|≤1e-9Ω（#118）
  G1（|S21|mean）    : vs 外部锚 −0.07dB，|Δ|≤0.3dB PASS / ≤0.5 PARTIAL / FAIL
  G2（|S11|max）     : vs 外部锚 −23.5dB，|Δ|≤6dB PASS / ≤10dB PARTIAL / FAIL
  G3（εeff 相位斜率）: vs 闭式现场重算，rel ≤2% PASS / ≤5% PARTIAL / FAIL
                       （L=参考面跨度=line_len=5.1mm 显式参数，#364-②）
  G4（Z0 隐含带）    : 由带内 |S11|max 换算 [50(1−g)/(1+g), 50(1+g)/(1−g)]，
                       g=10^(|S11|max/20)；须同含闭式锚 Z0 与外部经验锚
                       50.2Ω（二值）
  G5（健康，二值）   : max(|S11|²+|S21|²)≤1.05 带内 ∧ 全带无 |S|>1 ∧
                       求解收敛验收（passes≥1 且 final_delta_s≤ΔS，#335）
                       ∧ geometry_lint 零 ERROR ∧ 带内频点数=21
总 verdict：任一 FAIL→DISAGREE；全 PASS→AGREE；否则 PARTIAL；
产物缺→INCOMPLETE（如实不凑）。

合成已知量回收（#340 家法）：理想线 fixture（S21=exp(−jβL)、β=闭式解析、
S11=常量 Γ 且无源性配平）→ εeff 相位斜率复算锚相对误差 ≤1e-9。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.layered_stack_spec import (
    LayeredStackSpec,
    design_params,
)
from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
from rfauto.core.calculators import _suspended_stripline_ri

# ── 冻结的锚常量（#122：真跑前冻结，不因结果改）─────────────────────────────
C0 = 299792458.0
#: 闭式锚几何（腔高/膜厚/εr=spec 缺省=反馈 §3.4/§2.1 实测锚，qx10/qx11 同源）
B_MM, H_MM, ER_SI = 0.50, 0.05, 11.9
#: 名义频带（§5 实测扫频锚 create_linear_count_sweep("Setup1","GHz",85,105,21)）
BAND_GHZ = (85.0, 105.0)
F0_GHZ = 95.0
N_POINTS_SWEEP = 21
#: 外部实测锚（§2.1 原文，冻结）
HFSS_EXT_S11_MAX_DB = -23.5
HFSS_EXT_S21_MEAN_DB = -0.07
HFSS_EXT_Z0_OHM = 50.2
#: 求解收敛档（#335 先例预声明：ΔS 目标 0.01 + passes 上限 12）
MAX_DELTA_S = 0.01
MAX_PASSES = 12
SOLVE_TIMEOUT_S = 3600

# ── 门限（预声明冻结；G1-G4 阈值=Q-X9 spec §5 冻结门限复用）────────────────
G0_JUDGE_OHM = 1e-9
G1_PASS_DB, G1_PARTIAL_DB = 0.3, 0.5
G2_PASS_DB, G2_PARTIAL_DB = 6.0, 10.0
G3_PASS, G3_PARTIAL = 0.02, 0.05
PASSIVITY_MAX = 1.05

#: G4 须被隐含带覆盖的 Z0 锚集（闭式现场重算 + 外部经验锚）
G4_ANCHORS = ("closed_form", "external")

#: judge_qx16 必需观测键（缺任一 → INCOMPLETE，如实不凑）
REQUIRED_MEASURED_KEYS = (
    "s21_mean_db", "s11_max_db", "eps_eff", "passivity_max",
    "over_unity_cnt", "n_points_band", "solve_converged", "lint_pass",
)

#: openEMS 侧 verdict 数据源（引用登记非门；相对仓根）
OPENEMS_REF_PATHS = (
    "runs/aurora_q/qx10_smoke/verdict.json",
    "runs/aurora_q/qx11_server/verdict_a_auto.json",
)


# ── 名义 spec 与闭式锚（现场重算，不硬编码结果）────────────────────────────
def nominal_params() -> dict[str, float]:
    """名义参数面（registry TEMPLATE_NOMINAL 单源，qx10/qx11 同款）。"""
    return {k: float(v) for k, v in TEMPLATE_NOMINAL["layered_stack"].items()}


def nominal_spec() -> LayeredStackSpec:
    """名义 spec（render_core._layered_stack_spec_from_params 构造单源）。"""
    from rfauto.adapters.oe_templates.render_core import (
        _layered_stack_spec_from_params,
    )
    return _layered_stack_spec_from_params(nominal_params())


def nominal_strip_w_mm() -> float:
    """名义 strip 宽（design_params(50Ω) 反解单源；#118 自洽裁判在 G0 内复验）。"""
    return float(design_params(50.0)["params"]["strip_w_mm"])


def ref_plane_span_m(spec: LayeredStackSpec | None = None) -> float:
    """双波端口参考面跨度（米，εeff 相位斜率的 L，#364-② 显式参数）。

    HFSS plan 端口 sheet 落模型端面 x=±line_len/2 且 deembed=0.0 → 两参考
    面间距=线长 line_len（span=参考面跨度≠名义线长的坑只发生在测量面
    内缩形态 #364-②；本模型端口即端面，跨度=线长逐位成立）。
    """
    spec = nominal_spec() if spec is None else spec
    return float(spec.line_len_mm) * 1e-3


def closed_form_anchor() -> dict[str, float]:
    """闭式锚现场重算（独立复算：每次判读现算，不读硬编码结果）。"""
    w_mm = nominal_strip_w_mm()
    eps_eff, z0 = _suspended_stripline_ri(w_mm, B_MM, H_MM, ER_SI)
    return {"eps_eff": float(eps_eff), "z0_ohm": float(z0), "w_mm": w_mm,
            "b_mm": B_MM, "h_mm": H_MM, "epsilon_r": ER_SI}


def anchor_design_residual_ohm() -> float:
    """名义点正向复算残差 |Z0(w_nom)−50|（Ω）——#118 独立裁判量（G0）。"""
    return abs(closed_form_anchor()["z0_ohm"] - 50.0)


def implied_z0_band(s11_max_db: float,
                    port_z0_ohm: float = 50.0) -> tuple[float, float]:
    """|S11|max → Z0 隐含带（50Ω 重归一口径，Q-X9 同式）：
    g=10^(db/20) → [Z(1−g)/(1+g), Z(1+g)/(1−g)]。"""
    g = 10.0 ** (s11_max_db / 20.0)
    z = float(port_z0_ohm)
    return (z * (1.0 - g) / (1.0 + g), z * (1.0 + g) / (1.0 - g))


def eps_eff_from_phase(f_hz: np.ndarray, s21: np.ndarray,
                       span_m: float) -> float:
    """|S21| 解缠相位斜率 → εeff（HFSS 侧 β 主判提取）。

    arg(S21)=−β·L（参考面跨度 L）→ dφ/df=−2π·L·√εeff/c0（准 TEM β∝f）
    → √εeff=−slope·c0/(2π·L)。斜率拟合对频轴去均值（大 x 数值精度）。
    非负斜率/退化输入 → NaN（如实，不冒充数值）。
    """
    f_hz = np.asarray(f_hz, dtype=float)
    s21 = np.asarray(s21, dtype=complex)
    if f_hz.size < 2 or span_m <= 0.0:
        return float("nan")
    phase = np.unwrap(np.angle(s21))
    x = f_hz - float(np.mean(f_hz))
    slope = float(np.polyfit(x, phase, 1)[0])   # rad/Hz
    if not math.isfinite(slope) or slope >= 0.0:
        return float("nan")
    n_eff = -slope * C0 / (2.0 * math.pi * span_m)
    return float(n_eff * n_eff)


def stats_from_touchstone_arrays(f_hz: np.ndarray, s11: np.ndarray,
                                 s21: np.ndarray,
                                 span_m: float | None = None) -> dict[str, Any]:
    """Touchstone 数组 → 判读统计量（全 JSON 可序列化；arb 与合成回收同面）。

    - s21_mean_db / s11_max_db：带内（|S11|max=带内 dB 最大=最浅谷，Q-X9 口径）；
    - eps_eff：S21 解缠相位斜率（span=参考面跨度，#364-②）；
    - passivity_max：带内 max(|S11|²+|S21|²)（2×2 单始单终行和口径）；
    - over_unity_cnt：全带 |S11|>1 或 |S21|>1 计数（#262 家族哨兵）。
    """
    span_m = ref_plane_span_m() if span_m is None else float(span_m)
    f_hz = np.asarray(f_hz, dtype=float)
    s11 = np.asarray(s11, dtype=complex)
    s21 = np.asarray(s21, dtype=complex)
    band = (f_hz >= BAND_GHZ[0] * 1e9) & (f_hz <= BAND_GHZ[1] * 1e9)
    if not band.any():
        raise ValueError(
            f"stats_from_touchstone_arrays: 频轴与预声明带 {BAND_GHZ}GHz "
            f"无交集（{f_hz.size} 点，范围 "
            f"[{float(np.min(f_hz)) / 1e9:.3f}, {float(np.max(f_hz)) / 1e9:.3f}]GHz）")
    db = 20.0 * np.log10(np.maximum(np.abs(s21[band]), 1e-300))
    db11 = 20.0 * np.log10(np.maximum(np.abs(s11[band]), 1e-300))
    return {
        "s21_mean_db": float(np.mean(db)),
        "s11_max_db": float(np.max(db11)),
        "eps_eff": eps_eff_from_phase(f_hz[band], s21[band], span_m),
        "passivity_max": float(np.max(np.abs(s11[band]) ** 2
                                      + np.abs(s21[band]) ** 2)),
        "over_unity_cnt": int(np.sum((np.abs(s11) > 1.0) | (np.abs(s21) > 1.0))),
        "n_points_band": int(np.sum(band)),
        # INFO：arg(S21)=−β(f)·span → −slope/span=β(f)/f=2π√εeff/c0
        # （β∝f 的归一常数；β(f)=该值×f，非 β 本身——#340 量纲家法）
        "beta_phase_norm_info": (
            float("nan") if span_m <= 0 else float(
                -np.polyfit(f_hz[band] - float(np.mean(f_hz[band])),
                            np.unwrap(np.angle(s21[band])), 1)[0]) / span_m),
    }


# ── 门函数（每门返回 status/观测/门限，全 JSON 可序列化）───────────────────
def gate_g0_anchor(residual_ohm: float | None = None) -> dict[str, Any]:
    """G0 锚自洽（二值）：名义点正向复算 |ΔZ0|≤1e-9Ω（#118）。

    residual_ohm=None → 现场重算；显式注入用于边界钉（单测面）。
    """
    resid = anchor_design_residual_ohm() if residual_ohm is None \
        else float(residual_ohm)
    return {"gate": "G0", "status":
            "PASS" if resid <= G0_JUDGE_OHM else "FAIL",
            "design_residual_ohm": resid, "judge_ohm": G0_JUDGE_OHM}


def gate_g1_s21_mean(s21_mean_db: float) -> dict[str, Any]:
    dev = s21_mean_db - HFSS_EXT_S21_MEAN_DB
    status = ("PASS" if abs(dev) <= G1_PASS_DB
              else "PARTIAL" if abs(dev) <= G1_PARTIAL_DB else "FAIL")
    return {"gate": "G1", "status": status, "observed_s21_mean_db": s21_mean_db,
            "hfss_ext_db": HFSS_EXT_S21_MEAN_DB, "dev_db": dev,
            "pass_db": G1_PASS_DB, "partial_db": G1_PARTIAL_DB}


def gate_g2_s11_max(s11_max_db: float) -> dict[str, Any]:
    dev = s11_max_db - HFSS_EXT_S11_MAX_DB
    status = ("PASS" if abs(dev) <= G2_PASS_DB
              else "PARTIAL" if abs(dev) <= G2_PARTIAL_DB else "FAIL")
    return {"gate": "G2", "status": status, "observed_s11_max_db": s11_max_db,
            "hfss_ext_db": HFSS_EXT_S11_MAX_DB, "dev_db": dev,
            "pass_db": G2_PASS_DB, "partial_db": G2_PARTIAL_DB}


def gate_g3_eps_eff(eps_eff_engine: float) -> dict[str, Any]:
    anchor = closed_form_anchor()
    rel = abs(eps_eff_engine - anchor["eps_eff"]) / anchor["eps_eff"]
    status = ("PASS" if rel <= G3_PASS
              else "PARTIAL" if rel <= G3_PARTIAL else "FAIL")
    return {"gate": "G3", "status": status,
            "observed_eps_eff": eps_eff_engine,
            "closed_eps_eff": anchor["eps_eff"], "rel": rel,
            "pass_rel": G3_PASS, "partial_rel": G3_PARTIAL,
            "source": "S21 解缠相位斜率（L=参考面跨度=line_len 显式参数，"
                      "#364-②）"}


def gate_g4_z0_band(s11_max_db: float) -> dict[str, Any]:
    """G4 Z0 隐含带（二值）：带须同含闭式锚 Z0 与外部经验锚 50.2Ω。"""
    anchor = closed_form_anchor()
    lo, hi = implied_z0_band(s11_max_db)
    checks = {name: bool(lo <= z <= hi) for name, z in
              (("closed_form", anchor["z0_ohm"]),
               ("external", HFSS_EXT_Z0_OHM))}
    return {"gate": "G4", "status":
            "PASS" if all(checks[n] for n in G4_ANCHORS) else "FAIL",
            "observed_s11_max_db": s11_max_db,
            "implied_band_ohm": [lo, hi],
            "anchors_ohm": {"closed_form": anchor["z0_ohm"],
                            "external": HFSS_EXT_Z0_OHM},
            "checks": checks}


def gate_g5_health(passivity_max: float, over_unity_cnt: int,
                   solve_converged: bool, lint_pass: bool,
                   n_points_band: int) -> dict[str, Any]:
    ok = (passivity_max <= PASSIVITY_MAX and over_unity_cnt == 0
          and bool(solve_converged) and bool(lint_pass)
          and int(n_points_band) == N_POINTS_SWEEP)
    return {"gate": "G5", "status": "PASS" if ok else "FAIL",
            "passivity_max": passivity_max,
            "passivity_limit": PASSIVITY_MAX,
            "s_over_unity_cnt": over_unity_cnt,
            "solve_converged": bool(solve_converged),
            "solve_converge_rule": f"passes≥1 且 final_delta_s≤{MAX_DELTA_S}"
                                   "（#335 收敛验收先于判读）",
            "lint_pass": bool(lint_pass),
            "n_points_band": int(n_points_band),
            "n_points_expected": N_POINTS_SWEEP}


# ── 判读组装（真跑驱动与单测同源）──────────────────────────────────────────
def judge_qx16(measured: dict[str, Any] | None,
               openems_refs: dict[str, Any] | None = None) -> dict[str, Any]:
    """判读入口。measured=None 或必需键缺 → INCOMPLETE（如实不凑）。

    measured 键：s21_mean_db / s11_max_db / eps_eff / passivity_max /
    over_unity_cnt / n_points_band / solve_converged / lint_pass
    （+ solve_passes / solve_delta_s / wall_s INFO 可选）。
    openems_refs：openEMS 侧 verdict 数据源引用（非门，citation 登记）。
    """
    anchor = closed_form_anchor()
    out: dict[str, Any] = {
        "seat": "Q-X16", "campaign": "aurora_q",
        "subject": "layered_stack HFSS 仲裁（精确键合体 vs 冻结外部锚+"
                   "闭式现场重算；#190 对齐基准）",
        "band_ghz": list(BAND_GHZ), "f0_ghz": F0_GHZ,
        "config": {"max_delta_s": MAX_DELTA_S, "max_passes": MAX_PASSES,
                   "sweep_points": N_POINTS_SWEEP,
                   "solve_timeout_s": SOLVE_TIMEOUT_S,
                   "ref_plane_span_mm": ref_plane_span_m() * 1e3},
        "anchor": anchor,
        "hfss_ext": {"s11_max_db": HFSS_EXT_S11_MAX_DB,
                     "s21_mean_db": HFSS_EXT_S21_MEAN_DB,
                     "z0_ohm": HFSS_EXT_Z0_OHM},
        "openems_side_refs": openems_refs or {},
    }
    g0 = gate_g0_anchor()
    out["g0_anchor"] = {"status": g0["status"],
                        "design_residual_ohm": g0["design_residual_ohm"]}
    if measured is None:
        out["verdict"] = "INCOMPLETE"
        out["missing"] = ["touchstone/build_report"]
        return out
    missing = [k for k in REQUIRED_MEASURED_KEYS if measured.get(k) is None]
    if missing:
        out["verdict"] = "INCOMPLETE"
        out["missing"] = missing
        return out
    gates = {
        "G1": gate_g1_s21_mean(float(measured["s21_mean_db"])),
        "G2": gate_g2_s11_max(float(measured["s11_max_db"])),
        "G3": gate_g3_eps_eff(float(measured["eps_eff"])),
        "G4": gate_g4_z0_band(float(measured["s11_max_db"])),
        "G5": gate_g5_health(
            float(measured["passivity_max"]),
            int(measured["over_unity_cnt"]),
            bool(measured["solve_converged"]),
            bool(measured["lint_pass"]),
            int(measured["n_points_band"])),
    }
    statuses = [str(g["status"]) for g in gates.values()]
    verdict = ("DISAGREE" if "FAIL" in statuses
               else "AGREE" if all(s == "PASS" for s in statuses)
               else "PARTIAL")
    out["verdict"] = verdict
    out["gates"] = gates
    for info_key in ("solve_passes", "solve_delta_s", "wall_s",
                     "beta_phase_norm_info"):
        if measured.get(info_key) is not None:
            out.setdefault("info", {})[info_key] = measured[info_key]
    out["notes"] = [
        "HFSS=精确键合体（止于 ±L/2、波端口落腔端截面，§2.1 实测形态）；"
        "openEMS=匹配馈延续直入 PML_8（qx10 spec §2 结构近似面）——两端口径"
        "各自成立，本席 HFSS 侧先立 #190 对齐基准，openEMS 侧 verdict 只作"
        "引用登记（非门）",
        "εeff 主判=S21 解缠相位斜率，L=参考面跨度=line_len=5.1mm 显式参数"
        "（端口即模型端面、deembed=0，#364-② 语义逐位成立）",
        "G2 参考系分支声明（Q-X9 spec §5 同款）：HFSS 波端口缺省重归一 50Ω"
        "（plan renormalize=True）与外部锚口径一致——若 |S11|max 显著深于"
        "−30dB，按 50Ω 重归一口径解读，G2 仍按冻结门限判",
        "收敛档 ΔS=0.01/max_passes=12（#335 先例预声明）；若 G1/G3 落 PARTIAL"
        "边缘，仲裁升级路径=ΔS 阶梯 0.02→0.01→0.005 关键标量饱和性复核"
        "（escalation 预声明，不属改门）",
    ]
    return out


# ── 单测（判读函数钉；阈值边界逐点）─────────────────────────────────────────

def test_closed_form_anchor_deterministic_and_self_consistent():
    a1, a2 = closed_form_anchor(), closed_form_anchor()
    assert a1 == a2   # 确定性重算
    # 与 qx10/qx11 闭式锚同源同值（w=design_params(50Ω) 反解，b/h/εr 同表）
    assert math.isclose(a1["eps_eff"], 1.6007603731686557, rel_tol=1e-12)
    assert math.isclose(a1["z0_ohm"], 50.0, rel_tol=1e-12)
    # 名义点正向复算残差 ≤1e-9（#118 独立裁判）
    assert anchor_design_residual_ohm() <= G0_JUDGE_OHM
    # 外部经验锚对照（w=0.52→Z0≈50.2）：闭式现算 50.25±0.5（Q-X9 同钉）
    _, z052 = _suspended_stripline_ri(0.52, B_MM, H_MM, ER_SI)
    assert abs(z052 - 50.2) <= 0.5, z052


def test_nominal_spec_and_ref_plane_span_contract():
    spec = nominal_spec()
    nom = nominal_params()
    # registry 名义账本逐键一致（Q-X6 注册单源）
    assert math.isclose(spec.conductor.width_mm, nom["strip_w_mm"],
                        rel_tol=0.0, abs_tol=0.0)
    assert math.isclose(spec.line_len_mm, nom["line_len_mm"], abs_tol=0.0)
    assert math.isclose(spec.cavity.w_mm, nom["cavity_w_mm"], abs_tol=0.0)
    assert math.isclose(spec.cavity.h_mm, nom["cavity_h_mm"], abs_tol=0.0)
    # L=参考面跨度（#364-② 显式参数）：HFSS plan 端口即模型端面
    # （sheet pos=±line_len/2、deembed=0）→ 跨度=line_len 逐位成立
    assert math.isclose(ref_plane_span_m(spec), spec.line_len_mm * 1e-3,
                        rel_tol=1e-15)
    from rfauto.adapters.hfss_builder_layered import (
        PLAN_KIND,
        layered_stack_hfss_plan,
    )
    plan = layered_stack_hfss_plan(spec)
    assert plan["kind"] == PLAN_KIND
    l_half = spec.line_len_mm / 2.0
    xs = [float(pt["sheet"]["origin"][0]) for pt in plan["ports"]]
    assert len(xs) == 2
    assert math.isclose(xs[1] - xs[0], spec.line_len_mm, rel_tol=1e-15)
    for pt, x_pos in zip(plan["ports"], xs, strict=True):
        assert math.isclose(abs(x_pos), l_half, rel_tol=1e-15)
        assert float(pt["deembed"]) == 0.0
        # 积分线两锚点同在端口面（x=pos；跨度方向=z：带面→腔顶壁）
        il = pt["integration_line"]
        assert math.isclose(float(il[0][0]), x_pos, abs_tol=1e-12)
        assert math.isclose(float(il[1][0]), x_pos, abs_tol=1e-12)
        assert math.isclose(float(il[1][2]) - float(il[0][2]),
                            float(spec.cavity.h_mm) / 2.0, rel_tol=1e-12)


def test_gate_g0_boundaries():
    assert gate_g0_anchor()["status"] == "PASS"                    # 现场重算
    assert gate_g0_anchor(G0_JUDGE_OHM)["status"] == "PASS"        # 边界内含
    assert gate_g0_anchor(G0_JUDGE_OHM * 1.001)["status"] == "FAIL"
    assert gate_g0_anchor(1e-3)["status"] == "FAIL"


def test_gate_g1_g2_boundaries():
    # G1（|Δ|≤0.3 PASS / ≤0.5 PARTIAL / FAIL；Q-X9 冻结阈）
    assert gate_g1_s21_mean(HFSS_EXT_S21_MEAN_DB - 0.3)["status"] == "PASS"
    assert gate_g1_s21_mean(HFSS_EXT_S21_MEAN_DB + 0.3)["status"] == "PASS"
    assert gate_g1_s21_mean(HFSS_EXT_S21_MEAN_DB - 0.31)["status"] == "PARTIAL"
    assert gate_g1_s21_mean(HFSS_EXT_S21_MEAN_DB + 0.5)["status"] == "PARTIAL"
    assert gate_g1_s21_mean(HFSS_EXT_S21_MEAN_DB + 0.51)["status"] == "FAIL"
    # G2（|Δ|≤6 PASS / ≤10 PARTIAL / FAIL）
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB - 6.0)["status"] == "PASS"
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB + 6.0)["status"] == "PASS"
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB - 6.1)["status"] == "PARTIAL"
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB - 10.0)["status"] == "PARTIAL"
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB - 10.1)["status"] == "FAIL"
    assert gate_g2_s11_max(HFSS_EXT_S11_MAX_DB + 10.1)["status"] == "FAIL"


def test_gate_g3_g4_boundaries():
    a = closed_form_anchor()
    # G3：阈位 ±1e-9 相对挪移跨阈钉（浮点边界抖动，Q-X9/Q-X10 同款）
    g3 = gate_g3_eps_eff(a["eps_eff"] * (1.0 + G3_PASS - 1e-9))
    assert g3["status"] == "PASS" and math.isclose(g3["rel"], G3_PASS,
                                                   rel_tol=1e-7)
    assert gate_g3_eps_eff(a["eps_eff"] * (1.0 + G3_PASS + 1e-9))["status"] \
        == "PARTIAL"
    assert gate_g3_eps_eff(a["eps_eff"] * (1.0 + G3_PARTIAL + 1e-9))["status"] \
        == "FAIL"
    assert gate_g3_eps_eff(float("nan"))["status"] == "FAIL"   # NaN 如实 FAIL
    # G4：隐含带同含闭式 50.0 与外部 50.2 → PASS；带过窄（深谷 −60dB）
    # 排除 50.2 → FAIL
    g4 = gate_g4_z0_band(-23.5)
    assert g4["status"] == "PASS"
    lo, hi = g4["implied_band_ohm"]
    assert lo <= a["z0_ohm"] <= hi and lo <= HFSS_EXT_Z0_OHM <= hi
    assert gate_g4_z0_band(-60.0)["status"] == "FAIL"
    assert gate_g4_z0_band(-60.0)["implied_band_ohm"][0] > a["z0_ohm"] - 0.2


def test_gate_g5_health_binary():
    ok = dict(passivity_max=0.999, over_unity_cnt=0, solve_converged=True,
              lint_pass=True, n_points_band=N_POINTS_SWEEP)
    assert gate_g5_health(**ok)["status"] == "PASS"
    assert gate_g5_health(**{**ok, "passivity_max": 1.05})["status"] == "PASS"
    assert gate_g5_health(**{**ok, "passivity_max": 1.0500001})["status"] == "FAIL"
    assert gate_g5_health(**{**ok, "over_unity_cnt": 1})["status"] == "FAIL"
    assert gate_g5_health(**{**ok, "solve_converged": False})["status"] == "FAIL"
    assert gate_g5_health(**{**ok, "lint_pass": False})["status"] == "FAIL"
    assert gate_g5_health(**{**ok, "n_points_band": 20})["status"] == "FAIL"


def test_judge_verdict_mapping_and_openems_refs():
    good = {"s21_mean_db": -0.05, "s11_max_db": -26.0, "eps_eff":
            closed_form_anchor()["eps_eff"] * (1.0 + 0.001),
            "passivity_max": 0.999, "over_unity_cnt": 0, "n_points_band":
            N_POINTS_SWEEP, "solve_converged": True, "lint_pass": True,
            "solve_passes": 6, "solve_delta_s": 0.004, "wall_s": 600.0}
    refs = {"runs/aurora_q/qx10_smoke/verdict.json":
            {"verdict": "INCOMPLETE", "truncation_suspect": True}}
    v = judge_qx16(dict(good), openems_refs=refs)
    assert v["verdict"] == "AGREE"
    assert v["openems_side_refs"] == refs          # 引用登记非门
    assert v["g0_anchor"]["status"] == "PASS"
    assert v["anchor"]["z0_ohm"] == closed_form_anchor()["z0_ohm"]  # 现场重算
    # 单门 PARTIAL → 总 PARTIAL（不凑绿）
    v2 = judge_qx16(dict(good, s11_max_db=HFSS_EXT_S11_MAX_DB - 8.0))
    assert v2["verdict"] == "PARTIAL"
    # 任一 FAIL → DISAGREE
    v3 = judge_qx16(dict(good, s21_mean_db=HFSS_EXT_S21_MEAN_DB + 1.0))
    assert v3["verdict"] == "DISAGREE"
    # 必需观测键缺 → INCOMPLETE（如实不凑）
    v4 = judge_qx16({k: v0 for k, v0 in good.items() if k != "lint_pass"})
    assert v4["verdict"] == "INCOMPLETE" and v4["missing"] == ["lint_pass"]
    v5 = judge_qx16(None)
    assert v5["verdict"] == "INCOMPLETE" and v5["missing"]


def test_stats_synthetic_ideal_line_recovery_1e9():
    """合成已知量回收（#340 家法）：理想线 fixture → εeff 复算锚 ≤1e-9。"""
    anchor = closed_form_anchor()
    span_m = ref_plane_span_m()
    # 频轴=预声明扫频契约（create_linear_count_sweep 21 点；G5 点数门同链）
    f_hz = np.linspace(BAND_GHZ[0], BAND_GHZ[1], N_POINTS_SWEEP) * 1e9
    beta = 2.0 * np.pi * f_hz * math.sqrt(anchor["eps_eff"]) / C0
    s11_mag = 0.05                                  # −26.02dB 匹配背景
    s11 = s11_mag * np.exp(-1j * 0.3) * np.ones_like(f_hz)
    s21 = np.sqrt(1.0 - s11_mag ** 2) * np.exp(-1j * beta * span_m)
    st = stats_from_touchstone_arrays(f_hz, s11, s21, span_m=span_m)
    rel = abs(st["eps_eff"] - anchor["eps_eff"]) / anchor["eps_eff"]
    assert rel <= 1e-9, f"εeff 合成回收 rel={rel:.3e}（应 ≤1e-9）"
    # β 相位斜率归一 INFO 同锚：−slope/span=β(f)/f=2π√εeff/c0（β∝f 常数）
    beta_f0 = 2.0 * np.pi * F0_GHZ * 1e9 * math.sqrt(anchor["eps_eff"]) / C0
    beta_per_f = beta_f0 / (F0_GHZ * 1e9)
    assert abs(st["beta_phase_norm_info"] - beta_per_f) / beta_per_f <= 1e-9
    # 判读全链：合成已知量 → AGREE（G1-G5 全过）
    v = judge_qx16({**st, "solve_converged": True, "lint_pass": True})
    assert v["verdict"] == "AGREE", v["gates"]
    # 错误参考面跨度（#364-② 反例：拿名义线长以外的 L）→ εeff 系统性偏
    st_bad = stats_from_touchstone_arrays(f_hz, s11, s21, span_m=span_m * 2.0)
    rel_bad = abs(st_bad["eps_eff"] - anchor["eps_eff"]) / anchor["eps_eff"]
    assert rel_bad > 0.5, "跨度错 2× 应致 εeff 偏 ~4×（L² 语义）"


def test_implied_z0_band_math():
    lo, hi = implied_z0_band(HFSS_EXT_S11_MAX_DB)
    g = 10.0 ** (HFSS_EXT_S11_MAX_DB / 20.0)
    assert math.isclose(g, 0.066834, rel_tol=1e-4)
    assert math.isclose(lo, 50.0 * (1 - g) / (1 + g), rel_tol=1e-12)
    assert math.isclose(hi, 50.0 * (1 + g) / (1 - g), rel_tol=1e-12)
    assert abs(lo - 43.74) < 0.02 and abs(hi - 57.16) < 0.02   # Q-X9 同值


def test_openems_ref_paths_declared():
    """openEMS 侧 verdict 数据源声明面（引用路径与 judge 键名冻结）。"""
    assert OPENEMS_REF_PATHS == (
        "runs/aurora_q/qx10_smoke/verdict.json",
        "runs/aurora_q/qx11_server/verdict_a_auto.json",
    )
    assert all(isinstance(p, str) and p.startswith("runs/aurora_q/")
               for p in OPENEMS_REF_PATHS)
