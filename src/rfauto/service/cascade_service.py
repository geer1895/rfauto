"""DP-5 cascade service：系统级预算/杂散/IF 规划的 JSON 进出编排。

数值只在确定性内核（铁律 7）：全部物理数字来自 core/cascade.py 纯函数，
本模块只做三件事——
1. filter/atten/cable 级的插损来源解析（唯一 IO 点）：skrf Network 实取
   S21 插损（il_source="sparam"）或显式常数 il_db（il_source="constant"）；
   资产缺失/来源缺失时显式报错，要求"有效 S 参数文件或显式常数 il_db
   降级"，绝不静默默认（criteria.md §3）。
2. 参数校验与异常到 JSON 的翻译（ok=False + error，不抛出）。
3. core 调用与结果透传（core 返回值原样进 result，不再加工）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rfauto.core.cascade import PASSIVE_TYPES

_IL_TYPES = ("filter", "atten", "cable")


def _extract_il_from_network(network_path: str, il_freq_hz: float) -> float:
    """从 skrf Network 读 S21 在指定频率的插损 [dB]（线性插值，不外推）。

    本函数是 DP-5 编排链里唯一的 skrf/文件 IO 点；core 零 IO 由此保证。
    """
    try:
        import skrf
    except ImportError as exc:  # pragma: no cover - 环境缺 skrf 显式报错
        raise ValueError(
            f"读取 S 参数资产需要 skrf（当前环境不可用）: {exc}") from exc
    path = Path(network_path)
    if not path.is_file():
        raise ValueError(
            f"S 参数资产缺失: {network_path} ——请提供存在的 S 参数文件，"
            "或显式给常数插损 il_db 降级（显式降级口径，不静默默认）")
    try:
        nw = skrf.Network(str(path))
    except Exception as exc:
        raise ValueError(
            f"S 参数资产读取失败: {network_path}（{exc}）——请提供可解析的"
            " Touchstone/S 参数文件，或显式给常数插损 il_db 降级") from exc
    n_ports = getattr(nw, "nports", None)
    if n_ports != 2:
        raise ValueError(
            f"S 参数资产 {network_path} 端口数={n_ports}，插损提取须为 2 端口"
            "（取 S21）；请更换资产或显式给常数插损 il_db")
    import numpy as np

    s21_db = 20.0 * np.log10(np.abs(np.asarray(nw.s)[:, 1, 0]))
    freqs = np.asarray(nw.f, dtype=float)
    f0 = float(il_freq_hz)
    if not (freqs.size and freqs.min() <= f0 <= freqs.max()):
        raise ValueError(
            f"il_freq_hz={f0!r} 落在 S 参数资产 {network_path} 的频率范围 "
            f"[{freqs.min()!r}, {freqs.max()!r}] 之外——插损不外推，请更换资产"
            "或显式给常数插损 il_db")
    il_db = float(-np.interp(f0, freqs, s21_db))
    if not math.isfinite(il_db):
        raise ValueError(
            f"S 参数资产 {network_path} 在 {f0!r} Hz 的插损非有限（数据含零/"
            "NaN）——请修数据或显式给常数插损 il_db")
    return il_db


def resolve_stage_losses(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """解析 filter/atten/cable 级的插损来源（返回深拷贝，不改入参）。

    来源优先级与冲突规则（显式二选一，不静默）：
    - network_path + il_freq_hz → 实取 S21 插损，gain_db=−IL，
      il_source="sparam"（与其他插损来源同给 → 显式冲突报错）；
    - 显式 il_db → gain_db=−il_db，il_source="constant"
      （与 gain_db 同给且不一致 → 显式冲突报错）；
    - 只有 gain_db → 原样透传（il_source="gain_only"）；
    - 无源级三无（无 network_path/il_db/gain_db）→ 显式报错。
    amp/mixer 级原样透传。
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(stages):
        if not isinstance(raw, dict):
            raise ValueError(f"stages[{i}] 必须是 dict，收到 {type(raw)!r}")
        stage = dict(raw)
        stype = stage.get("type")
        if stype not in _IL_TYPES:
            out.append(stage)
            continue
        has_network = stage.get("network_path") is not None
        has_il = stage.get("il_db") is not None
        has_gain = stage.get("gain_db") is not None
        if has_network:
            if has_il or has_gain:
                raise ValueError(
                    f"stages[{i}]（type={stype!r}）同时给了 network_path 与 "
                    f"{'il_db' if has_il else 'gain_db'}——插损来源显式二选一"
                    "（S 参数实取 vs 常数），拒绝歧义输入")
            if stage.get("il_freq_hz") is None:
                raise ValueError(
                    f"stages[{i}]（type={stype!r}）给 network_path 时必须显式"
                    "给 il_freq_hz（实取插损的工作频率，不臆选）")
            il_db = _extract_il_from_network(
                str(stage["network_path"]), stage["il_freq_hz"])
            stage["gain_db"] = -il_db
            stage.pop("il_db", None)
            stage["il_source"] = "sparam"
        elif has_il:
            il_db = float(stage["il_db"])
            if not (math.isfinite(il_db) and il_db >= 0.0):
                raise ValueError(
                    f"stages[{i}].il_db 必须 ≥0 且有限，收到 {stage['il_db']!r}")
            if has_gain and abs(stage["gain_db"] + il_db) > 1e-12:
                raise ValueError(
                    f"stages[{i}]（type={stype!r}）gain_db={stage['gain_db']!r} "
                    f"与 il_db={il_db!r} 不一致（增益应=−插损）——显式二选一")
            stage["gain_db"] = -il_db
            stage["il_source"] = "constant"
        elif has_gain:
            stage["il_source"] = "gain_only"
        else:
            raise ValueError(
                f"stages[{i}]（type={stype!r}）无任何插损来源：请提供 "
                "network_path（S 参数资产实取插损）或显式常数 il_db/"
                "gain_db 降级——不静默默认")
        out.append(stage)
    return out


def cascade_budget_report(
    stages: list[dict[str, Any]],
    *,
    snr_min_db: float = 10.0,
    rx_power_dbm: float | None = None,
    bw_hz: float | None = None,
    t_kelvin: float = 290.0,
) -> dict[str, Any]:
    """stage 列表 → 级联预算报告（JSON 进出；错误 ok=False + error）。"""
    try:
        resolved = resolve_stage_losses(stages)
        from rfauto.core.cascade import cascade_budget as _core

        result = _core(resolved, snr_min_db=snr_min_db,
                       rx_power_dbm=rx_power_dbm, bw_hz=bw_hz, t_kelvin=t_kelvin)
        return {"ok": True, "result": result}
    except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError) as exc:
        return {"ok": False, "error": str(exc)}


def spur_search_report(
    f_rf_hz: float,
    f_lo_hz: float,
    *,
    if_center_hz: float | None = None,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    lo_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """混频杂散落带搜索报告（JSON 进出；产物表 + 落带/危险等级）。"""
    try:
        from rfauto.core.cascade import spur_search as _core

        spurs = _core(f_rf_hz, f_lo_hz, if_center_hz=if_center_hz,
                      if_bw_hz=if_bw_hz, rf_bw_hz=rf_bw_hz, lo_bw_hz=lo_bw_hz,
                      max_order=max_order)
        n_in_band = sum(1 for s in spurs
                        if s["in_band"] and s["role"] == "spur")
        return {"ok": True,
                "result": {"f_rf_hz": f_rf_hz, "f_lo_hz": f_lo_hz,
                           "if_center_hz": (abs(f_rf_hz - f_lo_hz)
                                            if if_center_hz is None
                                            else if_center_hz),
                           "max_order": max_order,
                           "n_products": len(spurs),
                           "n_spurs_in_band": n_in_band,
                           "spurs": spurs}}
    except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError) as exc:
        return {"ok": False, "error": str(exc)}


def if_plan_report(
    f_rf_hz: float,
    *,
    if_lo_hz: float,
    if_hi_hz: float,
    side: str = "low",
    n_points: int = 201,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    lo_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """IF 候选扫掠报告（JSON 进出；逐点判定 + spurious-free 窗口表）。"""
    try:
        from rfauto.core.cascade import if_plan_sweep as _core

        result = _core(f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz,
                       side=side, n_points=n_points, if_bw_hz=if_bw_hz,
                       rf_bw_hz=rf_bw_hz, lo_bw_hz=lo_bw_hz,
                       max_order=max_order)
        return {"ok": True, "result": result}
    except (ValueError, TypeError, KeyError, ArithmeticError, OverflowError) as exc:
        return {"ok": False, "error": str(exc)}


# PASSIVE_TYPES re-export（壳层提示用；口径单一来源 core.cascade）
__all__ = ["PASSIVE_TYPES", "cascade_budget_report", "if_plan_report",
           "resolve_stage_losses", "spur_search_report"]
