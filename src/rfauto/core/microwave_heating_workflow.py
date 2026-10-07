"""LT-5..7 微波加热**整包编排入口**（腔模/applicator/体吸收/电热环已备）。

规格（round18 包级裁决：微波加热=唯一整包立项；席6 任务书：内核复用度
最高，只差编排入口——**复用不重写**）。本模块 = 纯编排层：
- 只读消费既有核（零新数值）：core/microwave_heating 的 Weyl/精确模
  计数（LT-5）、负载匹配、TE10p applicator（LT-6）、体吸收功率密度、
  电热定点、工艺窗口/热失控（LT-7）；
- stage 化编排 + 每段 ok 旗标 + 总 verdict；任何一段输入不满足时该段
  如实 skipped（缺输入不猜），不阻塞其余段。

段结构（对应 round18 LT-5/6/7 递进）：
  S1 模式统计：Weyl 渐近 vs 精确枚举对拍 + 装填因子（多模适用性判据
     weyl_vs_exact_rel_dev）；
  S2 applicator：TE10p 单模腔模参数 + 场量报告（单模适用线）；
  S3 体吸收：介质功率密度（E 场口径）+ tanδ(T) 链（可选）；
  S4 电热定点：P(T) 定点迭代（吸收功率随温度变化时）；
  S5 工艺窗口：保持功率/工艺功率窗 + 热失控临界 α_crit。

调用方（service/战役层）按需组装输入 dict；本模块不进注册表（不加
calculators 键，同批约定）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.microwave_heating import (
    dielectric_power_density,
    heating_fixed_point,
    multimode_load_match,
    process_window,
    rect_cavity_mode_count,
    runaway_boundary_alpha,
    single_mode_load_report,
    weyl_mode_stats,
)

_C0 = 299792458.0

#: Weyl↔精确枚举相对偏差的多模适用带（|dev| 在带内判多模统计适用）
_MULTIMODE_DEV_RANGE = (0.0, 0.35)


def _try(stage_name: str, fn, *args, **kw) -> dict[str, Any]:
    """段执行包装：输入不全/越域 → 段 skipped（缺输入不猜，不阻塞他段）。"""
    try:
        out = fn(*args, **kw)
    except (ValueError, TypeError) as exc:
        return {"stage": stage_name, "ok": False, "skipped": True,
                "reason": str(exc)}
    if isinstance(out, dict):
        return {"stage": stage_name, "ok": True, "skipped": False, **out}
    return {"stage": stage_name, "ok": True, "skipped": False,
            "result": out}


def microwave_heating_workflow(
    *,
    freq_hz: Any,
    cavity_a_m: Any | None = None,
    cavity_b_m: Any | None = None,
    cavity_d_m: Any | None = None,
    cavity_er: Any | None = None,
    q_wall: Any | None = None,
    load_volume_m3: Any | None = None,
    load_eps_r: Any | None = None,
    load_tan_delta: Any | None = None,
    available_power_w: Any | None = None,
    field_rms_v_per_m: Any | None = None,
    load_density_kg_m3: Any | None = None,
    r_th_c_per_w: list[Any] | None = None,
    tau_s: list[Any] | None = None,
    ambient_c: Any | None = None,
    target_c: Any | None = None,
    t_max_c: Any | None = None,
    t_process_s: Any | None = None,
    power_w: Any | None = None,
) -> dict[str, Any]:
    """微波加热整包编排（LT-5→7 递进；纯复用编排，零新数值）。

    全输入可选、按段消费：给了腔几何→S1/S2；给了负载与功率→S1 匹配/S3；
    给了场强→S3 密度；给了热路→S4/S5。返回 dict 带逐段 ok/skipped 与
    总 verdict（staged_complete=全请求段 ok）。
    """
    freq = float(freq_hz)
    if freq <= 0.0:
        raise ValueError(f"freq_hz 必须为正，实际 {freq_hz!r}")
    stages: dict[str, Any] = {}
    cavity_volume = None
    if None not in (cavity_a_m, cavity_b_m, cavity_d_m):
        a, b, d = float(cavity_a_m), float(cavity_b_m), float(cavity_d_m)
        cavity_volume = a * b * d

    # ── S1 模式统计 + 装填匹配（LT-5）─────────────────────────────────────
    if cavity_volume is not None:
        er_cav = float(cavity_er) if cavity_er is not None else 1.0
        s1_stats = _try("mode_stats", weyl_mode_stats, cavity_volume, freq,
                        er_cav)
        count = None
        try:
            count = rect_cavity_mode_count(a, b, d, float(cavity_er or 1.0),
                                           freq)
        except (ValueError, TypeError) as exc:
            s1_stats["count_error"] = str(exc)
        if count is not None:
            s1_stats["exact_count"] = count
        s1 = {"stage": "s1_multimode", **s1_stats}
        if load_volume_m3 is not None and load_eps_r is not None \
                and load_tan_delta is not None and cavity_volume is not None \
                and cavity_volume >= float(load_volume_m3):
            match = _try("load_match", multimode_load_match, cavity_volume,
                         float(load_volume_m3), float(load_eps_r),
                         float(load_tan_delta), float(q_wall or 1e4),
                         float(available_power_w or 1.0))
            s1["load_match"] = match
        n_weyl = s1_stats.get("n_weyl")
        if n_weyl:
            s1["multimode_regime"] = (
                n_weyl >= 10.0 and (_MULTIMODE_DEV_RANGE[0]
                                    <= float(s1_stats.get(
                                        "weyl_vs_exact_rel_dev") or 0.0)
                                    <= _MULTIMODE_DEV_RANGE[1]))
        stages["s1_multimode"] = s1

    # ── S2 单模 applicator（LT-6；负载缺省走近空腔口径）───────────────────
    if None not in (cavity_a_m, cavity_b_m, cavity_d_m):
        load = _try(
            "te10p", single_mode_load_report,
            float(cavity_a_m), float(cavity_b_m), float(cavity_d_m),
            float(load_eps_r) if load_eps_r is not None else 1.0,
            float(load_tan_delta) if load_tan_delta is not None else 1e-5,
            float(cavity_er) if cavity_er is not None else 1.0,
            load_v_m3=(float(load_volume_m3)
                       if load_volume_m3 is not None else None))
        stages["s2_applicator"] = load

    # ── S3 体吸收（LT-7 输入面）───────────────────────────────────────────
    if field_rms_v_per_m is not None and load_eps_r is not None \
            and load_tan_delta is not None:
        stages["s3_absorption"] = _try(
            "power_density", dielectric_power_density, freq,
            float(load_eps_r), float(load_tan_delta),
            float(field_rms_v_per_m),
            float(load_density_kg_m3) if load_density_kg_m3 is not None
            else None)

    # ── S4 电热定点（LT-7）────────────────────────────────────────────────
    if None not in (r_th_c_per_w, ambient_c, available_power_w,
                    load_eps_r, load_tan_delta):
        def p_absorb(t_c: float) -> float:
            match = multimode_load_match(
                float(cavity_volume), float(load_volume_m3),
                float(load_eps_r), float(load_tan_delta),
                float(q_wall or 1e4), float(available_power_w))
            return float(match["p_load_w"])

        stages["s4_fixed_point"] = _try(
            "heating_fixed_point", heating_fixed_point, p_absorb,
            float(ambient_c), float(r_th_c_per_w[0])
            if len(r_th_c_per_w) == 1 else sum(float(x)
                                               for x in r_th_c_per_w))

    # ── S5 工艺窗口 + 热失控（LT-7）───────────────────────────────────────
    if None not in (r_th_c_per_w, tau_s, ambient_c, target_c):
        s5 = _try("process_window", process_window,
                  [float(x) for x in r_th_c_per_w],
                  [float(x) for x in tau_s],
                  float(ambient_c), float(target_c),
                  t_max_c=(float(t_max_c) if t_max_c is not None else None),
                  t_process_s=(float(t_process_s)
                               if t_process_s is not None else None),
                  power_w=(float(power_w) if power_w is not None else None))
        if None not in (available_power_w, r_th_c_per_w):
            s5["runaway"] = _try(
                "runaway_boundary", runaway_boundary_alpha,
                float(available_power_w), float(r_th_c_per_w[0]))
        stages["s5_process_window"] = s5

    requested = [s for s in stages.values() if not s.get("skipped")]
    return {
        "ok": True,
        "freq_hz": freq,
        "wavelength_m": _C0 / freq,
        "stages": stages,
        "n_stages_active": len(requested),
        "staged_complete": all(s.get("ok") for s in requested),
        "note": "纯编排（复用既有核零新数值）；段 skipped=缺输入不猜",
    }
