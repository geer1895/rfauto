"""HS-1 玻纤编织统计 skew 模型内核（纯闭式，零 IO；高速数字第三面）。

口径与来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- **WEAVE_STYLES 参数表**（pitch/纱宽/振幅/εr=6.0/tanδ=0.004，单位 mm）：
  逐值抄自 PyAEDT（ansys-aedt-core）GitHub main 分支
  ``src/ansys/aedt/core/modeler/advanced_cad/weave.py`` 的 ``WEAVE_STYLES``
  dict，SPDX-License-Identifier: MIT（Copyright (C) 2021 - 2026 Synopsys,
  Inc. and ANSYS, Inc.）——MIT 许可借参数值，出处文件路径如上；
  2026-09-27 实测抓取逐值核对（本仓 .venv 安装的 pyaedt 1.4.0 **无此
  模块**，该表属 main 分支 v1.7.0 实取；方案书所记 "PyAEDT 1.6" 与
  main 实取同源口径）。样式覆盖 1067/1080/2116/7628 四种常见玻璃布。
  warp=经纱（x/机向），fill=纬纱（y/横向）；x 向走线跨越 fill 纱
  （周期 pitch_x、横向纱宽 fill_width），y 向走线跨越 warp 纱
  （周期 pitch_y、横向纱宽 warp_width）。
- **Δt 闭式**：均匀介质传输线时延 T = L·√εeff/c（L 走线长、c 真空光速
  SI 精确值 299792458 m/s），两条路径（一在玻璃束上 εeff_hi、一在树脂
  区 εeff_lo）时延之差即 skew；实现=先各自算 T 再相减，ps 换算 ×1e12。
  sign 约定：hi 路径（εeff 高）更慢 → skew > 0。
- **均匀化口径（钉死一种：平行板串联混合）**：走线下方介质板按平行板
  串联（谐波）混合 ε_sub(f) = 1/(f/ε_glass + (1−f)/ε_resin)，f = 走线
  横向上玻璃占空比。上界路径=走线骑在纱线中心线（窄走线理想化
  f_hi = yarn_width/pitch；走线宽 w 时 f_hi = min(1, max(w, yarn)/pitch)）；
  下界路径=走线居树脂槽中央（窄走线理想化 f_lo = 0；w > pitch−yarn 时
  f_lo = min(1, (w−(pitch−yarn))/w)）。忽略空气域（场全在介质内的
  平行板全填充口径）：εeff 绝对值偏保守，两路径之差是 skew 主量。
  f=0/f=1 退化点按物理恒等式直返 ε_resin/ε_glass——浮点 1/(1/x) 往返
  不保逐位，退化分支使边界逐位成立（非特判造假：单一材料的谐波平均
  就是该材料本身）。
- **统计（概率平均）口径**：差分对两线玻璃覆盖率之差 Δρ ∈ [−1,1]
  （束覆盖比参数），E[skew] = Δρ·L·(√εeff_hi−√εeff_lo)/c；Δρ=1 退化为
  全长偏置最坏情形（与最坏口径逐位一致）。
- **weave-aware 布线**：zigzag 角 θ 的有效偏置周期 p_eff = pitch/sin(θ)
  （θ=90° 正交 → p_eff=pitch 逐位；θ→0 发散，定义域 (0°, 90°]）。建议
  角 ≥5°（保守 ≥10°）；差分对横向偏移取 n·pitch 对齐两线编织相位
  （相位对齐时两线覆盖率形态一致，残余 skew 由残余相位误差决定）。
  残余 skew 期望（均匀化平均意义的闭式近似，**标注：非统计严格结果**）
  = 最坏情形 × phase_error_frac / max(1, L/p_eff)（1/N 线性衰减启发式；
  phase_error_frac ∈ [0,1] 为 n·pitch 偏移规则执行后的残余相位误差
  占比，0=完全对齐）。
- **UI 对照面**：UI = 1/波特率，波特率 = 数据率（比特）/log2(NS)
  （NRZ NS=2 → UI=1/比特率，25.78125 Gb/s → UI≈38.8 ps；PAM4 NS=4 →
  UI=2/比特率）。判据 |skew| ≤ budget_frac·UI（budget_frac 为规则阈值
  旋钮非物理常数，缺省 0.1=每 UI 一成，恰等判达标）。

诚实边界（预声明）：本内核是统计闭式上界/期望估计面——不含损耗/色散
（εr 视作频率常数）、不含邻近效应与差分线间耦合修正、single-pitch 理想
织构（不含随机纱偏移统计）；Δt 闭式对微带/带线均按"场全在介质内"平行
板口径（微带实际 εeff 更低，skew 差值同口径可比但不等于全波值）；
er_resin 不内嵌缺省值（环氧树脂 εr 无单一权威常数，文献典型域
~3.0–3.8，调用方按叠层数据表给值——#118 无可达单源精确数不虚构）；
全波截面验证（openEMS）是后续独立裁判，本模块不自证物理正确性。

接口：全部函数返回 JSON 可序列化 float/dict/list（float/str/bool），单位
钉在参数名（mm/m/ps/deg）。数值 0.0 合法（coverage_delta=0、
phase_error_frac=0 等，判缺失一律 is not None，#364④）；bool 显式拒收
（df7+⑯）；非有限拒收。纯函数零 IO；不进 calculators 注册表（F-C P1
域内约定，消费者是 service/glass_weave_skew_service.py）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 真空光速（m/s，SI 精确定义值）
C_VACUUM_M_PER_S = 299792458.0
#: 秒 → 皮秒
PS_PER_S = 1e12
#: 米 → 毫米
MM_PER_M = 1000.0

#: weave-aware 布线最低建议 zigzag 角（deg；方案口径 ≥5°）
MIN_ROUTING_ANGLE_DEG = 5.0
#: 保守建议角（deg；方案口径 ≥10°）
CONSERVATIVE_ROUTING_ANGLE_DEG = 10.0
#: routing_rules_table 缺省角度档
DEFAULT_TABLE_THETAS_DEG = (5.0, 10.0, 15.0, 30.0, 45.0, 90.0)

# ─── WEAVE_STYLES 参数表（MIT 许可借参数值，出处见模块 docstring）────────────

WEAVE_STYLES: dict[str, dict[str, float]] = {
    "1067": dict(
        pitch_x_mm=0.28,
        pitch_y_mm=0.28,
        warp_width_mm=0.13,
        fill_width_mm=0.13,
        amplitude_mm=0.025,
        er_glass=6.0,
        tan_delta_glass=0.004,
        ratio_warp=0.077,
        ratio_fill=0.077,
    ),
    "1080": dict(
        pitch_x_mm=0.40,
        pitch_y_mm=0.40,
        warp_width_mm=0.18,
        fill_width_mm=0.18,
        amplitude_mm=0.035,
        er_glass=6.0,
        tan_delta_glass=0.004,
        ratio_warp=0.067,
        ratio_fill=0.067,
    ),
    "2116": dict(
        pitch_x_mm=0.50,
        pitch_y_mm=0.50,
        warp_width_mm=0.20,
        fill_width_mm=0.20,
        amplitude_mm=0.050,
        er_glass=6.0,
        tan_delta_glass=0.004,
        ratio_warp=0.057,
        ratio_fill=0.057,
    ),
    "7628": dict(
        pitch_x_mm=0.80,
        pitch_y_mm=0.80,
        warp_width_mm=0.35,
        fill_width_mm=0.28,
        amplitude_mm=0.080,
        er_glass=6.0,
        tan_delta_glass=0.004,
        ratio_warp=0.057,
        ratio_fill=0.057,
    ),
}

#: WEAVE_STYLES 出处登记（服务层 provenance 直用）
WEAVE_STYLES_PROVENANCE: dict[str, str] = {
    "source_file": "src/ansys/aedt/core/modeler/advanced_cad/weave.py",
    "source_project": "PyAEDT (ansys-aedt-core) GitHub main 分支",
    "license": "MIT",
    "copyright": "Copyright (C) 2021 - 2026 Synopsys, Inc. and ANSYS, Inc.",
    "verified": (
        "2026-09-27 逐值抓取核对；本地 .venv pyaedt 1.4.0 无此模块，"
        "main 分支（v1.7.0）实取"
    ),
    "units": "mm（er_glass/tan_delta_glass/ratio 无量纲）",
    "note": "MIT 许可借参数值；er_resin 不在源表中，由调用方按叠层数据表提供",
}


# ─── 入参收敛助手（与 core/aging.py 同口径）──────────────────────────────────


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


def _ratio(value: float, name: str) -> float:
    """把入参收敛为 [0,1] 内有限 float（占空比/覆盖率/相位误差占比）。"""
    out = _finite(value, name)
    if out < 0.0 or out > 1.0:
        raise ValueError(f"{name} 必须 ∈ [0,1]")
    return out


def _sym_ratio(value: float, name: str) -> float:
    """把入参收敛为 [-1,1] 内有限 float（带符号覆盖率差 Δρ）。"""
    out = _finite(value, name)
    if out < -1.0 or out > 1.0:
        raise ValueError(f"{name} 必须 ∈ [-1,1]")
    return out


def _theta_deg(value: float, name: str) -> float:
    """zigzag 角收敛：有限且 ∈ (0°, 90°]（θ→0 发散、θ>90° 越界均拒绝）。"""
    out = _finite(value, name)
    if out <= 0.0 or out > 90.0:
        raise ValueError(f"{name} 必须 ∈ (0, 90] deg")
    return out


# ─── 样式表 dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeaveStyleSpec:
    """一种玻璃布样式的参数集（单位 mm；字段语义见模块 docstring 来源节）。"""

    style: str
    pitch_x_mm: float
    pitch_y_mm: float
    warp_width_mm: float
    fill_width_mm: float
    amplitude_mm: float
    er_glass: float
    tan_delta_glass: float
    ratio_warp: float
    ratio_fill: float

    def to_dict(self) -> dict[str, float | str]:
        """JSON 可序列化 dict（服务层信封直用）。"""
        return {
            "style": self.style,
            "pitch_x_mm": self.pitch_x_mm,
            "pitch_y_mm": self.pitch_y_mm,
            "warp_width_mm": self.warp_width_mm,
            "fill_width_mm": self.fill_width_mm,
            "amplitude_mm": self.amplitude_mm,
            "er_glass": self.er_glass,
            "tan_delta_glass": self.tan_delta_glass,
            "ratio_warp": self.ratio_warp,
            "ratio_fill": self.ratio_fill,
        }


def weave_style_spec(style: str) -> WeaveStyleSpec:
    """样式名 → :class:`WeaveStyleSpec`（未知样式 ValueError，列出可选项）。"""
    if not isinstance(style, str):
        raise ValueError(f"style 必须为 str，实际 {type(style).__name__}")
    row = WEAVE_STYLES.get(style)
    if row is None:
        raise ValueError(f"未知 weave style {style!r}，可用：{sorted(WEAVE_STYLES)}")
    return WeaveStyleSpec(style=style, **row)


def direction_geometry(
    style: str | WeaveStyleSpec, direction: str = "x"
) -> dict[str, str | float]:
    """走线方向 → 跨越纱线的（周期, 纱宽）几何。

    direction="x"：跨越 fill 纱 → (pitch_x_mm, fill_width_mm)；
    direction="y"：跨越 warp 纱 → (pitch_y_mm, warp_width_mm)。
    7628 两向纱宽不同（warp 0.35 / fill 0.28），方向必须显式选。
    """
    spec = weave_style_spec(style) if isinstance(style, str) else style
    if not isinstance(spec, WeaveStyleSpec):
        raise ValueError("style 必须为样式名或 WeaveStyleSpec")
    if direction == "x":
        return {
            "direction": direction,
            "pitch_mm": spec.pitch_x_mm,
            "yarn_width_mm": spec.fill_width_mm,
        }
    if direction == "y":
        return {
            "direction": direction,
            "pitch_mm": spec.pitch_y_mm,
            "yarn_width_mm": spec.warp_width_mm,
        }
    raise ValueError(f"direction 必须 'x' 或 'y'，实际 {direction!r}")


# ─── 均匀化：占空比与 εeff 上下界（平行板串联混合口径）───────────────────────


def series_mixture_er(er_glass: float, er_resin: float, glass_fraction: float) -> float:
    """平行板串联（谐波）混合 ε_sub(f) = 1/(f/εg + (1−f)/εr)。

    f=glass_fraction ∈ [0,1]（玻璃占空比）；er_glass/er_resin 必须 >0。
    退化点按物理恒等式直返：f=0 → εr、f=1 → εg（逐位；浮点 1/(1/x)
    往返不保逐位，退化分支见模块 docstring）。εg>εr 时对 f 单调递增。
    """
    eg = _positive(er_glass, "er_glass")
    er = _positive(er_resin, "er_resin")
    f = _ratio(glass_fraction, "glass_fraction")
    return _series_mixture_er_pure(eg, er, f)


def _series_mixture_er_pure(eg: float, er: float, f: float) -> float:
    """已收敛入参的谐波混合（内部路径，f=0/1 退化分支逐位成立）。"""
    if f == 0.0:
        return er
    if f == 1.0:
        return eg
    return 1.0 / (f / eg + (1.0 - f) / er)


def homogenize_er_bounds(
    pitch_mm: float,
    yarn_width_mm: float,
    er_glass: float,
    er_resin: float,
    trace_width_mm: float | None = None,
) -> dict[str, float | None]:
    """差分走线两路径的 εeff 均匀化上下界（平行板串联混合口径）。

    pitch_mm/yarn_width_mm：跨越方向编织周期与纱宽（mm，>0；
    yarn_width > pitch 时占空比钳 1）。er_glass/er_resin >0。
    trace_width_mm：走线宽（mm，可选；None=窄走线理想化——上界路径
    f_hi=yarn/pitch、下界路径 f_lo=0）。

    返回（JSON 可序列化）：{"f_hi", "f_lo", "er_on_yarn"（上界路径）,
    "er_in_resin"（下界路径）, "er_upper" = max(两路径), "er_lower" =
    min(两路径)}。窄走线理想化下 f_lo=0 → er_lower == er_resin 逐位；
    trace_width ≥ pitch 时 f_hi=1 → er_upper == er_glass 逐位。
    """
    pitch = _positive(pitch_mm, "pitch_mm")
    yarn = _positive(yarn_width_mm, "yarn_width_mm")
    eg = _positive(er_glass, "er_glass")
    er = _positive(er_resin, "er_resin")
    if trace_width_mm is not None:
        width = _positive(trace_width_mm, "trace_width_mm")
        f_hi = min(1.0, max(width, yarn) / pitch)
        pocket = pitch - yarn
        f_lo = min(1.0, max(0.0, (width - pocket) / width))
    else:
        f_hi = min(1.0, yarn / pitch)
        f_lo = 0.0
    er_on = _series_mixture_er_pure(eg, er, f_hi)
    er_off = _series_mixture_er_pure(eg, er, f_lo)
    return {
        "f_hi": f_hi,
        "f_lo": f_lo,
        "er_on_yarn": er_on,
        "er_in_resin": er_off,
        "er_upper": max(er_on, er_off),
        "er_lower": min(er_on, er_off),
    }


# ─── Δt 闭式：时延差（先各算 T 再相减）───────────────────────────────────────


def path_delay_s(length_m: float, er_eff: float) -> float:
    """均匀介质走线时延 T = L·√εeff/c（L 米、返回秒）。

    εeff=1 → T = L/c（逐位）。length_m 必须 >0，er_eff 必须 >0。
    """
    lm = _positive(length_m, "length_m")
    er = _positive(er_eff, "er_eff")
    return lm * math.sqrt(er) / C_VACUUM_M_PER_S


def weave_skew_ps(length_m: float, er_eff_hi: float, er_eff_lo: float) -> dict[str, float]:
    """最坏情形 skew（全长偏置口径）：Δt = T_hi − T_lo，ps。

    er_eff_hi/er_eff_lo：两路径 εeff（典型=homogenize_er_bounds 的
    er_upper/er_lower）。sign 约定：hi 路径更慢 → 正。ε_hi == ε_lo →
    0.0（逐位）；上下界交换 → 变号且绝对值逐位不变（IEEE 减法反对称）。
    """
    lm = _positive(length_m, "length_m")
    t_hi = path_delay_s(lm, er_eff_hi)
    t_lo = path_delay_s(lm, er_eff_lo)
    return {
        "skew_ps": (t_hi - t_lo) * PS_PER_S,
        "delay_hi_ps": t_hi * PS_PER_S,
        "delay_lo_ps": t_lo * PS_PER_S,
    }


def weave_skew_expected_ps(
    length_m: float, coverage_delta: float, er_eff_hi: float, er_eff_lo: float
) -> dict[str, float]:
    """概率平均 skew（束覆盖比口径）：E[skew] = Δρ·(T_hi − T_lo)，ps。

    coverage_delta = Δρ ∈ [−1,1]：差分对两线玻璃覆盖率之差（1=一线全程
    在束上另一线全程在树脂=最坏全长偏置；0=两线覆盖率相同）。
    Δρ=1 → 与 weave_skew_ps 逐位一致；Δρ=0 → 0.0（逐位）。
    """
    lm = _positive(length_m, "length_m")
    delta = _sym_ratio(coverage_delta, "coverage_delta")
    t_hi = path_delay_s(lm, er_eff_hi)
    t_lo = path_delay_s(lm, er_eff_lo)
    span_ps = (t_hi - t_lo) * PS_PER_S
    return {
        "skew_expected_ps": delta * span_ps,
        "worst_case_ps": span_ps,
        "coverage_delta": delta,
    }


# ─── weave-aware 布线规则 ────────────────────────────────────────────────────


def zigzag_effective_period_mm(pitch_mm: float, theta_deg: float) -> float:
    """zigzag 角 θ 的有效偏置周期 p_eff = pitch/sin(θ)（mm）。

    θ=90°（正交跨越）→ p_eff == pitch（逐位）；θ→0⁺ → p_eff→∞（发散）；
    定义域 (0°, 90°]，域外 ValueError。
    """
    pitch = _positive(pitch_mm, "pitch_mm")
    th = _theta_deg(theta_deg, "theta_deg")
    if th == 90.0:
        # 物理恒等式：正交跨越周期即 pitch（逐位保证，见模块 docstring）
        return pitch
    return pitch / math.sin(math.radians(th))


def zigzag_residual_expected_ps(
    length_m: float,
    pitch_mm: float,
    theta_deg: float,
    phase_error_frac: float,
    er_eff_hi: float,
    er_eff_lo: float,
) -> dict[str, float]:
    """zigzag 布线的残余 skew 期望（闭式近似，**非统计严格结果**）。

    模型：全长最坏 skew × phase_error_frac / max(1, n_periods)，其中
    n_periods = L/p_eff（p_eff=pitch/sin θ）。1/N 线性衰减是均匀化平均
    意义的启发式近似（标注见模块 docstring）；phase_error_frac ∈ [0,1]
    为 n·pitch 偏移规则执行后的残余相位误差占比（0=完全对齐 → 残余 0
    逐位；1=完全未对齐且 L ≤ p_eff 时残余=最坏情形 逐位）。
    """
    lm = _positive(length_m, "length_m")
    p_eff = zigzag_effective_period_mm(pitch_mm, theta_deg)
    phase = _ratio(phase_error_frac, "phase_error_frac")
    n_periods = (lm * MM_PER_M) / p_eff
    n_avg = max(1.0, n_periods)
    worst = weave_skew_ps(lm, er_eff_hi, er_eff_lo)["skew_ps"]
    return {
        "p_eff_mm": p_eff,
        "n_periods": n_periods,
        "phase_error_frac": phase,
        "residual_ps": worst * phase / n_avg,
        "worst_case_ps": worst,
    }


def routing_rules_table(
    pitch_mm: float, thetas_deg: list[float] | tuple[float, ...] | None = None
) -> list[dict[str, float | bool]]:
    """weave-aware 布线规则量化表（θ 档 → p_eff + 建议角标记）。

    缺省角度档 (5, 10, 15, 30, 45, 90)°。每行 {"theta_deg", "p_eff_mm",
    "recommended"（θ ≥ 5° 方案建议角）}。n·pitch 横向偏移规则（差分对
    两线编织相位对齐）不随 θ 变化，见模块 docstring 与
    zigzag_residual_expected_ps 的 phase_error_frac 参数。
    """
    pitch = _positive(pitch_mm, "pitch_mm")
    thetas = DEFAULT_TABLE_THETAS_DEG if thetas_deg is None else thetas_deg
    if not isinstance(thetas, (list, tuple)):
        raise ValueError("thetas_deg 必须为角度序列")
    rows: list[dict[str, float | bool]] = []
    for idx, th in enumerate(thetas):
        theta = _theta_deg(th, f"thetas_deg[{idx}]")
        rows.append(
            {
                "theta_deg": theta,
                "p_eff_mm": zigzag_effective_period_mm(pitch, theta),
                "recommended": theta >= MIN_ROUTING_ANGLE_DEG,
            }
        )
    return rows


# ─── 奈奎斯特对照面：UI 换算与 verdict ───────────────────────────────────────


def ui_ps(data_rate_gbps: float, ns_levels: float = 2) -> float:
    """单位间隔 UI = 1/波特率（ps）；波特率 = 数据率(比特)/log2(NS)。

    data_rate_gbps：比特率（Gb/s，>0）；ns_levels：调制电平数 N
    （整数 ≥2；NRZ=2、PAM4=4）。25.78125 Gb/s NS=2 → 38.7879 ps 量级。
    """
    rate = _positive(data_rate_gbps, "data_rate_gbps")
    if isinstance(ns_levels, bool):
        raise ValueError("ns_levels 不接受 bool（float(True)=1.0 静默污染统计）")
    ns = float(ns_levels)
    if not math.isfinite(ns) or ns < 2.0 or ns != int(ns):
        raise ValueError("ns_levels 必须为 >=2 的整数电平数")
    return 1e3 * math.log2(ns) / rate


def skew_ui_verdict(
    skew_ps_value: float,
    data_rate_gbps: float,
    ns_levels: float = 2,
    budget_frac: float = 0.1,
) -> dict[str, float | bool]:
    """skew vs UI 预算 verdict：|skew| ≤ budget_frac·UI（恰等判达标）。

    skew_ps_value：skew（ps，任意有限值，sign 保留）；budget_frac ∈ [0,1]
    （规则阈值旋钮非物理常数，缺省 0.1）。返回 {"ui_ps", "skew_ps",
    "skew_over_ui", "budget_frac", "allowed_ps", "within_budget"}。
    """
    skew = _finite(skew_ps_value, "skew_ps_value")
    ui = ui_ps(data_rate_gbps, ns_levels)
    budget = _ratio(budget_frac, "budget_frac")
    allowed = budget * ui
    return {
        "ui_ps": ui,
        "skew_ps": skew,
        "skew_over_ui": abs(skew) / ui,
        "budget_frac": budget,
        "allowed_ps": allowed,
        "within_budget": abs(skew) <= allowed,
    }
