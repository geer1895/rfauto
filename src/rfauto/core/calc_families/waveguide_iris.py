"""矩形波导薄膜片/谐振窗匹配闭式族（aurora72 A7-B 席域 1，任务书候补
"矩形波导膜片/窗匹配"；#222 triple-grep 证据 2026-10-11 实测；
W3-CORE8 席 TE10 λg/λc/β 抽键原位扩展 2026-10-14）。

四键：wg_iris_susceptance（对称感性/容性薄膜片归一化电纳正反解双向）/
wg_resonant_window（感+容组合谐振窗：总电纳=0 共振条件，给定感性开口解
容性开口或双开口验证）/ wg_iris_match（单膜片匹配：负载 Γ → 膜片位置与
开口双分支闭式解+ABCD 回代残差验证）/ waveguide_lambda_g（TE10 传播
参数抽键：λg/λc/β 闭式独立键——R7-PREP G16 可选件，内部复用 _frequency
单源零公式复制）。

与既有面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- core/rwg_mmt.py=**数值模匹配**工具（H 面阶梯/膜片=阶梯构件级联的广义
  散射矩阵数值解，模块先例显式不进注册表）——本族=**工程薄膜片电纳闭
  式**（薄膜片近似档），数值模匹配是真机窗仲裁路径，语义层级不同不并入。
- rwg_tables.py=EIA 商品波导尺寸表；waveguide_closed_form.py=圆波导/腔
  谱族；hybrid_junction.py waveguide_tee_s_matrix=E/T 面三口结 S 矩阵；
  stub_tuner=通用传输线支节调配（电长度输出）——本族匹配键=波导 λg 口
  径+膜片开口 mm 反解（几何尺寸输出），拓扑代数同族但参数/输出面不同，
  不并入。
- waveguide_lambda_g（抽键）与既有 λg 面分层：slot_array._lambda_g_mm=
  缝隙阵内部 λg（λ0/2a 代数同构形态，锚树测试互证非 import 复用——
  G16 锚树已钉）、microstrip_lambda_g=准 TEM 微带 λg（εeff 色散口径）
  ——波导 TE10 主模/缝隙阵内嵌/准 TEM 线三层不撞；rwg_tables=EIA 尺寸
  档、rwg_mmt=数值模基，均无独立 λg 传播参数键面（R7-PREP 实测"当前
  无同名注册键"）。
- fab_export 的 window=制造图窗语境（误命中剔除）。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_a7b_iris_guanella.py 与 tests/unit/test_aurora_d_core8.py）
--------------------------------------------------------
- TE10 主模引导波长：λ0=c/f、fc=c/(2a)、λg=λ0/√(1−(fc/f)²)；f≤fc 显式
  拒绝（截止以下无传播，膜片电纳语义失效）。
- 对称感性薄膜片（宽边 a 内开口 d）：B/Y0 = −(λg/a)·cot²(πd/(2a))。
  极限自检：d→a（无膜片）cot(π/2)=0 → B→0；d→0（全闭）B→−∞（感性极
  大）——方向与符号自洽。
- 对称容性薄膜片（窄边 b 内开口 d）：B/Y0 = (4b/λ0)·ln csc(πd/(2b))，
  λ0=自由空间波长（容性膜片高次凋落模口径，与感性式 λg 不同源，两式
  λ 依赖不同是通行工程式的真实不对称，如实照录）。
  极限自检：d→b → csc(π/2)=1 → B→0；d→0 → B→+∞（容性极大）。
- 两式为**薄膜片（t→0）工程近似档**（Marcuvitz Waveguide Handbook 闭式
  的首阶形，经 Rizzi《Microwave Engineering: Passive Circuits》ch.4 二
  级文献通行式转引——原文页码未逐位复读，如实登记；厚膜片/有限厚度修
  正项不在本族口径）。
- 谐振窗：感性+容性膜片组合总电纳 B/Y0=0（f0 处全传输），给定感性开口
  d_i 反解容性开口 d_c：ln csc(πd_c/2b) = (λg·b)/(4aλ0)·cot²(πd_i/2a)，
  cot²≥0 → 右端≥0 → sin(πd_c/2b)=exp(−·)∈(0,1] 恒可解；指数下溢
  （d_c→0，感性开口过小所需容性电纳超出闭式可达）显式拒绝。
- 单膜片匹配（并联电纳调配的波导实现）：y_L=(1−Γ)/(1+Γ) 归一负载导纳，
  沿线 t=tan(βℓ) 变换 y(ℓ)=(y_L+jt)/(1+jy_L·t)，取 g_in=1 得二次方程
  (b²+g²−g)t² − 2b·t + (1−g) = 0（判别式 g[b²+(1−g)²]≥0 恒两实根，g>0
  对无源负载恒成立）；所需膜片电纳 b_i=−Im{y(ℓ)}，b_i<0 → 感性膜片开
  口反解 d=(2a/π)·arctan√(−a/(b_iλg))、b_i>0 → 容性反解
  d=(2b/π)·arcsin exp(−b_iλ0/(4b))。双分支如实并列，感性分支标工程优
  先（功率容量/易实现惯例）。|Γ|≥1 非物理显式拒绝。

数值锚（#118 独立路线）：极限恒等（开口=全波导 → 电纳 0）；匹配解
ABCD 回代 |Γin|≈0（解的代数恒等式，构造级残差）；谐振窗回代 |B总|≈0；
λg 对 fc 标度恒等式（测试侧独立重解）。测试侧另做导纳圆代数独立重解
（单支节调配闭式的教科书推导路线，与实现侧同式异推——推导即锚）。

守卫：a_mm/b_mm>0 且 b_mm≤a_mm（标准矩形波导口径）；f_ghz>0 且>fc10；
d_mm∈(0,a)（感性）/∈(0,b)（容性）；iris_type 白名单；d_mm 与 b_norm 恰
给其一（正解/反解互斥，双给显式拒绝）；gamma_mag∈[0,1)。bool 入参走
_float 自然拒收路径如实注记（df7+⑯ 同 gysel 先例口径）。

接口：纯函数零 IO；math/cmath 为主；全部返回 JSON 可序列化结构（浮点/
字符串/bool/None；数值 0.0 合法，判缺失一律 is not None，禁 ``or 缺
省``，#364④）。无 ``__all__``（公开 API 快照口径，mask_spec 先例反查）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_C0_M_S = 299792458.0
_IRIS_TYPES = ("inductive", "capacitive")


def _guide_dims(a_mm: float, b_mm: float, tag: str) -> tuple[float, float]:
    """波导尺寸收敛与守卫（a>0、b>0、b≤a 标准口径）。"""
    a = _finite(a_mm, f"{tag}.a_mm")
    b = _finite(b_mm, f"{tag}.b_mm")
    if a <= 0.0:
        raise ValueError(f"{tag}: a_mm 必须 >0，得到 {a_mm!r}")
    if b <= 0.0:
        raise ValueError(f"{tag}: b_mm 必须 >0，得到 {b_mm!r}")
    if b > a:
        raise ValueError(
            f"{tag}: b_mm 必须 ≤a_mm（标准矩形波导口径），得到 a={a!r}, "
            f"b={b!r}")
    return a, b


def _frequency(a_mm: float, f_ghz: float, tag: str) -> tuple[float, float,
                                                              float]:
    """频率收敛与 TE10 传播守卫；返回 (λ0_mm, λg_mm, fc10_ghz)。

    λg/λc/β 抽键单源（W3-CORE8 waveguide_lambda_g 内部复用本 helper，
    零公式复制；返回元组 2→3 扩的三个仓内消费点同笔更新）。
    """
    f = _finite(f_ghz, f"{tag}.f_ghz")
    if f <= 0.0:
        raise ValueError(f"{tag}: f_ghz 必须 >0，得到 {f_ghz!r}")
    a_m = a_mm * 1e-3
    fc10_ghz = _C0_M_S / (2.0 * a_m) / 1e9
    if f <= fc10_ghz:
        raise ValueError(
            f"{tag}: f_ghz={f!r} 不高于 TE10 截止 {fc10_ghz:.6f} GHz"
            "（截止以下无传播，膜片电纳语义失效）")
    lam0_mm = _C0_M_S / (f * 1e9) * 1e3
    lam_g_mm = lam0_mm / math.sqrt(1.0 - (fc10_ghz / f) ** 2)
    return lam0_mm, lam_g_mm, fc10_ghz


def _b_inductive(d_over_a: float, lam_g_over_a: float) -> float:
    """对称感性薄膜片归一化电纳：−(λg/a)·cot²(πd/(2a))。"""
    return -lam_g_over_a / math.tan(math.pi * d_over_a / 2.0) ** 2


def _b_capacitive(d_over_b: float, b_over_lam0: float) -> float:
    """对称容性薄膜片归一化电纳：(4b/λ0)·ln csc(πd/(2b))。"""
    return 4.0 * b_over_lam0 * math.log(
        1.0 / math.sin(math.pi * d_over_b / 2.0))


@register_calculator(
    "wg_iris_susceptance",
    "波导感性/容性膜片电纳：TE10 矩形波导对称薄膜片（感性宽边开口/"
    "容性窄边开口）归一化电纳闭式 B/Y0——感性 −(λg/a)cot²(πd/2a)、容性 "
    "(4b/λ0)ln csc(πd/2b)（薄膜片工程近似档，λg/λ0 依赖差异如实照录）；"
    "正反解双向（d_mm→电纳 / 电纳→d_mm 恰给其一）；f≤TE10 截止显式拒绝",
    (("a_mm", "float mm 波导宽边（TE10 截止= c/2a；>0）"),
     ("b_mm", "float mm 波导窄边（0<b≤a）"),
     ("f_ghz", "float GHz 工作频率（>TE10 截止）"),
     ("iris_type", "str 膜片类型 inductive|capacitive（缺省 inductive）"),
     ("d_mm", "float mm 膜片开口（正解方向，与 b_norm 恰给其一）"),
     ("b_norm", "float B/Y0 归一化电纳（反解方向，与 d_mm 恰给其一；感"
                "性<0/容性>0）")),
    required=("a_mm", "b_mm", "f_ghz"),
)
def wg_iris_susceptance(a_mm: float, b_mm: float, f_ghz: float,
                        iris_type: str = "inductive",
                        d_mm: float | None = None,
                        b_norm: float | None = None) -> dict[str, Any]:
    tag = "wg_iris_susceptance"
    a, b = _guide_dims(a_mm, b_mm, tag)
    lam0_mm, lam_g_mm, _fc10 = _frequency(a, f_ghz, tag)
    if iris_type not in _IRIS_TYPES:
        raise ValueError(
            f"{tag}: iris_type 必须在 {_IRIS_TYPES}，得到 {iris_type!r}")
    if (d_mm is None) == (b_norm is None):
        raise ValueError(
            f"{tag}: d_mm 与 b_norm 必须恰给其一（正解/反解互斥；双给或缺"
            "给均显式拒绝）")
    if iris_type == "inductive":
        lim_mm = a
        b_over_lam_g = lam_g_mm / a
    else:
        lim_mm = b
        b_over_lam_g = b / lam0_mm  # 容式 λ0 口径的等效标度
    if d_mm is not None:
        d = _finite(d_mm, f"{tag}.d_mm")
        if not 0.0 < d < lim_mm:
            raise ValueError(
                f"{tag}: d_mm 必须在 (0, {lim_mm}) 开区间（开口=全边即无"
                f"膜片），得到 {d_mm!r}")
        d_over = d / lim_mm
        b_val = (_b_inductive(d_over, b_over_lam_g) if iris_type == "inductive"
                 else _b_capacitive(d_over, b_over_lam_g))
        return {
            "a_mm": a, "b_mm": b, "f_ghz": _finite(f_ghz, f"{tag}.f_ghz"),
            "lambda_0_mm": round(lam0_mm, 12),
            "lambda_g_mm": round(lam_g_mm, 12),
            "iris_type": iris_type,
            "route": "aperture_to_susceptance",
            "d_mm": round(d, 12),
            "b_norm": round(b_val, 12),
            "x_norm": round(-1.0 / b_val, 12),
            "note": ("薄膜片（t→0）工程近似档：感性 B/Y0=−(λg/a)cot²(πd/"
                     "2a)、容性 B/Y0=(4b/λ0)ln csc(πd/2b)——容式用自由空"
                     "间波长 λ0（高次凋落模口径），与感式 λg 不同源，通"
                     "行工程式的真实不对称如实照录；厚膜片修正不在口径；"
                     "x_norm=−1/b 为等效归一化电抗展示面"),
            "source": (
                "Marcuvitz Waveguide Handbook 薄膜片闭式首阶形；Rizzi "
                "Microwave Engineering: Passive Circuits ch.4 通行式转引"),
        }
    b_target = _finite(b_norm, f"{tag}.b_norm")
    if iris_type == "inductive":
        if b_target >= 0.0:
            raise ValueError(
                f"{tag}: 感性膜片电纳必须 <0（cot²>0），得到 {b_norm!r}")
        # cot²x=−b·a/λg → tan x=√(−λg/(a·b))（b<0 分母负号消化）
        arg = -lam_g_mm / (a * b_target)
        d = (2.0 * a / math.pi) * math.atan(math.sqrt(arg))
    else:
        if b_target <= 0.0:
            raise ValueError(
                f"{tag}: 容性膜片电纳必须 >0（ln csc>0），得到 {b_norm!r}")
        sin_x = math.exp(-b_target * lam0_mm / (4.0 * b))
        if not 0.0 < sin_x <= 1.0:
            raise ValueError(
                f"{tag}: 容性反解不可达（所需电纳 {b_target!r} 使开口趋零"
                "——超出薄膜片闭式可达域），显式拒绝")
        d = (2.0 * b / math.pi) * math.asin(sin_x)
    d_over = d / lim_mm
    b_back = (_b_inductive(d_over, b_over_lam_g) if iris_type == "inductive"
              else _b_capacitive(d_over, b_over_lam_g))
    return {
        "a_mm": a, "b_mm": b, "f_ghz": _finite(f_ghz, f"{tag}.f_ghz"),
        "lambda_0_mm": round(lam0_mm, 12),
        "lambda_g_mm": round(lam_g_mm, 12),
        "iris_type": iris_type,
        "route": "susceptance_to_aperture",
        "d_mm": round(d, 12),
        "b_norm": round(b_target, 12),
        "b_norm_backsub": round(b_back, 15),
        "x_norm": round(-1.0 / b_target, 12),
        "note": ("反解=闭式代数逆（感性 arctan√(−λg/(a·b))、容性 "
                 "arcsin exp(−bλ0/4b)），b_norm_backsub=开口回代电纳（回"
                 "代残差≈机器精度，解的代数恒等式）；其余口径同正解档"),
        "source": (
            "Marcuvitz Waveguide Handbook 薄膜片闭式首阶形；Rizzi "
            "Microwave Engineering: Passive Circuits ch.4 通行式转引"),
    }


@register_calculator(
    "wg_resonant_window",
    "波导谐振窗设计：感性+容性薄膜片组合谐振窗（总电纳=0，f0 全传输——"
    "真空密封窗/波导滤波器谐振元），给定感性开口 d_ind 反解容性开口 "
    "d_cap，或双开口给齐验证残余电纳；指数下溢（感性开口过小容性解不可"
    "达）显式拒绝；f0 回代 |B总|≈0 构造级残差",
    (("a_mm", "float mm 波导宽边（>0）"),
     ("b_mm", "float mm 波导窄边（0<b≤a）"),
     ("f_ghz", "float GHz 谐振频率（>TE10 截止）"),
     ("d_ind_mm", "float mm 感性膜片开口（0<d<a）"),
     ("d_cap_mm", "float mm 容性膜片开口（给齐=验证档；缺省=反解档）")),
    required=("a_mm", "b_mm", "f_ghz", "d_ind_mm"),
)
def wg_resonant_window(a_mm: float, b_mm: float, f_ghz: float,
                       d_ind_mm: float, d_cap_mm: float | None = None
                       ) -> dict[str, Any]:
    tag = "wg_resonant_window"
    a, b = _guide_dims(a_mm, b_mm, tag)
    lam0_mm, lam_g_mm, _fc10 = _frequency(a, f_ghz, tag)
    d_i = _finite(d_ind_mm, f"{tag}.d_ind_mm")
    if not 0.0 < d_i < a:
        raise ValueError(
            f"{tag}: d_ind_mm 必须在 (0, {a}) 开区间，得到 {d_ind_mm!r}")
    b_ind = _b_inductive(d_i / a, lam_g_mm / a)
    if d_cap_mm is None:
        route = "solve_capacitive"
        b_cap_req = -b_ind
        sin_x = math.exp(-b_cap_req * lam0_mm / (4.0 * b))
        if not 0.0 < sin_x <= 1.0:
            raise ValueError(
                f"{tag}: 容性开口反解不可达（感性开口 {d_ind_mm!r} 过小，"
                "所需容性电纳超出薄膜片闭式可达域——指数下溢），显式拒绝")
        d_c = (2.0 * b / math.pi) * math.asin(sin_x)
    else:
        route = "verify"
        d_c = _finite(d_cap_mm, f"{tag}.d_cap_mm")
        if not 0.0 < d_c < b:
            raise ValueError(
                f"{tag}: d_cap_mm 必须在 (0, {b}) 开区间，得到 {d_cap_mm!r}")
    b_cap = _b_capacitive(d_c / b, b / lam0_mm)
    b_total = b_ind + b_cap
    return {
        "a_mm": a, "b_mm": b, "f_ghz": _finite(f_ghz, f"{tag}.f_ghz"),
        "lambda_0_mm": round(lam0_mm, 12),
        "lambda_g_mm": round(lam_g_mm, 12),
        "route": route,
        "d_ind_mm": round(d_i, 12),
        "d_cap_mm": round(d_c, 12),
        "b_ind_norm": round(b_ind, 12),
        "b_cap_norm": round(b_cap, 12),
        "b_total_norm": round(b_total, 15),
        "resonant": abs(b_total) <= 1e-9,
        "note": ("谐振条件 B_ind+B_cap=0（f0 处全传输）：反解档回代 |B总|"
                 "≈机器精度（构造级残差）；验证档如实给残余电纳不凑零；"
                 "感性开口过小时所需容性电纳指数下溢→显式拒绝（闭式可达"
                 "域守卫）；薄膜片工程近似档，厚度修正不在口径"),
        "source": (
            "Marcuvitz Waveguide Handbook 谐振窗（感性/容性组合）口径；"
            "Rizzi Microwave Engineering: Passive Circuits ch.4 通行式转引"),
    }


@register_calculator(
    "wg_iris_match",
    "波导单膜片匹配：负载反射 Γ → 归一导纳 y_L 沿线变换（TE10 λg 口径）"
    "g_in=1 二次方程双分支闭式解——每支给位置 ℓ、所需膜片电纳 b_i 与开口"
    "尺寸反解（感性/容性分支并列，感性标工程优先）；ABCD 回代 |Γin| 构造"
    "级残差；|Γ|≥1 非物理显式拒绝",
    (("a_mm", "float mm 波导宽边（>0）"),
     ("b_mm", "float mm 波导窄边（0<b≤a）"),
     ("f_ghz", "float GHz 工作频率（>TE10 截止）"),
     ("gamma_mag", "float 负载反射幅度（0≤|Γ|<1；=0 已匹配如实报告）"),
     ("gamma_phase_deg", "float 度 负载反射相位（−180..180）")),
    required=("a_mm", "b_mm", "f_ghz", "gamma_mag", "gamma_phase_deg"),
)
def wg_iris_match(a_mm: float, b_mm: float, f_ghz: float, gamma_mag: float,
                  gamma_phase_deg: float) -> dict[str, Any]:
    tag = "wg_iris_match"
    a, b = _guide_dims(a_mm, b_mm, tag)
    lam0_mm, lam_g_mm, _fc10 = _frequency(a, f_ghz, tag)
    g_mag = _finite(gamma_mag, f"{tag}.gamma_mag")
    g_ph = _finite(gamma_phase_deg, f"{tag}.gamma_phase_deg")
    if not 0.0 <= g_mag < 1.0:
        raise ValueError(
            f"{tag}: gamma_mag 必须 ∈[0,1)（无源负载；≥1 非物理），得到 "
            f"{gamma_mag!r}")
    if not -180.0 <= g_ph <= 180.0:
        raise ValueError(
            f"{tag}: gamma_phase_deg 必须 ∈[−180,180]，得到 "
            f"{gamma_phase_deg!r}")
    gamma = g_mag * cmath.exp(1j * math.radians(g_ph))
    if abs(gamma) <= 1e-12:
        return {
            "a_mm": a, "b_mm": b, "f_ghz": _finite(f_ghz, f"{tag}.f_ghz"),
            "lambda_0_mm": round(lam0_mm, 12),
            "lambda_g_mm": round(lam_g_mm, 12),
            "gamma_load_mag": g_mag,
            "gamma_load_phase_deg": g_ph,
            "y_load_norm_g": 1.0,
            "y_load_norm_b": 0.0,
            "branches": [{
                "branch": 1, "tan_beta_l": 0.0, "l_mm": 0.0,
                "l_over_lambda_g": 0.0, "b_iris_norm": 0.0,
                "iris_type": "none", "d_mm": 0.0,
                "gamma_in_residual": 0.0,
            }],
            "preferred_branch": 1,
            "note": ("|Γ|≈0 负载已匹配（参考面即匹配面），无需膜片——如实"
                     "报告 none 分支不虚构调配解；口径同双分支档"),
            "source": "负载已匹配退化路径（无膜片解）",
        }
    y_l = (1.0 - gamma) / (1.0 + gamma)
    g_l = y_l.real
    b_l = y_l.imag
    beta = 2.0 * math.pi / lam_g_mm

    def _solve_t(a_c: float, b_c: float, c_c: float) -> list[float]:
        """A t² − 2b t + C = 0 的实根列（A=0 退化线性支；判别式恒≥0）。"""
        if abs(a_c) < 1e-15:
            if abs(b_c) < 1e-15:
                raise ValueError(
                    f"{tag}: 匹配方程退化（A=b²+g²−g=0 且 b_L=0，g_L=1）"
                    "——负载已匹配，无膜片解（显式路径保护）")
            return [c_c / (2.0 * b_c)]
        disc = b_l * b_l + (1.0 - g_l) ** 2
        rad = g_l * disc
        sq = math.sqrt(max(rad, 0.0))
        return [(b_l + sq) / a_c, (b_l - sq) / a_c]

    a_c = b_l * b_l + g_l * g_l - g_l
    t_roots = _solve_t(a_c, b_l, 1.0 - g_l)
    branches: list[dict[str, Any]] = []
    for idx, t in enumerate(t_roots, start=1):
        bl = math.atan(t)
        if bl < 0.0:
            bl += math.pi  # ℓ ∈ [0, λg/2)
        ell_mm = bl / beta
        y_in = (y_l + 1j * t) / (1.0 + 1j * y_l * t)
        b_i = -y_in.imag  # 所需膜片电纳（并联补偿）
        if b_i < 0.0:
            i_type = "inductive"
            d_ap = (2.0 * a / math.pi) * math.atan(
                math.sqrt(-a / (b_i * lam_g_mm)))
        else:
            i_type = "capacitive"
            sin_x = math.exp(-b_i * lam0_mm / (4.0 * b))
            if not 0.0 < sin_x <= 1.0:
                raise ValueError(
                    f"{tag}: 分支 {idx} 容性开口反解不可达（所需电纳超出"
                    "闭式可达域），显式拒绝")
            d_ap = (2.0 * b / math.pi) * math.asin(sin_x)
        y_tot = y_in + 1j * b_i  # 并联电纳补偿虚部（b_i=−Im y_in）
        gamma_in = (1.0 - y_tot) / (1.0 + y_tot)
        branches.append({
            "branch": idx,
            "tan_beta_l": round(t, 15),
            "l_mm": round(ell_mm, 12),
            "l_over_lambda_g": round(ell_mm / lam_g_mm, 15),
            "b_iris_norm": round(b_i, 12),
            "iris_type": i_type,
            "d_mm": round(d_ap, 12),
            "gamma_in_residual": round(abs(gamma_in), 18),
        })
    branches.sort(key=lambda x: (x["iris_type"] != "inductive",
                                 x["branch"]))
    return {
        "a_mm": a, "b_mm": b, "f_ghz": _finite(f_ghz, f"{tag}.f_ghz"),
        "lambda_0_mm": round(lam0_mm, 12),
        "lambda_g_mm": round(lam_g_mm, 12),
        "gamma_load_mag": g_mag,
        "gamma_load_phase_deg": g_ph,
        "y_load_norm_g": round(g_l, 12),
        "y_load_norm_b": round(b_l, 12),
        "branches": branches,
        "preferred_branch": branches[0]["branch"],
        "note": ("单并联电纳调配的波导实现（TE10 λg 口径）：y(ℓ)=("
                 "y_L+jtanβℓ)/(1+jy_L·tanβℓ)，g_in=1 二次方程恒两实根（判"
                 "别式 g[b²+(1−g)²]≥0 对无源负载恒成立）；b_i<0→感性膜片/"
                 "b_i>0→容性膜片开口反解；感性分支标工程优先（功率容量/易"
                 "实现惯例）；gamma_in_residual=ABCD 回代构造级残差（解的"
                 "代数恒等式≈机器精度）；归一化导纳口径参考面无关（膜片电"
                 "纳归一 to TE10 波导等效 Y0）；与 stub_tuner 的边界=波导"
                 "λg+膜片开口 mm 输出面（电长度输出不并入）"),
        "source": (
            "单支节调配导纳圆代数（Pozar Microwave Engineering ch.5 同构"
            "推导在波导 λg 口径的膜片化）；薄膜片电纳式同 wg_iris_"
            "susceptance（Marcuvitz/Rizzi 转引）"),
    }


@register_calculator(
    "waveguide_lambda_g",
    "矩形波导 TE10 传播参数抽键：λ0=c/f、λc=2a、fc=c/2a、λg=λ0/√(1−"
    "(fc/f)²)、β=2π/λg（rad/m 与 rad/mm）+ 相/群速因子 λg/λ0 与 λ0/λg；"
    "f≤fc 截止显式拒绝；内部复用本族 _frequency 单源（wg_iris_*/"
    "wg_resonant_window 同源，零公式复制）；slot_array 内嵌 λg（λ0/2a "
    "同构形态）与 microstrip_lambda_g（准 TEM）分层不撞",
    (("a_mm", "float mm 波导宽边（TE10 截止=c/2a；>0）"),
     ("f_ghz", "float GHz 工作频率（>TE10 截止，截止下显式拒绝）"),
     ("b_mm", "float mm 波导窄边（>0 且 ≤a_mm，可选——TE10 λg 与 b 无"
      "关，给出即校验标准口径 b≤a）")),
    required=("a_mm", "f_ghz"),
)
def waveguide_lambda_g(
    a_mm: float,
    f_ghz: float,
    b_mm: float | None = None,
) -> dict[str, Any]:
    """矩形波导 TE10 λg/λc/β 闭式（_frequency 单源复用，零公式复制）。"""
    a = _finite(a_mm, "waveguide_lambda_g.a_mm")
    b: float | None = None
    if a <= 0.0:
        raise ValueError(
            f"waveguide_lambda_g: a_mm 必须 >0，得到 {a_mm!r}")
    if b_mm is not None:
        b_chk = _finite(b_mm, "waveguide_lambda_g.b_mm")
        if b_chk <= 0.0:
            raise ValueError(
                f"waveguide_lambda_g: b_mm 必须 >0，得到 {b_mm!r}")
        if b_chk > a:
            raise ValueError(
                f"waveguide_lambda_g: b_mm 必须 ≤a_mm（标准矩形波导口径），"
                f"得到 a={a!r}, b={b_chk!r}")
        b = b_chk
    lam0_mm, lam_g_mm, fc10_ghz = _frequency(a, f_ghz,
                                             "waveguide_lambda_g")
    beta_rad_per_mm = 2.0 * math.pi / lam_g_mm
    lambda_c_mm = 2.0 * a
    f_over_fc = f_ghz / fc10_ghz
    return {
        "a_mm": a,
        "b_mm": b,
        "f_ghz": f_ghz,
        "fc10_ghz": fc10_ghz,
        "f_over_fc": f_over_fc,
        "lambda_0_mm": lam0_mm,
        "lambda_c_mm": lambda_c_mm,
        "lambda_g_mm": lam_g_mm,
        "beta_rad_per_mm": beta_rad_per_mm,
        "beta_rad_per_m": beta_rad_per_mm * 1e3,
        "vp_over_c": lam_g_mm / lam0_mm,
        "vg_over_c": lam0_mm / lam_g_mm,
        "note": (
            "TE10 主模传播参数：λc=2a、fc=c/(2a)、λg=λ0/√(1−(fc/f)²)、"
            "β=2π/λg（色散口径 vp/c=λg/λ0>1、vg/c=λ0/λg<1 恒成立）；"
            "内部复用本族 _frequency 单源（wg_iris_* 膜片键同源，零公式"
            "复制）；f≤fc 截止显式拒绝（凋落模无传播语义）；b_mm 可选"
            "（TE10 λg 与 b 无关，给出即校验 b≤a 标准口径）；slot_array "
            "缝隙阵内嵌 λg 与 microstrip_lambda_g 准 TEM 口径语义分层"
            "不撞"),
        "source": (
            "TE10 传播参数闭式（Pozar Microwave Engineering §3.x 矩形波"
            "导主模口径，章节级转引，式号不落键面）；抽键=R7-PREP G16 "
            "可选件（runs/aurora_c/batch_b_wave3_specs/INDEX.md）；单源"
            "=本族 _frequency helper；实现前独立复算 runs/aurora_d/"
            "_core8_verify_derivation.py（fc/f、λ0/2a、k_z 三形态互证 "
            "rel≤5.1e-15），锚树 tests/unit/test_aurora_d_core8.py"),
    }
