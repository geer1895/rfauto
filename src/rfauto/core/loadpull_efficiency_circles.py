"""Cripps load-pull 等效率圆闭式（MT-7；线性简化口径）。

ge8d 波·席D4（runs/ge8_followup/wave_d/seat_d_all.md §席D4）；条目
研究扩充 round17 MT-7「等效率 load-pull 圆」。

定位（#222 接地先行）：core/active_chain.py 已有 Cripps **等功率**面
（LoadPullDevice / load_pull_power_dbm / cripps_contour_locus——Yt 平面
Norton 圆弧∪电压限弦）。本件是**效率**面：不修改既有件（只增不改），
import 其器件模型与等功率线为唯一产核，新增：

1. 漏效率 η(Γ_L) 闭式与 η_max（含膝点折减）：
     A 类：P_dc = V_DD·I_sw/2 恒定，线性（不削波）基波电流幅上限
       I_1 ≤ I_sw/2 → 自身最优负载 R_opt,A = 2·R_opt（经典：A 类负载线
       是 B 类两倍），η_A,max = (1/2)·V_sw/V_DD；
     B 类：I_1 ≤ I_sw（限幅口径），I_dc = 2·I_1/π（负载相关）→
       η_B,max = (π/4)·V_sw/V_DD，最优负载 R_opt = V_sw/I_sw。
   （η_max = (π/4)(1−V_knee/V_DD) 膝点折减是 Cripps 教材经典结果；
   文献指向 Cripps 2nd ed. ch.2-3，页码 UNVERIFIED——2026-10-03 检索
   通道限速未逐页复核，推导自明并测试锚定。）
2. **恒效率↔恒功率的关系（分面定理，诚实口径）**：
     A 类：P_dc = V_DD·I_sw/2 与负载无关 → η = P/P_dc 全域成立，
       **等效率圆 ≡ 等功率圆**（层级映射 η = η_max·10^(−BO/10)）——
       这就是"Cripps 线性简化"的经典等效率圆口径；
     B 类（P_dc = V_DD·2I_1/π 随负载变）分两支：
       电流限支（I_1 = I_sw，|Y_t| ≥ G_opt）：P_dc 在支内恒定 →
         η/η_max = P/P_max 恒等式成立，等效率圆 = Norton 圆
         （(G−G_opt/(2e))²+B_t² = (G_opt/(2e))²，e = η/η_max）；
       电压限支（I_1 = V_sw·|Y_t|，|Y_t| ≤ G_opt）：η = (π/4)·V_sw·
         G/(V_DD·|Y_t|) 依赖 |Y_t| —— 等效率轨迹是**过原点的恒功率
         因数线** G = e·|Y_t|（±θ_e 射线，cos θ_e = e），**窄于**等功率
         弦 G = e·G_opt（这是"实测效率圈小于功率圈"经典观察在线性模型
         的解析对应）。两支在 |Y_t| = G_opt、G = e·G_opt 处连续相接
         （tests 互证）。真实负载牵引的效率等值线因压缩/谐波效应进一
         步偏离——本件只声称线性模型口径，登记级边界如实。
     A 类效率面在 B 类最优点 Γ_opt 处为 η_max,A/2（3 dB 回退，负载线
     两倍的几何后果，tests 锚定）。
3. Z 平面/Γ 平面恒功率（=A 类恒效率）圆的**解析闭式**（C_out=0 显式
   简化；C_out>0 走 active_chain 的 Yt 平面形式）：
     电压限分支（P ∝ G）：G = p/R_opt 反演为
         (R − R_opt/(2p))² + X² = (R_opt/(2p))²
       ——过原点圆，Γ 平面像仍为圆：
         center_Γ = (γ₁+γ₂)/2, radius_Γ = (γ₂−γ₁)/2，
         γ₁ = Γ(0) = −1，γ₂ = Γ(R_opt/p)（实轴对称圆必以两实点为直径）。
     电流限分支（P ∝ R）：Norton 圆 |Y_t−g₀| = g₀（g₀=G_opt/(2p)）在
         Z = 1/Y_t 反演下退化为直线 Re Z = p·R_opt；Γ 像为过
         Γ(p·R_opt) 与 Γ(∞)=1 的圆：center = R/(R+Z₀)、radius = Z₀/(R+Z₀)。
     两支结点（闭合处）：Z_j = p·R_opt ± j·R_opt·√(1−p²)，
         |Z_j| = R_opt ⟺ |Y_t| = G_opt（与 active_chain 结点 B_t =
         ±G_opt√(1−p²) 同一事件的两种参数化，tests 互证）。
   B 类电压限支等效率线（恒功率因数线）单独闭式见
   class_b_efficiency_ray（Yt 平面 ±θ_e 射线；Γ 像为单位圆弧）。
4. 消费 active_chain.cripps_contour_locus：给定目标效率 → 所需回退
   BO = −10log₁₀(η/η_max) → 直接取既有等功率线（层级重标注，A 类
   全域/B 类电流限支有效；B 类电压限支以射线闭式另交付）。

极限锚（tests）：p→1 两圆均塌缩到 Γ(Z_opt)（R_opt=Z₀ 时 Γ_opt=0）；
p→0 电压限圆 → |Γ|=1 全图、电流限圆 → |Γ|=1 全图；±X 对称；
η_B(Γ_opt) = (π/4)·V_sw/V_DD 逐位。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from rfauto.core.active_chain import (
    DEFAULT_Z0,
    LoadPullDevice,
    cripps_contour_locus,
)

_PA_CLASSES = ("A", "B")

_EPS = 1e-15


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def max_efficiency(device: LoadPullDevice, pa_class: str) -> float:
    """峰值漏效率（膝点折减）：A 类 (1/2)·Vsw/VDD；B 类 (π/4)·Vsw/VDD。

    Examples
    --------
    >>> from rfauto.core.active_chain import LoadPullDevice
    >>> from rfauto.core.loadpull_efficiency_circles import max_efficiency
    >>> dev = LoadPullDevice(vdd_v=28.0, imax_a=2.0, cout_f=1e-12, vknee_v=0.0)
    >>> round(max_efficiency(dev, "B"), 12)
    0.785398163397
    """
    if pa_class not in _PA_CLASSES:
        raise ValueError(f"pa_class 须为 'A' 或 'B'，收到 {pa_class!r}")
    vsw = device.vsw_v
    if vsw <= 0:
        raise ValueError("VDD 必须大于膝点电压")
    factor = 0.5 if pa_class == "A" else math.pi / 4.0
    return factor * vsw / device.vdd_v


def fundamental_current_amplitude(device: LoadPullDevice, f_hz: float,
                                  gamma_l: complex, z0: float = DEFAULT_Z0,
                                  *, pa_class: str = "B") -> float:
    """给定负载点的基波电流幅 |I1| = min(I_cap, V_sw·|Y_t|)。

    与 active_chain.load_pull_power_dbm 同源公式（本件只增不改约束下
    本地复算；tests 断言 B 类功率面与 load_pull_power_dbm 全网格逐位
    一致）。I_cap：B 类 = I_sw（限幅口径）；A 类 = I_sw/2（线性不削波）。
    """
    w = 2.0 * math.pi * f_hz
    if abs(1.0 - gamma_l) < _EPS:
        return 0.0
    z = z0 * (1.0 + gamma_l) / (1.0 - gamma_l)
    if not math.isfinite(z.real) or not math.isfinite(z.imag):
        return 0.0
    y_l = 1.0 / z if abs(z) > _EPS else 0j
    y_t = y_l + 1j * w * device.cout_f
    if abs(y_t) < _EPS or y_l.real <= 0.0:
        return 0.0
    i_cap = device.imax_a if pa_class == "B" else device.imax_a / 2.0
    return min(i_cap, device.vsw_v * abs(y_t))


def output_power_w(gamma_l: complex, device: LoadPullDevice, f_hz: float,
                   pa_class: str, z0: float = DEFAULT_Z0) -> float | None:
    """类别一致的基波输出功率 P = 0.5·I1²·Re{Y_L}/|Y_t|²（W；无效 None）。

    I1 按类别取 fundamental_current_amplitude 的上限（B: I_sw；A: I_sw/2）。
    B 类面与 active_chain.load_pull_power_dbm 同源（tests 全网格互证，
    消费核验走测试断言而非运行时双算）。
    """
    if pa_class not in _PA_CLASSES:
        raise ValueError(f"pa_class 须为 'A' 或 'B'，收到 {pa_class!r}")
    w = 2.0 * math.pi * f_hz
    if abs(1.0 - gamma_l) < _EPS:
        return None
    z = z0 * (1.0 + gamma_l) / (1.0 - gamma_l)
    if not (math.isfinite(z.real) and math.isfinite(z.imag)):
        return None
    y_l = 1.0 / z if abs(z) > _EPS else 0j
    y_t = y_l + 1j * w * device.cout_f
    if abs(y_t) < _EPS or y_l.real <= 0.0:
        return None
    i1 = fundamental_current_amplitude(device, f_hz, gamma_l, z0,
                                       pa_class=pa_class)
    if i1 <= 0.0:
        return None
    return 0.5 * i1 * i1 * y_l.real / (abs(y_t) ** 2)


def drain_efficiency(gamma_l: complex, device: LoadPullDevice, f_hz: float,
                     pa_class: str, z0: float = DEFAULT_Z0) -> float | None:
    """给定 Γ_L 的漏效率 η = P_out/P_dc（线性模型闭式；无效点返回 None）。

    P_out 经 output_power_w（类别一致电流上限口径）；P_dc：A 类恒定
    V_DD·I_sw/2；B 类 V_DD·2I_1/π（负载相关）。

    Examples
    --------
    >>> from rfauto.core.active_chain import LoadPullDevice
    >>> from rfauto.core.loadpull_efficiency_circles import drain_efficiency
    >>> dev = LoadPullDevice(vdd_v=28.0, imax_a=2.0, cout_f=0.0, vknee_v=1.0)
    >>> g = dev.optimal_gamma(1e9)
    >>> e = drain_efficiency(g, dev, 1e9, "B")
    >>> round(e, 12) == round(max_efficiency(dev, "B"), 12)
    True
    """
    if pa_class not in _PA_CLASSES:
        raise ValueError(f"pa_class 须为 'A' 或 'B'，收到 {pa_class!r}")
    p_out = output_power_w(gamma_l, device, f_hz, pa_class, z0)
    if p_out is None:
        return None
    if pa_class == "A":
        p_dc = device.vdd_v * device.imax_a / 2.0
    else:
        i1 = fundamental_current_amplitude(device, f_hz, gamma_l, z0,
                                           pa_class="B")
        if i1 <= 0.0:
            return None
        p_dc = device.vdd_v * 2.0 * i1 / math.pi
    return p_out / p_dc


@dataclass
class EfficiencyContourCircle:
    """恒效率（≡恒功率）圆闭式：Z 平面与 Γ 平面参数 + 结点 + 极限注记。"""

    branch: str            # "voltage_limited" | "current_limited"
    p_ratio: float         # P/P_max = η/η_max
    r_opt_ohm: float
    z0_ohm: float
    z_center_re: float | None   # 电压限: R_opt/(2p)；电流限: 直线无圆心
    z_radius: float | None
    z_line_re: float | None     # 电流限: Re Z = p·R_opt
    gamma_center_re: float
    gamma_radius: float
    junction_z: list[complex] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "p_ratio": round(self.p_ratio, 12),
            "r_opt_ohm": round(self.r_opt_ohm, 12),
            "z0_ohm": round(self.z0_ohm, 12),
            "z_center_re": (None if self.z_center_re is None
                            else round(self.z_center_re, 12)),
            "z_radius": (None if self.z_radius is None
                         else round(self.z_radius, 12)),
            "z_line_re": (None if self.z_line_re is None
                          else round(self.z_line_re, 12)),
            "gamma_center_re": round(self.gamma_center_re, 12),
            "gamma_radius": round(self.gamma_radius, 12),
            "junction_z": [{"re": round(z.real, 12), "im": round(z.imag, 12)}
                           for z in self.junction_z],
            "note": self.note,
        }


def constant_efficiency_circle(p_ratio: float, r_opt_ohm: float,
                               branch: str,
                               z0_ohm: float = DEFAULT_Z0) -> EfficiencyContourCircle:
    """恒功率（=A 类恒效率 / B 类电流限支恒效率）圆的 Z/Γ 平面闭式。

    适用域（诚实口径）：A 类（P_dc 恒定）两分支全域；B 类仅电流限支
    （|Y_t| ≥ G_opt）——B 类电压限支的等效率线是恒功率因数射线（见
    class_b_efficiency_ray），不是本圆族的弦。

    电压限分支：(R − R_opt/(2p))² + X² = (R_opt/(2p))²——过原点圆，
    Γ 像以 γ₁=Γ(0)=−1 与 γ₂=Γ(R_opt/p) 为直径端点（实轴对称圆的两实交
    点必为直径端点）。电流限分支：Re Z = p·R_opt 直线，Γ 像过
    Γ(p·R_opt) 与 Γ(∞)=1。结点 Z_j = p·R_opt ± j·R_opt√(1−p²)。

    Examples
    --------
    >>> from rfauto.core.loadpull_efficiency_circles import (
    ...     constant_efficiency_circle)
    >>> c = constant_efficiency_circle(0.5, 50.0, "voltage_limited", 50.0)
    >>> round(c.z_center_re, 9), round(c.z_radius, 9)
    (50.0, 50.0)
    """
    p = _finite(p_ratio, "p_ratio")
    if not (0.0 < p <= 1.0):
        raise ValueError(f"p_ratio 必须在 (0, 1]，收到 {p_ratio!r}")
    r_opt = _finite(r_opt_ohm, "r_opt_ohm")
    if r_opt <= 0.0:
        raise ValueError(f"r_opt_ohm 必须为正，收到 {r_opt_ohm!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(f"z0_ohm 必须为正，收到 {z0_ohm!r}")
    x_j = r_opt * math.sqrt(max(1.0 - p * p, 0.0))
    junction = [complex(p * r_opt, x_j), complex(p * r_opt, -x_j)]
    if branch == "voltage_limited":
        c = r_opt / (2.0 * p)
        gamma1 = -1.0                                   # Γ(Z=0)
        gamma2 = (2.0 * c - z0) / (2.0 * c + z0)        # Γ(Z=2c=R_opt/p)
        return EfficiencyContourCircle(
            branch=branch, p_ratio=p, r_opt_ohm=r_opt, z0_ohm=z0,
            z_center_re=c, z_radius=c, z_line_re=None,
            gamma_center_re=(gamma1 + gamma2) / 2.0,
            gamma_radius=(gamma2 - gamma1) / 2.0, junction_z=junction,
            note="G=p/R_opt 反演圆；过原点，Γ 像直径端点 −1 与 Γ(R_opt/p)")
    if branch == "current_limited":
        r_line = p * r_opt
        gamma0 = (r_line - z0) / (r_line + z0)          # Γ(R, X=0)
        gamma_inf = 1.0                                  # Γ(Z→∞)
        return EfficiencyContourCircle(
            branch=branch, p_ratio=p, r_opt_ohm=r_opt, z0_ohm=z0,
            z_center_re=None, z_radius=None, z_line_re=r_line,
            gamma_center_re=(gamma0 + gamma_inf) / 2.0,
            gamma_radius=(gamma_inf - gamma0) / 2.0, junction_z=junction,
            note="Norton 圆反演直线 Re Z=p·R_opt；Γ 像过 Γ(R) 与 Γ(∞)=1")
    raise ValueError(
        f"branch 须为 'voltage_limited' 或 'current_limited'，收到 {branch!r}")


def class_b_efficiency_ray(device: LoadPullDevice,
                           eta_ratio: float) -> dict[str, Any]:
    """B 类电压限支等效率线闭式：过原点恒功率因数线 G = e·|Y_t|。

    η = (π/4)·V_sw·G/(V_DD·|Y_t|)（电压限支，I_1 = V_sw·|Y_t|），
    e = η/η_max ⟺ G/|Y_t| = e——Yt 平面 ±θ_e 两条射线
    （θ_e = arccos e，B_t/G = ±√(1−e²)/e），有效段 |Y_t| ≤ G_opt；
    与电流限支 Norton 圆（层级 e）在 (G,B_t) = (e·G_opt,
    ±G_opt·√(1−e²)) 连续相接。Γ 平面像为单位圆弧（过原点直线的
    Möbius 像，工程口径取 Yt 平面射线）。

    Returns
    -------
    dict：theta_e_rad/deg、slope dB/dG、junction (G,Bt)、有效段端点、
    与等功率弦的对比注记（等效率射线窄于 G=e·G_opt 弦）。

    Examples
    --------
    >>> from rfauto.core.active_chain import LoadPullDevice
    >>> from rfauto.core.loadpull_efficiency_circles import class_b_efficiency_ray
    >>> dev = LoadPullDevice(vdd_v=28.0, imax_a=2.0, cout_f=0.0, vknee_v=1.0)
    >>> r = class_b_efficiency_ray(dev, 0.5)
    >>> round(r["theta_e_deg"], 6), round(r["junction_g"] / dev.gopt_s, 6)
    (60.0, 0.5)
    """
    e = _finite(eta_ratio, "eta_ratio")
    if not (0.0 < e <= 1.0):
        raise ValueError(f"eta_ratio 必须在 (0, 1]，收到 {eta_ratio!r}")
    g_opt = device.gopt_s
    theta = math.acos(e)
    g_j = e * g_opt
    bt_j = g_opt * math.sqrt(max(1.0 - e * e, 0.0))
    return {
        "eta_ratio": round(e, 12),
        "theta_e_rad": round(theta, 12),
        "theta_e_deg": round(math.degrees(theta), 9),
        "bt_over_g_at_ray": round(math.sqrt(1.0 - e * e) / e, 12),
        "junction_g": round(g_j, 12),
        "junction_bt": round(bt_j, 12),
        "ray_segment_yt": "|Y_t| ∈ (0, G_opt]，G = e·|Y_t|，±θ_e",
        "note": "电压限支等效率线=恒功率因数线（窄于等功率弦 G=e·G_opt，"
                "后者沿弦 |B_t| ≤ G_opt√(1−e²) 任意延伸而效率随之变化）；"
                "与电流限支 Norton 圆在结点连续",
    }


def efficiency_contour(device: LoadPullDevice, f_hz: float, pa_class: str,
                       eta_target: float,
                       z0: float = DEFAULT_Z0) -> dict[str, Any]:
    """目标效率 → 所需回退 → active_chain 等功率线（层级重标注）+ 圆闭式。

    η_target ≤ η_max 对应 p = η/η_max，BO = −10log₁₀(p)；产核 =
    active_chain.cripps_contour_locus。A 类全域/B 类电流限支：等效率线
    = 等功率线（层级重映射）；B 类电压限支：另附恒功率因数射线闭式
    （class_b_efficiency_ray——与等功率弦分族，如实分面）。
    """
    if pa_class not in _PA_CLASSES:
        raise ValueError(f"pa_class 须为 'A' 或 'B'，收到 {pa_class!r}")
    eta = _finite(eta_target, "eta_target")
    if not (0.0 < eta <= 1.0):
        raise ValueError(f"eta_target 必须在 (0, 1]，收到 {eta_target!r}")
    eta_max = max_efficiency(device, pa_class)
    if eta > eta_max:
        raise ValueError(
            f"eta_target={eta:.6f} 超过 {pa_class} 类模型峰值 "
            f"{eta_max:.6f}——线性模型不存在该等效率线（不外推）")
    p = eta / eta_max
    backoff_db = -10.0 * math.log10(p)
    r_opt = 1.0 / device.gopt_s  # = V_sw/I_sw（Ω；勿写 vsw/gopt）
    return {
        "pa_class": pa_class,
        "eta_max": round(eta_max, 12),
        "eta_target": round(eta, 12),
        "p_ratio": round(p, 12),
        "backoff_db": round(backoff_db, 9),
        "power_level_dbm": round(device.max_power_dbm() - backoff_db, 9),
        "gamma_circle_voltage_limited": constant_efficiency_circle(
            p, r_opt, "voltage_limited", z0).to_dict(),
        "gamma_circle_current_limited": constant_efficiency_circle(
            p, r_opt, "current_limited", z0).to_dict(),
        "power_locus": cripps_contour_locus(device, f_hz, backoff_db, z0),
        "class_b_voltage_limited_ray": (None if pa_class == "A"
                                        else class_b_efficiency_ray(device,
                                                                    p)),
    }
