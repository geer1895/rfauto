"""LC-9 钢网开孔闭式面测试（席D3）。

裁判纪律（#118/#300：≥2 独立基准，禁自我推导自证）：

- 跨形状恒等互证：square=rect 的 L=W 特例（两公式独立实现，代数
  相消后必相等）；circle 两路径（D/(4T) 恒等 vs π 面积直算）；
- 文献数值锚：0402（0.5×0.6 mm 开孔@0.12 mm 钢片 AR≈1.136 手算）
  与 AR 下限恰临界的圆孔（D=4·0.66·T）；
- 回收钉：max_foil_thickness 反解厚度回代正向必复现判据阈值
  （合成已知量→回收，#118 家族标准动作）；
- 单调性：AR 随 T 单调降/随特征宽单调升。
"""

from __future__ import annotations

import math

import pytest

from rfauto.service.layout_stencil_service import (
    AR_MIN_IPC7525,
    ASPECT_MIN_IPC7525,
    aperture_area_ratio,
    evaluate_apertures,
    max_foil_thickness,
)


class TestAreaRatio:
    def test_rect_formula_source_anchor(self):
        # PCBCart/7PCB 公式直代：0.5×0.6@0.12 → 0.30/0.264
        ar = aperture_area_ratio("rect", 0.12, length_mm=0.6, width_mm=0.5)
        assert ar == pytest.approx(0.6 * 0.5 / (2 * 1.1 * 0.12))
        assert ar == pytest.approx(25.0 / 22.0, rel=1e-9)

    def test_square_rect_cross_identity(self):
        # 独立基准：square 公式 ≡ rect 公式取 L=W（两实现互证）
        for a, t in ((0.4, 0.1), (0.6, 0.15), (1.0, 0.08)):
            ar_rect = aperture_area_ratio(
                "rect", t, length_mm=a, width_mm=a)
            ar_square = aperture_area_ratio("square", t, length_mm=a)
            assert ar_square == pytest.approx(ar_rect, rel=1e-12)
            assert ar_square == pytest.approx(a / (4.0 * t))

    def test_circle_two_paths(self):
        # 独立基准：D/(4T) vs π 定义式直算
        for d, t in ((0.2, 0.1), (0.264, 0.1), (0.5, 0.12)):
            ar_fast = aperture_area_ratio("circle", t, diameter_mm=d)
            ar_def = (math.pi * d**2 / 4.0) / (math.pi * d * t)
            assert ar_fast == pytest.approx(ar_def, rel=1e-12)

    def test_area_ratio_threshold_critical_circle(self):
        # 文献锚：AR=0.66 临界圆孔 D=4·0.66·T（0.1 mm 钢片 → 0.264 mm）
        d_crit = 4.0 * AR_MIN_IPC7525 * 0.1
        assert aperture_area_ratio(
            "circle", 0.1, diameter_mm=d_crit) == pytest.approx(0.66)
        # 临界下方如实 FAIL
        assert aperture_area_ratio(
            "circle", 0.1, diameter_mm=0.9 * d_crit) < 0.66

    def test_monotonicity(self):
        # AR 随 T 单调降、随特征宽单调升（方向性守卫）
        ars_t = [aperture_area_ratio("circle", t, diameter_mm=0.3)
                 for t in (0.08, 0.1, 0.12, 0.15)]
        assert ars_t == sorted(ars_t, reverse=True)
        ars_w = [aperture_area_ratio("rect", 0.12, length_mm=0.6,
                                     width_mm=w) for w in (0.3, 0.4, 0.5)]
        assert ars_w == sorted(ars_w)

    def test_invalid_args(self):
        with pytest.raises(ValueError, match="shape"):
            aperture_area_ratio("oval", 0.1, diameter_mm=0.3)
        with pytest.raises(ValueError, match="正"):
            aperture_area_ratio("rect", 0.0, length_mm=0.6, width_mm=0.5)
        with pytest.raises(ValueError, match="正"):
            aperture_area_ratio("circle", 0.1, diameter_mm=-0.3)


class TestMaxFoilThickness:
    def test_recovery_area_ratio_governed(self):
        # 回收钉：反解 t_max 回代正向必复现 ar_min（圆孔面积主导）
        r = max_foil_thickness("circle", diameter_mm=0.4)
        assert r["governing"] == "area_ratio"
        t = r["t_max_mm"]
        assert aperture_area_ratio(
            "circle", t, diameter_mm=0.4) == pytest.approx(
            AR_MIN_IPC7525, rel=1e-12)

    def test_recovery_aspect_governed(self):
        # 回收钉：宽厚比主导情形（细长条 rect 5×0.2：t_aspect=0.1333 <
        # t_area=1.0/6.864=0.1457）aspect 回代复现 1.5
        r = max_foil_thickness("rect", length_mm=5.0, width_mm=0.2)
        assert r["governing"] == "aspect_ratio"
        t = r["t_aspect_mm"]
        assert 0.2 / t == pytest.approx(ASPECT_MIN_IPC7525)
        # t_max=两约束取交
        assert r["t_max_mm"] == pytest.approx(min(r["t_area_ratio_mm"],
                                                  r["t_aspect_mm"]))

    def test_rect_area_governed_recovery(self):
        # rect 面积主导：反解闭式 L·W/(2(L+W)·ar) 手算对照+回代
        r = max_foil_thickness("rect", length_mm=0.6, width_mm=0.5)
        t_expect = 0.6 * 0.5 / (2 * 1.1 * AR_MIN_IPC7525)
        assert r["t_area_ratio_mm"] == pytest.approx(t_expect)
        assert aperture_area_ratio(
            "rect", r["t_max_mm"], length_mm=0.6,
            width_mm=0.5) == pytest.approx(AR_MIN_IPC7525, rel=1e-12)


class TestEvaluateApertures:
    def test_batch_mixed_verdicts(self):
        # 0402@0.12 钢片手算 PASS；0.15 mm 圆点@0.15 钢片 AR=0.25 FAIL
        r = evaluate_apertures([
            {"name": "r0402_1", "shape": "rect", "length_mm": 0.6,
             "width_mm": 0.5},
            {"name": "via_dot", "shape": "circle", "diameter_mm": 0.15},
        ], 0.12)
        assert r["ok"] is True
        assert r["n_total"] == 2 and r["n_pass"] == 1 and r["n_fail"] == 1
        assert r["all_pass"] is False
        by_name = {x["name"]: x for x in r["results"]}
        assert by_name["r0402_1"]["verdict"] == "PASS"
        assert by_name["via_dot"]["verdict"] == "FAIL"
        assert by_name["via_dot"]["area_ratio"] == pytest.approx(0.3125)
        # 判据来源随行（IPC-7525 口径）
        assert r["criteria"]["ar_min"] == pytest.approx(0.66)
        assert r["criteria"]["aspect_min"] == pytest.approx(1.5)

    def test_all_pass_envelope(self):
        r = evaluate_apertures([
            {"shape": "rect", "length_mm": 0.8, "width_mm": 0.6},
            {"shape": "square", "length_mm": 0.5},
        ], 0.1)
        assert r["ok"] is True and r["all_pass"] is True

    def test_relaxed_criteria_explicit(self):
        # nano-coating 放宽：显式传参生效（缺省门不被静默放宽）
        r_strict = evaluate_apertures(
            [{"shape": "circle", "diameter_mm": 0.2}], 0.2)
        r_relaxed = evaluate_apertures(
            [{"shape": "circle", "diameter_mm": 0.2}], 0.2, ar_min=0.2,
            aspect_min=1.0)
        assert r_strict["all_pass"] is False
        assert r_relaxed["all_pass"] is True

    def test_invalid_aperture_reported(self):
        r = evaluate_apertures([
            {"name": "bad", "shape": "rect", "length_mm": 0.6},
            {"name": "good", "shape": "circle", "diameter_mm": 0.4},
        ], 0.12)
        assert r["ok"] is True
        by_name = {x["name"]: x for x in r["results"]}
        assert by_name["bad"]["verdict"] == "INVALID"
        assert by_name["good"]["verdict"] == "PASS"

    def test_error_envelope_empty_and_bad_thickness(self):
        assert evaluate_apertures([], 0.12)["ok"] is False
        assert evaluate_apertures(
            [{"shape": "circle", "diameter_mm": 0.4}], 0.0)["ok"] is False

    def test_aspect_ratio_recorded(self):
        # 宽厚比随行：rect 取短边
        r = evaluate_apertures([
            {"shape": "rect", "length_mm": 1.0, "width_mm": 0.3},
        ], 0.1)
        assert r["results"][0]["aspect_ratio"] == pytest.approx(3.0)
