"""电晕/局放判据族（MP-2，内核在 core/corona.py，本模块只做注册壳）。

round15 §三 :82 规格「电晕/局放判据（Paschen+海拔降额）入 high_power，
ECSS-E-ST-10-04C 语境」（2026-10-02）。单键 corona_pd_check（施加电压对
空气隙的击穿/局放/电晕三面裕量报告）；isa_pressure_pa/isa_temperature_c/
air_density_factor/townsend_paschen_voltage_v/schumann 空气式/peek 起始场
与几何因子为 core 纯函数不注册（分析面走 core 直调；高功率击穿主面仍在
core/high_power.py，本族是其中压/海拔降额伴生判据，不与其语义重叠）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "corona_pd_check",
    "MP-2 电晕/局放判据（round15 :82，Paschen+海拔降额，ECSS-E-ST-10-04C "
    "语境）：施加电压（峰值口径）对空气隙的击穿/局放/电晕三面裕量报告。"
    "击穿面=Schumann 空气均匀场工程式（V_b=24.22x+6.08√x kV，x=δ·d cm；"
    "1mm 海平面 4.345 kV 经典锚）主判，Townsend-Paschen 物理形式"
    "（L&L Table 14.1 空气常数）作参照列；局放面=均匀隙起始（空洞尺寸 "
    "pd_gap_mm 缺省=gap，更小时先于击穿面 binding）；电晕面=Peek 起始场"
    "（δ 空气密度修正）×几何因子（coax/two_wire/wire_plane，镜像定理 "
    "wire_plane(h)≡two_wire(2h)）。气压由 ISA/US 1976 按海拔换算"
    "（0–20 km，可 pressure_pa 覆盖）；气温缺省 25 °C 参考标准日"
    "（忽略高空低温对降额偏保守，可显式注入 isa_temperature_c(alt)）。"
    "margin=限值/施加，≥safety_factor 判过；pass=已计算面合取",
    (("voltage_v", "float 施加电压峰值 V（>0）"),
     ("gap_mm", "float 空气隙距离 mm（>0；击穿判据对象）"),
     ("geometry", "str 'uniform_gap'|'coax'|'two_wire'|'wire_plane'"
      "（默认 'uniform_gap'；非 uniform 需 r_mm+d_mm 触发电晕面）"),
     ("r_mm", "float 导体半径 mm（coax 内半径/two_wire 线半径/"
      "wire_plane 线半径；>0）"),
     ("d_mm", "float coax 外半径 R/two_wire 中心距 D/wire_plane 对地高度"
      " h（mm；需满足 R>r、D>2r、h>r）"),
     ("pd_gap_mm", "float 局放对象空洞特征尺寸 mm（缺省=gap_mm；"
      "空洞<间隙即经典'空洞局放'形态）"),
     ("altitude_m", "float 海拔 m（0–20000；默认 0；ISA 标准大气，"
      "20 km 以上近真空走 high_power multipactor 面）"),
     ("pressure_pa", "float 显式气压 Pa（>0；给定时覆盖 ISA 换算）"),
     ("temperature_c", "float 气温 °C（缺省 25 °C 参考标准日；ISA 剖面"
      "可经 core.corona.isa_temperature_c(alt) 显式注入）"),
     ("roughness", "float 导线表面粗糙度系数 m0（>0，缺省 1=光滑；"
      "<1 为工程粗糙面降额）"),
     ("safety_factor", "float 要求安全系数（缺省 1.0；margin≥sf 判过）"),
     ("e0_kv_per_cm", "float Peek E_0（缺省 30 kV/cm 峰值口径；"
      "rms 口径给 21.1）"),
     ("k", "float Peek k（缺省 0.301；rms 口径给 0.3081）")),
    required=("voltage_v", "gap_mm"),
)
def corona_pd_check(
    voltage_v: float,
    gap_mm: float,
    geometry: str = "uniform_gap",
    r_mm: float | None = None,
    d_mm: float | None = None,
    pd_gap_mm: float | None = None,
    altitude_m: float = 0.0,
    pressure_pa: float | None = None,
    temperature_c: float | None = None,
    roughness: float = 1.0,
    safety_factor: float = 1.0,
    e0_kv_per_cm: float = 30.0,
    k: float = 0.301,
) -> dict:
    from rfauto.core.corona import corona_pd_check as _check

    return _check(
        voltage_v,
        gap_mm * 1.0e-3,
        geometry=geometry,
        radius_m=None if r_mm is None else r_mm * 1.0e-3,
        spacing_m=None if d_mm is None else d_mm * 1.0e-3,
        pd_gap_m=None if pd_gap_mm is None else pd_gap_mm * 1.0e-3,
        altitude_m=altitude_m,
        pressure_pa=pressure_pa,
        temperature_c=temperature_c,
        roughness=roughness,
        safety_factor=safety_factor,
        e0_kv_per_cm=e0_kv_per_cm,
        k=k,
    )
