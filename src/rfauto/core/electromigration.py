r"""MP-4 电迁移-场联动确定性内核（round15 §三 :86「loss_density 场→局部 J
→Black MTTF + IPC-2152 ΔT 联合」）。

确定性纯函数、零 IO、JSON 可序列化；数值全部落在本内核，LLM/agent 只解释
（铁律 7）。本文件与 core/aging.py 互补：Black 方程/Arrhenius 加速因子**
消费 aging 既有实现**（black_mttf/arrhenius_af，零重复实现）；温度链消费
MP-1 core/thermal_transient.py 的 Foster Z_th（结温→MTTF）。

三条闭式
--------
1) 场→局部电流密度（焦耳体损耗密度反演）
       q = ρ(T)·J²  →  J = sqrt(q/ρ(T))
   ρ(T) = ρ_ref·[1 + α·(T − T_ref)]（α=电阻温度系数 TCR；α 缺省不修正）。
   语义口径：q 是 EM 场后处理的局部损耗密度（W/m³，逐网格局部值）——
   高频趋肤/邻近效应下局部 J 高于截面等效均值，本内核只做逐点局部反演，
   不做全局等效（全局等效会系统性低估热点 J）。铜参考常数（模块常量，
   非缺省注入）：ρ_Cu(20 °C)=1.724e-8 Ω·m（IACS 100% 退火铜）、
   α_Cu=3.93e-3 /K、原子体积 Ω=摩尔体积 7.11e-6 m³/mol ÷ N_A≈1.1807e-29。

2) Black 电迁移 MTTF（消费 core/aging.py）
       MTTF = A·J⁻ⁿ·exp(Ea/kT)
   n 缺省 2.0（J. R. Black, IEEE Trans. Electron Devices ED-16, 338
   (1969) 原始口径；后续文献按金属/微结构 1–2 典型带，可显式覆盖）；
   Ea 为必填（随金属/工艺标定：Al 系文献常见 ~0.5–0.7 eV、Cu 系
   ~0.8–1.0 eV——量级语境非缺省值，本内核不内置臆造 Ea）。A 的时间单位
   由标定吸收（A 按 h·(J 单位)^n 标定则 MTTF 返回小时）。温度加速因子
   AF = exp[(Ea/k)(1/T_use − 1/T_stress)]（aging.arrhenius_af 同式）。

3) Blech 长度效应（不 immortal 判据）
   电迁移引起的应力背压与 EM 漂移平衡时，线内应力梯度支撑起反向回流，
   稳态条件给出临界电流密度-长度积：
       (j·L)_c = Δσ·Ω / (|Z*|·e·ρ)
   （I. A. Blech, J. Appl. Phys. 47, 1203 (1976)；Δσ=可承受应力松弛窗
   Pa、Ω=原子体积 m³、Z*=有效电荷数、e=元电荷、ρ=电阻率 Ω·m。）
   j·L ≤ (jL)_c 判 immortal（margin=(jL)_c/(j·L) ≥ 1）。量级锚：Cu
   Δσ=50 MPa、ρ=1.724e-8 Ω·m 给 (jL)_c≈2.14e5 A/m≈2.1e3 A/cm——文献
   常引的 Cu「Blech product ~2000 A/cm」工程带（Δσ 50 MPa 量级假设）
   吻合；Δσ 上调到 100 MPa 同式翻倍（判据对 Δσ 取值线性敏感，调用方
   应按工艺标定 Δσ 而非套用通用数）。

温度链（MP-1 消费面）
--------------------
局部金属温度二选一：
  * direct：temperature_c 直接给（IPC-2152 ΔT 联合=把已注册键
    ipc2152_trace_temp_rise 的 delta_t_c 加到环境温度后经本口注入；
    组合链由锚树测试演示）；
  * thermal_transient：Foster 网络 (zth_r_c_per_w, zth_tau_s) + power_w
    （MP-1 step_response_zth；time_s 给则取瞬态 ΔT(t)，缺省稳态
    ΔT=P·ΣR——能量守恒锚）；Tj = ambient_c + ΔT。

设计约束：core 叶子层纯标准库 + 依赖 core/aging、core/thermal_transient
（同为零 IO 纯函数），非法输入显式 ValueError，不静默兜底；dict 输出
JSON 可序列化。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.aging import arrhenius_af, black_mttf
from rfauto.core.thermal_transient import step_response_zth

__all__ = [
    "COPPER_ATOMIC_VOLUME_M3",
    "COPPER_RESISTIVITY_OHM_M",
    "COPPER_TCR_PER_K",
    "E_CHARGE_C",
    "blech_check",
    "blech_critical_product",
    "em_mttf_check",
    "local_current_density",
    "resistivity_at",
]

# 元电荷（SI 2019 精确定义值）
E_CHARGE_C = 1.602176634e-19

# 铜参考常数（文献通引值；模块常量供调用方显式注入，不作隐藏缺省）
COPPER_RESISTIVITY_OHM_M = 1.724e-8  # Ω·m @ 20 °C（IACS 100% 退火铜）
COPPER_TCR_PER_K = 3.93e-3           # 1/K @ 20 °C 口径
COPPER_ATOMIC_VOLUME_M3 = 1.1807e-29  # Ω = 7.11e-6 m³/mol ÷ N_A


# ---------------------------------------------------------------------------
# 输入校验（house style：显式 ValueError，不静默兜底）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为有限数值") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数值")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


# ---------------------------------------------------------------------------
# 1) 场→局部 J（焦耳体损耗密度反演）
# ---------------------------------------------------------------------------

def resistivity_at(rho_ref_ohm_m: float, t_k: float, tcr_per_k: float,
                   t_ref_c: float = 20.0) -> float:
    """线性 TCR 修正 ρ(T) = ρ_ref·[1 + α·(T − T_ref)]。

    rho_ref_ohm_m：参考温度电阻率（Ω·m，>0）；t_k：目标温度（K，>0）；
    tcr_per_k：电阻温度系数（1/K，≥0）；t_ref_c：参考温度（°C，缺省 20）。
    1 + α·ΔT ≤ 0（非物理负电阻率）显式拒绝。
    """
    rho_ref = _positive(rho_ref_ohm_m, "rho_ref_ohm_m")
    alpha = _nonneg(tcr_per_k, "tcr_per_k")
    t_ref_k = _finite(t_ref_c, "t_ref_c") + 273.15
    if t_ref_k <= 0.0:
        raise ValueError("t_ref_c 低于绝对零度")
    _positive(t_k, "t_k")
    factor = 1.0 + alpha * (t_k - t_ref_k)
    if factor <= 0.0:
        raise ValueError(
            f"TCR 修正后电阻率非正（1+α·ΔT={factor:.6g}）：温度超出线性模型定义域")
    return rho_ref * factor


def local_current_density(loss_density_w_per_m3: float, t_k: float,
                          resistivity_ohm_m: float,
                          tcr_per_k: float | None = None,
                          t_ref_c: float = 20.0) -> float:
    """局部焦耳损耗密度 → 局部电流密度 J = sqrt(q/ρ(T))（A/m²）。

    loss_density_w_per_m3：EM 场后处理局部损耗密度（W/m³，>0）；
    t_k：局部金属温度（K，>0，供 TCR 修正）；resistivity_ohm_m：参考温度
    电阻率（Ω·m，>0）；tcr_per_k 给定则 ρ 取 TCR 修正后的 ρ(T)。
    语义：逐网格局部值反演（高频趋肤下局部 J > 截面均值，不做全局等效）。
    """
    q = _positive(loss_density_w_per_m3, "loss_density_w_per_m3")
    if tcr_per_k is None:
        rho = _positive(resistivity_ohm_m, "resistivity_ohm_m")
    else:
        rho = resistivity_at(resistivity_ohm_m, t_k, tcr_per_k, t_ref_c)
    return math.sqrt(q / rho)


# ---------------------------------------------------------------------------
# 2) Blech 长度效应
# ---------------------------------------------------------------------------

def blech_critical_product(delta_sigma_pa: float, atomic_volume_m3: float,
                           zstar: float, resistivity_ohm_m: float) -> float:
    """Blech 临界积 (j·L)_c = Δσ·Ω/(|Z*|·e·ρ)（A/m）。

    delta_sigma_pa：应力松弛窗（Pa，≥0；Δσ=0 → 临界积 0=永不 immortal）；
    atomic_volume_m3：原子体积（m³，>0，铜缺省常量 COPPER_ATOMIC_VOLUME_M3）；
    zstar：有效电荷数（非零；取 |Z*| 口径）；resistivity_ohm_m：线电阻率
    （Ω·m，>0）。
    """
    delta_sigma = _nonneg(delta_sigma_pa, "delta_sigma_pa")
    omega = _positive(atomic_volume_m3, "atomic_volume_m3")
    z = _finite(zstar, "zstar")
    if z == 0.0:
        raise ValueError("zstar 必须非零（无电迁移驱动力时判据无定义）")
    rho = _positive(resistivity_ohm_m, "resistivity_ohm_m")
    return delta_sigma * omega / (abs(z) * E_CHARGE_C * rho)


def blech_check(j_density_a_per_m2: float, segment_length_m: float,
                delta_sigma_pa: float, atomic_volume_m3: float,
                zstar: float, resistivity_ohm_m: float) -> dict[str, Any]:
    """Blech immortal 判据：j·L ≤ (jL)_c → immortal。

    返回 dict（JSON 可序列化）：jl_a_per_m / jl_critical_a_per_m /
    jl_a_per_cm / jl_critical_a_per_cm / margin（=(jL)_c/(jL)，≥1 immortal）/
    immortal（bool）/ resistivity_ohm_m（判据所用 ρ）。
    """
    j = _positive(j_density_a_per_m2, "j_density_a_per_m2")
    length = _positive(segment_length_m, "segment_length_m")
    jl_critical = blech_critical_product(delta_sigma_pa, atomic_volume_m3,
                                         zstar, resistivity_ohm_m)
    jl = j * length
    margin = jl_critical / jl
    return {
        "jl_a_per_m": round(jl, 12),
        "jl_critical_a_per_m": round(jl_critical, 12),
        "jl_a_per_cm": round(jl * 0.01, 12),
        "jl_critical_a_per_cm": round(jl_critical * 0.01, 12),
        "margin": round(margin, 12),
        "immortal": bool(margin >= 1.0),
        "resistivity_ohm_m": round(_positive(resistivity_ohm_m,
                                             "resistivity_ohm_m"), 15),
    }


# ---------------------------------------------------------------------------
# 3) 联合报告（场→J→T→Black MTTF + AF + Blech）
# ---------------------------------------------------------------------------

def em_mttf_check(
    loss_density_w_per_m3: float | None = None,
    j_density_a_per_m2: float | None = None,
    resistivity_ohm_m: float | None = None,
    tcr_per_k: float | None = None,
    t_ref_c: float = 20.0,
    temperature_c: float | None = None,
    ambient_c: float = 25.0,
    zth_r_c_per_w: list[float] | None = None,
    zth_tau_s: list[float] | None = None,
    power_w: float | None = None,
    time_s: float | None = None,
    a_black: float | None = None,
    n_black: float = 2.0,
    ea_ev: float | None = None,
    t_ref_af_c: float | None = None,
    segment_length_m: float | None = None,
    delta_sigma_pa: float | None = None,
    atomic_volume_m3: float | None = None,
    zstar: float = 1.0,
) -> dict[str, Any]:
    """电迁移-场联动联合报告：loss_density→局部 J→局部 T→Black MTTF。

    J 路由（二选一，都给/都不给显式拒绝）：
      * loss_density_w_per_m3（+resistivity_ohm_m 必填）：焦耳反演；
      * j_density_a_per_m2：直接给局部电流密度（实测/仿真提取值）。
    T 路由（二选一，都给/都不给显式拒绝）：
      * temperature_c：直接给局部金属温度（IPC-2152 ΔT 联合=外部把
        delta_t_c 加环境温度后经本口注入，组合链见锚树测试）；
      * Foster 热链：zth_r_c_per_w + zth_tau_s + power_w（三参数同给，
        消费 MP-1 thermal_transient；time_s 给则瞬态 ΔT(t)，缺省稳态
        P·ΣR）；Tj = ambient_c + ΔT。
    Black：a_black/ea_ev 必填（Ea 随金属/工艺标定，不内置臆造缺省）；
    n_black 缺省 2.0（Black 1969 原始口径）。t_ref_af_c 给定时输出
    Arrhenius 温度加速因子 AF（T_use=参考温度、T_stress=局部温度）与
    参考温度 MTTF（恒等式 mttf_at_ref = mttf·AF 由锚树钉）。
    Blech（可选）：segment_length_m 给定时启用，需 delta_sigma_pa 同给
    （direct J 路由还需 resistivity_ohm_m）；atomic_volume_m3 缺省铜值。

    Returns:
        JSON 可序列化 dict（见各键名；mttf 时间单位与 a_black 标定一致）。
    """
    # ── J 路由 ──
    if (loss_density_w_per_m3 is None) == (j_density_a_per_m2 is None):
        raise ValueError(
            "loss_density_w_per_m3 与 j_density_a_per_m2 必须二选一")
    if loss_density_w_per_m3 is not None:
        q = _positive(loss_density_w_per_m3, "loss_density_w_per_m3")
        rho_ref = _positive(resistivity_ohm_m, "resistivity_ohm_m")
        route_j = "loss_density"
    else:
        j_direct = _positive(j_density_a_per_m2, "j_density_a_per_m2")
        rho_ref = None if resistivity_ohm_m is None else _positive(
            resistivity_ohm_m, "resistivity_ohm_m")
        route_j = "direct"

    # ── T 路由 ──
    use_zth = any(v is not None
                  for v in (zth_r_c_per_w, zth_tau_s, power_w))
    if temperature_c is not None and use_zth:
        raise ValueError(
            "temperature_c 与 Foster 热链（zth_*+power_w）只能二选一")
    if temperature_c is None and not use_zth:
        raise ValueError(
            "必须给 temperature_c 或完整 Foster 热链（zth_r_c_per_w+"
            "zth_tau_s+power_w）")
    delta_t: float | None
    if use_zth:
        if zth_r_c_per_w is None or zth_tau_s is None or power_w is None:
            raise ValueError(
                "Foster 热链三参数必须同给：zth_r_c_per_w、zth_tau_s、power_w")
        ta = _finite(ambient_c, "ambient_c")
        p = _nonneg(power_w, "power_w")
        r_list = [_positive(v, f"zth_r_c_per_w[{i}]")
                  for i, v in enumerate(zth_r_c_per_w)]
        t_list = [_positive(v, f"zth_tau_s[{i}]")
                  for i, v in enumerate(zth_tau_s)]
        if len(r_list) != len(t_list):
            raise ValueError("zth_r_c_per_w 与 zth_tau_s 长度必须一致")
        if time_s is None:
            delta_t = p * sum(r_list)
            route_t = "thermal_transient_steady"
        else:
            delta_t = float(step_response_zth(
                _nonneg(time_s, "time_s"), r_list, t_list, power_w=p))
            route_t = "thermal_transient_transient"
        t_local_c = ta + delta_t
    else:
        t_local_c = _finite(temperature_c, "temperature_c")
        delta_t = None
        route_t = "direct"
    t_k = t_local_c + 273.15
    if t_k <= 0.0:
        raise ValueError("局部温度低于绝对零度")

    # ── J 与有效电阻率 ──
    if route_j == "loss_density":
        rho_eff = resistivity_at(rho_ref, t_k, tcr_per_k, t_ref_c) \
            if tcr_per_k is not None else rho_ref
        j_val = math.sqrt(q / rho_eff)
    else:
        rho_eff = rho_ref
        j_val = j_direct

    # ── Black MTTF（消费 core/aging）+ Arrhenius AF ──
    if a_black is None:
        raise ValueError("a_black 必填（Black 前置常数，随标定携带单位）")
    if ea_ev is None:
        raise ValueError("ea_ev 必填（激活能随金属/工艺标定，不内置臆造缺省）")
    a_ = _positive(a_black, "a_black")
    ea = _nonneg(ea_ev, "ea_ev")
    n_ = _nonneg(n_black, "n_black")
    mttf = black_mttf(a_, j_val, n_, ea, t_k)

    af: float | None = None
    mttf_at_ref: float | None = None
    if t_ref_af_c is not None:
        t_ref_k = _finite(t_ref_af_c, "t_ref_af_c") + 273.15
        if t_ref_k <= 0.0:
            raise ValueError("t_ref_af_c 低于绝对零度")
        af = arrhenius_af(ea, t_ref_k, t_k)
        mttf_at_ref = black_mttf(a_, j_val, n_, ea, t_ref_k)

    # ── Blech（可选） ──
    blech: dict[str, Any] | None = None
    if segment_length_m is not None:
        if rho_ref is None:
            raise ValueError(
                "Blech 判据需要 resistivity_ohm_m（临界积含 ρ）")
        if delta_sigma_pa is None:
            raise ValueError("Blech 判据需要 delta_sigma_pa")
        blech = blech_check(
            j_val, segment_length_m, delta_sigma_pa,
            COPPER_ATOMIC_VOLUME_M3 if atomic_volume_m3 is None
            else _positive(atomic_volume_m3, "atomic_volume_m3"),
            zstar, rho_eff)

    out: dict[str, Any] = {
        "route_j": route_j,
        "route_t": route_t,
        "j_density_a_per_m2": round(j_val, 12),
        "j_density_a_per_cm2": round(j_val * 1.0e-4, 12),
        "resistivity_ohm_m": None if rho_eff is None else round(rho_eff, 15),
        "temperature_c": round(t_local_c, 12),
        "temperature_k": round(t_k, 12),
        "delta_t_c": None if delta_t is None else round(delta_t, 12),
        "a_black": a_,
        "n_black": n_,
        "ea_ev": ea,
        "mttf": round(mttf, 12),
        "mttf_unit": "与 a_black 标定单位一致",
    }
    if af is not None:
        out["t_ref_af_c"] = _finite(t_ref_af_c, "t_ref_af_c")
        out["af"] = round(af, 12)
        out["mttf_at_ref"] = round(mttf_at_ref, 12)
    out["blech"] = blech
    return out
