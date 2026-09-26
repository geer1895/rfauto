"""output_sm_service：轻量 output-SM（响应空间 affine 修正 + 信任域，DP-14 N8）。

响应空间修正：corrected = OE 预测 + δ，δ 按头学习——GP 输入是**该头该频的
OE 低保真预测 u**（响应空间键控），而非设计参数 w（与 df5 w 键控 δGP 的
唯一结构差，KOH 简化式同构）。三头：S11 线性 |Γ|（#371 深谷 dB 表示病象
规避）/ S21 dB / εeff 绝对差。每支 = affine LS（含截距 OLS）+ 残差 1-D GP
（squared-exp，surrogate_registry 既有 smt_kriging，零新依赖）——affine
部分使 a+b·u 真值可精确表达（合成回收钉前提），GP 吸收剩余曲率。

信任域：|δ_pred| > (τ/100)·max(|u|, floor_head) 的条目回退到原始 OE 值
（δ=0）并记 warning——修正至多使响应幅值翻倍（τ=100% 预声明，判据见
runs/df6_dp14n8/criteria.md）。参数提取步不实现（已知脆弱点固定结构
规避）；GP 残差守卫（std<1e-9 → affine-only）防 KRG 对零残差产出垃圾值
（实现前探针实证 0.203）。实现无随机源（OLS 闭式 + SMT 单起点 +
确定性线代），"random_state 钉死"等价落实为双跑逐位一致。

基线锚定：runs/df5_mfk_lowfi_fix/anchor15/mfk_verdict_lowfi_fix.json 的
koh_lowfi_direct 臂 held-out |ΔΓ|max = 0.00373（9 锚，只读）。


# ── 终态裁定（2026-09-25，runs/df6_dp14n8/output_sm_eval_verdict.json）────────
# output_sm_verdict = **rejected-inferior**：与 koh 基线（held-out |ΔΓ|=0.00373）
# 同协议对照 0.14101（37.8× 劣，且劣于"纯 OE 直接当预测"0.0875）。归因=该微带
# 族 |Γ| 对 w/频带内近平（1.3% 跨度）而 δ_true 跨 2.6×——响应标量不携带可分辨
# (w,f) 信息，多值映射结构性失败（非可调参缺陷）。按 #122 如实登记弃：本模块
# 不接优化环、不产品化，仅作 LOO 评估 harness 与信任域参考实现存档。
# 信任域回退 22/22 正确拦截（真数据实证）——该机制本身可复用。"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "EXACT_W_TOL",
    "GP_RESID_STD_GUARD",
    "S11_DB_FLOOR",
    "TAU_PCT_DEFAULT",
    "TRUST_FLOOR_DEFAULT",
    "OutputSpaceMapper",
]

#: 信任域宽度（%）：|δ| ≤ τ%·max(|u|, floor) —— 预声明常数，不因真数据调整
TAU_PCT_DEFAULT = 100.0
#: 各头信任域绝对下限（|u|≈0 时的参考尺度，预声明）
TRUST_FLOOR_DEFAULT = {"gamma_lin": 0.01, "s21_db": 0.05, "eps_eff": 0.5}
#: GP 残差守卫：残差 std 低于该值跳过 GP（affine-only），预声明
GP_RESID_STD_GUARD = 1e-9
#: 锚 w 在低保真数据集中精确行匹配容差（嵌套 DoE 前提，不最近邻替代）
EXACT_W_TOL = 1e-9
#: 修正 |Γ| 回写 dB 的线性地板（同 df5 correct_low_rows 口径）
S11_DB_FLOOR = 1e-6
#: SMT KRG 初始长度尺度（归一化单位；df5 L0 同族，单起点确定性）
_THETA0_DEFAULT = 0.3
#: SMT KRG 逐指标最少点数（koh_service 同约定）
_MIN_GP_POINTS = 3

_HEADS = ("gamma_lin", "s21_db", "eps_eff")


def _gamma_lin(s11_db: Any) -> np.ndarray:
    """S11 dB → 线性 |Γ|（消费口径，#371）。"""
    return 10.0 ** (np.asarray(s11_db, dtype=float) / 20.0)


def _stats(diffs: np.ndarray) -> dict[str, float]:
    """与 scripts/factory_m2_mfk_rejudge._stats 同语义（max/mean/n）。"""
    if diffs.size == 0:
        return {"max": float("nan"), "mean": float("nan"), "n": 0}
    return {"max": float(np.max(diffs)), "mean": float(np.mean(diffs)),
            "n": int(diffs.size)}


def find_exact_low_row(low_rows: list[dict[str, Any]], w: float,
                       tol: float = EXACT_W_TOL) -> dict[str, Any] | None:
    """按 w 找精确 OE 行（容差 tol）；缺失返回 None（不最近邻替代）。"""
    hits = [r for r in low_rows if abs(float(r["w"]) - float(w)) <= tol]
    return hits[0] if hits else None


class _Branch:
    """单支修正模型（一个头 × 一个频点；εeff 头为单支 index=-1）。

    δ(u) = a + b·u + GP_residual(u)；GP 残差守卫：std(resid) < guard 或
    样本 < 3 或 u 零跨度 → 不拟合 GP（affine-only，如实计数）。
    """

    def __init__(self, head: str, index: int) -> None:
        self.head = head
        self.index = index
        self.a = 0.0
        self.b = 0.0
        self.u_lo = 0.0
        self.u_hi = 0.0
        self.gp: Any = None
        self.gp_fitted = False
        self.resid_std = 0.0

    def fit(self, u: np.ndarray, delta: np.ndarray, *, theta0: float,
            resid_guard: float) -> None:
        mask = np.isfinite(u) & np.isfinite(delta)
        u, delta = u[mask], delta[mask]
        um, dm = float(u.mean()), float(delta.mean())
        denom = float(((u - um) ** 2).sum())
        self.b = float(((u - um) * (delta - dm)).sum() / denom) if denom > 0.0 else 0.0
        self.a = dm - self.b * um
        self.u_lo, self.u_hi = float(u.min()), float(u.max())
        resid = delta - (self.a + self.b * u)
        self.resid_std = float(np.std(resid))
        if (u.size < _MIN_GP_POINTS or self.u_hi - self.u_lo <= 0.0
                or self.resid_std < resid_guard):
            return  # affine-only（守卫路径，summary 如实计数）
        from rfauto.optimization.surrogate.smt_kriging import SMTKrigingSurrogate

        gp = SMTKrigingSurrogate(config={
            "bounds": {"u": (self.u_lo, self.u_hi)},
            "theta0": theta0, "metrics": ["r"]})
        gp.fit([{"params": {"u": float(x)}, "metrics": {"r": float(r)}}
                for x, r in zip(u, resid, strict=True)])
        if "r" in getattr(gp, "models", {}):
            self.gp = gp
            self.gp_fitted = True

    def predict_delta(self, u_val: float) -> float:
        d = self.a + self.b * float(u_val)
        if self.gp is not None:
            d += float(self.gp.predict({"u": float(u_val)})["r"])
        return float(d)


class OutputSpaceMapper:
    """轻量 output-SM：响应空间 affine 修正 + 信任域（fit/predict/evaluate）。

    参数（预声明默认见模块头）：tau_pct / floors / theta0 /
    gp_resid_std_guard。fit 后 predict 只读已训练状态（纯函数语义，
    可复现红线 C4）。
    """

    HEADS = _HEADS

    def __init__(self, *, tau_pct: float = TAU_PCT_DEFAULT,
                 floors: dict[str, float] | None = None,
                 theta0: float = _THETA0_DEFAULT,
                 gp_resid_std_guard: float = GP_RESID_STD_GUARD) -> None:
        self.tau_pct = max(float(tau_pct), 0.0)
        self.floors = {**TRUST_FLOOR_DEFAULT,
                       **{k: float(v) for k, v in (floors or {}).items()}}
        self.theta0 = float(theta0)
        self.gp_resid_std_guard = float(gp_resid_std_guard)
        self.fitted = False
        self.branches: dict[tuple[str, int], _Branch] = {}
        self.fit_summary: dict[str, Any] = {}

    # ---------------------------------------------------------------- 拟合
    def fit(self, anchor_rows: list[dict[str, Any]],
            low_rows: list[dict[str, Any]], freqs: np.ndarray) -> dict[str, Any]:
        """用 (HFSS 锚, 精确 OE 行) 配对拟合逐头逐频修正支；返回摘要。

        anchor_rows/low_rows 行形态：{w, s11_db[n_f], s21_db[n_f],
        eps_eff, ...}（与 datafactory 行同构）。锚 w 无精确 OE 行 →
        ValueError（嵌套 DoE 前提，拒绝静默最近邻）。
        """
        n_f = len(freqs)
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for t in anchor_rows:
            oe = find_exact_low_row(low_rows, float(t["w"]))
            if oe is None:
                raise ValueError(
                    f"锚 w={float(t['w'])!r} 在低保真数据集中无精确行"
                    f"（tol={EXACT_W_TOL}）——嵌套 DoE 前提破坏，拒绝最近邻替代")
            pairs.append((t, oe))
        if len(pairs) < 2:
            raise ValueError("output-SM 拟合需 ≥2 个锚点")
        u_mat: dict[str, list[np.ndarray]] = {h: [] for h in _HEADS}
        d_mat: dict[str, list[np.ndarray]] = {h: [] for h in _HEADS}
        for t, oe in pairs:
            g_hi, g_lo = _gamma_lin(t["s11_db"]), _gamma_lin(oe["s11_db"])
            s21_hi = np.asarray(t["s21_db"], dtype=float)
            s21_lo = np.asarray(oe["s21_db"], dtype=float)
            u_mat["gamma_lin"].append(g_lo)
            d_mat["gamma_lin"].append(g_hi - g_lo)
            u_mat["s21_db"].append(s21_lo)
            d_mat["s21_db"].append(s21_hi - s21_lo)
            u_mat["eps_eff"].append(np.array([float(oe["eps_eff"])]))
            d_mat["eps_eff"].append(
                np.array([float(t["eps_eff"]) - float(oe["eps_eff"])]))
        self.branches = {}
        gp_counts = {h: 0 for h in _HEADS}
        affine_only = {h: 0 for h in _HEADS}
        resid_std_max = {h: 0.0 for h in _HEADS}
        train_delta_absmax = {h: 0.0 for h in _HEADS}
        train_over_limit = {h: 0 for h in _HEADS}
        for head in _HEADS:
            u_all = np.vstack(u_mat[head])
            d_all = np.vstack(d_mat[head])
            n_branch = u_all.shape[1]
            train_delta_absmax[head] = float(np.abs(d_all).max())
            for j in range(n_branch):
                br = _Branch(head, j)
                br.fit(u_all[:, j], d_all[:, j], theta0=self.theta0,
                       resid_guard=self.gp_resid_std_guard)
                self.branches[(head, j)] = br
                resid_std_max[head] = max(resid_std_max[head], br.resid_std)
                if br.gp_fitted:
                    gp_counts[head] += 1
                else:
                    affine_only[head] += 1
                for u_v, d_v in zip(u_all[:, j], d_all[:, j], strict=True):
                    limit = (self.tau_pct / 100.0) * max(
                        abs(float(u_v)), self.floors[head])
                    if abs(float(d_v)) > limit:
                        train_over_limit[head] += 1
        self.fit_summary = {
            "n_anchors": len(pairs),
            "n_freqs": n_f,
            "n_gp_fitted": gp_counts,
            "n_affine_only": affine_only,
            "resid_std_max": resid_std_max,
            "train_delta_absmax": train_delta_absmax,
            "train_over_limit_count": train_over_limit,
            "tau_pct": self.tau_pct,
            "floors": dict(self.floors),
            "theta0": self.theta0,
            "gp_resid_std_guard": self.gp_resid_std_guard,
            "note": ("train_over_limit_count 仅为如实出账（信任域只在 "
                     "predict 期生效）；train 锚深谷点（如 w0918 |Γ|~1e-4）"
                     "超限属预期，见 criteria §3"),
        }
        self.fitted = True
        return dict(self.fit_summary)

    # ---------------------------------------------------------------- 预测
    def _limit(self, head: str, u_val: float) -> float:
        return (self.tau_pct / 100.0) * max(abs(float(u_val)),
                                            self.floors[head])

    def predict_row(self, low_row: dict[str, Any],
                    freqs: np.ndarray) -> dict[str, Any]:
        """修正一行 OE 预测；返回修正头 + 信任域回退计数 + warnings。

        超信任域/非有限 δ 的条目回退 δ=0（用原始 OE 值）并记 warning
        （永不传播 NaN）。u 超出该支训练范围如实计数（SMT 内部裁剪到
        bounds，行为=边界外推受限）。
        """
        if not self.fitted:
            raise RuntimeError("OutputSpaceMapper 未拟合，先调用 fit()")
        n_f = len(freqs)
        g_lo = _gamma_lin(low_row["s11_db"])
        s21_lo = np.asarray(low_row["s21_db"], dtype=float)
        eps_lo = float(low_row["eps_eff"])
        fallbacks = {h: 0 for h in _HEADS}
        outside = {h: 0 for h in _HEADS}
        warnings: list[str] = []

        def _corrected(head: str, j: int, u_val: float) -> float:
            br = self.branches[(head, j)]
            if u_val < br.u_lo - 1e-12 or u_val > br.u_hi + 1e-12:
                outside[head] += 1
            d = br.predict_delta(u_val)
            limit = self._limit(head, u_val)
            if not np.isfinite(d) or abs(d) > limit:
                fallbacks[head] += 1
                warnings.append(
                    f"{head}[{j}]: |delta|={abs(d):.3e} "
                    f"limit={limit:.3e} -> fallback raw OE")
                return 0.0
            return float(d)

        d11 = np.array([_corrected("gamma_lin", j, float(g_lo[j]))
                        for j in range(n_f)])
        g_corr = np.clip(g_lo + d11, 0.0, 1.0)
        d21 = np.array([_corrected("s21_db", j, float(s21_lo[j]))
                        for j in range(n_f)])
        de = _corrected("eps_eff", 0, eps_lo)
        return {
            "w": float(low_row["w"]),
            "s11_db": 20.0 * np.log10(np.maximum(g_corr, S11_DB_FLOOR)),
            "s21_db": s21_lo + d21,
            "eps_eff": eps_lo + de,
            "run_id": f"outputsm::{low_row.get('run_id', '')}",
            "trust_region_fallbacks": fallbacks,
            "u_outside_train_range": outside,
            "warnings": warnings,
        }

    # ---------------------------------------------------------------- 评估
    def evaluate(self, low_rows: list[dict[str, Any]],
                 truth_rows: list[dict[str, Any]],
                 freqs: np.ndarray) -> dict[str, Any]:
        """held-out 评估（统计语义与 factory_m2_mfk_rejudge.arm_stats 一致）。

        线性域 |ΔΓ| 逐频绝对差 / S21 dB 绝对差 / εeff 相对差；预测或真值
        非有限、锚行缺 OE 均计 n_fit_failures（多报不放过，#314/#316）。
        """
        n_f = len(freqs)
        d_gamma: list[float] = []
        d_21: list[float] = []
        d_eps: list[float] = []
        per_point: list[dict[str, Any]] = []
        n_fail = 0
        n_fallbacks = 0
        for t in truth_rows:
            oe = find_exact_low_row(low_rows, float(t["w"]))
            g_pt: list[float] = []
            s_pt: list[float] = []
            eps_pt: float | None = None
            tr_fb: dict[str, int] = {}
            if oe is None:
                n_fail += 2 * n_f + 1
            else:
                pred = self.predict_row(oe, freqs)
                tr_fb = pred["trust_region_fallbacks"]
                n_fallbacks += sum(tr_fb.values())
                g_pred = _gamma_lin(pred["s11_db"])
                g_true = _gamma_lin(t["s11_db"])
                s21_pred = np.asarray(pred["s21_db"], dtype=float)
                s21_true = np.asarray(t["s21_db"], dtype=float)
                for j in range(n_f):
                    if np.isfinite(g_pred[j]) and np.isfinite(g_true[j]):
                        d = abs(float(g_pred[j]) - float(g_true[j]))
                        d_gamma.append(d)
                        g_pt.append(d)
                    else:
                        n_fail += 1
                    if np.isfinite(s21_pred[j]) and np.isfinite(s21_true[j]):
                        d = abs(float(s21_pred[j]) - float(s21_true[j]))
                        d_21.append(d)
                        s_pt.append(d)
                    else:
                        n_fail += 1
                v_p, v_t = float(pred["eps_eff"]), float(t["eps_eff"])
                if np.isfinite(v_p) and np.isfinite(v_t) and v_t != 0.0:
                    eps_pt = abs(v_p - v_t) / abs(v_t)
                    d_eps.append(eps_pt)
                else:
                    n_fail += 1
            per_point.append({
                "w": float(t["w"]),
                "point_id": t.get("point_id"),
                "gamma_lin_max": max(g_pt) if g_pt else None,
                "s21_db_max": max(s_pt) if s_pt else None,
                "eps_eff_rel": eps_pt,
                "trust_region_fallbacks": tr_fb,
            })
        return {
            "gamma_lin": _stats(np.asarray(d_gamma, dtype=float)),
            "s21_db": _stats(np.asarray(d_21, dtype=float)),
            "eps_eff_rel": _stats(np.asarray(d_eps, dtype=float)),
            "n_fit_failures": n_fail,
            "n_trust_region_fallbacks": n_fallbacks,
            "per_point": per_point,
        }

    # ---------------------------------------------------------------- LOO
    def leave_one_anchor_out(self, anchor_rows: list[dict[str, Any]],
                             low_rows: list[dict[str, Any]],
                             freqs: np.ndarray) -> dict[str, Any]:
        """9 折 leave-one-anchor-out：逐折全新拟合（8 锚）→ 评 1 锚。

        每折独立 OutputSpaceMapper（同构造参数）；返回逐折与聚合
        （fold-max 的 max/mean）统计。协议配平对照由驱动侧对参考臂
        以同一函数语义执行。
        """
        folds: list[dict[str, Any]] = []
        for i, t in enumerate(anchor_rows):
            train = [a for j, a in enumerate(anchor_rows) if j != i]
            mapper = OutputSpaceMapper(
                tau_pct=self.tau_pct, floors=self.floors,
                theta0=self.theta0,
                gp_resid_std_guard=self.gp_resid_std_guard)
            mapper.fit(train, low_rows, freqs)
            res = mapper.evaluate(low_rows, [t], freqs)
            folds.append({
                "point_id": t.get("point_id"),
                "w": float(t["w"]),
                "gamma_lin_max": res["gamma_lin"]["max"],
                "s21_db_max": res["s21_db"]["max"],
                "eps_eff_rel": res["eps_eff_rel"]["max"],
                "n_fit_failures": res["n_fit_failures"],
                "n_trust_region_fallbacks": res["n_trust_region_fallbacks"],
            })
        agg: dict[str, dict[str, float]] = {}
        for key in ("gamma_lin_max", "s21_db_max", "eps_eff_rel"):
            vals = np.array([f[key] for f in folds
                             if f[key] is not None
                             and np.isfinite(f[key])], dtype=float)
            agg[key] = ({"max": float(vals.max()), "mean": float(vals.mean()),
                         "n": int(vals.size)} if vals.size
                        else {"max": float("nan"), "mean": float("nan"),
                              "n": 0})
        return {"n_folds": len(folds), "folds": folds,
                "aggregate_of_fold_max": {
                    "gamma_lin": agg["gamma_lin_max"],
                    "s21_db": agg["s21_db_max"],
                    "eps_eff_rel": agg["eps_eff_rel"]}}
