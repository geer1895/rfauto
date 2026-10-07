"""判读收口纯函数助手（W1-F 席 H-02/H-03；internal_reinforcement §五 H 域）。

两件判读面惯例的确定性内核化（门值之外的双报与旁注，不翻门、不产物理数字
——阈值全部由调用方按 criteria 预声明值传入）：

1. :func:`sentinel_dual_report`（H-02，K-8 G4 哨兵口径二义的双报收口）：
   无源性硬门与截断哨兵是两个口径——``max|S|`` 落在 ``(1.0, passivity_limit]``
   时硬门 PASS 但 #262 截断哨兵亮，历史上允许"绿但注记"单报，存在把截断
   伪象静默当无源性证据的二义带。本函数把"双报"做成机器口径：返回逐口径
   判定 + 二义带标记，判读者必须两个口径都落账（verdict 模板逐键消费）。

2. :func:`magnitude_band_note`（H-03，量级合理性旁注惯例）：判读器在门判
   之外对关键观测量记"预期带外旁注"——观测值落在预声明预期带之外时如实
   随行注记（供人工归因），不改变任何门判定。

纯函数、零 I/O、零网络；输入非有限值按"带外"如实处理不抛（#105：
观测面故障不得阻塞判读主路径）。归档判读零改写（#325/#326）——本模块
只服务新判读，不回写任何历史 verdict。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "magnitude_band_note",
    "sentinel_dual_report",
]


def sentinel_dual_report(
    max_abs_s: float | None,
    *,
    passivity_limit: float,
    truncation_threshold: float = 1.0,
) -> dict[str, Any]:
    """无源性硬门 × 截断哨兵双报（H-02：两口径分列，禁单报静默 PASS）。

    Args:
        max_abs_s: 合并矩阵全频全条目 ``max|S|`` 观测（None=无观测，如实
            UNKNOWN 不判）。
        passivity_limit: 无源性硬门（criteria 预声明值，如 OE 网格噪声
            头寸 1.05）。
        truncation_threshold: 截断哨兵阈值（物理无源性上界 1.0；``>``
            严格比较——恰等 1.0 不算截断嫌疑）。

    Returns:
        dict: ``{max_abs_s, passivity_limit, truncation_threshold,
        passivity: "PASS"|"FAIL"|"UNKNOWN", truncation_suspect: bool,
        ambiguous_band: bool, dual_report_required: bool, notes: [str]}``。
        ``ambiguous_band=True`` 表示观测落在截断阈值之上但仍在无源性硬门
        之内——硬门绿不采信，须随 #262 截断注记双报（truncation 排查
        （FC 窗覆盖脉冲全程）完结前不得引用为无源性证据）。
    """
    if passivity_limit < truncation_threshold:
        raise ValueError(
            f"passivity_limit（{passivity_limit}）必须 ≥ truncation_threshold"
            f"（{truncation_threshold}），否则双报带定义失效")
    if max_abs_s is None or not isinstance(max_abs_s, (int, float)) \
            or isinstance(max_abs_s, bool) or not math.isfinite(max_abs_s):
        return {
            "max_abs_s": max_abs_s,
            "passivity_limit": passivity_limit,
            "truncation_threshold": truncation_threshold,
            "passivity": "UNKNOWN",
            "truncation_suspect": False,
            "ambiguous_band": False,
            "dual_report_required": False,
            "notes": ["max_abs_s 缺失或非有限——无源性如实 UNKNOWN 不判"
                      "（#122 不凑判）"],
        }
    suspect = max_abs_s > truncation_threshold
    passive = max_abs_s <= passivity_limit
    ambiguous = suspect and passive
    notes: list[str] = []
    if ambiguous:
        notes.append(
            "二义带双报：硬门 PASS 但截断哨兵亮（max|S|>1.0）——按 #262 "
            "先查截断（FC 窗须覆盖脉冲全程），截断未排除前硬门绿不采信")
    elif suspect:
        notes.append("截断哨兵亮且硬门 FAIL——#262 截断与非物理嫌疑并查")
    return {
        "max_abs_s": float(max_abs_s),
        "passivity_limit": passivity_limit,
        "truncation_threshold": truncation_threshold,
        "passivity": "PASS" if passive else "FAIL",
        "truncation_suspect": suspect,
        "ambiguous_band": ambiguous,
        "dual_report_required": suspect,
        "notes": notes,
    }


def magnitude_band_note(
    name: str,
    observed: float | None,
    expected_lo: float,
    expected_hi: float,
) -> str | None:
    """量级合理性旁注（H-03）：观测落在预声明预期带之外时返回旁注文案。

    门判之外的信息项旁注：预期带由判读者按 criteria/设计值预声明（本函数
    不产数字）；带内返回 None（零噪声）；带外返回含双侧边界与观测值的
    旁注串，判读者随行落账（不翻门、不重判）。None/非有限观测一律按
    带外如实注记（非有限值显式措辞），不静默放行。

    Args:
        name: 观测量名（如 "S21@f0 dB"）。
        observed: 观测值。
        expected_lo: 预期带下缘（含）。
        expected_hi: 预期带上缘（含）。

    Returns:
        旁注文案或 None（带内）。
    """
    if expected_lo > expected_hi:
        raise ValueError(
            f"预期带非法：lo（{expected_lo}）> hi（{expected_hi}）")
    if observed is None:
        return (f"预期带外旁注（{name}）：观测缺失——预期带 "
                f"[{expected_lo}, {expected_hi}]，缺失原因须随行落账")
    ok = isinstance(observed, (int, float)) and not isinstance(observed, bool) \
        and math.isfinite(observed) and expected_lo <= observed <= expected_hi
    if ok:
        return None
    if not isinstance(observed, (int, float)) or isinstance(observed, bool) \
            or not math.isfinite(observed):
        return (f"预期带外旁注（{name}）：观测非有限值（{observed!r}）——"
                f"预期带 [{expected_lo}, {expected_hi}]，量级不可判如实注记")
    return (f"预期带外旁注（{name}）：观测 {observed} 落在预期带 "
            f"[{expected_lo}, {expected_hi}] 之外——门判之外随行注记，"
            f"供人工归因（不翻门）")
