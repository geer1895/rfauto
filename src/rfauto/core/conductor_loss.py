r"""D2 导体损耗口径（§10.4 D2）：表面粗糙度（Huray / Hammerstad）+ 电镀厚度。

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
精度档案：knowledge/precision_profiles.yaml#conductor_loss（行为=UNVERIFIED，last_verified=2026-09-27）。
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


# ─── 分层导体表面阻抗（F-J.1）：镀层/基底 TL 级联闭式 ─────────────────────────

#: 渐近切换阈值：x = t_i/delta_i >= 20（|gamma*t| = sqrt(2)*x >= 28.3）时
#: ch/sh 渐近式 sh≈ch≈e^x/2 的公共大项满足 2*e^{-2x} < 4.2e-18（低于双精度
#: 分辨率），Z_in 与 Z_i 逐位不可分——直接取 Z_i，兼防大参数复数 ch/sh 溢出。
#: （较常引的 |gamma*t| > 20 口径更保守；切换点声明的义务见
#: layered_surface_impedance docstring。）
_ZS_ASYMPTOTIC_X = 20.0

#: 视为铜的材料名（归一小写后）；铜出现在非末层 = 层序颠倒，显式报错。
_COPPER_MATERIALS = frozenset({"cu", "copper"})

#: 层 dict 允许的键
_LAYER_KEYS = frozenset(
    {"material", "thickness_m", "conductivity_s_per_m", "rho_rel"}
)

#: 定性口径表支持的表面处理键（finish_qualitative_note）
FINISH_NOTE_KEYS: tuple[str, ...] = ("enig", "im_ag", "im_sn", "osp", "hasl")


def _parse_layer_spec(
    idx: int,
    raw: Any,
    *,
    is_substrate: bool,
    sigma_cu: float,
) -> tuple[str, float | None, float]:
    """解析单层 dict → (material, thickness_m 或 None, sigma)。

    非法输入显式 ValueError（bool、非有限、<=0、键缺失/冲突/未知、
    铜不在末层）；不静默兜底。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"layers[{idx}] 必须为 dict，收到 {type(raw).__name__}")
    unknown = sorted(set(raw) - _LAYER_KEYS)
    if unknown:
        raise ValueError(f"layers[{idx}] 含未知键 {unknown}，允许键集 {_LAYER_KEYS}")
    material = raw.get("material")
    if (
        isinstance(material, bool)
        or not isinstance(material, str)
        or not material.strip()
    ):
        raise ValueError(f"layers[{idx}].material 必须为非空字符串，收到 {material!r}")
    material = material.strip().lower()
    if material in _COPPER_MATERIALS and not is_substrate:
        # 位置守卫先于该层其余字段校验：层序颠倒（铜不在末层）是最根本的错误
        raise ValueError(
            f"层序颠倒：铜（{material!r}）出现在第 {idx} 层——layers 语义为"
            "顶面→基底序，基底铜必须是末层"
        )
    thickness: float | None = None
    if is_substrate:
        if raw.get("thickness_m") is not None:
            raise ValueError(
                f"layers[{idx}]（末层=基底）按半无限体处理，不接受 thickness_m，"
                f"收到 {raw.get('thickness_m')!r}"
            )
    else:
        if raw.get("thickness_m") is None:
            raise ValueError(f"layers[{idx}]（涂层层）必须给 thickness_m")
        if isinstance(raw["thickness_m"], bool):
            raise ValueError(f"layers[{idx}].thickness_m 不能为 bool")
        thickness = _non_negative(f"layers[{idx}].thickness_m", raw["thickness_m"])
    has_sigma = raw.get("conductivity_s_per_m") is not None
    has_rho = raw.get("rho_rel") is not None
    if has_sigma and has_rho:
        raise ValueError(
            f"layers[{idx}] 的 conductivity_s_per_m 与 rho_rel 二选一，不可同时给"
        )
    if not has_sigma and not has_rho:
        raise ValueError(
            f"layers[{idx}] 必须给 conductivity_s_per_m 或 rho_rel（相铜电阻率倍数）之一"
        )
    if has_sigma:
        if isinstance(raw["conductivity_s_per_m"], bool):
            raise ValueError(f"layers[{idx}].conductivity_s_per_m 不能为 bool")
        sigma = _positive(
            f"layers[{idx}].conductivity_s_per_m", raw["conductivity_s_per_m"]
        )
    else:
        if isinstance(raw["rho_rel"], bool):
            raise ValueError(f"layers[{idx}].rho_rel 不能为 bool")
        sigma = sigma_cu / _positive(f"layers[{idx}].rho_rel", raw["rho_rel"])
    return material, thickness, sigma


def layered_surface_impedance(
    freq_hz: float,
    layers: list[dict],
    sigma_cu: float = 5.8e7,
) -> dict:
    """分层导体表面阻抗 Zs(f)（F-J.1）——层内良导体近似 + TL 级联闭式。

    物理口径（逐式出处）：

    - 每层良导体近似：趋肤深度 delta_i = sqrt(2/(omega*mu0*sigma_i))（mu_r=1，
      Pozar, Microwave Engineering, 4th ed., §1.7.1，与 skin_depth() 同式）；
      层内传播常数 gamma_i = (1+j)/delta_i；层特性（表面）阻抗
      Z_i = (1+j)/(sigma_i*delta_i) = (1+j)*Rs_i
      （Ramo-Whinnery-Van Duzer, Fields and Waves in Communication Electronics,
      3rd ed., §5.5——有限厚导电板 Z_s = (1+j)/(sigma*delta)*coth((1+j)t/delta)
      即单层特例，见 finite_thickness_factor()）。
    - 级联（自基底向上递推；与多节传输线输入阻抗同型，Pozar §2.3）::

          Z_in,i = Z_i * (Z_{i+1}*ch(gamma_i*t_i) + Z_i*sh(gamma_i*t_i))
                 / (Z_i*ch(gamma_i*t_i) + Z_{i+1}*sh(gamma_i*t_i))

      末层（基底，通常铜）按**半无限体**处理：Z_in = Z_n（不接受
      thickness_m）。极值行为：t_i << delta_i 时 Z_in -> Z_{i+1}（镀层透明）；
      t_i >> delta_i 时 Z_in -> Z_i（顶层自蔽）。
    - 数值稳定性（渐近切换点声明）：x = t_i/delta_i >= _ZS_ASYMPTOTIC_X(=20)
      即 |gamma_i*t_i| = sqrt(2)*x >= 28.3 时，ch/sh 渐近 sh≈ch≈e^x/2，
      代数上 Z_in = Z_i*(Z_{i+1}+Z_i)/(Z_i+Z_{i+1}) = Z_i，渐近误差
      ~2*e^{-2x} < 4.2e-18 低于双精度分辨率——直接取 Z_i（避免大参数复数
      ch/sh 溢出与乘除舍入）。阈值较常引的 |gamma*t| > 20 更保守，
      使厚层极限逐位成立。x < 20 时按 ch/sh 全式计算（t_i >= 20*delta_i
      才可能溢出，无溢出路径；全式各项同号无相消）。

    **输出口径（显式声明，二选一之选择）**：直接输出 (r_eff, x_eff) =
    (Re Z_in, Im Z_in)。**不采用** round5 方案并列的 rho_eq(f) 反解口径
    （R_eff/Rs_smooth(f)*rho_cu）：分层 Zs(f) 的频态不是单一电阻率的
    sqrt(f) 律（r_eff 与 x_eff 各有独立频依赖，x_eff/r_eff 相位偏离 45°
    正是镀层损耗的因果性指纹），反解折叠会丢电抗信息且宽频带内非物理。
    消费面要标量 Rs_eff 时直接取 r_eff（可作 conductor_surface_resistance
    组合口径的基准；MLine 面接线属后续 F-J 件）。

    layers 语义（测试钉死）：list[dict]，**从顶面到基底排序**；每层
    {material, thickness_m, conductivity_s_per_m 或 rho_rel}——两电导键
    恰给其一，rho_rel = 相铜电阻率倍数（sigma = sigma_cu/rho_rel）；
    涂层厚度 t >= 0（t = 0 = 电学不存在，精确透传），末层不给 thickness_m。
    material 归一小写（"cu"/"copper" 视为铜；铜出现在非末层 = 层序颠倒，
    显式报错）。layers 接受 list/tuple。

    与既有 hammerstad/huray 粗糙度因子的关系：分层 Zs（平面分层、镜面）
    与粗糙度增益（Huray/Hammerstad）是**两个正交修正面**——本函数不改
    既有函数；镀层+粗糙度的组合属消费面职责（后续 F-J 件）。

    铁磁注意：本口径统一 mu_r = 1（与 gamma=(1+j)/delta 自洽）；铁磁镍的
    微波频段 mu_r 取值不定（弛豫使体 μr 显著下降），如需 mu_r > 1 须扩层
    参数——如实未做。

    Returns:
        dict: {freq_hz, z_in_complex [ohm], r_eff [ohm/sq],
        x_eff [ohm/sq], skin_depths（逐层 delta，顶→基底序）[m],
        regime_notes（逐层形态注记：semi-infinite / thick asymptote /
        transition / thin / passthrough）}。

    Raises:
        ValueError: freq_hz/sigma_cu 非法（bool、非有限、<=0）、层数 0、
            layers 非 list[dict]、层键缺失/冲突/未知、厚度缺失/负值/bool、
            末层带 thickness_m、铜不在末层。
    """
    if isinstance(freq_hz, bool):
        raise ValueError("freq_hz 不能为 bool（float(True)=1.0 静默污染）")
    freq = _positive("freq_hz", freq_hz)
    if isinstance(sigma_cu, bool):
        raise ValueError("sigma_cu 不能为 bool")
    sigma_ref = _positive("sigma_cu", sigma_cu)
    if isinstance(layers, (str, bytes)) or not isinstance(layers, (list, tuple)):
        raise ValueError(
            f"layers 必须为 list/tuple[dict]（顶面→基底序），收到 {type(layers).__name__}"
        )
    if len(layers) == 0:
        raise ValueError("layers 不能为空：至少需要一层半无限基底（如铜）")
    n_layers = len(layers)
    specs = [
        _parse_layer_spec(i, raw, is_substrate=(i == n_layers - 1), sigma_cu=sigma_ref)
        for i, raw in enumerate(layers)
    ]
    deltas = [skin_depth(freq, spec[2]) for spec in specs]
    z_layers = [
        complex(smooth_surface_resistance(freq, spec[2]),
                smooth_surface_resistance(freq, spec[2]))
        for spec in specs
    ]
    notes = [
        f"layer[{n_layers - 1}] {specs[-1][0]}: semi-infinite substrate "
        "(Z_in = Z_layer)"
    ]
    z_in = z_layers[-1]
    for i in range(n_layers - 2, -1, -1):
        material_i, thickness_i, _ = specs[i]
        if thickness_i == 0.0:
            notes.append(f"layer[{i}] {material_i}: thickness=0, exact passthrough")
            continue
        x = thickness_i / deltas[i]
        if x >= _ZS_ASYMPTOTIC_X:
            z_in = z_layers[i]
            notes.append(
                f"layer[{i}] {material_i}: t/delta={x:.4g} >= {_ZS_ASYMPTOTIC_X:g}, "
                "thick asymptote (Z_in = Z_layer, below invisible)"
            )
            continue
        # gamma_i*t_i = (1+j)*x：实虚部同值，ch/sh 用实数 math 式展开
        # （cosh(u+ju) = cosh(u)cos(u) + j*sinh(u)sin(u)，sinh 同理），无溢出路径。
        xu = x
        ch = complex(math.cosh(xu) * math.cos(xu), math.sinh(xu) * math.sin(xu))
        sh = complex(math.sinh(xu) * math.cos(xu), math.cosh(xu) * math.sin(xu))
        z_i = z_layers[i]
        z_in = z_i * (z_in * ch + z_i * sh) / (z_i * ch + z_in * sh)
        regime = "thin (coating nearly transparent)" if x <= 0.1 else "transition"
        notes.append(f"layer[{i}] {material_i}: t/delta={x:.4g}, {regime}")
    return {
        "freq_hz": freq,
        "z_in_complex": z_in,
        "r_eff": z_in.real,
        "x_eff": z_in.imag,
        "skin_depths": deltas,
        "regime_notes": notes,
    }


def enig_stack(
    freq_hz: float,
    au_thickness_m: float = 7.5e-8,
    ni_thickness_m: float = 3.0e-6,
    cu_conductivity: float = 5.8e7,
    sigma_au: float = 4.1e7,
    sigma_ni: float | None = None,
) -> dict:
    """ENIG（化镍沉金）三层便捷封装：Au / Ni(P) / Cu -> layered_surface_impedance。

    叠层口径（round5 F-J 件 1，区间取中/下缘为缺省）：

    - Au（沉金层）0.05-0.1 µm，缺省 0.075 µm（区间中点）；sigma_au 缺省
      4.1e7 S/m（体金通用值）。
    - Ni(P)（化学镍层）3-6 µm，缺省 3.0 µm（区间下缘）；**sigma_ni 缺省 =
      cu_conductivity/4（rho_Ni ≈ 4×rho_Cu）**。来源注记：Microwave Journal
      2017 与 Samtec DesignCon 2012（round5 调研 [15] 双源）均以 NiP 层为
      ENIG 附加损耗主体；NiP 电阻率随磷含量/工艺**实测分散明显**（文献口径
      3-6× 铜），4× 为体镍量级的工程缺省——需精化时显式传 sigma_ni，
      不静默兜底。
    - 基底铜半无限（cu_conductivity 缺省 5.8e7 S/m，与模块全局口径一致）。

    缺省参数下 1-10 GHz 的 r_eff ≈ 1.68-1.96 × 裸铜 Rs（独立推导：不透明 Ni
    极限 = sqrt(rho_rel) = 2.0；1 GHz 处 t_Ni/delta_Ni ≈ 0.72 过渡区拉低，
    x_eff/r_eff 相位同偏离 45°）。mu_r 统一取 1（铁磁镍微波 μr 取值不定，
    如需 >1 须扩层参数，如实未做）。

    Returns / Raises: 同 layered_surface_impedance。
    """
    if isinstance(freq_hz, bool):
        raise ValueError("freq_hz 不能为 bool（float(True)=1.0 静默污染）")
    if isinstance(au_thickness_m, bool) or isinstance(ni_thickness_m, bool):
        raise ValueError("厚度入参不能为 bool")
    if isinstance(cu_conductivity, bool) or isinstance(sigma_au, bool):
        raise ValueError("电导率入参不能为 bool")
    if sigma_ni is not None and isinstance(sigma_ni, bool):
        raise ValueError("sigma_ni 不能为 bool")
    sigma_cu_v = _positive("cu_conductivity", cu_conductivity)
    sigma_au_v = _positive("sigma_au", sigma_au)
    sigma_ni_v = (
        sigma_cu_v / 4.0 if sigma_ni is None else _positive("sigma_ni", sigma_ni)
    )
    au_t = _non_negative("au_thickness_m", au_thickness_m)
    ni_t = _non_negative("ni_thickness_m", ni_thickness_m)
    layers = [
        {"material": "au", "thickness_m": au_t, "conductivity_s_per_m": sigma_au_v},
        {"material": "ni", "thickness_m": ni_t, "conductivity_s_per_m": sigma_ni_v},
        {"material": "cu", "conductivity_s_per_m": sigma_cu_v},
    ]
    return layered_surface_impedance(freq_hz, layers, sigma_cu=sigma_cu_v)


def finish_qualitative_note(finish: str, freq_hz: float) -> str:
    """表面处理工程定性口径表（纯查表；定量用 layered_surface_impedance/enig_stack）。

    口径（round5 F-J 件 1 / [15] MwJ 2017 + Samtec DesignCon 2012）：

    - "enig"：Ni(P) 层自 GHz 段起主导附加导体损耗——必须定量建模。
    - "im_ag"（沉银）/ "osp"：**>2 GHz 影响可忽略**（工程上按裸铜处理，
      如实标注）；2 GHz 以下影响小，关键场景以实测为准。
    - "im_sn"（沉锡）：Cu-Sn 金属间化合物多孔层，GHz 段可能附加损耗，建议实测。
    - "hasl"：镀层厚且回流不平整，毫米波不推荐。

    未知工艺显式 ValueError（支持键集见 FINISH_NOTE_KEYS）。
    """
    if isinstance(finish, bool) or not isinstance(finish, str):
        raise ValueError(f"finish 必须为字符串，收到 {finish!r}")
    if isinstance(freq_hz, bool):
        raise ValueError("freq_hz 不能为 bool（float(True)=1.0 静默污染）")
    freq = _positive("freq_hz", freq_hz)
    key = finish.strip().lower()
    tail = "（定性查表口径；定量用 layered_surface_impedance / enig_stack）"
    if key == "enig":
        return (
            "ENIG（化镍沉金）：Au 0.05-0.1µm 层基本透明，Ni(P) 3-6µm"
            "（ρ≈4×Cu）自 GHz 段起主导导体损耗附加（缺省口径下 1-10GHz 约"
            " 1.7-2.0 倍裸铜 Rs；NiP 电阻率实测分散 3-6×铜，磷含量/工艺相关——"
            "来源：Microwave Journal 2017 / Samtec DesignCon 2012）；"
            "定量用 enig_stack()。" + tail
        )
    if key in ("im_ag", "osp"):
        if key == "im_ag":
            body = "沉银（Immersion Ag）：镀层薄且 σ_Ag > σ_Cu"
        else:
            body = "OSP（有机保焊膜）：有机薄层、无金属镀层"
        if freq > 2e9:
            return (
                f"{body}，>2GHz 影响可忽略，工程上按裸铜处理"
                f"（当前 {freq:.3g} Hz 属 >2GHz 段）。" + tail
            )
        return (
            f"{body}，>2GHz 影响可忽略（工程上按裸铜处理）；当前 {freq:.3g} Hz"
            " 在 2GHz 以下，影响小但若关键以实测为准。" + tail
        )
    if key == "im_sn":
        return (
            "沉锡（Immersion Sn）：镀层薄但存在 Cu-Sn 金属间化合物（多孔），"
            "GHz 段可能引入附加损耗；RF 关键场景建议实测确认。" + tail
        )
    if key == "hasl":
        return (
            "HASL（热风整平，含无铅）：镀层厚且回流后表面不平整（穹顶），"
            "厚度不均破坏阻抗控制——毫米波不推荐。" + tail
        )
    raise ValueError(f"未知表面处理 {finish!r}，支持 {FINISH_NOTE_KEYS}")
