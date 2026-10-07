"""PLL 环路滤波器综合族（MT-5，内核在 core/pll_loop_filter.py，本模块只做注册壳）。

round17 §二 MT-5 规格「Banerjee SNAA106C（TI 免费）T1/T2/T3→C1/C2/R2/C3
闭式+相位裕度迭代；验收：回代 open_loop_transfer 复现目标 f_c/PM」
（2026-10-02）。单键 pll_loop_filter_synthesize（f_c/PM/环路增益数 →
T1/T2/T3+A0+元件值+复核残差+闭环带宽）；开环/闭环/误差/CP 噪声整形传函
为 core 纯函数不注册（分析面走 core 直调；pll_budget 既有语义零改动——
规格补强项「pll_budget 接 MT-5 综合入口」属消费侧接线，不在本件文件面）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "pll_loop_filter_synthesize",
    "MT-5 三阶 PLL 环路滤波器综合（round17 MT-5，Banerjee SNAA106C T1/T2/"
    "T3→C1/C2/R2/C3 闭式+相位裕度迭代）：给定环路带宽 f_c（开环穿越）与相位"
    "裕度 PM → 峰值相位放置（dPM/dω|ωc=0，Gardner 二阶几何中值放置的三阶"
    "推广；极点比 r=T3/T1 为显式设计自由度，>1）反解 T1/T2/T3，总电容 A0 由 "
    "|G(jωc)|=1 闭式回代，元件值 C1=A0·T1/T2、C2=A0·(T2−T1)/T2、R2=T2/C2、"
    "C3·R3=T3。结果带回代复核（穿越/PM 残差入字段）+闭环 −3dB 带宽+"
    "|H(jωc)|=1/(2sin(PM/2)) 恒等值+C3 加载比（无源网络 T 形近似有效域自查："
    "C3≪A0；有源拓扑 T 形精确）。可达 PM 窗随 r 收窄，窗外/PM∉(0°,90°)/"
    "r≤1 显式报错",
    (("f_c_hz", "float 目标开环穿越频率（环路带宽）Hz（>0）"),
     ("phase_margin_deg", "float 目标相位裕度 deg（开区间 0<PM<90）"),
     ("kp_a_per_rad", "float 电荷泵/鉴相增益 Kφ A/rad（>0）"),
     ("kvco_hz_per_v", "float VCO 压控灵敏度 Hz/V（>0；内核折 rad/s/V）"),
     ("n_div", "float 分频比 N（≥1；分数 N 合法）"),
     ("t3_t1_ratio", "float 极点比 r=T3/T1（>1，缺省 3.0；设计自由度）"),
     ("c3_frac", "float C3=A0×此份额（0<c≤0.5，缺省 0.1；r3_ohm 未给时生效）"),
     ("r3_ohm", "float 显式第三极点电阻 Ω（>0；给定时 C3=T3/R3 覆盖 c3_frac）")),
    required=("f_c_hz", "phase_margin_deg", "kp_a_per_rad",
              "kvco_hz_per_v", "n_div"),
)
def pll_loop_filter_synthesize(
    f_c_hz: float,
    phase_margin_deg: float,
    kp_a_per_rad: float,
    kvco_hz_per_v: float,
    n_div: float,
    t3_t1_ratio: float = 3.0,
    c3_frac: float = 0.1,
    r3_ohm: float | None = None,
) -> dict:
    from rfauto.core.pll_loop_filter import synthesize_loop_filter as _core

    return _core(
        f_c_hz,
        phase_margin_deg,
        kp_a_per_rad,
        kvco_hz_per_v,
        n_div,
        t3_t1_ratio=t3_t1_ratio,
        c3_frac=c3_frac,
        r3_ohm=r3_ohm,
    ).to_dict()
