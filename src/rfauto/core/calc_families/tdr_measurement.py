"""TDR 测量规划族三键（aurora_h W1-K1，R2_core_tier5 §③ 3）。

故障定位/空间分辨率/等效时间采样——**测量仪器规划面**的闭式恒等式族
（传输线时域反射计教科书口径）；剖面**裁判面**是同仓
core/serdes_referee.py 的 DR-3 TDR/TDT 双路裁判核（阻抗剖面 Z(t) 双实现
+匹配线 Z=Z0/末端负载 Z_L/双段线段延迟处阶跃三解析锚）——测量规划（本
族）与剖面裁判（DR-3）分属同仓消费链两端，本批**不接线**，仅 docstring
注记语义衔接（serdes_referee 消费面注记，后续挂接走 service 层）。

公式（往返程差/分辨率恒等式；#122 如实标注惯例档）：
- 故障定位：d = v_p·t_fault/2（反射往返程差恒等：t_fault 为入射到收到
  反射的往返时间）；
  v_p = c0/√εeff（非磁性低损介质近似口径；或显式给 velocity_mps）。
- 空间分辨率：Δd = v_p·t_rise/2（阶跃上升时间对应的两故障点可分辨
  间距；系数 1/2 = 往返口径，工程惯例档如实标注——不同文献对"可分辨"
  判据（50% 幅度点/切线法）略有差异，本键按最常用往返口径）。
- 等效时间采样（ETS）：仪器实时采样率 f_trig（触发/采集重复率）下，
  每步延迟增量 Δt_step 逐步错位采样 → 等效采样间隔 = Δt_step、
  **等效采样率 f_eq = 1/Δt_step**（ETS 示波测量规划恒等式）；
  N_step 个点重建需 N_step 次触发，采集时间 = N_step/f_trig、
  记录时窗 = N_step·Δt_step。
  mode 档（纯规划语义标注，不改恒等式）：
  sequential=顺序步进（等间隔错位）；random_dither=随机抖动错位
  （覆盖统计均匀性靠过采样，同样点数下经验耗时略增——无闭式差异，
  如实标注不编系数）。

适用域：无损/低损传输线一阶规划口径（色散/多重反射细节归 DR-3 裁判
面）；boundary：serdes_referee（剖面裁判）、bandpass_sampling_plan
（A/D 采样规划——本键是测量仪器采样规划，不同对象）、microstrip/siw
（εeff 供给端）。

锚（#118 独立算术，tests/unit/test_w1k1_core_domains.py）：εeff=1 时
d=c0·t/2 真空恒等；εeff=4 → 距离减半恒等；分辨率 ∝ t_rise 线性恒等；
f_eq·Δt_step=1 乘法恒等；双段线定位距离与 serdes_referee 解析锚同仓
双源（裁判面解析锚已在 core 钉死，本族只做距离换算恒等）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator

_C0 = 299792458.0

_ETS_MODES = ("sequential", "random_dither")


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——bool 污染面 df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _pos(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，得 {out}")
    return out


def _resolve_velocity(eps_eff: float | None, velocity_mps: float | None,
                      where: str) -> float:
    """v_p 解析：εeff 档 / 显式速度二选一（均缺或双给显式拒绝）。"""
    if (eps_eff is None) == (velocity_mps is None):
        raise ValueError(
            f"{where}: 必须且只能给定 eps_eff 与 velocity_mps 之一")
    if velocity_mps is not None:
        v = _pos(velocity_mps, "velocity_mps")
        if v > _C0:
            raise ValueError(
                f"{where}: velocity_mps={v!r} > c0（超光速非物理，显式拒绝）")
        return v
    er = _num(eps_eff, "eps_eff")
    if er < 1.0:
        raise ValueError(f"{where}: eps_eff 必须 ≥1（物理介质下界真空），"
                         f"得 {er}")
    return _C0 / math.sqrt(er)


@register_calculator(
    "tdr_fault_location",
    "TDR故障定位：d=v_p·t_fault/2（反射往返程差恒等）；v_p=c0/√εeff 或显式"
    "velocity_mps 二选一（velocity>c0 显式拒绝）；εeff=1 退化为真空 d=c0·t/2 "
    "恒等。测量规划面——剖面裁判见 core/serdes_referee DR-3（同仓消费链）",
    (("t_roundtrip_s", "float s 入射到收到反射的往返时间（>0）"),
     ("eps_eff", "float 介质有效相对介电常数（≥1；与 velocity_mps 二选一）"),
     ("velocity_mps", "float m/s 显式传播速度（0<v≤c0；与 eps_eff 二选一）")),
    required=("t_roundtrip_s",),
)
def tdr_fault_location(t_roundtrip_s: float, eps_eff: float | None = None,
                       velocity_mps: float | None = None) -> dict[str, Any]:
    where = "tdr_fault_location"
    t = _pos(t_roundtrip_s, "t_roundtrip_s")
    v_p = _resolve_velocity(eps_eff, velocity_mps, where)
    distance = v_p * t / 2.0
    return {
        "t_roundtrip_s": t,
        "v_p_m_per_s": v_p,
        "distance_m": float(distance),
        "one_way_time_s": float(t / 2.0),
        "resolution_note": (
            "定位距离的可达精度另受上升时间限制，见 tdr_resolution 键"),
        "note": (
            "往返程差恒等式 d=v_p·t/2；εeff 口径为非磁性低损近似"
            "（v_p=c0/√εeff），有损耗/色散线以实测 velocity_mps 为准；"
            "剖面形态判读（阻抗阶跃/负载识别）属 serdes_referee DR-3 "
            "裁判面，本键只做距离换算"),
        "source": (
            "传输线时域反射计教科书恒等式（往返程差）；消费面注记 "
            "core/serdes_referee.py DR-3 解析锚同仓双源"),
    }


@register_calculator(
    "tdr_resolution",
    "TDR空间分辨率：Δd=v_p·t_rise/2（阶跃上升时间对应两故障点可分辨间距；"
    "系数 1/2=往返口径，工程惯例档如实标注——'可分辨'判据随文献口径微异）；"
    "v_p=c0/√εeff 或显式 velocity_mps 二选一；分辨率 ∝ t_rise 线性恒等",
    (("t_rise_s", "float s 入射阶跃上升时间（>0；10%-90% 或等效口径）"),
     ("eps_eff", "float 介质有效相对介电常数（≥1；与 velocity_mps 二选一）"),
     ("velocity_mps", "float m/s 显式传播速度（0<v≤c0；与 eps_eff 二选一）")),
    required=("t_rise_s",),
)
def tdr_resolution(t_rise_s: float, eps_eff: float | None = None,
                   velocity_mps: float | None = None) -> dict[str, Any]:
    where = "tdr_resolution"
    t_rise = _pos(t_rise_s, "t_rise_s")
    v_p = _resolve_velocity(eps_eff, velocity_mps, where)
    resolution = v_p * t_rise / 2.0
    return {
        "t_rise_s": t_rise,
        "v_p_m_per_s": v_p,
        "resolution_m": float(resolution),
        "resolution_mm": float(resolution * 1e3),
        "note": (
            "工程惯例档（往返口径 1/2 系数）：不同文献'可分辨'判据"
            "（50% 幅度点/切线法/能量判据）系数略有差异，本键按最常用"
            "往返口径如实标注，不作高分辨率判据仲裁；定位用本值与 "
            "tdr_fault_location 配套"),
        "source": (
            "TDR 分辨率工程惯例式（v_p·t_rise/2 往返口径；惯例档如实"
            "标注非仲裁口径）"),
    }


@register_calculator(
    "tdr_ets_equivalent_time",
    "TDR等效时间采样（ETS）规划：每步延迟增量 Δt_step 错位采样 → 等效采样"
    "间隔=Δt_step、等效采样率 f_eq=1/Δt_step（规划恒等式）；N_step 点重建"
    "需 N_step 次触发（采集时间=N_step/f_trig、记录时窗=N_step·Δt_step）；"
    "sequential/random_dither 两档纯规划语义标注（无闭式差异如实标注）",
    (("delta_t_step_s", "float s 每步延迟增量（>0，决定等效采样率）"),
     ("f_trigger_hz", "float Hz 仪器触发/采集重复率（>0）"),
     ("n_steps", "int 重建点数 N_step（≥2，可选；给定时附时窗/耗时规划）"),
     ("mode", "str 'sequential'（顺序步进）或 'random_dither'（随机抖动），"
      "缺省 sequential")),
    required=("delta_t_step_s", "f_trigger_hz"),
)
def tdr_ets_equivalent_time(delta_t_step_s: float, f_trigger_hz: float,
                            n_steps: int | None = None,
                            mode: str = "sequential") -> dict[str, Any]:
    where = "tdr_ets_equivalent_time"
    dt = _pos(delta_t_step_s, "delta_t_step_s")
    f_trig = _pos(f_trigger_hz, "f_trigger_hz")
    mode_key = str(mode).strip().lower()
    if mode_key not in _ETS_MODES:
        raise ValueError(
            f"{where}: mode 只收 {_ETS_MODES}，得 {mode!r}")
    n_steps_out: int | None = None
    record_window_s: float | None = None
    acquisition_time_s: float | None = None
    if n_steps is not None:
        if isinstance(n_steps, bool):
            raise ValueError("n_steps 必须为整数（不接受 bool）")
        n_val = float(n_steps)
        n_int = round(n_val)
        if abs(n_val - n_int) > 1e-9:
            raise ValueError(f"{where}: n_steps 必须为整数，得 {n_steps!r}")
        if n_int < 2:
            raise ValueError(f"{where}: n_steps 必须 ≥2，得 {n_int}")
        n_steps_out = n_int
        record_window_s = n_int * dt
        acquisition_time_s = n_int / f_trig
    f_eq = 1.0 / dt
    return {
        "delta_t_step_s": dt,
        "f_trigger_hz": f_trig,
        "mode": mode_key,
        "eq_sample_interval_s": dt,
        "eq_sample_rate_hz": float(f_eq),
        "ets_gain": float(f_eq / f_trig),
        "n_steps": n_steps_out,
        "record_window_s": record_window_s,
        "acquisition_time_s": acquisition_time_s,
        "note": (
            "ETS 恒等式 f_eq=1/Δt_step（等效带宽由仪器前沿/重建窗另限，"
            "非本键口径）；random_dither 档覆盖均匀性靠过采样、同样点数"
            "经验耗时略增（无闭式差异如实标注）；Δt_step 应 ≪ 被测波形"
            "特征时间（否则重建欠采样失真——规划前置自检）；剖面裁判面"
            "同仓 serdes_referee DR-3"),
        "source": (
            "等效时间采样测量规划恒等式（ETS 示波口径）；R2_core_tier5 "
            "§③ 3 恒等式族"),
    }
