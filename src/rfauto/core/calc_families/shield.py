"""QW-11 屏蔽效能（Schelkunoff 平面波三段闭式）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from .registry import register_calculator
from .rfid import _rfid_num

# ─── QW-11 屏蔽效能（Schelkunoff 平面波三段闭式，2026-09-26）─────────────────

_ETA0_OHM = 376.730313668  # 自由空间波阻抗 Ω（与 core/coupled_microstrip.ZF0_OHM 同值）
_MU0_H_PER_M = 4.0e-7 * math.pi  # 真空磁导率（SI 定义值）

# 近似电导率/相对磁导率（S/m, -）。来源：Ott《Electromagnetic Compatibility
# Engineering》2009 第 6 章常用屏蔽材料典型值（copper 5.8e7 与本仓
# core/synthesis.Stackup.rho=1.724e-8 Ω·m 同源；aluminum 3.5e7；brass
# 1.5e7；低碳钢 1.0e7/μr≈100）。本表取典型值口径：钢族 μr 随合金成分与
# 磁场强度大幅变化，表值为典型低场近似，精确设计须以实测为准；显式传
# conductivity_s_per_m/mu_r 时直给值优先于本表。
_SHIELD_MATERIALS: dict[str, tuple[float, float]] = {
    "copper": (5.8e7, 1.0),
    "aluminum": (3.5e7, 1.0),
    "brass": (1.5e7, 1.0),
    "steel_low_carbon": (1.0e7, 100.0),
}


@register_calculator(
    "shielding_effectiveness",
    "屏蔽效能（Schelkunoff 平面波三段闭式）：SE=A+R+B——吸收 "
    "A=20lg|e^{γt}|=8.686·t/δ（γ=(1+j)/δ 良导体）；反射 "
    "R=20lg|(Z_w+Z_s)²/(4Z_w Z_s)|（Z_s=√(jωμ/σ) 表面阻抗、"
    "Z_w=η0=376.73Ω 平面波）；多次反射修正 B=20lg|1−Γ²e^{−2γt}|"
    "（Γ=(Z_s−Z_w)/(Z_s+Z_w)；厚屏蔽 e^{−2γt}→0 ⟹ B→0，薄屏蔽 t<δ "
    "时 B<0 负贡献）。屏蔽体=有耗传输线段（Schelkunoff 1934 TL 类比；"
    "Ott 2009 §6），恒等式 SE_total≡−20lg|S21_ABCD| 由单测钉住；"
    "近场源（电/磁偶极）阻抗修正未实现，source 仅支持 plane_wave",
    (("frequency_hz", "float Hz 单点频率（与 f_axis_hz 二选一，同给显式拒绝）"),
     ("f_axis_hz", "list Hz 频率轴（逐点 >0；与 frequency_hz 二选一）"),
     ("thickness_m", "float m 屏蔽体厚度（>0）"),
     ("conductivity_s_per_m", "float S/m 电导率（>0；与 material 二选一，直给优先）"),
     ("mu_r", "float - 相对磁导率（>0，默认 1.0；material 命中表时取表值）"),
     ("material", "str 材料键（copper/aluminum/brass/steel_low_carbon，见 _SHIELD_MATERIALS）"),
     ("source", "str 源口径（仅 plane_wave；近场修正未实现，显式拒绝）")),
    required=("thickness_m",),
)
def shielding_effectiveness(
    frequency_hz: float | None = None,
    thickness_m: float | None = None,
    conductivity_s_per_m: float | None = None,
    mu_r: float = 1.0,
    material: str | None = None,
    f_axis_hz: Sequence[float] | None = None,
    source: str = "plane_wave",
) -> dict[str, Any]:
    """平面波屏蔽效能三段闭式（Schelkunoff TL 类比；Ott 2009 §6）。

    物理链（良导体口径，出处逐式）：
    - 趋肤深度 δ=√(2/(ωμσ))，传播常数 γ=(1+j)/δ（Pozar §1.4 良导体极限）；
    - 表面阻抗 Z_s=√(jωμ/σ)（|Z_s|=√(ωμ/σ)）；入射波阻抗 Z_w=η0（平面波）；
    - 吸收 A=20lg|e^{γt}|=(20/ln10)·t/δ；
    - 反射 R=20lg|(Z_w+Z_s)²/(4Z_w Z_s)|；
    - 多次反射修正 B=20lg|1−Γ²e^{−2γt}|，Γ=(Z_s−Z_w)/(Z_s+Z_w)——由
      屏蔽体有耗传输线段 ABCD=[cosh γt, Z_s sinh γt; sinh γt/Z_s, cosh γt]
      嵌入 Z_w 系统的精确透射 |S21|=|1−Γ²|/(|e^{γt}||1−Γ²e^{−2γt}|) 严格
      分解而来（SE=A+R+B 恒等精确，非近似拼合）；
    - 薄屏蔽 t<δ 时 |1−Γ²e^{−2γt}|<1 ⟹ B<0（负贡献口径，如实保留）。

    Returns:
        JSON 可序列化 dict：{f_hz, skin_depth_m, se_absorption_db,
        se_reflection_db, se_multiple_db, se_total_db（均为逐频列表）,
        conductivity_s_per_m, mu_r, material, note}。
    """
    if str(source) != "plane_wave":
        raise ValueError(
            f"source 仅支持 'plane_wave'（近场电/磁偶极源阻抗修正未实现，"
            f"不做虚构），got {source!r}")
    if (frequency_hz is None) == (f_axis_hz is None):
        raise ValueError("frequency_hz 与 f_axis_hz 须二选一（同给/都缺显式拒绝）")
    t_m = _rfid_num(thickness_m, "thickness_m")
    if t_m <= 0.0:
        raise ValueError("thickness_m 必须 >0（t=0 无屏蔽体）")
    if frequency_hz is not None:
        f_list = [_rfid_num(frequency_hz, "frequency_hz")]
    else:
        f_axis = list(f_axis_hz)  # type: ignore[arg-type]
        if not f_axis:
            raise ValueError("f_axis_hz 不能为空")
        f_list = [_rfid_num(v, f"f_axis_hz[{i}]") for i, v in enumerate(f_axis)]
    for i, f_v in enumerate(f_list):
        if f_v <= 0.0:
            raise ValueError(f"频率必须 >0（f=0 显式拒绝），f_axis_hz[{i}]={f_v}")

    mu_r_v = _rfid_num(mu_r, "mu_r")
    if mu_r_v <= 0.0:
        raise ValueError("mu_r 必须 >0")
    material_key: str | None = None
    if conductivity_s_per_m is not None:
        sigma = _rfid_num(conductivity_s_per_m, "conductivity_s_per_m")
        if sigma <= 0.0:
            raise ValueError("conductivity_s_per_m 必须 >0（σ=0 显式拒绝）")
        mu_use = mu_r_v
    elif material is not None:
        material_key = str(material).lower()
        if material_key not in _SHIELD_MATERIALS:
            raise ValueError(
                f"未知屏蔽材料 {material!r}（可用: "
                f"{sorted(_SHIELD_MATERIALS)}）")
        sigma, table_mu_r = _SHIELD_MATERIALS[material_key]
        mu_use = table_mu_r
    else:
        raise ValueError(
            "conductivity_s_per_m 与 material 须二选一（都缺显式拒绝）")

    f_arr = np.asarray(f_list, dtype=float)
    omega = 2.0 * math.pi * f_arr
    mu = _MU0_H_PER_M * mu_use
    delta = np.sqrt(2.0 / (omega * mu * sigma))
    gamma = (1.0 + 1j) / delta
    z_s = np.sqrt(1j * omega * mu / sigma)
    z_w = _ETA0_OHM
    refl_coef = (z_s - z_w) / (z_s + z_w)
    se_a = (20.0 / math.log(10.0)) * (t_m / delta)
    se_r = 20.0 * np.log10(np.abs((z_w + z_s) ** 2 / (4.0 * z_w * z_s)))
    se_b = 20.0 * np.log10(np.abs(
        1.0 - refl_coef ** 2 * np.exp(-2.0 * gamma * t_m)))
    se_total = se_a + se_r + se_b
    return {
        "f_hz": [round(float(v), 6) for v in f_arr],
        "skin_depth_m": [round(float(v), 15) for v in delta],
        "se_absorption_db": [round(float(v), 9) for v in se_a],
        "se_reflection_db": [round(float(v), 9) for v in se_r],
        "se_multiple_db": [round(float(v), 9) for v in se_b],
        "se_total_db": [round(float(v), 9) for v in se_total],
        "conductivity_s_per_m": round(float(sigma), 12),
        "mu_r": round(float(mu_use), 12),
        "material": material_key,
        "note": "Schelkunoff 平面波三段闭式（吸收/反射/多次反射，"
                "SE=A+R+B≡−20lg|S21_ABCD| 恒等）；薄屏蔽 t<δ 时多次反射"
                "修正为负贡献；近场源（电/磁偶极）阻抗修正未实现"}
