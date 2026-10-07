"""AAA 有理逼近试点钉（round3 附带三件之一；core/aaa.py）。

数值纪律：全部数值断言 = 合成已知有理函数的**回收误差**，
容差预声明（按 2026-09-28 venv scipy 1.18.1 实测收敛留 ≥10× 余量）：
- AAA 极点回收 max rel err ≤ 1e-5（实测 6.6e-7）
- AAA 样本 RMS ≤ 1e-12（实测 5.1e-17）
- VF 样本 RMS ≤ 1e-6（实测 1.2e-9，正确阶）
VF 侧只钉 RMS 与存储阶数（#286：skrf 共轭对只存一个；VF 极点 rad/s 域且
可在 RMS 达标下迁移，不做极点匹配——core/aaa.py docstring 如实口径）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.aaa import aaa_fit, aaa_vs_vf_compare, match_poles

_AAA_AVAILABLE = True
try:
    from scipy.interpolate import AAA  # noqa: F401
except ImportError:
    _AAA_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _AAA_AVAILABLE,
    reason="scipy>=1.15 无 AAA（诚实 skip；venv 实测 1.18.1 应转正执行）",
)

# 合成真系统：3 极点（1 共轭对 + 1 实极点）+ 直接项，纯数学域（x 即调用方
# 频轴，无物理断言）。极点置于采样带内/邻域保证可辨识。
_TRUE_POLES = np.array([3.0e8 + 4.0e8j, 3.0e8 - 4.0e8j, 1.2e9])
_TRUE_RESIDUES = np.array([1.0 + 0.5j, 1.0 - 0.5j, 2.0 - 1.0j])
_DIRECT = 0.3
_FREQS = np.geomspace(1.0e8, 2.0e9, 160)


def _truth(freqs: np.ndarray) -> np.ndarray:
    y = np.full(freqs.shape, _DIRECT, dtype=complex)
    for q, r in zip(_TRUE_POLES, _TRUE_RESIDUES, strict=True):
        y = y + r / (freqs - q)
    return y


class TestAaaFit:
    def test_pole_recovery_within_predeclared_tol(self):
        fit = aaa_fit(_FREQS, _truth(_FREQS))
        verdict = match_poles(_TRUE_POLES, fit.poles)
        assert verdict["n_unmatched_true"] == 0
        assert verdict["max_rel_err"] <= 1e-5

    def test_rms_at_samples_machine_level(self):
        fit = aaa_fit(_FREQS, _truth(_FREQS))
        assert fit.rms_at_samples <= 1e-12
        assert fit.rms_db_at_samples <= -240.0

    def test_model_off_support_accuracy(self):
        fit = aaa_fit(_FREQS, _truth(_FREQS))
        mid = np.sort(
            np.concatenate([_FREQS[:-1] + np.diff(_FREQS) / 2.0, [_FREQS[-1] * 1.01]])
        )
        err = np.abs(fit.model(mid) - _truth(mid))
        assert float(err.max()) <= 1e-9

    def test_deterministic_bitwise(self):
        f1 = aaa_fit(_FREQS, _truth(_FREQS))
        f2 = aaa_fit(_FREQS, _truth(_FREQS))
        assert np.array_equal(f1.poles, f2.poles)
        assert np.array_equal(f1.support_points, f2.support_points)

    def test_residues_finite_and_shaped(self):
        fit = aaa_fit(_FREQS, _truth(_FREQS))
        assert fit.residues.shape == fit.poles.shape
        assert np.all(np.isfinite(fit.residues))

    def test_rejects_nan_and_mismatched_shapes(self):
        y = _truth(_FREQS)
        with pytest.raises(ValueError, match="NaN/Inf"):
            aaa_fit(_FREQS, np.where(np.arange(y.size) == 3, np.nan, y))
        with pytest.raises(ValueError, match="1D"):
            aaa_fit(_FREQS, y[:10])
        with pytest.raises(ValueError, match="过少"):
            aaa_fit(_FREQS[:2], y[:2])


class TestMatchPoles:
    def test_exact_match_zero_error(self):
        verdict = match_poles(_TRUE_POLES, _TRUE_POLES.copy())
        assert verdict["max_rel_err"] == 0.0
        assert verdict["n_unmatched_true"] == 0

    def test_permuted_fit_set_matches_all(self):
        verdict = match_poles(_TRUE_POLES, _TRUE_POLES[::-1].copy())
        assert verdict["n_unmatched_true"] == 0
        assert verdict["max_rel_err"] <= 1e-12

    def test_insufficient_fit_poles_counts_unmatched(self):
        verdict = match_poles(_TRUE_POLES, _TRUE_POLES[:1])
        assert verdict["n_unmatched_true"] == 2
        assert verdict["max_rel_err"] == 0.0


class TestAaaVsVfCompare:
    def test_compare_report(self):
        report = aaa_vs_vf_compare(
            _FREQS, _truth(_FREQS), n_poles_real=1, n_poles_cmplx=2
        )
        # AAA 侧极点回收钉（同 aaa_fit）
        aaa_poles = np.array([re + 1j * im for re, im in report["aaa"]["poles"]])
        verdict = match_poles(_TRUE_POLES, aaa_poles)
        assert verdict["max_rel_err"] <= 1e-5
        # VF 侧：RMS + 存储阶数钉（#286：n_real + n_cmplx，共轭对只存一个）
        assert report["vf"]["rms_at_samples"] <= 1e-6
        assert (
            report["vf"]["n_poles_stored"]
            == report["vf"]["n_poles_real"] + report["vf"]["n_poles_cmplx"]
        )
        # JSON 安全（服务层直出契约）
        json.dumps(report)

    def test_compare_deterministic(self):
        kw = {"n_poles_real": 1, "n_poles_cmplx": 2}
        r1 = aaa_vs_vf_compare(_FREQS, _truth(_FREQS), **kw)
        r2 = aaa_vs_vf_compare(_FREQS, _truth(_FREQS), **kw)
        assert r1 == r2
