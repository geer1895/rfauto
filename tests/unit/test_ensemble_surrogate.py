"""T-N6 LOOCV 加权集成代理单测（aurora_n W1-C，注册键 "ensemble"）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N6）：
- 合成三族（光滑/噪声/离群）：ensemble ρ ≥ 单成员最优 ρ − ε，ε=0.05
  预声明（ρ 全部经 loocv_rho 公开 API 折外预测产生——裁判面与被测实现
  同口径但独立调用，不碰 ensemble 内部权重路径，#118）；
- 负例：单成员 fit/LOOCV 失败按权重剔除且 fit_info 如实记录（不静默
  塌缩）；全部成员失败显式 RuntimeError；仅 1 席幸存记 warning；
  多指标缺 rho_metric 显式 ValueError（不替用户猜裁判面）；
- 确定性钉：同配置同样本两次 fit 权重与预测逐位相等（只互比，不钉
  绝对值——跨平台 BLAS 轨迹漂移防线，#247 家法）；
- 注册面/门面 re-export/model_card 出卡验证（#231 家法消费者同步）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.surrogate import surrogate_registry
from rfauto.optimization.surrogate.ensemble import EnsembleSurrogate
from rfauto.optimization.surrogate.poly_ridge import loocv_rho

# 纯 numpy 必备成员（零可选依赖；gbdt/smt_kriging 组合面走 importorskip）。
# nn 用快档成员 config（epochs/席位收窄，成员 config 是 ensemble 契约面）
# ——缺省 epochs=4000×3 席会让 ensemble 整体 LOOCV（O(n²·m) 成员拟合，
# 模块 docstring 规模注记）在单测预算内跑不完（探针实测教训）。
NN_FAST = {"kind": "nn",
           "config": {"epochs": 300, "n_ensemble": 1, "hidden": 12}}
MEMBERS_CORE = ["poly_ridge", NN_FAST]
MEMBER_KINDS = ("poly_ridge", "nn")
#: ρ 门容差（任务书预声明：ensemble ρ 不劣于单成员最优 −ε，ε=0.05；
#: 探针冻结实测 runs/aurora_n/wave1_c/probe_tn6_rho_gate.py：
#: n=24 全 9 组最差余量 −0.0096；n=16 复测（单测预算收窄）三族最差
#: 余量 ens−best=−0.0147，两档均在 ε 内 3× 余量）
RHO_EPS = 0.05
GATE_N = 16
GATE_SEED = 20261029

BOUNDS = {"x": (0.0, 1.0)}


# ── 合成语料裁判（独立真值面，与被测实现非共享代码路径） ────────────────

def _truth(x: float) -> float:
    return 0.8 * x + 0.15 * math.sin(3.0 * x) + 0.4 * x * x


def _samples(family: str, n: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = rng.uniform(*BOUNDS["x"], n)
    ys = np.array([_truth(float(x)) for x in xs])
    if family == "noisy":
        ys = ys + rng.normal(0.0, 0.12, n)
    elif family == "outlier":
        idx = rng.choice(n, size=max(2, n // 10), replace=False)
        ys[idx] += rng.normal(0.0, 1.2, len(idx))
    return [{"params": {"x": float(x)}, "metrics": {"y": float(y)}}
            for x, y in zip(xs, ys, strict=True)]


def _ens_cfg(members: list) -> dict:
    return {"bounds": dict(BOUNDS), "members": members, "rho_metric": "y"}


def _member_rho(samples: list[dict], kind: str) -> float | None:
    """单成员 LOOCV ρ（公开 API 裁判面；与 ensemble 内部无共享路径）。"""
    cfg: dict = {"bounds": dict(BOUNDS)}
    if kind == "nn":
        cfg.update(NN_FAST["config"])
    if kind == "gbdt":
        cfg["n_estimators"] = 50
    res = loocv_rho(samples, lambda s: float(s["metrics"]["y"]),
                    lambda k=kind, c=cfg: surrogate_registry.create(
                        k, config=dict(c)))
    return float(res["rho"]) if res.get("ok") else None


# ── 正例：三族合成对照 ρ 门 ─────────────────────────────────────────────

class TestEnsembleRhoGate:
    @pytest.mark.parametrize("family", ["smooth", "noisy", "outlier"])
    def test_ensemble_rho_not_worse_than_best_member(self, family):
        """ensemble ρ ≥ max(单成员 ρ) − 0.05（预声明 ε，探针冻结常量）。"""
        samples = _samples(family, GATE_N, GATE_SEED)
        ens_factory = lambda: surrogate_registry.create(  # noqa: E731
            "ensemble", config=_ens_cfg(MEMBERS_CORE))
        res = loocv_rho(samples, lambda s: float(s["metrics"]["y"]),
                        ens_factory)
        assert res["ok"], res
        member_rhos = [r for r in (_member_rho(samples, k)
                                   for k in MEMBER_KINDS) if r is not None]
        assert member_rhos, "单成员裁判面自身失效（测试前提破坏）"
        best = max(member_rhos)
        assert res["rho"] >= best - RHO_EPS, (
            f"{family}: ensemble ρ={res['rho']:.4f} < best 成员 "
            f"{best:.4f} − {RHO_EPS}")

    def test_weights_monotone_in_rho_and_sum_to_one(self):
        """softmax 单调性：ρ 最高成员拿最大权重；权重和恒 1（构造恒等式）。"""
        samples = _samples("noisy", GATE_N, 7)
        model = EnsembleSurrogate(_ens_cfg(MEMBERS_CORE))
        info = model.fit(samples)
        w = info["weights"]
        assert set(w) == set(MEMBER_KINDS)
        assert abs(sum(w.values()) - 1.0) < 1e-12
        rho_of = {r["kind"]: r["rho"] for r in info["members"]
                  if r["status"] == "active"}
        best_rho = max(rho_of, key=rho_of.__getitem__)
        assert max(w, key=w.__getitem__) == best_rho


# ── 契约面：离散度 σ（免费 epistemic） ────────────────────────────────

class TestEnsembleUncertainty:
    def test_dispersion_std_and_range_two_members(self):
        """两成员离散度：std=|a−b|/2、range=|a−b|（构造恒等式）。"""
        samples = _samples("smooth", 24, 11)
        cfg = _ens_cfg(MEMBERS_CORE)
        m_std = EnsembleSurrogate(dict(cfg, dispersion="std"))
        m_rng = EnsembleSurrogate(dict(cfg, dispersion="range"))
        m_std.fit(samples)
        m_rng.fit(samples)
        pt = {"x": 0.37}
        # 离散度对照基准：成员各自按同款 spec 拟合（config 必须与 ensemble
        # 注入面一致——nn 快档 config 不一致=两个不同的网络，恒等式不成立）
        raw = []
        for spec in MEMBERS_CORE:
            kind = spec if isinstance(spec, str) else spec["kind"]
            cfg_i: dict = {"bounds": dict(BOUNDS)}
            if isinstance(spec, dict):
                cfg_i.update(spec["config"])
            mm = surrogate_registry.create(kind, config=cfg_i)
            mm.fit(samples)
            raw.append(float(mm.predict(pt)["y"]))
        spread = abs(raw[0] - raw[1])
        assert m_std.uncertainty(pt)["y"] == pytest.approx(spread / 2.0)
        assert m_rng.uncertainty(pt)["y"] == pytest.approx(spread)
        assert m_std.uncertainty(pt)["y"] >= 0.0
    def test_single_survivor_sigma_zero_with_warning(self):
        """仅 1 席幸存：uncertainty 恒 0.0 + fit_info warning（不静默）。"""
        samples = _samples("smooth", 20, 3)
        model = EnsembleSurrogate(_ens_cfg(["poly_ridge"]))
        info = model.fit(samples)
        assert info["n_members_effective"] == 1
        assert "single_member_warning" in info
        sigma = model.uncertainty({"x": 0.5})
        assert sigma == {"y": 0.0}

    def test_predict_with_std_via_base_contract(self):
        """base.predict_with_std 经 uncertainty 得 (mean, σ)，σ 非 None。"""
        samples = _samples("smooth", 20, 5)
        model = EnsembleSurrogate(_ens_cfg(MEMBERS_CORE))
        model.fit(samples)
        mean, std = model.predict_with_std({"x": 0.5})["y"]
        assert std is not None and std >= 0.0
        assert mean == pytest.approx(model.predict({"x": 0.5})["y"])


# ── 负例：剔除/全灭/裁判面歧义 ─────────────────────────────────────────

class TestEnsembleNegative:
    def test_bad_member_dropped_and_recorded_not_collapsed(self):
        """单成员注册键不存在 → 剔除 + fit_info 记 error（其余照常工作）。"""
        samples = _samples("smooth", 20, 9)
        model = EnsembleSurrogate(_ens_cfg([*MEMBERS_CORE, "no_such_kind"]))
        info = model.fit(samples)
        by_kind = {r["kind"]: r for r in info["members"]}
        assert by_kind["no_such_kind"]["status"] == "dropped"
        assert "no_such_kind" in by_kind["no_such_kind"]["error"]
        assert by_kind["poly_ridge"]["status"] == "active"
        assert info["n_members_effective"] == 2
        assert "no_such_kind" not in info["weights"]
        # 剔除后预测/离散度仍按幸存成员工作
        assert math.isfinite(model.predict({"x": 0.4})["y"])

    def test_all_members_fail_raises(self):
        """全部成员失败 → 显式 RuntimeError（不产空壳集成）。"""
        samples = _samples("smooth", 20, 9)
        model = EnsembleSurrogate(_ens_cfg(["no_such_kind", "also_missing"]))
        with pytest.raises(RuntimeError, match="全部成员失败"):
            model.fit(samples)
        assert not model.fitted

    def test_multi_metric_requires_explicit_rho_metric(self):
        """样本多指标且未给 rho_metric → ValueError（不猜裁判面）。"""
        samples = [{"params": {"x": 0.1 * i},
                    "metrics": {"y": float(i), "z": float(i * i)}}
                   for i in range(8)]
        cfg = {"bounds": dict(BOUNDS), "members": MEMBERS_CORE}
        model = EnsembleSurrogate(cfg)
        with pytest.raises(ValueError, match="rho_metric"):
            model.fit(samples)

    def test_too_few_samples_rejected(self):
        """样本 <4（LOOCV 无意义）→ fit 期显式 ValueError。"""
        samples = _samples("smooth", 3, 1)
        model = EnsembleSurrogate(_ens_cfg(MEMBERS_CORE))
        with pytest.raises(ValueError, match="至少需要 4"):
            model.fit(samples)

    def test_config_validation_rejects(self):
        """bounds 缺失/空成员/自嵌套/非法温度/非法离散度 → ValueError。"""
        with pytest.raises(ValueError, match="bounds"):
            EnsembleSurrogate({"members": ["poly_ridge"]})
        with pytest.raises(ValueError, match="members"):
            EnsembleSurrogate({"bounds": dict(BOUNDS), "members": []})
        with pytest.raises(ValueError, match="嵌套"):
            EnsembleSurrogate(_ens_cfg(["ensemble"]))
        with pytest.raises(ValueError, match="softmax_temperature"):
            EnsembleSurrogate(dict(_ens_cfg(MEMBERS_CORE),
                                   softmax_temperature=0.0))
        with pytest.raises(ValueError, match="dispersion"):
            EnsembleSurrogate(dict(_ens_cfg(MEMBERS_CORE),
                                   dispersion="mad"))


# ── 确定性钉（互比逐位，不钉绝对值） ───────────────────────────────────

class TestEnsembleDeterminism:
    def test_weights_and_predictions_bit_identical(self):
        samples = _samples("noisy", 26, 2026)
        m1 = EnsembleSurrogate(_ens_cfg(MEMBERS_CORE))
        m2 = EnsembleSurrogate(_ens_cfg(MEMBERS_CORE))
        i1, i2 = m1.fit(samples), m2.fit(samples)
        assert i1["weights"] == i2["weights"]
        for x in (0.1, 0.5, 0.9):
            pt = {"x": x}
            assert m1.predict(pt) == m2.predict(pt)
            assert m1.uncertainty(pt) == m2.uncertainty(pt)

    def test_registry_facade_and_card(self):
        """注册键可用；门面 re-export 同一对象；model_card 出卡验证。"""
        assert "ensemble" in surrogate_registry.available()
        from rfauto.optimization.surrogate import EnsembleSurrogate as F
        assert F is EnsembleSurrogate
        m = surrogate_registry.create("ensemble",
                                      config=_ens_cfg(MEMBERS_CORE))
        assert isinstance(m, EnsembleSurrogate)
        # #231 家法消费者：model_card_service registry 卡面含 ensemble
        from rfauto.service.model_card_service import (
            build_model_card,
            registry_model_ids,
        )
        assert "ensemble" in registry_model_ids()["surrogate"]
        card = build_model_card("ensemble", "registry")
        assert card.get("ok") is not False
        body = card
        assert body.get("model_id") == "ensemble"
        assert body.get("kind") == "surrogate"


# ── 可选依赖成员组合面（gbdt/smt_kriging；缺依赖环境跳过） ─────────────

class TestEnsembleOptionalMembers:
    def test_four_member_composition(self):
        pytest.importorskip("sklearn", reason="sklearn 可选依赖")
        pytest.importorskip("smt", reason="smt 可选依赖")
        samples = _samples("noisy", 24, 17)
        model = EnsembleSurrogate(
            _ens_cfg([*MEMBERS_CORE, "gbdt", "smt_kriging"]))
        info = model.fit(samples)
        assert info["n_members_effective"] == 4
        assert set(info["weights"]) == {"poly_ridge", "nn", "gbdt",
                                        "smt_kriging"}
        # 四成员离散度 ≥ 两成员（poly_ridge+nn）离散度的一般趋势不钉——
        # 只钉非负与有限（#247 跨平台防线）
        sigma = model.uncertainty({"x": 0.6})["y"]
        assert math.isfinite(sigma) and sigma >= 0.0
