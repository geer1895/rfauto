"""dataset_service.workdir —— 工作目录形态真机产物导入器。

自 dataset_service.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原节「工作目录形态真机产物导入器」逐字节搬迁。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    DATASET_FORMATS,
    DATASET_SCHEMA,
    DEFAULT_FORMAT,
    DEFAULT_OUT_DIR,
    GROUND_TRUTH_POLICY,
    HDF5_NAME,
    PARQUET_NAME,
    SCHEMA_VERSION,
    _canonical_json,
    _has_nonfinite,
    _import_pyarrow,
    _save_manifest_atomic,
    _validate_dataset_name,
    is_ground_truth_adapter,
)
from .io import (
    _register_dataset_row,
    _resolve_registry_sync,
    _write_points_hdf5,
)
from .materialize import _aggregate_bounds
from .workdir_params import (
    _WORKDIR_PARAM_PATHS,
    _resolve_workdir_params,
)

# ---------------------------------------------------------------------------
# 工作目录形态真机产物导入器（审查修复队列增量③；审计 #17 "造了零件没装上车"）
# ---------------------------------------------------------------------------
#
# slotline/hairpin/Marchand/mline/helix 等真机战役把产物直接落在
# ``runs/<工作目录>/<点目录>/``（sparams.csv / *.sNp / 摘要 JSON），没有
# meta.json，也没有 results/params.sNp 与 recipe.snapshot.yaml——不在 ①—⑤
# 收集契约里，materialize_dataset 一律"缺 meta.json 跳过"，是渐进式数据工厂
# 的漏数口（数据入库批如实记录的整类缺口）。
#
# 导入单元 = 曲线产物文件（Touchstone ``*.s<N>p`` 或 openEMS 单激励
# ``sparams.csv``），每个曲线产物物化为注册表一行（schema 同 DATASET_SCHEMA；
# source/algorithm 恒为 WORKDIR_SOURCE，查询侧可按列过滤）。设计参数只从内核
# 落盘的 JSON 里按固定键路径精确取值（铁律 7：导入器不产生任何数字）：
# - 归属规则（确定性，防多曲线目录张冠李戴）：自曲线所在目录逐级上溯到工作
#   目录根，每级 JSON 按小写文件名排序；先认"显式引用"（JSON 任一字符串值以
#   该曲线相对该级目录的路径结尾，如 helix 仲裁 JSON 的 ``s1p`` 键）或"同名
#   stem"；其次仅当该目录只有一个曲线产物时才认无引用 JSON（pt1/ 形态）；
#   多曲线目录里无引用可归属 → 该点跳过并记 error（#122 如实，不猜）。
# - 键路径优先级 _WORKDIR_PARAM_PATHS：``params`` > ``calib_params``（校准实跑
#   几何；hairpin calib.json 的 design_params 是校准前设计值，排在其后）>
#   ``design_params`` > ``design_point`` > ``design`` > ``geometry`` >
#   ``geom.nominal`` > ``nominal``；只收标量值（str/int/float/bool）。params
#   含非有限值整点拦截计数（同 ①—⑤ 口径）；metrics 非有限值只剔除该键（导入
#   器的 metrics 是摘要 JSON 顶层标量全扫，一个游离 NaN 不应吞掉整点）。
# - metrics = 提供参数的那个 JSON 的顶层标量键值；cost NULL（无统一语义）。
# - provenance（契约：来源目录/时间戳/touchstone 路径/n_ports 可查）：
#   run_id（工作目录名）/source_dir（曲线所在目录，相对 runs 根 posix）/
#   run_timestamp（曲线文件 mtime，UTC ISO）/curve_path+curve_kind（相对工作
#   目录）/n_ports（Touchstone 取扩展名 N；csv 取表头 S 下标最大值，
#   int）/touchstone_path（仅 Touchstone，与 ⑤ 分支同键）/params_source+
#   params_key（参数出处，可回溯）。
# - adapter 推断（GT 标注依据 is_ground_truth_adapter）：曲线目录名为 fdtd
#   或含 fdtd/ 或 simulation.py/_rfauto_runner.py（本目录或上一级）→
#   openems；工作目录根有 .aedt 或路径含 hfss → hfss；含 comsol → comsol；
#   否则 "workdir"（不标 GT）。
# - G11 健康门（默认开，同 materialize 口径）：曲线目录只有一个曲线产物时按
#   目录跑 health_check_run（meta.json 非必需），仅 verdict=="unhealthy" 禁入；
#   多曲线目录无法逐曲线体检 → 记 "unknown" 不拦；verdict 落 manifest。
# - 全量重扫重写：每次导入是对当前在盘工作目录产物的确定性完整收集（同
#   materialize 语义），指纹去重 (model, study_name, seed, params) 使重复导入
#   幂等；新战役落盘后重跑同名即渐进增长（行数只随在盘产物增加）。

WORKDIR_FAMILIES = ("slotline", "hairpin", "marchand", "mline", "helix")
WORKDIR_SOURCE = "workdir_import"
_WORKDIR_MAX_DEPTH = 3
_WORKDIR_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "hfss_project"})
_WORKDIR_SKIP_DIR_SUFFIXES = (".aedtresults", ".pyaedt", ".aedb", ".lock")
_WORKDIR_TOUCHSTONE_RE = re.compile(r"^.+\.s(\d+)p$", re.IGNORECASE)
_WORKDIR_CSV_NAME = "sparams.csv"
_WORKDIR_CSV_COL_RE = re.compile(r"^(?:re|im)_s(\d+)$", re.IGNORECASE)


def _workdir_family(name: str) -> str:
    """工作目录名 → 器件族标签（WORKDIR_FAMILIES 顺序首个命中子串；无 → ""）。"""
    low = str(name).lower()
    for fam in WORKDIR_FAMILIES:
        if fam in low:
            return fam
    return ""


def _normalize_families(models: Any) -> tuple[str, ...] | None:
    """models 过滤参数归一：None → None（不过滤）；否则必须是 WORKDIR_FAMILIES
    子集（去空/去重/小写），越界即 ValueError（不静默吞成零候选）。"""
    if models is None:
        return None
    if isinstance(models, str):
        models = [models]
    out: list[str] = []
    for m in models:
        fam = str(m).strip().lower()
        if not fam:
            continue
        if fam not in WORKDIR_FAMILIES:
            raise ValueError(
                f"未知器件族 {m!r}（只认 {'/'.join(WORKDIR_FAMILIES)}）")
        if fam not in out:
            out.append(fam)
    return tuple(out)


def _workdir_skip_dir(path: Path) -> bool:
    """引擎内部/缓存目录不下钻（.aedtresults 等可含上万文件）。"""
    name = path.name
    if name in _WORKDIR_SKIP_DIR_NAMES:
        return True
    low = name.lower()
    return any(low.endswith(suf) for suf in _WORKDIR_SKIP_DIR_SUFFIXES)


def _sparams_csv_ports(path: Path) -> int | None:
    """openEMS sparams.csv 表头 → 端口数（re/im_S<ij> 下标各位数字最大值：
    5 列 {S11,S21} → 2、9 列 {S11,S21,S31,S23} → 3）；表头不可解析 → None。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            header = fh.readline()
    except OSError:
        return None
    n = 0
    for col in header.strip().split(","):
        m = _WORKDIR_CSV_COL_RE.match(col.strip())
        if m is None:
            continue
        for ch in m.group(1):
            n = max(n, int(ch))
    return n or None


def _scan_workdir_curves(workdir: Path) -> list[dict[str, Any]]:
    """有界递归（≤ _WORKDIR_MAX_DEPTH 层，跳过引擎内部目录）收集曲线产物，
    按相对 posix 路径小写排序（确定性）。每条 {path, rel, kind, n_ports}。

    fdtd/ 不跳过：部分 openEMS 模板把 sparams.csv 落在 fdtd/ 子目录
    （p0_cross_fidelity 实证），只挑曲线文件不碰 et/ht/port_* 场文件。
    """
    found: list[dict[str, Any]] = []

    def _visit(d: Path, depth: int) -> None:
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for p in entries:
            if p.is_dir():
                if depth < _WORKDIR_MAX_DEPTH and not _workdir_skip_dir(p):
                    _visit(p, depth + 1)
                continue
            if not p.is_file():
                continue
            rel = p.relative_to(workdir).as_posix()
            if p.name.lower() == _WORKDIR_CSV_NAME:
                found.append({"path": p, "rel": rel, "kind": "sparams_csv",
                              "n_ports": _sparams_csv_ports(p)})
                continue
            m = _WORKDIR_TOUCHSTONE_RE.match(p.name)
            if m is None:
                continue
            try:
                n_ports = int(m.group(1))
            except ValueError:
                continue
            if n_ports <= 0:
                continue
            found.append({"path": p, "rel": rel, "kind": "touchstone",
                          "n_ports": n_ports})

    _visit(workdir, 0)
    found.sort(key=lambda a: (a["rel"].lower(), a["rel"]))
    return found




def _workdir_adapter(artifact: Path, workdir: Path, has_aedt: bool) -> str:
    """曲线产物 → 求解引擎标签（确定性目录/文件名证据，无证据 → "workdir"）。"""
    d = artifact.parent
    for probe in (d, d.parent):
        if probe.name.lower() == "fdtd" or (probe / "fdtd").is_dir() \
                or (probe / "simulation.py").is_file() \
                or (probe / "_rfauto_runner.py").is_file():
            return "openems"
    text = f"{workdir.name}/{artifact.relative_to(workdir).as_posix()}".lower()
    if has_aedt or "hfss" in text:
        return "hfss"
    if "comsol" in text:
        return "comsol"
    if "openems" in text:
        return "openems"
    return "workdir"


def _mtime_iso(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _scan_workdir(workdir: Path, runs_root: Path) -> dict[str, Any]:
    """单个工作目录的内部扫描记录（含 Path 对象；公开 API 另行序列化）。"""
    curves = _scan_workdir_curves(workdir)
    try:
        has_aedt = any(p.is_file() and p.suffix.lower() == ".aedt"
                       for p in workdir.iterdir())
    except OSError:
        has_aedt = False
    per_dir: dict[Path, int] = {}
    for c in curves:
        per_dir[c["path"].parent] = per_dir.get(c["path"].parent, 0) + 1
    for c in curves:
        c["adapter"] = _workdir_adapter(c["path"], workdir, has_aedt)
        c["n_curves_in_dir"] = per_dir[c["path"].parent]
        c["source_dir"] = c["path"].parent.relative_to(runs_root).as_posix()
        c["mtime"] = _mtime_iso(c["path"])
    return {
        "run_id": workdir.name,
        "family": _workdir_family(workdir.name),
        "source_dir": workdir.relative_to(runs_root).as_posix(),
        "curves": curves,
        "has_aedt": has_aedt,
    }


def _discover_workdir_scans(
    root: Path, fams: tuple[str, ...] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    """runs 根下无 meta.json 的目录 → 扫描记录列表（按目录名排序）。

    候选 = 无 meta.json 且（命中器件族 或 有曲线产物）；fams 非 None 时只留
    族标签在集合内的目录（未分类 "" 只在 fams=None 时列出）。返回
    (scans, n_scanned, n_with_meta)。
    """
    scans: list[dict[str, Any]] = []
    n_scanned = 0
    n_with_meta = 0
    for d in sorted((p for p in root.iterdir() if p.is_dir()),
                    key=lambda p: p.name):
        n_scanned += 1
        if (d / "meta.json").exists():
            n_with_meta += 1
            continue
        fam = _workdir_family(d.name)
        if fams is not None and fam not in fams:
            continue
        scan = _scan_workdir(d, root)
        if not fam and not scan["curves"]:
            continue
        scans.append(scan)
    return scans, n_scanned, n_with_meta


def _serialize_scan(scan: dict[str, Any]) -> dict[str, Any]:
    curves = [{
        "path": c["rel"],
        "kind": c["kind"],
        "n_ports": c["n_ports"],
        "adapter": c["adapter"],
        "source_dir": c["source_dir"],
        "mtime": c["mtime"],
    } for c in scan["curves"]]
    return {
        "run_id": scan["run_id"],
        "family": scan["family"],
        "source_dir": scan["source_dir"],
        "n_curves": len(curves),
        "adapters": sorted({c["adapter"] for c in curves}),
        "curves": curves,
    }


def discover_workdir_candidates(
    runs_root: str | Path = "runs",
    *,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """发现工作目录形态真机产物（无 meta.json 的 runs 子目录）——入口可发现。

    只读、无副作用。返回 JSON 安全 dict：ok/runs_root/families（导入器认的
    器件族清单）/n_scanned/n_with_meta（已在 ①—⑤ 契约内、不列）/n_candidates/
    per_family（族 → 候选数，未分类计 "other"）/candidates（逐目录：run_id/
    family/source_dir/n_curves/adapters/curves[{path, kind, n_ports, adapter,
    source_dir, mtime}]）。models 非 None 时只列所选族；None 列全部（含
    无族标签但有曲线产物的目录，family=""）。
    """
    root = Path(runs_root)
    try:
        fams = _normalize_families(models)
    except ValueError as exc:
        return error_envelope([str(exc)])
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root.resolve()}"])
    scans, n_scanned, n_with_meta = _discover_workdir_scans(root, fams)
    candidates = [_serialize_scan(s) for s in scans]
    per_family: dict[str, int] = {}
    for c in candidates:
        key = c["family"] or "other"
        per_family[key] = per_family.get(key, 0) + 1
    return ok_envelope(
        runs_root=str(root),
        families=list(WORKDIR_FAMILIES),
        n_scanned=n_scanned,
        n_with_meta=n_with_meta,
        n_candidates=len(candidates),
        per_family=dict(sorted(per_family.items())),
        candidates=candidates,
    )


def _workdir_health_verdict(
    art: dict[str, Any], cache: dict[Path, str], errors: list[str],
) -> str:
    """曲线目录级 G11 体检（best-effort，#105）：单曲线目录才可归属，多曲线
    目录 → "unknown"；体检器故障如实降级为 "unknown" 不拦。"""
    d = art["path"].parent
    if art["n_curves_in_dir"] != 1:
        return "unknown"
    if d in cache:
        return cache[d]
    try:
        from rfauto.service.health_service import health_check_run

        hc = health_check_run(d.name, runs_dir=d.parent)
        verdict = str(hc.get("verdict") or "unknown")
    except Exception as exc:
        errors.append(f"health_gate {d}: {exc}")
        verdict = "unknown"
    cache[d] = verdict
    return verdict


def import_workdir_runs(
    run_ids: list[str] | None = None,
    *,
    name: str,
    runs_root: str | Path = "runs",
    out_dir: str | Path = DEFAULT_OUT_DIR,
    models: list[str] | None = None,
    health_gate: bool = True,
    fmt: str = DEFAULT_FORMAT,
    registry_sync: bool | None = None,
) -> dict[str, Any]:
    """把工作目录形态真机产物导入 E1 注册表数据集（行式 schema 同 DATASET_SCHEMA，
    物化布局同 materialize_dataset：``<out_dir>/<name>/points.parquet`` +
    ``dataset_manifest.yaml``，query_dataset/list_datasets 直接可查）。

    run_ids：工作目录名清单（None=所选器件族下全部候选）；models：器件族
    过滤（None=WORKDIR_FAMILIES 五族，未分类目录不导入，需显式扩展
    WORKDIR_FAMILIES 单源）；health_gate：G11 目录级健康门（默认开）。

    registry_sync（R2-D-03 ⑤，默认关）：manifest 落盘后把数据集行
    upsert 进注册表 datasets 表，解析链与 materialize_dataset 同
    （显式实参 > settings db.dataset_registry_sync > False，best-effort）。

    返回 JSON 安全 dict：ok/name/dataset_dir/format/points_file/manifest/
    n_candidates/n_curves/n_points/n_rows/n_dup/n_nonfinite_skipped/
    n_points_skipped（无可归属参数）/source_runs[{run_id, family, n_curves,
    n_points}]/skipped_runs（零行）/missing_runs/unhealthy_points/
    health_verdicts/per_family_rows/bounds/columns/ground_truth/warnings。
    """
    try:
        name = _validate_dataset_name(name)
        fams = (_normalize_families(models) if models is not None
                else WORKDIR_FAMILIES)
    except ValueError as exc:
        return error_envelope([str(exc)])
    if fmt not in DATASET_FORMATS:
        return error_envelope(
            [
            f"fmt 只允许 {'/'.join(DATASET_FORMATS)}，收到 {fmt!r}"],
        )
    try:
        pa, pq = _import_pyarrow()
    except RuntimeError as exc:
        return error_envelope([str(exc)])
    root = Path(runs_root)
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root.resolve()}"])

    scans, _n_scanned, _n_with_meta = _discover_workdir_scans(root, fams)
    missing_runs: list[str] = []
    if run_ids is not None:
        ids = sorted({str(r).strip() for r in run_ids if str(r).strip()})
        known = {s["run_id"] for s in scans}
        missing_runs = [rid for rid in ids if rid not in known]
        scans = [s for s in scans if s["run_id"] in ids]
        if not scans:
            return error_envelope(
                [
                "指定的工作目录均不可导入（不存在/有 meta.json 走 materialize/"
                f"不属所选器件族）: {missing_runs}"],
                missing_runs=missing_runs,
            )
    if not scans:
        return error_envelope(
            [
            f"{root.resolve()} 下无 {'/'.join(fams)} 族工作目录形态产物"],
        )

    created_at = datetime.now(timezone.utc).isoformat()
    collect_errors: list[str] = []
    raw_points: list[dict[str, Any]] = []
    run_infos: list[dict[str, Any]] = []
    skipped_runs: list[str] = []
    unhealthy_points: list[str] = []
    health_verdicts: dict[str, str] = {}
    n_curves_total = 0
    n_points_skipped = 0
    n_nonfinite_skipped = 0
    verdict_cache: dict[Path, str] = {}

    for scan in scans:
        rid = scan["run_id"]
        workdir = root / rid
        curves = scan["curves"]
        n_curves_total += len(curves)
        n_before = len(raw_points)
        for idx, art in enumerate(curves):
            label = f"{rid}/{art['rel']}"
            if health_gate:
                verdict = _workdir_health_verdict(art, verdict_cache, collect_errors)
                health_verdicts[art["source_dir"]] = verdict
                if verdict == "unhealthy":
                    unhealthy_points.append(label)
                    continue
            ctx = _resolve_workdir_params(
                art["path"], workdir, art["n_curves_in_dir"])
            if ctx is None:
                n_points_skipped += 1
                collect_errors.append(
                    f"{label}: 无可归属的设计参数 JSON（键路径 "
                    f"{'/'.join(_WORKDIR_PARAM_PATHS)}；多曲线目录需 JSON 显式"
                    "引用曲线文件或同名 stem），跳过")
                continue
            params, metrics, json_path, key_path = ctx
            if _has_nonfinite(params):
                n_nonfinite_skipped += 1
                collect_errors.append(
                    f"{label}: params 含非有限值（NaN/±Inf），整点跳过")
                continue
            finite_metrics: dict[str, Any] = {}
            dropped: list[str] = []
            for k, v in metrics.items():
                if (isinstance(v, float) and not isinstance(v, bool)
                        and not math.isfinite(v)):
                    dropped.append(k)
                else:
                    finite_metrics[k] = v
            if dropped:
                collect_errors.append(
                    f"{label}: metrics 非有限值键 {dropped} 已剔除（点保留）")
            try:
                params_json = _canonical_json(params)
                metrics_json = _canonical_json(finite_metrics)
            except (ValueError, TypeError) as exc:
                collect_errors.append(
                    f"{label}: params/metrics 序列化被拒（{exc}），整点跳过")
                continue
            prov: dict[str, Any] = {
                "aedt_version": "",
                "ads_version": "",
                "git_sha": "",
                "run_timestamp": art["mtime"],
                "materialized_at": created_at,
                "run_id": rid,
                "importer": "workdir",
                "source_dir": art["source_dir"],
                "curve_path": art["rel"],
                "curve_kind": art["kind"],
                "params_source": json_path.relative_to(workdir).as_posix(),
                "params_key": key_path,
            }
            if isinstance(art["n_ports"], int):
                prov["n_ports"] = art["n_ports"]
            if art["kind"] == "touchstone":
                prov["touchstone_path"] = art["rel"]
            raw_points.append({
                "run_id": rid,
                "model": scan["family"],
                "adapter": art["adapter"],
                "algorithm": WORKDIR_SOURCE,
                # study_name = 工作目录名（战役即 study）：指纹去重只在同一战役
                # 内折叠同设计点，跨战役同设计各留一行（不同求解设置的真机曲线）
                "study_name": rid,
                "seed": None,
                "params": params,
                "params_json": params_json,
                "metrics_json": metrics_json,
                "cost": None,
                "point_index": int(idx),
                "source": WORKDIR_SOURCE,
                "provenance": prov,
            })
        n_pts = len(raw_points) - n_before
        if n_pts == 0:
            skipped_runs.append(rid)
        run_infos.append({"run_id": rid, "family": scan["family"],
                          "n_curves": len(curves), "n_points": n_pts})

    # 指纹去重（同 materialize：model/study_name/seed/params canonical json）
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[dict[str, Any]] = []
    n_dup = 0
    for row in raw_points:
        fp = (row["model"], row["study_name"], json.dumps(row["seed"]),
              row["params_json"])
        if fp in seen:
            n_dup += 1
            continue
        seen.add(fp)
        rows.append(row)

    n_points = len(raw_points)
    base_counts = {
        "n_candidates": len(scans),
        "n_curves": n_curves_total,
        "n_points": n_points,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "n_points_skipped": n_points_skipped,
        "source_runs": run_infos,
        "skipped_runs": skipped_runs,
        "missing_runs": missing_runs,
        "unhealthy_points": unhealthy_points,
        "health_verdicts": health_verdicts,
    }
    if not rows:
        return error_envelope(
            ["没有可导入的曲线点（候选工作目录均无可归属设计参数的"
                       "曲线产物，或全部被健康门拦下）", *collect_errors],
            **base_counts,
        )

    bounds = _aggregate_bounds(rows)
    columns = [c for c, _t in DATASET_SCHEMA]
    n_gt_rows = 0
    gt_per_model: dict[str, int] = {}
    per_family_rows: dict[str, int] = {}
    for row in rows:
        fam_key = row["model"] or "other"
        per_family_rows[fam_key] = per_family_rows.get(fam_key, 0) + 1
        if is_ground_truth_adapter(row["adapter"]):
            n_gt_rows += 1
            gt_per_model[row["model"]] = gt_per_model.get(row["model"], 0) + 1
    gt_block = {
        "policy": GROUND_TRUTH_POLICY,
        "n_gt_rows": n_gt_rows,
        "per_model": dict(sorted(gt_per_model.items())),
    }

    type_map = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64()}
    schema = pa.schema([(c, type_map[t]) for c, t in DATASET_SCHEMA])
    arrow_rows = []
    for row in rows:
        rec = {c: row[c] for c in columns if c != "provenance_json"}
        rec["provenance_json"] = json.dumps(
            row["provenance"], ensure_ascii=False, sort_keys=True)
        arrow_rows.append(rec)
    table = pa.Table.from_pylist(arrow_rows, schema=schema)

    dataset_dir = Path(out_dir) / name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    points_path = dataset_dir / (PARQUET_NAME if fmt == "parquet" else HDF5_NAME)
    try:
        if fmt == "hdf5":
            _write_points_hdf5(points_path, table)
        else:
            pq.write_table(table, points_path)
    except RuntimeError as exc:
        return error_envelope([str(exc)])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "format": fmt,
        "points_file": points_path.name,
        "created_at": created_at,
        "importer": "workdir",
        "runs_root": str(root),
        "families": list(fams),
        "source_runs": run_infos,
        "n_candidates": len(scans),
        "n_curves": n_curves_total,
        "n_points": n_points,
        "n_rows": len(rows),
        "n_dup": n_dup,
        "n_nonfinite_skipped": n_nonfinite_skipped,
        "n_points_skipped": n_points_skipped,
        "per_family_rows": dict(sorted(per_family_rows.items())),
        "bounds": bounds,
        "columns": columns,
        "parquet": PARQUET_NAME,
        "dedup_fingerprint": "(model, study_name, seed, params canonical json)",
        "health_gate": bool(health_gate),
        "n_unhealthy_skipped": len(unhealthy_points),
        "health_verdicts": health_verdicts,
        "visibility": "private",
        "ground_truth": gt_block,
    }
    manifest_path = _save_manifest_atomic(dataset_dir, manifest)

    # 注册表回写（R2-D-03 ⑤，默认关零行为变化；best-effort 不阻塞物化）
    sync_enabled = _resolve_registry_sync(registry_sync)
    registry_synced = False
    if sync_enabled:
        registry_synced = _register_dataset_row(
            name, manifest_path, fmt, len(rows), visibility="private")

    result: dict[str, Any] = ok_envelope(
                                 **{
                                 "name": name,
                                 "dataset_dir": str(dataset_dir),
                                 "format": fmt,
                                 "points_file": str(points_path),
                                 "manifest": str(manifest_path),
                                 "schema_version": SCHEMA_VERSION,
                                 "importer": "workdir",
                                 "runs_root": str(root),
                                 "families": list(fams),
                                 **base_counts,
                                 "n_rows": len(rows),
                                 "n_dup": n_dup,
                                 "per_family_rows": dict(sorted(per_family_rows.items())),
                                 "bounds": bounds,
                                 "columns": columns,
                                 "visibility": "private",
                                 "ground_truth": gt_block,
                                 "registry_sync": registry_synced,
                                 },
                             )
    if sync_enabled and not registry_synced:
        result["warnings"] = [*result.get("warnings", []),
                              "注册表回写失败（datasets 表未登记；"
                              "manifest 文件是事实源，导入不受影响）"]
    if collect_errors:
        result["warnings"] = [*result.get("warnings", []), *collect_errors]
    result["parquet" if fmt == "parquet" else "hdf5"] = str(points_path)
    return result
