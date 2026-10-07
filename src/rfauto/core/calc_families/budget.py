"""DP-5 系统级预算引擎 + 混频杂散搜索（payload 在 core/cascade.py）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from .registry import register_calculator

# ─── DP-5 系统级预算引擎 + 混频杂散搜索（payload 在 core/cascade.py）──────────
# 公式口径/规格书勘误（IIP3 级联式增益落分子）/经验口径标注见 core/cascade.py
# 模块 docstring 与 runs/df6_dp5cascade/criteria.md §0；回收钉在
# tests/unit/test_cascade.py（≤1e-12 逐位）。


@register_calculator(
    "cascade_budget",
    "DP-5 级联预算：stage 列表 → 总增益/Friis NF/IIP3·OIP3 级联/P1dB(经验幂和)/"
    "噪声底/SFDR/灵敏度/链路裕量。stage schema type∈{amp,mixer,filter,atten,"
    "cable}；无源级 NF 缺省=插损（T0）；skrf 真实插损解析在 service 层",
    (("stages", "list[dict] 级表（顺序=信号流向；type/gain_db/nf_db?/"
      "iip3_dbm?/p1db_dbm?/bw_hz?）"),
     ("snr_min_db", "float dB 解调最小 SNR（默认 10）"),
     ("rx_power_dbm", "float dBm 接收功率（可选，给定时输出链路裕量）"),
     ("bw_hz", "float Hz 系统噪声带宽（缺省取末级 bw_hz，皆无则显式报错）"),
     ("t_kelvin", "float K 等效热噪声温度（默认 290）")),
    required=("stages",),
)
def cascade_budget(stages: list[dict], snr_min_db: float = 10.0,
                   rx_power_dbm: float | None = None,
                   bw_hz: float | None = None,
                   t_kelvin: float = 290.0) -> dict:
    from rfauto.core.cascade import cascade_budget as _cascade_budget

    return _cascade_budget(stages, snr_min_db=snr_min_db,
                           rx_power_dbm=rx_power_dbm, bw_hz=bw_hz,
                           t_kelvin=t_kelvin)


@register_calculator(
    "spur_search",
    "DP-5 混频杂散落带搜索：f_spur=|m·f_RF±n·f_LO| 全阶枚举（缺省 m+n≤7），"
    "矩形近似卷积落带判据，危险等级=阶数反比；只报频率落带不报电平",
    (("f_rf_hz", "float Hz RF 中心频率（>0）"),
     ("f_lo_hz", "float Hz 本振频率（>0）"),
     ("if_center_hz", "float Hz 目标 IF 中心（缺省 |f_RF−f_LO|）"),
     ("if_bw_hz", "float Hz 目标带宽（默认 0）"),
     ("rf_bw_hz", "float Hz RF 信号带宽（默认 0，谐波带宽线性缩放）"),
     ("lo_bw_hz", "float Hz LO 带宽（默认 0=理想 LO）"),
     ("max_order", "int 最大阶数 m+n（默认 7）")),
    required=("f_rf_hz", "f_lo_hz"),
)
def spur_search(f_rf_hz: float, f_lo_hz: float,
                if_center_hz: float | None = None, if_bw_hz: float = 0.0,
                rf_bw_hz: float = 0.0, lo_bw_hz: float = 0.0,
                max_order: int = 7) -> dict:
    from rfauto.core.cascade import spur_search as _spur_search

    spurs = _spur_search(
        f_rf_hz, f_lo_hz, if_center_hz=if_center_hz, if_bw_hz=if_bw_hz,
        rf_bw_hz=rf_bw_hz, lo_bw_hz=lo_bw_hz, max_order=max_order)
    n_in_band = sum(1 for s in spurs if s["in_band"] and s["role"] == "spur")
    return {"n_products": len(spurs), "n_spurs_in_band": n_in_band,
            "f_rf_hz": f_rf_hz, "f_lo_hz": f_lo_hz,
            "if_center_hz": (abs(f_rf_hz - f_lo_hz)
                             if if_center_hz is None else if_center_hz),
            "max_order": max_order, "spurs": spurs}


@register_calculator(
    "if_plan_sweep",
    "DP-5 IF 频率规划扫掠：IF 候选网格逐点重取本振（low/high 侧注入）→ 逐点"
    "杂散落带判定 + spurious-free 窗口表（窗口边界=网格分辨率内）",
    (("f_rf_hz", "float Hz RF 中心频率（>0）"),
     ("if_lo_hz", "float Hz IF 扫掠下限（>0）"),
     ("if_hi_hz", "float Hz IF 扫掠上限（low 侧须 <f_RF）"),
     ("side", "str 注入侧 'low'|'high'（默认 low：f_LO=f_RF−IF）"),
     ("n_points", "int 网格点数（默认 201）"),
     ("if_bw_hz", "float Hz 目标带宽（默认 0）"),
     ("rf_bw_hz", "float Hz RF 信号带宽（默认 0）"),
     ("lo_bw_hz", "float Hz LO 带宽（默认 0）"),
     ("max_order", "int 最大阶数 m+n（默认 7）")),
    required=("f_rf_hz", "if_lo_hz", "if_hi_hz"),
)
def if_plan_sweep(f_rf_hz: float, if_lo_hz: float, if_hi_hz: float,
                  side: str = "low", n_points: int = 201,
                  if_bw_hz: float = 0.0, rf_bw_hz: float = 0.0,
                  lo_bw_hz: float = 0.0, max_order: int = 7) -> dict:
    from rfauto.core.cascade import if_plan_sweep as _if_plan_sweep

    return _if_plan_sweep(
        f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz, side=side,
        n_points=n_points, if_bw_hz=if_bw_hz, rf_bw_hz=rf_bw_hz,
        lo_bw_hz=lo_bw_hz, max_order=max_order)
