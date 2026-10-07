"""F-J.2 蚀刻梯形截面等效闭式链（工艺几何域）。

业界闭源黑箱（Polar Si9000 等）对蚀刻梯形（etched trapezoid）阻抗补正不
公开系数表——本模块只提供**可复现的几何恒等式 + 等效宽度双口径并列 +
方向恒等式**，精度口径如实标注 UNVERIFIED（无公开权威系数可对，#118
不虚构精度）。ΔZ 估计复用既有微带闭式链（core/synthesis.forward_z0，
skrf Hammerstad-Jensen，只读复用），不新造阻抗模型。

口径与来源（铁律 5：来源写 docstring）：

- 几何恒等式：梯形截面由顶宽 w_t、底宽 w_b、铜厚 t、蚀刻角 θ 参数化，
  w_b = w_t + 2·t·tan(θ)。θ = arctan((w_b − w_t)/(2t)) 反演同式。
- Etch factor：EF = t / undercut（undercut = 单侧横向咬蚀量），与 θ 的
  关系 tan(θ) = undercut/t = 1/EF，即 θ = arctan(1/EF)。EF=1 ↔ 45°、
  EF=2 ↔ 26.57°、EF→∞ ↔ 0°（垂直侧壁）。
  **UNVERIFIED**：业界典型带 EF ≈ 1.5-3 见 PCB 制程文献二手转述
  （Sierra Circuits/Eurocircuits 等 fab 指南口径），无公开权威系数表
  （Polar Si9000 闭源）；本表只作量级参考，非精度背书。
- 等效宽度双口径（并列输出，不裁剪）：
  1. 等面积口径 w_eq,area = A/t：梯形面积 A = (w_t+w_b)/2·t，故
     w_eq,area ≡ (w_t+w_b)/2（对梯形与经验平均口径**恒等**，docstring
     如实注明——两口径真正分叉在等周长）；
  2. 等周长口径 w_eq,perim：2(w_eq+t) = w_t+w_b+2·s（s = t/cosθ 斜边）
     ⟹ w_eq,perim = (w_t+w_b)/2 + t·(1/cosθ − 1)。
  两口径均落 [min(w_t,w_b), max(w_t,w_b)] 内（几何恒等式，单测钉）。
  **UNVERIFIED**：哪个口径更接近真实特征阻抗无公开权威结论（Si9000
  内部拟合未公开），两口径并列供上层保守取界。
- ΔZ 方向恒等式（物理，非经验）：正蚀刻（undercut>0，抗蚀开口=名义宽，
  顶窄底=名义）⟹ 等效宽度 < 名义宽 ⟹ 对物理 Z0(w)（宽线阻抗单调降）
  Z 升；负蚀刻（电镀增宽，undercut<0，顶=名义+2|u|）⟹ Z 降。方向只
  依赖 Z0(w) 的单调性，与闭式精度无关——单测以合成单调裁判 + skrf HJ
  真链双裁判扫描 θ 钉死。
- 版图 etch bias 补偿：定义带符号 bias = 实测线宽 − 设计线宽（电镀类
  制程常报"加宽"）。预补偿闭式 w_design = w_target − bias（fab 恒加宽
  b>0 时设计收窄 b）。业界典型 |bias| ≈ 0.5-1 mil（二手 fab 指南口径，
  **UNVERIFIED**）。往返恒等式：(w_target − bias) + bias = w_target。
- 三保真链登记（本件只登记不实现求解，真机批另立项）：
  f1 = 本模块闭式（等效宽度 → 既有 HJ 微带链）；
  f2 = HFSS/pyaedt 真梯形截面实抽取（接口：按 w_t/w_b/t 建实体 +
  wave port，HFSS 为对齐基准）；
  f3 = openEMS 真截面阶梯化渲染（接口：渲染端把梯形按网格线 staircase
  成矩形台阶并加金属层；预算注记：阶梯化引入附加网格线使 dt 按 CFL
  收缩、NrTS 需按 #152/#343 同口径重估，非零成本项）。
  f1↔f2/f3 对齐判据与预算归真机批，不在本件裁。

接口：纯函数零 IO；非法输入显式 ValueError（负厚度/θ∉[0°,90°)/w≤0，
bool 显式拒收，df7+⑯）；判缺失一律 is not None（#364④）。返回
dataclass（frozen）+ to_dict()（JSON 可序列化 float/str/bool/None）。
不进 calculators 注册表（域内约定同 core/aging.py）。
精度档案：knowledge/precision_profiles.yaml#etch_trapezoid（行为=UNVERIFIED，last_verified=2026-09-28）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "ETCH_BIAS_TYPICAL_MIL",
    "ETCH_FACTOR_TYPICAL",
    "MIL_TO_MM",
    "DeltaZResult",
    "EquivalentWidths",
    "EtchTrapezoidSpec",
    "bottom_width_mm",
    "delta_z_estimate",
    "delta_z_signed_undercut",
    "equivalent_widths",
    "etch_angle_deg_from_etch_factor",
    "etch_angle_deg_from_widths",
    "etch_bias_compensation",
    "etch_factor_from_undercut",
    "trapezoid_from_nominal",
    "undercut_from_etch_factor",
]

#: 1 mil = 0.0254 mm（英制线规换算，精确定义）
MIL_TO_MM = 0.0254

#: 蚀刻角 θ 合法域上界（deg，开区间；90°=tan 发散、侧壁外翻非物理）
_ETCH_ANGLE_MAX_DEG = 90.0

#: etch factor 业界典型带 [1.5, 3]（二手 fab 指南口径，UNVERIFIED，见模块 docstring）
ETCH_FACTOR_TYPICAL = (1.5, 3.0)

#: fab etch bias 典型幅度带 [0.5, 1.0] mil（二手 fab 指南口径，UNVERIFIED，见模块 docstring）
ETCH_BIAS_TYPICAL_MIL = (0.5, 1.0)


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _validate_angle(etch_angle_deg: float, name: str) -> float:
    """蚀刻角域守卫：θ ∈ [0, 90)。"""
    theta = _finite(etch_angle_deg, name)
    if theta < 0.0 or theta >= _ETCH_ANGLE_MAX_DEG:
        raise ValueError(f"{name} 必须在 [0, 90) deg 内，收到 {theta}")
    return theta


# ─── 几何恒等式 ──────────────────────────────────────────────────────────────


def bottom_width_mm(w_top_mm: float, t_cu_mm: float, etch_angle_deg: float) -> float:
    """底宽恒等式 w_b = w_t + 2·t·tan(θ)。

    w_top_mm：顶宽（mm，>0）；t_cu_mm：铜厚（mm，>0）；
    etch_angle_deg：蚀刻半角 θ（deg，[0, 90)）。θ=0 ⟹ w_b == w_t（矩形）。
    """
    w_t = _positive(w_top_mm, "w_top_mm")
    t = _positive(t_cu_mm, "t_cu_mm")
    theta = _validate_angle(etch_angle_deg, "etch_angle_deg")
    return w_t + 2.0 * t * math.tan(math.radians(theta))


def etch_angle_deg_from_widths(w_top_mm: float, w_bottom_mm: float, t_cu_mm: float) -> float:
    """由顶/底宽反演蚀刻角 θ = arctan((w_b − w_t)/(2t))（deg，[0, 90)）。

    w_b < w_t（顶宽底窄，负蚀刻形态）不在几何恒等式域内——负蚀刻走
    delta_z_signed_undercut 的带符号 undercut 通道（见其 docstring）。
    """
    w_t = _positive(w_top_mm, "w_top_mm")
    w_b = _positive(w_bottom_mm, "w_bottom_mm")
    t = _positive(t_cu_mm, "t_cu_mm")
    if w_b < w_t:
        raise ValueError(f"w_bottom_mm={w_b} 不得小于 w_top_mm={w_t}（负蚀刻走带符号通道）")
    return math.degrees(math.atan2(w_b - w_t, 2.0 * t))


def undercut_from_etch_factor(t_cu_mm: float, etch_factor: float) -> float:
    """单侧咬蚀量 undercut = t / EF（mm）。

    t_cu_mm：铜厚（mm，>0）；etch_factor：EF = t/undercut（>0；业界典型
    1.5-3，见 ETCH_FACTOR_TYPICAL，UNVERIFIED）。
    """
    t = _positive(t_cu_mm, "t_cu_mm")
    ef = _positive(etch_factor, "etch_factor")
    return t / ef


def etch_factor_from_undercut(t_cu_mm: float, undercut_mm: float) -> float:
    """etch factor EF = t / undercut（undercut_mm >0）。"""
    t = _positive(t_cu_mm, "t_cu_mm")
    u = _positive(undercut_mm, "undercut_mm")
    return t / u


def etch_angle_deg_from_etch_factor(etch_factor: float) -> float:
    """EF → 蚀刻角 θ = arctan(1/EF)（deg）。EF=1 ⟹ 45°（解析钉）。"""
    ef = _positive(etch_factor, "etch_factor")
    return math.degrees(math.atan(1.0 / ef))


# ─── 等效宽度双口径 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EtchTrapezoidSpec:
    """蚀刻梯形截面规格（正蚀刻域：w_top ≤ w_bottom，θ ∈ [0, 90)）。

    判缺失/非法：构造后调 validate()（字段必填由构造签名强制，数值域由
    validate 显式报错——判缺失一律 is not None，#364④）。负蚀刻（顶宽
    底窄）形态不进本 dataclass，走 delta_z_signed_undercut。
    """

    w_top_mm: float
    w_bottom_mm: float
    t_cu_mm: float

    def validate(self) -> EtchTrapezoidSpec:
        """数值域守卫：w>0、t>0、w_top ≤ w_bottom。返回自身（链式）。"""
        _positive(self.w_top_mm, "w_top_mm")
        _positive(self.w_bottom_mm, "w_bottom_mm")
        _positive(self.t_cu_mm, "t_cu_mm")
        if self.w_top_mm > self.w_bottom_mm:
            raise ValueError(
                f"w_top_mm={self.w_top_mm} 不得大于 w_bottom_mm={self.w_bottom_mm}"
                "（正蚀刻域；负蚀刻走 delta_z_signed_undercut）"
            )
        return self

    @property
    def etch_angle_deg(self) -> float:
        """蚀刻角 θ（deg，[0, 90)）。"""
        return etch_angle_deg_from_widths(self.w_top_mm, self.w_bottom_mm, self.t_cu_mm)

    def to_dict(self) -> dict:
        """JSON 可序列化 dict。"""
        return {
            "w_top_mm": float(self.w_top_mm),
            "w_bottom_mm": float(self.w_bottom_mm),
            "t_cu_mm": float(self.t_cu_mm),
            "etch_angle_deg": float(self.etch_angle_deg),
        }


@dataclass(frozen=True)
class EquivalentWidths:
    """等效宽度双口径并列（等面积 + 等周长，见模块 docstring UNVERIFIED 注记）。"""

    w_eq_area_mm: float
    w_eq_perimeter_mm: float
    w_top_mm: float
    w_bottom_mm: float
    t_cu_mm: float

    def to_dict(self) -> dict:
        """JSON 可序列化 dict。"""
        return {
            "w_eq_area_mm": float(self.w_eq_area_mm),
            "w_eq_perimeter_mm": float(self.w_eq_perimeter_mm),
            "w_top_mm": float(self.w_top_mm),
            "w_bottom_mm": float(self.w_bottom_mm),
            "t_cu_mm": float(self.t_cu_mm),
        }


def equivalent_widths(w_top_mm: float, w_bottom_mm: float, t_cu_mm: float) -> EquivalentWidths:
    """梯形截面 → 等效矩形宽度（双口径并列；顶/底序均可，翻转梯形合法）。

    等面积口径 w_eq,area = A/t ≡ (w_t+w_b)/2（对梯形与均值口径恒等）；
    等周长口径 w_eq,perim = (w_t+w_b)/2 + t·(1/cosθ − 1)，θ 取
    atan2(|w_b−w_t|, 2t)（cos 偶函数，序无关）。两者均
    ∈ [min(w_t,w_b), max(w_t,w_b)]（几何恒等式，单测钉）。
    精度口径 UNVERIFIED（见模块 docstring——无公开权威系数可对）。
    """
    w_t = _positive(w_top_mm, "w_top_mm")
    w_b = _positive(w_bottom_mm, "w_bottom_mm")
    t = _positive(t_cu_mm, "t_cu_mm")
    w_mean = 0.5 * (w_t + w_b)
    # 斜边 s = t/cosθ；等周长恒等式展开后对 θ>0 恒 < max(w_t,w_b)、> min(w_t,w_b)。
    # θ=0（矩形，无斜边）短路：w_perim ≡ w_mean 逐位（避开 +t−t 浮点摆动）。
    slope_deg = math.degrees(math.atan2(abs(w_b - w_t), 2.0 * t))
    if slope_deg == 0.0:
        w_perim = w_mean
    else:
        s = t / math.cos(math.radians(slope_deg))
        w_perim = w_mean + s - t
    return EquivalentWidths(
        w_eq_area_mm=w_mean,
        w_eq_perimeter_mm=w_perim,
        w_top_mm=w_t,
        w_bottom_mm=w_b,
        t_cu_mm=t,
    )


def trapezoid_from_nominal(
    w_nominal_mm: float, t_cu_mm: float, undercut_mm: float
) -> EtchTrapezoidSpec:
    """名义（矩形设计）宽 + 单侧咬蚀量 → 正蚀刻梯形。

    物理模型：抗蚀开口 = 名义宽 w_nominal ⟹ 底宽 = w_nominal（贴基板面
    不被咬蚀）、顶宽 = w_nominal − 2·undercut（两侧横向咬蚀）。
    undercut_mm ≥ 0 且 < w_nominal/2（顶宽须 >0）。负蚀刻（电镀增宽）
    不在此通道，走 delta_z_signed_undercut。
    """
    w_nom = _positive(w_nominal_mm, "w_nominal_mm")
    t = _positive(t_cu_mm, "t_cu_mm")
    u = _finite(undercut_mm, "undercut_mm")
    if u < 0.0:
        raise ValueError(f"undercut_mm 必须 >=0（负蚀刻走 delta_z_signed_undercut），收到 {u}")
    if u >= 0.5 * w_nom:
        raise ValueError(f"undercut_mm={u} 必须 < w_nominal_mm/2={0.5 * w_nom}（顶宽须 >0）")
    return EtchTrapezoidSpec(w_top_mm=w_nom - 2.0 * u, w_bottom_mm=w_nom, t_cu_mm=t)


# ─── ΔZ 估计（复用既有微带闭式链）────────────────────────────────────────────


@dataclass(frozen=True)
class DeltaZResult:
    """ΔZ 估计结果（双口径并列；幅值精度 UNVERIFIED，方向恒等式为硬判据）。

    undercut_mm：带符号单侧咬蚀量（物理约定：>0 正蚀刻/顶窄，<0 负蚀刻/
    电镀增宽，0 矩形）。
    """

    z0_nominal_ohm: float
    z0_area_ohm: float
    z0_perimeter_ohm: float
    dz_area_ohm: float
    dz_perimeter_ohm: float
    w_eq: EquivalentWidths
    undercut_mm: float
    direction: str = field(default="")  # "up"/"down"/"zero"

    def to_dict(self) -> dict:
        """JSON 可序列化 dict。"""
        return {
            "z0_nominal_ohm": float(self.z0_nominal_ohm),
            "z0_area_ohm": float(self.z0_area_ohm),
            "z0_perimeter_ohm": float(self.z0_perimeter_ohm),
            "dz_area_ohm": float(self.dz_area_ohm),
            "dz_perimeter_ohm": float(self.dz_perimeter_ohm),
            "w_eq": self.w_eq.to_dict(),
            "undercut_mm": float(self.undercut_mm),
            "direction": self.direction,
        }


def _direction(dz: float) -> str:
    if dz > 0.0:
        return "up"
    if dz < 0.0:
        return "down"
    return "zero"


def _delta_z_from_spec(
    spec_w_top_mm: float,
    spec_w_bottom_mm: float,
    t_cu_mm: float,
    signed_undercut: float,
    z0_of: Callable[[float], float],
) -> DeltaZResult:
    """共用装配：名义宽=底宽 → 双口径 w_eq → 双口径 Z → ΔZ 与方向标记。"""
    w_nom = _positive(spec_w_bottom_mm, "spec_w_bottom_mm")
    z_nom = float(z0_of(w_nom))
    widths = equivalent_widths(spec_w_top_mm, spec_w_bottom_mm, t_cu_mm)
    z_area = float(z0_of(widths.w_eq_area_mm))
    z_perim = float(z0_of(widths.w_eq_perimeter_mm))
    dz_area = z_area - z_nom
    return DeltaZResult(
        z0_nominal_ohm=z_nom,
        z0_area_ohm=z_area,
        z0_perimeter_ohm=z_perim,
        dz_area_ohm=dz_area,
        dz_perimeter_ohm=z_perim - z_nom,
        w_eq=widths,
        undercut_mm=float(signed_undercut),
        direction=_direction(dz_area),
    )


def delta_z_estimate(
    w_nominal_mm: float,
    t_cu_mm: float,
    etch_angle_deg: float,
    z0_of: Callable[[float], float] | None = None,
    *,
    h_sub_mm: float | None = None,
    er_sub: float | None = None,
) -> DeltaZResult:
    """正蚀刻梯形相对名义矩形的 ΔZ 估计（双口径并列）。

    z0_of：宽度（mm）→ Z0（Ω）的 callable（物理 Z0(w) 宽线单调降）。
    缺省 None 时由 h_sub_mm/er_sub 经既有链懒构建（core/synthesis.forward_z0，
    skrf HJ，只读复用；此时 h_sub_mm/er_sub 必须 is not None，否则显式
    ValueError——判缺失一律 is not None，#364④）。

    方向恒等式（硬判据，单测钉）：θ>0（顶窄）⟹ dz > 0；θ=0 ⟹ dz == 0
    （逐位，w_eq == w_nominal）。ΔZ 幅值精度 UNVERIFIED（等效宽度口径
    未对公开权威系数），方向不依赖精度。
    """
    t = _positive(t_cu_mm, "t_cu_mm")
    theta = _validate_angle(etch_angle_deg, "etch_angle_deg")
    undercut = t * math.tan(math.radians(theta))
    spec = trapezoid_from_nominal(w_nominal_mm, t, undercut)
    if z0_of is None:
        if h_sub_mm is None or er_sub is None:
            raise ValueError("z0_of 为 None 时 h_sub_mm 与 er_sub 必须 is not None（缺省链需层叠参数）")
        z0_of = _default_z0_of(h_sub_mm, er_sub)
    return _delta_z_from_spec(spec.w_top_mm, spec.w_bottom_mm, t, undercut, z0_of)


def delta_z_signed_undercut(
    w_nominal_mm: float,
    t_cu_mm: float,
    undercut_signed_mm: float,
    z0_of: Callable[[float], float],
) -> DeltaZResult:
    """带符号 undercut 的 ΔZ 估计（覆盖负蚀刻/电镀增宽通道）。

    undercut_signed_mm > 0：正蚀刻（w_top = w_nominal − 2u，w_bottom =
    w_nominal）；< 0：负蚀刻/电镀增宽（w_top = w_nominal + 2|u|，
    w_bottom = w_nominal——顶部两侧金属长出）；== 0：矩形（dz == 0 逐位）。
    方向恒等式：u>0 ⟹ dz>0；u<0 ⟹ dz<0（物理 Z0(w) 单调降）。
    """
    w_nom = _positive(w_nominal_mm, "w_nominal_mm")
    t = _positive(t_cu_mm, "t_cu_mm")
    u = _finite(undercut_signed_mm, "undercut_signed_mm")
    if u > 0.0:
        if u >= 0.5 * w_nom:
            raise ValueError(f"undercut_signed_mm={u} 必须 < w_nominal_mm/2={0.5 * w_nom}")
        w_top = w_nom - 2.0 * u
    elif u < 0.0:
        w_top = w_nom + 2.0 * (-u)
    else:
        w_top = w_nom
    return _delta_z_from_spec(w_top, w_nom, t, u, z0_of)


def _default_z0_of(h_sub_mm: float, er_sub: float) -> Callable[[float], float]:
    """缺省 Z0(w) 闭链：既有 core/synthesis.forward_z0（skrf HJ，只读复用）。

    懒导入（保持本模块 import 面零重依赖；skrf 缺失时调用才报）。
    Stackup 损耗面置零（tand=0、rough=0、rho=0）——ΔZ 是宽度差分，损耗
    面对宽线 Z0(w) 单调降的语义与 Z0 实部影响均为二阶小量，钉窄口径。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(
        name="etch_trapezoid_default",
        epsilon_r=float(er_sub),
        thickness_mm=float(h_sub_mm),
        loss_tangent=0.0,
        rho=0.0,
        rough_mm=0.0,
    )

    def z0_of(width_mm: float) -> float:
        z0, _ = forward_z0(width_mm, 1.0, stackup)
        return z0

    return z0_of


# ─── 版图 etch bias 补偿 ─────────────────────────────────────────────────────


def etch_bias_compensation(w_target_mm: float, etch_bias_signed_mm: float) -> float:
    """版图预补偿：w_design = w_target − bias（mm）。

    bias 约定：bias = 实测成品线宽 − 设计线宽（带符号）。电镀类制程常
    报"加宽"（bias>0）⟹ 设计预收窄；咬蚀类制程 bias<0 ⟹ 设计预放宽。
    往返恒等式（单测钉）：w_design + bias = w_target。
    典型 |bias| ≈ 0.5-1 mil（ETCH_BIAS_TYPICAL_MIL，UNVERIFIED）。
    """
    w_target = _positive(w_target_mm, "w_target_mm")
    bias = _finite(etch_bias_signed_mm, "etch_bias_signed_mm")
    return w_target - bias
