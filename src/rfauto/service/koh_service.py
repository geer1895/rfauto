"""koh_service：Kennedy–O'Hagan 模型偏差校准（阶段 6.1 首片 → D10 补强）。

p0 A/B 实证"标量锚不改善排序"——因为 fake 与 openEMS 的差异是模型结构
失配（discrepancy）而非参数错。KOH（Kennedy-O'Hagan, JRSS-B 2001）的
正解是把差异建成高斯过程 δ(x)。

三级能力（确定性内核、零新依赖，AGENTS 铁律 7）：

1. fit_discrepancy（首片，返回契约保持不变）：δ(x) ≈ GP 拟合的
   (openEMS metrics − fake metrics)(x)（real−fake，KOH 口径，与
   KOHCalibrator 的 δ=y−ρ·η 同号），即 ρ≡1 的可加偏差特例。
2. KOHCalibrator（D10 补强，完整 KOH）：

       z(x) = ρ·η(x) + δ(x) + ε

   - η(x)：仿真器（fake/openEMS）输出，由 eta_fn 提供；
   - ρ：确定性最小二乘标定因子（含截距 OLS 斜率；η 方差≈0 时退化为
     均值比，仍不可用则取 1.0）；
   - δ(x)：SMTKrigingSurrogate 对残差 y − ρ·η 的 GP 后验；样本少于
     min_gp_points 时退化为低阶多项式 + 先验宽度，并显式置
     gp_fitted=False（不假装有强证据）；
   - ε：观测噪声方差 noise_var（默认 0 = 确定性假设）；
   - 95% 区间：mean ± Z95·sqrt(δ 后验方差 + noise_var)，interval_coverage
     给出区间覆盖率指标。注意其区间是"GP 点估计 + 距离膨胀项"的建模
     选择，不是贝叶斯后验——真后验见第 3 档。
3. KOHMCMCPosterior（XD-12，全贝叶斯档）：模型同上，但对标定参数
   θ=(ρ, log a, log ℓ₁..ℓ_d) 做固定 seed 的 Metropolis-Hastings 后验
   采样（r=y−ρη 对 δ-GP 先验解析边缘化，KOH 2001 §2.2 口径），预测点
   出后验混合 predictive 的 u95 区间——替换档 2 的"距离膨胀"近似。
   MCMC 是经验近似（accept_rate 如实透出），seed 固定同输入逐位可复现
   （C4）。

真实数据应用见 scripts/koh_calibrate.py（产物 runs/koh_calibration/）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["DELTA_CONVENTION", "DELTA_CONVENTION_SINCE", "Z95", "KOHCalibrator",
           "KOHMCMCPosterior", "estimate_rho", "fit_discrepancy"]

#: 95% 正态分位（确定性常量；不额外引入 scipy 依赖）
Z95 = 1.959963984540054

#: δ 符号口径（P2⑩ 机器可读登记）：real−fake（KOH 口径，正 δ=仿真器低估观测）。
#: 切换时点=commit 2d68012（2026-09-13）：**只涉 fit_discrepancy 分支**——该
#: 分支此前实现为 fake−real（与模块头旧文案一致、与 KOH 口径相反）；
#: KOHCalibrator 分支 δ=y−ρ·η 自 D10 补强起一直是 KOH 口径，不受翻转影响。
#: 消费历史产物时：早于该时点且出自 fit_discrepancy 的 δ 需反号解读；
#: 出自 KOHCalibrator 的无需反号。
DELTA_CONVENTION = "real_minus_fake"
DELTA_CONVENTION_SINCE = "2026-09-13 commit 2d68012"


def estimate_rho(eta: Any, y: Any) -> float:
    """确定性 LS 标定因子 ρ（y ≈ ρ·η）：含截距 OLS 斜率。

    η 方差 ≈ 0（仿真器在该设计点输出恒定）时退化为均值比 mean(y)/mean(η)；
    均值比仍不可用（mean(η)≈0）时返回 1.0（无信息 → 不硬造标定因子）。
    """
    e = np.asarray(eta, dtype=float)
    obs = np.asarray(y, dtype=float)
    mask = np.isfinite(e) & np.isfinite(obs)
    e, obs = e[mask], obs[mask]
    if e.size < 2:
        return 1.0
    em, ym = float(e.mean()), float(obs.mean())
    denom = float(((e - em) ** 2).sum())
    if denom <= 1e-12:
        return float(ym / em) if abs(em) > 1e-12 else 1.0
    return float((((e - em) * (obs - ym)).sum()) / denom)


class KOHCalibrator:
    """Kennedy–O'Hagan 标定器：z(x) = ρ·η(x) + δ(x) + ε（确定性估计）。

    参数
    ----
    bounds : dict[str, tuple[float, float]]
        δ 的 GP 输入归一化基准（与 SMTKrigingSurrogate 同口径）。
    eta_fn : Callable[[dict[str, float]], float] | None
        仿真器函数；predict 未显式给 eta 时用它取 η。
    theta0 : float
        KRG 初始长度尺度（确定性，不做随机重启）。
    noise_var : float
        观测噪声方差 ε；默认 0.0（确定性假设，区间只反映 δ 后验方差）。
    prior_var : float | None
        δ 的先验方差；None = 用训练残差的样本方差（ddof=1）。
    z95 : float
        区间分位（默认 1.959963984540054 = 标准正态 95%）。
    min_gp_points : int
        低于该样本数不拟合 SMT KRG（KRG 逐指标需 ≥3 点），走显式退化路径。

    预测语义（纯函数、同参同输出，可复现红线 C4）：拟合后 predict 只读
    已训练状态，不再优化/采样。
    """

    KIND = "koh"

    def __init__(
        self,
        *,
        bounds: dict[str, tuple[float, float]],
        eta_fn: Callable[[dict[str, float]], float] | None = None,
        theta0: float = 1e-1,
        noise_var: float = 0.0,
        prior_var: float | None = None,
        z95: float = Z95,
        min_gp_points: int = 3,
    ) -> None:
        self.bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
        if not self.bounds:
            raise ValueError("bounds 不能为空（KOH 的 δ GP 需归一化基准）")
        self.names = sorted(self.bounds)
        self.eta_fn = eta_fn
        self.theta0 = float(theta0)
        self.noise_var = max(float(noise_var), 0.0)
        self.prior_var = None if prior_var is None else max(float(prior_var), 0.0)
        self.z95 = float(z95)
        self.min_gp_points = int(min_gp_points)
        self.rho = 1.0
        self.n_obs = 0
        self.fitted = False
        self.gp_fitted = False
        self._gp: Any = None
        self._coef: np.ndarray | None = None
        self._train_units: np.ndarray | None = None

    # ------------------------------------------------------------------ 内部
    def _raw_unit(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            (float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)
        ])

    def _unit(self, params: dict[str, float]) -> np.ndarray:
        return np.clip(self._raw_unit(params), 0.0, 1.0)

    def _dist(self, params: dict[str, float]) -> float:
        """归一化坐标下到最近训练点的欧氏距离（可 >1 = 外推）。"""
        assert self._train_units is not None
        return float(np.min(np.linalg.norm(self._train_units - self._raw_unit(params),
                                           axis=1)))

    def _delta_mean_var(self, params: dict[str, float]) -> tuple[float, float]:
        dist = self._dist(params)
        if self.gp_fitted:
            mean = float(self._gp.predict(params)["delta"])
            var = float(self._gp.uncertainty(params)["delta"]) ** 2
            # 无噪声 KRG 是精确插值：训练张成域内后验方差≈0（SMT 实测
            # ~1e-13）。为不给出过度自信区间，叠加显式的确定性膨胀项
            # prior_var·d²（d=归一化到最近训练点的距离）；这是明确标注的
            # 建模选择，不是"真实"贝叶斯后验（不做 MCMC）。
            var += float(self.prior_var) * dist ** 2
            return mean, max(var, 0.0)
        # 退化路径（样本 < min_gp_points）：低阶多项式均值 + 先验宽度
        u = self._unit(params)
        assert self._coef is not None
        mean = (float(self._coef[0]) if self._coef.size == 1
                else float(self._coef[0] + self._coef[1:] @ u))
        return mean, float(self.prior_var) * (1.0 + dist) ** 2

    # ------------------------------------------------------------------ 拟合
    def fit(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        """用 (params, eta, y) 观测拟合 KOH；返回 JSON 友好摘要。

        observations：[{"params": {...}, "eta": float, "y": float}, ...]。
        非有限值/缺字段的条目被忽略（对应真机失败 trial 的既有约定）。
        """
        obs: list[dict[str, Any]] = []
        for item in observations:
            if not isinstance(item, dict) or not isinstance(item.get("params"), dict):
                continue
            try:
                eta = float(item["eta"])
                y = float(item["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (np.isfinite(eta) and np.isfinite(y)):
                continue
            obs.append({"params": dict(item["params"]), "eta": eta, "y": y})
        if len(obs) < 2:
            return error_envelope(["KOH 标定需 ≥2 个 (params, eta, y) 有效观测"])

        eta_arr = np.array([o["eta"] for o in obs], dtype=float)
        y_arr = np.array([o["y"] for o in obs], dtype=float)
        self.rho = estimate_rho(eta_arr, y_arr)
        delta = y_arr - self.rho * eta_arr
        self.n_obs = len(obs)
        if self.prior_var is None:
            self.prior_var = (float(np.var(delta, ddof=1))
                              if delta.size > 1 else 0.0)
        self.prior_var = max(float(self.prior_var), 1e-12)
        self._train_units = np.array([self._unit(o["params"]) for o in obs])

        self.gp_fitted = False
        self._gp = None
        self._coef = None
        if len(obs) >= self.min_gp_points:
            from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

            gp = SMTKrigingSurrogate(config={
                "bounds": self.bounds, "theta0": self.theta0,
                "metrics": ["delta"]})
            gp.fit([{"params": o["params"], "metrics": {"delta": float(d)}}
                    for o, d in zip(obs, delta, strict=True)])
            if "delta" in getattr(gp, "models", {}):
                self._gp = gp
                self.gp_fitted = True
        if not self.gp_fitted:
            # 退化：阶数 min(1, n-1) 的多项式（n=2 → 过两点直线）
            design = np.hstack([np.ones((len(obs), 1)), self._train_units])
            if len(obs) < 2:
                self._coef = np.array([float(delta.mean())])
            else:
                coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
                self._coef = np.asarray(coef, dtype=float)

        self.fitted = True
        return ok_envelope(
            kind=self.KIND,
            n_obs=self.n_obs,
            rho=float(self.rho),
            gp_fitted=bool(self.gp_fitted),
            prior_var=float(self.prior_var),
            noise_var=float(self.noise_var),
            theta0=float(self.theta0),
            delta_train=[float(d) for d in delta],
        )

    # ------------------------------------------------------------------ 预测
    def predict(
        self, params: dict[str, float], eta: float | None = None,
    ) -> dict[str, float]:
        """预测 z(x)：返回 {mean, lo95, hi95, sigma, eta, delta, rho}。

        eta 缺省用构造时注入的 eta_fn(params)；两者都没有则显式报错，
        不静默降级（AGENTS 数值纪律）。
        """
        if not self.fitted:
            raise RuntimeError("KOHCalibrator 未拟合，先调用 fit()")
        if eta is None:
            if self.eta_fn is None:
                raise ValueError("predict 需要 eta，或构造时提供 eta_fn")
            eta = float(self.eta_fn(params))
        eta = float(eta)
        delta_mean, delta_var = self._delta_mean_var(params)
        mean = self.rho * eta + delta_mean
        sigma = float(np.sqrt(max(delta_var + self.noise_var, 0.0)))
        return {
            "mean": float(mean),
            "lo95": float(mean - self.z95 * sigma),
            "hi95": float(mean + self.z95 * sigma),
            "sigma": sigma,
            "eta": eta,
            "delta": float(delta_mean),
            "rho": float(self.rho),
        }

    def interval_coverage(self, points: list[dict[str, Any]]) -> dict[str, Any]:
        """区间覆盖率指标：points=[{params, y, eta?}] → {n, covered, coverage,
        n_skipped_no_eta}。

        缺 eta 且构造时无 eta_fn 的点逐点跳过（predict 的显式报错契约
        保持，本层只做统计面容错），计入 n_skipped_no_eta，不炸穿整批
        统计也不静默丢数。
        """
        n = 0
        covered = 0
        n_skipped_no_eta = 0
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("params"), dict):
                continue
            try:
                y = float(point["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if not np.isfinite(y):
                continue
            try:
                pred = self.predict(point["params"], eta=point.get("eta"))
            except ValueError:
                # 缺 eta 且无 eta_fn：跳过并计数（不静默）
                n_skipped_no_eta += 1
                continue
            n += 1
            if pred["lo95"] <= y <= pred["hi95"]:
                covered += 1
        return {"n": n, "covered": covered,
                "coverage": (covered / n) if n else None,
                "n_skipped_no_eta": n_skipped_no_eta}


def fit_discrepancy(
    samples_path: str | Path,
    *,
    model: str = "wilkinson_power_divider",
    fake_sampler: Callable[[dict[str, float]], dict[str, float]] | None = None,
    n_extra_fake: int = 16,
    theta0: float = 1e-1,
    freq_range: tuple[float, float] = (1.5, 3.5),
) -> dict[str, Any]:
    """拟合 openEMS−fake 的 discrepancy GP δ(x)（JSON 契约，real−fake）。

    samples_path：openEMS 真采样样本集（samples.json，含 bounds/objectives）。
    fake_sampler：可选注入（测试）；缺省用 FakeAdapter（零成本、确定性）
    按 samples.json 的 objectives 口径产指标。在 openEMS 采样点 + LHS
    补点处计算残差，逐指标训练 SMT KRG。

    这是完整 KOH（KOHCalibrator）在 ρ≡1、无观测噪声时的可加偏差特例——
    返回键保持不变（向后兼容），需要 ρ 与 95% 区间请用 KOHCalibrator。
    """
    path = Path(samples_path)
    if not path.exists():
        return error_envelope([f"样本集不存在: {path}"])
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = list(data.get("samples") or [])
    objectives = list(data.get("objectives") or [])
    bounds_raw = data.get("bounds") or {}
    if len(samples) < 5:
        return error_envelope(["openEMS 样本点不足（需 ≥5）"])
    if not objectives:
        return error_envelope(["样本集无 objectives，指标键无从对齐"])
    bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds_raw.items()}

    if fake_sampler is None:
        from rfauto.service.calibration_service import _make_sampler, _template_for

        template = _template_for(model)
        raw = _make_sampler("fake", template, tuple(freq_range), objectives,
                            Path("runs") / "koh_fake_work")

        def fake_sampler(params: dict[str, float]) -> dict[str, float]:
            return raw(params)

    # 配对残差：openEMS 点 + LHS 补点（fake 插值倾向处）
    from rfauto.optimization.sample_design import lhs_points

    pts = [dict(s["params"]) for s in samples]
    pts += lhs_points(bounds, n_extra_fake, seed=42,
                      include=pts, min_dist=0.1)["points"]

    residuals: list[dict[str, Any]] = []
    for pt in pts:
        real = next((s["metrics"] for s in samples
                     if s["params"] == pt), None)
        try:
            fake = fake_sampler(pt)
        except Exception:
            continue
        if not real or not fake:
            continue
        # δ 口径统一为 real−fake（KOH 口径，与 KOHCalibrator 的 δ=y−ρ·η
        # 同号）：模块头曾写 fake−real、实现也按 fake−real，与 KOH 口径
        # 相反——统一后"正 δ=仿真器低估观测"全库一致
        delta = {k: float(real[k]) - float(fake[k])
                 for k in real
                 if isinstance(real.get(k), (int, float))
                 and isinstance(fake.get(k), (int, float))}
        if delta:
            residuals.append({"params": pt, "metrics": delta})

    if len(residuals) < 5:
        return error_envelope(["有效配对残差不足"])

    # 逐指标 KRG 拟合 δ(x)（残差样本即"训练集"，契约与代理一致）
    from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

    model_gp = SMTKrigingSurrogate(config={"bounds": bounds, "theta0": theta0})
    model_gp.fit(residuals)

    metric_keys = sorted(model_gp.metric_keys)
    delta_summary: dict[str, dict[str, float]] = {}
    for key in metric_keys:
        vals = np.array([r["metrics"].get(key, np.nan) for r in residuals])
        vals = vals[np.isfinite(vals)]
        if len(vals) >= 3:
            delta_summary[key] = {"min": float(vals.min()),
                                  "max": float(vals.max()),
                                  "mean": float(vals.mean())}

    return {
        "ok": True,
        "samples_path": str(path),
        "model": model,
        "n_pairs": len(residuals),
        "metric_keys": metric_keys,
        "delta_summary": delta_summary,
        "model_kind": model_gp.KIND,
        "gp_fitted": model_gp.fitted,
        # P2⑩ 机器可读口径戳（加性键，既有契约键不变）
        "delta_convention": DELTA_CONVENTION,
        "delta_convention_since": DELTA_CONVENTION_SINCE,
        "note": "δ(x)=openEMS−fake（real−fake，KOH 口径）的 GP 残差；"
                "完整 KOH（ρ + 95% 区间）见 KOHCalibrator。口径切换时点 "
                f"{DELTA_CONVENTION_SINCE}：仅本 fit_discrepancy 分支由 "
                "fake−real 翻转为 real−fake（早于该时点的本分支产物需反号"
                "解读）；KOHCalibrator 分支 δ=y−ρ·η 一直同口径不受影响",
    }


# --------------------------------------------------------------------------- #
# XD-12 全贝叶斯档：固定 seed MH 采样 (ρ, δ-GP 超参) 后验（aurora_e W5-S22）
# --------------------------------------------------------------------------- #

_MCMC_JITTER = 1e-10
#: 预测混合采样的最大使用条数（striding 降采样，防 O(n_samples·n²·n*) 爆炸）
_MAX_PRED_SAMPLES = 200


def _clean_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """(params, eta, y) 观测清洗（与 KOHCalibrator.fit 同约定：非有限/
    缺字段条目忽略——真机失败 trial 的既有口径）。"""
    obs: list[dict[str, Any]] = []
    for item in observations or []:
        if not isinstance(item, dict) or not isinstance(item.get("params"), dict):
            continue
        try:
            eta = float(item["eta"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (np.isfinite(eta) and np.isfinite(y)):
            continue
        obs.append({"params": dict(item["params"]), "eta": eta, "y": y})
    return obs


class KOHMCMCPosterior:
    """XD-12：KOH 全贝叶斯档——固定 seed MH 后验采样（koh_service 扩展）。

    模型（z = ρ·η + δ + ε，δ ~ a²·SE-GP(ℓ)，ε ~ N(0, noise_var)）：

        r_i = y_i − ρ·η(x_i) ~ N(0, K_θ + (noise_var + jitter)·I)

    δ 对 GP 先验**解析边缘化**（KOH 2001 口径），MH 只在
    θ = (ρ, log a, log ℓ₁..ℓ_d) 上游走：

    - 先验：ρ ~ U(rho_box)（宽盒平坦）；log a、log ℓ_i ~ N(m, s²) 弱信息
      （缺省 m=0、s=3，ℓ 在单元空间约 1 附近散开）；
    - 提议：对称高斯步长（缺省按数据尺度自动定标，可 override）；
    - 输入单元归一化（与 KOHCalibrator 同基准，bounds 必填）。

    返回/预测（JSON 友好）：
    - fit → ok_envelope：accept_rate、rho 后验 {mean,lo95,hi95}、采样
      存档（n_samples 条）、empirical 戳（MCMC=经验近似，如实标注）；
    - predict(params, eta?) → {mean, lo95, hi95, sigma, u95, eta, rho}：
      后验混合 predictive（law of total variance 矩匹配），u95=[lo95,hi95]
      即 XC-U 消费面区间。

    确定性：seed 固定 + 同观测 → 链逐位可复现（C4）。诚实边界：MH 是
    经验近似档（无 ESS/R̂ 收敛诊断面板，accept_rate 是唯一健康探针，
    过低/过高时消费方应调 proposal_scales 重跑）。
    """

    KIND = "koh_mcmc"

    def __init__(
        self,
        *,
        bounds: dict[str, tuple[float, float]],
        eta_fn: Callable[[dict[str, float]], float] | None = None,
        noise_var: float = 0.0,
        seed: int = 20261018,
        n_samples: int = 400,
        burn: int = 200,
        thin: int = 2,
        rho_box: tuple[float, float] = (-10.0, 10.0),
        prior_loc: float = 0.0,
        prior_scale: float = 3.0,
        proposal_scales: list[float] | None = None,
        max_pred_samples: int = _MAX_PRED_SAMPLES,
    ) -> None:
        self.bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
        if not self.bounds:
            raise ValueError("bounds 不能为空（δ-GP 需归一化基准）")
        self.names = sorted(self.bounds)
        self.eta_fn = eta_fn
        self.noise_var = max(float(noise_var), 0.0)
        self.seed = int(seed)
        self.n_samples = int(n_samples)
        self.burn = int(burn)
        self.thin = max(int(thin), 1)
        self.rho_box = (float(rho_box[0]), float(rho_box[1]))
        self.prior_loc = float(prior_loc)
        self.prior_scale = max(float(prior_scale), 1e-9)
        self.proposal_scales = (None if proposal_scales is None
                                else [float(s) for s in proposal_scales])
        self.max_pred_samples = int(max_pred_samples)
        self.fitted = False
        self._train_units: np.ndarray | None = None
        self._eta_arr: np.ndarray | None = None
        self._y_arr: np.ndarray | None = None
        self.samples_: np.ndarray | None = None  # (n_samples, 2+d) 采样存档
        self.accept_rate: float | None = None

    # ------------------------------------------------------------------ 内部
    def _unit(self, params: dict[str, float]) -> np.ndarray:
        return np.array([
            np.clip((float(params.get(n, lo)) - lo) / max(hi - lo, 1e-12),
                    0.0, 1.0)
            for n, (lo, hi) in ((n, self.bounds[n]) for n in self.names)])

    def _kmat(self, u: np.ndarray, log_a: float,
              log_ell: np.ndarray) -> np.ndarray:
        from rfauto.optimization.surrogate.gp_det import se_ard_kernel

        k = se_ard_kernel(u, u, np.exp(log_ell), float(np.exp(log_a)))
        k[np.diag_indices(u.shape[0])] += self.noise_var + _MCMC_JITTER
        return k

    def _log_posterior(self, theta: np.ndarray) -> float:
        rho, log_a = float(theta[0]), theta[1]
        log_ell = np.asarray(theta[2:], dtype=float)
        if not (self.rho_box[0] <= rho <= self.rho_box[1]):
            return -np.inf
        assert self._eta_arr is not None and self._y_arr is not None
        r = self._y_arr - rho * self._eta_arr
        k = self._kmat(self._train_units, log_a, log_ell)
        try:
            chol = np.linalg.cholesky(k)
        except np.linalg.LinAlgError:
            return -np.inf
        alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, r))
        loglik = (-0.5 * float(r @ alpha)
                  - float(np.log(np.diag(chol)).sum())
                  - 0.5 * r.size * np.log(2.0 * np.pi))
        s2 = self.prior_scale ** 2
        logprior = (
            -0.5 * float(((theta[1:] - self.prior_loc) ** 2).sum()) / s2)
        return loglik + logprior

    # ------------------------------------------------------------------ 拟合
    def fit(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        """MH 采样后验；observations 契约同 KOHCalibrator.fit。"""
        obs = _clean_observations(observations)
        if len(obs) < 2:
            return error_envelope(
                ["KOH MCMC 标定需 ≥2 个 (params, eta, y) 有效观测"])
        self._eta_arr = np.array([o["eta"] for o in obs], dtype=float)
        self._y_arr = np.array([o["y"] for o in obs], dtype=float)
        self._train_units = np.array([self._unit(o["params"]) for o in obs])
        d = len(self.names)
        y_sd = float(np.std(self._y_arr)) or 1.0
        theta = np.concatenate([
            [float(estimate_rho(self._eta_arr, self._y_arr))],
            [float(np.log(max(
                float(np.std(self._y_arr - np.mean(self._y_arr))), 1e-3)))],
            np.full(d, float(np.log(0.5)))])
        scales = (np.array(self.proposal_scales, dtype=float)
                  if self.proposal_scales is not None else
                  np.concatenate([[0.1 * y_sd, 0.3], np.full(d, 0.3)]))
        if scales.size != theta.size:
            return error_envelope(
                [f"proposal_scales 长度需 = {theta.size}"
                 f"（ρ+log a+log ℓ×{d}）"])
        rng = np.random.default_rng(self.seed)
        lp = self._log_posterior(theta)
        total = self.burn + self.n_samples * self.thin
        kept: list[np.ndarray] = []
        n_accept = 0
        for it in range(total):
            prop = theta + scales * rng.standard_normal(theta.size)
            lp_prop = self._log_posterior(prop)
            if np.isfinite(lp_prop) and (
                    lp_prop >= lp or np.log(rng.random()) < lp_prop - lp):
                theta, lp = prop, lp_prop
                n_accept += 1
            if it >= self.burn and (it - self.burn) % self.thin == 0:
                kept.append(theta.copy())
        self.samples_ = np.array(kept)
        self.accept_rate = n_accept / max(total, 1)
        self.fitted = True
        rho_s = self.samples_[:, 0]
        return ok_envelope(
            kind=self.KIND,
            n_obs=len(obs),
            seed=self.seed,
            n_samples=int(self.samples_.shape[0]),
            burn=self.burn,
            thin=self.thin,
            accept_rate=float(self.accept_rate),
            rho={"mean": float(rho_s.mean()),
                 "lo95": float(np.percentile(rho_s, 2.5)),
                 "hi95": float(np.percentile(rho_s, 97.5))},
            empirical=True,
            note="固定 seed MH 后验（经验近似档，accept_rate 为健康探针）；"
                 "r=y−ρη 对 δ-GP 解析边缘化（KOH 2001）",
        )

    # ------------------------------------------------------------------ 预测
    def predict(
        self, params: dict[str, float], eta: float | None = None,
    ) -> dict[str, float]:
        """后验混合 predictive：u95 区间（XC-U 消费面）+ 与 KOHCalibrator
        同构的 mean/lo95/hi95/sigma 键（delta/rho 为后验均值口径）。"""
        if not self.fitted or self.samples_ is None:
            raise RuntimeError("KOHMCMCPosterior 未拟合，先调用 fit()")
        if eta is None:
            if self.eta_fn is None:
                raise ValueError("predict 需要 eta，或构造时提供 eta_fn")
            eta = float(self.eta_fn(params))
        eta = float(eta)
        u = self._unit(params)[None, :]
        n_s = self.samples_.shape[0]
        idx = np.linspace(0, n_s - 1,
                          min(n_s, self.max_pred_samples)).astype(int)
        from rfauto.optimization.surrogate.gp_det import se_ard_kernel

        means: list[float] = []
        variances: list[float] = []
        assert self._eta_arr is not None and self._y_arr is not None
        for th in self.samples_[idx]:
            rho, log_a = float(th[0]), th[1]
            log_ell = th[2:]
            r = self._y_arr - rho * self._eta_arr
            k = self._kmat(self._train_units, log_a, log_ell)
            chol = np.linalg.cholesky(k)
            alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, r))
            k_st = se_ard_kernel(u, self._train_units, np.exp(log_ell),
                                 float(np.exp(log_a)))
            k_ss = float(se_ard_kernel(u, u, np.exp(log_ell),
                                       float(np.exp(log_a)))[0, 0])
            v = np.linalg.solve(chol, k_st.T)
            m = rho * eta + float((k_st @ alpha)[0])
            var = k_ss - float((v * v).sum(axis=0)[0]) + self.noise_var
            means.append(m)
            variances.append(max(var, 0.0))
        mean = float(np.mean(means))
        var = float(np.mean(variances)) + float(np.var(means))
        sigma = float(np.sqrt(max(var, 0.0)))
        lo = float(mean - Z95 * sigma)
        hi = float(mean + Z95 * sigma)
        rho_s = self.samples_[:, 0]
        return {
            "mean": mean,
            "lo95": lo,
            "hi95": hi,
            "sigma": sigma,
            "u95": [lo, hi],
            "eta": eta,
            "delta": float(mean - rho_s.mean() * eta),
            "rho": float(rho_s.mean()),
        }
