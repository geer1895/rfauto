"""dataset_service.io —— 数据集存取面（manifest 读取/parquet-hdf5 点表读写/注册表行登记）。

自 dataset_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原节「物化格式分派与点级数据读取」逐字节搬迁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    DATASET_FORMATS,
    DATASET_SCHEMA,
    DEFAULT_FORMAT,
    HDF5_NAME,
    MANIFEST_NAME,
    PARQUET_NAME,
    _import_h5py,
    _import_pyarrow,
)

# ---------------------------------------------------------------------------
# 物化格式分派（parquet | hdf5）与点级数据读取
# ---------------------------------------------------------------------------

def _load_manifest_yaml(dataset_dir: Path) -> dict[str, Any] | None:
    """读本数据集 manifest YAML；缺失/解析失败/非对象一律 None。"""
    path = dataset_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _dataset_format(manifest: dict[str, Any] | None) -> str:
    """manifest ``format`` 键 → 物化格式；缺失（旧版 manifest）/未知值
    一律回退 parquet——既有注册表资产零迁移，读取永不被脏值卡死。"""
    fmt = str((manifest or {}).get("format") or DEFAULT_FORMAT)
    return fmt if fmt in DATASET_FORMATS else DEFAULT_FORMAT


def _points_path(dataset_dir: Path, manifest: dict[str, Any] | None) -> Path:
    """按 manifest 格式定位点级数据文件。"""
    return dataset_dir / (
        PARQUET_NAME if _dataset_format(manifest) == "parquet" else HDF5_NAME)


def _write_points_hdf5(path: Path, table: Any) -> None:
    """把行式 Arrow 表（DATASET_SCHEMA）写为 HDF5。

    每列一个 1D 数据集（create_dataset 顺序=DATASET_SCHEMA 列序，
    ``track_times=False`` 去对象时间戳，同输入字节级可复现）：
    - string 列 → 变长 UTF-8（本 schema 的 string 列无 NULL）；
    - 可空数值列（seed=int64/cost=float64）→ 值位 + ``__valid__<列>``
      u1 掩码（1=有值，0=NULL；HDF5 无原生 NULL，掩码是唯一无损口径；
      seed 的 NULL 值位填 0、cost 填 NaN，均被掩码遮蔽不参与语义）。
    """
    h5py = _import_h5py()
    str_dt = h5py.string_dtype(encoding="utf-8")
    kinds = dict(DATASET_SCHEMA)
    with h5py.File(path, "w") as f:
        for name in table.column_names:
            values = table[name].to_pylist()
            kind = kinds.get(name, "string")
            if kind == "string":
                f.create_dataset(
                    name, data=[str(v) for v in values],
                    dtype=str_dt, track_times=False)
                continue
            valid = [0 if v is None else 1 for v in values]
            if kind == "int64":
                filled = [int(v) if v is not None else 0 for v in values]
                f.create_dataset(name, data=filled, dtype="<i8",
                                 track_times=False)
            else:  # float64
                filled = [float(v) if v is not None else float("nan")
                          for v in values]
                f.create_dataset(name, data=filled, dtype="<f8",
                                 track_times=False)
            f.create_dataset(f"__valid__{name}", data=valid, dtype="u1",
                             track_times=False)


def _read_points_hdf5(path: Path, columns: list[str] | None = None) -> Any:
    """HDF5 点级数据 → pyarrow 表（列裁剪可选），与 Parquet 读路径同构。"""
    pa, _pq = _import_pyarrow()
    h5py = _import_h5py()
    want = list(columns) if columns is not None else [c for c, _t in DATASET_SCHEMA]
    types = dict(DATASET_SCHEMA)
    type_map = {"string": pa.string(), "int64": pa.int64(),
                "float64": pa.float64()}
    arrays: list[Any] = []
    with h5py.File(path, "r") as f:
        for name in want:
            if name not in f:
                raise KeyError(f"HDF5 数据集缺列: {name}")
            kind = types.get(name, "string")
            if kind == "string":
                raw = f[name][:]
                vals = [
                    v.decode("utf-8") if isinstance(v, bytes) else str(v)
                    for v in raw.tolist()]
                arrays.append(pa.array(vals, type=type_map["string"]))
                continue
            values = f[name][:].tolist()
            valid_ds = f"__valid__{name}"
            if valid_ds in f:
                valid = f[valid_ds][:].tolist()
                values = [v if int(m) == 1 else None
                          for v, m in zip(values, valid, strict=True)]
            arrays.append(pa.array(values, type=type_map[kind]))
    return pa.Table.from_arrays(arrays, names=want)


def _read_points_table(
    dataset_dir: Path,
    manifest: dict[str, Any] | None,
    columns: list[str] | None = None,
) -> Any:
    """按 manifest 格式读点级数据为 pyarrow 表（查询/统计共用入口）。

    parquet 直读；hdf5 经 h5py 重建同 schema Arrow 表。文件缺失抛
    FileNotFoundError（调用方转"数据集不存在"语义）。
    """
    fmt = _dataset_format(manifest)
    path = dataset_dir / (PARQUET_NAME if fmt == "parquet" else HDF5_NAME)
    if not path.exists():
        raise FileNotFoundError(f"点级数据文件不存在: {path}（先 materialize）")
    if fmt == "hdf5":
        return _read_points_hdf5(path, columns)
    _pa, pq = _import_pyarrow()
    return pq.read_table(path, columns=columns)


# ---------------------------------------------------------------------------
# 注册表回写（R2-D-03 ⑤：默认关，零行为变化；best-effort #105）
# ---------------------------------------------------------------------------

def _resolve_registry_sync(explicit: bool | None) -> bool:
    """registry_sync 解析链：显式实参 > settings ``db.dataset_registry_sync``
    > False。settings 读取失败安全侧按关处理（不阻塞物化主路径）。"""
    if explicit is not None:
        return bool(explicit)
    try:
        from rfauto.infra.config import load_settings

        return bool(load_settings().db.dataset_registry_sync)
    except Exception:
        return False


def _register_dataset_row(
    name: str,
    manifest_path: str | Path,
    fmt: str,
    n_rows: int | None,
    *,
    visibility: str = "private",
) -> bool:
    """把数据集行 upsert 进注册表 datasets 表（best-effort，#105）。

    懒 import RegistryDB、用完即 close（不占连接）；任何失败（依赖缺失/
    写库异常）只 warning 并返回 False，绝不阻塞物化主路径——注册表是
    观测索引，manifest 文件才是事实源。
    """
    import logging

    try:
        from rfauto.infra.db import RegistryDB

        db = RegistryDB()
        try:
            db.upsert_dataset(
                name=str(name),
                manifest_path=str(manifest_path),
                format=str(fmt or ""),
                visibility=str(visibility or "private"),
                n_rows=None if n_rows is None else int(n_rows),
            )
        finally:
            db.close()
        return True
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "dataset registry sync failed for %s: %s", name, exc)
        return False
