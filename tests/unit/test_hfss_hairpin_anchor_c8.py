"""hairpin_alt C8 HFSS 锚判读核离线单测（零真机/零网络，#118 mock 回收钉）。

裁判（#118 独立来源回收）：
  ① mock eigen 对注入 → k 回收：本征对按 k 已知构造（f_mean=2.45GHz，
    Δf=k·f_mean ⇒ k=2Δf/(f1+f2) 恒等闭式），先例守卫 analyze_eigen_modes
    回收逐位一致（rel 1e-12）；带内第三模 intruder/模数不足如实拒判。
  ② 判定门边界：g0500 重现门 5%（≤PASS/超 DEGRADED）、g1600 κ 线内插门
    15%（≤AGREE/超 DEVIATED），边界点与两侧分支钉死（#122 预声明门）。
  ③ 预声明常数与任务书一致性：c_interp 线性内插画法复现 c_true_interp
    （rel 1e-12）、c_interp×k_KJ(1.6) 复现 k_pred（rel 1e-9，repo 内核
    coupled_microstrip 同源）——任务书在检出版本内时钉，缺省 skip。
  ④ 总判组合（judge_all）：PASS+AGREE/PASS+DEGRADED/DEVIATED/缺项四分支。
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_hfss_hairpin_anchor_c8", str(_REPO / "scripts" / "hfss_hairpin_anchor_c8.py"))
assert _SPEC is not None and _SPEC.loader is not None
c8 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(c8)

PLAN = _REPO / "runs" / "hairpin_alt_k_extract" / "hfss_anchor_plan.json"
F_MEAN = 2.45     # 先例 analyze_eigen_modes 模对选取中心（GHz）


def _modes_for_k(k: float, f_mean: float = F_MEAN,
                 extra: list[float] | None = None) -> list[float]:
    """k 已知的本征对构造：k=2(f2−f1)/(f2+f1)，f1+f2=2·f_mean ⇒ Δf=k·f_mean。"""
    df = k * f_mean
    modes = sorted([f_mean - df / 2.0, f_mean + df / 2.0])
    return modes + list(extra or [])


# ── ① mock eigen 对注入 → k 回收（#118）────────────────────────────


def test_mock_eigen_pair_k_recovery_exact():
    """已知 k 本征对注入 → 先例守卫回收逐位一致 + 守卫旗标全绿。"""
    for k_true in (0.07625418440361244, 0.018165059455094727, 0.0469):
        modes = _modes_for_k(k_true, extra=[4.5, 4.8])
        res = c8.prec.analyze_eigen_modes(modes, 1.6)
        assert res["ok"] is True
        assert res["band_sanity"] is True
        assert res["intruder_modes_ghz"] == []
        assert res["k_split_eigen"] == pytest.approx(k_true, rel=1e-12)
        assert res["k_split_eigen_sq"] == pytest.approx(
            (modes[1] ** 2 - modes[0] ** 2) / (modes[1] ** 2 + modes[0] ** 2),
            rel=1e-12)


def test_mock_eigen_rejects_intruder_and_degenerate():
    """带内第三模（2.2–2.8GHz intruder）/模数不足 → 守卫 ok=False 不出 k。"""
    bad = c8.prec.analyze_eigen_modes(
        _modes_for_k(0.05, extra=[2.6]), 1.6)
    assert bad["ok"] is False and 2.6 in bad["intruder_modes_ghz"]
    deg = c8.prec.analyze_eigen_modes([4.5], 1.6)
    assert deg["ok"] is False and "k_split_eigen" not in deg


def test_analyze_point_recovery_routes_to_judge():
    """analyze_point：mock 对注入 → k 回收并按 gap 路由到对应判定。"""
    kj = c8.kj_impedances(1.6)
    row16 = c8.analyze_point(1.6, _modes_for_k(0.018, extra=[4.5, 4.8]),
                             solve_s=26.0, wall_s=75.0, kj=kj)
    assert row16["k_split_eigen"] == pytest.approx(0.018, rel=1e-12)
    assert row16["pt_id"] == "kgapalt_g1600"
    row05 = c8.analyze_point(0.5, _modes_for_k(0.076, extra=[4.5, 4.8]),
                             solve_s=26.0, wall_s=75.0,
                             kj=c8.kj_impedances(0.5))
    assert row05["pt_id"] == "kgapalt_g0500"
    # 守卫未过 → verdict=None 判读缺项（judge_all 记 FAIL，不凑绿）
    row_bad = c8.analyze_point(1.6, [4.5], solve_s=1.0, wall_s=1.0, kj=kj)
    assert row_bad["verdict"] is None and row_bad["ok"] is False


# ── ② 判定门边界（#122 预声明门，不事后改）─────────────────────────


def test_judge_g0500_reproduce_gate_boundary():
    """重现门 5%：±4.9% PASS / ±5.1% DEGRADED / 恰 5% PASS（≤含边界）。"""
    k_prev = c8.K_EIGEN_PREV_G0500
    assert c8.judge_g0500(k_prev)["verdict"] == "PASS"
    assert c8.judge_g0500(k_prev)["dev_pct"] == pytest.approx(0.0, abs=1e-12)
    for factor in (1.0 + 0.049, 1.0 - 0.049):
        assert c8.judge_g0500(k_prev * factor)["verdict"] == "PASS"
    assert c8.judge_g0500(k_prev * 1.05)["verdict"] == "PASS"      # 恰在门上
    for factor in (1.0 + 0.0501, 1.0 - 0.0501):
        row = c8.judge_g0500(k_prev * factor)
        assert row["verdict"] == "DEGRADED"
        assert "不事后改门" in row["verdict_note"]
    # 判读确定性：同入参逐位一致
    assert (c8.judge_g0500(k_prev * 1.03)
            == c8.judge_g0500(k_prev * 1.03))


def test_judge_g1600_pred_gate_boundary():
    """κ 线内插门 15%：±14% AGREE / ±15.1% DEVIATED；c_true_new=k/k_KJ。"""
    k_pred = c8.K_PRED_G1600
    kj = c8.kj_impedances(1.6)
    row = c8.judge_g1600(k_pred * 1.14, kj["k_kj"])
    assert row["verdict"] == "AGREE"
    assert row["c_true_new"] == pytest.approx(k_pred * 1.14 / kj["k_kj"],
                                              rel=1e-12)
    assert c8.judge_g1600(k_pred * 1.15, kj["k_kj"])["verdict"] == "AGREE"
    for factor in (1.0 + 0.1501, 1.0 - 0.1501, 0.80):
        row = c8.judge_g1600(k_pred * factor, kj["k_kj"])
        assert row["verdict"] == "DEVIATED"
        assert "不成立待归因" in row["verdict_note"]
    assert (c8.judge_g1600(k_pred * 1.10, kj["k_kj"])
            == c8.judge_g1600(k_pred * 1.10, kj["k_kj"]))


# ── ③ 预声明常数与任务书一致性（任务书在检出版本内时钉）─────────────


@pytest.mark.skipif(not PLAN.exists(),
                    reason="锚任务书 runs/hairpin_alt_k_extract/"
                           "hfss_anchor_plan.json 不在检出版本内")
def test_predeclared_constants_match_plan():
    """驱动预声明常数与任务书逐键一致（k_pred/门/κ 线/k_eigen_previous）。"""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    by_slot = {c["slot"]: c for c in plan["candidates"]}
    n1, n2 = by_slot["n1_middle"], by_slot["n2_kmax_resolved"]
    assert pytest.approx(
        n1["expected"]["k_pred"], rel=1e-15) == c8.K_PRED_G1600
    assert pytest.approx(
        n1["expected"]["c_true_interp"], rel=1e-15) == c8.C_INTERP_G1600
    assert n1["expected"]["k_pred_interval_pct"] == c8.GATE_PRED_PCT
    assert pytest.approx(
        n2["expected"]["k_eigen_previous"], rel=1e-15) == c8.K_EIGEN_PREV_G0500
    assert n2["expected"]["reproduce_gate_pct"] == c8.GATE_REPRODUCE_PCT
    assert pytest.approx(
        {float(k): v for k, v in plan["anchored_state"]["c_true"].items()},
        rel=1e-15) == c8.C_TRUE_ANCHORED
    # 画法复现：线性内插 c_true(1.1328..2.2)@1.6 == 任务书 c_true_interp
    assert c8.c_interp_linear(1.6) == pytest.approx(c8.C_INTERP_G1600,
                                                    rel=1e-12)
    # 闭环：c_interp × k_KJ(1.6)（repo 内核现算）== 任务书 k_pred（rel 1e-9）
    assert c8.c_interp_linear(1.6) * c8.kj_impedances(1.6)["k_kj"] == \
        pytest.approx(c8.K_PRED_G1600, rel=1e-9)


def test_kj_live_check_preflight_flags():
    """preflight 复核旗标：c_interp/k_pred 闭环 + g0500 KJ 归档比对全绿。"""
    kj = c8.kj_live_check()
    assert kj["c_interp_match"] is True
    assert kj["k_pred_match"] is True
    assert kj["0.5"]["k_kj_match"] is True
    assert kj["1.6"]["z0e_ohm"] > kj["1.6"]["z0o_ohm"] > 0.0
    assert 0.0 < kj["1.6"]["k_kj"] < c8.kj_impedances(0.5)["k_kj"]


# ── ④ 总判组合（judge_all 四分支）──────────────────────────────────


def _pts(v05: str | None, v16: str | None) -> dict:
    p05 = {"verdict": v05, "k_split_eigen": 0.076} if v05 else {"ok": False}
    p16 = {"verdict": v16, "k_split_eigen": 0.018,
           "c_true_new": 0.57} if v16 else {"ok": False}
    return {"0.5": p05, "1.6": p16}


def test_judge_all_branches():
    """PASS+AGREE → ANCHOR_C8_PASS；DEGRADED+AGREE → 采信+入预算；其余如实。"""
    ok = c8.judge_all(copy.deepcopy(_pts("PASS", "AGREE")))
    assert ok["verdict"] == "ANCHOR_C8_PASS" and ok["ok"] is True
    assert ok["anchor_ledger"]["1.6"]["role"] == "新锚 n1"
    deg = c8.judge_all(copy.deepcopy(_pts("DEGRADED", "AGREE")))
    assert deg["verdict"] == "ANCHORED_G1600_G0500_DEGRADED"
    assert deg["ok"] is True and "不确定度预算" in deg["note"]
    dev = c8.judge_all(copy.deepcopy(_pts("PASS", "DEVIATED")))
    assert dev["verdict"] == "G1600_DEVIATED" and dev["ok"] is False
    fail = c8.judge_all(copy.deepcopy(_pts(None, "AGREE")))
    assert fail["verdict"] == "FAIL" and fail["ok"] is False
    assert "0.5" in fail["note"]
