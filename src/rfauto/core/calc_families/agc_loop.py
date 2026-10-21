"""AGC 环路动力学（架构批 W3-S10 席域，R2_core_tier3 §③ D3 立项——
rx_impairments docstring 预声明排除面"AGC/压缩行为只做 P1dB 裕量检查"
的动态半边补全，rx_impairments 静态面语义零改动）。

两键：agc_loop_dynamics（对数域一阶环线性化闭环常数：开环增益→闭环
极点/环路带宽/attack-release 时间常数/稳态误差 1/(1+T)/建立时间/
起控门限与动态范围平面）/ agc_loop_response（阶跃扰动时域轨迹
δ(t)=δ_in/(1+T)·(1+T·e^{−t/τ})——attack/release 双档时间常数语义）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **链路模型**（经典接收机 AGC，控制论一阶环线性化口径）：

    VGA：G(V_c) = G0 − K_v·V_c [dB]（增益随控制电压线性递减，
          K_v [dB/V] 压控斜率、G0=V_c=0 最大增益）
    检波：V_d = K_d·P_out_dBm + b（对数检波器，K_d [V/dB] 检波斜率；
          基准项 b 并入参考面取 b=0，如实注记）
    误差放大：V_c = A·(V_d − V_ref)（A 环内放大；极性=输出过高→
          V_c↑→增益↓，负反馈闭环）
    环路滤波：单极点 τ_L（一阶；attack 充电时间常数基准，release
          放电路径 τ_base=ρ·τ_L，ρ≥1=放电电阻比惯例）

- **开环对数增益** T = A·K_d·K_v（量纲 dB/V·V/dB 相消，无量纲）。
  对数域小信号扰动 δ（P_out 对目标值的 dB 偏差）、输入扰动 δ_in：

      τ_L·dδ/dt + (1+T)·δ = δ_in

- **闭环常数闭式**（一阶环恒等式，测试锚主判）：
  闭环极点 ω_p=(1+T)/τ_L [rad/s]；环路带宽 f_loop=(1+T)/(2π·τ_L)
  （attack 档）；attack 时间常数 τ_a=τ_L/(1+T)、release τ_r=ρ·τ_L/
  (1+T)（release 档带宽再除 ρ）；稳态误差（dB 偏差残差比例）
  ε=1/(1+T)；阶跃暂态衰减到份额 α 的建立时间 t_s=−τ·ln(α)
  （一阶标准口径）。
- **阶跃响应闭式**：t=0⁺ 检波/滤波器状态连续→输出全额扰动
  δ(0⁺)=δ_in；终值 δ(∞)=δ_in/(1+T)；轨迹

      δ(t) = δ_in/(1+T)·(1 + T·e^{−t/τ_eff})

  τ_eff 按 attack/release 档取 τ_a/τ_r。正阶跃=attack（快档）、负
  阶跃=release（慢档）语义如实回显。
- **起控门限与动态范围**（可选平面）：环路把 P_out 驱动到目标
  P_tgt=V_ref/K_d；VGA 最大增益 G0 决定起控门限
  P_in_thresh = P_tgt − G0（低于门限环路开环=固定增益 G0 直通、
  无调整）；VGA 控制范围 ΔG 决定受控输入动态范围
  [P_thresh, P_thresh+ΔG]，对应输出变化仅 ΔG/(1+T)（环路压缩）。
- **诚实边界（预声明）**：线性化对数域一阶环——检波器理想对数律
  （实器件纹波/偏差不建模）、VGA 增益 dB 线性理想、单极点环路滤波
  （高阶滤波/环路时延的稳定性裕度面——时延相位侵蚀可致振荡——不在
  本域）、attack/release 不对称只进时间常数不进非线性切换暂态；
  P1dB 裕量/压缩后 NF 等静态线性度面仍归 rx_impairments（docstring
  预声明注记已改指路本模块）。无 AGC 退化=T→0（A→0 极限）：
  τ→τ_L、ε→1（开环直通恒等，测试锚数值极限档）。

出处
----
- 控制论一阶环线性化+对数放大器教科书口径（Bekker & 惯用接收机
  AGC 分析；二级转引，与 pll_loop_filter 一阶环同族不同对象——
  PLL 环路滤波器综合走 pll_loop_filter.py，本族只做 AGC 闭环
  动力学，边界互指）。
- attack/release 双时间常数=检波器充放电不对称惯例（音频/射频 AGC
  教科书口径，二级转引）。

守卫：detector_slope_v_per_db>0；vga_slope_db_per_v>0；loop_gain_a>0
（T→0 退化用 A→0⁺ 数值极限档）；loop_tau_s>0；release_ratio≥1；
settling_fraction∈(0,1)；step_db≠0；t_grid 有限非负严格递增；
门限面 p_out_target_dbm/g0_db/控制范围 ΔG 给出时均须有限且
ΔG>0、G0 有限；越界一律显式 ValueError。

出处（控制论一阶环+对数放大器教科书口径）：
- agc_loop_dynamics/agc_loop_response：对数域一阶环线性化（控制论
  一阶环经典式+对数放大器惯用接收机口径，二级转引；模块 docstring 逐项
  推导在档，阶跃轨迹三点恒等测试钉）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "agc_loop_dynamics",
    "agc_loop_response",
]

_SOURCE = (
    "对数域一阶环线性化=控制论一阶环+对数放大器教科书口径（二级转引）；"
    "attack/release 双时间常数=检波充放电不对称惯例（二级转引）；"
    "推导见模块头（本席落地，键内恒等式自检+测试侧独立重算）"
)


def _loop_constants(detector_slope_v_per_db: float, vga_slope_db_per_v: float,
                    loop_gain_a: float, loop_tau_s: float,
                    release_ratio: float, key: str) -> dict[str, float]:
    """环路参数守卫+闭环常数单源（两键共用，避免公式复制漂移）。"""
    kd = _finite(detector_slope_v_per_db, f"{key}.detector_slope_v_per_db")
    if kd <= 0.0:
        raise ValueError(
            f"{key}: detector_slope_v_per_db 必须 >0，得到 {kd!r}")
    kv = _finite(vga_slope_db_per_v, f"{key}.vga_slope_db_per_v")
    if kv <= 0.0:
        raise ValueError(f"{key}: vga_slope_db_per_v 必须 >0，得到 {kv!r}")
    a = _finite(loop_gain_a, f"{key}.loop_gain_a")
    if a <= 0.0:
        raise ValueError(
            f"{key}: loop_gain_a 必须 >0（无 AGC 退化用 A→0⁺ 数值极限档），"
            f"得到 {a!r}")
    tau_l = _finite(loop_tau_s, f"{key}.loop_tau_s")
    if tau_l <= 0.0:
        raise ValueError(f"{key}: loop_tau_s 必须 >0，得到 {tau_l!r}")
    rho = _finite(release_ratio, f"{key}.release_ratio")
    if rho < 1.0:
        raise ValueError(
            f"{key}: release_ratio 必须 ≥1（release 不快于 attack 惯例），"
            f"得到 {rho!r}")
    t_open = a * kd * kv  # 开环对数增益（dB/V·V/dB 相消）
    tau_attack = tau_l / (1.0 + t_open)
    tau_release = rho * tau_l / (1.0 + t_open)
    return {"kd": kd, "kv": kv, "a": a, "tau_l": tau_l, "rho": rho,
            "t_open": t_open, "tau_attack": tau_attack,
            "tau_release": tau_release}


def _threshold_plane(p_out_target_dbm: float | None, g0_db: float | None,
                     vga_gain_range_db: float | None,
                     t_open: float, key: str) -> dict[str, Any]:
    """起控门限/动态范围可选平面（三参全给才算，部分给显式拒绝）。"""
    given = [p_out_target_dbm is not None, g0_db is not None,
             vga_gain_range_db is not None]
    if not any(given):
        return {"threshold_plane": None}
    if not all(given):
        names = ("p_out_target_dbm", "g0_db", "vga_gain_range_db")
        missing = names[given.index(False)]
        raise ValueError(
            f"{key}: 起控门限面须 p_out_target_dbm/g0_db/vga_gain_range_db "
            f"三参同时给出（部分给显式拒绝），当前缺 {missing}")
    p_tgt = _finite(p_out_target_dbm, f"{key}.p_out_target_dbm")
    g0 = _finite(g0_db, f"{key}.g0_db")
    dg = _finite(vga_gain_range_db, f"{key}.vga_gain_range_db")
    if dg <= 0.0:
        raise ValueError(
            f"{key}: vga_gain_range_db 必须 >0，得到 {dg!r}")
    p_thresh = p_tgt - g0
    return {
        "threshold_plane": {
            "p_in_threshold_dbm": round(p_thresh, 12),
            "regulated_input_range_db": round(dg, 12),
            "p_in_range_dbm": [round(p_thresh, 12),
                               round(p_thresh + dg, 12)],
            "p_out_variation_db": round(dg / (1.0 + t_open), 15),
            "note": (
                "低于 P_in_thresh 环路开环（VGA 顶在 G0，固定增益直通无"
                "调整）；受控输入范围 [P_thresh, P_thresh+ΔG] 对应输出"
                "变化 ΔG/(1+T)——环路把输入摆幅压缩 (1+T) 倍的语义"),
        },
    }


# ─── 键 1：agc_loop_dynamics（闭环常数闭式）─────────────────────────────────

@register_calculator(
    "agc_loop_dynamics",
    "AGC环路动力学：对数域一阶环线性化闭环常数（R2 D3 立项——"
    "rx_impairments 预声明排除的动态半边补全；链路=对数检波 K_d[V/dB]+"
    "误差放大 A+压控增益 VGA K_v[dB/V]+单极点环路滤波 τ_L，负反馈极性）。"
    "开环对数增益 T=A·K_d·K_v→闭环极点 (1+T)/τ_L、环路带宽 "
    "f=(1+T)/(2πτ_L)、attack/release 时间常数 τ_L/(1+T) 与 ρτ_L/(1+T)"
    "（ρ=放电/充电比≥1）、稳态 dB 偏差残差比例 1/(1+T)、阶跃暂态衰减到"
    "份额 α 的建立时间 −τ·ln(α)。可选起控门限面（P_tgt−G0 门限/受控"
    "输入范围 ΔG/输出摆幅 ΔG/(1+T)）。无 AGC 退化=A→0⁺ 极限档 "
    "τ→τ_L、ε→1（开环直通恒等）。锚：极点/带宽恒等、稳态误差恒等、"
    "阶跃 e^{−t/τ} 渐近、直通退化极限",
    (("detector_slope_v_per_db", "float V/dB 对数检波器斜率 K_d（>0）"),
     ("vga_slope_db_per_v", "float dB/V 压控增益斜率 K_v（>0）"),
     ("loop_gain_a", "float 环内误差放大增益 A（>0；A→0⁺=无 AGC 直通"
      "退化档）"),
     ("loop_tau_s", "float s 环路滤波单极点时间常数 τ_L（>0，attack "
      "充电档基准）"),
     ("release_ratio", "float release/attack 时间常数比 ρ（≥1，缺省 1="
      "对称档；>1=放电慢档惯例）"),
     ("settling_fraction", "float 阶跃暂态衰减份额 α（∈(0,1)，缺省 0.1"
      "=衰减到 10%）"),
     ("p_out_target_dbm", "float dBm 输出目标电平（门限面三参之一）"),
     ("g0_db", "float dB VGA 最大增益 G0（门限面三参之一）"),
     ("vga_gain_range_db", "float dB VGA 控制范围 ΔG（>0，门限面三参"
      "之一）")),
    required=("detector_slope_v_per_db", "vga_slope_db_per_v",
              "loop_gain_a", "loop_tau_s"),
)
def agc_loop_dynamics(detector_slope_v_per_db: float,
                      vga_slope_db_per_v: float, loop_gain_a: float,
                      loop_tau_s: float, release_ratio: float = 1.0,
                      settling_fraction: float = 0.1,
                      p_out_target_dbm: float | None = None,
                      g0_db: float | None = None,
                      vga_gain_range_db: float | None = None) -> dict[str, Any]:
    key = "agc_loop_dynamics"
    lc = _loop_constants(detector_slope_v_per_db, vga_slope_db_per_v,
                         loop_gain_a, loop_tau_s, release_ratio, key)
    alpha = _finite(settling_fraction, f"{key}.settling_fraction")
    if not 0.0 < alpha < 1.0:
        raise ValueError(
            f"{key}: settling_fraction 须 ∈(0,1)，得到 {alpha!r}")
    t_open = lc["t_open"]
    tau_a = lc["tau_attack"]
    tau_r = lc["tau_release"]
    err_frac = 1.0 / (1.0 + t_open)
    out: dict[str, Any] = {
        "detector_slope_v_per_db": lc["kd"],
        "vga_slope_db_per_v": lc["kv"],
        "loop_gain_a": lc["a"],
        "loop_tau_s": lc["tau_l"],
        "release_ratio": lc["rho"],
        "open_loop_gain": round(t_open, 15),
        "closed_loop_pole_rad_s": round((1.0 + t_open) / lc["tau_l"], 15),
        "loop_bandwidth_hz": round((1.0 + t_open)
                                   / (2.0 * math.pi * lc["tau_l"]), 15),
        "attack_tau_s": round(tau_a, 18),
        "release_tau_s": round(tau_r, 18),
        "release_bandwidth_hz": round((1.0 + t_open)
                                      / (2.0 * math.pi * lc["rho"]
                                         * lc["tau_l"]), 15),
        "steady_state_error_fraction": round(err_frac, 18),
        "error_suppression_percent": round((1.0 - err_frac) * 100.0, 12),
        "settling_time_attack_s": round(-tau_a * math.log(alpha), 18),
        "settling_time_release_s": round(-tau_r * math.log(alpha), 18),
        "settling_fraction": alpha,
        "threshold_plane": None,
        "note": (
            "对数域线性化：δ 单位=dB（P_out 对目标偏差），稳态误差比例 "
            "1/(1+T) 施于 dB 偏差（输入扰动 ΔP dB→输出残差 ΔP/(1+T) "
            "dB）；release_ratio>1 只改时间常数（慢恢复），不改变稳态；"
            "T=0 退化=环路开环直通（τ→τ_L、ε→1）；检波纹波/VGA 非线性/"
            "环路时延稳定性裕度不在本域（模块头预声明）；P1dB/压缩静态"
            "面归 rx_impairments（其注记已改指路本模块）"),
        "source": _SOURCE,
    }
    out.update(_threshold_plane(p_out_target_dbm, g0_db, vga_gain_range_db,
                                t_open, key))
    return out


# ─── 键 2：agc_loop_response（阶跃时域轨迹）─────────────────────────────────

@register_calculator(
    "agc_loop_response",
    "AGC阶跃响应：对数域一阶环输入阶跃 δ_in（dB）后输出偏差轨迹闭式 "
    "δ(t)=δ_in/(1+T)·(1+T·e^{−t/τ_eff})——t=0⁺ 全额扰动（环路滤波状态"
    "连续）、终值 δ_in/(1+T)、暂态按 e^{−t/τ_eff} 衰减；正阶跃=attack"
    "（τ_a=τ_L/(1+T) 快档）、负阶跃=release（τ_r=ρτ_L/(1+T) 慢档）。"
    "给 p_out_target_dbm 时并列输出绝对电平轨迹。锚：闭式逐点恒等、"
    "t=0⁺/终值/τ 处 e^{−1} 三点解析、attack-release τ 比恒等",
    (("step_db", "float dB 输入功率阶跃幅度（≠0；符号定档：正=attack "
      "快档、负=release 慢档）"),
     ("t_grid_s", "list[float] 时间栅格 s（有限非负严格递增）"),
     ("detector_slope_v_per_db", "float V/dB 对数检波器斜率 K_d（>0）"),
     ("vga_slope_db_per_v", "float dB/V 压控增益斜率 K_v（>0）"),
     ("loop_gain_a", "float 环内误差放大增益 A（>0）"),
     ("loop_tau_s", "float s 环路滤波单极点时间常数 τ_L（>0）"),
     ("release_ratio", "float release/attack 比 ρ（≥1，缺省 1）"),
     ("p_out_target_dbm", "float dBm 输出目标电平（可选；给了才输出"
      "绝对电平轨迹）")),
    required=("step_db", "t_grid_s", "detector_slope_v_per_db",
              "vga_slope_db_per_v", "loop_gain_a", "loop_tau_s"),
)
def agc_loop_response(step_db: float, t_grid_s: list,
                      detector_slope_v_per_db: float,
                      vga_slope_db_per_v: float, loop_gain_a: float,
                      loop_tau_s: float, release_ratio: float = 1.0,
                      p_out_target_dbm: float | None = None
                      ) -> dict[str, Any]:
    key = "agc_loop_response"
    lc = _loop_constants(detector_slope_v_per_db, vga_slope_db_per_v,
                         loop_gain_a, loop_tau_s, release_ratio, key)
    step = _finite(step_db, f"{key}.step_db")
    if step == 0.0:
        raise ValueError(
            f"{key}: step_db 必须 ≠0（零阶跃无响应轨迹），得到 {step!r}")
    if not t_grid_s or not isinstance(t_grid_s, list):
        raise ValueError(
            f"{key}: t_grid_s 须为非空 list，得到 {type(t_grid_s)!r}")
    grid = [_finite(v, f"{key}.t_grid_s[{i}]")
            for i, v in enumerate(t_grid_s)]
    for i in range(1, len(grid)):
        if grid[i] <= grid[i - 1]:
            raise ValueError(
                f"{key}: t_grid_s 须严格递增，t[{i}]={grid[i]!r} ≤ "
                f"t[{i-1}]={grid[i-1]!r}")
    direction = "attack" if step > 0.0 else "release"
    tau_eff = lc["tau_attack"] if step > 0.0 else lc["tau_release"]
    t_open = lc["t_open"]
    ss_dev = step / (1.0 + t_open)
    dev = [round(ss_dev * (1.0 + t_open * math.exp(-t / tau_eff)), 18)
           for t in grid]
    level: list | None = None
    if p_out_target_dbm is not None:
        p_tgt = _finite(p_out_target_dbm, f"{key}.p_out_target_dbm")
        level = [round(p_tgt + d, 15) for d in dev]
    # 恒等面：t=0⁺ 极限/终值极限/τ 处 e^{−1} 三点（栅格含 0/大时刻时回显）
    dev0 = (None if grid[0] != 0.0 else
            round(ss_dev * (1.0 + t_open), 18))  # =step（状态连续恒等）
    big = (None if grid[-1] <= 20.0 * tau_eff else
           round(dev[-1], 18))  # e^{−20}≈2e-9 渐近带
    return {
        "step_db": step,
        "direction": direction,
        "open_loop_gain": round(t_open, 15),
        "tau_eff_s": round(tau_eff, 18),
        "attack_tau_s": round(lc["tau_attack"], 18),
        "release_tau_s": round(lc["tau_release"], 18),
        "steady_state_dev_db": round(ss_dev, 18),
        "t_grid_s": grid,
        "output_dev_db": dev,
        "output_level_dbm": level,
        "p_out_target_dbm": p_out_target_dbm,
        "identity_at_t0_dev_db": dev0,
        "asymptote_dev_db": big,
        "note": (
            "δ(t)=δ_in/(1+T)·(1+T·e^{−t/τ_eff}) 模块头闭式；t=0⁺ 恒等="
            "δ_in（环路滤波状态连续，identity_at_t0_dev_db 仅在栅格含 0 "
            "时回显）；渐近=δ_in/(1+T)（asymptote_dev_db 仅在末栅格 "
            ">20τ 时回显=e^{−20} 机器带）；正阶跃 attack 用快档、负阶跃 "
            "release 用慢档——两档时间常数比=ρ 恒等；一阶线性化边界见 "
            "agc_loop_dynamics 注记"),
        "source": _SOURCE,
    }
