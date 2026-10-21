"""功率校准链族（SB22-MS-1，内核在 core/power_calibration.py，本模块只做注册壳）。

出处（功率计量工程口径，正文与锚树转录）：
- power_cal_chain：校准因子补偿/平缆损耗补偿/失配修正三档链
  （微波功率计量工程惯例，二级转引 Keysight 功率测量应用指南家族
  口径）；GUM 合成不确定度预算（JCGM 100:2008）。

单键 power_cal_chain：功率计读数 → 校准因子补偿 → 平缆损耗补偿 →
源匹配/失配修正（none/band/exact 三档）→ 远端平面可用功率 + GUM 合成
不确定度预算。calibration_factor/type_b_standard_u/power_cal_uncertainty/
model_meter_reading_dbm/cal_verification 为 core 纯函数不注册（分析面走
core 直调；回收钉与文献数值例锚在 tests/unit/test_power_calibration.py）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "power_cal_chain",
    "功率校准链：SB22-MS-1 功率校准补偿链（读数 → 远端平面可用功率 + GUM 预算，"
    "确定性闭式）：①传感器校准因子补偿 P_inc=P_read−10lg K_b"
    "（K_b=η(1−|Γl|²)，Keysight AN 64-1A 定义）；②平缆损耗补偿 "
    "+L；③源匹配校正 +10lg(1/(1−|Γs|²))；④失配相位项 "
    "+20lg|1−ΓsΓl|——exact 模式逐点精确修正，band 模式相位未知只给 "
    "±MU=20lg(1+|Γs||Γl|) 带（U 形 u=MU/√2，JCGM 100:2008 §4.3.9；"
    "文献数值例 SWR1.5×1.25→±0.19 dB，Keysight AN 1449-3 与 R&S 失配表"
    "双源）。u_components B 类组件（rectangular a/√3=§4.3.7 / ushaped "
    "a/√2=§4.3.9）或已标准 u_db 直收，合成 u_c=√Σu²、展开 U=k=2。"
    "诚实边界：缆 S 参数级联失配与 |Γ| 自身不确定度不在本域（调用方以"
    "同一参考面等效 Γ 给入）；逐频点由调用方逐点调用。",
    (("p_read_dbm", "float dBm 功率计原始读数"),
     ("k_cal_lin", "float 线性 传感器校准因子 K_b=η(1−|Γl|²)（(0,1]）"),
     ("cable_loss_db", "float dB 传感器平面→远端平面平缆损耗（>=0，缺省 0）"),
     ("gamma_source", "list[float] 源反射 [re, im]（|Γ|<1，缺省 [0,0]）"),
     ("gamma_load", "list[float] 传感器侧反射 [re, im]（|Γ|<1，缺省 [0,0]）"),
     ("mismatch_mode", "str 'none'/'band'/'exact'（缺省 'none'）"),
     ("u_components", "list[dict] 可选不确定度组件 [{name, u_db} 或 "
      "{name, half_width_db, distribution: 'rectangular'|'ushaped'}]")),
    required=("p_read_dbm", "k_cal_lin"),
)
def power_cal_chain(
    p_read_dbm: float,
    k_cal_lin: float,
    cable_loss_db: float = 0.0,
    gamma_source: list | None = None,
    gamma_load: list | None = None,
    mismatch_mode: str = "none",
    u_components: list | None = None,
) -> dict[str, Any]:
    from rfauto.core.power_calibration import calibrate_power_chain

    if gamma_source is None:
        gamma_source = [0.0, 0.0]
    if gamma_load is None:
        gamma_load = [0.0, 0.0]
    for nm, val in (("gamma_source", gamma_source),
                    ("gamma_load", gamma_load)):
        if not isinstance(val, (list, tuple)) or len(val) != 2:
            raise ValueError(
                f"{nm} 必须是 [re, im] 两元素，收到 {val!r}")
    return calibrate_power_chain(
        p_read_dbm=p_read_dbm,
        k_cal_lin=k_cal_lin,
        cable_loss_db=cable_loss_db,
        gamma_source=complex(float(gamma_source[0]), float(gamma_source[1])),
        gamma_load=complex(float(gamma_load[0]), float(gamma_load[1])),
        mismatch_mode=mismatch_mode,
        u_components=u_components,
    )
