"""雷达目标 RCS 闭式件族（aurora72 A4-B 席域 1，R7 第二梯队 T9=G10）。

两键：rcs_sphere_mie（金属球精确 Mie 级数后向散射 RCS + Rayleigh/Mie/
光学三区判据） / rcs_peak_canonical（典型目标峰值 RCS 库：平板法向/
二面角/三方角反射器/圆柱侧向，全部教科书闭式）。

与既有雷达面的边界（语义防撞，R7 §② G10 三重搜索证据）
--------------------------------------------------------
- radar_eq.radar_range_equation = 雷达方程（σ 是**输入参数**，docstring
  自证只出 Swerling 0 主方程）；本族是 σ 的**目标侧供给端**（闭式库），
  向 radar_range_equation 供 σ。
- isac_ambiguity = 分辨率/模糊函数面；rfid = 标签反向散射（RCS 是标签
  参数非目标库）；本族只做**经典目标件**。
- `mie|sphere_rcs` 全仓 grep 仅 ridged_waveguide "Jamieson" 误命中
  （R7 证据）——本族是仓内首个目标 RCS 键。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 金属球后向散射精确 Mie 级数（PEC 球，Skolnik *Introduction to Radar
  Systems* 球 RCS 一节 / Ruck *Radar Cross Section Handbook* 口径）：
  尺寸参数 ρ=ka=2πa/λ，Riccati-Bessel ψ_n=ρ·j_n(ρ)、χ_n=−ρ·y_n(ρ)、
  ξ_n=ψ_n−j·χ_n（第二类 Hankel 径函数），PEC 球 Mie 系数

      a_n = −ψ'_n(ρ)/ξ'_n(ρ)，b_n = −ψ_n(ρ)/ξ_n(ρ)

  后向散射幅度和 S_b=Σ_{n=1}^{N} (−1)^n (2n+1)(a_n−b_n)，截面

      σ = (πa²/ρ²)·|S_b|²

  项数取 Wiscombe 截断 N=max(int(ρ+4.05·ρ^{1/3})+8, 8)。双解析极限
  锚（独立于级数实现）：Rayleigh 区（ρ≪1）σ→9πa²(ka)⁴（f⁴ 标度）；
  光学区（ρ≫1）σ→πa²（消光佯谬后向版，级数解围绕 πa² 振荡收敛）。
- 三区判据（工程惯例带，docstring 写死）：ka<0.5=rayleigh；
  0.5≤ka≤10=mie（过渡/谐振区，截面振荡非单调）；ka>10=optical。
- 峰值 RCS 闭式库（Skolnik 教科书表 + Knott-Shaeffer-Tuley 口径）：

      平板（法向）        σ = 4πA²/λ²            A=a·b（投影面积）
      二面角（90°，棱向） σ = 8πa²b²/λ²          （双跳变路等效孔径
                            √2·a·b=两侧板 45° 投影之和；a=b 时恰为同
                            单面面积平板的 2 倍，测试钉结构恒等）
      三方角反射器（方形） σ = 4πa⁴/(3λ²)         （等效孔径 a²/√3）
      圆柱（侧向正交）    σ = 2πL²r/λ            （λ⁻¹ 标度，与板族
                            λ⁻² 标度不同=结构钉）

  dBsm 换算恒等：dBsm = 10·log10(σ/m²)。三角三方角/圆锥尖顶/圆盘
  斜入射姿态项不在 v1 口径（常数源无法双源钉死，如实不做）。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- 球：Rayleigh 闭式与光学 πa² 双极限 in-output rel_dev 字段（窗内
  ≤2e-3 / ≤0.15 dB 实测）；f⁴ 标度逐点钉（ρ=0.02×2 → 比值 16±3.6e-3
  高阶项实测）；测试侧独立 Mie 实现（对数导数 D_n=ψ'/ψ 降序递推路线，
  与本键 scipy 球 Bessel 直算不同路线）四点 ρ 互证 ≤1e-9。
- 峰值库：全部闭式测试侧独立重算；λ⁻²/λ⁻¹ 双标度钉；二面角=2×平板
  （同单面面积）与三方角等效孔径 a²/√3 回代平板式两结构恒等。

守卫：radius_mm>0、f_ghz>0、ka∈[1e-3,200]（级数数值稳定域，越域显式
拒绝）；shape ∈ 封闭集合；各尺寸 >0（平板/二面角 a,b 同给，三方角只
a，圆柱 a=半径 b=长）；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

# 三区判据带（工程惯例，docstring 写死）
_RAYLEIGH_KA_MAX = 0.5
_OPTICAL_KA_MIN = 10.0
# Mie 级数数值稳定域（χ_n 上行递推幅度 ~ 1/ρ^{n+1}，ρ 过小溢出）
_KA_MIN, _KA_MAX = 1.0e-3, 200.0

_SOURCES = {
    "sphere": "Skolnik Introduction to Radar Systems 球 RCS（Mie 级数 PEC 球口径；"
              "Rayleigh 9πa²(ka)⁴ 与光学 πa² 双极限）；Wiscombe 截断 N=ρ+4.05ρ^{1/3}",
    "peak": "Skolnik 教科书峰值 RCS 表 + Knott-Shaeffer-Tuley 口径：平板 4πA²/λ²、"
            "二面角 8πa²b²/λ²、方形三方角 4πa⁴/3λ²、圆柱侧向 2πL²r/λ",
}

_PEAK_SHAPES = ("flat_plate", "dihedral", "square_trihedral",
                "cylinder_broadside")


def _sigma_sphere(rho: float) -> tuple[float, int]:
    """PEC 球后向散射 σ/πa² 的精确 Mie 级数（ρ=ka）→（效率，项数）。

    对 ρ=ka 归一效率 = |S_b|²/ρ²（σ = πa²·效率）；scipy 球 Bessel 直算
    路线（导数=球 Bessel 导数组合 ψ'=j_n+ρj'_n）。
    """
    n_max = max(int(rho + 4.05 * rho ** (1.0 / 3.0)) + 8, 8)
    from scipy.special import spherical_jn, spherical_yn  # 数值裁判惰性依赖

    psi = [rho * spherical_jn(n, rho) for n in range(1, n_max + 1)]
    psi_d = [spherical_jn(n, rho) + rho * spherical_jn(n, rho, derivative=True)
             for n in range(1, n_max + 1)]
    chi = [-rho * spherical_yn(n, rho) for n in range(1, n_max + 1)]
    chi_d = [-spherical_yn(n, rho) - rho * spherical_yn(n, rho, derivative=True)
             for n in range(1, n_max + 1)]
    s_b = 0.0 + 0j
    for n in range(n_max):
        sign = (-1.0) ** (n + 1)
        xi = psi[n] - 1j * chi[n]
        xi_d = psi_d[n] - 1j * chi_d[n]
        a_n = -psi_d[n] / xi_d
        b_n = -psi[n] / xi
        s_b += sign * (2 * (n + 1) + 1) * (a_n - b_n)
    # 显式收敛为 Python float（scipy 球 Bessel 返回 numpy 标量——service
    # 出口契约要求纯 JSON 类型，np.float64 直出会被 json.dumps 拒绝）
    return float(abs(s_b) ** 2) / rho ** 2, n_max


# ─── 键 1：金属球三区精确 RCS ────────────────────────────────────────────────

@register_calculator(
    "rcs_sphere_mie",
    "金属球 RCS 三区精确解：PEC 球后向散射 Mie 级数 σ=(πa²/ρ²)·|Σ(−1)^n·"
    "(2n+1)(a_n−b_n)|²（ρ=ka，Wiscombe 截断），输出 σ/dBsm+ka+三区判据"
    "（rayleigh ka<0.5 / mie 0.5–10 振荡过渡 / optical ka>10）+ 双解析极限"
    "自证字段（Rayleigh 9πa²(ka)⁴ 与光学 πa² 的 rel_dev，级数双极限锚）；"
    "Rayleigh 窗 f⁴ 标度逐点可钉。锚：ka=0.02 极限偏差 ≤1e-4；ka=30 偏差"
    "≤0.1dB；测试侧对数导数路线独立实现互证 ≤1e-9",
    (("radius_mm", "float mm 金属球半径 a（>0）"),
     ("f_ghz", "float GHz 雷达频率（>0；ka=2πa/λ 决定三区归属）")),
    required=("radius_mm", "f_ghz"),
)
def rcs_sphere_mie(radius_mm: float, f_ghz: float) -> dict[str, Any]:
    a = _finite(radius_mm, "radius_mm")
    f = _finite(f_ghz, "f_ghz")
    if a <= 0.0:
        raise ValueError(f"rcs_sphere_mie: radius_mm 必须 >0，得到 {radius_mm!r}")
    if f <= 0.0:
        raise ValueError(f"rcs_sphere_mie: f_ghz 必须 >0，得到 {f_ghz!r}")
    wavelength_mm = C_MM_GHZ / f
    a_m = a * 1e-3
    wavelength_m = wavelength_mm * 1e-3
    k = 2.0 * math.pi / wavelength_m
    ka = k * a_m
    if not _KA_MIN <= ka <= _KA_MAX:
        raise ValueError(
            f"rcs_sphere_mie: 尺寸参数 ka={ka:.6g} 超出级数稳定域 "
            f"[{_KA_MIN},{_KA_MAX}]（调 radius_mm/f_ghz 组合），显式拒绝")
    eff, n_terms = _sigma_sphere(ka)
    sigma_m2 = math.pi * a_m * a_m * eff
    sigma_dbsm = 10.0 * math.log10(sigma_m2)
    rayleigh_m2 = 9.0 * math.pi * a_m * a_m * ka ** 4
    optical_m2 = math.pi * a_m * a_m
    rayleigh_rel_dev = (sigma_m2 - rayleigh_m2) / rayleigh_m2
    optical_dev_db = 10.0 * math.log10(sigma_m2 / optical_m2)
    if ka < _RAYLEIGH_KA_MAX:
        region = "rayleigh"
    elif ka <= _OPTICAL_KA_MIN:
        region = "mie"
    else:
        region = "optical"
    if region == "rayleigh":
        note = (
            "Rayleigh 区（ka<0.5）：σ≈9πa²(ka)⁴（f⁴ 标度）；rayleigh_rel_dev "
            "为高阶项偏差（ka≤0.1 时 ≤2e-3 实测），随 ka 增大单调偏离")
    elif region == "mie":
        note = (
            "Mie 过渡区（0.5≤ka≤10）：截面围绕 πa² 强振荡（谐振瓣），单频点"
            "值对 ka 极敏感——姿/频扫描判读须以包络而非单点下结论")
    else:
        note = (
            "光学区（ka>10）：σ→πa²（消光佯谬后向版），optical_dev_db 为级数"
            "振荡残差（ka≥20 时 |偏差|≤0.15dB 实测，随 ka 增大收敛）")
    return {
        "radius_mm": a,
        "f_ghz": f,
        "wavelength_mm": round(wavelength_mm, 12),
        "ka": round(ka, 12),
        "region": region,
        # m² 量纲跨 1e-15..1e3 十八个量级——定点舍入会毁小量程有效位
        # （1e-12 量级 round(·,15) 只剩 3 位），截面原值不取舍、判读走
        # dBsm 字段（round 12）
        "sigma_m2": float(sigma_m2),
        "sigma_dbsm": round(sigma_dbsm, 12),
        "n_terms": n_terms,
        "rayleigh_closed_form_m2": float(rayleigh_m2),
        "rayleigh_rel_dev": round(rayleigh_rel_dev, 15),
        "optical_m2": float(optical_m2),
        "optical_dev_db": round(optical_dev_db, 12),
        "note": note,
        "source": _SOURCES["sphere"],
    }


# ─── 键 2：典型目标峰值 RCS 库 ───────────────────────────────────────────────

@register_calculator(
    "rcs_peak_canonical",
    "典型目标峰值 RCS 库：平板法向 σ=4πA²/λ²（A=a·b）/二面角 90° "
    "σ=8πa²b²/λ²（双跳变等效孔径 √2·ab）/方形三方"
    "角 σ=4πa⁴/(3λ²)（等效孔径 a²/√3）/圆柱侧向 σ=2πL²r/λ（λ⁻¹ 标度）"
    "——姿态=峰值口径（各形状最大方向），不建姿态方向图。锚：全闭式测试"
    "侧独立重算；板族 λ⁻² 与圆柱 λ⁻¹ 双标度钉；二面角(a=b)=2×同单面平板、"
    "三方角按 a²/√3 回代平板式两结构恒等；1m² 平板@10GHz=41.45dBsm 常数",
    (("shape", "str 形状 'flat_plate'|'dihedral'|'square_trihedral'|"
      "'cylinder_broadside'（封闭集合）"),
     ("f_ghz", "float GHz 雷达频率（>0）"),
     ("a_mm", "float mm 主尺寸：平板/二面角=边 a；三方角=边长；圆柱=半径 r"
      "（>0）"),
     ("b_mm", "float mm 次尺寸：平板/二面角=边 b；圆柱=长度 L（>0；三方角"
      "不给）")),
    required=("shape", "f_ghz", "a_mm"),
)
def rcs_peak_canonical(shape: str, f_ghz: float, a_mm: float,
                       b_mm: float | None = None) -> dict[str, Any]:
    if shape not in _PEAK_SHAPES:
        raise ValueError(
            f"rcs_peak_canonical: shape 须 {'|'.join(_PEAK_SHAPES)}，"
            f"得到 {shape!r}")
    f = _finite(f_ghz, "f_ghz")
    if f <= 0.0:
        raise ValueError(f"rcs_peak_canonical: f_ghz 必须 >0，得到 {f_ghz!r}")
    a = _finite(a_mm, "a_mm")
    if a <= 0.0:
        raise ValueError(f"rcs_peak_canonical: a_mm 必须 >0，得到 {a_mm!r}")
    a_m = a * 1e-3
    wavelength_m = (C_MM_GHZ / f) * 1e-3
    b_val: float | None = None
    if shape in ("flat_plate", "dihedral", "cylinder_broadside"):
        if b_mm is None:
            raise ValueError(
                f"rcs_peak_canonical: shape={shape} 需要 b_mm（第二边/长度）")
        b_val = _finite(b_mm, "b_mm")
        if b_val <= 0.0:
            raise ValueError(
                f"rcs_peak_canonical: b_mm 必须 >0，得到 {b_mm!r}")
        b_m = b_val * 1e-3
    else:
        if b_mm is not None:
            raise ValueError(
                "rcs_peak_canonical: square_trihedral 只取边长 a_mm，不接受 "
                f"b_mm（同给显式拒绝），得到 {b_mm!r}")
        b_m = None

    area_eff_m2: float | None = None
    if shape == "flat_plate":
        area_m2 = a_m * b_m
        area_eff_m2 = area_m2
        sigma_m2 = 4.0 * math.pi * area_m2 ** 2 / wavelength_m ** 2
        formula = "σ=4π(ab)²/λ²（PO 法向，A=ab）"
    elif shape == "dihedral":
        # 8πa²b²/λ² ≡ 4π(√2·ab)²/λ²（等效孔径 √2·ab=两板 45° 投影之和）
        area_eff_m2 = math.sqrt(2.0) * a_m * b_m
        sigma_m2 = 8.0 * math.pi * (a_m * b_m) ** 2 / wavelength_m ** 2
        formula = "σ=8πa²b²/λ²（90° 双跳变，等效孔径 √2·ab）"
    elif shape == "square_trihedral":
        # 4πa⁴/(3λ²) ≡ 4π(a²/√3)²/λ²（等效孔径 a²/√3）
        area_eff_m2 = a_m * a_m / math.sqrt(3.0)
        sigma_m2 = 4.0 * math.pi * a_m ** 4 / (3.0 * wavelength_m ** 2)
        formula = "σ=4πa⁴/(3λ²)（方形三方角，等效孔径 a²/√3）"
    else:  # cylinder_broadside
        sigma_m2 = 2.0 * math.pi * b_m ** 2 * a_m / wavelength_m
        formula = "σ=2πL²r/λ（圆柱侧向正交，L=b_mm、r=a_mm）"
    sigma_dbsm = 10.0 * math.log10(sigma_m2)
    note = (
        "峰值口径（各形状最大散射方向的单频点截面），不建姿态方向图；"
        "二面角=棱垂直极化的经典峰值（双跳变路），三方角=对称轴入射；"
        "三角三方角/圆锥尖顶/有限厚度与边缘绕射修正如实不在 v1 口径")
    return {
        "shape": shape,
        "f_ghz": f,
        "wavelength_mm": round(C_MM_GHZ / f, 12),
        "a_mm": a,
        "b_mm": b_val,
        "sigma_m2": float(sigma_m2),
        "sigma_dbsm": round(sigma_dbsm, 12),
        "effective_aperture_m2": (
            None if area_eff_m2 is None else float(area_eff_m2)),
        "formula": formula,
        "note": note,
        "source": _SOURCES["peak"],
    }
