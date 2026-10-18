"""EC-17 saas_gp 单测：SAAS 稀疏 ARD MAP 点估计（全离线确定性）。

合成基准（已知真值回收，#118 双源）：15 维函数仅 {x2, x7} 两轴活跃
（闭式定义即真值源）——MAP 后活跃集精确回收、非活跃轴 ℓ 压向不动点
（比活跃轴大 3 个量级）、留出集 NRMSE 达标；单轴函数进一步钉"稀疏压
力"（其余 14 轴全关）。empirical 诚实边界见模块 docstring（MAP 点估计
非全贝叶斯后验）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.stats import qmc

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.saas_gp import SaasArdSurrogate

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

D = 15
BOUNDS_15 = {f"x{i}": (0.0, 1.0) for i in range(D)}
TRUE_ACTIVE = {"x2", "x7"}


def _f15(u: np.ndarray) -> float:
    """15 维仅 2 轴活跃的闭式函数（等强度，避免数据支持度不对称）。"""
    return 0.6 * np.sin(2 * np.pi * u[2]) + 0.5 * np.sin(2 * np.pi * u[7])


def _samples(n: int = 48, seed: int = 11,
             fn=None) -> list[dict]:
    u_all = qmc.LatinHypercube(d=D, seed=seed).random(n=n)
    f = fn if fn is not None else _f15
    return [{"params": {f"x{i}": float(u[i]) for i in range(D)},
             "metrics": {"y": float(f(u))}} for u in u_all]


class TestSaasArd:
    def test_registered(self):
        assert "saas_gp" in surrogate_registry.available()

    def test_sparse_axis_recovery_15d(self):
        """合成基准核心断言：活跃集精确回收 + 量级分离 + 留出精度。"""
        model = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        model.fit(_samples())
        assert set(model.active_dims_["y"]) == TRUE_ACTIVE
        ell = model.lengthscales_["y"]
        max_active = max(ell[k] for k in TRUE_ACTIVE)
        min_inactive = min(v for k, v in ell.items() if k not in TRUE_ACTIVE)
        assert min_inactive / max_active > 100.0  # 量级分离（稀疏压力生效）
        # 留出集精度（已知真值回收）
        u_test = qmc.LatinHypercube(d=D, seed=12).random(n=30)
        errs = [model.predict({f"x{i}": float(u[i]) for i in range(D)})["y"]
                - _f15(u) for u in u_test]
        tru = [_f15(u) for u in u_test]
        nrmse = float(np.sqrt(np.mean(np.square(errs))) / np.std(tru))
        assert nrmse < 0.15

    def test_single_axis_function_all_others_suppressed(self):
        """仅 x0 活跃 ⇒ 其余 14 轴全部压到阈值外（稀疏先验本职）。"""
        model = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        model.fit(_samples(fn=lambda u: float(np.sin(2 * np.pi * u[0]))))
        assert set(model.active_dims_["y"]) == {"x0"}

    def test_deterministic_and_contract(self):
        """同数据同 ℓ（C4 逐位）+ 契约键/不确定度口径。"""
        samples = _samples()
        m1 = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        m2 = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        m1.fit(samples)
        m2.fit(samples)
        assert m1.lengthscales_ == m2.lengthscales_
        p = {f"x{i}": 0.3 for i in range(D)}
        assert m1.predict(p) == m2.predict(p)
        assert m1.uncertainty(p)["y"] > 0.0
        info = m1._mark_fitted(len(samples))
        assert info["kind"] == "saas_gp"

    def test_sparse_metric_key_skipped(self):
        samples = _samples()
        samples[0]["metrics"]["ghost"] = 0.0  # 仅 1 个有效点 → 跳过
        model = SaasArdSurrogate(config={"bounds": BOUNDS_15})
        model.fit(samples)
        assert "y" in model.models
        assert "ghost" not in model.models
