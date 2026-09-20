"""msl_cpw β2 口径审计驱动脚本（纯离线，零引擎真跑）。

预声明判据：⑦ msl_cpw β2 口径审计；预声明判据见
runs/msl_cpw_beta2_audit/criteria.md（先写后算，本脚本不设门只产证据）。

E1 窗长归因：300k 探针序列截到 N100 样本（=100k 窗）重算 β2/β1 中位，
   对照 100k 真跑归档 port_beta.csv（确定性预期 ≈0 差）。
E2 提取链复核：自实现 DFT（与 openEMS UI_data/DFT_time2freq 同口径：
   sum(v·e^{-j2πft})·Δt·2）+ ports.py CPWPort/MSLPort.ReadUIData β 公式，
   对照归档 port_beta.csv 全带。
E3 双行波拟合：三站 u 复数样本拟合 u(z)=F e^{-jβz}+R e^{+jβz} 得 β_fit、
   |Γ|；口径份额=|β_engine−β_fit|；另产引擎自算 ZL（#280 诊断）与
   站间相位斜率直接估计。
E4 闭式参考审计：_cpwg_ri 同参复算+参数敏感性；2D FDM 下域电容
   （无壁对照闭式 / 全壁上界）；3D 周期栅胞（离散过孔点估计，按
   C_via/C_novia 同网格比值转移到闭式基）；sparams S21 相位去嵌旁证。

用法: .venv/Scripts/python.exe scripts/msl_cpw_beta2_audit.py
输出: runs/msl_cpw_beta2_audit/evidence.json（+stdout 全文）
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import cg, spsolve

REPO = Path(__file__).resolve().parents[1]
RUN300K = REPO / "runs/benchmark/msl_cpw_m0.4_nrts300k"
RUN100K = REPO / "runs/benchmark/msl_cpw_m0.4"
OUT_DIR = REPO / "runs/msl_cpw_beta2_audit"

F_MID = 2.5e9
C0 = 299792458.0
EPS0 = 8.8541878128e-12
FREQS = np.linspace(2.25e9, 2.75e9, 401)
BAND = (FREQS >= 0.96 * F_MID) & (FREQS <= 1.04 * F_MID)

# 渲染几何（runs/benchmark/msl_cpw_m0.4_nrts300k/simulation.py 实读）
W_C, GAP, H_SUB, ER = 0.849e-3, 0.2e-3, 0.508e-3, 3.66
RV, SV = 0.15e-3, 2.0e-3          # 过孔半径/间距
X_VIA = W_C / 2 + GAP + 0.5e-3    # ±1.1245mm（地内缘外 VO=0.5mm）
EPS1_REF_HJ = 2.85273             # 门参考（json er_eff1_hj_closed_form）

# 探针站实际坐标（fdtd/port_* 文件头 start/stop-coordinates 实测，m）
Y2 = np.array([46.9071e-3, 46.5103e-3, 46.1136e-3])     # port2 u 站 A,B,C
Y1 = np.array([-46.9071e-3, -46.5103e-3, -46.1136e-3])  # port1 u 站 A,B,C
U_DELTA2 = float(np.sum(np.abs(np.diff(Y2))))
U_DELTA1 = float(np.sum(np.abs(np.diff(Y1))))
I_DELTA0 = 0.39675e-3          # 构造意图 i 站间距（相邻 meshline 中点差）


# ── 通用 IO 与门链 ──────────────────────────────────────────────────────

def read_beta_csv(path: Path):
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    f = np.array([float(r[0]) for r in rows])
    return f, np.array([float(r[1]) for r in rows]), np.array([float(r[2]) for r in rows])


def beta_eps_median(f: np.ndarray, b: np.ndarray) -> float:
    """harness _beta_eps 同款（scripts/engine_benchmark_expand.py:79）。"""
    sel = (f >= 0.96 * F_MID) & (f <= 1.04 * F_MID)
    beta = float(np.median(b[sel]))
    f_med = float(np.median(f[sel]))
    return (beta * C0 / (2 * np.pi * f_med)) ** 2


def band_med(x) -> float:
    return float(np.median(np.asarray(x)[BAND]))


def read_ui(path: Path):
    t, v = [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("%"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                t.append(float(parts[0]))
                v.append(float(parts[1]))
    return np.array(t), np.array(v)


def dft_pulse(t: np.ndarray, v: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    """openEMS DFT_time2freq 同口径（openEMS/utilities.py:21）。"""
    dt = t[1] - t[0]
    return 2.0 * (np.exp(-2j * np.pi * np.outer(freqs, t)) @ v) * dt


def load_port(run: Path, port: int, n_limit: int | None = None) -> dict:
    fd = run / "fdtd"
    u_fns = (["port_ut_2A1", "port_ut_2A2", "port_ut_2B1", "port_ut_2B2",
              "port_ut_2C1", "port_ut_2C2"] if port == 2 else
             ["port_ut_1A", "port_ut_1B", "port_ut_1C"])
    i_fns = ["port_it_2A", "port_it_2B"] if port == 2 else ["port_it_1A", "port_it_1B"]
    data, meta = {}, {}
    for fn in u_fns + i_fns:
        t, v = read_ui(fd / fn)
        data[fn] = dft_pulse(t[:n_limit], v[:n_limit], FREQS)
        meta[fn] = {"n": len(t), "dt_s": float(t[1] - t[0]), "t_end_s": float(t[-1])}
    return {"d": data, "meta": meta}


# ── E2：ports.py β 公式逐频复现 ────────────────────────────────────────

def beta_engine_cpw(p: dict):
    """CPWPort.ReadUIData（openEMS ports.py:1290-1315）逐频复现。"""
    g = p["d"]
    ufA = g["port_ut_2A1"] + g["port_ut_2A2"]
    ufB = g["port_ut_2B1"] + g["port_ut_2B2"]
    ufC = g["port_ut_2C1"] + g["port_ut_2C2"]
    Et = ufB
    dEt = (ufC - ufA) / U_DELTA2                      # unit=1（m 制网格）
    Ht = 0.5 * (g["port_it_2A"] + g["port_it_2B"])
    dHt = (g["port_it_2B"] - g["port_it_2A"]) / I_DELTA0
    beta = np.sqrt(-dEt * dHt / (Ht * Et))
    beta = np.where(np.real(beta) < 0, -beta, beta)
    ZL = np.sqrt(Et * dEt / (Ht * dHt))
    return beta, ZL


def beta_engine_msl(p: dict):
    """MSLPort.ReadUIData（openEMS ports.py:355-377）逐频复现。"""
    g = p["d"]
    Et = g["port_ut_1B"]
    dEt = (g["port_ut_1C"] - g["port_ut_1A"]) / U_DELTA1
    Ht = 0.5 * (g["port_it_1A"] + g["port_it_1B"])
    dHt = (g["port_it_1B"] - g["port_it_1A"]) / I_DELTA0
    beta = np.sqrt(-dEt * dHt / (Ht * Et))
    beta = np.where(np.real(beta) < 0, -beta, beta)
    ZL = np.sqrt(Et * dEt / (Ht * dHt))
    return beta, ZL


# ── E3：双行波拟合与站间相位 ───────────────────────────────────────────

def two_wave_fit(z: np.ndarray, u: np.ndarray, beta_ref: float):
    """u(z)=F e^{-jβz}+R e^{+jβz}：β 一维扫描+线性 LSQ（3 复数样本过定）。

    法方程 2×2 逐 β 解析解，向量化扫描（G=[[3,s],[s*,3]], s=Σe^{-2jβz}）。
    """

    def scan(betas: np.ndarray):
        E = np.exp(-1j * np.outer(betas, z))          # (nb,3) c1=e^{-jβz}
        s = np.sum(E * E, axis=1)                     # Σ e^{-2jβz}
        b1 = np.conj(E) @ u
        b2 = E @ u
        det = 9.0 - np.abs(s) ** 2
        F = (3.0 * b1 - np.conj(s) * b2) / det
        R = (3.0 * b2 - s * b1) / det
        uu = float(np.vdot(u, u).real)
        res2 = np.maximum(uu - (np.conj(b1) * F + np.conj(b2) * R).real, 0.0)
        return res2, F, R

    grid1 = np.linspace(0.5, 1.5, 2401) * beta_ref
    res2, _, _ = scan(grid1)
    b0 = grid1[int(np.argmin(res2))]
    grid2 = np.linspace(b0 - 1.2e-3 * beta_ref, b0 + 1.2e-3 * beta_ref, 161)
    res2, F, R = scan(grid2)
    j = int(np.argmin(res2))
    best_b = float(grid2[j])
    gamma = complex(R[j] / F[j]) if abs(F[j]) > 1e-30 else 0j
    uu = float(np.vdot(u, u).real)
    return best_b, gamma, float(math.sqrt(res2[j]) / max(math.sqrt(uu), 1e-30))


def fit_band(p: dict, port: int, beta_ref_arr: np.ndarray):
    if port == 2:
        ys = Y2[[2, 1, 0]]                    # 沿 +y 传播次序 C,B,A
        z = ys - ys[0]
        us = np.row_stack([p["d"]["port_ut_2C1"] + p["d"]["port_ut_2C2"],
                           p["d"]["port_ut_2B1"] + p["d"]["port_ut_2B2"],
                           p["d"]["port_ut_2A1"] + p["d"]["port_ut_2A2"]])
    else:
        z = Y1 - Y1[0]
        us = np.row_stack([p["d"]["port_ut_1A"], p["d"]["port_ut_1B"],
                           p["d"]["port_ut_1C"]])
    betas, gammas, resids = [], [], []
    for k in range(len(FREQS)):
        b, g, r = two_wave_fit(z, us[:, k], float(beta_ref_arr[k]))
        betas.append(b)
        gammas.append(abs(g))
        resids.append(r)
    return np.array(betas), np.array(gammas), np.array(resids)


def station_phase_beta(p: dict, port: int) -> dict:
    """站间相位斜率直接 β（行波假设下界诊断；驻波时 A→B 与 B→C 分离）。"""
    s = 0.39675e-3
    if port == 2:
        u0 = p["d"]["port_ut_2C1"] + p["d"]["port_ut_2C2"]
        u1 = p["d"]["port_ut_2B1"] + p["d"]["port_ut_2B2"]
        u2 = p["d"]["port_ut_2A1"] + p["d"]["port_ut_2A2"]
    else:
        u0, u1, u2 = p["d"]["port_ut_1A"], p["d"]["port_ut_1B"], p["d"]["port_ut_1C"]
    out = {}
    for name, (ua, ub, d) in {"AB": (u0, u1, s), "BC": (u1, u2, s),
                              "AC": (u0, u2, 2 * s)}.items():
        b = np.abs(np.angle(ub / ua)) / d      # +y 传播时 arg<0（相位滞后）
        out[f"beta_{name}_med"] = band_med(b)
    return out


# ── E4a：闭式与敏感性 ──────────────────────────────────────────────────

def cpwg_parts(w_mm, gap_mm, h_mm, er):
    """_cpwg_ri 同式（src/rfauto/core/calculators.py:305-337）→ (εeff, r1, r4, Z0)。"""
    from scipy.special import ellipk
    a, b = w_mm / 2.0, w_mm / 2.0 + gap_mm
    k1 = a / b
    k4 = math.tanh(math.pi * a / (2 * h_mm)) / math.tanh(math.pi * b / (2 * h_mm))
    r1 = float(ellipk(k1 * k1)) / float(ellipk(1 - k1 * k1))
    r4 = float(ellipk(k4 * k4)) / float(ellipk(1 - k4 * k4))
    eps = (r1 + er * r4) / (r1 + r4)
    z0 = 1.0 / (2 * EPS0 * C0 * math.sqrt((r1 + er * r4) * (r1 + r4)))
    return eps, r1, r4, z0


# ── E4b：2D FDM 下域电容（εr=1，每单位长）─────────────────────────────
# 域 x∈[-8,8]mm、ζ∈[0,h]；条 V=1、顶层地/底地/域侧 V=0、槽区(ζ=0)与侧无通量
# 由网格自然处理（槽区 k=0 非 free 节点=Neumann 镜像；侧列为 V=0，场已衰减）。


def fdm_c_lower_2d(with_wall: bool, dx: float = 1.0e-5):
    a, b = W_C / 2, W_C / 2 + GAP
    xs = np.arange(-8e-3, 8e-3 + dx / 2, dx)
    nz = round(H_SUB / dx) + 1
    nx = len(xs)
    kind = np.zeros((nx, nz), dtype=np.int8)   # 0 free, 1 strip(V=1), 2 gnd(V=0)
    kind[:, -1] = 2                            # 底地
    kind[0, :] = 2                             # 侧（|x|=8mm，场已衰减）
    kind[-1, :] = 2
    kind[np.abs(xs) <= a + 1e-15, 0] = 1       # 条
    kind[np.abs(xs) >= b - 1e-15, 0] = 2       # 顶层地
    if with_wall:
        kind[np.abs(np.abs(xs) - X_VIA) < dx / 2, :] = 2
    free = [(i, k) for i in range(1, nx - 1) for k in range(1, nz - 1)
            if kind[i, k] == 0]
    pos = {fk: p for p, fk in enumerate(free)}
    n = len(free)
    rows = np.empty(5 * n, dtype=np.int64)
    cols = np.empty(5 * n, dtype=np.int64)
    vals = np.empty(5 * n, dtype=np.float64)
    rhs = np.zeros(n)
    for p, (i, k) in enumerate(free):
        rows[5 * p] = cols[5 * p] = p
        vals[5 * p] = 4.0
        for m, (di, dk) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
            ii, kk = i + di, k + dk
            kd = kind[ii, kk]
            q = 5 * p + m + 1
            if kd == 0 and kk > 0:
                rows[q], cols[q], vals[q] = p, pos[(ii, kk)], -1.0
            elif kd == 0 and kk == 0:
                rows[q], cols[q], vals[q] = p, p, -1.0  # 槽区 ζ=0 Neumann 镜像
            else:
                rows[q], cols[q], vals[q] = p, p, 0.0
                if kd == 1:
                    rhs[p] += 1.0
    A = csr_matrix((vals, (rows, cols)), shape=(n, n))
    v = spsolve(A, rhs)
    lut = {fk: float(v[p]) for p, fk in enumerate(free)}
    q_strip = 0.0
    for i in range(1, nx - 1):
        if kind[i, 0] == 1 and (i, 1) in lut:
            q_strip += 1.0 - lut[(i, 1)]
    return q_strip, n


# ── E4b'：3D 周期栅胞（离散过孔点估计）────────────────────────────────

def fdm_c_lower_3d(with_via: bool, dx: float = 4.0e-5):
    """x∈[-4,4]mm（侧 V=0）、y∈[0,SV) 周期、ζ∈[0,h]（底 0V）；
    ζ=0：条 1V、地 0V、槽区 Neumann；with_via: (±X_VIA, SV/2) r=RV 圆柱 V=0。
    返回条竖直面电荷和（同网格同口径，供 C_via/C_novia 比值转移）。
    """
    a, b = W_C / 2, W_C / 2 + GAP
    xs = np.arange(-4e-3, 4e-3 + dx / 2, dx)
    ny = round(SV / dx)
    nz = round(H_SUB / dx) + 1
    ys = np.arange(ny) * dx
    nx = len(xs)
    kind = np.zeros((nx, ny, nz), dtype=np.int8)
    kind[:, :, -1] = 2
    kind[0, :, :] = 2
    kind[-1, :, :] = 2
    kind[np.abs(xs) <= a + 1e-15, :, 0] = 1
    kind[np.abs(xs) >= b - 1e-15, :, 0] = 2
    if with_via:
        for sx in (X_VIA, -X_VIA):
            dx2 = (xs[:, None] - sx) ** 2 + (ys[None, :] - SV / 2) ** 2
            hit = dx2 <= (RV + dx / 2) ** 2
            kind[hit, 1:-1] = 2
    free = [(i, j, k) for i in range(1, nx - 1) for j in range(ny)
            for k in range(1, nz - 1) if kind[i, j, k] == 0]
    pos = {fk: p for p, fk in enumerate(free)}
    n = len(free)
    rows = np.empty(7 * n, dtype=np.int64)
    cols = np.empty(7 * n, dtype=np.int64)
    vals = np.empty(7 * n, dtype=np.float64)
    rhs = np.zeros(n)
    for p, (i, j, k) in enumerate(free):
        rows[7 * p] = cols[7 * p] = p
        vals[7 * p] = 6.0
        nbrs = ((i + 1, j, k), (i - 1, j, k), (i, (j + 1) % ny, k),
                (i, (j - 1) % ny, k), (i, j, k + 1), (i, j, k - 1))
        for m, (ii, jj, kk) in enumerate(nbrs):
            kd = kind[ii, jj, kk]
            q = 7 * p + m + 1
            if kd == 0 and kk > 0:
                rows[q], cols[q], vals[q] = p, pos[(ii, jj, kk)], -1.0
            elif kd == 0 and kk == 0:
                rows[q], cols[q], vals[q] = p, p, -1.0  # 槽区 ζ=0 Neumann 镜像
            else:
                rows[q], cols[q], vals[q] = p, p, 0.0
                if kd == 1:
                    rhs[p] += 1.0
    A = csr_matrix((vals, (rows, cols)), shape=(n, n))
    v, info = cg(A, rhs, rtol=1e-13, maxiter=20000)
    if info != 0:
        raise RuntimeError(f"cg 未收敛 info={info}")
    lut = {fk: float(v[p]) for p, fk in enumerate(free)}
    q_strip = 0.0
    for i in range(1, nx - 1):
        if kind[i, 0, 0] != 1:
            continue
        for j in range(ny):
            if (i, j, 1) in lut:
                q_strip += 1.0 - lut[(i, j, 1)]
    return q_strip, n


# ── E4c：S21 相位去嵌 ──────────────────────────────────────────────────

def s21_deembed(beta1_fit: np.ndarray, beta2_seed: float):
    with open(RUN300K / "sparams.csv", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    s21 = np.array([complex(float(r[3]), float(r[4])) for r in rows])
    L1 = 46.5103e-3 - 5e-3      # B1 站 → 锥起点（MSL）
    Lt = 10e-3                  # 锥变段
    L2 = 46.5103e-3 - 5e-3      # 锥终点 → B2 站（CPW）
    phi = np.unwrap(np.angle(s21))
    sel = (FREQS >= 2.35e9) & (FREQS <= 2.65e9)
    f0 = float(np.median(FREQS[sel]))
    # 非色散模型（带内色散实测 ≤0.04%，远小于拟合数组带缘噪声）：
    # β_model(f) = β_med·f/f0，避免 β_fit 数组的带缘拟合噪声进斜率
    beta1_m = beta1_fit[sel].mean() * FREQS[sel] / f0
    beta_t = 0.5 * (beta1_m + beta2_seed * FREQS[sel] / f0)
    phi_c = -phi[sel] - beta1_m * L1 - beta_t * Lt
    slope, ic = (float(x) for x in np.polyfit(FREQS[sel], phi_c, 1))
    resid = phi_c - (slope * FREQS[sel] + ic)
    return slope * f0 / L2, float(np.max(np.abs(resid))), L1 + Lt + L2


# ── 主流程 ─────────────────────────────────────────────────────────────

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ev: dict = {"kind": "msl_cpw_beta2_audit", "captured": "2026-09-19",
                "criteria": "runs/msl_cpw_beta2_audit/criteria.md（预声明）",
                "zero_sim_note": "纯离线：归档 dump 复算+准静态 FDM，零 FDTD 真跑"}

    # 门链复核（#97：输入文件→计算式→输出全链）
    f100, b1_100, b2_100 = read_beta_csv(RUN100K / "port_beta.csv")
    f300, b1_300, b2_300 = read_beta_csv(RUN300K / "port_beta.csv")
    eps_ref, r1_cf, r4_cf, z0_cf = cpwg_parts(W_C * 1e3, GAP * 1e3, H_SUB * 1e3, ER)
    eps1_100, eps2_100 = beta_eps_median(f100, b1_100), beta_eps_median(f100, b2_100)
    eps1_300, eps2_300 = beta_eps_median(f300, b1_300), beta_eps_median(f300, b2_300)
    ev["gate_chain"] = {
        "inputs": {"run100k": "runs/benchmark/msl_cpw_m0.4/port_beta.csv",
                   "run300k": "runs/benchmark/msl_cpw_m0.4_nrts300k/port_beta.csv",
                   "formula": "(median β in ±4%×2.5GHz · c/(2π·f_med))²"},
        "eps2_ref_recompute": round(eps_ref, 5),
        "eps2_ref_vs_json_pct": round((eps_ref / 2.56729 - 1) * 100, 4),
        "eps1_100k": round(eps1_100, 4), "eps2_100k": round(eps2_100, 4),
        "eps1_300k": round(eps1_300, 4), "eps2_300k": round(eps2_300, 4),
        "delta1_100k_pct": round((eps1_100 / EPS1_REF_HJ - 1) * 100, 3),
        "delta2_100k_pct": round((eps2_100 / eps_ref - 1) * 100, 3),
        "delta1_300k_pct": round((eps1_300 / EPS1_REF_HJ - 1) * 100, 3),
        "delta2_300k_pct": round((eps2_300 / eps_ref - 1) * 100, 3),
        "beta1_med_100k": band_med(b1_100), "beta1_med_300k": band_med(b1_300),
        "beta2_med_100k": band_med(b2_100), "beta2_med_300k": band_med(b2_300),
        "cpwg_Z0_closed_ohm": round(z0_cf, 2),
    }

    # E2 提取链复核
    p2 = load_port(RUN300K, 2)
    p1 = load_port(RUN300K, 1)
    b2_rep, ZL2 = beta_engine_cpw(p2)
    b1_rep, ZL1 = beta_engine_msl(p1)
    b2_rep_re, b1_rep_re = np.real(b2_rep), np.real(b1_rep)
    ev["chain_validation_E2"] = {
        "note": "引擎 CSV 写 np.real(beta)（e^{-jωt} 口径 sqrt 返回 β−jα，虚部=−α）",
        "beta2_max_rel_diff": float(np.max(np.abs(b2_rep_re - b2_300) / b2_300)),
        "beta1_max_rel_diff": float(np.max(np.abs(b1_rep_re - b1_300) / b1_300)),
        "beta2_band_median_rel_diff": float(np.median(
            np.abs(b2_rep_re - b2_300)[BAND] / b2_300[BAND])),
        "alpha2_med_1_per_m": round(float(np.median(-np.imag(b2_rep[BAND]))), 4),
        "alpha1_med_1_per_m": round(float(np.median(-np.imag(b1_rep[BAND]))), 4),
        "probe_meta_300k_ut2B1": p2["meta"]["port_ut_2B1"],
        "ZL2_med_ohm": round(band_med(np.real(ZL2)), 2),
        "ZL2_band_absmin_ohm": round(float(np.min(np.abs(ZL2[BAND]))), 2),
        "ZL2_band_absmax_ohm": round(float(np.max(np.abs(ZL2[BAND]))), 2),
        "ZL1_med_ohm": round(band_med(np.real(ZL1)), 2),
        "ZL2_vs_closed_pct": round((band_med(np.real(ZL2)) / z0_cf - 1) * 100, 2),
        "ZL1_vs_closed_pct": round((band_med(np.real(ZL1)) / 50.0 - 1) * 100, 2),
        "z_resolution_note": ("槽下场竖直尺度 h/π=0.162mm vs z 格 0.127mm（4 层基板）"
                              "=1.3 格/尺度高；MSL 场展布全 h=4 格——β 与 ZL 双低"
                              "与磁能欠分辨（L' 低 → β 低、ZL 低）自洽，#313 z 地板族"),
    }

    # E1 窗长归因（截断实验；N100=100k 归档探针样本数实读）
    _, v100 = read_ui(RUN100K / "fdtd" / "port_ut_2B1")
    n100 = len(v100)
    p2t = load_port(RUN300K, 2, n_limit=n100)
    p1t = load_port(RUN300K, 1, n_limit=n100)
    b2_trunc, _ = beta_engine_cpw(p2t)
    b1_trunc, _ = beta_engine_msl(p1t)
    ev["window_truncation_E1"] = {
        "note": ("300k 探针截前 N100 样本（=100k 窗，同 537·dt_fdtd 采样栅）按同公式"
                 "重提，对照 100k 真跑归档 port_beta.csv 中位；确定性预期差≈0"),
        "n100_samples": n100,
        "beta2_trunc_med": band_med(b2_trunc),
        "beta2_100k_med": band_med(b2_100),
        "beta2_trunc_vs_100k_pct": round((band_med(b2_trunc) / band_med(b2_100) - 1) * 100, 4),
        "beta1_trunc_med": band_med(b1_trunc),
        "beta1_trunc_vs_100k_pct": round((band_med(b1_trunc) / band_med(b1_100) - 1) * 100, 4),
    }

    # E3 双行波拟合
    beta_ref2 = 2 * np.pi * FREQS * math.sqrt(eps_ref) / C0
    beta_ref1 = 2 * np.pi * FREQS * math.sqrt(EPS1_REF_HJ) / C0
    b2_fit, g2, res2 = fit_band(p2, 2, beta_ref2)
    b1_fit, g1, res1 = fit_band(p1, 1, beta_ref1)
    b2_fit_t, _, _ = fit_band(p2t, 2, beta_ref2)
    sel_mid = (FREQS >= 2.4e9) & (FREQS <= 2.6e9)
    ev["standing_wave_E3"] = {
        "beta2_engine_med": band_med(b2_300),
        "beta2_fit_med": band_med(b2_fit),
        "beta2_engine_minus_fit_pct": round((band_med(b2_300) / band_med(b2_fit) - 1) * 100, 4),
        "gamma2_med_band": round(float(np.median(g2[sel_mid])), 4),
        "gamma2_max_band": round(float(np.max(g2[sel_mid])), 4),
        "fit2_resid_max_band": round(float(np.max(res2[sel_mid])), 5),
        "beta2_fit_trunc_med": band_med(b2_fit_t),
        "beta2_fit_window_sens_pct": round((band_med(b2_fit_t) / band_med(b2_fit) - 1) * 100, 4),
        "beta1_engine_med": band_med(b1_300),
        "beta1_fit_med": band_med(b1_fit),
        "beta1_engine_minus_fit_pct": round((band_med(b1_300) / band_med(b1_fit) - 1) * 100, 4),
        "gamma1_med_band": round(float(np.median(g1[sel_mid])), 4),
        "fit1_resid_max_band": round(float(np.max(res1[sel_mid])), 5),
        "port2_station_phase": station_phase_beta(p2, 2),
        "port1_station_phase": station_phase_beta(p1, 1),
    }

    # E4a 闭式敏感性（哪个参数的 ±x% 等值线过 −2.15%）
    base = {"w": W_C * 1e3, "gap": GAP * 1e3, "h": H_SUB * 1e3, "er": ER}
    sens = {}
    for name, val in base.items():
        kw = dict(base)
        kw[name] = val * 1.10
        e_up = cpwg_parts(kw["w"], kw["gap"], kw["h"], kw["er"])[0]
        kw[name] = val * 0.90
        e_dn = cpwg_parts(kw["w"], kw["gap"], kw["h"], kw["er"])[0]
        d10 = (e_up - e_dn) / 2
        sens[name] = {
            "d_eps_pct_per_10pct": round(float(d10 / eps_ref * 100), 4),
            "param_shift_pct_needed": round(float((eps2_300 - eps_ref) / d10 * 10), 3),
        }

    # E4b 2D FDM：无壁对照（对闭式验证）与全壁上界；比值转移到闭式基
    c_nov, n_nov = fdm_c_lower_2d(False)
    c_wal, _ = fdm_c_lower_2d(True)
    c_nov_f, _ = fdm_c_lower_2d(False, dx=2.0e-5)
    c_base = 2 * EPS0 * r4_cf

    def eps_of(ratio: float) -> float:
        r4x = r4_cf * ratio
        return (r1_cf + ER * r4x) / (r1_cf + r4x)

    fdm2d = {
        "note": ("槽区 ζ=0 用 Neumann 镜像=部分电容近似，绝对 C 与共形闭式不可直比"
                 "（预声明 ≤1% 验证门不达，如实记录）；过孔效应只用同网格比值转移"),
        "c_lower_closed_per_m": c_base,
        "fdm_novia_dx10um_si": c_nov * EPS0,
        "fdm_novia_vs_closed_pct": round((c_nov * EPS0 / c_base - 1) * 100, 3),
        "fdm_novia_dx20um_si": c_nov_f * EPS0,
        "free_nodes_dx10um": n_nov,
        "wall_over_novia_ratio": round(c_wal / c_nov, 5),
        "eps_eff_wall_variant": round(eps_of(c_wal / c_nov), 5),
        "wall_correction_pp_on_ref": round((1 - eps_of(c_wal / c_nov) / eps_ref) * 100, 3),
        "physics_note": ("顶层地（x≥0.6245mm, V=0）与底地（V=0）间零场区屏蔽过孔位置"
                          "（x=±1.1245mm），栅栏效应被地内缘截断"),
    }

    # E4b' 3D 周期栅胞：离散过孔点估计
    try:
        q_nov, n3 = fdm_c_lower_3d(False)
        q_via, _ = fdm_c_lower_3d(True)
        ratio3 = q_via / q_nov
        fdm3d = {
            "free_nodes": n3,
            "note": "离散圆柱栅栏（r=0.15mm@2mm 间距）3D 周期栅胞，同网格比值转移",
            "ratio_via_over_novia": round(ratio3, 5),
            "eps_eff_via_variant": round(eps_of(ratio3), 5),
            "via_correction_pp_on_ref": round((1 - eps_of(ratio3) / eps_ref) * 100, 3),
        }
    except Exception as exc:
        fdm3d = {"error": repr(exc)}

    # E4c S21 相位去嵌独立旁证（#118 独立来源）
    try:
        b2_s21, resid, path = s21_deembed(b1_fit, band_med(b2_fit))
        # 直接量：phi_c 斜率×f0（去嵌后残段相位/频率）换回全路径相位斜率
        raw_total = band_med(b1_fit) * 0.0415103 + 0.5 * (band_med(b1_fit)
                      + band_med(b2_fit)) * 0.01 + b2_s21 * 0.0415103
        model_slope = (band_med(b1_fit) * 0.0415103 + 0.5 * (band_med(b1_fit)
                       + band_med(b2_fit)) * 0.01 + band_med(b2_fit) * 0.0415103)
        s21ev = {"beta2_s21_rad_per_m": round(b2_s21, 3),
                 "beta2_s21_vs_engine_pct": round((b2_s21 / band_med(b2_300) - 1) * 100, 3),
                 "beta2_s21_vs_fit_pct": round((b2_s21 / band_med(b2_fit) - 1) * 100, 3),
                 "unwrap_resid_rad_max": round(resid, 4),
                 "deembed_path_m": round(path, 5),
                 "adoption": "FAIL（超预声明 ≤0.7% 采信门，弃用）",
                 "path_slope_excess_pct": round((raw_total / model_slope - 1) * 100, 3),
                 "path_slope_total_rad": round(raw_total, 4),
                 "path_slope_model_rad": round(model_slope, 4),
                 "artifact_budget_note": ("u/i 平面错位 0.198mm × Zr/Z0 失配放大"
                                           "（port2 ρ=50/42.96=1.164 → d arg/dθ≈ρ/(ρ−1)=7.1）"
                                           "给 φ21 斜率 ~3-5e-11 rad/Hz ≈ 总斜率 1.0-1.6%"
                                           "——与路径超额同量级，S21 无法仲裁 83.0 vs 83.9")}
    except Exception as exc:
        s21ev = {"error": repr(exc)}

    e2_prof = (b2_300 * C0 / (2 * np.pi * FREQS)) ** 2
    e1_prof = (b1_300 * C0 / (2 * np.pi * FREQS)) ** 2
    ev["reference_E4"] = {
        "sensitivity": sens,
        "dispersion_eps2_range_pct_2p4_2p6": round(
            float((np.max(e2_prof[sel_mid]) / np.min(e2_prof[sel_mid]) - 1) * 100), 4),
        "dispersion_eps1_range_pct_2p4_2p6": round(
            float((np.max(e1_prof[sel_mid]) / np.min(e1_prof[sel_mid]) - 1) * 100), 4),
        "fdm2d": fdm2d,
        "fdm3d_via": fdm3d,
        "s21_deembed": s21ev,
    }

    with open(OUT_DIR / "evidence.json", "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1, default=float)
    print(json.dumps(ev, ensure_ascii=False, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
