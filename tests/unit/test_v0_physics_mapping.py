"""v0 物理映射修复测试（docs/surrogate_calibration_design.md）。

背景：P0 真机 FAIL（rank_flip 5/6）实锤 fake 对调参变量几乎无响应——
wilkinson 公式里 series_w/shunt_w 缺失、S11 形状物理倒置、校准常数把
响应压扁。本文件验证修复后的三件事：
1. 角色接口（physics_roles）解析正确；
2. 代理接口契约（surrogate 注册表，第三方接入点）；
3. fake 对调参变量的物理响应性（方向 + 幅度）。
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
import pytest

from rfauto.adapters.fake_adapter import FakeAdapter
from rfauto.core.physics_roles import parse_length, resolve_role


def _band_s11_db(adapter: FakeAdapter, band: tuple[float, float]) -> float:
    """带内 S11 最大值（dB），与 objectives 的 band 口径一致。"""
    ntw = adapter.get_sparams()
    freq = ntw.f / 1e9
    s11_db = 20 * np.log10(np.abs(ntw.s[:, 0, 0]) + 1e-12)
    mask = (freq >= band[0]) & (freq <= band[1])
    return float(s11_db[mask].max())


def _dip_linear(adapter: FakeAdapter) -> tuple[float, float]:
    """S11 线幅值谷点：(谷深度, 谷频率 GHz)。谐振下陷处 |S11| 局部最小。"""
    ntw = adapter.get_sparams()
    freq = ntw.f / 1e9
    mag = np.abs(ntw.s[:, 0, 0])
    i = int(np.argmin(mag))
    return float(mag[i]), float(freq[i])


def _dip_db(adapter: FakeAdapter) -> float:
    """谷底深度（dB，负值）。"""
    mag, _ = _dip_linear(adapter)
    return 20 * math.log10(mag + 1e-12)


def _solved_adapter(model: str, variables: dict[str, float]) -> FakeAdapter:
    ad = FakeAdapter(model_type=model, n_ports=3, freq_ghz=(1.5, 3.5, 201))
    ad.connect({})
    ad.set_variables({k: f"{v}mm" for k, v in variables.items()})
    report = ad.solve("main_setup")
    assert report.success
    return ad


class TestPhysicsRoles:
    def test_parse_length_variants(self):
        assert parse_length("20.5mm") == 20.5
        assert parse_length("20.5") == 20.5
        assert parse_length(18) == 18.0
        assert parse_length("abc") is None
        assert parse_length(None) is None

    def test_resolve_role_candidates_and_fallback(self):
        variables = {"arm_len_mm": "20.5mm", "series_w": 0.4}
        assert resolve_role("resonator_length_mm", variables) == 20.5
        assert resolve_role("impedance_line_width_mm", variables) == 0.4
        assert resolve_role("feed_offset_mm", variables, default=10.0) == 10.0
        # _mm 省略兜底：变量 arm_len 匹配候选 arm_len_mm
        assert resolve_role("resonator_length_mm", {"arm_len": 19}) == 19.0

    def test_custom_candidates_override(self):
        assert resolve_role(
            "resonator_length_mm", {"res_len": 12.0},
            candidates=("res_len",)) == 12.0


class TestSurrogateRegistry:
    def test_register_create_roundtrip(self):
        from rfauto.optimization.surrogate import (
            SurrogateModel,
            surrogate_registry,
        )

        @surrogate_registry.register("dummy_v0_test")
        class Dummy(SurrogateModel):
            KIND = "dummy_v0_test"

            def fit(self, samples):
                return self._mark_fitted(len(samples))

            def predict(self, params):
                return {"s11_db": -10.0}

        model = surrogate_registry.create("dummy_v0_test", config={"a": 1})
        assert isinstance(model, SurrogateModel)
        assert model.config == {"a": 1}
        assert not model.fitted
        info = model.fit([{"params": {}, "metrics": {}}])
        assert info["n_samples"] == 1 and model.fitted
        assert model.predict({}) == {"s11_db": -10.0}
        assert model.uncertainty({}) is None  # 默认无不确定性估计

    def test_unknown_kind_rejected(self):
        from rfauto.optimization.surrogate import surrogate_registry

        with pytest.raises(KeyError, match="未注册的代理类型"):
            surrogate_registry.create("no_such_kind")

    def test_available_lists_kinds(self):
        from rfauto.optimization.surrogate import (
            SurrogateModel,
            surrogate_registry,
        )

        @surrogate_registry.register("avail_probe")
        class _P(SurrogateModel):
            KIND = "avail_probe"

            def fit(self, samples):
                return {}

            def predict(self, params):
                return {}

        assert "avail_probe" in surrogate_registry.available()


class TestWilkinsonPhysicsResponse:
    """P0 FAIL 的核心修复验证：fake 必须对调参变量有物理响应。"""

    NOMINAL: ClassVar[dict[str, float]] = {
        "arm_len_mm": 20.5, "series_w_mm": 0.33, "shunt_w_mm": 1.10}
    BAND = (2.3, 2.5)

    def test_line_width_drives_dip_depth(self):
        """线宽失配驱动谐振深度：过细线（远离 70.7Ω）谷底应显著恶化。

        模型最优 series_w≈0.45-0.6mm（MLine 70.7Ω），HFSS 真机最优 0.423
        ——绝对位置有 ~20% 模型偏差（留给 v1 校准吸收），但"过细→恶化"
        的方向与幅度是排序可信度的底线。旧版三者差异 <0.1dB。

        2026-09-23 fake 位置锚 3.54（乘法缩放 K=3.54/2.725）落
        配置后，名义点谷位在带下方（~1.98GHz，对齐 openEMS 名义肩部口径
        ——2026-09-04 决策注释记载的同一"谷在带下方肩部"现象），带内 S11
        的失配对比被肩部阻尼（thin/opt 带内仅 ~0.4dB），失配响应的主载体
        改在谷底深度通道断言（幅度门不变：实测对比 ~4dB）；带内保留方向
        断言（肩部阻尼后排序仍须保序）。runs/fake_anchor_354/criteria.md。
        """
        depth_thin = _dip_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "series_w_mm": 0.25}))
        depth_opt = _dip_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "series_w_mm": 0.45}))
        assert depth_thin > depth_opt + 1.5, (depth_opt, depth_thin)
        s11_thin = _band_s11_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "series_w_mm": 0.25}),
            self.BAND)
        s11_opt = _band_s11_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "series_w_mm": 0.45}),
            self.BAND)
        assert s11_thin > s11_opt, (s11_opt, s11_thin)

    def test_shunt_width_drives_dip_depth(self):
        """并臂线宽失配驱动谷底深度（带内被肩部阻尼，同
        test_line_width_drives_dip_depth 口径；实测谷底对比 ~2.4dB）。"""
        depth_nominal = _dip_db(_solved_adapter("wilkinson", self.NOMINAL))
        depth_off = _dip_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "shunt_w_mm": 0.85}))
        assert depth_off > depth_nominal + 0.5, (depth_nominal, depth_off)
        s11_nominal = _band_s11_db(
            _solved_adapter("wilkinson", self.NOMINAL), self.BAND)
        s11_off = _band_s11_db(
            _solved_adapter("wilkinson", {**self.NOMINAL, "shunt_w_mm": 0.85}),
            self.BAND)
        assert s11_off > s11_nominal, (s11_nominal, s11_off)

    def test_arm_length_moves_resonance(self):
        """arm_len 变长 → λ/4 谐振频率下移（S11 谷点左移）。"""
        _, f_short = _dip_linear(
            _solved_adapter("wilkinson", {**self.NOMINAL, "arm_len_mm": 18.0}))
        _, f_long = _dip_linear(
            _solved_adapter("wilkinson", {**self.NOMINAL, "arm_len_mm": 23.0}))
        assert f_long < f_short - 0.2, (f_short, f_long)

    def test_band_s11_in_physical_range(self):
        """名义点带内 S11 落在真机量级附近（HFSS 实测名义点 -12.93dB）。

        2026-09-23 位置锚落配置后带内值在肩部（~-8dB，谷在带下方）——
        窗口 (-25,-8) 的物理合理性上缘从此贴边，量级语义以谷位锚为准
        （openEMS 名义口径 2.2GHz，非 HFSS 带内 -12.93dB）。
        """
        s11 = _band_s11_db(
            _solved_adapter("wilkinson", self.NOMINAL), self.BAND)
        assert -25 < s11 < -8, s11


class TestPatchPhysicsResponse:
    def test_feed_offset_drives_matching(self):
        """馈电偏移决定匹配深度（旧版公式里 feed_offset 根本没用）。

        一阶模型下 x0≈L/4 附近 R_in≈Z0（最佳匹配）；越靠近辐射边失配越重。
        """
        dip_good, _ = _dip_linear(
            _solved_adapter(
                "patch", {"patch_len_mm": 40.0, "feed_offset_mm": 10.0,
                          "patch_w_mm": 30.0}))
        dip_bad, _ = _dip_linear(
            _solved_adapter(
                "patch", {"patch_len_mm": 40.0, "feed_offset_mm": 3.0,
                          "patch_w_mm": 30.0}))
        assert dip_good < dip_bad - 0.05, (dip_good, dip_bad)

    def test_patch_len_moves_resonance(self):
        _, f_long = _dip_linear(
            _solved_adapter(
                "patch", {"patch_len_mm": 45.0, "feed_offset_mm": 10.0,
                          "patch_w_mm": 30.0}))
        _, f_short = _dip_linear(
            _solved_adapter(
                "patch", {"patch_len_mm": 38.0, "feed_offset_mm": 10.0,
                          "patch_w_mm": 30.0}))
        assert f_long < f_short - 0.2, (f_short, f_long)

    def test_passivity_holds(self):
        ad = _solved_adapter(
            "patch", {"patch_len_mm": 40.0, "feed_offset_mm": 10.0,
                      "patch_w_mm": 30.0})
        s = ad.get_sparams().s
        assert np.max(np.abs(s)) <= 1.0 + 1e-9
        assert math.isfinite(float(np.max(np.abs(s))))
