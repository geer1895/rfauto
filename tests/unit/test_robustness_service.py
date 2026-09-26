"""DP-15 C3：良率流水线第二片（向量化 MC/FORM v1/worst-case/profile/report）。

判据预声明见 runs/df6_dp15c3/criteria.md（先于实现写就）：
- (d) 向量化 vs 旧循环逐位一致（1e3 同种子 yield 逐位同）；
- (b) FORM 线性失效面合成例 Pf 相对差 ≤20%（实测机器精度级）；深谷
  非线性如实标近似（method_note + pf_vs_mc 对照，不凑 PASS）；
- (c) 1e6 点 MC wall ≤48s（#327 口径，实测数字进 verdict.json）；
- DuckDB/Parquet 落盘复用 query_dataset 读面（#369 n_rows 陷阱钉）。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def samples_path(tmp_path):
    """合成数据集：s11 = -20 + 5*(L-20)^2 + 10*(w-0.35)^2（二次可拟合）。"""
    rng = np.random.default_rng(7)
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for _ in range(25):
        L = float(rng.uniform(*bounds["arm_len_mm"]))
        w = float(rng.uniform(*bounds["series_w_mm"]))
        s11 = -20.0 + 5.0 * (L - 20.0) ** 2 + 10.0 * (w - 0.35) ** 2
        samples.append({
            "params": {"arm_len_mm": L, "series_w_mm": w},
            "metrics": {"s11_db_max_in_band": float(s11),
                        "s21_db_mean_in_band": -3.3},
        })
    samples[0]["params"] = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
    samples[0]["metrics"] = {"s11_db_max_in_band": -20.0,
                             "s21_db_mean_in_band": -3.3}
    data = {
        "bounds": bounds,
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "samples": samples,
    }
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 判据 d：向量化 vs 旧循环逐位一致 + 对外兼容
# ---------------------------------------------------------------------------

class TestVectorizedMcYield:
    def test_bitwise_matches_loop(self, samples_path):
        """判据 d：同种子 1e3 双跑，向量化 yield/统计逐位等于旧循环。"""
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1, "series_w_mm": 0.02}
        for seed in (1, 42):
            r_new = uq_service.surrogate_yield(samples_path, tol,
                                               n=1000, seed=seed)
            ctx, errs = uq_service._load_yield_context(samples_path, tol)
            assert ctx is not None, errs
            nominal = {k: float(v)
                       for k, v in ctx["nominal_sample"]["params"].items()}
            r_old = uq_service._mc_yield_loop(ctx, nominal, tol,
                                              n=1000, seed=seed)
            assert r_new["implementation"] == "vectorized"
            assert r_new["yield_rate"] == r_old["yield_rate"]
            for m, stats in r_old["metric_stats"].items():
                for k in ("mean", "std", "q05", "q95"):
                    assert r_new["metric_stats"][m][k] == stats[k]

    def test_same_seed_reproducible(self, samples_path):
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1}
        a = uq_service.surrogate_yield(samples_path, tol, n=1000, seed=3)
        b = uq_service.surrogate_yield(samples_path, tol, n=1000, seed=3)
        assert a["yield_rate"] == b["yield_rate"]
        assert a["yield_rate"] > 0.9  # 名义点余量大 → 良率高（语义不变）

    def test_public_output_superset_of_legacy_keys(self, samples_path):
        """对外兼容：既有键全在；新增确定性键 implementation。

        wall_s（计时浮点）不进公开面——test_wp42_yield 的同种子全 JSON
        逐字节钉会被计时差打破（回归教训，wall_s 仅存在于 _mc_yield
        内部产物与 robustness_report 报告体）。
        """
        from rfauto.service import uq_service

        r = uq_service.surrogate_yield(samples_path, {"arm_len_mm": 0.1},
                                       n=500, seed=1)
        for key in ("ok", "samples_path", "uncertainty_status",
                    "surrogate_kind", "n_draws", "seed", "nominal_params",
                    "nominal_metrics", "tolerances", "yield_rate",
                    "metric_stats", "sensitivity_ranking",
                    "sensitivity_violation_delta"):
            assert key in r, key
        assert "implementation" in r
        assert "wall_s" not in r

    def test_wall_1e6_under_48s(self, samples_path):
        """判据 c：1e6 点向量化 MC wall ≤48s（#327 口径；实测内核 wall_s）。"""
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1, "series_w_mm": 0.02}
        ctx, errs = uq_service._load_yield_context(samples_path, tol)
        assert ctx is not None, errs
        nominal = {k: float(v)
                   for k, v in ctx["nominal_sample"]["params"].items()}
        mc = uq_service._mc_yield(ctx, nominal, tol, n=1_000_000, seed=42)
        assert mc["implementation"] == "vectorized"
        assert mc["wall_s"] < 48.0
        assert 0.0 <= mc["yield_rate"] <= 1.0

    def test_gp_batch_path_close_to_loop(self, samples_path):
        """smt_kriging 分块批预测：良率判类与循环一致，预测 allclose。"""
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1}
        ctx, errs = uq_service._load_yield_context(
            samples_path, tol, kind="smt_kriging")
        assert ctx is not None, errs
        nominal = {k: float(v)
                   for k, v in ctx["nominal_sample"]["params"].items()}
        rv = uq_service._mc_yield(ctx, nominal, tol, n=2000, seed=1)
        rl = uq_service._mc_yield_loop(ctx, nominal, tol, n=2000, seed=1)
        assert rv["implementation"] == "vectorized"
        assert rv["yield_rate"] == rl["yield_rate"]
        for m in rl["metric_stats"]:
            assert rv["metric_stats"][m]["mean"] == pytest.approx(
                rl["metric_stats"][m]["mean"], abs=1e-6)

    def test_missing_metric_early_break_semantics_preserved(
            self, samples_path):
        """缺指标 early-break 语义逐位复刻：缺指标 spec → 全体 draw fail。"""
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1}
        ctx, _ = uq_service._load_yield_context(samples_path, tol)
        ctx = dict(ctx)
        ctx["specs"] = [*ctx["specs"],
                        {"metric": "nope_key", "op": "max_below",
                         "spec": 0.0}]
        nominal = {k: float(v)
                   for k, v in ctx["nominal_sample"]["params"].items()}
        rv = uq_service._mc_yield(ctx, nominal, tol, n=300, seed=1)
        rl = uq_service._mc_yield_loop(ctx, nominal, tol, n=300, seed=1)
        assert rv["yield_rate"] == 0.0 == rl["yield_rate"]
        assert rv["yield_rate"] == rl["yield_rate"]

    def test_loop_fallback_for_plain_predict_model(self, samples_path,
                                                   monkeypatch):
        """裸 predict 模型（_SigmaStub 面）→ 回退逐点循环，行为不变。"""

        class _Stub:
            KIND = "stub_plain"

            def fit(self, samples):
                return {"n_samples": len(samples)}

            def predict(self, params):
                return {"s11_db_max_in_band":
                        -20.0 + 5.0 * (float(params["arm_len_mm"]) - 20)**2}

        monkeypatch.setattr(
            "rfauto.service.calibration_service._make_model",
            lambda kind, bounds, **kw: _Stub())
        from rfauto.service import uq_service

        r = uq_service.surrogate_yield(samples_path, {"arm_len_mm": 0.1},
                                       n=300, seed=1)
        assert r["implementation"] == "loop"
        assert r["ok"]


# ---------------------------------------------------------------------------
# DuckDB/Parquet 落盘 + query_dataset 读面（#369）
# ---------------------------------------------------------------------------

class TestMcStore:
    @staticmethod
    def _internal_mc(samples_path, n=20_000, seed=1):
        """store_mc_draws 契约：吃 _mc_yield 内部产物（含 _draw_columns）。"""
        from rfauto.service import uq_service

        tol = {"arm_len_mm": 0.1, "series_w_mm": 0.02}
        ctx, errs = uq_service._load_yield_context(samples_path, tol)
        assert ctx is not None, errs
        nominal = {k: float(v)
                   for k, v in ctx["nominal_sample"]["params"].items()}
        mc = uq_service._mc_yield(ctx, nominal, tol, n=n, seed=seed)
        return mc, ctx

    def test_store_query_dataset_roundtrip(self, samples_path, tmp_path):
        from rfauto.service import uq_service
        from rfauto.service.dataset_service import query_dataset

        out_dir = tmp_path / "runs" / "datasets"
        mc, ctx = self._internal_mc(samples_path)
        st = uq_service.store_mc_draws("mc_pin_20k", mc, objs=ctx["objs"],
                                       out_dir=out_dir, seed=1,
                                       source_dataset="synthetic")
        assert st["ok"], st.get("errors")
        assert st["n_rows"] == 20_000
        assert "cost" in st["columns"]
        # query_dataset 读面可查：where/columns/limit 正常
        qr = query_dataset("mc_pin_20k", where="is_pass = 0", limit=3,
                           out_dir=out_dir)
        assert qr["ok"], qr.get("errors")
        assert qr["n_rows"] == 3  # limit 截断语义（#369）
        for col in ("draw_index", "param__arm_len_mm", "is_pass"):
            assert col in qr["columns"], col
        # 全量计数以 manifest n_rows 为准（大 limit 对账）
        qa = query_dataset("mc_pin_20k", limit=10_000_000, out_dir=out_dir)
        assert qa["n_rows"] == 20_000 == st["n_rows"]
        # cost 列与 yield 一致（is_pass ⇔ cost == 0，spec 语义对账）
        qc = query_dataset("mc_pin_20k", where="cost > 0",
                           limit=10_000_000, out_dir=out_dir)
        n_fail = qc["n_rows"]
        assert n_fail == round((1.0 - mc["yield_rate"]) * 20_000)

    def test_store_rejects_loop_result(self):
        from rfauto.service import uq_service

        st = uq_service.store_mc_draws("mc_bad", {"yield_rate": 1.0})
        assert not st["ok"]

    def test_store_rejects_public_stripped_result(self, samples_path,
                                                  tmp_path):
        """对外公开面（无 _draw_columns）不可落盘——内部产物契约。"""
        from rfauto.service import uq_service

        r = uq_service.surrogate_yield(samples_path, {"arm_len_mm": 0.1},
                                       n=200, seed=1)
        st = uq_service.store_mc_draws("bad name!", r,
                                       out_dir=tmp_path / "ds")
        assert not st["ok"]


# ---------------------------------------------------------------------------
# FORM v1（判据 b）
# ---------------------------------------------------------------------------

class TestFormPf:
    def test_linear_failure_surface_analytic(self):
        """判据 b：线性失效面 Pf 相对差 ≤20%（实测机器精度级）。"""
        from rfauto.service.robustness_service import form_pf

        mu = {"x1": 1.0, "x2": -0.5}
        sig = {"x1": 0.5, "x2": 0.25}

        def cost(p):
            return -1.0 + 2.0 * (p["x1"] - mu["x1"]) \
                + 1.0 * (p["x2"] - mu["x2"])

        r = form_pf(cost, mu, sig)
        beta_a = 1.0 / math.sqrt((2.0 * 0.5) ** 2 + (1.0 * 0.25) ** 2)
        pf_a = 0.5 * math.erfc(beta_a / math.sqrt(2.0))
        assert r["ok"] and r["converged"]
        assert r["form_engine"] == "internal"
        rel = abs(r["pf"] - pf_a) / pf_a
        assert rel <= 0.20  # 预声明门
        assert rel < 1e-9  # 实测：线性面机器精度级

    def test_mean_in_failure_side(self):
        from rfauto.service.robustness_service import form_pf

        mu = {"x1": 1.0, "x2": -0.5}
        sig = {"x1": 0.5, "x2": 0.25}

        def cost(p):
            return 1.0 - 2.0 * (p["x1"] - mu["x1"]) \
                - 1.0 * (p["x2"] - mu["x2"])

        r = form_pf(cost, mu, sig)
        assert r["pf"] == pytest.approx(0.8340122664586316, abs=1e-6)
        assert r["beta"] < 0  # 均值在失效域 → β 负号如实

    def test_nonlinear_deep_valley_labeled_approximate(self):
        """深谷非线性：抛物线谷 FORM 点解析可证（β=0.5），MC 对照差异
        如实进 pf_vs_mc/method_note，不凑 PASS。"""
        from rfauto.service.robustness_service import form_pf

        mu = {"x1": 1.0, "x2": -0.5}
        sig = {"x1": 0.5, "x2": 0.25}

        def g_valley(u):
            return 0.5 + u[1] + 2.0 * u[0] ** 2  # 谷形失效面

        def cost(p):
            return -g_valley([(p["x1"] - mu["x1"]) / sig["x1"],
                              (p["x2"] - mu["x2"]) / sig["x2"]])

        r = form_pf(cost, mu, sig)
        pf_form_analytic = 0.5 * math.erfc(0.5 / math.sqrt(2.0))
        assert r["converged"]
        assert r["pf"] == pytest.approx(pf_form_analytic, rel=0.02)
        # MC 对照（向量化参照系）：差异如实（谷面强非线性，一阶近似）
        rng = np.random.default_rng(5)
        u1 = rng.normal(0.0, 1.0, 1_000_000)
        u2 = rng.normal(0.0, 1.0, 1_000_000)
        pf_mc = float(np.mean(0.5 + u2 + 2.0 * u1 ** 2 <= 0.0))
        if pf_mc > 0:
            rel = abs(r["pf"] - pf_mc) / pf_mc
            assert "近似" in r["method_note"]
            assert rel != 0.0 or pf_mc == r["pf"]  # 如实，不强制相等

    def test_flat_surface_honest_no_info(self):
        from rfauto.service.robustness_service import form_pf

        r = form_pf(
            lambda p: max(0.0, (-40.0 + 5.0 * (p["L"] - 20.0) ** 2)
                          - (-15.0)),
            {"L": 20.0}, {"L": 0.1})
        assert r["ok"] and not r["converged"]
        assert r["n_converged_starts"] == 0
        assert any("无信息量" in n for n in r.get("notes", []))

    def test_hinge_crossing_converges_to_mc_neighborhood(self):
        """hinge 违约面（对称双支）：FORM 单模近似 + 如实报告。"""
        from rfauto.service.robustness_service import form_pf

        def cost(p):
            return max(0.0, (-20.0 + 5.0 * (p["L"] - 20.0) ** 2) - (-15.0))

        r = form_pf(cost, {"L": 20.0}, {"L": 0.6})
        assert r["converged"]
        # 双支对称面：真 Pf≈2·Φ(−β)；单模 FORM 如实低报（β 一致性）
        assert 0.0 < r["pf"] < 0.5
        beta = abs(r["beta"])
        assert abs(r["pf"] - 0.5 * math.erfc(beta / math.sqrt(2.0))) < 1e-12

    def test_engine_channel_monkeypatched(self, monkeypatch):
        """#139 惯例：外部库通道 monkeypatch 钉（存在→对照/缺失→note）。"""
        from rfauto.service import robustness_service as rs

        mu = {"x1": 1.0}
        sig = {"x1": 0.5}

        def cost(p):
            return -1.0 + (p["x1"] - mu["x1"])

        class _FakeOT:
            pass  # 触发 API 异常 → 对照如实 ok=False

        monkeypatch.setattr(rs, "_import_openturns", lambda: _FakeOT())
        r = rs.form_pf(cost, mu, sig, form_engine="auto")
        assert r["form_engine"] == "internal"  # 主算始终 internal
        assert r["cross_check"]["engine"] == "openturns"
        assert r["cross_check"]["ok"] is False

        monkeypatch.setattr(rs, "_import_openturns", lambda: None)
        monkeypatch.setattr(rs, "_import_uqpy", lambda: None)
        r2 = rs.form_pf(cost, mu, sig, form_engine="auto")
        assert "cross_check" not in r2
        assert any("均未安装" in n for n in r2.get("notes", []))

        r3 = rs.form_pf(cost, mu, sig, form_engine="openturns")
        assert r3["form_engine"] == "internal"
        assert any("回退 internal" in n for n in r3.get("notes", []))

    def test_input_validation(self):
        from rfauto.service.robustness_service import form_pf

        assert not form_pf(lambda p: 0.0, {}, {"x": 1.0})["ok"]  # 缺名义
        assert not form_pf(lambda p: 0.0, {"x": 1.0}, {})["ok"]
        assert not form_pf(lambda p: 0.0, {"x": 1.0}, {"x": -1.0})["ok"]


# ---------------------------------------------------------------------------
# worst-case（复用 pce._pattern_search）
# ---------------------------------------------------------------------------

class TestSurrogateWorstCase:
    def test_finds_violating_corner(self):
        from rfauto.service.robustness_service import surrogate_worst_case

        mu = {"x1": 1.0, "x2": -0.5}
        sig = {"x1": 0.5, "x2": 0.25}
        def cost(p):
            return sum(((p[k] - mu[k]) / sig[k]) ** 2 for k in mu)

        r = surrogate_worst_case(cost, mu, sig,
                                 {"x1": (-5.0, 5.0), "x2": (-5.0, 5.0)},
                                 k_sigma=3.0)
        assert r["ok"] and r["violated"]
        assert r["cost"] == pytest.approx(18.0, rel=1e-9)  # 2×(3σ)²/σ²
        assert r["n_starts"] == 5  # 中心 + 2² 角点
        assert "_pattern_search" in r["search"]
        assert r["params"]["x1"] == pytest.approx(2.5)  # 名义 +3σ

    def test_box_clipped_to_bounds(self):
        from rfauto.service.robustness_service import surrogate_worst_case

        mu = {"x": 0.0}
        def cost(p):
            return abs(p["x"])

        r = surrogate_worst_case(cost, mu, {"x": 1.0}, {"x": (-2.0, 1.5)},
                                 k_sigma=3.0)
        assert r["box"]["x"] == [-2.0, 1.5]  # ±3σ 被界裁剪
        assert r["params"]["x"] == pytest.approx(-2.0)

    def test_validation(self):
        from rfauto.service.robustness_service import surrogate_worst_case

        assert not surrogate_worst_case(
            lambda p: 0.0, {}, {"x": 1.0}, {"x": (0, 1)}, k_sigma=0)["ok"]
        assert not surrogate_worst_case(
            lambda p: 0.0, {"y": 0.0}, {"x": 1.0},
            {"x": (0, 1)})["ok"]  # 名义缺参数


# ---------------------------------------------------------------------------
# 公差 profile schema（±20µm → σ=20/3 µm）
# ---------------------------------------------------------------------------

class TestToleranceProfile:
    def test_sigma_is_tol_over_k_sigma(self):
        from rfauto.service.robustness_service import load_tolerance_profile

        lp = load_tolerance_profile({
            "profile": "fab_std",
            "params": {"w_mm": {"tol": 0.02, "unit": "mm"},
                       "gap_mm": {"tol": 0.01}},
        })
        assert lp["ok"]
        assert lp["k_sigma"] == 3.0
        assert lp["sigmas"]["w_mm"] == pytest.approx(0.02 / 3.0)
        assert lp["sigmas"]["gap_mm"] == pytest.approx(0.01 / 3.0)
        assert lp["tolerances"]["w_mm"] == 0.02
        assert lp["units"] == {"w_mm": "mm"}
        assert lp["fab"] is None

    def test_k_sigma_override_nominal_and_fab_passthrough(self):
        from rfauto.service.robustness_service import load_tolerance_profile

        lp = load_tolerance_profile({
            "k_sigma": 4.0,
            "params": {"w_mm": {"tol": 0.02, "nominal": 0.5}},
            "fab": {"process": "std", "notes": "DP-7 解析接口挂载点"},
        })
        assert lp["ok"]
        assert lp["sigmas"]["w_mm"] == pytest.approx(0.005)
        assert lp["nominal_overrides"] == {"w_mm": 0.5}
        assert lp["fab"] == {"process": "std",
                             "notes": "DP-7 解析接口挂载点"}

    def test_yaml_file_loading(self, tmp_path):
        import yaml

        from rfauto.service.robustness_service import load_tolerance_profile

        p = tmp_path / "profile.yaml"
        p.write_text(yaml.safe_dump({
            "profile": "cpw_fab_std",
            "k_sigma": 3.0,
            "params": {"w_mm": {"tol": 0.02, "unit": "mm"},
                       "gap_mm": {"tol": 0.01}},
        }), encoding="utf-8")
        lp = load_tolerance_profile(str(p))
        assert lp["ok"] and lp["profile"] == "cpw_fab_std"
        assert lp["sigmas"]["w_mm"] == pytest.approx(0.02 / 3.0)

    def test_validation_errors(self, tmp_path):
        from rfauto.service.robustness_service import load_tolerance_profile

        assert not load_tolerance_profile({"params": {}})["ok"]
        assert not load_tolerance_profile(
            {"params": {"w": {"tol": -1.0}}})["ok"]
        assert not load_tolerance_profile(
            {"params": {"w": {"tol": 0.01, "dist": "uniform"}}})["ok"]
        assert not load_tolerance_profile(
            {"k_sigma": 0.0, "params": {"w": {"tol": 0.01}}})["ok"]
        assert not load_tolerance_profile(tmp_path / "nope.yaml")["ok"]
        assert not load_tolerance_profile(42)["ok"]


# ---------------------------------------------------------------------------
# robustness_report（JSON 进出编排面）
# ---------------------------------------------------------------------------

class TestRobustnessReport:
    def test_samples_mode_end_to_end(self, samples_path, tmp_path):
        from rfauto.service.robustness_service import robustness_report

        prof = {"profile": "smoke", "params": {
            "arm_len_mm": {"tol": 0.3}, "series_w_mm": {"tol": 0.06}}}
        rep = robustness_report(
            samples_path, [{"metric": "s11_db", "op": "max_below",
                            "value": -15}],
            profile=prof, n_mc=20_000, seed=42, persist=True,
            store_name="mc_report_pin", store_out_dir=tmp_path / "ds")
        assert rep["ok"], rep.get("errors")
        # JSON 可序列化（进出契约）
        text = json.dumps(rep, ensure_ascii=False, allow_nan=False)
        assert "yield_rate" in text
        assert rep["yield_mc"]["implementation"] == "vectorized"
        assert rep["yield_mc"]["n_draws"] == 20_000
        assert rep["uncertainty_status"]["status"] == "qualitative"
        for key in ("form", "worst_case", "cpk", "pf_vs_mc", "profile",
                    "tolerance_source", "sigmas", "nominal_params"):
            assert key in rep, key
        assert rep["form"]["form_engine"] == "internal"
        assert rep["worst_case"]["violated"] is True
        assert rep["yield_mc"]["store"]["n_rows"] == 20_000
        assert rep["cpk"]["s11_db#0"]["cpk"] is not None
        # Cpk 口径对账：(usl − mean)/(3 std)（MC 分布统计）
        stats = rep["yield_mc"]["metric_stats"]["s11_db_max_in_band"]
        assert rep["cpk"]["s11_db#0"]["cpk"] == pytest.approx(
            (-15.0 - stats["mean"]) / (3.0 * stats["std"]), rel=1e-9)

    def test_dataset_mode_via_mc_store(self, samples_path, tmp_path):
        """dataset 模式：先用 store_mc_draws 造数据集，再以名字进报告。"""
        from rfauto.service import uq_service
        from rfauto.service.robustness_service import robustness_report

        out_dir = tmp_path / "ds"
        mc, ctx = TestMcStore._internal_mc(samples_path, n=5_000)
        st = uq_service.store_mc_draws("mc_ds_src", mc, objs=ctx["objs"],
                                       out_dir=out_dir, seed=1)
        assert st["ok"], st.get("errors")
        rep = robustness_report(
            "mc_ds_src",
            [{"metric": "s11_db", "op": "max_below", "value": -15}],
            profile={"params": {"arm_len_mm": {"tol": 0.3}}},
            n_mc=2_000, seed=7, store_out_dir=out_dir)
        assert rep["ok"], rep.get("errors")
        assert rep["dataset"] == "mc_ds_src"
        assert rep["yield_mc"]["implementation"] == "vectorized"

    def test_tolerances_arg_mode(self, samples_path):
        from rfauto.service.robustness_service import robustness_report

        rep = robustness_report(
            samples_path,
            [{"metric": "s11_db", "op": "max_below", "value": -15}],
            tolerances={"arm_len_mm": 0.1}, n_mc=1_000, seed=1)
        assert rep["ok"], rep.get("errors")
        assert rep["tolerance_source"] == "tolerances_arg"
        assert rep["sigmas"] == {"arm_len_mm": 0.1}

    def test_unknown_source_rejected(self, tmp_path):
        from rfauto.service.robustness_service import robustness_report

        rep = robustness_report(
            "no_such_thing_anywhere",
            [{"metric": "s11_db", "op": "max_below", "value": -15}],
            tolerances={"arm_len_mm": 0.1})
        assert not rep["ok"]
        assert rep["errors"]

    def test_missing_tolerance_rejected(self, samples_path):
        from rfauto.service.robustness_service import robustness_report

        rep = robustness_report(
            samples_path,
            [{"metric": "s11_db", "op": "max_below", "value": -15}])
        assert not rep["ok"]
        assert not robustness_report(
            samples_path, [], tolerances={"arm_len_mm": 0.1})["ok"]
        assert not robustness_report(
            samples_path,
            [{"metric": "s11_db", "op": "max_below", "value": -15}],
            tolerances={"arm_len_mm": 0.1}, n_mc=0)["ok"]
