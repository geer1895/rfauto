"""NGSolve 开源 FEM 频域适配器（最小实现）。

事实基线（真机确证，非假设）：NGSolve 6.2.2607 Windows
cp312 wheel 可装可用，HCurl 时谐 Maxwell 可建可解（PEC 立方腔特征模
o2 闭式 rel_err 0.31%）；**端口激励与 S 参数无现成 API**（dir() 236 名
零命中）——本适配器的端口/S 参数链路为自研，覆盖面如实声明：

- 首案例 ``parallel_plate``：平行板 TEM 传输线 2 端口（照 COMSOL 首案例
  模式，comsol_adapter.py）：PEC 上下板 + 侧壁自然 BC（PMC）+ 两端
  **解析 TEM 模态 Robin 端口**。闭式精确可对照：εeff=εr（TEM）、
  Z0=η0/√εr·H/W、S 矩阵 = 均匀线段 ABCD→S（tl_section_sparams）。
- 端口提取（自研，最小 TEM 口径）：**行波分解**——线内 5 个采样面
  （0.3L–0.7L 中心线，避开端口面凋落场）采 E_z → 模电压 V(x)=H·E_z，
  最小二乘拟合 V(x)=c₊e^{jkx}+c₋e^{−jkx}（NGSolve e^{−iωt} 约定，
  前向=+e^{jkx}）→ 波变量 a=(V+Zref·I)/(2√Zref) → S 矩阵。
  仅覆盖单模 TEM（高阶模在 W=6mm 板宽下截止 17GHz，工作带内不存在）；
  数值 eigenmode 端口仍未实现（解析模态端口见下）。
- 第二案例 ``rect_waveguide``（P2⑫）：矩形波导 TE10 模端口 + 真 2×2
  多端口（逐端口激励轮转）。端口 = **解析 TE10 模态 Robin**（自研，无
  eigenmode 求解）：边界项 ``C = −j·β(f)·γ(f)``、``γ(f) = Z_TE10(f)/Zref``
  ——边界项携带**模态传播常数 β**（TEM 案例的 −jkγ 中 k 恰为 TEM 的 β，
  同一口径的模态推广；γ=Z_modal/Zref 时模态负载恰为 Zref，Γ=(1−γ)/(1+γ)
  与 TEM 真机实证公式同构）；截止及以下显式 ValueError 拒绝。
  闭式锚：WR-90（a=22.86/b=10.16mm 空气）fc=6.5571GHz、
  Z_TE10@10GHz=498.97Ω、β=√(k²−(π/a)²)。
- 模电压提取（波导模）：**模剖面内积**——V(x)=b·Ê，
  Ê=Σ E_z·sin(πy/a) / Σ sin²(πy/a)（多点加权最小二乘投影，纯模精确）。
  TEM 的单点 E_z·H 采样是剖面为常数的特例；TE10 的 E_z∝sin(πy/a)
  单点采样会随 y 剧烈变化（节点处恒零），必须用剖面投影。
  纵向 0.3L–0.7L 五面窗与 wave_decompose 沿用。
- 多端口最小增量：逐端口激励轮转——同频 BilinearForm 组装一次、
  umfpack 分解一次、N 个 RHS 各回代一次（NGSolve 进程内合法；
  #208 是 openEMS Run(cleanup=True) 特有坑不适用）。每次激励读全部
  端口波变量装配真 S 列（sparams_column_from_waves），S22/S12 不再
  借用对称/互易假设（假设只留在 parallel_plate 旧路径，其锁定测试
  口径原样保留）。
- 相位/符号约定：与 TEM 链完全一致（NGSolve e^{−iωt} 解取共轭、
  a1=−E_INC/√Zref、激励 G=2jβγE_INC/b·sin(πy/a) 剖面口径）；验证由
  闭式全 2×2 复数逐元对照门承载（|ΔS|≤0.02，实测预期 ≪1e-3 量级）。
- 边界条件（真机实证锚定）：NGSolve 边界积分项
  ``a += C·(u.Trace()*v.Trace())*ds`` 对应自然 BC 为
  **n×curlE − C·E_t = G**（注意符号：C=+jkγ 实测给出反阻负载
  Γ=(1+γ)/(1−γ)，C=−jkγ 才是 n×curlE + jkγE_t = g 吸收/负载侧）。
  第一类 Robin（γ=1）对 TEM 垂直入射**精确**吸收；γ=Z0/Zref 时边界
  恰为 Zref 集中负载（TEM 精确）——两端口 γ=Z0/Zref 即实现标准
  S 参数测量条件（源/负载均匹配 Zref），闭式对照逐频全复数验证。
- 相位约定（真机锚定）：NGSolve 为 e^{−iωt} 约定，输出统一转工程
  e^{+jωt}（Touchstone/HFSS 口径）＝对解取共轭；激励波变量参考
  a1=−E_INC/√Zref（求解器约定下的源相位，闭式逐频验证钉死）。

默认几何刻意取 Z0≈30Ω ≠ Zref=50Ω：S11 闭式 |Γ|=0.25 非平凡，对照门
有区分度（全匹配线的 S11≈0 门抓不出提取链错误）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
    EMSolverType,
    SolverCapabilities,
    get_global_registry,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
C0 = 299792458.0
ETA0 = 376.730313668  # 自由空间波阻抗 Ω

TEMPLATE_NAME = "parallel_plate"
TEMPLATE_WAVEGUIDE = "rect_waveguide"
SUPPORTED_TEMPLATES: tuple[str, ...] = (TEMPLATE_NAME, TEMPLATE_WAVEGUIDE)

# 首案例默认参数（mm）：Z0 = η0/√2.1·(0.6924/6) ≈ 30Ω，刻意与 Zref=50Ω
# 失配（Γ=(30−50)/(30+50)=−0.25）——闭式非平凡对照，见模块 docstring。
PARALLEL_PLATE_DEFAULTS: dict[str, float] = {
    "length_mm": 20.0,
    "width_mm": 6.0,
    "height_mm": 0.6924,
    "eps_r": 2.1,
    "z_ref_ohm": 50.0,
}
E_INC = 1.0  # 入射模电压振幅 [V]（归一化基准，S 为比值不受其影响）
DEFAULT_MESH_MAXH_MM = 0.4  # 真机收敛档（o2 下闭式对照 <1e-3，实证）
DEFAULT_ORDER = 2
N_SAMPLE_PLANES = 5  # 行波采样面数（0.3L–0.7L 均布）
SAMPLE_WINDOW = (0.3, 0.7)  # 采样窗（避开端口面凋落场）
# rect_waveguide 默认参数（WR-90 空气）：闭式锚 fc=6.5571GHz、
# Z_TE10@10GHz=498.97Ω（te10_* 独立锚测试钉死）；段长 40mm≈λg@10GHz，
# S11/S21 相位非平凡。带内 8.2–12.4GHz 由 freq_ghz/freq_range 给出。
RECT_WAVEGUIDE_DEFAULTS: dict[str, float] = {
    "a_mm": 22.86,   # 宽边内尺寸（TE10 截止 fc=c/(2a√εr)）
    "b_mm": 10.16,   # 窄边内尺寸（E 场极化方向高度）
    "length_mm": 40.0,
    "eps_r": 1.0,
    "z_ref_ohm": 50.0,
}
WAVEGUIDE_MESH_MAXH_MM = 2.0  # TE10 剖面收敛档：宽边半正弦 ≥11 单元（o2）
N_Y_SAMPLES = 9  # 宽边模剖面采样点数（剖面内积加权最小二乘）

#: 闭式对照门（确定性判据；真跑测试消费）。εeff 的门控由闭式全复数
#: S 对照承载（相位含在内），不设独立门——失配线下 S21 相位斜率直接
#: 拟合有偏（见 solve() 内注释），斜率数字只作诊断如实报告。
GATE_S_MAX_ABS_ERR = 0.02  # |S_fem − S_闭式| 复数逐元 ≤ 0.02（−34dB）
PASSIVITY_TOL = 1e-3  # 无源性：逐端口 Σ_j|S_ij|² ≤ 1 + PASSIVITY_TOL（无耗=1+离散容差）


def ngsolve_installed() -> bool:
    """ngsolve/netgen 是否可导入（不触发 import）。"""
    return (importlib.util.find_spec("ngsolve") is not None
            and importlib.util.find_spec("netgen") is not None)


# ── 纯函数：参数映射 / 闭式 / 提取数学（确定性内核，可无 NGSOLVE 单测）────────

def normalize_parallel_plate_params(params: dict[str, Any] | None) -> dict[str, float]:
    """平行板模板参数规范化：补默认、转 float、正数校验。"""
    spec = dict(PARALLEL_PLATE_DEFAULTS)
    for key, value in (params or {}).items():
        if key in PARALLEL_PLATE_DEFAULTS:
            spec[key] = float(value)
    for key, value in spec.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"parallel_plate 参数 {key} 必须为正数，得到 {value}")
    return spec


def parallel_plate_z0(width_mm: float, height_mm: float, eps_r: float) -> float:
    """平行板 TEM 线特性阻抗闭式：Z0 = η0/√εr · (H/W)。"""
    return ETA0 / math.sqrt(eps_r) * (height_mm / width_mm)


def robin_gamma(z_line_ohm: float, z_ref_ohm: float) -> float:
    """TEM 模态 Robin 端口系数 γ = Z0/Zref。

    物理口径：n×curlE + jkγE_t = g 的均匀边界对 TEM 垂直入射表现为
    集中阻抗 Z0/γ（γ=1 吸收匹配；γ=Z0/Zref 时边界=Zref 负载）。
    """
    z_line, z_ref = float(z_line_ohm), float(z_ref_ohm)
    if not (math.isfinite(z_line) and math.isfinite(z_ref)) or z_line <= 0 or z_ref <= 0:
        raise ValueError(
            f"robin_gamma 需要正有限阻抗，得到 Z0={z_line}, Zref={z_ref}")
    return z_line / z_ref


def resolve_freq_points(config: EMSolverConfig,
                        params: dict[str, Any] | None) -> list[float]:
    """频点：params['freq_ghz'] 显式列表优先，否则 freq_range_ghz 等分
    extra_params['n_freq']（默认 4）个点。"""
    explicit = (params or {}).get("freq_ghz")
    if explicit is not None:
        pts = [float(f) for f in np.atleast_1d(np.asarray(explicit, dtype=float))]
        if not pts or any(f <= 0 for f in pts):
            raise ValueError("freq_ghz 必须为非空正数列表")
        return pts
    n = int((config.extra_params or {}).get("n_freq", 4))
    lo, hi = config.freq_range_ghz
    return [float(f) for f in np.linspace(lo, hi, max(n, 1))]


def tl_section_sparams(freq_ghz: np.ndarray, eps_eff: float, z_line: float,
                       length_mm: float, z_ref: float = 50.0) -> np.ndarray:
    """无耗均匀传输线段闭式 S 矩阵（ABCD→S，按 z_ref 归一）。shape (n,2,2)。

    工程 e^{+jωt} 约定（与 comsol_adapter.tl_section_sparams 同一条闭式，
    本地副本保持适配器自包含——adapters 间不互引）。
    """
    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    beta_l = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / C0 * (length_mm * 1e-3)
    a = np.cos(beta_l)
    b = 1j * z_line * np.sin(beta_l)
    c = 1j * np.sin(beta_l) / z_line
    d = a
    denom = a * z_ref + b + c * z_ref * z_ref + d * z_ref
    s = np.zeros((len(f_hz), 2, 2), dtype=complex)
    s[:, 0, 0] = (a * z_ref + b - c * z_ref * z_ref - d * z_ref) / denom
    s[:, 1, 1] = s[:, 0, 0]
    s[:, 1, 0] = 2.0 * z_ref / denom
    s[:, 0, 1] = s[:, 1, 0]
    return s


def parallel_plate_closed_form(spec: dict[str, float],
                               freq_ghz: np.ndarray) -> np.ndarray:
    """平行板 TEM 线闭式 S 矩阵（εeff=εr 精确，Z0 由几何闭式）。"""
    z0 = parallel_plate_z0(spec["width_mm"], spec["height_mm"], spec["eps_r"])
    return tl_section_sparams(freq_ghz, spec["eps_r"], z0, spec["length_mm"],
                              z_ref=spec["z_ref_ohm"])


def excitation_coef(k_rad_m: float, gamma: float, e_inc: float,
                    height_m: float) -> complex:
    """端口 1 激励 RHS 系数 G1（场量，V/m²）：G1 = 2jkγ·E_INC/H。

    推导口径（见模块 docstring 约定）：边界方程 n×curlE + jkγE_t = G1·ẑ，
    G1=2jkγE_INC/H ⟺ Thevenin 源 Vs=2·E_INC、内阻 Zref（a1=E_INC/√Zref
    的工程幅值；波变量参考相位 a1=−E_INC/√Zref 由
    :func:`sparams_from_waves` 内钉死）。
    """
    if height_m <= 0:
        raise ValueError(f"height_m 必须为正，得到 {height_m}")
    return 2j * k_rad_m * gamma * float(e_inc) / float(height_m)


def wave_decompose(voltages: np.ndarray, x_samples_m: np.ndarray,
                   k_rad_m: float) -> tuple[complex, complex]:
    """行波分解：V(x)=c₊e^{jkx}+c₋e^{−jkx} 最小二乘拟合（复 lstsq）。

    输入为各采样面模电压（V）；返回 (c_plus, c_minus)（NGSolve e^{−iωt}
    约定下 c_plus 为 +x 前向行波幅值）。欠定/坏输入显式报错。
    """
    v = np.asarray(voltages, dtype=complex).ravel()
    x = np.asarray(x_samples_m, dtype=float).ravel()
    if v.size < 2 or x.size != v.size:
        raise ValueError(f"行波分解至少需 2 个匹配采样点，得到 {v.size}/{x.size}")
    if not np.isfinite(k_rad_m) or k_rad_m <= 0:
        raise ValueError(f"k_rad_m 必须为正有限，得到 {k_rad_m}")
    mat = np.vstack([np.exp(1j * k_rad_m * x),
                     np.exp(-1j * k_rad_m * x)]).T
    coef, *_ = np.linalg.lstsq(mat, v, rcond=None)
    return complex(coef[0]), complex(coef[1])


def port_waves_to_b(c_plus: complex, c_minus: complex, k_rad_m: float,
                    length_m: float, z_line_ohm: float,
                    z_ref_ohm: float) -> tuple[complex, complex]:
    """线内行波幅值 → 两端口 b 变量（Zref 归一）。

    链路（真机闭式锚定）：
    - 模电压/电流：V(x)=c₊e^{jkx}+c₋e^{−jkx}，I(x)=(c₊e^{jkx}−c₋e^{−jkx})/Z0
      （端口 2 参考面 x=L 处 I 取入网方向 = −I_line(L)）；
    - 波变量（Zref 归一）：b_p=(V_p−Zref·I_p)/(2√Zref)。

    sparams_from_waves（TEM 旧路径）与 sparams_column_from_waves
    （P2⑫ 真 S 列）共用本函数，保证两条输出同源不漂移。
    """
    z_line, z_ref = float(z_line_ohm), float(z_ref_ohm)
    if z_line <= 0 or z_ref <= 0:
        raise ValueError("z_line/z_ref 必须为正数")
    if length_m <= 0:
        raise ValueError(f"length_m 必须为正数，得到 {length_m}")
    e1 = complex(np.exp(1j * k_rad_m * length_m))
    e2 = complex(np.exp(-1j * k_rad_m * length_m))
    cp, cm = complex(c_plus), complex(c_minus)
    v1 = cp + cm
    i1 = (cp - cm) / z_line
    v2 = cp * e1 + cm * e2
    i2 = -(cp * e1 - cm * e2) / z_line
    sqrt_z = math.sqrt(z_ref)
    b1 = (v1 - z_ref * i1) / (2.0 * sqrt_z)
    b2 = (v2 - z_ref * i2) / (2.0 * sqrt_z)
    return b1, b2


def sparams_from_waves(c_plus: complex, c_minus: complex, k_rad_m: float,
                       length_m: float, z_line_ohm: float, z_ref_ohm: float,
                       e_inc: float = E_INC) -> np.ndarray:
    """行波幅值 → 2 端口 S 矩阵（工程 e^{+jωt} 约定输出）。

    前两元素（S11/S21）为端口 1 激励的真测量；后两元素为**几何镜像
    对称 + 互易假设**填充（parallel_plate 旧路径专用口径，锁定测试
    钉死）。真 2×2 无假设测量走 sparams_column_from_waves ×逐端口
    激励轮转（rect_waveguide）。激励参考 a1=−E_INC/√Zref（负号来自
    RHS 系数 G 的相位映射，真机闭式逐频验证钉死）；NGSolve
    e^{−iωt} → 工程 e^{+jωt}：对 b/a 取共轭（Touchstone/HFSS 口径）。
    """
    b1, b2 = port_waves_to_b(c_plus, c_minus, k_rad_m, length_m, z_line_ohm,
                             z_ref_ohm)
    sqrt_z = math.sqrt(float(z_ref_ohm))
    a1 = -float(e_inc) / sqrt_z
    s = np.zeros((2, 2), dtype=complex)
    s[0, 0] = np.conj(b1 / a1)
    s[1, 0] = np.conj(b2 / a1)
    s[1, 1] = s[0, 0]  # 几何镜像对称（parallel_plate 结构对称）
    s[0, 1] = s[1, 0]  # 互易（无源互易介质）
    return s


def sparams_column_from_waves(c_plus: complex, c_minus: complex,
                              k_rad_m: float, length_m: float,
                              z_line_ohm: float, z_ref_ohm: float,
                              e_inc: float = E_INC) -> np.ndarray:
    """单次激励的完整 S 列 [S_1p, S_2p]（**无对称/互易假设**）。

    多端口增量（P2⑫）：每端口各激励一次，每次激励由同一线内行波分解
    同时给出全部端口的 b 变量 → 真 S 列；与 sparams_from_waves 的前
    两个元素逐位一致（该函数后两个元素是假设填充，仅 TEM 旧路径保留）。
    shape (2,)，工程 e^{+jωt} 约定输出（a1=−E_INC/√Zref 同锁定口径）。
    """
    b1, b2 = port_waves_to_b(c_plus, c_minus, k_rad_m, length_m, z_line_ohm,
                             z_ref_ohm)
    sqrt_z = math.sqrt(float(z_ref_ohm))
    a1 = -float(e_inc) / sqrt_z
    return np.array([np.conj(b1 / a1), np.conj(b2 / a1)], dtype=complex)


def extract_eps_eff(freq_ghz: np.ndarray, s21: np.ndarray,
                    length_mm: float) -> float:
    """由 S21 解缠相位斜率反推有效介电常数：φ=−βL，β=2πf√εeff/c。

    输入须为工程 e^{+jωt} 约定 S21（适配器输出已转）；与
    comsol_adapter.extract_eps_eff 同一条确定性口径（adapters 间不互引，
    本地副本）。
    """
    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    if f_hz.size < 2:
        raise ValueError("至少需要 2 个频点才能拟合相位斜率")
    phase = np.unwrap(np.angle(np.asarray(s21)))
    slope = float(np.polyfit(f_hz, phase, 1)[0])  # rad/Hz
    if slope >= 0:
        raise ValueError(f"S21 相位斜率非负（{slope:.3e} rad/Hz），无法解释为 "
                         "−βL 传播相位——检查输入是否为工程约定 S21")
    sqrt_eps = -slope * C0 / (2.0 * np.pi * length_mm * 1e-3)
    return float(sqrt_eps * sqrt_eps)


# ── TE10 矩形波导闭式（P2⑫；均匀无耗填充、主模口径，可无 NGSOLVE 单测）──────

def te10_fc_ghz(a_mm: float, eps_r: float = 1.0) -> float:
    """TE10 截止频率闭式：fc = c/(2a√εr)（GHz；a=宽边内尺寸 mm）。"""
    a_m, eps = float(a_mm) * 1e-3, float(eps_r)
    if (not (math.isfinite(a_m) and math.isfinite(eps))
            or a_m <= 0 or eps <= 0):
        raise ValueError(
            f"te10_fc_ghz 需要 a_mm>0、eps_r>0，得到 a={a_mm}, εr={eps_r}")
    return C0 / (2.0 * a_m * math.sqrt(eps)) / 1e9


def te10_beta(freq_ghz: float, fc_ghz: float, eps_r: float = 1.0) -> float:
    """TE10 相位常数：β = k√(1−(fc/f)²)，k=2πf√εr/c（rad/m）。

    截止及以下（f≤fc）显式 ValueError——低于截止无传播解，禁止把
    β≤0 静默喂进 wave_decompose（其 k_rad_m>0 守卫的语义上游）。
    """
    f, fc, eps = float(freq_ghz), float(fc_ghz), float(eps_r)
    if (not (math.isfinite(f) and math.isfinite(fc) and math.isfinite(eps))
            or f <= 0 or fc <= 0 or eps <= 0):
        raise ValueError(
            f"te10_beta 需要正有限频率，得到 f={freq_ghz}, fc={fc_ghz}, εr={eps_r}")
    if f <= fc:
        raise ValueError(
            f"工作频率 {f:.6g}GHz ≤ TE10 截止频率 {fc:.6g}GHz：截止以下无传播解，"
            "显式拒绝（不产静默垃圾）")
    k = 2.0 * math.pi * f * 1e9 * math.sqrt(eps) / C0
    ratio = fc / f
    return k * math.sqrt(1.0 - ratio * ratio)


def te10_wave_impedance(freq_ghz: float, fc_ghz: float,
                        eta_medium: float = ETA0) -> float:
    """TE 模波阻抗：Z_TE = η/√(1−(fc/f)²)（Ω；η=介质波阻抗，空气填 η0）。

    截止及以下显式 ValueError（Z_TE→∞ 无定义，拒绝静默垃圾）。
    """
    f, fc, eta = float(freq_ghz), float(fc_ghz), float(eta_medium)
    if (not (math.isfinite(f) and math.isfinite(fc) and math.isfinite(eta))
            or f <= 0 or fc <= 0 or eta <= 0):
        raise ValueError(
            f"te10_wave_impedance 需要正有限输入，得到 f={freq_ghz}, "
            f"fc={fc_ghz}, η={eta_medium}")
    if f <= fc:
        raise ValueError(
            f"工作频率 {f:.6g}GHz ≤ TE10 截止频率 {fc:.6g}GHz：截止以下 Z_TE "
            "无定义，显式拒绝")
    ratio = fc / f
    return eta / math.sqrt(1.0 - ratio * ratio)


def dispersive_section_sparams(freq_ghz: np.ndarray, beta_rad_m: np.ndarray,
                               z_line_ohm: np.ndarray, length_mm: float,
                               z_ref: float = 50.0) -> np.ndarray:
    """色散均匀线段闭式 S 矩阵（ABCD→S，β/Z 逐频数组）。shape (n,2,2)。

    与 tl_section_sparams 同一条 ABCD 代数（无耗线段，工程 e^{+jωt}），
    区别仅在接受逐频 β(f)、Z(f) 数组——矩形波导 TE10 色散段用；
    tl_section 的标量 εeff 签名及其锁定测试不动。
    """
    f_hz = np.asarray(freq_ghz, dtype=float)
    beta = np.asarray(beta_rad_m, dtype=float)
    z_line = np.asarray(z_line_ohm, dtype=float)
    if f_hz.ndim != 1 or beta.shape != f_hz.shape or z_line.shape != f_hz.shape:
        raise ValueError("freq_ghz/beta_rad_m/z_line_ohm 须为同长一维数组")
    if not float(length_mm) > 0:
        raise ValueError(f"length_mm 必须为正数，得到 {length_mm}")
    if np.any(z_line <= 0) or not np.all(np.isfinite(z_line)):
        raise ValueError("z_line_ohm 必须全为正有限")
    if not float(z_ref) > 0:
        raise ValueError(f"z_ref 必须为正数，得到 {z_ref}")
    theta = beta * (float(length_mm) * 1e-3)
    a_ = np.cos(theta)
    b_ = 1j * z_line * np.sin(theta)
    c_ = 1j * np.sin(theta) / z_line
    d_ = a_
    denom = a_ * z_ref + b_ + c_ * z_ref * z_ref + d_ * z_ref
    s = np.zeros((len(f_hz), 2, 2), dtype=complex)
    s[:, 0, 0] = (a_ * z_ref + b_ - c_ * z_ref * z_ref - d_ * z_ref) / denom
    s[:, 1, 1] = s[:, 0, 0]  # 均匀无耗线段本身对称/互易（闭式精确，非假设）
    s[:, 1, 0] = 2.0 * z_ref / denom
    s[:, 0, 1] = s[:, 1, 0]
    return s


def normalize_rect_waveguide_params(
        params: dict[str, Any] | None) -> dict[str, float]:
    """矩形波导模板参数规范化：补默认、转 float、正数校验 + TE10 前提 a>b。"""
    spec = dict(RECT_WAVEGUIDE_DEFAULTS)
    for key, value in (params or {}).items():
        if key in RECT_WAVEGUIDE_DEFAULTS:
            spec[key] = float(value)
    for key, value in spec.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"rect_waveguide 参数 {key} 必须为正数，得到 {value}")
    if spec["a_mm"] <= spec["b_mm"]:
        raise ValueError(
            f"TE10 主模要求宽边 a>窄边 b，得到 a={spec['a_mm']}, b={spec['b_mm']}")
    return spec


def rect_waveguide_closed_form(spec: dict[str, float],
                               freq_ghz: np.ndarray) -> np.ndarray:
    """矩形波导 TE10 色散段闭式 S 矩阵（shape (n,2,2)）。

    Z_line=Z_TE10(f)、β=te10_beta（任一频点≤截止显式 ValueError）；
    端口测量条件=Zref 模态负载（γ=Z_TE/Zref）⟹ 对照 ABCD 闭式按
    z_ref=Zref 归一。独立锚：WR-90 fc=6.5571GHz、Z_TE@10GHz=498.97Ω。
    """
    fc = te10_fc_ghz(spec["a_mm"], spec["eps_r"])
    f = np.asarray(freq_ghz, dtype=float)
    if f.size == 0 or np.any(f <= 0):
        raise ValueError("freq_ghz 必须为非空正数列表")
    if float(f.min()) <= fc:
        raise ValueError(
            f"频点 {float(f.min()):.6g}GHz 低于 TE10 截止 {fc:.6g}GHz"
            "（含截止以下频点，显式拒绝）")
    eta = ETA0 / math.sqrt(spec["eps_r"])
    beta = np.array([te10_beta(float(x), fc, spec["eps_r"]) for x in f])
    z_te = np.array([te10_wave_impedance(float(x), fc, eta) for x in f])
    return dispersive_section_sparams(f, beta, z_te, spec["length_mm"],
                                      z_ref=spec["z_ref_ohm"])


def modal_voltage_te10(e_z_samples: np.ndarray, y_samples_m: np.ndarray,
                       a_mm: float, b_mm: float) -> complex:
    """TE10 模电压（模剖面内积）：V = b·Ê，Ê = Σ E_z·w / Σ w²，w=sin(πy/a)。

    离散加权最小二乘 = 剖面投影：纯 TE10 剖面（E_z=Ê·sin）精确恢复 Ê，
    与采样点数/位置无关（只要不全落节点）；凋落高阶模与剖面正交被抑制。
    TEM 的 V=H·E_z 单点采样是剖面为常数的特例——波导模 E_z∝sin(πy/a)
    单点采样随 y 剧烈变化（节点恒零），必须用剖面内积（P2⑫ D 项）。
    """
    ez = np.asarray(e_z_samples, dtype=complex).ravel()
    ys = np.asarray(y_samples_m, dtype=float).ravel()
    a_m, b_m = float(a_mm) * 1e-3, float(b_mm) * 1e-3
    if ez.size < 1 or ez.size != ys.size:
        raise ValueError(
            f"模电压投影需匹配的非空采样，得到 E:{ez.size}/y:{ys.size}")
    if (not (math.isfinite(a_m) and math.isfinite(b_m))
            or a_m <= 0 or b_m <= 0):
        raise ValueError(f"a_mm/b_mm 必须为正，得到 a={a_mm}, b={b_mm}")
    w = np.sin(math.pi * ys / a_m)
    denom = float(np.dot(w, w))
    if denom <= 1e-15:
        raise ValueError("采样点全部落在模剖面节点（sin≈0），无法投影")
    return b_m * complex(np.dot(w, ez) / denom)


# ── 适配器 ────────────────────────────────────────────────────────────────────

class NGSolveAdapter(EMSolverAdapter):
    """NGSolve 频域 FEM 适配器（EMSolverAdapter 契约，最小 TEM 面）。

    生命周期：connect（查 ngsolve 可导入）→ build_geometry（规范化参数、
    落 spec 证据）→ solve（逐频：建网格/组装/直接解/行波提取）→
    get_sparams → close（无外部进程/内存常驻，清引用）。

    extra_params：order（HCurl 阶，默认 2）、n_freq（等分频点数，默认 4）、
    mesh_maxh_mm（默认 0.4，收敛档）。
    """

    param_semantics: ClassVar[dict[str, dict[str, str]]] = {
        TEMPLATE_NAME: {
            "length_mm": "平行板 TEM 线长（x 向传播长度，决定 S21 相位 −βL）",
            "width_mm": "板宽（y 向，与 H 一起决定 Z0）",
            "height_mm": "板间距（z 向，E 极化方向；模电压 V=H·E_z 积分路径）",
            "eps_r": "板间介质相对介电常数（TEM：εeff=εr 精确）",
            "z_ref_ohm": "模态 Robin 端口负载/参考阻抗（两端口同值=标准 S "
                         "参数测量条件）",
        },
        TEMPLATE_WAVEGUIDE: {
            "a_mm": "波导宽边内尺寸（TE10 截止 fc=c/(2a√εr)；默认 WR-90 "
                    "22.86mm，锚 6.5571GHz）",
            "b_mm": "波导窄边内尺寸（E 场极化方向高度；默认 WR-90 10.16mm；"
                    "TE10 主模要求 a>b）",
            "length_mm": "传播方向段长（S21 相位 = −β(f)L，色散；默认 "
                         "40mm≈λg@10GHz）",
            "eps_r": "均匀填充相对介电常数（β/Z_TE/fc 同受 √εr 标度；空气=1）",
            "z_ref_ohm": "TE10 模态 Robin 端口负载/参考阻抗（γ=Z_TE/Zref，"
                         "两端口同值=标准 S 参数测量条件）",
        },
    }

    # A5 能力声明（如实，逐行核对；A5 纪律：不得虚报）：
    #   - 端口：解析模态 Robin 端口（自研）——P2⑫ 起 rect_waveguide 提供
    #     TE10 波导模端口（C=−jβγ，γ=Z_TE/Zref）→ supports_wave_port=True
    #     （COMSOL 数值模端口过锚翻真同口径；数值 eigenmode 端口仍无）；
    #     集总端口无实现 → False；
    #   - 材料：PEC 壁（HCurl Dirichlet）+ 无耗介质 → 无 lossy；
    #   - 场导出：无场导出实现 → False；收敛报告/optimetrics/nf2ff/SAR
    #     无实现 → False；
    #   - Touchstone：无导出实现 → False（supported_output_formats 只报
    #     csv，6g 遗留默认口径被本类显式覆盖）；
    #   - 并行：单进程直接解，不透传并行开关 → 空元组；
    #   - license：NGSolve LGPL-2.1 开源 → False。
    CAPABILITIES: ClassVar[SolverCapabilities] = SolverCapabilities(
        solver_type="ngsolve",
        supports_wave_port=True,
        supports_lumped_port=False,
        supports_field_export=False,
        supports_convergence_report=False,
        supports_touchstone_export=False,
        supports_headless_solve=True,
        supports_optimetrics=False,
        dimension="3d",
        material_models=("pec", "lossless_dielectric"),
        parallel_backends=(),
        supports_sar=False,
        supports_nf2ff=False,
        supports_lumped_elements=False,
        supported_templates=SUPPORTED_TEMPLATES,
        requires_license=False,
        availability_gate="pip:ngsolve",
    )

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        ep = config.extra_params or {}
        self._order = int(ep.get("order", DEFAULT_ORDER))
        self._mesh_maxh_mm = float(ep.get("mesh_maxh_mm", DEFAULT_MESH_MAXH_MM))
        self._working_dir = Path(config.working_dir or "runs/ngsolve")
        self._template: str = TEMPLATE_NAME
        self._spec: dict[str, float] | None = None
        self._freqs_ghz: list[float] | None = None
        self._result: EMSolverResult | None = None

    # ── 可用性 / 连接 ────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        """ngsolve+netgen 可导入即可用（开源 wheel，无 license/外部进程）。"""
        return ngsolve_installed()

    def connect(self) -> bool:
        """连接=可用性确认（真正 import 推迟到 solve，惰性）。"""
        if not self.is_available():
            return False
        self._connected = True
        return True

    # ── 建模输入 ─────────────────────────────────────────────────────────────
    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """规范化模板参数并落 spec 证据（真正的网格/求解在 solve 内）。

        geometry: {"template": "parallel_plate", "params": {...,
                   freq_ghz: [...]}}
        """
        if not self._connected:
            return False
        template = str(geometry.get("template", TEMPLATE_NAME))
        if template not in SUPPORTED_TEMPLATES:
            logger.error("NGSolve 适配器暂不支持模板 %s（支持: %s）",
                         template, SUPPORTED_TEMPLATES)
            return False
        try:
            if template == TEMPLATE_WAVEGUIDE:
                self._spec = normalize_rect_waveguide_params(
                    geometry.get("params") or {})
            else:
                self._spec = normalize_parallel_plate_params(
                    geometry.get("params") or {})
            self._freqs_ghz = resolve_freq_points(self._config,
                                                  geometry.get("params") or {})
        except (TypeError, ValueError) as exc:
            logger.error("NGSolve 参数无效: %s", exc)
            return False
        self._template = template
        if (template == TEMPLATE_WAVEGUIDE
                and "mesh_maxh_mm" not in (self._config.extra_params or {})):
            # TE10 剖面收敛档：宽边半正弦 ≥11 单元（o2）；显式 extra_params 优先
            self._mesh_maxh_mm = WAVEGUIDE_MESH_MAXH_MM
        self._working_dir.mkdir(parents=True, exist_ok=True)
        if template == TEMPLATE_WAVEGUIDE:
            fc = te10_fc_ghz(self._spec["a_mm"], self._spec["eps_r"])
            eta = ETA0 / math.sqrt(self._spec["eps_r"])
            f_mid = float(np.median(self._freqs_ghz))
            in_band = f_mid > fc  # 低于截止仍可 build（solve 显式拒绝），诊断置 None
            z_te_mid = te10_wave_impedance(f_mid, fc, eta) if in_band else 0.0
            spec_doc: dict[str, Any] = {
                "template": template,
                "params": self._spec,
                "freq_ghz": self._freqs_ghz,
                "te10_fc_ghz": round(fc, 6),
                "te10_z_mid_ohm": round(z_te_mid, 4) if in_band else None,
                "te10_beta_mid_rad_m": round(
                    te10_beta(f_mid, fc, self._spec["eps_r"]), 4)
                if in_band else None,
                "robin_gamma_mid": round(
                    robin_gamma(z_te_mid, self._spec["z_ref_ohm"]), 6)
                if in_band else None,
                "port_convention": ("解析 TE10 模态 Robin 端口（边界项 C=-jβγ、"
                                    "γ=Z_TE/Zref；两端口同 γ = 源/负载均 Zref "
                                    "的标准 S 参数测量条件；逐端口激励轮转装配"
                                    "真 2×2，无对称/互易假设）"),
                "order": self._order,
                "mesh_maxh_mm": self._mesh_maxh_mm,
            }
        else:
            z0 = parallel_plate_z0(self._spec["width_mm"],
                                   self._spec["height_mm"],
                                   self._spec["eps_r"])
            spec_doc = {
                "template": template,
                "params": self._spec,
                "freq_ghz": self._freqs_ghz,
                "closed_form_z0_ohm": round(z0, 4),
                "robin_gamma": round(robin_gamma(z0, self._spec["z_ref_ohm"]), 6),
                "port_convention": ("解析 TEM 模态 Robin 端口（n×curlE + jkγE_t = g，"
                                    "γ=Z0/Zref；两端口同 γ = 源/负载均 Zref 的标准 "
                                    "S 参数测量条件）"),
                "order": self._order,
                "mesh_maxh_mm": self._mesh_maxh_mm,
            }
        (self._working_dir / "ngsolve_spec.json").write_text(
            json.dumps(spec_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    # ── 求解 ─────────────────────────────────────────────────────────────────
    def solve(self) -> EMSolverResult:
        """逐频 HCurl 直接解 + 行波提取；异常 → success=False。"""
        if not self._connected or self._spec is None or self._freqs_ghz is None:
            return EMSolverResult(success=False, message="未连接或未构建几何")
        if self._template == TEMPLATE_WAVEGUIDE:
            return self._solve_rect_waveguide()
        t0 = time.time()
        try:
            freq_ghz, s, extra = self._solve_parallel_plate()
        except Exception as exc:
            wall = time.time() - t0
            logger.error("NGSolve 求解失败: %s", exc)
            return EMSolverResult(success=False, wall_time_s=round(wall, 1),
                                  message=f"NGSolve 求解失败: {exc}")
        wall = time.time() - t0
        self._write_csv(freq_ghz, s)
        s_ref = parallel_plate_closed_form(self._spec,
                                           np.asarray(freq_ghz, dtype=float))
        err11 = float(np.abs(s[:, 0, 0] - s_ref[:, 0, 0]).max())
        err21 = float(np.abs(s[:, 1, 0] - s_ref[:, 1, 0]).max())
        # εeff 门控由闭式全复数 S 对照承载（相位含在内）：S21 相位残差
        # δφ ≤ |ΔS21|/|S21|min ⟹ εeff 相对误差 ≤ 2δφ/(β_max·L)。
        # S21 相位斜率直接拟合在失配线（Z0≠Zref）下有偏（分母
        # j(Z0+Zref²/Z0)sinβL 的相位非线性，实测 +6.2%）——只作诊断，
        # 与 comsol mline run7 如实记录的 +4.8% 偏差同族。
        s21_abs_min = float(np.abs(s[:, 1, 0]).min())
        phi_res = err21 / max(s21_abs_min, 1e-12)
        f_max_hz = float(np.max(freq_ghz)) * 1e9
        beta_max = 2.0 * np.pi * f_max_hz * math.sqrt(self._spec["eps_r"]) / C0
        eps_bound = 2.0 * phi_res / max(beta_max * self._spec["length_mm"] * 1e-3,
                                        1e-15)
        try:
            eps_diag = extract_eps_eff(np.asarray(freq_ghz), s[:, 1, 0],
                                       self._spec["length_mm"])
        except ValueError:
            eps_diag = float("nan")
        field_data = {
            "template": TEMPLATE_NAME,
            "solver": "ngsolve HCurl 时谐 Maxwell（直接解 umfpack）",
            "port_type": "解析 TEM 模态 Robin（γ=Z0/Zref，两端口）",
            "extraction": (f"行波分解 LS 拟合（{N_SAMPLE_PLANES} 面，"
                           f"{SAMPLE_WINDOW[0]}L–{SAMPLE_WINDOW[1]}L）"),
            "phase_convention": "工程 e^{+jωt}（求解器 e^{−iωt} 解取共轭）",
            "closed_form_z0_ohm": round(parallel_plate_z0(
                self._spec["width_mm"], self._spec["height_mm"],
                self._spec["eps_r"]), 4),
            "eps_eff_rel_err_bound": eps_bound,
            "eps_eff_slope_diagnostic": eps_diag,
            "eps_eff_slope_note": ("失配线下 S21 相位斜率有偏（分母相位非线"
                                   "性），仅诊断；εeff 门控=闭式全复数 S 对照"),
            "s11_max_abs_err": err11,
            "s21_max_abs_err": err21,
            "gates": {"s_max_abs_err": GATE_S_MAX_ABS_ERR},
            **extra,
        }
        ok = (err11 <= GATE_S_MAX_ABS_ERR and err21 <= GATE_S_MAX_ABS_ERR)
        self._result = EMSolverResult(
            success=True, freq_ghz=np.asarray(freq_ghz, dtype=float), s_params=s,
            field_data=field_data, wall_time_s=round(wall, 1),
            message=(f"NGSolve 频域求解完成（{TEMPLATE_NAME}，{len(freq_ghz)} 频点；"
                     f"闭式对照 |ΔS11|≤{err11:.2e} |ΔS21|≤{err21:.2e} "
                     f"εeff 相对误差 ≤{eps_bound:.2e}"
                     f"{'，门全过' if ok else '，有门未过（如实）'}）"),
        )
        return self._result

    def _solve_parallel_plate(self) -> tuple[list[float], np.ndarray, dict[str, Any]]:
        """真机链路：netgen.occ 盒子+命名面 → HCurl 逐频解 → 行波提取。

        API/符号约定全部真机实证（探针闭式对照逐频全复数
        <1e-3）：见模块 docstring。惰性 import——无 ngsolve 环境显式报错。
        """
        if not ngsolve_installed():
            raise RuntimeError(
                "ngsolve 未安装（.venv/Scripts/python.exe -m pip install ngsolve）")
        from netgen.occ import Box, Pnt, X, Y, Z
        from ngsolve import CF, BilinearForm, GridFunction, HCurl, LinearForm, curl, ds, dx

        assert self._spec is not None and self._freqs_ghz is not None
        spec = self._spec
        length, width, height = (spec["length_mm"] * 1e-3,
                                 spec["width_mm"] * 1e-3,
                                 spec["height_mm"] * 1e-3)
        z0 = parallel_plate_z0(spec["width_mm"], spec["height_mm"], spec["eps_r"])
        gamma = robin_gamma(z0, spec["z_ref_ohm"])
        maxh = self._mesh_maxh_mm * 1e-3

        box = Box(Pnt(0.0, 0.0, 0.0), Pnt(length, width, height))
        box.faces.Min(Z).name = "pec_bot"
        box.faces.Max(Z).name = "pec_top"
        box.faces.Min(Y).name = "pmc_y0"  # 侧壁不施加任何 BC = 自然 PMC（TEM 精确）
        box.faces.Max(Y).name = "pmc_y1"
        box.faces.Min(X).name = "port1"
        box.faces.Max(X).name = "port2"
        mesh = box.GenerateMesh(maxh=maxh)  # netgen.occ 直接返回 ngsolve Mesh
        n_tets = int(mesh.ne)

        fes = HCurl(mesh, order=self._order, complex=True,
                    dirichlet="pec_bot|pec_top")
        ezhat = CF((0, 0, 1))
        u, v = fes.TnT()
        x_lo, x_hi = SAMPLE_WINDOW
        sample_x = np.linspace(x_lo * length, x_hi * length, N_SAMPLE_PLANES)
        y_mid, z_mid = width / 2.0, height / 2.0

        freq_ghz = list(self._freqs_ghz)
        s = np.zeros((len(freq_ghz), 2, 2), dtype=complex)
        dof_count = int(fes.ndof)
        for i, f_ghz in enumerate(freq_ghz):
            k = 2.0 * np.pi * f_ghz * 1e9 * math.sqrt(spec["eps_r"]) / C0
            a = BilinearForm(fes)
            a += (curl(u) * curl(v) - (k * k) * (u * v)) * dx
            a += (-1j * k * gamma) * (u.Trace() * v.Trace()) * ds("port1")
            a += (-1j * k * gamma) * (u.Trace() * v.Trace()) * ds("port2")
            rhs = LinearForm(fes)
            rhs += excitation_coef(k, gamma, E_INC, height) * (
                ezhat * v.Trace()) * ds("port1")
            a.Assemble()
            rhs.Assemble()
            gfu = GridFunction(fes)
            gfu.vec.data = a.mat.Inverse(fes.FreeDofs(),
                                         inverse="umfpack") * rhs.vec
            vz = np.array([height * complex(gfu(mesh(float(xs), y_mid, z_mid))[2])
                           for xs in sample_x])
            c_plus, c_minus = wave_decompose(vz, sample_x, k)
            s[i] = sparams_from_waves(c_plus, c_minus, k, length, z0,
                                      spec["z_ref_ohm"])
        extra = {"n_tets": n_tets, "n_dof": dof_count, "order": self._order,
                 "mesh_maxh_mm": self._mesh_maxh_mm,
                 "robin_gamma": round(gamma, 6)}
        return freq_ghz, s, extra

    def _solve_rect_waveguide(self) -> EMSolverResult:
        """rect_waveguide 真机链路（P2⑫）：PEC 盒 TE10 解析模态 Robin 端口
        + 逐端口激励轮转装配真 2×2。

        约定（TEM 已实证口径的模态推广，见模块 docstring）：
        - 体积项 k²（介质波数）；边界项 C=−jβγ（β=TE10 模传播常数，
          γ=Z_TE(f)/Zref ⟹ 模态负载恰为 Zref，Γ=(1−γ)/(1+γ)）；
        - 激励 G=2jβγE_INC/b·sin(πy/a)（模剖面口径；复用 excitation_coef
          的 2jkγE_INC/H，k→β、H→b）；
        - 同频 BilinearForm 组装一次/umfpack 分解一次，两端口 RHS 各
          回代一次（进程内复用合法，#208 是 openEMS 特有坑）；
        - 每次激励：模剖面内积取 V(x) 五面窗 → wave_decompose →
          sparams_column_from_waves 成整列（S22/S12 真测量）。
        """
        t0 = time.time()
        try:
            if not ngsolve_installed():
                raise RuntimeError(
                    "ngsolve 未安装（.venv/Scripts/python.exe -m pip install "
                    "ngsolve）")
            assert self._spec is not None and self._freqs_ghz is not None
            spec = self._spec
            eps_r = spec["eps_r"]
            zref = spec["z_ref_ohm"]
            fc = te10_fc_ghz(spec["a_mm"], eps_r)
            s_ref = rect_waveguide_closed_form(spec,
                                               np.asarray(self._freqs_ghz,
                                                          dtype=float))
            # ↑ 任一频点≤截止在此显式 ValueError（先于任何网格构建）
            length = spec["length_mm"] * 1e-3
            a_m, b_m = spec["a_mm"] * 1e-3, spec["b_mm"] * 1e-3
            eta = ETA0 / math.sqrt(eps_r)
            maxh = self._mesh_maxh_mm * 1e-3

            from netgen.occ import Box, Pnt, X, Y, Z
            from ngsolve import CF, BilinearForm, GridFunction, HCurl, LinearForm, curl, ds, dx
            from ngsolve import sin as ng_sin
            from ngsolve import y as ng_y

            box = Box(Pnt(0.0, 0.0, 0.0), Pnt(length, a_m, b_m))
            box.faces.Min(Y).name = "pec_y0"  # 宽边壁（y=0，TE10 E_z 波腹处切向=0）
            box.faces.Max(Y).name = "pec_y1"  # 宽边壁（y=a）
            box.faces.Min(Z).name = "pec_z0"  # 窄边壁（z=0）
            box.faces.Max(Z).name = "pec_z1"  # 窄边壁（z=b）
            box.faces.Min(X).name = "port1"
            box.faces.Max(X).name = "port2"
            mesh = box.GenerateMesh(maxh=maxh)
            n_tets = int(mesh.ne)

            fes = HCurl(mesh, order=self._order, complex=True,
                        dirichlet="pec_y0|pec_y1|pec_z0|pec_z1")
            ezhat = CF((0, 0, 1))
            sin_cf = ng_sin(math.pi * ng_y / a_m)  # TE10 模剖面 w(y)
            u, v = fes.TnT()
            x_lo, x_hi = SAMPLE_WINDOW
            sample_x = np.linspace(x_lo * length, x_hi * length,
                                   N_SAMPLE_PLANES)
            sample_y = np.linspace(0.0, a_m, N_Y_SAMPLES)
            z_mid = b_m / 2.0

            freq_ghz = list(self._freqs_ghz)
            s = np.zeros((len(freq_ghz), 2, 2), dtype=complex)
            dof_count = int(fes.ndof)
            for i, f_ghz in enumerate(freq_ghz):
                k = 2.0 * np.pi * f_ghz * 1e9 * math.sqrt(eps_r) / C0
                beta = te10_beta(f_ghz, fc, eps_r)
                z_te = te10_wave_impedance(f_ghz, fc, eta)
                gamma = robin_gamma(z_te, zref)
                a_mat = BilinearForm(fes)
                a_mat += (curl(u) * curl(v) - (k * k) * (u * v)) * dx
                a_mat += (-1j * beta * gamma) * (u.Trace() * v.Trace()) * ds("port1")
                a_mat += (-1j * beta * gamma) * (u.Trace() * v.Trace()) * ds("port2")
                a_mat.Assemble()
                inv = a_mat.mat.Inverse(fes.FreeDofs(), inverse="umfpack")
                gfu = GridFunction(fes)
                g1 = excitation_coef(beta, gamma, E_INC, b_m)  # 2jβγE_INC/b
                for p, port in enumerate(("port1", "port2")):
                    rhs = LinearForm(fes)
                    rhs += g1 * (sin_cf * (ezhat * v.Trace())) * ds(port)
                    rhs.Assemble()
                    gfu.vec.data = inv * rhs.vec
                    vz = np.array([
                        modal_voltage_te10(
                            [complex(gfu(mesh(float(xs), float(ys), z_mid))[2])
                             for ys in sample_y],
                            sample_y, spec["a_mm"], spec["b_mm"])
                        for xs in sample_x])
                    c_plus, c_minus = wave_decompose(vz, sample_x, beta)
                    s[i, :, p] = sparams_column_from_waves(
                        c_plus, c_minus, beta, length, z_te, zref)
            # 门：全 2×2 复数逐元闭式对照 + 无源性 + 互易小量（真测量）
            err_max = float(np.abs(s - s_ref).max())
            # 无源性=逐端口功率守恒：Σ_j|S_ij|²≤1（无耗 ⟹ =1）；全矩阵求和
            # 对无损 2×2 恒为 2，不作门
            p_max = float(np.max(np.sum(np.abs(s) ** 2, axis=2)))
            recip = float(np.abs(s[:, 0, 1] - s[:, 1, 0]).max())
            f_mid = float(np.median(freq_ghz))
            wall = round(time.time() - t0, 1)
            self._write_csv(np.asarray(freq_ghz, dtype=float), s)
            ok = (err_max <= GATE_S_MAX_ABS_ERR
                  and p_max <= 1.0 + PASSIVITY_TOL
                  and recip <= GATE_S_MAX_ABS_ERR)
            extra = {"n_tets": n_tets, "n_dof": dof_count, "order": self._order,
                     "mesh_maxh_mm": self._mesh_maxh_mm,
                     "robin_gamma_mid": round(robin_gamma(
                         te10_wave_impedance(f_mid, fc, eta), zref), 6)}
            field_data = {
                "template": TEMPLATE_WAVEGUIDE,
                "solver": "ngsolve HCurl 时谐 Maxwell（直接解 umfpack）",
                "port_type": ("解析 TE10 模态 Robin（边界项 C=-jβγ、"
                              "γ=Z_TE/Zref，两端口；逐端口激励轮转）"),
                "extraction": (f"模剖面内积模电压（{N_Y_SAMPLES} 点 × "
                               f"{N_SAMPLE_PLANES} 面，{SAMPLE_WINDOW[0]}L–"
                               f"{SAMPLE_WINDOW[1]}L）+ 行波分解"),
                "phase_convention": "工程 e^{+jωt}（求解器 e^{−iωt} 解取共轭）",
                "te10_fc_ghz": round(fc, 6),
                "te10_z_mid_ohm": round(te10_wave_impedance(
                    f_mid, fc, eta), 4),
                "s_max_abs_err": err_max,
                "reciprocity_max_abs": recip,
                "passivity_max_sum": p_max,
                "gates": {"s_max_abs_err": GATE_S_MAX_ABS_ERR,
                          "passivity_tol": PASSIVITY_TOL,
                          "reciprocity_max_abs": GATE_S_MAX_ABS_ERR},
                **extra,
            }
            self._result = EMSolverResult(
                success=True, freq_ghz=np.asarray(freq_ghz, dtype=float),
                s_params=s, field_data=field_data, wall_time_s=wall,
                message=(f"NGSolve 频域求解完成（{TEMPLATE_WAVEGUIDE}，"
                         f"{len(freq_ghz)} 频点 × 2 激励；闭式全 2×2 对照 "
                         f"max|ΔS|≤{err_max:.2e} 互易≤{recip:.2e} "
                         f"Σ|S|²≤{p_max:.6f}"
                         f"{'，门全过' if ok else '，有门未过（如实）'}）"),
            )
            return self._result
        except Exception as exc:
            wall = round(time.time() - t0, 1)
            logger.error("NGSolve 求解失败: %s", exc)
            return EMSolverResult(success=False, wall_time_s=wall,
                                  message=f"NGSolve 求解失败: {exc}")

    def _write_csv(self, freq_ghz: np.ndarray, s: np.ndarray) -> None:
        """S 参量落 CSV（证据产物）；best-effort（#105）。"""
        try:
            self._working_dir.mkdir(parents=True, exist_ok=True)
            rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21,re_S12,im_S12,re_S22,im_S22"]
            for k, f in enumerate(np.asarray(freq_ghz, dtype=float)):
                cells = [f"{f * 1e9:.6e}"]
                for (p, q) in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    cells += [f"{s[k, p, q].real:.9e}", f"{s[k, p, q].imag:.9e}"]
                rows.append(",".join(cells))
            (self._working_dir / "sparams.csv").write_text(
                "\n".join(rows) + "\n", encoding="utf-8")
        except Exception:
            logger.warning("NGSolve sparams.csv 落盘失败（不影响结果）",
                           exc_info=True)

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """最近一次成功求解的 (freq_ghz, s_params)。"""
        if self._result is None or not self._result.success:
            raise RuntimeError("尚未成功求解，请先调用 solve()")
        assert self._result.freq_ghz is not None
        assert self._result.s_params is not None
        return self._result.freq_ghz, self._result.s_params

    def close(self) -> None:
        """清求解引用（无外部进程/license 常驻）。"""
        self._connected = False

    # ── 6g 产物视图协议 / 状态 ───────────────────────────────────────────────
    def visualizations(self) -> list[dict[str, Any]]:
        return [{"kind": "sparams",
                 "spec": {"file": str(self._working_dir / "sparams.csv")}}]

    def supported_output_formats(self) -> list[str]:
        """无 Touchstone 导出实现（A5 如实声明 False）——只报 csv。"""
        return ["csv"]

    def get_status(self) -> dict[str, Any]:
        status = super().get_status()
        status.update({
            "ngsolve_installed": ngsolve_installed(),
            "templates": list(SUPPORTED_TEMPLATES),
            "order": self._order,
            "mesh_maxh_mm": self._mesh_maxh_mm,
            "license_policy": "LGPL-2.1 开源，无 license 席位",
        })
        return status


# ── 注册到全局注册表（与 comsol/palace 同模式：导入即注册）──────────────────
def register_ngsolve() -> None:
    """注册 NGSolve 求解器到全局注册表。"""
    get_global_registry().register(EMSolverType.NGSOLVE, NGSolveAdapter)


with contextlib.suppress(Exception):
    register_ngsolve()
