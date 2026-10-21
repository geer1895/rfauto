"""批量操作服务面（SN-7/SN-8，W6-A 席位 2026-10-06）。

SN-7 N-way runs compare（service 层早已收 list，壳层此前砍到 2——本模块
把 N 语义补回 service/CLI 面）；SN-8 批量 validate/report（validate/report
单对象语义的批量入口，simci 是回归 diff 语义不同用途，并存不混）。

规则 4：JSON 进出；铁律 7：数值只由既有内核产出（compare 数字来自
``api.get_metrics``，本模块零新数值语义）。新函数全公开名（无 __all__，
public_api 快照口径记私有——纯增量零漂移）。

W12-S4（2026-10-19）：compare_runs_batch_md 对账表 Markdown 渲染面
（verdict_summary_service.md 同管道范式：提取层单源+确定性渲染层，
CLI ``runs compare-batch --format md`` 消费）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope


def _resolve_runs_dir(rel: str | Path) -> Path:
    """runs 面路径双根收敛薄口（ge9 审查 P2-3，F-6 家族同域单源）。

    转发 infra/runs_paths.resolve_runs_dir（cwd 根优先/仓内子目录 chdir
    收敛回仓库 runs/；绝对入参原样透传）。惰性导入：infra 面在 service
    之下，保持本模块 import 面最小（模块内既有局部导入惯例同）。
    """
    from rfauto.infra.runs_paths import resolve_runs_dir

    return resolve_runs_dir(rel)

# ---------------------------------------------------------------------------
# SN-7：N-way runs compare（delta 矩阵 N×N + 逐键并集统计）
# ---------------------------------------------------------------------------

def compare_runs_nway(run_ids: list[str]) -> dict[str, Any]:
    """N 次 run 的指标对比矩阵（SN-7）。

    - ``pairwise``：N×N 上三角，每对复用单对比 delta 语义（数值键 b−a，
      非数值键 delta=None，不臆测方向）；
    - ``per_metric``：指标并集逐键 {run_id: value} 行表（供 CLI 渲染矩阵）；
    - ``runs``：逐 run 摘要（run_id/cost/metrics）。

    N<2 或任一 run 无指标 → ok=False 如实报错（与 compare_runs 同口径）。
    数值全部来自 ``get_metrics``（既有内核），本函数只做表格重排。
    """
    ids = [str(r).strip() for r in (run_ids or []) if str(r).strip()]
    if len(ids) < 2:
        return error_envelope(
            [f"N-way 对比至少需要 2 个 run_id，收到 {len(ids)}"])
    if len(set(ids)) != len(ids):
        return error_envelope([f"run_id 重复: {ids}"])

    from rfauto.service.api import get_metrics

    runs: list[dict[str, Any]] = []
    errs: list[str] = []
    for rid in ids:
        r = get_metrics(rid)
        if not r.get("ok"):
            errs.append(f"run {rid} 无指标")
            continue
        data = r.get("data") or {}
        runs.append({
            "run_id": rid,
            "cost": data.get("cost"),
            "metrics": dict(data.get("metrics") or {}),
        })
    if errs:
        return error_envelope(errs)

    pairwise: list[dict[str, Any]] = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            ma, mb = runs[i]["metrics"], runs[j]["metrics"]
            delta: dict[str, Any] = {}
            for k in sorted(set(ma) | set(mb), key=str):
                va, vb = ma.get(k), mb.get(k)
                d = None
                if (isinstance(va, (int, float)) and isinstance(vb, (int, float))
                        and not isinstance(va, bool) and not isinstance(vb, bool)):
                    d = vb - va
                delta[k] = {"a": va, "b": vb, "delta": d}
            pairwise.append({
                "a": runs[i]["run_id"], "b": runs[j]["run_id"],
                "delta": delta,
            })

    keys = sorted({k for r in runs for k in r["metrics"]}, key=str)
    per_metric: list[dict[str, Any]] = []
    for k in keys:
        row: dict[str, Any] = {"metric": k}
        numeric: list[float] = []
        for r in runs:
            v = r["metrics"].get(k)
            row[r["run_id"]] = v
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric.append(float(v))
        if numeric:
            row["spread"] = max(numeric) - min(numeric)
        else:
            row["spread"] = None
        per_metric.append(row)

    return ok_envelope(
        n_runs=len(runs),
        runs=[{"run_id": r["run_id"], "cost": r["cost"]} for r in runs],
        pairwise=pairwise,
        per_metric=per_metric,
    )


# ---------------------------------------------------------------------------
# SN-8：批量 validate / report
# ---------------------------------------------------------------------------

def _collect_yaml_files(target: str | Path) -> tuple[list[Path] | None, str | None]:
    """批量目标解析：目录 → 内（含子目录）全部 *.yaml/*.yml；单文件 → [它]。

    Returns:
        (文件列表, None) 或 (None, 错误消息)。
    """
    p = Path(target)
    if p.is_dir():
        files = sorted(
            q for q in list(p.glob("*.yaml")) + list(p.glob("*.yml"))
            if q.is_file())
        if not files:
            return None, f"目录下无 YAML 配方: {p}"
        return files, None
    if p.is_file():
        return [p], None
    return None, f"目标不存在: {p}"


def validate_recipes_batch(target: str | Path) -> dict[str, Any]:
    """批量配方校验（SN-8）：目录或单文件 → 逐文件 validate_recipe 聚合。

    单文件失败不传染（逐文件 errors 留账）；汇总 ``passed``/``failed``
    名单，任一失败 → ok=False（退出码门禁语义由 CLI 层决定）。
    """
    from rfauto.service.api import validate_recipe

    files, err = _collect_yaml_files(target)
    if err:
        return error_envelope([err])
    results: list[dict[str, Any]] = []
    passed: list[str] = []
    failed: list[str] = []
    for f in files or []:
        r = validate_recipe(str(f))
        entry = {
            "recipe": str(f),
            "ok": bool(r.get("ok")),
            "errors": list(r.get("errors") or []),
            "warnings": list(r.get("warnings") or []),
        }
        results.append(entry)
        if entry["ok"]:
            passed.append(str(f))
        else:
            failed.append(str(f))
    return ok_envelope(
        target=str(target),
        n_files=len(results),
        passed=passed,
        failed=failed,
        results=results,
        ok_all=not failed,
    )


def report_runs_batch(
    run_ids: list[str],
    *,
    fmt: str = "markdown",
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """批量 run 报告（SN-8）：逐 run generate_report_for_run + 汇总索引页。

    - 单 run 失败不传染（逐 run errors 留账，#105）；
    - 汇总索引 ``index.md``（``out_dir`` 缺省 ``runs/report_batch/``）逐行
      run_id/状态/报告路径/主要指标（cost），确定性渲染零 LLM；
    - 报告本体仍按 generate_report_for_run 既有口径落各自 run 目录（或
      --output 指定面——批量入口只收目录，不逐 run 改名）。
    """
    from rfauto.service.api import generate_report_for_run

    ids = [str(r).strip() for r in (run_ids or []) if str(r).strip()]
    if not ids:
        return error_envelope(["未给定 run_id（批量 report 至少 1 个）"])

    index_dir = Path(out_dir) if out_dir is not None \
        else _resolve_runs_dir("runs") / "report_batch"
    index_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for rid in ids:
        r = generate_report_for_run(rid, fmt=fmt)
        if not r.get("ok"):
            failed.append({"run_id": rid,
                           "errors": [str(e) for e in r.get("errors") or ["失败"]]})
            continue
        entries.append({
            "run_id": rid,
            "ok": True,
            "report": str(r.get("report") or ""),
            "cost": r.get("metrics", {}).get("cost"),
            "metrics": dict(r.get("metrics") or {}),
        })

    lines = ["# 批量报告索引", "",
             f"- runs: {len(entries)} ok / {len(failed)} failed",
             f"- fmt: {fmt}", "",
             "| run_id | cost | 报告 |", "|---|---|---|"]
    for e in entries:
        cost = e.get("cost")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "-"
        lines.append(f"| {e['run_id']} | {cost_s} | {e['report']} |")
    for f in failed:
        lines.append(f"| {f['run_id']} | FAILED | {'; '.join(f['errors'])[:80]} |")
    index_path = index_dir / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return ok_envelope(
        n_runs=len(ids),
        n_ok=len(entries),
        n_failed=len(failed),
        reports=[e["report"] for e in entries],
        failed=failed,
        index=str(index_path),
    )


def discover_run_ids(
    runs_dir: str | Path = "runs",
    *,
    limit: int = 200,
    status: str | None = None,
) -> dict[str, Any]:
    """runs 目录 → 有 ``results/metrics.json`` 的 run_id 清单（批量入口枚举面）。

    供 ``report --dir`` / 批量 report 的"不给清单"形态使用：按 mtime 倒序
    取最近 ``limit`` 个；``status`` 过滤 meta.json 的 status 键（可空=不过滤）。

    ge9 审查 P2-3：缺省 ``runs`` 走 infra/runs_paths 双根收敛（cwd 根优先
    /仓内子目录 chdir 收敛回仓库 runs/，#295 族；与 agent_safety/
    campaign_dashboard 等五处收敛先例同源）——绝对路径入参原样透传。
    """
    root = _resolve_runs_dir(runs_dir)
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"])
    items: list[tuple[float, str, str]] = []
    for p in root.iterdir():
        if not (p / "results" / "metrics.json").is_file():
            continue
        st = ""
        meta_p = p / "meta.json"
        if meta_p.is_file():
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    st = str(meta.get("status") or "")
            except (OSError, ValueError):
                st = ""
        items.append((p.stat().st_mtime, p.name, st))
    items.sort(reverse=True)
    if status:
        items = [it for it in items if it[2] == str(status)]
    ids = [name for _mt, name, _st in items[: max(1, int(limit))]]
    return ok_envelope(run_ids=ids, n_runs=len(ids), runs_root=str(root))


# ---------------------------------------------------------------------------
# W8-S4（架构批 2026-10-19）：战役收官多 run 对账（compare_runs_nway 的
# 收官姊妹面——nway 面向指标矩阵且任一 run 无指标即整门 FAIL；本面面向
# 对账：status/耗时/verdict 判定逐 run 并排，缺产物降级 unknown 不传染，
# 指标偏差只对有数 run 计算并给 top-K。语义不同，并存不混。）
# ---------------------------------------------------------------------------

#: meta.wall_s 缺席时 verdict 侧耗时键（按序取首个数值）
_DURATION_KEYS = ("wall_s", "duration_s", "elapsed_s", "solve_s", "engine_wall_s")

#: 偏差排行上限（任务书口径 top-5；可调只收窄）
_MAX_TOP_K = 5

#: 零除保护下的相对偏差下限（全零指标列相对偏差不定义→None 不臆测）
_EPS = 1e-300


def _read_json_file(path: Path) -> dict[str, Any] | None:
    """JSON 文件 → dict；缺失/坏 JSON/非对象一律 None（对账面不炸）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _resolve_run_dir(rid: str) -> Path | None:
    """run 目录定位：runs 根下相对子路径（``<run_id>`` 或
    ``<战役>/<run>``——verdict 档案目录的主形态）。

    穿越段（``..``）/绝对路径拒绝（只读对账面防逃逸）；不存在返回
    None（调用方先查形态合法性再判存在，两种 errors 文案分开）。
    """
    p = Path(rid)
    parts = p.parts
    if p.is_absolute() or not parts \
            or any(seg in ("", ".", "..") for seg in parts):
        return None
    cand = _resolve_runs_dir("runs").joinpath(*parts)
    return cand if cand.is_dir() else None


def _illegal_run_id(rid: str) -> bool:
    """形态非法（绝对路径/穿越段）判别——与"不存在"分开记账。"""
    p = Path(rid)
    parts = p.parts
    return p.is_absolute() or not parts \
        or any(seg in ("", ".", "..") for seg in parts)


def compare_runs_batch(run_ids: list[str], *, top_k: int = _MAX_TOP_K) -> dict[str, Any]:
    """多 run 并排对账表（战役收官快速对账工具，W8-S4）。

    与 compare_runs_nway 的分工：nway 是"指标矩阵"（任一 run 无指标整门
    报错）；本面是"对账表"——逐 run 汇总判定（verdict.json status 优先，
    回落 meta.json status）+ 耗时（meta.wall_s，回落 verdict 耗时键）+
    cost + 指标数，缺产物降级 ``missing`` 行不传染；跨 run 数值指标并集
    逐键算极差（spread）与相对极差（rel_spread=spread/max|值|，全零列
    如实 None），按相对极差降序（键名升序消并列）取 top_k（缺省 5）。

    数值全部来自 meta.json / verdict.json / results/metrics.json 原文
    透传（铁律 7）；本函数只做并排与排序。run_id 非法（绝对路径/穿越
    段）或不存在 → 该行 missing 记 errors，不中断整批。
    """
    ids = [str(r).strip() for r in (run_ids or []) if str(r).strip()]
    if not ids:
        return error_envelope(["未给定 run_id（批量对账至少 1 个）"])
    if len(set(ids)) != len(ids):
        return error_envelope([f"run_id 重复: {ids}"])
    try:
        k = int(top_k)
    except (TypeError, ValueError):
        return error_envelope([f"top_k 必须是整数，收到 {top_k!r}"])
    if k < 1:
        return error_envelope([f"top_k 必须 >= 1，收到 {top_k!r}"])
    k = min(k, _MAX_TOP_K)

    rows: list[dict[str, Any]] = []
    errs: list[str] = []
    metrics_by_run: dict[str, dict[str, Any]] = {}

    for rid in ids:
        if _illegal_run_id(rid):
            errs.append(f"非法 run_id: {rid!r}")
            rows.append({"run_id": rid, "status": "missing",
                         "model": None, "adapter": None, "duration_s": None,
                         "cost": None, "n_metrics": 0, "has_verdict": False})
            continue
        run_dir = _resolve_run_dir(rid)
        if run_dir is None:
            errs.append(f"run 不存在: {rid}")
            rows.append({"run_id": rid, "status": "missing",
                         "model": None, "adapter": None, "duration_s": None,
                         "cost": None, "n_metrics": 0, "has_verdict": False})
            continue

        meta = _read_json_file(run_dir / "meta.json") or {}
        verdict = _read_json_file(run_dir / "verdict.json") or {}

        # 指标：meta 内嵌优先、results/metrics.json 回落（runs_diff 同口径）
        metrics = meta.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            metrics = _read_json_file(run_dir / "results" / "metrics.json") or {}
        numeric_metrics = {
            key: v for key, v in metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if numeric_metrics:
            metrics_by_run[rid] = numeric_metrics

        # 判定：verdict 总判定键原文优先，回落 meta.status（两形态并存时
        # 双列——verdict_status 是战役档案判定，meta_status 是 run 链状态）
        verdict_status = ""
        for key in ("status", "verdict", "result"):
            v = verdict.get(key)
            if isinstance(v, str) and v.strip():
                verdict_status = v.strip()
                break
        meta_status = str(meta.get("status") or "") or None

        # 耗时：meta.wall_s 优先，verdict 耗时键按序回落
        duration: float | None = None
        for key in _DURATION_KEYS:
            for src in (meta, verdict):
                v = src.get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    duration = float(v)
                    break
            if duration is not None:
                break

        cost = numeric_metrics.get("cost")
        rows.append({
            "run_id": rid,
            "status": verdict_status or meta_status or "unknown",
            "verdict_status": verdict_status or None,
            "meta_status": meta_status,
            "model": meta.get("model") or verdict.get("template"),
            "adapter": meta.get("adapter"),
            "duration_s": duration,
            "cost": cost,
            "n_metrics": len(numeric_metrics),
            "has_verdict": bool(verdict),
        })

    # 跨 run 指标偏差 top-K（数值并集；<2 个 run 有指标时如实空表+note）
    keys = sorted({key for m in metrics_by_run.values() for key in m}, key=str)
    devs: list[dict[str, Any]] = []
    notes: list[str] = []
    for key in keys:
        present = {rid: m[key] for rid, m in metrics_by_run.items()
                   if isinstance(m.get(key), (int, float))}
        if len(present) < 2:
            continue
        vals = list(present.values())
        spread = max(vals) - min(vals)
        max_abs = max(abs(v) for v in vals)
        rel = spread / max_abs if max_abs > _EPS else None
        devs.append({"metric": key, "values": present, "spread": spread,
                     "rel_spread": rel})
    devs.sort(key=lambda d: (d["rel_spread"] is None,
                             -(d["rel_spread"] or 0.0), d["metric"]))
    if len(metrics_by_run) < 2:
        notes.append(f"仅 {len(metrics_by_run)} 个 run 有数值指标——"
                     "偏差表需要 ≥2（missing/纯 verdict 档案 run 不参与）")
    truncated = len(devs) > k

    return ok_envelope(
        n_runs=len(ids),
        runs=rows,
        deviations=devs[:k],
        n_deviations=len(devs),
        deviations_truncated=truncated,
        top_k=k,
        errors=errs,
        notes=notes,
    )


def _md_val(v: Any) -> str:
    """对账表 Markdown 值格式：浮点 ``.6g``（显示层，不改值），其余 str
    直转；管道符转义（Markdown 表格安全）——verdict_summary_service.
    _fmt_val 同范式。"""
    s = f"{v:.6g}" if isinstance(v, float) else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def compare_runs_batch_md(run_ids: list[str], *,
                          top_k: int = _MAX_TOP_K) -> str:
    """多 run 对账表 → 结构化 Markdown（W12-S4，verdict_summary_md 同管道
    范式：提取层=compare_runs_batch 单源，本函数只做确定性渲染——零 LLM、
    零时间戳，同输入逐字节同输出；铁律 7 数值全部来自对账信封原文）。

    入参校验失败（空清单/重复/非法 top_k）返回以 ``批量对账不可用`` 起头
    的单行说明（渲染层不抛，供人读面直嵌；需要错误语义的调用方走
    compare_runs_batch 信封）。
    """
    r = compare_runs_batch(run_ids, top_k=top_k)
    if not r.get("ok"):
        return ("批量对账不可用\n\n"
                + "\n".join(f"- {e}" for e in r.get("errors") or []) + "\n")
    lines: list[str] = []
    lines.append(f"# run 批量对账 — {r.get('n_runs')} 个")
    lines.append("")
    lines.append("| run_id | 判定 | model | 耗时 s | cost | 指标数 | verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in r.get("runs") or []:
        dur = row.get("duration_s")
        cost = row.get("cost")
        dur_s = "-" if dur is None else f"{float(dur):.1f}"
        cost_s = "-" if cost is None else f"{float(cost):.4f}"
        verdict_s = "yes" if row.get("has_verdict") else "-"
        lines.append(
            f"| `{_md_val(row.get('run_id'))}` "
            f"| {_md_val(row.get('status'))} "
            f"| {_md_val(row.get('model') if row.get('model') is not None else '-')} "
            f"| {dur_s} | {cost_s} "
            f"| {row.get('n_metrics') or 0} | {verdict_s} |")
    lines.append("")
    devs = r.get("deviations") or []
    if devs:
        lines.append("## 跨 run 指标偏差 top（相对极差降序）")
        lines.append("")
        lines.append("| 指标 | 极差 | 相对极差 | 逐 run 值 |")
        lines.append("|---|---|---|---|")
        for d in devs:
            rel = d.get("rel_spread")
            vals = " ".join(
                f"{rid}={_md_val(v)}"
                for rid, v in sorted((d.get("values") or {}).items(),
                                     key=lambda kv: str(kv[0])))
            lines.append(
                f"| `{_md_val(d.get('metric'))}` "
                f"| {_md_val(d.get('spread'))} "
                f"| {'-' if rel is None else f'{float(rel):.4f}'} "
                f"| {_md_val(vals)} |")
        lines.append("")
        if r.get("deviations_truncated"):
            lines.append(f"> 偏差表截断：共 {r.get('n_deviations')} 项指标，"
                         f"只列前 {r.get('top_k')} 项（截断计数如实）。")
            lines.append("")
    for note in r.get("notes") or []:
        lines.append(f"- 注记: {_md_val(note)}")
    for err in r.get("errors") or []:
        lines.append(f"- 错误: {_md_val(err)}")
    if r.get("notes") or r.get("errors"):
        lines.append("")
    return "\n".join(lines)
