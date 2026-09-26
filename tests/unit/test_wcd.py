"""DP-18 C8：WCD 设计中心化 + Cpk 定向测试。

裁判口径（数值对独立来源核验铁律 #118）
-----------------------
- 判据 a 解析回收：两维抛物面 + 圆规范 WCD = √(L/α) − ‖中心偏移‖ 手算
  （推导见 runs/df6_dp18c8/criteria.md §2），内核直喂解析 callable
  （不含拟合误差），|差| ≤ 1e-9；各向异性 σ 情形与测试内**独立参考
  实现**（稠密方向 × 逐向二次方程求根闭式，不经被测内核）对照 ≤1e-6；
- 判据 c Cpk：手算公式独立写死（不调被测函数生成），并与
  robustness_service._cpk_for_objectives 跨实现对照同值；
- 全部确定性、固定种子、无网络。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# margin 镜像一致性
# ---------------------------------------------------------------------------


class TestSpecMargin:
    def test_margin_hinge_matches_vector_spec_cost(self):
        """hinge = max(0, −margin) 与 _vector_spec_cost 逐点一致（镜像对象）。

        注意既有逐点 _violates 不含 bandwidth 分支（恒 False）——mirror
        对象是 MC cost 列/FORM 失效面的 _vector_spec_cost（四 op 全处理）。
        """
        from rfauto.core.objectives import MetricOp
        from rfauto.core.wcd import spec_margin
        from rfauto.service.uq_service import _violates

        cases = [
            ("max_below", -15.0, [-20.0, -15.0, -10.0]),
            ("min_above", 0.5, [0.4, 0.5, 0.6]),
            ("mean_within", [0.0, 2.0], [-0.1, 0.0, 1.0, 2.0, 2.1]),
            ("bandwidth", 1.0, [0.9, 1.0, 1.1]),
        ]
        for op, value, values in cases:
            for v in values:
                margin = spec_margin(op, value, v)
                hinge = max(0.0, -margin)
                if op == MetricOp.MAX_BELOW:
                    expect = max(0.0, v - value)
                elif op == MetricOp.MIN_ABOVE:
                    expect = max(0.0, value - v)
                elif op == MetricOp.MEAN_WITHIN:
                    lo, hi = value
                    expect = (lo - v) if v < lo else (v - hi if v > hi else 0.0)
                else:  # bandwidth
                    expect = max(0.0, value - v)
                assert hinge == pytest.approx(expect), (op, v)
                # 三 op 共享面：与 _violates 判定一致（bandwidth 系其超集）
                if op != "bandwidth":
                    assert _violates(v, op, value) == (margin < 0.0), (op, v)

    def test_unknown_op_is_nan(self):
        from rfauto.core.wcd import spec_margin

        assert math.isnan(spec_margin("nope", 1.0, 0.0))


# ---------------------------------------------------------------------------
# 判据 a：解析回收（两维抛物面 + 圆规范）
# ---------------------------------------------------------------------------


class TestAnalyticRecovery:
    ALPHA = 1.0
    L = 9.0
    Z0 = (2.0, 1.0)  # 中心偏移
    TOL = 1e-9

    def _disk_margin(self):
        alpha, L = self.ALPHA, self.L
        z0 = np.array(self.Z0, dtype=float)

        def g(u: np.ndarray) -> float:
            return L - alpha * float(np.sum((u - z0) ** 2))

        return g

    def test_2d_vertex_form(self):
        """WCD = √(L/α) − ‖z*‖（推导：最近边界点在 C→O 延长线上）。"""
        from rfauto.core.wcd import boundary_distance

        g = self._disk_margin()
        res = boundary_distance(g, dim=2)
        analytic = math.sqrt(self.L / self.ALPHA) - math.hypot(*self.Z0)
        assert res["ok"] and res["inside"] and not res["censored"]
        assert res["refined"]
        assert abs(res["distance"] - analytic) <= self.TOL

    def test_2d_expanded_form_equivalent(self):
        """展开式 α(x²+y²)+bx+cy+d（d=α‖z*‖²）与顶点式同值（≤1e-9）。"""
        from rfauto.core.wcd import boundary_distance

        alpha, L = self.ALPHA, self.L
        z0 = np.array(self.Z0, dtype=float)
        b = -2.0 * alpha * z0
        d0 = alpha * float(z0 @ z0)

        def g(u: np.ndarray) -> float:
            return L - (alpha * float(u @ u) + float(b @ u) + d0)

        res = boundary_distance(g, dim=2)
        analytic = math.sqrt(L / alpha) - math.hypot(*self.Z0)
        assert abs(res["distance"] - analytic) <= self.TOL

    def test_1d(self):
        from rfauto.core.wcd import boundary_distance

        def g(u: np.ndarray) -> float:
            return 5.0 - (u[0] - 1.0) ** 2

        res = boundary_distance(g, dim=1)
        assert abs(res["distance"] - (math.sqrt(5.0) - 1.0)) <= self.TOL

    def test_anisotropic_sigma_vs_independent_reference(self):
        """σ=(1,2) 椭圆可接受域 vs 测试内独立参考（稠密方向闭式求根）。"""
        from rfauto.core.wcd import boundary_distance

        # 可接受域（u 空间）：(u0−2)² + (2u1−1)² ≤ 9，原点在域内
        def g(u: np.ndarray) -> float:
            return 9.0 - ((u[0] - 2.0) ** 2 + (2.0 * u[1] - 1.0) ** 2)

        res = boundary_distance(g, dim=2)

        # 独立参考：f(r,θ)=a·r²+b·r−4，a=θ0²+4θ1²，b=−4(θ0+θ1)，
        # 正根 r(θ)=(−b+√(b²+16a))/(2a)；min over 40k 稠密方向。
        best = math.inf
        for phi in np.linspace(0.0, 2.0 * math.pi, 40_001, endpoint=False):
            t0 = math.cos(phi)
            t1 = math.sin(phi)
            a = t0 * t0 + 4.0 * t1 * t1
            b = -4.0 * (t0 + t1)
            r = (-b + math.sqrt(b * b + 16.0 * a)) / (2.0 * a)
            best = min(best, r)
        assert abs(res["distance"] - best) <= 1e-6

    def test_3d_sphere_offset(self):
        from rfauto.core.wcd import boundary_distance

        z0 = np.array([1.0, 0.0, 0.0])

        def g(u: np.ndarray) -> float:
            return 9.0 - float(np.sum((u - z0) ** 2))

        res = boundary_distance(g, dim=3)
        assert res["ok"]
        assert abs(res["distance"] - (3.0 - 1.0)) <= 1e-6

    def test_nominal_violated_negative_distance(self):
        """名义已违约 → 距离为负，|distance| = ‖z*‖ − R。"""
        from rfauto.core.wcd import boundary_distance

        # R=1, z*=(2,1)：g(0) = 1−5 < 0（违约），WCD = −(√5−1)
        def g(u: np.ndarray) -> float:
            return 1.0 - float(np.sum((u - np.array([2.0, 1.0])) ** 2))

        res = boundary_distance(g, dim=2)
        assert res["ok"] and not res["inside"]
        assert abs(res["distance"] - (-(math.hypot(2.0, 1.0) - 1.0))) <= 1e-9

    def test_censored_when_never_violates(self):
        from rfauto.core.wcd import boundary_distance

        res = boundary_distance(lambda u: 100.0, dim=2, r_max=2.0)
        assert res["ok"] and res["censored"]
        assert res["distance"] == pytest.approx(2.0)

    def test_deterministic(self):
        from rfauto.core.wcd import boundary_distance

        g = self._disk_margin()
        a = boundary_distance(g, dim=2)
        b = boundary_distance(g, dim=2)
        assert a["distance"] == b["distance"]
        assert a["point_u"] == b["point_u"]


# ---------------------------------------------------------------------------
# 判据 c：Cpk 独立手工公式对照（合成 fixture）
# ---------------------------------------------------------------------------


class TestCpkFromMetricStats:
    FIXTURE_STATS: ClassVar[dict] = {
        "m1": {"mean": -18.0, "std": 1.0},
        "m2": {"mean": -0.2, "std": 0.1},
        "m3": {"mean": 0.9, "std": 0.1},
    }
    FIXTURE_SPECS: ClassVar[list] = [
        {"metric": "m1", "op": "max_below", "spec": -15},
        {"metric": "m2", "op": "min_above", "spec": -0.5},
        {"metric": "m3", "op": "mean_within", "spec": [0.0, 2.0]},
    ]

    def test_hand_formula_bitwise(self):
        """手算真值独立写死：1.0 / 1.0 / 3.0，同式浮点逐位。"""
        from rfauto.core.wcd import cpk_from_metric_stats

        out = cpk_from_metric_stats(self.FIXTURE_STATS, self.FIXTURE_SPECS)
        per = out["per_spec"]
        # 与被测函数同式手算（单表达式，同 double 算术 → 逐位）
        assert per["m1"]["cpk"] == (-15.0 - (-18.0)) / (3.0 * 1.0)
        assert per["m2"]["cpk"] == ((-0.2) - (-0.5)) / (3.0 * 0.1)
        assert per["m3"]["cpk"] == min((2.0 - 0.9) / (3.0 * 0.1),
                                       (0.9 - 0.0) / (3.0 * 0.1))
        assert abs(per["m1"]["cpk"] - 1.0) <= 1e-12
        assert abs(per["m2"]["cpk"] - 1.0) <= 1e-12
        assert abs(per["m3"]["cpk"] - 3.0) <= 1e-12
        assert out["min"] == min(per["m1"]["cpk"], per["m2"]["cpk"],
                                 per["m3"]["cpk"])

    def test_cross_check_with_robustness_cpk(self):
        """跨实现对照：robustness_service._cpk_for_objectives 同数字同值。

        键名口径映射：robustness 用 ``f"{metric}#{i}"``，本实现用裸
        metric 名——同一 fixture 数字分别按两口径喂入后逐位比对。
        """
        from rfauto.core.objectives import Objective
        from rfauto.core.wcd import cpk_from_metric_stats
        from rfauto.service.robustness_service import _cpk_for_objectives

        objs = [
            Objective(metric="m1", op="max_below", value=-15),
            Objective(metric="m2", op="min_above", value=-0.5),
            Objective(metric="m3", op="mean_within", value=[0.0, 2.0]),
        ]
        robust_stats = {f"{o.metric}#{i}": self.FIXTURE_STATS[f"m{i + 1}"]
                        for i, o in enumerate(objs)}
        robust = _cpk_for_objectives(objs, robust_stats)
        mine = cpk_from_metric_stats(self.FIXTURE_STATS, self.FIXTURE_SPECS)
        for i, o in enumerate(objs):
            name = f"m{i + 1}"
            assert robust[f"{o.metric}#{i}"]["cpk"] is not None
            assert mine["per_spec"][name]["cpk"] == \
                robust[f"{o.metric}#{i}"]["cpk"]

    def test_zero_std_and_missing_metric_honest(self):
        from rfauto.core.wcd import cpk_from_metric_stats

        stats = {"m1": {"mean": 1.0, "std": 0.0}}
        out = cpk_from_metric_stats(stats, [{"metric": "m1", "op": "max_below",
                                             "spec": 2.0}])
        assert out["per_spec"]["m1"]["cpk"] is None
        assert "note" in out["per_spec"]["m1"]
        assert out["min"] is None

        out2 = cpk_from_metric_stats({}, self.FIXTURE_SPECS)
        assert all(v["cpk"] is None for v in out2["per_spec"].values())
        assert out2["min"] is None

    def test_duplicate_metric_keys_disambiguated(self):
        from rfauto.core.wcd import cpk_from_metric_stats

        stats = {"m1": {"mean": -18.0, "std": 1.0}}
        specs = [
            {"metric": "m1", "op": "max_below", "spec": -15},
            {"metric": "m1", "op": "max_below", "spec": -16.5},
        ]
        out = cpk_from_metric_stats(stats, specs)
        assert set(out["per_spec"]) == {"m1", "m1#1"}
        assert abs(out["per_spec"]["m1#1"]["cpk"] - 0.5) <= 1e-12


# ---------------------------------------------------------------------------
# wcd_specs 编排（binding_spec / per_spec 键名口径）
# ---------------------------------------------------------------------------


class TestWcdSpecs:
    def test_binding_spec_and_key_mapping(self):
        """binding=最短腿；per_spec 键 = DEFAULT_METRIC_KEY 映射（与
        ctx["specs"]/metric_stats 同口径），取值键走 candidates（与
        SpecEvaluator 同口径）——键名口径双轨如实分开断言。"""
        from rfauto.core.wcd import wcd_specs

        # 预测面：s11 = −20 + (ΔL)²（mm²），L σ=0.5 → 边界 ΔL=±√5mm →
        # WCD = √5/0.5 = 2√5 ≈ 4.472σ
        def predict(params: dict[str, float]) -> dict[str, float]:
            dl = params["L"] - 20.0
            return {"s11_db_max_in_band": -20.0 + dl * dl,
                    "gain_db_min_in_band": 9.0 - abs(dl)}

        objs = [
            {"metric": "s11_db", "op": "max_below", "value": -15},
            {"metric": "gain_db", "op": "min_above", "value": 8.0},
        ]
        center = {"L": 20.0}
        sigmas = {"L": 0.5}
        res = wcd_specs(center, sigmas, predict, objs, n_directions=16)
        assert res["ok"], res.get("errors")
        # s11_db 在 DEFAULT_METRIC_KEY 表内 → 映射；gain_db 不在表 → 裸名
        assert set(res["per_spec"]) == {"s11_db_max_in_band", "gain_db"}
        gain = res["per_spec"]["gain_db"]
        assert gain["resolved_key"] == "gain_db_min_in_band"
        # s11 腿：ΔL=±√5mm → 2√5 σ；gain 腿：|ΔL|=1mm → 2σ（binding）
        assert res["binding_spec"] == "gain_db"
        assert abs(res["overall"] - 2.0) <= 1e-6
        s11_entry = res["per_spec"]["s11_db_max_in_band"]
        assert abs(s11_entry["distance"] - 2.0 * math.sqrt(5.0)) <= 1e-6

    def test_objective_objects_and_mappings_same_result(self):
        from rfauto.core.objectives import Objective
        from rfauto.core.wcd import wcd_specs

        def predict(params: dict[str, float]) -> dict[str, float]:
            dl = params["L"] - 20.0
            return {"s11_db_max_in_band": -20.0 + dl * dl}

        objs_obj = [Objective(metric="s11_db", op="max_below", value=-15)]
        objs_map = [{"metric": "s11_db", "op": "max_below", "value": -15}]
        r1 = wcd_specs({"L": 20.0}, {"L": 0.5}, predict, objs_obj,
                       n_directions=16)
        r2 = wcd_specs({"L": 20.0}, {"L": 0.5}, predict, objs_map,
                       n_directions=16)
        assert r1["overall"] == r2["overall"]

    def test_missing_metric_honest_error(self):
        from rfauto.core.wcd import wcd_specs

        res = wcd_specs({"L": 20.0}, {"L": 0.5},
                        lambda p: {"other": 1.0},
                        [{"metric": "s11_db", "op": "max_below", "value": -15}])
        assert not res["ok"]
        entry = next(iter(res["per_spec"].values()))
        assert not entry["ok"] and "note" in entry

    def test_zero_sigma_rejected(self):
        from rfauto.core.wcd import wcd_specs

        res = wcd_specs({"L": 20.0}, {"L": 0.0}, lambda p: {}, [])
        assert not res["ok"]


# ---------------------------------------------------------------------------
# uq_service.wcd_design_center（合成数据集端到端）
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def samples_path(tmp_path):
    """合成数据集：s11 = −20 + 5(L−20)² + 10(w−0.35)²（二次可拟合）。

    容差盒中位初始中心 L=20.5 → s11 名义 −18.75，L 腿 WCD = 1σ；
    中心化把 L 推向 20 → L 腿 2σ → MC 良率与 min-Cpk 双升。
    """
    rng = np.random.default_rng(7)
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for _ in range(30):
        Lv = float(rng.uniform(*bounds["arm_len_mm"]))
        wv = float(rng.uniform(*bounds["series_w_mm"]))
        s11 = -20.0 + 5.0 * (Lv - 20.0) ** 2 + 10.0 * (wv - 0.35) ** 2
        samples.append({
            "params": {"arm_len_mm": Lv, "series_w_mm": wv},
            "metrics": {"s11_db_max_in_band": float(s11)},
        })
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


class TestWcdDesignCenter:
    def test_centering_improves_wcd_yield_cpk(self, samples_path):
        from rfauto.service.uq_service import wcd_design_center

        r = wcd_design_center(
            samples_path, {"arm_len_mm": 0.5, "series_w_mm": 0.02},
            n_mc=4000, seed=42)
        assert r["ok"], r.get("errors")
        # 交付形状（规格书 §18.1）
        assert {"center", "wcd", "cpk",
                "yield_mc_before", "yield_mc_after"} <= set(r)
        assert {"per_spec", "binding_spec", "overall"} <= set(r["wcd"])
        assert {"per_spec", "min"} <= set(r["cpk"])
        # WCD 上升（1σ → 2σ 方向）
        assert r["wcd"]["overall"] > r["wcd_initial"]["overall"] + 0.5
        # 双升：MC 良率与 min-Cpk 均不降（二次良态面应严格升）
        assert r["yield_mc_after"]["yield_rate"] > r["yield_mc_before"]["yield_rate"]
        assert r["cpk"]["min"] is not None
        assert r["cpk_initial"]["min"] is not None
        assert r["cpk"]["min"] > r["cpk_initial"]["min"]
        # 中心向顶点 arm_len=20 移动
        assert abs(r["center"]["arm_len_mm"] - 20.0) < abs(
            r["initial_center"]["arm_len_mm"] - 20.0)
        # JSON 安全（无 _draw_columns 内部列泄漏）
        assert "_draw_columns" not in r["yield_mc_after"]
        json.dumps({k: v for k, v in r.items() if k != "samples_path"})
        # binding 指向 L 腿（WCD 最短）
        assert r["wcd"]["binding_spec"] == "s11_db_max_in_band"

    def test_missing_metric_rejected(self, samples_path):
        from rfauto.service.uq_service import wcd_design_center

        data = json.loads(Path(samples_path).read_text(encoding="utf-8"))
        data["objectives"].append(
            {"metric": "nope_db", "band": [], "op": "max_below", "value": 1})
        bad = Path(samples_path).parent / "bad.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        r = wcd_design_center(bad, {"arm_len_mm": 0.5})
        assert not r["ok"]
        assert any("不在代理预测面" in e for e in r["errors"])

    def test_invalid_args_rejected(self, samples_path):
        from rfauto.service.uq_service import wcd_design_center

        assert not wcd_design_center(samples_path, {"arm_len_mm": 0.5},
                                     k_sigma=0)["ok"]
        assert not wcd_design_center(samples_path, {"arm_len_mm": 0.5},
                                     shrink=1.5)["ok"]
        assert not wcd_design_center(samples_path, {"nope": 0.5})["ok"]
