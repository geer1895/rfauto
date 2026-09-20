"""c3 谐振 Q 时域提取 + S 参数稳态外推（确定性内核，纯离线零引擎）。

背景（#323 实测）：c3 族合规网格到 openEMS 能量判据 −60dB 需 ~10h+/模板（预算不可承受）；
归档 107.6ns 部分数据实证——能量尾部由弱负载环振模式主导（本模块从 port_ut 提取：
2.3314/2.4523/2.5342GHz，Q≈96/125/263，与「设计 Q 外推」差一个量级自洽，#323 的
12× 慢衰减由此定量闭合），而端口 S 响应的尾项贡献远早于能量判据收敛。本内核用
**环振多模尾项外推**替代「端口 S 全响应收敛判据」：从 port_ut/port_it 时间序列
提取主谐振模 (f0, α, Q)，按 S(ω,T) = S∞ + Σ_m c_m·exp((−α_m+j2π(f_m−ω/2π))·T)
的解析尾形状逐频线性最小二乘外推 t→∞，给出预估稳态 S21/S11、外推 vs 截断偏差、
留出（holdout）预测误差，以及「带心达到 ±tol 所需最短时长」——供
smoke_c3_filter_family 的「Q 外推置信门」在未达 −60dB 时提前判读。

方法（全部确定性，无随机源）：
① 环振段 = t ≥ t_excite（t_excite 来自引擎日志 excitation_s，禁止从数据瞎猜）；
② 模式检测：环振段 zero-pad ×8 rFFT 局部极大（限扫频带内），按幅值取前 n_modes 个，
   间隔 < 2×mask_halfwidth 的次峰合并；
③ 逐模 (f0, α)：**直接时域多模衰减拟合**（variable projection + Nelder-Mead，
   (A_m,B_m) 每步线性消去，只优化 α_m/ω_m）——不用包络/滤波提取：FFT-mask+hilbert
   包络的核宽 ~1/(2·hw)≈25ns 对 τ≈20ns 模式 α 系统偏 −14%（合成单模对照实测），
   直接拟合残差 ~3e-4（相对）且合成回收 α 偏差 ≤2%；span_db=8.686·α·窗时长
   （窗内衰减 dB，α 可辨识度；>100dB 的假峰=起振段干涉纹，丢弃）；
④ 窗阶梯：环振段均分 n_windows 个截断时刻 T_k，各窗部分 DFT（引擎同口径
   F(ω)=2·dt·Σ v·e^{−jωt}，dt=t[1]−t[0]；累计和一次算全部窗）→ 逐频
   [1, e^{(−α_m+j2π(f_m−f))T_k}] 基线性解 (S∞, {c_m})；
⑤ 置信面：外推 vs 截断偏差（dB）、holdout（前 n_windows−3 窗拟合预测末窗）、
   每模窗内衰减 span——三者全过预声明阈值方可提前判读（阈值在判读器侧写死：
   smoke_c3_filter_family.Q_EXTRAP_*，依据见其注释）。

归档实证（runs/smoke_c3_refix/interdigital/fdtd_partial，107.6ns，77.6 万步能量
−37.5dB 被预算 kill）：截断 S21 峰 2.4525GHz/−5.81dB；外推稳态 −5.77dB（偏差
+0.036dB）、S21@2.5GHz 偏差 −0.12dB、S11@带心偏差 +0.008dB；拟合残差 2.8e-4、
holdout@峰 2.5e-4；T_req(s21_peak 2.4525GHz ±5%)=52ns、带心 2.5GHz=25.2ns
（口径勘误：旧注误标"带心"，判读取 max=52ns 保守）。判读意义：截断态
已可信（0.04dB 量级），−60dB 能量判据对 S 参数可读性是过严判据；2h 处（~20ns）
模型预测偏差 ~2dB，门如实判红不许提前停，~4h（≥52ns 峰口径）出可信结论。

离线复算（归档/被 kill 轮，零仿真）：
  python scripts/c3_resonance_q_extract.py \
      --fdtd-dir runs/smoke_c3_refix/interdigital/fdtd_partial \
      --t-excite-ns 11.4593 --f-lo 2.25 --f-hi 2.75 --f-design-ghz 2.5 \
      --csv runs/smoke_c3_refix/interdigital/sparams_partial.csv \
      --out runs/smoke_c3_refix/interdigital/q_extrap.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

# 环振模式 mask 半宽（Hz）：峰间隔 >40MHz 时互相隔离（c3 归档三峰间隔 74/120MHz）
MASK_HALFWIDTH_HZ = 2.0e7
# FFT zero-pad 倍数（峰位插值分辨率）
FFT_PAD = 8


# ── 探针读入与端口合成（openEMS MSLPort 口径，ports.py ReadUIData）──────────────


def read_probe_series(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """port_ut/it 探针文件 → (t[s], v)（跳 % 头，两列数值）。"""
    a = np.loadtxt(str(path), comments="%")
    if a.ndim != 2 or a.shape[1] < 2 or a.shape[0] < 8:
        raise ValueError(f"探针文件不可解析或过短：{path}（shape={a.shape}）")
    return a[:, 0].astype(float), a[:, 1].astype(float)


def load_msl_probes(fdtd_dir: str | Path, port_numbers: tuple[int, ...] = (1, 2),
                    ) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """MSLPort 探针组合 → {port_nr: (t, u, i)}。

    openEMS MSLPort.ReadUIData 口径：uf_tot = U 文件序 [1]（B 行）时序、
    if_tot = 0.5·(I 文件 [0]+[1])（A+B 环流平均）——A/B/C 是测量面传播轴向
    三条电压线（meas−1/meas/meas+1），I 两条为相邻环流。
    """
    d = Path(fdtd_dir)
    out: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for nr in port_numbers:
        u_names = [d / f"port_ut_{nr}{s}" for s in "ABC"]
        i_names = [d / f"port_it_{nr}{s}" for s in "AB"]
        for p in u_names + i_names:
            if not p.exists():
                raise FileNotFoundError(f"缺探针文件：{p}")
        t, u_b = read_probe_series(u_names[1])
        _, i_a = read_probe_series(i_names[0])
        _, i_b = read_probe_series(i_names[1])
        n = min(t.size, i_a.size, i_b.size)          # kill 截断残行：截到公共最短
        out[nr] = (t[:n], u_b[:n], 0.5 * (i_a[:n] + i_b[:n]))
    return out


# ── 部分 DFT（引擎 DFT_time2freq 口径）与 S 参数 ────────────────────────────────


def dft_cumsum(t: np.ndarray, v: np.ndarray,
               freq_hz: np.ndarray) -> np.ndarray:
    """累计部分 DFT：返回 C 形 (n_t, n_f)，C[k] = 2·dt·Σ_{n≤k} v_n·e^{−j2πf·t_n}。

    与 openEMS utilities.DFT_time2freq('pulse') 同口径（单边谱 ×2×dt）；一次累计
    和即可取任意截断时刻的窗值（窗阶梯零重复计算）。比值型判读量对整体 2·dt 因子
    不敏感，保留因子以便与引擎 sparams 直接对拍。
    """
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    f = np.asarray(freq_hz, dtype=float)
    dt = float(t[1] - t[0])
    e = np.exp((-1j * 2.0 * np.pi) * np.outer(t, f))       # (n_t, n_f)
    return 2.0 * dt * np.cumsum(v[:, None] * e, axis=0)


def sparams_windows(t: np.ndarray, probes: dict[int, tuple[np.ndarray, np.ndarray]],
                    freq_hz: np.ndarray, t_ends: list[float | None],
                    z0: float = 50.0) -> dict[str, np.ndarray]:
    """端口 u/i 序列在窗阶梯 T_k 下的 S11/S21（引擎 CalcPort(ref=z0) 口径）。

    probes: {port_nr: (u, i)}（port1=激励口）。返回 {"s11": (K,n_f), "s21": (K,n_f)}
    （单端口时 "s11" 为 1×1 窗）。S = uf_ref/uf_inc，uf_inc=0.5(uf+z0·if)。
    """
    if 1 not in probes:
        raise ValueError("probes 须含激励口 port1")
    d1 = dft_cumsum(t, probes[1][0], freq_hz)
    c1 = dft_cumsum(t, probes[1][1], freq_hz)
    idx = [int(np.nonzero(t <= te)[0][-1]) if te is not None else t.size - 1
           for te in t_ends]
    uf1 = d1[idx]
    if1 = c1[idx]
    a1 = 0.5 * (uf1 + z0 * if1)
    out = {"s11": (0.5 * (uf1 - z0 * if1)) / a1}
    if 2 in probes:
        uf2 = dft_cumsum(t, probes[2][0], freq_hz)[idx]
        if2 = dft_cumsum(t, probes[2][1], freq_hz)[idx]
        out["s21"] = (0.5 * (uf2 - z0 * if2)) / a1
    return out


# ── 环振模式提取（f0/α/Q）───────────────────────────────────────────────────────


def extract_ring_modes(t: np.ndarray, u: np.ndarray, f_lo_hz: float, f_hi_hz: float,
                       t_excite_s: float, n_modes: int = 3,
                       mask_halfwidth_hz: float = MASK_HALFWIDTH_HZ,
                       fft_pad: int = FFT_PAD,
                       fit_delay_s: float = 2.0e-9) -> list[dict[str, float | int]]:
    """环振段主谐振模提取（确定性）：直接时域多模衰减拟合（variable projection）。

    模型 ur(t\') = Σ_m e^(−α_m t\')·(A_m cos ω_m t\' + B_m sin ω_m t\')，拟合窗
    t\' ≥ fit_delay_s（激励末端环振建立段不进拟合）。ω_m 初值=环振段 zero-pad FFT
    局部极大（带内、间隔 >2·mask_halfwidth 并主峰，按幅值取前 n_modes 个）；α 初值
    多起点；外层 scipy Nelder-Mead（固定输入/起点=确定性）只优化 (α_m, ω_m)，
    (A_m, B_m) 每步线性最小二乘消去——不经任何包络/滤波提取，无核宽平滑偏差
    （曾用 FFT-mask+hilbert 包络 ln 拟合，核宽 ~1/(2·hw)≈25ns 对 τ≈20ns 模式
    α 系统偏 −14%，合成单模对照实测）。

    返回按拟合均幅降序的 [{"f0_hz", "alpha_per_s", "q_loaded", "span_db",
    "n_fit"}]，span_db = 8.686·α_m·拟合窗时长（窗内该模衰减 dB，α 可辨识度度量）；
    扫频带内无可辨峰或拟合全无效时 ValueError。Q_L = π·f0/α。
    """
    from scipy.optimize import minimize

    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    ring = t >= float(t_excite_s)
    n_ring = int(np.count_nonzero(ring))
    if n_ring < 64:
        raise ValueError(f"环振段仅 {n_ring} 采样（<64）：t_excite_s 过晚或序列过短")
    tr = t[ring] - float(t_excite_s)
    ur = u[ring]
    dt = float(np.median(np.diff(tr)))
    nf = int(2 ** int(np.ceil(np.log2(n_ring * fft_pad))))
    spec = np.abs(np.fft.rfft(ur, nf))
    fr = np.fft.rfftfreq(nf, dt)
    inband = np.nonzero((fr >= f_lo_hz) & (fr <= f_hi_hz))[0]
    if inband.size < 8:
        raise ValueError("扫频带内 FFT 分辨率不足（频带太窄）")
    locs = [int(k) for k in inband[1:-1]
            if spec[k] > spec[k - 1] and spec[k] > spec[k + 1]]
    locs.sort(key=lambda k: -float(spec[k]))
    picked: list[int] = []
    for k in locs:                                   # 间隔过近的次峰并入主峰
        if all(abs(fr[k] - fr[j]) > 2.0 * mask_halfwidth_hz for j in picked):
            picked.append(k)
        if len(picked) >= int(n_modes):
            break
    if not picked:
        raise ValueError(f"扫频带 [{f_lo_hz / 1e9:.3g},{f_hi_hz / 1e9:.3g}]GHz 无谱峰")

    sel = tr >= float(fit_delay_s)
    tf = tr[sel]
    y = ur[sel]
    if tf.size < 16 * len(picked):
        raise ValueError(f"拟合窗仅 {tf.size} 采样（模式数 {len(picked)} 不足分辨）")
    t_end_w = float(tf[-1] - tf[0])
    a_scale = 4.0 / t_end_w                          # α 归一尺度（窗内衰 4 nat）
    w_scale = 2.0e6                                  # ω 偏移归一尺度（1MHz）
    omegas0 = np.array([2.0 * np.pi * fr[k] for k in picked])

    def _obj(theta: np.ndarray) -> float:
        alphas = theta[:len(picked)] * a_scale
        omegas = omegas0 + theta[len(picked):] * w_scale
        if np.any(alphas <= 0.0) or np.any(np.abs(omegas - omegas0) > 5.0 * w_scale):
            return 1e30
        cols = np.empty((tf.size, 2 * len(picked)))
        for m_i in range(len(picked)):
            e = np.exp(-alphas[m_i] * tf)
            cols[:, 2 * m_i] = e * np.cos(omegas[m_i] * tf)
            cols[:, 2 * m_i + 1] = e * np.sin(omegas[m_i] * tf)
        coef, *_ = np.linalg.lstsq(cols, y, rcond=None)
        return float(np.linalg.norm(cols @ coef - y))

    best = None
    for u0 in (1.0, 0.35, 3.0):                      # α 多起点（确定性）
        x0 = np.full(2 * len(picked), u0)
        res = minimize(_obj, x0, method="Nelder-Mead",
                       options={"maxiter": 20000, "xatol": 1e-9, "fatol": 1e-12})
        if best is None or res.fun < best.fun:
            best = res
    alphas = best.x[:len(picked)] * a_scale
    omegas = omegas0 + best.x[len(picked):] * w_scale
    modes: list[dict[str, float | int]] = []
    for m_i in range(len(picked)):
        f0 = float(omegas[m_i]) / (2.0 * np.pi)
        alpha = float(alphas[m_i])
        span_db = 8.686 * alpha * t_end_w
        # 窗内衰减 >100dB 的"模式"是起振段干涉纹（α 不可辨识，合成对照实测
        # α 可达 4e8 量级假峰），非物理谐振模，丢弃
        if not (alpha > 0.0 and f_lo_hz <= f0 <= f_hi_hz) or span_db > 100.0:
            continue
        modes.append({"f0_hz": f0, "alpha_per_s": alpha,
                      "q_loaded": float(np.pi * f0 / alpha),
                      "span_db": float(span_db),
                      "n_fit": int(tf.size)})
    if not modes:
        raise ValueError("谱峰存在但 α/f0 拟合全部无效（环振段过短或底噪淹没）")
    return modes


# ── 稳态外推（多模尾项线性最小二乘）─────────────────────────────────────────────


def _tail_basis(t_w: np.ndarray, modes: list[dict[str, float | int]],
                freq_hz: np.ndarray) -> list[np.ndarray]:
    """逐模尾基 B_m[k, f] = exp((−α_m + j2π(f_m−f))·T_k)。"""
    tw = np.asarray(t_w, dtype=float)
    cols = []
    for m in modes:
        cols.append(np.exp((-float(m["alpha_per_s"])
                            + 1j * 2.0 * np.pi * (float(m["f0_hz"])
                                                  - np.asarray(freq_hz, dtype=float)[None, :]))
                           * tw[:, None]))
    return cols


def _fit_window_ladder(t_w: np.ndarray, sw: np.ndarray,
                       modes: list[dict[str, float | int]],
                       freq_hz: np.ndarray) -> dict[str, np.ndarray]:
    """逐频 [1, B_1..B_M] 基线性解 (S∞, {c_m})；返回 s_inf/c/resid_rel（对 |S| 窗最大值）。"""
    k_w = sw.shape[0]
    cols = _tail_basis(t_w, modes, freq_hz)
    nf = np.asarray(freq_hz).size
    s_inf = np.zeros(nf, dtype=complex)
    c = np.zeros((nf, len(cols)), dtype=complex)
    resid = np.zeros(nf)
    for k in range(nf):
        amat = np.column_stack([np.ones(k_w), *[col[:, k] for col in cols]])
        y = sw[:, k]
        sol, *_ = np.linalg.lstsq(amat, y, rcond=None)
        s_inf[k] = sol[0]
        c[k] = sol[1:]
        denom = float(np.max(np.abs(y)))
        resid[k] = float(np.max(np.abs(amat @ sol - y))) / (denom if denom > 0 else 1.0)
    return {"s_inf": s_inf, "c": c, "resid_rel": resid}


def _tail_at(t_eval: float, c_row: np.ndarray,
             modes: list[dict[str, float | int]], f_hz: float) -> complex:
    tot = 0j
    for mi, m in enumerate(modes):
        tot = tot + c_row[mi] * np.exp(
            (-float(m["alpha_per_s"])
             + 1j * 2.0 * np.pi * (float(m["f0_hz"]) - f_hz)) * float(t_eval))
    return complex(tot)


def extrapolate_steady(t: np.ndarray, probes: dict[int, tuple[np.ndarray, np.ndarray]],
                       freq_hz: np.ndarray, modes: list[dict[str, float | int]],
                       t_excite_s: float, n_windows: int = 12,
                       z0: float = 50.0) -> dict[str, object]:
    """窗阶梯外推 → 截断态/外推稳态 S 与逐频残差（纯函数）。

    窗阶梯 = [t_excite, t_end] 均分 n_windows 个截断时刻（含 t_end）；
    holdout = 前 n_windows−3 窗拟合预测末窗（末窗不参与拟合的独立性检验）。
    """
    if int(n_windows) < len(modes) + 5:
        raise ValueError(f"n_windows={n_windows} 对 {len(modes)} 模不足"
                         "（须 ≥ n_modes+5，保证全拟合与 holdout 均可解）")
    t_ends = [float(t_excite_s) + (float(t[-1]) - float(t_excite_s)) * (k + 1) / int(n_windows)
              for k in range(int(n_windows))]
    sw = sparams_windows(t, probes, freq_hz, t_ends, z0=z0)
    t_w = np.array(t_ends, dtype=float)
    out: dict[str, object] = {"t_windows_s": t_w, "n_windows": int(n_windows)}
    for name in ("s11", "s21"):
        if name not in sw:
            continue
        mat = sw[name]
        fit = _fit_window_ladder(t_w, mat, modes, freq_hz)
        n_hold = max(int(n_windows) - 3, 4)
        fit_h = _fit_window_ladder(t_w[:n_hold], mat[:n_hold], modes, freq_hz)
        cols_h = _tail_basis(t_w, modes, freq_hz)
        pred_last = np.zeros(np.asarray(freq_hz).size, dtype=complex)
        nf = np.asarray(freq_hz).size
        for k in range(nf):
            row = np.concatenate([[fit_h["s_inf"][k]], fit_h["c"][k]])
            basis = np.column_stack([np.ones(len(t_w)),
                                     *[col[:, k] for col in cols_h]])
            pred_last[k] = (basis @ row)[len(t_w) - 1]
        holdout_rel = np.abs(pred_last - mat[-1]) / np.maximum(np.abs(mat[-1]), 1e-300)
        out[name] = {"trunc": mat[-1], "s_inf": fit["s_inf"],
                     "resid_rel": fit["resid_rel"], "c": fit["c"],
                     "windows": mat, "holdout_rel": holdout_rel,
                     "n_holdout_windows": n_hold}
    return out


def min_duration_s(s_inf: complex, c_row: np.ndarray,
                   modes: list[dict[str, float | int]], f_hz: float,
                   tol_rel: float, t_start_s: float, t_end_s: float,
                   t_max_s: float | None = None,
                   n_grid: int = 4000) -> float | None:
    """带心达到 |尾项| ≤ tol_rel·|S∞| 所需最短时长（对拟合尾模型解，log 栅格扫描）。

    t_max_s 缺省 = max(4·t_end, t_start+4/(最慢 α))；栅格内不满足 → None（如实不可达）。
    """
    t_hi = float(t_max_s) if t_max_s is not None else max(
        4.0 * float(t_end_s),
        float(t_start_s) + 4.0 / min(float(m["alpha_per_s"]) for m in modes))
    grid = np.geomspace(max(float(t_start_s), 1e-12), t_hi, int(n_grid))
    target = float(tol_rel) * abs(complex(s_inf))
    if target <= 0.0:
        return None
    vals = np.array([abs(_tail_at(tv, c_row, modes, f_hz)) for tv in grid])
    idx = np.nonzero(vals <= target)[0]
    return float(grid[idx[0]]) if idx.size else None


# ── 报告编排（判读器/CLI 共用）──────────────────────────────────────────────────


def q_extrap_report(t: np.ndarray, probes: dict[int, tuple[np.ndarray, np.ndarray]],
                    freq_hz: np.ndarray, modes: list[dict[str, float | int]],
                    t_excite_s: float, f_design_hz: float | None = None,
                    n_windows: int = 12, z0: float = 50.0,
                    tol_rel: float = 0.05) -> dict[str, object]:
    """完整报告：模式表 + 关键频点（S21 峰/设计带心）的外推 vs 截断 + T_req。"""
    ext = extrapolate_steady(t, probes, freq_hz, modes, t_excite_s,
                             n_windows=n_windows, z0=z0)
    s21 = ext["s21"]
    s21_inf = s21["s_inf"]                          # type: ignore[index]
    s21_tr = s21["trunc"]                           # type: ignore[index]
    f = np.asarray(freq_hz, dtype=float)
    i_pk = int(np.argmax(20.0 * np.log10(np.abs(s21_tr) + 1e-300)))
    keys: dict[str, dict[str, object]] = {}
    t_end = float(t[-1])
    i_f0 = (int(np.argmin(np.abs(f - float(f_design_hz))))
            if f_design_hz is not None else int(i_pk))
    for name, curve, fi in (("s21_peak", "s21", int(i_pk)),
                            ("s21_f0", "s21", i_f0),
                            ("s11_f0", "s11", i_f0)):
        if curve not in ext:
            continue
        arr = ext[curve]                            # type: ignore[index]
        inf_v = complex(arr["s_inf"][fi])           # type: ignore[index]
        tr_v = complex(arr["trunc"][fi])            # type: ignore[index]
        dev_db = float(20.0 * np.log10(abs(inf_v) + 1e-300)
                       - 20.0 * np.log10(abs(tr_v) + 1e-300))
        t_req = min_duration_s(inf_v, arr["c"][fi], modes, float(f[fi]),  # type: ignore[index]
                               tol_rel, float(t_excite_s), t_end)
        keys[name] = {
            "freq_hz": float(f[fi]),
            "s_trunc_db": float(20.0 * np.log10(abs(tr_v) + 1e-300)),
            "s_inf_db": float(20.0 * np.log10(abs(inf_v) + 1e-300)),
            "dev_db": dev_db,
            "resid_rel": float(arr["resid_rel"][fi]),        # type: ignore[index]
            "holdout_rel": float(arr["holdout_rel"][fi]),    # type: ignore[index]
            "tol_rel": float(tol_rel),
            "min_duration_s": t_req,
            "min_duration_satisfied": bool(t_req is not None and t_req <= t_end),
        }
    report: dict[str, object] = {
        "method": "ringdown_multimode_tail_extrapolation",
        "t_excite_s": float(t_excite_s), "t_end_s": t_end,
        "t_end_ns": t_end * 1e9, "n_windows": int(n_windows), "z0": float(z0),
        "tol_rel": float(tol_rel),
        "excitation_covered_by_data": bool(t_end >= float(t_excite_s)),
        "modes": [{"f0_ghz": float(m["f0_hz"]) / 1e9,
                   "alpha_per_ns": float(m["alpha_per_s"]) * 1e-9,
                   "q_loaded": float(m["q_loaded"]),
                   "span_db": float(m["span_db"]), "n_fit": int(m["n_fit"])}
                  for m in modes],
        "f_peak_hz": float(f[i_pk]),
        "keys": keys,
        "s21_trunc_db": (20.0 * np.log10(np.abs(s21_tr) + 1e-300)).tolist(),
        "s21_inf_db": (20.0 * np.log10(np.abs(s21_inf) + 1e-300)).tolist(),
        "freq_ghz": (f / 1e9).tolist(),
    }
    if "s11" in ext:
        s11 = ext["s11"]                            # type: ignore[assignment]
        report["s11_trunc_db"] = (20.0 * np.log10(np.abs(s11["trunc"]) + 1e-300)).tolist()  # type: ignore[index]
        report["s11_inf_db"] = (20.0 * np.log10(np.abs(s11["s_inf"]) + 1e-300)).tolist()    # type: ignore[index]
    return report


# ── 置信判读（阈值由判读器侧预声明传入，本函数只做机械比较）─────────────────────


def q_extrap_confidence(rep: dict[str, object], dev_db_max: float,
                        holdout_rel_max: float, span_db_min: float,
                        ) -> dict[str, object]:
    """Q 外推置信判读：外推稳态与截断态偏差 + holdout + 模式 span 三面齐过 → ok。

    阈值语义与依据由调用方（smoke_c3_filter_family.Q_EXTRAP_*）预声明；
    任一关键频点缺项按不过处置（不凑绿）。
    """
    keys = rep.get("keys")
    modes = rep.get("modes")
    checks: dict[str, object] = {}
    reasons: list[str] = []
    if not isinstance(keys, dict) or not keys:
        return {"ok": False, "reasons": ["报告缺 keys（无关键频点可判）"], "checks": {}}
    devs = [float(k["dev_db"]) for k in keys.values()]          # type: ignore[union-attr]
    holds = [float(k["holdout_rel"]) for k in keys.values()]    # type: ignore[union-attr]
    checks["dev_db_max_obs"] = max(abs(v) for v in devs)
    checks["holdout_rel_max_obs"] = max(holds)
    checks["dev_db_max"] = float(dev_db_max)
    checks["holdout_rel_max"] = float(holdout_rel_max)
    spans = [float(m["span_db"]) for m in modes] if isinstance(modes, list) else []
    if not spans:
        return {"ok": False, "reasons": ["报告缺 modes"], "checks": checks}
    checks["span_db_min_obs"] = min(spans)
    checks["span_db_min"] = float(span_db_min)
    checks["n_modes"] = len(spans)
    if checks["dev_db_max_obs"] > float(dev_db_max):            # type: ignore[arg-type]
        reasons.append(f"外推 vs 截断偏差 {checks['dev_db_max_obs']:.3f}dB > 门 "
                       f"{dev_db_max}dB")
    if checks["holdout_rel_max_obs"] > float(holdout_rel_max):  # type: ignore[arg-type]
        reasons.append(f"holdout 预测误差 {checks['holdout_rel_max_obs']:.3f} > 门 "
                       f"{holdout_rel_max}")
    if min(spans) < float(span_db_min):
        reasons.append(f"最弱模包络 span {min(spans):.1f}dB < 门 {span_db_min}dB "
                       "（α 不可辨）")
    return {"ok": not reasons, "reasons": reasons, "checks": checks}


# ── 离线 CLI（归档/被 kill 轮零仿真复算）────────────────────────────────────────


def _read_sparams_csv(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head = rows[0][:5]
    if head != ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"]:
        raise ValueError(f"sparams csv 表头不符：{head}")
    arr = np.array([[float(x) for x in r[:5]] for r in rows[1:] if r])
    return arr[:, 0], arr[:, 1] + 1j * arr[:, 2], arr[:, 3] + 1j * arr[:, 4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--fdtd-dir", required=True,
                        help="探针目录（port_ut_*/port_it_* 所在，fdtd/ 或 fdtd_partial/）")
    parser.add_argument("--t-excite-ns", type=float, required=True,
                        help="激励时长 ns（引擎日志 excitation_s，勿从数据猜）")
    parser.add_argument("--f-lo", type=float, default=2.25, help="扫频下沿 GHz")
    parser.add_argument("--f-hi", type=float, default=2.75, help="扫频上沿 GHz")
    parser.add_argument("--n-freq", type=int, default=401)
    parser.add_argument("--f-design-ghz", type=float, default=2.5, help="设计带心 GHz")
    parser.add_argument("--nrts-taken", type=int, default=None,
                        help="该数据实际步数（仅记录进报告，无判读作用）")
    parser.add_argument("--n-modes", type=int, default=3)
    parser.add_argument("--n-windows", type=int, default=12)
    parser.add_argument("--tol-rel", type=float, default=0.05,
                        help="带心置信容差（±5%%=0.42dB 量级）")
    parser.add_argument("--z0", type=float, default=50.0)
    parser.add_argument("--csv", default=None, help="引擎 sparams(_partial).csv 对拍（可选）")
    parser.add_argument("--out", default=None, help="报告 JSON 落盘路径（可选）")
    args = parser.parse_args(argv)

    probes = load_msl_probes(args.fdtd_dir)
    t = probes[1][0]
    freq = np.linspace(args.f_lo * 1e9, args.f_hi * 1e9, args.n_freq)
    modes = extract_ring_modes(t, probes[1][1], args.f_lo * 1e9, args.f_hi * 1e9,
                               args.t_excite_ns * 1e-9, n_modes=args.n_modes)
    rep = q_extrap_report(t, {k: (u, i) for k, (tt, u, i) in probes.items()},
                          freq, modes, args.t_excite_ns * 1e-9,
                          f_design_hz=args.f_design_ghz * 1e9,
                          n_windows=args.n_windows, z0=args.z0,
                          tol_rel=args.tol_rel)
    rep["fdtd_dir"] = str(args.fdtd_dir)            # type: ignore[assignment]
    if args.nrts_taken is not None:
        rep["nrts_taken"] = int(args.nrts_taken)    # type: ignore[assignment]
    if args.csv:
        fc, _s11c, s21c = _read_sparams_csv(args.csv)
        if fc.size == freq.size:
            d21 = float(np.max(np.abs(20 * np.log10(np.abs(s21c) + 1e-300)
                                      - np.asarray(rep["s21_trunc_db"]))))   # type: ignore[arg-type]
            rep["csv_crosscheck_max_db"] = d21       # type: ignore[assignment]
    print("modes:", json.dumps(rep["modes"], ensure_ascii=False), flush=True)
    print("keys:", json.dumps(rep["keys"], ensure_ascii=False, indent=1), flush=True)
    if "csv_crosscheck_max_db" in rep:
        print(f"csv 对拍 max|ΔS21|dB = {rep['csv_crosscheck_max_db']:.4f}", flush=True)
    if args.out:
        Path(args.out).write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report: {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
