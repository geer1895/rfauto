"""time_domain_suite：时域分析参数/schema 标准化内核（XC 时域套件面）。

现状（round18 横切清单）：时域参数散落多处形态——docs meta.yaml
``max_time_ns``、netlist global_params ``nrts``、渲染旋钮 ``_nrts``/
``_end_criteria``（END_CRITERIA_FD=1e-6，#266 口径）、et 文件实测
timestep。本模块把它们统一到单一 schema **rfauto-td-v1**（确定性、
零 I/O、零引擎依赖）::

    {"schema": "rfauto-td-v1",
     "f0_ghz": float,            # 中心频率（必给，>0）
     "fc_window": float,         # 分数带宽（0,1]，缺省 0.2
     "nrts": int | None,         # 步数上限
     "dt_s": float | None,       # 引擎实测/预估 timestep
     "max_time_ns": float | None,# 窗长（nrts·dt 的另一种声明形态）
     "end_criteria_db": float | None}  # 能量停机判据（负 dB）

闭式内核（出处随行）：
- ``cfl_dt_s``：3-D Yee CFL 稳定上限 dt ≤ Δ/(c√3)/√εr,max（Taflove &
  Hagness《Computational Electrodynamics》§3.6 立方格 Courant 界；
  εr_max 走保守缩短——有效波速 c/√εr）；
- ``window_s``/``nrts_for_window``：窗长↔步数换算（ceil/floor 显式）；
- ``excite_duration_s``：高斯调制脉冲 −10dB 时宽闭式估计
  τ ≈ k_cycles/fc，fc = f0·fc_window（时宽与带宽成反比：fc_window 越窄
  脉宽越长——openEMS excite 的 fc 语义；k_cycles 缺省 5：#262 族"窗要
  覆盖脉冲全程"的规划期估计口径——**估计非引擎实测**，实测以 et 文件
  首末行时间为准，估出值仅用于 truncation 预警）；
- ``truncation_guard``：nrts·dt ≥ margin·τ_excite（#262/#312 截断族
  纪律的形式化，margin 缺省 1.1 盖引擎安全余量先例）。

冲突守卫：``max_time_ns`` 与 ``nrts``+``dt_s`` 同时声明且互不自洽
（|nrts·dt − max_time| 相对差 >1e-9）→ ValueError（显式不静默，
#122 双声明必须一致）。
"""

from __future__ import annotations

import math
from typing import Any

#: schema 版本串
TD_SCHEMA = "rfauto-td-v1"
#: 真空光速（SI 精确值，m/s；与 core 口径同源）
SPEED_OF_LIGHT_M_S = 299_792_458.0
#: 3-D 立方格 Courant 稳定界分母 √3（Yee 格最坏对角）
_CFL_SQRT3 = math.sqrt(3.0)
#: 高斯脉冲 −10dB 时宽估计的周期数缺省（规划期口径，预声明可覆盖）
DEFAULT_K_CYCLES = 5.0
#: truncation guard 安全余量缺省（#266 显式 1.1 余量先例）
DEFAULT_TRUNCATION_MARGIN = 1.1

#: 合法键集（未知键显式拒——标准化面的意义就是不吞别名）
_TD_KEYS = ("schema", "f0_ghz", "fc_window", "nrts", "dt_s",
            "max_time_ns", "end_criteria_db", "k_cycles",
            "min_cell_mm", "er_max")


def _pos(value: Any, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，得到 {value!r}") from exc
    if not math.isfinite(v) or v <= 0:
        raise ValueError(f"{name} 必须为正有限，得到 {v!r}")
    return v


def cfl_dt_s(min_cell_m: float, er_max: float = 1.0) -> float:
    """3-D Yee CFL 稳定 timestep 上限（秒）：Δ/(c√3)/√εr,max。

    min_cell_m=最小网格边（米）；er_max=域内最大相对介电常数（≥1，
    保守取上界使 dt 缩短）。纯闭式零引擎依赖。
    """
    d = _pos(min_cell_m, "min_cell_m")
    er = _pos(er_max, "er_max")
    if er < 1.0:
        raise ValueError(f"er_max 必须 ≥1（相对介电常数），得到 {er!r}")
    return d / (SPEED_OF_LIGHT_M_S * _CFL_SQRT3 * math.sqrt(er))


def excite_duration_s(f0_ghz: float, fc_window: float,
                      *, k_cycles: float = DEFAULT_K_CYCLES) -> float:
    """高斯调制脉冲 −10dB 时宽估计（秒）：τ ≈ k_cycles/fc，fc=f0·fc_window。

    时宽与带宽成反比（fc_window 越窄脉宽越长）；fc_window 给 (0,1]
    分数带宽。规划期估计口径（#262 族），非引擎实测。
    """
    f0 = _pos(f0_ghz, "f0_ghz")
    bw = float(fc_window)
    if not (0.0 < bw <= 1.0):
        raise ValueError(f"fc_window 必须 ∈(0,1]，得到 {bw!r}")
    k = _pos(k_cycles, "k_cycles")
    fc_hz = f0 * bw * 1e9
    return k / fc_hz


def nrts_for_window(window_s: float, dt_s: float, *,
                    mode: str = "ceil") -> int:
    """窗长→步数（mode=ceil|floor 显式；ceil 缺省=盖满窗不截断）。"""
    w = _pos(window_s, "window_s")
    dt = _pos(dt_s, "dt_s")
    ratio = w / dt
    if mode == "ceil":
        return math.ceil(ratio)
    if mode == "floor":
        return max(1, math.floor(ratio))
    raise ValueError(f"mode 必须为 ceil|floor，得到 {mode!r}")


def normalize_td_spec(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """时域参数标准化：别名统一 + 校验 + 衍生窗长（rfauto-td-v1）。

    - 未知键显式 ValueError（标准化面不吞别名；别名消费在上游完成）；
    - ``max_time_ns`` 与 ``nrts``+``dt_s`` 双声明必须自洽
      （相对差 ≤1e-9），否则 ValueError（#122）；
    - 衍生字段：``window_ns``（=max_time_ns 或 nrts·dt）、
      ``cfl_dt_limit_s``（dt_s 给定时附稳定裕度比 dt/CFL）、
      ``excite_duration_ns`` 与 ``truncation`` 预警（窗与脉宽比对）。
    """
    spec = dict(spec or {})
    unknown = sorted(set(spec) - set(_TD_KEYS))
    if unknown:
        raise ValueError(f"rfauto-td-v1 未知键: {unknown}（合法: "
                         f"{sorted(_TD_KEYS)}；别名请在上游归一）")
    declared_schema = spec.get("schema", TD_SCHEMA)
    if declared_schema != TD_SCHEMA:
        raise ValueError(f"schema 必须为 {TD_SCHEMA!r}，得到 {declared_schema!r}")
    if spec.get("f0_ghz") is None:
        raise ValueError("f0_ghz 必给（中心频率）")
    f0 = _pos(spec["f0_ghz"], "f0_ghz")
    fc_window = float(spec.get("fc_window", 0.2) or 0.2)
    if not (0.0 < fc_window <= 1.0):
        raise ValueError(f"fc_window 必须 ∈(0,1]，得到 {fc_window!r}")
    nrts = spec.get("nrts")
    dt_s = spec.get("dt_s")
    max_time_ns = spec.get("max_time_ns")
    if nrts is not None and (
            not isinstance(nrts, int) or isinstance(nrts, bool) or nrts <= 0):
        raise ValueError(f"nrts 必须为正整数，得到 {nrts!r}")
    if dt_s is not None:
        dt_s = _pos(dt_s, "dt_s")
    if max_time_ns is not None:
        max_time_ns = _pos(max_time_ns, "max_time_ns")
    window_ns: float | None = None
    if max_time_ns is not None and (nrts is None or dt_s is None):
        window_ns = max_time_ns
    elif max_time_ns is None and nrts is not None and dt_s is not None:
        window_ns = nrts * dt_s * 1e9
    elif max_time_ns is not None and nrts is not None and dt_s is not None:
        derived = nrts * dt_s * 1e9
        if abs(derived - max_time_ns) > 1e-9 * max(abs(derived),
                                                   abs(max_time_ns), 1.0):
            raise ValueError(
                f"max_time_ns={max_time_ns!r} 与 nrts·dt={derived!r} ns 不自洽"
                "（相对差 >1e-9）——双声明必须一致（#122）")
        window_ns = max_time_ns
    end_criteria_db = spec.get("end_criteria_db")
    if end_criteria_db is not None:
        end_criteria_db = float(end_criteria_db)
        if not (math.isfinite(end_criteria_db) and end_criteria_db < 0):
            raise ValueError(
                f"end_criteria_db 必须为负 dB（能量停机判据），"
                f"得到 {end_criteria_db!r}")
    k_cycles = float(spec.get("k_cycles", DEFAULT_K_CYCLES) or DEFAULT_K_CYCLES)
    out: dict[str, Any] = {
        "schema": TD_SCHEMA,
        "f0_ghz": f0,
        "fc_window": fc_window,
        "nrts": nrts,
        "dt_s": dt_s,
        "max_time_ns": max_time_ns,
        "end_criteria_db": end_criteria_db,
        "window_ns": window_ns,
    }
    if dt_s is not None:
        min_cell_mm = spec.get("min_cell_mm")
        if min_cell_mm is not None:
            er_max = float(spec.get("er_max", 1.0) or 1.0)
            cfl = cfl_dt_s(_pos(min_cell_mm, "min_cell_mm") * 1e-3, er_max)
            out["cfl_dt_limit_s"] = cfl
            out["dt_over_cfl"] = dt_s / cfl
            out["cfl_note"] = "3-D Yee 立方格稳定界（Taflove §3.6）；" \
                              "dt/CFL >1=非稳定声明，显式暴露"
    tau_s = excite_duration_s(f0, fc_window, k_cycles=k_cycles)
    out["excite_duration_ns"] = tau_s * 1e9
    out["k_cycles"] = k_cycles
    if window_ns is not None:
        out["truncation"] = {
            "ok": window_ns >= DEFAULT_TRUNCATION_MARGIN * tau_s * 1e9,
            "margin": DEFAULT_TRUNCATION_MARGIN,
            "note": "规划期估计口径（k_cycles 高斯脉宽），引擎实测以 et "
                    "首末行时间为准（#268）",
        }
    return out
