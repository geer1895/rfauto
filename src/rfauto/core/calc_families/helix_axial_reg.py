"""G17 helical（轴向模螺旋）CALC 注册面薄包装族（批 B Wave3 W3-G17G9，2026-10-13）。

三键：helix_axial_performance（Kraus 闭式性能）/ helix_axial_design（反设计，
for_n_turns/optimal 双 route）/ helix_axial_bandwidth（轴向模工作带宽）。

**薄注册纪律（规格包 runs/aurora_c/batch_b_wave3_specs/G17_helical_axial.md）**：
物理公式单源在 ``rfauto.core.helix_axial``（B2 器件族批交付的 Kraus 闭式
内核，纯函数零 IO）——本模块**只注册不实现**，零公式复制（#116 死副本
教训：本地副本遮蔽 re-export=死代码）。wrapper 是纯委托：参数单位换算
（CALC 键面 GHz/mm 惯例 ↔ core SI Hz/m/deg）+ dict 字段映射，不做任何
数值变换、不 round——**薄度守卫 = wrapper 输出与 core 直调逐位一致**
（tests/unit/test_b_wave3_helix_reg.py 逐字段 ``==`` 钉）。域判定/失效域
warnings/恰等出域 verdict 全部由 core 侧原样透传（单一语义源），本模块
不自行判域。

- 出处见 rfauto.core.helix_axial 模块 docstring（Kraus 经验闭式，Balanis
  §10.3.1 转引；有效域 0.75<C_λ<4/3、12°<α<14°、N>3 严格；锚树
  tests/unit/test_helix_axial.py H1-H6 已 #118 合规在库——本席不重造
  裁判、不新增数值断言面）。
- 锚（Balanis 2nd ed §10.3.1 工作例 N=10/f0=10GHz/C_λ=0.95/α=14°）：
  HPBW=35.5658°、FNBW=78.6551°、D₀=32.0651（15.0603 dB）、Z_in=133Ω
  （=140·C_λ 恒等）；AR(N=8)=1.0625（=1+1/2N）。
- 与既有面边界：service/anchor_family_service 消费 helix_axial 是 anchor
  通道（并存不撞）；Zverev 螺旋谐振器滤波器面、emc_radiated/small_loop
  环路面均不在本族（轴向模螺旋天线专用）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.helix_axial import (
    axial_mode_bandwidth,
    design_for_n_turns,
    design_optimal,
    kraus_performance,
)

from .registry import register_calculator
from .thermal import _finite

_SOURCE = (
    "出处见 rfauto.core.helix_axial 模块 docstring（Kraus 经验闭式，"
    "Balanis Antenna Theory §10.3.1 转引；本键为薄注册包装，公式零复制）"
)


def _perf_to_calc(p: dict[str, Any]) -> dict[str, Any]:
    """HelixPerformance.to_dict() → CALC 键面字段映射（唯一单位换算点）。

    换算只有两形：f0_hz/1e9（→GHz）、长度 m×1e3（→mm）；其余字段
    （角度/无量纲/嵌套 verdict/warnings）逐字段原样透传——薄度守卫测试
    按"同一换算式作用于 core 直调值后逐位 =="钉死本映射。
    """
    return {
        "f0_ghz": p["f0_hz"] / 1e9,
        "wavelength_mm": p["wavelength_m"] * 1e3,
        "n_turns": p["n_turns"],
        "alpha_deg": p["alpha_deg"],
        "diameter_mm": p["diameter_m"] * 1e3,
        "circumference_mm": p["circumference_m"] * 1e3,
        "pitch_mm": p["pitch_m"] * 1e3,
        "c_lambda": p["c_lambda"],
        "s_lambda": p["s_lambda"],
        "hpbw_deg": p["hpbw_deg"],
        "fnbw_deg": p["fnbw_deg"],
        "directivity": p["directivity"],
        "directivity_db": p["directivity_db"],
        "input_impedance_ohm": p["input_impedance_ohm"],
        "axial_ratio": p["axial_ratio"],
        "polarization": p["polarization"],
        "axial_mode": p["axial_mode"],
        "warnings": p["warnings"],
    }


@register_calculator(
    "helix_axial_performance",
    "轴向模螺旋天线 Kraus 闭式性能：HPBW=52/(C_λ√(N·S_λ))、FNBW=115/"
    "(C_λ√(N·S_λ))、D0=15·N·C_λ²·S_λ（线性+dB）、Zin≈140·C_λ、轴上轴比 "
    "AR=1+1/(2N)；随行轴向模域 "
    "verdict（0.75<C_λ<4/3、12°<α<14°、N>3 严格，恰等出域）与失效域 "
    "warnings（N≤3 不静默）。锚（Balanis §10.3.1 工作例 N=10/f0=10GHz/"
    "C_λ=0.95/α=14°）：HPBW=35.5658°/FNBW=78.6551°/D0=32.0651（15.0603dB）/"
    "Zin=133Ω",
    (("f0_ghz", "float GHz 中心频率（>0）"),
     ("n_turns", "float 圈数（≥1；≤3 为 Kraus 失效域，warnings 如实登记不拒绝）"),
     ("alpha_deg", "float ° 螺距角（0<α<90 物理可建域；设计规程域 12°<α<14°）"),
     ("c_lambda", "float 周长波长数 C/λ（>0；与 diameter_mm 二选一，同给须"
      "一致相对偏差 ≤1e-9）"),
     ("diameter_mm", "float mm 螺旋直径（>0；与 c_lambda 二选一，C=πD）"),
     ("include_axial_ratio", "bool 缺省 True；False 时 axial_ratio=None")),
    required=("f0_ghz", "n_turns", "alpha_deg"),
)
def helix_axial_performance(
    f0_ghz: float,
    n_turns: float,
    alpha_deg: float,
    c_lambda: float | None = None,
    diameter_mm: float | None = None,
    include_axial_ratio: bool = True,
) -> dict[str, Any]:
    """薄委托 kraus_performance（core SI 入参换算见上，输出零数值变换）。"""
    f0_hz = _finite(f0_ghz, "f0_ghz") * 1e9
    diameter_m = (
        None if diameter_mm is None
        else _finite(diameter_mm, "diameter_mm") * 1e-3)
    perf = kraus_performance(
        f0_hz, n_turns, alpha_deg,
        c_lambda=c_lambda, diameter_m=diameter_m,
        include_axial_ratio=include_axial_ratio,
    )
    out = _perf_to_calc(perf.to_dict())
    out["note"] = (
        "薄注册包装：域判定看 axial_mode.verdict（恰等出域），失效域 N≤3 "
        "看 warnings；Kraus 经验式与全波/实测偏差 ~1-2dB（core 诚实边界 1）")
    out["source"] = _SOURCE
    return out


@register_calculator(
    "helix_axial_design",
    "轴向模螺旋反设计双 route：给 n_turns → for_n_turns（N 整数化后尺寸"
    "唯一，C_λ=(D0/(15·N·tanα))^(1/3) 或 HPBW 形）；不给 n_turns → "
    "optimal（在 [n_min,n_max] 整数圈内选 C_λ 最靠带心=带宽余量最大的解，"
    "同距取更小 N）。输出直径/螺距/节距角/总轴长几何+随行 performance"
    "（design→performance 往返自洽 1e-9）。解出 C_λ 出规程域或 N≤3 → "
    "warnings 如实登记不拒绝（域外解是合法数学解，采信由调用方决定）",
    (("f0_ghz", "float GHz 中心频率（>0）"),
     ("n_turns", "float 圈数（可选；给则 route=for_n_turns，≥1）"),
     ("alpha_deg", "float ° 螺距角（缺省 13.0=规程域 [12°,14°] 带心）"),
     ("target_metric", "str 反设计目标度量：'directivity'（线性）| "
      "'hpbw_deg'（度），缺省 directivity"),
     ("target_value", "float 目标值（>0，同度量纲），缺省 30.0"),
     ("n_min", "int optimal 路线圈数下限（≥1），缺省 4"),
     ("n_max", "int optimal 路线圈数上限（≥n_min），缺省 64")),
    required=("f0_ghz",),
)
def helix_axial_design(
    f0_ghz: float,
    n_turns: float | None = None,
    alpha_deg: float = 13.0,
    target_metric: str = "directivity",
    target_value: float = 30.0,
    n_min: int = 4,
    n_max: int = 64,
) -> dict[str, Any]:
    """薄委托 design_for_n_turns/design_optimal（route 按同键分派）。"""
    f0_hz = _finite(f0_ghz, "f0_ghz") * 1e9
    if n_turns is not None:
        design = design_for_n_turns(
            f0_hz, n_turns, alpha_deg,
            target_metric=target_metric, target_value=target_value)
        route = "for_n_turns"
    else:
        design = design_optimal(
            f0_hz, alpha_deg,
            target_metric=target_metric, target_value=target_value,
            n_min=n_min, n_max=n_max)
        route = "optimal"
    d = design.to_dict()
    return {
        "route": route,
        "f0_ghz": d["f0_hz"] / 1e9,
        "n_turns": d["n_turns"],
        "alpha_deg": d["alpha_deg"],
        "target_metric": d["target_metric"],
        "target_value": d["target_value"],
        "c_lambda": d["c_lambda"],
        "diameter_mm": d["diameter_m"] * 1e3,
        "circumference_mm": d["circumference_m"] * 1e3,
        "pitch_mm": d["pitch_m"] * 1e3,
        "axial_length_mm": d["axial_length_m"] * 1e3,
        "warnings": d["warnings"],
        "performance": _perf_to_calc(d["performance"]),
        "note": (
            "for_n_turns=定 N 解 C_λ（尺寸唯一）；optimal=扫 N 选 |C_λ-1| "
            "最小（同距取更小 N）；域外解/失效域见 warnings"),
        "source": _SOURCE,
    }


@register_calculator(
    "helix_axial_bandwidth",
    "轴向模工作带宽（周长域判据频率域换算）：周长固定时 "
    "C_λ(f)=C_λ0·(f/f0) 落设计规程域 [0.75, 4/3] 的频率区间——f_low="
    "f0·0.75/C_λ0、f_high=f0·(4/3)/C_λ0，输出带边/带宽/比值与 f0 是否在"
    "带内。诚实边界：这是**周长域判据的频率域换算**，非增益/阻抗带宽"
    "估计（core 诚实边界 4，文献口径 ~1.78:1 波束带宽不在本键）",
    (("f0_ghz", "float GHz 设计中心频率（>0）"),
     ("c_lambda", "float 设计点周长波长数 C_λ0（>0）")),
    required=("f0_ghz", "c_lambda"),
)
def helix_axial_bandwidth(f0_ghz: float, c_lambda: float) -> dict[str, Any]:
    """薄委托 axial_mode_bandwidth（f0_hz→f0_ghz 单位换算）。"""
    bw = axial_mode_bandwidth(_finite(f0_ghz, "f0_ghz") * 1e9, c_lambda)
    return {
        "f_low_ghz": bw["f_low_hz"] / 1e9,
        "f_high_ghz": bw["f_high_hz"] / 1e9,
        "bandwidth_ghz": bw["bandwidth_hz"] / 1e9,
        "ratio": bw["ratio"],
        "f0_in_band": bw["f0_in_band"],
        "note": (
            "周长域判据换算（C_λ∈[0.75,4/3] 映射），非增益/阻抗带宽估计"
            "（core 模块头注诚实边界 4）"),
        "source": _SOURCE,
    }
