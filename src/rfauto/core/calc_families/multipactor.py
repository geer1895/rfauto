"""multipactor 微放电击穿阈值族（MP-3，内核在 core/multipactor.py，
本模块只做注册壳）。

round15 §三 :84 规格「Vaughan 二次发射+20-gap 串接+N 载波等效功率
（IEEE 10904461 2025）」（2026-10-02）。单键 multipactor_susceptibility_check
（施加峰值电压对平行板一阶渡越敏感带 × SEY crossover 窗口的合成裕量
报告）；transit_resonance_voltage_v/susceptibility_band_v/vaughan_yield/
sey_crossover_energies_ev/角依赖/多载波等效功率/串接链换算为 core
纯函数不注册（分析面走 core 直调；工程仲裁面仍在 high_power 的 ECSS
f·d 实验包络 ecss_multipactor_fd，本族不与其语义重叠——verdict 语义仅对
一阶理想化模型自洽，报告 notes 固定指向 ECSS 仲裁）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "multipactor_susceptibility_check",
    "MP-3 multipactor 微放电击穿阈值（round15 :84，Vaughan 二次发射+20-gap "
    "串接+N 载波等效功率语境）：施加峰值电压对平行板一阶渡越敏感带 × SEY "
    "crossover 窗口的合成裕量报告。每序 n=1..order_max 的封闭周期轨道带 "
    "V∈[K/√(4+(2n−1)²π²), K/2]（K=4π²(m_e/e)(f·d)² 相似标度）经碰撞能量 "
    "窗口 E_imp∈(E1,E2) 门控（δ>1 判据，Kishek & Lau PAC97 口径）后给可"
    "持续带；落带内判模型敏感。SEY 窗口 e1_ev/e2_ev 可显式给出（VERIFIED）"
    "或缺省由 Vaughan 普适曲线 δ=δmax·(v·e^{1−v})^{k_s} 派生（曲线形状 "
    "UNVERIFIED，判定只消费 crossover）。载波表 carrier_powers_w 支持 "
    "非相干 RSS（ECSS 口径 P_eq=ΣPi，缺省）与相干最坏相位（P_eq=(Σ√Pi)²）"
    "双口径。verdict 仅对一阶理想化模型自洽（零初速发射）；工程仲裁走 "
    "high_power 的 ECSS-E-ST-20-01C 实验包络 ecss_multipactor_fd（报告 "
    "notes 固定指向）。margin=阈值/施加（dB），≥required_margin_db 判过",
    (("freq_ghz", "float GHz 工作频率（>0）"),
     ("gap_mm", "float mm 平行板临界间隙（>0）"),
     ("voltage_v", "float V 施加峰值电压（优先；与功率/载波三选一）"),
     ("power_w", "float W 单载波功率（配 z0_ohm：V=√(2PZ0)）"),
     ("z0_ohm", "float Ω 系统阻抗（默认 50）"),
     ("carrier_powers_w", "array W 各载波平均功率（触发多载波等效口径）"),
     ("carrier_coherent", "bool 载波相干最坏相位口径（缺省 False=RSS）"),
     ("delta_max", "float SEY 峰值 δmax（>1；缺省 2.0=UNVERIFIED 形状面）"),
     ("emax_ev", "float SEY 峰值能量 Emax eV（缺省 300=UNVERIFIED 形状面）"),
     ("e1_ev", "float 第一 crossover 能量 eV（与 e2_ev 成对；VERIFIED 判据面）"),
     ("e2_ev", "float 第二 crossover 能量 eV（与 e1_ev 成对；需 >e1）"),
     ("k_s", "float Vaughan 表面粗糙度因子（>0，缺省 1=光滑）"),
     ("order_max", "int 扫描最高序数（>=1，缺省 10）"),
     ("required_margin_db", "float dB 要求裕量（默认 6）")),
    required=("freq_ghz", "gap_mm"),
)
def multipactor_susceptibility_check(
    freq_ghz: float,
    gap_mm: float,
    voltage_v: float | None = None,
    power_w: float | None = None,
    z0_ohm: float = 50.0,
    carrier_powers_w: list | None = None,
    carrier_coherent: bool = False,
    delta_max: float = 2.0,
    emax_ev: float = 300.0,
    e1_ev: float | None = None,
    e2_ev: float | None = None,
    k_s: float = 1.0,
    order_max: int = 10,
    required_margin_db: float = 6.0,
) -> dict:
    from rfauto.core.multipactor import (
        multipactor_susceptibility_check as _check,
    )

    return _check(
        freq_ghz * 1.0e9,
        gap_mm * 1.0e-3,
        voltage_v=voltage_v,
        power_w=power_w,
        z0_ohm=z0_ohm,
        carrier_powers_w=carrier_powers_w,
        carrier_coherent=carrier_coherent,
        delta_max=delta_max,
        emax_ev=emax_ev,
        e1_ev=e1_ev,
        e2_ev=e2_ev,
        k_s=k_s,
        order_max=order_max,
        required_margin_db=required_margin_db,
    )
