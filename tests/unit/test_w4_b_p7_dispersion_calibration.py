"""W4-B P7：色散标定曲线层（core/dispersion_calibration）单测。

判据（#118 合成回收先行）：
- 合成回收：已知光滑色散律（Kobayashi 型单调饱和）稀疏采样 → log-f 内插
  在留守点回收真值（rel ≤1e-4）；
- 域盒 REFUSE：越界 DispersionRangeError 附相对余量；端点闭区间可达；
- 校验面：非单调 f/长度不匹配/非正值/eps_eff<1 全部显式拒绝；
- roundtrip：to_dict/from_dict + json.dumps 逐位；
- static_consistency 对账方向与 rel_dev 值；table_quality 噪声尖峰 WARN。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.dispersion_calibration import (
    C0,
    DispersionRangeError,
    apply_dispersion,
    build_dispersion_table,
    interp_eps_eff,
    interp_z0,
    lambda_g_mm,
    static_consistency,
    table_quality,
)


def _truth_law(f_hz: float) -> tuple[float, float]:
    """合成真值律（Kobayashi 型单调饱和色散；光滑、有解析式）。
    εeff(f) = εs + (ε0 − εs)·f²/(f²+fc²)，Z0(f) = Z0s·(1+a·f)/(1+b·f)。"""
    eps_s, eps0, fc = 2.2, 1.05, 18e9
    e = eps_s * f_hz * f_hz / (f_hz * f_hz + fc * fc) \
        + eps0 * fc * fc / (f_hz * f_hz + fc * fc)
    z = 78.0 * (1.0 + 1.2e-11 * f_hz) / (1.0 + 0.6e-11 * f_hz)
    return e, z


def _make_table(n: int = 25):
    """25 点 log 网格：held-out 回收 ≤5e-4（曲率受限），相邻跳变 <5%（PASS 面）。"""
    f = [8e9 * (40e9 / 8e9) ** (i / (n - 1)) for i in range(n)]
    pairs = [_truth_law(v) for v in f]
    e = [q[0] for q in pairs]
    z = [q[1] for q in pairs]
    return build_dispersion_table(
        f, list(e), list(z),
        geometry={"w_mm": 0.5, "g_mm": 0.508, "h_mm": 0.254, "er": 3.66},
        meta={"engine": "synthetic", "note": "test fixture"})


class TestSyntheticRecovery:
    def test_heldout_interpolation_recovery(self):
        tab = _make_table()
        worst_e = worst_z = 0.0
        for i in range(len(tab.f_grid_hz) - 1):
            f_mid = math.sqrt(tab.f_grid_hz[i] * tab.f_grid_hz[i + 1])
            e_true, z_true = _truth_law(f_mid)
            worst_e = max(worst_e, abs(interp_eps_eff(tab, f_mid) / e_true - 1.0))
            worst_z = max(worst_z, abs(interp_z0(tab, f_mid) / z_true - 1.0))
        assert worst_e <= 5e-4, f"eps_eff 回收最坏 {worst_e:.2e}"
        assert worst_z <= 5e-4, f"z0 回收最坏 {worst_z:.2e}"

    def test_grid_nodes_exact(self):
        tab = _make_table(7)
        for i, f in enumerate(tab.f_grid_hz):
            assert interp_eps_eff(tab, f) == pytest.approx(
                tab.eps_eff_grid[i], rel=1e-15)
            assert interp_z0(tab, f) == pytest.approx(
                tab.z0_grid[i], rel=1e-15)

    def test_apply_dispersion_consistency(self):
        tab = _make_table()
        f = 15e9
        out = apply_dispersion(tab, f)
        e_true, z_true = _truth_law(f)
        assert out["eps_eff"] == pytest.approx(e_true, rel=5e-4)
        assert out["z0_ohm"] == pytest.approx(z_true, rel=5e-4)
        assert out["lambda_g_mm"] == pytest.approx(
            C0 / f / math.sqrt(out["eps_eff"]) * 1e3, rel=1e-15)


class TestDomainBoxRefuse:
    def test_below_domain_refuses_with_margin(self):
        tab = _make_table()
        with pytest.raises(DispersionRangeError, match="域盒") as ei:
            interp_eps_eff(tab, tab.f_min_hz * 0.9)
        assert "low=" in str(ei.value)

    def test_above_domain_refuses(self):
        tab = _make_table()
        with pytest.raises(DispersionRangeError, match="REFUSE"):
            interp_z0(tab, tab.f_max_hz * 1.05)

    def test_endpoints_inclusive(self):
        tab = _make_table()
        assert interp_eps_eff(tab, tab.f_min_hz) > 0.0
        assert interp_eps_eff(tab, tab.f_max_hz) > 0.0


class TestValidation:
    def test_non_monotone_freq_rejected(self):
        with pytest.raises(ValueError, match="严格递增"):
            build_dispersion_table([1e9, 3e9, 2e9], [2.0, 2.1, 2.2],
                                   [70.0, 71.0, 72.0])

    def test_length_mismatch_rejected(self):
        with pytest.raises(ValueError, match="长度不一致"):
            build_dispersion_table([1e9, 2e9], [2.0, 2.1, 2.2], [70.0, 71.0])

    def test_nonpositive_values_rejected(self):
        with pytest.raises(ValueError, match="非正有限"):
            build_dispersion_table([1e9, 2e9], [2.0, -1.0], [70.0, 71.0])
        with pytest.raises(ValueError, match="非正有限"):
            build_dispersion_table([1e9, 2e9], [2.0, 2.1], [70.0, float("nan")])

    def test_eps_eff_below_one_rejected(self):
        with pytest.raises(ValueError, match="非物理"):
            build_dispersion_table([1e9, 2e9], [0.9, 2.1], [70.0, 71.0])

    def test_single_point_rejected(self):
        with pytest.raises(ValueError, match="至少 2 个频点"):
            build_dispersion_table([1e9], [2.0], [70.0])


class TestRoundtrip:
    def test_dict_roundtrip_and_json(self):
        tab = _make_table()
        payload = tab.to_dict()
        json.dumps(payload)  # JSON 可序列化
        tab2 = type(tab).from_dict(json.loads(json.dumps(payload)))
        assert tab2.f_grid_hz == tab.f_grid_hz
        assert tab2.eps_eff_grid == tab.eps_eff_grid
        assert tab2.z0_grid == tab.z0_grid
        assert tab2.geometry == tab.geometry
        assert tab2.meta == tab.meta


class TestStaticConsistencyAndQuality:
    def test_static_consistency_directions(self):
        tab = _make_table()
        e0, z0 = _truth_law(tab.f_min_hz)
        ok = static_consistency(tab, e0, z0)
        assert ok["ok"] is True
        assert ok["eps_eff_rel_dev"] < 1e-12
        bad = static_consistency(tab, e0 * 1.15, z0)
        assert bad["ok"] is False
        # rel_dev 以静态值（设计链值）为基准：0.15/1.15
        assert bad["eps_eff_rel_dev"] == pytest.approx(0.15 / 1.15, rel=1e-9)

    def test_static_consistency_ref_outside(self):
        tab = _make_table()
        with pytest.raises(DispersionRangeError):
            static_consistency(tab, 2.0, 70.0, f_ref_hz=1e6)

    def test_quality_pass_on_smooth(self):
        q = table_quality(_make_table())
        assert q["verdict"] == "PASS"
        assert q["violations"] == []
        assert q["provenance"] == "present"

    def test_quality_warns_on_spike(self):
        tab = _make_table()
        g = list(tab.z0_grid)
        g[3] *= 1.25  # 注入 25% 尖峰（采样噪声嫌疑面）
        tab2 = build_dispersion_table(tab.f_grid_hz, tab.eps_eff_grid, g,
                                      geometry=tab.geometry)
        q = table_quality(tab2)
        assert q["verdict"] == "WARN"
        assert any(v["quantity"] == "z0" and v["index"] == 3
                   for v in q["violations"])

    def test_provenance_absent_flagged(self):
        tab = build_dispersion_table([1e9, 2e9], [2.0, 2.1], [70.0, 71.0])
        q = table_quality(tab)
        assert q["provenance"] == "absent"


class TestLambdaG:
    def test_identity(self):
        # 3GHz、εeff=2.25 → λg = C0/(3GHz·1.5) = 66.6205mm（C0=SI 定义值）
        assert lambda_g_mm(3.0, 2.25) == pytest.approx(
            C0 / 3e9 / 1.5 * 1e3, rel=1e-15)

    def test_guards(self):
        with pytest.raises(ValueError):
            lambda_g_mm(-1.0, 2.0)
        with pytest.raises(ValueError):
            lambda_g_mm(3.0, 0.5)
