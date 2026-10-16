"""交指/梳状杆滤波器实现族（interdigital/combline bars，aurora72 A3-C 席
域 2，R7 第二梯队 T6；aurora_d W3-CORE7 席补 **combline 耦合缝半边**
（R7 T6="combline 耦合缝+交指综合"两半边的 combline 残半，2026-10-14））。

三键：interdigital_bars_capacitance（零厚度耦合杆条带线偶/奇模电容与阻抗
闭式——Getsinger 平行板耦合条形极限） / interdigital_bpf_synthesize（Getsi
nger 等效网络综合：g 值→J 倒置器→逐节 (C_e,C_o) 目标→杆宽/缝 mm 反解→杆
长 λ/4） / combline_coupling_gap（combline 半边：耦合系数 k_ij→邻杆间隙
g_ij 换算——k_ij→J=b_s·k_ij→(C_e,C_o) 目标→(w,s) 带域边界二分反解，剖面
电容闭式与交指两键同源 Getsinger 共形映射）。

与既有面的边界（#222 三重搜索证据，2026-10-11 实测；combline 半边
2026-10-14 树面复核：combline_resonator.py 三键=谐振器频率/Q 级且 docstring
明示"与互电容（G20 全 Caspi/FD 尺寸闭环）不在本键口径内"——k_ij→缝 mm
键面零命中）
--------------------------------------------------------
- adapters/oe_templates/render_c3.py interdigital_design_from_order = **模板
  渲染级**（C13 原型→MYJ 斜率→J 目标→KJ 耦合**微带**缝反解，绑定
  TEMPLATE_META）；本族是**注册计算器键**且走**条带线（平行板、均匀介质）
  电容闭式**介质档，语义互补不重复。
- combline_resonator（aurora36）= 单谐振器频率/Q 级（combline_resonance/
  coaxial_cavity_resonance/cavity_unloaded_q）；本族是它的**耦合缝/多杆实现
  续作**（k_ij↔缝 mm 闭环），谐振器频率/Q 不在本族——combline_coupling_
  gap 的装载斜率 θ₀ 与 combline_resonance 谐振条件同解自洽（锚树跨键互证）。
- 抽头位输入耦合（hairpin_tap_frac_from_qe）已有，不在本族；模板级负载电
  容型 combline 全滤波器设计（render_c3 combline_design_from_order，绑定
  TEMPLATE_META）不在本族——combline_coupling_gap 只做单对 k_ij→(w,g_ij)
  换算（装载斜率档与模板链互补，非整体设计复刻）。
- 有限杆厚/端电容（Getsinger 有限厚度修正）不在 v1 口径（零厚度极限，如实
  note）。R7 审计行提及的 Caspi 自电容比**多项式近似**不在本键口径（本键走
  Getsinger 共形映射精确闭式反解，精度高于多项式近似档）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 零厚度耦合杆条带线（两接地平板间距 b，杆宽 w、缝 s，均匀 εr；Getsinger,
  IRE Trans. MTT-10(1) 1962 "Coupled Rectangular Bars Between Parallel
  Plates" 薄条极限；Gupta《Computer-Aided Design of Microwave Circuits》
  耦合带状线同式）。共形映射精确闭式：

      x = πw/(2b)，y = π(w+s)/(2b)
      k_e = tanh(x)·tanh(y)，  k_e' = sqrt(cosh²y + sinh²x)/(cosh x·cosh y)
      k_o = tanh(x)/tanh(y)，  k_o' = sqrt(sinh(y−x)·sinh(y+x))/(sinh y·cosh x)

  （k' 平方根写法为 1−k² 的消相消稳定形：s→0 时 k_o'→0 不经 1−k² 相消。）
  模阻抗（30π 工程惯例口径，与 rf_line._stripline_z0 同源）：

      Z0m = 30π/(√εr·r_m)，r_m = K(k_m)/K'(k_m) = AGM(1,k_m)/AGM(1,k_m')

  模电容（TEM，C_m = √εr/(c₀·Z0m)）：C_e < C_o 恒（Z0e>Z0o）。双极限锚：
  s→∞ 退化为单杆条带线精确值（vs rf_line stripline 跨键）；s→0 偶模每线电
  容=并合 2w 宽单线电容之半（Landen 恒等式 tanh²x = (1−sech 2x)/(1+sech
  2x) 的数值逐位），Z0o→低阻（缝面虚地）。
- 倒置器/耦合系数（ Getsinger 等效网络，MYJ ch.10 口径；与 Cohn 精确开路
  节倒置器同族）：

      J_m,m+1 = v·(C_o − C_e)/2   [S]（v=c₀/√εr）
      k_phys = (C_o − C_e)/(C_o + C_e) ≡ (Z0e − Z0o)/(Z0e + Z0o)（TEM 恒等）

- 综合（λ/4 短路杆斜率 b_s = π/(4·Z_r)，MYJ；与 λ/2 谐振器斜率 πY_r/2 差
  一倍=谐振器型别）：

      J_01 = sqrt(b_s·δ/(Z0·g_0·g_1))，J_j = b_s·δ/sqrt(g_j·g_{j+1})，
      J_n,n+1 = sqrt(b_s·δ/(Z0·g_n·g_{n+1}))

  内节归一化耦合 k_j ≡ J_j/b_s = δ/sqrt(g_j g_{j+1})（构造恒等，测试逐位；
  端节是外部 Q_e=g_0g_1/δ 语义，不套此式）。逐
  节电容目标（几何均值约束 sqrt(C_e·C_o) = 1/(v·Z_r) ⇔ Z0e·Z0o=Z_r²）：

      C_e,o = (√(ΔC² + 4C_0²) ∓ ΔC)/2，ΔC = 2J/v，C_0 = 1/(v·Z_r)

  闭式精确（无小 x 近似）。(C_e,C_o)→(w,s) 二维数值反解（嵌套 brentq：内
  层固定 w 对 C_e 解 s（C_e 随 s 单调降），外层对 C_o 解 w）。杆长 =
  λ/4@√εr（均匀介质 TEM 精确，无色散修正项）。
- **combline 半边（combline_coupling_gap，W3-CORE7）**：剖面电容闭式与上
  同源（Getsinger 1962 同一几何——combline 与交指的截面数学恒同，电学区别
  在激励端：combline 杆同端接地+开路端集总装载）。输入 k_ij=MYJ 综合
  归一化耦合（=δ/√(g_j·g_{j+1}) 口径，与耦合矩阵综合/coupled_line_bpf 的
  k 面同源），换算链::

      J_ij = b_s·k_ij（窄带倒置器-耦合关系，MYJ ch.8/10）
      (C_e,C_o) 目标 = 上述几何均值约束闭式
      (w, g_ij) = 二维反解（带域边界二分：w_a=C_e(w,s_hi)=目标根、
                  w_b=C_e(w,s_lo)=目标根，h(w)=C_o(w,s_for_Ce(w))−目标
                  在 [w_a,w_b] 单调 −→+ 穿越，brentq 求根——比交指综合键
                  的对数网格扫描多一项带域边缘确定性，弱耦合窄带不掉根）

  斜率双档：缺省**空载 λ/4 短路杆** b_s=π/(4·Z_r)（与交指综合键同源）；
  给 cap_ff+f0_ghz 走 **combline 装载斜率**（本仓对 MYJ ch.8 等效电路的
  第一性推导：Y_in=j[ωC−cotθ/Z_r]，B(ω)=ωC−cotθ/Z_r，谐振条件
  ω₀CZ_r·tanθ₀=1 与 combline_resonance 同解）::

      b_s = [cotθ₀ + θ₀·csc²θ₀]/(2·Z_r)，  θ₀=arctan(1/(ω₀C·Z_r))

  （θ₀→90°（C→0）退化极限=π/(4Z_r) 恒等，锚树钉；杆长
  l=θ₀·c₀/(2π·f₀·√εeff) 与 combline_resonance 反解式同源。）
  输出并列两口径耦合：k_norm_realized=J_realized/b_s（MYJ 综合归一化档，
  与输入同口径 roundtrip）与 k_exact_phys=(C_o−C_e)/(C_o+C_e)（精确阻抗/
  电容定义档）——两者差为综合归一化线性化的系统差（O(k)，非误差），如实
  并列由消费方按语义取用。
  出处（剖面电容：Getsinger, IRE Trans. MTT-10(1) 1962 薄条极限——
  combline 与交指截面几何恒同；k_ij↔J_ij 与归一化耦合口径：Matthaei–
  Young–Jones ch.8 combline / ch.10 倒置器综合，章节级转引；装载斜率
  b_s=[cotθ₀+θ₀csc²θ₀]/(2Z_r) 为本仓 MYJ ch.8 等效电路第一性推导，实现
  前独立复算：k roundtrip ≤1e-15、k↔J 代数互逆恒等式、跨键结构锚（同参
  内节 (w,s) 与 interdigital_bpf_synthesize 逐位）、θ₀→90° 退化=π/(4Z_r)
  恒等，独立验证轨迹（内部档），锚树
  tests/unit/test_aurora_d_core7.py）。

数值锚（#118 独立来源；锚树 tests/unit/test_a3c_coupled_interdigital.py 与
tests/unit/test_aurora_d_core7.py）
- s→∞：Z0e=Z0o=单杆条带线值，vs rf_line stripline_analysis 跨键逐位
  （AGM 收敛 ~1e-10）；s→0：Z0e = 2×（2w 并合条单线值）逐位。
- k 恒等：(Z0e−Z0o)/(Z0e+Z0o) == (C_o−C_e)/(C_o+C_e) 逐位（TEM）。
- J 往返：J_model(w_j, s_j) == J_target（brentq xtol）；对称滤波器
  s_1=s_{n+1}、s_2=s_{n−1}（奇 N 回文 g 序列）；δ↑ → 缝单调收窄。
- combline 半边（core7）：k roundtrip ≤1e-15；k_exact == J·Z_r/√(1+(J·Z_r)²)
  恒等式（k↔J 精确代数互逆，第二路线）；同 (k,Z_r,b,εr) 内节对 → 与
  interdigital_bpf_synthesize 对应节 (w,s) 同值（截面同源结构锚）；k↑ →
  缝单调收窄；装载斜率 θ₀→90° 退化=π/(4Z_r) 逐位、θ₀ 与
  combline_resonance 跨键同解。

守卫：w_mm>0、s_mm>0、b_mm>w_mm（杆须在板间）、epsilon_r≥1；综合键
order≥2 整数、0<fbw≤1、ripple_db>0、b_mm>0；缝反解越域（极强耦合达 s 下
限 / 极弱耦合越上限）显式拒绝（附节序号与残差）；combline 键 k∈(0,1) 开
区间、s 上限 12b（tanh 饱和阈 y=πs/2b≲19，#334 同族——超界=数值上等价无
穷远，弱耦合越界显式拒绝）、w 上限 6b（x=πw/2b≤9.42 防 tanh 饱和，与交指
综合键同界）；cap_ff/f0_ghz 成对给（单给显式拒绝）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

_SOURCES = {
    "bars": ("Getsinger IRE Trans. MTT-10(1) 1962 薄条极限（零厚度耦合杆"
             "平行板闭式）；Gupta CAD 耦合带状线同式；模阻抗 30π 口径与 "
             "rf_line._stripline_z0 同源"),
    "synth": ("Getsinger IRE Trans. MTT-9(1) 1961 等效网络 + MYJ ch.10 交"
              "指综合口径；λ/4 短路杆斜率 b=π/(4Z_r)；J→(C_e,C_o) 几何均"
              "值约束闭式精确解"),
    "combline": ("剖面电容：Getsinger IRE Trans. MTT-10(1) 1962 薄条极限"
                 "（combline 与交指截面几何恒同）；k_ij↔J_ij 与归一化耦"
                 "合口径：Matthaei-Young-Jones ch.8 combline / ch.10 倒置"
                 "器综合（章节级转引）；装载斜率 b_s=[cotθ₀+θ₀csc²θ₀]/"
                 "(2Z_r) 为本仓 MYJ ch.8 等效电路第一性推导（谐振条件与 "
                 "combline_resonance 同解自洽，θ₀→90° 退化=π/(4Z_r) 恒"
                 "等；实现前独立复算：k roundtrip ≤1e-15、k↔J 代数互逆"
                 "恒等式、跨键结构锚，轨迹 "
                 "独立验证轨迹（内部档），锚树 "
                 "tests/unit/test_aurora_d_core7.py）"),
}


def _agm_ratio(k: float) -> float:
    """K(k)/K'(k) = AGM(1,k)/AGM(1,k')（AGM 恒等式，80 轮收敛）。"""
    kp = math.sqrt(max(0.0, 1.0 - k * k))
    a, b = 1.0, k
    c, d = 1.0, kp
    for _ in range(80):
        a, b = 0.5 * (a + b), math.sqrt(a * b)
        c, d = 0.5 * (c + d), math.sqrt(c * d)
        if abs(a - b) < 1e-15 * a and abs(c - d) < 1e-15 * c:
            break
    return a / c


def _bars_even_odd(w_mm: float, s_mm: float, b_mm: float,
                   epsilon_r: float) -> dict[str, float]:
    """零厚度耦合杆条带线偶/奇模闭式（稳定形；见模块 docstring 出处）。"""
    x = math.pi * w_mm / (2.0 * b_mm)
    y = math.pi * (w_mm + s_mm) / (2.0 * b_mm)
    tx, ty = math.tanh(x), math.tanh(y)
    shx = math.sinh(x)
    shy, chx, chy = math.sinh(y), math.cosh(x), math.cosh(y)
    k_e = tx * ty
    k_o = tx / ty
    kp_e = math.sqrt(chy * chy + shx * shx) / (chx * chy)
    kp_o = math.sqrt(math.sinh(y - x) * math.sinh(y + x)) / (shy * chx)
    z0e = 30.0 * math.pi / (_agm_ratio(k_e) * math.sqrt(epsilon_r))
    z0o = 30.0 * math.pi / (_agm_ratio(k_o) * math.sqrt(epsilon_r))
    c_scale = math.sqrt(epsilon_r) / (C_MM_GHZ * 1e6)   # F/m = √εr/(c₀·Z0)
    c_e = c_scale / z0e
    c_o = c_scale / z0o
    return {"z0e": z0e, "z0o": z0o, "c_e": c_e, "c_o": c_o,
            "k_e": k_e, "k_o": k_o, "kp_e": kp_e, "kp_o": kp_o}


# ─── 键 3：耦合杆偶/奇电容闭式 ───────────────────────────────────────────────

@register_calculator(
    "interdigital_bars_capacitance",
    "交指杆偶奇电容闭式：零厚度耦合杆条带线（平行板间距 b，Getsinger 1962 "
    "薄条极限）共形映射精确解——(w,s,b,εr) → 偶/奇模阻抗 Z0e/Z0o、每米电容 "
    "C_e/C_o、耦合系数 k=(C_o−C_e)/(C_o+C_e)、倒置器 J=v·(C_o−C_e)/2。锚："
    "s→∞ 退化单杆条带线精确值（rf_line 跨键逐位）；s→0 偶模=并合 2w 条电容"
    "之半（Landen 恒等）；k 的电容/阻抗两式恒等",
    (("w_mm", "float mm 杆宽（>0）"),
     ("s_mm", "float mm 缝宽（>0）"),
     ("b_mm", "float mm 两接地平板间距（>w_mm）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1）")),
    required=("w_mm", "s_mm", "b_mm", "epsilon_r"),
)
def interdigital_bars_capacitance(w_mm: float, s_mm: float, b_mm: float,
                                  epsilon_r: float) -> dict[str, Any]:
    w = _finite(w_mm, "w_mm")
    s = _finite(s_mm, "s_mm")
    b = _finite(b_mm, "b_mm")
    er = _finite(epsilon_r, "epsilon_r")
    if w <= 0.0:
        raise ValueError(
            f"interdigital_bars_capacitance: w_mm 必须 >0，得到 {w_mm!r}")
    if s <= 0.0:
        raise ValueError(
            f"interdigital_bars_capacitance: s_mm 必须 >0，得到 {s_mm!r}")
    if b <= w:
        raise ValueError(
            f"interdigital_bars_capacitance: 须 b_mm > w_mm（杆须在板间），"
            f"得到 b={b_mm!r}, w={w_mm!r}")
    if er < 1.0:
        raise ValueError(
            f"interdigital_bars_capacitance: epsilon_r 必须 ≥1，得到 {er!r}")

    d = _bars_even_odd(w, s, b, er)
    v = C_MM_GHZ * 1e6 / math.sqrt(er)                    # m/s
    k_cap = (d["c_o"] - d["c_e"]) / (d["c_o"] + d["c_e"])
    k_imp = (d["z0e"] - d["z0o"]) / (d["z0e"] + d["z0o"])
    j_inv = v * (d["c_o"] - d["c_e"]) / 2.0
    return {
        "w_mm": w,
        "s_mm": s,
        "b_mm": b,
        "epsilon_r": er,
        "z0e_ohm": round(d["z0e"], 9),
        "z0o_ohm": round(d["z0o"], 9),
        "c_e_pf_per_m": round(d["c_e"] * 1e12, 12),
        "c_o_pf_per_m": round(d["c_o"] * 1e12, 12),
        "k_coupling": round(k_cap, 15),
        "k_impedance_identity_dev": round(abs(k_cap - k_imp), 15),
        "j_inverter_s": round(j_inv, 15),
        "zr_ohm": round(math.sqrt(d["z0e"] * d["z0o"]), 9),
        "note": (
            "零厚度均匀介质条带线口径（Getsinger 1962 薄条极限）；微带非均"
            "匀介质交指实现走 render_c3 KJ 链（adapter 层）；有限杆厚/端电"
            "容修正不在本键；k_impedance_identity_dev=电容式与阻抗式两表 "
            "达恒等偏差（TEM，应机器精度）"),
        "source": _SOURCES["bars"],
    }


# ─── 键 4：交指带通综合（Getsinger 等效网络）────────────────────────────────

def _c_targets(j_target: float, v: float, z_r: float) -> tuple[float, float]:
    """J 目标 → (C_e, C_o)（几何均值约束 sqrt(C_eC_o)=1/(v Z_r) 闭式）。"""
    d_c = 2.0 * j_target / v
    c0 = 1.0 / (v * z_r)
    root = math.sqrt(d_c * d_c + 4.0 * c0 * c0)
    return (root - d_c) / 2.0, (root + d_c) / 2.0


@register_calculator(
    "interdigital_bpf_synthesize",
    "交指带通综合（Getsinger 等效网络）：全极点切比雪夫 g 值 → λ/4 短路杆斜"
    "率 b=π/(4Z_r) → J 倒置器目标 → 逐节 (C_e,C_o) 闭式 → 零厚度耦合杆条带"
    "线二维反解杆宽/缝 mm → 杆长 λ/4@√εr。锚：J 往返逐位；对称滤波器缝回文"
    "（s_1=s_{n+1}）；J·4Z_r/π=δ/√(g_jg_{j+1}) 构造恒等；δ↑ 缝单调收窄",
    (("order", "int 阶数 N（≥2；谐振器数，耦合缝=N+1）"),
     ("f0_ghz", "float GHz 中心频率（>0）"),
     ("fbw", "float 相对带宽 δ（0<δ≤1）"),
     ("ripple_db", "float dB 通带等纹波（>0）"),
     ("b_mm", "float mm 接地平板间距（>0；条带线介质档口径）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1）"),
     ("z0_ohm", "float Ω 端口阻抗（>0，缺省 50）"),
     ("z_r_ohm", "float Ω 杆特性阻抗目标 Z0e·Z0o=Z_r²（>0，缺省=z0_ohm）")),
    required=("order", "f0_ghz", "fbw", "ripple_db", "b_mm", "epsilon_r"),
)
def interdigital_bpf_synthesize(order: int, f0_ghz: float, fbw: float,
                                ripple_db: float, b_mm: float,
                                epsilon_r: float, z0_ohm: float = 50.0,
                                z_r_ohm: float | None = None) -> dict[str, Any]:
    from scipy.optimize import brentq

    n = int(order)
    if n < 2 or order != int(order):
        raise ValueError(
            f"interdigital_bpf_synthesize: order 须为 ≥2 整数，得到 {order!r}")
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    delta = _finite(fbw, "fbw")
    if not 0.0 < delta <= 1.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: fbw 须在 (0,1]，得到 {fbw!r}")
    rip = _finite(ripple_db, "ripple_db")
    if rip <= 0.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: ripple_db 必须 >0，得到 {rip!r}")
    b = _finite(b_mm, "b_mm")
    if b <= 0.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: b_mm 必须 >0，得到 {b_mm!r}")
    er = _finite(epsilon_r, "epsilon_r")
    if er < 1.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: epsilon_r 必须 ≥1，得到 {er!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    z_r = float(z_r_ohm) if z_r_ohm is not None else z0
    z_r = _finite(z_r, "z_r_ohm")
    if z_r <= 0.0:
        raise ValueError(
            f"interdigital_bpf_synthesize: z_r_ohm 必须 >0，得到 {z_r_ohm!r}")

    from .coupled_line_bpf import _g_values

    g = _g_values(n, rip)
    v = C_MM_GHZ * 1e6 / math.sqrt(er)                    # m/s
    b_slope = math.pi / (4.0 * z_r)                       # λ/4 短路杆斜率
    j_targets = [math.sqrt(b_slope * delta / (z0 * g[0] * g[1]))]
    for j in range(1, n):
        j_targets.append(b_slope * delta / math.sqrt(g[j] * g[j + 1]))
    j_targets.append(math.sqrt(b_slope * delta / (z0 * g[n] * g[n + 1])))

    s_lo, s_hi = 1e-4, 6.0 * b
    w_lo, w_hi = 1e-3 * b, 6.0 * b   # 上限 6b：x=πw/2b≤9.4 防 tanh 饱和（k→1
    # 逐位饱和使 AGM 分母归零静默爆数——rf_line R1-1 同族陷阱，稳形 k_o' 不救
    # 分母）

    def c_e_of(w: float, s: float) -> float:
        return _bars_even_odd(w, s, b, er)["c_e"]

    def s_for_c_e(w: float, c_e_t: float) -> float | None:
        """内层：固定 w 对 C_e 解 s（C_e 随 s 单调**升**，s→∞ 退化单杆值）；
        不可达返 None。"""
        f_lo = c_e_of(w, s_lo)
        f_hi = c_e_of(w, s_hi)
        if not max(f_lo, f_hi) > c_e_t > min(f_lo, f_hi):
            return None
        return float(brentq(lambda s_: c_e_of(w, s_) - c_e_t, s_lo, s_hi,
                            xtol=1e-12))

    def h_res(w: float, c_e_t: float, c_o_t: float) -> float | None:
        ss = s_for_c_e(w, c_e_t)
        if ss is None:
            return None
        return _bars_even_odd(w, ss, b, er)["c_o"] - c_o_t

    grid = [w_lo * (w_hi / w_lo) ** (i / 47.0) for i in range(48)]
    sections: list[dict[str, Any]] = []
    for j, jt in enumerate(j_targets):
        c_e_t, c_o_t = _c_targets(jt, v, z_r)
        prev: tuple[float, float] | None = None
        bracket: tuple[float, float] | None = None
        for w_g in grid:
            hv = h_res(w_g, c_e_t, c_o_t)
            if hv is None:
                prev = None
                continue
            if prev is not None and prev[1] * hv < 0.0:
                bracket = (prev[0], w_g)
                break
            prev = (w_g, hv)
        if bracket is None:
            raise ValueError(
                f"interdigital_bpf_synthesize: 第 {j + 1}/{n + 1} 节 "
                f"(C_e,C_o)=({c_e_t:.4e},{c_o_t:.4e}) F/m 在条带线模型可达域"
                f"外（w 网格 48 点无变号；调整 b/εr 或带宽）")
        c_e_j, c_o_j = c_e_t, c_o_t
        w_mm = float(brentq(
            lambda w_, ce=c_e_j, co=c_o_j: h_res(w_, ce, co),
            bracket[0], bracket[1], xtol=1e-10))
        s_mm = s_for_c_e(w_mm, c_e_t)
        assert s_mm is not None
        back = _bars_even_odd(w_mm, s_mm, b, er)
        j_back = v * (back["c_o"] - back["c_e"]) / 2.0
        sections.append({
            "index": j + 1,
            "j_target_s": round(jt, 15),
            "c_e_target_pf_m": round(c_e_t * 1e12, 12),
            "c_o_target_pf_m": round(c_o_t * 1e12, 12),
            "w_mm": round(w_mm, 6),
            "s_mm": round(s_mm, 6),
            "z0e_ohm": round(back["z0e"], 9),
            "z0o_ohm": round(back["z0o"], 9),
            "j_realized_s": round(j_back, 15),
        })

    rod_len = C_MM_GHZ / (4.0 * f0 * math.sqrt(er))
    # 归一化耦合（内节语义）：k_j = J_j/b_s = δ/√(g_j g_{j+1})，j=1..n−1
    # （端节是外部耦合 Q_e=g_0g_1/δ 语义，非此式——如实分列）
    k_interior = [round(delta / math.sqrt(g[j] * g[j + 1]), 15)
                  for j in range(1, n)]
    return {
        "order": n,
        "f0_ghz": f0,
        "fbw": delta,
        "ripple_db": rip,
        "b_mm": b,
        "epsilon_r": er,
        "z0_ohm": z0,
        "z_r_ohm": z_r,
        "g_list": [round(v2, 9) for v2 in g],
        "k_interior_norm": k_interior,
        "qe_in": round(g[0] * g[1] / delta, 9),
        "qe_out": round(g[n] * g[n + 1] / delta, 9),
        "j_targets_s": [round(v2, 15) for v2 in j_targets],
        "w_mm": [s["w_mm"] for s in sections],
        "s_mm": [s["s_mm"] for s in sections],
        "z0e_ohm": [s["z0e_ohm"] for s in sections],
        "z0o_ohm": [s["z0o_ohm"] for s in sections],
        "sections": sections,
        "rod_len_mm": round(rod_len, 6),
        "j_roundtrip_rel_dev_max": round(
            max(abs(s["j_realized_s"] / s["j_target_s"] - 1.0)
                for s in sections), 15),
        "note": (
            "条带线介质档（零厚度杆、均匀 εr、平行板 b）——微带非均匀介质交"
            "指走 render_c3 KJ 链（adapter 层）；杆长为理想 λ/4@√εr（接地端"
            "交替，开路端 Δl 与端电容 Getsinger 修正不在 v1 口径）；抽头位输"
            "入耦合（hairpin_tap_frac_from_qe）与负载电容型 combline 装载不"
            "在本键"),
        "source": _SOURCES["synth"],
    }


# ─── 键 5：combline 耦合缝 k_ij→(w,g_ij) 换算（W3-CORE7 combline 半边）──────

#: 缝上限倍数（s_hi=12b：tanh 饱和阈 y=πs/2b≲19，#334 同族——超界=数值上
#: 等价无穷远，弱耦合越界显式拒绝）
_COMBLINE_S_HI_MULT = 12.0
#: 杆宽上限倍数（w_hi=6b：x=πw/2b≤9.42 防 tanh 饱和，与交指综合键同界）
_COMBLINE_W_HI_MULT = 6.0


def _combline_pair_invert(
    c_e_t: float, c_o_t: float, b_mm: float, epsilon_r: float,
    tag: str,
) -> tuple[float, float]:
    """(C_e,C_o) 目标 → (w_mm, s_mm) 带域边界二分反解（combline 半边）。

    带域构造（C_e(w,s) 对 w、s 均严格单调升——tanh 自变量双增，AGM 比
    单调）：w_a=C_e(w,s_hi)=c_e_t 根、w_b=C_e(w,s_lo)=c_e_t 根；内层
    s_for_Ce(w) 在 (w_a,w_b) 内恒有解；h(w)=C_o(w,s_for_Ce(w))−c_o_t 在
    带域 −→+ 单调穿越（w→w_a⁺：s→s_hi，C_o→c_e_t+ΔC(s_hi)；w→w_b⁻：
    s→s_lo，C_o→大）→ brentq 求根。左边缘判据：h(w_a⁺)=ΔC(w_a,s_hi)
    −ΔC_needed ≥0 → k 太弱（所需缝超 s_hi）显式拒绝。

    相比 interdigital_bpf_synthesize 的对数网格扫描（48 点，内节 J 档够
    用），本反解对任意弱耦合窄带不掉根（带域边缘确定性），两键行为互不
    改动（扩展面新增，既有键逐字节不动）。
    """
    from scipy.optimize import brentq

    s_lo, s_hi = 1e-4, _COMBLINE_S_HI_MULT * b_mm
    w_lo, w_hi = 1e-3 * b_mm, _COMBLINE_W_HI_MULT * b_mm

    def ce_of(w: float, s: float) -> float:
        return _bars_even_odd(w, s, b_mm, epsilon_r)["c_e"]

    def co_of(w: float, s: float) -> float:
        return _bars_even_odd(w, s, b_mm, epsilon_r)["c_o"]

    # 带域可达性三判（每判附语义化越域消息）
    if c_e_t <= ce_of(w_lo, s_hi):
        raise ValueError(
            f"{tag}: 耦合过强越域——目标 C_e={c_e_t:.6e} F/m 低于模型可达"
            f"下界 {ce_of(w_lo, s_hi):.6e} F/m（w≥{w_lo:.3g}mm、s≤"
            f"{_COMBLINE_S_HI_MULT * b_mm:.3g}mm 档；调大 b/εr 或降低 k）")
    if c_e_t >= ce_of(w_hi, s_hi):
        s_cap_mm = _COMBLINE_S_HI_MULT * b_mm
        raise ValueError(
            f"{tag}: 耦合过弱越域——目标 C_e={c_e_t:.6e} F/m 超出模型域可达"
            f"上界 {ce_of(w_hi, s_hi):.6e} F/m（w≤{_COMBLINE_W_HI_MULT}b、"
            f"s≤{s_cap_mm:.3g}mm 档；Z_r 过低使 C0 超几何可达，或所需缝超 "
            "tanh 饱和阈——调大 b/εr 或提高 Z_r/k）")
    if c_e_t >= ce_of(w_hi, s_lo):
        raise ValueError(
            f"{tag}: 目标 C_e={c_e_t:.6e} F/m 需 w>{w_hi:.3g}mm（"
            f"{_COMBLINE_W_HI_MULT}b 上界，防 tanh 饱和；Z_r 过低所致）")

    w_a = float(brentq(lambda w_: ce_of(w_, s_hi) - c_e_t, w_lo, w_hi,
                       xtol=1e-12))
    w_b = float(brentq(lambda w_: ce_of(w_, s_lo) - c_e_t, w_lo, w_hi,
                       xtol=1e-12))

    def s_for_ce(w: float) -> float:
        f_lo = ce_of(w, s_lo) - c_e_t
        if f_lo >= 0.0:
            return s_lo  # w_b 边缘舍入
        f_hi = ce_of(w, s_hi) - c_e_t
        if f_hi <= 0.0:
            return s_hi  # w_a 边缘舍入
        return float(brentq(lambda s_: ce_of(w, s_) - c_e_t, s_lo, s_hi,
                            xtol=1e-12))

    def h(w: float) -> float:
        return co_of(w, s_for_ce(w)) - c_o_t

    # 左边缘极限判据：ΔC(w_a,s_hi) < ΔC_needed 才有根（否则 k 太弱）
    h_a = (co_of(w_a, s_hi) - ce_of(w_a, s_hi)) - (c_o_t - c_e_t)
    if h_a >= 0.0:
        raise ValueError(
            f"{tag}: 耦合过弱越域——ΔC 需求 {c_o_t - c_e_t:.6e} F/m 超过 "
            f"s={s_hi:.3g}mm 上限可达值 {h_a + (c_o_t - c_e_t):.6e} F/m"
            "（调小 b/εr 或提高 k）")
    if h(w_b * (1.0 - 1e-12)) <= 0.0:
        raise ValueError(
            f"{tag}: 反解带域右边缘非正（h(w_b)≤0）——参数组合超出模型域")
    w_mm = float(brentq(h, w_a, w_b, xtol=1e-12))
    s_mm = s_for_ce(w_mm)
    return w_mm, s_mm


@register_calculator(
    "combline_coupling_gap",
    "combline 耦合缝→间隙换算：k_ij（MYJ 综合归一化耦合=δ/√(g_j·g_{j+1})"
    "口径）→ J=b_s·k_ij → (C_e,C_o) 几何均值约束闭式 → (w,g_ij) 带域边界"
    "二分反解（combline 半边，截面电容与 interdigital 两键同源 Getsinger "
    "共形映射）；斜率双档=空载 λ/4 杆 π/(4Z_r)（缺省，与交指综合键同源）"
    "或 combline 装载斜率 [cotθ₀+θ₀csc²θ₀]/(2Z_r)（给 cap_ff+f0_ghz，θ₀ "
    "与 combline_resonance 同解）；输出并列 k_norm_realized（MYJ 档 "
    "roundtrip）与 k_exact_phys（精确阻抗/电容定义档）",
    (("k_coupling", "float 归一化耦合系数 k_ij（0<k<1 开区间；MYJ 综合"
      "口径）"),
     ("z_r_ohm", "float Ω 杆特性阻抗目标 Z0e·Z0o=Z_r²（>0）"),
     ("b_mm", "float mm 两接地平板间距（>0；条带线介质档口径）"),
     ("epsilon_r", "float 填充介质相对介电常数（≥1）"),
     ("cap_ff", "float fF 开路端装载电容（>0；与 f0_ghz 成对给=装载斜率档）"),
     ("f0_ghz", "float GHz 装载档谐振频率（>0；与 cap_ff 成对；给了才出"
      "杆长）")),
    required=("k_coupling", "z_r_ohm", "b_mm", "epsilon_r"),
)
def combline_coupling_gap(
    k_coupling: float,
    z_r_ohm: float,
    b_mm: float,
    epsilon_r: float,
    cap_ff: float | None = None,
    f0_ghz: float | None = None,
) -> dict[str, Any]:
    """combline 耦合缝 k_ij→(w,g_ij)：k→J→(C_e,C_o)→带域二分反解。"""
    tag = "combline_coupling_gap"
    k_in = _finite(k_coupling, "k_coupling")
    if not 0.0 < k_in < 1.0:
        raise ValueError(
            f"{tag}: k_coupling 必须 ∈(0,1) 开区间（0=无耦合/1=完全耦合"
            f"退化档不收），得到 {k_coupling!r}")
    z_r = _finite(z_r_ohm, "z_r_ohm")
    if z_r <= 0.0:
        raise ValueError(f"{tag}: z_r_ohm 必须 >0，得到 {z_r_ohm!r}")
    b = _finite(b_mm, "b_mm")
    if b <= 0.0:
        raise ValueError(f"{tag}: b_mm 必须 >0，得到 {b_mm!r}")
    er = _finite(epsilon_r, "epsilon_r")
    if er < 1.0:
        raise ValueError(f"{tag}: epsilon_r 必须 ≥1，得到 {er!r}")

    has_cap = cap_ff is not None
    has_f0 = f0_ghz is not None
    if has_cap != has_f0:
        raise ValueError(
            f"{tag}: cap_ff 与 f0_ghz 须成对给（装载斜率档），单给显式拒绝")
    theta0_rad = math.pi / 2.0
    rod_len = None
    if has_cap:
        cap_f = _finite(cap_ff, "cap_ff") * 1e-15  # fF → F
        if cap_f <= 0.0:
            raise ValueError(f"{tag}: cap_ff 必须 >0，得到 {cap_ff!r}")
        f0 = _finite(f0_ghz, "f0_ghz")
        if f0 <= 0.0:
            raise ValueError(f"{tag}: f0_ghz 必须 >0，得到 {f0_ghz!r}")
        w0 = 2.0 * math.pi * f0 * 1e9
        theta0_rad = math.atan(1.0 / (w0 * cap_f * z_r))
        b_slope = (1.0 / math.tan(theta0_rad)
                   + theta0_rad / math.sin(theta0_rad) ** 2) / (2.0 * z_r)
        slope_mode = "loaded_combline"
        rod_len = theta0_rad * C_MM_GHZ / (2.0 * math.pi * f0
                                           * math.sqrt(er))
    else:
        b_slope = math.pi / (4.0 * z_r)
        slope_mode = "unloaded_quarter_wave"

    v = C_MM_GHZ * 1e6 / math.sqrt(er)                    # m/s
    j_target = b_slope * k_in
    c_e_t, c_o_t = _c_targets(j_target, v, z_r)
    w_mm, s_mm = _combline_pair_invert(c_e_t, c_o_t, b, er, tag)
    back = _bars_even_odd(w_mm, s_mm, b, er)
    j_real = v * (back["c_o"] - back["c_e"]) / 2.0
    k_norm_back = j_real / b_slope
    k_exact = (back["c_o"] - back["c_e"]) / (back["c_o"] + back["c_e"])
    k_imp = (back["z0e"] - back["z0o"]) / (back["z0e"] + back["z0o"])

    out: dict[str, Any] = {
        "k_coupling": k_in,
        "z_r_ohm": z_r,
        "b_mm": b,
        "epsilon_r": er,
        "slope_mode": slope_mode,
        "theta0_deg": round(math.degrees(theta0_rad), 12),
        "b_slope_per_ohm": round(b_slope, 15),
        "j_target_s": round(j_target, 15),
        "c_e_target_pf_m": round(c_e_t * 1e12, 12),
        "c_o_target_pf_m": round(c_o_t * 1e12, 12),
        "w_mm": round(w_mm, 6),
        "gap_mm": round(s_mm, 6),
        "z0e_ohm": round(back["z0e"], 9),
        "z0o_ohm": round(back["z0o"], 9),
        "j_realized_s": round(j_real, 15),
        "k_norm_realized": round(k_norm_back, 15),
        "k_roundtrip_abs_dev": round(abs(k_norm_back - k_in), 15),
        "k_exact_phys": round(k_exact, 15),
        "k_impedance_identity_dev": round(abs(k_exact - k_imp), 15),
        "rod_len_mm": round(rod_len, 6) if rod_len is not None else None,
    }
    out["note"] = (
        "截面电容闭式与 interdigital_bars_capacitance/interdigital_bpf_"
        "synthesize 同源（combline 与交指截面几何恒同，电学区别=同端接地+"
        "开路端集总装载）；k_coupling 输入口径=MYJ 综合归一化耦合（δ/√"
        "(g_j·g_{j+1})，与耦合矩阵/coupled_line_bpf 的 k 面同源）→ "
        "J=b_s·k；k_norm_realized=J_realized/b_s（与输入同口径 roundtrip）"
        "与 k_exact_phys=(C_o−C_e)/(C_o+C_e)（精确阻抗/电容定义档）并列——"
        "两者差为综合归一化线性化的系统差（O(k)，非误差），消费方按语义"
        "取用；gap 上限 12b（tanh 饱和阈，#334 同族）、w 上限 6b；零厚度"
        "均匀介质条带线档——有限杆厚/端电容 Getsinger 修正不在 v1 口径；"
        "装载斜率 θ₀→90°（C→0）退化=π/(4Z_r)（锚树钉），θ₀ 与 "
        "combline_resonance 谐振条件同解；杆长 l=θ₀·c₀/(2πf₀√εr) 与 "
        "combline_resonance 反解式同源（空载档=λg/4）")
    out["source"] = _SOURCES["combline"]
    return out
