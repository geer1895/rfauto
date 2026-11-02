"""v2 物理先验 NN 代理增量一：极点-留数头 + 无源性后验判据（W4-3 最小骨架）。

定位裁定（aurora_m W4-3，"按需维持"语义）：
    TODO §〇 "v2 物理先验 NN 代理（按需维持：极点-留数头/无源性/虚拟样本）"
    的第一增量（NNSurrogate，838f9d8）已落标量参数代理；本模块补"极点-留数
    头 + 无源性"最小骨架。裁定=有缺口、无即期生产消费方（calibration/
    active_learning/optimize/playground 消费链全部吃标量指标，无流程等待
    "参数→极点-留数→S 曲线"头）——按任务书走 c 支：最小骨架落位（numpy
    零新依赖）+ 触发条件登记，不硬造需求。触发条件（任一成立即升格实施）：
    ① 曲线级校准/优化战役需要"参数→S 曲线"代理且要求无源性可信输出；
    ② fno/deeponet/pod_rom 曲线代理消费链需要无源性降权（设计文档 §7.5
    TRUST/TRANSITION/EXTRAP 落地时，本模块 passivity_verdict 即判据源）；
    ③ macromodel 单数据集 vf 链需要参数化外推（邻域参数插值宏模型）。

形态（docs/surrogate_calibration_design.md §7.3"可微极点-留数输出头 + 无源性
约束"的最小 numpy 版）：
- 极点-留数头：H(s) = Σ_k r_k/(s - p_k) + d + e·s。极点基固定（频带内
  对数栅格布点的实极点 + 共轭复极点对，全部严格左半平面——头输出天然
  因果稳定，design doc §7.3 的物理先验语义）；每样本的留数/d/e 由固定
  基下复数最小二乘闭式读出（列均衡 + LAPACK gelsd，确定性零随机），
  参数→系数回归头默认闭式 ridge（可切 nn_model._MLP，固定种子）。
- 无源性后验判据（约束的后验形态，采样 S 矩阵直判）：带内逐频点
  σmax(S(f)) ≤ 1 + tol（tol 与 core.macromodel._PASSIVITY_TOL 单源），
  同时报告矩阵域缺陷量 λmin(I − SᴴS)。口径归一说明：任务书原文
  "σmax(I−SᴴS)≤1+eps"按 #118 裁判纪律归一到标准形——σmax(I−SᴴS)≤1+eps
  漏检 σmax(S)∈(1,√2] 的违例（λmax(SᴴS)=2 时缺陷谱含 ±1，被 1+eps
  容差吞掉），标准形 σmax(S)≤1+tol ⟺ λmin(I − SᴴS) ≥ −(2tol+tol²) 才是
  无源性的正确判据；eps=1e-9（#376 家法余量）承担"恰无源（无损单位阵
  至浮点误差）不误红"的数值零位角色，随 verdict 一并透出。
- 带边过冲守卫 + 参数-曲线一致性判据（T-N3，aurora_n W1-B；闭环 W4-3
  开放项的判据半边）：band_edge_verdict 把带边外推区预测对带内末端
  dB 趋势的偏离量化为 excursion 门（verdict 键 band_edge=
  ok|extrapolation_warn，带外无源性旁证复用 passivity_verdict 单源）；
  param_conflict_verdict 检测同参数异曲线冲突样本（virtual_samples 族 B
  的 α·S 语义可判定面：θ 读出对曲线线性 ⇒ θ_α=α·θ，冲突样本进 fit 会在
  θ 空间最小二乘折中——消费前预检，处置=低置信度权重或剔除）。两件
  纯判据零拟合路径改动——fit/fit_residues/头回归逐字节不动（before/after
  逐位等价钉在 runs/aurora_n/wave1_b/）。

与既有面的关系（复用优于自造）：
- 数据→有理模型的全流程拟合（含阶数搜索/无源化/SPICE 导出）走
  core/macromodel.py 的 skrf VectorFitting 链——本模块不重造 vector
  fitting；固定基线性读出是头的结构先验（LS 闭式），不是拟合器替代。
- 无源性容差 PASSIVITY_TOL 从 core.macromodel 导入（单源，本模块不给
  第二常量源）。

W4-4 接口预留（虚拟样本，不越界实现）：fit(samples) 与 SurrogateModel
契约同构（samples=[{"params": {...}, "metrics": {"s11_curve": 复数数组}}]），
虚拟样本生成器（锚点间 IDW/双线性插值 + 置信度加权，design doc §7.2）
产出同构样本字典直接追加进 samples 即可，本侧不做任何样本数假设。

确定性红线（AGENTS 7）：极点基/列均衡/LS/ridge 全链确定性；MLP 头固定
种子；同配置同数据两跑逐位一致（测试钉住）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.macromodel import PASSIVITY_TOL

from .base import SurrogateModel, surrogate_registry
from .nn_model import _MLP

__all__ = [
    "PoleResidueSurrogate",
    "band_edge_verdict",
    "default_pole_basis",
    "evaluate_pole_residue",
    "fit_residues",
    "param_conflict_verdict",
    "passivity_verdict",
]

#: 曲线样本在 metrics 里的键（复数 S11(f)，单位 Hz 栅格）。
CURVE_KEY = "s11_curve"
#: dB 下限（|S|=0 保护，与 core.macromodel._DB_FLOOR 同值同语义）。
_DB_FLOOR = 1e-30
#: 矩阵域缺陷量数值零位（#376 家法余量：恰无源模型的浮点误差不误红）。
_DEFECT_EPS = 1e-9


# ─── 极点基（确定性，严格左半平面） ───────────────────────────────────────────


def default_pole_basis(f_lo_hz: float, f_hi_hz: float, n_real_poles: int = 2,
                       n_cmplx_pairs: int = 3, zeta: float = 0.7) -> np.ndarray:
    """频带内对数栅格布点的固定极点基（rad/s，skrf 口径）。

    实极点 s=-ω；复极点成共轭对 s=-ζω ± jω√(1-ζ²)（ζ∈(0,1]，缺省 0.7），
    共轭两侧都入基使读出层保持线性。全部严格左半平面 → 头输出天然稳定。
    """
    if f_lo_hz <= 0 or f_hi_hz <= f_lo_hz:
        raise ValueError("default_pole_basis：要求 0 < f_lo_hz < f_hi_hz")
    if n_real_poles < 0 or n_cmplx_pairs < 0 or n_real_poles + n_cmplx_pairs == 0:
        raise ValueError("default_pole_basis：极点数组合非法")
    if not 0.0 < zeta <= 1.0:
        raise ValueError("default_pole_basis：zeta 必须在 (0, 1]")
    w_lo, w_hi = 2.0 * np.pi * float(f_lo_hz), 2.0 * np.pi * float(f_hi_hz)
    log_span = np.log(w_hi / w_lo)

    def _interior_w(n: int) -> np.ndarray:
        fracs = np.linspace(0.0, 1.0, n + 2)[1:-1]
        return w_lo * np.exp(fracs * log_span)

    poles: list[complex] = []
    for w in _interior_w(int(n_real_poles)):
        poles.append(complex(-w))
    for w in _interior_w(int(n_cmplx_pairs)):
        poles.append(complex(-zeta * w, w * np.sqrt(1.0 - zeta * zeta)))
        poles.append(complex(-zeta * w, -w * np.sqrt(1.0 - zeta * zeta)))
    return np.array(poles, dtype=complex)


# ─── 固定基线性读出（闭式 LS，列均衡，确定性） ────────────────────────────────


def _design_matrix(freq_hz: np.ndarray, poles: np.ndarray) -> np.ndarray:
    """H(s)=Σ r_k/(s-p_k)+d+e·s 的采样矩阵：[1/(s-p_k) ..., 1, s]。"""
    s = 2.0j * np.pi * np.asarray(freq_hz, dtype=float)
    cols = [1.0 / (s - p) for p in poles]
    cols.append(np.ones_like(s))
    cols.append(s)
    return np.column_stack(cols)


def fit_residues(freq_hz: np.ndarray, s_curve: np.ndarray,
                 poles: np.ndarray) -> dict[str, Any]:
    """固定极点基下读出 (residues, d, e)（复数最小二乘闭式解）。

    列均衡（各列归一化后再 lstsq）——极点列 ~1/ω（GHz 带 ~1e-10 量级）与
    e 列 s（~1e10 量级）跨 20 个数量级，不均衡则 gelsd 的 rcond 截断会吞掉
    留数列。确定性：同输入逐位同输出。
    """
    y = np.asarray(s_curve, dtype=complex)
    if y.ndim != 1 or len(y) != len(freq_hz):
        raise ValueError(
            f"fit_residues：s_curve 须为一维且与 freq_hz 等长（{len(freq_hz)}）")
    a = _design_matrix(freq_hz, poles)
    if a.shape[0] < a.shape[1] + 2:
        raise ValueError(
            f"fit_residues：频点数 {a.shape[0]} 不足以支撑 "
            f"{a.shape[1]} 个待求系数（需 ≥ {a.shape[1] + 2}）")
    col_norm = np.linalg.norm(a, axis=0)
    col_norm = np.where(col_norm == 0.0, 1.0, col_norm)
    theta_scaled, *_ = np.linalg.lstsq(a / col_norm[None, :], y, rcond=None)
    theta = theta_scaled / col_norm
    n_poles = len(poles)
    resid = y - a @ theta
    return {
        "poles": np.asarray(poles, dtype=complex),
        "residues": theta[:n_poles],
        "d": complex(theta[n_poles]),
        "e": complex(theta[n_poles + 1]),
        "rms": float(np.sqrt(np.mean(np.abs(resid) ** 2))),
    }


def evaluate_pole_residue(freq_hz: np.ndarray, poles: np.ndarray,
                          residues: np.ndarray, d: complex,
                          e: complex) -> np.ndarray:
    """极点-留数模型在 freq_hz（Hz）上的频响（带内解析延拓面）。"""
    a = _design_matrix(np.asarray(freq_hz, dtype=float), poles)
    theta = np.concatenate([np.asarray(residues, dtype=complex),
                            np.array([complex(d), complex(e)])])
    return a @ theta


def model_to_theta(model: dict[str, Any]) -> np.ndarray:
    """极点-留数模型 → 实系数向量 [Re(r), Im(r), Re(d), Im(d), Re(e), Im(e)]。"""
    residues = np.asarray(model["residues"], dtype=complex)
    return np.concatenate([residues.real, residues.imag,
                           np.array([model["d"].real, model["d"].imag,
                                     model["e"].real, model["e"].imag])])


def theta_to_model(theta: np.ndarray, poles: np.ndarray) -> dict[str, Any]:
    """model_to_theta 的逆映射（头回归输出 → 可评估模型）。"""
    n_poles = len(poles)
    theta = np.asarray(theta, dtype=float)
    if len(theta) != 2 * n_poles + 4:
        raise ValueError(
            f"theta_to_model：theta 维度 {len(theta)} ≠ 2·n_poles+4="
            f"{2 * n_poles + 4}")
    residues = theta[:n_poles] + 1.0j * theta[n_poles:2 * n_poles]
    d = complex(theta[2 * n_poles], theta[2 * n_poles + 1])
    e = complex(theta[2 * n_poles + 2], theta[2 * n_poles + 3])
    return {"poles": np.asarray(poles, dtype=complex), "residues": residues,
            "d": d, "e": e}


# ─── 无源性后验判据（采样 S 矩阵直判，macromodel 口径单源） ───────────────────


def _iter_member_mats(s: np.ndarray):
    """逐 (模型, 频点) 产出 m×m 矩阵——无源性逐频点成立，成员间不得联合
    SVD（联合会把独立模型/频点算成 sqrt(Σ|S_i|²) 的伪奇异值，物理错误）。"""
    arr = np.asarray(s, dtype=complex)
    if arr.ndim == 1:
        for k in range(arr.shape[0]):
            yield arr[k]  # 1-port：标量走快路径
    elif arr.ndim == 2:
        for i in range(arr.shape[0]):
            for k in range(arr.shape[1]):
                yield arr[i, k]  # 1-port 批
    elif arr.ndim == 3:
        if arr.shape[1] != arr.shape[2]:
            raise ValueError(
                f"passivity_verdict：S 矩阵须方阵，实得 {arr.shape}")
        for k in range(arr.shape[0]):
            yield arr[k]
    else:
        raise ValueError(
            f"passivity_verdict：S 须为 (n_freq,) / (n_model, n_freq) / "
            f"(n_freq, m, m)，实得 shape {arr.shape}")


def passivity_verdict(s: np.ndarray, tol: float = PASSIVITY_TOL) -> dict[str, Any]:
    """带内采样无源性直判（1-port 曲线 / 1-port 批 / (n_freq, m, m) 栈）。

    主判（与 core.macromodel 带内直判同口径）：max σmax(S(f)) ≤ 1 + tol
    （批输入取全批最大值——任一成员任一频点违例即整批判非无源）。
    旁证（矩阵域缺陷量）：min λmin(I − S(f)ᴴS(f))，无源 ⇔ ≥ 0；
    恰无源（无损，σmax=1 至浮点误差）时该值 ≈ -1e-15 ≥ -eps（#376 家法
    余量 1e-9=数值零位，不是判定阈值——判定阈值是 tol）。
    """
    if tol <= 0:
        raise ValueError("passivity_verdict：tol 必须为正")
    arr = np.asarray(s, dtype=complex)
    sigma_max = 0.0
    lam_min = np.inf
    for sk in _iter_member_mats(arr):
        if sk.ndim == 0:  # 1-port 快路径：σmax=|S|，缺陷=1-|S|²
            sig = float(abs(sk))
            lam = 1.0 - sig * sig
        else:
            sig = float(np.linalg.svd(sk, compute_uv=False)[0])
            defect = np.eye(sk.shape[0]) - sk.conj().T @ sk
            lam = float(np.linalg.eigvalsh(defect)[0])
        sigma_max = max(sigma_max, sig)
        lam_min = min(lam_min, lam)
    return {
        "passive": bool(sigma_max <= 1.0 + tol),
        "sigma_max_in_band": sigma_max,
        "lambda_min_i_minus_ssh": float(lam_min),
        "tol": float(tol),
        "defect_eps": _DEFECT_EPS,
        "n_freq": int(arr.shape[0] if arr.ndim in (1, 3) else arr.shape[1]),
    }


# ─── 带边过冲守卫（T-N3 判据面扩展；不改拟合路径） ───────────────────────────


def _linear_trend_db(freq_hz: np.ndarray, db: np.ndarray) -> tuple[float, float]:
    """闭式一阶最小二乘（dB 域 vs 频率，确定性零随机）。返回 (slope, intercept)。"""
    fm = float(freq_hz.mean())
    dm = float(db.mean())
    df = freq_hz - fm
    denom = float((df * df).sum())
    if denom <= 0.0:
        return 0.0, dm
    slope = float((df * (db - dm)).sum()) / denom
    return slope, dm - slope * fm


def band_edge_verdict(freq_hz: np.ndarray, s: np.ndarray,
                      f_lo_hz: float, f_hi_hz: float, *,
                      n_trend: int = 7, proximal_frac: float = 0.10,
                      max_dev_db: float = 3.0,
                      tol: float = PASSIVITY_TOL) -> dict[str, Any]:
    """带边外推区过冲守卫（W4-3 触发条件②的判据半边，T-N3；纯判据不拟合）。

    语义：极点-留数头带外解析延拓可能过冲（带边极点高 Q 振铃/e·s 线性项
    外推发散）——本判据把"带边外预测"对"带内末端趋势"的偏离量化为
    excursion（dB 域）：每个带边取带内末端 n_trend 点做闭式一阶 LS 趋势
    （dB vs 频率），外推到近带边外推区（|f−带边| ≤ proximal_frac·带边，
    "近带边"窗口——深外推区物理上本就偏离局部趋势，单独 flag 不进门），
    偏离超过 max_dev_db 即判 extrapolation_warn。带外无源性旁证复用
    passivity_verdict（单源 #296：σmax(S)≤1+tol）。

    输入：
        freq_hz: 评估栅格（Hz，1-D；须覆盖带内至少 n_trend 点，带外点
            可选——无带外点时如实 ok + n_out_of_band=0 不伪造）。
        s: 复数曲线 (n_freq,) 或 1-port 批 (n_model, n_freq)（批取逐成员
            最坏聚合成单 verdict，成员明细随 per_member_excursion_db）；
            多端口矩阵栈 (n_freq, m, m) 不支持——显式 ValueError 不静默。
        f_lo_hz / f_hi_hz: 训练频带边界（须 0 < f_lo < f_hi）。

    返回 verdict dict（band_edge=ok|extrapolation_warn 新键，同
    passivity_verdict 形态）：band_edge / excursion_db / threshold_db /
    n_trend / n_out_of_band / n_proximal / deep_extrapolation /
    passive_out_of_band / sigma_max_out_of_band / per_edge / tol；
    批输入另带 per_member_excursion_db。
    """
    if n_trend < 2:
        raise ValueError("band_edge_verdict：n_trend 至少为 2")
    if proximal_frac <= 0 or max_dev_db <= 0:
        raise ValueError("band_edge_verdict：proximal_frac/max_dev_db 须为正")
    if tol <= 0:
        raise ValueError("band_edge_verdict：tol 必须为正")
    f_lo_hz, f_hi_hz = float(f_lo_hz), float(f_hi_hz)
    if not 0.0 < f_lo_hz < f_hi_hz:
        raise ValueError("band_edge_verdict：要求 0 < f_lo_hz < f_hi_hz")
    freq = np.asarray(freq_hz, dtype=float)
    arr = np.asarray(s, dtype=complex)
    if freq.ndim != 1:
        raise ValueError(f"band_edge_verdict：freq_hz 须一维，实得 {freq.shape}")
    if arr.ndim == 1:
        members = [arr]
        batch = False
    elif arr.ndim == 2:
        members = [arr[i] for i in range(arr.shape[0])]
        batch = True
    else:
        raise ValueError(
            "band_edge_verdict：s 须为 (n_freq,) 或 (n_model, n_freq)"
            f"（多端口矩阵栈不支持），实得 shape {arr.shape}")
    for m in members:
        if m.shape != freq.shape:
            raise ValueError(
                f"band_edge_verdict：s 与 freq_hz 等长要求破坏"
                f"（{m.shape} vs {freq.shape}）")

    in_band = (freq >= f_lo_hz) & (freq <= f_hi_hz)
    if int(in_band.sum()) < n_trend:
        raise ValueError(
            f"band_edge_verdict：带内点 {int(in_band.sum())} < n_trend="
            f"{n_trend}（趋势段不足，判据不成立）")
    below = freq < f_lo_hz
    above = freq > f_hi_hz
    win_lo = (freq >= f_lo_hz * (1.0 - proximal_frac)) & below
    win_hi = (freq <= f_hi_hz * (1.0 + proximal_frac)) & above
    deep = bool((below & ~win_lo).any() or (above & ~win_hi).any())

    ib_idx = np.where(in_band)[0]
    trend_lo_idx = ib_idx[:n_trend]
    trend_hi_idx = ib_idx[-n_trend:]

    per_member_exc: list[float] = []
    sigma_oob = 0.0
    for m in members:
        exc_edges: list[float] = []
        for t_idx, j_idx in ((trend_lo_idx, win_lo), (trend_hi_idx, win_hi)):
            if not j_idx.any():
                exc_edges.append(0.0)
                continue
            slope, intercept = _linear_trend_db(
                freq[t_idx], _to_db(m[t_idx]))  # 带内末端 dB 趋势
            trend_pred = intercept + slope * freq[j_idx]
            exc_edges.append(float(np.max(
                np.abs(_to_db(m[j_idx]) - trend_pred))))
        per_member_exc.append(max(exc_edges))
        oob = below | above
        if oob.any():
            v = passivity_verdict(m[oob], tol=tol)
            sigma_oob = max(sigma_oob, float(v["sigma_max_in_band"]))
    excursion = max(per_member_exc) if per_member_exc else 0.0
    n_oob = int((below | above).sum())
    n_prox = int((win_lo | win_hi).sum())
    verdict: dict[str, Any] = {
        "band_edge": "extrapolation_warn" if excursion > max_dev_db else "ok",
        "excursion_db": excursion,
        "threshold_db": float(max_dev_db),
        "n_trend": int(n_trend),
        "n_out_of_band": n_oob,
        "n_proximal": n_prox,
        "deep_extrapolation": deep,
        "passive_out_of_band": (bool(sigma_oob <= 1.0 + tol)
                                if n_oob else None),
        "sigma_max_out_of_band": sigma_oob if n_oob else None,
        "proximal_frac": float(proximal_frac),
        "tol": float(tol),
        "per_edge": {
            "low": {"n_judged": int(win_lo.sum()),
                    "f_edge_hz": f_lo_hz,
                    "window_hz": [f_lo_hz * (1.0 - proximal_frac), f_lo_hz]},
            "high": {"n_judged": int(win_hi.sum()),
                     "f_edge_hz": f_hi_hz,
                     "window_hz": [f_hi_hz, f_hi_hz * (1.0 + proximal_frac)]},
        },
    }
    if batch:
        verdict["per_member_excursion_db"] = per_member_exc
    return verdict


# ─── 参数-曲线一致性判据（T-N3 port_scale 语义可判定面；纯判据不拟合） ────────


def param_conflict_verdict(
    samples: list[dict[str, Any]], *, curve_key: str = CURVE_KEY,
    rtol: float = 1e-3,
) -> dict[str, Any]:
    """同参数异曲线冲突样本检测（virtual_samples 族 B 的 α·S 语义可判定面）。

    背景（W4-4 族 B 诚实注记的判据半边）：``port_scale`` 族产出
    ``S_v = α·S_i`` 且 params 与锚点相同——对确定性"参数→曲线"头这是
    不可学习的冲突样本；pole_residue 头的读出层对曲线线性
    （fit_residues(α·S) = α·fit_residues(S)，θ_α=α·θ），同批进 fit 时
    头回归会在两组 θ 间最小二乘折中（等效把 α 摊进系数），不报错但
    语义如实的冲突。本判据在消费前预检：同参数组的曲线两两比对，
    相对差 > rtol 记冲突，并进一步判定冲突是否可用单个 α∈(0,1] 缩放
    解释（``port_scale_like``——LS 拟 α=Re⟨S_a,S_b⟩/⟨S_a,S_a⟩ 后残差
    ≤ rtol），全部冲突可缩放解释时 ``port_scale_like_all=True``。

    处置语义（判据面不改拟合，与本模块其余判据同纪律）：检出冲突时
    消费方应把 α·S 类样本配低置信度权重（poly_ridge/nn 的
    sample_weight_key=VIRTUAL_WEIGHT_KEY 通道，T-N2）或剔除出 fit；
    本函数只报告不修改样本。

    输入：SurrogateModel 契约同构样本列表（params 须全数值可转 float，
    同参数判定=逐键 float 精确相等——族 B 生成器逐字复制 params，近似
    重复参数不并组，宁可漏报不误报参数不同形的合法样本）。
    返回 verdict dict：verdict=consistent|conflict / n_samples /
    n_curve_samples / n_param_groups / n_conflict_pairs / conflicts
    （含 indices/rel_diff/alpha/port_scale_like）/ port_scale_like_all /
    curve_key / rtol。
    """
    if rtol <= 0:
        raise ValueError("param_conflict_verdict：rtol 必须为正")
    groups: dict[tuple, list[int]] = {}
    n_curve = 0
    for idx, smp in enumerate(samples):
        params = smp.get("params") or {}
        try:
            key = tuple(sorted((k, float(v)) for k, v in params.items()))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"param_conflict_verdict：样本 {idx} params 含不可转 "
                f"float 的值") from exc
        metrics = smp.get("metrics") or {}
        if curve_key in metrics:
            groups.setdefault(key, []).append(idx)
            n_curve += 1
    conflicts: list[dict[str, Any]] = []
    for _key, idxs in groups.items():
        if len(idxs) < 2:
            continue
        curves = [np.asarray(samples[i]["metrics"][curve_key],
                             dtype=complex) for i in idxs]
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ca, cb = curves[a], curves[b]
                if ca.shape != cb.shape:
                    conflicts.append({
                        "indices": [idxs[a], idxs[b]],
                        "rel_diff": float("inf"), "alpha": None,
                        "port_scale_like": False, "reason": "shape_mismatch"})
                    continue
                denom = max(float(np.linalg.norm(ca)), 1e-300)
                rel = float(np.linalg.norm(cb - ca)) / denom
                if rel <= rtol:
                    continue
                na = float(np.vdot(ca, ca).real)
                alpha = (float(np.vdot(ca, cb).real) / na
                         if na > 0.0 else None)
                like = False
                if alpha is not None and 0.0 < alpha <= 1.0:
                    resid = float(np.linalg.norm(cb - alpha * ca)) / max(
                        float(np.linalg.norm(cb)), 1e-300)
                    like = resid <= rtol
                conflicts.append({
                    "indices": [idxs[a], idxs[b]], "rel_diff": rel,
                    "alpha": alpha, "port_scale_like": like})
    like_all: bool | None = None
    if conflicts:
        like_all = all(c["port_scale_like"] for c in conflicts)
    return {
        "verdict": "conflict" if conflicts else "consistent",
        "n_samples": len(samples),
        "n_curve_samples": n_curve,
        "n_param_groups": len(groups),
        "n_conflict_pairs": len(conflicts),
        "conflicts": conflicts,
        "port_scale_like_all": like_all,
        "curve_key": curve_key,
        "rtol": float(rtol),
    }


# ─── 曲线代理（kind="pole_residue"，SurrogateModel 契约） ─────────────────────


def _to_db(curve: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(curve), _DB_FLOOR))


@surrogate_registry.register("pole_residue")
class PoleResidueSurrogate(SurrogateModel):
    """参数→极点-留数系数→S 曲线的物理先验代理（最小骨架）。

    契约与样本格式：
        samples = [{"params": {param: value},
                    "metrics": {"s11_curve": 复数 S11(f) 数组（Hz 栅格，
                                与 config 频带/点数一致）}}]
    曲线缺失/长度不符/非复数可转的行按基类契约忽略（对应真机失败 trial）。

    config:
        bounds: {param: (low, high)}（必填；参数线性映射到 [-1,1]）
        freq_grid_ghz: (f_lo, f_hi) 曲线频带（GHz，必填）
        n_freq: 训练栅格点数（默认 81，须 ≥ n_poles+4）
        n_real_poles / n_cmplx_pairs / zeta: 极点基形态（默认 2/3/0.7）
        head: "ridge"（缺省，闭式零随机）|"mlp"（复用 nn_model._MLP，固定种子）
        ridge_lambda / seed / hidden / epochs: 头超参

    predict(params) 返回带内标量派生指标 s11_db_max_in_band /
    s11_db_min_in_band（曲线代理不冒充 objectives 原生指标键，消费方以
    predict_curve / passivity_verdict 为主面）。
    """

    KIND = "pole_residue"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        bounds = self.config.get("bounds")
        if not bounds:
            raise ValueError("PoleResidueSurrogate：config['bounds'] 必填")
        self.bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds.items()}
        self.param_names = sorted(self.bounds)
        grid = self.config.get("freq_grid_ghz")
        if not grid or len(grid) != 2 or float(grid[1]) <= float(grid[0]):
            raise ValueError(
                "PoleResidueSurrogate：config['freq_grid_ghz'] 须为 "
                "(f_lo, f_hi) 且 f_lo < f_hi")
        self.f_lo_hz = float(grid[0]) * 1e9
        self.f_hi_hz = float(grid[1]) * 1e9
        self.n_freq = int(self.config.get("n_freq", 81))
        self.n_real_poles = int(self.config.get("n_real_poles", 2))
        self.n_cmplx_pairs = int(self.config.get("n_cmplx_pairs", 3))
        self.zeta = float(self.config.get("zeta", 0.7))
        self.head_kind = str(self.config.get("head", "ridge"))
        if self.head_kind not in ("ridge", "mlp"):
            raise ValueError("PoleResidueSurrogate：head 须为 'ridge'|'mlp'")
        self.ridge_lambda = float(self.config.get("ridge_lambda", 1e-8))
        self.seed = int(self.config.get("seed", 42))
        self.hidden = int(self.config.get("hidden", 24))
        self.epochs = int(self.config.get("epochs", 3000))
        self.lr = float(self.config.get("lr", 5e-3))
        # 极点基仅由 config 决定 → 构造期建立并校验容量（fail fast）
        self._poles = default_pole_basis(
            self.f_lo_hz, self.f_hi_hz, self.n_real_poles,
            self.n_cmplx_pairs, self.zeta)
        if self.n_freq < len(self._poles) + 3:
            raise ValueError(
                f"PoleResidueSurrogate：n_freq={self.n_freq} 不足以支撑 "
                f"{len(self._poles)} 极点基（需 ≥ {len(self._poles) + 3}）")
        self._freq_hz: np.ndarray | None = None
        self._net: _MLP | None = None
        self._w_ridge: np.ndarray | None = None
        self._theta_mean: np.ndarray | None = None
        self._theta_std: np.ndarray | None = None

    # ── 内部 ──
    def _norm_params(self, params: dict[str, float]) -> np.ndarray:
        x = []
        for k in self.param_names:
            lo, hi = self.bounds[k]
            half = 0.5 * (hi - lo)
            val = float(params.get(k, 0.5 * (lo + hi)))
            x.append((val - 0.5 * (lo + hi)) / (half if half else 1.0))
        return np.array(x, dtype=float)

    def _theta_of(self, params: dict[str, float]) -> np.ndarray:
        x = self._norm_params(params)
        if self.head_kind == "ridge":
            row = np.concatenate([np.array([1.0]), x])
            theta_std = row @ self._w_ridge
        else:
            theta_std = self._net.forward(x[None, :])[0]
        return theta_std * self._theta_std + self._theta_mean

    def _n_theta(self) -> int:
        return 2 * len(self._poles) + 4

    # ── SurrogateModel 契约 ──
    def fit(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if not samples:
            raise ValueError("PoleResidueSurrogate.fit：无样本")
        self._freq_hz = np.linspace(self.f_lo_hz, self.f_hi_hz, self.n_freq)
        xs: list[np.ndarray] = []
        thetas: list[np.ndarray] = []
        models: list[dict[str, Any]] = []
        readout_rms: list[float] = []
        for sample in samples:
            metrics = sample.get("metrics") or {}
            raw = metrics.get(CURVE_KEY)
            if raw is None:
                continue
            try:
                curve = np.asarray(raw, dtype=complex)
            except (TypeError, ValueError):
                continue
            if curve.ndim != 1 or len(curve) != self.n_freq:
                continue
            model = fit_residues(self._freq_hz, curve, self._poles)
            models.append(model)
            xs.append(self._norm_params(sample.get("params") or {}))
            thetas.append(model_to_theta(model))
            readout_rms.append(model["rms"])
        if not thetas:
            raise ValueError(
                f"PoleResidueSurrogate.fit：无有效 {CURVE_KEY} 曲线样本")
        x_mat = np.vstack(xs)
        theta_mat = np.vstack(thetas)
        self._theta_mean = theta_mat.mean(0)
        self._theta_std = theta_mat.std(0) + 1e-12
        theta_std_mat = (theta_mat - self._theta_mean) / self._theta_std
        if self.head_kind == "ridge":
            x_aug = np.column_stack([np.ones(len(x_mat)), x_mat])
            penalty = np.eye(x_aug.shape[1]) * self.ridge_lambda
            penalty[0, 0] = 0.0  # 截距不正则
            self._w_ridge = np.linalg.solve(
                x_aug.T @ x_aug + penalty, x_aug.T @ theta_std_mat)
            self._net = None
        else:
            self._net = _MLP(len(self.param_names), self._n_theta(),
                             self.hidden, self.seed)
            for _ in range(self.epochs):
                self._net.adam_step(x_mat, theta_std_mat, 1e-4, self.lr)
            self._w_ridge = None
        readout_stack = np.vstack([
            evaluate_pole_residue(self._freq_hz, self._poles,
                                  m["residues"], m["d"], m["e"])
            for m in models])
        info = self._mark_fitted(len(thetas))
        info.update({
            "n_curves": len(thetas),
            "n_poles": len(self._poles),
            "head": self.head_kind,
            "max_fit_rms": max(readout_rms),
            "passivity": passivity_verdict(readout_stack),
        })
        return info

    def predict_curve(self, params: dict[str, float],
                      freq_ghz: np.ndarray | None = None) -> np.ndarray:
        """预测参数对应的复数 S11(f)（freq_ghz 缺省=训练栅格；带内解析延拓）。"""
        if not self._fitted:
            raise RuntimeError("PoleResidueSurrogate.predict_curve：先 fit")
        theta = self._theta_of(params)
        model = theta_to_model(theta, self._poles)
        freq_hz = (self._freq_hz if freq_ghz is None
                   else np.asarray(freq_ghz, dtype=float) * 1e9)
        return evaluate_pole_residue(freq_hz, self._poles, model["residues"],
                                     model["d"], model["e"])

    def predict(self, params: dict[str, float]) -> dict[str, Any]:
        curve = self.predict_curve(params)
        db = _to_db(curve)
        return {"s11_db_max_in_band": float(db.max()),
                "s11_db_min_in_band": float(db.min())}

    def passivity_verdict(self, params: dict[str, float],
                          n_dense: int = 201) -> dict[str, Any]:
        """预测模型的无源性后验判据（带内密集栅格）。"""
        if not self._fitted:
            raise RuntimeError("PoleResidueSurrogate.passivity_verdict：先 fit")
        f_dense = np.linspace(self.f_lo_hz, self.f_hi_hz, max(int(n_dense), 2))
        curve = self.predict_curve(params, f_dense / 1e9)
        return passivity_verdict(curve)

    def band_edge_verdict(self, params: dict[str, float], *,
                          ext_frac: float = 0.10, n_ext: int = 121,
                          n_trend: int = 7,
                          max_dev_db: float = 3.0) -> dict[str, Any]:
        """预测模型的带边外推过冲守卫（T-N3；评估栅格向带外扩 ext_frac）。

        与 passivity_verdict 同形态的判据入口：栅格 = [f_lo·(1−ext_frac),
        f_hi·(1+ext_frac)] 均匀 n_ext 点，预测曲线交给模块级
        band_edge_verdict（近带边外推窗=ext_frac，与扩展比一致）。
        判据面不改拟合——predict_curve 读出的就是 fit 固化的头。
        """
        if not self._fitted:
            raise RuntimeError("PoleResidueSurrogate.band_edge_verdict：先 fit")
        f_ext = np.linspace(self.f_lo_hz * (1.0 - float(ext_frac)),
                            self.f_hi_hz * (1.0 + float(ext_frac)),
                            max(int(n_ext), 2))
        curve = self.predict_curve(params, f_ext / 1e9)
        return band_edge_verdict(
            f_ext, curve, self.f_lo_hz, self.f_hi_hz, n_trend=n_trend,
            proximal_frac=float(ext_frac), max_dev_db=float(max_dev_db))

    def uncertainty(self, params: dict[str, float]) -> None:
        """无原生逐点不确定度（单头确定性模型，不伪造 σ——#122 诚实纪律）。"""
        return None
