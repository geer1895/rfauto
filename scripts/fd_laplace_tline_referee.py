"""C9 传输线族 II 准静态 FD 裁判 CLI（core/quasistatic_fd.py 薄壳；零仿真，秒级）。

用途：
  --nominal            打印 CPS/悬置带线标称几何裁判值（refs §11.1/§11.2 真值来源）
  --cps-family         CPS a/h×b/h 族：FD vs 定标闭式 vs 裸映射残差表（refs §11.1）
  --refit-cps-gamma    逐 εr 最小二乘有效厚度 γ 并幂律拟合 γ=1+C·εr^−P（复现
                       calculators.CPS_H_EFF_GAMMA_C/P；约 1~2 min）
  --ssl-series         悬置带线 h/b 序列（w=0.6 b=1.6）：FD vs 裸 q 式 vs 重定标
                       闭式残差（refs §11.2）
  --ssl-family         悬置带线 u=w/b×s=h/b 族：FD vs 重定标闭式残差表（§11.2）
  --refit-ssl-q        6u×6s×8εr FD 全局 LSQ 复现 softmin 修正族常数
                       （calculators.SSL_Q_G1/SSL_Q_G2/SSL_D/SSL_P；约 1~2 min）
  --cps-corner         CPS b/h 维角落扫描（a/h×b/h×εr）：适用域边界证据
                       （定标域外闭式低估表）
  --json PATH          结果落盘
数值纪律：只在确定性内核（本脚本不产生新常数，仅复现/打印）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.core.calculators import (
    CPS_H_EFF_GAMMA_C,
    CPS_H_EFF_GAMMA_P,
    SSL_D,
    SSL_P,
    SSL_Q_G1,
    SSL_Q_G2,
    _cps_ri,
    _kk_ratio,
    _stripline_z0,
    _suspended_stripline_ri,
)
from rfauto.core.quasistatic_fd import (
    cps_quasistatic,
    suspended_stripline_quasistatic,
)

ER, H = 3.66, 0.508
FIT_GEOMS = ((2.95, 0.5), (0.5, 0.5), (1.27, 0.508), (1.0, 0.2), (4.0, 1.0), (0.4, 0.1))
FIT_ERS = (1.5, 2.2, 3.0, 3.66, 4.4, 6.15, 10.2, 12.9)


def cps_closed_gamma(w: float, gap: float, h: float, er: float, gamma: float) -> float:
    """任意 γ 的 tanh 映射闭式（γ=1 裸映射；用于拟合，与 _cps_ri 同结构）。"""
    a, b = gap / 2.0, gap / 2.0 + w
    k3 = math.tanh(math.pi * a / (2 * h * gamma)) / math.tanh(math.pi * b / (2 * h * gamma))
    return 1.0 + (er - 1.0) * _kk_ratio(a / b) / (2.0 * _kk_ratio(k3))


def nominal() -> dict:
    cps = cps_quasistatic(2.95, 0.5, H, ER)
    ssl = suspended_stripline_quasistatic(0.9058, 1.016, H, ER)
    ssl_old = suspended_stripline_quasistatic(0.731, 1.016, H, ER)
    out = {
        "cps_nominal": {**cps.as_dict(), "closed_calibrated": _cps_ri(2.95, 0.5, H, ER),
                        "closed_bare": cps_closed_gamma(2.95, 0.5, H, ER, 1.0)},
        "ssl_nominal": {**ssl.as_dict(),
                        "closed_recalibrated": _suspended_stripline_ri(0.9058, 1.016, H, ER),
                        "z0_air_cohn": _stripline_z0(0.9058, 1.016, 1.0)},
        # 旧 q 式口径标称（FD 定案真值 εeff 2.092/Z0 56.1，历史锚保留）
        "ssl_old_nominal_w0.731": {**ssl_old.as_dict(),
                                   "closed_recalibrated": _suspended_stripline_ri(
                                       0.731, 1.016, H, ER),
                                   "z0_air_cohn": _stripline_z0(0.731, 1.016, 1.0)},
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def cps_family() -> list[dict]:
    rows = []
    for ah in (0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0):
        for bh in (1.5, 3.0, 6.0, 12.0):
            if bh <= ah:
                continue
            a, b = ah * H, bh * H
            w, gap = b - a, 2 * a
            fd = cps_quasistatic(w, gap, H, ER, d0_mm=min(H / 20, a / 4)).eps_eff
            cal = _cps_ri(w, gap, H, ER)[0]
            bare = cps_closed_gamma(w, gap, H, ER, 1.0)
            rows.append({"a_h": ah, "b_h": bh, "w_mm": round(w, 4), "gap_mm": round(gap, 4),
                         "fd": round(fd, 4), "calibrated_pct": round((cal / fd - 1) * 100, 2),
                         "bare_pct": round((bare / fd - 1) * 100, 2)})
            print(rows[-1], flush=True)
    return rows


def refit_cps_gamma() -> dict:
    from scipy.optimize import minimize_scalar

    per_er = {}
    for er in FIT_ERS:
        fds = [cps_quasistatic(w, g, H, er, d0_mm=min(H / 20, g / 8)).eps_eff
               for w, g in FIT_GEOMS]

        def cost(gm: float, er: float = er, fds: list[float] = fds) -> float:
            return sum(((cps_closed_gamma(w, g, H, er, gm) - e) / e) ** 2
                       for (w, g), e in zip(FIT_GEOMS, fds, strict=True))

        r = minimize_scalar(cost, bounds=(1.0, 3.0), method="bounded")
        errs = [(cps_closed_gamma(w, g, H, er, r.x) / e - 1) * 100
                for (w, g), e in zip(FIT_GEOMS, fds, strict=True)]
        per_er[er] = {"gamma_lsq": round(float(r.x), 4),
                      "max_abs_err_pct": round(max(abs(x) for x in errs), 2),
                      "fd": [round(x, 4) for x in fds]}
        print(er, per_er[er], flush=True)
    ers = np.array(FIT_ERS)
    gs = np.array([per_er[e]["gamma_lsq"] for e in FIT_ERS])
    p = np.polyfit(np.log(ers), np.log(gs - 1.0), 1)
    fit = {"C": round(float(math.exp(p[1])), 4), "P": round(float(-p[0]), 4),
           "registered": {"C": CPS_H_EFF_GAMMA_C, "P": CPS_H_EFF_GAMMA_P}}
    print("γ − 1 = C·εr^−P:", fit)
    return {"per_er": per_er, "fit": fit}


def _ssl_q_bare(u: float, s: float) -> float:
    """裸 q 式填充因子 r(k_b)/r(k_h)（重定标前的旧口径，对照列用）。"""
    k_b = math.tanh(math.pi * u / 2.0)
    r_b = _kk_ratio(k_b)
    if s <= 0:
        return 0.0
    k_h = math.tanh(math.pi * u / (2.0 * s))
    r_h = _kk_ratio(k_h)
    return min(max(r_b / r_h if math.isfinite(r_h) else 0.0, 0.0), 1.0)


def ssl_series() -> list[dict]:
    rows = []
    for hb in (0.0625, 0.1875, 0.3175, 0.5, 0.75, 0.994):
        h = hb * 1.6
        fd = suspended_stripline_quasistatic(0.6, 1.6, h, ER).eps_eff
        q = _ssl_q_bare(0.375, hb)
        cal = _suspended_stripline_ri(0.6, 1.6, h, ER)[0]
        rows.append({"h_b": hb, "fd": round(fd, 4),
                     "q_formula_bare": round(1.0 + (ER - 1.0) * q, 4),
                     "bare_pct": round(((1.0 + (ER - 1.0) * q) / fd - 1) * 100, 1),
                     "recalibrated": round(cal, 4),
                     "cal_pct": round((cal / fd - 1) * 100, 2)})
        print(rows[-1], flush=True)
    return rows


SSL_FIT_U = (0.1, 0.2, 0.375, 0.55, 0.719, 1.0)
SSL_FIT_S = (0.0625, 0.1875, 0.3175, 0.5, 0.75, 0.9)
SSL_VAL_U = (0.15, 0.3, 0.45, 0.62, 0.85)
SSL_VAL_S = (0.0625, 0.125, 0.4063, 0.625, 0.82)
SSL_B = 1.6


def ssl_family() -> list[dict]:
    rows = []
    for u in SSL_FIT_U:
        for s in SSL_FIT_S:
            fd = suspended_stripline_quasistatic(
                u * SSL_B, SSL_B, s * SSL_B, ER).eps_eff
            cal = _suspended_stripline_ri(u * SSL_B, SSL_B, s * SSL_B, ER)[0]
            rows.append({"u": u, "s": s, "fd": round(fd, 4),
                         "recalibrated": round(cal, 4),
                         "cal_pct": round((cal / fd - 1) * 100, 2)})
            print(rows[-1], flush=True)
    return rows


def refit_ssl_q() -> dict:
    """复现 SSL softmin 修正族常数（SSL_Q_G1/SSL_Q_G2/SSL_D/SSL_P）。

    结构与数据（6u×6s×8εr=288 点 FD 全局 LSQ）见 calculators._suspended_
    stripline_ri docstring；本函数为常数复现入口，拟合实现与定标批一致。
    """
    from scipy.optimize import least_squares

    def q_stable(u: float, s: float) -> float:
        """sech/AGM 稳定 q（与 calculators._kk_ratio_tanh 同口径）。"""
        from rfauto.core.calculators import _kk_ratio_tanh

        if s <= 0:
            return 0.0
        r_b = _kk_ratio_tanh(math.pi * u / 2.0)
        r_h = _kk_ratio_tanh(math.pi * u / (2.0 * s))
        q = r_b / r_h if math.isfinite(r_h) and r_h > 0 else 0.0
        return min(max(q, 0.0), 1.0)

    data = []
    for u in SSL_FIT_U:
        for s in SSL_FIT_S:
            for er in FIT_ERS:
                fd = suspended_stripline_quasistatic(
                    u * SSL_B, SSL_B, s * SSL_B, er).eps_eff
                data.append((u, s, er, fd))
    arr = np.array(data)
    us_a, ss_a, er_a = arr[:, 0], arr[:, 1], arr[:, 2]
    qs = np.array([q_stable(u, s) for u, s in zip(us_a, ss_a, strict=True)])
    bump = 4.0 * ss_a * (1.0 - ss_a)

    def model(params: np.ndarray) -> np.ndarray:
        a1, a1e, b1, mu1, a2, a2e, b2, mu2, d0_, d1_, d2_, p0_, p1_ = params
        g = (1.0 + us_a ** mu1 * a1 * ss_a ** a1e * (1.0 - ss_a) ** b1
             + us_a ** mu2 * a2 * ss_a ** a2e * (1.0 - ss_a) ** b2)
        d_cap = d0_ * (1.0 + us_a) ** d1_ * bump ** d2_
        p = p0_ + p1_ * ss_a
        dd = (er_a - 1.0) * qs * g
        return 1.0 + (dd ** (-p) + d_cap ** (-p)) ** (-1.0 / p)

    def res(params: np.ndarray) -> np.ndarray:
        return (model(params) - arr[:, 3]) / arr[:, 3]

    x0 = [0.85842, 0.003, 2.38305, -0.21519, 4.19252, 0.003, 8.57574, 0.1113,
          31.76642, -1.85399, -0.89951, 0.17662, 0.73466]
    lo = [0.0, 0.003, 0.2, -2.0, 0.0, 0.003, 0.5, -2.0, 0.5, -4.0, -3.5,
          0.05, 0.05]
    hi = [3.0, 1.5, 6.0, 2.0, 6.0, 1.5, 9.0, 2.0, 400.0, 4.0, -0.02, 1.2, 1.4]
    r = least_squares(res, x0, bounds=(lo, hi), max_nfev=30000)
    fitted = [round(float(v), 5) for v in r.x]
    e_fit = (model(r.x) / arr[:, 3] - 1.0) * 100
    errs = []
    for u in SSL_VAL_U:
        for s in SSL_VAL_S:
            for er in (1.5, 3.66, 10.2):
                fd = suspended_stripline_quasistatic(
                    u * SSL_B, SSL_B, s * SSL_B, er).eps_eff
                a1, a1e, b1, mu1, a2, a2e, b2, mu2, d0_, d1_, d2_, p0_, p1_ = r.x
                g = (1.0 + u ** mu1 * a1 * s ** a1e * (1.0 - s) ** b1
                     + u ** mu2 * a2 * s ** a2e * (1.0 - s) ** b2)
                d_cap = d0_ * (1.0 + u) ** d1_ * (4.0 * s * (1.0 - s)) ** d2_
                p = p0_ + p1_ * s
                dd = (er - 1.0) * q_stable(u, s) * g
                m = 1.0 + (dd ** (-p) + d_cap ** (-p)) ** (-1.0 / p)
                errs.append(abs((m / fd - 1) * 100))
    out = {
        "fitted": {"SSL_Q_G1": fitted[0:4], "SSL_Q_G2": fitted[4:8],
                   "SSL_D": fitted[8:11], "SSL_P": fitted[11:13]},
        "registered": {"SSL_Q_G1": list(SSL_Q_G1), "SSL_Q_G2": list(SSL_Q_G2),
                       "SSL_D": list(SSL_D), "SSL_P": list(SSL_P)},
        "fit_max_abs_err_pct": round(float(np.max(np.abs(e_fit))), 2),
        "fit_rms_pct": round(float(np.sqrt((e_fit ** 2).mean())), 2),
        "val_max_abs_err_pct": round(float(max(errs)), 2),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
    return out


CPS_CORNER_AH = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0)
CPS_CORNER_BH = (0.75, 1.5, 2.0, 3.0, 6.0)


def cps_corner() -> list[dict]:
    """③ 适用域边界证据表：定标域（a/h≲1 且 b/h≲3）外的闭式低估。"""
    from rfauto.core.calculators import cps_effective_thickness_factor

    rows = []
    for ah in CPS_CORNER_AH:
        for bh in CPS_CORNER_BH:
            if bh <= ah * 1.05:
                continue
            a, b = ah * H, bh * H
            w, gap = b - a, 2 * a
            for er in FIT_ERS:
                fd = cps_quasistatic(w, gap, H, er,
                                     d0_mm=min(H / 20, a / 4)).eps_eff
                cl = _cps_ri(w, gap, H, er)[0]
                rows.append({"a_h": ah, "b_h": bh, "er": er,
                             "fd": round(fd, 5),
                             "closed": round(cl, 5),
                             "err_pct": round((cl / fd - 1) * 100, 2),
                             "gamma_now": round(
                                 cps_effective_thickness_factor(er), 4)})
                print(rows[-1], flush=True)
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nominal", action="store_true")
    parser.add_argument("--cps-family", action="store_true")
    parser.add_argument("--refit-cps-gamma", action="store_true")
    parser.add_argument("--ssl-series", action="store_true")
    parser.add_argument("--ssl-family", action="store_true")
    parser.add_argument("--refit-ssl-q", action="store_true")
    parser.add_argument("--cps-corner", action="store_true")
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args(argv)
    out: dict = {}
    any_mode = (args.cps_family, args.refit_cps_gamma, args.ssl_series,
                args.ssl_family, args.refit_ssl_q, args.cps_corner)
    if args.nominal or not any(any_mode):
        out["nominal"] = nominal()
    if args.cps_family:
        out["cps_family"] = cps_family()
    if args.refit_cps_gamma:
        out["refit_cps_gamma"] = refit_cps_gamma()
    if args.ssl_series:
        out["ssl_series"] = ssl_series()
    if args.ssl_family:
        out["ssl_family"] = ssl_family()
    if args.refit_ssl_q:
        out["refit_ssl_q"] = refit_ssl_q()
    if args.cps_corner:
        out["cps_corner"] = cps_corner()
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding="utf-8")


if __name__ == "__main__":
    main()
