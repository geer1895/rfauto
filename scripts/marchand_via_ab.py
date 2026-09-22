"""C12：Marchand 巴伦 −18% 归因——过孔 PEC 薄片单变量对照 A/B（离线面+真机编排）。

登记语境（排空五轮段账项）：Marchand 巴伦 −18% 归因（过孔 PEC 薄片单变量
对照+综合器修正项）。−18%=HFSS 巴伦锚全波中心（S11 零点 2.04GHz）比理想电路
（2.5GHz）低 ≈18%（runs/hfss_marchand_anchor 归档；归因假设
=过孔柱电感 ≈0.7nH+开路 fringe ≈3%）。后续 marchand_line_calibration
把 openEMS 侧偏差主体定位到 Z0 窄线 −11.6%+激励口提取伪像，
engine_z0_correction（PCHIP 4 点）已落地——**该修正项是 openEMS 引擎
偏差修正，与 HFSS −18% 结构效应正交**；本对照回答的是 −18% 的过孔份额。

电路级预判（本文件 via_circuit_s11，core coupled_line_z_matrix + 短路口 jωL
负载约束；2026-09-21 实算）：L=0.7nH → 谷 2.046GHz（HFSS 实测 2.04，+0.3%），
L=0 → 2.500GHz——**−18% 主体可由过孔电感定量复现**（机理=短路副线电学变长：
θ_副线+θ_via=90°）。

A/B 口径（渲染单源 adapters/openems_templates.render_marchand2_script，rod 缺省
=runs/smoke_marchand_2sect 逐字节口径；两变体网格/端口/域/激励逐字节一致，
唯一差异=过孔金属原语）：
  rod   = 0.25mm 方柱（现状/HFSS 锚同款，有限过孔电感）——A 臂
  sheet = 理想 PEC 薄片短路墙（零 x 厚 yz 面、全臂宽，无收束电感）——B 臂
可证伪预测：rod→sheet 谷位上移 Δf/f≈+18~25%（openEMS 引擎偏置使两臂谷位整体
偏高——烟测 rod 谷 ≥3.0 触边截断，故扫频扩至 2.0–4.2GHz、网格锚保持烟测
3.0GHz 档逐字节不变）；**Δ<5% 即证伪过孔假设**（残差归 fringe/端口/引擎侧）。

用法（cwd=仓库根）：
  python scripts/marchand_via_ab.py --plan      # 两变体渲染+exec 几何审计（离线零仿真）
  python scripts/marchand_via_ab.py --collect   # A/B 两轮 openEMS 真跑（共享锁+#261+resume）
  python scripts/marchand_via_ab.py --judge     # 门判读+A/B 差值归因表（离线）

预算预声明（criteria.md 同源，起跑前写死）：单轮 NrTS=150000（G0 档 C→
RFAUTO_NRTS=300000 续跑一次，烟测先例）；单轮硬超时 90min、名义 ~20min（烟测
同档实测 ~15min），两轮名义 ≤1h、PARTIAL 门=1.5×（2.25h）；共享锁
runs/.oe_collect.lock（O_CREAT|O_EXCL、60s 轮询、陈锁 pid 接管）+#261 命令行
互斥查（不代杀）；断点 resume=summary.ok 标记逐变体幂等。

退出码：0=门过/完成；1=门未达/执行失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from rfauto.core.slotline_transitions import (  # noqa: E402
    MARCHAND2_GATES,
    coupled_line_z_matrix,
    marchand_two_section_nominal,
)

# ─── 预声明常量（criteria.md 同源；改判读先改 criteria 再改这里） ──────────────
ROOT = REPO / "runs" / "marchand_via_ab"
PLAN_PATH = ROOT / "plan.json"
CRITERIA_PATH = ROOT / "criteria.md"
VERDICT_PATH = ROOT / "verdict.json"
COLLECT_STATE_PATH = ROOT / "collect_state.json"
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 60.0

VARIANTS: tuple[str, ...] = ("rod", "sheet")
FREQ_RANGE_GHZ = (2.0, 4.2)        # A/B 扩窗（rod 烟测谷 ≥3.0 触边截断、sheet 更高）
NF = 441
NRTS = 150000
NRTS_RETRY = 300000                # G0 档 C → 续跑一次（烟测先例，预声明）
BASE_ANCHOR_F_HI_HZ = 3.0e9        # 网格锚=烟测 F_HI（扩窗不改网格，单变量）
F0_GHZ = 2.5
BAND_GHZ = (2.25, 2.75)
Z_UNBAL_OHM = 50.0
Z_BAL_SE_OHM = 140.0
VIA_SIDE_MM = 0.25
SOLVE_TIMEOUT_S = 90.0 * 60.0      # 单轮硬超时
BUDGET_WALL_S = 60.0 * 60.0        # 两轮名义预算
PARTIAL_FACTOR = 1.5               # 超 1.5× → PARTIAL(超预算)

#: 可证伪预测（电路级；judge 归因结论阈值预声明）
THEORY_L_VIA_NH = 0.7              # HFSS 锚归因估计（Goldfarb-Pucel d=0.25mm 给 1.278nH，并列）
THEORY_NULL_TOL_REL = 0.10         # 实测 Δ 与电路级理论 Δ 相对偏差容忍
VIA_CONFIRMED_MIN_REL = 0.05       # Δ<5% → VIA_FALSIFIED（预声明）

#: HFSS 先验（runs/hfss_marchand_anchor/verdict_b.json 归档实测）
HFSS_PRIOR: dict[str, float] = {
    "s11_null_ghz": 2.04,
    "band_max_s11_db": -10.299805691301849,
    "band_min_s21_db": -3.5758593338569717,
    "band_min_s31_db": -3.564869664441565,
    "band_max_abs_imbalance_db": 0.14683035418360868,
    "band_max_phase_error_deg": 0.6813062563215908,
}

_DESIGN = marchand_two_section_nominal()
_Z0O_OHM = float(_DESIGN.z0o_ohm)


# ─── 纯逻辑（单测钉死面，零引擎零 IO） ────────────────────────────────────────

def via_circuit_s11(freq_ghz, l_via_h: float,
                    design: Any = None) -> Any:
    """两节 Marchand 电路级 S11（短路口经 jωL 过孔电感接地；确定性内核裁判）。

    拓扑与 core marchand_two_section_sparams 同构（两节 z8、external=(0,3,6)、
    opens=(5,)、connections=((1,4))），唯一差异=短路口（2/7）约束由 V=0 改为
    V+jωL·I=0（负载口径：a[k,k]+=jωL，符号经 KCL 复核——2026-09-21 C12）。
    l_via_h=0 时与 core 电路逐位同解（S11(f0)=0，单测钉）。
    """
    import numpy as np

    d = design if design is not None else _DESIGN
    ze, zo = float(d.z0e_ohm), float(d.z0o_ohm)
    zs, zt = float(d.z_unbal_ohm), float(d.z_bal_se_ohm)
    f0 = float(d.f0_ghz)
    f = np.asarray(freq_ghz, dtype=float)
    theta = 0.5 * math.pi * f / f0
    z4 = coupled_line_z_matrix(ze, zo, theta)
    nf = z4.shape[0]
    z8 = np.zeros((nf, 8, 8), dtype=complex)
    z8[:, :4, :4] = z4
    z8[:, 4:, 4:] = z4
    ext = [0, 3, 6]
    zr = np.array([zs, zt, zt], dtype=float)
    a = np.zeros((nf, 8, 8), dtype=complex)
    b = np.zeros((nf, 8, 3), dtype=complex)
    for col, p in enumerate(ext):
        a[:, p, :] = z8[:, p, :]
        a[:, p, p] += zr[col]
        b[:, p, col] = 2.0 * math.sqrt(zr[col])
    for k in (5,):
        a[:, k, k] = 1.0
    w = 2.0 * np.pi * f * 1e9
    lv = float(l_via_h)
    for k in (2, 7):
        a[:, k, :] = z8[:, k, :]
        a[:, k, k] += 1j * w * lv          # V_k + jωL·I_k = 0（过孔电感负载）
    for i, j in ((1, 4),):
        a[:, i, :] = z8[:, i, :] - z8[:, j, :]
        a[:, j, i] = 1.0
        a[:, j, j] = 1.0
    currents = np.linalg.solve(a, b)
    volts = z8 @ currents
    s = np.empty((nf, 3, 3), dtype=complex)
    for row, k in enumerate(ext):
        s[:, row, :] = (volts[:, k, :] - zr[row] * currents[:, k, :]) / (
            2.0 * math.sqrt(zr[row]))
    return s


def theory_null_ghz(l_via_h: float, design: Any = None,
                    f_lo: float = 1.2, f_hi: float = 4.5,
                    n: int = 3301) -> float:
    """电路级 S11 零点（|S11| 最小频点；栅距 ≈1MHz，单测钉 0.7nH→2.046）。"""
    import numpy as np

    f = np.linspace(float(f_lo), float(f_hi), int(n))
    s = via_circuit_s11(f, l_via_h, design)
    return float(f[int(np.argmin(np.abs(s[:, 0, 0])))])


def via_l_from_nulls(f_rod_ghz: float, f_sheet_ghz: float,
                     z0o_ohm: float = _Z0O_OHM) -> float:
    """谷位对反演等效过孔电感（H）：θ_via=90°(1−f_rod/f_sheet)、L=Z0o·tanθ/(2π·f_rod)。

    机理口径=短路副线谐振 θ+θ_via=90°（t_res=Z0o/(ωL)）；f_sheet≤f_rod 时 θ≤0
    显式报错（薄片不可能更低，方向守卫）。
    """
    fr, fs = float(f_rod_ghz), float(f_sheet_ghz)
    if not (0.0 < fr < fs):
        raise ValueError(f"via_l_from_nulls: 须 f_rod < f_sheet，得 ({fr}, {fs})")
    theta = 0.5 * math.pi * (1.0 - fr / fs)
    if not 0.0 < theta < 0.5 * math.pi:
        raise ValueError(f"via_l_from_nulls: θ_via 越域 {theta:.4f} rad")
    return float(z0o_ohm) * math.tan(theta) / (2.0 * math.pi * fr * 1e9)


def attribution_table(f_rod: float | None, f_sheet: float | None,
                      f0_ghz: float = F0_GHZ,
                      z0o_ohm: float = _Z0O_OHM,
                      sweep_ghz: tuple[float, float] = FREQ_RANGE_GHZ,
                      censored: dict[str, bool] | None = None) -> dict[str, Any]:
    """A/B 谷位差值归因表（如实分解：过孔份额+理想短路后剩余，缺测项 UNKNOWN）。"""
    cens = dict(censored or {})
    th_lo = float(sweep_ghz[0])
    th_hi = float(sweep_ghz[1])
    out: dict[str, Any] = {
        "f0_ghz": float(f0_ghz), "sweep_ghz": [th_lo, th_hi],
        "f_null_ghz": {"rod": f_rod, "sheet": f_sheet},
        "censored": cens,
        "theory": {
            "l_via_nh_list": [0.0, THEORY_L_VIA_NH,
                              round(_gp_l_via_nh(VIA_SIDE_MM), 3)],
            "null_ghz": [round(theory_null_ghz(lv * 1e-9), 4)
                         for lv in (0.0, THEORY_L_VIA_NH,
                                    round(_gp_l_via_nh(VIA_SIDE_MM), 3))],
            "hfss_prior_null_ghz": HFSS_PRIOR["s11_null_ghz"],
            "hfss_vs_theory_dev_pct": round(
                (HFSS_PRIOR["s11_null_ghz"]
                 - theory_null_ghz(THEORY_L_VIA_NH * 1e-9))
                / theory_null_ghz(THEORY_L_VIA_NH * 1e-9) * 100.0, 2),
        },
    }
    if cens.get("rod") or cens.get("sheet"):
        out["conclusion"] = "INCONCLUSIVE(谷位触扫频边→扩窗复跑)"
        return out
    if f_rod is None or f_sheet is None:
        out["conclusion"] = "INCONCLUSIVE(谷位缺测)"
        return out
    delta_rel = (float(f_sheet) - float(f_rod)) / float(f_rod)
    th_rod = theory_null_ghz(THEORY_L_VIA_NH * 1e-9)
    th_sheet = theory_null_ghz(0.0)
    theory_rel = (th_sheet - th_rod) / th_rod
    out["delta_via_rel"] = round(delta_rel, 6)
    out["delta_via_pct"] = round(delta_rel * 100.0, 2)
    out["residual_after_sheet_rel"] = round((float(f0_ghz) - float(f_sheet))
                                            / float(f0_ghz), 6)
    out["residual_after_sheet_pct"] = round(out["residual_after_sheet_rel"] * 100.0, 2)
    try:
        out["l_via_eff_nh"] = round(via_l_from_nulls(f_rod, f_sheet, z0o_ohm) * 1e9, 4)
    except ValueError as exc:
        out["l_via_eff_nh"] = f"UNAVAILABLE({exc})"
    out["theory_rel"] = round(theory_rel, 6)
    if delta_rel < VIA_CONFIRMED_MIN_REL:
        out["conclusion"] = "VIA_FALSIFIED(Δ<5%：过孔假设不成立，残差归 fringe/端口/引擎侧)"
    elif abs(delta_rel - theory_rel) <= THEORY_NULL_TOL_REL * theory_rel:
        out["conclusion"] = (f"VIA_CONFIRMED(Δ={out['delta_via_pct']}% 与电路级理论 "
                             f"{theory_rel * 100:.1f}% 同向贴量；过孔电感为 −18% 主体)")
    else:
        out["conclusion"] = (f"VIA_CONFIRMED_DIRECTION(Δ={out['delta_via_pct']}% 同向但"
                             f"偏离理论 {theory_rel * 100:.1}% 超 "
                             f"{THEORY_NULL_TOL_REL * 100:.0f}%——有效 L 偏离估计值，如实列账)")
    return out


def _gp_l_via_nh(via_side_mm: float, h_mm: float = 1.524) -> float:
    """Goldfarb-Pucel 过孔电感工程式 L=(μ0/2π)·h·[ln(4h/d)+1]（NH；估计口径）。"""
    mu0 = 4.0e-7 * math.pi
    h = float(h_mm) * 1e-3
    d = float(via_side_mm) * 1e-3
    return mu0 / (2.0 * math.pi) * h * (math.log(4.0 * h / d) + 1.0) * 1e9


def g0_tier(decay: dict[str, dict[str, float]]) -> str:
    """G0 收敛档（#344 预声明）：A 采信/B 良性截断/C 被困嫌疑→续跑一次。"""
    worst_tail = max(float(d["tail10_rel_db"]) for d in decay.values())
    worst_slope = max(float(d["tail_slope_db_per_ns"]) for d in decay.values())
    if worst_tail <= -40.0 and worst_slope <= -1.0:
        return "A"
    if worst_tail <= -30.0 and worst_slope <= -1.0:
        return "B"
    return "C"


def metrics_from_summary(summ: dict[str, Any], rows: list[dict[str, str]],
                         band_ghz: tuple[float, float] = BAND_GHZ,
                         f0_ghz: float = F0_GHZ,
                         z_unbal_ohm: float = Z_UNBAL_OHM,
                         z_bal_se_ohm: float = Z_BAL_SE_OHM) -> dict[str, Any]:
    """主判估计量（驻波免疫，烟测 judge.py 同法单源移植）：Zin 直变换 Γ50+功率法。

    rows=sparams.csv DictReader 行（freq_hz/beta_rad_m 列）；返回带内门量+门判定
    +S11 零点（含触边截断旗标）+线基次口径交叉核对（β 合理性建议项）。
    """
    import numpy as np

    def _cx(d):
        return np.array(d["re"]) + 1j * np.array(d["im"])

    f = np.array([float(r["freq_hz"]) for r in rows])
    if len(f) != int(summ.get("nf", len(f))):
        raise ValueError(f"metrics_from_summary: nf 不一致 rows={len(f)} "
                         f"summary={summ.get('nf')}")
    i0 = int(np.argmin(np.abs(f - f0_ghz * 1e9)))
    ib = (f >= band_ghz[0] * 1e9) & (f <= band_ghz[1] * 1e9)
    u1i, u1r = _cx(summ["uf1_inc"]), _cx(summ["uf1_ref"])
    u2r, u2i = _cx(summ["uf2_ref"]), _cx(summ["uf2_inc"])
    u3r, u3i = _cx(summ["uf3_ref"]), _cx(summ["uf3_inc"])
    z1 = _cx(summ["z1_ref"])
    beta = np.array([float(r["beta_rad_m"]) for r in rows])
    # 原始 u/i（线性恒等式还原，不含任何分解产物）
    i1 = (u1i - u1r) / z1
    i2 = (u2i - u2r) / z_bal_se_ohm
    i3 = (u3i - u3r) / z_bal_se_ohm
    u1t = u1i + u1r
    zin = u1t / i1
    # 符号定约：被动结构要求带内 median Re(Zin)>0（如实记录）
    sgn = 1.0 if float(np.median(np.real(zin[ib]))) >= 0 else -1.0
    zin = sgn * zin
    gamma = (zin - z_unbal_ohm) / (zin + z_unbal_ohm)
    p_in = 0.5 * np.real(u1t * np.conj(i1)) * sgn
    p_avail = p_in / (1.0 - np.abs(gamma) ** 2)
    p2 = 0.5 * z_bal_se_ohm * np.abs(i2) ** 2
    p3 = 0.5 * z_bal_se_ohm * np.abs(i3) ** 2
    ok_pa = p_avail > 0
    a21 = np.sqrt(np.where(ok_pa, p2 / np.where(ok_pa, p_avail, 1.0), 0.0))
    a31 = np.sqrt(np.where(ok_pa, p3 / np.where(ok_pa, p_avail, 1.0), 0.0))
    s21 = a21 * np.exp(1j * np.angle(u2r))
    s31 = a31 * np.exp(1j * np.angle(u3r))

    def _db(x):
        return 20.0 * np.log10(np.maximum(np.abs(x), 1e-300))

    s11_db, s21_db, s31_db = _db(gamma), _db(s21), _db(s31)
    imb = s21_db - s31_db
    ph = np.degrees(np.angle(s31 * np.conj(s21)))
    ph_err = np.abs(np.abs(ph) - 180.0)
    metrics = {
        "band_ghz": list(band_ghz),
        "band_max_s11_db": float(np.max(s11_db[ib])),
        "band_min_s21_db": float(np.min(s21_db[ib])),
        "band_min_s31_db": float(np.min(s31_db[ib])),
        "band_max_abs_imbalance_db": float(np.max(np.abs(imb[ib]))),
        "band_max_phase_error_deg": float(np.max(ph_err[ib])),
        "s11_db_f0": float(s11_db[i0]), "s21_db_f0": float(s21_db[i0]),
        "s31_db_f0": float(s31_db[i0]), "phase_diff_deg_f0": float(ph[i0]),
    }
    gates = {
        "band_max_s11_le_minus10db":
            bool(metrics["band_max_s11_db"] <= MARCHAND2_GATES["band_max_s11_db_le"]),
        "band_min_s21_ge_minus3p5db":
            bool(metrics["band_min_s21_db"] >= MARCHAND2_GATES["band_min_s21_db_ge"]),
        "band_min_s31_ge_minus3p5db":
            bool(metrics["band_min_s31_db"] >= MARCHAND2_GATES["band_min_s31_db_ge"]),
        "amp_imbalance_le_1db":
            bool(metrics["band_max_abs_imbalance_db"] <=
                 MARCHAND2_GATES["band_max_abs_imbalance_db_le"]),
        "phase_error_le_10deg":
            bool(metrics["band_max_phase_error_deg"] <=
                 MARCHAND2_GATES["band_max_phase_error_deg_le"]),
    }
    i_null = int(np.argmin(np.abs(gamma)))
    censored = bool(i_null == 0 or i_null == len(f) - 1)
    # 线基次口径交叉核对（β 合理性建议项，烟测 judge 同法）
    from rfauto.core.synthesis import Stackup, forward_z0

    stack = Stackup(name="marchand2", epsilon_r=3.66, thickness_mm=1.524,
                    loss_tangent=0.0037)
    _, eps_hj = forward_z0(float(_DESIGN.w_mm), f0_ghz, stack)
    beta_hj = 2 * math.pi * f0_ghz * 1e9 * math.sqrt(eps_hj) / 299792458.0
    beta_dev_pct = float((beta[i0] - beta_hj) / beta_hj * 100.0)
    lb_xcheck = {"beta_sane": bool(abs(beta_dev_pct) <= 10.0),
                 "beta_dev_pct": round(beta_dev_pct, 3),
                 "beta_hj_rad_m": float(beta_hj),
                 "beta_engine_f0": float(beta[i0]),
                 "eps_eff_hj": float(eps_hj),
                 "note": "β 建议项非门（激励口 local β 为提取伪像）"}
    return {"metrics": metrics, "gates": gates, "all_gates_pass": all(gates.values()),
            "s11_null_ghz": float(f[i_null] / 1e9),
            "s11_null_censored": censored,
            "s11_passive_violation_pts": int(np.sum(np.abs(gamma) > 1.05)),
            "zin_sign_multiplier": sgn, "zin_f0_ohm":
                [float(zin[i0].real), float(zin[i0].imag)],
            "lb_xcheck": lb_xcheck,
            "mask": {"S11": True, "S21": True, "S31": True, "S23": False,
                     "note": "S23（隔离）单激励未测不判（#314）"}}


def recompute_decay(t, uts: dict[str, Any]) -> dict[str, dict[str, float]]:
    """G0 衰减统计独立重算（渲染侧同法；judge 从 port_time.npz 出发不信任 summary）。"""
    import numpy as np

    t = np.asarray(t, dtype=float)
    out = {}
    for tag, ut in uts.items():
        ut = np.abs(np.asarray(ut, dtype=float))
        post = ut[t > 2.0e-9]
        peak = float(np.max(post)) if len(post) else 0.0
        n10 = max(1, int(0.10 * len(t)))
        tail = float(np.max(ut[-n10:])) if len(ut) else 0.0
        n5 = max(2, len(t) // 2)
        tt, uu = t[-n5:], ut[-n5:]
        seg = max(2, len(tt) // 6)
        floor = max(peak * 1e-12, 1e-30)
        xs = [20 * math.log10(max(float(np.max(uu[i * seg:(i + 1) * seg])), floor))
              for i in range(6)]
        xc = [float(np.median(tt[i * seg:(i + 1) * seg])) for i in range(6)]
        slope = float(np.polyfit(xc, xs, 1)[0]) * 1e-9
        out[tag] = {"t_end_ns": float(t[-1] * 1e9), "post_pulse_peak": peak,
                    "tail10_rel_db": 20 * math.log10(max(tail, 1e-30)
                                                     / max(peak, 1e-30)),
                    "tail_slope_db_per_ns": slope}
    return out


# ─── 编排（真机面：锁/#261/断点续跑；离线面：渲染审计/判读） ──────────────────

def _variant_dir(mode: str) -> Path:
    return ROOT / mode


def _render_variant(mode: str) -> tuple[Path, str]:
    from rfauto.adapters.openems_templates import render_marchand2_script

    text = render_marchand2_script(
        FREQ_RANGE_GHZ, via_mode=mode, via_side_mm=VIA_SIDE_MM,
        nrts=NRTS, base_anchor_f_hi_hz=BASE_ANCHOR_F_HI_HZ)
    vd = _variant_dir(mode)
    vd.mkdir(parents=True, exist_ok=True)
    path = vd / "render_script.py"
    path.write_text(text, encoding="utf-8")
    return path, text


def _exec_audit(path: Path, text: str) -> dict[str, Any]:
    """离线 exec 几何审计（零仿真；FDTD.Run 截断口径，factory_m3 同法）。"""
    cut = text.index("FDTD.Run(")
    scope: dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    try:
        exec(compile(text[:cut], str(path), "exec"), scope)
    except SystemExit as exc:                       # audit FAIL 的渲染脚本出口
        raise RuntimeError(f"渲染脚本审计出口 rc={exc.code}（audit FAIL）") from exc
    audit = scope.get("audit")
    if not isinstance(audit, dict) or "all_pass" not in audit:
        raise RuntimeError("exec 后无 audit（渲染契约破坏？）")
    return audit


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CRITERIA_TEXT = """# criteria.md — C12 过孔 PEC 薄片单变量对照（起跑前预声明，{ts}）

## 问题钉死（语境）

- −18%=HFSS 巴伦锚全波中心（S11 零点 2.04GHz）比理想电路（2.5GHz）低 ≈18%
  （runs/hfss_marchand_anchor 归档）。
- engine_z0_correction（PCHIP 4 点）=openEMS 引擎 Z0 偏差修正，与
  HFSS −18% 结构效应正交——本对照**固定名义设计**（reference 口径，未做预畸
  变），单变量只有过孔表征。Z0 修正后的全波复跑（engine="openems" 设计）留
  独立项，不在本 A/B 混变量。
- 电路级预判（core 耦合线 Z 矩阵+短路口 jωL 负载约束）：L=0.7nH → 谷
  2.046GHz（对 HFSS 2.04 偏 +0.3%）——**−18% 主体可由过孔电感定量复现**。

## A/B 单变量

- 臂 A=rod：0.25mm 方柱贯通 z∈[0,H]（现状=runs/smoke_marchand_2sect 逐字节
  口径；HFSS 锚 VIA_SIDE_MM 同款，有限过孔电感）。
- 臂 B=sheet：理想 PEC 薄片短路墙（零 x 厚 yz 面、全臂宽、z∈[0,H]，无收束
  电感；followUp ① 登记口径）。
- 两臂网格线/端口/域/激励逐字节一致（rod 专属过孔网格线在 sheet 保留为纯
  加密）；渲染全文 diff 恰=VIA_MODE 行+过孔原语段（单测钉）。
- 名义几何：core marchand_two_section_nominal()（50Ω→280Ω 差分，
  (w,s,ℓ)=(1.7616,0.1016,18.467)mm @h=1.524/εr=3.66）。

## 预算（起跑前写死）

- 单轮 NrTS=150000、G0 档 C → RFAUTO_NRTS=300000 续跑一次（烟测先例）；
  网格锚=烟测 3.0GHz 档（BASE=1.0447/NEAR=0.2612mm 逐字节一致，扩窗不改网格）。
- 单轮硬超时 90min、名义 ~20min（烟测同档实测 ~15min）；两轮名义 ≤1h，
  **PARTIAL 门=1.5×（2.25h）**。
- 共享锁 runs/.oe_collect.lock + #261 命令行互斥查（不代杀）；断点 resume=
  summary.ok 逐变体幂等；判据/产出零改写（判读独立于渲染侧产物）。

## 扫频与判读带

- 扫频 2.0–4.2GHz、441 点（rod 烟测谷 ≥3.0 触边截断、sheet 预期更高——扩窗
  预声明）；判读带=f0±10%=2.25–2.75GHz；门=MARCHAND2_GATES（core 单源，
  逐臂如实判定，不凑绿——本实验判据是归因不是门冲绿）。
- 任何频点 |S11|>1.05 → 先查截断再谈物理（#262）。
- S11 零点触扫频端点（i=0/N−1）→ 记 censored，归因结论 INCONCLUSIVE（扩窗
  复跑），不得用边端假谷归因。

## 估计量（烟测 judge 同法单源移植）

- 主口径（驻波免疫）：Γ50=(Zin−50)/(Zin+50)（Zin=U_tot/I_tot 线性恒等式）；
  |S21|/|S31| 由端口吸收功率/入射可用功率；不平衡=功率比；相位差=出波相对
  相位。符号定约=带内 median Re(Zin)≥0（如实记录）。
- 次口径（交叉核对，非门）：线基分解+显式重归一 50Ω；β_dev>10% 记 beta_sane
  False 建议（激励口 local β 为提取伪像）。
- G0 档（#344）：judge 从 port_time.npz 独立重算（不信任 summary）；A ≤−40dB
  且斜率 ≤−1dB/ns；B ≤−30dB；C 其余。

## 归因规则（预声明，#122 不凑绿）

- 主量=谷位：delta_via_rel=(f_sheet−f_rod)/f_rod（过孔表征贡献，预期 +18~25%
  同向理论）；Δ<5% → **VIA_FALSIFIED**（过孔假设不成立，残差归 fringe/端口/
  引擎侧）；|Δ−理论|≤10%·理论 → VIA_CONFIRMED；同向超差 → 如实列账（有效 L
  偏离估计）。
- 等效过孔电感反演：θ_via=90°(1−f_rod/f_sheet)、L_eff=Z0o·tanθ/(2π·f_rod)
  （Z0o=36.489Ω）——**估计口径**：孤立短截线式忽略耦合加载，对电路级真值
  0.7nH 回收 0.832nH（+18.9% 模型偏，单测钉）；对照 Goldfarb-Pucel 1.278nH
  （d=0.25mm）与 HFSS 估计 0.7nH，均按估计列账（主判=Δ 谷位，非 L 反演）。
- 剩余失谐：residual_after_sheet=(f0−f_sheet)/f0（理想短路后仍偏离 f0 的份额
  →归 Z0/端口/引擎/fringe，本实验不下单臂结论）。
- dB 面并列：逐臂带内门量+A/B 差值如实进表（−18% 是频移效应，dB 差为副量）。
"""


def cmd_plan() -> int:
    """两变体渲染+exec 几何审计（离线零仿真）；plan.json 不可变（resume 幂等）。"""
    ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    CRITERIA_PATH.write_text(CRITERIA_TEXT.format(ts=ts), encoding="utf-8")
    entries: dict[str, Any] = {}
    if PLAN_PATH.exists():
        old = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        print(f"[ab] plan.json 已存在（不可变，sha 校验幂等）：{PLAN_PATH}")
        entries = old.get("variants", {})
    for mode in VARIANTS:
        path, text = _render_variant(mode)
        sha = _sha256_text(text)
        prev = entries.get(mode) or {}
        if prev.get("sha256") not in (None, sha):
            print(f"[ab] {mode} 渲染文本 sha 漂移（{prev.get('sha256')[:12]}→{sha[:12]}）"
                  "——判据/渲染器被改，拒绝静默复用旧 plan")
            return 1
        audit = _exec_audit(path, text)
        entries[mode] = {
            "script": str(path), "sha256": sha,
            "all_pass": bool(audit["all_pass"]),
            "via_guard": audit.get("via_guard"),
            "via": audit.get("via"),
            "mesh_lines": audit.get("mesh_lines"),
            "min_span_m": audit.get("min_span_m"),
        }
        print(f"[ab] {mode}: 渲染+exec 审计 all_pass={audit['all_pass']} "
              f"via_guard={audit.get('via_guard')}")
        if not audit["all_pass"]:
            print(f"[ab] {mode} 审计 FAIL——不起跑（修渲染器/守卫后再 --plan）")
            return 1
    plan = {
        "kind": "marchand_via_ab_plan", "created_utc": ts,
        "criteria": str(CRITERIA_PATH),
        "variants": entries,
        "declared": {
            "freq_range_ghz": FREQ_RANGE_GHZ, "nf": NF, "nrts": NRTS,
            "nrts_retry": NRTS_RETRY, "base_anchor_f_hi_hz": BASE_ANCHOR_F_HI_HZ,
            "band_ghz": BAND_GHZ, "via_side_mm": VIA_SIDE_MM,
            "solve_timeout_s": SOLVE_TIMEOUT_S, "budget_wall_s": BUDGET_WALL_S,
            "partial_factor": PARTIAL_FACTOR,
            "theory_null_ghz_l07nh": round(theory_null_ghz(THEORY_L_VIA_NH * 1e-9), 4),
            "gp_l_via_nh_d025": round(_gp_l_via_nh(VIA_SIDE_MM), 3),
            "prediction": "rod→sheet 谷位上移 +18~25%；Δ<5% → VIA_FALSIFIED",
        },
    }
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"[ab] plan 落盘：{PLAN_PATH}（判据 {CRITERIA_PATH}）")
    return 0


def _pid_alive(pid: int) -> bool | None:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
            capture_output=True, text=True, timeout=30)
        return str(pid) in (out.stdout or "")
    except Exception:
        return None


def acquire_lock(task: str, poll_s: float = LOCK_POLL_S) -> None:
    """O_CREAT|O_EXCL 原子建锁；占用则 60s 轮询（factory_m3 先例，陈锁 pid 接管）。"""
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"task": task,
                       "ts": datetime.now(timezone.utc).isoformat(),
                       "pid": os.getpid()}
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            os.close(fd)
            return
        except FileExistsError:
            holder: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                holder = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            pid = holder.get("pid")
            alive = _pid_alive(pid) if isinstance(pid, int) else None
            if alive is False:
                print(f"[ab] 陈锁接管（持有者 pid={pid} 已死）：{holder}")
                with contextlib.suppress(OSError):
                    LOCK_PATH.unlink()
                continue
            print(f"[ab] 锁被占（{holder or '未知持有者'}），{poll_s:.0f}s 后重试…",
                  flush=True)
            time.sleep(poll_s)


def release_lock(owner_pid: int) -> None:
    """删锁（删前校验内容 pid=自身，防误删后到者锁；best-effort #105）。"""
    try:
        holder = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        if holder.get("pid") == owner_pid:
            LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def oe_foreign_running() -> list[str]:
    """#261 互斥查：python 进程 CommandLine 含 _rfauto_runner|simulation.py。

    自身名不入模式（#261 自锁坑：互斥模式含自身名会命中自身 shim+解释器
    对死锁；自身求解期真互斥由他侧检查承担）。

    临时 .ps1 经 powershell -NoProfile -ExecutionPolicy Bypass -File 执行
    （#289：内联 $_ 会被 shell 层展开）。探测失败=如实抛错（fail-closed）。
    """
    ROOT.mkdir(parents=True, exist_ok=True)
    ps1 = ROOT / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match "
        "'_rfauto_runner|simulation\\.py' } | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        with contextlib.suppress(OSError):
            ps1.unlink()
    if out.returncode != 0:
        raise RuntimeError(f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]


def _solve_once(mode: str, nrts: int, t_deadline: float | None) -> tuple[bool, float]:
    """单轮真跑（子进程隔离；console 落日志；返回 (ok, wall_s)）。"""
    vd = _variant_dir(mode)
    script = vd / "render_script.py"
    t0 = time.monotonic()
    env = dict(os.environ)
    env.pop("RFAUTO_SKIP_RUN", None)
    env["RFAUTO_NRTS"] = str(nrts)
    log_path = vd / f"console_nrts{nrts}.log"
    timeout = SOLVE_TIMEOUT_S
    if t_deadline is not None:
        timeout = max(60.0, min(timeout, t_deadline - time.monotonic()))
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(vd),
                              env=env, stdout=log, stderr=subprocess.STDOUT,
                              timeout=timeout)
    wall = time.monotonic() - t0
    summ_path = vd / "summary.json"
    ok = proc.returncode == 0 and summ_path.exists()
    if ok:
        with open(summ_path, encoding="utf-8") as fh:
            ok = bool(json.load(fh).get("ok"))
    print(f"[ab] {mode} nrts={nrts} rc={proc.returncode} wall={wall:.0f}s "
          f"ok={ok}（日志 {log_path.name}）", flush=True)
    return ok, wall


def cmd_collect() -> int:
    """A/B 两轮 openEMS 真跑（共享锁内整段；断点 resume 幂等；预算 PARTIAL 门）。"""
    if not PLAN_PATH.exists():
        print("[ab] 无 plan.json（先 --plan）")
        return 2
    if str(Path.cwd().resolve()) != str(REPO.resolve()):
        print(f"[ab] 拒跑：cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
        return 2
    owner_pid = os.getpid()
    acquire_lock("marchand_via_ab")
    t0 = time.monotonic()
    state: dict[str, Any] = {"variants": {}, "partial_budget": False}
    try:
        foreign = oe_foreign_running()
        if foreign:
            print("[ab] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：\n"
                  + "\n".join(f"  {ln}" for ln in foreign[:10]))
            return 1
        print("[ab] #261 命令行查：无他轨 OE 进程，锁内起跑")
        for mode in VARIANTS:
            vd = _variant_dir(mode)
            summ_path = vd / "summary.json"
            if summ_path.exists():
                with open(summ_path, encoding="utf-8") as fh:
                    if json.load(fh).get("ok"):
                        print(f"[ab] {mode} summary.ok 已在（resume 跳过）")
                        state["variants"][mode] = {"status": "done(resume)"}
                        continue
            ok, wall = _solve_once(mode, NRTS, t0 + BUDGET_WALL_S * PARTIAL_FACTOR)
            rec: dict[str, Any] = {"status": "done" if ok else "failed",
                                   "wall_s": round(wall, 1), "nrts": NRTS}
            # G0 档 C → NrTS 续跑一次（预声明；烟测先例）
            tier = None
            if ok:
                with open(summ_path, encoding="utf-8") as fh:
                    decay = json.load(fh).get("decay", {})
                tier = g0_tier(decay) if decay else None
                if tier == "C":
                    print(f"[ab] {mode} G0 档 C → RFAUTO_NRTS={NRTS_RETRY} 续跑一次")
                    if (vd / "summary.json").exists():
                        (vd / "summary_run1.json").write_bytes(
                            (vd / "summary.json").read_bytes())
                    ok2, wall2 = _solve_once(mode, NRTS_RETRY,
                                             t0 + BUDGET_WALL_S * PARTIAL_FACTOR)
                    rec["retry_nrts"] = NRTS_RETRY
                    rec["retry_wall_s"] = round(wall2, 1)
                    rec["retry_ok"] = ok2
                    rec["run1_g0_tier"] = tier
                    ok = ok2
                    wall += wall2
                    if ok:
                        with open(summ_path, encoding="utf-8") as fh:
                            tier = g0_tier(json.load(fh).get("decay", {}))
            rec["g0_tier"] = tier
            rec["wall_s"] = round(wall, 1)
            state["variants"][mode] = rec
            if not ok:
                print(f"[ab] {mode} FAIL（留档续跑：重跑 --collect 即 resume）")
        wall_total = time.monotonic() - t0
        state["wall_total_s"] = round(wall_total, 1)
        state["partial_budget"] = bool(wall_total > BUDGET_WALL_S * PARTIAL_FACTOR)
    finally:
        with contextlib.suppress(Exception):
            state["finished_utc"] = datetime.now(timezone.utc).isoformat()
            COLLECT_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
        release_lock(owner_pid)
    n_done = sum(1 for v in state["variants"].values()
                 if isinstance(v, dict) and str(v.get("status", "")).startswith("done"))
    print(f"[ab] collect 完成 done={n_done}/2 wall={state.get('wall_total_s')}s "
          f"partial_budget={state['partial_budget']}")
    return 0 if n_done == 2 else 1


def cmd_judge() -> int:
    """门判读+A/B 差值归因表（离线；同频轴对齐+G0 独立重算+如实分解）。"""
    import csv

    import numpy as np

    if not PLAN_PATH.exists():
        print("[ab] 无 plan.json（先 --plan）")
        return 2
    variants: dict[str, Any] = {}
    freq_axes = []
    for mode in VARIANTS:
        vd = _variant_dir(mode)
        summ_path = vd / "summary.json"
        csv_path = vd / "sparams.csv"
        npz_path = vd / "port_time.npz"
        if not (summ_path.exists() and csv_path.exists()):
            print(f"[ab] {mode} 缺产物（summary/sparams）——先 --collect")
            return 2
        with open(summ_path, encoding="utf-8") as fh:
            summ = json.load(fh)
        with open(csv_path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        f_axis = [float(r["freq_hz"]) for r in rows]
        freq_axes.append(f_axis)
        judged = metrics_from_summary(summ, rows)
        # 同频轴对齐预检（#287/#294 家族：同栅才可比，异栅显式报错不插值）
        summ_axis = summ.get("uf1_inc", {}).get("re", [])
        judged["axis_len_match"] = bool(len(summ_axis) == len(f_axis))
        # G0 独立重算（#344 口径：不信任渲染侧 decay）
        g0 = None
        if npz_path.exists():
            npz = np.load(npz_path)
            decay = recompute_decay(npz["t"], {"p1": npz["ut1"], "p2": npz["ut2"],
                                               "p3": npz["ut3"]})
            g0 = {"tier": g0_tier(decay), "per_port": decay,
                  "s11_passive_violation_pts":
                      int(judged["s11_passive_violation_pts"])}
        variants[mode] = {
            "summary_effective": {k: summ.get(k) for k in
                                  ("via_mode", "via_side_mm", "nrts_declared",
                                   "base_mm", "near_mm", "f_lo_hz", "f_hi_hz", "nf")},
            "judged": judged, "g0": g0,
            "hfss_prior": {k: HFSS_PRIOR[k]
                           for k in ("band_max_s11_db", "band_min_s21_db",
                                     "band_min_s31_db", "band_max_abs_imbalance_db",
                                     "band_max_phase_error_deg")},
        }
    if not np.array_equal(np.array(freq_axes[0]), np.array(freq_axes[1])):
        print("[ab] 两变体频轴不一致（#287 家族：同栅才可比）——判读拒绝")
        return 1
    cens = {m: bool(variants[m]["judged"]["s11_null_censored"]) for m in VARIANTS}
    attribution = attribution_table(
        variants["rod"]["judged"]["s11_null_ghz"],
        variants["sheet"]["judged"]["s11_null_ghz"],
        censored=cens)
    gates_verdict = {m: ("PASS" if variants[m]["judged"]["all_gates_pass"] else "FAIL")
                     for m in VARIANTS}
    budget = None
    if COLLECT_STATE_PATH.exists():
        with open(COLLECT_STATE_PATH, encoding="utf-8") as fh:
            st = json.load(fh)
        budget = {"wall_total_s": st.get("wall_total_s"),
                  "partial_budget": st.get("partial_budget")}
    verdict = {
        "item": "C12 marchand_via_ab",
        "kind": "过孔 PEC 薄片单变量对照（rod vs sheet，名义设计固定）",
        "criteria": str(CRITERIA_PATH),
        "design_source": "core/slotline_transitions.marchand_two_section_nominal()",
        "z0_correction_status": (
            "engine_z0_correction（PCHIP 4 点）未参与本对照——其修正对象为 openEMS "
            "Z0 引擎偏差，与 HFSS −18% 结构效应正交；本 A/B 固定名义设计（单变量），"
            "Z0 修正后全波复跑留独立项"),
        "variants": variants,
        "ab_attribution": attribution,
        "gate_verdict_per_variant": gates_verdict,
        "note_gates": ("巴伦门逐臂如实判定（本实验判据=归因非门冲绿，#122）；"
                       "S23 单激励未测不判（#314）"),
        "budget": budget,
        "artifacts": ["rod/summary.json", "sheet/summary.json", "rod/sparams.csv",
                      "sheet/sparams.csv", "rod/port_time.npz",
                      "sheet/port_time.npz"],
    }
    VERDICT_PATH.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps({"null_ghz": attribution.get("f_null_ghz"),
                      "delta_via_pct": attribution.get("delta_via_pct"),
                      "l_via_eff_nh": attribution.get("l_via_eff_nh"),
                      "residual_after_sheet_pct":
                          attribution.get("residual_after_sheet_pct"),
                      "theory": attribution.get("theory"),
                      "conclusion": attribution.get("conclusion"),
                      "gates": gates_verdict, "g0_tiers":
                          {m: (variants[m]["g0"] or {}).get("tier") for m in VARIANTS}},
                     ensure_ascii=False, indent=1))
    print(f"[ab] verdict 落盘：{VERDICT_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C12 过孔 PEC 薄片单变量对照 A/B")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="渲染+exec 几何审计（离线）")
    g.add_argument("--collect", action="store_true", help="A/B 两轮真跑（锁+#261+resume）")
    g.add_argument("--judge", action="store_true", help="门判读+归因表（离线）")
    args = ap.parse_args(argv)
    if args.plan:
        return cmd_plan()
    if args.collect:
        return cmd_collect()
    return cmd_judge()


if __name__ == "__main__":
    raise SystemExit(main())
