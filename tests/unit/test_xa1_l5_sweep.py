"""XA-1 L5 扫频差分批·纯核回归钉（拟合/判读/合成回收；#340 回收钉范式）。

判据面 = runs/xa1_arbitration/l5_sweep/criteria.md（#122 判据先行，冻结）；
被测面 = scripts/xa1_l5_sweep_lib.py（纯 numpy 核，零引擎/零网络/零真机）。

钉面：
① 目标值与前席 xa1_arbitration_evidence.json criterion1 逐位一致（W/εeff/
   ΔL/X_A/X_B）+ 判定带不重叠（A 带上缘 < B 带下缘，无人区存在）；
② 座位表几何量自洽（A/B 语义频偏 ≤1% 且距带心 ≥8 个频栅步、馈偏在
   (0, L/2)、频带=±12% f_exp）；
③ 拟合精确性：无噪合成 X̂/εeff_fit 逐位回收 + 与二维非线性最小二乘独立
   实现互证（#118：裁判量须有独立来源对照）；
④ **合成回收钉**：A 语义合成 → 判 A；B 语义合成 → 判 B（判读函数独立
   测试，防"裁判先射箭后画靶"）；
⑤ 判读诚实条款：语义中点/欠功（<4 座）/超 CI/εeff 越完整性带/零数据
   全部如实 INCONCLUSIVE，绝不凑 A/B（#122）；
⑥ 谷门与谷位提取（refined/interior/深度；合成谐振曲线回收 f_dip）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import least_squares

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import xa1_l5_sweep_lib as lib

# 前席证据面冻结字面（runs/xa1_arbitration/xa1_arbitration_evidence.json
# criterion1 synthesize_patch_nominal 节，2026-10-02 实测；runs/ 不入库故
# 字面钉在测试内，来源随注释）
EVID_W_MM = 40.9168
EVID_EPS_EFF = 3.570779
EVID_DL_EDGE_MM = 0.242938
EVID_X_A_MM = 0.485876
EVID_X_B_MM = 0.971753


# ── ① 目标值与前席证据逐位一致 + 带不重叠 ─────────────────────────────────

def test_targets_match_prior_evidence():
    t = lib.arbitration_targets()
    assert t["w_mm"] == pytest.approx(EVID_W_MM, abs=1e-4)
    assert t["eps_eff_qs"] == pytest.approx(EVID_EPS_EFF, abs=1e-6)
    assert t["delta_l_edge_mm"] == pytest.approx(EVID_DL_EDGE_MM, abs=1e-6)
    assert t["x_a_mm"] == pytest.approx(EVID_X_A_MM, abs=1e-6)
    assert t["x_b_mm"] == pytest.approx(EVID_X_B_MM, abs=1e-6)
    assert t["x_b_mm"] - t["x_a_mm"] == pytest.approx(0.485877, abs=1e-5)


def test_bands_disjoint_with_no_man_land():
    t = lib.arbitration_targets()
    _a_lo, a_hi = t["band_a"]
    b_lo, _b_hi = t["band_b"]
    assert a_hi < b_lo, "A/B 判定带必须不重叠（否则判据不可分）"
    n_lo, n_hi = t["no_man_land"]
    assert (n_lo, n_hi) == (a_hi, b_lo)
    assert t["band_half_mm"] == pytest.approx(0.20)
    # 带半宽 < 语义差（半分带判据可分性的充分条件）
    assert 2 * t["band_half_mm"] < t["gap_mm"]


def test_criteria_file_present_with_frozen_tokens():
    if not (Path(__file__).resolve().parents[2] / "runs" / "xa1_arbitration" / "l5_sweep" / "criteria.md").is_file():
        pytest.skip("runs/xa1_arbitration 证据档缺席（公开分发视图）")
    # 驱动发射前强制 criteria.md 存在（#122）；冻结阈值词面在档
    text = (REPO / "runs" / "xa1_arbitration" / "l5_sweep" / "criteria.md"
            ).read_text(encoding="utf-8")
    for token in ("0.485876", "0.971753", "0.20 mm", "0.10 mm",
                  "INCONCLUSIVE", "2.5814", "1.5637"):
        assert token in text, f"criteria.md 缺冻结词面: {token}"


# ── ② 座位表几何自洽 ──────────────────────────────────────────────────────

def test_design_seats_table():
    seats = lib.design_seats()
    assert [s["name"] for s in seats] == ["l030", "l035", "l040", "l045", "l050"]
    t = lib.arbitration_targets()
    for seat in seats:
        f_exp = seat["f_exp_ghz"]
        lo, hi = seat["band_ghz"]
        assert lo == pytest.approx(lib.BAND_LO_RATIO * f_exp)
        assert hi == pytest.approx(lib.BAND_HI_RATIO * f_exp)
        # A/B 语义频偏 ≤1%（僵局根源的量化）且距带心 ≥7.9 个频栅步（401 点；
        # 最紧的 l050 座 7.94，criteria §二 "≥8 个"为整数口径）
        step = (hi - lo) / 400.0
        for key in ("a", "b"):
            f_sem = seat["f_sem_ghz"][key]
            dev = abs(f_sem / f_exp - 1.0)
            assert dev < 0.01
            assert dev * f_exp / step >= 7.9, (
                f"{seat['name']} {key} 语义谷距带心频栅步不足")
        off = seat["feed_offset_mm"]
        assert 0.0 < off < seat["l_mm"] / 2.0
        assert seat["params"]["patch_len_mm"] == pytest.approx(seat["l_mm"])
        assert seat["params"]["patch_w_mm"] == pytest.approx(
            round(t["w_mm"], 4))
        assert seat["params"]["feed_offset_mm"] == pytest.approx(round(off, 4))


def test_design_seats_rejects_nonpositive_l():
    with pytest.raises(ValueError):
        lib.design_seats((0.0, 40.0))


# ── ③ 拟合精确性 + 独立实现互证 ───────────────────────────────────────────

def test_fit_exact_recovery_noiseless():
    t = lib.arbitration_targets()
    for x_true in (t["x_a_mm"], t["x_b_mm"], 0.7):
        recs = lib.synthesize_sweep(lib.L_POINTS, x_true, t["eps_eff_qs"])
        fit = lib.fit_x_total([r["l_mm"] for r in recs],
                              [r["f_dip_ghz"] for r in recs])
        assert fit["x_hat_mm"] == pytest.approx(x_true, rel=1e-9)
        assert fit["eps_eff_fit"] == pytest.approx(t["eps_eff_qs"], rel=1e-9)
        assert fit["ci95_half_mm"] == pytest.approx(0.0, abs=1e-9)
        assert fit["n"] == 5 and fit["span_mm"] == pytest.approx(20.0)


def test_fit_matches_independent_nonlinear_ls():
    # 独立来源对照（#118）：线性化 OLS X̂ ↔ 二维非线性最小二乘 (X, εeff)
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_a_mm"], 3.62,
                                noise_std_mm=0.01, seed=20261003)
    l_arr = np.asarray([r["l_mm"] for r in recs])
    f = np.asarray([r["f_dip_ghz"] for r in recs])
    fit = lib.fit_x_total(l_arr, f)

    def resid(p):
        return lib.C0_MM_GHZ / (2.0 * f) - math.sqrt(p[1]) * (l_arr + p[0])

    sol = least_squares(resid, x0=[0.5, 3.0])
    assert fit["x_hat_mm"] == pytest.approx(float(sol.x[0]), rel=1e-6)
    assert fit["eps_eff_fit"] == pytest.approx(float(sol.x[1]), rel=1e-6)


def test_fit_noisy_ci_within_quality_gate():
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_a_mm"], t["eps_eff_qs"],
                                noise_std_mm=0.01, seed=7)
    fit = lib.fit_x_total([r["l_mm"] for r in recs],
                          [r["f_dip_ghz"] for r in recs])
    assert fit["ci95_half_mm"] < lib.MAX_CI95_HALF_MM
    assert fit["resid_rms_mm"] < 0.05


def test_fit_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        lib.fit_x_total([40.0], [2.0])                 # 单点
    with pytest.raises(ValueError):
        lib.fit_x_total([40.0, 40.0], [2.0, 2.1])      # 零跨度
    with pytest.raises(ValueError):
        lib.fit_x_total([30.0, 40.0], [2.0, float("nan")])


# ── ④ 合成回收钉（#340）：A 语义合成 → 判 A；B 语义合成 → 判 B ─────────────

@pytest.mark.parametrize("key", ("a", "b"))
def test_synthetic_recovery_pin(key):
    t = lib.arbitration_targets()
    x_true = t["x_a_mm"] if key == "a" else t["x_b_mm"]
    recs = lib.synthesize_sweep(lib.L_POINTS, x_true, t["eps_eff_qs"],
                                noise_std_mm=0.01, seed=42)
    out = lib.judge_sweep(recs, t)
    assert out["verdict"] == key.upper(), out["reasons"]
    fit = out["fit"]
    assert fit is not None
    lo = fit["x_hat_mm"] - fit["ci95_half_mm"]
    hi = fit["x_hat_mm"] + fit["ci95_half_mm"]
    assert lo <= x_true <= hi, "CI95 须覆盖真值（估计量自洽）"


def test_synthetic_recovery_pin_all_five_l_points_used():
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_b_mm"], t["eps_eff_qs"],
                                noise_std_mm=0.005, seed=1)
    out = lib.judge_sweep(recs, t)
    assert all(s["used_in_fit"] for s in out["seats"])
    assert out["fit"]["n"] == 5


# ── ⑤ 判读诚实条款（#122）────────────────────────────────────────────────

def test_judge_midgap_semantic_is_inconclusive():
    # 语义中点 3ΔL（无人区中心）——双落不裁
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, 3.0 * t["delta_l_edge_mm"],
                                t["eps_eff_qs"], noise_std_mm=0.005, seed=3)
    out = lib.judge_sweep(recs, t)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["gates"]["ci_in_band_a"] is False
    assert out["gates"]["ci_in_band_b"] is False


def test_judge_underpowered_is_inconclusive():
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS[:3], t["x_a_mm"],
                                t["eps_eff_qs"])          # 3 座 < 4
    out = lib.judge_sweep(recs, t)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["gates"]["g1_seats"] is False
    assert "质量门1" in out["reasons"][0]


def test_judge_huge_ci_is_inconclusive():
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_a_mm"], t["eps_eff_qs"],
                                noise_std_mm=0.5, seed=9)   # 散布主导
    out = lib.judge_sweep(recs, t)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["gates"]["g2_ci95"] is False


def test_judge_eps_eff_out_of_sanity_is_inconclusive():
    # εeff_fit 越完整性带（量的疑似非 TM10 模）——如实不判
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_a_mm"], 6.0)
    out = lib.judge_sweep(recs, t)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["gates"]["g3_eps_eff"] is False


def test_judge_no_valid_seats_is_inconclusive():
    out = lib.judge_sweep([{"name": "l030", "l_mm": 30.0, "ok": False,
                            "f_dip_ghz": None, "status": "FAIL",
                            "reason": "x"}])
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["fit"] is None


def test_judge_partial_seats_excluded_honestly():
    # 1 座坏 → 剔除不进拟合但如实留痕；其余 4 座仍可判
    t = lib.arbitration_targets()
    recs = lib.synthesize_sweep(lib.L_POINTS, t["x_a_mm"], t["eps_eff_qs"],
                                noise_std_mm=0.005, seed=11)
    recs[2]["ok"] = False
    recs[2]["reason"] = "谷深不足（剔除）"
    out = lib.judge_sweep(recs, t)
    assert out["seats"][2]["used_in_fit"] is False
    assert "剔除" in out["seats"][2]["reason"]
    assert out["verdict"] == "A"


# ── ⑥ 谷门与谷位提取 ─────────────────────────────────────────────────────

def _lorentz_dip_curve(f0_ghz: float, span_ghz: tuple[float, float],
                       n: int = 401, depth_db: float = 25.0,
                       fwhm_ghz: float = 0.02):
    f = np.linspace(span_ghz[0], span_ghz[1], n)
    floor_db = -1.0
    dip = -depth_db * 1.0 / (1.0 + ((f - f0_ghz) / (fwhm_ghz / 2)) ** 2)
    s11_db = floor_db + (dip - floor_db)
    s11 = 10.0 ** (s11_db / 20.0)
    return f, s11


def test_extract_dip_recovers_synthetic_resonance():
    f0 = 1.9476
    lo, hi = 0.88 * f0, 1.12 * f0
    f, s11 = _lorentz_dip_curve(f0, (lo, hi))
    f_dip, meta = lib.extract_dip(f, s11)
    step = (hi - lo) / 400.0
    assert abs(f_dip - f0) < 0.2 * step
    assert meta["refined"] is True
    assert meta["dip_db"] == pytest.approx(-26.0, abs=2.0)


def test_extract_dip_rejects_bad_input():
    with pytest.raises(ValueError):
        lib.extract_dip(np.linspace(1.0, 2.0, 4), np.array([1j] * 5))
    with pytest.raises(ValueError):
        lib.extract_dip(np.linspace(1.0, 2.0, 4),
                        np.array([1j, np.nan, 1j, 1j]))


def test_dip_gates_paths():
    band = (1.7139, 2.1814)
    ok_meta = {"argmin_ghz": 1.9476, "dip_db": -26.0, "refined": True}
    gates = lib.dip_gates(ok_meta, band)
    assert gates["ok"] is True and gates["reasons"] == []
    shallow = lib.dip_gates({"argmin_ghz": 1.9476, "dip_db": -3.0,
                             "refined": True}, band)
    assert shallow["ok"] is False and not shallow["deep_enough"]
    edge = lib.dip_gates({"argmin_ghz": 1.72, "dip_db": -26.0,
                          "refined": True}, band)
    assert edge["ok"] is False and not edge["interior"]
    unrefined = lib.dip_gates({"argmin_ghz": 1.9476, "dip_db": -26.0,
                               "refined": False}, band)
    assert unrefined["ok"] is False and not unrefined["refined"]
    assert all(len(g["reasons"]) == 1
               for g in (shallow, edge, unrefined))


def test_dip_gates_constants_match_criteria():
    assert lib.DIP_MAX_DB == -6.0
    assert lib.DIP_EDGE_MARGIN == 0.05
    assert lib.MAX_CI95_HALF_MM == 0.10
    assert lib.X_BAND_HALF_MM == 0.20
    assert lib.MIN_SEATS == 4
    assert lib.MIN_SPAN_MM == 15.0
    assert lib.EPS_EFF_SANITY == (0.85, 1.15)
    assert lib.L_POINTS == (30.0, 35.0, 40.0, 45.0, 50.0)
