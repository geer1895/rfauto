"""T-N1 split-conformal UQ 包装器单测（aurora_n W1-A，注册键 "conformal"）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N1）：
- 合成一维噪声函数 + 固定 seed：名义 90% 区间实测覆盖 ∈ [85%, 95%]
  （合成对照；裁判独立构造——本文件真值生成器与被测实现非共享代码路径，
  #118）；
- 负例：校准集混入分布外点（协变量 OOD 只进校准集的经典 split-conformal
  场景，cal_indices 显式划出）→ 覆盖如实破位（>95%）且 fit_info 报警；
  协变量漂移（低噪区校准/高噪区评估）→ 覆盖破位（<85%，边际保证失效
  实证，对应 docstring "边际覆盖非逐点" 标注）；
- 确定性钉：同 seed 两次 fit 分位数逐位相等；
- 数值内核单源：分位数数学全部复用 core/conformal（本文件零重复实现）；
- 覆盖率断言用带域而非逐位浮点（跨平台 BLAS 轨迹漂移防线，#247 家法）；
  确定性钉只断言"两次 fit 相互逐位相等"，不钉绝对值。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.surrogate.base import surrogate_registry
from rfauto.optimization.surrogate.conformal import ConformalSurrogate

# ── 合成对照裁判（独立真值面：f(x)=0.8x+0.15sin(3x)+N(0,σ)） ───────────

def _truth(xs, rng, sigma):
    return 0.8 * xs + 0.15 * np.sin(3.0 * xs) \
        + rng.normal(0.0, sigma, size=len(xs))


def _make_samples(xs, sigma, seed):
    ys = _truth(xs, np.random.default_rng(seed), sigma)
    return [{"params": {"x": float(xi)}, "metrics": {"y": float(yi)}}
            for xi, yi in zip(xs, ys, strict=True)]


def _coverage(model, xs, ys):
    """经验覆盖率（真值侧独立计算，不经被测实现的区间组装）。"""
    covered = 0
    for xi, yi in zip(xs, ys, strict=True):
        mean = float(model.predict({"x": float(xi)})["y"])
        q = float(model.uncertainty({"x": 0.0})["y"])
        covered += int((mean - q) <= float(yi) <= (mean + q))
    return covered / len(xs)


_BASE_CFG = {"base_kind": "poly_ridge",
             "base_config": {"bounds": {"x": [0.0, 1.0]}, "order": 2},
             "alpha": 0.1, "cal_ratio": 0.5, "seed": 7}


def _fit_pos():
    xs = np.random.default_rng(20261029).uniform(0.0, 1.0, 240)
    model = ConformalSurrogate(dict(_BASE_CFG))
    info = model.fit(_make_samples(xs, 0.05, 20261029))
    xt = np.random.default_rng(99).uniform(0.0, 1.0, 300)
    yt = _truth(xt, np.random.default_rng(99), 0.05)
    return model, info, xt, yt


# ── 正例：名义 90% 区间实测覆盖 ∈ [85%, 95%] ─────────────────────────

class TestConformalCoverage:
    def test_nominal_90_interval_coverage_in_band(self):
        """合成对照（任务书验收）：覆盖 0.93 ∈ [0.85, 0.95]（探针实测）。"""
        model, info, xt, yt = _fit_pos()
        assert info["n_train"] == 120 and info["n_cal"] == 120
        assert info["target_coverage"] == pytest.approx(0.9)
        cov = _coverage(model, xt, yt)
        assert 0.85 <= cov <= 0.95, f"实测覆盖 {cov} 越带"
        # 干净校准面不误报（启发式防误报钉：q90/q25 干净带 3.8–6.1）
        assert "coverage_warning" not in info

    def test_std_none_remedy_q_not_faked(self):
        """std=None 档正面出路：uncertainty 返回保形半宽（非 0 非伪造 σ）。"""
        model, _info, _xt, _yt = _fit_pos()
        q = model.uncertainty({"x": 0.5})
        assert q is not None and set(q) == {"y"}
        assert 0.05 < q["y"] < 0.2  # 探针实测 0.0968（噪声+偏差量级）
        # 基类 predict_with_std 经由 uncertainty 得 (mean, q)，std 不再是 None
        mean, std = model.predict_with_std({"x": 0.5})["y"]
        assert std is not None and std == q["y"]
        # 区间组装与 predict_interval 内核同源：lo = mean − q
        lo, hi = model.predict_interval({"x": 0.5})["y"]
        assert lo == pytest.approx(mean - q["y"])
        assert hi == pytest.approx(mean + q["y"])

    def test_registry_key_and_facade(self):
        """注册键 "conformal" 可用；注册面 create 与手写构造同构。"""
        assert "conformal" in surrogate_registry.available()
        m = surrogate_registry.create("conformal", config=dict(_BASE_CFG))
        assert isinstance(m, ConformalSurrogate)
        assert m.KIND == "conformal"
        from rfauto.optimization.surrogate import ConformalSurrogate as F
        assert F is ConformalSurrogate  # 包门面 re-export 同一对象


# ── 负例：分布外污染/漂移 → 覆盖如实破位 + fit_info 报警 ─────────────

class TestConformalNegative:
    def test_ood_in_calibration_breaks_coverage_and_warns(self):
        """校准集混入分布外点（OOD 全部只进校准集）→ 覆盖 >95% 破位 + 报警。

        形态：180 干净域内样本 + 20 个 x∈[1.6,2.4] 协变量 OOD（外推残差
        天然巨大），cal_indices 显式把 OOD 全部划进校准集（train 干净 →
        base 健康，重尾诊断可辨识）。实测（探针）：q 0.097→0.987（虚胖
        ~10×），干净测试面覆盖 1.0 > 0.95，fit_info 报警非空。
        """
        xs_in = np.random.default_rng(20261029).uniform(0.0, 1.0, 180)
        samples = _make_samples(xs_in, 0.05, 20261029)
        xs_ood = np.random.default_rng(31337).uniform(1.6, 2.4, 20)
        samples += _make_samples(xs_ood, 0.05, 31338)
        model = ConformalSurrogate(dict(_BASE_CFG,
                                        cal_indices=list(range(160, 200))))
        info = model.fit(samples)
        # fit_info 报警（#122 不静默）
        warns = info.get("coverage_warning")
        assert warns and len(warns) == 1
        assert "重尾" in warns[0] and "分布外" in warns[0]
        assert "y" in warns[0]
        # 覆盖如实破位（向上破带：区间虚胖致恒覆盖）
        xt = np.random.default_rng(99).uniform(0.0, 1.0, 300)
        yt = _truth(xt, np.random.default_rng(99), 0.05)
        cov = _coverage(model, xt, yt)
        assert cov > 0.95, f"实测覆盖 {cov} 未破位"
        # 干净面 q≈0.097 → 污染面 q≈0.99（虚胖，覆盖保证失效的直接证据）
        assert model.uncertainty({"x": 0.5})["y"] > 0.5

    def test_covariate_shift_breaks_coverage_downward(self):
        """协变量漂移（低噪区校准/高噪区评估）→ 覆盖 <85% 破位。

        边际覆盖保证的交换性前提被破坏的实证（docstring 口径）：校准面
        本身干净（无报警——报警只针对校准集污染，不臆测未来漂移），
        但名义 90% 区间在漂移评估面上实测只盖住 ~21%。
        """
        xs = np.random.default_rng(20261029).uniform(0.0, 0.45, 240)
        model = ConformalSurrogate(dict(_BASE_CFG))
        info = model.fit(_make_samples(xs, 0.05, 20261029))
        assert "coverage_warning" not in info  # 校准面干净，不误报
        xt = np.random.default_rng(77).uniform(0.55, 1.0, 200)
        yt = _truth(xt, np.random.default_rng(78), 0.40)
        cov = _coverage(model, xt, yt)
        assert cov < 0.85, f"实测覆盖 {cov} 未破位"


# ── 确定性钉：同 seed 两次 fit 分位数逐位相等 ─────────────────────────

class TestConformalDeterminism:
    def test_same_seed_bitwise_identical_quantiles(self):
        samples = _make_samples(
            np.random.default_rng(5).uniform(0.0, 1.0, 240), 0.05, 6)
        a = ConformalSurrogate(dict(_BASE_CFG)).fit(samples)["quantiles"]
        b = ConformalSurrogate(dict(_BASE_CFG)).fit(samples)["quantiles"]
        assert a == b  # 逐位（float ==）相等，非 approx
        # 显式 cal_indices 路径同样确定性（划分即显式，seed 不消费）
        cfg = dict(_BASE_CFG, cal_indices=[0, 2, 4, 6, 8, 10])
        c = ConformalSurrogate(cfg).fit(samples)["quantiles"]
        d = ConformalSurrogate(cfg).fit(samples)["quantiles"]
        assert c == d

    def test_explicit_cal_indices_split_accounting(self):
        samples = _make_samples(
            np.random.default_rng(5).uniform(0.0, 1.0, 12), 0.05, 6)
        cfg = dict(_BASE_CFG, cal_indices=[0, 2, 4, 6, 8, 10])
        model = ConformalSurrogate(cfg)
        info = model.fit(samples)
        assert info["n_cal"] == 6 and info["n_train"] == 6
        assert info["split"].startswith("explicit_cal_indices")


# ── 配置校验与边界（显式报错不静默） ─────────────────────────────────

class TestConformalConfigErrors:
    def _samples(self, n=8):
        return _make_samples(np.random.default_rng(1).uniform(0, 1, n),
                             0.05, 2)

    def test_missing_base_kind_rejected(self):
        with pytest.raises(ValueError, match="base_kind"):
            ConformalSurrogate({"alpha": 0.1}).fit(self._samples())

    def test_self_nesting_rejected(self):
        with pytest.raises(ValueError, match="不可嵌套自身"):
            ConformalSurrogate({"base_kind": "conformal"})

    def test_unknown_base_kind_rejected_by_registry(self):
        model = ConformalSurrogate({"base_kind": "no_such_kind"})
        with pytest.raises(KeyError, match="未注册"):
            model.fit(self._samples())

    def test_bad_cal_ratio_rejected(self):
        with pytest.raises(ValueError, match="cal_ratio"):
            ConformalSurrogate(dict(_BASE_CFG, cal_ratio=1.0))

    def test_too_few_samples_rejected(self):
        model = ConformalSurrogate(dict(_BASE_CFG))
        with pytest.raises(ValueError, match="至少需要 4 个样本"):
            model.fit(self._samples(3))

    def test_bad_alpha_rejected_by_kernel(self):
        """alpha 校验单源在内核 calibrate（fit 期显式报错）。"""
        model = ConformalSurrogate(dict(_BASE_CFG, alpha=1.0))
        with pytest.raises(ValueError, match="alpha"):
            model.fit(self._samples())

    def test_bad_cal_indices_rejected(self):
        with pytest.raises(ValueError, match="cal_indices"):
            ConformalSurrogate(dict(_BASE_CFG, cal_indices=[0, "x"]))
        with pytest.raises(ValueError, match="重复"):
            ConformalSurrogate(dict(_BASE_CFG, cal_indices=[1, 1, 2]))
        with pytest.raises(ValueError, match="至少 2 个"):
            ConformalSurrogate(dict(_BASE_CFG, cal_indices=[1]))
        model = ConformalSurrogate(dict(_BASE_CFG, cal_indices=[0, 1, 99]))
        with pytest.raises(ValueError, match="越界"):
            model.fit(self._samples(8))

    def test_unfitted_predict_rejected(self):
        model = ConformalSurrogate(dict(_BASE_CFG))
        with pytest.raises(RuntimeError, match="未拟合"):
            model.predict({"x": 0.5})
        with pytest.raises(RuntimeError, match="未拟合"):
            model.uncertainty({"x": 0.5})

    def test_q_overflow_honest_inf(self):
        """校准集撑不起 α → q=+inf（内核如实上溢不夹持）+ fit_info 报警。

        n_cal=2、alpha=0.1 → k=ceil(3·0.9)=3 > 2；cal_indices 显式钉小
        校准集（随机划分下 poly_ridge 需 ≥3 train 样本才出模型）。
        """
        samples = self._samples(6)
        model = ConformalSurrogate(dict(_BASE_CFG, cal_indices=[4, 5]))
        info = model.fit(samples)
        assert info["n_cal"] == 2
        q = model.uncertainty({"x": 0.5})["y"]
        assert math.isinf(q)
        assert any("+inf" in w for w in info["coverage_warning"])
        lo, hi = model.predict_interval({"x": 0.5})["y"]
        assert math.isinf(lo) and math.isinf(hi)

    def test_dropped_and_empty_metrics(self):
        """缺键指标如实 dropped；全空显式报错（不硬拟不伪造）。"""
        samples = self._samples(8)
        cfg = dict(_BASE_CFG, metrics=["y", "zz"])
        info = ConformalSurrogate(cfg).fit(samples)
        assert info["metric_keys_dropped"] == ["zz"]
        assert set(info["quantiles"]) == {"y"}
        with pytest.raises(ValueError, match="无有效指标"):
            ConformalSurrogate(dict(_BASE_CFG, metrics=["zz"])).fit(samples)
