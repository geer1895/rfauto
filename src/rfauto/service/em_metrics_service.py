"""em metrics 服务面（aurora_k K16 席，2026-10-23；反馈 P14/P6）。

三面（全部薄装配零数值面——数值只在 core 确定性内核，铁律 7）：

- ``collect_run_metrics``：run 目录双路读数合并（主口径=``results/
  metrics.json`` 的 metrics；补充口径=Touchstone 经 K8
  ``core.deembed.z12_series_metrics`` 现场提取——C/R/Q/SRF 家族键）+
  meta.json 网格参数摘取（键名含 "mesh" 者，收敛对比的档位证据）；
- ``em_metrics_from_run``：``rfauto em metrics --run`` 的信封出口——
  采集 + ``core.metric_groups.bind_metric_group`` 同族绑定（series 族
  Q 在场时附"Q 随 C 变，不是纯损耗"提示；shunt 族不提示）；
- ``convergence_check``：P6 两档网格收敛门——同模型两档网格的提取指标
  相对偏差 >``rel_tol``（缺省 0.10）→ ``verdict="not_converged"``。
  输入形态兼容：两个 run 目录（各跑过不同网格档，meta 网格参数作档位
  证据回带）或直接两组指标映射。

复用清单（防重复建设）：指标提取单源=K8 core.deembed 纯函数面（本模块
``extract_touchstone_metrics`` 是 em_sweep_service 同名私有函数的单源
收编，sweep 侧薄委托回这里）；绑定族表=core.metric_groups（K16 件一）；
run 根语义不在此层（调用方传目录，测试 chdir tmp 隔离，#144）。

刻意不带 ``__all__``（metric_glossary_service 同例：check_public_api
金快照不翻面）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# ─── Touchstone 提取的扁平字段白名单（与 K10 sweep 汇总列对齐） ───────────────

#: series 口径取进扁平读数的字段（K8 series 块；None 如实透传）。
_SERIES_FIELDS = ("r_series_ohm", "x_series_ohm", "c_series_f", "l_series_h",
                  "q_series", "s21_db")
#: shunt 口径同上（K8 shunt 块）。
_SHUNT_FIELDS = ("g_shunt_s", "b_shunt_s", "c_shunt_f", "l_shunt_h", "q_shunt")

# ─── 收敛判定的 metric 别名表（→ 候选键优先序；大小写不敏感兜底） ────────────

#: 别名 → 候选键。"em." 前缀=em_sweep summary 行的 K8 现场提取键形态。
_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "Q": ("q_series", "em.q_series", "q_shunt", "em.q_shunt", "q", "q_factor"),
    "SRF": ("srf_hz", "em.srf_hz", "srf"),
    "C": ("c_series_f", "em.c_series_f", "c_shunt_f", "em.c_shunt_f", "c"),
    "R": ("r_series_ohm", "em.r_series_ohm", "r_series"),
}

#: sweep 汇总对比的 metric 回退链（Q 主口径；缺数据逐级退到 SRF/C）。
CONVERGENCE_METRIC_FALLBACK = ("Q", "SRF", "C")


def _is_number(value: Any) -> bool:
    """可用作偏差计算的有限数值（bool 是 int 子类须排除；NaN/inf 非读数）。"""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _resolve_metric(metrics: Mapping[str, Any], metric: str) -> tuple[str | None, Any]:
    """别名/字面键 → (落位键, 数值)。别名表命中走候选序；否则按字面键
    查（如 "L_nh"/"s21_db"）。候选序+全映射大小写不敏感兜底；落位值须
    有限数值（字符串读数不当数值消费，如实记缺失）。"""
    wanted = str(metric).strip()
    candidates = _METRIC_ALIASES.get(wanted.upper())
    if candidates is None:
        candidates = (wanted,)
    for key in candidates:
        value = metrics.get(key)
        if _is_number(value):
            return key, value
    lowered = {str(k).strip().lower(): (k, v) for k, v in metrics.items()}
    for key in candidates:
        hit = lowered.get(key.lower())
        if hit and _is_number(hit[1]):
            return hit
    return None, None


# ─── run 目录指标采集（metrics.json + Touchstone 双路，best-effort #105） ────


def extract_touchstone_metrics(
    run_dir: str | Path, *, f_hz: float | None = None,
) -> tuple[dict[str, Any], str | None]:
    """run 目录 Touchstone → K8 现场提取扁平指标（best-effort）。

    返回 (扁平指标 dict 或空, 失败原因或 None)。2 端口=series 口径、
    1 端口=shunt 口径（K8 守卫白名单）；其余端口数/解析失败如实报原因。
    ``f_hz``（Hz）缺省 None=带内几何中心（K8 口径）；em_sweep_service
    的同名私有函数已收编为本单源（sweep 侧薄委托）。
    """
    run_dir = Path(run_dir)
    try:
        import skrf
    except ImportError:
        return {}, "skrf 不可用"
    s_files = sorted(run_dir.glob("results/params.s*p"))
    if not s_files:
        return {}, "无 Touchstone 产物（results/params.s*p）"
    try:
        net = skrf.Network(str(s_files[0]))
    except Exception as exc:
        return {}, f"Touchstone 解析失败: {exc}"
    from rfauto.core.deembed import z12_series_metrics

    topology = "series" if net.nports == 2 else (
        "shunt" if net.nports == 1 else None)
    if topology is None:
        return {}, f"{net.nports} 端口不在 K8 提取面（series=2 端口/shunt=1 端口）"
    try:
        raw = z12_series_metrics(
            net, f_hz=f_hz, topology=topology)
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        return {}, f"指标提取失败（topology={topology}）: {exc}"
    flat: dict[str, Any] = {}
    block = raw.get("series") if topology == "series" else raw.get("shunt")
    fields = _SERIES_FIELDS if topology == "series" else _SHUNT_FIELDS
    if isinstance(block, Mapping):
        for key in fields:
            flat[key] = block.get(key)
    flat["srf_hz"] = raw.get("srf_hz")
    flat["f_eval_hz"] = raw.get("f_eval_hz")
    return flat, None


def _mesh_params_from_meta(run_dir: Path) -> dict[str, Any]:
    """meta.json params 中键名含 "mesh"（大小写不敏感）者 → 档位证据。"""
    meta_path = run_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(meta, dict):
        return {}
    params = meta.get("params")
    if not isinstance(params, Mapping):
        return {}
    return {str(k): v for k, v in params.items() if "mesh" in str(k).lower()}


def collect_run_metrics(run_dir: str | Path, *, f_eval_ghz: float | None = None,
                        ) -> dict[str, Any]:
    """run 目录 → 合并指标 + 来源账 + 网格档位证据（不抛异常，#105）。

    Returns:
        dict：``metrics``（合并读数；metrics.json 的 objectives 读数为主
        口径，Touchstone K8 家族键用 ``setdefault`` 补缺不顶替）/
        ``sources``（metrics_json/touchstone 路径或 None）/ ``mesh``
        （meta 网格参数，可能空）/ ``errors``（逐路失败原因，可能空）。
    """
    run_dir = Path(run_dir)
    metrics: dict[str, Any] = {}
    sources: dict[str, str | None] = {"metrics_json": None, "touchstone": None}
    errors: list[str] = []
    metrics_path = run_dir / "results" / "metrics.json"
    if metrics_path.is_file():
        try:
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
            inner = data.get("metrics") if isinstance(data, dict) else None
            if isinstance(inner, Mapping):
                metrics.update({str(k): v for k, v in inner.items()})
                sources["metrics_json"] = str(metrics_path)
            else:
                errors.append("results/metrics.json 无 metrics 映射")
        except (OSError, ValueError) as exc:
            errors.append(f"results/metrics.json 不可读: {exc}")
    f_hz = None if f_eval_ghz is None else float(f_eval_ghz) * 1e9
    flat, why = extract_touchstone_metrics(run_dir, f_hz=f_hz)
    if why:
        errors.append(f"Touchstone 补充提取: {why}")
    else:
        sources["touchstone"] = str(sorted(run_dir.glob("results/params.s*p"))[0])
        for key, value in flat.items():
            metrics.setdefault(key, value)
    return {
        "metrics": metrics,
        "sources": sources,
        "mesh": _mesh_params_from_meta(run_dir),
        "errors": errors,
    }


# ─── 件一：em metrics --run 信封出口（采集+同族绑定） ────────────────────────


def em_metrics_from_run(
    run_dir: str | Path, *, f_eval_ghz: float | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    """``rfauto em metrics --run`` 的服务出口（规则 4：JSON 进出信封）。

    run 目录采集（metrics.json 主口径 + Touchstone K8 家族键补充）→
    ``core.metric_groups.bind_metric_group`` 同族绑定。族判不出（无任何
    族候选键）→ ``binding`` group=None + errors 如实（不猜族）。双路
    全空 → error 信封。
    """
    run_dir_p = Path(run_dir)
    if not run_dir_p.is_dir():
        return error_envelope(
            f"run 目录不存在: {run_dir_p}（传入 run 目录路径，或先跑一次 "
            "仿真生成）")
    collected = collect_run_metrics(run_dir_p, f_eval_ghz=f_eval_ghz)
    metrics = collected["metrics"]
    errors = list(collected["errors"])
    if not metrics:
        return error_envelope(
            [*errors, "run 目录无可读指标（无 metrics.json 且 Touchstone "
                      "提取失败）"],
            run_dir=str(run_dir_p), sources=collected["sources"])
    from rfauto.core.metric_groups import bind_metric_group

    binding = bind_metric_group(metrics, group=group)
    if binding["group"] is None:
        errors.append("指标不在任何绑定族（无 K8 家族键——绑定面不适用，"
                      "按原始读数输出）")
    notes: list[str] = []
    if binding.get("advisory"):
        notes.append(binding["advisory"])
    if binding.get("missing"):
        notes.append(
            f"同族缺数据键（如实标 missing）: {', '.join(binding['missing'])}")
    return ok_envelope(
        run_dir=str(run_dir_p),
        command="em metrics",
        metrics=metrics,
        binding=binding,
        sources=collected["sources"],
        mesh=collected["mesh"],
        errors=errors,
        notes=notes,
    )


# ─── 件二：P6 两档网格收敛门（not_converged 判定） ───────────────────────────


def _side_from_input(
    name: str, source: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """收敛判定单侧输入归一：run 目录（str/Path）→ 采集映射；映射 → 原样。

    Returns:
        (metrics 映射或 None, 侧账（source/mesh/path）或 None, 错误或 None)。
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_dir():
            return None, None, f"{name} 不是存在的 run 目录: {path}"
        collected = collect_run_metrics(path)
        side = {"source": "run_dir", "path": str(path),
                "mesh": collected["mesh"]}
        if not collected["metrics"]:
            return None, side, (
                f"{name}（{path}）无可读指标："
                + ("；".join(collected["errors"]) or "双路全空"))
        return collected["metrics"], side, None
    if isinstance(source, Mapping):
        return dict(source), {"source": "mapping"}, None
    return None, None, (
        f"{name} 输入形态不支持（run 目录路径或指标映射）: {source!r}")


def convergence_check(
    m1: Any, m2: Any, *, metric: str = "Q", rel_tol: float = 0.10,
) -> dict[str, Any]:
    """两档网格指标收敛判定（P6：默认网格能解 ≠ 数值可用）。

    Args:
        m1/m2: 两个 run 目录（str/Path——各自跑过不同网格档，meta 的
            mesh 参数作档位证据回带）或两组指标映射（如 em sweep summary
            行、扁平 K8 提取结果）。
        metric: 判定指标别名（"Q"/"SRF"/"C"/"R"，大小写不敏感）或直接
            键名（如 "L_nh"、"s21_db"）。
        rel_tol: 相对偏差容限（缺省 0.10=P6 的 10%）。**边界含等号**：
            偏差恰等于容限判 converged（>rel_tol 才违约——#376 家法，
            边界语义显式钉测试）。

    Returns:
        ok 信封：``verdict`` ∈ {"converged", "not_converged",
        "insufficient_data"}；``rel_dev`` = |v1−v2| / max(|v1|,|v2|)
        （对称分母——两档网格无"参考档"方向假设；双零读数 dev=0）；
        ``values`` 两侧落位键+数值+档位证据；``mesh_distinct``（两侧
        meta 网格参数是否不同：True/False/None=无网格参数可比）。

    语义红线（#122）：任一侧判不出指标 → verdict=``insufficient_data``
    如实（不猜、不拿别的键冒充）；两侧网格参数相同 → 仍出数值判定但
    notes 显式提示"不是网格收敛对"。
    """
    try:
        tol = float(rel_tol)
    except (TypeError, ValueError):
        return error_envelope(f"rel_tol 必须是数字，实际 {rel_tol!r}")
    if not math.isfinite(tol) or tol <= 0:
        return error_envelope(f"rel_tol 必须是正的有限数，实际 {rel_tol!r}")
    metrics1, side1, err1 = _side_from_input("m1", m1)
    metrics2, side2, err2 = _side_from_input("m2", m2)
    if err1 or err2:
        return error_envelope(
            [e for e in (err1, err2) if e],
            metric=str(metric), verdict="insufficient_data")
    key1, v1 = _resolve_metric(metrics1 or {}, str(metric))
    key2, v2 = _resolve_metric(metrics2 or {}, str(metric))
    values = {
        "m1": {**side1, "key": key1, "value": v1},
        "m2": {**side2, "key": key2, "value": v2},
    }
    if v1 is None or v2 is None:
        missing = [name for name, v in (("m1", v1), ("m2", v2)) if v is None]
        return ok_envelope(
            metric=str(metric), rel_tol=tol, rel_dev=None, converged=None,
            verdict="insufficient_data", values=values, mesh_distinct=None,
            notes=[f"{', '.join(missing)} 侧判不出指标 {metric!r}"
                   "（别名/字面键均无有限数值读数）——缺数据如实，不判收敛"])
    f1, f2 = float(v1), float(v2)
    denom = max(abs(f1), abs(f2))
    rel_dev = 0.0 if denom == 0 else abs(f1 - f2) / denom
    converged = rel_dev <= tol
    mesh1 = (side1 or {}).get("mesh") or {}
    mesh2 = (side2 or {}).get("mesh") or {}
    mesh_distinct: bool | None
    notes: list[str] = []
    if not mesh1 and not mesh2:
        mesh_distinct = None
    elif mesh1 == mesh2:
        mesh_distinct = False
        notes.append("两侧 meta 网格参数相同——不是网格收敛对，数值判定仅供参考")
    else:
        mesh_distinct = True
    if key1 != key2:
        notes.append(f"两侧落位键不同（{key1} vs {key2}）——别名兜底命中了"
                     "不同键，判读前核对提取方法")
    verdict = "converged" if converged else "not_converged"
    if not converged:
        notes.append(
            f"两档网格 {metric} 相对偏差 {rel_dev:.1%} > {tol:.0%}——"
            "默认网格能解≠数值可用：加密网格后重跑再采信该指标")
    return ok_envelope(
        metric=str(metric), rel_tol=tol,
        rel_dev=rel_dev, converged=converged, verdict=verdict,
        values=values, mesh_distinct=mesh_distinct, notes=notes)
