"""G10 实验追踪互操作（MLflow / W&B 单向外导， G10）。

把战役 run 的 trials/trial_*.json（optimizer.py 落盘契约）单向导出到团队既有
追踪栈，零新依赖、零侵入：本模块不 import mlflow / wandb，只产出可被对应生态
读取的文件：

- MLflow 兼容目录 <out_dir>/mlruns/<experiment_id>/<run_id>/{meta.yaml,
 params/,metrics/,tags/,artifacts/}。每个 trial 一个 MLflow run（同实验分组，
 params/metrics 不跨 trial 撞键）；metric 文件为 MLflow FileStore 行格式
 "<value> <timestamp_ms> <step> + 换行"。
- W&B 兼容 JSONL <out_dir>/wandb/<source_run_id>.jsonl，每行
 {"run", "step", "params", "metrics", "tags"}（参照 spec 的
 {"run", "params", "metrics"} 并补 step/tags）。
- JSON manifest <out_dir>/manifests/<source_run_id>.json：显式字段映射表 +
 provenance（源 run_id）。

设计要点：
- 确定性：无 wall-clock；时间戳一律取自源 meta.json 的 timestamp（缺失记 0
 哨兵并在 manifest 标 source_timestamp_known=false）；文件按固定顺序、键排序、
 allow_nan=False 写，同输入两次导出逐字节一致。
- 数值只在确定性内核（军规 7）：本模块只搬运既有 trial 数字——缺失字段一律
 不写、绝不补 0；非有限值（NaN/±Inf）与类型错误显式报错。
- 字段映射显式且完备：TRIAL_FIELD_MAP 覆盖全部已知 trial 字段
 （KNOWN_TRIAL_FIELDS）；出现映射外字段即 TrackingExportError——缺一即失败，
 不静默丢弃。
- 校验先于写入：任何 trial 非法时整体不落盘（无半成品假数据）。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

TRACKING_SCHEMA_VERSION = "1.0"
DEFAULT_OUT_DIR = Path("runs") / "tracking"
MLFLOW_DIRNAME = "mlruns"
WANDB_DIRNAME = "wandb"
MANIFEST_DIRNAME = "manifests"
PROVENANCE_ARTIFACT = "tracking_provenance.json"

#: 换行符（chr(10) 写法避免源码里的转义序列，保证磁盘字节恒为 LF）。
_NL = chr(10)

#: 每个 trial 顶层字段的去处（显式清单；缺一即失败）。
#: kind ∈ {param, metric, tag}；family ∈ {scalar, map, list}；
#: key 是目标键模板（map/list 用 {key} 占位）。
TRIAL_FIELD_MAP: dict[str, dict[str, str]] = {
  "trial_number": {"kind": "tag", "key": "trial_number", "family": "scalar"},
  "params": {"kind": "param", "key": "{key}", "family": "map"},
  "metrics": {"kind": "metric", "key": "{key}", "family": "map"},
  "cost": {"kind": "metric", "key": "cost", "family": "scalar"},
  "cache_hit": {"kind": "tag", "key": "cache_hit", "family": "scalar"},
  "feasible": {"kind": "tag", "key": "feasible", "family": "scalar"},
  "constraint_values": {"kind": "metric", "key": "constraint_{key}", "family": "list"},
}

#: 已知 trial 字段全集（注册表消费者；新增 trial 字段必须同时登记映射）。
KNOWN_TRIAL_FIELDS: frozenset[str] = frozenset(TRIAL_FIELD_MAP)

#: 源 meta.json 字段 → MLflow run tag（只导出存在的字段，best-effort）。
META_FIELD_MAP: dict[str, dict[str, str]] = {
  "run_id": {"kind": "tag", "key": "source_run_id"},
  "model": {"kind": "tag", "key": "model"},
  "adapter": {"kind": "tag", "key": "adapter"},
  "algorithm": {"kind": "tag", "key": "algorithm"},
  "study_name": {"kind": "tag", "key": "study_name"},
  "seed": {"kind": "tag", "key": "seed"},
  "git_sha": {"kind": "tag", "key": "git_sha"},
  "aedt_version": {"kind": "tag", "key": "aedt_version"},
  "ads_version": {"kind": "tag", "key": "ads_version"},
  "timestamp": {"kind": "tag", "key": "source_timestamp"},
  "status": {"kind": "tag", "key": "status"},
}

#: W&B JSONL 每行字段（稳定顺序，供读取器/文档对齐）。
WANDB_LINE_FIELDS: tuple[str, ...] = ("run", "step", "params", "metrics", "tags")

__all__ = [
  "DEFAULT_OUT_DIR",
  "KNOWN_TRIAL_FIELDS",
  "MANIFEST_DIRNAME",
  "META_FIELD_MAP",
  "MLFLOW_DIRNAME",
  "TRACKING_SCHEMA_VERSION",
  "TRIAL_FIELD_MAP",
  "WANDB_DIRNAME",
  "WANDB_LINE_FIELDS",
  "TrackingExportError",
  "check_field_coverage",
  "export_run_tracking",
  "export_run_tracking_safe",
  "load_run_meta",
  "load_trials",
  "read_mlflow_run",
  "read_mlflow_store",
  "read_wandb_history",
]


class TrackingExportError(ValueError):
  """非法输入 / 缺映射的 trial 字段（调用方应显式处理，不静默丢弃）。"""


# ---------------------------------------------------------------------------
# 基础工具（确定性序列化）
# ---------------------------------------------------------------------------

def _sha256_hex(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_name(name: str, *, what: str) -> str:
  """键/名做文件名安全校验（防路径穿越；不改变合法字符）。"""
  text = str(name)
  unsafe = ("/", chr(92), chr(0))
  if not text or text in {".", ".."} or any(c in text for c in unsafe):
    raise TrackingExportError(f"{what} 名非法（空或含路径分隔符）: {name!r}")
  return text


def _json_dumps(obj: Any) -> str:
  return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _number_str(value: int | float) -> str:
  """数值的确定性文本（json.dumps 用最短往返表示，int 不强制转 float）。"""
  return json.dumps(value)


def _as_number(value: Any, *, where: str) -> int | float:
  """校验数值（bool 不算数；拒绝 NaN/±Inf——不落规范外字面量）。"""
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise TrackingExportError(
      f"{where} 必须是数值，收到 {type(value).__name__}: {value!r}")
  if isinstance(value, float) and not math.isfinite(value):
    raise TrackingExportError(
      f"{where} 必须是有限数值（NaN/±Inf 不落盘）: {value!r}")
  return value


def _write_text(path: Path, text: str) -> None:
  """显式 newline=""（不翻译换行）：跨平台字节稳定（幂等前提）。"""
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text, encoding="utf-8", newline="")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
  _write_text(path, yaml.safe_dump(
    data, allow_unicode=True, sort_keys=True, default_flow_style=False))


def _read_json_file(path: Path) -> Any:
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except json.JSONDecodeError as exc:
    raise TrackingExportError(f"JSON 解析失败 {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# 读取源 run
# ---------------------------------------------------------------------------

def load_run_meta(run_dir: str | Path) -> dict[str, Any]:
  """读 meta.json；缺失/非对象即 TrackingExportError。"""
  meta_path = Path(run_dir) / "meta.json"
  if not meta_path.is_file():
    raise TrackingExportError(f"缺 meta.json（非 rfauto run 目录）: {meta_path}")
  meta = _read_json_file(meta_path)
  if not isinstance(meta, dict):
    raise TrackingExportError(f"meta.json 不是对象: {meta_path}")
  return meta


def load_trials(run_dir: str | Path) -> list[dict[str, Any]]:
  """按 trial_number 升序读取 trials/trial_*.json；无 trials 目录返回 []。"""
  tdir = Path(run_dir) / "trials"
  if not tdir.is_dir():
    return []
  trials: list[dict[str, Any]] = []
  seen: set[int] = set()
  for path in sorted(tdir.glob("trial_*.json")):
    data = _read_json_file(path)
    if not isinstance(data, dict):
      raise TrackingExportError(f"trial 不是对象: {path}")
    number = data.get("trial_number")
    if isinstance(number, bool) or not isinstance(number, int):
      raise TrackingExportError(
        f"trial_number 必须是 int: {path} -> {number!r}")
    if number in seen:
      raise TrackingExportError(f"trial_number 重复: {number}（{path}）")
    seen.add(number)
    trials.append(data)
  trials.sort(key=lambda t: t["trial_number"])
  return trials


def check_field_coverage(trial: dict[str, Any]) -> list[str]:
  """返回 trial 中无映射的字段（应为空）；测试/审计消费。"""
  return sorted(set(trial) - KNOWN_TRIAL_FIELDS)


def _validate_trial(trial: dict[str, Any], *, path_hint: str) -> None:
  extra = check_field_coverage(trial)
  if extra:
    raise TrackingExportError(
      f"trial 字段缺映射（不静默丢弃）{path_hint}: {extra}；"
      "请在 tracking_export.TRIAL_FIELD_MAP 显式登记")


def _timestamp_ms(meta: dict[str, Any]) -> tuple[int, bool]:
  """源 run 时间戳 → epoch 毫秒；缺失/非法返回 (0, False)（0 为哨兵非数据）。"""
  raw = meta.get("timestamp")
  if not isinstance(raw, str) or not raw.strip():
    return 0, False
  try:
    dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
  except ValueError:
    return 0, False
  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
  return int(dt.timestamp() * 1000), True


def _experiment_name(meta: dict[str, Any], override: str | None) -> str:
  if override is not None and str(override).strip():
    return str(override).strip()
  for key in ("study_name", "model"):
    val = meta.get(key)
    if val is not None and str(val).strip():
      return str(val).strip()
  return "rfauto"


def _experiment_id(name: str) -> str:
  """实验名 → 确定性数字 id（MLflow 实验 id 惯例为整数字符串）。"""
  return str(int(_sha256_hex(name)[:15], 16))


def _mlflow_run_id(source_run_id: str, trial_number: int) -> str:
  return _sha256_hex(f"{source_run_id}:{trial_number}")[:32]


def _source_run_record(meta: dict[str, Any]) -> dict[str, str]:
  return {k: str(meta[k]) for k in sorted(META_FIELD_MAP) if meta.get(k) is not None}


# ---------------------------------------------------------------------------
# trial → MLflow 文件内容（显式映射的落地）
# ---------------------------------------------------------------------------

def _trial_mlflow_payload(
  trial: dict[str, Any],
  *,
  meta: dict[str, Any],
) -> tuple[dict[str, str], dict[str, int | float], dict[str, str]]:
  """按 TRIAL_FIELD_MAP 把单个 trial 摊成 (params, metrics, tags)。

  - params：JSON 编码字符串（MLflow param 只能是字符串；编码保留类型，
   读取端 json.loads 精确还原）；
  - metrics：数值（含 cost 与 constraint_values）；
  - tags：trial_number/cache_hit/feasible + 源 meta 字段。
  """
  params: dict[str, str] = {}
  metrics: dict[str, int | float] = {}
  tags: dict[str, str] = {"trial_number": str(trial["trial_number"])}

  raw_params = trial.get("params", {})
  if not isinstance(raw_params, dict):
    raise TrackingExportError(f"trial.params 必须是对象: {raw_params!r}")
  for key in sorted(raw_params):
    params[_safe_name(str(key), what="param")] = _json_dumps(raw_params[key])

  raw_metrics = trial.get("metrics", {})
  if not isinstance(raw_metrics, dict):
    raise TrackingExportError(f"trial.metrics 必须是对象: {raw_metrics!r}")
  for key in sorted(raw_metrics):
    metrics[_safe_name(str(key), what="metric")] = _as_number(
      raw_metrics[key], where=f"metrics.{key}")

  if trial.get("cost") is not None:
    metrics["cost"] = _as_number(trial["cost"], where="cost")

  raw_cvals = trial.get("constraint_values")
  if raw_cvals is not None:
    if isinstance(raw_cvals, dict):
      items = [(str(k), raw_cvals[k]) for k in sorted(raw_cvals)]
    elif isinstance(raw_cvals, (list, tuple)):
      items = [(str(i), v) for i, v in enumerate(raw_cvals)]
    else:
      raise TrackingExportError(
        f"trial.constraint_values 必须是 list/dict: {raw_cvals!r}")
    for key, val in items:
      metrics[_safe_name(f"constraint_{key}", what="constraint metric")] = _as_number(
        val, where=f"constraint_values.{key}")

  for flag in ("cache_hit", "feasible"):
    val = trial.get(flag)
    if val is None:
      continue
    if not isinstance(val, bool):
      raise TrackingExportError(f"trial.{flag} 必须是 bool: {val!r}")
    tags[flag] = "true" if val else "false"

  for mkey, rule in META_FIELD_MAP.items():
    val = meta.get(mkey)
    if val is not None:
      tags[rule["key"]] = str(val)

  return params, metrics, tags


def _write_mlflow_trial_run(
  store: Path,
  exp_id: str,
  mlflow_run_id: str,
  *,
  number: int,
  params: dict[str, str],
  metrics: dict[str, int | float],
  tags: dict[str, str],
  meta: dict[str, Any],
  source_run_id: str,
  timestamp_ms: int,
) -> Path:
  run_dir = store / exp_id / mlflow_run_id
  for key, text in params.items():
    _write_text(run_dir / "params" / key, text)
  for key, val in metrics.items():
    _write_text(run_dir / "metrics" / key,
          f"{_number_str(val)} {timestamp_ms} {number}{_NL}")
  for key, text in tags.items():
    _write_text(run_dir / "tags" / key, text)

  _write_yaml(run_dir / "meta.yaml", {
    "artifact_uri": (run_dir / "artifacts").resolve().as_uri(),
    "end_time": timestamp_ms,
    "entry_point_name": "",
    "experiment_id": exp_id,
    "lifecycle_stage": "active",
    "run_id": mlflow_run_id,
    "run_name": f"{source_run_id}::trial_{number}",
    "source_name": "rfauto",
    "source_type": 4,
    "source_version": str(meta.get("git_sha") or ""),
    "start_time": timestamp_ms,
    "status": 3,
  })
  provenance = {
    "schema_version": TRACKING_SCHEMA_VERSION,
    "source_run_id": source_run_id,
    "trial_number": number,
    "source_run": _source_run_record(meta),
    "field_mapping": TRIAL_FIELD_MAP,
  }
  _write_text(
    run_dir / "artifacts" / PROVENANCE_ARTIFACT,
    json.dumps(provenance, sort_keys=True, ensure_ascii=True, indent=2) + _NL)
  return run_dir


# ---------------------------------------------------------------------------
# 导出主入口
# ---------------------------------------------------------------------------

def export_run_tracking(
  run_id: str,
  *,
  runs_root: str | Path = "runs",
  out_dir: str | Path | None = None,
  experiment_name: str | None = None,
) -> dict[str, Any]:
  """把 <runs_root>/<run_id> 的 trials 单向导出为 MLflow 目录 + W&B JSONL。

  校验先于写入：任一 trial 非法（缺映射字段/非有限值/类型错误）即抛
  TrackingExportError，不产生半成品。返回 JSON 安全 dict（ok/
  source_run_id/experiment_id/n_trials/各产物路径）。
  """
  rid = _safe_name(str(run_id).strip(), what="run_id")
  run_dir = Path(runs_root) / rid
  if not run_dir.is_dir():
    raise TrackingExportError(f"run 目录不存在: {run_dir}")
  meta = load_run_meta(run_dir)
  trials = load_trials(run_dir)

  out_root = (Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR).resolve()
  store = out_root / MLFLOW_DIRNAME
  exp_name = _experiment_name(meta, experiment_name)
  exp_id = _experiment_id(exp_name)
  timestamp_ms, ts_known = _timestamp_ms(meta)
  source_record = _source_run_record(meta)

  # ① 校验 + 构建（全量，先于任何写盘）
  prepared: list[tuple[int, str, dict[str, str], dict[str, int | float], dict[str, str]]] = []
  for trial in trials:
    number = trial["trial_number"]
    _validate_trial(trial, path_hint=f"{rid}/trial_{number}")
    params, metrics, tags = _trial_mlflow_payload(trial, meta=meta)
    prepared.append((number, _mlflow_run_id(rid, number), params, metrics, tags))

  # ② 写 MLflow run 目录 + 汇总 W&B/manifest 元数据
  run_dirs: list[str] = []
  trial_infos: list[dict[str, Any]] = []
  wandb_rows: list[dict[str, Any]] = []
  for (number, mlflow_run_id, params, metrics, tags), trial in zip(prepared, trials, strict=True):
    run_dir_ml = _write_mlflow_trial_run(
      store, exp_id, mlflow_run_id,
      number=number, params=params, metrics=metrics, tags=tags,
      meta=meta, source_run_id=rid, timestamp_ms=timestamp_ms)
    run_dirs.append(str(run_dir_ml))
    trial_infos.append({
      "trial_number": number,
      "mlflow_run_id": mlflow_run_id,
      "params": sorted(params),
      "metrics": sorted(metrics),
      "tags": sorted(tags),
    })
    wandb_rows.append({
      "run": rid,
      "step": number,
      "params": dict(trial.get("params") or {}),
      "metrics": dict(metrics),
      "tags": dict(tags),
    })

  # ③ 实验 meta（已存在不覆写——跨 run 共享 store 时保持稳定/幂等）
  exp_dir = store / exp_id
  if not (exp_dir / "meta.yaml").exists():
    _write_yaml(exp_dir / "meta.yaml", {
      "artifact_location": exp_dir.resolve().as_uri(),
      "creation_time": timestamp_ms,
      "experiment_id": exp_id,
      "last_update_time": timestamp_ms,
      "lifecycle_stage": "active",
      "name": exp_name,
    })

  # ④ W&B JSONL（空 trials → 空文件）
  wandb_path = out_root / WANDB_DIRNAME / f"{rid}.jsonl"
  _write_text(wandb_path, "".join(_json_dumps(row) + _NL for row in wandb_rows))

  # ⑤ JSON manifest（显式字段映射表 + provenance）
  manifest = {
    "schema_version": TRACKING_SCHEMA_VERSION,
    "source_run_id": rid,
    "source_run": source_record,
    "experiment": {"id": exp_id, "name": exp_name},
    "mlflow_store": MLFLOW_DIRNAME,
    "wandb_jsonl": f"{WANDB_DIRNAME}/{rid}.jsonl",
    "wandb_line_fields": list(WANDB_LINE_FIELDS),
    "field_mapping": {"trial": TRIAL_FIELD_MAP, "meta": META_FIELD_MAP},
    "source_timestamp_known": ts_known,
    "source_timestamp_ms": timestamp_ms if ts_known else None,
    "n_trials": len(trials),
    "trials": trial_infos,
  }
  manifest_path = out_root / MANIFEST_DIRNAME / f"{rid}.json"
  _write_text(manifest_path, json.dumps(
    manifest, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False) + _NL)

  return {
    "ok": True,
    "source_run_id": rid,
    "experiment_id": exp_id,
    "experiment_name": exp_name,
    "n_trials": len(trials),
    "mlflow_store": str(store),
    "mlflow_run_dirs": run_dirs,
    "wandb_jsonl": str(wandb_path),
    "manifest": str(manifest_path),
  }


def export_run_tracking_safe(
  run_id: str,
  *,
  runs_root: str | Path = "runs",
  out_dir: str | Path | None = None,
  experiment_name: str | None = None,
) -> dict[str, Any]:
  """export_run_tracking 的 JSON 安全包装：失败返回 {"ok": False, ...}。"""
  try:
    return export_run_tracking(
      run_id, runs_root=runs_root, out_dir=out_dir,
      experiment_name=experiment_name)
  except (TrackingExportError, OSError) as exc:
    return {"ok": False, "source_run_id": str(run_id), "errors": [str(exc)]}


# ---------------------------------------------------------------------------
# 读取器（简单读取器读回，字段对齐验收）
# ---------------------------------------------------------------------------

def _read_yaml_file(path: Path) -> dict[str, Any]:
  if not path.is_file():
    return {}
  data = yaml.safe_load(path.read_text(encoding="utf-8"))
  return data if isinstance(data, dict) else {}


def _read_mlflow_params(run_dir: Path) -> dict[str, Any]:
  out: dict[str, Any] = {}
  pdir = run_dir / "params"
  if not pdir.is_dir():
    return out
  for path in sorted(pdir.iterdir()):
    if not path.is_file():
      continue
    text = path.read_text(encoding="utf-8")
    try:
      out[path.name] = json.loads(text)
    except json.JSONDecodeError:
      out[path.name] = text
  return out


def _read_mlflow_metrics(run_dir: Path) -> dict[str, Any]:
  out: dict[str, Any] = {}
  mdir = run_dir / "metrics"
  if not mdir.is_dir():
    return out
  for path in sorted(mdir.iterdir()):
    if not path.is_file():
      continue
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
      continue
    tokens = lines[0].split()
    if not tokens:
      continue
    try:
      out[path.name] = json.loads(tokens[0])
    except json.JSONDecodeError:
      out[path.name] = float(tokens[0])
  return out


def _read_mlflow_tags(run_dir: Path) -> dict[str, str]:
  out: dict[str, str] = {}
  tdir = run_dir / "tags"
  if not tdir.is_dir():
    return out
  for path in sorted(tdir.iterdir()):
    if path.is_file():
      out[path.name] = path.read_text(encoding="utf-8")
  return out


def _tag_bool(text: Any) -> bool | None:
  if text is None:
    return None
  low = str(text).strip().lower()
  if low == "true":
    return True
  if low == "false":
    return False
  return None


def read_mlflow_run(run_dir: str | Path) -> dict[str, Any]:
  """读回单个 MLflow run 目录 → 归一化 trial 形状（与源 trial 字段对齐）。"""
  run_dir = Path(run_dir)
  meta = _read_yaml_file(run_dir / "meta.yaml")
  params = _read_mlflow_params(run_dir)
  metrics = _read_mlflow_metrics(run_dir)
  tags = _read_mlflow_tags(run_dir)
  raw_number = tags.get("trial_number")
  number: int | None
  try:
    number = int(raw_number) if raw_number is not None else None
  except (TypeError, ValueError):
    number = None
  cost = metrics.pop("cost", None)
  return {
    "source_run_id": tags.get("source_run_id", ""),
    "trial_number": number,
    "params": params,
    "metrics": metrics,
    "cost": cost,
    "cache_hit": _tag_bool(tags.get("cache_hit")),
    "feasible": _tag_bool(tags.get("feasible")),
    "mlflow_run_id": str(meta.get("run_id", "")),
    "experiment_id": str(meta.get("experiment_id", "")),
    "tags": tags,
  }


def read_mlflow_store(store_dir: str | Path) -> list[dict[str, Any]]:
  """扫描 mlruns 根下全部 run 目录 → 归一化 trial dict 列表（稳定排序）。"""
  store = Path(store_dir)
  records: list[dict[str, Any]] = []
  if store.is_dir():
    for meta_path in sorted(store.glob("*/*/meta.yaml")):
      records.append(read_mlflow_run(meta_path.parent))
  records.sort(key=lambda r: (
    str(r["source_run_id"]),
    r["trial_number"] if r["trial_number"] is not None else -1))
  return records


def read_wandb_history(path: str | Path) -> list[dict[str, Any]]:
  """读回 W&B 兼容 JSONL（每行一个 trial）。"""
  rows: list[dict[str, Any]] = []
  for line in Path(path).read_text(encoding="utf-8").splitlines():
    if line.strip():
      rows.append(json.loads(line))
  return rows
