"""df6 A1（R4 独立缺口）：2 棒对 k 全波标定锚 + 馈耦合 Qe/J01 语义（OE solo）。

规格与预声明判据（先于一切真机写死）：runs/df6_a1_r4/criteria.md。
fixture 复用 interdigital 模板 order/gaps_mm 参数化（零模板改动）：
  k fixture = order=2，gaps=[s_f,s_g,s_f]，s_f=0.8 弱馈（KJ 预估 Qe≈127）；
  qe fixture = order=1，gaps=[s_1, 2.0]（弱第二 tap，加载 ≈1%）。
k 主判 = 模分裂精确式 k=(f2²−f1²)/(f2²+f1²)（Hong & Lancaster；窄带近似只作
旁证列）；真机 k_raw 的馈 tap 加载拉动由合成电路偏置曲线逆映射修正（钉死）。
Qe = ω0·(τmax(S11)−2τ_line)/C_cfg：τ_line=馈线单程群时延（同一 S11 带缘相位
斜率自标定，#364② 参考面教训）；C_cfg 按点位确切 tap 配置由合成单极点网络
回收钉死（钉不过 judge 拒吃真机，#118/#300）。

用法（cwd=仓库根；OE solo：.oe_collect.lock + #261 命令行查双保险）：
  python -u scripts/df6_a1_r4_runner.py --plan               # 离线：选点+渲染+审计+plan.json
  python -u scripts/df6_a1_r4_runner.py --selftest           # 离线：合成回收钉（C 裁决+k 偏置曲线）
  python -u scripts/df6_a1_r4_runner.py --probe              # NrTS=10 探针：实测 dt/激励步数（#328 禁估计）
  python -u scripts/df6_a1_r4_runner.py --run  --pt kg_g13567    # 单点引擎（锁内，帽停自动展延一次）
  python -u scripts/df6_a1_r4_runner.py --judge --pt kg_g13567   # 单点判读（须 selftest PASS）
  python -u scripts/df6_a1_r4_runner.py --queue              # 串行队列驱动（detached 可跑，断点续跑幂等）
  python -u scripts/df6_a1_r4_runner.py --table              # 曲线级判读：k(g) 单调门 + J01 对照表
退出码：0=完成/门过；1=门未达/执行失败；2=参数错误。
产物根 runs/df6_a1_r4/<pt>/（simulation.py/engine.log/sparams.csv/port_beta.csv/
run_meta.json/verdict.json）；曲线级 curve_verdict.json。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (REPO / "src", HERE, REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.adapters.em_solver_base import resolve_openems_exe  # noqa: E402
from rfauto.adapters.openems_templates import (  # noqa: E402
    c3_coupling_j_from_gap,
    c3_gap_from_coupling_j,
    c3_inverter_chain_sparams,
    c3_slope_shorted_stub,
    c3_y_shorted_stub,
    render_script,
)
from rfauto.core.synthesis import Stackup, forward_z0  # noqa: E402
from smoke_coupled_bpf_nrts import (  # noqa: E402  只读复用（smoke_c3 同款）
    _run_engine,
    parse_engine_log,
    read_csv_cols,
    rewrite_nrts,
)

# ── 预声明常量（criteria.md 同源；改门先改 criteria 再改这里）─────────────────
ROOT = REPO / "runs" / "df6_a1_r4"
LOCK_PATH = REPO / "runs" / ".oe_collect.lock"
LOCK_POLL_S = 30.0
LOCK_BUSY_TIMEOUT_S = 600.0
F0_GHZ = 2.5
BAND_GHZ = (2.2, 2.8)
N_FREQ_PTS = 1201                      # 0.5MHz 栅格（脚本级 rewrite 401→1201）
ER, H_MM = 3.66, 0.508
Z0 = 50.0
W_MM = 1.1117                          # 50Ω HJ（与名义同源，铁律 1c）
RES_LEN_MM = 17.0820                   # 登记⑨+R1 过孔补偿口径（名义同值）
FEED_LEN_MM = 51.4590                  # 60 − res_len/2（阵列 y 居中）
S_FEED_K_MM = 0.8                      # k fixture 弱馈缝
S_TAP2_MM = 2.0                        # qe fixture 弱第二 tap（Qe≈1550）
S_QE_DESIGN_MM = 0.2263                # 设计馈耦合名义缝（J01 KJ=4.29e-3 S）
MESH_K_MM = 0.5                        # 曲线各点统一（系统误差相消）
MESH_QE_DESIGN_MM = 0.3                # min gap 0.2263 → c3_mesh_max_mm=0.3017
# 帽值修订（2026-09-24 首点 kg_g13567 帽停实测衰减 0.44-0.72dB/ns → −60dB
# 需 ~110ns；#344 先实测后外推，criteria 落痕有记录；预声明展延阈值 −35dB
# 与收敛门 −40dB 之间死区由此消除）
NRTS_K = 600_000
NRTS_QE_DESIGN = 450_000
NRTS_QE_WEAK = 600_000
EXTEND_FACTOR = 2                      # 帽停自动展延一次 ×2（#344 先实测后外推）
EXTEND_ENERGY_MAX_DB = -35.0           # 末能量劣于此才展延
CONVERGENCE_ENERGY_MAX_DB = -40.0      # 逐点收敛门（帽停态）
BETA_PCT_MAX = 10.0                    # β 门（#347）
K_DESIGN = 0.051514
QE_DESIGN = 17.0689
QE_HFSS_BAND = (290.0, 300.0)
K_TARGETS: tuple[float, ...] = (0.020, 0.028, 0.040, K_DESIGN, 0.065, 0.080)
# 钉偏置曲线栅格（合成电路免费，加密到 11 节点；非节点回收钉取 0.047）
PIN_K_GRID: tuple[float, ...] = (0.020, 0.025, 0.028, 0.034, 0.040, 0.0455,
                                 K_DESIGN, 0.058, 0.065, 0.072, 0.080)
QUEUE_ORDER = ("kg_g13567", "kg_g20293", "kg_g24950", "kg_g16132",
               "kg_g11441", "kg_g09707", "qe_g0800", "qe_g02263")
# τ_line 自标定拟合带：谐振特征以下 ≥150MHz（真机谐振 ~2.5GHz；钉电路谐振
# ~2.595GHz 同式同带提取，回收钉覆盖该处理链）
LINE_FIT_BAND_HZ = (2.20e9, 2.32e9)   # 谐振特征以下 >=150MHz（Hz）
PIN_FEED_LEN_MM = 58.0                 # 钉电路馈线长：真空时延 ≈ 真机 MSL 电气时延
PROBE_NRTS = 10
PROBE_TIMEOUT_S = 900.0
RUN_TIMEOUT_MARGIN_S = 1.5
RUN_TIMEOUT_BUFFER_S = 1800.0
RUN_TIMEOUT_FLOOR_S = 1800.0
S_PER_TS_REF = 0.0286                  # df5 stage1 实测 @12.464e6 cells（0.3mm 档）
CELLS_REF = 12.464e6
C_MUTEX_PS = "_oe_proc_check.ps1"
_FREQ_RE = re.compile(r"np\.linspace\(F0 - FC, F0 \+ FC, (\d+)\)")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_ksplit():
    """按路径加载 scripts/hairpin_alt_ksplit.py（复用 find_mode_pair/KSPLIT_RULE）。"""
    spec = importlib.util.spec_from_file_location(
        "_df6_hairpin_alt_ksplit", str(HERE / "hairpin_alt_ksplit.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_KS = None


def ksplit_mod():
    global _KS
    if _KS is None:
        _KS = _load_ksplit()
    return _KS


# ── 点位定义（criteria §〇 表的代码化）───────────────────────────────────────

def _zr_ere() -> tuple[float, float]:
    st = Stackup(name="df6a1", epsilon_r=ER, thickness_mm=H_MM)
    return forward_z0(W_MM, F0_GHZ, st)


def slope_b() -> float:
    return c3_slope_shorted_stub(_zr_ere()[0])


def j_from_qe(qe: float, b: float) -> float:
    """J01=√(b/(Qe·Z0)) 综合口径（criteria §四.5；逆式 Qe=b/(J²Z0)）。"""
    return math.sqrt(b / (float(qe) * Z0))


def qe_from_j(j_s: float, b: float) -> float:
    """单 tap 外部 Q：Qe=b/(J²Z0)（MYJ/Hong 口径）。"""
    return b / (float(j_s) ** 2 * Z0)


def _pt_name_k(s_g_mm: float) -> str:
    return f"kg_g{round(s_g_mm * 1e4):05d}"


def build_points() -> list[dict]:
    """点位表：k 目标 → J=k·b → 缝（brentq 反解，c3_gap_from_coupling_j）。"""
    b = slope_b()
    pts: list[dict] = []
    for k_t in K_TARGETS:
        j_t = k_t * b
        s_g = c3_gap_from_coupling_j(j_t, W_MM, F0_GHZ, ER, H_MM)
        j_rt, _ = c3_coupling_j_from_gap(W_MM, s_g, F0_GHZ, ER, H_MM)
        pts.append({
            "pt": _pt_name_k(s_g), "kind": "k", "k_target": float(k_t),
            "s_g_mm": round(float(s_g), 6), "j12_target_s": float(j_rt),
            "s_feed_mm": S_FEED_K_MM, "order": 2,
            "mesh_mm": MESH_K_MM, "nrts": NRTS_K,
            "params": {"order": 2, "w_mm": W_MM, "res_len_mm": RES_LEN_MM,
                       "feed_len_mm": FEED_LEN_MM,
                       "gaps_mm": [S_FEED_K_MM, round(float(s_g), 6),
                                   S_FEED_K_MM]},
        })
    for s1, pt, mesh, nrts in ((S_QE_DESIGN_MM, "qe_g02263",
                                MESH_QE_DESIGN_MM, NRTS_QE_DESIGN),
                               (S_FEED_K_MM, "qe_g0800", MESH_K_MM,
                                NRTS_QE_WEAK)):
        pts.append({
            "pt": pt, "kind": "qe", "s1_mm": s1, "s2_mm": S_TAP2_MM,
            "order": 1, "mesh_mm": mesh, "nrts": nrts,
            "params": {"order": 1, "w_mm": W_MM, "res_len_mm": RES_LEN_MM,
                       "feed_len_mm": FEED_LEN_MM,
                       "gaps_mm": [s1, S_TAP2_MM]},
        })
    order = {p: i for i, p in enumerate(QUEUE_ORDER)}
    pts.sort(key=lambda d: order[d["pt"]])
    return pts


# ── 提取内核（钉与真机同代码路径；纯函数离线可测）────────────────────────────

def synthetic_schain(j_list: list[float], res_len_mm: float, z_r: float,
                     ere: float, freqs: np.ndarray,
                     feed_len_mm: float = PIN_FEED_LEN_MM) -> np.ndarray:
    """理想 J 倒置器链（n=len(j_list)-1 个同长短路棒谐振臂，l_via=0）。"""
    y = lambda f: c3_y_shorted_stub(f, ere, res_len_mm, z_r, 0.0)  # noqa: E731
    return c3_inverter_chain_sparams(freqs, j_list, [y] * (len(j_list) - 1),
                                     feed_len_mm)


def parabolic_refine(f: np.ndarray, y: np.ndarray, i: int) -> float:
    """三点抛物线顶点（log|S|/τ 域峰位细化）；边界/退化回退网格点。"""
    if i <= 0 or i >= len(f) - 1:
        return float(f[i])
    d0, d1, d2 = float(y[i - 1]), float(y[i]), float(y[i + 1])
    den = d0 - 2.0 * d1 + d2
    if den == 0.0:
        return float(f[i])
    off = 0.5 * (d0 - d2) / den
    if not -1.0 < off < 1.0:
        return float(f[i])
    return float(f[i] + off * (f[i + 1] - f[i]))


def group_delay(freq_hz: np.ndarray, s: np.ndarray) -> np.ndarray:
    """群时延 τ=−dφ/dω（相位 unwrap + np.gradient 中心差分）。"""
    f = np.asarray(freq_hz, dtype=float)
    ph = np.unwrap(np.angle(np.asarray(s, dtype=complex)))
    return -np.gradient(ph, 2.0 * np.pi * f)


def line_delay_1way(freq_hz: np.ndarray, s11: np.ndarray,
                    band_hz: tuple[float, float]) -> float:
    """馈线单程群时延 τ_line：带缘（谐振特征以下）S11 相位斜率自标定。

    S11=Γ·e^(−2jβL) → dφ/df=−4πL/v ⇒ τ_line=L/v=−slope/(4π)。真机与钉电路
    同法提取（判据链自洽；#364② 参考面跨度教训的自标定替代）。
    """
    f = np.asarray(freq_hz, dtype=float)
    ph = np.unwrap(np.angle(np.asarray(s11, dtype=complex)))
    sel = (f >= band_hz[0]) & (f <= band_hz[1])
    if int(sel.sum()) < 10:
        raise ValueError("τ_line 拟合带样本不足")
    sl = float(np.polyfit(f[sel], ph[sel], 1)[0])
    return -sl / (4.0 * math.pi)


def mode_split_k(freq_hz: np.ndarray, s21: np.ndarray) -> dict:
    """双峰模分裂 k 提取：主判精确式 + 窄带近似旁证（峰位抛物线细化）。

    峰检复用 hairpin_alt_ksplit.find_mode_pair（KSPLIT_RULE，hairpin 先例
    同款确定性口径）；双峰不可分 → k=None（如实，不硬提）。
    """
    f = np.asarray(freq_hz, dtype=float)
    db = 20.0 * np.log10(np.abs(np.asarray(s21, dtype=complex)) + 1e-12)
    pair = ksplit_mod().find_mode_pair(f, db)
    out: dict = {"pair": pair, "f1_ghz": None, "f2_ghz": None, "k_raw": None,
                 "k_narrowband": None}
    if pair["f1_ghz"] is None or pair["f2_ghz"] is None:
        return out
    i1 = int(np.argmin(np.abs(f - pair["f1_ghz"] * 1e9)))
    i2 = int(np.argmin(np.abs(f - pair["f2_ghz"] * 1e9)))
    fr1 = parabolic_refine(f, db, i1)
    fr2 = parabolic_refine(f, db, i2)
    f1, f2 = sorted((fr1, fr2))
    if f1 <= 0.0 or f2 <= f1:
        return out
    k = (f2 * f2 - f1 * f1) / (f2 * f2 + f1 * f1)
    out.update({"f1_ghz": f1 / 1e9, "f2_ghz": f2 / 1e9, "k_raw": float(k),
                "k_narrowband": float(2.0 * (f2 - f1) / (f2 + f1))})
    return out


def bias_invert(k_raw: float, raw_grid: np.ndarray,
                true_grid: np.ndarray) -> float:
    """合成偏置曲线逆映射（M 单调递增；log-log 内插——偏置近幂律，线性域
    曲率实测致 midnode 回收 7.6% 偏差，#118 数值裁判弃线性域内插）。"""
    rg = np.log(np.asarray(raw_grid, dtype=float))
    tg = np.log(np.asarray(true_grid, dtype=float))
    if rg.size < 2 or not np.all(np.diff(rg) > 0):
        raise ValueError("偏置曲线 raw 栅格须严格递增")
    return float(math.exp(float(np.interp(math.log(k_raw), rg, tg))))


def extract_k_point(freq_hz: np.ndarray, s21: np.ndarray,
                    selftest: dict) -> dict:
    """真机 k 提取入口：mode_split_k + 偏置修正（selftest 偏置曲线逆）。"""
    ex = mode_split_k(freq_hz, s21)
    ex["k_corr"] = None
    if ex["k_raw"] is not None:
        stb = selftest["k_bias"]
        ex["k_corr"] = bias_invert(ex["k_raw"],
                                   np.asarray(stb["raw_grid"], dtype=float),
                                   np.asarray(stb["true_grid"], dtype=float))
    return ex


def extract_qe_point(freq_hz: np.ndarray, s11: np.ndarray,
                     c_cfg: float) -> dict:
    """真机 Qe 提取入口：τ(f) 四参数 Lorentzian+基线拟合（确定性内核）。

    τ(f)=A/(1+((f−f0)/w)²)+D：单极点谐振群时延形（D 吸收馈线往返时延+远带
    基线；带缘斜率法会被谐振器电抗斜率污染——钉电路实测 0.625ns vs 真线
    0.193ns，弃用）。理论：无耗单端口 Z_in=J²Z_res 在 f₀ 短路、
    φ=π−2·arctan(1/x)、x=2QeΔω/ω0 ⇒ τmax=4Qe/ω0 ⇒ **A=4·Qe/ω0、C=4**；
    Qe=A·ω0/C_cfg，C_cfg 由点位确切 tap 配置的合成回收钉死。
    """
    from scipy.optimize import curve_fit

    f = np.asarray(freq_hz, dtype=float)
    tau = group_delay(f, s11)
    i = int(np.argmax(tau))
    f0_hz = float(f[i])
    span = f[-1] - f[0]
    far = tau[(f <= f[0] + 0.2 * span) | (f >= f[-1] - 0.2 * span)]
    d0 = float(np.median(far))
    a0 = max(float(tau[i]) - d0, 1e-15)
    p0 = [a0, f0_hz, max(3.0e6, 0.02 * f0_hz), d0]

    def _model(ff, a, fc, w, d):
        return a / (1.0 + ((ff - fc) / w) ** 2) + d

    popt, _ = curve_fit(_model, f, tau, p0=p0, maxfev=20000)
    a_fit, fc_fit, w_fit, d_fit = (float(v) for v in popt)
    # 规范化 (A,w) 镜像简并（同 calculators qe_group_delay），符号感知见下。
    if w_fit < 0:
        a_fit, w_fit = -a_fit, -w_fit
    # 符号感知（同 calculators qe_group_delay 2026-09-25 修）：实测瓣可为负，
    # Qe=|A|·ω0/c，符号如实入 sign 字段（正瓣=合成钉约定，负瓣=实测约定）。
    resid = float(np.max(np.abs(tau - _model(f, *popt))))
    qe_signed = float(a_fit * 2.0 * math.pi * fc_fit / float(c_cfg))
    return {"tau_max_s": float(tau[i]), "a_fit_s": a_fit,
            "f_res_ghz": fc_fit / 1e9, "w_fit_hz": w_fit, "d_fit_s": d_fit,
            "fit_max_resid_s": resid,
            "qe_s11": abs(qe_signed),
            "sign": 1 if qe_signed > 0 else -1,
            "c_cfg": float(c_cfg)}


# ── selftest（合成回收钉；钉不过 judge 拒吃真机）─────────────────────────────

def run_selftest() -> dict:
    b = slope_b()
    z_r, ere = _zr_ere()
    freq_fine_ghz = np.linspace(2.42, 2.60, 36001)
    freq_fine = freq_fine_ghz * 1e9          # 提取内核统一 Hz 口径
    # ── C_S11 纯单端口锚：tap2 近不存在（Qe2=1e5），理论 A=4Qe/ω0 ⇒ C=4 ─────
    j_wk = j_from_qe(1e5, b)
    s_a = synthetic_schain([j_from_qe(17.07, b), j_wk], RES_LEN_MM, z_r, ere,
                           freq_fine_ghz)
    ex_a = extract_qe_point(freq_fine, s_a[:, 0, 0], 4.0)
    c_pure = (2.0 * math.pi * ex_a["f_res_ghz"] * 1e9
              * ex_a["a_fit_s"] / 17.07)
    # 独立第二例回收（C_pure 定于案例 A，案例 B 验）
    s_b = synthetic_schain([j_from_qe(100.0, b), j_wk], RES_LEN_MM, z_r, ere,
                           freq_fine_ghz)
    ex_b = extract_qe_point(freq_fine, s_b[:, 0, 0], c_pure)
    rec_b = ex_b["qe_s11"] / 100.0
    # ── 对称双馈 S21 口径（记录量；真机判据走 S11 单载反射）─────────────────
    s_c = synthetic_schain([j_from_qe(100.0, b), j_from_qe(100.0, b)],
                           RES_LEN_MM, z_r, ere, freq_fine_ghz)
    ex_c = extract_qe_point(freq_fine, s_c[:, 1, 0], 4.0)
    c_s21 = (2.0 * math.pi * ex_c["f_res_ghz"] * 1e9
             * ex_c["a_fit_s"] / 100.0)
    # ── 点位配置钉：q_e 每点用其确切 tap 组合的 C_cfg（KJ J 值即真机渲染缝）──
    c_by_pt: dict[str, dict] = {}
    for d in build_points():
        if d["kind"] != "qe":
            continue
        j1, _ = c3_coupling_j_from_gap(W_MM, float(d["s1_mm"]), F0_GHZ, ER,
                                       H_MM)
        j2, _ = c3_coupling_j_from_gap(W_MM, float(d["s2_mm"]), F0_GHZ, ER,
                                       H_MM)
        qe1 = qe_from_j(j1, b)
        s_p = synthetic_schain([j1, j2], RES_LEN_MM, z_r, ere, freq_fine_ghz)
        ex_p = extract_qe_point(freq_fine, s_p[:, 0, 0], 4.0)
        c_by_pt[d["pt"]] = {
            "c_cfg": float(2.0 * math.pi * ex_p["f_res_ghz"] * 1e9
                           * ex_p["a_fit_s"] / qe1),
            "qe1_true": float(qe1), "j1_s": float(j1), "j2_s": float(j2)}
        # 自回收（同一合成数据回代，须逐位）
        ex_r = extract_qe_point(freq_fine, s_p[:, 0, 0],
                                c_by_pt[d["pt"]]["c_cfg"])
        c_by_pt[d["pt"]]["self_recovery_rel"] = (
            ex_r["qe_s11"] / qe1 - 1.0)
    # ── k 偏置曲线（真机同频栅格 1201 点 + 同 s_f）─────────────────────────
    freq_cur_ghz = np.linspace(BAND_GHZ[0], BAND_GHZ[1], N_FREQ_PTS)
    freq_cur = freq_cur_ghz * 1e9
    j_f, _ = c3_coupling_j_from_gap(W_MM, S_FEED_K_MM, F0_GHZ, ER, H_MM)
    true_grid, raw_grid, rows = [], [], []
    for k_t in PIN_K_GRID:
        s = synthetic_schain([j_f, k_t * b, j_f], RES_LEN_MM, z_r, ere,
                             freq_cur_ghz)
        ex = mode_split_k(freq_cur, s[:, 1, 0])
        if ex["k_raw"] is None:
            rows.append({"k_true": float(k_t), "k_raw": None,
                         "note": "双峰不可分"})
            continue
        true_grid.append(float(k_t))
        raw_grid.append(float(ex["k_raw"]))
        rows.append({"k_true": float(k_t), "k_raw": float(ex["k_raw"]),
                     "k_narrowband": ex["k_narrowband"],
                     "f1_ghz": ex["f1_ghz"], "f2_ghz": ex["f2_ghz"],
                     "bias_rel": ex["k_raw"] / float(k_t) - 1.0,
                     "valley_db": ex["pair"]["valley_depth_db"]})
    checks = {
        "c_pure_near_theory_4": abs(c_pure - 4.0) < 0.2,
        "qe_recovery_case_b_05pct": abs(rec_b - 1.0) <= 0.005,
        "c_s21_recorded_positive": c_s21 > 0.0,
        "k_all_resolved": len(raw_grid) == len(PIN_K_GRID),
        "k_bias_within_10pct": all(
            abs(r / t - 1.0) <= 0.10
             for t, r in zip(true_grid, raw_grid, strict=True)),
        "k_raw_grid_monotone": all(a < c for a, c in pairwise(raw_grid)),
        "qe_cfg_self_recovery_1e_9": all(
            abs(v["self_recovery_rel"]) < 1e-9 for v in c_by_pt.values()),
    }
    # 节点逐位回收 + 非节点内插回收（0.045 不在栅格）
    i_design = true_grid.index(K_DESIGN)
    k_node = bias_invert(raw_grid[i_design], np.asarray(raw_grid),
                         np.asarray(true_grid))
    checks["k_node_bit_exact"] = abs(k_node / K_DESIGN - 1.0) < 1e-9
    s_mid = synthetic_schain([j_f, 0.047 * b, j_f], RES_LEN_MM, z_r, ere,
                             freq_cur_ghz)
    ex_mid = mode_split_k(freq_cur, s_mid[:, 1, 0])
    if ex_mid["k_raw"] is not None:
        k_mid = bias_invert(ex_mid["k_raw"], np.asarray(raw_grid),
                            np.asarray(true_grid))
        mid_err = abs(k_mid / 0.047 - 1.0)
    else:
        k_mid, mid_err = None, 1.0
    checks["k_midnode_interp_5e3"] = mid_err <= 5e-3
    out = {"ts": utc_now(), "b_s": b, "z_r_ohm": z_r, "ere": ere,
           "c_s11_pure": float(c_pure), "c_s21_sym": float(c_s21),
           "c_by_pt": c_by_pt,
           "line_fit_band_hz": list(LINE_FIT_BAND_HZ),
           "qe_recovery_case_b_rel": rec_b - 1.0,
           "k_bias": {"true_grid": true_grid, "raw_grid": raw_grid,
                      "rows": rows},
           "k_midnode": {"k_true": 0.047, "k_corr": k_mid, "rel_err": mid_err},
           "checks": checks, "passed": all(checks.values())}
    (ROOT / "selftest_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def require_selftest() -> dict:
    p = ROOT / "selftest_result.json"
    if not p.exists():
        raise SystemExit("selftest 未跑（--selftest 先行；钉不过不吃真机）")
    st = json.loads(p.read_text(encoding="utf-8"))
    if not st.get("passed"):
        raise SystemExit(f"selftest 未 PASS：{st.get('checks')}")
    return st


# ── 离线审计门（#212：渲染→exec 几何段→CSXCAD 实测，秒级零仿真）──────────────

def _load_scope(params: dict, mesh_mm: float):
    text = render_script("interdigital", dict(params), BAND_GHZ,
                         mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(ROOT / "_audit_sim.py")}
    exec(compile(head, "df6a1_audit", "exec"), scope)
    from tests.unit import _geometry_audit_helpers as gh
    return scope, gh.extract_primitives(scope["CSX"]), gh, text


def audit_fixture(tag: str, params: dict, mesh_mm: float) -> dict:
    scope, prims, gh, text = _load_scope(params, mesh_mm)
    n = int(params["order"])
    gaps_m = [v * 1e-3 for v in params["gaps_mm"]]
    metal = [p for p in prims if p.kind == "Metal"]
    y_top = max(p.hi[1] for p in metal)
    y1 = min(p.lo[1] for p in metal
             if p.lo[1] > -float(scope["BOARD"]) + 1e-9)
    # 1) 缝边到边逐缝一致 + 缝内内部网格线 ≥1（x 轴，缝缘线不算）
    strips = sorted([p for p in metal if p.radius is None
                     and p.hi[1] > y1 + 1e-9 and p.lo[1] < y_top],
                    key=lambda p: p.lo[0])
    uniq: list = []
    for p in strips:
        if not uniq or abs(p.lo[0] - uniq[-1].lo[0]) > 1e-12:
            uniq.append(p)
    lines_x = np.asarray(gh.mesh_lines(scope, "x"), dtype=float)
    gap_checks = []
    for j, (a, b2) in enumerate(pairwise(uniq)):
        gap = b2.lo[0] - a.hi[0]
        inner = lines_x[(lines_x > a.hi[0] + 1e-9)
                        & (lines_x < b2.lo[0] - 1e-9)]
        gap_checks.append({
            "gap_idx": j, "gap_m": float(gap), "want_m": gaps_m[j],
            "gap_ok": bool(abs(gap - gaps_m[j]) <= 1e-9 * max(1.0, gaps_m[j])),
            "inner_lines": int(inner.size), "inner_ok": bool(inner.size >= 1)})
    # 2) 导体分量 / 馈电点各落恰一导体且互异
    conductors, labels = gh.conductor_labels(prims)
    ports = gh.port_objects(scope)
    comp_of: dict[int, int] = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        if len(on) == 1:
            comp_of[number] = next(iter(on))
    # 3) 网格近重合 / 原语进网格 / 端口贴 PML 侧 / 边界表
    min_sp = {ax: float(np.min(np.diff(gh.mesh_lines(scope, ax))))
              for ax in ("x", "y", "z")}
    board = float(scope["BOARD"])
    ports_on_edge = all(
        abs(np.asarray(p.start, dtype=float)[1] + board) <= 1e-9
        for p in ports.values())
    # 4) 过孔交替（order=2）/ 底端（order=1）：过孔中心 y 判位
    cyls = sorted([p for p in metal if p.radius is not None],
                  key=lambda p: p.lo[0])
    via_centers = [float(p.lo[1]) + float(p.radius) for p in cyls]
    r_via = float(cyls[0].radius) if cyls else 0.0
    # 过孔中心距棒端内缩 r_via：奇棒底端 y1+r、偶棒顶端 y_top−r（Cohn 口径）
    via_ok = (len(cyls) == n
              and all(abs(via_centers[i]
                          - (y1 + r_via if i % 2 == 0 else y_top - r_via))
                      < 1e-9 for i in range(n)))
    checks = {
        "strip_count_is_n_plus_2": len(uniq) == n + 2,
        "gap_edge_exact_and_inner_lines": all(c["gap_ok"] and c["inner_ok"]
                                              for c in gap_checks),
        "conductor_components_n_plus_2": len(set(labels)) == n + 2,
        "port_feed_points_on_distinct_bars": (
            len(comp_of) == len(ports)
            and len(set(comp_of.values())) == len(ports)),
        "min_mesh_spacing_gt_1um": all(v > 1e-6 for v in min_sp.values()),
        "all_prims_enter_mesh": gh.off_mesh_planes(prims, scope) == [],
        "ports_on_pml_edge": bool(ports_on_edge),
        "pml_boundary_in_script": '"PML_8", "PML_8"' in text,
        "via_positions_alternating": bool(via_ok),
    }
    ok = all(bool(v) for v in checks.values())
    res = {"tag": tag, "params": params, "mesh_mm": mesh_mm, "ok": ok,
           "checks": checks, "gap_checks": gap_checks,
           "min_spacing_m": min_sp, "via_center_y_m": via_centers,
           "conductor_labels": len(set(labels)), "ts": utc_now()}
    adir = ROOT / "audit"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / f"audit_{tag}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return res


# ── OE solo 互斥/锁（siw_anchor_smoke 同式；#261 自排除）─────────────────────

def oe_foreign_running() -> list[str]:
    ROOT.mkdir(parents=True, exist_ok=True)
    ps1 = ROOT / C_MUTEX_PS
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match '_rfauto_runner|simulation\\.py'"
        " } | ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(f"#261 查询失败 rc={out.returncode}: "
                           f"{out.stderr[:300]}")
    own = str(os.getpid())
    return [ln.strip() for ln in (out.stdout or "").splitlines()
            if ln.strip() and not ln.strip().startswith(own + "\t")]


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) "
             f"{{ Write-Output ALIVE }}"],
            capture_output=True, text=True, timeout=30)
        return "ALIVE" in (out.stdout or "")
    except Exception:
        return True


def _lock_owner() -> dict | None:
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lock_acquire(task: str,
                 busy_timeout_s: float = LOCK_BUSY_TIMEOUT_S) -> dict:
    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"pid": os.getpid(), "task": task,
                     "ts": datetime.now(timezone.utc).isoformat()},
                    ensure_ascii=False))
            return {"acquired": True,
                    "waited_s": round(time.monotonic() - t0, 1), "owner": None}
        except FileExistsError:
            owner = _lock_owner()
            if isinstance(owner, dict) and isinstance(owner.get("pid"), int) \
                    and not _pid_alive(int(owner["pid"])):
                LOCK_PATH.unlink(missing_ok=True)   # 陈锁接管
                continue
            if time.monotonic() - t0 > busy_timeout_s:
                return {"acquired": False,
                        "waited_s": round(time.monotonic() - t0, 1),
                        "owner": owner}
            time.sleep(LOCK_POLL_S)


def lock_release() -> None:
    LOCK_PATH.unlink(missing_ok=True)


# ── 渲染/改写/运行（预算 #328：dt/速率全实测，禁估计）────────────────────────

def rewrite_freq_pts(script: str, n_pts: int) -> tuple[str, int]:
    """脚本级改写 DFT 栅格 `np.linspace(F0 - FC, F0 + FC, 401)` → n_pts。"""
    if not _FREQ_RE.search(script):
        return script, 0
    out = _FREQ_RE.sub(f"np.linspace(F0 - FC, F0 + FC, {int(n_pts)})",
                       script, count=1)
    return out, 1


def _probe_mesh_cells(mesh_mm: float) -> float | None:
    p = ROOT / "probe" / "probe_result.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))["meshes"]
        key = next((k for k in v if abs(float(k) - mesh_mm) < 1e-6), None)
        cells = v[key].get("cells") if key else None
        return float(cells) if cells else None
    except (OSError, ValueError, KeyError):
        return None


def _timeout_for(nrts: int, mesh_mm: float) -> float:
    """墙钟预算公式（criteria §三.3）：rate 实测值优先，探针 cells 标度兜底。"""
    rate_p = ROOT / "probe" / "rate.json"
    s_per_ts = None
    if rate_p.exists():
        try:
            r = json.loads(rate_p.read_text(encoding="utf-8"))
            s_per_ts = float(r["s_per_ts"])
            ref_cells = float(r.get("cells") or 0)
            if ref_cells > 0:
                now_cells = _probe_mesh_cells(mesh_mm) or ref_cells
                s_per_ts *= now_cells / ref_cells
        except (OSError, ValueError, KeyError):
            s_per_ts = None
    if s_per_ts is None:
        cells = _probe_mesh_cells(mesh_mm) or CELLS_REF
        s_per_ts = S_PER_TS_REF * cells / CELLS_REF
    return max(RUN_TIMEOUT_FLOOR_S,
               s_per_ts * nrts * RUN_TIMEOUT_MARGIN_S + RUN_TIMEOUT_BUFFER_S)


def _engine_once(pt: str, params: dict, mesh_mm: float, nrts: int,
                 timeout_s: float, exe: str | None) -> dict:
    work = ROOT / pt
    work.mkdir(parents=True, exist_ok=True)
    script = render_script("interdigital", dict(params), BAND_GHZ,
                           mesh_resolution_mm=mesh_mm)
    sha_plain = hashlib.sha256(script.encode("utf-8")).hexdigest()
    script, n_nrts = rewrite_nrts(script, nrts)
    script, n_freq = rewrite_freq_pts(script, N_FREQ_PTS)
    assert n_nrts >= 1 and n_freq >= 1, "渲染脚本口径漂移（NrTS/频栅格未命中）"
    spath = work / "simulation.py"
    spath.write_text(script, encoding="utf-8")
    sha_final = hashlib.sha256(script.encode("utf-8")).hexdigest()
    (work / "run_input.json").write_text(json.dumps(
        {"pt": pt, "nrts": nrts, "freq_pts": N_FREQ_PTS,
         "sha_render_plain": sha_plain, "sha_final": sha_final,
         "params": params, "mesh_mm": mesh_mm, "ts": utc_now()},
        ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.monotonic()
    rc, timed_out = 0, False
    try:
        rc = _run_engine(work, exe, timeout_s, work / "engine.log")
    except subprocess.TimeoutExpired:
        rc, timed_out = 124, True
    wall = time.monotonic() - t0
    log = (work / "engine.log").read_text(encoding="utf-8", errors="replace")
    eng = parse_engine_log(log)
    eng["timed_out"] = timed_out
    return {"rc": int(rc), "wall_s": round(wall, 1), "engine": eng,
            "nrts": int(nrts), "sha_final": sha_final,
            "sha_render_plain": sha_plain}


def run_point(pt: str, extend: bool = True) -> dict:
    pts = {d["pt"]: d for d in build_points()}
    if pt not in pts:
        raise SystemExit(f"未知点位 {pt}（plan 面：{sorted(pts)}）")
    d = pts[pt]
    foreign = oe_foreign_running()
    if foreign:
        return {"pt": pt, "started": False, "rc": None,
                "reason": f"#261 互斥命中（他轨 OE 在跑，不代杀）：{foreign}"}
    lock = lock_acquire("df6_a1_r4")
    if not lock["acquired"]:
        return {"pt": pt, "started": False, "rc": None,
                "reason": f".oe_collect.lock 忙（owner={lock['owner']}）"}
    try:
        exe = resolve_openems_exe()
        rec = _engine_once(pt, d["params"], float(d["mesh_mm"]),
                           int(d["nrts"]), _timeout_for(int(d["nrts"]),
                                                        float(d["mesh_mm"])),
                           exe)
        rec["extended"] = False
        eng = rec["engine"]
        done_steps = int(eng.get("iterations_done", 0) or 0)
        cap_hit = bool(eng.get("nrts_limit_warning")) or (
            0 < done_steps >= int(rec["nrts"]))
        last_e = eng.get("last_energy_db")
        if (extend and cap_hit and rec["rc"] == 0
                and isinstance(last_e, (int, float))
                and last_e > EXTEND_ENERGY_MAX_DB):
            nrts2 = int(rec["nrts"]) * EXTEND_FACTOR
            rec2 = _engine_once(pt, d["params"], float(d["mesh_mm"]), nrts2,
                                _timeout_for(nrts2, float(d["mesh_mm"])), exe)
            rec2["extended"] = True
            rec2["first_attempt"] = {k: rec[k] for k in ("rc", "wall_s",
                                                         "nrts")}
            rec = rec2
        done_steps = int(rec["engine"].get("iterations_done", 0) or 0)
        rate = round(done_steps / rec["wall_s"], 2) \
            if done_steps > 0 and rec["wall_s"] > 0 else None
        rec["ts_per_s_measured"] = rate
        rec["pt"] = pt
        (ROOT / pt / "run_meta.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        if rate:
            (ROOT / "probe").mkdir(parents=True, exist_ok=True)
            (ROOT / "probe" / "rate.json").write_text(json.dumps(
                {"pt": pt, "s_per_ts": 1.0 / rate, "ts_per_s": rate,
                 "cells": rec["engine"].get("cells"), "ts": utc_now()},
                ensure_ascii=False), encoding="utf-8")
        return rec
    finally:
        lock_release()


# ── 判读 ─────────────────────────────────────────────────────────────────────

def _beta_gate(pt: str) -> dict:
    st = Stackup(name="df6a1", epsilon_r=ER, thickness_mm=H_MM)
    _, ere = forward_z0(W_MM, F0_GHZ, st)
    beta_hj = 2.0 * math.pi * F0_GHZ * 1e9 * math.sqrt(ere) / 299792458.0
    p = ROOT / pt / "port_beta.csv"
    if not p.exists():
        return {"ok": False, "reason": "port_beta.csv 缺失", "beta_hj": beta_hj}
    rows = np.loadtxt(str(p), delimiter=",", skiprows=1)
    sel = rows[(rows[:, 0] >= 0.96 * F0_GHZ * 1e9)
               & (rows[:, 0] <= 1.04 * F0_GHZ * 1e9)]
    if sel.shape[0] == 0:
        return {"ok": False, "reason": "β 带内无样本", "beta_hj": beta_hj}
    beta_eng = float(np.median(sel[:, 1]))
    dev = abs(beta_eng / beta_hj - 1.0) * 100.0
    return {"ok": bool(dev <= BETA_PCT_MAX), "beta_engine": beta_eng,
            "beta_hj": beta_hj, "dev_pct": dev}


def _convergence_gate(run_meta: dict) -> dict:
    eng = run_meta.get("engine", {})
    last_e = eng.get("last_energy_db")
    end_ok = (not eng.get("nrts_limit_warning", True)) \
        and "iterations_done" in eng
    ok = (isinstance(last_e, (int, float))
          and last_e <= CONVERGENCE_ENERGY_MAX_DB) or bool(end_ok)
    return {"ok": bool(ok), "last_energy_db": last_e,
            "min_energy_db": eng.get("min_energy_db"),
            "endcriteria_reached": bool(end_ok),
            "threshold_db": CONVERGENCE_ENERGY_MAX_DB}


def judge_point(pt: str) -> dict:
    st = require_selftest()
    pts = {d["pt"]: d for d in build_points()}
    d = pts[pt]
    work = ROOT / pt
    sp = work / "sparams.csv"
    rp = work / "run_meta.json"
    if not sp.exists() or not rp.exists():
        raise SystemExit(f"{pt}: sparams.csv/run_meta.json 缺失（先 --run）")
    run_meta = json.loads(rp.read_text(encoding="utf-8"))
    data = read_csv_cols(sp)
    f_hz = data[:, 0]
    s11 = data[:, 1] + 1j * data[:, 2]
    s21 = data[:, 3] + 1j * data[:, 4]
    conv = _convergence_gate(run_meta)
    beta = _beta_gate(pt)
    res: dict = {"pt": pt, "kind": d["kind"], "ts": utc_now(),
                 "convergence": conv, "beta": beta,
                 "run": {k: run_meta.get(k) for k in
                         ("rc", "wall_s", "nrts", "extended", "engine")}}
    verdict = "PASS"
    if not conv["ok"]:
        verdict = "FAIL_NOT_CONVERGED"
    if not beta["ok"]:
        verdict = "FAIL_BETA"
    b = slope_b()
    if d["kind"] == "k":
        ex = extract_k_point(f_hz, s21, st)
        res["extract"] = ex
        res["k_kj"] = d["j12_target_s"] / b
        res["k_narrowband"] = ex.get("k_narrowband")
        if ex["k_raw"] is None:
            verdict = "FAIL_NO_MODE_PAIR"
        else:
            res["k_corr_vs_target_rel"] = ex["k_corr"] / d["k_target"] - 1.0
            res["k_kj_vs_corr_rel"] = res["k_kj"] / ex["k_corr"] - 1.0
    else:
        c_cfg = float(st["c_by_pt"][pt]["c_cfg"])
        ex = extract_qe_point(f_hz, s11, c_cfg)
        res["extract"] = ex
        res["qe_cfg_pin"] = st["c_by_pt"][pt]
        res["qe_design"] = QE_DESIGN
        res["qe_hfss_band"] = list(QE_HFSS_BAND)
        res["j01_comp_s"] = j_from_qe(ex["qe_s11"], b)
        j01_kj, _ = c3_coupling_j_from_gap(W_MM, float(d["s1_mm"]), F0_GHZ,
                                           ER, H_MM)
        res["j01_kj_s"] = float(j01_kj)
        res["j01_ratio_comp_vs_kj"] = res["j01_comp_s"] / float(j01_kj)
        res["qe_vs_design_rel"] = ex["qe_s11"] / QE_DESIGN - 1.0
        if not 0.05 < ex["qe_s11"] < 1e6:
            verdict = "FAIL_QE_OUT_OF_RANGE"
    res["verdict"] = verdict
    (work / "verdict.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return res


# ── 曲线级判读 + J01 对照表 ──────────────────────────────────────────────────

def build_table() -> dict:
    rows: list[dict] = []
    qe_rows: list[dict] = []
    for d in build_points():
        vp = ROOT / d["pt"] / "verdict.json"
        if not vp.exists():
            continue
        v = json.loads(vp.read_text(encoding="utf-8"))
        ex = v.get("extract", {})
        if d["kind"] == "k":
            rows.append({"pt": d["pt"], "gap_mm": d["s_g_mm"],
                         "k_target": d["k_target"], "k_kj": v.get("k_kj"),
                         "k_raw": ex.get("k_raw"), "k_corr": ex.get("k_corr"),
                         "k_narrowband": ex.get("k_narrowband"),
                         "f1_ghz": ex.get("f1_ghz"),
                         "f2_ghz": ex.get("f2_ghz"),
                         "verdict": v.get("verdict")})
        else:
            qe_rows.append({"pt": d["pt"], "s1_mm": d["s1_mm"],
                            "qe_s11": ex.get("qe_s11"),
                            "tau_peak_ns": (ex.get("a_fit_s") or 0) * 1e9,
                            "f_res_ghz": ex.get("f_res_ghz"),
                            "qe_vs_design_rel": v.get("qe_vs_design_rel"),
                            "j01_comp_s": v.get("j01_comp_s"),
                            "j01_kj_s": v.get("j01_kj_s"),
                            "j01_ratio": v.get("j01_ratio_comp_vs_kj"),
                            "verdict": v.get("verdict")})
    rows.sort(key=lambda r: -(r["gap_mm"] or 0))
    ks = [r["k_corr"] for r in rows if r.get("k_corr") is not None]
    # 行序=gap 降序（大缝→小缝），物理上 k 随缝减小而增大 → 断言严格递增
    # （2026-09-25 收口修正：原 a>c 方向写反，把完美单调数据误判 false）。
    mono = all(a < c for a, c in pairwise(ks)) if len(ks) >= 2 else None
    out: dict = {"ts": utc_now(), "k_rows": rows,
                 "k_monotone_decreasing_in_gap": mono, "qe_rows": qe_rows}
    cs = [r["k_corr"] / r["k_kj"] for r in rows
          if r.get("k_corr") and r.get("k_kj")]
    if cs:
        out["c_ratio_median"] = float(np.median(cs))
        out["c_ratio_all"] = cs
    ok = mono is True and bool(rows) and all(r.get("verdict") == "PASS"
                                             for r in rows)
    out["curve_verdict"] = "PASS" if ok else ("PARTIAL" if rows else "NO_DATA")
    (ROOT / "curve_verdict.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return out


# ── plan / probe / queue ─────────────────────────────────────────────────────

def do_plan() -> int:
    (ROOT / "audit").mkdir(parents=True, exist_ok=True)
    pts = build_points()
    a2 = audit_fixture("order2_kfixture", pts[0]["params"], MESH_K_MM)
    a1 = audit_fixture(
        "order1_qefixture",
        next(p["params"] for p in pts if p["pt"] == "qe_g02263"),
        MESH_QE_DESIGN_MM)
    plan = {"ts": utc_now(), "band_ghz": list(BAND_GHZ),
            "freq_pts": N_FREQ_PTS, "b_s": slope_b(),
            "audit_ok": bool(a2["ok"] and a1["ok"]), "points": pts}
    (ROOT / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"plan: {len(pts)} pts; audit_ok={plan['audit_ok']}")
    for a in (a2, a1):
        print(f"  audit {a['tag']}: ok={a['ok']} checks={a['checks']}")
        if not a["ok"]:
            print(f"    gap_checks={a['gap_checks']}")
    return 0 if plan["audit_ok"] else 1


def do_probe() -> int:
    foreign = oe_foreign_running()
    if foreign:
        print(f"#261 互斥命中，拒绝探针：{foreign}")
        return 1
    lock = lock_acquire("df6_a1_r4_probe")
    if not lock["acquired"]:
        print(f".oe_collect.lock 忙（owner={lock['owner']}）")
        return 1
    try:
        exe = resolve_openems_exe()
        pts = build_points()
        meshes = sorted({float(p["mesh_mm"]) for p in pts})
        out: dict = {"ts": utc_now(), "meshes": {}}
        (ROOT / "probe").mkdir(parents=True, exist_ok=True)
        for mesh in meshes:
            d = next(p for p in pts if float(p["mesh_mm"]) == mesh)
            rec = _engine_once(f"probe_m{str(mesh).replace('.', '')}",
                               d["params"], mesh, PROBE_NRTS,
                               PROBE_TIMEOUT_S, exe)
            eng = rec["engine"]
            done = int(eng.get("iterations_done", 0) or 0)
            out["meshes"][str(mesh)] = {
                "dt_s": eng.get("dt_s"),
                "excitation_steps": eng.get("excitation_steps"),
                "grid": eng.get("grid"), "cells": eng.get("cells"),
                "rc": rec["rc"], "wall_s": rec["wall_s"],
                "ts_per_s": (round(done / rec["wall_s"], 2)
                             if done > 0 and rec["wall_s"] > 0 else None)}
        (ROOT / "probe" / "probe_result.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out["meshes"], ensure_ascii=False, indent=1))
        ok = all(v["dt_s"] for v in out["meshes"].values())
        return 0 if ok else 1
    finally:
        lock_release()


def do_queue() -> int:
    """串行队列驱动（detached 可跑；verdict 在档=完成，幂等续跑）。"""
    state_p = ROOT / "queue_state.json"
    state: dict = {"updated": utc_now(), "order": list(QUEUE_ORDER),
                   "done": [], "skipped_busy": [], "failed": [],
                   "current": None}
    if state_p.exists():
        try:
            old = json.loads(state_p.read_text(encoding="utf-8"))
            state["done"] = [p for p in old.get("done", [])
                             if (ROOT / p / "verdict.json").exists()]
        except ValueError:
            pass
    for pt in QUEUE_ORDER:
        if (ROOT / pt / "verdict.json").exists():
            if pt not in state["done"]:
                state["done"].append(pt)
            continue
        state["current"] = pt
        state["updated"] = utc_now()
        state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        run = run_point(pt)
        reason = str(run.get("reason", ""))
        if not run.get("started", True):
            state["skipped_busy"].append({"pt": pt, "reason": reason})
            print(f"[queue] {pt} 跳过（互斥/锁忙，稍后续跑）：{reason}")
        elif run.get("rc") != 0:
            state["failed"].append({"pt": pt, "rc": run.get("rc"),
                                    "reason": reason})
            print(f"[queue] {pt} run 失败 rc={run.get('rc')}，继续下一点")
        else:
            try:
                v = judge_point(pt)
                print(f"[queue] {pt} → {v['verdict']}")
                state["done"].append(pt)
            except SystemExit as exc:
                state["failed"].append({"pt": pt, "rc": run.get("rc"),
                                        "reason": str(exc)})
                print(f"[queue] {pt} judge 失败：{exc}")
        state["current"] = None
        state["updated"] = utc_now()
        state_p.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    build_table()
    print(f"[queue] 完成 done={state['done']} failed={state['failed']}")
    return 0 if not state["failed"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--pt", default=None)
    args = ap.parse_args(argv)
    ROOT.mkdir(parents=True, exist_ok=True)
    if args.plan:
        return do_plan()
    if args.selftest:
        st = run_selftest()
        print(f"selftest passed={st['passed']} c_s11_pure={st['c_s11_pure']:.4f}"
              f" c_s21_sym={st['c_s21_sym']:.4f} checks={st['checks']}")
        return 0 if st["passed"] else 1
    if args.probe:
        return do_probe()
    if args.run:
        if not args.pt:
            ap.error("--run 须随 --pt")
        rec = run_point(args.pt)
        print(json.dumps({k: rec.get(k) for k in
                          ("pt", "rc", "wall_s", "nrts", "extended", "engine",
                           "reason", "ts_per_s_measured")},
                         ensure_ascii=False, default=str))
        return 0 if rec.get("rc") == 0 else 1
    if args.judge:
        if not args.pt:
            ap.error("--judge 须随 --pt")
        v = judge_point(args.pt)
        print(json.dumps({k: v.get(k) for k in
                          ("pt", "verdict", "extract", "beta", "convergence",
                           "k_kj", "k_corr_vs_target_rel", "j01_comp_s",
                           "j01_kj_s", "qe_vs_design_rel")},
                         ensure_ascii=False, default=str))
        return 0 if v.get("verdict") == "PASS" else 1
    if args.queue:
        return do_queue()
    if args.table:
        out = build_table()
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0 if out.get("curve_verdict") in ("PASS", "PARTIAL") else 1
    ap.error("须择一 action：--plan/--selftest/--probe/--run/--judge/--queue/"
             "--table")
    return 2


if __name__ == "__main__":
    sys.exit(main())
