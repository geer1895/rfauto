"""引擎联赛表（DP-17 W1）——runs/ 证据面只读抽取 → engine_league 表。

表 runs/league.duckdb（运行时产物，runs/ 已整体 gitignore 不进 git）。
字段名与 DP-13 fidelity_shadow（db_service.LEAGUE_COLUMNS）超集对齐：
delta_vs_hfss_db 泛化为 delta_vs_ref+ref_engine，新增 quantity/study/
verdict/provenance_json。唯一键 (run_id, engine, quantity)；rebuild 为
事务内全删全插（全量重算语义，确定性输入 → 内容逐字节不变）。

抽取白名单（runs/ 证据面零改写，#321 未知形态 skip 如实计数）：
- 来源 A（meta）：meta.json 的 adapter/model/metrics/wall_s/
  mesh_resolution_mm/study_name；quantity 强制带单位 token（#121）；
- 来源 B（verdict 工件）：verdict*/judg*/judge*/gate*/arbitration*.json
  经 4 形态读取器（verdict 字符串 / pass bool / all_gates_pass bool /
  overall 递归），归一到 verdict 白名单；markdown verdict（verdict.md/
  criteria.md）非机器可读，一律 skip 计数不猜；
- delta_vs_ref：组内（campaign, template_family, quantity）配对，
  ref_engine 缺省 hfss；数值量行引擎==ref → delta=0.0 恒成立；组内无
  数值 ref → NULL 不硬凑。

服务层 JSON 进出（规则 4）；duckdb 缺失 ok=False 不 raise（#105）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 表名与幂等键（db_service.LEAGUE_IDEMPOTENCY_KEY 的超集语义）
ENGINE_LEAGUE_TABLE = "engine_league"
ENGINE_LEAGUE_IDEMPOTENCY_KEY = ("run_id", "engine", "quantity")

#: 表结构（fidelity_shadow 7 列超集对齐 + DP-17 W1 扩展列）
ENGINE_LEAGUE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("run_id", "VARCHAR"),
    ("engine", "VARCHAR"),
    ("template_family", "VARCHAR"),
    ("quantity", "VARCHAR"),
    ("delta_vs_ref", "DOUBLE"),
    ("ref_engine", "VARCHAR"),
    ("wall_s", "DOUBLE"),
    ("mesh_mm", "DOUBLE"),
    ("params_hash", "VARCHAR"),
    ("study", "VARCHAR"),
    ("verdict", "VARCHAR"),
    ("provenance_json", "VARCHAR"),
)

#: verdict 归一白名单（前缀匹配；长前缀须先于短前缀判定：
#: FAIL_NOT_CONVERGED→FAIL、UNDECIDABLE→UNDECIDED）
VERDICT_WHITELIST: tuple[str, ...] = (
    "FAIL_NOT_CONVERGED",
    "UNDECIDABLE",
    "PASS",
    "FAIL",
    "PARTIAL",
    "UNDECIDED",
    "AGREE",
    "DISAGREE",
    "EQUIVALENT",
)

#: verdict 工件文件名关键词（.json 后缀；md/prose 一律非机器可读）
_VERDICT_FILE_KEYWORDS = ("verdict", "judg", "judge", "gate", "arbitration")

#: meta.status → verdict 归一（白名单之外 skip 计数）
_STATUS_VERDICT = {"done": "DONE", "failed": "FAILED", "fail": "FAILED"}

#: 参考引擎（HFSS 结果为对齐基准）
DEFAULT_REF_ENGINE = "hfss"

#: 设计参数指纹键（跨引擎配对用途；非全量参数，如实注记）
_DESIGN_KEY_RE = re.compile(r"_mm$|_ghz$|^er$|^tan_d$|^turns$")

#: verdict 工件来源行的量名标记（非数值量，不参与 delta/单位守卫）
GATE_VERDICT_QUANTITY = "gate_verdict"

_VERDICT_RAW_CAP = 200


def default_league_runs_dir() -> Path:
    """缺省 runs/ 目录（工作区根相对）。"""
    return Path("runs")


def league_db_path(runs_dir: str | Path | None = None) -> Path:
    """runs/league.duckdb 缺省路径（可传 runs_dir 覆盖，用于隔离测试）。"""
    base = Path(runs_dir) if runs_dir is not None else default_league_runs_dir()
    return base / "league.duckdb"


# ---------------------------------------------------------------------------
# verdict 归一与形态读取器
# ---------------------------------------------------------------------------

def normalize_verdict(value: Any) -> str | None:
    """verdict 原文 → 白名单归一形态；白名单外返回 None（不猜）。"""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text:
        return None
    for entry in VERDICT_WHITELIST:
        if text.startswith(entry):
            return entry
    return None


def _verdict_from_artifact_dict(d: dict[str, Any]) -> tuple[str | None, str | None]:
    """四形态读取器：返回 (归一 verdict, 形态名) 或 (None, None)。"""
    v = d.get("verdict")
    if isinstance(v, str) and v.strip():
        return normalize_verdict(v), "verdict_str"
    for key in ("all_gates_pass", "pass"):
        if isinstance(d.get(key), bool):
            return ("PASS" if d[key] else "FAIL"), f"{key}_bool"
    o = d.get("overall")
    if isinstance(o, str) and o.strip():
        nv = normalize_verdict(o)
        if nv is not None:
            return nv, "overall_str"
    elif isinstance(o, dict):
        return _verdict_from_artifact_dict(o)
    return None, None


def _is_verdict_artifact(name: str) -> bool:
    return name.endswith(".json") and any(k in name for k in _VERDICT_FILE_KEYWORDS)


def read_verdict_artifacts(run_dir: str | Path) -> dict[str, Any]:
    """扫描 run 目录内 verdict 工件（文件名白名单+四形态读取器）。

    返回 {"verdict": 归一值或 None, "verdict_raw": 原文, "shape": 形态,
    "file": 文件名, "tried": [(文件名, 结果), ...]}。确定性：verdict.json
    同名优先，其余按文件名排序，首个成功读取者胜出；W2 explain_run 与
    W1 loader 同源消费（单一读取面，避免两套口径漂移）。
    """
    run_dir = Path(run_dir)
    names = sorted(
        (n for n in os.listdir(run_dir) if _is_verdict_artifact(n)),
        key=lambda n: (n != "verdict.json", n),
    )
    tried: list[tuple[str, str]] = []
    for name in names:
        try:
            with open(run_dir / name, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            tried.append((name, f"unreadable:{type(exc).__name__}"))
            continue
        if not isinstance(data, dict):
            tried.append((name, "not_dict"))
            continue
        verdict, shape = _verdict_from_artifact_dict(data)
        if verdict is not None:
            raw_key = ("verdict" if isinstance(data.get("verdict"), str)
                       else "overall")
            return {
                "verdict": verdict,
                "verdict_raw": str(data.get(raw_key, ""))[:_VERDICT_RAW_CAP],
                "shape": shape,
                "file": name,
                "tried": tried,
            }
        tried.append((name, "no_known_shape"))
    return {"verdict": None, "verdict_raw": None, "shape": None,
            "file": None, "tried": tried}


# ---------------------------------------------------------------------------
# 来源 A：meta 行抽取
# ---------------------------------------------------------------------------

def _quantity_has_unit(name: str) -> bool:
    """#121 单位守卫：量名必须携带 _db_/_db/_ghz 单位 token。"""
    return "_db_" in name or name.endswith("_db") or name.endswith("_ghz")


def _design_params_hash(meta: dict[str, Any]) -> str | None:
    """设计参数子集指纹（_mm/_ghz/er/tan_d/turns 数值键；配对用途）。"""
    subset = {
        k: v for k, v in meta.items()
        if _DESIGN_KEY_RE.match(k) and isinstance(v, (int, float))
        and not isinstance(v, bool)
    }
    if not subset:
        return None
    payload = json.dumps(subset, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _meta_engine(meta: dict[str, Any]) -> str | None:
    engine = str(meta.get("adapter") or "").strip()
    if not engine:
        engine = str(meta.get("aedt_version") or "").strip()
    return engine or None


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_opt_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _rows_from_meta(run_dir: Path, campaign: str) -> tuple[list[dict[str, Any]], list[str]]:
    """meta.json → 联赛行；返回 (rows, skip_reasons)。"""
    skips: list[str] = []
    meta_path = run_dir / "meta.json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception as exc:
        return [], [f"meta_unreadable:{type(exc).__name__}"]
    if not isinstance(meta, dict):
        return [], ["meta_not_dict"]

    engine = _meta_engine(meta)
    if engine is None:
        skips.append("meta_no_engine")
        return [], skips
    family = _as_opt_str(meta.get("model"))
    status = str(meta.get("status") or "").strip().lower()
    verdict_from_status = _STATUS_VERDICT.get(status)
    if status and verdict_from_status is None:
        skips.append(f"unknown_status:{status}")

    # 来源 B verdict 工件优先于 status（工件是显式裁决面）
    art = read_verdict_artifacts(run_dir)
    verdict = art["verdict"] or verdict_from_status
    skips.extend(f"artifact_no_shape:{n}" for n, _r in art["tried"])

    run_id = _as_opt_str(meta.get("run_id")) or run_dir.name
    params_hash = _design_params_hash(meta)
    provenance_base: dict[str, Any] = {
        "source": "meta",
        "campaign": campaign,
        "meta_path": str(meta_path),
    }
    if art["verdict"] is not None:
        provenance_base["verdict_artifact"] = {
            "file": art["file"], "shape": art["shape"],
            "verdict_raw": art["verdict_raw"],
        }

    def _base_row(quantity: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "engine": engine,
            "template_family": family,
            "quantity": quantity,
            "delta_vs_ref": None,
            "ref_engine": None,
            "wall_s": _as_float(meta.get("wall_s")),
            "mesh_mm": _as_float(meta.get("mesh_resolution_mm")),
            "params_hash": params_hash,
            "study": _as_opt_str(meta.get("study_name")),
            "verdict": verdict,
            "provenance_json": "",
        }

    rows: list[dict[str, Any]] = []
    metrics = meta.get("metrics")
    if isinstance(metrics, dict):
        for key in sorted(metrics):
            value = metrics[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not _quantity_has_unit(key):
                skips.append(f"quantity_no_unit:{key}")
                continue
            prov = dict(provenance_base)
            prov["metric"] = key
            prov["metric_value"] = float(value)
            row = _base_row(key)
            row["provenance_json"] = json.dumps(prov, sort_keys=True,
                                                ensure_ascii=True)
            rows.append(row)
    else:
        skips.append("meta_no_metrics")

    # verdict 工件登记行（无数值量的裁决行；quantity=gate_verdict 标记）
    if art["verdict"] is not None and art["file"] is not None:
        prov = {
            "source": "verdict_artifact",
            "campaign": campaign,
            "file": str(run_dir / art["file"]),
            "shape": art["shape"],
            "verdict_raw": art["verdict_raw"],
        }
        row = _base_row(GATE_VERDICT_QUANTITY)
        row["wall_s"] = None
        row["mesh_mm"] = None
        row["provenance_json"] = json.dumps(prov, sort_keys=True,
                                            ensure_ascii=True)
        rows.append(row)
    return rows, skips


# ---------------------------------------------------------------------------
# 目录扫描（有界三种形态：顶层 / 一层嵌套 / campaign/runs/）
# ---------------------------------------------------------------------------

def _iter_candidate_run_dirs(runs_dir: Path) -> list[tuple[Path, str]]:
    """候选 run 目录（确定性排序）；返回 [(目录, campaign 名)]。

    campaign = 顶层目录名；顶层目录自身即 campaign。
    """
    out: list[tuple[Path, str]] = []
    for top in sorted(runs_dir.iterdir()):
        if not top.is_dir() or top.name.startswith(("_", ".")):
            continue
        out.append((top, top.name))
        for child in sorted(top.iterdir()):
            if child.is_dir() and not child.name.startswith(("_", ".")):
                out.append((child, top.name))
    # campaign/runs/<ts> 深层战役点（e11_warm 族）
    for meta_path in sorted(runs_dir.glob("*/campaign/runs/*/meta.json")):
        point = meta_path.parent
        out.append((point, point.parents[2].name))
    # 去重保序
    seen: set[str] = set()
    uniq: list[tuple[Path, str]] = []
    for d, camp in out:
        key = str(d)
        if key not in seen:
            seen.add(key)
            uniq.append((d, camp))
    return uniq


# ---------------------------------------------------------------------------
# delta 配对
# ---------------------------------------------------------------------------

def _group_key(row: dict[str, Any]) -> tuple[str, str, str]:
    prov = json.loads(row["provenance_json"])
    return (str(prov.get("campaign") or ""),
            str(row["template_family"] or ""),
            str(row["quantity"] or ""))


def _metric_value(row: dict[str, Any]) -> float | None:
    v = json.loads(row["provenance_json"]).get("metric_value")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
        else None


def _compute_deltas(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """组内（campaign, template_family, quantity）配对。

    ref = 组内 ref_engine 引擎、按 run_id 排序首个带数值的行；引擎==ref
    的数值量行 delta=0.0 恒成立；组内无数值 ref → delta/ref_engine 保持
    NULL（不硬凑）；gate_verdict 标记行不参与配对。返回 (rows, n_paired)。
    """
    groups: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = \
        defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[_group_key(row)][row["engine"] or ""].append(row)

    n_paired = 0
    for gkey, engines in groups.items():
        _campaign, _family, quantity = gkey
        if quantity == GATE_VERDICT_QUANTITY:
            continue  # 裁决登记行无数值语义，不配对
        ref_value: float | None = None
        for row in sorted(engines.get(DEFAULT_REF_ENGINE) or [],
                          key=lambda r: r["run_id"]):
            v = _metric_value(row)
            if v is not None:
                ref_value = v
                break
        if ref_value is None:
            continue
        for engine, erows in engines.items():
            for row in erows:
                row["ref_engine"] = DEFAULT_REF_ENGINE
                if engine == DEFAULT_REF_ENGINE:
                    row["delta_vs_ref"] = 0.0
                    n_paired += 1
                    continue
                v = _metric_value(row)
                if v is not None:
                    row["delta_vs_ref"] = v - ref_value
                    n_paired += 1
    return rows, n_paired


def collect_league_rows(runs_dir: str | Path | None = None) -> dict[str, Any]:
    """只读扫描 runs/ → 联赛行 + 如实统计（纯内存，零写面）。"""
    base = Path(runs_dir) if runs_dir is not None else default_league_runs_dir()
    if not base.is_dir():
        return {"ok": False, "reason": f"runs 目录不存在: {base}",
                "rows": [], "stats": {}}

    candidates = _iter_candidate_run_dirs(base)
    rows: list[dict[str, Any]] = []
    skip_counter: dict[str, int] = defaultdict(int)
    n_meta_dirs = 0
    for run_dir, campaign in candidates:
        if (run_dir / "meta.json").is_file():
            n_meta_dirs += 1
            got, skips = _rows_from_meta(run_dir, campaign)
            rows.extend(got)
            for s in skips:
                head = s.split(":", 1)[0]
                skip_counter[head] += 1
        elif any(_is_verdict_artifact(n) for n in os.listdir(run_dir)):
            # 无 meta 的 verdict 工件目录：engine 不可知 → skip 如实计数
            skip_counter["artifact_dir_no_meta"] += 1

    rows, n_paired = _compute_deltas(rows)
    skip_counter.setdefault("artifact_dir_no_meta", 0)
    return {
        "ok": True,
        "rows": rows,
        "stats": {
            "n_candidate_dirs": len(candidates),
            "n_meta_dirs": n_meta_dirs,
            "n_rows": len(rows),
            "n_paired_deltas": n_paired,
            "skipped": dict(sorted(skip_counter.items())),
        },
    }


# ---------------------------------------------------------------------------
# 落库（幂等建表 + 事务内全删全插）
# ---------------------------------------------------------------------------

def _league_row_values(row: dict[str, Any]) -> tuple:
    values = []
    for col, typ in ENGINE_LEAGUE_COLUMNS:
        v = row.get(col)
        if v is None:
            values.append(None)
        elif typ == "DOUBLE":
            values.append(float(v))
        else:
            values.append(str(v))
    return tuple(values)


def rebuild_league(
    runs_dir: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """全量重建 engine_league 表（幂等建表+事务内全删全插）。

    确定性输入 → 二次 rebuild 行数与内容哈希逐字节不变；runs/ 证据面
    只读（唯一写面=league.duckdb 自身，运行时产物不进 git）。
    """
    base = Path(runs_dir) if runs_dir is not None else default_league_runs_dir()
    path = Path(db_path) if db_path is not None else league_db_path(base)
    collected = collect_league_rows(base)
    base_out: dict[str, Any] = {"db_path": str(path),
                                "table": ENGINE_LEAGUE_TABLE,
                                "stats": collected.get("stats", {})}
    if not collected.get("ok"):
        return {"ok": False, "reason": collected.get("reason"), **base_out}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}", **base_out}

    rows = [_league_row_values(r) for r in collected["rows"]]
    col_names = [c for c, _ in ENGINE_LEAGUE_COLUMNS]
    placeholders = ", ".join("?" for _ in col_names)
    con = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
        cols = ", ".join(f"{c} {t}" for c, t in ENGINE_LEAGUE_COLUMNS)
        con.execute("BEGIN TRANSACTION")
        con.execute(f"CREATE TABLE IF NOT EXISTS {ENGINE_LEAGUE_TABLE} ({cols})")
        con.execute(f"DELETE FROM {ENGINE_LEAGUE_TABLE}")
        if rows:
            con.executemany(
                f"INSERT INTO {ENGINE_LEAGUE_TABLE} "
                f"({', '.join(col_names)}) VALUES ({placeholders})", rows)
        con.execute("COMMIT")
        n_total = int(con.execute(
            f"SELECT COUNT(*) FROM {ENGINE_LEAGUE_TABLE}").fetchone()[0])
        return {"ok": True, "n_rows_written": len(rows),
                "n_rows_total": n_total, **base_out}
    except Exception as exc:
        return {"ok": False, "reason": f"联赛表重建失败: {exc}", **base_out}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def league_content_hash(db_path: str | Path | None = None,
                        runs_dir: str | Path | None = None) -> dict[str, Any]:
    """全表内容哈希（按主键序拼接 sha256）——幂等判据①的度量。"""
    path = Path(db_path) if db_path is not None else league_db_path(runs_dir)
    if not path.exists():
        return {"ok": False, "reason": f"联赛库不存在: {path}"}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}"}
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        col_names = [c for c, _ in ENGINE_LEAGUE_COLUMNS]
        cur = con.execute(
            f"SELECT {', '.join(col_names)} FROM {ENGINE_LEAGUE_TABLE} "
            "ORDER BY run_id, engine, quantity")
        blob = repr(cur.fetchall()).encode("utf-8")
        return {"ok": True, "content_sha256": hashlib.sha256(blob).hexdigest()}
    except Exception as exc:
        return {"ok": False, "reason": f"内容哈希失败: {exc}"}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


# ---------------------------------------------------------------------------
# league_report：|delta| 中位 × wall_s 中位 Pareto 前沿（JSON+MD 双出）
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _pareto_front(points: list[dict[str, Any]]) -> None:
    """就地标记 on_front：|delta| 与 wall_s 双轴最小不被支配。"""
    comparable = [p for p in points
                  if p["median_abs_delta"] is not None
                  and p["median_wall_s"] is not None]
    comparable_ids = {id(p) for p in comparable}
    for p in points:
        p["on_front"] = True if id(p) in comparable_ids else None
    for p in comparable:
        for q in comparable:
            if q is p:
                continue
            if (q["median_abs_delta"] <= p["median_abs_delta"]
                    and q["median_wall_s"] <= p["median_wall_s"]
                    and (q["median_abs_delta"] < p["median_abs_delta"]
                         or q["median_wall_s"] < p["median_wall_s"])):
                p["on_front"] = False
                break


def league_report(
    db_path: str | Path | None = None,
    runs_dir: str | Path | None = None,
    *,
    template_family: str | None = None,
    quantity: str | None = None,
    min_rows: int = 1,
) -> dict[str, Any]:
    """按（族，量）分组出各引擎 |delta| 中位 × wall_s 中位 Pareto 前沿。

    - delta 轴只统计引擎!=ref 且 delta 非 NULL 的行（ref 行 delta=0 是
      构造基准，参与即偏差轴退化）；wall_s 轴只统计非 NULL 行；
    - 单轴缺失的引擎如实入表、on_front=NULL（不硬凑前沿）；
    - engine="unknown"/量=gate_verdict 的裁决登记行不进前沿（无物理量纲）。
    """
    path = Path(db_path) if db_path is not None else league_db_path(runs_dir)
    if not path.exists():
        return {"ok": False, "reason": f"联赛库不存在: {path}"}
    try:
        import duckdb
    except ImportError as exc:
        return {"ok": False, "reason": f"duckdb 未安装: {exc}"}
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        col_names = [c for c, _ in ENGINE_LEAGUE_COLUMNS]
        where: list[str] = []
        params: list[str] = []
        if template_family is not None:
            where.append("template_family = ?")
            params.append(str(template_family))
        if quantity is not None:
            where.append("quantity = ?")
            params.append(str(quantity))
        sql = (f"SELECT {', '.join(col_names)} FROM {ENGINE_LEAGUE_TABLE}")
        if where:
            sql += " WHERE " + " AND ".join(where)
        cur = con.execute(sql, params)
        all_rows = [dict(zip(col_names, r, strict=True)) for r in cur.fetchall()]
    except Exception as exc:
        return {"ok": False, "reason": f"联赛表读取失败: {exc}"}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()

    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = \
        defaultdict(lambda: defaultdict(list))
    for row in all_rows:
        groups[(row["template_family"] or "",
                row["quantity"])][row["engine"] or ""].append(row)

    out_groups: list[dict[str, Any]] = []
    for (family, qty), engines in sorted(groups.items()):
        points: list[dict[str, Any]] = []
        for engine, erows in sorted(engines.items()):
            deltas = [abs(float(r["delta_vs_ref"])) for r in erows
                      if r["delta_vs_ref"] is not None
                      and r["engine"] != DEFAULT_REF_ENGINE
                      and qty != GATE_VERDICT_QUANTITY]
            walls = [float(r["wall_s"]) for r in erows
                     if r["wall_s"] is not None]
            points.append({
                "engine": engine,
                "n_rows": len(erows),
                "median_abs_delta": _median(deltas),
                "median_wall_s": _median(walls),
            })
        if len(points) < max(1, int(min_rows)):
            continue
        _pareto_front(points)
        out_groups.append({
            "template_family": family,
            "quantity": qty,
            "engines": sorted(points, key=lambda p: p["engine"]),
        })

    md_lines: list[str] = [
        "# 引擎联赛报告（|delta_vs_ref| 中位 × wall_s 中位 Pareto 前沿）", "",
        f"- 库：`{path}`；行数：{len(all_rows)}；分组数：{len(out_groups)}",
        f"- 参考引擎：`{DEFAULT_REF_ENGINE}`（其行 delta=0 为构造基准，"
        "不进 delta 轴）", "",
    ]
    for g in out_groups:
        md_lines.append(f"## {g['template_family']} · {g['quantity']}")
        md_lines.append("")
        md_lines.append("| engine | n_rows | median_abs_delta | "
                        "median_wall_s | on_front |")
        md_lines.append("|---|---|---|---|---|")
        for p in g["engines"]:
            fmt = lambda v: "NULL" if v is None else f"{v:.4g}"  # noqa: E731
            md_lines.append(
                f"| {p['engine']} | {p['n_rows']} | "
                f"{fmt(p['median_abs_delta'])} | {fmt(p['median_wall_s'])} | "
                f"{p['on_front']} |")
        md_lines.append("")
    return {"ok": True, "groups": out_groups, "md": "\n".join(md_lines),
            "n_rows_scanned": len(all_rows), "db_path": str(path)}
