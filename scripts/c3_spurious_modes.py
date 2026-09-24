"""c3 零衰减伪模判别与物理模提取（纯离线零仿真；判据预声明
runs/c3_sirbpf_spurious/criteria.md，先判据后实现）。

背景（内部审计登记）：sir_bpf stage1 帽停判读 FAIL——三模中两个
α≈0（5.5e−5 与 5.1e−14 /ns，Q≈1.5e5 与 1.7e14）"零衰减伪模"使 span 门与
stage2 预算输入全废（α_min≈0 → rate≈0 → 加窗估计不可达）。本模块裁决其身份
并给判读链正确的处理路径。

裁决（criteria §一/§二，判据先行）：
- **材料 Q 帽硬判据**：平面微带器件一切谐振模（含被困模 #344 语境）的场必然
  穿过有耗基板 → Q_unloaded ≤ 1/tanδ ≈ 270（rogers4350b tanδ=0.0037）；
  取 5× 裕量 Q_MAT_CAP=1351 覆盖 datasheet 频漂/填充因子——**Q_L > 帽的模
  物理上不可能是本器件谐振模**（被困模假设一并否决：被困只解除端口负载，
  不解除介质损耗）。
- 归因标注（不影响处理）：跨窗重拟合 α 散布 >10× 或 f0 漂移 >30MHz →
  拟合退化（A1：有限窗截断正弦干涉被 NM 吸收成零 α 分量）；α 稳定但窗内
  不衰 → 真实非衰减分量嫌疑（A2：计算域盒模，MUR 掠入射吸收弱）。
  sir_bpf 实测（runs/c3_sirbpf_spurious/spurious_verdict.json）：两候选模
  α 跨 12 窗散布 15 个量级、f0 随窗长系统性游走（2.72→2.68→2.65GHz）、
  激励口与输出口独立拟合的"同区模"频差 14MHz（非驻定谐振）、幅值 0.9~3%、
  带外且 2.654GHz 与域 (0,3)/(3,0) 盒模估算一致——A1 为主、不排除 A2 混入。
- **物理模**：Q_L ≤ 帽（基准外推/置信门/预算输入面）；**伪模不进收敛门、
  不进尾外推基**（零 α 尾基与常数字共线 → S∞ 不可辨）。
- **缺省不变铁律**：无伪模形态（全部模 Q_L ≤ 帽）split_physical_refit 返回
  None，判读链零改动（既有 38 判读测试全绿钉）。
- **α→0 分支合成回收钉**（#118 纪律，先合成后真数据）：物理+零衰减双模注入
  → refine_modes_vp 紧收敛 VP 回收物理模 α/ω 相对误差 ≤1%（既有内核 NM 松
  收敛实测 2.6~6.9% 不可达标——紧收敛（xatol 1e-12/fatol 1e-18/maxiter 2e5）
  机器精度回收；真数据 α 仅移 0.1%，证据见 builder 报告）。

离线复算（真数据判别报告，零仿真）：
  python scripts/c3_spurious_modes.py \
      --work-dir runs/smoke_c3_fullcurve/sir_bpf/stage1 \
      --out runs/c3_sirbpf_spurious/spurious_verdict.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (REPO / "src", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from c3_resonance_q_extract import MASK_HALFWIDTH_HZ  # noqa: E402

# ── 预声明常量（criteria.md 同源，改判据先改 criteria 再改这里）─────────────────
TAN_D = 0.0037                 # rogers4350b datasheet（configs/materials.yaml）
Q_MAT_MARGIN = 5.0             # 裕量：datasheet 频漂 + 填充因子 + 场分布不确定性
Q_MAT_CAP = Q_MAT_MARGIN / TAN_D          # 1351.4（材料 Q 帽，硬判据）
SPAN_PHYS_MIN_DB = 3.0         # 预算输入面 α 可辨下界（置信门 20dB 总门不动）
ALPHA_DEGEN_SPREAD_MAX = 10.0  # C3：跨窗 α 散布 >10× → 拟合退化（A1）
F0_DEGEN_DRIFT_MHZ_MAX = 30.0  # C3：f0 漂移 >3×FFT 峰分辨（~10MHz）→ 退化
MODE_MATCH_TOL_HZ = 2.0 * MASK_HALFWIDTH_HZ   # 跨窗配对容差=拾取并峰阈（40MHz）
REFINE_FIT_DELAY_S = 2.0e-9    # 环振建立段不进拟合（内核同口径）
REFINE_MAXITER = 200_000
REFINE_XATOL = 1e-12
REFINE_FATOL = 1e-18
REFINE_OMEGA_STEPS = 20.0      # ω 搜索半径 = ±20·w_scale（±6.4MHz）：泄漏可把
                               # FFT 拾取拉偏 ~5MHz，精化须能走到真峰；目标函数
                               # 峰宽 ~1/T（≥38MHz），半径内无邻模（间隔 ≥150MHz）
BOX_MODE_EPS_GRID = (1.0, 1.1, 1.2, 1.3, 1.5, 2.0, 2.5, 3.0, 3.66)
BOX_MODE_TOL_REL = 0.02


# ── 分类（材料 Q 帽硬判据；纯函数）──────────────────────────────────────────────

def classify_modes(modes_report: list[dict[str, Any]],
                   q_mat_cap: float = Q_MAT_CAP) -> dict[str, Any]:
    """报告形模表二分（criteria §三）：Q_L ≤ 帽 → physical，> 帽 → spurious。

    modes_report 元素含 f0_ghz/alpha_per_ns/q_loaded/span_db/n_fit（内核报告
    口径）。changed=True 表示判读链须切物理模基（无伪模 → changed=False，
    缺省路径零改动依据）。
    """
    physical: list[dict[str, Any]] = []
    spurious: list[dict[str, Any]] = []
    for m in modes_report:
        q_raw = m.get("q_loaded")
        q = math.inf if q_raw is None else float(q_raw)
        (physical if q <= float(q_mat_cap) else spurious).append(dict(m))
    return {"changed": bool(spurious), "physical": physical, "spurious": spurious,
            "q_mat_cap": float(q_mat_cap),
            "basis": (f"Q_L = π·f0/α > Q_MAT_CAP={float(q_mat_cap):.0f}"
                      f"（tanδ={TAN_D}×{Q_MAT_MARGIN:g} 裕量）→ 材料帽以上非器件模"
                      "（criteria §一推论：被困模不解除介质损耗，一并否决）")}


def kernel_modes_from_report(modes_report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """报告形模表 → 内核 extract_ring_modes 形（q_extrap_report 输入面）。"""
    return [{"f0_hz": float(m["f0_ghz"]) * 1e9,
             "alpha_per_s": float(m["alpha_per_ns"]) * 1e9,
             "q_loaded": float(m["q_loaded"]),
             "span_db": float(m["span_db"]), "n_fit": int(m["n_fit"])}
            for m in modes_report]


# ── VP 紧收敛精化（#338 时域直接拟合，合成回收钉 ≤1% 的落点）────────────────────

def refine_modes_vp(t: np.ndarray, u: np.ndarray, t_excite_s: float,
                    modes: list[dict[str, Any]],
                    fit_delay_s: float = REFINE_FIT_DELAY_S,
                    ) -> list[dict[str, Any]]:
    """给定初值模表的 (α_m, ω_m) 紧收敛 VP 精化（可确定性重放）。

    模型 ur(t') = Σ_m e^(−α_m t')·(A_m cos ω_m t' + B_m sin ω_m t')，(A_m,B_m)
    每步线性最小二乘消去，外层 Nelder-Mead（多起点 ×紧收敛，固定输入/起点=
    确定性）只优化 (α_m, ω_m)；ω 限初值 ±20·w_scale（内核 ±5，本器有意放宽
    4×——跨窗粗定位需要）。
    与内核 extract_ring_modes 的差别只在优化器收敛设定（松收敛合成回收实测
    2.6~6.9%；紧收敛机器精度）。模数/频率顺序与输入一致；不重拾谱峰。
    """
    from scipy.optimize import minimize

    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    ring = t >= float(t_excite_s)
    tr = t[ring] - float(t_excite_s)
    ur = u[ring]
    if tr.size < 16 * max(len(modes), 1):
        raise ValueError(f"环振段仅 {tr.size} 采样：不足以精化 {len(modes)} 模")
    sel = tr >= float(fit_delay_s)
    tf = tr[sel]
    y = ur[sel]
    t_end_w = float(tf[-1] - tf[0])
    a_scale = 4.0 / t_end_w
    w_scale = 2.0e6
    nm = len(modes)
    omegas0 = np.array([2.0 * np.pi * float(m["f0_hz"]) for m in modes])

    def _obj(theta: np.ndarray) -> float:
        alphas = theta[:nm] * a_scale
        omegas = omegas0 + theta[nm:] * w_scale
        if (np.any(alphas <= 0.0)
                or np.any(np.abs(omegas - omegas0) > REFINE_OMEGA_STEPS * w_scale)):
            return 1e30
        cols = np.empty((tf.size, 2 * nm))
        for m_i in range(nm):
            e = np.exp(-alphas[m_i] * tf)
            cols[:, 2 * m_i] = e * np.cos(omegas[m_i] * tf)
            cols[:, 2 * m_i + 1] = e * np.sin(omegas[m_i] * tf)
        coef, *_ = np.linalg.lstsq(cols, y, rcond=None)
        return float(np.linalg.norm(cols @ coef - y))

    best = None
    for u0 in (0.35, 1.0, 3.0):                      # α 起点缩放（确定性）
        res = minimize(_obj, np.full(2 * nm, u0), method="Nelder-Mead",
                       options={"maxiter": REFINE_MAXITER, "maxfev": REFINE_MAXITER,
                                "xatol": REFINE_XATOL, "fatol": REFINE_FATOL})
        if best is None or res.fun < best.fun:
            best = res
    alphas = best.x[:nm] * a_scale
    omegas = omegas0 + best.x[nm:] * w_scale
    out: list[dict[str, Any]] = []
    for m_i in range(nm):
        f0 = float(omegas[m_i]) / (2.0 * np.pi)
        alpha = float(alphas[m_i])
        out.append({"f0_hz": f0, "alpha_per_s": alpha,
                    "q_loaded": float(np.pi * f0 / alpha) if alpha > 0 else math.inf,
                    "span_db": float(8.686 * alpha * t_end_w),
                    "n_fit": int(tf.size),
                    "resid": float(best.fun)})
    return out


# ── 物理模基重外推 + 分流薄接线（runner 消费面）────────────────────────────────

def budget_alpha_min(modes_refined: list[dict[str, Any]],
                     span_min_db: float = SPAN_PHYS_MIN_DB) -> float | None:
    """预算输入 α_min（精化物理模中 span ≥ 门的最小 α；单位 1/ns）。

    α 不可辨（全部 span < 门）→ None（预算如实缺失，criteria §三；
    置信门 20dB 总门不动——本地板只管"α 有没有数作预算输入"）。
    """
    ok = []
    for m in modes_refined:
        span_raw = m.get("span_db")
        span_f = 0.0 if span_raw is None else float(span_raw)
        if span_f >= float(span_min_db):
            ok.append(float(m["alpha_per_s"]) * 1e-9)
    return min(ok) if ok else None


def split_physical_refit(fdtd_dir: str, freq_hz: np.ndarray, t_excite_s: float,
                         f_design_hz: float, qrep_modes: list[dict[str, Any]],
                         refine: bool = True,
                         fit_delay_s: float = REFINE_FIT_DELAY_S,
                         n_windows: int = 12, z0: float = 50.0,
                         tol_rel: float = 0.05,
                         ) -> dict[str, Any] | None:
    """分类 + 物理模基重外推（判读链薄接线入口）。

    无伪模 → None（调用方零改动）；有伪模 → doc（physical/spurious 分类、
    modes_all 全模留痕、modes_physical_kernel 精化后物理模、report_physical
    物理模基外推报告）。物理模空或外推不可判 → refit_ok=False（调用方保留
    原全模报告，判读如实不过 #122）。
    """
    from c3_resonance_q_extract import load_msl_probes, q_extrap_report

    cls = classify_modes(list(qrep_modes))
    if not cls["changed"]:
        return None
    modes_phys = kernel_modes_from_report(cls["physical"])
    rep: dict[str, Any] | None = None
    if modes_phys:
        probes_all = load_msl_probes(fdtd_dir)
        t = probes_all[1][0]
        if refine:
            modes_phys = refine_modes_vp(t, probes_all[1][1], t_excite_s,
                                         modes_phys, fit_delay_s=fit_delay_s)
        probes = {k: (uu, ii) for k, (_tt, uu, ii) in probes_all.items()}
        rep = q_extrap_report(t, probes, freq_hz, modes_phys, t_excite_s,
                              f_design_hz=f_design_hz, n_windows=n_windows,
                              z0=z0, tol_rel=tol_rel)
        rep["fdtd_dir"] = str(fdtd_dir)
    return {"changed": True, "physical": cls["physical"], "spurious": cls["spurious"],
            "q_mat_cap": cls["q_mat_cap"], "basis": cls["basis"],
            "modes_all": list(qrep_modes), "modes_physical_kernel": modes_phys,
            "report_physical": rep, "refit_ok": rep is not None}


# ── 判别证据面（C3/C4/C5；builder 消费，纯离线）────────────────────────────────

def mode_amplitudes(t: np.ndarray, u: np.ndarray, t_excite_s: float,
                    modes: list[dict[str, Any]],
                    fit_delay_s: float = REFINE_FIT_DELAY_S) -> dict[str, Any]:
    """固定 (α,ω) 线性幅值解（C4 幅值占比；判据面无推断成分）。"""
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    sel = (t - float(t_excite_s)) >= float(fit_delay_s)
    tf = t[sel] - float(t_excite_s)
    y = u[sel]
    nm = len(modes)
    cols = np.empty((tf.size, 2 * nm))
    for m_i, m in enumerate(modes):
        e = np.exp(-float(m["alpha_per_s"]) * tf)
        w = 2.0 * np.pi * float(m["f0_hz"])
        cols[:, 2 * m_i] = e * np.cos(w * tf)
        cols[:, 2 * m_i + 1] = e * np.sin(w * tf)
    coef, *_ = np.linalg.lstsq(cols, y, rcond=None)
    resid = cols @ coef - y
    amps = [float(np.hypot(coef[2 * m_i], coef[2 * m_i + 1])) for m_i in range(nm)]
    amax = max(amps) if amps else 0.0
    return {"modes": [{"f0_ghz": float(m["f0_hz"]) / 1e9, "amp": a,
                       "rel_to_max": (a / amax if amax > 0 else None)}
                      for m, a in zip(modes, amps, strict=True)],
            "resid_rms": float(np.sqrt(np.mean(resid ** 2))) if y.size else None,
            "signal_rms": float(np.sqrt(np.mean(y ** 2))) if y.size else None}


def is_degenerate_fit(spread_ratio: float | None,
                      f0_drift_mhz: float | None) -> bool:
    """C3 退化判定（纯函数）：α 散布 >10× 或 f0 漂移 >30MHz → 拟合退化（A1）。

    spread_ratio=None（变体全缺席/全不可配）不算退化证据（缺席本身在 n_absent
    列账，判读主路径由材料 Q 帽把守）。
    """
    if spread_ratio is not None and spread_ratio > ALPHA_DEGEN_SPREAD_MAX:
        return True
    return bool(f0_drift_mhz is not None
                and f0_drift_mhz > F0_DEGEN_DRIFT_MHZ_MAX)


def cross_window_stability(t: np.ndarray, u: np.ndarray, f_lo_hz: float,
                           f_hi_hz: float, t_excite_s: float,
                           base_modes_report: list[dict[str, Any]],
                           delays_ns: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0),
                           fracs: tuple[float, ...] = (0.6, 0.8, 1.0),
                           match_tol_hz: float = MODE_MATCH_TOL_HZ,
                           t_end_s: float | None = None) -> dict[str, Any]:
    """C3 跨窗稳定性：延迟×长度变体重拟合（内核松收敛同径），逐基模配对 α/f0。

    配对容差 = 拾取并峰阈 2×MASK_HALFWIDTH（> 容差 = 该变体无对应峰，计缺席
    ——本身即不稳证据）。degenerate_fit = α 散布 > ALPHA_DEGEN_SPREAD_MAX 或
    f0 漂移 > F0_DEGEN_DRIFT_MHZ_MAX（A1 拟合退化指纹）。
    """
    from c3_resonance_q_extract import extract_ring_modes

    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    t_end = float(t_end_s) if t_end_s is not None else float(t[-1])
    variants: list[dict[str, Any]] = []
    for d_ns in delays_ns:
        for fr in fracs:
            t_end_w = float(t_excite_s) + (t_end - float(t_excite_s)) * float(fr)
            m = t <= t_end_w
            try:
                got = extract_ring_modes(t[m], u[m], float(f_lo_hz), float(f_hi_hz),
                                         float(t_excite_s),
                                         fit_delay_s=float(d_ns) * 1e-9)
            except ValueError:
                got = []
            variants.append({"delay_ns": float(d_ns), "frac": float(fr),
                             "t_end_ns": round((t_end_w - float(t_excite_s)) * 1e9, 3),
                             "modes": [{"f0_ghz": float(mo["f0_hz"]) / 1e9,
                                        "alpha_per_ns": float(mo["alpha_per_s"]) * 1e-9}
                                       for mo in got]})
    per_mode: list[dict[str, Any]] = []
    for bm in base_modes_report:
        f_b = float(bm["f0_ghz"]) * 1e9
        a_matched: list[float] = []
        f_matched: list[float] = []
        absent = 0
        for v in variants:
            cands = [mo for mo in v["modes"]
                     if abs(mo["f0_ghz"] * 1e9 - f_b) <= float(match_tol_hz)]
            if not cands:
                absent += 1
                continue
            nearest = min(cands, key=lambda mo: abs(mo["f0_ghz"] * 1e9 - f_b))
            a_matched.append(float(nearest["alpha_per_ns"]))
            f_matched.append(float(nearest["f0_ghz"]) * 1e9)
        if a_matched and min(a_matched) > 0.0:
            spread: float | None = max(a_matched) / min(a_matched)
        elif a_matched:
            spread = math.inf
        else:
            spread = None
        drift = (max(f_matched) - min(f_matched)) / 1e6 if f_matched else None
        degen = is_degenerate_fit(spread, drift)
        per_mode.append({
            "f0_ghz_base": float(bm["f0_ghz"]),
            "q_loaded_base": float(bm.get("q_loaded") or math.inf),
            "n_variants": len(variants), "n_matched": len(a_matched),
            "n_absent": absent,
            "alpha_matched_per_ns": a_matched,
            "alpha_spread_ratio": spread,
            "f0_matched_ghz": sorted({round(f / 1e9, 4) for f in f_matched}),
            "f0_drift_mhz": (round(drift, 3) if drift is not None else None),
            "degenerate_fit": degen})
    return {"n_variants": len(variants), "match_tol_hz": float(match_tol_hz),
            "variants": variants, "per_mode": per_mode,
            "thresholds": {"alpha_spread_max": ALPHA_DEGEN_SPREAD_MAX,
                           "f0_drift_mhz_max": F0_DEGEN_DRIFT_MHZ_MAX}}


def box_mode_candidates(f_target_ghz: float, lx_m: float = 0.120,
                        ly_m: float = 0.120, tol_rel: float = BOX_MODE_TOL_REL,
                        eps_grid: tuple[float, ...] = BOX_MODE_EPS_GRID,
                        i_max: int = 5, j_max: int = 5) -> list[dict[str, Any]]:
    """C5 域侧向盒模估算旁证：f=(c/2√εeff)·√((i/Lx)²+(j/Ly)²)，|dev|≤tol 候选。

    估算粗糙（z 向堆叠非均匀/边界混合 MUR-PML-PEC）——只作旁证不进门
    （criteria §二 C5）。
    """
    c0 = 299792458.0
    out: list[dict[str, Any]] = []
    for i in range(i_max + 1):
        for j in range(j_max + 1):
            if i == 0 and j == 0:
                continue
            base = (c0 / 2.0) * math.sqrt((i / float(lx_m)) ** 2
                                          + (j / float(ly_m)) ** 2)
            for eps in eps_grid:
                f_ghz = base / math.sqrt(float(eps)) / 1e9
                if abs(f_ghz - float(f_target_ghz)) <= tol_rel * float(f_target_ghz):
                    out.append({"i": i, "j": j, "eps_eff": float(eps),
                                "f_ghz": round(f_ghz, 4)})
    out.sort(key=lambda d: abs(d["f_ghz"] - float(f_target_ghz)))
    return out


# ── 真数据判别报告 builder（零仿真；runner 判读链之外的评价面）──────────────────

def build_spurious_verdict(work_dir: str | Path, out_path: str | Path | None = None,
                           f_lo_hz: float = 2.25e9, f_hi_hz: float = 2.75e9,
                           n_freq: int = 401, f_design_ghz: float = 2.5,
                           q_mat_cap: float = Q_MAT_CAP,
                           delays_ns: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0),
                           fracs: tuple[float, ...] = (0.6, 0.8, 1.0),
                           ) -> dict[str, Any]:
    """stage1 工作目录 → 伪模判别报告（分类+精化+跨窗+幅值+盒模+预算+前哨回放）。

    engine.log 供 dt/excitation/步数锚/能量与尾段斜率（缺则预算/回放面如实
    置 None，判别面照出）。不发射引擎、不改判读产物（stage1_verdict.json 归
    runner --judge-stage1 管）。
    """
    from c3_resonance_q_extract import extract_ring_modes, load_msl_probes, q_extrap_confidence, q_extrap_report

    work = Path(work_dir)
    probes_all = load_msl_probes(str(work / "fdtd"))
    t = probes_all[1][0]
    u1 = probes_all[1][1]
    freq = np.linspace(float(f_lo_hz), float(f_hi_hz), int(n_freq))

    # 激励时长：engine.log 只认日志（不从数据猜）；缺则按探针窗中点前如实物化
    t_exc: float | None = None
    eng: dict[str, Any] = {}
    rate_engine: float | None = None
    log_path = work / "engine.log"
    if log_path.exists():
        from smoke_c3_filter_family import parse_engine_log
        eng = parse_engine_log(log_path.read_text(encoding="utf-8",
                                                  errors="replace"))
        t_exc = eng.get("excitation_s")
        dt = eng.get("dt_s")
        if t_exc is not None and dt is not None:
            from c3_fullcurve_runner import engine_energy_tail_rate
            rate_engine = engine_energy_tail_rate(
                log_path.read_text(encoding="utf-8", errors="replace"),
                float(dt), float(t_exc))
    if t_exc is None:
        raise ValueError(f"engine.log 缺 excitation_s（t_excite 只认日志）：{log_path}")

    modes = extract_ring_modes(t, u1, float(f_lo_hz), float(f_hi_hz),
                               float(t_exc))
    modes_report = [{"f0_ghz": float(m["f0_hz"]) / 1e9,
                     "alpha_per_ns": float(m["alpha_per_s"]) * 1e-9,
                     "q_loaded": float(m["q_loaded"]),
                     "span_db": float(m["span_db"]), "n_fit": int(m["n_fit"])}
                    for m in modes]
    cls = classify_modes(modes_report, q_mat_cap=q_mat_cap)

    modes_phys_kernel = kernel_modes_from_report(cls["physical"])
    modes_phys_refined: list[dict[str, Any]] = []
    if modes_phys_kernel:
        modes_phys_refined = refine_modes_vp(t, u1, float(t_exc), modes_phys_kernel)

    rep_phys: dict[str, Any] | None = None
    conf_phys: dict[str, Any] | None = None
    if modes_phys_refined:
        probes = {k: (uu, ii) for k, (_tt, uu, ii) in probes_all.items()}
        rep_phys = q_extrap_report(t, probes, freq, modes_phys_refined,
                                   float(t_exc), f_design_hz=float(f_design_ghz) * 1e9)
        from smoke_c3_filter_family import Q_EXTRAP_DEV_DB_MAX, Q_EXTRAP_HOLDOUT_REL_MAX, Q_EXTRAP_SPAN_DB_MIN
        conf_phys = q_extrap_confidence(rep_phys, Q_EXTRAP_DEV_DB_MAX,
                                        Q_EXTRAP_HOLDOUT_REL_MAX,
                                        Q_EXTRAP_SPAN_DB_MIN)

    amp = mode_amplitudes(t, u1, float(t_exc), modes)
    stab = cross_window_stability(t, u1, float(f_lo_hz), float(f_hi_hz),
                                  float(t_exc), modes_report,
                                  delays_ns=delays_ns, fracs=fracs)
    box = {f"{m['f0_ghz']:.4f}": box_mode_candidates(float(m["f0_ghz"]))
           for m in cls["spurious"]}

    # A1/A2 归因（C3/C4/C5 组合，只标注不进门）——按频率配对，不依赖模表顺序
    attribution: dict[str, Any] = {}
    for sm in cls["spurious"]:
        pm = next((p for p in stab["per_mode"]
                   if abs(p["f0_ghz_base"] - float(sm["f0_ghz"])) < 1e-6), None)
        rel = next((a["rel_to_max"] for a in amp["modes"]
                    if abs(a["f0_ghz"] - float(sm["f0_ghz"])) < 1e-3), None)
        fit_degen = bool(pm["degenerate_fit"]) if pm is not None else False
        spread = pm["alpha_spread_ratio"] if pm is not None else None
        drift = pm["f0_drift_mhz"] if pm is not None else None
        absent = pm["n_absent"] if pm is not None else None
        box_hit = bool(box.get(f"{float(sm['f0_ghz']):.4f}"))
        attribution[f"{float(sm['f0_ghz']):.4f}"] = {
            "alpha_spread_ratio": spread,
            "f0_drift_mhz": drift,
            "n_absent": absent,
            "rel_amplitude": rel,
            "box_mode_candidate": box_hit,
            "class": ("A1_fitting_degenerate" if fit_degen
                      else ("A2_domain_mode_suspect" if rel is not None
                            and rel >= 0.01 else "A1_A2_mixed_suspect")),
            "note": ("归因只标注不进门——两假设均非器件物理模，处理同一："
                     "不进收敛门、不进尾外推基（criteria §二裁决规则）")}

    # 预算面（物理模 α；span≥3dB 才作预算输入，置信 20dB 总门不动）
    budget: dict[str, Any] | None = None
    alpha_min = budget_alpha_min(modes_phys_refined)
    eng_have = all(eng.get(k) is not None
                   for k in ("dt_s", "last_progress_step", "last_energy_db",
                             "excitation_steps"))
    if alpha_min is not None and eng_have:
        from c3_fullcurve_runner import compute_stage2_plan, energy_rate_from_alpha
        budget = compute_stage2_plan(
            dt_s=float(eng["dt_s"]),
            iterations_done=int(eng["last_progress_step"]),
            excitation_steps=int(eng["excitation_steps"]),
            e_cap_db=float(eng["last_energy_db"]),
            alpha_min_per_ns=alpha_min,
            rate_engine_db_per_ns=rate_engine,
            stage1_wall_s=eng.get("engine_wall_s"))
        budget["alpha_min_physical_per_ns"] = alpha_min
        budget["rate_kernel_physical_db_per_ns"] = energy_rate_from_alpha(alpha_min)
        budget["note"] = ("物理模口径预算（伪模剔除后 α_min；IF released 参考——"
                          "放行仍由前哨门把守，criteria §五）")

    # 前哨回放（物理模基置信 + S21∞@f0 门；sentinel_gate 复用 runner 面）
    sentinel: dict[str, Any] | None = None
    if conf_phys is not None and rep_phys is not None:
        from c3_fullcurve_runner import SENTINEL_S21_INF_F0_MIN_DB, sentinel_gate
        k21 = rep_phys["keys"].get("s21_f0")
        s21_inf = (float(k21["s_inf_db"]) if isinstance(k21, dict) else None)
        sentinel = sentinel_gate(conf_phys, s21_inf)
        sentinel["s21_inf_f0_min_db"] = SENTINEL_S21_INF_F0_MIN_DB

    doc: dict[str, Any] = {
        "work_dir": str(work), "criteria": "runs/c3_sirbpf_spurious/criteria.md",
        "q_mat_cap": float(q_mat_cap),
        "t_excite_s": float(t_exc), "t_end_probe_ns": float(t[-1]) * 1e9,
        "modes_all": modes_report,
        "classification": {"physical": cls["physical"], "spurious": cls["spurious"],
                           "basis": cls["basis"]},
        "modes_physical_refined": [
            {"f0_ghz": float(m["f0_hz"]) / 1e9,
             "alpha_per_ns": float(m["alpha_per_s"]) * 1e-9,
             "q_loaded": float(m["q_loaded"]), "span_db": float(m["span_db"]),
             "fit_resid": float(m.get("resid") or 0.0)}
            for m in modes_phys_refined],
        "physical_report": (None if rep_phys is None else {
            "keys": rep_phys.get("keys"),
            "s21_inf_db_curve_note": "全曲线在 rep 内（不落本报告防体积膨胀）"}),
        "confidence_physical": conf_phys,
        "amplitudes": amp,
        "cross_window_stability": stab,
        "box_mode_candidates": box,
        "attribution": attribution,
        "engine": {k: eng.get(k) for k in ("dt_s", "excitation_s", "excitation_steps",
                                           "last_progress_step", "last_energy_db",
                                           "nrts")},
        "rate_engine_db_per_ns": rate_engine,
        "stage2_budget_if_released": budget,
        "sentinel_replay_physical": sentinel,
        "stage2_release": (None if sentinel is None else {
            "released": bool(sentinel.get("ok", False)),
            "note": "放行由前哨门把守（criteria_a §三）；budget=IF released 参考"}),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--work-dir", required=True,
                    help="stage1 工作目录（fdtd/ 与 engine.log 所在）")
    ap.add_argument("--out", default=None, help="报告 JSON 落盘（可选）")
    ap.add_argument("--f-lo", type=float, default=2.25, help="扫频下沿 GHz")
    ap.add_argument("--f-hi", type=float, default=2.75, help="扫频上沿 GHz")
    ap.add_argument("--n-freq", type=int, default=401)
    ap.add_argument("--f-design-ghz", type=float, default=2.5)
    ap.add_argument("--q-mat-cap", type=float, default=Q_MAT_CAP)
    args = ap.parse_args(argv)
    doc = build_spurious_verdict(args.work_dir, args.out,
                                 f_lo_hz=args.f_lo * 1e9, f_hi_hz=args.f_hi * 1e9,
                                 n_freq=args.n_freq,
                                 f_design_ghz=args.f_design_ghz,
                                 q_mat_cap=args.q_mat_cap)
    print("classification:", json.dumps(
        {"physical": [m["f0_ghz"] for m in doc["classification"]["physical"]],
         "spurious": [m["f0_ghz"] for m in doc["classification"]["spurious"]],
         "q_mat_cap": doc["q_mat_cap"]}, ensure_ascii=False))
    print("physical_refined:", json.dumps(doc["modes_physical_refined"],
                                          ensure_ascii=False))
    print("attribution:", json.dumps(doc["attribution"], ensure_ascii=False))
    if doc["stage2_budget_if_released"] is not None:
        b = doc["stage2_budget_if_released"]
        print(f"budget(IF released): nrts={b['nrts']} pred={b['nrts_pred']} "
              f"budget_wall_s={b['budget_wall_s'] and round(b['budget_wall_s'])}")
    if doc["stage2_release"] is not None:
        print(f"stage2_release: {doc['stage2_release']['released']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
