"""LT-1 G/T 组合键（round18 :129，射电天文/卫星接收优值，2026-10-02）。

定义（ITU-R S.733-2 方法口径 / 标准 link-budget 优值）：

    G/T = G_dB − 10·log10(T_sys_K)      [dB/K]

其中 T_sys 为指向源方向的系统噪声温度（天线温度 + 接收机等效输入噪声温度）。
三条 T_sys 路径（显式互斥选择，is not None 判缺失 #364④）：

    1. t_sys_k 直接给定                        → path="t_sys_direct"
    2. nf_db（级联总 NF，cascade_budget 的
       nf_total_db 同名直连）：Te=T0·(F−1)，
       T_sys = t_ant_k + Te                    → path="nf"
    3. t_e_k（nf_measurement.y_factor/
       te_from_y 链的等效输入噪声温度），
       T_sys = t_ant_k + t_e_k                 → path="te"

t_sys_k/t_e_k 均缺省时 T_sys = t_ant_k（无源天线仅自身物理温度的
"antenna_only" 路径，如实标注不混同系统噪声）。T0 = 290 K（IEEE 噪声
温度基准，与 core/nf_measurement.py T0_K 同源同值）。

消费面（round18 "cascade+nf_measurement 直连"）：输入名与
cascade_budget 输出字段 gain_total_db/nf_total_db 同名——级联输出直接
喂本键；Te 亦可取自 nf_measurement.y_factor → te_from_y 链。

边界语义：G/T 分母 T_sys>0 域守卫（T_sys≤0 显式 ValueError）；数值
合法性检查同 exposure_limits._num 口径（bool 显式拒收，有限数）。
纯函数零 IO；返回 JSON 可序列化 dict；方法出处 ITU-R S.733-2
《Calculation of non-line-of-sight gain/noise-temperature ratio》
（定义级引用；数值锚=恒等式回收，见 tests/unit/test_gt_link_calculators.py）。
"""

from __future__ import annotations

import math
from typing import Any

T0_K = 290.0  # IEEE 噪声温度基准（与 nf_measurement.T0_K 同值同源）


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯；数值 0.0 合法，#364④）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def gt_ratio(
    gain_db: float,
    *,
    t_sys_k: float | None = None,
    nf_db: float | None = None,
    t_e_k: float | None = None,
    t_ant_k: float = T0_K,
    t0_k: float = T0_K,
) -> dict[str, Any]:
    """G/T 组合优值：G/T = G_dB − 10·log10(T_sys)。

    参数
    ----
    gain_db : 接收链指向源方向的总增益 [dB]（级联链=cascade_budget.
        gain_total_db 同名直连）。
    t_sys_k : 系统噪声温度直接给定 [K]（优先级最高）。
    nf_db : 系统总噪声系数 [dB]（→ Te=T0·(F−1)，与 nf_db 级联口径一致）。
    t_e_k : 接收机等效输入噪声温度 [K]（nf_measurement te_from_y 链输出）。
    t_ant_k : 天线噪声温度 [K]（默认 290；nf/te 路径下并入 T_sys）。
    t0_k : NF→Te 换算基准温度 [K]（默认 290，IEEE 口径）。

    返回
    ----
    dict：gt_db_per_k / t_sys_k / t_e_k（无 NF 路径为 None）/ path /
    t0_k。t_sys_k、nf_db、t_e_k 三者同时给定按优先级 t_sys_k > nf_db >
    t_e_k 取用（note 字段如实报告被忽略的冗余输入）。
    """
    g_db = _num(gain_db, "gain_db")
    ant_k = _num(t_ant_k, "t_ant_k")
    base_k = _num(t0_k, "t0_k")
    if base_k <= 0.0:
        raise ValueError(f"t0_k 必须为正（IEEE 基准 290），得 {base_k}")
    if ant_k <= 0.0:
        raise ValueError(f"t_ant_k 必须为正（物理温度），得 {ant_k}")

    ignored: list[str] = []
    if t_sys_k is not None:
        sys_k = _num(t_sys_k, "t_sys_k")
        te: float | None = None
        path = "t_sys_direct"
        for extra, label in ((nf_db, "nf_db"), (t_e_k, "t_e_k")):
            if extra is not None:
                ignored.append(label)
    elif nf_db is not None:
        nf = _num(nf_db, "nf_db")
        if nf < 0.0:
            raise ValueError(f"nf_db 必须 >= 0（无源/有耗链），得 {nf}")
        f_lin = 10.0 ** (nf / 10.0)
        te = base_k * (f_lin - 1.0)
        sys_k = ant_k + te
        path = "nf"
        if t_e_k is not None:
            ignored.append("t_e_k")
    elif t_e_k is not None:
        te = _num(t_e_k, "t_e_k")
        if te < 0.0:
            raise ValueError(f"t_e_k 必须 >= 0（等效噪声温度非负），得 {te}")
        sys_k = ant_k + te
        path = "te"
    else:
        te = None
        sys_k = ant_k
        path = "antenna_only"

    if sys_k <= 0.0:
        raise ValueError(
            f"系统噪声温度必须为正（G/T 分母），得 T_sys={sys_k} K"
            f"（path={path}）")
    gt = g_db - 10.0 * math.log10(sys_k)
    note: str | None = None
    if ignored:
        note = f"冗余输入被忽略（优先级 t_sys_k > nf_db > t_e_k）: {ignored}"
    return {
        "gt_db_per_k": gt,
        "t_sys_k": sys_k,
        "t_e_k": te,
        "t_ant_k": ant_k,
        "t0_k": base_k,
        "gain_db": g_db,
        "path": path,
        "note": note,
    }
