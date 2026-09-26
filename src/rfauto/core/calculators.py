"""CalculatorRegistry：微波闭式计算器（纯函数，零 IO，单位口径显式）。

一个计算器 = 注册表条目（名字 + 参数说明 + 纯
函数），UI/CLI/MCP 三壳共享同一 service 入口。单位约定：长度 mm、频率
GHz、阻抗 Ω、衰减 dB；返回值一律 JSON 可序列化 dict。

权威口径：
- 微带正/反解：skrf MLine (Hammerstad-Jensen)——与 core/synthesis.py 同链
- CPW：skrf CPW（quasi-static，含基底厚度 h）
- 带状线：零厚度对称结构椭圆积分共形映射闭式（t=0 精确；
  参照 w/b=1、er=1 → ≈68Ω 文献锚）
- 贴片谐振：Balanis 口径（W/εeff/ΔL/L），与 synthesis.synthesize_patch
  同公式——两者数值一致性有单测钉住
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from rfauto.core.symbolic_fit import CandidateFormula

C_MM_GHZ = 299.792458  # mm·GHz（光速，f[GHz]×λ[mm]=此值）


# ─── 注册表（接口先行：注册可见、未注册调用显式报错）─────────────────────────
# 实验态开关（2026-09-16 口径）：自动归纳（符号回归等）的经验
# 公式一律 experimental=True 入库——names()/describe() **默认不列**（任何
# 只拿 names() 的消费方天然不会拾取），显式 include_experimental=True 才
# 可见；运行放行由 service 层开关决定（core 零配置依赖，只带元数据）。

@dataclass(frozen=True)
class CalculatorSpec:
    """一个计算器的自描述条目（供 CLI/UI 动态生成表单）。"""

    name: str
    description: str
    func: Callable[..., dict[str, Any]]
    params: tuple[tuple[str, str], ...]  # (参数名, "类型 单位 说明")
    required: tuple[str, ...]
    experimental: bool = False  # 实验态：默认不列/默认拒跑，显式开关才用


class CalculatorRegistry:
    """基类+注册表模式（参照 EMSolverRegistry）：重名注册报错，
    未注册调用 KeyError 并列出可用名。"""

    def __init__(self) -> None:
        self._specs: dict[str, CalculatorSpec] = {}

    def register(self, spec: CalculatorSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"计算器重名注册: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> CalculatorSpec:
        if name not in self._specs:
            raise KeyError(
                f"未注册的计算器: {name}"
                f"（可用: {self.names(include_experimental=True)}）")
        return self._specs[name]

    def names(self, include_experimental: bool = False) -> list[str]:
        """已注册键（字典序）；实验键默认排除，include_experimental=True 才列。"""
        return sorted(
            key for key, spec in self._specs.items()
            if include_experimental or not spec.experimental)

    def is_experimental(self, name: str) -> bool:
        """键是否实验态；未注册名显式 KeyError（与 get 同语义）。"""
        return self.get(name).experimental

    def describe(self, include_experimental: bool = False) -> list[dict[str, Any]]:
        """自描述清单（含 experimental 标签）；实验键默认排除。"""
        return [
            {
                "name": self._specs[key].name,
                "description": self._specs[key].description,
                "experimental": bool(self._specs[key].experimental),
                "params": [
                    {"name": pname, "desc": pdesc,
                     "required": pname in self._specs[key].required}
                    for pname, pdesc in self._specs[key].params
                ],
            }
            for key in self.names(include_experimental=include_experimental)
        ]


CALCULATOR_REGISTRY = CalculatorRegistry()


def register_calculator(
    name: str,
    description: str,
    params: tuple[tuple[str, str], ...],
    required: tuple[str, ...] = (),
    experimental: bool = False,
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """把纯函数登记进 CALCULATOR_REGISTRY 的装饰器。

    experimental=True 的键：names()/describe() 默认不列、service 运行默认
    拒绝（见 calculator_service.run_calculator 的 allow_experimental 与
    configs/settings.yaml 的 calculators.allow_experimental）。
    """

    def deco(
        func: Callable[..., dict[str, Any]],
    ) -> Callable[..., dict[str, Any]]:
        CALCULATOR_REGISTRY.register(CalculatorSpec(
            name=name, description=description, func=func,
            params=params, required=required, experimental=experimental))
        return func

    return deco


# ─── 共用底座 ────────────────────────────────────────────────────────────────

def _ad_hoc_stackup(epsilon_r: float, h_mm: float, tand: float):
    """构造临时 Stackup（不落 materials.yaml），复用 synthesis 的 skrf 口径。"""
    from rfauto.core.synthesis import Stackup

    return Stackup(name="ad_hoc", epsilon_r=float(epsilon_r),
                   thickness_mm=float(h_mm), loss_tangent=float(tand))


def _media_z0_eps(media: Any, freq_ghz: float, er_default: float) -> tuple[float, float]:
    """skrf media → (z0_real, eps_eff)。εeff 提取链与 synthesis.forward_z0
    同口径：ep_reff → er_eff → β 反推 → 体介电常数兜底。"""
    import numpy as np

    z0 = float(np.real(media.z0[0]))
    try:
        eps_eff = float(np.real(media.ep_reff[0]))
    except AttributeError:
        try:
            eps_eff = float(media.er_eff[0])
        except AttributeError:
            try:
                beta = float(np.real(media.beta[0]))
                omega = 2 * math.pi * freq_ghz * 1e9
                eps_eff = (beta * 299792458.0 / omega) ** 2
            except Exception:
                eps_eff = er_default
    return z0, eps_eff


def _lambda_g_mm(freq_ghz: float, eps_eff: float) -> float:
    return C_MM_GHZ / (freq_ghz * math.sqrt(eps_eff))


# ─── 微带 ────────────────────────────────────────────────────────────────────

def _microstrip_media(width_mm: float, freq_ghz: float,
                      epsilon_r: float, h_mm: float, tand: float):
    import skrf

    return skrf.media.MLine(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=width_mm * 1e-3, h=h_mm * 1e-3, ep_r=epsilon_r, tand=tand,
        model="hammerstadjensen",
    )


@register_calculator(
    "microstrip_analysis",
    "微带线分析：线宽 → (Z0, εeff)。skrf HJ 模型",
    (("width_mm", "float mm 导带宽度"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("width_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_analysis(width_mm: float, freq_ghz: float,
                        epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    from rfauto.core.synthesis import forward_z0

    z0, eps_eff = forward_z0(width_mm, freq_ghz,
                             _ad_hoc_stackup(epsilon_r, h_mm, tand))
    return {"z0_ohm": round(z0, 2), "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "microstrip_synthesis",
    "微带线综合：目标 Z0 → 线宽（brentq 求逆 + 自洽回代）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("z0_ohm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_synthesis(z0_ohm: float, freq_ghz: float,
                         epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    from rfauto.core.synthesis import forward_z0, inverse_width

    stackup = _ad_hoc_stackup(epsilon_r, h_mm, tand)
    width_mm, z0_actual, status = inverse_width(z0_ohm, freq_ghz, stackup)
    _, eps_eff = forward_z0(width_mm, freq_ghz, stackup)
    return {"width_mm": round(width_mm, 4), "z0_actual_ohm": round(z0_actual, 2),
            "eps_eff": round(eps_eff, 4), "status": status,
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "microstrip_lambda_g",
    "微带 λg：给定几何/频率 → εeff、λ0、λg",
    (("width_mm", "float mm 导带宽度"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("width_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def microstrip_lambda_g(width_mm: float, freq_ghz: float,
                        epsilon_r: float, h_mm: float) -> dict:
    media = _microstrip_media(width_mm, freq_ghz, epsilon_r, h_mm, 0.0)
    z0, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"eps_eff": round(eps_eff, 4),
            "lambda_0_mm": round(C_MM_GHZ / freq_ghz, 3),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3),
            "z0_ohm": round(z0, 2)}


# ─── CPW ─────────────────────────────────────────────────────────────────────

def _cpw_media(w_mm: float, gap_mm: float, freq_ghz: float,
               epsilon_r: float, h_mm: float, tand: float):
    import skrf

    return skrf.media.CPW(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=w_mm * 1e-3, s=gap_mm * 1e-3, h=h_mm * 1e-3,
        ep_r=epsilon_r, tand=tand,
    )


@register_calculator(
    "cpw_analysis",
    "共面波导分析：(w, gap) → (Z0, εeff)。skrf CPW 准静态模型",
    (("w_mm", "float mm 中心导带宽度"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("w_mm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpw_analysis(w_mm: float, gap_mm: float, freq_ghz: float,
                 epsilon_r: float, h_mm: float, tand: float = 0.0) -> dict:
    media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, tand)
    z0, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"z0_ohm": round(z0, 2), "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


@register_calculator(
    "cpw_synthesis",
    "共面波导综合：目标 Z0 → 中心导带宽度（固定 gap，brentq 求逆）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpw_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                  epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, 0.0)
        return _media_z0_eps(media, freq_ghz, epsilon_r)[0] - z0_ohm

    # Z0 随 w 单调递减；扫描找括号，找不到如实报错
    w_lo, w_hi = 0.05, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi:.1f}, {z_lo:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-6)
    media = _cpw_media(w_mm, gap_mm, freq_ghz, epsilon_r, h_mm, 0.0)
    z_actual, eps_eff = _media_z0_eps(media, freq_ghz, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── CPWG（底接地共面波导，共形映射闭式）─────────────────────────────────────

_EPS0 = 8.8541878128e-12   # F/m（真空介电常数）
_C0_MS = 299792458.0       # m/s（光速）


def _cpwg_ri(w_mm: float, gap_mm: float, h_mm: float,
             epsilon_r: float) -> tuple[float, float]:
    """CPWG 准静态共形映射闭式：(εeff, Z0)。

    几何：中心带 a=w/2、半周期 b=w/2+gap、基板厚 h、底面接地。
    部分电容：C_air=2ε0(r1+r4)、C_tot=2ε0(r1+εr·r4)，其中
      k1 = a/b（上半空间共面映射），
      k4 = tanh(πa/2h)/tanh(πb/2h)（接地介质板映射），
      r = K(k)/K'(k)（椭圆积分比，scipy ellipk(m) 的 m=k²）。
    εeff = C/C_air = (r1+εr·r4)/(r1+r4)；Z0 = 1/(c√(C·C_air))。

    极限自洽（有单测）：h→∞ 退化为无地 CPW 无限厚基板
    （εeff→(1+εr)/2，Z0 与 skrf CPW 同式）；h→0 时 εeff→εr。
    实测锚（#193/#198）：rogers4350b w=4.035 gap=0.2 → 引擎 β 实测
    εeff=3.084 vs 闭式 3.03（−1.6%）；闭式 Z0=18.2Ω → |S11|=−6.56dB
    与冒烟实测 −6.5dB 精确对应（该几何是 18Ω 线，50Ω 是参照系错位）。
    """
    from scipy.special import ellipk

    a = w_mm / 2.0
    b = w_mm / 2.0 + gap_mm
    k1 = a / b
    k4 = (math.tanh(math.pi * a / (2.0 * h_mm))
          / math.tanh(math.pi * b / (2.0 * h_mm)))
    r1 = float(ellipk(k1 * k1)) / float(ellipk(1.0 - k1 * k1))
    r4 = float(ellipk(k4 * k4)) / float(ellipk(1.0 - k4 * k4))
    if not (math.isfinite(r1) and math.isfinite(r4)):
        raise ValueError("CPWG 闭式退化（k→1 数值溢出）：h 相对 w 过薄，"
                         "超出准静态共形映射适用域")
    eps_eff = (r1 + epsilon_r * r4) / (r1 + r4)
    z0 = 1.0 / (2.0 * _EPS0 * _C0_MS * math.sqrt(
        (r1 + epsilon_r * r4) * (r1 + r4)))
    return eps_eff, z0


@register_calculator(
    "cpwg_analysis",
    "底接地共面波导（CPWG）分析：共形映射闭式 (w, gap) → (Z0, εeff)。",
    (("w_mm", "float mm 中心导带宽度"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（底接地距离）"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "gap_mm", "epsilon_r", "h_mm"),
)
def cpwg_analysis(w_mm: float, gap_mm: float, epsilon_r: float, h_mm: float,
                  freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "cpwg_synthesis",
    "底接地共面波导（CPWG）综合：目标 Z0 → 中心带宽度（固定 gap，brentq）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 导带-地缝隙"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（底接地距离）")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cpwg_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                   epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)[1] - z0_ohm

    # Z0 随 w 单调递减（细条高阻→宽带低阻）；括号越界如实报错
    w_lo, w_hi = 1e-4, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi:.1f}, {z_lo:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _cpwg_ri(w_mm, gap_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── 带状线（零厚度对称，椭圆积分共形映射闭式）───────────────────────────────

def _stripline_z0(w_mm: float, b_mm: float, epsilon_r: float) -> float:
    from scipy.special import ellipk

    # 零厚度对称带状线共形映射精确解：Z0 = 30π/√εr · K(k')/K(k)
    # k = tanh(πw/2b)；scipy ellipk(m) 的 m=k²，故 K(k)=ellipk(k²)、
    # K(k')=ellipk(1-k²)。极限：w→0 时 Z0→∞（细条高阻）、w→∞ 时 Z0→0
    k = math.tanh(math.pi * w_mm / (2.0 * b_mm))
    ratio = float(ellipk(1.0 - k * k)) / float(ellipk(k * k))
    return 30.0 * math.pi * ratio / math.sqrt(epsilon_r)


@register_calculator(
    "stripline_analysis",
    "对称带状线分析（零厚度闭式，椭圆积分）：(w, b) → Z0",
    (("w_mm", "float mm 中心导带宽度"),
     ("b_mm", "float mm 两接地平面间距"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "b_mm", "epsilon_r"),
)
def stripline_analysis(w_mm: float, b_mm: float, epsilon_r: float,
                       freq_ghz: float | None = None) -> dict:
    z0 = _stripline_z0(w_mm, b_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2), "eps_eff": epsilon_r}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, epsilon_r), 3)
    return out


@register_calculator(
    "stripline_synthesis",
    "对称带状线综合（零厚度闭式求逆）：目标 Z0 → w",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("b_mm", "float mm 两接地平面间距"),
     ("epsilon_r", "float - 基板相对介电常数")),
    required=("z0_ohm", "b_mm", "epsilon_r"),
)
def stripline_synthesis(z0_ohm: float, b_mm: float, epsilon_r: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _stripline_z0(w_mm, b_mm, epsilon_r) - z0_ohm

    w_lo, w_hi = 1e-4 * b_mm, 20.0 * b_mm
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < z0_ohm or z_hi > z0_ohm:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 [{z_hi:.1f}, {z_lo:.1f}]Ω")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    return {"w_mm": round(w_mm, 5),
            "z0_actual_ohm": round(_stripline_z0(w_mm, b_mm, epsilon_r), 3)}


# ─── CPS（共面带，无地有限厚基板；共形映射部分电容闭式）───────

def _kk_ratio(k: float) -> float:
    """r(k) = K(k)/K'(k)（scipy ellipk(m) 的 m=k²）；k→0 时 r→0、k→1 时 r→∞。"""
    from scipy.special import ellipk

    return float(ellipk(k * k)) / float(ellipk(1.0 - k * k))


def _cps_ri(w_mm: float, gap_mm: float, h_mm: float,
            epsilon_r: float, corner2d: bool = False) -> tuple[float, float]:
    """CPS（coplanar strips，双带无地）准静态共形映射闭式 + FD 定标：(εeff, Z0)。

    corner2d=True 时叠加角落二维修正（h_eff = γ(εr)·E2(a/h,b/h,εr)·h，见
    cps_corner2d_gamma_factor；a/h<1 与缺省路径逐位一致，缺省 False 保守
    维持定标域内已验证口径）。

    几何：两条等宽带 w 并行，中央缝 gap；a=gap/2（内缘半距）、b=gap/2+w
    （外缘半距）、基板厚 h、基板下方为空气（无地）。
    出处（docs/rf_template_references.md §11.1）：
      · 均匀介质（空气）CPS：Wadell《Transmission Line Design Handbook》
        (1991) p.83 eqs 3.4.6.x —— Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b
        （MathWorks RF PCB Toolbox 官方例 MoM 对拍；与 CPW 互补对偶
        Z_CPS·Z_CPW=η0²/4=(60π)² 自洽：repo CPW 30π·K'/K 同 k）；
        等价 C_air = ε0·K'(k1)/K(k1) = ε0/r1。
      · 有限厚基板：Gupta/Ghione 部分电容技术（同 _cpwg_ri 框架），介质
        超额项用接地板 tanh 映射 k3 = tanh(πa/2h_eff)/tanh(πb/2h_eff)：
        C = ε0/r1 + (εr−1)·ε0/(2·r3)，εeff = C/C_air = 1+(εr−1)·r1/(2·r3)。
      · **FD 定标（核心/quasistatic_fd.py 裁判，#118）**：
        裸 tanh 映射（h_eff=h）对无地薄基板系统性偏低——基板下方无地时介质
        场向基板外泄漏，等效于"更厚的接地映射板"：h_eff = γ(εr)·h，
        γ(εr) = 1 + 0.9014·εr^(−0.6361)（εr→∞ 场受限 γ→1，εr=3.66 γ=1.395）。
        定标源：裁判在 εr∈{1.5,2.2,3.0,3.66,4.4,6.15,10.2,12.9}×6 几何
        （w/gap ∈ {2.95/0.5, 0.5/0.5, 1.27/0.508, 1.0/0.2, 4.0/1.0, 0.4/0.1}，
        h=0.508）逐 εr 相对误差最小二乘 γ，再幂律拟合（每档 max|err| ≤0.6%）；
        独立验证族 a/h∈[0.05,1]×b/h∈[1.5,12]（35 点，εr=3.66）max|err| 1.4%、
        rms 0.7%（裸映射 −2.9~−12.4%）；w=s=0.5 h∈[0.15,8] 族 ≤1.7%。
        标称 w=2.95/gap=0.5/h=0.508/εr=3.66：裸 1.5712（−5.7%）→ 定标 1.6761
        vs FD 1.667（Richardson，独立临时 FD ≈1.68）。
        **适用域边界（b/h 维 FD 复扫，#122 如实）**：
        定标域 a/h≲1 且 b/h≲3 之外（宽带缝角落）γ(εr) 单参数修正**数据不支持**
        ——逐点最优 γ 的增强比 γ_lsq/γ_now 为 (a/h, b/h) 二维曲面（a/h=0.25→3.0
        时 0.97→1.20，固定 a/h 随 b/h 非单调，εr 再混叠），单参数/b/h 一维因子
        拟合残差与效应同量级，不硬凑。实测闭式低估：a/h=2、b/h=6、εr=10.2
        → −2.8%；a/h=3、b/h=6、εr=12.9 → −5.7%（FD 单档裁判，test_cps_template
        钉住该边界）；比此前 refs 注记的"−2~−4%"更负且随 εr 加重。repo CPS
        模板名义 a/h=0.49、b/h=6.3 在定标域内（INFO 门 ≤1.2%）。
        **角落二维修正（2026-09-21 C5 followUp，corner2d=True opt-in）**：a/h≥1
        角落区按 160 点在档 FD 拟合 log E2 全二次面（γ 空间，10 系数，
        LOOCO max 2.13%；修正后角落残差 max 0.40% vs 修正前 −5.77%），
        定标域/系数/复现入口见 cps_corner2d_gamma_factor；缺省 False，
        缺省路径与上面钉住的边界证据表逐位一致。
    极限自洽（有单测，定标不改变）：h→0 εeff→1；h→∞ εeff→(1+εr)/2（Wen
    半空间口径，γ 不影响）；gap→0 Z0→0、gap→∞ Z0→∞；Z0 随 w 单调递减；
    εeff∈(1, εr)。Z0 = 1/(c·√(C·C_air))（L=1/(c²C_air) 准静态恒等式）。
    """
    if w_mm <= 0 or gap_mm <= 0 or h_mm <= 0 or epsilon_r < 1.0:
        raise ValueError("CPS 闭式定义域：w>0、gap>0、h>0、εr≥1")
    a = gap_mm / 2.0
    b = gap_mm / 2.0 + w_mm
    k1 = a / b
    h_eff = h_mm * cps_effective_thickness_factor(epsilon_r)
    if corner2d:
        h_eff *= cps_corner2d_gamma_factor(a / h_mm, b / h_mm, epsilon_r)
    k3 = (math.tanh(math.pi * a / (2.0 * h_eff))
          / math.tanh(math.pi * b / (2.0 * h_eff)))
    r1 = _kk_ratio(k1)
    r3 = _kk_ratio(k3)  # h≪w 时 k3→1、r3→inf（1/inf=0，超额项自然归零）
    if not (math.isfinite(r1) and r1 > 0.0):
        raise ValueError("CPS 闭式退化（k1→0 或 →1 数值溢出）：gap/w 比例"
                         "超出准静态共形映射适用域")
    c_air = 1.0 / r1                       # 以 ε0 为单位
    c_tot = c_air + (epsilon_r - 1.0) / (2.0 * r3)
    eps_eff = c_tot / c_air
    z0 = 1.0 / (_EPS0 * _C0_MS * math.sqrt(c_air * c_tot))
    return eps_eff, z0


#: CPS 有效厚度定标常数 γ(εr) = 1 + C·εr^(−P)（来源见 _cps_ri docstring；
#: 复现：scripts/fd_laplace_tline_referee.py --refit-cps-gamma）
CPS_H_EFF_GAMMA_C = 0.9014
CPS_H_EFF_GAMMA_P = 0.6361

# ── 锚消费（DP-3 第二批改道，df7 锚消费接线）────────────────────────────────
# 公式锚消费走 core/anchors 的活注册表接插点（core 零 IO：provider 由
# infra/anchors_store 导入时反向注册；未注册/任何失败 → None → 走下方原闭式
# ——回退值与锚值逐位相等，零行为变化，#105 best-effort）。
_CPS_GAMMA_ER_ANCHOR_ID = "cps.gamma_er.fdref-v1"
_SIW_W_EFF_ANCHOR_ID = "siw.w_eff.lit-v1"


def _live_anchor_set() -> Any:
    """惰性取活锚注册表（core/anchors 接插点；未注册/失败 → None）。"""
    try:
        from rfauto.core.anchors import live_anchor_set

        return live_anchor_set()
    except Exception:  # best-effort：锚内核任何故障不阻塞闭式主路径（#105）
        return None


def _cps_gamma_er_anchor_value(er: float) -> float | None:
    """cps.gamma_er 公式锚求值（er 已收敛 float；不可解析 → None 走闭式回退）。

    命中条件=hit 且 source=anchor 且非 stale 且值有限；域外
    （er<1.5 或 >12.9）resolve 结构化 fallback → None → 闭式，与改道前逐位同。"""
    anchor_set = _live_anchor_set()
    if anchor_set is None:
        return None
    try:
        got = anchor_set.resolve_anchor(_CPS_GAMMA_ER_ANCHOR_ID, {"er": er})
        value = got.get("value")
    except Exception:  # best-effort（#105）
        return None
    if (got.get("hit") and got.get("source") == "anchor"
            and not got.get("stale")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))):
        return float(value)
    return None


def _siw_w_eff_anchor_value(w_mm: float, d_mm: float, s_mm: float
                            ) -> float | None:
    """siw.w_eff 公式锚求值（入参已收敛 float；不可解析 → None 走闭式回退）。"""
    anchor_set = _live_anchor_set()
    if anchor_set is None:
        return None
    try:
        got = anchor_set.resolve_anchor(
            _SIW_W_EFF_ANCHOR_ID,
            {"w_mm": w_mm, "d_mm": d_mm, "s_mm": s_mm})
        value = got.get("value")
    except Exception:  # best-effort（#105）
        return None
    if (got.get("hit") and got.get("source") == "anchor"
            and not got.get("stale")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))):
        return float(value)
    return None


def cps_effective_thickness_factor(epsilon_r: float) -> float:
    """CPS 无地薄基板 tanh 映射的有效厚度因子 γ(εr)=1+C·εr^(−P)（≥1）。

    εr=1 时超额项恒为零（γ 值无关）；εr→∞ γ→1（接地映射趋精确）。
    值源（DP-3 第二批改道）：优先 cps.gamma_er.fdref-v1 公式锚
    （knowledge/anchors.yaml，expr=1 + 0.9014*er**-0.6361，域 er∈[1.5,12.9]）；
    锚不可解析（未注册/域外/失败）回退本闭式——回退值与锚值逐位相等
    （同 op 序，test_anchors_core a3 / test_anchor_wire_df7 钉），零行为变化。"""
    if epsilon_r < 1.0:
        raise ValueError("εr≥1")
    got = _cps_gamma_er_anchor_value(float(epsilon_r))
    if got is not None:
        return got
    return 1.0 + CPS_H_EFF_GAMMA_C * float(epsilon_r) ** (-CPS_H_EFF_GAMMA_P)


#: CPS 角落二维修正常数（2026-09-21 C5 followUp，#333 方法论；定标数据=
#: runs/w2f_rescale_batch/cps_bh_scan.json 160 点 a/h×b/h×εr FD 单档裁判，
#: 复现：scripts/fd_laplace_tline_referee.py --refit-cps-corner2d，侦察与
#: 形状族对比脚本 runs/cps_corner2d_fit/explore_fit.py）。模型（γ 空间，
#: 进 tanh 映射，εr=1 / h→0 / h→∞ 三支极限由框架自动保持）：
#:   log E2 = Σ c·φ，x = a/h − 1，
#:   φ = (1, x, ln(b/h), ln(εr), x², ln²(b/h), ln²(εr),
#:        x·ln(b/h), x·ln(εr), ln(b/h)·ln(εr))
#: 角落区 = a/h ≥ 1（γ(εr) 定标域边界；a/h<1 时 E2 ≡ 1 逐位不动）。
#: 结构对比（leave-one-cell-out，20 格）：线性 4 系数 LOOCO max 6.07% →
#: 加对角二次 7 系数 4.06% → 全二次 10 系数 2.13%；全量拟合后角落残差
#: max 0.40%/rms 0.17%（修正前 −2.8~−5.77%）。定标域：
#:   1.0 ≤ a/h ≤ 3.0、a/h < b/h ≤ 6.0、1.5 ≤ εr ≤ 12.9（FD 扫描网格内；
#:   域外显式拒绝不外推——(a/h=3, b/h≈a/h) 邻域与 b/h>6 外推方向无数据约束）
CPS_CORNER2D_COEFFS = (
    0.07944011580288148,
    0.15367879549434305,
    0.04932249237139794,
    -0.023693621533094955,
    0.003343053804404557,
    -0.04214467442272382,
    0.0005920149590515455,
    -0.025771928077387082,
    -0.022407272476807582,
    0.004118895177757769,
)
CPS_CORNER2D_AH_MIN = 1.0
CPS_CORNER2D_AH_MAX = 3.0
CPS_CORNER2D_BH_MAX = 6.0
CPS_CORNER2D_ER_MIN = 1.5
CPS_CORNER2D_ER_MAX = 12.9


def cps_corner2d_gamma_factor(a_over_h: float, b_over_h: float,
                              epsilon_r: float) -> float:
    """CPS 角落二维修正因子 E2(a/h, b/h, εr)（乘在 γ(εr) 上，opt-in）。

    a/h < 1（γ(εr) 单参数定标域内）恒返回 1.0（逐位不动）；εr = 1 亦恒 1.0
    （均匀空气超额项为零，γ 与本修正对 εeff 均无作用）；a/h ≥ 1 时按
    CPS_CORNER2D_COEFFS 的 log 二次面求值，超出 FD 定标网格显式 ValueError
    （不外推，#122 如实）。消费：_cps_ri(corner2d=True)；
    复现：scripts/fd_laplace_tline_referee.py --refit-cps-corner2d。"""
    if a_over_h < CPS_CORNER2D_AH_MIN or epsilon_r <= 1.0:
        return 1.0
    if (a_over_h > CPS_CORNER2D_AH_MAX or b_over_h > CPS_CORNER2D_BH_MAX
            or b_over_h <= a_over_h
            or epsilon_r < CPS_CORNER2D_ER_MIN or epsilon_r > CPS_CORNER2D_ER_MAX):
        raise ValueError(
            f"CPS 角落二维修正定标域：1.0≤a/h≤{CPS_CORNER2D_AH_MAX}、"
            f"a/h<b/h≤{CPS_CORNER2D_BH_MAX}、"
            f"{CPS_CORNER2D_ER_MIN}≤εr≤{CPS_CORNER2D_ER_MAX}"
            f"（got a/h={a_over_h}, b/h={b_over_h}, εr={epsilon_r}；"
            "域外无 FD 数据约束，不外推）")
    x = a_over_h - CPS_CORNER2D_AH_MIN
    lv, lw = math.log(b_over_h), math.log(epsilon_r)
    e = (CPS_CORNER2D_COEFFS[0]
         + CPS_CORNER2D_COEFFS[1] * x + CPS_CORNER2D_COEFFS[2] * lv
         + CPS_CORNER2D_COEFFS[3] * lw + CPS_CORNER2D_COEFFS[4] * x * x
         + CPS_CORNER2D_COEFFS[5] * lv * lv + CPS_CORNER2D_COEFFS[6] * lw * lw
         + CPS_CORNER2D_COEFFS[7] * x * lv + CPS_CORNER2D_COEFFS[8] * x * lw
         + CPS_CORNER2D_COEFFS[9] * lv * lw)
    return math.exp(e)


@register_calculator(
    "cps_analysis",
    "共面带（CPS，双带无地）分析：共形映射部分电容闭式 (w, gap, h) → (Z0, εeff)。",
    (("w_mm", "float mm 单带宽度（两带等宽）"),
     ("gap_mm", "float mm 两带间缝宽"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（无地，基板下为空气）"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "gap_mm", "epsilon_r", "h_mm"),
)
def cps_analysis(w_mm: float, gap_mm: float, epsilon_r: float, h_mm: float,
                 freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "cps_synthesis",
    "共面带（CPS）综合：目标 Z0 → 单带宽度（固定 gap，brentq 回代自洽）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("gap_mm", "float mm 两带间缝宽"),
     ("freq_ghz", "float GHz 频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度（无地）")),
    required=("z0_ohm", "gap_mm", "freq_ghz", "epsilon_r", "h_mm"),
)
def cps_synthesis(z0_ohm: float, gap_mm: float, freq_ghz: float,
                  epsilon_r: float, h_mm: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)[1] - z0_ohm

    # Z0 随 w 单调递减（细带高阻→宽带低阻；k1=gap/(gap+2w)）；括号越界如实报错
    w_lo, w_hi = 1e-4, max(10.0, 20.0 * gap_mm)
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi + z0_ohm:.1f}, {z_lo + z0_ohm:.1f}]Ω（gap={gap_mm}mm 括号扫描）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _cps_ri(w_mm, gap_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(z_actual, 2),
            "eps_eff": round(eps_eff, 4),
            "lambda_g_mm": round(_lambda_g_mm(freq_ghz, eps_eff), 3)}


# ─── 悬置带线（对称填充：厚 h 基板居中夹带，上下空气隙各 (b−h)/2）───────────

#: SSL（悬置带线）FD 重定标常数（裁判=
#: core/quasistatic_fd.py，复现：scripts/fd_laplace_tline_referee.py --refit-ssl-q）。
#: 结构=软最小值（softmin）串联饱和修正的平行份额填充：
#:   εeff = 1 + (Δ^(−p) + D^(−p))^(−1/p)，Δ=(εr−1)·q̃，q̃=q·G
#:   G = 1 + u^μ1·A1·s^a1·(1−s)^b1 + u^μ2·A2·s^a2·(1−s)^b2
#:   D = D0·(1+u)^d1·(4s(1−s))^d2，p = p0+p1·s（u=w/b、s=h/b）
#: q 式把介质份额按"平行份额"（算术）计；实际 slab 与空气隙沿场路径是串联
#: 成分 → εr↑ 时有效份额饱和下降（FD 实测 q_fd 随 εr 单调降），softmin 分母
#: 表达该饱和；(1−s)^b/4s(1−s) 因子保证 s→0/s→1 两端点修正消失（极限精确）。
#: 定标源：6 u×6 s×8 εr=288 点 FD 逐点真值全局 LSQ（fit max|err| 3.84%，
#: 最差点 u=0.1/s=0.5/εr=12.9 窄带高 εr 角落；rms 0.95%）；独立验证族
#: 5u×5s×3εr=75 点（网格外）max|err| 1.94%/rms 0.74%。适用域（#122 如实）：
#: u∈[0.1,1]、s∈[0.0625,0.9]、εr∈[1.5,12.9]；域外为外推（两端点极限仍精确、
#: 全 (u,s,εr) 域单调性经 2001 点/εr 网格验证零违例）。
SSL_Q_G1 = (0.85842, 0.003, 2.38305, -0.21519)    # (A1, a1, b1, mu1)
SSL_Q_G2 = (4.19252, 0.003, 8.57574, 0.1113)      # (A2, a2, b2, mu2)
SSL_D = (31.76642, -1.85399, -0.89951)            # (D0, d1, d2)
SSL_P = (0.17662, 0.73466)                        # (p0, p1)


def _kk_ratio_tanh(x: float) -> float:
    """r = K(k)/K'(k)，k = tanh(x)：经 k' = sech(x) = 1/cosh(x) 无相消计算。

    K(k) = π/(2·agm(1,k'))、K'(k) = π/(2·agm(1,k))（AGM 恒等式），比值无需
    π；k' 直取 1/cosh(x) 避免 1−k² 相消——消除 k→1 的双精度 tanh 饱和地板
    （旧实现 w/h≥5.5 后 q 恒 0，已修复；x≥710 cosh 溢出 → r=∞，
    q→0 正确极限）。
    """
    if x <= 0.0:
        return 0.0
    k = math.tanh(x)
    kp = 1.0 / math.cosh(x) if x < 710.0 else 0.0
    if kp <= 0.0:
        return math.inf
    a, b = 1.0, kp                     # agm(1, k')
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    agm_kp = 0.5 * (a + b)
    a, b = 1.0, k                      # agm(1, k)
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return (0.5 * (a + b)) / agm_kp


def _suspended_stripline_ri(w_mm: float, b_mm: float, h_mm: float,
                            epsilon_r: float) -> tuple[float, float]:
    """悬置带线（suspended substrate stripline，基板对称居中）闭式：(εeff, Z0)。

    几何：两接地板间距 b，零厚度带在中面 z=b/2，厚 h 的基板以带为中面对称
    填充 z∈[b/2−h/2, b/2+h/2]，两侧空气隙各 (b−h)/2（0≤h≤b）。
    出处（docs/rf_template_references.md §11）：
      · 两支精确极限锚=repo 零厚度对称带状线共形闭式 _stripline_z0
        （Cohn/Wadell 30π·K'(k)/K(k)/√εr，k=tanh(πw/2b)）：
        h→0 → 空气带状线 (1, _stripline_z0(w,b,1))；
        h→b → 全填充 (εr, _stripline_z0(w,b,εr))。
      · 填充因子基准 q = r(k_b)/r(k_h)，k_b=tanh(πw/2b)、k_h=tanh(πw/2h)
        （b 腔/h 腔共形电容比；_kk_ratio_tanh 稳定计算，旧 tanh 饱和地板撤）。
      · **FD 重定标（核心/quasistatic_fd.py 裁判）**：
        裸 q 式把介质份额按平行份额计，中段系统性高估（标称几何 +26%；
        旧"偏低"表出自未过基准的临时 FD 已撤，#300）——softmin 串联饱和
        修正族（常数 SSL_Q_G1/G2/SSL_D/SSL_P，定标与适用域见其注），
        288 点拟合 max|err| 3.84% / 独立验证族 75 点 max|err| 1.94%
        （标称 w=0.731 点 −0.58%）。Z0 = _stripline_z0(w,b,1)/√εeff
        （Z0_air 侧 FD vs Cohn −0.1%，未动）。
    单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr]。
    """
    if w_mm <= 0 or b_mm <= 0 or epsilon_r < 1.0:
        raise ValueError("悬置带线闭式定义域：w>0、b>0、εr≥1")
    if h_mm < 0 or h_mm > b_mm:
        raise ValueError(f"悬置带线基板厚 h={h_mm}mm 必须在 [0, b={b_mm}mm] 内"
                         "（基板不得越出接地板腔）")
    if h_mm <= 0.0:
        return 1.0, _stripline_z0(w_mm, b_mm, 1.0)
    if h_mm >= b_mm:
        return epsilon_r, _stripline_z0(w_mm, b_mm, epsilon_r)
    u = w_mm / b_mm
    s = h_mm / b_mm
    a1, b1, c1, mu1 = SSL_Q_G1
    a2, b2, c2, mu2 = SSL_Q_G2
    g = (1.0 + u ** mu1 * a1 * s ** b1 * (1.0 - s) ** c1
         + u ** mu2 * a2 * s ** b2 * (1.0 - s) ** c2)
    r_b = _kk_ratio_tanh(math.pi * u / 2.0)
    r_h = _kk_ratio_tanh(math.pi * u / (2.0 * s))
    q = r_b / r_h if math.isfinite(r_h) and r_h > 0.0 else 0.0
    dd = (epsilon_r - 1.0) * min(q * g, 1.0)
    if dd <= 0.0:                      # 极薄基板数值极限（q→0 精确）
        return 1.0, _stripline_z0(w_mm, b_mm, 1.0)
    d0_, d1_, d2_ = SSL_D
    d_cap = d0_ * (1.0 + u) ** d1_ * (4.0 * s * (1.0 - s)) ** d2_
    p = SSL_P[0] + SSL_P[1] * s
    eps_eff = 1.0 + (dd ** (-p) + d_cap ** (-p)) ** (-1.0 / p)
    z0 = _stripline_z0(w_mm, b_mm, 1.0) / math.sqrt(eps_eff)
    return eps_eff, z0


@register_calculator(
    "suspended_stripline_analysis",
    "悬置带线分析（基板厚 h 居中夹带、腔高 b）：共形电容比闭式 (w, b, h) → (Z0, εeff)",
    (("w_mm", "float mm 中心导带宽度"),
     ("b_mm", "float mm 两接地平面间距（腔高）"),
     ("h_mm", "float mm 基板厚度（0≤h≤b，以带为中面对称填充）"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率（可选，给了才返回 λg）")),
    required=("w_mm", "b_mm", "h_mm", "epsilon_r"),
)
def suspended_stripline_analysis(w_mm: float, b_mm: float, h_mm: float,
                                 epsilon_r: float,
                                 freq_ghz: float | None = None) -> dict:
    eps_eff, z0 = _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)
    out: dict[str, Any] = {"z0_ohm": round(z0, 2),
                           "eps_eff": round(eps_eff, 4)}
    if freq_ghz:
        out["lambda_g_mm"] = round(_lambda_g_mm(freq_ghz, eps_eff), 3)
    return out


@register_calculator(
    "suspended_stripline_synthesis",
    "悬置带线综合：目标 Z0 → w（固定 b/h，brentq 回代自洽，越界显式报错）",
    (("z0_ohm", "float Ω 目标特性阻抗"),
     ("b_mm", "float mm 两接地平面间距（腔高）"),
     ("h_mm", "float mm 基板厚度（0≤h≤b）"),
     ("epsilon_r", "float - 基板相对介电常数")),
    required=("z0_ohm", "b_mm", "h_mm", "epsilon_r"),
)
def suspended_stripline_synthesis(z0_ohm: float, b_mm: float, h_mm: float,
                                  epsilon_r: float) -> dict:
    from scipy.optimize import brentq

    def objective(w_mm: float) -> float:
        return _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)[1] - z0_ohm

    w_lo, w_hi = 1e-4 * b_mm, 20.0 * b_mm
    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z0_ohm}Ω 超出可达范围 "
            f"[{z_hi + z0_ohm:.1f}, {z_lo + z0_ohm:.1f}]Ω（b={b_mm} h={h_mm}）")
    w_mm = brentq(objective, w_lo, w_hi, xtol=1e-7)
    eps_eff, z_actual = _suspended_stripline_ri(w_mm, b_mm, h_mm, epsilon_r)
    return {"w_mm": round(w_mm, 5), "z0_actual_ohm": round(z_actual, 3),
            "eps_eff": round(eps_eff, 4)}


# ─── λ/4 变换 / 衰减器 / 驻波 ────────────────────────────────────────────────

@register_calculator(
    "quarter_wave_transformer",
    "λ/4 阻抗变换器：段特性阻抗 z0=sqrt(Zs·Zl)；给 εeff/频率时附物理长度",
    (("z_source_ohm", "float Ω 源侧阻抗"),
     ("z_load_ohm", "float Ω 负载阻抗"),
     ("freq_ghz", "float GHz 频率（可选，配合 eps_eff 算长度）"),
     ("eps_eff", "float - 有效介电常数（可选）")),
    required=("z_source_ohm", "z_load_ohm"),
)
def quarter_wave_transformer(z_source_ohm: float, z_load_ohm: float,
                             freq_ghz: float | None = None,
                             eps_eff: float | None = None) -> dict:
    z0 = math.sqrt(z_source_ohm * z_load_ohm)
    out: dict[str, Any] = {"z0_section_ohm": round(z0, 3)}
    if freq_ghz and eps_eff:
        lam_g = _lambda_g_mm(freq_ghz, eps_eff)
        out["lambda_g_mm"] = round(lam_g, 3)
        out["length_mm"] = round(lam_g / 4.0, 3)
    return out


@register_calculator(
    "attenuator_pi",
    "π 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_pi(attenuation_db: float, z0_ohm: float) -> dict:
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    # N=电压比=10^(A/20)，推导自匹配+分压两条件
    # （3dB 锚，经典值：中串 17.612Ω/端并 292.48Ω）
    n = 10.0 ** (attenuation_db / 20.0)
    r_series = z0_ohm * (n * n - 1.0) / (2.0 * n)
    r_shunt = z0_ohm * (n + 1.0) / (n - 1.0)
    return {"r_series_mid_ohm": round(r_series, 3),
            "r_shunt_end_ohm": round(r_shunt, 3),
            "note": "π 型：中点串 r_series_mid，两端各对地 r_shunt_end"}


@register_calculator(
    "attenuator_t",
    "T 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_t(attenuation_db: float, z0_ohm: float) -> dict:
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    # N=电压比=10^(A/20)（经典 3dB 锚：串臂 8.550Ω/中并 141.93Ω）
    n = 10.0 ** (attenuation_db / 20.0)
    r_series = z0_ohm * (n - 1.0) / (n + 1.0)
    r_shunt = 2.0 * z0_ohm * n / (n * n - 1.0)
    return {"r_series_arm_ohm": round(r_series, 3),
            "r_shunt_mid_ohm": round(r_shunt, 3),
            "note": "T 型：上下臂各串 r_series_arm，中点对地 r_shunt_mid"}


@register_calculator(
    "attenuator_bridged_t",
    "桥 T 型电阻衰减器：衰减量+Z0 → 桥/并电阻（串臂固定 Z0；节点导纳级联校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_bridged_t(attenuation_db: float, z0_ohm: float) -> dict:
    """桥 T 型（bridged-T）：两串臂各固定 R=Z0，桥电阻跨接输入-输出，中点并电阻对地。

    N=电压比=10^(A/20)。闭式（F8 首族变体，2026-09-16 三节点导纳 Kron 消元
    数值裁判先于采信，#118）：r_bridge=Z0·(N−1)，r_shunt=Z0/(N−1)，串臂=Z0；
    1/3/6/10/20 dB 全部 |S11|≤5e-11、|S21|=1/N（1e-6）。经典 3dB/50Ω 锚：
    桥 20.627Ω / 并 121.201Ω。极限自洽：A→0 桥→0（直通）、并→∞（开路）；
    A→∞ 桥→∞、并→0（中点接地，全反射吸收）。
    """
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    n = 10.0 ** (attenuation_db / 20.0)
    r_bridge = z0_ohm * (n - 1.0)
    r_shunt = z0_ohm / (n - 1.0)
    return {"r_series_arm_ohm": round(float(z0_ohm), 3),
            "r_bridge_ohm": round(r_bridge, 3),
            "r_shunt_mid_ohm": round(r_shunt, 3),
            "note": "桥 T 型：上下臂各串固定 Z0，输入-输出跨接 r_bridge，"
                    "中点对地 r_shunt_mid"}


@register_calculator(
    "vswr_convert",
    "驻波换算：VSWR↔|Γ|↔回损↔失配损耗（三入任一，全出）",
    (("vswr", "float - 电压驻波比（>1；与回损/Γ 二选一）"),
     ("return_loss_db", "float dB 回损（正数）"),
     ("gamma_mag", "float - 反射系数模（0-1）")),
    required=(),
)
def vswr_convert(vswr: float | None = None,
                 return_loss_db: float | None = None,
                 gamma_mag: float | None = None) -> dict:
    if vswr is not None:
        if vswr <= 1.0:
            raise ValueError("VSWR 必须 >1")
        gamma = (vswr - 1.0) / (vswr + 1.0)
    elif return_loss_db is not None:
        if return_loss_db <= 0:
            raise ValueError("回损必须 >0 dB")
        gamma = 10.0 ** (-return_loss_db / 20.0)
    elif gamma_mag is not None:
        if not 0.0 <= gamma_mag < 1.0:
            raise ValueError("|Γ| 必须在 [0,1)")
        gamma = gamma_mag
    else:
        raise ValueError("需提供 vswr / return_loss_db / gamma_mag 之一")
    g = float(gamma)
    if g <= 0.0:
        return {"gamma_mag": 0.0, "vswr": 1.0, "return_loss_db": None,
                "mismatch_loss_db": 0.0, "note": "回损无穷大记 null"}
    rl = -20.0 * math.log10(g)
    vswr_out = (1.0 + g) / (1.0 - g)
    mismatch_db = -10.0 * math.log10(1.0 - g * g)
    return {"gamma_mag": round(g, 6), "vswr": round(vswr_out, 4),
            "return_loss_db": round(rl, 4),
            "mismatch_loss_db": round(mismatch_db, 4)}


# ─── 贴片谐振（Balanis 口径，与 synthesize_patch 同公式）─────────────────────

@register_calculator(
    "patch_length",
    "矩形贴片谐振长度（Balanis 闭式含边缘修正）：f0+er+h → W/εeff/L",
    (("f0_ghz", "float GHz 谐振频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("f0_ghz", "epsilon_r", "h_mm"),
)
def patch_length(f0_ghz: float, epsilon_r: float, h_mm: float) -> dict:
    w_mm = C_MM_GHZ / (2.0 * f0_ghz) * math.sqrt(2.0 / (epsilon_r + 1.0))
    eps_eff = ((epsilon_r + 1.0) / 2.0
               + (epsilon_r - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / w_mm) ** -0.5)
    d_l = (0.824 * h_mm * (eps_eff + 0.3) / (eps_eff - 0.258)
           * (w_mm / h_mm + 0.264) / (w_mm / h_mm + 0.8))
    l_mm = C_MM_GHZ / (2.0 * f0_ghz * math.sqrt(eps_eff)) - 2.0 * d_l
    return {"patch_w_mm": round(w_mm, 4), "eps_eff": round(eps_eff, 4),
            "delta_l_mm": round(d_l, 4), "patch_l_mm": round(l_mm, 4),
            "lambda_g_mm": round(_lambda_g_mm(f0_ghz, eps_eff), 3)}


# ─── 耦合矩阵内核（广义切比雪夫 → Cameron N+2 → folded/arrow）────────────
# 口径（Cameron, Microwave Filters for Communication Systems, ch.6/8）：
#   S11(s)=F(s)/E(s), S21(s)=P(s)/(ε·E(s))；归一化低通带边 Ω=1 处 F_N=1，
#   ε = 1/√(10^(RL/10) − 1)。广义切比雪夫滤波函数用 cosh 和构造：
#   F_N(Ω) = (ΠY_k + ΠY_k⁻¹)/2，Y_k = X_k + √(X_k²−1)（主值分支），
#   无穷远 TZ：X = Ω（每项扫 π）；有限 TZ 对 ±Ω_k：X_k = Ω√(Ω_k²−1)/√(Ω_k²−Ω²)
#   （计入两次，一对 TZ 扫 2π，F = cosh(2·acosh X) = 2X²−1）。
#   耦合矩阵响应（本项目校准口径，N=1 解析锚 + 幺正性单测钉住）：
#   Y = diag(q₀,0..,q_L) + j(Ω·W − M)，W = diag(0,1..1,0)，
#   v = Y⁻¹e₀，S11 = 1 − 2v₀/q₀，S21 = 2v_L/√(q₀q_L)。
#   N+2 横向矩阵（闭式，Cameron 1999 §III-B / 书 §8.2）：
#   a=E+F 按与 N 同/异奇偶次拆成 D/Nu，y22=Nu/D，y21=P'/(εD)，
#   P'=jP 当 (N−n_fz) 为偶（j 规则，保证 jω 轴上 Y 纯虚）；留数
#   r22k=Nu(p_k)/D'(p_k)、r21k=P'(p_k)/(εD'(p_k))，横向元 m_kk=−jp_k、
#   m_0k=√r22k、m_kL=r21k/m_0k、m_0L=jK∞（全规范）。本口径下
#   y11(s)=Σm_0k²/(s−jm_kk) 等，闭式精确（vs 多项式响应 ≤1e−9，单测钉住），
#   LM 精化仅作数值病态兜底（它不保 y11=y22 结构，折叠序列需要该结构）。
#   拓扑约简用复正交合同旋转 M←RMRᵀ（RᵀR=I）：响应严格不变（分析矩阵
#   ΩW−jM+diag(q) 的三段 W/M/q 合同协变性有单测钉住）。folded 走经典
#   palindromic 序列（奇数轮消行右→左 pivot(l−1,l)、偶数轮消列上→下
#   pivot(k,k+1)，由外向内；对照 Yellowbooker/Standard-Coupling-Matrix-
#   Synthesis-Code to_foldedCM.m）。交叉耦合族按 TZ 计数规则自适应：
#   n_fz = N − (S→L 最短路径谐振器数)，反对角 i+j=N+1 给 N−2,N−4,…（偶 N
#   的对称 TZ 对）；奇 N 的偶数 n_fz 只能落在移位反对角 i+j=N+2
#   （(2,N),(3,N−1),…，如 N=5 的 2-5 四元组）。q = (1,1) 为本项目归一化约定
#   （谐振器斜率归一，外部耦合信息全部在 m₀ᵢ/m_{iL} 内）。

def _gcheb_yprod(tz_pairs, n_inf, w):
    """广义切比雪夫滤波函数的 Y 乘积（复主值分支）。"""
    w = np.asarray(w, dtype=complex)
    prod = np.ones_like(w)
    for wz in tz_pairs:
        x = w * math.sqrt(wz * wz - 1.0) / np.sqrt(wz * wz - w * w)
        y = x + np.sqrt(x * x - 1.0)
        prod = prod * y * y
    for _ in range(n_inf):
        prod = prod * (w + np.sqrt(w * w - 1.0))
    return prod


def _gcheb_fn(tz_pairs, n_inf, w):
    prod = _gcheb_yprod(tz_pairs, n_inf, np.asarray(w, dtype=complex))
    return 0.5 * (prod + 1.0 / prod)


def _gcheb_reflection_zeros(tz_pairs, n_inf, n_grid=4001):
    """F_N 在 (−1,1) 内的 N 个零点（单调扫频 + 对分，#118：不赌收敛）。"""
    wgrid = np.linspace(-1.0 + 1e-12, 1.0 - 1e-12, n_grid)
    fn = np.real(_gcheb_fn(tz_pairs, n_inf, wgrid))
    idx = np.where(np.diff(np.sign(fn)) != 0)[0]
    order = 2 * len(tz_pairs) + n_inf
    if len(idx) != order:
        raise ValueError(f"反射零点数 {len(idx)} != 阶数 {order}")
    roots = []
    for i in idx:
        a, b, fa = wgrid[i], wgrid[i + 1], fn[i]
        for _ in range(80):
            m = 0.5 * (a + b)
            fm = float(np.real(_gcheb_fn(tz_pairs, n_inf, np.array([m]))[0]))
            if fm == 0.0:
                a = b = m
                break
            if np.sign(fm) == np.sign(fa):
                a, fa = m, fm
            else:
                b = m
        roots.append(0.5 * (a + b))
    return np.array(sorted(roots))


def _gcheb_prototype(order, rl_db, tz_pairs):
    """广义切比雪夫原型 → (ε, 反射零点, f~, p~, F(s), P(s), E(s))。

    对称口径：TZ 以 ±ω_k 对给出（|ω_k|>1），其余在无穷远；
    F(s)/P(s) 取实系数规范（F 首项系数对齐 f~），E 取 Hurwitz 半边
    （尺度保持，E(s)E(−s)=G(−s²)，G(x)=f~²+p~²/ε² 的 x=Ω² 系数）。
    """
    n_pairs = len(tz_pairs)
    n_inf = order - 2 * n_pairs
    if n_inf < 0:
        raise ValueError(f"TZ 对数 {n_pairs} 超出阶数 {order}")
    eps = 1.0 / math.sqrt(10.0 ** (rl_db / 10.0) - 1.0)
    rz = _gcheb_reflection_zeros(tz_pairs, n_inf)
    f_w = np.real(np.poly(rz))
    p_tilde = np.array([1.0])
    p_s = np.array([1.0])
    for wz in tz_pairs:
        p_tilde = np.polymul(p_tilde, np.array([-1.0, 0.0, wz * wz]))
        p_s = np.polymul(p_s, np.array([1.0, 0.0, wz * wz]))
    f_tilde = f_w * (np.polyval(p_tilde, 1.0) / np.polyval(f_w, 1.0))

    def even_x(poly_w):
        d = len(poly_w) - 1
        out = [(p // 2, cc) for p, cc in
               ((d - k, cc) for k, cc in enumerate(poly_w)) if p % 2 == 0]
        deg = max(pp for pp, _ in out)
        arr = np.zeros(deg + 1)
        for pp, cc in out:
            arr[deg - pp] = cc
        return arr

    gx_f = even_x(np.polymul(f_tilde, f_tilde))
    gx_p = even_x(np.polymul(p_tilde, p_tilde))
    n_max = max(len(gx_f), len(gx_p))
    g_x = (np.concatenate([np.zeros(n_max - len(gx_f)), gx_f])
           + np.concatenate([np.zeros(n_max - len(gx_p)), gx_p]) / eps ** 2)
    degx = len(g_x) - 1
    h_poly = np.zeros(2 * degx + 1)
    for k, cc in enumerate(g_x):
        h_poly[2 * k] = cc * ((-1.0) ** (degx - k))
    roots_h = np.roots(h_poly)
    e_s = np.real(np.poly(roots_h[np.real(roots_h) < 0])) * math.sqrt(g_x[0])
    f_s = np.real(np.poly(1j * rz)) * f_tilde[0]
    return {"eps": eps, "rz": rz, "f_tilde": f_tilde, "p_tilde": p_tilde,
            "f_s": f_s, "p_s": p_s, "e_s": e_s}


def _cm_response_raw(m, qe0, qel, omega):
    """耦合矩阵频响（−jM 经典口径，合同不变）。返回 (S11, S21)。"""
    n2 = m.shape[0]
    Y = np.zeros((n2, n2), dtype=complex)
    for i in range(n2):
        for j in range(n2):
            if i == j:
                if i == 0:
                    Y[i, i] = qe0
                elif i == n2 - 1:
                    Y[i, i] = qel
                else:
                    Y[i, i] = 1j * (omega - m[i, i])
            else:
                Y[i, j] = -1j * m[i, j]
    b = np.zeros(n2, dtype=complex)
    b[0] = 1.0
    v = np.linalg.solve(Y, b)
    return 1.0 - 2.0 * v[0] / qe0, 2.0 * v[n2 - 1] / math.sqrt(qe0 * qel)


def _cm_transversal_exact(order, proto):
    """Cameron Y 留数法 N+2 横向矩阵（闭式精确；inc3 起支持
    复系数原型）。

    口径（Cameron 1999 IEEE T-MTT 47(4) §III-B；书 §8.2；口径块见文件头）：
    a(s)=E+F 按次幂与 N 同/异奇偶拆 D/Nu（同奇偶取实部→D、虚部→Nu；
    异奇偶反之），y22=Nu/D、y21=P'/(εD)，P'=jP 当 (N−n_fz) 为偶。
    留数 r22k/r21k 于 D 的根 p_k；m_kk=−j p_k、m_0k=√r22k、m_kL=r21k/m_0k、
    m_0L=j·K∞（P'/(εD) 的常数项，仅全规范时非零）。谐振器按 m_kk 降序。
    裁判=多项式闭式响应（_poly_response）逐点对照（#118）。
    复系数原型（真·非成对 TZ，_gcheb_prototype_explicit complex 分支）：
    E+F 非实系数，但 D/Nu 的「取实部/取 j×虚部」拆分即 Cameron §III-A 的
    complex-even/complex-odd 实化构造——jω 轴 TZ 集下 F 全实、P/E 低次幂
    交替纯虚，拆分后 D/Nu 均实，横向矩阵可含复元（复对称 M=Mᵀ，
    |m_0k| 与 |m_kL| 允许不等＝非对称网络），|S11|/|S21| 与原型逐点一致
    （实测 N=2..6 ≤1.3e−13，单测钉住）。
    """
    eps = proto["eps"]
    es, fs, ps = proto["e_s"], proto["f_s"], proto["p_s"]
    n = int(order)
    nfz = len(ps) - 1
    p_eff = np.asarray(ps, dtype=complex) / eps
    if (n - nfz) % 2 == 0:
        p_eff = 1j * p_eff
    a = np.polyadd(np.asarray(es, dtype=complex), np.asarray(fs, dtype=complex))
    deg = len(a) - 1
    d_poly = np.zeros(deg + 1, dtype=complex)
    nu_poly = np.zeros(deg + 1, dtype=complex)
    for idx, coef in enumerate(a):
        k = deg - idx
        if (k - n) % 2 == 0:
            d_poly[idx] = coef.real
            nu_poly[idx] = 1j * coef.imag
        else:
            d_poly[idx] = 1j * coef.imag
            nu_poly[idx] = coef.real
    d_poly = np.trim_zeros(d_poly, "f")
    if len(d_poly) - 1 != n:
        raise ValueError(f"Y 分母次数 {len(d_poly) - 1} != 阶数 {n}")
    poles = np.roots(d_poly)
    d_der = np.polyder(d_poly)
    r22 = np.array([np.polyval(nu_poly, p) / np.polyval(d_der, p)
                    for p in poles])
    r21 = np.array([np.polyval(p_eff, p) / np.polyval(d_der, p)
                    for p in poles])
    k_inf = 0j
    if len(p_eff) >= len(d_poly):
        quot, _ = np.polydiv(p_eff, d_poly)
        k_inf = complex(quot[-1])
    n2 = n + 2
    ma = np.zeros((n2, n2), dtype=complex)
    for i, k in enumerate(np.argsort(-np.imag(poles))):
        r = i + 1
        ma[r, r] = -1j * poles[k]
        t0 = np.sqrt(r22[k])
        tl = r21[k] / t0
        ma[0, r] = ma[r, 0] = t0
        ma[r, n2 - 1] = ma[n2 - 1, r] = tl
    ma[0, n2 - 1] = ma[n2 - 1, 0] = 1j * k_inf
    return ma


def _cm_poly_max_err(m, proto, n_grid=241):
    """耦合矩阵 vs 多项式闭式响应的 |S11|/|S21| 最大偏差（独立裁判）。"""
    err = 0.0
    for w_ in np.linspace(-1.0, 1.0, n_grid):
        s11c, s21c = _cm_response_raw(m, 1.0, 1.0, w_)
        s11p, s21p = _poly_response(proto, np.array([w_]))
        err = max(err, abs(abs(s21c) - abs(s21p[0])),
                  abs(abs(s11c) - abs(s11p[0])))
    return float(err)


def _cm_unpack(x, n2):
    k = n2 - 2
    m = x[0:k] + 1j * x[k:2 * k]
    t0 = x[2 * k:3 * k] + 1j * x[3 * k:4 * k]
    tl = x[4 * k:5 * k] + 1j * x[5 * k:6 * k]
    ma = np.zeros((n2, n2), dtype=complex)
    for i in range(k):
        ma[i + 1, i + 1] = m[i]
        ma[0, i + 1] = ma[i + 1, 0] = t0[i]
        ma[i + 1, n2 - 1] = ma[n2 - 1, i + 1] = tl[i]
    return ma


def _cm_pack(ma):
    n2 = ma.shape[0]
    return np.concatenate([np.diag(ma)[1:n2 - 1].real,
                           np.diag(ma)[1:n2 - 1].imag,
                           ma[0, 1:n2 - 1].real, ma[0, 1:n2 - 1].imag,
                           ma[1:n2 - 1, n2 - 1].real,
                           ma[1:n2 - 1, n2 - 1].imag])


def _cm_polish(order, proto, ma0, wgrid, rounds=4):
    """LM 最小二乘幅频精化（确定性内核；锚=多项式闭式响应）。"""
    from scipy.optimize import least_squares

    n2 = ma0.shape[0]
    x = _cm_pack(ma0)
    tgt = []
    for w_ in wgrid:
        s11p, s21p = _poly_response(proto, np.array([w_]))
        tgt.append((abs(s11p[0]), abs(s21p[0])))

    def resid(xx):
        ma = _cm_unpack(xx, n2)
        out = []
        for w_, (t11, t21) in zip(wgrid, tgt, strict=True):
            s11c, s21c = _cm_response_raw(ma, 1.0, 1.0, w_)
            out.append(abs(s11c) - t11)
            out.append(abs(s21c) - t21)
        return np.array(out)

    res = None
    for _ in range(rounds):
        res = least_squares(resid, x, method="lm", xtol=1e-15,
                            ftol=1e-15, max_nfev=2000)
        x = res.x
        if np.max(np.abs(res.fun)) < 1e-11:
            break
    return _cm_unpack(x, n2), res


def _poly_response(proto, omega):
    """多项式闭式响应（独立裁判）：S11=F/E, S21=P/(εE)。"""
    eps = proto["eps"]
    E = np.polyval(proto["e_s"].astype(complex), 1j * omega)
    s11 = np.polyval(proto["f_s"].astype(complex), 1j * omega) / E
    s21 = np.polyval(proto["p_s"].astype(complex), 1j * omega) / (eps * E)
    return s11, s21


def _cm_cong_rot(M, p, q, c, s):
    """复正交合同旋转 M ← RMRᵀ（RᵀR=I：响应与对称性严格保持）。"""
    n2 = M.shape[0]
    R = np.eye(n2, dtype=complex)
    R[p, p] = c
    R[q, q] = c
    R[p, q] = s
    R[q, p] = -s
    return R @ M @ R.T


def _cm_reduce_arrow(m, tol=1e-13):
    """横向 → arrow：载行清理 + 源行清理 + 块三对角化（合同旋转）。"""
    n2 = m.shape[0]
    M = m.copy()
    for j in range(1, n2 - 2):
        if abs(M[n2 - 1, j]) < tol:
            continue
        t = M[n2 - 1, j] / M[n2 - 1, n2 - 2]
        c = 1.0 / np.sqrt(1.0 + t * t)
        M = _cm_cong_rot(M, n2 - 2, j, c, t * c)
    for j in range(2, n2 - 1):
        if abs(M[0, j]) < tol:
            continue
        t = M[0, j] / M[0, 1]
        c = 1.0 / np.sqrt(1.0 + t * t)
        M = _cm_cong_rot(M, 1, j, c, t * c)
    for rr in range(1, n2 - 3 + 1):
        for k in range(n2 - 2, rr + 1, -1):
            if abs(M[rr, k]) < tol:
                continue
            t = M[rr, k] / M[rr, rr + 1]
            c = 1.0 / np.sqrt(1.0 + t * t)
            M = _cm_cong_rot(M, rr + 1, k, c, t * c)
    return M


def _cm_folded_keepers(n2):
    """folded 反对角族 keeper：次对角 + (0,L) + 交叉 i+j=N+1（0-based i+j=n2−1）。

    TZ 计数规则：交叉 (i, n2−1−i) 给 n_fz = N−2i（偶 N 的对称 TZ 对全在此族）。
    """
    L = n2 - 1
    keep = {(i, i + 1) for i in range(n2 - 1)}
    keep.add((0, L))
    for i in range(1, n2 - 2):
        j = L - i
        if j > i + 1:
            keep.add((i, j))
    return keep


def _cm_folded_keepers_shifted(n2):
    """folded 移位反对角族 keeper：次对角 + 交叉 i+j=N+2（0-based i+j=n2）。

    奇 N 的偶数 n_fz 只能落在此族：(1,L)→N−1、(2,N)→N−3、(3,N−1)→N−5…
    （反对角族在奇 N 时只给奇数 n_fz）。对称 ±TZ 对原型的奇数阶结果
    （如 N=5 的 2-5 四元组）即此族。
    """
    keep = {(i, i + 1) for i in range(n2 - 1)}
    for i in range(1, n2 - 1):
        j = n2 - i
        if i < j < n2 and j > i + 1:
            keep.add((i, j))
    return keep


def _cm_pattern_viol(m, keepers, tol):
    n2 = m.shape[0]
    return [(i, j, abs(m[i, j])) for i in range(n2) for j in range(i + 1, n2)
            if (i, j) not in keepers and abs(m[i, j]) > tol]


def _cm_folded_family(m, tol=1e-9):
    """判定 folded 结果的交叉耦合族：anti / shifted / none / mixed。"""
    n2 = m.shape[0]
    sub = {(i, i + 1) for i in range(n2 - 1)}
    anti = max((abs(m[i, j]) for i, j in _cm_folded_keepers(n2) - sub),
               default=0.0)
    shifted = max((abs(m[i, j])
                   for i, j in _cm_folded_keepers_shifted(n2) - sub),
                  default=0.0)
    if anti <= tol and shifted <= tol:
        return "none"
    if anti > tol and shifted > tol:
        return "mixed"
    return "anti" if anti > tol else "shifted"


def _cm_sign_normalize(m, preserve_s21_phase=False):
    """节点 ±1 相似归一：M ← DMD，D=diag(1, d_1..d_N, d_L)，d_k=±1。

    规则（显式口径）：
    - 源节点永不翻（d_0=1）⟹ S11/S22 严格不变（D 与 W/q 交换，且
      Y→DYD、v→Dv 下 v_0 只乘 d_0）；
    - 主线耦合 m_{k−1,k} 逐个扫过（k=1..），real<0 即翻节点 k：
      默认 mainline_positive 口径扫到载端（k=L），m_{N,L} 归正——
      **代价是 S21 相位可能翻 180°**（S21×d_L，|S| 不变，参考面约定）；
    - preserve_s21_phase=True 只翻谐振器节点（k=1..N），载端 d_L=1
      ⟹ S21 相位与输入严格同相，末端 m_{N,L} 允许为负（下游相位对拍
      用此口径）。
    返回 (M, d)：d 为符号向量，d_L=+1 ⟺ S21 相位未翻。
    """
    M = m.copy()
    n2 = M.shape[0]
    d = np.ones(n2)
    k_last = n2 - 2 if preserve_s21_phase else n2 - 1
    for k in range(1, k_last + 1):
        if M[k - 1, k].real < 0:
            d[k] = -1.0
            M[k, :] *= -1
            M[:, k] *= -1
    return M, d


def _cm_s21_phase_flipped(m_in, m_out, tol=1e-6):
    """判定 m_out 相对 m_in 的 S21 相位是否翻 180°（|S| 严格不变的
    相似变换后唯一可见差异）。取带中心 Ω=0（|S21| 最大、相位最稳），
    |S21(0)| 过小时回退 Ω=±0.3 多数票。"""
    for w in (0.0, 0.3, -0.3):
        _, a = _cm_response_raw(m_in, 1.0, 1.0, w)
        _, b = _cm_response_raw(m_out, 1.0, 1.0, w)
        if abs(a) > tol and abs(b) > tol:
            return bool((b / a).real < 0)
    return False


def _cm_reduce_folded(m, tol=1e-13, preserve_s21_phase=False):
    """横向 → folded：经典 palindromic 旋转序列（Cameron；复正交合同旋转）。

    序列（0-based，S=N+2，轮次 i=1..S−3）：
    - 奇数轮 t=(i+1)/2：消行 r=t−1 的列 l=S−t−1 → t+1（右→左），
      pivot (l−1,l)，θ=atan(−M[r,l]/M[r,l−1])；
    - 偶数轮 t=i/2：消列 c=S−t 的行 k=t+1 → S−t−2（上→下），
      pivot (k,k+1)，θ=atan(M[k,c]/M[k+1,c])。
    每轮留一个"自动位" (t, S−t)（i+j=S 移位反对角）不显式消：对称 TZ
    对原型在偶 N 时它自动为零，在奇 N 时它恰是承载偶数 n_fz 的交叉耦合
    （TZ 计数规则，见 _cm_folded_keepers_shifted）。共 N(N−1)/2 次旋转，
    旋转全在谐振器块内（不触源/载节点），频响严格不变。
    输入须为横向矩阵（对角+源行+载列）；任意输入亦可跑，残留如实返回。
    preserve_s21_phase 语义见 _cm_sign_normalize（默认 mainline_positive
    可能把载端翻 −1 ⟹ S21 相位对输入翻 180°）。
    返回 (M, bad)：bad 为两族 keeper 中残留更小者的违例 [(i, j, |m|)]。
    """
    S = m.shape[0]
    M = m.astype(complex).copy()
    for i in range(1, S - 2):
        if i % 2 == 1:
            t = (i + 1) // 2
            r = t - 1
            for col in range(S - t - 1, t, -1):
                num, den = M[r, col], M[r, col - 1]
                if abs(num) < tol:
                    continue
                th = np.arctan(-num / den) if abs(den) > 0 else np.pi / 2
                M = _cm_cong_rot(M, col - 1, col, np.cos(th), -np.sin(th))
        else:
            t = i // 2
            col = S - t
            for r in range(t + 1, S - t - 1):
                num, den = M[r, col], M[r + 1, col]
                if abs(num) < tol:
                    continue
                th = np.arctan(num / den) if abs(den) > 0 else np.pi / 2
                M = _cm_cong_rot(M, r, r + 1, np.cos(th), -np.sin(th))
    M, _ = _cm_sign_normalize(M, preserve_s21_phase=preserve_s21_phase)
    bad_anti = _cm_pattern_viol(M, _cm_folded_keepers(S), 1e-9)
    bad_shift = _cm_pattern_viol(M, _cm_folded_keepers_shifted(S), 1e-9)
    bad = min((bad_anti, bad_shift),
              key=lambda b: max((v for _, _, v in b), default=0.0))
    return M, bad


@register_calculator(
    "chebyshev_prototype",
    "广义切比雪夫原型（chebyshev_g 等价形式）：阶数+回损+传输零点 → "
    "F/P/E 多项式系数与反射零点（Cameron 口径，S11=F/E, S21=P/(εE)）",
    (("order", "int - 滤波器阶数（≥1）"),
     ("rl_db", "float dB 带内回波损耗纹波（>0）"),
     ("transmission_zeros", "array 归一化低通传输零点 |Ω|>1 列表"
      "（±ω 成对口径，缺省=全极点）")),
    required=("order", "rl_db"),
)
def chebyshev_prototype(order: int, rl_db: float,
                        transmission_zeros: list | None = None) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    tz = tuple(float(z) for z in (transmission_zeros or []))
    if len(tz) > order // 2 or any(abs(z) <= 1.0 for z in tz):
        raise ValueError("TZ 对数须 ≤ order//2 且 |Ω|>1")
    proto = _gcheb_prototype(order, rl_db, tz)

    def cplx(p):
        return [[round(v.real, 9), round(v.imag, 9)] for v in p]

    return {"ok": True, "order": order, "rl_db": rl_db,
            "epsilon": round(proto["eps"], 9),
            "reflection_zeros": [round(r, 9) for r in proto["rz"]],
            "f_s": cplx(proto["f_s"]), "p_s": cplx(proto["p_s"]),
            "e_s": cplx(proto["e_s"])}


@register_calculator(
    "chebyshev_refl_fn",
    "全极点切比雪夫反射函数：n+rz_db+Ω → |S11|/|S21|（闭式 "
    "|S11|=ε|T_n(Ω)|/√(1+ε²T_n²)，带边 Ω=1 处纹波峰值=−RL）",
    (("n", "int - 阶数"),
     ("rz_db", "float dB 带内回损纹波（>0）"),
     ("omega", "array 归一化低通频率轴")),
    required=("n", "rz_db", "omega"),
)
def chebyshev_refl_fn(n: int, rz_db: float, omega: list) -> dict:
    n = int(n)
    if n < 1:
        raise ValueError("阶数必须 ≥1")
    if rz_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    w = np.asarray(omega, dtype=float)
    if w.size == 0:
        raise ValueError("omega 不能为空")
    eps = 1.0 / math.sqrt(10.0 ** (rz_db / 10.0) - 1.0)
    tn = np.ones_like(w)
    if n >= 1:
        t0v, t1v = np.ones_like(w), w.copy()
        for _ in range(n - 1):
            t0v, t1v = t1v, 2 * w * t1v - t0v
        tn = t1v
    s11 = eps * tn / np.sqrt(1.0 + eps ** 2 * tn ** 2)
    s21 = 1.0 / np.sqrt(1.0 + eps ** 2 * tn ** 2)
    return {"omega": [round(float(v), 9) for v in w],
            "s11_mag": [round(float(v), 9) for v in s11],
            "s21_mag": [round(float(v), 9) for v in s21],
            "s11_db": [round(float(20 * math.log10(max(v, 1e-300))), 6)
                       for v in s11]}


@register_calculator(
    "coupling_matrix_synthesize_n2",
    "Cameron N+2 耦合矩阵综合：广义切比雪夫原型 → (N+2)×(N+2) 矩阵"
    "（口径：首/末节点为源/载，外部导纳 q=(1,1) 归一化，耦合信息在 "
    "m0i/miL；复 Entries 允许，频响与原型逐点一致）",
    (("order", "int - 阶数（≥1）"),
     ("rl_db", "float dB 带内回损纹波（>0）"),
     ("transmission_zeros", "array 归一化低通传输零点 |Ω|>1 列表"
      "（±ω 成对口径，缺省=全极点）")),
    required=("order", "rl_db"),
)
def coupling_matrix_synthesize_n2(order: int, rl_db: float,
                                  transmission_zeros: list | None = None
                                  ) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    tz = tuple(float(z) for z in (transmission_zeros or []))
    proto = _gcheb_prototype(order, rl_db, tz)
    mt = _cm_transversal_exact(order, proto)
    err = _cm_poly_max_err(mt, proto)
    resid = err
    method = "cameron_residue"
    if err > 1e-8:  # 数值病态兜底（高阶多项式条件数）：LM 幅频精化
        # 采样点数须 ≥ 3·order 才使残差数 2n ≥ 未知数 6·order（否则 LM 直接抛
        # ValueError，见 c13-inc2 N=15）；order≤13 时与旧网格逐位一致。
        n_pts = min(max(41, 3 * order + 2), 8 * order + 9)
        wgrid = np.linspace(-0.99, 0.99, n_pts)
        mt, res = _cm_polish(order, proto, mt, wgrid)
        resid = float(np.max(np.abs(res.fun)))
        err = _cm_poly_max_err(mt, proto)
        method = "cameron_residue+lm"

    return {"ok": bool(err < 5e-5), "order": order,
            "rl_db": rl_db,
            "transmission_zeros": [round(z, 9) for z in tz],
            "epsilon": round(proto["eps"], 9),
            "external_q": [1.0, 1.0],
            "coupling_matrix": _cm_to_list(mt),
            "matrix_shape": [order + 2, order + 2],
            "method": method,
            "fit_residual": round(resid, 12),
            "response_max_err": round(err, 12),
            "note": "矩阵元素为 [re, im] 对（行优先）；频响经 "
                    "coupling_matrix_response 还原"}


@register_calculator(
    "coupling_matrix_arrow",
    "耦合矩阵拓扑约简（arrow）：N+2 全矩阵 → 三对角线+载端星形"
    "（复正交合同旋转 RMRᵀ，频响与原矩阵逐点一致）",
    (("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),),
    required=("matrix",),
)
def coupling_matrix_arrow(matrix: list) -> dict:
    m = _cm_from_list(matrix)
    marr = _cm_reduce_arrow(m)
    return {"ok": True, "coupling_matrix": _cm_to_list(marr),
            "matrix_shape": list(marr.shape),
            "note": "元素为 [re, im] 对（行优先）"}


@register_calculator(
    "coupling_matrix_folded",
    "耦合矩阵拓扑约简（folded）：N+2 横向矩阵 → 主线+交叉耦合（经典 "
    "palindromic 合同旋转序列，频响与原矩阵逐点一致；交叉耦合族自适应："
    "anti=i+j=N+1（偶 N）/ shifted=i+j=N+2（奇 N 偶数 TZ）；非横向输入"
    "的残留如实见 pattern_residual）。边界注记：复系数（真·非对称 TZ）"
    "输入不保证单族 folded 清洁——实测仅单侧 TZ 的偶 N（N3[2.0]）与奇 N"
    "全规范（N2[1.5]）落单族（anti/shifted，残差 0），其余非对称输入"
    "（N3[1.5,-2.0]/N4[1.2,2.5]/N5[1.5,2.5]）pattern_residual 0.2~0.8、"
    "family=mixed 如实返回（频响不变性不受影响）；复系数 folded 拓扑"
    "增量不在本内核（本版本冻结范围，另立增量）",
    (("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),
     ("sign_mode", "str - 符号归一口径：mainline_positive（默认，主线全正，"
      "S21 相位可能对输入翻 180°）| preserve_s21_phase（只翻谐振器节点，"
      "S21 相位与输入同相，末端 m_{N,L} 允许为负）")),
    required=("matrix",),
)
def coupling_matrix_folded(matrix: list, sign_mode: str = "mainline_positive"
                           ) -> dict:
    m = _cm_from_list(matrix)
    if sign_mode not in ("mainline_positive", "preserve_s21_phase"):
        raise ValueError("sign_mode 须为 mainline_positive|preserve_s21_phase")
    preserve = (sign_mode == "preserve_s21_phase")
    mfd, bad = _cm_reduce_folded(m, preserve_s21_phase=preserve)
    return {"ok": len(bad) == 0, "coupling_matrix": _cm_to_list(mfd),
            "matrix_shape": list(mfd.shape),
            "cross_family": _cm_folded_family(mfd),
            "sign_mode": sign_mode,
            "s21_phase_flipped_vs_input": _cm_s21_phase_flipped(m, mfd),
            "pattern_residual": round(max((v for _, _, v in bad),
                                          default=0.0), 12),
            "pattern_violations": [[i, j, round(v, 12)] for i, j, v in bad],
            "note": "元素为 [re, im] 对（行优先）；符号归一规则：源节点不翻"
                    "（S11/S22 严格不变），mainline_positive 把主线含 m_{N,L}"
                    " 全归正（S21 相位可能翻 180°），preserve_s21_phase 只翻"
                    "谐振器节点（S21 相位保持）"}


def _cm_from_list(matrix):
    arr = np.array(matrix, dtype=float)
    if arr.ndim == 3 and arr.shape[-1] == 2:
        return arr[..., 0] + 1j * arr[..., 1]
    if arr.ndim == 2:
        return arr.astype(complex)
    raise ValueError("matrix 须为 (N+2)×(N+2) 实矩阵或 [re, im] 对嵌套列表")


def _cm_to_list(m):
    # 12 位：9 位会把 folded 约简后 ~5e−10 的浮点噪声钉成 1e−9 假残留
    return [[[round(v.real, 12), round(v.imag, 12)] for v in row] for row in m]


@register_calculator(
    "coupling_matrix_response",
    "耦合矩阵理想频响（fake 裁判闭式）：给定 (N+2) 矩阵+频率轴，"
    "低通→带通映射 Ω=(f/f0−f0/f)/fbw，返回 S11/S21（复数+dB）",
    (("freq_ghz", "array GHz 频率轴"),
     ("f0_ghz", "float GHz 中心频率"),
     ("fbw", "float - 相对带宽（0<fbw≤1）"),
     ("matrix", "array (N+2)×(N+2) 嵌套列表 [re, im] 对或实数"),
     ("external_q", "array [q_in, q_out] 归一化外部导纳（本项目=1,1）"),
     ("z_ref", "float Ω 参考阻抗（默认 50，仅标注用）")),
    required=("freq_ghz", "f0_ghz", "fbw", "matrix"),
)
def coupling_matrix_response(freq_ghz: list, f0_ghz: float, fbw: float,
                             matrix: list, external_q: list | None = None,
                             z_ref: float = 50.0) -> dict:
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    f = np.asarray(freq_ghz, dtype=float)
    if f.size == 0 or np.any(f <= 0):
        raise ValueError("freq_ghz 须为正频率")
    m = _cm_from_list(matrix)
    qe = [1.0, 1.0] if external_q is None else [float(v) for v in external_q]
    if len(qe) != 2 or qe[0] <= 0 or qe[1] <= 0:
        raise ValueError("external_q 须为正的 [q_in, q_out]")
    omega = (f / f0_ghz - f0_ghz / f) / fbw
    s_list = []
    for om in omega:
        s11, s21 = _cm_response_raw(m, qe[0], qe[1], om)
        s_list.append((s11, s21))
    s_cube = np.zeros((f.size, 2, 2), dtype=complex)
    for i, (s11, s21) in enumerate(s_list):
        s_cube[i, 0, 0] = s11
        s_cube[i, 1, 0] = s21
        s_cube[i, 0, 1] = s21
        s_cube[i, 1, 1] = s11

    def c3(a):
        # a: (nfreq, 2, 2) 复 ndarray → [freq][row][col] = [re, im]
        return [[[[round(float(v.real), 9), round(float(v.imag), 9)]
                  for v in row] for row in mat] for mat in a]

    return {"ok": True, "freq_ghz": [round(float(v), 9) for v in f],
            "omega_norm": [round(float(v), 9) for v in omega],
            "z_ref": z_ref, "f0_ghz": f0_ghz, "fbw": fbw,
            "s_matrix": c3(s_cube),
            "s11_db": [round(float(20 * math.log10(max(abs(s11), 1e-300))),
                             6) for s11, _ in s_list],
            "s21_db": [round(float(20 * math.log10(max(abs(s21), 1e-300))),
                             6) for _, s21 in s_list],
            "note": "s_matrix 为 (nfreq,2,2)，元素 [re, im] 对；"
                    "S22=S11/S12=S21 为对称口径"}


# ─── 显式 TZ 集合原型 + EM 响应反提（2026-09-12）────────────────────
# 口径（Cameron 书 §6；#118 独立裁判 = 同参数的对称老路径 + 乘积形式直接求值）：
#   * 广义切比雪夫滤波函数对显式 TZ 集合（每个 ±Ω_k 单独列出）用乘积形式
#       C_N(Ω) = (1/2)[ Π_k (X_k+√(X_k²−1)) + 1/Π_k(…) ],
#       X_k(Ω) = Ω·√(κ_k²−1)/√(κ_k²−Ω²),  κ_k² = −z_k²（z_k 为 s 平面 TZ）；
#       无穷远 TZ 记 X=Ω。z=jΩ_k（|Ω_k|>1）给实频陷波。当 ±Ω_k 都列出时
#       X 相同 ⇒ Π 出现 Y_k²，与老路径「±对」口径逐位一致（单测钉住）。
#   * 实系数原型要求 TZ 集合对 s→s̄（Ω→−Ω）闭合。共轭闭合集合走实系数
#     路径；**非闭合集合（真·非成对 ±Ω）亦支持**：P(s) 复
#     系数，E 由推广 Feldtkeller H(s)=F·F†(−s)+P·P†(−s)/ε² 的复 Hurwitz
#     谱分解给出（_gcheb_prototype_explicit complex 分支，轴上幺正性
#     |S11|²+|S21|²=1 精确、单测钉住）。复系数原型响应 Ω→−Ω 不再对称
#     （非对称口径本体），且可继续综合为复对称 N+2 横向矩阵——Cameron
#     1999 §III-A 的 complex-even/complex-odd 实化即既有 D/Nu「取实部/
#     取 j×虚部」拆分（jω 轴 TZ 下 F 全实、P 低次幂交替纯虚、E 同构，
#     拆分后 D/Nu 皆实），实测 N=2..6 |S| 与原型一致 ≤1.3e−13（单测）。
#   * 原型 F/P/E：P(s)=Π(s−jΩ_k)，F(s)=κ·Π(s−j·rz)（κ 实，使 |C(1)|=1），
#     E 取 H(s)=F(s)F(−s)+P(s)P(−s)/ε² 的 Hurwitz 谱因子（s 域谱分解，与
#     老路径的 Ω² 偶多项式口径是两条独立代码路径；对称输入下 ≤1e−9 一致）。
#   * EM 反提（coupling_matrix_extract）：Cauchy 线性化有理拟合
#     S11=F/E、S21=P/E（实系数 + 公共分母 E，尺度归一化改善条件数）→ 相位
#     去旋转（吸收 j 规则）→ 符号四选一按「矩阵频响 vs 数据」判定 →
#     Cameron Y 留数法（_cm_transversal_exact）重建 N+2 矩阵。f0 由拟合残差
#     一维精化（可辨识）；**fbw 由 S 参数形状不可辨识**（任何 fbw 缩放均可被
#     有理函数吸收），故无输入时按纹波带边（|S11|=纹波电平的外沿交点）估计。

def _tz_explicit_check(order, tz_omega):
    """显式 TZ 列表校验：有限值、|Ω|>1、个数 ≤ 阶数。

    Ω→−Ω 共轭闭合**不再强制**：非闭合集合（真·非成对 ±Ω）返回
    closed=False，由 _gcheb_prototype_explicit 走复系数谱分解路径。
    返回 (tz, closed)。
    """
    order = int(order)
    tz = [float(z) for z in tz_omega]
    if any((not math.isfinite(z)) or abs(z) <= 1.0 for z in tz):
        raise ValueError("有限传输零点须为有限值且满足 |Ω|>1（带外）")
    if len(tz) > order:
        raise ValueError(f"有限 TZ 个数 {len(tz)} 超出阶数 {order}")
    closed = all(any(abs(-z - y) <= 1e-9 for y in tz) for z in tz)
    return tz, closed


def _gcheb_x_factor(z_splane, w):
    """X_k(Ω)：z 为 s 平面 TZ；X=Ω√(κ²−1)/√(κ²−Ω²)，κ²=−z²（共轭安全分支）。"""
    w = np.asarray(w, dtype=complex)
    s2 = -complex(z_splane) ** 2
    num = np.lib.scimath.sqrt(np.asarray(s2 - 1.0, dtype=complex))
    den = np.lib.scimath.sqrt(s2 - w * w)
    return w * num / den


def _gcheb_fn_explicit(tz_omega, n_inf, w):
    """显式 TZ 集合的广义切比雪夫滤波函数 C_N(Ω)（复主值分支）。"""
    w = np.asarray(w, dtype=complex)
    prod = np.ones_like(w)
    for z in tz_omega:
        x = _gcheb_x_factor(1j * float(z), w)
        prod = prod * (x + np.lib.scimath.sqrt(x * x - 1.0))
    for _ in range(int(n_inf)):
        x = w
        prod = prod * (x + np.lib.scimath.sqrt(x * x - 1.0))
    return 0.5 * (prod + 1.0 / prod)


def _gcheb_reflection_zeros_explicit(tz_omega, n_inf, n_grid=4001):
    """C_N 在 (−1,1) 内的 N 个零点（单调扫频 + 对分，#118 不赌收敛）。"""
    wgrid = np.linspace(-1.0 + 1e-12, 1.0 - 1e-12, n_grid)
    fn = np.real(_gcheb_fn_explicit(tz_omega, n_inf, wgrid))
    idx = np.where(np.diff(np.sign(fn)) != 0)[0]
    order = len(tz_omega) + int(n_inf)
    if len(idx) != order:
        raise ValueError(f"反射零点数 {len(idx)} != 阶数 {order}")
    roots = []
    for i in idx:
        a, b, fa = wgrid[i], wgrid[i + 1], fn[i]
        for _ in range(80):
            m = 0.5 * (a + b)
            fm = float(np.real(
                _gcheb_fn_explicit(tz_omega, n_inf, np.array([m]))[0]))
            if fm == 0.0:
                a = b = m
                break
            if np.sign(fm) == np.sign(fa):
                a, fa = m, fm
            else:
                b = m
        roots.append(0.5 * (a + b))
    return np.array(sorted(roots))


def _gcheb_prototype_explicit(order, rl_db, tz_omega):
    """显式 TZ 集合 → (ε, rz, F/P/E)：共轭闭合走实系数 s 域谱分解
    （独立于老路径），非闭合走复系数谱分解（真·非对称口径）。

    复系数路径（tz 不对 Ω→−Ω 闭合时）：Feldtkeller 多项式推广为
    H(s) = F(s)·F†(−s) + P(s)·P†(−s)/ε²，其中 F†(−s) = 系数共轭 ×
    (−s) 次幂符号（实系数时退化为 F(−s)）；E 取 H 的 Hurwitz 半边
    （Re(s)<0 的根）× 复尺度 c（|c|²(−1)^N = H 首项 ⟹ 轴上幺正性
    |S11|²+|S21|²=1 精确成立；相位 gauge 取 arg f_N，实系数时退化为
    正实尺度）。反射零点提取不受影响：jΩ 轴 TZ（|Ω_k|>1）给实 κ_k，
    滤波函数 C_N(Ω) 在 (−1,1) 内仍实值。响应 |S21(Ω)| 不再 Ω→−Ω 对称
    ——这正是非对称口径。复系数原型可继续综合为复对称横向矩阵
    （complex-even/odd 实化构造，见 _cm_transversal_exact，Cameron 1999
    §III-A 口径，实测 N=2..6 |S| 一致 ≤1.3e−13）。
    """
    order = int(order)
    tz, closed = _tz_explicit_check(order, tz_omega)
    n_inf = order - len(tz)
    eps = 1.0 / math.sqrt(10.0 ** (rl_db / 10.0) - 1.0)
    rz = _gcheb_reflection_zeros_explicit(tz, n_inf)
    f0 = np.atleast_1d(np.poly(1j * rz))            # Π(s−j·rz)，未归一
    p_s = np.atleast_1d(np.poly([1j * z for z in tz]))  # P(s)=Π(s−jΩ_k)
    k = abs(np.polyval(p_s, 1j) / np.polyval(f0, 1j))   # C(1)=±1 ⇒ |F(1)|=|P(1)|
    f_s = k * f0
    fm = np.array([np.conj(c) * (-1.0) ** (len(f_s) - 1 - i)
                   for i, c in enumerate(f_s)])
    pm = np.array([np.conj(c) * (-1.0) ** (len(p_s) - 1 - i)
                   for i, c in enumerate(p_s)])
    h = np.polyadd(np.polymul(f_s, fm), np.polymul(p_s, pm) / eps ** 2)
    hmax = float(np.max(np.abs(h))) if h.size else 0.0
    if closed:
        if np.max(np.abs(h.imag)) > 1e-8 * max(hmax, 1.0):
            raise ValueError("谱多项式非实系数：TZ 集合未共轭闭合")
        h = np.trim_zeros(np.real(h), "f")
        deg = len(h) - 1
        g = np.array([c for i, c in enumerate(h) if (deg - i) % 2 == 0])
        roots = []
        for y in np.roots(g):
            s = np.lib.scimath.sqrt(complex(y))
            if s.real > 0 or (s.real == 0 and s.imag < 0):
                s = -s
            roots.append(s)
        e0 = np.poly(roots)
        j = 1j
        ee = np.polyval(e0, j) * np.polyval(e0, -j)
        hv = (np.polyval(f_s, j) * np.polyval(f_s, -j)
              + np.polyval(p_s, j) * np.polyval(p_s, -j) / eps ** 2)
        e_s = e0 * np.sqrt(complex(hv / ee))
        if np.max(np.abs(e_s.imag)) < 1e-9:
            e_s = np.real(e_s)
    else:
        n_deg = len(f_s) - 1
        lead = h[0] * (-1.0) ** n_deg        # |c|²(−1)^N·(−1)^N = h[0]
        if abs(lead.imag) > 1e-7 * max(abs(lead), 1.0):
            raise ValueError(f"谱多项式首项非实正（{lead}）：数值病态")
        roots_h = np.roots(h)
        hurwitz = [r for r in roots_h if r.real < 0.0]
        if len(hurwitz) != n_deg:
            n_axis = sum(1 for r in roots_h if abs(r.real) <= 1e-8)
            raise ValueError(
                f"复系数谱分解失败：Hurwitz 半边根 {len(hurwitz)} != "
                f"阶数 {n_deg}（jω 轴根 {n_axis} 个）")
        e0 = np.poly(hurwitz)
        c_abs = math.sqrt(lead.real)
        e_s = e0 * (c_abs * np.exp(1j * np.angle(f_s[0])))
    return {"eps": eps, "rz": rz, "f_s": f_s, "p_s": p_s, "e_s": e_s,
            "tz_omega": tz, "tz_conjugate_closed": closed,
            "coefficient_domain": "real" if closed else "complex"}


@register_calculator(
    "chebyshev_prototype_asym",
    "广义切比雪夫原型（显式 TZ 集合口径）：阶数+回损+完整 TZ 列表（每个 Ω "
    "单独列出）→ F/P/E 多项式与反射零点。±Ω 共轭闭合输入走实系数 s 域谱"
    "分解（与 chebyshev_prototype 数值一致 ≤1e−9）；非闭合（真·非对称）"
    "输入走复系数谱分解（推广 Feldtkeller 的 Hurwitz 半边），轴上幺正性"
    "保持、响应 Ω→−Ω 不再对称；可继续综合为复对称 N+2 耦合矩阵（见 "
    "coupling_matrix_synthesize_explicit）",
    (("order", "int - 滤波器阶数（≥1）"),
     ("rl_db", "float dB 带内回波损耗纹波（>0）"),
     ("transmission_zeros", "array 显式 TZ 列表（每项一个 Ω；成对输入=实系数"
      "路径，非成对输入=复系数路径）")),
    required=("order", "rl_db", "transmission_zeros"),
)
def chebyshev_prototype_asym(order: int, rl_db: float,
                             transmission_zeros: list) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    proto = _gcheb_prototype_explicit(order, rl_db, transmission_zeros)

    def cplx(p):
        return [[round(v.real, 9), round(v.imag, 9)] for v in p]

    return {"ok": True, "order": order, "rl_db": rl_db,
            "epsilon": round(proto["eps"], 9),
            "reflection_zeros": [round(r, 9) for r in proto["rz"]],
            "transmission_zeros": [round(z, 9) for z in proto["tz_omega"]],
            "tz_conjugate_closed": proto["tz_conjugate_closed"],
            "coefficient_domain": proto["coefficient_domain"],
            "f_s": cplx(proto["f_s"]), "p_s": cplx(proto["p_s"]),
            "e_s": cplx(proto["e_s"]),
            "note": "F/P/E 为 s 域多项式系数（降幂）；S11=F/E、S21=P/(εE)。"
                    "复系数路径（coefficient_domain=complex）的响应 Ω→−Ω "
                    "不对称；N+2 综合走 coupling_matrix_synthesize_explicit"}


@register_calculator(
    "coupling_matrix_synthesize_explicit",
    "显式 TZ 集合综合（Cameron N+2）：完整 TZ 列表（每个 Ω 单独列出；"
    "±Ω 成对=实系数原型，与 coupling_matrix_synthesize_n2 同口径；非成对"
    "=复系数原型，响应 Ω→−Ω 不对称）→ (N+2)×(N+2) 横向矩阵，频响与原型"
    "逐点一致（幅度；复系数路径实测 ≤1.3e−13）。复元矩阵为复对称 M=Mᵀ，"
    "非对称网络 |m_0k| 与 |m_kL| 允许不等",
    (("order", "int - 阶数（≥1）"),
     ("rl_db", "float dB 带内回损纹波（>0）"),
     ("transmission_zeros", "array 显式 TZ 列表（每项一个 Ω，|Ω|>1，"
      "个数 ≤ 阶数）")),
    required=("order", "rl_db", "transmission_zeros"),
)
def coupling_matrix_synthesize_explicit(order: int, rl_db: float,
                                        transmission_zeros: list) -> dict:
    order = int(order)
    if order < 1:
        raise ValueError("阶数必须 ≥1")
    if rl_db <= 0:
        raise ValueError("回损纹波必须 >0 dB")
    proto = _gcheb_prototype_explicit(order, rl_db, transmission_zeros)
    mt = _cm_transversal_exact(order, proto)
    err = _cm_poly_max_err(mt, proto)
    resid = err
    method = "cameron_residue"
    if err > 1e-8:  # 数值病态兜底（高阶多项式条件数）：LM 幅频精化
        n_pts = min(max(41, 3 * order + 2), 8 * order + 9)
        wgrid = np.linspace(-0.99, 0.99, n_pts)
        mt, res = _cm_polish(order, proto, mt, wgrid)
        resid = float(np.max(np.abs(res.fun)))
        err = _cm_poly_max_err(mt, proto)
        method = "cameron_residue+lm"
    return {"ok": bool(err < 5e-5), "order": order, "rl_db": rl_db,
            "transmission_zeros": [round(z, 9) for z in proto["tz_omega"]],
            "tz_conjugate_closed": proto["tz_conjugate_closed"],
            "coefficient_domain": proto["coefficient_domain"],
            "epsilon": round(proto["eps"], 9),
            "external_q": [1.0, 1.0],
            "coupling_matrix": _cm_to_list(mt),
            "matrix_shape": [order + 2, order + 2],
            "method": method,
            "fit_residual": round(resid, 12),
            "response_max_err": round(err, 12),
            "note": "矩阵元素为 [re, im] 对（行优先）；q=(1,1) 归一化；"
                    "频响经 coupling_matrix_response 还原（幅度）；"
                    "复系数路径的非对称网络 m_0k/m_kL 无镜像关系"}


# ─── EM 响应反提（Cauchy 有理拟合 → Cameron Y 留数 N+2 矩阵）─────────────────

def _cm_as_complex(seq, name, n_expected):
    arr = np.asarray(seq)
    if arr.ndim == 2 and arr.shape[-1] == 2:
        out = arr.astype(float)
        out = out[..., 0] + 1j * out[..., 1]
    elif np.iscomplexobj(arr):
        out = arr.astype(complex)
    else:
        out = np.asarray(seq, dtype=float).astype(complex)
    if out.ndim != 1:
        raise ValueError(f"{name} 须为一维序列（[re,im] 对或复数）")
    if len(out) != n_expected:
        raise ValueError(f"{name} 长度 {len(out)} != 频率点数 {n_expected}")
    return out


def _cm_rational_fit(omega, s11, s21, order, nz):
    """线性化有理拟合 S11≈F/E、S21≈P/E（实系数 + 公共分母 E，E 首一）。

    条件数改善：以 u=s/max|s| 为基底拟合后再精确换回 s 域（对角缩放）。
    返回 (f_s, p_s, e_s) s 域降幂系数数组。
    """
    s = 1j * np.asarray(omega, dtype=complex)
    scale = max(float(np.max(np.abs(s))), 1e-30)
    u = s / scale
    n_f, n_p, n_e = order + 1, nz + 1, order
    nu = n_f + n_p + n_e
    m = len(s)
    a = np.zeros((2 * m, nu), dtype=complex)
    b = np.zeros(2 * m, dtype=complex)
    for i in range(m):
        ui = u[i]
        rowf = ui ** np.arange(order, -1, -1)
        rowp = ui ** np.arange(nz, -1, -1)
        rowe = ui ** np.arange(order - 1, -1, -1)
        a[2 * i, 0:n_f] = rowf
        a[2 * i, n_f + n_p:] = -s11[i] * rowe
        b[2 * i] = s11[i] * ui ** order
        a[2 * i + 1, n_f:n_f + n_p] = rowp
        a[2 * i + 1, n_f + n_p:] = -s21[i] * rowe
        b[2 * i + 1] = s21[i] * ui ** order
    x, *_ = np.linalg.lstsq(a, b, rcond=None)

    def to_s(c):
        d = len(c) - 1
        return np.array([c[k] / scale ** (d - k) for k in range(d + 1)],
                        dtype=complex)

    e_s = np.concatenate([[1.0], x[n_f + n_p:]])
    return to_s(x[:n_f]), to_s(x[n_f:n_f + n_p]), to_s(e_s)


def _cm_fit_rms(f_s, p_s, e_s, omega, s11, s21):
    s = 1j * np.asarray(omega, dtype=complex)
    e = np.polyval(e_s, s)
    e = np.where(np.abs(e) < 1e-300, 1e-300 + 0j, e)
    r11 = np.polyval(f_s, s) / e - s11
    r21 = np.polyval(p_s, s) / e - s21
    return float(np.sqrt(np.mean(np.abs(r11) ** 2 + np.abs(r21) ** 2)))


def _cm_derotate(v):
    """去旋转：找 θ 使 e^{−jθ}v 的虚部最小（⇒ 实系数多项式），返回 (实向量, θ)。"""
    re, im = v.real, v.imag
    aa = float(np.sum(re ** 2 - im ** 2))
    bb = float(np.sum(re * im))
    if abs(aa) < 1e-300 and abs(bb) < 1e-300:
        return v.real.copy(), 0.0
    th = 0.5 * math.atan2(2.0 * bb, aa)
    w = v * np.exp(-1j * th)
    if w[0].real < 0:
        w = -w
    return w.real.copy(), th


def _cm_derotation_residual(v):
    """归一化去旋转残差 ‖Im(e^{−jθ}v)‖/‖v‖（θ 取虚部能量最小旋转）。

    实系数数据与 jΩ 轴 TZ 集的 F 实测 ≤1e−8（复原型 5 例 4.3e−10…9.2e−9）；
    真·复系数（非对称 TZ）P 为 O(0.15–0.7)——以 1e−6 为界分流 extract 的
    实/复路径（实测见 test_coupling_matrix 复往返用例）。
    """
    v = np.asarray(v, dtype=complex)
    nrm = float(np.linalg.norm(v))
    if nrm == 0.0:
        return 0.0
    _, th = _cm_derotate(v)
    return float(np.linalg.norm((v * np.exp(-1j * th)).imag) / nrm)


def _cm_band_edges(freq, s11_db, tol_db=0.05):
    """纹波带边：|S11| 与纹波电平的（外沿）交点，抛物线插值定位。

    返回 (f_lo, f_hi)；识别不到返回 None。
    """
    freq = np.asarray(freq, dtype=float)
    y = np.asarray(s11_db, dtype=float)
    n = len(freq)
    peaks = [i for i in range(1, n - 1) if y[i] >= y[i - 1] and y[i] > y[i + 1]]
    if len(peaks) < 2:
        return None
    # 纹波电平：以「深零点（反射零点）」围出的带内区间为准——最深谷之间
    # 的最高点即纹波峰（对 rl_db 很小/噪声格点稳健，避免被极低伪峰带偏）。
    top = max(y[i] for i in peaks)
    mins = [i for i in range(1, n - 1) if y[i] <= y[i - 1] and y[i] < y[i + 1]]
    deep = [i for i in mins if y[i] < top - 2.0]
    if len(deep) >= 1:
        i0, i1 = min(deep), max(deep)
        lvl = float(np.max(y[i0:i1 + 1]))
        starts = (i0, i1)
    else:
        lvl = min(y[i] for i in peaks)
        starts = (int(np.argmin(y)), int(np.argmin(y)))

    def edge(direction):
        i = starts[0] if direction < 0 else starts[1]
        while 0 <= i + direction < n and y[i + direction] <= lvl + tol_db:
            i += direction
        j = i + direction
        if not (0 <= i < n and 0 <= j < n):
            return None
        xs = ([freq[i - 1], freq[i], freq[j]] if direction > 0
              else [freq[j], freq[i], freq[i + 1]])
        if len(xs) != 3 or min(xs) == max(xs):
            return None
        ys = ([y[i - 1], y[i], y[j]] if direction > 0
              else [y[j], y[i], y[i + 1]])
        coef = np.polyfit(xs, ys, 2)
        rr = [r.real for r in np.roots(coef - np.array([0.0, 0.0, lvl]))
              if abs(r.imag) < 1e-9 and min(xs) <= r.real <= max(xs)]
        return float(rr[0]) if rr else float(freq[i])

    lo, hi = edge(-1), edge(1)
    if lo is None or hi is None or not (0 < lo < hi):
        return None
    return lo, hi


def _cm_refine_f0(freq, s11, s21, order, nz, f0_lo, f0_hi, fbw,
                  rounds=26, n_scan=11):
    """f0 一维精化：有理拟合残差在真 f0 处→0（f0 可辨识，fbw 尺度不可辨识）。

    多轮栅格收窄（#118：不赌单轮收敛），末轮步长 ~ (0.04)^rounds 带宽。
    """

    def residual(f0):
        try:
            om = (freq / f0 - f0 / freq) / fbw
            f_s, p_s, e_s = _cm_rational_fit(om, s11, s21, order, nz)
            return _cm_fit_rms(f_s, p_s, e_s, om, s11, s21)
        except (ValueError, np.linalg.LinAlgError):
            return float("inf")

    lo, hi = float(f0_lo), float(f0_hi)
    mid = 0.5 * (lo + hi)
    for _ in range(rounds):
        grid = np.linspace(lo, hi, n_scan)
        scored = [(residual(float(g)), float(g)) for g in grid]
        r, mid = min(scored, key=lambda t: t[0])
        half = (hi - lo) * 0.25
        lo, hi = mid - half, mid + half
        if not (np.isfinite(r) and half > 0):
            break
    return mid


def _cm_refine_ref_delay(freq, s11, s21, f0, fbw, order, nz, tau_hi_s,
                         rounds=20, n_scan=11):
    """参考面时延 τ̂ 一维精化（仿 _cm_refine_f0）。

    目标 = 有理拟合残差最小：对候选 τ 做 S11×e^{+j2πf·2τ}、
    S21×e^{+j2πf·2τ}（对称参考面，tau_in=tau_out=τ）后拟合。
    多轮栅格收窄（#118：不赌单轮收敛），末轮步长 ~(0.25)^rounds·τ_hi。
    τ_hi 缺省建议 1/f0（一个周期，物理时延上限量级）。
    """
    from rfauto.core.deembed import deembed_reference_delay

    freq = np.asarray(freq, dtype=float)
    f_hz = freq * 1e9
    om = (freq / f0 - f0 / freq) / fbw

    def residual(tau):
        try:
            s11c, s21c = deembed_reference_delay(f_hz, s11, s21, tau, tau)
            f_s, p_s, e_s = _cm_rational_fit(om, s11c, s21c, order, nz)
            return _cm_fit_rms(f_s, p_s, e_s, om, s11c, s21c)
        except (ValueError, np.linalg.LinAlgError):
            return float("inf")

    lo, hi = 0.0, float(tau_hi_s)
    mid = 0.5 * (lo + hi)
    for _ in range(rounds):
        grid = np.linspace(lo, hi, n_scan)
        scored = [(residual(float(g)), float(g)) for g in grid]
        r, mid = min(scored, key=lambda t: t[0])
        half = (hi - lo) * 0.25
        lo, hi = mid - half, mid + half
        if not (np.isfinite(r) and half > 0):
            break
    return float(mid)


# ─── |S|² 幅值域反提（2026-09-15 定稿）─────────────────────
# 口径：|S11(Ω)|² = F(jΩ)F(−jΩ) / E(jΩ)E(−jΩ) 是 x=Ω² 的实有理函数
#   （实系数 ⟹ conj F(jΩ)=F(−jΩ)），对相位污染数据天然免疫（只吃幅值）。
#   线性化：A(x) − |S11|²·B(x) = |S11|²·x^N（B 首一）+ S21² 同 B 共享，
#   行均衡化 lstsq（Vandermonde 动态范围 3+ 量级，否则 A 的二重根分辨不动）。
#   谱分解：G(s)=A(−s²)=F(s)F(−s)；E 取 G_B 的 Re(s)<0 半（Hurwitz，
#   ± 配对）；F/P 的根在 jΩ 轴 ⟹ G 的每根二重（实系数 F 的根 ±jω 成共轭
#   对 ⟹ F(s)F(−s)=(−1)^N F(s)² 完全平方），按 (Im,Re) 排序后相邻聚对取
#   中点。尺度：F=√(a_N/b_N)·F_m、P=√(c_nz/b_N)·P_m、E=E_m（首一）。
# 诚实边界（精度损失）：①幅值只定 |F|/|E| 的模，F 全局符号与 P 全局符号
#   不可辨识（下游符号枚举按 |S| 裁决）；②单侧 TZ 的 ±Ω 符号不可辨识
#   （|S21| 对 Ω→−Ω 对称），transmission_zeros_cplx 报 ± 对；③f0 精化
#   （复域可辨识性）不在幅值路径——f0/fbw 建议显式给定，缺省带边估计。

def _x_to_s_even(coef_x_asc):
    """A(x) 升幂系数（x=Ω²）→ G(s)=A(−s²) 降幂系数（偶次实多项式）。"""
    deg = len(coef_x_asc) - 1
    g = np.zeros(2 * deg + 1)
    for k, ak in enumerate(coef_x_asc):
        g[2 * (deg - k)] = ak * (-1.0) ** k
    return g


def _cm_spectral_factor(coef_x_asc, n, kind):
    """A(s)A(−s)=A(−s²) 型偶多项式的谱因子（首一 V(s)，n 次）。

    kind="hurwitz"（E）：根成 {s0,−s0} 对，取 Re<0 支；
    kind="axis"（F/P）：根在 jΩ 轴且每根二重（实系数 ⟹ 完全平方），
    按 (Im,Re) 排序后相邻聚对取中点（扰动 ≪ 根间距）。
    """
    rts = np.roots(_x_to_s_even(coef_x_asc))
    if len(rts) != 2 * n:
        raise ValueError(f"谱多项式根数 {len(rts)} != {2 * n}")
    pool = list(rts)
    picked = []
    if kind == "hurwitz":
        scale = max(1.0, float(np.max(np.abs(rts))))
        while pool:
            r = pool.pop(0)
            if not pool:
                raise ValueError("Hurwitz 谱分解根配对落单")
            j = min(range(len(pool)), key=lambda q: abs(pool[q] + r))
            twin = pool.pop(j)
            if abs(twin + r) > 1e-4 * scale:
                raise ValueError("谱分解根未成 ± 对（数据非无耗一致）")
            picked.append(r if r.real < twin.real else twin)
    else:
        ordered = sorted(rts, key=lambda z: (round(z.imag, 9),
                                             round(z.real, 9)))
        picked = [0.5 * (ordered[2 * k] + ordered[2 * k + 1])
                  for k in range(n)]
    v = np.poly(picked) if picked else np.array([1.0 + 0j])
    return v / v[0]


def _cm_mag2_fit(omega, mag11, mag21, order, nz):
    """|S11|、|S21| 幅值 → (F, P, E)（E 首一，ε 折入 P）+ |S| 域幅度 rms。

    确定性内核：行均衡化实数 lstsq + 谱分解（根配对口径见上方注释块）。
    数据非无耗一致（谱分解配对失败/首项非正）时抛 ValueError。
    """
    omega = np.asarray(omega, dtype=float)
    x = omega ** 2
    xs = float(np.max(x))
    if xs <= 0.0:
        raise ValueError("omega 全为 0，幅值域拟合不可分")
    xn = x / xs
    y11 = np.asarray(mag11, dtype=float) ** 2
    y21 = np.asarray(mag21, dtype=float) ** 2
    n_a, n_b, n_c = order + 1, order, nz + 1
    ntot = n_a + n_b + n_c
    m = len(xn)
    mat = np.zeros((2 * m, ntot))
    vec = np.zeros(2 * m)
    xp = np.vander(xn, order + 1, increasing=True)
    for i in range(m):
        mat[i, :n_a] = xp[i]
        mat[i, n_a:n_a + n_b] = -y11[i] * xp[i, :n_b]
        vec[i] = y11[i] * xn[i] ** order
        mat[m + i, n_a:n_a + n_b] = -y21[i] * xp[i, :n_b]
        mat[m + i, n_a + n_b:] = xp[i, :n_c]
        vec[m + i] = y21[i] * xn[i] ** order
    rn = np.max(np.abs(mat), axis=1)
    rn[rn == 0.0] = 1.0
    sol, *_ = np.linalg.lstsq(mat / rn[:, None], vec / rn, rcond=None)
    a = sol[:n_a] / (xs ** np.arange(n_a))
    b = (np.concatenate([sol[n_a:n_a + n_b], [1.0]])
         / (xs ** np.arange(n_b + 1)))
    c = sol[n_a + n_b:] / (xs ** np.arange(n_c))
    lead = float(b[-1])
    if not (lead > 0.0) or not (float(a[-1]) >= 0.0) \
            or not (float(c[-1]) >= 0.0):
        raise ValueError("幅值域拟合首项非正（数据非无耗一致响应）")
    e_s = _cm_spectral_factor(b, order, "hurwitz")
    f_s = _cm_spectral_factor(a, order, "axis") * math.sqrt(a[-1] / lead)
    if nz > 0:
        p_s = (_cm_spectral_factor(c, nz, "axis")
               * math.sqrt(c[-1] / lead))
    else:
        p_s = np.array([math.sqrt(c[-1] / lead)])
    ev = 1j * omega
    e_val = np.polyval(e_s, ev)
    r11 = np.abs(np.polyval(f_s, ev) / e_val) - np.asarray(mag11, dtype=float)
    r21 = np.abs(np.polyval(p_s, ev) / e_val) - np.asarray(mag21, dtype=float)
    rms = float(np.sqrt(np.mean(r11 ** 2 + r21 ** 2)))
    return f_s, p_s, e_s, rms


_CM_DEROT_COMPLEX_TOL = 1e-6


def _cm_extract_from_fit(order, f_s, p_s, e_s, omega, s11, s21,
                         phase_ref="unknown"):
    """由拟合多项式重建 N+2 矩阵：实/复路径分流 + 符号枚举。

    路径分流（2026-09-15 定稿）：旧实现无条件 _cm_derotate
    实化 F/P——对复系数（真·非对称 TZ）响应，实化直接摧毁矩阵（实测
    fit_rms=5.8e−10 但 kij 误差达 1.4~2e5、带内幺正性偏差 0.69 仍
    ok=True 的假绿，#122）。现按归一化去旋转残差分流：
    - max(δ_F, δ_P) < _CM_DEROT_COMPLEX_TOL（实系数数据，实测 ~1e−12）：
      既有实路径（实化 + 符号四选一，裁判 (|S| 逐点, 复值误差) 字典序）；
    - 否则复路径：F/P 不实化直进 _cm_transversal_exact（inc3 已证复原型
      支持）。符号枚举裁判按 phase_ref：
      "known"（已知参考面的综合往返）= 复值逐点最大误差；
      "unknown"（EM 参考面未知）= 保留 (|S| 逐点, 复值误差) 字典序
      （|S| 相位无关；复值误差仅在同幅值符号组内做确定性决断）。
      _cm_sign_normalize 的 .real<0 归一在复路径语义不适用（复元符号
      无「正负」物理约定），故复路径跳过节点符号归一，符号仅经枚举定。

    返回 (report, 矩阵)：report = {mag_max_err, cx_max_err, derot_f,
    derot_p, path}；数据结构不满足横向矩阵口径时返回 None。
    """
    derot_f = _cm_derotation_residual(f_s)
    derot_p = _cm_derotation_residual(p_s)
    use_complex = max(derot_f, derot_p) >= _CM_DEROT_COMPLEX_TOL
    es = np.asarray(e_s, dtype=complex)
    if use_complex:
        fr = np.asarray(f_s, dtype=complex)
        pr = np.asarray(p_s, dtype=complex)
        # 规范旋转（gauge）：_cm_transversal_exact 的 D/Nu 实/虚拆分要求
        # (F,P,E) 在 canonical 族（首项系数实，见 _gcheb_prototype_explicit
        # 的 gauge c=|c|·e^{j·arg f_N} 且 f_N 实 ⟹ 三项首项皆实）。extract
        # 的 E-首一归一化引入复尺度 e_N，破坏该族——以 F 首项相位 θg =
        # arg(F[0]) 旋转全部三项（F 首项=实 k>0/e_N ⟹ θg=−arg(e_N)=0 或 π，
        # 旋转=±1 实尺度，拆分不变量成立；P 首项相位 −2·arg(e_N)≡0 同归
        # 实正）。逐例实测：无此旋转时 (N−n_fz) 偶（jP 规则）路径重建
        # 全炸（kij 误差 ~1e5）。
        g = np.exp(1j * np.angle(fr[0]))
        fr = fr * g
        pr = pr * g
        es = es * g
    else:
        fr, _ = _cm_derotate(f_s)
        pr, _ = _cm_derotate(p_s)
    best = None
    p_phases = (1.0, -1.0, 1j, -1j) if use_complex else (1.0, -1.0)
    for sf in (1.0, -1.0):
        for pp in p_phases:
            try:
                m = _cm_transversal_exact(order, {
                    "eps": 1.0, "e_s": es,
                    "f_s": (sf * fr).astype(complex),
                    "p_s": (pp * pr).astype(complex)})
            except (ValueError, np.linalg.LinAlgError):
                continue
            mag_err = 0.0
            ph_err = 0.0
            for i, w in enumerate(omega):
                c11, c21 = _cm_response_raw(m, 1.0, 1.0, w)
                mag_err = max(mag_err, abs(abs(c11) - abs(s11[i])),
                              abs(abs(c21) - abs(s21[i])))
                ph_err = max(ph_err, abs(c11 - s11[i]), abs(c21 - s21[i]))
            # 裁判：|S| 逐点（相位无关，EM 参考面未知）为主，复值误差仅作同级微调
            score = (ph_err if (use_complex and phase_ref == "known")
                     else (mag_err, ph_err))
            if best is None or score < best[0]:
                best = (score, m, mag_err, ph_err)
    if best is None:
        return None
    _, m, mag_err, ph_err = best
    return {"mag_max_err": float(mag_err), "cx_max_err": float(ph_err),
            "derot_f": float(derot_f), "derot_p": float(derot_p),
            "path": "complex" if use_complex else "real"}, m


@register_calculator(
    "coupling_matrix_extract",
    "EM/电路响应反提：频轴+复 S11/S21(+阶数) → f0、FBW、外部 Q、N+2 耦合"
    "矩阵与拟合残差。Cauchy 线性化有理拟合（S11=F/E, S21=P/E）→ Cameron Y 留数"
    "重建；f0 由拟合精化，fbw 无输入时按纹波带边估计（形状不可辨识，见 note）"
    "；domain=magnitude 走 |S|² 幅值域（相位污染数据兜底，精度损失见 note）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数；magnitude 域取模）"),
     ("s21", "array 复 S21（[re,im] 对或复数；magnitude 域取模）"),
     ("order", "int 阶数（缺省=自动判阶）"),
     ("f0_ghz", "float GHz 中心频率（缺省=由拟合估计）"),
     ("fbw", "float 相对带宽（缺省=由纹波带边估计）"),
     ("phase_ref", "str complex 域符号枚举裁判：unknown（缺省，|S| 相位无关）|"
      "known（已知参考面，复值逐点）"),
     ("domain", "str complex（缺省，复 S 全信息）| magnitude（|S|² 幅值域）"),
     ("ref_delay_s", "float 对称参考面时延 τ(s)，complex 域反推后再拟合"),
     ("ref_delay_scan", "bool true=按拟合残差最小一维扫描 τ̂（仿 f0 精化）")),
    required=("freq_ghz", "s11", "s21"),
)
def coupling_matrix_extract(freq_ghz: list, s11: list, s21: list,
                            order: int | None = None,
                            f0_ghz: float | None = None,
                            fbw: float | None = None,
                            phase_ref: str = "unknown",
                            domain: str = "complex",
                            ref_delay_s: float | None = None,
                            ref_delay_scan: bool = False) -> dict:
    # ── 反提不收敛根因账（2026-09-15 定稿）──
    # 含馈线/λ/4 段参考面相位的电路裁判（coupled_bpf_circuit_sparams）反提
    # 不收敛（探针实测原始 rms 0.06~0.84 > 1e-2 门）。已败策略复盘：
    #   ① 相位滚转 ±：滚转是全局常数相位，而污染是
    #     f 的函数（e^{−j2πfτ} 非常数），滚不动；
    #   ② ABCD 精确逆：需已知夹具网络；裁判链的 λ/4 段是「2 导体 4 端口
    #     + 交叉口开路」复合结构，不是可分离级联件，精确逆不可得；
    #   ③ 纯时延去嵌（本函数 ref_delay_s/ref_delay_scan）：能开门
    #     （±3% 窗实测 rms 0.06→2.96e−3 ≤1e-2）但 kij 仍不可信（~1.5）
    #     ——根因链：λ/4 commensurate 网络在 Ω=(f/f0−f0/f)/fbw 域**非有理**
    #     （Richards 变量 tan(θ)≠Ω 映射），残余相位非时延型不可完全吸收；
    #     且窄带下错 τ 可被「多项式翘曲」补偿（探针实测 rms 1.3e−5 处
    #     拟合极点全飞），重建把离流形距离放大 ~10³ 倍（重建 vs 拟合
    #     2.6e−2 ≫ rms 1.3e−5）。纯时延校正不是收敛解。
    # 收敛解 = domain="magnitude"：只吃 |S|（天然免疫相位污染），|S|² 是
    # Ω² 的实有理函数，线性 Cauchy+谱分解重建。实测（±3% 窗，sync TEM
    # 裁判，名义 N=3 设计）：|S| rms 8.7e−3（过 1e-2 门）+ kij 逐元素
    # 偏差 1.95e−2；±1.5% 窗 kij 1.85e−2。色散模式（默认 εeff_e/o）
    # 裁判与理想矩阵 |S11| 带内差 ~0.16（模型差异，归 #11 裁判面），
    # 任何反提都受此地板限制——发现裁判模型问题只记录不改（模板渲染面
    # openems_templates.py 不因裁判结论回改）。
    if phase_ref not in ("unknown", "known"):
        raise ValueError("phase_ref 须为 unknown|known")
    if domain not in ("complex", "magnitude"):
        raise ValueError("domain 须为 complex|magnitude")
    if ref_delay_s is not None and ref_delay_scan:
        raise ValueError("ref_delay_s 与 ref_delay_scan 二选一")
    if domain == "magnitude" and (ref_delay_s is not None or ref_delay_scan):
        raise ValueError("ref_delay 只作用于 complex 域（幅值域天然无相位）")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 5:
        raise ValueError("freq_ghz 须为一维且至少 5 点")
    if np.any(freq <= 0):
        raise ValueError("freq_ghz 须为正频率")
    if np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须严格递增")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")

    if order is not None:
        order = int(order)
        if order < 1:
            raise ValueError("阶数必须 ≥1")
        n_list = [order]
    else:
        n_max = max(1, min(12, freq.size // 4))
        n_list = list(range(1, n_max + 1))

    # f0 / fbw（幅值量，两域同口径；|S| 不受参考面相位影响）
    f0_in = None if f0_ghz is None else float(f0_ghz)
    fbw_in = None if fbw is None else float(fbw)
    if fbw_in is not None and not 0 < fbw_in <= 1:
        raise ValueError("fbw 须在 (0,1]")
    s11_db = 20.0 * np.log10(np.maximum(np.abs(s11c), 1e-300))
    edges = _cm_band_edges(freq, s11_db)
    f0_est = math.sqrt(float(edges[0]) * float(edges[1])) if edges else \
        math.sqrt(float(freq[0]) * float(freq[-1]))
    fbw_est = (float(edges[1]) - float(edges[0])) / f0_est if edges else 0.1
    f0_use = f0_in if f0_in is not None else f0_est
    fbw_use = fbw_in if fbw_in is not None else min(max(fbw_est, 1e-3), 1.0)

    if domain == "complex":
        def fit_fn(om, a, b, n_ord, nz):
            f_s, p_s, e_s = _cm_rational_fit(om, a, b, n_ord, nz)
            return f_s, p_s, e_s, _cm_fit_rms(f_s, p_s, e_s, om, a, b)
    else:
        def fit_fn(om, a, b, n_ord, nz):
            return _cm_mag2_fit(om, np.abs(a), np.abs(b), n_ord, nz)

    def scan(f0, fbw_v, data):
        """给定 (f0, fbw)：逐阶扫 nz，返回每阶最优 (order, nz, rms, F,P,E, min_rms)。"""
        s11d, s21d = data
        out = []
        for n_ord in n_list:
            fits = {}
            for nz in range(0, n_ord + 1):
                try:
                    om = (freq / f0 - f0 / freq) / fbw_v
                    f_s, p_s, e_s, r = fit_fn(om, s11d, s21d, n_ord, nz)
                except (ValueError, np.linalg.LinAlgError):
                    continue
                if np.isfinite(r):
                    fits[nz] = (r, f_s, p_s, e_s)
            if not fits:
                continue
            min_r = min(v[0] for v in fits.values())
            # 零点数容差：绝对底噪 1e−6（容纳未知 f0 带来的模型误差）+
            # 相对最优 20×；否则额外 TZ 会吸收 f0 误差造成过拟合。
            tol = max(20.0 * min_r, 1e-6)
            nz_sel = min(k for k, v in fits.items() if v[0] <= tol)
            r, f_s, p_s, e_s = fits[nz_sel]
            out.append((n_ord, nz_sel, r, f_s, p_s, e_s, min_r))
        return out

    def choose(res):
        if not res:
            return None
        if order is not None:
            return res[0]
        best_r = min(t[6] for t in res)
        # 判阶容差取「绝对底噪 1e−6 + 相对最优 100×」：高阶过拟合（残差随阶数
        # 单调下降）与未知 f0 带来的模型误差都需容纳，否则会锁到过高的阶数。
        tol = max(100.0 * best_r, 1e-6)
        return next((t for t in res if t[6] <= tol), res[-1])

    data: tuple[np.ndarray, np.ndarray] = (s11c, s21c)
    ref_delay_used = None
    if domain == "complex" and (ref_delay_s is not None or ref_delay_scan):
        from rfauto.core.deembed import deembed_reference_delay

        if ref_delay_scan:
            # τ 扫描目标 (order,nz,f0,fbw) 用未去嵌数据初估（与 f0 精化同
            # 哲学：固定初选阶/零点数，只精化 τ 本身）。
            pre = choose(scan(f0_use, fbw_use, data))
            if pre is None:
                raise ValueError("有理拟合失败：数据无法用 ≤N 阶模型描述")
            tau_hi = 1.0 / (max(f0_use, 1e-9) * 1e9)
            ref_delay_used = _cm_refine_ref_delay(
                freq, s11c, s21c, f0_use, fbw_use, int(pre[0]), int(pre[1]),
                tau_hi)
        else:
            ref_delay_used = float(ref_delay_s)
        data = deembed_reference_delay(freq * 1e9, s11c, s21c,
                                       ref_delay_used, ref_delay_used)

    results = scan(f0_use, fbw_use, data)
    pick = choose(results)
    if pick is None:
        raise ValueError("有理拟合失败：数据无法用 ≤N 阶模型描述")

    # 未给 f0 时按拟合残差精化（f0 可辨识；fbw 缩放可被有理函数吸收）。
    # 仅 complex 域：幅值域的 |S|² 残差对 f0 的可辨识性未验证，不做。
    f0_source = "input" if f0_in is not None else "estimated"
    if domain == "complex" and f0_in is None and edges is not None:
        f0_ref = _cm_refine_f0(freq, data[0], data[1], pick[0], pick[1],
                               float(edges[0]), float(edges[1]), fbw_use)
        if abs(f0_ref - f0_use) > 1e-12:
            f0_use = f0_ref
            if fbw_in is None:
                fbw_use = min(max((float(edges[1]) - float(edges[0])) / f0_use,
                                  1e-3), 1.0)
            # 只在同一阶数内重选零点数：精化后的 f0 会把残差整体压低，
            # 若连阶数一起重选会向高阶过拟合（实测）。
            again = [t for t in scan(f0_use, fbw_use, data)
                     if t[0] == pick[0]]
            if again:
                pick = again[0]

    n_ord, nz_sel, fit_r, f_s, p_s, e_s, _ = pick

    om = (freq / f0_use - f0_use / freq) / fbw_use
    built = _cm_extract_from_fit(n_ord, f_s, p_s, e_s, om, data[0], data[1],
                                 phase_ref=phase_ref)
    if built is None:
        raise ValueError("Y 留数重建失败：拟合多项式结构不满足横向矩阵口径")
    report, m = built
    mat_err = report["mag_max_err"]
    if fit_r > 1e-2:
        raise ValueError(
            f"反提拟合残差过大（rms={fit_r:.3e}）：阶数不足或数据非理想滤波响应")

    marr = _cm_reduce_arrow(m)
    qe_in = 1.0 / (fbw_use * abs(marr[0, 1]) ** 2)
    qe_out = 1.0 / (fbw_use * abs(marr[n_ord, n_ord + 1]) ** 2)
    tz_roots = np.roots(p_s)
    tz_norm = sorted(abs(float(r.imag)) for r in tz_roots
                     if abs(r.real) < 1e-6 * max(1.0, abs(r)))
    tz_cplx = sorted((round(float((-1j * r).real), 9),
                      round(float((-1j * r).imag), 9)) for r in tz_roots)
    # 带内幺正性诊断（假绿关死的一道：重建矩阵须复现无耗响应）
    unit_dev = 0.0
    for w in om:
        a11, a21 = _cm_response_raw(m, 1.0, 1.0, w)
        unit_dev = max(unit_dev, abs(abs(a11) ** 2 + abs(a21) ** 2 - 1.0))
    # 假绿关死（#122）：旧探针「fit_rms=5.8e−10 而 response_max_err=1.15 /
    # 幺正偏差 0.69 仍 ok=True」。ok 现在明确=「重建矩阵复现数据」：
    # ①响应误差与拟合水平一致（1e3×fit，绝对地板 1e−4）；②响应误差
    # 绝对上限 0.05（线性幅度，~0.42dB——好反提实测 ≤1e−3，模型地板
    # 实测 ~3e−2）。门不过时 ok=False 如实返回（拟合门超限仍 raise）。
    resp_consistent = mat_err <= max(1e3 * fit_r, 1e-4)
    resp_absolute = mat_err <= 5e-2
    method = ("magnitude_squared_cauchy+cameron_residue" if domain == "magnitude"
              else "cauchy_rational_fit+cameron_residue")
    return {"ok": bool(resp_consistent and resp_absolute),
            "order": n_ord, "n_finite_tz": nz_sel,
            "f0_ghz": round(f0_use, 9),
            "fbw": round(fbw_use, 9),
            "f0_source": f0_source,
            "fbw_source": "input" if fbw_in is not None else "estimated",
            "band_edges_ghz": ([round(float(edges[0]), 9),
                                round(float(edges[1]), 9)] if edges else None),
            "external_q": [round(qe_in, 9), round(qe_out, 9)],
            "coupling_matrix": _cm_to_list(m),
            "matrix_shape": [n_ord + 2, n_ord + 2],
            "transmission_zeros_norm": [round(z, 9) for z in tz_norm],
            "transmission_zeros_cplx": [list(p) for p in tz_cplx],
            "fit_rms": round(fit_r, 12),
            "response_max_err": round(mat_err, 12),
            "fit_domain": domain,
            "phase_ref": phase_ref if domain == "complex" else "n/a",
            "ref_delay_s": (None if ref_delay_used is None
                            else round(ref_delay_used, 15)),
            "coefficient_path": (report["path"] if domain == "complex"
                                 else "magnitude"),
            "derotation_residual_f": round(report["derot_f"], 12),
            "derotation_residual_p": round(report["derot_p"], 12),
            "unitarity_max_dev": round(float(unit_dev), 12),
            "ok_reason": ("response_consistent"
                          if resp_consistent and resp_absolute else
                          f"response_max_err {mat_err:.3e} 与拟合水平"
                          f"(rms={fit_r:.3e})不一致或超绝对上限 0.05"),
            "method": method,
            "note": "矩阵元素 [re,im]；external_q=Qe=1/(fbw·m_arrow²)。"
                    "fbw 由 S 参数形状不可辨识（Ω 缩放可被有理函数吸收），"
                    "无输入时按纹波带边（|S11|=纹波电平外沿交点）估计，"
                    "精度受频点密度限制（实测 ~1e−3 相对）；f0 由拟合残差精化"
                    "（仅 complex 域）。domain=magnitude：|S|² 幅值域兜底，"
                    "相位污染免疫，但 F/P 全局符号与单侧 TZ 的 ±Ω 不可辨识"
                    "（transmission_zeros_cplx 报 ± 对）、f0 不精化。"
                    "ok=重建矩阵复现数据（响应一致性双门），门不过如实 False。"}

# ─── 热/功率闭式族 ────────────────────────────────────────────────────────────
# 裁判口径（#118：裁判=外部独立来源，不是本文件自己的推导）：
#  * 温漂：Δf/f = −CTE·ΔT − ½·TCDk·ΔT，由 f=c/(2L√ε) 的对数一阶展开
#    得到（TCDk=(1/ε)dε/dT、CTE=(1/L)dL/dT；Pozar《Microwave Engineering》
#    谐振器温漂）。
#  * 走线温升：IPC-2152（2009）只出版图表；Brooks & Adam 用
#    ΔT = K·I^a·W^b·Th^c（W/Th 以 mil 计）拟合其数据
#    （D. G. Brooks, J. Adam, "Trace Currents and Temperatures Revisited",
#    2015, Table 3-1）。系数/内层铜重分档逐条取自 KiCad 独立实现
#    common/track_width_calculations.cpp；其公开测试向量
#    （qa/tests/common/test_track_width_calculations.cpp）被本项单测复用。
#  * 1-D 热阻栈：稳态热阻网络（串联 Σθ、并联 1/Σ(1/θ)、Tj=Ta+P·θtot），
#    教科书电阻类比（Incropera《Fundamentals of Heat and Mass Transfer》）。
#  * 线热源：行波 P(z)=P0·e^(−2αz) → 单位长度耗散 2αP（Pozar §2.7）；
#    α_c=R'/(2Z0)、R'=R_s/w、R_s=√(ωμ0/2σ)；α_d=π·f·tanδ·√εeff/c。
#  * 平行板击穿：E=V/d；材料阈值表见 _DIELECTRIC_STRENGTH_MV_PER_M 表注。
#  * ECSS：ECSS-E-ST-20-01C (2020) Table 5-1 的 f×d(GHz·mm) → 最低击穿电压
#    阈值边界（Al/Cu/Ag/Au）逐行录入；插值在对数 f×d 上线性；标准定义的
#    "minimum inflexion point" 即该边界曲线的最低点。

_MIL_PER_MM = 39.37007874015748
_MIL_PER_OZ = 1.378
_MU0_H_PER_M = 1.2566370614359173e-6
_C0_M_PER_S = 299792458.0


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错。"""
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


@register_calculator(
    "resonator_thermal_drift",
    "谐振温漂（一阶闭式）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。"
    "CTE=有效线膨胀系数、TCDk=(1/ε)dε/dT，单位 ppm/K",
    (("f0_ghz", "float GHz 标称谐振频率（>0）"),
     ("delta_t_c", "float K 温度变化（可为负）"),
     ("cte_ppm_per_k", "float ppm/K 有效线膨胀系数（含封装）"),
     ("tcdk_ppm_per_k", "float ppm/K 介电常数温度系数")),
    required=("f0_ghz", "delta_t_c", "cte_ppm_per_k", "tcdk_ppm_per_k"),
)
def resonator_thermal_drift(f0_ghz: float, delta_t_c: float,
                            cte_ppm_per_k: float,
                            tcdk_ppm_per_k: float) -> dict:
    if _finite(f0_ghz, "f0_ghz") <= 0:
        raise ValueError("f0_ghz 必须 >0")
    dt = _finite(delta_t_c, "delta_t_c")
    cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    tcdk = _finite(tcdk_ppm_per_k, "tcdk_ppm_per_k")
    cte_term = -cte * 1e-6 * dt
    tcdk_term = -0.5 * tcdk * 1e-6 * dt
    ratio = cte_term + tcdk_term
    return {"df_over_f": round(ratio, 15),
            "df_over_f_ppm": round(ratio * 1e6, 9),
            "f_shifted_ghz": round(f0_ghz * (1.0 + ratio), 12),
            "df_ghz": round(f0_ghz * ratio, 15),
            "cte_term_ppm": round(cte_term * 1e6, 9),
            "tcdk_term_ppm": round(tcdk_term * 1e6, 9)}


# Brooks & Adam 对 IPC-2152 数据的拟合系数 (K, a, b, c)：ΔT=K·I^a·W^b·Th^c
_IPC2152_EXTERNAL = (215.3, 2.0, -1.15, -1.0)
_IPC2152_INTERNAL_HALF_OZ = (120.0, 2.0, -1.10, -1.52)
_IPC2152_INTERNAL_1OZ = (200.0, 1.9, -1.10, -1.52)
_IPC2152_INTERNAL_2OZ = (300.0, 2.0, -1.15, -1.52)
_IPC2152_INTERNAL_3OZ = (262.5, 1.9, -1.15, -1.52)
# 内层分档中点（K KiCad：名义铜厚 0.689/1.378/2.756/4.134 mil 的相邻中点）
_IPC2152_SPLIT_HALF_1OZ = (0.689 + 1.378) / 2.0
_IPC2152_SPLIT_1OZ_2OZ = (1.378 + 2.756) / 2.0
_IPC2152_SPLIT_2OZ_3OZ = (2.756 + 4.134) / 2.0


def _ipc2152_coefficients(internal: bool, thickness_mil: float):
    """按层别/铜厚选 (K, a, b, c)（分档与 KiCad 实现逐条一致）。"""
    if not internal:
        return _IPC2152_EXTERNAL
    if thickness_mil < _IPC2152_SPLIT_HALF_1OZ:
        return _IPC2152_INTERNAL_HALF_OZ
    if thickness_mil < _IPC2152_SPLIT_1OZ_2OZ:
        return _IPC2152_INTERNAL_1OZ
    if thickness_mil < _IPC2152_SPLIT_2OZ_3OZ:
        return _IPC2152_INTERNAL_2OZ
    return _IPC2152_INTERNAL_3OZ


@register_calculator(
    "ipc2152_trace_temp_rise",
    "IPC-2152 走线载流温升：线宽/铜厚/电流 → ΔT（Brooks & Adam 拟合 "
    "ΔT=K·I^a·W^b·Th^c，W/Th 以 mil 计；系数取自 KiCad 独立实现）。"
    "IPC-2152 结论：内层不按 IPC-2221 的老规矩 ×2 降额",
    (("width_mm", "float mm 走线宽度（>0）"),
     ("copper_oz", "float oz/ft² 铜厚（1 oz ≈ 1.378 mil）"),
     ("current_a", "float A 走线电流（DC/RMS，≥0）"),
     ("internal", "bool 是否内层（默认 False）")),
    required=("width_mm", "copper_oz", "current_a"),
)
def ipc2152_trace_temp_rise(width_mm: float, copper_oz: float,
                            current_a: float,
                            internal: bool = False) -> dict:
    if _finite(width_mm, "width_mm") <= 0:
        raise ValueError("width_mm 必须 >0")
    if _finite(copper_oz, "copper_oz") <= 0:
        raise ValueError("copper_oz 必须 >0")
    if _finite(current_a, "current_a") < 0:
        raise ValueError("current_a 必须 ≥0")
    w_mil = width_mm * _MIL_PER_MM
    th_mil = copper_oz * _MIL_PER_OZ
    coeff = _ipc2152_coefficients(bool(internal), th_mil)
    k_ba, a_ba, b_ba, c_ba = coeff
    delta_t = k_ba * (current_a ** a_ba) * (w_mil ** b_ba) * (th_mil ** c_ba)
    return {"delta_t_c": round(delta_t, 9),
            "width_mil": round(w_mil, 6),
            "thickness_mil": round(th_mil, 6),
            "layer": "internal" if internal else "external",
            "coefficients": list(coeff)}


@register_calculator(
    "thermal_resistance_stack",
    "1-D 热阻栈（结→壳→散热器→环境）：串联 Σθ 与可选并联完整支路 "
    "1/(Σ1/θi) 构成热阻网络，Tj = Ta + P·θtot（教科书电阻类比）",
    (("power_w", "float W 耗散功率（≥0）"),
     ("ambient_c", "float °C 环境温度"),
     ("theta_jc_c_per_w", "float °C/W 结→壳（串联链必需项）"),
     ("theta_cs_c_per_w", "float °C/W 壳→散热器（默认 0）"),
     ("theta_sa_c_per_w", "float °C/W 散热器→环境（默认 0）"),
     ("parallel_paths_c_per_w", "array °C/W 并联完整支路热阻（默认空）")),
    required=("power_w", "ambient_c", "theta_jc_c_per_w"),
)
def thermal_resistance_stack(power_w: float, ambient_c: float,
                             theta_jc_c_per_w: float,
                             theta_cs_c_per_w: float = 0.0,
                             theta_sa_c_per_w: float = 0.0,
                             parallel_paths_c_per_w: list | None = None
                             ) -> dict:
    if _finite(power_w, "power_w") < 0:
        raise ValueError("power_w 必须 ≥0")
    chain = 0.0
    for value, name in ((theta_jc_c_per_w, "theta_jc_c_per_w"),
                        (theta_cs_c_per_w, "theta_cs_c_per_w"),
                        (theta_sa_c_per_w, "theta_sa_c_per_w")):
        if _finite(value, name) < 0:
            raise ValueError(f"{name} 必须 ≥0")
        chain += value
    threads = [float(v) for v in (parallel_paths_c_per_w or [])]
    if any((not math.isfinite(v)) or v <= 0 for v in threads):
        raise ValueError("parallel_paths_c_per_w 各项必须为有限正热阻")
    if threads:
        if chain == 0.0:
            raise ValueError("串联链热阻为 0 时无法与并联支路组合")
        theta_parallel = 1.0 / sum(1.0 / v for v in threads)
        total = 1.0 / (1.0 / chain + 1.0 / theta_parallel)
    else:
        theta_parallel = None
        total = chain
    junction = ambient_c + power_w * total
    return {"theta_series_c_per_w": round(chain, 9),
            "theta_parallel_c_per_w": (None if theta_parallel is None
                                       else round(theta_parallel, 9)),
            "theta_total_c_per_w": round(total, 9),
            "delta_t_c": round(power_w * total, 9),
            "junction_temp_c": round(junction, 9),
            "parallel_count": len(threads)}


@register_calculator(
    "microstrip_loss_heat",
    "微带导体/介质损耗 → 等效线热源：匹配行波 P_loss/m = 2(α_c+α_d)·P"
    "（Pozar §2.7）。α_c=R'/(2Z0)（R'=Rs/w，趋肤 Rs=√(ωμ0/2σ)）、"
    "α_d=π·f·tanδ·√εeff/c",
    (("freq_ghz", "float GHz 频率（>0）"),
     ("power_w", "float W 传输功率（匹配负载，>0）"),
     ("z0_ohm", "float Ω 特性阻抗（>0）"),
     ("eps_eff", "float - 有效介电常数（>0）"),
     ("tand", "float - 损耗正切（≥0）"),
     ("width_mm", "float mm 导带宽度（面密度用，>0）"),
     ("sigma_s_per_m", "float S/m 导体电导率（默认铜 5.8e7）")),
    required=("freq_ghz", "power_w", "z0_ohm", "eps_eff", "tand", "width_mm"),
)
def microstrip_loss_heat(freq_ghz: float, power_w: float, z0_ohm: float,
                         eps_eff: float, tand: float, width_mm: float,
                         sigma_s_per_m: float = 5.8e7) -> dict:
    if _finite(freq_ghz, "freq_ghz") <= 0:
        raise ValueError("freq_ghz 必须 >0")
    if _finite(power_w, "power_w") <= 0:
        raise ValueError("power_w 必须 >0")
    if _finite(z0_ohm, "z0_ohm") <= 0:
        raise ValueError("z0_ohm 必须 >0")
    if _finite(eps_eff, "eps_eff") <= 0:
        raise ValueError("eps_eff 必须 >0")
    if _finite(tand, "tand") < 0:
        raise ValueError("tand 必须 ≥0")
    if _finite(width_mm, "width_mm") <= 0:
        raise ValueError("width_mm 必须 >0")
    if _finite(sigma_s_per_m, "sigma_s_per_m") <= 0:
        raise ValueError("sigma_s_per_m 必须 >0")
    omega = 2.0 * math.pi * freq_ghz * 1e9
    skin_depth = math.sqrt(2.0 / (omega * _MU0_H_PER_M * sigma_s_per_m))
    r_sheet = 1.0 / (sigma_s_per_m * skin_depth)
    r_prime = r_sheet / (width_mm * 1e-3)
    alpha_c = r_prime / (2.0 * z0_ohm)
    alpha_d = (math.pi * freq_ghz * 1e9 * tand * math.sqrt(eps_eff)
               / _C0_M_PER_S)
    alpha_total = alpha_c + alpha_d
    p_total = 2.0 * alpha_total * power_w
    return {"alpha_conductor_np_per_m": round(alpha_c, 15),
            "alpha_dielectric_np_per_m": round(alpha_d, 15),
            "alpha_total_db_per_m": round(alpha_total * 8.685889638065035, 12),
            "skin_depth_um": round(skin_depth * 1e6, 9),
            "r_sheet_ohm_per_sq": round(r_sheet, 12),
            "r_prime_ohm_per_m": round(r_prime, 9),
            "p_conductor_w_per_m": round(2.0 * alpha_c * power_w, 12),
            "p_dielectric_w_per_m": round(2.0 * alpha_d * power_w, 12),
            "p_loss_w_per_m": round(p_total, 12),
            "p_loss_w_per_mm2": round(p_total / width_mm * 1e-3, 15),
            "note": "R'=Rs/w 为均匀电流近似（未计边缘电流聚集与表面粗糙度）；"
                    "P_loss/m=2(α_c+α_d)P 为匹配行波口径"}


# 近似击穿场强（MV/m）。来源：electricity-magnetism.org 汇总的常用介质近似
# 值（Air 3 kV/mm；Teflon 60–120；Polyethylene 15–50；PVC 40–50；Mica
# 10–200 kV/mm）；本表取各范围的**保守下限**（空气原文仅一个值 3）。
_DIELECTRIC_STRENGTH_MV_PER_M = {
    "air": 3.0,
    "ptfe": 60.0,
    "polyethylene": 15.0,
    "pvc": 40.0,
    "mica": 10.0,
}


@register_calculator(
    "parallel_plate_breakdown_margin",
    "平行板击穿场强裕量：E = V/d 对比材料击穿阈值表（空气 3 MV/m 等）；"
    "margin_ratio = E_bd/E，safety_factor 为要求的安全系数（E·sf ≤ E_bd 判过）",
    (("voltage_v", "float V 施加直流/峰值电压（≥0）"),
     ("gap_mm", "float mm 极板间距（>0）"),
     ("material", "str 材料键（默认 air；可用见 _DIELECTRIC_STRENGTH_MV_PER_M）"),
     ("safety_factor", "float - 要求安全系数（默认 1.0）")),
    required=("voltage_v", "gap_mm"),
)
def parallel_plate_breakdown_margin(voltage_v: float, gap_mm: float,
                                    material: str = "air",
                                    safety_factor: float = 1.0) -> dict:
    if _finite(voltage_v, "voltage_v") < 0:
        raise ValueError("voltage_v 必须 ≥0")
    if _finite(gap_mm, "gap_mm") <= 0:
        raise ValueError("gap_mm 必须 >0")
    if _finite(safety_factor, "safety_factor") <= 0:
        raise ValueError("safety_factor 必须 >0")
    key = str(material).lower()
    if key not in _DIELECTRIC_STRENGTH_MV_PER_M:
        raise ValueError(
            f"未知材料 {material!r}（可用: "
            f"{sorted(_DIELECTRIC_STRENGTH_MV_PER_M)}）")
    threshold = _DIELECTRIC_STRENGTH_MV_PER_M[key]
    e_field = voltage_v / (gap_mm * 1e-3) / 1e6
    if e_field > 0.0:
        margin_ratio: float | None = threshold / e_field
        margin_db: float | None = 20.0 * math.log10(margin_ratio)
    else:
        margin_ratio = None
        margin_db = None
    return {"e_field_mv_per_m": round(e_field, 12),
            "breakdown_mv_per_m": threshold,
            "margin_ratio": (None if margin_ratio is None
                             else round(margin_ratio, 9)),
            "margin_db": None if margin_db is None else round(margin_db, 9),
            "safety_factor": safety_factor,
            "pass": bool(e_field * safety_factor <= threshold),
            "material": key}


# ECSS-E-ST-20-01C (15 June 2020) Table 5-1：f×d(GHz·mm) → 最低击穿电压阈值
# 边界 (Breakdown Voltage, V)，四材料逐行录入（Al/Cu/Ag/Au；各行使为该材料
# 图表边界的起始 f×d 不同，故序列长度不同：100/99/97/98 点）。
_ECSS_FD_TABLE = {
    "aluminium": (
        (0.43, 33.8), (0.47, 28.5), (0.49, 27.4), (0.50, 27.0), (0.53, 26.1), (0.56, 25.4),
        (0.59, 24.7), (0.62, 24.2), (0.66, 24.0), (0.70, 23.8), (0.74, 24.1), (0.78, 24.7),
        (0.82, 25.9), (0.87, 27.2), (0.92, 29.3), (0.97, 31.5), (1.02, 34.4), (1.08, 37.7),
        (1.14, 41.6), (1.21, 46.2), (1.28, 51.3), (1.35, 56.9), (1.43, 63.4), (1.51, 70.5),
        (1.59, 78.4), (1.68, 86.1), (1.78, 94.3), (1.88, 102.0), (1.99, 110.1), (2.10, 117.4),
        (2.22, 124.8), (2.34, 130.5), (2.48, 133.7), (2.62, 131.8), (2.77, 128.4), (2.92, 129.6),
        (3.09, 134.0), (3.27, 139.7), (3.45, 147.8), (3.65, 156.6), (3.85, 167.8), (4.07, 179.6),
        (4.30, 193.1), (4.55, 207.5), (4.81, 221.7), (5.08, 236.5), (5.37, 249.5), (5.67, 261.8),
        (5.99, 273.1), (6.33, 284.0), (6.69, 298.3), (7.07, 317.5), (7.47, 337.5), (7.90, 357.3),
        (8.34, 378.3), (8.82, 399.9), (9.32, 422.4), (9.85, 446.2), (10.41, 471.4), (11.00, 498.9),
        (11.62, 528.0), (12.28, 559.0), (12.98, 592.0), (13.71, 626.0), (14.49, 662.0), (15.31, 700.0),
        (16.18, 742.0), (17.10, 786.0), (18.07, 832.0), (19.10, 881.0), (20.18, 934.0), (21.32, 990.0),
        (22.53, 1050.0), (23.81, 1113.0), (25.16, 1181.0), (26.59, 1254.0), (28.10, 1370.0), (29.69, 1532.0),
        (31.38, 1682.0), (33.16, 1797.0), (35.04, 1875.0), (37.03, 1885.0), (39.13, 1926.0), (41.35, 2052.0),
        (43.70, 2186.0), (46.18, 2332.0), (48.80, 2486.0), (51.57, 2654.0), (54.49, 2833.0), (57.59, 3026.0),
        (60.85, 3232.0), (64.31, 3453.0), (67.95, 3690.0), (71.81, 3894.0), (75.88, 4050.0), (80.19, 4283.0),
        (84.74, 4698.0), (89.55, 5117.0), (94.63, 5440.0), (100.00, 5782.0),
    ),
    "copper": (
        (0.47, 36.6), (0.49, 33.4), (0.50, 32.5), (0.53, 30.8), (0.56, 29.7), (0.59, 28.8),
        (0.62, 28.1), (0.66, 27.7), (0.70, 27.4), (0.74, 27.5), (0.78, 27.7), (0.82, 28.7),
        (0.87, 29.9), (0.92, 31.9), (0.97, 34.0), (1.02, 37.0), (1.08, 40.3), (1.14, 44.4),
        (1.21, 49.0), (1.28, 54.2), (1.35, 60.3), (1.43, 67.0), (1.51, 74.8), (1.59, 83.3),
        (1.68, 91.9), (1.78, 101.4), (1.88, 110.8), (1.99, 120.9), (2.10, 130.1), (2.22, 139.7),
        (2.34, 148.2), (2.48, 156.7), (2.62, 160.2), (2.77, 154.3), (2.92, 149.2), (3.09, 150.6),
        (3.27, 155.2), (3.45, 163.0), (3.65, 171.7), (3.85, 183.4), (4.07, 195.8), (4.30, 211.2),
        (4.55, 227.6), (4.81, 244.6), (5.08, 262.5), (5.37, 277.3), (5.67, 290.7), (5.99, 302.9),
        (6.33, 314.4), (6.69, 329.6), (7.07, 350.3), (7.47, 372.1), (7.90, 394.5), (8.34, 418.0),
        (8.82, 441.6), (9.32, 466.6), (9.85, 493.1), (10.41, 521.0), (11.00, 551.0), (11.62, 583.0),
        (12.28, 617.0), (12.98, 653.0), (13.71, 691.0), (14.49, 731.0), (15.31, 773.0), (16.18, 819.0),
        (17.10, 867.0), (18.07, 919.0), (19.10, 974.0), (20.18, 1032.0), (21.32, 1093.0), (22.53, 1160.0),
        (23.81, 1229.0), (25.16, 1305.0), (26.59, 1385.0), (28.10, 1512.0), (29.69, 1704.0), (31.38, 1870.0),
        (33.16, 2000.0), (35.04, 2089.0), (37.03, 2087.0), (39.13, 2129.0), (41.35, 2269.0), (43.70, 2418.0),
        (46.18, 2581.0), (48.80, 2753.0), (51.57, 2941.0), (54.49, 3141.0), (57.59, 3359.0), (60.85, 3593.0),
        (64.31, 3845.0), (67.95, 4115.0), (71.81, 4383.0), (75.88, 4642.0), (80.19, 4952.0), (84.74, 5368.0),
        (89.55, 5798.0), (94.63, 6200.0), (100.00, 6624.0),
    ),
    "silver": (
        (0.50, 38.3), (0.53, 33.7), (0.56, 31.7), (0.59, 30.4), (0.62, 29.5), (0.66, 28.9),
        (0.70, 28.5), (0.74, 28.5), (0.78, 28.7), (0.82, 29.7), (0.87, 30.9), (0.92, 32.9),
        (0.97, 35.2), (1.02, 38.3), (1.08, 41.7), (1.14, 45.9), (1.21, 50.8), (1.28, 56.2),
        (1.35, 62.5), (1.43, 69.5), (1.51, 77.2), (1.59, 86.0), (1.68, 95.4), (1.78, 105.6),
        (1.88, 116.0), (1.99, 126.9), (2.10, 137.5), (2.22, 148.5), (2.34, 159.4), (2.48, 170.6),
        (2.62, 179.7), (2.77, 182.2), (2.92, 167.6), (3.09, 162.4), (3.27, 165.4), (3.45, 172.8),
        (3.65, 181.4), (3.85, 193.5), (4.07, 206.3), (4.30, 222.9), (4.55, 240.4), (4.81, 258.2),
        (5.08, 276.9), (5.37, 292.2), (5.67, 306.4), (5.99, 321.1), (6.33, 336.2), (6.69, 353.4),
        (7.07, 373.3), (7.47, 394.8), (7.90, 419.2), (8.34, 444.8), (8.82, 469.9), (9.32, 496.5),
        (9.85, 525.0), (10.41, 554.0), (11.00, 586.0), (11.62, 621.0), (12.28, 657.0), (12.98, 695.0),
        (13.71, 736.0), (14.49, 779.0), (15.31, 825.0), (16.18, 874.0), (17.10, 925.0), (18.07, 981.0),
        (19.10, 1039.0), (20.18, 1102.0), (21.32, 1168.0), (22.53, 1240.0), (23.81, 1315.0), (25.16, 1397.0),
        (26.59, 1483.0), (28.10, 1577.0), (29.69, 1677.0), (31.38, 1783.0), (33.16, 1897.0), (35.04, 2019.0),
        (37.03, 2152.0), (39.13, 2293.0), (41.35, 2448.0), (43.70, 2611.0), (46.18, 2791.0), (48.80, 2981.0),
        (51.57, 3191.0), (54.49, 3414.0), (57.59, 3659.0), (60.85, 3921.0), (64.31, 4206.0), (67.95, 4514.0),
        (71.81, 4846.0), (75.88, 5208.0), (80.19, 5595.0), (84.74, 6014.0), (89.55, 6458.0), (94.63, 6936.0),
        (100.00, 7440.0),
    ),
    "gold": (
        (0.49, 41.0), (0.50, 38.1), (0.53, 34.5), (0.56, 32.8), (0.59, 31.6), (0.62, 30.8),
        (0.66, 30.2), (0.70, 29.8), (0.74, 29.7), (0.78, 29.8), (0.82, 30.6), (0.87, 31.6),
        (0.92, 33.5), (0.97, 35.7), (1.02, 38.6), (1.08, 42.0), (1.14, 46.0), (1.21, 50.8),
        (1.28, 56.2), (1.35, 62.4), (1.43, 69.3), (1.51, 77.0), (1.59, 85.8), (1.68, 95.3),
        (1.78, 105.6), (1.88, 116.0), (1.99, 127.0), (2.10, 137.6), (2.22, 148.7), (2.34, 159.4),
        (2.48, 170.3), (2.62, 179.2), (2.77, 181.3), (2.92, 168.7), (3.09, 163.6), (3.27, 166.3),
        (3.45, 173.6), (3.65, 181.8), (3.85, 193.9), (4.07, 206.6), (4.30, 223.2), (4.55, 240.7),
        (4.81, 258.5), (5.08, 277.2), (5.37, 292.7), (5.67, 307.1), (5.99, 321.8), (6.33, 336.9),
        (6.69, 354.0), (7.07, 373.9), (7.47, 395.4), (7.90, 419.7), (8.34, 445.3), (8.82, 470.5),
        (9.32, 497.1), (9.85, 525.0), (10.41, 555.0), (11.00, 587.0), (11.62, 621.0), (12.28, 657.0),
        (12.98, 695.0), (13.71, 736.0), (14.49, 779.0), (15.31, 825.0), (16.18, 873.0), (17.10, 924.0),
        (18.07, 980.0), (19.10, 1038.0), (20.18, 1100.0), (21.32, 1166.0), (22.53, 1236.0), (23.81, 1311.0),
        (25.16, 1392.0), (26.59, 1478.0), (28.10, 1570.0), (29.69, 1668.0), (31.38, 1773.0), (33.16, 1885.0),
        (35.04, 2006.0), (37.03, 2136.0), (39.13, 2274.0), (41.35, 2425.0), (43.70, 2585.0), (46.18, 2761.0),
        (48.80, 2946.0), (51.57, 3150.0), (54.49, 3367.0), (57.59, 3604.0), (60.85, 3858.0), (64.31, 4132.0),
        (67.95, 4430.0), (71.81, 4752.0), (75.88, 5101.0), (80.19, 5474.0), (84.74, 5878.0), (89.55, 6306.0),
        (94.63, 6767.0), (100.00, 7254.0),
    ),
}

_ECSS_MATERIAL_ALIASES = {
    "al": "aluminium", "aluminum": "aluminium", "aluminium": "aluminium",
    "cu": "copper", "copper": "copper",
    "ag": "silver", "silver": "silver",
    "au": "gold", "gold": "gold",
}

# 标准定义的 "minimum inflexion point" = 边界曲线最低点
_ECSS_INFLEXION = {
    name: min(points, key=lambda pt: pt[1])
    for name, points in _ECSS_FD_TABLE.items()
}


def _ecss_lookup(material: str, fxd: float):
    """f×d 查表（对数横轴线性插值）；超出表范围时夹取端点并如实返回区域标记。"""
    points = _ECSS_FD_TABLE[material]
    if fxd < points[0][0]:
        return points[0][1], "below_chart_min"
    if fxd > points[-1][0]:
        return points[-1][1], "above_chart_max"
    for index in range(len(points) - 1):
        x0, v0 = points[index]
        x1, v1 = points[index + 1]
        if x0 <= fxd <= x1:
            frac = ((math.log(fxd) - math.log(x0))
                    / (math.log(x1) - math.log(x0)))
            return v0 + frac * (v1 - v0), "table"
    return points[-1][1], "above_chart_max"


@register_calculator(
    "ecss_multipactor_fd",
    "ECSS 多载流子 f·d 判据：f×d(GHz·mm) 查 ECSS-E-ST-20-01C Table 5-1 的"
    "最低击穿电压阈值边界（Al/Cu/Ag/Au，对数插值），与施加峰值电压比给出"
    "裕量 dB 与过/不过判定",
    (("freq_ghz", "float GHz 工作频率（>0）"),
     ("gap_mm", "float mm 临界间隙（>0）"),
     ("material", "str 金属键 aluminium/copper/silver/gold（默认 silver）"),
     ("voltage_v", "float V 施加峰值电压（优先；与功率二选一）"),
     ("power_w", "float W 单载波功率（配 z0_ohm：V=√(2PZ0)）"),
     ("z0_ohm", "float Ω 系统阻抗（默认 50）"),
     ("carrier_powers_w", "array W 各载波平均功率（ECSS 口径 Pavg=ΣPi）"),
     ("required_margin_db", "float dB 要求裕量（默认 6）")),
    required=("freq_ghz", "gap_mm"),
)
def ecss_multipactor_fd(freq_ghz: float, gap_mm: float,
                        material: str = "silver",
                        voltage_v: float | None = None,
                        power_w: float | None = None,
                        z0_ohm: float = 50.0,
                        carrier_powers_w: list | None = None,
                        required_margin_db: float = 6.0) -> dict:
    if _finite(freq_ghz, "freq_ghz") <= 0:
        raise ValueError("freq_ghz 必须 >0")
    if _finite(gap_mm, "gap_mm") <= 0:
        raise ValueError("gap_mm 必须 >0")
    key = _ECSS_MATERIAL_ALIASES.get(str(material).lower())
    if key is None:
        raise ValueError(f"未知金属 {material!r}（可用: {sorted(_ECSS_FD_TABLE)}）")
    if _finite(z0_ohm, "z0_ohm") <= 0:
        raise ValueError("z0_ohm 必须 >0")
    if voltage_v is not None:
        v_app = _finite(voltage_v, "voltage_v")
    elif carrier_powers_w is not None:
        powers = [float(p) for p in carrier_powers_w]
        if not powers or any((not math.isfinite(p)) or p < 0 for p in powers):
            raise ValueError("carrier_powers_w 须为非空非负功率列表")
        v_app = math.sqrt(2.0 * sum(powers) * z0_ohm)
    elif power_w is not None:
        if _finite(power_w, "power_w") <= 0:
            raise ValueError("power_w 必须 >0")
        v_app = math.sqrt(2.0 * power_w * z0_ohm)
    else:
        raise ValueError("需提供 voltage_v / power_w / carrier_powers_w 之一")
    if v_app <= 0:
        raise ValueError("施加电压必须 >0（功率须 >0）")
    required = _finite(required_margin_db, "required_margin_db")
    fxd = freq_ghz * gap_mm
    threshold, region = _ecss_lookup(key, fxd)
    margin_ratio = threshold / v_app
    margin_db = 20.0 * math.log10(margin_ratio)
    inflexion = _ECSS_INFLEXION[key]
    return {"fxd_ghz_mm": round(fxd, 12),
            "material": key,
            "threshold_v": round(threshold, 9),
            "applied_voltage_v": round(v_app, 12),
            "margin_ratio": round(margin_ratio, 12),
            "margin_db": round(margin_db, 9),
            "required_margin_db": required,
            "pass": bool(margin_db >= required),
            "region": region,
            "inflexion_fxd_ghz_mm": inflexion[0],
            "inflexion_voltage_v": inflexion[1]}


# ─── 腔体微扰频移（Pozar §6.7 材料微扰 + Slater 形状微扰）──────────────────
# 口径（Pozar《Microwave Engineering》§6.7 Cavity Perturbations，
# Slater 定理一阶式；腔体微扰法测 εr 的标准式）：
#   TE101 矩形腔（腔体 [0,a]×[0,b]×[0,d]，n=0 无 y 依赖）：
#     f0 = (c/2)·√(1/a² + 1/d²)，Vc = a·b·d
#     E_y ∝ sin(πx/a)·sin(πz/d)（E 极大在 (a/2, d/2)），
#     |H|² = [sin²(πx/a)cos²(πz/d) + (d/a)²cos²(πx/a)sin²(πz/d)]/(1+(d/a)²)
#       （由 ∇×E 与 Z_TE²=1+(d/a)²（ε0=μ0=1 归一）导出；能量等式
#        ∫μ|H|²dV = ∫ε|E|²dV = ε·Vc/4 在该归一下精确成立）
#   材料微扰（小介质样品，一阶）：Δf/f0 = −(εr−1)/2 · ∫Vs|E0|²dV / ∫Vc|E0|²dV
#   形状微扰（Slater 小金属样品）：Δf/f0 = ½·(∫Vs μ|H0|² − ε|E0|²)dV/∫Vc ε|E0|²dV
#   小样品极限（几何体积表述，∫Vc|E|²=Vc/4 折算）：
#     E 极大点介质样品 → −2(εr−1)·Vs/Vc；金属样品 → −2·Vs/Vc（频率下降）；
#     H 极大区金属样品 → 符号翻正（频率上升）。→ 位移法测 εr / 调谐螺钉
#     「E 区下压、H 区上抬」的标准结论。
# 判据（#118 双裁判）：有限盒样品走 sin²/cos² 原函数解析积分（精确）；
#   任意网格样品走体素奇偶性内点积分，测试做步长收敛 + 小样品极限对照。

def _te101_field_integrals_box(a_mm: float, b_mm: float, d_mm: float,
                               lo: list[float], hi: list[float]) -> dict[str, float]:
    """盒样品的 TE101 场权积分（sin²/cos² 原函数，解析精确）。

    x 向周期 a、z 向周期 d（各自独立），y 向无场变化 → 乘样品 y 长度
    （不是腔高 b——b 只进 ∫Vc 归一）。
    """
    pi = math.pi

    def anti_s(x: float, period: float) -> float:  # ∫sin²(πx/L)dx
        return x / 2.0 - period / (4.0 * pi) * math.sin(2.0 * pi * x / period)

    def anti_c(x: float, period: float) -> float:  # ∫cos²(πx/L)dx
        return x / 2.0 + period / (4.0 * pi) * math.sin(2.0 * pi * x / period)

    sx = anti_s(hi[0], a_mm) - anti_s(lo[0], a_mm)
    cx = anti_c(hi[0], a_mm) - anti_c(lo[0], a_mm)
    sz = anti_s(hi[2], d_mm) - anti_s(lo[2], d_mm)
    cz = anti_c(hi[2], d_mm) - anti_c(lo[2], d_mm)
    y_ext = hi[1] - lo[1]
    i_e = y_ext * sx * sz                         # ∫Vs wE dV
    i_hx = y_ext * sx * cz                        # ∫Vs sin²(x)cos²(z) dV
    i_hz = y_ext * cx * sz                        # ∫Vs cos²(x)sin²(z) dV
    ratio = (d_mm / a_mm) ** 2
    i_h = (i_hx + ratio * i_hz) / (1.0 + ratio)   # ∫Vs |H|² dV（归一）
    return {"i_e": i_e, "i_h": i_h, "sample_volume_mm3":
            (hi[0] - lo[0]) * y_ext * (hi[2] - lo[2])}


def _points_inside_mesh(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """体素中心 → 内点掩码（+x 射线 Möller–Trumbore 奇偶性；须水密网格）。

    共享边/顶点命中去重：射线恰穿两三角的公共边时两者在同一 t 命中，
    按 t 去重只计一次穿面（否则奇偶翻转 → 内点误判，实测盒对角线夹具
    8 体素错 4 个）。
    """
    v0 = tris[:, 0, :]
    e1 = tris[:, 1, :] - v0
    e2 = tris[:, 2, :] - v0
    direction = np.array([1.0, 0.0, 0.0])
    h = np.cross(direction, e2)                     # (T,3)，与查询点无关
    a_vec = np.einsum("tk,tk->t", e1, h)            # (T,)：行列式，与点无关
    scale = max(float(np.max(np.abs(tris))), 1.0)
    eps = 1e-12 * scale
    t_tol = 1e-9 * scale
    valid = np.abs(a_vec) > eps
    inv_a = np.where(valid, 1.0 / np.where(valid, a_vec, 1.0), 0.0)
    counts = np.zeros(points.shape[0], dtype=np.int64)
    chunk = 4096
    for start in range(0, points.shape[0], chunk):
        p = points[start:start + chunk]
        s_vec = p[:, None, :] - v0[None, :, :]      # (m,T,3)
        u = np.einsum("mtk,tk->mt", s_vec, h) * inv_a[None, :]
        q = np.cross(s_vec, e1[None, :, :])
        v = q[..., 0] * inv_a[None, :]              # q·direction = q_x
        t = np.einsum("mtk,tk->mt", q, e2) * inv_a[None, :]
        crossing = (valid[None, :] & (u >= 0.0) & (u <= 1.0)
                    & (v >= 0.0) & (u + v <= 1.0) & (t > eps))
        sentinel = 1e30 * scale  # 大有限哨兵（inf 的 diff 会出 nan 告警）
        t_hit = np.sort(np.where(crossing, t, sentinel), axis=1)
        hit_first = t_hit[:, 0] < sentinel
        # 不同 t 的有限命中数 = 1 + 「有限值之间的」跳变数（到哨兵的跳变不算）
        finite_to_finite = t_hit[:, 1:] < sentinel
        distinct_extra = (np.diff(t_hit, axis=1) > t_tol) & finite_to_finite
        counts[start:start + chunk] = (
            hit_first.astype(np.int64) + distinct_extra.sum(axis=1))
    return counts % 2 == 1


@register_calculator(
    "cavity_perturbation_shift",
    "矩形腔 TE101 腔体微扰频移（Pozar §6.7 / Slater 定理一阶）：腔尺寸+样品"
    "（轴对齐盒精确解析，或任意三角网格体素积分）→ f0、Δf/f0。小样品极限："
    "E 极大点介质 −2(εr−1)Vs/Vc、金属 −2Vs/Vc（下调）；H 极大区金属符号翻正",
    (("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 高（>0，进 Vc 与场权积分）"),
     ("d_mm", "float mm 腔 z 长（>0）"),
     ("sample_box_mm", "array [x0,y0,z0,x1,y1,z1] 轴对齐样品盒（mm，腔内）"),
     ("sample_triangles_mm", "array (n,3,3) 样品水密三角网格（mm，体素路线）"),
     ("sample_eps_r", "float - 样品相对介电常数（>1；缺省=金属微扰路线）"),
     ("voxel_mm", "float mm 体素步长上限（网格路线；缺省自动=样品最大边/24）")),
    required=("a_mm", "b_mm", "d_mm"),
)
def cavity_perturbation_shift(a_mm: float, b_mm: float, d_mm: float,
                              sample_box_mm: list | None = None,
                              sample_triangles_mm: list | None = None,
                              sample_eps_r: float | None = None,
                              voxel_mm: float | None = None) -> dict:
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    d = _finite(d_mm, "d_mm")
    if a <= 0 or b <= 0 or d <= 0:
        raise ValueError("腔尺寸 a/b/d 必须为正")
    if (sample_box_mm is None) == (sample_triangles_mm is None):
        raise ValueError("sample_box_mm 与 sample_triangles_mm 恰给其一")
    if sample_eps_r is not None:
        eps_r = _finite(sample_eps_r, "sample_eps_r")
        if eps_r <= 1.0:
            raise ValueError("sample_eps_r 必须 >1（介质微扰；εr≤1 无微扰意义）")
        perturbation = "dielectric"
    else:
        eps_r = None
        perturbation = "metal"
    cavity = np.array([a, b, d])
    tol = 1e-9 * max(a, b, d)

    if sample_box_mm is not None:
        raw = [float(v) for v in sample_box_mm]
        if len(raw) != 6 or any(not math.isfinite(v) for v in raw):
            raise ValueError("sample_box_mm 须为 6 个有限数 [x0,y0,z0,x1,y1,z1]")
        lo = [min(raw[0], raw[3]), min(raw[1], raw[4]), min(raw[2], raw[5])]
        hi = [max(raw[0], raw[3]), max(raw[1], raw[4]), max(raw[2], raw[5])]
        if any(hi[k] - lo[k] <= 0.0 for k in range(3)):
            raise ValueError("样品盒三向尺寸必须为正")
        if any(lo[k] < -tol or hi[k] > cavity[k] + tol for k in range(3)):
            raise ValueError(
                f"样品出腔：盒 [{lo}, {hi}] 超出腔 [0, {a}]×[0, {b}]×[0, {d}]")
        integ = _te101_field_integrals_box(a, b, d, lo, hi)
        route = "analytic_box"
        voxel_info: dict[str, Any] = {}
    else:
        from rfauto.core.solid_mesh import solid_mesh_from_triangles

        mesh = solid_mesh_from_triangles(sample_triangles_mm)
        if not mesh.is_watertight:
            raise ValueError("网格路线要求水密样品网格（奇偶性内点判定需闭合面）")
        lo, hi = mesh.bbox_mm
        if any(lo[k] < -tol or hi[k] > cavity[k] + tol for k in range(3)):
            raise ValueError(
                f"样品出腔：网格 bbox [{list(lo)}, {list(hi)}] 超出腔 "
                f"[0, {a}]×[0, {b}]×[0, {d}]")
        extent = np.asarray(hi) - np.asarray(lo)
        if voxel_mm is None:
            step = float(np.max(extent)) / 24.0
        else:
            step = _finite(voxel_mm, "voxel_mm")
            if step <= 0:
                raise ValueError("voxel_mm 必须 >0")
        steps = extent / np.maximum(
            np.ceil(extent / step - 1e-12), 1.0)
        n_cells = np.maximum(np.ceil(extent / step - 1e-12).astype(int), 1)
        if int(np.prod(n_cells)) > 4_000_000:
            raise ValueError(
                f"体素数 {int(np.prod(n_cells))} 超上限 4e6：调大 voxel_mm")
        axes = [lo[k] + (np.arange(n_cells[k]) + 0.5) * steps[k]
                for k in range(3)]
        gx, gy, gz = np.meshgrid(*axes, indexing="ij")
        points = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
        inside = _points_inside_mesh(points, np.asarray(sample_triangles_mm,
                                                        dtype=float))
        if not bool(np.any(inside)):
            raise ValueError("体素判定网格内部为空（网格退化或步长过粗）")
        pts_in = points[inside]
        i_e = float(np.sum(np.sin(np.pi * pts_in[:, 0] / a) ** 2
                           * np.sin(np.pi * pts_in[:, 2] / d) ** 2)
                    * np.prod(steps))
        ratio2 = (d / a) ** 2
        i_h = float(np.sum(
            (np.sin(np.pi * pts_in[:, 0] / a) ** 2
             * np.cos(np.pi * pts_in[:, 2] / d) ** 2)
            + ratio2 * (np.cos(np.pi * pts_in[:, 0] / a) ** 2
                        * np.sin(np.pi * pts_in[:, 2] / d) ** 2))
            * np.prod(steps) / (1.0 + ratio2))
        sample_volume = float(np.sum(inside) * np.prod(steps))
        mesh_volume = mesh.volume_mm3
        voxel_info = {
            "voxel_mm": round(float(np.max(steps)), 12),
            "voxel_count": int(np.sum(inside)),
            "voxel_vs_mesh_volume_rel_err": round(
                abs(sample_volume - mesh_volume)
                / max(mesh_volume, 1e-30), 9),
        }
        integ = {"i_e": i_e, "i_h": i_h, "sample_volume_mm3": sample_volume}
        route = "voxel_mesh"

    f0_ghz = (C_MM_GHZ / 2.0) * math.sqrt(1.0 / (a * a) + 1.0 / (d * d))
    vc = a * b * d
    weight_cavity = vc / 4.0  # ∫Vc|E0|²dV（E0=E 极大幅值归一）
    if perturbation == "dielectric":
        df_over_f = -(eps_r - 1.0) / 2.0 * integ["i_e"] / weight_cavity
        extra = {"eps_r": eps_r}
    else:
        df_over_f = 0.5 * (integ["i_h"] - integ["i_e"]) / weight_cavity
        extra = {}
    return {"f0_ghz": round(f0_ghz, 9),
            "df_over_f": round(df_over_f, 15),
            "df_ghz": round(f0_ghz * df_over_f, 15),
            "sample_volume_mm3": round(integ["sample_volume_mm3"], 12),
            "cavity_volume_mm3": round(vc, 12),
            "field_weight_ratio": round(integ["i_e"] / weight_cavity, 12),
            "perturbation": perturbation,
            "route": route,
            **extra,
            **voxel_info,
            "note": "口径：Pozar《Microwave Engineering》§6.7 腔体微扰"
                    "（材料微扰式）+ Slater 形状微扰一阶式；TE101 场权 "
                    "sin²(πx/a)sin²(πz/d)，∫Vc|E|²=Vc/4。金属形状因子"
                    "（球/针极化率修正）不在一阶式内（followUp）。"}


# ─── 符号归纳公式登记（experimental 默认关，2026-09-16 口径）─────────────────
# 口径（2026-09-16）：所有符号回归归纳公式入库但**默认关**、显式开关才用。
# 机制：register_symbolic_formula 把
# symbolic_fit 的 CandidateFormula 一律以 experimental=True 登记进注册表——
# names()/describe() 默认不列、service 运行默认拒绝（run_calculator 显式
# allow_experimental=True，或 configs/settings.yaml 的
# calculators.allow_experimental: true 放行）。人工审核晋级
# 是另一个显式动作：以 register_calculator(experimental=False) 重登记正式键，
# 本机制不提供自动晋级。
# 求值安全：项字符串只允许 build_library 词表能产出的语法
# （常量/已声明变量/+-*/、幂、sqrt/log），ast 白名单校验后才 eval——拒绝任何
# 经 term 字符串进入的任意代码；系数只来自记录产物（runs/）或确定性重拟合。

_ALLOWED_SYMBOLIC_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ALLOWED_SYMBOLIC_FUNCS = frozenset({"sqrt", "log"})


def _validate_symbolic_node(node: ast.AST, allowed_names: frozenset[str]) -> None:
    """递归校验公式语法树：只允许数值常量、已声明变量、四则/幂、一元 ±、
    sqrt/log 单参调用；其余节点一律 ValueError（显式，不静默降级）。"""
    if isinstance(node, ast.Expression):
        _validate_symbolic_node(node.body, allowed_names)
        return
    if (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)):
        return
    if isinstance(node, ast.Name) and node.id in allowed_names:
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_SYMBOLIC_BINOPS):
        _validate_symbolic_node(node.left, allowed_names)
        _validate_symbolic_node(node.right, allowed_names)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate_symbolic_node(node.operand, allowed_names)
        return
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _ALLOWED_SYMBOLIC_FUNCS
            and not node.keywords and len(node.args) == 1):
        _validate_symbolic_node(node.args[0], allowed_names)
        return
    raise ValueError(
        f"归纳公式项含不允许的语法节点: {type(node).__name__}"
        "（只允许常量/已声明变量/四则幂/sqrt/log——build_library 词表口径）")


def _compile_symbolic_terms(
    terms: Sequence[str], allowed_names: frozenset[str],
) -> list[Any]:
    """把归纳式各项编译为可求值代码对象（^→** 后 ast 白名单校验）。

    返回与 terms 等长的列表：None 表示常数项 1（build_library 的常数列），
    否则为 compile 后的表达式（eval 时配 sqrt/log 环境）。
    """
    compiled: list[Any] = []
    for term in terms:
        if term == "1":
            compiled.append(None)
            continue
        tree = ast.parse(term.replace("^", "**"), mode="eval")
        _validate_symbolic_node(tree, allowed_names)
        compiled.append(compile(tree, f"<symbolic:{term}>", "eval"))
    return compiled


def _eval_symbolic_terms(compiled: Sequence[Any], coefficients: Sequence[float],
                         namespace: Mapping[str, float]) -> float:
    """确定性求值 Σ cᵢ·termᵢ（纯 float 闭式；sqrt/log 来自 math）。"""
    env = {"sqrt": math.sqrt, "log": math.log, "__builtins__": {}}
    total = 0.0
    for code, coef in zip(compiled, coefficients, strict=True):
        term_value = 1.0 if code is None else float(eval(code, env, dict(namespace)))
        total += float(coef) * term_value
    return total


def register_symbolic_formula(
    candidate: CandidateFormula,
    key: str,
    *,
    variables: Sequence[str],
    param_names: Sequence[str] | None = None,
    output_key: str = "y",
    provenance: str = "",
    domain: Mapping[str, tuple[float, float]] | None = None,
    description: str | None = None,
    registry: CalculatorRegistry | None = None,
) -> str:
    """把 symbolic_fit 的 CandidateFormula 以 experimental=True 登记进注册表。

    后续一切自动归纳公式统一走本入口（一律实验态、默认关，见节首口径块）。
    - variables：项字符串里出现的变量名（build_library 词表口径，如 L_mm）；
    - param_names：计算器入参名（缺省=variables 原名；用于把库内变量名映射到
      注册表参数命名惯例，如 L_mm→l_mm）；
    - output_key：返回 dict 的量名（如 f0_ghz）；
    - provenance：出处串（数据集 id/点数/种子/rmse/裁判结论），进 description
      与每次返回值——系数必须可溯源（记录产物或确定性重拟合）；
    - domain：{入参名: (lo, hi)} 适用域——拟合数据范围外显式报错（外推未验证，
      不保证）。
    重名注册照常 ValueError；返回注册键名。
    """
    from rfauto.core.symbolic_fit import format_formula

    if len(set(variables)) != len(variables):
        raise ValueError(f"variables 有重复: {tuple(variables)}")
    pnames = tuple(param_names) if param_names is not None else tuple(variables)
    if len(pnames) != len(variables):
        raise ValueError("param_names 与 variables 长度不一致")
    terms = tuple(str(t) for t in candidate.terms)
    coefficients = tuple(float(c) for c in candidate.coefficients)
    if len(terms) != len(coefficients):
        raise ValueError("terms 与 coefficients 长度不一致")
    formula_text = format_formula(terms, coefficients, name=output_key)
    if description is None:
        description = (f"符号回归归纳公式（实验态，默认关闭）：{formula_text}。"
                       f"{provenance}")
    compiled = _compile_symbolic_terms(terms, frozenset(variables))
    domain_map: dict[str, tuple[float, float]] = dict(domain or {})
    if not set(domain_map) <= set(pnames):
        raise ValueError(
            f"domain 的键必须是入参名 {list(pnames)}，"
            f"收到 {sorted(domain_map)}")

    def func(**kwargs: float) -> dict[str, Any]:
        known = set(pnames)
        unknown = [k for k in kwargs if k not in known]
        if unknown:
            raise TypeError(f"未知参数: {unknown}（该计算器需要: {sorted(known)}）")
        ns: dict[str, float] = {}
        for var, pname in zip(variables, pnames, strict=True):
            if pname not in kwargs:
                raise ValueError(f"缺少参数: {pname}")
            v = float(kwargs[pname])
            if not math.isfinite(v):
                raise ValueError(f"{pname} 必须为有限数")
            ns[var] = v
        for pname, (lo, hi) in domain_map.items():
            v = float(kwargs[pname])
            if not lo <= v <= hi:
                raise ValueError(
                    f"{pname}={v} 超出归纳式适用域 [{lo}, {hi}]"
                    "（拟合数据范围外不保证，外推未验证）")
        value = _eval_symbolic_terms(compiled, coefficients, ns)
        return {output_key: round(value, 9),
                "formula": formula_text,
                "provenance": provenance,
                "note": "实验性归纳公式：对观测数据的最小二乘近似，不含物理"
                        "推导；默认关闭，需显式开关；适用域外不保证"}

    target = registry if registry is not None else CALCULATOR_REGISTRY
    params = tuple(
        (pname, f"float - 归纳变量 {var}（适用域/出处见 description）")
        for var, pname in zip(variables, pnames, strict=True))
    target.register(CalculatorSpec(
        name=key, description=description, func=func, params=params,
        required=pnames, experimental=True))
    return key


# patch 基模谐振候选公式（2026-09-12；系数与误差逐位
# 取自符号回归标定产物 patch_f0 的 induced.best）：
#   f0 = 0.0261448 + 75.1834/L + 0.0162789·L/W  （GHz；L/W 单位 mm）
# 51 真实 openEMS patch 点（L∈[35,45]、W∈[40,60]、er=3.66、h=0.508 恒定），
# holdout 每 5 留 1：rmse_holdout=0.001773GHz、r2_train=0.999889；独立裁判
# vs Hammerstad/HJ（patch_resonance_hj_ghz，#118 不自证）：mean −0.699%、
# max|dev|=0.765% ≤ 2% PASS。er/h 在数据集上恒定 → 本式不含 er/h
# （不可辨识），仅适用该基底；适用域外显式报错。实验态登记（默认关）。

def _register_e13_patch_f0() -> str:
    from rfauto.core.symbolic_fit import CandidateFormula

    return register_symbolic_formula(
        CandidateFormula(
            terms=("1", "1/L_mm", "L_mm/W_mm"),
            coefficients=(0.026144821820511657, 75.18344519064581,
                          0.0162789352212073),
            complexity=8,
            mse_train=1.3517603341483583e-06,
            rmse_train=0.0011626522842829487,
            r2_train=0.9998889118662188,
            mse_holdout=3.144626978633213e-06,
            rmse_holdout=0.0017733096116113545,
        ),
        "patch_f0_symbolic_e13",
        variables=("L_mm", "W_mm"),
        param_names=("l_mm", "w_mm"),
        output_key="f0_ghz",
        provenance=(
            "（符号回归标定产物 patch_f0）：数据集为 51 真实 openEMS 点"
            "（L∈[35,45]mm、W∈[40,60]mm、er=3.66、h=0.508），基模=[1.3,2.7]GHz"
            " 最低频 ≥3dB 局部谷；holdout 每 5 留 1，rmse_holdout=0.001773GHz、"
            "r2_train=0.999889；独立裁判 vs Hammerstad/HJ mean −0.699%、"
            "max|dev|=0.765%≤2% PASS"),
        domain={"l_mm": (35.0, 45.0), "w_mm": (40.0, 60.0)},
    )


_register_e13_patch_f0()



# ─── 槽线（slotline，单面金属开缝、无背板）闭式：Janaswamy–Schaubert 1986 ────────
# 内核在 core/slotline.py（常数双源核对、分段有效域、越界显式拒绝不外推，
# 路线 A 闭式裁判面；文献锚 Table 3.2 五频点 −0.83~−0.97%）。
# 本段只做注册壳：(w, h, εr, f) → (λ'/λ0, εeff, β, Z0) 与 Z0 → w 综合。
# 注意：全部量随频率变化（W/λ0、d/λ0 进入拟合式），freq_ghz 为必需参数；
# 仓库缺省叠层 h=0.508mm@2.5GHz 因 d/λ0=0.0042<0.006 落域外 → 显式 ValueError
# （设计点 RO4350B 60mil h=1.524mm）。

@register_calculator(
    "slotline_analysis",
    "槽线（slotline）分析：Janaswamy–Schaubert 闭式 (w, h, εr, f) → "
    "(λ'/λ0, εeff, β, Z0)；越有效域显式报错不外推。",
    (("w_mm", "float mm 槽宽（金属面上的缝）"),
     ("h_mm", "float mm 基板厚（单面金属，基板下为空气）"),
     ("epsilon_r", "float - 基板相对介电常数（2.22–9.8 两段拟合）"),
     ("freq_ghz", "float GHz 频率（W/λ0、d/λ0 进入拟合式，必需）")),
    required=("w_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def slotline_analysis(w_mm: float, h_mm: float, epsilon_r: float,
                      freq_ghz: float) -> dict:
    from rfauto.core.slotline import slotline_closed_form

    r = slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz)
    lam_g_mm = r.lambda_ratio * _C0_MS / (float(freq_ghz) * 1e9) * 1e3
    return {"z0_ohm": round(r.z0_ohm, 2),
            "eps_eff": round(r.eps_eff, 4),
            "lambda_ratio": round(r.lambda_ratio, 5),
            "beta_rad_m": round(r.beta_rad_m, 4),
            "lambda_g_mm": round(lam_g_mm, 3),
            "segment": r.segment,
            "w_over_lambda0": round(r.w_over_lambda0, 5),
            "d_over_lambda0": round(r.d_over_lambda0, 5)}


@register_calculator(
    "slotline_synthesis",
    "槽线（slotline）综合：目标 Z0 → 槽宽 w（同频窄槽段 0.0015≤W/λ0≤0.075 "
    "括号内 brentq，回代自洽；不可达/越域显式报错）",
    (("z0_ohm", "float Ω 目标特性阻抗（功率-电压定义）"),
     ("h_mm", "float mm 基板厚"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率")),
    required=("z0_ohm", "h_mm", "epsilon_r", "freq_ghz"),
)
def slotline_synthesis(z0_ohm: float, h_mm: float, epsilon_r: float,
                       freq_ghz: float) -> dict:
    from scipy.optimize import brentq

    from rfauto.core.slotline import (
        W_OVER_LAMBDA0_NARROW_RANGE,
        slotline_closed_form,
    )

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"slotline_synthesis: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    lam0_mm = _C0_MS / (float(freq_ghz) * 1e9) * 1e3
    # 窄槽段有效窗（w/λ0 ∈ [0.0015, 0.075]）内侧留 1e-6 相对余量防边界舍入
    w_lo = W_OVER_LAMBDA0_NARROW_RANGE[0] * lam0_mm * (1.0 + 1e-6)
    w_hi = W_OVER_LAMBDA0_NARROW_RANGE[1] * lam0_mm * (1.0 - 1e-6)

    def objective(w_mm: float) -> float:
        # d/λ0、εr 越域在此处即抛 ValueError（分段判定先于数值）
        return slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz).z0_ohm - z_t

    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    # Z0 随 w 单调上升（√(W/λ0) 主项；数值单调性由单测网格钉住）；括号越界如实报错
    if z_lo > 0.0 or z_hi < 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出窄槽段可达范围 "
            f"[{z_lo + z_t:.1f}, {z_hi + z_t:.1f}]Ω"
            f"（w∈[{w_lo:.4f}, {w_hi:.4f}]mm @ {freq_ghz}GHz 括号扫描）")
    w_mm = float(brentq(objective, w_lo, w_hi, xtol=1e-9))
    r = slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz)
    lam_g_mm = r.lambda_ratio * lam0_mm
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(r.z0_ohm, 2),
            "eps_eff": round(r.eps_eff, 4),
            "lambda_ratio": round(r.lambda_ratio, 5),
            "beta_rad_m": round(r.beta_rad_m, 4),
            "lambda_g_mm": round(lam_g_mm, 3), "segment": r.segment}


# ─── SIW（基片集成波导）闭式：Cassivi 2002 等效宽度 + RWG TE10 等效 ───────────
# 双源核实与全部常数出处：runs/siw_family/criteria.md §1（铁律 1c）——
# 等效宽度 w_eff = w − d²/(0.95·s)（来源 A：Wikipedia SIW 条目引 Cassivi et al.
# 2002 MWCL 12(9):333–335 / Bozzi 2011 IET 综述；来源 B：Microwaves101 SIW 条目
# eq.4 引 Wu–Deslandes–Cassivi TELSIKS 2003；rfessentials/calculator.academy 文本
# 逐字交叉印证）；TE10 截止与色散按"同宽 w_eff 同填充的介质矩形波导"等效
# （来源 A 明文）：
#   fc10 = c/(2·w_eff·√εr)，β(f) = √((n·k0)² − (π/w_eff)²)，n=√εr，kc=π/w_eff。
# 设计规则（过孔藩篱泄漏控制，来源 B[1]/C 双源）：s ≤ 2·d 且 d < λ_sub/5
# （λ_sub = c/(f·√εr) 为基板内平面波波长；较 λg 口径更严，取严者——
# NW Engineering Solutions SIW 设计条件明文 + Microwaves101 eq.5/6 同源）。
# 波导阻抗口径（确定性内核非手数，#7）：TE10 波阻抗 Z_TE=ωμ0/β（u/i 定义），
# 功率-电压定义 Z_PV = 2·b·Z_TE/w_eff（b=基板厚 h；V=中线全高电压=E0·b、
# P=E0²·a·b/(4·Z_TE) 消元）——渲染层 LumpedPort R 与 OE 锚判读同源消费。
# 回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；
# εr=1、a=22.86mm 复现 WR-90 空气波导 fc=6.5571GHz（Pozar 教科书值）。

def siw_effective_width_mm(w_mm: float, d_mm: float, s_mm: float) -> float:
    """Cassivi 2002 等效宽度（mm）：w_eff = w − d²/(0.95·s)。

    只做公式本体；几何设计规则守卫在 siw_check_design_rules。
    值源（DP-3 第二批改道）：优先 siw.w_eff.lit-v1 公式锚
    （knowledge/anchors.yaml，expr=w_mm - d_mm**2/(0.95*s_mm)，双源
    Cassivi 2002 / Wu-Deslandes-Cassivi 2003）；锚不可解析（未注册/失败）
    回退本闭式——回退式与锚式逐位相等（同 op 序，test_anchors_core a4 /
    test_anchor_wire_df7 钉），零行为变化。"""
    got = _siw_w_eff_anchor_value(float(w_mm), float(d_mm), float(s_mm))
    if got is not None:
        return got
    return float(w_mm) - (float(d_mm) ** 2) / (0.95 * float(s_mm))


def siw_check_design_rules(w_mm: float, d_mm: float, s_mm: float,
                           epsilon_r: float, freq_ghz: float | None = None,
                           ref_freq_ghz: float | None = None) -> dict:
    """过孔藩篱设计规则复核（双源出处见 criteria.md §1），违反显式 ValueError。

    - s > d：相邻过孔不得重叠（物理可制造性）；
    - s ≤ 2·d：泄漏控制上界（Microwaves101 eq.5/6 同源；
      NW Engineering 明文 "via spacing s must be less than double the via
      diameter d"）；
    - d < λ_sub/5：直径远小于波长（λ_sub=c/(f·√εr)；ref_freq_ghz 缺省取
      freq_ghz，都缺省用 fc 折算不可行——本检查只在给出频率时执行）。
    返回实测比值表（供判读留痕），全部通过才返回。
    """
    w = float(w_mm)
    d = float(d_mm)
    s = float(s_mm)
    er = float(epsilon_r)
    for name, v in (("w_mm", w), ("d_mm", d), ("s_mm", s)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"siw: {name} 必须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        # εr=1 合法（空气填充 RWG 极限=回收基准 WR-90 钉用）
        raise ValueError(f"siw: epsilon_r 必须为不小于 1 的有限数，得到 {er!r}")
    if not s > d:
        raise ValueError(f"siw: 过孔心距 s={s}mm 必须大于直径 d={d}mm（孔不重叠）")
    if s > 2.0 * d:
        raise ValueError(
            f"siw: 过孔心距 s={s}mm 超出泄漏控制上界 2·d={2.0 * d:.4g}mm"
            "（设计规则 s≤2d，Microwaves101 eq.5/6 / NWES，criteria.md §1）")
    lam_sub_mm = None
    f_ref = ref_freq_ghz if ref_freq_ghz is not None else freq_ghz
    if f_ref is not None:
        f_hz = float(f_ref) * 1e9
        if not (math.isfinite(f_hz) and f_hz > 0.0):
            raise ValueError(f"siw: 频率必须为正有限数，得到 {f_ref!r}")
        lam_sub_mm = _C0_MS / (f_hz * math.sqrt(er)) * 1e3
        if not d < lam_sub_mm / 5.0:
            raise ValueError(
                f"siw: 过孔直径 d={d}mm 未满足 d<λ_sub/5="
                f"{lam_sub_mm / 5.0:.4g}mm @ {f_ref}GHz"
                "（设计规则，criteria.md §1；λ_sub 口径较 λg 更严取严者）")
    return {"s_over_d": round(s / d, 6),
            "d_over_lambda_sub": (round(d / lam_sub_mm, 6)
                                  if lam_sub_mm is not None else None)}


def siw_beta_rad_m(w_eff_mm: float, epsilon_r: float,
                   freq_ghz: float) -> tuple[float, float]:
    """等效 RWG TE10 色散：返回 (beta_rad_m, fc10_ghz)。

    f≤fc10 时 β 为虚数（倏逝）——返回 NaN，由调用方按截止下衰减
    α=√(kc²−k²) 自行处理（分析键内部已给出 α）。
    """
    weff_m = float(w_eff_mm) * 1e-3
    f_hz = float(freq_ghz) * 1e9
    n = math.sqrt(float(epsilon_r))
    k0 = 2.0 * math.pi * f_hz / _C0_MS
    kc = math.pi / weff_m
    fc10_ghz = _C0_MS / (2.0 * weff_m * n) / 1e9
    k = k0 * n
    if k <= kc:
        return float("nan"), fc10_ghz
    return math.sqrt(k * k - kc * kc), fc10_ghz


@register_calculator(
    "siw_analysis",
    "SIW 分析：Cassivi 2002 等效宽度 + RWG TE10 等效 (w, d, s, εr, f) → "
    "(fc10, weff, β, λg, Z_TE, Z_PV)；过孔设计规则违规显式报错不外推。",
    (("w_mm", "float mm 两过孔列心距（物理宽度）"),
     ("d_mm", "float mm 金属化过孔直径"),
     ("s_mm", "float mm 过孔心距（同列相邻孔中心间距）"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 工作频率（β/λg/设计规则 d<λ_sub/5 检查）")),
    required=("w_mm", "d_mm", "s_mm", "epsilon_r", "freq_ghz"),
)
def siw_analysis(w_mm: float, d_mm: float, s_mm: float, epsilon_r: float,
                 freq_ghz: float) -> dict:
    f_ghz = float(freq_ghz)
    if not (math.isfinite(f_ghz) and f_ghz > 0.0):
        raise ValueError(f"siw_analysis: freq_ghz 必须为正有限数，得到 {freq_ghz!r}")
    rules = siw_check_design_rules(w_mm, d_mm, s_mm, epsilon_r, freq_ghz=f_ghz)
    weff_mm = siw_effective_width_mm(w_mm, d_mm, s_mm)
    if not weff_mm > 0.0:
        raise ValueError(
            f"siw_analysis: 等效宽度 w_eff={weff_mm:.4f}mm 非正（w 过小或 d/s 过大）")
    weff_m = weff_mm * 1e-3
    n = math.sqrt(float(epsilon_r))
    k0 = 2.0 * math.pi * f_ghz * 1e9 / _C0_MS
    kc = math.pi / weff_m
    fc10_ghz = _C0_MS / (2.0 * weff_m * n) / 1e9
    k = k0 * n
    if k > kc:
        beta = math.sqrt(k * k - kc * kc)
        lam_g_mm = 2.0 * math.pi / beta * 1e3
        z_te = 2.0 * math.pi * f_ghz * 1e9 * 1.25663706212e-6 / beta
        alpha_np_m = 0.0
    else:
        beta = float("nan")
        lam_g_mm = float("nan")
        z_te = float("nan")
        alpha_np_m = math.sqrt(kc * kc - k * k)
    # 功率-电压波阻抗（等效波导 b=h：R=2·b·Z_TE/w_eff；h 未入参——SIW 的
    # fc10/β/Z_TE 与 h 无关（Microwaves101 SIW 条目明文），Z_PV 需 h 时由
    # 渲染层按模板 h 换算，本键只出与 h 无关的量）
    return {"fc10_ghz": round(fc10_ghz, 4),
            "weff_mm": round(weff_mm, 4),
            "kc_rad_m": round(kc, 3),
            "beta_rad_m": (round(beta, 4) if math.isfinite(beta) else None),
            "alpha_below_cutoff_np_m": (None if math.isfinite(beta)
                                        else round(alpha_np_m, 3)),
            "lambda_g_mm": (round(lam_g_mm, 4) if math.isfinite(lam_g_mm)
                            else None),
            "z_te_ohm": (round(z_te, 3) if math.isfinite(z_te) else None),
            "lambda_sub_mm": round(_C0_MS / (f_ghz * 1e9 * n) * 1e3, 4),
            "f_over_fc": round(f_ghz / fc10_ghz, 6),
            "design_rules": rules}


@register_calculator(
    "siw_synthesis",
    "SIW 综合：目标 TE10 截止 fc10 → 两列心距 w（w_eff=c/(2·fc10·√εr) 反解 "
    "Cassivi 式；设计规则违规显式报错；回代自洽）。",
    (("fc10_ghz", "float GHz 目标 TE10 截止频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("d_mm", "float mm 金属化过孔直径"),
     ("s_mm", "float mm 过孔心距")),
    required=("fc10_ghz", "epsilon_r", "d_mm", "s_mm"),
)
def siw_synthesis(fc10_ghz: float, epsilon_r: float, d_mm: float,
                  s_mm: float) -> dict:
    fc = float(fc10_ghz)
    if not (math.isfinite(fc) and fc > 0.0):
        raise ValueError(f"siw_synthesis: fc10_ghz 必须为正有限数，得到 {fc10_ghz!r}")
    weff_mm = _C0_MS / (2.0 * fc * 1e9 * math.sqrt(float(epsilon_r))) * 1e3
    d = float(d_mm)
    s = float(s_mm)
    # w = w_eff + d²/(0.95·s)（Cassivi 式反解）；设计规则检查用 fc10（带内最松
    # 端——λ_sub 随 f 升高缩短，高频端的 d<λ_sub/5 由 siw_analysis 按实查 f 把关）
    w_mm = weff_mm + (d * d) / (0.95 * s)
    rules = siw_check_design_rules(w_mm, d, s, epsilon_r,
                                   ref_freq_ghz=fc)
    weff_back = siw_effective_width_mm(w_mm, d, s)
    fc_back = _C0_MS / (2.0 * weff_back * 1e-3
                        * math.sqrt(float(epsilon_r))) / 1e9
    if abs(fc_back - fc) > 1e-9 * max(1.0, fc):
        raise ValueError("siw_synthesis: 回代自洽失败（数值内部错误）")
    return {"w_mm": round(w_mm, 4),
            "weff_mm": round(weff_mm, 4),
            "weff_roundtrip_mm": round(weff_back, 6),
            "fc10_roundtrip_ghz": round(fc_back, 6),
            "kc_rad_m": round(math.pi / (weff_mm * 1e-3), 3),
            "design_rules": rules}


# ─── DP-5 系统级预算引擎 + 混频杂散搜索（payload 在 core/cascade.py）──────────
# 公式口径/规格书勘误（IIP3 级联式增益落分子）/经验口径标注见 core/cascade.py
# 模块 docstring 与 runs/df6_dp5cascade/criteria.md §0；回收钉在
# tests/unit/test_cascade.py（≤1e-12 逐位）。


@register_calculator(
    "cascade_budget",
    "DP-5 级联预算：stage 列表 → 总增益/Friis NF/IIP3·OIP3 级联/P1dB(经验幂和)/"
    "噪声底/SFDR/灵敏度/链路裕量。stage schema type∈{amp,mixer,filter,atten,"
    "cable}；无源级 NF 缺省=插损（T0）；skrf 真实插损解析在 service 层",
    (("stages", "list[dict] 级表（顺序=信号流向；type/gain_db/nf_db?/"
      "iip3_dbm?/p1db_dbm?/bw_hz?）"),
     ("snr_min_db", "float dB 解调最小 SNR（默认 10）"),
     ("rx_power_dbm", "float dBm 接收功率（可选，给定时输出链路裕量）"),
     ("bw_hz", "float Hz 系统噪声带宽（缺省取末级 bw_hz，皆无则显式报错）"),
     ("t_kelvin", "float K 等效热噪声温度（默认 290）")),
    required=("stages",),
)
def cascade_budget(stages: list[dict], snr_min_db: float = 10.0,
                   rx_power_dbm: float | None = None,
                   bw_hz: float | None = None,
                   t_kelvin: float = 290.0) -> dict:
    from rfauto.core.cascade import cascade_budget as _cascade_budget

    return _cascade_budget(stages, snr_min_db=snr_min_db,
                           rx_power_dbm=rx_power_dbm, bw_hz=bw_hz,
                           t_kelvin=t_kelvin)


@register_calculator(
    "spur_search",
    "DP-5 混频杂散落带搜索：f_spur=|m·f_RF±n·f_LO| 全阶枚举（缺省 m+n≤7），"
    "矩形近似卷积落带判据，危险等级=阶数反比；只报频率落带不报电平",
    (("f_rf_hz", "float Hz RF 中心频率（>0）"),
     ("f_lo_hz", "float Hz 本振频率（>0）"),
     ("if_center_hz", "float Hz 目标 IF 中心（缺省 |f_RF−f_LO|）"),
     ("if_bw_hz", "float Hz 目标带宽（默认 0）"),
     ("rf_bw_hz", "float Hz RF 信号带宽（默认 0，谐波带宽线性缩放）"),
     ("lo_bw_hz", "float Hz LO 带宽（默认 0=理想 LO）"),
     ("max_order", "int 最大阶数 m+n（默认 7）")),
    required=("f_rf_hz", "f_lo_hz"),
)
def spur_search(f_rf_hz: float, f_lo_hz: float,
                if_center_hz: float | None = None, if_bw_hz: float = 0.0,
                rf_bw_hz: float = 0.0, lo_bw_hz: float = 0.0,
                max_order: int = 7) -> dict:
    from rfauto.core.cascade import spur_search as _spur_search

    spurs = _spur_search(
        f_rf_hz, f_lo_hz, if_center_hz=if_center_hz, if_bw_hz=if_bw_hz,
        rf_bw_hz=rf_bw_hz, lo_bw_hz=lo_bw_hz, max_order=max_order)
    n_in_band = sum(1 for s in spurs if s["in_band"] and s["role"] == "spur")
    return {"n_products": len(spurs), "n_spurs_in_band": n_in_band,
            "f_rf_hz": f_rf_hz, "f_lo_hz": f_lo_hz,
            "if_center_hz": (abs(f_rf_hz - f_lo_hz)
                             if if_center_hz is None else if_center_hz),
            "max_order": max_order, "spurs": spurs}


@register_calculator(
    "if_plan_sweep",
    "DP-5 IF 频率规划扫掠：IF 候选网格逐点重取本振（low/high 侧注入）→ 逐点"
    "杂散落带判定 + spurious-free 窗口表（窗口边界=网格分辨率内）",
    (("f_rf_hz", "float Hz RF 中心频率（>0）"),
     ("if_lo_hz", "float Hz IF 扫掠下限（>0）"),
     ("if_hi_hz", "float Hz IF 扫掠上限（low 侧须 <f_RF）"),
     ("side", "str 注入侧 'low'|'high'（默认 low：f_LO=f_RF−IF）"),
     ("n_points", "int 网格点数（默认 201）"),
     ("if_bw_hz", "float Hz 目标带宽（默认 0）"),
     ("rf_bw_hz", "float Hz RF 信号带宽（默认 0）"),
     ("lo_bw_hz", "float Hz LO 带宽（默认 0）"),
     ("max_order", "int 最大阶数 m+n（默认 7）")),
    required=("f_rf_hz", "if_lo_hz", "if_hi_hz"),
)
def if_plan_sweep(f_rf_hz: float, if_lo_hz: float, if_hi_hz: float,
                  side: str = "low", n_points: int = 201,
                  if_bw_hz: float = 0.0, rf_bw_hz: float = 0.0,
                  lo_bw_hz: float = 0.0, max_order: int = 7) -> dict:
    from rfauto.core.cascade import if_plan_sweep as _if_plan_sweep

    return _if_plan_sweep(
        f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz, side=side,
        n_points=n_points, if_bw_hz=if_bw_hz, rf_bw_hz=rf_bw_hz,
        lo_bw_hz=lo_bw_hz, max_order=max_order)


# ─── DP-2 耦合矩阵诊断三件套（2026-09-24，规格 docs/plan_deepdive_specs_20260924.md
#     §DP-2；判据预声明 runs/df6_dp2diag/criteria.md 先写后跑）────────────────────
# 定位：既有 6 个 coupling_matrix 键（Cauchy 反提 coupling_matrix_extract 等）
# 保留为初值/独立裁判不删改（#315），本段是互补镜像面（VF+LM 固定拓扑诊断 +
# Q 双通道 + Dishal 调谐 critique）。
#
# C 系数裁决（#118/#300：合成回收唯一确定，判据 runs/df6_dp2diag/criteria.md §3）：
#   Qe = ω0·τmax/C 的 C 由单极点合成回收钉死，且**分属两个测量端口**：
#   * S21 透射泄漏口径（Dishal 原生通道，其余腔远失谐）：泄漏路径 ≈ 单极点
#     K/(Ω−jm01²)，τ_phys = 2Qe/ω0 ⟹ **C=2**（失谐 |Δm|=2..50 实测 C_eff
#     2.246→2.0008，收敛极限 2；有限失谐膨胀与峰位偏移指纹同源）；
#   * S11 反射全通口径（无耗一端口，零点镜像极点）：S11=−(Ω+jm01²)/(Ω−jm01²)，
#     τ_phys = 4Qe/ω0 ⟹ **C=4**（精确恒等式，任意耦合成立）；
#   * 规格书期望的配对（反射/2、Dishal/4）经推导+合成回收证伪互换；
#     单极点精确推导 + coupling_matrix_response 内核数值回收双重钉死
#     （tests/unit/test_dp2_diagnosis.py::test_c_coefficient_pins）。
#   注记：N=1 双端对称耦合（Q_L=Qe/2）给 C=1，不在候选集，备查。

_CAT_C_TRANSMISSION = 2.0  # Qe=ω0·τmax/C，S21 透射泄漏口径（Dishal）
_CAT_C_REFLECTION = 4.0    # Qe=ω0·τmax/C，S11 反射全通口径


def _dp2_response_batch(m, qe0, qel, omega):
    """_cm_response_raw 的向量化批口径（spec 2a「向量化」项）：逐点公式与
    批公式对同一 m/qe/omega 逐位一致（np.linalg.solve 批=逐个同 LAPACK 路径，
    test_dp2_response_batch_bitwise 钉死 #329）。返回 (S11, S21) 数组。"""
    omega = np.asarray(omega, dtype=float)
    n2 = m.shape[0]
    y = np.zeros((omega.size, n2, n2), dtype=complex)
    idx = np.arange(n2)
    eye = np.eye(n2, dtype=bool)
    diag = 1j * (omega[:, None] - m[None, idx, idx])
    diag[:, 0] = qe0
    diag[:, n2 - 1] = qel
    y[:, idx, idx] = diag
    y[:, ~eye] = (-1j * m[None, ~eye])
    b = np.zeros((omega.size, n2, 1), dtype=complex)
    b[:, 0, 0] = 1.0
    v = np.linalg.solve(y, b)[:, :, 0]
    s11 = 1.0 - 2.0 * v[:, 0] / qe0
    s21 = 2.0 * v[:, n2 - 1] / math.sqrt(qe0 * qel)
    return s11, s21


def _dp2_omega_norm(freq_ghz, f0_ghz, fbw):
    """物理频率 → 归一化低通 Ω=(f/f0−f0/f)/fbw（与 coupling_matrix_response 同口径）。"""
    f = np.asarray(freq_ghz, dtype=float)
    return (f / f0_ghz - f0_ghz / f) / fbw


def _dp2_group_delay_phys(freq_ghz, s_complex):
    """物理群时延 τ(f)=−dφ/dω（秒），ω=2πf rad/s；确定性数值差分。"""
    f = np.asarray(freq_ghz, dtype=float)
    ph = np.unwrap(np.angle(np.asarray(s_complex, dtype=complex)))
    return -np.gradient(ph, 2.0 * np.pi * f * 1e9)


def _dp2_prominent_peaks(values, rel=0.3):
    """显著局部峰（幅值 ≥rel·max）索引升序；邻位重复峰取大者。"""
    t = np.abs(np.asarray(values, dtype=float))
    if t.size < 3:
        return []
    tmax = float(t.max())
    out: list[int] = []
    for i in range(1, t.size - 1):
        if t[i] > t[i - 1] and t[i] >= t[i + 1] and t[i] >= rel * tmax:
            if out and i - out[-1] <= max(2, t.size // 100):
                if t[i] > t[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return out


def _taubin_circle_fit(xs, ys):
    """Taubin (1991) 代数圆拟合（近似无偏，小弧安全；Kasa 小弧有偏故不用）。

    实现：中心化数据 [Z0, X, Y]（Z0=(|p−μ|²−mean)/(2√mean)）取最小奇异向量；
    Z0 替换后单位范数约束恰为 Taubin 归一化 4α²Zm+D²+E²=1（Chernov 2010）。
    回收式：center=(mx−√Zm·A2/A1, my−√Zm·A3/A1)，R=√Zm/|A1|。
    裁判=合成整圆/30° 短弧精确回收（test_taubin_fit_exact，#118）。
    """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if x.size < 3:
        raise ValueError("圆拟合至少需要 3 点")
    mx, my = float(x.mean()), float(y.mean())
    u, v = x - mx, y - my
    z = u * u + v * v
    zm = float(z.mean())
    if zm <= 0.0:
        raise ValueError("数据点重合，圆拟合退化")
    z0 = (z - zm) / (2.0 * math.sqrt(zm))
    mat = np.column_stack([z0, u, v])
    _, _, vt = np.linalg.svd(mat, full_matrices=False)
    a1, a2, a3 = (float(c) for c in vt[2])
    if a1 == 0.0:
        raise ValueError("圆拟合奇异（共线数据）")
    root_zm = math.sqrt(zm)
    return mx - root_zm * a2 / a1, my - root_zm * a3 / a1, root_zm / abs(a1)


def _q_circle_channel(freq_ghz, s11):
    """Kajfez 反射口径单通道：Γ 圆 → β=1/(2s−1)（直径投影式，旋转不变）+
    3dB 弦 Q_L=f0/(f₂−f₁) + Q_u=Q_L(1+β)。

    代数事实（合成回收钉死，test_q_circle_recovery）：
    * 单极点反射 Γ=(β−1−jQu·x)/(β+1+jQu·x) 轨迹是过 p_far≈−1（冷态）与
      Γ0=(β−1)/(β+1)（谐振尖）的圆；
    * 原点在直径 [p_far,Γ0] 上的投影比例 s=(β+1)/(2β) ⟹ β=1/(2s−1)，
      逐代数可证参考面旋转不变；
    * 过圆心垂直直径的弦与半吸收功率点（1−|Γ|²=(1−|Γ0|²)/2，x=±1/Q_L）
      重合 ⟹ Q_L=f0/(f₂−f₁)、Q_u=Q_L(1+β)。
    """
    f = np.asarray(freq_ghz, dtype=float)
    g = np.asarray(s11, dtype=complex)
    if g.size != f.size or g.size < 16:
        raise ValueError("freq_ghz/s11 须同长且 ≥16 点（圆拟合需要足够弧段）")
    p_cold = 0.5 * (g[0] + g[-1])
    dk = np.abs(g - p_cold)
    i_tip = int(np.argmax(dk))
    # 0.25·max ⟺ |Q_L·x| ≤ 3.87（代数：|Γ−p_cold|=2β/√((β+1)²+Q²x²)），对任意
    # β 一致覆盖 3dB 弦交点（|Q_L·x|=1）约 3.9× 余量；0.5 档在高 Q 时会把
    # 交点切在窗外（实测 Qu=2000 窗仅 7 点）
    lvl = 0.25 * float(dk[i_tip])
    lo = i_tip
    while lo > 0 and dk[lo - 1] >= lvl:
        lo -= 1
    hi = i_tip
    while hi < g.size - 1 and dk[hi + 1] >= lvl:
        hi += 1
    if hi - lo < 7:
        raise ValueError("谐振窗点数不足（扫频须覆盖 ≥±1 线宽）")
    gw, fw = g[lo:hi + 1], f[lo:hi + 1]
    cx, cy, rad = _taubin_circle_fit(gw.real, gw.imag)
    c = complex(cx, cy)
    if not math.isfinite(rad) or rad <= 0:
        raise ValueError("圆拟合半径非正")
    uvec = c - p_cold
    norm = abs(uvec)
    if norm < 1e-12:
        raise ValueError("圆心与冷态点重合，直径方向不可辨")
    uhat = uvec / norm
    g_tip = c + rad * uhat
    p_far = c - rad * uhat
    seg = g_tip - p_far
    s_proj = float(((0 - p_far) * seg.conjugate()).real
                   / (seg * seg.conjugate()).real)
    if s_proj <= 0.5:
        raise ValueError("直径投影退化（数据非单极点反射轨迹）")
    beta = 1.0 / (2.0 * s_proj - 1.0)
    proj = ((gw - c) * uhat.conjugate()).real
    i0 = lo + int(np.argmax(np.abs(gw - p_far)))
    crossings = []
    for k in range(proj.size - 1):
        if proj[k] * proj[k + 1] < 0.0:
            t = proj[k] / (proj[k] - proj[k + 1])
            crossings.append(fw[k] + t * (fw[k + 1] - fw[k]))
    if len(crossings) < 2:
        raise ValueError("3dB 弦交点不足 2 个（窗过窄或数据非圆轨迹）")
    f0_hat = float(f[i0])
    q_loaded = f0_hat / (crossings[-1] - crossings[0])
    q_unloaded = q_loaded * (1.0 + beta)
    return {"ok": True, "beta": round(beta, 9),
            "q_loaded": round(q_loaded, 6),
            "q_unloaded": round(q_unloaded, 6),
            "f0_ghz": round(f0_hat, 9),
            "circle_center": [round(cx, 9), round(cy, 9)],
            "circle_radius": round(rad, 9),
            "window_points": int(hi - lo + 1),
            "coupling_side": ("over" if beta > 1.05 else
                              ("critical" if abs(beta - 1.0) <= 0.05
                               else "under")),
            "method": "kajfez_reflection_circle+taubin_fit"}


def _dp2_pole_map_to_omega(p_phys, w0_rad_s, fbw):
    """物理带通极点 s_p → 归一化低通极点 Ω_p=(s²+ω0²)/(j·s·ω0·fbw)（精确
    映射；test 钉：与 _cm_response_raw 内核 det Y=0 的精确极点一致）。"""
    return (p_phys * p_phys + w0_rad_s * w0_rad_s) \
        / (1j * p_phys * w0_rad_s * fbw)


def _dp2_vf_fit(ntwk, n_poles_cmplx):
    """skrf VectorFitting 单次拟合；收敛警告收编为返回值（不污染 stdout）。"""
    import warnings as _warnings

    from skrf.vectorFitting import VectorFitting

    from rfauto.core.macromodel import _poles_residues

    with _warnings.catch_warnings(record=True) as wlist:
        _warnings.simplefilter("always")
        vf = VectorFitting(ntwk)
        vf.vector_fit(n_poles_real=0, n_poles_cmplx=int(n_poles_cmplx),
                      enforce_dc=False)
    converged = not any("did not converge" in str(w.message)
                        for w in wlist if issubclass(w.category, Warning))
    n_ports = ntwk.s.shape[1]
    rms = max(vf.get_rms_error(i, j)
              for i in range(n_ports) for j in range(n_ports))
    summary = _poles_residues(vf, n_ports)
    return vf, float(rms), bool(converged), summary


def _dp2_vf_rational_polys(vf, n_ports):
    """VF 留数/极点 → 分子/分母多项式：S11 idx0、S21 idx=n_ports（行主序）。"""
    poles = np.asarray(vf.poles, dtype=complex)
    residues = np.asarray(vf.residues, dtype=complex)
    const = np.asarray(vf.constant_coeff, dtype=complex).reshape(-1)
    denom = np.array([1.0 + 0j])
    for p in poles:
        denom = np.convolve(denom, np.array([1.0, -p], dtype=complex))
    numer = {}
    for idx in (0, n_ports):
        num = np.array([complex(const[idx]) * c for c in denom])
        for k, _ in enumerate(poles):
            minor = np.array([1.0 + 0j])
            for j, pj in enumerate(poles):
                if j != k:
                    minor = np.convolve(minor, np.array([1.0, -pj],
                                                        dtype=complex))
            num = np.polyadd(num, residues[idx][k] * minor)
        numer[idx] = num
    return numer[0], numer[n_ports], denom


def _dp2_band_pairs(vf, f_lo_hz, f_hi_hz):
    """带内复极点对表（Im p>0 记一对）：f_ghz、Q_pole、损耗比、Ω 域映射。"""
    w0 = 2.0 * math.pi * math.sqrt(f_lo_hz * f_hi_hz)
    fbw_guess = (f_hi_hz - f_lo_hz) / math.sqrt(f_lo_hz * f_hi_hz)
    pairs = []
    for p in vf.poles:
        if p.imag <= 0.0:
            continue
        fp = p.imag / 2.0 / math.pi
        if not (f_lo_hz * 0.85 <= fp <= f_hi_hz * 1.15):
            continue
        q_pole = abs(p.imag) / (2.0 * abs(p.real)) if p.real != 0 else None
        om_p = _dp2_pole_map_to_omega(p, w0, fbw_guess)
        pairs.append({
            "f_ghz": round(fp / 1e9, 9),
            "q_pole": (round(q_pole, 6) if q_pole else None),
            "loss_ratio": round(abs(p.real) / abs(p.imag), 9),
            "omega_pole": [round(om_p.real, 9), round(om_p.imag, 9)]})
    pairs.sort(key=lambda d: d["f_ghz"])
    return pairs


@register_calculator(
    "q_factor_vf",
    "单腔 Q 双通道之 A（VF 极点法）：反射 S11 → skrf VectorFitting 复极点对 → "
    "Q_L=|Im p|/(2|Re p|)、f0=|Im p|/2π；给 q_e 时 1/Q_u=1/Q_L−Σ1/Q_e,k。"
    "|Re p|/|Im p|>0.05 → loss_degraded 如实标记（判据 criteria.md §2）",
    (("freq_ghz", "array GHz 频率轴（覆盖谐振 ±≥5 线宽）"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("f0_hint_ghz", "float GHz 谐振频率提示（缺省=取带内最强极点对）"),
     ("q_e", "array 外部 Q（列表或标量；缺省=None 只报 Q_L）"),
     ("n_poles", "int VF 复极点对数（默认 1）")),
    required=("freq_ghz", "s11"),
)
def q_factor_vf(freq_ghz: list, s11: list, f0_hint_ghz: float | None = None,
                q_e: list | None = None, n_poles: int = 1) -> dict:
    import skrf as skrf

    f = np.asarray(freq_ghz, dtype=float)
    g = _cm_as_complex(s11, "s11", f.size)
    if f.ndim != 1 or f.size < 16 or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    if np.max(np.abs(g)) > 1.0 + 1e-2:
        raise ValueError("数据非无源：|S11| > 1.01（含测量噪声容限，粗守卫）")
    n_poles = int(n_poles)
    if not 1 <= n_poles <= 4:
        raise ValueError("n_poles 须在 1..4")
    ntwk = skrf.Network(frequency=f * 1e9, s=g.reshape(-1, 1, 1), z0=50.0)
    vf, rms, converged, summary = _dp2_vf_fit(ntwk, n_poles)
    pairs = _dp2_band_pairs(vf, float(f[0]) * 1e9, float(f[-1]) * 1e9)
    if not pairs:
        raise ValueError("VF 未在给定频带内找到复极点对")
    pick = (min(pairs, key=lambda d: abs(d["f_ghz"] - float(f0_hint_ghz)))
            if f0_hint_ghz is not None else pairs[0])
    q_loaded = pick["q_pole"]
    loss_degraded = pick["loss_ratio"] > 0.05
    q_unloaded = None
    if q_e is not None:
        qe_list = [float(v) for v in (q_e if isinstance(q_e, (list, tuple))
                                      else [q_e])]
        if any(v <= 0 for v in qe_list):
            raise ValueError("q_e 须为正数")
        inv = 1.0 / q_loaded - sum(1.0 / v for v in qe_list)
        q_unloaded = (round(1.0 / inv, 6) if inv > 0 else None)
    return {"ok": bool(rms <= 1e-2 and converged),
            "q_loaded": q_loaded,
            "q_unloaded": q_unloaded,
            "f0_ghz": pick["f_ghz"],
            "fit_rms": round(rms, 12),
            "vf_converged": converged,
            "loss_degraded": bool(loss_degraded),
            "loss_ratio": pick["loss_ratio"],
            "pole_pairs": pairs,
            "vf_poles_rad_s": summary["poles_rad_s"],
            "vf_poles_summary": summary["poles_summary"],
            "method": "skrf_vector_fitting_pole",
            "note": "Q_L=|Im p|/(2|Re p|)（复频率极点口径）；q_e 未给时 "
                    "q_unloaded=None（1/Q_u=1/Q_L−Σ1/Q_e,k 需外部 Q）"}


@register_calculator(
    "q_factor_circle",
    "单腔 Q 双通道之 B（Kajfez 圆拟合）：S11 → Taubin 代数圆拟合（Kasa 小弧"
    "有偏不用）→ β=1/(2s−1)（直径投影式，参考面旋转不变）→ 3dB 弦 "
    "Q_L=f0/(f₂−f₁) → Q_u=Q_L(1+β)。与 q_factor_vf 互证 ≤10%，超阈 "
    "UNDECIDABLE（#122）",
    (("freq_ghz", "array GHz 频率轴（覆盖谐振 ±≥1 线宽）"),
     ("s11", "array 复 S11（[re,im] 对或复数）")),
    required=("freq_ghz", "s11"),
)
def q_factor_circle(freq_ghz: list, s11: list) -> dict:
    f = np.asarray(freq_ghz, dtype=float)
    g = _cm_as_complex(s11, "s11", f.size)
    if np.max(np.abs(g)) > 1.0 + 1e-2:
        raise ValueError("数据非无源：|S11| > 1.01（含测量噪声容限，粗守卫）")
    return _q_circle_channel(f, g)


@register_calculator(
    "cat_critique",
    "Dishal 顺序调谐确定性 critique（与 autotune_service.critique_point 同型 "
    "issues+typed fixes，无 LLM，数值只在内核 #7）：τ(f) 峰数=指纹（1 峰=单腔"
    "接入步→Qe；2 峰=相邻耦合步→k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)）；峰位"
    "偏=失谐方向。C 系数钉死（合成回收裁决，模块头注释）：S21 透射泄漏 C=2、"
    "S11 反射全通 C=4。k 计算注入点：df6 P1 k_split_pair 注册后由服务层经"
    " k_split_fn 消费，计算器面保持内部精确式（显式拒绝外部回调串入）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s21", "array 复 S21（透射口径，与 s11 恰给其一）"),
     ("s11", "array 复 S11（反射口径，C=4）"),
     ("f0_ghz", "float GHz 目标中心频率"),
     ("fbw", "float 相对带宽（0<fbw≤1）"),
     ("target_matrix", "array (N+2)×(N+2) 目标耦合矩阵"),
     ("current_params", "object 当前可调参数名→值（缺省=只报物理偏差）"),
     ("bounds", "object 参数名→[下,上]（缺省=不限）"),
     ("max_step_pct", "float 单步限幅（默认 0.2）"),
     ("tol", "float 相对容差（默认 0.1）")),
    required=("freq_ghz", "f0_ghz", "fbw", "target_matrix"),
)
def cat_critique(freq_ghz: list, s21: list | None = None,
                 s11: list | None = None, f0_ghz: float = 0.0,
                 fbw: float = 0.0, target_matrix: list | None = None,
                 current_params: dict | None = None,
                 bounds: dict | None = None, max_step_pct: float = 0.2,
                 tol: float = 0.1) -> dict:
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    if f0_ghz <= 0:
        raise ValueError("f0_ghz 须为正")
    if max_step_pct <= 0 or tol <= 0:
        raise ValueError("max_step_pct/tol 须为正")
    if (s21 is None) == (s11 is None):
        raise ValueError("s21 与 s11 恰给其一")
    if target_matrix is None:
        raise ValueError("target_matrix 须为 (N+2)×(N+2) 列表")
    channel = "transmission" if s21 is not None else "reflection"
    c_coef = _CAT_C_TRANSMISSION if channel == "transmission" \
        else _CAT_C_REFLECTION
    data = s21 if s21 is not None else s11
    name = "s21" if channel == "transmission" else "s11"
    f = np.asarray(freq_ghz, dtype=float)
    if f.ndim != 1 or f.size < 16 or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    s = _cm_as_complex(data, name, f.size)
    m_tgt = _cm_from_list(target_matrix)
    n2 = m_tgt.shape[0]
    if n2 < 3:
        raise ValueError("target_matrix 须为 (N+2)×(N+2)（N≥1）")
    m_arr = _cm_reduce_arrow(m_tgt)
    qe1_target = 1.0 / (fbw * abs(m_arr[0, 1]) ** 2)
    k12_target = abs(m_arr[1, 2]) * fbw if n2 >= 4 else None

    tau = _dp2_group_delay_phys(f, s)
    tau_peaks = _dp2_prominent_peaks(np.abs(tau))
    # Dishal 纹波指纹用 |S| 峰（透射=|S21| 纹波数=已接腔数；k12 步的双峰是
    # |S21| 纹波峰而非 τ 峰——同步 2 腔的 τ 恒单峰，实测 τ 双峰判 0/3 中）；
    # 双峰可辨要求探针耦合 ≪ k12（弱抽头口径，强加载时双峰合并=1 峰指纹，
    # 如实按单腔步降级——实测 m_port=0.15/m12=0.2 回收偏差 0.5%）。
    # 阶段分派：|S|≥2 峰 → k12 步；否则（含腔 2 失谐脱离致 |S21| 无带内峰的
    # 弱抽头形态）τ 峰存在即单腔步（Qe）；两者皆无 → no_peak 如实。
    mag_peaks = _dp2_prominent_peaks(np.abs(s))
    k_step = len(mag_peaks) >= 2
    peaks = mag_peaks if k_step else tau_peaks
    w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
    issues: list[dict] = []
    fixes: list[dict] = []
    out: dict = {"ok": True, "channel": channel, "c_coef": c_coef,
                 "n_peaks": len(peaks),
                 "peaks_ghz": [round(float(f[i]), 9) for i in peaks],
                 "tau_peaks_ghz": [round(float(f[i]), 9) for i in tau_peaks],
                 "qe1_target": round(qe1_target, 9),
                 "k12_target": (round(k12_target, 9)
                                if k12_target is not None else None),
                 "fingerprint": {"ripple_count": len(mag_peaks),
                                 "tau_peak_count": len(tau_peaks),
                                 "peak_offset_pct": None},
                 "issues": issues, "fixes": fixes,
                 "method": "dishal_sequential_critique"}

    def _clamp(step: float) -> float:
        return max(-max_step_pct, min(max_step_pct, step))

    def _param_fix(kind: str, op: str, value: float, reason: str) -> None:
        params = current_params or {}
        bounds_d = bounds or {}
        hit = False
        for pname, val in params.items():
            low = pname.lower()
            is_len = any(h in low for h in ("len", "length", "_l_"))
            matched = ((kind == "freq_scale" and is_len)
                       or (kind in ("qe_adjust", "k_adjust")
                           and "gap" in low))
            if not matched:
                continue
            new_v = float(val) * value
            if pname in bounds_d:
                new_v = max(float(bounds_d[pname][0]),
                            min(float(bounds_d[pname][1]), new_v))
            fixes.append({"param": pname, "op": op,
                          "value": round(new_v, 9), "reason": reason,
                          "kind": kind})
            hit = True
        if not hit:
            fixes.append({"param": None, "op": op, "value": round(value, 9),
                          "reason": reason, "kind": kind,
                          "queued": "coord_probe"})

    if not k_step and tau_peaks:
        i_pk = tau_peaks[0]  # Qe 步用 τ 峰（单腔谐振指纹）
        tau_max = float(abs(tau[i_pk]))
        qe_meas = w0 * tau_max / c_coef
        out["qe_measured"] = round(qe_meas, 9)
        offset_pct = round((float(f[i_pk]) - float(f0_ghz))
                           / float(f0_ghz) * 100.0, 6)
        out["fingerprint"]["peak_offset_pct"] = offset_pct
        dev = (qe_meas - qe1_target) / qe1_target
        out["qe_deviation"] = round(dev, 6)
        if abs(dev) > tol:
            issues.append({"kind": "qe_mismatch", "metric": "qe1",
                           "measured": round(qe_meas, 6),
                           "target": round(qe1_target, 6),
                           "deviation": round(dev, 6)})
            # Qe∝1/k²：Qe 偏大=耦合过弱 → 间隙按 √(Qe_tgt/Qe_meas) 缩
            #（k∝e^(−g/g0) 方向；环内坐标探测复核符号与步长）
            gap_scale = _clamp(math.sqrt(qe1_target / qe_meas) - 1.0) + 1.0
            _param_fix("qe_adjust", "scale_coupling_gap", gap_scale,
                       f"Qe1 {qe_meas:.4g} vs 目标 {qe1_target:.4g}"
                       f"（偏 {dev:+.0%}，耦合间隙按 {gap_scale:.3f}× 调整）")
        if abs(offset_pct) > tol * 100.0:
            ratio = float(f[i_pk]) / float(f0_ghz)
            issues.append({"kind": "detune", "metric": "peak_offset",
                           "measured": round(float(f[i_pk]), 9),
                           "target": float(f0_ghz),
                           "deviation": offset_pct})
            _param_fix("freq_scale", "scale", ratio,
                       f"τ 峰 {float(f[i_pk]):.6g}GHz 偏 f0（失谐方向指纹，"
                       f"长度类参数按 {ratio:.4f}× 缩放）")
    elif len(peaks) >= 2:
        f1, f2 = float(f[peaks[0]]), float(f[peaks[1]])
        # k 拆分精确式；注入点注记：df6 P1 注册 k_split_pair 后由服务层注入
        # 回调（消费注册表键），计算器面保持内部精确式（可复现、模型无关）
        k_meas = (f2 * f2 - f1 * f1) / (f2 * f2 + f1 * f1)
        out["k_measured"] = round(k_meas, 9)
        out["split_freqs_ghz"] = [round(f1, 9), round(f2, 9)]
        if k12_target is not None:
            dev = (k_meas - k12_target) / k12_target
            out["k12_deviation"] = round(dev, 6)
            if abs(dev) > tol:
                issues.append({"kind": "k_mismatch", "metric": "k12",
                               "measured": round(k_meas, 9),
                               "target": round(k12_target, 9),
                               "deviation": round(dev, 6)})
                gap_scale = _clamp(k12_target / k_meas - 1.0) + 1.0
                _param_fix("k_adjust", "scale_coupling_gap", gap_scale,
                           f"k12 {k_meas:.4g} vs 目标 {k12_target:.4g}"
                           f"（偏 {dev:+.0%}，腔间间隙按 {gap_scale:.3f}× "
                           "调整）")
    else:
        issues.append({"kind": "no_peak", "metric": "tau_peaks",
                       "measured": 0, "target": 1, "deviation": None})
        out["ok"] = False
        out["ok_reason"] = ("τ(f) 与 |S| 均无显著峰：扫频窗未覆盖谐振或数据"
                            "非谐振响应")
    out["verdict"] = ("PASS" if (out["ok"] and not issues)
                      else ("FAIL" if out["ok"] else "NO_PEAK"))
    return out


@register_calculator(
    "cm_extract_vf",
    "CM 反向提取段一（VF 结构面）：复 S11/S21 → skrf VectorFitting 定阶扫描"
    "（rms 表）→ 带内复极点对↔谐振器数 N + 逐对 Q_pole/损耗比 + S21 分子根→"
    "TZ 数 → (N,n_fz) 结构 → Ω 域固定结构重拟合 → Cameron Y 留数（既有 "
    "_cm_transversal_exact 复用，与 Cauchy 路线互证）→ folded/arrow 拓扑初值。"
    "既有 coupling_matrix_extract 键保留为独立裁判不删改（#315）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("s21", "array 复 S21（[re,im] 对或复数）"),
     ("order", "int 阶数（缺省=由 VF 带内极点对数判）"),
     ("n_fz", "int 有限 TZ 数（缺省=由 S21 分子根判）"),
     ("f0_ghz", "float GHz 中心频率提示（缺省=纹波带边估计）"),
     ("fbw", "float 相对带宽提示（缺省=带边估计）"),
     ("topology", "str folded（缺省）| arrow 拓扑初值"),
     ("k_max", "int VF 定阶扫描上限（默认 6）"),
     ("phase_ref", "str unknown（缺省，|S| 裁判）| known（复值逐点裁判）")),
    required=("freq_ghz", "s11", "s21"),
)
def cm_extract_vf(freq_ghz: list, s11: list, s21: list,
                  order: int | None = None, n_fz: int | None = None,
                  f0_ghz: float | None = None, fbw: float | None = None,
                  topology: str = "folded", k_max: int = 6,
                  phase_ref: str = "unknown") -> dict:
    import skrf as skrf

    if topology not in ("folded", "arrow"):
        raise ValueError("topology 须为 folded|arrow")
    if phase_ref not in ("unknown", "known"):
        raise ValueError("phase_ref 须为 unknown|known")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 16:
        raise ValueError("freq_ghz 须为一维且 ≥16 点")
    if np.any(freq <= 0) or np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")
    k_max = int(k_max)
    if not 1 <= k_max <= 10:
        raise ValueError("k_max 须在 1..10")
    if order is not None and int(order) < 1:
        raise ValueError("阶数必须 ≥1")

    s11_db = 20.0 * np.log10(np.maximum(np.abs(s11c), 1e-300))
    edges = _cm_band_edges(freq, s11_db)
    f0_use = float(f0_ghz) if f0_ghz else (
        math.sqrt(float(edges[0]) * float(edges[1])) if edges else
        math.sqrt(float(freq[0]) * float(freq[-1])))
    fbw_use = float(fbw) if fbw else (
        min(max((float(edges[1]) - float(edges[0])) / f0_use, 1e-3), 1.0)
        if edges else 0.1)
    if not 0 < fbw_use <= 1:
        raise ValueError("fbw 须在 (0,1]")

    s_cube = np.zeros((freq.size, 2, 2), dtype=complex)
    s_cube[:, 0, 0] = s_cube[:, 1, 1] = s11c
    s_cube[:, 1, 0] = s_cube[:, 0, 1] = s21c
    ntwk = skrf.Network(frequency=freq * 1e9, s=s_cube, z0=50.0)

    scan = []
    best = None
    for k in range(1, k_max + 1):
        vf, rms, conv, summary = _dp2_vf_fit(ntwk, k)
        pairs = _dp2_band_pairs(vf, float(freq[0]) * 1e9,
                                float(freq[-1]) * 1e9)
        scan.append({"n_poles_cmplx": k, "rms": round(rms, 12),
                     "band_pairs": len(pairs), "converged": conv})
        if best is None or rms < best[1]:
            best = (vf, rms, pairs, summary)
    vf, fit_rms_vf, pairs, summary = best

    # 阶数判定：显式 order 优先；缺省走 Ω 域 Cauchy 定阶扫描（每阶扫 nz 取
    # 最优，容差=绝对底噪 1e−6+相对最优 100×，与既有 choose 口径一致）。
    # 不用 VF 带内极点对数：过拟合 K 的 junk 极点可落带内使计数虚高
    # （实测 N=3 判 5）。
    om = _dp2_omega_norm(freq, f0_use, fbw_use)
    if order is not None:
        n_res = int(order)
    else:
        n_cap = min(max(2, len(pairs) + 1), 8)
        n_rms = {}
        for n_try in range(1, n_cap + 1):
            best_n = math.inf
            for nz_try in range(0, n_try + 1):
                try:
                    _fs, _ps, _es = _cm_rational_fit(om, s11c, s21c, n_try,
                                                     nz_try)
                    best_n = min(best_n, _cm_fit_rms(_fs, _ps, _es, om,
                                                     s11c, s21c))
                except (ValueError, np.linalg.LinAlgError):
                    continue
            if math.isfinite(best_n):
                n_rms[n_try] = best_n
        if not n_rms:
            raise ValueError("Cauchy 定阶扫描失败：数据无法用有理函数描述")
        best_r = min(n_rms.values())
        n_tol = max(100.0 * best_r, 1e-6)
        n_res = next((n for n in sorted(n_rms) if n_rms[n] <= n_tol),
                     max(n_rms, key=lambda n: n_rms[n]))
    if n_res < 1:
        raise ValueError("VF 带内极点对为 0：数据无带内谐振")

    # TZ 诊断（VF 面按 spec：S21 分子根 → Ω 域 |Im|≈0 且 |Re|>1，±对折叠；
    # 过拟合 K 会带伪根，故实际 nz 由下方 Ω 域扫描按既有 extract 容差口径定）
    w0 = 2.0 * math.pi * f0_use * 1e9
    _, num21, _ = _dp2_vf_rational_polys(vf, 2)
    vf_tz_norm = []
    for z in np.roots(num21):
        om_z = _dp2_pole_map_to_omega(z, w0, fbw_use)
        if abs(om_z.imag) <= 0.05 * max(1.0, abs(om_z)) and abs(om_z.real) > 1:
            vf_tz_norm.append(round(abs(float(om_z.real)), 6))
    vf_tz_norm = sorted(set(vf_tz_norm), key=lambda v: -v)

    # Ω 域固定结构重拟合 + nz 扫描（容差=绝对底噪 1e−6 + 相对最优 20×，与
    # coupling_matrix_extract 同口径）→ Cameron Y 留数（既有内核复用，#315）
    nz_list = ([min(int(n_fz), n_res)] if n_fz is not None
               else list(range(0, min(n_res, 4) + 1)))
    fits = {}
    for nz in nz_list:
        try:
            f_s, p_s, e_s = _cm_rational_fit(om, s11c, s21c, n_res, nz)
            r = _cm_fit_rms(f_s, p_s, e_s, om, s11c, s21c)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if np.isfinite(r):
            fits[nz] = (r, f_s, p_s, e_s)
    if not fits:
        raise ValueError("Ω 域结构化重拟合失败：nz 扫描无有效拟合")
    if n_fz is not None:
        nz_use = min(int(n_fz), n_res)
        if nz_use not in fits:
            raise ValueError("给定 n_fz 的 Ω 域重拟合失败")
    else:
        min_r = min(v[0] for v in fits.values())
        tol_nz = max(20.0 * min_r, 1e-6)
        nz_use = min(k for k, v in fits.items() if v[0] <= tol_nz)
    fit_rms, f_s, p_s, e_s = fits[nz_use]
    # TZ 位置（Ω 域 |Ω| 幅值表，±对逐根列出——与既有键 n_finite_tz=
    # P 次数、transmission_zeros_norm 口径一致，一对=两根）
    tz_mag = []
    for z in np.roots(np.asarray(p_s, dtype=complex)):
        if abs(z.real) <= 0.05 * max(1.0, abs(z)) and nz_use > 0:
            tz_mag.append(round(abs(float(z.imag)), 6))
    tz_norm = sorted(tz_mag)
    try:
        built = _cm_extract_from_fit(n_res, f_s, p_s, e_s, om, s11c, s21c,
                                     phase_ref=phase_ref)
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise ValueError(f"Ω 域结构化重拟合失败：{exc}") from None
    if built is None:
        raise ValueError("Y 留数重建失败：拟合结构不满足横向矩阵口径")
    report, m = built
    if topology == "folded":
        m_topo, bad = _cm_reduce_folded(m)
        topo_extra = {"cross_family": _cm_folded_family(m_topo),
                      "pattern_residual": round(max(
                          (v for _, _, v in bad), default=0.0), 12)}
    else:
        m_topo = _cm_reduce_arrow(m)
        topo_extra = {}
    resp_consistent = report["mag_max_err"] <= max(1e3 * fit_rms, 1e-4)
    ok = bool(fit_rms <= 1e-2 and resp_consistent
              and report["mag_max_err"] <= 5e-2)
    return {"ok": ok,
            "order": n_res, "n_fz": nz_use,
            "f0_ghz": round(f0_use, 9), "fbw": round(fbw_use, 9),
            "vf_scan": scan,
            "vf_fit_rms": round(fit_rms_vf, 12),
            "vf_pole_pairs": pairs,
            "vf_poles_rad_s": summary["poles_rad_s"],
            "vf_poles_summary": summary["poles_summary"],
            "loss_degraded": bool(any(p["loss_ratio"] > 0.05
                                      for p in pairs)),
            "transmission_zeros_norm": tz_norm,
            "vf_tz_norm_diagnostic": vf_tz_norm,
            "fit_rms": round(fit_rms, 12),
            "response_max_err": round(report["mag_max_err"], 12),
            "coefficient_path": report["path"],
            "coupling_matrix": _cm_to_list(m_topo),
            "matrix_transversal": _cm_to_list(m),
            "matrix_shape": [n_res + 2, n_res + 2],
            "topology": topology,
            "initial_for": "cm_refine_lm",
            **topo_extra,
            "note": "矩阵元素 [re,im] 对；段一产出 (N,n_fz) 结构+拓扑初值，"
                    "精化走 cm_refine_lm；与 Cauchy 反提键互证（#315）"}


def _dp2_support_set(m0, topology, tol=1e-6):
    """拓扑掩码 S：folded=次对角+初值所属单一交叉族（anti/shifted 按
    _cm_folded_family 判，mixed 才取并族）；arrow=主线三对角。
    单族约束防支撑过参数化下的响应等价漂移（同响应不同矩阵，实测
    max_rel_err 3.0 而 rms=0 的非唯一解）。对角：谐振器 m_kk（k=1..N）恒进
    θ（失谐/损耗），源/载对角=外部导纳不进。返回按 (i,j) 字典序支撑集。"""
    n2 = m0.shape[0]
    scale = max(float(np.max(np.abs(m0))), 1e-12)
    mainline = {(i, i + 1) for i in range(n2 - 1)}
    if topology == "folded":
        # 族判定用相对容差（5%·max）：噪声下提取矩阵的应零交叉位残留 ~噪声
        # 电平，1e-9 绝对容差会把单族误判 mixed → 并族过参数化 → 响应等价漂移
        fam = _cm_folded_family(m0, tol=0.05 * scale)
        if fam == "anti":
            keepers = _cm_folded_keepers(n2)
        elif fam == "shifted":
            keepers = _cm_folded_keepers_shifted(n2)
        elif fam == "none":
            keepers = mainline
        else:  # mixed：双族并存如实并族（稀疏性由幅值门限保证）
            keepers = _cm_folded_keepers(n2) | _cm_folded_keepers_shifted(n2)
    elif topology == "arrow":
        # 经典 arrow = 主线三对角 + 载端星形（_cm_reduce_arrow 产形：源行清到
        # (0,1)、载星 (i,L) 保留，TZ≠0 时 (2,L) 等非零，实测 N=4 tz1）
        keepers = mainline | {(i, n2 - 1) for i in range(1, n2 - 1)}
    else:
        raise ValueError("topology 须为 folded|arrow")
    sup = []
    for i in range(n2):
        for j in range(i, n2):
            if i == j:
                if 0 < i < n2 - 1:
                    sup.append((i, i))  # 谐振器对角恒进 θ
                continue
            if (i, j) in keepers and abs(m0[i, j]) > tol * scale:
                sup.append((i, j))
    return sup


def _dp2_theta_pack(m0, support, loss, start_mode: int) -> np.ndarray:
    """初值 θ 向量（start_mode: 0=原值，1/2/3=±20%/±10% 确定性扰动）。
    start=0 时逐位等于初值矩阵（含无损对角 d=0），保证精确初值零残差。"""
    pert = (0.0, 0.2, -0.2, -0.1)[start_mode % 4]
    x0: list[float] = []
    for (i, j) in support:
        if i == j:
            x0.append(m0[i, j].real * (1.0 + pert))
            if loss:
                x0.append(abs(m0[i, j].imag) * (1.0 + pert))
        else:
            x0.append(m0[i, j].real * (1.0 + pert))
            x0.append(m0[i, j].imag * (1.0 + pert))
    return np.array(x0, dtype=float)


def _dp2_cm_model(theta, m0, support, loss):
    """θ → ((N+2) 复矩阵, qe0, qel)：支撑集外恒 0；对角=失谐(re)+损耗(im)，
    loss=False 时损耗固定为初值虚部（cm_refine_lm.unpack 同构，测试共用）。"""
    m = np.zeros_like(m0)
    k = 0
    for (i, j) in support:
        if i == j:
            d_im = theta[k + 1] if loss else float(m0[i, j].imag)
            m[i, j] = theta[k] + 1j * d_im
            k += 2 if loss else 1
        else:
            m[i, j] = m[j, i] = theta[k] + 1j * theta[k + 1]
            k += 2
    return m, 1.0, 1.0


@register_calculator(
    "cm_refine_lm",
    "CM 反向提取段二（LM 固定拓扑反演）：给定初值矩阵+拓扑掩码，θ=支撑集非零"
    "元+对角失谐/损耗 d_k≥0（+可选 qe），残差 r=Ŵ[S_model−S_meas] 实虚堆叠"
    "（S_model=向量化 _cm_response_raw 口径，逐位一致有钉），scipy trf 箱约束"
    "最小二乘（|m_ij|≤2max|初值|、d_k≥0）；同伦 S_λ=(1−λ)S_ideal+λS_meas 共 "
    "8 步热启动（残差劣化 >50% 半步回退）+ ±20%×4 确定性多起点；收敛双门="
    "末段 rms≤1e-2 且 max|ΔS|≤0.05，不过 ok=False 如实",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("s21", "array 复 S21（[re,im] 对或复数）"),
     ("matrix", "array (N+2)×(N+2) 初值矩阵（cm_extract_vf 产出）"),
     ("f0_ghz", "float GHz 中心频率"),
     ("fbw", "float 相对带宽（0<fbw≤1）"),
     ("topology", "str folded（缺省）| arrow 掩码"),
     ("loss", "bool true=对角损耗 d_k 进 θ（缺省 true）"),
     ("refine_qe", "bool true=归一化外部导纳进 θ（缺省 false）"),
     ("external_q", "array [q_in,q_out] 归一化外部导纳初值（缺省 [1,1]）"),
     ("transmission_zeros_norm", "array Ω 域 TZ 位置（缺省=只做带内 ×3 加权）"),
     ("homotopy_steps", "int 同伦步数（默认 8）"),
     ("n_starts", "int 多起点数（默认 4，1..8）")),
    required=("freq_ghz", "s11", "s21", "matrix", "f0_ghz", "fbw"),
)
def cm_refine_lm(freq_ghz: list, s11: list, s21: list, matrix: list,
                 f0_ghz: float, fbw: float, topology: str = "folded",
                 loss: bool = True, refine_qe: bool = False,
                 external_q: list | None = None,
                 transmission_zeros_norm: list | None = None,
                 homotopy_steps: int = 8, n_starts: int = 4) -> dict:
    from scipy.optimize import least_squares

    if topology not in ("folded", "arrow"):
        raise ValueError("topology 须为 folded|arrow")
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    if f0_ghz <= 0:
        raise ValueError("f0_ghz 须为正")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 16 or np.any(freq <= 0) \
            or np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")
    m0 = _cm_from_list(matrix)
    n2 = m0.shape[0]
    if n2 < 3:
        raise ValueError("matrix 须为 (N+2)×(N+2)")
    qe_init = [1.0, 1.0] if external_q is None else \
        [float(v) for v in external_q]
    if len(qe_init) != 2 or qe_init[0] <= 0 or qe_init[1] <= 0:
        raise ValueError("external_q 须为正的 [q_in, q_out]")
    homotopy_steps = max(2, int(homotopy_steps))
    n_starts = max(1, min(8, int(n_starts)))

    support = _dp2_support_set(m0, topology)
    n_theta = sum(2 if (i != j) else (2 if loss else 1)
                  for (i, j) in support) + (2 if refine_qe else 0)
    if n_theta > freq.size:
        raise ValueError("未知量多于频点：增密频点或收窄支撑集")
    om = _dp2_omega_norm(freq, f0_ghz, fbw)
    s11_i, s21_i = _dp2_response_batch(m0, qe_init[0], qe_init[1], om)
    # S21 参考面相位 ±对齐（folded mainline_positive 归一可把载端翻 −1：
    # S11 严格不变、S21 相位对输入可能翻 180°，|S| 门不可见、复数残差致命）。
    # 按复残差范数取小者，确定性；等价于允许 DMD 相似变换的 d_L=±1 自由度。
    s21_sign = 1.0
    if (np.linalg.norm(s21_i + s21c) < np.linalg.norm(s21_i - s21c)):
        s21_sign = -1.0
    tgt = np.concatenate([s11c, s21_sign * s21c])
    s_ideal = np.concatenate([s11_i, s21_i])

    # Ŵ：带内（|Ω|≤1.05）+ TZ 邻域 ×3，其余 ×1（spec 2a）
    weight = np.ones(2 * om.size)
    hot = np.abs(om) <= 1.05
    if transmission_zeros_norm:
        for z in transmission_zeros_norm:
            hot |= np.abs(om - float(z)) <= 0.1 * max(1.0, abs(float(z)))
    nf = om.size
    weight[:nf][hot] = 3.0
    weight[nf:][hot] = 3.0

    def unpack(theta):
        m = np.zeros_like(m0)
        q0, ql = qe_init
        k = 0
        for (i, j) in support:
            if i == j:
                d_im = theta[k + 1] if loss else float(m0[i, j].imag)
                m[i, j] = theta[k] + 1j * d_im
                k += 2 if loss else 1
            else:
                m[i, j] = m[j, i] = theta[k] + 1j * theta[k + 1]
                k += 2
        if refine_qe:
            q0, ql = float(theta[k]), float(theta[k + 1])
        return m, q0, ql

    def resid(theta, lam: float) -> np.ndarray:
        m, q0, ql = unpack(theta)
        s11m, s21m = _dp2_response_batch(m, q0, ql, om)
        model = np.concatenate([s11m, s21m])
        r = weight * ((1.0 - lam) * s_ideal + lam * tgt - model)
        return np.concatenate([r.real, r.imag])

    def theta_bounds():
        lo_b = np.full(n_theta, -np.inf)
        hi_b = np.full(n_theta, np.inf)
        k = 0
        for (i, j) in support:
            if i == j:
                cap = 2.0 * max(abs(m0[i, j].real), 0.5)
                lo_b[k], hi_b[k] = -cap, cap
                k += 1
                if loss:
                    hi_b[k] = 2.0 * max(abs(m0[i, j].imag), 0.1)
                    k += 1
            else:
                cap = 2.0 * max(abs(m0[i, j]), 1e-3)
                lo_b[k], hi_b[k] = -cap, cap
                lo_b[k + 1], hi_b[k + 1] = -cap, cap
                k += 2
        if refine_qe:
            lo_b[k], hi_b[k] = 0.2 * qe_init[0], 5.0 * qe_init[0]
            lo_b[k + 1], hi_b[k + 1] = 0.2 * qe_init[1], 5.0 * qe_init[1]
        return lo_b, hi_b

    lo_b, hi_b = theta_bounds()
    best = None
    for start in range(n_starts):
        x = _dp2_theta_pack(m0, support, loss, start)
        if refine_qe:
            x = np.concatenate([x, [qe_init[0], qe_init[1]]])
        lam = 0.0
        rms_prev = float(np.sqrt(np.mean(resid(x, 0.0) ** 2)))
        lam_final = 0.0
        for step in range(1, homotopy_steps + 1):
            lam_try = step / homotopy_steps
            stepped = False
            for lam_try2 in (lam_try, lam + 0.5 * (lam_try - lam),
                             lam + 0.25 * (lam_try - lam)):
                sol = least_squares(resid, x, args=(lam_try2,), method="trf",
                                    bounds=(lo_b, hi_b), xtol=1e-12,
                                    ftol=1e-12, max_nfev=1200)
                rms_try = float(np.sqrt(np.mean(sol.fun ** 2)))
                if rms_try <= max(1.5 * rms_prev, 1e-12):
                    x, lam, rms_prev = sol.x, lam_try2, rms_try
                    stepped = True
                    break
            if not stepped:
                break  # 同伦卡住：保留已收敛段（local_min 由末门如实判）
            lam_final = lam
        m_hat, q0h, qlh = unpack(x)
        s11m, s21m = _dp2_response_batch(m_hat, q0h, qlh, om)
        err = np.concatenate([weight[:nf] * (s11m - s11c),
                              weight[nf:] * (s21m - s21_sign * s21c)])
        rms_data = float(np.sqrt(np.mean(np.abs(err) ** 2)))
        max_dev = float(max(np.max(np.abs(s11m - s11c)),
                            np.max(np.abs(s21m - s21_sign * s21c))))
        score = (rms_data, max_dev)
        if best is None or score < best[0]:
            best = (score, m_hat.copy(), rms_data, max_dev, start, lam_final)
    _, m_hat, rms_data, max_dev, start_used, lam_final = best
    ok = bool(rms_data <= 1e-2 and max_dev <= 0.05)
    homotopy_complete = lam_final >= 1.0 - 1e-9
    return {"ok": ok,
            "coupling_matrix": _cm_to_list(m_hat),
            "matrix_shape": [n2, n2],
            "topology": topology,
            "support_size": len(support),
            "s21_phase_flipped": bool(s21_sign < 0),
            "fit_rms": round(rms_data, 12),
            "response_max_dev": round(max_dev, 12),
            "homotopy_lambda_final": round(lam_final, 6),
            "homotopy_complete": bool(homotopy_complete),
            "n_starts": n_starts,
            "start_used": int(start_used),
            "external_q": [round(qe_init[0], 9), round(qe_init[1], 9)],
            "ok_reason": ("converged" if ok else
                          f"收敛双门未过（rms={rms_data:.3e}, "
                          f"max|ΔS|={max_dev:.3e}）"
                          + ("" if homotopy_complete
                             else "；同伦未走满（局部极小嫌疑 local_min）")),
            "note": "θ=支撑集非零元+对角失谐/损耗（d_k≥0 箱约束）"
                    + ("+qe" if refine_qe else "")
                    + "；S_model=向量化 _cm_response_raw 口径（逐位一致有钉）"}


# ─── Klopfenstein 渐变段（DP-15 C2，2026-09-24 df6_dp15c2，#231/#304 四表同步）
# 判据预声明与实测锚见 runs/df6_dp15c2/criteria.md §3；阻抗剖面来自
# skrf.taper.Klopfenstein 闭式（ DefinedGammaZ0(gamma=ω/c) 承载），宽度剖面
# 由 MLine 闭式同源求根——全程无抄毫米数（铁律 1c）。

@lru_cache(maxsize=8)
def _mline_z0_table(freq_ghz: float, epsilon_r: float, h_mm: float,
                    tand: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """微带 Z0(w) 对数锚表（48 点，w∈[1e-4·h, 30·h]），PCHIP 粗根底座。

    锚点全部来自 MLine 闭式（Hammerstad-Jensen），缓存纯函数于输入元组。
    """
    h_m = h_mm * 1e-3
    w_tab = np.exp(np.linspace(np.log(1e-4 * h_m), np.log(30.0 * h_m), 48))
    z_tab = [_mline_z0_of_width(float(w), freq_ghz, epsilon_r, h_mm, tand)
             for w in w_tab]
    return tuple(float(w) for w in w_tab), tuple(z_tab)


def _mline_z0_of_width(width_m: float, freq_ghz: float, epsilon_r: float,
                       h_mm: float, tand: float) -> float:
    media = _microstrip_media(width_m * 1e3, freq_ghz, epsilon_r, h_mm, tand)
    return float(np.real(media.z0[0]))


def _microstrip_width_for_z0(z0_target: float, freq_ghz: float,
                             epsilon_r: float, h_mm: float,
                             tand: float) -> tuple[float, float]:
    """MLine 闭式同源求根：w(mm) 使 |Z0_MLine(w)| = z0_target (Ω)。

    两步：对数域 PCHIP 粗根（锚表插值）→ MLine 牛顿精化（函数值精确、
    导数取 PCHIP，收敛到精确根）。返回 (width_mm, z0_achieved)。
    """
    from scipy.interpolate import PchipInterpolator

    w_tab, z_tab = _mline_z0_table(freq_ghz, epsilon_r, h_mm, tand)
    z_max, z_min = z_tab[0], z_tab[-1]  # w↑ → z0↓（单调，PCHIP 保号）
    zt = float(z0_target)
    if not z_min <= zt <= z_max:
        raise ValueError(
            f"目标阻抗 {zt:.2f}Ω 超出该叠层微带可达域 "
            f"[{z_min:.2f}, {z_max:.2f}]Ω（h={h_mm}mm/εr={epsilon_r}）")
    # 表按 w 升序 → z 降序；PCHIP 需要 x 升序，故反转（log-log 线性化）
    lnw_of_lnz = PchipInterpolator(np.log(np.array(z_tab[::-1])),
                                   np.log(np.array(w_tab[::-1])))
    lnw = float(lnw_of_lnz(math.log(zt)))
    lnzt = math.log(zt)
    z_exact = z_min
    for _ in range(6):
        w = math.exp(lnw)
        z_exact = _mline_z0_of_width(w, freq_ghz, epsilon_r, h_mm, tand)
        if abs(z_exact - zt) <= 1e-10 * zt:
            break
        d_lnw_d_lnz = float(lnw_of_lnz.derivative()(math.log(z_exact)))
        if not np.isfinite(d_lnw_d_lnz) or d_lnw_d_lnz == 0.0:
            break  # 导数退化：保守退出，末尾可达性检查会如实拦下
        # 注：lnw(lnz) 方向导数为负（z↑→w↓）是正常单调方向，勿拦
        lnw -= (math.log(z_exact) - lnzt) * d_lnw_d_lnz
    rel = abs(z_exact - zt) / zt
    if rel > 1e-6:
        raise ValueError(
            f"微带求根未收敛：目标 {zt:.4f}Ω， achieved {z_exact:.4f}Ω "
            f"（rel={rel:.2e}）")
    return math.exp(lnw) * 1e3, z_exact


def _klopfenstein_impedance_profile(z1: float, z2: float, rmax: float,
                                    length_m: float,
                                    n_sections: int) -> np.ndarray:
    """skrf.taper.Klopfenstein 阻抗剖面（Ω，length 方向 linspace(0, L)）。

    DefinedGammaZ0 需显式 gamma=ω/c——其缺省 gamma=1j 是常数 β=1 rad/m
    （零电长假网络陷阱，criteria §0.5）。rmax 经 f_kw 传入（构造器 kwarg
    会 TypeError，skrf.taper 实测）。
    """
    import skrf
    from skrf.taper import Klopfenstein

    freq = skrf.Frequency(1.0, 1.0, 1, unit="GHz")
    gamma = 1j * 2.0 * np.pi * freq.f / (C_MM_GHZ * 1e9)
    taper = Klopfenstein(
        med=skrf.media.DefinedGammaZ0,
        med_kw={"frequency": freq, "z0": float(z1), "gamma": gamma},
        f_kw={"rmax": float(rmax)},
        start=float(z1), stop=float(z2),
        length=float(length_m), n_sections=int(n_sections),
    )
    return np.array([float(m.z0[0].real) for m in taper.medias], dtype=float)


@register_calculator(
    "klopfenstein_taper",
    "Klopfenstein 阻抗渐变段综合：z1→z2 渐变（skrf.taper.Klopfenstein 剖面"
    " + 微带 MLine 同源宽度剖面）→ 阻抗/宽度剖面、通带回损估计、βL≥A 通带"
    "条件核验。rmax=通带反射因子 sech(A)，通带纹波 ρ0=Γ0·rmax（Γ0=½|ln(z2"
    "/z1)|，Pozar §5.9 参数化恒等）",
    (("z1_ohm", "float Ω 起端阻抗"),
     ("z2_ohm", "float Ω 末端阻抗（≠z1）"),
     ("length_mm", "float mm 渐变段物理长度"),
     ("epsilon_r", "float - 基板相对介电常数（>1）"),
     ("h_mm", "float mm 基板厚度"),
     ("freq_ghz", "float GHz 设计频率（βL 条件核验点）"),
     ("rmax", "float - 通带反射因子 ρ0/Γ0，(0,1) 开区间（缺省 0.1）"),
     ("n_sections", "int - 剖面离散段数 5..401（缺省 81）"),
     ("tand", "float - 损耗正切（默认 0）")),
    required=("z1_ohm", "z2_ohm", "length_mm", "epsilon_r", "h_mm",
              "freq_ghz"),
)
def klopfenstein_taper(z1_ohm: float, z2_ohm: float, length_mm: float,
                       epsilon_r: float, h_mm: float, freq_ghz: float,
                       rmax: float = 0.1, n_sections: int = 81,
                       tand: float = 0.0) -> dict:
    z1 = float(z1_ohm)
    z2 = float(z2_ohm)
    if not (np.isfinite(z1) and np.isfinite(z2)) or z1 <= 0 or z2 <= 0:
        raise ValueError("z1_ohm/z2_ohm 须为有限正数")
    if z1 == z2:
        raise ValueError(
            "z1==z2：步进反射 Γ0=0，渐变段无意义且通带回损无穷")
    if not (0.0 < float(rmax) < 1.0):
        raise ValueError(f"rmax 须在 (0,1) 开区间，实际 {rmax!r}")
    length = float(length_mm)
    if not np.isfinite(length) or length <= 0:
        raise ValueError(f"length_mm 须为正实数，实际 {length_mm!r}")
    er = float(epsilon_r)
    if not np.isfinite(er) or er <= 1.0:
        raise ValueError(f"epsilon_r 须 >1，实际 {epsilon_r!r}")
    h = float(h_mm)
    if not np.isfinite(h) or h <= 0:
        raise ValueError(f"h_mm 须为正实数，实际 {h_mm!r}")
    f_ghz = float(freq_ghz)
    if not np.isfinite(f_ghz) or f_ghz <= 0:
        raise ValueError(f"freq_ghz 须为正实数，实际 {freq_ghz!r}")
    n_sec = int(n_sections)
    if not 5 <= n_sec <= 401:
        raise ValueError(f"n_sections 须在 5..401，实际 {n_sections!r}")
    td = float(tand)
    if not np.isfinite(td) or td < 0:
        raise ValueError(f"tand 须为非负实数，实际 {tand!r}")

    gamma0 = abs(math.log(z2 / z1)) / 2.0
    A = math.acosh(1.0 / float(rmax))
    rho0 = gamma0 * float(rmax)
    rl_db = -20.0 * math.log10(rho0)

    profile = _klopfenstein_impedance_profile(z1, z2, rmax, length * 1e-3,
                                              n_sec)
    widths_mm = []
    z_rel_err = 0.0
    for zt in profile:
        w_mm, z_ok = _microstrip_width_for_z0(zt, f_ghz, er, h, td)
        widths_mm.append(w_mm)
        z_rel_err = max(z_rel_err, abs(z_ok - zt) / zt)

    diffs = np.diff(profile)
    monotonic = bool(np.all(diffs > 0) or np.all(diffs < 0))
    mid = _microstrip_media(widths_mm[n_sec // 2], f_ghz, er, h, td)
    beta_mid = float(np.real(mid.beta[0]))
    beta_l = beta_mid * (length * 1e-3)
    # 通带下限频率估算（低色散近似 β(f)≈β_mid·f/f_design；逐频色散不做，
    # 剖面是几何量，passband_ok 只在设计点核验）
    f_min_ghz = A * f_ghz / beta_l
    return {
        "z_profile_ohm": [round(v, 6) for v in profile],
        "width_profile_mm": [round(v, 6) for v in widths_mm],
        "x_norm": [round(v, 9) for v in np.linspace(0.0, 1.0, n_sec)],
        "n_sections": n_sec,
        "gamma0_step_reflection": round(gamma0, 9),
        "A": round(A, 9),
        "rmax": round(float(rmax), 9),
        "passband_ripple_rho0": round(rho0, 12),
        "rl_passband_db": round(rl_db, 4),
        "beta_l_design": round(beta_l, 6),
        "passband_ok": bool(beta_l >= A),
        "f_passband_min_ghz_estimate": round(f_min_ghz, 6),
        "monotonic": monotonic,
        "z0_width_check_max_rel": round(z_rel_err, 12),
        "note": "剖面=skrf.taper.Klopfenstein（linspace(0,L) 采样）；宽度="
                "MLine 闭式同源求根；通带纹波 ρ0=Γ0·rmax 仅在 βL≥A 频段"
                "成立（passband_ok/f_passband_min 为设计点核验与低色散估算）",
    }


# ─── k/Qe 标定键（df6 A1 R4 产品化，2026-09-25；签名出处
# runs/df6_a1_r4/calculator_signatures.md；内核与 scripts/df6_a1_r4_runner.py
# 提取面同式移植——test_kqe_registry_keys 跨实现互证钉防漂移）───────────────

_KSPLIT_RULE = {
    # 先于运行写死；prominence 与 HFSS 锚 analyze_driven_s2p 同款
    # （出处 scripts/hairpin_alt_ksplit.py KSPLIT_RULE，hairpin 先例）
    "prominence_db": 0.5,
    "neighborhood_ghz": 0.3,
    "level_floor_db": 15.0,
    "valley_resolved_db": 3.0,
}


def _ksplit_find_mode_pair(freq_hz: Any, s21_db: Any) -> dict:
    """|S21| dB 曲线通带邻域模对查找（KSPLIT_RULE；确定性）。"""
    from scipy.signal import find_peaks

    f = np.asarray(freq_hz, dtype=float)
    db = np.asarray(s21_db, dtype=float)
    if f.shape != db.shape or f.ndim != 1 or f.size < 5:
        raise ValueError("freq_hz/s21_db 须为等长一维且 ≥5 点")
    i_main = int(np.argmax(db))
    f_main = float(f[i_main])
    pk, props = find_peaks(db, prominence=float(_KSPLIT_RULE["prominence_db"]))
    prom_by_idx = {int(i): float(v) for i, v in
                   zip(pk, props["prominences"], strict=True)}
    cand = [int(i) for i in pk
            if abs(float(f[i]) - f_main) <= float(_KSPLIT_RULE["neighborhood_ghz"]) * 1e9
            and float(db[i]) >= float(db[i_main]) - float(_KSPLIT_RULE["level_floor_db"])]
    cands = [{"f_ghz": float(f[i]) / 1e9, "level_db": float(db[i]),
              "prominence_db": prom_by_idx[i]} for i in cand]
    out: dict = {"n_candidates": len(cand), "candidates": cands,
                 "f1_ghz": None, "f2_ghz": None, "level1_db": None,
                 "level2_db": None, "valley_depth_db": None,
                 "quality": "single_peak"}
    if len(cand) < 2:
        return out
    lo, hi = sorted(sorted(cand, key=lambda i: prom_by_idx[i], reverse=True)[:2])
    valley = float(db[lo:hi + 1].min())
    depth = float(min(db[lo], db[hi]) - valley)
    out.update({
        "f1_ghz": float(f[lo]) / 1e9, "f2_ghz": float(f[hi]) / 1e9,
        "level1_db": float(db[lo]), "level2_db": float(db[hi]),
        "valley_depth_db": depth,
        "quality": ("resolved" if depth >= float(_KSPLIT_RULE["valley_resolved_db"])
                    else "shallow_valley")})
    return out


def _ksplit_parabolic_refine(f: Any, y: Any, i: int) -> float:
    """三点抛物线顶点（log|S| 域峰位细化）；边界/退化回退网格点。"""
    f = np.asarray(f, dtype=float)
    y = np.asarray(y, dtype=float)
    if i <= 0 or i >= len(f) - 1:
        return float(f[i])
    d0, d1, d2 = float(y[i - 1]), float(y[i]), float(y[i + 1])
    den = d0 - 2.0 * d1 + d2
    if den == 0.0:
        return float(f[i])
    off = 0.5 * (d0 - d2) / den
    if not -1.0 < off < 1.0:
        return float(f[i])
    return float(f[i] + off * (f[i + 1] - f[i]))


def _ksplit_bias_invert(k_raw: float, raw_grid: Any, true_grid: Any) -> float:
    """合成偏置曲线逆映射（log-log 内插——偏置近幂律；线性域曲率实测
    致 midnode 回收 7.6% 偏差，#118 数值裁判弃线性域内插）。"""
    rg = np.log(np.asarray(raw_grid, dtype=float))
    tg = np.log(np.asarray(true_grid, dtype=float))
    if rg.size < 2 or not bool(np.all(np.diff(rg) > 0)):
        raise ValueError("偏置曲线 raw 栅格须严格递增")
    return float(math.exp(float(np.interp(math.log(k_raw), rg, tg))))


@register_calculator(
    "k_split_pair",
    "双峰模分裂耦合系数（Hong & Lancaster 精确式 k=(f2²−f1²)/(f2²+f1²)，"
    "df6 A1 R4）：|S21| dB 双主峰抛物线细化+KSPLIT_RULE 峰检（prominence "
    "0.5dB HFSS 锚同款+通带邻域守卫）；偏置曲线 log-log 逆映射修正；双峰不"
    "可分如实 None（#122）",
    (("freq_hz", "ndarray Hz 升序扫频栅格"),
     ("s21", "ndarray complex 复 S21（等长）"),
     ("bias_raw_grid", "list|None 偏置曲线 raw k 节点（缺省 None 不修正）"),
     ("bias_true_grid", "list|None 对应 true k 节点")),
    required=("freq_hz", "s21"),
)
def k_split_pair(freq_hz: Any, s21: Any,
                 bias_raw_grid: Any = None,
                 bias_true_grid: Any = None) -> dict:
    """双峰模分裂耦合系数（Hong & Lancaster 精确式；df6 A1 R4）。

    k=(f2²−f1²)/(f2²+f1²)，f1<f2 为 |S21| dB 双主峰（抛物线细化）；峰检
    KSPLIT_RULE（prominence 0.5dB HFSS 锚同款+通带邻域两守卫）。双峰不可分
    → k_raw/k_corr=None（如实不硬提，#122）。k_corr=偏置曲线 log-log 逆映射
    修正值（bias_*_grid 缺省 None 时与 k_raw 相等）；窄带近似只作旁证列。
    """
    f = np.asarray(freq_hz, dtype=float)
    g = _cm_as_complex(s21, "s21", f.size)
    db = 20.0 * np.log10(np.abs(g) + 1e-12)
    pair = _ksplit_find_mode_pair(f, db)
    out: dict = {"pair": pair, "f1_ghz": None, "f2_ghz": None,
                 "k_raw": None, "k_corr": None, "k_narrowband": None,
                 "valley_db": pair.get("valley_depth_db"),
                 "quality": pair.get("quality", "single_peak")}
    if pair["f1_ghz"] is None or pair["f2_ghz"] is None:
        return out
    i1 = int(np.argmin(np.abs(f - pair["f1_ghz"] * 1e9)))
    i2 = int(np.argmin(np.abs(f - pair["f2_ghz"] * 1e9)))
    fr1 = _ksplit_parabolic_refine(f, db, i1)
    fr2 = _ksplit_parabolic_refine(f, db, i2)
    f1, f2 = sorted((fr1, fr2))
    if f1 <= 0.0 or f2 <= f1:
        return out
    k = (f2 * f2 - f1 * f1) / (f2 * f2 + f1 * f1)
    out.update({"f1_ghz": f1 / 1e9, "f2_ghz": f2 / 1e9,
                "k_raw": float(k),
                "k_narrowband": float(2.0 * (f2 - f1) / (f2 + f1))})
    if out["k_raw"] is not None and bias_raw_grid is not None             and bias_true_grid is not None:
        out["k_corr"] = _ksplit_bias_invert(out["k_raw"], bias_raw_grid,
                                            bias_true_grid)
    elif out["k_raw"] is not None:
        out["k_corr"] = out["k_raw"]
    return out


@register_calculator(
    "qe_group_delay",
    "单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径，df6 A1 R4）："
    "τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合；无耗单端口 "
    "τmax=4Qe/ω0 ⇒ 缺省 c=4（合成回收 3.9972；/2 口径否决，DP-2 互证）",
    (("freq_hz", "ndarray Hz 升序扫频栅格"),
     ("s11", "ndarray complex 复 S11（单载反射）"),
     ("c", "float - τ→Qe 常数（缺省 4.0；对称双馈 S21 口径配 1.0）")),
    required=("freq_hz", "s11"),
)
def qe_group_delay(freq_hz: Any, s11: Any, c: float = 4.0) -> dict:
    """单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径；df6 A1 R4）。

    τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合（D 吸收馈线往返
    时延+基线；带缘斜率法被谐振器电抗斜率污染实测 3.2×，禁用）。无耗单端
    口理论 τmax=4Qe/ω0 ⇒ **缺省 c=4**（合成回收实测 3.9972，
    runs/df6_a1_r4/selftest_result.json；"/2"口径否决——DP-2 轨独立互证同
    裁决）；对称双馈 S21 口径 τmax=2Q_L/ω0 配 c=1.0（仅记录）。Qe=A·ω0/c。
    """
    from scipy.optimize import curve_fit

    f = np.asarray(freq_hz, dtype=float)
    s = _cm_as_complex(s11, "s11", f.size)
    ph = np.unwrap(np.angle(s))
    tau = -np.gradient(ph, 2.0 * np.pi * f)
    i = int(np.argmax(tau))
    f0_hz = float(f[i])
    span = f[-1] - f[0]
    far = tau[(f <= f[0] + 0.2 * span) | (f >= f[-1] - 0.2 * span)]
    d0 = float(np.median(far))
    a0 = max(float(tau[i]) - d0, 1e-15)
    p0 = [a0, f0_hz, max(3.0e6, 0.02 * f0_hz), d0]

    def _model(ff, a, fc, w, d):
        return a / (1.0 + ((ff - fc) / w) ** 2) + d

    popt, _ = curve_fit(_model, f, tau, p0=p0, maxfev=20000)
    a_fit, fc_fit, w_fit, d_fit = (float(v) for v in popt)
    # 规范化 (A,w)→(-A,-w) 镜像简并（模型对该变换不变，curve_fit 随机落边）：
    # 一律收窄到 w>0，a_fit 的符号才是物理符号（群时延瓣方向）。
    if w_fit < 0:
        a_fit, w_fit = -a_fit, -w_fit
    if w_fit == 0:
        raise ValueError("Lorentzian 拟合宽度退化（数据无谐振特征）")
    # 符号感知（2026-09-25 df6 A1 真机实证）：实测 S11 谐振群时延瓣可为负
    # （馈线相位旋转约定），Qe 由 |A| 定义、符号如实入 sign 字段不硬凑。
    resid = float(np.max(np.abs(tau - _model(f, *popt))))
    qe = abs(a_fit) * 2.0 * math.pi * fc_fit / float(c)
    if qe <= 0:
        raise ValueError("Qe 非正（拟合退化，数据无可用谐振特征）")
    return {"tau_max_s": float(tau[i]), "a_fit_s": a_fit,
            "f_res_ghz": fc_fit / 1e9, "w_fit_hz": w_fit, "d_fit_s": d_fit,
            "fit_max_resid_s": resid,
            "qe": qe,
            "sign": 1 if a_fit > 0 else -1,
            "c": float(c)}
