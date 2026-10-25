"""FORM 可靠性评估叶（T1 解环；aurora_g W6-S1）。

从 robustness_service 叶化：form_pf（XD-11 换基，HL-RF 收敛
core.form_beta 单源内核）+ _mk_cost_fn（违约 cost 构造）+ 外部库
（openturns/uqpy）对照辅助。uq_service 的 pf_vs_mc 面改读本叶，
静态图上不再出现 uq→robustness 边（robustness↔uq 2-环断；
robustness→uq 的上下文装载方向保留单向）。
测试缝不变：test_w2_g_rare_event 钉的是 core.form_beta（内核层）；
robustness_service 同名再导出保模块面零变化。
"""
from __future__ import annotations

import math
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: HL-RF 缺省迭代参数（可在 form_pf 入参覆盖；透传 core.form_beta 的
#: max_iter/tol。fd_eps 换基后仅用于信封 ``gradient_norm`` 报告面的
#: u 空间差分复算——求解梯度步长由内核固定相对步长 1e-6 单源承担）。
FORM_DEFAULT_MAX_ITER = 50
FORM_DEFAULT_TOL = 1e-6
FORM_DEFAULT_FD_EPS = 1e-5


def _normal_cdf(x: float) -> float:
    """标准正态 CDF Φ(x)（math.erfc 尾部稳定，无需 scipy）。"""
    return 0.5 * math.erfc(-float(x) / math.sqrt(2.0))


def _import_openturns() -> Any:
    """openturns 惰性导入（缺失返回 None；monkeypatch 钉测试通道 #139）。"""
    try:
        import openturns as ot

        return ot
    except ImportError:
        return None


def _import_uqpy() -> Any:
    """uqpy 惰性导入（缺失返回 None；monkeypatch 钉测试通道 #139）。"""
    try:
        import uqpy

        return uqpy
    except ImportError:
        return None


def _form_cross_check_openturns(
    ot: Any,
    cost_fn: Any,
    names: list[str],
    mu: Any,
    sigma: Any,
    *,
    threshold: float,
) -> dict[str, Any]:
    """openturns FORM 对照（可选库存在时；API 异常如实 ok=False 不透出细节）。

    注意：本仓 venv 未装 openturns，该分支无法本地实测——外层全部
    try/except 兜底，失败只降级对照（主结果始终是 internal 引擎）。
    """
    def _g(x: list[float]) -> list[float]:
        pt = {n: float(v) for n, v in zip(names, x, strict=True)}
        return [threshold - float(cost_fn(pt))]

    try:
        func = ot.PythonFunction(len(names), 1, _g)
        dist = ot.Normal(list(map(float, mu)), list(map(float, sigma)))
        algo = ot.FORM(ot.AbdoRackwitz(), ot.Event(ot.RandomVector(
            func, ot.RandomVector(dist)), ot.Less(), 0.0), dist.getMean())
        algo.run()
        res = algo.getResult()
        return ok_envelope(
            engine="openturns",
            pf=float(res.getEventProbability()),
            beta=float(res.getGeneralisedReliabilityIndex()),
        )
    except Exception as exc:  # API 漂移/运行失败：如实降级
        return {"ok": False, "engine": "openturns",
                "error": f"openturns 对照失败（{type(exc).__name__}）"}


def _form_cross_check_uqpy(
    uqpy_mod: Any,
    cost_fn: Any,
    names: list[str],
    mu: Any,
    sigma: Any,
    *,
    threshold: float,
) -> dict[str, Any]:
    """uqpy FORM 对照（可选库存在时；同 openturns 分支的兜底口径）。"""
    try:
        from uqpy import distributions as dist
        from uqpy import reliability as rel

        marginals = [dist.Normal(float(m), float(s))
                     for m, s in zip(mu, sigma, strict=True)]
        joint = dist.MultivariateDistribution(
            name="Independent", marginals=marginals)

        def _g(x: Any) -> Any:
            pts = x.reshape(-1, len(names))
            return [(threshold - float(cost_fn(
                {n: float(v) for n, v in zip(names, row, strict=True)})))
                for row in pts]

        form = rel.Form(
            name="HL", n_add=1, joint_distribution=joint,
            limit_state=_g)
        form.run()
        return ok_envelope(engine="uqpy", pf=float(form.failure_probability), beta=float(form.beta))
    except Exception as exc:  # API 漂移/运行失败：如实降级
        return {"ok": False, "engine": "uqpy",
                "error": f"uqpy 对照失败（{type(exc).__name__}）"}


def form_pf(
    cost_fn: Any,
    nominal: dict[str, float],
    sigmas: dict[str, float],
    *,
    threshold: float = 0.0,
    max_iter: int = FORM_DEFAULT_MAX_ITER,
    tol: float = FORM_DEFAULT_TOL,
    fd_eps: float = FORM_DEFAULT_FD_EPS,
    form_engine: str = "auto",
) -> dict[str, Any]:
    """FORM 服务面：HL-RF 收敛 core.form_beta 单源内核（JSON 契约）。

    失效面 g(x) = threshold − cost(x)（failure ⇔ g ≤ 0；threshold 缺省
    0 = 代理加权违约 cost ≥ 0 判失效，cost=SpecEvaluator 加权违约和或
    调用方自定义确定性函数）。独立正态 X_i ~ N(μ_i, σ_i²)，u 空间
    x = μ + σ⊙u。HL-RF 迭代/梯度/收敛判据全部吃 core.form_beta
    （XD-11 换基，rx2-s6 内核；本函数退役本地 hlrf 副本，#116 遮蔽
    治理）。

    **多起点**：违约 hinge cost 在安全区梯度恒 0，原点单起点会停在
    u=0（pf=0.5 无信息）——种子=原点+±2σ 轴点+角点（d≤6），逐种子以
    u0=seed 调内核，取收敛设计点中 ‖u‖ 最小者；全种子无梯度（搜索半径
    内无违约面）→ converged=False + note 如实（Pf 无信息量）。失效侧
    判定用 g(1.5u*) 符号（铰链面 g(0)=0 恰在界上，g(0) 判侧不成立）。

    **fd_eps 契约注记**（换基后）：求解梯度步长由内核固定相对步长
    （1e-6）单源承担；本参数仅用于信封 ``gradient_norm`` 报告面的复算，
    传非缺省值会附加 note 显式声明（不静默）。

    form_engine：``auto``（缺省，internal 主算 + 外部库存在时附
    cross_check）/ ``internal`` / ``openturns`` / ``uqpy``——指名外部库
    而不可用时回退 internal 并显式 note（不静默）。输出 ``form_engine``
    字段 = 主算引擎来源；``method_note`` 恒声明一阶线性化近似边界
    （深谷强非线性面 Pf 是近似值，如实不凑 PASS）。
    """
    if not callable(cost_fn):
        return error_envelope(["cost_fn 必须可调用"])
    names = sorted(sigmas)
    if not names:
        return error_envelope(["sigmas 为空（无随机变量）"])
    missing = [n for n in names if n not in nominal]
    if missing:
        return error_envelope([f"名义点缺少随机变量坐标: {missing}"])
    mu = [float(nominal[n]) for n in names]
    sigma = [float(sigmas[n]) for n in names]
    if any(s <= 0 for s in sigma):
        return error_envelope([f"σ 必须 >0，收到 {sigma}"])

    def g_u(u: list[float]) -> float:
        pt = {n: m + s * float(ui)
              for n, m, s, ui in zip(names, mu, sigma, u, strict=True)}
        return threshold - float(cost_fn(pt))

    def limit_state_x(x_arr: Any) -> float:
        """物理空间极限状态（core.form_beta 契约：ndarray → 标量）。"""
        pt = {n: float(v) for n, v in zip(names, x_arr, strict=True)}
        return threshold - float(cost_fn(pt))

    def _grad_norm_report(u: list[float]) -> float:
        """信封 gradient_norm 报告面：u 空间中心差分复算（fd_eps 口径）。"""
        grad = []
        for j in range(len(names)):
            up = list(u)
            un = list(u)
            h = float(fd_eps) * max(1.0, abs(u[j]))
            up[j] += h
            un[j] -= h
            grad.append((g_u(up) - g_u(un)) / (2.0 * h))
        return math.sqrt(sum(g * g for g in grad))

    # 多起点 HL-RF：违约 hinge cost（threshold−cost）在安全区梯度恒 0，
    # 原点单起点会停在 u=0（pf=0.5 无信息）——加轴点（半径 2/4/8σ）与
    # 角点种子，命中违约侧种子即有梯度可走；取收敛设计点中 ‖u‖ 最小者
    # （FORM 定义=失效面上距原点最近点）。全部种子无梯度/不收敛 → 如实
    # converged=False（Pf 无信息量，公差内可能确无违约）。
    # XD-11 换基：迭代内核=core.form_beta 单源（rx2-s6；本地 hlrf 副本
    # 已退役——收敛判据/梯度步长以内核为准，本函数只做多起点播种与
    # 最小 ‖u‖ 选点）。
    import numpy as np

    from rfauto.core.form_reliability import form_beta

    d = len(names)
    seeds: list[list[float]] = [[0.0] * d]
    for radius in (2.0, 4.0, 8.0):
        for j in range(d):
            for sign in (radius, -radius):
                pt = [0.0] * d
                pt[j] = sign
                seeds.append(pt)
    if d <= 4:
        for i in range(2 ** d):
            corner = [2.0 if (i >> j) & 1 else -2.0 for j in range(d)]
            seeds.append(corner)
    runs = [form_beta(limit_state_x, mu, sigma,
                      u0=np.asarray(s, dtype=float),
                      max_iter=int(max_iter), tol=float(tol))
            for s in seeds]
    good = [r for r in runs if r.converged]
    if good:
        best = min(good,
                   key=lambda r: float(np.linalg.norm(r.design_point_u)))
    else:
        best = min(runs,
                   key=lambda r: float(np.linalg.norm(r.design_point_u)))
    u = [float(v) for v in best.design_point_u]
    converged = bool(best.converged)
    n_iter = int(best.n_iter)
    beta_raw = math.sqrt(sum(ui * ui for ui in u))
    g_design = g_u(u)
    grad_norm = _grad_norm_report(u)
    n_converged = len(good)

    g_mean = g_u([0.0] * len(names))
    # 失效侧判定：g 在 1.5·u* 处的符号（失效方向=g 变负方向）。g(0) 判侧
    # 对违约 hinge cost 不成立——安全区 cost 恒 0 → g(0)=0 恰在界上，Probe
    # 法对线性面/均值失效/铰链界上三种情形一致（线性面上 g(αu*)=(α−1)c）。
    g_beyond = g_u([1.5 * ui for ui in u]) if beta_raw > 0 else g_mean
    if g_beyond <= 0.0:
        # 失效在 u* 外侧（常规安全均值/铰链界上）：Pf = Φ(−β)
        pf = _normal_cdf(-beta_raw)
        beta_signed = beta_raw
    else:
        # 均值点已在失效域（失效在原点侧）：Pf = Φ(+β) > 0.5，β 负号如实
        pf = _normal_cdf(beta_raw)
        beta_signed = -beta_raw
    design_x = {n: m + s * ui
                for n, m, s, ui in zip(names, mu, sigma, u, strict=True)}
    notes_start = (["全部起点无梯度信息/未收敛（违约面在搜索半径内平坦"
                    "——公差盒内可能无违约），Pf 估计无信息量"]
                   if not good else [])

    # 引擎分派：auto = internal 主算 + 存在即对照；指名外部库不可用 →
    # 回退 internal + note（不静默）
    notes: list[str] = []
    cross_check: dict[str, Any] | None = None
    engine = "internal"
    ot = _import_openturns() if form_engine in ("auto", "openturns") else None
    uqpy_mod = _import_uqpy() if form_engine in ("auto", "uqpy") else None
    if form_engine == "openturns":
        if ot is None:
            notes.append("指名 openturns 但库不可用，回退 internal 自实现")
        else:
            engine = "openturns"
            ext = _form_cross_check_openturns(
                ot, cost_fn, names, mu, sigma, threshold=threshold)
            internal_pf = pf
            if ext.get("ok"):
                pf, beta_signed = float(ext["pf"]), float(ext["beta"])
                cross_check = {"engine": "internal", "pf": internal_pf,
                               "rel_diff": abs(internal_pf - pf)
                               / max(abs(pf), 1e-12)}
            else:
                notes.append(ext.get("error", "openturns 对照失败"))
                engine = "internal"
    elif form_engine == "uqpy":
        if uqpy_mod is None:
            notes.append("指名 uqpy 但库不可用，回退 internal 自实现")
        else:
            engine = "uqpy"
            ext = _form_cross_check_uqpy(
                uqpy_mod, cost_fn, names, mu, sigma, threshold=threshold)
            internal_pf = pf
            if ext.get("ok"):
                pf, beta_signed = float(ext["pf"]), float(ext["beta"])
                cross_check = {"engine": "internal", "pf": internal_pf,
                               "rel_diff": abs(internal_pf - pf)
                               / max(abs(pf), 1e-12)}
            else:
                notes.append(ext.get("error", "uqpy 对照失败"))
                engine = "internal"
    else:  # auto / internal：internal 主算，外部库存在则对照
        if form_engine == "auto" and ot is not None:
            cross_check = _form_cross_check_openturns(
                ot, cost_fn, names, mu, sigma, threshold=threshold)
        elif form_engine == "auto" and uqpy_mod is not None:
            cross_check = _form_cross_check_uqpy(
                uqpy_mod, cost_fn, names, mu, sigma, threshold=threshold)
        elif form_engine == "auto":
            notes.append("openturns/uqpy 均未安装：仅 internal 自实现"
                         "（无外部对照）")

    all_notes = [*notes, *notes_start]
    if fd_eps != FORM_DEFAULT_FD_EPS:
        # 换基契约（见 docstring）：求解梯度步长由内核固定相对步长单源
        # 承担，fd_eps 只作用报告面——非缺省值显式声明，不静默
        all_notes.append(
            f"fd_eps={fd_eps!r} 仅用于 gradient_norm 报告复算；求解梯度"
            "步长由 core.form_beta 内核固定相对步长（1e-6）承担")
    if good and not converged:
        all_notes.append("最小 ‖u‖ 收敛点未达到（触顶如实报告）；"
                         "Pf 引用未收敛运行")
    return ok_envelope(
        **{"form_engine": engine, "pf": float(pf), "beta": float(beta_signed), "converged": bool(converged), "n_iter": int(n_iter), "max_iter": int(max_iter), "n_starts": len(seeds), "n_converged_starts": n_converged, "g_at_mean": float(g_mean), "g_at_design_point": float(g_design), "gradient_norm": float(grad_norm), "design_point_u": {n: float(ui)
                           for n, ui in zip(names, u, strict=True)}, "design_point_x": design_x, "threshold": float(threshold), "sigmas": dict(sigmas), "method_note": "FORM 一阶（core.form_beta 内核）：失效面在设计点线性化"
                       "（HL-RF 多起点，取最小 ‖u‖ 收敛点），强非线性（深谷"
                       "/多模）面上 Pf 为近似值——对照 MC 见 "
                       "robustness_report.pf_vs_mc，如实报告不凑 PASS", **({"cross_check": cross_check} if cross_check is not None else {}), **({"notes": all_notes} if all_notes else {})},
    )


def _mk_cost_fn(model: Any, objs: list[Any]) -> Any:
    """代理 + objectives → 确定性违约 cost 函数（FORM/worst-case 共用）。"""
    from rfauto.core.objectives import SpecEvaluator

    def cost_fn(params: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(model.predict(params), objs)

    return cost_fn
