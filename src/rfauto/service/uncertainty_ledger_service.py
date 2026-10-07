"""uncertainty_ledger：全链不确定度账本（XC-U，round19 P1"四处挂点纯编排"）。

**纯编排层**（硬规则 7：零新物理数字）：四个挂点全部消费既有内核——

1. **材料 u95**：``dielectric_extract`` 提取链的 ``{er,tan_d}.u95`` 口径
   （调用方传入提取产物，本面不重跑提取）；
2. **仿真 u_num**：``core.error_budget`` BUDGET_REGISTRY（GridDiscretization
   两点分解 #313 / Tolerance / CalibrationResidual / SurrogateError 等）经
   ``budget_evaluate`` 合成——含 GCI 型网格离散项；
3. **测量 u_c**：``measurement.en_report.gum_combined_uncertainty``（GUM
   预算表 configs/uncertainty_budgets.yaml 同口径）；
4. **产线 U**：``core.manufacturing_stats.guardband_limits``（PT-1，
   ILAC-G8 保护带）——**缺省链通**：production 段未显式给 u95 时消费
   measurement 段产出的 U（测量不确定度顺流入产线判定=全链语义）。

输出（round19 规格）：逐段 {status, u_std, unit, contributions[]} +
跨段贡献表（Sankey 式=逐段逐分量占比）+ **"最大分量"指针** + u_chain.csv
渲染（:func:`write_uncertainty_chain_csv`）。

单位纪律（#121）：各段带 ``unit`` 声明；跨段"最大分量"只在**全部已判段
单位一致**时给出（异单位如实 ``cross_stage_max: null``+note，不跨单位混算）。

#105：段缺/入参不足 → 该段 ``unknown`` 行不阻塞其余段；段内核抛错 →
该段 ``error`` 行（异常原文透传）。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

_STAGES = ("material", "simulation", "measurement", "production")
_SOURCE = "rfauto.service.uncertainty_ledger_service"


def _stage_row(stage: str, status: str, detail: str,
               result: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"stage": stage, "status": status, "detail": detail}
    if result is not None:
        row["result"] = result
    return row


def _run_material(section: Any) -> dict[str, Any]:
    """材料段：dielectric_extract 的 u95 口径（调用方传提取产物值）。"""
    if not isinstance(section, dict):
        return _stage_row("material", "unknown",
                          "未提供 material（{name, u95, k?, unit?}；u95 为提取链"
                          " ErTanProfile 拟合的 95% 展开不确定度）")
    u95 = section.get("u95")
    if u95 is None:
        return _stage_row("material", "unknown",
                          "material.u95 缺（提取链未给/未传入）")
    try:
        u95_f = float(u95)
        if not u95_f > 0:
            raise ValueError(f"u95 必须为正，得到 {u95_f!r}")
        k = float(section.get("k", 2.0))
        if not k > 0:
            raise ValueError(f"k 必须为正，得到 {k!r}")
    except (TypeError, ValueError) as exc:
        return _stage_row("material", "error", f"material 入参非法: {exc}")
    u_std = u95_f / k
    return _stage_row(
        "material", "ok",
        f"材料不确定度 u={u_std:.6g}（U95={u95_f:.6g}/k={k:g}）",
        {"u_std": u_std, "u95": u95_f, "k": k,
         "unit": str(section.get("unit", "dimensionless")),
         "name": str(section.get("name", "material")),
         "contributions": [{"name": str(section.get("name", "material")),
                            "u": u_std, "share": 1.0}]})


def _run_simulation(section: Any) -> dict[str, Any]:
    """仿真段：BUDGET_REGISTRY 条目经 budget_evaluate 合成（含网格离散 GCI 项）。"""
    if not isinstance(section, dict):
        return _stage_row(
            "simulation", "unknown",
            "未提供 simulation（{items: [{type, **params}...], f_hz: [..], "
            "unit?}；type=BUDGET_REGISTRY 键如 budget.grid_discretization）")
    if section.get("u_num") is not None:
        # 旁路口径：上游已算好的仿真不确定度直入账本（诚实标注 bypass）
        try:
            u_num = float(section["u_num"])
        except (TypeError, ValueError) as exc:
            return _stage_row("simulation", "error",
                              f"simulation.u_num 非法: {exc}")
        return _stage_row("simulation", "ok",
                          f"仿真不确定度（bypass 直入）u={u_num:.6g}",
                          {"u_std": u_num, "unit": str(section.get("unit", "dB")),
                           "bypass": True,
                           "contributions": [{"name": "u_num(bypass)",
                                              "u": u_num, "share": 1.0}]})
    items_spec = section.get("items")
    f_hz = section.get("f_hz")
    if not items_spec or f_hz is None:
        return _stage_row("simulation", "unknown",
                          "simulation 参数不足（items 与 f_hz 必给；或直接传"
                          " u_num 旁路）")
    import numpy as np

    from rfauto.core.error_budget import BUDGET_REGISTRY, budget_evaluate

    try:
        items = []
        for spec in items_spec:
            if not isinstance(spec, dict) or "type" not in spec:
                raise ValueError(f"仿真段条目缺 type 键: {spec!r}")
            kwargs = {k: v for k, v in spec.items() if k != "type"}
            items.append(BUDGET_REGISTRY.create(str(spec["type"]), **kwargs))
        freq = np.asarray([float(x) for x in
                           (f_hz if isinstance(f_hz, (list, tuple)) else [f_hz])],
                          dtype=float)
        trace = budget_evaluate(freq, items)
    except (KeyError, TypeError, ValueError) as exc:
        return _stage_row("simulation", "error",
                          f"仿真段预算求值失败: {exc}")
    total = trace.quadratic_sum()
    u_std = float(np.mean(total))
    contribs = []
    for name, c in trace.contributions.items():
        cm = float(np.mean(np.abs(np.asarray(c, dtype=float))))
        contribs.append({"name": name, "u": cm,
                         "share": (cm / u_std) if u_std > 0 else None})
    contribs.sort(key=lambda d: -(d["u"] if d["u"] is not None else 0.0))
    return _stage_row(
        "simulation", "ok",
        f"仿真不确定度 u={u_std:.6g}（{len(items)} 条目频率均值合成，"
        f"含 GCI/网格离散项口径=error_budget）",
        {"u_std": u_std, "unit": str(section.get("unit", "dB")),
         "contributions": contribs})


def _run_measurement(section: Any) -> dict[str, Any]:
    """测量段：GUM 合成（en_report.gum_combined_uncertainty）。"""
    if not isinstance(section, dict):
        return _stage_row(
            "measurement", "unknown",
            "未提供 measurement（{components: [{name, u, unit?, c?, per_c?}"
            "...], k?, delta_t_c?}；configs/uncertainty_budgets.yaml 同口径）")
    components = section.get("components")
    if not components:
        return _stage_row("measurement", "unknown",
                          "measurement.components 缺（GUM 预算分量表）")
    from rfauto.measurement.en_report import gum_combined_uncertainty

    try:
        gum = gum_combined_uncertainty(
            list(components), k=float(section.get("k", 2.0)),
            delta_t_c=float(section.get("delta_t_c", 0.0) or 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        return _stage_row("measurement", "error", f"GUM 合成失败: {exc}")
    u_c = float(gum["u_c"])
    contribs = [{"name": c["name"], "u": float(c["contribution"]),
                 "share": (float(c["contribution"]) / u_c) if u_c > 0 else None}
                for c in gum.get("contributions", [])]
    contribs.sort(key=lambda d: -(d["u"] if d["u"] is not None else 0.0))
    return _stage_row(
        "measurement", "ok",
        f"测量合成不确定度 u_c={u_c:.6g}，U(k={gum.get('k')})="
        f"{float(gum.get('U', 0.0)):.6g}",
        {"u_std": u_c, "U": gum.get("U"), "k": gum.get("k"),
         "unit": str(section.get("unit", "dB")), "contributions": contribs})


def _run_production(section: Any, meas_u95: float | None) -> dict[str, Any]:
    """产线段：guardband_limits（PT-1）；u95 缺省链通 measurement 段 U。"""
    if not isinstance(section, dict):
        return _stage_row(
            "production", "unknown",
            "未提供 production（{value, spec, u95?, pfa_target?, side?, k?}；"
            "u95 缺省消费测量段 U=全链口径）")
    if section.get("value") is None or section.get("spec") is None:
        return _stage_row("production", "unknown",
                          "production 参数不足（value 与 spec 必给）")
    u95 = section.get("u95")
    chained = False
    if u95 is None:
        if meas_u95 is None:
            return _stage_row(
                "production", "unknown",
                "production.u95 缺且测量段无 U 可链通（全链断在测量段）")
        u95 = meas_u95
        chained = True
    from rfauto.core.manufacturing_stats import guardband_limits

    try:
        gb = guardband_limits(
            float(section["value"]), float(u95), section["spec"],
            pfa_target=float(section.get("pfa_target", 0.02)),
            side=str(section.get("side", "upper")),
            k=float(section.get("k", 1.96)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _stage_row("production", "error",
                          f"护栏带求值失败: {exc}")
    note = "（u95 链通测量段 U=全链口径）" if chained else ""
    return _stage_row(
        "production", "ok",
        f"护栏带判定={gb.get('decision')}，AL_upper={gb.get('al_upper')}"
        f" AL_lower={gb.get('al_lower')}{note}",
        {**gb, "unit": str(section.get("unit", "dB")), "chained_u95": chained})


def uncertainty_ledger(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """全链不确定度账本：材料 u95 → 仿真 u_num → 测量 u_c → 产线 U。

    payload 四段键（material / simulation / measurement / production）
    全部可选；缺段=unknown 行不阻塞（#105）。返回::

        {"ok": True,
         "stages": [{stage, status, detail, result?}...],
         "chain": {"u_material"?, "u_simulation"?, "u_measurement"?,
                   "U_production"?},
         "contributions": [跨段贡献表（段+分量+share）...],
         "cross_stage_max": {"stage", "name", "u", "share"} | null,
         "unit_note": str}

    单位纪律（#121）：cross_stage_max 只在全部已判段 unit 一致时给出，
    否则 null+unit_note 说明（不跨单位混算）。
    """
    payload = dict(payload or {})
    m_row = _run_material(payload.get("material"))
    s_row = _run_simulation(payload.get("simulation"))
    meas_row = _run_measurement(payload.get("measurement"))
    meas_u95 = None
    if meas_row["status"] == "ok":
        meas_u95 = meas_row["result"].get("U")
    p_row = _run_production(payload.get("production"), meas_u95)
    stages = [m_row, s_row, meas_row, p_row]

    chain: dict[str, float] = {}
    contributions: list[dict[str, Any]] = []
    units: set[str] = set()
    for row, key in ((m_row, "u_material"), (s_row, "u_simulation"),
                     (meas_row, "u_measurement"), (p_row, "U_production")):
        res = row.get("result") or {}
        if row["status"] == "ok" and res.get("u_std") is not None:
            chain[key] = float(res["u_std"])
        for c in res.get("contributions") or []:
            contributions.append({"stage": row["stage"], **c})
            if res.get("unit"):
                units.add(str(res["unit"]))
    cross_max: dict[str, Any] | None = None
    judged = [c for c in contributions
              if c.get("u") is not None and c.get("name") is not None]
    if judged and len(units) == 1:
        best = max(judged, key=lambda c: float(c["u"]))
        total = sum(float(c["u"]) for c in judged)
        cross_max = {**best,
                     "share": (float(best["u"]) / total) if total > 0 else None}
    unit_note = ("全部已判段单位一致（" + sorted(units)[0] + "）"
                 if len(units) == 1 and units else
                 "各段单位不一或未声明——跨段最大分量指针不给（#121 单位纪律）")
    return ok_envelope(stages=stages, chain=chain,
                       contributions=contributions, cross_stage_max=cross_max,
                       unit_note=unit_note)


def render_uncertainty_chain_csv(ledger: dict[str, Any]) -> str:
    """账本 → u_chain.csv 文本（stage,status,u_std,unit,name,share；\\n 行尾）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["stage", "status", "u_std", "unit", "component",
                     "u_component", "share"])
    for row in ledger.get("stages", []):
        res = row.get("result") or {}
        u_std = res.get("u_std")
        unit = res.get("unit", "")
        contribs = res.get("contributions") or []
        if not contribs:
            writer.writerow([row.get("stage"), row.get("status"),
                             "" if u_std is None else u_std, unit, "", "", ""])
        for c in contribs:
            writer.writerow([row.get("stage"), row.get("status"),
                             "" if u_std is None else u_std, unit,
                             c.get("name", ""),
                             "" if c.get("u") is None else c["u"],
                             "" if c.get("share") is None else c["share"]])
    return buf.getvalue()


def write_uncertainty_chain_csv(ledger: dict[str, Any], path: str | Path) -> Path:
    """账本 u_chain.csv 落盘（父目录须已存在；返回写入路径）。"""
    p = Path(path)
    p.write_text(render_uncertainty_chain_csv(ledger), encoding="utf-8")
    return p
