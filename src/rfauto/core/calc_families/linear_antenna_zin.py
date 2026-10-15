"""线天线/环输入阻抗族（aurora72 A3-B 席域 2，R7 第二梯队 T4）。

三键：dipole_emf_zin（有限长偶极输入阻抗：R=正弦电流辐射功率积分
路线 + X=感应电动势法 Si/Ci 经典闭式 + 谐振长度二分 + 方向性积分） /
folded_dipole_zin（折合偶极两模阻抗：天线模 4Z_d 与传输线模 2jZ_t·
tan(kl/2) 并联，等粗 4×300Ω 锚） / small_loop_zin（小环输入阻抗分解：
Rr=320π⁴N²(A/λ²)² ≡ 20π²N²(C/λ)⁴ ≡ 31171·N²(A/λ²)² 三式恒等 +
趋肤损耗/效率/Q）。

与既有天线面的边界（语义防撞，R7 §③ T4 三重搜索证据）
--------------------------------------------------------
- emc_radiated（Ott 环路场强）/exposure_limits = 辐射发射/暴露面；
  本族只做**天线单元输入阻抗端**。
- patch/helix/lpda（lpda_synthesis）/array_synthesis = 其他单元或阵
  列综合；本族只做**线天线（偶极/折合偶极）与小环**。
- antenna_q.py = 天线 Q/带宽面；本族 small_loop 的 Q 是小环输入阻抗
  分解副产品（X/(Rr+RL)），语义不同。
- 细偶极 King 数值逼近/矩量法曲线档不在本键口径（Sin-King 曲线的
  闭式近似属 empirical 档，如实不做——本键 R 路线对"正弦电流分布
  假设"是精确积分，X 闭式为感应电动势法经典形）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 偶极（总长 l，半长 h=l/2，正弦电流 I(z)=I_m·sin(k(h−|z|))，馈电点
  电流 I_feed=I_m·sin(kh)）：
  R（辐射功率积分路线，对假设分布精确）：远场
      E_θ = jηI_m e^{−jkr}/(2πr)·[cos(kh·cosθ)−cos(kh)]/sinθ
      R_in = η/(2π·sin²(kh))·∫₀^π [cos(kh·cosθ)−cos(kh)]²/sinθ dθ
  （scipy.quad 定精度确定式）。双锚测试钉：短偶极渐近 R→20π²(l/λ)²
  （三角电流分布极限，rel<1e-3）、半波 R=73.1Ω 教科书常数（窗口
  断言）。
  X（感应电动势法经典闭式，Balanis §8.4 印刷形，Si/Ci）：
      X = (η/4π)·{2Si(kl) + cos(kl)·[2Si(kl)−Si(2kl)]
                  − sin(kl)·[2Ci(kl)−Ci(2kl)−Ci(2ka²/l)]}
  半波锚 X=+j42.5Ω（kl=π 处 sin 项归零，半径项无关）；细线短偶极
  容性渐近（X≈(ηkl/2π)[1−ln(l/2a)]<0）与 |X| 随线径增大而减小的
  定性钉。口径如实注记：该闭式在 kl=π 处与两归一重合；远离谐振区
  为工程近似档（感应电动势法），精度不及矩量法。
  谐振长度：X=0 在 [0.40,0.50]λ 内二分（X(0.4λ)<0<X(0.5λ)=+42.5
  已验证），细线锚带 0.47~0.49λ（Numerical 文献带，本键实测 ~0.470λ
  @a=0.5mm/f=2GHz）。
  方向性：D = 2(1−cos kh)²/J（J=同一积分，l≤λ 主瓣在 θ=90°），
  半波 1.641→2.15dBi、短偶极→1.5（1.76dBi）双锚。
- 折合偶极（等线径 a，间距 s 中心距，Balanis 传输线法两模分解）：
  天线模 = 等效包络偶极阻抗 Z_d（本键 dipole 路线复用）；传输线模 =
  短路线 l/2 输入阻抗 jZ_t·tan(kl/2)，Z_t=(η/π)·acosh(s/(2a))（空气
  双线）；两模在馈点并联（推导：线模把 4Z_d 旁路——
      Z_in = 4Z_d·(2jZ_t·tan(kl/2))/(4Z_d + 2jZ_t·tan(kl/2))
  谐振 l=λ/2 处 tan→∞ → Z_in=4Z_d（等粗 4×；73.1Ω → 292Ω≈300Ω
  教科书口径，线径/间距在谐振点约去=恒等锚）；l=mλ 处 tan=0 →
  Z_in=0（短路边）定性钉。不等线径 Mushiake 精确步升比不在本键口径
  （如实不做）；Z_d 取线径 a（包络等效半径修正不做，如实注记）。
- 小环（单匝半径 b，N 匝，线径 a）：
      Rr = 320π⁴·N²·(A/λ²)²（A=πb²）≡ 20π²·N²·(C/λ)⁴（C=2πb）
         ≈ 31171·N²·(A/λ²)²   [三式恒等，320π⁴=31170.9 测试钉]
  损耗（趋肤口径，圆导体表面电流）：Rs=√(πfμ/σ)，
      R_L = Rs·(导线长 N·C)/(2πa) = Rs·N·b/a
  效率 η_r = Rr/(Rr+R_L)；电感（单匝圆环 Grover 闭式）
      L = μ0·b·[ln(8b/a) − 2]，X = 2πf·N²·L（密绕 N² 近似，匝间
  互感修正不做，如实注记）；Q = X/(Rr+R_L)。电小判据 C/λ ≤ 0.3
  守卫（超出电小假设如实拒绝）。

守卫：length_mm ∈ (0, λ)（单瓣正弦电流假设域；l=λ 全波馈点电流节点
Z_in→∞ 模型奇点显式拒绝）；f_ghz>0；
wire_radius_mm>0；折合 spacing_mm>2·wire_radius_mm（线不重叠）；
小环 wire_radius_mm<radius_mm、turns_n≥1、conductivity_s_per_m>0、
C/λ≤0.3；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_ETA0 = math.sqrt(_MU0 / _EPS0)
_EULER_GAMMA = 0.5772156649015329

_SOURCES = {
    "dipole": "R：正弦电流远场 E_θ=jηI_m e^{−jkr}/(2πr)·[cos(kh cosθ)−cos(kh)]/"
              "sinθ 辐射功率积分（Balanis ch4/6 正弦分布口径，quad 定精度）；"
              "X：感应电动势法 Si/Ci 经典闭式（Balanis §8.4 印刷形）",
    "folded": "Balanis ch9 折合偶极传输线法两模分解（天线模 Z_d ∥ 传输线模 "
              "jZ_t tan(kl/2)，等粗 4× 口径）",
    "loop": "Balanis ch5 小环：Rr=320π⁴N²(A/λ²)²≡20π²N²(C/λ)⁴；Grover 单匝"
            "圆环电感 L=μ0b[ln(8b/a)−2]；趋肤损耗 Rs 口径",
}


def _sici(x: float) -> tuple[float, float]:
    """正弦/余弦积分 (Si, Ci)（scipy 惰性导入，缓存键面零 IO）。"""
    from scipy.special import sici

    return sici(x)


def _dipole_power_integral(kh: float) -> float:
    """J(kh)=∫₀^π [cos(kh·cosθ)−cos(kh)]²/sinθ dθ（quad 定精度确定式）。"""
    from scipy.integrate import quad

    def integrand(theta: float) -> float:
        diff = math.cos(kh * math.cos(theta)) - math.cos(kh)
        return diff * diff / math.sin(theta)

    value, _err = quad(integrand, 1e-9, math.pi - 1e-9, limit=400,
                       epsabs=1e-12, epsrel=1e-12)
    return value


def _dipole_r_in(l_mm: float, f_ghz: float) -> tuple[float, float]:
    """偶极输入电阻（馈电归一）与 J 积分值（方向性复用）。"""
    lam_mm = C_MM_GHZ / f_ghz
    kh = math.pi * l_mm / lam_mm
    j_val = _dipole_power_integral(kh)
    r_in = _ETA0 * j_val / (2.0 * math.pi * math.sin(kh) ** 2)
    return r_in, j_val


def _dipole_x_in(l_mm: float, f_ghz: float, a_mm: float) -> float:
    """偶极输入电抗（感应电动势法 Si/Ci 经典闭式，Balanis §8.4 印刷形）。"""
    lam_mm = C_MM_GHZ / f_ghz
    kl = 2.0 * math.pi * l_mm / lam_mm
    si1, ci1 = _sici(kl)
    si2, ci2 = _sici(2.0 * kl)
    radius_arg = 2.0 * (2.0 * math.pi) * a_mm * a_mm / (lam_mm * l_mm)
    ci_radius = (_EULER_GAMMA + math.log(radius_arg)
                 if radius_arg < 1e-12 else _sici(radius_arg)[1])
    return (_ETA0 / (4.0 * math.pi)) * (
        2.0 * si1 + math.cos(kl) * (2.0 * si1 - si2)
        - math.sin(kl) * (2.0 * ci1 - ci2 - ci_radius))


def _dipole_directivity(l_mm: float, f_ghz: float, j_val: float) -> float:
    """方向性 D=2(1−cos kh)²/J（l≤λ 主瓣 θ=90°，与 R 共享同一积分）。"""
    kh = math.pi * l_mm / (C_MM_GHZ / f_ghz)
    return 2.0 * (1.0 - math.cos(kh)) ** 2 / j_val


# ─── 键 1：偶极输入阻抗（EMF R 积分 + X 闭式）───────────────────────────────

@register_calculator(
    "dipole_emf_zin",
    "偶极输入阻抗（正弦电流假设）：R=辐射功率积分路线 η/(2πsin²kh)·∫₀^π"
    "[cos(kh·cosθ)−cos(kh)]²/sinθdθ（对假设分布精确，quad 定精度）——"
    "短偶极渐近 20π²(l/λ)²（三角电流极限）与半波 73.1Ω 教科书常数双锚；"
    "X=感应电动势法 Si/Ci 经典闭式（Balanis §8.4 印刷形，含 Ci(2ka²/l) "
    "线径项）——半波 j42.5Ω 锚、细线容性渐近定性钉；谐振长度 [0.40,"
    "0.50]λ 二分（细线 ~0.47λ 锚带）；方向性 D 共享同一积分——半波 "
    "2.15dBi/短偶极 1.76dBi 双锚。域 l∈(0,λ)（单瓣正弦假设；l=λ 全波"
    "馈点电流节点奇点显式拒绝）",
    (("length_mm", "float mm 偶极总长 l（∈(0,λ)，单瓣正弦电流假设域）"),
     ("f_ghz", "float GHz 工作频率（>0）"),
     ("wire_radius_mm", "float mm 导线半径 a（>0；X 闭式线径项 Ci(2ka²/l) "
      "输入）")),
    required=("length_mm", "f_ghz", "wire_radius_mm"),
)
def dipole_emf_zin(length_mm: float, f_ghz: float,
                   wire_radius_mm: float) -> dict[str, Any]:
    l_mm = _finite(length_mm, "length_mm")
    freq = _finite(f_ghz, "f_ghz")
    a_mm = _finite(wire_radius_mm, "wire_radius_mm")
    if freq <= 0.0:
        raise ValueError(f"dipole_emf_zin: f_ghz 必须 >0，得到 {f_ghz!r}")
    lam_mm = C_MM_GHZ / freq
    if l_mm <= 0.0 or l_mm >= lam_mm:
        raise ValueError(
            f"dipole_emf_zin: length_mm 须 ∈(0, λ)（λ={lam_mm:.6f}mm，"
            f"单瓣正弦电流假设域；l=λ 全波馈点恰为电流节点 sin(kh)=0，"
            f"Z_in→∞ 模型奇点显式拒绝），得到 {length_mm!r}")
    if a_mm <= 0.0:
        raise ValueError(
            f"dipole_emf_zin: wire_radius_mm 必须 >0，得到 {wire_radius_mm!r}")

    r_in, j_val = _dipole_r_in(l_mm, freq)
    x_in = _dipole_x_in(l_mm, freq, a_mm)
    directivity = _dipole_directivity(l_mm, freq, j_val)

    # 谐振长度：X=0 在 [0.40,0.50]λ 内二分（端点符号已验证：
    # X(0.40λ)<0<X(0.50λ)=+j42.5）
    lo, hi = 0.40 * lam_mm, 0.50 * lam_mm
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _dipole_x_in(mid, freq, a_mm) < 0.0:
            lo = mid
        else:
            hi = mid
    l_res = 0.5 * (lo + hi)
    x_res = _dipole_x_in(l_res, freq, a_mm)

    return {
        "length_mm": l_mm,
        "f_ghz": freq,
        "wire_radius_mm": a_mm,
        "lambda_mm": round(lam_mm, 9),
        "l_over_lambda": round(l_mm / lam_mm, 12),
        "r_in_ohm": round(r_in, 9),
        "x_in_ohm": round(x_in, 9),
        "directivity_linear": round(directivity, 9),
        "directivity_dbi": round(10.0 * math.log10(directivity), 9),
        "resonant_length_mm": round(l_res, 9),
        "resonant_l_over_lambda": round(l_res / lam_mm, 12),
        "residual_x_at_resonance_ohm": round(x_res, 12),
        "note": (
            "R=正弦电流辐射功率积分（对假设分布精确；三角电流极限 "
            "20π²(l/λ)² 与半波 73.1Ω 双锚测试钉）；X=感应电动势法经典"
            "闭式（半波 j42.5 锚；远离谐振区为工程近似档，精度不及矩量"
            "法，如实注记）；方向性 l≤λ 主瓣 θ=90° 口径"),
        "source": _SOURCES["dipole"],
    }


# ─── 键 2：折合偶极两模阻抗 ──────────────────────────────────────────────────

@register_calculator(
    "folded_dipole_zin",
    "折合偶极输入阻抗（等线径，传输线法两模分解）：天线模=等效偶极阻抗 "
    "Z_d（dipole_emf_zin 路线复用）与传输线模=短路线 l/2 输入阻抗 "
    "2jZ_t·tan(kl/2)（Z_t=(η/π)·acosh(s/2a) 空气双线）在馈点并联——"
    "Z_in=4Z_d·Z_tl/(4Z_d+Z_tl)；谐振 l=λ/2 处 tan→∞ → Z_in=4Z_d（等粗 "
    "4×：73.1Ω→292Ω≈300Ω 教科书口径，线径/间距谐振点约去=恒等锚）；"
    "l=mλ 处 Z_in=0 短路边定性钉；step_up=Z_in/Z_d 复数输出。不等线径 "
    "Mushiake 步升比与包络等效半径修正不在本键口径（如实不做）",
    (("length_mm", "float mm 折合偶极总长 l（∈(0,λ)，与 Z_d 同域）"),
     ("f_ghz", "float GHz 工作频率（>0）"),
     ("wire_radius_mm", "float mm 导线半径 a（>0）"),
     ("spacing_mm", "float mm 两线中心距 s（>2·wire_radius_mm，线不重叠）")),
    required=("length_mm", "f_ghz", "wire_radius_mm", "spacing_mm"),
)
def folded_dipole_zin(length_mm: float, f_ghz: float, wire_radius_mm: float,
                      spacing_mm: float) -> dict[str, Any]:
    l_mm = _finite(length_mm, "length_mm")
    freq = _finite(f_ghz, "f_ghz")
    a_mm = _finite(wire_radius_mm, "wire_radius_mm")
    s_mm = _finite(spacing_mm, "spacing_mm")
    if freq <= 0.0:
        raise ValueError(f"folded_dipole_zin: f_ghz 必须 >0，得到 {f_ghz!r}")
    lam_mm = C_MM_GHZ / freq
    if l_mm <= 0.0 or l_mm >= lam_mm:
        raise ValueError(
            f"folded_dipole_zin: length_mm 须 ∈(0, λ)（λ={lam_mm:.6f}mm；"
            f"l=λ 全波馈点电流节点模型奇点，显式拒绝），得到 {length_mm!r}")
    if a_mm <= 0.0:
        raise ValueError(
            f"folded_dipole_zin: wire_radius_mm 必须 >0，得到 "
            f"{wire_radius_mm!r}")
    if s_mm <= 2.0 * a_mm:
        raise ValueError(
            f"folded_dipole_zin: spacing_mm 必须 >2·wire_radius_mm="
            f"{2.0 * a_mm:.6f}（两线不重叠），得到 {spacing_mm!r}")

    r_d, _j = _dipole_r_in(l_mm, freq)
    x_d = _dipole_x_in(l_mm, freq, a_mm)
    z_d = complex(r_d, x_d)
    z_t = _ETA0 / math.pi * math.acosh(s_mm / (2.0 * a_mm))
    kl_half = math.pi * l_mm / lam_mm
    z_tl = 2j * z_t * math.tan(kl_half)
    z_in = 4.0 * z_d * z_tl / (4.0 * z_d + z_tl)
    step_up = z_in / z_d
    return {
        "length_mm": l_mm,
        "f_ghz": freq,
        "wire_radius_mm": a_mm,
        "spacing_mm": s_mm,
        "lambda_mm": round(lam_mm, 9),
        "l_over_lambda": round(l_mm / lam_mm, 12),
        "z_d_r_ohm": round(r_d, 9),
        "z_d_x_ohm": round(x_d, 9),
        "z_t_ohm": round(z_t, 9),
        "z_tl_r_ohm": round(z_tl.real, 9),
        "z_tl_x_ohm": round(z_tl.imag, 9),
        "z_in_r_ohm": round(z_in.real, 9),
        "z_in_x_ohm": round(z_in.imag, 9),
        "step_up_re": round(step_up.real, 12),
        "step_up_im": round(step_up.imag, 12),
        "step_up_abs": round(abs(step_up), 12),
        "note": (
            "两模并联口径：1/Z_in=1/(4Z_d)+1/(2jZ_t·tan(kl/2))（测试侧"
            "恒等式回收）；谐振点 4× 与线径/间距无关（Z_tl→∞ 极限）；"
            "Z_d 线径取 a，包络等效半径修正不做（如实注记）；空气口径"),
        "source": _SOURCES["folded"],
    }


# ─── 键 3：小环输入阻抗分解 ──────────────────────────────────────────────────

@register_calculator(
    "small_loop_zin",
    "小环输入阻抗分解（电小圆环，N 匝）：辐射电阻 Rr=320π⁴·N²·(A/λ²)² "
    "≡ 20π²·N²·(C/λ)⁴ ≈ 31171·N²·(A/λ²)² 三式恒等（320π⁴=31170.9 测试"
    "钉）；趋肤损耗 R_L=Rs·N·b/a（Rs=√(πfμ/σ)，表面电流口径）；效率 "
    "Rr/(Rr+R_L)；电感 L=μ0·b·[ln(8b/a)−2]（Grover 单匝闭式，X=2πf·N²·L "
    "密绕 N² 近似如实注记）；Q=X/(Rr+R_L)。电小判据 C/λ≤0.3 守卫（超出"
    "电小假设显式拒绝）",
    (("radius_mm", "float mm 环半径 b（>wire_radius_mm）"),
     ("f_ghz", "float GHz 工作频率（>0）"),
     ("wire_radius_mm", "float mm 导线半径 a（0<a<radius_mm）"),
     ("turns_n", "float 匝数 N（≥1；N² 标度口径，非整数仅作标度插值）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（>0；Cu=5.8e7）")),
    required=("radius_mm", "f_ghz", "wire_radius_mm", "turns_n",
              "conductivity_s_per_m"),
)
def small_loop_zin(radius_mm: float, f_ghz: float, wire_radius_mm: float,
                   turns_n: float, conductivity_s_per_m: float
                   ) -> dict[str, Any]:
    b_mm = _finite(radius_mm, "radius_mm")
    freq = _finite(f_ghz, "f_ghz")
    a_mm = _finite(wire_radius_mm, "wire_radius_mm")
    turns = _finite(turns_n, "turns_n")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    if freq <= 0.0:
        raise ValueError(f"small_loop_zin: f_ghz 必须 >0，得到 {f_ghz!r}")
    if a_mm <= 0.0 or a_mm >= b_mm:
        raise ValueError(
            f"small_loop_zin: 须 0 < wire_radius_mm < radius_mm，得到 a="
            f"{wire_radius_mm!r}, b={radius_mm!r}")
    if turns < 1.0:
        raise ValueError(
            f"small_loop_zin: turns_n 必须 ≥1，得到 {turns_n!r}")
    if sigma <= 0.0:
        raise ValueError(
            f"small_loop_zin: conductivity_s_per_m 必须 >0，得到 "
            f"{conductivity_s_per_m!r}")

    lam_mm = C_MM_GHZ / freq
    circ_mm = 2.0 * math.pi * b_mm
    c_over_lam = circ_mm / lam_mm
    if c_over_lam > 0.3:
        raise ValueError(
            f"small_loop_zin: 电小判据 C/λ={c_over_lam:.4f} >0.3（超出小环"
            f"假设域，显式拒绝），周长 {circ_mm:.4f}mm @ {freq!r}GHz")

    area_m2 = math.pi * (b_mm * 1e-3) ** 2
    lam_m = lam_mm * 1e-3
    r_r = 320.0 * math.pi ** 4 * turns * turns * (area_m2 / lam_m ** 2) ** 2
    # 三式恒等（20π²N²(C/λ)⁴ 精确恒等式；31171 为教科书圆整常数，相对
    # 偏差 ~3e-6 属常数圆整非公式差，如实注记）
    r_r_form2 = (20.0 * math.pi ** 2 * turns * turns
                 * c_over_lam ** 4)
    r_r_form3 = 31171.0 * turns * turns * (area_m2 / lam_m ** 2) ** 2
    ident_rel = abs(r_r - r_r_form2) / r_r
    rs = math.sqrt(math.pi * freq * 1e9 * _MU0 / sigma)
    r_loss = rs * turns * b_mm / a_mm
    efficiency = r_r / (r_r + r_loss)
    l_loop_h = _MU0 * turns * turns * (b_mm * 1e-3) * (
        math.log(8.0 * b_mm / a_mm) - 2.0)
    x_in = 2.0 * math.pi * freq * 1e9 * l_loop_h
    q_loop = x_in / (r_r + r_loss)
    return {
        "radius_mm": b_mm,
        "f_ghz": freq,
        "wire_radius_mm": a_mm,
        "turns_n": turns,
        "conductivity_s_per_m": sigma,
        "lambda_mm": round(lam_mm, 9),
        "circumference_over_lambda": round(c_over_lam, 12),
        "r_radiation_ohm": round(r_r, 12),
        "r_radiation_form2_ohm": round(r_r_form2, 12),
        "r_radiation_31171_ohm": round(r_r_form3, 12),
        "identity_rel_dev": round(ident_rel, 15),
        "r_loss_ohm": round(r_loss, 12),
        "efficiency": round(efficiency, 12),
        "l_loop_nh": round(l_loop_h * 1e9, 9),
        "x_in_ohm": round(x_in, 9),
        "q": round(q_loop, 9),
        "note": (
            "电小圆环口径（C/λ≤0.3）；三式恒等 identity_rel_dev 应为机器"
            "精度级；X 密绕 N² 近似（匝间互感修正不做，如实注记）；R_L "
            "为高频趋肤表面电流口径，不覆盖低频直流过渡区"),
        "source": _SOURCES["loop"],
    }
