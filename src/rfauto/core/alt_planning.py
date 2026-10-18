"""PT-4 ALT（Accelerated Life Testing）加速寿命试验换算面（纯函数内核）。

round18 规格（docs/research_expansion_20261002_round18.md §四 PT-4）：
多应力 Weibull 似然 ln η = a + b/T + 置信带；与 arrhenius_af 闭式对拍。
本模块与 core/aging.py 互补不重复：AF 闭式只消费 aging 既有实现
（arrhenius_af / coffin_manson / K_B_EV_PER_K / INV_K_K_PER_EV，只读），
本模块增量 = ①Coffin-Manson 循环域加速因子与应力→使用域等效换算；
②Arrhenius-Weibull 多应力 MLE（ln η = a + b/T，支持右删失）+ η 与 AF
的对数尺度置信带（δ 法，观测 Fisher 信息）；③零失效 ALT 验证试验计划
（目标置信度 + 加速因子 → 试验时长/样本量，β=1 退化为指数 χ² 验证）。

公式来源（#118 铁律：来源写 docstring，裁判=独立来源不自证）：

- Arrhenius-Weibull 模型 ln η = a + b/T：W.Q. Meeker & L.A. Escobar,
  《Statistical Methods for Reliability Data》(1998) §18.2；W. Nelson
  《Accelerated Testing》(1990)。b 与激活能关系 Ea = b·k_B（k_B =
  8.617333262e-5 eV/K，CODATA 2018，消费 aging 常数）；因此拟合模型
  蕴含的 AF = exp[b·(1/T_use − 1/T_stress)] 与 aging.arrhenius_af
  （Ea = b·k_B）逐恒等式对拍（单测钉，#122 口径）。
- 循环域加速因子 AF_cyc = (ΔT_stress/ΔT_use)^q：由 aging.coffin_manson
  （N_f = C·ΔT⁻ᵠ，Coffin 1954 / Manson 1965，IPC-9701 口径）的比值
  恒等式导出（C 约去），本模块不重新实现 N_f。
- 零失效（success-run）验证计划：n 件在应力域考核 t_test 零失效的
  二项精确 (1−C) 置信下界 R^n = 1−C，配 Weibull 时间尺度换算
  （η_stress = η_use/AF）。推论（本模块 plan_alt_demo docstring 给
  逐行推导）：t_test = η_req·((−ln(1−C))/n)^(1/β)/AF；β=1 时退化为
  指数 χ² 验证 T_total = θ·(−ln(1−C))（χ²_{2,C} = 2·(−ln(1−C)) 恒等
  式）。口径：Meeker & Escobar (1998) ch.7 演示试验 + JEDEC JESD47G
  零失效验收惯例（与 aging.py 同源出处）。
- 置信带：MLE 渐近正态 + δ 法（对数尺度区间，天然恒正），观测 Fisher
  信息（NLL 数值 Hessian，中心差分），Meeker & Escobar (1998) App. B。
- XD-14 ALT 模型族补全（2026-10-18，池 P3 圈定件）：广义 log-linear
  Weibull 引擎 ln η = c0 + Σ_j c_j·z_j（列变换=链接函数，统一 Arrhenius/
  逆幂律/Eyring/Peck/温度-非温度五族）+ 严格 Eyring AF 闭式 +
  标注竞争风险（多失效模式序列系统，逐模式 2 参 Weibull MLE）。
  出处：Meeker & Escobar (1998) ch.18（加速模型族：Arrhenius §18.2 同上、
  Eyring/温度-非温度/湿度族同章）；Peck (1986)（温湿度幂律）；竞争风险
  序列系统似然 = Meeker & Escobar (1998) ch.3 多失效模式口径（各模式
  似然独立分解，标注已知时总 NLL = Σ 模式 NLL，恒等式单测钉）。

诚实边界（沿 aging.py 纪律）：竞争失效/机理耦合项 UNKNOWN、不做认证级
寿命结论——计划面工具。全部返回 JSON 可序列化 float/dict（ndarray 已
转嵌套 list）。数值 0.0 合法（判缺失一律 is not None，#364④）；bool
显式拒收（float(True)=1.0 静默污染统计，df7+⑯）。纯算法零 IO；不进
calculators 注册表（F-C 域内约定）。

数值口径：MLE 内部以 x = (a, b' , ln β) 优化，b' = b/1000、自变量
u' = 1000/T（量级 ~2.5-3.1，规避 b~Ea/k~5800 的病态度量）；返回前
协方差阵经 D = diag(1, 1000, 1) 换算回 (a, b, ln β) 原度量。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from rfauto.core.aging import (
    INV_K_K_PER_EV,
    K_B_EV_PER_K,
    arrhenius_af,
    coffin_manson,
)

__all__ = [
    "af_ci",
    "coffin_manson_af",
    "demo_reliability_lower",
    "ea_from_slope",
    "equivalent_use_cycles",
    "equivalent_use_time",
    "eta_at_temperature",
    "eta_ci_at_temperature",
    "eyring_af",
    "fit_arrhenius_weibull",
    "fit_eyring_weibull",
    "fit_inverse_power_weibull",
    "fit_loglinear_weibull",
    "fit_peck_weibull",
    "fit_temperature_nonthermal_weibull",
    "fit_weibull_competing_risks",
    "min_samples_for_demo",
    "plan_alt_demo",
    "slope_from_ea",
]

# MLE 内部度量换算因子：b' = b / _B_SCALE，u' = _B_SCALE / T
_B_SCALE = 1000.0
# 数值 Hessian 步长：h_i = _HESS_REL·max(1, |x_i|)（中心差分，逐坐标）
_HESS_REL = 1e-3


# ─── 参数守卫（与 aging.py 同纪律：bool 显式拒收）───────────────────────────


def _num(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: float, name: str) -> float:
    """有限正 float（>0），非法即显式报错。"""
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _open01(value: float, name: str) -> float:
    """严格开区间 (0,1) 内的概率参数（置信度/可靠度目标），端点即报错。"""
    out = _num(value, name)
    if not 0.0 < out < 1.0:
        raise ValueError(f"{name} 必须在开区间 (0,1) 内")
    return out


def _count(value: int, name: str) -> int:
    """正整数样本量守卫（接受整数值 float，拒绝 bool/非整值/非正）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} 必须为整数值")
    out = int(value)
    if out < 1:
        raise ValueError(f"{name} 必须 >=1")
    return out


# ─── 加速因子面：消费 aging 闭式，不重复实现 ────────────────────────────────


def coffin_manson_af(delta_t_use_k: float, delta_t_stress_k: float, q: float) -> float:
    """Coffin-Manson 循环域加速因子 AF_cyc = (ΔT_stress/ΔT_use)^q。

    语义与 aging.arrhenius_af 对齐：1 次应力摆幅循环折合的使用域等效
    循环数（ΔT_stress > ΔT_use → AF>1 加速；< 则 AF<1 减速试验，数值
    合法）。

    推导（消费 aging.coffin_manson 不重复实现）：N_f = C·ΔT⁻ᵠ →
    AF = N_f(use)/N_f(stress) = [C·ΔT_u⁻ᵠ]/[C·ΔT_s⁻ᵠ] = (ΔT_s/ΔT_u)^q，
    C 约去。实现按 C=1 比值逐项调用 aging.coffin_manson（守卫与符号
    单一来源）。来源：Coffin (1954)/Manson (1965)，IPC-9701 口径。
    """
    dt_u = _pos(delta_t_use_k, "delta_t_use_k")
    dt_s = _pos(delta_t_stress_k, "delta_t_stress_k")
    q_ = _num(q, "q")
    if q_ < 0.0:
        raise ValueError("q 必须 >=0（与 aging.coffin_manson 同守卫）")
    return coffin_manson(1.0, dt_u, q_) / coffin_manson(1.0, dt_s, q_)


def equivalent_use_time(t_stress_h: float, af: float) -> float:
    """应力域时长 → 使用域等效时长 t_use = t_stress·AF（Arrhenius 域）。

    af 一般来自 aging.arrhenius_af（>0 即合法；AF<1 为减速试验，等效
    时长反而缩短，数值合法不拦）。单位自洽（h/cycles 皆可，函数不换算
    单位；参数名 _h 沿 aging.py 惯例默认小时口径）。
    """
    t = _nonneg_h(t_stress_h, "t_stress_h")
    af_ = _pos(af, "af")
    return t * af_


def equivalent_use_cycles(
    n_stress_cycles: float, delta_t_use_k: float, delta_t_stress_k: float, q: float
) -> float:
    """应力摆幅循环数 → 使用摆幅等效循环数 n_use = n_stress·AF_cyc。

    消费 coffin_manson_af；ΔT 单位 K（全摆幅，与 aging.coffin_manson
    同口径）。
    """
    n = _nonneg_h(n_stress_cycles, "n_stress_cycles")
    af = coffin_manson_af(delta_t_use_k, delta_t_stress_k, q)
    return n * af


def _nonneg_h(value: float, name: str) -> float:
    """有限非负 float（时长/循环数允许 0，#364④）。"""
    out = _num(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


# ─── Arrhenius 斜率 ↔ 激活能桥（ln η = a + b/T 与闭式 AF 的对拍枢纽）────────


def ea_from_slope(b_per_k: float) -> float:
    """Arrhenius-Weibull 斜率 b（K）→ 激活能 Ea = b·k_B（eV）。

    ln η = a + b/T 与 η ∝ exp(Ea/kT) 逐项对取 → b = Ea/k_B。
    k_B 消费 aging.K_B_EV_PER_K（CODATA 2018）。
    """
    b = _num(b_per_k, "b_per_k")
    if b < 0.0:
        raise ValueError("b_per_k 必须 >=0（单调Arrhenius 退化假设，负斜率即报错）")
    return b * K_B_EV_PER_K


def slope_from_ea(ea_ev: float) -> float:
    """激活能 Ea（eV）→ Arrhenius 斜率 b = Ea/k_B（K）；ea_from_slope 逆。"""
    ea = _num(ea_ev, "ea_ev")
    if ea < 0.0:
        raise ValueError("ea_ev 必须 >=0")
    return ea * INV_K_K_PER_EV


def eta_at_temperature(a: float, b_per_k: float, t_k: float) -> float:
    """Arrhenius-Weibull 特征寿命 η(T) = exp(a + b/T)。

    a 无量纲（ln 时间），b_per_k 单位 K，t_k 绝对温度 K（>0）。时间
    单位由 a 吸收（数据以 h 拟合则 η 为 h）。
    """
    a_ = _num(a, "a")
    b_ = _num(b_per_k, "b_per_k")
    t = _pos(t_k, "t_k")
    return math.exp(a_ + b_ / t)


# ─── Arrhenius-Weibull 多应力 MLE（规格：ln η=a+b/T+置信带）─────────────────


def _nll_alt(x: np.ndarray, u: np.ndarray, t: np.ndarray, failed: np.ndarray) -> float:
    """负对数似然（x = (a, b', ln β)，u = 1000/T，η = exp(a + b·u)）。

    失效点贡献 ln f = ln β + (β−1)·ln t − β·ln η − (t/η)^β；右删失点
    贡献 ln S = −(t/η)^β。非有限（溢出）→ +inf 让优化器回退。
    """
    a, b, log_beta = (float(x[0]), float(x[1]), float(x[2]))
    beta = math.exp(log_beta)
    log_eta = a + b * u
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        z = np.exp(beta * (np.log(t) - log_eta))  # (t/η)^β
        ll_failed = log_beta + (beta - 1.0) * np.log(t) - beta * log_eta - z
        ll_cens = -z
    ll = np.where(failed, ll_failed, ll_cens)
    if not bool(np.all(np.isfinite(ll))):
        return math.inf
    return -float(np.sum(ll))


def _hessian_fd(
    f: Any, x: np.ndarray, steps: np.ndarray
) -> np.ndarray:
    """中心差分数值 Hessian（确定性；对角=三点、非对角=四点公式）。"""
    n = x.size
    fx = f(x)
    hess = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i, n):
            if i == j:
                xp = x.copy()
                xp[i] += steps[i]
                xm = x.copy()
                xm[i] -= steps[i]
                hess[i, i] = (f(xp) - 2.0 * fx + f(xm)) / (steps[i] * steps[i])
            else:
                xpp = x.copy()
                xpp[i] += steps[i]
                xpp[j] += steps[j]
                xpm = x.copy()
                xpm[i] += steps[i]
                xpm[j] -= steps[j]
                xmp = x.copy()
                xmp[i] -= steps[i]
                xmp[j] += steps[j]
                xmm = x.copy()
                xmm[i] -= steps[i]
                xmm[j] -= steps[j]
                val = (f(xpp) - f(xpm) - f(xmp) + f(xmm)) / (
                    4.0 * steps[i] * steps[j]
                )
                hess[i, j] = val
                hess[j, i] = val
    return hess


def _cov_from_nll(
    x_hat: np.ndarray, u: np.ndarray, t: np.ndarray, failed: np.ndarray
) -> np.ndarray | None:
    """观测 Fisher 信息逆（协方差阵）；非正定/奇异 → None（如实降级）。"""
    steps = np.array([_HESS_REL * max(1.0, abs(v)) for v in x_hat])
    hess = _hessian_fd(lambda z: _nll_alt(z, u, t, failed), x_hat, steps)
    try:
        cov = np.linalg.inv(hess)
    except np.linalg.LinAlgError:
        return None
    if not bool(np.all(np.isfinite(cov))):
        return None
    if float(np.min(np.linalg.eigvalsh(0.5 * (cov + cov.T)))) <= 0.0:
        return None
    return cov


def fit_arrhenius_weibull(
    t_stress_k: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """多应力 Weibull MLE：ln η = a + b/T，公共形状 β，观测信息置信阵。

    t_stress_k：各观测的应力温度（K，>0，至少 2 个不同水平——单水平
    b 不可辨识）；t_obs_h：失效/删失时间（>0，单位自洽，h 惯例）；
    status：1=失效（缺省全失效）、0=右删失，逐点对应；confidence：
    后续 CI 缺省置信度 ∈(0,1)。

    返回 dict（全 JSON 可序列化）：a、b_per_k（K）、ea_ev（=b·k_B，
    即拟合激活能；b<0 时 None——负斜率=寿命随应力上升，非 Arrhenius
    单调退化，Ea 不定义，模型参数仍如实返回由调用方裁决）、beta、nll、
    n_obs/n_failures/n_censored、stress_levels_k（去重升序）、cov
    （3×3 嵌套 list，序 (a, b, ln β)，经 D=diag(1,1000,1) 换算回原
    度量）、cov_labels、confidence。数值病态（Hessian 非正定）→
    cov=None 如实降级，CI 函数显式报错。

    模型出处：Meeker & Escobar (1998) §18.2；优化 Nelder-Mead
    （确定性，无随机源）；Hessian 中心差分（步长 1e-3·max(1,|x|)）。
    """
    ts = np.asarray(t_stress_k, dtype=float)
    tobs = np.asarray(t_obs_h, dtype=float)
    if ts.ndim != 1 or ts.size == 0:
        raise ValueError("t_stress_k 必须为一维非空序列")
    if tobs.shape != ts.shape:
        raise ValueError("t_obs_h 与 t_stress_k 形状必须一致")
    if status is None:
        failed = np.ones(ts.size, dtype=bool)
    else:
        st = np.asarray(status)
        if st.shape != ts.shape:
            raise ValueError("status 与 t_stress_k 形状必须一致")
        stf = st.astype(float)
        if not bool(np.all(np.isin(stf, (0.0, 1.0)))):
            raise ValueError("status 只允许 0（右删失）/1（失效）")
        failed = stf == 1.0
    conf = _open01(confidence, "confidence")
    for name, arr in (("t_stress_k", ts), ("t_obs_h", tobs)):
        if not bool(np.all(np.isfinite(arr))) or float(np.min(arr)) <= 0.0:
            raise ValueError(f"{name} 必须全为有限正数")
    n_levels = int(np.unique(ts).size)
    if n_levels < 2:
        raise ValueError("至少 2 个不同应力温度（单水平 b 不可辨识）")
    n_fail = int(np.sum(failed))
    if n_fail < 2:
        raise ValueError("至少 2 个失效观测（β 不可辨识）")
    if ts.size < 4:
        raise ValueError("观测数须 >=4（3 参数 MLE 的最低样本下限）")

    u = _B_SCALE / ts
    y = np.log(tobs)
    b0, a0 = (float(v) for v in np.polyfit(u[failed], y[failed], 1))
    x0 = np.array([a0, b0, math.log(2.0)])
    res = minimize(
        _nll_alt,
        x0,
        args=(u, tobs, failed),
        method="Nelder-Mead",
        options={"maxiter": 20000, "maxfev": 20000, "xatol": 1e-8, "fatol": 1e-10},
    )
    if not bool(res.success):
        raise ValueError(f"MLE 未收敛（Nelder-Mead）：{res.message}")
    x_hat = np.asarray(res.x, dtype=float)
    a_hat = float(x_hat[0])
    b_hat = float(x_hat[1]) * _B_SCALE
    beta_hat = math.exp(float(x_hat[2]))
    cov_inner = _cov_from_nll(x_hat, u, tobs, failed)
    cov_out: list[list[float]] | None = None
    if cov_inner is not None:
        # (a, b', ln β) → (a, b, ln β)：D = diag(1, 1000, 1)，Σ = DΣ'D
        scale = np.array([1.0, _B_SCALE, 1.0])
        cov_out = [
            [float(scale[i] * cov_inner[i, j] * scale[j]) for j in range(3)]
            for i in range(3)
        ]
    return {
        "a": a_hat,
        "b_per_k": b_hat,
        "ea_ev": ea_from_slope(b_hat) if b_hat >= 0.0 else None,
        "beta": beta_hat,
        "nll": float(res.fun),
        "n_obs": int(ts.size),
        "n_failures": n_fail,
        "n_censored": int(ts.size) - n_fail,
        "stress_levels_k": [float(v) for v in np.unique(ts)],
        "cov": cov_out,
        "cov_labels": ["a", "b_per_k", "log_beta"],
        "confidence": conf,
    }


def _fit_cov(fit: dict[str, Any]) -> np.ndarray:
    cov = fit.get("cov")
    if cov is None:
        raise ValueError("该拟合 cov=None（数值病态如实降级），置信带不可用")
    arr = np.asarray(cov, dtype=float)
    if arr.shape != (3, 3):
        raise ValueError("cov 形状必须为 3x3")
    return arr


def eta_ci_at_temperature(
    fit: dict[str, Any], t_k: float, confidence: float | None = None
) -> dict[str, float]:
    """拟合模型在温度 T 的特征寿命 η 及其 (1−C) 对数尺度置信区间（δ 法）。

    ln η = a + b/T，梯度 g = (1, 1/T, 0)，Var(ln η) = g·Σ·g'；区间
    η·exp(±z·√Var)，z = Φ⁻¹(1−C/2)。返回
    {t_k, eta, se_log, ci_lo, ci_hi, confidence}。出处：Meeker &
    Escobar (1998) App. B（观测信息渐近正态）。
    """
    t = _pos(t_k, "t_k")
    conf = fit["confidence"] if confidence is None else _open01(confidence, "confidence")
    cov = _fit_cov(fit)
    grad = np.array([1.0, 1.0 / t, 0.0])
    var_log = float(grad @ cov @ grad)
    if var_log <= 0.0 or not math.isfinite(var_log):
        raise ValueError("Var(ln η) 非正，置信带不可用")
    eta = eta_at_temperature(fit["a"], fit["b_per_k"], t)
    z = float(norm.ppf(0.5 + conf / 2.0))
    half = z * math.sqrt(var_log)
    return {
        "t_k": t,
        "eta": eta,
        "se_log": math.sqrt(var_log),
        "ci_lo": eta * math.exp(-half),
        "ci_hi": eta * math.exp(half),
        "confidence": conf,
    }


def af_ci(
    fit: dict[str, Any],
    t_use_k: float,
    t_stress_k: float,
    confidence: float | None = None,
) -> dict[str, float]:
    """拟合模型蕴含的 Arrhenius 加速因子及其置信区间。

    点估计消费 aging.arrhenius_af（Ea = ea_from_slope(b)，规格"与
    arrhenius_af 闭式对拍"的落点——两口径逐恒等式同值，单测钉）。
    ln AF = b·(1/T_u − 1/T_s) 对 b 线性 → Var(ln AF) = x²·Var(b)
    （x = 1/T_u − 1/T_s），对数尺度区间恒正。返回
    {af, ci_lo, ci_hi, confidence, t_use_k, t_stress_k}。
    """
    tu = _pos(t_use_k, "t_use_k")
    tss = _pos(t_stress_k, "t_stress_k")
    conf = fit["confidence"] if confidence is None else _open01(confidence, "confidence")
    cov = _fit_cov(fit)
    x = 1.0 / tu - 1.0 / tss
    var_log = x * x * float(cov[1, 1])
    if var_log <= 0.0 or not math.isfinite(var_log):
        raise ValueError("Var(ln AF) 非正，置信带不可用")
    af = arrhenius_af(ea_from_slope(fit["b_per_k"]), tu, tss)
    z = float(norm.ppf(0.5 + conf / 2.0))
    half = z * math.sqrt(var_log)
    return {
        "af": af,
        "ci_lo": af * math.exp(-half),
        "ci_hi": af * math.exp(half),
        "confidence": conf,
        "t_use_k": tu,
        "t_stress_k": tss,
    }


# ─── 零失效 ALT 验证试验计划（目标置信度 + AF → 时长/样本量）────────────────
#
# 推导（逐行，供锚测对拍）：n 件在应力域各考核 t_test、零失效，作为
# η_use 的函数其似然 P = R_stress(t_test)^n = exp[−n·(t_test·AF/η_u)^β]
# （η_stress = η_use/AF）。(1−C) 置信下界取 P = 1−C：
#   η_use ≥ AF·t_test·(n/(−ln(1−C)))^(1/β)。
# 验证目标 R_target@t_m ⟺ η_req = t_m/(−ln R_target)^(1/β)。令下界
# ≥ η_req 解出计划公式（plan_alt_demo）：
#   t_test = η_req·((−ln(1−C))/n)^(1/β)/AF = (t_m/AF)·[(−ln(1−C)) /
#            (n·(−ln R_target))]^(1/β)。
# β=1 退化为指数 χ² 验证：T_total = n·t_test·AF = θ_req·(−ln(1−C))
# （χ²_{2,C}/2 = −ln(1−C) 恒等式，单测以 scipy.stats.chi2 第三路径钉）。


def plan_alt_demo(
    t_use_target_h: float,
    r_target: float,
    confidence: float,
    af: float,
    beta: float,
    n_samples: int,
) -> dict[str, Any]:
    """零失效 ALT 验证计划：给定样本量 → 应力域所需试验时长。

    t_use_target_h：使用域任务时长（单位自洽，h 惯例）；r_target：该
    任务时长的可靠度目标 ∈(0,1)；confidence：验证置信度 ∈(0,1)；
    af：应力→使用加速因子（>0，一般 aging.arrhenius_af 或本模块
    coffin_manson_af；AF<1 合法但试验时长反超任务时长）；beta：Weibull
    形状（>0，消费 aging docstring 经验域 1.8-10）；n_samples：样本量
    （>=1）。

    返回 {test_time_stress_h, eta_req_use_h, r_target, confidence, af,
    beta, n_samples, rule:"zero_failure"}。演示判据见本节头注推导。
    """
    t_m = _pos(t_use_target_h, "t_use_target_h")
    r = _open01(r_target, "r_target")
    conf = _open01(confidence, "confidence")
    af_ = _pos(af, "af")
    b = _pos(beta, "beta")
    n = _count(n_samples, "n_samples")
    eta_req = t_m / (-math.log(r)) ** (1.0 / b)
    t_test = eta_req * ((-math.log(1.0 - conf)) / n) ** (1.0 / b) / af_
    return {
        "test_time_stress_h": t_test,
        "eta_req_use_h": eta_req,
        "r_target": r,
        "confidence": conf,
        "af": af_,
        "beta": b,
        "n_samples": n,
        "rule": "zero_failure",
    }


def demo_reliability_lower(
    t_test_stress_h: float,
    n_samples: int,
    af: float,
    beta: float,
    confidence: float,
    t_use_target_h: float,
) -> dict[str, Any]:
    """零失效考核结果的演示下界：应力域零失效 → 使用域可靠度置信下界。

    与 plan_alt_demo 互逆（同一推导的观测侧）：η_L_use = AF·t_test·
    (n/(−ln(1−C)))^(1/β)，R_L(t_m) = exp[−(t_m/η_L_use)^β]。返回
    {r_lower, eta_lower_use_h, eta_lower_stress_h, confidence,
    t_use_target_h, n_samples, af, beta}。守卫：t_test >=0（0 时长
    零失效 → R_L=0 合法边界，不报错）。
    """
    t_test = _nonneg_h(t_test_stress_h, "t_test_stress_h")
    n = _count(n_samples, "n_samples")
    af_ = _pos(af, "af")
    b = _pos(beta, "beta")
    conf = _open01(confidence, "confidence")
    t_m = _pos(t_use_target_h, "t_use_target_h")
    eta_lower = af_ * t_test * (n / (-math.log(1.0 - conf))) ** (1.0 / b)
    r_lower = math.exp(-((t_m / eta_lower) ** b)) if eta_lower > 0.0 else 0.0
    return {
        "r_lower": r_lower,
        "eta_lower_use_h": eta_lower,
        "eta_lower_stress_h": eta_lower / af_,
        "confidence": conf,
        "t_use_target_h": t_m,
        "n_samples": n,
        "af": af_,
        "beta": b,
    }


def min_samples_for_demo(
    t_test_stress_h: float,
    t_use_target_h: float,
    r_target: float,
    confidence: float,
    af: float,
    beta: float,
) -> dict[str, Any]:
    """零失效 ALT 验证计划（反向）：给定考核时长 → 最少样本量。

    由 plan 公式反解 n_exact = (−ln(1−C))·(t_m/(AF·t_test))^β /
    (−ln R_target)；n_min = ceil(n_exact)（浮点噪声 1e-12 容差），
    并给出 n_min 下的达成演示下界（demo_reliability_lower，>=
    r_target 由构造保证）。返回 {n_exact, n_min, r_lower_achieved,
    test_time_at_n_min_h}。
    """
    t_test = _pos(t_test_stress_h, "t_test_stress_h")
    t_m = _pos(t_use_target_h, "t_use_target_h")
    r = _open01(r_target, "r_target")
    conf = _open01(confidence, "confidence")
    af_ = _pos(af, "af")
    b = _pos(beta, "beta")
    n_exact = (
        (-math.log(1.0 - conf))
        * (t_m / (af_ * t_test)) ** b
        / (-math.log(r))
    )
    n_min = max(1, math.ceil(n_exact - 1e-12))
    achieved = demo_reliability_lower(t_test, n_min, af_, b, conf, t_m)
    planned = plan_alt_demo(t_m, r, conf, af_, b, n_min)
    return {
        "n_exact": n_exact,
        "n_min": n_min,
        "r_lower_achieved": achieved["r_lower"],
        "test_time_at_n_min_h": planned["test_time_stress_h"],
    }


# ─── XD-14：广义 log-linear Weibull 引擎（链接函数=列变换）──────────────────
#
# 统一形态 ln η = c0 + Σ_j c_j·z_j（z=应力变换列），五族换列不换引擎：
#   Arrhenius  z=[1000/T]；逆幂律 z=[ln V]；Peck z=[1000/T, ln RH]；
#   温度-非温度 z=[1000/T, ln V]；广义 Eyring z=[1000/T, ln T]。
# 温度列沿用本模块既有度量约定（u=1000/T，规避 b~Ea/k~5800 病态度量，
# b_per_k=(1000/T 列系数)·1000）；其余列经引擎内部逐列缩放
# s_j=max(1, max|z_j|) 条件化，返回系数/协方差换算回传入列原度量。


def _nll_loglin(theta: np.ndarray, z: np.ndarray, t: np.ndarray,
                failed: np.ndarray) -> float:
    """广义负对数似然：theta = (c0…cp, ln β)，ln η = c0 + z·c[1:]。

    z 形状 (n, p)，p=0 时退化为两参 Weibull（截距即 ln η）。似然项与
    _nll_alt 同构（失效 ln f / 右删失 ln S）；非有限 → +inf 让优化器
    回退。
    """
    c = np.asarray(theta[:-1], dtype=float)
    log_beta = float(theta[-1])
    beta = math.exp(log_beta)
    log_eta = c[0] + z @ c[1:]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        zeta = np.exp(beta * (np.log(t) - log_eta))
        ll_failed = log_beta + (beta - 1.0) * np.log(t) - beta * log_eta - zeta
        ll_cens = -zeta
    ll = np.where(failed, ll_failed, ll_cens)
    if not bool(np.all(np.isfinite(ll))):
        return math.inf
    return -float(np.sum(ll))


def _obs_arrays(t_obs_h: Any, status: Any) -> tuple[np.ndarray, np.ndarray]:
    """观测时间/删失标记收敛（与 fit_arrhenius_weibull 同守卫口径）。"""
    tobs = np.asarray(t_obs_h, dtype=float)
    if tobs.ndim != 1 or tobs.size == 0:
        raise ValueError("t_obs_h 必须为一维非空序列")
    if not bool(np.all(np.isfinite(tobs))) or float(np.min(tobs)) <= 0.0:
        raise ValueError("t_obs_h 必须全为有限正数")
    if status is None:
        failed = np.ones(tobs.size, dtype=bool)
    else:
        st = np.asarray(status)
        if st.shape != tobs.shape:
            raise ValueError("status 与 t_obs_h 形状必须一致")
        stf = st.astype(float)
        if not bool(np.all(np.isin(stf, (0.0, 1.0)))):
            raise ValueError("status 只允许 0（右删失）/1（失效）")
        failed = stf == 1.0
    return tobs, failed


def _fit_loglin_core(z: np.ndarray, tobs: np.ndarray, failed: np.ndarray,
                     conf: float) -> dict[str, Any]:
    """广义 log-linear Weibull MLE 核心（确定性 Nelder-Mead + 数值 Hessian）。

    逐列缩放 s_j=max(1,max|z_j|) 条件化（zs=z/s）；OLS 起步；返回的
    coefficients=**传入列原度量**的系数（c_j = c'_j/s_j，与
    fit_arrhenius_weibull"报告 1/T 基系数"口径对齐），协方差经
    Σ = D⁻¹Σ'D⁻¹（D=diag(1,s…,1)）换算回原度量。数值病态（Hessian
    非正定）→ cov=None 如实降级。
    """
    n, p = z.shape
    scale = np.array([
        max(1.0, float(np.max(np.abs(z[:, j]))))
        for j in range(p)
    ])
    zs = z / scale[None, :]
    y = np.log(tobs[failed])
    design = np.concatenate(
        [np.ones((int(np.sum(failed)), 1)), zs[failed]], axis=1)
    coef0 = np.linalg.lstsq(design, y, rcond=None)[0]
    x0 = np.concatenate([coef0, [math.log(2.0)]])
    res = minimize(
        _nll_loglin,
        x0,
        args=(zs, tobs, failed),
        method="Nelder-Mead",
        options={"maxiter": 20000, "maxfev": 20000, "xatol": 1e-8,
                 "fatol": 1e-10},
    )
    if not bool(res.success):
        raise ValueError(f"MLE 未收敛（Nelder-Mead）：{res.message}")
    x_hat = np.asarray(res.x, dtype=float)
    cov_scaled = _cov_from_nll_loglin(x_hat, zs, tobs, failed)
    cov_out: list[list[float]] | None = None
    if cov_scaled is not None:
        inv_s = np.concatenate([[1.0], 1.0 / scale, [1.0]])
        cov_out = [
            [float(inv_s[i] * cov_scaled[i, j] * inv_s[j])
             for j in range(p + 2)]
            for i in range(p + 2)
        ]
    coefficients = [float(v) for v in x_hat[:-1]]
    coefficients[1:] = [c / float(s)
                        for c, s in zip(coefficients[1:], scale, strict=True)]
    return {
        "coefficients": coefficients,
        "beta": math.exp(float(x_hat[-1])),
        "nll": float(res.fun),
        "n_obs": int(n),
        "n_failures": int(np.sum(failed)),
        "n_censored": int(n - np.sum(failed)),
        "cov": cov_out,
        "confidence": conf,
    }


def _cov_from_nll_loglin(x_hat: np.ndarray, zs: np.ndarray, t: np.ndarray,
                         failed: np.ndarray) -> np.ndarray | None:
    """广义引擎的观测信息协方差（数值病态 → None 如实降级）。"""
    steps = np.array([_HESS_REL * max(1.0, abs(v)) for v in x_hat])
    hess = _hessian_fd(lambda q: _nll_loglin(q, zs, t, failed), x_hat, steps)
    try:
        cov = np.linalg.inv(hess)
    except np.linalg.LinAlgError:
        return None
    if not bool(np.all(np.isfinite(cov))):
        return None
    if float(np.min(np.linalg.eigvalsh(0.5 * (cov + cov.T)))) <= 0.0:
        return None
    return cov


def fit_loglinear_weibull(
    design: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
    term_names: Any = None,
) -> dict[str, Any]:
    """广义 log-linear Weibull MLE：ln η = c0 + Σ_j c_j·z_j（XD-14 引擎）。

    design：(n, p) 已变换应力列（p=0 合法=两参 Weibull 截距拟合；列
    变换即链接函数——Arrhenius [1000/T]、逆幂律 [ln V]、Peck
    [1000/T, ln RH] 等，包装函数族见同节）；t_obs_h/status：同
    fit_arrhenius_weibull 口径（>=2 失效，>=4 观测）；term_names：p 个
    列名（缺省 z1…zp）。

    返回 dict（全 JSON 可序列化）：coefficients=[c0,c1…cp]、term_names、
    beta、nll、n_obs/n_failures/n_censored、cov((p+2)² 嵌套 list，序
    (c0,c1…cp,ln β)，已换算回原度量)、cov_labels、confidence。数值病态
    → cov=None 如实降级。近似共线列 → Hessian 奇异同路降级（不猜）。
    """
    conf = _open01(confidence, "confidence")
    zs = np.asarray(design, dtype=float)
    if zs.ndim != 2:
        raise ValueError("design 必须为二维 (n, p)（p=0 合法）")
    if not bool(np.all(np.isfinite(zs))):
        raise ValueError("design 必须全为有限数")
    tobs, failed = _obs_arrays(t_obs_h, status)
    if tobs.size != zs.shape[0]:
        raise ValueError("design 行数必须与 t_obs_h 等长")
    if tobs.size < 4:
        raise ValueError("观测数须 >=4（MLE 最低样本下限）")
    if int(np.sum(failed)) < 2:
        raise ValueError("至少 2 个失效观测（β 不可辨识）")
    p = zs.shape[1]
    if term_names is None:
        names = [f"z{j + 1}" for j in range(p)]
    else:
        names = [str(v) for v in term_names]
        if len(names) != p:
            raise ValueError("term_names 长度必须与 design 列数一致")
    core = _fit_loglin_core(zs, tobs, failed, conf)
    core["term_names"] = names
    core["cov_labels"] = ["const", *names, "log_beta"]
    return core


# ─── XD-14 包装族：链接函数=列变换（出处见模块头注 XD-14 条）────────────────


def fit_inverse_power_weibull(
    v: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """逆幂律 Weibull MLE：η = exp(a + exponent·ln V)（XD-14）。

    v：非热应力（电压/功率/电流等，>0）；exponent = ln V 列系数，
    **<0 为期望退化方向**（应力升寿命降）；>0 = 寿命随应力上升，非
    单调退化，参数如实返回由调用方裁决（与 fit_arrhenius_weibull
    b<0 同纪律）。出处：Meeker & Escobar (1998) ch.18 逆幂律。
    """
    vv = np.asarray(v, dtype=float)
    if vv.ndim != 1 or not bool(np.all(np.isfinite(vv))) or float(np.min(vv)) <= 0.0:
        raise ValueError("v 必须为一维有限正数序列")
    out = fit_loglinear_weibull(
        np.log(vv)[:, None], t_obs_h, status, confidence,
        term_names=["ln_v"])
    out["a"] = out["coefficients"][0]
    out["exponent"] = out["coefficients"][1]
    out["model"] = "inverse_power"
    return out


def fit_peck_weibull(
    t_k: Any,
    rh: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """Peck 温湿度 Weibull MLE：ln η = a + b/T + c_rh·ln RH（XD-14）。

    rh：相对湿度（0<RH<=1）；c_rh（humidity_exponent）期望 <0（湿度升
    寿命降），>0 如实返回由调用方裁决。出处：Peck (1986)（温湿度
    幂律；Meeker & Escobar (1998) ch.18 同章表述）。
    """
    tt, rhv = np.asarray(t_k, dtype=float), np.asarray(rh, dtype=float)
    for name, arr in (("t_k", tt), ("rh", rhv)):
        if arr.ndim != 1 or not bool(np.all(np.isfinite(arr))):
            raise ValueError(f"{name} 必须为一维有限序列")
        if float(np.min(arr)) <= 0.0:
            raise ValueError(f"{name} 必须 >0")
    if float(np.max(rhv)) > 1.0:
        raise ValueError("rh 为相对湿度（0<RH<=1）")
    z = np.stack([_B_SCALE / tt, np.log(rhv)], axis=1)
    out = fit_loglinear_weibull(z, t_obs_h, status, confidence,
                                term_names=["inv_t_1000", "ln_rh"])
    out["a"] = out["coefficients"][0]
    out["b_per_k"] = out["coefficients"][1] * _B_SCALE
    out["ea_ev"] = (ea_from_slope(out["b_per_k"])
                    if out["b_per_k"] >= 0.0 else None)
    out["humidity_exponent"] = out["coefficients"][2]
    out["model"] = "peck"
    return out


def fit_temperature_nonthermal_weibull(
    t_k: Any,
    v: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """温度-非温度双应力 Weibull MLE：ln η = a + b/T + c_v·ln V（XD-14）。

    v：非热应力（电压等，>0）；c_v（voltage_exponent）期望 <0，>0 如实
    返回由调用方裁决。出处：Meeker & Escobar (1998) ch.18
    temperature-nonthermal 关系。
    """
    tt, vv = np.asarray(t_k, dtype=float), np.asarray(v, dtype=float)
    for name, arr in (("t_k", tt), ("v", vv)):
        if arr.ndim != 1 or not bool(np.all(np.isfinite(arr))):
            raise ValueError(f"{name} 必须为一维有限序列")
        if float(np.min(arr)) <= 0.0:
            raise ValueError(f"{name} 必须 >0")
    z = np.stack([_B_SCALE / tt, np.log(vv)], axis=1)
    out = fit_loglinear_weibull(z, t_obs_h, status, confidence,
                                term_names=["inv_t_1000", "ln_v"])
    out["a"] = out["coefficients"][0]
    out["b_per_k"] = out["coefficients"][1] * _B_SCALE
    out["ea_ev"] = (ea_from_slope(out["b_per_k"])
                    if out["b_per_k"] >= 0.0 else None)
    out["voltage_exponent"] = out["coefficients"][2]
    out["model"] = "temperature_nonthermal"
    return out


def fit_eyring_weibull(
    t_k: Any,
    t_obs_h: Any,
    status: Any = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """广义 Eyring Weibull MLE：ln η = a + b/T + c_t·ln T（XD-14）。

    广义形态两系数皆拟合（出处：Meeker & Escobar (1998) ch.18 Eyring
    模型族）；c_t（ln_t_coefficient）无预设符号。**严格** Eyring
    （ln T 系数固定 −1）的加速因子闭式 = eyring_af（消费
    aging.arrhenius_af，恒等式单测钉）。
    """
    tt = np.asarray(t_k, dtype=float)
    if tt.ndim != 1 or not bool(np.all(np.isfinite(tt))) or float(np.min(tt)) <= 0.0:
        raise ValueError("t_k 必须为一维有限正数序列")
    z = np.stack([_B_SCALE / tt, np.log(tt)], axis=1)
    out = fit_loglinear_weibull(z, t_obs_h, status, confidence,
                                term_names=["inv_t_1000", "ln_t"])
    out["a"] = out["coefficients"][0]
    out["b_per_k"] = out["coefficients"][1] * _B_SCALE
    out["ea_ev"] = (ea_from_slope(out["b_per_k"])
                    if out["b_per_k"] >= 0.0 else None)
    out["ln_t_coefficient"] = out["coefficients"][2]
    out["model"] = "eyring_generalized"
    return out


def eyring_af(ea_ev: float, t_use_k: float, t_stress_k: float) -> float:
    """严格 Eyring 加速因子 AF = (T_s/T_u)·exp[(Ea/k)(1/T_u − 1/T_s)]。

    由 η ∝ (1/T)·exp(Ea/kT) 的比值恒等式导出（1/T 前置项相除得
    T_s/T_u，指数项=aging.arrhenius_af）——消费既有闭式不重复实现
    （本模块 coffin_manson_af 同范式）。T_stress==T_use 或 Ea==0 时
    AF=(T_s/T_u)≠1（Eyring 的 1/T 前置项贡献，如实非单位）。
    """
    ea = _num(ea_ev, "ea_ev")
    if ea < 0.0:
        raise ValueError("ea_ev 必须 >=0")
    tu = _pos(t_use_k, "t_use_k")
    ts = _pos(t_stress_k, "t_stress_k")
    return (ts / tu) * arrhenius_af(ea, tu, ts)


def fit_weibull_competing_risks(
    t_obs_h: Any,
    status: Any,
    mode_labels: Any,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """标注竞争风险（多失效模式序列系统）逐模式 Weibull MLE（XD-14）。

    模式标注已知（物理定位/检查归类）时序列系统似然逐模式独立分解：
    模式 m 的失效点贡献 ln f_m，**其余全部观测**（他模式失效+右删失）
    对 m 贡献 ln S_m——总 NLL = Σ_m NLL_m（构造恒等式，单测钉）。
    每模式 = 截距 log-linear 两参 Weibull MLE（共享 _fit_loglin_core，
    单模式退化 ≡ fit_loglinear_weibull(design (n,0))，恒等式单测钉）。

    mode_labels：逐观测失效模式标注（str/int）；右删失点的标注不参与
    似然失效项但仍须给出（同长度校验）。要求每模式 >=2 个失效（β 可
    辨识，同本模块全局口径）。

    返回 {modes: {label: {a, eta, beta, nll, n_failures}},
    total_nll, n_obs, n_failures, confidence}（全 JSON 可序列化）。
    诚实边界：模式未标注/机理耦合 = UNKNOWN，不做认证级寿命结论
    （模块头注同口径）。
    """
    conf = _open01(confidence, "confidence")
    tobs, failed = _obs_arrays(t_obs_h, status)
    labels_raw = np.asarray(mode_labels)
    if labels_raw.shape != tobs.shape:
        raise ValueError("mode_labels 与 t_obs_h 形状必须一致")
    labels = [str(v) for v in labels_raw.tolist()]
    modes_out: dict[str, dict[str, Any]] = {}
    total_nll = 0.0
    n_fail_total = 0
    for label in sorted(set(labels)):
        fail_m = failed & np.array([v == label for v in labels])
        n_fail_m = int(np.sum(fail_m))
        if n_fail_m < 2:
            raise ValueError(
                f"模式 {label!r} 失效数 {n_fail_m} <2（β 不可辨识）")
        core = _fit_loglin_core(
            np.zeros((tobs.size, 0), dtype=float), tobs, fail_m, conf)
        a_m = core["coefficients"][0]
        modes_out[label] = {
            "a": a_m,
            "eta": math.exp(a_m),
            "beta": core["beta"],
            "nll": core["nll"],
            "n_failures": n_fail_m,
        }
        total_nll += core["nll"]
        n_fail_total += n_fail_m
    return {
        "modes": modes_out,
        "total_nll": total_nll,
        "n_obs": int(tobs.size),
        "n_failures": n_fail_total,
        "confidence": conf,
    }
