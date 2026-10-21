"""dataset_service.query —— DuckDB 直查面（谓词下推/列裁剪/csv 导出）。

自 dataset_service.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原节「DuckDB 直查」逐字节搬迁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    DEFAULT_OUT_DIR,
    HDF5_NAME,
    PARQUET_NAME,
    _import_duckdb,
    _validate_columns,
    _validate_dataset_name,
    _validate_where,
)
from .io import (
    _dataset_format,
    _load_manifest_yaml,
    _read_points_hdf5,
)

# DuckDB 直查
# ---------------------------------------------------------------------------

def query_dataset(
    name: str,
    where: str | None = None,
    columns: list[str] | None = None,
    *,
    limit: int = 100,
    model: str | None = None,
    study_name: str | None = None,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    order_by: str | None = None,
    order: str = "desc",
    offset: int = 0,
    out_fmt: str = "json",
) -> dict[str, Any]:
    """DuckDB 直查 Parquet 数据集（谓词下推/列裁剪）。

    where 是单条 SQL WHERE 片段（如 ``cost < 0.1 and model = 'mline'``），
    经白名单校验后以 ``WHERE (片段)`` 形式拼入；columns 做标识符校验后
    实现列裁剪。model/study_name 是等值过滤便捷参：以 DuckDB 位置参数
    （``?`` 占位）安全下推——**值永不拼进 SQL 文本**（防注入面不倒退），
    且在 LIMIT 之前生效（E11 未尽③：collect 按族过滤时不再被过滤前
    截断漏样本）。返回 {ok, rows, n_rows, columns, dataset, where,
    filters, limit}。

    SN-13（W6-A，2026-10-06）增量（全部可选，缺省零行为变化）：
    - ``order_by``：排序列名（标识符校验；列存在性执行期校验，未知列
      ok=False 如实报错）；``order``：``asc``|``desc``（缺省 desc）。
    - ``offset``：分页偏移（>=0，在 LIMIT 前生效）。
    - ``out_fmt``：``json``（缺省，rows 键不变）|``csv``（额外给 ``csv`` 键：
      RFC4180 文本，表头+数据行；rows 仍带便于双消费）。信封 ``format``
      键保持数据集存储格式（parquet/hdf5）不变。
    - ``total_rows``：过滤后（LIMIT/OFFSET 前）总行数（治 #369
      "n_rows=limit 截断被误当总数"复发——总数语义显式单列一键）。
    """
    try:
        name = _validate_dataset_name(name)
        where_sql = _validate_where(where) if where is not None else None
        cols = _validate_columns(columns)
        limit_i = int(limit)
        if limit_i < 1:
            raise ValueError(f"limit 必须 >= 1，收到 {limit!r}")
        offset_i = int(offset)
        if offset_i < 0:
            raise ValueError(f"offset 必须 >= 0，收到 {offset!r}")
        if order not in ("asc", "desc"):
            raise ValueError(f"order 只允许 asc|desc，收到 {order!r}")
        if out_fmt not in ("json", "csv"):
            raise ValueError(f"out_fmt 只允许 json|csv，收到 {out_fmt!r}")
        if order_by is not None:
            order_col = _validate_columns([order_by])
            order_col_name = order_col[0]
        else:
            order_col_name = None
    except (ValueError, TypeError) as exc:
        return error_envelope([str(exc)])

    # 等值谓词下推准备：值只进参数绑定不进 SQL；空串视为未过滤；
    # 非 str 拒绝（防静默 str() 成与列值永不相等的垃圾字面量）
    filters: dict[str, str] = {}
    for key, val in (("model", model), ("study_name", study_name)):
        if val is None:
            continue
        if not isinstance(val, str):
            return error_envelope(
                [
                f"{key} 必须是 str 或 None，收到 {type(val).__name__}"],
            )
        if val:
            filters[key] = val

    dataset_dir = Path(out_dir) / name
    manifest = _load_manifest_yaml(dataset_dir)
    fmt = _dataset_format(manifest)
    points_path = dataset_dir / (PARQUET_NAME if fmt == "parquet" else HDF5_NAME)
    if not points_path.exists():
        # 无 manifest 的裸目录仍可查（test_rest_api 惯例/旧资产）：另一格式
        # 文件在则改走它；两格式都缺才判不存在
        alt = dataset_dir / (HDF5_NAME if fmt == "parquet" else PARQUET_NAME)
        if manifest is None and alt.exists():
            points_path = alt
            fmt = "hdf5" if fmt == "parquet" else "parquet"
        else:
            return error_envelope(
                [
                f"数据集不存在: {name}（缺 {points_path}，先 materialize）"],
            )

    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return error_envelope([str(exc)])

    # hdf5：经 h5py 重建 Arrow 表并注册为 DuckDB 视图，where/filters/limit
    # 与 Parquet 路径共用同一 SQL 管线（防注入面不分叉）
    arrow_table: Any = None
    if fmt == "hdf5":
        try:
            arrow_table = _read_points_hdf5(points_path, None)
        except RuntimeError as exc:
            return error_envelope([str(exc)])
        except Exception:
            return error_envelope(
                [
                "HDF5 点级数据读取失败（文件损坏或列缺失；原始错误不透出）"],
            )
        source_sql = "dataset_points"
    else:
        source_sql = ("read_parquet("
                      f"'{str(points_path).replace(chr(39), chr(39) * 2)}')")

    select_list = (", ".join(f'"{c}"' for c in cols) if cols else "*")
    sql = f"SELECT {select_list} FROM {source_sql}"
    bind_params: list[Any] = []
    where_parts: list[str] = []
    if filters:
        # 列名是 DATASET_SCHEMA 固定白名单，值走 ? 参数绑定
        where_parts.append("(" + " AND ".join(f"{k} = ?" for k in filters) + ")")
        bind_params.extend(filters.values())
    if where_sql:
        where_parts.append(f"({where_sql})")
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    # SN-13：总数语义（过滤后、LIMIT/OFFSET 前的行数；#369 复发治理）。
    # count 查询与数据查询共享同一 WHERE/filters 管线，值同样只进 ? 绑定。
    count_sql = f"SELECT count(*) FROM {source_sql}"
    if where_parts:
        count_sql += " WHERE " + " AND ".join(where_parts)

    if order_col_name is not None:
        # 列名经 _validate_columns 标识符白名单，方向是 asc|desc 枚举——
        # 二者都不进自由 SQL 文本面
        sql += f' ORDER BY "{order_col_name}" {order}'
    sql += f" LIMIT {limit_i} OFFSET {offset_i}"

    con = duckdb.connect()
    try:
        if arrow_table is not None:
            con.register("dataset_points", arrow_table)
        cur = con.execute(sql, bind_params) if bind_params else con.execute(sql)
        col_names = [d[0] for d in cur.description]
        rows = [dict(zip(col_names, r, strict=False)) for r in cur.fetchall()]
        total_rows = int((con.execute(count_sql, bind_params).fetchone()
                          or [0])[0])
    except Exception:  # duckdb.Error 及其子类：语法/缺列/表函数越权等查询期错误
        # 错误文案统一收敛，不透传引擎原始消息：parquet_scan 等变体会把
        # 目标路径织进 IO Error 文本，回传即存在性 oracle（任意路径探测）。
        # "sql" 是调用方自身输入（含 where 原文）的回显，非引擎内部信息，
        # 保留供归因。
        return error_envelope(
            [
            "查询执行失败: where 表达式被拒绝（仅允许对本数据集列的"
            "比较/逻辑表达式；原始引擎错误不透出）"],
            sql=sql,
        )
    finally:
        con.close()

    out = ok_envelope(
        dataset=name,
        format=fmt,
        rows=rows,
        n_rows=len(rows),
        total_rows=total_rows,
        offset=offset_i,
        order_by=order_col_name,
        order=order,
        columns=col_names,
        where=where_sql or "",
        filters=filters,
        limit=limit_i,
    )
    if out_fmt == "csv":
        out["csv"] = _rows_to_csv(col_names, rows)
    return out


def _rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """行字典 → RFC4180 CSV 文本（SN-13 --format csv 导出面；确定性渲染）。

    空值渲染空串；数值 str() 直转；含引号/逗号/换行的字段按 RFC4180 双写
    引号包裹。表头恒为查询列序（col_names）。
    """
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            ["" if row.get(c) is None else row.get(c) for c in columns])
    return buf.getvalue()
