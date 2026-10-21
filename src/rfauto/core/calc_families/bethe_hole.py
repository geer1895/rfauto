"""Bethe 孔定向耦合器（矩形波导公共宽壁中心圆孔，架构批 W3-A 席，R2 空白域 G5）。

出处（原文口径+教科书二级转引，详见下节物理口径）：
- bethe_hole_coupler：Bethe 小孔极化率 αe=2r³/3、αm=4r³/3（H. A.
  Bethe 零厚无限屏原文口径）；耦合/方向性闭式与 M/E 比=2(β/k0)²
  （Pozar, Microwave Engineering §7.9 同族二级转引/结构锚 USPAS
  Nassiri 2003、Microwaves101 directional couplers 条目）；Cohn 有限
  壁厚修正（孔口共振增强+截止波导衰减，Collin, Foundations for
  Microwave Engineering 截止波导节）。

单键 bethe_hole_coupler 双向口径（分析/综合由入参自动分派）：
- 分析：给孔径 → 耦合度/方向性/隔离；
- 综合：给目标耦合度 → 孔径（反解三次式）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
几何：两个相同矩形波导共宽壁，圆孔位于宽壁中线（offset s=a/2，H_z=0，
只有法向 E_y 与切向 H_x 耦合）；TE10 激励。

- Bethe 小孔极化率（零厚无限屏）：αe=2r³/3、αm=4r³/3（H. A. Bethe,
  "Theory of Diffraction by Small Holes", Phys. Rev. 66:66, 1944；
  与 core/aperture_coupling.bethe_polarizability_circle 同源单源消费）。
- 耦合幅值（功率归一化模反应式；E 项=电偶极支路 ε0αe·Z10，M 项=磁偶极
  支路 μ0αm/Z10，两项同量纲 s·m²（prefactor 2ω/(ab)=1/(s·m²)，乘积
  无量纲幅值比）已核实）：

      |c_耦合| = (2ω/(ab))·(ε0αe·Z10 + μ0αm/Z10)    （E、M 同相相加）
      |c_隔离| = (2ω/(ab))·|ε0αe·Z10 − μ0αm/Z10|    （反相相消）

  M/E 比 = (αm/αe)·(η0/Z10)² = 2(β/k0)²：f = c0/(√2·a)（λg=2a）时隔离
  向严格相消 → 单孔方向性无究大（设计频率）；偏离设计频率方向性按
  D=20lg[(E+M)/|E−M|] 退化（窄带单孔特性）。反向（backward-wave/
  reverse）耦合器口径（Bethe 符号约定 m=−αmH_t 下反应式符号结构；
  Microwaves101 directional couplers 条目定性一致）。
- Cohn 有限壁厚修正（wall_thickness_mm>0 时启用，近似层级如实声明）：
  ①孔口共振增强因子 R=1/(1−(f/f_res)²)，f_res 取对应圆波导截止常数
  口径——磁耦合 f_res,m=c0/(1.706·d)（TE11 型）、电耦合 f_res,e=
  c0/(1.305·d)（TM01 型）（圆波导截止恒等式 λc=κ·d，教科书常数；κ
  系数层级为 Cohn 类修正的常用工程近似）；②孔颈按截止圆波导衰减
  exp(−α_cut·t)，α_cut=(2π/λ_res)·√(1−(f/f_res)²)（截止波导衰减通式，
  Collin, Foundations for Microwave Engineering 截止波导节）。
- 近似层级：一阶小孔（d≪λ0、d≪宽壁尺寸）、单 TE10 模、弱耦合
  （|c|≪1，不迭代加载修正）、无孔间互耦（多孔阵口径只给 λg/4 间距）。

守卫（全部显式拒绝不外推）：
- f ≤ fc10 或 f/fc < 1.05（截止附近 λg 发散，Bethe 场系数失真）；
- 孔径 d≤0（非物理）、d>0.8·b（窄边比例上限守卫，任务书钉）、
  d>λ0/3（小孔假设 d≪λ0）；
- 综合：目标耦合度在可达窗（d∈(0,d_max] 映射 C∈[C(d_max),∞)）外显式
  报错并列可达界；Cohn 域 f≥0.9·f_res,m 显式拒绝（共振因子发散）；
- 波导型号未知名（wr_lookup KeyError）与 a/b 非正有限显式拒绝。

数值锚（#118 独立来源）：WR-90 @10 GHz、d=6mm 零壁厚 → 耦合 20~21 dB
量级（X 波段单孔耦合文献典型带 20~30 dB，任务书指定锚）；f=c0/(√2·a)
设计频率方向性→无究大（E/M 平衡的独立物理不变量）；d→d·2^(1/3) 耦合
精确 +6.02 dB（c∝d³ 闭式自洽）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator

_C0 = 299792458.0  # m/s（SI 定义值；与 core/rw_tables.C0 同值）
_ETA0 = 376.730313668  # 真空波阻抗 Ω（√(μ0/ε0)）
_EPS0 = 8.8541878128e-12  # 真空介电常数 F/m（SI 2019）
_MU0 = 1.25663706212e-6  # 真空磁导率 H/m（SI 2019 实测值）

# 圆波导截止常数（λc=κ·d）：TE11 型（磁耦合共振口径）/ TM01 型（电耦合）
_COHN_KAPPA_M = 1.706
_COHN_KAPPA_E = 1.305

# 守卫常量
_F_OVER_FC_MIN = 1.05  # 截止附近显式拒绝下界（λg 发散带）
_D_OVER_B_MAX = 0.8  # 孔径/窄边比例上限（小孔假设 r≪b，任务书守卫）
_D_OVER_LAMBDA0_MAX = 1.0 / 3.0  # 孔径/自由空间波长上限（小孔假设 d≪λ0）
_COHN_F_RES_GUARD = 0.9  # f≥0.9·f_res,m 时 Cohn 修正域外拒绝


def _bethe_amplitude_coeffs(
    a_mm: float, b_mm: float, freq_ghz: float, diameter_mm: float,
    wall_thickness_mm: float,
) -> dict[str, Any]:
    """Bethe+Cohn 耦合幅值链公共核（分析/综合共用）。

    返回 c_strong/c_iso（线性幅值，无量纲别名比）、λg/Z10、E/M 支路与
    Cohn 修正因子表（供输出与测试审计）。
    """
    a_m = a_mm * 1e-3
    b_m = b_mm * 1e-3
    d_m = diameter_mm * 1e-3
    f_hz = freq_ghz * 1e9
    fc_hz = _C0 / (2.0 * a_m)
    if f_hz < _F_OVER_FC_MIN * fc_hz:
        raise ValueError(
            f"bethe_hole_coupler: f={freq_ghz:g} GHz 距 TE10 截止 "
            f"{fc_hz / 1e9:.4f} GHz 不足 {_F_OVER_FC_MIN:g}×（截止附近 λg "
            "发散，Bethe 场系数失真，显式拒绝）")
    lam0_m = _C0 / f_hz
    ratio = fc_hz / f_hz
    lam_g_m = lam0_m / math.sqrt(1.0 - ratio * ratio)
    z10 = _ETA0 * lam_g_m / lam0_m
    omega = 2.0 * math.pi * f_hz

    r_m = d_m / 2.0
    if not (math.isfinite(r_m) and r_m > 0.0):
        raise ValueError(
            f"bethe_hole_coupler: hole_diameter_mm 必须为正有限数，"
            f"得到 {diameter_mm!r}")
    # Bethe 极化率单源消费（core/aperture_coupling，Bethe 1944 同值）
    from rfauto.core.aperture_coupling import bethe_polarizability_circle

    pol = bethe_polarizability_circle(r_m)
    alpha_e = pol["alpha_e_m3"]
    alpha_m = pol["alpha_mx_m3"]

    # Cohn 修正（有限壁厚；t=0 → 纯 Bethe 零厚口径）
    cohn: dict[str, Any] = {"applied": bool(wall_thickness_mm > 0.0)}
    f_res_m = _C0 / (_COHN_KAPPA_M * d_m)
    f_res_e = _C0 / (_COHN_KAPPA_E * d_m)
    if wall_thickness_mm > 0.0:
        if f_hz >= _COHN_F_RES_GUARD * f_res_m:
            raise ValueError(
                f"bethe_hole_coupler: f={freq_ghz:g} GHz 已进入孔口共振带"
                f"（f≥{_COHN_F_RES_GUARD:g}·f_res,m={f_res_m / 1e9:.4g} GHz，"
                "小孔假设与 Cohn 修正同时失效，显式拒绝）")
        gain_m = 1.0 / (1.0 - (f_hz / f_res_m) ** 2)
        gain_e = 1.0 / (1.0 - (f_hz / f_res_e) ** 2)
        t_m = wall_thickness_mm * 1e-3
        lam_res_m = _C0 / f_res_m
        lam_res_e = _C0 / f_res_e
        att_m = math.exp(-(2.0 * math.pi / lam_res_m)
                         * math.sqrt(1.0 - (f_hz / f_res_m) ** 2) * t_m)
        att_e = math.exp(-(2.0 * math.pi / lam_res_e)
                         * math.sqrt(1.0 - (f_hz / f_res_e) ** 2) * t_m)
        cohn.update({
            "f_res_m_ghz": round(f_res_m / 1e9, 6),
            "f_res_e_ghz": round(f_res_e / 1e9, 6),
            "resonance_factor_m": round(gain_m, 6),
            "resonance_factor_e": round(gain_e, 6),
            "thickness_att_m": round(att_m, 6),
            "thickness_att_e": round(att_e, 6),
            "kappa_m": _COHN_KAPPA_M,
            "kappa_e": _COHN_KAPPA_E,
        })
        gain_m *= att_m
        gain_e *= att_e
    else:
        gain_m = 1.0
        gain_e = 1.0

    term_e = _EPS0 * alpha_e * z10 * gain_e  # 电偶极支路（s·m² 量纲）
    term_m = _MU0 * alpha_m / z10 * gain_m  # 磁偶极支路（s·m² 量纲）
    prefactor = 2.0 * omega / (a_m * b_m)  # 1/(s·m²) → 与支路相乘无量纲
    c_strong = prefactor * (term_e + term_m)  # 耦合（相加）方向幅值
    c_iso = prefactor * abs(term_e - term_m)  # 隔离（相消）方向幅值

    return {
        "c_strong": c_strong,
        "c_iso": c_iso,
        "term_e": term_e,
        "term_m": term_m,
        "prefactor": prefactor,
        "z10_ohm": z10,
        "lam0_mm": lam0_m * 1e3,
        "lam_g_mm": lam_g_m * 1e3,
        "fc10_ghz": fc_hz / 1e9,
        "f_design_ghz": _C0 / (math.sqrt(2.0) * a_m) / 1e9,
        "cohn": cohn,
    }


def _resolve_waveguide(wr_name: str | None, a_mm: float | None,
                       b_mm: float | None) -> tuple[float, float, str | None]:
    """波导尺寸解析：wr_name 走 rw_tables 单源，或显式 a/b；二者恰居其一。"""
    if wr_name is not None and (a_mm is not None or b_mm is not None):
        raise ValueError(
            "bethe_hole_coupler: wr_name 与 a_mm/b_mm 只能二选一"
            "（避免口径冲突）")
    if wr_name is not None:
        from rfauto.core.rw_tables import wr_lookup

        rec = wr_lookup(wr_name)
        return rec.a_mm, rec.b_mm, rec.wr_name
    if a_mm is None or b_mm is None:
        raise ValueError(
            "bethe_hole_coupler: 须给 wr_name（WR 型号，rw_tables 单源）"
            "或同时给 a_mm/b_mm（显式宽窄边）")
    a = float(a_mm)
    b = float(b_mm)
    if not (math.isfinite(a) and a > 0.0 and math.isfinite(b) and b > 0.0):
        raise ValueError(
            f"bethe_hole_coupler: a_mm/b_mm 必须为正有限数，"
            f"得到 a={a_mm!r}, b={b_mm!r}")
    return a, b, None


def _check_hole_bounds(diameter_mm: float, b_mm: float,
                       lam0_mm: float) -> None:
    """孔径物理守卫（小孔假设双上限 + 正性）。"""
    d = float(diameter_mm)
    if not (math.isfinite(d) and d > 0.0):
        raise ValueError(
            f"bethe_hole_coupler: hole_diameter_mm 必须为正有限数，"
            f"得到 {diameter_mm!r}")
    if d > _D_OVER_B_MAX * b_mm:
        raise ValueError(
            f"bethe_hole_coupler: 孔径 d={d:.4g}mm 超出窄边比例上限 "
            f"{_D_OVER_B_MAX:g}·b={_D_OVER_B_MAX * b_mm:.4g}mm"
            "（小孔假设 r≪b，任务书守卫）")
    if d > _D_OVER_LAMBDA0_MAX * lam0_mm:
        raise ValueError(
            f"bethe_hole_coupler: 孔径 d={d:.4g}mm 超出小孔假设上限 "
            f"λ0/{1.0 / _D_OVER_LAMBDA0_MAX:g}="
            f"{_D_OVER_LAMBDA0_MAX * lam0_mm:.4g}mm（Bethe 一阶小孔要求 d≪λ0）")


@register_calculator(
    "bethe_hole_coupler",
    "Bethe孔耦合器：Bethe 孔定向耦合器（矩形波导公共宽壁中心圆孔，双向单键）："
    "①分析——给孔径 hole_diameter_mm → 耦合度/方向性/隔离/设计频率"
    "（Bethe 极化率 αe=2r³/3、αm=4r³/3 + E/M 支路 Z10 加减结构，"
    "f=c0/(√2·a) 处隔离向严格相消=方向性极值；反向 reverse 耦合器）；"
    "②综合——给目标 coupling_db → 反解孔径（c∝d³）并回代自洽。"
    "wall_thickness_mm>0 启用 Cohn 修正（孔口共振因子 1/(1−(f/f_res)²)"
    "+截止衰减 e^(−αt)，f_res 取圆波导 TE11/TM01 截止常数 1.706d/1.305d"
    "口径）。守卫：f 距 TE10 截止 <5% 拒绝（λg 发散）；d≤0.8b 且 d≤λ0/3"
    "（小孔假设）；耦合度越可达窗显式报错。孔位输出=宽壁中线 s=a/2 + "
    "多孔阵 λg/4 间距口径。近似层级：一阶小孔/单模/弱耦合。",
    (("wr_name", "str - WR 波导型号（如 'WR-90'，rw_tables 单源；与 "
      "a_mm/b_mm 二选一）"),
     ("a_mm", "float mm 宽边内尺寸（显式口径，须与 b_mm 同给）"),
     ("b_mm", "float mm 窄边内尺寸"),
     ("freq_ghz", "float GHz 中心频率"),
     ("hole_diameter_mm", "float mm 圆孔直径（分析方向入参）"),
     ("coupling_db", "float dB 目标耦合度（综合方向入参，正 dB）"),
     ("wall_thickness_mm", "float mm 公共壁厚（>0 启用 Cohn 修正，缺省 0）")),
    required=("freq_ghz",),
)
def bethe_hole_coupler(
    freq_ghz: float,
    wr_name: str | None = None,
    a_mm: float | None = None,
    b_mm: float | None = None,
    hole_diameter_mm: float | None = None,
    coupling_db: float | None = None,
    wall_thickness_mm: float = 0.0,
) -> dict[str, Any]:
    f_ghz = float(freq_ghz)
    if not (math.isfinite(f_ghz) and f_ghz > 0.0):
        raise ValueError(
            f"bethe_hole_coupler: freq_ghz 必须为正有限数，得到 {freq_ghz!r}")
    if hole_diameter_mm is not None and coupling_db is not None:
        raise ValueError(
            "bethe_hole_coupler: hole_diameter_mm（分析）与 coupling_db"
            "（综合）只能给其一")
    if hole_diameter_mm is None and coupling_db is None:
        raise ValueError(
            "bethe_hole_coupler: 须给 hole_diameter_mm（分析口径）或 "
            "coupling_db（综合口径）之一")
    t_mm = float(wall_thickness_mm)
    if not (math.isfinite(t_mm) and t_mm >= 0.0):
        raise ValueError(
            f"bethe_hole_coupler: wall_thickness_mm 必须为非负有限数，"
            f"得到 {wall_thickness_mm!r}")

    a_wg, b_wg, wr_used = _resolve_waveguide(wr_name, a_mm, b_mm)

    fc_hz = _C0 / (2.0 * a_wg * 1e-3)
    if f_ghz * 1e9 < _F_OVER_FC_MIN * fc_hz:
        raise ValueError(
            f"bethe_hole_coupler: f={f_ghz:g} GHz 距 TE10 截止 "
            f"{fc_hz / 1e9:.4f} GHz 不足 {_F_OVER_FC_MIN:g}×（截止附近 λg "
            "发散，显式拒绝）")
    lam0_mm = C_MM_GHZ / f_ghz
    d_max = min(_D_OVER_B_MAX * b_wg, _D_OVER_LAMBDA0_MAX * lam0_mm)

    if hole_diameter_mm is not None:
        # ── 分析方向：孔径 → 耦合度 ────────────────────────────────
        d_mm = float(hole_diameter_mm)
        _check_hole_bounds(d_mm, b_wg, lam0_mm)
        core = _bethe_amplitude_coeffs(a_wg, b_wg, f_ghz, d_mm, t_mm)
        roundtrip_mm: float | None = None
        mode = "analysis"
    else:
        # ── 综合方向：目标耦合度 → 孔径 ────────────────────────────
        c_target = float(coupling_db)
        if not (math.isfinite(c_target) and c_target > 0.0):
            raise ValueError(
                f"bethe_hole_coupler: coupling_db 必须为正有限 dB 数，"
                f"得到 {coupling_db!r}")
        # 可达窗：d_max → 最强耦合（最低 C_db）；|c| = A·r³ 随 d 单调升
        core_max = _bethe_amplitude_coeffs(a_wg, b_wg, f_ghz, d_max, t_mm)
        c_at_dmax = core_max["c_strong"]
        if c_at_dmax >= 1.0:
            raise ValueError(
                "bethe_hole_coupler: 可达域上界处一阶弱耦合口径已失效"
                f"（|c(d_max)|={c_at_dmax:.4g}≥1）")
        c_min_db = -20.0 * math.log10(c_at_dmax)
        if c_target < c_min_db:
            raise ValueError(
                f"bethe_hole_coupler: 目标耦合度 {c_target:.4g} dB 不可达"
                f"（孔径上限 d_max={d_max:.4g}mm 下最强耦合 "
                f"{c_min_db:.4g} dB；更强耦合需多孔阵或多节口径）")
        # 反解：|c| = A_d·d³（A_d=c(d_max)/d_max³，1/m³，d 计米）→ d=(c/A_d)^(1/3)
        amp_per_m3 = c_at_dmax / (d_max * 1e-3) ** 3
        d_mm = 1.0e3 * (10.0 ** (-c_target / 20.0) / amp_per_m3) ** (1.0 / 3.0)
        core = _bethe_amplitude_coeffs(a_wg, b_wg, f_ghz, d_mm, t_mm)
        if abs(-20.0 * math.log10(core["c_strong"]) - c_target) > 1e-6:
            raise ValueError(
                "bethe_hole_coupler: 综合回代自洽失败"
                f"（目标 {c_target:.6f} dB，回代 "
                f"{-20.0 * math.log10(core['c_strong']):.6f} dB）")
        roundtrip_mm = round(d_mm, 6)
        mode = "synthesis"

    c_strong = core["c_strong"]
    c_iso = core["c_iso"]
    if c_strong >= 1.0:
        raise ValueError(
            f"bethe_hole_coupler: 耦合幅值 |c|={c_strong:.4g}≥1（弱耦合"
            "一阶口径失效，孔过大或频率过低）")
    coupling_val = -20.0 * math.log10(c_strong)
    directivity_val = (20.0 * math.log10(c_strong / c_iso)
                       if c_iso > 0.0 else None)

    return {
        "mode": mode,
        "wr_name": wr_used,
        "a_mm": round(a_wg, 4),
        "b_mm": round(b_wg, 4),
        "freq_ghz": round(f_ghz, 6),
        "fc10_ghz": round(core["fc10_ghz"], 6),
        "f_over_fc": round(f_ghz / core["fc10_ghz"], 6),
        "lambda0_mm": round(core["lam0_mm"], 4),
        "lambda_g_mm": round(core["lam_g_mm"], 4),
        "z10_ohm": round(core["z10_ohm"], 3),
        "hole_diameter_mm": round(d_mm, 6),
        "hole_radius_mm": round(d_mm / 2.0, 6),
        "hole_offset_s_mm": round(a_wg / 2.0, 4),
        "hole_position_note": "宽壁中线（s=a/2，H_z=0）；多孔阵相邻孔距取 λg/4",
        "hole_spacing_lambda_g_quarter_mm": round(core["lam_g_mm"] / 4.0, 4),
        "coupling_db": round(coupling_val, 6),
        "directivity_db": (round(directivity_val, 6)
                           if directivity_val is not None else None),
        "isolation_db": (round(coupling_val + directivity_val, 6)
                         if directivity_val is not None else None),
        "f_design_ghz": round(core["f_design_ghz"], 6),
        "f_design_note": "f=c0/(√2·a) 时 E/M 隔离向严格相消，单孔方向性无究大",
        "coupler_sense": "reverse (backward-wave)",
        "c_strong": round(c_strong, 12),
        "c_iso": round(c_iso, 12),
        "cohn": core["cohn"],
        "wall_thickness_mm": round(t_mm, 6),
        "roundtrip_diameter_mm": roundtrip_mm,
        "approx_level": ("一阶小孔（d≪λ0、d≪宽壁）+单 TE10 模+弱耦合；"
                         + ("Bethe+Cohn 有限壁厚修正"
                            if t_mm > 0.0 else "零壁厚纯 Bethe 口径")),
        "source": ("Bethe 1944 Phys.Rev.66:66; Cohn 修正圆波导截止常数口径; "
                   "结构锚 USPAS Nassiri 2003（Pozar §7.9 复现）/Microwaves101"),
    }
