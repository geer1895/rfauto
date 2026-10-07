"""LM-1 Fabry-Perot 谐振腔天线（FPA/RCA）闭式综合内核（纯函数零 IO）。

规格来源（研究扩充 round4 中件包二 LM-1）；
物理数字只出在本内核。口径与公式来源（铁律 5：来源写
docstring；裁判=独立来源，不自证，#118）：

- G. von Trentini, "Partially Reflecting Sheet Arrays," IRE Trans. Antennas
  Propag., vol. 4, no. 4, pp. 666-671, Oct. 1956 —— 谐振条件与
  (1+R)/(1-R) 增益口径的原始出处（IEEE 付费墙未直读，口径经下列开放原文
  Eq.(1)/Eq.(2) 转引核对——Trentini 是 Ji 2016 参考文献 [1]）。
- L. Ji, G. Fu, S.-X. Gong, "Array-Fed Beam-Scanning Partially Reflective
  Surface (PRS) Antenna," Progress In Electromagnetics Research Letters
  (PIERL, 开放期刊), vol. 58, pp. 73-79, 2016, DOI 10.2528/PIERL15101802。
  开放原文已抓全文（jpier.org, 2026-09-28）：Eq.(1) 腔高
  Lr = (phi/pi + 1)*lam0/4 + N*lam0/2（N 整数，PEC 地板 phi_GND=pi 口径）
  与本模块约定式 4*pi*h/lam0 - phi_PRS - phi_GND = 2*pi*N 的解集**逐位同族**
  （文献原生式 phi_PRS + phi_GND - 4*pi*h/lam0 = 2*pi*N 与本式仅差 N→-N
  整数翻转，解集不变）；Eq.(2) 增益 D_emax = (1+R)/(1-R)（R=PRS 功率反射率
  线性值；原文注明这是"相对源天线的"口径，绝对直增益需再乘馈源方向性——
  本模块按规格钉死口径只出 (1+R)/(1-R) 因子）；设计值 Lr=27 mm @ 5.5 GHz
  与均匀金属 PRS 的 ~180° 渐近口径差 1.8%，规格 ±5% 带内（单测
  test_literature_anchor_ji2016_pierl58 钉；反解频率取带心 5.5 GHz，带缘
  5.35/5.76 GHz 时偏差 7% 超带——如实登记，锚只在带心判）。
- Q/带宽面：**无可达文献闭式锚**（Ji 2016 无带宽-反射率式；
  Feresidis-Vardaxoglou 2001 付费墙）——由标准谐振腔能量衰减定义导出：
  腔内场每往返（时长 2h/c）能量乘 R（唯一泄漏通道=PRS 透射），指数衰减率
  -ln(R)/(2h/c)，Q = omega0*U/(-dU/dt) = 4*pi*h/(lam0*(-ln R))；与理想
  Airy 标准具半高全宽口径（系数精细度 F_c=4*sqrt(R)/(1-sqrt(R))^2，
  HWHM=2*arcsin((1-sqrt(R))/(2*R^(1/4)))）数值互差 1.0%@R=0.5、0.03%@R=0.9
  （高精细度极限两者渐近相等；单测双路径钉 ≤1.5%，#118 双径裁判）。
  **馈源加载项 UNKNOWN**（馈电耦合降低负载 Q——单源闭式不可达，v1 不虚构，
  同 aging.py 耦合项口径）：本 Q 面是无载（PRS 泄漏限定）估计，带宽
  1/Q 是增益峰 3dB 宽的**上界口径**（加载只会更宽），docstring/返回体
  双登记。

谐振条件（本模块约定，规格书钉死口径）::

    4*pi*h/lam0 - phi_PRS - phi_GND = 2*pi*N    （N = 0, ±1, ±2, ...）

- 腔高 h：PRS 至地板距离；phi_PRS/phi_GND：PRS/地板反射系数相位（弧度
  或度，本模块接口一律**度**）；N：谐振阶。给定 (f0, phi_PRS, phi_GND)
  的闭式解 h_N = (lam0/2)*(N + (phi_PRS+phi_GND)/(2*pi))，N 整数域多解
  （h>0 的全部 N），resonance_heights 返回升序解列表。
- 反解：给定 (f0, h, phi_GND) 所需 phi_PRS = 4*pi*h/lam0 - phi_GND - 2*pi*N
  （required_prs_phase，N 取最近整数使解包裹到 (−180, 180] 度；舍入用
  ceil(x-0.5) 半下取整，确定性，避开 round() 银行家舍入 df7+⑪，恰半整阶
  平局取 +180 度）。
- 边界（规格钉死）：R 不在 [0,1)、h<=0、f0<=0 → ValueError；bool 显式
  拒收（df7+⑯）。数值 0.0 合法面：R=0 → D=1（逐位）；phi=0 合法。

接口：全部函数返回 JSON 可序列化 float/int/str/bool/dict/list（ndarray 仅
directivity_scan 进出，序列化由调用方负责，同 aging.py Weibull 节口径）。
判缺失一律 ``is None``（数值 0.0 合法，#364④）。纯算法零 IO；不进
calculators 注册表（消费者是 service 层 fpa_antenna_service.py）。
metasurface_lut.py 的 PRS 供体接口 lut_prs_reflectance 输出
(r_power, phase_deg) 直接作本模块 (R, phi_PRS) 入参（LM-1 搭车面）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: 真空光速（m/s，SI 精确定义值）
C0_M_S = 299792458.0

#: Q 面模型标识（写进返回体，provenance 自描述）
FPA_Q_MODEL = "energy_decay_unloaded_v1"
#: 馈源加载登记（UNKNOWN 项的显式措辞，返回体携带）
FPA_Q_FEED_LOADING = "unknown_feed_loading_not_included"
#: 文献锚（Ji 2016 PIERL 58 设计值，写进 design_point 返回体 provenance）
FPA_LITERATURE_ANCHOR = "Ji2016_PIERL58_eq1_eq2_Lr27mm_5.5GHz"


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


def lam0_m(f0_ghz: float) -> float:
    """自由空间波长 lam0 = c/f0（m）。f0_ghz：频率（GHz，>0）。"""
    return C0_M_S / (_positive(f0_ghz, "f0_ghz") * 1e9)


# ─── 谐振条件：h 多解闭式 + phi_PRS 反解 ─────────────────────────────────────


@dataclass
class ResonanceSolution:
    """单阶谐振解（h_N 闭式解列表元素；to_dict JSON 可序列化）。"""

    n: int
    h_m: float
    lam0_m: float
    f0_ghz: float
    phi_prs_deg: float
    phi_gnd_deg: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n": int(self.n),
            "h_m": float(self.h_m),
            "lam0_m": float(self.lam0_m),
            "f0_ghz": float(self.f0_ghz),
            "phi_prs_deg": float(self.phi_prs_deg),
            "phi_gnd_deg": float(self.phi_gnd_deg),
        }


def _height_for_n(lam0: float, phi_sum_rad: float, n: int) -> float:
    """h_N = (lam0/2)*(N + (phi_PRS+phi_GND)/(2*pi))（谐振条件闭式反解）。"""
    return lam0 / 2.0 * (n + phi_sum_rad / (2.0 * math.pi))


def resonance_heights(
    f0_ghz: float,
    phi_prs_deg: float,
    phi_gnd_deg: float,
    *,
    n_solutions: int = 8,
    h_max_m: float | None = None,
) -> list[ResonanceSolution]:
    """给定 (f0, phi_PRS, phi_GND) → 谐振腔高闭式多解列表（N 整数域，升序）。

    解 h_N = (lam0/2)*(N + (phi_PRS+phi_GND)/(2*pi))，只收 h>0 的 N（h=0
    退化为无腔，排除）；N 自使 h>0 的最小整数起连续枚举 n_solutions 个。
    h_max_m 给出时只收 h<=h_max_m 的解（h 随 N 单调增，越界即止——可能
    返回空列表，如实不造解）。

    恒等式（单测钉 rel 1e-12）：回代 4*pi*h/lam0 - phi_PRS - phi_GND ==
    2*pi*N。phi_PRS=phi_GND=0 → h=N*lam0/2（规格 PMC/PPEC 口径）。
    """
    if not isinstance(n_solutions, int) or isinstance(n_solutions, bool) or n_solutions < 1:
        raise ValueError(f"n_solutions 须为 >=1 的 int，得 {n_solutions!r}")
    lam0 = lam0_m(f0_ghz)
    phi_p = _finite(phi_prs_deg, "phi_prs_deg")
    phi_g = _finite(phi_gnd_deg, "phi_gnd_deg")
    phi_sum = math.radians(phi_p) + math.radians(phi_g)
    # 最小 N：h>0 严格（h=0 排除）。floor(-s)+1 使 N+s ∈ (0,1]，s 整数时恰 1。
    n_min = math.floor(-phi_sum / (2.0 * math.pi)) + 1
    h_max = None if h_max_m is None else _positive(h_max_m, "h_max_m")
    out: list[ResonanceSolution] = []
    n = n_min
    while len(out) < n_solutions:
        h = _height_for_n(lam0, phi_sum, n)
        if h_max is not None and h > h_max:
            break
        out.append(
            ResonanceSolution(
                n=int(n),
                h_m=h,
                lam0_m=lam0,
                f0_ghz=float(f0_ghz),
                phi_prs_deg=phi_p,
                phi_gnd_deg=phi_g,
            )
        )
        n += 1
    return out


def required_prs_phase(f0_ghz: float, h_m: float, phi_gnd_deg: float) -> dict[str, float | int]:
    """反解：给定 (f0, h, phi_GND) → 所需 phi_PRS(f0)（包裹到 (-180, 180] 度）。

    phi_PRS = 4*pi*h/lam0 - phi_GND - 2*pi*N，N 取 ceil(x-0.5)（x=总相位/2pi，
    半下取整确定性；df7+⑪ 半整平局锚点：恰半整阶 x=k+0.5 → N=k+1、
    解取 +180 度而非 -180 度，包裹域 (−180, 180]）。返回 {"phi_prs_deg",
    "n", "h_m", "lam0_m", "f0_ghz", "phi_gnd_deg", "total_phase_deg"
    （4*pi*h/lam0-phi_GND 未包裹相位，度）}。回代恒等式：
    resonance_heights(f0, 返回值, phi_GND) 含 (n, h_m) 解（单测钉 rel 1e-12）。
    h<=0 / f0<=0 → ValueError。
    """
    lam0 = lam0_m(f0_ghz)
    h = _positive(h_m, "h_m")
    phi_g = _finite(phi_gnd_deg, "phi_gnd_deg")
    total = 4.0 * math.pi * h / lam0 - math.radians(phi_g)
    n = math.ceil(total / (2.0 * math.pi) - 0.5)
    phi_prs_rad = total - 2.0 * math.pi * n
    return {
        "phi_prs_deg": math.degrees(phi_prs_rad),
        "n": int(n),
        "h_m": h,
        "lam0_m": lam0,
        "f0_ghz": float(f0_ghz),
        "phi_gnd_deg": phi_g,
        "total_phase_deg": math.degrees(total),
    }


# ─── 增益口径（Ji 2016 Eq.(2) / Trentini 谱系）───────────────────────────────


def _validate_r(r: float, name: str, *, allow_zero: bool = True) -> float:
    """R 功率反射率收敛：有限且 [0,1)（R=1 → D/Q 发散，拒绝）。"""
    out = _finite(r, name)
    if out < 0.0 or out >= 1.0 or (out == 0.0 and not allow_zero):
        lo = "[0" if allow_zero else "(0"
        raise ValueError(f"{name} 必须为 {lo},1) 内的有限数，得 {out}")
    return out


def directivity(r: float) -> float:
    """PRS 功率反射率 → 法向直增益因子 D = (1+R)/(1-R)（Ji 2016 Eq.(2)）。

    R∈[0,1)。恒等式（单测钉）：R=0 → D=1.0 逐位；R=0.9 → D=19（双径
    (1+R)/(1-R) 与 2/(1-R)-1，rel 1e-9）；R→1⁻ → D→∞。
    相对口径注记见模块 docstring（绝对直增益需再乘馈源方向性，不在本式）。
    """
    r_ = _validate_r(r, "r")
    return (1.0 + r_) / (1.0 - r_)


def directivity_db(r: float) -> float:
    """D 的 dB 值 10*log10((1+R)/(1-R))。R=0 → 0.0 逐位（log10(1)）。"""
    return 10.0 * math.log10(directivity(r))


def directivity_scan(r_values: np.ndarray) -> np.ndarray:
    """R 数组 → D 数组（向量化，单调性守恒：R 严格增 → D 严格增，单测钉）。

    r_values 逐元素须在 [0,1)（含越界/NaN 即 ValueError）；ndarray 进出
    （JSON 序列化由调用方负责，模块 docstring 口径）。
    """
    arr = np.asarray(r_values, dtype=float)
    if arr.size == 0:
        return arr.copy()
    if (
        not bool(np.all(np.isfinite(arr)))
        or float(np.min(arr)) < 0.0
        or float(np.max(arr)) >= 1.0
    ):
        raise ValueError("r_values 必须为 [0,1) 内的有限数")
    return (1.0 + arr) / (1.0 - arr)


# ─── Q/带宽面（能量衰减定义导出；馈源加载 UNKNOWN，见模块 docstring）─────────


def resonance_q(f0_ghz: float, h_m: float, r: float) -> dict[str, float | str]:
    """谐振腔无载 Q 与 3dB 分数带宽估计：Q = 4*pi*h/(lam0*(-ln R))。

    口径（模块 docstring 全链）：能量每往返（2h/c）乘 R，指数衰减率
    -ln(R)/(2h/c)，Q=omega0*U/(-dU/dt)。与 Airy 标准具 FWHM 口径互差
    1.0%@R=0.5、0.03%@R=0.9（单测双路径钉 ≤1.5%）。R∈(0,1) 严格（R=0
    无腔无谐振、R>=1 无泄漏 Q→∞，均 ValueError）。分数带宽=1/Q 是
    **上界口径**（馈源加载只会更宽，UNKNOWN 登记）。返回 {"q",
    "bandwidth_frac", "bandwidth_hz", "roundtrip_orders"（2h/lam0）,
    "model", "feed_loading"}。
    """
    lam0 = lam0_m(f0_ghz)
    h = _positive(h_m, "h_m")
    r_ = _validate_r(r, "r", allow_zero=False)
    q = 4.0 * math.pi * h / (lam0 * (-math.log(r_)))
    bw_frac = 1.0 / q
    return {
        "q": q,
        "bandwidth_frac": bw_frac,
        "bandwidth_hz": bw_frac * (f0_ghz * 1e9),
        "roundtrip_orders": 2.0 * h / lam0,
        "model": FPA_Q_MODEL,
        "feed_loading": FPA_Q_FEED_LOADING,
    }


# ─── 一次成点：谐振解 + 增益 + Q（service 面单调用入口）──────────────────────


def design_point(
    f0_ghz: float,
    r: float,
    phi_gnd_deg: float,
    *,
    phi_prs_deg: float | None = None,
    h_m: float | None = None,
    n: int = 0,
) -> dict[str, float | int | str]:
    """FPA 设计点一次成点：给 phi_PRS 或 h 恰其一 → 另一者 + D/dB + Q/带宽。

    phi_prs_deg 给出 → 解该 N 阶腔高 h（n 指定阶，缺省 0=最低正腔高阶）；
    h_m 给出 → 反解所需 phi_PRS（required_prs_phase，N 由反解定，入参 n
    忽略）。返回 JSON 可序列化 dict（f0/lam0/r/phi_gnd/phi_prs/n/h_m/
    directivity/directivity_db/q/bandwidth_frac/q_model/feed_loading/
    literature_anchor）。phi_prs_deg 与 h_m 必须恰给其一（is None 判缺失，
    #364④）；该 N 阶 h<=0 时 ValueError（降阶或改相位）。
    """
    if (phi_prs_deg is None) == (h_m is None):
        raise ValueError("phi_prs_deg 与 h_m 必须恰给其一（is None 判缺失）")
    d = directivity(r)
    d_db = directivity_db(r)
    if phi_prs_deg is not None:
        if not isinstance(n, int) or isinstance(n, bool):
            raise ValueError(f"n 须为 int，得 {n!r}")
        lam0 = lam0_m(f0_ghz)
        phi_p = _finite(phi_prs_deg, "phi_prs_deg")
        phi_g = _finite(phi_gnd_deg, "phi_gnd_deg")
        phi_sum = math.radians(phi_p) + math.radians(phi_g)
        h = _height_for_n(lam0, phi_sum, n)
        if h <= 0.0:
            raise ValueError(f"n={n} 阶解 h={h}<=0（降阶或改相位）")
        n_used = int(n)
    else:
        req = required_prs_phase(f0_ghz, float(h_m) if h_m is not None else 0.0, phi_gnd_deg)
        phi_p = float(req["phi_prs_deg"])
        phi_g = _finite(phi_gnd_deg, "phi_gnd_deg")
        h = float(req["h_m"])
        lam0 = float(req["lam0_m"])
        n_used = int(req["n"])
    q = resonance_q(f0_ghz, h, r)
    return {
        "f0_ghz": float(f0_ghz),
        "lam0_m": lam0,
        "r": float(r),
        "phi_gnd_deg": phi_g,
        "phi_prs_deg": phi_p,
        "n": n_used,
        "h_m": h,
        "directivity": d,
        "directivity_db": d_db,
        "q": float(q["q"]),
        "bandwidth_frac": float(q["bandwidth_frac"]),
        "q_model": FPA_Q_MODEL,
        "feed_loading": FPA_Q_FEED_LOADING,
        "literature_anchor": FPA_LITERATURE_ANCHOR,
    }
