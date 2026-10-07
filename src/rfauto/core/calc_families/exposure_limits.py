"""RF 暴露限值族（内核在 core/exposure_limits.py，本模块只做注册壳）。"""

from __future__ import annotations

from .registry import register_calculator

# ─── r6 池「RF 暴露限值 quick-win」（ge6 pool3，2026-09-30）─────────────────
# FCC 47 CFR §1.1310(e)(1) Table 1（职业/公众双表）+ ICNIRP 2020 Table 5
# 全身平均公众参考水平——2026-09-30 回原文逐位核对（eCFR 当前版/ICNIRP
# 官方 PDF），表值与出处注记见 core/exposure_limits.py docstring。
# 距离=EIRP 定义球面 S=EIRP/(4πR²) 反解（远场；近场如实声明不判）。
# 本族为规范事实查表面：数值=表值+确定性闭式，零经验拟合。


@register_calculator(
    "exposure_mpe_limit",
    "RF 暴露 MPE/参考水平查表：FCC 47 CFR §1.1310(e)(1) Table 1"
    "（fcc_occupational/fcc_general）+ ICNIRP 2020 Table 5 全身平均"
    "公众（icnirp_public）→ E(V/m)/H(A/m)/S(W/m²) 限值与平均时间；"
    "域外显式拒绝（FCC 0.3–100000 MHz、ICNIRP 0.1–300000 MHz）",
    (("freq_hz", "float Hz 工作频率"),
     ("standard", "str - fcc_occupational|fcc_general|icnirp_public")),
    required=("freq_hz",),
)
def exposure_mpe_limit(freq_hz: float, standard: str = "fcc_general") -> dict:
    from rfauto.core.exposure_limits import mpe_limit

    return mpe_limit(freq_hz, standard)


@register_calculator(
    "exposure_compliance_distance",
    "EIRP 合规距离（远场球面反解）：R=√(EIRP_W/(4π·S_lim))；同几何"
    "远场 E=√(30·EIRP)/R 与 S=E²/η0 恒等（η0=4π·30）；plane_wave"
    "_equiv 段（FCC <300 MHz）如实标注；无 S 列段（ICNIRP 0.1–30 MHz"
    "恒近场域）显式拒绝；近场不判（note 声明）",
    (("eirp_w", "float W 等效全向辐射功率（线性瓦，>0）"),
     ("freq_hz", "float Hz 工作频率"),
     ("standard", "str - fcc_occupational|fcc_general|icnirp_public")),
    required=("eirp_w", "freq_hz"),
)
def exposure_compliance_distance(eirp_w: float, freq_hz: float,
                                 standard: str = "fcc_general") -> dict:
    from rfauto.core.exposure_limits import mpe_distance

    return mpe_distance(eirp_w, freq_hz, standard)
