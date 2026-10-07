"""RB-ALG-2：量化约束阵列综合 = MIP 精确解（Phase3 W3-E，2026-10-05）。

问题
====
给定阵元数 N、副瓣电平声明值 SLL、移相器 b-bit（相位码 Q=2^b 全码本）、
衰减器 G 档（每档 atten_step_db dB）、阵元开关（可选），求**逐元离散码字**
（开关/衰减档/相位码），使阵列方向图在副瓣区的峰值最小、同时主瓣（扫描
方向 u0）相干增益损失不超过 max_mainlobe_loss_db。

混合整数线性规划（MILP）精确形式
================================
参考锥削 A_n（缺省 Dolph-Chebyshev，实非负）为理想幅度；逐元 one-hot 二元
变量 y_{n,c}（c=(s,g,q) 遍历开关×衰减档×相位码，Σ_c y_{n,c}=1），实现复权

    w_n = Σ_c y_{n,c} · s·A_n·10^(−g·atten_step_db/20)·e^{j2πq/Q}

方向图 F(u)=Σ_n w_n·e^{jπ·2d·(u−u0)·n_d}（d=spacing_lambda，线性于 y）。
目标（spec §7.2 明文两分支的 **min 量化误差** 分支）：

    min Σ_n |w_n − A_n·e^{j0}|²  =  min Σ_{n,c} y_{n,c}·d_{n,c}

d_{n,c}=|W_{n,c}−A_n|² 为列常数（目标线性）。**不用 min-PSLL 分支的实测
依据**：连续相位可在网格点完美对消 → LP 对偶界≈0 → HiGHS 证不动任何
相对 gap（N=16 b=4 实测 >4min 不收敛，probe 2026-10-05）。
约束（全部线性）：
- 副瓣区切平面（定值水平）：Re(F(u_i)·e^{−jθ_k}) ≤ ρ_sl，
  ρ_sl=10^(sll/20)·ΣA_n，θ_k=2πk/K——**保守侧**外逼近（切平面在圆外），
  任意可行解的 |F(u_i)| ≤ ρ_sl；K=16 时线性化保守带
  ≤ 10·log10(1/cos(π/16)) ≈ 0.166dB（< spec §7.4 的 0.2dB 带预声明）；
- 主瓣下界（单线性约束，内逼近的安全方向）：Re(F(u0)) ≥ ρ0，
  ρ0 = (ΣA_n)·10^(−max_mainlobe_loss_db/20)——投影 ≤ 模长，保证
  |F(u0)| ≥ ρ0（参考相位实正，全局相位自由度被钉在参考方向，属可行域
  收紧的线性化选择，docstring 如实声明）。

求解与确定性
============
scipy.optimize.milp（HiGHS）。零新依赖（scipy 1.18.1 venv 实测 import OK，
宏图注记"零新依赖"兑现）。HiGHS 对同一输入确定性（G15 逐字节复跑钉）；
time_limit_s 缺省 None（不设墙钟上限，正常规模秒-分级；G15 fixture 用
小规模使求解瞬完，不受墙钟扰动）。

规模带（spec §7.2）：16-64 元秒-分级；b=6×64 元约束矩阵内存 ~GB 级不建
议（用 b=4）。>128 元线性化带内分解另立（不进本件）。

不可行（spec 过紧，spec §7.4 风险③）：如实返回 ok=False（不凑）；CALC
壳层转 ValueError（service ok=False 通道）。

出口
====
``quantized_array_milp`` 返回确定性 dict（无墙钟/迭代计数等非确定字段——
G15 确定性复跑钉要求）；回代 PSLL 为真非线性口径（稠密网格实测，
非线性化目标值）；码字表直连
``firmware_export.beam_codeword_table`` / ``beam_backsub_audit``（PT-5/PT-6
出口，端到端钉在 test_w3_e_quantized_milp.py）。
"""
from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "linearized_peak_field",
    "quantized_array_milp",
    "sidelobe_grid",
]

_TINY = 1e-12


def _validate_positive_int(value: Any, name: str, minimum: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须为整数，收到 {value!r}") from None
    if v != value or v < minimum:
        raise ValueError(f"{name} 必须为 ≥{minimum} 的整数，收到 {value!r}")
    return v


def _reference_taper(n_elements: int, sidelobe_level_db: float,
                     reference_weights) -> np.ndarray:
    if reference_weights is None:
        from rfauto.core.array_synthesis import chebyshev_weights

        return chebyshev_weights(n_elements, sidelobe_level_db)
    w = np.asarray(reference_weights, dtype=float).ravel()
    if w.size != n_elements:
        raise ValueError(
            f"reference_weights 长度 {w.size} != n_elements {n_elements}")
    if not np.all(np.isfinite(w)) or np.any(w < 0.0) or w.max() <= 0.0:
        raise ValueError(
            "reference_weights 须为有限非负实数且不全为零（衰减码本以其为基）")
    return w / w.max()


def sidelobe_grid(n_elements: int, spacing_lambda: float, scan_u0: float,
                  mainlobe_half_u: float | None,
                  n_points: int,
                  reference_weights=None) -> np.ndarray:
    """副瓣约束网格（确定性）：主瓣区 [u0−h, u0+h] 之外的可见区均匀采样，
    负/正两段各 n_points//2 点。

    h（主瓣半宽）缺省=**参考锥削方向图第一零点**的自动探测（锥削主瓣比
    均匀阵宽，固定系数会把网格落进主瓣肩上造成伪不可行——chebyshev
    −30dB@N=16 实测肩点超约束 3.7dB，probe 2026-10-05）；显式传
    mainlobe_half_u 时用显式值。探测失败回退 1.6×均匀阵第一零点 1/(N·d)。
    """
    if mainlobe_half_u is not None:
        half = float(mainlobe_half_u)
    else:
        if reference_weights is None:
            from rfauto.core.array_synthesis import chebyshev_weights

            taper = chebyshev_weights(n_elements, -30.0)
        else:
            taper = np.asarray(reference_weights, dtype=float).ravel()
        half = _reference_mainlobe_half_u(taper, spacing_lambda, scan_u0)
    lo, hi = -1.0 + scan_u0, 1.0 + scan_u0
    ml_lo, ml_hi = scan_u0 - half, scan_u0 + half
    if ml_lo <= lo + _TINY or ml_hi >= hi - _TINY:
        raise ValueError(
            f"主瓣半宽 {half:.4g} 吞没可见区 [{lo:.4g},{hi:.4g}]，"
            "调小 mainlobe_half_u")
    n_half = max(8, int(n_points) // 2)
    neg = np.linspace(lo, ml_lo, n_half, endpoint=False)
    pos = np.linspace(ml_hi, hi, n_half, endpoint=True)
    return np.concatenate([neg, pos])


def _reference_mainlobe_half_u(taper: np.ndarray, spacing_lambda: float,
                               scan_u0: float) -> float:
    """参考锥削方向图第一零点（主瓣半宽）自动探测：稠密扫描 |F_ref| 的
    首个局部极小 ×1.05 余量；无极小回退 1.6×均匀阵第一零点。"""
    n = taper.size
    u1 = 1.0 / (n * spacing_lambda)
    u = scan_u0 + np.linspace(0.02 * u1, 4.0 * u1, 4001)
    psi = 2.0 * np.pi * spacing_lambda * (u - scan_u0)
    field = np.abs(np.exp(1j * np.outer(psi, np.arange(n))) @ taper)
    pk = np.nonzero((field[1:-1] <= field[:-2])
                    & (field[1:-1] <= field[2:]))[0] + 1
    if pk.size == 0:
        return 1.6 * u1
    return float(1.05 * (u[pk[0]] - scan_u0))


def linearized_peak_field(weights_complex, grid, spacing_lambda: float,
                          scan_u0: float, n_tangent: int) -> float:
    """给定（已实现的）复权在线性化口径下的峰值副瓣场（MILP 目标同式）：
    max_{i,k} Re(F(u_i)·e^{−jθ_k})，θ_k=2πk/K。穷举对拍用（与 MILP 同参）。"""
    w = np.asarray(weights_complex, dtype=complex).ravel()
    u = np.asarray(grid, dtype=float)
    theta = 2.0 * np.pi * np.arange(int(n_tangent)) / int(n_tangent)
    psi = 2.0 * np.pi * spacing_lambda * (u - scan_u0)
    field = np.exp(1j * np.outer(psi, np.arange(w.size))) @ w
    rot = np.exp(-1j * theta)[None, :]
    return float(np.max(np.real(field[:, None] * rot)))


def quantized_array_milp(
    n_elements: int,
    sidelobe_level_db: float,
    *,
    n_bits: int = 4,
    atten_steps: int = 1,
    atten_step_db: float = 0.5,
    element_switch: bool = False,
    spacing_lambda: float = 0.5,
    scan_u0: float = 0.0,
    max_mainlobe_loss_db: float = 1.0,
    max_sl_degradation_db: float = 1.0,
    mainlobe_half_u: float | None = None,
    n_sidelobe_points: int | None = None,
    n_tangent: int = 16,
    mip_rel_gap: float = 1e-4,
    level_tol_db: float | None = None,
    sl_level_offset_db: float | None = None,
    time_limit_s: float | None = None,
    reference_weights=None,
) -> dict[str, Any]:
    """量化约束阵列综合 = MILP 精确解（模块 docstring 为权威口径）。

    目标 = spec §7.2 两分支中的 **min 量化误差**（缺省）：副瓣切平面约束
    水平=声明电平+max_sl_degradation_db（劣化容忍带），在此水平下最小化
    Σ|w_n−A_n|²（逐码列常数→线性目标、LP 界紧、秒级）。参考锥削自身满足
    带内约束时全零码即最优（量化劣化=0，如实报告）。

    **min-PSLL 分支（opt-in）**：level_tol_db 显式给出（如 0.5）时启用
    约束水平确定性二分（内层每步=上面那只 min-误差真 MIP）——min-PSLL
    直接作线性目标不可求解（LP 对偶界≈0，HiGHS 证不动任何相对 gap，
    N=16 b=4 实测 >4min，probe 2026-10-05）；二分近可行边界的步可能慢
    （生产用配 time_limit_s）。单水平直通模式：sl_level_offset_db 显式
    （可负=比声明更深，强制非平凡解）供穷举对拍与确定性复跑钉。

    返回 dict（确定性字段；不可行时 ok=False+reason，不抛异常——内核语义
    完整返回诊断；CALC 壳层负责转 service ok=False 通道）。
    """
    from scipy.optimize import Bounds, LinearConstraint, milp

    n = _validate_positive_int(n_elements, "n_elements", 2)
    bits = _validate_positive_int(n_bits, "n_bits", 1)
    if bits > 8:
        raise ValueError(
            f"n_bits ≤ 8（码本 2^b×G×2 膨胀），收到 {n_bits!r}")
    steps = _validate_positive_int(atten_steps, "atten_steps", 1)
    step_db = float(atten_step_db)
    if not np.isfinite(step_db) or step_db < 0.0:
        raise ValueError(
            f"atten_step_db 必须为非负有限值，收到 {atten_step_db!r}")
    sll = float(sidelobe_level_db)
    if not np.isfinite(sll) or sll >= 0.0:
        raise ValueError(
            f"sidelobe_level_db 必须为负的有限值（dB），收到 {sidelobe_level_db!r}")
    d = float(spacing_lambda)
    if not np.isfinite(d) or d <= 0.0:
        raise ValueError(
            f"spacing_lambda 必须为正的有限值，收到 {spacing_lambda!r}")
    u0 = float(scan_u0)
    if not np.isfinite(u0) or abs(u0) > 1.0:
        raise ValueError(f"scan_u0 必须落在 [-1,1]，收到 {scan_u0!r}")
    loss_db = float(max_mainlobe_loss_db)
    if not np.isfinite(loss_db) or loss_db < 0.0:
        raise ValueError(
            f"max_mainlobe_loss_db 必须为非负有限值，收到 {max_mainlobe_loss_db!r}")
    deg_db = float(max_sl_degradation_db)
    if not np.isfinite(deg_db) or deg_db < 0.0:
        raise ValueError(
            f"max_sl_degradation_db 必须为非负有限值，收到 "
            f"{max_sl_degradation_db!r}")
    k_tan = _validate_positive_int(n_tangent, "n_tangent", 2)
    taper = _reference_taper(n, sll, reference_weights)

    n_grid = int(n_sidelobe_points) if n_sidelobe_points is not None \
        else min(720, max(60, 6 * n))
    ml_half = float(mainlobe_half_u) if mainlobe_half_u is not None \
        else _reference_mainlobe_half_u(taper, d, u0)
    grid = sidelobe_grid(n, d, u0, ml_half, n_grid)

    q_levels = 2 ** bits
    codes: list[tuple[int, int, int]] = []   # 逐码 (s, g, q)
    for s_code in ((0, 1) if element_switch else (1,)):
        for g in range(steps):
            for q in range(q_levels):
                codes.append((s_code, g, q))
    n_codes = len(codes)
    sw_arr = np.asarray([c[0] for c in codes], dtype=float)
    at_arr = np.asarray([c[1] for c in codes], dtype=float)
    ph_arr = np.asarray([c[2] for c in codes], dtype=float)

    # ── 变量：y (n×n_codes)，无连续变量 ────────────────────────────────
    n_var = n * n_codes
    alpha = sw_arr * 10.0 ** (-at_arr * step_db / 20.0)
    code_w = taper[:, None] * alpha[None, :] \
        * np.exp(1j * 2.0 * np.pi * ph_arr[None, :] / q_levels)
    col_w = code_w.ravel()                    # 长度 n*n_codes，列序一致
    # 内层目标（min-误差，LP 界紧）：Σ_n |w_n − A_n e^{j0}|² 逐码列常数。
    # 外层目标（min-PSLL，spec §7.2 第一分支）经**约束水平确定性二分**实现：
    # min-PSLL 直接作线性目标时 LP 对偶界≈0（网格点连续相位可完美对消），
    # HiGHS 证不动任何相对 gap（N=16 b=4 实测 >4min 不收敛，probe
    # 2026-10-05）；二分序列的内层每步都是真 MIP，外层为确定性一维求根
    # （与 bayliss_weights 膨胀精化同方法论）。
    ref_sq = (taper ** 2)[:, None]
    code_err = np.real(code_w * np.conj(code_w)) - 2.0 * np.real(
        code_w * taper[:, None]) + ref_sq
    cost = np.maximum(code_err, 0.0).ravel()

    # ── 约束矩阵（水平无关，仅 ub 随二分水平变化）──────────────────────
    # 副瓣切平面：Re(F(u_i)·e^{−jθ_k}) ≤ ΣA·10^((sll+a)/20)（**保守侧**
    # 外逼近，|F| ≤ 水平）；主瓣投影下界 Re(F(u0)) ≥ ρ0（投影 ≤ 模长，
    # 保证 |F(u0)| ≥ ρ0；参考相位实正，钉全局相位自由度）。
    psi_grid = 2.0 * np.pi * d * (grid - u0)
    steer = np.exp(1j * np.outer(psi_grid, np.arange(n)))   # (n_grid, n)
    theta = 2.0 * np.pi * np.arange(k_tan) / k_tan
    rot = np.exp(-1j * theta)
    coef_blocks = col_w[None, :] * np.repeat(steer, n_codes, axis=1)
    re_blocks = np.real(coef_blocks[:, None, :] * rot[None, :, None])
    # one-hot 约束行（审查 P2-1，2026-10-05）：Σ_c y[n,c]=1 逐单元——缺此行
    # multi-hot 解可行而 y.argmax 出码与 res.fun 静默失对应（docstring 声明
    # 的 one-hot 形式缺约束行=潜在非显性缺口；穷举门实例最优恰 one-hot 故
    # 探针未见）。行序追加在切平面/主瓣行之后，lb/ub 同步扩。
    onehot = np.zeros((n, n_var))
    for n_i in range(n):
        onehot[n_i, n_i * n_codes:(n_i + 1) * n_codes] = 1.0
    a_mat = np.concatenate(
        [re_blocks.reshape(grid.size * k_tan, n_var),
         np.real(col_w)[None, :],
         onehot], axis=0)
    lb_vec = np.concatenate([
        np.full(grid.size * k_tan, -np.inf),
        [float(taper.sum()) * 10.0 ** (-loss_db / 20.0)],
        np.ones(n)])
    ub_ml = np.inf
    integrality = np.ones(n_var)
    vbounds = Bounds(lb=np.zeros(n_var), ub=np.ones(n_var))
    options: dict[str, Any] = {"mip_rel_gap": float(mip_rel_gap)}
    if time_limit_s is not None:
        options["time_limit"] = float(time_limit_s)

    ref_sum_a = float(taper.sum())
    if sl_level_offset_db is not None:
        # 单水平直通模式（穷举对拍/确定性测试）：offset 可负（比声明更深，
        # 强制非平凡解——全零码在参考=声明电平时恰在边界，须负偏才有效）
        offsets = [float(sl_level_offset_db)]
    elif level_tol_db is not None:
        offsets = None            # 二分 min-PSLL（opt-in）
    else:
        offsets = [float(max_sl_degradation_db)]   # 缺省单水平
    a_hi = float(max_sl_degradation_db)
    a_lo = a_hi - 40.0
    tol_db = float(level_tol_db) if level_tol_db is not None else 0.1

    def _solve_at(offset_db: float):
        ub = np.concatenate([
            np.full(grid.size * k_tan,
                    ref_sum_a * 10.0 ** ((sll + offset_db) / 20.0)),
            [ub_ml],
            # one-hot 行 ub=lb=1（审查 P2-1 修随行；等式经 lb=ub 表达）
            np.ones(n)])
        constraint = LinearConstraint(a_mat, lb_vec, ub)
        return milp(c=cost, constraints=constraint,
                    integrality=integrality, bounds=vbounds,
                    options=options)

    solver_status = "optimal"
    bisection_steps = 0
    if offsets is not None:
        res = _solve_at(offsets[0])
    else:
        res = _solve_at(a_hi)
        if res.success:
            while a_hi - a_lo > tol_db:
                mid = 0.5 * (a_lo + a_hi)
                res_mid = _solve_at(mid)
                bisection_steps += 1
                if res_mid.success and res_mid.x is not None:
                    a_hi = mid
                    res = res_mid
                else:
                    a_lo = mid
            solver_status = f"bisection({bisection_steps} steps)"
        # res 为 a_hi（最后可行水平）的解；若 a_hi 本身不可行则走失败分支

    if not res.success or res.x is None:
        status = getattr(res, "message", "") or "unknown"
        return {
            "ok": False,
            "reason": "milp_infeasible_or_failed",
            "solver_status": str(status),
            "n_elements": n,
            "sidelobe_level_db": sll,
            "n_bits": bits,
            "atten_steps": steps,
            "element_switch": bool(element_switch),
            "notes": ["spec 过紧（如 max_mainlobe_loss_db 过小/副瓣声明过深/"
                      "副瓣水平偏移取负过深）时 MILP 不可行——如实返回，"
                      "不凑（spec §7.4 风险③）"],
        }

    achieved_offset_db = (float(offsets[0]) if offsets is not None
                          else a_hi)
    y = res.x[: n * n_codes].reshape(n, n_codes)
    choice = y.argmax(axis=1)
    phase_code = np.zeros(n, dtype=int)
    atten_code = np.zeros(n, dtype=int)
    weights_realized = np.zeros(n, dtype=complex)
    for e in range(n):
        s_sel, g_sel, q_sel = codes[int(choice[e])]
        phase_code[e] = q_sel
        atten_code[e] = g_sel
        weights_realized[e] = taper[e] * s_sel \
            * (10.0 ** (-g_sel * step_db / 20.0)) \
            * np.exp(1j * 2.0 * np.pi * q_sel / q_levels)
    mask = (np.abs(weights_realized) > _TINY).astype(int)

    objective = float(res.fun)
    # F(u0)：扫描相位在 AF 核内（u=u0 时 steer=1）
    f0 = complex(np.sum(weights_realized))
    ref_sum = float(taper.sum())

    def _true_psll() -> tuple[float, float]:
        u_eval = np.linspace(-1.0, 1.0, 4001)
        psi_e = 2.0 * np.pi * d * (u_eval - u0)
        st = np.exp(1j * np.outer(psi_e, np.arange(n)))
        f_q = np.abs(st @ weights_realized)
        f_r = np.abs(st @ taper)
        sl_sel = np.abs(u_eval - u0) > ml_half
        if not np.any(sl_sel) or f_q[~sl_sel].max() <= 0.0:
            return float("nan"), float("nan")
        psll_q = 20.0 * np.log10(f_q[sl_sel].max() / f_q[~sl_sel].max())
        psll_r = 20.0 * np.log10(f_r[sl_sel].max() / f_r[~sl_sel].max())
        return float(psll_q), float(psll_r)

    psll_q, psll_r = _true_psll()
    gain_db = 20.0 * np.log10(max(abs(f0), _TINY) / ref_sum)
    tangent_conserv_db = 10.0 * np.log10(1.0 / float(np.cos(np.pi / k_tan)))

    return {
        "ok": True,
        "n_elements": n,
        "sidelobe_level_db": sll,
        "n_bits": bits,
        "n_phase_levels": q_levels,
        "atten_steps": steps,
        "atten_step_db": step_db,
        "element_switch": bool(element_switch),
        "spacing_lambda": d,
        "scan_u0": u0,
        "activation_mask": [int(v) for v in mask],
        "phase_code": [int(v) for v in phase_code],
        "atten_code": [int(v) for v in atten_code],
        "phase_deg": [float(v) for v in 360.0 * phase_code / q_levels],
        "weights_complex": [[float(np.real(v)), float(np.imag(v))]
                            for v in weights_realized],
        "quantization_error": objective,
        "milp_status": solver_status,
        "sl_level_offset_db": float(achieved_offset_db),
        "mainlobe_gain_db": float(gain_db),
        "psll_db_realized": psll_q,
        "psll_db_reference": psll_r,
        "psll_degradation_db": float(psll_q - psll_r),
        "linearization_conservatism_db": float(tangent_conserv_db),
        "n_sidelobe_points": int(grid.size),
        "n_tangent": k_tan,
        "notes": [
            "线性化保守带=10·log10(1/cos(pi/K))，K=16 时 ~0.166dB（切平面"
            "外逼近，可行解的线性化目标 ≥ 真峰值场的保守侧）",
            "主瓣约束为参考相位投影下界（线性化选择，钉全局相位自由度）；"
            "回代 PSLL 为稠密网格真非线性口径；sl_level_offset_db=副瓣"
            "切平面约束相对声明电平的最终偏移（二分精化或单水平显式值）",
            "缺省参考锥削=Dolph-Chebyshev（chebyshev_weights）；可用 "
            "reference_weights 覆盖（须有限非负）",
        ],
    }
