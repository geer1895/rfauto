"""WP4.2 公差/良率收口测试：良率目标函数 + 设计中心化 + D9 温区良率。

覆盖（方案 §4 WP4.2，2026-09-14）：
- surrogate_yield_at：显式名义点良率求值（目标函数点值形式，确定性）；
- yield_design_center：容差盒网格良率目标函数 + 坐标 pattern search
  设计中心化（复用 core/pce 内核）+ 蒙特卡洛前后认证；
- temperature_zone_yield：D9 环境包络 → 温度 σ → 代理蒙特卡洛 + 温区
  角点确定性评估（D9 待接收口）；
- 两个新 service 契约（YieldDesignCenterPayload / TemperatureZoneYieldPayload）。

全部离线秒级（合成二次面样本集，零仿真零网络）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def _write_samples(tmp_path, name, bounds, objectives, samples):
    data = {"bounds": bounds, "objectives": objectives, "samples": samples}
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


@pytest.fixture
def samples_path(tmp_path):
    """双参数二次面：s11 = -20 + 5(L-20)² + 10(w-0.35)²，最优 (20, 0.35)。"""
    rng = np.random.default_rng(7)
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for _ in range(25):
        L = float(rng.uniform(*bounds["arm_len_mm"]))
        w = float(rng.uniform(*bounds["series_w_mm"]))
        s11 = -20.0 + 5.0 * (L - 20.0) ** 2 + 10.0 * (w - 0.35) ** 2
        samples.append({"params": {"arm_len_mm": L, "series_w_mm": w},
                        "metrics": {"s11_db_max_in_band": float(s11)}})
    samples[0] = {"params": {"arm_len_mm": 20.0, "series_w_mm": 0.35},
                  "metrics": {"s11_db_max_in_band": -20.0}}
    objectives = [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
                   "value": -15}]
    return _write_samples(tmp_path, "samples.json", bounds, objectives, samples)


@pytest.fixture
def env_samples_path(tmp_path):
    """温度轴校准集（D8 口径）：s11 = -20 + 1e-3·(t-25)²，温区 [-40, 125] °C。"""
    bounds = {"t_c": [-40.0, 125.0]}
    samples = []
    for t in np.linspace(-40.0, 125.0, 26):
        samples.append({"params": {"t_c": float(t)},
                        "metrics": {"s11_db_max_in_band":
                                    -20.0 + 1e-3 * (float(t) - 25.0) ** 2}})
    samples[5] = {"params": {"t_c": 25.0},
                  "metrics": {"s11_db_max_in_band": -20.0}}
    objectives = [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
                   "value": -15.0}]
    return _write_samples(tmp_path, "env_samples.json", bounds, objectives,
                          samples)


class TestSurrogateYieldAt:
    """显式名义点良率（良率目标函数点值形式）。"""

    def test_yield_at_explicit_nominal(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield_at

        # ridge_lambda=1e-6 近无正则：二次面精确复现（#175 收缩偏差规避）
        kw = {"n": 2000, "seed": 1, "ridge_lambda": 1e-6}
        opt = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        off = {"arm_len_mm": 21.5, "series_w_mm": 0.35}
        tol = {"arm_len_mm": 0.1, "series_w_mm": 0.02}
        r_opt = surrogate_yield_at(samples_path, tol, opt, **kw)
        r_off = surrogate_yield_at(samples_path, tol, off, **kw)
        assert r_opt["ok"], r_opt.get("errors")
        assert r_opt["nominal_params"] == opt          # 名义点逐字保留
        assert r_opt["yield_rate"] > 0.95              # 最优点余量大
        assert r_off["yield_rate"] < r_opt["yield_rate"]  # 偏移点良率下降
        assert r_opt["metric_stats"]["s11_db_max_in_band"]["std"] > 0

    def test_deterministic_same_seed(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield_at

        nom = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        tol = {"arm_len_mm": 0.1}
        r1 = surrogate_yield_at(samples_path, tol, nom, n=500, seed=3)
        r2 = surrogate_yield_at(samples_path, tol, nom, n=500, seed=3)
        assert json.dumps(r1) == json.dumps(r2)        # 同输入逐字节一致

    def test_input_validation(self, samples_path):
        from rfauto.service.uq_service import surrogate_yield_at

        nom = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
        r = surrogate_yield_at(samples_path, {"nope": 0.1}, nom)
        assert not r["ok"]                             # 公差不在搜索空间
        r = surrogate_yield_at(samples_path, {"series_w_mm": 0.02},
                               {"arm_len_mm": 20.0})
        assert not r["ok"] and "缺少公差参数" in r["errors"][0]
        r = surrogate_yield_at(samples_path, {"arm_len_mm": 0.1},
                               {"arm_len_mm": 20.0, "ghost": 1.0})
        assert not r["ok"] and "不在搜索空间" in r["errors"][0]
        r = surrogate_yield_at(samples_path, {"arm_len_mm": 0.1}, nom, n=0)
        assert not r["ok"]


class TestYieldDesignCenter:
    """良率目标函数 + 设计中心化。"""

    def test_centering_raises_yield(self, samples_path):
        """箱中心 (20.5, 0.35) 的 ±3σ 角点违约 → 中心化应迁向真最优点 20。"""
        from rfauto.service.uq_service import yield_design_center

        # ridge_lambda=1e-6 近无正则：二次面精确复现，网格良率可手工对账
        r = yield_design_center(samples_path,
                                {"arm_len_mm": 0.3, "series_w_mm": 0.02},
                                k_sigma=3.0, n_levels=3, max_iter=40,
                                n_mc=2000, seed=11, ridge_lambda=1e-6)
        assert r["ok"], r.get("errors")
        assert r["initial_yield_rate"] == pytest.approx(2.0 / 3.0)
        assert r["yield_rate"] == pytest.approx(1.0)   # 中心化后全网格通过
        assert 19.9 <= r["center"]["arm_len_mm"] <= 20.1
        assert r["final_yield_mc"] >= r["initial_yield_mc"]  # MC 认证同向
        assert r["objective"] == "tolerance_box_grid_cost_violation(spec_max=0)"
        assert r["box_half_widths"]["arm_len_mm"] == pytest.approx(0.9)
        assert r["box_half_widths"]["series_w_mm"] == pytest.approx(0.06)

    def test_deterministic_same_seed(self, samples_path):
        from rfauto.service.uq_service import yield_design_center

        tol = {"arm_len_mm": 0.3, "series_w_mm": 0.02}
        r1 = yield_design_center(samples_path, tol, n_mc=500, seed=5)
        r2 = yield_design_center(samples_path, tol, n_mc=500, seed=5)
        assert r1["ok"] and json.dumps(r1) == json.dumps(r2)

    def test_input_validation(self, samples_path):
        from rfauto.service.uq_service import yield_design_center

        r = yield_design_center(samples_path, {"nope": 0.1})
        assert not r["ok"]                             # 公差不在搜索空间
        r = yield_design_center(samples_path, {"arm_len_mm": 0.1}, k_sigma=0)
        assert not r["ok"]
        r = yield_design_center(samples_path, {"arm_len_mm": 0.1}, n_levels=1)
        assert not r["ok"]

    def test_contract_validates(self, samples_path):
        from rfauto.service.contracts import YieldDesignCenterPayload
        from rfauto.service.uq_service import yield_design_center

        r = yield_design_center(samples_path,
                                {"arm_len_mm": 0.3, "series_w_mm": 0.02},
                                n_mc=500, seed=5)
        ok, errors, model = YieldDesignCenterPayload.validate(r)
        assert ok, errors
        assert 0.0 <= model.yield_rate <= 1.0
        assert model.k_sigma == pytest.approx(3.0)


class TestTemperatureZoneYield:
    """D9 环境包络 → 温区良率（待接收口）。"""

    def test_env_sigma_drives_mc_and_corners(self, env_samples_path):
        from rfauto.core.bands import get_env
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade1",
                                   n=3000, seed=5, ridge_lambda=1e-6)
        assert r["ok"], r.get("errors")
        axis = r["axis"]
        assert axis["nominal_c"] == pytest.approx(25.0)
        assert r["sigma_c"] == pytest.approx(100.0 / 3.0)  # 半宽100/3σ
        assert r["delta_t"]["delta_t_min_c"] == pytest.approx(-65.0)
        assert r["delta_t"]["delta_t_max_c"] == pytest.approx(100.0)
        assert 0.0 < r["yield_rate"] < 1.0
        assert r["metric_stats"]["s11_db_max_in_band"]["std"] > 0
        # 温区角点（确定性锚点）：冷端 -15.78 dB 通过，热端 -10 dB 违约
        assert r["corner_pass"] == {"t_min_c": True, "t_max_c": False}
        assert r["corners"]["t_min_c"]["metrics"][
            "s11_db_max_in_band"] == pytest.approx(-15.775, abs=1e-3)
        assert r["corners"]["t_max_c"]["metrics"][
            "s11_db_max_in_band"] == pytest.approx(-10.0, abs=1e-3)
        assert r["env"]["key"] == "aec_q100_grade1"
        assert r["env"] == get_env("aec_q100_grade1").to_dict()
        # 同种子确定性
        r2 = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade1",
                                    n=3000, seed=5, ridge_lambda=1e-6)
        assert json.dumps(r) == json.dumps(r2)

    def test_wider_zone_lower_yield(self, env_samples_path):
        """更宽包络（Grade 0，σ=125/3）→ 温漂违约更多 → 良率不升。"""
        from rfauto.service.uq_service import temperature_zone_yield

        kw = {"n": 3000, "seed": 5, "ridge_lambda": 1e-6}
        r1 = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade1",
                                    **kw)
        r0 = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade0",
                                    **kw)
        assert r0["ok"] and r0["sigma_c"] > r1["sigma_c"]
        assert r0["yield_rate"] < r1["yield_rate"]

    def test_env_sigma_overrides_user_t_c(self, env_samples_path):
        """温度 σ 以包络为准：调用方传 t_c 公差被覆盖。"""
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(env_samples_path, {"t_c": 1.0},
                                   "aec_q100_grade1", n=500, seed=5,
                                   ridge_lambda=1e-6)
        assert r["ok"]
        assert r["tolerances"]["t_c"] == pytest.approx(100.0 / 3.0)

    def test_t_ref_override(self, env_samples_path):
        """t_ref_c 覆盖：名义温度与 σ 跟随参考温度重算。"""
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade1",
                                   t_ref_c=125.0, n=500, seed=5,
                                   ridge_lambda=1e-6)
        assert r["ok"]
        assert r["axis"]["nominal_c"] == pytest.approx(125.0)
        assert r["sigma_c"] == pytest.approx(165.0 / 3.0)  # |−40−125|=165

    def test_requires_t_dimension(self, samples_path):
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(samples_path, {}, "aec_q100_grade1")
        assert not r["ok"]
        assert any("t_c" in e for e in r["errors"])

    def test_unknown_env_key(self, env_samples_path):
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(env_samples_path, {}, "no_such_env")
        assert not r["ok"]
        assert any("no_such_env" in e for e in r["errors"])

    def test_contract_validates(self, env_samples_path):
        from rfauto.service.contracts import TemperatureZoneYieldPayload
        from rfauto.service.uq_service import temperature_zone_yield

        r = temperature_zone_yield(env_samples_path, {}, "aec_q100_grade1",
                                   n=1000, seed=5, ridge_lambda=1e-6)
        ok, errors, model = TemperatureZoneYieldPayload.validate(r)
        assert ok, errors
        assert model.env_key == "aec_q100_grade1"
        assert 0.0 <= model.yield_rate <= 1.0
        assert model.corner_pass == {"t_min_c": True, "t_max_c": False}
