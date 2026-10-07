"""C13 耦合矩阵内核（广义切比雪夫原型→Cameron N+2 综合→folded/arrow 约简，含显式 TZ 口径）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

import numpy as np

from .registry import register_calculator

# ─── C13 耦合矩阵内核（广义切比雪夫 → Cameron N+2 → folded/arrow）────────────
# 口径（Cameron, Microwave Filters for Communication Systems, ch.6/8）：
#   S11(s)=F(s)/E(s), S21(s)=P(s)/(ε·E(s))；归一化低通带边 Ω=1 处 F_N=1，
#   ε = 1/√(10^(RL/10) − 1)。广义切比雪夫滤波函数用 cosh 和构造：
#   F_N(Ω) = (ΠY_k + ΠY_k⁻¹)/2，Y_k = X_k + √(X_k²−1)（主值分支），
#   无穷远 TZ：X = Ω（每项扫 π）；有限 TZ 对 ±Ω_k：X_k = Ω√(Ω_k²−1)/√(Ω_k²−Ω²)
#   （计入两次，一对 TZ 扫 2π，F = cosh(2·acosh X) = 2X²−1）。
#   耦合矩阵响应（本项目校准口径，N=1 解析锚 + 幺正性单测钉住）：
#   Y = diag(q₀,0..,q_L) + j(Ω·W − M)，W = diag(0,1..1,0)，
#   v = Y⁻¹e₀，S11 = 1 − 2v₀/q₀，S21 = 2v_L/√(q₀q_L)。
#   N+2 横向矩阵（C13 stage-2 闭式，Cameron 1999 §III-B / 书 §8.2）：
#   a=E+F 按与 N 同/异奇偶次拆成 D/Nu，y22=Nu/D，y21=P'/(εD)，
#   P'=jP 当 (N−n_fz) 为偶（j 规则，保证 jω 轴上 Y 纯虚）；留数
#   r22k=Nu(p_k)/D'(p_k)、r21k=P'(p_k)/(εD'(p_k))，横向元 m_kk=−jp_k、
#   m_0k=√r22k、m_kL=r21k/m_0k、m_0L=jK∞（全规范）。本口径下
#   y11(s)=Σm_0k²/(s−jm_kk) 等，闭式精确（vs 多项式响应 ≤1e−9，单测钉住），
#   LM 精化仅作数值病态兜底（它不保 y11=y22 结构，折叠序列需要该结构）。
#   拓扑约简用复正交合同旋转 M←RMRᵀ（RᵀR=I）：响应严格不变（分析矩阵
#   ΩW−jM+diag(q) 的三段 W/M/q 合同协变性有单测钉住）。folded 走经典
#   palindromic 序列（奇数轮消行右→左 pivot(l−1,l)、偶数轮消列上→下
#   pivot(k,k+1)，由外向内；对照 Yellowbooker/Standard-Coupling-Matrix-
#   Synthesis-Code to_foldedCM.m）。交叉耦合族按 TZ 计数规则自适应：
#   n_fz = N − (S→L 最短路径谐振器数)，反对角 i+j=N+1 给 N−2,N−4,…（偶 N
#   的对称 TZ 对）；奇 N 的偶数 n_fz 只能落在移位反对角 i+j=N+2
#   （(2,N),(3,N−1),…，如 N=5 的 2-5 四元组）。q = (1,1) 为本项目归一化约定
#   （谐振器斜率归一，外部耦合信息全部在 m₀ᵢ/m_{iL} 内）。

def _gcheb_yprod(tz_pairs, n_inf, w):
    """广义切比雪夫滤波函数的 Y 乘积（复主值分支）。"""
    w = np.asarray(w, dtype=complex)
    prod = np.ones_like(w)
    for wz in tz_pairs:
        x = w * math.sqrt(wz * wz - 1.0) / np.sqrt(wz * wz - w * w)
        y = x + np.sqrt(x * x - 1.0)
        prod = prod * y * y
    for _ in range(n_inf):
        prod = prod * (w + np.sqrt(w * w - 1.0))
    return prod


def _gcheb_fn(tz_pairs, n_inf, w):
    prod = _gcheb_yprod(tz_pairs, n_inf, np.asarray(w, dtype=complex))
    return 0.5 * (prod + 1.0 / prod)


def _gcheb_reflection_zeros(tz_pairs, n_inf, n_grid=4001):
    """F_N 在 (−1,1) 内的 N 个零点（单调扫频 + 对分，#118：不赌收敛）。"""
    wgrid = np.linspace(-1.0 + 1e-12, 1.0 - 1e-12, n_grid)
    fn = np.real(_gcheb_fn(tz_pairs, n_inf, wgrid))
    idx = np.where(np.diff(np.sign(fn)) != 0)[0]
    order = 2 * len(tz_pairs) + n_inf
    if len(idx) != order:
        raise ValueError(f"反射零点数 {len(idx)} != 阶数 {order}")
    roots = []
    for i in idx:
        a, b, fa = wgrid[i], wgrid[i + 1], fn[i]
        for _ in range(80):
            m = 0.5 * (a + b)
            fm = float(np.real(_gcheb_fn(tz_pairs, n_inf, np.array([m]))[0]))
            if fm == 0.0:
                a = b = m
                break
            if np.sign(fm) == np.sign(fa):
                a, fa = m, fm
            else:
                b = m
        roots.append(0.5 * (a + b))
    return np.array(sorted(roots))


def _gcheb_prototype(order, rl_db, tz_pairs):
    """广义切比雪夫原型 → (ε, 反射零点, f~, p~, F(s), P(s), E(s))。

    对称口径：TZ 以 ±ω_k 对给出（|ω_k|>1），其余在无穷远；
    F(s)/P(s) 取实系数规范（F 首项系数对齐 f~），E 取 Hurwitz 半边
    （尺度保持，E(s)E(−s)=G(−s²)，G(x)=f~²+p~²/ε² 的 x=Ω² 系数）。
    """
    n_pairs = len(tz_pairs)
    n_inf = order - 2 * n_pairs
    if n_inf < 0:
        raise ValueError(f"TZ 对数 {n_pairs} 超出阶数 {order}")
    eps = 1.0 / math.sqrt(10.0 ** (rl_db / 10.0) - 1.0)
    rz = _gcheb_reflection_zeros(tz_pairs, n_inf)
    f_w = np.real(np.poly(rz))
    p_tilde = np.array([1.0])
    p_s = np.array([1.0])
    for wz in tz_pairs:
        p_tilde = np.polymul(p_tilde, np.array([-1.0, 0.0, wz * wz]))
        p_s = np.polymul(p_s, np.array([1.0, 0.0, wz * wz]))
    f_tilde = f_w * (np.polyval(p_tilde, 1.0) / np.polyval(f_w, 1.0))

    def even_x(poly_w):
        d = len(poly_w) - 1
        out = [(p // 2, cc) for p, cc in
               ((d - k, cc) for k, cc in enumerate(poly_w)) if p % 2 == 0]
        deg = max(pp for pp, _ in out)
        arr = np.zeros(deg + 1)
        for pp, cc in out:
            arr[deg - pp] = cc
        return arr

    gx_f = even_x(np.polymul(f_tilde, f_tilde))
    gx_p = even_x(np.polymul(p_tilde, p_tilde))
    n_max = max(len(gx_f), len(gx_p))
    g_x = (np.concatenate([np.zeros(n_max - len(gx_f)), gx_f])
           + np.concatenate([np.zeros(n_max - len(gx_p)), gx_p]) / eps ** 2)
    degx = len(g_x) - 1
    h_poly = np.zeros(2 * degx + 1)
    for k, cc in enumerate(g_x):
        h_poly[2 * k] = cc * ((-1.0) ** (degx - k))
    roots_h = np.roots(h_poly)
    e_s = np.real(np.poly(roots_h[np.real(roots_h) < 0])) * math.sqrt(g_x[0])
    f_s = np.real(np.poly(1j * rz)) * f_tilde[0]
    return {"eps": eps, "rz": rz, "f_tilde": f_tilde, "p_tilde": p_tilde,
            "f_s": f_s, "p_s": p_s, "e_s": e_s}


def _cm_response_raw(m, qe0, qel, omega):
    """耦合矩阵频响（−jM 经典口径，合同不变）。返回 (S11, S21)。"""
    n2 = m.shape[0]
    Y = np.zeros((n2, n2), dtype=complex)
    for i in range(n2):
        for j in range(n2):
            if i == j:
                if i == 0:
                    Y[i, i] = qe0
                elif i == n2 - 1:
                    Y[i, i] = qel
                else:
                    Y[i, i] = 1j * (omega - m[i, i])
            else:
                Y[i, j] = -1j * m[i, j]
    b = np.zeros(n2, dtype=complex)
    b[0] = 1.0
    v = np.linalg.solve(Y, b)
    return 1.0 - 2.0 * v[0] / qe0, 2.0 * v[n2 - 1] / math.sqrt(qe0 * qel)


def _cm_transversal_exact(order, proto):
    """Cameron Y 留数法 N+2 横向矩阵（闭式精确，C13 stage-2；inc3 起支持
    复系数原型）。

    口径（Cameron 1999 IEEE T-MTT 47(4) §III-B；书 §8.2；口径块见文件头）：
    a(s)=E+F 按次幂与 N 同/异奇偶拆 D/Nu（同奇偶取实部→D、虚部→Nu；
    异奇偶反之），y22=Nu/D、y21=P'/(εD)，P'=jP 当 (N−n_fz) 为偶。
    留数 r22k/r21k 于 D 的根 p_k；m_kk=−j p_k、m_0k=√r22k、m_kL=r21k/m_0k、
    m_0L=j·K∞（P'/(εD) 的常数项，仅全规范时非零）。谐振器按 m_kk 降序。
    裁判=多项式闭式响应（_poly_response）逐点对照（#118）。
    复系数原型（真·非成对 TZ，_gcheb_prototype_explicit complex 分支）：
    E+F 非实系数，但 D/Nu 的「取实部/取 j×虚部」拆分即 Cameron §III-A 的
    complex-even/complex-odd 实化构造——jω 轴 TZ 集下 F 全实、P/E 低次幂
    交替纯虚，拆分后 D/Nu 均实，横向矩阵可含复元（复对称 M=Mᵀ，
    |m_0k| 与 |m_kL| 允许不等＝非对称网络），|S11|/|S21| 与原型逐点一致
    （实测 N=2..6 ≤1.3e−13，单测钉住）。
    """
    eps = proto["eps"]
    es, fs, ps = proto["e_s"], proto["f_s"], proto["p_s"]
    n = int(order)
    nfz = len(ps) - 1
    p_eff = np.asarray(ps, dtype=complex) / eps
    if (n - nfz) % 2 == 0:
        p_eff = 1j * p_eff
    a = np.polyadd(np.asarray(es, dtype=complex), np.asarray(fs, dtype=complex))
    deg = len(a) - 1
    d_poly = np.zeros(deg + 1, dtype=complex)
    nu_poly = np.zeros(deg + 1, dtype=complex)
    for idx, coef in enumerate(a):
        k = deg - idx
        if (k - n) % 2 == 0:
            d_poly[idx] = coef.real
            nu_poly[idx] = 1j * coef.imag
        else:
            d_poly[idx] = 1j * coef.imag
            nu_poly[idx] = coef.real
    d_poly = np.trim_zeros(d_poly, "f")
    if len(d_poly) - 1 != n:
        raise ValueError(f"Y 分母次数 {len(d_poly) - 1} != 阶数 {n}")
    poles = np.roots(d_poly)
    d_der = np.polyder(d_poly)
    r22 = np.array([np.polyval(nu_poly, p) / np.polyval(d_der, p)
                    for p in poles])
    r21 = np.array([np.polyval(p_eff, p) / np.polyval(d_der, p)
                    for p in poles])
    k_inf = 0j
    if len(p_eff) >= len(d_poly):
        quot, _ = np.polydiv(p_eff, d_poly)
        k_inf = complex(quot[-1])
    n2 = n + 2
    ma = np.zeros((n2, n2), dtype=complex)
    for i, k in enumerate(np.argsort(-np.imag(poles))):
        r = i + 1
        ma[r, r] = -1j * poles[k]
        t0 = np.sqrt(r22[k])
        tl = r21[k] / t0
        ma[0, r] = ma[r, 0] = t0
        ma[r, n2 - 1] = ma[n2 - 1, r] = tl
    ma[0, n2 - 1] = ma[n2 - 1, 0] = 1j * k_inf
    return ma


def _cm_poly_max_err(m, proto, n_grid=241):
    """耦合矩阵 vs 多项式闭式响应的 |S11|/|S21| 最大偏差（独立裁判）。"""
    err = 0.0
    for w_ in np.linspace(-1.0, 1.0, n_grid):
        s11c, s21c = _cm_response_raw(m, 1.0, 1.0, w_)
        s11p, s21p = _poly_response(proto, np.array([w_]))
        err = max(err, abs(abs(s21c) - abs(s21p[0])),
                  abs(abs(s11c) - abs(s11p[0])))
    return float(err)


def _cm_unpack(x, n2):
    k = n2 - 2
    m = x[0:k] + 1j * x[k:2 * k]
    t0 = x[2 * k:3 * k] + 1j * x[3 * k:4 * k]
    tl = x[4 * k:5 * k] + 1j * x[5 * k:6 * k]
    ma = np.zeros((n2, n2), dtype=complex)
    for i in range(k):
        ma[i + 1, i + 1] = m[i]
        ma[0, i + 1] = ma[i + 1, 0] = t0[i]
        ma[i + 1, n2 - 1] = ma[n2 - 1, i + 1] = tl[i]
    return ma


def _cm_pack(ma):
    n2 = ma.shape[0]
    return np.concatenate([np.diag(ma)[1:n2 - 1].real,
                           np.diag(ma)[1:n2 - 1].imag,
                           ma[0, 1:n2 - 1].real, ma[0, 1:n2 - 1].imag,
                           ma[1:n2 - 1, n2 - 1].real,
                           ma[1:n2 - 1, n2 - 1].imag])


def _cm_polish(order, proto, ma0, wgrid, rounds=4):
    """LM 最小二乘幅频精化（确定性内核；锚=多项式闭式响应）。"""
    from scipy.optimize import least_squares

    n2 = ma0.shape[0]
    x = _cm_pack(ma0)
    tgt = []
    for w_ in wgrid:
        s11p, s21p = _poly_response(proto, np.array([w_]))
        tgt.append((abs(s11p[0]), abs(s21p[0])))

    def resid(xx):
        ma = _cm_unpack(xx, n2)
        out = []
        for w_, (t11, t21) in zip(wgrid, tgt, strict=True):
            s11c, s21c = _cm_response_raw(ma, 1.0, 1.0, w_)
            out.append(abs(s11c) - t11)
            out.append(abs(s21c) - t21)
        return np.array(out)

    res = None
    for _ in range(rounds):
        res = least_squares(resid, x, method="lm", xtol=1e-15,
                            ftol=1e-15, max_nfev=2000)
        x = res.x
        if np.max(np.abs(res.fun)) < 1e-11:
            break
    return _cm_unpack(x, n2), res


def _poly_response(proto, omega):
    """多项式闭式响应（独立裁判）：S11=F/E, S21=P/(εE)。"""
    eps = proto["eps"]
    E = np.polyval(proto["e_s"].astype(complex), 1j * omega)
    s11 = np.polyval(proto["f_s"].astype(complex), 1j * omega) / E
    s21 = np.polyval(proto["p_s"].astype(complex), 1j * omega) / (eps * E)
    return s11, s21


def _cm_cong_rot(M, p, q, c, s):
    """复正交合同旋转 M ← RMRᵀ（RᵀR=I：响应与对称性严格保持）。"""
    n2 = M.shape[0]
    R = np.eye(n2, dtype=complex)
    R[p, p] = c
    R[q, q] = c
    R[p, q] = s
    R[q, p] = -s
    return R @ M @ R.T


def _cm_reduce_arrow(m, tol=1e-13):
    """横向 → arrow：载行清理 + 源行清理 + 块三对角化（合同旋转）。"""
    n2 = m.shape[0]
    M = m.copy()
    for j in range(1, n2 - 2):
        if abs(M[n2 - 1, j]) < tol:
            continue
        t = M[n2 - 1, j] / M[n2 - 1, n2 - 2]
        c = 1.0 / np.sqrt(1.0 + t * t)
        M = _cm_cong_rot(M, n2 - 2, j, c, t * c)
    for j in range(2, n2 - 1):
        if abs(M[0, j]) < tol:
            continue
        t = M[0, j] / M[0, 1]
        c = 1.0 / np.sqrt(1.0 + t * t)
        M = _cm_cong_rot(M, 1, j, c, t * c)
    for rr in range(1, n2 - 3 + 1):
        for k in range(n2 - 2, rr + 1, -1):
            if abs(M[rr, k]) < tol:
                continue
            t = M[rr, k] / M[rr, rr + 1]
            c = 1.0 / np.sqrt(1.0 + t * t)
            M = _cm_cong_rot(M, rr + 1, k, c, t * c)
    return M


def _cm_folded_keepers(n2):
    """folded 反对角族 keeper：次对角 + (0,L) + 交叉 i+j=N+1（0-based i+j=n2−1）。

    TZ 计数规则：交叉 (i, n2−1−i) 给 n_fz = N−2i（偶 N 的对称 TZ 对全在此族）。
    """
    L = n2 - 1
    keep = {(i, i + 1) for i in range(n2 - 1)}
    keep.add((0, L))
    for i in range(1, n2 - 2):
        j = L - i
        if j > i + 1:
            keep.add((i, j))
    return keep


def _cm_folded_keepers_shifted(n2):
    """folded 移位反对角族 keeper：次对角 + 交叉 i+j=N+2（0-based i+j=n2）。

    奇 N 的偶数 n_fz 只能落在此族：(1,L)→N−1、(2,N)→N−3、(3,N−1)→N−5…
    （反对角族在奇 N 时只给奇数 n_fz）。对称 ±TZ 对原型的奇数阶结果
    （如 N=5 的 2-5 四元组）即此族。
    """
    keep = {(i, i + 1) for i in range(n2 - 1)}
    for i in range(1, n2 - 1):
        j = n2 - i
        if i < j < n2 and j > i + 1:
            keep.add((i, j))
    return keep


def _cm_pattern_viol(m, keepers, tol):
    n2 = m.shape[0]
    return [(i, j, abs(m[i, j])) for i in range(n2) for j in range(i + 1, n2)
            if (i, j) not in keepers and abs(m[i, j]) > tol]


def _cm_folded_family(m, tol=1e-9):
    """判定 folded 结果的交叉耦合族：anti / shifted / none / mixed。"""
    n2 = m.shape[0]
    sub = {(i, i + 1) for i in range(n2 - 1)}
    anti = max((abs(m[i, j]) for i, j in _cm_folded_keepers(n2) - sub),
               default=0.0)
    shifted = max((abs(m[i, j])
                   for i, j in _cm_folded_keepers_shifted(n2) - sub),
                  default=0.0)
    if anti <= tol and shifted <= tol:
        return "none"
    if anti > tol and shifted > tol:
        return "mixed"
    return "anti" if anti > tol else "shifted"


def _cm_sign_normalize(m, preserve_s21_phase=False):
    """节点 ±1 相似归一：M ← DMD，D=diag(1, d_1..d_N, d_L)，d_k=±1。

    规则（显式口径）：
    - 源节点永不翻（d_0=1）⟹ S11/S22 严格不变（D 与 W/q 交换，且
      Y→DYD、v→Dv 下 v_0 只乘 d_0）；
    - 主线耦合 m_{k−1,k} 逐个扫过（k=1..），real<0 即翻节点 k：
      默认 mainline_positive 口径扫到载端（k=L），m_{N,L} 归正——
      **代价是 S21 相位可能翻 180°**（S21×d_L，|S| 不变，参考面约定）；
    - preserve_s21_phase=True 只翻谐振器节点（k=1..N），载端 d_L=1
      ⟹ S21 相位与输入严格同相，末端 m_{N,L} 允许为负（下游相位对拍
      用此口径）。
    返回 (M, d)：d 为符号向量，d_L=+1 ⟺ S21 相位未翻。
    """
    M = m.copy()
    n2 = M.shape[0]
    d = np.ones(n2)
    k_last = n2 - 2 if preserve_s21_phase else n2 - 1
    for k in range(1, k_last + 1):
        if M[k - 1, k].real < 0:
            d[k] = -1.0
            M[k, :] *= -1
            M[:, k] *= -1
    return M, d


def _cm_s21_phase_flipped(m_in, m_out, tol=1e-6):
    """判定 m_out 相对 m_in 的 S21 相位是否翻 180°（|S| 严格不变的
    相似变换后唯一可见差异）。取带中心 Ω=0（|S21| 最大、相位最稳），
    |S21(0)| 过小时回退 Ω=±0.3 多数票。"""
    for w in (0.0, 0.3, -0.3):
        _, a = _cm_response_raw(m_in, 1.0, 1.0, w)
        _, b = _cm_response_raw(m_out, 1.0, 1.0, w)
        if abs(a) > tol and abs(b) > tol:
            return bool((b / a).real < 0)
    return False


def _cm_reduce_folded(m, tol=1e-13, preserve_s21_phase=False):
    """横向 → folded：经典 palindromic 旋转序列（Cameron；复正交合同旋转）。

    序列（0-based，S=N+2，轮次 i=1..S−3）：
    - 奇数轮 t=(i+1)/2：消行 r=t−1 的列 l=S−t−1 → t+1（右→左），
      pivot (l−1,l)，θ=atan(−M[r,l]/M[r,l−1])；
    - 偶数轮 t=i/2：消列 c=S−t 的行 k=t+1 → S−t−2（上→下），
      pivot (k,k+1)，θ=atan(M[k,c]/M[k+1,c])。
    每轮留一个"自动位" (t, S−t)（i+j=S 移位反对角）不显式消：对称 TZ
    对原型在偶 N 时它自动为零，在奇 N 时它恰是承载偶数 n_fz 的交叉耦合
    （TZ 计数规则，见 _cm_folded_keepers_shifted）。共 N(N−1)/2 次旋转，
    旋转全在谐振器块内（不触源/载节点），频响严格不变。
    输入须为横向矩阵（对角+源行+载列）；任意输入亦可跑，残留如实返回。
    preserve_s21_phase 语义见 _cm_sign_normalize（默认 mainline_positive
    可能把载端翻 −1 ⟹ S21 相位对输入翻 180°）。
    返回 (M, bad)：bad 为两族 keeper 中残留更小者的违例 [(i, j, |m|)]。
    """
    S = m.shape[0]
    M = m.astype(complex).copy()
    for i in range(1, S - 2):
        if i % 2 == 1:
            t = (i + 1) // 2
            r = t - 1
            for col in range(S - t - 1, t, -1):
                num, den = M[r, col], M[r, col - 1]
                if abs(num) < tol:
                    continue
                th = np.arctan(-num / den) if abs(den) > 0 else np.pi / 2
                M = _cm_cong_rot(M, col - 1, col, np.cos(th), -np.sin(th))
        else:
            t = i // 2
            col = S - t
            for r in range(t + 1, S - t - 1):
                num, den = M[r, col], M[r + 1, col]
                if abs(num) < tol:
                    continue
                th = np.arctan(num / den) if abs(den) > 0 else np.pi / 2
                M = _cm_cong_rot(M, r, r + 1, np.cos(th), -np.sin(th))
    M, _ = _cm_sign_normalize(M, preserve_s21_phase=preserve_s21_phase)
    bad_anti = _cm_pattern_viol(M, _cm_folded_keepers(S), 1e-9)
    bad_shift = _cm_pattern_viol(M, _cm_folded_keepers_shifted(S), 1e-9)
    bad = min((bad_anti, bad_shift),
              key=lambda b: max((v for _, _, v in b), default=0.0))
    return M, bad


@register_calculator(
    "chebyshev_prototype",
    "广义切比雪夫原型（chebyshev_g 等价形式）：阶数+回损+传输零点 → "
    "F/P/E 多项式系数与反射零点（Cameron 口径，S11=F/E, S21=P/(εE)）",
    (("order", "int - 滤波器阶数（≥1）"),
     ("rl_db", "float dB 带内回波损耗纹波（>0）"),
     ("transmission_zeros", "array 归一化低通传输零点 |Ω|>1 列表"
      "（±ω 成对口径，缺省=全极点）")),
    required=("order", "rl_db"),
)
def chebyshev_prototype(order: int, rl_db: float,
                        transmission_zeros: list | None = None) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    tz = tuple(float(z) for z in (transmission_zeros or []))
    if len(tz) > order // 2 or any(abs(z) <= 1.0 for z in tz):
        raise ValueError("TZ 对数须 ≤ order//2 且 |Ω|>1")
    proto = _gcheb_prototype(order, rl_db, tz)

    def cplx(p):
        return [[round(v.real, 9), round(v.imag, 9)] for v in p]

    return {"ok": True, "order": order, "rl_db": rl_db,
            "epsilon": round(proto["eps"], 9),
            "reflection_zeros": [round(r, 9) for r in proto["rz"]],
            "f_s": cplx(proto["f_s"]), "p_s": cplx(proto["p_s"]),
            "e_s": cplx(proto["e_s"])}


@register_calculator(
    "chebyshev_refl_fn",
    "全极点切比雪夫反射函数：n+rz_db+Ω → |S11|/|S21|（闭式 "
    "|S11|=ε|T_n(Ω)|/√(1+ε²T_n²)，带边 Ω=1 处纹波峰值=−RL）",
    (("n", "int - 阶数"),
     ("rz_db", "float dB 带内回损纹波（>0）"),
     ("omega", "array 归一化低通频率轴")),
    required=("n", "rz_db", "omega"),
)
def chebyshev_refl_fn(n: int, rz_db: float, omega: list) -> dict:
    n = int(n)
    if n < 1:
        raise ValueError("阶数必须 ≥1")
    if rz_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    w = np.asarray(omega, dtype=float)
    if w.size == 0:
        raise ValueError("omega 不能为空")
    eps = 1.0 / math.sqrt(10.0 ** (rz_db / 10.0) - 1.0)
    tn = np.ones_like(w)
    if n >= 1:
        t0v, t1v = np.ones_like(w), w.copy()
        for _ in range(n - 1):
            t0v, t1v = t1v, 2 * w * t1v - t0v
        tn = t1v
    s11 = eps * tn / np.sqrt(1.0 + eps ** 2 * tn ** 2)
    s21 = 1.0 / np.sqrt(1.0 + eps ** 2 * tn ** 2)
    return {"omega": [round(float(v), 9) for v in w],
            "s11_mag": [round(float(v), 9) for v in s11],
            "s21_mag": [round(float(v), 9) for v in s21],
            "s11_db": [round(float(20 * math.log10(max(v, 1e-300))), 6)
                       for v in s11]}


@register_calculator(
    "coupling_matrix_synthesize_n2",
    "Cameron N+2 耦合矩阵综合：广义切比雪夫原型 → (N+2)×(N+2) 矩阵"
    "（口径：首/末节点为源/载，外部导纳 q=(1,1) 归一化，耦合信息在 "
    "m0i/miL；复 Entries 允许，频响与原型逐点一致）",
    (("order", "int - 阶数（≥1）"),
     ("rl_db", "float dB 带内回损纹波（>0）"),
     ("transmission_zeros", "array 归一化低通传输零点 |Ω|>1 列表"
      "（±ω 成对口径，缺省=全极点）")),
    required=("order", "rl_db"),
)
def coupling_matrix_synthesize_n2(order: int, rl_db: float,
                                  transmission_zeros: list | None = None
                                  ) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    tz = tuple(float(z) for z in (transmission_zeros or []))
    proto = _gcheb_prototype(order, rl_db, tz)
    mt = _cm_transversal_exact(order, proto)
    err = _cm_poly_max_err(mt, proto)
    resid = err
    method = "cameron_residue"
    if err > 1e-8:  # 数值病态兜底（高阶多项式条件数）：LM 幅频精化
        # 采样点数须 ≥ 3·order 才使残差数 2n ≥ 未知数 6·order（否则 LM 直接抛
        # ValueError，见 c13-inc2 N=15）；order≤13 时与旧网格逐位一致。
        n_pts = min(max(41, 3 * order + 2), 8 * order + 9)
        wgrid = np.linspace(-0.99, 0.99, n_pts)
        mt, res = _cm_polish(order, proto, mt, wgrid)
        resid = float(np.max(np.abs(res.fun)))
        err = _cm_poly_max_err(mt, proto)
        method = "cameron_residue+lm"

    return {"ok": bool(err < 5e-5), "order": order,
            "rl_db": rl_db,
            "transmission_zeros": [round(z, 9) for z in tz],
            "epsilon": round(proto["eps"], 9),
            "external_q": [1.0, 1.0],
            "coupling_matrix": _cm_to_list(mt),
            "matrix_shape": [order + 2, order + 2],
            "method": method,
            "fit_residual": round(resid, 12),
            "response_max_err": round(err, 12),
            "note": "矩阵元素为 [re, im] 对（行优先）；频响经 "
                    "coupling_matrix_response 还原"}


@register_calculator(
    "coupling_matrix_arrow",
    "耦合矩阵拓扑约简（arrow）：N+2 全矩阵 → 三对角线+载端星形"
    "（复正交合同旋转 RMRᵀ，频响与原矩阵逐点一致）",
    (("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),),
    required=("matrix",),
)
def coupling_matrix_arrow(matrix: list) -> dict:
    m = _cm_from_list(matrix)
    marr = _cm_reduce_arrow(m)
    return {"ok": True, "coupling_matrix": _cm_to_list(marr),
            "matrix_shape": list(marr.shape),
            "note": "元素为 [re, im] 对（行优先）"}


@register_calculator(
    "coupling_matrix_folded",
    "耦合矩阵拓扑约简（folded）：N+2 横向矩阵 → 主线+交叉耦合（经典 "
    "palindromic 合同旋转序列，频响与原矩阵逐点一致；交叉耦合族自适应："
    "anti=i+j=N+1（偶 N）/ shifted=i+j=N+2（奇 N 偶数 TZ）；非横向输入"
    "的残留如实见 pattern_residual）。边界注记：复系数（真·非对称 TZ）"
    "输入不保证单族 folded 清洁——实测仅单侧 TZ 的偶 N（N3[2.0]）与奇 N"
    "全规范（N2[1.5]）落单族（anti/shifted，残差 0），其余非对称输入"
    "（N3[1.5,-2.0]/N4[1.2,2.5]/N5[1.5,2.5]）pattern_residual 0.2~0.8、"
    "family=mixed 如实返回（频响不变性不受影响）；复系数 folded 拓扑"
    "增量不在本内核（方案 §10.18-§10.23 冻结，TODO 另立增量）",
    (("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),
     ("sign_mode", "str - 符号归一口径：mainline_positive（默认，主线全正，"
      "S21 相位可能对输入翻 180°）| preserve_s21_phase（只翻谐振器节点，"
      "S21 相位与输入同相，末端 m_{N,L} 允许为负）")),
    required=("matrix",),
)
def coupling_matrix_folded(matrix: list, sign_mode: str = "mainline_positive"
                           ) -> dict:
    m = _cm_from_list(matrix)
    if sign_mode not in ("mainline_positive", "preserve_s21_phase"):
        raise ValueError("sign_mode 须为 mainline_positive|preserve_s21_phase")
    preserve = (sign_mode == "preserve_s21_phase")
    mfd, bad = _cm_reduce_folded(m, preserve_s21_phase=preserve)
    return {"ok": len(bad) == 0, "coupling_matrix": _cm_to_list(mfd),
            "matrix_shape": list(mfd.shape),
            "cross_family": _cm_folded_family(mfd),
            "sign_mode": sign_mode,
            "s21_phase_flipped_vs_input": _cm_s21_phase_flipped(m, mfd),
            "pattern_residual": round(max((v for _, _, v in bad),
                                          default=0.0), 12),
            "pattern_violations": [[i, j, round(v, 12)] for i, j, v in bad],
            "note": "元素为 [re, im] 对（行优先）；符号归一规则：源节点不翻"
                    "（S11/S22 严格不变），mainline_positive 把主线含 m_{N,L}"
                    " 全归正（S21 相位可能翻 180°），preserve_s21_phase 只翻"
                    "谐振器节点（S21 相位保持）"}


def _cm_from_list(matrix):
    arr = np.array(matrix, dtype=float)
    if arr.ndim == 3 and arr.shape[-1] == 2:
        return arr[..., 0] + 1j * arr[..., 1]
    if arr.ndim == 2:
        return arr.astype(complex)
    raise ValueError("matrix 须为 (N+2)×(N+2) 实矩阵或 [re, im] 对嵌套列表")


def _cm_to_list(m):
    # 12 位：9 位会把 folded 约简后 ~5e−10 的浮点噪声钉成 1e−9 假残留
    return [[[round(v.real, 12), round(v.imag, 12)] for v in row] for row in m]


@register_calculator(
    "coupling_matrix_response",
    "耦合矩阵理想频响（fake 裁判闭式）：给定 (N+2) 矩阵+频率轴，"
    "低通→带通映射 Ω=(f/f0−f0/f)/fbw，返回 S11/S21（复数+dB）",
    (("freq_ghz", "array GHz 频率轴"),
     ("f0_ghz", "float GHz 中心频率"),
     ("fbw", "float - 相对带宽（0<fbw≤1）"),
     ("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),
     ("external_q", "array [q_in, q_out] 归一化外部导纳（本项目=1,1）"),
     ("z_ref", "float Ω 参考阻抗（默认 50，仅标注用）")),
    required=("freq_ghz", "f0_ghz", "fbw", "matrix"),
)
def coupling_matrix_response(freq_ghz: list, f0_ghz: float, fbw: float,
                             matrix: list, external_q: list | None = None,
                             z_ref: float = 50.0) -> dict:
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    f = np.asarray(freq_ghz, dtype=float)
    if f.size == 0 or np.any(f <= 0):
        raise ValueError("freq_ghz 须为正频率")
    m = _cm_from_list(matrix)
    qe = [1.0, 1.0] if external_q is None else [float(v) for v in external_q]
    if len(qe) != 2 or qe[0] <= 0 or qe[1] <= 0:
        raise ValueError("external_q 须为正的 [q_in, q_out]")
    omega = (f / f0_ghz - f0_ghz / f) / fbw
    s_list = []
    for om in omega:
        s11, s21 = _cm_response_raw(m, qe[0], qe[1], om)
        s_list.append((s11, s21))
    s_cube = np.zeros((f.size, 2, 2), dtype=complex)
    for i, (s11, s21) in enumerate(s_list):
        s_cube[i, 0, 0] = s11
        s_cube[i, 1, 0] = s21
        s_cube[i, 0, 1] = s21
        s_cube[i, 1, 1] = s11

    def c3(a):
        # a: (nfreq, 2, 2) 复 ndarray → [freq][row][col] = [re, im]
        return [[[[round(float(v.real), 9), round(float(v.imag), 9)]
                  for v in row] for row in mat] for mat in a]

    return {"ok": True, "freq_ghz": [round(float(v), 9) for v in f],
            "omega_norm": [round(float(v), 9) for v in omega],
            "z_ref": z_ref, "f0_ghz": f0_ghz, "fbw": fbw,
            "s_matrix": c3(s_cube),
            "s11_db": [round(float(20 * math.log10(max(abs(s11), 1e-300))),
                             6) for s11, _ in s_list],
            "s21_db": [round(float(20 * math.log10(max(abs(s21), 1e-300))),
                             6) for _, s21 in s_list],
            "note": "s_matrix 为 (nfreq,2,2)，元素 [re, im] 对；"
                    "S22=S11/S12=S21 为对称口径"}


# ─── C13 inc2：显式 TZ 集合原型 + EM 响应反提（2026-09-12）────────────────────
# 口径（Cameron 书 §6；#118 独立裁判 = 同参数的对称老路径 + 乘积形式直接求值）：
#   * 广义切比雪夫滤波函数对显式 TZ 集合（每个 ±Ω_k 单独列出）用乘积形式
#       C_N(Ω) = (1/2)[ Π_k (X_k+√(X_k²−1)) + 1/Π_k(…) ],
#       X_k(Ω) = Ω·√(κ_k²−1)/√(κ_k²−Ω²),  κ_k² = −z_k²（z_k 为 s 平面 TZ）；
#       无穷远 TZ 记 X=Ω。z=jΩ_k（|Ω_k|>1）给实频陷波。当 ±Ω_k 都列出时
#       X 相同 ⇒ Π 出现 Y_k²，与老路径「±对」口径逐位一致（单测钉住）。
#   * 实系数原型要求 TZ 集合对 s→s̄（Ω→−Ω）闭合。共轭闭合集合走实系数
#     路径；**非闭合集合（真·非成对 ±Ω）自 C13 inc3 起支持**：P(s) 复
#     系数，E 由推广 Feldtkeller H(s)=F·F†(−s)+P·P†(−s)/ε² 的复 Hurwitz
#     谱分解给出（_gcheb_prototype_explicit complex 分支，轴上幺正性
#     |S11|²+|S21|²=1 精确、单测钉住）。复系数原型响应 Ω→−Ω 不再对称
#     （非对称口径本体），且可继续综合为复对称 N+2 横向矩阵——Cameron
#     1999 §III-A 的 complex-even/complex-odd 实化即既有 D/Nu「取实部/
#     取 j×虚部」拆分（jω 轴 TZ 下 F 全实、P 低次幂交替纯虚、E 同构，
#     拆分后 D/Nu 皆实），实测 N=2..6 |S| 与原型一致 ≤1.3e−13（单测）。
#   * 原型 F/P/E：P(s)=Π(s−jΩ_k)，F(s)=κ·Π(s−j·rz)（κ 实，使 |C(1)|=1），
#     E 取 H(s)=F(s)F(−s)+P(s)P(−s)/ε² 的 Hurwitz 谱因子（s 域谱分解，与
#     老路径的 Ω² 偶多项式口径是两条独立代码路径；对称输入下 ≤1e−9 一致）。
#   * EM 反提（coupling_matrix_extract）：Cauchy 线性化有理拟合
#     S11=F/E、S21=P/E（实系数 + 公共分母 E，尺度归一化改善条件数）→ 相位
#     去旋转（吸收 j 规则）→ 符号四选一按「矩阵频响 vs 数据」判定 →
#     Cameron Y 留数法（_cm_transversal_exact）重建 N+2 矩阵。f0 由拟合残差
#     一维精化（可辨识）；**fbw 由 S 参数形状不可辨识**（任何 fbw 缩放均可被
#     有理函数吸收），故无输入时按纹波带边（|S11|=纹波电平的外沿交点）估计。

def _tz_explicit_check(order, tz_omega):
    """显式 TZ 列表校验：有限值、|Ω|>1、个数 ≤ 阶数。

    Ω→−Ω 共轭闭合**不再强制**：非闭合集合（真·非成对 ±Ω）返回
    closed=False，由 _gcheb_prototype_explicit 走复系数谱分解路径。
    返回 (tz, closed)。
    """
    order = int(order)
    tz = [float(z) for z in tz_omega]
    if any((not math.isfinite(z)) or abs(z) <= 1.0 for z in tz):
        raise ValueError("有限传输零点须为有限值且满足 |Ω|>1（带外）")
    if len(tz) > order:
        raise ValueError(f"有限 TZ 个数 {len(tz)} 超出阶数 {order}")
    closed = all(any(abs(-z - y) <= 1e-9 for y in tz) for z in tz)
    return tz, closed


def _gcheb_x_factor(z_splane, w):
    """X_k(Ω)：z 为 s 平面 TZ；X=Ω√(κ²−1)/√(κ²−Ω²)，κ²=−z²（共轭安全分支）。"""
    w = np.asarray(w, dtype=complex)
    s2 = -complex(z_splane) ** 2
    num = np.lib.scimath.sqrt(np.asarray(s2 - 1.0, dtype=complex))
    den = np.lib.scimath.sqrt(s2 - w * w)
    return w * num / den


def _gcheb_fn_explicit(tz_omega, n_inf, w):
    """显式 TZ 集合的广义切比雪夫滤波函数 C_N(Ω)（复主值分支）。"""
    w = np.asarray(w, dtype=complex)
    prod = np.ones_like(w)
    for z in tz_omega:
        x = _gcheb_x_factor(1j * float(z), w)
        prod = prod * (x + np.lib.scimath.sqrt(x * x - 1.0))
    for _ in range(int(n_inf)):
        x = w
        prod = prod * (x + np.lib.scimath.sqrt(x * x - 1.0))
    return 0.5 * (prod + 1.0 / prod)


def _gcheb_reflection_zeros_explicit(tz_omega, n_inf, n_grid=4001):
    """C_N 在 (−1,1) 内的 N 个零点（单调扫频 + 对分，#118 不赌收敛）。"""
    wgrid = np.linspace(-1.0 + 1e-12, 1.0 - 1e-12, n_grid)
    fn = np.real(_gcheb_fn_explicit(tz_omega, n_inf, wgrid))
    idx = np.where(np.diff(np.sign(fn)) != 0)[0]
    order = len(tz_omega) + int(n_inf)
    if len(idx) != order:
        raise ValueError(f"反射零点数 {len(idx)} != 阶数 {order}")
    roots = []
    for i in idx:
        a, b, fa = wgrid[i], wgrid[i + 1], fn[i]
        for _ in range(80):
            m = 0.5 * (a + b)
            fm = float(np.real(
                _gcheb_fn_explicit(tz_omega, n_inf, np.array([m]))[0]))
            if fm == 0.0:
                a = b = m
                break
            if np.sign(fm) == np.sign(fa):
                a, fa = m, fm
            else:
                b = m
        roots.append(0.5 * (a + b))
    return np.array(sorted(roots))


def _gcheb_prototype_explicit(order, rl_db, tz_omega):
    """显式 TZ 集合 → (ε, rz, F/P/E)：共轭闭合走实系数 s 域谱分解
    （独立于老路径），非闭合走复系数谱分解（真·非对称口径）。

    复系数路径（tz 不对 Ω→−Ω 闭合时）：Feldtkeller 多项式推广为
    H(s) = F(s)·F†(−s) + P(s)·P†(−s)/ε²，其中 F†(−s) = 系数共轭 ×
    (−s) 次幂符号（实系数时退化为 F(−s)）；E 取 H 的 Hurwitz 半边
    （Re(s)<0 的根）× 复尺度 c（|c|²(−1)^N = H 首项 ⟹ 轴上幺正性
    |S11|²+|S21|²=1 精确成立；相位 gauge 取 arg f_N，实系数时退化为
    正实尺度）。反射零点提取不受影响：jΩ 轴 TZ（|Ω_k|>1）给实 κ_k，
    滤波函数 C_N(Ω) 在 (−1,1) 内仍实值。响应 |S21(Ω)| 不再 Ω→−Ω 对称
    ——这正是非对称口径。复系数原型可继续综合为复对称横向矩阵
    （complex-even/odd 实化构造，见 _cm_transversal_exact，Cameron 1999
    §III-A 口径，实测 N=2..6 |S| 一致 ≤1.3e−13）。
    """
    order = int(order)
    tz, closed = _tz_explicit_check(order, tz_omega)
    n_inf = order - len(tz)
    eps = 1.0 / math.sqrt(10.0 ** (rl_db / 10.0) - 1.0)
    rz = _gcheb_reflection_zeros_explicit(tz, n_inf)
    f0 = np.atleast_1d(np.poly(1j * rz))            # Π(s−j·rz)，未归一
    p_s = np.atleast_1d(np.poly([1j * z for z in tz]))  # P(s)=Π(s−jΩ_k)
    k = abs(np.polyval(p_s, 1j) / np.polyval(f0, 1j))   # C(1)=±1 ⇒ |F(1)|=|P(1)|
    f_s = k * f0
    fm = np.array([np.conj(c) * (-1.0) ** (len(f_s) - 1 - i)
                   for i, c in enumerate(f_s)])
    pm = np.array([np.conj(c) * (-1.0) ** (len(p_s) - 1 - i)
                   for i, c in enumerate(p_s)])
    h = np.polyadd(np.polymul(f_s, fm), np.polymul(p_s, pm) / eps ** 2)
    hmax = float(np.max(np.abs(h))) if h.size else 0.0
    if closed:
        if np.max(np.abs(h.imag)) > 1e-8 * max(hmax, 1.0):
            raise ValueError("谱多项式非实系数：TZ 集合未共轭闭合")
        h = np.trim_zeros(np.real(h), "f")
        deg = len(h) - 1
        g = np.array([c for i, c in enumerate(h) if (deg - i) % 2 == 0])
        roots = []
        for y in np.roots(g):
            s = np.lib.scimath.sqrt(complex(y))
            if s.real > 0 or (s.real == 0 and s.imag < 0):
                s = -s
            roots.append(s)
        e0 = np.poly(roots)
        j = 1j
        ee = np.polyval(e0, j) * np.polyval(e0, -j)
        hv = (np.polyval(f_s, j) * np.polyval(f_s, -j)
              + np.polyval(p_s, j) * np.polyval(p_s, -j) / eps ** 2)
        e_s = e0 * np.sqrt(complex(hv / ee))
        if np.max(np.abs(e_s.imag)) < 1e-9:
            e_s = np.real(e_s)
    else:
        n_deg = len(f_s) - 1
        lead = h[0] * (-1.0) ** n_deg        # |c|²(−1)^N·(−1)^N = h[0]
        if abs(lead.imag) > 1e-7 * max(abs(lead), 1.0):
            raise ValueError(f"谱多项式首项非实正（{lead}）：数值病态")
        roots_h = np.roots(h)
        hurwitz = [r for r in roots_h if r.real < 0.0]
        if len(hurwitz) != n_deg:
            n_axis = sum(1 for r in roots_h if abs(r.real) <= 1e-8)
            raise ValueError(
                f"复系数谱分解失败：Hurwitz 半边根 {len(hurwitz)} != "
                f"阶数 {n_deg}（jω 轴根 {n_axis} 个）")
        e0 = np.poly(hurwitz)
        c_abs = math.sqrt(lead.real)
        e_s = e0 * (c_abs * np.exp(1j * np.angle(f_s[0])))
    return {"eps": eps, "rz": rz, "f_s": f_s, "p_s": p_s, "e_s": e_s,
            "tz_omega": tz, "tz_conjugate_closed": closed,
            "coefficient_domain": "real" if closed else "complex"}


@register_calculator(
    "chebyshev_prototype_asym",
    "广义切比雪夫原型（显式 TZ 集合口径）：阶数+回损+完整 TZ 列表（每个 Ω "
    "单独列出）→ F/P/E 多项式与反射零点。±Ω 共轭闭合输入走实系数 s 域谱"
    "分解（与 chebyshev_prototype 数值一致 ≤1e−9）；非闭合（真·非对称）"
    "输入走复系数谱分解（推广 Feldtkeller 的 Hurwitz 半边），轴上幺正性"
    "保持、响应 Ω→−Ω 不再对称；可继续综合为复对称 N+2 耦合矩阵（见 "
    "coupling_matrix_synthesize_explicit）",
    (("order", "int - 滤波器阶数（≥1）"),
     ("rl_db", "float dB 带内回波损耗纹波（>0）"),
     ("transmission_zeros", "array 显式 TZ 列表（每项一个 Ω；成对输入=实系数"
      "路径，非成对输入=复系数路径）")),
    required=("order", "rl_db", "transmission_zeros"),
)
def chebyshev_prototype_asym(order: int, rl_db: float,
                             transmission_zeros: list) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    proto = _gcheb_prototype_explicit(order, rl_db, transmission_zeros)

    def cplx(p):
        return [[round(v.real, 9), round(v.imag, 9)] for v in p]

    return {"ok": True, "order": order, "rl_db": rl_db,
            "epsilon": round(proto["eps"], 9),
            "reflection_zeros": [round(r, 9) for r in proto["rz"]],
            "transmission_zeros": [round(z, 9) for z in proto["tz_omega"]],
            "tz_conjugate_closed": proto["tz_conjugate_closed"],
            "coefficient_domain": proto["coefficient_domain"],
            "f_s": cplx(proto["f_s"]), "p_s": cplx(proto["p_s"]),
            "e_s": cplx(proto["e_s"]),
            "note": "F/P/E 为 s 域多项式系数（降幂）；S11=F/E、S21=P/(εE)。"
                    "复系数路径（coefficient_domain=complex）的响应 Ω→−Ω "
                    "不对称；N+2 综合走 coupling_matrix_synthesize_explicit"}


@register_calculator(
    "coupling_matrix_synthesize_explicit",
    "C13 显式 TZ 集合综合（Cameron N+2）：完整 TZ 列表（每个 Ω 单独列出；"
    "±Ω 成对=实系数原型，与 coupling_matrix_synthesize_n2 同口径；非成对"
    "=复系数原型，响应 Ω→−Ω 不对称）→ (N+2)×(N+2) 横向矩阵，频响与原型"
    "逐点一致（幅度；复系数路径实测 ≤1.3e−13）。复元矩阵为复对称 M=Mᵀ，"
    "非对称网络 |m_0k| 与 |m_kL| 允许不等",
    (("order", "int - 阶数（≥1）"),
     ("rl_db", "float dB 带内回损纹波（>0）"),
     ("transmission_zeros", "array 显式 TZ 列表（每项一个 Ω，|Ω|>1，"
      "个数 ≤ 阶数）")),
    required=("order", "rl_db", "transmission_zeros"),
)
def coupling_matrix_synthesize_explicit(order: int, rl_db: float,
                                        transmission_zeros: list) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    proto = _gcheb_prototype_explicit(order, rl_db, transmission_zeros)
    mt = _cm_transversal_exact(order, proto)
    err = _cm_poly_max_err(mt, proto)
    resid = err
    method = "cameron_residue"
    if err > 1e-8:  # 数值病态兜底（高阶多项式条件数）：LM 幅频精化
        n_pts = min(max(41, 3 * order + 2), 8 * order + 9)
        wgrid = np.linspace(-0.99, 0.99, n_pts)
        mt, res = _cm_polish(order, proto, mt, wgrid)
        resid = float(np.max(np.abs(res.fun)))
        err = _cm_poly_max_err(mt, proto)
        method = "cameron_residue+lm"
    return {"ok": bool(err < 5e-5), "order": order, "rl_db": rl_db,
            "transmission_zeros": [round(z, 9) for z in proto["tz_omega"]],
            "tz_conjugate_closed": proto["tz_conjugate_closed"],
            "coefficient_domain": proto["coefficient_domain"],
            "epsilon": round(proto["eps"], 9),
            "external_q": [1.0, 1.0],
            "coupling_matrix": _cm_to_list(mt),
            "matrix_shape": [order + 2, order + 2],
            "method": method,
            "fit_residual": round(resid, 12),
            "response_max_err": round(err, 12),
            "note": "矩阵元素为 [re, im] 对（行优先）；q=(1,1) 归一化；"
                    "频响经 coupling_matrix_response 还原（幅度）；"
                    "复系数路径的非对称网络 m_0k/m_kL 无镜像关系"}
