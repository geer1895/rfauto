"""WP3.9 MVP 基准单测（§10.0 判据/搜索环/几何表达式审计——全部零真机）。

覆盖面：
1. 判据原语（预算/劣化/墙钟比）与 judge_problem_pair/summarize 判定组合；
2. Pattern Search 基线环（Hooke-Jeeves）在合成面上的正确性 + 预算硬帽
   + 失败点不炸环；
3. rfauto sbo 环（run_surrogate_loop + smt_kriging）离线解析面收敛 +
   预算不超；
4. scripts/wp39_benchmark_run.py dry-run 全 6 组合（3 问题 × 2 引擎）
   端到端 + judge 汇总（tmp outdir，零真机零 runs/ 污染）；
5. 几何表达式离线审计（#212 教训：字符串存在性测试抓不住画法错误）——
   mline/ratrace 变量表达式在标称值处数值求值，对照独立来源
   （hfss_mline_probe.py 预计算值 / hfss_ratrace_arbitration.py 字面
   几何）逐角点核对。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "scripts"), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import wp39_benchmark_run as runner
from rfauto.core.objectives import Objective
from rfauto.optimization.surrogate_loop import run_surrogate_loop
from rfauto.service.wp39_benchmark import (
    BUDGET_DEFAULT,
    C_LIGHT,
    COST_MAX_DEGRADATION_PCT,
    WALLCLOCK_MAX_RATIO,
    best_so_far_trace,
    budget_used_ok,
    cost_degradation_pct,
    eps_eff_error_metric,
    eps_eff_from_beta,
    eps_eff_from_s21_phase,
    judge_problem_pair,
    mline_landscape_health_gate,
    pattern_search_loop,
    sbo_objectives,
    summarize_judgment,
    wallclock_ratio,
)

# ── 判据原语 ─────────────────────────────────────────────────────────────────


class TestCriteriaPrimitives:
    def test_budget_ok_and_violation(self):
        assert budget_used_ok(25, 25)
        assert budget_used_ok(0, 25)
        assert not budget_used_ok(26, 25)
        assert not budget_used_ok(-1, 25)

    def test_cost_degradation_signed(self):
        # dB 越负越好：试验臂 -38（基线 -40）→ 劣化 +5%
        assert cost_degradation_pct(-38.0, -40.0) == pytest.approx(5.0)
        assert cost_degradation_pct(-42.0, -40.0) == pytest.approx(-5.0)
        assert cost_degradation_pct(-40.0, -40.0) == pytest.approx(0.0)

    def test_cost_degradation_zero_ref_undecidable(self):
        assert cost_degradation_pct(1.0, 0.0) is None
        assert cost_degradation_pct(0.0, 0.0) == 0.0

    def test_wallclock_ratio(self):
        assert wallclock_ratio(10.0, 20.0) == pytest.approx(0.5)
        assert wallclock_ratio(21.0, 20.0) == pytest.approx(1.05)
        assert wallclock_ratio(10.0, 0.0) is None

    def test_best_so_far_trace_monotonic(self):
        assert best_so_far_trace([-3.0, -5.0, -4.0]) == \
            pytest.approx([-3.0, -5.0, -5.0])


def _camp(problem: str, metric: float | None, n_evals: int,
          opt_s: float) -> dict:
    best = None if metric is None else {
        "params": {}, "metric": metric, "cost": metric + 1e6}
    return {"problem": problem, "best": best, "n_evals": n_evals,
            "wall_s": {"optimization_s": opt_s}}


class TestJudgePair:
    def test_pass_case(self):
        base = _camp("mline", -40.0, 25, 600.0)
        cand = _camp("mline", -39.5, 12, 250.0)
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "PASS"
        assert v["budget_ok"] and v["wallclock_ok"] and v["cost_ok"]
        assert v["wallclock_ratio"] == pytest.approx(250 / 600, abs=1e-3)
        assert v["degradation_pct"] == pytest.approx(1.25)

    def test_fail_wallclock(self):
        base = _camp("patch", -30.0, 25, 600.0)
        cand = _camp("patch", -30.0, 20, 400.0)  # ratio 0.667 > 0.5
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "FAIL"
        assert not v["wallclock_ok"]
        assert any("wall-clock" in r for r in v["reasons"])

    def test_fail_degradation(self):
        base = _camp("ratrace", -40.0, 25, 600.0)
        cand = _camp("ratrace", -37.8, 12, 250.0)  # 劣化 5.5% > 5%
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "FAIL"
        assert not v["cost_ok"]
        assert v["degradation_pct"] == pytest.approx(5.5)

    def test_fail_budget(self):
        base = _camp("mline", -40.0, 26, 600.0)
        cand = _camp("mline", -40.0, 12, 250.0)
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "FAIL"
        assert not v["budget_ok"]

    def test_fail_missing_best(self):
        base = _camp("mline", None, 25, 600.0)
        cand = _camp("mline", -40.0, 12, 250.0)
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "FAIL"
        assert any("最优指标缺失" in r for r in v["reasons"])

    def test_undecidable_wallclock_no_crash(self):
        # 基线优化墙钟非正（如 dry-run 解析面 0.0s）→ 不可判定而非崩溃
        base = _camp("mline", -40.0, 25, 0.0)
        cand = _camp("mline", -40.0, 12, 3.0)
        v = judge_problem_pair(base, cand)
        assert v["verdict"] == "FAIL"
        assert v["wallclock_ratio"] is None
        assert any("wall-clock" in r for r in v["reasons"])

    def test_constants_match_plan(self):
        # §10.0 / 队列项口径：预算 25、wall ≤1/2、劣化 ≤5%
        assert BUDGET_DEFAULT == 25
        assert WALLCLOCK_MAX_RATIO == 0.5
        assert COST_MAX_DEGRADATION_PCT == 5.0


class TestSummarize:
    def test_all_pass(self):
        verdicts = {"a": {"verdict": "PASS"}, "b": {"verdict": "PASS"}}
        s = summarize_judgment(verdicts)
        assert s["overall"] == "PASS" and s["n_pass"] == 2

    def test_single_failure_no_cascade_but_overall_fail(self):
        verdicts = {"a": {"verdict": "PASS"},
                    "b": {"verdict": "FAIL", "reasons": ["x"]}}
        s = summarize_judgment(verdicts)
        assert s["overall"] == "FAIL" and s["n_pass"] == 1
        assert s["per_problem"]["b"] == "FAIL"


# ── Pattern Search 基线环 ────────────────────────────────────────────────────


def _quad1d_metrics(params: dict[str, float]) -> dict[str, float]:
    w = params["w_mm"]
    return {"s11_f0_db": -20.0 - 25.0 * math.exp(-((w - 1.11) / 0.30) ** 2)}


def _quad2d_metrics(params: dict[str, float]) -> dict[str, float]:
    lo, ww = params["patch_len_mm"], params["patch_w_mm"]
    return {"s11_f0_db": (-15.0 - 22.0 * math.exp(-((lo - 38.4) / 0.9) ** 2)
                          - 3.0 * math.exp(-((ww - 42.0) / 2.5) ** 2))}


class TestPatternSearchLoop:
    def test_1d_finds_optimum_within_budget(self):
        res = pattern_search_loop(
            {"w_mm": (0.5, 2.0)}, _quad1d_metrics,
            sbo_objectives("s11_f0_db"), x0={"w_mm": 1.113},
            budget=BUDGET_DEFAULT)
        assert res["ok"]
        assert res["n_evals"] <= BUDGET_DEFAULT
        # 解析最优 -45.0 @ w=1.11：模式搜索应逼近到 0.5dB 内
        assert res["best"]["cost"] - (-45.0 + 1e6) < 0.5
        assert res["best"]["params"]["w_mm"] == pytest.approx(1.11, abs=0.05)

    def test_2d_finds_optimum_within_budget(self):
        res = pattern_search_loop(
            {"patch_len_mm": (36.5, 41.5), "patch_w_mm": (40.0, 45.0)},
            _quad2d_metrics, sbo_objectives("s11_f0_db"),
            x0={"patch_len_mm": 40.0, "patch_w_mm": 45.0},
            budget=BUDGET_DEFAULT)
        assert res["ok"]
        assert res["n_evals"] <= BUDGET_DEFAULT
        assert res["best"]["params"]["patch_len_mm"] == \
            pytest.approx(38.4, abs=0.25)

    def test_budget_hard_cap_never_exceeded(self):
        # 极小 min_step 强制步长收缩路径走满预算——不得超 25
        res = pattern_search_loop(
            {"w_mm": (0.5, 2.0)}, _quad1d_metrics,
            sbo_objectives("s11_f0_db"), x0={"w_mm": 0.7},
            budget=BUDGET_DEFAULT, min_step_frac=1e-9)
        assert res["n_evals"] <= BUDGET_DEFAULT
        assert res["stop_reason"] == "budget"

    def test_start_clipped_to_bounds(self):
        res = pattern_search_loop(
            {"w_mm": (0.5, 2.0)}, _quad1d_metrics,
            sbo_objectives("s11_f0_db"), x0={"w_mm": 99.0},
            budget=BUDGET_DEFAULT)
        assert res["ok"]
        assert 0.5 <= res["best"]["params"]["w_mm"] <= 2.0

    def test_eval_failures_consume_budget_but_do_not_crash(self):
        calls = {"n": 0}

        def flaky(params: dict[str, float]) -> dict[str, float]:
            calls["n"] += 1
            if params["w_mm"] > 1.3:
                raise RuntimeError("solve 失败（模拟）")
            return _quad1d_metrics(params)

        res = pattern_search_loop(
            {"w_mm": (0.5, 2.0)}, flaky, sbo_objectives("s11_f0_db"),
            x0={"w_mm": 1.113}, budget=BUDGET_DEFAULT)
        assert res["ok"]
        assert res["n_evals"] <= BUDGET_DEFAULT
        assert res["n_failures"] >= 1
        assert res["best"]["params"]["w_mm"] <= 1.3

    def test_all_evals_fail_reports_failure(self):
        def always_fail(_params):
            raise RuntimeError("desktop 级故障")

        res = pattern_search_loop(
            {"w_mm": (0.5, 2.0)}, always_fail,
            sbo_objectives("s11_f0_db"), x0={"w_mm": 1.113},
            budget=BUDGET_DEFAULT)
        assert not res["ok"]
        assert res["best"] is None
        assert res["stop_reason"] == "all_failed"


# ── sbo 环离线收敛（smt_kriging；solutions 内核同真机配置）────────────────────


class TestSboOffline:
    def test_1d_converges_within_budget(self):
        pytest.importorskip("smt")
        res = run_surrogate_loop(
            {"w_mm": (0.5, 2.0)}, sbo_objectives("s11_f0_db"),
            _quad1d_metrics, n_init=5, top_k=2,
            virtual_trials=runner.SBO_VIRTUAL_TRIALS,
            max_real=BUDGET_DEFAULT, tol_abs=runner.SBO_TOL_ABS_DB,
            tol_rounds=runner.SBO_TOL_ROUNDS,
            surrogate_kind="smt_kriging", seed=42)
        assert res["ok"]
        assert res["n_attempts"] <= BUDGET_DEFAULT
        assert res["best"] is not None
        assert res["best"]["params"]["w_mm"] == pytest.approx(1.11, abs=0.1)
        # 谷深语义保序：最优 cost 接近解析谷 -45（+1e6 偏移）
        assert res["best"]["cost"] < -44.0 + 1e6
        assert len(res["real_cost_trace"]) == res["n_real_used"]

    def test_same_evaluator_both_engines(self):
        # 两引擎 objectives 同源（sbo_objectives）——"回代同一评估器"
        objs = sbo_objectives("s31_f0_db")
        assert isinstance(objs[0], Objective)
        assert objs[0].metric == "s31_f0_db"


# ── runner dry-run 端到端（零真机）───────────────────────────────────────────


class TestRunnerDryRun:
    @pytest.mark.parametrize("problem", ["mline", "patch", "ratrace"])
    @pytest.mark.parametrize("engine", ["sbo", "pattern_search"])
    def test_campaign_json_contract(self, tmp_path, problem, engine):
        pytest.importorskip("smt") if engine == "sbo" else None
        out = runner.run_campaign(problem, engine, tmp_path, dry_run=True)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == runner.SCHEMA
        assert data["dry_run"] is True
        assert data["problem"] == problem and data["engine"] == engine
        assert data["budget"] == BUDGET_DEFAULT
        assert data["stage"] == "done"
        assert data["best"] is not None
        assert isinstance(data["best"]["metric"], float)
        assert data["n_evals"] <= BUDGET_DEFAULT
        assert len(data["real_cost_trace"]) >= 1
        assert data["wall_s"]["optimization_s"] >= 0.0
        assert data["metric_name"] in ("s11_f0_db", "s31_f0_db")

    def test_judge_on_dry_results(self, tmp_path):
        pytest.importorskip("smt")
        for problem in ("mline", "patch", "ratrace"):
            for engine in ("sbo", "pattern_search"):
                runner.run_campaign(problem, engine, tmp_path, dry_run=True)
        summary_path = runner.judge(tmp_path)
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert data["schema"] == "wp39_mvp_summary_v1"
        assert data["summary"]["n_problems"] == 3
        for pname, v in data["problems"].items():
            # dry-run 两引擎跑同一解析面：预算与 cost 门必过；wall-clock
            # 取决于两环算法开销比（sbo 含 2000 虚拟寻优，解析面秒级），
            # 不在此钉死——真机判据见 runs/ 下战役归档 summary.json
            assert v["budget_ok"], (pname, v)
            assert v["cost_ok"], (pname, v)
        assert data["summary"]["overall"] in ("PASS", "FAIL")

    def test_real_run_retry_and_failure_path(self, tmp_path, monkeypatch):
        # 非 dry-run 路径的整轮重启/失败记账：钉死 launch（绝不在单测里
        # 碰 COM/HFSS 桌面）——两轮失败后 campaign 如实落 failed 记录
        monkeypatch.setattr(runner, "MAX_ATTEMPTS", 2)
        monkeypatch.setattr(runner, "_kill_desktops", lambda: None)

        def _no_hfss(self):
            raise RuntimeError("offline test：禁止真实 desktop")

        monkeypatch.setattr(runner.HfssEvaluator, "launch_and_build",
                            _no_hfss)
        out = runner.run_campaign("mline", "pattern_search", tmp_path,
                                  dry_run=False)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["stage"] == "attempt_failed"
        assert len(data["attempts"]) == 2
        assert all(a["outcome"] == "error" for a in data["attempts"])
        assert data.get("best") is None


# ── 几何表达式离线审计（#212：对照独立来源逐角点数值核对）─────────────────────


def _eval_expr(expr: str, var: str, value: float) -> float:
    """把 '0.5*R+0.482mm' 类表达式按变量值数值求值（测试专用微型求值器）。"""
    token = expr.replace(var, repr(value))
    token = token.replace("mm", "")
    return float(eval(token, {"__builtins__": {}}, {}))


class TestGeometryExpressionAudit:
    def test_mline_expressions_match_probe_literals(self):
        # 独立来源：scripts/hfss_mline_probe.py 预计算值（W=1.113）
        w = 1.113
        assert _eval_expr("-W/2", "W", w) == pytest.approx(-w / 2)
        assert _eval_expr("-2.5*W", "W", w) == pytest.approx(-2.5 * w)
        assert _eval_expr("5*W", "W", w) == pytest.approx(5.0 * w)
        # 官方波端口尺寸：宽 5w=5.565、高 4×0.508=2.032（#192 PASS_A 同法）
        assert 5.0 * w == pytest.approx(5.565)
        assert pytest.approx(2.032) == 4.0 * 0.508

    def test_ratrace_stub_corners_match_arbitration_literals(self):
        # 独立来源：scripts/hfss_ratrace_arbitration.py 的 _quad 数值几何
        # （真机 Normal Completion 口径，2026-09-12）
        r = runner.R_PHYS
        ky, w2 = runner.KY, runner.W2
        xt_off = runner.XT_OFF

        def _arb_quad(p0, p1, half_w):
            ux, uy = p1[0] - p0[0], p1[1] - p0[1]
            norm = math.hypot(ux, uy)
            nx, ny = uy / norm, -ux / norm
            a = [p0[0] + half_w * nx, p0[1] + half_w * ny]
            b = [p0[0] - half_w * nx, p0[1] - half_w * ny]
            c = [p1[0] + half_w * nx, p1[1] + half_w * ny]
            d = [p1[0] - half_w * nx, p1[1] - half_w * ny]
            return [a, c, d, b]

        p0 = (0.5 * r, ky * r)
        p1 = (0.5 * r + xt_off, ky * r + 4.0)
        expected = _arb_quad(p0, p1, w2)
        exprs = runner._stub_quad(
            runner._rx, +1, xt_off, 4.0, "0.508mm")
        assert len(exprs) == 4
        for (ex, ey, _z), (px, py) in zip(exprs, expected, strict=True):
            assert _eval_expr(ex, "Rr", r) == pytest.approx(px, abs=1e-6)
            assert _eval_expr(ey, "Rr", r) == pytest.approx(py, abs=1e-6)

    def test_ratrace_mirrored_stubs_match_arbitration(self):
        r = runner.R_PHYS
        ky, w2 = runner.KY, runner.W2
        xt_off = runner.XT_OFF

        def _arb_quad(p0, p1, half_w):
            ux, uy = p1[0] - p0[0], p1[1] - p0[1]
            norm = math.hypot(ux, uy)
            nx, ny = uy / norm, -ux / norm
            a = [p0[0] + half_w * nx, p0[1] + half_w * ny]
            b = [p0[0] - half_w * nx, p0[1] - half_w * ny]
            c = [p1[0] + half_w * nx, p1[1] + half_w * ny]
            d = [p1[0] - half_w * nx, p1[1] - half_w * ny]
            return [a, c, d, b]

        cases = [
            ("out2", runner._rx, -1, xt_off, -4.0,
             (0.5 * r, -ky * r), (0.5 * r + xt_off, -ky * r - 4.0)),
            ("delta", runner._mx, +1, -xt_off, 4.0,
             (-0.5 * r, ky * r), (-0.5 * r - xt_off, ky * r + 4.0)),
        ]
        for _name, xcoef, ysign, dx, dy, p0, p1 in cases:
            expected = _arb_quad(p0, p1, w2)
            exprs = runner._stub_quad(xcoef, ysign, dx, dy, "0.508mm")
            for (ex, ey, _z), (px, py) in zip(exprs, expected, strict=True):
                assert _eval_expr(ex, "Rr", r) == pytest.approx(px, abs=1e-6)
                assert _eval_expr(ey, "Rr", r) == pytest.approx(py, abs=1e-6)

    def test_ratrace_fixed_structures_match_arbitration(self):
        r = runner.R_PHYS
        port_w = runner.PORT_W
        # P1 Σ 馈波端口固定（x=+60），P2/P4 随 Rr，P3 镜像（对照仲裁字面）
        assert _eval_expr(
            runner._vexpr("-0.5*Rr", -(runner.XT_OFF + port_w / 2)),
            "Rr", r) == pytest.approx(
            -(0.5 * r + runner.XT_OFF) - port_w / 2)
        assert _eval_expr(runner._rx(runner.XT_OFF - port_w / 2),
                          "Rr", r) == pytest.approx(
            0.5 * r + runner.XT_OFF - port_w / 2)
        # 环内外半径（仲裁：r_out=R+W/2, r_in=R−W/2，物理半径不过 k）
        assert _eval_expr(runner._vexpr("Rr", runner.W_RING / 2),
                          "Rr", r) == pytest.approx(r + runner.W_RING / 2)
        assert _eval_expr(runner._vexpr("Rr", -runner.W_RING / 2),
                          "Rr", r) == pytest.approx(r - runner.W_RING / 2)

    def test_ratrace_bounds_sanity(self):
        # 参数域两端几何不自交：弯折点/端口均在板内（离线拓扑哨兵）
        for r in (runner.PROBLEMS["ratrace"].bounds["r_mm"][0],
                  runner.PROBLEMS["ratrace"].bounds["r_mm"][1]):
            y_m = runner.KY * r + 4.0
            x_t = 0.5 * r + runner.XT_OFF
            assert y_m < runner.BOARD, (r, y_m)
            assert x_t + runner.PORT_W / 2 < runner.BOARD, (r, x_t)
            assert x_t - runner.PORT_W / 2 > 0, (r, x_t)


# ── MVP 基准换代内核（wp39-factory-verdict-next 子项 B）──────────────────────


class TestEpsEffFromBeta:
    def test_recovers_eps_from_synthetic_beta(self):
        # 合成 β=2πf√εeff/c：窗口中值处精确还原
        eps_true = 2.886
        f_hz = np.linspace(2.4e9, 2.6e9, 41)
        beta = 2.0 * np.pi * f_hz * math.sqrt(eps_true) / C_LIGHT
        eps, f_med = eps_eff_from_beta(f_hz, beta, 2.5e9)
        assert eps == pytest.approx(eps_true, rel=1e-9)
        assert f_med == pytest.approx(2.5e9)

    def test_window_excludes_outliers(self):
        # ±4% 窗外离群 β 不进中值（engine_benchmark_mline._beta_eps 同口径）：
        # 2.30–2.345GHz（窗 2.4–2.6 之外）注入 2× 离群，结果不受影响
        eps_true = 2.9
        f_wide = np.linspace(2.3e9, 2.7e9, 81)
        beta_wide = 2.0 * np.pi * f_wide * math.sqrt(eps_true) / C_LIGHT
        beta_wide[:6] *= 2.0
        eps, f_med = eps_eff_from_beta(f_wide, beta_wide, 2.5e9)
        assert eps == pytest.approx(eps_true, rel=1e-9)
        assert f_med == pytest.approx(2.5e9)

    def test_empty_window_raises(self):
        with pytest.raises(ValueError, match="无 β 样本"):
            eps_eff_from_beta([1.0e9, 1.1e9], [10.0, 11.0], 2.5e9)

    def test_input_validation(self):
        with pytest.raises(ValueError, match="形状不一致"):
            eps_eff_from_beta([2.4e9, 2.5e9], [10.0], 2.5e9)
        with pytest.raises(ValueError, match="为正"):
            eps_eff_from_beta([2.4e9, 2.5e9], [10.0, 11.0], 0.0)


class TestEpsEffFromS21Phase:
    def test_recovers_eps_with_port_phase_intercept(self):
        # φ(f) = φ0 − 2πf√εeff·L/c：截距（端口参考面相位）被吸收
        eps_true, length_m, phi0 = 2.9, 0.08, 0.3
        f_hz = np.linspace(2.4e9, 2.6e9, 41)
        phase = phi0 - 2.0 * np.pi * f_hz * math.sqrt(eps_true) \
            * length_m / C_LIGHT
        s21 = 0.95 * np.exp(1j * phase)
        eps, meta = eps_eff_from_s21_phase(f_hz, s21, length_m)
        assert eps == pytest.approx(eps_true, rel=1e-6)
        # 截距含 np.angle 折叠分支（mod 2π）：与 φ0 相差整数个 2π
        assert (meta["intercept_rad"] - phi0) % (2.0 * math.pi) == \
            pytest.approx(0.0, abs=1e-9)
        assert meta["slope_rad_per_hz"] == pytest.approx(
            -2.0 * math.pi * math.sqrt(eps_true) * length_m / C_LIGHT,
            rel=1e-9)

    def test_input_validation(self):
        f = np.array([2.4e9, 2.5e9])
        with pytest.raises(ValueError, match="2 个"):
            eps_eff_from_s21_phase(f[:1], np.array([1.0 + 0j]), 0.08)
        with pytest.raises(ValueError, match="为正"):
            eps_eff_from_s21_phase(f, np.array([1.0, 1.0]), 0.0)


class TestEpsEffErrorMetric:
    def test_abs_error_non_db(self):
        assert eps_eff_error_metric(2.900, 2.886) == pytest.approx(0.014)
        assert eps_eff_error_metric(2.886, 2.900) == pytest.approx(0.014)

    def test_nonfinite_raises(self):
        with pytest.raises(ValueError, match="非有限"):
            eps_eff_error_metric(float("nan"), 2.9)

    def test_judge_pair_math_holds_for_non_db_metric(self):
        # cost_degradation_pct 对任何越小越好指标数学成立（非 dB 亦然）
        base = _camp("mline_eps", 0.004, 9, 600.0)
        cand = _camp("mline_eps", 0.006, 25, 200.0)
        v = judge_problem_pair(base, cand)
        assert v["degradation_pct"] == pytest.approx(50.0)
        assert v["verdict"] == "FAIL"  # wall 0.333 过、劣化 50% 超 5% 门
        assert not v["cost_ok"] and v["wallclock_ok"]
        # 反向：试验更优 → 负劣化
        v2 = judge_problem_pair(base, _camp("mline_eps", 0.003, 25, 200.0))
        assert v2["degradation_pct"] == pytest.approx(-25.0)


class TestMlineLandscapeHealthGate:
    def test_healthy_monotonic_landscape_passes(self):
        # 归档探针 1.2mm 真机复算口径（归因记录）：εeff 随 w 单调增、
        # 名义点对 HJ 约 +1.96%（≤3% 副锚）
        w = [0.85, 1.113, 1.4]
        eps = [2.8511, 2.9085, 2.9650]
        gate = mline_landscape_health_gate(
            w, eps, nominal_w=1.113, eps_hj=2.8526)
        assert gate["verdict"] == "PASS"
        assert gate["anchor_ok"] and gate["monotonic_ok"]
        assert gate["nominal_delta_hj_pct"] == pytest.approx(
            (2.9085 / 2.8526 - 1) * 100, abs=1e-6)

    def test_non_monotonic_fails(self):
        gate = mline_landscape_health_gate(
            [0.85, 1.113, 1.4], [2.85, 2.83, 2.96],
            nominal_w=1.113, eps_hj=2.8526)
        assert gate["verdict"] == "FAIL"
        assert not gate["monotonic_ok"] and gate["anchor_ok"]

    def test_nominal_anchor_beyond_tolerance_fails(self):
        gate = mline_landscape_health_gate(
            [0.85, 1.113, 1.4], [2.85, 3.00, 2.96],
            nominal_w=1.113, eps_hj=2.8526, eps_tol_pct=3.0)
        assert gate["verdict"] == "FAIL"
        assert not gate["anchor_ok"]
        assert any("副锚超门" in r for r in gate["reasons"])

    def test_decreasing_direction_supported(self):
        gate = mline_landscape_health_gate(
            [0.85, 1.113, 1.4], [2.96, 2.91, 2.85],
            nominal_w=1.113, eps_hj=2.91, direction="decreasing")
        assert gate["verdict"] == "PASS"

    def test_nominal_missing_raises(self):
        with pytest.raises(ValueError, match="名义点"):
            mline_landscape_health_gate(
                [0.9, 1.2], [2.85, 2.90], nominal_w=1.113, eps_hj=2.8526)


# ── 换判据变体运行器离线件（mline_eps / ratrace_null；零真机）──────────────────


class TestVariantProblemsOffline:
    @pytest.mark.parametrize("problem", ["mline_eps", "ratrace_null"])
    @pytest.mark.parametrize("engine", ["sbo", "pattern_search"])
    def test_variant_dry_run_contract(self, tmp_path, problem, engine):
        pytest.importorskip("smt") if engine == "sbo" else None
        out = runner.run_campaign(problem, engine, tmp_path, dry_run=True)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["stage"] == "done" and data["best"] is not None
        assert data["n_evals"] <= BUDGET_DEFAULT
        assert data["problem"] == problem
        pdef = runner.PROBLEMS[problem]
        assert data["metric_name"] == pdef.metric_name
        assert data["metric_semantics"].endswith(pdef.metric_semantics_note)
        if problem == "mline_eps":
            assert "非 dB" in data["metric_semantics"]
            assert data["best"]["metric"] >= 0.0  # |εeff−target| 非负
            # dry 合成 V 形地貌 target 在 w=1.20：pattern_search 精确逼近；
            # sbo 受 stagnation 容差（0.003 vs 域内量程 0.084）可提前停，
            # 契约测试只钉方向不钉收敛精度（真机判据看 runs/ JSON）
            tol = 0.05 if engine == "pattern_search" else 0.15
            assert data["best"]["params"]["w_mm"] == pytest.approx(1.20, abs=tol)
        else:
            assert data["best"]["metric"] < 0.0  # 邻域功率平均 dB

    def test_variant_sweep_declared(self):
        m = runner.PROBLEMS["mline_eps"]
        r = runner.PROBLEMS["ratrace_null"]
        assert m.sweep["band_ghz"] == (2.4, 2.6) and m.sweep["points"] == 41
        assert m.calibrate is True and m.eps_extract is not None
        # 起点≠标定点：target 在名义点 1.113 标定，Pattern Search 起点域中心
        # 1.25（起点=最优则 metric≡0 不可判；sbo 臂无起点先验）
        assert m.x0 == {"w_mm": 1.25} and m.nominal == {"w_mm": 1.113}
        assert r.x0 is None  # ratrace_null 仍从名义点起（同原 ratrace 口径）
        assert r.sweep["band_ghz"] == runner.RATRACE_NULL_SEARCH_GHZ == (2.3, 2.7)
        assert r.sweep["points"] == 81 and r.sweep["type"] == "Interpolating"
        # 与 ratrace_null.json 归档常量同源：hw 25MHz
        assert pytest.approx(0.025) == runner.RATRACE_NULL_HW_GHZ
        # 原三问题保持单频 setup（回归不动）
        for name in ("mline", "patch", "ratrace"):
            assert runner.PROBLEMS[name].sweep is None
            assert runner.PROBLEMS[name].calibrate is False

    def test_sbo_tol_abs_scales_with_metric(self):
        assert runner.sbo_tol_abs(runner.PROBLEMS["mline"]) == runner.SBO_TOL_ABS_DB
        assert runner.sbo_tol_abs(runner.PROBLEMS["ratrace_null"]) == \
            runner.SBO_TOL_ABS_DB
        assert runner.sbo_tol_abs(runner.PROBLEMS["mline_eps"]) == \
            runner.SBO_TOL_ABS_EPS < runner.SBO_TOL_ABS_DB

    def test_mline_eps_metric_requires_calibration(self, monkeypatch):
        skrf = pytest.importorskip("skrf")
        monkeypatch.setitem(runner.EPS_TARGET, "mline_eps", None)
        f_hz = np.linspace(2.4e9, 2.6e9, 41)
        eps_true = 2.9
        phase = -2.0 * np.pi * f_hz * math.sqrt(eps_true) \
            * runner.MLINE_LINE_LEN_M / C_LIGHT
        s = np.zeros((41, 2, 2), dtype=complex)
        s[:, 1, 0] = s[:, 0, 1] = 0.98 * np.exp(1j * phase)
        net = skrf.Network(frequency=skrf.Frequency.from_f(f_hz, "hz"), s=s)
        # 线长 = 波端口面间距 2×40mm=80mm
        assert pytest.approx(0.080) == runner.MLINE_LINE_LEN_M
        assert runner._mline_eps_from_network(net) == pytest.approx(eps_true,
                                                                    rel=1e-6)
        with pytest.raises(RuntimeError, match="未标定"):
            runner._mline_eps_metric(net)
        monkeypatch.setitem(runner.EPS_TARGET, "mline_eps", 2.886)
        assert runner._mline_eps_metric(net) == pytest.approx(0.014, abs=1e-6)

    def test_ratrace_null_metric_from_network(self):
        skrf = pytest.importorskip("skrf")
        f = np.linspace(2.3e9, 2.7e9, 81)
        s31_db = np.full(f.shape, -20.0)
        i0 = int(np.argmin(np.abs(f - 2.465e9)))
        s31_db[i0 - 1:i0 + 2] = [-35.0, -50.0, -35.0]
        s = np.zeros((f.size, 4, 4), dtype=complex)
        s[:, 2, 0] = 10 ** (s31_db / 20.0)
        net = skrf.Network(frequency=skrf.Frequency.from_f(f, "hz"), s=s)
        v = runner._s31_null_neighborhood_db(net)
        # 邻域 ±25MHz（5MHz 栅格 → 11 点）功率平均落在谷深与平底之间
        assert -50.0 < v < -20.0
        # 与 service 内核同源直算一致
        from rfauto.service.wp39_benchmark import deep_null_neighborhood_db
        assert v == pytest.approx(deep_null_neighborhood_db(
            f / 1e9, s31_db, 2.3, 2.7, 0.025))

    def test_judge_skips_problems_not_in_outdir(self, tmp_path):
        # 只放 ratrace_null 两臂：judge 表只含它（原三问题/其他变体不占表）
        for eng, metric, wall in (("pattern_search", -40.0, 600.0),
                                  ("sbo", -39.8, 250.0)):
            (tmp_path / f"ratrace_null__{eng}.json").write_text(json.dumps({
                "problem": "ratrace_null",
                "best": {"params": {"r_mm": 17.0}, "metric": metric},
                "n_evals": 10, "wall_s": {"optimization_s": wall}}),
                encoding="utf-8")
        data = json.loads(runner.judge(tmp_path).read_text(encoding="utf-8"))
        assert set(data["problems"]) == {"ratrace_null"}
        assert data["problems"]["ratrace_null"]["verdict"] == "PASS"
        assert data["summary"]["n_problems"] == 1
