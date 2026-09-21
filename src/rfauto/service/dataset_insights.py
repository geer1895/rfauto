"""dataset_insights —— 数据集注册表余量（待做列收口）。

dataset_service 已落 Parquet 物化 + DuckDB 直查 + 健康门禁 +
数据面消费；本模块补齐余量统计三件事：

- **点数/参数空间覆盖度统计**（``dataset_coverage``）：点数按
  model/adapter/source 分布 + 数值参数逐维 distinct/界/等宽分箱占用率
  （喂"LHS 增广至 100+ 点"的采样决策，6.3 神经算子前置）；
- **ground truth 标注 + 6.3 解锁进度可见**（``annotate_ground_truth`` /
  ``neural_operator_readiness``）：真机引擎白名单
  （dataset_service.is_ground_truth_adapter）逐行判别 → manifest
  ``ground_truth`` 块；解锁口径=**器件族级**——任一 model 的 GT 点数
  ≥门槛（默认 100，roadmap 6.3「单工作点 LHS 增广至 100+ 点」，跨族
  混点不算解锁）；
- **HF 格式/公开双集**（``set_dataset_visibility`` / ``export_hf_dataset`` /
  ``list_datasets``）：manifest ``visibility``（public/private，物化默认
  private）+ HuggingFace datasets 目录布局导出（``hf/data/train-*.parquet``
  逐字节副本 + README.md YAML frontmatter 数据卡）；private 数据集默认
  拒绝公开导出（防战役数据误发布，显式 allow_private 才放行）；
- **公开集注册路径 + 双集防污染**（``register_public_dataset`` /
  ``load_dataset_sets``，E1 收口）：``<out_dir>/public_set.yaml`` 是公开集
  注册表（E2 公开 RF 数据集接入的登记面），私有集=本地 manifest
  visibility=private 的数据集；两集 **id 交集非空即 FAIL**（对齐 WP3.7
  agent_bench.load_bench_sets 口径），私有战役资产未经显式 promote 不得
  登记为公开。

数值只由确定性内核产出（军规 7）：本模块只做确定性统计/判别/导出，
不引入任何估计量；所有数字可从 Parquet/manifest 复算。
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.dataset_service import (
    DEFAULT_OUT_DIR,
    GROUND_TRUTH_POLICY,
    MANIFEST_NAME,
    PARQUET_NAME,
    _dataset_format,
    _read_points_table,
    _register_dataset_row,
    _resolve_registry_sync,
    _validate_dataset_name,
    is_ground_truth_adapter,
)

# 6.3 神经算子解锁门槛（roadmap 6.3：LHS 增广至 100+ 点；WP2.4 行口径）
NEURAL_OPERATOR_THRESHOLD_DEFAULT = 100

VISIBILITIES = ("public", "private")

# HF 导出布局（HuggingFace datasets 本地目录惯例：README 卡 + data/*.parquet）
HF_DIR_NAME = "hf"
HF_CARD_NAME = "README.md"
HF_DATA_SPLIT = "data/train-00000-of-00001.parquet"

# 公开集注册表（注册表根目录下的文件，不是数据集目录——list_datasets 只
# 迭代目录，注册表文件不会被误认成数据集）
PUBLIC_SET_NAME = "public_set.yaml"
PUBLIC_SET_SCHEMA_VERSION = "1.0"
PUBLIC_SET_STATUS_LOADED = "loaded"
PUBLIC_SET_STATUS_NOT_CONFIGURED = "not_configured"
PUBLIC_SET_STATUS_INVALID = "invalid"


# ---------------------------------------------------------------------------
# 内部工具（manifest 读写 / 数据集定位 / 行读取）
# ---------------------------------------------------------------------------

def _load_manifest(dataset_dir: Path) -> dict[str, Any] | None:
    """读 manifest YAML；不存在/解析失败/非对象一律 None（调用方报不存在）。"""
    path = dataset_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _save_manifest(dataset_dir: Path, manifest: dict[str, Any]) -> None:
    import yaml

    (dataset_dir / MANIFEST_NAME).write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _resolve_dataset(name: str, out_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    """校验数据集名并定位目录 + manifest；不存在抛 FileNotFoundError。"""
    name = _validate_dataset_name(name)
    dataset_dir = Path(out_dir) / name
    manifest = _load_manifest(dataset_dir)
    if manifest is None:
        raise FileNotFoundError(
            f"数据集不存在: {name}（缺 {MANIFEST_NAME}，先 materialize_dataset）")
    return dataset_dir, manifest


def _read_rows(
    dataset_dir: Path,
    columns: list[str],
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按列读点级数据行（列裁剪，避免整表物化进内存）。

    格式随 manifest 分派（parquet 直读 / hdf5 经 h5py），单一入口
    dataset_service._read_points_table；缺可选依赖抛 RuntimeError 显式提示。
    """
    return _read_points_table(dataset_dir, manifest, columns).to_pylist()


def _tally(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """按列值计数（键序排序，输出确定性）。"""
    counts: dict[str, int] = {}
    for row in rows:
        k = str(row.get(key) or "")
        counts[k] = counts.get(k, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# 点数 / 参数空间覆盖度统计
# ---------------------------------------------------------------------------

def dataset_coverage(
    name: str,
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    bins: int = 10,
) -> dict[str, Any]:
    """数据集点数分布 + 参数空间覆盖度统计（WP2.4 待做列①）。

    - 点数：n_rows/n_points + by_model/by_adapter/by_source 计数；
    - 参数空间：数值参数（bool/非有限值除外）逐维 distinct、[min,max]、
      等宽分箱占用率（occupied_bins/bins）；常数维（min==max）记占 1 格
      并单列 n_constant_dims——常数维对覆盖度无贡献，不虚报 100%；
    - 汇总 mean/min occupancy 与最弱维 weakest_key（喂 LHS 增广采样决策）。

    bins 是分箱数（>=2），只影响占用率粒度，不影响 distinct/界。
    """
    bins_i = int(bins)
    if bins_i < 2:
        return {"ok": False, "errors": [f"bins 必须 >= 2，收到 {bins!r}"]}
    try:
        dataset_dir, manifest = _resolve_dataset(name, out_dir)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "errors": [str(exc)]}
    try:
        rows = _read_rows(
            dataset_dir, ["model", "adapter", "source", "params_json"], manifest)
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)]}
    except Exception as exc:
        return {"ok": False, "errors": [f"点级数据读取失败: {exc}"]}

    # 数值参数逐维收集（bool 与非有限值不进统计——与写入侧拦截口径一致）
    values: dict[str, set[float]] = {}
    present: dict[str, int] = {}
    for row in rows:
        try:
            params = json.loads(str(row.get("params_json") or "{}"))
        except Exception:
            continue
        if not isinstance(params, dict):
            continue
        for key, val in params.items():
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            fv = float(val)
            if not math.isfinite(fv):
                continue  # 写入侧已拦，双保险
            values.setdefault(key, set()).add(fv)
            present[key] = present.get(key, 0) + 1

    per_key: dict[str, dict[str, Any]] = {}
    occupancies: list[tuple[str, float]] = []
    for key in sorted(values):
        vs = values[key]
        lo, hi = min(vs), max(vs)
        if hi > lo:
            width = (hi - lo) / bins_i
            occupied = len({
                min(math.floor((v - lo) / width), bins_i - 1) for v in vs})
        else:
            occupied = 1  # 常数维：只占 1 格
        ratio = occupied / bins_i
        occupancies.append((key, ratio))
        per_key[key] = {
            "present_rows": present[key],
            "distinct": len(vs),
            "min": lo,
            "max": hi,
            "occupied_bins": occupied,
            "bins": bins_i,
            "occupancy": ratio,
        }

    coverage = {
        "n_dims": len(per_key),
        "n_constant_dims": sum(
            1 for spec in per_key.values() if spec["distinct"] == 1),
        "mean_occupancy": (
            sum(r for _k, r in occupancies) / len(occupancies)
            if occupancies else 0.0),
        "min_occupancy": min(r for _k, r in occupancies) if occupancies else 0.0,
        "weakest_key": min(occupancies, key=lambda t: t[1])[0] if occupancies else "",
    }
    return {
        "ok": True,
        "name": str(manifest.get("name") or name),
        "dataset_dir": str(dataset_dir),
        "n_points": int(manifest.get("n_points") or 0),
        "n_rows": int(manifest.get("n_rows") or len(rows)),
        "by_model": _tally(rows, "model"),
        "by_adapter": _tally(rows, "adapter"),
        "by_source": _tally(rows, "source"),
        "bins": bins_i,
        "per_key": per_key,
        "coverage": coverage,
    }


# ---------------------------------------------------------------------------
# ground truth 标注 + 6.3 神经算子解锁进度
# ---------------------------------------------------------------------------

def _gt_block(
    rows: list[dict[str, Any]],
    threshold: int,
    policy: str = GROUND_TRUTH_POLICY,
) -> dict[str, Any]:
    """逐行 GT 判别 → 标注块（含器件族级解锁判定）。"""
    per_model: dict[str, int] = {}
    n_gt = 0
    for row in rows:
        if is_ground_truth_adapter(row.get("adapter")):
            n_gt += 1
            model_key = str(row.get("model") or "")
            per_model[model_key] = per_model.get(model_key, 0) + 1
    per_model = dict(sorted(per_model.items()))
    return {
        "policy": policy,
        "n_gt_rows": n_gt,
        "n_rows": len(rows),
        "per_model": per_model,
        "threshold": threshold,
        "unlocked": any(v >= threshold for v in per_model.values()),
        "annotated_at": datetime.now(timezone.utc).isoformat(),
    }


def _progress_view(
    name: str,
    dataset_dir: Path,
    manifest: dict[str, Any],
    gt: dict[str, Any],
) -> dict[str, Any]:
    """从标注块计算 6.3 解锁进度视图（器件族级口径）。"""
    threshold = int(gt.get("threshold") or NEURAL_OPERATOR_THRESHOLD_DEFAULT)
    per_model_raw = gt.get("per_model") or {}
    per_model: dict[str, dict[str, Any]] = {}
    for model_key, n in sorted(per_model_raw.items()):
        per_model[str(model_key)] = {
            "n_gt": int(n),
            "unlocked": int(n) >= threshold,
        }
    best_model, best_gt = "", 0
    for model_key, spec in per_model.items():  # 键已排序：并列取字典序最小
        if spec["n_gt"] > best_gt:
            best_model, best_gt = model_key, spec["n_gt"]
    return {
        "ok": True,
        "name": str(manifest.get("name") or name),
        "manifest": str(dataset_dir / MANIFEST_NAME),
        "n_rows": int(gt.get("n_rows")
                      or manifest.get("n_rows") or 0),
        "n_gt_rows": int(gt.get("n_gt_rows") or 0),
        "threshold": threshold,
        "unlocked": bool(gt.get("unlocked")),
        "per_model": per_model,
        "best_model": best_model,
        "best_model_gt": best_gt,
        "progress_ratio": min(1.0, best_gt / threshold) if threshold else 0.0,
        "deficit": max(0, threshold - best_gt),
    }


def annotate_ground_truth(
    name: str,
    *,
    threshold: int = NEURAL_OPERATOR_THRESHOLD_DEFAULT,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """ground truth 标注（WP2.4 待做列②）：逐行判别 → manifest 回写 +
    6.3 解锁进度（幂等：重复调用以最新 threshold 重算并覆盖标注块）。

    物化时已写基础标注（dataset_service.materialize_dataset 的
    ``ground_truth`` 块）；本函数补 threshold/unlocked/annotated_at 并
    提供改门槛重算入口。
    """
    thr = int(threshold)
    if thr < 1:
        return {"ok": False, "errors": [f"threshold 必须 >= 1，收到 {threshold!r}"]}
    try:
        dataset_dir, manifest = _resolve_dataset(name, out_dir)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "errors": [str(exc)]}
    try:
        rows = _read_rows(dataset_dir, ["model", "adapter"], manifest)
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)]}
    except Exception as exc:
        return {"ok": False, "errors": [f"点级数据读取失败: {exc}"]}

    gt = _gt_block(rows, thr)
    manifest["ground_truth"] = gt
    _save_manifest(dataset_dir, manifest)
    return _progress_view(name, dataset_dir, manifest, gt)


def neural_operator_readiness(
    name: str,
    *,
    threshold: int = NEURAL_OPERATOR_THRESHOLD_DEFAULT,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """6.3 神经算子解锁进度（WP2.4「6.3 解锁进度可见，门槛 100+ 点」）。

    manifest 无标注块或 threshold 与请求不一致时自动重算并回写（幂等）；
    一致时零重算直读标注。返回值含 per_model 逐族进度/best_model/
    progress_ratio/deficit——UI/CLI 薄壳可直接渲染。
    """
    thr = int(threshold)
    if thr < 1:
        return {"ok": False, "errors": [f"threshold 必须 >= 1，收到 {threshold!r}"]}
    try:
        dataset_dir, manifest = _resolve_dataset(name, out_dir)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "errors": [str(exc)]}

    gt = manifest.get("ground_truth")
    need_annotate = (
        not isinstance(gt, dict) or "per_model" not in gt
        or int(gt.get("threshold") or 0) != thr)
    if need_annotate:
        return annotate_ground_truth(name, threshold=thr, out_dir=out_dir)
    return _progress_view(name, dataset_dir, manifest, gt)


# ---------------------------------------------------------------------------
# 公开/私有双集 + HF 格式导出
# ---------------------------------------------------------------------------

def set_dataset_visibility(
    name: str,
    visibility: str,
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """公开/私有双集切换（WP2.4/E1 待做列③）：manifest ``visibility``
    只允许 public/private；public 是 export_hf_dataset 的放行前提。

    R2-D-03 ⑤：manifest 保存后按 settings ``db.dataset_registry_sync``
    （默认关）best-effort 回写注册表 datasets 行的 visibility 字段；
    结果信封 ``registry_sync`` 如实透出是否已登记。
    """
    if visibility not in VISIBILITIES:
        return {"ok": False, "errors": [
            f"visibility 只允许 {'/'.join(VISIBILITIES)}，收到 {visibility!r}"]}
    try:
        dataset_dir, manifest = _resolve_dataset(name, out_dir)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "errors": [str(exc)]}
    manifest["visibility"] = visibility
    _save_manifest(dataset_dir, manifest)
    # 注册表回写（默认关零行为变化；写失败不回滚 manifest——文件是事实源）
    registry_synced = False
    if _resolve_registry_sync(None):
        registry_synced = _register_dataset_row(
            str(manifest.get("name") or name),
            dataset_dir / MANIFEST_NAME,
            str(manifest.get("format") or ""),
            manifest.get("n_rows"),
            visibility=visibility,
        )
    return {
        "ok": True,
        "name": str(manifest.get("name") or name),
        "visibility": visibility,
        "manifest": str(dataset_dir / MANIFEST_NAME),
        "registry_sync": registry_synced,
    }


def export_hf_dataset(
    name: str,
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    license: str = "",
    allow_private: bool = False,
) -> dict[str, Any]:
    """HF 格式导出（WP2.4/E1 待做列③）：HuggingFace datasets 本地目录布局。

    - ``<dataset_dir>/hf/data/train-00000-of-00001.parquet``：points.parquet
      逐字节副本（行式 schema 不变，``datasets.load_dataset`` 可直读）；
    - ``<dataset_dir>/hf/README.md``：YAML frontmatter 数据卡（configs/
      data_files 指向 data 分片；rfauto 统计/ground truth/provenance 归入
      ``rfauto:`` 嵌套键）——字段全部取自 manifest，不含导出时刻时间戳，
      同 manifest 重导出逐字节一致（确定性）；
    - private 数据集默认拒绝导出（防战役数据误发布）：先
      ``set_dataset_visibility(name, "public")``，或显式 allow_private=True。
    """
    try:
        dataset_dir, manifest = _resolve_dataset(name, out_dir)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "errors": [str(exc)]}
    visibility = str(manifest.get("visibility") or "private")
    if visibility != "public" and not allow_private:
        return {"ok": False, "errors": [
            f"数据集 {name} 为 {visibility}：公开导出需先 "
            "set_dataset_visibility(name, 'public')，或显式 allow_private=True"]}

    lic = str(license or "").strip()
    hf_dir = dataset_dir / HF_DIR_NAME
    data_dir = hf_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hf_parquet = data_dir / Path(HF_DATA_SPLIT).name
    src_parquet = dataset_dir / PARQUET_NAME
    if _dataset_format(manifest) == "parquet" and src_parquet.exists():
        shutil.copyfile(src_parquet, hf_parquet)  # 逐字节副本
    else:
        # hdf5 物化的数据集：HF datasets 布局要求 parquet 分片，经 Arrow
        # 表转写（行式 schema 不变，同输入确定性）
        try:
            table = _read_points_table(dataset_dir, manifest, None)
            import pyarrow.parquet as pq

            pq.write_table(table, hf_parquet)
        except (RuntimeError, FileNotFoundError, ImportError) as exc:
            return {"ok": False, "errors": [str(exc)]}

    front: dict[str, Any] = {
        "name": str(manifest.get("name") or name),
        "visibility": visibility,
        "tags": ["rfauto", "rf", "sparameters", "dataset-registry"],
        "configs": [{
            "config_name": "default",
            "data_files": [{"split": "train", "path": HF_DATA_SPLIT}],
        }],
    }
    if lic:
        front["license"] = lic
    rfauto_meta: dict[str, Any] = {
        "schema_version": str(manifest.get("schema_version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "n_points": int(manifest.get("n_points") or 0),
        "n_rows": int(manifest.get("n_rows") or 0),
        "n_dup": int(manifest.get("n_dup") or 0),
        "n_nonfinite_skipped": int(manifest.get("n_nonfinite_skipped") or 0),
        "columns": list(manifest.get("columns") or []),
        "bounds": dict(manifest.get("bounds") or {}),
        "source_runs": list(manifest.get("source_runs") or []),
    }
    gt = manifest.get("ground_truth")
    if isinstance(gt, dict):
        rfauto_meta["ground_truth"] = gt
    front["rfauto"] = rfauto_meta

    import yaml

    card = (
        "---\n"
        + yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + "rfauto 数据集注册表导出（WP2.4/E1）：行式 schema 与查询口径见"
        " rfauto.service.dataset_service（DATASET_SCHEMA）。\n"
        + "ground truth 口径与 6.3 神经算子解锁进度见"
        " rfauto.service.dataset_insights。\n")
    card_path = hf_dir / HF_CARD_NAME
    card_path.write_text(card, encoding="utf-8")

    return {
        "ok": True,
        "name": str(manifest.get("name") or name),
        "hf_dir": str(hf_dir),
        "parquet": str(hf_parquet),
        "card": str(card_path),
        "visibility": visibility,
        "license": lic,
        "n_rows": int(manifest.get("n_rows") or 0),
        "n_gt_rows": int(gt.get("n_gt_rows") or 0) if isinstance(gt, dict) else None,
    }


def list_datasets(
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    visibility: str | None = None,
) -> dict[str, Any]:
    """注册表余量总览：逐数据集关键数字（点数/GT 标注/可见性/HF 导出态），
    按 name 排序；visibility 过滤只影响列表不影响盘面。"""
    if visibility is not None and visibility not in VISIBILITIES:
        return {"ok": False, "errors": [
            f"visibility 只允许 {'/'.join(VISIBILITIES)} 或 None，"
            f"收到 {visibility!r}"]}
    out_root = Path(out_dir)
    items: list[dict[str, Any]] = []
    if out_root.is_dir():
        for d in sorted(p for p in out_root.iterdir() if p.is_dir()):
            manifest = _load_manifest(d)
            if manifest is None:
                continue
            vis = str(manifest.get("visibility") or "private")
            if visibility is not None and vis != visibility:
                continue
            gt = manifest.get("ground_truth")
            gt = gt if isinstance(gt, dict) else None
            items.append({
                "name": str(manifest.get("name") or d.name),
                "schema_version": str(manifest.get("schema_version") or ""),
                "created_at": str(manifest.get("created_at") or ""),
                "format": _dataset_format(manifest),
                "n_points": int(manifest.get("n_points") or 0),
                "n_rows": int(manifest.get("n_rows") or 0),
                "n_dup": int(manifest.get("n_dup") or 0),
                "visibility": vis,
                "n_gt_rows": int(gt.get("n_gt_rows") or 0) if gt else None,
                "gt_unlocked": bool(gt.get("unlocked")) if gt else None,
                "has_hf": (d / HF_DIR_NAME).is_dir(),
                "dataset_dir": str(d),
            })
    return {
        "ok": True,
        "out_dir": str(out_root),
        "datasets": items,
        "n_datasets": len(items),
    }


# ---------------------------------------------------------------------------
# 公开集注册路径 + 公开/私有双集防污染（E1 收口；对齐 WP3.7 load_bench_sets）
# ---------------------------------------------------------------------------

def _public_set_path(out_dir: str | Path) -> Path:
    return Path(out_dir) / PUBLIC_SET_NAME


def _load_public_set(
    out_dir: str | Path,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """读公开集注册表 → (entries, errors)。

    缺文件 → (None, [])（未配置，不是错误：E2 未接入前 public 侧合法为
    空）；存在但结构非法（非对象/entries 非列表/条目缺合法 name/重复
    name）→ (None, [错误])——防静默降级，与 load_bench_sets 的 invalid
    口径一致。
    """
    path = _public_set_path(out_dir)
    if not path.exists():
        return None, []
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"公开集注册表解析失败: {path.name}（{exc}）"]
    if not isinstance(data, dict):
        return None, [f"公开集注册表结构非法: {path.name} 顶层必须是对象"]
    entries = data.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        return None, [f"公开集注册表结构非法: {path.name} entries 必须是列表"]
    errors: list[str] = []
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            errors.append(f"公开集注册表 entries[{i}] 必须是对象")
            continue
        try:
            ename = _validate_dataset_name(str(item.get("name") or ""))
        except ValueError as exc:
            errors.append(f"公开集注册表 entries[{i}]: {exc}")
            continue
        if ename in seen:
            errors.append(f"公开集注册表内 id 重复: {ename}")
            continue
        seen.add(ename)
        cleaned.append({
            "name": ename,
            "source": str(item.get("source") or ""),
            "license": str(item.get("license") or ""),
            "registered_at": str(item.get("registered_at") or ""),
        })
    if errors:
        return None, errors
    return cleaned, []


def _private_dataset_ids(out_dir: str | Path) -> list[str]:
    """私有集 id：注册表目录下 manifest visibility=private（含缺键默认）的
    本地数据集名（现库 GT 121 行战役资产全部在此侧）。"""
    out_root = Path(out_dir)
    ids: list[str] = []
    if not out_root.is_dir():
        return ids
    for d in sorted(p for p in out_root.iterdir() if p.is_dir()):
        manifest = _load_manifest(d)
        if manifest is None:
            continue
        if str(manifest.get("visibility") or "private") == "private":
            ids.append(str(manifest.get("name") or d.name))
    return sorted(set(ids))


def load_dataset_sets(
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    """公开/私有双集装载 + 防污染检查（对齐 WP3.7 agent_bench.load_bench_sets）。

    - 公开集 = ``<out_dir>/public_set.yaml`` 注册表条目（状态 loaded /
      not_configured（缺文件，合法空集）/ invalid（结构非法=硬错误））；
    - 私有集 = 本地 manifest visibility=private 的数据集（manifest 派生，
      永远可装载）；
    - **两集 id 交集非空即 FAIL**（ok=False + overlap_ids）：公开集条目
      与私有战役数据同名意味着私有资产被遮蔽/洗白，必须显式处置
      （改名或 register_public_dataset(promote=True)）。
    """
    out_root = Path(out_dir)
    entries, errors = _load_public_set(out_root)
    if entries is None and not errors:
        public_status = PUBLIC_SET_STATUS_NOT_CONFIGURED
    elif entries is None:
        public_status = PUBLIC_SET_STATUS_INVALID
    else:
        public_status = PUBLIC_SET_STATUS_LOADED
    public_ids = sorted({str(e["name"]) for e in (entries or [])})
    private_ids = _private_dataset_ids(out_root)
    overlap = sorted(set(public_ids) & set(private_ids))
    if overlap:
        errors.append(
            f"双集污染：公开/私有数据集 id 交集非空（{len(overlap)} 个）→ "
            f"{overlap[:5]}")
    return {
        "ok": not errors,
        "errors": errors,
        "public": {
            "status": public_status,
            "path": str(_public_set_path(out_root)),
            "n_ids": len(public_ids),
            "ids": public_ids,
            "entries": list(entries or []),
        },
        "private": {"n_ids": len(private_ids), "ids": private_ids},
        "overlap_ids": overlap,
    }


def register_public_dataset(
    name: str,
    *,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    source: str = "",
    license: str = "",
    promote: bool = False,
) -> dict[str, Any]:
    """公开集注册路径（E1 收口；E2 公开 RF 数据集接入的登记面）。

    把数据集 id 登记进 ``public_set.yaml``（幂等：同名条目覆盖）；本地
    尚未物化的外部公开集也可先登记（source 记来源）。

    防污染前置：id 已是本地 **私有** 数据集时默认拒绝——私有战役资产不得
    未经显式确认洗白为公开；``promote=True`` 才先
    ``set_dataset_visibility(name, "public")``（离开私有集）再登记。登记
    后复跑 load_dataset_sets，两集 id 交集非空即 ok=False（纵深防御：
    手改注册表造成的污染也在此暴露）。
    """
    try:
        name = _validate_dataset_name(name)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)]}
    out_root = Path(out_dir)
    entries, errors = _load_public_set(out_root)
    if errors:
        return {"ok": False, "errors": errors}

    manifest = _load_manifest(out_root / name)
    local_private = (
        manifest is not None
        and str(manifest.get("visibility") or "private") == "private")
    if local_private and not promote:
        return {"ok": False, "errors": [
            f"双集污染防护：{name} 是本地私有数据集，公开集注册需显式 "
            "promote=True（先转 public 再登记），或为公开集改用不同 id"]}
    promoted = False
    if local_private:
        flip = set_dataset_visibility(name, "public", out_dir=out_root)
        if not flip.get("ok"):
            return {"ok": False, "errors": list(flip.get("errors") or [])}
        promoted = True

    registered_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "name": name,
        "source": str(source or ""),
        "license": str(license or ""),
        "registered_at": registered_at,
    }
    kept = [e for e in (entries or []) if str(e.get("name")) != name]
    kept.append(entry)
    kept.sort(key=lambda e: str(e.get("name")))
    import yaml

    out_root.mkdir(parents=True, exist_ok=True)
    _public_set_path(out_root).write_text(
        yaml.safe_dump(
            {"schema_version": PUBLIC_SET_SCHEMA_VERSION, "entries": kept},
            allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    check = load_dataset_sets(out_dir=out_root)
    return {
        "ok": bool(check.get("ok")),
        "errors": list(check.get("errors") or []),
        "name": name,
        "registered_at": registered_at,
        "promoted": promoted,
        "public_set": str(_public_set_path(out_root)),
        "n_entries": len(kept),
        "overlap_ids": list(check.get("overlap_ids") or []),
    }
