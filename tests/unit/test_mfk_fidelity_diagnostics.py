"""OP-7（round16 §六）：MFK 保真相关性诊断暴露 单元测试。

判据预声明（解析锚 + SMT 实录，2026-10-03 本机 smt 2.14.1 实测）：

1. 结构正确性：强相关合成族（y_hi = 2·y_lo 结构建模对齐）→ ρ=2
   （AR1 系数，smt optimal_par[1]['beta'][0,0] 实录位）、warn=False；
2. 弱相关告警：低保真 = 无关噪声（ρ≈0）→ |ρ| < 0.1 → warn=True 且
   warning 文案含"相关性弱"；全模型 warn 聚合位=True；
3. rho_regr 非 constant 档：无标量 ρ → rho=None + reason 文案（诚实
   缺省，不编数）；
4. 既有路径不变：predict/uncertainty 行为不受新增诊断方法影响；
   fit 未拟合时 diagnostics 显式 RuntimeError。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.optimization.surrogate.smt_mfk import SMTMultiFidelitySurrogate


def _make(low_scale: float, noise: float = 0.0, seed: int = 0,
          **extra_cfg) -> SMTMultiFidelitySurrogate:
    xh = np.linspace(0.0, 1.0, 6)
    yh = (xh - 0.5) ** 2
    xl = np.linspace(0.0, 1.0, 20)
    yl = low_scale * (xl - 0.5) ** 2 + 0.05
    if noise:
        rng = np.random.default_rng(seed)
        yl = yl + noise * rng.standard_normal(xl.size)
    hi = [{"params": {"x": float(v)}, "metrics": {"f": float(vv)}}
          for v, vv in zip(xh, yh, strict=True)]
    lo = [{"params": {"x": float(v)}, "metrics": {"f": float(vv)}}
          for v, vv in zip(xl, yl, strict=True)]
    cfg = {"bounds": {"x": (0.0, 1.0)}, "low_fi_samples": lo, **extra_cfg}
    model = SMTMultiFidelitySurrogate(config=cfg)
    model.fit(hi)
    return model


class TestRhoDiagnostics:
    def test_correlated_family_rho_positive(self):
        model = _make(0.5)
        diag = model.fidelity_diagnostics()
        entry = diag["metrics"]["f"]
        assert entry["rho"] == pytest.approx(2.0, abs=0.05)
        assert entry["warn"] is False
        assert diag["warn"] is False
        assert entry["sigma2_rho"] is not None
        assert entry["sigma2_rho"] >= 0.0

    def test_decorrelated_family_warns(self):
        model = _make(1.0, noise=2.0, seed=1)
        diag = model.fidelity_diagnostics()
        entry = diag["metrics"]["f"]
        assert entry["rho"] is not None and abs(entry["rho"]) < 0.1
        assert entry["warn"] is True
        assert "相关性弱" in entry["warning"]
        assert diag["warn"] is True

    def test_nonconstant_rho_regr_honest_none(self):
        model = _make(0.5, rho_regr="linear")
        diag = model.fidelity_diagnostics()
        entry = diag["metrics"]["f"]
        assert entry["rho"] is None
        assert "rho_regr" in entry["warning"]

    def test_explicit_x_point(self):
        model = _make(0.5)
        diag = model.fidelity_diagnostics({"x": 0.3})
        assert diag["x"] == {"x": pytest.approx(0.3)}
        assert "f" in diag["metrics"]

    def test_unfitted_rejected(self):
        model = SMTMultiFidelitySurrogate(
            config={"bounds": {"x": (0, 1)}, "low_fi_samples": []})
        with pytest.raises(RuntimeError, match="未拟合"):
            model.fidelity_diagnostics()


class TestExistingPathUnchanged:
    def test_predict_and_uncertainty_still_work(self):
        model = _make(0.5)
        pred = model.predict({"x": 0.25})
        assert set(pred) == {"f"}
        unc = model.uncertainty({"x": 0.25})
        assert unc["f"] >= 0.0
        # 新增 fit 选项不影响缺省（无 rho_regr 键 → SMT 缺省 constant）
        diag = model.fidelity_diagnostics()
        assert diag["metrics"]["f"]["rho"] is not None
