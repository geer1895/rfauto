"""F-L 第 3 步：振荡器综合内核（负阻起振判据 + 三点式频率闭式 + Leeson 相噪 + DRO 耦合）。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- 负阻起振判据：Kurokawa 负阻振荡器理论（K. Kurokawa, 1973 负阻振荡
  反射系数口径，任务书钉定；本地无原文——**二手转引**，通行口径见
  Pozar《Microwave Engineering》§12.2 一端口负阻振荡器设计）：小信号
  起振幅值条件 |Γ_amp|·|Γ_res| > 1、相位条件 ∠Γ_amp+∠Γ_res=0（mod 2π，
  振荡频率点）；串联口径 R_amp+R_res<0。大信号稳定交点：|R_in(V)| 随
  振幅增大而减小（限幅）→ R_in(V)+R_res 自下而上穿过 0 处即稳态工作
  点，交点处 R_in 随 V 递增（曲线斜率>0）判稳定。
- 三点式频率闭式（通行 RF 教科书口径，Razavi《RF Microelectronics》
  2nd ed. Ch.8 Oscillators；小节号二手转引不钉）：Colpitts
  C_eq=C1·C2/(C1+C2)、Hartley L_eq=L1+L2+2M（互感显式参数）、Clapp
  三电容串联 C3 主导、交叉耦合 LC f=1/(2π√(L·C))；交叉耦合差分负阻
  −2/gm、起振条件 gm·R_p≥2（R_p=谐振回路并联电阻）——|−2/gm|<R_p
  ⇔ gm·R_p>2，与并联导纳口径恒等。
- Leeson 相噪闭式（D. B. Leeson, "A Simple Model of Feedback Oscillator
  Noise Spectrum", Proc. IEEE 54(2): 329-330, Feb. 1966；本地无原文——
  **二手转引**，式形按任务书钉定）：L_lin(Δf) = F·k·T0/(2·P_s) ·
  (1+f_c/(2Δf)) · (1+(f0/(2·Q_L·Δf))²)。F=线性噪声因子、P_s=信号功率、
  f_c=器件 1/f 拐角、Q_L=有载 Q、T0=标准噪声温度（缺省 290 K，IEEE
  口径）。两个括号各自在 Δf=f_c/2 与 Δf=f0/(2Q_L) 处恰=2（+3.0103 dB）
  ——本内核取该两处为**有效拐角**（任务书钉定闪烁项 (1+f_c/(2Δf)) 与
  通行变体 (1+f_c/Δf) 差 2 倍拐角定义，本内核按钉定式自洽）。三段渐近
  幂律链（斜率 −3 / −2或−1 / 0）在拐角处与精确式解析衔接（分区渐近
  图像与 Hajimiri-Lee 分区谱同构）；段 dict 契约照抄
  core/clock_noise.build_power_law_segments 的输出契约：
  {f_lo, f_hi, slope, l_ref_dbc, f_ref}，L(f)=l_ref_dbc+10·slope·
  log10(f/f_ref)。精确式本身解析可积（乘积展开=斜率 0/−1/−2/−3 四条
  幂律之和，恰为 clock_noise 可积族同族）——leeson_sigma_phi2_exact
  逐项闭式积分，不经幂律链近似。
- DRO 耦合（介质谐振器外耦合通行口径，Kajfez & Guillon《Dielectric
  Resonators》二手转引）：Q_L=Q_0/(1+β)；外耦合功率比 β/(1+β)、腔内
  耗散 1/(1+β)、临界耦合 β=1 两两各半。Q_L 直供 Leeson：本模块 leeson_*
  全部收 q_l，由调用方经 dro_loaded_q 折算。

与 clock_noise（F-E 件 2）的关系：单向产数——本模块产段链，积分/求值
消费 clock_noise 公共接口（power_law_sigma_phi2 / power_law_l_dbc /
phase_jitter_from_l）；本模块**不 import clock_noise**（双向零耦合防同
式双实现分叉，#112 家族，clock_noise 头注同约定），rms 抖动闭环积分
自检在测试与 service 层做。active_chain（S 参数面）/pll_budget
（crystal_l_dbc 晶振谱）为只读互引面，本模块零依赖。

接口：全部函数返回 JSON 可序列化 float/dict（float/str/bool/None/list），
单位显式钉在参数名（Hz/s/S/Ω/W/K）。频率一律偏移频率 Δf（>0；f=0 即
载波本身，谱无定义）。数值 0.0 合法（f_c=0 即无闪烁项；判缺失一律
is not None，#364④；`or` 缺省惯语禁用于数值可达 0 的面）。负值元件/
非正 Q/P_s≤0/|k|>1 → ValueError。纯算法零 IO；不进 calculators 注册表
（F-L 域内约定，消费者是 service 层与测试）。

诚实边界（预声明）：
1. 起振判据是小信号线性判据+理想限幅稳态交点，不含注入锁定、pushing/
   pulling、VCO 调谐非线性（Kurokawa 全理论覆盖面远大于此，本内核只取
   起振与稳态两判据）；
2. Leeson 模型本身是经验模型：F、f_c 为拟合参数，不由本内核标定（由
   测量面/调用方供给）；三段幂律链是渐近近似（拐角过渡带内与精确式
   偏差可达 ~3 dB 量级，随两拐角间距变化），需要精确积分用
   leeson_sigma_phi2_exact，段链仅供与 clock_noise 拼接面消费；
3. 大信号交点用采样曲线线性插值且不外推——采样密度不足的交点位置
   误差由调用方负责（n_crossings/n_stable_crossings 诚实回告）；
4. 交叉耦合 −2/gm 是差分对限幅后的基波负阻一阶口径，不含尾噪声源
   上变频等 Hajimiri-Lee 机理细节（相噪面由 Leeson 经验模型承载）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "K_B_SI",
    "T0_REF_K",
    "ClappDesign",
    "ColpittsDesign",
    "CrossCoupledStartup",
    "HartleyDesign",
    "LeesonResult",
    "MarginSweep",
    "NegativeResistanceResult",
    "OperatingPointResult",
    "ReflectionStartupResult",
    "clapp_design",
    "clapp_frequency",
    "colpitts_design",
    "colpitts_equivalent_cap",
    "colpitts_frequency",
    "cross_coupled_design",
    "cross_coupled_frequency",
    "cross_coupled_margin_sweep",
    "cross_coupled_negative_resistance",
    "cross_coupled_startup",
    "dro_coupling_power",
    "dro_loaded_q",
    "hartley_design",
    "hartley_equivalent_ind",
    "hartley_frequency",
    "lc_resonant_frequency",
    "leeson_floor_dbc",
    "leeson_floor_lin",
    "leeson_l_dbc",
    "leeson_lin",
    "leeson_model",
    "leeson_sigma_phi2_exact",
    "negative_resistance_operating_point",
    "negative_resistance_startup",
    "reflection_startup",
]

# Boltzmann 常数（J/K）：SI 2019 精确定义值（CODATA 2018）
K_B_SI = 1.380649e-23
# 标准噪声温度（K）：IEEE 噪声口径（Leeson 式 T0）
T0_REF_K = 290.0

_TWO_PI = 2.0 * math.pi


# ─── 入参守卫（#140：注解不等于调用方真的传了；df7+⑯ bool 显式拒收）─────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: Any, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {out!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    """入参收敛为有限非负 float，非法即显式报错（0.0 合法）。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，实际 {out!r}")
    return out


def _component(value: Any, name: str) -> float:
    """元件值（L/C/R）收敛：有限且 >0（负值/零元件 → ValueError）。"""
    return _positive(value, name)


def _freq_array(value: Any, name: str) -> np.ndarray:
    """频率数组收敛：一维、有限、严格递增、全 >0。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(f"{name} 必须是长度 ≥2 的一维数组，实际形状 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    if not bool(np.all(np.diff(arr) > 0.0)):
        raise ValueError(f"{name} 必须严格单调递增")
    if float(arr[0]) <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return arr


def _real_array(value: Any, name: str, expect: int | None = None) -> np.ndarray:
    """实数数组收敛：一维、有限、长度校验（reject bool 数组）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    if np.asarray(value).dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维数组，实际形状 {arr.shape}")
    if expect is not None and arr.size != expect:
        raise ValueError(f"{name} 必须是长度 {expect} 的一维数组，实际长度 {arr.size}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    return arr


def _carray(value: Any, name: str, expect: int) -> np.ndarray:
    """复数数组收敛：一维、长度 expect、实虚部全有限（reject bool 数组）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    if np.asarray(value).dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组")
    arr = np.asarray(value, dtype=complex)
    if arr.ndim != 1 or arr.size != expect:
        raise ValueError(f"{name} 必须是长度 {expect} 的一维数组，实际形状 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    return arr


# ─── 1. 负阻起振判据（Kurokawa 口径）────────────────────────────────────────


@dataclass(frozen=True)
class NegativeResistanceResult:
    """串联负阻小信号起振判据结果（字段语义见 negative_resistance_startup）。"""

    r_in_ohm: float
    r_res_ohm: float
    oscillates: bool
    margin: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "r_in_ohm": self.r_in_ohm,
            "r_res_ohm": self.r_res_ohm,
            "oscillates": self.oscillates,
            "margin": self.margin,
        }


@dataclass(frozen=True)
class OperatingPointResult:
    """大信号稳态工作点搜索结果（字段语义见 negative_resistance_operating_point）。"""

    r_res_ohm: float
    small_signal_starts: bool
    stable_point_exists: bool
    amplitude: float | None
    r_in_at_point: float | None
    n_crossings: int
    n_stable_crossings: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "r_res_ohm": self.r_res_ohm,
            "small_signal_starts": self.small_signal_starts,
            "stable_point_exists": self.stable_point_exists,
            "amplitude": self.amplitude,
            "r_in_at_point": self.r_in_at_point,
            "n_crossings": self.n_crossings,
            "n_stable_crossings": self.n_stable_crossings,
        }


@dataclass(frozen=True)
class ReflectionStartupResult:
    """反射系数起振判据结果（字段语义见 reflection_startup）。"""

    oscillates: bool
    freq_hz: float | None
    product_mag: float | None
    margin: float | None
    n_candidates: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "oscillates": self.oscillates,
            "freq_hz": self.freq_hz,
            "product_mag": self.product_mag,
            "margin": self.margin,
            "n_candidates": self.n_candidates,
        }


def negative_resistance_startup(r_in_ohm: float, r_res_ohm: float) -> NegativeResistanceResult:
    """串联负阻小信号起振判据：R_amp+R_res<0（Kurokawa 串联口径）。

    r_in_ohm：小信号器件输入电阻（Ω，期望 <0；≥0 是合法物理输入，
    判 oscillates=False 不抛——器件无负阻即不起振，诚实回告）；
    r_res_ohm：谐振腔等效损耗电阻（Ω，必须 >0，否则 ValueError）。

    margin = (−r_in−r_res)/r_res：>0 起振、==0 恰临界（严格判据不起振）、
    <0 不起振。r_in=−r_res 恰临界时 margin==0.0（逐位）。
    """
    r_in = _finite(r_in_ohm, "r_in_ohm")
    r_res = _component(r_res_ohm, "r_res_ohm")
    net = -r_in - r_res  # = −(R_amp+R_res)：>0 即 R_amp+R_res<0 起振
    return NegativeResistanceResult(
        r_in_ohm=r_in,
        r_res_ohm=r_res,
        oscillates=net > 0.0,
        margin=net / r_res,
    )


def negative_resistance_operating_point(
    amplitudes: Any, r_in_curve: Any, r_res_ohm: float
) -> OperatingPointResult:
    """大信号稳态工作点：R_in(V)+R_res 自下而上过零且 R_in 随 V 递增判稳定。

    amplitudes：振幅采样（V，一维严格递增、≥2 点、非负、有限）；
    r_in_curve：与 amplitudes 等长的器件电阻曲线 R_in(V)（Ω，有限）；
    r_res_ohm：谐振腔损耗电阻（Ω，>0）。

    Kurokawa 稳定性口径：限幅器件 |R_in| 随振幅增大而减小（R_in 递增），
    故 R_in(V)+R_res 由负穿 0 处为稳定平衡点；若曲线斜率 <0（正反馈型
    过零）该交点不稳定、跳过。首个稳定交点线性插值返回；无起振
    （residual[0]≥0）或无稳定交点 → stable_point_exists=False、amplitude
    =None（诚实回告，不外推）。n_crossings 记全部过零（含不稳定）。
    """
    r_res = _component(r_res_ohm, "r_res_ohm")
    v = _real_array(amplitudes, "amplitudes")
    if v.size < 2:
        raise ValueError("amplitudes 必须是长度 ≥2 的一维数组")
    if float(v[0]) < 0.0:
        raise ValueError("amplitudes 必须 >=0（振幅非负）")
    if not bool(np.all(np.diff(v) > 0.0)):
        raise ValueError("amplitudes 必须严格单调递增")
    r = _real_array(r_in_curve, "r_in_curve", v.size)
    residual = r + r_res
    small_starts = bool(residual[0] < 0.0)
    n_cross = 0
    n_stable = 0
    for k in range(v.size - 1):
        r0, r1 = float(residual[k]), float(residual[k + 1])
        if (r0 < 0.0 <= r1) or (r1 < 0.0 <= r0):
            n_cross += 1
        if r0 < 0.0 <= r1 and float(r[k + 1]) > float(r[k]):
            n_stable += 1
            if n_stable == 1:
                frac = (0.0 - r0) / (r1 - r0)
                amp = float(v[k]) + frac * (float(v[k + 1]) - float(v[k]))
                rin_at = float(r[k]) + frac * (float(r[k + 1]) - float(r[k]))
    exists = n_stable > 0
    amp_out: float | None = amp if exists else None
    rin_out: float | None = rin_at if exists else None
    return OperatingPointResult(
        r_res_ohm=r_res,
        small_signal_starts=small_starts,
        stable_point_exists=exists,
        amplitude=amp_out,
        r_in_at_point=rin_out,
        n_crossings=n_cross,
        n_stable_crossings=n_stable,
    )


def reflection_startup(
    gamma_amp: Any, gamma_res: Any, freq_hz: Any
) -> ReflectionStartupResult:
    """反射系数起振判据（Kurokawa）：|Γ_amp·Γ_res|>1 且 ∠Γ_amp+∠Γ_res=0（mod 2π）。

    gamma_amp / gamma_res：有源器件注入反射系数与谐振腔反射系数
    （等长复数数组）；freq_hz：对应频率轴（Hz，严格递增、>0、≥2 点）。

    相位条件=乘积 Γ_amp·Γ_res 的辐角过 0（unwrapped 相位跨零线性插值
    定振荡频率；多候选取 |乘积| 最大者——最易起振点）。margin=
    |Γ_amp·Γ_res|−1（>0 起振）。无相位交点 → oscillates=False、freq_hz/
    product_mag/margin=None、n_candidates=0（诚实回告）。
    """
    f = _freq_array(freq_hz, "freq_hz")
    ga = _carray(gamma_amp, "gamma_amp", f.size)
    gr = _carray(gamma_res, "gamma_res", f.size)
    prod = ga * gr
    phase = np.unwrap(np.angle(prod))
    candidates: list[tuple[float, float]] = []
    for k in range(f.size - 1):
        p0, p1 = float(phase[k]), float(phase[k + 1])
        if not ((p0 < 0.0 <= p1) or (p1 < 0.0 <= p0)):
            continue
        frac = (0.0 - p0) / (p1 - p0)
        f_star = float(f[k]) + frac * (float(f[k + 1]) - float(f[k]))
        re_star = float(prod.real[k]) + frac * (float(prod.real[k + 1]) - float(prod.real[k]))
        im_star = float(prod.imag[k]) + frac * (float(prod.imag[k + 1]) - float(prod.imag[k]))
        candidates.append((f_star, math.hypot(re_star, im_star)))
    if not candidates:
        return ReflectionStartupResult(
            oscillates=False, freq_hz=None, product_mag=None, margin=None, n_candidates=0
        )
    f_best, mag_best = max(candidates, key=lambda item: item[1])
    return ReflectionStartupResult(
        oscillates=mag_best > 1.0,
        freq_hz=f_best,
        product_mag=mag_best,
        margin=mag_best - 1.0,
        n_candidates=len(candidates),
    )


# ─── 2. 三点式频率闭式 + 反设计 ──────────────────────────────────────────────


def lc_resonant_frequency(l_h: float, c_f: float) -> float:
    """LC 谐振频率 f = 1/(2π√(L·C))（Hz）。l_h（H）/c_f（F）必须 >0。"""
    l_val = _component(l_h, "l_h")
    c = _component(c_f, "c_f")
    return 1.0 / (_TWO_PI * math.sqrt(l_val * c))


def _series_caps(caps: tuple[float, ...]) -> float:
    """串联电容 C_eq = 1/Σ(1/Ci)（入参已收敛 >0，最少 2 个）。"""
    return 1.0 / sum(1.0 / c for c in caps)


def colpitts_equivalent_cap(c1_f: float, c2_f: float) -> float:
    """Colpitts 等效电容 C_eq = C1·C2/(C1+C2)（F；经串联口径单源实现）。"""
    c1 = _component(c1_f, "c1_f")
    c2 = _component(c2_f, "c2_f")
    return _series_caps((c1, c2))


def colpitts_frequency(l_h: float, c1_f: float, c2_f: float) -> float:
    """Colpitts 振荡频率 f = 1/(2π√(L·C_eq))，C_eq = C1·C2/(C1+C2)（Hz）。"""
    l_val = _component(l_h, "l_h")
    c_eq = colpitts_equivalent_cap(c1_f, c2_f)
    return 1.0 / (_TWO_PI * math.sqrt(l_val * c_eq))


@dataclass(frozen=True)
class ColpittsDesign:
    """Colpitts 反设计结果（字段语义见 colpitts_design）。"""

    f_hz: float
    l_h: float
    c_eq_f: float
    c1_f: float
    c2_f: float
    c_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "f_hz": self.f_hz,
            "l_h": self.l_h,
            "c_eq_f": self.c_eq_f,
            "c1_f": self.c1_f,
            "c2_f": self.c2_f,
            "c_ratio": self.c_ratio,
        }


def colpitts_design(f_hz: float, l_h: float, c_ratio: float) -> ColpittsDesign:
    """Colpitts 反设计：给目标频率 f、电感 L 与显式比值 r=C2/C1 → 元件值。

    C_eq = 1/((2πf)²L)；C1 = C_eq·(1+r)/r、C2 = C_eq·(1+r)。
    f_hz >0、l_h >0、c_ratio >0（否则 ValueError）。
    回路恒等式：colpitts_frequency(l_h, c1_f, c2_f)==f_hz（rel ~1e-15）。
    """
    f = _positive(f_hz, "f_hz")
    l_val = _component(l_h, "l_h")
    r = _positive(c_ratio, "c_ratio")
    c_eq = 1.0 / ((_TWO_PI * f) ** 2 * l_val)
    c1 = c_eq * (1.0 + r) / r
    c2 = c_eq * (1.0 + r)
    return ColpittsDesign(f_hz=f, l_h=l_val, c_eq_f=c_eq, c1_f=c1, c2_f=c2, c_ratio=r)


def hartley_equivalent_ind(l1_h: float, l2_h: float, m_h: float) -> float:
    """Hartley 等效电感 L_eq = L1+L2+2M（H；互感 M 显式，允许负=反绕）。"""
    l1 = _component(l1_h, "l1_h")
    l2 = _component(l2_h, "l2_h")
    m = _finite(m_h, "m_h")
    l_eq = l1 + l2 + 2.0 * m
    if l_eq <= 0.0:
        raise ValueError(f"L_eq = L1+L2+2M 必须 >0，实际 {l_eq!r}（互感过强反绕退化）")
    return l_eq


def hartley_frequency(l1_h: float, l2_h: float, m_h: float, c_f: float) -> float:
    """Hartley 振荡频率 f = 1/(2π√(L_eq·C))，L_eq = L1+L2+2M（Hz）。"""
    l_eq = hartley_equivalent_ind(l1_h, l2_h, m_h)
    c = _component(c_f, "c_f")
    return 1.0 / (_TWO_PI * math.sqrt(l_eq * c))


@dataclass(frozen=True)
class HartleyDesign:
    """Hartley 反设计结果（字段语义见 hartley_design）。"""

    f_hz: float
    c_f: float
    l_eq_h: float
    l1_h: float
    l2_h: float
    m_h: float
    k_coupling: float
    l_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "f_hz": self.f_hz,
            "c_f": self.c_f,
            "l_eq_h": self.l_eq_h,
            "l1_h": self.l1_h,
            "l2_h": self.l2_h,
            "m_h": self.m_h,
            "k_coupling": self.k_coupling,
            "l_ratio": self.l_ratio,
        }


def hartley_design(f_hz: float, c_f: float, l_ratio: float, k_coupling: float) -> HartleyDesign:
    """Hartley 反设计：给目标频率 f、电容 C、显式比值 r=L2/L1 与耦合系数 k → 元件值。

    L_eq = 1/((2πf)²C) = L1·(1+r+2k√r)（k=M/√(L1L2)）；L1 = L_eq/(1+r+2k√r)、
    L2 = r·L1、M = k·√(L1·L2)。|k| ≤ 1（否则 ValueError；|k|=1 全耦合合法）；
    分母 1+r+2k√r ≤ 0（如 r=1、k=−1）→ ValueError（退化，L_eq 非正）。
    """
    f = _positive(f_hz, "f_hz")
    c = _component(c_f, "c_f")
    r = _positive(l_ratio, "l_ratio")
    k = _finite(k_coupling, "k_coupling")
    if k < -1.0 or k > 1.0:
        raise ValueError(f"k_coupling 必须落在 [-1, 1]，实际 {k!r}")
    l_eq = 1.0 / ((_TWO_PI * f) ** 2 * c)
    denom = 1.0 + r + 2.0 * k * math.sqrt(r)
    if denom <= 0.0:
        raise ValueError(
            f"L_eq 归一分母 1+r+2k√r = {denom!r} ≤ 0（r={r!r}, k={k!r}）退化解，无物理元件值"
        )
    l1 = l_eq / denom
    l2 = r * l1
    m = k * math.sqrt(l1 * l2)
    return HartleyDesign(
        f_hz=f, c_f=c, l_eq_h=l_eq, l1_h=l1, l2_h=l2, m_h=m, k_coupling=k, l_ratio=r
    )


def clapp_frequency(l_h: float, c1_f: float, c2_f: float, c3_f: float) -> float:
    """Clapp 振荡频率 f = 1/(2π√(L·C_eq))，C_eq = 三电容串联（C3 主导口径）（Hz）。"""
    l_val = _component(l_h, "l_h")
    c_eq = _series_caps(
        (_component(c1_f, "c1_f"), _component(c2_f, "c2_f"), _component(c3_f, "c3_f"))
    )
    return 1.0 / (_TWO_PI * math.sqrt(l_val * c_eq))


@dataclass(frozen=True)
class ClappDesign:
    """Clapp 反设计结果（字段语义见 clapp_design）。"""

    f_hz: float
    l_h: float
    c_eq_f: float
    c1_f: float
    c2_f: float
    c3_f: float
    c_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "f_hz": self.f_hz,
            "l_h": self.l_h,
            "c_eq_f": self.c_eq_f,
            "c1_f": self.c1_f,
            "c2_f": self.c2_f,
            "c3_f": self.c3_f,
            "c_ratio": self.c_ratio,
        }


def clapp_design(f_hz: float, l_h: float, c_ratio: float, c3_f: float) -> ClappDesign:
    """Clapp 反设计：给目标频率 f、电感 L、比值 r=C2/C1 与串联电容 C3 → 元件值。

    C_eq = 1/((2πf)²L)；1/C1+1/C2 = 1/C_eq−1/C3 必须 >0（即 C3 > C_eq，
    否则三电容串联达不到目标 C_eq → ValueError）；C1 = (1+1/r)/S、
    C2 = r·C1，S = 1/C_eq−1/C3。Clapp 惯例 C3 ≪ C1,C2 时 C_eq≈C3
    （C3 主导调谐），本函数不强制该比例、由调用方按 C3 取值控制。
    """
    f = _positive(f_hz, "f_hz")
    l_val = _component(l_h, "l_h")
    r = _positive(c_ratio, "c_ratio")
    c3 = _component(c3_f, "c3_f")
    c_eq = 1.0 / ((_TWO_PI * f) ** 2 * l_val)
    s = 1.0 / c_eq - 1.0 / c3
    if s <= 0.0:
        raise ValueError(
            f"C3={c3!r} F 必须 > 目标 C_eq={c_eq!r} F（否则串联达不到目标等效电容）"
        )
    c1 = (1.0 + 1.0 / r) / s
    c2 = r * c1
    return ClappDesign(f_hz=f, l_h=l_val, c_eq_f=c_eq, c1_f=c1, c2_f=c2, c3_f=c3, c_ratio=r)


def cross_coupled_frequency(l_h: float, c_f: float) -> float:
    """交叉耦合 LC 振荡频率 f = 1/(2π√(L·C))（Hz；差分对每侧单端谐振腔口径）。"""
    return lc_resonant_frequency(l_h, c_f)


def cross_coupled_design(f_hz: float, l_h: float) -> float:
    """交叉耦合反设计：给目标频率 f 与电感 L → 谐振电容 C（F）。"""
    f = _positive(f_hz, "f_hz")
    l_val = _component(l_h, "l_h")
    return 1.0 / ((_TWO_PI * f) ** 2 * l_val)


def cross_coupled_negative_resistance(gm_s: float) -> float:
    """交叉耦合差分对基波负阻 R_n = −2/gm（Ω；gm 为单管跨导，S，必须 >0）。"""
    gm = _positive(gm_s, "gm_s")
    return -2.0 / gm


@dataclass(frozen=True)
class CrossCoupledStartup:
    """交叉耦合起振判据结果（字段语义见 cross_coupled_startup）。"""

    gm_s: float
    r_p_ohm: float
    oscillates: bool
    margin: float
    critical_gm_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "gm_s": self.gm_s,
            "r_p_ohm": self.r_p_ohm,
            "oscillates": self.oscillates,
            "margin": self.margin,
            "critical_gm_s": self.critical_gm_s,
        }


def cross_coupled_startup(gm_s: float, r_p_ohm: float) -> CrossCoupledStartup:
    """交叉耦合起振判据：gm·R_p ≥ 2（并联导纳口径 G_net = gm/2−1/R_p < 0）。

    gm_s：单管跨导（S，>=0，0=无跨导 → margin=−1 不起振）；r_p_ohm：
    谐振回路并联等效电阻（Ω，>0）。margin = 0.5·gm·R_p−1：>0 起振、
    ==0 恰临界（gm·R_p=2 恒等式，逐位）、<0 不起振。critical_gm_s =
    2/R_p。与负阻口径恒等：|R_n|=2/gm < R_p ⇔ margin>0。
    """
    gm = _nonneg(gm_s, "gm_s")
    r_p = _component(r_p_ohm, "r_p_ohm")
    margin = 0.5 * gm * r_p - 1.0
    return CrossCoupledStartup(
        gm_s=gm,
        r_p_ohm=r_p,
        oscillates=margin > 0.0,
        margin=margin,
        critical_gm_s=2.0 / r_p,
    )


@dataclass(frozen=True)
class MarginSweep:
    """起振裕度扫描结果（字段语义见 cross_coupled_margin_sweep）。"""

    gm_s: list[float]
    r_p_ohm: float
    margin: list[float]
    oscillates: list[bool]
    critical_gm_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "gm_s": list(self.gm_s),
            "r_p_ohm": self.r_p_ohm,
            "margin": list(self.margin),
            "oscillates": list(self.oscillates),
            "critical_gm_s": self.critical_gm_s,
        }


def cross_coupled_margin_sweep(gm_values: Any, r_p_ohm: float) -> MarginSweep:
    """起振裕度曲线：gm 数组 → margin=0.5·gm·R_p−1 逐点（向量化）。

    gm_values：跨导数组（S，一维、有限、≥0、长度 ≥1）；r_p_ohm 同上。
    返回逐点 margin 与 oscillates 旗标 + 临界跨导 critical_gm_s=2/R_p。
    """
    r_p = _component(r_p_ohm, "r_p_ohm")
    if isinstance(gm_values, (str, bytes)):
        raise ValueError("gm_values 必须是数值序列")
    if np.asarray(gm_values).dtype == bool:
        raise ValueError("gm_values 不接受布尔数组")
    arr = np.asarray(gm_values, dtype=float)
    if arr.ndim != 1 or arr.size < 1:
        raise ValueError(f"gm_values 必须是长度 ≥1 的一维数组，实际形状 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError("gm_values 含非有限值")
    if float(np.min(arr)) < 0.0:
        raise ValueError("gm_values 必须 >=0（跨导非负）")
    margins = 0.5 * arr * r_p - 1.0
    return MarginSweep(
        gm_s=[float(x) for x in arr],
        r_p_ohm=r_p,
        margin=[float(x) for x in margins],
        oscillates=[bool(x) for x in (margins > 0.0)],
        critical_gm_s=2.0 / r_p,
    )


# ─── 3. Leeson 相噪闭式 + 三段渐近幂律链 ────────────────────────────────────


@dataclass(frozen=True)
class LeesonResult:
    """Leeson 模型完整产出（字段语义见 leeson_model）。"""

    f0_hz: float
    q_l: float
    flicker_corner_hz: float
    noise_figure_lin: float
    p_s_w: float
    t0_k: float
    f_half_bw_hz: float
    f_flicker_hz: float
    floor_lin: float
    floor_dbc_hz: float
    f_min_hz: float
    f_max_hz: float
    segments: list[dict[str, float]]
    model_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "f0_hz": self.f0_hz,
            "q_l": self.q_l,
            "flicker_corner_hz": self.flicker_corner_hz,
            "noise_figure_lin": self.noise_figure_lin,
            "p_s_w": self.p_s_w,
            "t0_k": self.t0_k,
            "f_half_bw_hz": self.f_half_bw_hz,
            "f_flicker_hz": self.f_flicker_hz,
            "floor_lin": self.floor_lin,
            "floor_dbc_hz": self.floor_dbc_hz,
            "f_min_hz": self.f_min_hz,
            "f_max_hz": self.f_max_hz,
            "segments": [dict(seg) for seg in self.segments],
            "model_note": self.model_note,
        }


def leeson_floor_lin(noise_figure_lin: float, p_s_w: float, t0_k: float = T0_REF_K) -> float:
    """Leeson 平坦噪声底（线性功率谱密度，1/Hz）：F·k·T0/(2·P_s)。"""
    nf = _positive(noise_figure_lin, "noise_figure_lin")
    ps = _positive(p_s_w, "p_s_w")
    t0 = _positive(t0_k, "t0_k")
    return nf * K_B_SI * t0 / (2.0 * ps)


def leeson_floor_dbc(noise_figure_lin: float, p_s_w: float, t0_k: float = T0_REF_K) -> float:
    """Leeson 平坦噪声底（dBc/Hz）= 10·log10(F·k·T0/(2·P_s))。"""
    return 10.0 * math.log10(leeson_floor_lin(noise_figure_lin, p_s_w, t0_k))


def leeson_lin(
    df_hz: float,
    *,
    f0_hz: float,
    q_l: float,
    flicker_corner_hz: float,
    noise_figure_lin: float,
    p_s_w: float,
    t0_k: float = T0_REF_K,
) -> float:
    """Leeson 精确闭式（线性谱密度，1/Hz）：
    F·k·T0/(2·P_s)·(1+f_c/(2Δf))·(1+(f0/(2·Q_L·Δf))²)。

    df_hz：偏移频率（Hz，>0）；f0_hz：载波频率（Hz，>0）；q_l：有载 Q
    （>0）；flicker_corner_hz：器件 1/f 拐角（Hz，>=0，0=无闪烁项）；
    noise_figure_lin：线性噪声因子（>0，非 dB）；p_s_w：信号功率（W，
    >0）；t0_k：标准噪声温度（K，>0，缺省 290）。
    恒等式：Δf→f0/(2Q_L) 时第二括号=2（逐位）；Δf 远大于两有效拐角
    （浮点极限内）时结果==F·k·T0/(2·P_s)（逐位）。
    """
    df = _positive(df_hz, "df_hz")
    f0 = _positive(f0_hz, "f0_hz")
    q = _positive(q_l, "q_l")
    flick = _nonneg(flicker_corner_hz, "flicker_corner_hz")
    floor = leeson_floor_lin(noise_figure_lin, p_s_w, t0_k)
    c_flick = flick / 2.0
    c_half = f0 / (2.0 * q)
    return floor * (1.0 + c_flick / df) * (1.0 + (c_half / df) ** 2)


def leeson_l_dbc(
    df_hz: float,
    *,
    f0_hz: float,
    q_l: float,
    flicker_corner_hz: float,
    noise_figure_lin: float,
    p_s_w: float,
    t0_k: float = T0_REF_K,
) -> float:
    """Leeson 精确闭式（dBc/Hz）= 10·log10(leeson_lin(...))。"""
    return 10.0 * math.log10(
        leeson_lin(
            df_hz,
            f0_hz=f0_hz,
            q_l=q_l,
            flicker_corner_hz=flicker_corner_hz,
            noise_figure_lin=noise_figure_lin,
            p_s_w=p_s_w,
            t0_k=t0_k,
        )
    )


def leeson_sigma_phi2_exact(
    f1_hz: float,
    f2_hz: float,
    *,
    f0_hz: float,
    q_l: float,
    flicker_corner_hz: float,
    noise_figure_lin: float,
    p_s_w: float,
    t0_k: float = T0_REF_K,
) -> float:
    """Leeson 精确式的解析积分：σ_φ² = 2·∫[f1,f2] L_lin(Δf) dΔf（rad²）。

    乘积展开 F·k·T0/(2·P_s)·(1 + a/f + c²/f² + a·c²/f³)（a=f_c/2、
    c=f0/(2Q_L)）逐项闭式积分（斜率 0/−1/−2/−3 四条幂律，与
    clock_noise 可积族同族）——**不经三段渐近链**，无模型近似误差。
    f1_hz/f2_hz：偏移频率积分界（0<f1≤f2）；f1=f2 → 0.0（逐位）；
    f2<f1 → ValueError。
    """
    f0 = _positive(f0_hz, "f0_hz")
    q = _positive(q_l, "q_l")
    flick = _nonneg(flicker_corner_hz, "flicker_corner_hz")
    floor = leeson_floor_lin(noise_figure_lin, p_s_w, t0_k)
    f1 = _positive(f1_hz, "f1_hz")
    f2 = _positive(f2_hz, "f2_hz")
    if f2 < f1:
        raise ValueError(f"f2={f2!r} < f1={f1!r}（积分上限须 ≥ 下限）")
    if f2 == f1:
        return 0.0
    a = flick / 2.0
    c = f0 / (2.0 * q)
    c2 = c * c
    # ∫(floor·(1 + a/f + c²/f² + a·c²/f³)) df 逐项闭式
    integral = floor * (
        (f2 - f1)
        + a * math.log(f2 / f1)
        + c2 * (1.0 / f1 - 1.0 / f2)
        + a * c2 * 0.5 * (1.0 / (f1 * f1) - 1.0 / (f2 * f2))
    )
    return 2.0 * integral


def _leeson_corner_list(
    c_flick: float, c_half: float
) -> list[tuple[float, float]]:
    """有效拐角 →（f_c, 斜率）列表（严格递增；拐角重合塌缩为单拐角 −3）。"""
    if c_flick <= 0.0:
        return [(c_half, -2.0)]
    if c_flick == c_half:
        return [(c_flick, -3.0)]
    if c_flick < c_half:
        # 低段两括号全活（1/f³）；中间仅 1/f² 括号活；高段平坦
        return [(c_flick, -3.0), (c_half, -2.0)]
    # c_flick > c_half：中间仅闪烁括号活（1/f）
    return [(c_half, -3.0), (c_flick, -1.0)]


def _leeson_segments(
    floor_db: float, corners: list[tuple[float, float]], f_min: float, f_max: float
) -> list[dict[str, float]]:
    """拐角族 → 单链幂律段（角点连续锚定，契约与 clock_noise 段 dict 一致）。

    锚定算术与 clock_noise.build_power_law_segments 同序（自顶向下：
    L(末拐角)=白地板，L(f_ci)=L(f_c(i+1))+10·n_{i+1}·log10(f_ci/f_c(i+1))），
    使同输入两路径逐位一致（测试双路径钉，#118）。
    """
    corner_l = [0.0] * len(corners)
    corner_l[-1] = floor_db
    for i in range(len(corners) - 2, -1, -1):
        fc_up, n_up = corners[i + 1]
        corner_l[i] = corner_l[i + 1] + 10.0 * n_up * math.log10(corners[i][0] / fc_up)
    bounds = [f_min] + [fc for fc, _ in corners]
    segs: list[dict[str, float]] = []
    for i, (fc, slope) in enumerate(corners):
        segs.append(
            {
                "f_lo": bounds[i],
                "f_hi": bounds[i + 1],
                "slope": slope,
                "l_ref_dbc": corner_l[i],
                "f_ref": fc,
            }
        )
    segs.append(
        {
            "f_lo": corners[-1][0],
            "f_hi": f_max,
            "slope": 0.0,
            "l_ref_dbc": floor_db,
            "f_ref": corners[-1][0],
        }
    )
    return segs


def leeson_model(
    *,
    f0_hz: float,
    q_l: float,
    flicker_corner_hz: float,
    noise_figure_lin: float,
    p_s_w: float,
    f_min_hz: float,
    f_max_hz: float,
    t0_k: float = T0_REF_K,
) -> LeesonResult:
    """Leeson 模型总产出：精确闭式参数 + 三段渐近幂律段链（clock_noise 契约）。

    段链结构（渐近图像）：最低段两括号全活（斜率 −3）；两拐角之间单
    括号活（闪烁拐角更高 → −1；1/f² 拐角更高 → −2）；最高段白地板
    （斜率 0）。f_c=0 → 退化两段（−2 + 平坦）；两拐角重合 → 塌缩单
    拐角（−3 + 平坦）。f_min_hz 必须 < 最低有效拐角、f_max_hz 必须 >
    最高有效拐角（外区非零宽，否则 ValueError；与 clock_noise
    build_power_law_segments 契约一致）。

    诚实边界：段链是渐近近似模型（拐角过渡带内与精确式偏差可达 ~3 dB
    量级）；精确积分走 leeson_sigma_phi2_exact。
    """
    f0 = _positive(f0_hz, "f0_hz")
    q = _positive(q_l, "q_l")
    flick = _nonneg(flicker_corner_hz, "flicker_corner_hz")
    nf = _positive(noise_figure_lin, "noise_figure_lin")
    ps = _positive(p_s_w, "p_s_w")
    t0 = _positive(t0_k, "t0_k")
    f_min = _positive(f_min_hz, "f_min_hz")
    f_max = _positive(f_max_hz, "f_max_hz")
    if f_max <= f_min:
        raise ValueError(f"f_max_hz={f_max!r} 必须 > f_min_hz={f_min!r}")
    floor_lin = leeson_floor_lin(nf, ps, t0)
    floor_db = 10.0 * math.log10(floor_lin)
    c_flick = flick / 2.0
    c_half = f0 / (2.0 * q)
    corners = _leeson_corner_list(c_flick, c_half)
    if f_min >= corners[0][0]:
        raise ValueError(
            f"f_min_hz={f_min!r} 必须 < 最低有效拐角 {corners[0][0]!r}（最低幂律区非零宽）"
        )
    if f_max <= corners[-1][0]:
        raise ValueError(
            f"f_max_hz={f_max!r} 必须 > 最高有效拐角 {corners[-1][0]!r}（白地板区非零宽）"
        )
    segments = _leeson_segments(floor_db, corners, f_min, f_max)
    note = (
        "asymptotic piecewise power-law model (slopes -3 / between / 0); "
        "exact product form in leeson_lin / leeson_sigma_phi2_exact"
    )
    return LeesonResult(
        f0_hz=f0,
        q_l=q,
        flicker_corner_hz=flick,
        noise_figure_lin=nf,
        p_s_w=ps,
        t0_k=t0,
        f_half_bw_hz=c_half,
        f_flicker_hz=c_flick,
        floor_lin=floor_lin,
        floor_dbc_hz=floor_db,
        f_min_hz=f_min,
        f_max_hz=f_max,
        segments=segments,
        model_note=note,
    )


# ─── 4. DRO 耦合口径 ────────────────────────────────────────────────────────


def dro_loaded_q(q0: float, beta: float) -> float:
    """介质谐振器有载品质因数 Q_L = Q_0/(1+β)。

    q0：无载 Q（>0）；beta：外耦合系数（>=0，0=无耦合 → Q_L==Q_0 逐位、
    1=临界耦合 → Q_L==Q_0/2 逐位；负值 → ValueError）。
    """
    q0v = _positive(q0, "q0")
    beta_v = _nonneg(beta, "beta")
    return q0v / (1.0 + beta_v)


def dro_coupling_power(beta: float) -> dict[str, Any]:
    """介质谐振器外耦合功率分配：外耦合份额 β/(1+β)、腔内耗散 1/(1+β)。

    返回 dict：{"beta", "external_frac", "internal_frac", "critical_coupled"}
    （两份额之和=1；critical_coupled=beta==1.0 逐位判）。beta >=0。
    """
    beta_v = _nonneg(beta, "beta")
    denom = 1.0 + beta_v
    external = beta_v / denom
    internal = 1.0 / denom
    return {
        "beta": beta_v,
        "external_frac": external,
        "internal_frac": internal,
        "critical_coupled": beta_v == 1.0,
    }
