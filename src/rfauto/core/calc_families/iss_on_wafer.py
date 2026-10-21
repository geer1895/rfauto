"""在片 ISS 校准件族（架构批 W5-S18 席域，R2_core_tier3 边际池立项）。

两键：iss_standard_response（在片共面 ISS 标准件开路/短路/负载/直通的
寄生模型闭式响应——开路边缘电容频率多项式、短路串联电感多项式、负载
薄膜电阻+寄生 LC、直通匹配线损耗时延）/ iss_oneport_cal_extract（一端口
三项误差模型提取+Γ 回收——任意**非理想**标准件定义下的 Ed/Es/Er 闭式
线性反解，理想标准定义档与 trl_solt 同式逐位互证）。

边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- 全仓 grep（ISS/impedance standard substrate/在片/iss_standard）src/tests
  零实现零键（substring 误中=array_synth "baylISS"/注释语，行级剔除）；
  本族为该域首批注册键。
- core/cal_kit_verify.py（W3-S10 席）= **同轴机械 SOLT 件**响应核验+
  纹波 verification——语境=连接器/offset 空气线；本族=**共面在片件**
  （探针台 ISS 衬底语境：边缘电容频率多项式/薄膜负载/共面直通），二者
  频率依赖开路电容的高阶项恰在其预声明"诚实边界"（"多参数 C0,C1,C2
  拟合面不在本域"）之外——边界互补互指，open 一阶项同式恒等互证。
- core/trl_solt.py = 校准件**使用链**（理想标准定义 Γ=±1/0 下的二端口
  八项/一端口三项提取+TH-2 消费形态）；本族 iss_oneport_cal_extract=
  **任意非理想标准定义**的一端口三项提取（ISS 寄生定义直入），理想档
  退化回 trl_solt 同式（同仓双源锚，见键 2 docstring）。
- core/deembed.py = OpenShort 去嵌**泛用件**（2 端口夹具链，skrf 面）；
  本族不做去嵌应用面（R2 边际池"探针垫去嵌"半边由泛用件覆盖，如实不
  重复实现）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **开路**（共面探针开路端，边缘电容主导）：C(f) = c₀ + c₁·f + c₂·f² +
  c₃·f³（fF，f 以 GHz 代入）——校准套件定义文件的频率多项式惯例格式
  （Keysight 机械/在片套件定义 open 电容 C0..C3 格式，二级转引；厂商具
  体系数值无原文实取如实不入，#122/#300）。Γ = (1 − jωC·Z0)/(1 + jωC·
  Z0)——纯并联容抗反射（与 cal_kit_standard_response 的 open 一阶项
  同式，C(f) 逐频点代入；理想 C=0 → Γ=+1 逐位）。
- **短路**（共面短路，电流路径磁储能）：L(f) = l₀ + l₁·f + l₂·f² +
  l₃·f³（pH，同多项式惯例格式）；Z = jωL → Γ = (Z − Z0)/(Z + Z0)
  （理想 L=0 → Γ=−1 逐位；L>0 → 相位自 180° 回旋 −2·atan(ωL/Z0)，
  |Γ|=1 无耗档——与键内 note 同口径，W7-S25 P3-3 措辞统一）。
- **负载**（薄膜 50Ω 电阻，串联寄生电感+并联寄生电容）：Z = jωL_l +
  R/(1 + jωR·C_l) → Γ = (Z − Z0)/(Z + Z0)（理想 R=Z0/L=C=0 → Γ=0
  逐位；寄生 ≥0 无源 ⇒ |Γ|≤1）。
- **直通**（共面匹配线段）：S21 = exp(−(α_np + jβ)·l)，β = 2πf√εeff/c、
  α_np = IL/(20·log10 e)（精确 dB→Np 换算，IL = loss_db_mm·l_mm 平损耗
  档）；时延
  τ = l·√εeff/c（ns）；|S21| = 10^(−IL/20) 恒等式；理想 l=0 → S21=1。
- **一端口三项误差模型**（iss_oneport_cal_extract，Pozar VNA 校准章同
  款）：Γ_meas = Ed + Er·Γ/(1 − Es·Γ)。给定三个已知标准定义 Γ_i 与原
  始测量 m_i，恒等变形 m_i = Ed + Er′·Γ_i + Es·(m_i·Γ_i)（Er′ = Er −
  Ed·Es）→ 未知量 (Ed, Er′, Es) 的 3×3 线性方程组，Cramer 闭式解；
  Er = Er′ + Ed·Es。DUT 回收：Γ = (m − Ed)/(Er + Es·(m − Ed))。
  理想标准档（Γ={+1,−1,0}）代回即 trl_solt 的 d=m_load、Es=(ρ+1)/
  (ρ−1)、Er=2N_oN_s/(N_s−N_o)（ρ=N_o/N_s）同式——测试逐位互证。
- **诚实边界（预声明）**：①ISS 为一端口反射件模型（探针平面定义），
  共面模色散/衬底损耗对标准件本体的修正不在本域（那属探针/衬底建模，
  本族收标准件**定义→响应**闭式与校准反解面）；②多项式系数值须调用
  方给入（套件定义来源自负），本族不冒充任何厂商 spec 数值；③三项误
  差模型不含串扰/漂移项（八项以上归 trl_solt/thz_vna 级联域）；
  ④c₀..c₃/l₀..l₃ 单项系数允许带号（多项式惯例），但逐频点代入值必须
  ≥0（无源性检验，负值显式拒绝）。

出处
----
- Keysight 校准套件定义惯例（open 电容/短路电感频率多项式 C0..C3、
  L0..L3 格式，二级转引——格式出处而非厂商数值）。
- 在片 ISS（Impedance Standard Substrate）共面标准件语境（探针校准惯
  例，二级转引）。
- 一端口三项误差模型与回收闭式=Pozar Microwave Engineering VNA 校准
  章同款（trl_solt 同源文献族，二级转引）；理想档同式互证=同仓双源。

守卫：standard_type 白名单 open/short/load/thru；freq_ghz 有限>0 非空；
z0_ohm>0；电容/电感多项式仅各自键合法（错域显式拒绝）、逐频代入值≥0；
load_r_ohm>0、load_l_ph/load_c_ff≥0；length_mm≥0、eps_eff≥1、
loss_db_per_mm≥0；校准键 gamma_std_def/gamma_raw_meas 须 3 组 [re,im]
有限、|Γ_def|≤1+1e-9（无源标准）、3 个定义复数互异（行列式退化显式
拒绝）；越界一律显式 ValueError。

出处（Pozar VNA 校准章；ISS 探针格式惯例）：
- iss_standard_response/iss_oneport_cal_extract：一端口三项误差模型
  与回收闭式=Pozar Microwave Engineering VNA 校准章同款（trl_solt
  同源文献族，二级转引）；探针 ISS 标准 L0..L3 数据格式=探针校准惯例
  二级转引（格式出处而非厂商数值）；退化档与 trl_solt 同式同仓双源。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "iss_oneport_cal_extract",
    "iss_standard_response",
]

_C_LIGHT_M_S = 299792458.0
# dB→Np 精确换算（W3 cal_kit_verify 同款）：α_np = A_dB/(20·log10 e)
_NP_PER_DB = 1.0 / (20.0 * math.log10(math.e))

_STANDARDS = ("open", "short", "load", "thru")

_SOURCE = (
    "Keysight 校准套件定义惯例（open 电容/短路电感频率多项式 C0..C3/"
    "L0..L3 格式，二级转引，厂商数值如实不入 #122/#300）；在片 ISS 共面"
    "标准件语境（探针校准惯例，二级转引）；一端口三项模型=Pozar VNA 校"
    "准章同款（trl_solt 同源文献族）；同仓双源=cal_kit_standard_response "
    "open 一阶项同式互证")


def _freq_list(freq_ghz: Any) -> list[float]:
    if not isinstance(freq_ghz, (list, tuple)) or len(freq_ghz) == 0:
        raise ValueError(
            f"iss: freq_ghz 须为非空列表，收到 {freq_ghz!r}")
    out = []
    for v in freq_ghz:
        f = _finite(v, "freq_ghz")
        if f <= 0.0:
            raise ValueError(
                f"iss: freq_ghz 须有限 >0，收到 {v!r}")
        out.append(f)
    return out


def _poly_list(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(
            f"iss: {name} 须为 4 元多项式 [c0,c1,c2,c3]，收到 {value!r}")
    return [_finite(v, name) for v in value]


def _poly_eval(poly: list[float], f_ghz: float) -> float:
    """c0 + c1·f + c2·f² + c3·f³（f 以 GHz 代入）。"""
    return (poly[0] + poly[1] * f_ghz + poly[2] * f_ghz ** 2
            + poly[3] * f_ghz ** 3)


def _cplx_pair(value: Any, name: str) -> complex:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(
            f"iss_oneport: {name} 须为 [re, im] 两元素，收到 {value!r}")
    re = _finite(value[0], f"{name}.re")
    im = _finite(value[1], f"{name}.im")
    return complex(re, im)


def _gamma_json(g: complex) -> dict[str, Any]:
    mag = abs(g)
    return {
        "re": round(g.real, 15),
        "im": round(g.imag, 15),
        "mag": round(mag, 15),
        "mag_db": (round(20.0 * math.log10(mag), 12) if mag > 0.0
                   else None),
    }


def _reject_foreign(std: str, given: dict[str, Any]) -> None:
    """错域参数显式拒绝（W3 cal_kit_verify 同款纪律）。"""
    domain = {
        "open": ("cap_poly_ff",),
        "short": ("ind_poly_ph",),
        "load": ("load_r_ohm", "load_l_ph", "load_c_ff"),
        "thru": ("length_mm", "eps_eff", "loss_db_per_mm"),
    }
    for param in given:
        if param not in domain[std] and param != "freq_ghz":
            raise ValueError(
                f"iss_standard_response: 参数 {param!r} 仅属其他标准件域"
                f"（standard_type={std!r} 只收 {domain[std] + ('freq_ghz',)}"
                f"与 z0_ohm），显式拒绝")


# ─── 键 1：ISS 标准件寄生模型响应 ────────────────────────────────────────────

@register_calculator(
    "iss_standard_response",
    "ISS标准件响应闭式：在片共面校准件 open/short/load/thru 寄生模型逐频响"
    "应——open 边缘电容频率多项式 C(f)=c₀+c₁f+c₂f²+c₃f³（套件定义惯例格"
    "式）、short 串联电感多项式、load 薄膜电阻+寄生 LC、thru 匹配线损耗时"
    "延；Γ=(1−jωCZ0)/(1+jωCZ0) 等 closed-form。锚：理想退化 Γ=+1/−1/0、"
    "|S21|=10^(−IL/20) 恒等式、与 cal_kit_standard_response open 一阶项同"
    "仓互证",
    (("standard_type", "str 'open'/'short'/'load'/'thru'（共面在片标准件）"),
     ("freq_ghz", "array 频率列表 GHz（有限 >0）"),
     ("cap_poly_ff", "array open 专用 电容多项式 [c0,c1,c2,c3]（fF，f 以 "
                     "GHz 代入；缺省 [0,0,0,0]=理想开路；c1..c3 逐频代入"
                     "值须 ≥0）"),
     ("ind_poly_ph", "array short 专用 电感多项式 [l0,l1,l2,l3]（pH，同格"
                     "式；缺省 [0,0,0,0]=理想短路）"),
     ("load_r_ohm", "float load 专用 薄膜电阻 Ω（>0，缺省 50=理想负载）"),
     ("load_l_ph", "float load 专用 串联寄生电感 pH（≥0，缺省 0）"),
     ("load_c_ff", "float load 专用 并联寄生电容 fF（≥0，缺省 0）"),
     ("length_mm", "float thru 专用 线长 mm（≥0，缺省 0=理想直通）"),
     ("eps_eff", "float thru 专用 有效介电常数（≥1，缺省 1）"),
     ("loss_db_per_mm", "float thru 专用 平损耗 dB/mm（≥0，缺省 0）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）")),
    required=("standard_type", "freq_ghz"),
)
def iss_standard_response(
    standard_type: str,
    freq_ghz: list,
    cap_poly_ff: list | None = None,
    ind_poly_ph: list | None = None,
    load_r_ohm: float = 50.0,
    load_l_ph: float = 0.0,
    load_c_ff: float = 0.0,
    length_mm: float = 0.0,
    eps_eff: float = 1.0,
    loss_db_per_mm: float = 0.0,
    z0_ohm: float = 50.0,
) -> dict[str, Any]:
    if standard_type not in _STANDARDS:
        raise ValueError(
            f"iss_standard_response: standard_type 须 ∈{_STANDARDS}，"
            f"得到 {standard_type!r}")
    freqs = _freq_list(freq_ghz)
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"iss_standard_response: z0_ohm 必须 >0，得到 {z0!r}")

    # 错域参数拒绝（只报显式给出的非缺省域外参数——缺省 None 不触发）
    given_foreign: dict[str, Any] = {}
    if cap_poly_ff is not None:
        given_foreign["cap_poly_ff"] = cap_poly_ff
    if ind_poly_ph is not None:
        given_foreign["ind_poly_ph"] = ind_poly_ph
    if load_r_ohm != 50.0:
        given_foreign["load_r_ohm"] = load_r_ohm
    if load_l_ph != 0.0:
        given_foreign["load_l_ph"] = load_l_ph
    if load_c_ff != 0.0:
        given_foreign["load_c_ff"] = load_c_ff
    if length_mm != 0.0:
        given_foreign["length_mm"] = length_mm
    if eps_eff != 1.0:
        given_foreign["eps_eff"] = eps_eff
    if loss_db_per_mm != 0.0:
        given_foreign["loss_db_per_mm"] = loss_db_per_mm
    _reject_foreign(standard_type, given_foreign)

    out: dict[str, Any] = {
        "standard_type": standard_type,
        "freq_ghz": [round(f, 15) for f in freqs],
        "z0_ohm": z0,
    }

    if standard_type in ("open", "short"):
        if standard_type == "open":
            raw_poly = cap_poly_ff if cap_poly_ff is not None else [0.0] * 4
            pname = "cap_poly_ff"
        else:
            raw_poly = ind_poly_ph if ind_poly_ph is not None else [0.0] * 4
            pname = "ind_poly_ph"
        poly = _poly_list(raw_poly, pname)
        vals = [_poly_eval(poly, f) for f in freqs]
        negatives = [(f, v) for f, v in zip(freqs, vals, strict=True)
                     if v < 0.0]
        if negatives:
            raise ValueError(
                f"iss_standard_response: 多项式在 {negatives[0][0]!r} GHz "
                f"代入值为 {negatives[0][1]!r} <0（无源性检验），显式拒绝")
        if standard_type == "open":
            eff_ff = [round(v, 15) for v in vals]
            gre: list[float] = []
            gim: list[float] = []
            for f, c_ff in zip(freqs, vals, strict=True):
                omega_c_z0 = (2.0 * math.pi * f * 1e9) * (c_ff * 1e-15) * z0
                den = complex(1.0, omega_c_z0)
                g = complex(1.0, -omega_c_z0) / den
                gre.append(round(g.real, 15))
                gim.append(round(g.imag, 15))
            out.update({
                "cap_eff_ff": eff_ff,
                "gamma_re": gre,
                "gamma_im": gim,
                "gamma_mag": [round(math.hypot(a, b), 15)
                              for a, b in zip(gre, gim, strict=True)],
                "ideal_gamma": "+1",
                "note": (
                    "共面开路=边缘电容主导（无 offset 线段，纯并联容抗反"
                    "射）：C(f)=c₀+c₁f+c₂f²+c₃f³ 逐频代入（多项式单项系"
                    "数允许带号、逐频代入值≥0 无源检验），"
                    "Γ=(1−jωC·Z0)/(1+jωC·Z0)；理想 C=0 → Γ=+1 逐位；"
                    "C>0 → 相位随 f 单调负旋 2·atan(ωC·Z0)。与 "
                    "cal_kit_standard_response open 一阶项同式（C 为常数"
                    "档逐位互证，同仓双源）；厂商 ISS 系数值无原文实取如"
                    "实不入"),
                "source": _SOURCE,
            })
        else:
            eff_ph = [round(v, 15) for v in vals]
            gre = []
            gim = []
            for f, l_ph in zip(freqs, vals, strict=True):
                z = 1j * (2.0 * math.pi * f * 1e9) * (l_ph * 1e-12)
                g = (z - z0) / (z + z0)
                gre.append(round(g.real, 15))
                gim.append(round(g.imag, 15))
            out.update({
                "ind_eff_ph": eff_ph,
                "gamma_re": gre,
                "gamma_im": gim,
                "gamma_mag": [round(math.hypot(a, b), 15)
                              for a, b in zip(gre, gim, strict=True)],
                "ideal_gamma": "-1",
                "note": (
                    "共面短路=电流路径磁储能（串联感抗反射）：L(f) 同多项"
                    "式惯例格式，Z=jωL → Γ=(Z−Z0)/(Z+Z0)；理想 L=0 → "
                    "Γ=−1 逐位；L>0 → 相位自 180° 回旋 "
                    "−2·atan(ωL/Z0)（|Γ|=1 无耗档）"),
                "source": _SOURCE,
            })
        return out

    if standard_type == "load":
        r = _finite(load_r_ohm, "load_r_ohm")
        if r <= 0.0:
            raise ValueError(
                f"iss_standard_response: load_r_ohm 必须 >0，得到 {r!r}")
        l_l = _finite(load_l_ph, "load_l_ph")
        c_l = _finite(load_c_ff, "load_c_ff")
        if l_l < 0.0 or c_l < 0.0:
            raise ValueError(
                f"iss_standard_response: load 寄生须 ≥0（无源），得到 "
                f"l_ph={l_l!r}, c_ff={c_l!r}")
        gre, gim = [], []
        for f in freqs:
            omega = 2.0 * math.pi * f * 1e9
            z = 1j * omega * (l_l * 1e-12) + r / complex(
                1.0, omega * r * (c_l * 1e-15))
            g = (z - z0) / (z + z0)
            gre.append(round(g.real, 15))
            gim.append(round(g.imag, 15))
        out.update({
            "load_r_ohm": r, "load_l_ph": l_l, "load_c_ff": c_l,
            "gamma_re": gre, "gamma_im": gim,
            "gamma_mag": [round(math.hypot(a, b), 15)
                          for a, b in zip(gre, gim, strict=True)],
            "ideal_gamma": "0",
            "note": (
                "薄膜负载=π 型共面电阻（信号-地间薄膜 50Ω）：Z=jωL_l+"
                "R/(1+jωR·C_l) → Γ=(Z−Z0)/(Z+Z0)；理想 R=Z0 且寄生为零 "
                "→ Γ=0 逐位；寄生 ≥0 无源 ⇒ |Γ|≤1（失配地板 "
                "RL=−20lg|Γ|）"),
            "source": _SOURCE,
        })
        return out

    # thru
    length = _finite(length_mm, "length_mm")
    eps = _finite(eps_eff, "eps_eff")
    loss = _finite(loss_db_per_mm, "loss_db_per_mm")
    if length < 0.0:
        raise ValueError(
            f"iss_standard_response: length_mm 必须 ≥0，得到 {length!r}")
    if eps < 1.0:
        raise ValueError(
            f"iss_standard_response: eps_eff 必须 ≥1，得到 {eps!r}")
    if loss < 0.0:
        raise ValueError(
            f"iss_standard_response: loss_db_per_mm 必须 ≥0，得到 {loss!r}")
    s_re, s_im, il_db, tau_ns = [], [], [], []
    for f in freqs:
        beta = 2.0 * math.pi * (f * 1e9) * math.sqrt(eps) / _C_LIGHT_M_S
        l_m = length * 1e-3
        il = loss * length
        alpha_np = il * _NP_PER_DB
        s21 = math.exp(-alpha_np) * complex(math.cos(beta * l_m),
                                            -math.sin(beta * l_m))
        s_re.append(round(s21.real, 15))
        s_im.append(round(s21.imag, 15))
        il_db.append(round(il, 12))
        tau_ns.append(round(length * 1e-3 * math.sqrt(eps)
                            / _C_LIGHT_M_S * 1e9, 15))
    out.update({
        "length_mm": length, "eps_eff": eps,
        "loss_db_per_mm": loss,
        "s21_re": s_re, "s21_im": s_im,
        "s21_mag_db": [round(-v, 12) for v in il_db],
        "il_db": il_db,
        "group_delay_ns": tau_ns,
        "ideal_s21": "1",
        "note": (
            "共面直通=匹配线段：S21=exp(−(α_np+jβ)l)，β=2πf√εeff/c、"
            "|S21|=10^(−IL/20) 恒等式（IL=loss_db_mm·l_mm 平损耗档）、"
            "时延 τ=l·√εeff/c；理想 l=0 → S21=1 逐位；S11=0（匹配档，"
            "线体失配修正不在本域）"),
        "source": _SOURCE,
    })
    return out


# ─── 键 2：一端口三项误差模型提取+Γ 回收 ─────────────────────────────────────

def _cramer3(a: list[list[complex]], b: list[complex]) -> tuple[
        complex, float]:
    """3×3 Cramer 闭式解；返回 (解向量, |det|)。"""
    (a11, a12, a13), (a21, a22, a23), (a31, a32, a33) = a
    det = (a11 * (a22 * a33 - a23 * a32)
           - a12 * (a21 * a33 - a23 * a31)
           + a13 * (a21 * a32 - a22 * a31))
    if abs(det) < 1e-12:
        raise ValueError(
            "iss_oneport_cal_extract: 标准件定义组退化（3×3 行列式 "
            f"|det|={abs(det):.3e} <1e-12）——三个标准定义 Γ 须互异且张成"
            "三项模型可解空间")
    d0 = b[0] * (a22 * a33 - a23 * a32) \
        - a12 * (b[1] * a33 - a23 * b[2]) \
        + a13 * (b[1] * a32 - a22 * b[2])
    d1 = a11 * (b[1] * a33 - a23 * b[2]) \
        - b[0] * (a21 * a33 - a23 * a31) \
        + a13 * (a21 * b[2] - b[1] * a31)
    d2 = a11 * (a22 * b[2] - b[1] * a32) \
        - a12 * (a21 * b[2] - b[1] * a31) \
        + b[0] * (a21 * a32 - a22 * a31)
    return (d0 / det, d1 / det, d2 / det), abs(det)


@register_calculator(
    "iss_oneport_cal_extract",
    "ISS单端口校准提取：任意非理想标准件定义下的三项误差模型闭式反解+DUT "
    "Γ 回收——Γ_meas=Ed+Er·Γ/(1−Es·Γ) 恒等变形为 3×3 线性组 Cramer 解（"
    "Er′=Er−Ed·Es 换算）；理想档（Γ=+1/−1/0）与 trl_solt 一端口闭式同式"
    "逐位互证（同仓双源）",
    (("gamma_std_def", "array 3 组标准件已知定义 [re,im]（序=open/short/"
                       "load，可含 ISS 寄生定义；|Γ|≤1+1e-9 无源）"),
     ("gamma_raw_meas", "array 3 组标准件原始测量 [re,im]（同序 open/"
                        "short/load）"),
     ("gamma_meas_raw", "array 被测件原始测量 [re,im]（可选；缺省只提误差"
                        "箱）")),
    required=("gamma_std_def", "gamma_raw_meas"),
)
def iss_oneport_cal_extract(
    gamma_std_def: list,
    gamma_raw_meas: list,
    gamma_meas_raw: list | None = None,
) -> dict[str, Any]:
    if len(gamma_std_def) != 3 or len(gamma_raw_meas) != 3:
        raise ValueError(
            "iss_oneport_cal_extract: gamma_std_def/gamma_raw_meas 须各为 "
            f"3 组 [re,im]（序=open/short/load），收到 "
            f"{len(gamma_std_def)}/{len(gamma_raw_meas)} 组")
    g_defs = [_cplx_pair(v, f"gamma_std_def[{i}]")
              for i, v in enumerate(gamma_std_def)]
    m_raws = [_cplx_pair(v, f"gamma_raw_meas[{i}]")
              for i, v in enumerate(gamma_raw_meas)]
    for i, g in enumerate(g_defs):
        if abs(g) > 1.0 + 1e-9:
            raise ValueError(
                f"iss_oneport_cal_extract: 标准定义 |Γ[{i}]|={abs(g)!r} >"
                "1+1e-9（无源标准检验），显式拒绝")

    # 恒等变形：m_i = Ed + Er′·Γ_i + Es·(m_i·Γ_i)，未知 (Ed, Er′, Es)
    mat = [[complex(1.0), g_defs[i], m_raws[i] * g_defs[i]]
           for i in range(3)]
    rhs = list(m_raws)
    (ed, er_prime, es), det = _cramer3(mat, rhs)
    er = er_prime + ed * es

    # 反解残差（回代裁判）：|m_i − (Ed + Er·Γ/(1−Es·Γ))| 最大值
    residual = 0.0
    for i in range(3):
        forward = ed + er * g_defs[i] / (complex(1.0) - es * g_defs[i])
        residual = max(residual, abs(m_raws[i] - forward))

    out: dict[str, Any] = {
        "ed": _gamma_json(ed),
        "es": _gamma_json(es),
        "er": _gamma_json(er),
        "er_prime": _gamma_json(er_prime),
        "det_abs": round(det, 18),
        "solve_max_residual": round(residual, 18),
        "gamma_std_def": [[round(g.real, 15), round(g.imag, 15)]
                          for g in g_defs],
        "gamma_raw_meas": [[round(m.real, 15), round(m.imag, 15)]
                           for m in m_raws],
        "reciprocity": "one-port three-term error box (no S-matrix output)",
    }
    if gamma_meas_raw is not None:
        m = _cplx_pair(gamma_meas_raw, "gamma_meas_raw")
        num = m - ed
        den = er + es * num
        if abs(den) < 1e-300:
            raise ValueError(
                "iss_oneport_cal_extract: DUT 回收分母 |Er+Es·(m−Ed)|≈0"
                "（Er=0 或 m 恰在奇异点），显式拒绝")
        gamma_dut = num / den
        out["gamma_dut"] = _gamma_json(gamma_dut)
        out["gamma_meas_raw"] = [round(m.real, 15), round(m.imag, 15)]
    out["note"] = (
        "一端口三项误差模型 Γ_meas=Ed+Er·Γ/(1−Es·Γ)：恒等变形 "
        "m_i=Ed+Er′Γ_i+Es(m_iΓ_i)（Er′=Er−Ed·Es）→ 3×3 线性组 Cramer "
        "闭式解，Er=Er′+Ed·Es；DUT 回收 Γ=(m−Ed)/(Er+Es(m−Ed))。"
        "任意非理想标准定义直入（ISS 寄生定义由 iss_standard_response "
        "产出）；理想档 Γ={+1,−1,0} 退化回 trl_solt 同式（d=m_load、"
        "Es=(ρ+1)/(ρ−1)、Er=2N_oN_s/(N_s−N_o)，ρ=N_o/N_s）——同仓双源"
        "逐位互证见锚树测试。solve_max_residual=反解回代残差（闭式精确"
        "性裁判）")
    out["source"] = (
        "Pozar Microwave Engineering VNA 校准章一端口三项模型（二级转引，"
        "trl_solt 同源文献族）；理想档与 core/trl_solt.py 闭式同仓双源"
        "互证；ISS 语境见 iss_on_wafer 模块 docstring 边界节")
    return out
