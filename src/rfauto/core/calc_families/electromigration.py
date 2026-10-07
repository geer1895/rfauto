"""电迁移-场联动（MP-4，内核在 core/electromigration.py，本模块只做注册壳）。

round15 §三 :86 规格「loss_density 场→局部 J→Black MTTF + IPC-2152 ΔT
联合」（2026-10-02）。单键 electromigration_mttf_check（局部 J + 局部温度
→ Black MTTF/Arrhenius AF + 可选 Blech immortal 判据的联合报告）；
local_current_density/resistivity_at/blech_* 为 core 纯函数不注册（分析面
走 core 直调）。互补面（注册描述如实声明）：Black/Arrhenius 消费
core/aging 既有实现零重复；温度链消费 MP-1 core/thermal_transient Foster
Z_th；IPC-2152 ΔT 联合=已注册键 ipc2152_trace_temp_rise 的 delta_t_c 加
环境温度后经 temperature_c 口注入（组合链由锚树测试演示）。

本机单位约定（与 corona 壳同风格，core 收 SI）：应力 MPa（core 收 Pa）；
长度 m（IC 互连/板级导体段统一 SI 口径）；损耗密度/电流密度/电阻率为场量
SI（W/m³、A/m²、Ω·m）；温度 °C。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "electromigration_mttf_check",
    "MP-4 电迁移-场联动（round15 :86）：局部损耗密度场→局部 J→Black MTTF"
    "（+IPC-2152 ΔT 联合温度链 + 可选 Blech immortal 判据）联合报告。"
    "J 路由二选一：loss_density_w_per_m3（EM 场后处理局部焦耳体损耗，"
    "J=sqrt(q/ρ)，逐网格局部口径不做全局等效——高频趋肤下局部 J 高于截面"
    "均值）或 j_density_a_per_m2 直接给；ρ(T)=ρ_ref·(1+α·ΔT) 线性 TCR 修正"
    "（tcr_per_k 可选，铜 α=3.93e-3/K@20 °C 为模块常量非隐藏缺省）。"
    "T 路由二选一：temperature_c 直接给（IPC-2152 ΔT 联合=ipc2152 键输出"
    " delta_t_c 加环境温度后注入）或 Foster 热链 zth_r_c_per_w+zth_tau_s+"
    "power_w（三参同给，消费 MP-1 thermal_transient；time_s 缺省稳态 "
    "ΔT=P·ΣR 能量守恒锚）。Black：MTTF=A·J⁻ⁿ·exp(Ea/kT)，n 缺省 2.0"
    "（Black 1969 IEEE T-ED 原始口径），a_black/ea_ev 必填（Ea 随金属/工艺"
    "标定：Al 系 ~0.5–0.7 eV、Cu 系 ~0.8–1.0 eV 为文献量级语境非缺省值，"
    "MTTF 时间单位与 a_black 标定一致）；t_ref_af_c 给定时输出 Arrhenius "
    "AF=exp[(Ea/k)(1/T_use−1/T_stress)] 与参考温度 MTTF（恒等式 "
    "mttf_at_ref=mttf·AF）。Blech（segment_length_m 给则启用）：临界积 "
    "(jL)_c=Δσ·Ω/(|Z*|eρ)（Blech 1976 JAP 47:1203），j·L≤(jL)_c 判 "
    "immortal，Ω 缺省铜 1.1807e-29 m³（量级锚：Cu Δσ=50 MPa → "
    "(jL)_c≈2.1e3 A/cm=文献『Blech product ~2000 A/cm』带，判据对 Δσ "
    "线性敏感应按工艺标定）",
    (("loss_density_w_per_m3", "float W/m³ 局部焦耳体损耗密度（>0；与 "
      "j_density_a_per_m2 二选一，需 resistivity_ohm_m）"),
     ("j_density_a_per_m2", "float A/m² 直接给局部电流密度（>0；与 "
      "loss_density 二选一）"),
     ("resistivity_ohm_m", "float Ω·m 参考温度电阻率（>0；loss_density 路/"
      "Blech 判据必需，铜 1.724e-8@20 °C）"),
     ("tcr_per_k", "float 1/K 电阻温度系数（缺省不修正；铜 3.93e-3）"),
     ("t_ref_c", "float °C TCR 参考温度（缺省 20）"),
     ("temperature_c", "float °C 局部金属温度（与 Foster 热链二选一；"
      "IPC-2152 ΔT 联合=ambient+delta_t_c 经此注入）"),
     ("ambient_c", "float °C Foster 热链环境温度（缺省 25）"),
     ("zth_r_c_per_w", "array °C/W Foster 热阻链（与 zth_tau_s+power_w "
      "三参同给）"),
     ("zth_tau_s", "array s Foster 时间常数链（与热阻链等长）"),
     ("power_w", "float W 阶跃耗散功率（≥0；稳态 ΔT=P·ΣR）"),
     ("time_s", "float s 瞬态评估时刻（缺省稳态）"),
     ("a_black", "float Black 前置常数（>0；单位吸收时间标定，h·(J 单位)^n "
      "标定则 MTTF 返回小时）"),
     ("n_black", "float 电流密度指数（缺省 2.0=Black 1969 原始口径；≥0）"),
     ("ea_ev", "float eV 激活能（≥0；随金属/工艺标定，必填不内置缺省）"),
     ("t_ref_af_c", "float °C AF 参考温度（给则输出 AF 与参考 MTTF）"),
     ("segment_length_m", "float m 导体段长度（>0；给则启用 Blech 判据）"),
     ("delta_sigma_mpa", "float MPa 应力松弛窗（≥0；Blech 启用时必填）"),
     ("atomic_volume_m3", "float m³ 原子体积（缺省铜 1.1807e-29）"),
     ("zstar", "float 有效电荷数（非零，取 |Z*|；缺省 1.0）")),
    required=("a_black", "ea_ev"),
)
def electromigration_mttf_check(
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
    delta_sigma_mpa: float | None = None,
    atomic_volume_m3: float | None = None,
    zstar: float = 1.0,
) -> dict:
    from rfauto.core.electromigration import em_mttf_check as _check

    return _check(
        loss_density_w_per_m3=loss_density_w_per_m3,
        j_density_a_per_m2=j_density_a_per_m2,
        resistivity_ohm_m=resistivity_ohm_m,
        tcr_per_k=tcr_per_k,
        t_ref_c=t_ref_c,
        temperature_c=temperature_c,
        ambient_c=ambient_c,
        zth_r_c_per_w=zth_r_c_per_w,
        zth_tau_s=zth_tau_s,
        power_w=power_w,
        time_s=time_s,
        a_black=a_black,
        n_black=n_black,
        ea_ev=ea_ev,
        t_ref_af_c=t_ref_af_c,
        segment_length_m=segment_length_m,
        delta_sigma_pa=None if delta_sigma_mpa is None
        else delta_sigma_mpa * 1.0e6,
        atomic_volume_m3=atomic_volume_m3,
        zstar=zstar,
    )
