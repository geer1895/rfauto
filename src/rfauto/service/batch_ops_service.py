"""批量操作服务面（SN-7/SN-8，W6-A 席位 2026-10-06）。

SN-7 N-way runs compare（service 层早已收 list，壳层此前砍到 2——本模块
把 N 语义补回 service/CLI 面）；SN-8 批量 validate/report（validate/report
单对象语义的批量入口，simci 是回归 diff 语义不同用途，并存不混）。

规则 4：JSON 进出；铁律 7：数值只由既有内核产出（compare 数字来自
``api.get_metrics``，本模块零新数值语义）。新函数全公开名（无 __all__，
public_api 快照口径记私有——纯增量零漂移）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

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

    index_dir = Path(out_dir) if out_dir is not None else Path("runs") / "report_batch"
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
    """
    root = Path(runs_dir)
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
