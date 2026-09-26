"""DP-1 P3 G1——MMT vs HFSS 对拍判读 v3（离线零求解；判据
runs/df6_dp1p3/criteria.md §1 + §4 v2 修订，先写后跑 #122）。

v3（df7_dp1fix 缺陷①修复）：mmt_modal_s 改用归档完整 2×2（含 s22/s12）
反归一模态基——v2 对称假定 [[s11,s21],[s21,s11]] 在 s22≠s11（旧 core 端口
交换缺陷）下模态腿被污染；产物路径缺省不变，新增 --out-dir 供重算对照批
落 addendum（归档零改写，#325/#326）。

v2 判定口径（§4 修订 1，首轮 run1_voided 证据后）：
- **模态基对拍**：HFSS 波端口 renormalize=False 的 |S| =模式场反射/
  传输系数模（功率归一，与端口阻抗表征无关）；MMT 侧把 meta 的 50Ω
  S 经可逆功率波变换反归一回 TE10 模基（Z_TE=ωμ0/β，解析），两者
  |S11|/|S21| 直接可比。理由：首轮实证 HFSS 波端口 Zo 表征在
  ΔS 收敛网格上 273.5Ω vs 解析 499.3Ω（#335 实例：ΔS 达标≠关键
  标量收敛）——50Ω renormalize 的 S 带基失真，模态基绕开该误差源。

输入（禁手抄数字——全部直读产物）：
- runs/df6_dp1p3/mmt/{straight,iris_t0,iris_t1}/mmt_meta.json；
- runs/df6_dp1p3/hfss_run.json（v2：阶梯 + harvest 扫频面 Gamma/Zo）；
- runs/df6_dp1p3/hfss/{p3_straight,p3_iris_t0,p3_iris_t1}.s2p（模态基）。

门（criteria §1 + §4 v2）：
- G1-conv：每设计末级 delta_s≤0.005 且未触 max_passes（#335）；
- G1-main：膜片两例 determined 频点逐频 |Δ|S11||/|Δ|S21||（模态幅
  dB 差）max≤0.5（起步门）；深零守卫：|S|_lin<0.05 改线性域 |Δ|≤0.01；
- G1-anchor-β：MMT β vs siw_beta_rad_m ≤1e-6（既有钉复核）；HFSS
  Gamma（扫频面全带）vs 同闭式 ≤0.5%；
- G1-anchor-straight（模态基）：直段模态 S11=0、S21=e^{−jβL}——
  MMT 反归一后逐位（≤1e-9）；HFSS modal |S11|≤0.01、|S21| 偏差≤0.005。

verdict（#350 判向双记）：AGREE / AGREE_HFSS / AGREE_MMT / DISAGREE
/ UNKNOWN；恒携带 hfss_self 与 mmt_self 两节自洽锚结果。判向：超差时
S11 偏差符号一致性 ≥0.8（|d|<0.05dB 平局不计入）为方向系统性。

产物：runs/df6_dp1p3/g1_verdict.json + sparam_diff_table.csv。
自检：--selftest 合成回收（闭式 50Ω 线式反归一回 TE10 基恒等恢复
S=[[0,T],[T,0]]、roundtrip ≤1e-12；注入偏差验证门旗与判向）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "df6_dp1p3"
A_MM, L_MM = 22.86, 20.0
Z0 = 50.0
MU0 = 1.25663706212e-6          # 独立闭式常数（P2 闭式裁判同值）
TOL_DB_MAIN = 0.5               # G1-main 起步门（模态幅 dB 差）
TOL_LIN_NULL = 0.01             # 深零守卫线性域容差
NULL_LIN = 0.05                 # 深零守卫阈值（−26dB）
TOL_BETA_MMT = 1e-6             # 既有钉（G3）
TOL_BETA_HFSS = 5e-3            # 0.5%（criteria §1）
TOL_MMT_S11_STRAIGHT = 1e-9     # 直段模态锚（MMT 单段无反射，解析恒 0）
TOL_HFSS_S11_STRAIGHT = 0.01    # 直段模态锚（HFSS FEM 残差）
TOL_HFSS_S21_STRAIGHT = 0.005   # 直段模态 |S21| 偏差（=1 解析）
TOL_ROUNDTRIP = 1e-12
SYS_SIGN_FRAC = 0.8             # 判向：符号一致性阈值
TIE_DB = 0.05
IRIS_CASES = ("iris_t0", "iris_t1")
ALL_DESIGNS = ("p3_straight", "p3_iris_t0", "p3_iris_t1")


# ── 闭式裁判与基变换（独立重算；β 走 calculators 单源=既有钉同源）─────────

def beta_ref(f_hz: float) -> float:
    from rfauto.core.calculators import siw_beta_rad_m

    b, _fc = siw_beta_rad_m(A_MM, 1.0, f_hz / 1e9)
    return float(b)


def renorm_s(s: np.ndarray, z_from: list[float],
             z_to: list[float]) -> np.ndarray:
    """N 口功率波 S 参考阻抗变换（Z 矩阵中转；z0 实正。rwg_mmt
    renormalize_2port 同式推广，y1 _renorm_s 先例）——奇异显式报错。"""
    n = s.shape[0]
    zf = np.asarray(z_from, float)
    zt = np.asarray(z_to, float)
    eye = np.eye(n)
    z_mat = (np.sqrt(zf)[:, None] * np.linalg.solve(eye - s, eye + s)
             * np.sqrt(zf)[None, :])
    return (np.diag(1.0 / np.sqrt(zt))
            @ (z_mat - np.diag(zt)) @ np.linalg.solve(z_mat + np.diag(zt),
                                                      np.diag(np.sqrt(zt))))


def mmt_modal_s(mmt: dict) -> tuple[np.ndarray, np.ndarray]:
    """MMT 50Ω S（meta）反归一回 TE10 模基（Z_TE=ωμ0/β 解析逐频）。

    v3（缺陷①修复后版本）：以归档完整 2×2
    [[s11,s12],[s21,s22]] 重建后反归一——v2 曾以 [[s11,s21],[s21,s11]] 对称
    假定重建，而归档 meta s22≠s11（旧 core 端口交换缺陷在档证据），模态腿
    被污染（judge −13.146 vs 真模态 −12.957 dB @8GHz 实例）。straight 例
    s22==s11 逐位 → 直段锚面零变化。"""
    freqs = mmt["freqs_hz"]
    n = freqs.size
    s50 = np.full((n, 2, 2), np.nan + 1j * np.nan, complex)
    s50[:, 0, 0] = mmt["s11"]
    s50[:, 1, 0] = mmt["s21"]
    s50[:, 0, 1] = mmt["s12"]
    s50[:, 1, 1] = mmt["s22"]
    out = np.full_like(s50, np.nan + 1j * np.nan)
    for i in range(n):
        if not mmt["determined"][i]:
            continue
        beta = complex(mmt["meta"]["beta_te10_ports"][i][0][0],
                       mmt["meta"]["beta_te10_ports"][i][0][1]).real
        z_te = 2.0 * math.pi * float(freqs[i]) * MU0 / beta
        out[i] = renorm_s(s50[i], [Z0, Z0], [z_te, z_te])
    return out, s50


def line_s_closed(f_hz: np.ndarray, length_m: float) -> dict[str, np.ndarray]:
    """均匀波导段 50Ω 基闭式 S（criteria §0 完整式；合成回收裁判用）。"""
    s11 = np.zeros(f_hz.shape, complex)
    s21 = np.zeros(f_hz.shape, complex)
    for i, f in enumerate(f_hz):
        b = beta_ref(float(f))
        z_te = 2.0 * math.pi * float(f) * MU0 / b
        gam = (z_te - Z0) / (z_te + Z0)
        t = complex(math.cos(b * length_m), -math.sin(b * length_m))
        s11[i] = gam * (1 - t * t) / (1 - gam * gam * t * t)
        s21[i] = t * (1 - gam * gam) / (1 - gam * gam * t * t)
    return {"s11": s11, "s21": s21}


# ── 载入与对齐 ────────────────────────────────────────────────────────────

def load_mmt(case: str) -> dict:
    meta = json.loads(
        (WORK / "mmt" / case / "mmt_meta.json").read_text(encoding="utf-8"))
    freqs = np.asarray(meta["freqs_ghz"], float) * 1e9
    n = freqs.size

    def arr(key: str) -> np.ndarray:
        out = np.full(n, np.nan + 1j * np.nan, complex)
        for i, v in enumerate(meta[key]):
            if v is not None:
                out[i] = complex(v[0], v[1])
        return out

    return {"meta": meta, "freqs_hz": freqs, "s11": arr("s11"),
            "s21": arr("s21"), "s12": arr("s12"), "s22": arr("s22"),
            "determined": np.asarray([v is not None for v in meta["s11"]])}


def load_hfss_snp(case: str) -> tuple[np.ndarray, np.ndarray]:
    import skrf

    net = skrf.Network(str(WORK / "hfss" / f"p3_{case}.s2p"))
    return net.frequency.f.astype(float), np.asarray(net.s, dtype=complex)


def align_indices(f_hfss: np.ndarray, f_mmt: np.ndarray) -> np.ndarray:
    """最近邻对齐（#287/#294：禁 searchsorted，argmin|Δf| 真最近邻）。"""
    idx = np.empty(f_hfss.size, dtype=int)
    for i, f in enumerate(f_hfss):
        idx[i] = int(np.argmin(np.abs(f_mmt - f)))
    return idx


# ── 对拍核（selftest 与真机同路径）────────────────────────────────────────

def dev_entry(s_m: complex, s_h: complex) -> dict:
    am, ah = abs(s_m), abs(s_h)
    if min(am, ah) < NULL_LIN:                      # 深零守卫（线性域）
        return {"domain": "linear", "metric": abs(am - ah),
                "tol": TOL_LIN_NULL, "ok": bool(abs(am - ah)
                                                <= TOL_LIN_NULL),
                "s_m_db": 20 * math.log10(am + 1e-300),
                "s_h_db": 20 * math.log10(ah + 1e-300),
                "signed_db": None}
    d_db = 20 * math.log10(ah + 1e-300) - 20 * math.log10(am + 1e-300)
    return {"domain": "db", "metric": abs(d_db), "tol": TOL_DB_MAIN,
            "ok": bool(abs(d_db) <= TOL_DB_MAIN),
            "s_m_db": 20 * math.log10(am + 1e-300),
            "s_h_db": 20 * math.log10(ah + 1e-300), "signed_db": d_db}


def summarize(e11: list[dict], e21: list[dict]) -> dict:
    signed = [e["signed_db"] for e in e11 if e["signed_db"] is not None]
    med = float(np.median(signed)) if signed else None
    n_tie = sum(1 for d in signed if abs(d) < TIE_DB)
    n_same = sum(1 for d in signed
                 if med is not None and np.sign(d) == np.sign(med))
    denom = max(len(signed) - n_tie, 1)
    return {"n_judged": len(e11),
            "max_dev_s11": max((e["metric"] for e in e11), default=None),
            "max_dev_s21": max((e["metric"] for e in e21), default=None),
            "ok_s11": bool(e11) and all(e["ok"] for e in e11),
            "ok_s21": bool(e21) and all(e["ok"] for e in e21),
            "n_null_guard": sum(1 for e in e11 + e21
                                if e["domain"] == "linear"),
            "signed_median_db": med,
            "sign_consistency": (n_same / denom if signed else None)}


def compare_pairs(freqs_hz: np.ndarray, s11_m: np.ndarray, s21_m: np.ndarray,
                  determined: np.ndarray, s_h: np.ndarray,
                  idx: np.ndarray) -> tuple[dict, list[list]]:
    """膜片例逐频对拍（仅 determined 点）；返回(汇总, 逐频行)。"""
    e11: list[dict] = []
    e21: list[dict] = []
    rows: list[list] = []
    for i in range(freqs_hz.size):
        if not determined[i]:
            continue
        j = int(idx[i])
        de11 = dev_entry(s11_m[i], s_h[j, 0, 0])
        de21 = dev_entry(s21_m[i], s_h[j, 1, 0])
        e11.append(de11)
        e21.append(de21)
        rows.append([round(freqs_hz[i] / 1e9, 8), de11["s_m_db"],
                     de11["s_h_db"], de11["metric"], de11["domain"],
                     de11["signed_db"], de21["s_m_db"], de21["s_h_db"],
                     de21["metric"], de21["domain"], de21["signed_db"],
                     bool(de11["ok"] and de21["ok"])])
    return summarize(e11, e21), rows


def pairwise_verdict(cmp_res: dict, hfss_self_ok: bool, mmt_self_ok: bool,
                     hfss_self_data_ok: bool = True) -> str:
    if cmp_res["ok_s11"] and cmp_res["ok_s21"]:
        return "AGREE"
    systematic = (cmp_res["sign_consistency"] is not None
                  and cmp_res["sign_consistency"] >= SYS_SIGN_FRAC)
    if systematic and hfss_self_ok:
        return "AGREE_HFSS"
    if not hfss_self_ok and mmt_self_ok:
        # HFSS 自洽锚"真失败"（数据在场判不过）才可判 MMT；数据缺失
        # 属不可归因——UNKNOWN 不凑判（#122，§4.4 修订）
        return "AGREE_MMT" if hfss_self_data_ok else "UNKNOWN"
    return "DISAGREE"


# ── 锚 ────────────────────────────────────────────────────────────────────

def straight_anchors(mmt: dict, hfss_run: dict) -> dict:
    """直段锚 v2（模态基）：MMT β 钉 + HFSS β 全带 + 直段模态 S 恒等。"""
    out: dict = {}
    # ① MMT β 既有钉复核（≤1e-6，G3）
    freqs = mmt["freqs_hz"]
    b_mmt = np.asarray([complex(v[0][0], v[0][1]).real if v[0] else np.nan
                        for v in mmt["meta"]["beta_te10_ports"]])
    b_ref = np.asarray([beta_ref(float(f)) for f in freqs])
    with np.errstate(invalid="ignore"):
        rel = np.abs(b_mmt - b_ref) / b_ref
    rel = rel[np.isfinite(rel)]
    out["mmt_beta_pin"] = {
        "tol": TOL_BETA_MMT,
        "max_rel": float(rel.max()) if rel.size else None,
        "ok": bool(rel.size and rel.max() <= TOL_BETA_MMT)}
    # ② HFSS β（harvest 扫频面 Gamma 全带）vs 闭式 ≤0.5%
    hv = hfss_run.get("harvest", {}).get("p3_straight", {})
    gam = hv.get("expressions", {}).get("Gamma(P1)")
    entries: list[dict] = []
    if gam:
        fr = np.asarray(hv["freqs_ghz"], float)
        for i in range(fr.size):
            g = complex(gam[0][i], gam[1][i])
            if not math.isfinite(g.imag):
                continue                      # 扫频首点 NaN 如实跳过（#287 族）
            b_cf = beta_ref(fr[i] * 1e9)
            entries.append({"f_ghz": float(fr[i]), "rel":
                            abs(g.imag - b_cf) / b_cf})
    max_rel = max((e["rel"] for e in entries), default=None)
    out["hfss_beta"] = {"tol": TOL_BETA_HFSS, "n_points": len(entries),
                        "max_rel": max_rel,
                        "ok": bool(entries and max_rel is not None
                                   and max_rel <= TOL_BETA_HFSS)}
    # ③ 直段模态恒等（MMT 反归一后 S11=0、|S21|=1；HFSS modal 残差门）
    modal, _ = mmt_modal_s(mmt)
    out["mmt_straight_modal"] = {
        "max_abs_s11": float(np.nanmax(np.abs(modal[:, 0, 0]))),
        "max_abs_s21_dev": float(np.nanmax(np.abs(np.abs(modal[:, 1, 0])
                                                  - 1.0))),
        "tol_s11": TOL_MMT_S11_STRAIGHT,
        "ok": bool(np.nanmax(np.abs(modal[:, 0, 0])) <= TOL_MMT_S11_STRAIGHT
                   and np.nanmax(np.abs(np.abs(modal[:, 1, 0]) - 1.0))
                   <= TOL_ROUNDTRIP)}
    f_h, s_h = load_hfss_snp("straight")
    idx = align_indices(f_h, freqs)
    mis = float(np.max(np.abs(f_h - freqs[idx])))
    out["hfss_straight_modal"] = {
        "max_freq_misalign_hz": mis,
        "max_abs_s11": float(np.max(np.abs(s_h[:, 0, 0]))),
        "max_abs_s21_dev": float(np.max(np.abs(np.abs(s_h[:, 1, 0]) - 1.0))),
        "tol_s11": TOL_HFSS_S11_STRAIGHT,
        "tol_s21": TOL_HFSS_S21_STRAIGHT,
        "ok": bool(np.max(np.abs(s_h[:, 0, 0])) <= TOL_HFSS_S11_STRAIGHT
                   and np.max(np.abs(np.abs(s_h[:, 1, 0]) - 1.0))
                   <= TOL_HFSS_S21_STRAIGHT)}
    # ④ 端口 Zo 表征旁证（首轮基失真证据链：harvest Zo vs 解析 Z_TE）
    zo = hv.get("expressions", {}).get("Zo(P1)")
    if zo:
        fr = np.asarray(hv["freqs_ghz"], float)
        ratios = []
        for i in range(fr.size):
            z = complex(zo[0][i], zo[1][i])
            if abs(z) < 1e-9:
                continue
            b_cf = beta_ref(fr[i] * 1e9)
            z_te = 2.0 * math.pi * fr[i] * 1e9 * MU0 / b_cf
            ratios.append(abs(z) / z_te)
        out["hfss_port_zo_note"] = {
            "zo_over_zte_median": float(np.median(ratios)) if ratios else None,
            "note": "HFSS 波端口阻抗表征/解析 Z_TE——≪1 即欠收敛证据"
                    "（首轮 0.548；模态基对拍不受其影响， informational）"}
    return out


# ── 汇总判读 ──────────────────────────────────────────────────────────────

def judge() -> dict:
    out: dict = {"gate": "dp1_p3_g1",
                 "criteria": "runs/df6_dp1p3/criteria.md §1 + §4 v2 修订",
                 "basis": "modal（HFSS renormalize=False vs MMT TE10 模基）",
                 "tolerances": {"main_db": TOL_DB_MAIN,
                                "null_linear": TOL_LIN_NULL,
                                "beta_mmt": TOL_BETA_MMT,
                                "beta_hfss": TOL_BETA_HFSS,
                                "straight_modal": {
                                    "mmt_s11": TOL_MMT_S11_STRAIGHT,
                                    "hfss_s11": TOL_HFSS_S11_STRAIGHT,
                                    "hfss_s21": TOL_HFSS_S21_STRAIGHT}},
                 "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    hfss_run = json.loads(
        (WORK / "hfss_run.json").read_text(encoding="utf-8"))
    designs = hfss_run.get("designs", {})
    # G1-conv（#335：末级收敛+未触顶才采信；阶梯逐级落档）
    conv: dict = {}
    for kind in ALL_DESIGNS:
        d = designs.get(kind)
        if d is None:
            conv[kind] = {"trusted": False, "reason": "设计缺失/未完成"}
            continue
        last = d["levels"][-1]
        conv[kind] = {"trusted": bool(d.get("trusted")),
                      "converged_final": d.get("converged_final"),
                      "hit_max_passes_final": d.get("hit_max_passes_final"),
                      "passes": last["passes"],
                      "delta_s_final": last["delta_s_final"],
                      "max_delta_s": last["max_delta_s"],
                      "ladder": [{"max_delta_s": lv["max_delta_s"],
                                  "passes": lv["passes"],
                                  "delta_s_final": lv["delta_s_final"]}
                                 for lv in d["levels"]]}
    out["g1_conv"] = conv
    trusted_all = all(bool(v.get("trusted")) for v in conv.values())
    # MMT undetermined 旁证
    mmt = {c: load_mmt(c) for c in ("straight", *IRIS_CASES)}
    und_note: dict = {}
    for c in IRIS_CASES:
        und = mmt[c]["meta"]["undetermined_freqs_ghz"]
        und_note[c] = {"n_undetermined": len(und),
                       "band_ghz": ([min(und), max(und)] if und else None),
                       "note": "近截止带 MMT 如实 NaN，对拍只在 "
                               "determined 点判"}
    out["mmt_undetermined_note"] = und_note
    # 锚
    out["g1_anchor_straight"] = straight_anchors(mmt["straight"], hfss_run)
    # HFSS 自洽锚数据在场性（harvest Gamma 曲线/单点在场=可归因；
    # 数据缺失→UNKNOWN 不凑判，§4.4 修订）
    hv = hfss_run.get("harvest", {}).get("p3_straight", {})
    n_gamma = len(hv.get("expressions", {}).get("Gamma(P1)", [[]])[0])
    hfss_self_data_ok = bool(n_gamma > 0)
    out["hfss_self_data_ok"] = hfss_self_data_ok
    mmt_self_ok = bool(
        out["g1_anchor_straight"]["mmt_beta_pin"]["ok"]
        and out["g1_anchor_straight"]["mmt_straight_modal"]["ok"])
    hfss_self_ok = bool(
        trusted_all
        and out["g1_anchor_straight"]["hfss_beta"]["ok"]
        and out["g1_anchor_straight"]["hfss_straight_modal"]["ok"])
    out["self_consistency"] = {   # #350 双记本体（两侧各自陈述）
        "hfss_self": {
            "convergence_all": trusted_all,
            "beta_anchor": out["g1_anchor_straight"]["hfss_beta"]["ok"],
            "straight_modal": out["g1_anchor_straight"]
            ["hfss_straight_modal"]["ok"],
            "ok": hfss_self_ok},
        "mmt_self": {
            "beta_pin": out["g1_anchor_straight"]["mmt_beta_pin"]["ok"],
            "straight_modal": out["g1_anchor_straight"]
            ["mmt_straight_modal"]["ok"],
            "ok": mmt_self_ok}}
    # G1-main（膜片两例，模态基，determined 点）+ 逐频表
    cases: dict = {}
    table: dict = {}
    for c in IRIS_CASES:
        if not conv[f"p3_{c}"].get("trusted"):
            cases[c] = {"verdict": "UNKNOWN", "reason": "G1-conv 未过/缺失"}
            continue
        f_h, s_h = load_hfss_snp(c)
        m = mmt[c]
        idx = align_indices(f_h, m["freqs_hz"])
        mis = float(np.max(np.abs(f_h - m["freqs_hz"][idx])))
        modal_m, _ = mmt_modal_s(m)
        cmp_res, rows = compare_pairs(m["freqs_hz"], modal_m[:, 0, 0],
                                      modal_m[:, 1, 0], m["determined"],
                                      s_h, idx)
        table[c] = rows
        cases[c] = {
            "max_freq_misalign_hz": mis,
            "freq_misalign_ok": bool(mis <= 1e3),
            **{k: cmp_res[k] for k in (
                "n_judged", "max_dev_s11", "max_dev_s21", "ok_s11",
                "ok_s21", "n_null_guard", "signed_median_db",
                "sign_consistency")},
            "n_undetermined_skipped": int((~m["determined"]).sum()),
            "gate_db": TOL_DB_MAIN,
            "verdict": pairwise_verdict(cmp_res, hfss_self_ok,
                                        mmt_self_ok, hfss_self_data_ok)}
    out["g1_main"] = cases
    out["_rows"] = table
    # 预算（预声明 40-60min/例，>90=PARTIAL 超预算如实落档）
    per = {k: v.get("wall_clock_min") for k, v in designs.items()}
    out["budget"] = {"pre_declared": {"min": 40, "max": 60,
                                      "partial_over": 90},
                     "per_design_wall_min": per,
                     "session_wall_min": hfss_run.get("budget", {})
                     .get("session_wall_min"),
                     "partial_designs": [k for k, v in per.items()
                                         if v is not None and v > 90]}
    # 会话孤儿核验（HFSS 脚本收尾 + 判读时独立复核，双落档）
    out["session"] = {"hfss_script": hfss_run.get("session", {}),
                      "judge_time": _live_orphan_check()}
    # overall（#350：混向=不可单边采信）
    verdicts = [cases[c].get("verdict", "UNKNOWN") for c in IRIS_CASES]
    if not trusted_all or any(v == "UNKNOWN" for v in verdicts) \
            or hfss_run.get("fatal"):
        overall = "UNKNOWN"
    elif all(v == "AGREE" for v in verdicts):
        overall = "AGREE"
    elif any(v == "DISAGREE" for v in verdicts):
        overall = "DISAGREE"
    elif len(set(verdicts)) == 1:
        overall = verdicts[0]
    else:
        overall = "DISAGREE"
    out["overall_verdict"] = overall
    if out["budget"]["partial_designs"]:
        out["budget_verdict"] = "PARTIAL(超预算)"
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return out


def _live_orphan_check() -> dict:
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes

        procs = list_ansysedt_processes()
        return {"ansysedt_pids": [p["pid"] for p in procs],
                "zero_orphan": len(procs) == 0}
    except Exception as exc:
        return {"error": f"孤儿核验失败: {exc!r}"}


# ── 合成回收自检（#340：裁判先过已知基准）─────────────────────────────────

def selftest() -> int:
    freqs = np.linspace(8.0, 12.0, 201) * 1e9
    cf = line_s_closed(freqs, L_MM * 1e-3)      # 独立闭式 50Ω 线式
    # ① 反归一回收：闭式 50Ω S 反归一回 Z_TE 基须恒等恢复 S=[[0,T],[T,0]]
    for i in (0, 50, 100, 150, 200):
        f = freqs[i]
        b = beta_ref(float(f))
        z_te = 2.0 * math.pi * float(f) * MU0 / b
        s50 = np.array([[cf["s11"][i], cf["s21"][i]],
                        [cf["s21"][i], cf["s11"][i]]])
        mod = renorm_s(s50, [Z0, Z0], [z_te, z_te])
        t = complex(math.cos(b * L_MM * 1e-3), -math.sin(b * L_MM * 1e-3))
        assert abs(mod[0, 0]) <= TOL_MMT_S11_STRAIGHT, \
            f"反归一回收失败: |S11_modal|={abs(mod[0, 0])}"
        assert abs(abs(mod[1, 0]) - 1.0) <= 1e-12, "模态 |S21|≠1"
        assert abs(mod[1, 0] - t) <= 1e-9, "模态 S21≠e^-jβL"
    # ② roundtrip：renorm 双向可逆 ≤1e-12
    rng = np.random.default_rng(7)
    a = rng.uniform(0.2, 0.8)
    s_test = np.array([[0.3 + 0.1j, 0.9 - 0.2j], [0.9 - 0.2j, 0.2 + 0.05j]])
    s_rt = renorm_s(renorm_s(s_test, [Z0, Z0], [a * 1000, a * 1000]),
                    [a * 1000, a * 1000], [Z0, Z0])
    assert float(np.max(np.abs(s_rt - s_test))) <= TOL_ROUNDTRIP, \
        "renorm roundtrip 超差"
    # ③ 注入偏差：HFSS 侧 |S11| ×1.2（+1.58dB）→ 门旗抓到+方向系统性
    det = np.ones(freqs.shape, bool)
    idx = np.arange(freqs.size)
    s_h = np.stack([np.stack([cf["s11"], cf["s21"]], axis=-1),
                    np.stack([cf["s21"], cf["s11"]], axis=-1)], axis=-2)
    cmp0, _ = compare_pairs(freqs, cf["s11"], cf["s21"], det, s_h, idx)
    assert cmp0["ok_s11"] and cmp0["ok_s21"], "恒等回收门未过"
    s_h_bias = s_h.copy()
    s_h_bias[:, 0, 0] *= 1.2
    cmp1, _ = compare_pairs(freqs, cf["s11"], cf["s21"], det, s_h_bias, idx)
    assert not cmp1["ok_s11"], "注入偏差未被门旗抓到"
    assert cmp1["sign_consistency"] >= SYS_SIGN_FRAC, "方向系统性未检出"
    print(f"SELFTEST_OK (反归一恒等恢复+roundtrip≤1e-12；注入×1.2 幅度 "
          f"max_dev={cmp1['max_dev_s11']:.4f} 门旗抓到、符号一致性="
          f"{cmp1['sign_consistency']:.3f})")
    return 0


# ── 产物 ──────────────────────────────────────────────────────────────────

def write_csv(table: dict, out_dir: Path | None = None) -> Path:
    path = (out_dir or WORK) / "sparam_diff_table.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "f_ghz", "s11_mmt_db", "s11_hfss_db", "ds11",
                    "ds11_domain", "ds11_signed_db", "s21_mmt_db",
                    "s21_hfss_db", "ds21", "ds21_domain", "ds21_signed_db",
                    "ok"])
        for case, rows in table.items():
            for r in rows:
                w.writerow([case, *r])
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="DP-1 P3 G1 判读 v3（离线）")
    ap.add_argument("--selftest", action="store_true",
                    help="合成回收自检后退出，不读真机产物")
    ap.add_argument("--out-dir", default=None,
                    help="产物目录（缺省=归档 runs/df6_dp1p3，行为不变；"
                         "重算对照批用 --out-dir 落 addendum 目录，归档零改写）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    out = judge()
    table = out.pop("_rows", {})
    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir or WORK).joinpath("g1_verdict.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    csv_path = write_csv(table, out_dir)
    n_rows = sum(len(v) for v in table.values())
    print(f"verdict={out['overall_verdict']} rows={n_rows} csv={csv_path}")
    for c, v in out["g1_main"].items():
        print(f"  {c}: {v.get('verdict')} max_dS11={v.get('max_dev_s11')}"
              f" max_dS21={v.get('max_dev_s21')} "
              f"n_judged={v.get('n_judged')}")
    print("G1_JUDGE_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
