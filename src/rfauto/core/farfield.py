"""nf2ff 远场确定性内核（openEMS 原生）。

职责（数值只在确定性内核；本模块 = 纯 numpy 叶子，无业务依赖）：
- 从 openEMS nf2ff 产物（模板脚本落盘的 farfield_cut.csv / farfield3d.csv /
  farfield_meta.json）计算方向图（dB 归一）、按角/峰值方向性（directivity）、
  增益（gain）、辐射效率（efficiency）、半功率波瓣宽度（HPBW）、前后比
  （F/B）与功率守恒闭合；
- 文献口径（Balanis《Antenna Theory》表 4.1 / §4.4）：
  * 无耗半波偶极子 D0 = 1.642（2.15 dBi）、HPBW ≈ 78°；
  * 无方向性归一：D(θ,φ) = 4π·U(θ,φ)/Prad，U = r²·P_rad；
  * 效率 η = Prad / P_acc（P_acc = 端口接受功率），G = η·D；
  * PEC 地器件：openEMS nf2ff 单镜像面把 Prad 双计、Dmax 折半（见
    correct_pec_mirror 注记），后处理按盒几何确定性修正。

约定：farfield_cut.csv 每个 phi 平面一段（−180..180° θ 扫描），列见
parse_farfield_cut_csv；角度一律度，dB 一律相对峰值归一。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

#: 远场产物文件名（模板脚本与适配器/服务层共同遵守的契约）
FARFIELD_META_NAME = "farfield_meta.json"
FARFIELD_CUT_NAME = "farfield_cut.csv"
FARFIELD_3D_NAME = "farfield3d.csv"
SAR_CSV_NAME = "sar.csv"


# ─── 方向图与方向性 ──────────────────────────────────────────────────────────

def pattern_db(e_norm: np.ndarray) -> np.ndarray:
    """场归一化方向图（dB，相对峰值 0 dB）。峰值≤0（全零场）时原样返回 NaN。"""
    e = np.asarray(e_norm, dtype=float)
    peak = float(e.max()) if e.size else 0.0
    if peak <= 0.0:
        return np.full(e.shape, np.nan)
    return 20.0 * np.log10(e / peak + 1e-300)


def directivity_grid(
    p_rad: np.ndarray, theta_rad: np.ndarray, phi_rad: np.ndarray,
    prad_w: float | None = None,
) -> np.ndarray:
    """按角方向性 D(θ,φ) = 4π·U/Prad（U = r²·P_rad，球面梯形积分）。

    p_rad 形状 (n_theta, n_phi)，覆盖整球（θ 0..180、φ 覆盖 360°）。
    prad_w 缺省时由网格自积分（与绑定 Prad 互为交叉校验）。
    """
    pg = np.asarray(p_rad, dtype=float)
    th = np.asarray(theta_rad, dtype=float)
    ph = np.asarray(phi_rad, dtype=float)
    if pg.ndim != 2 or pg.shape != (th.size, ph.size):
        raise ValueError(
            f"p_rad 形状 {pg.shape} 与 (n_theta={th.size}, n_phi={ph.size}) 不符")
    inner = np.trapezoid(pg, ph, axis=1)          # ∫P dφ
    total = float(np.trapezoid(inner * np.sin(th), th))  # ∫∫P sinθ dθ dφ
    if total <= 0.0:
        raise ValueError("P_rad 球面积分为非正值，无法归一方向性")
    denom = prad_w if (prad_w is not None and prad_w > 0) else total
    return 4.0 * np.pi * pg / denom


def dmax_dbi(dmax_linear: float) -> float:
    """线性方向性 → dBi。"""
    return 10.0 * np.log10(max(float(dmax_linear), 1e-300))


def dmax_from_grid(
    p_rad: np.ndarray, theta_rad: np.ndarray, phi_rad: np.ndarray,
    prad_w: float | None = None,
) -> float:
    """网格 P_rad 的峰值方向性（线性）。文献锚：半波偶极子 ≈ 1.642。"""
    d = directivity_grid(p_rad, theta_rad, phi_rad, prad_w)
    return float(d.max())


# ─── 效率 / 增益 / 功率守恒 ──────────────────────────────────────────────────

def efficiency(prad_w: float, p_acc_w: float) -> float | None:
    """辐射效率 η = Prad / P_acc；P_acc 非正（严重失配/坏端口）→ None。"""
    if p_acc_w is None or p_acc_w <= 0.0:
        return None
    return float(prad_w) / float(p_acc_w)


def gain_max_db(dmax_db: float, eff: float | None) -> float | None:
    """峰值增益（dBi）= Dmax + 10·log10(η)；η 不可得 → None。"""
    if eff is None or eff <= 0.0:
        return None
    return float(dmax_db) + 10.0 * np.log10(float(eff))


def power_budget_closure(
    p_acc_w: float, prad_w: float, p_abs_w: float | None = None,
) -> float | None:
    """功率守恒闭合（相对量）：|P_acc − Prad − P_abs| / P_acc。

    官方 Dipole SAR 教程口径：闭合"within a few percent"确认远场/SAR 面
    功率账自洽（无 SAR 面时 P_abs 缺省 0——纯辐射结构 Prad≈P_acc）。
    P_acc 非正 → None（不可判读，不虚构）。
    """
    if p_acc_w is None or p_acc_w <= 0.0:
        return None
    absorbed = float(p_abs_w) if p_abs_w else 0.0
    return abs(float(p_acc_w) - float(prad_w) - absorbed) / float(p_acc_w)


# ─── PEC 地镜像修正（openEMS CreateNF2FFBox 单镜像面 Prad 双计）────────────
#
# 根因（2026-09-16 离线判读，源码+数据双证）：
# * openEMS.pyx CreateNF2FFBox：PEC 边界侧 → 该面 directions=False 且
#   mirror=1；nf2ff_calc.cpp AddPlane 在"单一镜像面开启"时对**每个**积分面
#   追加一次镜像面积分（AddMirrorPlane→AddSinglePlane），m_radPower 逐面累加；
#   nf2ff.cpp Write2HDF5 写出的 Prad = m_radPower = 真实 5 面 + 镜像 5 面
#   通量之和 = **2×物理辐射功率**；Dmax = 4π·U_max/m_radPower = 常规
#   D0（Balanis：Prad 取实际辐射的上半球）的 **½（−3.01 dB）**。
# * 真机复核（归档 farfield_3d.h5）：下/上半球图积分比
#   1.0000、逐点镜像误差 5.7e-7——下半球是纯镜像、非物理。
# 修正口径：盒底 z_start==0（贴 PEC 地）→ Prad/2、Dmax×2、η/2、增益与闭合重算。
# 六面全包（dipole/slot/loop，z_start<0）不受影响（dipole η=0.990 闭合 1%）。

#: openEMS 单 PEC 镜像面对 Prad 的双计因子
PEC_MIRROR_FACTOR = 2.0
_PEC_MIRROR_Z_TOL_M = 1e-9


def pec_mirror_factor(meta: dict[str, Any]) -> float:
    """由 farfield_meta 的 nf2ff 盒几何判定 Prad 双计因子（2 或 1）。

    判据：盒 z 起点恰为 0（接地辐射模板把盒底放在 PEC 地平面上）→ 2；
    盒坐标缺失/非零 → 1（不猜测）。
    """
    start = meta.get("nf2ff_box_start_m")
    try:
        z0 = float(start[2])  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return 1.0
    return PEC_MIRROR_FACTOR if abs(z0) < _PEC_MIRROR_Z_TOL_M else 1.0


_MIRROR_CORRECTED_KEYS = ("prad_w", "dmax_linear", "dmax_dbi", "efficiency",
                          "gain_max_dbi", "power_budget_closure")


def correct_pec_mirror(meta: dict[str, Any]) -> dict[str, Any]:
    """返回 PEC 镜像修正后的 farfield_meta 副本（不改入参）。

    附加字段：pec_mirror_factor（1 或 2）；因子为 2 时另附 raw（修正前六个
    指标原值）。数值链：Prad/k → η=Prad/P_acc → Dmax×k → G=Dmax+10lg η →
    闭合=|P_acc−Prad|/P_acc（无 SAR 面时即"未被远场捕获的损耗占比"）。

    幂等：meta 已带 pec_mirror_factor（渲染脚本 ff_calc_block
    在产出源按同一公式修正过，raw 已留痕）→ 原样直通，不二次折半；服务层
    （nf2ff_service/ui_service）对同一 meta 再调用本函数因此安全。
    """
    applied = meta.get("pec_mirror_factor")
    if applied is not None:
        out_applied: dict[str, Any] = dict(meta)
        out_applied["pec_mirror_factor"] = float(applied)
        return out_applied
    k = pec_mirror_factor(meta)
    out: dict[str, Any] = dict(meta)
    out["pec_mirror_factor"] = k
    if k == 1.0:
        return out
    out["raw"] = {key: meta.get(key) for key in _MIRROR_CORRECTED_KEYS}
    prad = meta.get("prad_w")
    p_acc = meta.get("p_acc_w")
    prad_fix = float(prad) / k if prad is not None else None
    out["prad_w"] = prad_fix
    dlin = meta.get("dmax_linear")
    if dlin is not None:
        out["dmax_linear"] = float(dlin) * k
        out["dmax_dbi"] = dmax_dbi(out["dmax_linear"])
    elif meta.get("dmax_dbi") is not None:
        out["dmax_dbi"] = float(meta["dmax_dbi"]) + 10.0 * np.log10(k)
    if prad_fix is not None and p_acc is not None:
        eta = efficiency(prad_fix, float(p_acc))
    elif meta.get("efficiency") is not None:
        eta = float(meta["efficiency"]) / k
    else:
        eta = None
    out["efficiency"] = eta
    out["gain_max_dbi"] = (gain_max_db(out["dmax_dbi"], eta)
                           if out.get("dmax_dbi") is not None else None)
    out["power_budget_closure"] = (
        power_budget_closure(float(p_acc), prad_fix)
        if prad_fix is not None and p_acc is not None else None)
    return out


# ─── 半球功率 / 图形自归一方向性 ─────────────────────────────────────────────

def hemisphere_power(
    p_rad: np.ndarray, theta_rad: np.ndarray, phi_rad: np.ndarray,
) -> dict[str, float]:
    """方向图网格的球面梯形积分 → {full, upper, lower}（W，或与 p_rad 同尺度）。

    p_rad 形状 (n_theta, n_phi)，θ∈[0,π] 升序，φ 覆盖一周（0..360−Δφ 的
    开区间网格自动补 2π 闭合列）。upper=θ≤π/2（含赤道），lower=θ≥π/2。
    φ 采样 <3 点（如 nf2ff 切面 φ=0/90）不构成球面 → ValueError。
    """
    pg = np.asarray(p_rad, dtype=float)
    th = np.asarray(theta_rad, dtype=float)
    ph = np.asarray(phi_rad, dtype=float)
    if pg.ndim != 2 or pg.shape != (th.size, ph.size):
        raise ValueError(
            f"p_rad 形状 {pg.shape} 与 (n_theta={th.size}, n_phi={ph.size}) 不符")
    if ph.size < 3:
        raise ValueError("φ 采样不足 3 点，无法做球面积分")
    dphi = float(np.median(np.diff(ph)))
    if (2.0 * np.pi - (ph[-1] - ph[0])) > 0.5 * dphi:
        ph = np.append(ph, ph[0] + 2.0 * np.pi)
        pg = np.concatenate([pg, pg[:, :1]], axis=1)
    w = np.trapezoid(pg, ph, axis=1) * np.sin(th)
    # 赤道容差取 float32 量级（openEMS h5 的 θ 轴为 float32：π/2→1.5707964）
    up = th <= np.pi / 2.0 + 1e-6
    lo = th >= np.pi / 2.0 - 1e-6
    return {
        "full": float(np.trapezoid(w, th)),
        "upper": float(np.trapezoid(w[up], th[up])) if up.sum() >= 2 else 0.0,
        "lower": float(np.trapezoid(w[lo], th[lo])) if lo.sum() >= 2 else 0.0,
    }


def dmax_from_pattern(
    p_rad: np.ndarray, theta_rad: np.ndarray, phi_rad: np.ndarray,
    hemisphere: str = "full",
) -> float:
    """图形自归一峰值方向性 D = 4π·U_max / ∫U dΩ（线性，尺度无关）。

    hemisphere="upper"：分母只取上半球（PEC 地器件的物理辐射空间，Balanis
    口径）；"full"：整球。openEMS 的 Dmax 属性用面通量 m_radPower 归一，与
    远场图自身积分相差紧贴盒的变换误差（真机 dipole +19%/patch −20%），
    本函数给出与图形自洽的教科书值作交叉校验。
    """
    hp = hemisphere_power(p_rad, theta_rad, phi_rad)
    denom = hp["upper"] if hemisphere == "upper" else hp["full"]
    if denom <= 0.0:
        raise ValueError("方向图积分为非正值，无法归一方向性")
    return 4.0 * np.pi * float(np.nanmax(np.asarray(p_rad, dtype=float))) / denom


def pattern_power_from_db(e_norm_db: np.ndarray) -> np.ndarray:
    """E 归一 dB（20·lg）→ 相对功率图 P/P_max=10^(dB/10)；NaN→0。"""
    db = np.asarray(e_norm_db, dtype=float)
    p = np.power(10.0, db / 10.0)
    return np.where(np.isfinite(p), p, 0.0)


# ─── 切面指标：HPBW / 前后比 / 峰值角 ────────────────────────────────────────

def hpbw_deg(
    theta_deg: np.ndarray, pattern_db: np.ndarray, level_db: float = -3.0,
) -> float | None:
    """半功率波瓣宽度（度）：峰值两侧首个跌破 level_db 处的角距（线性内插）。

    切面按 360° 周期处理（−180..180 网格首尾同点自动去重）；主瓣无
    −3dB 交叉（被截断或全向平坦）时返回 None——如实不可判读，不虚构。
    """
    th = np.asarray(theta_deg, dtype=float)
    pb = np.asarray(pattern_db, dtype=float)
    if th.size < 3 or th.shape != pb.shape:
        return None
    order = np.argsort(th)
    th, pb = th[order], pb[order]
    # 周期网格去重：首尾角差 ≡ 360°（如 −180..180）视为同一方向，弃末点
    step = float(np.median(np.diff(th)))
    n_eff = th.size
    if abs(th[-1] - th[0] - 360.0) < step / 2.0:
        n_eff -= 1
        if n_eff < 3:
            return None
    imax = int(np.argmax(pb[:n_eff]))

    def _walk(direction: int) -> float | None:
        """沿圆环走半圈找首个下穿点，返回峰到交叉点的角距（正值）。"""
        prev = imax
        for k in range(1, n_eff):
            i = (imax + direction * k) % n_eff
            if pb[i] < level_db:
                x0, x1 = pb[prev], pb[i]
                frac = 0.5 if x1 == x0 else (level_db - x0) / (x1 - x0)
                return (k - 1 + frac) * step  # 峰到交叉点的角距
            prev = i
            if k > n_eff // 2:
                break
        return None

    left = _walk(-1)
    right = _walk(+1)
    if left is None or right is None:
        return None
    return left + right


def front_to_back_db(theta_deg: np.ndarray, pattern_db: np.ndarray) -> float | None:
    """前后比（dB）：峰值方向与 180° 背向处的图值差。

    背向角无采样点（±1° 内无匹配）→ None；图值 NaN → None。
    """
    th = np.asarray(theta_deg, dtype=float)
    pb = np.asarray(pattern_db, dtype=float)
    if th.size < 2 or th.shape != pb.shape:
        return None
    imax = int(np.argmax(pb))
    front = float(pb[imax])
    back_angle = float(th[imax]) + 180.0
    # 角度按 360° 周期折回网格范围
    back_angle = (back_angle + 180.0) % 360.0 - 180.0
    idx = int(np.argmin(np.abs(th - back_angle)))
    if abs(float(th[idx]) - back_angle) > 1.0:
        return None
    back = float(pb[idx])
    if np.isnan(back):
        return None
    return front - back


def summarize_cut(theta_deg: np.ndarray, e_norm: np.ndarray) -> dict[str, Any]:
    """单切面指标汇总（polar 页/验收消费）。"""
    pdb = pattern_db(e_norm)
    return {
        "peak_theta_deg": (float(np.asarray(theta_deg)[int(np.argmax(pdb))])
                           if pdb.size and not np.all(np.isnan(pdb)) else None),
        "hpbw_deg": hpbw_deg(theta_deg, pdb),
        "front_to_back_db": front_to_back_db(theta_deg, pdb),
    }


# ─── 产物解析（模板脚本落盘契约）─────────────────────────────────────────────

_CUT_HEADER = ("phi_deg", "theta_deg", "re_e_theta", "im_e_theta",
               "re_e_phi", "im_e_phi", "e_norm", "p_rad")


def write_farfield_cut_csv(path: str | Path, rows: list[dict[str, float]]) -> None:
    """写 farfield_cut.csv（模板脚本与测试共用同一契约）。"""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CUT_HEADER)
        for r in rows:
            w.writerow([r["phi_deg"], r["theta_deg"],
                        r["re_e_theta"], r["im_e_theta"],
                        r["re_e_phi"], r["im_e_phi"],
                        r["e_norm"], r["p_rad"]])


def parse_farfield_cut_csv(path: str | Path) -> list[dict[str, Any]]:
    """解析 farfield_cut.csv → 按 phi 平面分组的切面列表。

    返回 [{phi_deg, theta_deg[], e_theta[](complex), e_phi[](complex),
           e_norm[], p_rad[]}]，每组内按 theta 升序。
    """
    groups: dict[float, dict[str, list[float]]] = {}
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            phi = float(row["phi_deg"])
            g = groups.setdefault(phi, {k: [] for k in
                                        ("theta_deg", "re_e_theta", "im_e_theta",
                                         "re_e_phi", "im_e_phi", "e_norm", "p_rad")})
            g["theta_deg"].append(float(row["theta_deg"]))
            g["re_e_theta"].append(float(row["re_e_theta"]))
            g["im_e_theta"].append(float(row["im_e_theta"]))
            g["re_e_phi"].append(float(row["re_e_phi"]))
            g["im_e_phi"].append(float(row["im_e_phi"]))
            g["e_norm"].append(float(row["e_norm"]))
            g["p_rad"].append(float(row["p_rad"]))
    cuts: list[dict[str, Any]] = []
    for phi in sorted(groups):
        g = groups[phi]
        order = np.argsort(np.asarray(g["theta_deg"]))
        cuts.append({
            "phi_deg": phi,
            "theta_deg": np.asarray(g["theta_deg"])[order],
            "e_theta": (np.asarray(g["re_e_theta"])
                        + 1j * np.asarray(g["im_e_theta"]))[order],
            "e_phi": (np.asarray(g["re_e_phi"])
                      + 1j * np.asarray(g["im_e_phi"]))[order],
            "e_norm": np.asarray(g["e_norm"])[order],
            "p_rad": np.asarray(g["p_rad"])[order],
        })
    return cuts


def parse_farfield_3d_csv(
    path: str | Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """解析 farfield3d.csv（theta_deg,phi_deg,e_norm_db）→ (θ°, φ°, dB 网格)。

    θ/φ 轴取升序去重值；网格形状 (n_theta, n_phi)，缺采样点填 NaN。
    """
    th_l: list[float] = []
    ph_l: list[float] = []
    vals: list[float] = []
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            th_l.append(float(row["theta_deg"]))
            ph_l.append(float(row["phi_deg"]))
            vals.append(float(row["e_norm_db"]))
    th = np.unique(np.asarray(th_l, dtype=float))
    ph = np.unique(np.asarray(ph_l, dtype=float))
    grid = np.full((th.size, ph.size), np.nan)
    ti = np.searchsorted(th, np.asarray(th_l, dtype=float))
    pi = np.searchsorted(ph, np.asarray(ph_l, dtype=float))
    grid[ti, pi] = np.asarray(vals, dtype=float)
    return th, ph, grid


def find_artifacts(run_dir: str | Path) -> dict[str, Path]:
    """在 run 目录内定位远场/SAR 产物（fdtd/ 子目录兼容，缺失不报错）。"""
    base = Path(run_dir)
    names = (FARFIELD_META_NAME, FARFIELD_CUT_NAME, FARFIELD_3D_NAME,
             SAR_CSV_NAME)
    found: dict[str, Path] = {}
    for name in names:
        hits = sorted(base.rglob(name))
        if hits:
            found[name] = hits[0]
    return found


# ─── 3D 复数 dump（DP-4 P3 EEP 叠加用；旧 farfield_cut/farfield3d 零改动）─────
#
# 契约（DP-4 规格书 §2c/#315 兼容纪律）：farfield3d_cplx.csv 每行一个角点，
# 列 theta_deg,phi_deg,re_e_theta,im_e_theta,re_e_phi,im_e_phi（复分量，全局
# 原点参考——nf2ff 以原点为相位基准，EEPₙ 已含单元位置相位，免手工补偿）。
# 本节只**新增**写/读函数与文件名常量；parse_farfield_cut_csv /
# parse_farfield_3d_csv 等旧契约零改动（#315：改公共解析器前先 grep 全仓
# 解包点——本批不改旧签名不改返回结构）。解析器向前兼容：多余列容忍并忽略，
# 缺必需列显式报错并列出缺失列名。

FARFIELD_3D_CPLX_NAME = "farfield3d_cplx.csv"
"""3D 复数远场 dump 文件名（DP-4 P3 模板脚本与解析器共同遵守的契约）。"""

_CPLX_3D_HEADER = ("theta_deg", "phi_deg", "re_e_theta", "im_e_theta",
                   "re_e_phi", "im_e_phi")


def write_farfield_3d_cplx_csv(
    path: str | Path,
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    e_theta: np.ndarray,
    e_phi: np.ndarray,
) -> None:
    """写 farfield3d_cplx.csv（模板脚本与测试共用同一契约）。

    e_theta/e_phi 为 (n_theta, n_phi) 复数网格，θ/φ 轴升序（与解析端一致）。
    """
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    et = np.asarray(e_theta, dtype=complex)
    ep = np.asarray(e_phi, dtype=complex)
    if et.shape != (th.size, ph.size) or ep.shape != (th.size, ph.size):
        raise ValueError(
            f"复数网格形状须为 (n_theta={th.size}, n_phi={ph.size})，"
            f"收到 e_theta={et.shape}, e_phi={ep.shape}")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_CPLX_3D_HEADER)
        for i, tv in enumerate(th):
            for j, pv in enumerate(ph):
                w.writerow([tv, pv,
                            et[i, j].real, et[i, j].imag,
                            ep[i, j].real, ep[i, j].imag])


def parse_farfield_3d_cplx_csv(
    path: str | Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """解析 farfield3d_cplx.csv → (θ°, φ°, e_theta 复网格, e_phi 复网格)。

    θ/φ 轴取升序去重值；网格形状 (n_theta, n_phi)，缺采样点填 NaN（复数
    nan+nanj）；重复采样点后写者优先（与 parse_farfield_3d_csv 语义一致）。
    向前兼容：表头多余列容忍并忽略；缺任一必需列 → ValueError 且列出缺失列。
    """
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = [col for col in _CPLX_3D_HEADER if col not in fieldnames]
        if missing:
            raise ValueError(
                f"{path}: 表头缺少必需列 {missing}（期望 {_CPLX_3D_HEADER}；"
                "多余列会被忽略——向前兼容契约）")
        th_l: list[float] = []
        ph_l: list[float] = []
        et_l: list[complex] = []
        ep_l: list[complex] = []
        for row in reader:
            th_l.append(float(row["theta_deg"]))
            ph_l.append(float(row["phi_deg"]))
            et_l.append(complex(float(row["re_e_theta"]),
                                float(row["im_e_theta"])))
            ep_l.append(complex(float(row["re_e_phi"]),
                                float(row["im_e_phi"])))
    if not th_l:
        raise ValueError(f"{path}: 无数据行")
    th = np.unique(np.asarray(th_l, dtype=float))
    ph = np.unique(np.asarray(ph_l, dtype=float))
    et = np.full((th.size, ph.size), complex(np.nan, np.nan), dtype=complex)
    ep = et.copy()
    ti = np.searchsorted(th, np.asarray(th_l, dtype=float))
    pi = np.searchsorted(ph, np.asarray(ph_l, dtype=float))
    et[ti, pi] = np.asarray(et_l, dtype=complex)
    ep[ti, pi] = np.asarray(ep_l, dtype=complex)
    return th, ph, et, ep

