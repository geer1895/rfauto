"""Wheeler cap 效率对照门（ge7 followUp ④，确定性内核，规则 7）。

ge6 预验缺陷（runs/ge6_oewin/wheeler/README §归因 3，如实记）：旧 G2 对照门
只设单侧下限（η ≥ 0.95），未设上限——attempt3 无损腔 DFT 截断污染致
Re(Zcap)=-10.4Ω 噪声 → η_wh_pec=1.3380 **钻单侧门空瑕假 PASS**。本模块把
效率对照门定为双侧带 [0.90, 1.05] 并对直接远场法（η_ff=Prad/P_acc）与
Wheeler cap 法（η_wh=1−Re(Z_cap)/Re(Z_free)）统一判读。

预声明（runs/ge7_wheeler/criteria.md §1，判据先行 #122，先于任何 ge7 仿真）：
- 下沿 0.90 = 1−0.10（与 10pp 主门同宽容度）；
- 上沿 1.05 = 能量守恒级数值噪声上限（attempt3 η_ff_pec=1.0331 实测即此
  量级）；η>1.05 常为"cap 内损耗高估/Re(Zcap)<0 噪声"病理，必须拦。
- ok=None 表示不可判读（η 缺失/非有限/分母守卫触发），不虚构（#105）。

调用方：runs/ge7_wheeler/ 探针驱动（本目录产物）；不进计算器注册表、
不动 facade（public_api 金快照零漂移为设计约束）。
"""
from __future__ import annotations

import math
from typing import Any

#: 效率双侧带（预声明，见模块 docstring；改动=显式评审动作）
ETA_BAND: tuple[float, float] = (0.90, 1.05)
#: 主门宽容度（个百分点）：|η_ff − η_wh| 上限
DIFF_TOL_PP: float = 10.0
#: Wheeler 公式分母守卫：|Re(Z_free)| 低于此值判不可读（噪声分母）
Z_FREE_GUARD_OHM: float = 5.0


def wheeler_eta(re_z_cap: float, re_z_free: float) -> float | None:
    """Wheeler cap 效率估计 η = 1 − Re(Z_cap)/Re(Z_free)。

    不可判读条件（返回 None，#105 如实）：入参非有限，或 |Re(Z_free)| ≤
    守卫值（分母是噪声）。注意 attempt3 病理形态：Re(Z_cap) 为负 → η>1
    ——本函数不做带判（那是 eta_band_gate 的职责），只忠实给出估计值。
    """
    try:
        rc = float(re_z_cap)
        rf = float(re_z_free)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(rc) and math.isfinite(rf)):
        return None
    if abs(rf) <= Z_FREE_GUARD_OHM:
        return None
    return 1.0 - rc / rf


def eta_band_gate(value: float | None,
                  lo: float = ETA_BAND[0],
                  hi: float = ETA_BAND[1]) -> dict[str, Any]:
    """η 双侧带判读（与 ui_service.patch_eta_gate 同返回形态）。

    返回 {gate:[lo,hi], value, ok(True/False/None), reason}；value 为
    None/NaN/Inf → ok=None（不可判读，不虚构）。
    """
    out: dict[str, Any] = {"gate": [lo, hi], "value": value,
                           "ok": None, "reason": ""}
    if value is None:
        out["reason"] = "η 不可得（分母守卫或输入缺失）"
        return out
    v = float(value)
    if not math.isfinite(v):
        out["reason"] = f"η={v} 非有限，不可判读"
        return out
    out["value"] = v
    if v < lo:
        out["ok"] = False
        out["reason"] = f"η={v:.4f} 低于下沿 {lo}（过损耗/欠辐射读数）"
    elif v > hi:
        out["ok"] = False
        out["reason"] = (f"η={v:.4f} 超上沿 {hi}"
                         "（cap 内损耗高估/Re(Zcap)<0 噪声病理嫌疑）")
    else:
        out["ok"] = True
        out["reason"] = f"η={v:.4f} 落 [{lo}, {hi}]"
    return out


def diff_gate(eta_ff: float | None, eta_wh: float | None,
              tol_pp: float = DIFF_TOL_PP) -> dict[str, Any]:
    """两法一致性门：|η_ff − η_wh| ≤ tol_pp（个百分点）。"""
    out: dict[str, Any] = {"tol_pp": tol_pp, "diff_pp": None,
                           "ok": None, "reason": ""}
    if eta_ff is None or eta_wh is None:
        out["reason"] = "η 缺失，不可判读"
        return out
    a, b = float(eta_ff), float(eta_wh)
    if not (math.isfinite(a) and math.isfinite(b)):
        out["reason"] = "η 含非有限值，不可判读"
        return out
    d = abs(a - b) * 100.0
    out["diff_pp"] = d
    if d <= tol_pp:
        out["ok"] = True
        out["reason"] = f"|Δη|={d:.2f}pp ≤ {tol_pp}pp"
    else:
        out["ok"] = False
        out["reason"] = f"|Δη|={d:.2f}pp > {tol_pp}pp"
    return out


def upper_sanity_gate(value: float | None,
                      hi: float = ETA_BAND[1]) -> dict[str, Any]:
    """η 上沿守卫（有损臂专用）：η ≤ hi（物理上界 η≤1+数值噪声）。

    [0.90,1.05] 带的下沿只适用 PEC 对照臂（η≈1）；有损变体解析期望
    η=R_rad/(R_rad+R_L)≈0.74–0.85 本就在 0.90 下方——对有损臂套下沿
    会把物理正确读数误判 FAIL（2026-09-30 ge7 criteria 定稿时测试先行
    抓出的门设计错，见 tests 回放钉 test_lossy_arm_below_band_is_ok）。
    """
    out: dict[str, Any] = {"gate": ["-inf", hi], "value": value,
                           "ok": None, "reason": ""}
    if value is None:
        out["reason"] = "η 不可得（分母守卫或输入缺失）"
        return out
    v = float(value)
    if not math.isfinite(v):
        out["reason"] = f"η={v} 非有限，不可判读"
        return out
    if v > hi:
        out["ok"] = False
        out["reason"] = (f"η={v:.4f} 超上沿 {hi}"
                         "（cap 内损耗高估/Re(Zcap)<0 噪声病理嫌疑）")
    else:
        out["ok"] = True
        out["reason"] = f"η={v:.4f} ≤ {hi}（上沿守卫过）"
    return out


def method_prevalidation_gate(
        eta_ff_pec: float | None, eta_wh_pec: float | None,
        eta_ff_rl: float | None, eta_wh_rl: float | None,
        lo: float = ETA_BAND[0], hi: float = ETA_BAND[1],
        tol_pp: float = DIFF_TOL_PP) -> dict[str, Any]:
    """ge7 复验门组（criteria §4：G1' 主门 + G2' 对照门，判读总装）。

    - G2'（对照门）：PEC 变体两法双侧带 [lo,hi]（替 ge6 单侧 ≥0.95——
      上限拦 η_wh_pec>1.05 病理，即本模块立项根因）；
    - G1'（主门）：损耗变体 |Δη| ≤ tol_pp 且两法各过上沿守卫 ≤hi
      （下沿不适用有损臂，见 upper_sanity_gate docstring）；
    - 全过 → verdict=PASS；G1' 过 G2' 不过 → PARTIAL（对照本底脏）；
      否则 FAIL。ok=None 的子门如实计入不过（不虚构）。
    """
    g2_checks = {"eta_ff_pec": eta_band_gate(eta_ff_pec, lo, hi),
                 "eta_wh_pec": eta_band_gate(eta_wh_pec, lo, hi)}
    g1_band = {"eta_ff_rl": upper_sanity_gate(eta_ff_rl, hi),
               "eta_wh_rl": upper_sanity_gate(eta_wh_rl, hi)}
    g1_diff = diff_gate(eta_ff_rl, eta_wh_rl, tol_pp)
    g2_pass = all(c["ok"] is True for c in g2_checks.values())
    g1_pass = (all(c["ok"] is True for c in g1_band.values())
               and g1_diff["ok"] is True)
    if g1_pass and g2_pass:
        verdict = "PASS"
    elif g1_pass:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return {"g1_main": {"band": g1_band, "diff": g1_diff, "pass": g1_pass},
            "g2_control": {"checks": g2_checks, "pass": g2_pass},
            "verdict": verdict}
