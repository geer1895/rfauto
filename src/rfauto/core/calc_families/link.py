"""link 族（LT-1 G/T 组合键，round18 :129，追加尾位 2026-10-02）。

内核在 core/gt_link.py（纯函数零 IO），本模块只做注册薄壳
（同 exposure_limits/t_match 惯例）。键名与 cascade_budget 输出字段
（gain_total_db/nf_total_db）同名直连——级联面输出即本键输入。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "gt_ratio",
    "LT-1 G/T 组合优值（ITU-R S.733-2 定义口径）：G/T = G_dB − "
    "10·log10(T_sys) [dB/K]。T_sys 三路径显式择一：t_sys_k 直接给定 / "
    "nf_db（=cascade_budget.nf_total_db 直连，Te=T0·(F−1)）/ t_e_k"
    "（=nf_measurement y-factor 链等效输入噪声温度）；t_ant_k 并入系统"
    "温度，三者全缺省时退化为 antenna_only（T_sys=t_ant_k，如实标注）。"
    "t_sys_k/nf_db/t_e_k 同给按优先级取用并如实报告冗余",
    (("gain_db", "float dB 接收链指向源方向总增益"
      "（cascade_budget.gain_total_db 同名直连）"),
     ("t_sys_k", "float K 系统噪声温度直接给定（可选，优先级最高）"),
     ("nf_db", "float dB 系统总噪声系数（可选；→ Te=T0·(F−1)）"),
     ("t_e_k", "float K 接收机等效输入噪声温度（可选，nf_measurement "
      "te_from_y 链输出）"),
     ("t_ant_k", "float K 天线噪声温度（默认 290）"),
     ("t0_k", "float K NF→Te 换算基准（默认 290，IEEE 口径）")),
    required=("gain_db",),
)
def gt_ratio(gain_db: float, t_sys_k: float | None = None,
             nf_db: float | None = None, t_e_k: float | None = None,
             t_ant_k: float = 290.0, t0_k: float = 290.0) -> dict:
    from rfauto.core.gt_link import gt_ratio as _gt_ratio

    return _gt_ratio(gain_db, t_sys_k=t_sys_k, nf_db=nf_db, t_e_k=t_e_k,
                     t_ant_k=t_ant_k, t0_k=t0_k)
