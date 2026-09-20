"""开跑前 fake 成本非退化探针（health_service.fake_cost_degeneracy_probe）。

裁判=core/solve_health 的 #195 因子（公开入口 solve_health_check(costs=...)）
+ 逐参数单轴方差（fake 确定性下不消费的参数方差恰为 0）。全部零真机、
零网络：cost 由 FakeAdapter 闭式 + SpecEvaluator 确定性内核产出。

三用例：
① ratrace（fake 分支不消费任何变量）→ 合成常数 cost → FAIL / lesson #195；
② hairpin arm_len_mm 扫描（fake 走 λg/2 反演 arm_len→f0）→ PASS；
③ hairpin {gap_mm, tap_frac} 扫描 → PASS 且二者不入 insensitive_params。

**③ 期望已按接线翻转**（原钉死"未定标态"FAIL）：fake hairpin 已接通
gap→k（KJ 闭式）/ tap_frac→Q_e（抽头闭式 × c(τ)），二者进入 cost 通路
（test_hairpin_template.py
TestHairpinFakeDispatch 同述）。tap_frac 物理域为 (0,0.5)（0.5=电压节点，
core/coupled_microstrip 显式拒绝），探针 bounds 取域内区间。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """探针不落盘，但统一 chdir 隔离（#144 惯例）。"""
    monkeypatch.chdir(tmp_path)
    yield


HAIRPIN_OBJ = [{"metric": "s11_db_min", "band": [2.3, 2.7],
                "op": "max_below", "value": -40.0}]
# 与 HAIRPIN_NOMINAL 同源的固定参数（w_mm=50Ω HJ 线宽、order=3）；探针只读
HAIRPIN_FIXED = {"w_mm": 1.1134, "order": 3}


class TestSyntheticConstant:
    def test_ratrace_params_unconsumed_is_degenerate(self):
        """fake ratrace 分支不消费任何变量 → cost 恒常数 → #195 FAIL。"""
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        r = fake_cost_degeneracy_probe(
            "ratrace", {"dummy_len_mm": (10.0, 20.0)},
            [{"metric": "s11_db", "band": [2.3, 2.5],
              "op": "max_below", "value": -30.0}],
            n_points=8, seed=42)
        assert r["ok"], r.get("errors")
        assert r["degenerate"] is True
        assert r["verdict"] == "unhealthy"
        assert r["cost_factor"]["status"] == "FAIL"
        assert r["cost_factor"]["lesson_ref"] == "#195"
        assert r["lesson_ref"] == "#195"
        assert r["n_points"] == 8
        assert len(set(r["costs"])) == 1  # 逐点 cost 字节级相同
        assert r["insensitive_params"] == ["dummy_len_mm"]


class TestHairpinProbe:
    def test_arm_len_sweep_is_non_degenerate(self):
        """arm_len→f0 λg/2 反演真被消费：cost 有区分度 → PASS。"""
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        r = fake_cost_degeneracy_probe(
            "hairpin", {"arm_len_mm": (30.0, 40.0)}, HAIRPIN_OBJ,
            fixed_params=HAIRPIN_FIXED, n_points=8, seed=42)
        assert r["ok"], r.get("errors")
        assert r["degenerate"] is False
        assert r["verdict"] == "healthy"
        assert r["cost_factor"]["status"] == "PASS"
        assert r["insensitive_params"] == []
        assert r["param_sensitivity"]["arm_len_mm"]["variance"] > 0.0
        assert r["sampling"]["n_ports"] == 2  # TEMPLATE_META["hairpin"]
        assert r["sampling"]["f0_ghz"] == pytest.approx(2.5)

    def test_gap_tap_sweep_is_non_degenerate_after_wiring(self):
        """{gap_mm, tap_frac} 调参：接线后 fake 消费二者（gap→k、
        tap_frac→Q_e）→ cost 有区分度 → PASS，二者不入 insensitive_params
        （见模块 docstring；接线前此处钉死 FAIL）。tap_frac 上界取 0.45
        （物理域 (0,0.5)，0.5=电压节点 fake 显式拒绝）。"""
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        r = fake_cost_degeneracy_probe(
            "hairpin",
            {"gap_mm": (0.6, 1.8), "tap_frac": (0.2, 0.45)}, HAIRPIN_OBJ,
            fixed_params={**HAIRPIN_FIXED, "arm_len_mm": 35.4653},
            n_points=8, seed=42)
        assert r["ok"], r.get("errors")
        assert not r.get("errors")  # 全部采样点落在 fake 物理域内
        assert r["degenerate"] is False
        assert r["verdict"] == "healthy"
        assert r["cost_factor"]["status"] == "PASS"
        assert r["insensitive_params"] == []
        for name in ("gap_mm", "tap_frac"):
            assert r["param_sensitivity"][name]["variance"] > 0.0
            assert r["param_sensitivity"][name]["insensitive"] is False


class TestProbeInputGuards:
    def test_unknown_model_rejected(self):
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        r = fake_cost_degeneracy_probe(
            "no_such_model", {"x_mm": (0.0, 1.0)}, HAIRPIN_OBJ)
        assert not r["ok"]
        assert "TEMPLATE_META" in "\n".join(r["errors"])

    def test_too_few_points_rejected(self):
        # n_points < COST_DEGENERATE_MIN_TRIALS（5）→ 内核只会 UNKNOWN，探针拒绝
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        r = fake_cost_degeneracy_probe(
            "hairpin", {"arm_len_mm": (30.0, 40.0)}, HAIRPIN_OBJ,
            fixed_params=HAIRPIN_FIXED, n_points=4)
        assert not r["ok"]
        assert "n_points" in "\n".join(r["errors"])

    def test_bad_bounds_and_empty_objectives_rejected(self):
        from rfauto.service.health_service import fake_cost_degeneracy_probe

        assert not fake_cost_degeneracy_probe(
            "hairpin", {"arm_len_mm": (40.0, 30.0)}, HAIRPIN_OBJ)["ok"]
        assert not fake_cost_degeneracy_probe(
            "hairpin", {}, HAIRPIN_OBJ)["ok"]
        assert not fake_cost_degeneracy_probe(
            "hairpin", {"arm_len_mm": (30.0, 40.0)}, [])["ok"]
