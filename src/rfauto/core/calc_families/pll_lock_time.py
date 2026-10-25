"""PLL 锁定/捕获时间族（aurora_f W4-S14 席域 3，R2_core_tier3 边际池立项
——边际池"PLL 锁定时间（S）"，R2 §④ grep 证据 `lock.time|settling.*pll`
全零）。

一键：pll_lock_time（二阶 II 型 PLL 频率阶跃的线性锁定时间精确包络闭式+
非线性捕获（pull-in）时间近似档+lock-in/pull-out 范围档位判别——环路带
宽/阻尼/频偏→锁定时间，消费面与 pll_loop_filter（环路滤波器综合→ω_n/
ζ 供给端）及 pll_budget（相噪/抖动预算面）衔接，边界互指）。

边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- 全仓 grep（lock_time|settling pll|pull-in|捕获时间）注册键面零命中；
- pll_loop_filter=三阶环路滤波器**综合**（T1/T2/T3→元件值，ω_n/ζ 上游
  供给端）、pll_budget=输出相噪/抖动**预算**（clock_noise 积分复用）、
  clock_noise=相噪谱积分、oscillator_synthesis=振荡器综合——均不做捕
  获动力学，边界互指见各模块 docstring。

物理口径（docstring 写死，#1c/#300 出处纪律；#122 文献锚=原文数值实取）
--------------------------------------------------------
- **线性模型**（II 型二阶环，Gardner《Phaselock Techniques》Ch.3 标准
  形式——pll_loop_filter 同源引注）：闭环传函
  H(s)=(2ζω_n·s+ω_n²)/(s²+2ζω_n·s+ω_n²)，误差传函
  E(s)=s²/(s²+2ζω_n·s+ω_n²)。频率阶跃 Δω·u(t) 下相位误差精确暂态：
  ζ<1：φ_e(t)=(Δω/ω_d)·e^{−ζω_n t}·sin(ω_d t)，ω_d=ω_n√(1−ζ²)
  ζ=1：φ_e(t)=Δω·t·e^{−ω_n t}（临界阻尼）
  ζ>1：φ_e(t)=Δω·(e^{s₁t}−e^{s₂t})/(s₁−s₂)，s₁₂=−ζω_n±ω_n√(ζ²−1)
  线性锁定时间（包络口径，精确闭式）：|φ_e|≤φ_tol ⇒
  t_lock=ln(Δω/(φ_tol·ω_d))/(ζω_n)（ζ<1）；ζ≥1 对精确暂态二分求根
  （确定性，包络不适用如实声明）。II 型环频率阶跃稳态误差恒 0（终值
  定理，测试锚）。
- **lock-in 范围/时间**（近似档，P.E. Allen ECE6440 L060 引 Best：
  高环路增益三滤波器统一 Δω_L≈2ζω_n；lock-in 时间 T_L≈1/f_n=2π/ω_n
  ≈一个自然谐振周期）——近似式如实标 approximation 档。
- **pull-in 时间**（非线性捕获，Best 4th ed. App.A/GT L060 同式）：
  T_P=(π²/16)·Δω₀²/(ζ·ω_n³)——近似档；文献锚（#122）：GT L060 例
  f_n=3Hz、ζ=0.7、Δf=30Hz → T_P=4.675s（本键逐位复现，窗 0.5%）。
- **pull-out 范围**（仿真档如实标）：Δω_PO≈1.8ω_n(ζ+1)（GT L060 引
  Best，仿真经验式）。
- **−3dB 闭环带宽**（Gardner 口径）：ω_3dB=ω_n·√(1+2ζ²+√((1+2ζ²)²+1))
  ——与 pll_budget 消费面的"环路带宽"语义桥（频域口径与捕获时域口径
  的换算字段）。
- **档位判别**：|Δf|≤Δf_L=ζω_n/π → 线性档（t_lock 有效，无周期滑移）；
  Δf_L<|Δf| → 非线性捕获档（t_lock 不适用如实标记，报 T_P 近似）；
  |Δf|>Δf_PO → 超出 pull-out 档位提示（可能失锁，II 型环仍可慢速拉入
  的定性注记）。无环路增益输入时 pull-in 范围不判（II 型有源 PI 环理
  论上 Δω_P→∞，如实注记）。

出处
----
- F.M. Gardner, Phaselock Techniques, 3rd ed., Wiley 2005, Ch.3（线性
  环标准形式；pll_loop_filter 同源引注）。
- R.E. Best, Phase-Locked Loops 4th ed., McGraw-Hill 1999, App.A
  （pull-in 时间/范围式；经 P.E. Allen ECE6440 L060 讲义数值例转引实
  取 4.675s 锚）。

守卫：fn_hz>0；zeta>0；df_hz≥0；tol_deg∈(0,180)；loop_gain 可选>0。

出处（Gardner 2005 Ch.3；Best 1999 App.A）：
- pll_lock_time：线性环标准形式=F.M. Gardner, Phaselock Techniques,
  3rd ed., Wiley 2005, Ch.3（pll_loop_filter 同源引注）；pull-in 时间/
  范围式=R.E. Best, Phase-Locked Loops, 4th ed., McGraw-Hill 1999,
  App.A（经 P.E. Allen ECE6440 L060 讲义数值例转引实取 4.675s 逐位锚）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "linear": ("二阶 II 型环误差传函 E(s)=s²/(s²+2ζω_n s+ω_n²) 频率阶跃"
               "精确暂态（Gardner 3rd ed. Ch.3 标准形式）；包络锁定时间 "
               "t_lock=ln(Δω/(φ_tol·ω_d))/(ζω_n)（ζ<1 精确闭式；ζ≥1 精"
               "确暂态二分求根）"),
    "acq": ("lock-in 范围 Δω_L≈2ζω_n/时间 T_L≈2π/ω_n（Best 高环路增益"
            "统一近似，GT ECE6440 L060 转引）；pull-in 时间 "
            "T_P=(π²/16)Δω²/(ζω_n³)（Best 4th ed. App.A；GT L060 数值例 "
            "f_n=3/ζ=0.7/Δf=30 → 4.675s 原文实取）；pull-out "
            "Δω_PO≈1.8ω_n(ζ+1)（仿真经验档如实标）"),
}


def _phi_error(t: float, dw: float, wn: float, zeta: float) -> float:
    """频率阶跃相位误差精确暂态 φ_e(t)（rad）。"""
    if zeta < 1.0:
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        return (dw / wd) * math.exp(-zeta * wn * t) * abs(math.sin(wd * t))
    if zeta == 1.0:
        return dw * t * math.exp(-wn * t)
    s1 = -zeta * wn + wn * math.sqrt(zeta * zeta - 1.0)
    s2 = -zeta * wn - wn * math.sqrt(zeta * zeta - 1.0)
    return abs(dw * (math.exp(s1 * t) - math.exp(s2 * t)) / (s1 - s2))


@register_calculator(
    "pll_lock_time",
    "PLL锁定时间：二阶 II 型环频率阶跃捕获判别+锁定时间——线性档（|Δf|"
    "≤lock-in 范围 2ζω_n）相位误差包络精确闭式 t_lock=ln(Δω/(φ_tol·ω_d))"
    "/(ζω_n)（ζ<1；ζ≥1 精确暂态二分），非线性档 pull-in 时间近似 "
    "T_P=(π²/16)Δω²/(ζω_n³)（Best App.A，文献例 4.675s 逐位锚），lock-in "
    "时间≈2π/ω_n、pull-out 范围 1.8ω_n(ζ+1) 档位如实标近似/仿真；稳态"
    "误差恒 0（II 型）+−3dB 带宽 Gardner 式（pll_budget 频域语义桥）",
    (("fn_hz", "float Hz 环路自然频率 ω_n/2π（>0；pll_loop_filter 综合输"
               "出的环路带宽换算端）"),
     ("zeta", "float 阻尼系数 ζ（>0；0.707 惯例）"),
     ("df_hz", "float Hz 频率阶跃 |Δf|（≥0；VCO 初始失谐/参考阶跃）"),
     ("tol_deg", "float deg 锁定判据相位误差容限 φ_tol（0<tol<180，缺省 "
                 "5）"),
     ("loop_gain_rad_s", "float rad/s 开环直流增益 K=Kφ·Kvco·(1/N)（>0；"
                         "可选，仅供 hold-in 量级参考不进判别）")),
    required=("fn_hz", "zeta", "df_hz"),
)
def pll_lock_time(fn_hz: float, zeta: float, df_hz: float,
                  tol_deg: float = 5.0,
                  loop_gain_rad_s: float | None = None) -> dict[str, Any]:
    fn = _finite(fn_hz, "fn_hz")
    if fn <= 0.0:
        raise ValueError(f"pll_lock_time: fn_hz 必须 >0，得到 {fn_hz!r}")
    z = _finite(zeta, "zeta")
    if z <= 0.0:
        raise ValueError(f"pll_lock_time: zeta 必须 >0，得到 {zeta!r}")
    df = _finite(df_hz, "df_hz")
    if df < 0.0:
        raise ValueError(f"pll_lock_time: df_hz 必须 ≥0，得到 {df_hz!r}")
    tol_deg_v = _finite(tol_deg, "tol_deg")
    if not 0.0 < tol_deg_v < 180.0:
        raise ValueError(
            f"pll_lock_time: tol_deg 须 ∈(0,180)，得到 {tol_deg!r}")
    kgain: float | None = None
    if loop_gain_rad_s is not None:
        kgain = _finite(loop_gain_rad_s, "loop_gain_rad_s")
        if kgain <= 0.0:
            raise ValueError(
                f"pll_lock_time: loop_gain_rad_s 必须 >0（给定时），"
                f"得到 {loop_gain_rad_s!r}")

    wn = 2.0 * math.pi * fn
    dw = 2.0 * math.pi * df
    phi_tol = math.radians(tol_deg_v)

    # lock-in / pull-out 范围档（近似/仿真档，字段如实标注）
    df_lock_in = z * wn / (2.0 * math.pi)          # Δω_L=2ζω_n
    df_pull_out = 1.8 * wn * (z + 1.0) / (2.0 * math.pi)
    # 档位=捕获场景：≤lock-in → 线性无滑移；>lock-in → 周期滑移非线性
    # 捕获（pull-in 时间口径；II 型环慢速拉入，pull_out 为锁定态阶跃
    # 失锁上界的独立提示字段）
    regime = "linear_lock" if df <= df_lock_in else "nonlinear_pull_in"

    # 线性锁定时间（ζ<1 精确闭式；ζ≥1 精确暂态二分）
    if dw <= 0.0:
        t_lock = 0.0
        lock_closed_form = True
    elif z < 1.0:
        wd = wn * math.sqrt(1.0 - z * z)
        arg = dw / (phi_tol * wd)
        t_lock = 0.0 if arg <= 1.0 else math.log(arg) / (z * wn)
        lock_closed_form = True
    else:
        lo, hi = 0.0, 1.0
        while _phi_error(hi, dw, wn, z) > phi_tol:
            hi *= 2.0
            if hi > 1e6 / wn:
                raise ValueError(
                    "pll_lock_time: ζ≥1 暂态求根未收敛（内部口径错误，"
                    "请报告）")
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _phi_error(mid, dw, wn, z) > phi_tol:
                lo = mid
            else:
                hi = mid
        t_lock = 0.5 * (lo + hi)
        lock_closed_form = False

    # 非线性捕获（pull-in）时间近似档
    t_pull_in = (math.pi ** 2 / 16.0) * dw * dw / (z * wn ** 3)

    # −3dB 闭环带宽（Gardner 口径；pll_budget 频域语义桥）
    q = 1.0 + 2.0 * z * z
    bw3db_hz = wn * math.sqrt(q + math.sqrt(q * q + 1.0)) / (2.0 * math.pi)
    # 线性档无周期滑移的上界复核（包络峰值 Δω/ω_d 对应峰值相位误差）
    peak_phase_rad = (dw / (wn * math.sqrt(max(1.0 - z * z, 1e-300)))
                      if z < 1.0 else dw / (wn * math.e))
    return {
        "fn_hz": fn,
        "zeta": z,
        "df_hz": df,
        "tol_deg": tol_deg_v,
        "omega_n_rad_s": round(wn, 12),
        "regime": regime,
        "df_lock_in_hz": round(df_lock_in, 12),
        "df_pull_out_hz": round(df_pull_out, 12),
        "t_lock_s": round(t_lock, 12),
        "t_lock_closed_form": lock_closed_form,
        "t_lockin_rule_of_thumb_s": round(1.0 / fn, 12),
        "t_pull_in_s": round(t_pull_in, 12),
        "peak_phase_error_rad": round(peak_phase_rad, 15),
        "steady_state_error_rad": 0.0,
        "bw_3db_hz": round(bw3db_hz, 12),
        "loop_gain_rad_s": kgain,
        "reciprocity": "scalar acquisition dynamics (no S matrix)",
        "note": (
            "档位口径：|Δf|≤Δf_L=ζω_n/π（=Δω_L/2π，Δω_L≈2ζω_n 高环路增"
            "益近似档）判 linear_lock——t_lock 为相位误差包络精确闭式"
            "（ζ<1）/精确暂态二分（ζ≥1，t_lock_closed_form=False 如实标"
            "记）；lock-in 区内无周期滑移。|Δf|>Δf_L 判 nonlinear_pull_"
            "in——t_lock 不适用（周期滑移主导），报 t_pull_in=(π²/16)"
            "Δω²/(ζω_n³) 近似档（Best App.A；f_n=3Hz/ζ=0.7/Δf=30Hz → "
            "4.675s 文献数值逐位锚——该例即 nonlinear_pull_in 档）。"
            "df_pull_out=1.8ω_n(ζ+1)（仿真档）是**锁定态**阶跃失锁上界的"
            "独立提示（applied-to-locked 场景），与解锁态捕获的 pull-in "
            "口径不同轴不互斥；II 型（有源 PI）环 pull-in 范围理论上无界"
            "（慢速拉入），定性注记不进判别。lock-in 时间经验档 "
            "T_L≈1/f_n=2π/ω_n（一个自然谐振周期）并列。II 型环频率阶跃"
            "稳态误差恒 0（终值定理）。bw_3db_hz=Gardner −3dB 闭环带宽"
            "（ω_n√(1+2ζ²+√((1+2ζ²)²+1))/2π），与 pll_budget 频域环路带"
            "宽语义桥；ω_n/ζ 供给端=pll_loop_filter 综合（f_c/PM→T1/T2/"
            "T3）"),
        "source": _SOURCES["linear"] + "；" + _SOURCES["acq"],
    }
