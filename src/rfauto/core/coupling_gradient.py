"""PB-2（round5 §4.1）：Georgiou 可微耦合矩阵综合——确定性梯度内核（纯函数零 IO）。

法源（#118：来源写 docstring；裁判=独立路径，不自证）：

- 论文口径（PB-2，arXiv:2609.22310，O. Georgiou 等 2026，"Differentiable
  Synthesis and Yield Optimization of Cross-Coupled Resonator Filters"；
  round5 §4.1 摘要级核实，全文实现细节 UNVERIFIED——本内核是按其公开结论
  的确定性重构，非论文代码移植）：跨耦合谐振器滤波器**两阶段可微综合**——
  第一阶段**特征多项式匹配**对随机初值的成功率（18/24）显著优于直接频响
  匹配（0/24）；第二阶段频响精化；再经可微软化做 MC 公差求导良率中心化
  （良率 50.9%→67.0%）。本增量交付：两阶段梯度面 + Armijo 梯度下降确定性
  收敛例 + 一阶公差敏感度切片（yield 面）。
- 耦合矩阵频响模型：Cameron-Ming Yu-Wang《Microwave Filters for
  Communication Systems》（Wiley）N+2 耦合矩阵导纳式，与
  core/calculators.py ``_cm_response_raw`` 逐式同口径（内节点对角
  j(Ω−m_ii)、非对角 −j·m_ij、源/载节点对角=外部导纳 qe；
  S21=2·v[N+1]/√(qe0·qeL)，S11=1−2·v[0]/qe0）——单测与既有
  coupling_matrix_response 计算器对拍钉住（只读消费，不 import 私有函数）。
- 复步长导数：Martins-Sturdza-Alonso, "The Complex-Step Derivative
  Approximation", AIAA Journal 41(9), 2003——实值目标 f:R^n→R 若**计算
  过程在实点处全实**且复解析，则 Im f(x+i·h·e_k)/h = ∂f/∂x_k − O(h²)；
  h=1e-20 时导数信息独占虚部分量、不经减法消去 → 机器精度。本仓零
  autodiff 依赖的确定性"可微"实现路（任务书口径）。
- **复中间链陷阱（本仓实证，专测钉住）**：把复步长直接套在复响应链
  （Y 矩阵复 LU 分解）上**必然失效**——中间量在实点处已是 O(1) 复数，
  参数的 ±1e-20 虚部扰动在每次复数加法中被 O(1) 虚部分量的舍入吸收
  （实测 S(z) 与 S(z̄) 逐位相同、梯度恰为 0）。复步长的适用前提是
  "实点处中间值全实"，不是"复数算术即可"。
- **响应目标的实块载体（本仓推导）**：Y=Yr+i·Yi、v=vr+i·vi 代入
  Yv=e0 展开为 2n×2n **实**线性系统 [[Yr,−Yi],[Yi,Yr]]·[vr;vi]=[e0;0]，
  其中 Yr（端口对角=qe，其余 0）与 Yi（内节点对角=Ω−m_ii、非对角=−m_ij）
  都是参数的实代数式——实点处 vr/vi 全实，复步长经此载体机器精度。
  目标 J=Σ_Ω(vr−Re t)²+(vi−Im t)² 与复路径 |S21−t|² 代数恒等
  （单测钉住 ≤1e-12）。
- **特征多项式系数载体**：Faddeev–LeVerrier 递推
  （M₁=I，c_k=−tr(A·M_k)/k，M_{k+1}=A·M_k+c_k·I）全由实矩阵积与迹构成，
  产出 monic 特征多项式 λ^N+c₁λ^{N−1}+…+c_N 的系数——系数是矩阵元的
  多项式（整函数），匹配系数 ⟺ 匹配极点集，**无单谱/简并前提**，
  复步长机器精度。这正是 Georgiou 第一阶段"特征多项式匹配"的字面实现
  （比特征值排序配对更贴原文措辞，且免去重谱守卫）。LeVerrier 高阶有
  舍入稳定域，本内核限 N≤8（滤波器综合典型 2-8 阶）。

接口约定（同 core/aging.py 域内约定）：纯函数零 IO；不进 calculators
注册表（消费者=service 层薄壳）；全部结果 dataclass 带 to_dict()（JSON
可序列化 float/int/bool/str/list）；数值 0.0 合法（判缺失一律 is not
None，#364④）；bool 数值入参显式拒收（df7+⑯）。参数化=实对称 (N+2)×
(N+2) 上三角行主序含对角（pack_upper/unpack_upper），复数步进走同一路径
零分支。复矩阵参数化与 S11 目标、MC 求导良率中心化不在本增量（见文件尾
「诚实边界」）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "CS_H",
    "FD_H_DEFAULT",
    "GradientCheck",
    "SynthesisTrace",
    "ToleranceSensitivity",
    "TwoStageResult",
    "char_poly_coeffs",
    "check_char_poly_gradient",
    "check_response_gradient",
    "gd_minimize",
    "grad_char_poly_complex_step",
    "grad_char_poly_fd",
    "grad_response_complex_step",
    "grad_response_fd",
    "objective_char_poly",
    "objective_response",
    "pack_upper",
    "s11_response",
    "s21_response",
    "tolerance_sensitivity",
    "two_stage_synthesize",
    "unpack_upper",
]

#: 复步长（AIAA 2003 惯例值：虚部分量承载导数，无减法消去）
CS_H = 1e-20
#: 中心差分裁判路径缺省步长（每分量再乘 max(1,|x_k|)）
FD_H_DEFAULT = 1e-6
#: 对称性/实性校验容差（pack_upper 入口）
SYM_TOL = 1e-12
#: Faddeev–LeVerrier 舍入稳定域上限（阶数守卫）
LEVERRIER_MAX_N = 8
#: 梯度双路径判定缺省 rel 门（#118 任务书口径）
GRAD_CHECK_TOL_DEFAULT = 1e-6


# ─── 入参收敛守卫 ────────────────────────────────────────────────────────────


def _finite_float(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染，df7+⑯）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _as_float_vector(x, name: str) -> np.ndarray:
    arr = np.asarray(x)
    if arr.dtype == np.bool_:
        raise ValueError(f"{name} 不接受 bool 数组（df7+⑯）")
    if np.issubdtype(arr.dtype, np.complexfloating):
        raise ValueError(f"{name} 不接受复数组（实值参数面专用）")
    if arr.ndim != 1:
        raise ValueError(f"{name} 须为一维数组")
    out = arr.astype(float)
    if out.size and not bool(np.all(np.isfinite(out))):
        raise ValueError(f"{name} 必须全为有限数")
    return out


def _as_complex_vector(x, name: str) -> np.ndarray:
    arr = np.asarray(x)
    if arr.dtype == np.bool_:
        raise ValueError(f"{name} 不接受 bool 数组（df7+⑯）")
    if arr.ndim != 1:
        raise ValueError(f"{name} 须为一维数组")
    out = arr.astype(complex)
    if out.size and not bool(np.all(np.isfinite(out))):
        raise ValueError(f"{name} 必须全为有限数")
    return out


def _as_matrix(matrix, name: str) -> np.ndarray:
    """矩阵入参收敛：实方阵或 [re, im] 对嵌套列表 → complex 方阵（≥2 阶）。"""
    raw = np.asarray(matrix)
    if raw.dtype == np.bool_:
        raise ValueError(f"{name} 不接受 bool 数组（df7+⑯）")
    if raw.ndim == 3 and raw.shape[-1] == 2:
        m = raw[..., 0].astype(complex) + 1j * raw[..., 1].astype(complex)
    elif raw.ndim == 2:
        m = raw.astype(complex)
    else:
        raise ValueError(f"{name} 须为方阵或 [re, im] 对嵌套列表")
    if m.shape[0] != m.shape[1] or m.shape[0] < 2:
        raise ValueError(f"{name} 须为 ≥2 阶方阵")
    if not bool(np.all(np.isfinite(m))):
        raise ValueError(f"{name} 必须全为有限数")
    return m


def _qe_pair(q_ext) -> tuple[float, float]:
    if q_ext is None:
        return 1.0, 1.0
    seq = list(q_ext)
    if len(seq) != 2:
        raise ValueError("q_ext 须为 [q_in, q_out] 两元素")
    q0 = _finite_float(seq[0], "q_ext[0]")
    ql = _finite_float(seq[1], "q_ext[1]")
    if q0 <= 0.0 or ql <= 0.0:
        raise ValueError("q_ext 须为正（外部导纳归一口径）")
    return q0, ql


def _size_from_packed(n_params: int) -> int:
    n2 = round((math.sqrt(8.0 * n_params + 1.0) - 1.0) / 2.0)
    if n2 < 2 or n2 * (n2 + 1) // 2 != n_params:
        raise ValueError("参数向量长度须为三角数 n2(n2+1)/2（n2≥2）")
    return n2


def _cs_h(h, name: str = "h") -> float:
    out = CS_H if h is None else _finite_float(h, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _check_n_res(n_res: int) -> int:
    n = int(n_res)
    if n < 2:
        raise ValueError("n_res 须 ≥2（单谐振器无耦合匹配面）")
    if n > LEVERRIER_MAX_N:
        raise ValueError(f"n_res 须 ≤{LEVERRIER_MAX_N}（LeVerrier 舍入稳定域）")
    return n


# ─── 参数化（实对称上三角） ──────────────────────────────────────────────────


def pack_upper(matrix) -> np.ndarray:
    """实对称矩阵 → 上三角行主序含对角参数向量（长度 n2(n2+1)/2）。

    非对称或含不可忽略虚部的输入显式拒绝（本参数化=实对称/互易口径；
    复矩阵参数化不在本增量，见模块 docstring 诚实边界）。
    """
    m = _as_matrix(matrix, "matrix")
    if float(np.max(np.abs(m - m.T))) > SYM_TOL:
        raise ValueError("matrix 须对称（互易参数化，|M−Mᵀ|≤1e-12）")
    if float(np.max(np.abs(m.imag))) > SYM_TOL:
        raise ValueError("matrix 须实（本参数化=实对称；复矩阵扩展不在本增量）")
    n2 = m.shape[0]
    iu = np.triu_indices(n2)
    return m[iu].real.astype(float)


def unpack_upper(x, n2: int) -> np.ndarray:
    """上三角参数向量 → 对称矩阵（对角含入；复向量走同一路径零分支）。"""
    if int(n2) < 2:
        raise ValueError("n2 须 ≥2")
    xv = np.asarray(x)
    if xv.ndim != 1 or xv.size != n2 * (n2 + 1) // 2:
        raise ValueError("x 长度须为三角数 n2(n2+1)/2")
    m = np.zeros((n2, n2), dtype=np.result_type(xv.dtype, np.float64))
    iu = np.triu_indices(n2)
    m[iu] = xv
    m[(iu[1], iu[0])] = xv
    return m


# ─── 频响内核：复路径（公开响应 API，与 calculators 同口径对拍） ─────────────


def _solve_grid(m: np.ndarray, q0: float, ql: float, om: np.ndarray) -> np.ndarray:
    """Y(Ω)v=e0 复批量解，返回 v (n_omega, n2)。经典参考路径。"""
    n2 = m.shape[0]
    nw = om.size
    Y = np.zeros((nw, n2, n2), dtype=complex)
    iu = np.triu_indices(n2, 1)
    Y[:, iu[0], iu[1]] = -1j * m[iu]
    Y[:, iu[1], iu[0]] = -1j * m[iu]
    idx = np.arange(n2)
    Y[:, idx, idx] = 1j * (om[:, None] - m[idx, idx][None, :])
    Y[:, 0, 0] = q0
    Y[:, n2 - 1, n2 - 1] = ql
    b = np.zeros((nw, n2), dtype=complex)
    b[:, 0] = 1.0
    return np.linalg.solve(Y, b[..., None])[..., 0]


def s21_response(matrix, omega_norm, q_ext=None) -> np.ndarray:
    """耦合矩阵 → S21 复数组（归一化低通 Ω 轴；与既有计算器同口径）。"""
    m = _as_matrix(matrix, "matrix")
    q0, ql = _qe_pair(q_ext)
    om = _as_float_vector(omega_norm, "omega_norm")
    return 2.0 * _solve_grid(m, q0, ql, om)[:, -1] / math.sqrt(q0 * ql)


def s11_response(matrix, omega_norm, q_ext=None) -> np.ndarray:
    """耦合矩阵 → S11 复数组（无损模型满足 |S11|²+|S21|²=1，单测钉）。"""
    m = _as_matrix(matrix, "matrix")
    q0, ql = _qe_pair(q_ext)
    om = _as_float_vector(omega_norm, "omega_norm")
    v = _solve_grid(m, q0, ql, om)
    return 1.0 - 2.0 * v[:, 0] / q0


# ─── 频响目标的实块载体（复步长解析载体；与复路径代数恒等） ─────────────────


def _response_streams(m: np.ndarray, q0: float, ql: float,
                      om: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """实块 2n×2n 系统 [[Yr,−Yi],[Yi,Yr]]·[vr;vi]=[e0;0]（见模块 docstring）。

    Yr/Yi 为参数的实代数式（实点处全实），复化参数走同一装配路径
    （纯 +,−,× 与线性求解，复解析）→ 复步长合法载体。
    """
    n2 = m.shape[0]
    nw = om.size
    dt = np.result_type(m.dtype, np.float64)
    iu = np.triu_indices(n2, 1)
    idx = np.arange(n2)
    iin = idx[1:-1]
    Yr = np.zeros((nw, n2, n2), dtype=dt)
    Yr[:, 0, 0] = q0
    Yr[:, n2 - 1, n2 - 1] = ql
    Yi = np.zeros((nw, n2, n2), dtype=dt)
    if n2 > 2:
        Yi[:, iin, iin] = om[:, None] - m[iin, iin][None, :]
    Yi[:, iu[0], iu[1]] = -m[iu]
    Yi[:, iu[1], iu[0]] = -m[iu]
    A = np.zeros((nw, 2 * n2, 2 * n2), dtype=dt)
    A[:, :n2, :n2] = Yr
    A[:, :n2, n2:] = -Yi
    A[:, n2:, :n2] = Yi
    A[:, n2:, n2:] = Yr
    b = np.zeros((nw, 2 * n2), dtype=dt)
    b[:, 0] = 1.0
    sol = np.linalg.solve(A, b[..., None])[..., 0]
    return sol[:, :n2], sol[:, n2:]


def _objective_streams(m: np.ndarray, q0: float, ql: float, om: np.ndarray,
                       t: np.ndarray) -> complex:
    """J=Σ_Ω|S21−t|²，S21=2·(vr_L+i·vi_L)/√(q0·ql)，L=载节点。

    复化参数下 Im(J̃)=h·J′（实块载体；流 reunited 成 S21 前为实代数链）。
    """
    vr, vi = _response_streams(m, q0, ql, om)
    scale = 2.0 / math.sqrt(q0 * ql)
    r = scale * vr[:, -1] - t.real
    im = scale * vi[:, -1] - t.imag
    return complex(np.sum(r * r + im * im))


# ─── 目标面（objective_response / objective_char_poly） ─────────────────────


def _response_ctx(x, omega_norm, s21_target, q_ext, name_x: str = "x"):
    xv = _as_float_vector(x, name_x)
    n2 = _size_from_packed(xv.size)
    om = _as_float_vector(omega_norm, "omega_norm")
    if om.size < 2:
        raise ValueError("omega_norm 至少 2 点（单点无梯度面意义）")
    t = _as_complex_vector(s21_target, "s21_target")
    if t.size != om.size:
        raise ValueError("s21_target 与 omega_norm 长度须一致")
    q0, ql = _qe_pair(q_ext)
    return xv, n2, om, t, q0, ql


def objective_response(x, omega_norm, s21_target, q_ext=None) -> float:
    """频响目标 J(x)=Σ_Ω |S21(M(x);Ω)−t(Ω)|²（实块载体求值，复路径恒等）。"""
    xv, n2, om, t, q0, ql = _response_ctx(x, omega_norm, s21_target, q_ext)
    jt = _objective_streams(unpack_upper(xv, n2), q0, ql, om, t)
    if abs(jt.imag) > 1e-9 * (1.0 + abs(jt.real)):
        raise ValueError("实块载体在实参数点出现显著虚部（数值一致性破坏）")
    return float(jt.real)


def char_poly_coeffs(matrix) -> np.ndarray:
    """monic 特征多项式系数 [c1..cN]（Faddeev–LeVerrier；P(λ)=det(λI−m)）。

    全实矩阵积与迹的递推：M₁=I，c_k=−tr(A·M_k)/k，M_{k+1}=A·M_k+c_k·I——
    实点处全实中间量，复步长合法载体；系数为矩阵元多项式（整函数）。
    dtype 跟随入参（实入参 → 实系数；复化入参 → 复系数，零分支）。
    """
    raw = np.asarray(matrix)
    if raw.dtype == np.bool_:
        raise ValueError("matrix 不接受 bool 数组（df7+⑯）")
    if raw.ndim == 3 and raw.shape[-1] == 2:
        m = raw[..., 0].astype(complex) + 1j * raw[..., 1].astype(complex)
    elif raw.ndim == 2:
        m = raw.astype(np.result_type(raw.dtype, np.float64))
    else:
        raise ValueError("matrix 须为方阵或 [re, im] 对嵌套列表")
    if m.shape[0] != m.shape[1] or m.shape[0] < 2:
        raise ValueError("matrix 须为 ≥2 阶方阵")
    if not bool(np.all(np.isfinite(m))):
        raise ValueError("matrix 必须全为有限数")
    n = m.shape[0]
    eye = np.eye(n, dtype=m.dtype)
    mk = eye.copy()
    coeffs = np.empty(n, dtype=m.dtype)
    for k in range(1, n + 1):
        ck = -(np.trace(m @ mk)) / k
        coeffs[k - 1] = ck
        mk = m @ mk + ck * eye
    return coeffs


def _poly_from_roots(poles: np.ndarray) -> np.ndarray:
    """Π(λ−p_k) 的 [c1..cN]（实根输入 → 实系数；卷积构造，确定性）。"""
    c = np.array([1.0])
    for p in poles:
        c = np.convolve(c, np.array([1.0, -float(p)]))
    return c[1:]


def objective_char_poly(x_int, n_res: int, target_coeffs) -> float:
    """特征多项式匹配目标（Georgiou 第一阶段）：J=Σ_k(c_k(M_int)−ĉ_k)²。

    系数面整函数，无单谱/简并前提；N≤8（LeVerrier 稳定域，docstring）。
    """
    xv = _as_float_vector(x_int, "x_int")
    n = _check_n_res(n_res)
    tc = _as_float_vector(target_coeffs, "target_coeffs")
    if tc.size != n:
        raise ValueError("target_coeffs 长度须 = n_res")
    m_int = unpack_upper(xv, n)
    return float(np.sum((char_poly_coeffs(m_int) - tc) ** 2))


# ─── 梯度面（复步长主路径 + 中心差分裁判路径） ───────────────────────────────


def grad_response_complex_step(x, omega_norm, s21_target, q_ext=None, h=None) -> np.ndarray:
    """频响目标梯度，实块载体复步长（h=1e-20 机器精度，零减法消去）。"""
    xv, n2, om, t, q0, ql = _response_ctx(x, omega_norm, s21_target, q_ext)
    hh = _cs_h(h)
    g = np.empty(xv.size)
    for k in range(xv.size):
        z = xv.astype(complex)
        z[k] += 1j * hh
        g[k] = np.imag(_objective_streams(unpack_upper(z, n2), q0, ql, om, t)) / hh
    return g


def grad_response_fd(x, omega_norm, s21_target, q_ext=None, h=None) -> np.ndarray:
    """频响目标梯度，实轴中心差分（独立裁判路径：有限差分算术，无复数链路）。"""
    xv, n2, om, t, q0, ql = _response_ctx(x, omega_norm, s21_target, q_ext)
    hh = FD_H_DEFAULT if h is None else _finite_float(h, "h_fd")

    def obj(vec: np.ndarray) -> float:
        return float(_objective_streams(unpack_upper(vec, n2), q0, ql, om, t).real)

    g = np.empty(xv.size)
    for k in range(xv.size):
        step = hh * max(1.0, abs(float(xv[k])))
        xp = xv.copy()
        xm = xv.copy()
        xp[k] += step
        xm[k] -= step
        g[k] = (obj(xp) - obj(xm)) / (2.0 * step)
    return g


def grad_char_poly_complex_step(x_int, n_res: int, target_coeffs, h=None) -> np.ndarray:
    """特征多项式目标梯度，LeVerrier 实链复步长（机器精度）。"""
    xv = _as_float_vector(x_int, "x_int")
    n = _check_n_res(n_res)
    tc = _as_float_vector(target_coeffs, "target_coeffs")
    if tc.size != n:
        raise ValueError("target_coeffs 长度须 = n_res")
    hh = _cs_h(h)
    g = np.empty(xv.size)
    for k in range(xv.size):
        z = xv.astype(complex)
        z[k] += 1j * hh
        m_int = unpack_upper(z, n)
        cc = char_poly_coeffs(m_int)
        g[k] = np.imag(np.sum((cc - tc) * (cc - tc))) / hh
    return g


def grad_char_poly_fd(x_int, n_res: int, target_coeffs, h=None) -> np.ndarray:
    """特征多项式目标梯度，实轴中心差分（独立裁判路径）。"""
    xv = _as_float_vector(x_int, "x_int")
    n = _check_n_res(n_res)
    tc = _as_float_vector(target_coeffs, "target_coeffs")
    if tc.size != n:
        raise ValueError("target_coeffs 长度须 = n_res")
    hh = FD_H_DEFAULT if h is None else _finite_float(h, "h_fd")
    g = np.empty(xv.size)
    for k in range(xv.size):
        step = hh * max(1.0, abs(float(xv[k])))
        xp = xv.copy()
        xm = xv.copy()
        xp[k] += step
        xm[k] -= step
        g[k] = (objective_char_poly(xp, n, tc) - objective_char_poly(xm, n, tc))
        g[k] /= 2.0 * step
    return g


# ─── 双路径梯度判定（#118） ──────────────────────────────────────────────────


@dataclass
class GradientCheck:
    """复步长 vs 中心差分双路径对照结果（#118：独立来源裁判，rel≤tol）。

    噪声地板口径：中心差分的舍入消去误差 ~eps·(1+|J|)/(2·h_fd)——真值
    恰为 0（结构对称零，如实对称矩阵的无关交叉耦合）的条目上 FD 只剩
    该噪声、复步长给机器精度 0，按 rel 判会假红。故 max_rel 只在
    max(|cs|,|fd|)>noise_floor 的活跃条目上取；地板下条目要求
    |cs−fd|≤noise_floor（双双≈0 即一致），n_below_floor 如实计数。
    """

    n_params: int
    max_rel: float
    ok: bool
    tol: float
    h_cs: float
    h_fd: float
    noise_floor: float
    n_below_floor: int
    cs_grad: list
    fd_grad: list

    def to_dict(self) -> dict:
        return {"n_params": int(self.n_params), "max_rel": float(self.max_rel),
                "ok": bool(self.ok), "tol": float(self.tol),
                "h_cs": float(self.h_cs), "h_fd": float(self.h_fd),
                "noise_floor": float(self.noise_floor),
                "n_below_floor": int(self.n_below_floor),
                "cs_grad": [float(v) for v in self.cs_grad],
                "fd_grad": [float(v) for v in self.fd_grad]}


def _make_check(g_cs: np.ndarray, g_fd: np.ndarray, tol, h_cs: float, h_fd: float,
                tol_default: float, obj_at_x: float) -> GradientCheck:
    tol_v = tol_default if tol is None else _finite_float(tol, "tol")
    if tol_v <= 0.0:
        raise ValueError("tol 必须 >0")
    # FD 舍入噪声地板：eps 量级目标值差 / 步长，8× 安全系数
    noise = (8.0 * float(np.finfo(float).eps)) * (1.0 + abs(float(obj_at_x))) / (2.0 * h_fd)
    mag = np.maximum(np.abs(g_cs), np.abs(g_fd))
    active = mag > noise
    diffs = np.abs(g_cs - g_fd)
    max_rel = float(np.max(diffs[active] / mag[active])) if bool(np.any(active)) else 0.0
    subfloor_bad = float(np.max(diffs[~active])) if bool(np.any(~active)) else 0.0
    ok = bool(max_rel <= tol_v and subfloor_bad <= noise)
    return GradientCheck(n_params=int(g_cs.size), max_rel=max_rel, ok=ok,
                         tol=tol_v, h_cs=float(h_cs), h_fd=float(h_fd),
                         noise_floor=float(noise), n_below_floor=int(np.sum(~active)),
                         cs_grad=[float(v) for v in g_cs], fd_grad=[float(v) for v in g_fd])


def check_response_gradient(x, omega_norm, s21_target, q_ext=None, fd_h=None,
                            tol=None) -> GradientCheck:
    """频响目标梯度双路径对照（复步长主 vs 中心差分裁判）。"""
    j0 = objective_response(x, omega_norm, s21_target, q_ext=q_ext)
    g_cs = grad_response_complex_step(x, omega_norm, s21_target, q_ext=q_ext)
    g_fd = grad_response_fd(x, omega_norm, s21_target, q_ext=q_ext, h=fd_h)
    h_fd = FD_H_DEFAULT if fd_h is None else float(fd_h)
    return _make_check(g_cs, g_fd, tol, CS_H, h_fd, GRAD_CHECK_TOL_DEFAULT, j0)


def check_char_poly_gradient(x_int, n_res: int, target_coeffs, fd_h=None,
                             tol=None) -> GradientCheck:
    """特征多项式目标梯度双路径对照（复步长主 vs 中心差分裁判）。"""
    j0 = objective_char_poly(x_int, n_res, target_coeffs)
    g_cs = grad_char_poly_complex_step(x_int, n_res, target_coeffs)
    g_fd = grad_char_poly_fd(x_int, n_res, target_coeffs, h=fd_h)
    h_fd = FD_H_DEFAULT if fd_h is None else float(fd_h)
    return _make_check(g_cs, g_fd, tol, CS_H, h_fd, GRAD_CHECK_TOL_DEFAULT, j0)


# ─── 确定性梯度下降（Armijo 回溯；供两阶段综合与最小用例） ───────────────────


@dataclass
class SynthesisTrace:
    """梯度下降轨迹（残差序列供单调性断言；全确定性，无随机源）。"""

    iterations: int
    objective_final: float
    grad_inf_norm: float
    converged: bool
    stop_reason: str
    residuals: list
    x_final: list

    def to_dict(self) -> dict:
        return {"iterations": int(self.iterations), "objective_final": float(self.objective_final),
                "grad_inf_norm": float(self.grad_inf_norm), "converged": bool(self.converged),
                "stop_reason": str(self.stop_reason),
                "residuals": [float(v) for v in self.residuals],
                "x_final": [float(v) for v in self.x_final]}


def gd_minimize(objective, gradient, x0, max_iter=200, step0=0.1, c1=1e-4,
                grad_tol=1e-12, shrink=0.5) -> SynthesisTrace:
    """Armijo 回溯梯度下降（确定性：固定初值/步长，无随机源、无 optuna）。

    每步从 step0 起以 shrink 折半回溯至充分下降 J(x−tg) ≤ J − c1·t·‖g‖²
    （Armijo 条件保证残差序列单调不增）；‖g‖∞≤grad_tol 或步长下溢或
    max_iter 触顶即停，stop_reason 如实记录（不冒充收敛）。
    """
    iters = int(max_iter)
    if iters < 1:
        raise ValueError("max_iter 须 ≥1")
    step0_v = _finite_float(step0, "step0")
    if step0_v <= 0.0:
        raise ValueError("step0 必须 >0")
    c1_v = _finite_float(c1, "c1")
    if c1_v <= 0.0:
        raise ValueError("c1 必须 >0")
    gtol = _finite_float(grad_tol, "grad_tol")
    if gtol < 0.0:
        raise ValueError("grad_tol 须 ≥0")
    sh = _finite_float(shrink, "shrink")
    if not 0.0 < sh < 1.0:
        raise ValueError("shrink 须在 (0,1)")

    x = _as_float_vector(x0, "x0").copy()
    j = float(objective(x))
    residuals = [j]
    g = np.asarray(gradient(x), dtype=float)
    gn = float(np.max(np.abs(g))) if g.size else 0.0
    reason = "max_iter"
    if gn <= gtol:
        return SynthesisTrace(0, j, gn, True, "grad_tol", residuals, [float(v) for v in x])
    for _ in range(iters):
        g = np.asarray(gradient(x), dtype=float)
        gn = float(np.max(np.abs(g))) if g.size else 0.0
        if gn <= gtol:
            reason = "grad_tol"
            break
        g2 = float(np.dot(g, g))
        t = step0_v
        accepted = False
        for _ in range(60):
            xn = x - t * g
            jn = float(objective(xn))
            if math.isfinite(jn) and jn <= j - c1_v * t * g2:
                accepted = True
                break
            t *= sh
        if not accepted:
            reason = "step_underflow"
            break
        x = xn
        j = jn
        residuals.append(j)
    return SynthesisTrace(iterations=len(residuals) - 1, objective_final=j,
                          grad_inf_norm=gn,
                          converged=bool(reason == "grad_tol"), stop_reason=reason,
                          residuals=[float(v) for v in residuals],
                          x_final=[float(v) for v in x])


# ─── Georgiou 两阶段确定性综合（特征多项式匹配 → 频响精化） ──────────────────


@dataclass
class TwoStageResult:
    """两阶段综合结果（stage1=特征多项式匹配，stage2=频响精化）。"""

    n_order: int
    n2: int
    stage1: SynthesisTrace
    stage2: SynthesisTrace
    matrix: list
    response_objective: float
    poly_objective: float

    def to_dict(self) -> dict:
        return {"n_order": int(self.n_order), "n2": int(self.n2),
                "stage1": self.stage1.to_dict(), "stage2": self.stage2.to_dict(),
                "matrix": [[float(v) for v in row] for row in self.matrix],
                "response_objective": float(self.response_objective),
                "poly_objective": float(self.poly_objective)}


def _default_internal_init(n_res: int, poles: np.ndarray) -> np.ndarray:
    m = np.zeros((n_res, n_res))
    if n_res >= 2:
        ps = float(np.mean(np.abs(poles)))
        for i in range(n_res - 1):
            m[i, i + 1] = ps
            m[i + 1, i] = ps
    return m


def two_stage_synthesize(target_poles, omega_norm, s21_target, n_order, q_ext=None,
                         x0_internal=None, x0_full=None, max_iter_stage1=120,
                         max_iter_stage2=300, step0=0.15, grad_tol=1e-12) -> TwoStageResult:
    """两阶段可微综合（Georgiou 谱系确定性重构；纯梯度下降，无全局优化）。

    stage1：内块 N×N 上三角参数对特征多项式目标 gd_minimize（目标系数由
    target_poles 经 Π(λ−p_k) 卷积构造）；stage2：全 (N+2) 参数对频响目标
    gd_minimize（初值=stage1 内块+源/载耦合 1.0，或显式 x0_full）。
    返回轨迹与终矩阵（实对称嵌套列表）。
    """
    n = _check_n_res(n_order)
    poles = _as_float_vector(target_poles, "target_poles")
    if poles.size != n:
        raise ValueError("target_poles 长度须 = n_order")
    coeffs = _poly_from_roots(poles)
    om = _as_float_vector(omega_norm, "omega_norm")
    if om.size < 2:
        raise ValueError("omega_norm 至少 2 点（单点无梯度面意义）")
    t = _as_complex_vector(s21_target, "s21_target")
    if t.size != om.size:
        raise ValueError("s21_target 与 omega_norm 长度须一致")
    q0, ql = _qe_pair(q_ext)
    if x0_internal is not None:
        x_start1 = _as_float_vector(x0_internal, "x0_internal")
        if x_start1.size != n * (n + 1) // 2:
            raise ValueError("x0_internal 长度须 = n_order(n_order+1)/2")
    else:
        x_start1 = pack_upper(_default_internal_init(n, poles))

    def obj1(vec: np.ndarray) -> float:
        return objective_char_poly(vec, n, coeffs)

    def grad1(vec: np.ndarray) -> np.ndarray:
        return grad_char_poly_complex_step(vec, n, coeffs)

    tr1 = gd_minimize(obj1, grad1, x_start1, max_iter=max_iter_stage1, step0=step0,
                      grad_tol=grad_tol)
    m_int = unpack_upper(np.asarray(tr1.x_final), n)

    n2 = n + 2
    if x0_full is not None:
        x_start2 = _as_float_vector(x0_full, "x0_full")
        if x_start2.size != n2 * (n2 + 1) // 2:
            raise ValueError("x0_full 长度须 = (n_order+2)(n_order+3)/2")
    else:
        m_full = np.zeros((n2, n2))
        m_full[1:n2 - 1, 1:n2 - 1] = m_int
        m_full[0, 1] = m_full[1, 0] = 1.0
        m_full[n2 - 2, n2 - 1] = m_full[n2 - 1, n2 - 2] = 1.0
        x_start2 = pack_upper(m_full)

    def obj2(vec: np.ndarray) -> float:
        return objective_response(vec, om, t, q_ext=(q0, ql))

    def grad2(vec: np.ndarray) -> np.ndarray:
        return grad_response_complex_step(vec, om, t, q_ext=(q0, ql))

    tr2 = gd_minimize(obj2, grad2, x_start2, max_iter=max_iter_stage2, step0=step0,
                      grad_tol=grad_tol)
    m_final = unpack_upper(np.asarray(tr2.x_final), n2)
    return TwoStageResult(
        n_order=n, n2=n2, stage1=tr1, stage2=tr2,
        matrix=[[float(v) for v in row] for row in m_final.real],
        response_objective=float(obj2(tr2.x_final)),
        poly_objective=float(obj1(tr1.x_final)),
    )


# ─── 一阶公差敏感度（yield 面切片；MC 求导中心化不在本增量） ─────────────────


@dataclass
class ToleranceSensitivity:
    """一阶公差成本敏感度 s_i=σ_i·|∂J/∂x_i| 与降序排名（确定性切片）。"""

    sensitivities: list
    ranking: list

    def to_dict(self) -> dict:
        return {"sensitivities": [float(v) for v in self.sensitivities],
                "ranking": [int(v) for v in self.ranking]}


def tolerance_sensitivity(x, sigma, omega_norm, s21_target, q_ext=None) -> ToleranceSensitivity:
    """给定公差 σ 与频响目标，输出各参数的一阶成本贡献排名（复步长梯度）。

    一阶 Taylor 口径：σ_i 扰动下的成本漂移主导项 = σ_i·|∂J/∂x_i|——用于
    公差预算排序与 WCD/autotune 面的参数筛；论文的 MC 公差求导良率
    中心化（软排序可微化）不在本增量，如实见模块 docstring。
    """
    xv, _n2, om, t, q0, ql = _response_ctx(x, omega_norm, s21_target, q_ext)
    sig = _as_float_vector(sigma, "sigma")
    if sig.size != xv.size:
        raise ValueError("sigma 与 x 长度须一致")
    if np.any(sig < 0.0):
        raise ValueError("sigma 须 ≥0")
    g = grad_response_complex_step(xv, om, t, q_ext=(q0, ql))
    sens = sig * np.abs(g)
    ranking = np.argsort(-sens, kind="stable")
    return ToleranceSensitivity(sensitivities=[float(v) for v in sens],
                                ranking=[int(v) for v in ranking])


# ─── 诚实边界（预声明，先写后跑） ────────────────────────────────────────────
# 1. arXiv:2609.22310 全文实现细节（参数化/优化器/MC 求导的软排序构造）
#    UNVERIFIED——本内核按摘要级结论做确定性重构，两阶段面的"论文对拍"
#    只能到"结论同构"级（极点匹配初值成功率优势属其随机初值实验，本增量
#    未复现该统计实验）。
# 2. 良率中心化只交付一阶公差敏感度切片（σ_i·|∂J/∂x_i| 排序）；经 MC 的
#    可微良率（软阈值/软排序）不在本增量——复步长对含 max/排序的 MC 统计
#    量不解析，需要论文式软化构造，留后续增量。
# 3. 频响目标只含 S21（S11/多目标加权留后续）；复矩阵参数化（复系数原型
#    的 folded 面）不在本增量。
# 4. LeVerrier 系数面在 N≳10 有舍入稳定域问题（本内核限 N≤8）；极高阶
#    特征多项式匹配应改经响应面二阶段（后续增量评估）。
# 5. 本模块不进 calculators 注册表（core 域内约定，同 aging），消费者是
#    service 层薄壳（service/coupling_gradient_service.py）。
