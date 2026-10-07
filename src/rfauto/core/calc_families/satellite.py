"""satellite 族（AP-9 卫星链路预算器，§A-10，追加尾位 2026-10-02）。

内核在 core/sat_link.py（纯函数零 IO），本模块只做注册薄壳
（同 link/propagation 惯例）。单键 sat_link_budget：单跳卫星链路预算
（EIRP→FSPL+pointing+gas+rain→G/T（core/gt_link 单源复用）→C/N0→
C/N→margin 逐项），LEO 圆轨几何（斜距/多普勒）随 elevation+alt 模式
自算；MODCOD 表 UNVERIFIED 档不做（解调需求显式输入）。slant_range_km/
doppler_hz/fspl_db 为纯辅助不注册（report 内随 geometry/path 承载）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "sat_link_budget",
    "AP-9 单跳卫星链路预算（JSON 进出，级表逐项风格）：C/N0 = EIRP − "
    "(FSPL+pointing+gas+rain) + G/T + 228.599（k=SI 精确值单源）。LEO 几何 "
    "elevation_deg∈(0,90]+alt_km>0 自算斜距 d=√((Re+h)²−(Re·cosE)²)−Re·sinE "
    "与圆轨多普勒（rising/setting 反号；Re=6378km、GM=WGS-84 惯例），或 "
    "slant_km 直接给；G/T 单源复用 gt_link（t_sys_k/nf_db/t_e_k 三路径）。"
    "gas 项走 itu_atmosphere 降级面（P.676 表 UNVERIFIED→gas_db=0+注记，"
    "不产假数）；MODCOD 表 UNVERIFIED 档不做——margin 依据显式需求门 "
    "required_cn0_db_hz/required_cn_db/required_ebno_db，只出到 C/N0→C/N→"
    "margin。域守卫：仰角/高度/频率/损耗非负显式 ValueError",
    (("link", "dict 链路描述（schema 见 core/sat_link.py sat_link_budget "
      "docstring：tx/path/rx 三段 + 可选 bw_hz/rb_bps/required_*）"),),
    required=("link",),
)
def sat_link_budget(link: dict) -> dict:
    from rfauto.core.sat_link import sat_link_budget as _sat_link_budget

    return _sat_link_budget(link)
