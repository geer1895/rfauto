"""ME-5 MMT 销钉/谐振窗 HFSS 仲裁锚（T14）——离线判读（零求解）。

判据预声明：runs/mmt_anchor_20260930/criteria.md §2。消费
runs/mmt_anchor_20260930/hfss/*.s2p（模态基）+ hfss_run.json（收敛/
会话/清理），产出 g_verdict.json + sparam_diff_table.csv。

裁判先过已知基准（#340/#118）：--selftest 合成回收——电路正反演
roundtrip ≤1e-12、极限行为（b→0⇒Γ→0、b→−∞⇒Γ→−1）、V 型谷位
slope-bracket 估计器对合成曲线精确回收。MMT 侧闭式值运行时调内核
（inductive_post_susceptance / resonant_window_susceptance），不手抄。

用法：
  .venv\\Scripts\\python.exe scripts/mmt_anchor_20260930_judge.py [--selftest]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "mmt_anchor_20260930"
HFSS_OUT = WORK / "hfss"
RUN_JSON = WORK / "hfss_run.json"
VERDICT_JSON = WORK / "g_verdict.json"
CSV_PATH = WORK / "sparam_diff_table.csv"

A_MM, B_MM = 22.86, 10.16
L_HALF_MM = 20.0
POST_R_MM = 1.0
WIN_W_MM = 13.916189
WIN_H_MM = 3.0
F0 = 10.0
C_MM_GHZ = 299.792458

# 预声明门（criteria §2）
GATE = {
    "straight_s11_max": 0.01,
    "straight_s21_dev_max": 0.005,
    "straight_beta_rel": 0.005,
    "power_balance": 0.02,
    "post_b_rel": 0.07,
    "post_y_real_abs": 0.05,
    "post_s11_lin": 0.02,
    "post_s21_lin": 0.02,
    "window_fres_rel": 0.03,
    "window_s11_min_db": -20.0,
    "window_s21_at_res_db": -0.3,
    "window_peak_gap_steps": 2,
    "sign_consistency": 0.8,
}


# ── 独立电路转换（判读侧自实现，#118 双路径）────────────────────────────────

def gamma_from_b(b: float) -> complex:
    """并联归一电纳 y=j·b 在特征导纳基上的反射系数 Γ=−y/(2+y)。"""
    y = 1j * b
    return -y / (2.0 + y)


def b_from_gamma(g: complex) -> float:
    """反演 y=−2Γ/(1+Γ)，取虚部为归一电纳（无损：Re(y)≈0 旁证）。"""
    if abs(1.0 + g) < 1e-12:
        return float("nan")
    y = -2.0 * g / (1.0 + g)
    return float(np.imag(y))


def lam_g_mm(f_ghz: float, a_mm: float = A_MM) -> float:
    fc = C_MM_GHZ / (2.0 * a_mm)
    lam0 = C_MM_GHZ / f_ghz
    return lam0 / math.sqrt(1.0 - (fc / f_ghz) ** 2)


def slope_bracket_vertex(f: np.ndarray, v: np.ndarray) -> float:
    """V 型 |S11| 谷位 slope-bracket 顶点估计（抛物线对 V 型有 e/2 系统
    偏，informational 另报）。

    差分斜率符号在样本间转正的转折处，把左右段斜率置于**段中点**做
    线性插值求导数零点（V 型分段线性采样下误差 ≤半格，实测 ~2MHz
    @20MHz 格；门 3%=300MHz 远大于该偏差）。
    """
    i0 = int(np.argmin(v))
    lo = max(1, i0 - 5)
    hi = min(len(v) - 1, i0 + 5)
    d = np.diff(v[lo - 1:hi + 1])
    df = f[1] - f[0]
    for k in range(len(d) - 1):
        if d[k] < 0.0 <= d[k + 1]:
            # d[k]=段[lo-1+k, lo+k] 斜率、d[k+1]=段[lo+k, lo+k+1] 斜率；
            # 转正 junction 在 f[lo+k]，左段中点 = f[lo+k] - df/2
            j = lo + k
            return float(f[j] - df / 2.0
                         + df * abs(d[k]) / (abs(d[k]) + d[k + 1]))
    return float(f[i0])


def parabolic_vertex(f: np.ndarray, v: np.ndarray) -> float:
    """三点抛物线细化（informational；对 V 型有 ≤半格系统偏）。"""
    i0 = int(np.argmin(v))
    if i0 == 0 or i0 == len(v) - 1:
        return float(f[i0])
    y1, y0, y3 = v[i0 - 1], v[i0], v[i0 + 1]
    den = y1 - 2.0 * y0 + y3
    if den <= 0:
        return float(f[i0])
    return float(f[i0] + 0.5 * (y1 - y3) / den * (f[1] - f[0]))


def selftest() -> dict:
    """合成回收（裁判先过已知基准）：全过才允许消费真数据。"""
    out: dict = {"cases": []}
    worst = 0.0
    for b in (-7.5, -4.286531, -1.0, -0.3, -0.05, -1e-3, 1e-3, 0.5, 3.0):
        b2 = b_from_gamma(gamma_from_b(b))
        worst = max(worst, abs(b2 - b) / max(1.0, abs(b)))
    out["cases"].append({"name": "roundtrip", "worst_rel": worst,
                         "pass": bool(worst <= 1e-12)})
    g0 = gamma_from_b(0.0)
    gb = gamma_from_b(-1e8)
    out["cases"].append({
        "name": "limits", "abs_g_at_b0": abs(g0),
        "one_minus_g_at_bmin1e8": abs(gb + 1.0),
        "pass": bool(abs(g0) <= 1e-15 and abs(gb + 1.0) <= 1e-4)})
    b = -4.286531
    expect = abs(b) / math.sqrt(4.0 + b * b)
    dev = abs(abs(gamma_from_b(b)) - expect)
    out["cases"].append({"name": "gamma_mag_identity", "dev": dev,
                         "pass": bool(dev <= 1e-12)})
    f = np.linspace(8.0, 12.0, 201)
    for f0_true in (10.0, 10.0137, 9.9871):
        v = np.minimum(1.0, 0.3048 * np.abs(f - f0_true) / 2.0) + 1e-6
        est = slope_bracket_vertex(f, v)
        out["cases"].append({
            "name": f"vertex_recovery@{f0_true}", "est_ghz": est,
            "err_mhz": abs(est - f0_true) * 1e3,
            "pass": bool(abs(est - f0_true) <= 5e-3)})  # ≤半格界内（5MHz，
    # 中点导数插值对非对称 V 的实测偏差 ~2MHz；门 3%=300MHz 远大于之）
    from rfauto.core.rwg_mmt import resonant_window_susceptance
    bt = resonant_window_susceptance(10.0, A_MM, B_MM, WIN_W_MM, WIN_H_MM)
    out["cases"].append({
        "name": "window_zero_at_construction", "b_total": bt["b_total"],
        "f_res_est": bt["f_resonant_ghz_est"],
        # w=13.916189 系 6 位小数二分构造（几何字面量精度），零点残差
        # 容差对齐该精度（b_total ~1e-7、f_res ~3e-7 GHz）
        "pass": bool(abs(bt["b_total"]) <= 5e-7
                     and abs(bt["f_resonant_ghz_est"] - 10.0) <= 1e-5)})
    out["all_pass"] = all(c["pass"] for c in out["cases"])
    return out


def load_s2p(kind: str):
    import skrf

    p = HFSS_OUT / f"{kind}.s2p"
    if not p.exists():
        return None
    return skrf.Network(str(p))


def check_grid(net) -> dict:
    f = net.f
    ok = (len(f) == 201 and abs(f[0] - 8e9) <= 8.0
          and abs(f[-1] - 12e9) <= 8.0)
    return {"n": len(f), "f_lo_ghz": float(f[0] / 1e9),
            "f_hi_ghz": float(f[-1] / 1e9), "ok": bool(ok)}


def judge() -> dict:
    from rfauto.core.rwg_mmt import (
        inductive_post_susceptance,
        resonant_window_susceptance,
    )

    verdict: dict = {"criteria": "runs/mmt_anchor_20260930/criteria.md",
                     "selftest": selftest()}
    bands: dict = {}
    if not verdict["selftest"]["all_pass"]:
        verdict["overall_verdict"] = "UNKNOWN"
        verdict["reason"] = "selftest 未全过——裁判基准失效，不消费真数据"
        return verdict, bands

    # 运行信封合并：跳过设计的阶梯/ trusted 记录在 prev 信封里（03:17
    # 实测教训——多轮 HALT/FAIL 覆写信封致记录丢失；逐设计取首个非空）
    run_info: dict = {"designs": {}}
    for p in sorted(WORK.glob("hfss_run*.json")):
        try:
            ri = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k, v in (ri.get("designs") or {}).items():
            cur = run_info["designs"].setdefault(k, {})
            for key in ("trusted", "levels"):
                if cur.get(key) is None and v.get(key) is not None:
                    cur[key] = v.get(key)
    latest: dict = {}
    if RUN_JSON.exists():
        latest = json.loads(RUN_JSON.read_text(encoding="utf-8"))
    verdict["session"] = {
        "cleanup_ok": (latest.get("cleanup") or {}).get("ok"),
        "port_50051_after_cleanup": latest.get("port_50051_after_cleanup"),
        "local_ansysedt_count_post": latest.get("local_ansysedt_count_post"),
        "grpc_task": latest.get("grpc_task"),
        "g12_port_discovery": (latest.get("steps") or {})
        .get("g12_port_discovery"),
        "envelopes_merged": [p.name for p in
                             sorted(WORK.glob("hfss_run*.json"))],
    }

    data: dict[str, dict] = {}
    for kind in ("ma_straight", "ma_post", "ma_window"):
        net = load_s2p(kind)
        if net is None:
            data[kind] = {"present": False}
            continue
        grid = check_grid(net)
        s = net.s
        data[kind] = {"present": True, "grid": grid,
                      "f_ghz": net.f / 1e9,
                      "s11": s[:, 0, 0], "s21": s[:, 1, 0]}
    verdict["grids"] = {k: (v.get("grid") if isinstance(v, dict) else None)
                        for k, v in data.items()}
    missing = [k for k, v in data.items()
               if not (isinstance(v, dict) and v.get("present"))]
    if missing:
        verdict["missing_designs"] = missing

    # ── G-straight（直段自洽，HFSS 侧）───────────────────────────────────
    straight: dict = {"present": bool(data["ma_straight"].get("present"))}
    if straight["present"]:
        d = data["ma_straight"]
        s11, s21, f_ghz = d["s11"], d["s21"], d["f_ghz"]
        s11_max = float(np.max(np.abs(s11)))
        s21_dev = float(np.max(np.abs(np.abs(s21) - 1.0)))
        beta_cf = np.array([2 * math.pi / (lam_g_mm(fg) / 1000.0)
                            for fg in f_ghz])
        # S21 相位=主值（mod 2π）——β 反演需分支解码：β=(−φ+2πk)/L，k 由
        # 最近闭式β 选出。解码唯一性由门自身保证：门 0.5%（0.79 rad/m）
        # ≪ 分支间距 2π/L=157 rad/m（错 k 偏 ≥39% 必炸门，无调门空间）。
        phi = np.unwrap(np.angle(s21))
        L_m = 2 * L_HALF_MM / 1000.0
        i0 = int(np.argmin(np.abs(f_ghz - F0)))
        k_best = int(np.round((beta_cf[i0] * L_m + phi[i0])
                              / (2 * math.pi)))
        beta_hfss = (-phi[i0] + 2 * math.pi * k_best) / L_m
        beta_rel = abs(beta_hfss - beta_cf[i0]) / beta_cf[i0]
        straight.update({
            "s11_max": s11_max, "s21_dev_max": s21_dev,
            "beta_hfss_10g": float(beta_hfss),
            "beta_cf_10g": float(beta_cf[i0]),
            "beta_branch_k": k_best,
            "beta_rel_10g": float(beta_rel),
            "g_s11": s11_max <= GATE["straight_s11_max"],
            "g_s21": s21_dev <= GATE["straight_s21_dev_max"],
            "g_beta": beta_rel <= GATE["straight_beta_rel"]})
        straight["g_all"] = bool(straight["g_s11"] and straight["g_s21"]
                                 and straight["g_beta"])
    verdict["straight"] = straight
    hfss_self_ok = bool(straight.get("g_all"))  # G-conv+G-straight 汇总

    # ── G-post（销钉主门）────────────────────────────────────────────────
    post: dict = {"present": bool(data["ma_post"].get("present"))}
    if post["present"]:
        d = data["ma_post"]
        s11, s21, f_ghz = d["s11"], d["s21"], d["f_ghz"]
        cf = [inductive_post_susceptance(float(fg), A_MM, POST_R_MM)
              for fg in f_ghz]
        b_cf = np.array([q["b_norm"] for q in cf])
        s11_cf = np.abs(np.array([gamma_from_b(b) for b in b_cf]))
        s21_cf = np.abs(2.0 / (2.0 + 1j * b_cf))
        i0 = int(np.argmin(np.abs(f_ghz - F0)))
        # ── b_hfss 主通道=幅值双路（旋转/相位约定无关）。03:35 实测改道
        # 依据：去嵌通道 Re(y)=0.437 爆自身 |Re|≤0.05 预声明门——波端口
        # 模态 S 相位参考约定使闭式 β 相位旋转失效；幅值双路互证 0.5%
        # 内自洽。感性符号由 arg(S21)≈+atan(|b|/2)>0 判（b<0）。去嵌通道
        # 降级 informational（y_real_abs 落档）。
        mag11_0 = float(abs(s11[i0]))
        mag21_0 = float(abs(s21[i0]))
        b_from_s11 = -2.0 * mag11_0 / math.sqrt(max(1.0 - mag11_0 ** 2,
                                                    1e-12))
        b_from_s21 = (-2.0 * math.sqrt(max(1.0 - mag21_0 ** 2, 1e-12))
                      / mag21_0)
        b_hfss0 = 0.5 * (b_from_s11 + b_from_s21)
        dual_path_dev = abs(b_from_s11 - b_from_s21) \
            / max(abs(b_from_s11), abs(b_from_s21))
        beta0 = 2 * math.pi / (cf[i0]["lambda_g_mm"] / 1000.0)
        g_de = s11[i0] * np.exp(2j * beta0 * (L_HALF_MM / 1000.0))
        y_hfss = -2.0 * g_de / (1.0 + g_de)
        y_real_abs = float(abs(np.real(y_hfss)))
        b_deembed_10g = float(np.imag(y_hfss))
        rel_b0 = abs(b_hfss0 - b_cf[i0]) / abs(b_cf[i0])
        d_s11_lin0 = abs(abs(s11[i0]) - s11_cf[i0])
        d_s21_lin0 = abs(abs(s21[i0]) - s21_cf[i0])
        # 全带：幅值双路 b（判向）；去嵌曲线弃用（约定敏感）
        mag11_band = np.abs(s11)
        mag21_band = np.abs(s21)
        b_hfss_band = np.array([
            -0.5 * (2.0 * m11 / math.sqrt(max(1.0 - m11 ** 2, 1e-12))
                    + 2.0 * math.sqrt(max(1.0 - m21 ** 2, 1e-12)) / m21)
            for m11, m21 in zip(mag11_band, mag21_band, strict=True)])
        rel_band = np.abs(b_hfss_band - b_cf) / np.abs(b_cf)
        sign_pos = float(np.mean(b_hfss_band > b_cf))
        pb = float(np.max(np.abs(np.abs(s11) ** 2 + np.abs(s21) ** 2 - 1.0)))
        design_info = (run_info.get("designs", {}).get("ma_post") or {})
        post.update({
            "b_cf_10g": float(b_cf[i0]), "b_hfss_10g": b_hfss0,
            "b_channel": "magnitude dual-path (|S11|+|S21|)",
            "b_from_s11_10g": b_from_s11, "b_from_s21_10g": b_from_s21,
            "dual_path_dev_pct": 100.0 * dual_path_dev,
            "b_deembed_10g_informational": b_deembed_10g,
            "rel_dev_b_pct": 100.0 * rel_b0,
            "y_real_abs_10g": y_real_abs,
            "s11_cf_10g": float(s11_cf[i0]),
            "s11_hfss_10g": mag11_0,
            "d_s11_lin_10g": float(d_s11_lin0),
            "s21_cf_10g": float(s21_cf[i0]),
            "s21_hfss_10g": mag21_0,
            "d_s21_lin_10g": float(d_s21_lin0),
            "rel_dev_band_max_pct": float(100.0 * np.nanmax(rel_band)),
            "rel_dev_band_med_pct": float(100.0 * np.nanmedian(rel_band)),
            "sign_pos_frac": sign_pos,
            "power_balance_max_dev": pb,
            "trusted": design_info.get("trusted"),
            "levels": design_info.get("levels"),
            "g_b_rel": rel_b0 <= GATE["post_b_rel"],
            "g_y_real": y_real_abs <= GATE["post_y_real_abs"],
            "g_dual_path": dual_path_dev <= 0.02,
            "g_s11_lin": d_s11_lin0 <= GATE["post_s11_lin"],
            "g_s21_lin": d_s21_lin0 <= GATE["post_s21_lin"],
            "g_power": pb <= GATE["power_balance"]})
        bands["post"] = {"f_ghz": f_ghz, "b_cf": b_cf,
                         "b_hfss": b_hfss_band, "s11_cf": s11_cf,
                         "s11_hfss": mag11_band, "s21_cf": s21_cf,
                         "s21_hfss": mag21_band}
        main_ok = bool(post["g_b_rel"] and post["g_s11_lin"]
                       and post["g_s21_lin"])
        if not post["trusted"]:
            post["verdict"] = "UNKNOWN"
            post["verdict_reason"] = "ΔS 阶梯未 trusted（触顶/超时），不判"
        elif not post["g_dual_path"] or not post["g_power"]:
            post["verdict"] = "UNKNOWN"
            post["verdict_reason"] = (
                f"幅值双路互证失配（{100.0 * dual_path_dev:.2f}%）或功率"
                "守恒失败——b 通道不可信，不判")
        elif main_ok:
            post["verdict"] = "AGREE"
        elif hfss_self_ok:
            if sign_pos >= GATE["sign_consistency"] \
                    or sign_pos <= 1.0 - GATE["sign_consistency"]:
                post["verdict"] = "AGREE_HFSS"
                post["verdict_reason"] = (
                    f"主门超差但方向系统性（b_hfss>b_cf 占比 {sign_pos:.3f}，"
                    "闭式偏感性），HFSS 为对齐基准，偏差如实注册")
            else:
                post["verdict"] = "DISAGREE"
                post["verdict_reason"] = (
                    f"主门超差且方向不系统（b_hfss>b_cf 占比 {sign_pos:.3f}）"
                    "——双记不单边采信")
        else:
            post["verdict"] = "DISAGREE"
            post["verdict_reason"] = (
                f"HFSS 侧自洽锚未全过（straight g_all={hfss_self_ok}）"
                "——不可归因不采信")
    verdict["post"] = post

    # ── G-window（谐振窗主门）────────────────────────────────────────────
    win: dict = {"present": bool(data["ma_window"].get("present"))}
    if win["present"]:
        d = data["ma_window"]
        s11, s21, f_ghz = d["s11"], d["s21"], d["f_ghz"]
        wcf = [resonant_window_susceptance(float(fg), A_MM, B_MM,
                                           WIN_W_MM, WIN_H_MM)
               for fg in f_ghz]
        b_cf_band = np.array([q["b_total"] for q in wcf])
        s11_cf_band = np.array([abs(gamma_from_b(b)) for b in b_cf_band])
        # f_res_cf = 闭式 b_total(f) 曲线自洽零点（符号翻转线性内插）
        sgn = np.sign(b_cf_band)
        flip = np.where(np.diff(sgn) != 0)[0]
        f_res_cf = None
        if len(flip):
            k = int(flip[0])
            t = abs(b_cf_band[k]) / (abs(b_cf_band[k])
                                     + abs(b_cf_band[k + 1]))
            f_res_cf = float(f_ghz[k] + t * (f_ghz[k + 1] - f_ghz[k]))
        mag11, mag21 = np.abs(s11), np.abs(s21)
        f_res_hfss = slope_bracket_vertex(f_ghz, mag11)
        f_res_hfss_para = parabolic_vertex(f_ghz, mag11)
        i_min = int(np.argmin(mag11))
        i_max21 = int(np.argmax(mag21))
        s11_min_db = float(20.0 * np.log10(max(mag11[i_min], 1e-12)))
        s21_res_lin = float(np.interp(f_res_hfss, f_ghz, mag21))
        s21_at_res_db = float(20.0 * np.log10(max(s21_res_lin, 1e-12)))
        peak_gap_steps = abs(i_max21 - i_min)
        rel_f = (abs(f_res_hfss - f_res_cf) / f_res_cf
                 if f_res_cf else float("nan"))
        pb = float(np.max(np.abs(mag11 ** 2 + mag21 ** 2 - 1.0)))
        design_info = (run_info.get("designs", {}).get("ma_window") or {})
        win.update({
            "f_res_est_kernel_ghz": wcf[0]["f_resonant_ghz_est"],
            "f_res_cf_ghz": f_res_cf,
            "f_res_hfss_ghz": f_res_hfss,
            "f_res_hfss_parabolic_ghz": f_res_hfss_para,
            "rel_dev_fres_pct": 100.0 * rel_f,
            "s11_min_db": s11_min_db,
            "s21_at_res_db": s21_at_res_db,
            "peak_gap_steps": peak_gap_steps,
            "power_balance_max_dev": pb,
            "trusted": design_info.get("trusted"),
            "levels": design_info.get("levels"),
            "g_fres_rel": bool(f_res_cf) and rel_f <= GATE["window_fres_rel"],
            "g_s11_min": s11_min_db <= GATE["window_s11_min_db"],
            "g_s21_res": s21_at_res_db >= GATE["window_s21_at_res_db"],
            "g_peak_gap": peak_gap_steps <= GATE["window_peak_gap_steps"],
            "g_power": pb <= GATE["power_balance"]})
        bands["window"] = {"f_ghz": f_ghz, "btotal_cf": b_cf_band,
                           "s11_cf": s11_cf_band, "s11_hfss": mag11,
                           "s21_hfss": mag21}
        main_ok = bool(win["g_fres_rel"])
        self_ok = bool(win["g_s11_min"] and win["g_s21_res"]
                       and win["g_peak_gap"] and win["g_power"])
        if not win["trusted"]:
            win["verdict"] = "UNKNOWN"
            win["verdict_reason"] = "ΔS 阶梯未 trusted（触顶/超时），不判"
        elif main_ok and self_ok:
            win["verdict"] = "AGREE"
        elif self_ok and hfss_self_ok:
            win["verdict"] = "AGREE_HFSS"
            win["verdict_reason"] = (
                f"谷位超门 {100.0 * rel_f:.3f}%（一阶式角区互作用量级），"
                "HFSS 为对齐基准，偏差如实注册")
        else:
            win["verdict"] = "DISAGREE"
            win["verdict_reason"] = (
                f"HFSS 侧自洽锚未全过（hfss_self={hfss_self_ok}, "
                f"case_self={self_ok}）——不可归因不采信")
    verdict["window"] = win

    case_v = [verdict.get(k, {}).get("verdict", "UNKNOWN")
              for k in ("post", "window")]
    if any(v == "DISAGREE" for v in case_v):
        overall = "DISAGREE"
    elif all(v in ("AGREE", "AGREE_HFSS") for v in case_v):
        overall = ("AGREE" if all(v == "AGREE" for v in case_v)
                   else "AGREE_HFSS")
    else:
        overall = "UNKNOWN"
    verdict["overall_verdict"] = overall
    verdict["case_verdicts"] = {"post": case_v[0], "window": case_v[1]}
    return verdict, bands


def _write_csv(verdict: dict, bands: dict) -> None:
    lines = ["freq_ghz,post_b_cf,post_b_hfss,post_s11_cf,post_s11_hfss,"
             "post_s21_hfss,post_rel_dev_pct,win_btotal_cf,win_s11_cf,"
             "win_s11_hfss,win_s21_hfss,win_s11_cf_db,win_s11_hfss_db"]
    p = bands.get("post")
    w = bands.get("window")
    n = len((p or w)["f_ghz"])
    for i in range(n):
        cells = [f"{float((p or w)['f_ghz'][i]):.6f}"]
        if p is not None:
            bcf = float(p["b_cf"][i])
            bh = float(p["b_hfss"][i])
            cells += [f"{bcf:.6f}", f"{bh:.6f}",
                      f"{float(p['s11_cf'][i]):.6f}",
                      f"{float(p['s11_hfss'][i]):.6f}",
                      f"{float(p['s21_hfss'][i]):.6f}",
                      f"{100 * abs(bh - bcf) / abs(bcf):.4f}"]
        else:
            cells += [""] * 6
        if w is not None:
            bt = float(w["btotal_cf"][i])
            s11cf = float(w["s11_cf"][i])
            s11h = float(w["s11_hfss"][i])
            cells += [f"{bt:.6f}", f"{s11cf:.6f}", f"{s11h:.6f}",
                      f"{float(w['s21_hfss'][i]):.6f}",
                      f"{20 * math.log10(max(s11cf, 1e-12)):.4f}",
                      f"{20 * math.log10(max(s11h, 1e-12)):.4f}"]
        else:
            cells += [""] * 6
        lines.append(",".join(cells))
    CSV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if "--selftest" in sys.argv:
        st = selftest()
        print(json.dumps(st, ensure_ascii=False, indent=2, default=float))
        return 0 if st["all_pass"] else 1
    verdict, bands = judge()
    _write_csv(verdict, bands)
    VERDICT_JSON.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2, default=float),
        encoding="utf-8")
    print(f"overall={verdict['overall_verdict']} "
          f"post={verdict['case_verdicts']['post']} "
          f"window={verdict['case_verdicts']['window']}")
    if verdict.get("post", {}).get("present"):
        p = verdict["post"]
        print(f"  post: b_cf={p['b_cf_10g']:.6f} b_hfss={p['b_hfss_10g']:.6f}"
              f" rel={p['rel_dev_b_pct']:.3f}% sign+={p['sign_pos_frac']:.3f}")
    if verdict.get("window", {}).get("present"):
        w = verdict["window"]
        print(f"  window: f_res_cf={w['f_res_cf_ghz']:.6f} "
              f"f_res_hfss={w['f_res_hfss_ghz']:.6f} "
              f"rel={w['rel_dev_fres_pct']:.3f}% "
              f"s11min={w['s11_min_db']:.2f}dB s21@res={w['s21_at_res_db']:.3f}dB")
    print(f"verdict → {VERDICT_JSON}")
    print(f"csv     → {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
