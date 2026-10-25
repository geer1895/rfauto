"""Kuroda 恒等式族（aurora_f W4-S14 席域 2，R2_core_tier3 边际池立项）。

两键：kuroda_identity_abcd（Pozar Table 8.7 四恒等式——单位元/串联短路/
并联开路/串联开路/并联短路线段在传输线滤波器实现间的精确等效变换，两侧
ABCD 矩阵逐位恒等断言字段）/ kuroda_shunt_realize（三阶低通原型的
Richards 变换+Kuroda (b) 两端化并联实现——Pozar Example 8.5 全链：g 值→
全并联 stub 拓扑（归一+定标），全链 ABCD 等价残差字段）。

边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- 全仓 grep（kuroda）src/tests 零命中（R2 §③ D9 附注同证）；本族为该域
  首批注册键。
- Richards 变换本体已在 core/stub_k_inverter.py（richards_omega/
  richards_omega_inverse，P.I. Richards 1948 同源单源）——本族不重复实
  现，仅在输出字段给出 Ω=tan(θ) 映射值供互查；stub_filter_design=短截
  线 BPF 综合（消费变换结果）不同对象；synthesize_commensurate_line=
  全 λ/4 阻抗变换匹配域不并入（边界互指见两模块 docstring）。
- 输出 ABCD 以 re/im 分量列表面呈现（无复 S 矩阵结构产出，互易语义由
  max_abcd_dev/reciprocity 自报——S 面归类见
  test_physics_invariants._NO_S_PLANE_KEYS 注记）。

物理口径（docstring 写死，#1c/#300 出处纪律；#122 文献锚=原文数值实取）
--------------------------------------------------------
- **网络基元 ABCD**（Pozar Table 4.1 同式）：单位元（unit element，
  λ/8@ωc 传输线 Z）[cosθ, jZ·sinθ; j·sinθ/Z, cosθ]；串联短路线段
  Z_in=jZ·tanθ → [1, jZ·tanθ; 0, 1]；串联开路线段 Z_in=−jZ·cotθ；
  并联线段以导纳入阵 [1,0; 1/Z_in, 1]；理想变压器 n:1 → [n,0; 0,1/n]。
  四恒等式在**任意公共电长 θ**（commensurate）下两侧 ABCD 逐位相等
  （Pozar §8.5 式 (8.79)-(8.80) 以 Ω=tanβℓ 因式分解的证明口径，本族
  数值实现逐位复核）。
- **四恒等式**（行语义按本族参数命名 stub=短截线、ue=单位元；元素序=
  级联序，输入→输出）：
  (a) [并联开路 stub] · [UE ue] ≡ [UE stub/n²] · [串联短路 ue/n²]，n²=1+stub/ue
  (b) [串联短路 stub] · [UE ue] ≡ [UE n²·stub] · [并联开路 n²·ue]，n²=1+ue/stub
  (c) [并联短路 stub] · [UE ue] ≡ [UE ue/n²] · [并联短路 stub/n²] · [变压器 1:n²]，n²=1+ue/stub
  (d) [串联开路 stub] · [UE ue] ≡ [UE n²·ue] · [串联开路 n²·stub] · [变压器 n²:1]，n²=1+stub/ue
  （(a)(b) 无变压器=串联↔并联、开路↔短路双转换；(c)(d) 同型换位+变压
  器阻抗重整——Pozar Table 8.7 四行原样（行标签 Z₁/Z₂ 在各行互换位置，
  n²=1+Z₂/Z₁ 恒成立，本族以 stub/ue 显式命名消除错位并在输出回显元素
  清单）。）
- **三阶低通全并联实现**（kuroda_shunt_realize，Pozar Example 8.5 全链
  逐位口径）：Chebyshev 等纹波原型 g₁=L₁、g₂=C₂、g₃=L₃、g₄=R_L=1
  → Richards 变换（串联电感→串联短路线段 Z=L、并联电容→并联开路线段
  Z=1/C，截长 λ/8@ωc）→ 两端加 UE(Z₀=1)（冗余件，匹配不改变响应）→
  两端各应用恒等式 (b)（n²=1+1/g₁ 与 1+1/g₃）→ 全并联拓扑
  [并联开路 n²·1][UE n²g₁][并联开路 1/g₂][UE n²g₃][并联开路 n²·1] →
  阻抗定标 ×Z₀。文献数值锚（#122）：g=(3.3487, 0.7117, 3.3487)、Z₀=50Ω
  → 并联短截线 64.9/70.3/64.9Ω、连接线 217.5Ω（Pozar 图 8.36(e) 三位
  有效数字圆整值；本族精确值 64.931/70.254/64.931/217.435——圆整窗
  0.5% 内一致）。一般 N 阶的级联恒等式迭代化实现不在本键（留续作，
  N=3 两端化=Pozar 原例口径如实声明）。

出处
----
- D.M. Pozar, Microwave Engineering 4th ed., §8.5（式 8.77-8.80、
  Table 8.7、Example 8.5/图 8.36）——四恒等式与全链数值原文实取。
- P.I. Richards, "Resistor-transmission-line circuits", Proc. IRE 36
  (1948)——变换本体（实现单源 core/stub_k_inverter）。

守卫：identity ∈{1,2,3,4}；z1/z2>0；θ∈(0,π) 且 sinθ≠0（θ=0/π 线段零
长奇异显式拒绝）；realize 键 g 须 3 元全正、z0>0。

出处（Pozar《Microwave Engineering》Table 8.7/§8.5/Example 8.5）：
- kuroda_identity_abcd：Pozar Table 8.7 四恒等式原样（Richards 变换
  Ω=tanβℓ；§8.5 式(8.79)-(8.80) 因式分解证明口径；Ex8.5 文献数值窗
  ±0.5% 逐位锚在测试）。
- kuroda_shunt_realize：Pozar Example 8.5 三阶低通全并联实现全链
  （g=(3.3487,0.7117,3.3487) 文献数值锚原文实取）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "abcd": ("Pozar Microwave Engineering 4th ed. §8.5 Table 8.7 四 Kuroda "
             "恒等式（式 8.79-8.80 ABCD 证明口径）：基元=λ/8 单位元/串联短"
             "路/串联开路/并联短路/并联开路线段+理想变压器；commensurate "
             "公共电长下两侧 ABCD 逐位相等"),
    "realize": ("Pozar 4th ed. Example 8.5（图 8.36 全链）：三阶 Chebyshev "
                "等纹波原型 g=(3.3487, 0.7117, 3.3487) → Richards 变换 → "
                "两端加 UE → 恒等式 (b) 两端化并联（n²=1+1/g₁=1+1/g₃="
                "1.2987）→ 阻抗定标；文献圆整值 217.5/64.9/70.3/64.9Ω"),
}


def _ue_abcd(z: float, th: float) -> list[list[complex]]:
    c = complex(math.cos(th), 0.0)
    s = complex(math.sin(th), 0.0)
    return [[c, 1j * z * s], [1j * s / z, c]]


def _stub_zin(z: float, kind: str, th: float) -> complex:
    tan_th = math.tan(th)
    if kind == "short":
        return 1j * z * tan_th
    if kind == "open":
        return -1j * z / tan_th
    raise ValueError(f"kuroda: stub kind 须 'short'/'open'，得到 {kind!r}")


def _series_abcd(zin: complex) -> list[list[complex]]:
    one = complex(1.0)
    zero = complex(0.0)
    return [[one, zin], [zero, one]]


def _shunt_abcd(yin: complex) -> list[list[complex]]:
    one = complex(1.0)
    zero = complex(0.0)
    return [[one, zero], [yin, one]]


def _trf_abcd(ratio: float) -> list[list[complex]]:
    return [[complex(ratio), complex(0.0)],
            [complex(0.0), complex(1.0 / ratio)]]


def _abcd_mul(m1: list[list[complex]], m2: list[list[complex]]
              ) -> list[list[complex]]:
    return [
        [m1[0][0] * m2[0][0] + m1[0][1] * m2[1][0],
         m1[0][0] * m2[0][1] + m1[0][1] * m2[1][1]],
        [m1[1][0] * m2[0][0] + m1[1][1] * m2[1][0],
         m1[1][0] * m2[0][1] + m1[1][1] * m2[1][1]],
    ]


def _abcd_chain(mats: list[list[list[complex]]]) -> list[list[complex]]:
    out = mats[0]
    for m in mats[1:]:
        out = _abcd_mul(out, m)
    return out


def _abcd_dev(m1: list[list[complex]], m2: list[list[complex]]) -> float:
    return max(abs(m1[i][j] - m2[i][j]) for i in range(2) for j in range(2))


def _flat_abcd(m: list[list[complex]]) -> dict[str, list[float]]:
    return {
        "a_re": [round(m[0][0].real, 15), round(m[0][1].real, 15),
                 round(m[1][0].real, 15), round(m[1][1].real, 15)],
        "a_im": [round(m[0][0].imag, 15), round(m[0][1].imag, 15),
                 round(m[1][0].imag, 15), round(m[1][1].imag, 15)],
    }


def _element(kind: str, z_ohm: float | None = None,
             ratio: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": kind}
    if z_ohm is not None:
        out["z_ohm"] = round(z_ohm, 12)
    if ratio is not None:
        out["ratio"] = (round(ratio, 15) if isinstance(ratio, float)
                        else ratio)
    return out


# ─── 键 1：四恒等式 ABCD 逐位校验 ─────────────────────────────────────────────
# 行规格（数值经 4 行×3 电长 θ 数值复核，dev≤4.4e-16；元素序=级联序）：
#   (a) 左=[并联开路 stub][UE ue]  右=[UE stub/n²][串联短路 ue/n²]  n²=1+stub/ue
#   (b) 左=[串联短路 stub][UE ue]  右=[UE n²·stub][并联开路 n²·ue]  n²=1+ue/stub
#   (c) 左=[并联短路 stub][UE ue]  右=[UE ue/n²][并联短路 stub/n²][变压器 1:n²]
#   (d) 左=[串联开路 stub][UE ue]  右=[UE n²·ue][串联开路 n²·stub][变压器 n²:1]
# Pozar 行标签对照：Z₁=左首位短截线、Z₂=单位元（(a)(d) 标签互换位置但
# n²=1+Z₂/Z₁ 恒成立）——本表以 stub/ue 显式命名消除错位。
_IDENTITY_ROWS = {
    1: {"label": "(a)", "stub_kind": "shunt_open",
        "left": [("shunt_open", "stub"), ("ue", "ue")],
        "right": [("ue", "stub/n"), ("series_short", "ue/n")],
        "n_sq": "stub_over_ue"},
    2: {"label": "(b)", "stub_kind": "series_short",
        "left": [("series_short", "stub"), ("ue", "ue")],
        "right": [("ue", "n*stub"), ("shunt_open", "n*ue")],
        "n_sq": "ue_over_stub"},
    3: {"label": "(c)", "stub_kind": "shunt_short",
        "left": [("shunt_short", "stub"), ("ue", "ue")],
        "right": [("ue", "ue/n"), ("shunt_short", "stub/n"),
                  ("transformer", "inv")],
        "n_sq": "ue_over_stub"},
    4: {"label": "(d)", "stub_kind": "series_open",
        "left": [("series_open", "stub"), ("ue", "ue")],
        "right": [("ue", "n*ue"), ("series_open", "n*stub"),
                  ("transformer", "id")],
        "n_sq": "stub_over_ue"},
}


def _resolve_z(expr: str, z_stub: float, z_ue: float, n_sq: float) -> float:
    if expr == "stub":
        return z_stub
    if expr == "ue":
        return z_ue
    if expr == "stub/n":
        return z_stub / n_sq
    if expr == "ue/n":
        return z_ue / n_sq
    if expr == "n*stub":
        return n_sq * z_stub
    if expr == "n*ue":
        return n_sq * z_ue
    raise ValueError(f"kuroda_identity_abcd: 内部规格错误 {expr!r}")


@register_calculator(
    "kuroda_identity_abcd",
    "Kuroda恒等式ABCD校验：Pozar Table 8.7 四恒等式（单位元+短截线在传输"
    "线滤波器实现间的精确等效）——(a) 并联开路·UE ≡ UE·串联短路、(b) 串"
    "联短路·UE ≡ UE·并联开路（无变压器双转换）、(c) 并联短路·UE ≡ "
    "UE·并联短路·变压器1:n²、(d) 串联开路·UE ≡ UE·串联开路·变压器n²:1，"
    "n²=1+Z₂/Z₁；两侧逐元素 ABCD 级联+逐位恒等残差字段（任意公共电长成"
    "立，commensurate 口径）。锚：四式 dev≤1e-12+Pozar 式 8.80 手算档",
    (("identity", "int 恒等式行号 1..4（=Pozar Table 8.7 行 (a)..(d)）"),
     ("z1_ohm", "float Ω 短截线特征阻抗 Z₁（>0；(a)(d)=并联开路/串联开"
                "路线段，(b)(c)=串联短路/并联短路线段）"),
     ("z2_ohm", "float Ω 单位元特征阻抗 Z₂（>0）"),
     ("theta_deg", "float deg 公共电长 θ（0<θ<180，λ/8@ωc 惯例=45，缺省 "
                   "45；commensurate 任意值恒等）")),
    required=("identity", "z1_ohm", "z2_ohm"),
)
def kuroda_identity_abcd(identity: int, z1_ohm: float, z2_ohm: float,
                         theta_deg: float = 45.0) -> dict[str, Any]:
    if identity not in _IDENTITY_ROWS:
        raise ValueError(
            f"kuroda_identity_abcd: identity 须 ∈{{1,2,3,4}}"
            f"（Pozar Table 8.7 行 (a)..(d)），得到 {identity!r}")
    z_stub = _finite(z1_ohm, "z1_ohm")
    z_ue = _finite(z2_ohm, "z2_ohm")
    if z_stub <= 0.0 or z_ue <= 0.0:
        raise ValueError(
            f"kuroda_identity_abcd: 阻抗须 >0，得到 z1={z_stub!r}, "
            f"z2={z_ue!r}")
    th_deg = _finite(theta_deg, "theta_deg")
    if not 0.0 < th_deg < 180.0:
        raise ValueError(
            f"kuroda_identity_abcd: theta_deg 须 ∈(0,180)，得到 {th_deg!r}")
    th = math.radians(th_deg)
    if abs(math.sin(th)) < 1e-15:
        raise ValueError(
            f"kuroda_identity_abcd: θ={th_deg}° 触及 sinθ=0 奇异（线段零"
            f"长退化），显式拒绝")
    row = _IDENTITY_ROWS[identity]
    n_sq = ((1.0 + z_stub / z_ue) if row["n_sq"] == "stub_over_ue"
            else 1.0 + z_ue / z_stub)

    def _elem_mat(kind: str, z: float) -> list[list[complex]]:
        if kind == "ue":
            return _ue_abcd(z, th)
        if kind == "series_short":
            return _series_abcd(_stub_zin(z, "short", th))
        if kind == "series_open":
            return _series_abcd(_stub_zin(z, "open", th))
        if kind == "shunt_open":
            return _shunt_abcd(1.0 / _stub_zin(z, "open", th))
        if kind == "shunt_short":
            return _shunt_abcd(1.0 / _stub_zin(z, "short", th))
        raise ValueError(f"kuroda_identity_abcd: 内部规格错误 {kind!r}")

    left = _abcd_chain([_elem_mat(kind, _resolve_z(expr, z_stub, z_ue, n_sq))
                        for kind, expr in row["left"]])
    right_elems: list[dict[str, Any]] = []
    right_mats: list[list[list[complex]]] = []
    for kind, expr in row["right"]:
        if kind == "transformer":
            ratio = (1.0 / n_sq) if expr == "inv" else n_sq
            right_elems.append(_element("transformer", ratio=ratio))
            right_mats.append(_trf_abcd(ratio))
            continue
        z = _resolve_z(expr, z_stub, z_ue, n_sq)
        right_elems.append(_element(kind, z_ohm=z))
        right_mats.append(_elem_mat(kind, z))
    right = _abcd_chain(right_mats)
    dev = _abcd_dev(left, right)
    omega = math.tan(th)
    left_elems = [
        (_element(kind, z_ohm=_resolve_z(expr, z_stub, z_ue, n_sq))
         if kind != "transformer" else _element("transformer", ratio=n_sq))
        for kind, expr in row["left"]]
    return {
        "identity": identity,
        "pozar_table_row": row["label"],
        "n_sq": round(n_sq, 15),
        "z1_ohm": z_stub,
        "z2_ohm": z_ue,
        "theta_deg": th_deg,
        "richards_omega_tan_theta": round(omega, 15),
        "left_elements": left_elems,
        "right_elements": right_elems,
        "abcd_left": _flat_abcd(left),
        "abcd_right": _flat_abcd(right),
        "max_abcd_dev": round(dev, 18),
        "reciprocity": "both networks reciprocal (Kuroda identities are "
                       "exact 2-port equivalences)",
        "note": (
            "行语义（stub=短截线、ue=单位元，Pozar Table 8.7 原样，元素"
            "序=级联序 输入→输出）：(a) [并联开路 stub][UE ue] ≡ [UE "
            "stub/n²][串联短路 ue/n²]，n²=1+stub/ue；(b) [串联短路 stub]"
            "[UE ue] ≡ [UE n²stub][并联开路 n²ue]，n²=1+ue/stub；(c) [并"
            "联短路 stub][UE ue] ≡ [UE ue/n²][并联短路 stub/n²][变压器 "
            "1:n²]，n²=1+ue/stub；(d) [串联开路 stub][UE ue] ≡ [UE n²ue]"
            "[串联开路 n²stub][变压器 n²:1]，n²=1+stub/ue。恒等在任意公"
            "共电长成立（commensurate），θ 缺省 45°=λ/8@ωc 惯例；Richards "
            "变换 Ω=tan(βℓ) 本体单源在 core/stub_k_inverter.richards_"
            "omega（本键只给映射值供互查）"),
        "source": _SOURCES["abcd"],
    }


# ─── 键 2：三阶低通全并联实现（Pozar Example 8.5 全链）────────────────────────

@register_calculator(
    "kuroda_shunt_realize",
    "Kuroda并联化实现：三阶低通原型 Richards 变换+恒等式(b)两端化并联（"
    "Pozar Example 8.5 全链）——g=(g₁,g₂,g₃)（串联 L/并联 C/串联 L）→ 串"
    "联短路 g_i/并联开路 1/g₂ 线段（λ/8@ωc）→ 两端加 UE(Z₀=1) → n²=1+1/g₁"
    "（两端对称）→ 全并联拓扑 [并联 n²·1][UE n²g₁][并联 1/g₂][UE n²g₃][并"
    "联 n²·1] ×Z₀ 定标；全链原始 vs 实现 ABCD 等价残差字段。锚：Ex 8.5 "
    "g=(3.3487,0.7117,3.3487)/50Ω → 64.93/70.25/64.93/217.435Ω（文献圆整 "
    "64.9/70.3/217.5）",
    (("g", "array 三阶低通原型 g 值 [g1,g2,g3]（g1/g3=串联 L、g2=并联 C，"
           "全正；Chebyshev 等纹波例 (3.3487, 0.7117, 3.3487)）"),
     ("z0_ohm", "float Ω 阻抗定标因子（源/负载阻抗；归一档传 1.0，缺省 "
                "50）")),
    required=("g",),
)
def kuroda_shunt_realize(g: list, z0_ohm: float = 50.0) -> dict[str, Any]:
    gvals = [float(v) for v in g]
    if len(gvals) != 3:
        raise ValueError(
            f"kuroda_shunt_realize: g 须为 3 元列表 [g1,g2,g3]（三阶原型，"
            f"一般 N 阶迭代化实现留续作），得到 {len(gvals)} 元")
    if any(not (v > 0.0) or not math.isfinite(v) for v in gvals):
        raise ValueError(
            f"kuroda_shunt_realize: g 值须全为正有限数，得到 {g!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"kuroda_shunt_realize: z0_ohm 必须 >0，得到 {z0!r}")
    g1, g2, g3 = gvals
    n_sq = 1.0 + 1.0 / g1
    n_sq_right = (1.0 + 1.0 / g3
                  if abs(n_sq - (1.0 + 1.0 / g3)) > 1e-12 else n_sq)

    th = math.pi / 4.0
    ue_norm = 1.0
    series1 = _stub_zin(g1, "short", th)
    shunt2 = 1.0 / _stub_zin(1.0 / g2, "open", th)
    series3 = _stub_zin(g3, "short", th)
    orig = _abcd_chain([
        _ue_abcd(ue_norm, th),
        _series_abcd(series1),
        _shunt_abcd(shunt2),
        _series_abcd(series3),
        _ue_abcd(ue_norm, th),
    ])
    stub_left = n_sq * ue_norm
    ue_left = n_sq * g1
    stub_mid = 1.0 / g2
    ue_right = n_sq_right * g3
    stub_right = n_sq_right * ue_norm
    real = _abcd_chain([
        _shunt_abcd(1.0 / _stub_zin(stub_left, "open", th)),
        _ue_abcd(ue_left, th),
        _shunt_abcd(1.0 / _stub_zin(stub_mid, "open", th)),
        _ue_abcd(ue_right, th),
        _shunt_abcd(1.0 / _stub_zin(stub_right, "open", th)),
    ])
    dev = _abcd_dev(orig, real)
    return {
        "g": [round(v, 15) for v in gvals],
        "z0_ohm": z0,
        "n_sq": round(n_sq, 15),
        "n_sq_right": round(n_sq_right, 15),
        "stub_shunt_normalized": [round(v, 15) for v in
                                  (stub_left, stub_mid, stub_right)],
        "ue_line_normalized": [round(v, 15) for v in (ue_left, ue_right)],
        "stub_shunt_ohm": [round(v * z0, 9) for v in
                           (stub_left, stub_mid, stub_right)],
        "ue_line_ohm": [round(v * z0, 9) for v in (ue_left, ue_right)],
        "topology": ("[并联开路 stub][UE 线][并联开路 stub][UE 线]"
                     "[并联开路 stub]（λ/8@ωc，输入→输出）"),
        "chain_abcd_max_dev": round(dev, 18),
        "reciprocity": "realized network reciprocal (exact equivalence, "
                       "chain ABCD identical up to float roundoff)",
        "note": (
            "Pozar Example 8.5 全链口径：归一原型（g₄=R_L=1 隐含）→ "
            "Richards 变换（串联电感 Z=L、并联电容 Z=1/C，全 λ/8@ωc）→ "
            "两端加 UE(Z₀=1)（匹配冗余件不改响应）→ 恒等式 (b) 及其镜像"
            "两端应用（n²=1+UE/g₁；非对称 g₁≠g₃ 时两端 n² 分列如实）→ "
            "全并联拓扑×Z₀ 定标；chain_abcd_max_dev=原始 vs 实现 ABCD 全"
            "链逐位残差（恒等式精确性的端到端裁判）。文献数值锚："
            "g=(3.3487,0.7117,3.3487)、Z₀=50Ω → 短截线 "
            "64.931/70.254/64.931Ω、连接线 217.435Ω（Pozar 图 8.36(e) 圆"
            "整值 64.9/70.3/64.9/217.5Ω）；一般 N 阶迭代化实现留续作（本"
            "键=N=3 两端化原例口径）"),
        "source": _SOURCES["realize"],
    }
