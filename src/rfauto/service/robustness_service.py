"""robustness_service：DP-15 C3 稳健性报告（良率/FORM/worst-case/Cpk）。

规格书 docs/plan_deepdive_specs_20260924.md §15.3 第二片，service 层
JSON 进出（分层铁律 #4；数值只在确定性内核 #7——FORM/搜索全部吃代理
确定性求值，本模块无随机决策）：

- ``load_tolerance_profile``：公差配方 profile schema+加载（±tol →
  σ = tol/k_sigma，k_sigma 缺省 3.0，与 optimization/tolerance.py 的
  ``sigma = tol / 3`` 口径一致；``fab`` 挂载点本批只定义 schema+加载
  透传，DP-7 解析接口后续接入）。
- ``form_pf``：FORM v1 自实现（HL-RF 迭代 + u 空间中心差分数值梯度），
  失效面 g(x) = threshold − cost(x)（threshold 缺省 0 = 代理加权违约
  cost ≥ 0 判失效）；openturns/uqpy 可选库存在则对照、缺失回退自实现
  （惰性 import，``form_engine`` 显式标注引擎来源）。
- ``surrogate_worst_case``：代理面上优化违约角点（复用 core/pce 的
  ``_pattern_search`` 内核——多起点=中心+2^d 角点，不重写搜索）。
- ``robustness_report``：输入=数据集/run/samples.json + 规范限 + 公差
  profile；输出 = {yield_mc（向量化 MC，见 uq_service）, form_pf,
  worst_case 角点, 逐规范 Cpk, uncertainty_status（消费 DP-13 R1 已挂
  面）, pf_vs_mc}。CLI/MCP 薄壳后续批次接线。

与 optimization/tolerance.py 的差别：tolerance 每点真机求解（贵）；
本模块全部在代理上（免费），代理可信度由校准 gate/uncertainty_status
背书。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

#: 公差半宽 → σ 的换算口径：tol = k_sigma·σ（缺省 3σ = tol，即 #195/
#: tolerance.py 同款"3σ=公差"惯例）。
PROFILE_DEFAULT_K_SIGMA = 3.0
#: profile.params[p].dist 允许值（v1 只有正态；均匀/三角等后续按需加）。
PROFILE_ALLOWED_DISTS = ("normal",)
#: HL-RF 缺省迭代参数（可在 form_pf 入参覆盖）。
FORM_DEFAULT_MAX_ITER = 50
FORM_DEFAULT_TOL = 1e-6
FORM_DEFAULT_FD_EPS = 1e-5
#: robustness_report 数据集读面的行数上限（本服务面向校准级样本集，
#: 不是 1e6 行 MC 库的检索面——检索走 query_dataset）。
_REPORT_MAX_DATASET_ROWS = 200_000


def _normal_cdf(x: float) -> float:
    """标准正态 CDF Φ(x)（math.erfc 尾部稳定，无需 scipy）。"""
    return 0.5 * math.erfc(-float(x) / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# 公差配方 profile schema + 加载
# ---------------------------------------------------------------------------

def load_tolerance_profile(
    profile: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """公差配方 profile → {param: σ} 换算（纯函数，JSON/YAML 进出）。

    schema（dict 或 YAML/JSON 文件路径）::

        profile: cpw_fab_std          # 名字（可选）
        description: ...              # 可选
        k_sigma: 3.0                  # tol = k_sigma·σ；缺省 3.0（3σ 口径）
        params:                       # 必填非空
          w_mm: {tol: 0.02, unit: mm} # tol=±半宽必填>0；dist 缺省 normal
          gap_mm: {tol: 0.01, dist: normal, nominal: 0.25}  # nominal 可选覆盖
        fab: {...}                    # 可选 fab 剖面挂载点（DP-7 解析接口，
                                      # 本批只加载透传不解释）

    σ = tol / k_sigma（±20µm → σ=20/3 µm）。返回
    {ok, profile, description, k_sigma, sigmas, tolerances, units,
    nominal_overrides, params, fab} 或 {ok: False, errors}。
    """
    if isinstance(profile, (str, Path)):
        path = Path(profile)
        if not path.is_file():
            return {"ok": False, "errors": [f"profile 文件不存在: {path}"]}
        text = path.read_text(encoding="utf-8")
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception as exc:
            return {"ok": False, "errors": [f"profile YAML 解析失败: {exc}"]}
        if not isinstance(data, dict):
            return {"ok": False, "errors": ["profile 文件顶层必须是映射"]}
        source = str(path)
    elif isinstance(profile, dict):
        data = profile
        source = "dict"
    else:
        return {"ok": False, "errors": [
            f"profile 必须是 dict 或文件路径，收到 {type(profile).__name__}"]}

    errors: list[str] = []
    raw_params = data.get("params")
    if not isinstance(raw_params, dict) or not raw_params:
        errors.append("profile.params 必须是非空映射 {param: {tol: ...}}")
        raw_params = {}
    k_sigma = data.get("k_sigma", PROFILE_DEFAULT_K_SIGMA)
    try:
        k_sigma = float(k_sigma)
        if k_sigma <= 0:
            errors.append(f"k_sigma 必须 >0，收到 {k_sigma}")
            k_sigma = PROFILE_DEFAULT_K_SIGMA
    except (TypeError, ValueError):
        errors.append(f"k_sigma 必须是数值，收到 {k_sigma!r}")
        k_sigma = PROFILE_DEFAULT_K_SIGMA

    sigmas: dict[str, float] = {}
    tolerances: dict[str, float] = {}
    units: dict[str, str] = {}
    overrides: dict[str, float] = {}
    detail: dict[str, dict[str, Any]] = {}
    for name, spec in raw_params.items():
        name = str(name)
        if not isinstance(spec, dict):
            errors.append(f"params.{name} 必须是映射（含 tol）")
            continue
        tol = spec.get("tol")
        try:
            tol_f = float(tol)
        except (TypeError, ValueError):
            errors.append(f"params.{name}.tol 必须是数值（±半宽），收到 {tol!r}")
            continue
        if tol_f <= 0:
            errors.append(f"params.{name}.tol 必须 >0，收到 {tol_f}")
            continue
        dist = str(spec.get("dist", "normal"))
        if dist not in PROFILE_ALLOWED_DISTS:
            errors.append(f"params.{name}.dist 只允许 "
                          f"{'/'.join(PROFILE_ALLOWED_DISTS)}，收到 {dist!r}")
            continue
        sigmas[name] = tol_f / k_sigma
        tolerances[name] = tol_f
        if spec.get("unit") is not None:
            units[name] = str(spec["unit"])
        if spec.get("nominal") is not None:
            try:
                overrides[name] = float(spec["nominal"])
            except (TypeError, ValueError):
                errors.append(f"params.{name}.nominal 必须是数值，"
                              f"收到 {spec['nominal']!r}")
                continue
        detail[name] = {"tol": tol_f, "sigma": sigmas[name],
                        "dist": dist, **({"unit": units[name]}
                                         if name in units else {}),
                        **({"nominal": overrides[name]}
                           if name in overrides else {})}
    if errors:
        return {"ok": False, "errors": errors, "source": source}
    fab = data.get("fab")
    return {
        "ok": True,
        "source": source,
        "profile": str(data["profile"]) if data.get("profile") else None,
        "description": str(data.get("description") or ""),
        "k_sigma": k_sigma,
        "sigmas": sigmas,
        "tolerances": tolerances,
        "units": units,
        "nominal_overrides": overrides,
        "params": detail,
        # fab 剖面挂载点：DP-7 解析接口（本批 schema+加载透传，不解释）
        "fab": fab if isinstance(fab, dict) else None,
    }


# ---------------------------------------------------------------------------
# FORM v1 自实现（HL-RF + 数值梯度）
# ---------------------------------------------------------------------------

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
        return {"ok": True, "engine": "openturns",
                "pf": float(res.getEventProbability()),
                "beta": float(res.getGeneralisedReliabilityIndex())}
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
        return {"ok": True, "engine": "uqpy", "pf": float(form.failure_probability),
                "beta": float(form.beta)}
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
    """FORM v1：HL-RF 迭代 + u 空间中心差分数值梯度（JSON 契约）。

    失效面 g(x) = threshold − cost(x)（failure ⇔ g ≤ 0；threshold 缺省
    0 = 代理加权违约 cost ≥ 0 判失效，cost=SpecEvaluator 加权违约和或
    调用方自定义确定性函数）。独立正态 X_i ~ N(μ_i, σ_i²)，u 空间
    x = μ + σ⊙u。HL-RF：u_{k+1} = ((∇gᵀu_k − g_k)/‖∇g‖²)·∇g_k。

    **多起点**：违约 hinge cost 在安全区梯度恒 0，原点单起点会停在
    u=0（pf=0.5 无信息）——种子=原点+±2σ 轴点+角点（d≤6），取收敛
    设计点中 ‖u‖ 最小者；全种子无梯度（搜索半径内无违约面）→
    converged=False + note 如实（Pf 无信息量）。失效侧判定用 g(1.5u*)
    符号（铰链面 g(0)=0 恰在界上，g(0) 判侧不成立）。

    form_engine：``auto``（缺省，internal 主算 + 外部库存在时附
    cross_check）/ ``internal`` / ``openturns`` / ``uqpy``——指名外部库
    而不可用时回退 internal 并显式 note（不静默）。输出 ``form_engine``
    字段 = 主算引擎来源；``method_note`` 恒声明一阶线性化近似边界
    （深谷强非线性面 Pf 是近似值，如实不凑 PASS）。
    """
    if not callable(cost_fn):
        return {"ok": False, "errors": ["cost_fn 必须可调用"]}
    names = sorted(sigmas)
    if not names:
        return {"ok": False, "errors": ["sigmas 为空（无随机变量）"]}
    missing = [n for n in names if n not in nominal]
    if missing:
        return {"ok": False, "errors": [f"名义点缺少随机变量坐标: {missing}"]}
    mu = [float(nominal[n]) for n in names]
    sigma = [float(sigmas[n]) for n in names]
    if any(s <= 0 for s in sigma):
        return {"ok": False, "errors": [f"σ 必须 >0，收到 {sigma}"]}

    def g_u(u: list[float]) -> float:
        pt = {n: m + s * float(ui)
              for n, m, s, ui in zip(names, mu, sigma, u, strict=True)}
        return threshold - float(cost_fn(pt))

    def hlrf(start: list[float]) -> dict[str, Any]:
        """单起点 HL-RF（跨界二分回边界；死起点/触顶如实不收敛）。"""
        u = list(start)
        converged = False
        n_iter = 0
        g_design = float("nan")
        grad_norm = float("nan")
        g0 = g_u(u)
        for k in range(int(max_iter)):
            grad = []
            for j in range(len(names)):
                up = list(u)
                un = list(u)
                h = float(fd_eps) * max(1.0, abs(u[j]))
                up[j] += h
                un[j] -= h
                grad.append((g_u(up) - g_u(un)) / (2.0 * h))
            gn = math.sqrt(sum(g * g for g in grad))
            grad_norm = gn
            if gn < 1e-14:
                # 无梯度信息（hinge 安全区平坦）——死起点，如实不收敛
                g_design = g0
                n_iter = k + 1
                break
            coef = (sum(g * ui for g, ui in zip(grad, u, strict=True)) - g0) \
                / (gn * gn)
            u_new = [coef * g for g in grad]
            g_new = g_u(u_new)
            n_iter = k + 1
            if g0 < 0.0 <= g_new:
                # 违约侧→安全侧跨界（hinge 面上 HL-RF 的经典振荡；安全侧
                # g 恒为 0，跨界落点常取 g_new==0）：沿线段二分回违约侧
                # 边界端点（g 与 0 差 ≤2^-24 段长），从该点继续迭代——
                # 逐步收敛到局部最近边界点，步长达标才判收敛
                a, b = list(u), list(u_new)
                for _ in range(24):
                    m = [(x + y) * 0.5 for x, y in zip(a, b, strict=True)]
                    if g_u(m) >= 0.0:
                        b = m
                    else:
                        a = m
                step = math.sqrt(sum((x - y) ** 2
                                     for x, y in zip(a, u, strict=True)))
                u = a
                g0 = g_u(u)
                g_design = g0
                n_iter = k + 1
                if step <= float(tol) * max(1.0, math.sqrt(
                        sum(ui * ui for ui in u))):
                    converged = True
                    break
                continue
            step = math.sqrt(sum((x - y) ** 2
                                 for x, y in zip(u_new, u, strict=True)))
            u = u_new
            g0 = g_new
            g_design = g0
            if step <= float(tol) * max(1.0, math.sqrt(
                    sum(ui * ui for ui in u))):
                converged = True
                break
        return {"u": u, "converged": converged, "n_iter": n_iter,
                "g_design": g_design, "grad_norm": grad_norm,
                "beta": math.sqrt(sum(ui * ui for ui in u))}

    # 多起点 HL-RF：违约 hinge cost（threshold−cost）在安全区梯度恒 0，
    # 原点单起点会停在 u=0（pf=0.5 无信息）——加轴点（半径 2/4/8σ）与
    # 角点种子，命中违约侧种子即有梯度可走；取收敛设计点中 ‖u‖ 最小者
    # （FORM 定义=失效面上距原点最近点）。全部种子无梯度/不收敛 → 如实
    # converged=False（Pf 无信息量，公差内可能确无违约）。
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
    runs = [hlrf(s) for s in seeds]
    good = [r for r in runs if r["converged"]]
    best = min(good, key=lambda r: r["beta"]) if good \
        else min(runs, key=lambda r: r["beta"])
    u = best["u"]
    converged = bool(best["converged"])
    n_iter = best["n_iter"]
    g_design = best["g_design"]
    grad_norm = best["grad_norm"]
    beta_raw = float(best["beta"])
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
    if good and not converged:
        all_notes.append("最小 ‖u‖ 收敛点未达到（触顶如实报告）；"
                         "Pf 引用未收敛运行")
    return {
        "ok": True,
        "form_engine": engine,
        "pf": float(pf),
        "beta": float(beta_signed),
        "converged": bool(converged),
        "n_iter": int(n_iter),
        "max_iter": int(max_iter),
        "n_starts": len(seeds),
        "n_converged_starts": n_converged,
        "g_at_mean": float(g_mean),
        "g_at_design_point": float(g_design),
        "gradient_norm": float(grad_norm),
        "design_point_u": {n: float(ui)
                           for n, ui in zip(names, u, strict=True)},
        "design_point_x": design_x,
        "threshold": float(threshold),
        "sigmas": dict(sigmas),
        "method_note": "FORM v1 一阶：失效面在设计点线性化（HL-RF 多起点，"
                       "取最小 ‖u‖ 收敛点），强非线性（深谷/多模）面上 Pf "
                       "为近似值——对照 MC 见 robustness_report.pf_vs_mc，"
                       "如实报告不凑 PASS",
        **({"cross_check": cross_check} if cross_check is not None else {}),
        **({"notes": all_notes} if all_notes else {}),
    }


# ---------------------------------------------------------------------------
# worst-case 违约角点（复用 core/pce._pattern_search 内核）
# ---------------------------------------------------------------------------

def surrogate_worst_case(
    cost_fn: Any,
    nominal: dict[str, float],
    sigmas: dict[str, float],
    bounds: dict[str, tuple[float, float]],
    *,
    k_sigma: float = 3.0,
    threshold: float = 0.0,
    max_iter: int = 200,
    step_tol: float = 1e-8,
) -> dict[str, Any]:
    """公差盒内代理违约 cost 最大角点（多起点坐标 pattern search）。

    搜索域 = 名义 ±k_sigma·σ ∩ bounds（只动公差参数，其余坐标钉名义）；
    起点集 = 盒中心 + 2^d 角点（d>10 退化为中心+各轴端点，同
    core/pce.worst_case 结构），搜索内核直接复用 ``pce._pattern_search``
    （勿重写——规格书 §15.3 ③）。返回 {ok, params, cost, violated,
    threshold, k_sigma, box, n_evaluations, n_starts}。
    """
    from rfauto.core.pce import _pattern_search

    if k_sigma <= 0:
        return {"ok": False, "errors": [f"k_sigma 必须 >0，收到: {k_sigma}"]}
    if max_iter < 1:
        return {"ok": False, "errors": [f"max_iter 必须 ≥1，收到: {max_iter}"]}
    names = sorted(sigmas)
    if not names:
        return {"ok": False, "errors": ["sigmas 为空（无公差参数）"]}
    missing = [n for n in names if n not in nominal]
    if missing:
        return {"ok": False, "errors": [f"名义点缺少公差参数: {missing}"]}
    lo = []
    hi = []
    box: dict[str, list[float]] = {}
    for n in names:
        if n not in bounds:
            return {"ok": False, "errors": [f"公差参数不在搜索空间: {n}"]}
        blo, bhi = (float(bounds[n][0]), float(bounds[n][1]))
        base = float(nominal[n])
        b_lo = max(blo, base - float(k_sigma) * float(sigmas[n]))
        b_hi = min(bhi, base + float(k_sigma) * float(sigmas[n]))
        lo.append(b_lo)
        hi.append(b_hi)
        box[n] = [b_lo, b_hi]

    def func(x: Any) -> float:
        pt = {n: float(v) for n, v in zip(names, x, strict=True)}
        return float(cost_fn(pt))

    import numpy as np

    lo_arr = np.asarray(lo, dtype=float)
    hi_arr = np.asarray(hi, dtype=float)
    d = len(names)
    center = [0.5 * (a + b) for a, b in zip(lo, hi, strict=True)]
    if d <= 10:
        starts = [center]
        for i in range(2 ** d):
            corner = [lo[j] if (i >> j) & 1 == 0 else hi[j]
                      for j in range(d)]
            starts.append(corner)
    else:  # 高维退化：中心 + 各轴端点（pce.worst_case 同款）
        starts = [center]
        for j in range(d):
            for bound in (lo[j], hi[j]):
                pt = list(center)
                pt[j] = bound
                starts.append(pt)

    best_x: list[float] | None = None
    best_v = -math.inf
    n_eval = 0
    for start in starts:
        x, value, used = _pattern_search(
            func, start, lo_arr, hi_arr, True, max_iter, step_tol)
        n_eval += used
        if value > best_v:
            best_v = value
            best_x = list(x)
    assert best_x is not None
    params = dict(nominal)
    params.update({n: float(v) for n, v in zip(names, best_x, strict=True)})
    return {
        "ok": True,
        "params": params,
        "cost": float(best_v),
        "violated": bool(best_v > float(threshold)),
        "threshold": float(threshold),
        "k_sigma": float(k_sigma),
        "box": box,
        "n_evaluations": int(n_eval),
        "n_starts": len(starts),
        "search": "pce._pattern_search(multi-start corner+center)",
    }


# ---------------------------------------------------------------------------
# robustness_report（JSON 进出编排面）
# ---------------------------------------------------------------------------

def _mk_cost_fn(model: Any, objs: list[Any]) -> Any:
    """代理 + objectives → 确定性违约 cost 函数（FORM/worst-case 共用）。"""
    from rfauto.core.objectives import SpecEvaluator

    def cost_fn(params: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(model.predict(params), objs)

    return cost_fn


def _dataset_samples(
    name: str, out_dir: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, float]]] | tuple[None, list[str]]:
    """runs/datasets/<name>（query_dataset 读面）→ samples + bounds。"""
    from rfauto.service.dataset_service import query_dataset

    qr = query_dataset(name, limit=_REPORT_MAX_DATASET_ROWS + 1,
                       out_dir=out_dir)
    if not qr.get("ok"):
        return None, list(qr.get("errors") or ["数据集读取失败"])
    rows = list(qr.get("rows") or [])
    # #369 口径：query_dataset 的 n_rows 是 limit 截断后返回行数——超限
    # 判别用 len(rows) > 上限（再查 manifest 全量计数代价高且无必要，
    # 本服务面向校准级样本集）
    if len(rows) > _REPORT_MAX_DATASET_ROWS:
        return None, [f"数据集行数超过本服务上限 {_REPORT_MAX_DATASET_ROWS}"
                      "（MC 库检索请走 query_dataset）"]
    samples: list[dict[str, Any]] = []
    pmin: dict[str, float] = {}
    pmax: dict[str, float] = {}
    flat_mode = bool(rows) and "params_json" not in rows[0]
    for row in rows:
        if flat_mode:
            # 平面向量库（store_mc_draws 形态）：param__*/metric__* 列
            params = {c[len("param__"):]: float(v) for c, v in row.items()
                      if c.startswith("param__") and v is not None}
            metrics = {c[len("metric__"):]: float(v) for c, v in row.items()
                       if c.startswith("metric__") and v is not None}
        else:
            try:
                params = json.loads(row.get("params_json") or "{}")
                metrics = json.loads(row.get("metrics_json") or "{}")
            except (TypeError, ValueError):
                continue
            params = {k: float(v) for k, v in params.items()
                      if isinstance(v, (int, float))}
            metrics = {k: float(v) for k, v in metrics.items()
                       if isinstance(v, (int, float))}
        if not params or not metrics:
            continue
        samples.append({"params": params, "metrics": metrics})
        for k, v in params.items():
            pmin[k] = min(pmin.get(k, math.inf), v)
            pmax[k] = max(pmax.get(k, -math.inf), v)
    bounds: dict[str, tuple[float, float]] = {}
    for k in sorted(pmin):
        lo, hi = pmin[k], pmax[k]
        if hi <= lo:  # 常数参数：±0.5% 或 1e-6 垫开（poly_ridge clip 前提）
            pad = max(abs(lo) * 5e-3, 1e-6)
            lo, hi = lo - pad, hi + pad
        bounds[k] = (lo, hi)
    if not samples:
        return None, ["数据集无可解析的 params/metrics 点"]
    return samples, bounds


def _cpk_for_objectives(
    objs: list[Any], metric_stats: dict[str, Any],
) -> dict[str, Any]:
    """逐规范 Cpk（MC 分布 mean/std；单侧/双侧按 op 分派）。"""
    out: dict[str, Any] = {}
    for i, o in enumerate(objs):
        key = f"{o.metric}#{i}"
        stats = metric_stats.get(key)
        entry: dict[str, Any] = {"op": str(getattr(o.op, "value", o.op))}
        if stats is None:
            out[key] = {**entry, "cpk": None,
                        "note": "MC 统计缺该指标（判 FAIL 面）"}
            continue
        mean = float(stats["mean"])
        std = float(stats["std"])
        entry.update({"mean": mean, "std": std})
        if std <= 0.0:
            out[key] = {**entry, "cpk": None,
                        "note": "MC 分布零离散度（常数面），Cpk 不可辨识"}
            continue
        op = getattr(o.op, "value", o.op)
        if op == "max_below":
            usl = float(o.value)
            out[key] = {**entry, "usl": usl,
                        "cpk": (usl - mean) / (3.0 * std)}
        elif op == "min_above":
            lsl = float(o.value)
            out[key] = {**entry, "lsl": lsl,
                        "cpk": (mean - lsl) / (3.0 * std)}
        elif op == "mean_within" and isinstance(o.value, list) \
                and len(o.value) == 2:
            low, high = float(o.value[0]), float(o.value[1])
            out[key] = {**entry, "lsl": low, "usl": high,
                        "cpk": min((high - mean) / (3.0 * std),
                                   (mean - low) / (3.0 * std))}
        else:
            out[key] = {**entry, "cpk": None,
                        "note": "该 op 无 Cpk 口径（如实不硬算）"}
    return out


def robustness_report(
    source: str | Path,
    specs: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | str | Path | None = None,
    tolerances: dict[str, float] | None = None,
    n_mc: int = 100_000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
    k_sigma: float = 3.0,
    threshold: float = 0.0,
    form_engine: str = "auto",
    persist: bool = False,
    store_name: str | None = None,
    store_out_dir: str | Path = "runs/datasets",
) -> dict[str, Any]:
    """稳健性报告：数据集/run/samples.json + 规范限 + 公差 profile → JSON。

    输入：``source`` = samples.json 路径 | 数据集名（runs/datasets/<name>，
    经 query_dataset 读面）| run id（runs/<rid>/meta.json 存在 → 先
    materialize_dataset(health_gate=False, registry_sync=False) 物化为
    数据集再读）；``specs`` = objectives schema 列表（metric/op/value/
    weight）；公差 = ``profile``（load_tolerance_profile schema，优先）
    或 ``tolerances``（{param: σ} 遗传直传）。

    输出（单 dict）：ok / source / surrogate_kind / uncertainty_status
    （R1 已挂面）/ profile / nominal_params / nominal_metrics /
    yield_mc{yield_rate, n_draws, wall_s, implementation, metric_stats,
    store?} / form{pf, beta, form_engine, converged, ..., method_note} /
    worst_case{params, cost, violated, box} / cpk / pf_vs_mc /
    tolerance_source。CLI/MCP 薄壳后续批次接线（本批不接）。
    """
    from rfauto.service.uq_service import (
        _load_yield_context,
        _mc_yield,
        build_yield_context,
        store_mc_draws,
    )

    if not isinstance(specs, list) or not specs:
        return {"ok": False,
                "errors": ["specs 必须是非空列表（objectives schema）"]}
    if n_mc < 1:
        return {"ok": False, "errors": [f"n_mc 必须 ≥1，收到: {n_mc}"]}

    # 公差解析：profile 优先，tolerances 兜底
    prof_out: dict[str, Any] | None = None
    if profile is not None:
        prof_out = load_tolerance_profile(profile)
        if not prof_out.get("ok"):
            return {"ok": False,
                    "errors": list(prof_out.get("errors") or [])}
        sigmas = dict(prof_out["sigmas"])
        if prof_out.get("k_sigma"):
            k_sigma = float(prof_out["k_sigma"])
        tolerance_source = ("profile:" + (prof_out.get("profile")
                                          or prof_out.get("source", "dict")))
    elif isinstance(tolerances, dict) and tolerances:
        sigmas = {k: float(v) for k, v in tolerances.items()}
        tolerance_source = "tolerances_arg"
    else:
        return {"ok": False,
                "errors": ["缺少公差：给 profile（推荐）或 tolerances"]}

    # 来源解析：samples.json | 数据集名 | 数据集目录 | run id
    src_path = Path(source)
    dataset_used: str | None = None
    if src_path.is_file():
        ctx, errs = _load_yield_context(
            src_path, sigmas, kind=kind, order=order,
            ridge_lambda=ridge_lambda)
        if ctx is None:
            return {"ok": False, "errors": list(errs or [])}
        resolved = str(src_path)
    else:
        from rfauto.service.dataset_service import materialize_dataset

        ds_out = Path(store_out_dir)
        ds_name: str | None = None
        if (ds_out / str(source)).is_dir():
            ds_name, ds_out = str(source), ds_out
        elif src_path.is_dir():
            ds_name, ds_out = src_path.name, src_path.parent
        else:
            run_meta = Path("runs") / str(source) / "meta.json"
            if run_meta.is_file():
                mat_name = f"robustness_src_{src_path.name}"
                mat = materialize_dataset(
                    [str(source)], name=mat_name, out_dir=ds_out,
                    health_gate=False, registry_sync=False)
                if not mat.get("ok"):
                    return {"ok": False, "errors": [
                        f"run 物化失败: {mat.get('errors')}"]}
                ds_name, ds_out = mat_name, ds_out
            else:
                return {"ok": False, "errors": [
                    "来源不可解析（非 samples.json 文件/数据集/run id）: "
                    f"{source}"]}
        samples, bounds_or_errs = _dataset_samples(ds_name, ds_out)
        if samples is None:
            return {"ok": False, "errors": list(bounds_or_errs)}
        ctx, errs = build_yield_context(
            samples, bounds_or_errs, specs, sigmas, kind=kind, order=order,
            ridge_lambda=ridge_lambda)
        if ctx is None:
            return {"ok": False, "errors": list(errs or [])}
        dataset_used = ds_name
        resolved = str(ds_out / ds_name)

    if not sigmas:
        return {"ok": False, "errors": ["公差解析结果为空"]}

    # 名义点：样本集 cost 最小点（确定性）+ profile nominal 覆盖（界内校验）
    nominal = {k: float(v)
               for k, v in ctx["nominal_sample"]["params"].items()}
    if prof_out and prof_out.get("nominal_overrides"):
        bad = [k for k, v in prof_out["nominal_overrides"].items()
               if k not in ctx["bounds"]
               or not (ctx["bounds"][k][0] <= v <= ctx["bounds"][k][1])]
        if bad:
            return {"ok": False, "errors": [
                f"profile nominal 覆盖越界/未知参数: {bad}"]}
        nominal.update(prof_out["nominal_overrides"])

    # ① 向量化 MC 良率
    mc = _mc_yield(ctx, nominal, sigmas, n=int(n_mc), seed=int(seed))
    report: dict[str, Any] = {
        "ok": True,
        "source": resolved,
        "dataset": dataset_used,
        "surrogate_kind": kind,
        "uncertainty_status": ctx["uncertainty_status"],
        "profile": {k: v for k, v in (prof_out or {}).items()
                    if k in ("profile", "description", "k_sigma", "params",
                             "fab", "source")},
        "tolerance_source": tolerance_source,
        "sigmas": sigmas,
        "n_mc": int(n_mc),
        "seed": int(seed),
        "nominal_params": nominal,
        "nominal_metrics": mc["nominal_metrics"],
        "yield_mc": {
            "yield_rate": mc["yield_rate"],
            "n_draws": int(n_mc),
            "implementation": mc["implementation"],
            "wall_s": mc["wall_s"],
            "metric_stats": mc["metric_stats"],
        },
    }
    if persist:
        sname = store_name or f"mc_{Path(resolved).stem}_{int(n_mc)}"
        store = store_mc_draws(
            sname, mc, objs=ctx["objs"], out_dir=store_out_dir,
            seed=int(seed), source_dataset=dataset_used)
        if store.get("ok"):
            # #369 口径提示：全量计数以 manifest n_rows 为准
            report["yield_mc"]["store"] = {
                "dataset": store["name"],
                "n_rows": store["n_rows"],
                "note": "全量计数以 manifest n_rows 为准"
                        "（query_dataset 返回 n_rows 是 limit 截断语义）",
            }
        else:
            report["yield_mc"]["store_error"] = list(
                store.get("errors") or ["MC 落盘失败"])

    # ② FORM（失效面 = 代理违约 cost ≥ threshold）
    cost_fn = _mk_cost_fn(ctx["model"], ctx["objs"])
    form = form_pf(cost_fn, nominal, sigmas, threshold=threshold,
                   form_engine=form_engine)
    report["form"] = form

    # ③ worst-case 违约角点
    worst = surrogate_worst_case(cost_fn, nominal, sigmas, ctx["bounds"],
                                 k_sigma=k_sigma, threshold=threshold)
    report["worst_case"] = worst

    # ④ 逐规范 Cpk（MC 分布口径）
    stats_by_key = {f"{o.metric}#{i}": mc["metric_stats"].get(s["metric"])
                    for i, (o, s) in enumerate(zip(ctx["objs"],
                                                   ctx["specs"],
                                                   strict=True))}
    report["cpk"] = _cpk_for_objectives(
        ctx["objs"], {k: v for k, v in stats_by_key.items() if v})

    # ⑤ FORM vs MC 交叉口径（threshold=0 且无 bandwidth 类目标时同事件）
    supported = all(
        str(getattr(o.op, "value", o.op)) in
        ("max_below", "min_above", "mean_within") for o in ctx["objs"])
    if supported and threshold == 0.0:
        mc_pf = 1.0 - float(mc["yield_rate"])
        pf = float(form["pf"])
        report["pf_vs_mc"] = {
            "mc_pf": mc_pf,
            "mc_n": int(n_mc),
            "rel_diff": abs(pf - mc_pf) / max(abs(mc_pf), 1e-12),
            "note": "同事件口径（cost>0 ⇔ 违约）；MC 采样标准差 ~√(p(1-p)/n)"
                    "（1e4→~0.5%@p=0.5）——差值含 FORM 线性化误差",
        }
    else:
        report["pf_vs_mc"] = {
            "mc_pf": None, "rel_diff": None,
            "note": "事件口径不同（bandwidth 类目标/非零 threshold），"
                    "不做同事件对照（如实不硬比）",
        }
    return report
