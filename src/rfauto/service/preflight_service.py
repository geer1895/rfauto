"""preflight：开工前统一预检门面（XC-F，plan_deepdive_specs B-4，`rfauto preflight` 的 service 面）。

**门面=组装者不是新判据**（同 design_lint 先例）：五个子门只调用既有
core/service 函数——0 精度档案（XC-P precision_profiles）/ 1 极限守卫
（bounds Bode-Fano + Chu 信息界）/ 2 功率容量（high_power.power_capacity_
report）/ 3 热降额（high_power.thermal_from_average_power）/ 4 加工 DFM
（fab_service.check_template_dfm）。本模块零新增物理判据（硬规则 7）。

payload 契约（JSON 进出，全部键可选；缺段=该门 unknown 不阻塞其余门，
#105 best-effort；门面层任何单门崩溃同样降级为 unknown 行）::

    {
      "gates": ["precision", "limits", "power", "thermal", "fab"]?,
          # 只跑子集；未知名 → ValueError（程序性错误，如实抛出）
      "precision": {"checks": [{"kernel_id", "quantity", "point"?}...]}?,
          # XC-P 精度档案越域预检（域外 REFUSE 由内核抛 → 本面记 fail）
      "limits": {
        "bode_fano": {"load": [R, C] | 复阻抗采样, "f"?, "gamma_target",
                      "bandwidth"}?,
        "chu": {"bbox_m": [米], "f_hz" | "f_ghz", "polarization"?}?,
      }?,
      "power": {"power_levels_w": [...], "reference_power_w",
                "reference_field_peak_mv_per_m", "material"?,
                "safety_factor"?, "material_strength_mv_per_m"?,
                "required_margin_db"?, "source"?}?,
      "thermal": {"power_w", "theta_jc_c_per_w", "ambient_c"?,
                  "theta_cs_c_per_w"?, "theta_sa_c_per_w"?,
                  "parallel_paths_c_per_w"?, "max_junction_c"?}?,
      "fab": {"template", "params"?, "profile"?, "material"?, "copper_oz"?,
              "surface_finish"?, "board_thickness_mm"?}?,
    }

status 语义与 design_lint 同源：pass / fail（检出违规或非法输入）/
warn（可行但降级，如 Bode-Fano marginal）/ unknown（段缺或内核不可判，
**unknown 不算 fail**）/ info（Chu 界等信息行，不影响 verdict）。

verdict 聚合（与 design_lint 同式）：fail>0 → ``issues``；warn/unknown>0 →
``attention``；否则 ``clean``。

预声明判据分派（#122）：
- Bode-Fano ``unreachable`` → fail（匹配规格物理不可达=硬守卫拦下）；
  ``marginal`` → warn；``reachable`` → pass。
- Chu/directivity 界恒为 info（极限界是设计参考非违规，design_lint 口径）。
- power ``all_pass`` → pass，否则 fail（first_failing_power_w 随行）。
- thermal ``pass`` 三值直译：None（未给 max_junction_c）→ info；
  True → pass；False → fail。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rfauto.service.envelope import ok_envelope

_GATE_NAMES = ("precision", "limits", "power", "thermal", "fab")
"""子门全集（顺序=调用序 0..4；聚合一致性由测试钉住）。"""

_SOURCE = "rfauto.service.preflight_service"


def _row(name: str, status: str, detail: str, source: str,
         result: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "status": status,
                           "detail": detail, "source": source}
    if result is not None:
        row["result"] = result
    return row


def _best_effort(fn: Callable[[dict[str, Any]], dict[str, Any]],
                 name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """单门崩溃降级 unknown 行，不阻塞其余门（#105 best-effort 门面纪律）。"""
    try:
        return fn(payload)
    except Exception as exc:  # 门面层兜底，异常原文透传
        return _row(name, "unknown",
                    f"门执行异常（降级不阻塞，#105）: {type(exc).__name__}: {exc}",
                    _SOURCE)


# ─── 0 precision（XC-P 精度档案越域预检） ────────────────────────────────────

_PRECISION_SOURCE = "rfauto.core.precision_profiles.precision_profile"


def _gate_precision(payload: dict[str, Any]) -> dict[str, Any]:
    from rfauto.core.precision_profiles import precision_profile

    section = payload.get("precision")
    if not isinstance(section, dict) or not section.get("checks"):
        return _row("precision", "unknown",
                    "未提供 precision.checks（精度档案越域预检按需运行）",
                    _PRECISION_SOURCE)
    checks = section["checks"]
    if not isinstance(checks, list) or \
            not all(isinstance(c, dict) for c in checks):
        return _row("precision", "fail",
                    "precision.checks 必须是 {kernel_id, quantity, point?} 对象列表",
                    _PRECISION_SOURCE)
    out_of_domain: list[str] = []   # WARN 档（UNVERIFIED 档归 unknown）
    refused: list[str] = []         # REFUSE 抛出=确认越域 → fail
    not_judgeable = 0               # point 缺/in_domain None → unknown 计数
    details: list[dict[str, Any]] = []
    for chk in checks:
        try:
            res = precision_profile(str(chk["kernel_id"]), str(chk["quantity"]),
                                    chk.get("point"))
        except (KeyError, TypeError, ValueError) as exc:
            refused.append(str(exc))
            details.append({"check": chk, "error": str(exc)})
            continue
        details.append(res)
        if res["in_domain"] is True:
            continue
        if res["in_domain"] is None or res.get("behavior") == "UNVERIFIED":
            not_judgeable += 1
        else:
            out_of_domain.append(
                f"{res['kernel_id']}.{res['quantity']}（behavior={res['behavior']}）")
    if refused:
        return _row("precision", "fail",
                    f"精度档案 REFUSE/查询失败 {len(refused)} 项: {refused}",
                    _PRECISION_SOURCE, result={"details": details})
    if out_of_domain:
        return _row("precision", "warn",
                    f"{len(out_of_domain)} 项确认域外（典型偏差分档不适用）: "
                    + "；".join(out_of_domain),
                    _PRECISION_SOURCE, result={"details": details})
    if not_judgeable:
        return _row("precision", "unknown",
                    f"{not_judgeable} 项域不可判（point 缺失或 UNVERIFIED 档）",
                    _PRECISION_SOURCE, result={"details": details})
    return _row("precision", "pass",
                f"{len(checks)} 项精度档案查询全部域内",
                _PRECISION_SOURCE, result={"details": details})


# ─── 1 limits（Bode-Fano 硬守卫 + Chu 信息界） ──────────────────────────────

_LIMITS_SOURCE = "rfauto.core.bounds.bode_fano_rc+chu_q_bound+bbox_to_ka"


def _gate_limits(payload: dict[str, Any]) -> dict[str, Any]:
    from rfauto.core.bounds import bbox_to_ka, bode_fano_rc, chu_q_bound

    section = payload.get("limits")
    if not isinstance(section, dict) or not section:
        return _row("limits", "unknown",
                    "未提供 limits（bode_fano / chu 任一即可）", _LIMITS_SOURCE)
    results: dict[str, Any] = {}
    fails: list[str] = []
    warns: list[str] = []
    infos: list[str] = []
    unknowns: list[str] = []

    bf = section.get("bode_fano")
    if bf is not None:
        if not isinstance(bf, dict) or bf.get("gamma_target") is None \
                or bf.get("bandwidth") is None or bf.get("load") is None:
            unknowns.append("bode_fano 参数不足（load/gamma_target/bandwidth 必给）")
        else:
            try:
                f = bf.get("f")
                verdict = bode_fano_rc(bf["load"], f,
                                       gamma_target=float(bf["gamma_target"]),
                                       bandwidth=float(bf["bandwidth"]))
                results["bode_fano"] = verdict.to_dict()
                if verdict.verdict == "reachable":
                    infos.append(
                        f"Bode-Fano 可达（margin_ratio={verdict.margin_ratio:.3g}）")
                elif verdict.verdict == "marginal":
                    warns.append(
                        f"Bode-Fano 边缘（margin_ratio={verdict.margin_ratio:.3g}）")
                else:
                    fails.append(
                        f"Bode-Fano 不可达（margin_ratio={verdict.margin_ratio:.3g}，"
                        f"τ=RC={verdict.tau_s:.3g}s）")
            except (KeyError, TypeError, ValueError) as exc:
                fails.append(f"bode_fano 入参非法: {exc}")

    chu = section.get("chu")
    if chu is not None:
        bbox = chu.get("bbox_m")
        f_hz = chu.get("f_hz")
        f_ghz = chu.get("f_ghz")
        if not bbox or (f_hz is None and f_ghz is None):
            unknowns.append("chu 参数不足（bbox_m + f_hz/f_ghz）")
        else:
            try:
                freq = float(f_hz) if f_hz is not None else float(f_ghz) * 1e9
                ka = bbox_to_ka(bbox, freq)
                chu_d = chu_q_bound(ka, str(chu.get("polarization", "linear"))).to_dict()
                results["chu"] = {"ka": ka, **chu_d}
                infos.append(f"Chu Q_min={chu_d.get('limit_value')}"
                             f"（ka={ka:.4g}，信息性界）")
            except (KeyError, TypeError, ValueError) as exc:
                fails.append(f"chu 入参非法: {exc}")

    if fails:
        status, detail = "fail", "；".join(fails + warns + unknowns)
    elif warns:
        status, detail = "warn", "；".join(warns + unknowns) or "Bode-Fano 边缘"
    elif unknowns:
        status, detail = "unknown", "；".join(unknowns)
    else:
        status, detail = "info", "；".join(infos)
    return _row("limits", status, detail, _LIMITS_SOURCE, result=results or None)


# ─── 2 power（功率容量容量门） ───────────────────────────────────────────────

_POWER_SOURCE = "rfauto.core.high_power.power_capacity_report"


def _gate_power(payload: dict[str, Any]) -> dict[str, Any]:
    from rfauto.core.high_power import power_capacity_report

    p = payload.get("power")
    if not isinstance(p, dict):
        return _row("power", "unknown",
                    "未提供 power（power_levels_w + reference_* 必给）",
                    _POWER_SOURCE)
    required = ("power_levels_w", "reference_power_w",
                "reference_field_peak_mv_per_m")
    missing = [k for k in required if p.get(k) is None]
    if missing:
        return _row("power", "unknown", f"power 参数不足（缺 {missing}）",
                    _POWER_SOURCE)
    try:
        rep = power_capacity_report(
            list(p["power_levels_w"]),
            reference_power_w=float(p["reference_power_w"]),
            reference_field_peak_mv_per_m=float(p["reference_field_peak_mv_per_m"]),
            material=p.get("material", "air"),
            safety_factor=float(p.get("safety_factor", 1.0)),
            material_strength_mv_per_m=p.get("material_strength_mv_per_m"),
            required_margin_db=float(p.get("required_margin_db", 0.0)),
            source=str(p.get("source", "recorded")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _row("power", "fail", f"power 入参非法: {exc}", _POWER_SOURCE)
    if rep.get("all_pass"):
        return _row("power", "pass",
                    f"全部 {len(rep['entries'])} 档功率容量通过"
                    f"（max_passing={rep.get('max_passing_power_w')}W）",
                    _POWER_SOURCE, result=rep)
    return _row("power", "fail",
                f"功率容量越限（first_failing={rep.get('first_failing_power_w')}W，"
                f"material={rep['reference']['material']}）",
                _POWER_SOURCE, result=rep)


# ─── 3 thermal（热降额门） ───────────────────────────────────────────────────

_THERMAL_SOURCE = "rfauto.core.high_power.thermal_from_average_power"


def _gate_thermal(payload: dict[str, Any]) -> dict[str, Any]:
    from rfauto.core.high_power import thermal_from_average_power

    t = payload.get("thermal")
    if not isinstance(t, dict):
        return _row("thermal", "unknown",
                    "未提供 thermal（power_w + theta_jc_c_per_w 必给）",
                    _THERMAL_SOURCE)
    if t.get("power_w") is None or t.get("theta_jc_c_per_w") is None:
        return _row("thermal", "unknown",
                    "thermal 参数不足：power_w 与 theta_jc_c_per_w 必给",
                    _THERMAL_SOURCE)
    try:
        kwargs: dict[str, Any] = {}
        if t.get("ambient_c") is not None:
            kwargs["ambient_c"] = float(t["ambient_c"])
        for key in ("theta_cs_c_per_w", "theta_sa_c_per_w"):
            if t.get(key) is not None:
                kwargs[key] = float(t[key])
        if t.get("parallel_paths_c_per_w") is not None:
            kwargs["parallel_paths_c_per_w"] = list(t["parallel_paths_c_per_w"])
        if t.get("max_junction_c") is not None:
            kwargs["max_junction_c"] = t["max_junction_c"]
        rep = thermal_from_average_power(float(t["power_w"]),
                                         theta_jc_c_per_w=float(t["theta_jc_c_per_w"]),
                                         **kwargs)
    except (KeyError, TypeError, ValueError) as exc:
        return _row("thermal", "fail", f"thermal 入参非法: {exc}", _THERMAL_SOURCE)
    if rep.get("pass") is None:
        return _row("thermal", "info",
                    f"Tj={rep.get('junction_temp_c')}°C（未给 max_junction_c，"
                    "只出结温信息行不判）",
                    _THERMAL_SOURCE, result=rep)
    if rep["pass"] is True:
        return _row("thermal", "pass",
                    f"Tj={rep.get('junction_temp_c')}°C ≤ "
                    f"max_junction_c={rep.get('max_junction_c')}°C",
                    _THERMAL_SOURCE, result=rep)
    return _row("thermal", "fail",
                f"Tj={rep.get('junction_temp_c')}°C > "
                f"max_junction_c={rep.get('max_junction_c')}°C（热降额越限）",
                _THERMAL_SOURCE, result=rep)


# ─── 4 fab（加工 DFM 门；与 design_lint.fab 共享内核 check_template_dfm） ────

_FAB_SOURCE = "rfauto.service.fab_service.check_template_dfm"


def _gate_fab(payload: dict[str, Any]) -> dict[str, Any]:
    from rfauto.service.fab_service import check_template_dfm

    f = payload.get("fab")
    if not isinstance(f, dict) or not f.get("template"):
        return _row("fab", "unknown",
                    "未提供 fab.template（DFM 门按模板名义几何运行）", _FAB_SOURCE)
    try:
        result = check_template_dfm(
            str(f["template"]), f.get("params"),
            profile=str(f.get("profile", "jlcpcb")),
            material=str(f.get("material", "rogers4350b_h0.508")),
            copper_oz=float(f.get("copper_oz", 1.0)),
            surface_finish=f.get("surface_finish"),
            board_thickness_mm=f.get("board_thickness_mm"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _row("fab", "fail", f"DFM 入参非法: {exc}", _FAB_SOURCE)
    if result.get("ran") is not True:
        errs = "；".join(str(e) for e in result.get("errors") or ["DFM 检查失败"])
        return _row("fab", "fail", errs, _FAB_SOURCE, result=result)
    violations = result.get("violations") or []
    if violations:
        codes = [str(v.get("code")) for v in violations]
        return _row("fab", "fail", f"{len(violations)} 项 DFM 违规: {codes}",
                    _FAB_SOURCE, result=result)
    return _row("fab", "pass", "无 DFM 违规", _FAB_SOURCE, result=result)


_GATES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "precision": _gate_precision,
    "limits": _gate_limits,
    "power": _gate_power,
    "thermal": _gate_thermal,
    "fab": _gate_fab,
}


def preflight(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """开工前统一预检：payload → {gates, summary, verdict, blocked}。

    缺省五门全跑（顺序 0..4）；``gates`` 给子集时只跑子集（未知名抛
    ValueError——程序性错误）。任何单门段缺/崩溃都归一为 unknown 行不
    阻塞其余门（#105 best-effort）；检出 fail 照常拦。verdict 语义与
    design_lint 同源：fail>0 → ``issues``；warn/unknown>0 → ``attention``；
    否则 ``clean``。
    """
    payload = dict(payload or {})
    requested = payload.get("gates")
    if requested is None:
        names = list(_GATES)
    else:
        if not isinstance(requested, list) or \
                not all(isinstance(n, str) for n in requested):
            raise ValueError("gates 必须是字符串列表")
        unknown_names = [n for n in requested if n not in _GATES]
        if unknown_names:
            raise ValueError(f"未知子门: {unknown_names}（可用: {list(_GATES)}）")
        names = list(requested)
    rows = [_best_effort(_GATES[name], name, payload) for name in names]
    summary: dict[str, int] = {"pass": 0, "fail": 0, "warn": 0,
                               "unknown": 0, "info": 0}
    for row in rows:
        st = str(row["status"])
        summary[st] = summary.get(st, 0) + 1
    if summary["fail"] > 0:
        verdict = "issues"
    elif summary["warn"] > 0 or summary["unknown"] > 0:
        verdict = "attention"
    else:
        verdict = "clean"
    blocked = [r["name"] for r in rows if r["status"] == "unknown"
               and "降级不阻塞" in str(r["detail"])]
    return ok_envelope(gates=rows, summary=summary,
                       verdict=verdict, blocked=blocked)
