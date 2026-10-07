"""AP-12 电小天线 Q 提取与带宽换算（round17 §三 AP-12，P1/S；2026-10-03）。

Yaghjian-Best 阻抗导数式 Q 提取（实测 Q 侧）+ 带宽换算 + Chu 界
可达性 verdict（接 core/bounds.py chu_q_bound——round17 现状行
"bounds 全是限值侧无实测 Q 侧"的补件）。全部**纯函数零 IO**、
numpy 依赖、返回 JSON 可序列化值。零求解器依赖。

出处与口径：
- 阻抗导数式 Q：A.D. Yaghjian & S.R. Best, "Impedance, Bandwidth,
  and Q of Antennas", IEEE Trans. Antennas Propag. 53(4):1298-1324,
  2005——单谐振口径：

      Q_A(Z_A) = ω·|dZ_A/dω| / (2·R_A)

  在 X=0（谐振）处取值。串/并联 RLC 解析恒等式（独立手推锚，
  预声明进测试）：串联 Q=ω₀L/R、并联 Q=ω₀RC，导数式在谐振点
  逐式回收（dZ/dω|_res：串联 =j·2L、并联 =−j·2R²C）。
- 带宽换算（同文口径；串联 RLC 精确恒等，数值确证到 1e-10）：
  匹配半功率（|Γ|²=1/2）相对带宽 FBW_hp = 2/Q；VSWR≤S 匹配相对
  带宽 FBW_S = (S−1)/(√S·Q)。二者自洽：FBW_hp 恰为 FBW_S 在
  S=(1+√2)²=3+2√2≈5.8284（|Γ|=1/√2 档，S=(1+|Γ|)/(1−|Γ|)）的
  取值（(S−1)/√S=2）。
  文献常引 "FBW≈1/Q" 为单边半宽或松口径，消费方按需换算（docstring
  显式口径，#122 不沿用未核数）。数值法互证：对合成 RLC 阻抗直接
  算 Γ(f)=(Z−Z₀)/(Z+Z₀) 数值找 |Γ|²=1/2 与 |Γ|=(S−1)/(S+1) 宽度，
  与换算式比对（两推导路径独立，门值预声明）。
- Chu 界可达性 verdict：Q_A 与 bounds.chu_q_bound 的
  Q_min=1/(ka)³+1/(ka)（McLean 1996 严格式；圆极化减半）比对：
  Q_A < Q_min·(1−tol) → "unreachable"（实测 Q 低于无耗下界=
  违反 Chu 界，物理不可能，提示测量/模型问题）；否则
  "reachable"。语义接 BoundVerdict（verdict 字段同值域）。

#118/#300 纪律：合成 RLC 已知量回收（synthetic recovery）+ 解析
恒等式 + Γ 数值宽度第三方法，≥2 独立基准/件，门值预声明
tests/unit/test_antenna_q.py。文献数值表（真实天线实测 Q 表值）
在本环境未能核实（搜索后端限流）——按 #122 不虚构文献数值例，
文献锚以解析恒等式与经典 Chu 界手算值承担。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.bounds import chu_q_bound, exact_spherical_q_bounds

#: Chu 界判定的浮点余量（相对 Q_min）：低于界 (1−tol) 倍才判
#: unreachable（#347 家族"恰等会炸"——贴界浮点噪声不判违约）。
DEFAULT_TOL = 0.05


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


# ─── 阻抗导数式 Q 提取 ───────────────────────────────────────────────────────


def q_from_impedance(
    f_hz: np.ndarray | list[float], z_ohm: np.ndarray | list[complex]
) -> np.ndarray:
    """逐频点阻抗导数式 Q(ω) = ω|dZ/dω|/(2·Re Z)（Yaghjian-Best 2005）。

    f_hz 升序频率采样、z_ohm 同形复阻抗；dZ/dω 用非均匀网格差分
    （np.gradient，edge_order=2——一阶单边差分把区间中点导数赋给
    端点，谐振点采在窗缘时会带 O(h/2) 系统偏差，实测 5e-5 量级）。
    采样分辨率契约：Δf/f₀ ≪ 1/(2Q)——串联型（Z=R+j2Qδ 线性）中
    心差分精确；并联型（Z=R/(1+j2Qδ)）截断误差 O((2Q·Δf/f₀)²)/6
    （并联 RLC 数值实证 6.4e-5@Δf/f₀=1e-4、Q=40；测试以 2e-6 步长
    预声明钉）。
    Re Z ≤ 0 的频点 Q 无定义（Yaghjian-Best 口径要求 R>0），按 NaN
    返回（消费方自裁；不静默剔除）。单谐振天线在 X=0 邻域取值有效，
    宽带多谐振口径如实退化（docstring 如实标注，resonance_extract
    提供谐振点定位）。
    """
    f = np.asarray(f_hz, dtype=float)
    z = np.asarray(z_ohm, dtype=complex)
    if f.ndim != 1 or z.shape != f.shape:
        raise ValueError(f"f_hz/z 须同形一维数组，得 {f.shape}/{z.shape}")
    if f.size < 3:
        raise ValueError(f"至少 3 个频点（中心差分），得 {f.size}")
    if np.any(np.diff(f) <= 0.0):
        raise ValueError("f_hz 必须严格升序")
    omega = 2.0 * np.pi * f
    r = z.real
    dz = np.gradient(z, omega, edge_order=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = omega * np.abs(dz) / (2.0 * r)
    q = np.where(r > 0.0, q, np.nan)
    return q


def resonance_extract(
    f_hz: np.ndarray | list[float], z_ohm: np.ndarray | list[complex]
) -> dict[str, Any]:
    """谐振点定位 + 谐振 Q（X=0 过零，取靠 |X| 全局最小者）。

    返回 dict：f0_hz（相邻样点线性内插的 X=0 频率）/ r0_ohm（内插
    R）/ q（内插点导数式 Q）/ method 注记。无 X=0 过零（如纯感性
    频段采样不足）显式 ValueError，不凑数。
    """
    f = np.asarray(f_hz, dtype=float)
    z = np.asarray(z_ohm, dtype=complex)
    if f.ndim != 1 or z.shape != f.shape:
        raise ValueError(f"f_hz/z 须同形一维数组，得 {f.shape}/{z.shape}")
    x = z.imag
    sign_change = np.where(np.diff(np.sign(x)) != 0)[0]
    if sign_change.size == 0:
        raise ValueError("采样窗内无 X=0 过零（谐振不在窗内或采样不足）")
    anchor = int(np.argmin(np.abs(x)))
    best = int(sign_change[np.argmin(np.abs(sign_change - anchor))])
    # 线性内插 X=0 频率与该点阻抗
    t = -x[best] / (x[best + 1] - x[best])
    f0 = float(f[best] + t * (f[best + 1] - f[best]))
    z0 = z[best] + t * (z[best + 1] - z[best])
    # f0 处导数式 Q：窗心对准 f0 最近样点（中央差分落在谐振点，
    # 避免 3 点窗把谐振点推到 edge 差分位置——O(h/2) 系统偏差实测 5e-5）
    idx = int(np.argmin(np.abs(f - f0)))
    lo = max(idx - 1, 0)
    hi = min(idx + 2, f.size)
    q_win = q_from_impedance(f[lo:hi], z[lo:hi])
    q0 = float(np.interp(f0, f[lo:hi], q_win))
    return {
        "f0_hz": f0,
        "r0_ohm": float(z0.real),
        "x0_ohm": float(z0.imag),
        "q": q0,
        "method": "Yaghjian-Best 2005 impedance derivative at X=0",
    }


# ─── 带宽换算（单谐振近似）──────────────────────────────────────────────────


def half_power_bandwidth(q: float) -> float:
    """匹配半功率（|Γ|²=1/2）相对带宽 FBW_hp = 2/Q（全宽口径）。

    串联 RLC（Z₀=R 匹配）精确恒等：|Γ|²=(2Qδ)²/(4+(2Qδ)²)=1/2 →
    δ=±1/Q → 全宽 2/Q；与 vswr_bandwidth 在 S=5.8284（半功率档
    VSWR）自洽：(S−1)/(√S·Q)=2/Q。文献常引 "1/Q" 为单边半宽或
    松口径（docstring 显式口径，#122）。Γ(f) 数值宽度互证（测试，
    串联 RLC 下精确到 1e-9）。
    """
    out = _num(q, "q")
    if out <= 0.0:
        raise ValueError(f"q 必须 >0，得 {out}")
    return 2.0 / out


def vswr_bandwidth(q: float, vswr: float) -> float:
    """VSWR≤S 匹配相对带宽 FBW_S = (S−1)/(√S·Q)（全宽口径）。

    串联 RLC（Z₀=R 匹配）精确恒等（|Γ|=(S−1)/(S+1) 代入
    |Γ|²=(2Qδ)²/(4+(2Qδ)²)）。S=2、Q=20 解析锚 0.0353553；Γ 数值
    宽度互证（测试，精确到 1e-9）。
    """
    out = _num(q, "q")
    if out <= 0.0:
        raise ValueError(f"q 必须 >0，得 {out}")
    s = _num(vswr, "vswr")
    if s <= 1.0:
        raise ValueError(f"vswr 必须 >1（S=1 为零带宽理想匹配），得 {s}")
    return (s - 1.0) / (math.sqrt(s) * out)


# ─── Chu 界可达性 verdict（接 bounds）────────────────────────────────────────


def q_reachability_band(
    ka: float,
    q_measured: float,
    polarization: str = "linear",
    tol: float = DEFAULT_TOL,
) -> dict[str, Any]:
    """实测 Q 三门带可达性 verdict（W4-C P6：单模→耦合模→不可达分档）。

    门值（bounds.exact_spherical_q_bounds，式号=Yaghjian arXiv:2501.03146）：
        q_gate_single = min(Q̃^TM_1Z, Q̃^TE_1Z)   式(42)/(47) 精确单模界
        q_gate_coupled = Q^TMTE_1Z               式(51) TM+TE 耦合模界（≈半）

    verdict 语义（tol 相对余量缺省 0.05，#347 贴界浮点噪声不判违约）：
        q_meas < q_gate_coupled·(1−tol)            → "unreachable"
            （低于耦合模下界=物理不可能，提示测量/模型问题）
        q_meas < q_gate_single·(1−tol)             → "reachable_with_coupled_modes"
            （单模界之下、耦合模界之上——合法，需 TM+TE 耦合激励，Thal 2009
            "Gain and Q bounds for coupled TM-TE modes," IEEE TAP 57(7):
            1879-1885 概念；原文勘误注记：SM 报告误记 54(10) 2006）
        其余                                        → "reachable"

    circular 极化按本模块既有约定对两门减半（两正交简并模同时激起的经典
    口径，与 chu_q_bound 的 circular 口径一致；耦合模+圆极化的严格界文献
    未逐式核对，如实用同一减半约定并在 source 注记）。

    返回 dict（JSON 可序列化）：verdict / q_measured / q_gate_single /
    q_gate_coupled / q_min_chu_mclean / ka / margin_ratio_coupled /
    margin_ratio_single / tol / source。
    """
    ka_val = _num(ka, "ka")
    if ka_val <= 0.0:
        raise ValueError(f"ka 必须 >0，得 {ka_val}")
    q_meas = _num(q_measured, "q_measured")
    if q_meas <= 0.0:
        raise ValueError(f"q_measured 必须 >0，得 {q_meas}")
    tol_val = _num(tol, "tol")
    if not (0.0 <= tol_val < 1.0):
        raise ValueError(f"tol 须在 [0, 1) 内，得 {tol_val}")
    if polarization not in ("linear", "circular"):
        raise ValueError(
            f"polarization 必须是 ['circular', 'linear'] 之一，收到 {polarization!r}")
    bounds = exact_spherical_q_bounds(ka_val)
    q_single = float(min(bounds.q_tm1, bounds.q_te1))
    q_coupled = float(bounds.q_tmte1)
    if polarization == "circular":
        q_single *= 0.5
        q_coupled *= 0.5
    ratio_single = (q_meas - q_single) / q_single
    ratio_coupled = (q_meas - q_coupled) / q_coupled
    if ratio_coupled < -tol_val:
        verdict = "unreachable"
    elif ratio_single < -tol_val:
        verdict = "reachable_with_coupled_modes"
    else:
        verdict = "reachable"
    return {
        "verdict": verdict,
        "q_measured": q_meas,
        "q_gate_single": q_single,
        "q_gate_coupled": q_coupled,
        "q_min_chu_mclean": float(bounds.q_chu_mclean),
        "ka": ka_val,
        "polarization": polarization,
        "margin_ratio_single": ratio_single,
        "margin_ratio_coupled": ratio_coupled,
        "tol": tol_val,
        "source": "Yaghjian arXiv:2501.03146 eq.(42)/(47)/(51) exact spherical-"
                  "mode Q bounds (TM+TE coupling per Thal 2009 TAP 57(7):1879-1885)",
    }


def q_reachability_verdict(
    ka: float,
    q_measured: float,
    polarization: str = "linear",
    tol: float = DEFAULT_TOL,
) -> dict[str, Any]:
    """实测 Q 对 Chu-Harrington 界的可达性 verdict（round17 AP-12）。

    Q_min = 1/(ka)³+1/(ka)（bounds.chu_q_bound，McLean 1996）。
    Q_meas < Q_min·(1−tol) → "unreachable"（违反无耗下界：物理不可
    能，提示测量/模型问题）；否则 "reachable"。tol 相对余量
    （缺省 0.05，#347 贴界浮点噪声不判违约）。返回 dict（JSON 可
    序列化）：verdict / q_measured / q_min_chu / ka / margin_ratio /
    source。手算锚：ka=π/2（半波偶极子量级）→ Q_min=8/π³+2/π
    =0.894632（测试预声明；0.89459 系旧 docstring 舍入笔误，2026-10-04
    勘误——A-01）。
    """
    ka_val = _num(ka, "ka")
    if ka_val <= 0.0:
        raise ValueError(f"ka 必须 >0，得 {ka_val}")
    q_meas = _num(q_measured, "q_measured")
    if q_meas <= 0.0:
        raise ValueError(f"q_measured 必须 >0，得 {q_meas}")
    tol_val = _num(tol, "tol")
    if not (0.0 <= tol_val < 1.0):
        raise ValueError(f"tol 须在 [0, 1) 内，得 {tol_val}")
    bound = chu_q_bound(ka_val, polarization=polarization)
    q_min = float(bound.limit_value)
    margin_ratio = (q_meas - q_min) / q_min
    verdict = "unreachable" if margin_ratio < -tol_val else "reachable"
    return {
        "verdict": verdict,
        "q_measured": q_meas,
        "q_min_chu": q_min,
        "ka": ka_val,
        "polarization": polarization,
        "margin_ratio": margin_ratio,
        "tol": tol_val,
        "source": "Yaghjian-Best 2005 Q vs McLean 1996 Chu bound "
                  "(rfauto.core.bounds.chu_q_bound)",
    }
