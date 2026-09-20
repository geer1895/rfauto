r"""导体损耗口径：表面粗糙度（Huray / Hammerstad）+ 电镀厚度。

本模块把「导体损耗」拆成三个**可复现、可对照**的确定性因子，全部为纯
numpy/math 标量运算，不引求解器、不联网、不加新依赖::

    Rs_eff = Rs_smooth(f, sigma) * K_rough(delta) * K_thick(t, delta)

1) 光滑铜（半无限厚）表面电阻（与既有皮肤深度口径一致）::

       delta      = sqrt(2 / (omega * mu0 * mu_r * sigma))
       Rs_smooth  = 1 / (sigma * delta) = sqrt(omega * mu0 * mu_r / (2 * sigma))

   来源：D. M. Pozar, Microwave Engineering, 4th ed., §1.7.1（趋肤深度与表面
   电阻）。MU0 = 1.25663706212e-6 H/m（CODATA 2018 / NIST），与
   core/loss_density.py 的 MU0、core/thermal_iteration.surface_resistance
   同口径。

2) **Huray 雪球模型（Hall-Huray 口径）** —— 把粗糙面看成「哑光基底 + 球形铜瘤
   (nodule) 铺排」，粗糙度增益因子 [1][2][3]::

       K_HH = A_matte/A_flat + (3/2) * sum_i  f_i / (1 + delta/r_i + delta^2/(2 r_i^2))
       f_i  = N_i * 4*pi*r_i^2 / A_flat

   其中 r_i = 铜瘤半径，N_i = 单位元面积 A_flat 内的铜瘤数，f_i = 铜瘤总表面积 /
   平坦面积（Hall-Huray surface ratio，SR），A_matte/A_flat = 哑光基底相对面积。
   **平坦铜基准** = 哑光面积比 1 且无铜瘤（f_i = 0）→ K_HH == 1；铜瘤越多/越大、
   频率越高（delta 越小）→ 增益单调增。

   - 闭式来源（逐字给出上式与 f_i 定义）：FlexCompute Tidy3D / Flex RF 文档
     tidy3d.rf.HuraySurfaceRoughness（"Roughness Correction" 节），
     https://tidy3d-help-center.simulation.cloud/flex_rf_gui/TCM/medium/metallic_pec_pmc/HuraySurfaceRoughness.html
     该式即 Ansys HFSS/SIwave 的 Hall-Huray 雪球模型口径，
     https://ansyshelp.ansys.com/public//Views/Secured/Electronics/v252/en/Subsystems/HFSS/Content/HFSS/HurayModel.htm
   - 原始文献：
     [1] P. G. Huray et al., "Fundamentals of a 3-D 'Snowball' Model for Surface
         Roughness Power Losses", 11th Annual IEEE SPI Proceedings, 2007.
     [2] S. H. Hall, S. G. Pytel, P. G. Huray et al., "Multi-GHz, Causal
         Transmission Line Modeling Methodology with a Hemispherical Surface
         Roughness Approach", IEEE Trans. MTT, Dec. 2007, pp. 2614-2624.
     [3] P. G. Huray et al., "Impact of Copper Surface Texture on Loss: A Model
         That Works", DesignCon 2010.

   **已刊参数点**（docstring / 单测引用，非本模块自造）：Ansys SIwave 三个系统
   内置 Huray 模型 r = 0.5 um，Hall-Huray surface ratio SR = 1 / 3 / 6
   （Low / Medium / High Loss），见
   https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v242/en/Subsystems/SIwave/Content/EditingLayerRoughness.htm

3) **Hammerstad 粗糙度修正（对照 / 备选）** —— 「修改版 Hammerstad」[4][5]::

       K_H = 1 + (RF - 1) * (2/pi) * arctan(1.4 * (Rq/delta)^2)

   Rq = RMS 表面粗糙度，RF = 最大粗糙度增益因子；RF = 2 即经典 Hammerstad 方程
   （K_H in [1, 2]）。RF = 1 → K_H == 1（平坦基准）；Rq -> 0 同样给出 K_H -> 1；
   Rq >> delta 时饱和到 RF。

   - 来源：[4] E. Hammerstad, O. Jensen, "Accurate Models for Microstrip
     Computer-Aided Design", IEEE MTT-S Int. Microwave Symp. Dig., 1980,
     pp. 407-409（粗糙度修正因子；Hammerstad 1975 会议文为其前身）；
     [5] Y. Shlepnev, C. Nwachukwu, "Roughness characterization for
     interconnect analysis", IEEE EMC, 2011, DOI: 10.1109/ISEMC.2011.6038367
     （RF 参数化）。FlexCompute 文档 HammerstadSurfaceRoughness 逐字给出上式。

4) **电镀 / 有限铜厚效应** —— 厚度 t 的导体板（单面）表面阻抗 [6]::

       Z_s(t) = (1 + j) / (sigma * delta) * coth((1 + j) * t / delta)

   取实部即有限厚度表面电阻修正因子（相对半无限基准）::

       K_t(t, delta) = [sinh(2t/delta) + sin(2t/delta)]
                       / [cosh(2t/delta) - cos(2t/delta)]

   极限：t >> delta（约 3-5 delta 以上）K_t -> 1（趋近半无限）；t << delta 时
   K_t -> delta/t，Rs_eff -> 1/(sigma*t)（薄层直流面电阻，电流沿厚度均匀）。

   - 来源：[6] S. Ramo, J. R. Whinnery, T. Van Duzer, Fields and Waves in
     Communication Electronics, 3rd ed., §5.5（导电板复表面阻抗
     Z_s = (1+j)/(sigma*delta) * coth((1+j)t/delta)）；亦见 J. D. Jackson,
     Classical Electrodynamics, 3rd ed., §5.18。

设计约束
--------
- core 叶子层：只 import numpy/math（不引 scipy/skrf/求解器）；纯标量函数 +
  冻结数据类；非法输入显式 ValueError，不静默兜底。
- 数值稳定性：K_t 对大 x 直接返回 1（误差 ~2*exp(-2x)）以免 exp 溢出；对小 x
  （< 1e-3）用级数展开避免 cosh - cos 的浮点相消。
- K_HH 的 SR 口径按 FlexCompute/Tidy3D 的 f_i = N_i*4*pi*r_i^2/A_flat 定义；
  Ansys 侧只把该量称作 Hall-Huray surface ratio，两者按同一几何量对齐。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "MU0",
    "ROUGHNESS_MODELS",
    "ConductorLossResult",
    "conductor_surface_resistance",
    "finite_thickness_factor",
    "finite_thickness_surface_resistance",
    "hall_huray_surface_ratio",
    "hammerstad_roughness_factor",
    "huray_factor_from_nodules",
    "huray_roughness_factor",
    "roughness_gain",
    "skin_depth",
    "smooth_surface_resistance",
]

#: 真空磁导率 [H/m]（CODATA 2018 / NIST），与 core/loss_density.py 的 MU0 同值
MU0 = 1.25663706212e-6

#: 支持的粗糙度模型标识
ROUGHNESS_MODELS: tuple[str, ...] = ("smooth", "hammerstad", "huray")


# ─── 输入校验辅助 ─────────────────────────────────────────────────────────────

def _finite(name: str, value: Any) -> float:
    """收敛为有限 float，否则 ValueError。"""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，收到 {value!r}") from exc
    if not np.isfinite(out):
        raise ValueError(f"{name} 必须为有限值，收到 {value!r}")
    return out


def _positive(name: str, value: Any) -> float:
    """校验严格正的有限标量。"""
    out = _finite(name, value)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 > 0，收到 {value!r}")
    return out


def _non_negative(name: str, value: Any) -> float:
    """校验非负的有限标量。"""
    out = _finite(name, value)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >= 0，收到 {value!r}")
    return out


# ─── 光滑铜基准（Pozar §1.7.1） ───────────────────────────────────────────────

def skin_depth(freq_hz: float, sigma_s_per_m: float, mu_r: float = 1.0) -> float:
    """趋肤深度 delta = sqrt(2 / (omega * mu0 * mu_r * sigma)) [m]（Pozar §1.7.1）。

    Raises:
        ValueError: f <= 0、sigma <= 0、mu_r <= 0 或非有限输入。
    """
    freq = _positive("freq_hz", freq_hz)
    sigma = _positive("sigma_s_per_m", sigma_s_per_m)
    mur = _positive("mu_r", mu_r)
    return math.sqrt(2.0 / (2.0 * math.pi * freq * MU0 * mur * sigma))


def smooth_surface_resistance(freq_hz: float, sigma_s_per_m: float, mu_r: float = 1.0) -> float:
    """光滑（半无限厚）导体表面电阻 Rs = sqrt(omega*mu/(2*sigma)) [ohm/sq]。

    等价于 1 / (sigma * skin_depth(...))。

    Raises:
        ValueError: f <= 0、sigma <= 0、mu_r <= 0 或非有限输入。
    """
    freq = _positive("freq_hz", freq_hz)
    sigma = _positive("sigma_s_per_m", sigma_s_per_m)
    mur = _positive("mu_r", mu_r)
    return math.sqrt(2.0 * math.pi * freq * MU0 * mur / (2.0 * sigma))


# ─── 粗糙度增益：Hammerstad（对照 / 备选） ────────────────────────────────────

def hammerstad_roughness_factor(
    rq_m: float,
    delta_m: float,
    roughness_factor: float = 2.0,
) -> float:
    """修改版 Hammerstad 粗糙度增益 K_H（Hammerstad-Jensen 1980 / Shlepnev 2011）。

    K_H = 1 + (RF - 1) * (2/pi) * arctan(1.4 * (Rq/delta)^2)；RF = 2 为经典
    Hammerstad 方程，RF = 1（或 Rq = 0）给出平坦基准 K_H = 1。

    Args:
        rq_m: RMS 表面粗糙度 [m]（>= 0）。
        delta_m: 趋肤深度 [m]（> 0）。
        roughness_factor: 最大粗糙度增益 RF（>= 1，默认 2 = 经典 Hammerstad）。

    Raises:
        ValueError: rq_m < 0、delta_m <= 0、roughness_factor < 1 或非有限输入。
    """
    rq = _non_negative("rq_m", rq_m)
    delta = _positive("delta_m", delta_m)
    rf = _finite("roughness_factor", roughness_factor)
    if rf < 1.0:
        raise ValueError(f"roughness_factor 必须 >= 1（平坦基准为 1），收到 {roughness_factor!r}")
    return 1.0 + (rf - 1.0) * (2.0 / math.pi) * math.atan(1.4 * (rq / delta) ** 2)


# ─── 粗糙度增益：Huray / Hall-Huray 雪球模型 ─────────────────────────────────

def huray_roughness_factor(
    delta_m: float,
    coeffs: Any = (),
    relative_matte_area: float = 1.0,
) -> float:
    """Hall-Huray 雪球模型粗糙度增益 K_HH（Huray 2007 / Hall 2007）。

    K_HH = A_matte/A_flat + (3/2) * sum_i f_i / (1 + delta/r_i + delta^2/(2 r_i^2))，
    f_i = 第 i 族铜瘤总表面积 / 平坦面积（= N_i*4*pi*r_i^2/A_flat）。
    平坦基准（coeffs 为空、relative_matte_area = 1）给出 K_HH = 1。

    Args:
        delta_m: 趋肤深度 [m]（> 0）。
        coeffs: 可迭代的 (f_i, r_i) 二元组序列；f_i >= 0，r_i > 0。
        relative_matte_area: 哑光基底相对面积 A_matte/A_flat（> 0，默认 1）。

    Raises:
        ValueError: delta_m <= 0、relative_matte_area <= 0、f_i < 0、r_i <= 0、
            元素非二元组或非有限输入。
    """
    delta = _positive("delta_m", delta_m)
    matte = _positive("relative_matte_area", relative_matte_area)
    total = matte
    items = () if coeffs is None else coeffs
    for idx, item in enumerate(items):
        try:
            f_i, r_i = item
        except (TypeError, ValueError) as exc:
            raise ValueError(f"coeffs[{idx}] 必须为 (f_i, r_i) 二元组，收到 {item!r}") from exc
        weight = _non_negative(f"coeffs[{idx}].f", f_i)
        radius = _positive(f"coeffs[{idx}].r", r_i)
        total += 1.5 * weight / (1.0 + delta / radius + delta * delta / (2.0 * radius * radius))
    return float(total)


def hall_huray_surface_ratio(
    nodule_radius_m: float,
    nodules_per_cell: float,
    cell_area_m2: float,
) -> float:
    """Hall-Huray surface ratio f = N * 4*pi*r^2 / A_flat（无量纲）。

    Args:
        nodule_radius_m: 铜瘤半径 [m]（> 0）。
        nodules_per_cell: 单位元内铜瘤数 N（>= 0）。
        cell_area_m2: 单位元面积 A_flat [m^2]（> 0）。

    Raises:
        ValueError: 半径 <= 0、N < 0、面积 <= 0 或非有限输入。
    """
    radius = _positive("nodule_radius_m", nodule_radius_m)
    count = _non_negative("nodules_per_cell", nodules_per_cell)
    area = _positive("cell_area_m2", cell_area_m2)
    return count * 4.0 * math.pi * radius * radius / area


def huray_factor_from_nodules(
    delta_m: float,
    nodule_radius_m: float,
    nodules_per_cell: float,
    cell_area_m2: float,
    relative_matte_area: float = 1.0,
) -> float:
    """按铜瘤几何参数（r, N, A_flat）构造单族 Hall-Huray 增益（见 huray_roughness_factor）。"""
    radius = _positive("nodule_radius_m", nodule_radius_m)
    ratio = hall_huray_surface_ratio(radius, nodules_per_cell, cell_area_m2)
    return huray_roughness_factor(delta_m, ((ratio, radius),), relative_matte_area)


# ─── 有限铜厚 / 电镀厚度 ─────────────────────────────────────────────────────

def finite_thickness_factor(thickness_m: float, delta_m: float) -> float:
    """有限铜厚表面电阻修正因子 K_t(t, delta) = Re[(1+j) coth((1+j)t/delta)]。

    闭式：K_t = [sinh(2x) + sin(2x)] / [cosh(2x) - cos(2x)]，x = t/delta。
    t >> delta 时 K_t -> 1；t << delta 时 K_t -> delta/t。

    Raises:
        ValueError: thickness_m <= 0、delta_m <= 0 或非有限输入。
    """
    thickness = _positive("thickness_m", thickness_m)
    delta = _positive("delta_m", delta_m)
    x = thickness / delta
    if x >= 50.0:
        return 1.0
    if x < 1e-3:
        x4 = x * x * x * x
        return (1.0 / x) * (1.0 + (2.0 / 15.0) * x4) / (1.0 + (2.0 / 45.0) * x4)
    return (math.sinh(2.0 * x) + math.sin(2.0 * x)) / (math.cosh(2.0 * x) - math.cos(2.0 * x))


def finite_thickness_surface_resistance(
    freq_hz: float,
    sigma_s_per_m: float,
    thickness_m: float,
    mu_r: float = 1.0,
) -> float:
    """有限厚度导体表面电阻 Rs(t) = Rs_smooth * K_t(t, delta) [ohm/sq]。"""
    delta = skin_depth(freq_hz, sigma_s_per_m, mu_r)
    return smooth_surface_resistance(freq_hz, sigma_s_per_m, mu_r) * finite_thickness_factor(
        thickness_m, delta
    )


# ─── 粗糙度模型分发 + 组合口径 ───────────────────────────────────────────────

def roughness_gain(
    model: str = "smooth",
    *,
    delta_m: float,
    rq_m: float | None = None,
    roughness_factor: float = 2.0,
    huray_coeffs: Any = None,
    nodule_radius_m: float | None = None,
    nodules_per_cell: float | None = None,
    cell_area_m2: float | None = None,
    relative_matte_area: float = 1.0,
) -> float:
    """按模型名计算粗糙度增益。

    - "smooth"：恒等 1（平坦基准）。
    - "hammerstad"：需 rq_m（见 hammerstad_roughness_factor）。
    - "huray"：需 huray_coeffs 或 (nodule_radius_m, nodules_per_cell,
      cell_area_m2)（见 huray_roughness_factor / huray_factor_from_nodules）。

    Raises:
        ValueError: 未知模型或缺参。
    """
    name = str(model).strip().lower()
    if name == "smooth":
        return 1.0
    if name == "hammerstad":
        if rq_m is None:
            raise ValueError("hammerstad 模型需要 rq_m")
        return hammerstad_roughness_factor(rq_m, delta_m, roughness_factor)
    if name == "huray":
        if huray_coeffs is not None:
            return huray_roughness_factor(delta_m, huray_coeffs, relative_matte_area)
        if nodule_radius_m is None or nodules_per_cell is None or cell_area_m2 is None:
            raise ValueError(
                "huray 模型需要 huray_coeffs 或 (nodule_radius_m, nodules_per_cell, cell_area_m2)"
            )
        return huray_factor_from_nodules(
            delta_m, nodule_radius_m, nodules_per_cell, cell_area_m2, relative_matte_area
        )
    raise ValueError(f"未知粗糙度模型 {model!r}，可选 {ROUGHNESS_MODELS}")


@dataclass(frozen=True)
class ConductorLossResult:
    """导体损耗口径结果（全部 SI 单位）。"""

    freq_hz: float
    sigma_s_per_m: float
    mu_r: float
    model: str
    skin_depth_m: float
    rs_smooth_ohm: float
    roughness_gain: float
    thickness_gain: float
    rs_effective_ohm: float

    @property
    def total_gain(self) -> float:
        """总增益 Rs_eff / Rs_smooth。"""
        return self.rs_effective_ohm / self.rs_smooth_ohm


def conductor_surface_resistance(
    freq_hz: float,
    sigma_s_per_m: float,
    *,
    mu_r: float = 1.0,
    model: str = "smooth",
    rq_m: float | None = None,
    roughness_factor: float = 2.0,
    huray_coeffs: Any = None,
    nodule_radius_m: float | None = None,
    nodules_per_cell: float | None = None,
    cell_area_m2: float | None = None,
    relative_matte_area: float = 1.0,
    thickness_m: float | None = None,
) -> ConductorLossResult:
    """组合口径：Rs_eff = Rs_smooth * K_rough * K_thick。

    thickness_m = None 表示半无限厚（K_thick = 1）；model = "smooth" 且给定无
    粗糙度参数时 K_rough = 1（平坦铜基准）。

    Raises:
        ValueError: 频率/电导率/相对磁导率非法、粗糙度模型非法或缺参、厚度非法。
    """
    freq = _positive("freq_hz", freq_hz)
    sigma = _positive("sigma_s_per_m", sigma_s_per_m)
    mur = _positive("mu_r", mu_r)
    delta = skin_depth(freq, sigma, mur)
    rs_smooth = smooth_surface_resistance(freq, sigma, mur)
    k_rough = roughness_gain(
        model,
        delta_m=delta,
        rq_m=rq_m,
        roughness_factor=roughness_factor,
        huray_coeffs=huray_coeffs,
        nodule_radius_m=nodule_radius_m,
        nodules_per_cell=nodules_per_cell,
        cell_area_m2=cell_area_m2,
        relative_matte_area=relative_matte_area,
    )
    k_thick = 1.0 if thickness_m is None else finite_thickness_factor(thickness_m, delta)
    return ConductorLossResult(
        freq_hz=freq,
        sigma_s_per_m=sigma,
        mu_r=mur,
        model=str(model).strip().lower(),
        skin_depth_m=delta,
        rs_smooth_ohm=rs_smooth,
        roughness_gain=k_rough,
        thickness_gain=k_thick,
        rs_effective_ohm=rs_smooth * k_rough * k_thick,
    )
