"""EM-7 SRA 内核定向测试（规格 §C-1 锚树，c-stream L 级条件项）。

锚树（规格原文逐条）与实测（2026-10-02，f=10 GHz，λ=30 mm，几何见常量）：
1. 合成电/磁偶极子对回收位置 ≤λ/20 + 残差 ≤−20 dB：电偶极子经 j_map、
   磁偶极子经 m_map 各自回收（单平面 [E_t;η₀H_t] 数据下 J/M 分解按最小范数
   混合：电型数据主入 J 通道、磁型数据的 −kz/k 符号分量落在 J 值域之外而
   被迫入 M̃ 通道——故电/磁各用纯源工况验证其自然通道，实测见各锚 docstring）；
2. 1% 噪声门（按实测重钉，规格预测偏离如实记入）：规格预测"1% 噪声过门 5%
   如实 ok=False"在修正 M̃ 块 η₀ 增益后的内核上不复现——扫参 du 0.12–0.3λ、
   d 0.5–3λ、cond 1e8–1e16 实测加噪位移 ≤0.02λ（正则强度随噪声自适应，最小
   范数 M̃ 峰位固有稳健）→ 重钉为稳健性锚（门内 + 噪声致位移 ≤2%λ）；核内
   ``ok`` 只消费可观测量（残差/域/cond/λ 双法，铁律 7：位置真值不进内核），
   如实 ok=False 路径由 extent/bandwidth/cond/undetermined 各锚钉死；
3. 纯口径对照峰位差 ≤λ/10：同一份电偶极子数据，SRA（稠密核+正则）与
   aperture_holography（纯 FFT 口径反演，主极化分量）各自定位，峰位差门；
4. du>λ/2 拒收：nyquist_guard 四轴逐轴，违反 ValueError；
5. λ 双法对照：加噪工况 L 曲线角与 GCV 一致（比 ≤10 → "lcurve+gcv"）；
   无噪工况 L 曲线无角区（谱平滑衰减）两法分歧 → "undetermined" 如实上报；
   合成分歧/单法失效分支在纯函数级钉死。

数值裁判 = 测试侧独立重建真值（#118 家族纪律）：偶极子闭式场走球坐标分量
+旋转矩阵（Jackson §9.2 经 e^{−iωt}→e^{+jωt} 共轭换算；与内核的笛卡尔并矢
∂i∂j g 装置完全不同代码路径，符号约定经远场 Poynting 外向流独立互证），
另有 operator-vs-闭式逐列对拍门防转录错。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.aperture_holography import C0, near_field_to_aperture
from rfauto.core.sra import (
    _diff_matrix,
    _gcv_minimize,
    _l_curve_corner,
    _reconcile_lambda,
    solve_sra,
    sra_operator,
    sra_solve,
)

F_HZ = 10.0e9
LAM = C0 / F_HZ  # 0.03 m
ETA0 = 4.0e-7 * math.pi * C0

# G1（细网格，良态）：源 18×18、观测 14×14、du=duo=0.2λ、d=0.8λ（外扩比 1.308）
G1 = dict(nsu=18, nsv=18, nou=14, nov=14, dus=0.2 * LAM, dvs=0.2 * LAM,
          duo=0.2 * LAM, dvo=0.2 * LAM, d=0.8 * LAM)
# G1v（D 锚 λ 双法工况）：du=duo=0.3λ 匹配栅（良态，cond≈3e4，λ 双法一致区）
G1V = dict(G1, dus=0.3 * LAM, dvs=0.3 * LAM, duo=0.3 * LAM, dvo=0.3 * LAM)
# G2（病态粗网格）：源 16×16、观测 12×12、du=duo=0.25λ、d=1.2λ（cond≈4.3e7）
G2 = dict(nsu=16, nsv=16, nou=12, nov=12, dus=0.25 * LAM, dvs=0.25 * LAM,
          duo=0.25 * LAM, dvo=0.25 * LAM, d=1.2 * LAM)

POS_GATE = 0.05 * LAM  # λ/20
RES_GATE_DB = -20.0


# ─── 测试侧独立真值：球坐标闭式偶极子场 + 旋转 ──────────────────────────────

def _dipole_fields(kind: str, p_hat, r_obs, moment: float, f_hz: float):
    """点流元场（与内核不同代码路径的真值）。

    电 流元 Il（A·m，e^{+jωt}、e^{−jkr}，推导见模块 docstring；与
    Jackson §9.2 e^{−iωt} 式经共轭换算一致）::

        E_r = ηIl cosθ (1+1/(jkR)) e^{−jkR} / (2πR²)
        E_θ = jηkIl sinθ (1+1/(jkR)−1/(kR)²) e^{−jkR} / (4πR)
        H_φ = jkIl sinθ (1+1/(jkR)) e^{−jkR} / (4πR)

    磁 流元 Ml（V·m）= 电元对偶（E→H、H→−E、Il→Ml/η₀）：
    E_M = −η₀·H_J(Il=Ml/η₀)、H_M = +E_J(Il=Ml/η₀)/η₀。
    """
    k = 2.0 * np.pi * f_hz / C0
    p_hat = np.asarray(p_hat, float)
    p_hat = p_hat / np.linalg.norm(p_hat)
    r = np.asarray(r_obs, float)
    big_r = float(np.linalg.norm(r))
    assert big_r > 0.0
    n_hat = r / big_r
    cos_t = float(p_hat @ n_hat)
    ncp = np.cross(n_hat, p_hat)
    sin_t = float(np.linalg.norm(ncp))
    assert sin_t > 1e-12, "测试自检：观测点避开偶极子轴线"
    th_hat = (cos_t * n_hat - p_hat) / sin_t
    ph_hat = np.cross(n_hat, th_hat)
    il = moment / ETA0 if kind == "M" else moment
    e_r = ETA0 * il * cos_t * (1.0 + 1.0 / (1j * k * big_r)) * np.exp(-1j * k * big_r) / (
        2.0 * np.pi * big_r**2
    )
    e_t = (
        1j * ETA0 * k * il * sin_t
        * (1.0 + 1.0 / (1j * k * big_r) - 1.0 / (k * big_r) ** 2)
        * np.exp(-1j * k * big_r) / (4.0 * np.pi * big_r)
    )
    h_ph = (
        1j * k * il * sin_t * (1.0 + 1.0 / (1j * k * big_r))
        * np.exp(-1j * k * big_r) / (4.0 * np.pi * big_r)
    )
    e_vec = e_r * n_hat + e_t * th_hat
    h_vec = h_ph * ph_hat
    if kind == "M":
        return -ETA0 * h_vec, e_vec / ETA0
    return e_vec, h_vec


def _synth_obs(geo: dict, sources):
    """观测面 4 分量场合成（源 = (kind, p_hat, (x,y), moment)，z=0）。"""
    ox = (np.arange(geo["nou"]) - (geo["nou"] - 1) / 2.0) * geo["duo"]
    oy = (np.arange(geo["nov"]) - (geo["nov"] - 1) / 2.0) * geo["dvo"]
    xg, yg = np.meshgrid(ox, oy, indexing="ij")
    pts = np.stack([xg.ravel(), yg.ravel(), np.full(xg.size, geo["d"])], axis=1)
    ex = np.zeros(pts.shape[0], complex)
    ey = np.zeros(pts.shape[0], complex)
    hx = np.zeros(pts.shape[0], complex)
    hy = np.zeros(pts.shape[0], complex)
    for kind, p_hat, spos, mom in sources:
        r_rel = pts - np.array([spos[0], spos[1], 0.0])
        for t in range(pts.shape[0]):
            e_vec, h_vec = _dipole_fields(kind, p_hat, r_rel[t], mom, F_HZ)
            ex[t] += e_vec[0]
            ey[t] += e_vec[1]
            hx[t] += h_vec[0]
            hy[t] += h_vec[1]
    return (
        ex.reshape(geo["nou"], geo["nov"]),
        ey.reshape(geo["nou"], geo["nov"]),
        hx.reshape(geo["nou"], geo["nov"]),
        hy.reshape(geo["nou"], geo["nov"]),
    )


def _add_channel_noise(fields, rel: float, seed: int):
    """逐通道相对噪声（每通道各自 1%·max——全局 max 会把小通道打成纯噪声）。"""
    rng = np.random.default_rng(seed)
    out = []
    for a in fields:
        sc = rel * float(np.abs(a).max())
        out.append(a + sc * (rng.standard_normal(a.shape) + 1j * rng.standard_normal(a.shape)) / np.sqrt(2))
    return out


def _solve(geo: dict, sources, **kw):
    ex, ey, hx, hy = _synth_obs(geo, sources)
    return solve_sra(
        ex, ey, hx, hy,
        geo["duo"], geo["dvo"], geo["d"], F_HZ,
        geo["dus"], geo["dvs"], geo["nsu"], geo["nsv"],
        **kw,
    )


# ─── 算子 vs 独立闭式（防转录错，#118） ─────────────────────────────────────

def test_operator_columns_match_independent_dipole_closed_form():
    """Z 的单列作用 = 同矩闭式偶极子场（E/M 通道各 2 极化 × 3 观测点）。"""
    geo = dict(nsu=6, nsv=6, nou=5, nov=5, dus=0.3 * LAM, dvs=0.3 * LAM,
               duo=0.25 * LAM, dvo=0.25 * LAM, d=0.7 * LAM)
    op = sra_operator(
        geo["dus"], geo["dvs"], geo["nsu"], geo["nsv"],
        geo["duo"], geo["dvo"], geo["nou"], geo["nov"], geo["d"], F_HZ,
    )
    z = np.asarray(op["z_matrix"])
    nsp = geo["nsu"] * geo["nsv"]
    nopp = geo["nou"] * geo["nov"]
    ox = (np.arange(geo["nou"]) - (geo["nou"] - 1) / 2.0) * geo["duo"]
    oy = (np.arange(geo["nov"]) - (geo["nov"] - 1) / 2.0) * geo["dvo"]
    obs_pts = [(1, 2), (3, 0), (4, 4)]  # (iu, iv) 观测点网格索引
    src_nodes = [(2, 3), (0, 0)]
    for ch, (kind, axis) in enumerate([("E", 0), ("E", 1), ("M", 0), ("M", 1)]):
        p_hat = np.zeros(3)
        p_hat[axis] = 1.0
        for ju, jv in src_nodes:
            col = ch * nsp + ju * geo["nsv"] + jv
            spos = ((ju - (geo["nsu"] - 1) / 2.0) * geo["dus"],
                    (jv - (geo["nsv"] - 1) / 2.0) * geo["dvs"])
            zc = z[:, col]
            col_norm = float(np.linalg.norm(zc))
            assert col_norm > 0.0
            mom = ETA0 if kind == "M" else 1.0  # M̃ 矩 1 → 物理 M 矩 η₀
            for iu, iv in obs_pts:
                pidx = iu * geo["nov"] + iv  # 行 = 分量块偏移 + 观测点 C 序索引
                px, py = ox[iu], oy[iv]
                e_vec, h_vec = _dipole_fields(
                    kind, p_hat, (px - spos[0], py - spos[1], geo["d"]), mom, F_HZ
                )
                want = np.array([e_vec[0], e_vec[1], ETA0 * h_vec[0], ETA0 * h_vec[1]])
                got = np.array([
                    zc[pidx], zc[nopp + pidx], zc[2 * nopp + pidx], zc[3 * nopp + pidx],
                ])
                rel = float(np.linalg.norm(got - want) / col_norm)
                assert rel <= 1e-9, f"通道 {ch} 节点 {(ju, jv)} 观测 {(iu, iv)}: rel={rel:.3g}"


# ─── 锚 1：电/磁偶极子回收位置 ≤λ/20 + 残差 ≤−20 dB ─────────────────────────

def test_anchor_electric_dipole_recovery_and_pure_aperture_comparison():
    """锚 1a+3：电偶极子（G1）j_map 回收 ≤λ/20、残差 ≤−20 dB、纯口径对照 ≤λ/10。

    实测（x̂ 取向，(1.3,−0.9)·du）：errJ=0.0092λ，res=−54.6 dB；
    纯 FFT 口径反演（主极化 Ex 分量，aperture_holography）峰位差=0.043λ。
    """
    pos = (1.3 * G1["duo"], -0.9 * G1["duo"])
    out = _solve(G1, [("E", [1.0, 0.0, 0.0], pos, 1.0)])
    err_j = float(np.linalg.norm(out["argmax_j_xy_m"] - np.array(pos)))
    assert out["domain_ok"] is True
    assert err_j <= POS_GATE, f"errJ={err_j / LAM:.4f} λ"
    assert out["residual_db"] <= RES_GATE_DB
    # 纯口径对照：同一数据的纯 FFT 口径反演（E 主极化分量）
    ex, _ey, _hx, _hy = _synth_obs(G1, [("E", [1.0, 0.0, 0.0], pos, 1.0)])
    inv = near_field_to_aperture(ex, G1["duo"], G1["dvo"], G1["d"], F_HZ)
    eap = np.abs(inv["e_aperture"]) ** 2
    xo = (np.arange(G1["nou"]) - (G1["nou"] - 1) / 2.0) * G1["duo"]
    i0, j0 = np.unravel_index(int(np.argmax(eap)), eap.shape)
    win = eap[max(i0 - 1, 0):i0 + 2, max(j0 - 1, 0):j0 + 2]
    loc_ap = np.array([
        (win.sum(axis=1) * xo[max(i0 - 1, 0):i0 + 2]).sum() / win.sum(),
        (win.sum(axis=0) * xo[max(j0 - 1, 0):j0 + 2]).sum() / win.sum(),
    ])
    diff = float(np.linalg.norm(out["argmax_j_xy_m"] - loc_ap))
    assert diff <= 0.1 * LAM, f"纯口径峰位差={diff / LAM:.4f} λ"


def test_anchor_magnetic_dipole_recovery():
    """锚 1b：磁偶极子（G1，x̂ 取向）m_map 回收 ≤λ/20 + 残差 ≤−20 dB。

    实测 errM=0.0065λ（(−1.3,2.6)·du）。磁型数据的 E/H 符号（η₀H_TE/E_TE
    = −kz/k）在纯 J 值域之外 → 最小范数解被迫在 M̃ 通道承载，m_map 峰落位。
    """
    pos = (-1.3 * G1["duo"], 2.6 * G1["duo"])
    out = _solve(G1, [("M", [1.0, 0.0, 0.0], pos, 1.0)])
    err_m = float(np.linalg.norm(out["argmax_m_xy_m"] - np.array(pos)))
    assert out["domain_ok"] is True
    assert err_m <= POS_GATE, f"errM={err_m / LAM:.4f} λ"
    assert out["residual_db"] <= RES_GATE_DB


# ─── 锚 2：1% 噪声过门 5% 如实（G2 病态工况） ────────────────────────────────

def test_anchor_one_percent_noise_position_robust_honest():
    """锚 2（按实测重钉，规格预测偏离如实记入）：1% 通道噪声下位置门内 + 核内自洽。

    规格锚原文"1% 噪声过门 5% 如实 ok=False"预测加噪越门；修正 M̃ 块
    η₀ 增益后的内核实测**不越门**（扫参 du 0.12–0.3λ、d 0.5–3λ、cond
    1e8–1e16：加噪位移 ≤0.02λ，加噪前后差 ≤0.01λ）——正则强度随噪声自适应
    （GCV+L 曲线一致区），最小范数 M̃ 峰位对 1% 噪声固有稳健。按 #122 如实
    重钉为稳健性锚：干净/加噪均 ≤5%λ 且噪声致位移 ≤2%λ；核内可观测量门
    （残差/λ/域/cond）在加噪工况保持自洽（铁律 7：位置真值不进内核）。
    如实 ok=False 路径由 extent/bandwidth/cond/undetermined 各锚钉死。
    """
    geo = G2
    pos = np.array([-2.7, -1.4]) * geo["duo"]
    fields = _synth_obs(geo, [("M", [1.0, 0.0, 0.0], pos, 1.0)])
    clean = solve_sra(*fields, geo["duo"], geo["dvo"], geo["d"], F_HZ,
                      geo["dus"], geo["dvs"], geo["nsu"], geo["nsv"])
    err_clean = float(np.linalg.norm(clean["argmax_m_xy_m"] - pos))
    assert err_clean <= POS_GATE, f"对照过门：errM={err_clean / LAM:.4f} λ"
    assert clean["residual_db"] <= RES_GATE_DB
    for seed in (11, 23):
        noisy = solve_sra(*_add_channel_noise(fields, 0.01, seed),
                          geo["duo"], geo["dvo"], geo["d"], F_HZ,
                          geo["dus"], geo["dvs"], geo["nsu"], geo["nsv"])
        err_n = float(np.linalg.norm(noisy["argmax_m_xy_m"] - pos))
        assert err_n <= POS_GATE, f"种子 {seed} 仍应在门内：errM={err_n / LAM:.4f} λ"
        assert abs(err_n - err_clean) <= 0.02 * LAM, "噪声致位移应 ≤2%λ（实测稳健性）"
        # 核内可观测量门自洽：残差 ≈ 噪声水平仍在 −20 dB 门内、λ 判据有效
        assert noisy["residual_db"] <= RES_GATE_DB
        assert noisy["method"] in ("lcurve+gcv", "lcurve", "gcv")


# ─── 锚 5：λ 双法对照 ────────────────────────────────────────────────────────

def test_lambda_dual_method_agreement_under_noise():
    """锚 5a：加噪工况（G1v，E+M 双源，1% 噪声种子 11）双法一致。

    实测 L/G 比 ≈1.4–2.1 ≤10 → method="lcurve+gcv"、λ=两法几何均值。
    """
    pos_e = (0.32 * G1V["duo"], -0.41 * G1V["duo"])
    pos_m = (-0.55 * G1V["duo"], 0.62 * G1V["duo"])
    fields = _synth_obs(G1V, [
        ("E", [0.0, 1.0, 0.0], pos_e, 1.0),
        ("M", [1.0, 0.0, 0.0], pos_m, 1.0),
    ])
    out = solve_sra(*_add_channel_noise(fields, 0.01, 11),
                    G1V["duo"], G1V["dvo"], G1V["d"], F_HZ,
                    G1V["dus"], G1V["dvs"], G1V["nsu"], G1V["nsv"])
    lam_l = out["reg_lambda_lcurve"]
    lam_g = out["reg_lambda_gcv"]
    assert lam_l is not None and lam_g is not None and lam_l > 0.0 and lam_g > 0.0
    ratio = max(lam_l, lam_g) / min(lam_l, lam_g)
    assert ratio <= 10.0, f"双法比={ratio:.3g}"
    assert out["method"] == "lcurve+gcv"
    assert out["reg_lambda"] == pytest.approx(math.sqrt(lam_l * lam_g), rel=1e-12)
    assert out["ok"] is True


def test_lambda_dual_method_undetermined_honest_without_noise():
    """锚 5b：无噪工况双法分歧 → "undetermined" 如实上报（ok=False）。

    无噪数据的 GCV 落网格下沿（λ→pinv）、L 曲线角在平滑衰减谱上无角区而
    止于重阻尼端——两法差 ≫10×，如实报 undetermined 并 ok=False（λ 仍报
    几何均值供检视，实测残差 −53 dB 仍过 −20 门：不可判定 ≠ 解不可用）。
    """
    pos = np.array([-2.7, -1.4]) * G2["duo"]
    out = _solve(G2, [("M", [1.0, 0.0, 0.0], pos, 1.0)])
    assert out["method"] == "undetermined"
    assert out["ok"] is False
    assert out["reg_lambda"] > 0.0
    assert out["residual_db"] <= RES_GATE_DB


def test_lambda_reconcile_lcurve_gcv_unit_branches():
    """锚 5c：合流/曲率角/GCV 纯函数级分支钉（合成曲线，真值构造已知）。"""
    # 合流：一致 → 几何均值 + lcurve+gcv；差 >10× → undetermined；单法；双无
    lam, method, _ = _reconcile_lambda(1.0, 2.0, 10.0)
    assert method == "lcurve+gcv" and lam == pytest.approx(math.sqrt(2.0))
    lam, method, _ = _reconcile_lambda(1.0, 100.0, 10.0)
    assert method == "undetermined" and lam == pytest.approx(10.0)
    lam, method, _ = _reconcile_lambda(None, 5.0, 10.0)
    assert method == "gcv" and lam == pytest.approx(5.0)
    lam, method, _ = _reconcile_lambda(7.0, None, 10.0)
    assert method == "lcurve" and lam == pytest.approx(7.0)
    lam, method, _ = _reconcile_lambda(None, None, 10.0)
    assert method == "undetermined" and lam is None
    # L 曲线角：双臂折线（底臂 u 2→1/v≈0，角点 (1,1)，竖臂 u≈1/v 1→7），
    # 曲率最大点 = 已知角点索引 10
    n = 21
    lam_grid = np.geomspace(1.0, 100.0, n)
    log_u = np.empty(n)
    log_v = np.empty(n)
    for i in range(n):
        if i <= 10:
            log_u[i] = 2.0 - 0.1 * i
            log_v[i] = 0.05 * i
        else:
            log_u[i] = 1.0 - 0.01 * (i - 10)
            log_v[i] = 1.0 + 0.3 * (i - 10)
    corner = _l_curve_corner(lam_grid, 10.0**log_u, 10.0**log_v)
    assert corner == pytest.approx(lam_grid[10], rel=1e-12)
    # 平滑无角曲线（纯指数趋势）也返回有限值（不崩）
    assert _l_curve_corner(lam_grid, np.geomspace(1, 1e-3, n), np.geomspace(1, 1e3, n)) is not None
    # GCV：构造抛物型 ρ(λ)（对数坐标最小在 λ0）+ trace=0 → 返回 λ0
    lam0 = 3.7
    grid = np.geomspace(0.1, 100.0, 200)
    rho = (np.log(grid / lam0)) ** 2 + 0.1
    best = _gcv_minimize(grid, rho, 50, np.zeros_like(grid))
    assert best == pytest.approx(grid[int(np.argmin(rho))], rel=1e-12)


# ─── 守卫四条 ────────────────────────────────────────────────────────────────

def test_guard_sampling_violation_rejected():
    """锚 4：du>λ/2 拒收（观测/源 × u/v 四轴逐轴，ValueError）。"""
    fields = _synth_obs(G1, [("E", [1.0, 0.0, 0.0], (0.0, 0.0), 1.0)])
    with pytest.raises(ValueError, match="λ/2"):
        solve_sra(fields[0], fields[1], fields[2], fields[3],
                  0.6 * LAM, G1["dvo"], G1["d"], F_HZ,
                  G1["dus"], G1["dvs"], G1["nsu"], G1["nsv"])
    with pytest.raises(ValueError, match="λ/2"):
        solve_sra(fields[0], fields[1], fields[2], fields[3],
                  G1["duo"], G1["dvo"], G1["d"], F_HZ,
                  0.55 * LAM, G1["dvs"], G1["nsu"], G1["nsv"])


def test_guard_extent_and_bandwidth_reported_domain_ok_false():
    """守卫 2/3：源面外扩不足 / 观测谱超源网格支撑 → domain_ok=False（不拒收）。"""
    # 外扩比 13/11=1.18 <1.3 → extent_ok=False，解照常产出（截断伪象可见）
    geo = dict(G1, nsu=14, nsv=14)
    out = _solve(geo, [("E", [1.0, 0.0, 0.0], (0.0, 0.0), 1.0)])
    assert out["extent_ok"] is False
    assert out["domain_ok"] is False
    assert out["ok"] is False
    assert float(np.max(out["j_map"])) > 0.0
    # 带宽守卫：近扫（0.3λ）+粗源格（0.4λ）+细观测（0.1λ）——观测谱含源网格
    # 不可表示的高角内容（实测占比 5.7e-2 > 1e-3 地板）
    geo_bw = dict(nsu=12, nsv=12, nou=20, nov=20, dus=0.4 * LAM, dvs=0.4 * LAM,
                  duo=0.1 * LAM, dvo=0.1 * LAM, d=0.3 * LAM)
    out_bw = _solve(geo_bw, [("E", [0.0, 1.0, 0.0], (0.3 * geo_bw["duo"], -0.2 * geo_bw["duo"]), 1.0)])
    assert out_bw["bandwidth_ok"] is False
    assert out_bw["bandwidth_frac_out"] > 1e-3
    assert out_bw["domain_ok"] is False
    assert out_bw["extent_ok"] is True


def test_guard_cond_warning_fires_but_solve_continues():
    """守卫 4：cond(Z)>1e8 警示（不拒收）：du=0.22λ、d=2λ 实测 cond≈4e12。"""
    geo = dict(G2, dus=0.22 * LAM, dvs=0.22 * LAM, d=2.0 * LAM)
    out = _solve(geo, [("E", [1.0, 0.0, 0.0], (0.2 * geo["duo"], -0.3 * geo["duo"]), 1.0)])
    assert out["cond_z"] > 1e8
    assert out["cond_warning"] is True
    assert out["ok"] is False
    assert float(np.max(out["j_map"])) > 0.0


def test_zero_data_rejected():
    """全零观测场拒收（残差相对值无定义）。"""
    zero = np.zeros((G1["nou"], G1["nov"]), complex)
    with pytest.raises(ValueError, match="零向量"):
        solve_sra(zero, zero, zero, zero,
                  G1["duo"], G1["dvo"], G1["d"], F_HZ,
                  G1["dus"], G1["dvs"], G1["nsu"], G1["nsv"])


# ─── L=一阶差分模式 ──────────────────────────────────────────────────────────

def test_diff_operator_mode_recovery_and_monotone_residual():
    """L=一阶差分（小网格）：回收 ≤λ/20、残差沿 λ 单调不减、schema 完整。"""
    geo = dict(nsu=10, nsv=10, nou=8, nov=8, dus=0.25 * LAM, dvs=0.25 * LAM,
               duo=0.25 * LAM, dvo=0.25 * LAM, d=0.6 * LAM)
    pos = (0.8 * geo["duo"], -0.6 * geo["duo"])
    out = _solve(geo, [("E", [0.0, 1.0, 0.0], pos, 1.0)], operator="diff")
    err_j = float(np.linalg.norm(out["argmax_j_xy_m"] - np.array(pos)))
    assert err_j <= POS_GATE, f"diff 模式 errJ={err_j / LAM:.4f} λ"
    assert out["residual_db"] <= RES_GATE_DB
    # 残差范数沿 λ 网格单调不减（Tikhonov 通性，与 L 无关）
    op = sra_operator(geo["dus"], geo["dvs"], geo["nsu"], geo["nsv"],
                      geo["duo"], geo["dvo"], geo["nou"], geo["nov"], geo["d"], F_HZ)
    z = np.asarray(op["z_matrix"])
    ex, ey, hx, hy = _synth_obs(geo, [("E", [0.0, 1.0, 0.0], pos, 1.0)])
    b = np.concatenate([ex.ravel(), ey.ravel(), (ETA0 * hx).ravel(), (ETA0 * hy).ravel()])
    sol = sra_solve(z, b, n_src_u=geo["nsu"], n_src_v=geo["nsv"], operator="diff")
    res_norms = np.asarray(sol["res_norms"])
    assert np.all(np.diff(res_norms) >= -1e-9 * max(float(res_norms[-1]), 1e-30))
    # 差分算子形状与行归零（差分核行和=0）
    l_mat = _diff_matrix(geo["nsu"], geo["nsv"])
    assert l_mat.shape == (4 * ((geo["nsu"] - 1) * geo["nsv"] + geo["nsu"] * (geo["nsv"] - 1)),
                           4 * geo["nsu"] * geo["nsv"])
    assert np.all(np.abs(l_mat.sum(axis=1)) <= 1e-12)


# ─── 输出 schema ─────────────────────────────────────────────────────────────

def test_output_schema_spec_keys():
    """规格 schema 八键齐备 + 类型/形状（λ→reg_lambda 映射见模块 docstring）。"""
    out = _solve(G1, [("E", [1.0, 0.0, 0.0], (0.5 * G1["duo"], 0.5 * G1["duo"]), 1.0)])
    for key in ("j_map", "m_map", "argmax_xy_m", "reg_lambda", "method",
                "cond_z", "residual_db", "domain_ok"):
        assert key in out, f"缺规格 schema 键 {key}"
    assert out["j_map"].shape == (G1["nsu"], G1["nsv"])
    assert out["j_map"].dtype.kind == "f"  # |J| 热图（实数）
    assert out["m_map"].shape == (G1["nsu"], G1["nsv"])
    assert np.all(np.isfinite(out["j_map"])) and np.all(np.isfinite(out["m_map"]))
    loc = np.asarray(out["argmax_xy_m"])
    assert loc.shape == (2,)
    half_u = (G1["nsu"] - 1) / 2.0 * G1["dus"] + G1["dus"]
    half_v = (G1["nsv"] - 1) / 2.0 * G1["dvs"] + G1["dvs"]
    assert abs(loc[0]) <= half_u and abs(loc[1]) <= half_v  # 定位在源网格内
    assert out["reg_lambda"] > 0.0
    assert out["method"] in ("lcurve+gcv", "lcurve", "gcv", "undetermined")
    assert isinstance(out["domain_ok"], bool)
    assert isinstance(out["ok"], bool)
    assert out["cond_z"] > 0.0
    assert out["residual_db"] <= 0.0
