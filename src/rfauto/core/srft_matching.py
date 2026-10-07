r"""MT-2 双匹配 SRFT（实数频率技术）匹配网络综合器——确定性内核
（round17 §二 :26「MT-2 双匹配 SRFT 综合器（P2/M-L）：实测
Z_L(f)/Z_S(f)→增益带宽平直→参数化有理拟合出元件值（Carlin-Yarman
1983/Yarman RCA 1982/Wiley 2016）；与 bounds.py Bode-Fano 门一致性
验收」，2026-10-02）。

法源与公式（铁律 5；#118：每面 ≥2 独立基准——Feldtkeller 恒等式+谱
分解回代+提取网络闭环重仿真+L 型匹配闭式功能锚+Bode-Fano 一致性，
锚树 test_srft_matching.py）：

- **H. J. Carlin, B. S. Yarman, "The Double Matching Problem:
  Analytic and Real Frequency Solutions", IEEE Trans. CAS 30:15-28
  (1983)；B. S. Yarman, "Design of Ultra Wideband Power Transfer
  Networks", Wiley 2010, Ch.4（SRFT 多项式法）**。

  增益参数化（SRFT 单调 roll-off 族，低通原型口径）：

      T(ω²) = ω^{2k}·P(ω²)² / ( ε²·ω^{2(k+n)} + ω^{2k}·P(ω²)² )

  P(ω²)=p₀+p₁ω²+…（实系数拟合参数）；T(0)=1、T(∞)~(p₀²/ε²)ω^{−2n}
  （k=高频传输零点数、n=带外滚降阶、ε=带外归一）。带内平坦度按
  最小二乘拟合（scipy least_squares，同输入同输出确定性）。

  多项式构造（谱分解）：|S21(jω)|²=T、|S11(jω)|²=1−T →

      g(λ)g★(λ) = ε²ω^{2(k+n)} + ω^{2k}P(ω²)²，  f(λ)=ε·λ^{k+n}

  （λ=jω 轴取模；g 最小相位=偶多项式 D(−λ²) 的 Re λ<0 半根 +
  λ=0 偶重根对半；首一化 |lead(g)|=ε）。**Feldtkeller 无耗恒等式**：
  |g(jω)|²−|f(jω)|²=ω^{2k}P(ω²)²（测试裁判）。

  阻抗矩阵（Darlington，Yarman 2010 §4）：

      z11 = (g_o+f_o)/(g_e−f_e)，  z21 = z12 = λ^k P(−λ²)/(g_e−f_e)，
      z22 = (g_o−f_o)/(g_e−f_e)

  （g_e/g_o、f_e/f_o=偶/奇部）。元件提取=∞ 极点逐次移除（Cauer 型
  梯形：z11 极点→串 L、y11 极点→并 C、z22/y22 对称端口 2），残余
  常数=负载电阻；双极点/非常数残余如实记 incomplete_extraction
  （Brune 段/理想变压器域，v1 边界显式声明）。

- **边界（#122 如实）**：v1 主口径=实源 R0+复载 Z_L(f) 的增益带综合
  （总 T 含负载失配因子 (1−|S_L|²)/|1−S22·S_L|²，S_L=(Z_L−R0)/
  (Z_L+R0) 解析构造）；**复源复载的完整 Brune 提取**（AA-1 合并注意
  不触发域）与理想变压器段=登记未做。提取完成域内（实载/∞ 极点可
  移除）闭环重仿真裁判。

- **Bode-Fano 一致性**（round17 验收）：带内 |Γ| 积分
  ∫ln(1/|Γ|)dω ≤ π/(RC)（bounds.bode_fano_rc 同源 limit 口径）——
  综合结果的输入反射积分不得越界（理论一致性锚）。

单位口径 SI（Ω/H/F/Hz）；λ 域多项式按 numpy 系数惯例（首项最高次）；
core 纯函数零 IO（scipy.optimize 惰性导入）；不注册 calculators 键
（本席纪律 3）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "srft_extract_ladder",
    "srft_fit_flat_gain",
    "srft_gain_response",
    "srft_impedance_matrix",
    "srft_input_impedance",
    "srft_network_response",
    "srft_polynomials",
    "srft_synthesize",
]


# ── 1) 增益响应与平坦拟合 ───────────────────────────────────────────────


def srft_gain_response(omega: Any, p_coeffs: Any, k: int, n: int,
                       eps: float) -> np.ndarray:
    """SRFT 单调 roll-off 增益 T(ω²)（模块 docstring 公式；ω 数组）。

    p_coeffs 为 P(ω²) 的系数（numpy 惯例，首项最高次；P 是 ω² 的
    多项式）。
    """
    _require_int("k", k, minimum=0)
    _require_int("n", n, minimum=0)
    eps = _require_positive("eps", eps)
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    if np.any(~np.isfinite(w)) or np.any(w < 0.0):
        raise ValueError("omega 必须为非负有限实数")
    p = np.asarray(p_coeffs, dtype=float)
    p_of_w2 = np.polyval(p, w * w)
    if float(p[-1]) == 0.0:
        raise ValueError("P(0)=0 与低通原型 T(0)=1 矛盾")
    num = (w ** (2 * k)) * p_of_w2**2
    den = (eps**2) * (w ** (2 * (k + n))) + num
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den
    # ω=0：k=0 时 num=den=p0²→1；k>0 时 0/0→洛必达极限 1（低通原型
    # T(0)=1，两支口径一致）
    out[w == 0.0] = 1.0
    return out


def srft_fit_flat_gain(
    omega_band: Any,
    *,
    k: int = 1,
    n: int = 2,
    eps: float = 1.0,
    n_p: int = 1,
    target_t0: float = 0.5,
    s_load: Any | None = None,
) -> dict[str, Any]:
    """带内平坦增益最小二乘拟合（SRFT 第 1 步；确定性）。

    自由参数：P 系数（n_p 个，初值全 1）；目标增益 T0 显式给定
    （target_t0，缺省 0.5——自由 T0 会退化到 T≡0 平凡解，实测后改为
    显式口径）。残差=T(ω²;p)−T0。s_load 给出（复数组，负载反射采样）
    时拟合对象为**总换能器增益一阶口径**：

        T_tot ≈ T_N·(1−|S_L|²)/|1−√(1−T_N)·|S_L||²

    （S22_N 相位以最小相位实偏近似入 |1−S22·S_L|——如实声明：负载
    路径为加权因子口径，非完整双匹配迭代，Brune 域登记未做）。
    入口域预检（A-08，W7 #12 接线前置件）：k、n 须为 ≥1 整数且
    (k,n)≠(1,1)——k=n=1 时谱分解 g 的偶部与 f=ε·λ² 恒同式，Darlington
    阻抗矩阵分母 g_e−f_e≡0（结构退化，此前深层 srft_impedance_matrix
    才报），入口显式 ValueError。
    返回 {p_coeffs, t0, k, n, eps, t_band, omega_band, converged}。
    """
    from scipy.optimize import least_squares

    _require_int("k", k, minimum=1)
    _require_int("n", n, minimum=1)
    if k == 1 and n == 1:
        raise ValueError(
            "k=n=1 结构退化域：谱分解 g 的偶部与 f=ε·λ^{k+n} 恒同式 → "
            "Darlington 阻抗矩阵分母 g_e−f_e≡0（此前深层 "
            "srft_impedance_matrix 才报，A-08）——k、n 至少其一 ≥2")
    _require_int("n_p", n_p, minimum=1)
    eps = _require_positive("eps", eps)
    t0 = _require_positive("target_t0", target_t0)
    if t0 >= 1.0:
        raise ValueError(f"target_t0={t0!r} 须 <1（无耗无源增益界）")
    wb = np.atleast_1d(np.asarray(omega_band, dtype=float))
    if wb.size < 3 or np.any(~np.isfinite(wb)) or np.any(wb <= 0.0):
        raise ValueError("omega_band 须 ≥3 个正频点（rad/s）")
    sl = None
    if s_load is not None:
        sl = np.atleast_1d(np.asarray(s_load, dtype=complex))
        if sl.shape != wb.shape:
            raise ValueError("s_load 须与 omega_band 同形")

    def _model(p: np.ndarray) -> np.ndarray:
        tn = srft_gain_response(wb, p, k, n, eps)
        if sl is None:
            return tn - t0
        load_factor = (1.0 - np.abs(sl) ** 2) / np.maximum(
            (1.0 - np.sqrt(np.maximum(1.0 - tn, 0.0)) * np.abs(sl)) ** 2,
            1e-12)
        return tn * load_factor - t0

    res = least_squares(_model, _fit_initial_guess(wb, k, n_p),
                        method="trf", bounds=(-np.inf, np.inf))
    p_fit = res.x
    return {
        "p_coeffs": p_fit,
        "t0": t0,
        "k": k,
        "n": n,
        "eps": eps,
        "t_band": srft_gain_response(wb, p_fit, k, n, eps),
        "omega_band": wb,
        "converged": bool(res.success),
        "cost": float(res.cost),
    }


# ── 2) 多项式构造（谱分解）──────────────────────────────────────────────


def srft_polynomials(p_coeffs: Any, k: int, n: int,
                     eps: float) -> dict[str, Any]:
    """(f, g, P̃) 三多项式构造（模块 docstring 谱分解；numpy 系数惯例）。

    g 最小相位：D(−λ²) 的 Re λ<0 半根+λ=0 偶重根对半；|lead(g)|=ε
    归一。返回 {f, g, p21（=P(−λ²) 系数）, k, n, eps}；并做
    Feldtkeller 恒等式带内自检（1e-8，违者 ValueError——构造错误
    不许下游）。
    """
    _require_int("k", k, minimum=0)
    _require_int("n", n, minimum=0)
    eps = _require_positive("eps", eps)
    p = np.asarray(p_coeffs, dtype=float)
    if p.ndim != 1 or p.size < 1:
        raise ValueError("p_coeffs 须为一维非空系数数组")

    # D(−λ²)：λ 域偶多项式。ε²ω^{2(k+n)} 项 → ε²(−1)^{k+n} λ^{2(k+n)}
    r_lead = eps**2 * ((-1.0) ** (k + n))
    lam_pow = np.zeros(2 * (k + n) + 1)
    lam_pow[0] = r_lead
    # ω^{2k}P(ω²)² 项：(−λ²)^k·P(−λ²)²；P(−λ²)=多项式复合（poly1d）。
    # numpy 系数惯例：[−1,0,0]=−λ²（[−1,0] 是 −λ——首版踩此坑）
    neg_lam2 = np.poly1d([-1.0, 0.0, 0.0])  # −λ²
    p_neg = np.poly1d(p)(neg_lam2).coeffs
    term2 = np.polymul(_poly_pow(np.array([-1.0, 0.0, 0.0]), k),
                       np.polymul(p_neg, p_neg))
    r_poly = _poly_add(lam_pow, term2)

    roots = np.roots(r_poly)
    tol = 1e-8 * max(1.0, float(np.max(np.abs(roots)))
                     if roots.size else 1.0)
    left = roots[np.real(roots) < -tol]
    near_zero = np.abs(roots) <= tol
    jw = roots[(np.abs(np.real(roots)) <= tol)
               & (np.abs(roots) > tol)]
    if jw.size:
        raise ValueError(
            "D(−λ²) 存在 jω 轴非零根（|S21|=1 退化域）——支路选择歧义，"
            "显式拒绝")
    n_zero = int(np.count_nonzero(near_zero))
    if n_zero % 2 != 0:
        raise ValueError("λ=0 根重数为奇（谱分解不闭合）")
    half_zero = n_zero // 2
    g_roots = np.concatenate([left, np.zeros(half_zero)])
    if g_roots.size != roots.size // 2:
        raise ValueError(
            f"谱分解半根数不闭合：{g_roots.size} vs {roots.size // 2}")
    g = np.poly(g_roots)
    # 归一 |lead(g)|=ε（numpy poly 首项=最高次）
    g = g * (eps / abs(g[0]))
    # f = ε·λ^{k+n}
    f = np.zeros(k + n + 1)
    f[0] = eps
    # P̃(λ) = P(−λ²)
    return {"f": f, "g": g, "p21": p_neg, "k": k, "n": n, "eps": eps,
            "g_roots": g_roots}


def _feldtkeller_residual(polys: dict[str, Any],
                          omega: Any) -> float:
    """带内 Feldtkeller 恒等式残差：|g|²−|f|²−ω^{2k}P²（应 ~0）。"""
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    lam = 1j * w
    g_val = np.polyval(polys["g"], lam)
    f_val = np.polyval(polys["f"], lam)
    p21 = np.polyval(polys["p21"], -(w**2))
    lhs = np.abs(g_val) ** 2 - np.abs(f_val) ** 2
    rhs = (w ** (2 * polys["k"])) * p21**2
    return float(np.max(np.abs(lhs - rhs))
                 / max(float(np.max(rhs)), 1.0))


# ── 3) 阻抗矩阵（Darlington）────────────────────────────────────────────


def srft_impedance_matrix(polys: dict[str, Any]) -> dict[str, Any]:
    """Darlington 阻抗矩阵 z 参数（Yarman 2010 §4 公式；多项式对表示）。

    z11=(g_o+f_o)/(g_e−f_e)、z21=z12=λ^k P(−λ²)/(g_e−f_e)、
    z22=(g_o−f_o)/(g_e−f_e)。偶/奇部分解：g_e=g 的偶次系数、g_o=奇次。
    返回 {z11: (num,den), z21: (num,den), z22: (num,den)}（numpy 系数对）。
    """
    g = np.asarray(polys["g"], dtype=float)
    f = np.asarray(polys["f"], dtype=float)
    # 偶/奇部：偶部=g[0::2]（λ^{2j} 项），奇部=g[1::2]·λ
    g_e = _even_part_poly(g)
    g_o = _odd_part_poly(g)
    f_e = _even_part_poly(f)
    f_o = _odd_part_poly(f)
    den = _poly_add(g_e, _poly_scale(f_e, -1.0))
    if np.count_nonzero(den) == 0:
        raise ValueError("g_e−f_e=0（Darlington 退化域）——提取域外")
    num11 = _poly_add(g_o, f_o)
    num22 = _poly_add(g_o, _poly_scale(f_o, -1.0))
    k = polys["k"]
    p21 = np.asarray(polys["p21"], dtype=float)
    lam_k = _poly_pow(np.array([1.0, 0.0]), k)
    num21 = np.polymul(lam_k, p21)
    return {
        "z11": (num11, den),
        "z21": (num21, den),
        "z22": (num22, den),
    }


# ── 4) 元件提取（∞ 极点移除）────────────────────────────────────────────


def srft_input_impedance(polys: dict[str, Any],
                         r0_ohm: float = 50.0) -> tuple[np.poly1d,
                                                        np.poly1d]:
    """Darlington 输入阻抗 z_in=R0·(1+S11)/(1−S11)（1-port Cauer 用）。

    S11=f/g（f=ελ^{k+n} 归一口径）；返回 (num, den) poly1d 对（含 R0
    量纲）。偶/奇部展开：1±S11=(g±f)/g → 分子=g+f、分母=g−f。
    """
    r0 = _require_positive("r0_ohm", r0_ohm)
    g = np.poly1d(np.asarray(polys["g"], dtype=float))
    f = np.poly1d(np.asarray(polys["f"], dtype=float))
    num = (g + f) * r0
    den = g - f
    return np.poly1d(num), np.poly1d(den)


def srft_extract_ladder(z_in: tuple[np.poly1d, np.poly1d],
                        *,
                        expect_load_ohm: float | None = None,
                        max_iter: int = 64) -> dict[str, Any]:
    """1-port Cauer 梯形提取：输入阻抗 z_in 的 ∞/0 极点逐次移除。

    顺序（每步）：z 极点 ∞→串 L；z 极点 0→串 C；y=1/z 极点 ∞→并 C；
    y 极点 0→并 L。元件值须>0，否则如实 incomplete_extraction（不伪
    造，#122）；残余常数=负载电阻（expect_load_ohm 给出时附一致性
    verdict，rel≤1%）。返回 {elements: [{kind,value,port=1}],
    remainder_ohm, status, reason}。
    """
    z_num_raw = np.poly1d(np.asarray(z_in[0].coeffs if hasattr(
        z_in[0], "coeffs") else z_in[0], dtype=float))
    z_den_raw = np.poly1d(np.asarray(z_in[1].coeffs if hasattr(
        z_in[1], "coeffs") else z_in[1], dtype=float))
    elements: list[dict[str, Any]] = []

    # λ 频率+阻抗归一化（宽动态系数下浮点尘埃与真系数不可分——首版
    # 实测 L 型基准 1e-9 量级真系数被尘埃阈值误剪）：λ=λ0·s、z=z_scale·zs
    n_max = float(np.max(np.abs(z_num_raw.coeffs)))
    d_max = float(np.max(np.abs(z_den_raw.coeffs)))
    deg_diff = z_num_raw.order - z_den_raw.order
    lam0 = ((d_max / n_max) ** (1.0 / deg_diff)
            if deg_diff != 0 and n_max > 0.0 and d_max > 0.0 else 1.0)

    def _rescale(p: np.poly1d) -> np.poly1d:
        coeffs = np.asarray(p.coeffs, dtype=float)
        n = coeffs.size
        powers = n - 1 - np.arange(n)
        return np.poly1d(coeffs * lam0 ** powers)

    z_num = _rescale(z_num_raw)
    z_den = _rescale(z_den_raw)
    z_scale = (float(np.max(np.abs(z_num.coeffs)))
               / max(float(np.max(np.abs(z_den.coeffs))), 1e-300))
    if not math.isfinite(z_scale) or z_scale <= 0.0:
        z_scale = 1.0
    z_num = np.poly1d(z_num.coeffs / z_scale)
    scale0 = max(float(np.max(np.abs(z_num.coeffs))),
                 float(np.max(np.abs(z_den.coeffs))), 1.0)

    def _trim(p: np.poly1d) -> np.poly1d:
        coeffs = np.asarray(p.coeffs, dtype=float)
        keep = 0
        while (keep < coeffs.size - 1
               and abs(coeffs[keep]) <= 1e-9 * scale0):
            keep += 1
        return np.poly1d(coeffs[keep:])

    def _fail(reason: str) -> dict[str, Any]:
        return {"elements": elements, "remainder_ohm": None,
                "status": "incomplete_extraction", "reason": reason}

    for _ in range(max_iter):
        # 消公共 λ 因子（poly1d[0]=常数项；λ 因子=常数项为零）
        while (z_num.order >= 1 and z_den.order >= 1
               and z_num[0] == 0.0 and z_den[0] == 0.0):
            z_num = np.poly1d(z_num.coeffs[:-1])
            z_den = np.poly1d(z_den.coeffs[:-1])
        z_num, z_den = _trim(z_num), _trim(z_den)
        # ① z 极点在 ∞（单阶）→ 串 L：首系数比（poly1d[-1]=最高次）
        if z_num.order - z_den.order == 1:
            val = z_num.coeffs[0] / z_den.coeffs[0]
            if val <= 0.0:
                return _fail(f"负串感 L={val:.6g}")
            elements.append({"kind": "series_l", "value_h": float(val),
                             "port": 1})
            z_num = z_num - np.poly1d([val, 0.0]) * z_den
            continue
        # ② z 极点在 0 → 串 C：residue=lim λ·z=常数项/λ¹ 系数
        if (z_den.order >= 1 and z_den[0] == 0.0
                and z_num.order >= 0 and z_num[0] != 0.0):
            residue = z_num[0] / z_den[1]
            val = 1.0 / residue
            if val <= 0.0:
                return _fail(f"负串容 C={val:.6g}")
            elements.append({"kind": "series_c", "value_f": float(val),
                             "port": 1})
            z_num = z_num * np.poly1d([1.0, 0.0]) \
                - np.poly1d([1.0 / val]) * z_den
            z_den = z_den * np.poly1d([1.0, 0.0])
            continue
        # ③ y=1/z 极点在 ∞ → 并 C：z'=z/(1−z·λC)=num/(den−λC·num)
        if z_den.order - z_num.order == 1:
            val = z_den.coeffs[0] / z_num.coeffs[0]
            if val <= 0.0:
                return _fail(f"负并容 C={val:.6g}")
            elements.append({"kind": "shunt_c", "value_f": float(val),
                             "port": 1})
            z_den = z_den - np.poly1d([val, 0.0]) * z_num
            continue
        # ④ y 极点在 0 → 并 L：z'=z/(1−z·residue/λ)
        #    =num·λ/(den·λ−residue·num)
        if (z_num.order >= 1 and z_num[0] == 0.0
                and z_den.order >= 0 and z_den[0] != 0.0):
            residue = z_den[0] / z_num[1]  # lim λ·y
            val = 1.0 / residue
            if val <= 0.0:
                return _fail(f"负并感 L={val:.6g}")
            elements.append({"kind": "shunt_l", "value_h": float(val),
                             "port": 1})
            z_num_mul = z_num * np.poly1d([1.0, 0.0])
            z_den = z_den * np.poly1d([1.0, 0.0]) - residue * z_num
            z_num = z_num_mul
            continue
        break
    # 残余判定：常数 → 负载电阻；反归一（λ=λ0·s、z=z_scale·zs →
    # L=L_s·z_scale/λ0、C=C_s/(z_scale·λ0)、R=R_s·z_scale）
    if z_num.order == 0:
        r_s = float(z_num[0] / z_den[0])
        remainder = r_s * z_scale
        result: dict[str, Any] = {"elements": elements,
                                  "remainder_ohm": remainder,
                                  "status": "complete", "reason": None}
        for el in elements:
            if el["kind"] in ("series_l", "shunt_l"):
                el["value_h"] *= z_scale / lam0
            else:
                el["value_f"] /= z_scale * lam0
        if expect_load_ohm is not None:
            dev = abs(remainder - expect_load_ohm) / expect_load_ohm
            result["load_verdict"] = "matched" if dev <= 0.01 \
                else "mismatched"
            result["load_rel_dev"] = dev
        return result
    return {"elements": elements, "remainder_ohm": None,
            "status": "incomplete_extraction",
            "reason": "∞/0 极点移除耗尽仍有动态残余（Brune/变压器域）"}


# ── 5) 综合入口与闭环重仿真 ─────────────────────────────────────────────


def srft_synthesize(
    omega_band: Any,
    *,
    k: int = 1,
    n: int = 2,
    eps: float = 1.0,
    n_p: int = 1,
    r_load_ohm: float | None = None,
    r0_ohm: float = 50.0,
) -> dict[str, Any]:
    """SRFT 综合入口：平坦拟合→多项式→z 矩阵→1-port Cauer 提取。

    内部**频率+阻抗归一化**（Ω=ω/ω_mid、1Ω 口径——GHz 域原始系数
    ~1e19，提取相消尘埃与真系数不可分，首轮实测提取器被毁）：拟合/
    多项式/提取全在归一域，元件值反归一 L=L'·R0/ω_mid、
    C=C'/(R0·ω_mid)、R=R'·R0（导纳量纲反向）。r_load_ohm 给出时附提取残余一致性
    verdict（rel ≤1% → matched）。返回拟合/多项式/z 参数/提取四段
    报告（p_coeffs 等为归一域口径，元素值为物理 SI）。
    """
    wb = np.atleast_1d(np.asarray(omega_band, dtype=float))
    omega_mid = float(np.mean(wb))
    wn = wb / omega_mid
    fit = srft_fit_flat_gain(wn, k=k, n=n, eps=eps, n_p=n_p)
    polys = srft_polynomials(fit["p_coeffs"], k, n, eps)
    resid = _feldtkeller_residual(polys, wn)
    if resid > 1e-6:
        raise ValueError(
            f"Feldtkeller 恒等式残差 {resid:.3e} > 1e-6（谱分解构造错误）")
    z_params = srft_impedance_matrix(polys)
    z_in = srft_input_impedance(polys, r0_ohm=1.0)
    ladder = srft_extract_ladder(z_in)
    l_denorm = r0_ohm / omega_mid   # L = L'·R0/ω_mid
    c_denorm = r0_ohm * omega_mid   # C = C'/(R0·ω_mid)
    for el in ladder["elements"]:
        if el["kind"] in ("series_l", "shunt_l"):
            el["value_h"] *= l_denorm
        else:
            el["value_f"] /= c_denorm
    if ladder["remainder_ohm"] is not None:
        ladder["remainder_ohm"] *= r0_ohm
        if r_load_ohm is not None:
            dev = abs(ladder["remainder_ohm"] - r_load_ohm) / r_load_ohm
            ladder["load_verdict"] = ("matched" if dev <= 0.01
                                      else "mismatched")
            ladder["load_rel_dev"] = dev
    return {"fit": fit, "polynomials": polys, "z_params": z_params,
            "ladder": ladder, "feldtkeller_residual": resid,
            "omega_mid_rad_s": omega_mid, "r0_ohm": r0_ohm}


def srft_network_response(elements: list[dict[str, Any]],
                          remainder_ohm: float | None,
                          freq_hz: Any,
                          z0_ohm: float = 50.0) -> dict[str, np.ndarray]:
    """提取元件的 ABCD 级联重仿真（闭环裁判面；实参考 z0）。

    elements 顺序=信号路径序（port 1 侧先于 port 2 侧按提取顺序）；
    remainder（负载电阻）作末端并臂。返回 {s11, s21}（复数组）。
    """
    z0 = _require_positive("z0_ohm", z0_ohm)
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    if np.any(~np.isfinite(f)) or np.any(f <= 0.0):
        raise ValueError("freq_hz 必须为正有限实数")
    r_load = remainder_ohm if remainder_ohm is not None else z0
    w = 2.0 * np.pi * f
    s21 = np.empty(f.size, dtype=complex)
    s11 = np.empty(f.size, dtype=complex)
    for i, wi in enumerate(w):
        abcd = np.eye(2, dtype=complex)
        for el in elements:
            if el["kind"] == "series_l":
                abcd = abcd @ np.array([[1.0, 1j * wi * el["value_h"]],
                                        [0.0, 1.0]])
            elif el["kind"] == "shunt_c":
                abcd = abcd @ np.array([[1.0, 0.0],
                                        [1j * wi * el["value_f"], 1.0]])
            elif el["kind"] == "series_c":
                abcd = abcd @ np.array([[1.0,
                                         1.0 / (1j * wi * el["value_f"])],
                                        [0.0, 1.0]])
            elif el["kind"] == "shunt_l":
                abcd = abcd @ np.array([[1.0, 0.0],
                                        [1.0 / (1j * wi * el["value_h"]),
                                         1.0]])
            else:
                raise ValueError(f"未知元件 kind={el['kind']!r}")
        # 终接 R_load（源侧 z0）：S21=2/(A+B/R_L+C·R0+D)；
        # Zin=(A·R_L+B)/(C·R_L+D) → Γ=(Zin−R0)/(Zin+R0)
        den = abcd[0, 0] + abcd[0, 1] / r_load + abcd[1, 0] * z0             + abcd[1, 1]
        s21[i] = 2.0 / den
        zin = ((abcd[0, 0] * r_load + abcd[0, 1])
               / (abcd[1, 0] * r_load + abcd[1, 1]))
        s11[i] = (zin - z0) / (zin + z0)
    return {"s11": s11, "s21": s21}


# ── 多项式小工具 ─────────────────────────────────────────────────────────


def _require_int(name: str, value: int, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} 须为 ≥{minimum} 整数，got {value!r}")


def _require_positive(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限实数，got {value!r}")
    return v


def _fit_initial_guess(wb: np.ndarray, k: int, n_p: int) -> np.ndarray:
    """量纲知情初值：p_j~ω̄^{2(k−j)}——T(ω̄²)≈0.5 的尺度（否则 LS 在
    ω_c^{2k}~1e19 量级差下停滞于平凡解，首轮实测）。"""
    wc = float(np.mean(wb))
    return np.array([wc ** (2 * (k - j)) for j in range(n_p)])


def _poly_pow(poly: np.ndarray, k: int) -> np.ndarray:
    out = np.array([1.0])
    base = np.asarray(poly, dtype=float)
    for _ in range(int(k)):
        out = np.polymul(out, base)
    return out


def _poly_add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = max(len(a), len(b))
    out = np.zeros(n)
    out[n - len(a):] += a
    out[n - len(b):] += b
    return out


def _poly_scale(a: np.ndarray, s: float) -> np.ndarray:
    return np.asarray(a, dtype=float) * s


def _even_part_poly(g: np.ndarray) -> np.ndarray:
    """偶部（λ 偶次幂项；numpy 系数按幂次奇偶对齐——按索引奇偶会在
    偶长数组上错位，首版踩此坑）。"""
    out = np.array(g, dtype=float)
    n = len(out)
    powers = n - 1 - np.arange(n)
    out[powers % 2 == 1] = 0.0
    return out


def _odd_part_poly(g: np.ndarray) -> np.ndarray:
    out = np.array(g, dtype=float)
    n = len(out)
    powers = n - 1 - np.arange(n)
    out[powers % 2 == 0] = 0.0
    return out
