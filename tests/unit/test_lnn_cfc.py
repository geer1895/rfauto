"""lnn_cfc（CfC 液态神经网络时域响应代理）单测（aurora_p LNN 席）。

判据（任务书预声明；容差先探针实测后冻结，冻结实测值见各断言注记；
证据 runs/aurora_p/lnn/probe_*.log 与 BENCH.md）：
- 裁判自检（#300 裁判先行）：二阶系统阶跃响应闭式解（欠/临/过三段式）
  对 scipy solve_ivp（rtol=1e-11，独立数值源）max|Δ| ≤ 1e-8（实测
  4.2e-12）；N 级 RC 级联闭式解对 scipy.special.gammainc（Erlang CDF
  独立源）max|Δ| ≤ 1e-12（实测 3.9e-16）；y(0)=0 与终值→1 三段通吃。
- BPTT 梯度裁判（#118 族）：loss_and_grads 对全部 12 组参数中心差分
  max|Δ| ≤ 1e-6（实测 2.95e-10）；
- CfC 单元性质锚（Eq.(10) 逐字推论）：gate(Δt=0)≡½（逐位）；f>0 时门随
  Δt 单调降且大 Δt→0；f>0 & Δt=1e3 ⇒ x⁺ 逐位=h（旧态路权重归零）；
  tanh 有界头 ⇒ |x⁺|≤1（LTC Thm.2 有界态精神）；同 seed 权重逐位、
  异 seed 必异；
- A1 已知锚+泛化+OOD（降档配置 6×6 网格/T=48/600 轮/H=12/B=24，探针
  probe_testcfg.log 冻结）：训练网格 RMSE mean ≤0.03（实测 0.0107）；
  内插 RMSE mean ≤0.02·max ≤0.05（实测 0.0079/0.0138）；ωn 凸包外
  [3.0,3.6] mean ≤0.05（实测 0.0128）；时域外推 t∈(8,11.9] mean ≤0.03
  （实测 0.0047）；细网格 2× 劣化为**结构性已知边界**（BENCH 30× 差距
  + Δt→0 门恒 ½ 根因），此处不设门、只钉 predict_curve docstring 所述
  包络外行为存在（诚实登记，#122 不凑绿）；
- A2 确定性（验收红线）：同 seed 重 fit 预测逐位相等；异 seed 必异；
  多速率档（dt_strides=(1,2)）同 seed 亦逐位；
- A3 负例（验收④）：samples 空 / 缺 bounds / 缺 time_grid / t1≤t0 /
  curve_samples<2 / hidden·backbone<1 / epochs<1 / lr≤0·非有限 /
  weight_decay<0 / dt_strides 非法（0/非整数/超界/空）/ grad_clip≤0 /
  轨迹非一维·长度<2·含非有限值（显式报错不静默）/ 有效轨迹 <2 /
  params 非有限 / 未拟合 predict / predict_curve n_points<2·t_end≤t0
  ——全部显式 ValueError/RuntimeError；
- A4 契约面（验收⑤零改动的存在性半边）：注册键在面 + 门面 re-export
  同一对象 + KIND="lnn_cfc" + fit_info 键面 + predict 摘要键与
  predict_curve 统计一致 + predict_with_std 如实 std=None + uncertainty
  None + n_params 计数钉（1309）+ 既有键零改动；
- 行为零改动由邻接回归定向批证明（devtest --changed 覆盖，本文件不重复）。
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.special import gammainc

import rfauto.optimization.surrogate as surr_pkg
from rfauto.optimization.surrogate import (
    DEFAULT_LNN_SEED,
    CfcNet,
    LnnCfcSurrogate,
    cfc_time_gate,
    rc_cascade_step_response,
    second_order_step_response,
    surrogate_registry,
)
from rfauto.optimization.surrogate.lnn_cfc import _clip_global_norm

_BOUNDS = {"wn": (1.0, 3.0), "zeta": (0.3, 1.2)}
_CFG = {"bounds": _BOUNDS, "time_grid": [0.0, 8.0], "curve_samples": 48,
        "hidden": 12, "backbone": 24, "epochs": 600, "lr": 5e-3,
        "seed": DEFAULT_LNN_SEED}


def _make_samples(bounds, fn, t, n_grid: int):
    lo0, hi0 = bounds["wn"]
    lo1, hi1 = bounds["zeta"]
    return [{"params": {"wn": float(w), "zeta": float(z)},
             "metrics": {"response_curve": fn(t, w, z).tolist()}}
            for w in np.linspace(lo0, hi0, n_grid)
            for z in np.linspace(lo1, hi1, n_grid)]


def _rmse(a, b) -> float:
    return float(np.sqrt(np.mean((np.asarray(a, float) - np.asarray(b, float)) ** 2)))


@pytest.fixture(scope="module")
def fitted():
    """降档配置一次拟合供锚/泛化/OOD 共用（探针实测 ~2s）。"""
    t = np.linspace(0.0, 8.0, 48)
    model = LnnCfcSurrogate(config=dict(_CFG))
    info = model.fit(_make_samples(_BOUNDS, second_order_step_response, t, 6))
    return model, info, t


# ─── 裁判自检（#300：裁判先过已知基准） ──────────────────────────────────────

class TestJudgeClosedForm:
    def test_second_order_vs_ivp_three_regimes(self):
        t = np.linspace(0.0, 8.0, 161)
        for wn, zeta in [(2.0, 0.3), (1.5, 1.0), (2.5, 1.4)]:
            def rhs(_t, s, wn=wn, zeta=zeta):
                y, dy = s
                return [dy, wn * wn * (1.0 - y) - 2.0 * zeta * wn * dy]
            sol = solve_ivp(rhs, (0.0, 8.0), [0.0, 0.0], t_eval=t,
                            rtol=1e-11, atol=1e-13)
            err = float(np.max(np.abs(
                sol.y[0] - second_order_step_response(t, wn, zeta))))
            assert err <= 1e-8  # 实测 ≤4.2e-12

    def test_second_order_boundary_values(self):
        t = np.array([0.0, 0.0])
        for zeta in (0.3, 1.0, 1.4):
            assert abs(second_order_step_response(t, 2.0, zeta)[0]) < 1e-14
        tail = second_order_step_response(np.array([200.0]), 2.0, 0.3)[0]
        assert abs(tail - 1.0) < 1e-6
        # 欠阻尼有过冲（>1），过阻尼单调无过冲
        assert second_order_step_response(np.array([1.0]), 2.0, 0.3)[0] > 1.0
        assert second_order_step_response(np.array([1.0]), 2.0, 1.4)[0] < 1.0

    def test_rc_cascade_vs_gammainc(self):
        t = np.linspace(0.0, 8.0, 161)
        for tau, n in [(1.0, 1), (0.7, 2), (1.3, 3), (2.0, 5)]:
            err = float(np.max(np.abs(
                gammainc(n, t / tau) - rc_cascade_step_response(t, tau, n))))
            assert err <= 1e-12  # 实测 ≤3.9e-16
        assert rc_cascade_step_response(np.array([1.0]), 1.0, 1)[0] == pytest.approx(
            1.0 - np.exp(-1.0), abs=1e-14)

    def test_judge_negatives(self):
        t = np.array([0.0, 1.0])
        with pytest.raises(ValueError):
            second_order_step_response(t, 0.0, 0.5)
        with pytest.raises(ValueError):
            second_order_step_response(t, 2.0, 0.0)
        with pytest.raises(ValueError):
            rc_cascade_step_response(t, 0.0, 1)
        with pytest.raises(ValueError):
            rc_cascade_step_response(t, 1.0, 0)


# ─── CfC 单元性质锚（Eq.(10) 推论） ─────────────────────────────────────────

class TestCfcCellAnchors:
    def test_gate_at_dt_zero_is_exactly_half(self):
        f = np.array([-3.0, -0.5, 0.0, 0.5, 3.0])
        assert np.array_equal(cfc_time_gate(f, 0.0), np.full(5, 0.5))

    def test_gate_monotone_decay_for_positive_f(self):
        f = np.full(6, 2.0)
        s = cfc_time_gate(f, np.array([0.0, 1.0, 2.0, 4.0, 8.0, 16.0]))
        assert np.all(np.diff(s) < 0.0)
        assert s[-1] < 1e-12

    def test_large_dt_positive_f_collapses_to_h_bitwise(self):
        net = CfcNet(n_in=1, hidden=4, backbone=5, seed=1)
        net.bf[:] = 2.0  # f>0 保证
        x = np.random.default_rng(0).uniform(-1.0, 1.0, (2, 4))
        theta = np.array([[0.3], [0.9]])
        x_next, (_, _, _, h, _) = net.step(x, theta, 1e3)
        assert np.array_equal(x_next, h)  # 实测逐位相等

    def test_state_bounded(self):
        net = CfcNet(n_in=2, hidden=8, backbone=10, seed=3)
        rng = np.random.default_rng(4)
        x = rng.uniform(-1.0, 1.0, (16, 8))
        theta = rng.uniform(-2.0, 3.0, (16, 2))  # 凸包外值也须有界
        x_next, _ = net.step(x, theta, 2.5)
        assert float(np.max(np.abs(x_next))) <= 1.0

    def test_net_init_determinism(self):
        a = CfcNet(2, 4, 6, 11)
        b = CfcNet(2, 4, 6, 11)
        c = CfcNet(2, 4, 6, 12)
        for pa, pb in zip(a.params, b.params, strict=True):
            assert np.array_equal(pa, pb)
        assert any(not np.array_equal(pa, pc)
                   for pa, pc in zip(a.params, c.params, strict=True))
        assert a.n_params == b.n_params > 0


# ─── BPTT 梯度裁判（#118） ──────────────────────────────────────────────────

class TestGradBPTT:
    def test_analytic_grads_match_central_difference(self):
        rng = np.random.default_rng(3)
        net = CfcNet(n_in=2, hidden=3, backbone=4, seed=7)
        theta = rng.uniform(-0.2, 1.2, (3, 2))
        y = rng.normal(0.0, 1.0, (3, 6))
        dt = np.array([1.0, 0.5, 1.5, 1.0, 0.8])
        wd = 1e-3
        _, grads = net.loss_and_grads(theta, y, dt, wd)
        eps = 1e-6
        for _name, p, g in zip(CfcNet._KEYS, net.params, grads, strict=True):
            num = np.zeros_like(p)
            it = np.nditer(p, flags=["multi_index"])
            while not it.finished:
                idx = it.multi_index
                old = float(p[idx])
                p[idx] = old + eps
                lp, _ = net.loss_and_grads(theta, y, dt, wd)
                p[idx] = old - eps
                lm, _ = net.loss_and_grads(theta, y, dt, wd)
                p[idx] = old
                num[idx] = (lp - lm) / (2 * eps)
                it.iternext()
            assert float(np.max(np.abs(num - g))) <= 1e-6  # 实测 2.95e-10

    def test_dt_vector_length_negative(self):
        net = CfcNet(1, 2, 3, 0)
        theta = np.zeros((1, 1))
        with pytest.raises(ValueError):
            net.forward(theta, 4, np.array([1.0, 2.0]))

    def test_clip_global_norm_scales_only_when_exceeded(self):
        grads = [np.array([3.0, 4.0]), np.array([0.0])]
        assert _clip_global_norm(grads, 10.0) == pytest.approx(5.0)
        assert grads[0][0] == pytest.approx(3.0)  # 未超阈不缩放
        assert _clip_global_norm(grads, 1.0) == pytest.approx(5.0)
        assert float(np.linalg.norm(grads[0])) == pytest.approx(1.0)


# ─── 已知锚 / 泛化 / OOD（降档配置，门=探针冻结） ────────────────────────────

class TestAnchorGeneralizationOod:
    def test_fit_info_shape_pins(self, fitted):
        _, info, _ = fitted
        assert info["kind"] == "lnn_cfc"
        assert info["n_samples"] == 36
        assert info["n_steps"] == 48
        assert info["n_params"] == 1309  # 计数钉 d=2,H=12,B=24
        assert info["hidden"] == 12 and info["backbone"] == 24
        assert info["epochs"] == 600 and info["seed"] == DEFAULT_LNN_SEED
        assert info["dt_strides"] == [1]
        assert info["grad_clip"] == 10.0
        assert info["loss_initial"] > 0.0 and info["loss_final"] > 0.0
        assert 0.0 < info["train_rmse"] <= 0.03  # 冻结：实测 0.0107
        assert info["constant_target"] is False
        assert info["dt_train_s"] == pytest.approx(8.0 / 47)

    def test_anchor_train_grid(self, fitted):
        model, _, t = fitted
        errs = [_rmse(model.predict_curve(s["params"])["response"],
                      s["metrics"]["response_curve"])
                for s in _make_samples(_BOUNDS, second_order_step_response, t, 6)]
        assert float(np.mean(errs)) <= 0.03  # 冻结：实测 0.0107
        assert float(np.max(errs)) <= 0.05  # 冻结：实测 max 0.0216（同档 probe）

    def test_interpolation_in_box(self, fitted):
        model, _, t = fitted
        rng = np.random.default_rng(5)
        errs = []
        for _ in range(30):
            wn, z = rng.uniform(1.0, 3.0), rng.uniform(0.3, 1.2)
            errs.append(_rmse(model.predict_curve({"wn": wn, "zeta": z})["response"],
                              second_order_step_response(t, wn, z)))
        assert float(np.mean(errs)) <= 0.02  # 冻结：实测 0.0079
        assert float(np.max(errs)) <= 0.05  # 冻结：实测 0.0138

    def test_ood_param_wn_extrapolation(self, fitted):
        model, _, t = fitted
        rng = np.random.default_rng(6)
        errs = []
        for _ in range(30):
            wn, z = rng.uniform(3.0, 3.6), rng.uniform(0.3, 1.2)
            errs.append(_rmse(model.predict_curve({"wn": wn, "zeta": z})["response"],
                              second_order_step_response(t, wn, z)))
        assert float(np.mean(errs)) <= 0.05  # 冻结：实测 0.0128

    def test_ood_time_extrapolation_same_dt(self, fitted):
        model, info, _ = fitted
        dt = float(info["dt_train_s"])
        n_ext = 48 + 24  # 同 Δt 多滚 24 步 → t_end = 8 + 24·Δt ≈ 12.09
        t_end = 8.0 + 24 * dt
        t_ext = np.linspace(0.0, t_end, n_ext)
        rng = np.random.default_rng(5)
        errs = []
        for _ in range(30):
            wn, z = rng.uniform(1.0, 3.0), rng.uniform(0.3, 1.2)
            pred = np.asarray(model.predict_curve(
                {"wn": wn, "zeta": z}, n_points=n_ext, t_end=t_end)["response"])
            truth = second_order_step_response(t_ext, wn, z)
            errs.append(_rmse(pred[48:], truth[48:]))  # 只评外推段
        assert float(np.mean(errs)) <= 0.03  # 冻结：实测 0.0047
        assert t_end == pytest.approx(12.0851, abs=0.01)

    def test_fine_grid_out_of_envelope_honest_pin(self, fitted):
        """细网格 Δt_unit<1 是结构性已知边界（BENCH FAIL 行）——只钉
        「仍可调用、返回形状正确」，不设精度门（#122 如实不凑绿）。"""
        model, _, _t = fitted
        t_fine = np.linspace(0.0, 8.0, 95)
        out = model.predict_curve({"wn": 2.0, "zeta": 0.6}, n_points=95)
        assert len(out["response"]) == 95
        truth = second_order_step_response(t_fine, 2.0, 0.6)
        # 包络外：劣化实测 ~20×（BENCH），此处只断言有限且形状正确
        assert np.all(np.isfinite(out["response"]))
        assert _rmse(out["response"], truth) > 0.0  # 占位：非退化调用

    def test_rc_cascade_family_anchor(self):
        t = np.linspace(0.0, 8.0, 32)
        bounds_b = {"wn": (0.5, 2.0), "zeta": (1.0, 3.0)}  # 键名复用 τ/N 面
        samples = [{"params": {"wn": float(tau), "zeta": float(n)},
                    "metrics": {"response_curve":
                                rc_cascade_step_response(t, tau, int(n)).tolist()}}
                   for tau in np.linspace(0.5, 2.0, 8) for n in (1.0, 2.0, 3.0)]
        model = LnnCfcSurrogate(config={
            "bounds": bounds_b, "time_grid": [0.0, 8.0], "curve_samples": 32,
            "hidden": 12, "backbone": 24, "epochs": 600, "lr": 5e-3,
            "seed": DEFAULT_LNN_SEED})
        info = model.fit(samples)
        assert info["train_rmse"] <= 0.03  # 冻结：BENCH Family A/B 同量级
        rng = np.random.default_rng(8)
        errs = []
        for _ in range(20):
            tau, n = rng.uniform(0.5, 2.0), float(rng.integers(1, 4))
            errs.append(_rmse(
                model.predict_curve({"wn": tau, "zeta": n})["response"],
                rc_cascade_step_response(t, tau, int(n))))
        assert float(np.mean(errs)) <= 0.03  # 冻结：BENCH interp 0.0055 同档


# ─── 确定性（红线） ─────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_seed_bitwise_and_different_seed_differs(self):
        t = np.linspace(0.0, 8.0, 48)
        samples = _make_samples(_BOUNDS, second_order_step_response, t, 4)
        a = LnnCfcSurrogate(config=dict(_CFG))
        b = LnnCfcSurrogate(config=dict(_CFG))
        c = LnnCfcSurrogate(config=dict(_CFG, seed=7))
        a.fit(samples)
        b.fit(samples)
        c.fit(samples)
        p1 = a.predict_curve({"wn": 2.2, "zeta": 0.6})["response"]
        p2 = b.predict_curve({"wn": 2.2, "zeta": 0.6})["response"]
        p3 = c.predict_curve({"wn": 2.2, "zeta": 0.6})["response"]
        assert p1 == p2  # 逐位
        assert p1 != p3

    def test_multirate_deterministic(self):
        t = np.linspace(0.0, 8.0, 48)
        samples = _make_samples(_BOUNDS, second_order_step_response, t, 4)
        cfg = dict(_CFG, dt_strides=(1, 2))
        a = LnnCfcSurrogate(config=cfg)
        b = LnnCfcSurrogate(config=cfg)
        ia = a.fit(samples)
        b.fit(samples)
        assert ia["dt_strides"] == [1, 2]
        assert (a.predict_curve({"wn": 1.8, "zeta": 0.9})["response"]
                == b.predict_curve({"wn": 1.8, "zeta": 0.9})["response"])
        assert np.isfinite(ia["loss_final"])


# ─── 负例契约（验收④） ─────────────────────────────────────────────────────

class TestNegatives:
    def _base(self, **over):
        cfg = dict(_CFG, epochs=1)
        cfg.update(over)
        return cfg

    def _samples(self, n: int = 4):
        t = np.linspace(0.0, 8.0, 48)
        return _make_samples(_BOUNDS, second_order_step_response, t, n)

    @pytest.mark.parametrize("over", [
        {"curve_samples": 1}, {"hidden": 0}, {"backbone": 0}, {"epochs": 0},
        {"lr": 0.0}, {"lr": float("nan")}, {"weight_decay": -1e-3},
        {"grad_clip": 0.0}, {"grad_clip": -1.0},
        {"dt_strides": (0,)}, {"dt_strides": (1.5,)}, {"dt_strides": (48,)},
        {"dt_strides": ()},
    ])
    def test_bad_config_raises(self, over):
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=self._base(**over)).fit(self._samples())

    def test_empty_samples_and_missing_bounds_and_time_grid(self):
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=dict(_CFG)).fit([])
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config={k: v for k, v in _CFG.items()
                                    if k != "bounds"}).fit(self._samples())
        for tg in (None, [0.0], [8.0, 0.0]):
            cfg = {k: v for k, v in _CFG.items() if k != "time_grid"}
            if tg is not None:
                cfg["time_grid"] = tg
            with pytest.raises(ValueError):
                LnnCfcSurrogate(config=cfg).fit(self._samples())

    def test_curve_validation(self):
        t = np.linspace(0.0, 8.0, 48)
        good = {"params": {"wn": 2.0, "zeta": 0.5},
                "metrics": {"response_curve": second_order_step_response(t, 2.0, 0.5).tolist()}}
        # 非一维
        bad2d = {"params": dict(good["params"]),
                 "metrics": {"response_curve": [[0.0, 1.0]]}}
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=dict(_CFG, epochs=1)).fit([good, bad2d])
        # 空轨迹
        bad_empty = {"params": dict(good["params"]),
                     "metrics": {"response_curve": [0.5]}}
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=dict(_CFG, epochs=1)).fit([good, bad_empty])
        # 非有限
        bad_nan = {"params": dict(good["params"]),
                   "metrics": {"response_curve":
                               [*second_order_step_response(t, 2.0, 0.5).tolist()[:10], float("nan")]}}
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=dict(_CFG, epochs=1)).fit([good, bad_nan])
        # 有效轨迹 <2（缺键样本如实跳过计数）
        only_one = [{"params": {"wn": 2.0, "zeta": 0.5},
                     "metrics": {"other_key": 1.0}}]
        with pytest.raises(ValueError):
            LnnCfcSurrogate(config=dict(_CFG, epochs=1)).fit([good, *only_one])

    def test_predict_before_fit_and_predict_curve_negatives(self):
        model = LnnCfcSurrogate(config=dict(_CFG))
        with pytest.raises(RuntimeError):
            model.predict({"wn": 2.0, "zeta": 0.5})
        with pytest.raises(RuntimeError):
            model.predict_curve({"wn": 2.0, "zeta": 0.5})
        model.fit(self._samples())
        with pytest.raises(ValueError):
            model.predict_curve({"wn": 2.0, "zeta": 0.5}, n_points=1)
        # t0=0：t_end≤0 非法（含 0.0）；窗内/窗外正值（8.0=训练终点、4.0 窗内）合法
        with pytest.raises(ValueError):
            model.predict_curve({"wn": 2.0, "zeta": 0.5}, t_end=0.0)
        with pytest.raises(ValueError):
            model.predict_curve({"wn": 2.0, "zeta": 0.5}, t_end=-1.0)
        assert len(model.predict_curve({"wn": 2.0, "zeta": 0.5}, t_end=4.0)["response"]) == 48
        with pytest.raises(ValueError):
            model.predict({"wn": float("nan"), "zeta": 0.5})

    def test_predict_curve_t_end_below_t0(self):
        model = LnnCfcSurrogate(config=dict(_CFG))
        model.fit(self._samples())
        with pytest.raises(ValueError):
            model.predict_curve({"wn": 2.0, "zeta": 0.5}, t_end=-1.0)


# ─── 契约面（验收⑤存在性半边） ─────────────────────────────────────────────

class TestContract:
    def test_registry_and_facade(self):
        assert "lnn_cfc" in surrogate_registry.available()
        assert LnnCfcSurrogate.KIND == "lnn_cfc"
        assert surr_pkg.LnnCfcSurrogate is LnnCfcSurrogate
        assert surr_pkg.CfcNet is CfcNet
        for name in ("DEFAULT_LNN_SEED", "CfcNet", "LnnCfcSurrogate",
                     "cfc_time_gate", "rc_cascade_step_response",
                     "second_order_step_response"):
            assert name in surr_pkg.__all__

    def test_existing_kinds_untouched(self):
        kinds = surrogate_registry.available()
        for legacy in ("svgp", "rff_gp", "nn", "poly_ridge", "smt_kriging",
                       "fno_lite", "vf_parametric", "pole_residue"):
            assert legacy in kinds

    def test_predict_summary_matches_curve_stats(self, fitted):
        model, _, _ = fitted
        params = {"wn": 2.4, "zeta": 0.9}
        curve = np.asarray(model.predict_curve(params)["response"])
        summary = model.predict(params)
        assert set(summary) == {"response_curve_final", "response_curve_max",
                                "response_curve_min"}
        assert summary["response_curve_final"] == pytest.approx(float(curve[-1]))
        assert summary["response_curve_max"] == pytest.approx(float(curve.max()))
        assert summary["response_curve_min"] == pytest.approx(float(curve.min()))
        assert model.uncertainty(params) is None
        pw = model.predict_with_std(params)
        assert pw["response_curve_final"][1] is None  # 如实 std=None
