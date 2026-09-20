"""E6a 微带综合引擎单元测试。

验收标准：
① 反解→正向回算 |ΔZ0|<0.5Ω
② 响应性：Z0 单调降 → W 单调升
③ 对拍矩阵：常规+极端 W/h + 多频点，常规 <3% 极端 <5%
④ 超限标 needs_calibration 而非静默通过
"""

from __future__ import annotations

import pytest

from rfauto.core.synthesis import (
    Stackup,
    SynthesisResult,
    forward_z0,
    inverse_width,
    synthesize_batch,
    synthesize_mline,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def rogers4350b() -> Stackup:
    return Stackup(
        name="rogers4350b_h0.508",
        epsilon_r=3.66,
        thickness_mm=0.508,
        loss_tangent=0.0037,
    )


# ─── 正向计算 ──────────────────────────────────────────────────────────────────

class TestForwardZ0:
    """正向计算：宽度 → 阻抗。"""

    def test_50ohm_width_gives_approx_50ohm(self, rogers4350b):
        """G0 定案值 1.11mm 应给出接近 50Ω。"""
        z0, _er_eff = forward_z0(1.11, 2.4, rogers4350b)
        assert 48.0 < z0 < 53.0, f"1.11mm -> {z0:.2f}Ω"

    def test_35ohm_width_gives_approx_35ohm(self, rogers4350b):
        """G0 定案值 1.87mm 应给出接近 35Ω。"""
        z0, _er_eff = forward_z0(1.87, 2.4, rogers4350b)
        assert 33.0 < z0 < 38.0, f"1.87mm -> {z0:.2f}Ω"

    def test_wider_line_lower_z0(self, rogers4350b):
        """更宽的线 → 更低的阻抗。"""
        z0_narrow, _ = forward_z0(0.5, 2.4, rogers4350b)
        z0_wide, _ = forward_z0(3.0, 2.4, rogers4350b)
        assert z0_narrow > z0_wide


# ─── 反解计算 ──────────────────────────────────────────────────────────────────

class TestInverseWidth:
    """反解计算：阻抗 → 宽度。"""

    def test_50ohm_inverse(self, rogers4350b):
        """50Ω 反解应接近 G0 定案值 1.11mm。"""
        w, _, status = inverse_width(50.0, 2.4, rogers4350b)
        assert status == "ok"
        assert 1.05 < w < 1.20, f"50Ω -> {w:.4f}mm"

    def test_35ohm_inverse(self, rogers4350b):
        """35.35Ω 反解应接近 G0 定案值 1.87mm。"""
        w, _, status = inverse_width(35.35, 2.4, rogers4350b)
        assert status == "ok"
        assert 1.80 < w < 1.95, f"35.35Ω -> {w:.4f}mm"

    def test_self_consistency(self, rogers4350b):
        """① 反解→正向回算 |ΔZ0|<0.5Ω。"""
        for z0_target in [20.0, 35.35, 50.0, 75.0, 100.0]:
            w, z0_actual, status = inverse_width(z0_target, 2.4, rogers4350b)
            assert status == "ok", f"Z0={z0_target}: status={status}"
            assert abs(z0_actual - z0_target) < 0.5, (
                f"Z0={z0_target}: w={w:.4f}mm, z0_actual={z0_actual:.2f}Ω, "
                f"delta={abs(z0_actual - z0_target):.4f}Ω"
            )


# ─── 响应性 ────────────────────────────────────────────────────────────────────

class TestResponsiveness:
    """② 响应性：Z0 单调降 → W 单调升。"""

    def test_z0_decreasing_w_increasing(self, rogers4350b):
        """阻抗降低时，线宽应单调增加。"""
        z0_targets = [100.0, 75.0, 50.0, 35.35, 25.0, 20.0]
        widths = []
        for z0 in z0_targets:
            w, _z0, _st = inverse_width(z0, 2.4, rogers4350b)
            widths.append(w)

        # 验证单调性：每个后续宽度应 >= 前一个
        for i in range(1, len(widths)):
            assert widths[i] >= widths[i - 1], (
                f"Z0 {z0_targets[i-1]}->{z0_targets[i]}: "
                f"W {widths[i-1]:.4f}->{widths[i]:.4f} (not monotonic)"
            )


# ─── 对拍矩阵 ──────────────────────────────────────────────────────────────────

class TestSynthesisMatrix:
    """③ 对拍矩阵：常规+极端 W/h + 多频点。"""

    @pytest.mark.parametrize("z0_target", [35.35, 50.0])
    @pytest.mark.parametrize("freq_ghz", [2.4, 5.8, 10.0])
    def test_common_impedances(self, z0_target, freq_ghz):
        """常规阻抗 + 多频点：偏差 <3%。"""
        stackup = Stackup(name="test", epsilon_r=3.66, thickness_mm=0.508)
        w, z0_actual, status = inverse_width(z0_target, freq_ghz, stackup)
        assert status == "ok"
        dev_pct = abs(z0_actual - z0_target) / z0_target * 100
        assert dev_pct < 3.0, (
            f"Z0={z0_target}@{freq_ghz}GHz: w={w:.4f}, z0={z0_actual:.2f}, dev={dev_pct:.2f}%"
        )

    @pytest.mark.parametrize("z0_target", [20.0, 120.0])
    def test_extreme_impedances(self, z0_target):
        """极端阻抗：偏差 <5%，超限标 needs_calibration。"""
        stackup = Stackup(name="test", epsilon_r=3.66, thickness_mm=0.508)
        _, z0_actual, status = inverse_width(z0_target, 2.4, stackup)
        dev_pct = abs(z0_actual - z0_target) / z0_target * 100
        if dev_pct < 5.0:
            assert status == "ok"
        else:
            assert status == "needs_calibration"


# ─── synthesize_mline 入口 ─────────────────────────────────────────────────────

class TestSynthesizeMline:
    """综合入口测试。"""

    def test_basic_synthesis(self):
        """基本综合流程。"""
        result = synthesize_mline(50.0, 2.4, "rogers4350b_h0.508")
        assert isinstance(result, SynthesisResult)
        assert result.status == "ok"
        assert 1.05 < result.width_mm < 1.20

    def test_to_dict(self):
        """结果序列化。"""
        result = synthesize_mline(50.0, 2.4)
        d = result.to_dict()
        assert "z0_target" in d
        assert "width_mm" in d
        assert "status" in d

    def test_synthesize_batch(self):
        """批量综合。"""
        targets = [
            (50.0, 2.4, "rogers4350b_h0.508"),
            (35.35, 2.4, "rogers4350b_h0.508"),
            (50.0, 5.8, "rogers4350b_h0.508"),
        ]
        results = synthesize_batch(targets)
        assert len(results) == 3
        for r in results:
            assert r.status == "ok"


# ─── Stackup 加载 ──────────────────────────────────────────────────────────────

class TestStackup:
    """层叠加载测试。"""

    def test_from_materials_yaml(self):
        """从 materials.yaml 加载。"""
        s = Stackup.from_materials_yaml("rogers4350b_h0.508")
        assert s.epsilon_r == 3.66
        assert s.thickness_mm == 0.508

    def test_unknown_stackup_raises(self):
        """未知层叠应抛 KeyError。"""
        with pytest.raises(KeyError):
            Stackup.from_materials_yaml("nonexistent_stackup")
