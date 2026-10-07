"""C13 EM/电路响应反提链（Cauchy 拟合→Cameron Y 留数 N+2 矩阵；含 |S|² 幅值域反提）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

import numpy as np

from .cm_core import _cm_reduce_arrow, _cm_response_raw, _cm_to_list, _cm_transversal_exact
from .registry import register_calculator

# ─── EM 响应反提（Cauchy 有理拟合 → Cameron Y 留数 N+2 矩阵）─────────────────

def _cm_as_complex(seq, name, n_expected):
    arr = np.asarray(seq)
    if arr.ndim == 2 and arr.shape[-1] == 2:
        out = arr.astype(float)
        out = out[..., 0] + 1j * out[..., 1]
    elif np.iscomplexobj(arr):
        out = arr.astype(complex)
    else:
        out = np.asarray(seq, dtype=float).astype(complex)
    if out.ndim != 1:
        raise ValueError(f"{name} 须为一维序列（[re,im] 对或复数）")
    if len(out) != n_expected:
        raise ValueError(f"{name} 长度 {len(out)} != 频率点数 {n_expected}")
    return out


def _cm_rational_fit(omega, s11, s21, order, nz):
    """线性化有理拟合 S11≈F/E、S21≈P/E（实系数 + 公共分母 E，E 首一）。

    条件数改善：以 u=s/max|s| 为基底拟合后再精确换回 s 域（对角缩放）。
    返回 (f_s, p_s, e_s) s 域降幂系数数组。
    """
    s = 1j * np.asarray(omega, dtype=complex)
    scale = max(float(np.max(np.abs(s))), 1e-30)
    u = s / scale
    n_f, n_p, n_e = order + 1, nz + 1, order
    nu = n_f + n_p + n_e
    m = len(s)
    a = np.zeros((2 * m, nu), dtype=complex)
    b = np.zeros(2 * m, dtype=complex)
    for i in range(m):
        ui = u[i]
        rowf = ui ** np.arange(order, -1, -1)
        rowp = ui ** np.arange(nz, -1, -1)
        rowe = ui ** np.arange(order - 1, -1, -1)
        a[2 * i, 0:n_f] = rowf
        a[2 * i, n_f + n_p:] = -s11[i] * rowe
        b[2 * i] = s11[i] * ui ** order
        a[2 * i + 1, n_f:n_f + n_p] = rowp
        a[2 * i + 1, n_f + n_p:] = -s21[i] * rowe
        b[2 * i + 1] = s21[i] * ui ** order
    x, *_ = np.linalg.lstsq(a, b, rcond=None)

    def to_s(c):
        d = len(c) - 1
        return np.array([c[k] / scale ** (d - k) for k in range(d + 1)],
                        dtype=complex)

    e_s = np.concatenate([[1.0], x[n_f + n_p:]])
    return to_s(x[:n_f]), to_s(x[n_f:n_f + n_p]), to_s(e_s)


def _cm_fit_rms(f_s, p_s, e_s, omega, s11, s21):
    s = 1j * np.asarray(omega, dtype=complex)
    e = np.polyval(e_s, s)
    e = np.where(np.abs(e) < 1e-300, 1e-300 + 0j, e)
    r11 = np.polyval(f_s, s) / e - s11
    r21 = np.polyval(p_s, s) / e - s21
    return float(np.sqrt(np.mean(np.abs(r11) ** 2 + np.abs(r21) ** 2)))


def _cm_derotate(v):
    """去旋转：找 θ 使 e^{−jθ}v 的虚部最小（⇒ 实系数多项式），返回 (实向量, θ)。"""
    re, im = v.real, v.imag
    aa = float(np.sum(re ** 2 - im ** 2))
    bb = float(np.sum(re * im))
    if abs(aa) < 1e-300 and abs(bb) < 1e-300:
        return v.real.copy(), 0.0
    th = 0.5 * math.atan2(2.0 * bb, aa)
    w = v * np.exp(-1j * th)
    if w[0].real < 0:
        w = -w
    return w.real.copy(), th


def _cm_derotation_residual(v):
    """归一化去旋转残差 ‖Im(e^{−jθ}v)‖/‖v‖（θ 取虚部能量最小旋转）。

    实系数数据与 jΩ 轴 TZ 集的 F 实测 ≤1e−8（复原型 5 例 4.3e−10…9.2e−9）；
    真·复系数（非对称 TZ）P 为 O(0.15–0.7)——以 1e−6 为界分流 extract 的
    实/复路径（实测见 test_coupling_matrix 复往返用例）。
    """
    v = np.asarray(v, dtype=complex)
    nrm = float(np.linalg.norm(v))
    if nrm == 0.0:
        return 0.0
    _, th = _cm_derotate(v)
    return float(np.linalg.norm((v * np.exp(-1j * th)).imag) / nrm)


def _cm_band_edges(freq, s11_db, tol_db=0.05):
    """纹波带边：|S11| 与纹波电平的（外沿）交点，抛物线插值定位。

    返回 (f_lo, f_hi)；识别不到返回 None。
    """
    freq = np.asarray(freq, dtype=float)
    y = np.asarray(s11_db, dtype=float)
    n = len(freq)
    peaks = [i for i in range(1, n - 1) if y[i] >= y[i - 1] and y[i] > y[i + 1]]
    if len(peaks) < 2:
        return None
    # 纹波电平：以「深零点（反射零点）」围出的带内区间为准——最深谷之间
    # 的最高点即纹波峰（对 rl_db 很小/噪声格点稳健，避免被极低伪峰带偏）。
    top = max(y[i] for i in peaks)
    mins = [i for i in range(1, n - 1) if y[i] <= y[i - 1] and y[i] < y[i + 1]]
    deep = [i for i in mins if y[i] < top - 2.0]
    if len(deep) >= 1:
        i0, i1 = min(deep), max(deep)
        lvl = float(np.max(y[i0:i1 + 1]))
        starts = (i0, i1)
    else:
        lvl = min(y[i] for i in peaks)
        starts = (int(np.argmin(y)), int(np.argmin(y)))

    def edge(direction):
        i = starts[0] if direction < 0 else starts[1]
        while 0 <= i + direction < n and y[i + direction] <= lvl + tol_db:
            i += direction
        j = i + direction
        if not (0 <= i < n and 0 <= j < n):
            return None
        xs = ([freq[i - 1], freq[i], freq[j]] if direction > 0
              else [freq[j], freq[i], freq[i + 1]])
        if len(xs) != 3 or min(xs) == max(xs):
            return None
        ys = ([y[i - 1], y[i], y[j]] if direction > 0
              else [y[j], y[i], y[i + 1]])
        coef = np.polyfit(xs, ys, 2)
        rr = [r.real for r in np.roots(coef - np.array([0.0, 0.0, lvl]))
              if abs(r.imag) < 1e-9 and min(xs) <= r.real <= max(xs)]
        return float(rr[0]) if rr else float(freq[i])

    lo, hi = edge(-1), edge(1)
    if lo is None or hi is None or not (0 < lo < hi):
        return None
    return lo, hi


def _cm_refine_f0(freq, s11, s21, order, nz, f0_lo, f0_hi, fbw,
                  rounds=26, n_scan=11):
    """f0 一维精化：有理拟合残差在真 f0 处→0（f0 可辨识，fbw 尺度不可辨识）。

    多轮栅格收窄（#118：不赌单轮收敛），末轮步长 ~ (0.04)^rounds 带宽。
    """

    def residual(f0):
        try:
            om = (freq / f0 - f0 / freq) / fbw
            f_s, p_s, e_s = _cm_rational_fit(om, s11, s21, order, nz)
            return _cm_fit_rms(f_s, p_s, e_s, om, s11, s21)
        except (ValueError, np.linalg.LinAlgError):
            return float("inf")

    lo, hi = float(f0_lo), float(f0_hi)
    mid = 0.5 * (lo + hi)
    for _ in range(rounds):
        grid = np.linspace(lo, hi, n_scan)
        scored = [(residual(float(g)), float(g)) for g in grid]
        r, mid = min(scored, key=lambda t: t[0])
        half = (hi - lo) * 0.25
        lo, hi = mid - half, mid + half
        if not (np.isfinite(r) and half > 0):
            break
    return mid


def _cm_refine_ref_delay(freq, s11, s21, f0, fbw, order, nz, tau_hi_s,
                         rounds=20, n_scan=11):
    """参考面时延 τ̂ 一维精化（C13 followUp ③，仿 _cm_refine_f0）。

    目标 = 有理拟合残差最小：对候选 τ 做 S11×e^{+j2πf·2τ}、
    S21×e^{+j2πf·2τ}（对称参考面，tau_in=tau_out=τ）后拟合。
    多轮栅格收窄（#118：不赌单轮收敛），末轮步长 ~(0.25)^rounds·τ_hi。
    τ_hi 缺省建议 1/f0（一个周期，物理时延上限量级）。
    """
    from rfauto.core.deembed import deembed_reference_delay

    freq = np.asarray(freq, dtype=float)
    f_hz = freq * 1e9
    om = (freq / f0 - f0 / freq) / fbw

    def residual(tau):
        try:
            s11c, s21c = deembed_reference_delay(f_hz, s11, s21, tau, tau)
            f_s, p_s, e_s = _cm_rational_fit(om, s11c, s21c, order, nz)
            return _cm_fit_rms(f_s, p_s, e_s, om, s11c, s21c)
        except (ValueError, np.linalg.LinAlgError):
            return float("inf")

    lo, hi = 0.0, float(tau_hi_s)
    mid = 0.5 * (lo + hi)
    for _ in range(rounds):
        grid = np.linspace(lo, hi, n_scan)
        scored = [(residual(float(g)), float(g)) for g in grid]
        r, mid = min(scored, key=lambda t: t[0])
        half = (hi - lo) * 0.25
        lo, hi = mid - half, mid + half
        if not (np.isfinite(r) and half > 0):
            break
    return float(mid)


# ─── |S|² 幅值域反提（C13 followUp ③ 候选 b，2026-09-15）─────────────────────
# 口径：|S11(Ω)|² = F(jΩ)F(−jΩ) / E(jΩ)E(−jΩ) 是 x=Ω² 的实有理函数
#   （实系数 ⟹ conj F(jΩ)=F(−jΩ)），对相位污染数据天然免疫（只吃幅值）。
#   线性化：A(x) − |S11|²·B(x) = |S11|²·x^N（B 首一）+ S21² 同 B 共享，
#   行均衡化 lstsq（Vandermonde 动态范围 3+ 量级，否则 A 的二重根分辨不动）。
#   谱分解：G(s)=A(−s²)=F(s)F(−s)；E 取 G_B 的 Re(s)<0 半（Hurwitz，
#   ± 配对）；F/P 的根在 jΩ 轴 ⟹ G 的每根二重（实系数 F 的根 ±jω 成共轭
#   对 ⟹ F(s)F(−s)=(−1)^N F(s)² 完全平方），按 (Im,Re) 排序后相邻聚对取
#   中点。尺度：F=√(a_N/b_N)·F_m、P=√(c_nz/b_N)·P_m、E=E_m（首一）。
# 诚实边界（精度损失）：①幅值只定 |F|/|E| 的模，F 全局符号与 P 全局符号
#   不可辨识（下游符号枚举按 |S| 裁决）；②单侧 TZ 的 ±Ω 符号不可辨识
#   （|S21| 对 Ω→−Ω 对称），transmission_zeros_cplx 报 ± 对；③f0 精化
#   （复域可辨识性）不在幅值路径——f0/fbw 建议显式给定，缺省带边估计。

def _x_to_s_even(coef_x_asc):
    """A(x) 升幂系数（x=Ω²）→ G(s)=A(−s²) 降幂系数（偶次实多项式）。"""
    deg = len(coef_x_asc) - 1
    g = np.zeros(2 * deg + 1)
    for k, ak in enumerate(coef_x_asc):
        g[2 * (deg - k)] = ak * (-1.0) ** k
    return g


def _cm_spectral_factor(coef_x_asc, n, kind):
    """A(s)A(−s)=A(−s²) 型偶多项式的谱因子（首一 V(s)，n 次）。

    kind="hurwitz"（E）：根成 {s0,−s0} 对，取 Re<0 支；
    kind="axis"（F/P）：根在 jΩ 轴且每根二重（实系数 ⟹ 完全平方），
    按 (Im,Re) 排序后相邻聚对取中点（扰动 ≪ 根间距）。
    """
    rts = np.roots(_x_to_s_even(coef_x_asc))
    if len(rts) != 2 * n:
        raise ValueError(f"谱多项式根数 {len(rts)} != {2 * n}")
    pool = list(rts)
    picked = []
    if kind == "hurwitz":
        scale = max(1.0, float(np.max(np.abs(rts))))
        while pool:
            r = pool.pop(0)
            if not pool:
                raise ValueError("Hurwitz 谱分解根配对落单")
            j = min(range(len(pool)), key=lambda q: abs(pool[q] + r))
            twin = pool.pop(j)
            if abs(twin + r) > 1e-4 * scale:
                raise ValueError("谱分解根未成 ± 对（数据非无耗一致）")
            picked.append(r if r.real < twin.real else twin)
    else:
        ordered = sorted(rts, key=lambda z: (round(z.imag, 9),
                                             round(z.real, 9)))
        picked = [0.5 * (ordered[2 * k] + ordered[2 * k + 1])
                  for k in range(n)]
    v = np.poly(picked) if picked else np.array([1.0 + 0j])
    return v / v[0]


def _cm_mag2_fit(omega, mag11, mag21, order, nz):
    """|S11|、|S21| 幅值 → (F, P, E)（E 首一，ε 折入 P）+ |S| 域幅度 rms。

    确定性内核：行均衡化实数 lstsq + 谱分解（根配对口径见上方注释块）。
    数据非无耗一致（谱分解配对失败/首项非正）时抛 ValueError。
    """
    omega = np.asarray(omega, dtype=float)
    x = omega ** 2
    xs = float(np.max(x))
    if xs <= 0.0:
        raise ValueError("omega 全为 0，幅值域拟合不可分")
    xn = x / xs
    y11 = np.asarray(mag11, dtype=float) ** 2
    y21 = np.asarray(mag21, dtype=float) ** 2
    n_a, n_b, n_c = order + 1, order, nz + 1
    ntot = n_a + n_b + n_c
    m = len(xn)
    mat = np.zeros((2 * m, ntot))
    vec = np.zeros(2 * m)
    xp = np.vander(xn, order + 1, increasing=True)
    for i in range(m):
        mat[i, :n_a] = xp[i]
        mat[i, n_a:n_a + n_b] = -y11[i] * xp[i, :n_b]
        vec[i] = y11[i] * xn[i] ** order
        mat[m + i, n_a:n_a + n_b] = -y21[i] * xp[i, :n_b]
        mat[m + i, n_a + n_b:] = xp[i, :n_c]
        vec[m + i] = y21[i] * xn[i] ** order
    rn = np.max(np.abs(mat), axis=1)
    rn[rn == 0.0] = 1.0
    sol, *_ = np.linalg.lstsq(mat / rn[:, None], vec / rn, rcond=None)
    a = sol[:n_a] / (xs ** np.arange(n_a))
    b = (np.concatenate([sol[n_a:n_a + n_b], [1.0]])
         / (xs ** np.arange(n_b + 1)))
    c = sol[n_a + n_b:] / (xs ** np.arange(n_c))
    lead = float(b[-1])
    if not (lead > 0.0) or not (float(a[-1]) >= 0.0) \
            or not (float(c[-1]) >= 0.0):
        raise ValueError("幅值域拟合首项非正（数据非无耗一致响应）")
    e_s = _cm_spectral_factor(b, order, "hurwitz")
    f_s = _cm_spectral_factor(a, order, "axis") * math.sqrt(a[-1] / lead)
    if nz > 0:
        p_s = (_cm_spectral_factor(c, nz, "axis")
               * math.sqrt(c[-1] / lead))
    else:
        p_s = np.array([math.sqrt(c[-1] / lead)])
    ev = 1j * omega
    e_val = np.polyval(e_s, ev)
    r11 = np.abs(np.polyval(f_s, ev) / e_val) - np.asarray(mag11, dtype=float)
    r21 = np.abs(np.polyval(p_s, ev) / e_val) - np.asarray(mag21, dtype=float)
    rms = float(np.sqrt(np.mean(r11 ** 2 + r21 ** 2)))
    return f_s, p_s, e_s, rms


_CM_DEROT_COMPLEX_TOL = 1e-6


def _cm_extract_from_fit(order, f_s, p_s, e_s, omega, s11, s21,
                         phase_ref="unknown"):
    """由拟合多项式重建 N+2 矩阵：实/复路径分流 + 符号枚举。

    路径分流（C13 followUp ②，2026-09-15）：旧实现无条件 _cm_derotate
    实化 F/P——对复系数（真·非对称 TZ）响应，实化直接摧毁矩阵（实测
    fit_rms=5.8e−10 但 kij 误差达 1.4~2e5、带内幺正性偏差 0.69 仍
    ok=True 的假绿，#122）。现按归一化去旋转残差分流：
    - max(δ_F, δ_P) < _CM_DEROT_COMPLEX_TOL（实系数数据，实测 ~1e−12）：
      既有实路径（实化 + 符号四选一，裁判 (|S| 逐点, 复值误差) 字典序）；
    - 否则复路径：F/P 不实化直进 _cm_transversal_exact（inc3 已证复原型
      支持）。符号枚举裁判按 phase_ref：
      "known"（已知参考面的综合往返）= 复值逐点最大误差；
      "unknown"（EM 参考面未知）= 保留 (|S| 逐点, 复值误差) 字典序
      （|S| 相位无关；复值误差仅在同幅值符号组内做确定性决断）。
      _cm_sign_normalize 的 .real<0 归一在复路径语义不适用（复元符号
      无「正负」物理约定），故复路径跳过节点符号归一，符号仅经枚举定。

    返回 (report, 矩阵)：report = {mag_max_err, cx_max_err, derot_f,
    derot_p, path}；数据结构不满足横向矩阵口径时返回 None。
    """
    derot_f = _cm_derotation_residual(f_s)
    derot_p = _cm_derotation_residual(p_s)
    use_complex = max(derot_f, derot_p) >= _CM_DEROT_COMPLEX_TOL
    es = np.asarray(e_s, dtype=complex)
    if use_complex:
        fr = np.asarray(f_s, dtype=complex)
        pr = np.asarray(p_s, dtype=complex)
        # 规范旋转（gauge）：_cm_transversal_exact 的 D/Nu 实/虚拆分要求
        # (F,P,E) 在 canonical 族（首项系数实，见 _gcheb_prototype_explicit
        # 的 gauge c=|c|·e^{j·arg f_N} 且 f_N 实 ⟹ 三项首项皆实）。extract
        # 的 E-首一归一化引入复尺度 e_N，破坏该族——以 F 首项相位 θg =
        # arg(F[0]) 旋转全部三项（F 首项=实 k>0/e_N ⟹ θg=−arg(e_N)=0 或 π，
        # 旋转=±1 实尺度，拆分不变量成立；P 首项相位 −2·arg(e_N)≡0 同归
        # 实正）。逐例实测：无此旋转时 (N−n_fz) 偶（jP 规则）路径重建
        # 全炸（kij 误差 ~1e5）。
        g = np.exp(1j * np.angle(fr[0]))
        fr = fr * g
        pr = pr * g
        es = es * g
    else:
        fr, _ = _cm_derotate(f_s)
        pr, _ = _cm_derotate(p_s)
    best = None
    p_phases = (1.0, -1.0, 1j, -1j) if use_complex else (1.0, -1.0)
    for sf in (1.0, -1.0):
        for pp in p_phases:
            try:
                m = _cm_transversal_exact(order, {
                    "eps": 1.0, "e_s": es,
                    "f_s": (sf * fr).astype(complex),
                    "p_s": (pp * pr).astype(complex)})
            except (ValueError, np.linalg.LinAlgError):
                continue
            mag_err = 0.0
            ph_err = 0.0
            for i, w in enumerate(omega):
                c11, c21 = _cm_response_raw(m, 1.0, 1.0, w)
                mag_err = max(mag_err, abs(abs(c11) - abs(s11[i])),
                              abs(abs(c21) - abs(s21[i])))
                ph_err = max(ph_err, abs(c11 - s11[i]), abs(c21 - s21[i]))
            # 裁判：|S| 逐点（相位无关，EM 参考面未知）为主，复值误差仅作同级微调
            score = (ph_err if (use_complex and phase_ref == "known")
                     else (mag_err, ph_err))
            if best is None or score < best[0]:
                best = (score, m, mag_err, ph_err)
    if best is None:
        return None
    _, m, mag_err, ph_err = best
    return {"mag_max_err": float(mag_err), "cx_max_err": float(ph_err),
            "derot_f": float(derot_f), "derot_p": float(derot_p),
            "path": "complex" if use_complex else "real"}, m


@register_calculator(
    "coupling_matrix_extract",
    "C13 EM/电路响应反提：频轴+复 S11/S21(+阶数) → f0、FBW、外部 Q、N+2 耦合"
    "矩阵与拟合残差。Cauchy 线性化有理拟合（S11=F/E, S21=P/E）→ Cameron Y 留数"
    "重建；f0 由拟合精化，fbw 无输入时按纹波带边估计（形状不可辨识，见 note）"
    "；domain=magnitude 走 |S|² 幅值域（相位污染数据兜底，精度损失见 note）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数；magnitude 域取模）"),
     ("s21", "array 复 S21（[re,im] 对或复数；magnitude 域取模）"),
     ("order", "int 阶数（缺省=自动判阶）"),
     ("f0_ghz", "float GHz 中心频率（缺省=由拟合估计）"),
     ("fbw", "float 相对带宽（缺省=由纹波带边估计）"),
     ("phase_ref", "str complex 域符号枚举裁判：unknown（缺省，|S| 相位无关）|"
      "known（已知参考面，复值逐点）"),
     ("domain", "str complex（缺省，复 S 全信息）| magnitude（|S|² 幅值域）"),
     ("ref_delay_s", "float 对称参考面时延 τ(s)，complex 域反推后再拟合"),
     ("ref_delay_scan", "bool true=按拟合残差最小一维扫描 τ̂（仿 f0 精化）")),
    required=("freq_ghz", "s11", "s21"),
)
def coupling_matrix_extract(freq_ghz: list, s11: list, s21: list,
                            order: int | None = None,
                            f0_ghz: float | None = None,
                            fbw: float | None = None,
                            phase_ref: str = "unknown",
                            domain: str = "complex",
                            ref_delay_s: float | None = None,
                            ref_delay_scan: bool = False) -> dict:
    # ── C13 followUp ③ 根因账（2026-09-15，替代 topology_service 旧边界注记）──
    # 含馈线/λ/4 段参考面相位的电路裁判（coupled_bpf_circuit_sparams）反提
    # 不收敛（探针实测原始 rms 0.06~0.84 > 1e-2 门）。已败策略复盘：
    #   ① 相位滚转 ±：滚转是全局常数相位，而污染是
    #     f 的函数（e^{−j2πfτ} 非常数），滚不动；
    #   ② ABCD 精确逆：需已知夹具网络；裁判链的 λ/4 段是「2 导体 4 端口
    #     + 交叉口开路」复合结构，不是可分离级联件，精确逆不可得；
    #   ③ 纯时延去嵌（本函数 ref_delay_s/ref_delay_scan）：能开门
    #     （±3% 窗实测 rms 0.06→2.96e−3 ≤1e-2）但 kij 仍不可信（~1.5）
    #     ——根因链：λ/4 commensurate 网络在 Ω=(f/f0−f0/f)/fbw 域**非有理**
    #     （Richards 变量 tan(θ)≠Ω 映射），残余相位非时延型不可完全吸收；
    #     且窄带下错 τ 可被「多项式翘曲」补偿（探针实测 rms 1.3e−5 处
    #     拟合极点全飞），重建把离流形距离放大 ~10³ 倍（重建 vs 拟合
    #     2.6e−2 ≫ rms 1.3e−5）。纯时延校正不是收敛解。
    # 收敛解 = domain="magnitude"：只吃 |S|（天然免疫相位污染），|S|² 是
    # Ω² 的实有理函数，线性 Cauchy+谱分解重建。实测（±3% 窗，sync TEM
    # 裁判，名义 N=3 设计）：|S| rms 8.7e−3（过 1e-2 门）+ kij 逐元素
    # 偏差 1.95e−2；±1.5% 窗 kij 1.85e−2。色散模式（默认 εeff_e/o）
    # 裁判与理想矩阵 |S11| 带内差 ~0.16（模型差异，归 #11 裁判面），
    # 任何反提都受此地板限制——发现裁判模型问题只记录不改（任务书禁改
    # openems_templates.py）。
    if phase_ref not in ("unknown", "known"):
        raise ValueError("phase_ref 须为 unknown|known")
    if domain not in ("complex", "magnitude"):
        raise ValueError("domain 须为 complex|magnitude")
    if ref_delay_s is not None and ref_delay_scan:
        raise ValueError("ref_delay_s 与 ref_delay_scan 二选一")
    if domain == "magnitude" and (ref_delay_s is not None or ref_delay_scan):
        raise ValueError("ref_delay 只作用于 complex 域（幅值域天然无相位）")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 5:
        raise ValueError("freq_ghz 须为一维且至少 5 点")
    if np.any(freq <= 0):
        raise ValueError("freq_ghz 须为正频率")
    if np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须严格递增")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")

    if order is not None:
        order = int(order)
        if order < 1:
            raise ValueError("阶数必须 ≥1")
        n_list = [order]
    else:
        n_max = max(1, min(12, freq.size // 4))
        n_list = list(range(1, n_max + 1))

    # f0 / fbw（幅值量，两域同口径；|S| 不受参考面相位影响）
    f0_in = None if f0_ghz is None else float(f0_ghz)
    fbw_in = None if fbw is None else float(fbw)
    if fbw_in is not None and not 0 < fbw_in <= 1:
        raise ValueError("fbw 须在 (0,1]")
    s11_db = 20.0 * np.log10(np.maximum(np.abs(s11c), 1e-300))
    edges = _cm_band_edges(freq, s11_db)
    f0_est = math.sqrt(float(edges[0]) * float(edges[1])) if edges else \
        math.sqrt(float(freq[0]) * float(freq[-1]))
    fbw_est = (float(edges[1]) - float(edges[0])) / f0_est if edges else 0.1
    f0_use = f0_in if f0_in is not None else f0_est
    fbw_use = fbw_in if fbw_in is not None else min(max(fbw_est, 1e-3), 1.0)

    if domain == "complex":
        def fit_fn(om, a, b, n_ord, nz):
            f_s, p_s, e_s = _cm_rational_fit(om, a, b, n_ord, nz)
            return f_s, p_s, e_s, _cm_fit_rms(f_s, p_s, e_s, om, a, b)
    else:
        def fit_fn(om, a, b, n_ord, nz):
            return _cm_mag2_fit(om, np.abs(a), np.abs(b), n_ord, nz)

    def scan(f0, fbw_v, data):
        """给定 (f0, fbw)：逐阶扫 nz，返回每阶最优 (order, nz, rms, F,P,E, min_rms)。"""
        s11d, s21d = data
        out = []
        for n_ord in n_list:
            fits = {}
            for nz in range(0, n_ord + 1):
                try:
                    om = (freq / f0 - f0 / freq) / fbw_v
                    f_s, p_s, e_s, r = fit_fn(om, s11d, s21d, n_ord, nz)
                except (ValueError, np.linalg.LinAlgError):
                    continue
                if np.isfinite(r):
                    fits[nz] = (r, f_s, p_s, e_s)
            if not fits:
                continue
            min_r = min(v[0] for v in fits.values())
            # 零点数容差：绝对底噪 1e−6（容纳未知 f0 带来的模型误差）+
            # 相对最优 20×；否则额外 TZ 会吸收 f0 误差造成过拟合。
            tol = max(20.0 * min_r, 1e-6)
            nz_sel = min(k for k, v in fits.items() if v[0] <= tol)
            r, f_s, p_s, e_s = fits[nz_sel]
            out.append((n_ord, nz_sel, r, f_s, p_s, e_s, min_r))
        return out

    def choose(res):
        if not res:
            return None
        if order is not None:
            return res[0]
        best_r = min(t[6] for t in res)
        # 判阶容差取「绝对底噪 1e−6 + 相对最优 100×」：高阶过拟合（残差随阶数
        # 单调下降）与未知 f0 带来的模型误差都需容纳，否则会锁到过高的阶数。
        tol = max(100.0 * best_r, 1e-6)
        return next((t for t in res if t[6] <= tol), res[-1])

    data: tuple[np.ndarray, np.ndarray] = (s11c, s21c)
    ref_delay_used = None
    if domain == "complex" and (ref_delay_s is not None or ref_delay_scan):
        from rfauto.core.deembed import deembed_reference_delay

        if ref_delay_scan:
            # τ 扫描目标 (order,nz,f0,fbw) 用未去嵌数据初估（与 f0 精化同
            # 哲学：固定初选阶/零点数，只精化 τ 本身）。
            pre = choose(scan(f0_use, fbw_use, data))
            if pre is None:
                raise ValueError("有理拟合失败：数据无法用 ≤N 阶模型描述")
            tau_hi = 1.0 / (max(f0_use, 1e-9) * 1e9)
            ref_delay_used = _cm_refine_ref_delay(
                freq, s11c, s21c, f0_use, fbw_use, int(pre[0]), int(pre[1]),
                tau_hi)
        else:
            ref_delay_used = float(ref_delay_s)
        data = deembed_reference_delay(freq * 1e9, s11c, s21c,
                                       ref_delay_used, ref_delay_used)

    results = scan(f0_use, fbw_use, data)
    pick = choose(results)
    if pick is None:
        raise ValueError("有理拟合失败：数据无法用 ≤N 阶模型描述")

    # 未给 f0 时按拟合残差精化（f0 可辨识；fbw 缩放可被有理函数吸收）。
    # 仅 complex 域：幅值域的 |S|² 残差对 f0 的可辨识性未验证，不做。
    f0_source = "input" if f0_in is not None else "estimated"
    if domain == "complex" and f0_in is None and edges is not None:
        f0_ref = _cm_refine_f0(freq, data[0], data[1], pick[0], pick[1],
                               float(edges[0]), float(edges[1]), fbw_use)
        if abs(f0_ref - f0_use) > 1e-12:
            f0_use = f0_ref
            if fbw_in is None:
                fbw_use = min(max((float(edges[1]) - float(edges[0])) / f0_use,
                                  1e-3), 1.0)
            # 只在同一阶数内重选零点数：精化后的 f0 会把残差整体压低，
            # 若连阶数一起重选会向高阶过拟合（实测）。
            again = [t for t in scan(f0_use, fbw_use, data)
                     if t[0] == pick[0]]
            if again:
                pick = again[0]

    n_ord, nz_sel, fit_r, f_s, p_s, e_s, _ = pick

    om = (freq / f0_use - f0_use / freq) / fbw_use
    built = _cm_extract_from_fit(n_ord, f_s, p_s, e_s, om, data[0], data[1],
                                 phase_ref=phase_ref)
    if built is None:
        raise ValueError("Y 留数重建失败：拟合多项式结构不满足横向矩阵口径")
    report, m = built
    mat_err = report["mag_max_err"]
    if fit_r > 1e-2:
        raise ValueError(
            f"反提拟合残差过大（rms={fit_r:.3e}）：阶数不足或数据非理想滤波响应")

    marr = _cm_reduce_arrow(m)
    qe_in = 1.0 / (fbw_use * abs(marr[0, 1]) ** 2)
    qe_out = 1.0 / (fbw_use * abs(marr[n_ord, n_ord + 1]) ** 2)
    tz_roots = np.roots(p_s)
    tz_norm = sorted(abs(float(r.imag)) for r in tz_roots
                     if abs(r.real) < 1e-6 * max(1.0, abs(r)))
    tz_cplx = sorted((round(float((-1j * r).real), 9),
                      round(float((-1j * r).imag), 9)) for r in tz_roots)
    # 带内幺正性诊断（假绿关死的一道：重建矩阵须复现无耗响应）
    unit_dev = 0.0
    for w in om:
        a11, a21 = _cm_response_raw(m, 1.0, 1.0, w)
        unit_dev = max(unit_dev, abs(abs(a11) ** 2 + abs(a21) ** 2 - 1.0))
    # 假绿关死（#122）：旧探针「fit_rms=5.8e−10 而 response_max_err=1.15 /
    # 幺正偏差 0.69 仍 ok=True」。ok 现在明确=「重建矩阵复现数据」：
    # ①响应误差与拟合水平一致（1e3×fit，绝对地板 1e−4）；②响应误差
    # 绝对上限 0.05（线性幅度，~0.42dB——好反提实测 ≤1e−3，模型地板
    # 实测 ~3e−2）。门不过时 ok=False 如实返回（拟合门超限仍 raise）。
    resp_consistent = mat_err <= max(1e3 * fit_r, 1e-4)
    resp_absolute = mat_err <= 5e-2
    method = ("magnitude_squared_cauchy+cameron_residue" if domain == "magnitude"
              else "cauchy_rational_fit+cameron_residue")
    return {"ok": bool(resp_consistent and resp_absolute),
            "order": n_ord, "n_finite_tz": nz_sel,
            "f0_ghz": round(f0_use, 9),
            "fbw": round(fbw_use, 9),
            "f0_source": f0_source,
            "fbw_source": "input" if fbw_in is not None else "estimated",
            "band_edges_ghz": ([round(float(edges[0]), 9),
                                round(float(edges[1]), 9)] if edges else None),
            "external_q": [round(qe_in, 9), round(qe_out, 9)],
            "coupling_matrix": _cm_to_list(m),
            "matrix_shape": [n_ord + 2, n_ord + 2],
            "transmission_zeros_norm": [round(z, 9) for z in tz_norm],
            "transmission_zeros_cplx": [list(p) for p in tz_cplx],
            "fit_rms": round(fit_r, 12),
            "response_max_err": round(mat_err, 12),
            "fit_domain": domain,
            "phase_ref": phase_ref if domain == "complex" else "n/a",
            "ref_delay_s": (None if ref_delay_used is None
                            else round(ref_delay_used, 15)),
            "coefficient_path": (report["path"] if domain == "complex"
                                 else "magnitude"),
            "derotation_residual_f": round(report["derot_f"], 12),
            "derotation_residual_p": round(report["derot_p"], 12),
            "unitarity_max_dev": round(float(unit_dev), 12),
            "ok_reason": ("response_consistent"
                          if resp_consistent and resp_absolute else
                          f"response_max_err {mat_err:.3e} 与拟合水平"
                          f"(rms={fit_r:.3e})不一致或超绝对上限 0.05"),
            "method": method,
            "note": "矩阵元素 [re,im]；external_q=Qe=1/(fbw·m_arrow²)。"
                    "fbw 由 S 参数形状不可辨识（Ω 缩放可被有理函数吸收），"
                    "无输入时按纹波带边（|S11|=纹波电平外沿交点）估计，"
                    "精度受频点密度限制（实测 ~1e−3 相对）；f0 由拟合残差精化"
                    "（仅 complex 域）。domain=magnitude：|S|² 幅值域兜底，"
                    "相位污染免疫，但 F/P 全局符号与单侧 TZ 的 ±Ω 不可辨识"
                    "（transmission_zeros_cplx 报 ± 对）、f0 不精化。"
                    "ok=重建矩阵复现数据（响应一致性双门），门不过如实 False。"}
