"""微波加热族（LT-5..7，内核在 core/microwave_heating.py，本模块只做注册壳）。

round18 §五 :137-144 规格「微波加热=唯一整包立项（LT-5/6/7 递进）」
（2026-10-02）。三键：多模腔模式统计+装填因子 / 单模 applicator 功率
沉积链 / 工艺窗口+热失控。weyl/精确计数/装填匹配、TE10p 场量、体吸收/
定点迭代/失控界/工艺窗为 core 纯函数不注册（分析面走 core 直调）；
shield_cavity_mode/thermal_transient 只读消费零改动；微扰失谐在本壳
组合 calc_families.cavity.cavity_perturbation_shift（规格 :140「复用
cavity_perturbation_shift」口径，不重实现）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


def _require_all_or_none(
    given: dict[str, Any], names: tuple[str, ...], block: str,
) -> None:
    """块参数全给或全不给（部分给显式报错，不静默取缺省拼凑）。"""
    filled = [n for n in names if given.get(n) is not None]
    if filled and len(filled) != len(names):
        missing = [n for n in names if given.get(n) is None]
        raise ValueError(
            f"{block} 块参数须全给或全不给；缺 {missing}（已给 {filled}）")


@register_calculator(
    "multimode_cavity_heating",
    "LT-5 多模腔模式统计+装填因子（round18 :137）：Weyl 渐近 "
    "N=8πV(f√εr/c0)³/3（双极化，Metaxas & Meredith Ch.5 口径）+ 矩形腔"
    "精确枚举交叉对拍（复用 shield_cavity_mode.rect_cavity_modes，TE 容许"
    "集+TM 子集分开计）+ 模式密度/平均模间距；可选负载块（全给或全不给）："
    "均匀场装填因子 F=εr′V_l/(εr′V_l+V_c−V_l)、Q_d=1/(F·tanδ)、效率 "
    "η=Q_L/Q_d 与负载吸收功率（匹配源口径）；1kW 水负载经典量级锚见锚树",
    (("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 边长（>0）"),
     ("d_mm", "float mm 腔 z 边长（>0）"),
     ("f_ghz", "float GHz 统计频率（>0）"),
     ("er", "float - 腔内介质相对介电常数（>0，缺省 1=空气腔）"),
     ("v_load_l", "float L 负载体积（负载块；>0，≤腔体积）"),
     ("load_eps_r", "float - 负载 εr′（负载块；>0）"),
     ("load_tan_d", "float - 负载 tanδ（负载块；>0）"),
     ("q_wall", "float - 空腔壁损 unloaded Q（负载块；>0）"),
     ("power_w", "float W 输入功率（>0，缺省 1）")),
    required=("a_mm", "b_mm", "d_mm", "f_ghz"),
)
def multimode_cavity_heating(
    a_mm: float,
    b_mm: float,
    d_mm: float,
    f_ghz: float,
    er: float = 1.0,
    v_load_l: float | None = None,
    load_eps_r: float | None = None,
    load_tan_d: float | None = None,
    q_wall: float | None = None,
    power_w: float = 1.0,
) -> dict:
    from rfauto.core.microwave_heating import (
        multimode_load_match,
        rect_cavity_mode_count,
        weyl_mode_stats,
    )

    a = a_mm * 1.0e-3
    b = b_mm * 1.0e-3
    d = d_mm * 1.0e-3
    f_hz = f_ghz * 1.0e9
    stats = weyl_mode_stats(a * b * d, f_hz, er)
    count = rect_cavity_mode_count(a, b, d, er, f_hz)
    out: dict[str, Any] = {
        "volume_m3": stats["volume_m3"],
        "f_hz": stats["f_hz"],
        "er": stats["er"],
        "n_weyl": stats["n_weyl"],
        "mode_density_per_hz": stats["mode_density_per_hz"],
        "mean_spacing_hz": stats["mean_spacing_hz"],
        "n_exact_te": count["te_count"],
        "n_exact_tm": count["tm_count"],
        "n_exact_total": count["total"],
        "scan_orders": count["scan_orders"],
    }
    if n_weyl := out["n_weyl"]:
        out["weyl_vs_exact_rel_dev"] = (
            out["n_exact_total"] - n_weyl) / n_weyl
    else:  # pragma: no cover - f>0 守卫保证走不到
        out["weyl_vs_exact_rel_dev"] = None
    _require_all_or_none(
        {"v_load_l": v_load_l, "load_eps_r": load_eps_r,
         "load_tan_d": load_tan_d, "q_wall": q_wall},
        ("v_load_l", "load_eps_r", "load_tan_d", "q_wall"),
        "负载（load）")
    if v_load_l is not None:
        load = multimode_load_match(
            a * b * d, v_load_l * 1.0e-3, load_eps_r, load_tan_d, q_wall,
            power_w)
        out["load"] = load
    return out


@register_calculator(
    "single_mode_applicator",
    "LT-6 单模 applicator（round18 :140）：TE10p 矩形腔谐振频率+场量归一"
    "（∫|E|²=V/4、储能 W=ε0εrE0²V/8、壁损逐壁闭式→Q_c）+介质负载功率沉积"
    "链（微扰装填因子 F=4εr′V_l·s/εrV、1/Q_d=F·tanδ、耦合 β=Q_u/Q_e、"
    "谐振吸收 4β/(1+β)²、能量平衡→E0 与 P_load 双路恒等）；可选样品块"
    "（sample_box_mm+sample_eps_r）触发介质微扰失谐（复用 "
    "cavity_perturbation_shift，Pozar §6.7 口径）。峰值 phasor 口径"
    "（P=(ω/2)ε0εr″∫|E|²dV）",
    (("a_mm", "float mm 腔 x 边长（>0）"),
     ("b_mm", "float mm 腔 y 边长（>0）"),
     ("d_mm", "float mm 腔 z 边长（>0）"),
     ("wall_sigma_s_per_m", "float S/m 腔壁电导率（>0，铜 5.8e7）"),
     ("er", "float - 腔内介质相对介电常数（>0，缺省 1）"),
     ("p_index", "int - z 向半波数 p（≥1，缺省 1=TE101）"),
     ("input_power_w", "float W 输入功率（>0，缺省 1）"),
     ("load_v_l", "float L 介质负载体积（缺省 None=空腔）"),
     ("load_eps_r", "float - 负载 εr′（给 load_v_l 时必给，>0）"),
     ("load_tan_d", "float - 负载 tanδ（给 load_v_l 时必给，>0）"),
     ("q_ext", "float - 外部耦合 Q（>0；缺省 None=匹配口径）"),
     ("load_x_mm", "float mm 负载重心 x（缺省 a/2 波腹）"),
     ("load_z_mm", "float mm 负载重心 z（缺省 d/2 波腹；偶 p 中心为波节"
      "会显式报错）"),
     ("sample_box_mm", "array [x0,y0,z0,x1,y1,z1] 微扰失谐样品盒（mm，"
      "腔内；给则触发 cavity_perturbation_shift）"),
     ("sample_eps_r", "float - 样品 εr（>1 介质微扰；缺省 None=金属微扰"
      "路线，透传复用键口径）")),
    required=("a_mm", "b_mm", "d_mm", "wall_sigma_s_per_m"),
)
def single_mode_applicator(
    a_mm: float,
    b_mm: float,
    d_mm: float,
    wall_sigma_s_per_m: float,
    er: float = 1.0,
    p_index: int = 1,
    input_power_w: float = 1.0,
    load_v_l: float | None = None,
    load_eps_r: float | None = None,
    load_tan_d: float | None = None,
    q_ext: float | None = None,
    load_x_mm: float | None = None,
    load_z_mm: float | None = None,
    sample_box_mm: list | None = None,
    sample_eps_r: float | None = None,
) -> dict:
    from rfauto.core.microwave_heating import single_mode_load_report

    _require_all_or_none(
        {"load_v_l": load_v_l, "load_eps_r": load_eps_r,
         "load_tan_d": load_tan_d},
        ("load_v_l", "load_eps_r", "load_tan_d"),
        "负载（load）")
    a = a_mm * 1.0e-3
    b = b_mm * 1.0e-3
    d = d_mm * 1.0e-3
    if load_x_mm is None and load_z_mm is None:
        centroid = None
    else:
        if load_x_mm is None or load_z_mm is None:
            raise ValueError("load_x_mm 与 load_z_mm 须同时给")
        centroid = (load_x_mm * 1.0e-3, load_z_mm * 1.0e-3)
    out: dict[str, Any] = single_mode_load_report(
        a, b, d, load_eps_r if load_eps_r is not None else 1.0,
        load_tan_d if load_tan_d is not None else 1.0,
        er=er,
        p_index=p_index,
        load_v_m3=None if load_v_l is None else load_v_l * 1.0e-3,
        wall_sigma_s_per_m=wall_sigma_s_per_m,
        input_power_w=input_power_w,
        q_ext=q_ext,
        load_centroid_m=centroid,
    )
    if sample_box_mm is not None:
        from .cavity import cavity_perturbation_shift

        detune = cavity_perturbation_shift(
            a_mm, b_mm, d_mm, sample_box_mm=sample_box_mm,
            sample_eps_r=sample_eps_r)
        out["perturbation"] = {
            "f0_ghz": detune["f0_ghz"],
            "df_over_f": detune["df_over_f"],
            "df_ghz": detune["df_ghz"],
            "field_weight_ratio": detune["field_weight_ratio"],
            "perturbation": detune["perturbation"],
            "route": detune["route"],
            "f_operating_ghz": detune["f0_ghz"] * (1.0 + detune["df_over_f"]),
        }
    return out


@register_calculator(
    "microwave_process_window",
    "LT-7 烘干/烧结工艺窗口+热失控（round18 :142）：Foster (R,τ) 阶跃热"
    "响应（复用 thermal_transient.step_response_zth，MP-1 零改动）→ 目标"
    "温度功率/时间窗（保持功率 ΔT/ΣR、工艺时刻所需功率 ΔT/Z_th(t)、给定"
    "功率到达时间二分反解、稳态越限旗标）；可选失控块（全给或全不给）："
    "tanδ(T)=tanδ_ref·e^{α(T−T_ref)} 体吸收链 P(T)→定点迭代（方法论同 "
    "thermal_iteration）+稳定性斜率 R_th·dP/dT 临界+解析失控界 "
    "α_crit=1/(e·R_th·P0)（收敛/失控分界由锚树复现）。体吸收为 rms 场口径",
    (("r_th_c_per_w", "array Foster 热阻表 °C/W（非空逐项 >0）"),
     ("tau_s", "array Foster 时间常数表 s（等长逐项 >0）"),
     ("ambient_c", "float °C 环境温度"),
     ("target_c", "float °C 目标温度（>ambient_c）"),
     ("t_max_c", "float °C 温度上限（≥target_c；给功率窗上沿/越限旗标）"),
     ("t_process_s", "float s 工艺时刻（>0；给所需功率/功率窗）"),
     ("power_w", "float W 给定功率（>0；给到达时间）"),
     ("f_ghz", "float GHz 加热频率（失控块触发键）"),
     ("e_rms_v_per_m", "float V/m rms 场强（失控块）"),
     ("load_v_l", "float L 负载体积（失控块）"),
     ("eps_r", "float - 负载 εr（>0，缺省 1）"),
     ("tan_d_ref", "float - 参考温度 tanδ（失控块，>0）"),
     ("alpha_per_k", "float 1/K tanδ 指数温升系数（失控块）"),
     ("t_ref_c", "float °C 材料参考温度（缺省 25）"),
     ("deps_d_t_per_k", "float 1/K εr 线性温度系数（缺省 0；失控界为一阶"
      "口径以 tanδ 指数主导为前提）")),
    required=("r_th_c_per_w", "tau_s", "ambient_c", "target_c"),
)
def microwave_process_window(
    r_th_c_per_w: list,
    tau_s: list,
    ambient_c: float,
    target_c: float,
    t_max_c: float | None = None,
    t_process_s: float | None = None,
    power_w: float | None = None,
    f_ghz: float | None = None,
    e_rms_v_per_m: float | None = None,
    load_v_l: float | None = None,
    eps_r: float = 1.0,
    tan_d_ref: float | None = None,
    alpha_per_k: float | None = None,
    t_ref_c: float = 25.0,
    deps_d_t_per_k: float = 0.0,
) -> dict:
    from rfauto.core.microwave_heating import (
        exponential_tand_power_chain,
        heating_fixed_point,
        process_window,
        runaway_boundary_alpha,
    )

    out: dict[str, Any] = process_window(
        r_th_c_per_w, tau_s, ambient_c, target_c,
        t_max_c=t_max_c, t_process_s=t_process_s, power_w=power_w)
    if f_ghz is None:
        return out
    _require_all_or_none(
        {"f_ghz": f_ghz, "e_rms_v_per_m": e_rms_v_per_m,
         "load_v_l": load_v_l, "tan_d_ref": tan_d_ref,
         "alpha_per_k": alpha_per_k},
        ("f_ghz", "e_rms_v_per_m", "load_v_l", "tan_d_ref", "alpha_per_k"),
        "失控（runaway）")
    power_fn = exponential_tand_power_chain(
        f_ghz * 1.0e9, eps_r, tan_d_ref, alpha_per_k, e_rms_v_per_m,
        load_v_l * 1.0e-3, t_ref_c=t_ref_c, deps_d_t_per_k=deps_d_t_per_k)
    r_total = out["r_total"]
    p0 = power_fn(t_ref_c)
    fixed = heating_fixed_point(power_fn, ambient_c, r_total)
    boundary = runaway_boundary_alpha(p0, r_total)
    out["runaway"] = {
        "p0_w": p0,
        "r_th_effective": r_total,
        "alpha_per_k": alpha_per_k,
        "alpha_crit_per_k": boundary["alpha_crit_per_k"],
        "alpha_margin_ratio": boundary["alpha_crit_per_k"] / alpha_per_k,
        "status": fixed["status"],
        "iterations": fixed["iterations"],
        "t_star_c": fixed["t_star_c"],
        "p_star_w": fixed["p_star_w"],
        "stability_slope": fixed["stability_slope"],
        "stability_margin": fixed["stability_margin"],
        "stable": fixed["stable"],
    }
    return out
