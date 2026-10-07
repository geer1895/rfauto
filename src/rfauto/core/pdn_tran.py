"""DR-7 PDN 瞬态纹波 + 推频相噪确定性内核（梯形负载电流谱 → V_pk-pk / L(f_m) 线谱）。

规格出处：规格深案 §C-5 DR-7（P1/M，2 天含 Xyce 窗）。
铁律 7：数值只在确定性内核——全部谱/纹波/相噪数字由本模块与
core/clock_noise.py 的确定性闭式产出；Xyce 网表渲染是纯文本面（不产数）。

链路（与规格一一对应）：
1. 梯形波形 schema ``{I_min, I_pk, T, t_r, t_f}``（TrapezoidCurrent，单位钉在
   字段名）→ 谐波谱：**解析包络**（导数法闭式，sinc 稳定化，trapezoid_harmonics）
   与 **FFT**（单周期采样 rfft/N，trapezoid_harmonics_fft）双路，一致性锚
   ≤1e-9（test_pdn_tran.py 钉，归一化到 ΔI）；
2. 谐波 × Z_pdn(f)（复用 core/pdn.py:pdn_impedance_profile / VrmModel /
   DecapSpec；自定义网络走 z_of_freq 闭式回调，如 z_parallel_rlc）→ IFFT →
   稳态纹波波形 → V_pk-pk（ripple_response）；SSO 上界快档保留
   （sso_bound_pp_v = 4·Σ|c_n·Z_n|，三角不等式严格上界，免 IFFT）；
3. Sφ：K_push（Hz/V，压控推频增益）确定性调制——纹波谐波 v_n 在偏移 f_m 处
   产生峰值频偏 Δf_n = K_push·v_n → 峰值相差 β_n = Δf_n/f_m → 单边带杂散
   L(f_m) = 10·log10(β_n²/4)（dBc/Hz，1 Hz 等效密度；IEEE 1139 杂散-相噪
   等效口径）→ clock_noise.phase_jitter_from_l（:214，INTERP_CONST 1 Hz 装填）
   收口出 σ_φ/jitter（push_jitter）。K_push 缺失（None）→ status=
   "awaiting_data" 不产数（规格风险条款：不虚构）。
4. Xyce 对照：render_tran_netlist 出 .TRAN 网表（负载电流 PWL 断点同 schema、
   并联 RLC 负载网络），schema 钉在 test_pdn_tran.py；真机对照由测试侧经
   adapters/xyce_adapter.run_xyce 驱动（core 层禁 import adapters——分层契约
   .importlinter），Xyce 不可达时对照面**如实降级登记**（网表生成+schema 钉
   仍交付，不虚报数值）。

数值口径：谐波系数 c_n 取 x(t) = Σ_n c_n·e^{+j2πnt/T} 约定（c_{−n}=conj(c_n)），
i_amp_n = 2|c_n|（峰-峰单谐波摆幅 2·i_amp_n）；Z(f) 与 core/pdn.py 同为
e^{+jωt} 口径，v_n = c_n·Z(f_n)；V_pk-pk 只含 AC 纹波（直流工作点 V_dc 由
DR-6 面负责，经 v_dc_offset_v 显式带入，缺省 0 不虚构）。

出处（#1c/#300 纪律）：
- 周期梯形脉冲串 Fourier 系数：本模块导数法闭式（dp/dt 矩形对 → 除以 j2πf），
  与任意标准教科书脉冲谱同构（对照锚=FFT 双路 ≤1e-9 + 单谐波逐位）；
- 电源杂散 → 相噪等效：β = Δf/f_m 的调相指数与 L = β²/4 单边带功率
  （IEEE Std 1139 口径的确定性杂散项；rms 相差 = β/√2）；
- 推频（supply pushing）：振荡器/时钟对电源纹波的 K_push 线性化模型，
  Efren de Sano 等时钟树文献谱系的标准一阶口径（确定性、模型无关）。

诚实边界（预声明）：
1. 稳态周期解（LTI + 周期激励的谐波稳态），不含启动瞬态与非线性 VRM 行为；
2. V_pk-pk 受 n_fft 网格分辨率限制（采样峰 ≤ 真峰，误差 ~ (π/n_fft)² 量级），
   精算时增大 n_fft；解析谐波和逐点式（test 内）可做真值互证；
3. β ≫ 1（大角度调制）时单边带闭式失效——small_angle_ok 如实置 False，
   不阻止计算但调用方不得采信（clock_noise 诚实边界④同族）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.clock_noise import (
    INTERP_CONST,
    PhaseJitterResult,
    phase_jitter_from_l,
    rms_jitter_s,
)
from rfauto.core.pdn import (
    DecapSpec,
    VrmModel,
    pdn_impedance_profile,
)

_TWO_PI = 2.0 * math.pi

#: 小角度调制门（β 低于此值单边带闭式可信；超门如实置 False 不阻止计算）
SMALL_ANGLE_BETA_MAX = 0.5

#: Sφ 装填 bin 半宽（Hz）：杂散按 1 Hz 等效密度装填 clock_noise（可配）
SPUR_BIN_HALF_WIDTH_HZ = 0.5


# ─── 梯形波形 schema ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrapezoidCurrent:
    """周期梯形负载电流 schema（规格键 {I_min, I_pk, T, t_r, t_f}，SI 单位）。

    波形（单周期，t=0 为上升沿起点）：i_min →（t_rise 线性）→ i_pk →
    （平顶 τ = T − t_rise − t_fall）→（t_fall 线性）→ i_min →保持到 T。

    Raises:
        ValueError: 参数非法（i_pk≤i_min、t_r/t_f≤0、t_r+t_f≥T、非有限）。
    """

    i_min_a: float
    i_pk_a: float
    t_period_s: float
    t_rise_s: float
    t_fall_s: float

    def __post_init__(self) -> None:
        vals = (self.i_min_a, self.i_pk_a, self.t_period_s, self.t_rise_s, self.t_fall_s)
        if not all(math.isfinite(float(v)) for v in vals):
            raise ValueError(f"梯形波形参数必须全为有限数，实际 {vals!r}")
        if float(self.i_pk_a) <= float(self.i_min_a):
            raise ValueError(
                f"i_pk_a 必须 > i_min_a（纯 DC 无瞬态语义），实际 {self.i_min_a!r}/{self.i_pk_a!r}"
            )
        if float(self.t_rise_s) <= 0.0 or float(self.t_fall_s) <= 0.0:
            raise ValueError(f"t_rise_s/t_fall_s 必须 >0，实际 {self.t_rise_s!r}/{self.t_fall_s!r}")
        if float(self.t_period_s) <= 0.0:
            raise ValueError(f"t_period_s 必须 >0，实际 {self.t_period_s!r}")
        if float(self.t_rise_s) + float(self.t_fall_s) >= float(self.t_period_s):
            raise ValueError(
                f"t_rise+t_fall ({self.t_rise_s!r}+{self.t_fall_s!r}) 必须 < T ({self.t_period_s!r}，"
                "平顶须非零宽——退化三角波不在 schema 内）"
            )

    @property
    def amplitude_a(self) -> float:
        """ΔI = I_pk − I_min（A）。"""
        return float(self.i_pk_a) - float(self.i_min_a)

    @property
    def tau_top_s(self) -> float:
        """平顶宽 τ = T − t_r − t_f（s，构造保证 >0）。"""
        return float(self.t_period_s) - float(self.t_rise_s) - float(self.t_fall_s)

    def waveform(self, t_s: Any) -> np.ndarray:
        """周期梯形波形求值（分段线性，np.interp；断点处逐位精确）。

        断点只取 4 个（0, t_r, t_r+τ, T）——t_r+τ 与 T−t_f 恒同值，若都写入
        xp 会成重复断点，np.interp 在重复点右侧取后值（i_min）使下降沿整段
        丢失为阶跃（实测双路对拍 1e-2 级假差根因）；4 断点形态下
        [t_r+τ, T] 段斜率 = −(i_pk−i_min)/t_f 恰为规定下降沿。
        """
        tt = np.mod(np.asarray(t_s, dtype=float), float(self.t_period_s))
        edges = (0.0, float(self.t_rise_s), float(self.t_rise_s) + self.tau_top_s,
                 float(self.t_period_s))
        vals = (float(self.i_min_a), float(self.i_pk_a), float(self.i_pk_a),
                float(self.i_min_a))
        return np.interp(tt, edges, vals)

    def to_dict(self) -> dict[str, float]:
        """schema 序列化（键即字段名，SI 单位；与规格 {I_min,I_pk,T,t_r,t_f} 一一对应）。"""
        return {
            "i_min_a": float(self.i_min_a),
            "i_pk_a": float(self.i_pk_a),
            "t_period_s": float(self.t_period_s),
            "t_rise_s": float(self.t_rise_s),
            "t_fall_s": float(self.t_fall_s),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TrapezoidCurrent:
        """schema 反序列化（缺键显式 KeyError 上抛，不虚构缺省）。"""
        return cls(
            i_min_a=raw["i_min_a"],
            i_pk_a=raw["i_pk_a"],
            t_period_s=raw["t_period_s"],
            t_rise_s=raw["t_rise_s"],
            t_fall_s=raw["t_fall_s"],
        )


# ─── 谐波谱（解析包络 + FFT 双路）────────────────────────────────────────────


@dataclass(frozen=True)
class HarmonicSpectrum:
    """单边谐波谱（n = 0..n_max；x(t) = Σ c_n e^{+j2πnt/T}，c_{−n}=conj(c_n)）。"""

    n: np.ndarray  # int
    f_hz: np.ndarray  # n/T
    c: np.ndarray  # 复系数 c_n（A）
    method: str  # "analytic" | "fft"

    @property
    def i_amp_a(self) -> np.ndarray:
        """谐波电流幅度 2|c_n|（n≥1 有效；n=0 为 DC 分量 |c_0|）。"""
        return 2.0 * np.abs(self.c)

    @property
    def dc_a(self) -> float:
        return float(np.real(self.c[0]))


def _rect_xform(f: np.ndarray, width: float, shift: float) -> np.ndarray:
    """矩形脉冲（宽 width、起点 shift）的 Fourier 变换稳定化闭式。

    (1−e^{−j2πf·w})/(j2πf)·e^{−j2πf·s} = w·e^{−j2πf(s+w/2)}·sinc(f·w)；
    np.sinc(x)=sin(πx)/(πx)，f→0 极限 = w（逐位稳定，无 0/0）。
    """
    arg = _TWO_PI * f
    return width * np.exp(-1j * arg * (shift + width / 2.0)) * np.sinc(f * width)


def _pulse_xform(f: np.ndarray, trap: TrapezoidCurrent, amplitude: float) -> np.ndarray:
    """单梯形脉冲（幅度 amplitude，t=0 起上升）的 Fourier 变换 X(f)。

    导数法：dp/dt = (a/t_r)·rect[0,t_r] − (a/t_f)·rect[t_r+τ, t_r+τ+t_f]，
    D(f) = 两个矩形变换的线性和；X(f) = D(f)/(j2πf)；f=0 极限 = 面积
    a·(t_r/2 + τ + t_f/2)。
    """
    f_arr = np.atleast_1d(np.asarray(f, dtype=float))
    amp = float(amplitude)
    d = (amp / float(trap.t_rise_s)) * _rect_xform(f_arr, float(trap.t_rise_s), 0.0)
    d -= (amp / float(trap.t_fall_s)) * np.exp(-1j * _TWO_PI * f_arr * (float(trap.t_rise_s) + trap.tau_top_s)) \
        * _rect_xform(f_arr, float(trap.t_fall_s), 0.0)
    out = np.empty_like(d)
    dc = amp * (float(trap.t_rise_s) / 2.0 + trap.tau_top_s + float(trap.t_fall_s) / 2.0)
    nz = f_arr != 0.0
    out[nz] = d[nz] / (1j * _TWO_PI * f_arr[nz])
    out[~nz] = dc
    return out


def trapezoid_harmonics(trap: TrapezoidCurrent, n_max: int) -> HarmonicSpectrum:
    """梯形负载电流谐波谱——解析包络闭式（导数法，见 _pulse_xform）。

    c_n = X(n/T)/T（X 为单个 ΔI 幅度梯形脉冲的 Fourier 变换）；c_0 为
    周期平均（DC 分量，含 i_min 基座）。n_max ≥ 1。
    """
    n = int(n_max)
    if n < 1:
        raise ValueError(f"n_max 必须 ≥1，实际 {n_max!r}")
    f_n = np.arange(n + 1, dtype=float) / float(trap.t_period_s)
    x_pulse = _pulse_xform(f_n, trap, trap.amplitude_a)
    mean = float(trap.i_min_a) + x_pulse[0] / float(trap.t_period_s)
    c = x_pulse / float(trap.t_period_s)
    c[0] = mean
    return HarmonicSpectrum(n=np.arange(n + 1), f_hz=f_n, c=c, method="analytic")


def trapezoid_harmonics_fft(trap: TrapezoidCurrent, n_fft: int) -> HarmonicSpectrum:
    """梯形负载电流谐波谱——FFT 路（单周期 n_fft 点采样 rfft/n_fft）。

    n_fft 必须为偶数且 ≥ 16（Nyquist bin = n_fft/2，n=0..n_fft/2 有效）；
    波形为分段线性，np.interp 采样在断点处逐位精确。
    """
    n_f = int(n_fft)
    if n_f < 16 or n_f % 2 != 0:
        raise ValueError(f"n_fft 必须为偶数且 ≥16，实际 {n_fft!r}")
    t = np.arange(n_f, dtype=float) * float(trap.t_period_s) / n_f
    samples = trap.waveform(t)
    c = np.fft.rfft(samples) / n_f
    n = np.arange(c.size)
    return HarmonicSpectrum(n=n, f_hz=n.astype(float) / float(trap.t_period_s), c=c, method="fft")


# ─── 负载网络闭式（Xyce 对照与解析锚用）──────────────────────────────────────


def z_parallel_rlc(
    f: float | Sequence[float] | np.ndarray, r_ohm: float, l_henry: float, c_farad: float
) -> np.ndarray:
    """并联 RLC（R∥L∥C 对地）阻抗闭式 Z = 1/(1/R + jωC + 1/(jωL))。

    DR-7 解析锚网络（与 render_tran_netlist 的 R1/L1/C1 三元件对地并联
    逐位同构）；f > 0（与 core/pdn._freq_array 同口径）。
    """
    freqs = np.atleast_1d(np.asarray(f, dtype=float))
    if np.any(freqs <= 0.0) or not np.all(np.isfinite(freqs)):
        raise ValueError(f"f 必须全为正有限数，实际 {freqs!r}")
    r = float(r_ohm)
    lh = float(l_henry)
    cap = float(c_farad)
    if not (math.isfinite(r) and r > 0.0 and math.isfinite(lh) and lh > 0.0
            and math.isfinite(cap) and cap > 0.0):
        raise ValueError(f"R/L/C 必须为正有限数，实际 {r!r}/{lh!r}/{cap!r}")
    omega = _TWO_PI * freqs
    y = 1.0 / r + 1j * (omega * cap - 1.0 / (omega * lh))
    return 1.0 / y


# ─── 纹波响应（×Z_pdn → IFFT → V_pk-pk）─────────────────────────────────────


def _default_n_fft(n_max: int) -> int:
    """缺省 n_fft：≥ max(64, 16·n_max) 的最小 2 幂（峰采样误差 ~(π/N)² 量级）。"""
    target = max(64, 16 * int(n_max))
    return 1 << max(6, (target - 1).bit_length())


@dataclass(frozen=True)
class RippleResult:
    """纹波响应结果（字段语义见 ripple_response）。"""

    v_pkpk_v: float
    v_rms_v: float  # AC 纹波 rms（Parseval Σ 2|v_n|²，不含 DC）
    sso_bound_pp_v: float  # SSO 上界快档 4·Σ|v_n|（三角不等式严格上界）
    v_dc_offset_v: float
    n_max: int
    n_fft: int
    f_hz: np.ndarray  # 谐波频率（n=1..n_max）
    i_amp_a: np.ndarray  # 谐波电流幅度 2|c_n|
    v_amp_v: np.ndarray  # 谐波电压幅度 2|c_n·Z_n|
    t_s: np.ndarray  # 波形采样时刻（单周期，[0,T)）
    v_t: np.ndarray  # 纹波波形（含 v_dc_offset）

    def as_dict(self) -> dict[str, Any]:
        return {
            "v_pkpk_v": self.v_pkpk_v,
            "v_rms_v": self.v_rms_v,
            "sso_bound_pp_v": self.sso_bound_pp_v,
            "v_dc_offset_v": self.v_dc_offset_v,
            "n_max": self.n_max,
            "n_fft": self.n_fft,
        }


def ripple_response(
    trap: TrapezoidCurrent,
    *,
    n_max: int,
    z_of_freq: Callable[[np.ndarray], np.ndarray] | None = None,
    vrm: VrmModel | None = None,
    bulk_caps: Sequence[DecapSpec | tuple[float, ...]] | None = None,
    decaps: Sequence[DecapSpec | tuple[float, ...]] | None = None,
    n_fft: int | None = None,
    v_dc_offset_v: float = 0.0,
) -> RippleResult:
    """梯形负载 × PDN 阻抗 → 稳态纹波（谐波乘 Z_n → IFFT → V_pk-pk）。

    Z 来源二选一：z_of_freq 闭式回调（返回与 f 同长复数组），或
    vrm/bulk_caps/decaps（复用 core/pdn.py pdn_impedance_profile，规格
    pdn.py:668 面）。两者都不给 → ValueError（不虚构负载）。

    n_fft：IFFT 周期采样点数（偶数，须 ≥ 2·n_max+2 使 n_max 落在非 Nyquist
    bin）；缺省 _default_n_fft。v_dc_offset_v：直流工作点（DR-6 面产出，
    显式带入；缺省 0 = 纯 AC 纹波口径）。
    """
    n = int(n_max)
    if n < 1:
        raise ValueError(f"n_max 必须 ≥1，实际 {n_max!r}")
    n_f = int(n_fft) if n_fft is not None else _default_n_fft(n)
    if n_f % 2 != 0 or n_f < 2 * n + 2:
        raise ValueError(f"n_fft 必须为偶数且 ≥ 2·n_max+2={2 * n + 2}，实际 {n_f!r}")
    v_dc = float(v_dc_offset_v)
    if not math.isfinite(v_dc):
        raise ValueError(f"v_dc_offset_v 必须为有限数，实际 {v_dc_offset_v!r}")

    spec = trapezoid_harmonics(trap, n)
    f_h = spec.f_hz[1:]
    c_h = spec.c[1:]
    if z_of_freq is not None:
        z_h = np.asarray(z_of_freq(f_h), dtype=complex)
        if z_h.shape != f_h.shape:
            raise ValueError(f"z_of_freq 返回形状 {z_h.shape} ≠ f 形状 {f_h.shape}")
    elif vrm is not None or bulk_caps is not None or decaps is not None:
        z_h = np.asarray(pdn_impedance_profile(vrm, bulk_caps, decaps, f_h), dtype=complex)
    else:
        raise ValueError("必须给 z_of_freq 或 vrm/bulk_caps/decaps 之一（不虚构负载网络）")

    v_h = c_h * z_h  # 电压谐波系数（n≥1）
    spectrum = np.zeros(n_f // 2 + 1, dtype=complex)
    spectrum[1:n + 1] = n_f * v_h
    spectrum[0] = n_f * v_dc
    v_t = np.fft.irfft(spectrum, n=n_f)
    v_pkpk = float(v_t.max() - v_t.min())
    v_rms = float(np.sqrt(np.sum(2.0 * np.abs(v_h) ** 2)))
    sso_bound = float(4.0 * np.sum(np.abs(v_h)))
    t_s = np.arange(n_f, dtype=float) * float(trap.t_period_s) / n_f
    return RippleResult(
        v_pkpk_v=v_pkpk,
        v_rms_v=v_rms,
        sso_bound_pp_v=sso_bound,
        v_dc_offset_v=v_dc,
        n_max=n,
        n_fft=n_f,
        f_hz=f_h,
        i_amp_a=spec.i_amp_a[1:],
        v_amp_v=2.0 * np.abs(v_h),
        t_s=t_s,
        v_t=v_t,
    )


# ─── Sφ：K_push 确定性调制 → L(f_m) 线谱 → clock_noise 收口 ─────────────────


@dataclass(frozen=True)
class PushLine:
    """单条推频杂散线谱（closed form 见模块 docstring）。"""

    f_offset_hz: float
    v_amp_v: float
    beta_rad: float  # 峰值相差 β = K_push·v/f_m
    l_dbc_per_hz: float  # 10·log10(β²/4)（1 Hz 等效密度，dBc/Hz）
    s_phi_equiv_rad2_per_hz: float  # β²/4


@dataclass(frozen=True)
class PushPhaseNoiseResult:
    """推频线谱结果（K_push 缺失 → status="awaiting_data"，lines 空，不产数）。"""

    status: str  # "ok" | "awaiting_data"
    k_push_hz_per_v: float | None
    lines: tuple[PushLine, ...]
    small_angle_ok: bool  # 全部 β < SMALL_ANGLE_BETA_MAX

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "k_push_hz_per_v": self.k_push_hz_per_v,
            "small_angle_ok": self.small_angle_ok,
            "lines": [
                {
                    "f_offset_hz": ln.f_offset_hz,
                    "v_amp_v": ln.v_amp_v,
                    "beta_rad": ln.beta_rad,
                    "l_dbc_per_hz": ln.l_dbc_per_hz,
                    "s_phi_equiv_rad2_per_hz": ln.s_phi_equiv_rad2_per_hz,
                }
                for ln in self.lines
            ],
        }


def _push_inputs(v_amp_v: Sequence[float], f_offset_hz: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    v = np.atleast_1d(np.asarray(v_amp_v, dtype=float))
    f = np.atleast_1d(np.asarray(f_offset_hz, dtype=float))
    if v.ndim != 1 or f.ndim != 1 or v.shape != f.shape or v.size < 1:
        raise ValueError(f"v_amp_v/f_offset_hz 须为一维同长非空数组，实际 {v.shape}/{f.shape}")
    if np.any(v <= 0.0) or not np.all(np.isfinite(v)):
        raise ValueError(f"v_amp_v 须全为正有限数（零幅谐波不是线谱成员，调用方过滤），实际 {v!r}")
    if np.any(f <= 0.0) or not np.all(np.isfinite(f)) or np.any(np.diff(f) <= 0.0):
        raise ValueError(f"f_offset_hz 须严格递增正数（偏移频率口径），实际 {f!r}")
    return v, f


def push_phase_noise(
    v_amp_v: Sequence[float],
    f_offset_hz: Sequence[float],
    k_push_hz_per_v: float | None,
) -> PushPhaseNoiseResult:
    """纹波谐波 → 推频杂散线谱 L(f_m)（闭式，见模块 docstring；不产数条款）。

    Args:
        v_amp_v: 各纹波谐波电压幅度（V，2|v_n|，非负）。
        f_offset_hz: 对应偏移频率（Hz，严格递增正数；= 载波 ± n/T 的 |f_m|）。
        k_push_hz_per_v: 推频增益（Hz/V）；**None → status="awaiting_data"，
            lines 为空，不产出任何物理数字**（规格风险条款：K_push 缺如实的）。

    Returns:
        PushPhaseNoiseResult。
    """
    v, f = _push_inputs(v_amp_v, f_offset_hz)
    if k_push_hz_per_v is None:
        return PushPhaseNoiseResult(
            status="awaiting_data", k_push_hz_per_v=None, lines=(), small_angle_ok=True)
    k = float(k_push_hz_per_v)
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(f"k_push_hz_per_v 必须为正有限数（无推频请勿调用，不产 −inf 线谱），实际 {k_push_hz_per_v!r}")
    beta = k * v / f
    lines = tuple(
        PushLine(
            f_offset_hz=float(f[i]),
            v_amp_v=float(v[i]),
            beta_rad=float(beta[i]),
            l_dbc_per_hz=float(10.0 * np.log10(beta[i] ** 2 / 4.0)),
            s_phi_equiv_rad2_per_hz=float(beta[i] ** 2 / 4.0),
        )
        for i in range(v.size)
    )
    return PushPhaseNoiseResult(
        status="ok",
        k_push_hz_per_v=k,
        lines=lines,
        small_angle_ok=bool(np.all(beta < SMALL_ANGLE_BETA_MAX)),
    )


@dataclass(frozen=True)
class PushJitterResult:
    """push_jitter 输出：线谱 + clock_noise 收口的相噪/抖动（awaiting 时 jitter=None）。"""

    push: PushPhaseNoiseResult
    phase_jitter: PhaseJitterResult | None
    sigma_phi2_closed_rad2: float | None  # 闭式 Σβ²/2（rms 口径；awaiting 时 None）

    def as_dict(self) -> dict[str, Any]:
        return {
            "push": self.push.as_dict(),
            "phase_jitter": None if self.phase_jitter is None else self.phase_jitter.to_dict(),
            "sigma_phi2_closed_rad2": self.sigma_phi2_closed_rad2,
        }


def push_jitter(
    v_amp_v: Sequence[float],
    f_offset_hz: Sequence[float],
    k_push_hz_per_v: float | None,
    f_carrier_hz: float | None = None,
) -> PushJitterResult:
    """推频线谱 → σ_φ/jitter（clock_noise.phase_jitter_from_l 收口，规格 :214/:366 面）。

    装填口径：每条杂散按 1 Hz 等效密度（SPUR_BIN_HALF_WIDTH_HZ=0.5 半宽）
    逐条喂 phase_jitter_from_l（INTERP_CONST 段积分为 clock_noise 侧解析闭式）
    并求和——杂散 bin 互不相连（间距须 >1 Hz），clock_noise 单链口径要求
    连续覆盖，故**逐条积分再求和**（闭式和的浮点等价，禁造 gap 谱密度）；
    rms 抖动经 clock_noise.rms_jitter_s（:205）换算。闭式对：σ_φ² =
    2·Σ(β²/4)·1 = Σβ²/2（rms 相差口径，与闭式 ~1e-16 相对一致）。
    K_push 缺失 → phase_jitter/sigma 闭式均 None（不产数）。
    """
    push = push_phase_noise(v_amp_v, f_offset_hz, k_push_hz_per_v)
    if push.status == "awaiting_data":
        return PushJitterResult(push=push, phase_jitter=None, sigma_phi2_closed_rad2=None)
    hw = SPUR_BIN_HALF_WIDTH_HZ
    fm = np.array([ln.f_offset_hz for ln in push.lines])
    if float(fm[0]) - hw <= 0.0:
        raise ValueError(f"最低杂散 {fm[0]!r} Hz 须 > {hw!r} Hz（装填 bin 不得触及 f=0）")
    if fm.size > 1 and np.any(np.diff(fm) <= 2.0 * hw):
        raise ValueError(f"杂散间距须 > {2 * hw!r} Hz（装填 bin 禁重叠），实际 {fm!r}")
    sigma2 = 0.0
    n_seg = 0
    for ln in push.lines:
        res_ln = phase_jitter_from_l(
            np.array([ln.f_offset_hz - hw, ln.f_offset_hz + hw]),
            np.array([ln.l_dbc_per_hz]),
            interp=INTERP_CONST,
        )
        sigma2 += res_ln.sigma_phi2_rad2
        n_seg += res_ln.n_segments
    sigma = math.sqrt(sigma2)
    carrier: float | None = None
    jitter: float | None = None
    if f_carrier_hz is not None:
        carrier = float(f_carrier_hz)
        jitter = rms_jitter_s(sigma, carrier)
    phase_jitter = PhaseJitterResult(
        f1_hz=float(fm[0] - hw),
        f2_hz=float(fm[-1] + hw),
        interp=INTERP_CONST,
        n_segments=n_seg,
        sigma_phi2_rad2=sigma2,
        sigma_phi_rad=sigma,
        sigma_phi_deg=math.degrees(sigma),
        f_carrier_hz=carrier,
        jitter_s=jitter,
    )
    sigma2_closed = float(sum(ln.beta_rad ** 2 for ln in push.lines) / 2.0)
    return PushJitterResult(push=push, phase_jitter=phase_jitter, sigma_phi2_closed_rad2=sigma2_closed)


# ─── Xyce .TRAN 对照网表（纯文本渲染，不产数；真机驱动在测试侧）───────────────


def _num(value: float) -> str:
    """SI 纯指数字面量（%.17g 双精度往返无损；与 adapters/xyce_adapter._num
    同口径——文本模板复制非数值内核重复，core 层禁 import adapters）。"""
    v = float(value)
    if v == 0.0:
        v = 0.0
    return f"{v:.17g}"


def render_tran_netlist(
    trap: TrapezoidCurrent,
    *,
    r_ohm: float,
    l_henry: float,
    c_farad: float,
    n_periods: int,
    t_step_s: float | None = None,
    print_node: str = "1",
    title: str = "rfauto DR-7 pdn tran ripple xyce cross-check",
) -> str:
    """渲染 PDN 瞬态纹波 Xyce 网表（负载电流 PWL 同 schema + 并联 RLC 负载）。

    结构：``I1 1 0 PWL(...)``（梯形负载电流逐周期断点，PWL 段间线性 = 梯形
    逐位同 schema）∥ ``R1 1 0`` ∥ ``L1 1 0`` ∥ ``C1 1 0`` → ``.tran`` →
    ``.print tran v(out)``。t_step 缺省 T/1000；t_stop = n_periods·T
    （末周期判稳态纹波峰峰，由消费方截取）。非 ASCII 标题在写盘 ascii 编码时
    显式报错（#89 口径）。
    """
    for name, val in (("r_ohm", r_ohm), ("l_henry", l_henry), ("c_farad", c_farad)):
        v = float(val)
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"{name} 必须为正有限数，实际 {val!r}")
    n_p = int(n_periods)
    if n_p < 1:
        raise ValueError(f"n_periods 必须 ≥1，实际 {n_periods!r}")
    t_step = float(trap.t_period_s) / 1000.0 if t_step_s is None else float(t_step_s)
    if not math.isfinite(t_step) or t_step <= 0.0 or t_step > float(trap.t_period_s):
        raise ValueError(f"t_step_s 须 (0, T]，实际 {t_step_s!r}")
    i_min, i_pk = float(trap.i_min_a), float(trap.i_pk_a)
    t_r, tau, t_f = float(trap.t_rise_s), trap.tau_top_s, float(trap.t_fall_s)
    period = float(trap.t_period_s)
    pts: list[str] = []
    for k in range(n_p):
        base = k * period
        pts.extend([
            f"{_num(base)} {_num(i_min)}",
            f"{_num(base + t_r)} {_num(i_pk)}",
            f"{_num(base + t_r + tau)} {_num(i_pk)}",
            f"{_num(base + t_r + tau + t_f)} {_num(i_min)}",
        ])
    t_stop = n_p * period
    pts.append(f"{_num(t_stop)} {_num(i_min)}")
    lines = [
        f"* {title}",
        f"I1 1 0 PWL({' '.join(pts)})",
        f"R1 1 0 {_num(r_ohm)}",
        f"L1 1 0 {_num(l_henry)}",
        f"C1 1 0 {_num(c_farad)}",
        f".tran {_num(t_step)} {_num(t_stop)}",
        f".print tran v({print_node})",
        ".end",
        "",
    ]
    return "\n".join(lines)
