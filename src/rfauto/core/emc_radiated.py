"""ME-2 EMC v2：辐射发射闭式层（Ott CM 电流式 + 偶极上限/镜像定理 + DM 环路 + 限值叠加）。

规格：月度增强方案 §三 A 流 ME-2。判据预声明：双路径
裁判（#118）——Ott 工程常数直代 vs 第一性天线式独立推导，同参数点一致带预声明
±3 dB 工程带（``DUAL_PATH_BAND_DB``；实际两路代数恒等，实测差 ~1e-14 dB，远窄于带）。
参照 core/aging.py（docstring 法源）与 core/emi_filter.py（ME-1；限值报告面复用其
margin_report）。**不进** @register_calculator（免 #231 注册表消费者三表同步，ME-1
同款约定），导出函数供 service 层直接调。

公式与单位口径（逐项核对钉死，任务书要求 docstring 单位推导表）：

1. **CM 电流辐射（Ott 式）**。H. W. Ott, *Electromagnetic Compatibility Engineering*,
   Wiley 2009：电缆共模电流按短偶极模型（均匀电流分布 + 理想地平面镜像）的最大远场
   工程式 ``E = 1.257e-6 · f · L · I_CM / d``。单位推导表（本模块按 SI 精确 c=299792458
   自洽重推，与 Ott 印刷常数 4 位有效数字一致）：

   ① 短偶极自由空间最大场（θ=90°）：E = η·k·I_A·L_m/(4π·d_m) = 60π·I_A·L/(λ·d) [V/m]
     （η=120π Ω 教科书口径、k=2π/λ；Balanis, *Antenna Theory*, 4th ed., 线电流元场式）。
   ② λ = c/f（f[Hz]）代入：E = 60π·I_A·L·f_Hz/(c·d) [V/m]。
   ③ 单位换算 f[MHz]·I[µA]：f_Hz·I_A = f_MHz·I_µA（10⁶ 与 10⁻⁶ 恰相消）→
      E = (60π/c)·f_MHz·I_µA·L/d [V/m]。
   ④ 理想地平面镜像（掠射角，h≪λ）：×2（镜像定理面见 ``ground_image_factor``）→
      E = (120π/c)·f_MHz·L_m·I_µA/d_m = 1.25750e-6 · f·L·I/d [V/m]
      （用 c≈3×10⁸ 简写时为 1.2566e-6；Ott 印刷值 1.257e-6 与两版皆 4 位舍入一致，
      0.05% 差如实登记，远窄于 ±3 dB 工程带）。
   ⑤ **单位口径钉死**：带 10⁻⁶ 的常数，输出单位是 **V/m 而非 µV/m**（任务书速记
      "1.26e-6（µV/m 输出）"两要素互相差 10⁶，不并立）；µV/m 口径常数为 1.25750
      （无 10⁻⁶）：E[µV/m] = 1.25750·f_MHz·L_m·I_µA/d_m；dBµV/m = 20·log10(E[µV/m])。
      本模块三口径并出（e_v_per_m / e_uv_per_m / e_dbuv_per_m），往返换算测试逐位钉。

2. **偶极上限对照面（半波长偶极 E 场口径）**：谐振参考 E = 60·I₀/d [V/m]
   （Balanis 半波偶极 θ=90° 场式 cos(π/2·cosθ)/sinθ→1；I₀=馈电点峰值电流；
   地镜像同 ×2）。与 Ott 均匀电流模型的结构性偏移如实登记：L=λ/2 处均匀电流外推比
   正弦分布半波偶极高 π/2 倍（+3.922 dB，同峰值电流口径）；短缆（L≪λ）真实三角
   分布比均匀模型低至 6 dB——Ott 模型是保守包络。对照值与偏移随结果并出
   （dipole_bound_* / ott_offset_vs_dipole_db），不做谁覆盖谁的硬判定。

3. **镜像定理面**：理想地平面上方 h 的水平 CM 源 → 真源+镜像源 = 2h 间距二元阵，
   上半空间方向图因子 2·|cos(k·h·sinα)|（α=仰角）；掠射 α=0 恒 ×2（+6.021 dB）；
   h=λ/4 天顶方向零点、h=λ/2 天顶方向峰（闭式，测试钉）。

4. **DM 环路辐射（Ott 环路式）**：小环（磁偶极）最大场 E = η·k²·I·A/(4π·d) [V/m]
   （Balanis 小环场式；地镜像 ×2）。工程常数：E[V/m] = 263e-16·f_Hz²·A_m²·I_A/d_m
   （Ott 印刷值，含地镜像；按 SI c 重推 = 2.63554e-2·f_MHz²·A·I/d，与印刷值差
   0.21% 如实登记）。CM/DM 分离口径并列输出（``cm_dm_split``，双径对照=本件差异化点）。

5. **限值叠加**：FCC §15.109(b) Class B 与 CISPR 32 Table A.4 Class B 辐射发射限值
   （3 m 口径；值面与 core/bands.py 的 fcc15b_rad_* / cispr32_classb_rad_* 种子条目
   逐值一致互证）→ ``radiated_margin`` 复用 ME-1 emi_filter.margin_report 报告面
   （margin=限值−预测，dB 报告面；带外 NaN 不参与判读语义同 ME-1）。

6. **精算层登记**：openEMS nf2ff 全波精算 = 真机批（见 ``PRECISION_LAYER_NOTE``），
   本闭式层不实现、不冒充。

零 IO、纯函数；数值 0.0 合法（判缺失一律 ``is not None``，#364④）；bool 显式拒收
（df7+⑯：float(True)=1.0 静默污染）。f=0 → E=0 恒等（dBµV/m 口径为 −inf，如实）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from rfauto.core.emi_filter import margin_report as _emi_margin_report

__all__ = [
    "C0_M_S",
    "DUAL_PATH_BAND_DB",
    "ETA0_OHM",
    "K_CM_FREE_V_PER_M",
    "K_CM_V_PER_M",
    "K_LOOP_FREE_V_PER_M",
    "K_LOOP_V_PER_M",
    "PRECISION_LAYER_NOTE",
    "CmDmSplitResult",
    "CmRadiatedResult",
    "DmLoopResult",
    "cispr32_classb_radiated_limits",
    "cm_dm_split",
    "cm_radiated_field",
    "dipole_upper_bound",
    "dm_loop_radiated_field",
    "fcc_part15b_radiated_limits",
    "ground_image_factor",
    "radiated_margin",
]

# ── 常数（SI 精确值 + 教科书口径）────────────────────────────────────────────

#: 真空光速（SI 精确定义值，m/s）。
C0_M_S = 299_792_458.0
#: 自由空间波阻抗教科书口径 η=120π Ω（严格值 376.7303 Ω，差 0.07%，工程式口径）。
ETA0_OHM = 120.0 * math.pi
#: Ott CM 工程常数（V/m per MHz·m·µA/m，**含**地镜像 ×2）：(120π/c) = 1.25750e-6。
K_CM_V_PER_M = 2.0 * 60.0 * math.pi / C0_M_S
#: Ott CM 工程常数自由空间版（不含地镜像）：(60π/c) = 0.62875e-6。
K_CM_FREE_V_PER_M = 60.0 * math.pi / C0_M_S
#: Ott 环路工程常数（V/m per Hz²·m²·A/m，含地镜像）：(240π²/c²) = 2.63554e-14。
K_LOOP_V_PER_M = 240.0 * math.pi**2 / C0_M_S**2
#: Ott 环路工程常数自由空间版（不含地镜像）：(120π²/c²) = 1.31777e-14。
K_LOOP_FREE_V_PER_M = 120.0 * math.pi**2 / C0_M_S**2

#: 双路径一致带预声明（dB，工程带；实际代数恒等 ~1e-14，登记用上界）。
DUAL_PATH_BAND_DB = 3.0

#: 精算层登记（任务书 ME-2 第 5 条：openEMS nf2ff=真机批，本层不实现）。
PRECISION_LAYER_NOTE = (
    "精算层登记：辐射发射精算走 openEMS nf2ff 近远场变换（既有内核 nf2ff_service，"
    "真机批接入），本闭式层只产 Ott 工程式与偶极/环路参考面，不冒充全波精度；"
    "闭式（短偶极均匀电流、小环均匀电流）适用域 L≪λ / 周长≪λ，接近谐振时以"
    "偶极上限对照面与精算层为准。"
)

_CM_STRUCTURE_NOTE = (
    "结构性登记：Ott 均匀电流模型是保守包络——短缆（L≪λ）真实三角分布比均匀模型低至"
    " 6 dB；L=λ/2 处均匀外推比正弦分布半波偶极高 π/2 倍（+3.922 dB，同峰值电流口径）。"
)

# ── 入参守卫（aging.py 同款，bool 显式拒收）──────────────────────────────────


def _finite(value: object, name: str) -> float:
    """有限实数守卫（拒 bool）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _nonneg(value: object, name: str) -> float:
    """非负有限实数守卫（0 合法——f=0→E=0、I=0→E=0 是判据钉的恒等面）。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须为非负数（负值无物理意义），实际 {value!r}")
    return out


def _positive(value: object, name: str) -> float:
    """正有限实数守卫。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，实际 {value!r}")
    return out


def _db_amplitude(ratio: float) -> float:
    """幅度 dB = 20·log10(ratio)（ratio≥0；0 → −inf 如实返回）。"""
    if ratio == 0.0:
        return -math.inf
    return 20.0 * math.log10(ratio)


# ── 镜像定理面 ────────────────────────────────────────────────────────────────


def ground_image_factor(height_m: float, f_mhz: float, elevation_deg: float) -> float:
    """理想地平面上方 h 的水平源：真源+镜像源（2h 间距二元阵）方向图因子。

    闭式 = 2·|cos(k·h·sinα)|，α=观察仰角（度，[0, 90]）；k=2πf/c。
    掠射 α=0 → 恒 2.0（+6.021 dB，Ott CM 式内嵌的 ×2）；h=λ/4、α=90°（天顶）→ 0
    （零点）；h=λ/2、α=90° → 2（峰）。f=0 → k=0 → 2.0。

    Args:
        height_m: 源离地高度 m（>=0）。
        f_mhz: 频率 MHz（>=0）。
        elevation_deg: 仰角度 [0, 90]（负角/超 90 显式 ValueError——地下无场）。

    Returns:
        方向图因子（[0, 2]，无量纲）。
    """
    h = _nonneg(height_m, "height_m")
    f_hz = _nonneg(f_mhz, "f_mhz") * 1e6
    alpha_deg = _finite(elevation_deg, "elevation_deg")
    if alpha_deg < 0.0 or alpha_deg > 90.0:
        raise ValueError(f"elevation_deg 必须在 [0, 90]，实际 {elevation_deg!r}")
    k = 2.0 * math.pi * f_hz / C0_M_S
    alpha = math.radians(alpha_deg)
    return 2.0 * abs(math.cos(k * h * math.sin(alpha)))


# ── CM 电流辐射（Ott 式 + 偶极上限对照）──────────────────────────────────────


@dataclass(frozen=True)
class CmRadiatedResult:
    """CM 电缆辐射闭式结果（JSON 可序列化，to_dict 面供 service/CLI）。"""

    f_mhz: float
    length_m: float
    i_cm_ua: float
    distance_m: float
    with_ground_image: bool
    electrical_length: float  # L/λ（无量纲；f=0 时为 0）
    e_v_per_m: float
    e_uv_per_m: float
    e_dbuv_per_m: float
    dipole_bound_v_per_m: float
    dipole_bound_dbuv_per_m: float
    ott_offset_vs_dipole_db: float
    dual_path_diff_db: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "model": "ott_cm_short_dipole",
            "f_mhz": self.f_mhz,
            "length_m": self.length_m,
            "i_cm_ua": self.i_cm_ua,
            "distance_m": self.distance_m,
            "with_ground_image": self.with_ground_image,
            "electrical_length": self.electrical_length,
            "e_v_per_m": self.e_v_per_m,
            "e_uv_per_m": self.e_uv_per_m,
            "e_dbuv_per_m": self.e_dbuv_per_m,
            "dipole_bound_v_per_m": self.dipole_bound_v_per_m,
            "dipole_bound_dbuv_per_m": self.dipole_bound_dbuv_per_m,
            "ott_offset_vs_dipole_db": self.ott_offset_vs_dipole_db,
            "dual_path_diff_db": self.dual_path_diff_db,
            "dual_path_band_db": DUAL_PATH_BAND_DB,
            "notes": list(self.notes),
        }


def cm_radiated_field(
    f_mhz: float,
    length_m: float,
    i_cm_ua: float,
    distance_m: float,
    *,
    with_ground_image: bool = True,
) -> CmRadiatedResult:
    """电缆共模电流辐射场（Ott 式直代 + 第一性短偶极独立式 + 偶极上限对照）。

    路径 A（工程常数直代）：E = K·f_MHz·L_m·I_µA/d_m，K=K_CM_V_PER_M（含镜像，
    1.2573e-6，输出 V/m——单位推导表见模块 docstring 第 1 条）。
    路径 B（第一性独立式）：E = N·η·k·I_A·L/(4π·d)，N=镜像因子，k=2πf/c。
    两路代数恒等（差仅浮点运算序 ~1e-14 dB，预声明 ±3 dB 带的实测值如实报告）。
    偶极上限对照：半波偶极 E=60·N·I_A/d（f 无关的谐振参考，模块 docstring 第 2 条）。

    Args:
        f_mhz: 频率 MHz（>=0；0 → E=0 恒等）。
        length_m: 电缆长度 m（>0）。
        i_cm_ua: 共模电流 µA（>=0；0 → E=0）。
        distance_m: 测量距离 m（>0）。
        with_ground_image: 理想地平面镜像 ×2（Ott 口径缺省含；True=含）。

    Returns:
        CmRadiatedResult（to_dict 面 JSON 可序列化；f=0 时 e_dbuv_per_m=-inf 如实）。
    """
    f = _nonneg(f_mhz, "f_mhz")
    length = _positive(length_m, "length_m")
    i_cm = _nonneg(i_cm_ua, "i_cm_ua")
    dist = _positive(distance_m, "distance_m")
    n_image = 2.0 if with_ground_image else 1.0

    f_hz = f * 1e6
    i_a = i_cm * 1e-6
    # 路径 B（第一性）：短偶极 η·k·I·L/(4πd)；f=0 时 k=0 → E=0，不除 λ（免 0 除）。
    k_wave = 2.0 * math.pi * f_hz / C0_M_S
    e_path_b = n_image * (ETA0_OHM * k_wave * i_a * length) / (4.0 * math.pi * dist)
    # 路径 A（Ott 工程常数直代）：与路径 B 代数恒等（K 常数即由同式吸收常数构成）。
    k_eng = K_CM_V_PER_M if with_ground_image else K_CM_FREE_V_PER_M
    e_path_a = k_eng * f * length * i_cm / dist
    dual_diff_db = (
        0.0
        if e_path_a == 0.0 and e_path_b == 0.0
        else abs(_db_amplitude(e_path_a / e_path_b))
    )

    e_dip = n_image * 60.0 * i_a / dist
    e_dbuv = _db_amplitude(e_path_a * 1e6)
    notes = (
        "路径 A=Ott 工程常数直代、路径 B=ηkIL/4πd 第一性式（#118 双路径），"
        f"预声明一致带 ±{DUAL_PATH_BAND_DB} dB",
        _CM_STRUCTURE_NOTE,
        PRECISION_LAYER_NOTE,
    )
    return CmRadiatedResult(
        f_mhz=f,
        length_m=length,
        i_cm_ua=i_cm,
        distance_m=dist,
        with_ground_image=with_ground_image,
        electrical_length=length * f_hz / C0_M_S,
        e_v_per_m=e_path_a,
        e_uv_per_m=e_path_a * 1e6,
        e_dbuv_per_m=e_dbuv,
        dipole_bound_v_per_m=e_dip,
        dipole_bound_dbuv_per_m=_db_amplitude(e_dip * 1e6),
        ott_offset_vs_dipole_db=e_dbuv - _db_amplitude(e_dip * 1e6),
        dual_path_diff_db=dual_diff_db,
        notes=notes,
    )


def dipole_upper_bound(
    i_peak_a: float,
    distance_m: float,
    *,
    with_ground_image: bool = True,
) -> dict[str, object]:
    """半波长偶极谐振参考面：E = 60·I₀/d [V/m]（θ=90° 最大方向）。

    对照面（非第二路径）：给"若电缆在该频点谐振，每安培峰值 CM 电流辐射多少"的
    参考值——f 无关（半波条件隐含 f）；Balanis 半波偶极场式 cos(π/2·cosθ)/sinθ 在
    θ=90° 取 1。镜像口径同 ×2。

    Args:
        i_peak_a: 峰值电流 A（>=0）。
        distance_m: 距离 m（>0）。
        with_ground_image: 地镜像 ×2。

    Returns:
        dict: {"i_peak_a", "distance_m", "with_ground_image", "e_v_per_m",
        "e_uv_per_m", "e_dbuv_per_m", "reference"}。
    """
    i_pk = _nonneg(i_peak_a, "i_peak_a")
    dist = _positive(distance_m, "distance_m")
    n_image = 2.0 if with_ground_image else 1.0
    e_v = n_image * 60.0 * i_pk / dist
    return {
        "i_peak_a": i_pk,
        "distance_m": dist,
        "with_ground_image": with_ground_image,
        "e_v_per_m": e_v,
        "e_uv_per_m": e_v * 1e6,
        "e_dbuv_per_m": _db_amplitude(e_v * 1e6),
        "reference": "Balanis, Antenna Theory 4th ed., half-wave dipole E(90°)=60·I₀/d",
    }


# ── DM 环路辐射（Ott 环路式）─────────────────────────────────────────────────


@dataclass(frozen=True)
class DmLoopResult:
    """DM 环路辐射闭式结果（JSON 可序列化）。"""

    f_mhz: float
    area_m2: float
    i_dm_a: float
    distance_m: float
    with_ground_image: bool
    e_v_per_m: float
    e_uv_per_m: float
    e_dbuv_per_m: float
    dual_path_diff_db: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "model": "ott_small_loop",
            "f_mhz": self.f_mhz,
            "area_m2": self.area_m2,
            "i_dm_a": self.i_dm_a,
            "distance_m": self.distance_m,
            "with_ground_image": self.with_ground_image,
            "e_v_per_m": self.e_v_per_m,
            "e_uv_per_m": self.e_uv_per_m,
            "e_dbuv_per_m": self.e_dbuv_per_m,
            "dual_path_diff_db": self.dual_path_diff_db,
            "dual_path_band_db": DUAL_PATH_BAND_DB,
            "notes": list(self.notes),
        }


def dm_loop_radiated_field(
    f_mhz: float,
    area_m2: float,
    i_dm_a: float,
    distance_m: float,
    *,
    with_ground_image: bool = True,
) -> DmLoopResult:
    """差模环路辐射场（Ott 小环式直代 + 第一性小环独立式）。

    路径 A（工程常数）：E[V/m] = K·f_Hz²·A·I/d（K=K_LOOP_V_PER_M 含镜像 2.63554e-14，
    即 Ott 印刷值 263e-16 口径，c 取 SI 精确值差 0.21% 已登记；不含镜像用
    K_LOOP_FREE_V_PER_M）。
    路径 B（第一性）：E = N·η·k²·I·A/(4π·d)（Balanis 小环场式）。
    两路代数恒等。适用域：环路周长≪λ（电小环）；接近谐振走精算层（PRECISION_LAYER_NOTE）。

    Args:
        f_mhz: 频率 MHz（>=0）。
        area_m2: 环路面积 m²（>=0；0 → E=0）。
        i_dm_a: 差模环路电流 A（>=0）。
        distance_m: 距离 m（>0）。
        with_ground_image: 地镜像 ×2。

    Returns:
        DmLoopResult（E ∝ f²，倍频 +12.04 dB 测试钉）。
    """
    f = _nonneg(f_mhz, "f_mhz")
    area = _nonneg(area_m2, "area_m2")
    i_dm = _nonneg(i_dm_a, "i_dm_a")
    dist = _positive(distance_m, "distance_m")
    n_image = 2.0 if with_ground_image else 1.0

    f_hz = f * 1e6
    k_wave = 2.0 * math.pi * f_hz / C0_M_S
    e_path_b = n_image * (ETA0_OHM * k_wave**2 * i_dm * area) / (4.0 * math.pi * dist)
    k_loop = K_LOOP_V_PER_M if with_ground_image else K_LOOP_FREE_V_PER_M
    e_path_a = k_loop * f_hz**2 * area * i_dm / dist
    dual_diff_db = (
        0.0
        if e_path_a == 0.0 and e_path_b == 0.0
        else abs(_db_amplitude(e_path_a / e_path_b))
    )
    e_dbuv = _db_amplitude(e_path_a * 1e6)
    notes = (
        "路径 A=Ott 263e-16·f_Hz² 口径（SI c 重推）、路径 B=ηk²IA/4πd 第一性式"
        f"（#118 双路径），预声明一致带 ±{DUAL_PATH_BAND_DB} dB",
        "E ∝ f²（倍频 +12.041 dB）与 E ∝ A（面积翻倍 +6.021 dB）恒等式测试钉",
        PRECISION_LAYER_NOTE,
    )
    return DmLoopResult(
        f_mhz=f,
        area_m2=area,
        i_dm_a=i_dm,
        distance_m=dist,
        with_ground_image=with_ground_image,
        e_v_per_m=e_path_a,
        e_uv_per_m=e_path_a * 1e6,
        e_dbuv_per_m=e_dbuv,
        dual_path_diff_db=dual_diff_db,
        notes=notes,
    )


# ── CM/DM 分离口径（双径对照）────────────────────────────────────────────────


@dataclass(frozen=True)
class CmDmSplitResult:
    """CM/DM 分离对照结果（dominant 严格判：delta_db>0 → "cm"，<0 → "dm"，=0 → "tie"）。"""

    cm: CmRadiatedResult
    dm: DmLoopResult
    dominant: str
    delta_db: float  # cm_dbuv − dm_dbuv（正=CM 占优）

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 可直接渲染的字典。"""
        return {
            "cm": self.cm.to_dict(),
            "dm": self.dm.to_dict(),
            "dominant": self.dominant,
            "delta_db": self.delta_db,
        }


def cm_dm_split(
    f_mhz: float,
    length_m: float,
    i_cm_ua: float,
    area_m2: float,
    i_dm_a: float,
    distance_m: float,
    *,
    with_ground_image: bool = True,
) -> CmDmSplitResult:
    """CM/DM 分离口径并列输出（Ott CM 式 vs DM 环路式，同频同距对照）。

    返回两条独立闭式路径的结果与主导径判定（delta_db = cm_dbuv − dm_dbuv，
    正=CM 主导；严格判，恰 0 记 "tie"——不用容差凑）。
    """
    cm_res = cm_radiated_field(
        f_mhz, length_m, i_cm_ua, distance_m, with_ground_image=with_ground_image
    )
    dm_res = dm_loop_radiated_field(
        f_mhz, area_m2, i_dm_a, distance_m, with_ground_image=with_ground_image
    )
    cm_db = cm_res.e_dbuv_per_m
    dm_db = dm_res.e_dbuv_per_m
    # 双零场（如 f=0）：−inf−(−inf) 无定义，显式归 0 → tie
    delta = 0.0 if cm_db == -math.inf and dm_db == -math.inf else cm_db - dm_db
    if delta > 0.0:
        dominant = "cm"
    elif delta < 0.0:
        dominant = "dm"
    else:
        dominant = "tie"
    return CmDmSplitResult(cm=cm_res, dm=dm_res, dominant=dominant, delta_db=delta)


# ── 辐射发射限值表（FCC §15.109(b) / CISPR 32 Table A.4，3 m 口径）────────────

_FCC_RAD_SOURCE = (
    "47 CFR §15.109(b) Class B 辐射发射限值（3 m），eCFR 现行文本口径；值面与"
    " core/bands.py 种子条目 fcc15b_rad_30m_88m（40 dBµV/m）/fcc15b_rad_88m_216m"
    "（43.5）/fcc15b_rad_216m_960m（46）/fcc15b_rad_above_960m（54，avg）逐值一致互证"
    "（bands 条目 source=47 CFR §15.109(b)，检索 2026-09-27 复核）。"
    "6 GHz 上界取 §15.33(a) 数字电路测量范围上限惯例（bands 同口径）。"
)

_CISPR32_RAD_SOURCE = (
    "CISPR 32:2015 Table A.4 Class B（≤1 GHz，3 m，QP）：30–230 MHz 40 dBµV/m、"
    "230–1000 MHz 47 dBµV/m；值面与 core/bands.py 种子条目 cispr32_classb_rad_30m_230m/"
    "cispr32_classb_rad_230m_1g 一致互证（标准正文收费，经 bands.py 既有裁定值面复用，"
    "检索 2026-09-27 复核）。"
)


def fcc_part15b_radiated_limits() -> dict[str, object]:
    """FCC Part 15 §15.109(b) Class B 辐射发射限值线（dBµV/m @3 m，30 MHz–6 GHz）。

    分段（双闭区间，边界取覆盖段最小值——"lower limit applies at band edges" 语义
    与 ME-1 fcc_limits_part15 同规则）：30–88 MHz 40、88–216 MHz 43.5、
    216–960 MHz 46（QP）；960 MHz 以上 54（avg 检波，500 µV/m）。
    segments 键与 emi_filter.margin_report 的 dict 入参 schema 兼容（f_lo_mhz/
    f_hi_mhz/kind/dbuv_lo/dbuv_hi），可直接作其 limits 传入。
    """
    segs = [
        {"f_lo_mhz": 30.0, "f_hi_mhz": 88.0, "kind": "flat", "dbuv_lo": 40.0, "dbuv_hi": 40.0},
        {"f_lo_mhz": 88.0, "f_hi_mhz": 216.0, "kind": "flat", "dbuv_lo": 43.5, "dbuv_hi": 43.5},
        {"f_lo_mhz": 216.0, "f_hi_mhz": 960.0, "kind": "flat", "dbuv_lo": 46.0, "dbuv_hi": 46.0},
        {"f_lo_mhz": 960.0, "f_hi_mhz": 6000.0, "kind": "flat", "dbuv_lo": 54.0, "dbuv_hi": 54.0},
    ]
    return {
        "regulation": "47 CFR Part 15 §15.109(b)",
        "device_class": "B",
        "distance_m": 3.0,
        "detector": {"30_960_mhz": "quasi-peak", "above_960_mhz": "average"},
        "f_min_mhz": 30.0,
        "f_max_mhz": 6000.0,
        "segments": [dict(s) for s in segs],
        "source": _FCC_RAD_SOURCE,
        "retrieved": "2026-09-27",
        "notes": [
            "边界取下限（band edges 语义）；求值对覆盖段取最小值（ME-1 同规则）",
            "960 MHz 以上行原文检波口径为 average（500 µV/m）",
        ],
    }


def cispr32_classb_radiated_limits() -> dict[str, object]:
    """CISPR 32:2015 Table A.4 Class B 辐射发射限值线（dBµV/m QP @3 m，30 MHz–1 GHz）。"""
    segs = [
        {"f_lo_mhz": 30.0, "f_hi_mhz": 230.0, "kind": "flat", "dbuv_lo": 40.0, "dbuv_hi": 40.0},
        {"f_lo_mhz": 230.0, "f_hi_mhz": 1000.0, "kind": "flat", "dbuv_lo": 47.0, "dbuv_hi": 47.0},
    ]
    return {
        "regulation": "CISPR 32:2015",
        "device_class": "B",
        "distance_m": 3.0,
        "detector": {"all": "quasi-peak"},
        "f_min_mhz": 30.0,
        "f_max_mhz": 1000.0,
        "segments": [dict(s) for s in segs],
        "source": _CISPR32_RAD_SOURCE,
        "retrieved": "2026-09-27",
        "notes": ["标准正文收费——值面按 core/bands.py 既有种子条目复用（三源一致可核口径）"],
    }


def radiated_margin(
    f: float | Sequence[float] | np.ndarray,
    e_dbuv_per_m: float | Sequence[float] | np.ndarray,
    limits: dict[str, object],
) -> dict[str, object]:
    """辐射限值裕量报告：margin = limit − predicted（dBµV/m 面，正=合规）。

    复用 ME-1 ``emi_filter.margin_report``（最小裕量+首违频点+带外 NaN 不判读语义
    同源）；limits 传本模块 ``fcc_part15b_radiated_limits()`` /
    ``cispr32_classb_radiated_limits()`` 返回 dict（segments schema 兼容）。

    Args:
        f: 频率 Hz（正有限，一维或标量；ME-1 报告面同口径）。
        e_dbuv_per_m: 预测/实测场强 dBµV/m（与 f 等长；3 m 口径与限值表同距）。
        limits: 限值 dict（见上）。

    Returns:
        ME-1 margin_report 的返回 dict（f_hz/limit_dbuv/margin_db/min_margin_db/
        first_violation_f_hz/n_violations/verdict 等）。
    """
    return _emi_margin_report(f, e_dbuv_per_m, limits)
